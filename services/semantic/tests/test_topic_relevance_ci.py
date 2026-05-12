from __future__ import annotations

import builtins
import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

SCRIPT_PATH = ROOT_DIR / "scripts" / "analyze_topic_relevance_ci.py"
SPEC = importlib.util.spec_from_file_location("topic_relevance_ci_test_module", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Failed to load topic relevance CI module from {SCRIPT_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_bootstrap_paired_ci_detects_positive_delta() -> None:
    baseline = MODULE.np.asarray([0.0, 0.2, 0.4, 0.6])
    run = MODULE.np.asarray([0.2, 0.4, 0.6, 0.8])

    result = MODULE.bootstrap_paired_ci(baseline, run, n_bootstrap=200, seed=7)

    assert result["delta_mean"] == 0.2
    assert result["delta_ci_low"] > 0.0
    assert result["p_delta_gt_0"] == 1.0


def test_align_metric_values_uses_intersection_by_query_id() -> None:
    rows = [
        {"run": "baseline", "query_id": "q1", "nDCG@10": 0.1, "split": "all"},
        {"run": "baseline", "query_id": "q2", "nDCG@10": 0.2, "split": "all"},
        {"run": "candidate", "query_id": "q2", "nDCG@10": 0.5, "split": "all"},
        {"run": "candidate", "query_id": "q3", "nDCG@10": 0.9, "split": "all"},
    ]

    query_ids, baseline, run = MODULE.align_metric_values(rows, baseline="baseline", run="candidate", metric="nDCG@10")

    assert query_ids == ["q2"]
    assert baseline.tolist() == [0.2]
    assert run.tolist() == [0.5]


def test_filter_rows_by_split_errors_for_missing_split() -> None:
    try:
        MODULE.filter_rows_by_split([{"split": "all"}], "holdout")
    except RuntimeError as exc:
        assert "holdout" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for missing split")


def test_select_default_run_prefers_rerank_grid_best_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report_dir = Path(tmp)
        with open(report_dir / "rerank_grid.json", "w", encoding="utf-8") as file_obj:
            json.dump({"best_run": "rerank_selected"}, file_obj)

        assert MODULE.select_default_run(report_dir) == "rerank_selected"


def test_delta_values_by_metric_aligns_query_pairs() -> None:
    rows = [
        {"run": "baseline", "query_id": "q2", "split": "all", "nDCG@10": 0.2},
        {"run": "rerank_x", "query_id": "q1", "split": "all", "nDCG@10": 0.5},
        {"run": "baseline", "query_id": "q1", "split": "all", "nDCG@10": 0.4},
        {"run": "rerank_x", "query_id": "q2", "split": "all", "nDCG@10": 0.1},
    ]

    deltas = MODULE.delta_values_by_metric(
        rows,
        baseline="baseline",
        run="rerank_x",
        metrics=["nDCG@10"],
        split="all",
    )

    assert MODULE.np.allclose(deltas["nDCG@10"], MODULE.np.asarray([0.1, -0.1]))


def test_write_plots_gracefully_skips_without_matplotlib() -> None:
    rows = [
        {
            "metric": "nDCG@10",
            "baseline_mean": 0.7,
            "baseline_ci_low": 0.6,
            "baseline_ci_high": 0.8,
            "run_mean": 0.75,
            "run_ci_low": 0.65,
            "run_ci_high": 0.85,
            "delta_mean": 0.05,
            "delta_ci_low": 0.01,
            "delta_ci_high": 0.09,
        }
    ]
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "matplotlib.pyplot":
            raise ImportError("missing matplotlib")
        return real_import(name, *args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        builtins.__import__ = fake_import
        try:
            assert MODULE.write_plots(Path(tmp), rows, {"nDCG@10": MODULE.np.asarray([0.05])}) is False
        finally:
            builtins.__import__ = real_import

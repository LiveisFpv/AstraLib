#!/usr/bin/env python3
"""Build bootstrap confidence intervals for OpenAlex topical relevance runs."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_METRICS = ("nDCG@10", "Precision@10", "Precision@5", "MRR@10")


def resolve_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT_DIR / candidate


def parse_metric_list(raw: str) -> list[str]:
    metrics = [item.strip() for item in raw.split(",") if item.strip()]
    if not metrics:
        raise ValueError("--metrics cannot be empty")
    return metrics


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise RuntimeError(f"Missing per-query metrics file: {path}")

    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig") as file_obj:
        for line in file_obj:
            if not line.strip():
                continue
            rows.append(json.loads(line))

    if not rows:
        raise RuntimeError(f"No per-query metrics found in {path}")

    return rows


def load_metrics_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with open(path, "r", newline="", encoding="utf-8-sig") as file_obj:
        return list(csv.DictReader(file_obj))


def select_default_run(report_dir: Path, *, preferred_metric: str = "nDCG@10") -> str:
    grid_path = report_dir / "rerank_grid.json"

    if grid_path.exists():
        with open(grid_path, "r", encoding="utf-8-sig") as file_obj:
            payload = json.load(file_obj)

        best_run = str(payload.get("best_run") or "")
        if best_run:
            return best_run

    rows = load_metrics_csv(report_dir / "metrics.csv")
    candidates = [row for row in rows if str(row.get("run") or "").startswith("rerank_")]

    if not candidates:
        raise RuntimeError("Could not infer target run: no rerank runs found in metrics.csv")

    metric = preferred_metric if preferred_metric in candidates[0] else "nDCG@5"
    return max(candidates, key=lambda row: float(row.get(metric) or 0.0))["run"]


def filter_rows_by_split(rows: Sequence[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    if split == "all":
        return list(rows)

    filtered = [row for row in rows if row.get("split") == split]

    if not filtered:
        raise RuntimeError(f"No per-query metrics rows found for split '{split}'")

    return filtered


def align_metric_values(
    rows: Sequence[dict[str, Any]],
    *,
    baseline: str,
    run: str,
    metric: str,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    by_run: dict[str, dict[str, dict[str, Any]]] = {}

    for row in rows:
        value = row.get(metric)
        if value is None:
            continue

        run_name = str(row.get("run"))
        query_id = str(row.get("query_id"))
        by_run.setdefault(run_name, {})[query_id] = row

    baseline_rows = by_run.get(baseline, {})
    run_rows = by_run.get(run, {})

    query_ids = sorted(set(baseline_rows) & set(run_rows))

    if not query_ids:
        raise RuntimeError(
            f"No aligned query rows for baseline='{baseline}', run='{run}', metric='{metric}'"
        )

    baseline_values = np.asarray(
        [float(baseline_rows[query_id][metric]) for query_id in query_ids],
        dtype=np.float64,
    )
    run_values = np.asarray(
        [float(run_rows[query_id][metric]) for query_id in query_ids],
        dtype=np.float64,
    )

    return query_ids, baseline_values, run_values


def bootstrap_paired_ci(
    baseline_values: np.ndarray,
    run_values: np.ndarray,
    *,
    n_bootstrap: int,
    seed: int,
) -> dict[str, Any]:
    if len(baseline_values) != len(run_values):
        raise ValueError("Baseline and run arrays must have the same length")
    if len(baseline_values) == 0:
        raise ValueError("Cannot bootstrap empty arrays")
    if n_bootstrap < 1:
        raise ValueError("--bootstrap must be >= 1")

    rng = np.random.default_rng(seed)
    n = len(baseline_values)

    baseline_means = np.empty(n_bootstrap, dtype=np.float64)
    run_means = np.empty(n_bootstrap, dtype=np.float64)
    delta_means = np.empty(n_bootstrap, dtype=np.float64)
    relative_delta_percent_means = np.empty(n_bootstrap, dtype=np.float64)

    for idx in range(n_bootstrap):
        sample_idx = rng.integers(0, n, size=n)

        baseline_mean = float(baseline_values[sample_idx].mean())
        run_mean = float(run_values[sample_idx].mean())
        delta_mean = run_mean - baseline_mean

        baseline_means[idx] = baseline_mean
        run_means[idx] = run_mean
        delta_means[idx] = delta_mean

        if baseline_mean != 0.0:
            relative_delta_percent_means[idx] = (delta_mean / baseline_mean) * 100.0
        else:
            relative_delta_percent_means[idx] = np.nan

    baseline_mean = float(baseline_values.mean())
    run_mean = float(run_values.mean())
    delta_mean = run_mean - baseline_mean

    if baseline_mean != 0.0:
        relative_delta_percent_mean = (delta_mean / baseline_mean) * 100.0
    else:
        relative_delta_percent_mean = float("nan")

    valid_relative = relative_delta_percent_means[~np.isnan(relative_delta_percent_means)]

    if len(valid_relative) == 0:
        raise RuntimeError("All relative bootstrap estimates are NaN")

    delta_ci_low = float(np.percentile(delta_means, 2.5))
    delta_ci_high = float(np.percentile(delta_means, 97.5))

    relative_delta_percent_ci_low = float(np.percentile(valid_relative, 2.5))
    relative_delta_percent_ci_high = float(np.percentile(valid_relative, 97.5))

    return {
        "queries": int(n),

        "baseline_mean": baseline_mean,
        "baseline_ci_low": float(np.percentile(baseline_means, 2.5)),
        "baseline_ci_high": float(np.percentile(baseline_means, 97.5)),

        "run_mean": run_mean,
        "run_ci_low": float(np.percentile(run_means, 2.5)),
        "run_ci_high": float(np.percentile(run_means, 97.5)),

        "delta_mean": float(delta_mean),
        "delta_ci_low": delta_ci_low,
        "delta_ci_high": delta_ci_high,

        "relative_delta_percent_mean": float(relative_delta_percent_mean),
        "relative_delta_percent_ci_low": relative_delta_percent_ci_low,
        "relative_delta_percent_ci_high": relative_delta_percent_ci_high,

        # Это НЕ p-value. Это доля bootstrap-выборок с положительным приростом.
        "positive_bootstrap_fraction": float(np.mean(delta_means > 0.0)),

        # Для интерпретации устойчивости абсолютного прироста.
        "ci_excludes_zero": bool(delta_ci_low > 0.0 or delta_ci_high < 0.0),
    }


def analyze_metrics(
    rows: Sequence[dict[str, Any]],
    *,
    baseline: str,
    run: str,
    metrics: Sequence[str],
    split: str,
    n_bootstrap: int,
    seed: int,
) -> list[dict[str, Any]]:
    filtered = filter_rows_by_split(rows, split)
    results: list[dict[str, Any]] = []

    for offset, metric in enumerate(metrics):
        _, baseline_values, run_values = align_metric_values(
            filtered,
            baseline=baseline,
            run=run,
            metric=metric,
        )

        stats = bootstrap_paired_ci(
            baseline_values,
            run_values,
            n_bootstrap=n_bootstrap,
            seed=seed + offset,
        )

        results.append(
            {
                "metric": metric,
                "split": split,
                "baseline": baseline,
                "run": run,
                **stats,
            }
        )

    return results


def delta_values_by_metric(
    rows: Sequence[dict[str, Any]],
    *,
    baseline: str,
    run: str,
    metrics: Sequence[str],
    split: str,
) -> dict[str, np.ndarray]:
    filtered = filter_rows_by_split(rows, split)
    deltas: dict[str, np.ndarray] = {}

    for metric in metrics:
        _, baseline_values, run_values = align_metric_values(
            filtered,
            baseline=baseline,
            run=run,
            metric=metric,
        )
        deltas[metric] = run_values - baseline_values

    return deltas


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fieldnames = [
        "metric",
        "split",
        "baseline",
        "run",
        "queries",

        "baseline_mean",
        "baseline_ci_low",
        "baseline_ci_high",

        "run_mean",
        "run_ci_low",
        "run_ci_high",

        "delta_mean",
        "delta_ci_low",
        "delta_ci_high",

        "relative_delta_percent_mean",
        "relative_delta_percent_ci_low",
        "relative_delta_percent_ci_high",

        "positive_bootstrap_fraction",
        "ci_excludes_zero",
    ]

    with open(path, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: Path, rows: Sequence[dict[str, Any]], params: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(
            {
                "params": params,
                "results": list(rows),
            },
            file_obj,
            ensure_ascii=False,
            indent=2,
        )


def write_markdown(
    path: Path,
    rows: Sequence[dict[str, Any]],
    params: dict[str, Any],
    *,
    plots_written: bool,
) -> None:
    lines = [
        "# Bootstrap Confidence Intervals",
        "",
        f"- baseline: `{params['baseline']}`",
        f"- run: `{params['run']}`",
        f"- split: `{params['split']}`",
        f"- bootstrap samples: `{params['bootstrap']}`",
        "",
        "| Metric | Baseline | Run | Δ abs | 95% CI Δ abs | Δ rel, % | 95% CI Δ rel, % | CI excludes 0 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for row in rows:
        lines.append(
            f"| {row['metric']} | "
            f"{row['baseline_mean']:.6f} | "
            f"{row['run_mean']:.6f} | "
            f"{row['delta_mean']:+.6f} | "
            f"[{row['delta_ci_low']:+.6f}; {row['delta_ci_high']:+.6f}] | "
            f"{row['relative_delta_percent_mean']:+.2f}% | "
            f"[{row['relative_delta_percent_ci_low']:+.2f}%; "
            f"{row['relative_delta_percent_ci_high']:+.2f}%] | "
            f"{'yes' if row.get('ci_excludes_zero') else 'no'} |"
        )

    if plots_written:
        lines.extend(
            [
                "",
                "## Plots",
                "",
                "- `bootstrap_ci_delta.png`",
                "- `bootstrap_ci_delta.svg`",
                "- `bootstrap_ci_delta.pdf`",
                "- `per_query_sorted_delta.png`",
                "- `per_query_sorted_delta.svg`",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Plots were not generated because `matplotlib` is not available.",
            ]
        )

    with open(path, "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(lines) + "\n")


def write_plots(
    report_dir: Path,
    rows: Sequence[dict[str, Any]],
    delta_by_metric: dict[str, np.ndarray],
) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)

        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter

    except ImportError:
        print("matplotlib is not installed; skipped plots.", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"matplotlib could not be initialized; skipped plots: {exc}", file=sys.stderr)
        return False

    sorted_rows = sorted(
        rows,
        key=lambda row: float(row["relative_delta_percent_mean"]),
        reverse=True,
    )

    metrics = [str(row["metric"]) for row in sorted_rows]

    delta = np.asarray(
        [float(row["relative_delta_percent_mean"]) for row in sorted_rows],
        dtype=np.float64,
    )
    delta_low = np.asarray(
        [float(row["relative_delta_percent_ci_low"]) for row in sorted_rows],
        dtype=np.float64,
    )
    delta_high = np.asarray(
        [float(row["relative_delta_percent_ci_high"]) for row in sorted_rows],
        dtype=np.float64,
    )

    delta_xerr = np.vstack([delta - delta_low, delta_high - delta])
    y = np.arange(len(metrics))

    fig, ax = plt.subplots(
        figsize=(7.4, max(3.2, len(metrics) * 0.55 + 1.0)),
        dpi=300,
    )
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    accent_color = "#1F77B4"

    ax.errorbar(
        delta,
        y,
        xerr=delta_xerr,
        fmt="o",
        color=accent_color,
        ecolor=accent_color,
        capsize=3,
        elinewidth=1.3,
        markersize=5.5,
    )

    ax.axvline(0.0, color="#8A8A8A", linewidth=0.9, linestyle="--")

    ax.set_yticks(y)
    ax.set_yticklabels(metrics)
    ax.invert_yaxis()

    ax.set_xlabel("Относительный прирост относительно baseline, %")
    ax.set_title("")

    x_min = float(min(delta_low.min(), 0.0))
    x_max = float(max(delta_high.max(), 0.0))
    padding = max((x_max - x_min) * 0.08, 0.15)

    ax.set_xlim(x_min - padding, x_max + padding * 2.4)

    for high_value, x_value, y_value in zip(delta_high, delta, y, strict=True):
        value_text = f"{x_value:+.2f}".replace(".", ",")
        label = f"{value_text}%"

        ax.text(
            high_value + padding * 0.35,
            y_value,
            label,
            va="center",
            ha="left",
            fontsize=9,
            color="#333333",
        )

    ax.grid(axis="x", color="#D8D8D8", linewidth=0.6)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#C8C8C8")
    ax.spines["bottom"].set_color("#C8C8C8")

    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda x, _: f"{x:.1f}".replace(".", ","))
    )

    fig.tight_layout()

    fig.savefig(
        report_dir / "bootstrap_ci_delta.png",
        dpi=300,
        facecolor="white",
        bbox_inches="tight",
    )
    fig.savefig(
        report_dir / "bootstrap_ci_delta.svg",
        facecolor="white",
        bbox_inches="tight",
    )
    fig.savefig(
        report_dir / "bootstrap_ci_delta.pdf",
        facecolor="white",
        bbox_inches="tight",
    )

    plt.close(fig)

    # Диагностический график по отдельным запросам.
    # Он показывает абсолютный прирост по запросам, а не относительный процент.
    # В статью его обычно вставлять не нужно.
    fig, ax = plt.subplots(figsize=(7.4, 4.2), dpi=300)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    for metric in metrics:
        metric_delta = delta_by_metric.get(metric)
        if metric_delta is None:
            continue

        sorted_delta = np.sort(metric_delta)
        x = np.arange(1, len(sorted_delta) + 1)

        ax.plot(x, sorted_delta, linewidth=1.4, label=metric)

    ax.axhline(0.0, color="#8A8A8A", linewidth=0.9, linestyle="--")
    ax.set_xlabel("Запросы, отсортированные по индивидуальному приросту")
    ax.set_ylabel("Абсолютный прирост относительно baseline")
    ax.set_title("Распределение прироста по отдельным запросам")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)

    fig.tight_layout()

    fig.savefig(
        report_dir / "per_query_sorted_delta.png",
        dpi=300,
        facecolor="white",
        bbox_inches="tight",
    )
    fig.savefig(
        report_dir / "per_query_sorted_delta.svg",
        facecolor="white",
        bbox_inches="tight",
    )

    plt.close(fig)

    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--baseline", default="baseline")
    parser.add_argument("--run")
    parser.add_argument("--metrics", default=",".join(DEFAULT_METRICS))
    parser.add_argument("--split", choices=["all", "tune", "holdout"], default="all")
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    if args.bootstrap < 1:
        raise ValueError("--bootstrap must be >= 1")

    return args


def main() -> None:
    args = parse_args()

    report_dir = resolve_path(args.report_dir)
    metrics = parse_metric_list(args.metrics)

    run = args.run or select_default_run(report_dir, preferred_metric=metrics[0])

    rows = load_jsonl(report_dir / "per_query_metrics.jsonl")

    delta_by_metric = delta_values_by_metric(
        rows,
        baseline=args.baseline,
        run=run,
        metrics=metrics,
        split=args.split,
    )

    results = analyze_metrics(
        rows,
        baseline=args.baseline,
        run=run,
        metrics=metrics,
        split=args.split,
        n_bootstrap=args.bootstrap,
        seed=args.seed,
    )

    params = {
        "report_dir": str(report_dir),
        "baseline": args.baseline,
        "run": run,
        "metrics": metrics,
        "split": args.split,
        "bootstrap": args.bootstrap,
        "seed": args.seed,
    }

    write_csv(report_dir / "bootstrap_ci.csv", results)
    write_json(report_dir / "bootstrap_ci.json", results, params)

    legacy_scores_plot = report_dir / "bootstrap_ci_scores.png"
    if legacy_scores_plot.exists():
        legacy_scores_plot.unlink()

    plots_written = write_plots(report_dir, results, delta_by_metric)

    write_markdown(
        report_dir / "bootstrap_report.md",
        results,
        params,
        plots_written=plots_written,
    )

    print(f"Wrote bootstrap CI artifacts to {report_dir}")


if __name__ == "__main__":
    main()
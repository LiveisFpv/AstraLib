from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT_DIR / "scripts" / "eval_scidocs_citation.py"
SPEC = importlib.util.spec_from_file_location("eval_scidocs_citation_test_module", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Failed to load eval script from {SCRIPT_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

evaluate_run = MODULE.evaluate_run
remove_qrel_edges = MODULE.remove_qrel_edges
build_neighbor_means = MODULE.build_neighbor_means
load_edges_from_file = MODULE.load_edges_from_file


def test_evaluate_run_computes_core_metrics() -> None:
    qrels = {
        "q1": {"d1": 1, "d2": 1, "d3": 0},
        "q2": {"d4": 1},
    }
    ranked = [
        ["d3", "d2", "d9", "d1"],
        ["d8", "d4", "d1"],
    ]

    metrics = evaluate_run(qrels=qrels, query_ids=["q1", "q2"], ranked_doc_ids=ranked)

    assert metrics["Precision@1"] == pytest.approx(0.0)
    assert metrics["Precision@5"] == pytest.approx(0.3)
    assert metrics["Recall@10"] == pytest.approx(1.0)
    assert metrics["MRR@10"] == pytest.approx(0.5)
    assert metrics["MAP@100"] == pytest.approx(0.5)
    assert 0.0 < metrics["nDCG@10"] < 1.0


def test_remove_qrel_edges_filters_positive_test_labels_only() -> None:
    edges = [
        ("q1", "d1"),
        ("q1", "d2"),
        ("q1", "d2"),
        ("q2", "d3"),
    ]
    qrels = {
        "q1": {"d1": 1, "d2": 0},
        "q2": {"d9": 1},
    }

    filtered, removed = remove_qrel_edges(edges, qrels)

    assert removed == 1
    assert filtered == [("q1", "d2"), ("q2", "d3")]


def test_build_neighbor_means_uses_only_in_corpus_edges() -> None:
    doc_ids = ["a", "b", "c"]
    embeddings = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
        ],
        dtype=np.float32,
    )
    edges = [("a", "b"), ("a", "missing"), ("b", "c")]

    out1, in1, out2, in2 = build_neighbor_means(
        doc_ids=doc_ids,
        embeddings=embeddings,
        edges=edges,
    )

    assert np.allclose(out1[0], embeddings[1])
    assert np.allclose(in1[1], embeddings[0])
    assert np.allclose(out2[0], embeddings[2])
    assert np.allclose(in2[2], embeddings[0])


def test_load_edges_from_scidocs_metadata_mapping(tmp_path: Path) -> None:
    metadata = {
        "paper-a": {
            "references": ["paper-b", {"paper_id": "paper-c"}],
            "cited_by": ["paper-d"],
        }
    }
    path = tmp_path / "paper_metadata_view_cite_read.json"
    path.write_text(__import__("json").dumps(metadata), encoding="utf-8")

    edges = load_edges_from_file(path)

    assert ("paper-a", "paper-b") in edges
    assert ("paper-a", "paper-c") in edges
    assert ("paper-d", "paper-a") in edges


def test_load_edges_from_jsonl_with_json_extension(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"
    path.write_text(
        "\n".join(
            [
                __import__("json").dumps({"paper_id": "a", "references": ["b"]}),
                __import__("json").dumps({"paper_id": "c", "cited_by": ["d"]}),
            ]
        ),
        encoding="utf-8",
    )

    edges = load_edges_from_file(path)

    assert ("a", "b") in edges
    assert ("d", "c") in edges

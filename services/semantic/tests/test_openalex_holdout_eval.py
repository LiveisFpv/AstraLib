from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

SCRIPT_PATH = ROOT_DIR / "scripts" / "eval_openalex_citation_holdout.py"
SPEC = importlib.util.spec_from_file_location("openalex_holdout_eval_test_module", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Failed to load OpenAlex holdout eval module from {SCRIPT_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CorpusData = MODULE.CorpusData
filter_ranked_indices = MODULE.filter_ranked_indices
parse_referenced_edges = MODULE.parse_referenced_edges
select_queries = MODULE.select_queries
split_pipe_ids = MODULE.split_pipe_ids
stable_edge_is_test = MODULE.stable_edge_is_test


def test_split_pipe_ids_normalizes_and_deduplicates_openalex_ids() -> None:
    assert split_pipe_ids("W1 | https://openalex.org/W2 |  | http://openalex.org/W2 | W3") == [
        "https://openalex.org/W1",
        "https://openalex.org/W2",
        "https://openalex.org/W3",
    ]


def test_parse_referenced_edges_removes_self_edges_and_splits_without_leakage() -> None:
    id_to_row = {
        "https://openalex.org/W1": 0,
        "https://openalex.org/W2": 1,
        "https://openalex.org/W3": 2,
    }
    rows = [
        ("https://openalex.org/W1", "https://openalex.org/W1 | https://openalex.org/W2 | https://openalex.org/W3"),
        ("https://openalex.org/W2", "https://openalex.org/W3"),
    ]

    split_a = parse_referenced_edges(rows, id_to_row, edge_test_frac=0.5, split_seed=7)
    split_b = parse_referenced_edges(rows, id_to_row, edge_test_frac=0.5, split_seed=7)

    assert split_a.raw_edges == 4
    assert split_a.self_edges_removed == 1
    assert split_a.edges_in_corpus == 3
    assert np.array_equal(split_a.train_edges, split_b.train_edges)
    assert np.array_equal(split_a.test_edges, split_b.test_edges)

    train = {tuple(edge) for edge in split_a.train_edges.tolist()}
    test = {tuple(edge) for edge in split_a.test_edges.tolist()}
    assert train.isdisjoint(test)
    assert (0, 0) not in train
    assert (0, 0) not in test


def test_stable_edge_is_test_is_deterministic() -> None:
    first = stable_edge_is_test("W1", "W2", test_frac=0.2, seed=42)
    second = stable_edge_is_test("W1", "W2", test_frac=0.2, seed=42)
    assert first == second


def test_select_queries_keeps_only_documents_with_withheld_positives() -> None:
    corpus = CorpusData(
        doc_ids=["https://openalex.org/W1", "https://openalex.org/W2", "https://openalex.org/W3"],
        titles=["Query title", "Target", ""],
        abstracts=["Abstract", "Target abstract", "No title"],
        languages=["en", "en", "en"],
    )
    test_edges = np.asarray([[0, 1], [2, 1]], dtype=np.int32)

    query_set = select_queries(
        corpus=corpus,
        test_edges=test_edges,
        query_limit=None,
        query_field="title",
        split_seed=1,
    )

    assert query_set.query_ids == ["https://openalex.org/W1"]
    assert query_set.query_texts == ["Query title"]
    assert query_set.qrels["https://openalex.org/W1"] == {"https://openalex.org/W2": 1}


def test_filter_ranked_indices_excludes_self_document() -> None:
    indices = np.asarray([[3, 1, 2, 4], [0, 2, 1, 3]], dtype=np.int64)
    filtered = filter_ranked_indices(indices, query_doc_rows=[3, 2], top_k=3)
    assert filtered == [[1, 2, 4], [0, 1, 3]]


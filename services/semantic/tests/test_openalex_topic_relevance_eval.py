from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

SCRIPT_PATH = ROOT_DIR / "scripts" / "eval_openalex_topic_relevance.py"
SPEC = importlib.util.spec_from_file_location("openalex_topic_relevance_eval_test_module", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Failed to load OpenAlex topic relevance eval module from {SCRIPT_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

DocMeta = MODULE.DocMeta
TopicQuery = MODULE.TopicQuery
build_candidate_union = MODULE.build_candidate_union
evaluate_ranked = MODULE.evaluate_ranked
extract_topics_from_row = MODULE.extract_topics_from_row
parse_judge_json = MODULE.parse_judge_json
rerank_by_score_blend = MODULE.rerank_by_score_blend
run_name_for_alpha = MODULE.run_name_for_alpha
select_best_run_by_metric = MODULE.select_best_run_by_metric
select_topic_queries = MODULE.select_topic_queries


def test_extract_topics_from_pipe_separated_metadata_deduplicates() -> None:
    row = {
        "topics_names": "Graph Neural Networks | Machine Learning",
        "keywords_names": "machine learning | Citation Recommendation",
        "concepts_names": "Data | Bibliometrics",
    }

    assert extract_topics_from_row(row) == [
        ("graph neural networks", "topics_names"),
        ("machine learning", "topics_names"),
        ("citation recommendation", "keywords_names"),
        ("bibliometrics", "concepts_names"),
    ]


def test_select_topic_queries_is_deterministic_and_filters_df() -> None:
    counts = MODULE.Counter({"a topic": 10, "b topic": 3, "c topic": 20})
    sources = {"a topic": "topics_names", "b topic": "keywords_names", "c topic": "concepts_names"}

    first = select_topic_queries(counts, sources, query_limit=2, seed=42, min_df=5, max_df=None)
    second = select_topic_queries(counts, sources, query_limit=2, seed=42, min_df=5, max_df=None)

    assert [item.text for item in first] == [item.text for item in second]
    assert {item.text for item in first} <= {"a topic", "c topic"}


def test_build_candidate_union_deduplicates_and_is_deterministic() -> None:
    baseline = [[1, 2, 3], [4, 5]]
    citation = [[3, 4, 1], [5, 6]]
    rerank = [[7, 1], [6, 8]]

    first = build_candidate_union(baseline, citation, rerank, candidate_top_k=3, seed=7, query_texts=["q1", "q2"])
    second = build_candidate_union(baseline, citation, rerank, candidate_top_k=3, seed=7, query_texts=["q1", "q2"])

    assert first == second
    assert [set(row) for row in first] == [{1, 2, 3, 4, 7}, {4, 5, 6, 8}]


def test_rerank_alpha_zero_preserves_baseline_order() -> None:
    ranked = [[1, 2, 3]]
    semantic_scores = [[0.9, 0.8, 0.7]]
    citation_scores = [[0.0, 10.0, 20.0]]

    assert rerank_by_score_blend(
        semantic_ranked=ranked,
        semantic_scores=semantic_scores,
        citation_scores=citation_scores,
        alpha=0.0,
    ) == ranked


def test_rerank_positive_alpha_changes_order_by_citation_score() -> None:
    ranked = [[1, 2, 3]]
    semantic_scores = [[0.9, 0.8, 0.7]]
    citation_scores = [[0.0, 10.0, 20.0]]

    assert rerank_by_score_blend(
        semantic_ranked=ranked,
        semantic_scores=semantic_scores,
        citation_scores=citation_scores,
        alpha=0.1,
    ) == [[3, 2, 1]]


def test_run_name_for_alpha_is_stable_for_file_friendly_names() -> None:
    assert run_name_for_alpha(0.05) == "rerank_alpha_0p05"


def test_select_best_run_prefers_ndcg10_and_falls_back_to_ndcg5() -> None:
    metrics = {
        "baseline": {"nDCG@5": 0.3},
        "rerank_alpha_0": {"nDCG@5": 0.4},
        "rerank_alpha_0p1": {"nDCG@5": 0.5},
    }

    assert select_best_run_by_metric(["rerank_alpha_0", "rerank_alpha_0p1"], metrics) == (
        "rerank_alpha_0p1",
        "nDCG@5",
    )

    metrics["rerank_alpha_0"]["nDCG@10"] = 0.7
    metrics["rerank_alpha_0p1"]["nDCG@10"] = 0.6
    assert select_best_run_by_metric(["rerank_alpha_0", "rerank_alpha_0p1"], metrics) == (
        "rerank_alpha_0",
        "nDCG@10",
    )


def test_parse_judge_json_accepts_wrapped_json() -> None:
    assert parse_judge_json('Here is the result: {"score": 2, "reason": "direct"}') == (2, "direct")


def test_parse_judge_json_rejects_out_of_range_score() -> None:
    try:
        parse_judge_json('{"score": 4, "reason": "bad"}')
    except ValueError as exc:
        assert "score" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_evaluate_ranked_computes_graded_metrics() -> None:
    queries = [TopicQuery(query_id="q1", text="graph neural networks", source="topics", doc_frequency=5)]
    metas = [
        DocMeta(doc_id="d1", title="A", abstract="", language="en", topics=[]),
        DocMeta(doc_id="d2", title="B", abstract="", language="en", topics=[]),
        DocMeta(doc_id="d3", title="C", abstract="", language="en", topics=[]),
    ]
    scores = {
        ("q1", "d1"): 2,
        ("q1", "d2"): 1,
        ("q1", "d3"): 0,
    }

    metrics, per_query = evaluate_ranked(
        queries=queries,
        ranked=[[1, 0, 2, 2, 2]],
        metas=metas,
        scores=scores,
        eval_top_k=5,
    )

    assert metrics["Precision@5"] == 2 / 5
    assert metrics["StrongPrecision@5"] == 1 / 5
    assert 0.0 < metrics["nDCG@5"] <= 1.0
    assert per_query[0]["relevant_at_10"] == 2

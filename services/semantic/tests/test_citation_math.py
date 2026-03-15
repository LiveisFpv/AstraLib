from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

CITATION_MATH_PATH = ROOT_DIR / "src" / "services" / "ingestion" / "citation_math.py"
SPEC = importlib.util.spec_from_file_location("citation_math_test_module", CITATION_MATH_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Failed to load citation_math module from {CITATION_MATH_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

compute_cache_arrays = MODULE.compute_cache_arrays
expand_affected_graph = MODULE.expand_affected_graph


def make_fetchers(edges: dict[int, list[int]]):
    predecessors: dict[int, list[int]] = {}
    for src, targets in edges.items():
        for dst in targets:
            predecessors.setdefault(dst, []).append(src)

    def fetch_successors(paper_ids: set[int]) -> dict[int, list[int]]:
        return {paper_id: list(edges.get(paper_id, [])) for paper_id in paper_ids}

    def fetch_predecessors(paper_ids: set[int]) -> dict[int, list[int]]:
        return {paper_id: list(predecessors.get(paper_id, [])) for paper_id in paper_ids}

    return fetch_successors, fetch_predecessors, predecessors


def full_cache(
    doc_ids: list[int],
    edges: dict[int, list[int]],
    predecessors: dict[int, list[int]],
    base_embeddings: np.ndarray,
    row_by_doc_id: dict[int, int],
) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int, int, int]]:
    result: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int, int, int]] = {}
    dim = base_embeddings.shape[1]

    def mean_rows(paper_ids: list[int]) -> np.ndarray:
        row_indices = [row_by_doc_id[paper_id] for paper_id in paper_ids if paper_id in row_by_doc_id]
        if not row_indices:
            return np.zeros((dim,), dtype=np.float16)
        return np.asarray(base_embeddings[row_indices], dtype=np.float32).mean(axis=0).astype(np.float16)

    for paper_id in doc_ids:
        direct_successors = list(edges.get(paper_id, []))
        direct_predecessors = list(predecessors.get(paper_id, []))
        out2_ids = [dst for src in direct_successors for dst in edges.get(src, [])]
        in2_ids = [src for dst in direct_predecessors for src in predecessors.get(dst, [])]
        result[paper_id] = (
            mean_rows(direct_successors),
            mean_rows(direct_predecessors),
            mean_rows(out2_ids),
            mean_rows(in2_ids),
            len(direct_successors),
            len(direct_predecessors),
            len(out2_ids),
            len(in2_ids),
        )
    return result


def test_expand_affected_graph_returns_exact_two_hop_closure() -> None:
    edges = {
        1: [2, 3],
        2: [4],
        3: [4, 5],
        5: [6],
        7: [1],
        8: [7],
    }
    fetch_successors, fetch_predecessors, _ = make_fetchers(edges)

    graph = expand_affected_graph(
        {1},
        fetch_successors=fetch_successors,
        fetch_predecessors=fetch_predecessors,
    )

    assert graph.affected_ids == {1, 2, 3, 4, 5, 7, 8}


def test_compute_cache_arrays_matches_full_rebuild_for_affected_rows() -> None:
    edges = {
        1: [2, 3],
        2: [4],
        3: [4, 5],
        5: [6],
        7: [1],
        8: [7],
    }
    fetch_successors, fetch_predecessors, predecessors = make_fetchers(edges)
    doc_ids = [1, 2, 3, 4, 5, 6, 7, 8]
    row_by_doc_id = {paper_id: idx for idx, paper_id in enumerate(doc_ids)}
    base_embeddings = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [2.0, 0.0],
            [0.0, 2.0],
            [3.0, 3.0],
            [4.0, 0.0],
            [0.0, 4.0],
        ],
        dtype=np.float16,
    )

    graph = expand_affected_graph(
        {1},
        fetch_successors=fetch_successors,
        fetch_predecessors=fetch_predecessors,
    )
    expected = full_cache(doc_ids, edges, predecessors, base_embeddings, row_by_doc_id)

    (
        ordered_ids,
        out1_rows,
        in1_rows,
        out2_rows,
        in2_rows,
        deg_out,
        deg_in,
        cnt_out2,
        cnt_in2,
    ) = compute_cache_arrays(
        affected_ids=graph.affected_ids,
        dim=2,
        row_by_doc_id=row_by_doc_id,
        base_embeddings=base_embeddings,
        successors=graph.successors,
        predecessors=graph.predecessors,
        successor_successors=graph.successor_successors,
        predecessor_predecessors=graph.predecessor_predecessors,
    )

    for offset, paper_id in enumerate(ordered_ids):
        exp_out1, exp_in1, exp_out2, exp_in2, exp_deg_out, exp_deg_in, exp_cnt_out2, exp_cnt_in2 = expected[paper_id]
        assert np.allclose(out1_rows[offset], exp_out1)
        assert np.allclose(in1_rows[offset], exp_in1)
        assert np.allclose(out2_rows[offset], exp_out2)
        assert np.allclose(in2_rows[offset], exp_in2)
        assert int(deg_out[offset]) == exp_deg_out
        assert int(deg_in[offset]) == exp_deg_in
        assert int(cnt_out2[offset]) == exp_cnt_out2
        assert int(cnt_in2[offset]) == exp_cnt_in2

    node5_idx = ordered_ids.index(5)
    assert np.allclose(out1_rows[node5_idx], np.asarray([3.0, 3.0], dtype=np.float16))


def test_rows_outside_affected_set_remain_unchanged_after_seed_embedding_update() -> None:
    edges = {
        1: [2, 3],
        2: [4],
        3: [4, 5],
        5: [6],
        7: [1],
        8: [7],
    }
    fetch_successors, fetch_predecessors, predecessors = make_fetchers(edges)
    doc_ids = [1, 2, 3, 4, 5, 6, 7, 8]
    row_by_doc_id = {paper_id: idx for idx, paper_id in enumerate(doc_ids)}

    before_embeddings = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [2.0, 0.0],
            [0.0, 2.0],
            [3.0, 3.0],
            [4.0, 0.0],
            [0.0, 4.0],
        ],
        dtype=np.float16,
    )
    after_embeddings = before_embeddings.copy()
    after_embeddings[row_by_doc_id[1]] = np.asarray([9.0, 9.0], dtype=np.float16)

    graph = expand_affected_graph(
        {1},
        fetch_successors=fetch_successors,
        fetch_predecessors=fetch_predecessors,
    )
    before_cache = full_cache(doc_ids, edges, predecessors, before_embeddings, row_by_doc_id)
    after_cache = full_cache(doc_ids, edges, predecessors, after_embeddings, row_by_doc_id)

    unaffected_ids = set(doc_ids) - graph.affected_ids
    assert unaffected_ids == {6}
    for paper_id in unaffected_ids:
        assert all(
            np.allclose(before_component, after_component)
            if isinstance(before_component, np.ndarray)
            else before_component == after_component
            for before_component, after_component in zip(before_cache[paper_id], after_cache[paper_id], strict=False)
        )

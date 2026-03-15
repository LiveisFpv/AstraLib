"""Pure helpers for incremental citation-aware cache recomputation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np


@dataclass(slots=True)
class AffectedGraph:
    affected_ids: set[int]
    successors: dict[int, list[int]]
    predecessors: dict[int, list[int]]
    successor_successors: dict[int, list[int]]
    predecessor_predecessors: dict[int, list[int]]


def expand_affected_graph(
    seed_ids: Iterable[int],
    *,
    fetch_successors: Callable[[set[int]], dict[int, list[int]]],
    fetch_predecessors: Callable[[set[int]], dict[int, list[int]]],
) -> AffectedGraph:
    normalized_seed = {int(paper_id) for paper_id in seed_ids if paper_id is not None}
    if not normalized_seed:
        return AffectedGraph(set(), {}, {}, {}, {})

    seed_successors = fetch_successors(normalized_seed)
    seed_predecessors = fetch_predecessors(normalized_seed)
    successor_ids = {dst for values in seed_successors.values() for dst in values}
    predecessor_ids = {src for values in seed_predecessors.values() for src in values}

    seed_successor_successors = fetch_successors(successor_ids) if successor_ids else {}
    seed_predecessor_predecessors = fetch_predecessors(predecessor_ids) if predecessor_ids else {}

    affected_ids = set(normalized_seed)
    affected_ids.update(successor_ids)
    affected_ids.update(predecessor_ids)
    affected_ids.update(dst for values in seed_successor_successors.values() for dst in values)
    affected_ids.update(src for values in seed_predecessor_predecessors.values() for src in values)

    successors = fetch_successors(affected_ids)
    predecessors = fetch_predecessors(affected_ids)

    affected_successor_ids = {dst for values in successors.values() for dst in values}
    affected_predecessor_ids = {src for values in predecessors.values() for src in values}
    successor_successors = fetch_successors(affected_successor_ids) if affected_successor_ids else {}
    predecessor_predecessors = fetch_predecessors(affected_predecessor_ids) if affected_predecessor_ids else {}

    return AffectedGraph(
        affected_ids=affected_ids,
        successors=successors,
        predecessors=predecessors,
        successor_successors=successor_successors,
        predecessor_predecessors=predecessor_predecessors,
    )


def compute_cache_arrays(
    *,
    affected_ids: Iterable[int],
    dim: int,
    row_by_doc_id: dict[int, int],
    base_embeddings: np.ndarray,
    successors: dict[int, list[int]],
    predecessors: dict[int, list[int]],
    successor_successors: dict[int, list[int]],
    predecessor_predecessors: dict[int, list[int]],
) -> tuple[
    list[int],
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    ordered_ids = sorted({int(paper_id) for paper_id in affected_ids if int(paper_id) in row_by_doc_id})
    if not ordered_ids:
        empty = np.zeros((0, dim), dtype=np.float16)
        empty_counts = np.zeros((0,), dtype=np.int32)
        return [], empty, empty, empty, empty, empty_counts, empty_counts, empty_counts, empty_counts

    out1_rows = np.zeros((len(ordered_ids), dim), dtype=np.float16)
    in1_rows = np.zeros((len(ordered_ids), dim), dtype=np.float16)
    out2_rows = np.zeros((len(ordered_ids), dim), dtype=np.float16)
    in2_rows = np.zeros((len(ordered_ids), dim), dtype=np.float16)
    deg_out = np.zeros((len(ordered_ids),), dtype=np.int32)
    deg_in = np.zeros((len(ordered_ids),), dtype=np.int32)
    cnt_out2 = np.zeros((len(ordered_ids),), dtype=np.int32)
    cnt_in2 = np.zeros((len(ordered_ids),), dtype=np.int32)

    for offset, paper_id in enumerate(ordered_ids):
        direct_successors = list(successors.get(paper_id, []))
        direct_predecessors = list(predecessors.get(paper_id, []))
        deg_out[offset] = len(direct_successors)
        deg_in[offset] = len(direct_predecessors)

        out1_rows[offset] = _mean_embeddings(
            direct_successors,
            row_by_doc_id=row_by_doc_id,
            base_embeddings=base_embeddings,
            dim=dim,
        )
        in1_rows[offset] = _mean_embeddings(
            direct_predecessors,
            row_by_doc_id=row_by_doc_id,
            base_embeddings=base_embeddings,
            dim=dim,
        )

        out2_ids: list[int] = []
        for successor_id in direct_successors:
            out2_ids.extend(successor_successors.get(successor_id, []))
        cnt_out2[offset] = len(out2_ids)
        out2_rows[offset] = _mean_embeddings(
            out2_ids,
            row_by_doc_id=row_by_doc_id,
            base_embeddings=base_embeddings,
            dim=dim,
        )

        in2_ids: list[int] = []
        for predecessor_id in direct_predecessors:
            in2_ids.extend(predecessor_predecessors.get(predecessor_id, []))
        cnt_in2[offset] = len(in2_ids)
        in2_rows[offset] = _mean_embeddings(
            in2_ids,
            row_by_doc_id=row_by_doc_id,
            base_embeddings=base_embeddings,
            dim=dim,
        )

    return ordered_ids, out1_rows, in1_rows, out2_rows, in2_rows, deg_out, deg_in, cnt_out2, cnt_in2


def _mean_embeddings(
    paper_ids: Iterable[int],
    *,
    row_by_doc_id: dict[int, int],
    base_embeddings: np.ndarray,
    dim: int,
) -> np.ndarray:
    row_indices = [row_by_doc_id[int(paper_id)] for paper_id in paper_ids if int(paper_id) in row_by_doc_id]
    if not row_indices:
        return np.zeros((dim,), dtype=np.float16)
    rows = np.asarray(base_embeddings[row_indices], dtype=np.float32)
    return rows.mean(axis=0).astype(np.float16)


__all__ = ["AffectedGraph", "compute_cache_arrays", "expand_affected_graph"]

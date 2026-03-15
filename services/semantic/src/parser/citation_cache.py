"""Shared helpers for citation cache and weighted vectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable, Sequence

import faiss
import numpy as np
from tqdm import tqdm


CITATION_CACHE_VERSION = 1


def load_memmap(mem_path: Path) -> tuple[np.memmap, int, int]:
    meta_path = mem_path.with_suffix(".shape.json")
    legacy_meta_path = mem_path.with_name(f"{mem_path.name}.shape.json")
    if not meta_path.exists() and legacy_meta_path.exists():
        meta_path = legacy_meta_path
    with open(meta_path, "r", encoding="utf-8") as meta_file:
        n_vectors, dim = json.load(meta_file)
    arr = np.memmap(mem_path, dtype=np.float16, mode="r", shape=(n_vectors, dim))
    return arr, int(n_vectors), int(dim)


def cache_paths(cache_dir: Path) -> dict[str, Path]:
    return {
        "out1_sum": cache_dir / "cites_out1.sum.f32.memmap",
        "in1_sum": cache_dir / "citedby_in1.sum.f32.memmap",
        "out2_sum": cache_dir / "cites_out2.sum.f32.memmap",
        "in2_sum": cache_dir / "citedby_in2.sum.f32.memmap",
        "out1_mean": cache_dir / "cites_out1.mean.f16.memmap",
        "in1_mean": cache_dir / "citedby_in1.mean.f16.memmap",
        "out2_mean": cache_dir / "cites_out2.mean.f16.memmap",
        "in2_mean": cache_dir / "citedby_in2.mean.f16.memmap",
        "deg_out": cache_dir / "deg_out.npy",
        "deg_in": cache_dir / "deg_in.npy",
        "cnt_out2": cache_dir / "cnt_out2.npy",
        "cnt_in2": cache_dir / "cnt_in2.npy",
    }


def cache_ready(cache_dir: Path, n: int, d: int) -> bool:
    required = [
        "out1_mean",
        "in1_mean",
        "out2_mean",
        "in2_mean",
        "deg_out",
        "deg_in",
        "cnt_out2",
        "cnt_in2",
    ]
    size = n * d * 2  # float16
    paths = cache_paths(cache_dir)
    for key in required:
        path = paths[key]
        if not path.exists():
            return False
        if key.endswith("_mean") and path.stat().st_size != size:
            return False
    return True


def map_ids(arr: Sequence[int], id_to_idx: dict[int, int]) -> np.ndarray:
    return np.fromiter((id_to_idx.get(int(x), -1) for x in arr), dtype=np.int32, count=len(arr))


def zero_memmap(path: Path, shape: tuple[int, int]) -> np.memmap:
    arr = np.memmap(path, dtype=np.float32, mode="w+", shape=shape)
    arr[:] = 0
    arr.flush()
    return arr


def write_means(sum_memmap: np.memmap, counts: np.ndarray, out_path: Path, chunk_docs: int) -> None:
    n = sum_memmap.shape[0]
    mean = np.memmap(out_path, dtype=np.float16, mode="w+", shape=sum_memmap.shape)
    for start in tqdm(range(0, n, chunk_docs), desc=f"Write {out_path.name}", unit="doc", dynamic_ncols=True):
        end = min(start + chunk_docs, n)
        chunk = np.array(sum_memmap[start:end], dtype=np.float32, copy=True)
        cnt = counts[start:end].astype(np.float32)
        mask = cnt > 0
        if mask.any():
            chunk[mask] /= cnt[mask][:, None]
        chunk[~mask] = 0.0
        mean[start:end] = chunk.astype(np.float16)
    mean.flush()


def build_citation_cache_from_batches(
    emb: np.memmap,
    id_to_idx: dict[int, int],
    edge_batches: Iterable[Sequence[tuple[int, int]]] | Callable[[], Iterable[Sequence[tuple[int, int]]]],
    cache_dir: Path,
    *,
    vec_chunk: int,
    doc_chunk: int,
    keep_sums: bool,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    n, d = emb.shape
    paths = cache_paths(cache_dir)

    out1_sum = zero_memmap(paths["out1_sum"], (n, d))
    in1_sum = zero_memmap(paths["in1_sum"], (n, d))
    deg_out = np.zeros(n, dtype=np.int32)
    deg_in = np.zeros(n, dtype=np.int32)

    batch_iterable = edge_batches() if callable(edge_batches) else edge_batches
    for batch in batch_iterable:
        if not batch:
            continue
        src_ids = np.asarray([int(src) for src, _ in batch], dtype=np.int64)
        tgt_ids = np.asarray([int(dst) for _, dst in batch], dtype=np.int64)
        src_idx = map_ids(src_ids, id_to_idx)
        tgt_idx = map_ids(tgt_ids, id_to_idx)
        mask = (src_idx >= 0) & (tgt_idx >= 0)
        if not mask.any():
            continue
        src_idx = src_idx[mask]
        tgt_idx = tgt_idx[mask]

        np.add.at(deg_out, src_idx, 1)
        np.add.at(deg_in, tgt_idx, 1)

        for start in range(0, len(src_idx), vec_chunk):
            end = min(start + vec_chunk, len(src_idx))
            ss = src_idx[start:end]
            tt = tgt_idx[start:end]
            np.add.at(out1_sum, ss, emb[tt])
            np.add.at(in1_sum, tt, emb[ss])

    out1_sum.flush()
    in1_sum.flush()

    write_means(out1_sum, deg_out, paths["out1_mean"], chunk_docs=doc_chunk)
    write_means(in1_sum, deg_in, paths["in1_mean"], chunk_docs=doc_chunk)

    out2_sum = zero_memmap(paths["out2_sum"], (n, d))
    in2_sum = zero_memmap(paths["in2_sum"], (n, d))
    cnt_out2 = np.zeros(n, dtype=np.int32)
    cnt_in2 = np.zeros(n, dtype=np.int32)

    batch_iterable = edge_batches() if callable(edge_batches) else edge_batches
    for batch in batch_iterable:
        if not batch:
            continue
        src_ids = np.asarray([int(src) for src, _ in batch], dtype=np.int64)
        tgt_ids = np.asarray([int(dst) for _, dst in batch], dtype=np.int64)
        src_idx = map_ids(src_ids, id_to_idx)
        tgt_idx = map_ids(tgt_ids, id_to_idx)
        mask = (src_idx >= 0) & (tgt_idx >= 0)
        if not mask.any():
            continue
        src_idx = src_idx[mask]
        tgt_idx = tgt_idx[mask]

        np.add.at(cnt_out2, src_idx, deg_out[tgt_idx])
        np.add.at(cnt_in2, tgt_idx, deg_in[src_idx])

        for start in range(0, len(src_idx), vec_chunk):
            end = min(start + vec_chunk, len(src_idx))
            ss = src_idx[start:end]
            tt = tgt_idx[start:end]
            np.add.at(out2_sum, ss, out1_sum[tt])
            np.add.at(in2_sum, tt, in1_sum[ss])

    out2_sum.flush()
    in2_sum.flush()

    write_means(out2_sum, cnt_out2, paths["out2_mean"], chunk_docs=doc_chunk)
    write_means(in2_sum, cnt_in2, paths["in2_mean"], chunk_docs=doc_chunk)

    np.save(paths["deg_out"], deg_out)
    np.save(paths["deg_in"], deg_in)
    np.save(paths["cnt_out2"], cnt_out2)
    np.save(paths["cnt_in2"], cnt_in2)

    if not keep_sums:
        del out1_sum, in1_sum, out2_sum, in2_sum
        for key in ("out1_sum", "in1_sum", "out2_sum", "in2_sum"):
            try:
                paths[key].unlink()
            except OSError:
                pass


def parse_weights(s: str) -> dict[str, float]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out = {"self": 1.0, "out1": 0.0, "in1": 0.0, "out2": 0.0, "in2": 0.0}
    for part in parts:
        if "=" not in part:
            raise ValueError(f"Bad weights token: {part}")
        key, val = part.split("=", 1)
        key = key.strip()
        if key not in out:
            raise ValueError(f"Unknown weight key: {key}")
        out[key] = float(val)
    return out


def build_weighted_vectors(
    base_vectors: np.ndarray,
    out1_vectors: np.ndarray | None,
    in1_vectors: np.ndarray | None,
    out2_vectors: np.ndarray | None,
    in2_vectors: np.ndarray | None,
    weights: dict[str, float],
    *,
    normalize: bool,
) -> np.ndarray:
    vectors = weights["self"] * base_vectors.astype(np.float32)
    if out1_vectors is not None and weights["out1"] != 0.0:
        vectors += weights["out1"] * out1_vectors.astype(np.float32)
    if in1_vectors is not None and weights["in1"] != 0.0:
        vectors += weights["in1"] * in1_vectors.astype(np.float32)
    if out2_vectors is not None and weights["out2"] != 0.0:
        vectors += weights["out2"] * out2_vectors.astype(np.float32)
    if in2_vectors is not None and weights["in2"] != 0.0:
        vectors += weights["in2"] * in2_vectors.astype(np.float32)
    if normalize and len(vectors) > 0:
        faiss.normalize_L2(vectors)
    return vectors


__all__ = [
    "CITATION_CACHE_VERSION",
    "build_citation_cache_from_batches",
    "build_weighted_vectors",
    "cache_paths",
    "cache_ready",
    "load_memmap",
    "parse_weights",
]

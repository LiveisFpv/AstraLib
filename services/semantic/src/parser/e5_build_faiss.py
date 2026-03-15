#!/usr/bin/env python3
"""Build a FAISS index from generated embeddings."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Iterable, Sequence

import faiss
import numpy as np
import psycopg
import pyarrow.parquet as pq
from tqdm import tqdm
from psycopg.rows import dict_row

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.parser.citation_cache import (
    CITATION_CACHE_VERSION,
    build_citation_cache_from_batches,
    build_weighted_vectors,
    cache_paths,
    cache_ready,
    load_memmap,
    parse_weights,
)
from src.storage.citation_repository import CitationRepository


def iter_parquet_edge_batches(
    paths: list[str],
    *,
    batch_rows: int,
    desc: str,
) -> Iterable[list[tuple[int, int]]]:
    for path in paths:
        parquet_file = pq.ParquetFile(path)
        total = parquet_file.metadata.num_rows
        progress = tqdm(
            total=total,
            desc=f"{desc}: {os.path.basename(path)}",
            unit="edge",
            dynamic_ncols=True,
        )
        for row_group in range(parquet_file.num_row_groups):
            table = parquet_file.read_row_group(row_group, columns=["source_id", "target_id"])
            src = table.column("source_id").to_numpy(zero_copy_only=False)
            dst = table.column("target_id").to_numpy(zero_copy_only=False)
            for start in range(0, len(src), batch_rows):
                end = min(start + batch_rows, len(src))
                progress.update(end - start)
                yield [
                    (int(src_id), int(dst_id))
                    for src_id, dst_id in zip(src[start:end], dst[start:end], strict=False)
                ]
        progress.close()


def materialize_weighted_vectors(
    row_indices: np.ndarray,
    embeddings: np.memmap,
    out1: np.memmap | None,
    in1: np.memmap | None,
    out2: np.memmap | None,
    in2: np.memmap | None,
    weights: dict[str, float],
    *,
    normalize: bool,
) -> np.ndarray:
    base_vectors = np.asarray(embeddings[row_indices], dtype=np.float32)
    out1_vectors = np.asarray(out1[row_indices], dtype=np.float32) if out1 is not None else None
    in1_vectors = np.asarray(in1[row_indices], dtype=np.float32) if in1 is not None else None
    out2_vectors = np.asarray(out2[row_indices], dtype=np.float32) if out2 is not None else None
    in2_vectors = np.asarray(in2[row_indices], dtype=np.float32) if in2 is not None else None
    return build_weighted_vectors(
        base_vectors,
        out1_vectors,
        in1_vectors,
        out2_vectors,
        in2_vectors,
        weights,
        normalize=normalize,
    )


def artifact_ref(base_dir: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path)


def load_or_resolve_doc_ids(doc_ids_path: Path, *, mutable_runtime: bool) -> np.ndarray:
    doc_ids = np.load(doc_ids_path, allow_pickle=True)
    try:
        return np.asarray(doc_ids, dtype=np.int64)
    except (TypeError, ValueError):
        if not mutable_runtime:
            return doc_ids
        resolved = resolve_legacy_doc_ids_to_paper_ids(doc_ids)
        tmp_path = doc_ids_path.with_name(f"{doc_ids_path.name}.tmp")
        with open(tmp_path, "wb") as file_obj:
            np.save(file_obj, resolved.astype(np.int64, copy=False))
        os.replace(tmp_path, doc_ids_path)
        return resolved


def resolve_legacy_doc_ids_to_paper_ids(doc_ids: np.ndarray, *, chunk_size: int = 10_000) -> np.ndarray:
    values = [str(doc_id).strip() for doc_id in doc_ids.tolist()]
    if not values:
        return np.empty((0,), dtype=np.int64)

    repository = CitationRepository()
    mapping: dict[str, int] = {}
    with psycopg.connect(repository.dsn, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            for start in range(0, len(values), chunk_size):
                chunk = list(dict.fromkeys(values[start : start + chunk_size]))
                cur.execute(
                    """
                    SELECT pi.identifier, pi.paper_id
                    FROM paper_identifiers pi
                    JOIN identifier_types it
                      ON it.identifier_type_id = pi.identifier_type_id
                    WHERE it.name = 'openalex'
                      AND pi.identifier = ANY(%s)
                    """,
                    (chunk,),
                )
                for row in cur.fetchall():
                    mapping[str(row["identifier"])] = int(row["paper_id"])

    missing = [value for value in values if value not in mapping]
    if missing:
        sample = ", ".join(missing[:5])
        raise RuntimeError(
            f"Failed to resolve {len(missing)} legacy doc_ids to paper_id; sample: {sample}"
        )
    return np.asarray([mapping[value] for value in values], dtype=np.int64)


def create_index(
    *,
    dim: int,
    index_type: str,
    metric: int,
    nlist: int,
    m: int,
    nbits: int,
    mutable_runtime: bool,
):
    if index_type == "flat":
        base_index = faiss.IndexFlatIP(dim) if metric == faiss.METRIC_INNER_PRODUCT else faiss.IndexFlatL2(dim)
        if mutable_runtime:
            return faiss.IndexIDMap2(base_index)
        return base_index

    if index_type == "ivfflat":
        description = f"IVF{nlist},Flat"
    elif index_type == "ivfpq":
        description = f"IVF{nlist},PQ{m}x{nbits}"
    else:
        raise ValueError(f"Unsupported index type: {index_type}")

    index = faiss.index_factory(dim, description, metric)
    if mutable_runtime:
        _enable_direct_map(index)
    return index


def _enable_direct_map(index) -> None:
    if not hasattr(faiss, "extract_index_ivf"):
        return
    try:
        ivf_index = faiss.extract_index_ivf(index)
    except Exception:
        ivf_index = None
    if ivf_index is None:
        return
    if hasattr(ivf_index, "set_direct_map_type"):
        ivf_index.set_direct_map_type(faiss.DirectMap.Hashtable)


def build_faiss_index(
    *,
    mem_path: Path,
    doc_ids_path: Path,
    out_path: Path,
    index_type: str,
    metric_name: str,
    nlist: int,
    m: int,
    nbits: int,
    train_size: int,
    seed: int,
    weights: dict[str, float],
    normalize: bool,
    cache_dir: Path | None,
    edge_batches_factory: Callable[[], Iterable[Sequence[tuple[int, int]]]] | None,
    recompute_cache: bool,
    vec_chunk: int,
    doc_chunk: int,
    keep_sums: bool,
    add_batch: int,
    mutable_runtime: bool,
    dirty_marker_name: str | None = None,
) -> dict[str, object]:
    embeddings, n_vecs, dim = load_memmap(mem_path)
    doc_ids = load_or_resolve_doc_ids(doc_ids_path, mutable_runtime=mutable_runtime)
    if len(doc_ids) != n_vecs:
        raise RuntimeError("Document IDs count does not match embeddings count")

    needs_citation = any(weights[key] != 0.0 for key in ("out1", "in1", "out2", "in2"))
    if mutable_runtime and not needs_citation:
        raise RuntimeError("Mutable weighted runtime requires non-zero citation weights")
    if needs_citation and edge_batches_factory is None:
        raise RuntimeError("Citation weights require an edge source")

    out1 = in1 = out2 = in2 = None
    if needs_citation:
        if cache_dir is None:
            raise RuntimeError("cache_dir is required when citation weights are enabled")
        if recompute_cache or not cache_ready(cache_dir, n_vecs, dim):
            id_to_idx = {int(doc_id): idx for idx, doc_id in enumerate(doc_ids.tolist())}
            build_citation_cache_from_batches(
                embeddings,
                id_to_idx,
                edge_batches_factory,
                cache_dir,
                vec_chunk=vec_chunk,
                doc_chunk=doc_chunk,
                keep_sums=keep_sums,
            )
        paths = cache_paths(cache_dir)
        out1 = np.memmap(paths["out1_mean"], dtype=np.float16, mode="r", shape=(n_vecs, dim))
        in1 = np.memmap(paths["in1_mean"], dtype=np.float16, mode="r", shape=(n_vecs, dim))
        out2 = np.memmap(paths["out2_mean"], dtype=np.float16, mode="r", shape=(n_vecs, dim))
        in2 = np.memmap(paths["in2_mean"], dtype=np.float16, mode="r", shape=(n_vecs, dim))

    metric = faiss.METRIC_INNER_PRODUCT if metric_name == "ip" else faiss.METRIC_L2
    index = create_index(
        dim=dim,
        index_type=index_type,
        metric=metric,
        nlist=nlist,
        m=m,
        nbits=nbits,
        mutable_runtime=mutable_runtime,
    )

    if not mutable_runtime and index_type != "flat":
        rng = np.random.RandomState(seed)
        sample_size = min(train_size, n_vecs)
        sample_idx = rng.choice(n_vecs, size=sample_size, replace=False)
        train_vectors = materialize_weighted_vectors(
            sample_idx,
            embeddings,
            out1,
            in1,
            out2,
            in2,
            weights,
            normalize=normalize,
        )
        index.train(train_vectors)
    elif mutable_runtime and index_type != "flat":
        rng = np.random.RandomState(seed)
        sample_size = min(train_size, n_vecs)
        sample_idx = rng.choice(n_vecs, size=sample_size, replace=False)
        train_vectors = materialize_weighted_vectors(
            sample_idx,
            embeddings,
            out1,
            in1,
            out2,
            in2,
            weights,
            normalize=normalize,
        )
        index.train(train_vectors)

    for start in tqdm(range(0, n_vecs, add_batch), desc="Adding", unit="vecs", dynamic_ncols=True):
        end = min(start + add_batch, n_vecs)
        row_indices = np.arange(start, end)
        vectors = materialize_weighted_vectors(
            row_indices,
            embeddings,
            out1,
            in1,
            out2,
            in2,
            weights,
            normalize=normalize,
        )
        if mutable_runtime:
            index.add_with_ids(vectors, doc_ids[row_indices].astype(np.int64))
        else:
            index.add(vectors)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_path))

    meta = {
        "vectors": int(n_vecs),
        "dimension": int(dim),
        "metric": metric_name,
        "index_type": index_type,
        "nlist": int(nlist) if index_type in {"ivfflat", "ivfpq"} else None,
        "m": int(m) if index_type == "ivfpq" else None,
        "nbits": int(nbits) if index_type == "ivfpq" else None,
        "train_size": int(min(train_size, n_vecs)),
        "seed": int(seed),
        "doc_ids": artifact_ref(out_path.parent, doc_ids_path),
        "weights": dict(weights),
        "normalized": bool(normalize),
        "id_mode": "paper_id" if mutable_runtime else "position",
        "citation_cache_version": CITATION_CACHE_VERSION if needs_citation else None,
        "artifacts": {
            "doc_ids": artifact_ref(out_path.parent, doc_ids_path),
            "embeddings": artifact_ref(out_path.parent, mem_path),
            "cache_dir": artifact_ref(out_path.parent, cache_dir),
            "dirty_marker": dirty_marker_name or f"{out_path.name}.dirty",
        },
        "training": {
            "index_type": index_type,
            "metric": metric_name,
            "nlist": int(nlist),
            "m": int(m),
            "nbits": int(nbits),
            "train_size": int(min(train_size, n_vecs)),
            "seed": int(seed),
            "add_batch": int(add_batch),
        },
    }
    meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
    with open(meta_path, "w", encoding="utf-8") as meta_file:
        json.dump(meta, meta_file, ensure_ascii=False, indent=2)
    return meta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FAISS index from embeddings")
    parser.add_argument("--emb-dir", required=True, help="Directory containing embedding outputs")
    parser.add_argument("--memfile", default="doc_embeddings.f16.memmap", help="Memmap file name")
    parser.add_argument("--doc-ids", default="doc_ids.npy", help="Doc IDs numpy file")
    parser.add_argument("--out", help="Output index path (defaults to <emb-dir>/faiss.index)")
    parser.add_argument("--index-type", choices=["flat", "ivfflat", "ivfpq"], default="ivfpq")
    parser.add_argument("--metric", choices=["ip", "l2"], default="ip")
    parser.add_argument("--nlist", type=int, default=4096)
    parser.add_argument("--m", type=int, default=32)
    parser.add_argument("--nbits", type=int, default=8)
    parser.add_argument("--train-size", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--weights", help="Citation weights: self=1.0,out1=0.0,in1=0.0,out2=0.0,in2=0.0")
    parser.add_argument("--edges", nargs="+", help="Parquet edge files with source_id/target_id")
    parser.add_argument("--citations-from-db", action="store_true", help="Read citation_edges from Postgres")
    parser.add_argument("--cache-dir", help="Cache dir for citation vectors (defaults to <emb-dir>/citation_cache)")
    parser.add_argument("--recompute-cache", action="store_true")
    parser.add_argument("--edge-batch-rows", type=int, default=200_000)
    parser.add_argument("--vec-chunk", type=int, default=10_000)
    parser.add_argument("--doc-chunk", type=int, default=4_096)
    parser.add_argument("--keep-sums", action="store_true")
    parser.add_argument("--add-batch", type=int, default=200_000)
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--mutable-runtime", action="store_true", help="Store paper_id as FAISS external ids")
    parser.add_argument("--dirty-marker-name", help="Dirty marker filename for mutable runtime")
    return parser.parse_args()


def resolve_edge_batches_factory(args: argparse.Namespace) -> Callable[[], Iterable[Sequence[tuple[int, int]]]] | None:
    if args.citations_from_db and args.edges:
        raise SystemExit("Use either --citations-from-db or --edges, not both")
    if args.citations_from_db:
        repository = CitationRepository()
        return lambda: repository.iter_edges(batch_size=args.edge_batch_rows)
    if args.edges:
        edge_paths = [str(path) for path in args.edges]
        return lambda: iter_parquet_edge_batches(edge_paths, batch_rows=args.edge_batch_rows, desc="Citations")
    return None


def main() -> None:
    args = parse_args()

    emb_dir = Path(args.emb_dir)
    mem_path = emb_dir / args.memfile
    doc_ids_path = emb_dir / args.doc_ids
    out_path = Path(args.out) if args.out else emb_dir / "faiss.index"
    cache_dir = Path(args.cache_dir) if args.cache_dir else emb_dir / "citation_cache"

    weights = parse_weights(args.weights) if args.weights else {
        "self": 1.0,
        "out1": 0.0,
        "in1": 0.0,
        "out2": 0.0,
        "in2": 0.0,
    }
    build_faiss_index(
        mem_path=mem_path,
        doc_ids_path=doc_ids_path,
        out_path=out_path,
        index_type=args.index_type,
        metric_name=args.metric,
        nlist=args.nlist,
        m=args.m,
        nbits=args.nbits,
        train_size=args.train_size,
        seed=args.seed,
        weights=weights,
        normalize=not args.no_normalize,
        cache_dir=cache_dir,
        edge_batches_factory=resolve_edge_batches_factory(args),
        recompute_cache=args.recompute_cache,
        vec_chunk=args.vec_chunk,
        doc_chunk=args.doc_chunk,
        keep_sums=args.keep_sums,
        add_batch=args.add_batch,
        mutable_runtime=args.mutable_runtime,
        dirty_marker_name=args.dirty_marker_name,
    )
    print(f"Saved index to {out_path}")


if __name__ == "__main__":
    main()

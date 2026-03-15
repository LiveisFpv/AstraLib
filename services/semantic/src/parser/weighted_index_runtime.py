#!/usr/bin/env python3
"""Bootstrap and repair mutable weighted citation-aware FAISS runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.db.connection import transaction
from src.parser.citation_cache import parse_weights
from src.parser.e5_build_faiss import build_faiss_index
from src.storage.citation_repository import CitationRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage mutable weighted FAISS runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="Build mutable weighted runtime from embeddings + DB citations")
    _add_common_build_args(bootstrap)
    bootstrap.add_argument("--skip-backfill", action="store_true", help="Skip legacy paper_relations backfill")

    repair = subparsers.add_parser("repair", help="Repair mutable weighted runtime from existing artifacts + DB citations")
    repair.add_argument("--index", required=True, help="Path to FAISS index file")
    repair.add_argument("--embeddings", help="Path to embeddings memmap; defaults to meta artifacts.embeddings")
    repair.add_argument("--doc-ids", help="Path to doc_ids.npy; defaults to meta artifacts.doc_ids")
    repair.add_argument("--cache-dir", help="Path to citation cache dir; defaults to meta artifacts.cache_dir")
    repair.add_argument("--weights", help="Override weights; defaults to meta weights")
    repair.add_argument("--index-type", choices=["flat", "ivfflat", "ivfpq"])
    repair.add_argument("--metric", choices=["ip", "l2"])
    repair.add_argument("--nlist", type=int)
    repair.add_argument("--m", type=int)
    repair.add_argument("--nbits", type=int)
    repair.add_argument("--train-size", type=int)
    repair.add_argument("--seed", type=int)
    repair.add_argument("--edge-batch-rows", type=int, default=200_000)
    repair.add_argument("--vec-chunk", type=int, default=10_000)
    repair.add_argument("--doc-chunk", type=int, default=4_096)
    repair.add_argument("--keep-sums", action="store_true")
    repair.add_argument("--add-batch", type=int)
    repair.add_argument("--no-normalize", action="store_true")
    repair.add_argument("--dirty-marker-name", help="Override dirty marker filename")
    return parser.parse_args()


def _add_common_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--emb-dir", required=True, help="Directory containing embedding outputs")
    parser.add_argument("--memfile", default="doc_embeddings.f16.memmap", help="Embeddings memmap filename")
    parser.add_argument("--doc-ids", default="doc_ids.npy", help="Doc IDs numpy filename")
    parser.add_argument("--out", help="Output index path; defaults to <emb-dir>/faiss.index")
    parser.add_argument("--cache-dir", help="Cache dir; defaults to <emb-dir>/citation_cache")
    parser.add_argument("--weights", required=True, help="Citation weights string")
    parser.add_argument("--index-type", choices=["flat", "ivfflat", "ivfpq"], default="ivfpq")
    parser.add_argument("--metric", choices=["ip", "l2"], default="ip")
    parser.add_argument("--nlist", type=int, default=4096)
    parser.add_argument("--m", type=int, default=32)
    parser.add_argument("--nbits", type=int, default=8)
    parser.add_argument("--train-size", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--edge-batch-rows", type=int, default=200_000)
    parser.add_argument("--vec-chunk", type=int, default=10_000)
    parser.add_argument("--doc-chunk", type=int, default=4_096)
    parser.add_argument("--keep-sums", action="store_true")
    parser.add_argument("--add-batch", type=int, default=200_000)
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--dirty-marker-name", help="Dirty marker filename")


def resolve_artifact(base_dir: Path, reference: str | None, fallback: Path | None = None) -> Path:
    if reference:
        candidate = Path(reference)
        if candidate.is_absolute():
            return candidate
        return (base_dir / candidate).resolve()
    if fallback is None:
        raise RuntimeError("Required artifact path is missing")
    return fallback.resolve()


def load_meta(index_path: Path) -> dict:
    meta_path = index_path.with_suffix(index_path.suffix + ".meta.json")
    if not meta_path.exists():
        raise RuntimeError(f"Index meta file is missing: {meta_path}")
    with open(meta_path, "r", encoding="utf-8") as meta_file:
        data = json.load(meta_file)
    if not isinstance(data, dict):
        raise RuntimeError(f"Index meta file is invalid: {meta_path}")
    return data


def run_bootstrap(args: argparse.Namespace) -> None:
    emb_dir = Path(args.emb_dir)
    mem_path = emb_dir / args.memfile
    doc_ids_path = emb_dir / args.doc_ids
    out_path = Path(args.out) if args.out else emb_dir / "faiss.index"
    cache_dir = Path(args.cache_dir) if args.cache_dir else emb_dir / "citation_cache"

    repository = CitationRepository()
    if not args.skip_backfill:
        with transaction() as conn:
            repository.backfill_legacy_citations(conn)

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
        weights=parse_weights(args.weights),
        normalize=not args.no_normalize,
        cache_dir=cache_dir,
        edge_batches_factory=lambda: repository.iter_edges(batch_size=args.edge_batch_rows),
        recompute_cache=True,
        vec_chunk=args.vec_chunk,
        doc_chunk=args.doc_chunk,
        keep_sums=args.keep_sums,
        add_batch=args.add_batch,
        mutable_runtime=True,
        dirty_marker_name=args.dirty_marker_name,
    )
    dirty_marker_name = args.dirty_marker_name or f"{out_path.name}.dirty"
    dirty_marker_path = resolve_artifact(out_path.parent, dirty_marker_name)
    if dirty_marker_path.exists():
        dirty_marker_path.unlink()
    print(f"Bootstrapped mutable runtime at {out_path}")


def run_repair(args: argparse.Namespace) -> None:
    index_path = Path(args.index).resolve()
    meta = load_meta(index_path)
    training = meta.get("training") or {}
    artifacts = meta.get("artifacts") or {}
    base_dir = index_path.parent

    mem_path = resolve_artifact(base_dir, args.embeddings or artifacts.get("embeddings"))
    doc_ids_path = resolve_artifact(base_dir, args.doc_ids or artifacts.get("doc_ids"))
    cache_dir = resolve_artifact(base_dir, args.cache_dir or artifacts.get("cache_dir"))
    weights = parse_weights(args.weights) if args.weights else meta.get("weights")
    if not isinstance(weights, dict):
        raise RuntimeError("Repair requires weights in meta or via --weights")

    build_faiss_index(
        mem_path=mem_path,
        doc_ids_path=doc_ids_path,
        out_path=index_path,
        index_type=args.index_type or str(training.get("index_type") or meta.get("index_type") or "ivfpq"),
        metric_name=args.metric or str(training.get("metric") or meta.get("metric") or "ip"),
        nlist=int(args.nlist if args.nlist is not None else training.get("nlist") or meta.get("nlist") or 4096),
        m=int(args.m if args.m is not None else training.get("m") or meta.get("m") or 32),
        nbits=int(args.nbits if args.nbits is not None else training.get("nbits") or meta.get("nbits") or 8),
        train_size=int(
            args.train_size
            if args.train_size is not None
            else training.get("train_size") or meta.get("train_size") or 200_000
        ),
        seed=int(args.seed if args.seed is not None else training.get("seed") or meta.get("seed") or 0),
        weights={str(key): float(value) for key, value in weights.items()},
        normalize=bool(meta.get("normalized", True)) if not args.no_normalize else False,
        cache_dir=cache_dir,
        edge_batches_factory=lambda: CitationRepository().iter_edges(batch_size=args.edge_batch_rows),
        recompute_cache=True,
        vec_chunk=args.vec_chunk,
        doc_chunk=args.doc_chunk,
        keep_sums=args.keep_sums,
        add_batch=int(args.add_batch if args.add_batch is not None else training.get("add_batch") or 200_000),
        mutable_runtime=True,
        dirty_marker_name=args.dirty_marker_name or artifacts.get("dirty_marker"),
    )

    dirty_marker_ref = args.dirty_marker_name or artifacts.get("dirty_marker")
    if dirty_marker_ref:
        dirty_marker_path = resolve_artifact(base_dir, dirty_marker_ref)
        if dirty_marker_path.exists():
            dirty_marker_path.unlink()
    print(f"Repaired mutable runtime at {index_path}")


def main() -> None:
    args = parse_args()
    if args.command == "bootstrap":
        run_bootstrap(args)
        return
    if args.command == "repair":
        run_repair(args)
        return
    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()

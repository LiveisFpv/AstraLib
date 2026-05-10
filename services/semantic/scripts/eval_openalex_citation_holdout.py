#!/usr/bin/env python3
"""Evaluate OpenAlex citation holdout retrieval with plain and citation-aware vectors."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.al_models.e5.encoder import EncoderConfig, SemanticEncoder
from src.parser.citation_cache import build_weighted_vectors, cache_paths, cache_ready, parse_weights


DEFAULT_WEIGHTS = "self=1.0,out1=0.0,in1=0.05,out2=0.03,in2=0.025"
EMBEDDINGS_NAME = "doc_embeddings.f16.memmap"


@dataclass(slots=True)
class CorpusData:
    doc_ids: list[str]
    titles: list[str]
    abstracts: list[str]
    languages: list[str]

    @property
    def texts(self) -> list[str]:
        return [format_document(title, abstract) for title, abstract in zip(self.titles, self.abstracts, strict=True)]


@dataclass(slots=True)
class EdgeSplit:
    train_edges: np.ndarray
    test_edges: np.ndarray
    raw_edges: int
    edges_in_corpus: int
    self_edges_removed: int


@dataclass(slots=True)
class QuerySet:
    query_doc_rows: list[int]
    query_ids: list[str]
    query_texts: list[str]
    qrels: dict[str, dict[str, int]]


def log_phase(message: str) -> None:
    print(f"[openalex-holdout] {message}", flush=True)


def normalize_openalex_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("https://openalex.org/"):
        return text
    if text.startswith("http://openalex.org/"):
        return "https://openalex.org/" + text.rsplit("/", 1)[-1]
    if text.startswith("W") and text[1:].isdigit():
        return f"https://openalex.org/{text}"
    return text


def split_pipe_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = str(value).split(" | ")
    result: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        item = normalize_openalex_id(raw)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def format_document(title: str, abstract: str) -> str:
    parts = [str(title or "").strip(), str(abstract or "").strip()]
    return "\n".join(part for part in parts if part)


def format_query(title: str, abstract: str, query_field: str) -> str:
    if query_field == "title":
        return str(title or "").strip()
    if query_field == "title_abstract":
        return format_document(title, abstract)
    raise ValueError(f"Unsupported query_field: {query_field}")


def stable_fraction(*parts: Any) -> float:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    value = int.from_bytes(digest, byteorder="big", signed=False)
    return value / float(2**64 - 1)


def stable_edge_is_test(src_id: str, dst_id: str, *, test_frac: float, seed: int) -> bool:
    if test_frac <= 0.0:
        return False
    if test_frac >= 1.0:
        return True
    return stable_fraction(seed, src_id, dst_id) < test_frac


def stable_row_order(row: int, doc_id: str, *, seed: int) -> tuple[float, int]:
    return stable_fraction("query", seed, doc_id), row


def hash_strings(values: Sequence[str]) -> str:
    digest = hashlib.blake2b(digest_size=16)
    for value in values:
        encoded = str(value).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def hash_edges(edges: np.ndarray) -> str:
    digest = hashlib.blake2b(digest_size=16)
    digest.update(str(edges.shape).encode("ascii"))
    digest.update(np.ascontiguousarray(edges, dtype=np.int32).tobytes())
    return digest.hexdigest()


def parse_referenced_edges(
    rows: Iterable[tuple[str, Any]],
    id_to_row: dict[str, int],
    *,
    edge_test_frac: float,
    split_seed: int,
) -> EdgeSplit:
    train_src: list[int] = []
    train_dst: list[int] = []
    test_src: list[int] = []
    test_dst: list[int] = []
    raw_edges = 0
    edges_in_corpus = 0
    self_edges_removed = 0
    seen_edges: set[tuple[int, int]] = set()

    for raw_src_id, referenced_works in rows:
        src_id = normalize_openalex_id(raw_src_id)
        src_row = id_to_row.get(src_id)
        if src_row is None:
            continue
        for dst_id in split_pipe_ids(referenced_works):
            raw_edges += 1
            dst_row = id_to_row.get(dst_id)
            if dst_row is None:
                continue
            if dst_row == src_row:
                self_edges_removed += 1
                continue
            edge_key = (src_row, dst_row)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edges_in_corpus += 1
            if stable_edge_is_test(src_id, dst_id, test_frac=edge_test_frac, seed=split_seed):
                test_src.append(src_row)
                test_dst.append(dst_row)
            else:
                train_src.append(src_row)
                train_dst.append(dst_row)

    train_edges = np.column_stack([train_src, train_dst]).astype(np.int32) if train_src else np.zeros((0, 2), dtype=np.int32)
    test_edges = np.column_stack([test_src, test_dst]).astype(np.int32) if test_src else np.zeros((0, 2), dtype=np.int32)
    return EdgeSplit(
        train_edges=train_edges,
        test_edges=test_edges,
        raw_edges=raw_edges,
        edges_in_corpus=edges_in_corpus,
        self_edges_removed=self_edges_removed,
    )


def select_queries(
    *,
    corpus: CorpusData,
    test_edges: np.ndarray,
    query_limit: int | None,
    query_field: str,
    split_seed: int,
) -> QuerySet:
    positives_by_src: dict[int, set[int]] = defaultdict(set)
    for src, dst in test_edges.tolist():
        positives_by_src[int(src)].add(int(dst))

    candidates: list[tuple[float, int]] = []
    for src_row, positives in positives_by_src.items():
        if not positives:
            continue
        query_text = format_query(corpus.titles[src_row], corpus.abstracts[src_row], query_field)
        if query_text:
            candidates.append(stable_row_order(src_row, corpus.doc_ids[src_row], seed=split_seed))
    candidates.sort()
    if query_limit is not None:
        candidates = candidates[:query_limit]

    query_doc_rows: list[int] = []
    query_ids: list[str] = []
    query_texts: list[str] = []
    qrels: dict[str, dict[str, int]] = {}
    for _, src_row in candidates:
        query_id = corpus.doc_ids[src_row]
        positives = positives_by_src[src_row]
        query_doc_rows.append(src_row)
        query_ids.append(query_id)
        query_texts.append(format_query(corpus.titles[src_row], corpus.abstracts[src_row], query_field))
        qrels[query_id] = {corpus.doc_ids[dst_row]: 1 for dst_row in sorted(positives)}

    return QuerySet(
        query_doc_rows=query_doc_rows,
        query_ids=query_ids,
        query_texts=query_texts,
        qrels=qrels,
    )


def dcg(gains: Sequence[int]) -> float:
    return sum((float((2**gain) - 1) / math.log2(rank + 2)) for rank, gain in enumerate(gains))


def evaluate_run(
    *,
    qrels: dict[str, dict[str, int]],
    query_ids: Sequence[str],
    ranked_doc_ids: Sequence[Sequence[str]],
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    evaluated = 0
    for query_id, retrieved in zip(query_ids, ranked_doc_ids, strict=False):
        rels = qrels.get(query_id)
        if not rels:
            continue
        positives = {doc_id for doc_id, score in rels.items() if score > 0}
        if not positives:
            continue
        evaluated += 1

        for k in (1, 5, 10):
            topk = list(retrieved[:k])
            hits = sum(1 for doc_id in topk if rels.get(doc_id, 0) > 0)
            totals[f"Precision@{k}"] += hits / float(k)

        for k in (10, 100):
            topk = set(retrieved[:k])
            hits = sum(1 for doc_id in positives if doc_id in topk)
            totals[f"Recall@{k}"] += hits / float(len(positives))

        rr = 0.0
        for rank, doc_id in enumerate(retrieved[:10], start=1):
            if rels.get(doc_id, 0) > 0:
                rr = 1.0 / float(rank)
                break
        totals["MRR@10"] += rr

        ap_sum = 0.0
        hits = 0
        for rank, doc_id in enumerate(retrieved[:100], start=1):
            if rels.get(doc_id, 0) > 0:
                hits += 1
                ap_sum += hits / float(rank)
        totals["MAP@100"] += ap_sum / float(len(positives))

        ideal_gains = sorted((score for score in rels.values() if score > 0), reverse=True)
        for k in (10, 100):
            gains = [int(rels.get(doc_id, 0)) for doc_id in retrieved[:k]]
            denom = dcg(ideal_gains[:k])
            totals[f"nDCG@{k}"] += (dcg(gains) / denom) if denom > 0 else 0.0

    if evaluated == 0:
        raise RuntimeError("No queries with positive qrels were evaluated")
    return {key: value / float(evaluated) for key, value in sorted(totals.items())}


def resolve_path(path: str | Path, *, base_dir: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


def read_openalex_corpus(
    parquet_paths: Sequence[Path],
    *,
    lang_filter: str,
    limit_docs: int | None,
) -> CorpusData:
    import pyarrow.parquet as pq

    doc_ids: list[str] = []
    titles: list[str] = []
    abstracts: list[str] = []
    languages: list[str] = []
    seen: set[str] = set()
    columns = ["id", "title", "abstract_text", "language"]
    for path in parquet_paths:
        if not path.exists():
            raise RuntimeError(f"Missing OpenAlex parquet file: {path}")
        table = pq.read_table(path, columns=columns)
        for row in table.to_pylist():
            language = str(row.get("language") or "").strip()
            if lang_filter != "any" and language != lang_filter:
                continue
            doc_id = normalize_openalex_id(row.get("id"))
            if not doc_id or doc_id in seen:
                continue
            title = str(row.get("title") or "").strip()
            abstract = str(row.get("abstract_text") or "").strip()
            if not format_document(title, abstract):
                continue
            seen.add(doc_id)
            doc_ids.append(doc_id)
            titles.append(title)
            abstracts.append(abstract)
            languages.append(language)
            if limit_docs is not None and len(doc_ids) >= limit_docs:
                return CorpusData(doc_ids=doc_ids, titles=titles, abstracts=abstracts, languages=languages)
    return CorpusData(doc_ids=doc_ids, titles=titles, abstracts=abstracts, languages=languages)


def read_openalex_edges(
    parquet_paths: Sequence[Path],
    *,
    id_to_row: dict[str, int],
    edge_test_frac: float,
    split_seed: int,
) -> EdgeSplit:
    import pyarrow.parquet as pq

    all_train: list[np.ndarray] = []
    all_test: list[np.ndarray] = []
    raw_edges = 0
    edges_in_corpus = 0
    self_edges_removed = 0
    for path in parquet_paths:
        table = pq.read_table(path, columns=["id", "referenced_works"])
        rows = ((row.get("id"), row.get("referenced_works")) for row in table.to_pylist())
        split = parse_referenced_edges(
            rows,
            id_to_row,
            edge_test_frac=edge_test_frac,
            split_seed=split_seed,
        )
        all_train.append(split.train_edges)
        all_test.append(split.test_edges)
        raw_edges += split.raw_edges
        edges_in_corpus += split.edges_in_corpus
        self_edges_removed += split.self_edges_removed

    train_edges = np.vstack([item for item in all_train if len(item)]) if any(len(item) for item in all_train) else np.zeros((0, 2), dtype=np.int32)
    test_edges = np.vstack([item for item in all_test if len(item)]) if any(len(item) for item in all_test) else np.zeros((0, 2), dtype=np.int32)
    if len(train_edges):
        train_edges = np.unique(train_edges, axis=0)
    if len(test_edges):
        test_edges = np.unique(test_edges, axis=0)
    return EdgeSplit(
        train_edges=train_edges.astype(np.int32, copy=False),
        test_edges=test_edges.astype(np.int32, copy=False),
        raw_edges=raw_edges,
        edges_in_corpus=edges_in_corpus,
        self_edges_removed=self_edges_removed,
    )


def shape_path(path: Path) -> Path:
    return path.with_name(path.name + ".shape.json")


def load_doc_embeddings(path: Path) -> tuple[np.memmap, int, int] | None:
    meta_path = shape_path(path)
    if not path.exists() or not meta_path.exists():
        return None
    with open(meta_path, "r", encoding="utf-8") as file_obj:
        n_docs, dim = json.load(file_obj)
    return np.memmap(path, dtype=np.float16, mode="r", shape=(int(n_docs), int(dim))), int(n_docs), int(dim)


def save_doc_ids(path: Path, doc_ids: Sequence[str]) -> None:
    np.save(path, np.asarray(list(doc_ids), dtype=str), allow_pickle=False)


def load_doc_ids(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    return [str(item) for item in np.load(path, allow_pickle=False).tolist()]


def write_doc_meta(path: Path, corpus: CorpusData) -> None:
    with open(path, "w", encoding="utf-8") as file_obj:
        for doc_id, title, language in zip(corpus.doc_ids, corpus.titles, corpus.languages, strict=True):
            file_obj.write(json.dumps({"id": doc_id, "title": title, "language": language}, ensure_ascii=False) + "\n")


def embed_documents_or_load(
    *,
    encoder: SemanticEncoder,
    corpus: CorpusData,
    embeddings_path: Path,
    model_name: str,
    doc_ids_hash: str,
    force: bool,
) -> tuple[np.memmap, int]:
    meta_path = embeddings_path.with_name("doc_embeddings.meta.json")
    cached = None if force else load_doc_embeddings(embeddings_path)
    if cached is not None:
        emb, n_docs, dim = cached
        meta_matches = False
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as file_obj:
                    meta = json.load(file_obj)
                meta_matches = meta.get("model") == model_name and meta.get("doc_ids_hash") == doc_ids_hash
            except (OSError, json.JSONDecodeError):
                meta_matches = False
        if n_docs == len(corpus.doc_ids) and dim == encoder.output_dim and meta_matches:
            log_phase(f"Using cached document embeddings: {embeddings_path}")
            return emb, dim

    import torch

    embeddings_path.parent.mkdir(parents=True, exist_ok=True)
    n_docs = len(corpus.doc_ids)
    dim = encoder.output_dim
    memmap = np.memmap(embeddings_path, dtype=np.float16, mode="w+", shape=(n_docs, dim))
    for start in tqdm(range(0, n_docs, encoder.config.batch_size), desc="Embed documents", unit="batch", dynamic_ncols=True):
        end = min(start + encoder.config.batch_size, n_docs)
        texts = [format_document(corpus.titles[idx], corpus.abstracts[idx]) for idx in range(start, end)]
        with torch.inference_mode():
            vectors = encoder._encode(texts, prefix=encoder.config.passage_prefix, max_length=encoder.config.max_passage_length)
        memmap[start:end] = vectors.astype(np.float16)
    memmap.flush()
    with open(shape_path(embeddings_path), "w", encoding="utf-8") as file_obj:
        json.dump([int(n_docs), int(dim)], file_obj)
    with open(meta_path, "w", encoding="utf-8") as file_obj:
        json.dump(
            {"model": model_name, "doc_ids_hash": doc_ids_hash, "documents": int(n_docs), "dimension": int(dim)},
            file_obj,
            ensure_ascii=False,
            indent=2,
        )
    return np.memmap(embeddings_path, dtype=np.float16, mode="r", shape=(n_docs, dim)), dim


def query_cache_name(
    *,
    model: str,
    query_field: str,
    split_seed: int,
    edge_test_frac: float,
    query_count: int,
    query_hash: str,
) -> str:
    model_slug = model.replace("/", "__").replace("\\", "__").replace(":", "_")
    frac_slug = str(edge_test_frac).replace(".", "p")
    return f"query_embeddings.{model_slug}.{query_field}.seed{split_seed}.frac{frac_slug}.n{query_count}.{query_hash}.npy"


def embed_queries_or_load(
    *,
    encoder: SemanticEncoder,
    query_texts: Sequence[str],
    cache_path: Path,
    force: bool,
) -> np.ndarray:
    if not force and cache_path.exists() and shape_path(cache_path).exists():
        cached = np.load(cache_path, allow_pickle=False).astype(np.float32, copy=False)
        if len(cached) == len(query_texts):
            log_phase(f"Using cached query embeddings: {cache_path}")
            return cached

    import torch

    chunks: list[np.ndarray] = []
    for start in tqdm(range(0, len(query_texts), encoder.config.batch_size), desc="Embed queries", unit="batch", dynamic_ncols=True):
        end = min(start + encoder.config.batch_size, len(query_texts))
        with torch.inference_mode():
            chunks.append(
                encoder._encode(
                    list(query_texts[start:end]),
                    prefix=encoder.config.query_prefix,
                    max_length=encoder.config.max_query_length,
                )
            )
    result = np.vstack(chunks) if chunks else np.zeros((0, encoder.output_dim), dtype=np.float32)
    np.save(cache_path, result.astype(np.float32, copy=False), allow_pickle=False)
    with open(shape_path(cache_path), "w", encoding="utf-8") as file_obj:
        json.dump(list(result.shape), file_obj)
    return result


def edge_batches_from_array(edges: np.ndarray, batch_size: int) -> Iterable[list[tuple[int, int]]]:
    for start in range(0, len(edges), batch_size):
        end = min(start + batch_size, len(edges))
        yield [(int(src), int(dst)) for src, dst in edges[start:end]]


def build_cache_if_needed(
    *,
    embeddings: np.memmap,
    train_edges: np.ndarray,
    cache_dir: Path,
    cache_meta: dict[str, Any],
    force: bool,
    edge_batch_size: int,
    vec_chunk: int,
    doc_chunk: int,
) -> float:
    from src.parser.citation_cache import build_citation_cache_from_batches

    n_docs, dim = embeddings.shape
    meta_path = cache_dir / "openalex_holdout_cache_meta.json"
    meta_matches = False
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as file_obj:
                meta_matches = json.load(file_obj) == cache_meta
        except (OSError, json.JSONDecodeError):
            meta_matches = False
    if not force and cache_ready(cache_dir, int(n_docs), int(dim)) and meta_matches:
        log_phase(f"Using cached citation features: {cache_dir}")
        return 0.0

    id_to_idx = {idx: idx for idx in range(int(n_docs))}

    def batches() -> Iterable[list[tuple[int, int]]]:
        return edge_batches_from_array(train_edges, edge_batch_size)

    start = time.perf_counter()
    build_citation_cache_from_batches(
        embeddings,
        id_to_idx,
        batches,
        cache_dir,
        vec_chunk=vec_chunk,
        doc_chunk=doc_chunk,
        keep_sums=False,
    )
    with open(meta_path, "w", encoding="utf-8") as file_obj:
        json.dump(cache_meta, file_obj, ensure_ascii=False, indent=2)
    return time.perf_counter() - start


def filter_ranked_indices(indices: np.ndarray, query_doc_rows: Sequence[int], top_k: int) -> list[list[int]]:
    filtered: list[list[int]] = []
    for row, self_idx in zip(indices, query_doc_rows, strict=False):
        out: list[int] = []
        for idx in row:
            idx_int = int(idx)
            if idx_int < 0 or idx_int == int(self_idx):
                continue
            out.append(idx_int)
            if len(out) >= top_k:
                break
        filtered.append(out)
    return filtered


def ranked_indices_to_doc_ids(ranked_indices: Sequence[Sequence[int]], doc_ids: Sequence[str]) -> list[list[str]]:
    return [[doc_ids[int(idx)] for idx in row] for row in ranked_indices]


def search_vectors(
    *,
    embeddings: np.memmap,
    query_vectors: np.ndarray,
    query_doc_rows: Sequence[int],
    top_k: int,
    doc_chunk: int,
    weights: dict[str, float] | None,
    cache_dir: Path | None,
) -> tuple[list[list[int]], dict[str, float]]:
    import faiss

    n_docs, dim = embeddings.shape
    index = faiss.IndexFlatIP(int(dim))

    out1 = in1 = out2 = in2 = None
    if weights is not None:
        if cache_dir is None:
            raise ValueError("cache_dir is required for weighted search")
        paths = cache_paths(cache_dir)
        out1 = np.memmap(paths["out1_mean"], dtype=np.float16, mode="r", shape=(n_docs, dim))
        in1 = np.memmap(paths["in1_mean"], dtype=np.float16, mode="r", shape=(n_docs, dim))
        out2 = np.memmap(paths["out2_mean"], dtype=np.float16, mode="r", shape=(n_docs, dim))
        in2 = np.memmap(paths["in2_mean"], dtype=np.float16, mode="r", shape=(n_docs, dim))

    build_start = time.perf_counter()
    for start in tqdm(range(0, n_docs, doc_chunk), desc="Build index", unit="doc", dynamic_ncols=True):
        end = min(start + doc_chunk, n_docs)
        base = np.asarray(embeddings[start:end], dtype=np.float32)
        if weights is None:
            faiss.normalize_L2(base)
            vectors = base
        else:
            vectors = build_weighted_vectors(
                base,
                np.asarray(out1[start:end], dtype=np.float32) if out1 is not None else None,
                np.asarray(in1[start:end], dtype=np.float32) if in1 is not None else None,
                np.asarray(out2[start:end], dtype=np.float32) if out2 is not None else None,
                np.asarray(in2[start:end], dtype=np.float32) if in2 is not None else None,
                weights,
                normalize=True,
            )
        index.add(vectors.astype(np.float32, copy=False))
    build_seconds = time.perf_counter() - build_start

    search_k = min(int(n_docs), int(top_k) + 1)
    search_start = time.perf_counter()
    _, indices = index.search(query_vectors.astype(np.float32, copy=False), search_k)
    search_seconds = time.perf_counter() - search_start
    ranked = filter_ranked_indices(indices, query_doc_rows, top_k)
    return ranked, {"index_build_seconds": build_seconds, "search_seconds": search_seconds}


def write_reports(
    *,
    out_dir: Path,
    metrics_by_run: dict[str, dict[str, float]],
    stats_by_run: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    metric_names = sorted({name for metrics in metrics_by_run.values() for name in metrics})

    with open(out_dir / "metrics.csv", "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=["run", *metric_names])
        writer.writeheader()
        for run, metrics in metrics_by_run.items():
            writer.writerow({"run": run, **{name: metrics.get(name, 0.0) for name in metric_names}})

    with open(out_dir / "metrics.json", "w", encoding="utf-8") as file_obj:
        json.dump({"params": params, "metrics": metrics_by_run, "stats": stats_by_run}, file_obj, ensure_ascii=False, indent=2)

    baseline = metrics_by_run["baseline"]
    citation = metrics_by_run["citation_aware"]
    lines = [
        "# OpenAlex Citation Holdout Retrieval Evaluation",
        "",
        "## Metrics",
        "",
        "| Metric | Baseline | Citation-aware | Delta | Relative |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in metric_names:
        base = baseline.get(name, 0.0)
        cited = citation.get(name, 0.0)
        delta = cited - base
        relative = (delta / base * 100.0) if base else 0.0
        lines.append(f"| {name} | {base:.6f} | {cited:.6f} | {delta:+.6f} | {relative:+.2f}% |")
    lines.extend(
        [
            "",
            "## Parameters",
            "",
            "```json",
            json.dumps(params, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Runtime Stats",
            "",
            "```json",
            json.dumps(stats_by_run, ensure_ascii=False, indent=2),
            "```",
        ]
    )
    with open(out_dir / "report.md", "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate OpenAlex citation holdout retrieval.")
    parser.add_argument(
        "--parquet",
        nargs="+",
        default=["data/processed/openalex_en.merged.parquet", "data/processed/openalex_ru.merged.parquet"],
        help="OpenAlex parquet files relative to services/semantic or absolute paths.",
    )
    parser.add_argument("--data-dir", default="data/eval/openalex_holdout")
    parser.add_argument("--out-dir", default="reports/openalex_holdout")
    parser.add_argument("--model", default="intfloat/multilingual-e5-large")
    parser.add_argument("--weights", default=DEFAULT_WEIGHTS)
    parser.add_argument("--edge-test-frac", type=float, default=0.2)
    parser.add_argument("--split-seed", type=int, default=42)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--limit-docs", type=int, default=None)
    parser.add_argument("--query-limit", type=int, default=5000)
    parser.add_argument("--lang-filter", choices=["any", "en", "ru"], default="any")
    parser.add_argument("--query-field", choices=["title", "title_abstract"], default="title")
    parser.add_argument("--doc-batch-size", type=int, default=64)
    parser.add_argument("--query-batch-size", type=int, default=64)
    parser.add_argument("--doc-chunk", type=int, default=4096)
    parser.add_argument("--edge-batch-size", type=int, default=200000)
    parser.add_argument("--vec-chunk", type=int, default=10000)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.edge_test_frac <= 0.0 or args.edge_test_frac >= 1.0:
        raise ValueError("--edge-test-frac must be in (0.0, 1.0)")
    if args.top_k < 1:
        raise ValueError("--top-k must be >= 1")
    return args


def main() -> None:
    total_start = time.perf_counter()
    args = parse_args()
    data_dir = resolve_path(args.data_dir, base_dir=ROOT_DIR)
    out_dir = resolve_path(args.out_dir, base_dir=ROOT_DIR)
    parquet_paths = [resolve_path(path, base_dir=ROOT_DIR) for path in args.parquet]
    data_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    log_phase("Loading OpenAlex corpus")
    corpus_start = time.perf_counter()
    corpus = read_openalex_corpus(parquet_paths, lang_filter=args.lang_filter, limit_docs=args.limit_docs)
    if not corpus.doc_ids:
        raise RuntimeError("No OpenAlex documents loaded")
    id_to_row = {doc_id: idx for idx, doc_id in enumerate(corpus.doc_ids)}
    save_doc_ids(data_dir / "doc_ids.npy", corpus.doc_ids)
    write_doc_meta(data_dir / "doc_meta.jsonl", corpus)

    log_phase("Building train/test citation edge split")
    edge_split = read_openalex_edges(
        parquet_paths,
        id_to_row=id_to_row,
        edge_test_frac=args.edge_test_frac,
        split_seed=args.split_seed,
    )
    if len(edge_split.train_edges) == 0:
        raise RuntimeError("No train citation edges found inside the eval corpus")
    if len(edge_split.test_edges) == 0:
        raise RuntimeError("No test citation edges found inside the eval corpus")
    np.save(data_dir / "train_edges.npy", edge_split.train_edges, allow_pickle=False)
    np.save(data_dir / "test_edges.npy", edge_split.test_edges, allow_pickle=False)

    query_set = select_queries(
        corpus=corpus,
        test_edges=edge_split.test_edges,
        query_limit=args.query_limit,
        query_field=args.query_field,
        split_seed=args.split_seed,
    )
    if not query_set.query_ids:
        raise RuntimeError("No query documents with withheld citation positives found")
    corpus_seconds = time.perf_counter() - corpus_start
    doc_ids_hash = hash_strings(corpus.doc_ids)
    query_hash = hash_strings(
        [
            f"{query_id}\x1f{query_text}"
            for query_id, query_text in zip(query_set.query_ids, query_set.query_texts, strict=True)
        ]
    )
    train_edges_hash = hash_edges(edge_split.train_edges)
    log_phase(
        f"Loaded {len(corpus.doc_ids)} docs, {len(query_set.query_ids)} queries, "
        f"{len(edge_split.train_edges)} train edges, {len(edge_split.test_edges)} test edges"
    )

    log_phase(f"Loading model: {args.model}")
    encoder = SemanticEncoder(
        EncoderConfig(
            model_name=args.model,
            batch_size=args.doc_batch_size,
        )
    )
    log_phase(f"Model loaded on {encoder.device}; output_dim={encoder.output_dim}")

    embedding_start = time.perf_counter()
    embeddings, dim = embed_documents_or_load(
        encoder=encoder,
        corpus=corpus,
        embeddings_path=data_dir / EMBEDDINGS_NAME,
        model_name=args.model,
        doc_ids_hash=doc_ids_hash,
        force=args.force,
    )
    encoder.config.batch_size = args.query_batch_size
    query_vectors = embed_queries_or_load(
        encoder=encoder,
        query_texts=query_set.query_texts,
        cache_path=data_dir
        / query_cache_name(
            model=args.model,
            query_field=args.query_field,
            split_seed=args.split_seed,
            edge_test_frac=args.edge_test_frac,
            query_count=len(query_set.query_ids),
            query_hash=query_hash,
        ),
        force=args.force,
    )
    embedding_seconds = time.perf_counter() - embedding_start

    cache_seconds = build_cache_if_needed(
        embeddings=embeddings,
        train_edges=edge_split.train_edges,
        cache_dir=data_dir / "citation_cache",
        cache_meta={
            "doc_ids_hash": doc_ids_hash,
            "train_edges_hash": train_edges_hash,
            "train_edges": int(len(edge_split.train_edges)),
            "edge_test_frac": args.edge_test_frac,
            "split_seed": args.split_seed,
            "limit_docs": args.limit_docs,
            "lang_filter": args.lang_filter,
            "dimension": int(dim),
        },
        force=args.force,
        edge_batch_size=args.edge_batch_size,
        vec_chunk=args.vec_chunk,
        doc_chunk=args.doc_chunk,
    )

    common_stats: dict[str, Any] = {
        "documents": len(corpus.doc_ids),
        "queries": len(query_set.query_ids),
        "raw_edges": edge_split.raw_edges,
        "edges_in_corpus": edge_split.edges_in_corpus,
        "self_edges_removed": edge_split.self_edges_removed,
        "train_edges": int(len(edge_split.train_edges)),
        "test_edges": int(len(edge_split.test_edges)),
        "corpus_seconds": corpus_seconds,
        "embedding_seconds": embedding_seconds,
        "citation_cache_seconds": cache_seconds,
        "dimension": dim,
    }

    metrics_by_run: dict[str, dict[str, float]] = {}
    stats_by_run: dict[str, dict[str, Any]] = {}

    log_phase("Searching baseline")
    baseline_ranked_idx, baseline_stats = search_vectors(
        embeddings=embeddings,
        query_vectors=query_vectors,
        query_doc_rows=query_set.query_doc_rows,
        top_k=args.top_k,
        doc_chunk=args.doc_chunk,
        weights=None,
        cache_dir=None,
    )
    baseline_ranked = ranked_indices_to_doc_ids(baseline_ranked_idx, corpus.doc_ids)
    metrics_by_run["baseline"] = evaluate_run(
        qrels=query_set.qrels,
        query_ids=query_set.query_ids,
        ranked_doc_ids=baseline_ranked,
    )
    stats_by_run["baseline"] = {**common_stats, **baseline_stats}

    log_phase("Searching citation-aware")
    weights = parse_weights(args.weights)
    citation_ranked_idx, citation_stats = search_vectors(
        embeddings=embeddings,
        query_vectors=query_vectors,
        query_doc_rows=query_set.query_doc_rows,
        top_k=args.top_k,
        doc_chunk=args.doc_chunk,
        weights=weights,
        cache_dir=data_dir / "citation_cache",
    )
    citation_ranked = ranked_indices_to_doc_ids(citation_ranked_idx, corpus.doc_ids)
    metrics_by_run["citation_aware"] = evaluate_run(
        qrels=query_set.qrels,
        query_ids=query_set.query_ids,
        ranked_doc_ids=citation_ranked,
    )
    stats_by_run["citation_aware"] = {**common_stats, **citation_stats}

    params = {
        "dataset": "OpenAlex citation holdout",
        "parquet": [str(path) for path in parquet_paths],
        "model": args.model,
        "weights": weights,
        "edge_test_frac": args.edge_test_frac,
        "split_seed": args.split_seed,
        "top_k": args.top_k,
        "limit_docs": args.limit_docs,
        "query_limit": args.query_limit,
        "lang_filter": args.lang_filter,
        "query_field": args.query_field,
        "data_dir": str(data_dir),
        "total_seconds": time.perf_counter() - total_start,
    }
    write_reports(out_dir=out_dir, metrics_by_run=metrics_by_run, stats_by_run=stats_by_run, params=params)
    log_phase(f"Wrote reports to {out_dir}")
    for run, metrics in metrics_by_run.items():
        log_phase(f"{run}: " + ", ".join(f"{key}={value:.4f}" for key, value in sorted(metrics.items())))


if __name__ == "__main__":
    main()

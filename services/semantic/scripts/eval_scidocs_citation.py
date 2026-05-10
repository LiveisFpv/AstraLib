#!/usr/bin/env python3
"""Evaluate SCIDOCS retrieval with plain and citation-aware document vectors."""

from __future__ import annotations

import argparse
import csv
import json
from json import JSONDecodeError
import math
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import quote

import numpy as np
from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))


BEIR_CORPUS_URLS = [
    "https://huggingface.co/datasets/BeIR/scidocs/resolve/main/corpus/corpus-00000-of-00001.parquet",
    "https://huggingface.co/datasets/BeIR/scidocs/resolve/a16f934d922c12d1623e1c4e37a05e16adfaf86a/corpus/corpus/0000.parquet",
    "https://huggingface.co/datasets/BeIR/scidocs/resolve/main/corpus/corpus/0000.parquet",
    "https://huggingface.co/datasets/BeIR/scidocs/resolve/bd21f410749e22fdf6f19b39613a93fedd2b4d41/corpus/corpus/0000.parquet",
]
BEIR_QUERIES_URLS = [
    "https://huggingface.co/datasets/BeIR/scidocs/resolve/main/queries/queries-00000-of-00001.parquet",
    "https://huggingface.co/datasets/BeIR/scidocs/resolve/a16f934d922c12d1623e1c4e37a05e16adfaf86a/queries/queries/0000.parquet",
    "https://huggingface.co/datasets/BeIR/scidocs/resolve/main/queries/queries/0000.parquet",
    "https://huggingface.co/datasets/BeIR/scidocs/resolve/bd21f410749e22fdf6f19b39613a93fedd2b4d41/queries/queries/0000.parquet",
]
BEIR_QRELS_URLS = [
    "https://huggingface.co/datasets/BeIR/scidocs-qrels/resolve/main/test.tsv",
]
SCIDOCS_S3_BUCKET_URL = "https://ai2-s2-research-public.s3-us-west-2.amazonaws.com"
SCIDOCS_S3_PREFIX = "specter/scidocs/"


@dataclass(slots=True)
class TextRecord:
    record_id: str
    text: str


@dataclass(slots=True)
class EvalData:
    corpus: list[TextRecord]
    queries: list[TextRecord]
    qrels: dict[str, dict[str, int]]
    edges: list[tuple[str, str]]


def download_file(urls: Sequence[str], out_path: Path) -> None:
    import requests

    out_path.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in urls:
        try:
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
                with open(tmp_path, "wb") as file_obj:
                    progress = tqdm(
                        total=total or None,
                        desc=f"Download {out_path.name}",
                        unit="B",
                        unit_scale=True,
                        dynamic_ncols=True,
                    )
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        file_obj.write(chunk)
                        progress.update(len(chunk))
                    progress.close()
                os.replace(tmp_path, out_path)
                return
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(f"Failed to download {out_path}. Tried:\n" + "\n".join(errors))


def download_beir_files(
    data_dir: Path,
    *,
    limit_docs: int | None = None,
    limit_queries: int | None = None,
) -> None:
    _ = (limit_docs, limit_queries)
    beir_dir = data_dir / "beir"
    corpus_parquet = beir_dir / "corpus.parquet"
    if corpus_parquet.exists():
        print(f"Found {corpus_parquet}")
    else:
        download_file(BEIR_CORPUS_URLS, corpus_parquet)

    queries_parquet = beir_dir / "queries.parquet"
    if queries_parquet.exists():
        print(f"Found {queries_parquet}")
    else:
        download_file(BEIR_QUERIES_URLS, queries_parquet)

    qrels_path = beir_dir / "qrels-test.tsv"
    if qrels_path.exists():
        print(f"Found {qrels_path}")
    else:
        download_file(BEIR_QRELS_URLS, qrels_path)


def list_public_s3_prefix(*, bucket_url: str, prefix: str) -> list[tuple[str, int]]:
    import requests

    keys: list[tuple[str, int]] = []
    continuation_token: str | None = None
    while True:
        params = {
            "list-type": "2",
            "prefix": prefix,
            "max-keys": "1000",
        }
        if continuation_token:
            params["continuation-token"] = continuation_token
        response = requests.get(bucket_url, params=params, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        contents = root.findall("s3:Contents", namespace)
        if not contents and root.findall("Contents"):
            namespace = {}
            contents = root.findall("Contents")
        for item in contents:
            key_node = item.find("s3:Key", namespace) if namespace else item.find("Key")
            size_node = item.find("s3:Size", namespace) if namespace else item.find("Size")
            if key_node is None or not key_node.text:
                continue
            size = int(size_node.text or 0) if size_node is not None else 0
            keys.append((key_node.text, size))

        truncated_node = root.find("s3:IsTruncated", namespace) if namespace else root.find("IsTruncated")
        is_truncated = (truncated_node is not None and (truncated_node.text or "").lower() == "true")
        if not is_truncated:
            break
        token_node = (
            root.find("s3:NextContinuationToken", namespace)
            if namespace
            else root.find("NextContinuationToken")
        )
        if token_node is None or not token_node.text:
            break
        continuation_token = token_node.text
    return keys


def sync_public_s3_prefix(*, bucket_url: str, prefix: str, out_dir: Path) -> None:
    import requests

    objects = list_public_s3_prefix(bucket_url=bucket_url, prefix=prefix)
    if not objects:
        raise RuntimeError(f"No objects found at public S3 prefix: {bucket_url}/{prefix}")

    total_bytes = sum(size for _, size in objects)
    print(f"Downloading SciDocs data without awscli: {len(objects)} files, {total_bytes / (1024 ** 3):.2f} GiB")
    for key, size in objects:
        relative_key = key[len(prefix) :] if key.startswith(prefix) else key
        if not relative_key or relative_key.endswith("/"):
            continue
        target = out_dir / relative_key
        if target.exists() and target.stat().st_size == size:
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"{bucket_url}/{quote(key, safe='/')}"
        tmp_path = target.with_suffix(target.suffix + ".tmp")
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with open(tmp_path, "wb") as file_obj:
                progress = tqdm(
                    total=size or None,
                    desc=f"Download {relative_key}",
                    unit="B",
                    unit_scale=True,
                    dynamic_ncols=True,
                )
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    file_obj.write(chunk)
                    progress.update(len(chunk))
                progress.close()
        os.replace(tmp_path, target)


def download_scidocs_data(data_dir: Path) -> None:
    scidocs_dir = data_dir / "original"
    marker_candidates = [
        scidocs_dir / "paper_metadata_view_cite_read.json",
        scidocs_dir / "paper_metadata_recomm.json",
    ]
    if any(path.exists() for path in marker_candidates):
        print(f"Found SciDocs data at {scidocs_dir}")
        return

    aws = shutil.which("aws")
    if not aws:
        sync_public_s3_prefix(
            bucket_url=SCIDOCS_S3_BUCKET_URL,
            prefix=SCIDOCS_S3_PREFIX,
            out_dir=scidocs_dir,
        )
    else:
        scidocs_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            aws,
            "s3",
            "sync",
            "--no-sign-request",
            "s3://ai2-s2-research-public/specter/scidocs/",
            str(scidocs_dir),
        ]
        subprocess.run(cmd, check=True)

    if not any(path.exists() for path in marker_candidates):
        raise RuntimeError(f"SciDocs download finished, but expected metadata files are missing in {scidocs_dir}")


def load_beir_records(path: Path, *, limit: int | None = None) -> list[TextRecord]:
    if not path.exists():
        raise RuntimeError(f"Missing BEIR record file: {path}")
    import pyarrow.parquet as pq

    rows = pq.read_table(path).to_pylist()
    records: list[TextRecord] = []
    for row in rows:
        record_id = str(row.get("_id") or row.get("id") or row.get("doc_id") or "").strip()
        if not record_id:
            continue
        title = str(row.get("title") or "").strip()
        text = str(row.get("text") or row.get("abstract") or "").strip()
        combined = "\n".join(part for part in (title, text) if part)
        if combined:
            records.append(TextRecord(record_id=record_id, text=combined))
        if limit and len(records) >= limit:
            break
    return records


def load_qrels(path: Path, *, query_ids: set[str] | None = None) -> dict[str, dict[str, int]]:
    if not path.exists():
        raise RuntimeError(f"Missing BEIR qrels file: {path}")
    result: dict[str, dict[str, int]] = defaultdict(dict)
    with open(path, "r", encoding="utf-8") as file_obj:
        reader = csv.DictReader(file_obj, delimiter="\t")
        for row in reader:
            query_id = str(row.get("query-id") or row.get("query_id") or "").strip()
            corpus_id = str(row.get("corpus-id") or row.get("corpus_id") or "").strip()
            if not query_id or not corpus_id:
                continue
            if query_ids is not None and query_id not in query_ids:
                continue
            try:
                score = int(float(row.get("score") or 0))
            except ValueError:
                score = 0
            result[query_id][corpus_id] = score
    return dict(result)


def _read_json_records(path: Path) -> Iterable[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as file_obj:
        first = file_obj.read(1)
        file_obj.seek(0)
        if first in "[{":
            try:
                payload = json.load(file_obj)
                if isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict):
                            yield item
                elif isinstance(payload, dict):
                    for key, value in payload.items():
                        if isinstance(value, dict):
                            item = dict(value)
                            item.setdefault("paper_id", key)
                            yield item
                return
            except JSONDecodeError:
                file_obj.seek(0)
        for line in file_obj:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                yield item


def _coerce_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iter_neighbor_values(record: dict[str, Any]) -> Iterable[Any]:
    keys = {
        "references",
        "reference_ids",
        "cited_paper_ids",
        "citations",
        "citation_ids",
        "outbound_citations",
        "out_citations",
        "cites",
        "cited",
    }
    for key, value in record.items():
        normalized = str(key).strip().lower()
        if normalized not in keys:
            continue
        if isinstance(value, list):
            yield from value
        elif isinstance(value, tuple):
            yield from value
        elif isinstance(value, dict):
            yield from value.values()


def _iter_values(record: dict[str, Any], keys: set[str]) -> Iterable[Any]:
    for key, value in record.items():
        normalized = str(key).strip().lower()
        if normalized not in keys:
            continue
        if isinstance(value, list):
            yield from value
        elif isinstance(value, tuple):
            yield from value
        elif isinstance(value, dict):
            yield from value.values()


def load_edges_from_file(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        raise RuntimeError(f"Missing citation edge file: {path}")
    suffix = path.suffix.lower()
    edges: list[tuple[str, str]] = []

    if suffix == ".qrel":
        with open(path, "r", encoding="utf-8") as file_obj:
            for line in file_obj:
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                src, _, dst, score = parts[:4]
                try:
                    relevant = float(score) > 0
                except ValueError:
                    relevant = False
                if relevant:
                    edges.append((src, dst))
        return edges

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with open(path, "r", encoding="utf-8") as file_obj:
            reader = csv.DictReader(file_obj, delimiter=delimiter)
            for row in reader:
                src = _coerce_id(
                    row.get("source_id")
                    or row.get("src_id")
                    or row.get("src")
                    or row.get("source")
                    or row.get("query_id")
                    or row.get("pid")
                )
                dst = _coerce_id(
                    row.get("target_id")
                    or row.get("dst_id")
                    or row.get("dst")
                    or row.get("target")
                    or row.get("corpus_id")
                    or row.get("clicked_pid")
                )
                if src and dst:
                    edges.append((src, dst))
        return edges

    if suffix == ".parquet":
        import pyarrow.parquet as pq

        table = pq.read_table(path)
        columns = set(table.column_names)
        src_col = next((c for c in ("source_id", "src_id", "src", "source") if c in columns), None)
        dst_col = next((c for c in ("target_id", "dst_id", "dst", "target") if c in columns), None)
        if not src_col or not dst_col:
            raise RuntimeError(f"Parquet edge file lacks source/target columns: {path}")
        src_values = table[src_col].to_pylist()
        dst_values = table[dst_col].to_pylist()
        for src, dst in zip(src_values, dst_values, strict=False):
            src_id = _coerce_id(src)
            dst_id = _coerce_id(dst)
            if src_id and dst_id:
                edges.append((src_id, dst_id))
        return edges

    outbound_keys = {
        "references",
        "reference_ids",
        "cited_paper_ids",
        "citations",
        "citation_ids",
        "outbound_citations",
        "out_citations",
        "cites",
        "cited",
    }
    inbound_keys = {
        "cited_by",
        "citedby",
        "inbound_citations",
        "in_citations",
    }
    for record in _read_json_records(path):
        src = _coerce_id(
            record.get("paper_id")
            or record.get("paperId")
            or record.get("id")
            or record.get("_id")
            or record.get("source_id")
        )
        if not src:
            continue
        for raw_dst in _iter_values(record, outbound_keys):
            if isinstance(raw_dst, dict):
                raw_dst = raw_dst.get("paper_id") or raw_dst.get("paperId") or raw_dst.get("id")
            dst = _coerce_id(raw_dst)
            if dst:
                edges.append((src, dst))
        for raw_citing in _iter_values(record, inbound_keys):
            if isinstance(raw_citing, dict):
                raw_citing = raw_citing.get("paper_id") or raw_citing.get("paperId") or raw_citing.get("id")
            citing = _coerce_id(raw_citing)
            if citing:
                edges.append((citing, src))
    return edges


def discover_scidocs_edge_files(scidocs_dir: Path) -> list[Path]:
    if not scidocs_dir.exists():
        return []
    compact_candidates: list[Path] = []
    metadata_candidates: list[Path] = []
    for path in scidocs_dir.rglob("*"):
        if path.suffix.lower() not in {".json", ".jsonl", ".csv", ".tsv", ".qrel", ".parquet"}:
            continue
        name = path.name.lower()
        if "test" in name or "pid2anns" in name or "qrels" in name:
            continue
        parent = path.parent.name.lower()
        if path.suffix.lower() == ".qrel" and parent in {"cite", "cocite", "coread", "coview"}:
            compact_candidates.append(path)
            continue
        if path.suffix.lower() == ".csv" and name in {"train.csv", "val.csv"}:
            compact_candidates.append(path)
            continue
        if any(token in name for token in ("cite", "citation", "view_cite_read", "metadata")):
            metadata_candidates.append(path)
    return sorted(compact_candidates) or sorted(metadata_candidates, key=lambda item: item.stat().st_size)


def remove_qrel_edges(
    edges: Iterable[tuple[str, str]],
    qrels: dict[str, dict[str, int]],
) -> tuple[list[tuple[str, str]], int]:
    forbidden = {
        (str(query_id), str(doc_id))
        for query_id, docs in qrels.items()
        for doc_id, score in docs.items()
        if int(score) > 0
    }
    filtered: list[tuple[str, str]] = []
    removed = 0
    seen: set[tuple[str, str]] = set()
    for src, dst in edges:
        edge = (str(src), str(dst))
        if edge in forbidden:
            removed += 1
            continue
        if edge in seen:
            continue
        seen.add(edge)
        filtered.append(edge)
    return filtered, removed


def load_scidocs_edges(
    *,
    scidocs_dir: Path,
    qrels: dict[str, dict[str, int]],
    explicit_edges: Sequence[Path],
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    files = list(explicit_edges) if explicit_edges else discover_scidocs_edge_files(scidocs_dir)
    if not files:
        raise RuntimeError(
            "No SciDocs citation graph files found. Provide --scidocs-edge-file or download the original "
            "SciDocs data; citation-aware evaluation will not use BEIR test qrels as graph edges."
        )

    edges: list[tuple[str, str]] = []
    loaded_files: list[str] = []
    for path in files:
        file_edges = load_edges_from_file(path)
        if file_edges:
            edges.extend(file_edges)
            loaded_files.append(str(path))

    filtered, removed = remove_qrel_edges(edges, qrels)
    if not filtered:
        raise RuntimeError(
            "SciDocs graph files were found but yielded no usable non-test citation edges. "
            "Check --scidocs-edge-file and file schema."
        )
    return filtered, {
        "edge_files": loaded_files,
        "raw_edges": len(edges),
        "edges_removed_as_test_qrels": removed,
        "edges_used": len(filtered),
    }


def build_neighbor_means(
    *,
    doc_ids: list[str],
    embeddings: np.ndarray,
    edges: Sequence[tuple[str, str]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_docs, dim = embeddings.shape
    id_to_idx = {doc_id: idx for idx, doc_id in enumerate(doc_ids)}
    out_neighbors: list[list[int]] = [[] for _ in range(n_docs)]
    in_neighbors: list[list[int]] = [[] for _ in range(n_docs)]
    for src, dst in edges:
        src_idx = id_to_idx.get(src)
        dst_idx = id_to_idx.get(dst)
        if src_idx is None or dst_idx is None:
            continue
        out_neighbors[src_idx].append(dst_idx)
        in_neighbors[dst_idx].append(src_idx)

    def mean_for(rows: list[int]) -> np.ndarray:
        if not rows:
            return np.zeros((dim,), dtype=np.float32)
        return embeddings[rows].astype(np.float32).mean(axis=0)

    out1 = np.zeros((n_docs, dim), dtype=np.float32)
    in1 = np.zeros((n_docs, dim), dtype=np.float32)
    out2 = np.zeros((n_docs, dim), dtype=np.float32)
    in2 = np.zeros((n_docs, dim), dtype=np.float32)
    for idx in tqdm(range(n_docs), desc="Build citation features", unit="doc", dynamic_ncols=True):
        out1[idx] = mean_for(out_neighbors[idx])
        in1[idx] = mean_for(in_neighbors[idx])
        out2_ids = [second for first in out_neighbors[idx] for second in out_neighbors[first]]
        in2_ids = [second for first in in_neighbors[idx] for second in in_neighbors[first]]
        out2[idx] = mean_for(out2_ids)
        in2[idx] = mean_for(in2_ids)
    return out1, in1, out2, in2


def _shape_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".shape.json")


def save_embedding_cache(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, arr.astype(np.float32, copy=False))
    with open(_shape_path(path), "w", encoding="utf-8") as file_obj:
        json.dump(list(arr.shape), file_obj)


def load_embedding_cache(path: Path) -> np.ndarray | None:
    if not path.exists() or not _shape_path(path).exists():
        return None
    return np.load(path, allow_pickle=False).astype(np.float32, copy=False)


def embed_or_load(
    *,
    cache_path: Path,
    texts: Sequence[str],
    encoder: Any,
    mode: str,
    force: bool,
) -> np.ndarray:
    if not force:
        cached = load_embedding_cache(cache_path)
        if cached is not None and len(cached) == len(texts):
            print(f"Using cached {mode} embeddings: {cache_path}")
            return cached

    if mode == "query":
        import torch

        chunks: list[np.ndarray] = []
        for start in tqdm(range(0, len(texts), encoder.config.batch_size), desc="Embed queries", unit="batch"):
            batch = texts[start : start + encoder.config.batch_size]
            with torch.inference_mode():
                chunks.append(
                    encoder._encode(
                        list(batch),
                        prefix=encoder.config.query_prefix,
                        max_length=encoder.config.max_query_length,
                    )
                )
        embeddings = np.vstack(chunks) if chunks else np.zeros((0, encoder.output_dim), dtype=np.float32)
    elif mode == "passage":
        embeddings = encoder.embed_passages(texts)
    else:
        raise ValueError(f"Unsupported embedding mode: {mode}")

    save_embedding_cache(cache_path, embeddings)
    return embeddings


def dcg(gains: Sequence[int]) -> float:
    return sum((float((2**gain) - 1) / math.log2(rank + 2)) for rank, gain in enumerate(gains))


def evaluate_run(
    *,
    qrels: dict[str, dict[str, int]],
    query_ids: Sequence[str],
    ranked_doc_ids: Sequence[Sequence[str]],
) -> dict[str, float]:
    ks_precision = [1, 5, 10]
    ks_recall = [10, 100]
    ks_ndcg = [10, 100]
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

        for k in ks_precision:
            topk = list(retrieved[:k])
            hits = sum(1 for doc_id in topk if rels.get(doc_id, 0) > 0)
            totals[f"Precision@{k}"] += hits / float(k)

        for k in ks_recall:
            topk = set(retrieved[:k])
            hits = sum(1 for doc_id in positives if doc_id in topk)
            totals[f"Recall@{k}"] += hits / float(len(positives))

        top10 = list(retrieved[:10])
        rr = 0.0
        for rank, doc_id in enumerate(top10, start=1):
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
        for k in ks_ndcg:
            gains = [int(rels.get(doc_id, 0)) for doc_id in retrieved[:k]]
            ideal = ideal_gains[:k]
            denom = dcg(ideal)
            totals[f"nDCG@{k}"] += (dcg(gains) / denom) if denom > 0 else 0.0

    if evaluated == 0:
        raise RuntimeError("No queries with positive qrels were evaluated")
    return {key: value / float(evaluated) for key, value in sorted(totals.items())}


def search_index(doc_vectors: np.ndarray, query_vectors: np.ndarray, top_k: int) -> tuple[np.ndarray, float, float]:
    import faiss

    start = time.perf_counter()
    index = faiss.IndexFlatIP(doc_vectors.shape[1])
    index.add(doc_vectors.astype(np.float32, copy=False))
    build_seconds = time.perf_counter() - start
    start = time.perf_counter()
    _, indices = index.search(query_vectors.astype(np.float32, copy=False), top_k)
    search_seconds = time.perf_counter() - start
    return indices, build_seconds, search_seconds


def parse_float_values(raw: str) -> list[float]:
    values = [float(item.strip()) for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("Weight value list cannot be empty")
    return values


def weights_key(weights: dict[str, float]) -> tuple[float, float, float, float, float]:
    return (
        float(weights.get("self", 0.0)),
        float(weights.get("out1", 0.0)),
        float(weights.get("in1", 0.0)),
        float(weights.get("out2", 0.0)),
        float(weights.get("in2", 0.0)),
    )


def format_weights(weights: dict[str, float]) -> str:
    return (
        f"self={weights['self']:g},out1={weights['out1']:g},in1={weights['in1']:g},"
        f"out2={weights['out2']:g},in2={weights['in2']:g}"
    )


def make_weight_sets(args: argparse.Namespace, parse_weights_fn: Any) -> list[dict[str, float]]:
    primary = parse_weights_fn(args.weights)
    if not args.grid_search:
        return [primary]

    weight_sets: list[dict[str, float]] = [primary]
    for self_w, out1_w, in1_w, out2_w, in2_w in product(
        parse_float_values(args.self_vals),
        parse_float_values(args.out1_vals),
        parse_float_values(args.in1_vals),
        parse_float_values(args.out2_vals),
        parse_float_values(args.in2_vals),
    ):
        weight_sets.append(
            {
                "self": self_w,
                "out1": out1_w,
                "in1": in1_w,
                "out2": out2_w,
                "in2": in2_w,
            }
        )

    deduped: list[dict[str, float]] = []
    seen: set[tuple[float, float, float, float, float]] = set()
    for weights in weight_sets:
        key = weights_key(weights)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(weights)
    return deduped


def indices_to_doc_ids(indices: np.ndarray, doc_ids: Sequence[str]) -> list[list[str]]:
    out: list[list[str]] = []
    for row in indices:
        out.append([doc_ids[int(idx)] for idx in row if int(idx) >= 0])
    return out


def write_reports(
    *,
    out_dir: Path,
    metrics_by_run: dict[str, dict[str, float]],
    stats_by_run: dict[str, dict[str, Any]],
    params: dict[str, Any],
    optimize_metric: str = "nDCG@10",
    top_runs: int = 20,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    metric_names = sorted({name for metrics in metrics_by_run.values() for name in metrics})

    csv_path = out_dir / "metrics.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=["run", "weights", *metric_names])
        writer.writeheader()
        for run, metrics in metrics_by_run.items():
            run_stats = stats_by_run.get(run, {})
            writer.writerow(
                {
                    "run": run,
                    "weights": run_stats.get("weights", ""),
                    **{name: metrics.get(name, 0.0) for name in metric_names},
                }
            )

    json_path = out_dir / "metrics.json"
    with open(json_path, "w", encoding="utf-8") as file_obj:
        json.dump(
            {
                "params": params,
                "metrics": metrics_by_run,
                "stats": stats_by_run,
            },
            file_obj,
            ensure_ascii=False,
            indent=2,
        )

    baseline = metrics_by_run["baseline"]
    compared_runs = [run for run in metrics_by_run if run != "baseline"]
    best_run = max(
        compared_runs,
        key=lambda run: metrics_by_run[run].get(optimize_metric, float("-inf")),
        default="citation_aware" if "citation_aware" in metrics_by_run else "",
    )
    selected_run = best_run or ("citation_aware" if "citation_aware" in metrics_by_run else "")
    citation = metrics_by_run[selected_run] if selected_run else {}
    lines = [
        "# SCIDOCS Citation-Aware Retrieval Evaluation",
        "",
        "## Metrics",
        "",
        f"Selected run: `{selected_run}`",
        "",
        "| Metric | Baseline | Selected | Delta | Relative |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in metric_names:
        base = baseline.get(name, 0.0)
        cited = citation.get(name, 0.0)
        delta = cited - base
        relative = (delta / base * 100.0) if base else 0.0
        lines.append(f"| {name} | {base:.6f} | {cited:.6f} | {delta:+.6f} | {relative:+.2f}% |")
    if best_run and len(compared_runs) > 1:
        ranked_runs = sorted(
            compared_runs,
            key=lambda run: metrics_by_run[run].get(optimize_metric, float("-inf")),
            reverse=True,
        )[:top_runs]
        lines.extend(
            [
                "",
                f"## Top Runs by {optimize_metric}",
                "",
                "| Rank | Run | Weights | Score | Delta vs Baseline |",
                "| ---: | --- | --- | ---: | ---: |",
            ]
        )
        baseline_score = baseline.get(optimize_metric, 0.0)
        for rank, run in enumerate(ranked_runs, start=1):
            score = metrics_by_run[run].get(optimize_metric, 0.0)
            delta = score - baseline_score
            weight_text = stats_by_run.get(run, {}).get("weights", "")
            lines.append(f"| {rank} | `{run}` | `{weight_text}` | {score:.6f} | {delta:+.6f} |")
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


def log_phase(message: str) -> None:
    print(f"[scidocs-eval] {message}", flush=True)


def load_eval_data(args: argparse.Namespace) -> tuple[EvalData, dict[str, Any]]:
    data_dir = Path(args.data_dir)
    if args.download:
        download_beir_files(
            data_dir,
            limit_docs=args.limit_docs,
            limit_queries=args.limit_queries,
        )
        download_scidocs_data(data_dir)

    beir_dir = data_dir / "beir"
    corpus_path = beir_dir / "corpus.parquet"
    queries_path = beir_dir / "queries.parquet"

    corpus = load_beir_records(corpus_path, limit=args.limit_docs)
    queries = load_beir_records(queries_path, limit=args.limit_queries)
    query_ids = {item.record_id for item in queries}
    qrels = load_qrels(data_dir / "beir" / "qrels-test.tsv", query_ids=query_ids)

    edge_paths = [Path(path) for path in args.scidocs_edge_file]
    edges, edge_stats = load_scidocs_edges(
        scidocs_dir=data_dir / "original",
        qrels=qrels,
        explicit_edges=edge_paths,
    )
    return EvalData(corpus=corpus, queries=queries, qrels=qrels, edges=edges), edge_stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/eval/scidocs")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--model", default="intfloat/multilingual-e5-large")
    parser.add_argument("--weights", default="self=1.0,out1=0.0,in1=0.05,out2=0.03,in2=0.025")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--query-batch-size", type=int, default=64)
    parser.add_argument("--doc-batch-size", type=int, default=64)
    parser.add_argument("--out-dir", default="reports/scidocs")
    parser.add_argument("--scidocs-edge-file", action="append", default=[])
    parser.add_argument("--limit-docs", type=int)
    parser.add_argument("--limit-queries", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--grid-search", action="store_true", help="Evaluate a grid of citation-aware weights.")
    parser.add_argument("--self-vals", default="1.0")
    parser.add_argument("--out1-vals", default="0.0,0.01,0.03,0.05")
    parser.add_argument("--in1-vals", default="0.0,0.025,0.05,0.075,0.1")
    parser.add_argument("--out2-vals", default="0.0,0.01,0.03,0.05")
    parser.add_argument("--in2-vals", default="0.0,0.01,0.025,0.05")
    parser.add_argument("--optimize-metric", default="nDCG@10")
    parser.add_argument("--top-runs", type=int, default=20)
    parser.add_argument(
        "--smoke-model",
        action="store_true",
        help="Use intfloat/multilingual-e5-small for quick local smoke runs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.smoke_model:
        args.model = "intfloat/multilingual-e5-small"
    log_phase("Importing encoder and vector helpers")
    from src.al_models.e5.encoder import EncoderConfig, SemanticEncoder
    from src.parser.citation_cache import build_weighted_vectors, parse_weights

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    started = time.perf_counter()
    log_phase("Loading SCIDOCS/BEIR data")
    eval_data, edge_stats = load_eval_data(args)
    if not eval_data.corpus:
        raise RuntimeError("SCIDOCS corpus is empty")
    if not eval_data.queries:
        raise RuntimeError("SCIDOCS queries are empty")
    log_phase(
        f"Loaded {len(eval_data.corpus)} documents, {len(eval_data.queries)} queries, "
        f"{len(eval_data.qrels)} qrel query groups, {len(eval_data.edges)} graph edges"
    )

    weight_sets = make_weight_sets(args, parse_weights)
    log_phase(f"Weight sets to evaluate: {len(weight_sets)}")
    log_phase(f"Loading model: {args.model}")
    encoder = SemanticEncoder(
        EncoderConfig(
            model_name=args.model,
            batch_size=args.doc_batch_size,
        )
    )
    log_phase(f"Model loaded on {encoder.device}; output_dim={encoder.output_dim}")
    cache_dir = data_dir / "cache"
    model_slug = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in args.model)
    doc_texts = [item.text for item in eval_data.corpus]
    query_texts = [item.text for item in eval_data.queries]
    doc_ids = [item.record_id for item in eval_data.corpus]
    query_ids = [item.record_id for item in eval_data.queries]

    embedding_start = time.perf_counter()
    log_phase("Embedding documents")
    doc_vectors = embed_or_load(
        cache_path=cache_dir / f"{model_slug}_doc_embeddings.npy",
        texts=doc_texts,
        encoder=encoder,
        mode="passage",
        force=args.force,
    )
    log_phase(f"Document embeddings ready: shape={doc_vectors.shape}")
    encoder.config.batch_size = args.query_batch_size
    log_phase("Embedding queries")
    query_vectors = embed_or_load(
        cache_path=cache_dir / f"{model_slug}_query_embeddings.npy",
        texts=query_texts,
        encoder=encoder,
        mode="query",
        force=args.force,
    )
    log_phase(f"Query embeddings ready: shape={query_vectors.shape}")
    embedding_seconds = time.perf_counter() - embedding_start
    encoder.close()
    log_phase(f"Embedding stage finished in {embedding_seconds:.2f}s")

    log_phase("Searching baseline IndexFlatIP")
    baseline_indices, baseline_build, baseline_search = search_index(
        doc_vectors,
        query_vectors,
        args.top_k,
    )
    baseline_ranked = indices_to_doc_ids(baseline_indices, doc_ids)
    baseline_metrics = evaluate_run(
        qrels=eval_data.qrels,
        query_ids=query_ids,
        ranked_doc_ids=baseline_ranked,
    )
    log_phase("Baseline metrics computed")

    feature_start = time.perf_counter()
    log_phase("Building citation-neighborhood vectors")
    out1, in1, out2, in2 = build_neighbor_means(
        doc_ids=doc_ids,
        embeddings=doc_vectors,
        edges=eval_data.edges,
    )
    feature_seconds = time.perf_counter() - feature_start
    log_phase(f"Citation-neighborhood vectors ready in {feature_seconds:.2f}s")

    metrics_by_run: dict[str, dict[str, float]] = {"baseline": baseline_metrics}
    citation_stats_by_run: dict[str, dict[str, Any]] = {}
    best_run = ""
    best_score = float("-inf")
    primary_weight_key = weights_key(parse_weights(args.weights))
    for idx, weights in enumerate(weight_sets, start=1):
        run_name = "citation_aware" if weights_key(weights) == primary_weight_key else f"grid_{idx:04d}"
        if run_name in metrics_by_run:
            run_name = f"grid_{idx:04d}"
        log_phase(f"Searching {run_name} ({idx}/{len(weight_sets)}): {format_weights(weights)}")
        weighted_start = time.perf_counter()
        citation_vectors = build_weighted_vectors(
            doc_vectors,
            out1,
            in1,
            out2,
            in2,
            weights,
            normalize=True,
        )
        vector_seconds = time.perf_counter() - weighted_start
        citation_indices, citation_build, citation_search = search_index(
            citation_vectors,
            query_vectors,
            args.top_k,
        )
        citation_ranked = indices_to_doc_ids(citation_indices, doc_ids)
        citation_metrics = evaluate_run(
            qrels=eval_data.qrels,
            query_ids=query_ids,
            ranked_doc_ids=citation_ranked,
        )
        metrics_by_run[run_name] = citation_metrics
        citation_stats_by_run[run_name] = {
            "index_type": "IndexFlatIP",
            "vectors": int(len(citation_vectors)),
            "weights": format_weights(weights),
            "feature_build_seconds": feature_seconds,
            "weighted_vector_seconds": vector_seconds,
            "index_build_seconds": citation_build,
            "search_seconds": citation_search,
        }
        score = citation_metrics.get(args.optimize_metric, float("-inf"))
        if score > best_score:
            best_score = score
            best_run = run_name
        del citation_vectors
    log_phase(f"Best run by {args.optimize_metric}: {best_run}={best_score:.6f}")

    params = {
        "dataset": "SCIDOCS",
        "model": args.model,
        "weights": parse_weights(args.weights),
        "grid_search": args.grid_search,
        "weight_sets": len(weight_sets),
        "optimize_metric": args.optimize_metric,
        "top_k": args.top_k,
        "limit_docs": args.limit_docs,
        "limit_queries": args.limit_queries,
    }
    stats_by_run = {
        "dataset": {
            "documents": len(eval_data.corpus),
            "queries": len(eval_data.queries),
            "qrels_queries": len(eval_data.qrels),
            **edge_stats,
            "embedding_seconds": embedding_seconds,
            "total_seconds": time.perf_counter() - started,
        },
        "baseline": {
            "index_type": "IndexFlatIP",
            "vectors": int(len(doc_vectors)),
            "index_build_seconds": baseline_build,
            "search_seconds": baseline_search,
        },
        **citation_stats_by_run,
    }
    write_reports(
        out_dir=out_dir,
        metrics_by_run=metrics_by_run,
        stats_by_run=stats_by_run,
        params=params,
        optimize_metric=args.optimize_metric,
        top_runs=args.top_runs,
    )
    log_phase(f"Saved report to {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()

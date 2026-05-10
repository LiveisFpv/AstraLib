#!/usr/bin/env python3
"""Evaluate topical OpenAlex retrieval with local LM Studio judgments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import requests
from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (ROOT_DIR, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.append(str(path))

from eval_openalex_citation_holdout import (  # type: ignore
    DEFAULT_WEIGHTS,
    EMBEDDINGS_NAME,
    build_cache_if_needed,
    embed_documents_or_load,
    embed_queries_or_load,
    format_document,
    hash_edges,
    hash_strings,
    load_doc_embeddings,
    load_doc_ids,
    normalize_openalex_id,
    read_openalex_corpus,
    read_openalex_edges,
    resolve_path,
    search_vectors,
)
from src.al_models.e5.encoder import EncoderConfig, SemanticEncoder
from src.parser.citation_cache import build_weighted_vectors, cache_paths, parse_weights


PROMPT_VERSION = "openalex-topic-relevance-v1"
TOPIC_COLUMNS = ("topics_names", "keywords_names", "concepts_names")
STOP_TOPICS = {
    "article",
    "research",
    "science",
    "study",
    "studies",
    "method",
    "methods",
    "analysis",
    "data",
    "model",
    "models",
}


@dataclass(slots=True)
class DocMeta:
    doc_id: str
    title: str
    abstract: str
    language: str
    topics: list[str]


@dataclass(slots=True)
class TopicQuery:
    query_id: str
    text: str
    source: str
    doc_frequency: int


@dataclass(slots=True)
class Judgment:
    query: str
    doc_id: str
    score: int | None
    reason: str
    error: str | None = None


def log_phase(message: str) -> None:
    print(f"[openalex-topic-eval] {message}", flush=True)


def stable_hash(text: str, *, digest_size: int = 16) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=digest_size).hexdigest()


def stable_fraction(text: str) -> float:
    value = int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")
    return value / float(2**64 - 1)


def split_pipe_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = str(value).split(" | ")
    result: list[str] = []
    for raw in raw_values:
        cleaned = normalize_topic(raw)
        if cleaned:
            result.append(cleaned)
    return result


def normalize_topic(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" .;:,/\\|()[]{}")
    if not text:
        return ""
    normalized = text.lower()
    if len(normalized) < 4:
        return ""
    if normalized in STOP_TOPICS:
        return ""
    if not re.search(r"[a-zа-я]", normalized, re.IGNORECASE):
        return ""
    return normalized


def extract_topics_from_row(row: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for column in TOPIC_COLUMNS:
        for topic in split_pipe_values(row.get(column)):
            if topic in seen:
                continue
            seen.add(topic)
            pairs.append((topic, column))
    return pairs


def select_topic_queries(
    topic_counts: Counter[str],
    topic_sources: dict[str, str],
    *,
    query_limit: int,
    seed: int,
    min_df: int,
    max_df: int | None,
) -> list[TopicQuery]:
    candidates: list[tuple[float, str]] = []
    for topic, count in topic_counts.items():
        if count < min_df:
            continue
        if max_df is not None and count > max_df:
            continue
        candidates.append((stable_fraction(f"{seed}\x1f{topic}"), topic))
    candidates.sort()
    selected = candidates[:query_limit]
    return [
        TopicQuery(
            query_id=f"topic-{stable_hash(topic, digest_size=8)}",
            text=topic,
            source=topic_sources.get(topic, "metadata"),
            doc_frequency=int(topic_counts[topic]),
        )
        for _, topic in selected
    ]


def read_metadata_and_topics(
    parquet_paths: Sequence[Path],
    *,
    doc_ids: Sequence[str],
    query_limit: int,
    seed: int,
    min_topic_df: int,
    max_topic_df: int | None,
) -> tuple[list[DocMeta], list[TopicQuery]]:
    import pyarrow.parquet as pq

    id_to_row = {doc_id: idx for idx, doc_id in enumerate(doc_ids)}
    metas: list[DocMeta | None] = [None] * len(doc_ids)
    topic_counts: Counter[str] = Counter()
    topic_sources: dict[str, str] = {}
    columns = ["id", "title", "abstract_text", "language", *TOPIC_COLUMNS]

    for path in parquet_paths:
        if not path.exists():
            raise RuntimeError(f"Missing OpenAlex parquet file: {path}")
        table = pq.read_table(path, columns=columns)
        for row in table.to_pylist():
            doc_id = normalize_openalex_id(row.get("id"))
            idx = id_to_row.get(doc_id)
            if idx is None:
                continue
            topics = extract_topics_from_row(row)
            topic_values = [topic for topic, _ in topics]
            metas[idx] = DocMeta(
                doc_id=doc_id,
                title=str(row.get("title") or "").strip(),
                abstract=str(row.get("abstract_text") or "").strip(),
                language=str(row.get("language") or "").strip(),
                topics=topic_values,
            )
            for topic, source in topics:
                topic_counts[topic] += 1
                topic_sources.setdefault(topic, source)

    missing = [idx for idx, item in enumerate(metas) if item is None]
    if missing:
        for idx in missing:
            metas[idx] = DocMeta(doc_id=doc_ids[idx], title="", abstract="", language="", topics=[])
    queries = select_topic_queries(
        topic_counts,
        topic_sources,
        query_limit=query_limit,
        seed=seed,
        min_df=min_topic_df,
        max_df=max_topic_df,
    )
    if not queries:
        raise RuntimeError("No topic queries generated; relax --min-topic-df/--max-topic-df")
    return [item for item in metas if item is not None], queries


def query_cache_name(*, model: str, query_count: int, query_hash: str) -> str:
    model_slug = model.replace("/", "__").replace("\\", "__").replace(":", "_")
    return f"topic_query_embeddings.{model_slug}.n{query_count}.{query_hash}.npy"


def load_or_prepare_artifacts(args: argparse.Namespace, parquet_paths: Sequence[Path]) -> tuple[Path, list[str], np.memmap, int]:
    reuse_dir = resolve_path(args.reuse_openalex_holdout_cache, base_dir=ROOT_DIR) if args.reuse_openalex_holdout_cache else None
    if reuse_dir is not None:
        doc_ids = load_doc_ids(reuse_dir / "doc_ids.npy")
        loaded = load_doc_embeddings(reuse_dir / EMBEDDINGS_NAME)
        if doc_ids is not None and loaded is not None:
            embeddings, n_docs, dim = loaded
            if len(doc_ids) == n_docs:
                log_phase(f"Reusing OpenAlex holdout cache: {reuse_dir}")
                return reuse_dir, doc_ids, embeddings, dim
            log_phase("Holdout cache doc_ids length does not match embeddings; falling back to topic cache")

    data_dir = resolve_path(args.data_dir, base_dir=ROOT_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    corpus = read_openalex_corpus(parquet_paths, lang_filter=args.lang_filter, limit_docs=args.limit_docs)
    if not corpus.doc_ids:
        raise RuntimeError("No OpenAlex documents loaded")
    doc_ids_hash = hash_strings(corpus.doc_ids)
    encoder = SemanticEncoder(EncoderConfig(model_name=args.model, batch_size=args.doc_batch_size))
    try:
        embeddings, dim = embed_documents_or_load(
            encoder=encoder,
            corpus=corpus,
            embeddings_path=data_dir / EMBEDDINGS_NAME,
            model_name=args.model,
            doc_ids_hash=doc_ids_hash,
            force=args.force,
        )
    finally:
        encoder.close()

    id_to_row = {doc_id: idx for idx, doc_id in enumerate(corpus.doc_ids)}
    edge_split = read_openalex_edges(
        parquet_paths,
        id_to_row=id_to_row,
        edge_test_frac=args.edge_test_frac,
        split_seed=args.seed,
    )
    if len(edge_split.train_edges) == 0:
        raise RuntimeError("No train citation edges found inside the topic eval corpus")
    build_cache_if_needed(
        embeddings=embeddings,
        train_edges=edge_split.train_edges,
        cache_dir=data_dir / "citation_cache",
        cache_meta={
            "doc_ids_hash": doc_ids_hash,
            "train_edges_hash": hash_edges(edge_split.train_edges),
            "train_edges": int(len(edge_split.train_edges)),
            "edge_test_frac": args.edge_test_frac,
            "split_seed": args.seed,
            "limit_docs": args.limit_docs,
            "lang_filter": args.lang_filter,
            "dimension": int(dim),
        },
        force=args.force,
        edge_batch_size=args.edge_batch_size,
        vec_chunk=args.vec_chunk,
        doc_chunk=args.doc_chunk,
    )
    np.save(data_dir / "doc_ids.npy", np.asarray(corpus.doc_ids, dtype=str), allow_pickle=False)
    return data_dir, corpus.doc_ids, embeddings, dim


def build_candidate_union(
    *ranked_runs: Sequence[Sequence[int]],
    candidate_top_k: int,
    seed: int,
    query_texts: Sequence[str],
) -> list[list[int]]:
    unions: list[list[int]] = []
    if not ranked_runs:
        return [[] for _ in query_texts]
    for query_idx, query_text in enumerate(query_texts):
        seen: set[int] = set()
        candidates: list[int] = []
        for ranked in ranked_runs:
            for idx in list(ranked[query_idx][:candidate_top_k]):
                idx_int = int(idx)
                if idx_int in seen:
                    continue
                seen.add(idx_int)
                candidates.append(idx_int)
        candidates.sort(key=lambda idx: stable_fraction(f"{seed}\x1f{query_text}\x1f{idx}"))
        unions.append(candidates)
    return unions


def search_semantic_with_scores(
    *,
    embeddings: np.memmap,
    query_vectors: np.ndarray,
    top_k: int,
    doc_chunk: int,
) -> tuple[list[list[int]], list[list[float]], dict[str, float]]:
    import faiss

    n_docs, dim = embeddings.shape
    index = faiss.IndexFlatIP(int(dim))
    build_start = time.perf_counter()
    for start in tqdm(range(0, n_docs, doc_chunk), desc="Build semantic index", unit="doc", dynamic_ncols=True):
        end = min(start + doc_chunk, n_docs)
        vectors = np.asarray(embeddings[start:end], dtype=np.float32)
        faiss.normalize_L2(vectors)
        index.add(vectors)
    build_seconds = time.perf_counter() - build_start

    search_start = time.perf_counter()
    scores, indices = index.search(query_vectors.astype(np.float32, copy=False), min(int(n_docs), int(top_k)))
    search_seconds = time.perf_counter() - search_start
    ranked = [[int(idx) for idx in row if int(idx) >= 0] for row in indices]
    ranked_scores = [
        [float(score) for idx, score in zip(index_row, score_row, strict=False) if int(idx) >= 0]
        for index_row, score_row in zip(indices, scores, strict=False)
    ]
    return ranked, ranked_scores, {"index_build_seconds": build_seconds, "search_seconds": search_seconds}


def parse_float_values(raw: str) -> list[float]:
    values = [float(item.strip()) for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("Float value list cannot be empty")
    return values


def run_name_for_alpha(alpha: float) -> str:
    return f"rerank_alpha_{alpha:g}".replace(".", "p").replace("-", "m")


def rerank_by_score_blend(
    *,
    semantic_ranked: Sequence[Sequence[int]],
    semantic_scores: Sequence[Sequence[float]],
    citation_scores: Sequence[Sequence[float]],
    alpha: float,
) -> list[list[int]]:
    reranked: list[list[int]] = []
    for row_indices, row_semantic, row_citation in zip(semantic_ranked, semantic_scores, citation_scores, strict=True):
        items = [
            (int(idx), float(semantic_score) + alpha * float(citation_score), rank)
            for rank, (idx, semantic_score, citation_score) in enumerate(
                zip(row_indices, row_semantic, row_citation, strict=False)
            )
        ]
        items.sort(key=lambda item: (-item[1], item[2]))
        reranked.append([idx for idx, _, _ in items])
    return reranked


def compute_candidate_citation_scores(
    *,
    embeddings: np.memmap,
    cache_dir: Path,
    query_vectors: np.ndarray,
    ranked: Sequence[Sequence[int]],
    weights: dict[str, float],
) -> tuple[list[list[float]], float]:
    n_docs, dim = embeddings.shape
    paths = cache_paths(cache_dir)
    out1 = np.memmap(paths["out1_mean"], dtype=np.float16, mode="r", shape=(n_docs, dim))
    in1 = np.memmap(paths["in1_mean"], dtype=np.float16, mode="r", shape=(n_docs, dim))
    out2 = np.memmap(paths["out2_mean"], dtype=np.float16, mode="r", shape=(n_docs, dim))
    in2 = np.memmap(paths["in2_mean"], dtype=np.float16, mode="r", shape=(n_docs, dim))

    started = time.perf_counter()
    all_scores: list[list[float]] = []
    for query_idx, candidates in enumerate(tqdm(ranked, desc="Score citation rerank feature", unit="query", dynamic_ncols=True)):
        if not candidates:
            all_scores.append([])
            continue
        idx = np.asarray(candidates, dtype=np.int64)
        vectors = build_weighted_vectors(
            np.asarray(embeddings[idx], dtype=np.float32),
            np.asarray(out1[idx], dtype=np.float32),
            np.asarray(in1[idx], dtype=np.float32),
            np.asarray(out2[idx], dtype=np.float32),
            np.asarray(in2[idx], dtype=np.float32),
            weights,
            normalize=True,
        )
        scores = vectors @ query_vectors[query_idx].astype(np.float32, copy=False)
        all_scores.append([float(score) for score in scores.tolist()])
    return all_scores, time.perf_counter() - started


def judgment_key(query: str, doc: DocMeta, *, judge_model: str) -> str:
    payload = "\x1f".join([PROMPT_VERSION, judge_model, query, doc.doc_id, doc.title, doc.abstract])
    return stable_hash(payload)


def load_judgment_cache(path: Path) -> dict[str, Judgment]:
    cache: dict[str, Judgment] = {}
    if not path.exists():
        return cache
    with open(path, "r", encoding="utf-8") as file_obj:
        for line in file_obj:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(payload.get("key") or "")
            if not key:
                continue
            cache[key] = Judgment(
                query=str(payload.get("query") or ""),
                doc_id=str(payload.get("doc_id") or ""),
                score=payload.get("score") if isinstance(payload.get("score"), int) else None,
                reason=str(payload.get("reason") or ""),
                error=payload.get("error"),
            )
    return cache


def append_judgment(path: Path, key: str, judgment: Judgment) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as file_obj:
        file_obj.write(
            json.dumps(
                {
                    "key": key,
                    "query": judgment.query,
                    "doc_id": judgment.doc_id,
                    "score": judgment.score,
                    "reason": judgment.reason,
                    "error": judgment.error,
                    "prompt_version": PROMPT_VERSION,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def parse_judge_json(content: str) -> tuple[int, str]:
    text = content.strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    payload = json.loads(text)
    score = int(payload["score"])
    if score not in {0, 1, 2}:
        raise ValueError(f"Judge score must be 0, 1, or 2; got {score}")
    reason = str(payload.get("reason") or "").strip()
    return score, reason


def judge_prompt(query: str, doc: DocMeta) -> list[dict[str, str]]:
    abstract = doc.abstract[:2400]
    return [
        {
            "role": "system",
            "content": (
                "You judge whether a scientific paper is relevant to a topical search query. "
                "Return strict JSON only. Scores: 2=directly relevant, 1=partially/background/method related, 0=not relevant."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Query topic: {query}\n\n"
                f"Paper title: {doc.title}\n\n"
                f"Paper abstract: {abstract}\n\n"
                'Return exactly: {"score": 0|1|2, "reason": "short reason"}'
            ),
        },
    ]


def call_lmstudio_judge(
    *,
    base_url: str,
    model: str,
    query: str,
    doc: DocMeta,
    timeout: int,
    temperature: float,
) -> Judgment:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": judge_prompt(query, doc),
        "temperature": temperature,
        "max_tokens": 96,
    }
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = requests.post(endpoint, json=payload, timeout=timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            score, reason = parse_judge_json(str(content))
            return Judgment(query=query, doc_id=doc.doc_id, score=score, reason=reason)
        except Exception as exc:  # noqa: BLE001 - preserve judge failures in artifacts
            last_error = exc
    return Judgment(query=query, doc_id=doc.doc_id, score=None, reason="", error=str(last_error))


def ensure_judgments(
    *,
    queries: Sequence[TopicQuery],
    candidate_unions: Sequence[Sequence[int]],
    metas: Sequence[DocMeta],
    judgments_path: Path,
    base_url: str,
    judge_model: str,
    timeout: int,
    temperature: float,
) -> dict[tuple[str, str], int]:
    cache = load_judgment_cache(judgments_path)
    scores: dict[tuple[str, str], int] = {}
    missing: list[tuple[str, TopicQuery, int, str]] = []

    for query, candidates in zip(queries, candidate_unions, strict=True):
        for idx in candidates:
            doc = metas[int(idx)]
            key = judgment_key(query.text, doc, judge_model=judge_model)
            cached = cache.get(key)
            if cached and cached.score is not None:
                scores[(query.query_id, doc.doc_id)] = int(cached.score)
            else:
                missing.append((key, query, int(idx), doc.doc_id))

    if missing:
        log_phase(f"Judging {len(missing)} query-document pairs via LM Studio")
    for key, query, idx, doc_id in tqdm(missing, desc="Judge candidates", unit="pair", dynamic_ncols=True):
        doc = metas[idx]
        judgment = call_lmstudio_judge(
            base_url=base_url,
            model=judge_model,
            query=query.text,
            doc=doc,
            timeout=timeout,
            temperature=temperature,
        )
        append_judgment(judgments_path, key, judgment)
        if judgment.score is not None:
            scores[(query.query_id, doc_id)] = int(judgment.score)
    return scores


def dcg(scores: Sequence[int]) -> float:
    return sum(((2**score - 1) / math.log2(rank + 2)) for rank, score in enumerate(scores))


def select_best_run_by_metric(
    run_names: Sequence[str],
    metrics_by_run: dict[str, dict[str, float]],
    *,
    preferred_metric: str = "nDCG@10",
) -> tuple[str | None, str]:
    available_metrics = {metric for metrics in metrics_by_run.values() for metric in metrics}
    if preferred_metric in available_metrics:
        metric_name = preferred_metric
    elif "nDCG@5" in available_metrics:
        metric_name = "nDCG@5"
    else:
        metric_name = sorted(available_metrics)[0] if available_metrics else preferred_metric
    best_run = max(run_names, key=lambda name: metrics_by_run[name].get(metric_name, float("-inf")), default=None)
    return best_run, metric_name


def evaluate_ranked(
    *,
    queries: Sequence[TopicQuery],
    ranked: Sequence[Sequence[int]],
    metas: Sequence[DocMeta],
    scores: dict[tuple[str, str], int],
    eval_top_k: int,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    totals: dict[str, float] = defaultdict(float)
    per_query: list[dict[str, Any]] = []
    evaluated = 0
    for query, row in zip(queries, ranked, strict=True):
        top = list(row[:eval_top_k])
        gains: list[int] = []
        for idx in top:
            doc_id = metas[int(idx)].doc_id
            gains.append(int(scores.get((query.query_id, doc_id), 0)))
        if not gains:
            continue
        evaluated += 1
        judged_scores = [
            int(value)
            for (query_id, _), value in scores.items()
            if query_id == query.query_id
        ]
        ideal = sorted(judged_scores, reverse=True)
        for k in (5, 10):
            if eval_top_k < k:
                continue
            denom = dcg(ideal[:k])
            totals[f"nDCG@{k}"] += (dcg(gains[:k]) / denom) if denom > 0 else 0.0
            totals[f"Precision@{k}"] += sum(1 for score in gains[:k] if score >= 1) / float(k)
            totals[f"StrongPrecision@{k}"] += sum(1 for score in gains[:k] if score == 2) / float(k)
        rr = 0.0
        for rank, score in enumerate(gains[: min(10, eval_top_k)], start=1):
            if score >= 1:
                rr = 1.0 / float(rank)
                break
        totals["MRR@10"] += rr
        per_query.append(
            {
                "query_id": query.query_id,
                "query": query.text,
                "dcg10": dcg(gains[: min(10, eval_top_k)]),
                "relevant_at_10": sum(1 for score in gains[: min(10, eval_top_k)] if score >= 1),
                "strong_at_10": sum(1 for score in gains[: min(10, eval_top_k)] if score == 2),
            }
        )
    if evaluated == 0:
        raise RuntimeError("No judged queries were evaluated")
    return {key: value / float(evaluated) for key, value in sorted(totals.items())}, per_query


def write_queries(path: Path, queries: Sequence[TopicQuery]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_obj:
        for query in queries:
            file_obj.write(json.dumps(asdict(query), ensure_ascii=False) + "\n")


def write_reports(
    *,
    out_dir: Path,
    metrics_by_run: dict[str, dict[str, float]],
    stats: dict[str, Any],
    params: dict[str, Any],
    examples: list[dict[str, Any]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    metric_names = sorted({name for metrics in metrics_by_run.values() for name in metrics})
    with open(out_dir / "metrics.csv", "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=["run", *metric_names])
        writer.writeheader()
        for run, metrics in metrics_by_run.items():
            writer.writerow({"run": run, **{name: metrics.get(name, 0.0) for name in metric_names}})
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as file_obj:
        json.dump({"params": params, "metrics": metrics_by_run, "stats": stats, "examples": examples}, file_obj, ensure_ascii=False, indent=2)

    baseline = metrics_by_run["baseline"]
    citation = metrics_by_run.get("citation_aware", {})
    rerank_runs = [name for name in metrics_by_run if name.startswith("rerank_alpha_")]
    best_rerank, best_metric_name = select_best_run_by_metric(rerank_runs, metrics_by_run)
    lines = [
        "# OpenAlex Topical Relevance Evaluation",
        "",
        "## Metrics",
        "",
    ]
    if rerank_runs:
        lines.extend(
            [
                "| Metric | Baseline | Citation-aware | Best rerank | Rerank delta |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for name in metric_names:
            base = baseline.get(name, 0.0)
            cited = citation.get(name, 0.0)
            rerank_value = metrics_by_run[best_rerank].get(name, 0.0) if best_rerank else 0.0
            rerank_delta = rerank_value - base
            lines.append(f"| {name} | {base:.6f} | {cited:.6f} | {rerank_value:.6f} | {rerank_delta:+.6f} |")
        lines.extend(
            [
                "",
                f"## Rerank Runs by {best_metric_name}",
                "",
                f"| Rank | Run | {best_metric_name} | Delta vs Baseline |",
                "| ---: | --- | ---: | ---: |",
            ]
        )
        for rank, run in enumerate(
            sorted(rerank_runs, key=lambda item: metrics_by_run[item].get(best_metric_name, float("-inf")), reverse=True),
            start=1,
        ):
            score = metrics_by_run[run].get(best_metric_name, 0.0)
            lines.append(f"| {rank} | `{run}` | {score:.6f} | {score - baseline.get(best_metric_name, 0.0):+.6f} |")
    else:
        lines.extend(
            [
                "| Metric | Baseline | Citation-aware | Delta | Relative |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for name in metric_names:
            base = baseline.get(name, 0.0)
            cited = citation.get(name, 0.0)
            delta = cited - base
            relative = (delta / base * 100.0) if base else 0.0
            lines.append(f"| {name} | {base:.6f} | {cited:.6f} | {delta:+.6f} | {relative:+.2f}% |")
    lines.extend(["", "## Examples", ""])
    for item in examples[:10]:
        lines.append(
            f"- `{item['query']}`: baseline_dcg10={item['baseline_dcg10']:.3f}, "
            f"comparison_dcg10={item['comparison_dcg10']:.3f}, delta={item['delta']:+.3f}"
        )
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
            json.dumps(stats, ensure_ascii=False, indent=2),
            "```",
        ]
    )
    with open(out_dir / "report.md", "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(lines) + "\n")


def build_examples(
    baseline_per_query: Sequence[dict[str, Any]],
    compared_per_query: Sequence[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    by_query = {item["query_id"]: item for item in baseline_per_query}
    examples: list[dict[str, Any]] = []
    for compared in compared_per_query:
        base = by_query.get(compared["query_id"])
        if not base:
            continue
        delta = float(compared["dcg10"]) - float(base["dcg10"])
        examples.append(
            {
                "query_id": compared["query_id"],
                "query": compared["query"],
                "baseline_dcg10": float(base["dcg10"]),
                "comparison_dcg10": float(compared["dcg10"]),
                "delta": delta,
            }
        )
    examples.sort(key=lambda item: abs(float(item["delta"])), reverse=True)
    return examples[:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", nargs="+", default=["data/processed/openalex_en.merged.parquet", "data/processed/openalex_ru.merged.parquet"])
    parser.add_argument("--data-dir", default="data/eval/openalex_topic_relevance")
    parser.add_argument("--out-dir", default="reports/openalex_topic_relevance")
    parser.add_argument("--reuse-openalex-holdout-cache", default="data/eval/openalex_holdout")
    parser.add_argument("--model", default="intfloat/multilingual-e5-large")
    parser.add_argument("--weights", default=DEFAULT_WEIGHTS)
    parser.add_argument("--lmstudio-base-url", default="http://localhost:1234/v1")
    parser.add_argument("--judge-model", default="local-model")
    parser.add_argument("--query-limit", type=int, default=1000)
    parser.add_argument("--retrieval-top-k", type=int, default=100)
    parser.add_argument("--candidate-top-k", type=int, default=20)
    parser.add_argument("--eval-top-k", type=int, default=10)
    parser.add_argument("--rerank-mode", choices=["none", "citation-score"], default="none")
    parser.add_argument("--alpha-vals", default="0.0,0.02,0.05,0.1,0.2,0.5,1.0")
    parser.add_argument("--rerank-weights", default="self=0.0,out1=0.0,in1=0.05,out2=0.03,in2=0.025")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-topic-df", type=int, default=20)
    parser.add_argument("--max-topic-df", type=int)
    parser.add_argument("--limit-docs", type=int)
    parser.add_argument("--lang-filter", choices=["any", "en", "ru"], default="any")
    parser.add_argument("--doc-batch-size", type=int, default=64)
    parser.add_argument("--query-batch-size", type=int, default=64)
    parser.add_argument("--doc-chunk", type=int, default=4096)
    parser.add_argument("--edge-test-frac", type=float, default=0.2)
    parser.add_argument("--edge-batch-size", type=int, default=200000)
    parser.add_argument("--vec-chunk", type=int, default=10000)
    parser.add_argument("--judge-timeout", type=int, default=120)
    parser.add_argument("--judge-temperature", type=float, default=0.0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.candidate_top_k < args.eval_top_k:
        raise ValueError("--candidate-top-k must be >= --eval-top-k")
    if args.retrieval_top_k < args.candidate_top_k:
        raise ValueError("--retrieval-top-k must be >= --candidate-top-k")
    return args


def main() -> None:
    started = time.perf_counter()
    args = parse_args()
    out_dir = resolve_path(args.out_dir, base_dir=ROOT_DIR)
    data_dir = resolve_path(args.data_dir, base_dir=ROOT_DIR)
    parquet_paths = [resolve_path(path, base_dir=ROOT_DIR) for path in args.parquet]
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    cache_dir, doc_ids, embeddings, dim = load_or_prepare_artifacts(args, parquet_paths)
    log_phase("Reading metadata and generating topic queries")
    metas, queries = read_metadata_and_topics(
        parquet_paths,
        doc_ids=doc_ids,
        query_limit=args.query_limit,
        seed=args.seed,
        min_topic_df=args.min_topic_df,
        max_topic_df=args.max_topic_df,
    )
    write_queries(out_dir / "queries.jsonl", queries)
    query_texts = [query.text for query in queries]
    query_hash = hash_strings(query_texts)

    log_phase(f"Loading query encoder: {args.model}")
    encoder = SemanticEncoder(EncoderConfig(model_name=args.model, batch_size=args.query_batch_size))
    try:
        query_vectors = embed_queries_or_load(
            encoder=encoder,
            query_texts=query_texts,
            cache_path=data_dir / query_cache_name(model=args.model, query_count=len(queries), query_hash=query_hash),
            force=args.force,
        )
    finally:
        encoder.close()

    log_phase("Searching baseline")
    baseline_ranked, baseline_scores, baseline_search_stats = search_semantic_with_scores(
        embeddings=embeddings,
        query_vectors=query_vectors,
        top_k=args.retrieval_top_k,
        doc_chunk=args.doc_chunk,
    )
    log_phase("Searching citation-aware")
    query_doc_rows = [-1] * len(queries)
    citation_ranked, citation_search_stats = search_vectors(
        embeddings=embeddings,
        query_vectors=query_vectors,
        query_doc_rows=query_doc_rows,
        top_k=args.candidate_top_k,
        doc_chunk=args.doc_chunk,
        weights=parse_weights(args.weights),
        cache_dir=cache_dir / "citation_cache",
    )
    rerank_ranked_by_run: dict[str, list[list[int]]] = {}
    rerank_stats: dict[str, Any] = {}
    if args.rerank_mode == "citation-score":
        alphas = parse_float_values(args.alpha_vals)
        rerank_weights = parse_weights(args.rerank_weights)
        citation_feature_scores, citation_feature_seconds = compute_candidate_citation_scores(
            embeddings=embeddings,
            cache_dir=cache_dir / "citation_cache",
            query_vectors=query_vectors,
            ranked=baseline_ranked,
            weights=rerank_weights,
        )
        rerank_stats = {
            "mode": args.rerank_mode,
            "alpha_vals": alphas,
            "weights": rerank_weights,
            "citation_feature_seconds": citation_feature_seconds,
        }
        for alpha in alphas:
            rerank_ranked_by_run[run_name_for_alpha(alpha)] = rerank_by_score_blend(
                semantic_ranked=baseline_ranked,
                semantic_scores=baseline_scores,
                citation_scores=citation_feature_scores,
                alpha=alpha,
            )

    candidate_unions = build_candidate_union(
        baseline_ranked,
        citation_ranked,
        *rerank_ranked_by_run.values(),
        candidate_top_k=args.candidate_top_k,
        seed=args.seed,
        query_texts=query_texts,
    )
    judgments_path = out_dir / "judgments.jsonl"
    scores = ensure_judgments(
        queries=queries,
        candidate_unions=candidate_unions,
        metas=metas,
        judgments_path=judgments_path,
        base_url=args.lmstudio_base_url,
        judge_model=args.judge_model,
        timeout=args.judge_timeout,
        temperature=args.judge_temperature,
    )
    if not scores:
        raise RuntimeError("No successful LLM judgments were collected")

    baseline_metrics, baseline_per_query = evaluate_ranked(
        queries=queries,
        ranked=baseline_ranked,
        metas=metas,
        scores=scores,
        eval_top_k=args.eval_top_k,
    )
    citation_metrics, citation_per_query = evaluate_ranked(
        queries=queries,
        ranked=citation_ranked,
        metas=metas,
        scores=scores,
        eval_top_k=args.eval_top_k,
    )
    metrics_by_run = {"baseline": baseline_metrics, "citation_aware": citation_metrics}
    per_query_by_run = {"baseline": baseline_per_query, "citation_aware": citation_per_query}
    for run_name, ranked in rerank_ranked_by_run.items():
        run_metrics, run_per_query = evaluate_ranked(
            queries=queries,
            ranked=ranked,
            metas=metas,
            scores=scores,
            eval_top_k=args.eval_top_k,
        )
        metrics_by_run[run_name] = run_metrics
        per_query_by_run[run_name] = run_per_query
    rerank_runs = [name for name in metrics_by_run if name.startswith("rerank_alpha_")]
    best_rerank, best_metric_name = select_best_run_by_metric(rerank_runs, metrics_by_run)
    best_comparison = best_rerank or "citation_aware"
    examples = build_examples(baseline_per_query, per_query_by_run[best_comparison], limit=50)
    stats = {
        "documents": len(doc_ids),
        "queries": len(queries),
        "judged_pairs": len(scores),
        "retrieval_top_k": args.retrieval_top_k,
        "candidate_top_k": args.candidate_top_k,
        "eval_top_k": args.eval_top_k,
        "embedding_dimension": int(dim),
        "cache_dir": str(cache_dir),
        "baseline_search": baseline_search_stats,
        "citation_search": citation_search_stats,
        "rerank": rerank_stats,
        "best_rerank": best_rerank,
        "best_rerank_metric": best_metric_name if best_rerank else None,
        "total_seconds": time.perf_counter() - started,
    }
    params = {
        "dataset": "OpenAlex topical relevance",
        "parquet": [str(path) for path in parquet_paths],
        "model": args.model,
        "weights": parse_weights(args.weights),
        "judge": {
            "base_url": args.lmstudio_base_url,
            "model": args.judge_model,
            "prompt_version": PROMPT_VERSION,
            "temperature": args.judge_temperature,
        },
        "query_limit": args.query_limit,
        "retrieval_top_k": args.retrieval_top_k,
        "candidate_top_k": args.candidate_top_k,
        "eval_top_k": args.eval_top_k,
        "rerank_mode": args.rerank_mode,
        "alpha_vals": parse_float_values(args.alpha_vals),
        "rerank_weights": parse_weights(args.rerank_weights),
        "min_topic_df": args.min_topic_df,
        "max_topic_df": args.max_topic_df,
        "seed": args.seed,
    }
    write_reports(out_dir=out_dir, metrics_by_run=metrics_by_run, stats=stats, params=params, examples=examples)
    log_phase(f"Wrote reports to {out_dir}")
    for run, metrics in metrics_by_run.items():
        log_phase(f"{run}: " + ", ".join(f"{key}={value:.4f}" for key, value in sorted(metrics.items())))


if __name__ == "__main__":
    main()

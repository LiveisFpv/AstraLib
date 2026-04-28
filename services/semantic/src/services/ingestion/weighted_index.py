"""Mutable weighted citation-aware FAISS runtime."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from src.al_models.e5.encoder import SemanticEncoder
from src.lib.logger import Logger
from src.parser.citation_cache import (
    CITATION_CACHE_VERSION,
    build_weighted_vectors,
    cache_paths,
)
from src.services.ingestion.citation_math import compute_cache_arrays, expand_affected_graph
from src.services.ingestion.models import StoredPaper
from src.services.search.faiss_index import FaissIndex
from src.storage.citation_repository import CitationRepository


@dataclass(slots=True)
class WeightedRuntimeArtifacts:
    embeddings_path: Path
    embeddings_shape_path: Path
    cache_dir: Path
    dirty_marker_path: Path


def maybe_create_weighted_index_manager(
    *,
    index: FaissIndex,
    encoder: SemanticEncoder,
    citation_repository: CitationRepository,
    logger: Logger,
    required: bool = False,
) -> "CitationIndexManager | None":
    meta = index.get_meta()
    weights = meta.get("weights")
    if not isinstance(weights, dict):
        if required:
            meta_path = getattr(index, "meta_path", None)
            index_path = getattr(index, "index_path", None)
            doc_ids_path = getattr(index, "doc_ids_path", None)
            raise RuntimeError(
                "Weighted runtime is required but FAISS meta has no weights "
                f"(index_path={index_path}, index_exists={Path(index_path).exists() if index_path else None}, "
                f"doc_ids_path={doc_ids_path}, doc_ids_exists={Path(doc_ids_path).exists() if doc_ids_path else None}, "
                f"meta_path={meta_path}, meta_exists={Path(meta_path).exists() if meta_path else None}, "
                f"meta_keys={sorted(meta.keys())})"
            )
        return None
    return CitationIndexManager(
        index=index,
        encoder=encoder,
        citation_repository=citation_repository,
        logger=logger,
    )


class CitationIndexManager:
    def __init__(
        self,
        *,
        index: FaissIndex,
        encoder: SemanticEncoder,
        citation_repository: CitationRepository,
        logger: Logger,
    ) -> None:
        self.index = index
        self.encoder = encoder
        self.citation_repository = citation_repository
        self.logger = logger
        self._lock = threading.RLock()

        self.meta = self._validate_meta(index.get_meta())
        self.weights = dict(self.meta["weights"])
        self.normalize = bool(self.meta.get("normalized", True))
        self.dim = int(self.meta["dimension"])
        self.artifacts = self._resolve_artifacts()

        self.doc_ids = np.asarray(index.doc_ids, dtype=np.int64)
        self.row_by_doc_id = {int(doc_id): idx for idx, doc_id in enumerate(self.doc_ids.tolist())}

        n_rows, loaded_dim = self._load_embeddings_shape()
        if loaded_dim != self.dim:
            raise RuntimeError("Weighted runtime dimension does not match base embeddings")
        if n_rows != len(self.doc_ids):
            raise RuntimeError("Weighted runtime row storage does not match doc_ids length")

        self.base_embeddings = np.memmap(
            self.artifacts.embeddings_path,
            dtype=np.float16,
            mode="r+",
            shape=(n_rows, loaded_dim),
        )
        self.cache_memmaps = self._open_cache_memmaps(n_rows, self.dim)
        self.count_arrays = self._load_count_arrays(n_rows)

    def ensure_writable(self) -> None:
        if self.is_dirty():
            raise RuntimeError(
                f"Weighted index is dirty; repair required at {self.artifacts.dirty_marker_path}"
            )

    def is_dirty(self) -> bool:
        return self.artifacts.dirty_marker_path.exists()

    def apply_delta(self, papers: list[StoredPaper], seed_paper_ids: Iterable[int]) -> int:
        seed_ids = {int(paper_id) for paper_id in seed_paper_ids if paper_id is not None}
        candidates = [paper for paper in papers if paper.text]
        if not candidates and not seed_ids:
            return 0

        self.ensure_writable()
        embeddings = (
            self.encoder.embed_passages([paper.text for paper in candidates])
            if candidates
            else np.zeros((0, self.dim), dtype=np.float32)
        )

        try:
            with self._lock:
                self.ensure_writable()
                self._mark_dirty_locked("weighted index update in progress")
                self._upsert_base_embeddings([paper.paper_id for paper in candidates], embeddings)

                graph = expand_affected_graph(
                    seed_ids | {paper.paper_id for paper in candidates},
                    fetch_successors=self._fetch_successors,
                    fetch_predecessors=self._fetch_predecessors,
                )
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
                    dim=self.dim,
                    row_by_doc_id=self.row_by_doc_id,
                    base_embeddings=self.base_embeddings,
                    successors=graph.successors,
                    predecessors=graph.predecessors,
                    successor_successors=graph.successor_successors,
                    predecessor_predecessors=graph.predecessor_predecessors,
                )
                if not ordered_ids:
                    self._clear_dirty_locked()
                    return 0

                self._write_cache_rows(
                    ordered_ids=ordered_ids,
                    out1_rows=out1_rows,
                    in1_rows=in1_rows,
                    out2_rows=out2_rows,
                    in2_rows=in2_rows,
                    deg_out=deg_out,
                    deg_in=deg_in,
                    cnt_out2=cnt_out2,
                    cnt_in2=cnt_in2,
                )

                row_indices = [self.row_by_doc_id[int(doc_id)] for doc_id in ordered_ids]
                base_vectors = np.asarray(self.base_embeddings[row_indices], dtype=np.float32)
                weighted_vectors = build_weighted_vectors(
                    base_vectors,
                    np.asarray(out1_rows, dtype=np.float32),
                    np.asarray(in1_rows, dtype=np.float32),
                    np.asarray(out2_rows, dtype=np.float32),
                    np.asarray(in2_rows, dtype=np.float32),
                    self.weights,
                    normalize=self.normalize,
                )

                self.meta["vectors"] = int(len(self.doc_ids))
                self.index.sync_doc_ids(self.doc_ids)
                self.index.set_meta(self.meta)
                self.index.replace_documents(ordered_ids, weighted_vectors)
                self._clear_dirty_locked()
                return len(ordered_ids)
        except Exception as exc:
            with self._lock:
                self._mark_dirty_locked(str(exc))
            raise

    def mark_dirty(self, reason: str) -> None:
        with self._lock:
            self._mark_dirty_locked(reason)

    def clear_dirty(self) -> None:
        with self._lock:
            self._clear_dirty_locked()

    def _validate_meta(self, meta: dict[str, Any]) -> dict[str, Any]:
        if meta.get("id_mode") != "paper_id":
            raise RuntimeError("Weighted runtime requires FAISS meta id_mode=paper_id")
        if int(meta.get("citation_cache_version") or 0) != CITATION_CACHE_VERSION:
            raise RuntimeError("Weighted runtime citation cache version is missing or unsupported")

        weights = meta.get("weights")
        if not isinstance(weights, dict):
            raise RuntimeError("Weighted runtime weights are missing in FAISS meta")

        artifacts = meta.get("artifacts")
        if not isinstance(artifacts, dict):
            raise RuntimeError("Weighted runtime artifacts block is missing in FAISS meta")
        if not artifacts.get("embeddings"):
            raise RuntimeError("Weighted runtime embeddings artifact is missing in FAISS meta")
        if not artifacts.get("cache_dir"):
            raise RuntimeError("Weighted runtime cache_dir artifact is missing in FAISS meta")
        return meta

    def _resolve_artifacts(self) -> WeightedRuntimeArtifacts:
        base_dir = self.index.index_path.parent
        artifacts_meta = self.meta["artifacts"]
        embeddings_path = base_dir / str(artifacts_meta["embeddings"])
        shape_path = _resolve_shape_path(embeddings_path)
        cache_dir = base_dir / str(artifacts_meta["cache_dir"])
        dirty_name = str(artifacts_meta.get("dirty_marker") or f"{self.index.index_path.name}.dirty")
        dirty_marker_path = base_dir / dirty_name
        return WeightedRuntimeArtifacts(
            embeddings_path=embeddings_path,
            embeddings_shape_path=shape_path,
            cache_dir=cache_dir,
            dirty_marker_path=dirty_marker_path,
        )

    def _load_embeddings_shape(self) -> tuple[int, int]:
        with open(self.artifacts.embeddings_shape_path, "r", encoding="utf-8") as meta_file:
            n_vectors, dim = json.load(meta_file)
        return int(n_vectors), int(dim)

    def _open_cache_memmaps(self, n_rows: int, dim: int) -> dict[str, np.memmap]:
        paths = cache_paths(self.artifacts.cache_dir)
        result: dict[str, np.memmap] = {}
        for key in ("out1_mean", "in1_mean", "out2_mean", "in2_mean"):
            path = paths[key]
            if not path.exists():
                raise RuntimeError(f"Weighted runtime cache file is missing: {path}")
            result[key] = np.memmap(path, dtype=np.float16, mode="r+", shape=(n_rows, dim))
        return result

    def _load_count_arrays(self, n_rows: int) -> dict[str, np.ndarray]:
        paths = cache_paths(self.artifacts.cache_dir)
        result: dict[str, np.ndarray] = {}
        for key in ("deg_out", "deg_in", "cnt_out2", "cnt_in2"):
            path = paths[key]
            if not path.exists():
                raise RuntimeError(f"Weighted runtime counter file is missing: {path}")
            values = np.load(path, allow_pickle=False)
            if len(values) != n_rows:
                raise RuntimeError(f"Weighted runtime counter length does not match row storage: {path}")
            result[key] = np.asarray(values, dtype=np.int32)
        return result

    def _upsert_base_embeddings(self, paper_ids: list[int], embeddings: np.ndarray) -> None:
        if len(paper_ids) != len(embeddings):
            raise ValueError("paper_ids and embeddings must have the same length")
        if not paper_ids:
            return

        new_doc_ids = [int(doc_id) for doc_id in paper_ids if int(doc_id) not in self.row_by_doc_id]
        if new_doc_ids:
            self._expand_storage(new_doc_ids)

        row_indices = [self.row_by_doc_id[int(doc_id)] for doc_id in paper_ids]
        self.base_embeddings[row_indices] = embeddings.astype(np.float16)
        self.base_embeddings.flush()

    def _expand_storage(self, new_doc_ids: list[int]) -> None:
        new_doc_ids = [int(doc_id) for doc_id in new_doc_ids]
        if not new_doc_ids:
            return

        old_rows = len(self.doc_ids)
        new_rows = old_rows + len(new_doc_ids)
        file_size = new_rows * self.dim * np.dtype(np.float16).itemsize

        self.base_embeddings.flush()
        del self.base_embeddings
        for memmap in self.cache_memmaps.values():
            memmap.flush()
        self.cache_memmaps.clear()

        self.artifacts.cache_dir.mkdir(parents=True, exist_ok=True)
        os.truncate(self.artifacts.embeddings_path, file_size)
        for key, path in cache_paths(self.artifacts.cache_dir).items():
            if not key.endswith("_mean"):
                continue
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "wb"):
                    pass
                os.truncate(path, file_size)
            else:
                os.truncate(path, file_size)

        self.doc_ids = np.concatenate(
            [self.doc_ids.astype(np.int64, copy=False), np.asarray(new_doc_ids, dtype=np.int64)]
        )
        self.row_by_doc_id = {int(doc_id): idx for idx, doc_id in enumerate(self.doc_ids.tolist())}
        for key in ("deg_out", "deg_in", "cnt_out2", "cnt_in2"):
            self.count_arrays[key] = np.concatenate(
                [
                    self.count_arrays[key].astype(np.int32, copy=False),
                    np.zeros((len(new_doc_ids),), dtype=np.int32),
                ]
            )
        self._persist_row_storage()
        self._persist_count_arrays()

        self.base_embeddings = np.memmap(
            self.artifacts.embeddings_path,
            dtype=np.float16,
            mode="r+",
            shape=(new_rows, self.dim),
        )
        self.cache_memmaps = self._open_cache_memmaps(new_rows, self.dim)
        for key in ("out1_mean", "in1_mean", "out2_mean", "in2_mean"):
            self.cache_memmaps[key][old_rows:new_rows] = 0
            self.cache_memmaps[key].flush()

    def _persist_row_storage(self) -> None:
        self.index.doc_ids_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts.embeddings_shape_path.parent.mkdir(parents=True, exist_ok=True)
        doc_ids_tmp = self.index.doc_ids_path.with_name(f"{self.index.doc_ids_path.name}.tmp")
        with open(doc_ids_tmp, "wb") as file_obj:
            np.save(file_obj, self.doc_ids.astype(np.int64, copy=False))
        os.replace(doc_ids_tmp, self.index.doc_ids_path)

        shape_tmp = self.artifacts.embeddings_shape_path.with_name(
            f"{self.artifacts.embeddings_shape_path.name}.tmp"
        )
        with open(shape_tmp, "w", encoding="utf-8") as meta_file:
            json.dump([int(len(self.doc_ids)), int(self.dim)], meta_file)
        os.replace(shape_tmp, self.artifacts.embeddings_shape_path)

    def _persist_count_arrays(self) -> None:
        paths = cache_paths(self.artifacts.cache_dir)
        for key in ("deg_out", "deg_in", "cnt_out2", "cnt_in2"):
            path = paths[key]
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_name(f"{path.name}.tmp")
            with open(tmp_path, "wb") as file_obj:
                np.save(file_obj, self.count_arrays[key].astype(np.int32, copy=False))
            os.replace(tmp_path, path)

    def _write_cache_rows(
        self,
        *,
        ordered_ids: list[int],
        out1_rows: np.ndarray,
        in1_rows: np.ndarray,
        out2_rows: np.ndarray,
        in2_rows: np.ndarray,
        deg_out: np.ndarray,
        deg_in: np.ndarray,
        cnt_out2: np.ndarray,
        cnt_in2: np.ndarray,
    ) -> None:
        row_indices = [self.row_by_doc_id[int(doc_id)] for doc_id in ordered_ids]
        self.cache_memmaps["out1_mean"][row_indices] = out1_rows
        self.cache_memmaps["in1_mean"][row_indices] = in1_rows
        self.cache_memmaps["out2_mean"][row_indices] = out2_rows
        self.cache_memmaps["in2_mean"][row_indices] = in2_rows
        for memmap in self.cache_memmaps.values():
            memmap.flush()

        self.count_arrays["deg_out"][row_indices] = np.asarray(deg_out, dtype=np.int32)
        self.count_arrays["deg_in"][row_indices] = np.asarray(deg_in, dtype=np.int32)
        self.count_arrays["cnt_out2"][row_indices] = np.asarray(cnt_out2, dtype=np.int32)
        self.count_arrays["cnt_in2"][row_indices] = np.asarray(cnt_in2, dtype=np.int32)
        self._persist_count_arrays()

    def _fetch_successors(self, paper_ids: set[int]) -> dict[int, list[int]]:
        mapping = self.citation_repository.fetch_successors_map(paper_ids)
        return {
            int(src): [int(dst) for dst in values if int(dst) in self.row_by_doc_id]
            for src, values in mapping.items()
            if int(src) in self.row_by_doc_id
        }

    def _fetch_predecessors(self, paper_ids: set[int]) -> dict[int, list[int]]:
        mapping = self.citation_repository.fetch_predecessors_map(paper_ids)
        return {
            int(dst): [int(src) for src in values if int(src) in self.row_by_doc_id]
            for dst, values in mapping.items()
            if int(dst) in self.row_by_doc_id
        }

    def _mark_dirty_locked(self, reason: str) -> None:
        self.artifacts.dirty_marker_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        tmp_path = self.artifacts.dirty_marker_path.with_name(
            f"{self.artifacts.dirty_marker_path.name}.tmp"
        )
        with open(tmp_path, "w", encoding="utf-8") as dirty_file:
            json.dump(payload, dirty_file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.artifacts.dirty_marker_path)

    def _clear_dirty_locked(self) -> None:
        if self.artifacts.dirty_marker_path.exists():
            self.artifacts.dirty_marker_path.unlink()


def _resolve_shape_path(embeddings_path: Path) -> Path:
    legacy = embeddings_path.with_name(f"{embeddings_path.name}.shape.json")
    if legacy.exists():
        return legacy
    return embeddings_path.with_suffix(".shape.json")


__all__ = ["CitationIndexManager", "WeightedRuntimeArtifacts", "maybe_create_weighted_index_manager"]

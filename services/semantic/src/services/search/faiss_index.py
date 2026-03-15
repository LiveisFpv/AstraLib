"""Wrapper around FAISS index and document id mapping."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, List, Tuple

import faiss
import numpy as np


class FaissIndex:
    def __init__(
        self,
        *,
        index_path: str | Path,
        doc_ids_path: str | Path,
        dimension: int | None = None,
    ) -> None:
        self.index_path = Path(index_path)
        self.doc_ids_path = Path(doc_ids_path)
        self.meta_path = self.index_path.with_suffix(self.index_path.suffix + ".meta.json")
        self._lock = threading.RLock()
        self.meta: dict[str, Any] = self._load_meta()
        self.id_mode = str(self.meta.get("id_mode") or "position")

        if self.index_path.exists() and self.doc_ids_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            self.doc_ids = np.load(self.doc_ids_path, allow_pickle=True)
        else:
            if dimension is None:
                raise RuntimeError("FAISS index files are missing and dimension is not provided")
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            self.doc_ids_path.parent.mkdir(parents=True, exist_ok=True)
            self.index = faiss.IndexFlatIP(int(dimension))
            self.doc_ids = np.empty((0,), dtype=np.int64)
            self._persist_locked()

        self._doc_id_set = {self._normalize_doc_id(doc_id) for doc_id in self.doc_ids.tolist()}

        if self.id_mode == "position" and self.index.ntotal != len(self.doc_ids):
            raise RuntimeError("FAISS index vector count does not match doc_ids length")

    def search(self, vector: np.ndarray, top_k: int) -> Tuple[List[Any], List[float]]:
        if vector.ndim == 1:
            vector = vector.reshape(1, -1)
        with self._lock:
            scores, indices = self.index.search(vector.astype("float32"), top_k)
            matched_ids: List[Any] = []
            matched_scores: List[float] = []
            for idx, score in zip(indices[0], scores[0]):
                if idx < 0:
                    continue
                if self.id_mode == "paper_id":
                    matched_ids.append(int(idx))
                else:
                    matched_ids.append(self._normalize_doc_id(self.doc_ids[idx]))
                matched_scores.append(float(score))
            return matched_ids, matched_scores

    def contains_doc_id(self, doc_id: int) -> bool:
        with self._lock:
            return self._normalize_doc_id(doc_id) in self._doc_id_set

    def add_documents(self, doc_ids: List[int], vectors: np.ndarray) -> int:
        if not doc_ids:
            return 0
        if len(doc_ids) != len(vectors):
            raise ValueError("doc_ids and vectors must have the same length")

        with self._lock:
            new_doc_ids: list[int] = []
            new_vectors: list[np.ndarray] = []
            for position, raw_doc_id in enumerate(doc_ids):
                doc_id = int(raw_doc_id)
                if doc_id in self._doc_id_set:
                    continue
                new_doc_ids.append(doc_id)
                new_vectors.append(vectors[position])

            if not new_doc_ids:
                return 0
            if not self.index.is_trained:
                raise RuntimeError("FAISS index is not trained and cannot accept new vectors")

            batch = np.asarray(new_vectors, dtype="float32")
            if self.id_mode == "paper_id":
                self._add_with_ids_locked(batch, np.asarray(new_doc_ids, dtype=np.int64))
            else:
                self.index.add(batch)
                self.doc_ids = np.concatenate(
                    [self.doc_ids.astype(np.int64, copy=False), np.asarray(new_doc_ids, dtype=np.int64)]
                )
            self._doc_id_set.update(new_doc_ids)
            self._persist_locked()
            return len(new_doc_ids)

    def replace_documents(self, doc_ids: List[int], vectors: np.ndarray) -> int:
        if self.id_mode != "paper_id":
            raise RuntimeError("replace_documents is only supported for id_mode=paper_id")
        if len(doc_ids) != len(vectors):
            raise ValueError("doc_ids and vectors must have the same length")

        ordered_doc_ids: list[int] = []
        ordered_vectors: list[np.ndarray] = []
        seen: set[int] = set()
        for idx, raw_doc_id in enumerate(doc_ids):
            doc_id = int(raw_doc_id)
            if doc_id in seen:
                continue
            seen.add(doc_id)
            ordered_doc_ids.append(doc_id)
            ordered_vectors.append(np.asarray(vectors[idx], dtype=np.float32))

        if not ordered_doc_ids:
            return 0

        with self._lock:
            self._remove_ids_locked(ordered_doc_ids)
            self._add_with_ids_locked(
                np.asarray(ordered_vectors, dtype=np.float32),
                np.asarray(ordered_doc_ids, dtype=np.int64),
            )
            self._doc_id_set.update(ordered_doc_ids)
            self._persist_locked()
            return len(ordered_doc_ids)

    def sync_doc_ids(self, doc_ids: np.ndarray) -> None:
        with self._lock:
            self.doc_ids = np.asarray(doc_ids, dtype=np.int64)
            self._doc_id_set = {self._normalize_doc_id(doc_id) for doc_id in self.doc_ids.tolist()}

    def set_meta(self, meta: dict[str, Any]) -> None:
        with self._lock:
            self.meta = dict(meta)
            self.id_mode = str(self.meta.get("id_mode") or "position")

    def get_meta(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.meta)

    def _remove_ids_locked(self, doc_ids: List[int]) -> int:
        ids = np.asarray(sorted({int(doc_id) for doc_id in doc_ids}), dtype=np.int64)
        if ids.size == 0:
            return 0
        selector = faiss.IDSelectorArray(ids.size, faiss.swig_ptr(ids))
        return int(self.index.remove_ids(selector))

    def _add_with_ids_locked(self, vectors: np.ndarray, doc_ids: np.ndarray) -> None:
        if not hasattr(self.index, "add_with_ids"):
            raise RuntimeError("FAISS index does not support add_with_ids")
        self.index.add_with_ids(vectors.astype("float32"), doc_ids.astype(np.int64))

    def _persist_locked(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_ids_path.parent.mkdir(parents=True, exist_ok=True)

        index_tmp = self.index_path.with_name(f"{self.index_path.name}.tmp")
        doc_ids_tmp = self.doc_ids_path.with_name(f"{self.doc_ids_path.name}.tmp")

        faiss.write_index(self.index, str(index_tmp))
        with open(doc_ids_tmp, "wb") as file_obj:
            np.save(file_obj, self.doc_ids)

        os.replace(index_tmp, self.index_path)
        os.replace(doc_ids_tmp, self.doc_ids_path)
        if self.meta:
            meta_tmp = self.meta_path.with_name(f"{self.meta_path.name}.tmp")
            with open(meta_tmp, "w", encoding="utf-8") as meta_file:
                json.dump(self.meta, meta_file, ensure_ascii=False, indent=2)
            os.replace(meta_tmp, self.meta_path)

    def _load_meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            return {}
        with open(self.meta_path, "r", encoding="utf-8") as meta_file:
            data = json.load(meta_file)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _normalize_doc_id(doc_id: Any) -> Any:
        if isinstance(doc_id, np.generic):
            doc_id = doc_id.item()
        if isinstance(doc_id, bytes):
            doc_id = doc_id.decode("utf-8", errors="ignore")
        if isinstance(doc_id, str):
            text = doc_id.strip()
            if not text:
                return text
            try:
                return int(text)
            except ValueError:
                return text
        try:
            return int(doc_id)
        except (TypeError, ValueError):
            return str(doc_id)


__all__ = ["FaissIndex"]

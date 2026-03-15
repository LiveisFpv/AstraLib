"""Wrapper around FAISS index and document id mapping."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List, Tuple

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
        self._lock = threading.RLock()

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

        self._doc_id_set = {int(doc_id) for doc_id in self.doc_ids.tolist()}

        if self.index.ntotal != len(self.doc_ids):
            raise RuntimeError(
                "FAISS index vector count does not match doc_ids length"
            )

    def search(self, vector: np.ndarray, top_k: int) -> Tuple[List[int], List[float]]:
        if vector.ndim == 1:
            vector = vector.reshape(1, -1)
        with self._lock:
            scores, indices = self.index.search(vector.astype("float32"), top_k)
            matched_ids: List[int] = []
            matched_scores: List[float] = []
            for idx, score in zip(indices[0], scores[0]):
                if idx < 0:
                    continue
                matched_ids.append(int(self.doc_ids[idx]))
                matched_scores.append(float(score))
            return matched_ids, matched_scores

    def contains_doc_id(self, doc_id: int) -> bool:
        with self._lock:
            return int(doc_id) in self._doc_id_set

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
            self.index.add(batch)
            self.doc_ids = np.concatenate(
                [self.doc_ids.astype(np.int64, copy=False), np.asarray(new_doc_ids, dtype=np.int64)]
            )
            self._doc_id_set.update(new_doc_ids)
            self._persist_locked()
            return len(new_doc_ids)

    def _persist_locked(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_ids_path.parent.mkdir(parents=True, exist_ok=True)

        index_tmp = self.index_path.with_name(f"{self.index_path.name}.tmp")
        doc_ids_tmp = self.doc_ids_path.with_name(f"{self.doc_ids_path.name}.tmp")

        faiss.write_index(self.index, str(index_tmp))
        with open(doc_ids_tmp, "wb") as file_obj:
            np.save(file_obj, self.doc_ids.astype(np.int64, copy=False))

        os.replace(index_tmp, self.index_path)
        os.replace(doc_ids_tmp, self.doc_ids_path)


__all__ = ["FaissIndex"]

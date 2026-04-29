"""FAISS-backed semantic search using injected dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.domain.models.search import SearchResult
from src.al_models.e5.encoder import SemanticEncoder
from src.domain.models.paper import PaperModel
from src.services.search.faiss_index import FaissIndex
from src.storage.paper_repository import PaperRepository

class FaissSearcher:
    def __init__(
        self,
        encoder: SemanticEncoder,
        index: FaissIndex,
        repository: PaperRepository,
    ) -> None:
        self.encoder = encoder
        self.index = index
        self.repository = repository

    def search(self, query: str, *, top_k: int = 5) -> List[SearchResult]:
        query_vec = self.encoder.embed_query(query)
        doc_ids, scores = self.index.search(query_vec, top_k)

        rows = self.repository.fetch_ordered(doc_ids)

        results: List[SearchResult] = []
        for idx, row in enumerate(rows):
            if not row:
                continue
            paper = PaperModel(
                row["paper_id"],
                Title=row.get("title") or "",
                Abstract=row.get("abstract") or "",
                Year=row.get("year") or 0,
                Best_oa_location=(row.get("best_oa_location") or ""),
                Referenced_works=list(row.get("referenced_works") or []),
                Related_works=list(row.get("related_works") or []),
                Cited_by_count=int(row.get("cited_by_count") or 0),
                Authors=list(row.get("authors") or []),
                Institutions=list(row.get("institutions") or []),
                Identifiers=list(row.get("identifiers") or []),
            )
            score = scores[idx] if idx < len(scores) else 0.0
            results.append(SearchResult(paper=paper, score=float(score)))
        return results

    def close(self) -> None:
        self.encoder.close()


__all__ = ["FaissSearcher", "SearchResult"]

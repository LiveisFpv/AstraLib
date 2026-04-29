"""High-level search service leveraging FAISS index and Postgres metadata."""

from __future__ import annotations

from typing import List

from src.domain.models.search import SearchResult
from src.services.search.faiss_searcher import FaissSearcher


class SearchService:
    def __init__(self, semantic_searcher: FaissSearcher) -> None:
        self.semantic_searcher = semantic_searcher

    def search_paper(self, text: str, top_k: int = 5) -> List[SearchResult]:
        results = self.semantic_searcher.search(text, top_k=top_k)
        return results

    def close(self) -> None:
        self.semantic_searcher.close()

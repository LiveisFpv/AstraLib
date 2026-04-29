from src.domain.models.paper import PaperModel
from dataclasses import dataclass

@dataclass(slots=True)
class SearchResult:
    paper: PaperModel
    score: float
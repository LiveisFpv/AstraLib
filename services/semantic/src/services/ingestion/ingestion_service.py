"""High-level ingestion orchestration for queue processing and OpenAlex sync."""

from __future__ import annotations

from typing import Any

from src.al_models.e5.encoder import SemanticEncoder
from src.lib.logger import Logger
from src.services.ingestion.models import AuthorSubmission, SOURCE_AUTHOR_SUBMISSION, StoredPaper
from src.services.ingestion.openalex_client import OpenAlexClient
from src.services.ingestion.settings import IngestionSettings
from src.services.search.faiss_index import FaissIndex
from src.storage.ingestion_repository import IngestionRepository
from src.storage.paper_ingestion_repository import PaperIngestionRepository


class IngestionService:
    def __init__(
        self,
        *,
        queue_repository: IngestionRepository,
        paper_repository: PaperIngestionRepository,
        encoder: SemanticEncoder,
        index: FaissIndex,
        settings: IngestionSettings,
        logger: Logger,
        openalex_client: OpenAlexClient | None = None,
    ) -> None:
        self.queue_repository = queue_repository
        self.paper_repository = paper_repository
        self.encoder = encoder
        self.index = index
        self.settings = settings
        self.logger = logger
        self.openalex_client = openalex_client

    def enqueue_author_submission(self, submission: AuthorSubmission) -> int:
        task = self.queue_repository.enqueue_task(
            source=SOURCE_AUTHOR_SUBMISSION,
            payload=submission.to_payload(),
            max_attempts=self.settings.task_max_attempts,
        )
        self.logger.info("Queued author submission for ingestion", task_id=task.task_id, source=task.source)
        return task.task_id

    def process_pending_tasks(self, *, limit: int | None = None) -> int:
        task_limit = limit or self.settings.max_tasks_per_tick
        tasks = self.queue_repository.claim_tasks(limit=task_limit)
        processed = 0
        for task in tasks:
            processed += 1
            try:
                result = self._process_task(task.source, task.payload)
                self.queue_repository.mark_completed(task.task_id, result=result)
                self.logger.info(
                    "Completed ingestion task",
                    task_id=task.task_id,
                    source=task.source,
                    indexed_count=result.get("indexed_count", 0),
                )
            except Exception as exc:
                retry_after = None
                if task.attempts < task.max_attempts:
                    retry_after = self.settings.task_retry_delay_seconds
                self.queue_repository.mark_failed(
                    task.task_id,
                    error=str(exc),
                    retry_after_seconds=retry_after,
                )
                self.logger.error(
                    "Failed ingestion task",
                    task_id=task.task_id,
                    source=task.source,
                    error=str(exc),
                    will_retry=retry_after is not None,
                )
        return processed

    def run_openalex_sync(self, *, limit: int | None = None) -> dict[str, Any]:
        if not self.settings.openalex_enabled:
            return {"fetched_count": 0, "stored_count": 0, "indexed_count": 0}
        if self.openalex_client is None:
            raise RuntimeError("OpenAlex client is not configured")

        papers = self.openalex_client.fetch_latest(limit=limit)
        stored = self.paper_repository.upsert_openalex_batch(papers)
        indexed_count = self._index_papers(stored)
        result = {
            "fetched_count": len(papers),
            "stored_count": len(stored),
            "indexed_count": indexed_count,
        }
        self.logger.info(
            "Completed OpenAlex sync",
            fetched_count=result["fetched_count"],
            stored_count=result["stored_count"],
            indexed_count=result["indexed_count"],
        )
        return result

    def _process_task(self, source: str, payload: dict[str, Any]) -> dict[str, Any]:
        if source != SOURCE_AUTHOR_SUBMISSION:
            raise RuntimeError(f"Unsupported ingestion source: {source}")

        submission = AuthorSubmission.from_payload(payload)
        stored = self.paper_repository.upsert_author_submission(submission)
        indexed_count = self._index_papers([stored])
        return {
            "paper_id": stored.paper_id,
            "indexed_count": indexed_count,
        }

    def _index_papers(self, papers: list[StoredPaper]) -> int:
        candidates = [paper for paper in papers if paper.text and not self.index.contains_doc_id(paper.paper_id)]
        if not candidates:
            return 0

        embeddings = self.encoder.embed_passages([paper.text for paper in candidates])
        return self.index.add_documents(
            [paper.paper_id for paper in candidates],
            embeddings,
        )

    def close(self) -> None:
        if self.openalex_client is not None:
            self.openalex_client.close()


__all__ = ["IngestionService"]

"""Background scheduler for ingestion queue and OpenAlex top-up."""

from __future__ import annotations

import threading
import time

from src.lib.logger import Logger
from src.services.ingestion.ingestion_service import IngestionService
from src.services.ingestion.settings import IngestionSettings


class IngestionScheduler:
    def __init__(
        self,
        *,
        service: IngestionService,
        settings: IngestionSettings,
        logger: Logger,
    ) -> None:
        self.service = service
        self.settings = settings
        self.logger = logger
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_openalex_run = 0.0

    def start(self) -> None:
        if not self.settings.enabled:
            self.logger.info("Ingestion scheduler is disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ingestion-scheduler",
            daemon=True,
        )
        self._thread.start()
        self.logger.info("Ingestion scheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.logger.info("Ingestion scheduler stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(self.settings.poll_interval_seconds)

    def _tick(self) -> None:
        try:
            requeued = self.service.queue_repository.requeue_stale_tasks(
                stale_after_seconds=self.settings.stale_task_timeout_seconds,
            )
            if requeued:
                self.logger.warning("Requeued stale ingestion tasks", count=requeued)

            processed = self.service.process_pending_tasks(limit=self.settings.max_tasks_per_tick)
            if processed:
                self.logger.info("Processed ingestion queue batch", processed=processed)
        except Exception as exc:
            self.logger.error("Ingestion queue tick failed", error=str(exc))

        if not self.settings.openalex_enabled:
            return

        now = time.monotonic()
        if now - self._last_openalex_run < self.settings.openalex_interval_seconds:
            return

        try:
            self.service.run_openalex_sync(limit=self.settings.openalex_limit)
            self._last_openalex_run = now
        except Exception as exc:
            self.logger.error("OpenAlex top-up failed", error=str(exc))


__all__ = ["IngestionScheduler"]

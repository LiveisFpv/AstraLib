"""Configuration for background ingestion and scheduler."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_languages(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    parts = [part.strip().lower() for part in raw.split(",")]
    cleaned = tuple(dict.fromkeys(part for part in parts if part))
    return cleaned or default


@dataclass(slots=True)
class IngestionSettings:
    enabled: bool = _env_bool("INGESTION_SCHEDULER_ENABLED", True)
    poll_interval_seconds: float = float(os.getenv("INGESTION_SCHEDULER_POLL_SECONDS", "15"))
    max_tasks_per_tick: int = int(os.getenv("INGESTION_SCHEDULER_MAX_TASKS", "10"))
    stale_task_timeout_seconds: int = int(os.getenv("INGESTION_TASK_STALE_SECONDS", "900"))
    task_retry_delay_seconds: int = int(os.getenv("INGESTION_TASK_RETRY_SECONDS", "60"))
    task_max_attempts: int = int(os.getenv("INGESTION_TASK_MAX_ATTEMPTS", "3"))

    openalex_enabled: bool = _env_bool("INGESTION_OPENALEX_ENABLED", False)
    openalex_interval_seconds: int = int(os.getenv("INGESTION_OPENALEX_INTERVAL_SECONDS", "3600"))
    openalex_limit: int = int(os.getenv("INGESTION_OPENALEX_LIMIT", "100"))
    openalex_timeout_seconds: int = int(os.getenv("INGESTION_OPENALEX_TIMEOUT_SECONDS", "30"))
    openalex_email: str | None = os.getenv("OPENALEX_EMAIL")
    openalex_languages: tuple[str, ...] = _env_languages("INGESTION_OPENALEX_LANGUAGES", ("en", "ru"))

    @property
    def openalex_per_language_limit(self) -> int:
        lang_count = max(1, len(self.openalex_languages))
        return max(1, math.ceil(max(1, self.openalex_limit) / lang_count))


DEFAULT_INGESTION_SETTINGS = IngestionSettings()


__all__ = ["DEFAULT_INGESTION_SETTINGS", "IngestionSettings"]

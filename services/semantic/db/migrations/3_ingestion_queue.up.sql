BEGIN;

CREATE TABLE ingestion_tasks (
  task_id       BIGSERIAL PRIMARY KEY,
  source        TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
  result        JSONB NULL,
  attempts      INT NOT NULL DEFAULT 0,
  max_attempts  INT NOT NULL DEFAULT 3,
  priority      INT NOT NULL DEFAULT 0,
  scheduled_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at    TIMESTAMPTZ NULL,
  finished_at   TIMESTAMPTZ NULL,
  last_error    TEXT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_ingestion_tasks_status
    CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

CREATE INDEX idx_ingestion_tasks_status_schedule
  ON ingestion_tasks(status, scheduled_at);

CREATE INDEX idx_ingestion_tasks_source_status
  ON ingestion_tasks(source, status);

COMMIT;

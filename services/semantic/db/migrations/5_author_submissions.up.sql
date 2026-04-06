BEGIN;

CREATE TABLE author_submissions (
  submission_id         BIGSERIAL PRIMARY KEY,
  created_by_user_id    INT NOT NULL,
  source_identifier     TEXT NULL,
  title                 TEXT NULL,
  abstract              TEXT NULL,
  year                  INT NULL CHECK (year BETWEEN 0 AND 9999),
  best_oa_location      TEXT NULL,
  status                TEXT NOT NULL,
  moderated_by_user_id  INT NULL,
  moderation_comment    TEXT NULL,
  approved_paper_id     INT NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  submitted_at          TIMESTAMPTZ NULL,
  moderated_at          TIMESTAMPTZ NULL,
  CONSTRAINT chk_author_submissions_status
    CHECK (status IN ('draft', 'pending', 'approved', 'rejected')),
  CONSTRAINT fk_author_submissions_user
    FOREIGN KEY (created_by_user_id) REFERENCES users(id)
      ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_author_submissions_moderator
    FOREIGN KEY (moderated_by_user_id) REFERENCES users(id)
      ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_author_submissions_approved_paper
    FOREIGN KEY (approved_paper_id) REFERENCES papers(paper_id)
      ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE INDEX idx_author_submissions_user_status_updated
  ON author_submissions(created_by_user_id, status, updated_at DESC);

CREATE INDEX idx_author_submissions_status_updated
  ON author_submissions(status, updated_at DESC);

CREATE INDEX idx_author_submissions_source_identifier
  ON author_submissions(created_by_user_id, source_identifier);

CREATE TABLE author_submission_links (
  submission_id   BIGINT NOT NULL,
  relation_type   TEXT NOT NULL,
  identifier      TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (submission_id, relation_type, identifier),
  CONSTRAINT chk_author_submission_links_relation_type
    CHECK (relation_type IN ('referenced', 'related')),
  CONSTRAINT fk_author_submission_links_submission
    FOREIGN KEY (submission_id) REFERENCES author_submissions(submission_id)
      ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX idx_author_submission_links_submission_relation
  ON author_submission_links(submission_id, relation_type);

COMMIT;

BEGIN;

CREATE TABLE citation_edges (
  src_paper_id  INT NOT NULL,
  dst_paper_id  INT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (src_paper_id, dst_paper_id),
  CONSTRAINT chk_citation_edges_no_self CHECK (src_paper_id <> dst_paper_id),
  FOREIGN KEY (src_paper_id) REFERENCES papers(paper_id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  FOREIGN KEY (dst_paper_id) REFERENCES papers(paper_id)
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX idx_citation_edges_src ON citation_edges(src_paper_id);
CREATE INDEX idx_citation_edges_dst ON citation_edges(dst_paper_id);

CREATE TABLE pending_citation_edges (
  src_paper_id        INT NOT NULL,
  identifier_type_id  INT NOT NULL,
  identifier          TEXT NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (src_paper_id, identifier_type_id, identifier),
  FOREIGN KEY (src_paper_id) REFERENCES papers(paper_id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  FOREIGN KEY (identifier_type_id) REFERENCES identifier_types(identifier_type_id)
    ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE INDEX idx_pending_citation_edges_src
  ON pending_citation_edges(src_paper_id);

CREATE INDEX idx_pending_citation_edges_identifier
  ON pending_citation_edges(identifier_type_id, identifier);

INSERT INTO citation_edges (src_paper_id, dst_paper_id)
SELECT pr.src_paper_id, pr.dst_paper_id
FROM paper_relations pr
WHERE NOT EXISTS (
  SELECT 1
  FROM paper_relations rev
  WHERE rev.src_paper_id = pr.dst_paper_id
    AND rev.dst_paper_id = pr.src_paper_id
);

DELETE FROM paper_relations pr
WHERE NOT EXISTS (
  SELECT 1
  FROM paper_relations rev
  WHERE rev.src_paper_id = pr.dst_paper_id
    AND rev.dst_paper_id = pr.src_paper_id
);

COMMIT;

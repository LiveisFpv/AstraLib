BEGIN;

INSERT INTO paper_relations (src_paper_id, dst_paper_id)
SELECT src_paper_id, dst_paper_id
FROM citation_edges
ON CONFLICT DO NOTHING;

DROP TABLE IF EXISTS pending_citation_edges;
DROP TABLE IF EXISTS citation_edges;

COMMIT;

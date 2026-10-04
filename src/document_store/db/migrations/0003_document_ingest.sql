-- 0003_document_ingest.sql
-- One top-level document per source file, and an audit trail for route changes.

CREATE UNIQUE INDEX idx_document_source_top_level
    ON document(source_file_id)
    WHERE parent_id IS NULL;

CREATE TABLE document_route_change (
    id                 INTEGER PRIMARY KEY,
    document_id        INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    from_route         TEXT    NOT NULL CHECK (from_route IN (
                           'standard', 'local_only', 'index_only', 'external')),
    to_route           TEXT    NOT NULL CHECK (to_route IN (
                           'standard', 'local_only', 'index_only', 'external')),
    change_kind        TEXT    NOT NULL CHECK (change_kind IN ('automatic', 'manual')),
    is_downgrade       INTEGER NOT NULL CHECK (is_downgrade IN (0, 1)),
    risk_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK (risk_acknowledged IN (0, 1)),
    reason             TEXT,
    changed_at         TEXT    NOT NULL
);

CREATE INDEX idx_document_route_change_document ON document_route_change(document_id);
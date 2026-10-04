-- 0005_unclassified_class.sql
-- Split "other" into two classes:
--   unclassified: system default for files matching no rule (needs review)
--   other:        reviewed, and deliberately assigned as fitting no category
--
-- Existing "other" rows are NOT reinterpreted here. If you have real data
-- predating this migration, decide manually whether each should become
-- "unclassified" or stay "other" before running this. For a fresh start,
-- delete case.sqlite and re-ingest.
--
-- SQLite cannot alter a CHECK constraint in place, so document and
-- document_class_change are rebuilt.

CREATE TABLE document_new (
    id               INTEGER PRIMARY KEY,
    source_file_id   INTEGER NOT NULL REFERENCES source_file(id) ON DELETE CASCADE,
    parent_id        INTEGER REFERENCES document(id) ON DELETE CASCADE,
    title            TEXT,
    doc_class        TEXT    NOT NULL CHECK (doc_class IN (
                         'correspondence', 'court_filing', 'in_camera',
                         'financial_statement', 'receipt', 'other', 'unclassified')),
    processing_route TEXT    NOT NULL CHECK (processing_route IN (
                         'standard', 'local_only', 'index_only', 'external')),
    doc_date         TEXT,
    low_confidence   INTEGER NOT NULL DEFAULT 0 CHECK (low_confidence IN (0, 1)),
    created_at       TEXT    NOT NULL
);

INSERT INTO document_new SELECT * FROM document;
DROP TABLE document;
ALTER TABLE document_new RENAME TO document;

CREATE INDEX idx_document_class ON document(doc_class);
CREATE INDEX idx_document_date  ON document(doc_date);
CREATE INDEX idx_document_source_file ON document(source_file_id);
CREATE INDEX idx_document_parent ON document(parent_id);
CREATE UNIQUE INDEX idx_document_source_top_level
    ON document(source_file_id)
    WHERE parent_id IS NULL;

CREATE TABLE document_class_change_new (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    from_class  TEXT    NOT NULL CHECK (from_class IN (
                    'correspondence', 'court_filing', 'in_camera',
                    'financial_statement', 'receipt', 'other', 'unclassified')),
    to_class    TEXT    NOT NULL CHECK (to_class IN (
                    'correspondence', 'court_filing', 'in_camera',
                    'financial_statement', 'receipt', 'other', 'unclassified')),
    reason      TEXT    NOT NULL,
    changed_at  TEXT    NOT NULL
);

INSERT INTO document_class_change_new SELECT * FROM document_class_change;
DROP TABLE document_class_change;
ALTER TABLE document_class_change_new RENAME TO document_class_change;

CREATE INDEX idx_document_class_change_document ON document_class_change(document_id);
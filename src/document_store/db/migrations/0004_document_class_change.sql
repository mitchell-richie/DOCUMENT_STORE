-- 0004_document_class_change.sql
-- Audit trail for manual changes to a document's class.

CREATE TABLE document_class_change (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    from_class  TEXT    NOT NULL CHECK (from_class IN (
                    'correspondence', 'court_filing', 'in_camera',
                    'financial_statement', 'receipt', 'other')),
    to_class    TEXT    NOT NULL CHECK (to_class IN (
                    'correspondence', 'court_filing', 'in_camera',
                    'financial_statement', 'receipt', 'other')),
    reason      TEXT    NOT NULL,
    changed_at  TEXT    NOT NULL
);

CREATE INDEX idx_document_class_change_document ON document_class_change(document_id);
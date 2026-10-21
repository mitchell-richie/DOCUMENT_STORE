-- 0006_document_page_ocr.sql
-- Per-page OCR confidence and review state (STORY-3.9).
-- document.low_confidence is derived from this table: it is 1 while any page
-- of the document has low_confidence = 1 and reviewed_at IS NULL.

CREATE TABLE document_page_ocr (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    page_number     INTEGER NOT NULL CHECK (page_number >= 1),
    engine          TEXT    NOT NULL,
    engine_tag      TEXT    NOT NULL,
    mean_confidence REAL    NOT NULL CHECK (mean_confidence >= 0 AND mean_confidence <= 1),
    low_confidence  INTEGER NOT NULL CHECK (low_confidence IN (0, 1)),
    recorded_at     TEXT    NOT NULL,
    reviewed_at     TEXT,
    review_note     TEXT,
    UNIQUE (document_id, page_number)
);
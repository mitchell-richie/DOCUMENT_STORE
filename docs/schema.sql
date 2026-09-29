CREATE INDEX idx_chunk_document ON chunk(document_id);
CREATE INDEX idx_document_class ON document(doc_class);
CREATE INDEX idx_document_date  ON document(doc_date);
CREATE INDEX idx_document_parent ON document(parent_id);
CREATE INDEX idx_document_source_file ON document(source_file_id);
CREATE INDEX idx_email_message_sent   ON email_message(sent_at);
CREATE INDEX idx_email_message_thread ON email_message(thread_id);
CREATE INDEX idx_entity_mention_chunk  ON entity_mention(chunk_id);
CREATE INDEX idx_entity_mention_entity ON entity_mention(entity_id);
CREATE INDEX idx_entity_name ON entity(canonical_name);
CREATE INDEX idx_event_date   ON event(event_date);
CREATE INDEX idx_event_entity_entity ON event_entity(entity_id);
CREATE INDEX idx_event_status ON event(status);
CREATE INDEX idx_message_participant_entity ON message_participant(entity_id);
CREATE INDEX idx_processing_run_stage ON processing_run(stage);
CREATE INDEX idx_relationship_source ON relationship(source_type, source_id);
CREATE INDEX idx_relationship_target ON relationship(target_type, target_id);
CREATE INDEX idx_review_item_pending ON review_item(decided_at);
CREATE TABLE chunk (
    id             INTEGER PRIMARY KEY,
    document_id    INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    ordinal        INTEGER NOT NULL CHECK (ordinal >= 0),
    page_start     INTEGER,
    page_end       INTEGER,
    text           TEXT    NOT NULL,
    char_start     INTEGER NOT NULL CHECK (char_start >= 0),
    char_end       INTEGER NOT NULL CHECK (char_end >= char_start),
    chunk_method   TEXT    NOT NULL,
    ocr_confidence REAL CHECK (ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)),
    UNIQUE (document_id, ordinal)
);
CREATE TABLE document (
    id                INTEGER PRIMARY KEY,
    source_file_id    INTEGER NOT NULL REFERENCES source_file(id) ON DELETE CASCADE,
    parent_id         INTEGER REFERENCES document(id) ON DELETE CASCADE,
    title             TEXT,
    doc_class         TEXT    NOT NULL CHECK (doc_class IN (
                          'correspondence', 'court_filing', 'in_camera',
                          'financial_statement', 'receipt', 'other')),
    processing_route TEXT    NOT NULL CHECK (processing_route IN (
                          'standard', 'local_only', 'index_only', 'external')),
    doc_date          TEXT,
    low_confidence    INTEGER NOT NULL DEFAULT 0 CHECK (low_confidence IN (0, 1)),
    created_at        TEXT    NOT NULL
);
CREATE TABLE email_message (
    id                 INTEGER PRIMARY KEY,
    document_id        INTEGER NOT NULL UNIQUE REFERENCES document(id) ON DELETE CASCADE,
    thread_id          INTEGER REFERENCES email_thread(id) ON DELETE SET NULL,
    message_id_header  TEXT UNIQUE,
    in_reply_to        TEXT,
    sent_at            TEXT,
    subject            TEXT,
    thread_confidence  TEXT NOT NULL DEFAULT 'high' CHECK (thread_confidence IN ('high', 'low'))
);
CREATE TABLE email_thread (
    id                INTEGER PRIMARY KEY,
    subject_normalised TEXT,
    first_sent_at    TEXT,
    last_sent_at     TEXT
);
CREATE TABLE entity (
    id             INTEGER PRIMARY KEY,
    entity_type    TEXT NOT NULL CHECK (entity_type IN ('person', 'organisation', 'place', 'issue')),
    canonical_name TEXT NOT NULL,
    notes          TEXT,
    created_at     TEXT NOT NULL
);
CREATE TABLE entity_alias (
    id              INTEGER PRIMARY KEY,
    entity_id       INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    alias           TEXT    NOT NULL,
    source_chunk_id INTEGER REFERENCES chunk(id) ON DELETE SET NULL,
    UNIQUE (entity_id, alias)
);
CREATE TABLE entity_mention (
    id          INTEGER PRIMARY KEY,
    entity_id   INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    chunk_id    INTEGER NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
    quote       TEXT    NOT NULL,
    confidence  REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    status      TEXT    NOT NULL DEFAULT 'proposed' CHECK (status IN (
                    'proposed', 'confirmed', 'edited', 'rejected')),
    created_at  TEXT    NOT NULL
);
CREATE TABLE event (
    id             INTEGER PRIMARY KEY,
    title          TEXT    NOT NULL,
    description    TEXT,
    event_date     TEXT,
    date_precision TEXT    NOT NULL DEFAULT 'unknown' CHECK (date_precision IN (
                       'exact', 'month', 'year', 'approximate', 'unknown')),
    confidence     REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    status         TEXT    NOT NULL DEFAULT 'proposed' CHECK (status IN (
                       'proposed', 'confirmed', 'edited', 'rejected')),
    created_at     TEXT    NOT NULL
);
CREATE TABLE event_entity (
    event_id  INTEGER NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, entity_id)
);
CREATE TABLE event_evidence (
    event_id INTEGER NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    chunk_id INTEGER NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
    quote    TEXT    NOT NULL,
    PRIMARY KEY (event_id, chunk_id)
);
CREATE TABLE external_record (
    id                 INTEGER PRIMARY KEY,
    document_id        INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    external_system    TEXT    NOT NULL,
    external_id        TEXT    NOT NULL,
    summary_date_range TEXT,
    UNIQUE (external_system, external_id)
);
CREATE TABLE message_participant (
    message_id INTEGER NOT NULL REFERENCES email_message(id) ON DELETE CASCADE,
    entity_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL CHECK (role IN ('from', 'to', 'cc')),
    PRIMARY KEY (message_id, entity_id, role)
);
CREATE TABLE processing_run (
    id          INTEGER PRIMARY KEY,
    stage       TEXT NOT NULL,
    model_id    TEXT,
    parameters  TEXT,                     -- JSON
    started_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE relationship (
    id                INTEGER PRIMARY KEY,
    source_type       TEXT    NOT NULL CHECK (source_type IN ('entity', 'event')),
    source_id         INTEGER NOT NULL,
    target_type       TEXT    NOT NULL CHECK (target_type IN ('entity', 'event')),
    target_id         INTEGER NOT NULL,
    relationship_type TEXT    NOT NULL,
    confidence        REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    status            TEXT    NOT NULL DEFAULT 'proposed' CHECK (status IN (
                          'proposed', 'confirmed', 'edited', 'rejected')),
    evidence_chunk_id INTEGER REFERENCES chunk(id) ON DELETE SET NULL,
    created_at        TEXT    NOT NULL
);
CREATE TABLE review_item (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN (
                   'entity_mention', 'event', 'alias', 'relationship', 'classification', 'ocr')),
    payload    TEXT NOT NULL,             -- JSON
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decision   TEXT CHECK (decision IS NULL OR decision IN (
                   'confirmed', 'edited', 'rejected'))
);
CREATE TABLE schema_migrations ( version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);
CREATE TABLE source_file (
    id          INTEGER PRIMARY KEY,
    sha256      TEXT    NOT NULL UNIQUE,
    size_bytes  INTEGER NOT NULL CHECK (size_bytes >= 0),
    mime_type   TEXT,
    imported_at TEXT    NOT NULL
);
CREATE TABLE source_file_location (
    id              INTEGER PRIMARY KEY,
    source_file_id  INTEGER NOT NULL REFERENCES source_file(id) ON DELETE CASCADE,
    path            TEXT    NOT NULL UNIQUE,
    first_seen_at   TEXT    NOT NULL
);
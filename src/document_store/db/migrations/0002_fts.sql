-- 0002_fts.sql
-- Full-text index over chunk text (FTS5, external-content table).
-- Triggers keep chunk_fts in step with chunk, including cascade deletes.

CREATE VIRTUAL TABLE chunk_fts USING fts5(
    text,
    content = 'chunk',
    content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER chunk_fts_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts (rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER chunk_fts_ad AFTER DELETE ON chunk BEGIN
    INSERT INTO chunk_fts (chunk_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER chunk_fts_au AFTER UPDATE OF text ON chunk BEGIN
    INSERT INTO chunk_fts (chunk_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunk_fts (rowid, text) VALUES (new.id, new.text);
END;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO metadata(key, value) VALUES ('schema_version', '1')
ON CONFLICT(key) DO UPDATE SET value = excluded.value;

CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    path UNINDEXED,
    content,
    tokenize = 'trigram'
);

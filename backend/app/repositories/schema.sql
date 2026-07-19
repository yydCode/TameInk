PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    path UNINDEXED,
    content,
    tokenize = 'trigram'
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('read', 'write')),
    purpose TEXT NOT NULL DEFAULT 'manual' CHECK (
        purpose IN (
            'manual', 'setting', 'commercial', 'book_outline', 'volume_outline',
            'chapter', 'import', 'commercial_audit', 'memory_curation', 'export'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'pending', 'running', 'awaiting_approval', 'completed',
            'failed', 'cancelled', 'interrupted'
        )
    ),
    subject_id TEXT,
    volume_id TEXT,
    chapter_id TEXT,
    parent_task_id TEXT,
    retry_of_task_id TEXT,
    cancel_requested_at TEXT,
    error_code TEXT,
    error_message TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_write_task_per_project
ON tasks(project_id)
WHERE kind = 'write'
  AND status IN ('pending', 'running', 'awaiting_approval');

CREATE TRIGGER IF NOT EXISTS enforce_task_status_transition
BEFORE UPDATE OF status ON tasks
WHEN NEW.status <> OLD.status AND NOT (
    (OLD.status = 'pending' AND NEW.status IN ('running', 'cancelled')) OR
    (OLD.status = 'running' AND NEW.status IN (
        'awaiting_approval', 'completed', 'failed', 'cancelled', 'interrupted'
    )) OR
    (OLD.status = 'awaiting_approval' AND NEW.status IN ('running', 'cancelled')) OR
    (OLD.status = 'interrupted' AND NEW.status IN ('running', 'cancelled', 'failed'))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid task transition');
END;

CREATE TABLE IF NOT EXISTS task_events (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    type TEXT NOT NULL CHECK (length(trim(type)) > 0),
    timestamp TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (task_id, sequence)
);

CREATE TABLE IF NOT EXISTS commercial_observations (
    id TEXT PRIMARY KEY,
    observed_at TEXT NOT NULL,
    impressions INTEGER NOT NULL CHECK (impressions > 0),
    opens INTEGER NOT NULL CHECK (opens > 0 AND opens <= impressions),
    chapter_one_completions INTEGER NOT NULL CHECK (
        chapter_one_completions >= 0 AND chapter_one_completions <= opens
    ),
    chapter_three_completions INTEGER NOT NULL CHECK (
        chapter_three_completions >= 0
        AND chapter_three_completions <= chapter_one_completions
    ),
    follows INTEGER NOT NULL CHECK (follows >= 0 AND follows <= opens),
    read_minutes INTEGER NOT NULL CHECK (read_minutes >= 0),
    revenue_cents INTEGER NOT NULL CHECK (revenue_cents >= 0)
);

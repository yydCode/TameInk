PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 全文搜索索引：内容由 Python 端 jieba 分词后以空格分隔存入，tokenizer 按空格分词
CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    path UNINDEXED,
    content,
    tokenize = 'unicode61 remove_diacritics 0'
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

CREATE TABLE IF NOT EXISTS task_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('info', 'warning', 'error')),
    component TEXT NOT NULL CHECK (length(trim(component)) > 0),
    event TEXT NOT NULL CHECK (length(trim(event)) > 0),
    agent TEXT,
    details TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS task_logs_by_task_id
ON task_logs(task_id, id);

CREATE TABLE IF NOT EXISTS creative_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'reader_contract', 'story_engine', 'character_state', 'expectation',
            'story_card', 'chapter_plan', 'chapter_draft', 'evidence_finding',
            'actual_event', 'memory_proposal', 'ending_plan'
        )
    ),
    source_layer TEXT NOT NULL CHECK (source_layer IN ('candidate', 'hypothesis')),
    status TEXT NOT NULL CHECK (
        status IN (
            'candidate', 'needs_decision', 'conflict', 'ready',
            'awaiting_approval', 'accepted', 'rejected'
        )
    ),
    payload_path TEXT NOT NULL CHECK (length(trim(payload_path)) > 0),
    accepted_layer TEXT CHECK (accepted_layer IN ('canon', 'commitment')),
    formal_path TEXT,
    accepted_decision_id TEXT REFERENCES artifact_decisions(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (
            status = 'accepted'
            AND source_layer = 'candidate'
            AND accepted_layer IS NOT NULL
            AND formal_path IS NOT NULL
            AND accepted_decision_id IS NOT NULL
        ) OR (
            status <> 'accepted'
            AND accepted_layer IS NULL
            AND formal_path IS NULL
            AND accepted_decision_id IS NULL
        )
    ),
    CHECK (
        formal_path IS NULL
        OR (accepted_layer = 'canon' AND (
            formal_path LIKE 'canon/%' OR formal_path LIKE 'memory/%'
        ))
        OR (accepted_layer = 'commitment' AND formal_path LIKE 'commitments/%')
    ),
    CHECK (kind <> 'evidence_finding' OR source_layer = 'hypothesis'),
    CHECK (
        status <> 'accepted'
        OR (kind = 'reader_contract' AND formal_path = 'commitments/reader-contract.yaml')
        OR (kind = 'story_engine' AND formal_path = 'commitments/story-engine.yaml')
        OR (kind = 'ending_plan' AND formal_path = 'commitments/ending-plan.yaml')
        OR (kind = 'character_state' AND formal_path LIKE 'canon/characters/%')
        OR (kind = 'expectation' AND formal_path LIKE 'commitments/expectations/%')
        OR (kind IN ('story_card', 'chapter_plan')
            AND formal_path LIKE 'commitments/story-cards/%')
        OR (kind = 'chapter_draft' AND formal_path LIKE 'canon/chapters/%')
        OR (kind = 'actual_event' AND formal_path LIKE 'canon/actual-events/%')
        OR (kind = 'memory_proposal' AND (
            formal_path LIKE 'canon/characters/%'
            OR formal_path LIKE 'canon/actual-events/%'
            OR formal_path LIKE 'memory/%'
        ))
    )
);

CREATE TABLE IF NOT EXISTS artifact_decisions (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES creative_artifacts(id),
    project_id TEXT NOT NULL,
    expected_status TEXT NOT NULL CHECK (
        expected_status IN (
            'candidate', 'needs_decision', 'conflict', 'ready',
            'awaiting_approval', 'accepted', 'rejected'
        )
    ),
    action TEXT NOT NULL CHECK (action IN ('accept', 'reject', 'mix', 'revise', 'replan')),
    rationale TEXT,
    effects TEXT NOT NULL,
    target_layer TEXT CHECK (target_layer IN ('canon', 'commitment')),
    formal_path TEXT,
    created_at TEXT NOT NULL,
    CHECK (
        (action IN ('accept', 'mix') AND target_layer IS NOT NULL AND formal_path IS NOT NULL)
        OR (action NOT IN ('accept', 'mix') AND target_layer IS NULL AND formal_path IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS artifacts_by_project_status
ON creative_artifacts(project_id, status, created_at);

CREATE INDEX IF NOT EXISTS decisions_by_artifact
ON artifact_decisions(artifact_id, created_at);

CREATE TRIGGER IF NOT EXISTS protect_artifact_identity
BEFORE UPDATE OF project_id, task_id, kind, source_layer, payload_path, created_at
ON creative_artifacts
BEGIN
    SELECT RAISE(ABORT, 'artifact identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS enforce_artifact_status_transition
BEFORE UPDATE OF status ON creative_artifacts
WHEN NEW.status <> OLD.status AND NOT (
    (OLD.status = 'candidate' AND NEW.status IN (
        'needs_decision', 'conflict', 'ready', 'rejected'
    )) OR
    (OLD.status = 'needs_decision' AND NEW.status IN ('candidate', 'rejected')) OR
    (OLD.status = 'conflict' AND NEW.status IN ('candidate', 'rejected')) OR
    (OLD.status = 'ready' AND NEW.status IN (
        'candidate', 'awaiting_approval', 'rejected'
    )) OR
    (OLD.status = 'awaiting_approval' AND NEW.status IN (
        'candidate', 'accepted', 'rejected'
    ))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid artifact transition');
END;

CREATE TRIGGER IF NOT EXISTS enforce_artifact_acceptance_decision
BEFORE UPDATE OF status ON creative_artifacts
WHEN NEW.status = 'accepted' AND NOT EXISTS (
    SELECT 1 FROM artifact_decisions
    WHERE id = NEW.accepted_decision_id
      AND artifact_id = OLD.id
      AND project_id = OLD.project_id
      AND expected_status = OLD.status
      AND action IN ('accept', 'mix')
)
BEGIN
    SELECT RAISE(ABORT, 'artifact acceptance requires author decision');
END;

CREATE TRIGGER IF NOT EXISTS enforce_artifact_rejection_decision
BEFORE UPDATE OF status ON creative_artifacts
WHEN NEW.status = 'rejected' AND NOT EXISTS (
    SELECT 1 FROM artifact_decisions
    WHERE artifact_id = OLD.id
      AND project_id = OLD.project_id
      AND expected_status = OLD.status
      AND action = 'reject'
)
BEGIN
    SELECT RAISE(ABORT, 'artifact rejection requires author decision');
END;

CREATE TRIGGER IF NOT EXISTS enforce_artifact_revision_decision
BEFORE UPDATE OF status ON creative_artifacts
WHEN NEW.status = 'candidate' AND OLD.status <> 'candidate' AND NOT EXISTS (
    SELECT 1 FROM artifact_decisions
    WHERE artifact_id = OLD.id
      AND project_id = OLD.project_id
      AND expected_status = OLD.status
      AND action IN ('revise', 'replan')
)
BEGIN
    SELECT RAISE(ABORT, 'artifact revision requires author decision');
END;

CREATE TRIGGER IF NOT EXISTS protect_artifact_decision_updates
BEFORE UPDATE ON artifact_decisions
BEGIN
    SELECT RAISE(ABORT, 'artifact decision is immutable');
END;

CREATE TRIGGER IF NOT EXISTS protect_artifact_decision_deletes
BEFORE DELETE ON artifact_decisions
BEGIN
    SELECT RAISE(ABORT, 'artifact decision is immutable');
END;

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

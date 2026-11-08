PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id      TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id      TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    payload_json    TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS cases (
    case_id         TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'reopened')),
    summary_json    TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_user ON cases(user_id, status);

CREATE TABLE IF NOT EXISTS case_events (
    event_id    TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    event_type  TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    UNIQUE (case_id, sequence_no)
);
CREATE INDEX IF NOT EXISTS idx_events_case ON case_events(case_id, sequence_no);

CREATE TABLE IF NOT EXISTS case_facts (
    fact_id            TEXT PRIMARY KEY,
    case_id            TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    fact_type          TEXT NOT NULL,
    raw_value          TEXT NOT NULL,
    normalised_value_json TEXT,
    source_type        TEXT NOT NULL CHECK (source_type IN ('user_message', 'evidence')),
    source_id          TEXT NOT NULL,
    evidence_id        TEXT,
    page_number        INTEGER,
    status             TEXT NOT NULL CHECK (status IN ('user_reported', 'document_supported', 'disputed', 'unknown')),
    inferred           INTEGER NOT NULL DEFAULT 0,
    ambiguity_flag     INTEGER NOT NULL DEFAULT 0,
    supersedes_fact_id TEXT,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_case ON case_facts(case_id, fact_type);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id       TEXT PRIMARY KEY,
    case_id           TEXT REFERENCES cases(case_id) ON DELETE SET NULL,
    original_filename TEXT NOT NULL,
    storage_key       TEXT NOT NULL UNIQUE,
    sha256            TEXT NOT NULL,
    mime_type         TEXT NOT NULL,
    size_bytes        INTEGER NOT NULL,
    extraction_status TEXT NOT NULL,
    error_code        TEXT,
    pages_json        TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_drafts (
    draft_id      TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    draft_type    TEXT NOT NULL,
    content       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'needs_review',
    missing_fields_json TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_snapshots (
    snapshot_id  TEXT PRIMARY KEY,
    case_id      TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    sequence_no  INTEGER NOT NULL,
    state_json   TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

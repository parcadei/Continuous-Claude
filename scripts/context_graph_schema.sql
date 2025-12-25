-- Context Graph Schema
-- Database location: .claude/cache/context-graph/context.db
--
-- This schema supports indexing and querying Claude Code session artifacts:
-- - Handoffs (completed tasks with post-mortems)
-- - Plans (design documents)
-- - Continuity ledgers (session state snapshots)
-- - Queries (compound learning from Q&A)
--
-- FTS5 is used for full-text search with porter stemming.
-- Triggers keep FTS5 indexes in sync with main tables.

-- Handoffs (completed tasks with post-mortems)
CREATE TABLE IF NOT EXISTS handoffs (
    id TEXT PRIMARY KEY,
    session_name TEXT NOT NULL,
    task_number INTEGER,
    file_path TEXT NOT NULL,

    -- Core content
    task_summary TEXT,
    what_worked TEXT,
    what_failed TEXT,
    key_decisions TEXT,
    files_modified TEXT,  -- JSON array

    -- Outcome (from user annotation)
    outcome TEXT CHECK(outcome IN ('SUCCEEDED', 'PARTIAL_PLUS', 'PARTIAL_MINUS', 'FAILED', 'UNKNOWN')),
    outcome_notes TEXT,
    confidence TEXT CHECK(confidence IN ('HIGH', 'INFERRED')) DEFAULT 'INFERRED',

    -- Braintrust trace links (for correlation with session logs)
    root_span_id TEXT,       -- Braintrust trace ID (same for main + subagents)
    turn_span_id TEXT,       -- The turn span that created this handoff
    session_id TEXT,         -- Claude session ID (for debugging)
    braintrust_session_id TEXT,  -- Legacy field (kept for compatibility)

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Plans (design documents)
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    session_name TEXT,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,

    -- Content
    overview TEXT,
    approach TEXT,
    phases TEXT,  -- JSON array
    constraints TEXT,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Continuity snapshots (session state at key moments)
CREATE TABLE IF NOT EXISTS continuity (
    id TEXT PRIMARY KEY,
    session_name TEXT NOT NULL,

    -- State
    goal TEXT,
    state_done TEXT,  -- JSON array
    state_now TEXT,
    state_next TEXT,
    key_learnings TEXT,
    key_decisions TEXT,

    -- Context
    snapshot_reason TEXT CHECK(snapshot_reason IN ('phase_complete', 'session_end', 'milestone', 'manual')),

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Queries (compound learning from Q&A)
CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,

    -- Matches
    handoffs_matched TEXT,  -- JSON array of IDs
    plans_matched TEXT,
    continuity_matched TEXT,
    braintrust_sessions TEXT,

    -- Feedback
    was_helpful BOOLEAN,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 indexes for full-text search
-- Using porter tokenizer for stemming + prefix index for code identifiers
CREATE VIRTUAL TABLE IF NOT EXISTS handoffs_fts USING fts5(
    task_summary, what_worked, what_failed, key_decisions, files_modified,
    content='handoffs', content_rowid='rowid',
    tokenize='porter ascii',
    prefix='2 3'
);

CREATE VIRTUAL TABLE IF NOT EXISTS plans_fts USING fts5(
    title, overview, approach, phases, constraints,
    content='plans', content_rowid='rowid',
    tokenize='porter ascii',
    prefix='2 3'
);

CREATE VIRTUAL TABLE IF NOT EXISTS continuity_fts USING fts5(
    goal, key_learnings, key_decisions, state_now,
    content='continuity', content_rowid='rowid',
    tokenize='porter ascii'
);

CREATE VIRTUAL TABLE IF NOT EXISTS queries_fts USING fts5(
    question, answer,
    content='queries', content_rowid='rowid',
    tokenize='porter ascii'
);

-- Configure BM25 column weights (higher = more important)
-- handoffs: task_summary(10), what_worked(5), what_failed(3), key_decisions(3), files_modified(1)
-- Run after table creation:
-- INSERT INTO handoffs_fts(handoffs_fts, rank) VALUES('rank', 'bm25(10.0, 5.0, 3.0, 3.0, 1.0)');

-- Triggers to keep FTS5 in sync (INSERT, UPDATE, DELETE)

-- HANDOFFS triggers
CREATE TRIGGER IF NOT EXISTS handoffs_ai AFTER INSERT ON handoffs BEGIN
    INSERT INTO handoffs_fts(rowid, task_summary, what_worked, what_failed, key_decisions, files_modified)
    VALUES (NEW.rowid, NEW.task_summary, NEW.what_worked, NEW.what_failed, NEW.key_decisions, NEW.files_modified);
END;

CREATE TRIGGER IF NOT EXISTS handoffs_ad AFTER DELETE ON handoffs BEGIN
    INSERT INTO handoffs_fts(handoffs_fts, rowid, task_summary, what_worked, what_failed, key_decisions, files_modified)
    VALUES('delete', OLD.rowid, OLD.task_summary, OLD.what_worked, OLD.what_failed, OLD.key_decisions, OLD.files_modified);
END;

CREATE TRIGGER IF NOT EXISTS handoffs_au AFTER UPDATE ON handoffs BEGIN
    INSERT INTO handoffs_fts(handoffs_fts, rowid, task_summary, what_worked, what_failed, key_decisions, files_modified)
    VALUES('delete', OLD.rowid, OLD.task_summary, OLD.what_worked, OLD.what_failed, OLD.key_decisions, OLD.files_modified);
    INSERT INTO handoffs_fts(rowid, task_summary, what_worked, what_failed, key_decisions, files_modified)
    VALUES (NEW.rowid, NEW.task_summary, NEW.what_worked, NEW.what_failed, NEW.key_decisions, NEW.files_modified);
END;

-- PLANS triggers
CREATE TRIGGER IF NOT EXISTS plans_ai AFTER INSERT ON plans BEGIN
    INSERT INTO plans_fts(rowid, title, overview, approach, phases, constraints)
    VALUES (NEW.rowid, NEW.title, NEW.overview, NEW.approach, NEW.phases, NEW.constraints);
END;

CREATE TRIGGER IF NOT EXISTS plans_ad AFTER DELETE ON plans BEGIN
    INSERT INTO plans_fts(plans_fts, rowid, title, overview, approach, phases, constraints)
    VALUES('delete', OLD.rowid, OLD.title, OLD.overview, OLD.approach, OLD.phases, OLD.constraints);
END;

CREATE TRIGGER IF NOT EXISTS plans_au AFTER UPDATE ON plans BEGIN
    INSERT INTO plans_fts(plans_fts, rowid, title, overview, approach, phases, constraints)
    VALUES('delete', OLD.rowid, OLD.title, OLD.overview, OLD.approach, OLD.phases, OLD.constraints);
    INSERT INTO plans_fts(rowid, title, overview, approach, phases, constraints)
    VALUES (NEW.rowid, NEW.title, NEW.overview, NEW.approach, NEW.phases, NEW.constraints);
END;

-- CONTINUITY triggers
CREATE TRIGGER IF NOT EXISTS continuity_ai AFTER INSERT ON continuity BEGIN
    INSERT INTO continuity_fts(rowid, goal, key_learnings, key_decisions, state_now)
    VALUES (NEW.rowid, NEW.goal, NEW.key_learnings, NEW.key_decisions, NEW.state_now);
END;

CREATE TRIGGER IF NOT EXISTS continuity_ad AFTER DELETE ON continuity BEGIN
    INSERT INTO continuity_fts(continuity_fts, rowid, goal, key_learnings, key_decisions, state_now)
    VALUES('delete', OLD.rowid, OLD.goal, OLD.key_learnings, OLD.key_decisions, OLD.state_now);
END;

CREATE TRIGGER IF NOT EXISTS continuity_au AFTER UPDATE ON continuity BEGIN
    INSERT INTO continuity_fts(continuity_fts, rowid, goal, key_learnings, key_decisions, state_now)
    VALUES('delete', OLD.rowid, OLD.goal, OLD.key_learnings, OLD.key_decisions, OLD.state_now);
    INSERT INTO continuity_fts(rowid, goal, key_learnings, key_decisions, state_now)
    VALUES (NEW.rowid, NEW.goal, NEW.key_learnings, NEW.key_decisions, NEW.state_now);
END;

-- QUERIES triggers
CREATE TRIGGER IF NOT EXISTS queries_ai AFTER INSERT ON queries BEGIN
    INSERT INTO queries_fts(rowid, question, answer)
    VALUES (NEW.rowid, NEW.question, NEW.answer);
END;

CREATE TRIGGER IF NOT EXISTS queries_ad AFTER DELETE ON queries BEGIN
    INSERT INTO queries_fts(queries_fts, rowid, question, answer)
    VALUES('delete', OLD.rowid, OLD.question, OLD.answer);
END;

CREATE TRIGGER IF NOT EXISTS queries_au AFTER UPDATE ON queries BEGIN
    INSERT INTO queries_fts(queries_fts, rowid, question, answer)
    VALUES('delete', OLD.rowid, OLD.question, OLD.answer);
    INSERT INTO queries_fts(rowid, question, answer)
    VALUES (NEW.rowid, NEW.question, NEW.answer);
END;

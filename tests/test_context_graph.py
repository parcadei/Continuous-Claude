"""Tests for context_graph_index.py parsing functions."""

import json
import tempfile
from pathlib import Path

import pytest


# Test data - representative samples from actual files
SAMPLE_HANDOFF = """---
date: 2025-12-23T17:32:00-08:00
task_number: 1
task_total: 3
status: success
braintrust_session_id: abc123
---

# Task Handoff: Progressive Context Warnings

## What Was Done
- Replaced the single 75% threshold warning with three tiers
- Updated comment to clarify "tiered warnings" purpose

## What Worked
- TypeScript compilation passed
- Hook execution at 70% shows gentle reminder

## What Failed
- Initial test with shell script failed due to unset CLAUDE_PROJECT_DIR

## Key Decisions
- **Threshold values (70/80/90)**: Followed the plan specification

## Files Modified
- `.claude/hooks/skill-activation-prompt.ts:169-196` - Replaced single threshold
- `scripts/context_graph_index.py` - New file

## Patterns/Learnings for Next Tasks
- The hook shell script requires CLAUDE_PROJECT_DIR
"""

SAMPLE_PLAN = """# Plan: Context Graph Implementation

**Created:** 2025-12-24
**Status:** In Progress

## Overview
Build a local SQLite database to index and search handoffs, plans, and continuity ledgers.

## Implementation Approach
Use FTS5 for full-text search with BM25 ranking.

## Phase 1: Schema & Indexer
Create database schema and indexer script.

## Phase 2: Query Script
Create query interface for searching the database.

## What We're Not Doing
- No cloud deployment
- No vector embeddings in Phase 1
"""

SAMPLE_CONTINUITY = """# Session: open-source-release
Updated: 2025-12-24T16:52:06.940Z

## Goal
Prepare Continuous Claude for open source release on GitHub.

## State
- Done:
  - [x] Initial release pushed
  - [x] Codebase cleanup
- Now: [->] Implement Phase 1: Schema & Indexer (TDD)
- Next:
  - [ ] Implement Phase 2: Query Script

## Key Learnings (This Session)
1. LLM-as-judge: scores are theater
2. Paradigm shift: Judging vs Learning

## Key Decisions
- Custom LLM-as-judge over autoevals
"""


class TestParseHandoff:
    """Tests for parse_handoff function."""

    def test_extracts_frontmatter_date(self, tmp_path):
        """Should extract date from frontmatter."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert result["created_at"] == "2025-12-23T17:32:00-08:00"

    def test_extracts_frontmatter_status(self, tmp_path):
        """Should extract status from frontmatter and map to canonical outcome."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        # "success" in frontmatter maps to "SUCCEEDED" canonical value
        assert result["outcome"] == "SUCCEEDED"

    def test_extracts_braintrust_session_id(self, tmp_path):
        """Should extract braintrust_session_id from frontmatter."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert result["braintrust_session_id"] == "abc123"

    def test_extracts_session_name_from_path(self, tmp_path):
        """Should extract session name from file path."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "my-test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert result["session_name"] == "my-test-session"

    def test_extracts_task_number_from_filename(self, tmp_path):
        """Should extract task number from filename."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-05-feature.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert result["task_number"] == 5

    def test_extracts_what_was_done_section(self, tmp_path):
        """Should extract what_was_done section as task_summary."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert "Replaced the single 75% threshold" in result["task_summary"]

    def test_extracts_what_worked_section(self, tmp_path):
        """Should extract what_worked section."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert "TypeScript compilation passed" in result["what_worked"]

    def test_extracts_what_failed_section(self, tmp_path):
        """Should extract what_failed section."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert "unset CLAUDE_PROJECT_DIR" in result["what_failed"]

    def test_extracts_key_decisions_section(self, tmp_path):
        """Should extract key_decisions section."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert "Threshold values" in result["key_decisions"]

    def test_extracts_files_modified(self, tmp_path):
        """Should extract files_modified as JSON array."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)
        files = json.loads(result["files_modified"])

        assert ".claude/hooks/skill-activation-prompt.ts" in files
        assert "scripts/context_graph_index.py" in files

    def test_generates_unique_id(self, tmp_path):
        """Should generate a unique ID based on file path."""
        from scripts.context_graph_index import parse_handoff

        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(SAMPLE_HANDOFF)

        result = parse_handoff(handoff_file)

        assert "id" in result
        assert len(result["id"]) == 12  # MD5 hex prefix

    def test_handles_missing_sections_gracefully(self, tmp_path):
        """Should handle missing sections with empty strings."""
        from scripts.context_graph_index import parse_handoff

        minimal_handoff = """---
status: success
---

# Minimal Handoff

## What Was Done
Just a quick fix.
"""
        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(minimal_handoff)

        result = parse_handoff(handoff_file)

        assert result["what_worked"] == ""
        assert result["what_failed"] == ""

    def test_extracts_h3_subsections_under_post_mortem(self, tmp_path):
        """Should extract h3 subsections (What Worked/Failed/Decisions) under Post-Mortem h2."""
        from scripts.context_graph_index import parse_handoff

        handoff_with_nested_sections = """---
status: success
---

# Task Handoff: Test

## What Was Done
Main task completed.

## Post-Mortem (Required for Context Graph)

### What Worked
- TDD approach was effective
- Using argparse for CLI

### What Failed
- Initial regex was too greedy
- Had to refactor twice

### Key Decisions
- Used SQLite over Postgres
- Chose FTS5 for search

## Next Steps
Continue with Phase 2.
"""
        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "task-01-test.md"
        handoff_file.write_text(handoff_with_nested_sections)

        result = parse_handoff(handoff_file)

        # Should extract h3 sections even when nested under h2 Post-Mortem
        assert "TDD approach was effective" in result["what_worked"]
        assert "Initial regex was too greedy" in result["what_failed"]
        assert "Used SQLite over Postgres" in result["key_decisions"]


class TestExtractFiles:
    """Tests for extract_files helper function."""

    def test_extracts_backtick_file_paths(self):
        """Should extract file paths in backticks."""
        from scripts.context_graph_index import extract_files

        content = """
- `.claude/hooks/skill-activation-prompt.ts` - Updated
- `scripts/context_graph_index.py` - New file
"""
        files = extract_files(content)

        assert ".claude/hooks/skill-activation-prompt.ts" in files
        assert "scripts/context_graph_index.py" in files

    def test_extracts_file_bold_format(self):
        """Should extract file paths in **File**: format."""
        from scripts.context_graph_index import extract_files

        content = """
**File**: `path/to/file.py`
**File**: another/file.ts
"""
        files = extract_files(content)

        assert "path/to/file.py" in files
        assert "another/file.ts" in files


class TestParsePlan:
    """Tests for parse_plan function."""

    def test_extracts_title_from_h1(self, tmp_path):
        """Should extract title from first H1."""
        from scripts.context_graph_index import parse_plan

        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN)

        result = parse_plan(plan_file)

        assert result["title"] == "Plan: Context Graph Implementation"

    def test_extracts_overview_section(self, tmp_path):
        """Should extract overview section."""
        from scripts.context_graph_index import parse_plan

        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN)

        result = parse_plan(plan_file)

        assert "local SQLite database" in result["overview"]

    def test_extracts_approach_section(self, tmp_path):
        """Should extract implementation approach section."""
        from scripts.context_graph_index import parse_plan

        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN)

        result = parse_plan(plan_file)

        assert "FTS5 for full-text search" in result["approach"]

    def test_extracts_phases_as_json(self, tmp_path):
        """Should extract phases as JSON array."""
        from scripts.context_graph_index import parse_plan

        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN)

        result = parse_plan(plan_file)
        phases = json.loads(result["phases"])

        assert len(phases) == 2
        assert any("phase_1" in p["name"] for p in phases)

    def test_extracts_constraints(self, tmp_path):
        """Should extract what we're not doing as constraints."""
        from scripts.context_graph_index import parse_plan

        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN)

        result = parse_plan(plan_file)

        assert "No cloud deployment" in result["constraints"]

    def test_generates_unique_id(self, tmp_path):
        """Should generate unique ID from file path."""
        from scripts.context_graph_index import parse_plan

        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN)

        result = parse_plan(plan_file)

        assert "id" in result
        assert len(result["id"]) == 12


class TestParseContinuity:
    """Tests for parse_continuity function."""

    def test_extracts_session_name_from_filename(self, tmp_path):
        """Should extract session name from filename."""
        from scripts.context_graph_index import parse_continuity

        ledger_file = tmp_path / "CONTINUITY_CLAUDE-my-session.md"
        ledger_file.write_text(SAMPLE_CONTINUITY)

        result = parse_continuity(ledger_file)

        assert result["session_name"] == "my-session"

    def test_extracts_goal_section(self, tmp_path):
        """Should extract goal section."""
        from scripts.context_graph_index import parse_continuity

        ledger_file = tmp_path / "CONTINUITY_CLAUDE-test.md"
        ledger_file.write_text(SAMPLE_CONTINUITY)

        result = parse_continuity(ledger_file)

        assert "open source release" in result["goal"]

    def test_extracts_state_done_as_json(self, tmp_path):
        """Should extract completed state items as JSON array."""
        from scripts.context_graph_index import parse_continuity

        ledger_file = tmp_path / "CONTINUITY_CLAUDE-test.md"
        ledger_file.write_text(SAMPLE_CONTINUITY)

        result = parse_continuity(ledger_file)
        state_done = json.loads(result["state_done"])

        assert len(state_done) >= 2
        assert any("Initial release" in item for item in state_done)

    def test_extracts_state_now(self, tmp_path):
        """Should extract current state item."""
        from scripts.context_graph_index import parse_continuity

        ledger_file = tmp_path / "CONTINUITY_CLAUDE-test.md"
        ledger_file.write_text(SAMPLE_CONTINUITY)

        result = parse_continuity(ledger_file)

        assert "Phase 1" in result["state_now"]

    def test_extracts_key_learnings(self, tmp_path):
        """Should extract key learnings section."""
        from scripts.context_graph_index import parse_continuity

        ledger_file = tmp_path / "CONTINUITY_CLAUDE-test.md"
        ledger_file.write_text(SAMPLE_CONTINUITY)

        result = parse_continuity(ledger_file)

        assert "scores are theater" in result["key_learnings"]

    def test_extracts_key_decisions(self, tmp_path):
        """Should extract key decisions section."""
        from scripts.context_graph_index import parse_continuity

        ledger_file = tmp_path / "CONTINUITY_CLAUDE-test.md"
        ledger_file.write_text(SAMPLE_CONTINUITY)

        result = parse_continuity(ledger_file)

        assert "autoevals" in result["key_decisions"]


class TestGetDbPath:
    """Tests for get_db_path function."""

    def test_uses_default_path_when_none_provided(self, tmp_path, monkeypatch):
        """Should use default path when no custom path provided."""
        from scripts.context_graph_index import get_db_path

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        path = get_db_path()

        assert path == Path(".claude/cache/context-graph/context.db")

    def test_uses_custom_path_when_provided(self, tmp_path):
        """Should use custom path when provided."""
        from scripts.context_graph_index import get_db_path

        custom = tmp_path / "custom" / "db.sqlite"
        path = get_db_path(str(custom))

        assert path == custom

    def test_creates_parent_directories(self, tmp_path):
        """Should create parent directories if they don't exist."""
        from scripts.context_graph_index import get_db_path

        custom = tmp_path / "deep" / "nested" / "path" / "db.sqlite"
        path = get_db_path(str(custom))

        assert path.parent.exists()


class TestIndexing:
    """Integration tests for indexing functions."""

    def test_index_handoffs_counts_files(self, tmp_path):
        """Should return count of indexed handoffs."""
        from scripts.context_graph_index import get_db_path, init_db, index_handoffs

        # Create test handoffs
        handoff_dir = tmp_path / "thoughts" / "handoffs" / "test-session"
        handoff_dir.mkdir(parents=True)
        (handoff_dir / "task-01-test.md").write_text(SAMPLE_HANDOFF)
        (handoff_dir / "task-02-test.md").write_text(SAMPLE_HANDOFF)

        # Create schema file
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        schema_file = scripts_dir / "context_graph_schema.sql"
        schema_file.write_text(get_minimal_schema())

        # Initialize database
        db_path = get_db_path(str(tmp_path / "test.db"))
        conn = init_db(db_path)

        # Index handoffs
        count = index_handoffs(conn, handoff_dir.parent)

        assert count == 2

    def test_index_plans_counts_files(self, tmp_path):
        """Should return count of indexed plans."""
        from scripts.context_graph_index import get_db_path, init_db, index_plans

        # Create test plans
        plans_dir = tmp_path / "thoughts" / "shared" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "plan-one.md").write_text(SAMPLE_PLAN)
        (plans_dir / "plan-two.md").write_text(SAMPLE_PLAN)

        # Create schema file
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        schema_file = scripts_dir / "context_graph_schema.sql"
        schema_file.write_text(get_minimal_schema())

        # Initialize database
        db_path = get_db_path(str(tmp_path / "test.db"))
        conn = init_db(db_path)

        # Index plans
        count = index_plans(conn, plans_dir)

        assert count == 2


def get_minimal_schema():
    """Return a minimal schema for testing."""
    return """
CREATE TABLE IF NOT EXISTS handoffs (
    id TEXT PRIMARY KEY,
    session_name TEXT,
    task_number INTEGER,
    file_path TEXT,
    task_summary TEXT,
    what_worked TEXT,
    what_failed TEXT,
    key_decisions TEXT,
    files_modified TEXT,
    outcome TEXT,
    braintrust_session_id TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    title TEXT,
    file_path TEXT,
    overview TEXT,
    approach TEXT,
    phases TEXT,
    constraints TEXT
);

CREATE TABLE IF NOT EXISTS continuity (
    id TEXT PRIMARY KEY,
    session_name TEXT,
    goal TEXT,
    state_done TEXT,
    state_now TEXT,
    state_next TEXT,
    key_learnings TEXT,
    key_decisions TEXT,
    snapshot_reason TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS handoffs_fts USING fts5(
    task_summary, what_worked, what_failed, key_decisions, files_modified,
    content='handoffs', content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS plans_fts USING fts5(
    title, overview, approach, phases, constraints,
    content='plans', content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS continuity_fts USING fts5(
    goal, key_learnings, key_decisions, state_now,
    content='continuity', content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS queries_fts USING fts5(
    question, answer
);

CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY,
    question TEXT,
    answer TEXT
);
"""

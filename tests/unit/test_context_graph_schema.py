"""
Tests for Context Graph SQL schema.

Verifies:
1. Schema file exists and is valid SQL
2. All expected tables are created
3. FTS5 virtual tables are created
4. Triggers are created for sync
5. Database can be created from schema without errors
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest


SCHEMA_PATH = Path(__file__).parent.parent.parent / "scripts" / "context_graph_schema.sql"

# Expected tables from the schema
EXPECTED_TABLES = {"handoffs", "plans", "continuity", "queries"}
EXPECTED_FTS_TABLES = {"handoffs_fts", "plans_fts", "continuity_fts", "queries_fts"}

# Expected triggers (3 per table: ai=after insert, ad=after delete, au=after update)
EXPECTED_TRIGGERS = {
    "handoffs_ai", "handoffs_ad", "handoffs_au",
    "plans_ai", "plans_ad", "plans_au",
    "continuity_ai", "continuity_ad", "continuity_au",
    "queries_ai", "queries_ad", "queries_au",
}


class TestSchemaFileExists:
    """Test that the schema file exists and is readable."""

    def test_schema_file_exists(self):
        """Schema file should exist at scripts/context_graph_schema.sql."""
        assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"

    def test_schema_file_is_not_empty(self):
        """Schema file should not be empty."""
        assert SCHEMA_PATH.stat().st_size > 0, "Schema file is empty"

    def test_schema_file_is_valid_sql(self):
        """Schema should be parseable as SQL (no syntax errors)."""
        schema_sql = SCHEMA_PATH.read_text()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
            conn = sqlite3.connect(tmp.name)
            try:
                conn.executescript(schema_sql)
            except sqlite3.Error as e:
                pytest.fail(f"Schema SQL has syntax error: {e}")
            finally:
                conn.close()


class TestTableCreation:
    """Test that all expected tables are created."""

    @pytest.fixture
    def db_conn(self):
        """Create an in-memory database with the schema loaded."""
        schema_sql = SCHEMA_PATH.read_text()
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)
        yield conn
        conn.close()

    def test_main_tables_created(self, db_conn):
        """All four main tables should be created."""
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}

        for expected in EXPECTED_TABLES:
            assert expected in tables, f"Table '{expected}' not found. Found: {tables}"

    def test_fts5_tables_created(self, db_conn):
        """FTS5 virtual tables should be created for all main tables."""
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_fts'"
        )
        fts_tables = {row[0] for row in cursor.fetchall()}

        for expected in EXPECTED_FTS_TABLES:
            assert expected in fts_tables, f"FTS5 table '{expected}' not found. Found: {fts_tables}"

    def test_triggers_created(self, db_conn):
        """Sync triggers should be created for all tables."""
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
        triggers = {row[0] for row in cursor.fetchall()}

        for expected in EXPECTED_TRIGGERS:
            assert expected in triggers, f"Trigger '{expected}' not found. Found: {triggers}"


class TestHandoffsTable:
    """Test the handoffs table schema."""

    @pytest.fixture
    def db_conn(self):
        """Create an in-memory database with the schema loaded."""
        schema_sql = SCHEMA_PATH.read_text()
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)
        yield conn
        conn.close()

    def test_handoffs_columns(self, db_conn):
        """Handoffs table should have all expected columns."""
        cursor = db_conn.execute("PRAGMA table_info(handoffs)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            "id", "session_name", "task_number", "file_path",
            "task_summary", "what_worked", "what_failed", "key_decisions", "files_modified",
            "outcome", "outcome_notes", "confidence",
            "braintrust_session_id",
            "created_at", "indexed_at"
        }

        for col in expected_columns:
            assert col in columns, f"Column '{col}' not found in handoffs table. Found: {columns}"

    def test_handoffs_outcome_check_constraint(self, db_conn):
        """Outcome column should only accept valid values."""
        valid_outcomes = ["SUCCEEDED", "PARTIAL_PLUS", "PARTIAL_MINUS", "FAILED", "UNKNOWN"]

        # Valid outcomes should work
        for outcome in valid_outcomes:
            db_conn.execute(
                "INSERT INTO handoffs (id, session_name, file_path, outcome) VALUES (?, 'test', 'test.md', ?)",
                (f"test_{outcome}", outcome)
            )

        # Invalid outcome should fail
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO handoffs (id, session_name, file_path, outcome) VALUES ('invalid', 'test', 'test.md', 'INVALID')"
            )


class TestFTS5Functionality:
    """Test FTS5 full-text search functionality."""

    @pytest.fixture
    def db_conn(self):
        """Create an in-memory database with the schema loaded and test data."""
        schema_sql = SCHEMA_PATH.read_text()
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)

        # Insert test handoff
        conn.execute("""
            INSERT INTO handoffs (id, session_name, file_path, task_summary, what_worked, what_failed, key_decisions, files_modified, outcome)
            VALUES ('test1', 'auth-session', 'handoffs/auth/task-01.md',
                    'Implemented OAuth authentication with JWT tokens',
                    'Using jose library for JWT worked well',
                    'Initial attempt with custom JWT parsing was error-prone',
                    'Chose jose over jsonwebtoken for better TypeScript support',
                    '["src/auth.ts", "src/middleware.ts"]',
                    'SUCCEEDED')
        """)
        conn.commit()

        yield conn
        conn.close()

    def test_fts5_search_finds_matching_content(self, db_conn):
        """FTS5 should find documents matching search terms."""
        cursor = db_conn.execute(
            "SELECT task_summary FROM handoffs_fts WHERE handoffs_fts MATCH 'OAuth'"
        )
        results = cursor.fetchall()
        assert len(results) == 1
        assert "OAuth" in results[0][0]

    def test_fts5_search_with_stemming(self, db_conn):
        """FTS5 with porter tokenizer should handle word stems."""
        # "authentication" should match "Implemented" stem isn't expected,
        # but "authentication" should match exact
        cursor = db_conn.execute(
            "SELECT task_summary FROM handoffs_fts WHERE handoffs_fts MATCH 'authentication'"
        )
        results = cursor.fetchall()
        assert len(results) == 1

    def test_fts5_trigger_inserts_on_new_record(self, db_conn):
        """Inserting into main table should auto-populate FTS table."""
        # Insert new record
        db_conn.execute("""
            INSERT INTO handoffs (id, session_name, file_path, task_summary, outcome)
            VALUES ('test2', 'new-session', 'test.md', 'Added database migration script', 'SUCCEEDED')
        """)
        db_conn.commit()

        # Should be searchable
        cursor = db_conn.execute(
            "SELECT task_summary FROM handoffs_fts WHERE handoffs_fts MATCH 'migration'"
        )
        results = cursor.fetchall()
        assert len(results) == 1

    def test_fts5_trigger_updates_on_record_change(self, db_conn):
        """Updating main table should update FTS table."""
        # Update the record
        db_conn.execute("""
            UPDATE handoffs SET task_summary = 'Implemented SSO authentication with SAML'
            WHERE id = 'test1'
        """)
        db_conn.commit()

        # Old term should not match
        cursor = db_conn.execute(
            "SELECT task_summary FROM handoffs_fts WHERE handoffs_fts MATCH 'OAuth'"
        )
        assert len(cursor.fetchall()) == 0

        # New term should match
        cursor = db_conn.execute(
            "SELECT task_summary FROM handoffs_fts WHERE handoffs_fts MATCH 'SAML'"
        )
        assert len(cursor.fetchall()) == 1

    def test_fts5_trigger_deletes_on_record_removal(self, db_conn):
        """Deleting from main table should remove from FTS table."""
        # Delete the record
        db_conn.execute("DELETE FROM handoffs WHERE id = 'test1'")
        db_conn.commit()

        # Should not be searchable
        cursor = db_conn.execute(
            "SELECT task_summary FROM handoffs_fts WHERE handoffs_fts MATCH 'OAuth'"
        )
        assert len(cursor.fetchall()) == 0


class TestPlansTable:
    """Test the plans table schema."""

    @pytest.fixture
    def db_conn(self):
        """Create an in-memory database with the schema loaded."""
        schema_sql = SCHEMA_PATH.read_text()
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)
        yield conn
        conn.close()

    def test_plans_columns(self, db_conn):
        """Plans table should have all expected columns."""
        cursor = db_conn.execute("PRAGMA table_info(plans)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            "id", "session_name", "title", "file_path",
            "overview", "approach", "phases", "constraints",
            "created_at", "indexed_at"
        }

        for col in expected_columns:
            assert col in columns, f"Column '{col}' not found in plans table. Found: {columns}"


class TestContinuityTable:
    """Test the continuity table schema."""

    @pytest.fixture
    def db_conn(self):
        """Create an in-memory database with the schema loaded."""
        schema_sql = SCHEMA_PATH.read_text()
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)
        yield conn
        conn.close()

    def test_continuity_columns(self, db_conn):
        """Continuity table should have all expected columns."""
        cursor = db_conn.execute("PRAGMA table_info(continuity)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            "id", "session_name",
            "goal", "state_done", "state_now", "state_next",
            "key_learnings", "key_decisions",
            "snapshot_reason", "created_at"
        }

        for col in expected_columns:
            assert col in columns, f"Column '{col}' not found in continuity table. Found: {columns}"

    def test_continuity_snapshot_reason_check_constraint(self, db_conn):
        """Snapshot_reason column should only accept valid values."""
        valid_reasons = ["phase_complete", "session_end", "milestone", "manual"]

        # Valid reasons should work
        for reason in valid_reasons:
            db_conn.execute(
                "INSERT INTO continuity (id, session_name, snapshot_reason) VALUES (?, 'test', ?)",
                (f"test_{reason}", reason)
            )

        # Invalid reason should fail
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO continuity (id, session_name, snapshot_reason) VALUES ('invalid', 'test', 'INVALID')"
            )


class TestQueriesTable:
    """Test the queries table schema."""

    @pytest.fixture
    def db_conn(self):
        """Create an in-memory database with the schema loaded."""
        schema_sql = SCHEMA_PATH.read_text()
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)
        yield conn
        conn.close()

    def test_queries_columns(self, db_conn):
        """Queries table should have all expected columns."""
        cursor = db_conn.execute("PRAGMA table_info(queries)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            "id", "question", "answer",
            "handoffs_matched", "plans_matched", "continuity_matched", "braintrust_sessions",
            "was_helpful", "created_at"
        }

        for col in expected_columns:
            assert col in columns, f"Column '{col}' not found in queries table. Found: {columns}"

#!/usr/bin/env python3
"""
Tests for context_graph_query.py - Context Graph query functionality.

TDD: Tests written before implementation.
"""

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest import TestCase, main

# Add scripts to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestQueryFunctions(TestCase):
    """Test query functions with in-memory database."""

    @classmethod
    def setUpClass(cls):
        """Create test database with sample data."""
        cls.conn = sqlite3.connect(":memory:")

        # Load schema
        schema_path = Path(__file__).parent.parent / "scripts" / "context_graph_schema.sql"
        cls.conn.executescript(schema_path.read_text())

        # Insert test handoffs
        cls.conn.execute("""
            INSERT INTO handoffs (id, session_name, task_number, file_path, task_summary,
                                  what_worked, what_failed, key_decisions, files_modified, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "handoff001", "auth-session", 1, "thoughts/handoffs/auth/task-01.md",
            "Implemented OAuth2 authentication flow with JWT tokens",
            "Used passport.js for OAuth, worked well with middleware",
            "First tried session cookies but had CORS issues",
            "Chose JWT over sessions for stateless auth",
            '["src/auth/oauth.ts", "src/middleware/jwt.ts"]',
            "SUCCEEDED"
        ))

        cls.conn.execute("""
            INSERT INTO handoffs (id, session_name, task_number, file_path, task_summary,
                                  what_worked, what_failed, key_decisions, files_modified, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "handoff002", "api-session", 2, "thoughts/handoffs/api/task-02.md",
            "Built REST API endpoints for user management",
            "Express routing with TypeScript worked great",
            "WebSocket integration failed, needed different approach",
            "REST over GraphQL for simplicity",
            '["src/api/users.ts", "src/routes/index.ts"]',
            "PARTIAL_PLUS"
        ))

        cls.conn.execute("""
            INSERT INTO handoffs (id, session_name, task_number, file_path, task_summary,
                                  what_worked, what_failed, key_decisions, files_modified, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "handoff003", "failed-session", 3, "thoughts/handoffs/failed/task-03.md",
            "Attempted database migration but encountered issues",
            "", "Migration scripts corrupted existing data",
            "Rollback and manual recovery needed",
            '["migrations/001.sql"]',
            "FAILED"
        ))

        # Insert test plans
        cls.conn.execute("""
            INSERT INTO plans (id, title, file_path, overview, approach, phases, constraints)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "plan001", "Authentication System Design",
            "thoughts/shared/plans/2024-01-01-auth.md",
            "Design OAuth2 + JWT authentication system",
            "Use passport.js with custom strategies",
            '[{"name": "phase_1", "content": "Setup OAuth providers"}]',
            "No third-party auth services"
        ))

        # Insert test continuity
        cls.conn.execute("""
            INSERT INTO continuity (id, session_name, goal, state_done, state_now, state_next,
                                    key_learnings, key_decisions, snapshot_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "cont001", "auth-session",
            "Implement secure authentication for the API",
            '["Phase 1: OAuth setup", "Phase 2: JWT integration"]',
            "Phase 3: Testing",
            "Phase 4: Documentation",
            "JWT refresh tokens prevent session hijacking",
            "Use httpOnly cookies for token storage",
            "phase_complete"
        ))

        # Insert test past query
        cls.conn.execute("""
            INSERT INTO queries (id, question, answer, handoffs_matched, plans_matched,
                                 continuity_matched, was_helpful)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "query001", "How do I implement OAuth?",
            "See handoff auth-session/task-01 for OAuth implementation",
            '["handoff001"]', '["plan001"]', '["cont001"]', True
        ))

        cls.conn.commit()

        # Rebuild FTS5 indexes
        cls.conn.execute("INSERT INTO handoffs_fts(handoffs_fts) VALUES('rebuild')")
        cls.conn.execute("INSERT INTO plans_fts(plans_fts) VALUES('rebuild')")
        cls.conn.execute("INSERT INTO continuity_fts(continuity_fts) VALUES('rebuild')")
        cls.conn.execute("INSERT INTO queries_fts(queries_fts) VALUES('rebuild')")
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_import_query_functions(self):
        """Test that query functions can be imported."""
        from context_graph_query import (
            search_handoffs, search_plans, search_continuity,
            search_past_queries, format_results, save_query
        )
        self.assertTrue(callable(search_handoffs))
        self.assertTrue(callable(search_plans))
        self.assertTrue(callable(search_continuity))
        self.assertTrue(callable(search_past_queries))
        self.assertTrue(callable(format_results))
        self.assertTrue(callable(save_query))

    def test_search_handoffs_basic(self):
        """Test basic handoff search returns results."""
        from context_graph_query import search_handoffs
        results = search_handoffs(self.conn, "authentication OAuth")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "handoff001")

    def test_search_handoffs_by_outcome(self):
        """Test filtering handoffs by outcome."""
        from context_graph_query import search_handoffs
        succeeded = search_handoffs(self.conn, "authentication", outcome="SUCCEEDED")
        self.assertEqual(len(succeeded), 1)
        self.assertEqual(succeeded[0]["outcome"], "SUCCEEDED")

        failed = search_handoffs(self.conn, "database migration", outcome="FAILED")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["outcome"], "FAILED")

    def test_search_handoffs_limit(self):
        """Test limit parameter works."""
        from context_graph_query import search_handoffs
        # Insert more handoffs with matching terms
        self.conn.execute("""
            INSERT INTO handoffs (id, session_name, task_number, file_path, task_summary,
                                  what_worked, what_failed, key_decisions, files_modified, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "handoff004", "api-session-2", 4, "thoughts/handoffs/api2/task-04.md",
            "More API endpoint work",
            "API testing framework", "", "Use supertest",
            '["tests/api.test.ts"]', "SUCCEEDED"
        ))
        self.conn.commit()
        self.conn.execute("INSERT INTO handoffs_fts(handoffs_fts) VALUES('rebuild')")

        results = search_handoffs(self.conn, "API", limit=1)
        self.assertEqual(len(results), 1)

    def test_search_handoffs_returns_all_fields(self):
        """Test that handoff search returns all expected fields."""
        from context_graph_query import search_handoffs
        results = search_handoffs(self.conn, "OAuth")
        self.assertGreater(len(results), 0)
        result = results[0]

        expected_fields = ["id", "session_name", "task_number", "task_summary",
                          "what_worked", "what_failed", "key_decisions",
                          "outcome", "file_path", "created_at", "score"]
        for field in expected_fields:
            self.assertIn(field, result, f"Missing field: {field}")

    def test_search_plans_basic(self):
        """Test basic plan search."""
        from context_graph_query import search_plans
        results = search_plans(self.conn, "authentication OAuth")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "plan001")

    def test_search_plans_returns_fields(self):
        """Test plan search returns expected fields."""
        from context_graph_query import search_plans
        results = search_plans(self.conn, "authentication")
        self.assertGreater(len(results), 0)
        result = results[0]

        expected_fields = ["id", "title", "overview", "approach", "file_path", "created_at", "score"]
        for field in expected_fields:
            self.assertIn(field, result, f"Missing field: {field}")

    def test_search_continuity_basic(self):
        """Test basic continuity search."""
        from context_graph_query import search_continuity
        results = search_continuity(self.conn, "authentication JWT")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "cont001")

    def test_search_continuity_returns_fields(self):
        """Test continuity search returns expected fields."""
        from context_graph_query import search_continuity
        results = search_continuity(self.conn, "authentication")
        self.assertGreater(len(results), 0)
        result = results[0]

        expected_fields = ["id", "session_name", "goal", "key_learnings",
                          "key_decisions", "state_now", "created_at", "score"]
        for field in expected_fields:
            self.assertIn(field, result, f"Missing field: {field}")

    def test_search_past_queries(self):
        """Test searching past queries."""
        from context_graph_query import search_past_queries
        results = search_past_queries(self.conn, "OAuth implement")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "query001")

    def test_search_past_queries_returns_fields(self):
        """Test past query search returns expected fields."""
        from context_graph_query import search_past_queries
        results = search_past_queries(self.conn, "OAuth")
        self.assertGreater(len(results), 0)
        result = results[0]

        expected_fields = ["id", "question", "answer", "was_helpful", "created_at", "score"]
        for field in expected_fields:
            self.assertIn(field, result, f"Missing field: {field}")

    def test_search_no_results(self):
        """Test search with no matching results."""
        from context_graph_query import search_handoffs
        results = search_handoffs(self.conn, "xyz123nonexistent")
        self.assertEqual(len(results), 0)


class TestFormatResults(TestCase):
    """Test result formatting."""

    def test_format_empty_results(self):
        """Test formatting when no results found."""
        from context_graph_query import format_results
        output = format_results({})
        self.assertIn("No relevant precedent found", output)

    def test_format_handoffs_with_outcome_icons(self):
        """Test handoff formatting includes outcome icons."""
        from context_graph_query import format_results
        results = {
            "handoffs": [{
                "id": "h1",
                "session_name": "test",
                "task_number": 1,
                "task_summary": "Test task",
                "what_worked": "Everything",
                "what_failed": "",
                "outcome": "SUCCEEDED",
                "file_path": "test.md"
            }]
        }
        output = format_results(results)
        self.assertIn("Relevant Handoffs", output)
        self.assertIn("test/task-1", output)

    def test_format_plans(self):
        """Test plan formatting."""
        from context_graph_query import format_results
        results = {
            "plans": [{
                "id": "p1",
                "title": "Test Plan",
                "overview": "Test overview",
                "file_path": "plan.md"
            }]
        }
        output = format_results(results)
        self.assertIn("Relevant Plans", output)
        self.assertIn("Test Plan", output)

    def test_format_continuity(self):
        """Test continuity formatting."""
        from context_graph_query import format_results
        results = {
            "continuity": [{
                "id": "c1",
                "session_name": "test-session",
                "goal": "Test goal",
                "key_learnings": "Important learning"
            }]
        }
        output = format_results(results)
        self.assertIn("Related Sessions", output)
        self.assertIn("test-session", output)

    def test_format_past_queries(self):
        """Test past query formatting."""
        from context_graph_query import format_results
        results = {
            "past_queries": [{
                "id": "q1",
                "question": "How to do X?",
                "answer": "Do Y instead"
            }]
        }
        output = format_results(results)
        self.assertIn("Previously Asked", output)


class TestSaveQuery(TestCase):
    """Test query saving for compound learning."""

    def setUp(self):
        """Create test database."""
        self.conn = sqlite3.connect(":memory:")
        schema_path = Path(__file__).parent.parent / "scripts" / "context_graph_schema.sql"
        self.conn.executescript(schema_path.read_text())

    def tearDown(self):
        self.conn.close()

    def test_save_query(self):
        """Test saving a query."""
        from context_graph_query import save_query
        matches = {
            "handoffs": [{"id": "h1"}],
            "plans": [{"id": "p1"}],
            "continuity": []
        }
        save_query(self.conn, "test question", "test answer", matches)

        # Verify saved
        cursor = self.conn.execute("SELECT * FROM queries")
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)

    def test_save_query_stores_matches(self):
        """Test that matched IDs are stored as JSON."""
        from context_graph_query import save_query
        matches = {
            "handoffs": [{"id": "h1"}, {"id": "h2"}],
            "plans": [{"id": "p1"}],
            "continuity": [{"id": "c1"}]
        }
        save_query(self.conn, "test question", "test answer", matches)

        cursor = self.conn.execute(
            "SELECT handoffs_matched, plans_matched, continuity_matched FROM queries"
        )
        row = cursor.fetchone()
        self.assertEqual(json.loads(row[0]), ["h1", "h2"])
        self.assertEqual(json.loads(row[1]), ["p1"])
        self.assertEqual(json.loads(row[2]), ["c1"])


class TestCLI(TestCase):
    """Test CLI interface."""

    def test_help(self):
        """Test --help works."""
        result = subprocess.run(
            [sys.executable, "scripts/context_graph_query.py", "--help"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Search the Context Graph", result.stdout)

    def test_db_not_found(self):
        """Test graceful error when database not found."""
        result = subprocess.run(
            [sys.executable, "scripts/context_graph_query.py",
             "test query", "--db", "/nonexistent/path.db"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent
        )
        # Should not crash, should print helpful message
        self.assertIn("Database not found", result.stdout)

    def test_json_output(self):
        """Test --json output flag."""
        # First ensure we have a database
        db_path = Path(__file__).parent.parent / ".claude" / "cache" / "context-graph" / "context.db"
        if not db_path.exists():
            self.skipTest("Database not available for CLI test")

        result = subprocess.run(
            [sys.executable, "scripts/context_graph_query.py",
             "test", "--json"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent
        )
        # Should output valid JSON
        try:
            json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail("Output is not valid JSON")

    def test_type_filter(self):
        """Test --type filter."""
        db_path = Path(__file__).parent.parent / ".claude" / "cache" / "context-graph" / "context.db"
        if not db_path.exists():
            self.skipTest("Database not available for CLI test")

        result = subprocess.run(
            [sys.executable, "scripts/context_graph_query.py",
             "test", "--type", "handoffs", "--json"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent
        )
        self.assertEqual(result.returncode, 0)


class TestFTS5Ranking(TestCase):
    """Test FTS5 BM25 ranking behavior."""

    @classmethod
    def setUpClass(cls):
        """Create test database with documents for ranking tests."""
        cls.conn = sqlite3.connect(":memory:")
        schema_path = Path(__file__).parent.parent / "scripts" / "context_graph_schema.sql"
        cls.conn.executescript(schema_path.read_text())

        # Insert documents with varying relevance
        # High relevance: multiple mentions in important fields
        cls.conn.execute("""
            INSERT INTO handoffs (id, session_name, task_number, file_path, task_summary,
                                  what_worked, what_failed, key_decisions, files_modified, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "high_rel", "test", 1, "test1.md",
            "WebSocket real-time WebSocket communication",  # Multiple mentions in high-weight field
            "WebSocket library worked great",
            "", "Chose WebSocket over polling",
            '[]', "SUCCEEDED"
        ))

        # Low relevance: single mention in low-weight field
        cls.conn.execute("""
            INSERT INTO handoffs (id, session_name, task_number, file_path, task_summary,
                                  what_worked, what_failed, key_decisions, files_modified, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "low_rel", "test", 2, "test2.md",
            "Some other task about databases",
            "", "", "WebSocket mentioned once",  # Single mention in lower-weight field
            '[]', "SUCCEEDED"
        ))

        cls.conn.commit()
        cls.conn.execute("INSERT INTO handoffs_fts(handoffs_fts) VALUES('rebuild')")
        cls.conn.execute(
            "INSERT OR REPLACE INTO handoffs_fts(handoffs_fts, rank) VALUES('rank', 'bm25(10.0, 5.0, 3.0, 3.0, 1.0)')"
        )
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_ranking_order(self):
        """Test that more relevant documents rank higher."""
        from context_graph_query import search_handoffs
        results = search_handoffs(self.conn, "WebSocket")

        self.assertEqual(len(results), 2)
        # High relevance should come first (lower/more negative BM25 score = better match)
        self.assertEqual(results[0]["id"], "high_rel")
        self.assertEqual(results[1]["id"], "low_rel")


if __name__ == "__main__":
    main()

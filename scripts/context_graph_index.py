#!/usr/bin/env python3
"""
USAGE: context_graph_index.py [--handoffs] [--plans] [--continuity] [--all] [--file PATH] [--db PATH]

Index handoffs, plans, and continuity ledgers into the Context Graph database.

Examples:
    # Index all handoffs
    uv run python scripts/context_graph_index.py --handoffs

    # Index everything
    uv run python scripts/context_graph_index.py --all

    # Index a single handoff file (fast, for hooks)
    uv run python scripts/context_graph_index.py --file thoughts/handoffs/session/task-01.md

    # Use custom database path
    uv run python scripts/context_graph_index.py --all --db /path/to/context.db
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_db_path(custom_path: Optional[str] = None) -> Path:
    """Get database path, creating directory if needed."""
    if custom_path:
        path = Path(custom_path)
    else:
        path = Path(".claude/cache/context-graph/context.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize database with schema."""
    conn = sqlite3.connect(db_path)
    schema_path = Path(__file__).parent / "context_graph_schema.sql"
    if schema_path.exists():
        conn.executescript(schema_path.read_text())
    return conn


def parse_handoff(file_path: Path) -> dict:
    """Parse a handoff markdown file into structured data."""
    content = file_path.read_text()

    # Extract frontmatter if present
    frontmatter = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    frontmatter[key.strip()] = value.strip()
            content = parts[2]

    # Extract h2 sections
    sections = {}
    current_section = None
    current_content = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line[3:].strip().lower().replace(" ", "_")
            current_content = []
        elif current_section:
            current_content.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_content).strip()

    # Extract h3 subsections (for Post-Mortem nested sections)
    subsections = {}
    current_subsection = None
    current_subcontent = []

    for line in content.split("\n"):
        if line.startswith("### "):
            if current_subsection:
                subsections[current_subsection] = "\n".join(current_subcontent).strip()
            current_subsection = line[4:].strip().lower().replace(" ", "_")
            current_subcontent = []
        elif line.startswith("## "):
            # End subsection at next h2
            if current_subsection:
                subsections[current_subsection] = "\n".join(current_subcontent).strip()
            current_subsection = None
            current_subcontent = []
        elif current_subsection:
            current_subcontent.append(line)

    if current_subsection:
        subsections[current_subsection] = "\n".join(current_subcontent).strip()

    # Merge subsections into sections (h3 overrides h2 if same name)
    sections.update(subsections)

    # Generate ID from file path
    file_id = hashlib.md5(str(file_path).encode()).hexdigest()[:12]

    # Extract session name from path (thoughts/handoffs/<session>/task-XX.md)
    parts = file_path.parts
    session_name = ""
    if "handoffs" in parts:
        idx = parts.index("handoffs")
        if idx + 1 < len(parts):
            session_name = parts[idx + 1]

    # Extract task number
    task_match = re.search(r"task-(\d+)", file_path.stem)
    task_number = int(task_match.group(1)) if task_match else None

    # Map status values to canonical outcome values
    status = frontmatter.get("status", "UNKNOWN").upper()
    outcome_map = {
        "SUCCESS": "SUCCEEDED",
        "SUCCEEDED": "SUCCEEDED",
        "PARTIAL": "PARTIAL_PLUS",
        "PARTIAL_PLUS": "PARTIAL_PLUS",
        "PARTIAL_MINUS": "PARTIAL_MINUS",
        "FAILED": "FAILED",
        "FAILURE": "FAILED",
        "UNKNOWN": "UNKNOWN",
    }
    outcome = outcome_map.get(status, "UNKNOWN")

    return {
        "id": file_id,
        "session_name": session_name,
        "task_number": task_number,
        "file_path": str(file_path),
        "task_summary": sections.get("what_was_done", sections.get("summary", ""))[:500],
        "what_worked": sections.get("what_worked", ""),
        "what_failed": sections.get("what_failed", ""),
        "key_decisions": sections.get("key_decisions", sections.get("decisions", "")),
        "files_modified": json.dumps(extract_files(sections.get("files_modified", ""))),
        "outcome": outcome,
        # Braintrust trace links
        "root_span_id": frontmatter.get("root_span_id", ""),
        "turn_span_id": frontmatter.get("turn_span_id", ""),
        "session_id": frontmatter.get("session_id", ""),
        "braintrust_session_id": frontmatter.get("braintrust_session_id", ""),
        "created_at": frontmatter.get("date", datetime.now().isoformat()),
    }


def extract_files(content: str) -> list:
    """Extract file paths from markdown content."""
    files = []
    for line in content.split("\n"):
        # Match common patterns like "- `path/to/file.py`" or "- `path/to/file.py:123`"
        # Group 1 captures path up to extension, Group 2 captures optional :line-range
        matches = re.findall(r"`([^`]+\.[a-z]+)(:[^`]*)?`", line)
        files.extend([m[0] for m in matches])  # Only take the path, not line range
        # Match **File**: format
        matches = re.findall(r"\*\*File\*\*:\s*`?([^\s`]+)`?", line)
        files.extend(matches)
    return files


def index_handoffs(conn: sqlite3.Connection, base_path: Path = Path("thoughts/handoffs")):
    """Index all handoffs into the database."""
    if not base_path.exists():
        print(f"Handoffs directory not found: {base_path}")
        return 0

    count = 0
    for handoff_file in base_path.rglob("*.md"):
        try:
            data = parse_handoff(handoff_file)
            conn.execute("""
                INSERT OR REPLACE INTO handoffs
                (id, session_name, task_number, file_path, task_summary, what_worked,
                 what_failed, key_decisions, files_modified, outcome,
                 root_span_id, turn_span_id, session_id, braintrust_session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["id"], data["session_name"], data["task_number"], data["file_path"],
                data["task_summary"], data["what_worked"], data["what_failed"],
                data["key_decisions"], data["files_modified"], data["outcome"],
                data["root_span_id"], data["turn_span_id"], data["session_id"],
                data["braintrust_session_id"], data["created_at"]
            ))
            count += 1
        except Exception as e:
            print(f"Error indexing {handoff_file}: {e}")

    conn.commit()
    print(f"Indexed {count} handoffs")
    return count


def parse_plan(file_path: Path) -> dict:
    """Parse a plan markdown file into structured data."""
    content = file_path.read_text()

    # Generate ID
    file_id = hashlib.md5(str(file_path).encode()).hexdigest()[:12]

    # Extract title from first H1
    title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else file_path.stem

    # Extract sections
    sections = {}
    current_section = None
    current_content = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line[3:].strip().lower().replace(" ", "_")
            current_content = []
        elif current_section:
            current_content.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_content).strip()

    # Extract phases
    phases = []
    for key in sections:
        if key.startswith("phase_"):
            phases.append({"name": key, "content": sections[key][:500]})

    return {
        "id": file_id,
        "title": title,
        "file_path": str(file_path),
        "overview": sections.get("overview", "")[:1000],
        "approach": sections.get("implementation_approach", sections.get("approach", ""))[:1000],
        "phases": json.dumps(phases),
        "constraints": sections.get("what_we're_not_doing", sections.get("constraints", "")),
    }


def index_plans(conn: sqlite3.Connection, base_path: Path = Path("thoughts/shared/plans")):
    """Index all plans into the database."""
    if not base_path.exists():
        print(f"Plans directory not found: {base_path}")
        return 0

    count = 0
    for plan_file in base_path.glob("*.md"):
        try:
            data = parse_plan(plan_file)
            conn.execute("""
                INSERT OR REPLACE INTO plans
                (id, title, file_path, overview, approach, phases, constraints)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data["id"], data["title"], data["file_path"],
                data["overview"], data["approach"], data["phases"], data["constraints"]
            ))
            count += 1
        except Exception as e:
            print(f"Error indexing {plan_file}: {e}")

    conn.commit()
    print(f"Indexed {count} plans")
    return count


def parse_continuity(file_path: Path) -> dict:
    """Parse a continuity ledger into structured data."""
    content = file_path.read_text()

    # Generate ID
    file_id = hashlib.md5(str(file_path).encode()).hexdigest()[:12]

    # Extract session name from filename (CONTINUITY_CLAUDE-<session>.md)
    session_match = re.search(r"CONTINUITY_CLAUDE-(.+)\.md", file_path.name)
    session_name = session_match.group(1) if session_match else file_path.stem

    # Extract sections
    sections = {}
    current_section = None
    current_content = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line[3:].strip().lower().replace(" ", "_")
            current_content = []
        elif current_section:
            current_content.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_content).strip()

    # Parse state section
    state = sections.get("state", "")
    state_done = []
    state_now = ""
    state_next = ""

    for line in state.split("\n"):
        if "[x]" in line.lower():
            state_done.append(line.strip())
        elif "[->]" in line or "now:" in line.lower():
            state_now = line.strip()
        elif "[ ]" in line or "next:" in line.lower():
            state_next = line.strip()

    return {
        "id": file_id,
        "session_name": session_name,
        "goal": sections.get("goal", "")[:500],
        "state_done": json.dumps(state_done),
        "state_now": state_now,
        "state_next": state_next,
        "key_learnings": sections.get("key_learnings", sections.get("key_learnings_(this_session)", "")),
        "key_decisions": sections.get("key_decisions", ""),
        "snapshot_reason": "manual",
    }


def index_continuity(conn: sqlite3.Connection, base_path: Path = Path(".")):
    """Index all continuity ledgers into the database."""
    count = 0
    for ledger_file in base_path.glob("CONTINUITY_CLAUDE-*.md"):
        try:
            data = parse_continuity(ledger_file)
            conn.execute("""
                INSERT OR REPLACE INTO continuity
                (id, session_name, goal, state_done, state_now, state_next,
                 key_learnings, key_decisions, snapshot_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["id"], data["session_name"], data["goal"],
                data["state_done"], data["state_now"], data["state_next"],
                data["key_learnings"], data["key_decisions"], data["snapshot_reason"]
            ))
            count += 1
        except Exception as e:
            print(f"Error indexing {ledger_file}: {e}")

    conn.commit()
    print(f"Indexed {count} continuity ledgers")
    return count


def index_single_file(conn: sqlite3.Connection, file_path: Path) -> bool:
    """Index a single file based on its location/type.

    Returns True if indexed successfully, False otherwise.
    """
    file_path = Path(file_path).resolve()

    # Determine file type based on path
    path_str = str(file_path)

    if "handoffs" in path_str and file_path.suffix == ".md":
        try:
            data = parse_handoff(file_path)
            conn.execute("""
                INSERT OR REPLACE INTO handoffs
                (id, session_name, task_number, file_path, task_summary, what_worked,
                 what_failed, key_decisions, files_modified, outcome,
                 root_span_id, turn_span_id, session_id, braintrust_session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["id"], data["session_name"], data["task_number"], data["file_path"],
                data["task_summary"], data["what_worked"], data["what_failed"],
                data["key_decisions"], data["files_modified"], data["outcome"],
                data["root_span_id"], data["turn_span_id"], data["session_id"],
                data["braintrust_session_id"], data["created_at"]
            ))
            conn.commit()
            print(f"Indexed handoff: {file_path.name}")
            return True
        except Exception as e:
            print(f"Error indexing handoff {file_path}: {e}")
            return False

    elif "plans" in path_str and file_path.suffix == ".md":
        try:
            data = parse_plan(file_path)
            conn.execute("""
                INSERT OR REPLACE INTO plans
                (id, title, file_path, overview, approach, phases, constraints)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data["id"], data["title"], data["file_path"],
                data["overview"], data["approach"], data["phases"], data["constraints"]
            ))
            conn.commit()
            print(f"Indexed plan: {file_path.name}")
            return True
        except Exception as e:
            print(f"Error indexing plan {file_path}: {e}")
            return False

    elif file_path.name.startswith("CONTINUITY_CLAUDE-"):
        try:
            data = parse_continuity(file_path)
            conn.execute("""
                INSERT OR REPLACE INTO continuity
                (id, session_name, goal, state_done, state_now, state_next,
                 key_learnings, key_decisions, snapshot_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["id"], data["session_name"], data["goal"],
                data["state_done"], data["state_now"], data["state_next"],
                data["key_learnings"], data["key_decisions"], data["snapshot_reason"]
            ))
            conn.commit()
            print(f"Indexed continuity: {file_path.name}")
            return True
        except Exception as e:
            print(f"Error indexing continuity {file_path}: {e}")
            return False

    else:
        print(f"Unknown file type, skipping: {file_path}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Index context graph artifacts")
    parser.add_argument("--handoffs", action="store_true", help="Index handoffs")
    parser.add_argument("--plans", action="store_true", help="Index plans")
    parser.add_argument("--continuity", action="store_true", help="Index continuity ledgers")
    parser.add_argument("--all", action="store_true", help="Index everything")
    parser.add_argument("--file", type=str, help="Index a single file (fast, for hooks)")
    parser.add_argument("--db", type=str, help="Custom database path")

    args = parser.parse_args()

    # Handle single file indexing (fast path for hooks)
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"File not found: {file_path}")
            return

        db_path = get_db_path(args.db)
        conn = init_db(db_path)
        success = index_single_file(conn, file_path)
        conn.close()
        return 0 if success else 1

    if not any([args.handoffs, args.plans, args.continuity, args.all]):
        parser.print_help()
        return

    db_path = get_db_path(args.db)
    conn = init_db(db_path)

    print(f"Using database: {db_path}")

    if args.all or args.handoffs:
        index_handoffs(conn)

    if args.all or args.plans:
        index_plans(conn)

    if args.all or args.continuity:
        index_continuity(conn)

    # After bulk indexing, rebuild FTS5 indexes and optimize
    print("Rebuilding FTS5 indexes...")
    conn.execute("INSERT INTO handoffs_fts(handoffs_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO plans_fts(plans_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO continuity_fts(continuity_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO queries_fts(queries_fts) VALUES('rebuild')")

    # Configure BM25 column weights
    conn.execute("INSERT OR REPLACE INTO handoffs_fts(handoffs_fts, rank) VALUES('rank', 'bm25(10.0, 5.0, 3.0, 3.0, 1.0)')")
    conn.execute("INSERT OR REPLACE INTO plans_fts(plans_fts, rank) VALUES('rank', 'bm25(10.0, 5.0, 3.0, 3.0, 1.0)')")

    # Optimize for query performance
    print("Optimizing indexes...")
    conn.execute("INSERT INTO handoffs_fts(handoffs_fts) VALUES('optimize')")
    conn.execute("INSERT INTO plans_fts(plans_fts) VALUES('optimize')")
    conn.execute("INSERT INTO continuity_fts(continuity_fts) VALUES('optimize')")
    conn.execute("INSERT INTO queries_fts(queries_fts) VALUES('optimize')")
    conn.commit()

    conn.close()
    print("Done!")


if __name__ == "__main__":
    main()

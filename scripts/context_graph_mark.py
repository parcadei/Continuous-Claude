#!/usr/bin/env python3
"""
USAGE: context_graph_mark.py --handoff ID --outcome OUTCOME [--notes NOTES] [--db PATH]

Mark a handoff with user outcome in the Context Graph database.

This updates the handoff's outcome and sets confidence to HIGH to indicate
user verification. Used for improving future session recommendations.

Examples:
    # Mark a handoff as succeeded
    uv run python scripts/context_graph_mark.py --handoff abc123 --outcome SUCCEEDED

    # Mark with additional notes
    uv run python scripts/context_graph_mark.py --handoff abc123 --outcome PARTIAL_PLUS --notes "Almost done, one test failing"

    # List all handoffs to find IDs
    sqlite3 .claude/cache/context-graph/context.db "SELECT id, session_name, task_number, task_summary FROM handoffs ORDER BY indexed_at DESC LIMIT 10"
"""

import argparse
import sqlite3
from pathlib import Path
from typing import Optional


def get_db_path(custom_path: Optional[str] = None) -> Path:
    """Get database path."""
    if custom_path:
        return Path(custom_path)
    return Path(".claude/cache/context-graph/context.db")


def main():
    parser = argparse.ArgumentParser(
        description="Mark handoff outcome in Context Graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Mark handoff as succeeded
  %(prog)s --handoff abc123 --outcome SUCCEEDED

  # Mark with notes
  %(prog)s --handoff abc123 --outcome PARTIAL_PLUS --notes "One test failing"

  # Find handoff IDs
  sqlite3 .claude/cache/context-graph/context.db \\
    "SELECT id, session_name, task_number, task_summary FROM handoffs \\
     ORDER BY indexed_at DESC LIMIT 10"
"""
    )
    parser.add_argument("--handoff", required=True, help="Handoff ID to mark")
    parser.add_argument(
        "--outcome",
        required=True,
        choices=["SUCCEEDED", "PARTIAL_PLUS", "PARTIAL_MINUS", "FAILED"],
        help="Outcome of the handoff"
    )
    parser.add_argument("--notes", default="", help="Optional notes about the outcome")
    parser.add_argument("--db", type=str, help="Custom database path")

    args = parser.parse_args()

    db_path = get_db_path(args.db)

    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        print("Run: uv run python scripts/context_graph_index.py --all")
        return 1

    conn = sqlite3.connect(db_path)

    # First, check if handoff exists
    cursor = conn.execute(
        "SELECT id, session_name, task_number, task_summary FROM handoffs WHERE id = ?",
        (args.handoff,)
    )
    handoff = cursor.fetchone()

    if not handoff:
        print(f"Error: Handoff not found: {args.handoff}")
        print("\nAvailable handoffs:")
        cursor = conn.execute(
            "SELECT id, session_name, task_number, task_summary FROM handoffs ORDER BY indexed_at DESC LIMIT 10"
        )
        for row in cursor.fetchall():
            print(f"  {row[0]}: {row[1]}/task-{row[2]} - {row[3][:60]}...")
        conn.close()
        return 1

    # Update the handoff
    cursor = conn.execute(
        "UPDATE handoffs SET outcome = ?, outcome_notes = ?, confidence = 'HIGH' WHERE id = ?",
        (args.outcome, args.notes, args.handoff)
    )

    if cursor.rowcount == 0:
        print(f"Error: Failed to update handoff: {args.handoff}")
        conn.close()
        return 1

    conn.commit()

    # Show confirmation
    print(f"✓ Marked handoff {args.handoff} as {args.outcome}")
    print(f"  Session: {handoff[1]}")
    if handoff[2]:
        print(f"  Task: task-{handoff[2]}")
    print(f"  Summary: {handoff[3][:80]}...")
    if args.notes:
        print(f"  Notes: {args.notes}")
    print(f"  Confidence: HIGH (user-verified)")

    conn.close()
    return 0


if __name__ == "__main__":
    exit(main())

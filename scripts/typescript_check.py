#!/usr/bin/env python3
"""
TypeScript Pre-flight Check Script

Runs tsc + qlty on a TypeScript file to catch errors immediately after edit.
Designed to be called from PostToolUse hook.

Usage:
    python scripts/typescript_check.py --file src/index.ts
    python scripts/typescript_check.py --file src/index.ts --project-root /path/to/project
    python scripts/typescript_check.py --file src/index.ts --tsc-only
    python scripts/typescript_check.py --file src/index.ts --qlty-only

Returns:
    JSON with errors from both tsc and qlty, or empty if clean.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TypedDict


class CheckResult(TypedDict):
    has_errors: bool
    tsc_errors: list[str]
    qlty_errors: list[str]
    summary: str


def find_project_root(file_path: str) -> Path | None:
    """Find the nearest directory with tsconfig.json or package.json."""
    current = Path(file_path).resolve().parent

    while current != current.parent:
        if (current / "tsconfig.json").exists():
            return current
        if (current / "package.json").exists():
            return current
        current = current.parent

    return None


def run_tsc(project_root: Path, file_path: str) -> list[str]:
    """Run tsc --noEmit and extract errors for the specific file."""
    errors = []

    try:
        # Check if tsconfig exists
        tsconfig = project_root / "tsconfig.json"
        if not tsconfig.exists():
            return []

        # Run tsc with incremental for speed
        cmd = ["npx", "tsc", "--noEmit", "--pretty", "false"]

        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse errors - filter to just the edited file
        file_basename = Path(file_path).name
        for line in result.stdout.split('\n'):
            # tsc error format: file(line,col): error TS1234: message
            if file_basename in line and 'error TS' in line:
                errors.append(line.strip())
            # Also catch generic errors
            elif 'error TS' in line and not errors:
                errors.append(line.strip())

        # Limit to first 10 errors
        return errors[:10]

    except subprocess.TimeoutExpired:
        return ["tsc timed out after 30s"]
    except FileNotFoundError:
        return ["tsc not found - is TypeScript installed?"]
    except Exception as e:
        return [f"tsc error: {str(e)}"]


def run_qlty(project_root: Path, file_path: str) -> list[str]:
    """Run qlty check on the specific file."""
    errors = []

    try:
        # Check if qlty is available
        result = subprocess.run(
            ["which", "qlty"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return []  # qlty not installed, skip silently

        # Run qlty on the specific file
        cmd = ["qlty", "check", "--no-progress", file_path]

        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse qlty output - it outputs JSON-ish or plain text
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and ('error' in line.lower() or 'warning' in line.lower()):
                errors.append(line)

        # Limit to first 10
        return errors[:10]

    except subprocess.TimeoutExpired:
        return ["qlty timed out after 30s"]
    except Exception as e:
        return [f"qlty error: {str(e)}"]


def main():
    parser = argparse.ArgumentParser(description="TypeScript pre-flight check")
    parser.add_argument("--file", required=True, help="File path to check")
    parser.add_argument("--project-root", help="Project root (auto-detected if not provided)")
    parser.add_argument("--tsc-only", action="store_true", help="Only run tsc")
    parser.add_argument("--qlty-only", action="store_true", help="Only run qlty")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    file_path = args.file

    # Find project root
    if args.project_root:
        project_root = Path(args.project_root)
    else:
        project_root = find_project_root(file_path)
        if not project_root:
            print("Could not find project root (no tsconfig.json or package.json)")
            sys.exit(1)

    # Run checks
    tsc_errors = []
    qlty_errors = []

    if not args.qlty_only:
        tsc_errors = run_tsc(project_root, file_path)

    if not args.tsc_only:
        qlty_errors = run_qlty(project_root, file_path)

    # Build result
    has_errors = bool(tsc_errors or qlty_errors)

    # Build summary
    summary_parts = []
    if tsc_errors:
        summary_parts.append(f"{len(tsc_errors)} type error(s)")
    if qlty_errors:
        summary_parts.append(f"{len(qlty_errors)} lint issue(s)")

    summary = ", ".join(summary_parts) if summary_parts else "No errors"

    result: CheckResult = {
        "has_errors": has_errors,
        "tsc_errors": tsc_errors,
        "qlty_errors": qlty_errors,
        "summary": summary
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        # Human-readable output
        if not has_errors:
            print("✅ No TypeScript or lint errors")
        else:
            print(f"⚠️ {summary}")
            if tsc_errors:
                print("\n--- TypeScript Errors ---")
                for err in tsc_errors:
                    print(f"  {err}")
            if qlty_errors:
                print("\n--- Lint Issues ---")
                for err in qlty_errors:
                    print(f"  {err}")

    # Exit with error code if issues found
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()

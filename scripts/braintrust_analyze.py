#!/usr/bin/env python3
"""Braintrust Session Analysis - Query and analyze Claude Code sessions.

Use Cases:
- Analyze recent session(s) for patterns and issues
- Find loop detection (repeated tool calls)
- Agent/skill usage statistics
- Token consumption trends
- Session replay for debugging
- Extract learnings from sessions

Usage:
  # Analyze last session
  uv run python -m runtime.harness scripts/braintrust_analyze.py \
    --last-session

  # Analyze last N sessions
  uv run python -m runtime.harness scripts/braintrust_analyze.py \
    --sessions 5

  # Get agent usage stats
  uv run python -m runtime.harness scripts/braintrust_analyze.py \
    --agent-stats

  # Detect loops in recent sessions
  uv run python -m runtime.harness scripts/braintrust_analyze.py \
    --detect-loops

  # Replay a specific session (shows actual content)
  uv run python -m runtime.harness scripts/braintrust_analyze.py \
    --replay <session-id>

  # Extract learnings from a session
  uv run python -m runtime.harness scripts/braintrust_analyze.py \
    --learn --session-id <session-id>

  # Extract learnings from last session
  uv run python -m runtime.harness scripts/braintrust_analyze.py \
    --learn

  # Weekly summary
  uv run python -m runtime.harness scripts/braintrust_analyze.py \
    --weekly-summary

Requires: BRAINTRUST_API_KEY in environment
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Note: We use direct LLM-as-judge API calls via Braintrust proxy
# instead of autoevals library for more control over prompts


# Phase 1: Metrics collection only (no warnings)
# Quantitative checks removed as false positives:
# - high_tokens: Sessions naturally grow to 200K before compact
# - loop_count: Total tool count isn't meaningful
# - slow_agent: Long duration can be valid (e.g., RepoPrompt analysis)
# Phase 2 will add qualitative scoring via autoevals


def load_api_key() -> str:
    """Load API key from environment or .env file."""
    # Try loading from .env files
    for path in [Path.home() / ".claude", Path.cwd(), *Path.cwd().parents]:
        env_file = path / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith("BRAINTRUST_API_KEY="):
                        key = line.strip().split("=", 1)[1].strip('"\'')
                        os.environ["BRAINTRUST_API_KEY"] = key
                        break

    api_key = os.environ.get("BRAINTRUST_API_KEY")
    if not api_key:
        print("Error: BRAINTRUST_API_KEY not found.", file=sys.stderr)
        print("Set it in ~/.claude/.env or project .env", file=sys.stderr)
        sys.exit(1)
    return api_key


def days_ago(n: int = 7) -> str:
    """Get ISO date string for N days ago. BTQL doesn't support INTERVAL."""
    return (datetime.utcnow() - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_project_id(project_name: str, api_key: str) -> str:
    """Get project ID from name."""
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(
        "https://api.braintrust.dev/v1/project",
        headers=headers,
        params={"project_name": project_name},
    )
    if resp.status_code == 200:
        projects = resp.json().get("objects", [])
        if projects:
            return projects[0]["id"]

    # Try listing all projects and matching by name
    resp = requests.get("https://api.braintrust.dev/v1/project", headers=headers)
    if resp.status_code == 200:
        projects = resp.json().get("objects", [])
        for p in projects:
            if p.get("name", "").lower() == project_name.lower():
                return p["id"]

    print(f"Error: Project '{project_name}' not found", file=sys.stderr)
    sys.exit(1)


def run_sql(project_id: str, query: str, api_key: str) -> list[dict]:
    """Execute SQL query against Braintrust logs."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Replace "FROM logs" with the project-scoped source
    full_query = re.sub(
        r"\bFROM\s+logs\b", f"FROM project_logs('{project_id}')", query, flags=re.IGNORECASE
    )

    resp = requests.post(
        "https://api.braintrust.dev/btql",
        headers=headers,
        json={"query": full_query, "fmt": "json"},
    )

    if resp.status_code == 200:
        return resp.json().get("data", [])
    else:
        print(f"SQL Error: {resp.status_code} - {resp.text}", file=sys.stderr)
        return []


def get_hierarchical_context(root_span_id: str) -> dict:
    """Get handoff + ledger from Context Graph for a session.

    Returns dict with 'handoff' and 'ledger' keys (may be None).
    """
    import subprocess
    import json as json_mod

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    query_script = Path(project_dir) / "scripts" / "context_graph_query.py"

    if not query_script.exists():
        return {"handoff": None, "ledger": None}

    try:
        result = subprocess.run(
            ["uv", "run", "python", str(query_script),
             "--by-span-id", root_span_id, "--with-content", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_dir
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json_mod.loads(result.stdout)
            return {
                "handoff": data if data else None,
                "ledger": data.get("ledger") if data else None
            }
    except Exception as e:
        print(f"  Context Graph query failed: {e}")

    return {"handoff": None, "ledger": None}


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}m"
    else:
        return f"{seconds/3600:.1f}h"


def format_tokens(tokens: int) -> str:
    """Format token count with K suffix."""
    if tokens >= 1000:
        return f"{tokens/1000:.1f}K"
    return str(tokens)


def analyze_last_session(project_id: str, api_key: str):
    """Analyze the most recent session."""
    # Get session info
    sessions = run_sql(project_id, """
        SELECT
            root_span_id as session_id,
            MIN(created) as started,
            MAX(created) as ended,
            COUNT(*) as span_count
        FROM logs
        GROUP BY root_span_id
        ORDER BY started DESC
        LIMIT 1
    """, api_key)

    if not sessions:
        print("No sessions found")
        return

    session = sessions[0]
    session_id = session["session_id"]

    # Get tool breakdown
    tools = run_sql(project_id, f"""
        SELECT
            COALESCE(metadata['tool_name'], span_attributes['name']) as tool,
            COUNT(*) as count
        FROM logs
        WHERE root_span_id = '{session_id}'
          AND span_attributes['type'] = 'tool'
        GROUP BY 1
        ORDER BY count DESC
        LIMIT 10
    """, api_key)

    # Get agent usage
    agents = run_sql(project_id, f"""
        SELECT
            metadata['agent_type'] as agent,
            COUNT(*) as count
        FROM logs
        WHERE root_span_id = '{session_id}'
          AND metadata['agent_type'] IS NOT NULL
        GROUP BY 1
        ORDER BY count DESC
    """, api_key)

    # Get skill usage
    skills = run_sql(project_id, f"""
        SELECT
            metadata['skill_name'] as skill,
            COUNT(*) as count
        FROM logs
        WHERE root_span_id = '{session_id}'
          AND metadata['skill_name'] IS NOT NULL
        GROUP BY 1
        ORDER BY count DESC
    """, api_key)

    # Get token estimate (from LLM spans if available)
    tokens_result = run_sql(project_id, f"""
        SELECT
            SUM(COALESCE(metrics['tokens'], 0)) as total_tokens
        FROM logs
        WHERE root_span_id = '{session_id}'
    """, api_key)

    # Output
    print(f"## Session Analysis")
    print(f"**ID:** `{session_id[:8]}...`")
    print(f"**Started:** {session['started']}")
    print(f"**Spans:** {session['span_count']}")

    total_tokens = tokens_result[0].get("total_tokens", 0) if tokens_result else 0
    if total_tokens:
        print(f"**Tokens:** {format_tokens(int(total_tokens))}")

    if tools:
        print(f"\n### Tool Usage")
        for t in tools[:7]:
            print(f"- {t['tool']}: {t['count']}")

    if agents:
        print(f"\n### Agents Spawned")
        for a in agents:
            print(f"- {a['agent']}: {a['count']}")

    if skills:
        print(f"\n### Skills Activated")
        for s in skills:
            print(f"- {s['skill']}: {s['count']}")


def list_sessions(project_id: str, api_key: str, limit: int = 5):
    """List recent sessions with summary."""
    sessions = run_sql(project_id, f"""
        SELECT
            root_span_id as session_id,
            MIN(created) as started,
            MAX(created) as ended,
            COUNT(*) as span_count,
            COUNT(*) FILTER (WHERE span_attributes['type'] = 'tool') as tool_count
        FROM logs
        GROUP BY root_span_id
        ORDER BY started DESC
        LIMIT {limit}
    """, api_key)

    if not sessions:
        print("No sessions found")
        return

    print(f"## Recent Sessions ({len(sessions)})")
    print()
    for s in sessions:
        print(f"**{s['session_id'][:12]}...**")
        print(f"  Started: {s['started']}")
        print(f"  Spans: {s['span_count']} | Tools: {s['tool_count']}")
        print()


def agent_stats(project_id: str, api_key: str):
    """Show agent usage statistics."""
    since = days_ago()
    stats = run_sql(project_id, f"""
        SELECT
            metadata['agent_type'] as agent,
            COUNT(*) as runs,
            COUNT(DISTINCT root_span_id) as sessions
        FROM logs
        WHERE metadata['agent_type'] IS NOT NULL
          AND created > '{since}'
        GROUP BY 1
        ORDER BY runs DESC
    """, api_key)

    if not stats:
        print("No agent data found (last 7 days)")
        print("Note: Agent tagging was just added - data will appear after new sessions")
        return

    print("## Agent Usage (Last 7 Days)")
    print()
    print("| Agent | Runs | Sessions |")
    print("|-------|------|----------|")
    for s in stats:
        print(f"| {s['agent']} | {s['runs']} | {s['sessions']} |")


def skill_stats(project_id: str, api_key: str):
    """Show skill usage statistics."""
    since = days_ago()
    stats = run_sql(project_id, f"""
        SELECT
            metadata['skill_name'] as skill,
            COUNT(*) as activations,
            COUNT(DISTINCT root_span_id) as sessions
        FROM logs
        WHERE metadata['skill_name'] IS NOT NULL
          AND created > '{since}'
        GROUP BY 1
        ORDER BY activations DESC
    """, api_key)

    if not stats:
        print("No skill data found (last 7 days)")
        print("Note: Skill tagging was just added - data will appear after new sessions")
        return

    print("## Skill Usage (Last 7 Days)")
    print()
    print("| Skill | Activations | Sessions |")
    print("|-------|-------------|----------|")
    for s in stats:
        print(f"| {s['skill']} | {s['activations']} | {s['sessions']} |")


def detect_loops(project_id: str, api_key: str):
    """Find sessions with repeated tool calls (potential loops)."""
    since = days_ago()
    # BTQL doesn't support HAVING, so fetch all and filter client-side
    all_counts = run_sql(project_id, f"""
        SELECT
            root_span_id as session_id,
            COALESCE(metadata['tool_name'], span_attributes['name']) as tool,
            COUNT(*) as call_count,
            MIN(created) as first_call,
            MAX(created) as last_call
        FROM logs
        WHERE span_attributes['type'] = 'tool'
          AND created > '{since}'
        GROUP BY root_span_id, 2
        ORDER BY call_count DESC
        LIMIT 100
    """, api_key)

    # Client-side filter: only keep tools called >5 times
    loops = [l for l in (all_counts or []) if l.get('call_count', 0) > 5][:15]

    if not loops:
        print("No potential loops detected (>5 same tool calls)")
        return

    print("## Potential Loops (>5 repeated tool calls)")
    print()
    for l in loops:
        print(f"**Session:** `{l['session_id'][:8]}...`")
        print(f"  Tool: {l['tool']} ({l['call_count']}x)")
        print()


def replay_session(project_id: str, api_key: str, session_id: str):
    """Replay a specific session showing the sequence of actions with actual content."""
    # Handle partial session ID
    if len(session_id) < 36:
        # Find full session ID
        sessions = run_sql(project_id, f"""
            SELECT DISTINCT root_span_id
            FROM logs
            WHERE root_span_id LIKE '{session_id}%'
            LIMIT 1
        """, api_key)
        if sessions:
            session_id = sessions[0]["root_span_id"]
        else:
            print(f"Session not found: {session_id}")
            return

    spans = run_sql(project_id, f"""
        SELECT
            created,
            input,
            output,
            span_attributes,
            metadata
        FROM logs
        WHERE root_span_id = '{session_id}'
        ORDER BY created
        LIMIT 200
    """, api_key)

    if not spans:
        print(f"No data for session: {session_id}")
        return

    print(f"## Session Replay: `{session_id[:12]}...`")
    print()

    def truncate(text: str, max_len: int = 200) -> str:
        """Truncate text to max length."""
        if not text:
            return ""
        text = str(text).strip()
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."

    for i, s in enumerate(spans, 1):
        span_attrs = s.get("span_attributes") or {}
        metadata = s.get("metadata") or {}
        span_type = span_attrs.get("type", "unknown")
        span_name = span_attrs.get("name", "unknown")

        # Determine prefix
        prefix = ""
        if metadata.get("agent_type"):
            prefix = f"[Agent:{metadata['agent_type']}] "
        elif metadata.get("skill_name"):
            prefix = f"[Skill:{metadata['skill_name']}] "
        elif metadata.get("tool_name"):
            prefix = f"[Tool:{metadata['tool_name']}] "

        # Show span header
        print(f"{i:3}. {prefix}**{span_name}** ({span_type})")

        # Show content based on span type
        if span_type == "llm":
            # LLM spans have both input and output
            input_text = s.get("input")
            output_text = s.get("output")
            if input_text:
                print(f"     Input: {truncate(input_text)}")
            if output_text:
                print(f"     Output: {truncate(output_text)}")
        elif span_type == "task":
            # Task spans have user message in input
            input_text = s.get("input")
            if input_text:
                print(f"     Message: {truncate(input_text)}")
        elif span_type == "tool":
            # Tool spans may have input/output
            input_text = s.get("input")
            output_text = s.get("output")
            if input_text:
                print(f"     Input: {truncate(input_text)}")
            if output_text:
                print(f"     Output: {truncate(output_text)}")

        # Show tool calls from metadata if present
        if metadata.get("tool_calls"):
            tool_calls = metadata["tool_calls"]
            if isinstance(tool_calls, list):
                print(f"     Tool calls: {len(tool_calls)}")
                for tc in tool_calls[:3]:  # Show first 3
                    if isinstance(tc, dict):
                        print(f"       - {tc.get('name', 'unknown')}")

        print()  # Blank line between spans


def weekly_summary(project_id: str, api_key: str):
    """Generate a weekly analysis summary."""
    since = days_ago()
    # BTQL doesn't support DATE(), so we fetch raw data and aggregate client-side
    raw_data = run_sql(project_id, f"""
        SELECT
            created,
            root_span_id,
            span_attributes['type'] as span_type
        FROM logs
        WHERE created > '{since}'
        ORDER BY created
        LIMIT 1000
    """, api_key)

    # Client-side aggregation by day
    from collections import defaultdict
    daily_stats = defaultdict(lambda: {"sessions": set(), "tool_calls": 0})
    for row in raw_data or []:
        day = row.get("created", "")[:10]  # Extract YYYY-MM-DD
        daily_stats[day]["sessions"].add(row.get("root_span_id"))
        if row.get("span_type") == "tool":
            daily_stats[day]["tool_calls"] += 1

    daily = [{"day": k, "sessions": len(v["sessions"]), "tool_calls": v["tool_calls"]}
             for k, v in sorted(daily_stats.items())]

    # Top tools
    top_tools = run_sql(project_id, f"""
        SELECT
            COALESCE(metadata['tool_name'], span_attributes['name']) as tool,
            COUNT(*) as count
        FROM logs
        WHERE span_attributes['type'] = 'tool'
          AND created > '{since}'
        GROUP BY 1
        ORDER BY count DESC
        LIMIT 5
    """, api_key)

    print("## Weekly Summary")
    print()
    print("### Daily Activity")
    print("| Day | Sessions | Tool Calls |")
    print("|-----|----------|------------|")
    for d in daily:
        print(f"| {d['day']} | {d['sessions']} | {d['tool_calls']} |")

    if top_tools:
        print()
        print("### Top Tools")
        for t in top_tools:
            print(f"- {t['tool']}: {t['count']}")


def token_trends(project_id: str, api_key: str):
    """Show token usage trends."""
    since = days_ago()
    # BTQL doesn't support DATE(), so we fetch raw data and aggregate client-side
    raw_data = run_sql(project_id, f"""
        SELECT
            created,
            root_span_id,
            metrics['tokens'] as tokens
        FROM logs
        WHERE created > '{since}'
        ORDER BY created
        LIMIT 1000
    """, api_key)

    # Client-side aggregation by day
    from collections import defaultdict
    daily_stats = defaultdict(lambda: {"sessions": set(), "tokens": 0})
    for row in raw_data or []:
        day = row.get("created", "")[:10]  # Extract YYYY-MM-DD
        daily_stats[day]["sessions"].add(row.get("root_span_id"))
        daily_stats[day]["tokens"] += row.get("tokens") or 0

    trends = [{"day": k, "sessions": len(v["sessions"]), "total_tokens": v["tokens"]}
              for k, v in sorted(daily_stats.items())]

    if not trends:
        print("No token data found")
        return

    print("## Token Trends (Last 7 Days)")
    print()
    print("| Day | Sessions | Tokens |")
    print("|-----|----------|--------|")
    for t in trends:
        tokens = int(t.get("total_tokens", 0) or 0)
        print(f"| {t['day']} | {t['sessions']} | {format_tokens(tokens)} |")


def get_session_metrics(project_id: str, api_key: str, session_id: str) -> dict:
    """Gather all metrics for a session."""
    # Token count
    tokens = run_sql(project_id, f"""
        SELECT SUM(COALESCE(metrics['tokens'], 0)) as total
        FROM logs
        WHERE root_span_id = '{session_id}'
    """, api_key)

    # Tool counts - extract tool name, handling different formats
    tools = run_sql(project_id, f"""
        SELECT
            COALESCE(metadata['tool_name'], span_attributes['name']) as tool,
            COUNT(*) as count
        FROM logs
        WHERE root_span_id = '{session_id}'
          AND span_attributes['type'] = 'tool'
        GROUP BY 1
    """, api_key)

    # Span count for session
    spans = run_sql(project_id, f"""
        SELECT COUNT(*) as total
        FROM logs
        WHERE root_span_id = '{session_id}'
    """, api_key)

    # Agent durations (count-based for now, timing TODO)
    agents = run_sql(project_id, f"""
        SELECT metadata['agent_type'] as agent, COUNT(*) as count
        FROM logs
        WHERE root_span_id = '{session_id}'
          AND metadata['agent_type'] IS NOT NULL
        GROUP BY 1
    """, api_key)

    # Build tool counts (metadata['tool_name'] already has correct names)
    tool_counts = {t["tool"]: t["count"] for t in tools if t.get("tool")} if tools else {}

    return {
        "total_tokens": int(tokens[0]["total"] or 0) if tokens else 0,
        "span_count": int(spans[0]["total"] or 0) if spans else 0,
        "tool_calls": sum(tool_counts.values()),
        "tool_counts": tool_counts,
        "duration_seconds": 0,  # TODO: calculate from span timing
        "agent_durations": {a["agent"]: 0 for a in agents} if agents else {}
    }


# ============================================================================
# Phase 2: Qualitative Scoring with LLM-as-Judge
# ============================================================================

DEFAULT_MODEL = "gpt-5.2-2025-12-11"  # Via Braintrust proxy custom provider "Eval"

# Critique-focused LLM-as-Judge prompts (binary pass/fail + gaps list)
# Based on research: "Scores are theater, critiques are the product"

PLAN_JUDGE_PROMPT = """You are a critical reviewer of implementation plans. Find what's MISSING or WRONG.

**Plan Document:**
{content}

**Required Elements (P0 - must have):**
1. Clear phases with logical order
2. Success criteria for verification
3. Specific files/functions to modify
4. Dependencies between steps

**Find These Issues:**
- Missing requirements that should be specified
- Vague phases without concrete actions
- No verification criteria
- Missing file/function specifics
- Unclear dependencies

**Output JSON only:**
{{
  "verdict": "PASS" | "FAIL",
  "gaps": [
    {{
      "type": "MISSING_REQUIREMENT|VAGUE_PHASE|NO_VERIFICATION|UNCLEAR",
      "severity": "P0|P1|P2",
      "description": "what's missing",
      "fix_suggestion": "how to fix"
    }}
  ],
  "summary": "1 sentence assessment"
}}

A plan FAILS if any P0 element is missing. Focus on gaps only."""

# NOTE: Handoff scoring removed - no feedback loop (created at session end)
# Keep for reference but don't use in auto-insights
HANDOFF_JUDGE_PROMPT = """You are reviewing a handoff document for completeness.

**Handoff Document:**
{content}

**Find what's MISSING (do not list what's present):**
1. Task status unclear?
2. Recent changes without file:line references?
3. Missing learnings/key decisions?
4. No actionable next steps?

**Output JSON only:**
{{
  "verdict": "PASS" | "FAIL",
  "gaps": [
    {{
      "element": "TASK_STATUS|CHANGES|LEARNINGS|NEXT_STEPS",
      "description": "what's missing",
      "severity": "P0|P1|P2"
    }}
  ],
  "summary": "1 sentence assessment"
}}

PASS if all essential elements present. FAIL if any P0 gaps."""

# New: Implementation review prompt (compares plan vs code diff)
REVIEW_JUDGE_PROMPT = """You are verifying whether code changes implement a plan correctly.

**PLAN (Source of Truth):**
{plan_content}

**CODE CHANGES:**
{diff_content}

**SESSION CONTEXT (what tools were used):**
{session_summary}

**Instructions:**
1. List requirements from the PLAN
2. For each, find evidence in CODE CHANGES
3. Mark as: DONE | PARTIAL | MISSING | DIVERGED

**Focus on GAPS only - do not list correctly implemented items.**

**Output JSON only:**
{{
  "verdict": "PASS" | "FAIL",
  "requirements_checked": {{"total": N, "done": N, "gaps": N}},
  "gaps": [
    {{
      "id": "GAP-001",
      "requirement": "what was expected",
      "status": "MISSING|PARTIAL|DIVERGED",
      "evidence": "file:line or 'not found'",
      "severity": "P0|P1|P2",
      "fix_action": "specific fix"
    }}
  ],
  "scope_creep": ["items in diff but not in plan"],
  "summary": "1 sentence verdict"
}}

PASS if all P0 requirements DONE. FAIL if any P0 gap exists."""


async def llm_judge(prompt: str, **format_args) -> dict:
    """Run LLM-as-judge evaluation with custom prompt.

    Returns dict with verdict (PASS/FAIL), gaps list, and summary.
    """
    import aiohttp

    api_key = os.environ.get("BRAINTRUST_API_KEY", "")
    if not api_key:
        return {"verdict": None, "error": "BRAINTRUST_API_KEY not set"}

    # Format prompt with provided args
    # GPT-5.2 has 400k context, no truncation needed
    truncated_args = format_args
    full_prompt = prompt.format(**truncated_args)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.braintrust.dev/v1/proxy/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": DEFAULT_MODEL,
                    "messages": [{"role": "user", "content": full_prompt}],
                    "temperature": 0,
                    "max_tokens": 16000  # GPT-5.2 has 128k max, uses reasoning tokens internally
                }
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    return {"verdict": None, "error": f"API error: {error[:100]}"}
                data = await resp.json()
                if not data.get("choices"):
                    return {"verdict": None, "error": f"No choices in response: {data}"}
                response_text = data["choices"][0]["message"]["content"] or ""
                finish_reason = data["choices"][0].get("finish_reason", "")
                usage = data.get("usage", {})
                if not response_text and finish_reason == "length":
                    return {"verdict": None, "error": f"Empty response (finish_reason: length). Usage: {usage}. Model may need higher max_tokens."}

                # Parse JSON from response (handle nested objects)
                import re
                # Strip markdown code fences if present (```json ... ``` or ```JSON ... ```)
                if '```' in response_text:
                    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response_text, re.IGNORECASE)
                    if fence_match:
                        response_text = fence_match.group(1).strip()
                # Find JSON object, handling nested braces
                json_start = response_text.find('{')
                if json_start >= 0:
                    brace_count = 0
                    json_end = json_start
                    for i, c in enumerate(response_text[json_start:], json_start):
                        if c == '{':
                            brace_count += 1
                        elif c == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                json_end = i + 1
                                break
                    try:
                        result = json.loads(response_text[json_start:json_end])
                        return {
                            "verdict": result.get("verdict"),
                            "gaps": result.get("gaps", []),
                            "summary": result.get("summary", ""),
                            "raw": result
                        }
                    except json.JSONDecodeError:
                        pass
                return {"verdict": None, "error": f"Could not parse judge response: {response_text[:200]}"}
    except Exception as e:
        return {"verdict": None, "error": str(e)[:100]}


async def score_plan(plan_content: str) -> dict:
    """Score plan quality using critique-focused LLM-as-judge.

    Returns verdict (PASS/FAIL) with gaps list instead of numeric score.
    """
    result = await llm_judge(PLAN_JUDGE_PROMPT, content=plan_content)
    result["scorer"] = "plan_quality"
    return result


async def review_implementation(plan_content: str, diff_content: str, session_summary: str) -> dict:
    """Review implementation by comparing plan (intent) vs code (reality).

    This is the key LLM-as-judge function - compares what was planned
    against what was actually implemented.
    """
    result = await llm_judge(
        REVIEW_JUDGE_PROMPT,
        plan_content=plan_content,
        diff_content=diff_content,
        session_summary=session_summary
    )
    result["scorer"] = "implementation_review"
    return result


# RAG-Enhanced LLM-as-Judge prompt (uses Context Graph precedent)
RAG_JUDGE_PROMPT = """You are reviewing a plan before implementation.

**Plan to evaluate:**
{plan_content}

**Similar past work that SUCCEEDED (learn from these):**
{succeeded_precedent}

**Similar past work that FAILED (avoid these patterns):**
{failed_precedent}

Based on the precedent from similar past work, evaluate this plan.

Respond in JSON:
{{
  "verdict": "PASS" or "FAIL",
  "gaps": [
    {{"requirement": "What's missing", "severity": "P0/P1", "evidence": "Based on similar failure in..."}}
  ],
  "insights": ["Patterns from past successes that apply here"],
  "summary": "One sentence assessment"
}}

PASS if plan addresses patterns that caused past failures.
FAIL if plan repeats mistakes from similar failed work."""


async def judge_plan_with_context(plan_content: str, db_path: str = None) -> dict:
    """RAG-enhanced plan judging using Context Graph precedent.

    Queries similar handoffs to provide contextual critique based on
    what SUCCEEDED and what FAILED in similar past work.
    """
    # Import context graph query functions
    import sqlite3
    scripts_dir = Path(__file__).parent
    sys.path.insert(0, str(scripts_dir))
    from context_graph_query import search_handoffs, get_db_path

    db = db_path or get_db_path()
    if not Path(db).exists():
        return {"verdict": None, "error": f"Context Graph not found: {db}"}

    conn = sqlite3.connect(db)

    # Extract goal/summary from plan for search
    # Look for first heading or Overview section
    goal_match = re.search(r'^#\s+(.+)$', plan_content, re.MULTILINE)
    overview_match = re.search(r'Overview[:\s]*\n(.+?)(?:\n\n|\n#)', plan_content, re.DOTALL)
    search_query = goal_match.group(1) if goal_match else ""
    if overview_match:
        search_query += " " + overview_match.group(1)[:200]

    if not search_query.strip():
        search_query = plan_content[:300]  # Fallback to first 300 chars

    # Query similar handoffs
    succeeded = search_handoffs(conn, search_query, outcome="SUCCEEDED", limit=3)
    failed = search_handoffs(conn, search_query, outcome="FAILED", limit=2)
    # Also check PARTIAL failures for cautionary patterns
    partial_minus = search_handoffs(conn, search_query, outcome="PARTIAL_MINUS", limit=1)
    failed.extend(partial_minus)

    conn.close()

    # Format precedent for prompt
    def format_precedent(handoffs: list) -> str:
        if not handoffs:
            return "(No similar past work found)"
        parts = []
        for h in handoffs:
            parts.append(f"**{h['session_name']}/task-{h['task_number']}**")
            parts.append(f"  Summary: {h['task_summary'][:150]}")
            if h.get('what_worked'):
                parts.append(f"  What worked: {h['what_worked'][:150]}")
            if h.get('what_failed'):
                parts.append(f"  What failed: {h['what_failed'][:150]}")
            if h.get('key_decisions'):
                parts.append(f"  Key decisions: {h['key_decisions'][:100]}")
            parts.append("")
        return "\n".join(parts)

    succeeded_precedent = format_precedent(succeeded)
    failed_precedent = format_precedent(failed)

    # Run LLM judge with context
    result = await llm_judge(
        RAG_JUDGE_PROMPT,
        plan_content=plan_content,
        succeeded_precedent=succeeded_precedent,
        failed_precedent=failed_precedent
    )
    result["scorer"] = "rag_enhanced_judge"
    result["precedent_found"] = {
        "succeeded": len(succeeded),
        "failed": len(failed)
    }
    return result


async def run_scorers(project_dir: str, session_id: str) -> list[dict]:
    """Run applicable scorers on session artifacts.

    Currently scores plans only (have feedback loop - can iterate before implementing).
    Handoff scoring removed (no feedback loop - created at session end).
    """
    scores = []
    today = datetime.now().strftime("%Y-%m-%d")

    # Score plans (useful - can iterate before implementing)
    plans_dir = Path(project_dir) / "thoughts" / "shared" / "plans"
    if plans_dir.exists():
        for plan_file in plans_dir.glob(f"{today}*.md"):
            content = plan_file.read_text()
            score = await score_plan(content)
            score["file"] = str(plan_file.relative_to(project_dir))
            scores.append(score)

    # NOTE: Handoff scoring intentionally removed
    # Reason: Handoffs are created at session end, so scoring them
    # has no feedback loop (can't iterate). This is "theater" scoring.
    # Instead, use /create_handoff skill which enforces structure upfront.

    return scores


async def run_implementation_review(project_dir: str, plan_path: str, session_id: str = None) -> dict:
    """Run implementation review comparing plan vs git diff vs session data.

    This is invoked by the review-agent, not auto-insights.
    """
    import subprocess

    # Read plan
    plan_file = Path(project_dir) / plan_path
    if not plan_file.exists():
        return {"error": f"Plan not found: {plan_path}"}
    plan_content = plan_file.read_text()

    # Get git diff
    try:
        diff_result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True
        )
        diff_content = diff_result.stdout or "(no uncommitted changes)"
    except Exception as e:
        diff_content = f"(could not get diff: {e})"

    # Get session summary if available
    session_summary = "Session data not provided"
    if session_id:
        # Could query Braintrust here for tool usage summary
        session_summary = f"Session {session_id[:8]} - see Braintrust for details"

    # Run the review
    result = await review_implementation(plan_content, diff_content, session_summary)
    result["plan_file"] = plan_path
    result["session_id"] = session_id

    return result




LEARN_JUDGE_PROMPT = """Analyze this Claude Code session trace. Extract learnings:

SESSION TRACE:
{formatted_trace}

Provide:
1. **What Worked** - Approaches that succeeded
2. **What Failed** - Approaches abandoned or blocked
3. **Key Decisions** - Important choices and rationale
4. **Patterns** - Reusable techniques

Be specific. Reference actual tool calls and outcomes.

Output in markdown format (not JSON)."""


async def learn_from_session(project_id: str, api_key: str, session_id: str | None = None):
    """Extract learnings from a session and save to .claude/cache/learnings/."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    learnings_dir = Path(project_dir) / ".claude" / "cache" / "learnings"
    learnings_dir.mkdir(parents=True, exist_ok=True)

    # Get session data (use provided ID or most recent)
    if not session_id:
        sessions = run_sql(project_id, """
            SELECT root_span_id as session_id
            FROM logs
            ORDER BY created DESC
            LIMIT 1
        """, api_key)
        if not sessions:
            print("No sessions found")
            return
        session_id = sessions[0]["session_id"]
    elif len(session_id) < 36:
        # Handle partial session ID
        sessions = run_sql(project_id, f"""
            SELECT DISTINCT root_span_id
            FROM logs
            WHERE root_span_id LIKE '{session_id}%'
            LIMIT 1
        """, api_key)
        if sessions:
            session_id = sessions[0]["root_span_id"]
        else:
            print(f"Session not found: {session_id}")
            return

    # Fetch full session trace (like fixed replay)
    spans = run_sql(project_id, f"""
        SELECT
            created,
            input,
            output,
            span_attributes,
            metadata
        FROM logs
        WHERE root_span_id = '{session_id}'
        ORDER BY created
        LIMIT 200
    """, api_key)

    if not spans:
        print(f"No data for session: {session_id}")
        return

    # Query Context Graph for handoff + ledger (hierarchical context)
    print(f"  Querying Context Graph for hierarchical context...")
    hier_ctx = get_hierarchical_context(session_id)
    handoff = hier_ctx.get("handoff")
    ledger = hier_ctx.get("ledger")

    if handoff:
        print(f"  Found handoff: {handoff.get('session_name')}")
    if ledger:
        print(f"  Found ledger: {ledger.get('session_name')}")

    # Build hierarchical context string
    hierarchical_lines = []

    # Priority 1: Handoff (Claude's synthesis of the session)
    if handoff and handoff.get("content"):
        hierarchical_lines.append("# Session Handoff (Claude's Summary)")
        hierarchical_lines.append("")
        hierarchical_lines.append(handoff["content"][:20000])  # Cap at 20KB
        hierarchical_lines.append("")
        hierarchical_lines.append("---")
        hierarchical_lines.append("")

    # Priority 2: Ledger (goal and context)
    if ledger and ledger.get("content"):
        hierarchical_lines.append("# Session Goal & Context (from Ledger)")
        hierarchical_lines.append("")
        # Extract just Goal and State sections to keep it focused
        ledger_content = ledger["content"]
        # Try to extract just the relevant sections
        goal_match = re.search(r'## Goal\n(.*?)(?=\n## |\Z)', ledger_content, re.DOTALL)
        state_match = re.search(r'## State\n(.*?)(?=\n## |\Z)', ledger_content, re.DOTALL)
        if goal_match:
            hierarchical_lines.append(f"## Goal\n{goal_match.group(1).strip()[:2000]}")
        if state_match:
            hierarchical_lines.append(f"\n## State\n{state_match.group(1).strip()[:3000]}")
        hierarchical_lines.append("")
        hierarchical_lines.append("---")
        hierarchical_lines.append("")

    hierarchical_context = "\n".join(hierarchical_lines)
    hierarchical_chars = len(hierarchical_context)
    print(f"  Hierarchical context: {hierarchical_chars:,} chars")

    # Format trace for LLM with dynamic budget
    trace_lines = []
    trace_lines.append(f"# Session Trace: {session_id}")
    trace_lines.append("")

    # Dynamic budget calculation (accounting for hierarchical context)
    # 272k tokens ≈ 800k chars (conservative 3 chars/token)
    TOTAL_CHARS = 800_000
    RESERVE_CHARS = 100_000  # prompt template + response headroom
    AVAILABLE_CHARS = TOTAL_CHARS - RESERVE_CHARS - hierarchical_chars
    MIN_PER_FIELD = 1500
    MAX_PER_FIELD = 8000

    # Estimate ~1.5 fields per span (some have input+output, some just input)
    span_count = len(spans)
    estimated_fields = int(span_count * 1.5)
    per_field_budget = AVAILABLE_CHARS // max(1, estimated_fields)
    per_field_budget = max(MIN_PER_FIELD, min(MAX_PER_FIELD, per_field_budget))

    def clean(text: str, max_len: int = per_field_budget) -> str:
        """Clean and truncate text for trace (dynamic budget based on span count)."""
        if not text:
            return ""
        text = str(text).strip()
        if len(text) > max_len:
            return text[:max_len] + f"... [truncated {len(text) - max_len} chars]"
        return text

    print(f"  Spans: {span_count}, budget: {per_field_budget} chars/field")

    for i, s in enumerate(spans, 1):
        span_attrs = s.get("span_attributes") or {}
        metadata = s.get("metadata") or {}
        span_type = span_attrs.get("type", "unknown")
        span_name = span_attrs.get("name", "unknown")

        # Determine prefix
        prefix = ""
        if metadata.get("agent_type"):
            prefix = f"[Agent:{metadata['agent_type']}] "
        elif metadata.get("skill_name"):
            prefix = f"[Skill:{metadata['skill_name']}] "
        elif metadata.get("tool_name"):
            prefix = f"[Tool:{metadata['tool_name']}] "

        trace_lines.append(f"## {i}. {prefix}{span_name} ({span_type})")

        # Add content based on span type
        if span_type == "llm":
            input_text = s.get("input")
            output_text = s.get("output")
            if input_text:
                trace_lines.append(f"**Input:** {clean(input_text)}")
            if output_text:
                trace_lines.append(f"**Output:** {clean(output_text)}")
        elif span_type == "task":
            input_text = s.get("input")
            if input_text:
                trace_lines.append(f"**Message:** {clean(input_text)}")
        elif span_type == "tool":
            input_text = s.get("input")
            output_text = s.get("output")
            if input_text:
                trace_lines.append(f"**Input:** {clean(input_text)}")
            if output_text:
                trace_lines.append(f"**Output:** {clean(output_text)}")

        trace_lines.append("")

    formatted_trace = "\n".join(trace_lines)

    # Combine hierarchical context + traces
    # Priority: Handoff (testimony) → Ledger (goal) → Traces (evidence)
    if hierarchical_context:
        full_session_context = hierarchical_context + "\n" + formatted_trace
    else:
        full_session_context = formatted_trace

    # Pass to LLM judge for learning extraction
    print(f"Extracting learnings from session {session_id}...")

    # Use llm_judge but with a learning extraction prompt
    import aiohttp

    bt_api_key = os.environ.get("BRAINTRUST_API_KEY", "")
    if not bt_api_key:
        print("Error: BRAINTRUST_API_KEY not set")
        return

    full_prompt = LEARN_JUDGE_PROMPT.format(formatted_trace=full_session_context)
    print(f"  Context: {len(full_session_context):,} chars (hierarchical: {hierarchical_chars:,}, traces: {len(formatted_trace):,})")
    print(f"  Prompt: {len(full_prompt):,} chars")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.braintrust.dev/v1/proxy/chat/completions",
                headers={"Authorization": f"Bearer {bt_api_key}", "Content-Type": "application/json"},
                json={
                    "model": DEFAULT_MODEL,
                    "messages": [{"role": "user", "content": full_prompt}],
                    "temperature": 0,
                    "max_tokens": 16000
                }
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    print(f"Error: API error: {error[:100]}")
                    return
                data = await resp.json()
                if not data.get("choices"):
                    print(f"Error: No choices in response")
                    return
                learnings_content = data["choices"][0]["message"]["content"] or ""

                if not learnings_content:
                    print("Error: Empty response from LLM")
                    return

                # Save to file
                date_str = datetime.now().strftime("%Y-%m-%d")
                filename = f"{date_str}_{session_id}.md"
                output_path = learnings_dir / filename

                with open(output_path, "w") as f:
                    f.write(f"# Learnings from Session {session_id}\n\n")
                    f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(learnings_content)

                print(f"Learnings saved to: {output_path}")
                print("\n" + learnings_content)

    except Exception as e:
        print(f"Error: {str(e)[:100]}")


def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Analyze Braintrust sessions")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--last-session", action="store_true",
                       help="Analyze the most recent session")
    group.add_argument("--sessions", type=int, metavar="N",
                       help="List last N sessions")
    group.add_argument("--agent-stats", action="store_true",
                       help="Show agent usage statistics")
    group.add_argument("--skill-stats", action="store_true",
                       help="Show skill usage statistics")
    group.add_argument("--detect-loops", action="store_true",
                       help="Find sessions with repeated tool calls")
    group.add_argument("--replay", metavar="SESSION_ID",
                       help="Replay a specific session")
    group.add_argument("--weekly-summary", action="store_true",
                       help="Generate weekly analysis summary")
    group.add_argument("--token-trends", action="store_true",
                       help="Show token usage trends")
    group.add_argument("--learn", action="store_true",
                       help="Extract learnings from session and save to .claude/cache/learnings/")
    group.add_argument("--review", metavar="PLAN_PATH",
                       help="Review implementation: compare plan vs git diff vs session")
    group.add_argument("--rag-judge", metavar="PLAN_PATH",
                       help="RAG-enhanced plan judging using Context Graph precedent")

    parser.add_argument("--project", default="agentica",
                        help="Braintrust project name (default: agentica)")
    parser.add_argument("--session-id", metavar="ID",
                        help="Specific session ID for --learn or --review")
    parser.add_argument("--score", action="store_true",
                        help="Enable qualitative scoring (uses LLM-as-judge)")

    # Handle being called via runtime.harness
    args_to_parse = [arg for arg in sys.argv[1:] if not arg.endswith(".py")]
    return parser.parse_args(args_to_parse)


def main():
    args = parse_args()
    api_key = load_api_key()
    project_id = get_project_id(args.project, api_key)

    if args.last_session:
        analyze_last_session(project_id, api_key)
    elif args.sessions:
        list_sessions(project_id, api_key, args.sessions)
    elif args.agent_stats:
        agent_stats(project_id, api_key)
    elif args.skill_stats:
        skill_stats(project_id, api_key)
    elif args.detect_loops:
        detect_loops(project_id, api_key)
    elif args.replay:
        replay_session(project_id, api_key, args.replay)
    elif args.weekly_summary:
        weekly_summary(project_id, api_key)
    elif args.token_trends:
        token_trends(project_id, api_key)
    elif args.learn:
        import asyncio
        asyncio.run(learn_from_session(project_id, api_key, args.session_id))
    elif args.review:
        import asyncio
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        result = asyncio.run(run_implementation_review(project_dir, args.review, args.session_id))

        # Print review results
        if result.get("error"):
            print(f"Error: {result['error']}")
            sys.exit(1)

        verdict = result.get("verdict", "UNKNOWN")
        gaps = result.get("gaps", [])
        p0_gaps = [g for g in gaps if g.get("severity") == "P0"]

        print(f"\n## Implementation Review")
        print(f"**Plan:** {result.get('plan_file', 'unknown')}")
        print(f"**Verdict:** {verdict}")
        print(f"**Gaps:** {len(gaps)} total ({len(p0_gaps)} blocking)")

        if result.get("summary"):
            print(f"\n**Summary:** {result['summary']}")

        if gaps:
            print(f"\n### Gaps Found")
            for g in gaps:
                sev = g.get("severity", "?")
                status = g.get("status", "?")
                req = g.get("requirement", "unknown")[:80]
                print(f"\n**[{sev}] {status}:** {req}")
                if g.get("evidence"):
                    print(f"  Evidence: {g['evidence']}")
                if g.get("fix_action"):
                    print(f"  Fix: {g['fix_action']}")

        if result.get("raw", {}).get("scope_creep"):
            print(f"\n### Scope Creep (in diff but not in plan)")
            for item in result["raw"]["scope_creep"]:
                print(f"  - {item}")

        if verdict == "FAIL":
            print(f"\n**Action Required:** Address {len(p0_gaps)} P0 gap(s) before proceeding")
            sys.exit(1)
        else:
            print(f"\n**Ready for:** Handoff creation")

    elif args.rag_judge:
        import asyncio
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        plan_file = Path(project_dir) / args.rag_judge
        if not plan_file.exists():
            print(f"Error: Plan not found: {args.rag_judge}")
            sys.exit(1)

        plan_content = plan_file.read_text()
        db_path = Path(project_dir) / ".claude" / "cache" / "context-graph" / "context.db"
        result = asyncio.run(judge_plan_with_context(plan_content, str(db_path)))

        # Print results
        if result.get("error"):
            print(f"Error: {result['error']}")
            sys.exit(1)

        verdict = result.get("verdict", "UNKNOWN")
        gaps = result.get("gaps", [])
        insights = result.get("raw", {}).get("insights", [])
        precedent = result.get("precedent_found", {})

        # Build output markdown
        output_lines = []
        output_lines.append("## RAG-Enhanced Plan Review")
        output_lines.append(f"**Plan:** {args.rag_judge}")
        output_lines.append(f"**Verdict:** {verdict}")
        output_lines.append(f"**Precedent used:** {precedent.get('succeeded', 0)} succeeded, {precedent.get('failed', 0)} failed")

        if result.get("summary"):
            output_lines.append(f"\n**Summary:** {result['summary']}")

        if insights:
            output_lines.append("\n### Insights from Past Successes")
            for insight in insights:
                output_lines.append(f"  - {insight}")

        if gaps:
            output_lines.append("\n### Gaps Found (based on past failures)")
            for g in gaps:
                sev = g.get("severity", "?")
                req = g.get("requirement", "unknown")[:80]
                output_lines.append(f"\n**[{sev}]:** {req}")
                if g.get("evidence"):
                    output_lines.append(f"  Evidence: {g['evidence']}")

        if verdict == "FAIL":
            output_lines.append("\n**Action:** Revise plan to address patterns from past failures")
        else:
            output_lines.append("\n**Ready for:** Implementation")

        # Print to stdout
        output_text = "\n" + "\n".join(output_lines)
        print(output_text)

        # Save to file
        reviews_dir = Path(project_dir) / ".claude" / "cache" / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        plan_basename = Path(args.rag_judge).stem
        output_filename = f"{timestamp}_{plan_basename}.md"
        output_path = reviews_dir / output_filename

        with open(output_path, "w") as f:
            f.write(output_text.strip() + "\n")

        print(f"\nReview saved to: {output_path}")

        if verdict == "FAIL":
            sys.exit(1)


if __name__ == "__main__":
    main()

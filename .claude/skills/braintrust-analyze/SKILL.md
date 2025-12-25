---
name: braintrust-analyze
description: Analyze Claude Code sessions via Braintrust
---

# Braintrust Analysis

Analyze your Claude Code sessions for patterns, issues, and insights using Braintrust tracing data.

## When to Use

- After completing a complex task (retrospective)
- When debugging why something failed
- Weekly review of productivity patterns
- Finding opportunities to create new skills
- Understanding token usage trends

## Commands

Run from the project directory:

```bash
# Analyze last session - summary with tool/agent/skill breakdown
uv run python -m runtime.harness scripts/braintrust_analyze.py --last-session

# List recent sessions
uv run python -m runtime.harness scripts/braintrust_analyze.py --sessions 5

# Agent usage statistics (last 7 days)
uv run python -m runtime.harness scripts/braintrust_analyze.py --agent-stats

# Skill usage statistics (last 7 days)
uv run python -m runtime.harness scripts/braintrust_analyze.py --skill-stats

# Detect loops - find repeated tool patterns (>5 same tool calls)
uv run python -m runtime.harness scripts/braintrust_analyze.py --detect-loops

# Replay specific session - show full sequence of actions
uv run python -m runtime.harness scripts/braintrust_analyze.py --replay <session-id>

# Weekly summary - daily activity breakdown
uv run python -m runtime.harness scripts/braintrust_analyze.py --weekly-summary

# Token trends - usage over time
uv run python -m runtime.harness scripts/braintrust_analyze.py --token-trends
```

## Options

- `--project NAME` - Braintrust project name (default: agentica)

## What You'll Learn

### Session Analysis
- Tool usage breakdown
- Agent spawns (plan-agent, debug-agent, etc.)
- Skill activations (/commit, /research, etc.)
- Token consumption estimates

### Loop Detection
Find sessions where the same tool was called repeatedly, which may indicate:
- Stuck in a search loop
- Inefficient approach
- Opportunity for better tooling

### Usage Patterns
- Which agents you use most
- Which skills get activated
- Daily/weekly activity trends

## Examples

### Quick Retrospective
```bash
# What happened in my last session?
uv run python -m runtime.harness scripts/braintrust_analyze.py --last-session
```

Output:
```
## Session Analysis
**ID:** `92940b91...`
**Started:** 2025-12-24T01:31:05Z
**Spans:** 14

### Tool Usage
- Read: 4
- Bash: 2
- Edit: 2
...
```

### Find Loops
```bash
uv run python -m runtime.harness scripts/braintrust_analyze.py --detect-loops
```

### Weekly Review
```bash
uv run python -m runtime.harness scripts/braintrust_analyze.py --weekly-summary
```

## Requirements

- BRAINTRUST_API_KEY in ~/.claude/.env or project .env
- Braintrust tracing enabled (via braintrust-claude-plugin)

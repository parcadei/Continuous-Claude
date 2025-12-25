---
name: onboard
description: Analyze brownfield codebase and create initial continuity ledger
---

# Onboard - Project Discovery & Ledger Creation

Analyze a brownfield codebase and create an initial continuity ledger.

## When to Use

- First time working in an existing project
- User says "onboard", "analyze this project", "get familiar with codebase"
- After running `init-project.sh` in a new project

## How to Use

**Spawn the onboard agent:**

Use the Task tool with `subagent_type: "general-purpose"` and this prompt:

```
Onboard me to this project.

Read and follow the instructions in .claude/agents/onboard.md exactly.

1. Check if thoughts/ledgers/ exists (if not, tell me to run init-project.sh)
2. Analyze the codebase using rp-cli if available, otherwise bash commands
3. Detect tech stack
4. Ask me about my goals using AskUserQuestion
5. Create a continuity ledger at thoughts/ledgers/CONTINUITY_CLAUDE-<project>.md

DO NOT use MCP tools. Only use: Bash, Read, Write, Glob, Grep, AskUserQuestion.
```

## Why an Agent?

The onboard process:
- Requires multiple exploration steps
- Should not pollute main context with codebase dumps
- Needs restricted tools to prevent MCP pollution
- Returns a clean summary + creates the ledger

## Output

- Continuity ledger created at `thoughts/ledgers/CONTINUITY_CLAUDE-<name>.md`
- User has clear starting context
- Ready to begin work with full project awareness

## Notes

- This skill is for BROWNFIELD projects (existing code)
- For greenfield, use `/create_plan` instead
- Ledger can be updated anytime with `/continuity_ledger`
- RepoPrompt requires the app running with MCP Server enabled

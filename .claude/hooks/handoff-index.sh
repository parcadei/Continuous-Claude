#!/bin/bash
# PostToolUse hook: Index handoffs and inject Braintrust IDs
# Matches: Write tool calls to thoughts/handoffs/**/*.md
set -e
cd "$CLAUDE_PROJECT_DIR/.claude/hooks"

# Check if we should use bundled version
if [ -f "dist/handoff-index.mjs" ]; then
  cat | node dist/handoff-index.mjs
else
  cat | npx tsx src/handoff-index.ts
fi

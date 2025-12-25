#!/bin/bash
set -e

# TypeScript Pre-flight Check Hook
# Runs after Edit/Write on .ts/.tsx files

# Use project hooks if available, otherwise global
if [ -f "$CLAUDE_PROJECT_DIR/.claude/hooks/dist/typescript-preflight.mjs" ]; then
    cd "$CLAUDE_PROJECT_DIR/.claude/hooks"
    cat | node dist/typescript-preflight.mjs
elif [ -f "$HOME/.claude/hooks/dist/typescript-preflight.mjs" ]; then
    cd "$HOME/.claude/hooks"
    cat | node dist/typescript-preflight.mjs
else
    # Fallback: just continue if hook not built
    echo '{"result":"continue"}'
fi

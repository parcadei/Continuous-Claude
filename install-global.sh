#!/bin/bash
# Install Continuous Claude globally to ~/.claude/
# This enables all features in any project, not just this repo.
#
# Usage: ./install-global.sh
#
# ⚠️  WARNING: This script REPLACES the following directories:
#   ~/.claude/skills/     - Replaced entirely
#   ~/.claude/agents/     - Replaced entirely
#   ~/.claude/rules/      - Replaced entirely
#   ~/.claude/hooks/      - Replaced entirely
#   ~/.claude/scripts/    - Files added/overwritten
#   ~/.claude/plugins/braintrust-tracing/ - Replaced
#   ~/.claude/settings.json - Replaced (backup created)
#
# ✓ Preserved:
#   ~/.claude/.env        - Not touched if exists
#   ~/.claude/cache/      - Not touched
#   ~/.claude/state/      - Not touched
#
# Safe to run multiple times - settings.json is backed up before overwrite.
# If you have custom skills/agents/rules, copy them to a safe location first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLOBAL_DIR="$HOME/.claude"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo ""
echo "┌─────────────────────────────────────────────────────────────┐"
echo "│  Continuous Claude - Global Installation                    │"
echo "└─────────────────────────────────────────────────────────────┘"
echo ""
echo "This will install to: $GLOBAL_DIR"
echo ""
echo "⚠️  WARNING: The following will be REPLACED:"
echo "   • ~/.claude/skills/     (all skills)"
echo "   • ~/.claude/agents/     (all agents)"
echo "   • ~/.claude/rules/      (all rules)"
echo "   • ~/.claude/hooks/      (all hooks)"
echo "   • ~/.claude/settings.json (backup created)"
echo ""
echo "✓ PRESERVED (not touched):"
echo "   • ~/.claude/.env"
echo "   • ~/.claude/cache/"
echo "   • ~/.claude/state/"
echo ""
echo "📦 A full backup will be created at ~/.claude-backup-<timestamp>"
echo ""

# Check for --yes flag to skip prompt
if [[ "${1:-}" != "--yes" && "${1:-}" != "-y" ]]; then
    read -p "Continue with installation? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
fi

echo ""
echo "Installing Continuous Claude to $GLOBAL_DIR..."
echo ""

# Create global dir if needed
mkdir -p "$GLOBAL_DIR"

# Full backup of existing .claude directory
BACKUP_DIR="$HOME/.claude-backup-$TIMESTAMP"
if [ -d "$GLOBAL_DIR" ] && [ "$(ls -A "$GLOBAL_DIR" 2>/dev/null)" ]; then
    echo "Creating full backup at $BACKUP_DIR..."
    cp -r "$GLOBAL_DIR" "$BACKUP_DIR"
    echo "Backup complete. To restore: rm -rf ~/.claude && mv $BACKUP_DIR ~/.claude"
    echo ""
fi

# Copy directories (overwrite)
echo "Copying skills..."
rm -rf "$GLOBAL_DIR/skills"
cp -r "$SCRIPT_DIR/.claude/skills" "$GLOBAL_DIR/skills"

echo "Copying agents..."
rm -rf "$GLOBAL_DIR/agents"
cp -r "$SCRIPT_DIR/.claude/agents" "$GLOBAL_DIR/agents"

echo "Copying rules..."
rm -rf "$GLOBAL_DIR/rules"
cp -r "$SCRIPT_DIR/.claude/rules" "$GLOBAL_DIR/rules"

echo "Copying hooks..."
rm -rf "$GLOBAL_DIR/hooks"
cp -r "$SCRIPT_DIR/.claude/hooks" "$GLOBAL_DIR/hooks"
# Remove source files (only dist needed for runtime)
rm -rf "$GLOBAL_DIR/hooks/src" "$GLOBAL_DIR/hooks/node_modules" "$GLOBAL_DIR/hooks/*.ts" 2>/dev/null || true

echo "Copying scripts..."
mkdir -p "$GLOBAL_DIR/scripts"
cp "$SCRIPT_DIR/scripts/"*.py "$GLOBAL_DIR/scripts/" 2>/dev/null || true
cp "$SCRIPT_DIR/.claude/scripts/"*.sh "$GLOBAL_DIR/scripts/" 2>/dev/null || true

echo "Copying plugins..."
mkdir -p "$GLOBAL_DIR/plugins"
cp -r "$SCRIPT_DIR/.claude/plugins/braintrust-tracing" "$GLOBAL_DIR/plugins/" 2>/dev/null || true

# Copy settings.json (use project version as base)
echo "Installing settings.json..."
cp "$SCRIPT_DIR/.claude/settings.json" "$GLOBAL_DIR/settings.json"

# Create .env if it doesn't exist
if [ ! -f "$GLOBAL_DIR/.env" ]; then
    echo "Creating .env template..."
    cp "$SCRIPT_DIR/.env.example" "$GLOBAL_DIR/.env"
    echo ""
    echo "IMPORTANT: Edit ~/.claude/.env and add your API keys:"
    echo "  - BRAINTRUST_API_KEY (for session tracing)"
    echo "  - PERPLEXITY_API_KEY (for web search)"
    echo "  - etc."
else
    echo ".env already exists (not overwritten)"
fi

# Create required cache directories
mkdir -p "$GLOBAL_DIR/cache/learnings"
mkdir -p "$GLOBAL_DIR/cache/insights"
mkdir -p "$GLOBAL_DIR/cache/agents"
mkdir -p "$GLOBAL_DIR/cache/artifact-index"
mkdir -p "$GLOBAL_DIR/state/braintrust_sessions"

echo ""
echo "Installation complete!"
echo ""
echo "Features now available in any project:"
echo "  - Continuity ledger (/continuity_ledger)"
echo "  - Handoffs (/create_handoff, /resume_handoff)"
echo "  - TDD workflow (auto-activates on 'implement', 'fix bug')"
echo "  - Session tracing (if BRAINTRUST_API_KEY set)"
echo "  - All skills and agents"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "FOR EACH PROJECT - Initialize project structure:"
echo ""
echo "  cd /path/to/your/project"
echo "  $SCRIPT_DIR/init-project.sh"
echo ""
echo "This creates thoughts/, .claude/cache/, and the Artifact Index"
echo "database so all hooks work immediately."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "To update later, pull the repo and run this script again."

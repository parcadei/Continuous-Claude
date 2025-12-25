#!/bin/bash
###
# SessionStart Hook - Creates the root trace span when a Claude Code session begins
###

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

debug "SessionStart hook triggered"

tracing_enabled || { debug "Tracing disabled"; exit 0; }
check_requirements || exit 0

# Read input from stdin
INPUT=$(cat)
debug "SessionStart input: $INPUT"

# Extract session ID from input
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

if [ -z "$SESSION_ID" ]; then
    # Generate a session ID if not provided
    SESSION_ID=$(generate_uuid)
    debug "Generated session ID: $SESSION_ID"
fi

# Get project ID
PROJECT_ID=$(get_project_id "$PROJECT") || { log "ERROR" "Failed to get project"; exit 0; }
debug "Using project: $PROJECT (id: $PROJECT_ID)"

# Check if we already have a root span for this session
EXISTING_ROOT=$(get_session_state "$SESSION_ID" "root_span_id")
if [ -n "$EXISTING_ROOT" ]; then
    debug "Session already has root span: $EXISTING_ROOT"
    exit 0
fi

# Create root span for the session
ROOT_SPAN_ID="$SESSION_ID"
TIMESTAMP=$(get_timestamp)

# Extract workspace info if available
WORKSPACE=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
WORKSPACE_NAME=$(basename "$WORKSPACE" 2>/dev/null || echo "Claude Code")

# Get system info
HOSTNAME=$(get_hostname)
USERNAME=$(get_username)
OS=$(get_os)

EVENT=$(jq -n \
    --arg id "$ROOT_SPAN_ID" \
    --arg span_id "$ROOT_SPAN_ID" \
    --arg root_span_id "$ROOT_SPAN_ID" \
    --arg created "$TIMESTAMP" \
    --arg session "$SESSION_ID" \
    --arg workspace "$WORKSPACE_NAME" \
    --arg cwd "$WORKSPACE" \
    --arg hostname "$HOSTNAME" \
    --arg username "$USERNAME" \
    --arg os "$OS" \
    '{
        id: $id,
        span_id: $span_id,
        root_span_id: $root_span_id,
        created: $created,
        input: ("Session: " + $workspace),
        metadata: {
            session_id: $session,
            workspace: $cwd,
            hostname: $hostname,
            username: $username,
            os: $os,
            source: "claude-code"
        },
        span_attributes: {
            name: ("Claude Code: " + $workspace),
            type: "task"
        }
    }')

ROW_ID=$(insert_span "$PROJECT_ID" "$EVENT") || { log "ERROR" "Failed to create session root"; exit 0; }

# Save session state
set_session_state "$SESSION_ID" "root_span_id" "$ROOT_SPAN_ID"
set_session_state "$SESSION_ID" "project_id" "$PROJECT_ID"
set_session_state "$SESSION_ID" "turn_count" "0"
set_session_state "$SESSION_ID" "tool_count" "0"
set_session_state "$SESSION_ID" "started" "$TIMESTAMP"

log "INFO" "Created session root: $SESSION_ID workspace=$WORKSPACE_NAME"

exit 0

#!/bin/bash
###
# UserPromptSubmit Hook - Creates a Turn container span when user submits a prompt
###

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

debug "UserPromptSubmit hook triggered"

tracing_enabled || { debug "Tracing disabled"; exit 0; }
check_requirements || exit 0

# Read input from stdin
INPUT=$(cat)
debug "UserPromptSubmit input: $(echo "$INPUT" | jq -c '.' 2>/dev/null | head -c 500)"

# Extract session ID and prompt
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)

[ -z "$SESSION_ID" ] && { debug "No session ID"; exit 0; }

# Get session info
ROOT_SPAN_ID=$(get_session_state "$SESSION_ID" "root_span_id")
PROJECT_ID=$(get_session_state "$SESSION_ID" "project_id")

# If no session root exists yet, we'll create it
if [ -z "$ROOT_SPAN_ID" ] || [ -z "$PROJECT_ID" ]; then
    PROJECT_ID=$(get_project_id "$PROJECT") || { log "ERROR" "Failed to get project"; exit 0; }
    ROOT_SPAN_ID="$SESSION_ID"

    # Get workspace name from cwd
    CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
    WORKSPACE_NAME=$(basename "$CWD" 2>/dev/null || echo "workspace")

    TIMESTAMP=$(get_timestamp)
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
                workspace: $workspace,
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

    insert_span "$PROJECT_ID" "$EVENT" >/dev/null || true
    set_session_state "$SESSION_ID" "root_span_id" "$ROOT_SPAN_ID"
    set_session_state "$SESSION_ID" "project_id" "$PROJECT_ID"
    log "INFO" "Created session root: $SESSION_ID"
fi

# Reconciliation: finalize any previous turn that wasn't closed (e.g., Esc interrupt)
PREV_TURN_SPAN_ID=$(get_session_state "$SESSION_ID" "current_turn_span_id")
if [ -n "$PREV_TURN_SPAN_ID" ]; then
    log "WARN" "Previous turn $PREV_TURN_SPAN_ID still open - finalizing now (likely Esc interrupt)"
    END_TIME=$(date +%s)
    TURN_UPDATE=$(jq -n \
        --arg id "$PREV_TURN_SPAN_ID" \
        --argjson end_time "$END_TIME" \
        '{
            id: $id,
            _is_merge: true,
            metrics: {
                end: $end_time
            }
        }')
    insert_span "$PROJECT_ID" "$TURN_UPDATE" >/dev/null 2>&1 || log "WARN" "Failed to finalize previous turn"
    set_session_state "$SESSION_ID" "current_turn_span_id" ""
fi

# Increment turn count and create Turn span
TURN_COUNT=$(get_session_state "$SESSION_ID" "turn_count")
TURN_COUNT=${TURN_COUNT:-0}
TURN_COUNT=$((TURN_COUNT + 1))

TURN_SPAN_ID=$(generate_uuid)
TIMESTAMP=$(get_timestamp)
START_TIME=$(date +%s)

# Truncate prompt for display (first 100 chars)
PROMPT_PREVIEW="${PROMPT:0:100}"
[ ${#PROMPT} -gt 100 ] && PROMPT_PREVIEW="${PROMPT_PREVIEW}..."

# Create Turn container span
EVENT=$(jq -n \
    --arg id "$TURN_SPAN_ID" \
    --arg span_id "$TURN_SPAN_ID" \
    --arg root_span_id "$ROOT_SPAN_ID" \
    --arg created "$TIMESTAMP" \
    --arg prompt "$PROMPT" \
    --argjson turn "$TURN_COUNT" \
    --argjson start_time "$START_TIME" \
    '{
        id: $id,
        span_id: $span_id,
        root_span_id: $root_span_id,
        span_parents: [$root_span_id],
        created: $created,
        input: $prompt,
        metrics: {
            start: $start_time
        },
        span_attributes: {
            name: ("Turn " + ($turn | tostring)),
            type: "task"
        }
    }')

ROW_ID=$(insert_span "$PROJECT_ID" "$EVENT") || { log "ERROR" "Failed to create turn span"; exit 0; }

# Save turn state
set_session_state "$SESSION_ID" "turn_count" "$TURN_COUNT"
set_session_state "$SESSION_ID" "current_turn_span_id" "$TURN_SPAN_ID"
set_session_state "$SESSION_ID" "current_turn_start" "$START_TIME"
set_session_state "$SESSION_ID" "current_turn_tool_count" "0"

log "INFO" "Turn $TURN_COUNT started: $TURN_SPAN_ID"

exit 0

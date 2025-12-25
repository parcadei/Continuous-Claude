#!/bin/bash
###
# SessionEnd Hook - Finalizes the trace when a Claude Code session ends
###

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

debug "SessionEnd hook triggered"

tracing_enabled || { debug "Tracing disabled"; exit 0; }
check_requirements || exit 0

# Read input from stdin
INPUT=$(cat)
debug "SessionEnd input: $(echo "$INPUT" | jq -c '.' 2>/dev/null | head -c 500)"

# Extract session ID
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

if [ -z "$SESSION_ID" ]; then
    SESSION_ID=$(load_state | jq -r '.sessions | keys | .[-1] // empty' 2>/dev/null)
fi

[ -z "$SESSION_ID" ] && { debug "No session ID, skipping"; exit 0; }

# Get session info
ROOT_SPAN_ID=$(get_session_state "$SESSION_ID" "root_span_id")
PROJECT_ID=$(get_session_state "$SESSION_ID" "project_id")
TURN_COUNT=$(get_session_state "$SESSION_ID" "turn_count")
TOOL_COUNT=$(get_session_state "$SESSION_ID" "tool_count")
STARTED=$(get_session_state "$SESSION_ID" "started")

[ -z "$ROOT_SPAN_ID" ] && { debug "No root span for session"; exit 0; }
[ -z "$PROJECT_ID" ] && { debug "No project ID for session"; exit 0; }

# Reconciliation: finalize any open turn before ending session
CURRENT_TURN_SPAN_ID=$(get_session_state "$SESSION_ID" "current_turn_span_id")
if [ -n "$CURRENT_TURN_SPAN_ID" ]; then
    log "INFO" "Finalizing open turn $CURRENT_TURN_SPAN_ID at session end"
    END_TIME=$(date +%s)
    TURN_UPDATE=$(jq -n \
        --arg id "$CURRENT_TURN_SPAN_ID" \
        --argjson end_time "$END_TIME" \
        '{
            id: $id,
            _is_merge: true,
            metrics: {
                end: $end_time
            }
        }')
    insert_span "$PROJECT_ID" "$TURN_UPDATE" >/dev/null 2>&1 || log "WARN" "Failed to finalize turn at session end"
    set_session_state "$SESSION_ID" "current_turn_span_id" ""
fi

# Calculate duration if we have start time
DURATION=""
if [ -n "$STARTED" ]; then
    # Note: This is a rough estimate, proper duration tracking would need more work
    DURATION="session"
fi

# Update the root span with final stats
TIMESTAMP=$(get_timestamp)

# We could update the root span with summary info, but Braintrust doesn't
# support updating existing spans via the insert API. Instead, we'll just
# log the session summary.

TURN_COUNT=${TURN_COUNT:-0}
TOOL_COUNT=${TOOL_COUNT:-0}

log "INFO" "Session ended: $SESSION_ID (turns=$TURN_COUNT, tools=$TOOL_COUNT)"

# Clean up session state (optional - keeps state file cleaner)
# Uncomment to remove session from state after it ends:
# STATE=$(load_state)
# STATE=$(echo "$STATE" | jq --arg s "$SESSION_ID" 'del(.sessions[$s])')
# save_state "$STATE"

exit 0

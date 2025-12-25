#!/bin/bash
###
# PostToolUse Hook - Creates a tool span as child of current Turn
###

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

debug "PostToolUse hook triggered"

tracing_enabled || { debug "Tracing disabled"; exit 0; }
check_requirements || exit 0

# Read input from stdin
INPUT=$(cat)
debug "PostToolUse input: $(echo "$INPUT" | jq -c '.' 2>/dev/null | head -c 500)"

# Extract tool info
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
TOOL_INPUT=$(echo "$INPUT" | jq -c '.tool_input // {}' 2>/dev/null)
TOOL_OUTPUT=$(echo "$INPUT" | jq -c '.tool_response // .output // {}' 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

# Skip if no tool name
[ -z "$TOOL_NAME" ] && { debug "No tool name, skipping"; exit 0; }
[ -z "$SESSION_ID" ] && { debug "No session ID, skipping"; exit 0; }

# Extract agent type from Task tool
AGENT_TYPE=""
if [ "$TOOL_NAME" = "Task" ]; then
    AGENT_TYPE=$(echo "$TOOL_INPUT" | jq -r '.subagent_type // empty' 2>/dev/null)
    debug "Task agent_type: $AGENT_TYPE"
fi

# Extract skill name from Skill tool
SKILL_NAME=""
if [ "$TOOL_NAME" = "Skill" ]; then
    SKILL_NAME=$(echo "$TOOL_INPUT" | jq -r '.skill // empty' 2>/dev/null)
    debug "Skill name: $SKILL_NAME"
fi

# Get session info
ROOT_SPAN_ID=$(get_session_state "$SESSION_ID" "root_span_id")
PROJECT_ID=$(get_session_state "$SESSION_ID" "project_id")
TURN_SPAN_ID=$(get_session_state "$SESSION_ID" "current_turn_span_id")

# If no turn span exists, tools are orphaned - skip
if [ -z "$TURN_SPAN_ID" ] || [ -z "$PROJECT_ID" ]; then
    debug "No current turn for session $SESSION_ID, skipping tool trace"
    exit 0
fi

# Increment tool count for this turn
TOOL_COUNT=$(get_session_state "$SESSION_ID" "current_turn_tool_count")
TOOL_COUNT=${TOOL_COUNT:-0}
TOOL_COUNT=$((TOOL_COUNT + 1))
set_session_state "$SESSION_ID" "current_turn_tool_count" "$TOOL_COUNT"

# Generate span ID
SPAN_ID=$(generate_uuid)
TIMESTAMP=$(get_timestamp)
TOOL_TIME=$(date +%s)

# Determine span name based on tool
case "$TOOL_NAME" in
    Read|Write|Edit|MultiEdit)
        FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.file_path // .path // empty' 2>/dev/null)
        if [ -n "$FILE_PATH" ]; then
            SPAN_NAME="$TOOL_NAME: $(basename "$FILE_PATH")"
        else
            SPAN_NAME="$TOOL_NAME"
        fi
        ;;
    Bash|Terminal)
        CMD=$(echo "$TOOL_INPUT" | jq -r '.command // empty' 2>/dev/null | head -c 50)
        SPAN_NAME="Terminal: ${CMD:-command}"
        ;;
    mcp__*)
        SPAN_NAME=$(echo "$TOOL_NAME" | sed 's/mcp__/MCP: /' | sed 's/__/ - /')
        ;;
    *)
        SPAN_NAME="$TOOL_NAME"
        ;;
esac

# Build the event - tool is child of Turn
EVENT=$(jq -n \
    --arg id "$SPAN_ID" \
    --arg span_id "$SPAN_ID" \
    --arg root_span_id "$ROOT_SPAN_ID" \
    --arg parent "$TURN_SPAN_ID" \
    --arg created "$TIMESTAMP" \
    --arg tool "$TOOL_NAME" \
    --arg agent_type "$AGENT_TYPE" \
    --arg skill_name "$SKILL_NAME" \
    --argjson input "$TOOL_INPUT" \
    --argjson output "$TOOL_OUTPUT" \
    --arg name "$SPAN_NAME" \
    --argjson start_time "$TOOL_TIME" \
    --argjson end_time "$TOOL_TIME" \
    '{
        id: $id,
        span_id: $span_id,
        root_span_id: $root_span_id,
        span_parents: [$parent],
        created: $created,
        input: $input,
        output: $output,
        metrics: {
            start: $start_time,
            end: $end_time
        },
        metadata: ({
            tool_name: $tool
        } + (if $agent_type != "" then {agent_type: $agent_type} else {} end)
          + (if $skill_name != "" then {skill_name: $skill_name} else {} end)),
        span_attributes: {
            name: $name,
            type: "tool"
        }
    }')

ROW_ID=$(insert_span "$PROJECT_ID" "$EVENT") || { log "ERROR" "Failed to create tool span"; exit 0; }

log "INFO" "Tool: $SPAN_NAME (turn=$TURN_SPAN_ID)"

exit 0

#!/bin/bash
###
# Stop Hook - Creates LLM spans for each model call within the Turn
#
# Structure:
#   Session (task)
#   ├── Turn 1 (task) - created by UserPromptSubmit
#   │   ├── claude-sonnet... (llm) - first model call (plan + tool_use)
#   │   ├── Tool 1 (tool) - created by PostToolUse
#   │   ├── Tool 2 (tool) - created by PostToolUse
#   │   └── claude-sonnet... (llm) - second model call (after tools)
#   └── Turn 2 (task)
#       └── ...
#
# Each assistant message block = one LLM call
###

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

log "INFO" "=== STOP HOOK CALLED ==="

tracing_enabled || { log "WARN" "Tracing disabled"; exit 0; }
check_requirements || exit 0

# Read input from stdin
INPUT=$(cat)
debug "Stop input: $(echo "$INPUT" | jq -c '.' 2>/dev/null | head -c 500)"

# Get session ID
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

if [ -z "$SESSION_ID" ]; then
    TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
    if [ -n "$TRANSCRIPT_PATH" ]; then
        SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl)
    fi
fi

[ -z "$SESSION_ID" ] && { debug "No session ID"; exit 0; }

# Get session state
ROOT_SPAN_ID=$(get_session_state "$SESSION_ID" "root_span_id")
PROJECT_ID=$(get_session_state "$SESSION_ID" "project_id")
TURN_SPAN_ID=$(get_session_state "$SESSION_ID" "current_turn_span_id")
TURN_START=$(get_session_state "$SESSION_ID" "current_turn_start")

if [ -z "$TURN_SPAN_ID" ] || [ -z "$PROJECT_ID" ]; then
    log "WARN" "No current turn to finalize (TURN_SPAN_ID='$TURN_SPAN_ID', PROJECT_ID='$PROJECT_ID')"
    exit 0
fi

log "INFO" "Stop hook processing turn: $TURN_SPAN_ID (session=$SESSION_ID)"

# Find the conversation file
CONV_FILE=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
if [ -z "$CONV_FILE" ] || [ ! -f "$CONV_FILE" ]; then
    SESSIONS_DIR="$HOME/.claude/projects"
    CONV_FILE=$(find "$SESSIONS_DIR" -name "${SESSION_ID}.jsonl" -type f 2>/dev/null | head -1)
fi

[ -z "$CONV_FILE" ] || [ ! -f "$CONV_FILE" ] && { debug "No conversation file"; exit 0; }

debug "Processing transcript: $CONV_FILE"

# Get last processed line for this turn
TURN_LAST_LINE=$(get_session_state "$SESSION_ID" "turn_last_line")
TURN_LAST_LINE=${TURN_LAST_LINE:-0}

TOTAL_LINES=$(wc -l < "$CONV_FILE" | tr -d ' ')

# Process the transcript to find LLM calls
# An LLM call = assistant message(s) that follow a user message or tool_result
LLM_CALLS_CREATED=0
CURRENT_OUTPUT_TEXT=""
CURRENT_TOOL_CALLS="[]"
CURRENT_MODEL=""
CURRENT_PROMPT_TOKENS=0
CURRENT_COMPLETION_TOKENS=0
CURRENT_START_TIMESTAMP=""  # ISO timestamp when this LLM call started
CURRENT_END_TIMESTAMP=""    # ISO timestamp when this LLM call ended
LINE_NUM=0

# Accumulated conversation history (JSON array of messages)
CONVERSATION_HISTORY="[]"

# Add message to conversation history
# Uses temp files to avoid "argument list too long" errors with large content
add_to_history() {
    local role="$1"
    local content="$2"
    local tool_call_id="$3"
    local tool_calls="$4"

    # Use temp files to avoid shell argument limits for large content
    local tmp_content=$(mktemp)
    local tmp_history=$(mktemp)
    trap "rm -f '$tmp_content' '$tmp_history'" RETURN

    # Truncate very large content to avoid memory issues (keep first 50KB)
    echo "${content:0:51200}" > "$tmp_content"
    echo "$CONVERSATION_HISTORY" > "$tmp_history"

    if [ "$role" = "tool" ]; then
        CONVERSATION_HISTORY=$(jq --arg role "$role" --arg id "$tool_call_id" \
            --rawfile content "$tmp_content" \
            '. += [{role: $role, tool_call_id: $id, content: $content}]' "$tmp_history")
    elif [ -n "$tool_calls" ] && [ "$tool_calls" != "[]" ]; then
        CONVERSATION_HISTORY=$(jq --arg role "$role" --argjson tc "$tool_calls" \
            --rawfile content "$tmp_content" \
            '. += [{role: $role, content: $content, tool_calls: $tc}]' "$tmp_history")
    else
        CONVERSATION_HISTORY=$(jq --arg role "$role" \
            --rawfile content "$tmp_content" \
            '. += [{role: $role, content: $content}]' "$tmp_history")
    fi
}

# Convert ISO timestamp (UTC with Z suffix) to Unix epoch
iso_to_epoch() {
    local ts="$1"
    [ -z "$ts" ] && { date +%s; return; }
    # Remove the Z and milliseconds, parse as UTC
    local clean_ts="${ts%.*}"  # Remove .xxxZ
    clean_ts="${clean_ts}+0000"  # Append UTC offset
    # macOS: use -j -f with explicit UTC offset
    date -j -f "%Y-%m-%dT%H:%M:%S%z" "$clean_ts" "+%s" 2>/dev/null || \
    # Linux: -d handles ISO format natively
    date -d "$ts" "+%s" 2>/dev/null || \
    date +%s
}

create_llm_span() {
    local output_text="$1"
    local model="$2"
    local prompt_tokens="$3"
    local completion_tokens="$4"
    local start_ts="$5"   # ISO timestamp
    local end_ts="$6"     # ISO timestamp
    local tool_calls_json="${7:-[]}"
    local input_history="$8"  # JSON array of conversation history

    # Need either text or tool_calls
    [ -z "$output_text" ] && [ "$tool_calls_json" = "[]" ] && return

    local span_id=$(generate_uuid)
    local total_tokens=$((prompt_tokens + completion_tokens))
    local start_time=$(iso_to_epoch "$start_ts")
    local end_time=$(iso_to_epoch "$end_ts")

    # Input is the conversation history up to this point
    local input_json="$input_history"

    # Format output - include tool_calls if present
    local output_json
    local has_tool_calls=$(echo "$tool_calls_json" | jq 'length > 0' 2>/dev/null)
    if [ "$has_tool_calls" = "true" ]; then
        output_json=$(jq -n \
            --arg content "${output_text:-}" \
            --argjson tool_calls "$tool_calls_json" \
            '{role: "assistant", content: $content, tool_calls: $tool_calls}')
    else
        output_json=$(jq -n --arg content "$output_text" '{role: "assistant", content: $content}')
    fi

    local event=$(jq -n \
        --arg id "$span_id" \
        --arg span_id "$span_id" \
        --arg root_span_id "$ROOT_SPAN_ID" \
        --arg parent "$TURN_SPAN_ID" \
        --arg created "${start_ts:-$(get_timestamp)}" \
        --argjson input "$input_json" \
        --argjson output "$output_json" \
        --arg model "${model:-claude}" \
        --argjson prompt_tokens "$prompt_tokens" \
        --argjson completion_tokens "$completion_tokens" \
        --argjson tokens "$total_tokens" \
        --argjson start_time "$start_time" \
        --argjson end_time "$end_time" \
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
                end: $end_time,
                prompt_tokens: $prompt_tokens,
                completion_tokens: $completion_tokens,
                tokens: $tokens
            },
            metadata: {
                model: $model
            },
            span_attributes: {
                name: $model,
                type: "llm"
            }
        }')

    insert_span "$PROJECT_ID" "$event" >/dev/null && {
        LLM_CALLS_CREATED=$((LLM_CALLS_CREATED + 1))
        log "INFO" "LLM span: $model tokens=$total_tokens (turn=$TURN_SPAN_ID)"
    } || true
}

while IFS= read -r line; do
    LINE_NUM=$((LINE_NUM + 1))
    [ "$LINE_NUM" -le "$TURN_LAST_LINE" ] && continue
    [ -z "$line" ] && continue

    MSG_TYPE=$(echo "$line" | jq -r '.type // empty' 2>/dev/null)
    MSG_TIMESTAMP=$(echo "$line" | jq -r '.timestamp // empty' 2>/dev/null)

    if [ "$MSG_TYPE" = "user" ]; then
        # Check if tool_result or real user message
        CONTENT=$(echo "$line" | jq -r '.message.content // empty' 2>/dev/null)
        IS_TOOL_RESULT=$(echo "$CONTENT" | jq -e '.[0].type == "tool_result"' >/dev/null 2>&1 && echo "true" || echo "false")

        if [ "$IS_TOOL_RESULT" = "true" ]; then
            # Tool result - if we have pending output, save it first
            if [ -n "$CURRENT_OUTPUT_TEXT" ] || [ "$CURRENT_TOOL_CALLS" != "[]" ]; then
                create_llm_span "$CURRENT_OUTPUT_TEXT" "$CURRENT_MODEL" "$CURRENT_PROMPT_TOKENS" "$CURRENT_COMPLETION_TOKENS" "$CURRENT_START_TIMESTAMP" "$CURRENT_END_TIMESTAMP" "$CURRENT_TOOL_CALLS" "$CONVERSATION_HISTORY"
                # Add assistant response to history
                add_to_history "assistant" "$CURRENT_OUTPUT_TEXT" "" "$CURRENT_TOOL_CALLS"
            fi

            # Extract tool result content and tool_use_id
            TOOL_RESULT_CONTENT=$(echo "$CONTENT" | jq -r '.[0].content // "tool result"' 2>/dev/null)
            TOOL_USE_ID=$(echo "$CONTENT" | jq -r '.[0].tool_use_id // ""' 2>/dev/null)

            # Add tool result to conversation history
            add_to_history "tool" "$TOOL_RESULT_CONTENT" "$TOOL_USE_ID" ""

            # Reset for next LLM call - DON'T set start timestamp yet
            # The next assistant message timestamp will be the actual LLM start
            CURRENT_OUTPUT_TEXT=""
            CURRENT_TOOL_CALLS="[]"
            CURRENT_MODEL=""
            CURRENT_PROMPT_TOKENS=0
            CURRENT_COMPLETION_TOKENS=0
            CURRENT_START_TIMESTAMP=""  # Will be set from first assistant message
            CURRENT_END_TIMESTAMP=""
        else
            # Real user message - if we have pending output, save it
            if [ -n "$CURRENT_OUTPUT_TEXT" ] || [ "$CURRENT_TOOL_CALLS" != "[]" ]; then
                create_llm_span "$CURRENT_OUTPUT_TEXT" "$CURRENT_MODEL" "$CURRENT_PROMPT_TOKENS" "$CURRENT_COMPLETION_TOKENS" "$CURRENT_START_TIMESTAMP" "$CURRENT_END_TIMESTAMP" "$CURRENT_TOOL_CALLS" "$CONVERSATION_HISTORY"
                # Add assistant response to history
                add_to_history "assistant" "$CURRENT_OUTPUT_TEXT" "" "$CURRENT_TOOL_CALLS"
            fi

            # Add user message to conversation history
            add_to_history "user" "$CONTENT" "" ""

            # Reset for next LLM call
            CURRENT_OUTPUT_TEXT=""
            CURRENT_TOOL_CALLS="[]"
            CURRENT_MODEL=""
            CURRENT_PROMPT_TOKENS=0
            CURRENT_COMPLETION_TOKENS=0
            CURRENT_START_TIMESTAMP="$MSG_TIMESTAMP"
            CURRENT_END_TIMESTAMP=""
        fi

    elif [ "$MSG_TYPE" = "assistant" ]; then
        # Extract text content
        TEXT=$(echo "$line" | jq -r '
            .message.content
            | if type == "array" then
                [.[] | select(.type == "text") | .text] | join("\n")
              elif type == "string" then
                .
              else
                empty
              end
        ' 2>/dev/null)

        # Extract full tool_use objects for tool_calls
        TOOL_CALLS_JSON=$(echo "$line" | jq -c '
            .message.content
            | if type == "array" then
                [.[] | select(.type == "tool_use") | {
                    id: .id,
                    type: "function",
                    function: {
                        name: .name,
                        arguments: (.input | tojson)
                    }
                }]
              else
                []
              end
        ' 2>/dev/null)

        # Check if we have tool calls
        HAS_TOOL_CALLS=$(echo "$TOOL_CALLS_JSON" | jq 'length > 0' 2>/dev/null)

        # Set start timestamp from first assistant message of this LLM call
        [ -z "$CURRENT_START_TIMESTAMP" ] && CURRENT_START_TIMESTAMP="$MSG_TIMESTAMP"

        if [ -n "$TEXT" ]; then
            if [ -n "$CURRENT_OUTPUT_TEXT" ]; then
                CURRENT_OUTPUT_TEXT="$CURRENT_OUTPUT_TEXT"$'\n'"$TEXT"
            else
                CURRENT_OUTPUT_TEXT="$TEXT"
            fi
            CURRENT_END_TIMESTAMP="$MSG_TIMESTAMP"
        fi

        if [ "$HAS_TOOL_CALLS" = "true" ]; then
            CURRENT_TOOL_CALLS="$TOOL_CALLS_JSON"
            CURRENT_END_TIMESTAMP="$MSG_TIMESTAMP"
        fi

        # Extract model
        MODEL=$(echo "$line" | jq -r '.message.model // empty' 2>/dev/null)
        [ -n "$MODEL" ] && CURRENT_MODEL="$MODEL"

        # Extract tokens
        USAGE=$(echo "$line" | jq -c '.message.usage // {}' 2>/dev/null)
        if [ "$USAGE" != "{}" ] && [ -n "$USAGE" ]; then
            INPUT_TOKENS=$(echo "$USAGE" | jq -r '.input_tokens // 0' 2>/dev/null)
            OUTPUT_TOKENS=$(echo "$USAGE" | jq -r '.output_tokens // 0' 2>/dev/null)
            [ "$INPUT_TOKENS" != "null" ] && [ "$INPUT_TOKENS" -gt 0 ] 2>/dev/null && CURRENT_PROMPT_TOKENS=$((CURRENT_PROMPT_TOKENS + INPUT_TOKENS))
            [ "$OUTPUT_TOKENS" != "null" ] && [ "$OUTPUT_TOKENS" -gt 0 ] 2>/dev/null && CURRENT_COMPLETION_TOKENS=$((CURRENT_COMPLETION_TOKENS + OUTPUT_TOKENS))
        fi
    fi
done < "$CONV_FILE"

log "DEBUG" "Finished processing transcript (processed $LINE_NUM lines, LLM calls created so far: $LLM_CALLS_CREATED)"

# Save final LLM call
if [ -n "$CURRENT_OUTPUT_TEXT" ] || [ "$CURRENT_TOOL_CALLS" != "[]" ]; then
    log "DEBUG" "Saving final LLM call"
    create_llm_span "$CURRENT_OUTPUT_TEXT" "$CURRENT_MODEL" "$CURRENT_PROMPT_TOKENS" "$CURRENT_COMPLETION_TOKENS" "$CURRENT_START_TIMESTAMP" "$CURRENT_END_TIMESTAMP" "$CURRENT_TOOL_CALLS" "$CONVERSATION_HISTORY"
fi

# Update Turn span with end time using merge write
END_TIME=$(date +%s)

TURN_UPDATE=$(jq -n \
    --arg id "$TURN_SPAN_ID" \
    --argjson end_time "$END_TIME" \
    '{
        id: $id,
        _is_merge: true,
        metrics: {
            end: $end_time
        }
    }')

log "DEBUG" "Attempting turn finalization: turn=$TURN_SPAN_ID project=$PROJECT_ID"
debug "TURN_UPDATE payload: $(echo "$TURN_UPDATE" | jq -c .)"

FINALIZE_RESULT=$(insert_span "$PROJECT_ID" "$TURN_UPDATE" 2>&1) && {
    log "DEBUG" "Turn finalization insert succeeded: $FINALIZE_RESULT"
} || {
    log "ERROR" "Turn finalization insert failed: $FINALIZE_RESULT"
}

# Update state
set_session_state "$SESSION_ID" "turn_last_line" "$TOTAL_LINES"
set_session_state "$SESSION_ID" "current_turn_span_id" ""

[ "$LLM_CALLS_CREATED" -gt 0 ] && log "INFO" "Created $LLM_CALLS_CREATED LLM spans for turn"
log "INFO" "Turn finalized (end=$END_TIME)"

exit 0

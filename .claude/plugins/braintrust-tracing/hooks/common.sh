#!/bin/bash
###
# Common utilities for Braintrust Claude Code tracing hooks
#
# FIXED: Per-session state files to prevent multi-instance clobbering
###

# Config
export LOG_FILE="$HOME/.claude/state/braintrust_hook.log"
export STATE_DIR="$HOME/.claude/state/braintrust_sessions"
export GLOBAL_STATE_FILE="$HOME/.claude/state/braintrust_global.json"
export DEBUG="${BRAINTRUST_CC_DEBUG:-false}"
export API_KEY="${BRAINTRUST_API_KEY}"
export PROJECT="${BRAINTRUST_CC_PROJECT:-claude-code}"
export API_URL="${BRAINTRUST_API_URL:-https://api.braintrust.dev}"

# Ensure directories exist
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$STATE_DIR"

# Logging
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [$1] $2" >> "$LOG_FILE"; }
debug() { [ "$(echo "$DEBUG" | tr '[:upper:]' '[:lower:]')" = "true" ] && log "DEBUG" "$1" || true; }

# Check if tracing is enabled
tracing_enabled() {
    [ "$(echo "$TRACE_TO_BRAINTRUST" | tr '[:upper:]' '[:lower:]')" = "true" ]
}

# Validate requirements
check_requirements() {
    for cmd in jq curl; do
        command -v "$cmd" &>/dev/null || { log "ERROR" "$cmd not installed"; return 1; }
    done
    [ -z "$API_KEY" ] && { log "ERROR" "BRAINTRUST_API_KEY not set"; return 1; }
    return 0
}

# Get session state file path
get_session_file() {
    local session_id="$1"
    echo "$STATE_DIR/${session_id}.json"
}

# Load state from file with validation
load_state_file() {
    local file="$1"
    if [ -f "$file" ]; then
        local content
        content=$(cat "$file" 2>/dev/null)
        # Validate it's valid JSON
        if echo "$content" | jq -e '.' >/dev/null 2>&1; then
            echo "$content"
        else
            debug "Corrupt state file: $file"
            echo "{}"
        fi
    else
        echo "{}"
    fi
}

# Save state to file atomically
save_state_file() {
    local file="$1"
    local content="$2"
    local temp_file="${file}.tmp.$$"

    # Validate content is valid JSON before saving
    if ! echo "$content" | jq -e '.' >/dev/null 2>&1; then
        log "ERROR" "Attempted to save invalid JSON to $file"
        return 1
    fi

    # Write to temp file then atomic rename
    echo "$content" > "$temp_file" && mv "$temp_file" "$file"
}

# Global state (for project_id cache - shared across sessions)
load_global_state() {
    load_state_file "$GLOBAL_STATE_FILE"
}

save_global_state() {
    save_state_file "$GLOBAL_STATE_FILE" "$1"
}

get_state_value() {
    local key="$1"
    load_global_state | jq -r ".$key // empty"
}

set_state_value() {
    local key="$1"
    local value="$2"
    local state
    state=$(load_global_state)
    state=$(echo "$state" | jq --arg k "$key" --arg v "$value" '.[$k] = $v')
    save_global_state "$state"
}

# Per-session state
get_session_state() {
    local session_id="$1"
    local key="$2"
    local file
    file=$(get_session_file "$session_id")
    load_state_file "$file" | jq -r ".$key // empty"
}

set_session_state() {
    local session_id="$1"
    local key="$2"
    local value="$3"
    local file state
    file=$(get_session_file "$session_id")
    state=$(load_state_file "$file")
    state=$(echo "$state" | jq --arg k "$key" --arg v "$value" '.[$k] = $v')
    save_state_file "$file" "$state"
}

# Get or create project ID (cached globally)
get_project_id() {
    local name="$1"

    # Check cache first
    local cached_id
    cached_id=$(get_state_value "project_id")
    if [ -n "$cached_id" ]; then
        echo "$cached_id"
        return 0
    fi

    local encoded_name
    encoded_name=$(printf '%s' "$name" | jq -sRr @uri)

    # Try to get existing project
    local resp
    resp=$(curl -sf -H "Authorization: Bearer $API_KEY" "$API_URL/v1/project?project_name=$encoded_name" 2>/dev/null) || true
    local pid
    pid=$(echo "$resp" | jq -r '.id // empty' 2>/dev/null)

    if [ -n "$pid" ]; then
        set_state_value "project_id" "$pid"
        echo "$pid"
        return 0
    fi

    # Create project
    debug "Creating project: $name"
    resp=$(curl -sf -X POST -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
        -d "{\"name\": \"$name\"}" "$API_URL/v1/project" 2>/dev/null) || true
    pid=$(echo "$resp" | jq -r '.id // empty' 2>/dev/null)

    if [ -n "$pid" ]; then
        set_state_value "project_id" "$pid"
        echo "$pid"
        return 0
    fi

    return 1
}

# Insert a span to Braintrust
insert_span() {
    local project_id="$1"
    local event_json="$2"

    debug "Inserting span: $(echo "$event_json" | jq -c '.')"

    # Check if API_KEY is set
    if [ -z "$API_KEY" ]; then
        log "ERROR" "API_KEY is empty - check BRAINTRUST_API_KEY env var"
        return 1
    fi

    local resp http_code
    # Use -w to capture HTTP status, don't use -f so we can see error responses
    resp=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" \
        -d "{\"events\": [$event_json]}" \
        "$API_URL/v1/project_logs/$project_id/insert" 2>&1)

    # Extract HTTP code from last line
    http_code=$(echo "$resp" | tail -1)
    resp=$(echo "$resp" | sed '$d')

    if [ "$http_code" != "200" ]; then
        log "ERROR" "Insert failed (HTTP $http_code): $resp"
        return 1
    fi

    local row_id
    row_id=$(echo "$resp" | jq -r '.row_ids[0] // empty' 2>/dev/null)

    if [ -n "$row_id" ]; then
        echo "$row_id"
        return 0
    else
        log "WARN" "Insert returned empty row_ids: $resp"
        return 1
    fi
}

# Generate a UUID
generate_uuid() {
    uuidgen | tr '[:upper:]' '[:lower:]'
}

# Get current ISO timestamp
get_timestamp() {
    date -u +"%Y-%m-%dT%H:%M:%S.000Z"
}

# Get system info for metadata
get_hostname() {
    hostname 2>/dev/null || echo "unknown"
}

get_username() {
    whoami 2>/dev/null || echo "unknown"
}

get_os() {
    uname -s 2>/dev/null || echo "unknown"
}

# Cleanup old session state files (older than 7 days)
cleanup_old_sessions() {
    find "$STATE_DIR" -name "*.json" -mtime +7 -delete 2>/dev/null || true
}

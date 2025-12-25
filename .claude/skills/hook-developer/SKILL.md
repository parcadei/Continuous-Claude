---
name: hook-developer
description: Complete Claude Code hooks reference - input/output schemas, registration, testing patterns
---

# Hook Developer

Complete reference for developing Claude Code hooks. Use this to write hooks with correct input/output schemas.

## When to Use

- Creating a new hook
- Debugging hook input/output format
- Understanding what fields are available
- Setting up hook registration in settings.json
- Learning what hooks can block vs inject context

## Quick Reference

| Hook | Fires When | Can Block? | Primary Use |
|------|-----------|------------|-------------|
| **PreToolUse** | Before tool executes | YES | Block/modify tool calls |
| **PostToolUse** | After tool completes | Partial | React to tool results |
| **UserPromptSubmit** | User sends prompt | YES | Validate/inject context |
| **PermissionRequest** | Permission dialog shows | YES | Auto-approve/deny |
| **SessionStart** | Session begins | NO | Load context |
| **SessionEnd** | Session ends | NO | Cleanup/save state |
| **Stop** | Agent finishes | YES | Force continuation |
| **SubagentStop** | Subagent finishes | YES | Force continuation |
| **PreCompact** | Before compaction | NO | Save state |
| **Notification** | Notification sent | NO | Custom alerts |

---

## Hook Input/Output Schemas

### PreToolUse

**Purpose:** Block or modify tool execution before it happens.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "default|plan|acceptEdits|bypassPermissions",
  "hook_event_name": "PreToolUse",
  "tool_name": "string",
  "tool_input": {
    "file_path": "string",
    "command": "string"
  },
  "tool_use_id": "string"
}
```

**Output (JSON):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow|deny|ask",
    "permissionDecisionReason": "string",
    "updatedInput": {}
  },
  "continue": true,
  "stopReason": "string",
  "systemMessage": "string",
  "suppressOutput": true
}
```

**Exit code 2:** Blocks tool, stderr shown to Claude.

**Common matchers:** `Bash`, `Edit|Write`, `Read`, `Task`, `mcp__.*`

---

### PostToolUse

**Purpose:** React to tool execution results, provide feedback to Claude.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "PostToolUse",
  "tool_name": "string",
  "tool_input": {},
  "tool_response": {
    "filePath": "string",
    "success": true,
    "output": "string",
    "exitCode": 0
  },
  "tool_use_id": "string"
}
```

**CRITICAL:** The response field is `tool_response`, NOT `tool_result`.

**Output (JSON):**
```json
{
  "decision": "block",
  "reason": "string",
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "string"
  },
  "continue": true,
  "stopReason": "string",
  "suppressOutput": true
}
```

**Blocking:** `"decision": "block"` with `"reason"` prompts Claude to address the issue.

**Common matchers:** `Edit|Write`, `Bash`

---

### UserPromptSubmit

**Purpose:** Validate user prompts, inject context before Claude processes.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "string"
}
```

**Output (Plain text):**
```
Any stdout text is added to context for Claude.
```

**Output (JSON):**
```json
{
  "decision": "block",
  "reason": "string",
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "string"
  }
}
```

**Blocking:** `"decision": "block"` erases prompt, shows `"reason"` to user only (not Claude).

**Exit code 2:** Blocks prompt, shows stderr to user only.

---

### PermissionRequest

**Purpose:** Automate permission dialog decisions.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "PermissionRequest",
  "tool_name": "string",
  "tool_input": {}
}
```

**Output:**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow|deny",
      "updatedInput": {},
      "message": "string",
      "interrupt": false
    }
  }
}
```

---

### SessionStart

**Purpose:** Initialize session, load context, set environment variables.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "SessionStart",
  "source": "startup|resume|clear|compact"
}
```

**Environment variable:** `CLAUDE_ENV_FILE` - write `export VAR=value` to persist env vars.

**Output (Plain text or JSON):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "string"
  },
  "suppressOutput": true
}
```

Plain text stdout is added as context.

---

### SessionEnd

**Purpose:** Cleanup, save state, log session.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "SessionEnd",
  "reason": "clear|logout|prompt_input_exit|other"
}
```

**Output:** Cannot affect session (already ending). Use for cleanup only.

---

### Stop

**Purpose:** Control when Claude stops, force continuation.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "Stop",
  "stop_hook_active": false
}
```

**CRITICAL:** Check `stop_hook_active: true` to prevent infinite loops!

**Output:**
```json
{
  "decision": "block",
  "reason": "string"
}
```

**Blocking:** `"decision": "block"` forces Claude to continue with `"reason"` as prompt.

---

### SubagentStop

**Purpose:** Control when subagents (Task tool) stop.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "SubagentStop",
  "stop_hook_active": false
}
```

**Output:** Same as Stop.

---

### PreCompact

**Purpose:** Save state before context compaction.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "PreCompact",
  "trigger": "manual|auto",
  "custom_instructions": "string"
}
```

**Matchers:** `manual`, `auto`

**Output:**
```json
{
  "continue": true,
  "systemMessage": "string"
}
```

---

### Notification

**Purpose:** Custom notification handling.

**Input:**
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "Notification",
  "message": "string",
  "notification_type": "permission_prompt|idle_prompt|auth_success|elicitation_dialog"
}
```

**Matchers:** `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog`, `*`

**Output:**
```json
{
  "continue": true,
  "suppressOutput": true,
  "systemMessage": "string"
}
```

---

## Registration in settings.json

### Standard Structure

```json
{
  "hooks": {
    "EventName": [
      {
        "matcher": "ToolPattern",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/my-hook.sh",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

### Matcher Patterns

| Pattern | Matches |
|---------|---------|
| `Bash` | Exactly Bash tool |
| `Edit\|Write` | Edit OR Write |
| `Read.*` | Regex: Read* |
| `mcp__.*__write.*` | MCP write tools |
| `*` | All tools |

**Case-sensitive:** `Bash` ≠ `bash`

### Events Requiring Matchers

- PreToolUse - YES (required)
- PostToolUse - YES (required)
- PermissionRequest - YES (required)
- Notification - YES (optional)
- SessionStart - YES (`startup|resume|clear|compact`)
- PreCompact - YES (`manual|auto`)

### Events Without Matchers

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [{ "type": "command", "command": "/path/to/hook.sh" }]
      }
    ]
  }
}
```

---

## Environment Variables

### Available to All Hooks

| Variable | Description |
|----------|-------------|
| `CLAUDE_PROJECT_DIR` | Absolute path to project root |
| `CLAUDE_CODE_REMOTE` | "true" if remote, empty if local |

### SessionStart Only

| Variable | Description |
|----------|-------------|
| `CLAUDE_ENV_FILE` | Path to write `export VAR=value` lines |

---

## Exit Codes

| Exit Code | Behavior | stdout | stderr |
|-----------|----------|--------|--------|
| **0** | Success | JSON processed | Ignored |
| **2** | Blocking error | IGNORED | Error message |
| **Other** | Non-blocking error | Ignored | Verbose mode |

### Exit Code 2 by Hook

| Hook | Effect |
|------|--------|
| PreToolUse | Blocks tool, stderr to Claude |
| PostToolUse | stderr to Claude (tool already ran) |
| UserPromptSubmit | Blocks prompt, stderr to user only |
| Stop | Blocks stop, stderr to Claude |

---

## Shell Wrapper Pattern

```bash
#!/bin/bash
set -e
cd "$CLAUDE_PROJECT_DIR/.claude/hooks"
cat | npx tsx src/my-hook.ts
```

Or for bundled:

```bash
#!/bin/bash
set -e
cd "$HOME/.claude/hooks"
cat | node dist/my-hook.mjs
```

---

## TypeScript Handler Pattern

```typescript
import { readFileSync } from 'fs';

interface HookInput {
  session_id: string;
  hook_event_name: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_response?: Record<string, unknown>;
  // ... other fields per hook type
}

function readStdin(): string {
  return readFileSync(0, 'utf-8');
}

async function main() {
  const input: HookInput = JSON.parse(readStdin());

  // Process input

  const output = {
    decision: 'block',  // or undefined to allow
    reason: 'Why blocking'
  };

  console.log(JSON.stringify(output));
}

main().catch(console.error);
```

---

## Testing Hooks

### Manual Test Commands

```bash
# PostToolUse (Write)
echo '{"tool_name":"Write","tool_input":{"file_path":"test.md"},"tool_response":{"success":true},"session_id":"test"}' | \
  .claude/hooks/my-hook.sh

# PreToolUse (Bash)
echo '{"tool_name":"Bash","tool_input":{"command":"ls"},"session_id":"test"}' | \
  .claude/hooks/my-hook.sh

# SessionStart
echo '{"hook_event_name":"SessionStart","source":"startup","session_id":"test"}' | \
  .claude/hooks/session-start.sh

# SessionEnd
echo '{"hook_event_name":"SessionEnd","reason":"clear","session_id":"test"}' | \
  .claude/hooks/session-end.sh

# UserPromptSubmit
echo '{"prompt":"test prompt","session_id":"test"}' | \
  .claude/hooks/prompt-submit.sh
```

### Rebuild After TypeScript Edits

```bash
cd .claude/hooks
npx esbuild src/my-hook.ts \
  --bundle --platform=node --format=esm \
  --outfile=dist/my-hook.mjs
```

---

## Common Patterns

### Block Dangerous Files (PreToolUse)

```python
#!/usr/bin/env python3
import json, sys

data = json.load(sys.stdin)
path = data.get('tool_input', {}).get('file_path', '')

BLOCKED = ['.env', 'secrets.json', '.git/']
if any(b in path for b in BLOCKED):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked: {path} is protected"
        }
    }))
else:
    print('{}')
```

### Auto-Format Files (PostToolUse)

```bash
#!/bin/bash
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ "$FILE" == *.ts ]] || [[ "$FILE" == *.tsx ]]; then
  npx prettier --write "$FILE" 2>/dev/null
fi

echo '{}'
```

### Inject Git Context (UserPromptSubmit)

```bash
#!/bin/bash
echo "Git status:"
git status --short 2>/dev/null || echo "(not a git repo)"
echo ""
echo "Recent commits:"
git log --oneline -5 2>/dev/null || echo "(no commits)"
```

### Force Test Verification (Stop)

```python
#!/usr/bin/env python3
import json, sys, subprocess

data = json.load(sys.stdin)

# Prevent infinite loops
if data.get('stop_hook_active'):
    print('{}')
    sys.exit(0)

# Check if tests pass
result = subprocess.run(['npm', 'test'], capture_output=True)
if result.returncode != 0:
    print(json.dumps({
        "decision": "block",
        "reason": "Tests are failing. Please fix before stopping."
    }))
else:
    print('{}')
```

---

## Debugging Checklist

- [ ] Hook registered in settings.json?
- [ ] Shell script has `+x` permission?
- [ ] Bundle rebuilt after TS changes?
- [ ] Using `tool_response` not `tool_result`?
- [ ] Output is valid JSON (or plain text)?
- [ ] Checking `stop_hook_active` in Stop hooks?
- [ ] Using `$CLAUDE_PROJECT_DIR` for paths?

---

## Key Learnings from Past Sessions

1. **Field names matter** - `tool_response` not `tool_result`
2. **Output format** - `decision: "block"` + `reason` for blocking
3. **Exit code 2** - stderr goes to Claude/user, stdout IGNORED
4. **Rebuild bundles** - TypeScript source edits don't auto-apply
5. **Test manually** - `echo '{}' | ./hook.sh` before relying on it
6. **Check outputs first** - `ls .claude/cache/` before editing code
7. **Detached spawn hides errors** - add logging to debug

## See Also

- `/debug-hooks` - Systematic debugging workflow
- `.claude/rules/hooks.md` - Hook development rules

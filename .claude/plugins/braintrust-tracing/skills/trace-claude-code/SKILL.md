---
name: trace-claude-code
description: |
  Automatically trace Claude Code conversations to Braintrust for observability.
  Captures sessions, conversation turns, and tool calls as hierarchical traces.
version: 1.1.0
---

# Trace Claude Code to Braintrust

Automatically send Claude Code conversations to Braintrust for tracing and observability. Get full visibility into your AI coding sessions with hierarchical traces showing sessions, turns, and every tool call.

## What you get

```
Claude Code Session (root trace)
├── Turn 1: "Add error handling"
│   ├── Read: src/app.ts
│   ├── Edit: src/app.ts
│   └── Response: "I've added try-catch..."
├── Turn 2: "Now run the tests"
│   ├── Terminal: npm test
│   └── Response: "All tests pass..."
└── Turn 3: "Great, commit this"
    ├── Terminal: git add .
    ├── Terminal: git commit -m "..."
    └── Response: "Changes committed..."
```

## How it works

Four hooks capture the complete workflow:

| Hook | What it captures |
|------|------------------|
| **SessionStart** | Creates root trace when you start Claude Code |
| **PostToolUse** | Captures every tool call (file reads, edits, terminal commands) |
| **Stop** | Captures conversation turns (your message + Claude's response) |
| **SessionEnd** | Logs session summary when you exit |

## Quick setup

Run the setup script in any project directory where you want tracing:

```bash
bash /path/to/skills/trace-claude-code/setup.sh
```

The script prompts for your API key and project name, then configures all hooks automatically.

## Manual setup

### Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed
- [Braintrust API key](https://www.braintrust.dev/app/settings/api-keys)
- `jq` command-line tool (`brew install jq` on macOS)

### Configuration

Create `.claude/settings.local.json` in your project directory:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash /path/to/hooks/session_start.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash /path/to/hooks/post_tool_use.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash /path/to/hooks/stop_hook.sh"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash /path/to/hooks/session_end.sh"
          }
        ]
      }
    ]
  },
  "env": {
    "TRACE_TO_BRAINTRUST": "true",
    "BRAINTRUST_API_KEY": "sk-...",
    "BRAINTRUST_CC_PROJECT": "my-project"
  }
}
```

Replace `/path/to/hooks/` with the actual path to this skill's hooks directory.

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TRACE_TO_BRAINTRUST` | Yes | Set to `"true"` to enable tracing |
| `BRAINTRUST_API_KEY` | Yes | Your Braintrust API key |
| `BRAINTRUST_CC_PROJECT` | No | Project name (default: `claude-code`) |
| `BRAINTRUST_CC_DEBUG` | No | Set to `"true"` for verbose logging |

## Viewing traces

After running Claude Code with tracing enabled:

1. Go to [braintrust.dev](https://www.braintrust.dev)
2. Navigate to your project (e.g., `claude-code`)
3. Click **Logs** to see all traced sessions

Each trace shows:
- **Session root**: The overall Claude Code session
- **Turns**: Each conversation exchange (user input → assistant response)
- **Tool calls**: Individual operations (file reads, edits, terminal commands)

## Trace structure

Traces are hierarchical:

- **Session** (root span)
  - `span_attributes.type`: `"task"`
  - `metadata.session_id`: Unique session identifier
  - `metadata.workspace`: Project directory

- **Turn** (child of session)
  - `span_attributes.type`: `"llm"`
  - `input`: User message
  - `output`: Assistant response
  - `metadata.turn_number`: Sequential turn number

- **Tool call** (child of turn or session)
  - `span_attributes.type`: `"tool"`
  - `input`: Tool input (file path, command, etc.)
  - `output`: Tool result
  - `metadata.tool_name`: Name of the tool used

## Troubleshooting

### No traces appearing

1. **Check hooks are running:**
   ```bash
   tail -f ~/.claude/state/braintrust_hook.log
   ```

2. **Verify environment variables** in `.claude/settings.local.json`:
   - `TRACE_TO_BRAINTRUST` must be `"true"`
   - `BRAINTRUST_API_KEY` must be valid

3. **Enable debug mode:**
   ```json
   {
     "env": {
       "BRAINTRUST_CC_DEBUG": "true"
     }
   }
   ```

### Permission errors

Make hook scripts executable:

```bash
chmod +x /path/to/hooks/*.sh
```

### Missing jq command

Install jq:
- **macOS**: `brew install jq`
- **Ubuntu/Debian**: `sudo apt-get install jq`

### State issues

Reset the tracing state:

```bash
rm ~/.claude/state/braintrust_state.json
```

### Hook logs

View detailed hook execution logs:

```bash
# Follow logs in real-time
tail -f ~/.claude/state/braintrust_hook.log

# View last 50 lines
tail -50 ~/.claude/state/braintrust_hook.log

# Clear logs
> ~/.claude/state/braintrust_hook.log
```

## File structure

```
hooks/
├── common.sh          # Shared utilities (logging, API, state)
├── session_start.sh   # Creates root trace span
├── post_tool_use.sh   # Captures tool calls
├── stop_hook.sh       # Captures conversation turns
└── session_end.sh     # Finalizes trace
```

## Alternative: SDK integration

For programmatic use with the Claude Agent SDK, use the native Braintrust integration:

```typescript
import { initLogger, wrapClaudeAgentSDK } from "braintrust";
import * as claudeSDK from "@anthropic-ai/claude-agent-sdk";

initLogger({
  projectName: "my-project",
  apiKey: process.env.BRAINTRUST_API_KEY,
});

const { query, tool } = wrapClaudeAgentSDK(claudeSDK);
```

See [Braintrust Claude Agent SDK docs](https://www.braintrust.dev/docs/integrations/sdk-integrations/claude-agent-sdk) for details.

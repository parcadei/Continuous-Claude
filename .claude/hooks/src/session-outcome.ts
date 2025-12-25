import * as fs from 'fs';
import * as path from 'path';

interface SessionEndInput {
  session_id: string;
  transcript_path: string;
  reason: 'clear' | 'logout' | 'prompt_input_exit' | 'other';
}

interface HookOutput {
  result: "continue";
  message?: string;
}

async function readStdin(): Promise<string> {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
  });
}

async function main() {
  const input: SessionEndInput = JSON.parse(await readStdin());
  const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();

  // Only prompt on user-initiated session end, not auto-compaction
  if (input.reason === 'other') {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }

  // Check if Artifact Index database exists
  const dbPath = path.join(projectDir, '.claude', 'cache', 'context-graph', 'context.db');
  const dbExists = fs.existsSync(dbPath);

  if (!dbExists) {
    // Database doesn't exist yet, skip outcome marking
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }

  // Find most recent handoff to mark
  const ledgerFiles = fs.readdirSync(projectDir)
    .filter(f => f.startsWith('CONTINUITY_CLAUDE-') && f.endsWith('.md'))
    .sort((a, b) => {
      const statA = fs.statSync(path.join(projectDir, a));
      const statB = fs.statSync(path.join(projectDir, b));
      return statB.mtime.getTime() - statA.mtime.getTime();
    });

  if (ledgerFiles.length === 0) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }

  const sessionName = ledgerFiles[0]
    .replace('CONTINUITY_CLAUDE-', '')
    .replace('.md', '');

  // Check for handoffs in this session
  const handoffDir = path.join(projectDir, 'thoughts', 'handoffs', sessionName);
  if (!fs.existsSync(handoffDir)) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }

  const handoffFiles = fs.readdirSync(handoffDir)
    .filter(f => f.startsWith('task-') && f.endsWith('.md'))
    .sort((a, b) => {
      const statA = fs.statSync(path.join(handoffDir, a));
      const statB = fs.statSync(path.join(handoffDir, b));
      return statB.mtime.getTime() - statA.mtime.getTime();
    });

  if (handoffFiles.length === 0) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }

  const latestHandoff = handoffFiles[0];

  // Extract handoff ID from database (would need to query DB, but for simplicity
  // we'll just construct the message with session/task info)
  const taskMatch = latestHandoff.match(/task-(\d+)/);
  const taskNumber = taskMatch ? taskMatch[1] : '??';

  const output: HookOutput = {
    result: "continue",
    message: `

─────────────────────────────────────────────────
Session ended: ${sessionName}
Latest handoff: task-${taskNumber}

To mark outcome and improve future sessions:

  uv run python scripts/context_graph_mark.py \\
    --handoff <handoff-id> \\
    --outcome SUCCEEDED|PARTIAL_PLUS|PARTIAL_MINUS|FAILED

To find handoff ID, query the database:

  sqlite3 .claude/cache/context-graph/context.db \\
    "SELECT id, session_name, task_number, task_summary FROM handoffs WHERE session_name='${sessionName}' ORDER BY indexed_at DESC LIMIT 1"

Outcome meanings:
  SUCCEEDED      - Task completed successfully
  PARTIAL_PLUS   - Mostly done, minor issues remain
  PARTIAL_MINUS  - Some progress, major issues remain
  FAILED         - Task abandoned or blocked
─────────────────────────────────────────────────
`
  };

  console.log(JSON.stringify(output));
}

main().catch(console.error);

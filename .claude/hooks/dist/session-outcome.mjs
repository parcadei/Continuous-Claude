// src/session-outcome.ts
import * as fs from "fs";
import * as path from "path";
async function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.on("data", (chunk) => data += chunk);
    process.stdin.on("end", () => resolve(data));
  });
}
async function main() {
  const input = JSON.parse(await readStdin());
  const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  if (input.reason === "other") {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }
  const dbPath = path.join(projectDir, ".claude", "cache", "context-graph", "context.db");
  const dbExists = fs.existsSync(dbPath);
  if (!dbExists) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }
  const ledgerFiles = fs.readdirSync(projectDir).filter((f) => f.startsWith("CONTINUITY_CLAUDE-") && f.endsWith(".md")).sort((a, b) => {
    const statA = fs.statSync(path.join(projectDir, a));
    const statB = fs.statSync(path.join(projectDir, b));
    return statB.mtime.getTime() - statA.mtime.getTime();
  });
  if (ledgerFiles.length === 0) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }
  const sessionName = ledgerFiles[0].replace("CONTINUITY_CLAUDE-", "").replace(".md", "");
  const handoffDir = path.join(projectDir, "thoughts", "handoffs", sessionName);
  if (!fs.existsSync(handoffDir)) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }
  const handoffFiles = fs.readdirSync(handoffDir).filter((f) => f.startsWith("task-") && f.endsWith(".md")).sort((a, b) => {
    const statA = fs.statSync(path.join(handoffDir, a));
    const statB = fs.statSync(path.join(handoffDir, b));
    return statB.mtime.getTime() - statA.mtime.getTime();
  });
  if (handoffFiles.length === 0) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }
  const latestHandoff = handoffFiles[0];
  const taskMatch = latestHandoff.match(/task-(\d+)/);
  const taskNumber = taskMatch ? taskMatch[1] : "??";
  const output = {
    result: "continue",
    message: `

\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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
\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
`
  };
  console.log(JSON.stringify(output));
}
main().catch(console.error);

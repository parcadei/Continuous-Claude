// src/session-start-continuity.ts
import * as fs from "fs";
import * as path from "path";
import { execSync } from "child_process";
function getLatestHandoff(handoffDir) {
  if (!fs.existsSync(handoffDir)) return null;
  const handoffFiles = fs.readdirSync(handoffDir).filter((f) => (f.startsWith("task-") || f.startsWith("auto-handoff-")) && f.endsWith(".md")).sort((a, b) => {
    const statA = fs.statSync(path.join(handoffDir, a));
    const statB = fs.statSync(path.join(handoffDir, b));
    return statB.mtime.getTime() - statA.mtime.getTime();
  });
  if (handoffFiles.length === 0) return null;
  const latestFile = handoffFiles[0];
  const content = fs.readFileSync(path.join(handoffDir, latestFile), "utf-8");
  const isAutoHandoff = latestFile.startsWith("auto-handoff-");
  let taskNumber;
  let status;
  let summary;
  if (isAutoHandoff) {
    const typeMatch = content.match(/type:\s*auto-handoff/i);
    status = typeMatch ? "auto-handoff" : "unknown";
    const timestampMatch = latestFile.match(/auto-handoff-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})/);
    taskNumber = timestampMatch ? timestampMatch[1] : "auto";
    const inProgressMatch = content.match(/## In Progress\n([\s\S]*?)(?=\n## |$)/);
    summary = inProgressMatch ? inProgressMatch[1].trim().split("\n").slice(0, 3).join("; ").substring(0, 150) : "Auto-handoff from pre-compact";
  } else {
    const taskMatch = latestFile.match(/task-(\d+)/);
    taskNumber = taskMatch ? taskMatch[1] : "??";
    const statusMatch = content.match(/status:\s*(success|partial|blocked)/i);
    status = statusMatch ? statusMatch[1] : "unknown";
    const summaryMatch = content.match(/## What Was Done\n([\s\S]*?)(?=\n## |$)/);
    summary = summaryMatch ? summaryMatch[1].trim().split("\n").slice(0, 2).join("; ").substring(0, 150) : "No summary available";
  }
  return {
    filename: latestFile,
    taskNumber,
    status,
    summary,
    isAutoHandoff
  };
}
function getUnmarkedHandoffs() {
  try {
    const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
    const dbPath = path.join(projectDir, ".claude", "cache", "artifact-index", "context.db");
    if (!fs.existsSync(dbPath)) {
      return [];
    }
    const result = execSync(
      `sqlite3 "${dbPath}" "SELECT id, session_name, task_number, task_summary FROM handoffs WHERE outcome = 'UNKNOWN' ORDER BY indexed_at DESC LIMIT 5"`,
      { encoding: "utf-8", timeout: 3e3 }
    );
    if (!result.trim()) {
      return [];
    }
    return result.trim().split("\n").map((line) => {
      const [id, session_name, task_number, task_summary] = line.split("|");
      return { id, session_name, task_number: task_number || null, task_summary: task_summary || "" };
    });
  } catch (error) {
    return [];
  }
}
async function main() {
  const input = JSON.parse(await readStdin());
  const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const sessionType = input.source || input.type;
  const ledgerDir = path.join(projectDir, "thoughts", "ledgers");
  if (!fs.existsSync(ledgerDir)) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }
  const ledgerFiles = fs.readdirSync(ledgerDir).filter((f) => f.startsWith("CONTINUITY_CLAUDE-") && f.endsWith(".md")).sort((a, b) => {
    const statA = fs.statSync(path.join(ledgerDir, a));
    const statB = fs.statSync(path.join(ledgerDir, b));
    return statB.mtime.getTime() - statA.mtime.getTime();
  });
  let message = "";
  let additionalContext = "";
  if (ledgerFiles.length > 0) {
    const mostRecent = ledgerFiles[0];
    const ledgerPath = path.join(ledgerDir, mostRecent);
    const ledgerContent = fs.readFileSync(ledgerPath, "utf-8");
    const goalMatch = ledgerContent.match(/## Goal\n([\s\S]*?)(?=\n## |$)/);
    const nowMatch = ledgerContent.match(/- Now: ([^\n]+)/);
    const goalSummary = goalMatch ? goalMatch[1].trim().split("\n")[0].substring(0, 100) : "No goal found";
    const currentFocus = nowMatch ? nowMatch[1].trim() : "Unknown";
    const sessionName = mostRecent.replace("CONTINUITY_CLAUDE-", "").replace(".md", "");
    const handoffDir = path.join(projectDir, "thoughts", "shared", "handoffs", sessionName);
    const latestHandoff = getLatestHandoff(handoffDir);
    if (sessionType === "startup") {
      let startupMsg = `\u{1F4CB} Ledger available: ${sessionName} \u2192 ${currentFocus}`;
      if (latestHandoff) {
        if (latestHandoff.isAutoHandoff) {
          startupMsg += ` | Last handoff: auto (${latestHandoff.status})`;
        } else {
          startupMsg += ` | Last handoff: task-${latestHandoff.taskNumber} (${latestHandoff.status})`;
        }
      }
      startupMsg += " (run /resume_handoff to continue)";
      message = startupMsg;
    } else {
      console.error(`\u2713 Ledger loaded: ${sessionName} \u2192 ${currentFocus}`);
      message = `[${sessionType}] Loaded: ${mostRecent} | Goal: ${goalSummary} | Focus: ${currentFocus}`;
      if (sessionType === "clear" || sessionType === "compact") {
        additionalContext = `Continuity ledger loaded from ${mostRecent}:

${ledgerContent}`;
        const unmarkedHandoffs = getUnmarkedHandoffs();
        if (unmarkedHandoffs.length > 0) {
          additionalContext += `

---

## Unmarked Session Outcomes

`;
          additionalContext += `The following handoffs have no outcome marked. Consider marking them to improve future session recommendations:

`;
          for (const h of unmarkedHandoffs) {
            const taskLabel = h.task_number ? `task-${h.task_number}` : "handoff";
            const summaryPreview = h.task_summary ? h.task_summary.substring(0, 60) + "..." : "(no summary)";
            additionalContext += `- **${h.session_name}/${taskLabel}** (ID: \`${h.id.substring(0, 8)}\`): ${summaryPreview}
`;
          }
          additionalContext += `
To mark an outcome:
\`\`\`bash
uv run python scripts/context_graph_mark.py --handoff <ID> --outcome SUCCEEDED|PARTIAL_PLUS|PARTIAL_MINUS|FAILED
\`\`\`
`;
        }
        if (latestHandoff) {
          const handoffPath = path.join(handoffDir, latestHandoff.filename);
          const handoffContent = fs.readFileSync(handoffPath, "utf-8");
          const handoffLabel = latestHandoff.isAutoHandoff ? "Latest auto-handoff" : "Latest task handoff";
          additionalContext += `

---

${handoffLabel} (${latestHandoff.filename}):
`;
          additionalContext += `Status: ${latestHandoff.status}${latestHandoff.isAutoHandoff ? "" : ` | Task: ${latestHandoff.taskNumber}`}

`;
          const truncatedHandoff = handoffContent.length > 2e3 ? handoffContent.substring(0, 2e3) + "\n\n[... truncated, read full file if needed]" : handoffContent;
          additionalContext += truncatedHandoff;
          const allHandoffs = fs.readdirSync(handoffDir).filter((f) => (f.startsWith("task-") || f.startsWith("auto-handoff-")) && f.endsWith(".md")).sort((a, b) => {
            const statA = fs.statSync(path.join(handoffDir, a));
            const statB = fs.statSync(path.join(handoffDir, b));
            return statB.mtime.getTime() - statA.mtime.getTime();
          });
          if (allHandoffs.length > 1) {
            additionalContext += `

---

All handoffs in ${handoffDir}:
`;
            allHandoffs.forEach((f) => {
              additionalContext += `- ${f}
`;
            });
          }
        }
      }
    }
  } else {
    if (sessionType !== "startup") {
      console.error(`\u26A0 No ledger found. Run /continuity_ledger to track session state.`);
      message = `[${sessionType}] No ledger found. Consider running /continuity_ledger to track session state.`;
    }
  }
  const output = { result: "continue" };
  if (message) {
    output.message = message;
    output.systemMessage = message;
  }
  if (additionalContext) {
    output.hookSpecificOutput = {
      hookEventName: "SessionStart",
      additionalContext
    };
  }
  console.log(JSON.stringify(output));
}
async function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.on("data", (chunk) => data += chunk);
    process.stdin.on("end", () => resolve(data));
  });
}
main().catch(console.error);

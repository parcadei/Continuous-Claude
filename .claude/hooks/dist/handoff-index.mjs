// src/handoff-index.ts
import * as fs from "fs";
import * as path from "path";
import { spawn } from "child_process";
async function main() {
  const input = JSON.parse(await readStdin());
  const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const homeDir = process.env.HOME || "";
  if (input.tool_name !== "Write") {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }
  const filePath = input.tool_input?.file_path || "";
  if (!filePath.includes("handoffs") || !filePath.endsWith(".md")) {
    console.log(JSON.stringify({ result: "continue" }));
    return;
  }
  try {
    const fullPath = path.isAbsolute(filePath) ? filePath : path.join(projectDir, filePath);
    if (!fs.existsSync(fullPath)) {
      console.log(JSON.stringify({ result: "continue" }));
      return;
    }
    let content = fs.readFileSync(fullPath, "utf-8");
    let modified = false;
    const hasFrontmatter = content.startsWith("---");
    const hasRootSpanId = content.includes("root_span_id:");
    if (!hasRootSpanId) {
      const stateFile = path.join(homeDir, ".claude", "state", "braintrust_sessions", `${input.session_id}.json`);
      if (fs.existsSync(stateFile)) {
        try {
          const stateContent = fs.readFileSync(stateFile, "utf-8");
          const state = JSON.parse(stateContent);
          const newFields = [
            `root_span_id: ${state.root_span_id}`,
            `turn_span_id: ${state.current_turn_span_id || ""}`,
            `session_id: ${input.session_id}`
          ].join("\n");
          if (hasFrontmatter) {
            content = content.replace(/^---\n/, `---
${newFields}
`);
          } else {
            content = `---
${newFields}
---

${content}`;
          }
          const tempPath = fullPath + ".tmp";
          fs.writeFileSync(tempPath, content);
          fs.renameSync(tempPath, fullPath);
          modified = true;
        } catch (stateErr) {
        }
      }
    }
    const indexScript = path.join(projectDir, "scripts", "context_graph_index.py");
    if (fs.existsSync(indexScript)) {
      const child = spawn("uv", ["run", "python", indexScript, "--file", fullPath], {
        cwd: projectDir,
        detached: true,
        stdio: "ignore"
      });
      child.unref();
    }
    console.log(JSON.stringify({ result: "continue" }));
  } catch (err) {
    console.log(JSON.stringify({ result: "continue" }));
  }
}
async function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.on("data", (chunk) => data += chunk);
    process.stdin.on("end", () => resolve(data));
  });
}
main().catch(console.error);

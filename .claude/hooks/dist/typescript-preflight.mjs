// src/typescript-preflight.ts
import { execSync } from "child_process";
import * as path from "path";
import * as fs from "fs";
function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("readable", () => {
      let chunk;
      while ((chunk = process.stdin.read()) !== null) {
        data += chunk;
      }
    });
    process.stdin.on("end", () => resolve(data));
  });
}
async function main() {
  try {
    const stdinData = await readStdin();
    const input = JSON.parse(stdinData);
    if (input.tool_name !== "Edit" && input.tool_name !== "Write") {
      console.log(JSON.stringify({}));
      return;
    }
    const response = input.tool_response || {};
    const filePath = response.filePath || response.file_path || input.tool_input?.file_path;
    if (!filePath || typeof filePath !== "string") {
      console.log(JSON.stringify({}));
      return;
    }
    if (!filePath.endsWith(".ts") && !filePath.endsWith(".tsx")) {
      console.log(JSON.stringify({}));
      return;
    }
    if (filePath.includes("node_modules") || filePath.includes(".test.")) {
      console.log(JSON.stringify({}));
      return;
    }
    const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
    const homeDir = process.env.HOME || "";
    let scriptPath = path.join(projectDir, "scripts", "typescript_check.py");
    if (!fs.existsSync(scriptPath)) {
      scriptPath = path.join(homeDir, ".claude", "scripts", "typescript_check.py");
    }
    if (!fs.existsSync(scriptPath)) {
      console.log(JSON.stringify({}));
      return;
    }
    try {
      const result = execSync(
        `python3 "${scriptPath}" --file "${filePath}" --json`,
        {
          timeout: 35e3,
          encoding: "utf8",
          stdio: ["pipe", "pipe", "pipe"]
        }
      );
      const checkResult = JSON.parse(result);
      if (checkResult.has_errors) {
        const errorLines = [];
        errorLines.push(`\u26A0\uFE0F TypeScript Pre-flight Check: ${checkResult.summary}`);
        errorLines.push("");
        if (checkResult.tsc_errors?.length > 0) {
          errorLines.push("**Type Errors:**");
          for (const err of checkResult.tsc_errors.slice(0, 5)) {
            errorLines.push(`  ${err}`);
          }
        }
        if (checkResult.qlty_errors?.length > 0) {
          errorLines.push("**Lint Issues:**");
          for (const err of checkResult.qlty_errors.slice(0, 5)) {
            errorLines.push(`  ${err}`);
          }
        }
        errorLines.push("");
        errorLines.push("Fix these errors before proceeding.");
        console.log(JSON.stringify({
          decision: "block",
          reason: errorLines.join("\n")
        }));
        return;
      }
      console.log(JSON.stringify({}));
    } catch (checkError) {
      if (checkError && typeof checkError === "object" && "status" in checkError) {
        const execError = checkError;
        if (execError.stdout) {
          try {
            const checkResult = JSON.parse(execError.stdout);
            if (checkResult.has_errors) {
              console.log(JSON.stringify({
                decision: "block",
                reason: `\u26A0\uFE0F TypeScript Pre-flight: ${checkResult.summary}

Fix before proceeding.`
              }));
              return;
            }
          } catch {
          }
        }
      }
      console.log(JSON.stringify({}));
    }
  } catch (error) {
    console.log(JSON.stringify({}));
  }
}
main();

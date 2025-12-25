/**
 * PostToolUse Hook: TypeScript Pre-flight Check
 *
 * Runs tsc + qlty after Edit/Write on .ts/.tsx files to catch errors immediately.
 * Returns errors as system reminder so Claude can fix before moving on.
 */

import { execSync } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

interface PostToolUseInput {
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_response: {
    filePath?: string;
    file_path?: string;
    content?: string;
    [key: string]: unknown;
  };
}

interface HookOutput {
  decision?: 'block';
  reason?: string;
}

function readStdin(): Promise<string> {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('readable', () => {
      let chunk;
      while ((chunk = process.stdin.read()) !== null) {
        data += chunk;
      }
    });
    process.stdin.on('end', () => resolve(data));
  });
}

async function main() {
  try {
    const stdinData = await readStdin();
    const input: PostToolUseInput = JSON.parse(stdinData);

    // Only process Edit and Write tools
    if (input.tool_name !== 'Edit' && input.tool_name !== 'Write') {
      console.log(JSON.stringify({}));
      return;
    }

    // Get file path from response
    const response = input.tool_response || {};
    const filePath = response.filePath || response.file_path || input.tool_input?.file_path as string;
    if (!filePath || typeof filePath !== 'string') {
      console.log(JSON.stringify({}));
      return;
    }

    // Only process TypeScript files
    if (!filePath.endsWith('.ts') && !filePath.endsWith('.tsx')) {
      console.log(JSON.stringify({}));
      return;
    }

    // Skip node_modules and test files (configurable)
    if (filePath.includes('node_modules') || filePath.includes('.test.')) {
      console.log(JSON.stringify({}));
      return;
    }

    // Find the script - check both project and global locations
    const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
    const homeDir = process.env.HOME || '';

    let scriptPath = path.join(projectDir, 'scripts', 'typescript_check.py');
    if (!fs.existsSync(scriptPath)) {
      scriptPath = path.join(homeDir, '.claude', 'scripts', 'typescript_check.py');
    }
    if (!fs.existsSync(scriptPath)) {
      // Script not available, continue silently
      console.log(JSON.stringify({}));
      return;
    }

    // Run the check script
    try {
      const result = execSync(
        `python3 "${scriptPath}" --file "${filePath}" --json`,
        {
          timeout: 35000,
          encoding: 'utf8',
          stdio: ['pipe', 'pipe', 'pipe']
        }
      );

      const checkResult = JSON.parse(result);

      if (checkResult.has_errors) {
        // Format errors for system reminder
        const errorLines: string[] = [];
        errorLines.push(`⚠️ TypeScript Pre-flight Check: ${checkResult.summary}`);
        errorLines.push('');

        if (checkResult.tsc_errors?.length > 0) {
          errorLines.push('**Type Errors:**');
          for (const err of checkResult.tsc_errors.slice(0, 5)) {
            errorLines.push(`  ${err}`);
          }
        }

        if (checkResult.qlty_errors?.length > 0) {
          errorLines.push('**Lint Issues:**');
          for (const err of checkResult.qlty_errors.slice(0, 5)) {
            errorLines.push(`  ${err}`);
          }
        }

        errorLines.push('');
        errorLines.push('Fix these errors before proceeding.');

        // Use decision: block with reason to make message visible to Claude
        // Since this is PostToolUse, edit already happened - "block" just shows the error
        console.log(JSON.stringify({
          decision: 'block',
          reason: errorLines.join('\n')
        }));
        return;
      }

      // No errors - continue silently
      console.log(JSON.stringify({}));

    } catch (checkError: unknown) {
      // Check script failed - extract stderr if available
      if (checkError && typeof checkError === 'object' && 'status' in checkError) {
        // Non-zero exit means errors found, try to parse stdout
        const execError = checkError as { stdout?: string; stderr?: string };
        if (execError.stdout) {
          try {
            const checkResult = JSON.parse(execError.stdout);
            if (checkResult.has_errors) {
              console.log(JSON.stringify({
                decision: 'block',
                reason: `⚠️ TypeScript Pre-flight: ${checkResult.summary}\n\nFix before proceeding.`
              }));
              return;
            }
          } catch {
            // Couldn't parse, continue
          }
        }
      }
      // Other error, continue silently
      console.log(JSON.stringify({}));
    }

  } catch (error) {
    // Parse error or other issue - don't block
    console.log(JSON.stringify({}));
  }
}

main();

import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';

interface PostToolUseInput {
  session_id: string;
  transcript_path: string;
  cwd: string;
  permission_mode: string;
  hook_event_name: string;
  tool_name: string;
  tool_input: {
    file_path?: string;
    content?: string;
  };
  tool_response: {
    success?: boolean;
    filePath?: string;
  };
  tool_use_id: string;
}

interface BraintrustState {
  root_span_id: string;
  project_id: string;
  current_turn_span_id: string;
  turn_count: string;
}

async function main() {
  const input: PostToolUseInput = JSON.parse(await readStdin());
  const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const homeDir = process.env.HOME || '';

  // Only process Write tool calls
  if (input.tool_name !== 'Write') {
    console.log(JSON.stringify({ result: 'continue' }));
    return;
  }

  const filePath = input.tool_input?.file_path || '';

  // Only process handoff files
  if (!filePath.includes('handoffs') || !filePath.endsWith('.md')) {
    console.log(JSON.stringify({ result: 'continue' }));
    return;
  }

  try {
    const fullPath = path.isAbsolute(filePath) ? filePath : path.join(projectDir, filePath);

    if (!fs.existsSync(fullPath)) {
      console.log(JSON.stringify({ result: 'continue' }));
      return;
    }

    // Read current file content
    let content = fs.readFileSync(fullPath, 'utf-8');
    let modified = false;

    // Check if frontmatter already has root_span_id
    const hasFrontmatter = content.startsWith('---');
    const hasRootSpanId = content.includes('root_span_id:');

    // If missing root_span_id, try to inject it
    if (!hasRootSpanId) {
      // Read Braintrust state file
      const stateFile = path.join(homeDir, '.claude', 'state', 'braintrust_sessions', `${input.session_id}.json`);

      if (fs.existsSync(stateFile)) {
        try {
          const stateContent = fs.readFileSync(stateFile, 'utf-8');
          const state: BraintrustState = JSON.parse(stateContent);

          const newFields = [
            `root_span_id: ${state.root_span_id}`,
            `turn_span_id: ${state.current_turn_span_id || ''}`,
            `session_id: ${input.session_id}`
          ].join('\n');

          if (hasFrontmatter) {
            // Insert after opening ---
            content = content.replace(/^---\n/, `---\n${newFields}\n`);
          } else {
            // Add frontmatter at the start
            content = `---\n${newFields}\n---\n\n${content}`;
          }

          // Write updated content atomically (temp file + rename)
          const tempPath = fullPath + '.tmp';
          fs.writeFileSync(tempPath, content);
          fs.renameSync(tempPath, fullPath);
          modified = true;
        } catch (stateErr) {
          // State file missing or invalid - continue without IDs
        }
      }
    }

    // Always trigger indexing (idempotent, will upsert)
    const indexScript = path.join(projectDir, 'scripts', 'context_graph_index.py');

    if (fs.existsSync(indexScript)) {
      const child = spawn('uv', ['run', 'python', indexScript, '--file', fullPath], {
        cwd: projectDir,
        detached: true,
        stdio: 'ignore'
      });
      child.unref();
    }

    console.log(JSON.stringify({ result: 'continue' }));
  } catch (err) {
    // Don't block on errors
    console.log(JSON.stringify({ result: 'continue' }));
  }
}

async function readStdin(): Promise<string> {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => resolve(data));
  });
}

main().catch(console.error);

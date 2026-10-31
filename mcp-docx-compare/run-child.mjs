// Run one converter/comparer script and kill its WHOLE process tree on timeout.
//
// `execFile(..., {timeout})` sends SIGTERM to the shell script only. The bash
// wrapper is waiting on powershell.exe, has no TERM trap, and its child keeps
// running after the MCP tool has already returned failure -- a late Word/COM
// process can then overwrite the output while a retry is using it. Spawning in
// a new process group lets the timeout kill the group, not just the wrapper.
import { spawn } from 'node:child_process';

export function runFile(file, args, options = {}) {
  const { timeout = 0, maxBuffer = 4 * 1024 * 1024, ...spawnOptions } = options;
  const detached = process.platform !== 'win32';
  return new Promise((resolve, reject) => {
    const child = spawn(file, args, {
      ...spawnOptions,
      detached,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let overflow = '';
    const killGroup = () => {
      try {
        if (detached && child.pid) process.kill(-child.pid, 'SIGKILL');
        else child.kill('SIGKILL');
      } catch {
        // already gone
      }
    };
    // `maxBuffer` is an ERROR budget, not a silent truncation point. The old
    // `take()` stopped appending but let the child finish and resolved with the
    // cut text as success, so a comparer flood lost its diagnostics and the
    // caller could not tell its output was incomplete. This logic is kept
    // identical to mcp-docx-converter/run-child.mjs: the two servers ship the
    // same runner.
    const budget = { stdout: 0, stderr: 0 };
    const append = (stream, chunk) => {
      if (overflow) return;
      const text = String(chunk);
      const bytes = Buffer.byteLength(text, 'utf8');
      if (budget[stream] + bytes > maxBuffer) {
        overflow = `Command output exceeded the ${maxBuffer}-byte buffer and its process `
                 + `group was killed: ${file}`;
        killGroup();
        return;
      }
      budget[stream] += bytes;
      if (stream === 'stdout') stdout += text;
      else stderr += text;
    };
    child.stdout.on('data', (chunk) => append('stdout', chunk));
    child.stderr.on('data', (chunk) => append('stderr', chunk));
    let timer = null;
    if (timeout > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        killGroup();
      }, timeout);
    }
    const finish = (error, result) => {
      if (timer) clearTimeout(timer);
      if (error) reject(error);
      else resolve(result);
    };
    child.on('error', (error) => finish(error));
    child.on('close', (code, signal) => {
      const detail = overflow
        ? overflow
        : timedOut
          ? `Command timed out after ${timeout}ms and its process group was killed: ${file}`
          : `Command failed (code ${code}, signal ${signal || 'none'}): ${file} ${args.join(' ')}`;
      const error = new Error(detail);
      error.code = code;
      error.signal = signal;
      error.stdout = stdout;
      error.stderr = stderr;
      error.killed = timedOut || Boolean(overflow);
      error.overBudget = Boolean(overflow);
      if (overflow || timedOut || code !== 0) finish(error);
      else finish(null, { stdout, stderr });
    });
  });
}

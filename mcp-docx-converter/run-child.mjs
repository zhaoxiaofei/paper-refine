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
    const take = (buffered, chunk) => (
      buffered.length >= maxBuffer ? buffered : buffered + String(chunk)
    );
    child.stdout.on('data', (chunk) => { stdout = take(stdout, chunk); });
    child.stderr.on('data', (chunk) => { stderr = take(stderr, chunk); });
    let timer = null;
    if (timeout > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        try {
          if (detached && child.pid) process.kill(-child.pid, 'SIGKILL');
          else child.kill('SIGKILL');
        } catch {
          // already gone
        }
      }, timeout);
    }
    const finish = (error, result) => {
      if (timer) clearTimeout(timer);
      if (error) reject(error);
      else resolve(result);
    };
    child.on('error', (error) => finish(error));
    child.on('close', (code, signal) => {
      const detail = timedOut
        ? `Command timed out after ${timeout}ms and its process group was killed: ${file}`
        : `Command failed (code ${code}, signal ${signal || 'none'}): ${file} ${args.join(' ')}`;
      const error = new Error(detail);
      error.code = code;
      error.signal = signal;
      error.stdout = stdout;
      error.stderr = stderr;
      error.killed = timedOut;
      if (timedOut || code !== 0) finish(error);
      else finish(null, { stdout, stderr });
    });
  });
}

// Run one converter/comparer script and kill its WHOLE process tree on timeout.
//
// `execFile(..., {timeout})` sends SIGTERM to the shell script only. The bash
// wrapper is waiting on powershell.exe, has no TERM trap, and its child keeps
// running after the MCP tool has already returned failure -- a late Word/COM
// process can then overwrite the output while a retry is using it. Spawning in
// a new process group lets the timeout kill the group, not just the wrapper.
import { spawn, spawnSync } from 'node:child_process';
import { StringDecoder } from 'node:string_decoder';

// Kill the WHOLE process tree `child` started. POSIX uses a new process group;
// Windows cannot (`detached` is false there), and `child.kill` reaches only the
// bash wrapper, leaving powershell.exe/Word/COM alive to overwrite the output of
// a retry. `taskkill /T /F` on the wrapper pid kills that tree. Kept identical
// to mcp-docx-converter/run-child.mjs; the runners are injected so the
// behaviour is testable without starting Word.
export function killProcessTree(child, options = {}) {
  const platform = options.platform || process.platform;
  const detached = options.detached !== undefined ? options.detached : platform !== 'win32';
  const run = options.spawnSync || spawnSync;
  const kill = options.kill || process.kill;
  const pid = child && child.pid;
  try {
    if (platform === 'win32' && pid) {
      let taskkill = null;
      try {
        taskkill = run('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore' });
      } catch (err) {
        taskkill = { error: err };
      }
      if (taskkill && taskkill.status === 0) return { ok: true };
      // taskkill is unavailable, was denied, or the pid was a wrapper that had
      // already exited: the documented WHOLE-TREE kill did NOT run. Fall back
      // to the wrapper handle and a PowerShell force-stop, and record the
      // failure so the caller's timeout error can name it.
      const notes = [];
      if (child && typeof child.kill === 'function') {
        try {
          child.kill('SIGKILL');
          notes.push('child.kill sent');
        } catch {
          notes.push('child.kill failed');
        }
      }
      try {
        const ps = run('powershell', ['-NoProfile', '-NonInteractive', '-Command',
          `Stop-Process -Id ${pid} -Force -ErrorAction SilentlyContinue`],
          { stdio: 'ignore' });
        notes.push(ps && ps.status === 0
          ? 'PowerShell Stop-Process sent'
          : 'PowerShell Stop-Process failed');
      } catch {
        notes.push('PowerShell unavailable');
      }
      const why = taskkill && taskkill.error
        ? (taskkill.error.message || String(taskkill.error))
        : `status ${taskkill ? taskkill.status : 'none'}`;
      const detail = `taskkill /T /F failed for pid ${pid} (${why}); ${notes.join('; ')}`;
      if (child && typeof child === 'object') child.treeKillError = detail;
      return { ok: false, error: detail };
    }
    if (detached && pid) {
      kill(-pid, 'SIGKILL');
      return { ok: true };
    }
    if (child && typeof child.kill === 'function') child.kill('SIGKILL');
    return { ok: true };
  } catch (err) {
    const detail = String((err && err.message) || err);
    if (child && typeof child === 'object') child.treeKillError = detail;
    return { ok: false, error: detail };
  }
}

export function runFile(file, args, options = {}) {
  const { timeout = 0, maxBuffer = 4 * 1024 * 1024, killGraceMs = 5000,
    killTree = killProcessTree, ...spawnOptions } = options;
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
    let treeKillError = '';
    const killGroup = () => {
      try {
        const result = killTree(child, { detached });
        if (result && result.error) treeKillError = result.error;
      } catch (err) {
        treeKillError = String((err && err.message) || err);
      }
    };
    // `maxBuffer` is an ERROR budget, not a silent truncation point. The old
    // `take()` stopped appending but let the child finish and resolved with the
    // cut text as success, so a comparer flood lost its diagnostics and the
    // caller could not tell its output was incomplete. This logic is kept
    // identical to mcp-docx-converter/run-child.mjs: the two servers ship the
    // same runner.
    const budget = { stdout: 0, stderr: 0 };
    // A Buffer chunk is not a character: a multibyte UTF-8 sequence can be
    // split across two 'data' events, and `String(chunk)` then decodes each
    // half to U+FFFD. Decode each stream with a StringDecoder (which buffers an
    // incomplete sequence) and count the RAW bytes against the budget. Kept
    // identical to mcp-docx-converter/run-child.mjs.
    const decoders = {
      stdout: new StringDecoder('utf8'),
      stderr: new StringDecoder('utf8'),
    };
    const append = (stream, chunk) => {
      if (overflow) return;
      const bytes = chunk.length;
      if (budget[stream] + bytes > maxBuffer) {
        // Kill first: `treeKillError` is assigned by killGroup(), so composing
        // the error before the call can never name a failed overflow kill.
        killGroup();
        overflow = `Command output exceeded the ${maxBuffer}-byte buffer and its process `
                 + `group was killed: ${file}`
                 + (treeKillError ? ` (tree kill incomplete: ${treeKillError})` : '');
        return;
      }
      budget[stream] += bytes;
      const text = decoders[stream].write(chunk);
      if (stream === 'stdout') stdout += text;
      else stderr += text;
    };
    child.stdout.on('data', (chunk) => append('stdout', chunk));
    child.stderr.on('data', (chunk) => append('stderr', chunk));
    let timer = null;
    let graceTimer = null;
    let settled = false;
    if (timeout > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        killGroup();
        // A failed tree kill leaves the child (and its pipes) alive, so no
        // 'close' event may ever arrive and this promise would stay pending
        // forever past its deadline. Arm a short grace period that settles the
        // call with the recorded tree-kill failure (F038).
        graceTimer = setTimeout(() => {
          if (settled) return;
          const detail = `Command timed out after ${timeout}ms and its process group could `
            + `not be confirmed dead: ${file}`
            + (treeKillError ? ` (tree kill incomplete: ${treeKillError})` : '');
          const error = new Error(detail);
          error.code = null;
          error.signal = null;
          error.stdout = stdout;
          error.stderr = stderr;
          error.killed = true;
          error.overBudget = false;
          finish(error);
        }, killGraceMs);
        if (typeof graceTimer.unref === 'function') graceTimer.unref();
      }, timeout);
    }
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (graceTimer) clearTimeout(graceTimer);
      if (error) reject(error);
      else resolve(result);
    };
    child.on('error', (error) => finish(error));
    child.on('close', (code, signal) => {
      // Flush a trailing partial sequence (a decoder may still hold bytes).
      for (const stream of ['stdout', 'stderr']) {
        const tail = decoders[stream].end();
        if (!tail) continue;
        if (stream === 'stdout') stdout += tail;
        else stderr += tail;
      }
      const detail = overflow
        ? overflow
        : timedOut
          ? `Command timed out after ${timeout}ms and its process group was killed: ${file}`
          + (treeKillError ? ` (tree kill incomplete: ${treeKillError})` : '')
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

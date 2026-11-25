// Run one converter/comparer script and kill its WHOLE process tree on timeout.
//
// `execFile(..., {timeout})` sends SIGTERM to the shell script only. The bash
// wrapper is waiting on powershell.exe, has no TERM trap, and its child keeps
// running after the MCP tool has already returned failure -- a late Word/COM
// process can then overwrite the output while a retry is using it. Spawning in
// a new process group lets the timeout kill the group, not just the wrapper.
import { spawn, spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { StringDecoder } from 'node:string_decoder';

/** True on WSL (Linux userland, Windows interop), where the POSIX group kill
 * does not reach the Windows powershell.exe/Word process the script started. */
export function isWsl(platform = process.platform) {
  if (platform !== 'linux') return false;
  if (process.env.WSL_DISTRO_NAME || process.env.WSL_INTEROP) return true;
  try {
    return /microsoft|wsl/i.test(readFileSync('/proc/sys/kernel/osrelease', 'utf8'));
  } catch {
    return false;
  }
}

/** The Windows pids the child recorded (one per line/space). */
function windowsPids(file) {
  if (!file) return [];
  let text = '';
  try {
    text = readFileSync(file, 'utf8');
  } catch {
    return [];
  }
  const seen = new Set();
  for (const part of text.split(/\s+/)) {
    const n = Number(part);
    if (Number.isInteger(n) && n > 0 && n < 2 ** 32) seen.add(n);
  }
  return [...seen];
}

// Kill the WHOLE process tree `child` started. POSIX uses a new process group;
// Windows cannot (`detached` is false there), and `child.kill` reaches only the
// bash wrapper, leaving powershell.exe/Word/COM alive to overwrite the output of
// a retry. `taskkill /T /F` on the wrapper pid kills that tree. The runners are
// injected so the behaviour is testable without starting Word.
export function killProcessTree(child, options = {}) {
  const platform = options.platform || process.platform;
  const detached = options.detached !== undefined ? options.detached : platform !== 'win32';
  const run = options.spawnSync || spawnSync;
  const kill = options.kill || process.kill;
  const wsl = options.wsl !== undefined
    ? options.wsl
    : platform === 'linux' && isWsl(platform);
  const pid = child && child.pid;
  try {
    if (platform === 'win32' && pid) {
      let taskkill = null;
      try {
        taskkill = run('taskkill', ['/pid', String(pid), '/T', '/F'],
                          { stdio: 'ignore', timeout: 15000 });
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
          { stdio: 'ignore', timeout: 15000 });
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
      if (!wsl) {
        kill(-pid, 'SIGKILL');
        return { ok: true };
      }
      // WSL interop: the Unix process group does not contain the Windows
      // powershell.exe, and Word is launched by COM outside both groups. The
      // wrapper records those Windows pids; kill the Unix group first, then
      // taskkill.exe every recorded Windows pid. 128 is taskkill's "process
      // not found" (it already died with its group), which is success here.
      let groupError = '';
      try {
        kill(-pid, 'SIGKILL');
      } catch (err) {
        groupError = String((err && err.message) || err);
      }
      const pidFile = options.windowsPidFile
                    || (child && child.windowsPidFile);
      const pids = windowsPids(pidFile);
      const failures = [];
      for (const wp of pids) {
        let result = null;
        try {
          result = run('taskkill.exe', ['/PID', String(wp), '/T', '/F'],
                       { stdio: 'ignore', timeout: 15000 });
        } catch (err) {
          failures.push(`taskkill.exe /PID ${wp} failed `
                        + `(${(err && err.message) || err})`);
          continue;
        }
        if (result && (result.status === 0 || result.status === 128)) continue;
        const why = result && result.error
          ? (result.error.message || String(result.error))
          : `status ${result ? result.status : 'none'}`;
        failures.push(`taskkill.exe /PID ${wp} failed (${why})`);
      }
      if (failures.length) {
        const detail = failures.join('; ');
        if (child && typeof child === 'object') child.treeKillError = detail;
        return { ok: false, error: detail };
      }
      if (groupError) {
        const detail = `process-group kill failed (${groupError})`;
        if (child && typeof child === 'object') child.treeKillError = detail;
        return { ok: false, error: detail };
      }
      if (pidFile && pids.length === 0) {
        // A pid file was requested but held nothing: either the wrapper had
        // not recorded the Windows pids yet or the read failed, so the
        // taskkill half of the tree kill did not run. Reporting {ok:true} told
        // the caller the tree was dead when Word/COM could still be alive
        // (F045); name the gap so the timeout says the kill is incomplete.
        const detail = `no Windows pids recorded in ${pidFile}; `
                     + 'the Windows tree kill could not run';
        if (child && typeof child === 'object') child.treeKillError = detail;
        return { ok: false, error: detail };
      }
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

const _ACTIVE_CHILDREN = new Set();


export function killAllChildren() {
  // F042: the Python driver must be able to stop the server's Word/COM tree.
  // A SIGTERM handler (index.js) calls this before exiting, so a group kill of
  // the node server does not orphan the bash -> PowerShell -> Word chain.
  for (const child of [..._ACTIVE_CHILDREN]) {
    try {
      const opts = child._killOptions || {};
      (child._killTree || killProcessTree)(child, opts);
    } catch { /* best effort */ }
  }
}

export function runFile(file, args, options = {}) {
  const { timeout = 0, maxBuffer = 4 * 1024 * 1024, killGraceMs = 5000,
    killTree = killProcessTree, windowsPidFile = '', ...spawnOptions } = options;
  const detached = process.platform !== 'win32';
  // The wrapper records its Windows pids here; the timeout path reads the same
  // path back. The caller places the file beside the output (a path both WSL
  // and Windows can write) and removes it after the run.
  const env = windowsPidFile
    ? { ...(spawnOptions.env || process.env),
        DOCX_MCP_WINDOWS_PID_FILE: windowsPidFile }
    : spawnOptions.env;
  return new Promise((resolve, reject) => {
    const child = spawn(file, args, {
      ...spawnOptions,
      env,
      detached,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    if (windowsPidFile) child.windowsPidFile = windowsPidFile;
    _ACTIVE_CHILDREN.add(child);
    child._killOptions = { detached, windowsPidFile };
    child._killTree = killTree;
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let overflow = '';
    let treeKillError = '';
    const killGroup = () => {
      try {
        const result = killTree(child, { detached, windowsPidFile });
        if (result && result.error) treeKillError = result.error;
      } catch (err) {
        treeKillError = String((err && err.message) || err);
      }
    };
    // `maxBuffer` is an ERROR budget, not a silent truncation point. The old
    // `take()` stopped appending but let the child finish and resolved with the
    // cut text as success, so a converter flood lost its diagnostics and the
    // caller could not tell its output was incomplete.
    const budget = { stdout: 0, stderr: 0 };
    // A Buffer chunk is not a character: a multibyte UTF-8 sequence can be
    // split across two 'data' events, and `String(chunk)` then decodes each
    // half to U+FFFD. Decode each stream with a StringDecoder (which buffers an
    // incomplete sequence) and count the RAW bytes against the budget.
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
        // The SAME failed-kill hazard as the timeout path: if the tree kill did
        // not take, the child can hold its pipes open and no 'close' event ever
        // arrives. Arm the bounded grace timer here too, so an overflow settles.
        graceTimer = setTimeout(() => {
          if (settled) return;
          const error = new Error(overflow);
          error.code = null;
          error.signal = null;
          error.stdout = stdout;
          error.stderr = stderr;
          error.killed = true;
          error.overBudget = true;
          finish(error);
        }, killGraceMs);
        if (typeof graceTimer.unref === 'function') graceTimer.unref();
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
      _ACTIVE_CHILDREN.delete(child);
      if (timer) clearTimeout(timer);
      if (graceTimer) clearTimeout(graceTimer);
      // A grace-timer settle means the tree kill was not confirmed and the
      // child may still be running: no 'close' event will ever come to release
      // its two pipe fds, so every failed kill leaked fds (and the child) in
      // this long-lived server (F047). Destroy the pipes, drop our listeners
      // and unref the child. The no-op 'error' listener keeps a late stream
      // error from becoming an uncaught exception.
      for (const stream of [child.stdout, child.stderr]) {
        if (!stream) continue;
        try { stream.removeAllListeners('data'); } catch { /* ignore */ }
        try { stream.destroy(); } catch { /* ignore */ }
      }
      try { child.removeAllListeners('close'); } catch { /* ignore */ }
      try { child.removeAllListeners('error'); } catch { /* ignore */ }
      try { child.on('error', () => {}); } catch { /* ignore */ }
      if (typeof child.unref === 'function') child.unref();
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

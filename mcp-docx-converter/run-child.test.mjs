// Hermetic test for the Windows process-tree kill in run-child.mjs.
//   node run-child.test.mjs
// Needs no npm install and never starts Word/COM: the tree kill is injected.
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import * as runner from './run-child.mjs';

const fails = [];
function check(name, fn) {
  try {
    fn();
    console.log(`OK ${name}`);
  } catch (err) {
    fails.push(`${name}: ${err.message}`);
    console.log(`FAIL ${name}: ${err.message}`);
  }
}

check('run-child exports the testable tree killer', () => {
  assert.equal(typeof runner.killProcessTree, 'function');
});

if (typeof runner.killProcessTree === 'function') {
  check('Windows uses taskkill /T /F on the wrapper pid', () => {
    const calls = [];
    const kills = [];
    runner.killProcessTree(
      { pid: 1234, kill: (sig) => kills.push(sig) },
      { platform: 'win32', detached: false,
        spawnSync: (file, args, opts) => {
          calls.push({ file, args, opts });
          return { status: 0 };
        } },
    );
    assert.equal(calls.length, 1);
    assert.equal(calls[0].file, 'taskkill');
    assert.deepEqual(calls[0].args, ['/pid', '1234', '/T', '/F']);
    assert.deepEqual(kills, [], 'the wrapper-only child.kill must not be the Windows path');
  });

  check('Windows falls back when taskkill fails, and records the failure', () => {
    const calls = [];
    const kills = [];
    const child = { pid: 4321, kill: (sig) => kills.push(sig) };
    const result = runner.killProcessTree(child, {
      platform: 'win32', detached: false,
      spawnSync: (file, args, opts) => {
        calls.push({ file, args, opts });
        return file === 'taskkill' ? { status: 1 } : { status: 0 };
      },
    });
    assert.equal(calls.length, 2, 'the PowerShell fallback must be attempted');
    assert.equal(calls[1].file, 'powershell');
    assert.match(calls[1].args.join(' '), /Stop-Process -Id 4321 -Force/);
    assert.deepEqual(kills, ['SIGKILL'], 'the wrapper handle is still killed');
    assert.equal(result.ok, false);
    assert.match(result.error, /taskkill \/T \/F failed for pid 4321/);
    assert.match(child.treeKillError, /taskkill \/T \/F failed/);
  });

  check('Windows still falls back when taskkill throws', () => {
    const kills = [];
    const child = { pid: 7, kill: (sig) => kills.push(sig) };
    const result = runner.killProcessTree(child, {
      platform: 'win32', detached: false,
      spawnSync: (file) => {
        if (file === 'taskkill') throw new Error('ENOENT');
        return { status: 0 };
      },
    });
    assert.deepEqual(kills, ['SIGKILL']);
    assert.match(result.error, /ENOENT/);
  });

  check('POSIX detached kills the whole process group', () => {
    const killed = [];
    let wrapperKilled = false;
    runner.killProcessTree(
      { pid: 77, kill: () => { wrapperKilled = true; } },
      { platform: 'linux', detached: true,
        kill: (pid, sig) => killed.push([pid, sig]) },
    );
    assert.deepEqual(killed, [[-77, 'SIGKILL']]);
    assert.equal(wrapperKilled, false);
  });

  check('POSIX non-detached falls back to the child', () => {
    const kills = [];
    runner.killProcessTree(
      { pid: 5, kill: (sig) => kills.push(sig) },
      { platform: 'darwin', detached: false, kill: () => { throw new Error('no group'); } },
    );
    assert.deepEqual(kills, ['SIGKILL']);
  });

  check('an already-gone process never throws', () => {
    runner.killProcessTree(
      { pid: 9, kill: () => { throw new Error('gone'); } },
      { platform: 'linux', detached: true, kill: () => { throw new Error('gone'); } },
    );
  });

  check('WSL taskkills every recorded Windows pid after the group kill', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'run-child-'));
    const pidfile = path.join(dir, 'winpids');
    writeFileSync(pidfile, '111\n222\n');
    const calls = [];
    try {
      const result = runner.killProcessTree(
        { pid: 33, kill: () => {} },
        { platform: 'linux', detached: true, wsl: true, windowsPidFile: pidfile,
          kill: (pid, sig) => calls.push(['kill', pid, sig]),
          spawnSync: (file, args) => {
            calls.push([file, ...args]);
            return { status: 0 };
          } },
      );
      assert.deepEqual(calls[0], ['kill', -33, 'SIGKILL']);
      assert.deepEqual(calls.slice(1), [
        ['taskkill.exe', '/PID', '111', '/T', '/F'],
        ['taskkill.exe', '/PID', '222', '/T', '/F'],
      ]);
      assert.equal(result.ok, true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  check('WSL treats taskkill 128 (already gone) as success', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'run-child-'));
    const pidfile = path.join(dir, 'winpids');
    writeFileSync(pidfile, '7\n');
    try {
      const result = runner.killProcessTree(
        { pid: 1, kill: () => {} },
        { platform: 'linux', detached: true, wsl: true, windowsPidFile: pidfile,
          kill: () => {}, spawnSync: () => ({ status: 128 }) },
      );
      assert.equal(result.ok, true, 'a process that already died is not a failure');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  check('WSL records a taskkill failure so the timeout can name it', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'run-child-'));
    const pidfile = path.join(dir, 'winpids');
    writeFileSync(pidfile, '9\n');
    const child = { pid: 1, kill: () => {} };
    try {
      const result = runner.killProcessTree(child, {
        platform: 'linux', detached: true, wsl: true, windowsPidFile: pidfile,
        kill: () => {}, spawnSync: () => ({ status: 1 }),
      });
      assert.equal(result.ok, false);
      assert.match(result.error, /taskkill\.exe \/PID 9 failed/);
      assert.match(child.treeKillError, /taskkill\.exe \/PID 9 failed/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  check('plain Unix does not invoke Windows taskkill', () => {
    const calls = [];
    runner.killProcessTree(
      { pid: 44, kill: () => {} },
      { platform: 'linux', detached: true, wsl: false,
        windowsPidFile: '/does/not/exist',
        kill: (pid, sig) => calls.push(['kill', pid, sig]),
        spawnSync: (file) => { calls.push(['spawn', file]); return { status: 0 }; } },
    );
    assert.deepEqual(calls, [['kill', -44, 'SIGKILL']]);
  });

  check('isWsl is a boolean predicate', () => {
    assert.equal(typeof runner.isWsl, 'function');
    assert.equal(typeof runner.isWsl(), 'boolean');
  });
}

// R02: an overflow whose process-group kill fails must name the failure, just
// as the timeout path does. `killTree` is injectable for the same reason
// `killProcessTree` takes its runners: the check is hermetic and never touches
// a real process tree.
if (typeof runner.runFile === 'function') {
  try {
    await runner.runFile(
      process.execPath,
      ['-e', "process.stdout.write('x'.repeat(4096)); process.exit(0);"],
      { maxBuffer: 256,
        killTree: () => ({ ok: false, error: 'simulated taskkill denial' }) },
    );
    fails.push('overflow with a failing kill: runFile resolved instead of rejecting');
    console.log('FAIL overflow with a failing kill names the tree-kill failure');
  } catch (err) {
    try {
      assert.match(err.message, /tree kill incomplete: simulated taskkill denial/);
      console.log('OK overflow with a failing kill names the tree-kill failure');
    } catch (assertErr) {
      fails.push(`overflow with a failing kill: ${assertErr.message}`);
      console.log(`FAIL overflow with a failing kill: ${assertErr.message}`);
    }
  }
}

// F038: a timeout whose tree kill FAILS must still settle. Without the grace
// timer the promise waited for a 'close' event that a surviving child never
// sends -- the MCP tool hung past its budget. The injected killer leaves the
// child alive, and the child exits on its own well after the grace period.
if (typeof runner.runFile === 'function') {
  const started = Date.now();
  try {
    await runner.runFile(
      process.execPath,
      ['-e', "setTimeout(() => process.exit(0), 1200);"],
      { timeout: 30, killGraceMs: 100,
        killTree: () => ({ ok: false, error: 'simulated denial' }) },
    );
    fails.push('timeout with a failing kill: runFile resolved instead of rejecting');
    console.log('FAIL timeout with a failing kill settles with an error');
  } catch (err) {
    try {
      assert.match(err.message, /could not be confirmed dead/);
      assert.match(err.message, /tree kill incomplete: simulated denial/);
      assert.ok(Date.now() - started < 900, 'the grace timer must settle before the child exits');
      console.log('OK timeout with a failing kill settles with an error');
    } catch (assertErr) {
      fails.push(`timeout with a failing kill: ${assertErr.message}`);
      console.log(`FAIL timeout with a failing kill: ${assertErr.message}`);
    }
  }
}


if (typeof runner.runFile === 'function') {
  const dir = mkdtempSync(path.join(tmpdir(), 'run-child-env-'));
  const pidfile = path.join(dir, 'pids');
  try {
    const { stdout } = await runner.runFile(
      process.execPath,
      ['-e', "process.stdout.write(process.env.DOCX_MCP_WINDOWS_PID_FILE || '')"],
      { windowsPidFile: pidfile, timeout: 10000 },
    );
    if (stdout === pidfile) {
      console.log('OK runFile hands the Windows pid file to the child');
    } else {
      fails.push(`runFile Windows pid file: ${stdout}`);
      console.log(`FAIL runFile hands the Windows pid file to the child (${stdout})`);
    }
  } catch (err) {
    fails.push(`runFile Windows pid file: ${err.message}`);
    console.log(`FAIL runFile hands the Windows pid file to the child: ${err.message}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

if (fails.length) {
  console.log(`\n${fails.length} run-child check(s) FAILED`);
  process.exit(1);
}
console.log('\nAll run-child checks PASSED');

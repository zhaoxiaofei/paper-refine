// Hermetic test for the Windows process-tree kill in run-child.mjs.
//   node run-child.test.mjs
// Needs no npm install and never starts Word/COM: the tree kill is injected.
import assert from 'node:assert/strict';
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

if (fails.length) {
  console.log(`\n${fails.length} run-child check(s) FAILED`);
  process.exit(1);
}
console.log('\nAll run-child checks PASSED');

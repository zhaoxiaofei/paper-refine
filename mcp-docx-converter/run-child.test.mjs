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
        spawnSync: (file, args, opts) => calls.push({ file, args, opts }) },
    );
    assert.equal(calls.length, 1);
    assert.equal(calls[0].file, 'taskkill');
    assert.deepEqual(calls[0].args, ['/pid', '1234', '/T', '/F']);
    assert.deepEqual(kills, [], 'the wrapper-only child.kill must not be the Windows path');
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

if (fails.length) {
  console.log(`\n${fails.length} run-child check(s) FAILED`);
  process.exit(1);
}
console.log('\nAll run-child checks PASSED');

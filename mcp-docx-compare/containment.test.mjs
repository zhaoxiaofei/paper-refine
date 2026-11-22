// Hermetic test for the DOCX_MCP_ALLOWED_ROOTS containment rule.
//   node containment.test.mjs
// Needs no npm install: the module under test imports node: core only.
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync,
         writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { allowedRoots, containsPath, containedSpawnPath,
         stageContainedInput } from './containment.mjs';

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

const work = mkdtempSync(path.join(tmpdir(), 'docx-containment-'));
const root = path.join(work, 'allowed');
const outside = path.join(work, 'outside');
const stage = path.join(work, 'stage');
mkdirSync(root);
mkdirSync(outside);
mkdirSync(stage, { mode: 0o700 });
const insideDoc = path.join(root, 'inside.docx');
writeFileSync(insideDoc, 'x');
const outsideDoc = path.join(outside, 'secret.docx');
writeFileSync(outsideDoc, 'x');
const link = path.join(root, 'link.docx');
symlinkSync(outsideDoc, link);
const rootLink = path.join(work, 'allowed-link');
symlinkSync(root, rootLink);

try {
  check('an unset root list allows anything', () => {
    assert.equal(containsPath(outsideDoc, allowedRoots('')), true);
  });
  check('a file inside the allowed root is allowed', () => {
    assert.equal(containsPath(insideDoc, allowedRoots(root)), true);
  });
  check('a file outside the allowed root is refused', () => {
    assert.equal(containsPath(outsideDoc, allowedRoots(root)), false);
  });
  check('a sibling directory sharing the prefix is refused', () => {
    const sibling = `${root}-extra`;
    mkdirSync(sibling);
    assert.equal(containsPath(path.join(sibling, 'x.docx'), allowedRoots(root)), false);
  });
  check('the LEXICAL check would have allowed the symlink (the bug)', () => {
    const abs = path.resolve(link);
    assert.ok(abs === root || abs.startsWith(root + path.sep),
              'fixture does not reproduce the lexical bypass');
  });
  check('a symlink inside the root pointing outside is refused', () => {
    assert.equal(containsPath(link, allowedRoots(root)), false);
  });
  check('a root given as a symlink still allows its real subtree', () => {
    assert.equal(containsPath(insideDoc, allowedRoots(rootLink)), true);
  });
  const outLinkDir = path.join(root, 'outdir');
  symlinkSync(outside, outLinkDir);
  check('a not-yet-existing OUTPUT under a symlinked directory is refused', () => {
    const out = path.join(outLinkDir, 'new-redline.docx');
    assert.equal(existsSync(out), false, 'fixture output already exists');
    assert.equal(containsPath(out, allowedRoots(root)), false);
  });
  check('a not-yet-existing output under a REAL directory is allowed', () => {
    const out = path.join(root, 'new-redline.docx');
    assert.equal(containsPath(out, allowedRoots(root)), true);
  });
  check('the spawn-time recheck says an unset root list is off (lexical)', () => {
    assert.equal(containedSpawnPath(insideDoc, allowedRoots('')), path.resolve(insideDoc));
  });
  check('the spawn-time recheck refreshes the real path of an allowed file', () => {
    assert.equal(containedSpawnPath(insideDoc, allowedRoots(root)),
                 path.resolve(insideDoc));
  });
  check('the spawn-time recheck refuses a path swapped for an outside symlink', () => {
    const swap = path.join(root, 'swap.docx');
    writeFileSync(swap, 'x');
    assert.equal(containsPath(swap, allowedRoots(root)), true);
    // The check-then-spawn window: the checked regular file is replaced by a
    // symlink pointing outside the root BEFORE the child would open it.
    rmSync(swap);
    symlinkSync(outsideDoc, swap);
    assert.throws(() => containedSpawnPath(swap, allowedRoots(root)),
                  /outside DOCX_MCP_ALLOWED_ROOTS/);
  });
  check('the spawn-time recheck refuses a dangling-symlink output', () => {
    const dead = path.join(root, 'dead.docx');
    symlinkSync(path.join(outside, 'missing.docx'), dead);
    assert.throws(() => containedSpawnPath(dead, allowedRoots(root)),
                  /dangling symlink/);
  });
  check('the spawn-time stage copies an allowed file into the private dir', () => {
    const dest = stageContainedInput(insideDoc, allowedRoots(root), stage, 'copy.docx');
    assert.ok(dest.startsWith(stage + path.sep), `copy landed at ${dest}`);
    assert.equal(readFileSync(dest, 'utf8'), 'x');
  });
  check('a symlink to an INSIDE file is staged from its target', () => {
    const alias = path.join(root, 'alias-inside.docx');
    symlinkSync(insideDoc, alias);
    const dest = stageContainedInput(alias, allowedRoots(root), stage, 'alias.docx');
    assert.equal(readFileSync(dest, 'utf8'), 'x');
  });
  check('a post-check swap cannot change what the staged copy reads', () => {
    const victim = path.join(root, 'victim.docx');
    const secret = path.join(outside, 'secret.docx');
    writeFileSync(victim, 'INSIDE-CONTENT');
    writeFileSync(secret, 'SECRET-OUTSIDE');
    // The server validated the file; the child would open this string later.
    const dest = stageContainedInput(victim, allowedRoots(root), stage, 'victim.docx');
    rmSync(victim);
    symlinkSync(secret, victim);
    assert.equal(readFileSync(dest, 'utf8'), 'INSIDE-CONTENT',
                 'the staged copy must keep the validated bytes');
    // A swap that happens BEFORE the staging open is refused, not followed.
    assert.throws(() => stageContainedInput(victim, allowedRoots(root), stage,
                                            'victim-2.docx'),
                  /outside DOCX_MCP_ALLOWED_ROOTS|symlink/);
  });
  check('a set-but-empty root list fails closed instead of allowing anything', () => {
    assert.throws(() => allowedRoots(path.delimiter), /names no roots/);
    assert.throws(() => allowedRoots(` ${path.delimiter} `), /names no roots/);
  });
  check('a PATH-delimiter separated list keeps every root', () => {
    assert.equal(allowedRoots([root, outside].join(path.delimiter)).length, 2);
  });
  check('a "/" root allows any absolute path (the allow-everything spelling)', () => {
    const roots = allowedRoots(path.sep);
    assert.deepEqual(roots, [path.sep]);
    assert.equal(containsPath('/etc/passwd', roots), true);
    assert.equal(containsPath(work, roots), true);
  });
} finally {
  rmSync(work, { recursive: true, force: true });
}

if (fails.length) {
  console.log(`\n${fails.length} containment check(s) FAILED`);
  for (const f of fails) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('\nAll containment checks PASSED');

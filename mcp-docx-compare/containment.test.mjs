// Hermetic test for the DOCX_MCP_ALLOWED_ROOTS containment rule.
//   node containment.test.mjs
// Needs no npm install: the module under test imports node: core only.
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { allowedRoots, containsPath } from './containment.mjs';

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
mkdirSync(root);
mkdirSync(outside);
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
  check('a PATH-delimiter separated list keeps every root', () => {
    assert.equal(allowedRoots([root, outside].join(path.delimiter)).length, 2);
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

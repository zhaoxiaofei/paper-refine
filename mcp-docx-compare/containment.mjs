// Containment for the optional DOCX_MCP_ALLOWED_ROOTS restriction.
//
// A lexical prefix check on `path.resolve()` is NOT containment: the docx path
// only has to LOOK like it lives under an allowed root, so a symlink placed
// inside the root (`<root>/x.docx -> /etc/secret.docx`) passes the string test
// while `execFile` opens the target outside the root. Both sides are therefore
// resolved with `realpath` before the comparison. Kept dependency-free (node:
// core only) so the rule is unit-testable without the MCP SDK installed.
import { lstatSync, realpathSync } from 'node:fs';
import * as path from 'node:path';

function realOrResolved(p) {
  // A path that does not exist yet (the redline OUTPUT, above all) must still
  // be resolved through its deepest EXISTING ancestor: `realpathSync` alone
  // fails on it and the lexical fallback would let a symlinked directory inside
  // an allowed root smuggle the write outside it. A root that does not exist
  // keeps its resolved shape, and a component that cannot be resolved at all
  // (broken link, racing delete) keeps the lexical shape too.
  const abs = path.resolve(p);
  const tail = [];
  for (let head = abs; ; ) {
    try {
      const real = realpathSync(head);
      return tail.length ? path.join(real, ...tail) : real;
    } catch {
      const parent = path.dirname(head);
      if (parent === head) return abs;
      tail.unshift(path.basename(head));
      head = parent;
    }
  }
}

/** The allowed roots from DOCX_MCP_ALLOWED_ROOTS (PATH-delimiter separated). */
export function allowedRoots(value) {
  return String(value || '')
    .split(path.delimiter)
    .filter(Boolean)
    .map((r) => realOrResolved(r));
}

function hasDanglingSymlink(p) {
  // `realOrResolved` falls back to the lexical path when a component cannot be
  // resolved. For a DANGLING symlink that fallback is exactly the bypass: the
  // path looks inside the root, but the first write follows the link outside
  // it. Walk the existing components and refuse the path when a link on it has
  // no target.
  const abs = path.resolve(p);
  let cur = path.sep;
  for (const part of abs.split(path.sep).filter(Boolean)) {
    cur = path.join(cur, part);
    try {
      if (lstatSync(cur).isSymbolicLink()) {
        try {
          realpathSync(cur);
        } catch {
          return true;
        }
      }
    } catch {
      return false;             // a component that does not exist yet
    }
  }
  return false;
}

/** True when `target` is under one of `roots` (an empty list allows anything). */
export function containsPath(target, roots) {
  if (!roots || !roots.length) return true;
  if (hasDanglingSymlink(target)) return false;
  const abs = realOrResolved(target);
  // A root that already ENDS with the separator is the filesystem root: adding
  // another one turned "/" into "//", which no absolute path starts with, so
  // the "allow everything" spelling DOCX_MCP_ALLOWED_ROOTS=/ refused every file.
  return roots.some((r) => abs === r
    || abs.startsWith(r.endsWith(path.sep) ? r : r + path.sep));
}

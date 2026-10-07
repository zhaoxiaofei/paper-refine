// Containment for the optional DOCX_MCP_ALLOWED_ROOTS restriction.
//
// A lexical prefix check on `path.resolve()` is NOT containment: the docx path
// only has to LOOK like it lives under an allowed root, so a symlink placed
// inside the root (`<root>/x.docx -> /etc/secret.docx`) passes the string test
// while `execFile` opens the target outside the root. Both sides are therefore
// resolved with `realpath` before the comparison. Kept dependency-free (node:
// core only) so the rule is unit-testable without the MCP SDK installed.
import { realpathSync } from 'node:fs';
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

/** True when `target` is under one of `roots` (an empty list allows anything). */
export function containsPath(target, roots) {
  if (!roots || !roots.length) return true;
  const abs = realOrResolved(target);
  return roots.some((r) => abs === r || abs.startsWith(r + path.sep));
}

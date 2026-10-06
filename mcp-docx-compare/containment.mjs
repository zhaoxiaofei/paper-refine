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
  try {
    return realpathSync(p);
  } catch {
    // A root that does not exist yet keeps its resolved shape; a TARGET that
    // cannot be resolved (broken link, racing delete) also falls back, and the
    // caller refuses it anyway when it is not under a real root.
    return path.resolve(p);
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

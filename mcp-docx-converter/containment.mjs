// Containment for the optional DOCX_MCP_ALLOWED_ROOTS restriction.
//
// A lexical prefix check on `path.resolve()` is NOT containment: the docx path
// only has to LOOK like it lives under an allowed root, so a symlink placed
// inside the root (`<root>/x.docx -> /etc/secret.docx`) passes the string test
// while `execFile` opens the target outside the root. Both sides are therefore
// resolved with `realpath` before the comparison. Kept dependency-free (node:
// core only) so the rule is unit-testable without the MCP SDK installed.
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync,
         realpathSync, statSync, writeSync } from 'node:fs';
import * as path from 'node:path';

export function realOrResolved(p) {
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
  const raw = String(value ?? '');
  if (raw === '') return [];        // unset: containment is deliberately off
  const roots = raw
    .split(path.delimiter)
    .map((r) => r.trim())
    .filter(Boolean)
    .map((r) => {
      // A FILE accepted as an allowed "root" disabled the write containment:
      // the derived PDF beside it landed outside the intended tree (F148).
      const real = realOrResolved(r);
      let st = null;
      try { st = statSync(real); } catch { st = null; }
      if (!st || !st.isDirectory()) {
        throw new Error(`DOCX_MCP_ALLOWED_ROOTS entry is not an existing `
                        + `directory: ${r}`);
      }
      return real;
    });
  if (!roots.length) {
    // Set but carrying only delimiters/whitespace. `containsPath` used to read
    // the empty list as "allow anything", so a malformed value silently
    // disabled containment; fail closed instead.
    throw new Error('DOCX_MCP_ALLOWED_ROOTS is set but names no roots; unset it to '
                    + 'disable containment or name at least one root');
  }
  return roots;
}

function hasDanglingSymlink(p) {
  // `realOrResolved` falls back to the lexical path when a component cannot be
  // resolved. For a DANGLING symlink that fallback is exactly the bypass: the
  // path looks inside the root, but the first write follows the link outside
  // it. Walk the existing components and refuse the path when a link on it has
  // no target.
  const abs = path.resolve(p);
  // Start at the path's ROOT (POSIX "/" or a Windows drive/UNC root) and join
  // only the remainder. Seeding the walk at `path.sep` and then feeding it the
  // drive component produced a path like "\C:" on win32, which lstat throws on,
  // so the walk returned false for EVERY Windows path and the dangling-link
  // check never fired (F038).
  const root = path.parse(abs).root;
  let cur = root;
  for (const part of abs.slice(root.length).split(path.sep).filter(Boolean)) {
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

function isInside(abs, roots) {
  // A root that already ENDS with the separator is the filesystem root: adding
  // another one turned "/" into "//", which no absolute path starts with, so
  // the "allow everything" spelling DOCX_MCP_ALLOWED_ROOTS=/ refused every file.
  return roots.some((r) => abs === r
    || abs.startsWith(r.endsWith(path.sep) ? r : r + path.sep));
}

/** True when `target` is under one of `roots` (an empty list = variable unset). */
export function containsPath(target, roots) {
  if (!roots || !roots.length) return true;
  if (hasDanglingSymlink(target)) return false;
  return isInside(realOrResolved(target), roots);
}

/** True when post-run cleanup may delete a stray file at `target`.
 *
 * A final-component SYMLINK may always be unlinked: removing the link never
 * touches its target. A REGULAR file is deletable only when its parent still
 * resolves inside `roots`: when a directory component was swapped for an
 * outside symlink, `lstatSync(target).isFile()` is true for the OUTSIDE file
 * and an unconditional `rmSync` destroys a file the tool refused to write
 * (F010). `roots` unset keeps the historical cleanup behaviour.
 */
export function strayRemovalAllowed(target, roots) {
  try {
    if (lstatSync(target).isSymbolicLink()) return true;
    if (!lstatSync(target).isFile()) return false;
    return containsPath(path.dirname(target), roots);
  } catch {
    return false;
  }
}


/** Re-resolve an EXACT path immediately before it is handed to the child.
 *
 * The containment checks run on the request, then the comparer/converter opens
 * the path in a separate process. A path swapped for a symlink in that window
 * escaped the root. This helper re-runs the resolution on the string that is
 * about to become argv, so the child receives the REAL path that was just
 * re-validated (and a swap is refused instead of followed). `roots` empty means
 * containment is off and the lexical path is returned.
 */
export function containedSpawnPath(target, roots) {
  const abs = path.resolve(target);
  if (!roots || !roots.length) return abs;
  if (hasDanglingSymlink(abs)) {
    throw new Error(`${abs} is a dangling symlink (it escapes DOCX_MCP_ALLOWED_ROOTS)`);
  }
  const real = realOrResolved(abs);
  if (!isInside(real, roots)) {
    throw new Error(`${abs} is outside DOCX_MCP_ALLOWED_ROOTS`);
  }
  return real;
}

/** Copy a validated input into a PRIVATE staging directory and return that copy.
 *
 * `containedSpawnPath()` still returns a path STRING: after it is re-validated,
 * a writer inside an allowed root can replace the file with a symlink to an
 * outside file, and the child opens the string and follows it (F14). The child
 * must therefore never receive the user's path. This helper opens the validated
 * file ONCE, refuses a swapped-in symlink (O_NOFOLLOW) and a directory-component
 * swap (the opened inode is re-checked through /proc/self/fd on Linux), then
 * copies the bytes READ FROM THAT DESCRIPTOR into a private directory. The child
 * opens the private copy, so a later swap of the original path cannot change
 * what it reads.
 */
export function stageContainedInput(target, roots, stagingDir, name) {
  if (!stagingDir) {
    throw new Error('stageContainedInput requires a private staging directory');
  }
  const real = containedSpawnPath(target, roots);
  let fd;
  try {
    fd = openSync(real, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
  } catch (error) {
    if (error && (error.code === 'ELOOP' || error.code === 'EMLINK')) {
      throw new Error(`${target} is a symlink (it escapes `
                      + `DOCX_MCP_ALLOWED_ROOTS)`);
    }
    throw error;
  }
  try {
    if (!fstatSync(fd).isFile()) {
      throw new Error(`${target} is not a regular file`);
    }
    if (process.platform === 'linux') {
      // The final component is covered by O_NOFOLLOW; a swapped DIRECTORY
      // component is not. /proc/self/fd names the inode the descriptor holds,
      // so re-checking its real path catches the directory swap as well.
      let opened = null;
      try { opened = realpathSync(`/proc/self/fd/${fd}`); } catch { opened = null; }
      if (opened && !isInside(opened, roots)) {
        throw new Error(`${target} changed while it was opened (it escapes `
                        + `DOCX_MCP_ALLOWED_ROOTS)`);
      }
    }
    const dest = path.join(stagingDir, name);
    const out = openSync(dest,
                         constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL,
                         0o600);
    try {
      const buf = Buffer.allocUnsafe(1 << 20);
      for (;;) {
        let n;
        try {
          n = readSync(fd, buf, 0, buf.length, null);
        } catch (error) {
          if (error && error.code === 'EINTR') continue;
          throw error;
        }
        if (n === 0) break;
        let off = 0;
        while (off < n) {
          try {
            off += writeSync(out, buf, off, n - off);
          } catch (error) {
            if (error && error.code === 'EINTR') continue;
            throw error;
          }
        }
      }
    } finally {
      closeSync(out);
    }
    return dest;
  } finally {
    closeSync(fd);
  }
}

// ~/mcp-docx-compare/index.js
//
// The Word-native COMPARE MCP service: `compare_docx(originalPath, revisedPath,
// [outputPath])` drives `docxcompare.sh`, which drives PowerShell, which drives
// `Word.Application.CompareDocuments` through COM automation -- Word's own
// redline engine, the same one behind Review > Compare. The pipeline tries THIS
// server FIRST whenever it has to track the differences between two .docx files
// (`paper_pipeline.redline_one_pair`, tool order `auto`), then falls back to
// python-redlines[docxodus] / docx-trackdiff / --redline-cmd / the built-in
// OOXML writer.
import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import { accessSync, constants, existsSync, lstatSync, mkdtempSync, rmSync, unlinkSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as z from 'zod/v4';
import { allowedRoots, containedSpawnPath, containsPath, realOrResolved,
         strayRemovalAllowed,
         sameFile, stageContainedInput } from './containment.mjs';
import { derivedOutput, inFlightKey } from './derived-output.mjs';

import { isWsl, runFile, killAllChildren } from './run-child.mjs';

// F042: on SIGTERM/SIGINT the server kills its in-flight Word/COM tree
// before exiting, so the Python driver's timeout does not orphan
// bash -> PowerShell -> Word.
const _shutdown = () => {
  try { killAllChildren(); } catch { /* best effort */ }
  process.exit(0);
};
process.on('SIGTERM', _shutdown);
process.on('SIGINT', _shutdown);

// The comparer script is NOT welded to one machine: an explicit env override
// wins, then the repo-relative copy, then a sibling copy, then PATH. A
// candidate that exists but is not executable (a fresh clone tracks
// docxcompare.sh without the executable bit) must not shadow PATH: execFile has
// no shell to fall back on and would fail with EACCES.
function isExecutable(p) {
  try {
    accessSync(p, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function resolveComparer() {
  const candidates = [
    process.env.DOCXCOMPARE_SH,
    fileURLToPath(new URL('../docxcompare.sh', import.meta.url)),
    fileURLToPath(new URL('docxcompare.sh', import.meta.url)),
  ].filter(Boolean);
  for (const c of candidates) {
    if (existsSync(c) && isExecutable(c)) return c;
  }
  return 'docxcompare.sh';                 // let execFile resolve it on PATH
}

const COMPARER = resolveComparer();
// Optional containment: DOCX_MCP_ALLOWED_ROOTS is a PATH-delimiter-separated
// list of roots the tool may read/compare/write. Unset = only the shape checks
// below. The roots (and every requested file, below) are REALPATH-resolved: a
// symlink inside an allowed root must not smuggle a target outside it.
const ALLOWED_ROOTS = allowedRoots(process.env.DOCX_MCP_ALLOWED_ROOTS);
// Concurrent calls for the same output file are serialized, so one call's
// startup cleanup can never delete another call's finished redline.
const inFlight = new Map();

function isDocx(p) {
  return path.extname(p).toLowerCase() === '.docx';
}

// The wrapper records the WINDOWS pids it started here; the timeout path reads
// them back to taskkill a Word/COM server the Unix group kill cannot reach. It
// lives beside the output so both WSL and Windows can reach it; an empty string
// means the normal process-group kill only (non-WSL, or no output yet).
function windowsPidPath(outputPath) {
  if (!outputPath || process.platform !== 'linux' || !isWsl()) return '';
  return `${outputPath}.winpids-${process.pid}-${Date.now().toString(36)}-`
       + Math.random().toString(36).slice(2);
}

serveStdio(() => {
  const server = new McpServer({ name: 'docx-compare', version: '1.0.0' });

  server.registerTool(
    'compare_docx',
    {
      description: '用 Microsoft Word 自带的比较引擎生成两个 DOCX 的修订标记对比文档'
        + '（Word.Application.CompareDocuments，通过 WSL 的 PowerShell COM 自动化）。',
      inputSchema: z.object({
        originalPath: z.string().describe('原始 DOCX 的绝对路径 (WSL 路径, 例如 /mnt/c/Users/...)'),
        revisedPath: z.string().describe('修订 DOCX 的绝对路径 (WSL 路径)'),
        outputPath: z.string().optional().describe(
          '输出 redline DOCX 的绝对路径 (缺省时写到原始文件旁边, 名字为 '
          + '"<original>-vs-<revised>-redline.docx")'),
      }),
    },
    async ({ originalPath, revisedPath, outputPath }) => {
      const inputs = [originalPath, revisedPath];
      for (const p of inputs) {
        if (!path.isAbsolute(p) || !isDocx(p)) {
          return {
            content: [{ type: 'text', text: `refused: every input must be an existing absolute `
                                            + `.docx file: ${p}` }],
            isError: true,
          };
        }
      }
      const absOriginal = path.resolve(originalPath);
      const absRevised = path.resolve(revisedPath);
      // The comparer writes through a symlinked directory to the file's real
      // location; resolve the output through its deepest existing ancestor so
      // the argv, the equality check and the in-flight key all name that one
      // file (`/allowed/out.docx` and `/allowed/link->allowed/out.docx`).
      const absOutput = outputPath ? realOrResolved(outputPath) : '';
      // The existence check is made on the RESOLVED path -- the one execFile
      // opens. `existsSync` on the raw string follows symlinks and `..` through
      // the KERNEL, so `<dir>/link/../../x.docx` can name an existing file
      // while `path.resolve()` of it names another (or none at all): the old
      // check validated one document and handed a DIFFERENT one to the
      // comparer, which is also how the containment rule below got to see a
      // file the run never touched.
      for (const p of [absOriginal, absRevised]) {
        if (!existsSync(p)) {
          return {
            content: [{ type: 'text', text: `refused: every input must be an existing absolute `
                                            + `.docx file: ${p}` }],
            isError: true,
          };
        }
      }
      if (outputPath && (!path.isAbsolute(outputPath) || !isDocx(outputPath))) {
        return {
          content: [{ type: 'text', text: `refused: outputPath must be an absolute .docx path: `
                                          + `${outputPath}` }],
          isError: true,
        };
      }
      for (const p of [...inputs, ...(outputPath ? [outputPath] : [])]) {
        if (!containsPath(p, ALLOWED_ROOTS)) {
          return {
            content: [{ type: 'text', text: `refused: ${p} is outside `
                                            + `DOCX_MCP_ALLOWED_ROOTS` }],
            isError: true,
          };
        }
      }
      // An output that IS an input would replace that input when the script's
      // unique temp is renamed into place; refuse it here too, so the caller
      // gets a clear reason instead of a mysterious COM failure. (The script
      // does not delete the destination up front: it renders to a unique temp
      // and renames on success.) The comparison is made on the REAL paths: a
      // symlinked alias of the input names the same file the rename replaces.
      // Identity, not spelling: on a case-sensitive filesystem `report.docx`
      // and `Report.docx` are two files, and folding case refused the latter
      // as "an input file" (F053). sameFile() compares device+inode when both
      // exist and only folds case on win32 for a not-yet-created output.
      const realInputs = [absOriginal, absRevised].map((p) => realOrResolved(p));
      if (absOutput && realInputs.some((p) => sameFile(absOutput, p))) {
        return {
          content: [{ type: 'text', text: `refused: outputPath must not be an input file: `
                                          + `${outputPath}` }],
          isError: true,
        };
      }
      // The containment checks above judged paths the child has not opened
      // yet. Re-resolving a path is not enough: the result is still a STRING,
      // and a writer inside the root can swap it for an outside symlink between
      // that check and the child's open (F14). When containment is on, the
      // validated inputs are therefore copied into a private staging directory
      // and the child receives THOSE copies; a later swap of the user's path
      // cannot change what it reads. The output is written to the caller's path
      // (the script removes a stale entry and renames its temp into place), and
      // the derived default output is named here because the staged input is
      // not the path the script would derive it from. When containment is unset
      // the lexical paths are kept unchanged.
      let spawnOriginal = absOriginal;
      let spawnRevised = absRevised;
      // Compute the documented DEFAULT output in the non-containment branch
      // too (the converter already does). With containment off, spawnOutput
      // used to stay "" when outputPath was omitted, so windowsPidPath("")
      // returned "" and a WSL timeout killed no Windows pid while reporting
      // the tree kill as successful (F045). derivedOutput() is the same name
      // docxcompare.sh derives.
      let spawnOutput = absOutput || derivedOutput(absOriginal, absRevised);
      let realOriginal = absOriginal;
      let realRevised = absRevised;
      let stagingDir = '';
      if (ALLOWED_ROOTS.length) {
        try {
          realOriginal = containedSpawnPath(absOriginal, ALLOWED_ROOTS);
          realRevised = containedSpawnPath(absRevised, ALLOWED_ROOTS);
          spawnOutput = absOutput
            ? containedSpawnPath(absOutput, ALLOWED_ROOTS)
            : derivedOutput(realOriginal, realRevised);
          // The default output is a write of its own: contain it too.
          spawnOutput = containedSpawnPath(spawnOutput, ALLOWED_ROOTS);
          // The stage must be readable by the WINDOWS child. Its directory is
          // the validated output's directory: Word writes the output there, so
          // that path mapping is known to work (os.tmpdir() is not necessarily
          // shared with Windows on WSL).
          stagingDir = mkdtempSync(path.join(path.dirname(spawnOutput),
                                             '.docx-mcp-compare-'));
          // mkdtemp followed the path string: a directory component swapped
          // after containedSpawnPath() would create the private stage (and the
          // copied manuscripts) outside the roots. Verify where it really is
          // before the child writes there (F046).
          if (!containsPath(stagingDir, ALLOWED_ROOTS)) {
            throw new Error(`the private staging directory ${stagingDir} is outside `
                            + `DOCX_MCP_ALLOWED_ROOTS`);
          }
          spawnOriginal = stageContainedInput(realOriginal, ALLOWED_ROOTS,
                                              stagingDir, 'original.docx');
          spawnRevised = stageContainedInput(realRevised, ALLOWED_ROOTS,
                                             stagingDir, 'revised.docx');
        } catch (error) {
          if (stagingDir) rmSync(stagingDir, { recursive: true, force: true });
          return {
            content: [{ type: 'text', text: `refused: ${error.message}` }],
            isError: true,
          };
        }
        // A racing DELETE between the request check and the spawn must refuse
        // too, not hand a missing path to Word.
        for (const p of [spawnOriginal, spawnRevised]) {
          if (!existsSync(p)) {
            // Every other refusal path removes the staging directory; this one
            // leaked it plus both copied manuscripts (F74).
            if (stagingDir) rmSync(stagingDir, { recursive: true, force: true });
            return {
              content: [{ type: 'text', text: `refused: every input must be an existing `
                                              + `absolute .docx file: ${p}` }],
              isError: true,
            };
          }
        }
      }
      const argv = [spawnOriginal, spawnRevised, ...(spawnOutput ? [spawnOutput] : [])];
      // The server timer must fire BEFORE the caller's deadline: the Python
      // redline budget is 900 s, so an equal server cap let the client kill the
      // server first and skip runFile's WSL taskkill/diagnostics (F043).
      // 870 s leaves 30 s for staging and for the server's own report.
      const windowsPidFile = windowsPidPath(spawnOutput);
      const run = () => runFile(COMPARER, argv,
                                  { timeout: 870_000, maxBuffer: 4 * 1024 * 1024,
                                    windowsPidFile });
      // Key on the REAL destination, not the random staging directory: two
      // revised files that share a basename derive the same redline path, and
      // two concurrent calls for the same input pair must still serialize.
      const key = inFlightKey(realOriginal, realRevised, spawnOutput);
      // See the converter: only a destination that did not exist before the
      // child ran may be removed as its stray write (F046/F010).
      const strayAbsentBeforeRun = !(spawnOutput && existsSync(spawnOutput));
      const previous = inFlight.get(key) ?? Promise.resolve();
      const next = previous.catch(() => {}).then(run);
      inFlight.set(key, next);
      let keepWindowsPidFile = false;
      try {
        const { stdout, stderr } = await next;
        // The child wrote to a path validated before it ran; a writer inside
        // the allowed root can swap a directory component in between and send
        // the write outside DOCX_MCP_ALLOWED_ROOTS. Verify where the output
        // actually landed, remove the stray file, and refuse instead of
        // reporting a contained success (F046). A Node process cannot openat()
        // for the child, so this detection is the enforcement point.
        if (ALLOWED_ROOTS.length && spawnOutput && existsSync(spawnOutput)
            && !containsPath(spawnOutput, ALLOWED_ROOTS)) {
          // Never delete the RESOLVED target of an outside-root symlink: that
          // would remove a file we were refusing to write. Unlink the output
          // path itself (a symlink removal never touches its target), and only
          // remove a regular file when its directory is inside the roots (F022).
          try {
            if (strayRemovalAllowed(spawnOutput, ALLOWED_ROOTS)
                && lstatSync(spawnOutput).isSymbolicLink()) {
              unlinkSync(spawnOutput);
            } else if (strayRemovalAllowed(spawnOutput, ALLOWED_ROOTS)
                       || (strayAbsentBeforeRun && lstatSync(spawnOutput).isFile())) {
              // The child wrote this stray file during THIS call; removing a
              // regular stray path is cleanup. A symlink is unlinked above so
              // its outside TARGET is never deleted (F022). The parent must
              // still resolve inside the roots: when a directory component was
              // swapped for an outside symlink, the final component is a
              // regular OUTSIDE file and rmSync would destroy it (F010).
              rmSync(spawnOutput, { force: true });
            }
          } catch { /* already gone */ }
          return {
            content: [{ type: 'text', text: `refused: the output was written outside `
                                            + `DOCX_MCP_ALLOWED_ROOTS (its path changed during `
                                            + `the run): ${outputPath || spawnOutput}` }],
            isError: true,
          };
        }
        return {
          content: [{
            type: 'text',
            text: `对比文档已生成 (Word 原生修订标记)！输出信息:\n${stdout}\n`
              + `${stderr ? `错误输出:\n${stderr}` : ''}`,
          }],
        };
      } catch (error) {
        // Keep the pid file when the tree kill failed: those Windows pids are
        // still alive and the file is the only record for taskkill (F82).
        keepWindowsPidFile = /tree kill incomplete/.test(String(error.message || ''));
        const pidNote = keepWindowsPidFile && windowsPidFile
          ? `\n[windows pids retained for manual taskkill: ${windowsPidFile}]`
          : '';
        return {
          content: [{
            type: 'text',
            text: `对比失败: ${error.message}\n标准输出: ${error.stdout ?? ''}\n`
              + `标准错误: ${error.stderr ?? ''}${pidNote}`,
          }],
          isError: true,
        };
      } finally {
        if (windowsPidFile && !keepWindowsPidFile) {
          try { rmSync(windowsPidFile, { force: true }); } catch { /* gone */ }
        }
        if (stagingDir) rmSync(stagingDir, { recursive: true, force: true });
        if (inFlight.get(key) === next) inFlight.delete(key);
      }
    }
  );

  return server;
});

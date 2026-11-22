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
import { accessSync, constants, existsSync, mkdtempSync, rmSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as z from 'zod/v4';
import { allowedRoots, containedSpawnPath, containsPath, realOrResolved,
         stageContainedInput } from './containment.mjs';
import { derivedOutput, inFlightKey } from './derived-output.mjs';

import { isWsl, runFile } from './run-child.mjs';

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
      // An output that IS an input would be deleted by the script's
      // stale-output cleanup before Word reads it; refuse it here too, so the
      // caller gets a clear reason instead of a mysterious COM failure. The
      // comparison is made on the REAL paths: a symlinked alias of the input
      // names the same file the cleanup would delete.
      const lc = (s) => s.toLowerCase();
      const realInputs = [absOriginal, absRevised].map((p) => realOrResolved(p));
      if (absOutput && realInputs.some((p) => lc(absOutput) === lc(p))) {
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
      let spawnOutput = absOutput;
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
            return {
              content: [{ type: 'text', text: `refused: every input must be an existing `
                                              + `absolute .docx file: ${p}` }],
              isError: true,
            };
          }
        }
      }
      const argv = [spawnOriginal, spawnRevised, ...(spawnOutput ? [spawnOutput] : [])];
      // 900_000 matches the orchestrator's redline budget
      // (paper_pipeline.render_docx_visual(timeout=900) and the redline chain's
      // own 900s); a smaller server-side cap would kill a slow-but-valid Word
      // comparison before the caller's own timeout and silently downgrade the
      // redline to a lower-fidelity fallback.
      const windowsPidFile = windowsPidPath(spawnOutput);
      const run = () => runFile(COMPARER, argv,
                                  { timeout: 900_000, maxBuffer: 4 * 1024 * 1024,
                                    windowsPidFile });
      // Key on the REAL destination, not the random staging directory: two
      // revised files that share a basename derive the same redline path, and
      // two concurrent calls for the same input pair must still serialize.
      const key = inFlightKey(realOriginal, realRevised, spawnOutput);
      const previous = inFlight.get(key) ?? Promise.resolve();
      const next = previous.catch(() => {}).then(run);
      inFlight.set(key, next);
      try {
        const { stdout, stderr } = await next;
        return {
          content: [{
            type: 'text',
            text: `对比文档已生成 (Word 原生修订标记)！输出信息:\n${stdout}\n`
              + `${stderr ? `错误输出:\n${stderr}` : ''}`,
          }],
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `对比失败: ${error.message}\n标准输出: ${error.stdout ?? ''}\n`
              + `标准错误: ${error.stderr ?? ''}`,
          }],
          isError: true,
        };
      } finally {
        if (windowsPidFile) {
          try { rmSync(windowsPidFile, { force: true }); } catch { /* gone */ }
        }
        if (stagingDir) rmSync(stagingDir, { recursive: true, force: true });
        if (inFlight.get(key) === next) inFlight.delete(key);
      }
    }
  );

  return server;
});

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
import { execFile } from 'node:child_process';
import { accessSync, constants, existsSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import * as z from 'zod/v4';
import { allowedRoots, containsPath, realOrResolved } from './containment.mjs';
import { inFlightKey } from './derived-output.mjs';

const execFileAsync = promisify(execFile);

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
      const argv = [absOriginal, absRevised, ...(absOutput ? [absOutput] : [])];
      // 900_000 matches the orchestrator's redline budget
      // (paper_pipeline.render_docx_visual(timeout=900) and the redline chain's
      // own 900s); a smaller server-side cap would kill a slow-but-valid Word
      // comparison before the caller's own timeout and silently downgrade the
      // redline to a lower-fidelity fallback.
      const run = () => execFileAsync(COMPARER, argv,
                                      { timeout: 900_000, maxBuffer: 4 * 1024 * 1024 });
      // Key on the path the comparer will actually write, not the input pair:
      // two revised files that share a basename derive the same redline path.
      // `inFlightKey` also case-folds it (a case-insensitive destination).
      const key = inFlightKey(absOriginal, absRevised, absOutput);
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
        if (inFlight.get(key) === next) inFlight.delete(key);
      }
    }
  );

  return server;
});

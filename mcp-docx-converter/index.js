// ~/mcp-docx-converter/index.js
import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import { accessSync, constants, existsSync, lstatSync, mkdtempSync, rmSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as z from 'zod/v4';
import { allowedRoots, containedSpawnPath, containsPath, realOrResolved,
         stageContainedInput } from './containment.mjs';
import { pdfKey } from './in-flight.mjs';

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

// The converter script is NOT welded to one machine: an explicit env override
// wins, then the repo-relative copy, then a sibling copy, then PATH. A
// candidate that exists but is not executable (a fresh clone tracks
// docx2pdf.sh without the executable bit) must not shadow PATH: execFile has
// no shell to fall back on and would fail with EACCES.
function isExecutable(p) {
  try {
    accessSync(p, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function resolveConverter() {
  const candidates = [
    process.env.DOCX2PDF_SH,
    fileURLToPath(new URL('../docx2pdf.sh', import.meta.url)),
    fileURLToPath(new URL('docx2pdf.sh', import.meta.url)),
  ].filter(Boolean);
  for (const c of candidates) {
    if (existsSync(c) && isExecutable(c)) return c;
  }
  return 'docx2pdf.sh';                 // let execFile resolve it on PATH
}

const CONVERTER = resolveConverter();
// Optional containment: DOCX_MCP_ALLOWED_ROOTS is a PATH-delimiter-separated
// list of roots the tool may read/convert. Unset = only the shape checks below.
// The roots (and every requested file, below) are REALPATH-resolved: a symlink
// inside an allowed root must not smuggle a target outside it.
const ALLOWED_ROOTS = allowedRoots(process.env.DOCX_MCP_ALLOWED_ROOTS);
// Concurrent calls for the same output PDF are serialized, so one call's
// startup cleanup can never delete another call's finished render.
const inFlight = new Map();

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
  const server = new McpServer({ name: 'docx-converter', version: '1.0.0' });

  server.registerTool(
    'convert_docx_to_pdf',
    {
      description: '将 Word DOCX 文件转换为 PDF。使用 Microsoft Word (通过 WSL 的 PowerShell 互操作) 以获得最高保真度。',
      inputSchema: z.object({
        docxPath: z.string().describe('要转换的 DOCX 文件的绝对路径 (WSL 路径, 例如 /mnt/c/Users/...)'),
      }),
    },
    async ({ docxPath }) => {
      if (!path.isAbsolute(docxPath) || path.extname(docxPath).toLowerCase() !== '.docx') {
        return {
          content: [{ type: 'text', text: `refused: docxPath must be an existing absolute .docx `
                                          + `file: ${docxPath}` }],
          isError: true,
        };
      }
      const abs = path.resolve(docxPath);
      // The existence check is made on the RESOLVED path -- the one the
      // converter opens. `existsSync` on the raw string follows symlinks and
      // `..` through the KERNEL, so a path can name an existing file there and
      // a different (or absent) one here, and the containment rule below would
      // then judge a file the conversion never reads.
      if (!existsSync(abs)) {
        return {
          content: [{ type: 'text', text: `refused: docxPath must be an existing absolute .docx `
                                          + `file: ${abs}` }],
          isError: true,
        };
      }
      if (!containsPath(abs, ALLOWED_ROOTS)) {
        return {
          content: [{ type: 'text', text: `refused: ${abs} is outside `
                                          + `DOCX_MCP_ALLOWED_ROOTS` }],
          isError: true,
        };
      }
      // The containment check above judged a path the converter has not opened
      // yet. Re-resolving that path is not enough: the result is still a
      // STRING, and a writer inside the root can swap it for an outside symlink
      // between the check and the child's open (F14). When containment is on,
      // the validated input is copied into a private staging directory and the
      // child receives THAT copy; the PDF destination is the caller-visible
      // path beside the REAL input, passed explicitly because the staged input
      // is not the path docx2pdf.sh would derive it from.
      let spawnPath = abs;
      let finalPdf = '';
      let stagingDir = '';
      if (ALLOWED_ROOTS.length) {
        try {
          const real = containedSpawnPath(abs, ALLOWED_ROOTS);
          finalPdf = real.replace(/\.docx$/i, '.pdf');
          // The DERIVED PDF is a write, and it must be contained too: checking
          // only the input let an allowed root that was really a file smuggle
          // the output outside it (F148).
          if (!containsPath(finalPdf, ALLOWED_ROOTS)) {
            return {
              content: [{ type: 'text', text: `refused: the derived PDF is outside `
                                              + `DOCX_MCP_ALLOWED_ROOTS` }],
              isError: true,
            };
          }
          // The stage must be readable by the WINDOWS child. Its directory is
          // the validated PDF's directory: Word writes the PDF there, so that
          // path mapping is known to work (os.tmpdir() is not necessarily
          // shared with Windows on WSL).
          stagingDir = mkdtempSync(path.join(path.dirname(finalPdf),
                                             '.docx-mcp-convert-'));
          // mkdtemp followed the path string: a directory component swapped
          // after containedSpawnPath() would create the private stage (and the
          // copied manuscript) outside the roots. Verify where it really is
          // before the child reads the copy and writes the PDF (F046).
          if (!containsPath(stagingDir, ALLOWED_ROOTS)) {
            throw new Error(`the private staging directory ${stagingDir} is outside `
                            + `DOCX_MCP_ALLOWED_ROOTS`);
          }
          spawnPath = stageContainedInput(real, ALLOWED_ROOTS, stagingDir,
                                          'input.docx');
        } catch (error) {
          if (stagingDir) rmSync(stagingDir, { recursive: true, force: true });
          return {
            content: [{ type: 'text', text: `refused: ${error.message}` }],
            isError: true,
          };
        }
        if (!existsSync(spawnPath)) {
          rmSync(stagingDir, { recursive: true, force: true });
          return {
            content: [{ type: 'text', text: `refused: docxPath must be an existing absolute `
                                            + `.docx file: ${spawnPath}` }],
            isError: true,
          };
        }
      }
      // The destination may be case-insensitive; it is computed once.
      const key = finalPdf ? finalPdf.toLowerCase() : pdfKey(spawnPath);
      // The server timer must fire BEFORE the caller's deadline, not after it:
      // the Python caller's 300 s template-render budget used to race a 900 s
      // server cap, so the client killed the server before runFile could run
      // its WSL taskkill/diagnostics and a Word/COM process survived (F043).
      // 240 s leaves the caller 60 s to receive the server's own timeout report.
      const windowsPidFile = windowsPidPath(finalPdf);
      const run = () => runFile(CONVERTER,
                                  finalPdf ? [spawnPath, finalPdf] : [spawnPath],
                                  { timeout: 240_000, maxBuffer: 4 * 1024 * 1024,
                                    windowsPidFile });
      const previous = inFlight.get(key) ?? Promise.resolve();
      const next = previous.catch(() => {}).then(run);
      inFlight.set(key, next);
      try {
        // 调用 docx2pdf.sh 脚本；脚本内部会处理路径转换和 PowerShell 调用。
        const { stdout, stderr } = await next;
        // The child wrote the derived PDF at a path validated before it ran; a
        // writer inside the allowed root can swap a directory component in
        // between and redirect the write outside DOCX_MCP_ALLOWED_ROOTS. Check
        // where the PDF really landed, remove a stray file, and refuse instead
        // of reporting a contained success (F046).
        if (ALLOWED_ROOTS.length && finalPdf && existsSync(finalPdf)
            && !containsPath(finalPdf, ALLOWED_ROOTS)) {
          let stray = '';
          try { stray = realOrResolved(finalPdf); } catch { stray = ''; }
          if (stray) {
            try {
              if (lstatSync(stray).isFile()) rmSync(stray, { force: true });
            } catch { /* already gone */ }
          }
          return {
            content: [{ type: 'text', text: `refused: the PDF was written outside `
                                            + `DOCX_MCP_ALLOWED_ROOTS (its path changed during `
                                            + `the run): ${finalPdf}` }],
            isError: true,
          };
        }
        return {
          content: [{
            type: 'text',
            text: `转换成功！输出信息:\n${stdout}\n${stderr ? `错误输出:\n${stderr}` : ''}`,
          }],
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `转换失败: ${error.message}\n标准输出: ${error.stdout ?? ''}\n` +
                  `标准错误: ${error.stderr ?? ''}`,
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

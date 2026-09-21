// ~/mcp-docx-converter/index.js
import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import * as z from 'zod/v4';

const execFileAsync = promisify(execFile);

// The converter script is NOT welded to one machine: an explicit env override
// wins, then the repo-relative copy, then a sibling copy, then PATH, and the
// historical absolute path remains as a last-resort fallback for the deployed
// ~/mcp-docx-converter layout.
function resolveConverter() {
  const candidates = [
    process.env.DOCX2PDF_SH,
    fileURLToPath(new URL('../docx2pdf.sh', import.meta.url)),
    fileURLToPath(new URL('docx2pdf.sh', import.meta.url)),
    '/home/zhaoxiaofei/.local/bin/docx2pdf.sh',
  ].filter(Boolean);
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return 'docx2pdf.sh';                 // let execFile resolve it on PATH
}

const CONVERTER = resolveConverter();
// Optional containment: DOCX_MCP_ALLOWED_ROOTS is a PATH-delimiter-separated
// list of roots the tool may read/convert. Unset = only the shape checks below.
const ALLOWED_ROOTS = (process.env.DOCX_MCP_ALLOWED_ROOTS || '')
  .split(path.delimiter)
  .filter(Boolean)
  .map((r) => path.resolve(r));
// Concurrent calls for the same output PDF are serialized, so one call's
// startup cleanup can never delete another call's finished render.
const inFlight = new Map();

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
      if (!path.isAbsolute(docxPath) || path.extname(docxPath).toLowerCase() !== '.docx'
          || !existsSync(docxPath)) {
        return {
          content: [{ type: 'text', text: `refused: docxPath must be an existing absolute .docx `
                                          `file: ${docxPath}` }],
          isError: true,
        };
      }
      const abs = path.resolve(docxPath);
      if (ALLOWED_ROOTS.length
          && !ALLOWED_ROOTS.some((r) => abs === r || abs.startsWith(r + path.sep))) {
        return {
          content: [{ type: 'text', text: `refused: ${abs} is outside `
                                          `DOCX_MCP_ALLOWED_ROOTS` }],
          isError: true,
        };
      }
      const pdf = abs.replace(/\.docx$/i, '.pdf');
      const run = () => execFileAsync(CONVERTER, [abs],
                                      { timeout: 180_000, maxBuffer: 4 * 1024 * 1024 });
      const previous = inFlight.get(pdf) ?? Promise.resolve();
      const next = previous.catch(() => {}).then(run);
      inFlight.set(pdf, next);
      try {
        // 调用 docx2pdf.sh 脚本；脚本内部会处理路径转换和 PowerShell 调用。
        const { stdout, stderr } = await next;
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
        if (inFlight.get(pdf) === next) inFlight.delete(pdf);
      }
    }
  );

  return server;
});

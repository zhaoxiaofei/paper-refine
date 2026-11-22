#!/usr/bin/env python3
"""Regression checks for the MCP candidates left unfixed by the 2026-11-22
11:28 fix-bugs wave 1 (wave 2, batch M2).

Run: python3 .paper_test/test_fix_wave2_M2_mcp.py

  F14  the Word child reads a PRIVATE copy of each validated input, so a
       post-check symlink swap can no longer redirect the read outside
       DOCX_MCP_ALLOWED_ROOTS; the child no longer receives the user's path
  F133 on WSL the runner taskkills the Windows pids the wrapper recorded
       (PowerShell and the Word/COM server), because the Unix process group
       kill does not reach them

The node checks are the shipped suites next to the servers; this file also
checks the shell hook that records the Windows pids and the optional explicit
output that lets the converter write beside the real input while Word reads the
staged copy.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def text(rel):
    return (WS / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The shipped node suites
# ---------------------------------------------------------------------------
def test_node_suites():
    print("\n== F14/F133 the shipped node suites ==")
    for rel in ("mcp-docx-compare/containment.test.mjs",
                "mcp-docx-converter/containment.test.mjs"):
        p = subprocess.run(["node", rel.split("/")[-1]], cwd=str(WS / rel.split("/")[0]),
                           capture_output=True, text=True, timeout=180)
        check(f"{rel} passes", p.returncode == 0 and "PASSED" in p.stdout,
              (p.stdout + p.stderr)[-300:])
    for rel in ("mcp-docx-compare/run-child.test.mjs",
                "mcp-docx-converter/run-child.test.mjs"):
        p = subprocess.run(["node", rel.split("/")[-1]], cwd=str(WS / rel.split("/")[0]),
                           capture_output=True, text=True, timeout=300)
        check(f"{rel} passes", p.returncode == 0 and "All run-child checks PASSED" in p.stdout,
              (p.stdout + p.stderr)[-300:])


def test_f14_swap_after_staging():
    print("\n== F14: a post-check swap cannot redirect the staged read ==")
    repo = str(WS)
    code = textwrap.dedent(f"""
        import {{ mkdtempSync, mkdirSync, symlinkSync, writeFileSync, readFileSync,
                  rmSync }} from 'node:fs';
        import {{ tmpdir }} from 'node:os';
        import * as path from 'node:path';
        import {{ allowedRoots, stageContainedInput }}
          from '{repo}/mcp-docx-compare/containment.mjs';
        const work = mkdtempSync(path.join(tmpdir(), 'f14-t-'));
        const root = path.join(work, 'allowed'); mkdirSync(root);
        const outside = path.join(work, 'outside'); mkdirSync(outside);
        const stage = path.join(work, 'stage'); mkdirSync(stage, {{ mode: 0o700 }});
        const inside = path.join(root, 'input.docx'); writeFileSync(inside, 'INSIDE');
        const secret = path.join(outside, 'secret.docx'); writeFileSync(secret, 'SECRET');
        const roots = allowedRoots(root);
        const staged = stageContainedInput(inside, roots, stage, 'input.docx');
        rmSync(inside); symlinkSync(secret, inside);
        process.stdout.write(readFileSync(staged, 'utf8'));
        rmSync(work, {{ recursive: true, force: true }});
    """)
    p = subprocess.run(["node", "--input-type=module", "-e", code],
                       capture_output=True, text=True, timeout=120)
    check("F14 the child's copy keeps the validated bytes after the swap",
          p.returncode == 0 and p.stdout == "INSIDE",
          f"rc={p.returncode} out={p.stdout!r} err={p.stderr[-250:]}")


def test_f14_servers_use_staging():
    print("\n== F14: both servers hand the child a staged copy ==")
    for rel in ("mcp-docx-compare/index.js", "mcp-docx-converter/index.js"):
        src = text(rel)
        check(f"{rel} stages a validated input",
              "stageContainedInput(" in src
              and "mkdtempSync(" in src
              and "rmSync(stagingDir" in src)
        check(f"{rel} keys/validates on the real input, not the staged path",
              "inFlightKey(realOriginal" in src or "finalPdf ? finalPdf.toLowerCase()" in src
              or "pdfKey(spawnPath)" in src)


# ---------------------------------------------------------------------------
# F133: the shell records the Windows pids; the runner kills them
# ---------------------------------------------------------------------------
def test_f133_source_contracts():
    print("\n== F133: the WSL Windows-pid handoff ==")
    for rel in ("mcp-docx-compare/run-child.mjs", "mcp-docx-converter/run-child.mjs"):
        src = text(rel)
        check(f"{rel} has a WSL predicate", "export function isWsl(" in src)
        check(f"{rel} taskkills the recorded Windows pids",
              "taskkill.exe" in src and "windowsPidFile" in src
              and "DOCX_MCP_WINDOWS_PID_FILE" in src)
    for rel in ("docxcompare.sh", "docx2pdf.sh"):
        src = text(rel)
        check(f"{rel} records the PowerShell/Word Windows pids",
              "DOCX_MCP_WINDOWS_PID_FILE" in src
              and "$PID | Set-Content" in src
              and "Get-Process -Name WINWORD" in src
              and "Add-Content -LiteralPath $pidFile" in src.replace("\\$", "$"))
        check(f"{rel} keeps the pid-file write best-effort",
              "catch { }" in src)


def _fake_bin(d: Path, mode: str) -> Path:
    """A fake powershell.exe + wslpath pair.

    `mode` is 'compare' (write a valid DOCX at $outputPath) or 'pdf' (write a
    minimal PDF at $pdf). Paths are translated back through the fake wslpath's
    C:\\... form. A pid file env is dumped verbatim for the caller to inspect.
    """
    b = d / "bin"
    b.mkdir()
    (b / "wslpath").write_text(textwrap.dedent(r"""
        #!/usr/bin/env bash
        if [ "$1" = "-w" ]; then printf 'C:%s' "${2//\//\\}"; else
          p="${2#C:}"; printf '%s' "${p//\\//}"; fi
        """).lstrip(), encoding="utf-8")
    (b / "powershell.exe").write_text(textwrap.dedent(r"""
        #!/usr/bin/env python3
        import base64, os, re, sys
        argv = sys.argv[1:]
        enc = argv[argv.index("-EncodedCommand") + 1]
        script = base64.b64decode(enc).decode("utf-16-le")
        dump = os.environ.get("PS_DUMP")
        if dump:
            open(dump, "w", encoding="utf-8").write(script)

        def linux(win):
            p = win.replace("''", "'")
            if p[:2].lower() == "c:":
                p = p[2:]
            return "/" + p.replace("\\", "/").lstrip("/")

        mode = "__MODE__"
        if mode == "compare":
            out = re.search(r"\$outputPath\s*=\s*'(.*)'", script).group(1)
            import zipfile
            ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
            with zipfile.ZipFile(linux(out), "w") as z:
                z.writestr("[Content_Types].xml",
                           '<?xml version="1.0"?><Types xmlns="http://schemas.'
                           'openxmlformats.org/package/2006/content-types"/>')
                z.writestr("word/_rels/document.xml.rels",
                           '<?xml version="1.0"?><Relationships xmlns="http://'
                           'schemas.openxmlformats.org/package/2006/relationships"/>')
                z.writestr("word/document.xml",
                           '<?xml version="1.0"?><w:document ' + ns
                           + '><w:body/><w:p/></w:document>')
        elif mode == "pdf":
            out = re.search(r"\$pdf\s*=\s*'(.*)'", script).group(1)
            open(linux(out), "wb").write(b"%PDF-1.4\n" + b"x" * 2048 + b"\n%%EOF\n")
        sys.exit(0)
        """).lstrip().replace("__MODE__", mode), encoding="utf-8")
    (b / "wslpath").chmod(0o755)
    (b / "powershell.exe").chmod(0o755)
    return b


def _run(script, args, d, mode, pidfile=""):
    b = _fake_bin(d, mode)
    env = dict(os.environ, PATH=f"{b}{os.pathsep}{os.environ.get('PATH', '')}",
               PS_DUMP=str(d / "ps_dump.txt"))
    if pidfile:
        env["DOCX_MCP_WINDOWS_PID_FILE"] = str(pidfile)
    return subprocess.run(["bash", str(WS / script)] + [str(a) for a in args],
                          cwd=str(d), capture_output=True, text=True, timeout=180,
                          env=env)


def test_f133_pidfile_hook():
    print("\n== F133: the wrapper puts a Windows pid file in the PowerShell ==")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "a.docx").write_bytes(b"x")
        pidfile = d / "pids"
        p = _run("docxcompare.sh", [d / "a.docx", d / "a.docx", d / "out.docx"],
                 d, "compare", pidfile)
        dump = (d / "ps_dump.txt").read_text(encoding="utf-8") if (d / "ps_dump.txt").exists() else ""
        check("F133 docxcompare.sh hands the converted pid path to PowerShell",
              "pidFile" in dump and "pids" in dump and "Set-Content -LiteralPath $pidFile" in dump,
              f"rc={p.returncode} dump={dump[:200]!r}")
        check("F133 docxcompare.sh still succeeds with the hook present",
              p.returncode == 0 and (d / "out.docx").is_file(),
              (p.stdout + p.stderr)[-300:])

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "a.docx").write_bytes(b"x")
        p = _run("docx2pdf.sh", [d / "a.docx", d / "custom.pdf"], d, "pdf",
                 d / "pids")
        dump = (d / "ps_dump.txt").read_text(encoding="utf-8") if (d / "ps_dump.txt").exists() else ""
        check("F133 docx2pdf.sh hands the converted pid path to PowerShell",
              "pidFile" in dump and "pids" in dump and "Set-Content -LiteralPath $pidFile" in dump,
              f"rc={p.returncode} dump={dump[:200]!r}")
        check("F133 docx2pdf.sh accepts the explicit output beside the real input",
              p.returncode == 0 and (d / "custom.pdf").is_file()
              and (d / "a.pdf").exists() is False,
              (p.stdout + p.stderr)[-300:])


def test_f14_staged_input_shell():
    print("\n== F14: the scripts accept a staged input + explicit output ==")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        real = d / "real"; real.mkdir()
        stage = d / "stage"; stage.mkdir()
        (real / "paper.docx").write_bytes(b"original")
        (stage / "input.docx").write_bytes(b"original")
        p = _run("docx2pdf.sh", [stage / "input.docx", real / "paper.pdf"],
                 d, "pdf")
        check("F14 the converter reads the staged copy and writes the requested PDF",
              p.returncode == 0 and (real / "paper.pdf").is_file()
              and not (stage / "input.pdf").exists(),
              (p.stdout + p.stderr)[-300:])
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        real = d / "real"; real.mkdir()
        stage = d / "stage"; stage.mkdir()
        for name in ("original.docx", "revised.docx"):
            (real / name).write_bytes(b"x")
            (stage / name).write_bytes(b"x")
        out = real / "redline.docx"
        p = _run("docxcompare.sh",
                 [stage / "original.docx", stage / "revised.docx", out],
                 d, "compare")
        check("F14 the comparer reads the staged copies and writes the requested output",
              p.returncode == 0 and out.is_file(),
              (p.stdout + p.stderr)[-300:])


def main() -> int:
    test_node_suites()
    test_f14_swap_after_staging()
    test_f14_servers_use_staging()
    test_f133_source_contracts()
    test_f133_pidfile_hook()
    test_f14_staged_input_shell()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL WAVE-2 MCP CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

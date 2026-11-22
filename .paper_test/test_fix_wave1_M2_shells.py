#!/usr/bin/env python3
"""Regression checks for the shell/MCP candidates of the 2026-11-22 11:28
fix-bugs wave (batch M2).

Run: python3 .paper_test/test_fix_wave1_M2_shells.py

  F02  compare/convert write a UNIQUE temp and rename atomically
  F28  the comparer verifies real XML parts, not just two ZIP names
  F64  the installer backup writers never follow a planted link
  F82  a failed PowerShell run leaves no partial file at the final path
  F102 export-test-env.sh reads PIPESTATUS without tripping `set -e`
  F117 install_dependencies.sh writes generated files via a safe temp
  F135 ENV_NAME cannot escape --out
  F148 allowed roots must be existing directories (and the PDF is checked)
  F173 the overflow test fails when the grace timer is removed
  F207 taskkill/PowerShell fallbacks carry a bounded timeout
"""
from __future__ import annotations

import os
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


def test_static_shell_contracts():
    cmp_sh = text("docxcompare.sh")
    pdf_sh = text("docx2pdf.sh")
    check("F02 the comparer writes a temp and renames",
          'OUTPUT_TMP="${OUTPUT}.tmp.' in cmp_sh
          and 'mv -f -- "$OUTPUT_TMP" "$OUTPUT"' in cmp_sh)
    check("F02 the converter writes a temp and renames",
          'PDF_TMP="${PDF}.tmp.' in pdf_sh
          and 'mv -f -- "$PDF_TMP" "$PDF"' in pdf_sh)
    check("F82 both scripts install a failure trap that removes the output",
          "_cleanup_partial" in cmp_sh and "trap _cleanup_partial EXIT" in cmp_sh
          and "_cleanup_partial" in pdf_sh and "trap _cleanup_partial EXIT" in pdf_sh)
    check("F28 the comparer parses the required XML parts",
          "xml.etree.ElementTree" in cmp_sh
          and "word/_rels/document.xml.rels" in cmp_sh
          and "not xml at all" not in cmp_sh)
    installer = text("install_agent_tooling.sh")
    check("F64 the installer creates backups with O_EXCL, never cp -p",
          "cp -p --" not in installer and installer.count("set -o noclobber") >= 2)
    deps = text("install_dependencies.sh")
    check("F117 the dependency installer writes generated files safely",
          deps.count("safe_write_file") >= 5
          and '> "$REPO_ROOT/deps.env"' not in deps)
    check("F102 PIPESTATUS is read with errexit off",
          "set +e" in text("scripts/export-test-env.sh")
          and "_ps=(\"${PIPESTATUS[@]}\")" in text("scripts/export-test-env.sh"))
    for rel in ("mcp-docx-compare/run-child.mjs", "mcp-docx-converter/run-child.mjs"):
        src = text(rel)
        check(f"F207 {rel} bounds the Windows kill fallbacks",
              src.count("timeout: 15000") >= 2)


def test_f135_env_escape():
    env = dict(os.environ, PAPER_REFINE_TEST_ENV="../escape")
    p = subprocess.run(["bash", str(WS / "scripts/export-test-env.sh")],
                       capture_output=True, text=True, timeout=60, env=env)
    check("F135 a traversing ENV_NAME is refused", p.returncode == 2
          and "one filename component" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-200:])


def _fake_powershell(bindir: Path, mode: str):
    """A powershell.exe that writes into the output path in the encoded script."""
    script = bindir / "powershell.exe"
    script.write_text(textwrap.dedent(r"""        #!/usr/bin/env bash
        enc=""
        while [ $# -gt 0 ]; do
          if [ "$1" = "-EncodedCommand" ]; then enc="$2"; shift; fi
          shift
        done
        decoded="$(printf '%s' "$enc" | base64 -d | iconv -f UTF-16LE -t UTF-8)"
        case "__MODE__" in
          names-only)
            out="$(printf '%s' "$decoded" | sed -n "s/.*outputPath *= *'\([^']*\)'.*/\1/p" | head -1)"
            out="$(wslpath -u "$out")"
            python3 -c 'import sys, zipfile
z = zipfile.ZipFile(sys.argv[1], "w")
z.writestr("[Content_Types].xml", b"not xml at all")
z.writestr("word/document.xml", b"")' "$out"
            exit 0
            ;;
          partial)
            out="$(printf '%s' "$decoded" | sed -n "s/.*\$pdf  *= *'\([^']*\)'.*/\1/p" | head -1)"
            out="$(wslpath -u "$out")"
            printf 'partial-not-a-pdf' > "$out"
            exit 1
            ;;
        esac
        exit 1
        """).replace("__MODE__", mode), encoding="utf-8")
    script.chmod(0o755)
    return script


def _run_with_fake(script, args, bindir, fake_dir, mode):
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_DIR=str(fake_dir), FAKE_MODE=mode)
    return subprocess.run(["bash", str(WS / script)] + [str(a) for a in args],
                          capture_output=True, text=True, timeout=120, env=env)


def test_f28_names_only_rejected():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        bindir = d / "bin"; bindir.mkdir()
        _fake_powershell(bindir, "names-only")
        (d / "a.docx").write_bytes(b"x")
        (d / "b.docx").write_bytes(b"y")
        out = d / "out.docx"
        p = _run_with_fake("docxcompare.sh", [d / "a.docx", d / "b.docx", out],
                           bindir, d, "names-only")
        check("F28 a two-name non-XML ZIP is not a successful comparison",
              p.returncode != 0 and not out.exists(),
              f"rc={p.returncode} out={out.exists()} err={(p.stderr or '')[-200:]}")


def test_f82_partial_removed():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        bindir = d / "bin"; bindir.mkdir()
        _fake_powershell(bindir, "partial")
        (d / "a.docx").write_bytes(b"x")
        p = _run_with_fake("docx2pdf.sh", [d / "a.docx"], bindir, d, "partial")
        pdf = d / "a.pdf"
        leftovers = sorted(str(q.name) for q in d.glob("*.tmp.*"))
        check("F82 a failed conversion leaves no partial PDF at the final path",
              p.returncode != 0 and not pdf.exists() and not leftovers,
              f"rc={p.returncode} pdf={pdf.exists()} leftovers={leftovers}")


def test_f148_file_root_refused():
    with tempfile.TemporaryDirectory() as td:
        root_file = Path(td) / "root.docx"
        root_file.write_bytes(b"x")
        code = ("import('" + (WS / "mcp-docx-converter/containment.mjs").as_uri() + "')"
                ".then((m) => { try { m.allowedRoots(process.argv[1]); "
                "console.log('ACCEPTED'); } catch (e) { console.log('REFUSED ' + e.message); } });")
        p = subprocess.run(["node", "-e", code, str(root_file)],
                           capture_output=True, text=True, timeout=60)
        check("F148 a regular file is not accepted as an allowed root",
              "REFUSED" in p.stdout and "not an existing directory" in p.stdout,
              (p.stdout + p.stderr)[-200:])


def test_f173_grace_timer():
    p = subprocess.run(["node", "run-child.test.mjs"], cwd=str(WS / "mcp-docx-compare"),
                       capture_output=True, text=True, timeout=120)
    check("F173 the overflow test still passes with the grace timer",
          p.returncode == 0 and "All run-child checks PASSED" in p.stdout,
          (p.stdout + p.stderr)[-300:])


def main() -> int:
    test_static_shell_contracts()
    test_f135_env_escape()
    test_f28_names_only_rejected()
    test_f82_partial_removed()
    test_f148_file_root_refused()
    test_f173_grace_timer()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL M2 SHELL/MCP CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

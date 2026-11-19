#!/usr/bin/env python3
"""Regression tests for the 2026-11-19 fix-bugs wave 1, g10 (PDF + profile).

Run: python3 .paper_test/test_fix_bugs_20261119_g10_pdf_tests.py
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))

import paper_pipeline as pp  # noqa: E402

TMPDIRS = []
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def make_fake_latexmk(bin_dir: Path, body: str) -> None:
    exe = bin_dir / "latexmk"
    exe.write_text("#!/bin/sh\nfor a in \"$@\"; do last=\"$a\"; done\n"
                   "out=\"${last%.tex}.pdf\"\n" + body, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_evidence_nested_link_is_not_followed():
    tmp = scratch("fbg10_ev_")
    src = tmp / "raw_data"
    (src / "sub").mkdir(parents=True)
    (src / "ok.txt").write_text("visible", encoding="utf-8")
    outside = tmp / "secret.txt"
    outside.write_text("HOST SECRET", encoding="utf-8")
    os.symlink(outside, src / "sub" / "secret.txt")
    dst = tmp / "build" / "raw_data"
    links, copied = pp._materialise_evidence(src, dst)
    check("F033 a nested evidence symlink is named", links == ["sub/secret.txt"], repr(links))
    check("F033 the evidence area is copied, not symlinked", copied and not dst.is_symlink())
    check("F033 the outside file is not in the build tree",
          not (dst / "sub" / "secret.txt").exists())
    check("F033 real evidence files survive", (dst / "ok.txt").read_text() == "visible")

    clean = tmp / "feedback"
    clean.mkdir()
    (clean / "note.md").write_text("note", encoding="utf-8")
    (tmp / "build2").mkdir()
    dst2 = tmp / "build2" / "feedback"
    links2, copied2 = pp._materialise_evidence(clean, dst2)
    check("F033 a link-free area still uses the symlink fast path",
          links2 == [] and not copied2 and dst2.is_symlink())


def test_compile_rejects_non_pdf():
    tmp = scratch("fbg10_pdf_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}x\\end{document}\n", encoding="utf-8")
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    make_fake_latexmk(bin_dir, "printf 'not a pdf' > \"$out\"\nexit 0\n")
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(bin_dir) + os.pathsep + old_path
    try:
        bad = pp.compile_latex_pdf(pkg, "main.tex", tmp / "bad.pdf")
    finally:
        os.environ["PATH"] = old_path
    check("F035 a non-PDF output is not recorded ok", bad["ok"] is False, repr(bad))
    check("F035 the reason names the signature problem",
          "PDF" in (bad.get("error") or ""), repr(bad.get("error")))

    make_fake_latexmk(bin_dir, "printf '%%PDF-1.4\\n%%%%EOF\\n' > \"$out\"\nexit 0\n")
    os.environ["PATH"] = str(bin_dir) + os.pathsep + old_path
    try:
        good = pp.compile_latex_pdf(pkg, "main.tex", tmp / "good.pdf")
    finally:
        os.environ["PATH"] = old_path
    check("F035 a real PDF signature is still accepted", good["ok"] is True, repr(good))
    check("F035 the accepted PDF is copied out", (tmp / "good.pdf").is_file())


def test_fidelity_view_keeps_non_text_marks():
    import importlib.util
    import zipfile
    spec = importlib.util.spec_from_file_location(
        "fbg10_fidelity", str(WS / ".paper_test" / "test_redline_fidelity.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tmp = scratch("fbg10_marks_")
    docx = tmp / "marks.docx"
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document ' + ns + "><w:body>"
                   "<w:p><w:r><w:t>x</w:t><w:br/><w:tab/>"
                   "<w:drawing/></w:r></w:p>"
                   "</w:body></w:document>")
    _, accept, reject = mod.body_views(docx)
    check("F039 the general fidelity view keeps break/tab/drawing marks",
          accept[0] == "x<br><tab><drawing>" and reject[0] == accept[0],
          repr(accept))


def main():
    test_evidence_nested_link_is_not_followed()
    test_compile_rejects_non_pdf()
    test_fidelity_view_keeps_non_text_marks()
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("\nG10 PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        import shutil
        for tmp in TMPDIRS:
            shutil.rmtree(tmp, ignore_errors=True)

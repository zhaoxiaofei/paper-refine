#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group G9 (run 20261115-220228).

Each check pins one re-validated candidate from the verified findings set:
  C060  a failed cold-start claim scan must be reported, not shown as "none"
  C144  the OOXML sanitizer needs an aggregate/entry-count budget, not only
        a per-part cap
  C145  run_dsh_streaming must not hand a captured stderr to Popen
  C146  TeX include expansion needs a size/depth budget

Hermetic: temp dirs only; no network, no agent runs.

Run:  python3 -B .paper_test/test_wave2_G9.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent-common"))

import paper_pipeline as pp          # noqa: E402
import paper_dsh_runtime as dsh      # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def test_c060_failed_claim_scan_is_reported():
    print("\n== C060: a failed claim scan is a named gap, not 'no claims' ==")
    sb = Path(tempfile.mkdtemp())
    (sb / "base").mkdir()

    def boom(*_a, **_k):
        raise RuntimeError("model exploded")

    old = pp.code_side_evidence
    pp.code_side_evidence = boom
    try:
        res = pp.seed_cold_start_surfaces(SimpleNamespace(), sb, 1)
        text = (sb / pp.COLD_START_SURFACES_REL).read_text(encoding="utf-8")
    finally:
        pp.code_side_evidence = old
    check("C060 the failure is named in CLAIM_SURFACES.md", "model exploded" in text)
    check("C060 it is marked as a coverage gap", "COVERAGE GAP" in text)
    check("C060 the return value carries the error", "model exploded" in res.get("error", ""))

    # A genuinely clean (but empty) scan is still not a gap.
    old = pp.code_side_evidence
    pp.code_side_evidence = lambda *_a, **_k: {"claims": {"rows": []}}
    try:
        pp.seed_cold_start_surfaces(SimpleNamespace(), sb, 2)
        clean = (sb / pp.COLD_START_SURFACES_REL).read_text(encoding="utf-8")
    finally:
        pp.code_side_evidence = old
    check("C060 a clean empty scan is not called a gap", "COVERAGE GAP" not in clean)


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, size in entries:
            z.writestr(name, b" " * size)
    return buf.getvalue()


def test_c144_ooxml_package_budget():
    print("\n== C144: an OOXML package is bounded in aggregate, not only per part ==")
    many = _zip([(f"word/part{i}.xml", 10) for i in range(pp.MAX_DOCX_ENTRIES + 1)])
    out, notes = pp._sanitize_ooxml_bytes(many)
    check("C144 an over-count package is refused",
          any("entry-count budget" in note for note in notes), str(notes[:1]))
    check("C144 the refused package is returned unchanged", out == many)

    big = _zip([(f"word/big{i}.xml", 60 * 1024 * 1024) for i in range(5)])
    out, notes = pp._sanitize_ooxml_bytes(big)
    check("C144 an over-size aggregate is refused",
          any("total size budget" in note for note in notes), str(notes[:1]))
    check("C144 the oversized package is returned unchanged", out == big)

    small = _zip([("word/document.xml", 64)])
    out, notes = pp._sanitize_ooxml_bytes(small)
    check("C144 a normal package is still processed",
          not any("budget" in note for note in notes), str(notes[:1]))


def test_c145_captured_stderr():
    print("\n== C145: a captured stderr does not crash the DSH adapter ==")
    real = sys.stderr
    for label, stream in (("StringIO", io.StringIO()),
                          ("TextIOWrapper", io.TextIOWrapper(io.BytesIO()))):
        sys.stderr = stream
        try:
            rc, _turn_failed = dsh.run_dsh_streaming(
                ["/bin/sh", "-c", "exit 0"], dict(os.environ), "probe")
            crashed = ""
        except Exception as exc:                                  # noqa: BLE001
            rc, crashed = None, f"{type(exc).__name__}: {exc}"
        finally:
            sys.stderr = real
        check(f"C145 {label} stderr runs the child", crashed == "" and rc == 0,
              crashed or f"rc={rc}")


def test_c146_tex_include_budget():
    print("\n== C146: TeX include expansion is bounded ==")
    d = Path(tempfile.mkdtemp())
    n = 22
    for i in range(n):
        body = ("\\input{n%d}\n\\input{n%d}\n" % (i + 1, i + 1)) if i < n - 1 else "leaf\n"
        (d / f"n{i}.tex").write_text(body, encoding="utf-8")
    out = pp._tex_expand_includes((d / "n0.tex").read_text(encoding="utf-8"), d,
                                  source=d / "n0.tex")
    check("C146 the expansion does not blow up", len(out) < 1024 * 1024, str(len(out)))
    check("C146 it leaves a named residual include", "\\input" in out)

    (d / "main.tex").write_text("A \\input{body}\n", encoding="utf-8")
    (d / "body.tex").write_text("B body\n", encoding="utf-8")
    normal = pp._tex_expand_includes((d / "main.tex").read_text(encoding="utf-8"), d,
                                     source=d / "main.tex")
    check("C146 an ordinary include still expands", "B body" in normal and "\\input" not in normal,
          repr(normal))


def main():
    test_c060_failed_claim_scan_is_reported()
    test_c144_ooxml_package_budget()
    test_c145_captured_stderr()
    test_c146_tex_include_budget()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

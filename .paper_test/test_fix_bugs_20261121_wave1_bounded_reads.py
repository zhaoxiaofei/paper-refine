#!/usr/bin/env python3
"""Regression tests for the 2026-11-21 fix-bugs wave 1.

One hermetic check block per confirmed candidate:

  F13  the README states the profile-driven cover-letter bound, not a universal
       300-500 preference
  F44  _repair_file_text reads an agent-written file through the bounded reader
  F46  the judge-view materializer checks the payload size before reading it
  F47  _cached_sha256 hashes in bounded chunks and refuses an over-budget file
  F48  validate_latex reads a bounded prefix/chunks, never the whole .tex
  F66  a UTF-16 DOCX part is decoded with its own encoding, not as UTF-8
  F97  a software token is not a citation, and a bracket citation is one

Run:  python3 .paper_test/test_fix_bugs_20261121_wave1.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(WS))

import paper_pipeline as pp  # noqa: E402

FAILS = []
TMPDIRS = []
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def write_docx(path: Path, paragraphs, encoding="utf-8"):
    body = "".join(
        '<w:p><w:r><w:t xml:space="preserve">'
        + p.replace("&", "&amp;").replace("<", "&lt;")
        + "</w:t></w:r></w:p>" for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="%s" standalone="yes"?>'
           '<w:document %s><w:body>%s</w:body></w:document>'
           % (encoding.upper(), W, body))
    data = xml.encode("utf-16") if encoding == "utf-16" else xml.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", data)


# ---------------------------------------------------------------------------
# F13 -- README cover-letter bound is profile-driven
# ---------------------------------------------------------------------------
def test_f13():
    print("\n== F13 README states the profile-driven cover-letter bound ==")
    readme = (WS / "README.md").read_text(encoding="utf-8")
    start = readme.index("The **cover letter** has two separate reported budgets")
    end = readme.index("**A venue's word limit", start)
    para = readme[start:end]
    check("F13 the persuading part is measured against the profile's bound",
          "venue profile's own `cover_letter` bound" in para)
    check("F13 300-500 is the no-block default, not a universal preference",
          "applies only when the" in para
          and "configures no cover-letter block" in para)
    check("F13 the unconditional operator 300-500 preference is gone",
          "operator's 300–500-word preference" not in para, para[:200])
    skill = (WS / "paper-skills/paper-review/SKILL.md").read_text(encoding="utf-8")
    check("F13 the review skill already states the same rule",
          "measured against the venue profile's own `cover_letter` bound" in skill)
    prof = json.loads((WS / "venue_profiles/frontiers-in-immunology.json")
                      .read_text(encoding="utf-8"))
    check("F13 a shipped profile sets a non-300-500 bound (the contradiction)",
          (prof.get("length_limits") or {}).get("cover_letter", {}).get("max") == 200,
          str((prof.get("length_limits") or {}).get("cover_letter")))


# ---------------------------------------------------------------------------
# F44 -- _repair_file_text is bounded / no-follow
# ---------------------------------------------------------------------------
def test_f44():
    print("\n== F44 _repair_file_text uses the bounded reader ==")
    d = scratch("f44_")
    big = d / "big.md"
    big.write_bytes(b"x" * (pp.PACKAGE_TEXT_BYTES_LIMIT + 1))
    check("F44 an over-budget package file is opaque, not read whole",
          pp._repair_file_text(big) is None, repr(pp._repair_file_text(big))[:80])
    outside = d / "outside.txt"
    outside.write_text("SECRET OUTSIDE", encoding="utf-8")
    link = d / "link.txt"
    link.symlink_to(outside)
    check("F44 a symlinked package file is not read", pp._repair_file_text(link) is None)
    ok = d / "ok.md"
    ok.write_text("normal package text", encoding="utf-8")
    check("F44 a normal in-budget text file still reads",
          pp._repair_file_text(ok) == "normal package text")
    docx = d / "ok.docx"
    write_docx(docx, ["Hello world"])
    check("F44 the DOCX paragraph path is unchanged",
          pp._repair_file_text(docx) == "Hello world", repr(pp._repair_file_text(docx)))


# ---------------------------------------------------------------------------
# F46 -- judge-view materializer checks the source size first
# ---------------------------------------------------------------------------
def test_f46():
    print("\n== F46 judge-view materializer stats before it reads ==")
    d = scratch("f46_")
    big = d / "big.svg"
    with open(big, "wb") as fh:
        fh.write(b'<svg xmlns="http://www.w3.org/2000/svg">')
        fh.truncate(pp.MAX_PAYLOAD_BYTES + 1)
    data, notes = pp._transform_view_file("big.svg", big, {"big.svg": "f1.svg"})
    check("F46 an over-budget payload is omitted before read", data is None,
          f"len={None if data is None else len(data)}")
    check("F46 the omission is a named gap",
          any("payload budget" in str(n) and "omitted" in str(n) for n in notes), str(notes))
    ok = d / "ok.txt"
    ok.write_text("hello\n", encoding="utf-8")
    data, notes = pp._transform_view_file("ok.txt", ok, {"ok.txt": "f1.txt"})
    check("F46 an in-budget text payload is still transformed",
          data == b"hello\n" and notes == [], f"{data!r} {notes!r}")


# ---------------------------------------------------------------------------
# F47 -- _cached_sha256 is chunked and over-budget-capped
# ---------------------------------------------------------------------------
def test_f47():
    print("\n== F47 _cached_sha256 hashes in bounded chunks ==")
    d = scratch("f47_")
    big = d / "big.png"
    with open(big, "wb") as fh:
        fh.truncate(pp.MEDIA_PART_MAX_BYTES + 1)
    try:
        got = pp._cached_sha256(big)
        raised = ""
    except Exception as e:                                            # noqa: BLE001
        got, raised = None, f"{type(e).__name__}: {e}"
    check("F47 an over-budget referenced figure is refused, not loaded",
          raised and "digest budget" in raised, raised or str(got))
    small = d / "small.bin"
    small.write_bytes(b"abc")
    digest = pp._cached_sha256(small)
    check("F47 a small payload's digest is unchanged",
          digest == hashlib.sha256(b"abc").hexdigest(), digest)
    check("F47 the digest is cached by (path, mtime, size)",
          pp._cached_sha256(small) == digest)


# ---------------------------------------------------------------------------
# F48 -- validate_latex never reads the whole .tex
# ---------------------------------------------------------------------------
def _no_whole_read(fn):
    orig = Path.read_text
    calls = {"n": 0}

    def spy(self, *a, **k):
        calls["n"] += 1
        return orig(self, *a, **k)

    Path.read_text = spy
    try:
        fn()
    finally:
        Path.read_text = orig
    return calls["n"]


def test_f48():
    print("\n== F48 validate_latex reads a bounded head and bounded chunks ==")
    d = scratch("f48_")
    fmt = pp._format_module()
    check("F48 the format module loads", fmt is not None)
    frag = d / "frag.tex"
    frag.write_text("A section body line.\n" * 1000, encoding="utf-8")
    seen = {}
    calls = _no_whole_read(lambda: seen.update(fmt.validate_latex(frag)))
    check("F48 a fragment is classified without any whole-file read_text",
          calls == 0 and seen.get("ok") is None
          and "fragment" in str(seen.get("detail")), f"calls={calls} {seen}")
    # The marker may straddle the 8000-byte head/chunk boundary; the streaming
    # scan must still find it and (with no engine) not call it a fragment.
    split = d / "split.tex"
    split.write_bytes(b"a" * 7998 + b"\\documentclass{article}\n" + b"b" * 100000)
    seen2 = {}
    _no_whole_read(lambda: seen2.update(fmt.validate_latex(split)))
    check("F48 a documentclass split across the head boundary is found",
          "fragment" not in str(seen2.get("detail")), str(seen2.get("detail"))[:80])


# ---------------------------------------------------------------------------
# F66 -- UTF-16 DOCX parts are decoded with their own encoding
# ---------------------------------------------------------------------------
def test_f66():
    print("\n== F66 a UTF-16 DOCX part keeps its text ==")
    d = scratch("f66_")
    u8 = d / "u8.docx"
    u16 = d / "u16.docx"
    body = "<w:p><w:r><w:t>Hello world</w:t></w:r></w:p>"
    write_docx(u8, ["Hello world"], encoding="utf-8")
    write_docx(u16, ["Hello world"], encoding="utf-16")
    check("F66 UTF-8 control: paragraphs read", pp._docx_paragraphs(u8) == ["Hello world"])
    check("F66 UTF-16 part: the shared paragraph reader already sees it",
          pp._docx_paragraphs(u16) == ["Hello world"])
    check("F66 UTF-16 part: _docx_paragraph_texts sees it",
          pp._docx_paragraph_texts(u16) == ["Hello world"],
          repr(pp._docx_paragraph_texts(u16)))
    texts, gap = pp._email_texts_in_file(u16)
    check("F66 UTF-16 part: the e-mail/identifier scan sees its text",
          texts == ["Hello world"] and gap == "", f"{texts!r} {gap!r}")
    check("F66 UTF-8 control: _docx_paragraph_texts unchanged",
          pp._docx_paragraph_texts(u8) == ["Hello world"])
    _ = body


# ---------------------------------------------------------------------------
# F97 -- tool tokens are not citations; bracket citations are
# ---------------------------------------------------------------------------
def test_f97():
    print("\n== F97 PKG-23 citation parsing ==")
    for token in ("processed with MACS2", "ggplot2 and Seurat4",
                  "using DESeq2"):
        check(f"F97 {token!r} is not a numeric citation",
              [m.groups() for m in pp.INLINE_CITATION_RE.finditer(token)] == [],
              str([m.groups() for m in pp.INLINE_CITATION_RE.finditer(token)]))
    check("F97 a glued citation is still read",
          [m.groups() for m in pp.INLINE_CITATION_RE.finditer("single-cell omics43.")]
          == [("omics", "43")])
    check("F97 a decimal is still not a citation",
          [m.groups() for m in pp.INLINE_CITATION_RE.finditer("value 43.5 here")] == [])
    bracket_re = getattr(pp, "BRACKET_CITATION_RE", None)
    check("F97 a bracket citation is parsed",
          bracket_re is not None
          and bracket_re.findall("single-cell omics [43]") == ["43"],
          repr(bracket_re))

    d = scratch("f97_")
    false_pos = d / "false_positive"
    write_docx(false_pos / "manuscript.docx", [
        "Results.", "We used single-cell omics processed with MACS2 and ggplot2.",
        "References",
        "2. Smith, J. The complete sequence of a human genome. Science 372, 984 (2021).",
        "4. Doe, A. Telomere-to-telomere assembly of a human genome. Nature 600, 1 (2021).",
    ])
    rows = pp.scan_single_cell_citation_mismatch(false_pos)
    check("F97 a software name invents no PKG-23 citation mismatch", rows == [],
          str([r.get("reference") for r in rows]))
    bracket = d / "bracket"
    write_docx(bracket / "manuscript.docx", [
        "Results.", "We used single-cell omics [43].",
        "References",
        "43. Nurk, S. et al. The complete sequence of a human genome. "
        "Science 372, 984 (2021).",
    ])
    rows = pp.scan_single_cell_citation_mismatch(bracket)
    check("F97 a real bracket citation to an assembly is reported",
          len(rows) == 1 and rows[0].get("reference") == "ref. 43",
          str([(r.get("reference"), r.get("detail", "")[:40]) for r in rows]))


def main() -> int:
    test_f13()
    test_f44()
    test_f46()
    test_f47()
    test_f48()
    test_f66()
    test_f97()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-11-21 wave-1 FIX-BUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        cleanup()
    sys.exit(rc)

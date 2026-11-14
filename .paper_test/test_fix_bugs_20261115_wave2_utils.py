#!/usr/bin/env python3
"""Regression checks for 2026-11-15 fix-bugs wave 2, group `utils` (F103-F131).

Each check pins one candidate this wave re-verified on the tree and repaired.
Hermetic: every fixture lives under tempfile.mkdtemp(); chmod-000 fixtures are
restored before cleanup so a non-root runner can always remove them.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_utils.py
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import struct
import sys
import tempfile
import types
import zipfile
from pathlib import Path
from unittest import mock

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1115w2utils_pp", "paper_pipeline.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def _restore_writable(root: Path) -> None:
    """chmod every entry under root back to owner rwx so cleanup succeeds."""
    for p in sorted(root.rglob("*"), key=lambda q: len(q.parts), reverse=True):
        try:
            os.chmod(p, 0o755 if p.is_dir() else 0o644)
        except OSError:
            pass
    try:
        os.chmod(root, 0o755)
    except OSError:
        pass


# ---------------------------------------------------------------- F103
def test_f103():
    print("\n== F103: an unreadable .tex manuscript is an unparsed gap, not 0 words ==")
    tmp = scratch("w2utils_f103_")
    (tmp / "paper.tex").write_text("\\section{Introduction}\nBody text.\n", encoding="utf-8")
    (tmp / "notes.md").write_text("notes\n", encoding="utf-8")
    os.chmod(tmp / "paper.tex", 0)
    try:
        prof = pp.load_venue_profile("nature-biotechnology").with_article_type(
            "brief-communication")
        info = pp.scan_lengths_in_sources([(tmp, "", ())], profile=prof)
        rows = [r for r in info["rows"] if r.get("document") == "paper.tex"]
        note = pp.length_note(info)
        if IS_ROOT:
            check("F103 (root: chmod-000 is still readable; check skipped)", True)
            return
        check("F103 the unreadable manuscript is NAMED in unparsed",
              "paper.tex" in info["unparsed"], str(info["unparsed"]))
        check("F103 no 0-word main-text row is invented for it", rows == [], str(rows))
        check("F103 the length note never calls it within the caps", "0 words" not in note, note)
    finally:
        _restore_writable(tmp / "paper.tex")


# ---------------------------------------------------------------- F104
def test_f104():
    print("\n== F104: an unreadable text source is a NAMED format-sweep gap ==")
    tmp = scratch("w2utils_f104_")
    (tmp / "paper.tex").write_text("\\section{Methods}\nWe used a long sentence.\n")
    os.chmod(tmp / "paper.tex", 0)
    try:
        info = pp.scan_format_in_sources([(tmp, "", ())])
        if IS_ROOT:
            check("F104 (root: chmod-000 is still readable; check skipped)", True)
            return
        got = [r for r in info["rows"] if r.get("document") == "paper.tex"]
        check("F104 the unreadable manuscript contributes an FMT-X1 gap row",
              bool(got) and got[0].get("rule") == "FMT-X1", str(got[:1]))
        check("F104 the format note no longer reads clean",
              "clean" not in pp.format_note(info), pp.format_note(info))
    finally:
        _restore_writable(tmp / "paper.tex")


# ---------------------------------------------------------------- F105
def test_f105():
    print("\n== F105: a trailing in-prose example never wins over the document ==")
    doc = '{"findings": [{"id": "F1", "severity": "major", "claim": "the real document"}]}'
    text = doc + "\n\n" + "Here is why I concluded this. " * 60 + '\nOne row looks like: {"foo": 1}'
    check("F105 the ambiguity is malformed, not the trailing snippet",
          pp._json_from_text(text, True) is None, repr(pp._json_from_text(text, True)))
    check("F105 a real marker at the end of prose still parses",
          pp._json_from_text('Here is the marker:\n{"stage": "revise", "ok": true}\n', True)
          == {"stage": "revise", "ok": True})
    check("F105 the complete leading document still beats a smaller example",
          pp._json_from_text('{"scores": [1, 2, 3], "decision": "accept"}\n'
                             'Note the schema example is {"example": true}', True)
          == {"scores": [1, 2, 3], "decision": "accept"})


# ---------------------------------------------------------------- F106
def test_f106():
    print("\n== F106: an unreadable subtree does not hash like an empty tree ==")
    tmp = scratch("w2utils_f106_")
    empty = tmp / "empty"
    empty.mkdir()
    tree = tmp / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "x.txt").write_text("x")
    os.chmod(tree / "sub", 0)
    try:
        man = pp.corpus_tree_manifest(tree)
        if IS_ROOT:
            check("F106 (root: chmod-000 is still readable; check skipped)", True)
            return
        check("F106 the manifest names the unreadable directory",
              man.get("unreadable_dirs") == ["sub"], str(man))
        check("F106 the digest is NOT the empty-tree digest",
              pp.corpus_tree_digest(tree) != pp.corpus_tree_digest(empty))
    finally:
        _restore_writable(tree / "sub")


# ---------------------------------------------------------------- F107
def test_f107():
    print("\n== F107: an unreadable subdirectory is a named scan gap ==")
    tmp = scratch("w2utils_f107_")
    (tmp / "main.md").write_text("Contact: a@uni.edu\n")
    (tmp / "supp").mkdir()
    (tmp / "supp" / "extra.md").write_text("Contact: guessed@other.edu\n")
    os.chmod(tmp / "supp", 0)
    try:
        if IS_ROOT:
            check("F107 (root: chmod-000 is still readable; check skipped)", True)
            return
        gaps = []
        found = pp._files_under_ci(tmp, (".md",), gaps=gaps)
        check("F107 the walker keeps the readable file", [p.name for p in found] == ["main.md"],
              str(found))
        check("F107 the walker records the unreadable directory", gaps == ["supp"], str(gaps))
        _addr, addr_gaps = pp._email_addresses_in_sources([(tmp, "", ())])
        check("F107 the e-mail scan names the unreadable directory",
              any("supp" in g for g in addr_gaps), str(addr_gaps))
        fmt_gaps = [r for r in pp.scan_format_in_sources([(tmp, "", ())])["rows"]
                    if r.get("document") == "supp"]
        check("F107 the format sweep records the directory gap", bool(fmt_gaps), str(fmt_gaps[:1]))
        # The two callers the original fix left on the gap-less walker must not
        # treat the truncated listing as the complete document set (R01).
        corpus_gaps = []
        check("F107 the corpus DOCX walk records the unreadable directory",
              pp._fmt_corpus_files(tmp, corpus_gaps) == [] and corpus_gaps == ["supp"],
              str(corpus_gaps))
        prompt_gaps = []
        check("F107 the prompt DOCX list records the unreadable directory",
              pp._prompt_docx_names(tmp, prompt_gaps) == [] and prompt_gaps == ["supp"],
              str(prompt_gaps))
        _errs, cont_warns = [], []
        rep = pp.zotero_field_continuity_check(tmp, tmp, "t", _errs, cont_warns)
        check("F107 the Zotero continuity check names the unreadable directory",
              (rep.get("unreadable_dirs") or {}).get("base") == ["supp"]
              and any("could not be read" in w for w in cont_warns),
              str(rep.get("unreadable_dirs")))
        prompt = pp.apply_guideline_conform_prompt(
            types.SimpleNamespace(cfg={}, root=tmp), tmp)
        check("F107 the conform prompt names the unreadable directory",
              "WARNING: these directories could not be read" in prompt)
    finally:
        _restore_writable(tmp / "supp")


# ---------------------------------------------------------------- F108
def test_f108():
    print("\n== F108: the evidence scan follows the canonical area link ==")
    tmp = scratch("w2utils_f108_")
    canon = tmp / "root" / "non_revised" / "raw_data"
    canon.mkdir(parents=True)
    (canon / "data.md").write_text("Contact: real.person@university.edu\n")
    pkg = tmp / "pkg"
    (pkg / "non_revised").mkdir(parents=True)
    (pkg / "non_revised" / "raw_data").symlink_to(canon, target_is_directory=True)
    got, gaps = pp._email_addresses_in_sources(
        [(pkg / "non_revised", "", ())], evidence=True)
    check("F108 the linked evidence area contributes its address",
          "real.person@university.edu" in got, str(got))


# ---------------------------------------------------------------- F109
def test_f109():
    print("\n== F109: atomic writers preserve the destination mode ==")
    tmp = scratch("w2utils_f109_")
    p = tmp / "state.json"
    p.write_text('{"judge_salt": "s"}')
    os.chmod(p, 0o600)
    pp.write_json_atomic(p, {"judge_salt": "s", "round": 2})
    got = stat.S_IMODE(p.stat().st_mode)
    check("F109 a 0600 JSON registry stays 0600", got == 0o600, oct(got))
    q = tmp / "note.txt"
    q.write_text("x")
    os.chmod(q, 0o600)
    pp.write_text_atomic(q, "y")
    gotq = stat.S_IMODE(q.stat().st_mode)
    check("F109 a 0600 text file stays 0600", gotq == 0o600, oct(gotq))
    r = tmp / "new.json"
    pp.write_json_atomic(r, {"x": 1})
    check("F109 a NEW file still gets the default mode",
          stat.S_IMODE(r.stat().st_mode) == (0o666 & ~_umask()), oct(stat.S_IMODE(r.stat().st_mode)))


def _umask() -> int:
    cur = os.umask(0)
    os.umask(cur)
    return cur


# ---------------------------------------------------------------- F110
def test_f110():
    print("\n== F110: an fsync failure is not swallowed ==")
    tmp = scratch("w2utils_f110_")
    p = tmp / "state.json"
    p.write_text("old")
    real = os.fsync

    def enospc(fd):
        raise OSError(28, "No space left on device")
    os.fsync = enospc
    try:
        raised = ""
        try:
            pp.write_json_atomic(p, {"new": True})
        except OSError as exc:
            raised = f"{type(exc).__name__}: {exc}"
    finally:
        os.fsync = real
    check("F110 ENOSPC aborts the write", "ENOSPC" in raised or "No space" in raised, raised)
    check("F110 the destination keeps its old bytes", p.read_text() == "old", p.read_text())

    def eio(fd):
        raise OSError(5, "Input/output error")
    os.fsync = eio
    try:
        raised = ""
        try:
            pp.write_text_atomic(tmp / "x.txt", "x")
        except OSError as exc:
            raised = str(exc)
    finally:
        os.fsync = real
    check("F110 EIO aborts the write", bool(raised), raised)

    def unsupported(fd):
        raise OSError(22, "Invalid argument")
    os.fsync = unsupported
    try:
        pp.write_text_atomic(tmp / "ok.txt", "ok")
        ok = (tmp / "ok.txt").read_text() == "ok"
    finally:
        os.fsync = real
    check("F110 EINVAL (fsync unsupported) is still best-effort", ok)


# ---------------------------------------------------------------- F111
def test_f111():
    print("\n== F111: the parent directory is fsynced after the rename ==")
    tmp = scratch("w2utils_f111_")
    p = tmp / "dur.json"
    p.write_text("old")
    seen = []
    real = os.fsync

    def record(fd):
        st = os.fstat(fd)
        seen.append((stat.S_ISDIR(st.st_mode), st.st_ino))
        return real(fd)
    os.fsync = record
    try:
        pp.write_json_atomic(p, {"new": True})
    finally:
        os.fsync = real
    parent_ino = p.parent.stat().st_ino
    check("F111 the parent directory inode reaches fsync",
          (True, parent_ino) in seen, f"{seen} parent={parent_ino}")


# ---------------------------------------------------------------- F113
def test_f113():
    print("\n== F113: UTF-16 text is decoded, not scanned as NUL mojibake ==")
    tmp = scratch("w2utils_f113_")
    p = tmp / "paper.md"
    p.write_bytes("# Abstract\n\nA short abstract with real words in it.\n\n"
                  "# Introduction\n\nBody text here.\n".encode("utf-16-le"))
    text = pp.read_text_bounded(p)
    check("F113 UTF-16LE decodes to real prose", text.startswith("# Abstract"), repr(text[:20]))
    info = pp.scan_lengths_in_sources([(tmp, "", ())])
    sections = {r.get("section") for r in info["rows"]}
    check("F113 the length scan finds the abstract", "abstract" in sections, str(sections))
    check("F113 the file is not silently skipped", "paper.md" not in info["skipped"],
          str(info["skipped"]))


# ---------------------------------------------------------------- F114
def test_f114():
    print("\n== F114: the empty-string policy value resolves like the formatter's ==")
    fmt = pp._format_module()
    for value in ("", "off", "false", "no", "0", "on", "true", None, True, False):
        mine = pp._policy_flag({"figure_ocr": value}, "figure_ocr", True)
        theirs = fmt._policy_flag({"figure_ocr": value}, "figure_ocr", True)
        check(f"F114 {value!r} resolves identically", mine == theirs, f"{mine} vs {theirs}")


# ---------------------------------------------------------------- F115
def test_f115():
    print("\n== F115: a deleted document is not paired with the output main text ==")
    tmp = scratch("w2utils_f115_")
    base, out = tmp / "base", tmp / "out"
    base.mkdir(), out.mkdir()
    (base / "appendix.docx").write_bytes(b"base appendix")
    (out / "mainText.docx").write_bytes(b"main")
    (out / "cover.docx").write_bytes(b"cover")
    pairs = []

    class Fake:
        def zotero_report_for_docx(self, path):
            return {"name": Path(path).name}

        def zotero_field_continuity_problems(self, before, after):
            pairs.append((before["name"], after["name"]))
            return {"baseline_fields": 0, "output_fields": 0, "errors": [],
                    "warnings": [], "deleted": [], "added": [], "edited": [],
                    "plain_text": []}

    real = pp._format_module
    pp._format_module = lambda: Fake()
    try:
        pp.zotero_field_continuity_check(base, out, "t", [], [])
    finally:
        pp._format_module = real
    check("F115 the unmatched appendix is NOT compared to mainText.docx",
          pairs == [], str(pairs))

    # A real non-main rename is still paired (the fix must not over-restrict).
    base2, out2 = tmp / "base2", tmp / "out2"
    base2.mkdir(), out2.mkdir()
    (base2 / "supplementary.docx").write_bytes(b"s")
    (out2 / "suppMaterial.docx").write_bytes(b"s")
    pairs2 = []

    class Fake2(Fake):
        def zotero_field_continuity_problems(self, before, after):
            pairs2.append((before["name"], after["name"]))
            return super().zotero_field_continuity_problems(before, after)

    pp._format_module = lambda: Fake2()
    try:
        pp.zotero_field_continuity_check(base2, out2, "t", [], [])
    finally:
        pp._format_module = real
    check("F115 a supplementary rename is still compared",
          len(pairs2) == 1, str(pairs2))


# ---------------------------------------------------------------- F118
def test_f118():
    print("\n== F118: an unreadable base directory is named by the document-set check ==")
    tmp = scratch("w2utils_f118_")
    base, cand = tmp / "base", tmp / "cand"
    base.mkdir(), cand.mkdir()
    (base / "mainText.docx").write_text("same bytes")
    (cand / "mainText.docx").write_text("same bytes")
    supp = base / "supp"
    supp.mkdir()
    (supp / "Table-S1.docx").write_text("supp content")
    os.chmod(supp, 0)
    try:
        if IS_ROOT:
            check("F118 (root: chmod-000 is still readable; check skipped)", True)
            return
        got = pp.document_set_check([(base, "", ())], [(cand, "", ())])
        check("F118 the unreadable base directory is named",
              got.get("unreadable_dirs") == ["supp"], str(got))
        check("F118 the stage postcheck surfaces the gap",
              "unreadable_dirs" in (WS / "paper_pipeline_parts" /
                                    "p06_postchecks.py").read_text("utf-8"))
    finally:
        _restore_writable(supp)


# ---------------------------------------------------------------- F119
def test_f119():
    print("\n== F119: two different unreadable files are not a rename pair ==")
    tmp = scratch("w2utils_f119_")
    base, cand = tmp / "base", tmp / "cand"
    base.mkdir(), cand.mkdir()
    a = base / "fig1.pdf"
    a.write_text("base figure bytes")
    b = cand / "other.pdf"
    b.write_text("a DIFFERENT figure")
    os.chmod(a, 0)
    os.chmod(b, 0)
    try:
        if IS_ROOT:
            check("F119 (root: chmod-000 is still readable; check skipped)", True)
            return
        got = pp.document_set_check([(base, "", ())], [(cand, "", ())])
        check("F119 the invented unreadable file is reported as added",
              got["added_non_editable"] == ["other.pdf"], str(got))
        check("F119 it is not reported as content-preserved under another name",
              got["content_preserved_under_other_name"] == [], str(got))
    finally:
        _restore_writable(a)
        _restore_writable(b)


# ---------------------------------------------------------------- F120
def test_f120():
    print("\n== F120: rmtree_force reports a surviving tree as failure ==")
    tmp = scratch("w2utils_f120_")
    tree = tmp / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("x")
    sub = tree / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("y")
    os.chmod(sub, 0o500)

    def deny(path, mode, *a, **k):
        raise OSError(30, "Read-only file system")
    try:
        with mock.patch("os.chmod", deny):
            ok = pp.rmtree_force(tree)
        check("F120 a surviving tree is reported as NOT removed", ok is False, str(ok))
        check("F120 the tree is still there", tree.exists() and (sub / "b.txt").exists())
    finally:
        _restore_writable(tree)


# ---------------------------------------------------------------- F121
def test_f121():
    print("\n== F121: an unsupported-compression template part does not crash ==")
    tmp = scratch("w2utils_f121_")
    p = tmp / "tpl.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/theme/theme1.xml", b"<a:theme/>" * 10)
    raw = bytearray(p.read_bytes())
    target = b"word/theme/theme1.xml"
    for tag, off in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        i = 0
        while True:
            i = raw.find(tag, i)
            if i < 0:
                break
            nlen = struct.unpack("<H", raw[(i + 28 if tag == b"PK\x01\x02" else i + 26):][:2])[0]
            name = bytes(raw[(i + 46 if tag == b"PK\x01\x02" else i + 30):][:nlen])
            if name == target:
                raw[i + off:i + off + 2] = struct.pack("<H", 99)
            i += 4
    p.write_bytes(bytes(raw))
    raised = ""
    try:
        got = pp._protected_template_parts(p)
    except BaseException as exc:                                       # noqa: BLE001
        got, raised = {}, f"{type(exc).__name__}: {exc}"
    check("F121 the unreadable template part is caught, not raised", not raised, raised)
    check("F121 the reader falls back to no protected parts", got == {}, str(got))


# ---------------------------------------------------------------- F122
def test_f122():
    print("\n== F122: an unreadable template is unverified, not 'no furniture' ==")
    tmp = scratch("w2utils_f122_")
    bad = tmp / "template.docx"
    bad.write_bytes(b"this is not a zip file")
    sig = pp._docx_hf_signature(bad)
    gap = pp._hf_gap(sig, {})
    check("F122 the signature marks the document unreadable", sig.get("unreadable") is True,
          str(sig))
    check("F122 the header/footer check reports unverified", bool(gap.get("unverified")),
          str(gap))


# ---------------------------------------------------------------- F123
def test_f123():
    print("\n== F123: a VML logo header belongs to the protected template parts ==")
    tmp = scratch("w2utils_f123_")
    p = tmp / "tpl.docx"
    doc = ('<w:document><w:body><w:sectPr><w:headerReference w:type="default" '
           'r:id="rId3"/></w:sectPr></w:body></w:document>')
    logo = ('<w:hdr><w:p><w:r><w:pict><v:shape><v:imagedata r:id="rId9"/>'
            '</v:shape></w:pict></w:r></w:p></w:hdr>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/header1.xml", logo)
        z.writestr("word/theme/theme1.xml", "<a:theme/>")
    protected = pp._protected_template_parts(p)
    check("F123 the logo header is required byte-for-byte",
          "word/header1.xml" in protected, str(sorted(protected)))
    check("F123 the theme is still required", "word/theme/theme1.xml" in protected,
          str(sorted(protected)))


# ---------------------------------------------------------------- F124
def test_f124():
    print("\n== F124: a Word owner file is not a submission document ==")
    tmp = scratch("w2utils_f124_")
    base, cand = tmp / "base", tmp / "cand"
    base.mkdir(), cand.mkdir()
    (base / "mainText.docx").write_text("same")
    (cand / "mainText.docx").write_text("same")
    (base / "~$mainText.docx").write_text("owner name blob")
    collected = sorted(pp.collect_documents([(base, "", ())]))
    got = pp.document_set_check([(base, "", ())], [(cand, "", ())])
    check("F124 the owner file is not collected", collected == ["maintext.docx"],
          str(collected))
    check("F124 it is not reported as a lost document", got["missing"] == [], str(got))


# ---------------------------------------------------------------- F125
def test_f125():
    print("\n== F125: a README that mentions CHANGELOG.md stays documentation ==")
    tmp = scratch("w2utils_f125_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    readme = pkg / "README.md"
    readme.write_text("# Analysis code\n\nRun `python analyze.py`. "
                      "See CHANGELOG.md for the version history.\n")
    rows = pp.readme_internal_note_rows(readme)
    held = pp.hold_internal_readme_notes(pkg, tmp / "reports" / "readme_notes" / "a1")
    check("F125 a bare CHANGELOG.md cross-reference is not an internal note", rows == [], str(rows))
    check("F125 the author README is not moved out of the package",
          held == [] and readme.exists(), str(held))

    # A real pipeline-artifact name is still held back.
    bad = pkg / "README_RUN.md"
    bad.write_text("See REVISION_REPORT.md and MANUAL_STEPS.md for the hand-off.\n")
    rows_bad = pp.readme_internal_note_rows(bad)
    check("F125 a real stage-report reference is still flagged", bool(rows_bad), str(rows_bad))


# ---------------------------------------------------------------- F126
def test_f126():
    print("\n== F126: the rebuilt template package carries no bookkeeping ==")
    tmp = scratch("w2utils_f126_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    for n in ("mainText.docx", "CHANGELOG.md", "MANUAL_STEPS.md", "DIFF_LEDGER.md",
              "REVISION_REPORT.md", "revision_report.json"):
        (pkg / n).write_text("x")
    (pkg / "figure.png").write_text("img")
    (pkg / "work").mkdir()
    (pkg / "work" / "scratch.md").write_text("x")
    rels = [p.relative_to(pkg).as_posix() for p in pp.template_package_files(pkg)]
    carried = sorted(r for r in rels if pp.is_bookkeeping_name(Path(r).name))
    check("F126 no bookkeeping file is carried", carried == [], str(carried))
    check("F126 the manuscript and the figure are still carried",
          sorted(rels) == ["figure.png", "mainText.docx"], str(sorted(rels)))


# ---------------------------------------------------------------- F127
def test_f127():
    print("\n== F127: captioned Markdown and real LaTeX tables are producers ==")
    tmp = scratch("w2utils_f127_")
    (tmp / "table_with_title.md").write_text(
        "Table 1. Cohort characteristics\n| group | n |\n|---|---|\n| A | 10 |\n")
    (tmp / "bare_table.md").write_text("| group | n |\n|---|---|\n| A | 10 |\n")
    (tmp / "table.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\begin{table}\n"
        "\\begin{tabular}{ll}\ngroup & n \\\\\nA & 10 \\\\\n\\end{tabular}\n"
        "\\end{table}\n\\end{document}\n")
    (tmp / "prose.md").write_text("This is a prose note with no table at all.\n")
    found = sorted(rel for rel, _text in pp.data_table_texts([(tmp, "", ())]))
    check("F127 a captioned Markdown table is read",
          "table_with_title.md" in found, str(found))
    check("F127 a real LaTeX table is read", "table.tex" in found, str(found))
    check("F127 prose is still not a producer", "prose.md" not in found, str(found))


# ---------------------------------------------------------------- F129
def test_f129():
    print("\n== F129: rename-key pairing runs before the content-only pass ==")
    tmp = scratch("w2utils_f129_")
    base, cand = tmp / "base", tmp / "cand"
    base.mkdir(), cand.mkdir()
    (base / "mainText-4f3a9c1.docx").write_text("identical placeholder bytes")
    (base / "supplementary.docx").write_text("identical placeholder bytes")
    (cand / "mainText-9b2c1d3.docx").write_text("identical placeholder bytes EDITED")
    (cand / "supplementary.docx").write_text("identical placeholder bytes")
    got = pp.document_set_check([(base, "", ())], [(cand, "", ())])
    check("F129 no document is falsely reported missing", got["missing"] == [], str(got))
    check("F129 no document is falsely reported added", got["added"] == [], str(got))


# ---------------------------------------------------------------- F130
def test_f130():
    print("\n== F130: ensure_copy repairs a plain-file destination ==")
    tmp = scratch("w2utils_f130_")
    src = tmp / "src"
    src.mkdir()
    (src / "a.txt").write_text("A")
    dst = tmp / "dst"
    dst.write_text("planted FILE where a directory is expected")
    raised = ""
    rebuilt = False
    try:
        rebuilt = pp.ensure_copy(src, dst)
    except BaseException as exc:                                       # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("F130 the materializer does not abort", not raised, raised)
    check("F130 the destination is rebuilt as a directory", dst.is_dir(), str(dst))
    check("F130 the copied file is there", (dst / "a.txt").read_text() == "A")
    check("F130 the rebuild reports True", rebuilt is True, str(rebuilt))


# ---------------------------------------------------------------- F131
def test_f131():
    print("\n== F131: a failed scan renders as an ERROR, not a clean zero ==")
    ev = {"captions": {"error": "boom"}, "lengths": {"error": "boom"},
          "format": {"error": "boom"}, "placeholders": {"error": "boom"},
          "corpus_identity": {"error": "boom"}}
    summary = pp.evidence_pack_summary(ev)
    check("F131 M19 names the error", "M19 ERROR(boom)" in summary, summary)
    check("F131 M20 names the error", "M20 ERROR(boom)" in summary, summary)
    check("F131 no failed scan reads as 0 rows", "0 row(s)" not in summary, summary)
    good = {"lengths": {"rows": [], "over_limit": []},
            "format": {"rows": [], "high": 0}, "captions": {"count": 0},
            "placeholders": {"count": 0}, "corpus_identity": {"digest": "abc"}}
    summary2 = pp.evidence_pack_summary(good)
    check("F131 a genuinely empty scan still reads 0", "M19 0 section(s)" in summary2, summary2)


def main() -> int:
    try:
        test_f103()
        test_f104()
        test_f105()
        test_f106()
        test_f107()
        test_f108()
        test_f109()
        test_f110()
        test_f111()
        test_f113()
        test_f114()
        test_f115()
        test_f118()
        test_f119()
        test_f120()
        test_f121()
        test_f122()
        test_f123()
        test_f124()
        test_f125()
        test_f126()
        test_f127()
        test_f129()
        test_f130()
        test_f131()
        print()
        if FAILS:
            print(f"FAILED {len(FAILS)} check(s):")
            for name in FAILS:
                print(f"  - {name}")
            return 1
        print("ALL UTILS WAVE-2 CHECKS PASSED")
        return 0
    finally:
        for d in TMPDIRS:
            _restore_writable(d)
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

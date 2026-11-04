#!/usr/bin/env python3
"""Regression checks for the 2026-11-04 fix-bugs wave 1.

Every check below failed on the pre-fix tree and pins one candidate from the
verified-findings set (F01 .. F79).  Run:

    python3 .paper_test/test_fix_bugs_20261104_stage.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs20261104_pp", "paper_pipeline.py")
pf = load("fixbugs20261104_pf", "paper_docx_format.py")
ec = load("fixbugs20261104_ec", "paper-skills/paper-review/scripts/extract_citations.py")
eo = load("fixbugs20261104_eo", "paper-skills/paper-review/scripts/extract_occurrences.py")
en = load("fixbugs20261104_en", "paper-skills/paper-review/scripts/extract_numbers.py")
cw = load("fixbugs20261104_cw", "paper-skills/paper-review/scripts/count_words.py")
qa = load("fixbugs20261104_qa", "paper_qwen_agent.py")
ps = load("fixbugs20261104_ps", "pairwise_scores.py")
cc = load("fixbugs20261104_cc", "paper-skills/paper-review/scripts/convert_corpus.py")


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def _docx_part(body="", prefix="w", encoding="utf-8"):
    text = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<{prefix}:document xmlns:{prefix}="{WORD_NS}"><{prefix}:body>{body}'
            f'</{prefix}:body></{prefix}:document>')
    return text.encode(encoding)


def _zip_bytes(parts: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, payload in parts.items():
            z.writestr(name, payload)
    return buf.getvalue()


def _docx_file(body="", *, extra=None, encoding="utf-8", prefix="w") -> str:
    p = scratch("fixbt_docx_") / "fixture.docx"
    parts = {"word/document.xml": _docx_part(body, prefix=prefix, encoding=encoding)}
    parts.update(extra or {})
    p.write_bytes(_zip_bytes(parts))
    return str(p)


def _sanitize_docx(body="", *, prefix="w", encoding="utf-8", file_map=None):
    data, notes = pp._sanitize_ooxml_bytes(
        _zip_bytes({"word/document.xml": _docx_part(body, prefix=prefix,
                                                    encoding=encoding)}),
        file_map=file_map, old_rel="main.docx")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read("word/document.xml"), notes


def _extract(files: dict) -> dict:
    d = scratch("fixbt_corp_")
    work = d / "work"
    (work / "corpus").mkdir(parents=True)
    for name, text in files.items():
        (work / "corpus" / name).write_text(text, encoding="utf-8")
    old = sys.argv
    sys.argv = ["extract_citations.py", "--work", str(work), "--out", str(d / "out")]
    try:
        ec.main()
    finally:
        sys.argv = old
    return json.loads((d / "out" / "artifacts" / "M2_citations.json").read_text())


def test_number_proof():
    print("\n== F01/F02: a table proof is bound to row and source ==")
    rows = [{"number": "42", "sentence": "The control cohort age was 42 years.",
             "kind": "body"}]
    out = pf.reconcile_number_rows(
        rows, [("ages.csv", "cohort,age\ncontrol,19\ntreatment,42\n")])
    check("F01 a control-cohort claim is not proved by the treatment row",
          out["filled"] == 0 and rows[0].get("status") != "proved", str(rows[0]))
    rows = [{"number": "42", "sentence": "We observed 42 cells.", "kind": "body"}]
    out = pf.reconcile_number_rows(rows, [
        ("alpha.csv", "age,note\n42,foo\n0,bar\n"),
        ("beta.csv", "cells,note\n42,foo\n0,bar\n")])
    check("F02 a later compatible source proves the claim",
          out["filled"] == 1 and "cells" in rows[0].get("source", ""), str(rows[0]))


def test_repair_bounds():
    print("\n== F03/F05/F06/F07/F11: bounded-repair and timeout guards ==")
    d = scratch("fixbt_repair_")
    (d / "pre").mkdir()
    (d / "cur").mkdir()
    (d / "pre" / "m.md").write_text("A = 10 and B = 10\n")
    (d / "cur" / "m.md").write_text("A = 20 and B = 20\n")
    check("F03 a second same-value edit is outside the quoted span",
          pp._repair_spans_cover(d / "pre", d / "cur", "m.md",
                                 [("A = 10", "A = 20")]) is not None)
    (d / "cur" / "m.md").write_text("A = 20 and B = 10\n")
    check("F03 the authorized edit alone still passes",
          pp._repair_spans_cover(d / "pre", d / "cur", "m.md",
                                 [("A = 10", "A = 20")]) is None)
    (d / "cur" / "calc.py").write_text("n=20\nsecret=999\n")
    (d / "pre" / "calc.py").write_text("n=10\nsecret=1\n")
    check("F05 a .py repair is span-checked, not file-level only",
          pp._repair_spans_cover(d / "pre", d / "cur", "calc.py",
                                 [("n=10", "n=20")]) is not None)
    rows = [{"id": "R1", "file": "m2.md", "wrong": "10", "correct": "20",
             "status": "confirmed"}]
    f6 = scratch("fixbt_f06_")
    (f6 / "pre").mkdir()
    (f6 / "cur").mkdir()
    (f6 / "pre" / "m2.md").write_text("A = 10\n")
    (f6 / "cur" / "m2.md").write_text("A = 10\n")
    check("F06 a confirmed no-op repair is a violation",
          pp._revised_repair_violations(f6 / "pre", f6 / "cur", rows, {"R1"}) == ["m2.md"])
    (f6 / "cur" / "m2.md").write_text("A = 20\n")
    check("F06 the applied repair passes",
          pp._revised_repair_violations(f6 / "pre", f6 / "cur", rows, {"R1"}) == [])
    base = scratch("fixbt_base_")
    (base / "x.md").write_text("A\n")
    dig1 = pp.manifest_digest(pp.hash_manifest(base, follow_dir_links=True))
    (base / "x.md").write_text("B\n")
    dig2 = pp.manifest_digest(pp.hash_manifest(base, follow_dir_links=True))
    check("F07 the trusted baseline digest changes when the snapshot is modified",
          dig1 != dig2)
    # Why the digest is needed: rewriting BOTH sides to the same unplanned
    # content leaves the pre/post comparison with nothing to report.
    same = scratch("fixbt_f07same_")
    (same / "pre").mkdir()
    (same / "cur").mkdir()
    (same / "pre" / "m.md").write_text("unplanned\n")
    (same / "cur" / "m.md").write_text("unplanned\n")
    check("F07 the pre/post comparison alone cannot detect a rewritten baseline",
          pp._revised_repair_violations(same / "pre", same / "cur",
                                        [{"id": "R1", "file": "m.md"}], {"R1"}) == [])
    # F11: a TERM-ignoring child must die with its leader.
    t = scratch("fixbt_tree_")
    pidfile = t / "child.pid"
    child = t / "child.py"
    child.write_text("import os,signal,time\n"
                     "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                     f"open({str(pidfile)!r},'w').write(str(os.getpid()))\n"
                     "time.sleep(30)\n")
    parent = t / "parent.py"
    parent.write_text("import subprocess,sys\n"
                      f"subprocess.Popen([sys.executable,{str(child)!r}])\n")
    proc = subprocess.Popen([sys.executable, str(parent)], start_new_session=True)
    for _ in range(50):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.1)
    cpid = int(pidfile.read_text().strip())
    pp._terminate_agent_tree(proc)
    time.sleep(0.4)
    try:
        state = Path(f"/proc/{cpid}/stat").read_text().split()[2]
    except OSError:
        state = "gone"
    check("F11 a TERM-ignoring descendant does not survive the leader",
          state in ("gone", "Z"), state)
    if state not in ("gone",):
        try:
            os.kill(cpid, signal.SIGKILL)
        except OSError:
            pass


def test_view_references():
    print("\n== F10/F12-F17/F77: judge-view reference rewriting ==")
    f = pp._rewrite_view_references
    check("F12 \\usepackage follows the renamed .sty",
          f(r"\usepackage{local}", "local.sty", "f2.sty",
            {"local.sty": "f2.sty"}) == r"\usepackage{f2}")
    check("F12 \\documentclass follows the renamed .cls",
          f(r"\documentclass{custom}", "custom.cls", "f2.cls",
            {"custom.cls": "f2.cls"}) == r"\documentclass{f2}")
    check("F12 \\bibliographystyle follows the renamed .bst",
          f(r"\bibliographystyle{local}", "refs/local.bst", "d01/f2.bst",
            {"refs/local.bst": "d01/f2.bst"}) == r"\bibliographystyle{f2}")
    check("F13 a starred \\includegraphics is rewritten",
          f(r"\includegraphics*{plot}", "plot.pdf", "f2.pdf",
            {"plot.pdf": "f2.pdf"}) == r"\includegraphics*{f2}")
    check("F14 \\import rewrites BOTH arguments",
          f(r"\import{chapters/}{intro}", "chapters/intro.tex", "d01/f2.tex",
            {"chapters/intro.tex": "d01/f2.tex"}) == r"\import{d01/}{f2}")
    check("F15 a renamed Python module's import is rewritten",
          f("import helper\nprint(helper.value)", "helper.py", "f2.py",
            {"helper.py": "f2.py"}).startswith("import f2\n"))
    check("F16 an external URL is byte-identical",
          f("https://example.org/data.csv", "data.csv", "f2.csv",
            {"data.csv": "f2.csv"}) == "https://example.org/data.csv")
    out = f(r"\input{part.tex}", "b/main.tex", "b/main.tex",
            {"a/part.tex": "d01/f2.tex", "b/part.tex": "d02/f3.tex"})
    check("F17 an ambiguous basename resolves against the referring directory",
          "f2" not in out and "f3" in out, out)
    check("F77 a remote identifier keeps a token-shaped path segment",
          pp._normalize_version_refs(b"https://data.example/paper-1234567.csv", [])
          == b"https://data.example/paper-1234567.csv")
    # F10: the expected-view cache keys on the relative layout, not bytes alone.
    lay = scratch("fixbt_layout_")
    (lay / "main.tex").write_text(r"\input{data.csv}")
    (lay / "data.csv").write_text("x")
    ctx = type("C", (), {"root": lay})()
    old = pp.corpus_files_for_view
    try:
        pp._VIEW_EXPECT_CACHE.clear()
        pp.corpus_files_for_view = lambda *_a: [
            ("main.tex", lay / "main.tex"), ("data.csv", lay / "data.csv")]
        a = pp.expected_view_digest(ctx, 1, "v1", "seed")
        pp.corpus_files_for_view = lambda *_a: [
            ("main.tex", lay / "main.tex"), ("renamed.csv", lay / "data.csv")]
        b = pp.expected_view_digest(ctx, 1, "v1", "seed")
    finally:
        pp.corpus_files_for_view = old
    check("F10 a same-content rename does not reuse the old expected view", a != b)


def test_ooxml():
    print("\n== F18-F23: OOXML sanitization and its warnings ==")
    parts = {"word/document.xml": _docx_part("<w:p/>"),
             "word/_rels/document.xml.rels":
                 b'<Relationships><Relationship Id="rId1" Target="supplement.docx" '
                 b'TargetMode="External" Type="hyperlink"/></Relationships>'}
    data, _ = pp._sanitize_ooxml_bytes(
        _zip_bytes(parts), file_map={"main.docx": "f1.docx",
                                     "supplement.docx": "f2.docx"},
        old_rel="main.docx")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    check("F18 a package hyperlink follows the renamed member",
          'Target="f2.docx"' in rels, rels)
    body = ('<w:tbl><w:tr><w:trPr><w:del w:id="1" w:author="r1_w1"/></w:trPr>'
            '<w:tc><w:p><w:r><w:t>DELETED ROW</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    xml, _ = _sanitize_docx(body)
    check("F19 a deleted table row is not accepted content", b"DELETED ROW" not in xml)
    data, _ = pp._sanitize_ooxml_bytes(_zip_bytes({
        "xl/comments1.xml": b"<comments><authors><author>r1_w1 generated by model X"
                            b"</author></authors><commentList/></comments>"}))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        comments = z.read("xl/comments1.xml").decode("utf-8")
    check("F20 a spreadsheet comment author is blanked",
          "r1_w1" not in comments and "<author>author</author>" in comments, comments)
    xml, _ = _sanitize_docx(
        '<a:p><a:del a:author="r1_w1"><a:r><a:delText>DELETED</a:delText></a:r>'
        "</a:del></a:p>", prefix="a")
    check("F21 a legal non-w Word prefix is sanitized",
          b"DELETED" not in xml and b"r1_w1" not in xml, xml[:160])
    data, _ = _sanitize_docx(
        '<w:p><w:del w:author="r1_w1"><w:r><w:delText>DELETED</w:delText></w:r>'
        "</w:del></w:p>", encoding="utf-16")
    check("F22 UTF-16 OOXML is decoded and sanitized",
          b"DELETED" not in data and b"r1_w1" not in data, data[:160])
    # F23: a failed sanitization is persisted in the state record.
    warn = scratch("fixbt_warn_")
    (warn / "broken.docx").write_bytes(b"not a zip")
    warnings = {}

    class C:
        root = warn
        state = {}

        def save_state(self):
            warnings["saved"] = True

    c = C()
    old = pp.corpus_files_for_view
    try:
        pp.corpus_files_for_view = lambda *_a: [("broken.docx", warn / "broken.docx")]
        pp.build_judge_view(c, 1, "a1", warn / "view", time.time(), "seed")
    finally:
        pp.corpus_files_for_view = old
    rec = c.state.get("view_transform_warnings") or {}
    check("F23 an unresolved sanitizer gap reaches the state record",
          warnings.get("saved") and any("not a readable OOXML" in n
                                        for notes in rec.values() for n in notes), rec)


def test_convert_corpus():
    print("\n== F24-F41: review converter ==")
    lines, _ = cc.docx_part_to_lines(
        f'<a:document xmlns:a="{WORD_NS}"><a:body><a:p><a:r><a:t>Visible text'
        "</a:t></a:r></a:p></a:body></a:document>")
    check("F24 another Word namespace prefix yields the same text",
          lines == ["Visible text"], lines)
    text, _ = cc.docx_to_text(_docx_file(
        "<w:p><w:r><w:t>Visible text</w:t></w:r></w:p>", encoding="utf-16"))
    check("F25 a UTF-16 DOCX keeps its text", text == "Visible text", text)
    text, _ = cc.docx_to_text(_docx_file(
        "<w:p><w:moveFrom><w:r><w:t>old position</w:t></w:r></w:moveFrom></w:p>"
        "<w:p><w:moveTo><w:r><w:t>new position</w:t></w:r></w:moveTo></w:p>"))
    check("F26 moved-from content is not current prose",
          "old position" not in text and "new position" in text, text)
    text, notes = cc.docx_to_text(_docx_file(
        "<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>Hidden rejected value 17</w:t>"
        "</w:r></w:p><w:p><w:r><w:t>Visible value 19</w:t></w:r></w:p>"))
    check("F27 hidden text is omitted with a visibility note",
          "Hidden rejected" not in text and any("hidden" in n for n in notes),
          f"{text!r} {notes!r}")
    bare = cc.convert_one(_docx_file(""), "x.docx")
    noted = cc.convert_one(_docx_file("", extra={
        "docProps/core.xml": b'<cp:coreProperties xmlns:cp="x" xmlns:dc="y">'
                             b"<dc:creator>r1_w1</dc:creator></cp:coreProperties>"}),
        "x.docx")
    check("F29 an empty readable DOCX is converted-empty either way",
          bare["status"] == noted["status"] == "converted-empty",
          f"{bare['status']} vs {noted['status']}")
    lines, _ = cc.docx_part_to_lines(
        f'<w:document xmlns:w="{WORD_NS}"><w:body><!-- <w:p><w:r><w:t>Not '
        'visible: n=500</w:t></w:r></w:p> --><w:p><w:r><w:t>Visible n=50</w:t>'
        "</w:r></w:p></w:body></w:document>")
    check("F30 an XML comment is not manuscript text",
          lines == ["Visible n=50"], lines)
    check("F31 all inline-string runs are kept",
          cc._xlsx_cell_value("t=\"inlineStr\"",
                              "<is><r><t>alpha </t></r><r><t>beta</t></r></is>", {})
          == "alpha beta")
    check("F33 SpreadsheetML escapes are decoded",
          cc._xlsx_cell_value("t=\"inlineStr\"",
                              "<is><t>alpha_x000A_beta</t></is>", {})
          == "alpha\nbeta")

    def rtf(content):
        p = scratch("fixbt_rtf_") / "x.rtf"
        p.write_text(content, encoding="latin-1")
        return cc.rtf_to_text(str(p))[0]

    check("F35 group-scoped ucN is honoured",
          rtf(r"{\rtf1\ansi \uc2\u945?? beta}") == "\u03b1 beta"
          and rtf(r"{\rtf1\ansi \uc0\u945X}") == "\u03b1X")
    check("F36 the declared code page decodes hex escapes",
          rtf("{\\rtf1\\ansi\\ansicpg1251 \\'cf\\'f0\\'e8\\'e2\\'e5\\'f2}")
          == "\u041f\u0440\u0438\u0432\u0435\u0442")
    check("F37 nonbreaking space/hyphen survive",
          rtf(r"{\rtf1\ansi alpha\~beta\_gamma}") == "alpha\u00a0beta\u2011gamma")
    check("F38 tracked-deleted RTF text is not current prose",
          rtf(r"{\rtf1\ansi visible {\deleted old result} current result}")
          == "visible current result")

    class R:
        returncode = 1
        stdout = b"first page only"
        stderr = b"Error: block not found on page 2"

    p = scratch("fixbt_pdf_") / "x.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    old = cc.subprocess.run
    cc.subprocess.run = lambda *_a, **_k: R()
    try:
        got = cc.convert_one(str(p), "x.pdf")
    finally:
        cc.subprocess.run = old
    check("F39 a non-zero pdftotext exit is not labeled converted",
          got["status"] == "converted-partial" and "pdftotext-incomplete" in " ".join(
              got["notes"]), str(got))

    def run_main(sub, work):
        old_argv = sys.argv
        sys.argv = ["convert_corpus.py", "--submission", str(sub), "--work", str(work)]
        try:
            cc.main()
        finally:
            sys.argv = old_argv

    d = scratch("fixbt_reconvert_")
    sub, work = d / "sub", d / "work"
    sub.mkdir()
    (sub / "a.md").write_text("A")
    run_main(sub, work)
    (sub / "a.md").unlink()
    (sub / "b.md").write_text("B")
    run_main(sub, work)
    check("F40 reconversion drops the removed document",
          sorted(os.listdir(work / "corpus")) == ["b.md.txt"],
          str(sorted(os.listdir(work / "corpus"))))
    d = scratch("fixbt_overlap_")
    sub, work = d / "sub", d / "sub" / "work"
    sub.mkdir()
    (sub / "b.md").write_text("B")
    run_main(sub, work)
    run_main(sub, work)
    inv = json.loads((work / "inventory.json").read_text())
    check("F41 a work dir inside the submission is not inventoried",
          sorted(x["path"] for x in inv) == ["b.md"], str([x["path"] for x in inv]))


def test_citations():
    print("\n== F42-F54: citation extraction ==")
    names = ("treatment_response.md.txt", "survey_responses.md.txt",
             "response_inhibition.md.txt")
    check("F42 scientific response filenames are manuscripts",
          not any(ec.is_non_manuscript(n) for n in names),
          str({n: ec.is_non_manuscript(n) for n in names}))
    check("F46 a parenthesis-delimited BibTeX entry supplies its key",
          ec.BIB_ENTRY_RE.findall("@article(present, title={X})") == ["present"])
    check("F47 a BibTeX directive is not an entry",
          ec.BIB_ENTRY_RE.findall("@comment{ghost, not a reference}") == [])
    check("F49 a non-ASCII surname is inventoried",
          bool(ec.AY_CIT_RE.search("(García, 2020)"))
          and bool(ec.AY_CIT_RE.search("(Åberg, 2020)")))
    check("F51 an inline verbatim sample is blanked",
          "cite" not in ec.latex_source_text(r"Example: \verb|\cite{ghost}|."))
    check("F52 a comment environment is blanked",
          "cite" not in ec.latex_source_text(
              r"\begin{comment}\cite{ghost}\end{comment}"))
    check("F54 text after \\endinput is not reviewed",
          "cite" not in ec.latex_source_text("text\n\\endinput\n\\cite{ghost}"))
    r = _extract({"main.md.txt": "# Main\n\nReferences\n\n1. One\n2. Two\n",
                  "supp.md.txt": "# Supp\n\nAs shown [1].\n\nReferences\n\n1. One\n"})
    check("F43 another document's citation does not mask an uncited list",
          r["uncited_entries_by_list"].get("main.md.txt") == [1, 2],
          str(r["uncited_entries_by_list"]))
    r = _extract({
        "a.tex.txt": "\\documentclass{article}\\begin{document}\\cite{b}\\end{document}\n",
        "b.tex.txt": ("\\documentclass{article}\\begin{document}"
                      "\\bibitem{b} X.\\end{document}\n")})
    check("F44 an unrelated document's \\bibitem cannot resolve a key",
          r["tex_orphan_keys_by_file"].get("a.tex.txt") == ["b"],
          str(r["tex_orphan_keys_by_file"]))
    r = _extract({"main.md.txt": "# Main\n\n(Smith, 2019; Jones, 2020).\n"})
    check("F48 a parenthesized author-year cluster yields every call-out",
          sorted(c["refs"][0] for c in r["callouts"]) == ["Jones 2020", "Smith 2019"],
          str(r["callouts"]))
    r = _extract({
        "a.tex.txt": ("\\documentclass{article}\\begin{document}"
                      "\\parencites{missing}{other}\\end{document}\n"),
        "r.bib.txt": "@article{missing, title={A}}\n@article{other, title={B}}\n"})
    check("F53 a multicite macro yields every key",
          sorted(c["key"] for c in r["tex_callouts"]) == ["missing", "other"],
          str(r["tex_callouts"]))
    r = _extract({"main.tex.txt": (
        "\\documentclass{article}\n\\begin{document}\n\\cite{alpha,\n beta}\n"
        "\\bibitem{alpha} A\n\\bibitem{beta} B\n\\end{document}\n")})
    check("F45 a multiline cite argument is inventoried",
          sorted(c["key"] for c in r["tex_callouts"]) == ["alpha", "beta"],
          str(r["tex_callouts"]))


def test_occurrences():
    print("\n== F55-F59: numeric occurrence variants ==")

    def m(term, text):
        return bool(eo.variant_pattern(term, "value").search(text))

    check("F55 an integer mantissa is not zero-padded",
          not m("5", "50e+00") and m("5", "5e+0"))
    check("F56 a scientific coefficient is not the whole number",
          not m("5", "5 \u00d7 10^2") and m("5", "5 \u00d7 10^0"))
    check("F57 a grouped value finds its plain spelling", m("1,234", "1234"))
    check("F58 an explicit positive sign names the same value",
          m("5", "+5") and not m("5", "-5"))
    check("F59 a large integer is not float-rounded",
          not m("9007199254740993", "9.007199254740992e+15")
          and m("9007199254740993", "9.007199254740993e+15"))


def test_numbers_and_words():
    print("\n== F60-F66: labeled metrics and word counting ==")

    def hits(label, text):
        return [m.groups() for lab, rx in en.LABEL_PATTERNS if lab == label
                for m in rx.finditer(text)]

    check("F60 a negative percentage keeps its sign",
          hits("percentage", "change = -12.5%") == [("-12.5",)])
    check("F61 signed/integer R2 values are inventoried",
          hits("R2", "R\u00b2=-0.25") == [("-0.25",)]
          and hits("R2", "R\u00b2=1") == [("1",)])
    check("F62 a multiplicative p-value keeps its magnitude",
          en._metric_key("p-value", hits("p-value", "p = 5 \u00d7 10^-8")[0][0])
          == "5e-08"
          and en._metric_key("p-value",
                             hits("p-value", "p = 5 \\times 10^{-8}")[0][0])
          == "5e-08"
          and en._metric_key("p-value",
                             hits("p-value", "p = 5 \u00d7 10\u207b\u2078")[0][0])
          == "5e-08")
    check("F63 a parenthesized confidence interval is inventoried",
          hits("CI", "95% CI (0.2, 0.5)") == [("0.2", "0.5")])
    check("F65 distinct large counts keep distinct keys",
          en._metric_key("n", "9007199254740992")
          != en._metric_key("n", "9007199254740993"))
    text = r"We use \textcite{smith2020} and \parencite{jones2021}."
    check("F66 citation keys are not manuscript words",
          "smith2020" not in cw._strip_latex(text)
          and "jones2021" not in cw._strip_latex(text), cw._strip_latex(text))


def test_qwen_and_pairwise():
    print("\n== F67/F68/F71/F72/F73: chat/harness and pairwise identity ==")
    cfg = {"base_url": "http://x", "model": "m", "max_tokens": 10, "api_key": "k"}
    old = qa._request
    try:
        qa._request = lambda *_a, **_k: (200, {"choices": [{
            "finish_reason": "stop",
            "message": {"content": None, "reasoning_content": "Let me think..."}}]}, "")
        text, err = qa.chat_text(cfg, "hi")
        check("F67 a reasoning-only response is not the final answer",
              text == "" and "reasoning" in err, f"{text!r} {err!r}")
        qa._request = lambda *_a, **_k: (200, {"choices": [{
            "finish_reason": "content_filter",
            "message": {"content": "partial", "reasoning_content": None}}]}, "")
        text, err = qa.chat_text(cfg, "hi")
        check("F68 a content-filtered response is an incomplete answer",
              text == "" and "content_filter" in err, f"{text!r} {err!r}")
    finally:
        qa._request = old
    check("F71 a cancelled turn is a failure",
          qa._dsh_turn_failed(b'{"type":"turn_end","status":"cancelled"}') is True
          and qa._dsh_turn_failed(b'{"type":"turn_end","status":"ok"}') is False)
    d = scratch("fixbt_pair_")
    paths = []
    for sub, score in (("x", 1), ("y", -1)):
        rd = d / sub / "run" / "reports"
        rd.mkdir(parents=True)
        p = rd / "round1_raw_scores.csv"
        p.write_text("member,opponent_id,direction,credited\na,b,own,%d\n" % score)
        paths.append(p)
    cubes = ps.collect(paths, "mean", True, True)[0]
    check("F72 same-basename runs stay distinct",
          len(cubes) == 2
          and sorted(v for rounds in cubes.values()
                     for pairs in rounds.values()
                     for ps_obj in pairs.values() for v in ps_obj.values)
          == [-1.0, 1.0], str(cubes.keys()))
    used = set()
    a = ps.sheet_tab("ABC", "1", used)
    b = ps.sheet_tab("abc", "1", used)
    check("F73 sheet names are reserved case-insensitively",
          a.casefold() != b.casefold(), f"{a} vs {b}")


def test_pdf_and_prompts():
    print("\n== F74/F76/F78/F79: PDF roots and prompt dispositions ==")
    d = scratch("fixbt_pdfroot_")
    (d / "fragment.tex").write_text("% \\documentclass{article}\n\\section{x}\n")
    (d / "sample.tex").write_text(
        "\\begin{verbatim}\n\\documentclass{article}\n\\end{verbatim}\n")
    check("F74 a commented/verbatim documentclass is not a root",
          pp.latex_root_documents(d) == [], str(pp.latex_root_documents(d)))
    src = scratch("fixbt_pdfsrc_")
    (src / "main.tex").write_text("\\documentclass{article}\n")
    (src / "main.ltx").write_text("\\documentclass{article}\n")
    out = scratch("fixbt_pdfout_") / "label"
    out.mkdir(parents=True)
    old_compile = pp.compile_latex_pdf

    def fake_compile(pkg, rel, out_pdf, **_kw):
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        out_pdf.write_bytes(b"%PDF-1.4 " + rel.encode())
        return {"ok": True, "tool": "stub", "pages": 1}

    pp.compile_latex_pdf = fake_compile
    try:
        ctx = type("C", (), {"root": out.parent})()
        docs = pp.render_pdf_set(ctx, "label", [(src, "", set())], out)
    finally:
        pp.compile_latex_pdf = old_compile
    outs = [x["out"] for x in docs]
    check("F76 same-stem tex/ltx roots get distinct PDF targets",
          len(outs) == len(set(outs)) == 2, str(outs))
    revise = pp.REVISE_DIRECTIVES
    check("F78 the revise prompt no longer authorizes substantive I-xxx repairs",
          "Rigor repairs are legal under E6" not in revise
          and "NEW OBSERVATION" in revise and "I-xxx" in revise)
    prompt = pp._defect_audit_prompt(1, 1)
    check("F79 an unverifiable defect audit row is UNVERIFIED, not TP",
          "label it TP" not in prompt and "UNVERIFIED" in prompt)
    norm = pp._normalize_defect_audit(
        {"verdicts": [{"defect_id": "d1", "label": "unverified", "reason": "missing"}]},
        {"d1"})
    check("F79 UNVERIFIED survives normalization", norm.get("d1", ("",))[0]
          == "UNVERIFIED", str(norm))


def main() -> int:
    test_number_proof()
    test_repair_bounds()
    test_view_references()
    test_ooxml()
    test_convert_corpus()
    test_citations()
    test_occurrences()
    test_numbers_and_words()
    test_qwen_and_pairwise()
    test_pdf_and_prompts()
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for name in FAILS:
            print(" -", name)
        return 1
    print("ALL 2026-11-04 FIX-BUGS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Regression checks for the 2026-10-28 fix-bugs wave 1.

Run:  python3 .paper_test/test_fix_bugs_20261028_wave1.py

Every finding was verified TRUE_POSITIVE by two independent passes over the
2026-10-27 find-bugs tree. Each check below fails on the pre-fix tree and pins
the smallest observed defect (F01..F46, the ids of the verification ledger).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1028_pp", "paper_pipeline.py")
pf = load("fixbugs1028_pf", "paper_docx_format.py")
cw = load("fixbugs1028_cw", "paper-skills/paper-review/scripts/count_words.py")
cv = load("fixbugs1028_cv", "paper-skills/paper-review/scripts/convert_corpus.py")
ec = load("fixbugs1028_ec", "paper-skills/paper-review/scripts/extract_citations.py")
en = load("fixbugs1028_en", "paper-skills/paper-review/scripts/extract_numbers.py")
eo = load("fixbugs1028_eo", "paper-skills/paper-review/scripts/extract_occurrences.py")
rt = load("fixbugs1028_rt", "paper-skills/paper-revise/scripts/revision_token.py")
zt = load("fixbugs1028_zt", ".paper_test/test_zotero_auto_refresh_2026_1011.py")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def run_py(*args, cwd=None):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True,
                          text=True, cwd=cwd)


# ---------------------------------------------------------------------------
# F01/F36/F43 -- documentation and CLI reference agree with the code
# ---------------------------------------------------------------------------
def test_f01_f36_f43() -> None:
    print()
    print("== F01/F36/F43: the documented surface matches the tree ==")
    suites = len(list((WS / ".paper_test").glob("test_*.py")))
    readme = (WS / "README.md").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"run them in parallel \u2014 (\d+) suites", readme)
    check("F01 README's suite count matches the tree",
          bool(m) and int(m.group(1)) == suites, f"README={m and m.group(1)} tree={suites}")

    helped = run_py(WS / "paper_pipeline.py", "--help").stdout
    check("F36 --help accepts the qwen agent the parser accepts",
          "[--agent codex|claude|dsh|qwen|manual]" in helped
          and "[--judge-agent codex|claude|dsh|qwen|manual]" in helped)
    check("F36 AGENT_CHOICES still carries qwen", "qwen" in pp.AGENT_CHOICES)

    spec = pp.parse_only_spec("1,3:merge")
    check("F43 1,3:merge parses as round 1 full + round 3 integrate",
          spec.rounds_in_full == {1} and spec.pairs == {3: {"integrate"}},
          f"{spec.rounds_in_full} {spec.pairs}")
    check("F43 the OnlySpec docstring no longer promises round 3 in full",
          "round 3 in full" not in (pp.OnlySpec.__doc__ or ""),
          (pp.OnlySpec.__doc__ or "")[:100])


# ---------------------------------------------------------------------------
# F02/F05/F31 -- the two M19 counters and the LaTeX input scan agree
# ---------------------------------------------------------------------------
def test_f02_f05_f31() -> None:
    print()
    print("== F02/F05/F31: M19 keyword/References parity and comment parity ==")
    lines = ["Abstract", "We studied X.", "2 Keywords: alpha beta gamma",
             "Introduction", "Body text here and more."]
    pip = [(r["section"], r["words"]) for r in pp._length_rows_for_lines(lines, "ms.md")]
    cwr = [(s, w) for s, w, _ in cw.sections("\n".join(lines))]
    check("F02 a numbered Keywords heading is a boundary in both counters",
          pip == cwr == [("abstract", 3), ("main text", 5)], f"PIP={pip} CW={cwr}")

    tex = r"""\documentclass{article}
\begin{document}
\begin{abstract}
We studied X.
\end{abstract}
\section{Introduction}
Body text here and more.
\begin{thebibliography}{9}
\bibitem{a} Alpha et al. A title. 2020.
\bibitem{b} Beta et al. Another title. 2021.
\end{thebibliography}
\end{document}
"""
    ls, caps, ae = pp._tex_length_scan(tex)
    pip = [(r["section"], r["words"]) for r in
           pp._length_rows_for_lines(ls, "ms.tex", caption_spans=caps, abstract_end=ae)]
    cwr = [(s, w) for s, w, _ in cw.sections("\n".join(cw.tex_lines(tex)[0]))]
    check("F05 an inline bibliography is excluded by both counters",
          pip == cwr and ("main text", 5) in pip, f"PIP={pip} CW={cwr}")

    src = r"x\\% \input{hidden.tex}"
    check("F31 a \\\\% comment ends the line (parity with strip_tex_comment)",
          pp._tex_strip_comments(src) == pp.strip_tex_comment(src) == "x\\\\")
    check("F31 a commented-out \\input is not a dependency",
          pp.tex_input_targets(src) == [], pp.tex_input_targets(src))


# ---------------------------------------------------------------------------
# F04/F11/F15 -- the integration DIFF_LEDGER contract is enforced
# ---------------------------------------------------------------------------
def _ledger(text: str, donors=("a1",)):
    out = scratch("paper_led_") / "integrated"
    out.mkdir()
    (out / "DIFF_LEDGER.md").write_text(text, encoding="utf-8")
    return pp.integration_ledger_report(out, list(donors), False)


def test_f04_f11_f15() -> None:
    print()
    print("== F04/F11/F15: DIFF_LEDGER port/empty/verdict checks ==")
    led = _ledger("| donor | size | verdict |\n|---|---|---|\n| a1 | small | port |\n")
    check("F04 a legacy table with a port row is a hard failure, not a warning",
          led["legacy_no_revalidated"] is True and led["legacy_ports"] is True, str(led))
    led = _ledger("| donor | size | verdict |\n|---|---|---|\n| a1 | small | keep-self |\n")
    check("F04 a legacy keep-self-only table stays a tolerated legacy ledger",
          led["legacy_ports"] is False, str(led))

    led = _ledger("| donor | size | verdict | revalidated |\n|---|---|---|---|\n")
    check("F11 a header-only ledger carries no row", led["rows"] == 0, str(led))
    check("F11 the prompt no longer promises an unimplemented row-count check",
          "non-empty (a header-only table fails)" in pp.DIFF_LEDGER_RULE)

    led = _ledger("| donor | size | verdict | revalidated |\n|---|---|---|---|\n"
                  "| a1 | small | keep-self | bogus |\n")
    check("F15 an uninterpretable revalidated value is reported",
          led["invalid_revalidated"] and led["missing_revalidated"] == [], str(led))
    led = _ledger("| donor | size | verdict | revalidated |\n|---|---|---|---|\n"
                  "| a1 | small | keep-self | rejected |\n")
    check("F15 the two Rule 1B verdicts are accepted",
          led["invalid_revalidated"] == [] and led["invalid_ports"] == [], str(led))


# ---------------------------------------------------------------------------
# F06/F44 -- one file-role rule for the review scripts and the pipeline
# ---------------------------------------------------------------------------
def test_f06_f44() -> None:
    print()
    print("== F06/F44: reply names, editor role, disabled evidence ==")
    for fname, mod in (("extract_numbers.py", en), ("extract_citations.py", ec),
                       ("extract_occurrences.py", eo)):
        check(f"F06 {fname} treats ReviewerResponse.md as a reply",
              mod.is_non_manuscript("ReviewerResponse.md") is True)
        check(f"F06 {fname} treats reviewerresponse.md as a reply",
              mod.is_non_manuscript("reviewerresponse.md") is True)
        check(f"F06 {fname} keeps a bare editor.md as manuscript",
              mod.is_non_manuscript("editor.md") is False)
        check(f"F06 {fname} still excludes editor_comments.md",
              mod.is_non_manuscript("editor_comments.md") is True)
        check(f"F06 {fname} still keeps immune_response.md as prose",
              mod.is_non_manuscript("immune_response.md") is False)
        check(f"F44 {fname} treats <area>.disabled/ as inert evidence",
              mod.is_non_manuscript("llm_review_feedback.disabled/notes.md") is True
              and mod.is_non_manuscript("raw_data.off/x.txt") is True)
    check("F44 the pipeline agrees on the disabled area",
          pp.is_non_manuscript_rel("llm_review_feedback.disabled/notes.md") is True)
    check("F06 convert_corpus keeps a bare editor.md out of the feedback role",
          cv.is_feedback_rel("editor.md") is False
          and cv.is_feedback_rel("editor_comments.md") is True)


# ---------------------------------------------------------------------------
# F17/F18/F19 -- the review corpus is the rendered DOCX text and the call-out
# ---------------------------------------------------------------------------
def test_f17_f18_f19() -> None:
    print()
    print("== F17/F18/F19: converter text parity and em-dash ranges ==")
    lines, _notes = cv.docx_part_to_lines(
        '<w:p><w:r><w:t>A</w:t><w:noBreakHyphen/><w:t>B</w:t>'
        '<w:sym w:font="W" w:char="F0E0"/><w:t>C</w:t></w:r></w:p>')
    check("F17 noBreakHyphen/sym render like the pipeline extractor",
          lines == ["A-B\ufffdC"], lines)
    xml = ('<w:p><w:r><w:t>Before</w:t></w:r></w:p>'
           '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps">'
           '<w:t>ChoiceText</w:t></mc:Choice><mc:Fallback><w:t>FallbackText</w:t>'
           '</mc:Fallback></mc:AlternateContent></w:r></w:p>'
           '<w:p><w:r><w:t>After</w:t></w:r></w:p>')
    check("F18 only the rendered AlternateContent branch is emitted",
          cv.docx_part_to_lines(xml)[0] == ["Before", "ChoiceText", "After"],
          cv.docx_part_to_lines(xml))
    check("F19 an em-dash range expands and cites its entries",
          ec.parse_nums("12\u201414") == [12, 13, 14], ec.parse_nums("12\u201414"))
    check("F19 en dash and hyphen still work",
          ec.parse_nums("12\u201314") == ec.parse_nums("12-14") == [12, 13, 14])


# ---------------------------------------------------------------------------
# F08/F20/F42/F46 -- file/directory symlinks are not package content
# ---------------------------------------------------------------------------
def test_f08_f20_f42_f46() -> None:
    print()
    print("== F08/F20/F42/F46: symlink containment ==")
    tmp = scratch("paper_links_")
    outside = tmp / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET", encoding="utf-8")
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "main.md").write_text("M", encoding="utf-8")
    os.symlink(outside, pkg / "raw_data")
    seen = [p.relative_to(pkg).as_posix()
            for p in pp._iter_tree_files(pkg, follow_dir_links=True)]
    check("F08 a planted raw_data link to an arbitrary directory is not followed",
          seen == ["main.md"], seen)

    # The walker is not handed the owning root, so it can only test the target
    # SHAPE (its docstring now says exactly that). The strict containment proof
    # is is_canonical_evidence_link, which copy_into/ensure_pristine_input use
    # because they DO receive the owning root: an outside tree with the same
    # shape must fail it.
    shaped = tmp / "outside_store" / "non_revised" / "raw_data"
    shaped.mkdir(parents=True)
    (shaped / "secret.txt").write_text("SECRET", encoding="utf-8")
    shaped_pkg = tmp / "pkg_shaped"
    shaped_pkg.mkdir()
    (shaped_pkg / "main.md").write_text("M", encoding="utf-8")
    os.symlink(shaped, shaped_pkg / "raw_data")
    check("F08 the owner-root proof refuses an outside tree with the canonical shape",
          pp.is_canonical_evidence_link(shaped_pkg / "raw_data",
                                        tmp / "not_the_owner") is False)
    shaped_dst = tmp / "shaped_copy"
    shaped_dst.mkdir()
    pp.copy_into(shaped_pkg, shaped_dst, root=tmp / "not_the_owner")
    check("F08 copy_into refuses an outside tree with the canonical shape",
          not (shaped_dst / "raw_data" / "secret.txt").exists()
          and (shaped_dst / "main.md").exists())

    # ...while the REAL layout (package under the run root that owns the
    # canonical store) is still followed: <runroot>/<sandbox>/raw_data ->
    # <runroot>/non_revised/raw_data.
    real_root = tmp / "real_runroot"
    (real_root / "non_revised" / "raw_data").mkdir(parents=True)
    (real_root / "non_revised" / "raw_data" / "real.txt").write_text("R", encoding="utf-8")
    real_pkg = real_root / "sandbox" / "revised"
    real_pkg.mkdir(parents=True)
    os.symlink(real_root / "non_revised" / "raw_data", real_pkg / "raw_data")
    seen = [p.relative_to(real_pkg).as_posix()
            for p in pp._iter_tree_files(real_pkg, follow_dir_links=True)]
    check("F08 the owning root's canonical <root>/non_revised/<area> link is followed",
          seen == ["raw_data/real.txt"], seen)

    runroot = tmp / "runroot"
    (runroot / "non_revised" / "raw_data").mkdir(parents=True)
    (runroot / "non_revised" / "raw_data" / "d.txt").write_text("D", encoding="utf-8")
    sb = tmp / "sb"
    (sb / "non_revised").mkdir(parents=True)
    os.symlink(runroot / "non_revised" / "raw_data", sb / "non_revised" / "raw_data")
    seen = [p.relative_to(sb / "non_revised").as_posix()
            for p in pp._iter_tree_files(sb / "non_revised", follow_dir_links=True)]
    check("F08 a link to the canonical-shaped <root>/non_revised/<area> store is followed",
          seen == ["raw_data/d.txt"], seen)

    docs = tmp / "docs"
    docs.mkdir()
    (tmp / "real.docx").write_text("x", encoding="utf-8")
    os.symlink(tmp / "real.docx", docs / "link.docx")
    (docs / "own.docx").write_text("y", encoding="utf-8")
    check("F20 a symlinked .docx is not read by the formatter",
          [p.name for p in pf.docx_files_under(docs)] == ["own.docx"],
          [p.name for p in pf.docx_files_under(docs)])

    dset = tmp / "pkg2"
    dset.mkdir()
    (dset / "README.md").write_text(
        "The following will be submitted: `*.docx`\n", encoding="utf-8")
    (tmp / "evil.docx").write_text("S", encoding="utf-8")
    os.symlink(tmp / "evil.docx", dset / "evil.docx")
    (dset / "own.docx").write_text("O", encoding="utf-8")
    res = pp.declared_submission_set(dset)
    check("F42 a declared-set file symlink is not submitted content",
          res["files"] == ["own.docx"], res["files"])

    # F46: the figure walk must not hand a symlinked image to OCR/label rows.
    figpkg = tmp / "figpkg"
    (figpkg / "figures").mkdir(parents=True)
    (figpkg / "main.md").write_text("text", encoding="utf-8")
    outside_png = tmp / "outside.png"
    outside_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    os.symlink(outside_png, figpkg / "figures" / "link.png")
    (figpkg / "figures" / "own.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    grabbed = []
    real_figure_rows = pf.figure_label_rows
    pf.figure_label_rows = lambda images, vocab: (grabbed.append(list(images)) or [])
    try:
        pol = dict(pf.POLICY_DEFAULTS)
        pol["figure_ocr"] = True
        pf.scan_paths([figpkg], pol)
    finally:
        pf.figure_label_rows = real_figure_rows
    names = sorted(p.name for group in grabbed for p in group)
    check("F46 a symlinked image is not scanned/sent to OCR",
          names == ["own.png"], names)


# ---------------------------------------------------------------------------
# F09/F13/F16 -- decision report and ranking inputs
# ---------------------------------------------------------------------------
def test_f09_f13_f16() -> None:
    print()
    print("== F09/F13/F16: reported rule, ranking key, open-item shapes ==")
    ctx = types.SimpleNamespace(cfg={"vs_original_rule": "sign"})
    doc = pp.score_model_doc(ctx)
    check("F09 the score model reports the configured sign rule",
          doc["anti_regression_rule"].startswith("sign")
          and pp.vs_original_rule_of(ctx) == "sign", doc["anti_regression_rule"][:40])
    row = {"defect_prefix_census": (0,), "median": 1.0, "mean": 1.0, "iqr": 0.0,
           "digest": "abc"}
    check("F13 the ranking key ends at the digest (no id label)",
          pp.champion_sort_key(dict(row, id="w1"))
          == pp.champion_sort_key(dict(row, id="a2")),
          pp.champion_sort_key(dict(row, id="w1")))
    check("F13 the reported tiebreak list no longer names an id rung",
          "id" not in doc["tiebreaks"], doc["tiebreaks"])
    rows = pp._open_item_rows({"status": "complete",
                               "F-001": {"final_status": "manual-required"}})
    check("F16 an id-keyed mapping with a metadata key keeps its rows",
          rows == [{"final_status": "manual-required", "id": "F-001"}], rows)


# ---------------------------------------------------------------------------
# F10/F12/F25 -- token parity, honest PDF summary, safe temp files
# ---------------------------------------------------------------------------
def test_f10_f12_f25() -> None:
    print()
    print("== F10/F12/F25: token parity, PDF summary, atomic temp ==")
    tmp = scratch("paper_tok_")
    (tmp / "main text.md").write_text("hello", encoding="utf-8")
    (tmp / "MANUAL_TODO.csv").write_text("a,b\n", encoding="utf-8")
    (tmp / "MANUAL_TODO-v2.csv").write_text("a,b\n", encoding="utf-8")
    script = rt.revision_token(tmp)
    pipe = pp.revision_token_for_dir(tmp)
    check("F10 MANUAL_TODO.csv is bookkeeping in both implementations",
          script["token"] == pipe["token"]
          and script["files"] == pipe["files"] == 1,
          f"{script} vs {pipe}")

    r = run_py(WS / "paper_docx_format.py", "check-pdf", tmp / "missing.pdf")
    check("F12 an unreadable PDF reports NOT CHECKED, not '0 pages; blank: none'",
          "NOT CHECKED" in r.stdout and "0 page(s)" not in r.stdout and r.returncode == 1,
          r.stdout.strip())

    outside = tmp / "outside.txt"
    outside.write_text("ORIG", encoding="utf-8")
    for i in range(1, 40):
        try:
            os.symlink(outside, tmp / f"PROMPT.md.{os.getpid()}.{i}.tmp")
        except FileExistsError:
            pass
    pp.write_text_atomic(tmp / "PROMPT.md", "SECRET")
    check("F25 a pre-created predictable temp symlink does not receive the write",
          outside.read_text(encoding="utf-8") == "ORIG"
          and (tmp / "PROMPT.md").read_text(encoding="utf-8") == "SECRET",
          outside.read_text(encoding="utf-8"))

    # The zotero-refresh writer had its own predictable temp path.
    ztmp = scratch("paper_zotrefresh_")
    zsrc = zt._docx(ztmp / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
                    marker_b=r"\super 1\nosupersub{}", visible_b="1")
    zdst = ztmp / "out.docx"
    zoutside = ztmp / "outside.bin"
    zoutside.write_bytes(b"ORIG")
    os.symlink(zoutside, zdst.with_name(f".{zdst.name}.zotrefresh{os.getpid()}.tmp"))
    zrep = pf.refresh_zotero_package(zsrc, zdst, dict(zt.fmt.POLICY_DEFAULTS))
    check("F25 a pre-created zotero-refresh temp symlink does not receive the archive",
          zrep.get("ok") and zrep.get("changed")
          and zoutside.read_bytes() == b"ORIG"
          and not zdst.is_symlink() and zipfile.is_zipfile(zdst),
          f"changed={zrep.get('changed')} outside={zoutside.read_bytes()[:4]!r} "
          f"dst_link={zdst.is_symlink()}")


# ---------------------------------------------------------------------------
# F23/F24/F26/F27/F28 -- DOCX parsing: budget, one branch, one text
# ---------------------------------------------------------------------------
def test_f23_f24_f26_f27_f28() -> None:
    print()
    print("== F23/F24/F26/F27/F28: DOCX budget and one visible text ==")
    tmp = scratch("paper_docx_")
    doc = tmp / "d.docx"
    wx = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
          'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>A</w:t>'
          '<w:noBreakHyphen/><w:t>B</w:t><w:sym w:font="W" w:char="F0E0"/>'
          '<w:t>C</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(doc, "w") as z:
        z.writestr("word/document.xml", wx)
    check("F27 _docx_paragraphs renders noBreakHyphen/sym like _docx_paragraph_texts",
          pp._docx_paragraphs(doc) == pp._docx_paragraph_texts(doc) == ["A-B\ufffdC"],
          f"{pp._docx_paragraphs(doc)} vs {pp._docx_paragraph_texts(doc)}")

    para = ('<w:p><w:r><w:t>A</w:t></w:r>'
            '<w:r><mc:AlternateContent><mc:Choice Requires="wps">'
            '<w:r><w:t>CHOICE</w:t></w:r></mc:Choice><mc:Fallback>'
            '<w:r><w:t>FALL</w:t></w:r></mc:Fallback></mc:AlternateContent></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>RESULT</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    text = pf.text_of(para)
    check("F26 a field result after an AlternateContent maps to its text range",
          text == "ACHOICERESULT" and text.index("RESULT") == 7
          and pf.field_result_text_ranges(para) == [(7, 13)],
          f"{text!r} {pf.field_result_text_ranges(para)}")

    body = ('<w:body><w:p><w:r><w:t>Before</w:t></w:r></w:p>'
            '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps">'
            '<w:p><w:r><w:t>ChoiceText</w:t></w:r></w:p></mc:Choice>'
            '<mc:Fallback><w:p><w:r><w:t>FallbackText</w:t></w:r></w:p></mc:Fallback>'
            '</mc:AlternateContent></w:r></w:p>'
            '<w:p><w:r><w:t>After</w:t></w:r></w:p></w:body>')
    check("F28 paragraphs() yields only the rendered AlternateContent branch",
          [pf.text_of(p[2]) for p in pf.paragraphs(body)]
          == ["Before", "ChoiceText", "After"],
          [pf.text_of(p[2]) for p in pf.paragraphs(body)])

    evil = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e0 "' + "A" * 256 + '">'
            + "".join(f'<!ENTITY e{i} "&e{i-1};&e{i-1};">' for i in range(1, 9))
            + ']><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
              '2006/main"><w:body><w:p><w:r><w:t>&e8;</w:t></w:r></w:p></w:body>'
              '</w:document>')
    edoc = tmp / "evil.docx"
    with zipfile.ZipFile(edoc, "w") as z:
        z.writestr("word/document.xml", evil)
    check("F23 a DOCX carrying a DTD/entity declaration is refused",
          pp._docx_paragraphs(edoc) is None
          and "DTD/entity" in pf.analyse_package(edoc, pf.load_policy(None))["rows"][0]["evidence"],
          pp._docx_paragraphs(edoc))
    prob = pf._docx_zip_problem(types.SimpleNamespace(infolist=lambda: [
        types.SimpleNamespace(filename="x", file_size=pf.MAX_DOCX_PART_BYTES + 1)]))
    check("F24 an over-budget part is refused before it is read", bool(prob), prob)

    # The sibling reader used by the template-conformance postcheck must apply
    # the SAME per-part cap, not decompress the part anyway.
    over = tmp / "over.docx"
    big = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
           + "A" * (pp.MAX_DOCX_PART_BYTES + 1024)
           + '</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(over, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", big)
    check("F24 both p04 DOCX readers refuse the over-budget part",
          pp._docx_paragraphs(over) is None and pp._docx_paragraph_texts(over) == [],
          f"paragraphs={pp._docx_paragraphs(over)} "
          f"texts={len(pp._docx_paragraph_texts(over))}")


# ---------------------------------------------------------------------------
# F29/F33/F37/F38 -- bounded repair, disabled evidence, review gates
# ---------------------------------------------------------------------------
def _review_errors(tmp: Path, *, prior_ids=(), findings=(), all_out=(),
                   scope="full", extra_out=()):
    sb = tmp / "sb"
    (sb / "prior_round").mkdir(parents=True)
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    (sb / "prior_round" / "findings.json").write_text(
        json.dumps({"findings": [{"id": i} for i in prior_ids]}), encoding="utf-8")
    wanted = list(pp.REQUIRED_REVIEW_CHECKS) + [
        "M19", "M18", "M20", "M21", "M22", "M23", "M24", "M25", "M26", "M27", "M28",
        "M29", "J5", "M30", "M31", "M32", "M33", "M34", "M35", "M36"]
    cov = [{"check": c,
            "disposition": ("out of scope -- formatting-only pass"
                            if c in all_out or c in extra_out
                            else "clean -- basis: a.md")}
           for c in wanted]
    cur = {"submission_dir": "./base", "findings": list(findings), "coverage": cov}
    (sb / "guided_review" / "findings.json").write_text(json.dumps(cur), encoding="utf-8")
    for name in ("M1.md", "M27_evidence_coverage.md", "M34_source_data_coverage.md"):
        (sb / "guided_review" / "artifacts" / name).write_text(
            "| check | disposition |\n|---|---|\n| x | clean |\n", encoding="utf-8")
    (sb / "guided_review" / "findings.md").write_text("# findings\n", encoding="utf-8")
    ctx = types.SimpleNamespace(cfg={})
    errs, warns = [], []
    pp.check_review_contract(ctx, sb, cur, errs, warns, scope=scope)
    return errs


def test_f29_f33_f37_f38() -> None:
    print()
    print("== F29/F33/F37/F38: repair scope, disabled evidence, review gates ==")
    tmp = scratch("paper_rep_")
    pre, cur = tmp / "pre", tmp / "cur"
    for d, val in ((pre, "one"), (cur, "two")):
        (d / "figures").mkdir(parents=True)
        (d / "figures" / "a.txt").write_text(val, encoding="utf-8")
    rows = [{"id": "RP-001", "file": "figures"}]
    check("F29 a directory row cannot authorize edits under it",
          pp._revised_repair_violations(pre, cur, rows, {"RP-001"}) == ["figures/a.txt"],
          pp._revised_repair_violations(pre, cur, rows, {"RP-001"}))
    sb = tmp / "sb"
    (sb / "revised" / "figures").mkdir(parents=True)
    (sb / "revision_audit").mkdir()
    (sb / "revision_audit" / "REPAIR_PLAN.json").write_text(
        json.dumps({"rows": rows}), encoding="utf-8")
    check("F29 a plan row naming an existing directory invalidates the plan",
          pp._revision_plan_rows(sb) is None)

    # A DANGLING symlink at the row's path is not "absent": a repair writing
    # through it would write outside revised/ while the manifest audit (which
    # skips symlinks) sees nothing change.
    dangling = tmp / "sb_dangling"
    (dangling / "revised").mkdir(parents=True)
    (dangling / "revision_audit").mkdir()
    os.symlink(tmp / "not-there-yet.json", dangling / "revised" / "figures")
    (dangling / "revision_audit" / "REPAIR_PLAN.json").write_text(
        json.dumps({"rows": [{"id": "RP-002", "file": "figures"}]}), encoding="utf-8")
    check("F29 a plan row naming a DANGLING symlink invalidates the plan",
          pp._revision_plan_rows(dangling) is None,
          pp._revision_plan_rows(dangling))

    # ...and the application audit reports a confirmed row that resolved to a
    # symlink, rather than silently accepting the write-through.
    pre_link, cur_link = tmp / "pre_link", tmp / "cur_link"
    pre_link.mkdir()
    cur_link.mkdir()
    os.symlink(tmp / "outside-link-target", cur_link / "figures")
    link_rows = [{"id": "RP-003", "file": "figures"}]
    check("F29 the repair audit reports a confirmed row that resolved to a symlink",
          pp._revised_repair_violations(pre_link, cur_link, link_rows, {"RP-003"})
          == ["figures"],
          pp._revised_repair_violations(pre_link, cur_link, link_rows, {"RP-003"}))

    # A row naming a file that does not exist yet is still a valid plan: the
    # plan is written before the repair creates the file.
    future = tmp / "sb_future"
    (future / "revised").mkdir(parents=True)
    (future / "revision_audit").mkdir()
    (future / "revision_audit" / "REPAIR_PLAN.json").write_text(
        json.dumps({"rows": [{"id": "RP-004", "file": "new/passage.md",
                              "location": "new section", "wrong": "",
                              "correct": "text", "basis": "review finding F-001",
                              "edit": "add the passage",
                              "evidence": "guided_review/findings.json F-001"}]}),
        encoding="utf-8")
    check("F29 a plan row naming a file that does not exist yet is accepted",
          pp._revision_plan_rows(future) is not None,
          pp._revision_plan_rows(future))

    check("F33 <area>.disabled is inert for the formatter too",
          pf.is_evidence_part("llm_review_feedback.disabled") is True
          and pf.is_evidence_part("raw_data.off") is True
          and pf.is_evidence_part("raw_data") is True
          and pf.is_evidence_part("main text") is False)

    errs = _review_errors(scratch("paper_f37_"), all_out={"M1", "M2", "M3"})
    check("F37 a FULL review cannot dispose an in-scope check as out of scope",
          any("out of scope" in e for e in errs), errs[:2])
    errs = _review_errors(scratch("paper_f37b_"), all_out={"M1", "M3"},
                          scope="formatting-writing")
    check("F37 a scoped round cannot dispose an IN-SCOPE check as out of scope "
          "(the 2026-10-28 F14 correction)",
          any("in-scope check(s)" in e for e in errs), errs[:2])
    # A genuinely out-of-scope check may be disposed as out of scope; every such
    # id must say so, and none of them is reported as an in-scope violation.
    _scoped = set(pp.scoped_review_checks("formatting-writing"))
    _wanted = set(pp.REQUIRED_REVIEW_CHECKS) | {
        "M19", "M18", "M20", "M21", "M22", "M23", "M24", "M25", "M26", "M27",
        "M28", "M29", "J5", "M30", "M31", "M32", "M33", "M34", "M35", "M36"}
    errs = _review_errors(scratch("paper_f37c_"), extra_out=tuple(_wanted - _scoped),
                          scope="formatting-writing")
    check("F37 a scoped round may dispose the out-of-scope ids as out of scope",
          not any("in-scope check(s)" in e for e in errs), errs[:2])

    errs = _review_errors(scratch("paper_f38_"), prior_ids=["F-999"],
                          findings=[{"id": "F-001", "explanation": "see F-999"}])
    check("F38 an unrelated mention of a prior id does not reconcile it",
          any("F-999" in e for e in errs), errs[:2])
    errs = _review_errors(scratch("paper_f38b_"), prior_ids=["F-999"],
                          findings=[{"id": "F-001",
                                     "explanation": "carried over from F-999"}])
    check("F38 the exact carried-over marker reconciles the prior id",
          not any("F-999" in e for e in errs), errs[:2])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    test_f01_f36_f43()
    test_f02_f05_f31()
    test_f04_f11_f15()
    test_f06_f44()
    test_f17_f18_f19()
    test_f08_f20_f42_f46()
    test_f09_f13_f16()
    test_f10_f12_f25()
    test_f23_f24_f26_f27_f28()
    test_f29_f33_f37_f38()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL 2026-10-28 FIX-BUGS WAVE-1 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

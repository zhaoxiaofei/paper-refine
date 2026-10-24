#!/usr/bin/env python3
"""Regressions for the 18 candidates of the 2026-10-25 fix-bugs round.

Run:  python3 .paper_test/test_fix_bugs_2026_1025_verified.py

Every check is a repro that failed on the pre-fix tree (or a direct assertion
of the corrected invariant).  Hermetic: temp dirs only, no network, no Word.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


fmt = load("fixbugs2_fmt", WS / "paper_docx_format.py")
pp = load("fixbugs2_pp", WS / "paper_pipeline.py")
cw = load("fixbugs2_cw", WS / "paper-skills/paper-review/scripts/count_words.py")


# ---------------------------------------------------------------------------
# pipeline: F003 lenient-JSON recovery is linear
# ---------------------------------------------------------------------------
def test_f003():
    print("\n== F003: lenient JSON recovery ==")
    payload = "[" + ",".join(['{"x": 1}'] * 4400)   # truncated, many braces
    t0 = time.time()
    got = pp._json_from_text(payload, True)
    dt = time.time() - t0
    check("a truncated 40 KiB payload is refused without quadratic decode work",
          got is None and dt < 2.0, f"{dt:.3f}s")
    cases = [
        ('```json\n{"a": 1, "s": "}"}\n```', {"a": 1, "s": "}"}),
        ('Here: {"a": 1} and the data is {"b": 2}', {"b": 2}),
        ("prefix [1,2,3] suffix", [1, 2, 3]),
        ('[{"a": {"b": 2}}]', [{"a": {"b": 2}}]),
    ]
    for text, want in cases:
        check(f"wrapped JSON still recovers: {text[:28]!r}",
              pp._json_from_text(text, True) == want)


# ---------------------------------------------------------------------------
# pipeline: F005 graphicspath rewrite
# ---------------------------------------------------------------------------
def test_f005():
    print("\n== F005: \\graphicspath directories are rewritten ==")
    file_map = {"main.tex": "d01.tex",
                "figures/fig1.png": "d03/f0001.png",
                "figures/sub/fig2.png": "d03/s01/f0002.png"}
    src = r"\graphicspath{{figures/}}\includegraphics{fig1}"
    out = pp._rewrite_view_references(src, "main.tex", "d01.tex", file_map)
    check("a {dir} pair is mapped, not left dead", "\\graphicspath{{d03/}}" in out, out)
    check("the extension-less includegraphics stem is mapped", "\\includegraphics{f0001}" in out, out)
    nested = (r"\graphicspath{{figures/}{figures/sub/}}")
    out2 = pp._rewrite_view_references(nested, "main.tex", "d01.tex", file_map)
    check("several {dir} pairs in one argument are all mapped",
          "{{d03/}{d03/s01/}}" in out2, out2)


# ---------------------------------------------------------------------------
# pipeline: F017 canonical evidence link must belong to THIS root
# ---------------------------------------------------------------------------
def test_f017():
    print("\n== F017: canonical evidence link containment ==")
    d = scratch("fixbugs_f017_")
    root = d / "root"
    (root / "non_revised" / "raw_data").mkdir(parents=True)
    (root / "non_revised" / "raw_data" / "ok.txt").write_text("ok", encoding="utf-8")
    evil = d / "evil" / "non_revised" / "raw_data"
    evil.mkdir(parents=True)
    (evil / "secret.txt").write_text("secret", encoding="utf-8")
    src = d / "src"
    src.mkdir()
    (src / "paper.docx").write_text("x", encoding="utf-8")
    (src / "raw_data").symlink_to(evil, target_is_directory=True)
    dst = d / "dst"
    dst.mkdir()
    check("a link to another root/non_revised/<area> is refused",
          not pp.is_canonical_evidence_link(src / "raw_data", root))
    with contextlib.redirect_stderr(io.StringIO()):
        pp.copy_into(src, dst, root=root)
    check("the outside secret is not copied", not (dst / "raw_data" / "secret.txt").exists(),
          str(sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*"))))

    good = d / "good"
    good.mkdir()
    (good / "paper.docx").write_text("x", encoding="utf-8")
    (good / "raw_data").symlink_to(root / "non_revised" / "raw_data",
                                   target_is_directory=True)
    dst2 = d / "dst2"
    dst2.mkdir()
    check("this root's canonical link is accepted",
          pp.is_canonical_evidence_link(good / "raw_data", root))
    with contextlib.redirect_stderr(io.StringIO()):
        pp.copy_into(good, dst2, root=root)
    check("the canonical evidence is materialized", (dst2 / "raw_data" / "ok.txt").is_file())


# ---------------------------------------------------------------------------
# pipeline: F018 file symlinks are not in the hash manifest
# ---------------------------------------------------------------------------
def test_f018():
    print("\n== F018: file symlinks are not manifest content ==")
    d = scratch("fixbugs_f018_")
    src = d / "src"
    src.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    (src / "linked.txt").symlink_to(d / "outside.txt")
    (d / "outside.txt").write_text("outside", encoding="utf-8")
    manifest = pp.hash_manifest(src)
    check("the manifest hashes only the real file", manifest["count"] == 1,
          str(manifest))
    check("the link name is absent from the manifest", "linked.txt" not in manifest["files"])
    dst = d / "dst"
    dst.mkdir()
    with contextlib.redirect_stderr(io.StringIO()):
        first = pp.ensure_copy(src, dst, root=None)
        second = pp.ensure_copy(src, dst, root=None)
    check("the first materialization happens", first is True)
    check("the copy matches afterwards (no permanent mismatch)", second is False)


# ---------------------------------------------------------------------------
# pipeline: F024 scope guard keys by exact path
# ---------------------------------------------------------------------------
def test_f024():
    print("\n== F024: scope guard does not fold distinct documents ==")
    d = scratch("fixbugs_f024_")
    sb = d / "sb"
    (sb / "base").mkdir(parents=True)
    (sb / "revised").mkdir()
    (sb / "base" / "appendix-a.docx").write_text("A", encoding="utf-8")
    (sb / "base" / "appendix-b.docx").write_text("B", encoding="utf-8")
    (sb / "revised" / "appendix-a.docx").write_text("A2", encoding="utf-8")
    (sb / "revised" / "revision_report.json").write_text("[]", encoding="utf-8")
    errs = pp.scoped_scope_problems(None, sb, sb / "revised")
    check("dropping appendix-b is reported", any("appendix-b.docx" in e for e in errs),
          str(errs))
    check("both exact paths are keyed separately",
          set(pp._scope_tree_files(sb / "base")) == {"appendix-a.docx", "appendix-b.docx"})

    # A version-token rename is still one document, when it is unambiguous.
    d2 = scratch("fixbugs_f024r_")
    sb2 = d2 / "sb"
    (sb2 / "base").mkdir(parents=True)
    (sb2 / "revised").mkdir()
    (sb2 / "base" / "manuscript.txt").write_text("original\n", encoding="utf-8")
    (sb2 / "revised" / "manuscript-9b2c7e4.txt").write_text("original\n", encoding="utf-8")
    (sb2 / "revised" / "revision_report.json").write_text(
        json.dumps([{"id": "C1", "files": ["manuscript-9b2c7e4.txt"]}]), encoding="utf-8")
    check("a version-token rename is not add+delete",
          pp.scoped_scope_problems(None, sb2, sb2 / "revised") == [])


# ---------------------------------------------------------------------------
# pipeline: F062 trend vs_input margin (verification false positive)
#
# The verify-findings set read "the version THAT run started from" as the
# round's base. For a chained run the version the RUN starts from is its
# pristine original (`vs_original`), which is exactly what the field carries;
# `vs_base` is the round's incumbent. The candidate patch collapsed the two
# columns into the same number, so this check pins the documented distinction.
# ---------------------------------------------------------------------------
def test_f062():
    print("\n== F062: trend vs_input is the run-input margin ==")
    d = scratch("fixbugs_f062_")
    (d / "reports").mkdir()
    decision = {
        "config": {"source": None},
        "rounds": [{
            "round": 1,
            "selection": {"champion": "a1", "champion_rep": "a1"},
            "stats": {"a1": {"median": 0.0, "mean": 0.0, "n": 4,
                             "vs_original": -2.0, "vs_base": 1.0}},
        }],
        "final": {},
    }
    (d / "reports" / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    rows, _run_rows = pp.trend_rows([d])
    row = rows[0]
    check("vs_input carries the run-input (pristine-original) margin",
          row["vs_input"] == -2.0, str(row))
    check("vs_incumbent carries the round-base margin", row["vs_incumbent"] == 1.0, str(row))
    check("the two documented margins are not collapsed", row["vs_input"] != row["vs_incumbent"],
          str(row))


# ---------------------------------------------------------------------------
# pipeline: F069 Supplementary Materials / Note boundaries
# ---------------------------------------------------------------------------
def test_f069():
    print("\n== F069: supplementary materials/note headings ==")
    for heading in ("Supplementary Materials", "Supplementary Material",
                    "Supplementary Note", "Supplementary Notes"):
        check(f"pipeline recognises {heading!r}",
              bool(pp.LENGTH_SECTION_BOUND_RE.match(heading))
              and pp._length_section_kind(heading) == "supplementary")
        check(f"count_words.py recognises {heading!r}",
              bool(cw.SECTION_BOUND.match(heading))
              and cw.section_kind(heading) == "supplementary")


# ---------------------------------------------------------------------------
# pipeline: F096 manual malformed-output attempt is bumped
# ---------------------------------------------------------------------------
def test_f096():
    print("\n== F096: manual malformed-output attempt is counted ==")
    d = scratch("fixbugs_f096_")
    (d / "sb").mkdir()

    class FakeCtx:
        root = d

        def sandbox_of(self, rec):
            return d / "sb"

        def log(self, *a, **k):
            pass

        def save_state(self):
            pass

    rec = {"id": "r1", "round": 1, "kind": "judge", "attempts": 1, "attempts_done": 1,
           "attempts_log": [{"attempt": 1, "ok": True, "errors": [], "warnings": []}],
           "last_attempt_started": "now", "status": "running"}
    originals = {
        "completion_signal_exists": pp.completion_signal_exists,
        "structured_output_problems": pp.structured_output_problems,
        "structured_output_signature": pp.structured_output_signature,
        "leftovers_present": pp.leftovers_present,
        "sleep": pp.time.sleep,
    }
    pp.completion_signal_exists = lambda ctx, rec: False
    pp.structured_output_problems = lambda ctx, rec: ["bad output"]
    pp.structured_output_signature = lambda ctx, rec: ("sig",)
    pp.leftovers_present = lambda ctx, rec: False
    pp.time.sleep = lambda n: None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            pp.manual_run_one(FakeCtx(), rec, poll=2, timeout=0)
    finally:
        pp.completion_signal_exists = originals["completion_signal_exists"]
        pp.structured_output_problems = originals["structured_output_problems"]
        pp.structured_output_signature = originals["structured_output_signature"]
        pp.leftovers_present = originals["leftovers_present"]
        pp.time.sleep = originals["sleep"]
    check("the retry budget counts the failure", rec["attempts"] == 2,
          f"attempts={rec['attempts']}")
    check("the previous attempt history survives",
          [e.get("attempt") for e in rec["attempts_log"]] == [1, 2],
          str([e.get("attempt") for e in rec["attempts_log"]]))


# ---------------------------------------------------------------------------
# docx: F020 spelled-out numbers
# ---------------------------------------------------------------------------
def test_f020():
    print("\n== F020: long/large spelled-out numbers parse whole ==")
    cases = {
        "one hundred and twenty five samples": ("one hundred and twenty five", 125),
        "two million cells": ("two million", 2_000_000),
        "one thousand two hundred donors": ("one thousand two hundred", 1200),
    }
    for text, (written, value) in cases.items():
        matches = list(fmt.NUMBER_WORD_RE.finditer(text))
        check(f"{text!r} is one match", len(matches) == 1 and matches[0].group(1) == written,
              str([m.group(1) for m in matches]))
        check(f"{text!r} parses to {value}", fmt._word_number_value(written) == value)
    rows = fmt.word_number_rows("one hundred and twenty five samples were collected")
    check("the count ledger records 125, not 120 + 5",
          [r["number"] for r in rows] == ["125"], str(rows))


# ---------------------------------------------------------------------------
# docx: F029 CT_RPr insertion order
# ---------------------------------------------------------------------------
def test_f029():
    print("\n== F029: w:i insertion respects schema order ==")
    out, changed = fmt._rpr_set_emphasis(
        '<w:rPr><w:sz w:val="20"/><w:color w:val="FF0000"/></w:rPr>', True)
    check("the override is inserted", changed and "<w:i/>" in out)
    check("w:i precedes w:sz", out.index("<w:i/>") < out.index("<w:sz"), out)
    out2, _ = fmt._rpr_set_emphasis(
        '<w:rPr><w:color w:val="FF0000"/><w:sz w:val="20"/></w:rPr>', True)
    check("a reversed property order is also handled",
          out2.index("<w:i/>") < out2.index("<w:color"), out2)


# ---------------------------------------------------------------------------
# docx: F036 indented correspondence label
# ---------------------------------------------------------------------------
def test_f036():
    print("\n== F036: indented correspondence label bolds the label only ==")
    para = ('<w:p><w:r><w:t xml:space="preserve">  * Correspondence: Zhen Xie'
            '</w:t></w:r></w:p>')
    out = fmt._bold_label_runs(para)
    runs = re.findall(r"<w:r\b[\s\S]*?</w:r>", out)
    bold = [r for r in runs if "<w:b/>" in r or re.search(r'<w:b w:val="(?:1|true|on)"', r)]
    check("a bold run exists", len(bold) == 1, out)
    if bold:
        check("the bold run is the label, not its first 13 characters",
              fmt.text_of(bold[0]).strip() == "* Correspondence:",
              repr(fmt.text_of(bold[0])))
    check("the paired bold check agrees", fmt._label_is_bold(out) is True)

    # The leading whitespace may live in its OWN run; a whitespace-only run is
    # skipped by the run walk, so its characters must not extend the window.
    split = ('<w:p><w:r><w:t xml:space="preserve">  </w:t></w:r>'
             '<w:r><w:t>* Correspondence: Zhen Xie</w:t></w:r></w:p>')
    out2 = fmt._bold_label_runs(split)
    runs2 = re.findall(r"<w:r\b[\s\S]*?</w:r>", out2)
    bold2 = [r for r in runs2 if "<w:b/>" in r or re.search(r'<w:b w:val="(?:1|true|on)"', r)]
    check("a whitespace-only leading run does not shift the bold window",
          len(bold2) == 1 and fmt.text_of(bold2[0]).strip() == "* Correspondence:",
          repr([fmt.text_of(r) for r in runs2]))
    check("the paired bold check agrees on the split-run form",
          fmt._label_is_bold(out2) is True)


# ---------------------------------------------------------------------------
# docx: F064 reference cleanup in a paragraph with a break
# ---------------------------------------------------------------------------
def test_f064():
    print("\n== F064: dangling-reference cleanup sees the same text as the writer ==")
    d = scratch("fixbugs_f064_")
    src = d / "a.docx"
    body = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Intro sentence.</w:t></w:r>'
            '<w:r><w:br/><w:t>See Fig. 9 for details. Final sentence.</w:t></w:r>'
            '</w:p></w:body></w:document>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("word/document.xml", body)

    def finder(text):
        return [m.span() for m in re.finditer(r"Fig\.\s*9", text)]

    res = fmt.strip_reference_sentences(src, d / "b.docx", finder)
    check("the cleanup succeeds", res["ok"] is True, str(res))
    check("the dangling sentence is removed", len(res["removed"]) == 1, str(res["removed"]))
    if (d / "b.docx").exists():
        with zipfile.ZipFile(d / "b.docx") as z:
            text = fmt.text_of(z.read("word/document.xml").decode("utf-8"))
        check("only the sentence leaves, the break survives",
              text == "Intro sentence.\nFinal sentence.", repr(text))


# ---------------------------------------------------------------------------
# docx: F065 healthy role-prefixed addresses are not split
# ---------------------------------------------------------------------------
def test_f065():
    print("\n== F065: valid role-prefixed addresses are not re-spaced ==")
    for address in ("emailupdates@list.edu", "contactsxyz@host.edu"):
        m = fmt.EMAIL_RE.search(address)
        check(f"{address!r} is not cut",
              fmt._email_glue_cut(address, m) == (None, None),
              str(fmt._email_glue_cut(address, m)))
        check(f"{address!r} produces no FMT-X2 row",
              fmt.correspondence_glue_rows([address], [False]) == [])
    glued = "Correspondence: lead contactzhenxie@tsinghua.edu.cn"
    m = fmt.EMAIL_RE.search(glued)
    check("the true glue shape is still cut",
          fmt._email_glue_cut(glued, m) == (28, "before"),
          str(fmt._email_glue_cut(glued, m)))


# ---------------------------------------------------------------------------
# docx: F080 ppr_of/rpr_of balanced through tracked changes
# ---------------------------------------------------------------------------
def test_f080():
    print("\n== F080: pPr/rPr readers are balanced ==")
    ppr = ('<w:pPr><w:pPrChange w:id="1"><w:pPr><w:jc w:val="left"/></w:pPr>'
           '</w:pPrChange><w:spacing w:after="0"/></w:pPr>')
    got = fmt.ppr_of(ppr)
    check("ppr_of keeps the whole element", got == ppr, str(got))
    rpr = ('<w:rPr><w:rPrChange w:id="2"><w:rPr><w:i/></w:rPr></w:rPrChange>'
           '<w:b/></w:rPr>')
    check("rpr_of keeps the whole element", fmt.rpr_of(rpr) == rpr, str(fmt.rpr_of(rpr)))
    check("the self-closing form is still read", fmt.ppr_of("<w:p><w:pPr/></w:p>") == "<w:pPr/>")


# ---------------------------------------------------------------------------
# count_words: F058 bare profile id, F111 thebibliography, F112 inline abstract
# ---------------------------------------------------------------------------
def test_count_words():
    print("\n== count_words: venue id, bibliography, inline abstract ==")
    d = scratch("fixbugs_cw_")
    doc = d / "ms.md"
    doc.write_text("Abstract: We studied ten samples in detail.\n\n"
                   "Introduction\nWe did work.\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(WS / "paper-skills/paper-review/scripts/count_words.py"),
         str(doc), "--venue-profile", "nature-biotechnology", "--article-type", "article"],
        cwd=str(WS), text=True, capture_output=True)
    check("--venue-profile accepts the documented bare id",
          r.returncode == 0 and "caps: abstract" in r.stdout,
          r.stdout[-300:] + r.stderr[-300:])
    r2 = subprocess.run(
        [sys.executable, str(WS / "paper-skills/paper-review/scripts/count_words.py"),
         str(doc), "--venue-profile", "not-a-profile"],
        cwd=str(WS), text=True, capture_output=True)
    check("an unknown id still fails cleanly", r2.returncode == 2, r2.stderr[-200:])

    rows = cw.sections(doc.read_text(encoding="utf-8"))
    abstract = next((w for s, w, _n in rows if s == "abstract"), None)
    main = next((w for s, w, _n in rows if s == "main text"), None)
    check("an inline 'Abstract: ...' heading is separated", abstract == 6, str(rows))
    check("the inline abstract is not left in the main text", main == 3, str(rows))

    tex = ("\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n"
           "We did work here today.\n\\begin{thebibliography}{9}\n"
           "\\bibitem{a} Smith J. A paper. 2020.\n"
           "\\bibitem{b} Doe A. Another paper. 2021.\n"
           "\\end{thebibliography}\n\\end{document}\n")
    lines, abstract_end, captions = cw.tex_lines(tex)
    tex_rows = cw.sections("\n".join(lines), abstract_end=abstract_end,
                           caption_lines=captions)
    tex_main = next((w for s, w, _n in tex_rows if s == "main text"), None)
    check("thebibliography ends the main-text span", tex_main == 5, str(tex_rows))
    check("the reference heading is emitted", "References" in lines, str(lines))


# ---------------------------------------------------------------------------
# skill: F117 convert_corpus refuses submission symlinks
# ---------------------------------------------------------------------------
def test_f117():
    print("\n== F117: convert_corpus refuses submission symlinks ==")
    d = scratch("fixbugs_f117_")
    sub = d / "sub"
    sub.mkdir()
    (sub / "paper.md").write_text("Abstract: x\n\nIntroduction\nReal text.\n",
                                 encoding="utf-8")
    outside = d / "outside.md"
    outside.write_text("SECRET OUTSIDE CONTENT", encoding="utf-8")
    (sub / "notes.md").symlink_to(outside)
    (sub / "linkdir").symlink_to(d, target_is_directory=True)
    work = d / "work"
    r = subprocess.run(
        [sys.executable, str(WS / "paper-skills/paper-review/scripts/convert_corpus.py"),
         "--submission", str(sub), "--work", str(work)],
        cwd=str(WS), text=True, capture_output=True)
    check("the converter succeeds on the remaining files", r.returncode == 0, r.stderr[-300:])
    corpus = {p.name for p in (work / "corpus").glob("*")}
    check("the outside target is not copied", "notes.md.txt" not in corpus, str(corpus))
    check("a symlinked directory is not walked into",
          not any("outside" in p.name for p in (work / "corpus").glob("*")), str(corpus))
    inventory = json.loads((work / "inventory.json").read_text(encoding="utf-8"))
    check("the link is absent from the inventory",
          [e["path"] for e in inventory] == ["paper.md"], str(inventory))
    check("the omission is warned about once", "skipped 2 symlink(s)" in r.stdout,
          r.stdout[-300:])


def main():
    try:
        test_f003()
        test_f005()
        test_f017()
        test_f018()
        test_f024()
        test_f062()
        test_f069()
        test_f096()
        test_f020()
        test_f029()
        test_f036()
        test_f064()
        test_f065()
        test_f080()
        test_count_words()
        test_f117()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} failed")
        for name in FAILS:
            print(f"  FAILED: {name}")
        return 1
    print("ALL 2026-10-25 VERIFIED-FINDING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

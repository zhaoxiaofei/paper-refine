#!/usr/bin/env python3
"""The 2026-10-12 debug round: length-scan comments/abstract end, corpus roles,
Zotero marker ranges, bibliography parity word boundaries, display-item
supplementary families and the readiness/reason stamping order.

Run:  python3 .paper_test/test_debug_2026_1012.py

Every check below is a defect an independent audit of commit `6bd5840` reported
and this round reproduced on the tree:

  * the LaTeX readers stripped a comment only when the `%` had NO backslash
    before it, so `\\\\%` (a line break followed by a comment) leaked the whole
    comment into the prose the length/style scans count;
  * `\\end{abstract}` was only honoured at the START of a line: a normal
    `Last sentence.\\end{abstract}` left `abstract_end` unset, the NEXT paragraph
    was counted as abstract text and the main-text count lost it;
  * the corpus-role heuristic `(^|[^a-z])ref` classifies `refined_draft.txt` and
    `refresh_log.txt` as a BIBLIOGRAPHY, and a "references"-role file with no
    heading is then consumed as the reference region for the whole file (its
    in-text call-outs are never counted, its prose is read as entries);
  * `_entry_describes_item` / `_zotero_entry_match_score` matched a surname or
    title token as a SUBSTRING ("He" in "The method", "Li" in "Applied",
    "model" in "Remodeling"), so FMT-Z2 cannot see a bibliography entry that
    describes a different work;
  * `_marker_numbers` read `12-14 p. 5` as the single number 12 (the same
    cluster written `12-14, p. 5` expands), and a range it will not expand
    (`1-90`, a reversed `5-3`) was dropped ENTIRELY, so the field looks like it
    cites nothing and the refresh skips the document;
  * `display_order_rows` compared `Supplementary Figure 2` / `Extended Data
    Figure 3` as MAIN figures, firing a false FMT-O1 when the real `Figure 1`
    follows;
  * `decide` stamped `final_clean_version.certified` BEFORE the readiness
    findings joined the gate problems, so `--require-ready` could write
    `final_clean_version.certified: true` beside `certification.certified:
    false` -- the split `final_clean_reason` exists to prevent.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
FAILS = []
TMPDIRS = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nb = _load("paperp_dbg1012", WS / "paper_pipeline.py")
fmt = _load("paperf_dbg1012", WS / "paper_docx_format.py")
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
cw = _load("count_words_dbg1012", SCRIPTS / "count_words.py")
ec = _load("extract_citations_dbg1012", SCRIPTS / "extract_citations.py")
en = _load("extract_numbers_dbg1012", SCRIPTS / "extract_numbers.py")
ea = _load("extract_acronyms_dbg1012", SCRIPTS / "extract_acronyms.py")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


# =====================================================================
# D1 -- LaTeX comments and the abstract end are read as LaTeX reads them
# =====================================================================

def test_latex_readers():
    print()
    print("== D1 LaTeX comment stripping and the abstract boundary ==")
    comment = ("\\section{Results}\n"
               "Hello world.\\\\% this comment must not count at all here.\n")
    control = "\\section{Results}\nHello world.\n"
    lines, caps, end = nb._tex_length_scan(comment)
    cwords_ctl = nb.count_words(" ".join(nb._tex_length_scan(control)[0]))
    words = nb.count_words(" ".join(lines))
    check("D1 the pipeline does not count a \\\\% comment as prose",
          words == cwords_ctl and "comment" not in " ".join(lines),
          f"words={words} control={cwords_ctl} lines={lines}")
    clines, cend, ccaps = cw.tex_lines(comment)
    cwords = cw.count_words(" ".join(clines)) if hasattr(cw, "count_words") else \
        len(" ".join(clines).split())
    check("D1 count_words.py does not count a \\\\% comment as prose",
          cwords == cwords_ctl and "comment" not in " ".join(clines),
          f"words={cwords} lines={clines}")
    # ... and an escaped percent (`\%`) still belongs to the prose.
    escaped = "\\section{Results}\nA 50\\% reduction was observed today.\n"
    elines, _ecaps, _eend = nb._tex_length_scan(escaped)
    check("D1 an escaped \\% stays in the prose",
          nb.count_words(elines[-1]) == 6 and "50\\%" in elines[-1], str(elines))

    abstract = ("\\begin{abstract}\n"
                "We measured three cohorts of patients across sites.\n"
                "This last sentence ends the abstract.\\end{abstract}\n"
                "Results start here with the first finding of the study.\n")
    alines, acaps, aend = nb._tex_length_scan(abstract)
    check("D1 a mid-line \\end{abstract} closes the abstract", aend is not None,
          f"abstract_end={aend} lines={alines}")
    rows = {r["section"]: r["words"] for r in
            nb._length_rows_for_lines(alines, "d.tex", acaps, aend)}
    check("D1 the paragraph after \\end{abstract} is main text, not abstract",
          rows.get("abstract") == 14 and rows.get("main text") == 10,
          str(rows))
    clines2, cend2, _ccaps2 = cw.tex_lines(abstract)
    check("D1 count_words.py honours the mid-line \\end{abstract} too",
          cend2 is not None and clines2[cend2 - 1] == "This last sentence ends the abstract."
          and "Results start here" in clines2[cend2],
          f"end={cend2} lines={clines2}")


# =====================================================================
# D2 -- a filename is not a bibliography because it starts with "ref"
# =====================================================================

def test_ref_role_names():
    print()
    print("== D2 the corpus-role heuristic does not match ref-prefixed words ==")
    for mod, name in ((ec, "extract_citations"), (en, "extract_numbers"),
                      (ea, "extract_acronyms")):
        wrong = {n: mod.classify_context(n)
                 for n in ("refined_draft.docx.txt", "refresh_log.txt",
                           "refactored-main.docx.txt")}
        check(f"D2 {name}: a ref-PREFIXED word is not a bibliography",
              all(v != "references" for v in wrong.values()), str(wrong))
        # The positive controls are the names the corpus convention and
        # convert_corpus.py's own role guesser (`\brefs?\b|\breferences?\b`)
        # call a bibliography.
        right = {n: mod.classify_context(n)
                 for n in ("refs.docx.txt", "references.txt", "cnb-26-4-ref-list.txt",
                           "cnb-26-4-ref.docx.txt", "suppAll-d.bib")}
        check(f"D2 {name}: a real reference-role name still classifies as references",
              all(v == "references" for v in right.values()), str(right))

    # The harm: a "references"-role file with no heading is consumed as the
    # reference region, so its in-text call-out never reaches the sweep.
    work = scratch("paper_dbg_roles_") / "work"
    corpus = work / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "refined_draft.docx.txt").write_text(
        "The design follows our earlier benchmark [2] and the protocol of the\n"
        "consortium. No list is given in this file.\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPTS / "extract_citations.py"),
                           "--work", str(work)],
                          capture_output=True, text=True, timeout=120)
    art = work.parent / "artifacts" / "M2_citations.json"
    payload = json.loads(art.read_text(encoding="utf-8")) if art.is_file() else {}
    orphans = payload.get("orphan_callouts") or payload.get("orphans") or []
    check("D2 a ref-prefixed main-text file keeps its in-text call-out",
          proc.returncode == 0 and 2 in [int(x) for x in orphans],
          f"rc={proc.returncode} orphans={orphans} keys={sorted(payload)[:12]} "
          f"err={(proc.stderr or proc.stdout)[-160:]}")


# =====================================================================
# D3 -- bibliography parity compares WORDS, not substrings
# =====================================================================

def test_bibliography_word_match():
    print()
    print("== D3 bibliography entry matching uses word boundaries ==")
    he = {"author": [{"family": "He", "given": "X"}],
          "title": "Gene regulation in tumours", "issued": {"date-parts": [[2020]]}}
    check("D3 family 'He' does not match 'The method ...'",
          fmt._entry_describes_item(
              "The method we used to reconstruct the phylogeny was as follows.",
              he) is False
          and fmt._zotero_entry_match_score(
              "The method we used to reconstruct the phylogeny was as follows.", he) < 4,
          str(fmt._zotero_entry_match_score(
              "The method we used to reconstruct the phylogeny was as follows.", he)))
    li = {"author": [{"family": "Li", "given": "X"}], "title": "Genome assembly methods",
          "issued": {"date-parts": [[2020]]}}
    check("D3 family 'Li' does not match 'Applied and Environmental ...'",
          fmt._entry_describes_item(
              "Applied and Environmental Microbiology 12, 3 (2020).", li) is False,
          "")
    model = {"author": [{"family": "Zhao", "given": "Q"}], "title": "Model for CNV",
             "issued": {"date-parts": [[2020]]}}
    check("D3 title token 'model' does not match 'Remodeling of ...'",
          fmt._entry_describes_item(
              "Remodeling of chromatin architecture. Nature 588, 1 (2020).",
              model) is False, "")
    check("D3 a genuinely matching entry is still accepted",
          fmt._entry_describes_item(
              "Li X, et al. Copy number inference. Nature 12, 3 (2020).", li) is True
          and fmt._zotero_entry_match_score(
              "Li X, et al. Copy number inference. Nature 12, 3 (2020).", li) >= 4,
          str(fmt._zotero_entry_match_score(
              "Li X, et al. Copy number inference. Nature 12, 3 (2020).", li)))
    check("D3 a genuinely matching title token is still accepted",
          fmt._entry_describes_item(
              "Zhao Q. A model for CNV detection. Nature 588, 1 (2020).", model) is True, "")


# =====================================================================
# D4 -- the citation marker's numbers survive a page locator and a long range
# =====================================================================

def test_marker_numbers():
    print()
    print("== D4 citation-marker number parsing ==")
    cases = [
        ("\\super 12\u201314 p. 5\\nosupersub{}", [12, 13, 14],
         "a range glued to a page locator expands"),
        ("\\super 12-14, p. 5\\nosupersub{}", [12, 13, 14],
         "the comma spelling still expands"),
        ("\\super 1-3\\nosupersub{}", [1, 2, 3], "a short range still expands"),
        ("\\super 20-24,30\\nosupersub{}", [20, 21, 22, 23, 24, 30],
         "a list is unchanged"),
        ("\\super 1-90\\nosupersub{}", [1, 90],
         "a range too long to expand keeps its endpoints"),
        ("\\super 5-3\\nosupersub{}", [5, 3],
         "a reversed range keeps its endpoints"),
        ("\\super 2019-2020\\nosupersub{}", [],
         "a year range is still not a citation range"),
        ("\\super 3,39\\nosupersub{}", [3, 39], "a plain cluster is unchanged"),
    ]
    for marker, want, label in cases:
        got = fmt._marker_numbers(marker)
        check(f"D4 {label}", got == want, f"{marker!r} -> {got} (want {want})")


# =====================================================================
# D5 -- supplementary display items are their own family
# =====================================================================

def test_supplementary_families():
    print()
    print("== D5 supplementary/extended-data display items are not main figures ==")

    def rows(paras):
        return [r["evidence"] for r in fmt.display_order_rows(list(paras), order_policy=True)]

    check("D5 'Supplementary Figure 2' before 'Figure 1' is not an order defect",
          rows(["Supplementary Figure 2 shows the panel.",
                "Figure 1 shows the design."]) == [],
          str(rows(["Supplementary Figure 2 shows the panel.",
                    "Figure 1 shows the design."])))
    check("D5 'Extended Data Figure 3' before 'Figure 1' is not an order defect",
          rows(["Extended Data Figure 3 shows the panel.",
                "Figure 1 shows the design."]) == [],
          str(rows(["Extended Data Figure 3 shows the panel.",
                    "Figure 1 shows the design."])))
    check("D5 the S-spelling is still handled",
          rows(["Supplementary Figure S2 shows the panel.",
                "Figure 1 shows the design."]) == [], "")
    check("D5 a real main-text order defect is still reported",
          len(rows(["Figure 3 shows the panel.", "Figure 1 shows the design."])) == 1,
          str(rows(["Figure 3 shows the panel.", "Figure 1 shows the design."])))
    check("D5 supplementary items are still ordered among themselves",
          len(rows(["Supplementary Figure 3 lists them.",
                    "Supplementary Figure 1 lists them."])) == 1,
          str(rows(["Supplementary Figure 3 lists them.",
                    "Supplementary Figure 1 lists them."])))


# =====================================================================
# D6 -- final_clean_version.certified agrees with the certification verdict
# =====================================================================

def test_readiness_is_a_blocker_before_the_reason():
    print()
    print("== D6 decide: the published copy's verdict matches the certification ==")
    tmp = scratch("paper_dbg_ready_")
    source = tmp / "source"
    source.mkdir(parents=True)
    (source / "cnb-11-2-mainText-b.md").write_text(
        "Abstract\n\n" + ("word " * 120).strip() + "\n\nIntroduction\n\n"
        + ("text " * 300).strip() + "\n\nMethods\n\nx\n", encoding="utf-8")
    # An internal working note inside the published package: PKG-1 reads it as
    # a package-level finding, which `--require-ready` turns into a blocker.
    (source / "cnb-11-4-notes-c.md").write_text(
        "Hand-off notes.\n\nSee https://sorryios.ai/c/6aa536ff for the internal review.\n",
        encoding="utf-8")
    root = tmp / "root"

    def run(argv, timeout=900):
        return subprocess.run([sys.executable, str(WS / "paper_pipeline.py")] + argv,
                              capture_output=True, text=True, timeout=timeout)

    proc = run(["setup", "--source", str(source), "--root", str(root), "--rounds", "1",
                "--rewrites", "0", "--revises", "1", "--judges", "1"])
    check("D6 setup succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])
    proc = run(["run-decide", "--root", str(root), "--require-ready",
                "--agent-cmd", json.dumps([sys.executable, str(HERE / "stub_agent.py")]),
                "--judge-agent-cmd", json.dumps([sys.executable,
                                                 str(HERE / "stub_judge.py")]),
                "--retries", "0"])
    out = proc.stdout + proc.stderr
    decision_path = root / "reports" / "decision.json"
    check("D6 the decision was written", decision_path.is_file(), out[-300:])
    if not decision_path.is_file():
        return
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    cert = decision.get("certification") or {}
    fc = (decision.get("final") or {}).get("final_clean_version") or {}
    readiness = decision.get("readiness") or {}
    check("D6 the published copy carries the internal-artifact finding",
          (readiness.get("findings") or []) and not readiness.get("submission_ready"),
          json.dumps(readiness)[:200])
    check("D6 --require-ready blocks the certification",
          cert.get("certified") is False and proc.returncode == 5,
          f"rc={proc.returncode} cert={json.dumps(cert)[:200]}")
    check("D6 final_clean_version.certified agrees with the certification",
          fc.get("certified") is False,
          f"certified={fc.get('certified')} note={fc.get('certification_note')}")
    readme = root / "final_clean_version.readme.md"
    text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
    check("D6 the sibling readme says NOT CERTIFIED",
          "Certification: NOT CERTIFIED" in text, text[:200])


def main() -> int:
    test_latex_readers()
    test_ref_role_names()
    test_bibliography_word_match()
    test_marker_numbers()
    test_supplementary_families()
    if os.environ.get("PAPER_DBG_SKIP_HEAVY") != "1":
        test_readiness_is_a_blocker_before_the_reason()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-10-12 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

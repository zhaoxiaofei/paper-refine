#!/usr/bin/env python3
"""Fix-wave-1 regression checks for paper_docx_format_parts/p01_text_rules.py.

F59, F62, F71, F72, F85, F153, F154, F155/F156 and F193. Run with
`conda run -n paper-refine-test python .paper_test/test_fix_wave1_F_p01text.py`.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
_spec = importlib.util.spec_from_file_location("paper_docx_format",
                                               str(WS / "paper_docx_format.py"))
fmt = importlib.util.module_from_spec(_spec)
sys.modules["paper_docx_format"] = fmt
_spec.loader.exec_module(fmt)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def para(runs):
    body = "".join("<w:r>" + ("<w:rPr><w:i/></w:rPr>" if ital else "<w:rPr/>")
                   + '<w:t xml:space="preserve">' + escape(t) + "</w:t></w:r>"
                   for t, ital in runs)
    return '<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr>' + body + "</w:p>"


def rules(rows):
    return [r["rule"] for r in rows]

# --- F59: FMT-T9a compares OCCURRENCES, not runs ---------------------------
rows, fixes = fmt.emphasis_consistency({}, [
    (0, 0, para([("(Co-corresponding author; ", True), ("a@b.org)", True)])),
    (1, 0, para([("(Co-corresponding author; c@d.org)", False)]))])
ev = rows[0]["evidence"] if rows else ""
check("F59: one italic occurrence split over two runs is ONE place",
      "italic in 1 place(s)" in ev and "(p0, p0)" not in ev, ev)
check("F59: the 1:1 tie resolves to roman (no roman->italic fix)",
      bool(fixes) and all(f[3] is False for f in fixes), str(fixes))
mixed = para([("(Co-corresponding author; ", True), ("a@b.org)", False)])
check("F59: a genuinely mixed occurrence is still a FMT-T9a row",
      bool(fmt.emphasis_consistency({}, [(0, 0, mixed)])[0]))

# --- F62: end-matter section context without heading flags -----------------
ack = ["Introduction", "We studied many samples here.", "Acknowledgements",
       "We gratefully acknowledge the support of the NIH under grant R01 CA123456."]
t9k = [r for r in fmt.long_text_rows(ack, kinds=fmt.section_kinds(ack))
       if r["rule"] == "FMT-T9k"]
check("F62: an Acknowledgements paragraph is exempt from FMT-T9k (text source)",
      not [r for r in t9k if "paragraph 3" in r["evidence"]], t9k)
md = ["## Introduction", "We studied many samples here.", "## Acknowledgements",
      "We gratefully acknowledge the support of the NIH under grant R01 CA123456."]
check("F62: a Markdown '## Acknowledgements' heading is recognised",
      not [r for r in fmt.long_text_rows(md, kinds=fmt.section_kinds(md))
           if r["rule"] == "FMT-T9k" and "paragraph 3" in r["evidence"]])
check("F62: 'Acknowledgements' matches the end-matter section vocabulary",
      bool(fmt.SINGLE_SENTENCE_SKIP_SECTION_RE.match("Acknowledgements")))

# --- F71: Methods section headings ----------------------------------------
# --- F60: the declared sentence bar is a CAP (exactly-at-bar is legal) -----
bar46 = {"sentence_words": {"body": 46}}
at_bar = " ".join(["word"] * 46) + "."
over_bar = " ".join(["word"] * 47) + "."
check("F60 a sentence exactly at the declared bar is not a finding",
      not [r for r in fmt.long_text_rows([at_bar], kinds=["body"],
                                         style_limits=bar46)
           if "long sentence" in r["evidence"]])
check("F60 one word over the declared bar is a finding",
      bool([r for r in fmt.long_text_rows([over_bar], kinds=["body"],
                                          style_limits=bar46)
            if "long sentence" in r["evidence"]]))

lim = {"sentence_words": {"methods": 61, "abstract": 40}}
p71 = ["Abstract", "We report a thing.", "Experimental Procedures",
       "We used a method that " + " ".join(["w"] * 45) + "."]
check("F71: 'Experimental Procedures' switches the section to methods",
      fmt.section_kinds(p71)[-1] == "methods", fmt.section_kinds(p71))
check("F71: a 50-word Methods sentence is not measured against the abstract bar",
      not fmt.long_text_rows(p71, kinds=fmt.section_kinds(p71), style_limits=lim))

# --- F72: Markdown emphasis markers on a caption label --------------------
p72 = ["Introduction", "Body. ",
       "**Figure 1.** Cell counts across all donors and conditions."]
check("F72: a bold Markdown figure caption is a legend",
      fmt.section_kinds(p72)[-1] == "legend", fmt.section_kinds(p72))
check("F72: the bold caption is not a one-sentence paragraph",
      "FMT-T9k" not in rules(fmt.long_text_rows(p72, kinds=fmt.section_kinds(p72))))
long_cap = ["Introduction", "Body. ", "**Figure 1.** " + " ".join(["w"] * 300) + "."]
check("F72: a long bold caption is not a FMT-T9i mega-paragraph",
      "FMT-T9i" not in rules(fmt.long_text_rows(
          long_cap, kinds=fmt.section_kinds(long_cap),
          style_limits={"paragraph_words": 250})))

# --- F85: abbreviation-aware sentence split -------------------------------
long85 = ("We compared the assay to the published workflow of Smith et al. and found "
          "that the measured values agreed closely with the reference standard across all "
          "of the tested samples in the cohort and in two additional validation cohorts "
          "that were processed with a different library preparation protocol at a second site.")
split = getattr(fmt, "split_sentences", lambda text: [])
check("F85: the shared abbreviation-aware splitter exists",
      callable(getattr(fmt, "split_sentences", None)))
check("F85: 'et al.' does not split the sentence", len(split(long85)) == 1, split(long85))
check("F85: 'Fig. 3 ...' is one sentence",
      split("Fig. 3 shows the result. Ginkgo gave the highest ROC-AUC.")
      == ["Fig. 3 shows the result.", "Ginkgo gave the highest ROC-AUC."],
      split("Fig. 3 shows the result. Ginkgo gave the highest ROC-AUC."))
check("F85: the 52-word sentence reaches the profile bar",
      any(r["rule"] == "FMT-T9c" and "long sentence (52 words" in r["evidence"]
          for r in fmt.long_text_rows([long85], kinds=["body"],
                                      style_limits={"sentence_words": {"body": 46}})))
led = fmt.number_ledger(["As Smith et al. reported in 2019, 42 samples were used."])
check("F85: the number ledger keeps the whole sentence",
      bool(led) and led[0]["sentence"].startswith("As Smith et al. reported"), led[:1])
# R02: an abbreviation period is non-terminal only when the abbreviation is
# mid-sentence; `Smith et al. The ...` is a real boundary and must split.
check("R02: a real sentence boundary after 'et al.' splits",
      split("We followed Smith et al. The trial enrolled thirty patients.")
      == ["We followed Smith et al.", "The trial enrolled thirty patients."],
      split("We followed Smith et al. The trial enrolled thirty patients."))
check("R02: 'e.g. Python' and 'Fig. 3' still do not split",
      split("We use tools, e.g. Python and Julia. Fig. 3 shows it.")
      == ["We use tools, e.g. Python and Julia.", "Fig. 3 shows it."],
      split("We use tools, e.g. Python and Julia. Fig. 3 shows it."))
r02_long = "We followed Smith et al. The " + " ".join(["word"] * 44) + "."
check("R02: a 45-word sentence after 'et al.' is measured alone",
      not any(r["rule"] == "FMT-T9c" for r in fmt.long_text_rows(
          [r02_long], kinds=["body"],
          style_limits={"sentence_words": {"body": 46}})),
      fmt.long_text_rows([r02_long], kinds=["body"],
                         style_limits={"sentence_words": {"body": 46}}))
led2 = fmt.number_ledger(["We followed Smith et al. The trial enrolled 42 patients."])
check("R02: the number ledger sees the sentence after 'et al.' as its own",
      bool(led2) and led2[0]["sentence"] == "The trial enrolled 42 patients.", led2[:1])

# --- F153: the 40-word floor is for the single-word branch only -----------
journal = ("Nature Biotechnology published the work. Nature Biotechnology reviewed it. "
           "We thank Nature Biotechnology. Nature Biotechnology is cited.")
check("F153: a 17-word paragraph naming the journal 4x is FMT-T8c",
      any(r["rule"] == "FMT-T8c" and "4x" in r["evidence"]
          for r in fmt.term_repetition_rows([journal], [False])))
check("F153: a short single-word repetition keeps the floor (no row)",
      fmt.term_repetition_rows(["performance " * 8], [False]) == [])

# --- F154: a DOI's digits are not a quantity -----------------------------
check("F154: doi:10.1000/xyz123 does not mix separators with 1,000",
      fmt.number_format_rows(["We processed 1,000 cells; see doi:10.1000/xyz123."]) == [])
check("F154: a real 10,000-vs-20000 mix is still reported",
      any(r["rule"] == "FMT-T9h"
          for r in fmt.number_format_rows(["We processed 10,000 cells and 20000 more."])))

# --- F155 / F156: FMT-T9i scope ------------------------------------------
cap = "Table 1. " + " ".join(["w"] * 220) + "."
check("F155: a long Table caption is not a FMT-T9i mega-paragraph",
      "FMT-T9i" not in rules(fmt.long_text_rows(
          [cap], kinds=["body"], in_area=[True],
          style_limits={"paragraph_words": 200})))
check("F156: FMT-T9i does not run on the abstract",
      "FMT-T9i" not in rules(fmt.long_text_rows(
          ["Abstract " + " ".join(["w"] * 300) + "."], kinds=["abstract"],
          style_limits={"paragraph_words": 250})))

# --- F193: outline refs keep the supplementary label ---------------------
row = fmt.outline_rows(["As shown in Supplementary Figure 1 and Fig. 2."])[0]
refs = [r for r in row["refs"].split(",") if r]
check("F193: 'Supplementary Figure 1' is not rewritten as 'Figure 1'",
      "Supplementary Figure 1" in refs and "Figure 1" not in refs, row["refs"])
check("F193: the outline's first sentence is not cut at 'Fig.'",
      row["first_sentence"] == "As shown in Supplementary Figure 1 and Fig. 2.",
      row["first_sentence"])

print()
if FAILS:
    print(f"{len(FAILS)} check(s) FAILED: {FAILS}")
    sys.exit(1)
print("all checks passed")

#!/usr/bin/env python3
"""Regressions for wave 1 of the 2026-10-26 fix-bugs stage (candidate F-004..F-216).

Hermetic: temp dirs only, no network, no Word. Run:
    python3 .paper_test/test_fix_bugs_20261026_wave1.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("wave1_pp", WS / "paper_pipeline.py")
fmt = load("wave1_fmt", WS / "paper_docx_format.py")
ec = load("wave1_ec", WS / "paper-skills/paper-review/scripts/extract_citations.py")
en = load("wave1_en", WS / "paper-skills/paper-review/scripts/extract_numbers.py")
ea = load("wave1_ea", WS / "paper-skills/paper-review/scripts/extract_acronyms.py")
eo = load("wave1_eo", WS / "paper-skills/paper-review/scripts/extract_occurrences.py")
cw = load("wave1_cw", WS / "paper-skills/paper-review/scripts/count_words.py")
qa = load("wave1_qa", WS / "paper_qwen_agent.py")


def test_numbers():
    print("\n== numbers / occurrences ==")
    def hits(text):
        out = []
        for label, pat in en.LABEL_PATTERNS:
            for m in pat.finditer(text):
                if label == "percentage" and (
                        en.re.match(r"\s*(?:CI|confidence)\b", text[m.end():], en.re.I)
                        or en.re.search(r"(?:CI|confidence)\s*$", text[:m.start()], en.re.I)):
                    continue
                out.append((label, m.group(1) if m.lastindex else m.group(0)))
        return out
    check("F-128 'p of 12' is not a p-value", hits("a group p of 12 patients") == [],
          str(hits("a group p of 12 patients")))
    check("F-168 a U+2212 exponent is kept",
          hits("p = 1.2e\u22124") == [("p-value", "1.2e\u22124")],
          str(hits("p = 1.2e\u22124")))
    check("F-169 a space-grouped count is one number",
          hits("n = 1 234") == [("n", "1 234")], str(hits("n = 1 234")))
    check("F-171 'CI 95%' is not a percentage",
          not any(lbl == "percentage" for lbl, _v in hits("CI 95%")), str(hits("CI 95%")))
    check("F-171 a signed interval keeps its sign",
          ("CI", "-1.2") in hits("95% CI -1.2 to 0.4"), str(hits("95% CI -1.2 to 0.4")))
    check("F-172 'AUC was approximately' is inventoried",
          ("AUC", "0.91") in hits("AUC was approximately 0.91"), str(hits("AUC was approximately 0.91")))
    check("F-172 'R2 was' is inventoried", ("R2", "0.80") in hits("R2 was 0.80"),
          str(hits("R2 was 0.80")))
    check("F-179 leading-dot percent keeps the dot", hits(".5%") == [("percentage", ".5")],
          str(hits(".5%")))
    check("F-179 em-dash CI is inventoried", ("CI", "1.2") in hits("CI 1.2\u20143.4"),
          str(hits("CI 1.2\u20143.4")))
    check("F-113 APA bracket CI is inventoried", ("CI", "1.2") in hits("95% CI [1.2, 3.4]"),
          str(hits("95% CI [1.2, 3.4]")))
    check("F-095 a rounded scientific form is not the value",
          not eo.variant_pattern("1234.5", "value").search("1.2e+03"))
    check("F-095 the exact scientific form is matched",
          bool(eo.variant_pattern("0.0215", "value").search("2.15e-02")))


def test_reference_heuristics():
    print("\n== reference regions / contexts / citations ==")
    lines = ["References", "Smith J, Doe A (2020). Title. Journal.", "",
             "In 2020 we reanalysed the cohort and found n = 12 more cases."]
    check("F-025 a post-references prose paragraph ends the region",
          en.find_reference_region(lines)[1] == 3, str(en.find_reference_region(lines)))
    for name in ("config.txt", "notable_findings.txt", "subtitle_analysis.txt",
                 "abstraction.md"):
        check(f"F-121 {name} is not a display/role context",
              en.classify_context(name) == "main text", en.classify_context(name))
    check("F-121 a real figure name is still a legend",
          en.classify_context("figs.md") == "figure legend", en.classify_context("figs.md"))
    inline = r"before \begin{verbatim}secret\end{verbatim}\cite{after}"
    check("F-126 a one-line verbatim closes on the same line",
          "\\cite{after}" in ec.latex_source_text(inline))
    check("F-127 Darwin (1859) is an author-year call-out",
          any(m.group(0) == "Darwin (1859)" for m in ec.AY_CIT_RE.finditer("Darwin (1859)")))
    check("F-180 DNA and RNA 2020 is rejected as date prose",
          all(ec.is_date_prose(m) for m in ec.AY_CIT_RE.finditer("DNA and RNA 2020")))
    check("F-180 'Results and Discussion 2020' is rejected",
          all(ec.is_date_prose(m) for m in ec.AY_CIT_RE.finditer(
              "See Results and Discussion 2020.")))
    check("F-180 a real two-author call-out survives",
          not ec.is_date_prose(next(ec.AY_CIT_RE.finditer("Smith and Jones 2020"))))
    check("F-180 the pinned range treatment is unchanged",
          ec.parse_nums("1-250") == [1, 250] and ec.parse_nums("8-3") == [3, 8])


def test_acronyms_and_words():
    print("\n== acronyms / word count ==")
    check("F-097 a LaTeX citation key is not prose",
          "smith2019" not in ea.mask_nonprose(r"we cite \cite{smith2019} here").lower())
    tex = ("\\begin{abstract}One two.\\end{abstract}\n\\section{Introduction}\n"
           "Alpha beta gamma.\n\\begin{verbatim}\nnot counted at all here\n"
           "\\end{verbatim}\nDelta epsilon.\n")
    lines, _abs, _caps = cw.tex_lines(tex)
    check("F-130 a verbatim body is not prose", "not counted" not in " ".join(lines),
          str(lines))
    _a = en._metric_key("n", "1 234")
    check("F-060 a thin/space-grouped key normalizes", _a == "1234", _a)


def test_pipeline_helpers():
    print("\n== pipeline helpers ==")
    check("F-028 F1000 takes 'an'", pp._indefinite("F1000") == "an F1000", pp._indefinite("F1000"))
    check("F-163 dietary supplementation is main",
          pp.docx_document_role("Dietary_supplementation.docx") == "main")
    check("F-163 supplemental material is still supplementary",
          pp.docx_document_role("Supplemental_Material.docx") == "supp")
    check("F-143 base_editor_results is not feedback",
          pp.is_journal_feedback_name("base_editor_results.docx") is False)
    check("F-143 an actual editor comments file is feedback",
          pp.is_journal_feedback_name("editor_comments.docx") is True)
    check("F-143 a camel-case reviewer comments file is feedback",
          pp.is_journal_feedback_name("ReviewersComments.docx") is True)
    check("F-143 a camel-case editor comments file is feedback",
          pp.is_journal_feedback_name("EditorComments.docx") is True)
    check("F-143 a doubly-suffixed letter-to-the-editor is a manuscript",
          pp.is_journal_feedback_name("letter_to_the_editor.docx.txt") is False)
    prev_dir = scratch("wave1_prev_") / "human_review_feedback"
    prev_dir.mkdir(parents=True)
    for _name in ("cover_letter.docx", "response_to_reviewers.docx",
                  "uncover_response.docx"):
        (prev_dir / _name).write_text("stub", encoding="utf-8")
    ctx = types.SimpleNamespace(pristine=prev_dir.parent)
    prev = [label for _p, label in pp.journal_previous_responses(ctx)]
    check("F-144 the cover letter is not a previous response and real replies survive",
          prev == ["human_review_feedback/response_to_reviewers.docx",
                   "human_review_feedback/uncover_response.docx"], str(prev))
    check("F-193 a one-ulp difference is not reproduced",
          pp._probe_value_equal("9007199254740993", "9007199254740992") is False)
    check("F-193 0.031 and 3.1e-2 still compare equal",
          pp._probe_value_equal("0.031", "3.1e-2") is True)
    refs = pp._numbered_reference_titles(
        ["References.", "[1] Smith J. A title. 2020.", "2) Doe A. Another. 2021."])
    check("F-141/F-165 bracket/parenthesis numbering and 'References.' are read",
          refs.get(1, "").startswith("Smith") and refs.get(2, "").startswith("Doe"), str(refs))
    refs = pp._numbered_reference_titles(
        ["1.\nHow introns enhance gene expression. 2019.", "References",
         "1. Nurk, S. et al. Science 372 (2021)."])
    check("F-182 a body two-line number does not overwrite the real entry",
          refs.get(1, "").startswith("Nurk"), str(refs))
    check("F-183 a cited panel letter is kept",
          "s3a" in pp._pkg4_cited_labels("S3a"), str(pp._pkg4_cited_labels("S3a")))
    check("F-184 a compressed data name is visible",
          bool(pp.PKG2_NAME_RE.search("reads.fastq.gz")) and
          bool(pp.PKG2_NAME_RE.search("data.csv.gz")), str(pp.PKG2_NAME_RE.pattern))


def test_docx_helpers():
    print("\n== docx helpers ==")
    check("F-032 a bare caption does not swallow a trailing body brace",
          pp._tex_captions(r"\caption{Alpha beta} {gamma delta}") == ["Alpha beta"],
          str(pp._tex_captions(r"\caption{Alpha beta} {gamma delta}")))
    check("F-032 a captionof type argument still works",
          pp._tex_captions(r"\captionof{figure}[short]{Alpha beta}") == ["Alpha beta"])
    check("F-033 math after a line break is stripped",
          "$" not in pp._strip_latex(r"line \\$x$ next"), pp._strip_latex(r"line \\$x$ next"))
    check("F-081 noBreakHyphen is rendered as a hyphen",
          fmt.text_of('<w:p><w:r><w:t>ten</w:t><w:noBreakHyphen/><w:t>year</w:t></w:r></w:p>')
          == "ten-year")
    _raw, _vis = fmt._zotero_cluster_for_ranks([4, 5, 6], "1,2,3")
    check("F-061 a comma cluster is not rebuilt as a range", _vis == "4,5,6", _vis)
    _raw2, _vis2 = fmt._zotero_cluster_for_ranks([4, 5, 6], "1-3")
    check("F-061 an original range still collapses", _vis2 == "4-6", _vis2)
    check("F-058 6.6 does not produce the candidate 7",
          "7" not in fmt._num_candidates(6.6), str(fmt._num_candidates(6.6)))
    check("F-173 a leading minus is part of the number",
          any(r.get("number") == "-80" for r in fmt.number_ledger(["Dose -80 mg."])))
    check("F-057 a glued decimal is not truncated",
          any(r.get("number") == "7.5" for r in fmt.number_ledger(["Dose 7.5mg."])))
    rpr = ('<w:rPr><w:i/><w:rPrChange><w:rPr><w:i/></w:rPr></w:rPrChange></w:rPr>')
    new, _changed = fmt._rpr_set_emphasis(rpr, False)
    check("F-080 rPrChange is preserved verbatim",
          "<w:rPrChange><w:rPr><w:i/></w:rPr></w:rPrChange>" in new, new)
    raw = (b'<w:instrText>ADDIN </w:instrText>'
           b'<w:instrText>ZOTERO_ITEM</w:instrText>')
    check("F-020 split instrText fields are found", fmt._part_has_zotero_item_field(raw))


def cleanup():
    import shutil
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_numbers, test_reference_heuristics, test_acronyms_and_words,
               test_pipeline_helpers, test_docx_helpers):
        try:
            fn()
        except Exception:                                             # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append(fn.__name__)
    cleanup()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)

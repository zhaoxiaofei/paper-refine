#!/usr/bin/env python3
"""Regression tests for the 2026-11-23 19:21 fix-bugs wave (26 verified findings).

Each check asserts the POST-FIX behaviour of one confirmed candidate; on the
pre-fix tree the same check failed (the reproduction is in
debug_runs/20261123-192151/03_fix_bugs/fix_bugs_report.md). One `[ok ]`/`[FAIL]`
line per check, as `.paper_test/run_all.py` requires.

Run: python3 .paper_test/test_fix_bugs_20261123_192151.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "paper-skills" / "paper-review" / "scripts"))

import paper_docx_format as fmt                 # noqa: E402
import paper_pipeline as pipe                   # noqa: E402
import convert_corpus as corpus                 # noqa: E402
import count_words as words                     # noqa: E402
import extract_citations as citations           # noqa: E402
import extract_acronyms as acronyms             # noqa: E402

FAILS: list[str] = []


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


W_BODY = ('<w:document><w:body><w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>'
          '<w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p></w:body></w:document>')


def test_corpus_whitespace() -> None:
    print("\n== F01-F05: a legal whitespace-closed DOCX tag is read ==")
    check("F01 a whitespace-closed w:t keeps its text",
          corpus.docx_part_to_lines(W_BODY.replace("</w:t>", "</w:t >"))[0]
          == ["First paragraph.", "Second paragraph."])
    check("F02 a whitespace-closed w:p separates paragraphs",
          corpus.docx_part_to_lines(W_BODY.replace("</w:p>", "</w:p >"))[0]
          == ["First paragraph.", "Second paragraph."])
    hidden = ('<w:document><w:body><w:p><w:r><w:rPr><w:vanish/></w:rPr>'
              '<w:t>SECRET</w:t></w:r><w:r><w:t>Visible</w:t></w:r></w:p></w:body></w:document>')
    check("F03 a whitespace-closed hidden run is omitted",
          corpus.docx_part_to_lines(hidden.replace("</w:r>", "</w:r >"))[0] == ["Visible"])
    moved = ('<w:document><w:body><w:p><w:moveFrom><w:r><w:t>DELETED</w:t></w:r>'
             '</w:moveFrom><w:r><w:t>Live</w:t></w:r></w:p></w:body></w:document>')
    check("F04 a whitespace-closed moveFrom is scrubbed",
          corpus.docx_part_to_lines(moved.replace("</w:moveFrom>", "</w:moveFrom >"))[0]
          == ["Live"])
    alt = ('<w:document><w:body><w:p><mc:AlternateContent><mc:Choice><w:r><w:t>VISIBLE'
           '</w:t></w:r></mc:Choice><mc:Fallback><w:r><w:t>FALLBACK</w:t></w:r></mc:Fallback>'
           '</mc:AlternateContent></w:p></w:body></w:document>')
    check("F05 a whitespace-closed mc branch keeps one visible copy",
          corpus.docx_part_to_lines(
              alt.replace("</mc:AlternateContent>", "</mc:AlternateContent >"))[0] == ["VISIBLE"]
          and corpus.docx_part_to_lines(
              alt.replace("</mc:Choice>", "</mc:Choice >").replace(
                  "</mc:Fallback>", "</mc:Fallback >"))[0] == ["VISIBLE"])


def test_docx_format() -> None:
    print("\n== F06/F08/F14/F15/F24/F28: shared OOXML/text readers ==")
    xml = ('<w:p><w:hyperlink r:id="rId1"><w:r><w:rPr><w:color w:val="0000FF"/>'
           '<w:rPrChange w:id="1"><w:rPr><w:color w:val="FF0000"/></w:rPr></w:rPrChange >'
           '</w:rPr><w:t>link</w:t></w:r></w:hyperlink></w:p>')
    out, _changes, _ = fmt.fix_document(xml, {}, dict(fmt.POLICY_DEFAULTS, url_style="plain"))
    check("F06 a whitespace-closed rPrChange keeps its tracked history", "FF0000" in out, out)
    check("F08 a quoted `>` in an attribute does not leak into text",
          fmt.text_of('<w:t w:rsidR="a>b">x</w:t>') == "x",
          repr(fmt.text_of('<w:t w:rsidR="a>b">x</w:t>')))
    check("F14 a whitespace-closed template rPr is copied",
          fmt._ppr_extra('<w:pPr><w:rPr><w:rFonts w:ascii="Times"/></w:rPr ></w:pPr>')
          == '<w:rPr><w:rFonts w:ascii="Times"/></w:rPr >')
    check("F15 a whitespace-closed run is split",
          fmt.split_run_text_span(
              '<w:r><w:rPr><w:b/></w:rPr><w:t>abc</w:t></w:r >', 0, 3) is not None)
    check("F24 negative zero renders as 0", fmt._fmt_number(-0.0) == "0")
    check("F28 a GFM row without outer pipes is a table row",
          fmt._table_row_like("A | B") and fmt._table_row_like("1 | 2")
          and fmt._table_row_like("--- | ---"))


def test_text_rules() -> None:
    print("\n== F09/F11/F25: sentence and section rules ==")
    check("F09 a one-letter symbol before a real boundary splits",
          fmt.split_sentences("We used vitamin C. The cells grew.")
          == ["We used vitamin C.", "The cells grew."],
          fmt.split_sentences("We used vitamin C. The cells grew."))
    check("F09 a personal initial does not split",
          fmt.split_sentences("J. Smith reported the result. The end.")
          == ["J. Smith reported the result.", "The end."])
    check("F25 a closing quote/parenthesis precedes the boundary",
          fmt.split_sentences('He said "Go." Then he left.')
          == ['He said "Go."', "Then he left."]
          and fmt.split_sentences("It is done.) Next sentence.")
          == ["It is done.)", "Next sentence."])
    check("F11 a Markdown heading labels its section",
          fmt.section_kinds(["## Methods", "We did X."])[1] == "methods"
          and fmt.section_kinds(["## References", "Smith J. 2020."])[1] == "refs"
          and fmt.section_kinds(["References", "Smith J. 2020."])[1] == "refs")


def test_scripts() -> None:
    print("\n== F10/F16/F27/F31: standalone review scripts ==")
    check("F10 an unclosed fence and indented code are not prose",
          words.count_words(words.strip_markdown_nonprose(
              "Main text.\n```\ncode words here\n")) == 2
          and words.count_words(words.strip_markdown_nonprose(
              "Main text.\n\n    code line one\n    code line two\n")) == 2)
    check("F16 a glued numbered reference entry is recognized",
          citations.find_reference_region(
              ["References", "[1]Smith J. Title. Journal. 2020.",
               "[2]Jones K. Title2. Journal. 2021."])[1] == 3)
    check("F27 an irregular abbreviation key is defined",
          acronyms._comma_definitions("IQR, interquartile range") != {})
    check("F31 the pipeline's article-type suffixes are shared",
          words._name_is_type_manuscript("Article-final.docx", ["Article"])
          and words._name_is_type_manuscript("Article-abc1234.docx", ["Article"])
          and not words.is_cover_letter(
              "Dear Editor,\nPlease consider our manuscript.\n",
              "Article-abc1234.docx", ["Article"]))


def test_repair_regressions() -> None:
    print("\n== R01/R02/R03/R04/R05: regressions found by the verify-fixes review ==")
    refs = ["References", "[1] Smith J. T. J. 2020.", "[2] Jones K. T2. J. 2021.",
            "", "3.5-fold increase in expression was observed across all samples.",
            "", "The next paragraph has no numeric lead."]
    check("R01 decimal-leading prose is not a reference entry",
          citations.looks_like_reference_entry(
              "3.5-fold increase in expression was observed across all samples.") is False
          and citations.find_reference_region(refs)[1] == 4
          and citations.looks_like_reference_entry(
              "[1]Smith J. T. J. 2020.") is True
          and citations.find_reference_region(
              ["References", "[1]Smith J. Title. Journal. 2020.",
               "[2]Jones K. Title2. Journal. 2021."])[1] == 3,
          citations.find_reference_region(refs))
    hanging = ("1. Smith J, Jones K.\n    A title of a paper. Journal. 2020.\n"
               "2. Doe A.\n    Another title. Journal. 2021.\n")
    continuation = "- item one with words\n    continued prose here\n- item two\n"
    check("R02 a hanging reference continuation is prose",
          words.count_words(words.strip_markdown_nonprose(hanging))
          == words.count_words(hanging) == 19,
          words.count_words(words.strip_markdown_nonprose(hanging)))
    check("R02 a list-item continuation is prose",
          words.count_words(words.strip_markdown_nonprose(continuation))
          == words.count_words(continuation) == 11,
          words.count_words(words.strip_markdown_nonprose(continuation)))
    check("R02 a genuine indented code block is still blanked",
          words.count_words(words.strip_markdown_nonprose(
              "Text.\n\n    code line one\n    code line two\n")) == 1)
    check("R03 count-form and inflected filler are rejected",
          pipe._coverage_disposition_ok("0 findings -- lorem ipsum") is False
          and pipe._coverage_disposition_ok("clean -- basis: no problems found") is False
          and pipe._coverage_disposition_ok("clean -- basis: all checks passed") is False
          and pipe._audit_disposition_ok("clean -- basis: no problems found") is False
          and pipe._is_recorded_reason("no problems found") is False
          and pipe._defect_audit_reason_ok("no problems found") is False)
    check("R03 named count-form reasons still pass",
          pipe._coverage_disposition_ok("0 findings -- artifacts/M1_acronyms.md")
          and pipe._coverage_disposition_ok("3 findings; none critical"))
    hyper = ('<w:p><w:hyperlink r:id="a>b"><w:r><w:t>Hello</w:t>'
             '</w:r></w:hyperlink></w:p>')
    unwrapped, _changes, _ = fmt.fix_document(
        hyper, {}, dict(fmt.POLICY_DEFAULTS, url_style="plain"))
    check("R04 a legal `>` in a hyperlink attribute never leaks into text",
          unwrapped == '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>', unwrapped)
    anchored = ('<w:p><w:hyperlink r:id="a>b" w:anchor="s1"><w:r><w:t>Hello</w:t>'
                '</w:r></w:hyperlink></w:p>')
    kept, _changes, _ = fmt.fix_document(
        anchored, {}, dict(fmt.POLICY_DEFAULTS, url_style="plain"))
    check("R04 the anchor guard reads the quoted attribute, not its `>`",
          kept == anchored, kept)
    check("R05 prose with an inline pipe is not a table row",
          fmt._table_row_like("The ratio a | b is 2.") is False
          and fmt._table_row_like("see Table | for values") is False
          and fmt._table_row_like("A | B") and fmt._table_row_like("1 | 2")
          and fmt._table_row_like("--- | ---"))
    prose_rows = [r for r in fmt.long_text_rows(
        ["The ratio a | b is 2."], kinds=["body"], headings=[False])
        if r.get("rule") == "FMT-T9k"]
    table_rows = [r for r in fmt.long_text_rows(
        ["Model name | Accuracy (%).", "--- | ---", "x | 1"],
        kinds=["body"] * 3, headings=[False] * 3) if r.get("rule") == "FMT-T9k"]
    check("R05 FMT-T9k reports pipe prose but exempts a real table",
          len(prose_rows) == 1 and table_rows == [], (prose_rows, table_rows))


def test_pipeline_gates() -> None:
    print("\n== F07/F12/F13/F17/F22: pipeline gates and helpers ==")
    for text in ("https://x/y?X-Goog-Signature=abc123", "https://x/y?X-Amz-Signature=abc",
                 "https://x/y?sig=abc", "Authorization: Bearer abc.def",
                 "api_key: abc", "X-Api-Key: abc"):
        red = pipe.redact_secrets(text)
        check(f"F07 {text!r} is redacted", "abc" not in red and "abc.def" not in red, red)
    check("F12 generic filler is not a disposition",
          pipe._coverage_disposition_ok("clean -- basis: lorem ipsum dolor sit amet") is False
          and pipe.disposition_artifact_problems(
              [{"disposition": "OK — lorem ipsum dolor sit"}])
          and pipe._is_recorded_reason("lorem ipsum dolor sit amet") is False
          and pipe._defect_audit_reason_ok("lorem ipsum dolor sit amet") is False
          and pipe._audit_disposition_ok("0 findings -- lorem ipsum") is False)
    check("F12 named reasons still pass",
          pipe._coverage_disposition_ok("clean -- basis: artifacts/M1_acronyms.md")
          and pipe.disposition_artifact_problems(
              [{"disposition": "OK — checked the table"}]) == []
          and pipe._defect_audit_reason_ok("base/main.md:12 quotes the sentence"))
    check("F12/F01 a count tail is read the same way by the coverage and audit gates",
          pipe._audit_disposition_ok("0 findings; lorem ipsum") is False
          and pipe._coverage_disposition_ok("0 findings; lorem ipsum") is False
          and pipe._audit_disposition_ok("0 findings -- none") is True
          and pipe._coverage_disposition_ok("0 findings -- none") is True
          and pipe._audit_disposition_ok("3 findings; unable to see") is True)
    check("F13 heading style ids are case-insensitive",
          pipe._docx_heading_style("heading1") and pipe._docx_heading_style("H1")
          and pipe._docx_heading_style("Heading1"))
    check("F13 a declared non-heading style name still wins over the id",
          pipe._docx_heading_style("H1", {"H1": "Body Text"}) is False
          and pipe._docx_heading_style("H1", {"H1": "heading 1"}) is True)
    seed = {"candidates": [{"text": "fix this"}]}
    sandbox = Path(tempfile.mkdtemp(prefix="fix192151_seed_"))
    (sandbox / "feedback").mkdir()
    (sandbox / "feedback" / "CONCERN_SEED.json").write_text(json.dumps(seed))
    check("F17 a seed with candidates but no ids fails the coverage gate",
          pipe.journal_seed_coverage_problems(sandbox, seed, [], require_missing=True) != [])
    check("F22 the helper implements its documented `Figures 1-3` example",
          pipe._pkg4_cited_labels("Figures 1-3") == ["1", "2", "3"])


def test_test_harness_and_docs() -> None:
    print("\n== F19/F20/F32: root-only skips, docs and symlink containment ==")
    for rel in ("test_wave2_G1.py", "test_fix_bugs_20261114_I.py",
                "test_fix_bugs_20261115_wave2_utils.py"):
        text = (HERE / rel).read_text(encoding="utf-8")
        check(f"F19 {rel} reports a root-only skip as `[skip]`",
              'check("' not in text or "check skipped" not in text)
        check(f"F19 {rel} has a separate skip counter",
              "SKIPS" in text and "def skip(" in text)
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    check("F20 the README names the current judge harness flag",
          "`--judge-agent`/`conflicts`" not in readme
          and "`--judge-agent-harness`/`conflicts`" in readme)
    vs = _load(ROOT / "paper-skills" / "tests" / "validate_skill.py", "fix192151_vs")
    pr = _load(ROOT / "paper-skills" / "tests" / "probe_regressions.py", "fix192151_pr")
    for name, mod in (("validate_skill", vs), ("probe_regressions", pr)):
        base = Path(tempfile.mkdtemp(prefix=f"fix192151_{name}_"))
        skill = base / "skill"
        skill.mkdir()
        (skill / "keep.txt").write_text("keep")
        link = base / "link"
        link.symlink_to(skill)
        victim = link / "victim"
        victim.mkdir()
        (victim / "data.txt").write_text("data")
        refused = False
        try:
            mod._fresh_run_dir(str(victim), str(skill))
        except SystemExit:
            refused = True
        check(f"F32 {name} refuses a symlinked --run-dir inside the skill tree",
              refused and (skill / "victim" / "data.txt").exists())


def main() -> int:
    test_corpus_whitespace()
    test_docx_format()
    test_text_rules()
    test_scripts()
    test_repair_regressions()
    test_pipeline_gates()
    test_test_harness_and_docs()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL 2026-11-23 19:21 FIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

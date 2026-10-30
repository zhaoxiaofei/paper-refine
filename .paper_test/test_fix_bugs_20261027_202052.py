#!/usr/bin/env python3
"""Regression checks for the 2026-10-27 20:20 fix-bugs wave (44 candidates).

Every check pins a candidate confirmed on this tree by reproducing the cited
behaviour before the fix. Hermetic: temp dirs only, no network, no Word.
Run: python3 .paper_test/test_fix_bugs_20261027_202052.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import types
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
if str(WS) not in sys.path:
    sys.path.insert(0, str(WS))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

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


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


import paper_docx_format as fmt
import paper_pipeline as pp

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def make_docx(path: Path, body: str, settings: str = "", app_pages: int = None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document xmlns:w="{W_NS}">'
                   f"<w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", f'<w:styles xmlns:w="{W_NS}"/>')
        if settings:
            z.writestr("word/settings.xml", f'<w:settings xmlns:w="{W_NS}">{settings}</w:settings>')
        if app_pages is not None:
            z.writestr("docProps/app.xml",
                       '<Properties xmlns="http://schemas.openxmlformats.org/'
                       'officeDocument/2006/extended-properties">'
                       f"<Pages>{app_pages}</Pages></Properties>")


def para(text):
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


# ---------------------------------------------------------------------------
# docx core (S-002, S-003, S-004, S-008, G-022, G-027)
# ---------------------------------------------------------------------------
def test_docx_core():
    print("\n== docx core ==")
    field = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText>ADDIN ZOTERO_ITEM {"citationID":"abc"}</w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    end = '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    rep = fmt.zotero_field_report(field + '<w:r><w:t/></w:r><w:r><w:t>Smith</w:t></w:r>' + end)
    check("S-002 a self-closing w:t is empty, not an opening tag",
          rep["fields"][0]["visible_text"] == "Smith",
          rep["fields"][0]["visible_text"])
    rep = fmt.zotero_field_report(
        field + '<w:r><w:t>Smith</w:t><w:br/><w:t>2020</w:t></w:r>' + end)
    check("S-003 a field-result line break is a newline, matching text_of",
          rep["fields"][0]["visible_text"] == "Smith\n2020",
          repr(rep["fields"][0]["visible_text"]))
    tmp = scratch("fixbugs1027c_even_")
    for val, want in (('<w:evenAndOddHeaders w:val="0"/>', False),
                      ('<w:evenAndOddHeaders w:val="false"/>', False),
                      ('<w:evenAndOddHeaders/>', True)):
        p = tmp / f"{abs(hash(val))}.docx"
        make_docx(p, "", settings=val)
        check(f"S-004 evenAndOddHeaders {val!r} is {want}",
              fmt._template_uses_even_odd(p) is want)
    cases = {
        "The Lancet published a study": [],
        "EMBO today announced": [],
        "Cell's membrane": [],
        "Lancet Oncology 2020": ["Lancet Oncology"],
        "Lancet Oncology published a study": ["Lancet Oncology"],
        "The EMBO Journal published a paper": ["EMBO Journal"],
        "EMBO J. 2020": ["EMBO J"],
        "Cell Reports": ["Cell Reports"],
    }
    for text, want in cases.items():
        check(f"S-008 journal_matches({text!r})", fmt.journal_matches(text) == want,
              str(fmt.journal_matches(text)))
    alt = ('<w:p><w:r><mc:AlternateContent xmlns:mc="' + MC_NS + '">'
           '<mc:Choice Requires="wps"><w:t>Hello</w:t></mc:Choice>'
           '<mc:Fallback><w:t>Hello</w:t></mc:Fallback>'
           '</mc:AlternateContent></w:r></w:p>')
    check("G-022 text_of reads one AlternateContent branch", fmt.text_of(alt) == "Hello",
          fmt.text_of(alt))
    p = tmp / "alt.docx"
    make_docx(p, alt)
    check("G-022 the pipeline paragraph walk reads one branch too",
          pp._docx_paragraphs(p) == ["Hello"], str(pp._docx_paragraphs(p)))
    textbox = ('<w:p><w:r><mc:AlternateContent xmlns:mc="' + MC_NS + '">'
               '<mc:Choice Requires="wps"><w:drawing><wps:txbx xmlns:wps='
               '"http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
               '<w:txbxContent><w:p><w:r><w:t>ChoiceText</w:t></w:r></w:p>'
               '</w:txbxContent></wps:txbx></w:drawing></mc:Choice>'
               '<mc:Fallback><w:pict><v:textbox xmlns:v='
               '"urn:schemas-microsoft-com:vml"><w:txbxContent>'
               '<w:p><w:r><w:t>FallbackText</w:t></w:r></w:p></w:txbxContent>'
               '</v:textbox></w:pict></mc:Fallback></mc:AlternateContent>'
               '</w:r></w:p>')
    p = tmp / "textbox.docx"
    make_docx(p, textbox)
    got = pp._docx_paragraphs(p) or []
    check("R02 a text-box AlternateContent yields the Choice text once",
          sum("ChoiceText" in t for t in got) == 1
          and "FallbackText" not in "".join(got), str(got))
    ppr = ('<w:pPr><w:pPrChange><w:pPr><w:ind w:firstLine="720"/></w:pPr>'
           "</w:pPrChange></w:pPr>")
    p = f"<w:p>{ppr}<w:r><w:t>x</w:t></w:r></w:p>"
    check("G-027 elem/indent ignore pPrChange history",
          fmt.paragraph_first_line_indent(p) == 0 and fmt.elem(ppr, "ind") is None)
    rpr = '<w:rPr><w:rPrChange><w:rPr><w:sz w:val="8"/></w:rPr></w:rPrChange></w:rPr>'
    check("G-027 elem ignores rPrChange history", fmt.elem(rpr, "sz") is None,
          str(fmt.elem(rpr, "sz")))


# ---------------------------------------------------------------------------
# text rules (S-001, S-009..S-018, S-020..S-023, G-041)
# ---------------------------------------------------------------------------
def test_text_rules():
    print("\n== text rules ==")
    text = "(A (B) and C)"
    groups = fmt.balanced_paren_groups(text)
    check("S-001 balanced_paren_groups returns an exclusive end",
          text[groups[-1][0]:groups[-1][1]] == text, str(groups))
    check("S-001 nested-parenthesis evidence keeps the closing paren",
          fmt.nested_parentheses_rows([text])[0]["evidence"] == text)
    check("S-009 a compound heading enters body mode",
          fmt.section_kinds(["Results and discussion", "We did X.", "More."]) ==
          ["heading", "body", "body"], str(fmt.section_kinds(
              ["Results and discussion", "We did X.", "More."])))
    kw = fmt.section_kinds(["Keywords are important", "We did X."])
    check("S-010 a 'Keywords are ...' sentence does not switch to body",
          kw[1] == "front", str(kw))
    kinds = fmt.section_kinds(["Abstract", "Abs text.", "Introduction", "Body.",
                               "Summary", "More body."])
    check("S-010 a later Summary does not reset body to abstract",
          kinds[4:] == ["body", "body"], str(kinds))
    check("S-012 copy-number variation is not counted in the CN family",
          fmt.concept_family_rows(["We measured copy-number variation."]) == [])
    check("S-013 'three and five' is two counts, not 8",
          [r["number"] for r in fmt.word_number_rows(
              "We enrolled three and five patients.")] == ["3", "5"])
    check("S-013 'one hundred and twenty five' still parses as 125",
          fmt._word_number_value("one hundred and twenty five") == 125)
    check("S-014 '1,' is not a separated quantity",
          fmt.number_format_rows(["We saw 1, 2 and 12000 samples."]) == [])
    check("S-014 NUMBER_RE does not swallow a trailing comma",
          [m.group(1) for m in fmt.NUMBER_RE.finditer("1, 2")] == ["1", "2"],
          str([m.group(1) for m in fmt.NUMBER_RE.finditer("1, 2")]))
    check("S-014 '2,019' is not a separated quantity",
          fmt.number_format_rows(["We saw 2,019 and 12000 samples."]) == [])
    check("S-014 a real decimal with a separator is still a case",
          bool(fmt.number_format_rows(["We saw 1,234.5 and 12000 cells."])))
    cands = fmt._num_candidates(4e-7)
    check("S-015 the exact tiny spelling is a candidate",
          "0.0000004" in cands and "4e-07" in cands, str(sorted(cands)))
    check("S-015 a zero-only rounding no longer proves 0.00",
          "0.00" not in cands, str(sorted(cands)))
    check("S-015 the documented 1.773 -> 1.77 rounding stays",
          "1.77" in fmt._num_candidates(1.773))
    check("S-015 the typographic minus is a candidate",
          "\u221280" in fmt._num_candidates(-80))
    rows = fmt.number_ledger(["We counted 12\u00a0000 cells."])
    seed = fmt.hierarchy_seed_rows(
        rows, [("t.tsv", "name\tcells\na\t12000\nb\t12001\nc\t11999\n")])
    check("S-016 the seed normalizes a thin-space thousands separator",
          bool(seed) and "matches a cell" in seed[0]["seed check"],
          str(seed[:1]))
    check("S-017 _fmt_number keeps a tiny nonzero value",
          fmt._fmt_number(4e-7) != "0" and fmt._fmt_number(-4e-7) != "-0",
          f"{fmt._fmt_number(4e-7)} / {fmt._fmt_number(-4e-7)}")
    check("S-018 a title year in parentheses does not beat the journal year",
          fmt._entry_year("Berg JK. A reply (2014). Nature 2016; 11: 1.") == "2016",
          fmt._entry_year("Berg JK. A reply (2014). Nature 2016; 11: 1."))
    sici = ("10.1002/(SICI)1097-0258(19980215)19:8<1001::AID-SIM743>"
            "3.0.CO;2-5")
    check("S-020 a SICI DOI is kept whole",
          fmt.DOI_RE.findall("doi:" + sici) == [sici], str(fmt.DOI_RE.findall("doi:" + sici)))
    ph = [{"class": "searchable", "kind": "doi", "payload": "persistent identifier",
           "document": "cover.txt", "document_paragraph": 2}]
    docs = [("cover.txt", ["Manuscript title: CopyNumBench study",
                           "Code https://github.com/a/b and 10.1038/paper.4060"])]
    plan = fmt.placeholder_lookup_plan(ph, docs)
    check("S-021 a doi placeholder uses doi/repository/title kinds per query",
          {p["kind"] for p in plan} == {"doi", "repository", "title"}, str(plan))
    short = fmt.lookup_kind("archive", "data", timeout=1)
    check("S-022 an archive query with no distinctive token is an error, not found",
          short["verdict"] == "error" and short["hits"] == [], str(short))
    masked = fmt.spelling_nonprose_mask("doi.org/10.1000/colour-map")
    check("S-023 a scheme-less doi.org path is masked", masked.strip() == "", repr(masked))
    idx = fmt.table_value_index(
        [("t.tsv", "name\tvalue\n" + "".join(f"{c}\t{v}\n" for c, v in [
            ("a", 11), ("b", 12), ("c", 13), ("d", ""), ("e", ""), ("f", ""),
            ("g", ""), ("h", ""), ("i", ""), ("j", "")]))])
    check("G-041 the data-row count is every row, not the numeric cells",
          idx.get("10") == "number of data rows in t.tsv", str(idx.get("10")))


# ---------------------------------------------------------------------------
# report / layout (D-053, G-030, G-031, G-032, G-033)
# ---------------------------------------------------------------------------
def test_report_layout():
    print("\n== report / layout ==")
    tmp = scratch("fixbugs1027c_rep_")
    bad = tmp / "bad.docx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", b'<w:document>\xff\xfe</w:document>')
    try:
        rep = fmt.repair_layout_package(bad, tmp / "out.docx")
        check("D-053 a non-UTF-8 document.xml returns an error report",
              "error" in rep and "unreadable DOCX" in rep["error"], str(rep.get("error")))
    except UnicodeDecodeError as e:
        check("D-053 a non-UTF-8 document.xml returns an error report", False, repr(e))
    # The bounded runner (F38) is the seam now: patch IT, not the subprocess
    # module the implementation used to call. The check is about the
    # blank-page/image gap logic, not about how the child is spawned.
    orig = (fmt.shutil.which, fmt._run_text_tool, fmt._pdf_image_pages)
    try:
        fmt.shutil.which = lambda n: "/usr/bin/pdftotext" if n == "pdftotext" else None
        fmt._run_text_tool = lambda argv, timeout: (0, "\f\f", "")
        fmt._pdf_image_pages = lambda p: None
        rep = fmt.check_pdf(Path("figure-only.pdf"), dict(fmt.POLICY_DEFAULTS))
        high = [r for r in rep["rows"] if r["rule"] == "FMT-S2" and r["severity"] == "high"]
        gap = [r for r in rep["rows"] if r["rule"] == "FMT-S2" and r["severity"] == "low"]
        check("G-030 missing pdfimages files a gap, not false blank pages",
              not high and bool(gap), str(rep["rows"]))
    finally:
        fmt.shutil.which, fmt._run_text_tool, fmt._pdf_image_pages = orig
    letter = tmp / "Letter.docx"
    make_docx(letter, para("Dear Editor"), app_pages=3)
    rep = fmt.analyse_package(letter, dict(fmt.POLICY_DEFAULTS, page_budget={
        "front_page_keywords": False, "cover_letter_max_pages": 2,
        "source": "the test's venue rule"}))
    check("G-031 a letter named Letter.docx enters the two-page budget",
          any(r["rule"] == "FMT-T8h" for r in rep["rows"]),
          str([r["rule"] for r in rep["rows"]]))
    cw = load("fixbugs1027c_cw", "paper-skills/paper-review/scripts/count_words.py")
    for label, rx in (("pipeline", pp.TABLE_CAPTION_START_RE),
                      ("formatter", fmt.TABLE_CAPTION_RE),
                      ("skill", cw.TABLE_CAPTION)):
        check(f"G-032 {label} recognizes 'Supp. Table 1. Title'",
              bool(rx.match("Supp. Table 1. Title")))
    check("G-033 the skill's suspect-caption pattern accepts 'Supp. Fig. 3'",
          bool(cw.CAPTION_SUSPECT.match("Supp. Fig. 3")))


# ---------------------------------------------------------------------------
# skill scripts (D-075, D-084, G-001, G-035, G-038)
# ---------------------------------------------------------------------------
def test_skills():
    print("\n== skill scripts ==")
    en = load("fixbugs1027c_en", "paper-skills/paper-review/scripts/extract_numbers.py")
    ec = load("fixbugs1027c_ec", "paper-skills/paper-review/scripts/extract_citations.py")
    eo = load("fixbugs1027c_eo", "paper-skills/paper-review/scripts/extract_occurrences.py")
    rt = load("fixbugs1027c_rt", "paper-skills/paper-revise/scripts/revision_token.py")
    check("D-075 signed CI spellings share one metric key",
          en._metric_key("CI", "-0.5--0.1") == en._metric_key("CI", "-0.50--0.10"),
          f"{en._metric_key('CI', '-0.5--0.1')} vs {en._metric_key('CI', '-0.50--0.10')}")
    pct = [p for label, p in en.LABEL_PATTERNS if label == "percentage"][0]
    check("D-084 1000% is inventoried", pct.findall("1000%") == ["1000"],
          str(pct.findall("1000%")))
    check("G-035 an em-dash citation range is a citation",
          ec.NUM_CIT_RE.findall("see [1\u20143]") == ["1\u20143"],
          str(ec.NUM_CIT_RE.findall("see [1\u20143]")))
    pat = eo.variant_pattern("3.10e2", "value")
    check("G-038 the unpadded e+ spelling matches",
          bool(pat.search("3.10e+2")), pat.pattern[:200])
    check("R04 the unsigned short exponent spelling still matches",
          bool(pat.search("3.1e2")) and bool(pat.search("3.1E2"))
          and not pat.search("3.1e20"), pat.pattern[:200])
    # G-001: the skill and the pipeline walks agree on the symlink policy.
    tmp = scratch("fixbugs1027c_tok_")
    plain = tmp / "plain"
    plain.mkdir()
    (plain / "paper.txt").write_text("body\n", encoding="utf-8")
    a, b = pp.revision_token_for_dir(plain), rt.revision_token(plain)
    check("G-001 plain package tokens agree", a["token"] == b["token"] and a["token"],
          f"{a['token']} vs {b['token']}")
    nested = tmp / "nested"
    nested.mkdir()
    (nested / "paper.txt").write_text("body\n", encoding="utf-8")
    outside = tmp / "outside"
    outside.mkdir()
    (outside / "secret-4f3a9c1.txt").write_text("x\n", encoding="utf-8")
    os.symlink(str(outside), nested / "sub")
    a, b = pp.revision_token_for_dir(nested), rt.revision_token(nested)
    check("G-001 a nested directory link is skipped by BOTH walks",
          a["token"] == b["token"] and not a["hex_tokens"],
          f"{a['hex_tokens']} vs {b['hex_tokens']}")


# ---------------------------------------------------------------------------
# pipeline rules (D-007, D-017, D-052, G-003..G-009, G-012, G-015, G-021, G-043)
# ---------------------------------------------------------------------------
def test_pipeline_rules():
    print("\n== pipeline rules ==")
    status_src = (WS / "paper_pipeline_parts/p12_conflicts_decide.py").read_text("utf-8")
    check("D-007 the floor=0 help says empty prefix",
          "0 = empty prefix (no census cells lead)" in status_src
          and "0 = one cell only" not in status_src)
    tmp = scratch("fixbugs1027c_fp_")
    (tmp / "a.txt").write_text("body\n", encoding="utf-8")
    (tmp / "raw_data.disabled").mkdir()
    (tmp / "raw_data.disabled" / "x.txt").write_text("inert\n", encoding="utf-8")
    base = scratch("fixbugs1027c_fp2_")
    (base / "a.txt").write_text("body\n", encoding="utf-8")
    check("D-017 a disabled evidence area is inert to the fingerprint",
          pp.corpus_content_set_fingerprint([(tmp, "", set())])
          == pp.corpus_content_set_fingerprint([(base, "", set())])
          and pp.manifest_for_sources([(tmp, "", set())])["count"] == 1)
    # D-052: a table after an inserted paragraph stays after it.
    d = scratch("fixbugs1027c_red_")
    b, r, o = d / "b.docx", d / "r.docx", d / "o.docx"
    table = ('<w:tbl><w:tr><w:tc><w:p><w:r><w:t>T1</w:t></w:r></w:p>'
             "</w:tc></w:tr></w:tbl>")
    make_docx(b, para("First") + table + para("Third"))
    make_docx(r, para("First") + para("Inserted") + table + para("Third"))
    pp.builtin_tracked_changes(b, r, o)
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(o) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(f"{{{W_NS}}}body")
    tags = [c.tag.split("}")[1] for c in list(body)]
    check("D-052 the table lands after the inserted paragraph",
          tags == ["p", "p", "tbl", "p"], str(tags))
    # R01: a table after a DELETED base paragraph must stay after the deletion,
    # so rejecting all changes still reproduces the base body order.
    make_docx(b, para("First") + para("Second") + table)
    make_docx(r, para("First") + table)
    pp.builtin_tracked_changes(b, r, o)
    with zipfile.ZipFile(o) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(f"{{{W_NS}}}body")
    tags = [c.tag.split("}")[1] for c in list(body)]
    check("R01 a table after a deleted paragraph keeps the base order",
          tags == ["p", "p", "tbl"], str(tags))
    used = [f"X-{i}" for i in range(901, 1000)]
    try:
        pp.cold_start_findings_for_merge(used, [{"id": "X-950"}])
        check("G-003 an exhausted probe block refuses to emit X-1000", False)
    except RuntimeError as e:
        check("G-003 an exhausted probe block refuses to emit X-1000",
              "X-901..X-999" in str(e), str(e))
    new = {"defect_prefix_census": [0, 5], "defect_prefix_total": 5}
    old = {"defect_prefix_census": [1, 0], "defect_prefix_total": 1}
    check("G-004 the no-progress key is the ordered census, not the total",
          pp.no_progress_measure(new) < pp.no_progress_measure(old),
          f"{pp.no_progress_measure(new)} vs {pp.no_progress_measure(old)}")
    # G-006: the setter refuses to re-open the probe in a scoped mode.
    try:
        import journal_revision_modes_lib as jr
        jtmp = scratch("fixbugs1027c_scoped_")
        src = jr.build_source(jtmp)
        root = jtmp / "root"
        setup = jr.run_cli("setup", "--source", str(src), "--root", str(root),
                           "--revision-mode", "major", "--journal", "iScience")
        r = jr.run_cli("set-cold-start-review", "on", "--force", "--root", str(root))
        check("G-006 set-cold-start-review on is refused in a scoped mode",
              setup.returncode == 0 and r.returncode != 0
              and "concern-scoped" in (r.stdout + r.stderr),
              f"setup={setup.returncode} rc={r.returncode} out={(r.stdout + r.stderr)[-200:]}")
    except Exception as e:  # noqa: BLE001
        check("G-006 set-cold-start-review on is refused in a scoped mode", False, repr(e))
    p05 = (WS / "paper_pipeline_parts/p05_state_corpus.py").read_text("utf-8")
    check("G-007 rewrite concerns are staged for every feedback mode",
          "if journal_has_feedback(ctx) and not journal_is_scoped(ctx):" in p05
          and 'ensure_copy(fb / "concerns", sb / "concerns")' in p05)
    p07 = (WS / "paper_pipeline_parts/p07_stage_quality_journal.py").read_text("utf-8")
    check("G-008 an empty response letter is an error",
          "is EMPTY: the response to" in p07)
    check("G-009 a repeated concern id is an error",
          "response letter mentions concern {cid!r} {mentions}" in p07
          and pp._finding_id_occurrences("R1-1", "## R1-1 x\n## R1-1 y") == 2)
    check("G-012 coverage rows are validated",
          pp.concern_coverage_problems({"coverage": []}, False)
          and pp.concern_coverage_problems(
              {"coverage": [{"check": "scope", "disposition": "outside is a gap"}]}, False) == []
          and pp.concern_coverage_problems(
              {"coverage": [{"check": "scope", "disposition": "gap"}]}, True))
    check("R05 arbitrary coverage rows do not satisfy the named-gap gate",
          pp.concern_coverage_problems({"coverage": [
              {"check": "scope", "disposition": "x"},
              {"check": "other", "disposition": "y"}]}, True)
          and pp.concern_coverage_problems({"coverage": [
              {"check": "anything", "disposition": "not a gap"}]}, False)
          and pp.concern_coverage_problems({"coverage": [
              {"check": "scope", "disposition": "not a gap"}]}, False)
          and pp.concern_coverage_problems({"coverage": [
              {"check": "scope", "disposition": "every class outside is a named gap"},
              {"check": "LLM-pre-filter",
               "disposition": "its dropped classes are a named gap"}]}, True) == [])
    check("G-015 an explicit default_cap 0 is preserved",
          pp._clean_captions({"published_limit": 250, "default_cap": 0}, "x", [])
          ["default_cap"] == 0
          and pp._clean_captions({"published_limit": 250}, "x", [])["default_cap"] == 250)
    p01 = (WS / "paper_pipeline_parts/p01_venues.py").read_text("utf-8")
    check("G-021 the norm prompt no longer prescribes 'lead contact'",
          '"<Name>, lead contact"' not in p01
          and "corresponding author's name (when the source marks a lead contact" in p01)
    check("G-021 the formatter still flags the leftover phrase",
          bool(fmt.leftover_phrase_rows(["* Correspondence: Zhen Xie, lead contact"],
                                        ["lead contact"])))
    check("G-043 a sign-only contradiction is not collapsed",
          pp._conflict_numbers("-12") != pp._conflict_numbers("12")
          and pp._conflict_numbers("-12") == {-12},
          f"{pp._conflict_numbers('-12')} vs {pp._conflict_numbers('12')}")


def main() -> int:
    try:
        test_docx_core()
        test_text_rules()
        test_report_layout()
        test_skills()
        test_pipeline_rules()
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: " + "; ".join(FAILS))
        return 1
    print("OK all fix-bugs 2026-10-27 20:20 checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression checks for the 2026-11-15 (08:17) fix-bugs run, wave 1.

Each check names the verified finding it pins. Hermetic: tempfile only, no
network, no model/Word call.

Run: PYTHONDONTWRITEBYTECODE=1 python3 .paper_test/test_fix_bugs_20261115_run2_wave1.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FAILS = []

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f'xmlns:w="{W_NS}"'


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1115run2_pp", "paper_pipeline.py")
fmt = load("fb1115run2_fmt", "paper_docx_format.py")
extract_numbers = load("fb1115run2_nums",
                       "paper-skills/paper-review/scripts/extract_numbers.py")


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def document(body: str) -> str:
    return f'<w:document {W}><w:body>{body}</w:body></w:document>'


def table(text: str) -> str:
    return ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="100"/></w:tblGrid>'
            f'<w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc></w:tr>'
            '</w:tbl>')


def test_f002_break_before_table():
    """F002: a break-only body paragraph before a table keeps the table on the
    new page (pageBreakBefore lands on the table's first paragraph, not after it)."""
    policy = dict(fmt.POLICY_DEFAULTS)
    break_only = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    body = ('<w:p><w:r><w:t>Intro.</w:t></w:r></w:p>' + break_only
            + table("Cell text.")
            + '<w:p><w:r><w:t>After.</w:t></w:r></w:p>')
    fixed, _changes, _meta = fmt.fix_document(document(body), {}, policy)
    root = ET.fromstring(fixed)
    b = root.find(f"{{{W_NS}}}body")
    tags = [c.tag.split("}")[-1] for c in b]
    check("F002 the table is the block right after the intro", tags == ["p", "tbl", "p"], str(tags))
    cell_p = b[1].find(f"{{{W_NS}}}tr/{{{W_NS}}}tc/{{{W_NS}}}p")
    after_p = b[2]
    check("F002 the table's first paragraph carries pageBreakBefore",
          cell_p is not None and cell_p.find(f"{{{W_NS}}}pPr/{{{W_NS}}}pageBreakBefore") is not None)
    check("F002 the paragraph AFTER the table does not carry the break",
          after_p.find(f"{{{W_NS}}}pPr/{{{W_NS}}}pageBreakBefore") is None)


def test_f016_bold_val_zero():
    """F016: an explicit <w:b w:val="0"/> is set ON in place, not duplicated."""
    para = (f'<w:p {W}><w:r><w:rPr><w:b w:val="0"/><w:i/></w:rPr>'
            '<w:t>* Correspondence: Alice</w:t></w:r></w:p>')
    out = fmt._bold_label_runs(para)
    rpr = out[out.find("<w:rPr>"):out.find("</w:rPr>") + len("</w:rPr>")]
    check("F016 exactly one live w:b remains", rpr.count("<w:b") == 1, rpr)
    check("F016 the existing b is now on (no val=0)", "<w:b/>" in rpr, rpr)


def test_f037_page_field_static_digits():
    """F037: a duplicate PAGE paragraph with static digits is NOT deleted;
    a field-only duplicate still is."""
    footer = ('<w:ftr ' + W + '>'
              '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText> PAGE </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              '<w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
              '<w:p><w:r><w:t>2 2024</w:t></w:r>'
              '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText> PAGE </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              '<w:r><w:t>2</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
              '</w:ftr>')
    check("F037 static digits beside the field are kept", fmt.page_field_fixes(footer) == [])
    field_only = footer.replace("<w:r><w:t>2 2024</w:t></w:r>", "")
    check("F037 a field-only duplicate is still removed", len(fmt.page_field_fixes(field_only)) == 1)


def test_f051_ppr_order():
    """F051: template pPr children land in CT_PPrBase order, without duplicates."""
    tpl = ('<w:pPr><w:pStyle w:val="X"/><w:keepNext/><w:keepLines/>'
           '<w:spacing w:before="240"/><w:ind w:firstLine="0"/><w:jc w:val="both"/>'
           '<w:rPr><w:b/></w:rPr></w:pPr>')
    target = (f'<w:p {W}><w:pPr><w:pStyle w:val="Y"/><w:keepNext/></w:pPr>'
              '<w:r><w:t>x</w:t></w:r></w:p>')
    out = fmt._apply_ppr_extra(target, fmt._ppr_extra(tpl))
    ppr = out[out.find("<w:pPr>"):out.find("</w:pPr>") + len("</w:pPr>")]
    order = [m for m in ("keepNext", "keepLines", "spacing", "ind", "jc", "rPr")
             if f"<w:{m}" in ppr]
    check("F051 children are in CT_PPrBase order", order == ["keepNext", "keepLines", "spacing", "ind", "jc", "rPr"], str(order))
    check("F051 keepNext is not duplicated", ppr.count("<w:keepNext") == 1, ppr)
    check("F051 keepLines is not duplicated", ppr.count("<w:keepLines") == 1, ppr)


def test_f157_header_part_regex():
    """F157: a descriptively named header/footer part is in the Zotero inventory."""
    for name in ("word/header_venue_default.xml", "word/footer_journal.xml",
                 "word/header1.xml", "word/header.xml", "word/footer.xml",
                 "word/comments.xml"):
        check("F157 inventory recognises " + name,
              bool(fmt.ZOTERO_FIELD_AUX_PARTS_RE.match(name)))
    check("F157 a styles part is not a header", not fmt.ZOTERO_FIELD_AUX_PARTS_RE.match("word/headerStyles.xml"))


def test_f210_bib_fallback():
    """F210: the .bib logging fallback is one balanced @comment entry, not % lines."""
    d = Path(tempfile.mkdtemp())
    base = d / "a.bib"
    cand = d / "b.bib"
    base.write_text("@article{a, title={A}}\n", encoding="utf-8")
    cand.write_text("@article{a, title={B}}\n", encoding="utf-8")
    res = pp.write_text_logging_fallback(base, cand, d / "out.logging-a1.bib", "a1", "no tool")
    text = (d / "out.logging-a1.bib").read_text(encoding="utf-8")
    check("F210 the fallback was written", res.get("ok") is True)
    check("F210 the bib fallback is one @comment entry", text.startswith("@comment{"))
    check("F210 the comment braces stay balanced", text.count("{") == 1 and text.count("}") == 1)


def test_f066_auto_promoted_label():
    check("F066 the mandated label survives a blocker",
          pp.certification_label({"auto_promoted": [1], "blockers": ["x"]})
          == "AUTO-PROMOTED — PROVISIONAL (NOT JUDGED)")


def test_f091_extglob_reversed_range():
    check("F091 a reversed class is rejected, not a crash", pp._extglob_to_regex("[z-a]*") is None)


def test_f095_handoff_empty_path():
    d = Path(tempfile.mkdtemp())
    (d / "README-AUTHOR-TO-COMPLETE.md").write_text("- item\n", encoding="utf-8")
    old = Path.cwd()
    try:
        import os
        os.chdir(d)
        check("F095 an absent final_clean.path does not scan the CWD",
              pp._handoff_readme_items({}) == {})
        check("F095 a skipped publication does not scan the CWD",
              pp._handoff_readme_items({"skipped": "no winner"}) == {})
    finally:
        os.chdir(old)


def test_f074_resolved_item_removed():
    """F074: a publisher-generated row disappears on the next publish once resolved."""
    d = Path(tempfile.mkdtemp())
    (d / "README-AUTHOR-TO-COMPLETE.md").write_text(
        "# Author to complete\n\n"
        "| TODO item ID | importance | author action | description |\n"
        "|---|---|---|---|\n"
        "| T-005 | major | MANUALLY DO/DO_NOT correct without LLMs-recommended corrections provided | author row |\n",
        encoding="utf-8")
    oi = {"items": [{"id": "F-1", "status": "fixed", "check": "M1", "severity": "major",
                     "location": "A.TXT", "evidence": "DOI 10.1/abc must be checked"}]}
    r1 = pp.write_published_handoff_readme(d, open_items=oi)
    first = (d / "README-AUTHOR-TO-COMPLETE.md").read_text(encoding="utf-8")
    check("F074 publish 1 appends one row", r1.get("items") == 1, str(r1))
    check("F074 publish 1 carries the item", "DOI 10.1/abc" in first)
    r2 = pp.write_published_handoff_readme(d, open_items={"items": []})
    second = (d / "README-AUTHOR-TO-COMPLETE.md").read_text(encoding="utf-8")
    check("F074 publish 2 reports no item", r2.get("items") == 0, str(r2))
    check("F074 the resolved row is gone", "DOI 10.1/abc" not in second, second)
    check("F074 the author's own row survives", "author row" in second)


def test_f077_zero_item_manual_steps():
    r = pp.package_readiness(
        {"certified": False,
         "open_items": {"manual_steps": "x/MANUAL_STEPS.md", "manual_steps_items": 0,
                        "items": [], "discarded": []}},
        residuals={}, author_to_complete="readme", lengths={})
    check("F077 a zero-item manual list is not a blocker",
          bool(r.get("submission_ready")) and not r.get("blocking_findings"), str(r))


def test_f104_f105_numbers():
    check("F104 '5 × 10−8' normalizes to 5e-08",
          extract_numbers._metric_key("p-value", "5 × 10−8") == "5e-08",
          extract_numbers._metric_key("p-value", "5 × 10−8"))
    check("F104 the caret spelling still normalizes to 5e-08",
          extract_numbers._metric_key("p-value", "5 × 10^-8") == "5e-08")
    got = [(m.group("low"), m.group("high"))
           for m in extract_numbers.RANGE_RE.finditer("−60 °C to −80 °C")]
    check("F105 a Unicode-minus ascending range is parsed", got == [("−60", "−80")], str(got))


def test_f109_f191_f196_markers():
    check("F109 a marker bullet containing pipes is still an item",
          pp._handoff_items_from_manual_steps(
              "- [AUTHOR TO COMPLETE: report the metric | value | unit]")
          == ["report the metric | value | unit"])
    check("F191 the token quoted in a rule sentence is not an item",
          pp._handoff_items_from_manual_steps(
              "The token [AUTHOR TO COMPLETE: software version] is forbidden under readme.")
          == [])
    for rule in (
            "The phrase '[AUTHOR TO COMPLETE: verify the grant]' marks an author action.",
            "The [AUTHOR TO COMPLETE: x] is forbidden."):
        got = pp._handoff_items_from_manual_steps(rule)
        check("F191 a rule sentence that mentions the token is not an item: "
              + rule[:22], got == [], str(got))
    rows = pp._readme_action_rows(
        "| T-001 | major | MANUALLY DO/DO_NOT correct without any LLMs-recommended corrections"
        " | a \\| b |\n")
    check("F196 an escaped pipe stays inside its cell",
          rows and "a | b" in rows[0] and "\\" not in rows[0], str(rows))


def test_f117_policy_flag():
    import types
    for value in (False, "false", "off", "no", "0"):
        ctx = types.SimpleNamespace(
            cfg={"format_policy": {"unlink_zotero_fields_at_publish": value}})
        check("F117 %r disables flattening" % (value,),
              pp.publication_format_policy(ctx, {})[1] is False)
    ctx = types.SimpleNamespace(
        cfg={"format_policy": {"unlink_zotero_fields_at_publish": True}})
    check("F117 True still enables flattening",
          pp.publication_format_policy(ctx, {})[1] is True)


def test_f116_f125_f131_venue_types():
    def rejected(profile):
        try:
            pp.normalize_venue_profile(profile, "t")
        except pp.VenueProfileError:
            return True
        return False

    check("F116 an empty image_dpi block is rejected",
          rejected({"id": "x", "image_dpi": {}}))
    check("F116 an empty figure_text block is rejected",
          rejected({"id": "x", "figure_text": {}}))
    check("F125 a bool sentence_words bar is rejected",
          rejected({"id": "x", "style_limits": {"sentence_words": {"body": True}}}))
    check("F125 a float paragraph_words cap is rejected",
          rejected({"id": "x", "style_limits": {"paragraph_words": 99.9}}))
    check("F131 a bool relaxation is rejected",
          rejected({"id": "x", "length_limits": {"abstract": {"base": 100, "relaxation": True}}}))
    check("F131 a bool min_dpi is rejected",
          rejected({"id": "x", "image_dpi": {"min_dpi": True, "source": "s"}}))


def test_f183_duplicate_role_key():
    check("F183 a hex token before -v2 is removed",
          pp._duplicate_role_key("mainText-abc1234-v2.docx") == "maintext")
    check("F183 a hex token before provenance is removed",
          pp._duplicate_role_key("mainText-9915d6e-FrontiersTemplate-zotero.docx")
          == "maintext")


def test_f130_pprchange_base_only():
    base = ET.fromstring(
        f'<w:p {W}><w:pPr><w:pStyle w:val="Heading1"/><w:rPr><w:rFonts w:ascii="Arial"/>'
        '</w:rPr></w:pPr><w:r><w:t>x</w:t></w:r></w:p>')
    rev = ET.fromstring(
        f'<w:p {W}><w:pPr><w:pStyle w:val="Heading2"/><w:rPr><w:rFonts w:ascii="Arial"/>'
        '</w:rPr></w:pPr><w:r><w:t>x</w:t></w:r></w:p>')
    out = pp._pPr_for(base, rev, [0], "2026-01-01T00:00:00Z")
    change = out.find(f"{{{W_NS}}}pPrChange")
    old_pr = change.find(f"{{{W_NS}}}pPr") if change is not None else None
    check("F130 a pPrChange is emitted", change is not None)
    check("F130 CT_PPrBase carries no rPr in the change record",
          old_pr is not None and old_pr.find(f"{{{W_NS}}}rPr") is None)


def test_f188_leading_whitespace():
    base = ET.fromstring(f'<w:p {W}><w:r><w:t xml:space="preserve">  Hello world</w:t></w:r></w:p>')
    rev = ET.fromstring(f'<w:p {W}><w:r><w:t>Hello world</w:t></w:r></w:p>')
    out = pp._replace_para(base, rev, [0], "2026-01-01T00:00:00Z")
    tags = {str(el.tag).rsplit("}", 1)[-1] for el in out.iter()}
    check("F188 the leading-space edit is marked",
          "del" in tags or "ins" in tags, str(tags))


def test_f201_toml_array():
    check("F201 a comma-less array is unreadable",
          pp._toml_array_values('["node" "server.js"]') is None)
    check("F201 a valid array still parses",
          pp._toml_array_values('["node", "server.js"]') == ["node", "server.js"])
    check("F201 a trailing comma still parses",
          pp._toml_array_values('["node", "server.js",]') == ["node", "server.js"])


def test_f169_deletion_audit_summary_table():
    d = Path(tempfile.mkdtemp())
    ra = d / "revision_audit"
    ra.mkdir()
    (ra / "DELETED_PARAGRAPHS.md").write_text(
        "# DELETED PARAGRAPHS\n\n"
        "| # | document | line | paragraph | disposition |\n"
        "|---|---|---|---|---|\n"
        "| 1 | m.docx | 3 | A removed paragraph | OK — content survives in Results |\n\n"
        "| # | paragraph | note |\n"
        "|---|---|---|\n"
        "| 1 | Rows audited | 3 |\n",
        encoding="utf-8")
    problems = pp.deletion_audit_problems(d, expected_rows=1)
    check("F169 an appended summary table does not fail the audit", problems == [], str(problems))


def test_f017_paragraph_mark():
    """F017: a whole-paragraph insert/delete marks the PARAGRAPH MARK too."""
    for tag in ("del", "ins"):
        para = ET.fromstring(f'<w:p {W}><w:r><w:t>text</w:t></w:r></w:p>')
        out = pp._wrap_para(para, tag, tag == "del", [0], "2026-01-01T00:00:00Z")
        mark = out.find(f"{{{W_NS}}}pPr/{{{W_NS}}}rPr/{{{W_NS}}}{tag}")
        check(f"F017 the {tag} paragraph carries a paragraph-mark {tag}", mark is not None)


def test_f107_manifests_equal_gaps():
    check("F107 different unreadable subtrees are not equal",
          not pp.manifests_equal(
              {"files": {"a": "1"}, "unreadable_dirs": ["hidden"]},
              {"files": {"a": "1"}}))
    check("F107 the same gap still compares equal",
          pp.manifests_equal(
              {"files": {"a": "1"}, "unreadable_dirs": ["hidden"]},
              {"files": {"a": "1"}, "unreadable_dirs": ["hidden"]}))


def test_f127_f149_declaration():
    d = Path(tempfile.mkdtemp())
    (d / "README.md").write_text(
        "The following will be submitted to the venue:\n\n```\nms-*.docx\n```\n",
        encoding="utf-8")
    for rel in ("ms-main.docx", "other.docx", "drafts/ms-old.docx"):
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    got = pp.declared_submission_set(d)
    check("F127 a fenced bare glob is parsed", got.get("patterns") == ["ms-*.docx"],
          str(got))
    check("F149 a basename match in another directory is not submitted",
          got.get("files") == ["ms-main.docx"], str(got))


def test_f162_judge_view_digest_symlink():
    d = Path(tempfile.mkdtemp())
    view = d / "view"
    view.mkdir()
    (view / "a.md").write_text("a", encoding="utf-8")
    before = pp.judge_view_digest(view)
    (view / "planted.md").symlink_to(view / "a.md")
    after = pp.judge_view_digest(view)
    check("F162 a planted symlink changes the view digest", before != after,
          f"{before} -> {after}")
    check("F162 the planted symlink is named as a sentinel",
          any(dig == "<symlink>" for _rel, dig in after), str(after))


def test_f050_f121_main_role_only():
    d = Path(tempfile.mkdtemp())
    (d / "main.md").write_text("# Title\n\n"
                               "We review funding policies in related work.\n",
                               encoding="utf-8")
    (d / "supplement.tex").write_text(
        "\\documentclass{frontiers}\n\\section{Results}\n"
        "\\section{Data availability}\n\\section{Funding}\n", encoding="utf-8")
    req = {"mandatory_sections": ["Results"], "statements": [{"label": "Funding"}],
           "documentclass": "frontiers"}
    got = pp.scan_template_conformance([(d, "", ())], req)
    check("F050 a supplement does not satisfy the main mandate",
          "Results" in (got.get("missing_sections") or []), str(got))
    check("F121 a body mention does not satisfy a statement",
          "Funding" in (got.get("missing_statements") or []), str(got))
    check("F050 a supplement's documentclass does not satisfy the main class",
          got.get("class_ok") is False, str(got.get("found")))

    # R04/F121: a statement-block LEAD paragraph (not only a heading) is a
    # required statement; a supplement's lead still may not satisfy the main
    # manuscript.
    lead = Path(tempfile.mkdtemp())
    (lead / "main.md").write_text(
        "# Title\n\n**Funding.** This work was supported by grant 123.\n\n"
        "# Results\n\ntext\n", encoding="utf-8")
    req = {"mandatory_sections": ["Results"],
           "statements": [{"label": "Funding"}]}
    got = pp.scan_template_conformance([(lead, "", ())], req)
    check("F121 a statement-block lead paragraph satisfies the statement",
          not (got.get("missing_statements") or []), str(got.get("missing_statements")))
    (lead / "main.md").write_text(
        "# Title\n\n**Acknowledgements.** We thank the funders.\n", encoding="utf-8")
    got = pp.scan_template_conformance(
        [(lead, "", ())], {"statements": [{"label": "Acknowledgements"}]})
    check("F121 a prefix-pattern statement lead is recognised",
          not (got.get("missing_statements") or []),
          str(got.get("missing_statements")))
    (lead / "main.md").write_text(
        "# Title\n\n# Results\n\ntext\n", encoding="utf-8")
    (lead / "supplement.md").write_text(
        "# Supplement\n\n**Funding.** Supplement only.\n", encoding="utf-8")
    got = pp.scan_template_conformance([(lead, "", ())], req)
    check("F050 a supplement's statement lead does not satisfy the main mandate",
          "Funding" in (got.get("missing_statements") or []), str(got.get("missing_statements")))


def main() -> int:
    test_f002_break_before_table()
    test_f016_bold_val_zero()
    test_f037_page_field_static_digits()
    test_f051_ppr_order()
    test_f157_header_part_regex()
    test_f210_bib_fallback()
    test_f066_auto_promoted_label()
    test_f091_extglob_reversed_range()
    test_f095_handoff_empty_path()
    test_f074_resolved_item_removed()
    test_f077_zero_item_manual_steps()
    test_f104_f105_numbers()
    test_f109_f191_f196_markers()
    test_f117_policy_flag()
    test_f116_f125_f131_venue_types()
    test_f183_duplicate_role_key()
    test_f130_pprchange_base_only()
    test_f188_leading_whitespace()
    test_f201_toml_array()
    test_f169_deletion_audit_summary_table()
    test_f017_paragraph_mark()
    test_f107_manifests_equal_gaps()
    test_f127_f149_declaration()
    test_f162_judge_view_digest_symlink()
    test_f050_f121_main_role_only()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return 1
    print("\nALL WAVE-1 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

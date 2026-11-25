#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression checks for the 2026-11-14 fix-bugs run, group B (F12-F19).

Each check names the verified finding it pins. Hermetic: tempfile only, no
network, no model/Word call.

Run: conda run -n paper-refine-test python .paper_test/test_fix_bugs_20261114_B.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("paper_fixbugs_B_fmt",
                                              str(WS / "paper_docx_format.py"))
fmt = importlib.util.module_from_spec(spec)
sys.modules["paper_fixbugs_B_fmt"] = fmt
spec.loader.exec_module(fmt)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f'xmlns:w="{W_NS}"'
FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_docx(path: Path, doc_xml: bytes, styles_xml: bytes = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc_xml)
        if styles_xml is not None:
            z.writestr("word/styles.xml", styles_xml)
    return path


def encoded(xml: str, enc: str) -> bytes:
    return xml.encode("utf-8") if enc == "utf-8" else b"\xff\xfe" + xml.encode("utf-16-le")


def test_f12_utf16_parts():
    """F12: UTF-16 OOXML parts stay visible to the Zotero/style readers."""
    item = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM '
            'CSL_CITATION {"citationID":"c1"}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>(Smith 2020)</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    title = ('<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr>'
             '<w:r><w:t>A UTF-16 title</w:t></w:r></w:p>')
    doc = (f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>'
           f'{title}{item}</w:body></w:document>')
    styles = (f'<?xml version="1.0" encoding="UTF-8"?><w:styles {W}>'
              '<w:style w:type="paragraph" w:styleId="Body"/></w:styles>')
    tmp = Path(tempfile.mkdtemp(prefix="fixbugsB_f12_"))
    for enc in ("utf-8", "utf-16"):
        p = make_docx(tmp / f"{enc}.docx", encoded(doc, enc), encoded(styles, enc))
        rep = fmt.zotero_report_for_docx(p)
        check(f"F12 {enc} Zotero inventory keeps the field",
              rep["counts"]["fields"] == 1 and not rep["errors"], str(rep["counts"]))
        check(f"F12 {enc} style ids are read",
              fmt.docx_style_ids(p) == ["Body"], str(fmt.docx_style_ids(p)))
        check(f"F12 {enc} front matter reads the title style",
              fmt.docx_front_matter_report(p).get("title_style") == "Title",
              str(fmt.docx_front_matter_report(p).get("title_style")))


def test_f13_tab_stops():
    """F13: a pPr tab-STOP definition is not paragraph text."""
    para = ('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/>'
            '<w:tab w:val="right" w:pos="9360"/></w:tabs></w:pPr>'
            '<w:r><w:t>Correspondence: a@b.org</w:t></w:r></w:p>')
    text = fmt.text_of(para)
    check("F13 tab-stop definitions add no newline",
          text == "Correspondence: a@b.org", repr(text))
    real_tab = '<w:p><w:r><w:t>a</w:t><w:tab/><w:t>b</w:t></w:r></w:p>'
    check("F13 a run-content tab is still a delimiter",
          fmt.text_of(real_tab) == "a\nb", repr(fmt.text_of(real_tab)))
    new_para, applied = fmt.rewrite_text_spans(para, [(0, 1, "X")])
    check("F13 the text fixer keeps the same offset model",
          applied and fmt.text_of(new_para) == "Xorrespondence: a@b.org",
          repr(fmt.text_of(new_para)))


def test_f14_alternate_content_runs():
    """F14: runs() reads the same AlternateContent branch as text_of()."""
    para = ('<w:p><w:r><w:t>See </w:t></w:r><mc:AlternateContent>'
            '<mc:Choice Requires="wps"><w:r><w:t>Nature Methods</w:t></w:r></mc:Choice>'
            '<mc:Fallback><w:r><w:t>Nature Methods</w:t></w:r></mc:Fallback>'
            '</mc:AlternateContent><w:r><w:t> and other leading journals.</w:t></w:r></w:p>')
    runs = fmt.runs(para)
    joined = "".join(fmt.text_of(r[2]) for r in runs)
    check("F14 the hidden Fallback run is not returned", len(runs) == 3, str(len(runs)))
    check("F14 run texts reproduce the paragraph text",
          joined == fmt.text_of(para), repr(joined))


def test_f15_nested_textbox_paragraph():
    """F15: a text-box paragraph is its own paragraph, not host text."""
    xml = ('<w:p><w:r><w:t>Outer text before </w:t></w:r><w:r><w:drawing>'
           '<wps:txbx><w:txbxContent><w:p><w:r><w:t>BOXED CAPTION</w:t></w:r></w:p>'
           '</w:txbxContent></wps:txbx></w:drawing></w:r>'
           '<w:r><w:t> outer after.</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>')
    paras = fmt.paragraphs(xml)
    texts = [fmt.text_of(p[2]) for p in paras]
    check("F15 the nested paragraph is emitted", len(paras) == 3, str(texts))
    check("F15 the host paragraph no longer carries the box text",
          "BOXED CAPTION" not in texts[0], repr(texts[0]))
    check("F15 the box paragraph carries its own text",
          texts[1] == "BOXED CAPTION", repr(texts[1]))
    host = paras[0][2]
    check("F15 run texts of the host agree with its text",
          "".join(fmt.text_of(r[2]) for r in fmt.runs(host)) == fmt.text_of(host),
          repr(fmt.text_of(host)))
    doc = (f'<w:document {W}><w:body>{xml}</w:body></w:document>')
    check("F15 a whole-document text walk still reads every top-level paragraph",
          "Outer text before " in fmt.text_of(doc)
          and "Second paragraph." in fmt.text_of(doc), repr(fmt.text_of(doc)))


def test_textbox_repairs_preserve_paragraph_ownership():
    def box(inner):
        return ('<w:pict><v:shape><v:textbox><w:txbxContent>'
                f'{inner}</w:txbxContent></v:textbox></v:shape></w:pict>')

    def document(body):
        return (f'<w:document {W} xmlns:v="urn:schemas-microsoft-com:vml">'
                f'<w:body>{body}</w:body></w:document>')

    policy = dict(fmt.POLICY_DEFAULTS)
    break_only = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    next_body = '<w:p><w:r><w:t>Next body paragraph.</w:t></w:r></w:p>'
    host = f'<w:p><w:r><w:t>Host text.</w:t>{box(break_only)}</w:r></w:p>'
    xml = document(host + next_body)
    fixed, _, _ = fmt.fix_document(xml, {}, policy)
    check("a text-box page break stays inside its own paragraph", fixed == xml)
    report = fmt.analyse_document(xml, {}, policy, "d.docx")
    check("no FMT-S1 repair is proposed for the box",
          not any(row["rule"] == "FMT-S1" for row in report["rows"]))

    inner = '<w:p><w:pPr/><w:r><w:t>Box text.</w:t></w:r></w:p>'
    drawing_only = f'<w:p><w:r>{box(inner)}</w:r></w:p>'
    fixed, _, _ = fmt.fix_document(document(break_only + drawing_only + next_body), {}, policy)
    body = ET.fromstring(fixed).find(f"{{{W_NS}}}body")
    check("a body break before a drawing-only host goes onto that host",
          len(body) == 2
          and body[0].find(f"{{{W_NS}}}pPr/{{{W_NS}}}pageBreakBefore") is not None
          and body[1].find(f"{{{W_NS}}}pPr/{{{W_NS}}}pageBreakBefore") is None
          and inner in fixed)

    target = ('<w:p><!-- keep <w:pPr/> --><?editor keep?>'
              '<w:pPr><w:keepNext/></w:pPr>'
              f'<w:r>{box(inner)}</w:r></w:p>')
    fixed, _, _ = fmt.fix_document(document(break_only + target + next_body), {}, policy)
    body = ET.fromstring(fixed).find(f"{{{W_NS}}}body")
    properties = body[0].findall(f"{{{W_NS}}}pPr")
    check("comments and processing instructions leave a single host property element",
          len(properties) == 1
          and properties[0].find(f"{{{W_NS}}}pageBreakBefore") is not None
          and properties[0].find(f"{{{W_NS}}}keepNext") is not None
          and '<!-- keep <w:pPr/> --><?editor keep?>' in fixed)

    for value in ('"0"', "'false'"):
        disabled_break = f'<w:pageBreakBefore w:val={value}/>'
        commented_break = f'<!-- {disabled_break} -->'
        target = (f'<w:p><w:pPr>{commented_break}{disabled_break}</w:pPr>'
                  f'<w:r>{box(inner)}</w:r></w:p>')
        fixed, _, _ = fmt.fix_document(document(break_only + target + next_body), {}, policy)
        body = ET.fromstring(fixed).find(f"{{{W_NS}}}body")
        breaks = body[0].findall(f"{{{W_NS}}}pPr/{{{W_NS}}}pageBreakBefore")
        check("a relocated body break enables the host's explicit false value",
              len(body) == 2 and len(breaks) == 1 and not breaks[0].attrib
              and commented_break in fixed and inner in fixed, value)

    inner_url = ('<w:p><w:r><w:rPr><w:i/></w:rPr>'
                 '<w:t>https://example.org/box</w:t></w:r></w:p>')
    outer_url = ('<w:p><w:r><w:rPr><w:color w:val="FF0000"/></w:rPr>'
                 f'<w:t>https://example.org/body</w:t>{box(inner_url)}</w:r></w:p>')
    fixed, _, _ = fmt.fix_document(document(outer_url), {}, policy)
    try:
        root = ET.fromstring(fixed)
    except ET.ParseError as exc:
        check("host and nested URL edits leave valid XML", False, str(exc))
        return
    check("host and nested URL styling is fixed without overlapping edits",
          "https://example.org/body" in fixed and "https://example.org/box" in fixed
          and root.find(f".//{{{W_NS}}}color") is None
          and root.find(f".//{{{W_NS}}}i") is None)

    leading_xml = '<!-- keep <w:rPr/> --><?editor keep?>'
    styled_url = (f'<w:p><w:r>{leading_xml}<w:rPr><w:i/></w:rPr>'
                  '<w:t>https://example.org/styled</w:t></w:r></w:p>')
    plain_url = '<w:p><w:r><w:t>https://example.org/plain</w:t></w:r></w:p>'
    xml = document(styled_url + plain_url)
    report = fmt.analyse_document(xml, {}, policy, "d.docx")
    fixed, _, _ = fmt.fix_document(xml, {}, policy)
    check("URL styling is found and repaired after comments and processing instructions",
          any(row["rule"] == "FMT-T7b" for row in report["rows"])
          and leading_xml in fixed and '<w:i/>' not in fixed)

    # A COMMENTED-OUT property is not the live one: `ppr_of`/`rpr_of` must skip
    # it, or the scanner reads the comment while the fixer repairs the live pPr
    # and the re-scan keeps the row, making `fix` reject the whole document.
    commented = document(
        '<w:p><!-- <w:pPr><w:pStyle w:val="Heading1"/></w:pPr> -->'
        '<w:pPr><w:keepLines/></w:pPr><w:r><w:t>Body paragraph.</w:t></w:r></w:p>')
    report = fmt.analyse_document(commented, {}, policy, "d.docx")
    check("a commented pPr does not make the body paragraph a heading",
          not any(row["rule"] == "FMT-T3a" for row in report["rows"]),
          str(report["rows"]))
    fixed, _, _ = fmt.fix_document(commented, {}, policy)
    leftover = [row["rule"] for row in fmt.analyse_document(fixed, {}, policy, "d.docx")["rows"]
                if row["fix"] == "mechanical"]
    check("the scan and the fixer read the same live pPr, so no mechanical row is left",
          not leftover, f"{leftover} in {fixed}")

    live_heading = document(
        '<w:p><!-- <w:pPr><w:pStyle w:val="Caption"/></w:pPr> -->'
        '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        '<w:r><w:t>Real heading</w:t></w:r></w:p>')
    fixed, _, _ = fmt.fix_document(live_heading, {}, policy)
    check("the live heading after a commented pPr still gets keepNext",
          "<w:pStyle w:val=\"Heading1\"/><w:keepNext/><w:keepLines/>" in fixed, fixed)


def test_f16_fld_simple():
    """F16: w:fldSimple is part of the field inventory in_field() consults."""
    para = ('<w:p><w:r><w:fldSimple w:instr=" ADDIN ZOTERO_ITEM CSL_CITATION '
            '{&quot;citationID&quot;:&quot;X&quot;} "><w:r><w:t>Nature Methods</w:t>'
            '</w:r></w:fldSimple></w:r></w:p>')
    ranges = fmt.field_ranges(para)
    check("F16 the simple field is inventoried", len(ranges) == 1, str(ranges))
    check("F16 its result is inside the fence",
          bool(fmt.in_field(ranges, para.index("Nature"))), str(ranges))
    check("F16 the instruction is decoded",
          "ADDIN ZOTERO_ITEM" in ranges[0][2], repr(ranges[0][2]) if ranges else "")


def test_f18_unreadable_baseline():
    """F18: an unreadable baseline is an error, so the template gate cannot skip it."""
    bad = {"fields": [], "errors": ["unreadable DOCX package: BadZipFile: x"],
           "error_codes": {"unreadable-docx": 1},
           "counts": {}, "text": ""}
    cont = fmt.zotero_field_continuity_problems(bad, dict(bad))
    check("F18 an unreadable package is an error, not only a warning",
          any("unreadable-docx" in e for e in cont["errors"]), str(cont["errors"]))
    check("F18 the template gate's skip condition is no longer true",
          bool(cont["baseline_fields"] or cont["output_fields"] or cont["errors"]))


def test_f19_styles_dtd():
    """F19: a DTD in word/styles.xml is refused like the document part."""
    doc = f'<?xml version="1.0"?><w:document {W}><w:body/></w:document>'
    styles = (b'<?xml version="1.0"?><!DOCTYPE w:styles [<!ENTITY x "x">]>'
              b'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              b'<w:style w:type="paragraph" w:styleId="Body"/></w:styles>')
    tmp = Path(tempfile.mkdtemp(prefix="fixbugsB_f19_"))
    p = make_docx(tmp / "dtd.docx", doc.encode("utf-8"), styles)
    with zipfile.ZipFile(p) as z:
        raised = False
        try:
            fmt.parse_styles(z)
        except OSError:
            raised = True
    check("F19 parse_styles refuses the DTD instead of returning {}", raised)
    rep = fmt.analyse_package(p, dict(fmt.POLICY_DEFAULTS))
    check("F19 the scan reports FMT-X1 for it",
          any(r.get("rule") == "FMT-X1" for r in rep.get("rows") or []),
          str(rep.get("rows"))[:200])


def main() -> int:
    test_f12_utf16_parts()
    test_f13_tab_stops()
    test_f14_alternate_content_runs()
    test_f15_nested_textbox_paragraph()
    test_textbox_repairs_preserve_paragraph_ownership()
    test_f16_fld_simple()
    test_f18_unreadable_baseline()
    test_f19_styles_dtd()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return 1
    print("\nALL GROUP-B REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

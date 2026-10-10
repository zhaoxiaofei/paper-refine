#!/usr/bin/env python3
"""The 2026-10-10 round-2 debug run: repros from the broad-scope audit candidate set.

Run:  python3 .paper_test/test_debug_round2_2026_1010.py

Each check fails on the pre-round-2 tree (5cda903) and passes only when the
confirmed defect it pins is closed:

  * `detect_round_judge_conflicts` raised IndexError on an empty agent-authored
    `checks` value, silently killing the whole mechanical conflicts pass;
  * `_bold_label_runs` emitted a run with TWO `w:rPr` children when the run
    carried the routine `w:rsidRPr` attribute (schema-invalid output);
  * `zotero_structural_faults` dropped a fault whose part name contains a space
    (`word/my notes.xml: [bad-citation-json] ...`), so `zotero-check` printed
    CLEAN, exit 0 on a broken field;
  * `field_result_text_ranges` is paragraph-scoped, so a multi-paragraph Zotero
    bibliography field reports NO protected result text and the fixer happily
    edits text that Word/Zotero will regenerate (AGENT.md rule 16);
  * the FMT-PDF1 strong placeholder pattern matched the ordinary phrase
    "please wait", flagging healthy one-page letters as XFA form shells.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_r2_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_r2_format", WS / "paper_docx_format.py")

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    if cond:
        print(f"[ok ] {name}")
    else:
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))
        FAILS.append(name)


def scratch(prefix="pr2_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def _cite_field(cid, marker, items, visible):
    """A Zotero citation field: `items` = [(key, title, first-author family)]."""
    payload = {
        "citationID": cid,
        "properties": {"formattedCitation": marker, "plainCitation": visible,
                       "noteIndex": 0},
        "citationItems": [
            {"id": k + "/1",
             "uris": [f"http://zotero.org/users/local/AAA/items/{k}"],
             "itemData": {"type": "article-journal", "title": title,
                          "author": [{"family": family, "given": "A"}]}}
            for k, title, family in items],
    }
    instr = html.escape(" ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(payload),
                        quote=False)
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>{visible}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. the judge-conflict mechanical pass survives an empty `checks` value
# ---------------------------------------------------------------------------
def test_conflicts_empty_check():
    base = {"target": "c1", "opponent": "c2"}
    ops = [dict(base, judge_run="r1_j1", checks={"M20": ""}),
           dict(base, judge_run="r1_j2", checks={"M20": "clean"})]
    try:
        pp.detect_round_judge_conflicts(ops)
        raised = None
    except Exception as e:                                          # noqa: BLE001
        raised = e
    check("an empty checks value no longer kills the conflicts pass",
          raised is None, f"{type(raised).__name__}: {raised}" if raised else "")
    # The pass must still do its job: a real clean-vs-findings split is detected.
    ops2 = [dict(base, judge_run="r1_j1", checks={"M20": "clean"}),
            dict(base, judge_run="r1_j2", checks={"M20": "findings"}),
            dict(base, judge_run="r1_j3", checks={"M20": ""})]
    rows = pp.detect_round_judge_conflicts(ops2)
    check("clean vs findings is still reported as a check_disposition conflict",
          any(r.get("kind") == "check_disposition" for r in rows), str(rows)[:300])


# ---------------------------------------------------------------------------
# 2. the venue-template pass never emits two <w:rPr> children in one run
# ---------------------------------------------------------------------------
def test_bold_label_runs_single_rpr():
    para = ('<w:p><w:r><w:rPr w:rsidRPr="00A1B2C3"><w:rFonts w:ascii="Times"/></w:rPr>'
            '<w:t>* Correspondence: Zhen Xie, lead contact</w:t></w:r></w:p>')
    out = fmt._bold_label_runs(para)
    per_run = [r.count("<w:rPr") for r in
               __import__("re").findall(r"<w:r\b[\s\S]*?</w:r>", out)]
    check("no run carries two w:rPr children",
          per_run and all(n <= 1 for n in per_run), f"rPr counts {per_run}: {out[:220]}")
    check("the label still ends up bold", fmt._label_is_bold(out), out[:200])
    check("the text is byte-preserved",
          fmt.text_of(out) == fmt.text_of(para),
          f"{fmt.text_of(out)!r} != {fmt.text_of(para)!r}")
    # The same shape without the rsid attribute (the case the old regex handled).
    plain = ('<w:p><w:r><w:t>* Correspondence: Someone</w:t></w:r></w:p>')
    out2 = fmt._bold_label_runs(plain)
    check("a plain run is still split and bolded",
          fmt._label_is_bold(out2) and fmt.text_of(out2) == fmt.text_of(plain), out2[:200])


# ---------------------------------------------------------------------------
# 3. zotero_structural_faults sees a fault whose part name contains a space
# ---------------------------------------------------------------------------
def test_structural_fault_space_part():
    msg = "word/my notes.xml: [bad-citation-json] unparseable citation payload"
    faults = fmt.zotero_structural_faults({"errors": [msg]})
    check("a bad-citation-json fault in 'word/my notes.xml' is not dropped",
          faults == [msg], str(faults))
    # A non-Zotero part prefix must still not smuggle in an unrelated code.
    msg2 = "word/notes.xml: [unclosed-field] some non-Zotero field remains open"
    check("a non-Zotero unclosed-field is still ignored",
          fmt.zotero_structural_faults({"errors": [msg2]}) == [])
    msg3 = "word/notes.xml: [no-separate] the item field has no separate"
    check("a Zotero item-field no-separate is still reported",
          fmt.zotero_structural_faults({"errors": [msg3]}) == [msg3])


# ---------------------------------------------------------------------------
# 4. a multi-paragraph field's result text is protected document-wide
# ---------------------------------------------------------------------------
P1 = ('<w:p><w:pPr><w:pStyle w:val="RefList"/></w:pPr>'
      '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
      '<w:r><w:instrText> ADDIN ZOTERO_BIBL </w:instrText></w:r>'
      '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
      '<w:r><w:t>1. First reference.</w:t></w:r></w:p>')
P2 = ('<w:p><w:pPr><w:pStyle w:val="RefList"/></w:pPr>'
      '<w:r><w:t> 2. Second reference with a leading space.</w:t></w:r></w:p>')
P3 = ('<w:p><w:pPr><w:pStyle w:val="RefList"/></w:pPr>'
      '<w:r><w:t>3. Third reference.</w:t></w:r>'
      '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
P4 = ('<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr>'
      '<w:r><w:t> A stray leading space outside any field.</w:t></w:r></w:p>')


def _doc_xml(body: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{body}</w:body></w:document>')


def _make_docx(path: Path, body: str):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.'
                   'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.'
                   'org/officeDocument/2006/relationships/officeDocument" '
                   'Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", _doc_xml(body))


def test_multiparagraph_field_protection():
    xml = _doc_xml(P1 + P2 + P3)
    spans = fmt._field_result_spans(xml)
    paras = fmt.paragraphs(xml)
    run_spans = [[(s, e) for s, e in [(0, 0)]]]  # noqa: F841 - clarity only
    protected = [fmt.field_result_text_ranges(para, spans, p0)
                 for p0, _p1, para in paras]
    t2 = fmt.text_of(paras[1][2])
    check("the middle result paragraph of a 3-paragraph field is protected",
          protected[1] == [(0, len(t2))], str(protected))
    check("the first result run and the last are protected too",
          protected[0] == [(0, len(fmt.text_of(paras[0][2])))]
          and protected[2] == [(0, len(fmt.text_of(paras[2][2])))], str(protected))

    # End to end: the scanner marks the leading-space row field-protected and
    # the fixer leaves the field's result text alone (AGENT.md rule 16).
    root = scratch("pr2_docx_")
    src, out = root / "manuscript.docx", root / "out.docx"
    _make_docx(src, P1 + P2 + P3 + P4)
    policy = fmt.load_policy(None)
    info = fmt.scan_paths([src], policy)
    rows = [r for r in info["rows"] if r["rule"] == "FMT-P4"]
    by_loc = {r["location"]: r for r in rows}
    check("the leading-space row inside the field is reported field-protected",
          by_loc.get("p1", {}).get("protected") is True
          and by_loc["p1"].get("fix") == "style-field"
          and by_loc.get("p3", {}).get("fix") == "mechanical", str(rows))
    res = fmt.fix_package(src, out, policy)
    check("the fixer verifies ok while refusing the protected edit", res.get("ok") is True,
          str(res.get("verified"))[:300] + str(res.get("error") or ""))
    with zipfile.ZipFile(out) as z:
        after = z.read("word/document.xml").decode("utf-8")
    check("the field's result text is byte-identical after the fix",
          fmt.text_of(fmt.paragraphs(after)[1][2]) == fmt.text_of(paras[1][2]),
          repr(fmt.text_of(fmt.paragraphs(after)[1][2])))
    check("a mechanical control row OUTSIDE the field still gets fixed",
          fmt.text_of(fmt.paragraphs(after)[3][2]).startswith("A stray leading space"),
          repr(fmt.text_of(fmt.paragraphs(after)[3][2])))


# ---------------------------------------------------------------------------
# 5. FMT-PDF1 fires on the Adobe shell, not on ordinary prose
# ---------------------------------------------------------------------------
def _tiny_pdf(path: Path, page_text: bytes = b"", xfa: bytes = None,
              page_w=612, page_h=792):
    """A minimal one-page PDF; `xfa` adds the AcroForm/XFA store when given."""
    page_stream = zlib.compress(b"BT /F1 12 Tf 72 720 Td (" + page_text + b") Tj ET")
    objects = []
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    if xfa is not None:
        catalog = (b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [] "
                   b"/XFA [(xdp:xdp) 6 0 R] >> >>")
    objects.append(catalog)
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
                   + f"{page_w} {page_h}".encode() + b"] /Contents 4 0 R "
                   b"/Resources << /Font << /F1 5 0 R >> >> >>")
    objects.append(b"<< /Length " + str(len(page_stream)).encode() + b" >>\nstream\n"
                   + page_stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    if xfa is not None:
        objects.append(b"<< /Length " + str(len(zlib.compress(xfa))).encode()
                       + b" >>\nstream\n" + zlib.compress(xfa) + b"\nendstream")
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n"
            f"{xref}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))


def test_pdf_placeholder_precision():
    root = scratch("pr2_pdf_")
    letter = root / "response-to-reviewers.pdf"
    _tiny_pdf(letter)
    prose = "Please wait for the reviewer assignment before contacting us again."
    rules = [r["rule"] for r in fmt.pdf_artifact_rows(letter, text=prose)]
    check("ordinary prose 'Please wait for ...' is not reported as FMT-PDF1",
          "FMT-PDF1" not in rules, str(rules))

    # The ellipsis form in a document pdfinfo proves is NOT a form: a reader
    # sees the words, so the "form shell" row would be a false positive. (With
    # no pdfinfo on the box the row is kept deliberately: unprovable.)
    ellipsis_prose = "Please wait... the response letter follows on the next page."
    rules0 = [r["rule"] for r in fmt.pdf_artifact_rows(letter, text=ellipsis_prose)]
    check("'Please wait...' prose in a non-form PDF is not a form shell",
          (not shutil.which("pdfinfo"))
          or (fmt._pdfinfo_form(letter).lower() == "none" and "FMT-PDF1" not in rules0),
          f"pdfinfo form={fmt._pdfinfo_form(letter)!r} rules={rules0}")

    shell = root / "reporting-summary-filled.pdf"
    placeholder = (b"Please wait... If this message is not eventually replaced by the proper "
                   b"contents of the document, your PDF viewer may not be able to display this "
                   b"type of document.")
    dataset = (b"<xfa:datasets xmlns:xfa='http://www.xfa.org/schema/xfa-data/1.0/'>"
               b"<xfa:data><form><author/></form></xfa:data></xfa:datasets>")
    _tiny_pdf(shell, placeholder, xfa=dataset)
    rules2 = [r["rule"] for r in fmt.pdf_artifact_rows(shell)]
    check("the Adobe XFA shell is still reported",
          {"FMT-PDF1", "FMT-PDF2"} <= set(rules2) or not shutil.which("pdftotext"),
          str(rules2))

    plain = root / "normal.pdf"
    _tiny_pdf(plain, b"A normal page of text with no placeholder phrase.")
    check("a normal PDF still produces no artifact row",
          fmt.pdf_artifact_rows(plain) == [], str(fmt.pdf_artifact_rows(plain)))


# ---------------------------------------------------------------------------
# 6. a numeric-style document keeps its footnote staleness visible even when
#    the footnote part itself is mixed numeric/author-year
# ---------------------------------------------------------------------------
def test_mixed_numeric_part():
    items = [("AAAA", "Alpha work", "Alvarez"), ("BBBB", "Beta work", "Bianchi"),
             ("CCCC", "Gamma work", "Chen"), ("DDDD", "Delta work", "Dubois")]
    doc = ('<w:document xmlns:w="%s"><w:body>' % NS
           + _cite_field("dA", r"\super 1\nosupersub{}", items[:1], "1")
           + _cite_field("dB", r"\super 2\nosupersub{}", items[1:2], "2")
           + '</w:body></w:document>')
    foot = ('<w:footnotes xmlns:w="%s"><w:footnote w:id="1">' % NS
            + _cite_field("fC", r"\super 39\nosupersub{}", items[2:3], "39")
            + _cite_field("fD", "Smith et al., 2019", items[3:4], "Smith et al., 2019")
            + '</w:footnote></w:footnotes>')
    rows = fmt.zotero_parity_rows_for_parts(
        [("word/document.xml", doc), ("word/footnotes.xml", foot)])
    z1 = [r for r in rows if r["rule"] == "FMT-Z1" and "footnotes" in str(r.get("location"))]
    check("a stale numeric footnote beside an author-year footnote is reported",
          bool(z1), str(rows)[:400])
    check("the author-year footnote is not misreported as stale",
          not any(r["rule"] in ("FMT-Z1", "FMT-Z3") and "fD" in str(r.get("location"))
                  for r in rows), str(rows)[:400])


# ---------------------------------------------------------------------------
# 7. FMT-O1 dates every number of a "Figures 3 and 4" call-out
# ---------------------------------------------------------------------------
def test_display_order_conjunction():
    paras = ["Results appear in Figures 3 and 4.", "Figure 5 shows the pipeline.",
             "As shown in Figure 4, the effect is large."]
    rows = fmt.display_order_rows(paras, order_policy=True)
    check("a later number inside a conjunction counts as a first mention",
          rows == [], str(rows)[:300])
    out_of_order = ["Results appear in Figures 3 and 4.", "Figure 2 shows the pipeline."]
    rows2 = fmt.display_order_rows(out_of_order, order_policy=True)
    check("a genuinely out-of-order first mention is still reported",
          any(r["rule"] == "FMT-O1" for r in rows2), str(rows2)[:300])
    # The conjunction list must not read a trailing ENGLISH word as an item:
    # "and C. elegans" used to date a phantom "figure 100" (X-ray: "figure 10"),
    # and the next real item then looked out of order.
    for probe in ("As shown in Figure 1 and C. elegans data were collected.",
                  "As shown in Figure 2 and X-ray diffraction data were collected."):
        rows3 = fmt.display_order_rows([probe, "Figure 3 shows the pipeline."],
                                       order_policy=True)
        check(f"a trailing word in {probe!r} is not read as a call-out",
              rows3 == [], str(rows3)[:250])


def test_marker_shapes():
    check("'see 39' names 39", fmt._marker_numbers("see 39") == [39],
          str(fmt._marker_numbers("see 39")))
    check("'1, 2 p. 5, 3' keeps the 2",
          fmt._marker_numbers("1, 2 p. 5, 3") == [1, 2, 3],
          str(fmt._marker_numbers("1, 2 p. 5, 3")))
    check("a bare year is not a reference number", fmt._marker_numbers("2019") == [],
          str(fmt._marker_numbers("2019")))
    check("'Smith et al., 2019' names no reference number",
          fmt._marker_numbers("Smith et al., 2019") == [],
          str(fmt._marker_numbers("Smith et al., 2019")))
    check("a page locator does not add a number", fmt._marker_numbers("1, p. 5") == [1],
          str(fmt._marker_numbers("1, p. 5")))
    check("(hg19)37 still names 37", fmt._marker_numbers("(hg19)37") == [37],
          str(fmt._marker_numbers("(hg19)37")))
    check("a year range is not a reference range", fmt._marker_numbers("2019-2020") == [],
          str(fmt._marker_numbers("2019-2020")))
    items = [("AAAA", "Alpha work", "Smith"), ("BBBB", "Beta work", "Doe")]
    doc = ('<w:document xmlns:w="%s"><w:body>' % NS
           + _cite_field("c1", "Smith et al., 2019", items[:1], "Smith et al., 2019")
           + _cite_field("c2", "Doe et al., 2020", items[1:2], "Doe et al., 2020")
           + '</w:body></w:document>')
    rows = fmt.zotero_parity_rows_for_parts([("word/document.xml", doc)])
    check("a healthy author-year document reports no stale rows", rows == [],
          str(rows)[:300])


# ---------------------------------------------------------------------------
# 8. the template writer sees a self-closing first section (page 1 furniture)
# ---------------------------------------------------------------------------
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT_XML = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
           'package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/>'
           '<Override PartName="/word/document.xml" ContentType="application/vnd.'
           'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
           '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
           'officedocument.wordprocessingml.styles+xml"/>'
           '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-'
           'officedocument.wordprocessingml.header+xml"/></Types>')
_ROOT_RELS = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
              'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
              'openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
              'Target="word/document.xml"/></Relationships>')


def _doc_xml2(body: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{NS}" xmlns:r="{RNS}"><w:body>{body}</w:body>'
            '</w:document>')


def _zip_parts(path: Path, parts: dict):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)


def test_self_closing_first_section_in_template_writer():
    root = scratch("pr2_sect_")
    man, tpl, out = root / "man.docx", root / "tpl.docx", root / "out.docx"
    body = ('<w:p><w:r><w:t>Two Section Manuscript</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:sectPr/></w:pPr></w:p>'
            '<w:p><w:r><w:t>Second section body text.</w:t></w:r></w:p>'
            '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>')
    _zip_parts(man, {"[Content_Types].xml": _CT_XML, "_rels/.rels": _ROOT_RELS,
                     "word/document.xml": _doc_xml2(body),
                     "word/_rels/document.xml.rels":
                         '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                         'openxmlformats.org/package/2006/relationships"></Relationships>'})
    tpl_body = ('<w:p><w:r><w:t>Template</w:t></w:r></w:p>'
                '<w:sectPr><w:headerReference w:type="default" r:id="rId4"/>'
                '<w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
                'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr>')
    _zip_parts(tpl, {"[Content_Types].xml": _CT_XML, "_rels/.rels": _ROOT_RELS,
                     "word/document.xml": _doc_xml2(tpl_body),
                     "word/_rels/document.xml.rels":
                         '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                         'openxmlformats.org/package/2006/relationships"><Relationship '
                         'Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/'
                         '2006/relationships/header" Target="header1.xml"/></Relationships>',
                     "word/styles.xml":
                         f'<?xml version="1.0"?><w:styles xmlns:w="{NS}"><w:style '
                         'w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/>'
                         '</w:style></w:styles>',
                     "word/header1.xml":
                         f'<?xml version="1.0"?><w:hdr xmlns:w="{NS}"><w:p><w:r>'
                         '<w:t>Venue running head</w:t></w:r></w:p></w:hdr>'})
    rep = fmt.apply_word_template(man, out, tpl)
    check("the template pass succeeds", rep.get("ok") is True, str(rep)[:200])
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    first = fmt.first_section_props(xml) or ""
    check("the self-closing page-1 section carries the first-page furniture",
          "headerReference" in first and "titlePg" in first, first[:300])
    check("page-1 geometry is the template's", 'w:w="11906"' in first, first[:300])
    stripped = re.sub(r"<w:sectPr[\s\S]*?</w:sectPr>|<w:sectPr[^>]*/>", "", xml)
    check("no header/footer reference is spliced outside a section",
          not re.search(r"headerReference|footerReference", stripped), stripped[-200:])
    ET.fromstring(xml)
    check("the output stays well-formed", True)


def test_blank_pdf_reaches_the_publish_scan():
    """The publish path claims FMT-PDF1..3 but never passed a page count."""
    root = scratch("pr2_blankpdf_")
    blank = root / "empty-export.pdf"
    _tiny_pdf(blank)                      # one page, no text, no image
    rules = [r["rule"] for r in fmt.pdf_artifact_rows(blank, pages=1)]
    check("an empty one-page export is reported as FMT-PDF3 when the path"
          " is given the page count",
          "FMT-PDF3" in rules, str(rules))
    rows = pp.package_pdf_rows(root)
    check("the publish scan reports the empty export too",
          any(r["rule"] == "FMT-PDF3" for r in rows), str(rows)[:300])


def test_subprocess_text_output_decodes_as_utf8():
    """pdftotext output must not be decoded with the caller's locale codec.

    Under a non-UTF-8 locale (forced for the child), an invalid byte used to
    raise UnicodeDecodeError out of the scan; the fix decodes as UTF-8 with
    replacement, like the agent launcher already does.
    """
    root = scratch("pr2_enc_")
    bindir = root / "bin"
    bindir.mkdir()
    fake = bindir / "pdftotext"
    fake.write_text("#!/bin/sh\nprintf '\\377\\376plain\\n'\n", encoding="utf-8")
    fake.chmod(0o755)
    pdf = root / "x.pdf"
    _tiny_pdf(pdf)
    code = (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('m', {str(WS / 'paper_docx_format.py')!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        f"rows = m.pdf_artifact_rows({str(pdf)!r})\n"
        "print('DECODED', len(rows))\n")
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["LC_ALL"] = "C"
    env["PYTHONCOERCECLOCALE"] = "0"
    env["PYTHONUTF8"] = "0"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, env=env)
    check("non-UTF-8 pdftotext output no longer crashes the scan",
          proc.returncode == 0 and "DECODED" in (proc.stdout or ""),
          ((proc.stdout or "") + (proc.stderr or ""))[-300:])


def test_rounds_count_clamp():
    ctx = pp.Ctx(scratch("pr2_ctx_"))
    ctx.cfg = {"rounds": 0}
    check("rounds_count() clamps a hand-edited zero like config_rounds",
          ctx.rounds_count() == pp.config_rounds(cfg={"rounds": 0}) >= 1,
          f"{ctx.rounds_count()} vs {pp.config_rounds(cfg={'rounds': 0})}")
    ctx.cfg = {"rounds": 2}
    check("rounds_count() keeps a configured count", ctx.rounds_count() == 2)
    ctx.cfg = {"rounds": "junk"}
    check("rounds_count() survives a corrupt value", ctx.rounds_count() >= 1)
    ctx.cfg = {"rounds": -5}
    check("rounds_count() clamps a negative count like config_rounds",
          ctx.rounds_count() == pp.config_rounds(cfg={"rounds": -5}) == 1,
          f"{ctx.rounds_count()} vs {pp.config_rounds(cfg={'rounds': -5})}")


def test_only_range_is_bounded():
    """`--only 1-999999999` used to materialize a billion-element set."""
    code = (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('m', {str(WS / 'paper_pipeline.py')!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "try:\n"
        "    m.parse_only_rounds('1-999999999', '1-999999999')\n"
        "    print('NO-ERROR')\n"
        "except SystemExit as e:\n"
        "    print('DIED', e.code)\n")
    proc = subprocess.run(
        ["bash", "-c", "ulimit -v 3000000; exec python3 -c " + shlex.quote(code)],
        capture_output=True, text=True, timeout=120)
    check("an implausible --only range is refused, not materialized",
          "DIED" in (proc.stdout or ""),
          ((proc.stdout or "") + (proc.stderr or ""))[-250:])
    check("a real range still parses",
          pp.parse_only_rounds("1-3", "1-3") == {1, 2, 3})


def test_zotero_check_counts_footnote_items():
    import contextlib
    import io
    from types import SimpleNamespace
    root = scratch("pr2_zcheck_")
    p = root / "note-style.docx"
    _zip_parts(p, {"[Content_Types].xml": _CT_XML, "_rels/.rels": _ROOT_RELS,
                   "word/document.xml":
                       f'<w:document xmlns:w="{NS}"><w:body><w:p><w:r>'
                       '<w:t>Body text with no in-text fields.</w:t></w:r></w:p></w:body>'
                       '</w:document>',
                   "word/footnotes.xml":
                       f'<w:footnotes xmlns:w="{NS}"><w:footnote w:id="1">'
                       + _cite_field("f1", r"\super 1\nosupersub{}",
                                     [("AAAA", "Alpha work", "Alvarez")], "1")
                       + '</w:footnote></w:footnotes>'})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fmt.cmd_zotero_check(SimpleNamespace(file=str(p), json=None))
    out = buf.getvalue()
    check("zotero-check's distinct count includes footnote citations",
          "1 distinct cited item" in out and rc == 0, out.replace("\n", " | ")[:300])


def test_home_relative_mcp_command_is_probed_expanded():
    """A `~/...` MCP command must be probed after ~ expansion, not Path(raw)."""
    conf, spec_fn = pp.mcp_server_configured, pp.mcp_server_spec
    try:
        pp.mcp_server_configured = lambda name: True
        pp.mcp_server_spec = lambda name: {"command": "~", "args": []}
        check("docx_compare_mcp_spec keeps a home-relative command",
              pp.docx_compare_mcp_spec() != {}, "spec was dropped")
        names = [name for name, _spec in pp.visual_renderer_choices()]
        check("the renderer chain keeps a home-relative MCP command",
              any(str(n).startswith("mcp:") for n in names), str(names)[:200])
    finally:
        pp.mcp_server_configured, pp.mcp_server_spec = conf, spec_fn


def test_lookup_gene_kind_accepted():
    """The pipeline builds kind="gene" lookup targets; the CLI must accept it."""
    import contextlib
    import io
    calls = {}
    orig = fmt.lookup_kind
    try:
        def fake(kind, q, timeout=None):
            calls["kind"] = kind
            return {"kind": kind, "query": q, "verdict": "absent", "hits": [], "errors": []}
        fmt.lookup_kind = fake
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = fmt.main(["lookup", "TP53", "--kind", "gene", "--timeout", "1"])
        except SystemExit:                # argparse refusal = the CLI rejected the kind
            rc = 2
    finally:
        fmt.lookup_kind = orig
    check("lookup --kind gene is accepted and dispatched",
          rc == 0 and calls.get("kind") == "gene", f"rc={rc} calls={calls}")


def test_zotero_check_sees_every_style_store():
    """The CLI read two store parts; the scanner also reads customXml."""
    import contextlib
    import io
    from types import SimpleNamespace
    root = scratch("pr2_z5_")
    p = root / "third-store.docx"
    doc_body = _cite_field("c1", r"\super 1\nosupersub{}",
                           [("AAAA", "Alpha work", "Alvarez")], "1")
    _zip_parts(p, {
        "[Content_Types].xml": _CT_XML, "_rels/.rels": _ROOT_RELS,
        "word/document.xml":
            f'<w:document xmlns:w="{NS}"><w:body>{doc_body}</w:body></w:document>',
        "word/settings.xml":
            f'<w:settings xmlns:w="{NS}"><w:docVars><w:docVar w:name="ZOTERO_STYLE" '
            'w:val="http://www.zotero.org/styles/nature-biotechnology"/></w:docVars>'
            '</w:settings>',
        "customXml/item1.xml":
            '<customXml>http://www.zotero.org/styles/apa</customXml>'})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fmt.cmd_zotero_check(SimpleNamespace(file=str(p), json=None))
    out = buf.getvalue()
    check("zotero-check reports a third style store in customXml/item1.xml",
          "FMT-Z5" in out and rc == 0, out.replace("\n", " | ")[:300])


def test_format_scan_applies_source_overrides():
    """A later source's copy wins; the overridden copy must not be scanned."""
    root = scratch("pr2_fmtovr_")
    a, b = root / "a", root / "b"
    a.mkdir()
    b.mkdir()
    _zip_parts(a / "x.docx", {"word/document.xml":
               f'<w:document xmlns:w="{NS}"><w:body><w:p><w:r><w:br w:type="page"/>'
               '</w:r></w:p></w:body></w:document>'})
    _zip_parts(b / "x.docx", {"word/document.xml":
               f'<w:document xmlns:w="{NS}"><w:body><w:p><w:r><w:t>clean text'
               '</w:t></w:r></w:p></w:body></w:document>'})
    info = pp.scan_format_in_sources([(a, "", ()), (b, "", ())])
    check("the format scan reports nothing from a copy a later source overrides",
          info["rows"] == [], str(info["rows"])[:300])


def test_terminate_agent_tree_without_posix_group_calls():
    """A platform without os.getpgid/os.killpg must not raise out of the kill."""
    saved = {}
    for name in ("getpgid", "killpg"):
        if hasattr(os, name):
            saved[name] = getattr(os, name)
            delattr(os, name)
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        try:
            pp._terminate_agent_tree(proc)
            raised = None
        except BaseException as e:                                  # noqa: BLE001
            raised = e
        check("the agent-tree kill survives a platform without process groups",
              raised is None, f"{type(raised).__name__}: {raised}")
        check("the process is actually dead", proc.poll() is not None)
    finally:
        for name, fn in saved.items():
            setattr(os, name, fn)
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_parity_parts_reuse_the_inventory():
    """One parse per part: the multi-part parity call must not re-inventory."""
    items = [("AAAA", "Alpha work", "Alvarez"), ("BBBB", "Beta work", "Bianchi")]
    doc = (f'<w:document xmlns:w="{NS}"><w:body>'
           + _cite_field("dA", r"\super 1\nosupersub{}", items[:1], "1")
           + _cite_field("dB", r"\super 2\nosupersub{}", items[1:], "2")
           + '</w:body></w:document>')
    foot = (f'<w:footnotes xmlns:w="{NS}"><w:footnote w:id="1">'
            + _cite_field("fC", r"\super 3\nosupersub{}", items[:1], "3")
            + '</w:footnote></w:footnotes>')
    parts = [("word/document.xml", doc), ("word/footnotes.xml", foot)]
    calls = {"n": 0}
    orig = fmt.zotero_citation_state
    try:
        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)
        fmt.zotero_citation_state = counting
        rows = fmt.zotero_parity_rows_for_parts(parts)
    finally:
        fmt.zotero_citation_state = orig
    check("the multi-part parity call inventories each part once",
          calls["n"] == len(parts), f"{calls['n']} parse(s) for {len(parts)} parts")
    z1 = [r for r in rows if r["rule"] == "FMT-Z1"]
    check("the stale footnote is still reported once by the reused inventory",
          len(z1) == 1 and "footnotes" in str(z1[0].get("location")),
          str([(r["rule"], r.get("location")) for r in rows])[:300])


def test_non_dict_profile_sources_are_reported():
    err = None
    try:
        pp.normalize_venue_profile({"id": "x", "sources": ["list", "not", "a", "map"]})
    except pp.VenueProfileError as e:
        err = str(e)
    check("a non-object profile 'sources' is reported, not silently dropped",
          err is not None and "sources" in err, str(err))
    prof = pp.normalize_venue_profile({"id": "x", "sources": {"a": "b"}})
    check("a valid sources map is carried through",
          prof.get("sources") == {"a": "b"}, str(prof.get("sources")))


def test_root_mutating_commands_are_run_logged():
    for name in ("conform", "add-venue", "track"):
        check(f"{name} keeps its console in the root's run log",
              name in pp.LOGGING_COMMANDS, str(pp.LOGGING_COMMANDS))


def test_reference_rules_survive_style_remap():
    """A venue template remaps style ids; FMT-R must still see the list."""
    root = scratch("pr2_reffb_")
    p = root / "restyled.docx"
    body = ('<w:p><w:r><w:t>References</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="RefList"/></w:pPr><w:r>'
            '<w:t xml:space="preserve">1. Dong, X. et al. SCCNV: a software tool. '
            'Front. Genet. Volume 11-2020, (2020).</w:t></w:r></w:p>')
    _zip_parts(p, {"word/document.xml":
                   f'<w:document xmlns:w="{NS}"><w:body>{body}</w:body></w:document>'})
    rows = fmt.analyse_package(p, fmt.load_policy(None))["rows"]
    check("FMT-R1 fires when the reference list carries a remapped style id",
          any(r["rule"] == "FMT-R1" for r in rows), str([r["rule"] for r in rows]))


def test_uppercase_docx_extension_is_scanned():
    """rglob('*.docx') is case-sensitive on Linux; .DOCX must be seen too."""
    root = scratch("pr2_docxcase_")
    _zip_parts(root / "REPORT.DOCX", {"word/document.xml":
               f'<w:document xmlns:w="{NS}"><w:body><w:p><w:r><w:br w:type="page"/>'
               '</w:r></w:p></w:body></w:document>'})
    info = fmt.scan_paths([root], fmt.load_policy(None))
    check("scan_paths sees an uppercase-extension DOCX",
          any(r["rule"] == "FMT-S1" for r in info["rows"]),
          str([r["rule"] for r in info["rows"]])[:200])
    pinfo = pp.scan_format_in_sources([(root, "", ())])
    check("the pipeline's format scan sees it too",
          any(r["rule"] == "FMT-S1" for r in pinfo["rows"]),
          str([r["rule"] for r in pinfo["rows"]])[:200])


def test_availability_pins_every_host_spelling():
    a = "cd2e3e7847b5ccef0288b73624cd4b41fffc8e1a"
    b = "0b105331aa1fbbd94832ae308a84e133831fa807"
    def rules(paras):
        return [r["rule"] for r in fmt.availability_rows(paras, [False] * len(paras))]
    check("two GitLab commit pins on one repository are reported",
          "FMT-AV2" in rules([f"Code at https://gitlab.com/u/repo/-/commit/{a}",
                              f"Data at https://gitlab.com/u/repo/-/commit/{b}"]))
    check("two GitHub blob pins are reported",
          "FMT-AV2" in rules([f"Code at https://github.com/u/repo/blob/{a}/a.py",
                              f"Data at https://github.com/u/repo/blob/{b}/b.csv"]))
    check("two GitLab tree pins are reported",
          "FMT-AV2" in rules([f"Code at https://gitlab.com/u/repo/-/tree/{a}",
                              f"Data at https://gitlab.com/u/repo/-/tree/{b}"]))
    check("two github tree pins are still reported",
          "FMT-AV2" in rules([f"Code at https://github.com/u/repo/tree/{a}",
                              f"Data at https://github.com/u/repo/tree/{b}"]))
    check("release tags are not treated as conflicting pins",
          "FMT-AV2" not in rules(["Release v1.2.3: "
                                  "https://github.com/u/repo/releases/tag/v1.2.3",
                                  "Release v1.2.4: "
                                  "https://github.com/u/repo/releases/tag/v1.2.4"]))


def main() -> int:
    sections = [("conflicts_empty_check", test_conflicts_empty_check),
                ("bold_label_runs", test_bold_label_runs_single_rpr),
                ("structural_fault_space_part", test_structural_fault_space_part),
                ("multiparagraph_field_protection", test_multiparagraph_field_protection),
                ("pdf_placeholder_precision", test_pdf_placeholder_precision),
                ("mixed_numeric_part", test_mixed_numeric_part),
                ("display_order_conjunction", test_display_order_conjunction),
                ("marker_shapes", test_marker_shapes),
                ("self_closing_first_section", test_self_closing_first_section_in_template_writer),
                ("blank_pdf_publish_scan", test_blank_pdf_reaches_the_publish_scan),
                ("subprocess_utf8_decode", test_subprocess_text_output_decodes_as_utf8),
                ("rounds_count_clamp", test_rounds_count_clamp),
                ("only_range_bounded", test_only_range_is_bounded),
                ("zotero_check_footnote_counts", test_zotero_check_counts_footnote_items),
                ("mcp_home_relative", test_home_relative_mcp_command_is_probed_expanded),
                ("lookup_gene_kind", test_lookup_gene_kind_accepted),
                ("zotero_check_style_stores", test_zotero_check_sees_every_style_store),
                ("format_scan_overrides", test_format_scan_applies_source_overrides),
                ("terminate_agent_tree_portable",
                 test_terminate_agent_tree_without_posix_group_calls),
                ("parity_parts_reuse", test_parity_parts_reuse_the_inventory),
                ("profile_sources_validation", test_non_dict_profile_sources_are_reported),
                ("run_logged_commands", test_root_mutating_commands_are_run_logged),
                ("reference_rules_style_remap", test_reference_rules_survive_style_remap),
                ("uppercase_docx_extension", test_uppercase_docx_extension_is_scanned),
                ("availability_pin_spellings", test_availability_pins_every_host_spelling)]
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL ROUND-2 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

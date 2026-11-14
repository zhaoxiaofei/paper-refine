#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 2, group `docx_layout`.

Every check pins one candidate this wave re-validated on the tree and repaired
(F36, F38-F47, F49, F50). Fixtures are built inline (DOCX via `zipfile` where a
whole package is needed), so the file is hermetic: each scratch directory lives
under `tempfile.mkdtemp()` and is removed on exit.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_docx_layout.py
"""
from __future__ import annotations

import html
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = load("fb1115w2_docx_layout_fmt", "paper_docx_format.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


# ---------------------------------------------------------------------------
# small OOXML builders
# ---------------------------------------------------------------------------
def _p(text: str, ppr: str = "") -> str:
    return (f'<w:p><w:pPr>{ppr}</w:pPr><w:r><w:t xml:space="preserve">{text}</w:t>'
            "</w:r></w:p>")


def _doc(body: str) -> str:
    return f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'


ITEMS = {
    "K1": {"title": "Alpha diversity in single cells", "family": "Alvarez", "year": 2020},
    "K2": {"title": "Beta catenin signalling atlas", "family": "Bianchi", "year": 2021},
}
K1_TEXT = ("Alvarez, A. et al. Alpha diversity in single cells. "
           "Journal 1, 1-9 (2020).")
K2_TEXT = ("Bianchi, B. et al. Beta catenin signalling atlas. "
           "Journal 2, 1-9 (2021).")
BIB_FIELD_OPEN = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                  '<w:r><w:instrText>ADDIN ZOTERO_BIBL {}</w:instrText></w:r>'
                  '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')


def _cite_instr(cid: str, marker: str, keys: list, visible: str) -> str:
    payload = {
        "citationID": cid,
        "properties": {"formattedCitation": marker, "plainCitation": visible,
                       "noteIndex": 0},
        "citationItems": [
            {"id": k + "/1",
             "uris": [f"http://zotero.org/users/local/AAA/items/{k}"],
             "itemData": {"type": "article-journal", "title": ITEMS[k]["title"],
                          "author": [{"family": ITEMS[k]["family"], "given": "A"}],
                          "issued": {"date-parts": [[ITEMS[k]["year"]]]}}}
            for k in keys],
        "schema": "https://github.com/citation-style-language/schema/raw/master/csl-citation.json",
    }
    return "ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(payload, ensure_ascii=False)


def _field_para(cid: str, marker: str, keys: list, visible: str) -> str:
    instr = html.escape(_cite_instr(cid, marker, keys, visible), quote=False)
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>{visible}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def _bib_para(number: str, text: str, opener: str = "") -> str:
    return ('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>' + opener
            + f'<w:r><w:t>{number}.</w:t></w:r>'
            '<w:r><w:tab/><w:t xml:space="preserve">' + text + "</w:t></w:r></w:p>")


def _texts(xml: str) -> list:
    return [fmt.text_of(p[2]) for p in fmt.paragraphs(xml)]


# ---------------------------------------------------------------------------
# F36 -- visual line spans share text_of's token walk
# ---------------------------------------------------------------------------
def test_f36_line_spans() -> None:
    print("\n== F36: line spans skip pPr tab stops and nested text-box runs ==")
    para = ('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
            '<w:r><w:t xml:space="preserve">abc </w:t><w:br/><w:t>def</w:t></w:r></w:p>')
    lines = fmt.visual_text_lines(para)
    check("F36 the tab-STOP is not a new visual line",
          lines == [(0, 4), (5, 8)], repr(lines))
    p4 = [s for s in fmt.hygiene_spans(para) if s["rule"] == "FMT-P4"]
    check("F36 the trailing-space span is (3,4), not shifted past the break",
          p4 and (p4[0]["start"], p4[0]["end"]) == (3, 4), repr(p4))
    new, applied = fmt.rewrite_text_spans(para, [(3, 4, "")])
    check("F36 deleting the trailing space keeps the line break",
          fmt.text_of(new) == "abc\ndef" and applied == [(3, 4, " ", "")],
          repr(fmt.text_of(new)))

    boxed = ('<w:p xmlns:w="%s"><w:r><w:t xml:space="preserve">Body text </w:t></w:r>'
             '<w:r><w:drawing><w:txbxContent><w:p><w:r><w:t>box text</w:t></w:r>'
             '</w:p></w:txbxContent></w:drawing></w:r></w:p>' % W)
    text = fmt.text_of(boxed)
    p4 = [(s["start"], s["end"]) for s in fmt.hygiene_spans(boxed)
          if s["rule"] == "FMT-P4"]
    check("F36 a text-box host never produces an out-of-range span",
          all(0 <= a <= b <= len(text) for a, b in p4), (len(text), p4))
    check("F36 the text-box trailing space is the real (9,10)",
          p4 == [(9, 10)], p4)
    new, applied = fmt.rewrite_text_spans(boxed, [(9, 10, "")])
    check("F36 that span is applicable",
          applied == [(9, 10, " ", "")] and fmt.text_of(new) == "Body text",
          repr(applied))


# ---------------------------------------------------------------------------
# F38 -- duplicate citationItems cannot be collapsed into one number
# ---------------------------------------------------------------------------
def test_f38_duplicate_citation_items() -> None:
    print("\n== F38: a field citing one item twice is refused, not collapsed ==")
    xml = _doc(_p("Main")
               + _field_para("citeA", r"\super 1,2\nosupersub{}", ["K1", "K1"], "1,2")
               + _p("References")
               + _bib_para("1", K1_TEXT, opener=BIB_FIELD_OPEN)
               + '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    res = fmt.zotero_refresh_document(xml, _texts(xml))
    check("F38 a duplicate item refuses the refresh",
          res["changed"] is False and res.get("skip")
          and "more than once" in res["skip"], repr(res.get("skip")))
    check("F38 the document is returned unchanged", res["xml"] == xml)


# ---------------------------------------------------------------------------
# F39 -- one number split across several w:t elements
# ---------------------------------------------------------------------------
def test_f39_split_number_run() -> None:
    print("\n== F39: a split number run is renumbered as a whole ==")
    def split_bib(a: str, b: str, text: str, opener: str = "") -> str:
        return ('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>' + opener
                + f'<w:r><w:t>{a}</w:t><w:t>{b}</w:t></w:r>'
                '<w:r><w:tab/><w:t xml:space="preserve">' + text + "</w:t></w:r></w:p>")
    xml = _doc(_p("Main")
               + _field_para("cA", r"\super 1\nosupersub{}", ["K1"], "1")
               + _field_para("cB", r"\super 2\nosupersub{}", ["K2"], "2")
               + _p("References")
               + split_bib("1", "0.", K1_TEXT, opener=BIB_FIELD_OPEN)
               + split_bib("2", "0.", K2_TEXT)
               + '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    res = fmt.zotero_refresh_document(xml, _texts(xml))
    check("F39 the refresh succeeds", res["changed"] is True and not res.get("skip"),
          repr(res.get("skip")))
    after = _texts(res["xml"])
    entries = [t for t in after if "Alpha" in t or "Beta" in t]
    check("F39 split numbers 10/20 become 1/2",
          len(entries) == 2 and entries[0].startswith("1.")
          and entries[1].startswith("2."), [e[:24] for e in entries])
    check("F39 no stale 10./20. number survives",
          not any(t.startswith(("10.", "20.")) for t in entries),
          [e[:24] for e in entries])
    check("F39 the parity scan no longer calls the entries never-cited",
          not any(r["rule"] == "FMT-Z3" and "never cited" in r["evidence"]
                  for r in fmt.zotero_parity_rows(res["xml"], after)))


# ---------------------------------------------------------------------------
# F40 -- one instruction split across several w:instrText elements
# ---------------------------------------------------------------------------
def test_f40_split_instr_text() -> None:
    print("\n== F40: a split Zotero instruction is joined before parsing ==")
    instr = html.escape(_cite_instr("cA", r"\super 1\nosupersub{}", ["K1"], "1"),
                        quote=False)
    cut = instr.find("CSL_CITATION")
    first, second = instr[:cut], instr[cut:]
    para = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{first}</w:instrText></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{second}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>2</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    xml = _doc(para)
    report = fmt.zotero_field_report(xml)
    check("F40 the field report reads the split field as an item",
          report["fields"] and report["fields"][0]["kind"] == "item",
          report["fields"][:1])
    res = fmt.zotero_refresh_document(xml, _texts(xml))
    check("F40 the refresh no longer refuses it as unparseable",
          res["changed"] is True and not res.get("skip"), repr(res.get("skip")))
    check("F40 both instruction elements survive the rewrite",
          res["xml"].count("<w:instrText") == 2,
          res["xml"].count("<w:instrText"))
    reread = fmt.zotero_field_report(res["xml"])
    check("F40 the rewritten field still parses as one item field",
          reread["fields"] and reread["fields"][0]["kind"] == "item"
          and not reread["errors"], reread["errors"])


# ---------------------------------------------------------------------------
# F41 -- XML between two bibliography entries is never dropped
# ---------------------------------------------------------------------------
def test_f41_bookmark_between_entries() -> None:
    print("\n== F41: a bookmark between entries refuses the rebuild ==")
    xml = _doc(_p("Main")
               + _field_para("cA", r"\super 1\nosupersub{}", ["K1"], "1")
               + _field_para("cB", r"\super 2\nosupersub{}", ["K2"], "2")
               + _p("References")
               + _bib_para("2", K2_TEXT, opener=BIB_FIELD_OPEN)
               + '<w:bookmarkStart w:id="9" w:name="ref_alpha"/>'
               + _bib_para("1", K1_TEXT)
               + '<w:bookmarkEnd w:id="9"/>'
               + '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    res = fmt.zotero_refresh_document(xml, _texts(xml))
    check("F41 the rebuild is refused rather than unbalancing bookmarks",
          res["changed"] is False and res.get("skip")
          and "between bibliography entries" in res["skip"], repr(res.get("skip")))
    check("F41 the returned document is byte-identical",
          res["xml"] == xml and res["xml"].count("bookmarkStart") == 1
          and res["xml"].count("bookmarkEnd") == 1)


# ---------------------------------------------------------------------------
# F42 -- FMT-R1 does not append a locator the entry already carries
# ---------------------------------------------------------------------------
def test_f42_r1_locator() -> None:
    print("\n== F42: FMT-R1 sees a locator written later in the entry ==")
    xml = ('<w:body>' + _p("References")
           + _p("1. Smith J. A title. Front. Genet. Volume 11-2020. Article 565825.")
           + "</w:body>")
    recs = [{"key": "s", "type": "article", "title": "A title",
             "first_family": "Smith", "year": "2020",
             "journal": "Frontiers in Genetics", "volume": "11", "pages": "565825",
             "doi": "", "eprint": "", "eprinttype": "", "url": "", "file": "x.bib"}]
    res = fmt.repair_reference_entries(xml, recs)
    entries = [t for t in _texts(res["xml"]) if "Smith" in t]
    check("F42 the malformed volume is repaired",
          res["changed"] is True and entries
          and "Front. Genet. 11." in entries[0], entries)
    check("F42 the article number is not duplicated",
          entries and entries[0].count("565825") == 1, entries)


# ---------------------------------------------------------------------------
# F43 -- UTF-16 OOXML parts are decoded (and re-encoded) correctly
# ---------------------------------------------------------------------------
def _zip(path: Path, parts: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path


def test_f43_utf16_parts() -> None:
    print("\n== F43: p02 readers honour UTF-16 parts ==")
    tmp = scratch("fb1115w2_utf16_")
    rels = ('<?xml version="1.0" encoding="UTF-16"?>'
            f'<Relationships xmlns="{PKG_REL}">'
            f'<Relationship Id="rId1" Type="{R}/attachedTemplate" '
            'Target="file:///C:\\Users\\a\\t.dotx"/></Relationships>')
    settings = (f'<?xml version="1.0" encoding="UTF-16"?>'
                f'<w:settings xmlns:w="{W}" xmlns:r="{R}">'
                '<w:attachedTemplate r:id="rId1"/></w:settings>')
    document = (f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>'
                "<w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>")
    src = _zip(tmp / "in.docx", {
        "[Content_Types].xml": ('<?xml version="1.0"?>'
                                '<Types xmlns="http://schemas.openxmlformats.org/'
                                'package/2006/content-types">'
                                '<Default Extension="xml" ContentType="application/xml"/>'
                                "</Types>"),
        "_rels/.rels": f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}"/>',
        "word/document.xml": document,
        "word/settings.xml": settings.encode("utf-16"),
        "word/_rels/settings.xml.rels": rels.encode("utf-16"),
    })
    rows = fmt.local_path_link_rows(src)
    check("F43 a UTF-16 .rels link is found",
          len(rows) == 1 and rows[0][0] == "word/_rels/settings.xml.rels", rows)
    out = tmp / "out.docx"
    res = fmt.strip_local_path_links(src, out)
    check("F43 the local attached-template link is removed",
          res.get("ok") is True and len(res.get("removed") or []) == 1,
          str(res)[:300])
    with zipfile.ZipFile(out) as z:
        raw_rels = z.read("word/_rels/settings.xml.rels")
        raw_settings = z.read("word/settings.xml")
    check("F43 the rewritten parts keep their UTF-16 encoding",
          raw_rels[:2] == b"\xff\xfe" and raw_settings[:2] == b"\xff\xfe",
          (raw_rels[:2], raw_settings[:2]))
    check("F43 the attachedTemplate is gone",
          "attachedTemplate" not in raw_rels.decode("utf-16"))

    header = ('<w:hdr xmlns:w="%s"><w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText> ADDIN ZOTERO_ITEM CSL_CITATION '
              '{"citationID":"x"} </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              '<w:r><w:t>1</w:t></w:r>'
              '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:hdr>') % W
    check("F43 the aux-part guard sees a UTF-16 Zotero field",
          fmt._part_has_zotero_item_field(header.encode("utf-16")) is True)

    # R03: the four remaining part reads -- the template document.xml reader,
    # part_rels, figure_text_size_rows and the style-store reconcile.
    template_doc = (f'<?xml version="1.0" encoding="UTF-16"?>'
                    f'<w:document xmlns:w="{W}"><w:body>'
                    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                    '<w:r><w:t>Title</w:t></w:r></w:p>'
                    "<w:p/>"
                    '<w:p><w:r><w:t>Body</w:t></w:r></w:p>'
                    "</w:body></w:document>")
    tpl = _zip(tmp / "tpl.docx",
               {"word/document.xml": template_doc.encode("utf-16")})
    slots = fmt.empty_paragraph_slots_from_template(tpl)
    check("F43 a UTF-16 template document yields its empty-paragraph slots",
          bool(slots), slots)

    img_rel = ('<?xml version="1.0" encoding="UTF-16"?>'
               f'<Relationships xmlns="{PKG_REL}">'
               f'<Relationship Id="rId9" Type="{R}/image" '
               'Target="media/image1.png"/></Relationships>')
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
           + struct.pack(">II", 100, 100) + b"\x00" * 20)
    fig_doc = (f'<?xml version="1.0" encoding="UTF-16"?>'
               f'<w:document xmlns:w="{W}" xmlns:r="{R}" '
               'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
               'wordprocessingDrawing"><w:body><w:p><w:r><w:drawing>'
               '<wp:inline><wp:extent cx="914400" cy="914400"/>'
               '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/'
               '2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/'
               'drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.'
               'openxmlformats.org/drawingml/2006/picture"><pic:blipFill>'
               '<a:blip r:embed="rId9"/></pic:blipFill></pic:pic></a:graphicData>'
               "</a:graphic></wp:inline></w:drawing></w:r></w:p></w:body>"
               "</w:document>")
    fig = _zip(tmp / "fig.docx", {
        "word/document.xml": fig_doc.encode("utf-16"),
        "word/_rels/document.xml.rels": img_rel.encode("utf-16"),
        "word/media/image1.png": png,
    })
    with zipfile.ZipFile(fig) as z:
        rel_map = fmt.part_rels(z, "word/document.xml")
    check("F43 a UTF-16 .rels image relationship is found",
          rel_map.get("rId9") == "media/image1.png", rel_map)
    real_ocr = fmt._ocr_word_heights
    real_which = fmt.shutil.which
    fmt._ocr_word_heights = lambda data: [10, 12]
    fmt.shutil.which = lambda name: ("/usr/bin/tesseract" if name == "tesseract"
                                     else real_which(name))
    try:
        fig_rows = fmt.figure_text_size_rows(fig, {"min_figure_text_pt": 10})
    finally:
        fmt._ocr_word_heights = real_ocr
        fmt.shutil.which = real_which
    check("F43 a UTF-16 document yields its below-floor figure text row",
          bool(fig_rows) and fig_rows[0]["rule"] == "FMT-IM6", fig_rows)

    style_a = ('<?xml version="1.0" encoding="UTF-16"?>'
               f'<w:settings xmlns:w="{W}"><w:docVars>'
               '<w:docVar w:name="ZOTERO_STYLE" '
               'w:val="https://www.zotero.org/styles/apa"/>'
               "</w:docVars></w:settings>")
    style_b = ('<?xml version="1.0" encoding="UTF-16"?>'
               '<Properties xmlns="http://schemas.openxmlformats.org/'
               'officeDocument/2006/custom-properties">'
               '<property name="ZOTERO_STYLE"><vt:lpwstr xmlns:vt="http://'
               'schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
               "https://www.zotero.org/styles/chicago-author-date"
               "</vt:lpwstr></property></Properties>")
    style_info = fmt.zotero_style_reconcile({
        "word/settings.xml": style_a.encode("utf-16"),
        "docProps/custom.xml": style_b.encode("utf-16")})
    check("F43 a UTF-16 style store is reconciled",
          style_info.get("changed") is True, str(style_info)[:300])
    rewritten = (style_info.get("parts") or {}).get("word/settings.xml") or b""
    check("F43 the rewritten UTF-16 style store keeps its encoding",
          rewritten[:2] == b"\xff\xfe"
          and "chicago-author-date" in rewritten.decode("utf-16"), rewritten[:2])


# ---------------------------------------------------------------------------
# F44 -- a zero-length insertion anchored at a break is written
# ---------------------------------------------------------------------------
def test_f44_zero_length_at_break() -> None:
    print("\n== F44: an insertion anchored at a break/non-text piece is emitted ==")
    cases = [
        (f'<w:p xmlns:w="{W}"><w:r><w:br/></w:r>'
         "<w:r><w:t>def</w:t></w:r></w:p>", "X\ndef"),
        (f'<w:p xmlns:w="{W}"><w:r><w:noBreakHyphen/></w:r>'
         "<w:r><w:t>ab</w:t></w:r></w:p>", "Y-ab"),
    ]
    for para, expected in cases:
        new, applied = fmt.rewrite_text_spans(para, [(0, 0, expected[0])])
        check(f"F44 insertion at offset 0 writes {expected!r}",
              fmt.text_of(new) == expected and applied == [(0, 0, "", expected[0])],
              (repr(fmt.text_of(new)), applied))
    trailing = (f'<w:p xmlns:w="{W}"><w:r><w:t>ab</w:t></w:r>'
                "<w:r><w:br/></w:r></w:p>")
    new, applied = fmt.rewrite_text_spans(trailing, [(3, 3, "Z")])
    check("F44 an insertion after a final break is still written",
          fmt.text_of(new) == "ab\nZ" and applied == [(3, 3, "", "Z")],
          repr(fmt.text_of(new)))


# ---------------------------------------------------------------------------
# F45 -- every break-separated repeat of a tripled word is deleted
# ---------------------------------------------------------------------------
def test_f45_tripled_word_across_breaks() -> None:
    print("\n== F45: FMT-G1 deletes every repeat, keeping the breaks ==")
    def para(parts: list) -> str:
        out = [f'<w:p xmlns:w="{W}">']
        for piece in parts:
            out.append("<w:r><w:br/></w:r>" if piece == "br"
                       else f'<w:r><w:t xml:space="preserve">{piece}</w:t></w:r>')
        return "".join(out) + "</w:p>"
    p = para(["the", "br", "the", "br", "the"])
    spans = [s for s in fmt.hygiene_spans(p) if s["rule"] == "FMT-G1"]
    check("F45 one deletion per repeat is emitted", len(spans) == 2,
          [(s["start"], s["end"]) for s in spans])
    new, applied = fmt.rewrite_text_spans(
        p, [(s["start"], s["end"], s["repl"]) for s in spans])
    remaining = [s for s in fmt.hygiene_spans(new) if s["rule"] == "FMT-G1"]
    check("F45 the rescan files no FMT-G1", remaining == [], remaining)
    check("F45 both line breaks survive",
          new.count("<w:br/>") == 2, new.count("<w:br/>"))


# ---------------------------------------------------------------------------
# F46 -- a tracked-deletion paragraph is not a stray empty paragraph
# ---------------------------------------------------------------------------
def test_f46_tracked_deletion() -> None:
    print("\n== F46: a paragraph carrying a tracked change is never deleted ==")
    heading = (f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
               "<w:r><w:t>%s</w:t></w:r></w:p>")
    deleted = (f'<w:p xmlns:w="{W}"><w:pPr><w:rPr>'
               '<w:del w:id="1" w:author="a" '
               'w:date="2026-01-01T00:00:00Z"/></w:rPr></w:pPr>'
               "<w:r><w:delText>Old sentence that was deleted.</w:delText>"
               "</w:r></w:p>")
    xml = "<w:body>" + heading % "Intro" + deleted + heading % "Methods" + "</w:body>"
    paras = fmt.paragraphs(xml)
    groups, _prescribed = fmt.stray_empty_paragraph_groups(
        paras, {"max_empty_paragraph_run": 1}, xml)
    check("F46 the tracked deletion is not in a delete group", groups == [], groups)
    check("F46 its delText is still in the paragraph",
          "delText" in paras[1][2])


# ---------------------------------------------------------------------------
# F47 -- a caption binds to the adjacent image, not across an intervening one
# ---------------------------------------------------------------------------
def test_f47_adjacent_images() -> None:
    print("\n== F47: a caption cannot skip an intervening image ==")
    image = (f'<w:p xmlns:w="{W}"><w:r><w:drawing>'
             '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/'
             '2006/wordprocessingDrawing"><wp:extent cx="100" cy="100"/>'
             "</wp:inline></w:drawing></w:r></w:p>")
    caption = f'<w:p xmlns:w="{W}"><w:r><w:t>Figure 2 | Second legend.</w:t></w:r></w:p>'
    xml = "<w:body>" + image + image + caption + "</w:body>"
    rows, inv = fmt.figure_conformance_rows(
        xml, {"figures": {"placement": "inline", "caption": "after", "source": "x"}},
        "main.docx")
    check("F47 the legend binds to the second image",
          [(e["caption"], e["caption_side"]) for e in inv]
          == [("", ""), ("Figure 2 | Second legend.", "after")],
          [(e["index"], e["caption"]) for e in inv])
    check("F47 the remaining no-caption row names figure 1, not figure 2",
          rows and all("figure 1" in r["location"] for r in rows),
          [r["location"] for r in rows])


# ---------------------------------------------------------------------------
# F49 -- an entry inside a live field is protected and never repaired
# ---------------------------------------------------------------------------
def test_f49_live_field_reference() -> None:
    print("\n== F49: a live-field reference entry is protected and skipped ==")
    entry = "1. Smith J. A title. Front. Genet. Volume 11-2020."
    plain = fmt.reference_entry_rows([entry], [True])
    check("F49 an ordinary entry is not protected",
          plain and plain[0]["protected"] is False
          and "fix" not in plain[0], plain[:1])
    in_field = fmt.reference_entry_rows([entry], [True], field_ranges=[[(0, len(entry))]])
    check("F49 a field-result entry is protected / style-field",
          in_field and in_field[0]["protected"] is True
          and in_field[0].get("fix") == "style-field", in_field[:1])
    xml = _doc(_p("Main")
               + '<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
               '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
               '<w:r><w:instrText>ADDIN ZOTERO_BIBL {}</w:instrText></w:r>'
               '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
               f'<w:r><w:t>{entry}</w:t></w:r></w:p>'
               '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    recs = [{"key": "s", "type": "article", "title": "A title",
             "first_family": "Smith", "year": "2020",
             "journal": "Frontiers in Genetics", "volume": "11", "pages": "565825",
             "doi": "", "eprint": "", "eprinttype": "", "url": "", "file": "x.bib"}]
    res = fmt.repair_reference_entries(xml, recs)
    check("F49 repair_reference_entries leaves the live-field result alone",
          res["changed"] is False and res["xml"] == xml, str(res)[:300])
    check("F49 the skip names the live field result",
          any("live Zotero field result" in s for s in res["skipped"]),
          res["skipped"])


# ---------------------------------------------------------------------------
# F50 -- both strip helpers honour the DOCX zip budget
# ---------------------------------------------------------------------------
def test_f50_zip_budget() -> None:
    print("\n== F50: the strip helpers refuse an over-budget package ==")
    tmp = scratch("fb1115w2_zipbomb_")
    path = tmp / "bomb.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", "<w:document/>")
    data = bytearray(path.read_bytes())
    cd = data.find(b"PK\x01\x02")
    check("F50 fixture: central directory found", cd >= 0)
    if cd >= 0:
        # Central-directory uncompressed size lives at +24.
        struct.pack_into("<I", data, cd + 24, 100 * 1024 * 1024)
        path.write_bytes(data)
    ref = fmt.strip_reference_sentences(path, tmp / "o1.docx", lambda _t: [])
    check("F50 strip_reference_sentences refuses the over-budget part",
          ref.get("ok") is False and "limit" in str(ref.get("error")),
          str(ref.get("error"))[:200])
    loc = fmt.strip_local_path_links(path, tmp / "o2.docx")
    check("F50 strip_local_path_links refuses the over-budget part",
          loc.get("ok") is False and "limit" in str(loc.get("error")),
          str(loc.get("error"))[:200])


def main() -> int:
    print("== 2026-11-15 fix-bugs wave 2, docx_layout regression checks ==")
    test_f36_line_spans()
    test_f38_duplicate_citation_items()
    test_f39_split_number_run()
    test_f40_split_instr_text()
    test_f41_bookmark_between_entries()
    test_f42_r1_locator()
    test_f43_utf16_parts()
    test_f44_zero_length_at_break()
    test_f45_tripled_word_across_breaks()
    test_f46_tracked_deletion()
    test_f47_adjacent_images()
    test_f49_live_field_reference()
    test_f50_zip_budget()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

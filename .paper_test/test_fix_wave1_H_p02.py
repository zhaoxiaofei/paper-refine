#!/usr/bin/env python3
"""Regressions for fix-bugs wave 1, batch H_p02 (F05/F21/F22/F56/F74/F92/F112/F132/F167/F200).

Every check fails on the pre-wave tree and passes after the smallest fix.
Hermetic: temporary directories only, no network, no Word.
Run: python3 .paper_test/test_fix_wave1_H_p02.py
"""
from __future__ import annotations

import html
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import paper_docx_format as fmt                                        # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FAILS = []
EXACT = dict(fmt.POLICY_DEFAULTS, image_aspect_tolerance=0)


def check(label, cond, detail=""):
    print(("[ok ] " if cond else "[FAIL] ") + label
          + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(label)


def _p(text, close="</w:p>"):
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r>{close}'


def _doc(body):
    return f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'


def _texts(xml):
    return [fmt.text_of(p[2]) for p in fmt.paragraphs(xml)]


# ---- Zotero fixtures -----------------------------------------------------
ITEMS = {"K1": {"title": "Alpha diversity in single cells", "family": "Alvarez", "year": 2020},
         "K2": {"title": "Beta catenin signalling atlas", "family": "Bianchi", "year": 2021}}
K1 = "Alvarez, A. et al. Alpha diversity in single cells. Journal 1, 1-9 (2020)."
K2 = "Bianchi, B. et al. Beta catenin signalling atlas. Journal 2, 1-9 (2021)."
BIB_OPEN = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText>ADDIN ZOTERO_BIBL {}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
END = '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'


def _field(cid, marker, keys, visible, tclose="</w:t>", iclose="</w:instrText>"):
    payload = {"citationID": cid, "properties": {"formattedCitation": marker,
                                                "plainCitation": visible, "noteIndex": 0},
               "citationItems": [{"id": k + "/1",
                                  "uris": [f"http://zotero.org/users/local/AAA/items/{k}"],
                                  "itemData": {"title": ITEMS[k]["title"],
                                               "author": [{"family": ITEMS[k]["family"]}],
                                               "issued": {"date-parts": [[ITEMS[k]["year"]]]}}}
                                 for k in keys],
               "schema": "https://github.com/citation-style-language/schema/raw/master/csl-citation.json"}
    instr = html.escape("ADDIN ZOTERO_ITEM CSL_CITATION "
                        + json.dumps(payload, ensure_ascii=False), quote=False)
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{instr}{iclose}</w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t xml:space="preserve">{visible}{tclose}</w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def _bib(number, text, close="</w:t>"):
    return ('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>' + BIB_OPEN
            + f'<w:r><w:t>{number}{close}</w:r>'
            '<w:r><w:tab/><w:t xml:space="preserve">' + text + "</w:t></w:r></w:p>")


def _split_runs(a, b, text):
    return ('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
            + f'<w:r><w:t>{a}</w:t></w:r><w:r><w:t>{b}</w:t></w:r>'
            '<w:r><w:tab/><w:t xml:space="preserve">' + text + "</w:t></w:r></w:p>")


# ---- F56/F74: FMT-CL1 single-quoted pStyle; whitespace-closed caption ----
def test_f56_f74():
    def cover(style_el):
        path = Path(tempfile.mkdtemp()) / "cover_letter.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", _doc(
                f'<w:p>{style_el}<w:r><w:t>Hello</w:t></w:r></w:p>'))
        return path
    policy = {"cover_letter": {"manuscript_front_matter_styles": ["TitleMSS"],
                               "manuscript_article_type_names": ["research-article"]}}
    for label, pstyle in (("double", '<w:pStyle w:val="TitleMSS"/>'),
                          ("single", "<w:pStyle w:val='TitleMSS'/>")):
        rows = fmt.cover_letter_stamp_rows(cover(f"<w:pPr>{pstyle}</w:pPr>"), policy)
        check(f"F56 {label}-quoted pStyle files FMT-CL1",
              [r["rule"] for r in rows] == ["FMT-CL1"], rows)
    cont = _p(" continues.")
    for label, close in (("canonical", "</w:p>"), ("whitespace", "</w:p >")):
        lab = _p("Figure 1. A caption", close)
        block = [(0, len(lab), lab), (len(lab), len(lab) + len(cont), cont)]
        check(f"F74 {label}-closed caption paragraph is mergeable",
              fmt._caption_para_split(lab) is not None
              and fmt.caption_block_mergeable(block) is True)


# ---- F112: a nested self-closing <w:p/> does not swallow body blocks ----
def test_f112():
    first = ('<w:p><w:r><w:t>First</w:t></w:r>'
             '<w:r><w:txbxContent><w:p/></w:txbxContent></w:r></w:p>')
    body = '<w:body>' + first + '<w:p><w:r><w:t>Second</w:t></w:r></w:p></w:body>'
    blocks = [(t, fmt.text_of(frag)) for t, _s, _e, frag in fmt.body_block_spans(body)]
    check("F112 a text-box <w:p/> still yields two body paragraphs",
          blocks == [("p", "First"), ("p", "Second")], blocks)


# ---- F132/F167/F05: single-quoted VML style, SVG viewBox, a:srcRect ----
def test_geometry_quotes():
    rels, sizes = {"rId9": "word/media/img1.png"}, {"word/media/img1.png": (300, 200)}
    art = ("<w:p><w:r><w:pict><v:shape style='width:10pt;height:10pt'>"
           "<v:imagedata r:id='rId9'/></v:shape></w:pict></w:r></w:p>")
    rows, fixes = fmt.drawing_geometry_rows(art, rels, sizes, "d.docx", EXACT)
    fixed = fmt.apply_edits(art, fixes)
    check("F132 single-quoted VML geometry files FMT-IM1 and repairs",
          [r["rule"] for r in rows] == ["FMT-IM1"] and len(fixes) == 1
          and "height:6.666666666666667pt" in fixed, (rows, fixes))
    for label, svg in (("double", b'<svg viewBox="0 0 100 50"></svg>'),
                       ("single", b"<svg viewBox='0 0 100 50'></svg>")):
        check(f"F167 {label}-quoted SVG viewBox",
              fmt.image_pixel_size(svg) == (100.0, 50.0))

    def drawing(rect):
        return ('<w:p><w:r><w:drawing><wp:inline><wp:extent cx="457200" cy="914400"/>'
                '<a:graphic><a:graphicData><pic:pic><pic:blipFill>'
                '<a:blip r:embed="rId7"/><a:srcRect ' + rect + '/></pic:blipFill>'
                '<pic:spPr><a:xfrm><a:ext cx="457200" cy="914400"/></a:xfrm></pic:spPr>'
                '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    rels7 = {"rId7": "word/media/image1.png"}
    sizes7 = {"word/media/image1.png": (1000, 1000)}
    for label, rect in (("double", 'l="50000" r="0" t="0" b="0"'),
                        ("single", "l='50000' r='0' t='0' b='0'")):
        rows, fixes = fmt.drawing_geometry_rows(drawing(rect), rels7, sizes7,
                                                "d.docx", EXACT)
        check(f"F05 {label}-quoted 50% crop keeps its aspect ratio",
              rows == [] and fixes == [], (rows, fixes))


# ---- F21/F22/F92/F200: legal quote/whitespace spellings in Zotero XML ---
def test_zotero_spellings():
    out = fmt._zotero_renumber_run('<w:r><w:rPr><w:b/></w:rPr><w:t>5.</w:t ></w:r>', 1)
    check("F22 a whitespace-closed w:t is renumbered", fmt.text_of(out) == "1.", out)
    split = '<w:r><w:t>1</w:t></w:r><w:r><w:t>0. Smith A study.</w:t></w:r>'
    span = fmt._zotero_entry_span_of_run(split)
    check("F21 a number split across runs reads as 10",
          span is not None and span[2] == 10, span)
    check("F21 renumbering that group keeps the entry text",
          span is not None
          and fmt.text_of(fmt._zotero_renumber_run(split[span[0]:span[1]], 2))
          == "2. Smith A study.")
    xml = _doc(_p("Main") + _field("cA", r"\super 1\nosupersub{}", ["K1"], "1")
               + _field("cB", r"\super 2\nosupersub{}", ["K2"], "2") + _p("References")
               + _bib("1", K1) + _split_runs("1", "0. ", K2) + END)
    res = fmt.zotero_refresh_document(xml, _texts(xml))
    after = _texts(res["xml"])
    bianchi = [t for t in after if "Bianchi" in t]
    check("F21 the split entry is not rewritten as 20.",
          res["changed"] is True and not res.get("skip") and bianchi
          and bianchi[0].startswith("2.")
          and not any(t.startswith("20.") for t in after), (res.get("skip"), bianchi))
    for label, kw, kind in (("F92", {"tclose": "</w:t >"}, "result run"),
                            ("F200", {"iclose": "</w:instrText >"}, "instrText")):
        xml = _doc(_p("Main") + _field("cA", r"\super 5\nosupersub{}", ["K1"], "5", **kw)
                   + _p("References") + _bib("1", K1) + END)
        res = fmt.zotero_refresh_document(xml, _texts(xml))
        check(f"{label} a whitespace-closed {kind} refreshes",
              res["changed"] is True and not res.get("skip"), repr(res.get("skip")))


def main() -> int:
    for fn in (test_f56_f74, test_f112, test_geometry_quotes, test_zotero_spellings):
        fn()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

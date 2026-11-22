#!/usr/bin/env python3
"""Regression tests for fix-bugs wave 1, batch G_p03rcli (report/format CLI).

Run: conda run -n paper-refine-test python .paper_test/test_fix_wave1_G_p03rcli.py
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(WS))
import paper_docx_format as df  # noqa: E402

FAILS, TMPDIRS = [], []
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
CT = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/'
      '2006/content-types"/>')
RELS = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships"/>')


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch() -> Path:
    d = Path(tempfile.mkdtemp(prefix="fix_G_"))
    TMPDIRS.append(d)
    return d


def build(path: Path, parts: dict) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)


def package(docx: str, sty: str, extra: dict = None) -> dict:
    parts = {"[Content_Types].xml": CT, "word/document.xml": docx,
             "word/styles.xml": sty, "word/_rels/document.xml.rels": RELS}
    parts.update(extra or {})
    return parts


def document(body: str) -> str:
    return f'<w:document {W}><w:body>{body}</w:body></w:document>'


def styles(extra: str = "") -> str:
    return (f'<w:styles {W}><w:style w:type="paragraph" w:styleId="Normal">'
            '<w:name w:val="Normal"/></w:style>' + extra + '</w:styles>')


def apply(src_parts: dict, tpl_parts: dict):
    tmp = scratch()
    src, tpl, out = tmp / "s.docx", tmp / "t.docx", tmp / "o.docx"
    build(src, src_parts)
    build(tpl, tpl_parts)
    with contextlib.redirect_stderr(io.StringIO()):
        res = df.apply_word_template(src, out, tpl)
    return res, out


def base_parts(body: str, extra: dict = None) -> dict:
    return package(document(body), styles(), extra)


def rules(xml: str) -> list:
    return [r["rule"] for r in
            df.analyse_document(xml, {}, df.POLICY_DEFAULTS, "d.docx")["rows"]]


def test_f08() -> None:
    print("\n== F08 single-quoted w:numId ==")
    num = ('<w:numbering %s><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0">'
           '%s</w:lvl></w:abstractNum><w:num w:numId="%s">'
           '<w:abstractNumId w:val="0"/></w:num></w:numbering>')
    src = base_parts('<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/>'
                     "<w:numId w:val='5'/></w:numPr></w:pPr>"
                     '<w:r><w:t>list item text</w:t></w:r></w:p>',
                     {"word/numbering.xml": num % (W, '<w:numFmt w:val="decimal"/>', "5")})
    tpl = base_parts('<w:p><w:r><w:t>t</w:t></w:r></w:p>',
                     {"word/numbering.xml": num % (W, '<w:numFmt w:val="bullet"/>', "1")})
    res, out = apply(src, tpl)
    with zipfile.ZipFile(out) as z:
        dx, nx = (z.read("word/document.xml").decode(),
                  z.read("word/numbering.xml").decode())
    check("F08 the list definition is carried and the reference remapped",
          res.get("ok") is True and "w:numId w:val='5'" not in dx
          and "w:numId w:val='6'" in dx and 'w:numId="6"' in nx,
          f"ok={res.get('ok')} doc={dx[-140:]}")


def test_f26() -> None:
    print("\n== F26 whitespace-closed template styles part ==")
    src = base_parts('<w:p><w:pPr><w:pStyle w:val="Quote2"/></w:pPr>'
                     '<w:r><w:t>quoted</w:t></w:r></w:p>')
    src["word/styles.xml"] = styles(
        '<w:style w:type="paragraph" w:styleId="Quote2">'
        '<w:name w:val="Quote 2"/></w:style>')
    for close in ("</w:styles>", "</w:styles >"):
        res, out = apply(src, package(document('<w:p><w:r><w:t>t</w:t></w:r></w:p>'),
                                      styles().replace("</w:styles>", close)))
        with zipfile.ZipFile(out) as z:
            sx = z.read("word/styles.xml").decode()
        check(f"F26 manuscript-only style kept (close={close!r})",
              res.get("ok") is True and 'w:styleId="Quote2"' in sx, sx[-110:])


def test_f52() -> None:
    print("\n== F52 footer prose closed with `</w:t >` ==")
    tdoc = (f'<w:document {W} {NS_R}><w:body><w:p><w:r><w:t>t</w:t></w:r></w:p>'
            '<w:sectPr><w:footerReference w:type="even" r:id="rId7"/></w:sectPr>'
            '</w:body></w:document>')
    trels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
             'relationships"><Relationship Id="rId7" Type="http://schemas.openxmlformats.'
             'org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
             '</Relationships>')
    page = '<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
    for tclose in ("</w:t>", "</w:t >"):     # both spellings carry the template prose
        tmp = scratch()
        build(tmp / "t.docx", {"[Content_Types].xml": CT, "word/document.xml": tdoc,
                               "word/_rels/document.xml.rels": trels,
                               "word/footer1.xml": (
                                   f'<w:ftr {W}><w:p><w:r>{page}<w:t>Typeset by the '
                                   f'journal office{tclose}</w:r></w:p></w:ftr>')})
        parts = {"[Content_Types].xml": CT.encode(), "word/document.xml": tdoc.encode(),
                 "word/_rels/document.xml.rels": RELS.encode()}
        with zipfile.ZipFile(tmp / "t.docx") as tpkg:
            out = df._template_front_parts(tpkg, parts, set(tpkg.namelist()))
        copied = parts.get("word/footer_venue_even.xml", b"").decode()
        check(f"F52 prose footer is replaced (close={tclose!r})",
              out.get("footer_replaced") == ["even"] and "Typeset by" not in copied,
              copied[-100:])


def test_f57_f58() -> None:
    print("\n== F57/F58 live revision and tab counters ==")
    commented = document('<w:p><w:r><w:t>clean body text</w:t></w:r></w:p>'
                         '<!-- <w:ins w:id="1"/><w:proofErr w:type="spellStart"/> -->')
    check("F57 a commented-out w:ins/w:proofErr is not a live revision mark",
          "FMT-S4" not in rules(commented) and "FMT-S5" not in rules(commented))
    live = document('<w:p><w:r><w:del w:id="1" w:author="A">'
                    '<w:rPr/><w:delText>old</w:delText></w:del></w:r></w:p>')
    check("F57 a live tracked deletion is still reported", "FMT-S4" in rules(live),
          repr(rules(live)))
    tabs = document('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/>'
                    '</w:tabs ></w:pPr><w:r><w:t>hello</w:t><w:tab/>'
                    '<w:t>world</w:t></w:r></w:p>')
    check("F58 a run tab after `</w:tabs >` is counted", "FMT-S7" in rules(tabs),
          repr(rules(tabs)))


def test_f130() -> None:
    print("\n== F130 whitespace-closed run enumerators ==")
    long_p = ('<w:p><w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>'
              + "word " * 30 + "</w:t></w:r></w:p>")
    for close in ("</w:r>", "</w:r >"):
        heading = ('<w:p><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr>'
                   f'<w:t>Results</w:t>{close}</w:p>')
        got = [h[1] for h in df.heading_like_paragraphs(long_p + heading)]
        check(f"F130 heading run detected (run close={close!r})", got == ["Results"],
              repr(got))


def test_f136() -> None:
    print("\n== F136 post-write verifier coverage ==")
    tdoc = (f'<w:document {W} {NS_R}><w:body><w:p><w:r><w:t>t</w:t></w:r></w:p>'
            '<w:sectPr><w:footerReference w:type="default" r:id="rId9"/></w:sectPr>'
            '</w:body></w:document>')
    trels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
             'relationships"><Relationship Id="rId9" Type="http://schemas.openxmlformats.'
             'org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
             '</Relationships>')
    res, _out = apply(base_parts('<w:p><w:r><w:t>body</w:t></w:r></w:p>'),
                      package(tdoc, styles(), {
                          "word/_rels/document.xml.rels": trels,
                          "word/footer1.xml":
                              f'<w:ftr {W}><w:p><w:r><w:t>X</w:t></w:r></w:ftr>'}))
    check("F136 a malformed copied footer fails verification",
          res.get("ok") is False and "verification failed" in str(res.get("error")),
          str(res.get("error"))[:90])


def test_f202_f203_f205() -> None:
    print("\n== F202/F203/F205 quote-agnostic readers ==")
    tpl = scratch() / "t.docx"
    tdoc = document('<w:p><w:pPr><w:pStyle w:val=\'Heading1\'/></w:pPr>'
                    '<w:r><w:t>A</w:t></w:r></w:p>'
                    '<w:p><w:pPr><w:pStyle w:val=\'Heading1\'/></w:pPr>'
                    '<w:r><w:t>B</w:t></w:r></w:p>')
    build(tpl, package(tdoc, f'<w:styles {W}><w:style w:type="paragraph" '
                             'w:styleId="Heading1"><w:name w:val="heading 1"/>'
                             '</w:style></w:styles>'))
    depth = df.template_style_roles(tpl).get("max_heading_level")
    check("F202 a single-quoted w:pStyle contributes to the heading depth",
          depth == 1, repr(depth))
    cell = ("<w:tc><w:p><w:pPr><w:pStyle w:val='MyCell'/></w:pPr>"
            "<w:r><w:t>x</w:t></w:r></w:p></w:tc>")
    sz = df._cell_font_pt({"MyCell": {"sz": "24", "basedOn": None}}, cell)
    check("F203 a single-quoted cell pStyle resolves the style size", sz == 12.0, repr(sz))
    page = '<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
    footer = ('<w:ftr ' + W + '><w:p><w:r>' + page + '</w:r></w:p>'
              '<w:txbxContent><w:p><w:r>' + page + '</w:r></w:p></w:txbxContent >'
              '<w:p><w:r>' + page + '</w:r></w:p></w:ftr>')
    rows = df.page_field_rows([("word/footer1.xml", footer)], "d.docx")
    check("F205 a whitespace-closed text box is counted",
          bool(rows) and "1 of them sit in a floating text box" in rows[0]["evidence"],
          rows[0]["evidence"] if rows else "(no row)")


def main() -> int:
    try:
        test_f08(); test_f26(); test_f52(); test_f57_f58(); test_f130()
        test_f136(); test_f202_f203_f205()
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

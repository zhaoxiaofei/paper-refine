#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group G3 (run 20261115-220228).

Each check pins one re-validated candidate from the verified findings set:
DOCX/PDF template and formatting helpers (UTF-16 codecs, style ids, front
matter, report writers, PDF inspectors). Hermetic: temporary directories only,
no network, no Word; the `.tex` check is skipped when no TeX engine is on PATH.

Run:  python3 -B .paper_test/test_wave2_G3.py
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_docx_format as f          # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def doc(body, ns=True):
    nsattr = f' xmlns:w="{W}"' if ns else ""
    return (f'<w:document{nsattr} xmlns:r="{R}"><w:body>{body}</w:body></w:document>')


def styles_xml(extra=""):
    return (f'<w:styles xmlns:w="{W}">'
            '<w:style w:type="paragraph" w:styleId="Normal">'
            '<w:name w:val="Normal"/></w:style>' + extra + "</w:styles>")


def style(sid, name, typ="paragraph"):
    return (f'<w:style w:type="{typ}" w:styleId="{sid}">'
            f'<w:name w:val="{name}"/></w:style>')


def make_docx(path: Path, document: str, styles: str = None, extra: dict = None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles or styles_xml())
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def read_part(path: Path, name: str):
    with zipfile.ZipFile(path) as z:
        return z.read(name)


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


# ---------------------------------------------------------------------------
# C019 -- a legal UTF-16 settings.xml keeps its encoding when parity is added
# ---------------------------------------------------------------------------
def test_c019_utf16_settings() -> None:
    print("\n== C019: _with_even_odd_headers keeps a UTF-16 settings part legal ==")
    import xml.etree.ElementTree as ET
    settings = ('<?xml version="1.0" encoding="UTF-16" standalone="yes"?>'
                f'<w:settings xmlns:w="{W}"><w:characterSpacingControl '
                'w:val="doNotCompress"/></w:settings>').encode("utf-16")
    parts = {"word/settings.xml": settings,
             "word/_rels/document.xml.rels": b"<Relationships/>",
             "[Content_Types].xml": b"<Types/>"}
    added = f._with_even_odd_headers(parts)
    out = parts["word/settings.xml"]
    try:
        ET.fromstring(out)
        parses = True
        detail = ""
    except ET.ParseError as e:
        parses = False
        detail = str(e)
    check("C019 the rewritten UTF-16 settings part still parses", added and parses, detail)
    check("C019 the parity element was really inserted",
          f.is_on(f.ooxml_part_text(out), "evenAndOddHeaders"), out[:24])


# ---------------------------------------------------------------------------
# C020 -- the TEMPLATE's styles.xml is refused before any ET.parse
# ---------------------------------------------------------------------------
def test_c020_template_entity_guard() -> None:
    print("\n== C020: an untrusted template's DTD is refused before parsing ==")
    td = scratch("g3_c020_")
    try:
        src, out, tpl = td / "s.docx", td / "o.docx", td / "t.docx"
        make_docx(src, doc('<w:p><w:r><w:t>Body</w:t></w:r></w:p>'))
        bad_styles = ('<?xml version="1.0"?><!DOCTYPE w:styles '
                      '[<!ENTITY e "ExpandedName">]>'
                      f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" '
                      'w:styleId="S"><w:name w:val="&e;"/></w:style></w:styles>')
        make_docx(tpl, doc("<w:p/>"), styles=bad_styles)
        seen = []
        orig = f._style_index

        def spy(text):
            seen.append(text)
            return orig(text)

        f._style_index = spy
        try:
            res = f.apply_word_template(src, out, tpl)
        finally:
            f._style_index = orig
        check("C020 the DTD template is refused", res.get("ok") is False,
              str(res.get("error"))[:160])
        check("C020 the entity-bearing styles never reach _style_index",
              not any("<!DOCTYPE" in s for s in seen), f"{len(seen)} call(s)")
        check("C020 the refusal names the part and the declaration",
              "word/styles.xml" in str(res.get("error") or "")
              and "DTD/entity" in str(res.get("error") or ""), str(res.get("error")))
        check("C020 no output package is written", not out.exists())
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C021 -- fix_package publishes a parseable UTF-16 main part
# ---------------------------------------------------------------------------
def test_c021_utf16_fix_package() -> None:
    print("\n== C021: fix_package keeps the main part's UTF-16 encoding ==")
    import xml.etree.ElementTree as ET
    td = scratch("g3_c021_")
    try:
        src, out = td / "s.docx", td / "o.docx"
        body = ('<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
                '<w:p><w:r><w:t>Hello world.</w:t></w:r></w:p>')
        payload = ('<?xml version="1.0" encoding="UTF-16" standalone="yes"?>'
                   + doc(body).replace(' xmlns:r="' + R + '"', "")).encode("utf-16")
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", payload)
        rep = f.fix_package(src, out, dict(f.POLICY_DEFAULTS))
        raw = read_part(out, "word/document.xml")
        try:
            ET.fromstring(raw)
            parses = True
            detail = ""
        except ET.ParseError as e:
            parses = False
            detail = f"{e} :: {raw[:24]!r}"
        check("C021 the fixed package reports success", rep.get("ok") is True,
              str(rep.get("error"))[:160])
        check("C021 the PUBLISHED bytes parse (declaration matches encoding)",
              parses, detail)
        check("C021 the rewritten part keeps its BOM/UTF-16 form",
              raw[:2] in (b"\xff\xfe", b"\xfe\xff"), repr(raw[:8]))
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C071 -- a template with only a footer keeps the manuscript's running head
# ---------------------------------------------------------------------------
def test_c071_keep_undefined_header_role() -> None:
    print("\n== C071: _apply_front_refs keeps source refs the template lacks ==")
    td = scratch("g3_c071_")
    try:
        src, out, tpl = td / "s.docx", td / "o.docx", td / "t.docx"
        sdoc = (f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>'
                '<w:p><w:r><w:t>Body</w:t></w:r></w:p>'
                '<w:sectPr><w:headerReference w:type="default" r:id="rIdH"/>'
                '</w:sectPr></w:body></w:document>')
        srels = (f'<Relationships><Relationship Id="rIdH" Type="{R}/header" '
                 'Target="header1.xml"/></Relationships>')
        make_docx(src, sdoc, extra={
            "word/_rels/document.xml.rels": srels,
            "word/header1.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r>'
                                '<w:t>SOURCEHEAD</w:t></w:r></w:p></w:hdr>'})
        tdoc = (f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>'
                '<w:p><w:r><w:t>T</w:t></w:r></w:p>'
                '<w:sectPr><w:footerReference w:type="default" r:id="rIdF"/>'
                '</w:sectPr></w:body></w:document>')
        trels = (f'<Relationships><Relationship Id="rIdF" Type="{R}/footer" '
                 'Target="footer1.xml"/></Relationships>')
        make_docx(tpl, tdoc, extra={
            "word/_rels/document.xml.rels": trels,
            "word/footer1.xml": f'<w:ftr xmlns:w="{W}"><w:p><w:fldSimple '
                                'w:instr=" PAGE "><w:r><w:t>1</w:t></w:r>'
                                '</w:fldSimple></w:p></w:ftr>'})
        res = f.apply_word_template(src, out, tpl)
        od = read_part(out, "word/document.xml").decode("utf-8", "replace")
        check("C071 apply succeeds and the text is unchanged",
              res.get("ok") is True and res.get("text_unchanged") is True,
              str(res.get("error"))[:160])
        check("C071 the source default header reference survives", 'rIdH' in od, od[:400])
        check("C071 the template footer is still applied",
              "footerReference" in od, od[:400])
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C072 -- a bare Keywords heading does not leak its style onto the Abstract body
# ---------------------------------------------------------------------------
def test_c072_keywords_pending() -> None:
    print("\n== C072: _front_matter_styles clears a stale Keywords pending state ==")

    def p(t, sid=None):
        ppr = f'<w:pPr><w:pStyle w:val="{sid}"/></w:pPr>' if sid else ""
        return f'<w:p>{ppr}<w:r><w:t>{t}</w:t></w:r></w:p>'

    def styles_of(xml):
        rows = []
        for m in re.finditer(r"<w:p>(.*?)</w:p>", xml):
            sid_m = re.search(r'<w:pStyle w:val="([^"]+)"', m.group(1))
            rows.append(["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", m.group(1))),
                         sid_m.group(1) if sid_m else None])
        return rows

    roles = {"title": "Title", "author": "AuthorList",
             "headings": {1: "Heading1"}, "max_heading_level": 2}
    body = (p("A title about cells") + p("Alice Smith, Bob Jones")
            + p("Keywords") + p("Abstract")
            + p("The abstract body describes the study and must keep its own style."))
    out, info = f._front_matter_styles(doc(body), roles, "")
    got = dict(styles_of(out))
    check("C072 the abstract body is not restyled as front matter",
          got.get("The abstract body describes the study and must keep its own style.")
          is None, str(styles_of(out)))
    check("C072 no keyword list is reported", info.get("keywords") is False, str(info))

    good = (p("A title") + p("Alice Smith, Bob Jones") + p("Keywords")
            + p("cell, assay, beta") + p("Body paragraph here."))
    out2, info2 = f._front_matter_styles(doc(good), roles, "")
    got2 = dict(styles_of(out2))
    check("C072 a real keyword list under the heading is still styled",
          got2.get("cell, assay, beta") == "AuthorList" and info2.get("keywords") is True,
          str(styles_of(out2)))


# ---------------------------------------------------------------------------
# C073 -- style ids are XML-escaped when spliced into attributes
# ---------------------------------------------------------------------------
def test_c073_style_id_escaping() -> None:
    print("\n== C073: _set_para_style / _remap_style_refs escape style ids ==")
    import xml.etree.ElementTree as ET
    ok = True
    detail = ""
    for sid in ('A"B', "A&B"):
        got = f._set_para_style("<w:p><w:r><w:t>x</w:t></w:r></w:p>", sid)
        try:
            ET.fromstring(f'<w:document xmlns:w="{W}"><w:body>{got}</w:body></w:document>')
        except ET.ParseError as e:
            ok = False
            detail = f"{sid}: {e}"
    check("C073 an unusual style id yields well-formed XML", ok, detail)
    remapped, n = f._remap_style_refs(
        '<w:p><w:pPr><w:pStyle w:val="X"/></w:pPr></w:p>', {"X": "A&B"})
    check("C073 _remap_style_refs escapes its target id",
          n == 1 and 'w:val="A&amp;B"' in remapped, remapped)


# ---------------------------------------------------------------------------
# C074 -- _template_front_layout reads the resolved role ids, not literals
# ---------------------------------------------------------------------------
def test_c074_template_layout_roles() -> None:
    print("\n== C074: _template_front_layout uses the resolved front-matter ids ==")

    def p(t, sid):
        return (f'<w:p><w:pPr><w:pStyle w:val="{sid}"/></w:pPr>'
                f'<w:r><w:t>{t}</w:t></w:r></w:p>')

    tpl = doc(p("Keywords: cells", "Authors") + p("Abstract", "Authors"))
    roles = {"author": "Authors", "headings": {1: "Heading1"}}
    got = f._template_front_layout(tpl, roles)
    check("C074 a template whose author style is 'Authors' yields keywords/abstract layout",
          "keywords" in got and "abstract_head" in got, str(got))
    check("C074 the unresolved-roles caller keeps the historical ids",
          f._template_front_layout(tpl) == {}, str(f._template_front_layout(tpl)))


# ---------------------------------------------------------------------------
# C075 -- single-quoted template attributes are read and rewritten
# ---------------------------------------------------------------------------
def test_c075_single_quoted_attrs() -> None:
    print("\n== C075: _template_front_parts handles single-quoted attributes ==")
    td = scratch("g3_c075_")
    try:
        tpl = td / "t.docx"
        tdoc = (f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body><w:sectPr>'
                "<w:headerReference w:type='default' r:id='rId1'/>"
                "</w:sectPr></w:body></w:document>")
        trels = (f'<Relationships><Relationship Id="rId1" Type="{R}/header" '
                 'Target="header1.xml"/></Relationships>')
        hrels = (f'<Relationships><Relationship Id="rId9" Type="{R}/image" '
                 "Target='media/logo.png'/></Relationships>")
        with zipfile.ZipFile(tpl, "w") as z:
            z.writestr("word/document.xml", tdoc)
            z.writestr("word/_rels/document.xml.rels", trels)
            z.writestr("word/header1.xml",
                       f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:drawing/></w:r></w:p></w:hdr>')
            z.writestr("word/_rels/header1.xml.rels", hrels)
            z.writestr("word/media/logo.png", b"png")
            z.writestr("[Content_Types].xml", "<Types/>")
        parts = {"[Content_Types].xml": b"<Types/>"}
        with zipfile.ZipFile(tpl) as z:
            front = f._template_front_parts(z, parts, set(z.namelist()))
        check("C075 a single-quoted headerReference is harvested",
              bool(front.get("header_default")), str(front))
        rels = parts.get("word/_rels/header_venue_first.xml.rels", b"").decode()
        check("C075 the copied image Target is rewritten in its own quote style",
              "venue_logo.png" in rels and 'Target="media/logo.png"' not in rels, rels)
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C076 -- a style referenced only from comments.xml is carried over
# ---------------------------------------------------------------------------
def test_c076_comment_only_style() -> None:
    print("\n== C076: a custom style used only by a comment survives the restyle ==")
    td = scratch("g3_c076_")
    try:
        src, out, tpl = td / "s.docx", td / "o.docx", td / "t.docx"
        make_docx(src, doc('<w:p><w:r><w:t>Body</w:t></w:r></w:p>'),
                  styles=styles_xml(style("MyCustom", "My Custom")),
                  extra={"word/comments.xml": (
                      f'<w:comments xmlns:w="{W}"><w:comment w:id="1"><w:p>'
                      '<w:pPr><w:pStyle w:val="MyCustom"/></w:pPr>'
                      '<w:r><w:t>Note</w:t></w:r></w:p></w:comment></w:comments>')})
        make_docx(tpl, doc('<w:p><w:r><w:t>T</w:t></w:r></w:p>'))
        res = f.apply_word_template(src, out, tpl)
        ost = read_part(out, "word/styles.xml").decode("utf-8", "replace")
        check("C076 apply reports success", res.get("ok") is True, str(res.get("error"))[:160])
        check("C076 the comment-only style definition is carried into the template styles",
              'w:styleId="MyCustom"' in ost, ost[:300])
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C077 -- a same-id, different-name style is not silently replaced
# ---------------------------------------------------------------------------
def test_c077_style_id_collision() -> None:
    print("\n== C077: apply_word_template does not apply an unrelated same-id style ==")
    td = scratch("g3_c077_")
    try:
        src, out, tpl = td / "s.docx", td / "o.docx", td / "t.docx"
        body = ('<w:p><w:r><w:t>A title about cells</w:t></w:r></w:p>'
                '<w:p><w:pPr><w:pStyle w:val="X"/></w:pPr>'
                '<w:r><w:t>Hello body.</w:t></w:r></w:p>')
        make_docx(src, doc(body), styles=styles_xml(style("X", "Body Text")))
        make_docx(tpl, doc('<w:p><w:r><w:t>T</w:t></w:r></w:p>'),
                  styles=styles_xml(style("X", "Title")))
        res = f.apply_word_template(src, out, tpl)
        od = read_part(out, "word/document.xml").decode("utf-8", "replace")
        ost = read_part(out, "word/styles.xml").decode("utf-8", "replace")
        check("C077 the id collision is recorded", bool(res.get("style_id_collisions")),
              str(res.get("style_id_collisions")))
        check("C077 the body paragraph no longer points at the template's Title style",
              'w:val="X_ms"' in od and res.get("style_refs_remapped") == 1, od)
        check("C077 the manuscript's own Body Text definition is kept under the fresh id",
              'w:styleId="X_ms"' in ost and "Body Text" in ost, ost[:300])
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C078 -- a legal UTF-16 source document is restyled, not silently skipped
# ---------------------------------------------------------------------------
def test_c078_utf16_restyle() -> None:
    print("\n== C078: apply_word_template reads/rewrites a UTF-16 source ==")
    td = scratch("g3_c078_")
    try:
        src, out, tpl = td / "s.docx", td / "o.docx", td / "t.docx"
        body = ('<w:p><w:pPr><w:pStyle w:val="BodyX"/></w:pPr>'
                '<w:r><w:t>Hello</w:t></w:r></w:p>')
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", doc(body).encode("utf-16"))
            z.writestr("word/styles.xml", styles_xml(style("BodyX", "Body Text")))
        make_docx(tpl, doc('<w:p><w:r><w:t>T</w:t></w:r></w:p>'),
                  styles=styles_xml(style("BodyT", "Body Text")))
        res = f.apply_word_template(src, out, tpl)
        raw = read_part(out, "word/document.xml")
        text = f.ooxml_part_text(raw)
        check("C078 the UTF-16 source is read and restyled",
              res.get("ok") is True and res.get("style_refs_remapped") == 1
              and 'w:val="BodyT"' in text, f"{res.get('style_refs_remapped')} :: {text[:200]}")
        check("C078 the rewritten main part is still UTF-16",
              raw[:2] in (b"\xff\xfe", b"\xfe\xff"), repr(raw[:8]))
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C079 -- FMT-T6d does not demand an italic journal title from a book entry
# ---------------------------------------------------------------------------
def test_c079_book_reference() -> None:
    print("\n== C079: FMT-T6d only fires on article-like entries ==")

    def rules(text):
        p = (f'<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
             f'<w:r><w:t>{text}</w:t></w:r></w:p>')
        res = f.analyse_document(doc(p), {}, dict(f.POLICY_DEFAULTS), "x.docx")
        return [r["rule"] for r in res["rows"] if r["rule"] == "FMT-T6d"]

    check("C079 a book entry with a year and no italics is not FMT-T6d",
          rules("Smith J. (2020). A book about cells. Publisher.") == [],
          str(rules("Smith J. (2020). A book about cells. Publisher.")))
    check("C079 an article entry with a volume/page locator still fires",
          rules("Poe A. (2021) A study. Cell 3: 4.") == ["FMT-T6d"])


# ---------------------------------------------------------------------------
# C080 -- the generic 'will be flagged as' prose no longer fires a logic row
# ---------------------------------------------------------------------------
def test_c080_logic_phrase() -> None:
    print("\n== C080: FMT-T9L does not fire on ordinary prose ==")
    plain = f.logic_rows(["Samples will be flagged as low quality and removed."], [False])
    check("C080 ordinary QC prose produces no FMT-T9L row", plain == [], str(plain))
    context = f.logic_rows(
        ["Low-quality callers will be flagged as failing the benchmark."], [False])
    check("C080 the benchmark-mechanism context is still reported",
          any(r["rule"] == "FMT-T9L" for r in context), str(context))


# ---------------------------------------------------------------------------
# C082 -- FMT-ST1 parses a family whose count column is not literally 10/none
# ---------------------------------------------------------------------------
def test_c082_stats_family_column() -> None:
    print("\n== C082: stats_floor_rows parses a non-10 family column ==")
    caption = "Table S3. A 19-test family; single pooled family of Holm-adjusted tests.\n"
    rows19 = [caption + "Method 19 9 0.030 1.00\n" * 5]
    rows10 = [caption + "Method 10 9 0.030 1.00\n" * 5]
    got = f.stats_floor_rows(rows19)
    check("C082 a 19-test family is parsed and flagged", len(got) == 5,
          f"{len(got)} row(s)")
    check("C082 the 10-column table keeps producing the same rows",
          len(f.stats_floor_rows(rows10)) == 5)


# ---------------------------------------------------------------------------
# C085 -- url_style=plain leaves w:rPrChange tracked formatting intact
# ---------------------------------------------------------------------------
def test_c085_rprchange_preserved() -> None:
    print("\n== C085: url_style=plain keeps the tracked-formatting record ==")
    xml = (f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body><w:p>'
           '<w:hyperlink r:id="rId1"><w:r><w:rPr>'
           '<w:rStyle w:val="Hyperlink"/><w:color w:val="0563C1"/>'
           '<w:u w:val="single"/>'
           '<w:rPrChange w:id="7" w:author="A" w:date="2020-01-01T00:00:00Z">'
           '<w:rPr><w:rStyle w:val="OldHyperlink"/><w:color w:val="FF0000"/>'
           '<w:u w:val="double"/></w:rPr></w:rPrChange></w:rPr>'
           '<w:t>https://example.org</w:t></w:r></w:hyperlink></w:p></w:body></w:document>')
    out, changes, _meta = f.fix_document(xml, {}, dict(f.POLICY_DEFAULTS))
    m = re.search(r"<w:rPrChange.*?</w:rPrChange>", out, re.S)
    kept = m.group(0) if m else ""
    check("C085 the rPrChange record survives byte-for-byte",
          'w:val="OldHyperlink"' in kept and 'w:val="FF0000"' in kept
          and 'w:val="double"' in kept, kept[:200])
    check("C085 the live link styling is still removed",
          'w:val="Hyperlink"' not in out and 'w:val="0563C1"' not in out, changes)


# ---------------------------------------------------------------------------
# C086 -- validate_latex compiles the document in a caller-supplied workdir
# ---------------------------------------------------------------------------
def test_c086_latex_workdir() -> None:
    print("\n== C086: validate_latex copies the source into an existing workdir ==")
    if f.latex_engine() is None:
        print("[skip] no TeX engine on PATH")
        return
    td = scratch("g3_c086_")
    try:
        srcdir = td / "src"
        srcdir.mkdir()
        tex = srcdir / "main.tex"
        tex.write_text("\\documentclass{article}\n\\begin{document}Hello\\end{document}\n",
                       encoding="utf-8")
        wd = td / "wd"
        wd.mkdir()
        rep = f.validate_latex(tex, workdir=wd, timeout=120)
        check("C086 a valid document compiles when a workdir is supplied",
              rep.get("ok") is True, str(rep)[:240])
        check("C086 the caller's workdir is not polluted by the compile copy",
              list(wd.iterdir()) == [], str([p.name for p in wd.iterdir()]))
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C087 -- validate_paths does not report a clean pass for zero documents
# ---------------------------------------------------------------------------
def test_c087_empty_validate() -> None:
    print("\n== C087: validate_paths' empty-input verdict is not ok ==")
    td = scratch("g3_c087_")
    try:
        rep = f.validate_paths([td])
        check("C087 an empty directory is not a clean validation",
              rep.get("ok") is False and rep.get("files") == 0, str(rep)[:200])
        make_docx(td / "good.docx", doc("<w:p/>"))
        rep2 = f.validate_paths([td])
        check("C087 a directory with a valid DOCX still passes",
              rep2.get("ok") is True and rep2.get("files") == 1, str(rep2)[:200])
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C088 -- a --json destination that is a directory is refused, not a traceback
# ---------------------------------------------------------------------------
def test_c088_report_directory() -> None:
    print("\n== C088: a directory report destination is an input error ==")
    td = scratch("g3_c088_")
    try:
        d = td / "reports"
        d.mkdir()
        check("C088 the path guard names the directory",
              "directory" in f._output_path_problem(d),
              f._output_path_problem(d))
        got = None
        try:
            got = f._write_report(d, {"ok": True})
        except Exception as e:                                     # noqa: BLE001
            got = f"EXC {type(e).__name__}: {e}"
        check("C088 _write_report returns an error instead of raising",
              isinstance(got, str) and got and not got.startswith("EXC"), str(got))
        check("C088 the directory is left intact", d.is_dir())
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# C089 -- the PDF stream locators accept CR-only end-of-line markers
# ---------------------------------------------------------------------------
def test_c089_cr_streams() -> None:
    print("\n== C089: PDF stream locators accept CR, LF and CRLF EOLs ==")
    import zlib
    payload = (b"<xfa:datasets><xfa:data><name>Alice</name></xfa:data>"
               b"</xfa:datasets>")
    comp = zlib.compress(payload)
    lf = b"%PDF-1.5\n1 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + comp + \
        b"\nendstream\nendobj\n"
    cr = b"%PDF-1.5\r1 0 obj\r<< /Filter /FlateDecode >>\rstream\r" + comp + \
        b"\rendstream\rendobj\r"
    crlf = b"%PDF-1.5\r\n1 0 obj\r\n<< /Filter /FlateDecode >>\r\nstream\r\n" + comp + \
        b"\r\nendstream\r\nendobj\r\n"
    check("C089 a CR-only form yields its dataset packet",
          len(f._xfa_dataset_packets(cr)) == 1, str(f._xfa_dataset_packets(cr)))
    check("C089 LF and CRLF forms still yield their packet",
          len(f._xfa_dataset_packets(lf)) == 1
          and len(f._xfa_dataset_packets(crlf)) == 1)


# ---------------------------------------------------------------------------
# C161 -- FMT-T6h reads a page range positionally, not any digits-hyphen span
# ---------------------------------------------------------------------------
def test_c161_bold_title_range() -> None:
    print("\n== C161: FMT-T6h does not treat a bold title range as a page range ==")

    def rows(runs):
        p = (f'<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>{runs}</w:p>')
        return f.reference_bold_rows(doc(p), {}, "x.docx")

    title_only = ('<w:r><w:rPr><w:b/></w:rPr>'
                  '<w:t>Effect of 2-3 doses on outcomes</w:t></w:r>'
                  '<w:r><w:t xml:space="preserve">. Journal 2020;1:1-9.</w:t></w:r>')
    check("C161 a numeric range in a bold title is not FMT-T6h",
          rows(title_only) == [], str(rows(title_only)))
    page_bold = ('<w:r><w:t xml:space="preserve">Effect of doses. Journal 2020;1:</w:t></w:r>'
                 '<w:r><w:rPr><w:b/></w:rPr><w:t>1-9</w:t></w:r>')
    check("C161 a bold page range still fires", any(
        r["rule"] == "FMT-T6h" for r in rows(page_bold)), str(rows(page_bold)))


# ---------------------------------------------------------------------------
# C165 -- every PDF artifact row carries the mandatory tier field
# ---------------------------------------------------------------------------
def test_c165_pdf_row_tiers() -> None:
    print("\n== C165: pdf_artifact_rows rows carry a tier ==")
    td = scratch("g3_c165_")
    try:
        p = td / "x.pdf"
        p.write_bytes(b"%PDF-1.4\n")
        rows = f.pdf_artifact_rows(p, text="Please wait...")
        check("C165 pdf_artifact_rows returns its rows", bool(rows), str(rows))
        check("C165 every PDF row carries a tier",
              all("tier" in r and r["tier"] for r in rows),
              str([(r.get("rule"), r.get("tier")) for r in rows]))
        rep = f.check_pdf(p, dict(f.POLICY_DEFAULTS))
        check("C165 check_pdf's rows carry a tier too",
              all("tier" in r and r["tier"] for r in rep["rows"]),
              str([(r.get("rule"), r.get("tier")) for r in rep["rows"]]))
    finally:
        shutil.rmtree(td, ignore_errors=True)


def main() -> int:
    test_c019_utf16_settings()
    test_c020_template_entity_guard()
    test_c021_utf16_fix_package()
    test_c071_keep_undefined_header_role()
    test_c072_keywords_pending()
    test_c073_style_id_escaping()
    test_c074_template_layout_roles()
    test_c075_single_quoted_attrs()
    test_c076_comment_only_style()
    test_c077_style_id_collision()
    test_c078_utf16_restyle()
    test_c079_book_reference()
    test_c080_logic_phrase()
    test_c082_stats_family_column()
    test_c085_rprchange_preserved()
    test_c086_latex_workdir()
    test_c087_empty_validate()
    test_c088_report_directory()
    test_c089_cr_streams()
    test_c161_bold_title_range()
    test_c165_pdf_row_tiers()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    if FAILS:
        for f_ in FAILS:
            print("  -", f_)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

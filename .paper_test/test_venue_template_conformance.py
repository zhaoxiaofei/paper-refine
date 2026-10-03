#!/usr/bin/env python3
"""Official venue templates: resolution, staging, restyling, conformance rows.

A venue whose `.official/` corpus carries a Word template must have every
produced .docx restyled into that template (styles/theme/numbering + style-name
mapping + page geometry + removal of the direct overrides that hide the styles),
its architecture (section order, statement names, figure/table label order)
checked by code, and the template files staged into every session sandbox so
the prompt's mandate is actionable.

Run:  python3 .paper_test/test_venue_template_conformance.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_tpl", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_tpl"] = nb
spec.loader.exec_module(nb)
fspec = importlib.util.spec_from_file_location("paper_tpl_fmt", str(WS / "paper_docx_format.py"))
fmt = importlib.util.module_from_spec(fspec)
sys.modules["paper_tpl_fmt"] = fmt
fspec.loader.exec_module(fmt)

FAILS = []
TMPDIRS = []
CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def styles_xml(font, size, sid, name, extra=None):
    extra_el = (f'<w:style w:type="paragraph" w:styleId="{extra}">'
                f'<w:name w:val="{extra}"/></w:style>' if extra else "")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}"/><w:sz w:val="{size}"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/><w:rPr><w:rFonts w:ascii="{font}"/><w:sz w:val="{size}"/></w:rPr></w:style>
{extra_el}
</w:styles>"""


def document_xml(style=None, text="Title text", geometry=("11906", "16838"),
                 extra_style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/><w:spacing w:before="480"/>' \
          f'<w:ind w:firstLine="720"/><w:jc w:val="center"/></w:pPr>' if style else \
          '<w:pPr><w:spacing w:before="240"/></w:pPr>'
    extra_par = (f'<w:p><w:pPr><w:pStyle w:val="{extra_style}"/></w:pPr>'
                 f'<w:r><w:t>note</w:t></w:r></w:p>' if extra_style else "")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p>{ppr}<w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="24"/></w:rPr><w:t>{text}</w:t></w:r></w:p>
{extra_par}
<w:p><w:r><w:t>plain paragraph</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="{geometry[0]}" w:h="{geometry[1]}"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>
</w:body></w:document>"""


def build_docx(path: Path, *, font="Times New Roman", size="24", sid="H1",
               name="heading 1", text="Title text", geometry=("11906", "16838"),
               extra_style=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", document_xml(sid, text, geometry, extra_style))
        z.writestr("word/styles.xml", styles_xml(font, size, sid, name, extra_style))


def build_fake_official(root: Path, *, word=True) -> Path:
    off = root / "venue_profiles" / "fake-venue.official"
    off.mkdir(parents=True)
    if word:
        build_docx(off / "Fake_Template.docx", font="Georgia", size="32",
                   sid="Heading1", name="heading 1", text="Template sample",
                   geometry=("12240", "15840"))
        build_docx(off / "Fake_Supplementary_Material.docx", font="Georgia", size="32",
                   sid="Heading1", name="heading 1", text="SI template")
    return off


def build_fake_pack(root: Path) -> None:
    """A minimal pinned pack: official sections/statements + an advisory order."""
    pack = root / "venue_profiles" / "fake-venue.templates"
    pack.mkdir(parents=True)
    structure = {
        "official": {
            "documentclass": "",
            "mandatory_sections": ["Introduction"],
            "statements": [{"label": "Funding"}, {"label": "Data availability"}],
            "sections": [{"title": "Introduction"}, {"title": "Methods"},
                         {"title": "Results"}],
        },
        "norm": {"sections": [{"title": "Introduction"}, {"title": "Methods"},
                              {"title": "Results"}]},
    }
    (pack / "structure.json").write_text(json.dumps(structure), encoding="utf-8")
    (pack / "venue_architecture.md").write_text("# Fake venue structure\n", encoding="utf-8")


def test_resolution_and_staging():
    root = scratch("paper_tpl_res_")
    build_fake_official(root)
    build_fake_pack(root)
    class Ctx:
        pass
    ctx = Ctx()
    ctx.root = root
    ctx.cfg = {"venue": "fake-venue"}
    files = nb.official_template_files("fake-venue", root)
    check("the official Word templates resolve (main + supplementary)",
          (files.get("word") or {}).get("main", Path()).name == "Fake_Template.docx"
          and (files.get("word") or {}).get("supplementary", Path()).name
          == "Fake_Supplementary_Material.docx",
          str(files.get("word")))
    sb = root / "sandbox"
    sb.mkdir()
    staged = nb.stage_venue_template(ctx, sb)
    check("the templates are staged read-only inside a session sandbox",
          staged and (sb / "venue_template" / "word" / "Fake_Template.docx").is_file()
          and not os.access(sb / "venue_template" / "word" / "Fake_Template.docx", os.W_OK),
          str(staged))
    block = nb.venue_norm_block("fake-venue", root)
    check("the venue block names the template files and the conformance mandate",
          "TEMPLATE FILES FOR THIS RUN" in block and "Fake_Template.docx" in block
          and "ARCHITECTURE AND FORMATTING FOLLOW THE TEMPLATE" in block)


def test_restyler():
    tmp = scratch("paper_tpl_restyle_")
    man = tmp / "manuscript.docx"
    tpl = tmp / "template.docx"
    out = tmp / "out.docx"
    build_docx(man, font="Times New Roman", size="24", sid="H1", name="heading 1",
               extra_style="CustomNote")
    build_docx(tpl, font="Georgia", size="32", sid="Heading1", name="heading 1",
               geometry=("12240", "15840"))
    rep = fmt.apply_word_template(man, out, tpl)
    check("the restyler reports success and text identity",
          rep.get("ok") is True and rep.get("text_unchanged") is True, str(rep))
    with zipfile.ZipFile(out) as z:
        doc = z.read("word/document.xml").decode("utf-8")
        sty = z.read("word/styles.xml").decode("utf-8")
    check("the manuscript style is remapped to the template's style id",
          '<w:pStyle w:val="Heading1"/>' in doc, doc[:200])
    check("the template's styles and page geometry are adopted",
          "Georgia" in sty and '<w:pgSz w:w="12240" w:h="15840"/>' in doc)
    check("the direct overrides that would hide the styles are gone",
          "<w:rFonts" not in doc and "<w:spacing" not in doc and "<w:jc" not in doc)
    check("the restyled package validates", fmt.validate_docx_parts(out).get("ok") is True)
    check("a manuscript-only referenced style survives the styles.xml swap",
          'w:styleId="CustomNote"' in sty, sty[-200:])


def test_normalizer_and_conformance():
    root = scratch("paper_tpl_conf_")
    build_fake_official(root)
    build_fake_pack(root)
    corpus = root / "corpus"
    corpus.mkdir()
    build_docx(corpus / "mainText.docx", font="Times New Roman", size="24", sid="H1",
               name="heading 1")
    shutil.copy2(corpus / "mainText.docx", corpus / "suppInfo.docx")
    (corpus / "notes.md").write_text(
        "# Results\n\nFigure 2 | Second.\n\n# Introduction\n\n"
        "Figure 1 | First.\n\nFunding\n\nData availability\n", encoding="utf-8")
    class Ctx:
        pass
    ctx = Ctx()
    ctx.root = root
    ctx.cfg = {"venue": "fake-venue"}
    tmpl = nb.venue_word_templates(ctx)
    req = nb.official_template_requirements("fake-venue", root)
    before = nb.scan_template_conformance([(corpus, "", ())], req,
                                          word_template=tmpl.get("main"),
                                          word_template_supplementary=tmpl.get("supplementary"))
    check("the pre-restyle scan reports the missing template styles",
          before.get("word_styles_missing"), str(before.get("word_styles_missing")))
    check("the scan reports the section-order inversion",
          any("Results" in r and "Introduction" in r for r in before.get("order_rows") or []),
          str(before.get("order_rows")))
    check("the scan reports the figure-label order",
          any("Figure" in r for r in before.get("label_rows") or []),
          str(before.get("label_rows")))
    rep = nb.normalize_formatting_in_dir(corpus, dict(fmt.POLICY_DEFAULTS), "probe",
                                         warns=[], artifacts_dir=root, template=tmpl)
    check("the normalizer restyles every corpus DOCX",
          rep.get("failed") == [] and all((d.get("template") or {}).get("ok")
                                          for d in rep["documents"]),
          str([(d["file"], d.get("applied"), d.get("template")) for d in rep["documents"]]))
    after = nb.scan_template_conformance([(corpus, "", ())], req,
                                         word_template=tmpl.get("main"),
                                         word_template_supplementary=tmpl.get("supplementary"))
    check("the post-restyle scan finds no missing template styles",
          after.get("word_styles_missing") == [], str(after.get("word_styles_missing")))
    check("the supplementary file is checked against the supplementary template",
          "suppInfo.docx" not in {m["document"] for m in after.get("word_styles_missing") or []})


def test_prompt_wiring():
    sandbox = scratch("paper_tpl_prompt_")
    marker = "=== FAKE VENUE TEMPLATE RULES ==="
    for name, text in (
            ("review", nb.review_prompt(sandbox, "r1_review", 1, venue_norm=marker)),
            ("revise", nb.revise_prompt(sandbox, "r1_a2_revise", 1, venue_norm=marker)),
            ("integrate", nb.integrate_prompt(sandbox, "r1_i1", 1, "a1", ["w1"],
                                              venue_norm=marker)),
            ("audit", nb.audit_prompt(sandbox, "r1_audit", 1, venue_norm=marker)),
            ("rewrite", nb.rewrite_prompt(sandbox, "r1_w1", 1, venue_norm=marker)),
            ("judge", nb.judge_prompt(sandbox, "r1_judge_x_j1", 1, "t", 1, 1, ["l1"],
                                      venue_norm=marker))):
        check(f"the {name} prompt carries the venue template block", marker in text)


FULL_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman"/><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:jc w:val="center"/></w:pPr><w:rPr><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="AuthorList"><w:name w:val="Author List"/><w:aliases w:val="Keywords,Abstract"/><w:basedOn w:val="Subtitle"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/></w:style>
</w:styles>"""


def full_docx(path: Path, doc_xml: str, *, styles=FULL_STYLES, extra=None, ct_extra="",
              rels_extra=""):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT.replace("</Types>", ct_extra + "</Types>"))
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc_xml)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", RELS.replace(
            "</Relationships>", rels_extra + "</Relationships>"))
        for name, data in (extra or {}).items():
            z.writestr(name, data)


def para(style, text):
    ppr = f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def test_generalized_template_restyle():
    """The pass is template-driven: any journal's template supplies the roles."""
    tmp = scratch("paper_tpl_generic_")
    tpl = tmp / "template.docx"
    body = (para("Title", "Journal sample title") + para(None, "First Author, Second Author")
            + para("AuthorList", "Abstract") + para("Heading1", "Introduction")
            + para("Heading2", "First subsection") + para("Heading2", "Second subsection"))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
           f'<w:body>{body}<w:sectPr>'
           '<w:headerReference w:type="first" r:id="rIdH1"/>'
           '<w:headerReference w:type="default" r:id="rIdH2"/>'
           '<w:footerReference w:type="default" r:id="rIdF1"/>'
           '<w:pgSz w:w="12240" w:h="15840"/>'
           '<w:pgMar w:top="1138" w:right="1181" w:bottom="1138" w:left="1282" '
           'w:header="283" w:footer="510" w:gutter="0"/><w:titlePg/>'
           '</w:sectPr></w:body></w:document>')
    logo = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:p><w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml">'
            '<v:imagedata r:id="rIdImg"/></v:shape></w:pict></w:r></w:p></w:hdr>')
    blank = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
             '<w:p/></w:hdr>')
    footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:p><w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
              '</w:p></w:ftr>')
    ct_extra = ('<Override PartName="/word/header1.xml" ContentType="application/vnd.'
                'openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                '<Override PartName="/word/header2.xml" ContentType="application/vnd.'
                'openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                '<Override PartName="/word/footer1.xml" ContentType="application/vnd.'
                'openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                '<Default Extension="png" ContentType="image/png"/>')
    rels_extra = ('<Relationship Id="rIdH1" Type="http://schemas.openxmlformats.org/'
                  'officeDocument/2006/relationships/header" Target="header1.xml"/>'
                  '<Relationship Id="rIdH2" Type="http://schemas.openxmlformats.org/'
                  'officeDocument/2006/relationships/header" Target="header2.xml"/>'
                  '<Relationship Id="rIdF1" Type="http://schemas.openxmlformats.org/'
                  'officeDocument/2006/relationships/footer" Target="footer1.xml"/>')
    h1_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
               'relationships"><Relationship Id="rIdImg" Type="http://schemas.openxmlformats.org/'
               'officeDocument/2006/relationships/image" Target="media/logo.png"/>'
               '</Relationships>')
    full_docx(tpl, doc, ct_extra=ct_extra, rels_extra=rels_extra,
              extra={"word/header1.xml": logo, "word/header2.xml": blank,
                     "word/footer1.xml": footer,
                     "word/_rels/header1.xml.rels": h1_rels,
                     "word/media/logo.png": b"\x89PNG\r\n\x1a\n"})
    roles = fmt.template_style_roles(tpl)
    check("the template's roles are derived from its own styles (any journal)",
          roles.get("title") == "Title" and roles.get("author") == "AuthorList"
          and roles.get("headings", {}).get(2) == "Heading2"
          and roles.get("max_heading_level") == 2, str(roles))
    man = tmp / "manuscript.docx"
    man_body = (para(None, "A title of the manuscript") + para(None, "Ann Author, Bob Author")
                + para("Heading1", "Abstract") + para("Heading2", "Keywords")
                + para(None, "keyword1; keyword2") + para("Heading2", "Lead contact")
                + para("Heading3", "Deep subsection") + para("Heading1", "Introduction")
                + para(None, "Body text."))
    man_doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               f'<w:body>{man_body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
               '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
               'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>')
    full_docx(man, man_doc)
    before = fmt.docx_front_matter_report(man, tpl)
    check("the pre-pass report names the logo/footer/front-matter gaps",
          any("logo" in r for r in before.get("rows") or [])
          and any("footer" in r for r in before.get("rows") or [])
          and any("title" in r for r in before.get("rows") or [])
          and any("deeper" in r for r in before.get("rows") or []),
          str(before.get("rows")))
    out = tmp / "out.docx"
    rep = fmt.apply_word_template(man, out, tpl)
    check("the generalized restyle keeps the text identical",
          rep.get("ok") is True and rep.get("text_unchanged") is True, str(rep.get("error")))
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        docx = z.read("word/document.xml").decode("utf-8", "replace")
    check("the venue's first-page header (logo) and page-number footers are copied",
          "word/header_venue_first.xml" in names and "word/media/venue_logo.png" in names
          and "word/footer_venue_first.xml" in names
          and 'w:type="first"' in docx, str(sorted(n for n in names if "venue" in n)))
    after = fmt.docx_front_matter_report(out, tpl)
    check("Title/AuthorList front matter is applied from the template's roles",
          after.get("title_style") == "Title" and after.get("author_style") == "AuthorList"
          and after.get("abstract_style") == "AuthorList", str(after))
    check("a heading deeper than the template's own depth is flattened",
          "Heading3" not in docx and rep.get("front_matter", {}).get("deep_headings_demoted") == 1,
          str(rep.get("front_matter")))
    check("the post-pass report no longer names the logo/footer gaps",
          not any("logo" in r or "footer" in r for r in after.get("rows") or []),
          str(after.get("rows")))


def main() -> int:
    try:
        test_resolution_and_staging()
        test_restyler()
        test_normalizer_and_conformance()
        test_prompt_wiring()
        test_generalized_template_restyle()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} VENUE-TEMPLATE CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL VENUE-TEMPLATE CONFORMANCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

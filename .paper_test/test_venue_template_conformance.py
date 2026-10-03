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
import re
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
    check("the venue block tells every role to READ the templates and use them",
          "READ THE TEMPLATE FILES YOURSELF" in block
          and "the REVIEW and the AUDIT" in block and "the JUDGE" in block
          and "visual_template/" in block)


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
        check(f"the {name} prompt requires the seeded template render comparison",
              "visual_template/" in text
              and "Template comparison" in text
              and "checks that the comparison was actually made" in text)
    judge = nb.judge_prompt(sandbox, "r1_judge_x_j1", 1, "t", 1, 1, ["l1"], venue_norm=marker)
    check("the judge's blinding rule names the venue-level template-render exception",
          "venue-level exception" in judge and "identical for every session" in judge)


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
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr></w:style>
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
    with zipfile.ZipFile(out) as z:
        hrels = z.read("word/_rels/header_venue_first.xml.rels").decode("utf-8", "replace")
    check("the copied logo relationship stays relative to the header part "
          "(Target='media/venue_logo.png', not a bare file name)",
          'Target="media/venue_logo.png"' in hrels, hrels)
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


def _run(text, sz=None, bold=False, space=False):
    rpr = ""
    if bold or sz:
        sz_xml = f'<w:sz w:val="{sz}"/>' if sz else ""
        rpr = (f"<w:rPr>{'<w:b/>' if bold else ''}"
               f"{sz_xml}</w:rPr>")
    keep = ' xml:space="preserve"' if space else ""
    return f"<w:r>{rpr}<w:t{keep}>{text}</w:t></w:r>"


def test_heading_retag():
    """Headings the source only DIRECT-formatted get the template's heading styles.

    The manuscript this pipeline exists for writes its sections as bold lines one
    point above the body size with no paragraph style at all; the normalizer's
    direct-format strip used to flatten them into body text, leaving the
    template's Heading 1/2 defined but unused. The retag runs BEFORE the strip,
    tags exactly the heading-like paragraphs, and every exclusion (title, front
    matter, captions, lists, table cells) stays untouched.
    """
    tmp = scratch("paper_tpl_retag_")
    tpl = tmp / "template.docx"
    tpl_body = (para("Heading1", "Introduction") + para("Heading1", "Methods")
                + para("Heading2", "A subsection") + para("Heading2", "Another subsection"))
    full_docx(tpl, ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                    '2006/main"><w:body>' + tpl_body +
                    '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                    '<w:pgMar w:top="1138" w:right="1181" w:bottom="1138" w:left="1282" '
                    'w:header="283" w:footer="510" w:gutter="0"/></w:sectPr>'
                    '</w:body></w:document>'))
    man = tmp / "manuscript.docx"
    body = "".join([
        f"<w:p>{_run('A directly formatted manuscript', sz=32, bold=True)}</w:p>",
        f"<w:p>{_run('Ann Author, Bob Author', sz=22)}</w:p>",
        f"<w:p>{_run('Abstract', sz=28, bold=True)}</w:p>",
        f"<w:p>{_run('word ' * 30, sz=22, space=True)}</w:p>",
        f"<w:p>{_run('Introduction', sz=28, bold=True)}</w:p>",
        f"<w:p>{_run('word ' * 40, sz=22, space=True)}</w:p>",
        f"<w:p>{_run('Sub-analysis of the primary cohort', sz=24, bold=True)}</w:p>",
        f"<w:p>{_run('Figure 1 | a directly formatted caption', sz=24, bold=True)}</w:p>",
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
        + _run("First numbered item", sz=24, bold=True) + "</w:p>",
        '<w:tbl><w:tr><w:tc><w:p>' + _run("Reagent", sz=24, bold=True)
        + "</w:p></w:tc></w:tr></w:tbl>",
    ])
    full_docx(man, ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                    '2006/main"><w:body>' + body +
                    '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                    '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
                    'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
                    '</w:body></w:document>'))
    cands = [t for _i, t, _s in fmt.heading_like_paragraphs(
        zipfile.ZipFile(man).read("word/document.xml").decode("utf-8", "replace"))]
    check("only the real section headings are candidates (title/front matter, caption, "
          "list item and table cell excluded)",
          cands == ["Introduction", "Sub-analysis of the primary cohort"], str(cands))
    out = tmp / "out.docx"
    rep = fmt.apply_word_template(man, out, tpl)
    retagged = rep.get("headings_retagged") or []
    check("the headings are tagged with the template's heading styles, level by size",
          [(t["text"], t["level"], t["style"]) for t in retagged]
          == [("Introduction", 1, "Heading1"),
              ("Sub-analysis of the primary cohort", 2, "Heading2")], str(retagged))
    with zipfile.ZipFile(out) as z:
        docx = z.read("word/document.xml").decode("utf-8", "replace")
    by_text = {}
    for m in re.finditer(r"<w:p\b[\s\S]*?</w:p>", docx):
        frag = m.group(0)
        by_text["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", frag)).strip()[:40]] = frag
    check("the retag survives into the package, and every direct size is stripped so the "
          "template styles own the typography",
          re.findall(r'<w:pStyle w:val="([^"]+)"', by_text["Introduction"]) == ["Heading1"]
          and re.findall(r'<w:pStyle w:val="([^"]+)"',
                         by_text["Sub-analysis of the primary cohort"]) == ["Heading2"]
          and 'w:sz w:val=' not in docx and rep.get("text_unchanged") is True)
    check("the caption, list item and table cell keep no heading style",
          all(not re.findall(r'<w:pStyle w:val="([^"]+)"', by_text[k])
              for k in ("Figure 1 | a directly formatted caption", "First numbered item",
                        "Reagent")),
          str({k: re.findall(r'<w:pStyle w:val="([^"]+)"', by_text[k])
               for k in ("Figure 1 | a directly formatted caption", "First numbered item",
                         "Reagent")}))


def test_even_odd_furniture():
    """A template whose headers/footers alternate by page parity keeps ALL roles.

    Frontiers' own Word templates do exactly this: the logo on the first page,
    a running head (Supplementary_Material.docx) or nothing on odd/even pages,
    the page number on odd ones and the typeset-provisional note on even ones.
    The pass must carry the even-typed parts AND the `w:evenAndOddHeaders`
    setting, must not stamp the template's prose into the manuscript, and must
    keep the produced file one Word actually opens (an AlternateContent
    text-box footer re-roled to first/even corrupts the package).
    """
    tmp = scratch("paper_tpl_evenodd_")
    tpl = tmp / "template.docx"
    body = para("Title", "Sample title") + para("Heading1", "Introduction")
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
           f'<w:body>{body}<w:sectPr>'
           '<w:headerReference w:type="first" r:id="rIdH1"/>'
           '<w:headerReference w:type="default" r:id="rIdH2"/>'
           '<w:headerReference w:type="even" r:id="rIdH3"/>'
           '<w:footerReference w:type="default" r:id="rIdF1"/>'
           '<w:footerReference w:type="even" r:id="rIdF2"/>'
           '<w:pgSz w:w="12240" w:h="15840"/><w:titlePg/>'
           '</w:sectPr></w:body></w:document>')
    head = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '{}</w:hdr>')
    logo = head.format('<w:p><w:r><w:drawing/></w:r></w:p>')
    blank = head.format("<w:p/>")
    running = head.format('<w:p><w:r><w:t>Running head</w:t></w:r></w:p>')
    box_footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                  'xmlns:v="urn:schemas-microsoft-com:vml">'
                  '<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent>'
                  '<w:p><w:r><w:t>{}</w:t></w:r>'
                  '<w:fldSimple w:instr=" PAGE "><w:r><w:t>3</w:t></w:r></w:fldSimple>'
                  '</w:p></w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p></w:ftr>')
    settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:defaultTabStop w:val="420"/>'
                '<w:evenAndOddHeaders/><w:characterSpacingControl w:val="doNotCompress"/>'
                '</w:settings>')
    ct_extra = "".join(
        f'<Override PartName="/word/{name}" ContentType="application/vnd.openxmlformats-'
        f'officedocument.wordprocessingml.{kind}+xml"/>'
        for name, kind in (("header1.xml", "header"), ("header2.xml", "header"),
                           ("header3.xml", "header"), ("footer1.xml", "footer"),
                           ("footer2.xml", "footer"), ("settings.xml", "settings")))
    rels_extra = "".join(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/'
        f'2006/relationships/{kind}" Target="{target}"/>'
        for rid, kind, target in (("rIdH1", "header", "header1.xml"),
                                  ("rIdH2", "header", "header2.xml"),
                                  ("rIdH3", "header", "header3.xml"),
                                  ("rIdF1", "footer", "footer1.xml"),
                                  ("rIdF2", "footer", "footer2.xml"),
                                  ("rIdS1", "settings", "settings.xml")))
    full_docx(tpl, doc, ct_extra=ct_extra, rels_extra=rels_extra,
              extra={"word/header1.xml": logo, "word/header2.xml": blank,
                     "word/header3.xml": running,
                     "word/footer1.xml": box_footer.format(""),
                     "word/footer2.xml": box_footer.format(
                         "This is a provisional file, not the final typeset article"),
                     "word/settings.xml": settings})
    check("the template is detected as parity-furnished",
          fmt._template_uses_even_odd(tpl) is True)
    man = tmp / "manuscript.docx"
    man_doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               f'<w:body>{para(None, "A title")}{para(None, "Ann Author")}'
               '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
               '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
               'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>')
    man_settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                    '2006/main"><w:zoom w:percent="100"/>'
                    '<w:defaultTabStop w:val="420"/>'
                    '<w:characterSpacingControl w:val="doNotCompress"/></w:settings>')
    full_docx(man, man_doc,
              ct_extra='<Override PartName="/word/settings.xml" ContentType="application/vnd.'
                       'openxmlformats-officedocument.wordprocessingml.settings+xml"/>',
              rels_extra='<Relationship Id="rIdS9" Type="http://schemas.openxmlformats.org/'
                         'officeDocument/2006/relationships/settings" Target="settings.xml"/>',
              extra={"word/settings.xml": man_settings})
    before = fmt.docx_front_matter_report(man, tpl)
    check("the pre-pass report names the missing parity setting",
          any("evenAndOddHeaders" in r for r in before.get("rows") or []),
          str(before.get("rows")))
    out = tmp / "out.docx"
    rep = fmt.apply_word_template(man, out, tpl)
    fp = rep.get("front_parts") or {}
    check("the even-typed header role is carried and the parity switch is set",
          rep.get("ok") is True and fp.get("even_odd") is True
          and fp.get("header_even") == "header_venue_even.xml"
          and fp.get("footer_even") == "footer_venue_even.xml",
          str(fp))
    with zipfile.ZipFile(out) as z:
        docx = z.read("word/document.xml").decode("utf-8", "replace")
        sett = z.read("word/settings.xml").decode("utf-8", "replace")
        even_head = z.read("word/header_venue_even.xml").decode("utf-8", "replace")
        even_foot = z.read("word/footer_venue_even.xml").decode("utf-8", "replace")
        def_foot = z.read("word/footer_venue_default.xml").decode("utf-8", "replace")
    refs = re.findall(r'<w:(header|footer)Reference w:type="(\w+)"', docx)
    check("the produced document references first, default AND even furniture",
          sorted(refs) == sorted([("header", "default"), ("header", "first"),
                                  ("header", "even"), ("footer", "default"),
                                  ("footer", "first"), ("footer", "even")]), str(refs))
    check("the parity setting lands where the schema puts it",
          "<w:defaultTabStop w:val=\"420\"/><w:evenAndOddHeaders/>"
          "<w:characterSpacingControl" in sett, sett[-260:])
    check("the even running head is carried", "Running head" in even_head)
    check("the template's even-footer PROSE is not stamped into the manuscript",
          "provisional" not in even_foot.lower() and "PAGE" in even_foot
          and fp.get("footer_replaced") == ["even"], str(fp.get("footer_replaced")))
    check("the template's default text-box footer is still carried as the default",
          "txbxContent" in def_foot and "PAGE" in def_foot)
    after = fmt.docx_front_matter_report(out, tpl)
    check("the post-pass report no longer names the parity gap",
          not any("evenAndOddHeaders" in r for r in after.get("rows") or []),
          str(after.get("rows")))


FAKE_MCP_SERVER_PY = '''#!/usr/bin/env python3
"""Minimal newline-delimited JSON-RPC MCP server for the tests: answers
initialize, ignores notifications, and writes a stand-in PDF next to the DOCX
its single tool is handed."""
import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    msg = json.loads(line)
    method = msg.get("method")
    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                          "result": {"protocolVersion": "2025-06-18",
                                     "capabilities": {"tools": {}},
                                     "serverInfo": {"name": "fake-docx-converter",
                                                    "version": "0"}}}), flush=True)
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments") or {}
        docx = str(args.get("docxPath") or "")
        pdf = docx[:-5] + ".pdf" if docx.lower().endswith(".docx") else docx + ".pdf"
        with open(pdf, "wb") as fh:
            fh.write(b"%PDF-1.4\\n% fake mcp render\\n")
        print(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                          "result": {"content": [{"type": "text", "text": "converted"}],
                                     "isError": False}}), flush=True)
'''


def _package_docx(path: Path, heading: str) -> None:
    sup = ("<w:r><w:rPr><w:vertAlign w:val=\"superscript\"/><w:sz w:val=\"22\"/></w:rPr>"
           "<w:t>1</w:t></w:r>")
    bullet = ("<w:p><w:pPr><w:pStyle w:val=\"ListParagraph\"/><w:numPr>"
              "<w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr></w:pPr>"
              + _run("A bulleted point of the real content", sz=22) + "</w:p>")
    body = ("<w:p><w:pPr><w:pStyle w:val=\"Title\"/></w:pPr>"
            + _run("A package title", sz=32, bold=True) + "</w:p>"
            + f"<w:p>{_run('Ann Author', sz=22)}{sup}</w:p>"
            + f"<w:p>{_run('word ' * 30, sz=22, space=True)}</w:p>"
            + bullet
            + f"<w:p>{_run(heading, sz=28, bold=True)}</w:p>")
    full_docx(path, ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                     '2006/main"><w:body>' + body +
                     '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                     '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
                     'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
                     '</w:body></w:document>'))


def test_foreign_containers_are_venue_data():
    """The formatter carries NO journal's vocabulary: container names are data.

    A venue profile declares the other publisher's block headings its own
    submission must not keep (`foreign_container_headings`); the formatter's
    default is empty, so a venue that declares none gets no container rule.
    """
    tmp = scratch("paper_tpl_containers_")
    tpl = tmp / "template.docx"
    full_docx(tpl, ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                    '2006/main"><w:body>' + para("Heading1", "Introduction")
                    + para("Heading2", "Methods") +
                    '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
                    '</w:body></w:document>'))
    man = tmp / "manuscript.docx"
    body = (f"<w:p>{_run('A title', sz=32, bold=True)}</w:p>"
            f"<w:p>{_run('word ' * 30, sz=22, space=True)}</w:p>"
            f"<w:p>{_run('Lead contact', sz=28, bold=True)}</w:p>"
            f"<w:p>{_run('word ' * 30, sz=22, space=True)}</w:p>"
            f"<w:p>{_run('Introduction', sz=28, bold=True)}</w:p>")
    full_docx(man, ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                    '2006/main"><w:body>' + body +
                    '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
                    '</w:body></w:document>'))
    plain = fmt.docx_front_matter_report(man, tpl)
    with_venue = fmt.docx_front_matter_report(man, tpl, containers=("Lead contact",))
    check("with no venue list the formatter reports NO foreign-container heading",
          not any("container heading" in r for r in plain.get("rows") or []),
          str(plain.get("rows")))
    check("a venue that declares its own foreign blocks gets the row",
          any("'Lead contact'" in r for r in with_venue.get("rows") or []),
          str(with_venue.get("rows")))
    check("the retag also skips what the VENUE declares foreign (and tags it otherwise)",
          [t for _i, t, _s in fmt.heading_like_paragraphs(
              zipfile.ZipFile(man).read("word/document.xml").decode("utf-8", "replace"),
              containers=("Lead contact",))] == ["Introduction"]
          and "Lead contact" in [t for _i, t, _s in fmt.heading_like_paragraphs(
              zipfile.ZipFile(man).read("word/document.xml").decode("utf-8", "replace"))])
    prof = nb.VenueProfile({"id": "probe-venue", "label": "Probe",
                            "foreign_container_headings": ["Lead contact"]})
    check("the venue profile validates and carries the field",
          prof.data["foreign_container_headings"] == ["Lead contact"]
          and nb.VenueProfile({"id": "probe-venue-2", "label": "Probe 2"}
                              ).data["foreign_container_headings"] == [])


def test_apply_template_package():
    """`apply-template`: the WHOLE package rebuilt inside the venue's templates."""
    tmp = scratch("paper_tpl_pkg_")
    tpl = tmp / "tpl"
    tpl.mkdir()
    main_tpl = tpl / "Fake_Template.docx"
    supp_tpl = tpl / "Fake_Supplementary_Material.docx"
    for t, marker in ((main_tpl, "Main"), (supp_tpl, "Supplementary")):
        full_docx(t, ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                      '2006/main"><w:body>' + para("Heading1", marker + " one")
                      + para("Heading1", marker + " two") + para("Heading2", "sub")
                      + para("Heading2", "sub two") +
                      '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                      '<w:pgMar w:top="1138" w:right="1181" w:bottom="1138" w:left="1282" '
                      'w:header="283" w:footer="510" w:gutter="0"/></w:sectPr>'
                      '</w:body></w:document>'))
    pkg = tmp / "pkg"
    (pkg / "work").mkdir(parents=True)
    _package_docx(pkg / "mainText.docx", "Introduction")
    _package_docx(pkg / "suppInfo.docx", "Supplementary tables")
    (pkg / "figure1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (pkg / "MANUAL_STEPS.md").write_text("steps\n", encoding="utf-8")
    (pkg / "work" / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    (pkg / "mainText.tracked.docx").write_bytes((pkg / "mainText.docx").read_bytes())
    dest = tmp / "out"
    rep = nb.rebuild_package_from_templates(
        {"main": main_tpl, "supplementary": supp_tpl}, pkg, dest)
    check("the package rebuild restyles every DOCX and copies every other file",
          rep.get("ok") is True and rep.get("documents_rebuilt") == 2
          and rep.get("files_copied") == 2, str(rep)[:260])
    names = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    check("process scratch and tracked-change auxiliaries stay out of the rebuilt package",
          names == ["MANUAL_STEPS.md", "figure1.png", "mainText.docx", "suppInfo.docx"],
          str(names))
    check("the supplementary document uses the supplementary template",
          (rep["files"] and any(f["file"] == "suppInfo.docx"
                                and Path(str(f.get("template") or "")).name
                                == "Fake_Supplementary_Material.docx"
                                for f in rep["files"])), str(rep["files"]))
    with zipfile.ZipFile(dest / "mainText.docx") as z:
        docx = z.read("word/document.xml").decode("utf-8", "replace")
    check("the rebuilt manuscript keeps its text and its headings are tagged",
          'w:pStyle w:val="Heading1"' in docx
          and all(f.get("text_unchanged") is not False for f in rep["files"]
                  if f["kind"] == "docx-rebuilt")
          and any(len(f.get("headings_retagged") or []) == 1 for f in rep["files"]),
          str([f.get("headings_retagged") for f in rep["files"]]))
    check("the report is written BESIDE the package, never inside it",
          (dest.parent / "out.template_report.json").is_file()
          and (dest.parent / "out.template_report.md").is_file()
          and not any("template_report" in n for n in names), str(names))


def _furnished_template(path: Path, guide: str, *, main: bool = True) -> None:
    """A template with a first-page logo header + a PAGE footer + guide prose."""
    body = (para("Title", "Article Title")
            + para(None, "First Author1, Second Author2*, Third Author1,2")
            + para(None, "* Correspondence: Corresponding Authoremail@uni.edu")
            + f"<w:p>{_run(guide, sz=22, space=True)}</w:p>"
            + para("Heading1", "Introduction") + para("Heading1", "Methods")
            + para("Heading2", "A subsection") + para("Heading2", "Another subsection")
            + para("ListParagraph", "A sample bullet the journal wants"))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
           f'<w:body>{body}<w:sectPr>'
           '<w:headerReference w:type="first" r:id="rIdH1"/>'
           '<w:footerReference w:type="default" r:id="rIdF1"/>'
           '<w:pgSz w:w="12240" w:h="15840"/><w:titlePg/></w:sectPr></w:body></w:document>')
    logo = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:p><w:r><w:drawing/></w:r></w:p></w:hdr>')
    footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:p><w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
              '</w:p></w:ftr>')
    ct_extra = ('<Override PartName="/word/header1.xml" ContentType="application/vnd.'
                'openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                '<Override PartName="/word/footer1.xml" ContentType="application/vnd.'
                'openxmlformats-officedocument.wordprocessingml.footer+xml"/>')
    rels_extra = ('<Relationship Id="rIdH1" Type="http://schemas.openxmlformats.org/'
                  'officeDocument/2006/relationships/header" Target="header1.xml"/>'
                  '<Relationship Id="rIdF1" Type="http://schemas.openxmlformats.org/'
                  'officeDocument/2006/relationships/footer" Target="footer1.xml"/>')
    full_docx(path, doc, ct_extra=ct_extra, rels_extra=rels_extra,
              extra={"word/header1.xml": logo, "word/footer1.xml": footer})


def test_template_rewrite_postcheck():
    """The template-first (LLM) session's verifiers: prose gone, content covered,
    template styles AND headers/footers carried."""
    tmp = scratch("paper_tpl_rewrite_")
    tpl = tmp / "template.docx"
    _furnished_template(tpl, "You may insert up to 5 heading levels into your manuscript as can "
                             "be seen in the Styles tab of this template.")
    pkg = tmp / "pkg"
    pkg.mkdir()
    _package_docx(pkg / "mainText.docx", "Introduction")
    sb = tmp / "session"
    (sb / "out").mkdir(parents=True)
    good = fmt.apply_word_template(pkg / "mainText.docx", sb / "out" / "mainText.docx", tpl)
    check("the simulated compliant agent output keeps the template's furniture",
          good.get("ok") and _hf_roles(sb / "out" / "mainText.docx")
          == [("footer", "default"), ("footer", "first"), ("header", "first")],
          str(_hf_roles(sb / "out" / "mainText.docx")))
    (sb / "out" / "REPLACEMENT_LEDGER.md").write_text("| placeholder | replacement |\n",
                                                      encoding="utf-8")
    rep = nb.template_rewrite_postcheck(sb, pkg, {"main": tpl})
    check("a filled template passes: source content covered, guide prose gone, styles kept",
          rep.get("ok") is True and rep["coverage"]["ratio"] >= 0.95
          and not rep["template_prose_left"], str(rep)[:260])
    # the failure mode the operator reported: the template copied but NOT filled
    shutil.copy(tpl, sb / "out" / "mainText.docx")
    rep2 = nb.template_rewrite_postcheck(sb, pkg, {"main": tpl})
    check("an UNFILLED template copy fails on leftover guide prose and missing content",
          rep2.get("ok") is False
          and any("guide sentence" in e for e in rep2["errors"])
          and any("coverage" in e for e in rep2["errors"]), str(rep2["errors"])[:260])
    # headers/footers dropped from an otherwise filled output
    fmt.apply_word_template(pkg / "mainText.docx", sb / "out" / "mainText.docx", tpl)
    with zipfile.ZipFile(sb / "out" / "mainText.docx") as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    doc = {i.filename: d for i, d in items}["word/document.xml"].decode("utf-8", "replace")
    doc = re.sub(r'<w:(?:header|footer)Reference[^>]*/>', "", doc)
    with zipfile.ZipFile(sb / "out" / "mainText.docx", "w", zipfile.ZIP_DEFLATED) as z:
        for i, d in items:
            z.writestr(i, doc.encode("utf-8") if i.filename == "word/document.xml" else d)
    rep3 = nb.template_rewrite_postcheck(sb, pkg, {"main": tpl})
    check("an output that lost the template's headers/footers is rejected",
          rep3.get("ok") is False
          and any("headers/footers" in e for e in rep3["errors"]), str(rep3["errors"])[:260])
    # a REBUILT package (no template furniture parts) is rejected as not derived
    fmt.apply_word_template(pkg / "mainText.docx", sb / "out" / "mainText.docx", tpl)
    with zipfile.ZipFile(sb / "out" / "mainText.docx") as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    rebuilt = [(i, d) for i, d in items
               if not re.match(r"word/(theme/|fontTable\.xml|numbering\.xml|"
                               r"(?:header|footer)\w*\.xml)", i.filename)]
    with zipfile.ZipFile(sb / "out" / "mainText.docx", "w", zipfile.ZIP_DEFLATED) as z:
        for i, d in rebuilt:
            z.writestr(i, d)
    rep4 = nb.template_rewrite_postcheck(sb, pkg, {"main": tpl})
    check("a package REBUILT without the template's furniture parts is rejected",
          rep4.get("ok") is False
          and any("not derived from the templates" in e for e in rep4["errors"]),
          str(rep4["errors"])[:260])
    # a dropped superscript (affiliation marker) is rejected
    fmt.apply_word_template(pkg / "mainText.docx", sb / "out" / "mainText.docx", tpl)
    with zipfile.ZipFile(sb / "out" / "mainText.docx") as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    doc = {i.filename: d for i, d in items}["word/document.xml"].decode("utf-8", "replace")
    doc = doc.replace('<w:vertAlign w:val="superscript"/>', "")
    with zipfile.ZipFile(sb / "out" / "mainText.docx", "w", zipfile.ZIP_DEFLATED) as z:
        for i, d in items:
            z.writestr(i, doc.encode("utf-8") if i.filename == "word/document.xml" else d)
    rep5 = nb.template_rewrite_postcheck(sb, pkg, {"main": tpl})
    check("a dropped affiliation superscript is rejected",
          rep5.get("ok") is False
          and any("superscript" in e for e in rep5["errors"]), str(rep5["errors"])[:260])
    # a list item re-tagged away from the template's bullet style is rejected
    fmt.apply_word_template(pkg / "mainText.docx", sb / "out" / "mainText.docx", tpl)
    with zipfile.ZipFile(sb / "out" / "mainText.docx") as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    doc = {i.filename: d for i, d in items}["word/document.xml"].decode("utf-8", "replace")
    doc = doc.replace('<w:pStyle w:val="ListParagraph"/>', "")
    with zipfile.ZipFile(sb / "out" / "mainText.docx", "w", zipfile.ZIP_DEFLATED) as z:
        for i, d in items:
            z.writestr(i, doc.encode("utf-8") if i.filename == "word/document.xml" else d)
    rep6 = nb.template_rewrite_postcheck(sb, pkg, {"main": tpl})
    check("a bullet whose template list style was dropped is rejected",
          rep6.get("ok") is False
          and any("no longer USE the styles" in e for e in rep6["errors"]),
          str(rep6["errors"])[:260])
    # ---- exact parity: the 5-word cutoff, the 95% tolerance floor and the
    # joined-text fallback are gone; every paragraph must be accounted for ----
    pkg2 = tmp / "pkg_parity"
    pkg2.mkdir()
    lines = ["A short unique line"] + [
        f"Paragraph number {i} carries enough words to be checked." for i in range(1, 22)]
    body = "".join(para(None, t) for t in lines)
    full_docx(pkg2 / "mainText.docx",
              '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              "<w:body>" + body
              + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
              "</w:body></w:document>")
    sb2 = tmp / "session_parity"
    (sb2 / "out").mkdir(parents=True)
    ledger = sb2 / "out" / "REPLACEMENT_LEDGER.md"
    ledger.write_text("| placeholder | replacement |\n", encoding="utf-8")
    fmt.apply_word_template(pkg2 / "mainText.docx", sb2 / "out" / "mainText.docx", tpl)
    base_rep = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("exact parity: the untampered package passes at ratio 1.0",
          base_rep.get("ok") is True and base_rep["coverage"]["ratio"] == 1.0
          and base_rep["coverage"]["mode"] == "exact-multiset", str(base_rep)[:240])
    # a SHORT source paragraph dropped (the old check never looked at <5 words)
    _drop_docx_paragraph(sb2 / "out" / "mainText.docx", "A short unique line")
    rep_short = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("a dropped SHORT source line fails exact parity",
          rep_short.get("ok") is False and any("coverage" in e for e in rep_short["errors"]),
          str(rep_short["errors"])[:240])
    # one of 21 long paragraphs dropped = 95.2%: the old 95% floor passed it
    fmt.apply_word_template(pkg2 / "mainText.docx", sb2 / "out" / "mainText.docx", tpl)
    _drop_docx_paragraph(sb2 / "out" / "mainText.docx", "Paragraph number 7 carries")
    rep95 = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("a 95.2%-covered package fails exact parity (no tolerance floor)",
          rep95.get("ok") is False and rep95["coverage"]["ratio"] < 1.0,
          str(rep95["errors"])[:240])
    # an undeclared 6-word addition fails; declaring it in the ledger's JSON passes
    fmt.apply_word_template(pkg2 / "mainText.docx", sb2 / "out" / "mainText.docx", tpl)
    _add_docx_paragraph(sb2 / "out" / "mainText.docx", "An invented sentence appears here.")
    rep_add = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("an undeclared content-bearing addition fails",
          rep_add.get("ok") is False
          and any("not present in any source" in e for e in rep_add["errors"]),
          str(rep_add["errors"])[:240])
    ledger.write_text(
        "| placeholder | replacement |\n\n```json\n"
        '{"exceptions": [{"kind": "addition", '
        '"output": "An invented sentence appears here.", '
        '"reason": "venue statement block"}]}\n```\n', encoding="utf-8")
    rep_add2 = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("a declared addition is accounted for and passes",
          rep_add2.get("ok") is True, str(rep_add2["errors"])[:240])
    # a declared re-wrap excuses a short line the template folds into a block --
    # the declared output must be TEXT THE SOURCE DID NOT ALREADY CARRY, or the
    # declaration would excuse a drop without preserving anything
    fmt.apply_word_template(pkg2 / "mainText.docx", sb2 / "out" / "mainText.docx", tpl)
    _drop_docx_paragraph(sb2 / "out" / "mainText.docx", "A short unique line")
    _add_docx_paragraph(sb2 / "out" / "mainText.docx", "A short unique line, lead contact.")
    ledger.write_text(
        "| placeholder | replacement |\n\n```json\n"
        '{"exceptions": [{"kind": "rewrap", "source": "A short unique line", '
        '"output": "A short unique line, lead contact.", '
        '"reason": "folded into the correspondence block"}]}\n```\n', encoding="utf-8")
    rep_rw = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("a declared re-wrap into NEW output text passes",
          rep_rw.get("ok") is True, str(rep_rw["errors"])[:240])
    # ... and pointing the declaration at a paragraph that was already in the
    # source (and stays in the output) cannot excuse the drop: one declaration
    # would otherwise be used as both the dropped source and the 'new' output.
    fmt.apply_word_template(pkg2 / "mainText.docx", sb2 / "out" / "mainText.docx", tpl)
    _drop_docx_paragraph(sb2 / "out" / "mainText.docx", "A short unique line")
    ledger.write_text(
        "| placeholder | replacement |\n\n```json\n"
        '{"exceptions": [{"kind": "rewrap", "source": "A short unique line", '
        '"output": "Paragraph number 1 carries enough words to be checked.", '
        '"reason": "folded into the correspondence block"}]}\n```\n', encoding="utf-8")
    rep_rw2 = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("a re-wrap declared into text the source already carries is rejected",
          rep_rw2.get("ok") is False
          and any("already fully accounted for" in e for e in rep_rw2["errors"]),
          str(rep_rw2["errors"])[:240])
    # the ledger is discovered by ONE rule: the existence check and the parser
    # must agree on the file, lower-case included
    fmt.apply_word_template(pkg2 / "mainText.docx", sb2 / "out" / "mainText.docx", tpl)
    _drop_docx_paragraph(sb2 / "out" / "mainText.docx", "A short unique line")
    _add_docx_paragraph(sb2 / "out" / "mainText.docx", "A short unique line, lead contact.")
    (sb2 / "out" / "REPLACEMENT_LEDGER.md").unlink()
    (sb2 / "out" / "replacement_ledger.md").write_text(
        "| placeholder | replacement |\n\n```json\n"
        '{"exceptions": [{"kind": "rewrap", "source": "A short unique line", '
        '"output": "A short unique line, lead contact.", '
        '"reason": "folded into the correspondence block"}]}\n```\n', encoding="utf-8")
    rep_led = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("a lower-case ledger file is parsed, not merely counted as present",
          rep_led.get("ok") is True, str(rep_led["errors"])[:240])
    (sb2 / "out" / "replacement_ledger.md").unlink()
    rep_noled = nb.template_rewrite_postcheck(sb2, pkg2, {"main": tpl})
    check("a genuinely missing ledger is reported as missing",
          rep_noled.get("ok") is False
          and any("is missing" in e for e in rep_noled["errors"]),
          str(rep_noled["errors"])[:240])
    # a source package whose only paragraph is whitespace cannot pass vacuously:
    # the gate would report ratio 1.0 with checked == 0
    blank = tmp / "pkg_blank"
    blank.mkdir()
    full_docx(blank / "mainText.docx",
              '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:body><w:p><w:r><w:t xml:space="preserve">   </w:t></w:r></w:p>'
              '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>')
    sb_blank = tmp / "session_blank"
    (sb_blank / "out").mkdir(parents=True)
    fmt.apply_word_template(blank / "mainText.docx", sb_blank / "out" / "mainText.docx", tpl)
    (sb_blank / "out" / "REPLACEMENT_LEDGER.md").write_text("| placeholder | replacement |\n",
                                                            encoding="utf-8")
    rep_blank = nb.template_rewrite_postcheck(sb_blank, blank, {"main": tpl})
    check("a source with no readable paragraph cannot pass vacuously",
          rep_blank.get("ok") is False and rep_blank["coverage"]["checked"] == 0
          and any("vacuous" in e for e in rep_blank["errors"]), str(rep_blank)[:220])


def _rewrite_docx_document(path: Path, edit) -> None:
    """Apply edit(document_xml) -> document_xml to one DOCX; other parts untouched."""
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, d in items:
            if i.filename == "word/document.xml":
                d = edit(d.decode("utf-8", "replace")).encode("utf-8")
            z.writestr(i, d)


def _drop_docx_paragraph(path: Path, needle: str) -> None:
    def edit(xml: str) -> str:
        for block in re.findall(r"<w:p\b[\s\S]*?</w:p>", xml):
            if needle.lower() in re.sub(r"<[^>]+>", "", block).lower():
                return xml.replace(block, "", 1)
        raise AssertionError(f"paragraph {needle!r} not found in {path}")
    _rewrite_docx_document(path, edit)


def _add_docx_paragraph(path: Path, text: str) -> None:
    def edit(xml: str) -> str:
        block = f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
        return xml.replace("</w:body>", block + "</w:body>", 1)
    _rewrite_docx_document(path, edit)


def _hf_roles(path: Path) -> list:
    return sorted(nb._docx_hf_signature(path).get("roles") or [])


def test_transfer_mode_runs_the_template_stage_first():
    """Transfer mode: authoring in the journal's templates is stage 0 by default.

    The stage gates the run (manual mode stops with the instruction and stages
    nothing else), can be opted out of, and a PASSED stage becomes round 1's
    working original -- the a1 base and every vs_original comparison read it.
    """
    tmp = scratch("paper_tpl_transfer_")
    root = tmp / "root"
    (root / "non_revised").mkdir(parents=True)
    _package_docx(root / "non_revised" / "mainText.docx", "Introduction")
    (root / "non_revised" / "figs").mkdir()
    (root / "non_revised" / "figs" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "non_revised" / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    off = root / "venue_profiles" / "fake-venue.official"
    off.mkdir(parents=True)
    _furnished_template(off / "Fake_Template.docx",
                        "Fill this template with your own manuscript content, please.")
    (root / "venue_profiles" / "fake-venue.json").write_text(json.dumps({
        "id": "fake-venue", "label": "Fake Venue", "journals": ["Fake Journal"],
        "default_journal": "Fake Journal"}), encoding="utf-8")
    (root / "reports").mkdir()
    ctx = nb.Ctx(root)
    ctx.cfg = {"venue": "fake-venue", "revision_mode": "transfer", "rounds": 1}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": {"files": {}, "count": 0}, "original_digest": "d0",
                 "config": ctx.cfg}
    check("with no passed stage the working original is still the pristine corpus",
          nb.template_stage_record(ctx) == {}
          and nb.working_original_dir(ctx) == ctx.pristine)
    class Args:
        no_template_stage = False
        agent = "manual"
        agent_cmd = None
        timeout = 5
    import contextlib as _ctxlib
    import io as _io
    err = _io.StringIO()
    code = 0
    try:
        with _ctxlib.redirect_stderr(err), _ctxlib.redirect_stdout(_io.StringIO()):
            nb._ensure_template_stage_for_run(ctx, Args())
    except SystemExit as e:
        code = int(e.code or 0)
    check("transfer mode stops at the template stage and tells the operator to fill it",
          code == 1 and "before any other stage" in err.getvalue()
          and (root / "template_rewrite" / "out").is_dir()
          and (root / "template_rewrite" / "PROMPT.md").is_file(),
          err.getvalue()[-200:])
    # the staged source/ must carry the WHOLE package -- the prompt tells the
    # agent to copy figures/tables/data into out/, which becomes round 1's base
    staged = root / "template_rewrite" / "source"
    check("the staged source/ carries non-docx package files with their paths",
          (staged / "figs" / "fig1.png").is_file()
          and (staged / "data.csv").is_file(),
          str(sorted(p.relative_to(staged).as_posix()
                     for p in staged.rglob("*") if p.is_file())))
    prompt_text = (root / "template_rewrite" / "PROMPT.md").read_text(encoding="utf-8")
    check("the venue-agnostic template prompt names no other journal's furniture",
          "Frontiers" not in prompt_text and "Fake Venue" in prompt_text,
          prompt_text[prompt_text.find("SELF-CHECK") - 80:][:200])
    class Skip(Args):
        no_template_stage = True
    nb._ensure_template_stage_for_run(ctx, Skip())     # must not raise
    check("--no-template-stage opts out", True)
    # a passed stage changes the working original
    out = root / "template_rewrite" / "out"
    _package_docx(out / "mainText.docx", "Introduction")
    ctx.state["template_stage"] = {"ok": True, "dir": "template_rewrite/out",
                                   "digest": "d-template", "content_fingerprint": "fp"}
    check("a PASSED stage becomes round 1's working original (base, field, views)",
          nb.working_original_dir(ctx) == out
          and nb.working_original_digest(ctx) == "d-template"
          and nb.working_original_fingerprint(ctx) == "fp"
          and nb.recorded_version_digest(ctx, 1, nb.ORIGINAL_ID) == "d-template"
          and nb.recorded_content_fingerprint(ctx, 1, nb.ORIGINAL_ID) == "fp"
          and nb.corpus_sources(ctx, 1, nb.ORIGINAL_ID) == [(out, "", ())],
          str(nb.corpus_sources(ctx, 1, nb.ORIGINAL_ID)))
    # The recorded digest must use the SAME corpus rule materialize_a1 re-computes.
    # The prompt requires out/VISUAL_CHECK.md; the A1 rule strips it as bookkeeping,
    # so a whole-tree digest made every compliant stage fail "does not match its
    # source" before round 1 could start.
    (out / "VISUAL_CHECK.md").write_text("# visual check\n", encoding="utf-8")
    rec = nb._record_template_stage(ctx, root / "template_rewrite", "manual")
    check("a passed stage's digest uses the rule A1 re-computes (bookkeeping stripped)",
          rec["digest"] == nb.manifest_digest(nb.manifest_for_sources([(out, "", ())]))
          and "VISUAL_CHECK.md" in nb.corpus_tree_manifest(out)["files"]
          and "VISUAL_CHECK.md" not in nb.manifest_for_sources([(out, "", ())])["files"],
          f"{rec['digest'][:12]} vs "
          f"{nb.manifest_digest(nb.manifest_for_sources([(out, '', ())]))[:12]}")
    a1_err, a1 = "", None
    try:
        a1 = nb.materialize_a1(ctx, 1)
    except Exception as e:                                            # noqa: BLE001
        a1_err = f"{type(e).__name__}: {e}"
    check("the passed template stage can seed round 1 (materialize_a1 does not raise)",
          a1 is not None and a1.get("status") == "done", a1_err[:200])


def test_init_mode_conform_stage():
    """`init`: the conform stage runs before anything else; with an official
    template it fills it, without one it falls back to the journal's own author
    guidelines and then to academic convention -- never to a feedback agent."""
    import contextlib as _ctxlib
    import io as _io

    class Args:
        no_template_stage = False
        agent = "manual"
        agent_cmd = None
        timeout = 5

    class Skip(Args):
        no_template_stage = True

    def build_ctx(base: Path, with_template: bool) -> nb.Ctx:
        (base / "non_revised").mkdir(parents=True)
        _package_docx(base / "non_revised" / "mainText.docx", "Introduction")
        off = base / "venue_profiles" / "fake-venue.official"
        off.mkdir(parents=True)
        if with_template:
            _furnished_template(off / "Fake_Template.docx",
                                "Fill this template with your own manuscript content, please.")
        (base / "venue_profiles" / "fake-venue.json").write_text(json.dumps({
            "id": "fake-venue", "label": "Fake Venue", "journals": ["Fake Journal"],
            "default_journal": "Fake Journal"}), encoding="utf-8")
        (base / "reports").mkdir()
        ctx = nb.Ctx(base)
        ctx.cfg = {"venue": "fake-venue", "revision_mode": "init", "rounds": 1}
        ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                     "log": [], "source_manifest": {"files": {}, "count": 0},
                     "original_digest": "d0", "config": ctx.cfg}
        return ctx

    tmp = scratch("paper_tpl_init_")
    # --- the venue ships an official Word template -----------------------------
    root = tmp / "with"
    ctx = build_ctx(root, with_template=True)
    check("init plans no journal stages (no feedback/concerns/response)",
          not ({e["kind"] for e in nb.round_run_plan(ctx, 1)}
               & {"feedback", "concerns", "response"}))
    nb._ensure_template_stage_for_run(ctx, Skip())
    check("--no-template-stage opts init out before anything is staged",
          not (root / "template_rewrite").exists())
    err = _io.StringIO()
    code = 0
    try:
        with _ctxlib.redirect_stderr(err), _ctxlib.redirect_stdout(_io.StringIO()):
            nb._ensure_template_stage_for_run(ctx, Args())
    except SystemExit as e:
        code = int(e.code or 0)
    prompt = (root / "template_rewrite" / "PROMPT.md").read_text(encoding="utf-8")
    check("init with an official template stages the template-fill session before any round",
          code == 1 and "before any other stage" in err.getvalue()
          and "COPY each template FILE" in prompt
          and not (ctx.state.get("runs") or {}), err.getvalue()[-200:])

    # --- the venue ships NO official template: guidelines then convention -----
    root2 = tmp / "without"
    ctx2 = build_ctx(root2, with_template=False)
    err2 = _io.StringIO()
    out2 = _io.StringIO()
    code2 = 0
    try:
        with _ctxlib.redirect_stderr(err2), _ctxlib.redirect_stdout(out2):
            nb._ensure_template_stage_for_run(ctx2, Args())
    except SystemExit as e:
        code2 = int(e.code or 0)
    prompt2 = (root2 / "template_rewrite" / "PROMPT.md").read_text(encoding="utf-8")
    check("init without an official template falls back to guidelines, then convention",
          code2 == 1 and "author guidelines" in out2.getvalue()
          and "NO official Word template" in prompt2 and "academic convention" in prompt2
          and "COPY each template FILE" not in prompt2
          and not (ctx2.state.get("runs") or {}),
          (out2.getvalue() + err2.getvalue())[-200:])

    # --- a passed stage becomes round 1's working original either way ---------
    out = root2 / "template_rewrite" / "out"
    _package_docx(out / "mainText.docx", "Introduction")
    ctx2.state["template_stage"] = {"ok": True, "dir": "template_rewrite/out",
                                    "digest": "d-init", "content_fingerprint": "fp"}
    check("a passed no-template init stage seeds round 1's working original",
          nb.working_original_dir(ctx2) == out
          and nb.working_original_digest(ctx2) == "d-init")


def test_mcp_first_render_chain():
    """The orchestrator's own template renders use the operator's FIRST choice:
    the docx-converter MCP tool, then docx2pdf.sh, then LibreOffice."""
    tmp = scratch("paper_tpl_mcp_")
    home = tmp / "codex_home"
    home.mkdir()
    server = tmp / "fake_mcp_server.py"
    server.write_text(FAKE_MCP_SERVER_PY, encoding="utf-8")
    (home / "config.toml").write_text(
        "[mcp_servers.docx-converter]\n"
        f'command = "{sys.executable}"\n'
        f'args = ["{server}"]\n', encoding="utf-8")
    old_home = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = str(home)
    try:
        check("a configured docx-converter MCP server is discovered and parsed",
              nb.mcp_server_configured("docx-converter") is True
              and nb.mcp_server_spec("docx-converter").get("command") == sys.executable,
              str(nb.mcp_server_spec("docx-converter")))
        names = [c[0] for c in nb.visual_renderer_choices()]
        check("the MCP tool heads the renderer chain",
              bool(names) and names[0] == "mcp:docx-converter", str(names))
        docx = tmp / "sample.docx"
        docx.write_bytes(b"PK\x03\x04not-a-real-package")
        out = tmp / "out"
        out.mkdir()
        rep = nb.render_docx_visual(docx, out)
        check("the orchestrator renders through the MCP tool first (Word fidelity)",
              rep.get("ok") is True and rep.get("renderer") == "mcp:docx-converter"
              and (out / "sample.pdf").is_file()
              and not (tmp / "sample.pdf").exists(), str(rep)[:260])
        # a dead MCP server must fall back to the next renderer, and say so
        broken = tmp / "broken_mcp.py"
        broken.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        fake_sh = tmp / "docx2pdf.sh"
        fake_sh.write_text('#!/bin/sh\nprintf \'%%PDF-1.4\\n%% fake word\\n\' > "${1%.*}.pdf"\n',
                           encoding="utf-8")
        os.chmod(fake_sh, 0o755)
        real_choices, real_pages = nb.visual_renderer_choices, nb._pdf_page_count
        nb.visual_renderer_choices = lambda: [
            ("mcp:docx-converter", {"command": sys.executable, "args": [str(broken)]}),
            ("word", fake_sh)]
        nb._pdf_page_count = lambda _pdf: 1
        try:
            fallback = nb.render_docx_visual(docx, out)
        finally:
            nb.visual_renderer_choices, nb._pdf_page_count = real_choices, real_pages
        check("a dead MCP server falls back to docx2pdf.sh, recording the failure",
              fallback.get("ok") is True and fallback.get("renderer") == "word"
              and (fallback.get("fallbacks") or [{}])[0].get("renderer")
              == "mcp:docx-converter", str(fallback)[:300])
    finally:
        if old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_home


def test_visual_template_render_and_comparison():
    """The venue's own templates are RENDERED into each session sandbox, and the
    recorded visual pass must compare against that render (page count + names)."""
    tmp = scratch("paper_tpl_visual_")
    root = tmp / "root"
    root.mkdir()
    build_fake_official(root)
    build_fake_pack(root)

    class Ctx:
        pass

    ctx = Ctx()
    ctx.root = root
    ctx.cfg = {"venue": "fake-venue"}
    sb = tmp / "sandbox"
    sb.mkdir()
    # A fake Word: handed a .docx copy, it writes a (stand-in) PDF next to it.
    fake = tmp / "docx2pdf.sh"
    fake.write_text('#!/bin/sh\nprintf \'%%PDF-1.4\\n%% fake render\\n\' > "${1%.*}.pdf"\n',
                    encoding="utf-8")
    os.chmod(fake, 0o755)
    real_choices, real_pages = nb.visual_renderer_choices, nb._pdf_page_count
    page_calls = {"n": 0}

    def fake_choices():
        return [("word", fake)]

    def fake_page_count(_pdf):
        page_calls["n"] += 1
        return 4

    nb.visual_renderer_choices = fake_choices
    nb._pdf_page_count = fake_page_count
    try:
        man = nb.seed_template_visuals(ctx, sb)
        docs = {d["role"]: d for d in man.get("documents") or []}
        check("the venue's Word templates are rendered into the sandbox",
              man.get("renderer") == "word" and set(docs) == {"main", "supplementary"}
              and all(d.get("ok") and d.get("pages") == 4 for d in docs.values()),
              str(man)[:300])
        check("the template render (PDF + manifest) lands under visual_template/",
              (sb / "visual_template" / "main" / "Fake_Template.pdf").is_file()
              and (sb / "visual_template" / "supplementary"
                   / "Fake_Supplementary_Material.pdf").is_file()
              and (sb / "visual_template" / "manifest.json").is_file())
        check("one render per template digest is cached under the root",
              (root / ".visual_cache").is_dir()
              and list((root / ".visual_cache").rglob("manifest.json")))
        calls = page_calls["n"]
        nb.seed_template_visuals(ctx, sb)
        check("a second materialization reuses the cached render (no re-render)",
              page_calls["n"] == calls, f"{calls} -> {page_calls['n']}")
        check("the prompt names the seeded render as the comparison basis",
              "visual_template/" in nb.venue_norm_block("fake-venue", root))
    finally:
        nb.visual_renderer_choices, nb._pdf_page_count = real_choices, real_pages

    # The cache's failure policy: retry once, then reuse the recorded failure.
    cache = tmp / "cache"
    cache.mkdir()
    nb.write_json_atomic(cache / "manifest.json",
                         {"renderer": "word", "ok": False, "attempts": 1,
                          "error": "transient"})
    rec, attempts = nb._cached_visual_render(cache, "word")
    check("a failed cached render is retried once (a flake must not win)",
          rec is None and attempts == 1, f"{rec} / {attempts}")
    nb.write_json_atomic(cache / "manifest.json",
                         {"renderer": "word", "ok": False, "attempts": 2,
                          "error": "still failing"})
    rec, attempts = nb._cached_visual_render(cache, "word")
    check("a twice-failed render is reused instead of re-driven per session",
          isinstance(rec, dict) and rec.get("ok") is False and attempts == 2, f"{rec}")
    nb.write_json_atomic(cache / "manifest.json", {"renderer": "word", "ok": True, "pages": 4})
    rec, attempts = nb._cached_visual_render(cache, "word")
    check("a successful cached render is always reused",
          isinstance(rec, dict) and rec.get("ok") is True)
    check("a cache written by another renderer is not reused",
          nb._cached_visual_render(cache, "libreoffice") == (None, 0))

    # The record gate: with the template render seeded, the visual artifact must
    # name each template document with its page count and report the comparison.
    target = sb / "target"
    target.mkdir()
    (target / "rendered.pdf").write_bytes(b"%PDF-1.4\n")
    art = sb / "VISUAL_CHECK.md"
    art.write_text(
        "Rendered every page with the fake Word renderer and looked at them.\n\n"
        "Template comparison: Fake_Template.docx (4 page(s)) vs the manuscript, and "
        "Fake_Supplementary_Material.docx (4 page(s)) for the supplement -- title centred, "
        "author list bold, logo header and page-number footer present.\n", encoding="utf-8")
    errs, warns = [], []
    nb.check_visual_artifact(art, "the visual record", errs, warns,
                             render_roots=[target], sandbox=sb)
    check("a record that compares against the template render passes", not errs, str(errs))
    art.write_text("Rendered every page with the fake Word renderer and looked at them. "
                   "The title is left-aligned.\n", encoding="utf-8")
    errs, warns = [], []
    nb.check_visual_artifact(art, "the visual record", errs, warns,
                             render_roots=[target], sandbox=sb)
    check("a record that ignores the seeded template render fails",
          any("does not compare against it" in e for e in errs), str(errs))
    art.write_text("Template comparison against Fake_Template.docx and its 4 page(s): the "
                   "manuscript title is centred; Fake_Supplementary_Material.docx matches too.\n",
                   encoding="utf-8")
    errs, warns = [], []
    nb.check_visual_artifact(art, "the visual record", errs, warns,
                             render_roots=[target], sandbox=sb)
    check("the gate is satisfied once the record names every template document + page count",
          not errs, str(errs))

    # A template whose render FAILED (no renderer here) cannot be compared
    # against, so the gate stays open -- the record's own honesty rules apply.
    sb2 = tmp / "sandbox2"
    (sb2 / "visual_template").mkdir(parents=True)
    (sb2 / "target").mkdir()
    (sb2 / "target" / "rendered.pdf").write_bytes(b"%PDF-1.4\n")
    nb.write_json_atomic(sb2 / "visual_template" / "manifest.json",
                         {"renderer": "none",
                          "documents": [{"role": "main", "source": "Fake_Template.docx",
                                         "ok": False, "pages": 0, "error": "no renderer"}]})
    art2 = sb2 / "VISUAL_CHECK.md"
    art2.write_text("Rendered every page with the docx CLI and looked at them.\n",
                    encoding="utf-8")
    errs, warns = [], []
    nb.check_visual_artifact(art2, "the visual record", errs, warns,
                             render_roots=[sb2 / "target"], sandbox=sb2)
    check("an unrenderable template does not gate the visual record", not errs, str(errs))


def main() -> int:
    try:
        test_resolution_and_staging()
        test_restyler()
        test_normalizer_and_conformance()
        test_prompt_wiring()
        test_generalized_template_restyle()
        test_heading_retag()
        test_even_odd_furniture()
        test_foreign_containers_are_venue_data()
        test_apply_template_package()
        test_template_rewrite_postcheck()
        test_transfer_mode_runs_the_template_stage_first()
        test_init_mode_conform_stage()
        test_mcp_first_render_chain()
        test_visual_template_render_and_comparison()
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

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
        rpr = (f"<w:rPr>{'<w:b/>' if bold else ''}"
               f"{f'<w:sz w:val=\"{sz}\"/>' if sz else ''}</w:rPr>")
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

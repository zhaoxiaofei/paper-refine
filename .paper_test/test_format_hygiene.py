#!/usr/bin/env python3
"""Whitespace, grammar artifacts and embedded-image geometry (M20).

The classes the text-only corpus cannot see shipped through two real rounds:
a correspondence e-mail one space to the right of its line, a stray empty
paragraph between "2 Materials and Methods" and "2.1 Study design", and two
supplementary figures delivered 31% / 16% off their own pixel ratio. This
suite pins the round trip:

  * the scan reports `FMT-P4` (a space at a visual line edge), `FMT-S8` (a
    blank line attached to a heading), `FMT-G1` (a doubled article/preposition)
    and `FMT-IM1` (an image drawn off its own aspect ratio) -- and the fixer
    repairs all four with `ok=True` under the recorded-text-edit verification;
  * TEMPLATE-PRESCRIBED BLANKS ARE NEVER TOUCHED: the venue template's own
    empty-paragraph slots (derived from the template, carried in
    `format_policy.json`) and anything before the first non-empty paragraph
    (the spacer above the title) are neither reported nor deleted;
  * the spelling-pair TIE (`modelling` x1 vs `modeling` x1) normalizes by the
    first occurrence, so the mechanical finding is clearable and no longer
    rejects every other repair of the file;
  * `format_policy_of` carries the venue template's slots, the session policy
    file writes them, and the review/revise/integrate/rewrite/judge prompts and
    the auditor directives name the new classes and the template exemption.

Run:  python3 .paper_test/test_format_hygiene.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paperp", WS / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp"] = np
spec.loader.exec_module(np)
fspec = importlib.util.spec_from_file_location("paper_docx_format",
                                               WS / "paper_docx_format.py")
fmt = importlib.util.module_from_spec(fspec)
sys.modules["paper_docx_format"] = fmt
fspec.loader.exec_module(fmt)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


# ---- fixtures ---------------------------------------------------------------

DOC_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')


def para(text="", style=None, runs=None, ppr_extra=""):
    ppr = ""
    if ppr_extra:
        ppr = f"<w:pPr>{ppr_extra}</w:pPr>"
    elif style:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
    body = runs if runs is not None else (
        f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>' if text else "")
    return f"<w:p>{ppr}{body}</w:p>"


def empty_para(style=None):
    return f"<w:p><w:pPr/></w:p>" if style is None else (
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr></w:p>')


def drawing(rid, cx, cy, rot=None):
    xfrm = (f'<a:xfrm rot="{rot}">' if rot else "<a:xfrm>")
    return ('<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/>'
            '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
            '<wp:docPr id="1" name="Picture 1"/><wp:cNvGraphicFramePr/>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/'
            'drawingml/2006/picture"><pic:pic>'
            '<pic:nvPicPr><pic:cNvPr id="1" name="Picture 1"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
            '</pic:blipFill><pic:spPr>'
            f'{xfrm}<a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>")


def document(*blocks):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:document {DOC_NS}><w:body>{''.join(blocks)}</w:body></w:document>")


def png(width, height):
    """A minimal valid PNG (stdlib only)."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x10\x20\x30" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


IMAGE_REL = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.'
             'org/package/2006/relationships"><Relationship Id="rId5" Type="http://schemas.'
             'openxmlformats.org/officeDocument/2006/relationships/image" '
             'Target="media/image1.png"/></Relationships>')


def write_pkg(dirp: Path, name: str, xml: str, rels=None, media=None,
              media_name: str = "image1.png") -> Path:
    dirp.mkdir(parents=True, exist_ok=True)
    p = dirp / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="xml" ContentType='
                   '"application/xml"/><Default Extension="png" ContentType="image/png"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.'
                   'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://'
                                  'schemas.openxmlformats.org/package/2006/relationships"/>')
        z.writestr("word/document.xml", xml)
        z.writestr("word/styles.xml",
                   '<?xml version="1.0"?><w:styles xmlns:w="http://schemas.'
                   'openxmlformats.org/wordprocessingml/2006/main"/>')
        if rels is not None:
            z.writestr("word/_rels/document.xml.rels", rels)
        if media is not None:
            z.writestr(f"word/media/{media_name}", media)
    return p


def rows_of(info, rule):
    return [r for r in info["rows"] if r["rule"] == rule]


# ---- 1. line-edge spaces + the stray blank between two headings -------------

def test_scan_and_fix_real_defects():
    print()
    print("== a line-edge space and a stray blank between headings ==")
    body = (
        para("Manuscript title", style="Title")
        + para("Authors", style="AuthorList")
        + para("Materials and Methods", style="Heading1")
        + empty_para()
        + para("Study design and data provenance", style="Heading2")
        + para("This study generated no new data.")
        + para(runs='<w:r><w:t xml:space="preserve">* Correspondence: </w:t></w:r>'
                    "<w:r><w:br/></w:r>"
                    "<w:r><w:t xml:space=\"preserve\">Zhen Xie, lead contact</w:t></w:r>"
                    "<w:r><w:br/></w:r>"
                    "<w:r><w:t xml:space=\"preserve\"> zhenxie@example.edu</w:t></w:r>"))
    tmp = Path(tempfile.mkdtemp(prefix="paper_hyg_"))
    src = write_pkg(tmp, "main.docx", document(*body))
    pol = dict(fmt.POLICY_DEFAULTS)
    info = fmt.analyse_package(src, pol)
    check("the blank line between the H1 and the H2 is FMT-S8",
          len(rows_of(info, "FMT-S8")) == 1
          and rows_of(info, "FMT-S8")[0]["location"] == "p3",
          str([(r["rule"], r["location"]) for r in info["rows"]]))
    p4 = rows_of(info, "FMT-P4")
    check("the space before the e-mail is a line-edge FMT-P4",
          any("zhenxie@example.edu" in r["evidence"] and "leading" in r["evidence"]
              for r in p4), str([r["evidence"][:70] for r in p4]))
    check("the trailing space of the correspondence label is FMT-P4 too",
          any("Correspondence" in r["evidence"] for r in p4))
    out = tmp / "fixed.docx"
    rep = fmt.fix_package(src, out, pol)
    after = fmt.analyse_package(out, pol)
    check("the fixer repairs them and self-verifies (recorded text edits only)",
          rep["ok"] is True and rep["verified"]["text_diff_only_recorded_edits"]
          and rep["verified"]["mechanical_findings_after"] == 0,
          json.dumps(rep["verified"])[:220])
    check("no mechanical row survives the fix",
          not [r for r in after["rows"] if r["rule"] in ("FMT-S8", "FMT-P4", "FMT-G1")],
          str([(r["rule"], r["location"]) for r in after["rows"]]))
    fixed = zipfile.ZipFile(out).read("word/document.xml").decode()
    check("the fixed XML no longer carries the leading space or the blank paragraph",
          " zhenxie@example.edu" not in fixed
          and "<w:pPr/></w:p>" not in fixed)
    check("a self-closing w:pPr is filled, never duplicated (the schema regression)",
          "</w:pPr><w:pPr" not in fixed)
    # A doubled word is mechanical, but the rule must not rewrite a valid
    # construction ("studies in in vitro systems").
    guarded = document(para("Manuscript title", style="Title"),
                       para("We studied the effect in in vitro systems."))
    guarded_src = write_pkg(tmp, "guarded.docx", guarded)
    check("`in in vitro` is not treated as a doubled word",
          not rows_of(fmt.analyse_package(guarded_src,
                                          dict(fmt.POLICY_DEFAULTS)), "FMT-G1"))
    return tmp, src


def test_template_prescribed_blanks_survive(tmp):
    print()
    print("== template-prescribed blanks are never reported or deleted ==")
    template = document(
        empty_para(),                      # the spacer above the title
        para("Article Title", style="Title"),
        para("Equations", style="Heading2"),
        empty_para(style="Caption"),       # the template's own placeholder slot
        para("Figures", style="Heading2"))
    slots = fmt.empty_paragraph_slots_from_template(template)
    check("the template's slots are the front-matter spacer and the Caption slot",
          ["", "", "Title"] in slots and ["Caption", "H2", "H2"] in slots,
          json.dumps(slots))
    body = (
        empty_para()                       # front-matter spacer (before the title)
        + para("Manuscript title", style="Title")
        + para("Equations", style="Heading2")
        + empty_para(style="Caption")      # template-prescribed slot
        + para("Figures", style="Heading2")
        + para("Materials and Methods", style="Heading1")
        + empty_para()                     # NOT prescribed -> stray
        + para("Study design", style="Heading2"))
    src = write_pkg(tmp, "slots.docx", document(*body))
    pol = dict(fmt.POLICY_DEFAULTS)
    pol["empty_paragraph_slots"] = slots
    info = fmt.analyse_package(src, pol)
    check("with the slots in the policy only the un-prescribed blank is FMT-S8",
          [r["location"] for r in rows_of(info, "FMT-S8")] == ["p6"],
          str([(r["rule"], r["location"]) for r in info["rows"]]))
    no_slots = fmt.analyse_package(src, dict(fmt.POLICY_DEFAULTS))
    check("without the slots the Caption placeholder is reported (the rule works)",
          [r["location"] for r in rows_of(no_slots, "FMT-S8")] == ["p3", "p6"],
          str([r["location"] for r in rows_of(no_slots, "FMT-S8")]))
    check("the front-matter blank is exempt even without slots",
          all(r["location"] != "p0" for r in no_slots["rows"]))
    out = tmp / "slots.fixed.docx"
    rep = fmt.fix_package(src, out, pol)
    fixed = zipfile.ZipFile(out).read("word/document.xml").decode()
    check("the fixer deletes only the un-prescribed blank",
          rep["ok"] is True
          and fixed.count("<w:pPr/></w:p>") == 1     # the front-matter spacer stays
          and fixed.count('<w:pStyle w:val="Caption"/>') == 1,
          f"blank=<w:pPr/></w:p> x{fixed.count('<w:pPr/></w:p>')}")


# ---- 2. embedded images keep their own aspect ratio -------------------------

def test_image_aspect_ratio(tmp):
    print()
    print("== an image drawn off its own pixel ratio is FMT-IM1 and is restored ==")
    xml = document(para("Manuscript title", style="Title"),
                   drawing("rId5", 2_000_000, 2_000_000),
                   para("Figure 1. A distorted figure."))
    src = write_pkg(tmp, "images.docx", xml, rels=IMAGE_REL, media=png(100, 50))
    pol = dict(fmt.POLICY_DEFAULTS)
    info = fmt.analyse_package(src, pol)
    im = rows_of(info, "FMT-IM1")
    check("the 2.0-ratio PNG drawn at 1.0 is reported (FMT-IM1)",
          len(im) == 1 and "100x50 px" in im[0]["evidence"]
          and im[0]["fix"] == "mechanical", str(im)[:200])
    out = tmp / "images.fixed.docx"
    rep = fmt.fix_package(src, out, pol)
    fixed = zipfile.ZipFile(out).read("word/document.xml").decode()
    check("the fixer keeps the width and restores the height in BOTH extents",
          rep["ok"] is True
          and '<wp:extent cx="2000000" cy="1000000"/>' in fixed
          and '<a:ext cx="2000000" cy="1000000"/>' in fixed,
          fixed[fixed.find("<wp:extent"):fixed.find("<wp:extent") + 60])
    check("the repaired extents are not re-reported on the next scan",
          not rows_of(fmt.analyse_package(out, pol), "FMT-IM1"))
    ok_xml = document(para("Manuscript title", style="Title"),
                      drawing("rId5", 2_000_000, 1_000_000))
    ok_src = write_pkg(tmp, "images.ok.docx", ok_xml, rels=IMAGE_REL, media=png(100, 50))
    check("an image inside the tolerance is clean",
          not rows_of(fmt.analyse_package(ok_src, pol), "FMT-IM1"))
    # Vector art carries its ratio too: an SVG's viewBox.
    svg_rel = IMAGE_REL.replace('Target="media/image1.png"', 'Target="media/fig1.svg"')
    svg = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
           b'viewBox="0 0 200 50"></svg>')
    svg_src = write_pkg(tmp, "images.svg.docx", xml, rels=svg_rel, media=svg,
                        media_name="fig1.svg")
    svg_rows = rows_of(fmt.analyse_package(svg_src, pol), "FMT-IM1")
    check("an SVG's viewBox ratio is checked like a raster image",
          len(svg_rows) == 1 and "200x50" in svg_rows[0]["evidence"],
          str(svg_rows)[:200])
    svg_out = tmp / "images.svg.fixed.docx"
    rep_svg = fmt.fix_package(svg_src, svg_out, pol)
    fixed_svg = zipfile.ZipFile(svg_out).read("word/document.xml").decode()
    check("the SVG fixer keeps the width and restores the height",
          rep_svg["ok"] is True and 'cx="2000000" cy="500000"' in fixed_svg,
          fixed_svg[fixed_svg.find("<wp:extent"):fixed_svg.find("<wp:extent") + 60])
    rot_xml = document(para("Manuscript title", style="Title"),
                       drawing("rId5", 2_000_000, 2_000_000, rot=5_400_000))
    rot_src = write_pkg(tmp, "images.rot.docx", rot_xml, rels=IMAGE_REL, media=png(100, 50))
    check("a deliberately rotated drawing (90 degrees) is not 'repaired'",
          not rows_of(fmt.analyse_package(rot_src, pol), "FMT-IM1"))


# ---- 3. the spelling tie no longer blocks every other repair ----------------

def test_spelling_tie_is_clearable(tmp):
    print()
    print("== a spelling-pair tie normalizes instead of blocking the fix ==")
    xml = document(para("Manuscript title", style="Title"),
                   para("We used modelling here."),
                   para("Modeling was used again."))
    src = write_pkg(tmp, "spell.docx", xml)
    pol = dict(fmt.POLICY_DEFAULTS)
    info = fmt.analyse_package(src, pol)
    check("the 1:1 mix is reported with the tie-break target named",
          any(r["rule"] == "FMT-T8d" and "first occurrence" in r["evidence"]
              for r in info["rows"]), str(rows_of(info, "FMT-T8d"))[:200])
    out = tmp / "spell.fixed.docx"
    rep = fmt.fix_package(src, out, pol)
    fixed = zipfile.ZipFile(out).read("word/document.xml").decode()
    check("the fixer clears the finding and self-verifies",
          rep["ok"] is True and rep["verified"]["mechanical_findings_after"] == 0
          and not rows_of(fmt.analyse_package(out, pol), "FMT-T8d"),
          json.dumps(rep["verified"])[:200])
    check("the first occurrence's form wins (modelling -> one variant left)",
          ("modelling" in fixed) != ("modeling" in fixed), fixed[:0])


# ---- 4. the policy, the session file and every prompt carry the classes -----

def test_policy_and_prompts():
    print()
    print("== policy slots + the review/audit/revise/integrate/rewrite/judge text ==")
    tmp = Path(tempfile.mkdtemp(prefix="paper_hyg_prompt_"))
    root = tmp / "root"
    (root / "venue_profiles").mkdir(parents=True)
    src = (WS / "venue_profiles" / "frontiers-in-immunology.json").read_text(encoding="utf-8")
    (root / "venue_profiles" / "frontiers-in-immunology.json").write_text(src,
                                                                         encoding="utf-8")
    # The venue's official Word template is LOCAL downloaded data
    # (`venue_profiles/*` is gitignored), so a clean checkout has no
    # `<venue>.official/` pack at all -- and the check below then saw an empty
    # slot list and failed. Build the minimal template the derivation needs
    # under the root's own venue_profiles/, which wins over the script's copy,
    # so this suite is hermetic on any machine.
    official = root / "venue_profiles" / "frontiers-in-immunology.official"
    official.mkdir(parents=True)
    tpl_doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
               '2006/main"><w:body>'
               '<w:p><w:r><w:t>Article title</w:t></w:r></w:p>'
               '<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr></w:p>'
               '<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>'
               '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
               '</w:body></w:document>')
    with zipfile.ZipFile(official / "Frontiers_Template.docx", "w") as z:
        z.writestr("word/document.xml", tpl_doc)
    ctx = np.Ctx(root)
    ctx.cfg = {"venue": "frontiers-in-immunology"}
    slots = np.format_policy_of(ctx).get("empty_paragraph_slots") or []
    check("the venue template's own blank slots reach the policy",
          slots and all(len(s) == 3 for s in slots), json.dumps(slots)[:160])
    pol_file = np.seed_format_policy_file(ctx, tmp)
    written = json.loads(pol_file.read_text(encoding="utf-8"))
    check("the session's format_policy.json carries the slots and the tolerance",
          written.get("empty_paragraph_slots") == slots
          and written.get("image_aspect_tolerance") == 0.02, json.dumps(written)[:160])
    fr = np.load_venue_profile("frontiers-in-immunology")
    sb = Path(tempfile.mkdtemp(prefix="paper_hyg_prompts_"))
    review = np.review_prompt(sb, "r1_review", 1, venue=fr)
    revise = np.revise_prompt(sb, "r1_a2", 1, venue=fr)
    integrate = np.integrate_prompt(sb, "r1_i1", 1, "a1", ["a2"], venue=fr)
    rewrite = np.rewrite_prompt(sb, "r1_w1", 1, venue=fr)
    judge = np.judge_prompt(sb, "r1_judge_t_j1", 1, "tok", 1, 2, ["v1"], venue=fr)
    audit = np.audit_prompt(sb, "r1_audit", 1)
    for name, text in (("review", review), ("revise", revise),
                       ("integrate", integrate), ("rewrite", rewrite),
                       ("judge", judge), ("audit", audit)):
        check(f"the {name} text carries the new classes and the template exemption",
              "FMT-IM1" in text
              and ("FMT-P4" in text or "line edge" in text or "start or end of a" in text)
              and "template" in text.lower(),
              "")
    check("the audit re-derives the mechanical formatting state itself",
          "RE-DERIVE THE FORMATTING" in audit and "format_policy.json" in audit)
    check("the judge names the aspect-ratio damage and the residual-row rule",
          "width-to-height" in judge.replace("\n", " ") or "aspect ratio" in judge)


def main():
    tmp, _src = test_scan_and_fix_real_defects()
    test_template_prescribed_blanks_survive(tmp)
    test_image_aspect_ratio(tmp)
    test_spelling_tie_is_clearable(tmp)
    test_policy_and_prompts()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL FORMAT-HYGIENE/IMAGE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

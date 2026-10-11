#!/usr/bin/env python3
"""The 2026-10-11 round-2 debug run: the front-matter splice that emitted TWO `w:rPr`.

Run:  python3 .paper_test/test_debug_round2_2026_1011.py

The 2026-10-10 round-2 debug closed two-`w:rPr` output for RUNS
(`_bold_label_runs`, pinned by `test_debug_round2_2026_1010.py`); the
PARAGRAPH-mark path kept the same flaw. `_insert_ppr_extra` spliced the
template's own pPr snippet -- and for the affiliation and correspondence roles
that snippet is a `w:spacing` + `w:rPr` pair -- BEFORE the paragraph's existing
`w:rPr`, so a paragraph that carried a direct `w:rPr` ended up with TWO `w:rPr`
children where CT_PPr allows exactly one. The emitted package is
schema-invalid: Word reports unreadable content and `docx validate` fails, the
fixer's own verification refuses to repair the document (its output cannot
validate), and the offline Zotero refresh/flatten lane is unavailable for it.

The venue-template pass is applied by every package-producing stage and by
publication, and the shipped NeoHeteroclitic main text carries exactly this
shape on its three affiliation lines and its correspondence line: the
canonical run's published copy `final_clean_version/neohetero-9-2-mainText-*.docx`
fails `docx validate` with `Element 'w:rPr': This element is not expected`, while
the same run's `round1_winner` copy of the SAME version validates -- the
duplicates come back when the template is re-applied.

Checked here (hermetic; no real package is needed):

  * the paragraph-mark splice never leaves two `w:rPr` children in one `w:pPr`;
  * the template's own values are the ones that survive (the same replacement
    rule `_apply_ppr_extra` already applies to the direct spacing/ind/jc it
    strips), and the paragraph keeps the template's direct spacing;
  * `apply_word_template` on a front-matter fixture emits a package the `docx`
    CLI accepts (when the CLI exists), text-identical, parts intact;
  * a paragraph that already satisfies the template is left alone.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__import__("os").environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = _load("paper_r2b_format", WS / "paper_docx_format.py")

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
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="AuthorList"><w:name w:val="Author List"/><w:aliases w:val="author list,authors"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/></w:style>
</w:styles>"""
GEOM = ('<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="720" w:footer="720" w:gutter="0"/>')
# The affiliation/correspondence role snippet a real venue template carries: a
# direct spacing pair plus the paragraph-mark run properties.
TPL_CHILDREN = ('<w:spacing w:before="240" w:after="0"/>'
                '<w:rPr><w:rFonts w:cs="Times New Roman"/><w:b/><w:szCs w:val="24"/></w:rPr>')
TPL_PPR = "<w:pPr>" + TPL_CHILDREN + "</w:pPr>"


def check(name, cond, detail=""):
    if cond:
        print(f"[ok ] {name}")
    else:
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))
        FAILS.append(name)


def scratch(prefix="pr2b_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def _p(text: str, ppr: str = "") -> str:
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _build(path: Path, paragraphs: str) -> None:
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{paragraphs}<w:sectPr>{GEOM}</w:sectPr></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", xml)
        z.writestr("word/styles.xml", STYLES)


def _ppr_blocks(xml: str):
    return re.findall(r"<w:pPr\b[^>]*>.*?</w:pPr>", xml, re.S)


def _doubled_rpr(xml: str):
    return [b for b in _ppr_blocks(xml)
            if len(re.findall(r"<w:rPr(?=[\s>])", b)) > 1]


def _front_matter_pair(tmp: Path):
    """(manuscript, template): the shape the shipped NeoHet package has."""
    man = tmp / "mainText.docx"
    tpl = tmp / "Template.docx"
    own = "<w:pPr><w:rPr><w:b/></w:rPr></w:pPr>"
    _build(man, _p("Heteroclitic peptide ranking", '<w:pPr><w:pStyle w:val="Title"/></w:pPr>')
           + _p("1Institute of Bioinformatics, Tsinghua University", own)
           + _p("2School of Life Sciences, Beijing", own)
           + _p("* Correspondence: Zhen Xie (zhenxie@tsinghua.edu.cn)", own)
           + _p("Body text.", ""))
    _build(tpl, _p("Template title", '<w:pPr><w:pStyle w:val="Title"/></w:pPr>')
           + _p("1Affiliation of the template", TPL_PPR)
           + _p("* Correspondence: Author (a@b.c)", TPL_PPR)
           + _p("Template body.", ""))
    return man, tpl


# ---------------------------------------------------------------------------
# 1. the paragraph-mark splice (unit)
# ---------------------------------------------------------------------------
def test_insert_ppr_extra_keeps_one_rpr():
    ppr = '<w:pPr><w:spacing w:after="0"/><w:rPr><w:b/></w:rPr></w:pPr>'
    extra = ('<w:spacing w:before="240" w:after="0"/>'
             '<w:rPr><w:rFonts w:cs="Times New Roman"/><w:szCs w:val="24"/></w:rPr>')
    out = fmt._insert_ppr_extra(ppr, extra)
    check("the pPr keeps exactly one w:rPr", len(re.findall(r"<w:rPr(?=[\s>])", out)) == 1, out)
    check("the TEMPLATE's run properties replace the paragraph's direct ones",
          '<w:szCs w:val="24"/>' in out and '<w:rFonts w:cs="Times New Roman"/>' in out, out)
    check("the template's spacing still lands on the paragraph",
          '<w:spacing w:before="240" w:after="0"/>' in out, out)
    # A snippet WITHOUT an rPr still lands before an existing one (schema order:
    # spacing precedes rPr), and one with neither keeps the old shape.
    spaced = fmt._insert_ppr_extra('<w:pPr><w:rPr><w:b/></w:rPr></w:pPr>',
                                   '<w:spacing w:before="240"/>')
    check("a spacing-only snippet still precedes the existing rPr",
          spaced == '<w:pPr><w:spacing w:before="240"/><w:rPr><w:b/></w:rPr></w:pPr>', spaced)
    empty = fmt._insert_ppr_extra('<w:pPr><w:jc w:val="center"/></w:pPr>', "")
    check("an empty snippet is a no-op", empty == '<w:pPr><w:jc w:val="center"/></w:pPr>', empty)


def test_apply_ppr_extra_keeps_one_rpr():
    frag = ('<w:p><w:pPr><w:spacing w:after="0"/><w:rPr><w:b/></w:rPr></w:pPr>'
            "<w:r><w:t>x</w:t></w:r></w:p>")
    out = fmt._apply_ppr_extra(frag, TPL_CHILDREN)
    check("_apply_ppr_extra emits one w:rPr (it emitted two)",
          not _doubled_rpr(out) and out.count("<w:pPr") == 1, out)
    check("the direct spacing the caller strips is not re-added beside the template's",
          out.count("<w:spacing") == 1, out)
    check("the paragraph text is untouched", "<w:t>x</w:t>" in out, out)


# ---------------------------------------------------------------------------
# 1b. the same splice on the two property bags that used to be mishandled:
#     `<w:pPr/>` (a second pPr was appended) and a recorded `w:pPrChange`
#     (whose nested pPr/rPr is revision record, not the paragraph's bag)
# ---------------------------------------------------------------------------
CHANGE = ('<w:pPrChange w:id="9"><w:pPr><w:jc w:val="left"/><w:rPr><w:i/></w:rPr>'
          "</w:pPr></w:pPrChange>")


def _direct_rpr_block(xml: str) -> str:
    """The part of a pPr BEFORE a recorded change (direct children only)."""
    ci = xml.find("<w:pPrChange")
    return xml[:ci] if ci >= 0 else xml


def test_property_bag_edge_cases():
    self_closing = fmt._insert_ppr_extra("<w:pPr/>", TPL_CHILDREN)
    check("a self-closing <w:pPr/> is opened, not duplicated",
          self_closing == TPL_PPR, self_closing)
    with_attr = fmt._insert_ppr_extra('<w:pPr w:rsidR="00A1"/>', TPL_CHILDREN)
    check("a self-closing pPr keeps its attributes",
          with_attr == '<w:pPr w:rsidR="00A1">' + TPL_CHILDREN + "</w:pPr>", with_attr)
    changed = fmt._insert_ppr_extra('<w:pPr><w:jc w:val="center"/>' + CHANGE, TPL_CHILDREN)
    check("the recorded change is byte-identical after the splice",
          changed.endswith(CHANGE), changed)
    check("the template's children land BEFORE the recorded change",
          changed.startswith("<w:pPr><w:jc w:val=\"center\"/>" + TPL_CHILDREN), changed)
    check("exactly one direct rPr survives beside the record",
          len(re.findall(r"<w:rPr(?=[\s>])", _direct_rpr_block(changed))) == 1, changed)
    spacing_only = fmt._insert_ppr_extra('<w:pPr><w:rPr><w:b/></w:rPr>' + CHANGE,
                                         '<w:spacing w:before="240"/>')
    check("a spacing-only snippet still precedes the direct rPr, record intact",
          spacing_only.startswith('<w:pPr><w:spacing w:before="240"/>'
                                  "<w:rPr><w:b/></w:rPr>")
          and spacing_only.endswith(CHANGE), spacing_only)
    frag = ('<w:p><w:pPr><w:jc w:val="left"/>' + CHANGE + "</w:pPr>"
            "<w:r><w:t>x</w:t></w:r></w:p>")
    applied = fmt._apply_ppr_extra(frag, TPL_CHILDREN)
    check("_apply_ppr_extra keeps the recorded change byte-identical",
          CHANGE in applied, applied)
    check("_apply_ppr_extra strips the direct jc but not the one inside the record",
          '<w:jc w:val="left"/>' not in _direct_rpr_block(applied)
          and '<w:jc w:val="left"/>' in applied, applied)
    emptied = fmt._apply_ppr_extra("<w:p><w:pPr/><w:r><w:t>y</w:t></w:r></w:p>",
                                   TPL_CHILDREN)
    check("_apply_ppr_extra gives a <w:pPr/> paragraph exactly one pPr",
          emptied.count("<w:pPr") == 1 and TPL_CHILDREN in emptied, emptied)


# ---------------------------------------------------------------------------
# 2. the venue-template pass (end to end, the publishing path's own call)
# ---------------------------------------------------------------------------
def test_apply_word_template_front_matter_schema():
    tmp = scratch()
    man, tpl = _front_matter_pair(tmp)
    out = tmp / "out.docx"
    rep = fmt.apply_word_template(man, out, tpl)
    check("the restyle reports success and text identity",
          rep.get("ok") is True and rep.get("text_unchanged") is True, str(rep)[:200])
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        styles = z.read("word/styles.xml").decode("utf-8")
    bad = _doubled_rpr(xml)
    check("no w:pPr carries two w:rPr children", not bad, str(bad)[:300])
    check("the template's own run properties are the ones that survive",
          '<w:rFonts w:cs="Times New Roman"/>' in xml and '<w:szCs w:val="24"/>' in xml,
          xml[:200])
    check("the template's styles were adopted", "Times New Roman" in styles, styles[:120])
    if shutil.which("docx"):
        proc = subprocess.run(["docx", "validate", str(out)], capture_output=True, text=True)
        detail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
        check("the emitted package passes `docx validate`", proc.returncode == 0,
              detail[-1][:200] if detail else f"rc={proc.returncode}")
    else:
        print("[ok ] the emitted package passes `docx validate`  -- skipped (no docx CLI)")


def test_already_conforming_paragraph_is_left_alone():
    tmp = scratch()
    man, tpl = _front_matter_pair(tmp)
    # A manuscript whose affiliation line already carries the template's own
    # rPr values: the splice must not double them either.
    src = tmp / "conforming.docx"
    _build(src,
           _p("Heteroclitic peptide ranking", '<w:pPr><w:pStyle w:val="Title"/></w:pPr>')
           + _p("1Institute of Bioinformatics, Tsinghua University",
                '<w:pPr><w:spacing w:before="240" w:after="0"/>'
                "<w:rPr><w:b/></w:rPr></w:pPr>")
           + _p("Body text.", ""))
    out = tmp / "out2.docx"
    rep = fmt.apply_word_template(src, out, tpl)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    check("a paragraph that already carries a direct rPr still ends with one",
          rep.get("ok") is True and not _doubled_rpr(xml), str(rep)[:200])


# ---------------------------------------------------------------------------
# 3. FMT-AV1: the DEFERRED-LOCATOR verb family
#    ("will be added ... before publication" is the same promise as
#    "will be deposited ... before publication", which the rule already named)
# ---------------------------------------------------------------------------
def test_availability_deferred_locator_verbs():
    shipped = ("The curated benchmark dataset definitions, the analysis and aggregation "
               "scripts, and the NeoHeteroclitic source code are public at "
               "https://github.com/zhaoxiaofei/neoguider. The continuous-dataset matrices "
               "underlying Figure 4 will be added to that repository before publication. "
               "The repository is already public and is accessible to reviewers without "
               "restriction.")
    rows = fmt.availability_rows([shipped])
    check("FMT-AV1 reports the shipped 'will be added ... before publication' promise",
          any(r["rule"] == "FMT-AV1" for r in rows), str(rows)[:200])
    for text in ("Before publication, the matrices will be added to that repository.",
                 "The matrices will be uploaded to Zenodo upon publication.",
                 "The results will be released before publication.",
                 "The code will be made available before publication.",
                 "The data will be archived on acceptance."):
        rows = fmt.availability_rows([text])
        check(f"FMT-AV1 reports {text[:44]!r}",
              any(r["rule"] == "FMT-AV1" for r in rows), str(rows)[:160])
    clean = fmt.availability_rows([
        "All data are deposited at https://doi.org/10.5281/zenodo.1234567 and the code at "
        "https://github.com/zhaoxiaofei/paper-refine/tree/0bfedcc1.",
        "The manuscript was accepted for publication after revision.",
        "The discussion continues in the meantime with the planned analyses."])
    check("resolved or future-free statements stay clean",
          not [r for r in clean if r["rule"] == "FMT-AV1"], str(clean)[:200])


def main() -> int:
    sections = [("insert_ppr_extra_single_rpr", test_insert_ppr_extra_keeps_one_rpr),
                ("apply_ppr_extra_single_rpr", test_apply_ppr_extra_keeps_one_rpr),
                ("property_bag_edge_cases", test_property_bag_edge_cases),
                ("template_front_matter_schema", test_apply_word_template_front_matter_schema),
                ("conforming_paragraph", test_already_conforming_paragraph_is_left_alone),
                ("availability_deferred_locator_verbs",
                 test_availability_deferred_locator_verbs)]
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
    print("ALL 2026-1011 ROUND-2 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

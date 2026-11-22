#!/usr/bin/env python3
"""Regression tests for fix-bugs wave 1, batch E_p00 (paper_docx_format_parts/p00_core.py).

One hermetic block per confirmed candidate. A "pre-fix:" check fails on the
HEAD tree; the others guard the behaviour the fix must keep.

Run:  python3 .paper_test/test_fix_wave1_E_p00.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(WS))

import docx  # noqa: E402
import paper_docx_format as df  # noqa: E402

FAILS, TMPDIRS = [], []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def build_docx(tag: str, styles_extra: bytes = b"", doc_extra: bytes = b"") -> Path:
    p = Path(tempfile.mkdtemp(prefix="e_p00_")) / f"{tag}.docx"
    TMPDIRS.append(p.parent)
    d = docx.Document()
    d.add_paragraph("Hello")
    d.save(str(p))
    with zipfile.ZipFile(p) as z:
        read = {n: z.read(n) for n in z.namelist()}
    if styles_extra:
        read["word/styles.xml"] = read["word/styles.xml"].replace(
            b"</w:styles>", styles_extra + b"</w:styles>")
    if doc_extra:
        read["word/document.xml"] = read["word/document.xml"].replace(
            b"</w:body>", doc_extra + b"</w:body>")
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in read.items():
            z.writestr(n, data)
    return p


def main() -> int:
    # ---- F09: a nested text-box run's w:vanish must not hide the OUTER run
    run = ('<w:r><w:rPr><w:b/></w:rPr><w:t>Outer visible</w:t><w:drawing>'
           '<w:txbxContent><w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>box</w:t>'
           '</w:r></w:p></w:txbxContent></w:drawing></w:r>')
    check("F09 pre-fix: a nested text-box vanish does not hide the outer run",
          df._run_rpr_hidden(run) is False and df.text_of(run) == "Outer visible")
    check("F09 a genuinely hidden run and rPrChange history still behave",
          df.text_of('<w:r><w:rPr><w:vanish/></w:rPr><w:t>X</w:t></w:r>') == ""
          and df.text_of('<w:r><w:rPr><w:rPrChange><w:rPr><w:vanish/></w:rPr>'
                         '</w:rPrChange></w:rPr><w:t>X</w:t></w:r>') == "X")

    # ---- F27: the canonical declaration must be on the ROOT element
    x = ('<word:document xmlns:word="%s"><word:body><w:p xmlns:w="%s">'
         '<w:r><w:t>hi</w:t></w:r></w:p></word:body></word:document>'
         % (df.W_NS, df.W_NS))
    out = df.canonicalize_ooxml_prefixes(x)
    try:
        ET.fromstring(out)
        ok = True
    except ET.ParseError as e:
        ok, out = False, f"{out} [{e}]"
    check("F27 pre-fix: a nested-only canonical declaration still parses", ok, out)
    conv = f'<w:document xmlns:w="{df.W_NS}"><w:body><w:p/></w:body></w:document>'
    check("F27 a conventional part stays byte-identical",
          df.canonicalize_ooxml_prefixes(conv) == conv)

    # ---- F29: ppr_of/rpr_of read only the element's OWN direct property
    para = ('<w:p><w:r><w:t>Outer</w:t><w:drawing><w:txbxContent><w:p>'
            '<w:pPr><w:pStyle w:val="BoxStyle"/></w:pPr><w:r><w:rPr><w:i/>'
            '</w:rPr><w:t>box</w:t></w:r></w:p></w:txbxContent></w:drawing>'
            '</w:r></w:p>')
    check("F29 pre-fix: no inherited text-box pPr", df.ppr_of(para) is None
          and df.para_style(para) is None)
    run = ('<w:r><w:t>Outer</w:t><w:drawing><w:txbxContent><w:p><w:r>'
           '<w:rPr><w:i/></w:rPr><w:t>box</w:t></w:r></w:p></w:txbxContent>'
           '</w:drawing></w:r>')
    check("F29 pre-fix: no inherited text-box rPr", df.rpr_of(run) is None
          and df.run_is_italic({}, None, run) is False)
    check("F29 own and inner-content properties still resolve",
          df.ppr_of('<w:p><w:pPr><w:jc w:val="center"/></w:pPr></w:p>')
          == '<w:pPr><w:jc w:val="center"/></w:pPr>'
          and df.rpr_of('<w:r><w:rPr><w:i/></w:rPr><w:t>x</w:t></w:r>')
          == '<w:rPr><w:i/></w:rPr>'
          and df.ppr_of('<w:pPr><w:jc w:val="center"/></w:pPr>')
          == '<w:pPr><w:jc w:val="center"/></w:pPr>')

    # ---- F50: a field instruction is entity-decoded exactly once
    check("F50 pre-fix: '&amp;quot;' stays the literal '&quot;'",
          df._fld_simple_instruction(
              '<w:fldSimple w:instr="A &amp;quot;B&amp;quot; C">')
          == 'A &quot;B&quot; C')
    x = ('<w:p><w:fldSimple w:instr="ADDIN ZOTERO_ITEM CSL_CITATION '
         '{ &amp;quot;citationID&amp;quot;: &amp;quot;X&amp;quot; }">R'
         '</w:fldSimple></w:p>')
    check("F50 pre-fix: zotero inventory decodes once; a real '&quot;' still does",
          "&quot;citationID&quot;" in df.zotero_field_report(x)["fields"][0]["instr"]
          and df._fld_simple_instruction('<w:fldSimple w:instr="A &quot;B&quot; C">')
          == 'A "B" C')

    # ---- F95: a whitespace-closed paired w:i is removed, not duplicated
    out, _changed = df._rpr_set_emphasis('<w:rPr><w:i></w:i ></w:rPr>', False)
    check("F95 pre-fix: one w:i and one w:iCs, no leftover paired tag",
          "<w:i></w:i >" not in out and out.count("<w:i ") == 1
          and out.count("<w:iCs ") == 1, out)
    check("F95 a self-closing w:i still behaves",
          df._rpr_set_emphasis('<w:rPr><w:i/></w:rPr>', False)[0]
          == '<w:rPr><w:i w:val="0"/><w:iCs w:val="0"/></w:rPr>')

    # ---- F105 + F111: decoded style ids, no commented-out styles
    check("F105 pre-fix: ppr_style decodes a style id containing &",
          df.ppr_style('<w:pPr><w:pStyle w:val="Heading&amp;1"/></w:pPr>')
          == "Heading&1")
    p = build_docx("f105", styles_extra=(
        b'<!-- <w:style w:type="paragraph" w:styleId="CommentedOut">'
        b'<w:name w:val="CommentedOut"/></w:style> -->'
        b'<w:style w:type="paragraph" w:styleId="Heading&amp;1">'
        b'<w:name w:val="Heading&amp;1"/></w:style>'))
    ids = df.docx_style_ids(p)
    check("F111 pre-fix: a commented-out w:style is not a declared style",
          "CommentedOut" not in ids)
    check("F105 pre-fix: docx_style_ids decodes the id parse_styles keys",
          "Heading&1" in ids and "Heading&1" in df.docx_style_name_map(p))
    with zipfile.ZipFile(p) as z:
        check("F105 style_chain resolves the decoded id",
              df.style_chain(df.parse_styles(z), "Heading&1") == ["Heading&1"])

    # ---- F115: a fldSimple instruction containing a literal '>'
    x = ('<w:p><w:fldSimple w:instr="IF a > b &quot;yes&quot; &quot;no&quot;">'
         '<w:r><w:t>yes</w:t></w:r></w:fldSimple></w:p>')
    ranges = df.field_ranges(x)
    check("F115 pre-fix: the instruction survives a literal '>'",
          len(ranges) == 1 and ranges[0][2] == 'IF a > b "yes" "no"', repr(ranges))
    check("F115 the result is fenced; an empty fldSimple is still inventoried",
          bool(df.in_field(ranges, x.index("yes")))
          and len(df.field_ranges(
              '<w:p><w:fldSimple w:instr="IF a > b &quot;y&quot; &quot;n&quot;"/>'
              '<w:r><w:t>t</w:t></w:r></w:p>')) == 1)

    # ---- F116: a commented-out sectPr is not the live first section
    x = ('<w:body><w:p/><!-- <w:sectPr><w:headerReference w:type="even" '
         'r:id="rIdCOMMENT"/></w:sectPr> --><w:sectPr><w:headerReference '
         'w:type="first" r:id="rIdLIVE"/></w:sectPr></w:body>')
    got = df.first_section_props(x) or ""
    check("F116 pre-fix: the live first section is read, not the comment",
          "rIdLIVE" in got and "rIdCOMMENT" not in got, got)
    check("F116 pre-fix: a commented-only section is not a live section",
          df.first_section_props(
              '<w:body><!-- <w:sectPr><w:pgSz w:w="1"/></w:sectPr> --></w:body>')
          is None)
    p = build_docx("f116", doc_extra=(
        b'<!-- <w:sectPr><w:headerReference w:type="even" r:id="rX"/>'
        b'</w:sectPr> --><w:sectPr><w:headerReference w:type="first" r:id="rY"/>'
        b'</w:sectPr>'))
    check("F116 pre-fix: _template_uses_even_odd ignores the commented reference",
          df._template_uses_even_odd(p) is False)

    # ---- F128: every mc:Choice after the first is unrendered
    def ac(extra):
        return ('<w:p><w:r><w:t>OUT</w:t></w:r><mc:AlternateContent>' + extra
                + '</mc:AlternateContent></w:p>')
    two = ('<mc:Choice Requires="wps"><w:r><w:t>ACHOICE1</w:t></w:r></mc:Choice>'
           '<mc:Choice Requires="wpg"><w:r><w:t>ACHOICE2</w:t></w:r></mc:Choice>'
           '<mc:Fallback><w:r><w:t>AFALL</w:t></w:r></mc:Fallback>')
    one = ('<mc:Choice Requires="wps"><w:r><w:t>ACHOICE1</w:t></w:r></mc:Choice>'
           '<mc:Fallback><w:r><w:t>AFALL</w:t></w:r></mc:Fallback>')
    check("F128 pre-fix: only the first Choice is read",
          df.text_of(ac(two)) == "OUTACHOICE1", repr(df.text_of(ac(two))))
    check("F128 pre-fix: the paragraph/run walkers see the text once",
          [df.text_of(r[2]) for r in df.runs(ac(two))] == ["OUT", "ACHOICE1"])
    check("F128 one Choice + Fallback, and a Choice-less Fallback, are unchanged",
          df.text_of(ac(one)) == "OUTACHOICE1"
          and df.text_of(ac('<mc:Fallback><w:r><w:t>AFALL</w:t></w:r>'
                            '</mc:Fallback>')) == "OUTAFALL")

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL E_p00 FIX-BUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
    sys.exit(rc)

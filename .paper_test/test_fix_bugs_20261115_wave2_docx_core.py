#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 2, group `docx_core`.

Every check pins one candidate this wave re-validated on the tree and repaired:
F22 (nested `mc:AlternateContent`), F23 (OMML math deleted as an empty
paragraph), F24 (XML comments read as text), F25 (tracked-deleted rows / cells /
`w:moveFrom` read as live), F26 (`w:sectPrChange` read as the live section),
F30 (single-newline reference list read as one entry), F32 (scheme-less URL
rewritten by the spelling fixer), F33 (plural stemmer bypasses the context
stopwords) and F34 (`negative_claim_rows` row cap with no INCOMPLETE row).

Hermetic: every fixture lives under `tempfile.mkdtemp()`; the DOCX packages are
built inline with `zipfile`.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_docx_core.py
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FAILS = []
TMPDIRS = []

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = load("fb1115wave2_docx_core_fmt", "paper_docx_format.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def docx_package(path: Path, document_xml: str, rels: str = "",
                 parts: dict | None = None, settings: str = "") -> Path:
    """A minimal but readable DOCX package (document + rels + extra parts)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   f'<?xml version="1.0"?><Types xmlns="{CT}">'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Default Extension="rels" ContentType="application/'
                   'vnd.openxmlformats-package.relationships+xml"/></Types>')
        z.writestr("_rels/.rels",
                   f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}">'
                   f'<Relationship Id="rId1" Type="{R}/officeDocument" '
                   'Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/_rels/document.xml.rels",
                   rels or f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}"/>')
        if settings:
            z.writestr("word/settings.xml", settings)
        for name, body in (parts or {}).items():
            z.writestr(name, body)
    return path


# ---------------------------------------------------------------------------
# F22 -- nested mc:AlternateContent
# ---------------------------------------------------------------------------
def test_f22_nested_alternate_content() -> None:
    print("\n== F22 nested mc:AlternateContent: the OUTER Fallback is not content ==")
    inner = ('<mc:AlternateContent><mc:Choice Requires="wpg">'
             '<w:p><w:r><w:t>IN</w:t></w:r></w:p></mc:Choice>'
             '<mc:Fallback><w:p><w:r><w:t>INFB</w:t></w:r></w:p></mc:Fallback>'
             '</mc:AlternateContent>')
    outer = ('<w:p><w:r><w:t>OUT1</w:t></w:r>'
             '<w:r><mc:AlternateContent><mc:Choice Requires="wps">'
             '<w:drawing><w:txbxContent>' + inner + '</w:txbxContent></w:drawing>'
             '</mc:Choice><mc:Fallback><w:p><w:r><w:t>OUTFB</w:t></w:r></w:p>'
             '</mc:Fallback></mc:AlternateContent></w:r>'
             '<w:r><w:t>OUT2</w:t></w:r></w:p>')
    check("F22 text_of keeps the visible branch and drops the outer Fallback",
          fmt.text_of(outer) == "OUT1OUT2", repr(fmt.text_of(outer)))
    texts = [fmt.text_of(p[2]) for p in fmt.paragraphs(outer)]
    check("F22 paragraphs() never returns the unrendered OUTER Fallback",
          texts == ["OUT1OUT2", "IN"], texts)
    check("F22 the inner Choice text is not lost from the paragraph model",
          "IN" in texts, texts)
    check("F22 no Fallback text reaches runs()",
          "".join(fmt.text_of(r[2]) for r in fmt.runs(outer)) == "OUT1OUT2",
          "".join(fmt.text_of(r[2]) for r in fmt.runs(outer)))

    host = ('<w:p><w:r><w:t>OUT1</w:t></w:r><w:r><mc:AlternateContent>'
            '<mc:Choice Requires="wps"><w:drawing><w:txbxContent>' + inner
            + '</w:txbxContent></w:drawing></mc:Choice>'
            '<mc:Fallback><w:r><w:t>OUTFB</w:t></w:r></mc:Fallback>'
            '</mc:AlternateContent></w:r><w:r><w:t>OUT2</w:t></w:r></w:p>')
    check("F22 host-level outer-Fallback text is not read as live prose",
          fmt.text_of(host) == "OUT1OUT2", repr(fmt.text_of(host)))

    plain = ('<w:p><w:r><w:t>See </w:t></w:r><mc:AlternateContent>'
             '<mc:Choice Requires="wps"><w:r><w:t>ChoiceText</w:t></w:r></mc:Choice>'
             '<mc:Fallback><w:r><w:t>FallbackText</w:t></w:r></mc:Fallback>'
             '</mc:AlternateContent></w:p>')
    check("F22 a non-nested AlternateContent still reads only its Choice",
          fmt.text_of(plain) == "See ChoiceText", repr(fmt.text_of(plain)))


# ---------------------------------------------------------------------------
# F23 -- OMML math is content
# ---------------------------------------------------------------------------
def test_f23_math_is_content() -> None:
    print("\n== F23 OMML math: an equation paragraph is never 'empty' ==")
    xml = ('<w:document><w:body>'
           '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
           '<w:r><w:t>Methods</w:t></w:r></w:p>'
           '<w:p/>'
           '<w:p><m:oMathPara><m:oMath><m:r><m:t>x=1</m:t></m:r></m:oMath>'
           '</m:oMathPara></w:p>'
           '<w:p/>'
           '<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>'
           '</w:body></w:document>')
    paras = fmt.paragraphs(xml)
    math = paras[2][2]
    check("F23 has_math recognises an <m:oMathPara>",
          fmt.has_math(math) and not fmt.has_math(paras[4][2]),
          f"{fmt.has_math(math)} {fmt.has_math(paras[4][2])}")
    groups, _prescribed = fmt.stray_empty_paragraph_groups(
        paras, dict(fmt.POLICY_DEFAULTS), xml)
    drop = {i for indices, _kind in groups for i in indices}
    check("F23 the equation paragraph is not a stray-empty paragraph",
          2 not in drop, sorted(drop))
    check("F23 the truly empty neighbours are still stray",
          {1, 3} == drop, sorted(drop))
    new, changes, _meta = fmt.fix_document(xml, {}, dict(fmt.POLICY_DEFAULTS))
    check("F23 fix_document keeps the display equation", "oMath" in new, changes)
    check("F23 the fix still deletes the two real blank lines",
          new.count("<w:p/>") == 0, changes)

    break_math = ('<w:p><w:r><w:br w:type="page"/></w:r>'
                  '<m:oMathPara><m:oMath><m:r><m:t>y=2</m:t></m:r></m:oMath>'
                  '</m:oMathPara></w:p>')
    check("F23 a page-break + equation paragraph is not break-only",
          fmt._break_only_paragraph(break_math) is False)
    break_only = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    check("F23 a genuinely break-only paragraph is still reported",
          fmt._break_only_paragraph(break_only) is True)


# ---------------------------------------------------------------------------
# F24 -- XML comments are not content
# ---------------------------------------------------------------------------
def test_f24_comments_are_not_content() -> None:
    print("\n== F24 XML comments: a commented-out paragraph is not prose ==")
    xml = ('<w:document><w:body>'
           '<w:p><w:r><w:t>The tumor color map is red.</w:t></w:r></w:p>'
           '<!-- <w:p><w:r><w:t>The tumour colour map was retired.</w:t></w:r>'
           '</w:p> -->'
           '</w:body></w:document>')
    doc = fmt.analyse_document(xml, {}, dict(fmt.POLICY_DEFAULTS), "x.docx")
    check("F24 the commented paragraph is not a paragraph",
          doc["paras"] == 1, doc["paras"])
    check("F24 the commented text is not counted as words",
          doc["words"] == 6, doc["words"])
    check("F24 no spelling row is filed from the comment",
          [r for r in doc["rows"] if r["rule"] == "FMT-T8d"] == [],
          [r.get("evidence") for r in doc["rows"] if r["rule"] == "FMT-T8d"])
    check("F24 text_of skips a commented <w:t>",
          fmt.text_of('<w:body><w:p><w:r><w:t>live</w:t></w:r>'
                      '<!-- <w:t>ghost</w:t> --></w:p></w:body>') == "live")

    unclosed = ('<w:body><!-- <w:p> --><w:p><w:r><w:t>One</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Two</w:t></w:r></w:p></w:body>')
    check("F24 an unclosed tag in a comment does not adopt later paragraphs",
          [fmt.text_of(p[2]) for p in fmt.paragraphs(unclosed)] == ["One", "Two"],
          [fmt.text_of(p[2]) for p in fmt.paragraphs(unclosed)])

    pol = dict(fmt.POLICY_DEFAULTS)
    pol["quote_style"] = "curly"
    quoted = ('<w:body><w:p><w:r><w:t>He said "hi".</w:t></w:r>'
              '<!-- <w:r><w:t>retired "quote"</w:t></w:r> --></w:p></w:body>')
    new, _changes, _meta = fmt.fix_document(quoted, {}, pol)
    check("F24 the fixer does not rewrite a <w:t> inside a comment",
          '<!-- <w:r><w:t>retired "quote"</w:t></w:r> -->' in new, new)
    check("F24 the fixer still normalizes the live quotation",
          "He said \u201chi\u201d." in new, new)


# ---------------------------------------------------------------------------
# F25 -- tracked deletions are not live content
# ---------------------------------------------------------------------------
def test_f25_tracked_deletions_are_hidden() -> None:
    print("\n== F25 tracked-deleted rows/cells + moveFrom are not live prose ==")
    xml = ('<w:document><w:body>'
           '<w:p><w:r><w:t>The tumor cells grew.</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:trPr><w:del w:id="1" w:author="a"/></w:trPr>'
           '<w:tc><w:p><w:r><w:t>The tumour cells shrank after treatment.</w:t>'
           '</w:r></w:p></w:tc></w:tr>'
           '<w:tr><w:tc><w:p><w:r><w:t>The control cells were untreated.</w:t>'
           '</w:r></w:p></w:tc></w:tr></w:tbl>'
           '<w:p><w:moveFrom w:id="3" w:author="a"><w:r><w:t>moved old sentence'
           '</w:t></w:r></w:moveFrom>'
           '<w:moveTo w:id="4" w:author="a"><w:r><w:t>moved new sentence</w:t>'
           '</w:r></w:moveTo></w:p>'
           '</w:body></w:document>')
    doc = fmt.analyse_document(xml, {}, dict(fmt.POLICY_DEFAULTS), "x.docx")
    texts = [fmt.text_of(p[2]) for p in fmt.paragraphs(xml)]
    check("F25 the deleted row's paragraph is not live",
          "The tumour cells shrank after treatment." not in texts, texts)
    check("F25 moveFrom is not read (moveTo is the live copy)",
          "moved old sentence" not in "".join(texts)
          and "moved new sentence" in "".join(texts), texts)
    check("F25 the word count no longer counts deleted text",
          doc["words"] == 12, doc["words"])
    check("F25 the deleted row's spelling variant files no row",
          [r for r in doc["rows"] if r["rule"] == "FMT-T8d"] == [],
          [r.get("evidence") for r in doc["rows"] if r["rule"] == "FMT-T8d"])

    cell = ('<w:tbl><w:tr><w:tc><w:tcPr>'
            '<w:cellDel w:id="2" w:author="a"/></w:tcPr>'
            '<w:p><w:r><w:t>GONE</w:t></w:r></w:p></w:tc>'
            '<w:tc><w:p><w:r><w:t>LIVE</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    check("F25 a cellDel cell is hidden and its sibling stays",
          [fmt.text_of(p[2]) for p in fmt.paragraphs(cell)] == ["LIVE"],
          [fmt.text_of(p[2]) for p in fmt.paragraphs(cell)])

    ins = ('<w:tbl><w:tr><w:trPr><w:ins w:id="5" w:author="a"/></w:trPr>'
           '<w:tc><w:p><w:r><w:t>INSERTED ROW</w:t></w:r></w:p></w:tc>'
           '</w:tr></w:tbl>')
    check("F25 an inserted row is still live",
          [fmt.text_of(p[2]) for p in fmt.paragraphs(ins)] == ["INSERTED ROW"],
          [fmt.text_of(p[2]) for p in fmt.paragraphs(ins)])

    # Hiding a tracked deletion must not turn a paragraph that CARRIES one into
    # a deletable break-only paragraph (that would discard the revision).
    rev_break = ('<w:p><w:r><w:br w:type="page"/></w:r>'
                 '<w:del w:id="9" w:author="a"><w:r><w:t>old</w:t></w:r>'
                 '</w:del></w:p>')
    check("F25 a break-only paragraph carrying a tracked change is not deleted",
          fmt._break_only_paragraph(rev_break) is False)


# ---------------------------------------------------------------------------
# F26 -- w:sectPrChange is history, not the live section
# ---------------------------------------------------------------------------
def test_f26_sectpr_change() -> None:
    print("\n== F26 w:sectPrChange: the obsolete section does not win ==")
    doc = (f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>'
           '<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
           '<w:p><w:pPr><w:sectPr>'
           '<w:headerReference w:type="default" r:id="rId5"/>'
           '<w:sectPrChange w:id="7" w:author="a"><w:sectPr>'
           '<w:headerReference w:type="default" r:id="rId9"/>'
           '</w:sectPr></w:sectPrChange>'
           '</w:sectPr></w:pPr></w:p></w:body></w:document>')
    first = fmt.first_section_props(doc) or ""
    check("F26 first_section_props returns the LIVE section (balanced, whole)",
          first.startswith("<w:sectPr>") and first.rstrip().endswith("</w:sectPr>"),
          repr(first[:80]))
    check("F26 the change record is not part of the live section text",
          "rId9" not in first and "<w:sectPrChange" not in first, repr(first))
    check("F26 the live header reference survives",
          'r:id="rId5"' in first, repr(first))
    spans = fmt.SECT_READ_RE.findall(doc)
    check("F26 SECT_READ_RE matches the live section, not the nested old one",
          len(spans) == 1 and spans[0].rstrip().endswith("</w:sectPr>")
          and "<w:sectPrChange" in spans[0], [s[:60] for s in spans])

    tmp = scratch("fb1115wave2_f26_")
    pkg = docx_package(
        tmp / "pkg.docx", doc,
        rels=f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}">'
             f'<Relationship Id="rId5" Type="{R}/header" Target="header5.xml"/>'
             f'<Relationship Id="rId9" Type="{R}/header" Target="header9.xml"/>'
             '</Relationships>',
        parts={
            "word/header5.xml":
                f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>plain</w:t></w:r></w:p></w:hdr>',
            "word/header9.xml":
                f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:drawing/></w:r></w:p></w:hdr>',
        })
    rep = fmt.docx_front_matter_report(pkg)
    check("F26 the live default header is still resolved",
          rep.get("first_header") is True, rep)
    check("F26 the logo is not reported from the obsolete header",
          rep.get("logo_header") is False, rep)

    even_old = (f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body><w:p>'
                '<w:pPr><w:sectPr>'
                '<w:sectPrChange w:id="8" w:author="a"><w:sectPr>'
                '<w:headerReference w:type="even" r:id="rId7"/>'
                '</w:sectPr></w:sectPrChange>'
                '</w:sectPr></w:pPr></w:p></w:body></w:document>')
    even_live = even_old.replace('<w:sectPr><w:sectPrChange', '<w:sectPr>'
                                 '<w:headerReference w:type="even" r:id="rId6"/>'
                                 '<w:sectPrChange')
    tpl_old = docx_package(tmp / "old_tpl.docx", even_old)
    tpl_live = docx_package(tmp / "live_tpl.docx", even_live)
    check("F26 an even-page reference only in the change record is not parity use",
          fmt._template_uses_even_odd(tpl_old) is False)
    check("F26 a live even-page reference is still parity use",
          fmt._template_uses_even_odd(tpl_live) is True)


# ---------------------------------------------------------------------------
# F30 -- single-newline reference lists are per-entry
# ---------------------------------------------------------------------------
def test_f30_single_newline_references() -> None:
    print("\n== F30 a paragraph-per-line reference list is split per entry ==")
    rows = [("References", False, True),
            ("1. Smith J. Title one. Nature. 2016;511:430-440. "
             "doi:10.1000/gb-2015-0001", False, False),
            ("2. Doe A. Title two. Science. 2019;363:123. "
             "doi:10.1000/gb-2019-0002", False, False)]
    entries = fmt.reference_entries([("paper.docx", rows)])
    check("F30 two single-newline entries are two entries",
          len(entries) == 2, entries)
    check("F30 each entry carries only its own text",
          all("Title two" not in body for _d, _l, body in entries[:1]),
          entries)
    ints = fmt.reference_integrity_rows([("paper.docx", rows)])
    years = {r["identifier"]: r["year"] for r in ints}
    check("F30 each DOI gets its own entry's year",
          years.get("10.1000/gb-2015-0001") == "2016"
          and years.get("10.1000/gb-2019-0002") == "2019", years)
    check("F30 no DOI row carries the whole list",
          all("10.1000/gb-2019-0002" not in r["text"] for r in ints if
              r["identifier"] == "10.1000/gb-2015-0001"), ints)

    wrapped = [("References", False, True),
               ("1. Smith J. A title that wraps onto the next line\n"
                "of the paragraph. Nature. 2016;511:430.", False, False),
               ("2. Doe A. Title two. Science. 2019;363:123. "
                "doi:10.1000/gb-2019-0002", False, False)]
    check("F30 a hard-wrapped entry is not split mid-entry",
          len(fmt.reference_entries([("p.docx", wrapped)])) == 2,
          [e[2][:40] for e in fmt.reference_entries([("p.docx", wrapped)])])

    raw = ("References\n\n1. Smith J. Title. 2016.\n\n2. Doe A. Title. 2019.")
    check("F30 a one-row raw text source keeps the blank-line split",
          len(fmt.reference_entries([("a.tex", [(raw, False, False)])])) == 2,
          fmt.reference_entries([("a.tex", [(raw, False, False)])]))


# ---------------------------------------------------------------------------
# F32 -- scheme-less host/path URLs are not prose
# ---------------------------------------------------------------------------
def test_f32_schemeless_url_mask() -> None:
    print("\n== F32 the spelling fixer never rewrites a scheme-less URL ==")
    prose = ["The color map is red.",
             "The dataset is at github.com/lab/colour-tool for reuse."]
    masked = fmt.spelling_nonprose_mask(prose[1])
    check("F32 the bare repository URL is masked, same length",
          "colour" not in masked and len(masked) == len(prose[1]),
          repr(masked))
    check("F32 the URL occurrence no longer decides the minority",
          fmt.spelling_minority_targets(prose) == {},
          fmt.spelling_minority_targets(prose))
    # A body occurrence still decides the direction for real prose.
    both = ["The color map is red.", "The colour map is blue.",
            "The dataset is at github.com/lab/colour-tool for reuse."]
    check("F32 the body spelling still decides the target",
          fmt.spelling_minority_targets(both) == {"colour": "color"},
          fmt.spelling_minority_targets(both))

    pol = dict(fmt.POLICY_DEFAULTS)
    pol["term_spelling"] = "dominant"
    xml = ('<w:body>'
           '<w:p><w:r><w:t>The color map is red.</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>The colour map is blue.</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>The dataset is at github.com/lab/colour-tool '
           'for reuse.</w:t></w:r></w:p>'
           '</w:body>')
    new, _changes, _meta = fmt.fix_document(xml, {}, pol)
    check("F32 the fixer normalizes the body occurrence",
          "The color map is blue." in new, new[-200:])
    check("F32 the fixer leaves the repository path untouched",
          "github.com/lab/colour-tool" in new, new[-200:])


# ---------------------------------------------------------------------------
# F33 -- the plural stemmer must not bypass the context stopwords
# ---------------------------------------------------------------------------
def test_f33_context_stopwords() -> None:
    print("\n== F33 generic plural column names are stopped before stemming ==")
    for word in ("values", "tables", "files", "value", "table", "file"):
        check(f"F33 _context_tokens({word!r}) is empty",
              fmt._context_tokens(word) == set(), fmt._context_tokens(word))
    check("F33 a substantive noun still survives",
          fmt._context_tokens("cells") == {"cell"},
          fmt._context_tokens("cells"))
    check("F33 a plural of a substantive noun still survives",
          fmt._context_tokens("samples") == {"sampl"},
          fmt._context_tokens("samples"))


# ---------------------------------------------------------------------------
# F34 -- negative_claim_rows' row cap is not silent
# ---------------------------------------------------------------------------
def test_f34_negative_claim_row_cap() -> None:
    print("\n== F34 the M30-NC row cap appends an INCOMPLETE row ==")
    table = "sample,tool\n" + "\n".join(f"S{i},TOOL{i}" for i in range(1, 6))
    texts = [f"TOOL1 could not be run in analysis number {i} "
             f"(dataset cohort {i})." for i in range(1, 61)]
    rows = fmt.negative_claim_rows(texts, [("t.csv", table)], limit=40)
    gaps = [r for r in rows if r.get("token") == "(truncated)"]
    check("F34 the cap still stops at 40 claim rows",
          len([r for r in rows if r.get("token") != "(truncated)"]) == 40,
          len(rows))
    check("F34 the cap now appends one M30-NC gap row",
          len(gaps) == 1 and gaps[0]["rule"] == "M30-NC",
          [r.get("detail") for r in gaps])
    check("F34 the gap states how many claims were not compared",
          gaps and "20 further written negative claim(s)" in gaps[0]["detail"],
          gaps[0]["detail"] if gaps else "")
    check("F34 the gap is INCOMPLETE, not a silent cut",
          gaps and "INCOMPLETE" in gaps[0]["detail"],
          gaps[0]["detail"] if gaps else "")
    short = fmt.negative_claim_rows(texts[:3], [("t.csv", table)], limit=40)
    check("F34 no gap row when the cap is not reached",
          [r for r in short if r.get("token") == "(truncated)"] == [], short)


def main() -> int:
    test_f22_nested_alternate_content()
    test_f23_math_is_content()
    test_f24_comments_are_not_content()
    test_f25_tracked_deletions_are_hidden()
    test_f26_sectpr_change()
    test_f30_single_newline_references()
    test_f32_schemeless_url_mask()
    test_f33_context_stopwords()
    test_f34_negative_claim_row_cap()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL WAVE-2 docx_core CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

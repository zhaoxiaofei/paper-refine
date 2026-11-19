#!/usr/bin/env python3
"""Regression checks for the 2026-11-19 fix-bugs wave 1, group `g9_docx`.

Every check pins one candidate this wave re-validated on the tree and repaired
(F188, F189, F190, F191, F192, F193, F194, F195, F197, F198). Fixtures are
tiny inline OOXML strings (plus whole-DOCX-shaped XML through `fix_document`),
so the file is hermetic.

F199 is a FALSE POSITIVE on this tree: `ooxml_part_text` canonicalises an
aliased WordprocessingML prefix before any reader runs (see
`test_fix_bugs_20261115_run2_wave3.py::test_f036_ooxml_namespace_aliases`), so
the raw-fragment probe in the candidate does not describe a package read.

Run:  python3 .paper_test/test_fix_bugs_20261119_g9_docx.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

WS = Path(__file__).resolve().parent.parent
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WQ = "{" + W + "}"
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = load("fb1119_g9_docx_fmt", "paper_docx_format.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def nested_runs(xml: str) -> int:
    """Number of `w:r` elements that contain another `w:r` (invalid CT_R)."""
    root = ET.fromstring(xml)
    return sum(1 for run in root.iter(WQ + "r")
               if len(list(run.iter(WQ + "r"))) > 1)


def para(inner: str) -> str:
    return f'<w:p xmlns:w="{W}">{inner}</w:p>'


def doc(body: str) -> str:
    return f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'


# ---------------------------------------------------------------------------
# F188 -- a zero-length insertion at a break/sym is a bare w:t, not a nested run
# ---------------------------------------------------------------------------
def test_f188_zero_insertion_at_break() -> None:
    print("\n== F188: a zero-length insertion at a break/symbol emits a bare w:t ==")
    p = para("<w:r><w:br/><w:br/></w:r>")
    out, applied = fmt.rewrite_text_spans(p, [(1, 1, "X")])
    check("F188 the insertion between two breaks is reported applied",
          applied == [(1, 1, "", "X")], str(applied))
    check("F188 the emitted paragraph is well-formed XML",
          nested_runs(out) == 0, out)
    check("F188 the insertion lands BEFORE the second break in text order",
          fmt.text_of(out) == "\nX\n", repr(fmt.text_of(out)))
    check("F188 no `<w:r>` is nested inside the enclosing run",
          "<w:r><w:r" not in out.replace(" ", ""), out)

    sym = para('<w:r><w:sym w:font="Arial" w:char="F0E0"/><w:br/></w:r>')
    out2, applied2 = fmt.rewrite_text_spans(sym, [(0, 0, "X")])
    check("F188 an insertion at a w:sym is reported applied",
          applied2 == [(0, 0, "", "X")], str(applied2))
    check("F188 the w:sym paragraph has no nested run and parses",
          nested_runs(out2) == 0, out2)
    check("F188 the insertion precedes the symbol glyph",
          fmt.text_of(out2) == "X\ufffd\n", repr(fmt.text_of(out2)))


# ---------------------------------------------------------------------------
# F189 -- a self-closing `<w:t />` is not an opening tag
# ---------------------------------------------------------------------------
def test_f189_self_closing_wt() -> None:
    print("\n== F189: a self-closing `<w:t />` never swallows the following runs ==")
    q = ('<w:p><w:r><w:t />text</w:r><w:r><w:rPr><w:b/></w:rPr>'
         "<w:t>hello</w:t></w:r></w:p>")
    spans = list(fmt._iter_wt_elements(q))
    check("F189 only the real w:t element is yielded",
          spans == [(53, 69, "hello")], str(spans))
    out = fmt._replace_text_in_para(q, "hello", "bye")
    check("F189 the replacement applies", out is not None and "bye" in (out or ""), str(out))
    check("F189 live markup is never escaped into text",
          out is not None and "&lt;" not in out and "<w:b/>" in out, str(out))
    check("F189 the self-closing element and the enclosing runs survive",
          out is not None and "<w:t />text</w:r>" in out
          and "<w:rPr><w:b/></w:rPr>" in out, str(out))


# ---------------------------------------------------------------------------
# F190 -- a match crossing a break/soft token is refused, not relocated
# ---------------------------------------------------------------------------
def test_f190_break_crossing_refused() -> None:
    print("\n== F190: a replacement crossing a break is refused ==")
    r = ('<w:p><w:r><w:t>10. Sm</w:t></w:r><w:r><w:br/></w:r>'
         "<w:r><w:t>ith J. 2020.</w:t></w:r></w:p>")
    before = fmt.text_of(r)
    check("F190 the fixture's visible text crosses the break",
          before == "10. Sm\nith J. 2020.", repr(before))
    out = fmt._replace_text_in_para(r, "Smith J. 2020.", "Smith, J. (2020).")
    check("F190 the crossing edit is refused", out is None, str(out))
    check("F190 the line break is not relocated to the paragraph end",
          out is None or fmt.text_of(out) == before, repr(fmt.text_of(out or r)))
    # A match that does NOT cross the break still applies.
    plain = ('<w:p><w:r><w:t>Volume 11-2020, </w:t></w:r>'
             "<w:r><w:t>565825 (2020).</w:t></w:r></w:p>")
    applied = fmt._replace_text_in_para(plain, "Volume 11-2020, ", "11, 565825 ")
    check("F190 an ordinary multi-run replacement is still applied",
          applied is not None and "11, 565825" in fmt.text_of(applied),
          str(applied))


# ---------------------------------------------------------------------------
# F191 -- two insertions at one offset keep the caller's order
# ---------------------------------------------------------------------------
def test_f191_same_offset_insertion_order() -> None:
    print("\n== F191: same-offset insertions keep caller order ==")
    p = '<w:p><w:r><w:t>xyz</w:t></w:r></w:p>'
    out, applied = fmt.rewrite_text_spans(p, [(1, 1, "2"), (1, 1, "1")])
    check("F191 the two insertions are emitted in caller order (2 then 1)",
          fmt.text_of(out) == "x21yz", repr(fmt.text_of(out)))
    check("F191 `applied` reports the caller's order",
          applied == [(1, 1, "", "2"), (1, 1, "", "1")], str(applied))
    out2, _applied2 = fmt.rewrite_text_spans(p, [(0, 0, "B"), (0, 0, "A")])
    check("F191 B then A is BA, not the lexicographic AB",
          fmt.text_of(out2) == "BAxyz", repr(fmt.text_of(out2)))


# ---------------------------------------------------------------------------
# F192 -- overlapping splices keep the outer range and lose no bytes
# ---------------------------------------------------------------------------
def test_f192_apply_edits_overlap() -> None:
    print("\n== F192: overlapping splices never delete the intervening bytes ==")
    got = fmt.apply_edits("0123456789", [(5, 7, "X"), (3, 9, "Y")])
    check("F192 the containing range wins and the tail `9` survives",
          got == "012Y9", repr(got))
    got2 = fmt.apply_edits("0123456789", [(3, 9, "Y"), (5, 7, "X")])
    check("F192 caller order does not change the no-loss result",
          got2 == "012Y9", repr(got2))
    got3 = fmt.apply_edits("0123456789", [(3, 7, "X"), (5, 9, "Y")])
    check("F192 a partial overlap keeps every byte outside the winning range",
          got3 == "012X789", repr(got3))
    got4 = fmt.apply_edits("0123456789", [(1, 3, "A"), (5, 7, "B")])
    check("F192 disjoint edits are unchanged",
          got4 == "0A34B789", repr(got4))
    got5 = fmt.apply_edits("0123456789", [(4, 4, "A"), (4, 4, "B")])
    check("F192 two insertions at one offset are both written in caller order",
          got5 == "0123AB456789", repr(got5))


# ---------------------------------------------------------------------------
# F193 -- the before-the-edit record inside *PrChange is history
# ---------------------------------------------------------------------------
def test_f193_change_record_preserved() -> None:
    print("\n== F193: `*PrChange` keeps its recorded old formatting ==")
    ppr = ('<w:pPr><w:spacing w:before="100"/>'
           '<w:pPrChange w:id="1" w:author="A"><w:pPr>'
           '<w:spacing w:before="200"/><w:jc w:val="center"/>'
           "</w:pPr></w:pPrChange></w:pPr>")
    out, removed = fmt._strip_direct_format(ppr)
    check("F193 only the live direct property is counted/removed",
          removed == 1 and '<w:spacing w:before="100"/>' not in out, f"removed={removed} {out}")
    check("F193 the recorded old spacing survives byte-identically",
          '<w:spacing w:before="200"/>' in out, out)
    check("F193 the recorded old alignment survives too",
          '<w:jc w:val="center"/>' in out, out)
    check("F193 the change record itself is untouched",
          fmt._strip_direct_format(ppr)[0].count("<w:pPrChange") == 1
          and fmt._strip_direct_format(ppr)[0].endswith("</w:pPrChange></w:pPr>"), out)

    rpr = ('<w:rPr><w:sz w:val="28"/>'
           '<w:rPrChange w:id="2" w:author="A"><w:rPr><w:sz w:val="24"/>'
           "</w:rPr></w:rPrChange></w:rPr>")
    rout, rremoved = fmt._strip_direct_format(rpr)
    check("F193 a live run size is stripped while the recorded one survives",
          rremoved == 1 and '<w:sz w:val="28"/>' not in rout
          and '<w:sz w:val="24"/>' in rout, f"removed={rremoved} {rout}")


# ---------------------------------------------------------------------------
# F194 -- the template section is read balanced, not truncated at the record
# ---------------------------------------------------------------------------
def test_f194_template_section_balanced() -> None:
    print("\n== F194: the template section read is balanced and live-only ==")
    s = ('<w:sectPr><w:pgSz w:w="100" w:h="200"/>'
         '<w:sectPrChange w:id="1" w:author="A"><w:sectPr>'
         '<w:pgSz w:w="999" w:h="999"/><w:docGrid w:linePitch="111"/>'
         "</w:sectPr></w:sectPrChange></w:sectPr>")
    found = fmt._SECT_RE.findall(s)
    check("F194 the section regex returns the complete element",
          found == [s], str(found))
    check("F194 the section regex accepts a self-closing sectPr",
          fmt._SECT_RE.search('<w:sectPr w:rsidR="00A1"/>') is not None)
    manuscript = doc('<w:p><w:r><w:t>x</w:t></w:r></w:p>'
                     '<w:sectPr><w:pgSz w:w="10" w:h="20"/></w:sectPr>')
    template = doc(s)
    out, applied = fmt._adopt_page_geometry(manuscript, template)
    check("F194 the manuscript section is adopted", applied is True, str(applied))
    check("F194 the live template geometry is written",
          '<w:pgSz w:w="100" w:h="200"/>' in out, out)
    check("F194 obsolete geometry from the change record is never adopted",
          'linePitch="111"' not in out and 'w:w="999"' not in out, out)
    ET.fromstring(out)


# ---------------------------------------------------------------------------
# F195 -- geometry is looked up and spliced only in the live section
# ---------------------------------------------------------------------------
def test_f195_live_section_only() -> None:
    print("\n== F195: a missing live geometry element is not found in history ==")
    manuscript = doc(
        '<w:p><w:r><w:t>x</w:t></w:r></w:p>'
        '<w:sectPr><w:pgSz w:w="100" w:h="200"/>'
        '<w:sectPrChange w:id="1" w:author="A"><w:sectPr>'
        '<w:pgMar w:top="111" w:left="111"/>'
        "</w:sectPr></w:sectPrChange></w:sectPr>")
    template = doc(
        '<w:sectPr><w:pgSz w:w="300" w:h="400"/>'
        '<w:pgMar w:top="222" w:left="222"/></w:sectPr>')
    out, applied = fmt._adopt_page_geometry(manuscript, template)
    check("F195 the manuscript section is adopted", applied is True, str(applied))
    live, _sep, history = out.partition("<w:sectPrChange")
    check("F195 the live section now carries the template page margins",
          "w:top=\"222\"" in live and "w:left=\"222\"" in live, live)
    check("F195 the tracked-change before-state keeps its own margins",
          "w:top=\"111\"" in history and "w:left=\"111\"" in history, history)
    check("F195 no template margin was written into revision history",
          "w:top=\"222\"" not in history, history)
    check("F195 the live margin lands before (not after) the change record",
          out.index('w:top="222"') < out.index("<w:sectPrChange"), out)
    ET.fromstring(out)


# ---------------------------------------------------------------------------
# F197 -- the break-only paragraph loop is not capped at 50
# ---------------------------------------------------------------------------
def test_f197_no_fifty_paragraph_cap() -> None:
    print("\n== F197: every break-only paragraph is repaired, not only 50 ==")
    breaks = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>' * 60
    xml = doc(breaks + "<w:p><w:r><w:t>Hello</w:t></w:r></w:p>")
    out, changes, _meta = fmt.fix_document(xml, {}, fmt.load_policy(None))
    remaining = sum(1 for _s, _e, p in fmt.paragraphs(out, include_empty_hosts=True)
                    if fmt._break_only_paragraph(p))
    check("F197 all 60 break-only paragraphs are gone", remaining == 0, f"remaining={remaining}")
    check("F197 the page break moved onto the following paragraph",
          out.count("<w:pageBreakBefore/>") == 1, out)
    check("F197 the change log accounts for every repair",
          len([c for c in changes if "page break" in c]) == 60, str(len(changes)))


# ---------------------------------------------------------------------------
# F198 -- legal single-quoted / spaced w:type='page' spellings are a page break
# ---------------------------------------------------------------------------
def test_f198_pagebreak_spellings() -> None:
    print("\n== F198: legal page-break spellings are recognised ==")
    spellings = [
        '<w:br w:type="page"/>',
        "<w:br w:type='page'/>",
        '<w:br w:type = "page"/>',
        "<w:br w:type = 'page' />",
    ]
    for spelling in spellings:
        check(f"F198 {spelling!r} is a page break",
              fmt.PAGEBREAK_RE.search(spelling) is not None)
        check(f"F198 {spelling!r} makes the paragraph break-only",
              fmt._break_only_paragraph(para(f"<w:r>{spelling}</w:r>")) is True)
    for not_break in ('<w:br/>', '<w:br w:type="textWrapping"/>'):
        check(f"F198 {not_break!r} is not a page break",
              fmt.PAGEBREAK_RE.search(not_break) is None)
    xml = doc('<w:p><w:r><w:br w:type=\'page\'/></w:r></w:p>'
              "<w:p><w:r><w:t>Hello</w:t></w:r></w:p>")
    out, _changes, _meta = fmt.fix_document(xml, {}, fmt.load_policy(None))
    check("F198 the FMT-S1 repair sees and removes the single-quoted break-only paragraph",
          fmt._break_only_paragraph(paragraphs_first(out)) is False
          and out.count("<w:br w:type='page'/>") == 0, out)


def paragraphs_first(xml: str) -> str:
    paras = fmt.paragraphs(xml, include_empty_hosts=True)
    return paras[0][2] if paras else ""


def main() -> int:
    test_f188_zero_insertion_at_break()
    test_f189_self_closing_wt()
    test_f190_break_crossing_refused()
    test_f191_same_offset_insertion_order()
    test_f192_apply_edits_overlap()
    test_f193_change_record_preserved()
    test_f194_template_section_balanced()
    test_f195_live_section_only()
    test_f197_no_fifty_paragraph_cap()
    test_f198_pagebreak_spellings()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return 1
    print("\nALL g9_docx CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

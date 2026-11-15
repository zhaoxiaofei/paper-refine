#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group G4 (run 20261115-220228).

Each check pins one re-validated candidate: DOCX layout / relationship / zip
claims in `paper_docx_format_parts/p02_layout_edit.py`. Hermetic: temporary
directories only, no network, no Word, no agent runs.

Run:  python3 .paper_test/test_wave2_G4.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_docx_format as f          # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ATTACHED = REL + "/attachedTemplate"

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="g4_"))


def _docx(path: Path, settings: str = "", rels: str = "", body: str = "") -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
        if settings:
            z.writestr("word/settings.xml", settings)
        if rels:
            z.writestr("word/_rels/settings.xml.rels", rels)
    return path


# ---------------------------------------------------------------------------
# C023 -- a relationship id written with an aliased prefix must still be
# resolved: the element and its relationship go together (no dangling r:id).
# ---------------------------------------------------------------------------
def test_c023_aliased_rel_prefix() -> None:
    tmp = _tmp()
    settings = (f'<?xml version="1.0"?><w:settings xmlns:w="{W}" '
                f'xmlns:rel="{REL}">'
                '<w:attachedTemplate rel:id="rId1"/></w:settings>')
    rels = (f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}">'
            '<Relationship Id="rId1" Type="' + ATTACHED + '" '
            'Target="file:///C:/Users/x/template.dotx"/></Relationships>')
    src = _docx(tmp / "s.docx", settings, rels)
    out = tmp / "out.docx"
    res = f.strip_local_path_links(src, out)
    new_settings = zipfile.ZipFile(out).read("word/settings.xml").decode()
    new_rels = zipfile.ZipFile(out).read("word/_rels/settings.xml.rels").decode()
    check("C023 an attachedTemplate with an aliased r: prefix is removed with its link",
          res["ok"] and "attachedTemplate" not in new_settings
          and 'Id="rId1"' not in new_rels and res["skipped"] == [],
          f"{res['skipped']} {new_settings[-80:]}")


# ---------------------------------------------------------------------------
# C024 -- a UTF-16 main part must be written back as UTF-16, not as UTF-8
# bytes under an encoding="UTF-16" declaration.
# ---------------------------------------------------------------------------
def test_c024_utf16_part_roundtrip() -> None:
    tmp = _tmp()
    src = tmp / "u16.docx"
    xml = (f'<?xml version="1.0" encoding="UTF-16"?><w:document xmlns:w="{W}">'
           '<w:body><w:p><w:r><w:t>Data are at github.com/acme/x.</w:t></w:r>'
           '</w:p></w:body></w:document>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml.encode("utf-16"))
    out = tmp / "out.docx"
    res = f.strip_reference_sentences(
        src, out, lambda t: [m.span() for m in re.finditer(r"github\.com/\S+", t)])
    raw = zipfile.ZipFile(out).read("word/document.xml")
    import xml.etree.ElementTree as ET
    parsed = True
    try:
        ET.fromstring(raw)
    except Exception:                                            # noqa: BLE001
        parsed = False
    check("C024 a rewritten UTF-16 document.xml keeps UTF-16 bytes and parses",
          res["ok"] and parsed and raw[:2] == b"\xff\xfe", raw[:8])


# ---------------------------------------------------------------------------
# C090 -- the enclosing-run guard must find a legal run tag with whitespace
# before its attributes, instead of applying the multi-run replacement.
# ---------------------------------------------------------------------------
def test_c090_run_tag_whitespace() -> None:
    para = ('<w:p><w:r\n w:rsidR="00A1"><w:rPr><w:i/></w:rPr>'
            '<w:t xml:space="preserve">Front. Genet. Volume 11-</w:t></w:r>'
            "<w:r><w:t>2020</w:t></w:r></w:p>")
    refused = f._replace_text_in_para(para, "Volume 11-2020", "11, 565825 (2020)")
    check("C090 a formatted run whose tag has whitespace before its attributes is refused",
          refused is None, str(refused)[:120])
    plain = ('<w:p><w:r\n w:rsidR="00A1">'
             '<w:t xml:space="preserve">Front. Genet. Volume 11-</w:t></w:r>'
             "<w:r><w:t>2020</w:t></w:r></w:p>")
    applied = f._replace_text_in_para(plain, "Volume 11-2020", "11, 565825 (2020)")
    check("C090 the same multi-run replacement still applies to plain runs",
          applied is not None and "11, 565825 (2020)" in f.text_of(applied))


# ---------------------------------------------------------------------------
# C091 -- a commented-out table is not a live body block (no FMT-TB rows).
# ---------------------------------------------------------------------------
def test_c091_commented_table_not_a_block() -> None:
    body = ("<!-- <w:tbl><w:tr><w:tc><w:p><w:t>Table 1 | retired</w:t></w:p>"
            "</w:tc></w:tr></w:tbl> -->"
            "<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>")
    xml = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    blocks = [(t, xml[s:e]) for t, s, e, _x in f.body_block_spans(xml)]
    policy = {"tables": {"placement": "end", "caption": "before", "source": "venue"}}
    rows, inventory = f.table_conformance_rows(xml, policy, "manuscript.docx")
    check("C091 body_block_spans does not return a commented-out table",
          [b[0] for b in blocks] == ["p"], str([b[0] for b in blocks]))
    check("C091 no FMT-TB row / inventory entry for a commented-out table",
          rows == [] and inventory == [], f"{rows} {inventory}")


# ---------------------------------------------------------------------------
# C092 -- a commented-out <w:tbl> must not open a container that never closes.
# ---------------------------------------------------------------------------
def test_c092_commented_table_container() -> None:
    body = ("<!-- <w:tbl> -->"
            "<w:p><w:r><w:t>Discussion text follows the figure.</w:t></w:r></w:p>"
            '<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr><w:r>'
            "<w:t>Figure 1 | A caption that should be mergeable.</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>The continuation of the caption block.</w:t></w:r></w:p>")
    xml = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    paras = f.paragraphs(xml)
    containers = f.container_spans(xml)
    blocks = f.caption_block_ranges(paras, f.display_area_kinds(paras), containers, xml=xml)
    check("C092 a commented-out table opens no container", containers == [], str(containers))
    check("C092 the caption continuation after the comment is still detected",
          [b["continuations"] for b in blocks] == [[2]],
          str([b["continuations"] for b in blocks]))


# ---------------------------------------------------------------------------
# C093 -- the display rules are skipped by WORD tokens, not by raw substrings.
# ---------------------------------------------------------------------------
def test_c093_display_name_tokens() -> None:
    mains = ("support_vector_analysis.docx", "supply_chain_manuscript.docx",
             "suppressor_study.docx", "discovery_analysis.docx", "coverage_stats.docx",
             "manuscript.docx")
    skipped = ("Supplementary_Material.docx", "supporting_information.docx",
               "cover_letter.docx", "supp1.docx")
    bad_main = [n for n in mains if not f.display_rules_apply(n)]
    bad_skip = [n for n in skipped if f.display_rules_apply(n)]
    check("C093 a main manuscript whose name merely contains 'supp'/'cover' keeps the rules",
          bad_main == [], str(bad_main))
    check("C093 supplementary/cover documents are still skipped", bad_skip == [], str(bad_skip))


# ---------------------------------------------------------------------------
# C094 -- duplicate zip members are refused, never silently collapsed.
# ---------------------------------------------------------------------------
def test_c094_duplicate_members() -> None:
    tmp = _tmp()
    src = tmp / "dup.docx"
    one = f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>FIRST</w:t></w:r>' \
          "</w:p></w:body></w:document>"
    two = one.replace("FIRST", "SECOND")
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", one)
        z.writestr("word/document.xml", two)
    strip = f.strip_reference_sentences(src, tmp / "out.docx", lambda t: [])
    refresh = f.refresh_zotero_package(src, tmp / "out2.docx")
    links = f.strip_local_path_links(src, tmp / "out3.docx")
    check("C094 a duplicate word/document.xml is refused by the strip helper",
          (not strip["ok"]) and "repeats member" in str(strip.get("error", "")),
          str(strip.get("error"))[:80])
    check("C094 a duplicate member is refused by the refresh too",
          (not refresh["ok"]) and "repeats member" in str(refresh.get("skip", ""))
          and not (tmp / "out2.docx").exists(), str(refresh.get("skip"))[:80])
    check("C094 a duplicate member is refused by the link strip helper",
          not links["ok"], str(links.get("error"))[:80])


# ---------------------------------------------------------------------------
# C096 -- the template slot reader applies the DOCX part budget.
# ---------------------------------------------------------------------------
def test_c096_template_part_budget() -> None:
    tmp = _tmp()
    # An EMPTY heading slot plus an over-budget text part: a reader that ignores
    # the budget still returns the slot, so the check discriminates.
    body = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr></w:p>'
            "<w:p><w:r><w:t>" + ("a" * 4000) + "</w:t></w:r></w:p>")
    src = _docx(tmp / "t.docx", body=body)
    old_part, old_total = f.MAX_DOCX_PART_BYTES, f.MAX_DOCX_TOTAL_BYTES
    f.MAX_DOCX_PART_BYTES = 512
    try:
        slots = f.empty_paragraph_slots_from_template(src)
    finally:
        f.MAX_DOCX_PART_BYTES, f.MAX_DOCX_TOTAL_BYTES = old_part, old_total
    check("C096 an over-budget template part is refused instead of decoded", slots == [],
          str(slots)[:120])


# ---------------------------------------------------------------------------
# C098 -- "Supplementary Information, Figure 3" is a supplementary call-out.
# ---------------------------------------------------------------------------
def test_c098_supplementary_comma() -> None:
    ps = ["We show it in Supplementary Information, Figure 3.",
          "As in Figure 1, the data are complete."]
    rows = f.display_order_rows(ps, [False, False], [False, False], [False, False], True)
    check("C098 a comma after 'Supplementary Information' keeps the supplementary family",
          rows == [], str([(r["rule"], r["evidence"]) for r in rows]))
    real = f.display_order_rows(["We show Figure 2 here.", "As in Figure 1."],
                                [False, False], [False, False], [False, False], True)
    check("C098 a real main-figure order defect still fires",
          [r["rule"] for r in real] == ["FMT-O1"], str(real[:1]))


# ---------------------------------------------------------------------------
# C100 -- the local-path link scan applies the same package budget as its
# sibling strip helper.
# ---------------------------------------------------------------------------
def test_c100_link_scan_budget() -> None:
    tmp = _tmp()
    rels = (f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}">'
            '<Relationship Id="rId1" Type="http://x/y" '
            'Target="file:///C:/x/t.dotx"/></Relationships>')
    pad = "<!-- " + ("A" * 4000) + " -->"
    body = rels[: -len("</Relationships>")] + pad + "</Relationships>"
    src = _docx(tmp / "b.docx", rels=body)
    old_part, old_total = f.MAX_DOCX_PART_BYTES, f.MAX_DOCX_TOTAL_BYTES
    f.MAX_DOCX_PART_BYTES = 512
    try:
        rows = f.local_path_link_rows(src)
    finally:
        f.MAX_DOCX_PART_BYTES, f.MAX_DOCX_TOTAL_BYTES = old_part, old_total
    check("C100 an over-budget .rels part yields no rows instead of being read",
          rows == [], str(rows)[:120])


# ---------------------------------------------------------------------------
# C101 -- a legal prefixed <pr:Relationship> is a relationship.
# ---------------------------------------------------------------------------
def test_c101_prefixed_rels_part() -> None:
    tmp = _tmp()
    pref = (f'<?xml version="1.0"?><pr:Relationships xmlns:pr="{PKG_REL}">'
            '<pr:Relationship Id="rId1" Type="' + ATTACHED + '" '
            'Target="file:///C:/Users/hannah.eccles/template.dotx"/>'
            "</pr:Relationships>")
    settings = (f'<w:settings xmlns:w="{W}" xmlns:r="{REL}">'
                '<w:attachedTemplate r:id="rId1"/></w:settings>')
    src = _docx(tmp / "p.docx", settings, pref)
    rows = f.local_path_link_rows(src)
    res = f.strip_local_path_links(src, tmp / "out.docx")
    check("C101 a prefixed .rels part yields its local-path link",
          len(rows) == 1 and rows[0][1] == "rId1", str(rows))
    check("C101 the prefixed attached-template link is stripped",
          res["ok"] and len(res["removed"]) == 1, str(res["skipped"]))


# ---------------------------------------------------------------------------
# C102 -- one numbered-entry definition for parity, repair and verification.
# ---------------------------------------------------------------------------
def test_c102_numbered_entry_readers() -> None:
    texts = ["References", "1\nSmith J. Alpha beta.", "2\nJones K. Gamma delta."]
    entries = f.zotero_citation_state("", texts, {})["entries"]
    check("C102 the parity reader sees a tab-aligned numbered entry",
          entries == {1: "Smith J. Alpha beta.", 2: "Jones K. Gamma delta."}, str(entries))
    body = ('<w:p><w:r><w:t>References</w:t></w:r></w:p>'
            "<w:p><w:r><w:t>1</w:t></w:r><w:r><w:tab/>"
            '<w:t xml:space="preserve">Smith J. Alpha beta. Journal of Tests '
            "Volume 11-2020.</w:t></w:r></w:p>")
    xml = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    rec = {"first_family": "Smith", "year": "2020", "title": "Alpha beta in tests",
           "volume": "11", "pages": "565825", "doi": "10.1/x"}
    res = f.repair_reference_entries(xml, [rec])
    check("C102 the FMT-R repair reaches and verifies a tab-aligned entry",
          res["changed"] and [r["rule"] for r in res["repairs"]] == ["FMT-R1"],
          str(res["skipped"])[:120])


# ---------------------------------------------------------------------------
# C103 -- the Zotero style store is chosen by ROLE, not lexicographically.
# ---------------------------------------------------------------------------
def test_c103_style_store_choice() -> None:
    # settings names 'nature', the secondary store names 'vancouver': lexical
    # order and the primary store disagree, so the choice is observable.
    parts = {
        "word/settings.xml": (
            f'<w:settings xmlns:w="{W}"><w:docVars><w:docVar '
            'w:name="ZOTERO_STYLE" '
            'w:val="http://www.zotero.org/styles/nature"/></w:docVars></w:settings>'),
        "customXml/item1.xml": (
            '<b:Sources xmlns:b="x"><b:Style>'
            "http://www.zotero.org/styles/vancouver</b:Style></b:Sources>"),
    }
    res = f.zotero_style_reconcile(parts)
    check("C103 with no custom.xml the primary word/settings.xml store is kept",
          res["to"] == {"customXml/item1.xml": "nature"}, str(res["to"]))
    two_secondary = {
        "customXml/item1.xml": '<b:Style>http://www.zotero.org/styles/nature</b:Style>',
        "customXml/item2.xml": '<b:Style>http://www.zotero.org/styles/vancouver</b:Style>',
    }
    res2 = f.zotero_style_reconcile(two_secondary)
    check("C103 two secondary stores with no preferred style are left untouched",
          res2["changed"] is False and res2["to"] == {} and bool(res2.get("skip")),
          str(res2.get("skip"))[:80])


# ---------------------------------------------------------------------------
# C166 -- w:rPrChange is revision history, not a live direct font.
# ---------------------------------------------------------------------------
def test_c166_run_font_ignores_rprchange() -> None:
    old = ('<w:r><w:rPr><w:rPrChange w:id="1" w:author="a"><w:rPr>'
           '<w:rFonts w:ascii="Times New Roman"/></w:rPr></w:rPrChange></w:rPr>'
           "<w:t>The quick brown fox jumps</w:t></w:r>")
    new = ('<w:r><w:rPr><w:rFonts w:ascii="Arial"/></w:rPr>'
           "<w:t>over the lazy dog today</w:t></w:r>")
    check("C166 _run_font reads no direct font out of w:rPrChange",
          f._run_font(old) == "", repr(f._run_font(old)))
    xml = f'<w:document xmlns:w="{W}"><w:body><w:p>{old}{new}</w:p></w:body></w:document>'
    rows = [r for r in f.style_convention_rows(f.paragraphs(xml), {}, "m.docx")
            if r["rule"] == "FMT-T10a"]
    check("C166 no FMT-T10a row for one live direct font", rows == [], str(rows[:1]))


# ---------------------------------------------------------------------------
# C167 -- renumbering must not write a w:tab placeholder back as a newline.
# ---------------------------------------------------------------------------
def test_c167_renumber_keeps_tab() -> None:
    run = "<w:r><w:t>1</w:t><w:tab/></w:r>"
    out = f._zotero_renumber_run(run, 5)
    check("C167 a trailing w:tab survives renumbering without gaining a newline",
          f.text_of(out) == "5\n" and "<w:tab/>" in out,
          repr(f.text_of(out)) + " " + out)


# ---------------------------------------------------------------------------
# C170 -- a bare 'Keywords' heading resolves to the paragraph that holds the
# terms, so FMT-T8g is evaluated for that layout.
# ---------------------------------------------------------------------------
def test_c170_bare_keywords_heading() -> None:
    body = ('<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Abstract</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Keywords</w:t></w:r></w:p>'
            '<w:p><w:r><w:lastRenderedPageBreak/>'
            '<w:t>mice, rats</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Body</w:t></w:r></w:p>')
    xml = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    row = f.front_matter_page_break_row(xml, f.paragraphs(xml), "m.docx")
    check("C170 FMT-T8g is evaluated when 'Keywords' is a bare heading",
          row is not None and row["rule"] == "FMT-T8g",
          "None" if row is None else row["evidence"][:90])


# ---------------------------------------------------------------------------
# C171 -- the FMT-G3 insertion point is after the comma, not inside the word.
# ---------------------------------------------------------------------------
def test_c171_missing_space_offset() -> None:
    para = "<w:p><w:r><w:t>results,the data</w:t></w:r></w:p>"
    text = f.text_of(para)
    spans = [s for s in f.hygiene_spans(para) if s["rule"] == "FMT-G3"]
    ok = len(spans) == 1
    at = spans[0]["start"] if ok else -1
    check("C171 the FMT-G3 span sits right after the comma",
          ok and at == text.index(",") + 1 and spans[0]["end"] == at, f"{at} in {text!r}")
    check("C171 inserting one space at the reported span renders the repaired text",
          ok and (text[:at] + " " + text[at:]).startswith("results, the data"),
          repr(text[:at] + " " + text[at:]) if ok else "no span")


# ---------------------------------------------------------------------------
# C172 -- w:firstLineChars is hundredths of a character, converted to twips.
# ---------------------------------------------------------------------------
def test_c172_first_line_chars() -> None:
    para = ('<w:p><w:pPr><w:rPr><w:sz w:val="24"/></w:rPr>'
            '<w:ind w:firstLineChars="200"/></w:pPr><w:r><w:t>x</w:t></w:r></w:p>')
    got = f.paragraph_first_line_indent(para)
    check("C172 200 firstLineChars at 12 pt is 480 twips, not 200", got == 480, str(got))
    twips = ('<w:p><w:pPr><w:ind w:firstLine="360"/></w:pPr>'
             "<w:r><w:t>x</w:t></w:r></w:p>")
    check("C172 a real twips firstLine is unchanged",
          f.paragraph_first_line_indent(twips) == 360,
          str(f.paragraph_first_line_indent(twips)))


# ---------------------------------------------------------------------------
# C173 -- the in-place refresh fsyncs the new archive before os.replace.
# ---------------------------------------------------------------------------
def test_c173_refresh_fsync() -> None:
    tmp = _tmp()
    src = _docx(tmp / "m.docx", body="<w:p><w:r><w:t>x</w:t></w:r></w:p>")
    real_parts = f.refresh_zotero_parts
    real_fsync = os.fsync
    calls = []

    def spy_parts(parts, policy=None):
        return {"parts": dict(parts), "changed": True, "changes": ["spy change"],
                "skip": None, "zotero": None, "nothing_to_do": False}

    def spy_fsync(fd):
        calls.append(fd)
        return real_fsync(fd)

    f.refresh_zotero_parts = spy_parts
    os.fsync = spy_fsync
    try:
        res = f.refresh_zotero_package(src, tmp / "out.docx")
    finally:
        f.refresh_zotero_parts = real_parts
        os.fsync = real_fsync
    check("C173 the changed refresh path fsyncs before replacing the manuscript",
          res["changed"] and len(calls) == 1, f"fsync calls={len(calls)}")


# ---------------------------------------------------------------------------
# C174 -- a nested table's cell text is not glued into the outer cell.
# ---------------------------------------------------------------------------
def test_c174_nested_table_header() -> None:
    tbl = ("<w:tbl><w:tr><w:tc><w:p><w:t>outer</w:t></w:p>"
           "<w:tbl><w:tr><w:tc><w:p><w:t>inner1</w:t></w:p></w:tc>"
           "<w:tc><w:p><w:t>inner2</w:t></w:p></w:tc></w:tr></w:tbl>"
           "</w:tc></w:tr></w:tbl>")
    cells = f.table_first_row_cells(tbl)
    check("C174 the first-row cell text excludes the nested table",
          cells == ["outer"], str(cells))


def main() -> int:
    test_c023_aliased_rel_prefix()
    test_c024_utf16_part_roundtrip()
    test_c090_run_tag_whitespace()
    test_c091_commented_table_not_a_block()
    test_c092_commented_table_container()
    test_c093_display_name_tokens()
    test_c094_duplicate_members()
    test_c096_template_part_budget()
    test_c098_supplementary_comma()
    test_c100_link_scan_budget()
    test_c101_prefixed_rels_part()
    test_c102_numbered_entry_readers()
    test_c103_style_store_choice()
    test_c166_run_font_ignores_rprchange()
    test_c167_renumber_keeps_tab()
    test_c170_bare_keywords_heading()
    test_c171_missing_space_offset()
    test_c172_first_line_chars()
    test_c173_refresh_fsync()
    test_c174_nested_table_header()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    for name in FAILS:
        print("  -", name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group G5 (run 20261115-220228).

One check block per re-validated candidate:
  * F131/C095 -- a commented-out `<w:i/>`/`<w:b/>` in the rPr is not live
    emphasis (and the fixer's emphasis analysis sees no italic run);
  * F135/C099 -- an explicit `0` in --policy keeps its documented
    "0 = not gated" meaning next to a venue `image_dpi`/`figure_text` block;
  * F226/C168 -- a self-closing `<w:fldSimple .../>` is inventoried as a field
    by field_ranges()/zotero_field_report(), like has_field() already sees it;
  * F133/C097 -- legal `w:fldCharType = "end"` / `'end'` spellings and
    single-quoted attributes are read;
  * F228/C169 -- a commented-out property element is not the live one;
  * F116/C081 -- a negative claim is paired only with a method named in ITS
    sentence, not one from the preceding sentence;
  * F118/C083 -- a column's `values` keeps every row, so a value past the 200th
    row has an exact match;
  * F119/C084 -- the 40-table statistics cap records an INCOMPLETE seed row;
  * F218/C162 -- one repeated proper name is one row, not one per overlapping
    n-gram.

Hermetic: tempfile dirs only; no network, no Word, no agent runs.

Run:  python3 .paper_test/test_wave2_G5.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_docx_format as fmt      # noqa: E402

FAILS = []
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


# ---------------------------------------------------------------------------
# F131 / C095 -- commented-out emphasis is not live formatting
# ---------------------------------------------------------------------------
def test_f131_commented_emphasis() -> None:
    print("\n== F131: a commented-out <w:i/>/<w:b/> is not live emphasis ==")
    commented_i = '<w:r><w:rPr><!-- <w:i/> --></w:rPr><w:t>Nature Methods</w:t></w:r>'
    commented_b = '<w:r><w:rPr><!-- <w:b/> --></w:rPr><w:t>Bold?</w:t></w:r>'
    live_i = '<w:r><w:rPr><w:i/></w:rPr><w:t>Nature Methods</w:t></w:r>'
    check("F131 a commented-out <w:i/> is not italic",
          fmt.run_is_italic({}, "", commented_i) is False,
          fmt.run_is_italic({}, "", commented_i))
    check("F131 a LIVE <w:i/> is still italic",
          fmt.run_is_italic({}, "", live_i) is True)
    check("F131 a commented-out <w:b/> is not bold",
          fmt.run_is_bold({}, "", commented_b) is False,
          fmt.run_is_bold({}, "", commented_b))
    para = "<w:p>" + commented_i + "</w:p>"
    italic = fmt.journal_emphasis_runs({}, "", para)["italic"]
    check("F131 the emphasis analysis lists no italic run for the comment",
          italic == [], italic)


# ---------------------------------------------------------------------------
# F135 / C099 -- an explicit 0 in --policy is not overwritten by the venue
# ---------------------------------------------------------------------------
def test_f135_policy_explicit_zero() -> None:
    print("\n== F135: an explicit 0 keeps '0 = not gated' ==")
    d = Path(tempfile.mkdtemp(prefix="g5_policy_"))
    explicit = d / "explicit.json"
    explicit.write_text(json.dumps({"min_image_dpi": 0, "min_figure_text_pt": 0,
                                    "image_dpi": {"min_dpi": 450},
                                    "figure_text": {"min_pt": 5}}), encoding="utf-8")
    pol = fmt.load_policy(explicit)
    check("F135 explicit min_image_dpi 0 survives a venue 450",
          pol["min_image_dpi"] == 0, pol["min_image_dpi"])
    check("F135 explicit min_figure_text_pt 0 survives a venue 5",
          pol["min_figure_text_pt"] == 0, pol["min_figure_text_pt"])
    venue_only = d / "venue.json"
    venue_only.write_text(json.dumps({"image_dpi": {"min_dpi": 450},
                                      "figure_text": {"min_pt": 5}}), encoding="utf-8")
    pol2 = fmt.load_policy(venue_only)
    check("F135 a venue-only policy still derives 450 dpi",
          pol2["min_image_dpi"] == 450.0, pol2["min_image_dpi"])
    check("F135 a venue-only policy still derives 5 pt",
          pol2["min_figure_text_pt"] == 5.0, pol2["min_figure_text_pt"])
    check("F135 no policy file keeps the default 0",
          fmt.load_policy(None)["min_image_dpi"] == 0)


# ---------------------------------------------------------------------------
# F226 / C168 -- a self-closing w:fldSimple is a field everywhere
# ---------------------------------------------------------------------------
def test_f226_self_closing_fldsimple() -> None:
    print("\n== F226: a self-closing <w:fldSimple/> is inventoried ==")
    item = ('<w:p><w:fldSimple w:instr=" ADDIN ZOTERO_ITEM CSL_CITATION '
            '{&quot;citationID&quot;:&quot;c9&quot;}" r:id="rId9"/></w:p>')
    check("F226 has_field() sees the field", fmt.has_field(item) is True)
    ranges = fmt.field_ranges(item)
    check("F226 field_ranges() sees the field",
          len(ranges) == 1 and "ZOTERO_ITEM" in ranges[0][2], ranges)
    rep = fmt.zotero_field_report(item)
    check("F226 the Zotero inventory counts one item field",
          rep["counts"]["item"] == 1 and rep["counts"]["fields"] == 1, rep["counts"])
    check("F226 the inventory reads the instruction and the empty result",
          [f["citationID"] for f in rep["fields"]] == ["c9"]
          and [f["visible_text"] for f in rep["fields"]] == [""],
          [(f["citationID"], f["visible_text"]) for f in rep["fields"]])
    # A self-closing field followed by a PAIRED one must stay TWO fields: the
    # paired alternative must not swallow the self-closing tag's body.
    two = (item + '<w:p><w:fldSimple w:instr=" ADDIN ZOTERO_BIBL {}">'
                  '<w:r><w:t>[1]</w:t></w:r></w:fldSimple></w:p>')
    rep2 = fmt.zotero_field_report(two)
    check("F226 a self-closing field next to a paired one is still two fields",
          rep2["counts"]["fields"] == 2
          and rep2["counts"]["bibliography"] == 1
          and [(f["kind"], f["visible_text"]) for f in rep2["fields"]]
          == [("item", ""), ("bibliography", "[1]")],
          [(f["kind"], f["visible_text"]) for f in rep2["fields"]])


# ---------------------------------------------------------------------------
# F133 / C097 -- legal fldCharType spellings and single-quoted attributes
# ---------------------------------------------------------------------------
def test_f133_field_spellings() -> None:
    print("\n== F133: legal field/attribute spellings are read ==")
    pol = {"max_empty_paragraph_run": 1, "empty_paragraph_slots": []}

    def doc(attr: str) -> str:
        body = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                '<w:r><w:t>Results</w:t></w:r></w:p>'
                f'<w:p><w:r><w:fldChar {attr}/></w:r></w:p>'
                '<w:p><w:r><w:t>Body.</w:t></w:r></w:p>')
        return f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'

    for attr in ('w:fldCharType="end"',
                 'w:fldCharType = "end"',
                 "w:fldCharType='end'"):
        xml = doc(attr)
        paras = fmt.paragraphs(xml)
        groups = fmt.stray_empty_paragraph_groups(paras, pol, xml)[0]
        check(f"F133 {attr} keeps the field paragraph",
              fmt.has_field(paras[1][2]) is True and groups == [], groups)
    check("F133 a single-quoted w:val reads the value",
          fmt.attr("<w:pStyle w:val='Heading1'/>", "val") == "Heading1",
          fmt.attr("<w:pStyle w:val='Heading1'/>", "val"))
    check("F133 a single-quoted pStyle reads the real style",
          fmt.para_style("<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr></w:p>")
          == "Heading1",
          fmt.para_style("<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr></w:p>"))
    pair = ('<w:p><w:r><w:fldChar w:fldCharType = "begin"/></w:r>'
            "<w:r><w:fldChar w:fldCharType='end'/></w:r></w:p>")
    check("F133 a spaced/single-quoted begin+end pair is one field range",
          len(fmt.field_ranges(pair)) == 1, fmt.field_ranges(pair))
    both = ('<w:p><w:r><w:fldChar w:fldCharType = "begin"/>'
            '<w:instrText> ADDIN ZOTERO_ITEM CSL_CITATION '
            '{&quot;citationID&quot;:&quot;c1&quot;}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>Smith 2020</w:t></w:r>'
            "<w:r><w:fldChar w:fldCharType='end'/></w:r></w:p>")
    rep = fmt.zotero_field_report(both)
    check("F133 the Zotero inventory sees a spaced/single-quoted complex field",
          rep["counts"]["item"] == 1 and rep["errors"] == []
          and rep["fields"][0]["visible_text"] == "Smith 2020",
          (rep["counts"], rep["errors"]))


# ---------------------------------------------------------------------------
# F228 / C169 -- elem() returns the LIVE property, not a commented-out one
# ---------------------------------------------------------------------------
def test_f228_elem_skips_comments() -> None:
    print("\n== F228: elem() reads the live property element ==")
    para = ('<w:p><w:pPr><!-- <w:ind w:firstLine="720"/> -->'
            '<w:ind w:firstLine="0"/></w:pPr><w:r><w:t>x</w:t></w:r></w:p>')
    check("F228 a commented-out <w:ind> is not the paragraph's indentation",
          fmt.paragraph_first_line_indent(para) == 0,
          fmt.paragraph_first_line_indent(para))
    el = fmt.elem(fmt.ppr_of(para), "ind")
    check("F228 elem() returns the live <w:ind>",
          el == '<w:ind w:firstLine="0"/>', el)
    check("F228 a live property after a comment is still found",
          fmt.elem('<w:pPr><w:jc w:val="center"/></w:pPr>', "jc")
          == '<w:jc w:val="center"/>')
    changed = ('<w:pPr><w:pPrChange><w:pPr><w:ind w:firstLine="720"/></w:pPr>'
               '</w:pPrChange><w:ind w:firstLine="0"/></w:pPr>')
    check("F228 the revision record is still not live formatting",
          fmt.elem(changed, "ind") == '<w:ind w:firstLine="0"/>',
          fmt.elem(changed, "ind"))


# ---------------------------------------------------------------------------
# F116 / C081 -- a negative claim's subject is in ITS sentence
# ---------------------------------------------------------------------------
def test_f116_negative_claim_sentence() -> None:
    print("\n== F116: a negative claim is not paired across a sentence boundary ==")
    table = "tool,score\nCHISEL,1\nSCYN,2\n" * 3
    rows = fmt.negative_claim_rows(
        ["We applied CHISEL. SCYN could not be run on the cohort."],
        [("t.csv", table)])
    tokens = [r["token"] for r in rows if r["rule"] == "M30-NC"]
    check("F116 the preceding sentence's CHISEL is not the subject",
          "chisel" not in tokens, tokens)
    check("F116 the same-sentence SCYN is still the subject",
          "scyn" in tokens, tokens)
    same = fmt.negative_claim_rows(
        ["We applied CHISEL and SCYN could not be run on the cohort."],
        [("t.csv", table)])
    same_tokens = [r["token"] for r in same if r["rule"] == "M30-NC"]
    check("F116 a method named earlier in the SAME sentence is still paired",
          "chisel" in same_tokens, same_tokens)


# ---------------------------------------------------------------------------
# F118 / C083 -- a column's values are not cut at 200
# ---------------------------------------------------------------------------
def test_f118_column_values_not_truncated() -> None:
    print("\n== F118: table_column_stats keeps every column value ==")
    rows = [f"s{i},{i}" for i in range(1, 251)]
    table = "sample,ploidy\n" + "\n".join(rows) + "\n"
    stats = fmt.table_column_stats([("big.csv", table)])[1]
    check("F118 the column carries all 250 numeric values",
          len(stats["values"]) == 250, len(stats["values"]))
    number_rows = [{"document": "m", "document_paragraph": 1, "kind": "body",
                    "number": "250", "sentence": "We observed 250 ploidy events.",
                    "source": ""}]
    seed = fmt.hierarchy_seed_rows(number_rows, [("big.csv", table)])
    check("F118 a value at data row 250 has an exact match in the column",
          "the value matches a cell in column 'ploidy'" in seed[0]["seed check"],
          seed[0]["seed check"])


# ---------------------------------------------------------------------------
# F119 / C084 -- the 40-table cap is an INCOMPLETE row, not a silent cut
# ---------------------------------------------------------------------------
def test_f119_table_file_cap_recorded() -> None:
    print("\n== F119: the M30 statistics cap records the omitted tables ==")
    tables = [(f"t{i}.csv", "alpha,beta\nx,1\ny,2\nz,3\n") for i in range(40)]
    coverage = {}
    try:
        fmt.table_column_stats(tables, coverage=coverage)
    except TypeError as e:          # the pre-fix signature has no coverage dict
        coverage = {"error": str(e)}
    check("F119 table_column_stats reports total/examined/omitted",
          coverage == {"total": 40, "examined": 40, "omitted": 0}, coverage)
    tables.append(("producer.csv", "sample,n_cells\ns1,10\ns2,20\ns3,30\n"))
    number_rows = [{"document": "m", "document_paragraph": 1, "kind": "body",
                    "number": "99", "sentence": "We sequenced 99 cells across the cohort.",
                    "source": ""}]
    rows = fmt.hierarchy_seed_rows(number_rows, tables)
    gaps = [r for r in rows if r.get("kind") == "gap"]
    check("F119 a 41st table produces one INCOMPLETE gap row", len(gaps) == 1, gaps)
    check("F119 the gap states one of 41 tables was omitted",
          gaps and "1 shipped table file(s) of 41" in gaps[0]["sentence"],
          gaps[0]["sentence"] if gaps else "")
    under = fmt.hierarchy_seed_rows(
        number_rows, [(f"t{i}.csv", "alpha,beta\nx,1\ny,2\nz,3\n") for i in range(40)])
    check("F119 no gap row when every table is examined",
          [r for r in under if r.get("kind") == "gap"] == [], under)


# ---------------------------------------------------------------------------
# F218 / C162 -- one repeated proper name is one row
# ---------------------------------------------------------------------------
def test_f218_repeated_name_one_row() -> None:
    print("\n== F218: overlapping n-grams of ONE repeated name are one row ==")
    text = ("The New York Times reported the result and The New York Times repeated it. "
            "Later The New York Times published a follow-up and The New York Times closed "
            "the story. This filler sentence brings the passage above the minimum word "
            "count for the rule to run at all.")
    rows = fmt.term_repetition_rows([text], [False])
    check("F218 four repetitions of one name produce ONE FMT-T8c row",
          len(rows) == 1, [r["evidence"] for r in rows])
    check("F218 the row names the maximal 3-word term",
          rows and "new york times" in rows[0]["evidence"].lower(),
          rows[0]["evidence"] if rows else "")
    # A DISTINCT second repeated name must still be reported.
    two = ("The New York Times reported it and The New York Times repeated it. "
           "Later The New York Times closed it and The New York Times reopened it. "
           "Nature Biotechnology published it and Nature Biotechnology repeated it. "
           "Later Nature Biotechnology closed it and Nature Biotechnology reopened it. "
           + "padding " * 8)
    terms = [r["evidence"].lower() for r in fmt.term_repetition_rows([two], [False])]
    check("F218 a distinct repeated name is not dropped as an overlap",
          len(terms) == 2 and any("new york times" in t for t in terms)
          and any("nature biotechnology" in t for t in terms), terms)


def main() -> int:
    test_f131_commented_emphasis()
    test_f135_policy_explicit_zero()
    test_f226_self_closing_fldsimple()
    test_f133_field_spellings()
    test_f228_elem_skips_comments()
    test_f116_negative_claim_sentence()
    test_f118_column_values_not_truncated()
    test_f119_table_file_cap_recorded()
    test_f218_repeated_name_one_row()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    if FAILS:
        for f in FAILS:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

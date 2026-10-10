#!/usr/bin/env python3
"""Repro/regression checks for the 2026-10-10 bug-candidate audit.

Run:  python3 .paper_test/test_debug_2026_1010.py

Every check here FAILS on the tree as ingested and PASSES once the matching
defect is fixed, so this file doubles as the repro script for each confirmed
candidate (see the ledger in the debug report for the id -> check mapping):

  * C01 `_select_lookup_targets` discards the remainder of every class it has
    reserved a share for, so the lookup budget is never filled and an
    identifier-heavy corpus checks only its first four identifiers;
  * C02 FMT-O1 does not recognise the plural call-out "Figures 3 and 4";
  * C03 FMT-Z1 mispairs a Zotero cluster whose items are stored in insertion
    order while the marker renders them sorted, reporting a false stale row;
  * C04 the version-to-version Zotero gate compares parity-row COUNTS, so a
    version that repairs one stale field while breaking another passes;
  * C05 the stage gate's parity half reads only word/document.xml, so a stale
    field in footnotes/endnotes/headers is invisible to it (the CLI sees it);
  * C06 `zotero-check` prints CLEAN and exits 0 on a field with unparseable
    citation JSON;
  * C07 FMT-R3 calls a commit-pinned repository URL "no version";
  * C08 FMT-AV1 misses the common conditional locators ("available from the
    corresponding author on reasonable request", "will be made available upon
    publication", "shared upon request");
  * C09 `census_prefix_total` fabricates 0 when a member has a census row but
    the decision carries no ranking prefix.
"""
from __future__ import annotations

import html
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_dbg_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_dbg_format", WS / "paper_docx_format.py")

FAILS: list = []
TMPDIRS: list = []


def check(name: str, cond, detail: str = "") -> None:
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


def _cite_field(cid: str, marker: str, items: list, visible: str) -> str:
    """A Zotero citation field: `items` = [(key, title, first-author family)]."""
    payload = {
        "citationID": cid,
        "properties": {"formattedCitation": marker, "plainCitation": visible,
                       "noteIndex": 0},
        "citationItems": [
            {"id": k + "/1",
             "uris": [f"http://zotero.org/users/local/AAA/items/{k}"],
             "itemData": {"type": "article-journal", "title": title,
                          "author": [{"family": family, "given": "A"}]}}
            for k, title, family in items],
    }
    instr = html.escape(" ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(payload),
                        quote=False)
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>{visible}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def _bibliography_para(number: int, text: str) -> str:
    return (f'<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{number}. {text}</w:t></w:r></w:p>')


# =====================================================================
# C01 -- the lookup budget must actually be spent
# =====================================================================
def test_lookup_budget():
    print("\n== C01 the per-class lookup budget keeps the leftovers ==")
    targets = ([{"source": "identifier", "kind": "doi", "query": f"10.1/{i}"}
                for i in range(30)]
               + [{"source": "gene", "kind": "gene", "query": f"G{i}"} for i in range(5)]
               + [{"source": "placeholder", "kind": "preprint", "query": "T"}])
    picked = pp._select_lookup_targets(targets, pp.LOOKUP_MAX_TARGETS)
    srcs = Counter(t["source"] for t in picked)
    check("the lookup budget is filled to its cap when targets remain",
          len(picked) == pp.LOOKUP_MAX_TARGETS, f"{len(picked)} of {pp.LOOKUP_MAX_TARGETS}")
    check("an identifier-heavy corpus checks more than the reserved four",
          srcs["identifier"] > pp.LOOKUP_BUDGET_SHARES["identifier"], str(dict(srcs)))
    check("every class keeps at least its reserved share",
          srcs["gene"] >= 5 and srcs["placeholder"] >= 1, str(dict(srcs)))
    small = [{"source": "identifier", "kind": "doi", "query": "d"}]
    check("a pool within budget is returned unchanged",
          pp._select_lookup_targets(small, 24) == small)


# =====================================================================
# C02 -- FMT-O1 must see the plural call-out form
# =====================================================================
def test_display_order_plural():
    print("\n== C02 FMT-O1 reads the plural 'Figures N' call-out ==")
    paras = ["Results appear in Figures 3 and 4.", "Figure 1 shows the pipeline."]
    rows = fmt.display_order_rows(paras, order_policy=True)
    check("a later 'Figure 1' after 'Figures 3 and 4' is an order row",
          any(r["rule"] == "FMT-O1" for r in rows), str(rows)[:200])
    in_order = ["Figure 1 shows the pipeline.", "Figures 2 and 3 show the rest."]
    check("an in-order plural call-out produces no row",
          fmt.display_order_rows(in_order, order_policy=True) == [],
          str(fmt.display_order_rows(in_order, order_policy=True))[:200])


# =====================================================================
# C03 -- a sorted numeric cluster is not a stale marker
# =====================================================================
def test_sorted_cluster_is_not_stale():
    print("\n== C03 a numerically sorted cluster is not a stale marker ==")
    # f1 cites Delta then Gamma -> Delta is rank 1, Gamma rank 2. f2 cites them
    # in the opposite order (Gamma, Delta) and Zotero renders the cluster
    # sorted ("1,2"): a consistent field whose stored order differs from the
    # rendered one.
    items = [("AAAA", "Alpha work", "Alvarez"), ("BBBB", "Beta work", "Bianchi"),
             ("CCCC", "Gamma work", "Chen"), ("DDDD", "Delta work", "Dubois")]
    xml = ('<w:document xmlns:w="%s"><w:body>' % NS
           + _cite_field("f1", r"\super 1,2\nosupersub{}", [items[3], items[2]], "1,2")
           + _cite_field("f2", r"\super 1,2\nosupersub{}", [items[2], items[3]], "1,2")
           + '<w:p><w:t>References</w:t></w:p>'
           + _bibliography_para(1, "Dubois, D. Delta work. Journal (2014).")
           + _bibliography_para(2, "Chen, C. Gamma work. Journal (2013).")
           + '</w:body></w:document>')
    para = [fmt.text_of(q[2]) for q in fmt.paragraphs(xml)]
    rows = fmt.zotero_parity_rows(xml, para)
    check("a cluster whose numbers are exactly its items' ranks is not stale",
          not any(r["rule"] == "FMT-Z1" for r in rows), str(rows)[:240])
    stale = ('<w:document xmlns:w="%s"><w:body>' % NS
             + _cite_field("f1", r"\super 1,2\nosupersub{}", [items[3], items[2]], "1,2")
             + _cite_field("f2", r"\super 39,40\nosupersub{}", [items[2], items[3]], "39,40")
             + '<w:p><w:t>References</w:t></w:p>'
             + _bibliography_para(1, "Dubois, D. Delta work. Journal (2014).")
             + _bibliography_para(2, "Chen, C. Gamma work. Journal (2013).")
             + '</w:body></w:document>')
    srows = fmt.zotero_parity_rows(stale, para)
    check("a genuinely stale cluster is still reported",
          any(r["rule"] == "FMT-Z1" for r in srows), str(srows)[:240])
    # a half-updated cluster: two items but one visible number
    half = ('<w:document xmlns:w="%s"><w:body>' % NS
            + _cite_field("f1", r"\super 1\nosupersub{}", [items[3], items[2]], "1")
            + '<w:p><w:t>References</w:t></w:p>'
            + _bibliography_para(1, "Dubois, D. Delta work. Journal (2014).")
            + _bibliography_para(2, "Chen, C. Gamma work. Journal (2013).")
            + '</w:body></w:document>')
    hrows = fmt.zotero_parity_rows(half, [fmt.text_of(q[2]) for q in fmt.paragraphs(half)])
    # C14: a marker whose count cannot be paired is judged by neither rule.
    check("a marker with fewer numbers than cited items is reported",
          any(r["rule"] == "FMT-Z3" and "rendered number" in r["evidence"] for r in hrows),
          str(hrows)[:240])


# =====================================================================
# C04/C05 -- the stage gate: identity, and every field-carrying part
# =====================================================================
def _docx(tmp: Path, name: str, doc: str, footnotes: str = None) -> Path:
    p = tmp / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)
        if footnotes is not None:
            z.writestr("word/footnotes.xml", footnotes)
    return p


def test_gate_identity_and_parts():
    print("\n== C04/C05 the Zotero gate compares faults, not counts, over every part ==")
    tmp = scratch("dbg_gate_")
    items = [("AAAA", "Alpha work", "Alvarez"), ("BBBB", "Beta work", "Bianchi"),
             ("CCCC", "Gamma work", "Chen"), ("DDDD", "Delta work", "Dubois")]
    bib = ('<w:p><w:t>References</w:t></w:p>'
           + _bibliography_para(1, "Alvarez, A. Alpha work. Journal (2011).")
           + _bibliography_para(2, "Bianchi, B. Beta work. Journal (2012).")
           + _bibliography_para(3, "Chen, C. Gamma work. Journal (2013).")
           + _bibliography_para(4, "Dubois, D. Delta work. Journal (2014)."))

    def doc(cite_a_marker, cite_b_marker, vis_a="1,2", vis_b="3,4"):
        return ('<w:document xmlns:w="%s"><w:body>' % NS
                + _cite_field("citeA", cite_a_marker, items[:2], vis_a)
                + _cite_field("citeB", cite_b_marker, items[2:], vis_b)
                + bib + '</w:body></w:document>')

    v1 = _docx(tmp, "v1.docx", doc(r"\super 1,2\nosupersub{}",
                                   r"\super 39,40\nosupersub{}", vis_b="39,40"))
    v2 = _docx(tmp, "v2.docx", doc(r"\super 9,10\nosupersub{}",
                                   r"\super 3,4\nosupersub{}", vis_a="9,10"))
    cont = fmt.zotero_field_continuity_problems(fmt.zotero_report_for_docx(v1),
                                                fmt.zotero_report_for_docx(v2))
    check("repairing one stale field while breaking another is a NEW fault",
          any("NEW stale-citation fault" in e for e in cont.get("errors") or []),
          str(cont.get("errors"))[:240])

    foot = (f'<?xml version="1.0"?><w:footnotes xmlns:w="{NS}">'
            '<w:footnote w:id="1"><w:p>'
            + _cite_field("footA", r"\super 39\nosupersub{}", [items[0]], "39")
            + '</w:p></w:footnote></w:footnotes>')
    body = ('<w:document xmlns:w="%s"><w:body>' % NS
            + _cite_field("citeA", r"\super 1\nosupersub{}", [items[0]], "1")
            + '<w:p><w:t>References</w:t></w:p>'
            + _bibliography_para(1, "Alvarez, A. Alpha work. Journal (2011).")
            + '</w:body></w:document>')
    p = _docx(tmp, "foot.docx", body, foot)
    rows = fmt.zotero_report_for_docx(p).get("parity_rows") or []
    check("a stale footnote marker reaches the stage gate's parity rows",
          any(r["rule"] == "FMT-Z1" for r in rows), str(rows)[:240])
    check("the footnote row names its part",
          any("footnotes" in str(r.get("location")) for r in rows),
          str([r.get("location") for r in rows])[:240])

    # The package-wide order is document-first however the caller lists the
    # parts (a zip may put footnotes.xml first): the main part's ranks must not
    # shift, or every in-text citation reports a false stale row.
    doc_xml = ('<w:document xmlns:w="%s"><w:body>' % NS
               + _cite_field("fA", r"\super 1\nosupersub{}", [items[0]], "1")
               + _cite_field("fB", r"\super 2\nosupersub{}", [items[1]], "2")
               + '<w:p><w:t>References</w:t></w:p>'
               + _bibliography_para(1, "Alvarez, A. Alpha work. Journal (2011).")
               + _bibliography_para(2, "Bianchi, B. Beta work. Journal (2012).")
               + '</w:body></w:document>')
    foot_ok = (f'<?xml version="1.0"?><w:footnotes xmlns:w="{NS}">'
               '<w:footnote w:id="1"><w:p>'
               + _cite_field("fC", r"\super 3\nosupersub{}",
                             [("EEEE", "Epsilon work", "Evans")], "3")
               + '</w:p></w:footnote></w:footnotes>')
    for order_parts in ([("word/document.xml", doc_xml), ("word/footnotes.xml", foot_ok)],
                        [("word/footnotes.xml", foot_ok), ("word/document.xml", doc_xml)]):
        prows = fmt.zotero_parity_rows_for_parts(order_parts)
        check("the part order does not shift the package-wide citation order",
              not any(r["rule"] in ("FMT-Z1", "FMT-Z2", "FMT-Z4") for r in prows),
              str(prows)[:240])


# =====================================================================
# C06 -- zotero-check must not call a corrupt field clean
# =====================================================================
def test_zotero_check_structural_fault():
    print("\n== C06 zotero-check reports a corrupt citation field ==")
    tmp = scratch("dbg_cli_")
    good = _cite_field("c1", r"\super 1\nosupersub{}",
                       [("AAAA", "Alpha work", "Alvarez")], "1")
    bad = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM CSL_CITATION '
           '{"citationID": "c2", "properties": {"formattedCitation": "\\super 2'
           '</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           '<w:r><w:t>2</w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    doc = ('<w:document xmlns:w="%s"><w:body>' % NS + good + bad
           + '<w:p><w:t>References</w:t></w:p>'
           + _bibliography_para(1, "Alvarez, A. Alpha work. Journal (2011).")
           + '</w:body></w:document>')
    p = _docx(tmp, "corrupt.docx", doc)
    run = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"),
                          "zotero-check", str(p)], capture_output=True, text=True,
                         timeout=120)
    check("a document with unparseable citation JSON does not print CLEAN",
          "CLEAN" not in run.stdout, run.stdout[-240:])
    check("a document with unparseable citation JSON exits non-zero",
          run.returncode != 0, f"rc={run.returncode}")
    check("the structural fault is named",
          "JSON" in run.stdout or "json" in run.stdout, run.stdout[-240:])
    # A Word package carries footnotes.xml, and the merged multi-part inventory
    # prefixes every message with its part name ("word/document.xml: [...]"):
    # the fault must survive that prefix, or every real file reads CLEAN again.
    foot = (f'<?xml version="1.0"?><w:footnotes xmlns:w="{NS}">'
            '<w:footnote w:id="-1"><w:p><w:r><w:t>separator</w:t></w:r></w:p>'
            '</w:footnote></w:footnotes>')
    p2 = _docx(tmp, "corrupt_multi_part.docx", doc, foot)
    run2 = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"),
                           "zotero-check", str(p2)], capture_output=True, text=True,
                          timeout=120)
    check("a corrupt field in a package with footnotes is not called clean",
          "CLEAN" not in run2.stdout and run2.returncode != 0, run2.stdout[-240:])


# =====================================================================
# C07/C08 -- reference-shape and availability-shape false positives/negatives
# =====================================================================
def test_reference_and_availability_shapes():
    print("\n== C07/C08 repository pins and conditional locators ==")
    pinned = ("Zhao, X., et al. paper-refine: manuscript revision pipeline. GitHub "
              "https://github.com/zhaoxiaofei/paper-refine/tree/"
              "0bfedcc1ec7842d8bde7537e26536af64a10cf00 (2026).")
    rows = fmt.reference_entry_rows([pinned], [True])
    check("a commit-pinned repository URL is a version",
          not any(r["rule"] == "FMT-R3" for r in rows), str(rows)[:200])
    bare = "Zhao, X., et al. paper-refine. GitHub https://github.com/zhaoxiaofei/paper-refine."
    rows = fmt.reference_entry_rows([bare], [True])
    check("an unpinned repository URL is still FMT-R3",
          any(r["rule"] == "FMT-R3" for r in rows), str(rows)[:200])

    for text in ("Data are available from the corresponding author on reasonable request.",
                 "The data will be made available upon publication.",
                 "Code is shared upon request."):
        rows = fmt.availability_rows([text])
        check(f"FMT-AV1 reports {text[:42]!r}",
              any(r["rule"] == "FMT-AV1" for r in rows), str(rows)[:200])
    ok = fmt.availability_rows([
        "All data are deposited at https://doi.org/10.5281/zenodo.1234567 and the code at "
        "https://github.com/zhaoxiaofei/paper-refine/tree/0bfedcc1."])
    check("a resolved locator is not a conditional one",
          not any(r["rule"] == "FMT-AV1" for r in ok), str(ok)[:200])


# =====================================================================
# C09 -- no fabricated defect count
# =====================================================================
def test_census_prefix_total_no_fabricated_zero():
    print("\n== C09 a member with no ranking prefix shows no number ==")
    census = {"r1_a2": {"tiers": {"correctness": {"severities": {
        "fatal": {"own": 1, "peer": 0}, "critical": {"own": 0, "peer": 0},
        "major": {"own": 0, "peer": 0}, "minor": {"own": 0, "peer": 0}}}}}}
    agg = {"issue_census": census}
    check("a census member with no cells_used reports None, not 0",
          pp.census_prefix_total(agg, {}, "r1_a2") is None,
          str(pp.census_prefix_total(agg, {}, "r1_a2")))
    sel = {"tiebreak": {"cells_used": 2, "cells_total": 48, "floor": 1}}
    check("the same member with a prefix reports its cumulative count",
          pp.census_prefix_total(agg, sel, "r1_a2") == 1,
          str(pp.census_prefix_total(agg, sel, "r1_a2")))
    check("a member with no census row at all still reports None",
          pp.census_prefix_total(agg, sel, "nope") is None)


# =====================================================================
# C10 -- flattening must refuse a stale document
# =====================================================================
def test_flatten_refuses_stale_document():
    print("\n== C10 unlink_zotero_fields refuses a stale document ==")
    tmp = scratch("dbg_flatten_")
    items = [("AAAA", "Alpha work", "Alvarez"), ("BBBB", "Beta work", "Bianchi")]
    body = ('<w:document xmlns:w="%s"><w:body>' % NS
            + _cite_field("citeA", r"\super 1\nosupersub{}", [items[0]], "1")
            + _cite_field("citeB", r"\super 39\nosupersub{}", [items[1]], "39")
            + '<w:p><w:t>References</w:t></w:p>'
            + _bibliography_para(1, "Alvarez, A. Alpha work. Journal (2011).")
            + _bibliography_para(2, "Bianchi, B. Beta work. Journal (2012).")
            + '</w:body></w:document>')
    stale = _docx(tmp, "stale.docx", body)
    policy = dict(fmt.POLICY_DEFAULTS)
    policy["unlink_zotero_fields"] = True
    out = tmp / "flattened.docx"
    rep = fmt.fix_package(stale, out, policy)
    check("the formatter refuses to unlink the fields of a stale document",
          rep.get("ok") is False and "stale" in str(rep.get("error")),
          str(rep)[:240])
    check("no flattened copy is produced", not out.exists())
    clean_body = ('<w:document xmlns:w="%s"><w:body>' % NS
                  + _cite_field("citeA", r"\super 1\nosupersub{}", [items[0]], "1")
                  + _cite_field("citeB", r"\super 2\nosupersub{}", [items[1]], "2")
                  + '<w:p><w:t>References</w:t></w:p>'
                  + _bibliography_para(1, "Alvarez, A. Alpha work. Journal (2011).")
                  + _bibliography_para(2, "Bianchi, B. Beta work. Journal (2012).")
                  + '</w:body></w:document>')
    clean = _docx(tmp, "clean.docx", clean_body)
    rep2 = fmt.fix_package(clean, tmp / "clean_out.docx", policy)
    check("a clean document is still flattened",
          "refusing to flatten" not in str(rep2.get("error")), str(rep2)[:240])


# =====================================================================
# C11 -- a name collision must not drop a document from the field check
# =====================================================================
def test_field_check_covers_colliding_documents():
    print("\n== C11 appendix-a / appendix-b are both field-checked ==")
    tmp = scratch("dbg_collide_")
    base = tmp / "base"
    out = tmp / "out"
    base.mkdir()
    out.mkdir()
    items = [("AAAA", "Alpha work", "Alvarez")]
    field = _cite_field("citeA", r"\super 1\nosupersub{}", items, "1")
    plain = '<w:p><w:r><w:t>1</w:t></w:r></w:p>'
    appendix_doc = ('<w:document xmlns:w="%s"><w:body>' % NS + field
                    + '</w:body></w:document>')
    appendix_out = ('<w:document xmlns:w="%s"><w:body>' % NS + plain
                    + '</w:body></w:document>')
    for name in ("appendix-a.docx", "appendix-b.docx"):
        _docx(base, name, appendix_doc)
        _docx(out, name, appendix_doc)
    # appendix-a loses its field (the visible text remains as plain text)
    _docx(out, "appendix-a.docx", appendix_out)
    errs, warns = [], []
    rep = pp.zotero_field_continuity_check(base, out, "collision", errs, warns)
    check("the shadowed document is compared, not skipped",
          any("appendix-a.docx" in str(e) for e in errs), str(errs)[:240])
    check("the other colliding document still passes", rep.get("errors", 0) >= 1,
          str(rep)[:200])


def test_availability_pin_prefix():
    print("\n== C12 one commit at two truncation lengths is one pin ==")
    same = fmt.availability_rows([
        "Code: https://github.com/zhaoxiaofei/paper-refine/tree/"
        "0bfedcc1ec7842d8bde7537e26536af64a10cf00",
        "Also https://github.com/zhaoxiaofei/paper-refine/commit/0bfedcc1"])
    check("the same commit at two lengths is not two pins",
          not any(r["rule"] == "FMT-AV2" for r in same), str(same)[:200])
    other = fmt.availability_rows([
        "Code: https://github.com/zhaoxiaofei/paper-refine/tree/0bfedcc1",
        "Code: https://github.com/zhaoxiaofei/paper-refine/tree/9f2c1ab"])
    check("two genuinely different commits are still two pins",
          any(r["rule"] == "FMT-AV2" for r in other), str(other)[:200])


def test_prefixed_marker_is_read():
    print("\n== C13 a prefixed marker is not invisible ==")
    check("the prefix (hg19) does not hide the citation number",
          fmt._marker_numbers("(hg19)37") == [37], str(fmt._marker_numbers("(hg19)37")))
    check("a prefix with a multi-number cluster is read",
          fmt._marker_numbers(r"(hg19)37,39\nosupersub{}") == [37, 39],
          str(fmt._marker_numbers(r"(hg19)37,39\nosupersub{}")))
    items = [("AAAA", "Alpha work", "Alvarez"), ("BBBB", "Beta work", "Bianchi")]
    xml = ('<w:document xmlns:w="%s"><w:body>' % NS
           + _cite_field("f1", r"\super 1\nosupersub{}", [items[0]], "1")
           + _cite_field("f2", r"\super (hg19)37\nosupersub{}", [items[1]], "(hg19)37")
           + '<w:p><w:t>References</w:t></w:p>'
           + _bibliography_para(1, "Alvarez, A. Alpha work. Journal (2011).")
           + _bibliography_para(2, "Bianchi, B. Beta work. Journal (2012).")
           + '</w:body></w:document>')
    rows = fmt.zotero_parity_rows(xml, [fmt.text_of(q[2]) for q in fmt.paragraphs(xml)])
    check("the stale number inside a prefixed marker is reported",
          any(r["rule"] in ("FMT-Z1", "FMT-Z3") for r in rows), str(rows)[:240])


def test_venue_profile_sources_survive():
    print("\n== C15 a venue profile's own sources survive normalization ==")
    raw = json.loads((WS / "venue_profiles" / "nature-biotechnology.json").read_text(
        encoding="utf-8"))
    norm = pp.normalize_venue_profile(raw, "test")
    check("the profile's `sources` map is carried through",
          isinstance(norm.get("sources"), dict)
          and norm["sources"].get("submission_guidelines", "").startswith("https://"),
          str(norm.get("sources"))[:120])
    check("the sources the profile declared are all kept",
          set(norm.get("sources") or {}) == set(raw.get("sources") or {}),
          str(sorted(norm.get("sources") or {}))[:160])


def main() -> int:
    sections = [("lookup_budget", test_lookup_budget),
                ("display_order_plural", test_display_order_plural),
                ("sorted_cluster", test_sorted_cluster_is_not_stale),
                ("gate_identity_and_parts", test_gate_identity_and_parts),
                ("zotero_check_structural", test_zotero_check_structural_fault),
                ("reference_availability", test_reference_and_availability_shapes),
                ("census_prefix_total", test_census_prefix_total_no_fabricated_zero),
                ("flatten_refuses_stale", test_flatten_refuses_stale_document),
                ("field_check_collisions", test_field_check_covers_colliding_documents),
                ("pin_prefix", test_availability_pin_prefix),
                ("prefixed_marker", test_prefixed_marker_is_read),
                ("venue_sources", test_venue_profile_sources_survive)]
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
    print("ALL 2026-1010 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""FMT-Z1..Z5 / M36 — the Zotero live-field refresh parity (2026-10-09).

Run:  python3 .paper_test/test_zotero_refresh_parity.py

A certified package's citations are LIVE Zotero fields: their rendered numbers
and the bibliography are CACHED results. When the manuscript is edited around
them (rounds merged, paragraphs moved, fields spliced), the cache goes stale --
the numbers in the text and the order of the reference list no longer agree with
the document's own citation order -- and the next Word/Zotero Refresh renumbers
everything, reorders the bibliography and (because the style is stored twice)
can re-render the entries in a different CSL style. This suite pins the checks
that make that visible BEFORE the package ships:

  * `zotero_citation_state` reads each field's embedded `itemData` and computes
    the document's own citation order -- no Zotero library and no network;
  * `FMT-Z1` a marker whose number is not the item's rank (a stale marker),
    `FMT-Z2` a bibliography entry that describes another work, `FMT-Z3` one item
    with two numbers / a number outside 1..N / an entry never cited, `FMT-Z4` a
    stored marker that disagrees with the visible text, `FMT-Z5` two conflicting
    Zotero style stores in one package;
  * the en-dash RANGE marker (`19–23`) is expanded, so a multi-citation field is
    compared item by item;
  * `zotero_report_for_docx` carries the rows, and
    `zotero_field_continuity_problems` calls a version that INTRODUCES a stale
    marker an ERROR while a refresh that clears them is a recorded repair;
  * `analyse_package`/`scan_paths` surface the rows, and the `zotero-check` CLI
    exits 1 on a high row;
  * the M36 sweep is wired into the skill text, the review coverage contract and
    all five stage prompts (with discovery proposals now starting at M37).

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_zp_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_zp_format", WS / "paper_docx_format.py")

FAILS = []
TMPDIRS = []
STYLE_A = "http://www.zotero.org/styles/nature-biotechnology"
STYLE_B = "http://www.zotero.org/styles/nature"


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


def _cite_instr(cid: str, marker: str, items: list, visible: str) -> str:
    """A Zotero citation field's instruction JSON (itemData embedded)."""
    payload = {
        "citationID": cid,
        "properties": {"formattedCitation": marker, "plainCitation": visible,
                       "noteIndex": 0},
        "citationItems": [{"id": it["key"] + "/1",
                           "uris": [f"http://zotero.org/users/local/AAA/items/{it['key']}"],
                           "itemData": {"type": "article-journal", "title": it["title"],
                                        "author": [{"family": it["family"],
                                                    "given": it.get("given", "A")}],
                                        "issued": {"date-parts": [[2020]]}}}
                          for it in items],
        "schema": "https://github.com/citation-style-language/schema/raw/master/csl-citation.json",
    }
    return ("ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(payload, ensure_ascii=False))


def _field_para(cid: str, marker: str, items: list, visible: str) -> str:
    import html
    instr = html.escape(_cite_instr(cid, marker, items, visible), quote=False)
    return (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f'<w:r><w:t>{visible}</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def _bibliography_para(number: int, text: str) -> str:
    return (f'<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{number}. {text}</w:t></w:r></w:p>')


ITEMS = [
    {"key": "AAAA1111", "title": "Alpha diversity in single cells", "family": "Alvarez"},
    {"key": "BBBB2222", "title": "Beta catenin signalling atlas", "family": "Bianchi"},
    {"key": "CCCC3333", "title": "Gamma ray damage response", "family": "Chen"},
    {"key": "DDDD4444", "title": "Delta copy number landscape", "family": "Dubois"},
]


def _docx(path: Path, paragraphs: list, styles: dict = None, marker_overrides=None,
          entry_overrides=None):
    """A minimal DOCX carrying Zotero citation fields and a bibliography."""
    st = styles if styles is not None else {"word/settings.xml": STYLE_A}
    marker_overrides = marker_overrides or {}
    entry_overrides = entry_overrides or {}
    # two citation fields: 1,2 then 3,4 (the refresh-stable case)
    body = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
            '<w:body>']
    body.append("<w:p><w:r><w:t>Main text.</w:t></w:r></w:p>")
    body.append(_field_para("citeA", marker_overrides.get("citeA", r"\super 1,2\nosupersub{}"),
                            ITEMS[:2], marker_overrides.get("citeA-vis", "1,2")))
    body.append(_field_para("citeB", marker_overrides.get("citeB", r"\super 3,4\nosupersub{}"),
                            ITEMS[2:], marker_overrides.get("citeB-vis", "3,4")))
    body.append("<w:p><w:r><w:t>References</w:t></w:r></w:p>")
    for i, it in enumerate(ITEMS, 1):
        body.append(_bibliography_para(
            i, entry_overrides.get(i, f"{it['family']}, A. et al. {it['title']}. "
                                       f"Journal {i}, 1-9 (2020).")))
    body.append('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                '<w:r><w:instrText xml:space="preserve">ADDIN ZOTERO_BIBL '
                '{"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY'
                '</w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                '<w:r><w:t>bibliography</w:t></w:r>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    body.append("</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", "\n".join(body))
        for part, style in st.items():
            if part == "word/settings.xml":
                z.writestr(part, '<?xml version="1.0"?><w:settings '
                                 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                                 '2006/main"><w:docVars><w:docVar w:name="ZOTERO_PREF_1" '
                                 f'w:val="&lt;data&gt;&lt;style id=&quot;{style}&quot;/&gt;'
                                 '&lt;/data&gt;"/></w:docVars></w:settings>')
            else:
                z.writestr(part, '<?xml version="1.0"?><Properties><property '
                                 'fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" '
                                 'name="ZOTERO_PREF_1"><vt:lpwstr>'
                                 f'&lt;data&gt;&lt;style id="{style}"/&gt;&lt;/data&gt;'
                                 '</vt:lpwstr></property></Properties>')
    return path


# ---------------------------------------------------------------------------
# 1. the reader + the clean baseline
# ---------------------------------------------------------------------------
def test_clean_document():
    tmp = scratch("zp_clean_")
    p = _docx(tmp / "main.docx", [])
    report = fmt.zotero_report_for_docx(p)
    check("the citation fields are inventoried", report["counts"]["item"] == 2,
          str(report["counts"]))
    rows = report.get("parity_rows") or []
    check("a refresh-stable document produces no parity row", rows == [], str(rows)[:200])
    cli = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), "zotero-check",
                          str(p)], capture_output=True, text=True, timeout=120)
    check("the zotero-check CLI reports the clean document and exits 0",
          cli.returncode == 0 and "CLEAN" in cli.stdout, cli.stdout[-200:])


# ---------------------------------------------------------------------------
# 2. a stale marker (the defect the audit found after the Word refresh)
# ---------------------------------------------------------------------------
def test_stale_marker():
    tmp = scratch("zp_stale_")
    p = _docx(tmp / "main.docx", [],
              marker_overrides={"citeB": r"\super 39,40\nosupersub{}", "citeB-vis": "39,40"})
    rows = fmt.zotero_parity_rows(
        zipfile.ZipFile(p).read("word/document.xml").decode("utf-8"),
        [fmt.text_of(q) for _a, _b, q in fmt.paragraphs(
            zipfile.ZipFile(p).read("word/document.xml").decode("utf-8"))])
    z1 = [r for r in rows if r["rule"] == "FMT-Z1"]
    check("FMT-Z1 reports the stale marker (one row per field)", len(z1) == 1,
          str([r["evidence"] for r in rows]))
    check("FMT-Z1 names the shown numbers and their ranks",
          bool(z1) and "shows 39" in z1[0]["evidence"] and "rank is 3" in z1[0]["evidence"]
          and "shows 40" in z1[0]["evidence"] and "rank is 4" in z1[0]["evidence"],
          str(z1[0]["evidence"]) if z1 else "")
    check("FMT-Z3 adds the bibliographic consequences (a number outside 1..N, entries "
          "never cited)",
          any(r["rule"] == "FMT-Z3" and "exceed" in r["evidence"] for r in rows)
          and any(r["rule"] == "FMT-Z3" and "never cited" in r["evidence"] for r in rows),
          str([r["evidence"][:60] for r in rows if r["rule"] == "FMT-Z3"]))
    check("a parity row is a field-protected row",
          bool(rows) and all(r["protected"] for r in rows))
    pkg = fmt.analyse_package(p, fmt.POLICY_DEFAULTS)
    check("the package scan carries the row as fix=manual (only Zotero can re-render it)",
          all(r["fix"] == "manual" for r in pkg["rows"] if r["rule"].startswith("FMT-Z")))
    cli = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), "zotero-check",
                          str(p)], capture_output=True, text=True, timeout=120)
    check("the zotero-check CLI exits 1 on a stale marker", cli.returncode == 1,
          cli.stdout[-160:])


# ---------------------------------------------------------------------------
# 3. a bibliography that describes other works (FMT-Z2)
# ---------------------------------------------------------------------------
def test_bibliography_mismatch():
    tmp = scratch("zp_bib_")
    p = _docx(tmp / "main.docx", [], entry_overrides={1: "Zzz, Q. et al. A different work. "
                                                                  "Journal 9, 1-2 (1999).",
                                                       2: "Yyy, R. et al. Another work. "
                                                          "Journal 8, 3-4 (1998)."})
    xml = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
    rows = fmt.zotero_parity_rows(xml, [fmt.text_of(q) for _a, _b, q in fmt.paragraphs(xml)])
    z2 = [r for r in rows if r["rule"] == "FMT-Z2"]
    check("FMT-Z2 reports the entry that describes another work", len(z2) >= 2,
          str([r["evidence"][:80] for r in rows]))
    check("FMT-Z2 names the cited title and the entry",
          all("cited item title" in r["evidence"] for r in z2))


# ---------------------------------------------------------------------------
# 4. the range marker, the half-updated field and the style conflict
# ---------------------------------------------------------------------------
def test_range_z4_z5():
    tmp = scratch("zp_misc_")
    # a range marker "1-2" (en dash in the stored escape) with two items
    p = _docx(tmp / "main.docx", [],
              marker_overrides={"citeA": r"\super 1\uc0\u8211{}2\nosupersub{}",
                                "citeA-vis": "1\u20132"})
    xml = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
    para = [fmt.text_of(q) for _a, _b, q in fmt.paragraphs(xml)]
    rows = fmt.zotero_parity_rows(xml, para)
    check("an en-dash range marker is expanded, not read as a count mismatch",
          not any(r["rule"] == "FMT-Z4" for r in rows), str(rows)[:200])
    check("the range's numbers are checked item by item (clean here)", rows == [], str(rows))
    # a half-updated field: the stored marker says 1,2 while the runs show 1,2,3
    p2 = _docx(tmp / "half.docx", [], marker_overrides={"citeA-vis": "1,2,3"})
    xml2 = zipfile.ZipFile(p2).read("word/document.xml").decode("utf-8")
    rows2 = fmt.zotero_parity_rows(xml2, [fmt.text_of(q) for _a, _b, q in fmt.paragraphs(xml2)])
    check("FMT-Z4 reports a stored marker that disagrees with the visible text",
          any(r["rule"] == "FMT-Z4" for r in rows2), str(rows2)[:200])
    # two conflicting style stores
    p3 = _docx(tmp / "styles.docx", [], styles={"word/settings.xml": STYLE_B,
                                                "docProps/custom.xml": STYLE_A})
    info = fmt.analyse_package(p3, fmt.POLICY_DEFAULTS)
    check("FMT-Z5 reports two conflicting Zotero style stores",
          any(r["rule"] == "FMT-Z5" for r in info["rows"]),
          str([r["rule"] for r in info["rows"]]))
    p4 = _docx(tmp / "onestyle.docx", [], styles={"word/settings.xml": STYLE_A})
    info4 = fmt.analyse_package(p4, fmt.POLICY_DEFAULTS)
    check("one style store is not a finding",
          not any(r["rule"] == "FMT-Z5" for r in info4["rows"]))


# ---------------------------------------------------------------------------
# 5. the version-to-version gate
# ---------------------------------------------------------------------------
def test_continuity_gate():
    tmp = scratch("zp_gate_")
    clean = _docx(tmp / "clean.docx", [])
    stale = _docx(tmp / "stale.docx", [],
                  marker_overrides={"citeB": r"\super 39,40\nosupersub{}", "citeB-vis": "39,40"})
    rep_clean = fmt.zotero_report_for_docx(clean)
    rep_stale = fmt.zotero_report_for_docx(stale)
    bad = fmt.zotero_field_continuity_problems(rep_clean, rep_stale)
    check("a version that INTRODUCES stale markers is a hard error",
          any("NEW stale-citation fault" in e for e in bad.get("errors", [])),
          str(bad.get("errors"))[:200])
    good = fmt.zotero_field_continuity_problems(rep_stale, rep_clean)
    check("a refresh that clears them is recorded, not an error",
          not any("stale-citation" in e for e in good.get("errors", []))
          and any("GONE" in w for w in good.get("warnings", [])),
          str(good.get("warnings"))[:200])


# ---------------------------------------------------------------------------
# 6. the sweep wiring
# ---------------------------------------------------------------------------
def test_wiring():
    sweeps = (WS / "paper-skills" / "paper-review" / "references" / "sweeps.md").read_text(
        encoding="utf-8")
    check("sweeps.md defines M36", "## M36 —" in sweeps)
    for rid in ("FMT-Z1", "FMT-Z2", "FMT-Z3", "FMT-Z4", "FMT-Z5"):
        check(f"sweeps.md documents {rid}", f"`{rid}`" in sweeps)
    check("sweeps.md announces M1-M36", "M1–M36" in sweeps)
    src = (WS / "paper_pipeline.py").read_text(encoding="utf-8")
    check("the review coverage contract requires M36",
          '"M31", "M32", "M33", "M34", "M35", "M36"' in src)
    check("the M36 artifact is part of the review contract",
          '"M36_zotero_parity.md"' in src)
    for where in ("review", "audit", "revise", "integrate", "rewrite"):
        block = pp.apply_evidence_integrity("@@EVIDENCE_INTEGRITY@@", where)
        check(f"the {where} prompt carries the M36 class",
              "M36" in block and "Zotero" in block)
    prof = pp.load_venue_profile("nature-biotechnology")
    prompt = pp.review_prompt(Path("/tmp/zp_sb"), "r1_review", 1, venue=prof)
    check("the review prompt tells the session how to resolve a stale marker",
          "zotero-check" in prompt and "M36_zotero_parity.md" in prompt)
    check("discovery proposals now start at M37",
          "M37" in prompt and "@@EVIDENCE_INTEGRITY@@" not in prompt)
    disc = (WS / "paper-skills" / "paper-review" / "references" / "discovery.md").read_text(
        encoding="utf-8")
    check("discovery.md says 41 check IDs and proposals start at M37",
          "41 check IDs (M1–M36, J1–J5)" in disc and "Proposals therefore start at M37" in disc)
    ip = (WS / "paper-skills" / "prompts" / "identify_issues.prompt.md").read_text(
        encoding="utf-8")
    check("the identify-issues appendix carries M36 verbatim",
          "## M36 —" in ip and "Proposals therefore start at M37" in ip)


def main() -> int:
    sections = [("clean", test_clean_document),
                ("stale_marker", test_stale_marker),
                ("bibliography_mismatch", test_bibliography_mismatch),
                ("range_z4_z5", test_range_z4_z5),
                ("continuity_gate", test_continuity_gate),
                ("wiring", test_wiring)]
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
    print("ALL ZOTERO REFRESH-PARITY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

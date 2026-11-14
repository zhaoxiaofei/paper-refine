#!/usr/bin/env python3
"""Regressions for the 2026-11-14 fix-bugs round, group C (DOCX text/layout/CLI).

Every check pins one candidate id from
`debug_runs/20261114-045738/02_verify_findings/verified_findings/verified_findings.json`:
the defect is reproduced against the current tree and the repaired behaviour is
asserted beside it. Run:

    conda run -n paper-refine-test python .paper_test/test_fix_bugs_20261114_C.py

Self-contained: tempfile fixtures only, no repo writes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_docx_format", str(WS / "paper_docx_format.py"))
fmt = importlib.util.module_from_spec(spec)
sys.modules["paper_docx_format"] = fmt
spec.loader.exec_module(fmt)

FAILS = []
TMP = Path(tempfile.mkdtemp(prefix="fixbugs_20261114_c_"))
W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
PAGE = '<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'ok ' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def make_docx(path: Path, body_extra: str = "", extra: dict = None) -> Path:
    xml = (f'<?xml version="1.0"?><w:document {W}><w:body>'
           f'<w:p><w:r><w:t>Body text of the manuscript.</w:t></w:r></w:p>'
           f'{body_extra}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def cli(*args: str):
    p = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), *args],
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------------------------------------------------------------------
# F17 -- the table-value token cap is not silent
# ---------------------------------------------------------------------------
def test_f17_table_token_cap() -> None:
    print("\n== F17: table_value_tokens cap is recorded, not silent ==")
    text = "\n".join(["tool\tscore"] + [f"tool_{i:03d}\t{i}" for i in range(450)])
    stats = {}
    toks = fmt.table_value_tokens([("toy.tsv", text)], stats=stats)
    check("F17 the cap still bounds the vocabulary", len(toks) == 400, str(len(toks)))
    check("F17 the truncation is counted", stats.get("total") == 450
          and stats.get("omitted") == 50, str(stats))
    gap = [r for r in fmt.negative_claim_rows(
        ["tool_449 could not be run on the cohort."], [("toy.tsv", text)])
        if r.get("token") == "(truncated)"]
    check("F17 the M30 seed carries an INCOMPLETE row", len(gap) == 1
          and "INCOMPLETE" in gap[0]["detail"] and "50" in gap[0]["detail"], str(gap))
    # A value INSIDE the cap keeps its real row (no regression).
    hit = [r for r in fmt.negative_claim_rows(
        ["tool_000 could not be run on the cohort."], [("toy.tsv", text)])
        if r.get("token") == "tool_000"]
    check("F17 a compared value still files its claim row", len(hit) == 1, str(hit))


# ---------------------------------------------------------------------------
# F20 -- LaTeX \code{}/\verb spans are not prose for the spelling rule
# ---------------------------------------------------------------------------
def test_f20_latex_code_mask() -> None:
    print("\n== F20: spelling_nonprose_mask masks LaTeX code/verbatim ==")
    raw = r"We label the tumour types; the code prints \code{catalogue} and \code{colour} identifiers."
    masked = fmt.spelling_nonprose_mask(raw)
    check("F20 the mask keeps the length", len(masked) == len(raw), str(len(masked)))
    check("F20 \\code{} literals are blanked",
          "catalogue" not in masked and "colour" not in masked, masked)
    check("F20 real prose keeps its spelling", "tumour" in masked, masked)
    verb = r"A \verb|colour| literal and \verb+tumour+ too."
    vmasked = fmt.spelling_nonprose_mask(verb)
    check("F20 \\verb delimiters are blanked",
          "colour" not in vmasked and "tumour" not in vmasked, vmasked)
    rows = fmt.variant_rows(
        ["The tumor samples were analysed.", r"Calling \code{tumour} returns the label."],
        [False, False])
    check("F20 a code-only variant files no FMT-T8d", rows == [], str(rows))


# ---------------------------------------------------------------------------
# F21 -- the parenthetical rule does not police the reference list
# ---------------------------------------------------------------------------
def test_f21_nested_parens_reference_list() -> None:
    print("\n== F21: FMT-T8b skips the reference list ==")
    bib = "Smith J. A method for calls (see (Doe, 2019) for the original). Nature 1, 1-2 (2020)."
    body = "Body sentence about the method (a first group (and an inner one)) here."
    rows = fmt.text_style_rows([bib, body], [True, False])
    t8b = [r for r in rows if r.get("rule") == "FMT-T8b"]
    check("F21 the bibliography entry files no FMT-T8b",
          all("Doe" not in r["evidence"] for r in t8b), str(t8b))
    check("F21 the body paragraph still files its FMT-T8b", len(t8b) == 1, str(t8b))
    # The default (no is_ref) keeps the old, argument-compatible behaviour.
    check("F21 nested_parentheses_rows still works positionally",
          fmt.nested_parentheses_rows([body])[0]["rule"] == "FMT-T8b")


# ---------------------------------------------------------------------------
# F23 -- a duplicate PAGE paragraph carrying a drawing is left to the author
# ---------------------------------------------------------------------------
def test_f23_page_field_keeps_drawing() -> None:
    print("\n== F23: page_field_fixes never splices out non-text content ==")
    hdr = (f'<?xml version="1.0"?><w:hdr {W}>'
           f'<w:p><w:r><w:t>Page </w:t></w:r>{PAGE}</w:p>'
           f'<w:p><w:r><w:t>2</w:t></w:r><w:r><w:drawing><wp:inline '
           f'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
           f'<wp:extent cx="914400" cy="914400"/></wp:inline></w:drawing></w:r>{PAGE}</w:p>'
           f'</w:hdr>')
    fixes = fmt.page_field_fixes(hdr)
    out = fmt.apply_edits(hdr, fixes) if fixes else hdr
    check("F23 the drawing-bearing paragraph is refused", fixes == [], str(fixes))
    check("F23 the drawing survives", "<w:drawing" in out)
    # A plain duplicate PAGE paragraph is still repaired.
    plain = ('<w:hdr ' + W + f'><w:p><w:r><w:t>Page </w:t></w:r>{PAGE}</w:p>'
             f'<w:p><w:r><w:t>2</w:t></w:r>{PAGE}</w:p></w:hdr>')
    pfix = fmt.page_field_fixes(plain)
    check("F23 a text-only duplicate PAGE paragraph is still deleted",
          len(pfix) == 1 and "<w:t>2</w:t>" not in fmt.apply_edits(plain, pfix), str(pfix))


# ---------------------------------------------------------------------------
# F24 -- the caption merge keeps ONE complex-script companion
# ---------------------------------------------------------------------------
def test_f24_caption_companion_unique() -> None:
    print("\n== F24: caption continuation rPr keeps one bCs/szCs ==")
    styles = {"B": {"b": False, "sz": 20}, "A": {"b": True, "sz": 20}}
    run = '<w:r><w:rPr><w:bCs w:val="1"/><w:szCs w:val="30"/></w:rPr><w:t>x</w:t></w:r>'
    out = fmt._caption_continuation_runs(run, styles, "B", "A")
    check("F24 bCs appears once", out.count("<w:bCs") == 1, out)
    check("F24 szCs appears once", out.count("<w:szCs") == 1, out)
    check("F24 the companion agrees with the primary value",
          'w:val="0"' in out.split("<w:bCs")[1][:20], out)
    # A run with no companion still gets the pair.
    bare = fmt._caption_continuation_runs('<w:r><w:t>y</w:t></w:r>', styles, "B", "A")
    check("F24 an absent companion is still added", "<w:bCs" in bare, bare)


# ---------------------------------------------------------------------------
# F25 -- the documented --out is written on a no-op success path
# ---------------------------------------------------------------------------
def test_f25_noop_out_is_written() -> None:
    print("\n== F25: no-op writers still materialise `out` ==")
    clean = make_docx(TMP / "f25_clean.docx")
    out = TMP / "f25_refresh.docx"
    rc, text = cli("zotero-refresh", str(clean), "--out", str(out))
    check("F25 zotero-refresh --out exits 0 and writes the copy",
          rc == 0 and out.is_file(), f"rc={rc} out={(text or '')[:160]!r}")
    res = fmt.strip_reference_sentences(clean, TMP / "f25_strip.docx", lambda t: [])
    check("F25 strip_reference_sentences writes its no-op copy",
          res.get("ok") is True and (TMP / "f25_strip.docx").is_file(), str(res)[:200])
    res2 = fmt.strip_local_path_links(clean, TMP / "f25_links.docx")
    check("F25 strip_local_path_links writes its no-op copy",
          res2.get("ok") is True and (TMP / "f25_links.docx").is_file(), str(res2)[:200])
    if (TMP / "f25_strip.docx").is_file():
        with zipfile.ZipFile(clean) as a, zipfile.ZipFile(TMP / "f25_strip.docx") as b:
            check("F25 the no-op copy keeps the document part",
                  a.read("word/document.xml") == b.read("word/document.xml"))


# ---------------------------------------------------------------------------
# F26 -- zotero-check --json writes a failure report
# ---------------------------------------------------------------------------
def test_f26_zotero_check_json_on_failure() -> None:
    print("\n== F26: zotero-check --json reports an unreadable DOCX ==")
    bad = TMP / "f26_bad.docx"
    bad.write_bytes(b"not a zip")
    jp = TMP / "f26.json"
    rc, text = cli("zotero-check", str(bad), "--json", str(jp))
    check("F26 the failure still exits 1", rc == 1, f"rc={rc}")
    data = json.loads(jp.read_text(encoding="utf-8")) if jp.is_file() else {}
    check("F26 the JSON is written", jp.is_file() and data.get("ok") is False, str(data)[:200])
    check("F26 the JSON records the error",
          "unreadable DOCX" in str(data.get("error")) and bool(data.get("field_integrity_faults")),
          str(data)[:200])


# ---------------------------------------------------------------------------
# F27/F28 -- "read nothing, report clean" is not a clean pass
# ---------------------------------------------------------------------------
def test_f27_f28_empty_paths() -> None:
    print("\n== F27/F28: a path with no document is not a clean pass ==")
    empty = TMP / "f27_empty"
    empty.mkdir(parents=True, exist_ok=True)
    rc, text = cli("scan", str(empty))
    check("F27 scan of an empty dir exits non-zero", rc == 2, f"rc={rc} {text[:120]!r}")
    check("F27 scan says it did not check",
          "not checked" in text and "clean" not in text, text[:160])
    rc, text = cli("validate", str(empty))
    check("F28 validate of an empty dir exits non-zero", rc == 2, f"rc={rc} {text[:120]!r}")
    check("F28 validate says it did not check",
          "not checked" in text and "0 failure" not in text, text[:160])
    # A real document is still a real (clean) scan.
    doc = TMP / "f27_ok"
    doc.mkdir(parents=True, exist_ok=True)
    make_docx(doc / "main.docx")
    rc, text = cli("scan", str(doc))
    check("F27 a scanned document keeps the clean summary", rc == 0
          and "OOXML formatting: clean" in text, f"rc={rc} {text[:160]!r}")


# ---------------------------------------------------------------------------
# F31 -- an unreadable rendered PDF falls back to the cached page count
# ---------------------------------------------------------------------------
def test_f31_cover_letter_pdf_read_failure() -> None:
    print("\n== F31: a corrupt rendered PDF does not skip the page budget ==")
    d = TMP / "f31"
    d.mkdir(parents=True, exist_ok=True)
    letter = make_docx(d / "cover_letter.docx", extra={
        "docProps/app.xml":
            '<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/'
            'officeDocument/2006/extended-properties"><Pages>5</Pages></Properties>'})
    (d / "cover_letter.pdf").write_bytes(b"garbage not a pdf")
    pol = d / "policy.json"
    pol.write_text(json.dumps({"page_budget": {"cover_letter_max_pages": 2}}), encoding="utf-8")
    rows = fmt.analyse_package(letter, fmt.load_policy(str(pol)))["rows"]
    hit = [r for r in rows if r["rule"] == "FMT-T8h"]
    check("F31 the cached 5-page count still trips the 2-page budget",
          len(hit) == 1 and "5 page(s)" in hit[0]["evidence"], str(hit))


# ---------------------------------------------------------------------------
# F32 -- a refused Zotero refresh reaches the fix CLI
# ---------------------------------------------------------------------------
def test_f32_fix_reports_refused_refresh() -> None:
    print("\n== F32: fix's summary names a refused Zotero refresh ==")
    cite = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM CSL_CITATION '
            '{"citationID":"abc","properties":{"formattedCitation":"(1)",'
            '"plainCitation":"(1)"},"citationItems":[{"id":1,"itemData":{"id":1,'
            '"type":"article-journal","title":"T","author":[{"family":"A"}],'
            '"issued":{"date-parts":[[2020]]}}}} </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    src = make_docx(TMP / "f32_src.docx", extra={
        "word/header1.xml": f'<?xml version="1.0"?><w:hdr {W}>{cite}</w:hdr>',
        "word/_rels/document.xml.rels":
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId8" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/header" '
            'Target="header1.xml"/></Relationships>'})
    rep = fmt.fix_package(src, TMP / "f32_out.docx", dict(fmt.POLICY_DEFAULTS))
    skip = str((rep.get("zotero_refresh") or {}).get("skip") or "")
    check("F32 the package reports the refusal in its report", "header1.xml" in skip, skip)
    out = TMP / "f32_cli.docx"
    rc, text = cli("fix", str(src), "--out", str(out))
    check("F32 the CLI prints the refusal", "[gap]" in text and "header1.xml" in text,
          text[-300:])
    check("F32 the mechanical fix is still delivered", rc == 0 and out.is_file(), f"rc={rc}")


# ---------------------------------------------------------------------------
# F33 -- image_aspect_tolerance: 0 means exact, not the 0.02 default
# ---------------------------------------------------------------------------
def test_f33_zero_aspect_tolerance() -> None:
    print("\n== F33: an exact-ratio policy is honoured ==")
    xml = ('<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/'
           'drawingml/2006/wordprocessingDrawing"><wp:extent cx="1010000" cy="1000000"/>'
           '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
           '<a:graphicData><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/'
           '2006/picture"><pic:blipFill><a:blip r:embed="rId9"/></pic:blipFill></pic:pic>'
           '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    rels = {"rId9": "word/media/img1.png"}
    sizes = {"word/media/img1.png": (100, 100)}
    default = dict(fmt.POLICY_DEFAULTS, image_aspect_tolerance=0.02)
    exact = dict(fmt.POLICY_DEFAULTS, image_aspect_tolerance=0)
    lazy = [r["rule"] for r in fmt.drawing_geometry_rows(
        xml, rels, sizes, "d.docx", default)[0]]
    strict = [r["rule"] for r in fmt.drawing_geometry_rows(
        xml, rels, sizes, "d.docx", exact)[0]]
    check("F33 the 1% error passes the 2% default", lazy == [], str(lazy))
    check("F33 tolerance 0 files the 1% error", strict == ["FMT-IM1"], str(strict))


# ---------------------------------------------------------------------------
# F34 -- xfa-export distinguishes an unreadable input from an empty form
# ---------------------------------------------------------------------------
def test_f34_xfa_export_missing_input() -> None:
    print("\n== F34: xfa-export reports an unreadable PDF as an input error ==")
    missing = TMP / "f34_missing.pdf"
    rc, text = cli("xfa-export", str(missing))
    check("F34 a missing PDF exits 2", rc == 2, f"rc={rc} {text[:160]!r}")
    check("F34 the message names the unreadable input",
          "cannot read" in text and "no such file" in text, text[:160])
    check("F34 it no longer claims the form has no answers",
          "no XFA dataset answers" not in text, text[:160])
    # A readable PDF with no XFA data keeps the "nothing to export" message.
    plain = TMP / "f34_plain.pdf"
    plain.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
    rc2, text2 = cli("xfa-export", str(plain))
    check("F34 a readable empty form keeps its own message",
          rc2 == 1 and "no XFA dataset answers" in text2, f"rc={rc2} {text2[:160]!r}")


def main() -> int:
    test_f17_table_token_cap()
    test_f20_latex_code_mask()
    test_f21_nested_parens_reference_list()
    test_f23_page_field_keeps_drawing()
    test_f24_caption_companion_unique()
    test_f25_noop_out_is_written()
    test_f26_zotero_check_json_on_failure()
    test_f27_f28_empty_paths()
    test_f31_cover_letter_pdf_read_failure()
    test_f32_fix_reports_refused_refresh()
    test_f33_zero_aspect_tolerance()
    test_f34_xfa_export_missing_input()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

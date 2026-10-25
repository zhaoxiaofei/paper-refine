#!/usr/bin/env python3
"""Regressions for the confirmed findings of the 2026-10-25 fix-bugs stage.

Every check is a repro that failed on the pre-fix tree (or a direct assertion
of the corrected invariant). Hermetic: temp dirs only, no network, no Word.

Run:  python3 .paper_test/test_fix_bugs_20261025_stage.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def mini_docx(path: Path, body: str) -> Path:
    """A minimal readable .docx whose document body is `body` (wordprocessingML)."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (f'<w:document xmlns:w="{ns}"><w:body>{body}<w:sectPr/></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", xml)
    return path


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


fmt = load("stage_fmt", WS / "paper_docx_format.py")
pp = load("stage_pp", WS / "paper_pipeline.py")
en = load("stage_en", WS / "paper-skills/paper-review/scripts/extract_numbers.py")
ec = load("stage_ec", WS / "paper-skills/paper-review/scripts/extract_citations.py")
cw = load("stage_cw", WS / "paper-skills/paper-review/scripts/count_words.py")
ps = load("stage_ps", WS / "pairwise_scores.py")


# ---------------------------------------------------------------- F001
def test_f001_view_layout_collision():
    print("\n== F001: evidence view directories cannot collide ==")
    files = [("raw_data/figures/fig1.png", "s"),
             ("raw_data/source_data/table.png", "s"),
             ("raw_data/figures/sub/fig2.png", "s"),
             ("raw_data/figures/sub/deep/x.png", "s")]
    dirs, file_map = pp._view_layout(files, 1, "v", "seed")
    check("sibling evidence directories get distinct anonymous names",
          dirs["raw_data/figures"] != dirs["raw_data/source_data"], str(dirs))
    check("every file maps to a distinct target path",
          len(set(file_map.values())) == len(files), str(file_map))


# ---------------------------------------------------------------- F052/F017/F126/F014/F012/F071
def test_docx_layout():
    print("\n== DOCX layout defects ==")
    heading = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
               '<w:r><w:t>Results</w:t></w:r></w:p>')
    sect = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '</w:sectPr></w:pPr></w:p>')
    body = '<w:p><w:r><w:t>Body</w:t></w:r></w:p>'
    parts = [(0, len(heading), heading),
             (len(heading), len(heading) + len(sect), sect),
             (len(heading) + len(sect), len(heading) + len(sect) + len(body), body)]
    groups, _p = fmt.stray_empty_paragraph_groups(parts, {"max_empty_paragraph_run": 1}, "")
    check("a section-break paragraph is never a stray empty paragraph",
          all(1 not in indices for indices, _kind in groups), str(groups))

    for url in ("https://example.com/path?x=ab,cd&y=2",
                "https://example.com/path#ab,cd",
                "https://example.com/?ab,cd"):
        check(f"a URL comma is not an FMT-G3 typo: {url}",
              not fmt._MISSING_SPACE_RE.search(url), str(fmt._MISSING_SPACE_RE.findall(url)))
    check("a real missing space still matches",
          bool(fmt._MISSING_SPACE_RE.search("default,however")))

    check("an expandable 1000-1020 citation range expands",
          fmt._marker_range_numbers(1000, 1020) == list(range(1000, 1021)))
    check("a publication-year range still yields nothing",
          fmt._marker_range_numbers(2019, 2020) == [])
    check("a backwards span keeps its written order",
          fmt._marker_range_numbers(2019, 3) == [2019, 3])

    para = ('<w:p><w:r><w:t xml:space="preserve">and the</w:t></w:r><w:br/>'
            '<w:r><w:t xml:space="preserve"> the end</w:t></w:r></w:p>')
    spans = fmt.hygiene_spans(para)
    edits = [(s["start"], s["end"], s["repl"]) for s in spans
             if s["fix"] == "mechanical"]
    new, _applied = fmt.rewrite_text_spans(para, edits)
    check("a doubled word after a soft break is deleted, the break kept",
          fmt.text_of(new) == "and the\nend", repr(fmt.text_of(new)))

    grp = ('<w:drawing><wp:anchor><wp:extent cx="1000000" cy="2000000"/>'
           '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/'
           'drawingml/2006/wordprocessingGroup"><wpg:wgp>'
           '<wpg:grpSpPr><a:xfrm><a:ext cx="2000000" cy="4000000"/></a:xfrm>'
           '</wpg:grpSpPr><wpg:pic><p:pic><p:blipFill><a:blip r:embed="rId1"/>'
           '</p:blipFill><p:spPr><a:xfrm><a:ext cx="4500000" cy="4500000"/>'
           '</a:xfrm></p:spPr></p:pic></wpg:pic></wpg:wgp></a:graphicData>'
           '</a:graphic></wp:anchor></w:drawing>')
    xml = ('<w:document xmlns:w="http://x" xmlns:r="http://r" xmlns:wp="http://wp" '
           'xmlns:a="http://a" xmlns:wpg="http://wpg" xmlns:p="http://p"><w:body>'
           '<w:p>' + grp + '</w:p></w:body></w:document>')
    rows, fixes = fmt.drawing_geometry_rows(
        xml, {"rId1": "media/fig.png"}, {"word/media/fig.png": (100, 100)}, "x.docx", {})
    check("a grouped drawing is not repaired from its first child's ratio",
          rows == [] and fixes == [], f"{rows} {fixes}")

    label = ('<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr>'
             '<w:r><w:t>Figure 1. A caption</w:t></w:r></w:p>')
    cont = ('<w:p><w:pPr><w:pPrChange w:author="a"><w:pPr/></w:pPrChange>'
            '</w:pPr><w:r><w:t>continues here.</w:t></w:r></w:p>')
    block = [(0, len(label), label),
             (len(label), len(label) + len(cont), cont)]
    check("a caption continuation carrying pPrChange is not merged",
          fmt.caption_block_mergeable(block) is False)


# ---------------------------------------------------------------- F010/F015/F059/F086/F080/F079
def test_docx_cli_rules():
    print("\n== DOCX scanner/fixer defects ==")
    paras = ["We used copy-number profiles.",
             "The copy number of a locus was estimated."]
    rows = fmt.variant_rows(paras, [False, False])
    check("the noun use 'copy number of' does not fire FMT-T8e",
          not any(r["rule"] == "FMT-T8e" for r in rows), str(rows))

    field = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM '
             'CSL_CITATION {"citationID":"abc"} </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             '<w:r><w:t>[1]</w:t></w:r>'
             '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    doc = ('<w:document xmlns:w="http://x"><w:body>' + field
           + '</w:body></w:document>')
    faults = fmt.zotero_structural_faults(fmt.zotero_field_report(doc))
    check("a duplicate separator inside a Zotero field is reported",
          len(faults) == 1 and "duplicate-separate" in faults[0], str(faults))
    page = field.replace(' ADDIN ZOTERO_ITEM CSL_CITATION {"citationID":"abc"} ', ' PAGE ')
    check("a duplicate separator in a non-Zotero field stays out of zotero-check",
          fmt.zotero_structural_faults(fmt.zotero_field_report(
              '<w:document xmlns:w="http://x"><w:body>' + page
              + '</w:body></w:document>')) == [])

    rel_a = ('<Relationships><Relationship Id="rId1" Type="http://x/header" '
             'Target="header1.xml"/></Relationships>')
    rel_b = ('<Relationships><Relationship Target="header1.xml" Id="rId1" '
             'Type="http://x/header"/></Relationships>')
    check("a .rels entry is read in any attribute order",
          fmt._rels_entries(rel_a) == fmt._rels_entries(rel_b) != [])

    d = scratch("stage_validate_")
    bad = d / "summary.pdf"
    bad.write_bytes(b"%PDF-1.4")
    rep = fmt.validate_paths([bad])
    check("validating an unsupported file is a failure, not 0 files of success",
          rep["files"] == 1 and rep["failed"] == 1 and rep["ok"] is False, str(rep))

    real_which = fmt.shutil.which
    try:
        fmt.shutil.which = lambda name: None if name == "pdftotext" else real_which(name)
        res = fmt.check_pdf(bad, fmt.load_policy(None))
        check("a missing pdftotext is NOT CHECKED, not a clean 0-page pass",
              res["ok"] is None)
    finally:
        fmt.shutil.which = real_which
    empty_path = scratch("stage_nopath_")
    env = dict(os.environ, PATH=str(empty_path))
    proc = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"),
                           "check-pdf", str(bad)],
                          cwd=str(WS), text=True, capture_output=True, env=env)
    check("the check-pdf CLI says NOT CHECKED and exits 1 without pdftotext",
          proc.returncode == 1 and "NOT CHECKED" in proc.stdout,
          f"rc={proc.returncode} out={proc.stdout[-120:]!r} err={proc.stderr[-120:]!r}")

    # F015/F123: a spelling/hyphenation occurrence inside a live field result
    # cannot be edited by the fixer; the row must be field-held, never
    # mechanical, or fix_package rejects the whole file it just repaired.
    def p(t):
        return f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'

    field = ('<w:p><w:r><w:t>A field: </w:t></w:r>'
             '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             '<w:r><w:t>colour</w:t></w:r>'
             '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    d = scratch("stage_fieldspell_")
    pkg = mini_docx(d / "spell.docx",
                    p("We used color profiles.") + p("Another color analysis.")
                    + p("A third color result.") + field)
    rows = [r for r in fmt.analyse_package(pkg, fmt.load_policy(None))["rows"]
            if r["rule"] == "FMT-T8d"]
    check("a spelling variant held in a field result is field-held, not mechanical",
          len(rows) == 1 and rows[0]["fix"] == "style-field" and rows[0]["protected"],
          str(rows))
    res = fmt.fix_package(pkg, d / "spell.out.docx", fmt.load_policy(None))
    check("a field-held spelling variant does not reject the repaired file",
          res.get("ok") is True
          and not res.get("verified", {}).get("remaining_mechanical_rules"),
          str(res.get("verified", {}).get("remaining_mechanical_rules")))

    # The fixer must not act on a use the scanner classifies as the noun use.
    # "single-cell and" is excluded by the same follower rule on both sides: no
    # FMT-T8e row, and no unaudited hyphenation of the unrelated open form.
    m_paras = ["We compared single-cell and bulk RNA-seq in this study.",
               "We prepared single cell suspensions from the tissue."]
    rows = fmt.variant_rows(m_paras, [False, False])
    check("a noun-coordinating use is not an FMT-T8e row",
          not any(r["rule"] == "FMT-T8e" for r in rows), str(rows))
    md = scratch("stage_hytarget_")
    mpkg = mini_docx(md / "hy.docx",
                     p(m_paras[0]) + p(m_paras[1]))
    mres = fmt.fix_package(mpkg, md / "hy.out.docx", fmt.load_policy(None))
    check("the fixer makes no unaudited hyphenation edit",
          not any("hyphenat" in c for c in mres.get("changes") or []),
          str(mres.get("changes")))


# ---------------------------------------------------------------- F054/F074/F072/F122/F043/F148/F036
def test_pipeline_text():
    print("\n== pipeline decision/report defects ==")
    readiness = {"submission_ready": False,
                 "findings": [{"rule": "AUTH-1", "advisory": True,
                               "detail": "hand-off-marker scan FAILED"}]}
    probs = pp.readiness_gate_problems(readiness, True)
    check("--require-ready does not cite an advisory row as its reason", probs == [], str(probs))
    blocking = {"submission_ready": False,
                "findings": [{"rule": "PKG-5", "detail": "x"},
                             {"rule": "AUTH-1", "advisory": True, "detail": "y"}]}
    probs = pp.readiness_gate_problems(blocking, True)
    check("--require-ready counts only blocking findings",
          probs and "1 package-level finding" in probs[0], str(probs))
    check("a failed hand-off-marker residual is mirrored into readiness",
          "hand-off-marker scan FAILED" in " ".join(
              f.get("detail", "") for f in pp.package_readiness(
                  None, residuals={"items": [
                      "r1: the hand-off-marker scan FAILED (boom)"]},
                  author_to_complete="off").get("findings", [])), "not found")

    check("a sentence-final superscript citation is seen",
          pp.INLINE_CITATION_RE.findall("We used single-cell omics43.") == [("omics", "43")])
    check("a decimal is still not a citation",
          pp.INLINE_CITATION_RE.findall("value 43.5 here") == [])

    check("a typographic minus score parses",
          ps.parse_score("\u22120.5") == -0.5 and ps.parse_score("\u2013.5") == -0.5)

    manifest = {"pipeline_root": ".", "versions": [{"round": 1, "comparisons": [
        {"ok": False, "skipped": True, "tool": None},
        {"ok": False, "skipped": False, "tool": None},
        {"ok": True, "tool": "x"}]}]}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pp.tracking_summary(manifest)
    line = [ln for ln in buf.getvalue().splitlines()
            if ln.startswith("[track]") and "tracked copy" in ln][0]
    check("an intentionally skipped tool=none row is not also counted FAILED",
          "1 skipped (tool=none)" in line and "1 FAILED" in line, line)

    proc = subprocess.run([sys.executable, str(WS / ".paper_test/run_all.py"),
                           "--only", "definitely-not-a-suite"],
                          cwd=str(WS), text=True, capture_output=True)
    check("run_all usage error exits 2", proc.returncode == 2, f"rc={proc.returncode}")


# ---------------------------------------------------------------- F011/F060/F130
def test_tables_and_stats():
    print("\n== table widths and Holm family ==")
    def table(tcw_type):
        return ('<w:tbl><w:tblGrid><w:gridCol w:w="4320"/><w:gridCol w:w="4320"/>'
                '</w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:type="' + tcw_type
                + '" w:w="2500"/></w:tcPr><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>'
                '<w:tc><w:tcPr><w:tcW w:type="' + tcw_type
                + '" w:w="2500"/></w:tcPr><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc>'
                '</w:tr></w:tbl>')
    for kind in ("pct", "auto"):
        xml = ('<w:document xmlns:w="http://x"><w:body>' + table(kind)
               + '</w:body></w:document>')
        check(f"a {kind} table is not repaired from percent/auto numbers",
              fmt.table_layout_rows(xml, {}, "x.docx") == [], kind)
    xml = ('<w:document xmlns:w="http://x"><w:body>' + table("dxa")
           + '</w:body></w:document>')
    check("a dxa table still gets FMT-TB4",
          any(r["rule"] == "FMT-TB4" for r in fmt.table_layout_rows(xml, {}, "x")))

    paras = ["Table S3. Holm single pooled family of 4."] + \
            [f"Method{i} 10 9 0.020 1.00" for i in range(8)]
    check("the caption's stated family size wins over the row count",
          fmt.stats_floor_rows(paras) == [], str(fmt.stats_floor_rows(paras)))


# ---------------------------------------------------------------- F055/F063/F121
def test_pipeline_corpus():
    print("\n== judge-view / logging fallback defects ==")
    files = [("main.tex", "s"), ("chapters/methods.tex", "s"), ("refs.bib", "s")]
    _dirs, file_map = pp._view_layout(files, 1, "v", "seed")
    src = r"\input{chapters/methods}\bibliography{refs}"
    out = pp._rewrite_view_references(src, "main.tex", file_map["main.tex"], file_map)
    check("extension-less \\input/\\bibliography stems are rewritten",
          "chapters/methods" not in out and "refs" not in out, out)
    check("the rewritten \\input points at the anonymous .tex",
          "\\input{" in out and file_map["chapters/methods.tex"].rsplit(".", 1)[0] in out, out)

    # A standalone source and its compiled target share a stem; the stem maps
    # must not compete for it.
    dirs, fmap = pp._view_layout([("figs/plot.tex", "s"), ("figs/plot.pdf", "s"),
                                  ("main.tex", "s")], 1, "v", "figseed")
    inc = pp._rewrite_view_references(r"\includegraphics{plot}", "main.tex",
                                      fmap["main.tex"], fmap)
    inp = pp._rewrite_view_references(r"\input{plot}", "main.tex", fmap["main.tex"], fmap)
    check("\\includegraphics maps a stem to the target, never the source",
          inc == "\\includegraphics{" + Path(fmap["figs/plot.pdf"]).stem + "}", inc)
    check("\\input maps a stem to the source, never the target",
          inp == "\\input{" + Path(fmap["figs/plot.tex"]).stem + "}", inp)

    nested = ('<w:document xmlns:w="http://x"><w:body><w:p>'
              '<w:del w:id="1" w:author="a"><w:r><w:t>A</w:t></w:r>'
              '<w:del w:id="2" w:author="a"><w:r><w:t>B</w:t></w:r></w:del>'
              '<w:r><w:t>C</w:t></w:r></w:del><w:r><w:t>D</w:t></w:r></w:p>'
              '</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", nested)
    out, _notes = pp._sanitize_ooxml_bytes(buf.getvalue())
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        got = z.read("word/document.xml")
    check("a nested tracked deletion is removed as a whole",
          b"A" not in got and b"B" not in got and b"C" not in got and b"D" in got, got)
    check("the accepted document stays well-formed",
          __import__("xml.etree.ElementTree", fromlist=["fromstring"]).fromstring(got) is not None)

    # A SELF-CLOSING nested mark must not pair with the outer element's close.
    selfclosed = ('<w:document xmlns:w="http://x"><w:body><w:p>'
                  '<w:del w:id="1"><w:r><w:t>A</w:t></w:r><w:del w:id="2"/></w:del>'
                  '<w:r><w:t>D</w:t></w:r></w:p></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("word/document.xml", selfclosed)
    out2, _notes = pp._sanitize_ooxml_bytes(buf.getvalue())
    with zipfile.ZipFile(io.BytesIO(out2)) as z:
        got2 = z.read("word/document.xml")
    try:
        __import__("xml.etree.ElementTree", fromlist=["fromstring"]).fromstring(got2)
        wf = True
    except Exception:                                            # noqa: BLE001
        wf = False
    check("a self-closing nested revision mark leaves well-formed XML", wf, got2)


    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def para(t):
        return f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'

    def tbl(a, b):
        return ('<w:tbl><w:tr><w:tc>' + para(a) + '</w:tc><w:tc>' + para(b)
                + '</w:tc></w:tr></w:tbl>')

    def doc(ps, table):
        return ('<w:document xmlns:w="' + W + '"><w:body>'
                + "".join(para(t) for t in ps) + table
                + '<w:sectPr/></w:body></w:document>')

    d = scratch("stage_logfb_")
    base, cand, outd = d / "base.docx", d / "cand.docx", d / "out.docx"
    for path, payload in ((base, doc(["Intro unchanged", "Old paragraph"],
                                     tbl("Table cell A", "Table cell B"))),
                          (cand, doc(["Intro unchanged", "New paragraph"],
                                     tbl("Table cell A", "Table cell B")))):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
            z.writestr("word/document.xml", payload)
    rep = pp.write_docx_logging_fallback(base, cand, outd, "original", "test")
    with zipfile.ZipFile(outd) as z:
        text = z.read("word/document.xml").decode()
    check("the logging fallback writes once",
          rep.get("ok") and text.count("Table cell A") == 1
          and text.count("Table cell B") == 1, text)
    check("an unchanged table cell is not marked BEFORE",
          "[BEFORE: Table cell A]" not in text and "[BEFORE: Table cell B]" not in text)

    # A table-only edit must not be reported as "no textual difference".
    d2 = scratch("stage_logfb_table_")
    base2, cand2, out2 = d2 / "base.docx", d2 / "cand.docx", d2 / "out.docx"
    for path, payload in ((base2, doc(["A", "B"], tbl("x", "y"))),
                          (cand2, doc(["A", "B"], tbl("x2", "y")))):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
            z.writestr("word/document.xml", payload)
    rep2 = pp.write_docx_logging_fallback(base2, cand2, out2, "original", "test")
    with zipfile.ZipFile(out2) as z:
        text2 = z.read("word/document.xml").decode()
    check("a table-only change is recorded, not called no-difference",
          rep2.get("ok") and "no textual difference" not in text2
          and "[BEFORE: x]" in text2 and "[AFTER: x2]" in text2, text2[:400])



# ---------------------------------------------------------------- extract_numbers cluster
def test_extract_numbers():
    print("\n== number extractor defects ==")
    pats = dict(en.LABEL_PATTERNS)
    ranges = [("-80 C to -60 C", "-80", "C"),
              ("from 90% to 10%", "90", "%"),
              ("from 10 mg/L to 2 mg/L", "10", "mg/L"),
              ("from 5 µg to 2 µg", "5", "µg")]
    for text, low, unit in ranges:
        m = en.RANGE_RE.search(text)
        check(f"a range is read with its sign/unit: {text}", m is not None
              and m.group("low") == low and m.group("u1") == unit,
              (m.group(0) if m else None))
    check("n = 1,234 is one count", pats["n"].search("n = 1,234").group(1) == "1,234")
    check("n = 12.5 is not a count", pats["n"].search("n = 12.5") is None)
    check("plural p-values extract", pats["p-value"].search("p-values < 0.05").group(1) == "0.05")
    check("a p-value 'of' form extracts", pats["p-value"].search("p-value of 0.03") is not None)
    check("AUC of 12 patients is not AUC 12", pats["AUC"].search("AUC of 12 patients") is None)
    check("AUC = 1 is still a perfect AUC", pats["AUC"].search("AUC = 1").group(1) == "1")
    check("0.05/.05/0.050 normalize to one key",
          en._metric_key("p-value", "0.05") == en._metric_key("p-value", ".05")
          == en._metric_key("p-value", "0.050"))
    check("a bare publication-year range is not a physical range",
          en.RANGE_RE.search("2019-2020") is None)
    check("2019-2020 is a year range, 1000-1020 an expandable citation range",
          fmt._marker_range_numbers(2019, 2020) == []
          and fmt._marker_range_numbers(1000, 1020) == list(range(1000, 1021)))


# ---------------------------------------------------------------- node helpers
def test_node_keys():
    print("\n== in-flight keys ==")
    node = shutil.which("node")
    if node is None:
        check("node is available for the in-flight-key checks", False)
        return
    d = scratch("stage_keys_")
    (d / "Real.docx").write_bytes(b"x")
    (d / "link.docx").symlink_to(d / "Real.docx")
    (d / "a").mkdir()
    (d / "b").mkdir()
    (d / "a" / "rev.docx").write_bytes(b"x")
    (d / "b" / "rev.docx").write_bytes(b"x")
    script = (
        "import { inFlightKey } from " + json.dumps(str(WS / "mcp-docx-compare" / "derived-output.mjs")) + ";\n"
        "console.log(inFlightKey(" + json.dumps(str(d / "Real.docx")) + ","
        + json.dumps(str(d / "a" / "rev.docx")) + "));\n"
        "console.log(inFlightKey(" + json.dumps(str(d / "Real.docx")) + ","
        + json.dumps(str(d / "b" / "rev.docx")) + "));\n")
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          cwd=str(WS), text=True, capture_output=True)
    lines = proc.stdout.strip().splitlines()
    check("two same-basename revised files share one redline key",
          proc.returncode == 0 and len(lines) == 2 and lines[0] == lines[1],
          proc.stdout + proc.stderr[-200:])
    script2 = (
        "import { pdfKey } from " + json.dumps(str(WS / "mcp-docx-converter" / "in-flight.mjs")) + ";\n"
        "console.log(pdfKey(" + json.dumps(str(d / "Real.docx")) + "));\n"
        "console.log(pdfKey(" + json.dumps(str(d / "link.docx")) + "));\n")
    proc = subprocess.run([node, "--input-type=module", "-e", script2],
                          cwd=str(WS), text=True, capture_output=True)
    lines = proc.stdout.strip().splitlines()
    check("a symlinked input and its realpath share one PDF key",
          proc.returncode == 0 and len(lines) == 2 and lines[0] == lines[1]
          and lines[0].endswith("real.pdf"), proc.stdout + proc.stderr[-200:])


def test_more_fixes():
    print("\n== remaining confirmed fixes ==")
    # F003: ensure_copy must compare against a manifest built with its options.
    d = scratch("stage_copy_")
    src, dst = d / "src", d / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    (src / "work").mkdir()
    (src / "work" / "x.txt").write_text("x", encoding="utf-8")
    seq = [pp.ensure_copy(src, dst, exclude_top=("work",)) for _ in range(3)]
    check("ensure_copy converges with the caller's exclusions", seq == [True, False, False], seq)

    # strip_bookkeeping filters a NAME at any depth in copy_into's ignore
    # callback; the expected manifest must agree.
    src2, dst2 = d / "src2", d / "dst2"
    (src2 / "sub").mkdir(parents=True)
    (src2 / "a.txt").write_text("a", encoding="utf-8")
    (src2 / "sub" / "REVISION_REPORT.md").write_text("report", encoding="utf-8")
    seq = [pp.ensure_copy(src2, dst2, strip_bookkeeping=True) for _ in range(3)]
    check("ensure_copy converges with nested bookkeeping stripped",
          seq == [True, False, False], seq)
    check("a nested bookkeeping file stays out of the copy",
          not (dst2 / "sub" / "REVISION_REPORT.md").exists()
          and (dst2 / "a.txt").is_file())

    # An inert `<area>.disabled/` is never copied; it must not force a rebuild.
    src3, dst3 = d / "src3", d / "dst3"
    src3.mkdir()
    (src3 / "a.txt").write_text("a", encoding="utf-8")
    (src3 / "raw_data.disabled").mkdir()
    (src3 / "raw_data.disabled" / "x.txt").write_text("x", encoding="utf-8")
    seq = [pp.ensure_copy(src3, dst3) for _ in range(3)]
    check("ensure_copy converges with an inert disabled area",
          seq == [True, False, False], seq)
    check("a disabled evidence area stays out of the copy",
          not (dst3 / "raw_data.disabled").exists())

    # F023: a Markdown ATX heading is a counting boundary.
    lines = ["# Abstract", "Short abstract.", "## Introduction", "Alpha beta.",
             "## Methods", "method words one two three four", "## Results", "Gamma delta."]
    rows = pp._length_rows_for_lines(lines, "x.md")
    main = next((r["words"] for r in rows if r["section"] == "main text"), None)
    check("M19 sees ## Methods as an excluded heading", main == 4, str(rows))

    # F024: a positive scientific notation does not match the U+2212 value.
    eo = load("stage_eo", WS / "paper-skills/paper-review/scripts/extract_occurrences.py")
    positive = eo.variant_pattern("1500", "value")
    negative = eo.variant_pattern("0.0015", "value")
    check("a positive exponent does not match the opposite-sign spelling",
          positive.search("1.5 × 10^3") and not positive.search("1.5 × 10^−3"))
    check("a negative exponent still matches the U+2212 spelling",
          negative.search("1.5 × 10^−3") and negative.search("1.5 × 10−3"))

    # F029: a root's frozen copy shadows the shipped profile without an error.
    r = scratch("stage_profiles_")
    shutil.copytree(WS / "venue_profiles", r / "venue_profiles")
    profs = pp.available_venue_profiles(r)
    check("a post-setup root's profiles are not reported as duplicates",
          not any(v.get("error") or "#duplicate" in k for k, v in profs.items()),
          str([k for k, v in profs.items() if v.get("error")]))
    # F034: resolution follows the file name, not the internal id.
    (r / "venue_profiles" / "my-venue.json").write_text(json.dumps(
        {**json.loads((WS / "venue_profiles" / "generic.json").read_text(
            encoding="utf-8")), "id": "other"}), encoding="utf-8")
    try:
        pp.load_venue_profile("other", root=r)
        internal_ok = False
    except pp.VenueProfileError:
        internal_ok = True
    check("a mismatched internal id does not resolve", internal_ok)
    check("the file-name id still resolves", pp.load_venue_profile("my-venue", root=r) is not None)

    # F042/F056: a mid-table dash row is data; a new header starts a new table.
    one = ("| finding | disposition |\n|---|---|\n| F1 | OK |\n"
           "| - | - |\n| F2 | OK |\n")
    check("a mid-table dash row keeps its identity",
          ("-",) in pp._repair_table_rows(one), str(pp._repair_table_rows(one)))
    two = ("| finding | resolution |\n|---|---|\n| F1 | OK |\n\n"
           "| item | evidence |\n|---|---|\n| C1 | raw text |\n")
    check("a second table uses its own header",
          ("C1", "raw text") in pp._repair_table_rows(two), str(pp._repair_table_rows(two)))

    # F048: a list citation names every item, but a comma after a SINGULAR
    # keyword followed by a count is not a list.
    check("a figure list names every cited label",
          pp._pkg4_cited_labels("2, 4 and S2") == ["2", "4", "s2"])
    check("a figure range expands",
          pp._pkg4_cited_labels("2-4") == ["2", "3", "4"])
    check("'Fig. 2, 3 clusters' cites Figure 2 only",
          pp._pkg4_cited_labels("2, 3", plural=False) == ["2"])
    check("'Figures 2, 4' cites both",
          pp._pkg4_cited_labels("2, 4", plural=True) == ["2", "4"])
    check("a thousands grouping is not a figure label",
          [m.group(0) for m in pp.PKG4_FIGURE_CITE_RE.finditer("Figure 2 and 3,000 cells")]
          == ["Figure 2"])

    # F050: the pooled-table CAPTION READER reads both forms. (The helper alone
    # always did; the defect was the call site that passed only "captionof".)
    cap = d / "pooled.tex"
    cap.write_text(r"Results. \caption{A pooled table} \captionof{table}{Also pooled.}",
                   encoding="utf-8")
    quoted = pp._pooled_table_caption(cap)
    check("the standard caption command is read too",
          "A pooled table" in quoted and "Also pooled." in quoted, quoted)

    # F140: a number word is a fact only when it is a COUNT.
    check("'one of the scripts' is not a numeric fact",
          not pp.sentence_carries_scientific_fact(
              "One of the scripts is one of the deposited files in code/."))
    check("'Twelve donors were excluded' is a numeric fact",
          pp.sentence_carries_scientific_fact("Twelve donors were excluded."))

    # F062: a malformed structured output reaches the scoped repair.
    f = d / "bad.json"
    f.write_text('{"a": [1, 2', encoding="utf-8")
    msg = pp._structured_problem_for("revised/revision_report.json", f)
    check("a malformed JSON message is a repairable structured problem",
          msg and any(re.search(p, msg) for p in pp.REPAIR_STRUCTURED_PATTERNS), str(msg))

    # F064: a tab before a field result shifts no protected offset.
    para = ('<w:p><w:r><w:t>A</w:t></w:r><w:r><w:tab/></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>[1]</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    text = fmt.text_of(para)
    ranges = fmt.field_result_text_ranges(para)
    check("field-result offsets count the preceding tab",
          [text[s:e] for s, e in ranges] == ["[1]"], str((text, ranges)))

    # F082: page PNGs sort numerically and are matched literally.
    pdir = scratch("stage_pages_")
    for name in ("Papers[1]-1.png", "Papers[1]-2.png", "Papers[1]-10.png", "other-1.png"):
        (pdir / name).write_bytes(b"x")
    check("page images sort by page number and literal stem",
          pp._page_png_names(pdir, "Papers[1]")
          == ["Papers[1]-1.png", "Papers[1]-2.png", "Papers[1]-10.png"])

    # F087: a bad --policy is a clean exit 2.
    proc = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), "scan",
                           str(WS), "--policy", str(d / "nope.json")],
                          cwd=str(WS), text=True, capture_output=True)
    check("a missing --policy file exits 2 without a traceback",
          proc.returncode == 2 and "Traceback" not in proc.stderr, proc.stderr[-200:])

    # F101/F140: data 12 and spelled-out counts are facts.
    check("'data 12' is a count, not a label",
          pp.sentence_carries_scientific_fact("We excluded data 12 because x."))
    check("a spelled-out count is a fact",
          pp.sentence_carries_scientific_fact("Twelve donors were excluded."))
    check("'Data S2' is still a label",
          not pp.sentence_carries_scientific_fact("See Data S2."))

    # F102/F137: four-digit citations, no decimal reference entries.
    check("a 1000-number citation cluster is visible",
          ec.NUM_CIT_RE.findall("[8-1000]") == ["8-1000"])
    check("a decimal is not a reference entry",
          ec.REF_ENTRY_RE.match("1.5 million reads") is None
          and ec.REF_ENTRY_RE.match("[1]Smith J.") is not None)

    # F105: a bare Keywords heading does not resume an excluded section.
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(
        "stage_cw2", str(WS / "paper-skills/paper-review/scripts/count_words.py"))
    cw2 = _ilu.module_from_spec(spec)
    sys.modules["stage_cw2"] = cw2
    spec.loader.exec_module(cw2)
    kw = ("Abstract\nShort abstract.\n\nIntroduction\nAlpha beta.\n\nMethods\n"
          "Methods words here today.\n\nKeywords\ncell, assay, beta\n\nResults\nGamma delta.\n")
    kmain = next(w for s, w, _n in cw2.sections(kw) if s == "main text")
    check("a Keywords heading does not put Methods back in the count", kmain == 4, kmain)

    # F113: docxcompare refuses a non-docx output before Word is needed.
    a, b = d / "a.docx", d / "b.docx"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    shell = subprocess.run(["bash", str(WS / "docxcompare.sh"), str(a), str(b),
                            str(d / "out.pdf")], cwd=str(WS), text=True, capture_output=True)
    check("docxcompare refuses a non-docx output", shell.returncode == 2
          and "output must be a .docx" in shell.stderr, shell.stderr[-200:])

    # F120: a subjectless LLM row does not merge into one of two subjects.
    mech = [{"kind": "claim_inversion", "member": "a1", "opponent": "a2",
             "judges": ["j1"], "subject": "claim:alpha", "summary": "alpha",
             "severity": "minor"},
            {"kind": "claim_inversion", "member": "a1", "opponent": "a2",
             "judges": ["j1"], "subject": "claim:beta", "summary": "beta",
             "severity": "minor"}]
    llm = [{"kind": "claim_inversion", "member": "a1", "opponent": "a2",
            "judges": ["j1"], "summary": "a longer beta summary", "severity": "blocker"}]
    merged = pp._merge_judge_conflicts(mech, llm)
    check("a subjectless LLM row does not overwrite one of two subjects",
          len(merged) == 3 and all(m["severity"] == "minor" for m in merged
                                   if m.get("subject")), str(merged))

    # F123/F124: thin-space thousands and the U+2212 exponent are one number.
    check("a thin-space thousands separator is one number",
          fmt.NUMBER_RE.findall("12\u2009000") == ["12\u2009000"]
          and fmt._cell_number("12\u2009000") == 12000)
    check("a U+2212 exponent is one number",
          fmt.NUMBER_RE.findall("1.2e\u22124") == ["1.2e\u22124"]
          and fmt._cell_number("1.2e\u22124") == 0.00012)

    # F127/F128/F138: named exclusions, & heading, base+margin wording.
    prof = pp.default_venue_profile()
    rule = pp.length_rule_text(prof)
    check("the length prompt prints the base and the margin",
          "base 150 +10% = 165" in rule and "base 3000 +25% = 3750" in rule, rule[:400])
    check("table captions are a named counting kind",
          any(k == "table-captions" for k, _l in pp._NAMED_COUNTING_KINDS))
    check("Materials & Methods enters methods mode",
          fmt.section_kinds(["Materials & Methods", "Body."], [True, False])
          == ["heading", "methods"])

    # F008: a DOCX never writes over the LaTeX render of the same stem.
    pout = scratch("stage_pdfs_")
    (pout / "main.pdf").write_bytes(b"x")
    check("a colliding DOCX render gets its own path",
          pp._docx_pdf_target(pout, "main", {(pout / "main.pdf").resolve()}).name
          == "main-docx.pdf")

    # F132: the root copy set includes skills and the render shims.
    frozen = scratch("stage_frozen_")
    copied = pp.copy_asset_dirs(WS, frozen)
    # setup copies the shims beside the driver; do the same here so the
    # manifest records real files (the copy-set itself is checked above).
    for shim in ("docx2pdf.sh", "docxcompare.sh"):
        shutil.copy2(WS / shim, frozen / shim)
    manifest = pp.module_manifest(frozen)
    check("setup's copy set carries paper-skills",
          "paper-skills" in copied and (frozen / "paper-skills").is_dir(), str(copied))
    check("the module manifest records paper-skills and both shims",
          manifest.get("paper-skills") and manifest.get("docx2pdf.sh")
          and manifest.get("docxcompare.sh"), str(sorted(manifest)))

    # K: a moved-aside DOCX render must not land on another DOCX's own name.
    pdfdir = scratch("stage_pdfname_")
    latex = {(pdfdir / "main.pdf").resolve()}
    defaults = {(pdfdir / "main.pdf").resolve(), (pdfdir / "main-docx.pdf").resolve()}
    check("a moved-aside DOCX render avoids another DOCX's own name",
          pp._docx_pdf_target(pdfdir, "main", latex, defaults, set()).name
          == "main-docx-2.pdf", pp._docx_pdf_target(pdfdir, "main", latex, defaults, set()).name)


# ---------------------------------------------------------------- stage-review fixes
def test_review_regressions():
    print("\n== regressions found in the change-set review ==")
    # F105 parity: the pipeline's M19 scan and the review skill must agree on a
    # bare Keywords heading (it is a boundary and never resumes an excluded
    # section).
    kw = ("Abstract\nShort abstract.\n\nIntroduction\nAlpha beta.\n\nMethods\n"
          "Methods words here today.\n\nKeywords\ncell, assay, beta\n\nResults\nGamma delta.\n")
    kmain = next(w for s, w, _n in cw.sections(kw) if s == "main text")
    pmain = next(r["words"] for r in pp._length_rows_for_lines(kw.split("\n"), "x.md")
                 if r["section"] == "main text")
    check("the M19 scan and count_words agree after a Keywords heading",
          kmain == pmain == 4, f"count_words={kmain} pipeline={pmain}")

    # F105 raw-profile fallback mirrors the normalizer: an id-less FIRST type is
    # still the default, so its cover-letter block is inherited.
    wd = scratch("stage_cover_")
    prof = wd / "mixed.json"
    prof.write_text(json.dumps({"article_types": [
        {"label": "Research Article",
         "length_limits": {"cover_letter": {"min": 200, "max": 400}}},
        {"id": "brief", "length_limits": {}}]}), encoding="utf-8")
    cover = wd / "cover.txt"
    cover.write_text("Dear editor, we submit this manuscript for your consideration please.\n",
                     encoding="utf-8")
    proc = subprocess.run([sys.executable,
                           str(WS / "paper-skills/paper-review/scripts/count_words.py"),
                           str(cover), "--section", "cover-letter",
                           "--venue-profile", str(prof)],
                          cwd=str(WS), text=True, capture_output=True)
    check("an id-less first article type supplies the cover-letter rule",
          proc.returncode == 0 and "200-400" in proc.stdout and "300-500" not in proc.stdout,
          proc.stdout[-300:])

    # F102: a bracketed publication year/range is prose, not a numeric call-out;
    # a genuine four-digit reference still counts.
    work = scratch("stage_cites_")
    (work / "corpus").mkdir()
    (work / "corpus" / "ms.md.txt").write_text(
        "We searched the literature [2015-2020] and the guideline [2020].\n"
        "As shown previously [1,2], the effect is real [3].\n"
        "References\n\n1. Smith J. Nature 2019.\n2. Doe A. Science 2020.\n"
        "3. Roe B. Cell 2021.\n", encoding="utf-8")
    cite_out = work / "out"
    cite_out.mkdir()
    proc = subprocess.run([sys.executable,
                           str(WS / "paper-skills/paper-review/scripts/extract_citations.py"),
                           "--work", str(work), "--out", str(cite_out)],
                          cwd=str(WS), text=True, capture_output=True)
    try:
        cit = json.loads((cite_out / "artifacts" / "M2_citations.json").read_text())
    except (OSError, ValueError):
        cit = {}
    check("bracketed years are not phantom citations",
          proc.returncode == 0 and cit.get("orphan_callouts") == []
          and cit.get("order_violations") == [], proc.stderr[-300:])

    # F066/F005: an `llm` review consumes the feedback ledger, so the feedback
    # run is an upstream dependency (a pending one must defer, not crash).
    class LlmCtx:
        cfg = {"revision_mode": "llm"}

    class ContinueCtx:
        cfg = {}

    check("an llm review depends on its feedback run",
          pp.rid_feedback(1) in pp.upstream_deps({"kind": "review", "round": 1}, LlmCtx()))
    check("a continue review has no feedback dependency",
          pp.rid_feedback(1) not in pp.upstream_deps(
              {"kind": "review", "round": 1}, ContinueCtx()))

    # F004: a GENERAL (non-scoped) revise arm still freshness-checks its review
    # copy; the scoped-only branch had silently dropped that check.
    root = scratch("stage_fresh_")
    sb = root / "runs" / "r1_revise1"
    upstream = root / "runs" / "r1_review"
    (sb / "review").mkdir(parents=True)
    (upstream / "review").mkdir(parents=True)
    (sb / "review" / "a.json").write_text("new", encoding="utf-8")
    (upstream / "review" / "a.json").write_text("old", encoding="utf-8")
    revise_rec = {"kind": "revise", "round": 1}

    class FreshCtx:
        cfg = {}
        source_manifest = {}

        def run(self, rid):
            return {"status": "done"} if rid == pp.rid_review(1) else None

        def sandbox_of(self, rec):
            return sb if rec is revise_rec else upstream

    probs = pp._input_freshness_problems(FreshCtx(), revise_rec)
    check("a general revise arm is stale when its review copy changed",
          any("no longer matches" in p for p in probs), str(probs))

    # F057: a DECLARED re-wrap is exempt from the old paragraph-boundary check,
    # but its OUTPUT must still keep the source paragraph's superscripts.
    def sup_docx(path, merged, with_sup):
        rpr = ('<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>' if with_sup else "")
        tail = ('<w:r><w:t xml:space="preserve"> for their time.</w:t></w:r>'
                if merged else "")
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
               '2006/main"><w:body><w:p>'
               '<w:r><w:t xml:space="preserve">We thank the reviewers</w:t></w:r>'
               f'<w:r>{rpr}<w:t>1</w:t></w:r>' + tail + '</w:p><w:sectPr/></w:body></w:document>')
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
            z.writestr("word/document.xml", xml)

    sup = scratch("stage_sup_")
    ssrc, ssb = sup / "src", sup / "sb"
    ssrc.mkdir()
    (ssb / "out").mkdir(parents=True)
    sup_docx(ssrc / "main.docx", False, True)
    (ssb / "out" / "REPLACEMENT_LEDGER.md").write_text("```json\n" + json.dumps({
        "exceptions": [{"kind": "rewrap", "source": "We thank the reviewers1",
                        "output": "We thank the reviewers1 for their time.",
                        "reason": "a template row"}]}) + "\n```\n", encoding="utf-8")
    sup_docx(ssb / "out" / "main.docx", True, True)
    rep = pp.template_rewrite_postcheck(ssb, ssrc, {}, {})
    check("a compliant declared re-wrap passes the superscript gate",
          not [e for e in rep.get("errors", []) if "superscript" in e],
          str([e for e in rep.get("errors", []) if "superscript" in e]))
    sup_docx(ssb / "out" / "main.docx", True, False)
    rep = pp.template_rewrite_postcheck(ssb, ssrc, {}, {})
    check("a declared re-wrap that drops a superscript still fails",
          any("superscript" in e for e in rep.get("errors", [])),
          str(rep.get("errors", [])[:2]))

    # F132: the recorded skills digest is part of the manifest drift check.
    frozen = scratch("stage_skilldrift_")
    shutil.copy2(WS / "paper_pipeline.py", frozen / "paper_pipeline.py")
    (frozen / "paper-skills").mkdir()
    (frozen / "paper-skills" / "x.txt").write_text("x", encoding="utf-8")
    ctx = pp.Ctx(frozen)
    ctx.state = {"pipeline": {"modules": {"paper-skills": "0" * 64}}}
    st = pp.root_pipeline_staleness(ctx)
    check("a recorded paper-skills digest that no longer matches is detected",
          "paper-skills" in st["recorded_module_diffs"], str(st["recorded_module_diffs"]))


def test_step2_findings():
    print("\n== step-2 confirmed findings ==")
    # F031: an unknown article type must not make the VENUE look broken.
    vroot = scratch("stage_f031_")
    (vroot / "venue_profiles").mkdir()
    shutil.copy2(WS / "venue_profiles/generic.json",
                 vroot / "venue_profiles/generic.json")

    class VenueCtx:
        pass

    vctx = VenueCtx()
    vctx.root = vroot
    vctx.cfg = {"venue": "generic", "article_type": "typo"}
    vctx.state = {}
    _notes, probs = pp.venue_config_findings(vctx)
    check("an unknown article type names the set-article-type remedy",
          any("set-article-type" in p for p in probs)
          and not any("select another venue" in p for p in probs), str(probs))
    lines = pp.venue_status_lines(vctx)
    check("status keeps the venue resolved and names set-article-type",
          lines and "UNRESOLVED" not in lines[0] and any("set-article-type" in ln for ln in lines),
          str(lines[:2]))
    check("venue_summary points at set-article-type",
          "set-article-type" in pp.venue_summary(vctx))
    # ... and the advertised remedy must actually run on that same root.
    (vroot / "pipeline_config.json").write_text(
        json.dumps({"venue": "generic", "article_type": "typo"}), encoding="utf-8")
    (vroot / "state.json").write_text(json.dumps({
        "version": 3, "runs": {}, "rounds": {}, "pinned": [], "log": [],
        "source_manifest": {},
        "config": {"venue": "generic", "article_type": "typo"}}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "set-article-type",
         "--root", str(vroot), "--list"],
        cwd=str(WS), text=True, capture_output=True)
    check("the advertised set-article-type remedy runs on the broken-type root",
          proc.returncode == 0 and "Article types" in (proc.stdout + proc.stderr),
          f"rc={proc.returncode} out={(proc.stdout + proc.stderr)[-400:]!r}")

    # F049: the common one-line numbered entry is a reference; a numbered body
    # list is not, and a body item must not overwrite a genuine entry.
    refs = pp._numbered_reference_titles(
        ["References",
         "43. Nurk, S. et al. The complete sequence. Science 372, 984 (2021)."])
    check("a one-line numbered reference entry is read", refs.get(43, "").startswith("Nurk, S."),
          str(refs))
    check("a numbered body list is not read as a bibliography",
          pp._numbered_reference_titles(["1. Do the first thing carefully."]) == {})
    check("a one-line entry outside a references section is not a reference",
          pp._numbered_reference_titles(
              ["43. Nurk, S. et al. Science 372, 984 (2021)."]) == {})
    check("a body list item cannot overwrite the real entry",
          pp._numbered_reference_titles(
              ["1. Cells were cultured at 37 C (2022).", "References",
               "1. Nurk, S. et al. Science 372, 984 (2021).",
               "1. Genome assembly was performed with Flye (2023)."]).get(1, "")
          .startswith("Nurk, S."),
          str(pp._numbered_reference_titles(
              ["1. Cells were cultured at 37 C (2022).", "References",
               "1. Nurk, S. et al. Science 372, 984 (2021).",
               "1. Genome assembly was performed with Flye (2023)."])))

    # F051: publication reports the stage's own PKG-2 record (it never removes
    # a reference itself), and cites the artifact that really exists.
    froot = scratch("stage_f051_")
    fsb = froot / "runs" / "r1_a2_revise"
    fsb.mkdir(parents=True)
    strip = {"label": "r1_a2_revise", "removed": 2, "removed_links": 1,
             "files": [{"file": "main.md", "removed": ["the code/ pointer"]}],
             "remaining": [{"rule": "PKG-2", "file": "notes.json", "line": 1,
                            "reference": "code/a.py"}]}
    (fsb / "PKG2_r1_a2_revise.json").write_text(json.dumps(strip), encoding="utf-8")

    class ReportCtx:
        def __init__(self):
            self.root = froot
            self.reports_dir = froot / "reports"
            self.reports_dir.mkdir()

        def run(self, rid):
            return ({"id": "r1_a2_revise", "status": "done"}
                    if rid == pp.rid_for_fresh(1, "a2") else None)

        def sandbox_of(self, rec):
            return fsb

    got = pp._stage_dangling_report(ReportCtx(), {"stored": {"champion": "a2", "round": 1}})
    check("the champion stage's PKG-2 record is found",
          got and got.get("removed") == 2
          and str(got.get("artifact", "")).endswith("PKG2_r1_a2_revise.json"), str(got))
    rctx = pp.Ctx(froot)
    rctx.cfg = {}
    readme = pp.final_clean_readme_text(
        rctx, {"certified": True, "exit_code": 0},
        {"pin": {"id": "r1_a2", "digest": "0" * 64},
         "stored": {"champion": "a2", "round": 1}},
        {"hygiene": {"removed_dangling_references": got}, "files": 3,
         "digest": "1" * 64})
    check("the readme cites the real stage artifact, not a never-written PKG2 name",
          "PKG2_r1_a2_revise.json" in readme and "PKG2_final_clean" not in readme,
          readme[-500:])
    # A post-pin journal-submission report describes a DERIVED copy, never the
    # champion's published bytes: it must not be reported as the stage repair.
    (froot / "reports" / "PKG2_journal_submission.json").write_text(
        json.dumps({"label": "journal submission", "removed": 3, "files": []}),
        encoding="utf-8")

    class BaseChampionCtx:
        def __init__(self):
            self.root = froot
            self.reports_dir = froot / "reports"

        def run(self, rid):
            return {"id": "r1_a1", "status": "done"} if rid == pp.rid_a1(1) else None

        def sandbox_of(self, rec):
            return froot / "runs" / "r1_a1"

    check("a post-pin journal record is not the champion's repair",
          pp._stage_dangling_report(BaseChampionCtx(),
                                    {"stored": {"champion": "a1", "round": 1}}) is None)

    # F066: read-only roles never get the producer's add/edit/delete contract.
    for role in ("review", "judge"):
        block = pp.zotero_cli_block(role, "read")
        check(f"{role} does not authorize citation-field edits",
              "You may ADD" not in block and "this session is READ-ONLY" in block)
    rw = pp.zotero_cli_block("rewrite", "read")
    check("rewrite preserves fields without authorizing edits",
          "You may ADD" not in rw and "REWRITES FORM, not content" in rw)
    check("the edit stage keeps the producer field rule",
          "You may ADD" in pp.zotero_cli_block("edit", "edit"))

    # F067/F068: a letter-type template is a MANUSCRIPT template; a cover .tex
    # is a cover, never the LaTeX sample.
    tdir = scratch("stage_678_")
    vid = "testvenue"
    (tdir / f"{vid}.json").write_text(json.dumps({
        "id": vid, "label": "Test Venue",
        "default_article_type": "article",
        "article_types": [{"id": "article", "label": "Article"},
                          {"id": "letter-to-the-editor",
                           "label": "Letter to the Editor"}]}), encoding="utf-8")
    off = tdir / f"{vid}.official"
    off.mkdir()
    for name in ("Main_Template.docx", "Letter_to_the_Editor.docx"):
        (off / name).write_bytes(b"PK\x03\x04")
    (off / "Cover_Letter.tex").write_text("\\section{Dear editor}\n", encoding="utf-8")
    (off / "Letter_to_the_Editor.tex").write_text(
        "\\documentclass{article}\n\\section{Introduction}\n", encoding="utf-8")
    tres = pp.official_template_files(vid, profiles_dir=tdir,
                                      manuscript_names=["letter to the editor"])
    check("a letter-type template is the manuscript main, not a cover",
          Path(tres["word"].get("main", "")).name == "Main_Template.docx"
          and not tres["word"].get("cover"),
          str({k: v.name for k, v in tres["word"].items()}))
    check("a cover-letter .tex is its own role, not the LaTeX sample",
          Path(tres["latex"].get("cover", "")).name == "Cover_Letter.tex"
          and Path(tres["latex"].get("sample", "")).name == "Letter_to_the_Editor.tex",
          str({k: (v.name if isinstance(v, Path) else v) for k, v in tres["latex"].items()}))
    pack = pp.build_venue_templates(vid, profiles_dir=tdir)
    check("the pack builder skips a .tex cover-letter template",
          any(s.get("file") == "Cover_Letter.tex" for s in pack.get("skipped") or []),
          str(pack.get("skipped"))[:300])
    check("a letter-type template is not parsed into the venue-wide skeleton",
          any(s.get("file") == "Letter_to_the_Editor.docx"
              and "cover-letter template" in str(s.get("why") or "")
              for s in pack.get("skipped") or []),
          str(pack.get("skipped"))[:400])

    # F076: every manuscript scan uses the no-symlink corpus walker.
    sdir = scratch("stage_076_")
    (sdir / "main.md").write_text("# Introduction\n\nWe used 12 samples.\n", encoding="utf-8")
    (sdir / "other.md").write_text(
        "# Introduction\n\nWe used 99 samples. [AUTHOR TO COMPLETE: x]\n", encoding="utf-8")
    (sdir / "main.tsv").write_text("method\tn\nx\t1\n", encoding="utf-8")
    (sdir / "other.tsv").write_text("method\tn\ny\t2\n", encoding="utf-8")
    (sdir / "linked.md").symlink_to(sdir / "other.md")
    (sdir / "linked.tsv").symlink_to(sdir / "other.tsv")
    docs = pp.collect_documents([(sdir, "", ())])
    check("collect_documents refuses a file symlink", "linked.md" not in docs, str(sorted(docs)))
    lengths = pp.scan_lengths_in_sources([(sdir, "", ())])
    check("the M19 scan refuses a file symlink",
          "linked.md" not in (lengths.get("documents") or []),
          str(lengths.get("documents") or []))
    tables = [rel for rel, _text in pp.data_table_texts([(sdir, "", ())])]
    check("data_table_texts refuses a file symlink", "linked.tsv" not in tables, str(tables))
    ph = pp.scan_placeholders_in_sources([(sdir, "", ())])
    check("the M6 placeholder scan refuses a file symlink",
          ph.get("files") == ["other.md"], str(ph.get("files")))

    # F077: stale-lock reclaim also works on a no-hardlink filesystem.
    lroot = scratch("stage_077_")
    lctx = pp.Ctx(lroot)
    lock = lroot / "paper_pipeline.lock"
    staged = lroot / "stage.tmp"
    new_info = {"pid": os.getpid(), "what": "test", "since": "now"}
    staged.write_text(json.dumps(new_info), encoding="utf-8")
    lock.write_text(json.dumps({"pid": 99999999, "what": "dead", "since": "then"}),
                    encoding="utf-8")
    real_link = pp.os.link

    def no_hardlink(*_a, **_k):
        raise OSError(1, "no hardlinks")

    try:
        pp.os.link = no_hardlink
        got_lock = lctx._claim_lock(lock, staged, new_info, "test")
    finally:
        pp.os.link = real_link
    check("a stale lock is reclaimed on a no-hardlink filesystem",
          got_lock and json.loads(lock.read_text())["what"] == "test", str(got_lock))

    # F078: the operator's proxy cap is never called the venue's own limit.
    example = pp.load_venue_profile("example-journal")
    check("the venue's own published cap keeps the venue wording",
          "venue's own limit" in pp.caption_rule_text(250, example))
    over = pp.caption_rule_text(300, example)
    check("an operator override is named as the operator's proxy",
          "venue's own limit" not in over and "OPERATOR" in over and "250" in over,
          over[:300])
    disabled = pp.caption_rule_text(0, example)
    check("a disabled cap on a publishing venue says DISABLED, not unpublished",
          "DISABLED" in disabled and "is not published" not in disabled
          and "250" in disabled, disabled[:300])
    # The ASSEMBLED review prompt must agree with the caption rule: the M18
    # directive may not claim the venue publishes no limit while the venue's
    # published number is in the same prompt.
    rprompt = pp.review_prompt(scratch("stage_m18prompt_"), "r1_review", 1,
                               caption_limit=0, venue=example)
    check("the assembled M18 directive does not call a published limit unpublished",
          "publishes no per-type legend limit" not in rprompt
          and "publishes a figure-legend limit of 250 words" in rprompt,
          rprompt[:400])

    # F083: a latexmk timeout kills the whole compiler process group.
    ldir = scratch("stage_083_")
    bindir = ldir / "bin"
    bindir.mkdir()
    fake = bindir / "latexmk"
    fake.write_text("#!/bin/sh\necho $$ > \"$FAKE_PIDS\"\nsleep 60 &\n"
                    "echo $! >> \"$FAKE_PIDS\"\nsleep 60\n", encoding="utf-8")
    fake.chmod(0o755)
    lpkg = ldir / "pkg"
    lpkg.mkdir()
    (lpkg / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    pids_file = ldir / "pids.txt"
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(bindir) + os.pathsep + old_path
    os.environ["FAKE_PIDS"] = str(pids_file)
    try:
        res = pp.compile_latex_pdf(lpkg, "main.tex", ldir / "out.pdf", timeout=1)
    finally:
        os.environ["PATH"] = old_path
        os.environ.pop("FAKE_PIDS", None)
    timeout_pids = []
    if pids_file.is_file():
        timeout_pids = [int(x) for x in pids_file.read_text().split()]
    alive = []
    for pid in timeout_pids:
        try:
            os.kill(pid, 0)
            alive.append(pid)
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        except OSError:
            pass
    check("a latexmk timeout returns a structured error", res.get("ok") is False, str(res)[:200])
    check("a latexmk timeout kills the compiler child too",
          len(timeout_pids) >= 2 and not alive, f"pids={timeout_pids} alive={alive}")

    # F109: role-word filters are not substrings.
    scripts = {
        "extract_numbers": (lambda m, p: m.is_non_manuscript(p)),
        "extract_citations": (lambda m, p: m.is_non_manuscript(p)),
        "extract_occurrences": (lambda m, p: m.is_non_manuscript(p)),
        "enumerate_conventions": (lambda m, p: m._non_manuscript(p)),
        "extract_acronyms": (lambda m, p: m.is_evidence_name(p)),
        "count_words": (lambda m, p: m.is_evidence_path(p)),
    }
    manuscripts = ["dose_response.txt", "immune_response.md.txt",
                   "biofeedback_results.txt", "feedback_loop.md",
                   "response_surface.md", "letter_to_the_editor.docx",
                   "letter_to_the_editor.docx.txt", "editorial.tex.txt"]
    replies = ["response_to_reviewers.docx", "responses_to_reviewers.txt",
               "reviewer_feedback.txt", "FeedbackForm.docx", "feedbackreport.docx",
               "referees_report.docx.txt", "editor_decision.pdf"]
    for name, pred in scripts.items():
        mod = load(f"stage_f109_{name}",
                   WS / "paper-skills" / "paper-review" / "scripts" / f"{name}.py")
        check(f"{name} keeps real manuscripts named like a role word",
              not any(pred(mod, p) for p in manuscripts),
              str([p for p in manuscripts if pred(mod, p)]))
        check(f"{name} still drops a real response/feedback file",
              all(pred(mod, p) for p in replies),
              str([p for p in replies if not pred(mod, p)]))


def main() -> int:
    try:
        test_f001_view_layout_collision()
        test_docx_layout()
        test_docx_cli_rules()
        test_pipeline_text()
        test_tables_and_stats()
        test_pipeline_corpus()
        test_extract_numbers()
        test_node_keys()
        test_more_fixes()
        test_review_regressions()
        test_step2_findings()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} failed")
        for name in FAILS:
            print(f"  FAILED: {name}")
        return 1
    print("ALL 2026-10-25 STAGE FIX-BUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

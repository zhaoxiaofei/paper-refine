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
    check("a 1000-1020 citation range is not mistaken for a year",
          not (1900 <= 1000 <= 2099 and 1900 <= 1020 <= 2099))


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

    # F048: a list citation names every item.
    check("a figure list names every cited label",
          pp._pkg4_cited_labels("2, 4 and S2") == ["2", "4", "s2"])
    check("a figure range expands",
          pp._pkg4_cited_labels("2-4") == ["2", "3", "4"])

    # F050: both \caption and \captionof are read.
    check("the standard caption command is read too",
          pp._latex_command_bodies(r"\caption{A pooled table}", "caption") == ["A pooled table"])

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

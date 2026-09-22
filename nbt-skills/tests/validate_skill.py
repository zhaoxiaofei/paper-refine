#!/usr/bin/env python3
"""Regression harness for the nbt-review scripts (shipped with the package).

Covers the 24 script-level and 16 instruction-level checks from the v0.3 audit:
reference-list truncation, xlsx shared strings, percentage/AUC extraction,
acronym detectors, citation matching and bookkeeping, docx header/footer
coverage, RTF handling, occurrence-artifact naming, prompt/reference sync.

Usage:
  python3 tests/validate_skill.py --skill-root . --run-dir /tmp/nbt_validate

Prints one PASS/FAIL line per check plus a summary; exit status 1 if any fail.
Writes only inside --run-dir.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


# ---------------------------------------------------------------- fixtures
def docx(path, paras, header=None, footer=None):
    body = "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % p
                   for p in paras)
    doc = '<?xml version="1.0"?><w:document %s><w:body>%s</w:body></w:document>' % (W_NS, body)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)
        if header:
            z.writestr("word/header1.xml",
                       '<?xml version="1.0"?><w:hdr %s><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:hdr>'
                       % (W_NS, header))
        if footer:
            z.writestr("word/footer1.xml",
                       '<?xml version="1.0"?><w:ftr %s><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:ftr>'
                       % (W_NS, footer))
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0"?><cp:coreProperties'
                   ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
                   ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   '<dc:creator>Author One</dc:creator></cp:coreProperties>')
        z.writestr("[Content_Types].xml", "<Types/>")


def xlsx(path, sheets):
    """sheets: list of (name, [[cell, ...], ...]) with cell = ('s', text) | ('n', number)."""
    shared, index = [], {}
    for _name, rows in sheets:
        for row in rows:
            for kind, val in row:
                if kind == "s" and val not in index:
                    index[val] = len(shared)
                    shared.append(val)
    sst = ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           + "".join("<si><t>%s</t></si>" % s for s in shared) + "</sst>")
    wb_sheets, rels = [], []
    for i, (name, _rows) in enumerate(sheets, 1):
        wb_sheets.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (name, i, i))
        rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/'
                    '2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i))
    wb = ('<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
          ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets>%s</sheets></workbook>' % "".join(wb_sheets))
    relsxml = ('<?xml version="1.0"?><Relationships'
               ' xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
               % "".join(rels))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", relsxml)
        for i, (_name, rows) in enumerate(sheets, 1):
            cells = []
            for r, row in enumerate(rows, 1):
                cs = []
                for c, (kind, val) in enumerate(row):
                    ref = "%s%d" % (chr(ord("A") + c), r)
                    if kind == "s":
                        cs.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, index[val]))
                    else:
                        cs.append('<c r="%s"><v>%s</v></c>' % (ref, val))
                cells.append('<row r="%d">%s</row>' % (r, "".join(cs)))
            z.writestr("xl/worksheets/sheet%d.xml" % i,
                       '<?xml version="1.0"?><worksheet'
                       ' xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s'
                       '</sheetData></worksheet>' % "".join(cells))


def build_fixtures(base):
    sub = os.path.join(base, "sub")
    os.makedirs(sub, exist_ok=True)
    docx(os.path.join(sub, "manuscript.docx"), [
        "Title: Single-cell profiling of Treg biology",
        "Abstract",
        "We performed single-cell RNA sequencing (scRNA-seq) on 12 samples.",
        "Response was 62% and the AUC was 0.81.",
        "Results",
        "The treated cohort included n = 15 patients [1].",
        "Methods",
        "Cells were processed with the manufacturer protocol.",
        "References",
        "1. Smith J. Nature 2019;10:1-9.",
        "2. Doe A. Science 2020;11:20-30.",
        "3. Lee B. Cell 2018;9:5-15.",
        "Figure legends",
        "Fig. 1 | HLA-DR and FMO staining of Tregs. Error bars, s.e.m. n = 12 patients [2].",
    ], header="Corresponding author: jane.doe@uni.edu", footer="Page 1 of 9")
    xlsx(os.path.join(sub, "supp_tables.xlsx"), [("S1", [
        [("s", "Sample"), ("s", "count")],
        [("s", "Cohort A"), ("n", "15")],
        [("s", "Cohort B"), ("n", "12")],
    ])])
    xlsx(os.path.join(sub, "wide11.xlsx"),
         [("S%d" % i, [[("s", "M%d" % i), ("n", str(i))]]) for i in range(1, 12)])
    with open(os.path.join(sub, "legacy.rtf"), "w", encoding="latin-1") as f:
        f.write(r"{\rtf1\ansi\deff0 {\fonttbl{\f0 Times;}}\fs20 Treg counts were 15. \par "
                r"Email: a\'40b.org \u8217? done \par}")
    open(os.path.join(sub, "empty.txt"), "w").close()
    with open(os.path.join(sub, "scan.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 broken\n")
    with open(os.path.join(sub, "cover_letter.md"), "w", encoding="utf-8") as f:
        f.write("# Cover letter\n\nDear Editor,\n\n"
                "See our previous work [5] and the assay described by Smith et al., 2019.\n")
    with open(os.path.join(sub, "main_text.md"), "w", encoding="utf-8") as f:
        f.write("Main text cites [1] and [2].\n\n"
                "References\n1. A. One. 2019.\n2. B. Two. 2020.\n3. C. Three. 2021.\n\n"
                "Figure legends\nFig. 2 | Design. Data from n = 9 patients [2].\n")
    with open(os.path.join(sub, "supp_notes.md"), "w", encoding="utf-8") as f:
        f.write("Supplementary Note 2\n\n"
                "In 2020, Smith reported a new method. Since 2015, the field has grown.\n"
                "The signal fell in the interval [2, 5] units.\n"
                "We used Lee et al. (2018) and the 95% CI 1.2-3.4 as reported [4].\n\n"
                "Reference list\n"
                "1. Foo C. Nature 2021;1:1-2.\n"
                "2. Bar D. Science 2022;2:3-4.\n")
    with open(os.path.join(sub, "acro_probe.md"), "w", encoding="utf-8") as f:
        f.write("Abstract\n"
                "Treg and Foxp3 and Nrf2 and Tregs were profiled by scRNA-seq/scATAC-seq.\n\n"
                "Results\n"
                "HLA-DR and IL-6 were measured.\n\n"
                "References\n"
                "1. A. One. 2019.\n\n"
                "Figure legends\n"
                "Fig. 3 | PD-1 and FMO gating.\n")
    # reading-order probe: the defining file sorts FIRST alphabetically but comes
    # LAST in reading order (Abstract precedes Methods)
    with open(os.path.join(sub, "01_methods.md"), "w", encoding="utf-8") as f:
        f.write("Methods\n\nCells were profiled by single-cell ATAC sequencing (scATAC-seq).\n")
    with open(os.path.join(sub, "zz_abstract.md"), "w", encoding="utf-8") as f:
        f.write("Abstract\n\nWe used scATAC-seq in this study.\n")
    # M1b probe: the acronym is introduced in the abstract and the main text
    # keeps spelling the term out -- the reported "never revised" error class.
    with open(os.path.join(sub, "m1b_probe.md"), "w", encoding="utf-8") as f:
        f.write("Abstract\n\nCopy-number (CN) alterations were common.\n\n"
                "Results\n\nWe scored copy-number burden per cell, then checked the "
                "copy-number gains.\n")
    print("fixtures in", sub)
    return sub


# ------------------------------------------------------------------ runner
def run(skill_root, script, *args):
    py = os.path.join(skill_root, "nbt-review", "scripts", script)
    p = subprocess.run([sys.executable, py] + list(args), capture_output=True, text=True)
    if p.returncode != 0:
        print("   !! %s exited %d: %s" % (script, p.returncode, (p.stdout + p.stderr).strip()[:300]))
    return p


def pipeline(skill_root, work, sub):
    run(skill_root, "convert_corpus.py", "--submission", sub, "--work", work)
    for script in ("extract_acronyms.py", "extract_citations.py", "extract_numbers.py"):
        run(skill_root, script, "--work", work, "--out", os.path.dirname(work))


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def jload(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("%-4s %-55s %s" % ("PASS" if ok else "FAIL", name, detail[:150]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-root", required=True)
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    root, run_dir = os.path.abspath(args.skill_root), os.path.abspath(args.run_dir)
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir)
    sub = build_fixtures(run_dir)
    work, out = os.path.join(run_dir, "review", "work"), os.path.join(run_dir, "review")
    pipeline(root, work, sub)
    corpus, art = os.path.join(work, "corpus"), os.path.join(out, "artifacts")
    inv = jload(os.path.join(work, "inventory.json"))
    inv_by_path = {e["path"]: e for e in inv} if isinstance(inv, list) else {}
    corpus_text = {os.path.basename(p): read(os.path.join(corpus, p))
                   for p in os.listdir(corpus)} if os.path.isdir(corpus) else {}
    m1_md = read(os.path.join(art, "M1_acronyms.md"))
    m1 = jload(os.path.join(art, "M1_acronyms.json"))
    m2 = jload(os.path.join(art, "M2_citations.json"))
    m4_md = read(os.path.join(art, "M4_numbers.md"))
    m1_rows = {r.get("acronym"): r for r in m1} if isinstance(m1, list) else {}
    call_raws = [c.get("raw", "") for c in m2.get("callouts", [])]

    x = corpus_text.get("supp_tables.xlsx.txt", "")
    check("C1 xlsx shared strings decoded",
          "Cohort A | 15" in x and "Sample | count" in x and "0 | 1" not in x,
          repr(x.splitlines()[:4]))
    check("C2 percentages enumerated (M4)",
          re.search(r"\|\s*percentage\s*\|\s*62\b", m4_md) is not None)
    check("C3 AUC 'was 0.81' enumerated (M4)",
          re.search(r"\|\s*AUC\s*\|\s*0\.81\b", m4_md) is not None)
    check("C4 n=12 legend after References reaches M4",
          re.search(r"\|\s*n\s*\|\s*12\b", m4_md) is not None)
    legend_line = next((i for i, ln in enumerate(corpus_text.get("main_text.md.txt", "").splitlines(), 1)
                        if "Fig. 2 |" in ln), -1)
    check("C5 [2] call-out in the post-References legend reaches M2",
          any(c.get("file", "").startswith("main_text") and c.get("line") == legend_line
              for c in m2.get("callouts", [])), "legend_line=%d" % legend_line)
    check("C6 FMO (legend after References) inventoried in M1",
          "FMO" in m1_rows, "tokens=%d" % len(m1_rows))
    missing = [t for t in ("Treg", "Foxp3", "Nrf2") if t not in m1_rows]
    check("C7 single-leading-capital tokens inventoried", not missing, "missing=%s" % missing)
    check("C8 'Smith et al., 2019' matched as call-out",
          any("Smith et al." in r and "2019" in r for r in call_raws))
    prose = [r for r in call_raws if re.match(r"^(In|Since)\b", r.strip())]
    check("C9 prose years ('In 2020','Since 2015') not call-outs", not prose, "bad=%s" % prose)
    check("C10 no cross-document order violations",
          not m2.get("order_violations"), "n=%d" % len(m2.get("order_violations") or []))
    check("C11 per-document reference lists not 'duplicates'",
          not m2.get("duplicate_entries"), "dups=%s" % m2.get("duplicate_entries"))
    supp_refs = [e for e in m2.get("ref_entries", []) if e.get("file", "").startswith("supp_notes")]
    bogus = [r for r in call_raws if re.match(r"^(Nature|Science|Cell)\b", r.strip())]
    check("C12 'Reference list' heading parsed, list not read as prose",
          len(supp_refs) >= 2 and not bogus and len(m2.get("ref_entries", [])) >= 5,
          "supp_refs=%d all_refs=%d bogus=%s" % (len(supp_refs), len(m2.get("ref_entries", [])), bogus))
    vf = os.path.join(run_dir, "variants.json")
    with open(vf, "w", encoding="utf-8") as f:
        json.dump({"canonical": "scRNA-seq", "variants": ["scRNAseq", "single-cell RNA-seq"]}, f)
    p = subprocess.run([sys.executable, os.path.join(root, "nbt-review", "scripts",
                        "extract_occurrences.py"), "--work", work, "--variants-file", vf],
                       capture_output=True, text=True)
    occ_md = [f for f in os.listdir(work) if f.startswith("occurrences_") and f.endswith(".md")]
    occ_text = "".join(read(os.path.join(work, f)) for f in occ_md)
    check("C13 --variants-file dict form accepted",
          p.returncode == 0 and "scRNAseq" in occ_text, "rc=%d" % p.returncode)
    vf_a = os.path.join(run_dir, "variants_a.json")
    vf_b = os.path.join(run_dir, "variants_b.json")
    with open(vf_a, "w", encoding="utf-8") as f:
        json.dump([{"canonical": "scRNA-seq", "variants": ["scRNAseq"]}], f)
    with open(vf_b, "w", encoding="utf-8") as f:
        json.dump([{"canonical": "scRNA-seq", "variants": ["scATAC-seq"]}], f)
    occ_script = os.path.join(root, "nbt-review", "scripts", "extract_occurrences.py")
    subprocess.run([sys.executable, occ_script, "--work", work, "--variants-file", vf_a],
                   capture_output=True, text=True)
    before = {f for f in os.listdir(work) if f.startswith("occurrences_")}
    subprocess.run([sys.executable, occ_script, "--work", work, "--variants-file", vf_b],
                   capture_output=True, text=True)
    after = {f for f in os.listdir(work) if f.startswith("occurrences_")}
    check("C22 two variant runs keep separate artifacts", len(after - before) >= 1,
          "before=%d after=%d" % (len(before), len(after)))
    docx_text = corpus_text.get("manuscript.docx.txt", "")
    notes = " ".join(inv_by_path.get("manuscript.docx", {}).get("notes", []))
    check("C14 docx header text extracted (and noted)",
          "jane.doe@uni.edu" in docx_text and "header" in notes.lower(),
          "notes=%s" % notes[:70])
    rtf = corpus_text.get("legacy.rtf.txt", "")
    check("C15 RTF rendered as text, not markup",
          "{\\rtf1" not in rtf and "Treg counts were 15" in rtf, repr(rtf[:80]))
    ctx = {r["acronym"]: r.get("first_occurrence_per_context", {}) for r in m1_rows.values()}
    fmo_ctx = " ".join((ctx.get("FMO") or {}).keys())
    scrna_ctx = " ".join((ctx.get("scRNA-seq") or {}).keys())
    check("C16 context detected inside a single file",
          "figure legend" in fmo_ctx and "abstract" in scrna_ctx,
          "FMO=%s scRNA-seq=%s" % (fmo_ctx, scrna_ctx))
    a1 = m1_rows.get("scATAC-seq", {})
    check("C17 first-use ordering follows reading order, not filename sort",
          a1.get("defined_at_first_use") == "defined-later",
          "scATAC-seq=%s files=%s" % (a1.get("defined_at_first_use"), a1.get("files")))
    check("C18 zero-byte file recorded in corpus",
          "(empty file)" in corpus_text.get("empty.txt.txt", ""),
          repr(corpus_text.get("empty.txt.txt", ""))[:40])
    pdf_notes = inv_by_path.get("scan.pdf", {}).get("notes", [])
    check("C19 unconvertible pdf carries an explanatory note", bool(pdf_notes), "notes=%s" % pdf_notes)
    wide = corpus_text.get("wide11.xlsx.txt", "")
    ok20 = True
    for i in range(1, 12):
        m = re.search(r"### sheet: S%d\s*\n(.{0,40})" % i, wide, re.S)
        if not m or ("M%d" % i) not in m.group(1):
            ok20 = False
    check("C20 11-sheet xlsx keeps sheet names aligned", ok20, wide.splitlines()[:4])
    split_row = m1_rows.get("scATAC-seq", {})
    check("C21 slash-separated acronyms split into two tokens",
          "acro_probe.md.txt" in (split_row.get("files") or []),
          "files=%s" % (split_row.get("files") or []))
    check("C23 CI listed as an EXEMPT row in M1",
          re.search(r"\|\s*CI\s*\|\s*EXEMPT", m1_md) is not None)
    interval_line = next((i for i, ln in enumerate(corpus_text.get("supp_notes.md.txt", "").splitlines(), 1)
                          if "interval [2, 5]" in ln), -1)
    interval_calls = [c for c in m2.get("callouts", [])
                      if c.get("file", "").startswith("supp_notes") and c.get("line") == interval_line]
    check("C24 interval [2, 5] not treated as a citation",
          not interval_calls and 2 not in m2.get("orphan_callouts", []),
          "calls=%s suspects=%d" % (interval_calls, len(m2.get("suspect_brackets", []))))
    cn_row = m1_rows.get("CN") or {}
    m1b_rows = [ln for ln in m1_md.split("## M1b", 1)[-1].splitlines()
                if ln.startswith("| CN |")]
    check("C25 M1b instance table lists long-form residue rows",
          "## M1b — LONG FORMS RE-USED AFTER THEIR FIRST USE" in m1_md
          and len(m1b_rows) == 1 and "m1b_probe.md.txt:7" in m1b_rows[0]
          and "copy-number" in m1b_rows[0],
          "rows=%s" % m1b_rows)
    check("C26 M1 rows carry the M1b columns and JSON fields",
          cn_row.get("long_form_after_first_use_total") == 1
          and cn_row.get("long_form_after_first_use", {}).get("main text") == ["m1b_probe.md.txt:7"]
          and cn_row.get("long_form_first_use", {}).get("abstract") == "m1b_probe.md.txt:3"
          and "copy-number" in (cn_row.get("long_form_variants_seen") or [])
          and isinstance(cn_row.get("short_form_uses"), dict)
          and isinstance(cn_row.get("long_form_repeat_notes"), dict)
          and "long form after first use (n)" in m1_md,
          "cn=%s" % {k: cn_row.get(k) for k in ("long_form_after_first_use_total",
                                                "long_form_first_use")})

    readme = read(os.path.join(root, "README.md"))
    rev_skill = read(os.path.join(root, "nbt-revise", "SKILL.md"))
    rev_rules = read(os.path.join(root, "nbt-revise", "references", "edit_rules.md"))
    ledger = read(os.path.join(root, "nbt-revise", "references", "ledger.md"))
    sweeps = read(os.path.join(root, "nbt-review", "references", "sweeps.md"))
    rev_sk = read(os.path.join(root, "nbt-review", "SKILL.md"))
    check("D1 README has no dead skill paths",
          "~/.codex/skills/nbt-review" not in readme and "~/.codex/skills/nbt-revise" not in readme)
    check("D2 README drops the missing eval-HTML promise",
          "eval-review-iteration-1.html" not in readme)
    check("D3 nbt-revise acceptance does not say A1–A8",
          "A1–A8" not in rev_skill and "A1–A9" in rev_skill)
    check("D4 ledger defines V1/V4 artifacts",
          "checksums_after" in ledger and "roundtrip" in ledger.lower())
    _rr = " ".join(rev_rules.lower().split())          # wrap-insensitive
    check("D5 Zotero rule allows guarded citation edits and forbids uncontrolled "
          "library writes",
          "correct the underlying" not in _rr
          and "explicit" in _rr and "propose-then-verify" in _rr
          and "last-modified auto" in _rr and "never create or delete" in _rr)
    check("D6 tracked-changes fallback has a distinct name",
          "before-after" in rev_rules or "before-after" in readme)
    check("D7 M4 purpose text repaired", "wait," not in sweeps)
    check("D8 M1(h) consistent with format flexibility",
          "flag every non-exempt acronym appearing in abstract/title" not in sweeps)
    check("D9 review skill documents occurrence artifact location", "occurrences_" in rev_sk)
    check("D11 growth loop has a read-only fallback", "skill directory is read-only" in rev_sk)
    check("D12 README states which sweeps are script-backed", "shipped scripts" in readme)
    check("D13 README carries a package version + duplicate warning",
          "Package version" in readme and "duplicate" in readme.lower())
    check("D14 review skill guards OUT vs SUBMISSION_DIR", "outside SUBMISSION_DIR" in rev_sk)
    check("D15 all extractors know the 'Reference list' heading",
          all("reference\\s+list" in read(os.path.join(root, "nbt-review", "scripts", s))
              for s in ("extract_acronyms.py", "extract_citations.py", "extract_numbers.py")))
    _sw = " ".join(sweeps.split())
    check("D16 the length rule (M19) replaced the blanket exemption",
          "never flag abstract/main-text word limits" not in " ".join(rev_sk.split())
          and "never shorten text to meet abstract/main-text word limits"
          not in " ".join(rev_skill.split())
          and "## M19 —" in sweeps and "172" in _sw and "3,750" in _sw
          and "state-of-the-art" in _sw)
    _cw_path = os.path.join(root, "nbt-review", "scripts", "count_words.py")
    _cw = read(_cw_path) if os.path.isfile(_cw_path) else ""
    check("D17 count_words.py ships the deterministic counting rule",
          "\\S+" in _cw and "state-of-the-art" in _cw and "lenient_cap" in _cw)
    _sw2 = " ".join(sweeps.split()).lower()
    _cw2 = " ".join(_cw.split()).lower()
    check("D21 M18 always enumerates legends and M19 carries the cover-letter preference",
          "always enumerated" in _sw2 and "no cover-letter word limit" in _sw2
          and "300-500" in _sw2 and "persuading part" in _sw2
          and "cover-letter" in _cw2 and "persuading part" in _cw2)
    _rev2 = " ".join(rev_skill.split()).lower()
    _rt_path = os.path.join(root, "nbt-revise", "scripts", "revision_token.py")
    _rt = read(_rt_path) if os.path.isfile(_rt_path) else ""
    check("D22 revision names carry one content-hash token (no letter increments)",
          "revision_token.py" in _rev2 and "content-hash" in _rev2
          and "increment rule is withdrawn" in _rev2
          and "collision fallback" in _rev2
          and "increment that token" not in _rev2
          and "version-lettered basenames" not in _rev2
          and "content_token_free" in _rt and "--verify" in _rt)
    def appendix(text, heading, next_heading=None):
        lines = text.split("\n")
        start = next((i + 1 for i, ln in enumerate(lines) if ln.startswith(heading)), None)
        if start is None:
            return ""
        if next_heading:
            end = next((j for j in range(start, len(lines)) if lines[j].startswith(next_heading)),
                       len(lines))
        else:
            end = len(lines)
        return "\n".join(lines[start:end]).strip()

    ip = read(os.path.join(root, "prompts", "identify_issues.prompt.md"))
    sw = read(os.path.join(root, "nbt-review", "references", "sweeps.md"))
    di = read(os.path.join(root, "nbt-review", "references", "discovery.md"))
    check("D18 M18-M24 are reserved/adopted and discovery proposals start at M25",
          "## M18 —" in sweeps and "proposals start at M25" in " ".join(di.split()))
    sweeps_app = appendix(ip, "## APPENDIX: Sweeps", "## APPENDIX: Discovery")
    disc_app = appendix(ip, "## APPENDIX: Discovery")
    check("D10 identify prompt appendices in sync",
          sweeps_app == sw.strip() and disc_app == di.strip())
    ap = read(os.path.join(root, "prompts", "adress_issues.prompt.md"))
    led = read(os.path.join(root, "nbt-revise", "references", "ledger.md"))
    er = read(os.path.join(root, "nbt-revise", "references", "edit_rules.md"))
    led_app = appendix(ap, "## APPENDIX: Ledger", "## APPENDIX: Edit rules")
    er_app = appendix(ap, "## APPENDIX: Edit rules")
    check("D10b revise prompt appendices in sync",
          led_app == led.strip() and er_app == er.strip())
    _ip = " ".join(ip.split()).lower()
    _ap = " ".join(ap.split()).lower()
    check("D19 the Zotero policy's four modes are documented",
          all(m in _rr for m in ("**off**", "**read**", "**edit**", "**apply**"))
          and "snapshot first" in _rr and "citationid" in _rr)
    check("D20 both standalone prompts carry the length rule and the Zotero protocol",
          "172" in _ip and "3,750" in _ip and "m19" in _ip
          and "no cover-letter word limit" in _ip and "always enumerated" in _ip
          and "172" in _ap and "propose-then-verify" in _ap
          and "last-modified auto" in _ap
          and "no cover-letter word limit" in _ap)

    n_fail = sum(1 for _n, ok, _d in RESULTS if not ok)
    print("\n%d checks, %d failed" % (len(RESULTS), n_fail))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regression probes for the v0.4/v0.5 audit findings (R1-R20).

Every probe is written to FAIL on the previous release and PASS on the fixed
one. Run with:

  python3 tests/probe_regressions.py --skill-root . --run-dir /tmp/nbt_probe

Writes only inside --run-dir. Exit status 1 if any probe fails.
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
FAILS = []


def run(skill_root, script, *args):
    p = subprocess.run(
        [sys.executable, os.path.join(skill_root, "nbt-review", "scripts", script)] + list(args),
        capture_output=True, text=True)
    return p


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def analyse(skill_root, case_dir, submission=None):
    sub = submission or os.path.join(case_dir, "sub")
    work = os.path.join(case_dir, "work")
    out = os.path.join(case_dir, "out")
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    run(skill_root, "convert_corpus.py", "--submission", sub, "--work", work)
    for script in ("extract_acronyms.py", "extract_citations.py", "extract_numbers.py"):
        run(skill_root, script, "--work", work, "--out", out)
    return work, out


def m1_rows(out):
    return {r["acronym"]: r for r in load(os.path.join(out, "artifacts", "M1_acronyms.json"))}


def check(cid, desc, ok, detail=""):
    print("%-4s %-6s %-52s %s" % ("PASS" if ok else "FAIL", cid, desc, detail[:110]))
    if not ok:
        FAILS.append(cid)


def docx(path, paras, header=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % p for p in paras)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document %s><w:body>%s</w:body></w:document>' % (W_NS, body))
        if header:
            z.writestr("word/header1.xml",
                       '<?xml version="1.0"?><w:hdr %s><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:hdr>'
                       % (W_NS, header))
        z.writestr("[Content_Types].xml", "<Types/>")


def xlsx(path, shared, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sst = ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           + "".join("<si><t>%s</t></si>" % s for s in shared) + "</sst>")
    wb = ('<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
          ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets><sheet name="S1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships'
            ' xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    body = "".join('<row r="%d">%s</row>' % (i, r) for i, r in enumerate(rows, 1))
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>%s</sheetData></worksheet>' % body)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-root", required=True)
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    root = os.path.abspath(args.skill_root)
    base = os.path.abspath(args.run_dir)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)

    # R1 — all-lowercase gene/protein symbols
    d = os.path.join(base, "r1")
    write(os.path.join(d, "sub", "m.md"),
          "Methods\nExpression of p53, p21, nf1, il6, stat3, mbd3, nrf2 and CD8 was measured.\n")
    work, out = analyse(root, d)
    rows = m1_rows(out)
    missing = [t for t in ("p53", "p21", "nf1", "il6", "stat3", "mbd3", "nrf2", "CD8") if t not in rows]
    check("R1", "lowercase gene/protein symbols inventoried", not missing, "missing=%s" % missing)

    # R2 — extra_acronyms.txt can add digit-free lowercase terms
    d = os.path.join(base, "r2")
    write(os.path.join(d, "sub", "m.md"), "Methods\nWe measured tnf and nanog levels.\n")
    work, out = analyse(root, d)
    before = set(m1_rows(out))
    write(os.path.join(work, "extra_acronyms.txt"), "tnf\nnanog\n")
    run(root, "extract_acronyms.py", "--work", work, "--out", out)
    after = set(m1_rows(out))
    check("R2", "extra_acronyms.txt adds lowercase terms", {"tnf", "nanog"} <= after,
          "before=%s after=%s" % (sorted(before)[:6], sorted(after)[:6]))

    # R3 — bibliography followed by an unrecognised heading
    d = os.path.join(base, "r3")
    write(os.path.join(d, "sub", "main.md"),
          "Results\nBaseline n = 15 patients [1].\n\nReferences\n1. A. One. 2019.\n\n"
          "## Statistical analysis\nValidation cohort n = 12 patients; HLA-DR was measured.\n")
    work, out = analyse(root, d)
    m4 = read(os.path.join(out, "artifacts", "M4_numbers.md"))
    check("R3", "content after bibliography + unknown heading is swept",
          "| n | 12 |" in m4 and "HLA-DR" in m1_rows(out),
          "n-rows=%s" % [l for l in m4.splitlines() if l.startswith("| n")])

    # R4 — unheaded prose after the reference list
    d = os.path.join(base, "r4")
    write(os.path.join(d, "sub", "main.md"),
          "Results\nBaseline n = 15 patients [1].\n\nReferences\n1. A. One. 2019.\n\n"
          "The validation cohort comprised n = 12 patients.\n")
    work, out = analyse(root, d)
    m4 = read(os.path.join(out, "artifacts", "M4_numbers.md"))
    check("R4", "unheaded prose after the reference list is swept", "| n | 12 |" in m4,
          "n-rows=%s" % [l for l in m4.splitlines() if l.startswith("| n")])

    # R5 — unnumbered author-year reference entries
    d = os.path.join(base, "r5")
    write(os.path.join(d, "sub", "paper.md"),
          "Introduction\nAs shown before (Smith et al., 2019), the effect is real.\n\n"
          "References\nSmith J. A study of things. Nature. 2019;570:1-9.\n"
          "Jones A, Lee B. Another study. Science. 2020;11:20-30.\n")
    work, out = analyse(root, d)
    m2 = load(os.path.join(out, "artifacts", "M2_citations.json"))
    check("R5", "unnumbered author-year reference entries enumerated",
          len(m2.get("ref_entries", [])) >= 2, "ref_entries=%d" % len(m2.get("ref_entries", [])))

    # R6 — a Results sentence starting "Fig. 1 shows ..." must not flip the context
    d = os.path.join(base, "r6")
    write(os.path.join(d, "sub", "main.md"),
          "Results\nFig. 1 shows the cohort design.\nExpression of HLA-DR was measured in every sample.\n")
    work, out = analyse(root, d)
    rows = m1_rows(out)
    ctx = " ".join((rows.get("HLA-DR", {}).get("first_occurrence_per_context") or {}).keys())
    check("R6", "prose 'Fig. 1 shows ...' does not flip the section", "figure legend" not in ctx,
          "context=%r" % ctx)

    # R7 — sparse xlsx rows keep column alignment
    d = os.path.join(base, "r7")
    xlsx(os.path.join(d, "sub", "supp.xlsx"), ["Sample", "count", "batch"],
         [['<c r="A1" t="s"><v>0</v></c>', '<c r="B1" t="s"><v>1</v></c>', '<c r="C1" t="s"><v>2</v></c>'],
          ['<c r="A2" t="s"><v>3</v></c>', '<c r="B2"><v>15</v></c>'],
          ['<c r="C3"><v>7</v></c>']])
    work, out = analyse(root, d)
    corpus = read(os.path.join(work, "corpus", "supp.xlsx.txt"))
    rows_txt = [ln for ln in corpus.splitlines() if "|" in ln]
    widths = {len(ln.split("|")) for ln in rows_txt}
    check("R7", "sparse xlsx rows keep column alignment", len(widths) == 1,
          "rows=%s widths=%s" % (rows_txt, sorted(widths)))

    # R8 — repeated --value is honoured
    d = os.path.join(base, "r8")
    write(os.path.join(d, "sub", "paper.md"),
          "Results\nValues were 0.021 and 0.031 in two cohorts.\n")
    work, out = analyse(root, d)
    p = run(root, "extract_occurrences.py", "--work", work, "--value", "0.021", "--value", "0.031")
    md = "".join(read(os.path.join(work, f)) for f in os.listdir(work)
                 if f.startswith("occurrences_") and f.endswith(".md"))
    check("R8", "repeated --value enumerates every value",
          p.returncode == 0 and md.count("## Target:") >= 2,
          "targets=%d" % md.count("## Target:"))

    # R9 — measurement intervals are not citations
    d = os.path.join(base, "r9")
    write(os.path.join(d, "sub", "paper.md"),
          "Results\nThe samples had values [2, 5] in arbitrary units and ages [8, 9] years.\n"
          "Doses [3, 4] mg were given.\n\nReferences\n1. A. One. 2019.\n")
    work, out = analyse(root, d)
    m2 = load(os.path.join(out, "artifacts", "M2_citations.json"))
    check("R9", "measurement intervals are not citation call-outs",
          not re.search(r"\[(?:2,\s*5|8,\s*9|3,\s*4)\]",
                        " ".join(c["raw"] for c in m2.get("callouts", []))),
          "callouts=%s suspects=%d" % ([c["raw"] for c in m2.get("callouts", [])],
                                       len(m2.get("suspect_brackets", []))))

    # R10 — header text gets its own context
    d = os.path.join(base, "r10")
    os.makedirs(os.path.join(d, "sub"), exist_ok=True)
    docx(os.path.join(d, "sub", "ms.docx"),
         ["Figure legends", "Fig. 1 | HLA-DR staining of Tregs."],
         header="Running head: FMO controls")
    work, out = analyse(root, d)
    rows = m1_rows(out)
    ctx = " ".join((rows.get("FMO", {}).get("first_occurrence_per_context") or {}).keys())
    check("R10", "header text carries its own context", "header" in ctx, "context=%r" % ctx)

    # R11 — dead constants removed
    src = read(os.path.join(root, "nbt-review", "scripts", "convert_corpus.py"))
    check("R11", "unused constants removed from convert_corpus.py",
          "READABLE_READONLY" not in src and not re.search(r"^W_NS\s*=", src, re.M))

    # R12 — regression harness ships with the package
    check("R12", "tests/ shipped and referenced by CHANGELOG",
          os.path.exists(os.path.join(root, "tests", "validate_skill.py"))
          and "tests/" in read(os.path.join(root, "CHANGELOG.md")))

    # R13 — the skipped reference-region boundary is visible in the artifacts
    d = os.path.join(base, "r13")
    write(os.path.join(d, "sub", "main.md"),
          "Results\nn = 15 [1].\n\nReferences\n1. A. One. 2019.\n")
    work, out = analyse(root, d)
    m1md = read(os.path.join(out, "artifacts", "M1_acronyms.md"))
    m4md = read(os.path.join(out, "artifacts", "M4_numbers.md"))
    check("R13", "reference-region boundary recorded in artifacts",
          "reference" in m1md.lower() and "reference" in m4md.lower()
          and ("lines" in m1md.lower() or "line" in m1md.lower()),
          "m1=%r" % [l for l in m1md.splitlines() if "reference" in l.lower()][:1])

    # R14 — corpus markers do not become acronym rows
    d = os.path.join(base, "r14")
    xlsx(os.path.join(d, "sub", "supp.xlsx"), ["Sample"], [['<c r="A1" t="s"><v>0</v></c>']])
    os.makedirs(os.path.join(d, "sub"), exist_ok=True)
    docx(os.path.join(d, "sub", "ms.docx"), ["Results", "Text."], header="Head")
    work, out = analyse(root, d)
    rows = set(m1_rows(out))
    check("R14", "sheet/header markers are not acronym rows",
         not ({"SHEET", "HEADER", "FOOTER"} & rows), "rows=%s" % sorted(rows))

    # R15 — M1b: a definition in one context and long-form re-use in another
    d = os.path.join(base, "r15")
    write(os.path.join(d, "sub", "01_abstract.md"),
          "Abstract\n\nCopy-number (CN) alterations are common in tumours.\n")
    write(os.path.join(d, "sub", "02_main.md"),
          "Results\n\nWe scored copy-number burden per cell.\n"
          "The copy-number gains were frequent.\n")
    work, out = analyse(root, d)
    row = m1_rows(out).get("CN") or {}
    m1md = read(os.path.join(out, "artifacts", "M1_acronyms.md"))
    check("R15", "M1b finds long-form re-use after an abstract-only definition",
          row.get("long_form_after_first_use_total") == 1
          and row.get("long_form_after_first_use", {}).get("main text") == ["02_main.md.txt:4"]
          and "## M1b" in m1md,
          "total=%s first=%s" % (row.get("long_form_after_first_use_total"),
                                 row.get("long_form_first_use")))

    # R16 — the abbreviation-key form "CN, copy number" is a definition
    d = os.path.join(base, "r16")
    write(os.path.join(d, "sub", "legend.md"),
          "Fig. 1 | Hap_0: haploid ground truth. CN, copy number; "
          "PCC, Pearson correlation coefficient.\n"
          "The CN caller measured a copy number gain.\n")
    work, out = analyse(root, d)
    rows = m1_rows(out)
    cn, pcc = rows.get("CN") or {}, rows.get("PCC") or {}
    m1md = read(os.path.join(out, "artifacts", "M1_acronyms.md"))
    key_rows = [ln for ln in m1md.split("## M1b", 1)[-1].splitlines()
                if ln.startswith("| CN |") and "legend.md.txt:1 " in ln]
    check("R16", "abbreviation-key entries define instead of flagging residue",
          cn.get("defined_at_first_use") == "Y" and not key_rows
          and cn.get("long_form_after_first_use_total") == 1
          and pcc.get("expansions") == ["Pearson correlation coefficient"],
          "cn=%s key_rows=%s pcc=%s" % (cn.get("defined_at_first_use"), key_rows,
                                        pcc.get("expansions")))

    # R17 — a bibliography file is not manuscript prose
    d = os.path.join(base, "r17")
    write(os.path.join(d, "sub", "refs.bib"),
          "@article{x,\n  title = {A study of copy-number variation},\n"
          "  abstract = {We profiled copy-number states in 100 samples.}\n}\n")
    write(os.path.join(d, "sub", "01_abstract.md"),
          "Abstract\n\nCopy-number (CN) alterations are common.\n")
    work, out = analyse(root, d)
    rows = m1_rows(out)
    files = {f for r in rows.values() for f in (r.get("files") or [])}
    check("R17", "bibliography contributes no M1 tokens and no M1b rows",
          not any("refs.bib" in f for f in files)
          and "## M1b" in read(os.path.join(out, "artifacts", "M1_acronyms.md"))
          and "no long-form re-use detected" in read(os.path.join(out, "artifacts",
                                                                  "M1_acronyms.md")),
          "files=%s" % sorted(files))

    # R18 — quoted titles are counted, never rows
    d = os.path.join(base, "r18")
    write(os.path.join(d, "sub", "ms.md"),
          "Abstract\n\nCopy-number (CN) states were called.\n\n"
          "Results\n\nWe scored copy-number states per cell.\n"
          "See \u201cCopy-number analysis of single cells\u201d for the method,\n"
          "then a final copy-number check was run.\n")
    work, out = analyse(root, d)
    row = m1_rows(out).get("CN") or {}
    check("R18", "a quoted long-form title is counted, not listed",
          row.get("long_form_after_first_use_total") == 1
          and sum((row.get("long_form_quoted_skipped") or {}).values()) == 1,
          "rows=%s quoted=%s" % (row.get("long_form_after_first_use_total"),
                                 row.get("long_form_quoted_skipped")))

    # R19 — the closed loop: substitution clears the M1b table
    d = os.path.join(base, "r19")
    write(os.path.join(d, "sub", "01_abstract.md"),
          "Abstract\n\nCopy-number (CN) alterations are common.\n")
    write(os.path.join(d, "sub", "02_main.md"),
          "Results\n\nWe scored copy-number burden per cell.\n"
          "We scored CN burden per cell.\n")
    work, out = analyse(root, d)
    row = m1_rows(out).get("CN") or {}
    check("R19", "P1a substitution leaves zero M1b rows for that context",
          row.get("long_form_after_first_use_total") == 0
          and "no long-form re-use detected" in read(os.path.join(out, "artifacts",
                                                                  "M1_acronyms.md")),
          "total=%s" % row.get("long_form_after_first_use_total"))

    # R20 — repeated page furniture is annotated with its repeat count
    d = os.path.join(base, "r20")
    write(os.path.join(d, "sub", "ms.md"),
          "Abstract\n\nCopy-number (CN) states were called.\n\n"
          "Results\n\nWe benchmarked copy-number inference.\n"
          "We benchmarked copy-number inference.\n"
          "We benchmarked copy-number inference.\n")
    work, out = analyse(root, d)
    furn = [ln for ln in read(os.path.join(out, "artifacts", "M1_acronyms.md")).splitlines()
            if ln.startswith("| CN |") and "[same line x3 in this file]" in ln]
    check("R20", "repeated identical lines carry a page-furniture annotation",
          len(furn) == 2, "rows=%d" % len(furn))

    print("\n%d probe(s) failed%s" % (len(FAILS), (": " + ", ".join(FAILS)) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

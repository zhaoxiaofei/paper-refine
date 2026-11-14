#!/usr/bin/env python3
"""Regression checks for the fix-bugs 20261114-213018 wave-1 candidates.

Run:  conda run -n paper-refine-test python \
          .paper_test/test_fix_bugs_20261114_candidates_wave1.py

Pinned here:
  F01  the deletion audit honours the package's declared submission set
  F02  the deletion audit reports a submitted file it could not read
  F07  a value that changes UNIT is a fact change, not a surviving fact
  F08  "accession number <id>" records the accession, not the word "number"
  F12  the pre-repair snapshot never follows/trusts a symlink into the package
  F13  the probe-audit verdict is read from its verdict column only
  F14  a submitted DOCX that cannot be parsed is a named coverage gap
  F18  revision_token.py survives an unreadable subdirectory and reports it
  F20  README states that the default deletion mode runs the fact gate
  F31  --disable-insertions sees a citation the base never made
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_fix_bugs_20261114_cand",
                                              str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["paper_fix_bugs_20261114_cand"] = pp
spec.loader.exec_module(pp)

SCRIPT = WS / "paper-skills" / "paper-revise" / "scripts" / "revision_token.py"
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


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_docx(path: Path, paras) -> None:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
                   for p in paras)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>'
                   f'{body}</w:body></w:document>')


# ---------------------------------------------------------------- F01 / F02
def test_deletion_audit_surface() -> None:
    print("\n== F01/F02: the deletion audit reads the submitted set, and names unreadable files ==")
    root = scratch("fbC_del_")
    base = root / "base"
    base.mkdir()
    write(base / "README.md", "Only `main*.md` will be submitted to the journal.\n")
    write(base / "main.md", "We measured the samples with the standard protocol.\n")
    write(base / "notes.md",
          "An internal working note with 6137 seedlings in block A.\n")
    docs = [r[0] for r in pp.deletion_audit_paragraphs(base)]
    check("F01 a README-declared non-submitted file is not audited",
          docs == ["main.md"], str(docs))

    bad = root / "bad"
    bad.mkdir()
    (bad / "bad.docx").write_bytes(b"not a zip")
    write(bad / "ok.md", "A real paragraph with 1234 facts lives in the text.\n")
    skipped = []
    rows = pp.deletion_audit_paragraphs(bad, skipped=skipped)
    check("F02 the unreadable submitted DOCX is named as skipped",
          skipped == ["bad.docx"], str(skipped))
    check("F02 the readable document is still audited",
          [r[0] for r in rows] == ["ok.md"], str(rows))
    rev = root / "revised"
    rev.mkdir()
    skipped_rows = []
    out = pp.deletion_audit_rows(bad, rev, skipped=skipped_rows)
    check("F02 deletion_audit_rows threads the skipped channel",
          skipped_rows == ["bad.docx"] and [r["document"] for r in out] == ["ok.md"],
          f"{skipped_rows} {out}")


# ---------------------------------------------------------------- F07 / F08
def test_fact_units_and_accession() -> None:
    print("\n== F07/F08: a unit is part of a numeric fact; an accession is not 'number' ==")
    root = scratch("fbC_fact_")
    base, cand = root / "base", root / "revised"
    base.mkdir()
    cand.mkdir()
    write(base / "main.md",
          "# Methods\n\nWe injected 55 mg of the drug into each animal.\n\n"
          "We measured seedling density in every plot of the stand.\n")
    write(cand / "main.md",
          "# Methods\n\nWe injected 55 ml of vehicle into each control animal.\n\n"
          "We measured seedling density in every plot of the stand.\n")
    problems = pp.fact_preservation_problems(base, cand, "revise")
    check("F07 a unit-only change is a fact change",
          len(problems) == 1 and "55 mg" in problems[0] and "UNIT" in problems[0],
          str(problems))
    # A corrected NUMBER in a surviving sentence is still allowed (R12-3).
    base2, cand2 = root / "b2", root / "c2"
    base2.mkdir()
    cand2.mkdir()
    write(base2 / "main.md",
          "# Methods\n\nWe selected 12 blocks along the transect and matched the plots.\n")
    write(cand2 / "main.md",
          "# Methods\n\nWe selected 6 blocks along the transect and matched the plots.\n")
    check("F07 a changed value in a surviving sentence is not a unit change",
          pp.fact_preservation_problems(base2, cand2, "revise") == [])
    # The ordinary English word "in" is not the inch unit: a count phrase must
    # not be turned into a measurement.
    base3, cand3 = root / "b3", root / "c3"
    base3.mkdir()
    cand3.mkdir()
    write(base3 / "main.md", "The group had 55 in the sample and the rest outside.\n")
    write(cand3 / "main.md", "The group had 55 samples and the rest outside.\n")
    check("F07 '55 in the sample' is not read as 55 inches",
          pp.fact_preservation_problems(base3, cand3, "revise") == [])

    # Equivalent spellings/case of the SAME unit are one fact (R01), and a
    # one-letter label glued to a hyphenated word ("A-rated") is not a unit.
    equivalents = [
        ("The sample was 55 ml of buffer.", "The sample was 55 mL of buffer.", "ml/mL"),
        ("The sample was 55 l of buffer.", "The sample was 55 L of buffer.", "l/L"),
        ("The sample was 55 hr of buffer.", "The sample was 55 h of buffer.", "hr/h"),
        ("The sample was 55 uL of buffer.", "The sample was 55 \u00b5L of buffer.",
         "uL/\u00b5L"),
        ("The sample was 55 mg of buffer.", "The sample was 55 milligrams of buffer.",
         "mg/milligrams"),
        ("We included 12 A-rated items in the survey.",
         "We included 12 B-rated items in the survey.", "A-rated/B-rated"),
    ]
    for i, (b_text, c_text, label) in enumerate(equivalents):
        b, c = root / f"eqb{i}", root / f"eqc{i}"
        b.mkdir()
        c.mkdir()
        write(b / "main.md", b_text + "\n")
        write(c / "main.md", c_text + "\n")
        got = pp.fact_preservation_problems(b, c, "revise")
        check(f"R01 equivalent units {label} are not a unit change", got == [], str(got))
    # A case-distinct unit is a different measurement and stays reported.
    b, c = root / "caseb", root / "casec"
    b.mkdir()
    c.mkdir()
    write(b / "main.md", "The sample was 55 m of buffer.\n")
    write(c / "main.md", "The sample was 55 M of buffer.\n")
    got = pp.fact_preservation_problems(b, c, "revise")
    check("R01 case-distinct units m/M are still a unit change",
          len(got) == 1 and "UNIT" in got[0], str(got))

    # A compound unit token is part of the key, not a bare number (R02).
    compounds = [
        ("The dose was 55 mg/kg in the treated group.",
         "The dose was 55 mg/mL in the treated group.", "mg/kg->mg/mL"),
        ("The dose was 55 mg/kg in the treated group.",
         "The dose was 55 ug/kg in the treated group.", "mg/kg->ug/kg"),
    ]
    for i, (b_text, c_text, label) in enumerate(compounds):
        b, c = root / f"cmpb{i}", root / f"cmpc{i}"
        b.mkdir()
        c.mkdir()
        write(b / "main.md", b_text + "\n")
        write(c / "main.md", c_text + "\n")
        got = pp.fact_preservation_problems(b, c, "revise")
        check(f"R02 compound unit change {label} is a fact change",
              len(got) == 1 and "UNIT" in got[0], str(got))

    toks = pp._fact_survival_tokens(
        "The data are under accession number PRJNA12345 in the archive.")
    check("F08 'accession number <id>' keeps the accession token",
          "PRJNA12345" in toks and "number" not in toks, str(toks))
    check("F08 the colon form records the same accession key",
          pp._fact_survival_key(
              pp._fact_survival_tokens("accession: PRJNA12345")[0])
          == pp._fact_survival_key("PRJNA12345"))


# ---------------------------------------------------------------- F12
def test_prerepair_symlink_safety() -> None:
    print("\n== F12: the bounded-repair snapshot must not follow or trust symlinks ==")
    root = scratch("fbC_pre_")
    outside = root / "outside"
    outside.mkdir()
    write(outside / "secret.txt", "outside secret\n")
    sb = root / "sb"
    rev = sb / pp.REVISED_DIR
    rev.mkdir(parents=True)
    write(rev / "main.md", "manuscript\n")
    os.symlink(outside, rev / "sub")
    err = pp._snapshot_revised_prerepair(sb)
    pre = sb / "revised_prerepair"
    check("F12 the snapshot succeeds", err == "", err)
    check("F12 a nested link stays a link instead of being followed",
          pre.is_dir() and not pre.is_symlink() and (pre / "sub").is_symlink(),
          f"pre dir={pre.is_dir()} link={(pre / 'sub').is_symlink()}")
    check("F12 outside content is not copied in place of the link",
          (pre / "sub").resolve() == outside.resolve()
          and not (pre / "secret.txt").exists())

    sb2 = root / "sb2"
    (sb2 / pp.REVISED_DIR).mkdir(parents=True)
    write(sb2 / pp.REVISED_DIR / "main.md", "manuscript\n")
    pre2 = sb2 / "revised_prerepair"
    os.symlink(outside, pre2)
    err2 = pp._snapshot_revised_prerepair(sb2)
    check("F12 a planted revised_prerepair symlink is replaced by a real snapshot",
          err2 == "" and pre2.is_dir() and not pre2.is_symlink(),
          f"{err2} dir={pre2.is_dir()} link={pre2.is_symlink()}")
    check("F12 the planted target's files are not the snapshot",
          not (pre2 / "secret.txt").exists())

    sb3 = root / "sb3"
    cur = sb3 / pp.REVISED_DIR
    cur.mkdir(parents=True)
    write(cur / "main.md", "current package\n")
    os.symlink(outside, sb3 / "revised_prerepair")
    err3 = pp._restore_revised_from_prerepair(sb3)
    check("F12 a symlinked pre-repair snapshot is refused on restore",
          bool(err3) and "symlink" in err3, str(err3))
    check("F12 the refused restore copies no outside content",
          not (cur / "secret.txt").exists())


# ---------------------------------------------------------------- F13
def test_probe_audit_column() -> None:
    print("\n== F13: the probe verdict is read from the verdict column only ==")
    row = {"probe id": "P1", "reviewer's disposition": "no anomalies",
           "your verdict": "", "evidence": "stands unrebutted by any source"}
    check("F13 an evidence cell beginning 'stands' is not a verdict",
          pp._probe_audit_verdict(row) == "")
    row2 = {"probe id": "P2", "reviewer's disposition": "no anomalies",
            "your verdict": "stands on the named locations", "evidence": "x"}
    check("F13 the named verdict column is accepted",
          pp._probe_audit_verdict(row2).startswith("stands"))
    row3 = {"probe id": "P3", "reviewer's disposition": "stands but unfounded",
            "your verdict": "", "evidence": "x"}
    check("F13 the reviewer's own disposition column is not the audit's verdict",
          pp._probe_audit_verdict(row3) == "")


# ---------------------------------------------------------------- F14
def test_document_read_gaps() -> None:
    print("\n== F14: an unreadable submitted DOCX is a named coverage gap ==")
    root = scratch("fbC_docx_")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "bad.docx").write_bytes(b"not a zip")
    write(pkg / "main.md",
          "# Results\n\nA real paragraph with a claim and 1234 facts here.\n")
    docs = pp._package_document_texts(pkg)
    gaps = list(getattr(docs, "gaps", []) or [])
    check("F14 the shared document reader records the parse failure",
          any("bad.docx" in g for g in gaps), str(gaps))
    gap_rows = pp._document_read_gap_rows(docs)
    check("F14 the package report carries a named gap row",
          bool(gap_rows) and gap_rows[0].get("gap")
          and "bad.docx" in gap_rows[0].get("detail", ""), str(gap_rows))
    glue = pp.package_front_matter_glue_rows(pkg)
    check("F14 the front-matter glue scan reports the unreadable DOCX",
          any(r.get("gap") and "bad.docx" in r.get("detail", "") for r in glue),
          str(glue))
    # The consumer must not turn the gap into `document: None` with a
    # `: None --` prefix (R04).
    glue_ready = pp.package_readiness({"hygiene": {"front_matter_glue": glue}})
    glue_gap = [f for f in glue_ready.get("findings") or []
                if f.get("rule") == "FMT-X2" and "bad.docx" in str(f.get("detail") or "")]
    check("R04 the glue gap reaches the consumer with its document and no bad prefix",
          bool(glue_gap) and glue_gap[0].get("document") == "bad.docx"
          and ": None --" not in str(glue_gap[0].get("detail") or "")
          and not str(glue_gap[0].get("detail") or "").startswith(":"),
          str(glue_gap))
    # A corrupt MAIN document beside a readable form must not look clean.
    pkg2 = root / "pkg2"
    pkg2.mkdir()
    (pkg2 / "main.docx").write_bytes(b"not a zip")
    make_docx(pkg2 / "reporting_summary.docx",
              ["Software. STAR 2.7.5 and bedtools 2.31 were used."])
    form = pp.scan_form_software_coverage(pkg2)
    check("F14 the form-software scan gaps the unreadable main document",
          any(r.get("gap") and "main.docx" in r.get("detail", "") for r in form),
          str(form))
    # The PKG-6..9 contradiction scan uses a second shared reader; a corrupt
    # DOCX there is the same named gap, not an empty document.
    contradictions = pp.package_contradiction_rows(pkg)
    check("F14 the contradiction scan reports the unreadable DOCX",
          any(r.get("gap") and "bad.docx" in r.get("detail", "")
              for r in contradictions), str(contradictions))
    docs2 = pp.package_document_texts(pkg)
    check("F14 package_document_texts also carries its read gaps",
          any("bad.docx" in g for g in getattr(docs2, "gaps", []) or []),
          str(getattr(docs2, "gaps", None)))


# ---------------------------------------------------------------- F18
def test_revision_token_unreadable_dir() -> None:
    print("\n== F18: revision_token.py survives an unreadable subdirectory ==")
    root = scratch("fbC_tok_")
    sub = root / "sub"
    sub.mkdir()
    write(root / "main.md", "body text here\n")
    write(sub / "x.md", "hidden\n")
    os.chmod(sub, 0)
    try:
        out = subprocess.run([sys.executable, str(SCRIPT), "--json", str(root)],
                             capture_output=True, text=True)
    finally:
        os.chmod(sub, stat.S_IRWXU)
    check("F18 the tool exits 0 instead of raising PermissionError", out.returncode == 0,
          f"rc={out.returncode} stderr={out.stderr[:300]}")
    try:
        info = json.loads(out.stdout)
    except ValueError:
        info = {}
    check("F18 the unreadable directory is reported as a note",
          any("unreadable director" in n for n in info.get("notes") or []),
          f"{info.get('notes')} stdout={out.stdout[:300]}")
    check("F18 the readable payload is still hashed",
          len(info.get("token") or "") == 7, str(info.get("token")))


# ---------------------------------------------------------------- F20
def test_readme_default_documents_fact_gate() -> None:
    print("\n== F20: the README content-policy default names the fact gate ==")
    text = (WS / "README.md").read_text(encoding="utf-8")
    check("F20 the old 'exactly as it always has' default promise is gone",
          "By default the pipeline behaves exactly as it always has: a revision may add prose"
          not in text)
    check("F20 the default section states the fact-survival gate still runs",
          "fact-survival gate (D8) still" in text and "including this default" in text)


# ---------------------------------------------------------------- F31
def test_inserted_citation_with_existing_bib_entry() -> None:
    print("\n== F31: --disable-insertions sees a newly cited uncited .bib entry ==")
    root = scratch("fbC_cite_")
    base, cand = root / "base", root / "revised"
    base.mkdir()
    cand.mkdir()
    write(base / "main.md", "We measured the samples with the standard protocol.\n")
    write(base / "refs.bib", "@article{New2025, title={X}, year={2025}}\n")
    write(cand / "main.md",
          "We measured the samples with the standard protocol \\cite{New2025}.\n")
    write(cand / "refs.bib", "@article{New2025, title={X}, year={2025}}\n")
    check("F31 the prose-only key sets expose the new citation occurrence",
          pp._citation_keys(base, include_bibliography=False) == set()
          and pp._citation_keys(cand, include_bibliography=False) == {"New2025"})
    problems = pp.content_edit_problems(
        None, base, cand, "revise", insertions_allowed=False, deletions_allowed=True)
    check("F31 the strict insertion policy reports the new citation",
          len(problems) == 1 and "New2025" in problems[0], str(problems))
    # Adding only an UNCITED .bib entry is not a manuscript insertion.
    write(base / "empty.md", "A stable sentence in the manuscript body.\n")
    write(cand / "empty.md", "A stable sentence in the manuscript body.\n")
    base2, cand2 = root / "b2", root / "c2"
    base2.mkdir()
    cand2.mkdir()
    write(base2 / "main.md", "A stable sentence in the manuscript body.\n")
    write(cand2 / "main.md", "A stable sentence in the manuscript body.\n")
    write(cand2 / "refs.bib", "@article{OnlyBib2026, title={Y}, year={2026}}\n")
    check("F31 an uncited bibliography entry alone is not an insertion",
          pp.content_edit_problems(
              None, base2, cand2, "revise",
              insertions_allowed=False, deletions_allowed=True) == [])


def main() -> int:
    test_deletion_audit_surface()
    test_fact_units_and_accession()
    test_prerepair_symlink_safety()
    test_probe_audit_column()
    test_document_read_gaps()
    test_revision_token_unreadable_dir()
    test_readme_default_documents_fact_gate()
    test_inserted_citation_with_existing_bib_entry()
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)
    if FAILS:
        print(f"\n{len(FAILS)} CHECK(S) FAILED: {', '.join(FAILS)}")
        return 1
    print("\nALL WAVE-1 CANDIDATE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regression checks for the 2026-11-14 fact-survival and bounded-repair fixes.

Run:  conda run -n paper-refine-test python .paper_test/test_fix_bugs_20261114_rule12.py

Pinned here (all in paper_pipeline_parts/):
  R12-1  a deleted base sentence may not take a numeric value with it, in EITHER
         content-edit mode (p07 fact_preservation_problems)
  R12-2  a duplicate deletion whose value survives elsewhere is not a fact loss
  R12-3  a changed value inside a SURVIVING sentence is not a deletion, so the
         source-hierarchy repair path is not blocked by the new gate
  R12-4  a deleted identifier (DOI/URL) is a fact loss too
  R12-5  the pipeline's own recorded removals stay exempt
  R12-6  a deleted-paragraph row disposed `OK — no fact is lost` while its value
         is gone is a false disposition (p07 deletion_row_fact_loss_problems)
  R12-7  `fact removed — RP-xxx` and `manual-required` rows are not flagged
  R12-8  a repair-plan row whose `wrong` is descriptive, not literal, fails the
         audit instead of failing the repair after it edited the package
  R12-9  the audited pre-repair package is restored when the repair is rejected
  R12-5d/e a scratch hand-off cannot clear the gate; the package-root one can
  R12-5f the fact gate runs whenever a deletion is permitted (not only the
         permissive both-enabled mode)
  R12-7c/d the row check uses the FULL seeded paragraph, not the truncated cell
  R12-8c a literal `wrong` in a real (deflated) DOCX is not rejected
  R12-14 a genuine identity pair is cleared only by the package-root hand-off
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_fix_bugs_20261114_rule12",
                                              str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["paper_fix_bugs_20261114_rule12"] = pp
spec.loader.exec_module(pp)

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


def package(base_text: str, cand_text: str):
    root = scratch("fbR12_")
    base, cand = root / "base", root / "revised"
    base.mkdir()
    cand.mkdir()
    write(base / "main.md", base_text)
    write(cand / "main.md", cand_text)
    return base, cand


# ---------------------------------------------------------------- R12-1 .. R12-5
def test_fact_preservation() -> None:
    print("\n== R12: a deletion may not take a fact with it ==")
    base, cand = package(
        "# Results\n\nThe deposited count table records 6137 seedlings in block A.\n\n"
        "We measured seedling density in every plot of the stand.\n",
        "# Results\n\nWe measured seedling density in every plot of the stand.\n")
    problems = pp.fact_preservation_problems(base, cand, "revise")
    check("R12-1 a deleted sentence's value is reported",
          len(problems) == 1 and "6137" in problems[0], str(problems))

    # The duplicate deletion is the removable case: the value survives.
    base, cand = package(
        "# Methods\n\nWe counted every seedling twice and recounted the four plots.\n\n"
        "We counted every seedling twice and recounted the four plots.\n",
        "# Methods\n\nWe counted every seedling twice and recounted the four plots.\n")
    check("R12-2 a duplicate whose value survives is not a fact loss",
          pp.fact_preservation_problems(base, cand, "revise") == [])

    # A value CHANGED inside a surviving sentence is the agreement rule's job,
    # not a deletion: the gate must not block it.
    base, cand = package(
        "# Methods\n\nWe selected 12 blocks along the transect and matched the plots.\n",
        "# Methods\n\nWe selected 6 blocks along the transect and matched the plots.\n")
    check("R12-3 a changed value in a surviving sentence is not a deletion",
          pp.fact_preservation_problems(base, cand, "revise") == [])

    base, cand = package(
        "# Data\n\nThe archive is at https://doi.org/10.1234/abcd.5678 for the cohort.\n\n"
        "We thank the landowner for access to the stand.\n",
        "# Data\n\nWe thank the landowner for access to the stand.\n")
    problems = pp.fact_preservation_problems(base, cand, "revise")
    check("R12-4 a deleted identifier is a fact loss",
          len(problems) == 1 and "doi.org" in problems[0], str(problems))

    removed = ["The deposited count table records 6137 seedlings in block A."]
    base, cand = package(
        "# Results\n\nThe deposited count table records 6137 seedlings in block A.\n\n"
        "We measured seedling density in every plot of the stand.\n",
        "# Results\n\nWe measured seedling density in every plot of the stand.\n")
    check("R12-5 a recorded pipeline removal stays exempt",
          pp.fact_preservation_problems(base, cand, "revise",
                                        exempt_removed=removed) == [])

    # The compliant route: a value that must leave the manuscript is recorded
    # for the author, and that record clears the gate instead of looping.
    base, cand = package(
        "# Results\n\nThe archived block holds 6137 seedlings in the sample.\n\n"
        "We measured seedling density in every plot of the stand.\n",
        "# Results\n\nWe measured seedling density in every plot of the stand.\n")
    write(cand / "README-AUTHOR-TO-COMPLETE.md",
          "| id | manual action |\n|---|---|\n"
          "| T-001 | restore the archived block count 6137 from the deposit |\n")
    check("R12-5c a value recorded for the author clears the gate",
          pp.fact_preservation_problems(base, cand, "revise") == [])

    # Only the package ROOT is the author hand-off: a same-named file in the
    # session's own scratch must not clear the gate (that is how a reward hack
    # would look -- write the lost value into work/ and keep the deletion).
    base, cand = package(
        "# Results\n\nThe archived block holds 6137 seedlings in the sample.\n\n"
        "We measured seedling density in every plot of the stand.\n",
        "# Results\n\nWe measured seedling density in every plot of the stand.\n")
    write(cand / "work" / "MANUAL_STEPS.md", "restore the archived block count 6137\n")
    check("R12-5d scratch work/MANUAL_STEPS.md does NOT clear the gate",
          len(pp.fact_preservation_problems(base, cand, "revise")) == 1)
    write(cand / "MANUAL_STEPS.md", "restore the archived block count 6137\n")
    check("R12-5e the root hand-off file does clear it",
          pp.fact_preservation_problems(base, cand, "revise") == [])

    # The gate must run whenever a DELETION is permitted: the no-deletion mode
    # already reports every missing unit, but --disable-insertions (deletions
    # still on) has no other deletion check.
    check("R12-5f the fact gate is enabled whenever a deletion is allowed",
          pp.fact_survival_required(False, True) is True
          and pp.fact_survival_required(True, True) is True
          and pp.fact_survival_required(True, False) is False
          and pp.fact_survival_required(False, False) is False)

    # A single digit is a list marker or a cross-reference far more often than a
    # fact, so it is not a survival token.
    base, cand = package(
        "# Results\n\nWe report 3 blocks and one interval in this section now.\n\n"
        "The density response was uniform across the sampled stands.\n",
        "# Results\n\nThe density response was uniform across the sampled stands.\n")
    check("R12-5b a lone digit is not a survival token",
          pp.fact_preservation_problems(base, cand, "revise") == [])


# ---------------------------------------------------------------- R12-6 / R12-7
def test_deleted_row_disposition() -> None:
    print("\n== R12: an `OK` disposition cannot cover a lost value ==")
    sb = scratch("fbR12_sb_")
    write(sb / "revised" / "main.md",
          "# Results\n\nWe measured seedling density in every plot of the stand.\n")
    row = {"#": "D7", "document": "main.md", "line": 3,
           "paragraph": "The deposited count table records 6137 seedlings in block A.",
           "disposition": "OK — internal working note; correct value lives in the table"}
    problems = pp.deletion_row_fact_loss_problems(sb, [row])
    check("R12-6 an OK row with a lost value is a false disposition",
          len(problems) == 1 and "6137" in problems[0], str(problems))

    for disposition in ("fact removed — RP-001",
                        "manual-required — the author must restore the block count"):
        check(f"R12-7 `{disposition.split(' ')[0]}` is not flagged",
              pp.deletion_row_fact_loss_problems(sb, [dict(row, disposition=disposition)])
              == [])

    write(sb / "revised" / "main.md",
          "# Results\n\nThe deposited count table records 6137 seedlings in block A.\n\n"
          "We measured seedling density in every plot of the stand.\n")
    check("R12-7b a value that survives elsewhere is not a loss",
          pp.deletion_row_fact_loss_problems(sb, [row]) == [])

    # The seeded table cell is display-truncated; the check must use the FULL
    # seeded paragraph, or a value beyond the cut is a silent false negative.
    long_full = ("Long procedural preamble. " * 80) + "The archived block holds 9241 seedlings."
    truncated = long_full[:1200]
    long_row = {"#": "D9", "document": "main.md", "line": 3, "paragraph": truncated,
                "disposition": "OK — redundant; all values survive elsewhere"}
    check("R12-7c a value beyond the truncated cell is not seen from the cell alone",
          pp.deletion_row_fact_loss_problems(sb, [long_row]) == [])
    check("R12-7d the full seeded paragraph exposes the lost value",
          len(pp.deletion_row_fact_loss_problems(sb, [long_row],
                                                 {"D9": long_full})) == 1)


# ---------------------------------------------------------------- R12-8
def test_repair_plan_literal() -> None:
    print("\n== R12: the repair plan quotes literal text ==")
    sb = scratch("fbR12_plan_")
    write(sb / "revised" / "main.md",
          "In 36 paired plots in a southern temperate mixed forest, thinning raised "
          "canopy openness.\n")
    literal = {"id": "RP-001", "file": "main.md", "wrong": "36 paired plots",
               "correct": "18 paired plots"}
    check("R12-8 a literal `wrong` passes",
          pp.repair_plan_literal_problems(sb, [literal]) == [])

    descriptive = {"id": "RP-002", "file": "main.md",
                   "wrong": "36 paired plots (line 19: 'in 36 paired plots in a mixed "
                            "forest'); line 61: 'The 36 plots were matched'",
                   "correct": "18 paired plots (9 blocks x 2 plots per block = 18)"}
    problems = pp.repair_plan_literal_problems(sb, [descriptive])
    check("R12-8b a descriptive `wrong` fails the audit",
          len(problems) == 1 and "not literal text" in problems[0], str(problems))

    # A real DOCX is a DEFLATED zip: its paragraph text is not in the raw
    # bytes. The audit must read it the way the repair's span audit does.
    docx = sb / "revised" / "main.docx"
    docx_xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                'We selected 36 paired plots along the transect.'
                '</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", docx_xml)
    docx_row = {"id": "RP-003", "file": "main.docx", "wrong": "36 paired plots",
                "correct": "18 paired plots"}
    check("R12-8c a literal DOCX row is not rejected by the raw-bytes read",
          pp.repair_plan_literal_problems(sb, [docx_row]) == [])


# ---------------------------------------------------------------- R12-9
def test_repair_rollback() -> None:
    print("\n== R12: a rejected repair does not ship its edits ==")
    sb = scratch("fbR12_roll_")
    write(sb / "revised" / "main.md", "The audited version says 36 paired plots.\n")
    write(sb / "revised_prerepair" / "main.md", "The audited version says 36 paired plots.\n")
    write(sb / "revised" / "main.md", "The rejected repair rewrote this to 12.\n")
    err = pp._restore_revised_from_prerepair(sb)
    restored = (sb / "revised" / "main.md").read_text(encoding="utf-8")
    check("R12-9 the pre-repair bytes are restored", err == ""
          and "36 paired plots" in restored, f"{err!r} {restored!r}")

    empty = scratch("fbR12_noroll_")
    write(empty / "revised" / "main.md", "kept\n")
    err = pp._restore_revised_from_prerepair(empty)
    check("R12-9b a missing snapshot is reported, the package is untouched",
          bool(err) and "revised_prerepair" in err
          and (empty / "revised" / "main.md").read_text(encoding="utf-8") == "kept\n",
          f"{err!r}")


# ---------------------------------------------------------------- R12-10..13
def test_identity_typo_gate() -> None:
    print("\n== R12: one identity value, one spelling ==")

    def package(front: str, block: str, extra: str = "") -> Path:
        root = scratch("fbR12_id_")
        (root / "revised").mkdir()
        write(root / "revised" / "paper.md",
              "# Title\n\nCorrespondence:\n" + front + "\n\n"
              "## Author metadata\n\n**Authors and correspondence**\n\n" + block + "\n")
        if extra:
            write(root / "revised" / "work" / "notes.md", extra)
        return root / "revised"

    def block(local_domain: str) -> str:
        return f"- Rowan Ellis — {local_domain}"

    pkg = package("rowan.ellis@example-university.ac.uk\n", block("rowan.ellis@example-university-x.ac.uk"))
    problems = pp.identity_typo_problems(pkg, "revise")
    check("R12-10 a near-miss domain is reported", len(problems) == 1
          and "example-university" in problems[0], str(problems))

    pkg = package("rowan.ellis@example-university.ac.uk\n", block("rowan.ellis@example-university.ac.uk"))
    check("R12-11 one spelling is clean", pp.identity_typo_problems(pkg, "revise") == [])

    pkg = package("rowan.ellis@example-university.ac.uk\n", block("rowan.ellis@other-institute.org"))
    check("R12-12 a genuinely different domain is not a typo",
          pp.identity_typo_problems(pkg, "revise") == [])

    pkg = package("rowan.ellis@example-university.ac.uk\n", block("rowan.ellis@example-university.ac.uk"),
                  extra="the old spelling was rowan.ellis@example-university-x.ac.uk\n")
    check("R12-13 bookkeeping is not scanned",
          pp.identity_typo_problems(pkg, "revise") == [])

    # A pair that is genuinely two people is recorded for the author; the
    # message promises that route, so the gate must honour it -- and only from
    # the package ROOT, never from the session's scratch.
    pair = ("rowan.ellis@example-university.ac.uk and "
            "rowan.ellis@example-university-x.ac.uk are two different people\n")
    pkg = package("rowan.ellis@example-university.ac.uk\n",
                  block("rowan.ellis@example-university-x.ac.uk"))
    write(pkg / "work" / "MANUAL_STEPS.md", pair)
    check("R12-14 scratch work/MANUAL_STEPS.md does NOT clear the identity gate",
          len(pp.identity_typo_problems(pkg, "revise")) == 1)
    write(pkg / "MANUAL_STEPS.md", pair)
    check("R12-14b the root hand-off recording BOTH spellings clears it",
          pp.identity_typo_problems(pkg, "revise") == [])


def main() -> int:
    try:
        test_fact_preservation()
        test_deleted_row_disposition()
        test_repair_plan_literal()
        test_repair_rollback()
        test_identity_typo_gate()
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} RULE-12 CHECK(S) FAILED")
        for f in FAILS:
            print("  -", f)
        return 1
    print("all rule-12 regression checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

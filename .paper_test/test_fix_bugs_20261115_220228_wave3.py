#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 3 (run 20261115-220228), candidate C012.

C012 / F012: a non-M20 seeded decision row could be deleted individually as
long as one disposed row of its table remained. The seeded-row gate only
recognised a HEADER-ONLY table (`_empty_keyed`); it never compared the rows that
remain with the rows the read-only base seeded.

The fix pins each seeded table by its own header shape and row count, so:
  * M18/M19/M8/OUTLINE/PLACEHOLDERS/CLAIM_STRENGTH/M2 have one pin each;
  * M30 has THREE pins (tables A, B and C), never their sum -- the summed count
    is what made the first attempt misfire on the end-to-end stub;
  * a table that still has the seeded header but fewer rows is reported;
  * a table replaced by an unrelated generic table is reported too (the seed
    cannot be deleted by changing its shape).

Hermetic: temp dirs only; no agent runs, no network.

Run:  python3 -B .paper_test/test_fix_bugs_20261115_220228_wave3.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def review_dir(files: dict) -> Path:
    rd = Path(tempfile.mkdtemp()) / "guided_review"
    (rd / "artifacts").mkdir(parents=True)
    for rel, text in files.items():
        p = rd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return rd


M18_HEADER = ("| # | document | caption | words | over_limit | excerpt | disposition |\n"
              "|---|---|---|---|---|---|---|\n")


def m18_rows(n: int) -> str:
    return "".join(
        f"| {i} | a.docx | fig{i} | {10 + i} |  |  | OK — figure legend inside its bar |\n"
        for i in range(1, n + 1))


def test_f012_partial_deletion_is_reported():
    print("\n== C012: a partially deleted seeded table is reported ==")
    pins = {"artifacts/M18_caption_words.md": [
        {"columns": ["document", "caption", "words"], "count": 3, "label": "M18"}]}
    rd = review_dir({"artifacts/M18_caption_words.md": M18_HEADER + m18_rows(2)})
    report = pp.artifact_quality_report(rd, require_files=False,
                                        seeded_row_pins=pins)
    problems = report.get("artifacts/M18_caption_words.md") or []
    check("C012 two of three seeded rows is reported",
          any("2 of the 3" in p for p in problems), str(problems)[:300])

    # A complete table is still clean.
    rd = review_dir({"artifacts/M18_caption_words.md": M18_HEADER + m18_rows(3)})
    report = pp.artifact_quality_report(rd, require_files=False,
                                        seeded_row_pins=pins)
    check("C012 a complete seeded table is clean",
          not (report.get("artifacts/M18_caption_words.md") or []), str(report)[:200])


def test_f012_replaced_seeded_table_is_reported():
    print("\n== C012: a replaced seeded table is reported, not accepted ==")
    pins = {"artifacts/M18_caption_words.md": [
        {"columns": ["document", "caption", "words"], "count": 2, "label": "M18"}]}
    rd = review_dir({"artifacts/M18_caption_words.md":
                     "# M18\n\n| row | disposition |\n|---|---|\n"
                     "| stub | OK — nothing found |\n"})
    report = pp.artifact_quality_report(rd, require_files=False,
                                        seeded_row_pins=pins)
    problems = report.get("artifacts/M18_caption_words.md") or []
    check("C012 a generic replacement table does not dispose the seed",
          any("0 of the 2" in p or "none of the 2" in p for p in problems),
          str(problems)[:300])


def test_f012_m30_pins_are_per_table_not_summed():
    print("\n== C012/M30: the three seed tables are pinned separately ==")
    # Table A: 2 seeded rows; B: 2; C: 1. One A row is deleted; B/C complete.
    art = (
        "# M30\n\n## A\n\n"
        "| # | document | kind | number | unit | sentence | candidate producer | "
        "producer summary | seed check | disposition |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| 1 | ms.md | abstract | 12 | | We analysed 12 samples. | raw_data/x.csv:sample | "
        "3 rows | differs | OK — producer is authoritative |\n"
        "| 2 | ms.md | abstract | 0.81 | | accuracy 0.81 | (no shipped table column matches) | "
        " | look in code/ | unable — no shipped producer |\n\n"
        "## B\n\n"
        "| # | file | line | symbol | value | context | disposition |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | code/a.py | 1 | N | 15 | N = 15 | OK — Methods parameter |\n"
        "| 2 | code/a.py | 2 | P | 7 | P = 7 | OK — Methods parameter |\n\n"
        "## C\n\n"
        "| # | written claim | method token | shipped table says | detail | disposition |\n"
        "|---|---|---|---|---|---|\n"
        "| 1 | not run | methodx | table rows | finite values | contradiction — F-001 |\n")
    pins = {"artifacts/M30_hierarchy_reconciliation.md": [
        {"columns": ["document", "kind", "number"], "count": 2,
         "label": "A. written values"},
        {"columns": ["file", "line", "symbol"], "count": 2,
         "label": "B. code literals"},
        {"columns": ["written claim", "method token"], "count": 1,
         "label": "C. negative claims"}]}
    # B and C pass; A has 2 present (we did not delete there) -> clean.
    rd = review_dir({"artifacts/M30_hierarchy_reconciliation.md": art})
    report = pp.artifact_quality_report(rd, require_files=False,
                                        seeded_row_pins=pins)
    check("C012/M30 a complete three-table ledger is clean",
          not (report.get("artifacts/M30_hierarchy_reconciliation.md") or []),
          str(report)[:300])

    deleted = art.replace(
        "| 2 | ms.md | abstract | 0.81 | | accuracy 0.81 | (no shipped table column matches) | "
        " | look in code/ | unable — no shipped producer |\n", "")
    rd = review_dir({"artifacts/M30_hierarchy_reconciliation.md": deleted})
    report = pp.artifact_quality_report(rd, require_files=False,
                                        seeded_row_pins=pins)
    problems = report.get("artifacts/M30_hierarchy_reconciliation.md") or []
    check("C012/M30 the deleted table-A row is reported",
          any("1 of the 2" in p and ("A." in p or "written values" in p) for p in problems),
          str(problems)[:400])

    # A complete B table must not be read as an over-count of A.
    rd = review_dir({"artifacts/M30_hierarchy_reconciliation.md": art})
    report = pp.artifact_quality_report(rd, require_files=False,
                                        seeded_row_pins=pins)
    check("C012/M30 a complete B table does not excuse A",
          not report or not any("3 of the 2" in p
                               for ps in report.values() for p in ps),
          str(report)[:200])


def test_f012_pins_are_derived_per_seeded_table():
    print("\n== C012: the read-only base derives one pin per seeded table ==")
    corpus = Path(tempfile.mkdtemp()) / "corpus"
    (corpus / "raw_data").mkdir(parents=True)
    (corpus / "code").mkdir()
    (corpus / "manuscript.md").write_text(
        "Abstract\n\nWe analysed 12 samples and report accuracy 0.81.\n\n"
        "Methods\n\nWe used tool A with parameter 5.\n\n"
        "Results\n\nThe mean coverage was 30x.\n\n"
        "Figure 1 | Accuracy of the caller.\n", encoding="utf-8")
    (corpus / "raw_data" / "calls.csv").write_text(
        "sample,coverage\n1,31\n2,29\n3,30\n", encoding="utf-8")
    (corpus / "code" / "analysis.py").write_text(
        "N_SAMPLES = 15\nPARAM = 7\n", encoding="utf-8")
    ctx = type("C", (), {"cfg": {}})()
    pins = pp.review_seeded_row_pins(ctx, corpus)
    m30 = pins.get("artifacts/M30_hierarchy_reconciliation.md") or []
    check("C012 the M30 pin is THREE tables, not one summed count",
          len(m30) == 3, str([p.get("count") for p in m30]))
    check("C012 M30 table A carries the hierarchy rows",
          m30 and m30[0]["count"] == 2, str(m30[:1]))
    check("C012 M30 table B carries the literal rows",
          len(m30) > 1 and m30[1]["count"] == 2, str(m30[1:2]))
    # Other seeded tables keep one pin each, with the base-derived count.
    m18 = pins.get("artifacts/M18_caption_words.md") or []
    check("C012 M18 has one pin with the caption count",
          len(m18) == 1 and m18[0]["count"] == 1, str(m18))


def main():
    test_f012_partial_deletion_is_reported()
    test_f012_replaced_seeded_table_is_reported()
    test_f012_m30_pins_are_per_table_not_summed()
    test_f012_pins_are_derived_per_seeded_table()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

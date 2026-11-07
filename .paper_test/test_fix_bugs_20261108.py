#!/usr/bin/env python3
"""Regression checks for the 2026-11-08 fix-bugs wave.

Run:  python3 .paper_test/test_fix_bugs_20261108.py

Each block pins one candidate confirmed on the current tree:

  F01  the cold-start coverage gate rejects a report whose findings outnumber
       the examined candidates, although one candidate may yield several
       independent findings;
  F02  the cold-start checked totals are never compared with the findings list
       when the list is non-empty;
  F03  the review canonical finding shape omits the `scope` key the J5 gate
       requires;
  F06  two-character filler (`ok`, `ab`, `12`) passes as a named basis;
  F12  the skill names the M8 artifact `M8_terminology.md` while the gate and
       the seed require `M8_terms.md`;
  F15  the response change check never binds the quoted spans to the claimed
       location;
  F16  a changed file's ledger quotes are not bound to the plan's
       `wrong`/`correct` values;
  F28  the coverage disposition regex is applied with `match`, so a
       contradictory tail is accepted;
  F34  M16 promises every headline claim but enumerates only numbers;
  F52  the status cell is spelled as a sentence in deliverable prompts;
  F79  the focused-audit E6 compile writes bytecode into the audited tree;
  F82  a clean sweep disposition needs no per-sweep artifact.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
import paper_pipeline as pp  # noqa: E402

FAILS = []
TMPDIRS = []


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"fb1108_{tag}_"))
    TMPDIRS.append(p)
    return p


def cleanup() -> None:
    for p in TMPDIRS:
        shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------- F01/F02
def _finding(i: int) -> dict:
    return {"id": f"X-90{i}", "location": f"base/paper.md:{i}",
            "category": 2, "check": "stale sidecar", "severity": "Major",
            "evidence": f"quote {i}", "explanation": "fix route",
            "status": "resolvable"}


def _cold_start_sandbox(doc: dict) -> Path:
    sb = scratch("cold") / "sb"
    (sb / "cold_start_review").mkdir(parents=True)
    (sb / "cold_start_review" / "findings_cold_start_review.json").write_text(
        json.dumps(doc), encoding="utf-8")
    return sb


def test_cold_start_coverage_counts() -> None:
    print("\n== F01/F02 cold-start coverage counts ==")
    sb = _cold_start_sandbox({"checked": [{"area": "A", "examined": 2, "findings": 3}],
                              "findings": [_finding(1), _finding(2), _finding(3)]})
    errs, _warns, _fs = pp._cold_start_contract_problems(sb)
    check("F01 three findings from two examined candidates is legal", errs == [], errs)

    sb = _cold_start_sandbox({"checked": [{"area": "A", "examined": 10, "findings": 0}],
                              "findings": [_finding(1)]})
    errs, _warns, _fs = pp._cold_start_contract_problems(sb)
    check("F02 checked totals that contradict a non-empty findings list are refused",
          any("checked" in e and "finding" in e for e in errs), errs)

    sb = _cold_start_sandbox({"checked": [{"area": "A", "examined": 10, "findings": 1}],
                              "findings": [_finding(1)]})
    errs, _warns, _fs = pp._cold_start_contract_problems(sb)
    check("F02 matching checked totals are accepted", errs == [], errs)

    # One finding can belong to two examined areas (abstract vs raw_data/), so
    # an over-count is not a contradiction; counting it nowhere is.
    sb = _cold_start_sandbox({"checked": [{"area": "A", "examined": 10, "findings": 1},
                                          {"area": "B", "examined": 4, "findings": 1}],
                              "findings": [_finding(1)]})
    errs, _warns, _fs = pp._cold_start_contract_problems(sb)
    check("F02 a finding counted in two areas is accepted", errs == [], errs)


# ---------------------------------------------------------------- F03
def test_j5_scope_documented() -> None:
    print("\n== F03 the J5 `scope` key is in the canonical shape ==")
    p03 = (WS / "paper_pipeline_parts/p03_prompts.py").read_text(encoding="utf-8")
    block = p03.split("=== CANONICAL OUTPUTS", 1)[-1].split("@@DEFECT_CLASS_RULE@@", 1)[0]
    check("F03 the canonical findings.json example carries `scope`",
          '"scope"' in block, block[:200])
    skill = (WS / "paper-skills/paper-review/SKILL.md").read_text(encoding="utf-8")
    prompt = (WS / "paper-skills/prompts/identify_issues.prompt.md").read_text(encoding="utf-8")
    for name, text in (("review skill", skill), ("identify prompt", prompt)):
        check(f"F03 {name} names the J5 scope key",
              "`scope` key" in text, text[:160])


# ---------------------------------------------------------------- F06/F28
def test_coverage_disposition_strictness() -> None:
    print("\n== F06/F28 coverage dispositions are named and whole ==")
    for value in ("clean -- basis: ok", "clean -- basis: ab", "clean -- basis: 12",
                  "unable -- ok"):
        check(f"F06 {value!r} is filler", not pp._coverage_disposition_ok(value))
    for value in ("clean -- basis: artifacts/M8_terms.md",
                  "unable -- no PDF renderer", "3 findings",
                  "out of scope -- formatting-writing round"):
        check(f"F06 {value!r} is a real disposition", pp._coverage_disposition_ok(value))

    for value in ("2 findings but none", "clean -- basis: x.md not checked"):
        check(f"F28 {value!r} is not one whole disposition",
              not pp._coverage_disposition_ok(value))
    for value in ("2 findings", "2 findings confirmed (F-1, F-2)",
                  "0 findings -- within the relaxed caps",
                  "clean -- basis: artifacts/M8_terms.md (0 competing families)",
                  "unable -- no PDF renderer",
                  "out of scope -- formatting-writing round"):
        check(f"F28 {value!r} is one whole disposition",
              pp._coverage_disposition_ok(value))


# ---------------------------------------------------------------- F12
def test_m8_artifact_name_parity() -> None:
    print("\n== F12 the documented M8 artifact is the seeded M8_terms.md ==")
    paths = ("paper-skills/paper-review/SKILL.md",
             "paper-skills/paper-review/references/sweeps.md",
             "paper-skills/prompts/identify_issues.prompt.md")
    for rel in paths:
        text = (WS / rel).read_text(encoding="utf-8")
        check(f"F12 {rel} names M8_terms.md", "M8_terms.md" in text, rel)
        check(f"F12 {rel} does not name a second M8 artifact",
              "M8_terminology.md" not in text, rel)
    gate = (WS / "paper_pipeline_parts/p06_postchecks.py").read_text(encoding="utf-8")
    check("F12 the gate requires artifacts/M8_terms.md",
          '"artifacts/M8_terms.md"' in gate)
    seed = (WS / "paper_pipeline_parts/p04_utils.py").read_text(encoding="utf-8")
    check("F12 the seed writes M8_terms.md", '_seed_write(art / "M8_terms.md"' in seed)


# ---------------------------------------------------------------- F15
def _response_sandbox(prev: str, target: str, name: str = "paper.md") -> Path:
    sb = scratch("resp") / "sb"
    (sb / "previous_package").mkdir(parents=True)
    (sb / "target").mkdir(parents=True)
    (sb / "previous_package" / name).write_text(prev, encoding="utf-8")
    (sb / "target" / name).write_text(target, encoding="utf-8")
    return sb


def _response_rows(name: str, location: str, before: str, after: str) -> list:
    return [{"id": "C1", "changes": [{
        "file": name, "location": location, "operation": "edit",
        "before": before, "after": after}]}]


def test_response_location_binding() -> None:
    print("\n== F15 a response change's location resolves in the package ==")
    sb = _response_sandbox(
        "## Results\nPrevious manuscript.\nNo age was recorded.\n",
        "## Results\nActual manuscript.\nNo age was recorded.\n")
    rows = _response_rows("paper.md", "Appendix 9", "Previous manuscript.",
                          "Actual manuscript.")
    problems = pp._response_change_span_problems(sb, sb / "target", rows)
    check("F15 an invented location is refused", bool(problems), problems)

    rows[0]["changes"][0]["location"] = "Results"
    problems = pp._response_change_span_problems(sb, sb / "target", rows)
    check("F15 a real section location is accepted", problems == [], problems)

    # R01: the same unchanged sentence also occurs earlier (Abstract); the real
    # edit is in Results and must not be rejected for the earlier occurrence.
    sb = _response_sandbox(
        "## Abstract\nNo age was recorded. More text.\n"
        "## Results\nNo age was recorded. More text.\n",
        "## Abstract\nNo age was recorded. More text.\n"
        "## Results\nAge was recorded. More text.\n")
    rows = _response_rows("paper.md", "Results", "No age was recorded.",
                          "Age was recorded.")
    problems = pp._response_change_span_problems(sb, sb / "target", rows)
    check("R01 a repeated earlier `before` span still resolves at the location",
          problems == [], problems)

    # R01: the revised wording already exists earlier in the file, and the same
    # real edit occurs again in Results.
    sb = _response_sandbox(
        "## Abstract\nAge was recorded.\n## Results\nNo age was recorded.\n",
        "## Abstract\nAge was recorded.\n## Results\nAge was recorded.\n")
    rows = _response_rows("paper.md", "Results", "No age was recorded.",
                          "Age was recorded.")
    problems = pp._response_change_span_problems(sb, sb / "target", rows)
    check("R01 a repeated earlier `after` span still resolves at the location",
          problems == [], problems)

    # Guard: a span that occurs only BEFORE the claimed location is still
    # refused; the R01 fix must not turn the binding into a presence check.
    sb = _response_sandbox(
        "## Abstract\nNo age.\n## Results\nSomething else.\n",
        "## Abstract\nAge.\n## Results\nSomething else.\n")
    rows = _response_rows("paper.md", "Results", "No age.", "Age.")
    problems = pp._response_change_span_problems(sb, sb / "target", rows)
    check("R01 a span only before the claimed location is still refused",
          bool(problems), problems)

    # R01 secondary (review report): a tabular `row N` locator is positional
    # like `line N` and must not be mistaken for an invented section.
    sb = _response_sandbox("x,y\n1,2\n3,4\n", "x,y\n1,2\n3,5\n", name="paper.csv")
    rows = _response_rows("paper.csv", "row 3", "3,4", "3,5")
    problems = pp._response_change_span_problems(sb, sb / "target", rows)
    check("R01 a tabular row locator is accepted", problems == [], problems)


# ---------------------------------------------------------------- F16
def test_repair_plan_binding() -> None:
    print("\n== F16 a changed file's quotes are bound to the plan values ==")
    d = scratch("repair")
    pre, cur = d / "pre", d / "cur"
    pre.mkdir(); cur.mkdir(); (d / "revised").mkdir()
    (pre / "paper.md").write_text("Primary endpoint 7.\nPopulation n = 10.\n")
    (cur / "paper.md").write_text("Primary endpoint 9.\nPopulation n = 10.\n")
    ledger = {"rows": [{"id": "R1", "verdict": "confirmed", "reason": "r",
                         "before": "Primary endpoint 7.",
                         "after": "Primary endpoint 9."}]}
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps(ledger))
    (d / "revised" / "REPAIR_LEDGER.json").write_text(json.dumps(ledger))
    rows = [{"id": "R1", "file": "paper.md", "location": "Results",
             "wrong": "10", "correct": "20", "basis": "b", "edit": "e",
             "evidence": "x"}]
    problem, counts, ids = pp._revision_repair_ledger(d, rows, with_ids=True)
    check("F16 the ledger loads", problem == "" and ids == {"R1"}, (problem, counts))
    bad = pp._revised_repair_violations(pre, cur, rows, {"R1"})
    check("F16 a plan 10 -> 20 discharged by a 7 -> 9 edit is a violation",
          bad == ["paper.md"], bad)

    (pre / "paper.md").write_text("Primary endpoint 7.\nPopulation n = 10.\n")
    (cur / "paper.md").write_text("Primary endpoint 7.\nPopulation n = 20.\n")
    rows[0].update({"wrong": "10", "correct": "20"})
    ledger["rows"][0].update({"before": "Population n = 10.",
                              "after": "Population n = 20."})
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps(ledger))
    (d / "revised" / "REPAIR_LEDGER.json").write_text(json.dumps(ledger))
    bad = pp._revised_repair_violations(pre, cur, rows, {"R1"})
    check("F16 the matching plan values are accepted", bad == [], bad)


# ---------------------------------------------------------------- F34/F52
def test_docs_consistency() -> None:
    print("\n== F34/F52 review documentation is internally consistent ==")
    sweeps = (WS / "paper-skills/paper-review/references/sweeps.md").read_text(encoding="utf-8")
    m16 = sweeps.split("## M16 —", 1)[1].split("## M17 —", 1)[0]
    check("F34 M16 enumerates qualitative headline claims",
          "headline claim" in m16 and ("qualitative" in m16 or "claim" in m16.split("**Enumeration", 1)[1]),
          m16[:260])
    check("F34 M16's artifact has a claim row",
          "abstract value" in m16 and "claim" in m16.split("**Artifact:**", 1)[1],
          m16[:260])

    prompt = (WS / "paper-skills/prompts/identify_issues.prompt.md").read_text(encoding="utf-8")
    p03 = (WS / "paper_pipeline_parts/p03_prompts.py").read_text(encoding="utf-8")
    for name, text in (("review skill", sweeps), ("identify prompt", prompt),
                       ("pipeline prompt", p03)):
        check(f"F52 {name} spells status as the enum",
              "`unresolvable — manual verification required`" not in text
              or "status" not in text,
              name)
    check("F52 the status list is the three enums",
          "Statuses: `resolvable` / `unresolvable` / `guideline-dependent`" in prompt,
          "missing")
    check("F52 the status list is the three enums (sweeps)",
          "Statuses: `resolvable` / `unresolvable` / `guideline-dependent`" in sweeps,
          "missing")


# ---------------------------------------------------------------- F79
def test_focused_audit_e6_redirects_bytecode() -> None:
    print("\n== F79 the E6 compile redirects its bytecode cache ==")
    text = (WS / ".paper_test/test_focused_audit_2026_1009.py").read_text(encoding="utf-8")
    fn = text.split("def test_extract_citations_compiles_warning_free", 1)[1]
    fn = fn.split("\ndef ", 1)[0]
    check("F79 E6 sets PYTHONPYCACHEPREFIX for py_compile",
          "PYTHONPYCACHEPREFIX" in fn, fn[:300])
    check("F79 E6 asserts the audited tree is unchanged",
          "unchanged" in fn or "snapshot" in fn or "__pycache__" in fn, fn[:300])


# ---------------------------------------------------------------- F82
SWEEP_FILES = ("M1_acronyms.md", "M3_display_items.md", "M4_numbers.md",
               "M5_mandatory.md", "M6_hygiene.md", "M7_crossrefs.md",
               "M9_files.md", "M10_ref_format.md", "M11_si.md", "M12_authors.md",
               "M13_reporting.md", "M14_metadata.md", "M15_totals.md",
               "M16_abstract_trace.md", "M17_anomalies.md",
               "M21_correspondence.md", "M22_availability.md",
               "M23_supp_parity.md")
PARITY_FILES = ("M25_artwork_parity.md", "M2_references.md", "M26_conventions.md",
                "M27_evidence_coverage.md", "M28_symmetry.md", "M29_caption_schema.md",
                "M30_hierarchy_reconciliation.md", "M31_artwork_legend.md",
                "M32_statistics.md", "M33_availability.md",
                "M34_source_data_coverage.md", "M35_disclosures.md",
                "M36_zotero_parity.md")
ALL_REVIEW_CHECKS = [f"M{i}" for i in range(1, 37)] + [f"J{i}" for i in range(1, 6)]


def _review_sandbox(artifacts) -> tuple:
    sb = scratch("review") / "sb"
    (sb / "base").mkdir(parents=True)
    art = sb / "guided_review" / "artifacts"
    art.mkdir(parents=True)
    for name in artifacts:
        (art / name).write_text(f"# {name}\n\n| item | disposition |\n|---|---|\n"
                                f"| x | OK - checked |\n", encoding="utf-8")
    (sb / "guided_review" / "ARCHITECTURE.md").write_text(
        "| scope | disposition |\n|---|---|\n| whole | OK - order serves the reader |\n",
        encoding="utf-8")
    coverage = [{"check": cid, "disposition": "clean -- basis: locations"}
                for cid in ALL_REVIEW_CHECKS]
    fj = {"submission_dir": "./base", "coverage": coverage, "findings": []}
    errs, warns = [], []
    pp.check_review_contract(None, sb, fj, errs, warns)
    return errs, sb, fj


def test_review_sweep_artifacts_required() -> None:
    print("\n== F82 a clean sweep disposition needs its artifact ==")
    mapping = getattr(pp, "SWEEP_ARTIFACTS", None)
    check("F82 the pipeline defines the per-sweep artifact table",
          isinstance(mapping, dict) and mapping.get("M3") == "M3_display_items.md",
          mapping)
    errs, _sb, _fj = _review_sandbox(PARITY_FILES)
    check("F82 a clean M3 with no M3_display_items.md is refused",
          any("M3_display_items.md" in e for e in errs), errs[:3])
    if isinstance(mapping, dict):
        missing = sorted(set(mapping.values()) - set(PARITY_FILES))
        errs, _sb, _fj = _review_sandbox(PARITY_FILES + tuple(missing))
        check("F82 all mapped sweep artifacts present passes the artifact gate",
              not any("M3_display_items.md" in e for e in errs), errs[:3])


def main() -> int:
    test_cold_start_coverage_counts()
    test_j5_scope_documented()
    test_coverage_disposition_strictness()
    test_m8_artifact_name_parity()
    test_response_location_binding()
    test_repair_plan_binding()
    test_docs_consistency()
    test_focused_audit_e6_redirects_bytecode()
    test_review_sweep_artifacts_required()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL FIX-BUGS 2026-11-08 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup()

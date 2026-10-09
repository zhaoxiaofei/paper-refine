#!/usr/bin/env python3
"""Repro/regression tests for the 2026-10-09 round-2-sweep candidate set.

Run:  python3 .paper_test/test_round2_sweep_2026_1009.py

The candidates come from `audit_data/2026-1009-0810-round2-sweep-issues/`
(four independent model audits of the second sweep / discovery round). Two
classes survived re-validation on this tree; every check below FAILS on the
tree as ingested and PASSES once the matching defect is fixed, so this file is
both the repro script and the regression guard:

  R2-X  the prior-round reconciliation gate reads only prior_round/findings.json
        (`F-*`), so a discovery finding (`X-*`, prior_round/findings_extra.json)
        can vanish between rounds without failing the review;
  R2-D  the live skill/prompt documents still spell the frozen sweep set as
        "M1-M30" (and one appendix header as "M1-M35") although the checklist
        the same files require is M1-M36 + J1-J5.

`PAPER_WS` / `PAPER_SKILLS` retarget it at a baseline copy:

    PAPER_WS=/tmp/paper_baseline python3 .paper_test/test_round2_sweep_2026_1009.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

DEFAULT_WS = Path(__file__).resolve().parent.parent
WS = Path(os.environ.get("PAPER_WS") or DEFAULT_WS)
# Test the pack this repo vendors by default; PAPER_SKILLS still wins when a
# caller wants to point at one explicitly.
SKILLS = Path(os.environ.get("PAPER_SKILLS") or WS / "paper-skills")

spec = importlib.util.spec_from_file_location("paper_rep_r2s", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_rep_r2s"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name: str, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"r2s_{tag}_"))
    TMPDIRS.append(p)
    return p


def cleanup():
    for p in TMPDIRS:
        shutil.rmtree(p, ignore_errors=True)


# =====================================================================
# R2-X -- the prior-round gate reads BOTH frozen-finding namespaces
# =====================================================================

COVERAGE = ([{"check": c, "disposition": "clean -- basis: stub"}
             for c in list(nb.REQUIRED_REVIEW_CHECKS)
             + ["M18", "M19", "M20", "M21", "M22", "M23", "M24",
                "M25", "M26", "M27", "M28", "M29", "M30",
                "M31", "M32", "M33", "M34", "M35", "M36", "J5"]])


def review_contract_errors(tmp: Path, prior_f=(), prior_x=(), current_ids=(),
                           blob_extra="", with_x_file=True):
    """Errors from `check_review_contract` for one fabricated review sandbox.

    `prior_x` is written to prior_round/findings_extra.json (the discovery
    findings the previous round archived); leaving `with_x_file` False models a
    first-generation prior round that has no discovery findings at all.
    """
    sb = tmp / "sb"
    (sb / "base").mkdir(parents=True, exist_ok=True)
    (sb / "review").mkdir(parents=True, exist_ok=True)
    (sb / "prior_round").mkdir(parents=True, exist_ok=True)
    (sb / "prior_round" / "findings.json").write_text(
        json.dumps({"findings": [{"id": i} for i in prior_f]}), encoding="utf-8")
    if with_x_file or prior_x:
        (sb / "prior_round" / "findings_extra.json").write_text(
            json.dumps({"findings": [{"id": i} for i in prior_x]}), encoding="utf-8")
    cur = {"submission_dir": "./base",
           "findings": [{"id": i} for i in current_ids],
           "coverage": COVERAGE}
    (sb / "review" / "findings.json").write_text(json.dumps(cur), encoding="utf-8")
    (sb / "review" / "findings.md").write_text("# findings\n" + blob_extra, encoding="utf-8")
    (sb / "review" / "ARCHITECTURE.md").write_text(
        "| document | disposition |\n|---|---|\n| base | none |\n", encoding="utf-8")
    errs, warns = [], []
    nb.check_review_contract(None, sb, cur, errs, warns, scope="full")
    return [e for e in errs if "reconciled NOWHERE" in e]


def test_prior_x_reconciliation():
    print("\n== R2-X prior-round reconciliation covers the X-* namespace ==")
    # Control: the F-* half of the gate still fires (no regression).
    errs = review_contract_errors(tmpdir("x_ctrl"), prior_f=["F-001"])
    check("X-control: an unreconciled prior F-001 still fails the review",
          len(errs) == 1 and "F-001" in errs[0], str(errs)[:200])
    # The defect: a discovery finding that no later pass mentions.
    errs = review_contract_errors(tmpdir("x_gap"), prior_f=["F-001"], prior_x=["X-001"],
                                  current_ids=["F-100"],
                                  blob_extra="\ncarried over from F-001\n")
    check("X1: an unreconciled prior X-001 fails the review",
          len(errs) == 1 and "X-001" in errs[0], str(errs)[:200])
    # Reconciled by carrying it forward: no error.
    errs = review_contract_errors(tmpdir("x_carry"), prior_x=["X-001"], current_ids=["F-100"],
                                  blob_extra="\ncarried over from X-001\n")
    check("X2: an X-id carried forward satisfies the gate", not errs, str(errs)[:200])
    # Reconciled by recording it gone in findings.md: no error.
    errs = review_contract_errors(tmpdir("x_gone"), prior_x=["X-001"],
                                  blob_extra="prior X-001: not reproducible in base/\n")
    check("X3: an X-id recorded as not reproducible satisfies the gate",
          not errs, str(errs)[:200])
    # No prior discovery file at all: behaviour unchanged (nothing to reconcile).
    errs = review_contract_errors(tmpdir("x_none"), prior_f=["F-001"],
                                  current_ids=["F-100"],
                                  blob_extra="\ncarried over from F-001\n",
                                  with_x_file=False)
    check("X4: a prior round without findings_extra.json is unchanged",
          not errs, str(errs)[:200])
    # The prompt the reviewer reads must name the X namespace too, or a session
    # that follows it exactly would be failed for an omission it was not told
    # about.
    rule = " ".join(nb.PRIOR_ROUND_RULE.split())
    check("X5: the prior-round rule names prior_round/findings_extra.json in its "
          "re-check instruction",
          "re-check EVERY finding in prior_round/findings.json AND every discovery finding "
          "in prior_round/findings_extra.json against the current base/ corpus" in rule,
          rule[:220])


# =====================================================================
# R2-D -- the live documents state the frozen set the code enforces
# =====================================================================

LIVE_DOCS = {
    "paper-review/references/discovery.md":
        ["the standard review runs fixed sweeps M1–M36 and judgment passes"],
    "paper-review/SKILL.md":
        ["the EVIDENCE-INTEGRITY sweeps M31–M36",
         "the evidence-integrity sweeps M31–M36 (the seeded "
         "`review/artifacts/M31_artwork_legend.md`"],
    "paper-revise/SKILL.md": ["the M1–M36 sweeps from paper-review"],
    "paper-revise/references/ledger.md": ["(M1–M36 / J1–J5)"],
    "prompts/identify_issues.prompt.md":
        ["the standard review runs fixed sweeps M1–M36 and judgment passes",
         "## APPENDIX: Sweeps M1–M36 and judgment passes J1–J5",
         "the EVIDENCE-INTEGRITY sweeps M31–M36",
         "the evidence-integrity sweeps M31–M36 (the seeded "
         "`review/artifacts/M31_artwork_legend.md`"],
    "prompts/adress_issues.prompt.md":
        ["the M1–M36 sweeps from paper-review", "(M1–M36 / J1–J5)"],
    "README.md": ["M1–M36 + J1–J5 (source of truth)"],
}


def test_docs_state_the_current_range():
    print("\n== R2-D the skill documents name the frozen set the code enforces ==")
    stale = ("M1–M30", "M1-M30", "M1–M35", "M1-M35")
    for rel, must_have in LIVE_DOCS.items():
        p = SKILLS / rel
        text = p.read_text(encoding="utf-8")
        hits = [s for s in stale if s in text]
        check(f"D1 {rel} carries no stale sweep range", not hits, str(hits))
        for needle in must_have:
            check(f"D2 {rel} states {needle!r}", needle in text)
    # The review skill's acceptance item itself must name the adopted M31-M36 block
    # (a bare "M31-M36" elsewhere in the file would not fix the list the human reads).
    sk = (SKILLS / "paper-review/SKILL.md").read_text(encoding="utf-8")
    acc = sk[sk.find("## Acceptance checks"):]
    item1 = acc[acc.find("1. `findings.md` coverage table"):acc.find("2. Every sweep")]
    check("D3 paper-review/SKILL.md's acceptance item 1 reaches M36",
          "M31–M36" in item1 or "M21–M36" in item1, item1[:300])
    # The review prompt's coverage-table spec must reach M36 too.
    ip = (SKILLS / "prompts/identify_issues.prompt.md").read_text(encoding="utf-8")
    spec = ip[ip.find("5. Coverage table:"):][:400]
    check("D4 identify_issues.prompt.md's coverage-table spec reaches M36",
          "M31–M36" in spec or "M21–M36" in spec, spec[:300])
    # The review skill's own deliverables list mirrors that spec and must reach
    # M36 as well (the prompt half alone left the two documents disagreeing).
    sk_spec = sk[sk.find("5. Coverage table:"):][:400]
    check("D5 paper-review/SKILL.md's coverage-table spec reaches M36",
          "M31–M36" in sk_spec or "M21–M36" in sk_spec, sk_spec[:300])


def main():
    test_prior_x_reconciliation()
    test_docs_state_the_current_range()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL ROUND-2-SWEEP CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup()

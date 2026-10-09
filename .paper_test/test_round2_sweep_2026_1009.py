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

The audit folder also carried FEATURE requests (gating the D0-D5 phase,
machine-checking D0's dedup rule, attacking probe dispositions, re-probing the
previous round's proposals, adopting proposals by command). Their checks live
in R2-C/R2-E/R2-A below, added with the implementation:

  R2-C  the discovery round's D0-D5 deliverables are verified as a contract
        (>=25 disposed gap rows, a probe or recorded limitation per uncovered
        row, an executed disposition per probe, sweeps.md-shaped proposals
        from M37 or an explicit no-proposal statement, honest-limits summary);
  R2-P  the previous round's proposals are re-probed (or explicitly
        dispositioned) in the current round's round-2 artifacts;
  R2-XD F/X cross-namespace duplicates get a mechanical audit trail;
  R2-PA the auditor attacks the discovery round's probe dispositions
        (audit/PROBE_AUDIT.md, one row per probe);
  R2-A  `adopt-sweep` validates proposals and (with --yes) appends them to
        sweeps.md, re-syncing the standalone prompt's appendix.

`PAPER_WS` / `PAPER_SKILLS` retarget it at a baseline copy:

    PAPER_WS=/tmp/paper_baseline python3 .paper_test/test_round2_sweep_2026_1009.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
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


# =====================================================================
# R2-C -- the discovery round's D0-D5 deliverables are a contract
# =====================================================================

def _gap_table(n=25, uncovered=2):
    return ("# D1 (fixture)\n\n| # | gap row | coverage |\n|---|---|---|\n"
            + "\n".join(f"| {i} | class {i} | "
                        + ("UNCOVERED" if i > n - uncovered else "COVERED (M1)") + " |"
                        for i in range(1, n + 1)) + "\n")


def _round2(sb: Path, **overrides):
    """Write a conformant review/round2/ fixture into `sb` (None deletes a file)."""
    r2 = sb / "review/round2"
    r2.mkdir(parents=True, exist_ok=True)
    files = {
        "known_index.md": "# D0 (fixture)\n\nKNOWN-CLASSES: M1 ... M36, J1 ... J5\n",
        "gap_table.md": _gap_table(),
        "probes.md": ("# D2 (fixture)\n\n| probe id | gap row | status |\n|---|---|---|\n"
                      "| P2-001 | 24 | executed |\n| P2-002 | 25 | executed |\n"),
        "probe_results.md": ("# D3 (fixture)\n\n| probe id | disposition |\n|---|---|\n"
                             "| P2-001 | executed - no anomalies - checked: base/x |\n"
                             "| P2-002 | executed - no anomalies - checked: base/x |\n"),
        "findings_extra.json": json.dumps({"findings": [], "coverage": []}),
        "findings_extra.md": "# D4 (fixture)\n",
        "new_sweeps.md": "# D5 (fixture)\n\nNo new sweep proposals: nothing recurred.\n",
        "round2_summary.md": ("# Summary (fixture)\n\nGap rows: 25 (23 covered, 2 uncovered). "
                              "Probes: 2 executed (2 clean). X-findings: none. Proposed sweeps: "
                              "none.\nHonest limits: fixture only.\n"),
    }
    files.update(overrides)
    for name, text in files.items():
        p = r2 / name
        if text is None:
            if p.exists():
                p.unlink()
        else:
            p.write_text(text, encoding="utf-8")
    return sb


def discovery_errors(sb):
    errs, _warns = nb.discovery_contract_problems(sb)
    return errs


def test_discovery_contract():
    print("\n== R2-C the discovery round's D0-D5 deliverables are a contract ==")
    sb = _round2(tmpdir("dc_ok") / "sb")
    check("C1 a conformant discovery round passes", not discovery_errors(sb),
          str(discovery_errors(sb))[:240])
    sb = _round2(tmpdir("dc_ok_pad") / "sb",
                 **{"known_index.md": "# D0 (fixture)\n\nKNOWN-CLASSES: M01 ... M36, J01 ... J05\n"})
    check("C1b zero-padded M01/J05 spellings are accepted",
          not discovery_errors(sb), str(discovery_errors(sb))[:240])

    sb = _round2(tmpdir("dc_missing") / "sb", **{"gap_table.md": None})
    errs = discovery_errors(sb)
    check("C2 a missing deliverable fails and is named",
          len(errs) == 1 and "gap_table.md" in errs[0], str(errs)[:240])

    sb = _round2(tmpdir("dc_small") / "sb", **{"gap_table.md": _gap_table(n=10)})
    check("C3 fewer than 25 gap rows fail",
          any("at least 25" in e for e in discovery_errors(sb)),
          str(discovery_errors(sb))[:240])

    sb = _round2(tmpdir("dc_covered") / "sb", **{"gap_table.md": _gap_table(n=25, uncovered=0)})
    check("C4 a gap table with no UNCOVERED row fails",
          any("found no uncovered class" in e for e in discovery_errors(sb)),
          str(discovery_errors(sb))[:240])

    sb = _round2(tmpdir("dc_probe_short") / "sb",
                 **{"probes.md": "# D2 (fixture)\n\n| probe id | gap row | status |\n|---|---|---|\n"
                                  "| P2-001 | 24 | executed |\n"})
    check("C5 an uncovered row without a probe/limitation fails",
          any("UNCOVERED gap row(s)" in e for e in discovery_errors(sb)),
          str(discovery_errors(sb))[:240])

    sb = _round2(tmpdir("dc_pending") / "sb",
                 **{"probe_results.md": "# D3 (fixture)\n\n| probe id | disposition |\n|---|---|\n"
                                        "| P2-001 | pending |\n| P2-002 | pending |\n"})
    errs = discovery_errors(sb)
    check("C6 a still-pending probe result fails", any("still `pending`" in e for e in errs),
          str(errs)[:240])

    sb = _round2(tmpdir("dc_nocheck") / "sb",
                 **{"probe_results.md": "# D3 (fixture)\n\n| probe id | disposition |\n|---|---|\n"
                                        "| P2-001 | executed - no anomalies |\n"
                                        "| P2-002 | executed - no anomalies |\n"})
    check("C7 'no anomalies' without checked locations fails",
          any("without naming the checked locations" in e for e in discovery_errors(sb)),
          str(discovery_errors(sb))[:240])

    sb = _round2(tmpdir("dc_none") / "sb", **{"new_sweeps.md": "# none\n"})
    check("C8 a placeholder new_sweeps.md fails",
          any("does not state" in e for e in discovery_errors(sb)),
          str(discovery_errors(sb))[:240])

    sb = _round2(tmpdir("dc_floor") / "sb",
                 **{"new_sweeps.md": "# D5 (fixture)\n\n## M36 — Late proposal (proposed)\n"
                                     "**Purpose:** x\n**Enumeration:** y\n**Artifact:** z\n"
                                     "**Finding rules:** w\n"})
    errs = discovery_errors(sb)
    check("C9 a proposal below the M37 floor fails",
          any("below the numbering floor" in e for e in errs), str(errs)[:240])

    bad_x = json.dumps({"findings": [{"id": "X-001", "location": "base/x", "category": 2,
                                      "check": "checklist gap", "severity": "Medium",
                                      "evidence": "e", "explanation": "x"}]})
    sb = _round2(tmpdir("dc_x") / "sb")
    (sb / "review/round2/findings_extra.json").write_text(bad_x, encoding="utf-8")
    errs = discovery_errors(sb)
    check("C10 a malformed X-finding fails",
          any("malformed X-finding" in e and "severity" in e for e in errs), str(errs)[:240])

    # the strict-artifacts policy: fail by default, warn when the operator
    # turns the policy off (the decision still gates via the residual report)
    class _Ctx:
        def __init__(self, policy):
            self.cfg = {"artifact_policy": policy}

    sb = _round2(tmpdir("dc_policy") / "sb", **{"gap_table.md": _gap_table(n=10)})
    errs, warns = [], []
    nb.check_discovery_contract(_Ctx("on"), sb, errs, warns)
    check("C11 the strict policy fails the run",
          any("discovery round:" in e for e in errs) and not warns, str(errs)[:240])
    errs, warns = [], []
    nb.check_discovery_contract(_Ctx("off"), sb, errs, warns)
    check("C12 the non-strict policy records warnings only",
          not errs and any("discovery round:" in w for w in warns), str(warns)[:240])


# =====================================================================
# R2-P -- prior proposals must be re-probed (the convergence loop)
# =====================================================================

def test_prior_proposals_reprobed():
    print("\n== R2-P the previous round's proposals are re-probed ==")
    sb = _round2(tmpdir("pp") / "sb")
    (sb / "prior_round").mkdir(parents=True, exist_ok=True)
    (sb / "prior_round/new_sweeps.md").write_text(
        "# prior\n\n## M37 — Figure resolution (proposed)\n**Purpose:** x\n", encoding="utf-8")
    check("P1 a prior proposal re-checked nowhere fails",
          any("re-checks NOWHERE" in e and "M37" in e for e in discovery_errors(sb)),
          str(discovery_errors(sb))[:240])
    (sb / "review/round2/probes.md").write_text(
        "# D2 (fixture)\n\n| probe id | gap row | question | evidence | status |\n"
        "|---|---|---|---|---|\n"
        "| P2-001 | 24 | prior proposal M37: figure resolution | base/x | executed |\n"
        "| P2-002 | 25 | class 25 | base/x | executed |\n", encoding="utf-8")
    check("P2 a prior proposal re-probed passes",
          not any("re-checks NOWHERE" in e for e in discovery_errors(sb)),
          str(discovery_errors(sb))[:240])
    (sb / "prior_round/new_sweeps.md").write_text(
        "# prior\n\n## M38 — Another class (proposed)\n**Purpose:** x\n", encoding="utf-8")
    (sb / "review/round2/new_sweeps.md").write_text(
        "# D5 (fixture)\n\nNo new sweep proposals: prior proposal M38: no instances in base/.\n",
        encoding="utf-8")
    check("P3 a prior proposal dispositioned as not-reproducible passes",
          not any("re-checks NOWHERE" in e for e in discovery_errors(sb)),
          str(discovery_errors(sb))[:240])


# =====================================================================
# R2-XD -- F/X cross-namespace duplicates get a mechanical audit trail
# =====================================================================

def test_cross_namespace_duplicates():
    print("\n== R2-XD F/X cross-namespace duplicates get a mechanical trail ==")
    sb = _round2(tmpdir("xd") / "sb")
    quote = "line 42 of the manuscript: the treated group showed a higher median value"
    (sb / "review/round2/findings_extra.json").write_text(json.dumps({"findings": [
        {"id": "X-001", "location": "base/m.md", "category": 0, "check": "M30",
         "severity": "Major", "evidence": quote, "explanation": "x"}]}), encoding="utf-8")
    fj = {"findings": [{"id": "F-012", "location": "base/m.md", "category": 0, "check": "M30",
                        "severity": "Major", "evidence": quote, "explanation": "y"}]}
    notes = nb.cross_namespace_duplicate_notes(sb, fj)
    check("XD1 an X row restating an F row is reported",
          len(notes) == 1 and "X-001" in notes[0] and "F-012" in notes[0], str(notes)[:240])
    fj2 = {"findings": [dict(fj["findings"][0], evidence=(
        "line 42 of the manuscript: a completely different subject entirely"))]}
    check("XD2 a same-line different-substance row is not reported",
          nb.cross_namespace_duplicate_notes(sb, fj2) == [],
          str(nb.cross_namespace_duplicate_notes(sb, fj2))[:240])
    # A different CLASS at the same place is a different defect: D0's key is
    # "same class + same location + same substance", and the audit compared a
    # literal "X" against a literal "X" -- so it told the session to drop a
    # legitimate X row that merely shared a line with an unrelated F row.
    fj3 = {"findings": [dict(fj["findings"][0], check="M1")]}
    check("XD3 a different class at the same place is not reported",
          nb.cross_namespace_duplicate_notes(sb, fj3) == [],
          str(nb.cross_namespace_duplicate_notes(sb, fj3))[:240])
    # The finding format spells a location as a section/paragraph reference just
    # as often as a `line N`; without the location-cell fallback the census key
    # alone left the audit inert for those rows.
    plain = dict(fj["findings"][0], location="Results, paragraph 2",
                 evidence="the treated group showed a higher median value")
    (sb / "review/round2/findings_extra.json").write_text(json.dumps({"findings": [
        dict(plain, id="X-001", explanation="x")]}), encoding="utf-8")
    notes = nb.cross_namespace_duplicate_notes(sb, {"findings": [dict(plain, id="F-012")]})
    check("XD4 a same-location/same-substance pair without a line number is reported",
          len(notes) == 1 and "X-001" in notes[0], str(notes)[:240])


# =====================================================================
# R2-PA -- the auditor attacks the discovery probe dispositions
# =====================================================================

def test_probe_audit():
    print("\n== R2-PA the auditor attacks the discovery probe dispositions ==")
    sb = tmpdir("pa") / "sb"
    (sb / "review/round2").mkdir(parents=True)
    (sb / "review/round2/probe_results.md").write_text(
        "# D3 (fixture)\n\n| probe id | disposition |\n|---|---|\n"
        "| P2-001 | executed - no anomalies - checked: base/x |\n", encoding="utf-8")
    errs = nb.probe_audit_problems(sb)
    check("PA1 a probe result without PROBE_AUDIT.md fails",
          len(errs) == 1 and "PROBE_AUDIT.md" in errs[0], str(errs)[:240])
    (sb / "audit").mkdir()
    (sb / "audit/PROBE_AUDIT.md").write_text(
        "| probe id | disposition | verdict | evidence |\n|---|---|---|---|\n"
        "| P2-001 | no anomalies | promoted to AU-001 | the metadata holds the rule |\n",
        encoding="utf-8")
    (sb / "audit/audit.json").write_text(json.dumps({"adds": []}), encoding="utf-8")
    errs = nb.probe_audit_problems(sb)
    check("PA2 a promotion naming no AU-* finding fails",
          any("AU-001" in e for e in errs), str(errs)[:240])
    (sb / "audit/audit.json").write_text(json.dumps({"adds": [{"id": "AU-001"}]}),
                                         encoding="utf-8")
    check("PA3 a full PROBE_AUDIT passes", nb.probe_audit_problems(sb) == [],
          str(nb.probe_audit_problems(sb))[:240])


# =====================================================================
# R2-A -- adopt-sweep validates and appends proposals
# =====================================================================

GOOD_PROPOSAL = """# New sweeps

## M37 — Figure resolution and portability (proposed)
**Purpose:** a figure under the venue's print resolution.
**Enumeration:** parse the image density and the displayed extent.
**Artifact:** M37_figure_resolution.md: file | pixels | dpi | disposition.
**Finding rules:** one finding per figure under the minimum.
"""


def test_adopt_sweep():
    print("\n== R2-A adopt-sweep validates and appends proposals ==")
    proposals, problems = nb.parse_sweep_proposals(GOOD_PROPOSAL)
    check("A1 a sweeps.md-shaped proposal parses",
          len(proposals) == 1 and proposals[0][0] == "M37" and not problems,
          str(problems)[:240])
    _p2, problems2 = nb.parse_sweep_proposals(
        "# x\n\n## M36 — too late (proposed)\n**Purpose:** x\n**Enumeration:** y\n"
        "**Artifact:** z\n**Finding rules:** w\n")
    check("A2 a below-floor proposal is refused",
          any("below the numbering floor" in p for p in problems2), str(problems2)[:240])
    _p3, problems3 = nb.parse_sweep_proposals(
        "# x\n\n## M37 — named (proposed)\n**Purpose:** x\n")
    check("A3 a proposal missing template fields is refused",
          any("no `enumeration` field" in p for p in problems3), str(problems3)[:240])
    target = "# Sweeps (fixture)\n\n## M36 — last adopted\n**Purpose:** x\n"
    check("A4 a proposal that does not continue the numbering is refused",
          any("does not continue" in p for p in
              nb.adopt_sweep_problems([("M35", "x", "## M35 — x\n")], target)), "")
    check("A4b a proposal colliding with an existing id is refused",
          any("already exists" in p for p in
              nb.adopt_sweep_problems([("M36", "x", "## M36 — x\n")], target)), "")
    tmp = tmpdir("adopt")
    sk = tmp / "sk"
    (sk / "paper-review/references").mkdir(parents=True)
    (sk / "prompts").mkdir(parents=True)
    sweeps = sk / "paper-review/references/sweeps.md"
    sweeps.write_text(target, encoding="utf-8")
    prompt = sk / "prompts/identify_issues.prompt.md"
    prompt.write_text("# Identify\n\n## APPENDIX: Sweeps M1–M36\n\nOLD\n\n"
                      "## APPENDIX: Discovery round D0–D5\n\nDiscovery.\n", encoding="utf-8")
    prop = tmp / "new_sweeps.md"
    prop.write_text(GOOD_PROPOSAL, encoding="utf-8")
    base_cmd = [sys.executable, str(WS / "paper_pipeline.py"), "adopt-sweep",
                "--proposals", str(prop), "--sweeps", str(sweeps)]
    run = subprocess.run(base_cmd, capture_output=True, text=True)
    check("A5 the default is a dry run",
          run.returncode == 0 and "dry run" in run.stdout
          and "## M37" not in sweeps.read_text(encoding="utf-8"), run.stdout[-240:])
    run = subprocess.run(base_cmd + ["--yes"], capture_output=True, text=True)
    text = sweeps.read_text(encoding="utf-8")
    check("A6 --yes appends the proposal without '(proposed)'",
          run.returncode == 0 and "## M37 — Figure resolution and portability" in text
          and "(proposed)" not in text, run.stdout[-240:])
    lines = prompt.read_text(encoding="utf-8").split("\n")
    start = next(i + 1 for i, ln in enumerate(lines) if ln.startswith("## APPENDIX: Sweeps"))
    stop = next(i for i, ln in enumerate(lines) if ln.startswith("## APPENDIX: Discovery"))
    check("A7 the standalone prompt's appendix is re-synced",
          "\n".join(lines[start:stop]).strip() == text.strip(),
          "\n".join(lines[start:stop])[:240])
    bad = tmp / "bad.md"
    bad.write_text("# x\n\n## M36 — late (proposed)\n**Purpose:** x\n", encoding="utf-8")
    run = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "adopt-sweep",
                          "--proposals", str(bad), "--sweeps", str(sweeps), "--yes"],
                         capture_output=True, text=True)
    check("A8 a refused proposal leaves sweeps.md byte-identical",
          run.returncode != 0 and sweeps.read_text(encoding="utf-8") == text,
          run.stdout[-240:])


def main():
    test_prior_x_reconciliation()
    test_docs_state_the_current_range()
    test_discovery_contract()
    test_prior_proposals_reprobed()
    test_cross_namespace_duplicates()
    test_probe_audit()
    test_adopt_sweep()
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

#!/usr/bin/env python3
"""Regression checks for the 2026-11-06 verified fixes.

Run:  python3 .paper_test/test_fix_bugs_20261106.py

Each block pins one confirmed defect on the current tree:

  * the judge prompt said "the first tier in which the two versions differ
    decides" while the same prompt's formula takes the first tier whose NET is
    not zero -- a net-zero higher tier would have been read as deciding;
  * the revise prompt invited a reviser to re-open an audited-and-dropped
    finding, which would be filing and applying a new finding in one run
    (AGENTS.md rule 1A);
  * the cold-start prompt never stated the hard verifier budget (50 scripts /
    600 s aggregate) that its postcheck enforces, so a valid 51-script attempt
    failed after the fact;
  * the bounded-repair plan required a non-empty `correct`, so a confirmed pure
    DELETION could not be represented although the repair ledger and span audit
    support an empty postimage;
  * the self-check command interpolated the driver path inside double quotes,
    where a legal `$` or backtick is expanded by the shell;
  * medium's paged rules are written to one fixed path, so the revision audit
    and bounded repair (which run in the revise sandbox) overwrote the
    reviser's nine sections while its PROMPT.md still pointed at the file.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
if str(WS) not in sys.path:
    sys.path.insert(0, str(WS))

import paper_pipeline as pp  # noqa: E402

FAILS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"[ok ] {name}")
    else:
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))
        FAILS.append(name)


def flat(value: str) -> str:
    return " ".join(str(value or "").split())


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


# ---------------------------------------------------------------------------
# 1. The judge's priority prose agrees with its own net-zero formula.
# ---------------------------------------------------------------------------
def test_judge_priority_uses_net_difference() -> None:
    print()
    print("== judge: the deciding tier is the first with a NON-ZERO NET ==")
    sb = scratch("jnet_")
    judge = flat(pp.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, []))
    check("judge: the priority sentence says NET difference",
          "the first tier whose NET difference is not zero decides the comparison" in judge,
          judge[:120])
    check("judge: the stale 'differ...decides' sentence is gone",
          "the first tier in which the two versions differ decides" not in judge)
    check("judge: the formula's net-zero rule is still stated",
          "the FIRST tier whose net is not zero DECIDES the comparison" in judge)
    # The basis field must keep the net-zero row exception: for a 0, the basis
    # names the highest tier that carries rows.
    check("judge: a net-zero comparison still names its row-bearing tier",
          "for a clean 0" in judge and "tier in which the two versions differ at all" in judge)


# ---------------------------------------------------------------------------
# 2. A dropped finding is not re-opened and patched by the reviser.
# ---------------------------------------------------------------------------
def test_reviser_does_not_reopen_dropped_findings() -> None:
    print()
    print("== revise: a dropped finding is routed to the next review, not patched ==")
    sb = scratch("rreopen_")
    prompt = flat(pp.revise_prompt(sb, "r1_a2_revise", 1, audit=True))
    check("revise: the audited-list rule still forbids re-litigation",
          "a dropped finding is NOT yours to re-litigate" in prompt)
    check("revise: the old re-opening permission is gone",
          "re-opening one requires new evidence" not in prompt)
    check("revise: the next-review route cites rule 1A",
          "rule 1A" in prompt and "NEXT round's review" in prompt)
    check("revise: the observation route is still stated",
          "audit/UNRESOLVED.md" in prompt and "observation for the" in prompt)


# ---------------------------------------------------------------------------
# 3. The cold-start prompt states the verifier budget its postcheck enforces.
# ---------------------------------------------------------------------------
def test_cold_start_verifier_budget_is_stated() -> None:
    print()
    print("== cold start: the prompt states the hard verifier budget ==")
    sb = scratch("cbudget_")
    prompt = flat(pp.cold_start_review_prompt(sb, "r1_cold_start_review", 1))
    check("cold start: the maximum number of verifiers is stated",
          f"at most {pp.COLD_START_REPRO_MAX_VERIFIERS} declared verifiers" in prompt,
          prompt[:160])
    check("cold start: the aggregate seconds budget is stated",
          f"{pp.COLD_START_REPRO_TOTAL_BUDGET} s" in prompt)
    check("cold start: the unrun verifier's failure is stated",
          "did not run FAILS the attempt" in prompt)
    # The numbers in the prompt must come from the same constants the postcheck
    # uses; a hard-coded copy would drift.
    check("cold start: the budgets are interpolated, not copied",
          str(pp.COLD_START_REPRO_MAX_VERIFIERS) in prompt
          and str(pp.COLD_START_REPRO_TOTAL_BUDGET) in prompt)


# ---------------------------------------------------------------------------
# 4. A bounded-repair plan can represent a pure deletion.
# ---------------------------------------------------------------------------
def _plan(sb: Path, rows: list) -> None:
    (sb / "revision_audit").mkdir(parents=True, exist_ok=True)
    (sb / "revised").mkdir(parents=True, exist_ok=True)
    (sb / "revision_audit" / "REPAIR_PLAN.json").write_text(
        json.dumps({"rows": rows}), encoding="utf-8")


def _row(**over) -> dict:
    row = {"id": "RP-001", "finding": "F-001", "file": "paper.md",
           "location": "Results, paragraph 3", "wrong": "the duplicated sentence",
           "correct": "the corrected sentence", "basis": "paper.md:12",
           "edit": "replace the duplicated sentence", "evidence": "the quote"}
    row.update(over)
    return row


def test_repair_plan_accepts_pure_deletion() -> None:
    print()
    print("== revision audit: REPAIR_PLAN represents a pure deletion ==")
    sb = scratch("rplan_")
    _plan(sb, [_row(correct="", edit="delete the duplicated sentence")])
    rows = pp._revision_plan_rows(sb)
    check("plan: a pure deletion (empty correct, quoted wrong) is valid",
          isinstance(rows, list) and len(rows) == 1 and rows[0]["correct"] == "",
          str(rows)[:200])

    _plan(sb, [_row(wrong="", edit="insert the missing sentence")])
    check("plan: a pure insertion (empty wrong) is still valid",
          isinstance(pp._revision_plan_rows(sb), list))

    _plan(sb, [_row(wrong="", correct="", edit="nothing to quote")])
    check("plan: a row with neither wrong nor correct is rejected",
          pp._revision_plan_rows(sb) is None)

    _plan(sb, [_row(correct="", basis="")])
    check("plan: an empty basis still invalidates the plan",
          pp._revision_plan_rows(sb) is None)

    prompt = flat(pp.revision_audit_prompt(scratch("rprompt_"), "r1_revision_audit", 1))
    check("plan: the auditor prompt documents the pure-deletion shape",
          "A PURE DELETION" in prompt and '"correct": ""' in prompt)


# ---------------------------------------------------------------------------
# 5. The self-check command is shell-quoted, not double-quoted.
# ---------------------------------------------------------------------------
def test_selfcheck_command_is_shell_quoted() -> None:
    print()
    print("== self-check: the frozen driver's path is shell-quoted ==")
    real, real_fb = pp.pipeline_self_path, pp.pipeline_fallback_paths
    # A legal root path may carry `$` or a backtick. Inside double quotes the
    # shell expands them; the command must quote for the shell, not for prose.
    dangerous = "/tmp/paper-check-$PAPER_SELF_DIR/paper_pipeline.py"
    try:
        pp.pipeline_self_path = lambda: Path(dangerous)
        pp.pipeline_fallback_paths = lambda: []
        block = pp.selfcheck_block("revise", "r1_a2_revise", 1)
    finally:
        pp.pipeline_self_path, pp.pipeline_fallback_paths = real, real_fb
    m = re.search(r"(?m)^\s+python (.*?) selfcheck --sandbox", block)
    token = m.group(1) if m else ""
    check("selfcheck: the command names the path", bool(token), block[:160])
    env = dict(os.environ, PAPER_SELF_DIR="EXPANDED")
    got = subprocess.run(["bash", "-c", f"printf '%s' {token}"],
                         capture_output=True, text=True, env=env)
    check("selfcheck: a literal `$` in the path is not expanded by the shell",
          got.returncode == 0 and got.stdout == dangerous,
          f"{got.stdout!r} != {dangerous!r}")
    check("selfcheck: the path is not merely double-quoted",
          f'python "{dangerous}"' not in block)

    # The judge pre-flight carries the same command and must be quoted too.
    try:
        pp.pipeline_self_path = lambda: Path(dangerous)
        pp.pipeline_fallback_paths = lambda: []
        judge = pp.judge_selfcheck_block("judge_x_j1")
    finally:
        pp.pipeline_self_path, pp.pipeline_fallback_paths = real, real_fb
    m = re.search(r"(?m)^\s+python (.*?) selfcheck --sandbox", judge)
    token = m.group(1) if m else ""
    got = subprocess.run(["bash", "-c", f"printf '%s' {token}"],
                         capture_output=True, text=True, env=env)
    check("selfcheck: the judge's pre-flight is quoted the same way",
          token and got.returncode == 0 and got.stdout == dangerous,
          f"{got.stdout!r}")


# ---------------------------------------------------------------------------
# 6. Medium's paged rules are per-stage when auxiliary sessions share a sandbox.
# ---------------------------------------------------------------------------
def test_medium_auxiliary_sidecar_does_not_overwrite_reviser() -> None:
    print()
    print("== medium: the audit/repair sidecars leave the reviser's rules intact ==")
    sb = scratch("rsidecar_") / "r1_a2_revise"
    sb.mkdir(parents=True)
    pp.revise_prompt(sb, "r1_a2_revise", 1, audit=True, execution_profile="medium")
    reviser_file = sb / "INSTRUCTIONS" / "PROFILE_RULES.md"
    before = reviser_file.read_text(encoding="utf-8")
    check("sidecar: the reviser's paged file is the documented path",
          reviser_file.is_file() and "_Stage: revise_" in before)
    sections = before.count("\n## ")

    audit = pp.revision_audit_prompt(sb, "r1_revision_audit", 1,
                                     execution_profile="medium")
    after = reviser_file.read_text(encoding="utf-8")
    audit_sidecar = sb / "INSTRUCTIONS" / "PROFILE_RULES_revision_audit.md"
    check("sidecar: the audit does not shorten the reviser's file",
          re.sub(r"\s+", " ", after) == re.sub(r"\s+", " ", before)
          and after.count("\n## ") == sections, f"{sections} -> {after.count(chr(10)+'## ')}")
    check("sidecar: the audit gets its own stage-named file",
          audit_sidecar.is_file() and "_Stage: revision_audit_" in
          audit_sidecar.read_text(encoding="utf-8"))
    check("sidecar: the audit prompt points at its own file",
          "PROFILE_RULES_revision_audit.md" in audit
          and "INSTRUCTIONS/PROFILE_RULES.md" not in audit)

    pp.revision_repair_prompt(sb, "r1_revision_repair", 1, 1,
                              execution_profile="medium")
    repair_sidecar = sb / "INSTRUCTIONS" / "PROFILE_RULES_revision_repair.md"
    check("sidecar: the bounded repair gets its own stage-named file",
          repair_sidecar.is_file()
          and "_Stage: revision_repair_" in repair_sidecar.read_text(encoding="utf-8"))
    check("sidecar: the reviser's file survives both auxiliary prompts",
          reviser_file.read_text(encoding="utf-8").count("\n## ") == sections)


if __name__ == "__main__":
    test_judge_priority_uses_net_difference()
    test_reviser_does_not_reopen_dropped_findings()
    test_cold_start_verifier_budget_is_stated()
    test_repair_plan_accepts_pure_deletion()
    test_selfcheck_command_is_shell_quoted()
    test_medium_auxiliary_sidecar_does_not_overwrite_reviser()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): " + ", ".join(FAILS))
        sys.exit(1)
    print("ALL 2026-11-06 FIX CHECKS PASSED")

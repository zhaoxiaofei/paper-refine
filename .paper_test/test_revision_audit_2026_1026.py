#!/usr/bin/env python3
"""Revision audit and bounded repair: the post-revise chain.

Run:  python3 .paper_test/test_revision_audit_2026_1026.py

The general round is:
  review → findings → audit (no new findings; the review auditor only disposes)
  → revise (re-validating every finding) → revised version
  → revision audit (no new revisions; it writes a bounded-repair plan only)
  → bounded repair (only when the plan is non-empty; re-validating every row)
  → each arm's pre-integration revised version → integration / judge / decision.

The two auditors are optional: `--audit off` skips the review audit, and
`PAPER_REVISION_AUDIT=off` skips the revision audit (the revised version is then
final). The suite pins the prompts, the skip, the empty-plan path and the
one-row repair path against the repo's stub agent.
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

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
STUB = WS / ".paper_test" / "stub_agent.py"
FAILS: list[str] = []
TMPDIRS: list[Path] = []


def check(name: str, cond: bool, detail: str = "") -> None:
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


def run(args, *, env=None, **kw):
    merged = os.environ.copy()
    merged.pop("PAPER_REVISION_AUDIT", None)
    merged.pop("PAPER_STUB_REVISION_AUDIT_ROWS", None)
    merged.update(env or {})
    return subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), *args],
        capture_output=True, text=True, timeout=1200, env=merged, **kw)


def make_source(tmp: Path) -> Path:
    src = tmp / "source"
    src.mkdir(parents=True)
    (src / "manuscript-o.md").write_text(
        "# Title\n\nA stub manuscript for the revision-audit test.\n", encoding="utf-8")
    return src


def setup_and_run(prefix: str, *, env=None):
    tmp = scratch(prefix)
    src = make_source(tmp)
    root = tmp / "root"
    r = run(["setup", "--source", str(src), "--root", str(root), "--rounds", "1",
             "--judges", "1", "--rewrites", "0", "--revises", "1", "--integrators", "0"], env=env)
    if r.returncode != 0:
        return tmp, root, r
    r = run(["run", "--root", str(root), "--agent-cmd",
             json.dumps([sys.executable, str(STUB)]), "--retries", "0"], env=env)
    return tmp, root, r


def revive(sb: Path) -> dict:
    state = json.loads((sb.parent.parent / "state.json").read_text(encoding="utf-8"))
    return state["runs"].get("r1_a2_revise") or {}


def test_prompts():
    print("\n== the prompts state the strategy ==")
    pp = load("rev_audit_pipeline", WS / "paper_pipeline.py")
    tmp = scratch("rev_audit_prompt_")
    sb = tmp / "sandbox"
    sb.mkdir()
    audit = pp.audit_prompt(sb, "r1_audit", 1)
    check("the review audit adds no findings", "THIS AUDIT ADDS NO FINDINGS" in audit)
    check("the review audit requires adds=[]", "`adds` MUST be `[]`" in audit)
    check("unresolved observations have their own file", "audit/UNRESOLVED.md" in audit)
    revise = pp.revise_prompt(sb, "r1_a2_revise", 1)
    check("the reviser re-validates every finding", "RE-VALIDATE IT" in revise)
    check("a rejected finding is recorded, not applied",
          "revalidated: rejected" in revise and "unable — <reason>" in revise)
    ra = pp.revision_audit_prompt(sb, "r1_a2_revise", 1)
    check("the revision audit writes only the plan", "write only the BOUNDED-REPAIR PLAN" in ra.lower() or
          "BOUNDED-REPAIR PLAN" in ra)
    check("the revision audit never edits", "you do NOT edit the manuscript" in ra)
    check("the plan schema is named", "RP-001" in ra and "REPAIR_PLAN.json" in ra)
    check("the revision audit reads the merged probe list, not a missing directory",
          "cold_start_review/" not in ra and "guided_review/round2/findings_extra.json" in ra)
    rr = pp.revision_repair_prompt(sb, "r1_a2_revise", 1, 2)
    check("the repair re-validates every row", "RE-VALIDATE EVERY PLANNED REPAIR" in rr)
    check("the repair applies only confirmed rows", "Apply only `confirmed` rows" in rr)
    check("the repair is one pass", "ONE pass" in rr)
    check("the repair names the readme-mode hand-off destination",
          "README-AUTHOR-TO-COMPLETE.md" in rr)


def test_chain_guards():
    print("\n== the chain's guards (plan shape, ledger, bookkeeping) ==")
    pp = load("rev_audit_guards", WS / "paper_pipeline.py")
    sb = scratch("rev_audit_guards_") / "sb"
    (sb / "revised").mkdir(parents=True)
    plan_dir = sb / "revision_audit"
    plan_dir.mkdir()

    def write_plan(rows):
        (plan_dir / "REPAIR_PLAN.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")

    def full_row(**over):
        row = {"id": "RP-001", "file": "manuscript.md",
               "location": "Results, paragraph 3", "wrong": "n = 12",
               "correct": "n = 13", "basis": "raw_data/table1.csv row 2",
               "edit": "replace n = 12 with n = 13",
               "evidence": "guided_review/findings.json F-001"}
        row.update(over)
        return row

    write_plan([{"id": "RP-001", "file": "manuscript.md"}])
    check("a plan row with no described repair invalidates the plan",
          pp._revision_plan_rows(sb) is None)
    write_plan([full_row()])
    rows = pp._revision_plan_rows(sb)
    check("a well-formed plan is accepted", rows and rows[0]["id"] == "RP-001", str(rows))
    write_plan([full_row(),
                full_row(id="RP-001", file="other.md")])
    check("a duplicate plan id invalidates the plan", pp._revision_plan_rows(sb) is None)
    write_plan([full_row(file="../base/manuscript.md")])
    check("a plan row outside the package invalidates the plan",
          pp._revision_plan_rows(sb) is None)
    write_plan([full_row(file="")])
    check("a plan row without a file invalidates the plan",
          pp._revision_plan_rows(sb) is None)
    write_plan([full_row(basis="")])
    check("a plan row without a deciding basis invalidates the plan",
          pp._revision_plan_rows(sb) is None)
    write_plan([full_row(edit="")])
    check("a plan row without the proposed repair invalidates the plan",
          pp._revision_plan_rows(sb) is None)
    write_plan(["not-an-object"])
    check("a non-object plan row invalidates the plan (never '0 rows')",
          pp._revision_plan_rows(sb) is None)

    plan_rows = [{"id": "RP-001", "file": "manuscript.md"},
                 {"id": "RP-002", "file": "manuscript.md"}]
    (sb / "revised" / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-001", "verdict": "confirmed", "reason": "stub"},
        {"id": "RP-002", "verdict": "rejected", "reason": "the base agrees with the revision"},
    ]}), encoding="utf-8")
    problem, counts = pp._revision_repair_ledger(sb, plan_rows)
    check("a complete re-validation ledger is accepted",
          not problem and counts == {"confirmed": 1, "rejected": 1},
          f"{problem!r} {counts!r}")
    (sb / "revised" / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-001", "verdict": "confirmed", "reason": "stub"},
    ]}), encoding="utf-8")
    problem, _counts = pp._revision_repair_ledger(sb, plan_rows)
    check("a ledger that omits a planned row is detected", bool(problem), problem)
    (sb / "revised" / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-001", "verdict": "maybe", "reason": "stub"},
    ]}), encoding="utf-8")
    problem, _counts = pp._revision_repair_ledger(sb, plan_rows)
    check("a ledger verdict outside confirmed|rejected is detected", bool(problem), problem)
    check("the repair ledger is pipeline bookkeeping (never judged/pinned/shipped)",
          pp.is_bookkeeping_name("REPAIR_LEDGER.json")
          and pp.is_bookkeeping_name("REPAIR_LEDGER.md"))
    # F07: a crash AFTER the audit record was stored must not suppress the
    # unfinished repair/post-repair postcheck. The scheduler used to re-enter the
    # chain only when `revision_audit` was absent, which made the guard inside
    # run_revision_chain unreachable in exactly this state.
    rec = {"kind": "revise", "status": "done"}
    check("F07 no audit record yet is pending", pp.revision_chain_pending(rec))
    rec["revision_audit"] = {"status": "failed", "error": "bad plan"}
    check("F07 a failed audit is retried", pp.revision_chain_pending(rec))
    rec["revision_audit"] = {"status": "skipped", "reason": "revision audit off"}
    check("F07 a terminal skip is not re-entered", not pp.revision_chain_pending(rec))
    rec["revision_audit"] = {"status": "skipped", "reason": "manual mode: re-run that round"}
    check("F07 a manual-mode skip resumes on an automated run",
          pp.revision_chain_pending(rec))
    rec["revision_audit"] = {"status": "done", "rows": 0}
    check("F07 an empty plan is complete", not pp.revision_chain_pending(rec))
    rec["revision_audit"] = {"status": "done", "rows": 2}
    check("F07 a non-empty plan with no repair record is pending",
          pp.revision_chain_pending(rec))
    rec["revision_repair"] = {"status": "done"}
    check("F07 a finished repair whose postcheck never ran is pending",
          pp.revision_chain_pending(rec))
    rec["revision_chain"] = "complete"
    check("F07 a completed chain is not re-entered", not pp.revision_chain_pending(rec))


def test_skip():
    print("\n== skipping the revision audit leaves the revision final ==")
    _, root, r = setup_and_run("rev_audit_skip_", env={"PAPER_REVISION_AUDIT": "off"})
    check("the round completes", r.returncode == 0, (r.stdout or r.stderr)[-300:])
    run_rec = revive(root / "runs" / "r1_a2_revise")
    check("the skip is recorded", (run_rec.get("revision_audit") or {}).get("status") == "skipped")
    sb = root / "runs" / "r1_a2_revise"
    check("no audit plan is written", not (sb / "revision_audit" / "REPAIR_PLAN.json").exists())
    check("no pre-repair copy is made", not (sb / "revised_prerepair").exists())


def test_empty_plan():
    print("\n== an empty plan ends at the revised version ==")
    _, root, r = setup_and_run("rev_audit_empty_")
    check("the round completes", r.returncode == 0, (r.stdout or r.stderr)[-300:])
    sb = root / "runs" / "r1_a2_revise"
    run_rec = revive(sb)
    audit = run_rec.get("revision_audit") or {}
    check("the audit ran", audit.get("status") == "done", str(audit))
    check("the plan is empty", audit.get("rows") == 0, str(audit))
    check("no repair session is recorded", not run_rec.get("revision_repair"))
    check("the plan file is present and empty",
          json.loads((sb / "revision_audit" / "REPAIR_PLAN.json").read_text())["rows"] == [])


def test_one_row_repair():
    print("\n== a non-empty plan runs one bounded repair and re-verifies ==")
    _, root, r = setup_and_run("rev_audit_rows_",
                               env={"PAPER_STUB_REVISION_AUDIT_ROWS": "1"})
    check("the round completes", r.returncode == 0, (r.stdout or r.stderr)[-400:])
    sb = root / "runs" / "r1_a2_revise"
    run_rec = revive(sb)
    audit = run_rec.get("revision_audit") or {}
    repair = run_rec.get("revision_repair") or {}
    check("the audit found one row", audit.get("rows") == 1, str(audit))
    check("the repair ran", repair.get("status") == "done", str(repair))
    check("the audited bytes are preserved", (sb / "revised_prerepair").is_dir())
    ledger = sb / "revised" / "REPAIR_LEDGER.json"
    check("the repair recorded its re-validation", ledger.is_file())
    if ledger.is_file():
        rows = json.loads(ledger.read_text(encoding="utf-8")).get("rows") or []
        check("the row was confirmed", rows and rows[0].get("verdict") == "confirmed", str(rows[:1]))
    check("the run stayed done after the re-postcheck", run_rec.get("status") == "done",
          str(run_rec.get("status")))


def test_crash_after_audit_resumes():
    print("\n== a crash after the audit record resumes the repair (F07) ==")
    tmp = scratch("rev_audit_resume_")
    src = make_source(tmp)
    root = tmp / "root"
    r = run(["setup", "--source", str(src), "--root", str(root), "--rounds", "1",
             "--rewrites", "0", "--revises", "1", "--integrators", "0", "--judges", "1"])
    check("the resume root is created", r.returncode == 0, (r.stderr or r.stdout)[-300:])
    only = ["run", "--root", str(root), "--only", "review,audit,revise", "--retries", "0",
            "--agent-cmd", json.dumps([sys.executable, str(STUB)])]
    r = run(only)
    check("the first invocation stops before the judge wave", r.returncode == 3,
          (r.stdout or r.stderr)[-300:])
    run_rec = revive(root / "runs" / "r1_a2_revise")
    check("the first chain used the empty plan",
          (run_rec.get("revision_audit") or {}).get("rows") == 0, str(run_rec.get("revision_audit")))
    # Simulate the crash: the audit stored a ONE-ROW plan, then the process died
    # before the repair ran. This is exactly the state the old call-site guard
    # (`not rec.get("revision_audit")`) refused to resume.
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    rec = state["runs"]["r1_a2_revise"]
    rec["revision_audit"] = {"status": "done", "rows": 1, "duration": 0.1, "error": ""}
    rec.pop("revision_repair", None)
    rec.pop("revision_chain", None)
    sb = root / rec["sandbox"]
    for rel in ("revised/REPAIR_LEDGER.json", "revised/REPAIR_LEDGER.md",
                "revision_audit/REPAIR_PLAN.json", "revision_audit/REPAIR_PLAN.md"):
        (sb / rel).unlink(missing_ok=True)
    shutil.rmtree(sb / "revised_prerepair", ignore_errors=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    r = run(only, env={"PAPER_STUB_REVISION_AUDIT_ROWS": "1"})
    check("the resumed invocation reaches the chain again", r.returncode == 3,
          (r.stdout or r.stderr)[-300:])
    run_rec = revive(sb)
    check("the resumed audit found the one-row plan",
          (run_rec.get("revision_audit") or {}).get("rows") == 1,
          str(run_rec.get("revision_audit")))
    check("the bounded repair ran on the resume",
          (run_rec.get("revision_repair") or {}).get("status") == "done",
          str(run_rec.get("revision_repair")))
    check("the chain recorded its post-repair postcheck as complete",
          run_rec.get("revision_chain") == "complete", str(run_rec.get("revision_chain")))
    check("the revise stayed done after the resumed postcheck",
          run_rec.get("status") == "done", str(run_rec.get("status")))


def test_failed_repair_is_not_fatal():
    print("\n== a failed bounded repair is recorded, and the postcheck decides ==")
    # The verification ledger rejected making a failed bounded repair fatal
    # (F02 is NOT_A_BUG): the repository documents the stage postcheck as the
    # authority. The wrapper lets the stub write a VALID package, then exits 1
    # so the repair record is `failed`; the revision must still be accepted.
    tmp = scratch("rev_audit_repair_fail_")
    src = make_source(tmp)
    root = tmp / "root"
    wrapper = tmp / "stub_fail_repair.py"
    wrapper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(WS / '.paper_test')!r})\n"
        "import stub_agent\n"
        "prompt = sys.stdin.read()\n"
        "rc = stub_agent.main(prompt)\n"
        "sys.exit(1 if 'BOUNDED REPAIR' in prompt else rc)\n", encoding="utf-8")
    r = run(["setup", "--source", str(src), "--root", str(root), "--rounds", "1",
             "--rewrites", "0", "--revises", "1", "--integrators", "0", "--judges", "1"])
    check("the failed-repair root is created", r.returncode == 0, (r.stderr or r.stdout)[-300:])
    r = run(["run", "--root", str(root), "--retries", "0",
             "--agent-cmd", json.dumps([sys.executable, str(wrapper)])],
            env={"PAPER_STUB_REVISION_AUDIT_ROWS": "1"})
    check("the round still completes after the failed repair", r.returncode == 0,
          (r.stdout or r.stderr)[-400:])
    run_rec = revive(root / "runs" / "r1_a2_revise")
    check("the repair failure is recorded",
          (run_rec.get("revision_repair") or {}).get("status") == "failed",
          str(run_rec.get("revision_repair")))
    check("the failed repair does not fail the accepted revision",
          run_rec.get("status") == "done", str(run_rec.get("status")))
    check("the post-repair postcheck ran and completed the chain",
          run_rec.get("revision_chain") == "complete", str(run_rec.get("revision_chain")))


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_prompts()
        test_chain_guards()
        test_skip()
        test_empty_plan()
        test_one_row_repair()
        test_crash_after_audit_resumes()
        test_failed_repair_is_not_fatal()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL REVISION-AUDIT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

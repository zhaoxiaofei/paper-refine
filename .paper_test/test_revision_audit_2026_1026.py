#!/usr/bin/env python3
"""Revision audit and bounded repair: the post-revise chain.

Run:  python3 .paper_test/test_revision_audit_2026_1026.py

The general round is:
  review → findings → audit (no new findings; the review auditor only disposes)
  → revise (re-validating every finding) → revised version
  → revision audit (no new revisions; it writes a bounded-repair plan only)
  → bounded repair (only when the plan is non-empty; re-validating every row)
  → the final revised version of the round → integration / judge / decision.

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
    rr = pp.revision_repair_prompt(sb, "r1_a2_revise", 1, 2)
    check("the repair re-validates every row", "RE-VALIDATE EVERY PLANNED REPAIR" in rr)
    check("the repair applies only confirmed rows", "Apply only `confirmed` rows" in rr)
    check("the repair is one pass", "ONE pass" in rr)


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


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_prompts()
        test_skip()
        test_empty_plan()
        test_one_row_repair()
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

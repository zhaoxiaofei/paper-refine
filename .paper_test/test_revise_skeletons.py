#!/usr/bin/env python3
"""The revise ledger and language-pass skeletons: a head start, never a pass.

The 2026-11-13 benchmark arm wrote the revised brief and then stopped before
`revised/revision_report.json` and `revised/work/R6_language.md`, so the stage
failed on three "missing deliverable" errors after hours of work. The pipeline
now seeds the two files EMPTY-BUT-SHAPED: the ledger already names every frozen
finding id (one row, empty verdict) and the language pass already carries the
L1-L11 coverage rows (empty counts).

The contract this test pins:

  A. seed      a revise sandbox carries both skeletons; the ledger names every
               frozen id; the language table has all eleven rows.
  B. not a pass an empty verdict and an empty coverage cell are still ERRORS
               (`without a VERDICT`, `covers 0/11`), never an accepted clean run.
  C. repairable the two empty-cell errors are exactly what the scoped repair
               (`--strict-artifacts fix`) may complete from the package's own
               evidence; the completion marker is NOT repairable (it is the
               signal the stage finished).
  D. end to end a revise stage whose agent writes nothing leaves the skeletons
               in place and fails on the empty cells -- not on "file missing".

Run:  python3 .paper_test/test_revise_skeletons.py
`PAPER_WS` retargets the suite at another copy of the tree.
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
HERE = Path(__file__).resolve().parent
STUB = HERE / "stub_agent.py"

spec = importlib.util.spec_from_file_location("paper_skeletons", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_skeletons"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(p)
    return p


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_seed_shape():
    print()
    print("== A. the two late deliverables are seeded empty-but-shaped ==")
    sb = scratch("paper_skeleton_shape_")
    write(sb / "guided_review" / "findings.json",
          json.dumps({"findings": [{"id": "F-001"}, {"id": "F-002"}]}))
    write(sb / "guided_review" / "round2" / "findings_extra.json",
          json.dumps({"findings": [{"id": "X-001"}]}))
    seeded = nb.seed_revise_deliverable_skeletons(sb)
    ledger = json.loads((sb / "revised" / "revision_report.json").read_text(encoding="utf-8"))
    ids = [row.get("id") for row in ledger]
    check("A1 the ledger is seeded with one row per frozen id (F-* and X-*)",
          seeded["ledger"] and ids == ["F-001", "F-002", "X-001"], str(ids))
    check("A2 every seeded row is EMPTY (no verdict, no rationale)",
          all(not row.get("verdict") and not row.get("rationale") for row in ledger))
    lang = (sb / "revised" / "work" / "R6_language.md").read_text(encoding="utf-8")
    check("A3 the language pass carries all eleven coverage rows",
          seeded["language"] and all(f"| L{i} |" in lang for i in range(1, 12)))
    check("A4 the completion marker is NOT seeded (a stopped stage stays unfinished)",
          not (sb / "_pipeline_done.json").exists())

    # Re-seeding must never overwrite a file the agent already filled.
    write(sb / "revised" / "revision_report.json", json.dumps([{"id": "F-001",
                                                              "verdict": "confirmed"}]))
    seeded2 = nb.seed_revise_deliverable_skeletons(sb)
    check("A5 an existing (agent-written) ledger is never overwritten",
          not seeded2["ledger"]
          and "confirmed" in (sb / "revised" / "revision_report.json").read_text(encoding="utf-8"))

    # A review whose list could not be read must NOT get an empty ledger that
    # would satisfy the all-clean branch.
    sb2 = scratch("paper_skeleton_empty_")
    seeded3 = nb.seed_revise_deliverable_skeletons(sb2)
    check("A6 an unreadable/empty frozen list seeds no ledger",
          not seeded3["ledger"] and not (sb2 / "revised" / "revision_report.json").exists())

    # A READABLE review with no findings is clean, not unreadable: the ledger is
    # seeded as [] and the postcheck accepts it with a warning (never an error).
    sb_clean = scratch("paper_skeleton_clean_")
    write(sb_clean / "guided_review" / "findings.json", json.dumps({"findings": []}))
    seeded_clean = nb.seed_revise_deliverable_skeletons(sb_clean)
    check("A6b a clean review gets an EMPTY ledger (not no ledger)",
          seeded_clean["ledger"]
          and json.loads((sb_clean / "revised" / "revision_report.json").read_text(
              encoding="utf-8")) == [])
    clean_errs, clean_warns = nb.revision_ledger_problems(sb_clean / "revised", [], 0)
    check("A6c the clean ledger is accepted with a warning, not an error",
          clean_errs == [] and any("all-clean ledger" in w for w in clean_warns),
          str(clean_errs or clean_warns))

    # A process that died BEFORE writing anything must be a fresh attempt, not
    # "finished artifacts, re-verify": the seeds are inputs, not a package.
    root = scratch("paper_skeleton_complete_")
    rec_sb = root / "runs" / "r1_a2_revise"
    shape = scratch("paper_skeleton_complete_src_")
    write(shape / "guided_review" / "findings.json",
          json.dumps({"findings": [{"id": "F-001"}]}))
    nb.seed_revise_deliverable_skeletons(shape)
    shutil.copytree(shape, rec_sb)
    ctx = nb.Ctx(root)
    rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1,
           "sandbox": "runs/r1_a2_revise"}
    check("A7 a sandbox carrying ONLY the seeds is not 'likely complete'",
          nb.likely_complete_artifacts(ctx, rec) is False)
    write(rec_sb / "revised" / "manuscript-b.md", "title\n")
    check("A8 a manuscript in revised/ IS agent work (the probe still fires)",
          nb.likely_complete_artifacts(ctx, rec) is True)


def test_empty_cells_are_errors():
    print()
    print("== B. seeding is a head start, not a pass ==")
    sb = scratch("paper_skeleton_errors_")
    write(sb / "guided_review" / "findings.json",
          json.dumps({"findings": [{"id": "F-001"}, {"id": "F-002"}]}))
    nb.seed_revise_deliverable_skeletons(sb)
    errs, _warns = nb.revision_ledger_problems(sb / "revised", ["F-001", "F-002"], 2)
    check("B1 the seeded ledger FAILS on the empty verdicts",
          any("without a VERDICT" in e for e in errs), str(errs)[:200])
    check("B2 the failure is not 'file missing' (the head start did its job)",
          not any("is missing" in e for e in errs), str(errs)[:200])
    rep = nb.language_pass_report(sb / "revised")
    check("B3 the seeded language pass FAILS on the empty coverage cells",
          rep["present"] and rep["missing"] == [f"L{i}" for i in range(1, 12)], str(rep))


def test_repair_boundary():
    print()
    print("== C. the empty cells are repairable; the marker is not ==")
    root = scratch("paper_skeleton_repair_")
    ctx = nb.Ctx(root)
    ctx.cfg = {"artifact_policy": "fix"}
    rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1, "attempts_done": 1,
           "sandbox": "runs/r1_a2_revise"}
    ledger_err = ("revised/revision_report.json names 2 finding id(s) without a VERDICT: "
                  "F-001, F-002 -- naming an id is not a disposal")
    lang_err = ("revise: the language pass covers 0/11 steps; no coverage row for "
                "L1, L2, L3, L4, L5, L6, L7, L8, L9, L10, L11")
    got = nb.repairable_artifact_failure(ctx, {**rec, "postcheck": {
        "ok": False, "errors": [ledger_err, lang_err], "warnings": []}})
    check("C1 the scoped repair may complete the seeded cells", bool(got), str(got)[:160])
    marker = ("completion marker _pipeline_done.json missing (it is prompted as the very last "
              "step; a non-empty output directory is NOT completion)")
    got_marker = nb.repairable_artifact_failure(ctx, {**rec, "postcheck": {
        "ok": False, "errors": [marker], "warnings": []}})
    check("C2 the completion marker is still a plain FAIL, never a repair", got_marker == [],
          str(got_marker)[:160])
    # Rule 1: the frozen list is Phase 2's INPUT. A stage that never produced it
    # has not finished; no repair may author it (and a warning would let Phase 2
    # run on an empty list -- a silent zero).
    findings_missing = ("guided_review/findings.json is missing: it is the deliverable "
                        "Phase 2 consumes")
    got_findings = nb.repairable_artifact_failure(ctx, {**rec, "postcheck": {
        "ok": False, "errors": [findings_missing], "warnings": []}})
    check("C3 a missing frozen finding list is a plain FAIL, never a repair",
          got_findings == [], str(got_findings)[:160])


def setup_root(tmp: Path) -> Path:
    source = tmp / "source"
    (source / "raw_data").mkdir(parents=True)
    # Deliberately tiny: the stub review's templated OUTLINE dispositions are a
    # boilerplate closure on a long document (a different, already-tested gate).
    write(source / "manuscript-b.md", "title\n")
    write(source / "raw_data" / "data.tsv", "a\tb\n")
    root = tmp / "root"
    subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                    "--source", str(source), "--root", str(root), "--rounds", "1",
                    "--judges", "1", "--rewrites", "0", "--revises", "1",
                    "--integrators", "0x0", "--audit", "off"],
                   capture_output=True, text=True, check=True, timeout=600)
    return root


def run_stage(root: Path, only: str, agent_cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "paper_pipeline.py"), "run",
                           "--root", str(root), "--only", only, "--retries", "0",
                           "--retry-backoff", "0", "--agent-cmd", json.dumps(agent_cmd)],
                          capture_output=True, text=True, timeout=1800)


def test_end_to_end():
    print()
    print("== D. end to end: a revise agent that writes nothing leaves the skeletons ==")
    tmp = scratch("paper_skeleton_e2e_")
    root = setup_root(tmp)
    review = run_stage(root, "review", [sys.executable, str(STUB)])
    check("D1 the stub review finished", "r1_guided_review done" in review.stdout,
          (review.stdout + review.stderr)[-300:])
    # The revise agent is a no-op: it reads the prompt and exits 0, exactly the
    # shape of a session that stopped before writing anything.
    noop = [sys.executable, "-c", "import sys; sys.stdin.read()"]
    proc = run_stage(root, "revise", noop)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_a2_revise"]
    errors = (rec.get("postcheck") or {}).get("errors") or []
    sbs = sorted(p for p in root.glob("runs/r1_a2_revise*") if p.is_dir())
    sb = sbs[0] if sbs else root / "runs" / "r1_a2_revise"
    ledger = sb / "revised" / "revision_report.json"
    lang = sb / "revised" / "work" / "R6_language.md"
    frozen = json.loads((sb / "guided_review" / "findings.json").read_text(encoding="utf-8"))
    frozen_ids = [f["id"] for f in frozen.get("findings") or [] if f.get("id")]
    wrote = json.loads(ledger.read_text(encoding="utf-8")) if ledger.is_file() else []
    check("D2 the sandbox carries both seeded files even though the agent wrote nothing",
          ledger.is_file() and lang.is_file())
    check("D3 the seeded ledger names every frozen id",
          [r.get("id") for r in wrote] == frozen_ids, f"{[r.get('id') for r in wrote]} vs {frozen_ids}")
    check("D4 the stage fails on the empty cells, not on a missing file",
          any("without a VERDICT" in e for e in errors)
          and any("language pass covers 0/11" in e for e in errors)
          and not any("revision_report.json is missing" in e for e in errors)
          and not any("no work/R6_language.md" in e for e in errors),
          str(errors)[:400])
    check("D5 the stage is still failed (a skeleton is not a completion)",
          proc.returncode != 0 and rec["status"] == "failed",
          f"rc={proc.returncode} status={rec['status']}")


def main() -> int:
    tries = [test_seed_shape, test_empty_cells_are_errors, test_repair_boundary,
             test_end_to_end]
    try:
        for fn in tries:
            fn()
    finally:
        for tmp in TMPDIRS:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} REVISE-SKELETON CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL REVISE-SKELETON CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

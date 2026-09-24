#!/usr/bin/env python3
"""The audit stage's rebuild, the completion signal's location, the self-check.

Run:  python3 .nbt_test/test_stage_signals_and_rebuild.py

Every check FAILS on the pre-fix tree and PASSES on the fixed one. The three
failures come from root `cnb-13to14-0923-1040-2482bdf` (2026-09-23):

  A. REBUILD   the auditor's third attempt never happened: `r1_audit` failed its
               postcheck, and the retry died in `rebuild_sandbox` with
               "cannot rebuild unknown run kind 'audit'" (the audit stage had no
               rebuilder), so the run was abandoned after 1 of its 3 attempts and
               `r1_a2_revise` + `r1_i1..i4` never started. Now: a rebuild table
               keyed by kind, a plan-level fail-fast guard, and an end-to-end
               retry that really rebuilds and finishes the round.
  B. LOCATION  the auditor wrote a complete, valid `_pipeline_done.json` into
               `audit/` instead of the sandbox root, and the postcheck read the
               root. Now: the prompts state the location, the postcheck ADOPTS a
               signal that names this run and stage, and a signal that names
               another run/stage is refused WITH its path in the message.
  C. ROWS      the reviewer rewrote OUTLINE.md's 185 rows one cell SHORT (its
               verdicts landed in the `summary` column), so the table read as
               "185 of 185 row(s) have an EMPTY disposition cell" and the whole
               25-minute review was re-run. Now: the message names the row, its
               cell count and the header's, the mandate forbids re-emitting rows
               with a different shape, and the session can run the postcheck's
               own detectors (`selfcheck`) BEFORE it writes the marker.

`NBT_WS` retargets the suite at a baseline copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_signals", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_signals"] = nb
spec.loader.exec_module(nb)

STUB = WS / ".nbt_test" / "stub_agent.py"
STUB_JUDGE = WS / ".nbt_test" / "stub_judge.py"
STUB_TIMED = WS / ".nbt_test" / "stub_timed.py"
STUB_STRAY = WS / ".nbt_test" / "stub_stray_signal.py"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def cli(*argv, timeout=900, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout, env=e)


def make_root(tmp: Path) -> Path:
    """A one-round root with the auditor ON (that is the reported failure)."""
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    root = tmp / "root"
    # `--integrators 0x1` keeps the suite's rounds small (one integration arm
    # instead of one per pool member): the scheduling tests own the mask.
    proc = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1",
               "--rewrites", "1", "--revises", "1", "--judges", "1", "--audit", "on",
               "--integrators", "0x1")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return root


def run_root(root: Path, agent=STUB, retries="1", env=None, judge_agent=STUB_JUDGE):
    e = dict(env or {})
    proc = cli("run", "--root", str(root),
               "--agent-cmd", json.dumps([sys.executable, str(agent)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(judge_agent)]),
               "--retries", retries, env=e)
    return proc


def state_of(root: Path) -> dict:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))


def leaf(root: Path, *cands):
    for c in cands:
        p = root / c
        if p.exists():
            return p
    return root / cands[0]


# =====================================================================
# A. the rebuild: every planned kind can be re-materialized
# =====================================================================

def test_kind_support_tables():
    print("== A. every kind the plan can produce has a postcheck AND a rebuilder ==")
    if not hasattr(nb, "run_kind_support_problems") or not hasattr(nb, "REBUILD_HANDLERS"):
        check("the rebuild dispatch table exists (REBUILD_HANDLERS)",
              False, "this build has no REBUILD_HANDLERS/run_kind_support_problems")
        return
    tmp = scratch("nbt_sig_a_")
    root = make_root(tmp)
    ctx = nb.Ctx(root)
    ctx.load()
    kinds = {str(e.get("kind")) for e in nb.round_run_plan(ctx, 1)}
    check("the round's plan really contains the audit stage", "audit" in kinds, str(sorted(kinds)))
    check("the given root's plan is fully supported (no missing handler)",
          nb.run_kind_support_problems(ctx) == [], str(nb.run_kind_support_problems(ctx)))
    check("every postcheckable kind has a rebuilder",
          set(nb.REBUILD_HANDLERS) >= set(nb.POSTCHECK_HANDLERS),
          str(sorted(set(nb.POSTCHECK_HANDLERS) - set(nb.REBUILD_HANDLERS))))
    check("... including the audit stage that could not be rebuilt before",
          "audit" in nb.REBUILD_HANDLERS)
    # the guard must REPORT a missing rebuilder instead of staying silent
    saved = nb.REBUILD_HANDLERS.pop("audit")
    try:
        problems = nb.run_kind_support_problems(ctx)
        check("a missing rebuilder is reported before anything is launched",
              any("audit" in p and "rebuild" in p for p in problems), str(problems))
    finally:
        nb.REBUILD_HANDLERS["audit"] = saved
    check("the guard is quiet again once the kind is supported",
          nb.run_kind_support_problems(ctx) == [])


def test_rebuild_recreates_an_audit_sandbox():
    print()
    print("== A. rebuild_sandbox() re-materializes an `audit` sandbox ==")
    tmp = scratch("nbt_sig_a2_")
    root = make_root(tmp)
    ctx = nb.Ctx(root)
    ctx.load()
    nb.materialize_a1(ctx, 1)
    rev = nb.materialize_review(ctx, 1)
    write(ctx.sandbox_of(rev) / "review" / "findings.json",
          {"findings": [{"id": "F-001", "location": "base", "category": 2, "check": "J3",
                         "severity": "Minor", "evidence": "e", "status": "resolvable"}]})
    rev["status"] = "done"
    rec = nb.materialize_audit(ctx, 1)
    sb = ctx.sandbox_of(rec)
    write(sb / "audit" / "audit.json", {"dispositions": []})
    write(sb / "_pipeline_done.json", {"stage": "audit", "run_id": rec["id"], "round": 1,
                                       "status": "complete"})
    rec["postcheck"] = {"ok": False, "errors": ["x"], "warnings": []}
    rec["last_error"] = "x"
    rec["status"] = "failed"
    try:
        nb.rebuild_sandbox(ctx, rec)
        rebuild_err = ""
    except Exception as exc:                                     # noqa: BLE001
        rebuild_err = f"{type(exc).__name__}: {exc}"
    check("rebuild_sandbox() re-materializes an audit sandbox (no 'unknown run kind')",
          not rebuild_err, rebuild_err[:200])
    if rebuild_err:
        return
    check("the audit sandbox was rebuilt (the marker is gone)",
          not (sb / "_pipeline_done.json").is_file())
    check("the rebuilt sandbox carries base/, non_revised/ and the frozen review/",
          all((sb / d).is_dir() for d in ("base", "non_revised", "review", "audit")))
    check("the frozen review/ was re-copied from the review run",
          (sb / "review" / "findings.json").is_file())
    check("the failed attempt's sandbox was archived, not discarded",
          (root / "runs" / f"{rec['id']}_try1_failed").is_dir())
    check("the record was reset for the next attempt",
          rec["postcheck"] is None and rec["last_error"] is None)


def test_audit_retry_completes_the_round():
    print()
    print("== A. a failed audit attempt is retried (rebuilt) and the round finishes ==")
    tmp = scratch("nbt_sig_a3_")
    root = make_root(tmp)
    # NBT_TIMING_LOG is what makes the stub's "fail once" FLAG unique to this
    # run: with the default path a flag left by an earlier suite run (or by the
    # baseline leg of this one) would make the first audit attempt succeed.
    proc = run_root(root, agent=STUB_TIMED, retries="1",
                    env={"NBT_TIMING_FAIL_ONCE": "r1_audit",
                         "NBT_TIMING_LOG": str(tmp / "timing.log")})
    out = proc.stdout + proc.stderr
    state = state_of(root)
    rec = (state.get("runs") or {}).get("r1_audit") or {}
    check("no 'unknown run kind' rebuild failure anywhere in the console",
          "unknown run kind" not in out and "sandbox rebuild failed" not in out, out[-300:])
    check("the audit run was retried and completed",
          rec.get("status") == "done" and int(rec.get("attempts") or 0) == 2,
          f"status={rec.get('status')} attempts={rec.get('attempts')}")
    check("the failed first attempt is kept as an archive",
          (root / "runs" / "r1_audit_try1_failed" / "record.json").is_file())
    check("the round completed, so the revise and integration runs were not blocked",
          ((state.get("rounds") or {}).get("1") or {}).get("status") == "done",
          str((state.get("rounds") or {}).get("1")))


# =====================================================================
# B. the completion signal's location
# =====================================================================

def test_relocation_semantics():
    print()
    print("== B. a signal in the stage's own directory: adoption and refusals ==")
    if not hasattr(nb, "relocate_stray_signal"):
        check("the stray-signal layer exists (relocate_stray_signal)",
              False, "this build has no relocate_stray_signal")
        return
    tmp = scratch("nbt_sig_b_")
    root = make_root(tmp)
    ctx = nb.Ctx(root)
    ctx.load()
    sb = root / "runs" / "r1_audit"
    (sb / "audit").mkdir(parents=True)
    rec = ctx.register("r1_audit", "audit", 1, "runs/r1_audit")
    stray = sb / "audit" / nb.MARKER_FILE
    write(stray, {"stage": "audit", "run_id": "r1_audit", "round": 1, "status": "complete"})
    notes = nb.relocate_stray_signal(ctx, rec)
    check("this run's own marker is adopted (moved to the root)",
          len(notes) == 1 and (sb / nb.MARKER_FILE).is_file() and not stray.is_file(),
          str(notes))
    check("the adoption is reported, naming the stray path",
          "audit/_pipeline_done.json" in notes[0] and "ADOPTED" in notes[0], str(notes[0])[:160])
    check("adoption is idempotent (nothing to do the second time)",
          nb.relocate_stray_signal(ctx, rec) == [])
    (sb / nb.MARKER_FILE).unlink()
    write(stray, {"stage": "review", "run_id": "r1_review", "round": 1, "status": "complete"})
    check("ANOTHER stage's marker is never adopted",
          nb.relocate_stray_signal(ctx, rec) == [] and stray.is_file())
    check("... and the failure message names it, with its stage",
          "audit/_pipeline_done.json" in nb.stray_signal_note(sb, rec, nb.MARKER_FILE)
          and "review" in nb.stray_signal_note(sb, rec, nb.MARKER_FILE))
    write(stray, {"stage": "audit", "run_id": "r1_audit_try9", "round": 1, "status": "complete"})
    check("another RUN's marker is never adopted",
          nb.relocate_stray_signal(ctx, rec) == [] and stray.is_file())
    write(stray, "this is not JSON at all")
    check("an unparseable stray is never adopted",
          nb.relocate_stray_signal(ctx, rec) == [] and stray.is_file())
    # the review stage's own directory is its alt dir; a revise sandbox is NOT
    # allowed to adopt the auditor's copied marker (its alt dir is revised/)
    check("the alt directories are per stage",
          nb.SIGNAL_ALT_DIRS["audit"] == ("audit",)
          and nb.SIGNAL_ALT_DIRS["revise"] == ("revised",)
          and nb.SIGNAL_ALT_DIRS["judge"] == ("judge_review",))


def test_misplaced_marker_is_adopted_end_to_end():
    print()
    print("== B. end to end: a marker in audit/ does not cost the session ==")
    tmp = scratch("nbt_sig_b2_")
    root = make_root(tmp)
    proc = run_root(root, agent=STUB_STRAY, retries="0",
                    env={"NBT_STRAY_MARKER": "r1_audit"})
    out = proc.stdout + proc.stderr
    state = state_of(root)
    rec = (state.get("runs") or {}).get("r1_audit") or {}
    sb = leaf(root, "runs/r1_audit", "runs/r1_audit_try1_failed")
    check("the audit run PASSED although the marker was written into audit/",
          rec.get("status") == "done" and int(rec.get("attempts") or 0) == 1,
          f"status={rec.get('status')} attempts={rec.get('attempts')}")
    check("the marker now sits in the sandbox root",
          (sb / nb.MARKER_FILE).is_file() and not (sb / "audit" / nb.MARKER_FILE).is_file())
    check("the adoption is recorded as a warning naming the stray path",
          any("audit/_pipeline_done.json" in w and "ADOPTED" in w
              for w in ((rec.get("postcheck") or {}).get("warnings") or [])),
          str(((rec.get("postcheck") or {}).get("warnings") or [])[:1])[:200])
    check("the console reports the adoption too", "ADOPTED" in out, out[-200:])
    check("the round completed", ((state.get("rounds") or {}).get("1") or {}).get("status")
          == "done")
    rev = (state.get("runs") or {}).get("r1_a2_revise") or {}
    rev_sb = rev.get("sandbox")
    check("the reviser's copied audit/ carries NO stray marker",
          rev_sb is not None
          and not (root / rev_sb / "audit" / nb.MARKER_FILE).exists())


def test_foreign_stray_marker_fails_with_its_path():
    print()
    print("== B. end to end: a marker that names the WRONG stage is refused ==")
    tmp = scratch("nbt_sig_b3_")
    root = make_root(tmp)
    proc = run_root(root, agent=STUB_STRAY, retries="0",
                    env={"NBT_STRAY_STAGE": "r1_audit"})
    state = state_of(root)
    rec = (state.get("runs") or {}).get("r1_audit") or {}
    errs = " ".join((rec.get("postcheck") or {}).get("errors") or [])
    sb = leaf(root, "runs/r1_audit", "runs/r1_audit_try1_failed")
    check("the attempt failed (nothing was silently adopted)", rec.get("status") == "failed",
          str(rec.get("status")))
    check("the error names the stray file and the stage it really names",
          "audit/_pipeline_done.json" in errs and "definitely-not-this-stage" in errs,
          errs[:240])
    check("the forged marker was left exactly where the agent put it",
          (sb / "audit" / nb.MARKER_FILE).is_file() and not (sb / nb.MARKER_FILE).exists())
    check("the round stayed incomplete",
          ((state.get("rounds") or {}).get("1") or {}).get("status") != "done")
    check("the console carries the reason", "definitely-not-this-stage"
          in (proc.stdout + proc.stderr))


# =====================================================================
# C. the seeded tables: a one-cell-short row is diagnosed as such
# =====================================================================

OUTLINE_HEADER = ("| # | document | heading | paragraph | words | lists | refs | "
                  "first sentence | summary | disposition |")


def outline_rows(n_short: int, n_ok: int) -> str:
    lines = [OUTLINE_HEADER, "|---|" + "---|" * 9]
    i = 0
    for _ in range(n_short):
        i += 1
        # ONE CELL SHORT: the verdict was written where `summary` is.
        lines.append(f"| {i} | base.docx | Intro | {i} | 20 |  |  | First {i}. | "
                     f"OK — row {i}: the paragraph makes one point |")
    for _ in range(n_ok):
        i += 1
        lines.append(f"| {i} | base.docx | Intro | {i} | 20 |  |  | First {i}. | "
                     f"Summary of paragraph {i}. | OK — row {i}: inside its own bar |")
    return "\n".join(lines) + "\n"


def test_short_rows_are_named():
    print()
    print("== C. a row that is one cell short is diagnosed, not just 'EMPTY' ==")
    tmp = scratch("nbt_sig_c_")
    art = tmp / "review" / "artifacts"
    art.mkdir(parents=True)
    write(art / "OUTLINE.md", "# OUTLINE\n\n" + outline_rows(3, 0))
    report = nb.artifact_quality_report(tmp / "review")
    probs = report.get("artifacts/OUTLINE.md") or []
    text = " ".join(probs)
    check("the short rows are still a FAILURE (they are not waved through)",
          bool(probs) and "EMPTY disposition cell" in text, text[:160])
    check("the message says the rows are narrower than their header, and by how much",
          "NARROWER than the table's 10-column header" in text and "row 1 has 9 cell(s)" in text,
          text[:400])
    check("the message says where the verdict went and what to do",
          "POSITIONALLY" in text and "one cell per seeded column" in text)
    check("the notes name the narrow rows too",
          any("NARROWER" in n for n in
              (nb.artifact_quality_notes(tmp / "review").get("artifacts/OUTLINE.md") or [])),
          str(nb.artifact_quality_notes(tmp / "review"))[:200])
    # the message keeps the shape the repair profiles match on
    check("the message still carries the `decision artifact ` prefix the repair layer matches",
          all(p.startswith("3 of 3 row(s) have an EMPTY disposition cell") for p in probs)
          and any(re.search(r"^decision artifact ", f"decision artifact artifacts/OUTLINE.md: {p}")
                  for p in probs))
    # a well-formed table produces nothing
    write(art / "OUTLINE.md", "# OUTLINE\n\n" + outline_rows(0, 4))
    check("a correctly shaped, disposed table reports nothing",
          nb.artifact_quality_report(tmp / "review") == {},
          str(nb.artifact_quality_report(tmp / "review"))[:200])
    # the mandate tells the session the rule (the prompt-level layer)
    check("the decision-artifact mandate forbids re-emitting a row with a different shape",
          "ROW SHAPE IS PART OF THAT CONTRACT" in nb.DISPOSITION_MANDATE)


# =====================================================================
# D. the session-facing self-check
# =====================================================================

def build_review_sandbox(tmp: Path, short_rows: bool, marker_in_review: bool) -> Path:
    sb = tmp / "r1_review"
    art = sb / "review" / "artifacts"
    art.mkdir(parents=True)
    # A sandbox that is genuinely CLEAN: the review contract requires a coverage
    # row for every check id, so the fixture carries them (the pre-flight now
    # checks the real contract, not a subset of it).
    wanted = list(nb.REQUIRED_REVIEW_CHECKS) + ["M18", "M19", "M20",
                                                "M21", "M22", "M23", "M24"]
    write(sb / "review" / "findings.json",
          {"submission_dir": "./base", "findings": [],
           "coverage": [{"check": c, "disposition": "clean -- basis: stub artifact",
                         "detail": "stub"} for c in wanted]})
    write(art / "OUTLINE.md", "# OUTLINE\n\n" + outline_rows(2 if short_rows else 0,
                                                            0 if short_rows else 2))
    write(art / "VIS_visual.md", "# visual\n\npages reviewed: none\n")
    marker = {"stage": "review", "run_id": "r1_review", "round": 1, "status": "complete"}
    write((sb / "review" / nb.MARKER_FILE) if marker_in_review else (sb / nb.MARKER_FILE), marker)
    return sb


def test_selfcheck():
    print()
    print("== D. `selfcheck` reports what the postcheck will reject (and is read-only) ==")
    tmp = scratch("nbt_sig_d_")
    sb = build_review_sandbox(tmp, short_rows=True, marker_in_review=True)
    before = {p.relative_to(sb).as_posix(): p.read_bytes()
              for p in sorted(sb.rglob("*")) if p.is_file()}
    proc = cli("selfcheck", "--sandbox", str(sb), "--stage", "review",
               "--run-id", "r1_review", "--round", "1")
    out = proc.stdout + proc.stderr
    check("the self-check FAILS an attempt the postcheck would fail", proc.returncode == 1,
          out[-300:])
    check("it reports the misplaced marker, naming the stray path",
          "review/_pipeline_done.json" in out, out[-400:])
    check("it reports the one-cell-short rows", "NARROWER than the table's 10-column header" in out)
    after = {p.relative_to(sb).as_posix(): p.read_bytes()
             for p in sorted(sb.rglob("*")) if p.is_file()}
    check("the self-check changed NOTHING on disk (read-only pre-flight)", before == after,
          str(sorted(set(after) ^ set(before))[:4]))
    # fix everything the check named, then it passes
    write(sb / "review" / "artifacts" / "OUTLINE.md", "# OUTLINE\n\n" + outline_rows(0, 2))
    (sb / "review" / nb.MARKER_FILE).replace(sb / nb.MARKER_FILE)
    proc2 = cli("selfcheck", "--sandbox", str(sb), "--stage", "review",
                "--run-id", "r1_review", "--round", "1")
    check("a clean sandbox passes the self-check", proc2.returncode == 0,
          (proc2.stdout + proc2.stderr)[-300:])
    # the same detectors the postcheck uses (not a parallel implementation)
    if hasattr(nb, "sandbox_selfcheck"):
        ok, errs, warns = nb.sandbox_selfcheck(sb, "review", "r1_review", 1)
        check("sandbox_selfcheck() is importable and quiet on the fixed sandbox",
              ok and not errs, str(errs)[:200])
    else:
        check("sandbox_selfcheck() exists", False, "this build has no sandbox_selfcheck")
    tmp2 = scratch("nbt_sig_d2_")
    bad = build_review_sandbox(tmp2, short_rows=True, marker_in_review=False)
    expected = [f"decision artifact {rel}: {p}"
                for rel, ps in sorted(nb.artifact_quality_report(bad / "review").items())
                for p in ps]
    if hasattr(nb, "sandbox_selfcheck"):
        got = nb.sandbox_selfcheck(bad, "review", "r1_review", 1)[1]
        check("the self-check's decision-table verdict IS the postcheck's own report",
              all(e in got for e in expected) and bool(expected), str(expected)[:200])
    if hasattr(nb, "sandbox_selfcheck"):
        # every stage has a pre-flight, and each one judges its OWN layout
        tmp3 = scratch("nbt_sig_d3_")
        jsb = tmp3 / "judge_tok9_j1"
        write(jsb / "scores.json", {"run_id": "judge_tok9_j1", "target_id": "tok9",
                                    "comparisons": [{"opponent_label": "v1", "score": 0}]})
        write(jsb / "judge_review" / "inventory.md", "# inventory\n")
        write(jsb / nb.MARKER_FILE, {"stage": "judge", "run_id": "judge_tok9_j1",
                                     "status": "complete"})
        ok_j, errs_j, _w = nb.sandbox_selfcheck(jsb, "judge", "judge_tok9_j1", 0)
        check("a judge sandbox is judged as a JUDGE (no package-directory complaint)",
              ok_j and not errs_j, str(errs_j)[:200])
        (jsb / "judge_review" / "inventory.md").unlink()
        check("an empty judge_review/ is reported",
              any("judge_review/" in e for e in nb.sandbox_selfcheck(jsb, "judge",
                                                                     "judge_tok9_j1", 0)[1]))
        rsb = tmp3 / "r1_a2_revise"
        (rsb / "revised").mkdir(parents=True)
        write(rsb / nb.MARKER_FILE, {"stage": "revise", "run_id": "r1_a2_revise", "round": 1,
                                     "status": "complete"})
        errs_r = nb.sandbox_selfcheck(rsb, "revise", "r1_a2_revise", 1)[1]
        check("an empty package directory is reported",
              any("revised/ is empty" in e for e in errs_r), str(errs_r)[:160])
        check("... and so is the missing revision ledger",
              any("revision_report.json is missing" in e for e in errs_r), str(errs_r)[:160])
    proc3 = cli("selfcheck", "--sandbox", str(sb), "--stage", "bogus")
    check("an unknown stage is refused by the CLI parser", proc3.returncode != 0)


def test_prompts_state_the_marker_location():
    print()
    print("== D. every stage prompt states the marker's location and the self-check ==")
    sb = Path("/tmp/x")
    prompts = {
        "review": nb.review_prompt(sb, "r1_review", 1),
        "revise": nb.revise_prompt(sb, "r1_a2_revise", 1, 1, 1),
        "rewrite": nb.rewrite_prompt(sb, "r1_w1", 1, 1, 1),
        "integrate": nb.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1", "a2"]),
        "audit": nb.audit_prompt(sb, "r1_audit", 1),
    }
    for kind, text in prompts.items():
        check(f"{kind}: the prompt says the marker goes in the SANDBOX ROOT",
              "SANDBOX ROOT" in text, text[:0])
        check(f"{kind}: the prompt names the pre-flight command for this stage",
              f"selfcheck --sandbox . --stage {kind}" in text)
        check(f"{kind}: no unresolved prompt token is left",
              "@@MARKER_ROOT@@" not in text and "@@SELFCHECK@@" not in text)
        check(f"{kind}: the marker is still asked for LAST",
              nb.MARKER_FILE in text and "VERY LAST STEP" in text)
    audit = prompts["audit"]
    check("audit: the old contradiction is gone ('write everything inside audit/')",
          "write everything inside" not in audit)
    check("audit: the tail says the marker is NOT inside audit/",
          "IN THE SANDBOX ROOT" in audit and "NOT inside `audit/`" in audit)
    check("audit: the marker fields are still spelled out",
          '"finding_tier_rows_examined"' in audit and '"promoted"' in audit)
    judge = nb.judge_prompt(sb, "judge_tok9_j1", 1, "tok9", 1, 1, ["v1", "v2"])
    check("judge: the sheet's location is stated",
          "sandbox root" in judge and "scores.json IS the completion signal" in judge)
    check("judge: the pre-flight block is present but writes no provenance into the prompt",
          "selfcheck --sandbox . --stage judge" in judge
          and hasattr(nb, "judge_selfcheck_block")
          and nb.judge_selfcheck_block("judge_tok9_j1").count("--round") == 0)


# =====================================================================
# E. the same failure families for the OTHER stages
# =====================================================================

def package_sandbox(root: Path, rid: str, kind: str, *, lang=True, marker=True):
    """A minimal package-stage sandbox (rewrite/revise/integrate) that is COMPLETE."""
    sb = root / "runs" / rid
    pkg = sb / nb.output_dir_for_kind(kind)
    pkg.mkdir(parents=True)
    write(pkg / "manuscript.md", "# revised\n")
    if lang:
        write(pkg / "work" / "R6_language.md",
              "# language pass\n\n| step | change |\n|---|---|\n"
              + "".join(f"| L{i} | none |\n" for i in range(1, 12)))
    if marker:
        write(sb / nb.MARKER_FILE, {"stage": kind, "run_id": rid, "round": 1,
                                    "status": "complete"})
    return sb, pkg


def test_misplaced_deliverable_is_rescued():
    print()
    print("== E. a required bookkeeping file written one level up is adopted ==")
    if not hasattr(nb, "rescue_misplaced_deliverable"):
        check("the deliverable-rescue layer exists", False,
              "this build has no rescue_misplaced_deliverable")
        return
    tmp = scratch("nbt_sig_e_")
    root = make_root(tmp)
    ctx = nb.Ctx(root)
    ctx.load()
    cases = (("r1_a2_revise", "revise", "revision_report.json", "revised/revision_report.json"),
             ("r1_w1", "rewrite", "REWRITE_REPORT.md", "rewritten/REWRITE_REPORT.md"),
             ("r1_review", "review", "findings.json", "review/findings.json"),
             ("r1_audit", "audit", "audit.json", "audit/audit.json"))
    for rid, kind, name, rel in cases:
        sb = root / "runs" / rid
        sb.mkdir(parents=True, exist_ok=True)
        rec = ctx.register(rid, kind, 1, f"runs/{rid}")
        payload = {"findings": []} if name in ("findings.json",) else {"dispositions": []}
        if not name.endswith(".json"):
            payload = "report\n"
        write(sb / name, payload)
        notes = nb.rescue_misplaced_deliverable(ctx, rec)
        check(f"{kind}: a `{name}` in the sandbox root is adopted into {rel}",
              len(notes) == 1 and (sb / rel).is_file() and not (sb / name).is_file()
              and "ADOPTED" in notes[0], str(notes)[:160])
        check(f"{kind}: adoption is idempotent", nb.rescue_misplaced_deliverable(ctx, rec) == [])
    # from the session's own work/ scratch too
    sb, _pkg = package_sandbox(root, "r1_a2_revise2", "revise")
    rec = ctx.register("r1_a2_revise2", "revise", 1, "runs/r1_a2_revise2")
    write(sb / "revised" / "work" / "revision_report.json", {"rows": [{"id": "F-001"}]})
    notes = nb.rescue_misplaced_deliverable(ctx, rec)
    check("a ledger in the package's own work/ scratch is adopted too",
          len(notes) == 1 and (sb / "revised" / "revision_report.json").is_file(),
          str(notes)[:120])
    # refusals: garbage, an existing target, and a read-only input area
    sb, _pkg = package_sandbox(root, "r1_a2_revise3", "revise")
    rec = ctx.register("r1_a2_revise3", "revise", 1, "runs/r1_a2_revise3")
    write(sb / "revision_report.json", "{ truncated")
    check("a truncated ledger is NOT adopted",
          nb.rescue_misplaced_deliverable(ctx, rec) == []
          and not (sb / "revised" / "revision_report.json").exists())
    (sb / "revision_report.json").unlink()
    write(sb / "revised" / "revision_report.json", {"rows": []})
    write(sb / "revision_report.json", {"rows": [{"id": "F-001"}]})
    check("an existing target is never overwritten",
          nb.rescue_misplaced_deliverable(ctx, rec) == []
          and (sb / "revision_report.json").is_file())
    sb, _pkg = package_sandbox(root, "r1_a2_revise4", "revise")
    rec = ctx.register("r1_a2_revise4", "revise", 1, "runs/r1_a2_revise4")
    write(sb / "base" / "revision_report.json", {"rows": [{"id": "F-001"}]})
    check("a file from a read-only input area is never moved into the package",
          nb.rescue_misplaced_deliverable(ctx, rec) == []
          and (sb / "base" / "revision_report.json").is_file())
    check("only BOOKKEEPING names are listed (never a manuscript document)",
          all(str(n).endswith((".json", ".md"))
              for table in nb.STAGE_DELIVERABLES.values()
              for n in list(table["required"]) + list(table["expected"]))
          and not any(str(n).endswith((".docx", ".tex", ".bib", ".pdf"))
                      for table in nb.STAGE_DELIVERABLES.values()
                      for n in list(table["required"]) + list(table["expected"])))


def test_selfcheck_covers_the_other_stages():
    print()
    print("== E. the pre-flight covers each stage's own failure modes ==")
    if not hasattr(nb, "sandbox_selfcheck"):
        check("sandbox_selfcheck() exists", False, "this build has no sandbox_selfcheck")
        return
    tmp = scratch("nbt_sig_e2_")

    # reviser: the ledger must NAME every finding id of the AUDITED list
    sb, pkg = package_sandbox(tmp / "a", "r1_a2_revise", "revise")
    write(sb / "review" / "findings.json",
          {"findings": [{"id": "F-001"}, {"id": "F-002"}]})
    write(pkg / "revision_report.json", {"rows": [{"id": "F-001", "verdict": "fixed"}]})
    errs = nb.sandbox_selfcheck(sb, "revise", "r1_a2_revise", 1)[1]
    check("revise: a ledger that omits a frozen finding id is caught before the marker",
          any("does not name" in e and "F-002" in e for e in errs), str(errs)[:200])
    write(pkg / "revision_report.json", {"rows": [{"id": "F-001", "verdict": "fixed"},
                                                   {"id": "F-002", "verdict": "fixed"}]})
    check("revise: a complete sandbox then passes",
          nb.sandbox_selfcheck(sb, "revise", "r1_a2_revise", 1)[0] is True,
          str(nb.sandbox_selfcheck(sb, "revise", "r1_a2_revise", 1)[1])[:160])
    write(sb / "audit" / "audit.json",
          {"dispositions": [{"id": "F-002", "verdict": "drop",
                             "reason": "the quoted text does not exist in base/ at all",
                             "evidence": "the sentence quoted by the finding is absent from "
                                         "the submitted manuscript entirely"}],
           "adds": [{"id": "AU-001"}]})
    errs = nb.sandbox_selfcheck(sb, "revise", "r1_a2_revise", 1)[1]
    check("revise: the pre-flight reads the AUDITED list (a dropped id is not required)",
          any("AU-001" in e for e in errs) and not any("F-002" in e for e in errs),
          str(errs)[:200])

    # the language pass, on every package stage
    sb_i, _pkg = package_sandbox(tmp / "b", "r1_i1", "integrate", lang=False)
    errs = nb.sandbox_selfcheck(sb_i, "integrate", "r1_i1", 1)[1]
    check("integrate: a missing L1-L11 language pass is caught",
          any("R6_language.md" in e for e in errs), str(errs)[:160])
    sb_w, _pkg = package_sandbox(tmp / "c", "r1_w1", "rewrite")
    write(sb_w / "PROMPT.md", "=== THIS ARM'S LEVEL: STRUCTURAL (organization-level) ===\n")
    write(sb_w / "rewritten" / "REWRITE_REPORT.md", "# report\n\nLevel: sentence\n")
    errs = nb.sandbox_selfcheck(sb_w, "rewrite", "r1_w1", 1)[1]
    check("rewrite: a report that declares the wrong level is caught before the marker",
          any("declares level" in e for e in errs), str(errs)[:200])

    # integrator: a ledger row without its `artifact` cell
    sb_i2, pkg_i2 = package_sandbox(tmp / "d", "r1_i2", "integrate")
    write(pkg_i2 / "DIFF_LEDGER.md",
          "# ledger\n\n| donor | artifact | size | finding effect | verdict |\n"
          "|---|---|---|---|---|\n| w1 |  | small | preserves F-001 | ported |\n")
    errs = nb.sandbox_selfcheck(sb_i2, "integrate", "r1_i2", 1)[1]
    check("integrate: a ledger row with no `artifact` cell is caught before the marker",
          any("carry no `artifact`" in e for e in errs), str(errs)[:200])

    # judge: whatever the sandbox can verify about its own sheet
    jsb = tmp / "e" / "judge_tok9_j1"
    (jsb / "field" / "v1").mkdir(parents=True)
    (jsb / "field" / "v2").mkdir(parents=True)
    write(jsb / "judge_review" / "inventory.md", "# inventory\n")
    write(jsb / "scores.json",
          {"run_id": "judge_tok9_j1", "target_id": "tok9", "judge_index": 1,
           "comparisons": [{"opponent_label": "v1", "score": 2, "basis": "correctness",
                            "resolved": [], "introduced": [], "checks": {}}]})
    write(jsb / nb.MARKER_FILE, {"stage": "judge", "run_id": "judge_tok9_j1",
                                 "status": "complete"})
    errs = nb.sandbox_selfcheck(jsb, "judge", "judge_tok9_j1", 0)[1]
    check("judge: a score with no item on its side is caught (ledger arithmetic)",
          any("no ledger item on its side" in e for e in errs), str(errs)[:200])
    check("judge: a missing check-coverage map is caught",
          any("coverage map" in e for e in errs), str(errs)[:200])
    check("judge: an issued opponent label with no comparison is caught",
          any("omit" in e and "v2" in e for e in errs), str(errs)[:200])


def test_other_stages_recover_from_a_failed_attempt():
    print()
    print("== E. other stages' failed attempts are rebuilt and retried ==")
    # The REVISER (the longest session of the round) and the JUDGE panel: each
    # one fails its first attempt and must come back through a rebuilt sandbox.
    for run_id, kind in (("r1_a2_revise", "revise"), ("judge_", "judge")):
        tmp = scratch(f"nbt_sig_f_{kind}_")
        root = make_root(tmp)
        proc = run_root(root, agent=STUB_TIMED, judge_agent=STUB_TIMED, retries="1",
                        env={"NBT_TIMING_FAIL_ONCE": run_id,
                             "NBT_TIMING_LOG": str(tmp / "timing.log")})
        out = proc.stdout + proc.stderr
        state = state_of(root)
        if kind == "judge":
            recs = [r for r in (state.get("runs") or {}).values()
                    if r.get("kind") == "judge" and int(r.get("attempts") or 0) == 2]
            check("judge: a failed panel session was rebuilt and its retry succeeded",
                  bool(recs) and all(r.get("status") == "done" for r in recs)
                  and "sandbox rebuild failed" not in out,
                  f"{len(recs)} judge session(s) retried"
                  + (f" tail={out[-120:]}" if not recs else ""))
        else:
            rec = (state.get("runs") or {}).get(run_id) or {}
            check("revise: the failed first attempt was rebuilt and the retry succeeded",
                  rec.get("status") == "done" and int(rec.get("attempts") or 0) == 2
                  and "unknown run kind" not in out and "sandbox rebuild failed" not in out,
                  f"status={rec.get('status')} attempts={rec.get('attempts')} tail={out[-140:]}")
    # ... and the rebuild covers EVERY kind, so nothing can be missing for the
    # stages this loop does not drive end to end (see test_kind_support_tables).
    check("the rebuild table covers the revise/integrate/judge/rewrite kinds explicitly",
          hasattr(nb, "REBUILD_HANDLERS")
          and {"revise", "integrate", "judge", "rewrite", "review", "audit"}
          <= set(nb.REBUILD_HANDLERS))


def test_misplaced_revision_ledger_is_adopted_end_to_end():
    print()
    print("== E. end to end: a reviser's ledger written into the sandbox root ==")
    tmp = scratch("nbt_sig_h_")
    root = make_root(tmp)
    proc = run_root(root, agent=STUB_STRAY, retries="0",
                    env={"NBT_STRAY_DELIVERABLE": "r1_a2_revise:revision_report.json"})
    out = proc.stdout + proc.stderr
    state = state_of(root)
    rec = (state.get("runs") or {}).get("r1_a2_revise") or {}
    sb = leaf(root, "runs/r1_a2_revise", "runs/r1_a2_revise_try1_failed")
    check("the revision PASSED although its ledger was written into the sandbox root",
          rec.get("status") == "done" and int(rec.get("attempts") or 0) == 1,
          f"status={rec.get('status')} attempts={rec.get('attempts')} tail={out[-160:]}")
    check("the ledger now sits in revised/",
          (sb / "revised" / "revision_report.json").is_file()
          and not (sb / "revision_report.json").is_file())
    check("the adoption is recorded as a warning naming the source path",
          any("revision_report.json" in w and "ADOPTED" in w
              for w in ((rec.get("postcheck") or {}).get("warnings") or [])),
          str(((rec.get("postcheck") or {}).get("warnings") or [])[:1])[:200])
    check("the console reports the adoption too", "ADOPTED" in out)
    check("the round completed", ((state.get("rounds") or {}).get("1") or {}).get("status")
          == "done")
    pkg_files = [p.name for p in (sb / "revised").rglob("*") if p.is_file()]
    check("the package the pipeline judged still carries its own content files",
          len([n for n in pkg_files if not nb.is_bookkeeping_name(n)]) >= 1
          and not (sb / "revised" / nb.MARKER_FILE).exists(), str(sorted(pkg_files)[:6]))


def judge_rec(rid="judge_tok9_j1"):
    return {"id": rid, "kind": "judge", "round": 1, "label_map": {"v1": "w1"},
            "judge_target_token": "tok9", "target_id": "w1", "judge_index": 1,
            "contract": nb.JUDGE_CONTRACT_VERSION}


def judge_sheet(check_id, score=1, tier="writing", severity="minor"):
    return {"run_id": "judge_tok9_j1", "target_id": "tok9", "judge_index": 1,
            "comparisons": [{"opponent_label": "v1", "score": score, "basis": tier,
                             "reason": "one comparison for the stub",
                             "resolved": [{"tier": tier, "severity": severity,
                                           "evidence": "the sentence repeats itself",
                                           "check": check_id}],
                             "introduced": [],
                             "checks": {c: "clean" for c in nb.JUDGE_COVERAGE_CHECKS}}]}


def test_judge_check_ids_the_prompt_names_are_accepted():
    print()
    print("== F. the ids the JUDGE PROMPT names are not rejected by the validator ==")
    if not hasattr(nb, "WRITING_RUBRIC_CHECK"):
        check("the writing rubric's items map onto the check that owns them (J3)", False,
              "this build has no WRITING_RUBRIC_CHECK / Q-item mapping")
        return
    check("the writing rubric's items are normalized to the check that owns them (J3)",
          all(nb._norm_check_id(q) == nb.WRITING_RUBRIC_CHECK
              for q in ("Q1", "Q6", "Q7", "Q11", "Q12", "q6", " Q 7 ")),
          str([nb._norm_check_id(q) for q in ("Q1", "Q6", "Q7", "Q11", "Q12")]))
    check("a sweep rule id still normalizes to M20, and a frozen id is untouched",
          nb._norm_check_id("FMT-T9C") == "M20" and nb._norm_check_id("fmt-p1") == "M20"
          and nb._norm_check_id("J3") == "J3" and nb._norm_check_id("M21") == "M21")
    check("anything else is left exactly as written",
          nb._norm_check_id("ZZ9") == "ZZ9" and nb._norm_check_id(None) == "")
    for cid in ("Q1", "Q6", "Q7", "Q11", "Q12", "J3", "FMT-T9c"):
        errs, warns = nb.validate_judge_sheet(judge_sheet(cid), judge_rec())
        check(f"a ledger row citing {cid!r} is ACCEPTED (no error, no warning)",
              errs == [] and warns == [], f"errs={errs[:1]} warns={warns[:1]}")
    # an id nobody recognizes may not cost a 20-40 minute session: the row still
    # counts for the arithmetic, and the id is reported for the human.
    errs, warns = nb.validate_judge_sheet(judge_sheet("ZZ9"), judge_rec())
    check("an unrecognized id is a WARNING that names what to cite, never a failure",
          errs == [] and any("ZZ9" in w and "not a frozen check id" in w for w in warns),
          f"errs={errs[:1]} warns={warns[:1]}")
    sheet = judge_sheet("ZZ9", score=2, tier="consistency", severity="major")
    errs, warns = nb.validate_judge_sheet(sheet, judge_rec())
    check("... and the row still counts for the derived score",
          errs == [] and nb.derived_comparison_score(sheet["comparisons"][0]) == 2,
          str(nb.derived_comparison_score(sheet["comparisons"][0])))


def test_judge_prompt_gets_a_blinding_safe_preflight():
    print()
    print("== F. the judge prompt carries a pre-flight without leaking provenance ==")
    prompt = nb.judge_prompt(Path("/tmp/x"), "judge_tok9_j1", 1, "tok9", 1, 3, ["v1", "v2"])
    check("the pre-flight block is in the judge prompt",
          "PRE-FLIGHT CHECK" in prompt
          and "selfcheck --sandbox . --stage judge" in prompt)
    check("no unresolved prompt token is left",
          "@@JUDGE_SELFCHECK@@" not in prompt and "@@WRITING_RUBRIC@@" not in prompt)
    check("the rubric still says what to cite AND what the check cell carries",
          "Q7" in prompt and getattr(nb, "WRITING_RUBRIC_CHECK", "J3") in prompt
          and "Q1-Q11 correspond one-to-one to the" in prompt)
    # The blinding rule is the reason this block was withheld from the judge
    # prompt before: keep the same forbidden vocabulary as test_judge_blinding.
    forbidden = {
        r"\bround\b": "the word 'round'", r"\barm\b": "the word 'arm'",
        r"\brewrite\b": "the word 'rewrite'", r"\brevised\b": "the word 'revised'",
        r"\brevision\b": "the word 'revision'", r"\bintegration\b": "the word 'integration'",
        r"\bmerge\b": "the word 'merge'", r"\bchampion\b": "the word 'champion'",
        r"\b(?:a1|a2|w1|i1)\b": "an arm id", r"\br\d+_judge": "a round-prefixed run id",
        r"CHANGELOG": "a bookkeeping name", r"MANUAL_STEPS": "a bookkeeping name",
        r"REVISION_REPORT": "a bookkeeping name", r"DIFF_LEDGER": "a bookkeeping name",
        r"AUTHOR TO COMPLETE": "the pipeline's own marker token",
    }
    hits = {label: re.findall(pat, prompt, re.I)
            for pat, label in forbidden.items() if re.findall(pat, prompt, re.I)}
    check("the judge prompt still carries NO provenance vocabulary", hits == {}, str(hits))


def test_judge_selfcheck_catches_a_bad_sheet():
    print()
    print("== F. the judge's own pre-flight reproduces the postcheck's verdict ==")
    if not hasattr(nb, "sandbox_selfcheck"):
        check("sandbox_selfcheck() exists", False, "this build has no sandbox_selfcheck")
        return
    tmp = scratch("nbt_sig_f_")

    def build(sheet):
        jsb = tmp / f"judge_tok9_j1_{len(list(tmp.iterdir()))}"
        (jsb / "field" / "v1").mkdir(parents=True)
        write(jsb / "judge_review" / "inventory.md", "# inventory\n")
        write(jsb / "scores.json", sheet)
        write(jsb / nb.MARKER_FILE, {"stage": "judge", "run_id": sheet["run_id"],
                                     "status": "complete"})
        return jsb

    # the real failure shape: Q-rubric ids in the ledger rows
    sb = build(judge_sheet("Q11"))
    ok, errs, warns = nb.sandbox_selfcheck(sb, "judge", "judge_tok9_j1", 0)
    check("a sheet citing Q11 passes the pre-flight (the 2026-09-23 false failure)",
          ok and not errs, str(errs)[:200])
    # plus the second problem of that panel: an integer the rows cannot back
    bad = judge_sheet("Q11", score=3, tier="writing", severity="minor")
    sb2 = build(bad)
    errs2 = nb.sandbox_selfcheck(sb2, "judge", "judge_tok9_j1", 0)[1]
    check("a score its own rows cannot back is caught before the marker",
          any("contradicts its own ledger" in e for e in errs2), str(errs2)[:200])


def test_process_died_after_the_audit_finished():
    print()
    print("== E. a crashed process with a complete audit sandbox is re-verified ==")
    tmp = scratch("nbt_sig_g_")
    root = make_root(tmp)
    ctx = nb.Ctx(root)
    ctx.load()
    sb = root / "runs" / "r1_audit"
    (sb / "audit").mkdir(parents=True)
    rec = ctx.register("r1_audit", "audit", 1, "runs/r1_audit")
    check("an empty audit sandbox is NOT 'likely complete'",
          nb.likely_complete_artifacts(ctx, rec) is False)
    write(sb / "audit" / "audit.json", {"dispositions": []})
    check("a complete audit sheet IS 'likely complete' (re-verify, not re-run)",
          nb.likely_complete_artifacts(ctx, rec) is True)
    check("the audit's own sheet is part of the structured-output parse gate",
          "audit/audit.json" in nb.STRUCTURED_OUTPUT_JSON.get("audit", ()))


def main() -> int:
    test_kind_support_tables()
    test_rebuild_recreates_an_audit_sandbox()
    test_audit_retry_completes_the_round()
    test_relocation_semantics()
    test_misplaced_marker_is_adopted_end_to_end()
    test_foreign_stray_marker_fails_with_its_path()
    test_short_rows_are_named()
    test_selfcheck()
    test_prompts_state_the_marker_location()
    test_misplaced_deliverable_is_rescued()
    test_selfcheck_covers_the_other_stages()
    test_other_stages_recover_from_a_failed_attempt()
    test_misplaced_revision_ledger_is_adopted_end_to_end()
    test_judge_check_ids_the_prompt_names_are_accepted()
    test_judge_prompt_gets_a_blinding_safe_preflight()
    test_judge_selfcheck_catches_a_bad_sheet()
    test_process_died_after_the_audit_finished()
    cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

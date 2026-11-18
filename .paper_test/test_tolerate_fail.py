#!/usr/bin/env python3
"""`--tolerate-fail`: use a run's best failed trial when its retries run out.

The policy is OFF by default in paper-refine and the off path is the historical
strict one:

  * every attempt a run is allowed is a hard `FAIL`: the round stays incomplete
    and `run` exits 3;
  * `--tolerate-fail` (recorded by `setup`, overridable by `run`) prints the
    exhausted run as `TOLERATED_FAIL`, chooses its best failed trial (most
    required output files produced in the stage's own output area, then fewest
    FAIL messages, then the latest attempt), moves that trial into the run's
    sandbox and marks the run `done` with a `tolerated_fail` record, so the
    stages that depend on it continue on the most complete attempt;
  * the round's decision stays PROVISIONAL and is never certified; a run with no
    usable trial (no required output at all) is still a hard FAIL, and
    `--no-tolerate-fail` restores the strict path for one invocation.

The agent here is `/bin/sh -c 'exit 1'`: every session fails immediately, so the
end-to-end checks exercise the failure path without any model or network. The
trial-selection checks build a small fake root and call the pipeline helper
directly, because a real agent is not needed to test the ordering.

Run:  python3 .paper_test/test_tolerate_fail.py
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
PIPELINE = WS / "paper_pipeline.py"
FAIL_AGENT = '["/bin/sh","-c","exit 1"]'
TMPDIRS = []
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def cli(*argv, timeout=300):
    return subprocess.run([sys.executable, str(PIPELINE), *argv],
                          capture_output=True, text=True, timeout=timeout)


def load_pipeline():
    spec = importlib.util.spec_from_file_location("paper_pipeline_under_test", PIPELINE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["paper_pipeline_under_test"] = module
    spec.loader.exec_module(module)
    return module


def make_source(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\nA short synthetic abstract for the failure-path test.\n\n"
        "Introduction\n\nWe study a synthetic system and report one result.\n\n"
        "Methods\n\nWe ran the test once.\n", encoding="utf-8")
    return src


def setup_root(tmp: Path, *extra, champion_select: str = "revise") -> Path:
    src = make_source(tmp)
    root = tmp / "root"
    args = ["setup", "--source", str(src), "--root", str(root),
            "--round-indices", "-1", "--venue", "generic",
            "--journal", "Journal of Synthetic Methods", *extra]
    if champion_select:
        args += ["--champion-select", champion_select]
    proc = cli(*args)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return root


def run_root(root: Path, *extra, retries: str = "2"):
    return cli("run", "--root", str(root), "--agent-cmd", FAIL_AGENT,
               "--retries", retries, "--no-redline", "--no-track",
               "--no-defect-audit", "--no-conflict-agent", "--jobs", "1", *extra)


def state(root: Path) -> dict:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))


def round_one(root: Path) -> dict:
    return state(root).get("rounds", {}).get("1") or {}


class FakeCtx:
    """The slice of Ctx that the trial helper touches (no pipeline state)."""

    def __init__(self, tmp: Path, cfg=None):
        self.root = tmp
        self.runs_dir = tmp / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = dict(cfg or {})
        self.logs = []

    def sandbox_of(self, rec):
        return self.runs_dir / rec["id"]

    def save_state(self):
        pass

    def log(self, *args, **kwargs):
        self.logs.append((args, kwargs))


def _trial(root: Path, name: str, files: list, errors: list) -> Path:
    sb = root / "runs" / name
    (sb / "guided_review").mkdir(parents=True, exist_ok=True)
    for f in files:
        (sb / "guided_review" / f).write_text("# synthetic review file\n", encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(
        json.dumps({"run_id": "r1_a2_revise", "kind": "revise"}), encoding="utf-8")
    (sb / "record.json").write_text(
        json.dumps({"attempt": 1, "kind": "revise", "errors": errors}), encoding="utf-8")
    return sb


def test_best_trial_selection() -> None:
    pp = load_pipeline()
    tmp = scratch("tf-select-")
    ctx = FakeCtx(tmp, {"tolerate_fail": "on"})
    rid = "r1_a2_revise"
    rec = {"id": rid, "kind": "guided_review", "status": "failed", "attempt": 3,
           "attempts_log": [{"attempt": 3, "ok": False, "errors": ["e3a", "e3b"]}]}
    # try 1: one output file, two FAIL messages
    _trial(tmp, f"{rid}_try1_failed", ["a.md"], ["e1a", "e1b"])
    # try 2: two output files, one FAIL message -- the most complete
    _trial(tmp, f"{rid}_try2_failed", ["a.md", "b.md"], ["e2a"])
    # current attempt: one output file, two FAIL messages
    active = ctx.sandbox_of(rec)
    (active / "guided_review").mkdir(parents=True)
    (active / "guided_review" / "c.md").write_text("# current\n", encoding="utf-8")
    (active / "_pipeline_done.json").write_text("{}", encoding="utf-8")
    pp.use_best_failed_trial(ctx, rec)
    check("a tolerated run becomes done", rec.get("status") == "done", rec.get("status"))
    tf = rec.get("tolerated_fail") or {}
    check("the most complete trial is chosen", tf.get("outputs") == 3, tf)
    check("the tie-break counts FAIL messages", tf.get("fail_messages") == 1, tf)
    check("the chosen trial is the active sandbox",
          (active / "guided_review" / "a.md").is_file()
          and (active / "guided_review" / "b.md").is_file(),
          sorted(p.name for p in (active / "guided_review").iterdir()))
    check("the last attempt is kept as evidence",
          (ctx.runs_dir / f"{rid}_try3_failed").is_dir(),
          sorted(p.name for p in ctx.runs_dir.iterdir()))


def test_trial_selection_tie_break_and_none() -> None:
    pp = load_pipeline()
    tmp = scratch("tf-tie-")
    ctx = FakeCtx(tmp, {"tolerate_fail": "on"})
    rid = "r1_guided_review"
    rec = {"id": rid, "kind": "guided_review", "status": "failed", "attempt": 2,
           "attempts_log": [{"attempt": 2, "ok": False, "errors": ["x"]}]}
    _trial(tmp, f"{rid}_try1_failed", ["a.md", "b.md"], ["e1", "e2"])
    _trial(tmp, f"{rid}_try2_failed", ["a.md", "b.md"], ["e1"])
    active = ctx.sandbox_of(rec)
    (active / "guided_review").mkdir(parents=True)
    (active / "guided_review" / "c.md").write_text("# current\n", encoding="utf-8")
    (active / "_pipeline_done.json").write_text("{}", encoding="utf-8")
    pp.use_best_failed_trial(ctx, rec)
    tf = rec.get("tolerated_fail") or {}
    check("equal outputs: fewer FAIL messages wins", tf.get("fail_messages") == 1, tf)
    # No output anywhere -> no usable trial, the run stays failed.
    tmp2 = scratch("tf-none-")
    ctx2 = FakeCtx(tmp2, {"tolerate_fail": "on"})
    rec2 = {"id": "r1_guided_review", "kind": "guided_review", "status": "failed",
            "attempt": 1,
            "attempts_log": [{"attempt": 1, "ok": False, "errors": ["x"]}]}
    (ctx2.sandbox_of(rec2) / "guided_review").mkdir(parents=True)
    used = pp.use_best_failed_trial(ctx2, rec2)
    check("a trial with no required output is not used", used is False and
          rec2.get("status") == "failed", (used, rec2.get("status")))
    # The policy off leaves even a complete trial alone.
    tmp3 = scratch("tf-off-")
    ctx3 = FakeCtx(tmp3, {"tolerate_fail": "off"})
    rec3 = {"id": "r1_guided_review", "kind": "guided_review", "status": "failed",
            "attempt": 1,
            "attempts_log": [{"attempt": 1, "ok": False, "errors": ["x"]}]}
    _trial(tmp3, "r1_guided_review_try1_failed", ["a.md"], ["e"])
    used3 = pp.use_best_failed_trial(ctx3, rec3)
    check("the policy off never promotes a trial", used3 is False and
          rec3.get("status") == "failed", (used3, rec3.get("status")))


def test_strict_default() -> None:
    tmp = scratch("tf-strict-")
    root = setup_root(tmp)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("setup writes no tolerate_fail key by default", "tolerate_fail" not in cfg)
    proc = run_root(root)
    check("strict run exits 3", proc.returncode == 3, f"rc={proc.returncode}")
    check("strict run prints a [FAIL] summary",
          "[r1] FAIL:" in proc.stdout, proc.stdout[-1200:])
    check("strict run never prints TOLERATED_FAIL",
          "TOLERATED_FAIL" not in proc.stdout, proc.stdout[-1200:])
    check("strict round stays incomplete",
          (round_one(root).get("status") or "") != "done",
          round_one(root).get("status"))


def test_setup_records_and_run_override() -> None:
    tmp = scratch("tf-on-")
    root = setup_root(tmp, "--tolerate-fail")
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("setup records tolerate_fail=on", cfg.get("tolerate_fail") == "on",
          cfg.get("tolerate_fail"))
    proc = run_root(root, "--no-tolerate-fail")
    check("run --no-tolerate-fail restores the strict exit", proc.returncode == 3,
          f"rc={proc.returncode}")
    check("run --no-tolerate-fail prints the strict policy",
          "failure policy: off" in proc.stdout, proc.stdout[-600:])
    # With the policy on and an agent that produces no required output, there is
    # no usable trial: the run must stay a hard FAIL (never invent a trial).
    tmp2 = scratch("tf-on-nofiles-")
    root2 = setup_root(tmp2, "--tolerate-fail")
    proc2 = run_root(root2)
    check("on-policy run with no usable trial exits 3", proc2.returncode == 3,
          f"rc={proc2.returncode}\n{proc2.stdout[-1200:]}")
    check("on-policy run with no usable trial prints no TOLERATED_FAIL status",
          "[TOLERATED_FAIL] r1_" not in proc2.stdout, proc2.stdout[-1200:])


def test_run_enables_it_on_a_strict_root() -> None:
    tmp = scratch("tf-run-on-")
    root = setup_root(tmp)
    proc = run_root(root, "--tolerate-fail")
    check("run --tolerate-fail prints the enabled policy",
          "failure policy: on" in proc.stdout, proc.stdout[-800:])
    # No output from the failing agent -> still strict.
    check("no usable trial still exits 3", proc.returncode == 3,
          f"rc={proc.returncode}")


def test_tolerated_trial_is_used_end_to_end() -> None:
    # A stub agent writes a completion marker plus the minimum output each stage
    # needs (an empty review finding list, an audit report, the revised base
    # documents) and then exits 1. Every stage exhausts its retries, each best
    # trial is promoted, and the auto-promoted round closes with a2 -- but the
    # decision must stay PROVISIONAL and refuse certification.
    tmp = scratch("tf-e2e-")
    stub = tmp / "stub.sh"
    stub.write_text(
        "#!/bin/sh\n"
        "mkdir -p guided_review cold_start_review audit revised concerns\n"
        "echo '[]' > guided_review/findings.json\n"
        "echo '[]' > guided_review/findings_extra.json\n"
        "echo '[]' > cold_start_review/findings_cold_start_review.json\n"
        "printf '# Audit\\n\\nNo findings.\\n' > audit/AUDIT_REPORT.md\n"
        "if [ -d base ]; then cp -a base/. revised/ 2>/dev/null || true; fi\n"
        "printf '# Change\\n' > revised/CHANGELOG.md\n"
        "printf '{\"run_id\":\"x\",\"kind\":\"x\"}\\n' > _pipeline_done.json\n"
        "exit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    root = setup_root(tmp, "--tolerate-fail")
    proc = cli("run", "--root", str(root), "--agent-cmd", json.dumps([str(stub)]),
               "--retries", "1", "--retry-backoff", "0", "--no-redline",
               "--no-track", "--no-defect-audit", "--no-conflict-agent", "--jobs", "1")
    check("end-to-end tolerated run exits 0", proc.returncode == 0,
          f"rc={proc.returncode}\n{proc.stdout[-2000:]}")
    check("the exhausted stages print TOLERATED_FAIL",
          "[TOLERATED_FAIL]" in proc.stdout, proc.stdout[-2000:])
    rec = round_one(root)
    check("the round closes with the promoted trial", rec.get("champion") == "a2",
          rec.get("champion"))
    check("the tolerated round is not certified", rec.get("certified") is False,
          rec.get("certified"))
    tf = rec.get("tolerated_fail") or {}
    check("the round records the tolerated runs",
          set(tf.get("failed_runs") or []) >= {"r1_guided_review", "r1_a2_revise"}, tf)
    a2 = (state(root).get("runs") or {}).get("r1_a2_revise") or {}
    check("the revise run is done with a promoted trial",
          a2.get("status") == "done" and bool(a2.get("tolerated_fail")), a2.get("status"))
    check("the promoted candidate has a corpus digest", bool(a2.get("corpus_digest")),
          a2.get("corpus_digest"))
    dec = cli("decide", "--root", str(root))
    check("decide refuses to certify a tolerated round", dec.returncode == 5,
          f"rc={dec.returncode}\n{dec.stdout[-1600:]}")
    decision = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    cert = decision.get("certification") or {}
    check("decision.json is NOT certified and provisional",
          cert.get("certified") is False and cert.get("provisional") is True, cert)
    check("decision.json names the tolerated stage blocker",
          any("TOLERATED_FAIL" in str(p) for p in cert.get("blockers") or []),
          cert.get("blockers"))


def test_legacy_switch_is_accepted() -> None:
    tmp = scratch("tf-legacy-")
    root = setup_root(tmp, "--almost-fail")
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("the legacy --almost-fail records tolerate_fail=on",
          cfg.get("tolerate_fail") == "on", cfg.get("tolerate_fail"))


def main() -> int:
    try:
        test_best_trial_selection()
        test_trial_selection_tie_break_and_none()
        test_strict_default()
        test_setup_records_and_run_override()
        test_run_enables_it_on_a_strict_root()
        test_tolerated_trial_is_used_end_to_end()
        test_legacy_switch_is_accepted()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): " + ", ".join(FAILS))
        return 1
    print("all tolerate-fail checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

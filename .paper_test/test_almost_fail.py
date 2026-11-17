#!/usr/bin/env python3
"""`--almost-fail`: an exhausted stage is a warning, not a lost invocation.

The policy is OFF by default and the off path is the historical strict one:

  * a stage that exhausts its retry budget prints `[FAIL]`, the round stays
    incomplete and `run` exits 3;
  * `--almost-fail` (recorded by `setup`, overridable by `run`) prints
    `[ALMOST_FAIL]`, keeps the invocation going, closes an auto-promoted round
    with its base when the promised candidate never finished (PROVISIONAL,
    never certified), and exits 0;
  * `--no-almost-fail` restores the strict path for one invocation.

The agent here is `/bin/sh -c 'exit 1'`: every session fails immediately, so
the test exercises the failure path without any model or network.

Run:  python3 .paper_test/test_almost_fail.py
"""
from __future__ import annotations

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


def run_root(root: Path, *extra):
    return cli("run", "--root", str(root), "--agent-cmd", FAIL_AGENT,
               "--retries", "0", "--no-redline", "--no-track",
               "--no-defect-audit", "--no-conflict-agent", "--jobs", "1", *extra)


def state(root: Path) -> dict:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))


def round_one(root: Path) -> dict:
    return state(root).get("rounds", {}).get("1") or {}


def test_strict_default() -> None:
    tmp = scratch("af-strict-")
    root = setup_root(tmp)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("setup writes no almost_fail key by default", "almost_fail" not in cfg)
    proc = run_root(root)
    check("strict run exits 3", proc.returncode == 3, f"rc={proc.returncode}")
    check("strict run prints [FAIL]",
          "[FAIL] r1_guided_review" in proc.stdout, proc.stdout[-800:])
    check("strict round stays incomplete",
          (round_one(root).get("status") or "") != "done",
          round_one(root).get("status"))


def test_setup_enables_it() -> None:
    tmp = scratch("af-on-")
    root = setup_root(tmp, "--almost-fail")
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("setup records almost_fail=on", cfg.get("almost_fail") == "on", cfg.get("almost_fail"))
    proc = run_root(root)
    check("almost-fail run exits 0", proc.returncode == 0,
          f"rc={proc.returncode}\n{proc.stdout[-1200:]}")
    check("run prints [ALMOST_FAIL]",
          "[ALMOST_FAIL] r1_guided_review" in proc.stdout, proc.stdout[-1200:])
    check("run prints no [FAIL] status",
          "[FAIL] r1_" not in proc.stdout, proc.stdout[-1200:])
    rec = round_one(root)
    check("round closes with the base", rec.get("champion") == "a1", rec.get("champion"))
    af = rec.get("almost_fail") or {}
    check("round records the fallback", bool(af.get("fallback")) is True, af)
    check("round is provisional, not certified",
          bool(rec.get("auto_promoted")) and not bool(rec.get("certified")),
          (rec.get("auto_promoted"), rec.get("certified")))
    winner = root / "round1_winner"
    check("round winner is published", winner.is_dir() and any(winner.iterdir()))
    round_json = json.loads((root / "reports" / "round1.json").read_text(encoding="utf-8"))
    check("round JSON carries the fallback",
          bool((round_json.get("round_record") or {}).get("almost_fail", {}).get("fallback")),
          round_json.get("round_record", {}).get("almost_fail"))


def test_judge_mode_stays_strict() -> None:
    # ALMOST_FAIL has a defined fallback only for the no-judge modes. A judge
    # round must not be decided on a shrunken field, so it stays pending even
    # though the invocation itself exits 0.
    tmp = scratch("af-judge-")
    root = setup_root(tmp, "--almost-fail", champion_select="")
    proc = run_root(root)
    check("judge-mode almost-fail run exits 0", proc.returncode == 0,
          f"rc={proc.returncode}\n{proc.stdout[-1200:]}")
    rec = round_one(root)
    check("judge-mode round stays pending", rec.get("status") != "done", rec.get("status"))
    check("judge-mode round has no champion", not rec.get("champion"), rec.get("champion"))
    check("judge-mode round publishes no winner", not (root / "round1_winner").exists())
    check("judge-mode run says no champion is the final answer",
          "no champion is the final answer yet" in proc.stdout, proc.stdout[-800:])


def test_decide_accepts_the_fallback() -> None:
    # `decide` must not call a DECLARED fallback an inconsistent record: the
    # round is PROVISIONAL, and the promised-vs-stored mismatch is the recorded
    # reason, not corruption.
    tmp = scratch("af-decide-")
    root = setup_root(tmp, "--almost-fail")
    run_root(root)
    proc = cli("decide", "--root", str(root))
    check("decide exits 0 for a fallback round", proc.returncode == 0,
          f"rc={proc.returncode}\n{proc.stdout[-1200:]}")
    check("decide names the fallback",
          "recorded ALMOST_FAIL fallback" in proc.stdout, proc.stdout[-800:])
    check("decide does not call the fallback inconsistent",
          "inconsistent" not in proc.stdout, proc.stdout[-800:])


def test_run_overrides_the_root() -> None:
    tmp = scratch("af-override-")
    root = setup_root(tmp, "--almost-fail")
    proc = run_root(root, "--no-almost-fail")
    check("run --no-almost-fail restores the strict exit", proc.returncode == 3,
          f"rc={proc.returncode}")
    check("run --no-almost-fail prints [FAIL]",
          "[FAIL] r1_guided_review" in proc.stdout, proc.stdout[-800:])


def test_run_enables_it_on_a_strict_root() -> None:
    tmp = scratch("af-run-on-")
    root = setup_root(tmp)
    proc = run_root(root, "--almost-fail")
    check("run --almost-fail exits 0 on a strict root", proc.returncode == 0,
          f"rc={proc.returncode}\n{proc.stdout[-1200:]}")
    check("round closes with the base", round_one(root).get("champion") == "a1",
          round_one(root).get("champion"))


def main() -> int:
    try:
        test_strict_default()
        test_setup_enables_it()
        test_judge_mode_stays_strict()
        test_decide_accepts_the_fallback()
        test_run_overrides_the_root()
        test_run_enables_it_on_a_strict_root()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): " + ", ".join(FAILS))
        return 1
    print("all almost-fail checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

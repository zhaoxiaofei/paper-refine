#!/usr/bin/env python3
"""Scheduling tests: every round step starts as soon as its inputs exist.

Run:  python3 .paper_test/test_parallel_scheduling.py

The round is a DAG, not a pipeline of barriers:

    a1 (copy)
      +-- w1..wM  rewrites   } start TOGETHER (both only need the base)
      +-- review             }
    review
      +-- a2..a{1+N} revisions   start the moment the review marker exists,
                                 WITHOUT waiting for the rewrites
    pool = {a1, w1..wM, a2..a{1+N}}
      +-- i1..iK integrations    start only once the WHOLE pool is done
    field deduplicated
      +-- judge sessions         start once the field is complete

The stub agent records start/end timestamps per session (`stub_timed.py`), so
each claim is measured rather than assumed. `--jobs` still caps the number of
concurrent sessions.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
STUB = HERE / "stub_timed.py"
STUB_JUDGE = HERE / "stub_judge.py"
FAILS = []
TMPDIRS = []


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


def run_round(tmp: Path, *, rewrites: str, revises: str, jobs: int, sleeps: dict,
              retries: str = "0", extra_env: dict = None):
    source = tmp / "source"
    (source / "raw_figs").mkdir(parents=True)
    (source / "manuscript-b.md").write_text("title\n", encoding="utf-8")
    (source / "raw_figs" / "data.tsv").write_text("a\tb\n", encoding="utf-8")
    root = tmp / "root"
    log = tmp / "timing.log"
    subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                    "--source", str(source), "--root", str(root), "--rounds", "1",
                    "--judges", "2", "--rewrites", rewrites, "--revises", revises],
                   capture_output=True, text=True, check=True)
    env = dict(os.environ)
    env["PAPER_TIMING_LOG"] = str(log)
    for key, value in sleeps.items():
        env[key] = str(value)
    env.update(extra_env or {})
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "run",
                           "--root", str(root), "--jobs", str(jobs),
                           "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
                           # the judge wave runs through the same instrumented stub, so its
                           # sessions are measured too (the generic stub judge is enough here:
                           # this suite is about WHEN sessions start, not how they score)
                           "--judge-agent-cmd", json.dumps([sys.executable, str(STUB)]),
                           "--retries", str(retries),
                           # the tests measure SCHEDULING, not the backoff wait
                           "--retry-backoff", "0"],
                          capture_output=True, text=True, timeout=900, env=env)
    spans = {}
    for line in log.read_text(encoding="utf-8").splitlines() if log.is_file() else []:
        parts = line.split()
        if len(parts) != 3:
            continue
        event, name, ts = parts[0], parts[1], float(parts[2])
        span = spans.setdefault(name, {})
        # A retried session logs start/fail/start/end; keying one slot per event
        # made the retry's own start<end the only thing a check could see. Keep
        # the attempt boundaries so the retry can be compared with the failure.
        if event == "start":
            span.setdefault("start", ts)
            span["last_start"] = ts
        elif event == "fail":
            span.setdefault("first_fail", ts)
            span["end"] = ts
        else:
            span["end"] = ts
    return root, proc, spans


def overlap(a: dict, b: dict) -> bool:
    return (a["start"] < b["end"]) and (b["start"] < a["end"])


def max_concurrency(spans: dict) -> int:
    events = []
    for span in spans.values():
        if "start" in span and "end" in span:
            events.append((span["start"], 1))
            events.append((span["end"], -1))
    events.sort(key=lambda e: (e[0], e[1]))       # a start before an end at the same instant
    cur = best = 0
    for _ts, delta in events:
        cur += delta
        best = max(best, cur)
    return best


def test_dag_scheduling():
    print("== the round's steps run as soon as their inputs exist ==")
    tmp = scratch("paper_sched_")
    # 2026-09-22: the revise now waits for review + AUDIT, so the rewrite arms are
    # given more headroom: the case must still show "no barrier on the rewrites",
    # not measure how fast this machine can postcheck an extra session.
    # The windows the assertions depend on must survive a LOADED box: with
    # `.paper_test/run_all.py` running 8 suites at once, a 0.3 s session could start
    # after its sibling had already finished (overlap assertion) or the revise's
    # own chain (review + audit + two postchecks) could outlast a 3 s rewrite --
    # both failed for the machine's load, not for a scheduling barrier. The slow
    # rewrites are therefore 6 s and the phases whose PARALLELISM is asserted are
    # 1.5 s / 1.0 s, so the suite measures the graph, not the CPU.
    sleeps = {"PAPER_TIMING_SLEEP_W": 6.0,     # rewrites: the slowest production arm
              "PAPER_TIMING_SLEEP_R": 0.6,     # review: finishes long before them
              "PAPER_TIMING_SLEEP_AU": 0.4,    # auditor: between the review and the revise
              "PAPER_TIMING_SLEEP_V": 0.5,     # revise
              "PAPER_TIMING_SLEEP_I": 1.5,     # integrations (parallelism is asserted)
              "PAPER_TIMING_SLEEP_J": 1.0}     # judges (parallelism is asserted)
    root, proc, spans = run_round(tmp, rewrites="2", revises="1", jobs=8, sleeps=sleeps)
    out = proc.stdout + proc.stderr
    check("the round completes", proc.returncode == 0, out[-300:])
    names = sorted(spans)
    check("every expected session was instrumented",
          set(names) >= {"r1_w1", "r1_w2", "r1_review", "r1_audit", "r1_a2_revise",
                         "r1_i1", "r1_i2", "r1_i3", "r1_i4"}
          and sum(1 for n in names if ("_judge_" in n or n.startswith("judge_"))) == 16,
          str(names[:6]) + f" ... {len(names)} total")
    w1, w2, rev = spans["r1_w1"], spans["r1_w2"], spans["r1_review"]
    check("the two rewrites run in parallel with each other", overlap(w1, w2),
          f"w1 {w1['start']:.2f}-{w1['end']:.2f} w2 {w2['start']:.2f}-{w2['end']:.2f}")
    check("the REVIEW runs in parallel with the rewrites (no stage barrier)",
          overlap(rev, w1) and overlap(rev, w2),
          f"review {rev['start']:.2f}-{rev['end']:.2f}")
    check("the review finishes BEFORE the slow rewrites (so a revise can start early)",
          rev["end"] < w1["start"] + sleeps["PAPER_TIMING_SLEEP_W"] - 0.3,
          f"review end {rev['end']:.2f} vs rewrite end {w1['end']:.2f}")
    a2 = spans["r1_a2_revise"]
    # 2026-09-22: the auditor sits between the review and the revisers (default
    # `--audit on`), so the revise starts after the AUDIT -- still without waiting
    # for the slow rewrites, which is what this case is about. The auditor's own
    # session is part of the wave and is asserted to run in parallel.
    aud = spans.get("r1_audit")
    check("the auditor runs between the review and the revise",
          aud is not None and aud["start"] >= rev["end"] - 0.05
          and a2["start"] >= aud["end"] - 0.05,
          f"review end {rev['end']:.2f} audit {aud and (aud['start'], aud['end'])} "
          f"revise {a2['start']:.2f}")
    check("the REVISE starts before the slow rewrites finish (no barrier on them)",
          a2["start"] < w1["end"] and a2["start"] < w2["end"],
          f"revise start {a2['start']:.2f} vs rewrite ends {w1['end']:.2f}/{w2['end']:.2f}")
    check("the revise does not start before the review ends",
          a2["start"] >= rev["end"] - 0.05,
          f"revise {a2['start']:.2f} review end {rev['end']:.2f}")
    pool_end = max(w1["end"], w2["end"], a2["end"])
    integrations = {n: s for n, s in spans.items() if re.search(r"_i\d+$", n)}
    check("EVERY integration starts only after the WHOLE pool is done",
          all(s["start"] >= pool_end - 0.05 for s in integrations.values()),
          f"pool end {pool_end:.2f}, earliest integration "
          f"{min(s['start'] for s in integrations.values()):.2f}")
    first, second = sorted(integrations.values(), key=lambda s: s["start"])[:2]
    check("the integrations run in parallel with each other", overlap(first, second))
    judge_spans = [s for n, s in spans.items() if ("_judge_" in n or n.startswith("judge_"))]
    integ_end = max(s["end"] for s in integrations.values())
    check("the judge wave starts only after the last integration",
          min(s["start"] for s in judge_spans) >= integ_end - 0.05,
          f"integrations end {integ_end:.2f}, first judge "
          f"{min(s['start'] for s in judge_spans):.2f}")
    j_first, j_second = sorted(judge_spans, key=lambda s: s["start"])[:2]
    check("judge sessions run in parallel with each other", overlap(j_first, j_second))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("the round is decided normally",
          state["rounds"]["1"]["status"] == "done"
          and state["rounds"]["1"]["field"] == ["orig", "w1", "w2", "a2", "i1", "i2", "i3", "i4"],
          str(state["rounds"]["1"].get("field")))
    check("the printed plan names the parallel schedule",
          "Sessions start as soon as their inputs exist" in out, out[-200:])


def test_jobs_cap_is_respected():
    print()
    print("== --jobs still caps concurrent sessions ==")
    tmp = scratch("paper_sched1_")
    sleeps = {"PAPER_TIMING_SLEEP": 0.25}
    root, proc, spans = run_round(tmp, rewrites="2", revises="1", jobs=1, sleeps=sleeps)
    check("the serialised round still completes", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-200:])
    check("with --jobs 1 no two sessions overlap", max_concurrency(spans) == 1,
          f"max concurrency {max_concurrency(spans)} over {len(spans)} sessions")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("with --jobs 1 the dependency order is still respected",
          state["rounds"]["1"]["status"] == "done")


def test_dependency_order_is_never_violated():
    print()
    print("== dependencies hold even when the pool is large ==")
    tmp = scratch("paper_sched2_")
    sleeps = {"PAPER_TIMING_SLEEP_W": 0.4, "PAPER_TIMING_SLEEP_R": 0.2,
              "PAPER_TIMING_SLEEP_V": 0.2, "PAPER_TIMING_SLEEP_I": 0.2,
              "PAPER_TIMING_SLEEP_J": 0.1}
    root, proc, spans = run_round(tmp, rewrites="2", revises="2", jobs=12, sleeps=sleeps)
    out = proc.stdout + proc.stderr
    check("the M=2/N=2 round completes", proc.returncode == 0, out[-200:])
    pool = ["r1_w1", "r1_w2", "r1_a2_revise", "r1_a3_revise"]
    integrations = {n: s for n, s in spans.items() if re.search(r"_i\d+$", n)}
    check("all K = 1+M+N = 5 integrations ran", len(integrations) == 5, str(sorted(integrations)))
    pool_end = max(spans[n]["end"] for n in pool)
    check("no integration started while a pool member was still running",
          all(s["start"] >= pool_end - 0.05 for s in integrations.values()),
          f"pool end {pool_end:.2f} vs first integration "
          f"{min(s['start'] for s in integrations.values()):.2f}")
    judges = [s for n, s in spans.items() if ("_judge_" in n or n.startswith("judge_"))]
    integ_end = max(s["end"] for s in integrations.values())
    check("no judge started while an integration was still running",
          min(s["start"] for s in judges) >= integ_end - 0.05,
          f"integrations end {integ_end:.2f} vs first judge {min(s['start'] for s in judges):.2f}")
    # field = orig + (w1, w2, a2, a3) + (i1..i5) = 10 members, 2 judges each
    check("all ten field members were judged (2 judges each)",
          len(judges) == 20, str(len(judges)))


def test_retry_policy_survives_the_scheduler():
    print()
    print("== a failed session is still retried with a rebuilt sandbox ==")
    tmp = scratch("paper_sched3_")
    sleeps = {"PAPER_TIMING_SLEEP": 0.2}
    root, proc, spans = run_round(tmp, rewrites="1", revises="1", jobs=4, sleeps=sleeps,
                                  retries="1",
                                  extra_env={"PAPER_TIMING_FAIL_ONCE": "r1_a2_revise"})
    out = proc.stdout + proc.stderr
    check("the round completes although one session failed once", proc.returncode == 0,
          out[-300:])
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_a2_revise"]
    check("the failed session was retried (>= 2 attempts) and ended done",
          rec["status"] == "done" and rec["attempts"] >= 2,
          f"status={rec['status']} attempts={rec['attempts']}")
    check("the retry started AFTER the first attempt failed",
          spans.get("r1_a2_revise", {}).get("last_start", 0)
          >= spans.get("r1_a2_revise", {}).get("first_fail", float("inf")),
          str(spans.get("r1_a2_revise")))
    check("the round still produced a champion",
          state["rounds"]["1"]["status"] == "done" and
          state["rounds"]["1"].get("champion") is not None,
          str(state["rounds"]["1"].get("champion")))


def test_permanent_failure_keeps_the_round_undecided():
    print()
    print("== a permanently failed session keeps the round undecided ==")
    tmp = scratch("paper_sched4_")
    sleeps = {"PAPER_TIMING_SLEEP": 0.1}
    root, proc, spans = run_round(tmp, rewrites="1", revises="1", jobs=4, sleeps=sleeps,
                                  retries="1",
                                  extra_env={"PAPER_TIMING_ALWAYS_FAIL": "r1_a2_revise"})
    out = proc.stdout + proc.stderr
    check("`run` exits non-zero when a session cannot finish", proc.returncode != 0,
          str(proc.returncode))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_a2_revise"]
    check("the failing session tried the whole retry budget",
          rec["status"] == "failed" and rec["attempts"] == 2,
          f"status={rec['status']} attempts={rec['attempts']}")
    check("the round is NOT decided on a shrunk pool",
          state["rounds"]["1"]["status"] != "done"
          and not state["rounds"]["1"].get("champion"), str(state["rounds"]["1"].get("champion")))
    check("no pin/winner was published from the incomplete round",
          not (root / "pinned" / "r1_a2").exists()
          and not (root / "round1_winner").exists())
    check("the integration runs dependent on the failed session never started",
          all(not re.search(r"_i\d+$", name) for name in spans),
          str(sorted(spans)))


def test_broken_marker_is_a_failed_attempt():
    print()
    print("== a marker that fails its postcheck is retried, never spun on ==")
    tmp = scratch("paper_sched5_")
    sleeps = {"PAPER_TIMING_SLEEP": 0.1}
    start = time.time()
    root, proc, spans = run_round(tmp, rewrites="1", revises="1", jobs=4, sleeps=sleeps,
                                  retries="1",
                                  extra_env={"PAPER_TIMING_BAD_MARKER": "r1_w1"})
    elapsed = time.time() - start
    out = proc.stdout + proc.stderr
    check("the run terminates instead of spinning on the broken marker", elapsed < 240,
          f"{elapsed:.1f}s")
    check("`run` reports the round as incomplete", proc.returncode != 0, str(proc.returncode))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_w1"]
    check("the broken marker was treated as a FAILED ATTEMPT (whole retry budget used)",
          rec["status"] == "failed" and rec["attempts"] == 2,
          f"status={rec['status']} attempts={rec['attempts']}")
    checks = sum(1 for line in out.splitlines() if "stage mismatch" in line)
    check("the postcheck error is the stage mismatch the stub wrote",
          checks > 0 and "stage mismatch" in out, out[-200:])
    check("the downstream integration runs never started from the broken package",
          all(not re.search(r"_i\d+$", name) for name in spans), str(sorted(spans)))


def main() -> int:
    sections = (("dag", test_dag_scheduling),
                ("jobs", test_jobs_cap_is_respected),
                ("order", test_dependency_order_is_never_violated),
                ("retry", test_retry_policy_survives_the_scheduler),
                ("hard-fail", test_permanent_failure_keeps_the_round_undecided),
                ("bad-marker", test_broken_marker_is_a_failed_attempt))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL SCHEDULING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

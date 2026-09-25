#!/usr/bin/env python3
"""Run every `.paper_test/test_*.py` suite, in parallel.

Sequential, the suites take about five and a half minutes and most of that is
waiting on stub agents, LibreOffice, pdflatex and sleeps. They are independent
(each builds its own root under `tempfile.mkdtemp`, and the fixed paths they use
are per-suite), so they can run at once:

    python3 .paper_test/run_all.py                 # GNU parallel, jobs = #cores
    python3 .paper_test/run_all.py -j 4            # cap the parallelism
    python3 .paper_test/run_all.py -j 1            # exactly the old sequential loop
    python3 .paper_test/run_all.py --only test_pipeline.py test_docx_format.py
    python3 .paper_test/run_all.py --engine python # no GNU parallel on this box

Every suite runs through `run_one.sh`, which gives it a private TMPDIR
(`$rundir/tmp/<suite>`) and captures its output to `$rundir/<suite>.log` plus its
status/timing in `$rundir/status/`. The runner prints one line per suite and a
total; a suite that fails is RE-RUN ALONE once (`--no-rerun` disables that), so a
timing-sensitive suite that only failed because 15 others were competing is
reported as `flaky` instead of a false alarm -- and a suite that fails alone too
is a real failure, with its `[FAIL]` lines quoted.

Exit status: 0 when every suite passed (a flaky suite that passed alone counts as
passed, but is named), 1 when one failed both ways, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
RUN_ONE = HERE / "run_one.sh"


def suites() -> list:
    return sorted(p.name for p in HERE.glob("test_*.py"))


def run_dir_under(path: str = None) -> Path:
    """A fresh directory for logs/status/tmp (or the one the operator named)."""
    if path:
        p = Path(path).resolve()
        if p.exists() and any(p.iterdir()):
            sys.exit(f"--logs {p} is not empty; choose a fresh directory")
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path(tempfile.mkdtemp(prefix="paper-tests-"))


def run_one(suite: str, rundir: Path, python: str) -> None:
    env = dict(os.environ,
               PAPER_TEST_RUNDIR=str(rundir), PAPER_TEST_WS=str(WS), PAPER_TEST_PYTHON=python)
    subprocess.run(["/bin/sh", str(RUN_ONE), suite], env=env, check=False)


def result_of(suite: str, rundir: Path) -> tuple:
    """(exit status, wall seconds) as `run_one.sh` recorded them."""
    rc_file = rundir / "status" / f"{suite}.rc"
    time_file = rundir / "status" / f"{suite}.time"
    rc = int(rc_file.read_text().strip()) if rc_file.is_file() else 1
    start = end = None
    if time_file.is_file():
        parts = time_file.read_text().split()
        if len(parts) == 2:
            start, end = float(parts[0]), float(parts[1])
    return rc, (end - start) if start is not None else None


def parallel_available() -> bool:
    return shutil.which("parallel") is not None


def engine_parallel(todo: list, jobs: int, rundir: Path, python: str) -> None:
    """GNU parallel drives `run_one.sh`; `{}` is the suite name."""
    env = dict(os.environ,
               PAPER_TEST_RUNDIR=str(rundir), PAPER_TEST_WS=str(WS), PAPER_TEST_PYTHON=python)
    proc = subprocess.run(["parallel", "--jobs", str(jobs), "--no-notice",
                           "--joblog", str(rundir / "joblog"),
                           f"{RUN_ONE} {{}}"],
                          input="\n".join(todo) + "\n", text=True, env=env, check=False)
    if proc.returncode not in (0,) and not any(
            (rundir / "status" / f"{s}.rc").is_file() for s in todo):
        sys.exit("GNU parallel failed before running any suite (see its output above)")


def engine_python(todo: list, jobs: int, rundir: Path, python: str) -> None:
    """Fallback for a box without GNU parallel: the same helper, thread-pooled."""
    with futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        list(ex.map(lambda s: run_one(s, rundir, python), todo))


def tail_failures(suite: str, rundir: Path, limit: int = 6) -> list:
    log = rundir / f"{suite}.log"
    if not log.is_file():
        return []
    lines = [ln.rstrip() for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
             if "[FAIL]" in ln]
    return lines[:limit]


def summary_line(suite: str, rc: int, secs: float, width: int) -> str:
    tag = "PASS" if rc == 0 else "FAIL"
    dur = f"{secs:.1f}s" if secs is not None else "-"
    return f"  {tag:<5} {suite:<{width}} {dur:>8}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the .paper_test suites in parallel.")
    ap.add_argument("-j", "--jobs", type=int, default=0,
                    help="parallel sessions (default: min(CPU count, 8) -- see the docstring; "
                         "`-j 1` is the old sequential loop)")
    ap.add_argument("--only", nargs="+", metavar="SUITE",
                    help="run these suites only (names with or without .py)")
    ap.add_argument("--engine", choices=("auto", "parallel", "python"), default="auto",
                    help="GNU parallel (default when installed), or the built-in thread pool")
    ap.add_argument("--logs", metavar="DIR",
                    help="keep logs/status/timing here (default: a fresh temp directory)")
    ap.add_argument("--no-rerun", action="store_true",
                    help="do not re-run a failed suite alone (see the docstring)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="stream each suite's log to the terminal as it finishes")
    ap.add_argument("--list", action="store_true", help="list the suites and exit")
    args = ap.parse_args()

    all_suites = suites()
    if args.list:
        print("\n".join(all_suites))
        return 0
    if not all_suites:
        sys.exit(f"no test_*.py suites under {HERE}")
    todo = all_suites
    if args.only:
        wanted = {n if n.endswith(".py") else f"{n}.py" for n in args.only}
        unknown = sorted(wanted - set(all_suites))
        if unknown:
            sys.exit(f"unknown suite(s): {', '.join(unknown)} (see --list)")
        todo = [s for s in all_suites if s in wanted]

    engine = args.engine
    if engine == "auto":
        engine = "parallel" if parallel_available() else "python"
    if engine == "parallel" and not parallel_available():
        sys.exit("--engine parallel was asked for, but `parallel` is not on PATH")
    # Measured on the 20-core dev box: 8 jobs run the whole set in ~108 s and 20
    # jobs in ~110 s -- the heavy suites (stub rounds, LibreOffice, pdflatex) keep
    # every core busy either way, and the extra sessions only add contention (and
    # with it the chance of a timing suite reporting a load flake). `-j N` overrides.
    jobs = args.jobs if args.jobs > 0 else min(os.cpu_count() or 1, 8, len(todo))
    jobs = max(1, min(jobs, len(todo)))
    rundir = run_dir_under(args.logs)
    python = os.environ.get("PAPER_TEST_PYTHON") or sys.executable

    print(f"[tests] {len(todo)} suite(s), jobs={jobs}, engine={engine}, "
          f"logs={rundir}")
    started = time.time()
    results = {}
    if engine == "parallel":
        engine_parallel(todo, jobs, rundir, python)
    else:
        engine_python(todo, jobs, rundir, python)
    for suite in todo:
        results[suite] = result_of(suite, rundir)
    phase_wall = time.time() - started

    width = max(len(s) for s in todo)
    for suite in todo:
        rc, secs = results[suite]
        line = summary_line(suite, rc, secs, width)
        if rc == 0 and args.verbose:
            line += f"   {rundir / f'{suite}.log'}"
        print(line)

    failed = [s for s in todo if results[s][0] != 0]
    flaky = []
    if failed and not args.no_rerun:
        print(f"\n[tests] {len(failed)} suite(s) failed under load; re-running each ALONE "
              f"(--no-rerun disables this)")
        for suite in failed:
            quiet = rundir / "alone"
            quiet.mkdir(exist_ok=True)
            run_one(suite, quiet, python)
            rc, secs = result_of(suite, quiet)
            if rc == 0:
                flaky.append(suite)
                print(f"[tests] {suite}: FLKY -- passed alone in {secs:.0f}s "
                      f"(load-sensitive, not a real failure); full log: "
                      f"{quiet / f'{suite}.log'}")
            else:
                print(f"[tests] {suite}: FAILS ALONE TOO ({secs:.0f}s) -- real failure")
        failed = [s for s in failed if s not in flaky]

    for suite in failed:
        print(f"\n[tests] {suite}: first failing checks (full log: {rundir / f'{suite}.log'})")
        for line in tail_failures(suite, rundir):
            print(f"    {line}")

    passed = len(todo) - len(failed) - len(flaky)
    wall = time.time() - started
    phase = "" if abs(wall - phase_wall) < 1 else f" (wall {wall:.0f}s incl. the alone re-runs)"
    print(f"\n[tests] {len(todo)} suite(s) in {phase_wall:.0f}s{phase}: {passed} passed"
          + (f", {len(flaky)} flaky{flaky}" if flaky else "")
          + (f", {len(failed)} FAILED {failed}" if failed else "")
          + f"  (logs: {rundir})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

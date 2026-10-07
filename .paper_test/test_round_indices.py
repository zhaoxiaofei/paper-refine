#!/usr/bin/env python3
"""`setup --round-indices`: run a SUBSET of the built-in round schedule.

Run:  python3 .paper_test/test_round_indices.py

The built-in schedule (DEFAULTS) has three entries: round 1 stages the two
from-scratch rewrites and every integration arm; round 2 has no rewrites and
every integration arm; round 3 is the final review/revise round with no
rewrites and NO integration arm. `--round-indices` selects which entries the
pipeline's own rounds follow:

  * `--round-indices 2 3` implies `--rounds 2` and makes pipeline rounds 1-2
    adopt schedule entries 2 and 3 (no rewrites; no integration in the second);
  * `--round-indices 3` / `--round-indices -1` run only the final schedule
    round (no rewrites, no integrations);
  * `--round-indices 1 2` is byte-equivalent to `--rounds 2`;
  * out-of-range/zero/duplicate/descending indices, mixing with the per-round
    flags the schedule owns, and scoped journal modes are refused.
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
STUB_JUDGE = WS / ".paper_test" / "stub_judge.py"
spec = importlib.util.spec_from_file_location("paper_ri", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_ri"] = nb
spec.loader.exec_module(nb)

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


def make_source(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.txt").write_text(
        "Abstract\nWe used scRNA-seq to profile the cells.\n\n"
        "Introduction\nscRNA-seq was performed once and the claims follow.\n", encoding="utf-8")
    return src


def run_setup(src: Path, root: Path, *extra, timeout=600):
    return subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--source", str(src),
         "--root", str(root), *map(str, extra)],
        capture_output=True, text=True, timeout=timeout)


def cfg_of(root: Path) -> dict:
    path = root / "pipeline_config.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


KEYS = ("rounds", "rewrites", "revises", "integrators", "review_scope", "judges")


def test_two_of_three():
    print()
    print("== RI1: --round-indices 2 3 runs schedule rounds 2 and 3 as pipeline rounds 1-2 ==")
    tmp = scratch("paper_ri_23_")
    src = make_source(tmp)
    root = tmp / "root"
    r = run_setup(src, root, "--round-indices", "2", "3")
    cfg = cfg_of(root)
    check("RI1 setup accepts the option", r.returncode == 0, (r.stdout + r.stderr)[-300:])
    check("RI1 it implies --rounds 2 (and says so)",
          "implies --rounds 2" in r.stdout and cfg.get("rounds") == 2,
          str(cfg.get("rounds")) + r.stdout[-200:])
    check("RI1 the per-round plan comes from schedule rounds 2 and 3",
          cfg.get("rewrites") == [0, 0] and cfg.get("revises") == [1, 1]
          and cfg.get("integrators") == [nb.INTEGRATOR_ALL, 0]
          and cfg.get("review_scope") == ["full", "full"]
          and cfg.get("round_indices") == [2, 3],
          str({k: cfg.get(k) for k in KEYS + ("round_indices",)}))
    check("RI1 setup prints the mapping",
          "round indices:" in r.stdout and "schedule round(s) 2, 3" in r.stdout,
          r.stdout[-300:])
    ctx = nb.Ctx(root)
    ctx.load()
    check("RI1 the plan has no rewrites and one revision per round",
          nb.round_counts(ctx, 1) == (0, 1) and nb.round_counts(ctx, 2) == (0, 1))
    check("RI1 only the first pipeline round integrates",
          bool(nb.round_integrated_run_ids(ctx, 1))
          and not nb.round_integrated_run_ids(ctx, 2),
          f"{nb.round_integrated_run_ids(ctx, 1)} / {nb.round_integrated_run_ids(ctx, 2)}")


def test_last_round_forms():
    print()
    print("== RI2: 3 and -1 both select the final schedule round ==")
    tmp = scratch("paper_ri_last_")
    src = make_source(tmp)
    cfgs = {}
    for tag, args in (("three", ("3",)), ("minus_one", ("-1",))):
        root = tmp / f"root_{tag}"
        r = run_setup(src, root, "--round-indices", *args)
        check(f"RI2 `--round-indices {' '.join(args)}` is accepted",
              r.returncode == 0, (r.stdout + r.stderr)[-300:])
        cfgs[tag] = cfg_of(root)
    check("RI2 both run exactly one round",
          all(c.get("rounds") == 1 for c in cfgs.values()), str(cfgs))
    check("RI2 the final round has no rewrites and no integrations",
          all(c.get("rewrites") == [0] and c.get("integrators") == [0]
              and c.get("round_indices") == [3] for c in cfgs.values()), str(cfgs))
    ctx = nb.Ctx(tmp / "root_three")
    ctx.load()
    check("RI2 no integration run is planned",
          nb.round_integrated_run_ids(ctx, 1) == [],
          str(nb.round_integrated_run_ids(ctx, 1)))


def test_prefix_equivalence():
    print()
    print("== RI3: --round-indices 1 2 is the --rounds 2 default plan ==")
    tmp = scratch("paper_ri_prefix_")
    src = make_source(tmp)
    r1 = run_setup(src, tmp / "indices", "--round-indices", "1", "2")
    r2 = run_setup(src, tmp / "rounds", "--rounds", "2")
    a, b = cfg_of(tmp / "indices"), cfg_of(tmp / "rounds")
    check("RI3 both setups succeed", r1.returncode == 0 and r2.returncode == 0,
          (r1.stdout + r1.stderr + r2.stdout + r2.stderr)[-300:])
    check("RI3 the effective plans are identical",
          all(a.get(k) == b.get(k) for k in KEYS),
          f"{ {k: a.get(k) for k in KEYS} } vs { {k: b.get(k) for k in KEYS} }")
    check("RI3 only the indices root records the mapping",
          a.get("round_indices") == [1, 2] and not b.get("round_indices"), str(b))


def test_refusals():
    print()
    print("== RI4: invalid selections and conflicting flags are refused ==")
    tmp = scratch("paper_ri_bad_")
    src = make_source(tmp)
    cases = ((("4",), "outside the built-in schedule"),
             (("0",), "0 is not a round"),
             (("2", "2"), "repeated round"),
             (("3", "2"), "ascending run order"))
    for args, want in cases:
        r = run_setup(src, tmp / ("root_" + "_".join(args)), "--round-indices", *args)
        check(f"RI4 {args} is refused", r.returncode != 0 and want in (r.stdout + r.stderr),
              (r.stdout + r.stderr)[-200:])
    r = run_setup(src, tmp / "root_rewrite", "--round-indices", "2", "--rewrites", "1")
    check("RI4 --rewrites conflicts with --round-indices",
          r.returncode != 0 and "do not pass --rewrites" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-220:])
    r = run_setup(src, tmp / "root_scoped", "--round-indices", "2",
                  "--revision-mode", "major")
    check("RI4 a scoped journal mode conflicts with --round-indices",
          r.returncode != 0 and "concern-scoped round" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-220:])


def test_last_round_e2e():
    print()
    print("== RI5: a final-round run stages no rewrite and no integration ==")
    tmp = scratch("paper_ri_e2e_")
    src = make_source(tmp)
    root = tmp / "root"
    r = run_setup(src, root, "--round-indices", "-1", "--judges", "1")
    check("RI5 setup succeeds", r.returncode == 0, (r.stdout + r.stderr)[-300:])
    r = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "run", "--root", str(root),
         "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
         "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
         "--timeout", "300", "--retries", "0"], capture_output=True, text=True, timeout=900)
    check("RI5 the run completes", r.returncode == 0, (r.stdout + r.stderr)[-500:])
    runs = root / "runs"
    check("RI5 no rewrite run was staged", not (runs / "r1_w1").exists())
    check("RI5 no integration run was staged", not (runs / "r1_i1").exists())
    check("RI5 the review/revision/judge chain ran",
          (runs / "r1_review").is_dir() and (runs / "r1_a2_revise").is_dir()
          and any(p.name.startswith("judge_") for p in runs.iterdir()),
          str(sorted(p.name for p in runs.iterdir())))
    st = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "status",
                         "--root", str(root)], capture_output=True, text=True, timeout=300)
    check("RI5 status names the schedule mapping",
          "round indices: pipeline rounds 1..1 follow built-in schedule round(s) 3" in st.stdout,
          st.stdout[-400:])


def main() -> int:
    sections = (("two-of-three", test_two_of_three),
                ("last-round", test_last_round_forms),
                ("prefix", test_prefix_equivalence),
                ("refusals", test_refusals),
                ("e2e", test_last_round_e2e))
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
    print("ALL round-indices CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

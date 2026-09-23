#!/usr/bin/env python3
"""`run --only <stages>`: run a subset of the round's stages in one invocation.

Run:  python3 .nbt_test/test_stage_subset.py

The pipeline's resumable round plan lets an operator run only the stages they
need -- e.g. re-run just the review, just the revise sessions, just the
integrations ("merge from the other versions"), or only the judge wave -- and
resume the rest in a later invocation. `retry --run <ID>` remains the way to
force a COMPLETED stage to run again.

The end-to-end part drives the real CLI with the repo's stub agent, so the
assertions are about actual run records, not about the parser alone.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_stage_subset", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_stage_subset"] = nb
spec.loader.exec_module(nb)

STUB = WS / ".nbt_test" / "stub_agent.py"
STUB_JUDGE = WS / ".nbt_test" / "stub_judge.py"
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


def cli(*argv, timeout=900):
    return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def make_root(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    root = tmp / "root"
    proc = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1",
               "--rewrites", "0", "--revises", "1", "--judges", "1")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return root


def run_only(root: Path, only: str, *extra):
    return cli("run", "--root", str(root), "--only", only,
               "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
               "--retries", "0", *extra)


def statuses(root: Path) -> dict:
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    return {rid: (rec.get("status"), rec.get("kind")) for rid, rec in (state.get("runs") or {}).items()}


def test_parser():
    print()
    print("== parser: stage names and aliases ==")
    check("plain names parse", nb.parse_only_stages("review,revise") == {"review", "revise"})
    check("aliases parse (merge -> integrate, a2 -> revise, w -> rewrite, j -> judge)",
          nb.parse_only_stages("w,a2,merge,j") == {"rewrite", "revise", "integrate", "judge"})
    check("whitespace and plurals are tolerated",
          nb.parse_only_stages(" rewrites , reviews ") == {"rewrite", "review"})
    check("None/empty/'all' mean every stage",
          nb.parse_only_stages(None) == set() and nb.parse_only_stages("") == set()
          and nb.parse_only_stages("all") == set())
    try:
        nb.parse_only_stages("rewrite,bogus")
        check("an unknown stage is rejected", False, "no SystemExit")
    except SystemExit as e:
        check("an unknown stage is rejected with a helpful message", e.code == 1, str(e.code))
    # Round ordinals are part of the same selection language (`--only 1,2`).
    spec = nb.parse_only_spec("1,2")
    check("--only 1,2 selects rounds 1 and 2 in full",
          spec is not None and spec.rounds == {1, 2} and spec.stages_for(1) == set(), str(spec))
    spec = nb.parse_only_spec("2:merge,3:judge")
    check("ROUND:STAGE items select one stage of one round",
          spec is not None and spec.rounds == {2, 3}
          and spec.stages_for(2) == {"integrate"} and spec.stages_for(3) == {"judge"},
          str(spec))
    spec = nb.parse_only_spec("1-3:review")
    check("round ranges expand", spec is not None and spec.rounds == {1, 2, 3}
          and spec.stages_for(2) == {"review"}, str(spec))
    check("`all` still means every round and stage",
          nb.parse_only_spec("all") is not None and nb.parse_only_spec("all").is_everything())
    for bad in ("0", "bogus", "1:bogus", "3-1"):
        try:
            nb.parse_only_spec(bad)
            check(f"--only {bad!r} is rejected", False, "no SystemExit")
        except SystemExit as e:
            check(f"--only {bad!r} is rejected", e.code == 1, str(e.code))
    spec = nb.parse_only_spec("3")
    try:
        spec.validate(2)
        check("an out-of-range round is rejected against --rounds", False, "no SystemExit")
    except SystemExit as e:
        check("an out-of-range round is rejected against --rounds", e.code == 1, str(e.code))


def test_end_to_end():
    print()
    print("== --only: review, then revise, then merge, then judge ==")
    tmp = scratch("nbt_subset_")
    root = make_root(tmp)
    # 1) review only
    p = run_only(root, "review")
    st = statuses(root)
    check("--only review runs the review", st.get(("r1_review")) == ("done", "review"), str(st))
    check("--only review does NOT run the revise/merge/judge stages",
          all((st.get(f"r1_{k}") or ("missing", None))[0] != "done"
              for k in ("a2_revise", "i1", "i2")),
          str({k: st.get(k) for k in ("r1_a2_revise", "r1_i1", "r1_i2")}))
    check("--only review reports the skipped stages and the incomplete round",
          "--only review" in (p.stdout + p.stderr)
          and "stays incomplete" in (p.stdout + p.stderr)
          and "round 1 is incomplete" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-260:])
    check("the review's M20 artifact was seeded and the run passed its contract",
          (root / "runs" / "r1_review" / "review" / "artifacts" / "M20_formatting.md").is_file()
          and (root / "runs" / "r1_review" / "review" / "work" / "FORMAT_SCAN.json").is_file())
    # 2) the auditor runs between the review and the revise; the revise REFUSES
    #    to start before it (the default plan contains the auditor).
    p = run_only(root, "revise")
    st = statuses(root)
    check("--only revise refuses to start before the auditor",
          st.get("r1_a2_revise") != ("done", "revise")
          and "audit" in (p.stdout + p.stderr).lower(),
          str({"a2": st.get("r1_a2_revise"), "out": (p.stdout + p.stderr)[-200:]}))
    p = run_only(root, "audit")
    st = statuses(root)
    check("--only audit runs the auditor", st.get("r1_audit") == ("done", "audit"),
          str(st.get("r1_audit")))
    p = run_only(root, "revise")
    st = statuses(root)
    check("--only revise runs the revise session", st.get("r1_a2_revise") == ("done", "revise"),
          str(st.get("r1_a2_revise")))
    check("--only revise does not start the integrations", st.get("r1_i1") is None, str(st.get("r1_i1")))
    # 3) merge (integration) only
    p = run_only(root, "merge")
    st = statuses(root)
    check("--only merge runs every integration",
          st.get("r1_i1") == ("done", "integrate") and st.get("r1_i2") == ("done", "integrate"),
          str({"r1_i1": st.get("r1_i1"), "r1_i2": st.get("r1_i2")}))
    # 4) judge only -> completes the round and pins the champion
    p = run_only(root, "judge")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("--only judge runs the panel and completes the round",
          (state.get("rounds", {}).get("1") or {}).get("status") == "done",
          str(state.get("rounds", {}).get("1")))
    check("a champion was pinned", bool(state.get("pinned")), str(state.get("pinned"))[:120])
    dec = cli("decide", "--root", str(root))
    check("decide succeeds on the subset-built round", dec.returncode == 0,
          (dec.stdout + dec.stderr)[-260:])
    check("the decision report notes the formatting scan",
          "formatting" in (root / "reports" / "DECISION_REPORT.md").read_text(encoding="utf-8").lower())
    # 5) the round's OWN raw scores: the flat `credited` list the printed median
    #    and mean were computed from, one row per directed score (own + received).
    with open(root / "reports" / "round1_raw_scores.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    stats = (state.get("rounds", {}).get("1") or {}).get("stats") or {}
    check("round 1 wrote reports/round1_raw_scores.csv", bool(rows) and bool(stats),
          f"{len(rows)} row(s) for {len(stats)} member(s)")
    check("every field member appears, in both directions",
          {r["member"] for r in rows} == set(stats)
          and {r["direction"] for r in rows} == {"own", "received"},
          f"members={sorted({r['member'] for r in rows})} "
          f"directions={sorted({r['direction'] for r in rows})}")
    reproduced = True
    for vid, st in stats.items():
        credited = [int(r["credited"]) for r in rows if r["member"] == vid]
        reproduced = reproduced and len(credited) == st["n"] \
            and statistics.median(credited) == st["median"] \
            and abs(statistics.fmean(credited) - float(st["mean"])) < 1e-9
    check("the recorded n/median/mean reproduce from the `credited` column", reproduced,
          str({vid: (st.get("n"), st.get("median"), st.get("mean"))
               for vid, st in list(stats.items())[:2]}))


def test_multiple_stages_and_errors():
    print()
    print("== --only with several stages, and error handling ==")
    tmp = scratch("nbt_subset2_")
    root = make_root(tmp)
    p = run_only(root, "review,audit,revise")
    st = statuses(root)
    check("--only review,audit,revise runs all three in one invocation",
          st.get("r1_review") == ("done", "review") and st.get("r1_a2_revise") == ("done", "revise"),
          str({k: st.get(k) for k in ("r1_review", "r1_a2_revise")}))
    check("the judge wave was not started",
          not any(k.startswith("r1_judge") and v[0] == "done" for k, v in st.items()), str(st))
    bad = cli("run", "--root", str(root), "--only", "rewrite,bogus")
    check("an unknown --only stage fails fast with the choices listed",
          bad.returncode != 0 and "unknown stage" in (bad.stdout + bad.stderr)
          and "integrate" in (bad.stdout + bad.stderr), (bad.stdout + bad.stderr)[-200:])
    help_out = cli("run", "--help")
    check("`run --help` documents --only, its round items and the merge alias",
          "--only SELECTION" in help_out.stdout and "merge" in help_out.stdout
          and "--only 1,2" in help_out.stdout and "ROUND:STAGE" in help_out.stdout,
          help_out.stdout[-200:])


def main() -> int:
    try:
        test_parser()
        test_end_to_end()
        test_multiple_stages_and_errors()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} STAGE-SUBSET CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL STAGE-SUBSET CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

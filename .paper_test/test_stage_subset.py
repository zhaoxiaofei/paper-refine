#!/usr/bin/env python3
"""`run --only <stages>` / `retry --runs <selection>`: the subset grammar.

Run:  python3 .paper_test/test_stage_subset.py

The pipeline's resumable round plan lets an operator run only the stages they
need -- e.g. re-run just the review, just the revise sessions, just the
integrations ("merge from the other versions"), or only the judge wave -- and
resume the rest in a later invocation. Forcing a COMPLETED stage to run again
is `retry`: `--run <ID>` names one run, `--all-failed` every failed/stale one,
and `--runs <SELECTION>` takes the SAME grammar as `run --only` (rounds, stage
classes, ROUND:STAGE, single sessions, judge selectors and judge run ids), so
the two commands select the same part of the pipeline.

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

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_stage_subset", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_stage_subset"] = nb
spec.loader.exec_module(nb)

STUB = WS / ".paper_test" / "stub_agent.py"
STUB_JUDGE = WS / ".paper_test" / "stub_judge.py"
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
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
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


def run_root(root: Path, *extra):
    """A plain `run` (every stage, every round) with the repo's stub agents."""
    return cli("run", "--root", str(root),
               "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
               "--retries", "0", *extra)


def retry_runs(root: Path, *args):
    return cli("retry", "--root", str(root), *args)


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
    tmp = scratch("paper_subset_")
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
    tmp = scratch("paper_subset2_")
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


def test_retry_runs_selection():
    """`retry --runs <SELECTION>`: the `--only` grammar, resolved to RUN RECORDS.

    The command must reset exactly the runs an equivalent `run --only` would
    have driven (never more), in the round plan's dependency order, and it must
    leave a resumable root behind: a plain `run` afterwards re-drives the reset
    sessions and re-decides the round.
    """
    print()
    print("== retry --runs: the --only grammar selects the runs to reset ==")
    tmp = scratch("paper_retry_runs_")
    root = make_root(tmp)
    p = run_root(root)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("the fixture round completes before the retries",
          p.returncode == 0
          and (state.get("rounds", {}).get("1") or {}).get("status") == "done",
          (p.stdout + p.stderr)[-200:])
    help_out = cli("retry", "--help")
    check("`retry --help` documents --runs with the --only grammar and an example",
          "--runs SELECTION" in help_out.stdout and "run --only" in help_out.stdout
          and "1:review,1:feedback" in help_out.stdout
          and "1:judge,2:feedback,2:review" in help_out.stdout,
          help_out.stdout[-300:])
    # ONE stage of one round.
    p = retry_runs(root, "--runs", "1:review")
    out = p.stdout + p.stderr
    check("retry --runs 1:review selects exactly r1_review and resets it",
          p.returncode == 0 and "[retry] runs (1): r1_review" in out
          and "r1_review" in out
          and statuses(root).get("r1_review", ("?",))[0] != "done",
          out[-260:])
    check("the round was invalidated (retry's documented round semantics)",
          (json.loads((root / "state.json").read_text(encoding="utf-8"))
           .get("rounds", {}).get("1") or {}).get("status") == "pending")
    # ONE session, by the id `agents` prints.
    p = retry_runs(root, "--runs", "r1_audit")
    out = p.stdout + p.stderr
    check("retry --runs r1_audit (a session id) selects exactly that run",
          p.returncode == 0 and "[retry] runs (1): r1_audit" in out,
          out[-200:])
    p = retry_runs(root, "--runs", "r1_w1")
    check("a session this round's plan does not have is refused (same message as --only)",
          p.returncode == 1 and "plans no session" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-200:])
    # The whole JUDGE wave, then ONE judge session by its version+index.
    p = retry_runs(root, "--runs", "1:judge")
    out = p.stdout + p.stderr
    judge_ids = [line.split(": ", 1)[1].split(", ")
                 for line in out.splitlines() if "[retry] runs (" in line]
    picked = judge_ids[0] if judge_ids else []
    check("retry --runs 1:judge selects the whole judge wave of round 1",
          p.returncode == 0 and picked and all(i.startswith("judge_") for i in picked),
          str(picked[:4]))
    p = retry_runs(root, "--runs", "r1_judge_orig_j1")
    out = p.stdout + p.stderr
    check("retry --runs r1_judge_orig_j1 selects ONE judge session",
          p.returncode == 0 and "[retry] runs (1): " in out
          and "judge_" in out.split("[retry] runs (1): ", 1)[1].split("\n", 1)[0],
          out[-200:])
    # A round in full: dependency order, the base first and the judges last.
    p = retry_runs(root, "--runs", "1")
    out = p.stdout + p.stderr
    line = next((l for l in out.splitlines() if "[retry] runs (" in l), "")
    order = [x.strip() for x in line.split(": ", 1)[1].split(",")] if ": " in line else []
    check("retry --runs 1 selects the whole round in dependency order",
          p.returncode == 0 and order[:2] == ["r1_a1", "r1_review"]
          and order[-1].startswith("judge_") and "r1_a2_revise" in order
          and "r1_i1" in order,
          str(order))
    # Error handling: the grammars fail the same way, and the selectors are
    # mutually exclusive.
    both = retry_runs(root, "--run", "r1_review", "--runs", "1:review")
    check("--run and --runs together are refused (exit 1)",
          both.returncode == 1 and "specify ONE of" in (both.stdout + both.stderr),
          (both.stdout + both.stderr)[-200:])
    bad = retry_runs(root, "--runs", "1:bogus")
    check("an unknown stage fails with the same message as `run --only`",
          bad.returncode == 1 and "unknown stage" in (bad.stdout + bad.stderr)
          and "integrate" in (bad.stdout + bad.stderr),
          (bad.stdout + bad.stderr)[-200:])
    empty = retry_runs(root, "--runs", "")
    check("an empty selection is refused",
          empty.returncode == 1 and "names nothing" in (empty.stdout + empty.stderr),
          (empty.stdout + empty.stderr)[-200:])
    beyond = retry_runs(root, "--runs", "1,2")
    check("a round this root does not have is refused",
          beyond.returncode == 1 and "do not exist" in (beyond.stdout + beyond.stderr),
          (beyond.stdout + beyond.stderr)[-200:])
    none_yet = retry_runs(root, "--runs", "1:concerns")
    check("a stage this root's plan has no sessions for names the fact and resets nothing",
          none_yet.returncode == 0 and "plans no" in (none_yet.stdout + none_yet.stderr)
          and "selects no existing run" in (none_yet.stdout + none_yet.stderr),
          (none_yet.stdout + none_yet.stderr)[-260:])
    # A roundless judge selector that names no session of ONE round must die
    # there, never fall back to "every judge of that round" (the empty set is
    # the run loop's "whole panel" sentinel; `retry` must not reset more than
    # the operator named).
    real = (nb.judgeable_ids, nb.round_judges, nb.config_rounds)
    probe_ctx = nb.Ctx(root)
    nb.judgeable_ids = lambda ctx, r: {1: ["orig"], 2: ["orig", "w2"]}[int(r)]
    nb.round_judges = lambda ctx, r: 1
    nb.config_rounds = lambda ctx: 2
    try:
        positive = nb._judge_selection_for_retry(probe_ctx, 2, "w2_j1")
        try:
            nb._judge_selection_for_retry(probe_ctx, 1, "w2_j1")
            guarded = False
        except SystemExit as e:
            guarded = e.code == 1
    finally:
        nb.judgeable_ids, nb.round_judges, nb.config_rounds = real
    check("a judge selector resolves to the sessions it names",
          positive == {("w2", 1)}, str(positive))
    check("a judge selector that names no session of a round is refused there", guarded)
    # The root is still resumable: a plain `run` re-drives the reset sessions
    # and completes the round again.
    p = run_root(root)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("the root the selection reset is resumable (a plain `run` completes it)",
          p.returncode == 0
          and (state.get("rounds", {}).get("1") or {}).get("status") == "done"
          and bool(state.get("pinned")),
          (p.stdout + p.stderr)[-200:])


def main() -> int:
    try:
        test_parser()
        test_end_to_end()
        test_multiple_stages_and_errors()
        test_retry_runs_selection()
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

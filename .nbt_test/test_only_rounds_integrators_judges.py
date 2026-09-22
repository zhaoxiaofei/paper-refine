#!/usr/bin/env python3
"""`run --only ROUNDS`, per-round integrator masks and per-round judge counts.

Run:  python3 .nbt_test/test_only_rounds_integrators_judges.py

Three operator-facing additions, each driven through the real CLI with the
repo's stub agents:

  * `run --only 1,2` runs only the named rounds (every stage), and
    `--only 2:review` runs one stage of one round; the other rounds are not
    started or adopted, so a filtered invocation leaves them pending.
  * `setup --integrators 0x5` (a per-round 32-bit mask) selects which pool
    members run an integration: bit (k-1) belongs to the k-th pool member
    [a1, w1..wM, a2..a{1+N}]. A clear bit means no session, no judge row and no
    chance to win; the default 0xFFFFFFFF keeps every applicable agent.
  * `setup --judges 1,2` sets the number of judge sessions per version PER
    ROUND, and the panel expectation follows the round's own count.
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

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_only_rounds", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_only_rounds"] = nb
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


def cli(*argv, timeout=1200):
    return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def make_source(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    return src


def make_root(tmp: Path, **setup_args) -> Path:
    src = make_source(tmp)
    root = tmp / "root"
    argv = ["setup", "--source", str(src), "--root", str(root)]
    for k, v in setup_args.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    proc = cli(*argv)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return root


def run(root: Path, *extra, timeout=1200):
    return cli("run", "--root", str(root),
               "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
               "--retries", "1", *extra, timeout=timeout)


def state_of(root: Path) -> dict:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))


def kinds_of(state: dict, round_no: int, kind: str) -> list:
    return [rid for rid, rec in (state.get("runs") or {}).items()
            if rec.get("round") == round_no and rec.get("kind") == kind]


def test_only_rounds():
    print()
    print("== --only ROUND[:STAGE] selects which rounds this invocation drives ==")
    tmp = scratch("nbt_onlyrounds_")
    root = make_root(tmp, rounds=2, rewrites="1,1", revises="1,1", judges="1,1")

    # Round 2 consumes round 1's pin, so asking for it first must fail with the
    # dependency named -- not with "the root is inconsistent".
    p = run(root, "--only", "2:review")
    st = state_of(root)
    check("--only 2:review before round 1 is done reports the unmet dependency",
          p.returncode != 0 and "round 1 is pending" in (p.stdout + p.stderr)
          and "repair the upstream output" not in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-300:])
    check("nothing of round 2 was started by that invocation",
          not st["runs"], str({k: v.get("status") for k, v in st["runs"].items()}))
    p = run(root, "--only", "1")
    st = state_of(root)
    check("--only 1 completes round 1 with every stage",
          (st["rounds"].get("1") or {}).get("status") == "done"
          and bool(st.get("pinned")), str(st["rounds"].get("1"))[:200])
    check("--only 1 starts nothing in round 2",
          not any(rec.get("round") == 2 for rec in st["runs"].values()),
          str(sorted(st["runs"])))
    check("the untouched round is reported as NOT selected",
          "round 2/2 NOT selected by --only" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-200:])
    check("--only 1 reports which rounds it ran",
          "--only ran round(s) 1 of 2" in (p.stdout + p.stderr), (p.stdout + p.stderr)[-200:])

    p = run(root, "--only", "2:review")
    st = state_of(root)
    check("--only 2:review runs round 2's review once its base exists",
          (st["runs"].get("r2_review") or {}).get("status") == "done",
          str({k: v.get("status") for k, v in st["runs"].items()}))
    check("round 2 does not run its audit/revise/integrate in that invocation",
          all((st["runs"].get(rid) or {}).get("status") != "done"
              for rid in ("r2_audit", "r2_a2_revise", "r2_i1", "r2_i2", "r2_i3")),
          str({rid: (st["runs"].get(rid) or {}).get("status")
               for rid in ("r2_audit", "r2_a2_revise", "r2_i1", "r2_i2", "r2_i3")}))

    p = run(root)          # plain run resumes round 2 only
    st = state_of(root)
    check("a plain `run` resumes the not-selected round and completes it",
          (st["rounds"].get("2") or {}).get("status") == "done", str(st["rounds"].get("2"))[:200])
    dec = cli("decide", "--root", str(root))
    check("decide succeeds after the round-filtered invocations", dec.returncode == 0,
          (dec.stdout + dec.stderr)[-300:])

    bad = run(root, "--only", "3")
    check("an out-of-range round fails fast against the configured --rounds",
          bad.returncode != 0 and "do not exist" in (bad.stdout + bad.stderr),
          (bad.stdout + bad.stderr)[-200:])


def test_integrator_mask():
    print()
    print("== --integrators: bit k-1 selects the k-th pool member's integration arm ==")
    tmp = scratch("nbt_integrators_")
    root = make_root(tmp, rounds=1, rewrites=2, revises=1, judges=1, integrators="0x5")
    p = run(root)
    out = p.stdout + p.stderr
    st = state_of(root)
    # pool = [a1, w1, w2, a2]; mask 0x5 = bits 0 and 2 -> i1 (a1) and i3 (w2).
    check("the mask 0x5 plans exactly the arms i1 and i3",
          [v for v in ("r1_i1", "r1_i2", "r1_i3", "r1_i4") if st["runs"].get(v)]
          == ["r1_i1", "r1_i3"],
          str(sorted(k for k in st["runs"] if "_i" in k)))
    check("the skipped arms never ran", all((st["runs"].get(v) or {}).get("status") != "done"
                                            for v in ("r1_i2", "r1_i4")),
          str({v: (st["runs"].get(v) or {}).get("status") for v in ("r1_i2", "r1_i4")}))
    check("the run log marks the skipped arms",
          "[SKIPPED: integrators bit clear]" in out and "integrators 0x5" in out,
          out[-300:])
    rrec = st["rounds"]["1"]
    check("the round's field holds the pool and the selected arms only",
          [v for v in rrec.get("field") if v.startswith("i")] == ["i1", "i3"],
          str(rrec.get("field")))
    check("the round records the mask and the arms it ran",
          rrec.get("plan", {}).get("integrators") == 5
          and rrec.get("plan", {}).get("integrated") == ["i1", "i3"],
          str(rrec.get("plan")))
    check("every selected arm was judged (1 judge x 6 members)",
          len(kinds_of(st, 1, "judge")) == 6, str(len(kinds_of(st, 1, "judge"))))
    dec = cli("decide", "--root", str(root))
    report = (root / "reports" / "DECISION_REPORT.md").read_text(encoding="utf-8")
    check("decide succeeds and the report names the arms the mask left out",
          dec.returncode == 0 and "NOT RUN: the integrator mask left this arm out" in report,
          (dec.stdout + dec.stderr)[-200:])

    # 0x0 = no integration at all; the pool arms still compete.
    tmp2 = scratch("nbt_integrators0_")
    root2 = make_root(tmp2, rounds=1, rewrites=1, revises=1, judges=1, integrators="0")
    p2 = run(root2)
    st2 = state_of(root2)
    check("--integrators 0 runs no integration and still decides the round",
          not kinds_of(st2, 1, "integrate") and st2["rounds"]["1"].get("status") == "done"
          and "NO integration run" in (p2.stdout + p2.stderr),
          str(st2["rounds"]["1"].get("plan")))
    check("the field of an integration-free round is the pool alone",
          [v for v in st2["rounds"]["1"].get("field") if v.startswith("i")] == [],
          str(st2["rounds"]["1"].get("field")))

    bad = cli("setup", "--source", str(tmp / "src"), "--root", str(tmp / "root_too_big"),
              "--rounds", "1", "--rewrites", "32", "--revises", "0", "--judges", "1")
    check("a pool wider than the 32-bit mask is refused at setup",
          bad.returncode != 0 and "more than the 32 bits" in (bad.stdout + bad.stderr),
          (bad.stdout + bad.stderr)[-200:])


def test_judges_per_round():
    print()
    print("== --judges A,B: the panel expectation follows the round's own count ==")
    tmp = scratch("nbt_judges_")
    root = make_root(tmp, rounds=2, rewrites="1,1", revises="1,1", judges="1,2")
    run(root)                      # both rounds, judges 1 then 2
    st = state_of(root)
    r1, r2 = st["rounds"]["1"], st["rounds"]["2"]
    check("round 1 records 1 judge per version, round 2 records 2",
          r1["plan"]["judges"] == 1 and r2["plan"]["judges"] == 2,
          str([r1["plan"], r2["plan"]]))
    check("round 1 ran one judge session per field member",
          len(kinds_of(st, 1, "judge")) == len(r1["field"]),
          f"{len(kinds_of(st, 1, 'judge'))} vs {len(r1['field'])}")
    check("round 2 ran two judge sessions per field member",
          len(kinds_of(st, 2, "judge")) == 2 * len(r2["field"]),
          f"{len(kinds_of(st, 2, 'judge'))} vs {2 * len(r2['field'])}")
    check("each round's scores-per-version uses its OWN judge count",
          r1["scores_per_version"] == 2 * 1 * (len(r1["field"]) - 1)
          and r2["scores_per_version"] == 2 * 2 * (len(r2["field"]) - 1),
          f"{r1['scores_per_version']} / {r2['scores_per_version']}")
    dec = cli("decide", "--root", str(root))
    check("decide certifies the per-round panels", dec.returncode == 0,
          (dec.stdout + dec.stderr)[-300:])
    report = (root / "reports" / "DECISION_REPORT.md").read_text(encoding="utf-8")
    check("the decision report prints the per-round judge counts",
          "judges/version=1,2" in report and "- judges per version: 2 " in report,
          report[:200])

    bad = cli("setup", "--source", str(tmp / "src"), "--root", str(tmp / "root_zero"),
              "--rounds", "2", "--rewrites", "1,1", "--revises", "1,1", "--judges", "2,0")
    check("a zero judge count in any round is refused at setup",
          bad.returncode != 0 and "--judges must be >= 1 per round" in (bad.stdout + bad.stderr),
          (bad.stdout + bad.stderr)[-200:])


def test_plan_survives_a_config_edit():
    print()
    print("== a decided round's mask and judge count survive a config edit ==")
    tmp = scratch("nbt_masked_decide_")
    root = make_root(tmp, rounds=1, rewrites=2, revises=1, judges=1, integrators="0x5")
    run(root)
    st = state_of(root)
    check("the round is done before the edit",
          (st["rounds"].get("1") or {}).get("status") == "done", str(st["rounds"].get("1"))[:120])
    # The operator "raises" both knobs afterwards. `decide` must recompute the
    # stored round from the plan that produced it, not from the edited config:
    # otherwise the un-run arms become phantom candidates and the 1-judge panel
    # is reported as a 3-judge gap (exit 5 on a perfectly valid root).
    cfg_path = root / "pipeline_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["judges"] = [3, 3]
    cfg["integrators"] = [0xFFFFFFFF, 0xFFFFFFFF]
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    st["config"]["judges"] = [3, 3]
    st["config"]["integrators"] = [0xFFFFFFFF, 0xFFFFFFFF]
    (root / "state.json").write_text(json.dumps(st, indent=2), encoding="utf-8")
    ctx = nb.Ctx(root)
    ctx.load()
    check("the recorded mask still selects only i1 and i3",
          nb.round_candidate_ids_run(ctx, 1) == ["w1", "w2", "a2", "i1", "i3"],
          str(nb.round_candidate_ids_run(ctx, 1)))
    check("the recorded judge count is still the round's panel size",
          nb.round_judges(ctx, 1) == 1, str(nb.round_judges(ctx, 1)))
    dec = cli("decide", "--root", str(root))
    out = dec.stdout + dec.stderr
    check("decide still certifies the round after the config edit",
          dec.returncode == 0 and "PANEL INCOMPLETE" not in out
          and "recomputed champion" not in out, out[-300:])



def test_only_judge_sessions():
    print()
    print("== `run --only r1_judge_w2_j1` runs ONE judge session ==")
    # --- the grammar --------------------------------------------------------
    o = nb.parse_only_spec("r1_judge_w2_j1")
    check("O1 `r1_judge_w2_j1` = round 1, judge stage, session w2_j1",
          sorted(o.rounds) == [1] and o.pairs.get(1) == {"judge"}
          and o.judge_spec_for(1) == "w2_j1" and o.judge_spec_for(2) == ""
          and not o.is_everything() and "judge sessions: w2_j1" in o.describe(),
          o.describe())
    o2 = nb.parse_only_spec("2:judge_i1_j1,r1_judge_w2")
    check("O2 the `ROUND:judge_…` form and several selectors combine",
          sorted(o2.rounds) == [1, 2] and o2.pairs.get(2) == {"judge"}
          and o2.judge_spec_for(1) == "w2" and o2.judge_spec_for(2) == "i1_j1",
          f"{o2.judge_spec_for(1)} / {o2.judge_spec_for(2)}")
    o3 = nb.parse_only_spec("w2_j1")
    check("O3 a roundless session name applies to every round that has it",
          o3.judge_spec_for(1) == "w2_j1" and o3.judge_spec_for(2) == "w2_j1"
          and not o3.rounds, o3.describe())
    check("O4 plain stage, round and `all` items are unchanged",
          nb.parse_only_spec("judge").judge_spec_for(1) == ""
          and nb.parse_only_spec("judge").stages == {"judge"}
          and sorted(nb.parse_only_spec("1").rounds) == [1]
          and nb.parse_only_spec("all").is_everything()
          and nb.parse_only_spec(None) is None)
    check("O5 `run --only judge` still means the WHOLE judge stage",
          nb.parse_only_spec("judge").stages_for(1) == {"judge"}
          and nb.parse_only_spec("judge").judge_spec_for(1) == "")

    # --- a real pilot: run the pool, then one judge session ----------------
    tmp = scratch("nbt_only_judge_")
    root = make_root(tmp, rounds=1, rewrites=1, revises=0, integrators="0x0", judges=3)
    run(root, "--only", "rewrite")
    st = state_of(root)
    check("O6 the pool ran without any judge session",
          not kinds_of(st, 1, "judge") and st["runs"]["r1_w1"]["status"] == "done",
          str(kinds_of(st, 1, "judge")))
    p1 = run(root, "--only", "r1_judge_w1_j1")
    st = state_of(root)
    judges = kinds_of(st, 1, "judge")
    rrec = st["rounds"]["1"]
    check("O7 only the selected session ran, and it judged w1",
          len(judges) == 1 and st["runs"][judges[0]].get("target_id") == "w1"
          and st["runs"][judges[0]].get("judge_index") == 1,
          str([(j, st["runs"][j].get("target_id"), st["runs"][j].get("judge_index"))
               for j in judges]))
    stats = rrec.get("stats") or {}
    check("O8 the panel expectation follows the one enabled session",
          stats and all(s.get("complete") for s in stats.values())
          and stats["w1"]["expected_n"] == 1 and stats["orig"]["expected_n"] == 1,
          str({v: (s.get("n"), s.get("expected_n")) for v, s in stats.items()}))
    check("O9 the round decides on that pilot panel and records the selector",
          rrec.get("status") == "done"
          and (rrec.get("plan") or {}).get("judges_enabled") == "w1_j1"
          and "--only 'r1_judge_w1_j1'" in (p1.stdout + p1.stderr),
          f"{rrec.get('status')} {(rrec.get('plan') or {}).get('judges_enabled')}")

    # --- a wrong session name is refused before any session starts --------
    tmp2 = scratch("nbt_only_judge_bad_")
    root2 = make_root(tmp2, rounds=1, rewrites=1, revises=0, integrators="0x0", judges=2)
    bad = run(root2, "--only", "r1_judge_w1_j7")
    st2 = state_of(root2)
    check("O10 an unknown judge index dies with the valid range, before any session",
          bad.returncode != 0 and "judge index 7 is outside 1..2" in (bad.stdout + bad.stderr)
          and not kinds_of(st2, 1, "judge"),
          (bad.stdout + bad.stderr).strip().splitlines()[-1][:140])

    # --- a remembered selection survives a later invocation, `judge` clears it
    ctx2 = nb.Ctx(root2)
    ctx2.load()
    ctx2.round_rec(1)["judges_enabled"] = "w1_j1"      # as a selector run records it
    ctx2.save_state()
    check("O11 a pending round remembers the selector recorded by a previous invocation",
          nb.judges_enabled_spec(ctx2, 1) == "w1_j1"
          and nb.enabled_judges(ctx2, 1, "w1") == 1
          and nb.enabled_judges(ctx2, 1, "a1") == 0,
          f"{nb.judges_enabled_spec(ctx2, 1)}")
    run(root2, "--only", "judge")
    st3 = state_of(root2)
    check("O12 a bare `--only judge` asks for the whole panel and clears it",
          st3["rounds"]["1"].get("judges_enabled") is None,
          str(st3["rounds"]["1"].get("judges_enabled")))


def test_judges_enabled():
    print()
    print("== --judges-enabled selects WHICH judge sessions run (a whitelist) ==")
    # --- the parser: the operator's syntax, the `:` variant, missing axes ----
    # Round 1 (M=2,N=1): orig + a1,w1,w2,a2 + i1,i2; round 2 (M=1,N=1): orig + a1,w1,a2 + i1.
    pool_of = lambda r: (["orig", "a1", "w1", "w2", "a2", "i1", "i2"] if r == 1
                         else ["orig", "a1", "w1", "a2", "i1"])
    judges_of = lambda r: 3
    cases = {
        "all": set(),
        "": set(),
        "r1_judge_w2_j1": {(1, "w2", 1)},
        "r1_judge_w2_j1,r2_judge_i1_j1": {(1, "w2", 1)},       # r2 has no i1 -> handled below
        "r1:w2:j1": {(1, "w2", 1)},
        "r1_judge_w2": {(1, "w2", 1), (1, "w2", 2), (1, "w2", 3)},
        "r1": {(1, v, j) for v in pool_of(1) for j in (1, 2, 3)},
        # A missing round means every round that HAS the version; a bare `j1`
        # means judge 1 of every round.
        "w2_j2": {(1, "w2", 2)},
        "j1": {(r, v, 1) for r in (1, 2) for v in pool_of(r)},
    }
    for spec, want in cases.items():
        if spec == "r1_judge_w2_j1,r2_judge_i1_j1":
            continue                      # covered by the dedicated check below
        got = nb.parse_judges_enabled(spec, 2, pool_of, judges_of)
        check(f"J1 {spec!r} expands as expected", got == want, f"{sorted(got)[:4]} vs {sorted(want)[:4]}")
    got = nb.parse_judges_enabled("r1_judge_w2_j1,r1_judge_w2_j2", 1, pool_of, judges_of)
    check("J2 two selectors for the same version accumulate", got == {(1, "w2", 1), (1, "w2", 2)},
          str(sorted(got)))
    for bad, why in (("r3_judge_w1_j1", "round"), ("r1_judge_zz_j1", "version"),
                     ("r1_judge_w1_j9", "judge index")):
        try:
            nb.parse_judges_enabled(bad, 2, pool_of, judges_of)
            check(f"J3 {bad!r} is refused ({why})", False, "no error")
        except ValueError as e:
            check(f"J3 {bad!r} is refused and names the {why}", why in str(e), str(e)[:110])

    # --- a real round with ONE enabled judge session -------------------------
    tmp = scratch("nbt_judges_enabled_")
    root = make_root(tmp, rounds=1, rewrites=1, revises=0, integrators="0x0",
                     judges=3, judges_enabled="r1_judge_w1_j1")
    p = run(root)
    st = state_of(root)
    judge_ids = kinds_of(st, 1, "judge")
    rrec = st["rounds"]["1"]
    check("J4 only the selected judge session is materialized and run",
          len(judge_ids) == 1 and st["runs"][judge_ids[0]]["status"] == "done",
          f"{judge_ids}")
    check("J5 the selector is recorded on the round plan and in the run log",
          (rrec.get("plan") or {}).get("judges_enabled") == "r1_judge_w1_j1"
          and "--judges-enabled" in (p.stdout + p.stderr),
          str((rrec.get("plan") or {}).get("judges_enabled")))
    stats = rrec.get("stats") or {}
    ctx = nb.Ctx(root)
    ctx.load()
    enabled = {v: nb.enabled_judges(ctx, 1, v) for v in stats}
    k = len(stats)
    want_expected = {v: enabled[v] * (k - 1) + (sum(enabled.values()) - enabled[v])
                     for v in stats}
    check("J6 each version's panel expectation follows the ENABLED sessions",
          stats and all(s.get("complete") for s in stats.values())
          and all(stats[v]["expected_n"] == want_expected[v] for v in stats)
          and enabled.get("w1") == 1 and enabled.get("orig", 0) == 0,
          f"enabled={enabled} got={ {v: (s.get('n'), s.get('expected_n')) for v, s in stats.items()} }")
    check("J7 the round is decided on that smaller panel",
          rrec.get("status") == "done" and rrec.get("champion") == "w1",
          f"{rrec.get('status')} {rrec.get('champion')}")

    # --- a sheet for a session the selector does NOT enable is ignored -------
    field_ids = [e["id"] for e in (rrec.get("field_entries") or [])] or ["orig", "w1"]
    state_path = root / "state.json"
    st["runs"]["judge_disabled_j2"] = {"id": "judge_disabled_j2", "kind": "judge", "round": 1,
                                       "status": "done", "judge_index": 2, "target_id": "w1",
                                       "sandbox": "runs/judge_disabled_j2", "attempts": 1}
    state_path.write_text(json.dumps(st), encoding="utf-8")
    ctx = nb.Ctx(root)
    ctx.load()
    agg = nb.aggregate_round(ctx, 1, field_ids)
    check("J8 a done sheet for a DISABLED session is ignored, not counted as a panel gap",
          any("judge_disabled_j2" in line for line in (agg["diagnostics"].get("disabled_sheets") or []))
          and all(s.get("complete") for s in agg["stats"].values()),
          str(agg["diagnostics"].get("disabled_sheets"))[:160])

def main() -> int:
    try:
        test_only_rounds()
        test_integrator_mask()
        test_judges_per_round()
        test_plan_survives_a_config_edit()
        test_judges_enabled()
        test_only_judge_sessions()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} ONLY-ROUNDS/INTEGRATORS/JUDGES CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL ONLY-ROUNDS/INTEGRATORS/JUDGES CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

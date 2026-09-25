#!/usr/bin/env python3
"""`run --only ROUNDS`, per-round integrator masks and per-round judge counts.

Run:  python3 .paper_test/test_only_rounds_integrators_judges.py

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

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_only_rounds", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_only_rounds"] = nb
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


def cli(*argv, timeout=1200):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
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


def ctx_of(root: Path):
    """A loaded Ctx for the in-process checks (see `--only` selector resolution)."""
    ctx = nb.Ctx(root)
    ctx.load()
    return ctx


def kinds_of(state: dict, round_no: int, kind: str) -> list:
    return [rid for rid, rec in (state.get("runs") or {}).items()
            if rec.get("round") == round_no and rec.get("kind") == kind]


def kind_of(state: dict, rid: str) -> tuple:
    """(kind, target_id, judge_index) of one run record, for the judge checks."""
    rec = (state.get("runs") or {}).get(rid) or {}
    return rec.get("kind"), rec.get("target_id"), rec.get("judge_index")


def test_only_rounds():
    print()
    print("== --only ROUND[:STAGE] selects which rounds this invocation drives ==")
    tmp = scratch("paper_onlyrounds_")
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
    # Re-running a selection whose rounds are ALREADY complete is a successful
    # no-op (exit 0): it must not be reported as "selected nothing" and must not
    # claim the last round's champion. `--only 1:judge` here covers round 1 (done)
    # and not the still-pending round 2.
    p_again = run(root, "--only", "1:judge")
    out_again = p_again.stdout + p_again.stderr
    check("re-running a completed `--only` selection exits 0 as a no-op",
          p_again.returncode == 0
          and "already complete -- nothing to do in this invocation" in out_again
          and "ran round(s) 1 of 2" in out_again
          and "selected no session of the round(s) that still need work" not in out_again,
          out_again[-260:])

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
    tmp = scratch("paper_integrators_")
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
    tmp2 = scratch("paper_integrators0_")
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
    tmp = scratch("paper_judges_")
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
    tmp = scratch("paper_masked_decide_")
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
          sorted(o.rounds) == [1] and o.classes_for(1) == {"judge"}
          and o.judge_spec_for(1) == "r1_w2_j1" and o.judge_spec_for(2) == ""
          and not o.is_everything() and "judge session(s) w2_j1" in o.describe(),
          o.describe())
    o2 = nb.parse_only_spec("2:judge_i1_j1,r1_judge_w2")
    check("O2 the `ROUND:judge_…` form and several selectors combine",
          sorted(o2.rounds) == [1, 2] and o2.classes_for(2) == {"judge"}
          and o2.judge_spec_for(1) == "r1_w2" and o2.judge_spec_for(2) == "r2_i1_j1",
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
    tmp = scratch("paper_only_judge_")
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
    # A judge SESSION selection runs exactly those sessions and NOTHING
    # downstream: the round decision (select + pin) is a step of the round's DAG
    # and `--only` never continues into a step the operator did not ask for. The
    # panel expectation is the CONFIGURED one (3 per version here), never the
    # selected subset.
    check("O8 a session selection leaves the round UNDECIDED (no champion, no plan, exit != 0)",
          p1.returncode != 0 and rrec.get("status") == "pending"
          and not rrec.get("champion") and not rrec.get("plan") and not st.get("pinned"),
          f"rc={p1.returncode} status={rrec.get('status')} champion={rrec.get('champion')}")
    check("O8b the round says the decision was not started, and how to get it",
          "the ROUND DECISION is NOT started" in (p1.stdout + p1.stderr)
          and "run --only judge" in (p1.stdout + p1.stderr))
    check("O9 the round's panel is still the CONFIGURED one, not the selected subset",
          not (rrec.get("stats") or {})                       # nothing was aggregated/decided
          and nb.round_judges(ctx_of(root), 1) == 3,
          str(list((rrec.get("stats") or {}).items())[:1]))
    # ... and finishing the judge step decides: the already-done session is kept.
    p1b = run(root, "--only", "judge")
    st = state_of(root)
    rrec = st["rounds"]["1"]
    n_field1 = len(rrec.get("field") or [])
    check("O9b `--only judge` completes the panel (the done session is NOT re-run) and pins",
          rrec.get("status") == "done" and rrec.get("champion")
          and len(kinds_of(st, 1, "judge")) == n_field1 * 3         # configured 3 per version
          and st["runs"][judges[0]]["attempts"] == 1                # the kept session ran once
          and (rrec.get("plan") or {}).get("judges_enabled") == "all",
          f"status={rrec.get('status')} champ={rrec.get('champion')} "
          f"judges={len(kinds_of(st, 1, 'judge'))} field={n_field1} "
          f"plan={(rrec.get('plan') or {}).get('judges_enabled')}")

    # --- a wrong session name is refused before any session starts --------
    tmp2 = scratch("paper_only_judge_bad_")
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

    # --- a sheet OUTSIDE the configured panel is ignored, never a gap --------
    # (The old "a sheet for a session the selection excluded" case cannot arise
    # any more: asking for the judge STEP clears the session selection, so the
    # round's panel is always the configured one. A sheet beyond the configured
    # 1..--judges range is still recorded and skipped.)
    ctx_o = nb.Ctx(root)
    ctx_o.load()
    field_ids = [e["id"] for e in ((st.get("rounds", {}).get("1") or {}).get("field_entries")
                                   or [])] or ["orig", "w1"]
    ctx_o.state["runs"]["judge_out_of_range_j9"] = {
        "id": "judge_out_of_range_j9", "kind": "judge", "round": 1, "status": "done",
        "judge_index": 9, "target_id": "w1", "sandbox": "runs/judge_out_of_range_j9",
        "attempts": 1}
    ctx_o.save_state()
    agg = nb.aggregate_round(ctx_o, 1, field_ids)
    check("O13 a sheet outside the configured panel range is ignored, not a panel gap",
          any("judge_out_of_range_j9" in line
              for line in (agg["diagnostics"].get("out_of_range_sheets") or []))
          and all(s.get("complete") for s in agg["stats"].values()),
          str(agg["diagnostics"].get("out_of_range_sheets"))[:160])


def test_only_agent_sessions():
    print()
    print("== `run --only rewriter2` / `integrator2` select ONE agent session ==")
    # --- the grammar --------------------------------------------------------
    check("A1 `ROUND:rewriter2` = round 1's second rewrite session, and nothing else",
          sorted(nb.parse_only_spec("1:rewriter2").rounds) == [1]
          and nb.parse_only_spec("1:rewriter2").session_tokens_for(1) == ["w2"]
          and nb.parse_only_spec("1:rewriter2").classes_for(1) == set(),
          nb.parse_only_spec("1:rewriter2").describe())
    check("A2 the friendly spellings map onto the pipeline's own session ids",
          nb.parse_only_spec("rewriter1").session_tokens_for(1) == ["w1"]
          and nb.parse_only_spec("w2").session_tokens_for(1) == ["w2"]
          and nb.parse_only_spec("reviser1").session_tokens_for(1) == ["a2"]
          and nb.parse_only_spec("integrator2").session_tokens_for(1) == ["i2"]
          and nb.parse_only_spec("r2_i1").session_tokens_for(2) == ["i1"]
          and nb.parse_only_spec("reviewer").session_tokens_for(1) == ["review"]
          and nb.parse_only_spec("r1_review_b").session_tokens_for(1) == ["review_b"])
    check("A3 a stage name still means the whole stage (a2 = revise, judge1 = judge index 1)",
          nb.parse_only_spec("a2").classes_for(1) == {"revise"}
          and nb.parse_only_spec("a2").session_tokens_for(1) == []
          and nb.parse_only_spec("judge").classes_for(1) == {"judge"}
          and nb.parse_only_spec("judge").judge_class_named(1)
          and nb.parse_only_spec("judge1").judge_spec_for(1) == "j1"
          and not nb.parse_only_spec("judge1").judge_class_named(1))
    check("A4 a round-qualified session keeps its round in the judge selector",
          nb.parse_only_spec("r1_judge_w2_j1").judge_spec_for(1) == "r1_w2_j1"
          and nb.parse_only_spec("r1_judge_w2_j1").judge_spec_for(2) == ""
          and nb.parse_only_spec("r1_w2_j1").judge_spec_for(1) == "r1_w2_j1"
          and nb.parse_only_spec("w2_j1").judge_spec_for(1) == "w2_j1")
    check("A4b the items are a UNION: a roundless item keeps its rounds in play",
          nb.parse_only_spec("review,2:merge").covers_round(1)
          and nb.parse_only_spec("review,2:merge").covers_round(2)
          and nb.parse_only_spec("rewrite,judge_t497f106d_j1").covers_round(1)
          and not nb.parse_only_spec("2:merge").covers_round(1)
          and nb.parse_only_spec("1").covers_round(1)
          and not nb.parse_only_spec("1").covers_round(2))
    for bad in ("a1", "orig"):
        try:
            nb.parse_only_spec(bad)
            check(f"A5 `--only {bad}` is refused (it names no agent session)", False,
                  "no SystemExit")
        except SystemExit as e:
            check(f"A5 `--only {bad}` is refused (it names no agent session)", e.code == 1,
                  str(e.code))
    tmp0 = scratch("paper_only_agent_gate_")
    root0 = make_root(tmp0, rounds=1, rewrites=2, revises=1, integrators="0xFFFFFFFF", judges=1)
    for bad in ("rewriter9", "integrator9"):
        p0 = run(root0, "--only", bad)
        check(f"A5 `--only {bad}` is refused with the sessions the round plans",
              p0.returncode != 0
              and "no round of this pipeline runs session(s)" in (p0.stdout + p0.stderr)
              and "round 1 plans w1, w2" in (p0.stdout + p0.stderr),
              (p0.stdout + p0.stderr).strip().splitlines()[-1][:150])
    p0 = run(root0, "--only", "1:reviser9")
    check("A5 a round-qualified typo is refused against THAT round's plan",
          p0.returncode != 0 and "round 1 plans no session" in (p0.stdout + p0.stderr)
          and "reviser1` is a2" in (p0.stdout + p0.stderr),
          (p0.stdout + p0.stderr).strip().splitlines()[-1][:150])

    # --- one producing session runs, and NOTHING else ------------------------
    tmp = scratch("paper_only_agent_")
    root = make_root(tmp, rounds=1, rewrites=2, revises=1, integrators="0xFFFFFFFF", judges=1)
    p = run(root, "--only", "rewriter2")
    st = state_of(root)
    done = {rid for rid, rec in st["runs"].items() if rec.get("status") == "done"}
    check("A6 `--only rewriter2` runs w2 and nothing else (no judge wave either)",
          done == {"r1_a1", "r1_w2"}, str(sorted(done)))
    check("A7 a producing-session selection never starts the judge wave",
          not kinds_of(st, 1, "judge")
          and "the judge wave and the round decision are NOT started" in (p.stdout + p.stderr),
          str(kinds_of(st, 1, "judge")))
    p = run(root, "--only", "1:rewriter1")
    st = state_of(root)
    check("A8 `--only 1:rewriter1` adds exactly w1",
          {rid for rid, rec in st["runs"].items() if rec.get("status") == "done"}
          == {"r1_a1", "r1_w1", "r1_w2"}, str(sorted(st["runs"])))

    # --- a roundless item applies to the rounds that have the session --------
    root2 = make_root(scratch("paper_only_agent_r2_"), rounds=2, rewrites="2,1", revises="1,1",
                      integrators="0xFFFFFFFF", judges=1)
    p2 = run(root2, "--only", "w2")
    st2 = state_of(root2)
    check("A9 a roundless session item runs where it exists and skips the rest",
          (st2["runs"].get("r1_w2") or {}).get("status") == "done"
          and (st2["runs"].get("r1_w1") or {}).get("status") != "done"
          and not any(rec.get("round") == 2 for rec in st2["runs"].values())
          and "round 1 is incomplete" in (p2.stdout + p2.stderr),
          str(sorted(st2["runs"])))
    j9 = json.loads(cli("agents", "--root", str(root2), "--only", "w2", "--json").stdout)
    check("A9 the dry plan keeps a roundless item to the rounds that have the session",
          [row["round"] for row in j9["rounds"]] == [1]
          and [s["id"] for s in j9["rounds"][0]["producing"]] == ["r1_w2"],
          json.dumps(j9["rounds"])[:160])

    # --- an integration waits for the WHOLE pool, then runs alone -----------
    root3 = make_root(scratch("paper_only_agent_r3_"), rounds=1, rewrites=1, revises=1,
                      integrators="0xFFFFFFFF", judges=1)
    run(root3, "--only", "integrator2")
    st3 = state_of(root3)
    check("A10 `--only integrator2` starts nothing while the pool is missing",
          all((st3["runs"].get(rid) or {}).get("status") != "done"
              for rid in ("r1_w1", "r1_review", "r1_a2_revise", "r1_i1", "r1_i2")),
          str({rid: (st3["runs"].get(rid) or {}).get("status")
               for rid in ("r1_w1", "r1_review", "r1_a2_revise", "r1_i1", "r1_i2")}))
    run(root3, "--only", "rewrite,review,audit,revise")
    run(root3, "--only", "integrator2")
    st3 = state_of(root3)
    check("A11 once the pool is done, ONLY the selected integration arm runs",
          (st3["runs"].get("r1_i2") or {}).get("status") == "done"
          and (st3["runs"].get("r1_i1") or {}).get("status") != "done"
          and (st3["runs"].get("r1_i3") or {}).get("status") != "done",
          str({rid: (st3["runs"].get(rid) or {}).get("status")
               for rid in ("r1_i1", "r1_i2", "r1_i3")}))


def test_only_accepts_the_printed_ids():
    print()
    print("== every id `agents` prints is a valid `--only` item ==")
    # --- the grammar of the printed forms --------------------------------
    check("H1 the printed producing run ids are accepted (arm ids are not re-indexed)",
          nb.parse_only_spec("r1_a2_revise").session_tokens_for(1) == ["a2"]
          and nb.parse_only_spec("r2_a3_revise").session_tokens_for(2) == ["a3"]
          and nb.parse_only_spec("r1_a2").session_tokens_for(1) == ["a2"]
          and nb.parse_only_spec("2:a3").session_tokens_for(2) == ["a3"]
          and nb.parse_only_spec("r1_reviser2").session_tokens_for(1) == ["a3"]
          and nb.parse_only_spec("r1_w1").session_tokens_for(1) == ["w1"]
          and nb.parse_only_spec("r1_review").session_tokens_for(1) == ["review"])
    check("H2 `judge_<k>` and the round-qualified index forms parse",
          nb.parse_only_spec("judge_1").judge_spec_for(1) == "j1"
          and nb.parse_only_spec("j_2").judge_spec_for(1) == "j2"
          and nb.parse_only_spec("r1_judge_1").judge_spec_for(1) == "r1_j1"
          and nb.parse_only_spec("r1_judge1").judge_spec_for(1) == "r1_j1"
          and nb.parse_only_spec("2:judge_2").judge_spec_for(2) == "r2_j2"
          and nb.parse_only_spec("2:a2").classes_for(2) == {"revise"})
    check("H3 a printed judge run id stays PENDING until a root resolves it",
          nb.parse_only_spec("judge_t497f106d_j1").judge_run_ids
          == [("judge_t497f106d_j1", "judge_t497f106d_j1")]
          and nb.parse_only_spec("judge_t497f106d_j1").judge_selectors == {})

    # --- a real round trip: the id `agents` printed, fed back to `run` -----
    tmp = scratch("paper_only_runids_")
    root = make_root(tmp, rounds=1, rewrites=1, revises=0, integrators="0x0", judges=3)
    run(root, "--only", "rewrite")
    j = json.loads(cli("agents", "--root", str(root), "--json").stdout)
    w1_ids = [s["id"] for row in j["rounds"] for s in row["judge"] if s["target"] == "w1"]
    check("H4 `agents` prints the judge ids with their targets", len(w1_ids) == 3, str(w1_ids))
    ctx = nb.Ctx(root)
    ctx.load()
    check("H4 the printed token is the resolved (round, version) token",
          w1_ids[0] == nb.rid_judge(1, nb.judge_token_for(ctx, 1, "w1"), 1)
          and w1_ids[2] == nb.rid_judge(1, nb.judge_token_for(ctx, 1, "w1"), 3),
          str(w1_ids))
    p = run(root, "--only", w1_ids[1])
    st = state_of(root)
    judges = kinds_of(st, 1, "judge")
    check("H5 `run --only judge_<token>_j2` runs exactly that judge session",
          judges == [w1_ids[1]] and st["runs"][w1_ids[1]]["status"] == "done"
          and kind_of(st, w1_ids[1]) == ("judge", "w1", 2)
          and "judge run id -> round 1, version w1, judge 2" in (p.stdout + p.stderr),
          str({rid: (st["runs"][rid]["status"], st["runs"][rid].get("target_id"),
                     st["runs"][rid].get("judge_index")) for rid in judges}))
    check("H5b the round stays UNDECIDED: a judge session is a step, not the judge step",
          p.returncode != 0 and st["rounds"]["1"].get("status") == "pending"
          and not st["rounds"]["1"].get("plan") and not st.get("pinned"),
          f"rc={p.returncode} status={st['rounds']['1'].get('status')}")

    # --- a wrong run id, and the `--only` preview of a run id --------------
    bad = run(root, "--only", "judge_tdeadbeef_j1")
    check("H6 an unknown judge run id is refused with the `agents` hint, before anything starts",
          bad.returncode != 0
          and "is not a judge session of this root" in (bad.stdout + bad.stderr)
          and "agents" in (bad.stdout + bad.stderr),
          (bad.stdout + bad.stderr).strip().splitlines()[-1][:150])
    j2 = json.loads(cli("agents", "--root", str(root), "--only", w1_ids[2],
                        "--json").stdout)
    check("H7 `agents --only <judge run id>` previews the very same session",
          [(s["id"], s["target"]) for s in j2["rounds"][0]["judge"]] == [(w1_ids[2], "w1")]
          and j2["rounds"][0]["judge"][0]["status"] == "planned",
          json.dumps(j2["rounds"][0]["judge"]))


def test_only_judge_the_pinned_base():
    print()
    print("== a round-2 judge session on the PINNED base (`r1_w2`) ==")
    tmp = scratch("paper_only_pin_")
    root = make_root(tmp, rounds=2, rewrites="2,1", revises="1,1",
                     integrators="0x5", judges="2,1")
    run(root, "--only", "1")
    st = state_of(root)
    pin = str((st.get("pinned") or [{}])[0].get("id") or "")
    check("P1 round 1 pinned a champion", bool(pin), str(st.get("pinned")))
    j = json.loads(cli("agents", "--root", str(root), "--json").stdout)
    r2 = [row for row in j["rounds"] if row["round"] == 2][0]
    targets = [s["target"] for s in r2["judge"]]
    check("P2 a pending round 2 lists the PIN as the base candidate (besides its fresh a1)",
          pin in targets and "a1" in targets and targets.index(pin) < targets.index("a1")
          and len({s["id"] for s in r2["judge"]}) == len(r2["judge"]),
          str(targets))
    pin_id = [s["id"] for s in r2["judge"] if s["target"] == pin][0]
    # Asking for it before the round's own arms exist must EXPLAIN, not traceback.
    blocked = run(root, "--only", pin_id)
    out = blocked.stdout + blocked.stderr
    check("P3 an early judge-only selection explains what is still missing",
          blocked.returncode != 0 and "needs the WHOLE field" in out
          and "Traceback" not in out and not kinds_of(state_of(root), 2, "judge"),
          out[-200:])
    run(root, "--only", "2:rewrite,2:review,2:audit,2:revise,2:merge")
    p = run(root, "--only", pin_id)
    st2 = state_of(root)
    judges = kinds_of(st2, 2, "judge")
    stats = (st2["rounds"]["2"].get("stats") or {})
    check("P4 the printed id then runs exactly that judge session",
          judges == [pin_id] and kind_of(st2, pin_id) == ("judge", pin, 1)
          and "judge run id -> round 2, version " + pin in (p.stdout + p.stderr),
          str({rid: kind_of(st2, rid) for rid in judges}))
    check("P5 that session does NOT decide round 2 (the judge step was not asked for)",
          p.returncode != 0 and st2["rounds"]["2"].get("status") == "pending"
          and not st2["rounds"]["2"].get("plan") and not stats
          and "the ROUND DECISION is NOT started" in (p.stdout + p.stderr),
          f"rc={p.returncode} status={st2['rounds']['2'].get('status')} stats={bool(stats)}")
    p5 = run(root, "--only", "judge")
    st3 = state_of(root)
    rr2 = st3["rounds"]["2"]
    stats3 = rr2.get("stats") or {}
    n_field = len(rr2.get("field") or [])
    check("P6 `--only judge` then completes the panel (keeping the session already done) "
          "and decides round 2 with the CONFIGURED panel",
          rr2.get("status") == "done" and rr2.get("champion")
          and len(kinds_of(st3, 2, "judge")) == n_field          # 1 judge x every field member
          and (rr2.get("plan") or {}).get("judges_enabled") == "all"
          and all(s.get("complete") for s in stats3.values())
          and all(s.get("expected_n") == 2 * (n_field - 1) for s in stats3.values()),
          f"status={rr2.get('status')} judges={len(kinds_of(st3, 2, 'judge'))} "
          f"expected={ {v: s.get('expected_n') for v, s in list(stats3.items())[:3]} }")


def test_agents_command():
    print()
    print("== `agents`: the session names every round will run ==")
    tmp = scratch("paper_agents_")
    root = make_root(tmp, rounds=2, rewrites="2,1", revises="1,1",
                     integrators="0x5", judges="2,1")
    p = cli("agents", "--root", str(root))
    out = p.stdout + p.stderr
    check("G1 the dry plan lists every producing session of every round",
          p.returncode == 0
          and all(s in out for s in ("r1_a1", "r1_w1", "r1_w2", "r1_review", "r1_audit",
                                     "r1_a2_revise", "r1_i1", "r1_i3",
                                     "r2_w1", "r2_review", "r2_a2_revise", "r2_i1", "r2_i3"))
          and "r2_w2" not in out and "r1_i2" not in out,
          out[:200])
    check("G2 it lists the judge sessions of both rounds, with their targets",
          out.count("judge_t") >= 20 and "-> w1" in out and "2 per version" in out
          and "1 per version" in out,
          str([l for l in out.splitlines() if "judge_t" in l][:2]))
    j = json.loads(cli("agents", "--root", str(root), "--only", "r1_w2", "--json").stdout)
    check("G3 `agents --only` previews exactly the sessions the equivalent run would drive",
          j["only"] == "r1_w2" and len(j["rounds"]) == 1
          and [s["id"] for s in j["rounds"][0]["producing"]] == ["r1_w2"]
          and j["rounds"][0]["judges_selected"] is False
          and j["rounds"][0]["judge"] == [],
          json.dumps(j["rounds"][0])[:200])
    j2 = json.loads(cli("agents", "--root", str(root), "--only", "r1_judge_w1_j2",
                        "--json").stdout)
    check("G4 a judge-session preview lists exactly that session",
          len(j2["rounds"][0]["judge"]) == 1
          and j2["rounds"][0]["judge"][0]["judge_index"] == 2
          and j2["rounds"][0]["judge"][0]["status"] == "planned",
          json.dumps(j2["rounds"][0]["judge"]))
    # Plan-time ids must be the ids that actually run (the judge token is salted,
    # but it is derived from (round, version id) alone -- no document hash).
    run(root)
    st = state_of(root)
    q = json.loads(cli("agents", "--root", str(root), "--json").stdout)
    listed = {s["id"] for row in q["rounds"] for s in row["judge"]}
    actual = {rid for rid in st["runs"] if rid.startswith("judge_")}
    check("G5 after the run the judge ids are EXACT (every judge run is listed)",
          bool(listed) and listed == actual, f"{len(listed)} listed vs {len(actual)} run")
    planned_prod = {s["id"] for row in q["rounds"] for s in row["producing"]}
    check("G6 the listed producing ids are the round plan's runs",
          planned_prod == {rid for rid, rec in st["runs"].items()
                           if rec.get("kind") != "judge"}
          and all(s["status"] == "done" for row in q["rounds"] for s in row["producing"]),
          str(sorted(planned_prod)))
    # Every printed id must be usable as an `--only` item (the base copy's a1
    # line is the documented exception: it is not an agent session).
    bad = []
    for rid in sorted(planned_prod):
        if rid.endswith("_a1"):
            continue
        try:
            spec = nb.parse_only_spec(rid)
            nb.resolve_judge_run_ids(ctx_of(root), spec, label="[test]")
            spec.validate(2)
            nb.validate_only_selectors(ctx_of(root), spec)
        except SystemExit:
            bad.append(rid)
    check("G7 every producing id `agents` prints is a valid `--only` item", not bad, str(bad))
    bad = []
    for rid in sorted({s["id"] for row in q["rounds"] for s in row["judge"]}):
        try:
            spec = nb.parse_only_spec(rid)
            nb.resolve_judge_run_ids(ctx_of(root), spec, label="[test]")
            spec.validate(2)
            nb.validate_only_selectors(ctx_of(root), spec)
        except SystemExit:
            bad.append(rid)
    check("G8 every judge id `agents` prints is a valid `--only` item", not bad, str(bad))

def main() -> int:
    try:
        test_only_rounds()
        test_integrator_mask()
        test_judges_per_round()
        test_plan_survives_a_config_edit()
        test_only_judge_sessions()
        test_only_agent_sessions()
        test_only_accepts_the_printed_ids()
        test_only_judge_the_pinned_base()
        test_agents_command()
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

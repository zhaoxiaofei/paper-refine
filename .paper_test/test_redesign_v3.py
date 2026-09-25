#!/usr/bin/env python3
"""The 2026-09-21 redesign: judge contract v3, writing class, incumbent-margin ranking.

Run:  python3 .paper_test/test_redesign_v3.py
`PAPER_WS` retargets the suite at a baseline copy (red before the redesign).
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
spec = importlib.util.spec_from_file_location("paperp", WS / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp"] = np
spec.loader.exec_module(np)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def row(tier, severity, evidence="loc: unit fixture", check_id=None):
    out = {"tier": tier, "severity": severity, "evidence": evidence}
    if check_id:
        out["check"] = check_id
    return out


def comp(score, resolved=(), introduced=(), checks=True, basis="consistency"):
    out = {"opponent_label": "v1", "score": score, "reason": "unit fixture", "basis": basis,
           "resolved": list(resolved), "introduced": list(introduced)}
    if checks:
        out["checks"] = {c: "clean -- unit fixture" for c in np.JUDGE_COVERAGE_CHECKS}
        if score:
            out["checks"]["M1"] = "findings -- unit fixture"
    return out


def test_contract_v3():
    print("== judge contract v3: writing class, weights, derived score, coverage ==")
    check("the contract version is 3", np.JUDGE_CONTRACT_VERSION == 3,
          str(np.JUDGE_CONTRACT_VERSION))
    check("`writing` is a scored class", "writing" in np.BASIS_TIERS, str(np.BASIS_TIERS))
    check("formatting and writing are MINOR-only classes",
          set(np.MINOR_ONLY_TIERS) == {"formatting", "writing"})
    # minor-only enforcement
    e, _w = np.judge_basis_problems(comp(1, [row("writing", "major")]), "c[0]", strict=True)
    check("a writing MAJOR row fails its run", bool(e), str(e[:1]))
    e2, _w2 = np.judge_basis_problems(comp(1, [row("formatting", "critical")]), "c[0]",
                                      strict=True)
    check("a formatting CRITICAL row fails its run", bool(e2), str(e2[:1]))
    # proportional, capped derivation, BOUNDED BY THE RUNG the rows can back
    # (2026-09-23: the caps alone could demand a number the rung rule forbids --
    # three minor consistency rows sum to 3 with no MAJOR row, two MAJOR
    # correctness rows sum to 4 with no CRITICAL row -- and two judge sessions of
    # a real panel failed on that contradiction whichever number they wrote).
    five = [row("consistency", "minor") for _ in range(5)]
    check("five minor consistency rows derive +2 (MINOR rows reach 'better', never 'clearly')",
          np.derived_comparison_score(comp(2, five)) == 2)
    three_major = [row("correctness", "major"), row("correctness", "major")]
    check("two MAJOR correctness rows derive +3 ('clearly better' needs a MAJOR, not a CRITICAL)",
          np.derived_comparison_score(comp(3, three_major, basis="correctness")) == 3)
    for rows, want in ((five, 2), (three_major, 3)):
        errs, _ = np.judge_basis_problems(comp(want, rows,
                                              basis="correctness" if want == 3 else "consistency"),
                                          "c[0]", strict=True)
        check(f"the arithmetic and the rung rules AGREE on a {want:+d} sheet",
              not any("rung" in x or "DERIVED" in x for x in errs), str(errs[:1]))
    fmt3 = [row("formatting", "minor") for _ in range(3)]
    check("three formatting rows still derive +1 (class cap)",
          np.derived_comparison_score(comp(1, fmt3)) == 1)
    wr = [row("writing", "minor")]
    check("writing is worth at most one point", np.derived_comparison_score(comp(1, wr)) == 1)
    crit = [row("correctness", "critical"), row("consistency", "minor")]
    check("critical correctness + minor derives +4",
          np.derived_comparison_score(comp(4, crit, basis="correctness")) == 4)
    # the sweep's RULE ids are accepted as the check that owns them (M20)
    fmt_rule = [row("formatting", "minor", check_id="FMT-T9C")]
    check("a formatting-sweep rule id (`FMT-T9C`) is read as its check (M20)",
          np._norm_check_id("FMT-T9C") == "M20" and np._norm_check_id("fmt-s4") == "M20"
          and np._norm_check_id("M20") == "M20")
    e_fmt, _wf = np.judge_basis_problems(comp(1, fmt_rule, basis="formatting"), "c[0]",
                                         strict=True)
    check("a ledger row citing `FMT-T9C` no longer fails the frozen-check-id gate",
          not any("frozen check id" in x for x in e_fmt), str(e_fmt[:1]))
    # 2026-09-24: the writing rubric names its own items and tells the judge to
    # cite one ("a row names its rubric item (`Q7`)"), so Q1-Q12 are the twelve
    # faces OF the frozen check J3, exactly as FMT-* rules belong to M20. The
    # 2026-09-23 round-1 panel shows what the missing mapping cost: 8 of the 24
    # sessions failed on nothing but `check 'Q11' is not a frozen check id`, three
    # of them twice and one on all three attempts, and the round needed 3h20m and
    # still finished incomplete.
    q_row = [row("writing", "minor", check_id="Q11")]
    e_q, w_q = np.judge_basis_problems(comp(1, q_row, basis="writing"), "c[0]", strict=True)
    check("the rubric's items are read as the check that owns them (Q11 -> J3)",
          np._norm_check_id("Q11") == np.WRITING_RUBRIC_CHECK == "J3"
          and np._norm_check_id("q6") == "J3" and not e_q
          and not any("frozen check id" in x for x in w_q), f"{e_q[:1]} {w_q[:1]}")
    # An id nobody recognizes may not cost a 20-40 minute judge session either:
    # a ledger row's `check` cell is descriptive (the arithmetic reads
    # tier/severity/evidence only), so it is reported and the row still counts.
    e_u, w_u = np.judge_basis_problems(comp(1, [row("writing", "minor", check_id="ZZ9")]),
                                       "c[0]", strict=True)
    check("an unknown id is a warning that names what to cite, not a failed run",
          not e_u and any("ZZ9" in x and "not a frozen check id" in x for x in w_u),
          f"{e_u[:1]} {w_u[:1]}")
    # a sheet whose integer contradicts its rows
    e3, _ = np.judge_basis_problems(comp(4, wr, basis="writing"), "c[0]", strict=True)
    check("an integer that contradicts its own rows fails its run",
          any("DERIVED" in x for x in e3), str(e3[:1]))
    # coverage
    rec = {"id": "r2_judge_tX_j1", "round": 2, "target_id": "a2", "judge_index": 1,
           "label_map": {"v1": "orig"}, "contract": np.JUDGE_CONTRACT_VERSION}
    sheet = {"run_id": rec["id"], "target_id": "a2", "judge_index": 1,
             "comparisons": [comp(0, checks=False, basis="none")]}
    errs, _ = np.validate_judge_sheet(sheet, rec)
    check("a comparison without a `checks` map fails under v3",
          any("checks" in x for x in errs), str(errs[:1]))
    short = comp(0, checks=True, basis="none")
    short["checks"].pop("M7")
    errs2, _ = np.validate_judge_sheet(
        {"run_id": rec["id"], "target_id": "a2", "judge_index": 1, "comparisons": [short]}, rec)
    check("an omitted frozen check id fails under v3",
          any("M7" in x for x in errs2), str(errs2[:1]))


def test_prompts_and_policy():
    print("== prompts and the publication-time fixer policy ==")
    sb = Path("/tmp/paper_v3_prompt")
    judge = np.judge_prompt(sb, "judge_t1_j1", 1, "t1", 1, 2, ["v1", "v2"])
    check("the judge prompt states the derived-score rule",
          "DERIVED" in judge and "writing" in judge)
    check("the judge prompt requires a disposition for every frozen check id",
          "checks" in judge and "M1-M17" in judge)
    revise = np.revise_prompt(sb, "r1_a2_revise", 1)
    check("the revise prompt carries the improvement-row contract",
          "IMPROVEMENT ROWS" in revise and "I-xxx" in revise)
    integrate = np.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1", "a2"])
    check("the integrate difference ledger no longer forbids sentence-level ports",
          "do not only port" not in integrate.split("INTEGRATION DIFFERENCE LEDGER")[-1][:600])
    tmp = Path(tempfile.mkdtemp(prefix="paper_v3_pol_"))
    TMPDIRS.append(tmp)
    ctx = np.Ctx(tmp)
    ctx.cfg = {"format_policy": {}}
    pre = np.pre_judge_format_policy(ctx)
    pub = np.format_policy_of(ctx)
    check("the pre-judge policy leaves the text-level consistency rules unfixed",
          all(pre.get(k) == "keep" for k in np.TEXT_CONSISTENCY_KEYS), str(pre))
    check("the publication policy keeps the configured text-level rules",
          pub.get("term_spelling") == "dominant" and pub.get("citation_journal_names") == "drop",
          str({k: pub.get(k) for k in np.TEXT_CONSISTENCY_KEYS}))


def test_field_wide_ranking_and_reported_margin():
    print("== the field-wide statistic decides; the incumbent margin is reported ==")
    tmp = Path(tempfile.mkdtemp(prefix="paper_v3_rank_"))
    TMPDIRS.append(tmp)
    ctx = np.Ctx(tmp)
    ctx.cfg = {"rounds": 2, "judges": 1, "caption_limit": 0, "rewrites": [1, 1],
               "revises": [1, 1]}
    ctx.state = {"version": np.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": {"files": {}, "count": 0}, "original_digest": "d_orig",
                 "config": ctx.cfg}
    ctx.state["pinned"] = [{"id": "r1_a2", "round": 1, "digest": "d_pin", "source_id": "a2"}]
    ctx.state["runs"]["r2_a1"] = {"id": "r2_a1", "kind": "a1", "round": 2,
                                  "sandbox": "runs/r2_a1", "status": "done",
                                  "corpus_digest": "d_pin", "attempts": 1}
    for vid in ("w1", "i1"):
        ctx.state["runs"][np.rid_for_fresh(2, vid)] = {
            "id": np.rid_for_fresh(2, vid),
            "kind": "rewrite" if vid == "w1" else "integrate", "round": 2,
            "sandbox": f"runs/{np.rid_for_fresh(2, vid)}", "status": "done",
            "corpus_digest": f"d_{vid}", "attempts": 1,
            "summary": {"critical_remaining": 0, "writing_remaining": 0, "manual_items": 0}}
    (tmp / "reports").mkdir(parents=True, exist_ok=True)
    field = ["orig", "r1_a2", "w1", "i1"]
    stats = {}
    base = {"id": "r1_a2", "n": 6, "expected_n": 6, "complete": True, "median": 1.0,
            "mean": 1.0, "iqr": 1.0, "vs_original": 1.0, "vs_original_complete": True,
            "anti_regression_ok": None, "vs_base": None, "vs_base_vals": [], "is_base": True,
            "digest": "d_pin"}
    # w1: the best FIELD-WIDE statistics, but it LOSES the pair against the incumbent.
    w1 = dict(base, id="w1", median=3.0, mean=3.0, vs_original=3.0, vs_base=-2.0,
              vs_base_vals=[-2, -2], is_base=False, digest="d_w1", anti_regression_ok=True)
    # i1: weaker field-wide statistics, but it WINS the pair against the incumbent.
    i1 = dict(base, id="i1", median=2.0, mean=2.0, vs_original=2.0, vs_base=2.0,
              vs_base_vals=[2, 2], is_base=False, digest="d_i1", anti_regression_ok=True)
    for rowd in (base, w1, i1):
        stats[rowd["id"]] = rowd
    agg = {"stats": stats, "base_rep": "r1_a2", "field": field, "field_size": len(field),
           "scores_per_version": 6, "diagnostics": {}}
    sel = np.select_champion(ctx, 2, agg)
    # Operator policy (2026-09-21): vs_base carries only 2*judges directed scores,
    # so ONE outlier session flips its sign statistic. The field-wide list decides.
    check("the better field-wide median wins even though it lost the incumbent pair",
          sel["champion"] == "w1",
          f"champion={sel['champion']} rep={sel['champion_rep']}")
    # Flip the pair: w1 now wins it and i1 loses it. The champion must NOT move --
    # the pair is reported, the field-wide list decides.
    stats["w1"].update({"vs_base": 2.0, "vs_base_vals": [2, 2]})
    stats["i1"].update({"vs_base": -2.0, "vs_base_vals": [-2, -2]})
    sel2 = np.select_champion(ctx, 2, agg)
    check("flipping the incumbent pair does not change the champion (it is not a ranking key)",
          sel2["champion"] == "w1", f"champion={sel2['champion']}")
    check("the trace documents the field-wide key and the reported-only margin",
          any("ranking key: (-median, -mean, IQR, critical_remaining, writing_remaining, "
              "digest, id)" in ln for ln in sel2["trace"])
          and any("vs_base is reported but NOT a ranking key" in ln for ln in sel2["trace"]),
          str(sel2["trace"][-1:])[:200])


ZERO_CHECK_IDS = ([f"M{i}" for i in range(1, 18)]
                  + ["M18", "M19", "M20", "M21", "M22", "M23", "M24"]
                  + [f"J{i}" for i in range(1, 5)])


def zero_judge_main() -> int:
    """A panel that claims no difference anywhere: every round pins the incumbent."""
    import re
    sb = Path.cwd()
    prompt = (sb / "PROMPT.md").read_text(encoding="utf-8")
    token = re.search(r'"target_id":\s*"([^"]+)"', prompt).group(1)
    jidx = int(re.search(r'"judge_index":\s*(\d+)', prompt).group(1))
    labels = [x.strip() for x in
              re.findall(r"no more, no fewer:\s*(.+)", prompt)[0].strip().split(",")]
    checks = {c: "clean -- zero judge" for c in ZERO_CHECK_IDS}
    comps = [{"opponent_label": lab, "score": 0, "basis": "none", "resolved": [],
              "introduced": [], "checks": dict(checks),
              "reason": "zero judge: no difference claimed"} for lab in labels]
    (sb / "scores.json").write_text(json.dumps({
        "run_id": sb.name, "target_id": token, "judge_index": jidx,
        "comparisons": comps, "notes": "zero judge"}), encoding="utf-8")
    jr = sb / "judge_review"
    (jr / "artifacts").mkdir(parents=True, exist_ok=True)
    (jr / "inventory.md").write_text("# inventory (zero judge)\n", encoding="utf-8")
    (jr / "artifacts" / "M1_acronyms.md").write_text("| row |\n|---|\n", encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(json.dumps(
        {"stage": "judge", "run_id": sb.name, "status": "complete", "error": None}),
        encoding="utf-8")
    return 0


def test_second_pass():
    print("== second pass: order balance, provider record, adaptive stop ==")
    sb = Path("/tmp/paper_v3_second")
    default = np.judge_prompt(sb, "judge_t1_j1", 1, "t1", 1, 2, ["v1", "v2"])
    flipped = np.judge_prompt(sb, "judge_t1_j2", 1, "t1", 2, 2, ["v1", "v2"],
                              field_first=True)
    check("the default judge prompt keeps the target-first task order",
          "READING ORDER FOR THIS SESSION" not in default)
    check("the balanced session reads the field before the target",
          "READING ORDER FOR THIS SESSION" in flipped and "IN FULL FIRST" in flipped)
    import re as _re
    _block = flipped.split("READING ORDER FOR THIS SESSION", 1)[1][:400].lower()
    _hits = sorted(set(_re.findall(
        r"\b(champion|pipeline|round|rounds|arm|revise|revised|integration)\b", _block)))
    check("the inserted reading-order block adds no provenance vocabulary",
          not _hits, str(_hits))
    tmp = Path(tempfile.mkdtemp(prefix="paper_v3_stop_"))
    TMPDIRS.append(tmp)
    source = tmp / "source"
    (source / "raw_figs").mkdir(parents=True)
    (source / "manuscript-b.md").write_text("title\n", encoding="utf-8")
    (source / "raw_figs" / "data.tsv").write_text("a\tb\n", encoding="utf-8")
    root = tmp / "root"
    stub = Path(__file__).resolve().parent / "stub_agent.py"
    setup = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                            "--source", str(source), "--root", str(root), "--rounds", "2",
                            "--judges", "1", "--rewrites", "1", "--revises", "1",
                            "--stop-after-no-progress", "1"],
                           capture_output=True, text=True, timeout=600)
    check("setup accepts --stop-after-no-progress", setup.returncode == 0,
          (setup.stdout + setup.stderr)[-200:])
    run = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "run",
                          "--root", str(root), "--jobs", "4",
                          "--agent-cmd", json.dumps([sys.executable, str(stub)]),
                          "--judge-agent-cmd",
                          json.dumps([sys.executable, str(Path(__file__).resolve()),
                                      "--as-zero-judge"]),
                          "--retries", "0", "--retry-backoff", "0"],
                         capture_output=True, text=True, timeout=1800)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    stop = state.get("stopped_early") or {}
    check("the all-zero panel pins the incumbent and the stop fires after round 1",
          run.returncode == 0 and stop.get("after_round") == 1
          and str((state.get("rounds") or {}).get("1", {}).get("champion")) == "a1",
          f"rc={run.returncode} stop={stop} out={(run.stdout + run.stderr)[-200:]}")
    check("the run records which backend judged (C24)",
          isinstance(state.get("judge_provider"), dict)
          and state["judge_provider"].get("judge")
          and state["judge_provider"].get("producer"),
          str(state.get("judge_provider"))[:160])
    dec = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "decide",
                          "--root", str(root)], capture_output=True, text=True, timeout=900)
    dj = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    check("decide treats the pre-registered stop as a FINAL answer",
          dec.returncode == 0 and (dj.get("stopped_early") or {}).get("after_round") == 1,
          f"rc={dec.returncode} stopped={dj.get('stopped_early')}")
    check("decision.json carries the judge-provider record",
          isinstance(dj.get("judge_provider"), dict)
          and dj["judge_provider"].get("same_as_producer") is False)


def main() -> int:
    if "--as-zero-judge" in sys.argv[1:]:
        return zero_judge_main()
    test_contract_v3()
    test_prompts_and_policy()
    test_field_wide_ranking_and_reported_margin()
    test_second_pass()
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print(f"\n[FAIL] {len(FAILS)} check(s) failed: {', '.join(FAILS)}")
        return 1
    print("\n[ok ] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

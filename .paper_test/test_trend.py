#!/usr/bin/env python3
"""The cross-run trend report: can you SEE improvement over many runs?

A round's integer compares its champion against THAT round's own input, so the
reference moves with the chain and the per-round numbers cannot be read as one
trajectory. The `trend` command reports the two things that ARE comparable:

  * the per-round PAIRED margins the run itself recorded (`vs_input` = the
    champion against the version that run started from; `vs_incumbent` = the
    champion against the previous round's champion);
  * the champion's ISSUE CENSUS per tier and severity (the absolute "what is
    left" count from the judges' ledger rows; `-` for runs decided before the
    census existed), plus the deterministic, panel-free counters (formatting
    rows, over-cap sections, hand-off placeholders).

This suite pins the ordering inference (a root whose recorded `source` points
inside another root comes after it), the row extraction, the markdown/CSV
outputs and the CLI wiring.

Run:  python3 .paper_test/test_trend.py
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("paperp", WS / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp"] = np
spec.loader.exec_module(np)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def census(totals):
    """A minimal issue_census entry: tiers/severities with the wanted totals."""
    tiers = {t: {"own": 0, "peer": 0, "total": int(totals.get(t, 0)),
                 "per_session": None,
                 "severities": {s: {"own": 0, "peer": 0, "total": 0, "per_session": None}
                                for s in np.SEVERITIES}}
             for t in np.BASIS_TIERS}
    sevs = {s: {"own": 0, "peer": 0, "total": int(totals.get(s, 0)), "per_session": None}
            for s in np.SEVERITIES}
    return {"tiers": tiers, "severities": sevs, "own": 1, "peer": 1,
            "total": sum(tiers[t]["total"] for t in np.BASIS_TIERS),
            "per_session": None, "own_sessions": 1, "peer_sessions": 1,
            "sessions_expected": 2}


def write_decision(root: Path, source, rounds: list, final: dict = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    p = root / "reports" / "decision.json"
    p.write_text(json.dumps({
        "generated": "2026-01-01T00:00:00+00:00",
        "pipeline_root": str(root),
        "config": {"source": str(source) if source else None},
        "rounds": rounds,
        "final": final or {}}, indent=1), encoding="utf-8")
    return p


def round_rec(rn, champion, median, mean, n, vs_input, vs_incumbent, totals=None):
    return {"round": rn, "field": ["orig", champion], "field_size": 2,
            "scores_per_version": 2,
            "stats": {champion: {"median": median, "mean": mean, "n": n,
                                 "vs_original": vs_input, "vs_base": vs_incumbent,
                                 "author_placeholders": 1}},
            "selection": {"champion": champion, "champion_rep": champion},
            "stored_champion": champion,
            "issue_census": ({champion: census(totals)} if totals else {})}


tmp = Path(tempfile.mkdtemp(prefix="paper_trend_"))
root_a = tmp / "run-1-0920-aaaaaaa"
root_b = tmp / "run-2-0921-bbbbbbb"
write_decision(root_a, None, [
    round_rec(1, "i1", 2.0, 1.5, 42, 2.0, 2.0,
              {"correctness": 3, "writing": 1, "major": 3, "minor": 1})],
    {"champion": "i1", "format": {"rows": [{"rule": "FMT-T1"}], "high": 0, "medium": 1, "low": 0},
     "lengths": {"over_limit": []}})


# B CONSUMED A's output (the moving reference), and predates the census.
write_decision(root_b, root_a / "final_clean_version", [
    round_rec(2, "i3", 2.0, 1.0, 36, 2.0, 1.0),
    round_rec(3, "a2", 2.0, 1.1, 36, 2.0, 0.5)],
    {"champion": "a2", "format": {"rows": [{"rule": "FMT-T1"}, {"rule": "FMT-T2"}],
                                  "high": 0, "medium": 2, "low": 0},
     "lengths": {"over_limit": ["main text"]}})


def test_order():
    print("== the chain order comes from the recorded source, not the argument order ==")
    got = [Path(p).name for p in np.trend_order([str(root_b), str(root_a)])]
    check("the root whose source is inside the other is placed AFTER it",
          got == [root_a.name, root_b.name], str(got))
    lone = tmp / "run-lone-ccccccc"
    write_decision(lone, tmp / "not-a-root", [round_rec(1, "w1", 0.0, 0.0, 2, 0.0, 0.0)])
    got2 = [Path(p).name for p in np.trend_order([str(lone), str(root_b), str(root_a)])]
    check("an unlinked root keeps its given position instead of breaking the chain",
          got2[0] == lone.name and got2[1:] == [root_a.name, root_b.name], str(got2))


def test_rows():
    print()
    print("== per-round margins and the per-tier census are both reported ==")
    rr, run = np.trend_rows([str(root_b), str(root_a)])
    check("one round row per decided round, in chain order",
          [r["run"] for r in rr] == [root_a.name, root_b.name, root_b.name],
          str([r["run"] for r in rr]))
    a1 = rr[0]
    check("the round row carries the champion and its paired margins",
          (a1["round"], a1["champion"], a1["vs_input"], a1["vs_incumbent"]) == (1, "i1", 2.0, 2.0),
          str(a1))
    check("the champion's census is reported per tier and per severity",
          a1["correctness"] == 3 and a1["writing"] == 1 and a1["major"] == 3
          and a1["minor"] == 1 and a1["critical"] == 0, str(a1))
    check("a run decided before the census existed reports '-' (None), never a fake zero",
          all(rr[k]["correctness"] is None for k in (1, 2)), str(rr[1]))
    b2 = rr[2]
    check("the last round's paired incumbent margin (the diminishing-return signal) is present",
          (b2["round"], b2["champion"], b2["vs_incumbent"]) == (3, "a2", 0.5), str(b2))
    check("the per-run deterministic counters ride along",
          run[0]["format_rows"] == 1 and run[0]["over_length"] == 0
          and run[1]["format_rows"] == 2 and run[1]["over_length"] == 1
          and run[1]["champion"] == "a2", str(run))


def test_render_and_writes():
    print()
    print("== the report renders, and --out/--csv land on disk ==")
    rr, run = np.trend_rows([str(root_a), str(root_b)])
    text = np.format_trend(rr, run)
    check("the report states the reading rule (the reference moves with the chain)",
          "vs_input" in text and "vs_incumbent" in text
          and "reference" in text and "ISSUE CENSUS" in text)
    check("both tables are rendered with their headers",
          all(k in text for k in np.TREND_ROUND_FIELDS)
          and all(k in text for k in np.TREND_RUN_FIELDS))
    out = tmp / "TREND.md"
    csvp = tmp / "TREND.csv"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        np.cmd_trend(argparse.Namespace(root=str(root_a), roots=[str(root_a), str(root_b)],
                                        out=str(out), csv=str(csvp)))
    check("--out writes the markdown report",
          out.is_file() and "Cross-run trend" in out.read_text(encoding="utf-8"))
    with open(csvp, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    check("--csv writes one row per round with the census columns",
          len(rows) == 3 and list(rows[0]) == list(np.TREND_ROUND_FIELDS)
          and rows[0]["correctness"] == "3" and rows[1]["correctness"] == "",
          str(rows[0]))
    check("the console says where the files went",
          str(out) in buf.getvalue() and str(csvp) in buf.getvalue())


def test_cli_and_missing_roots():
    print()
    print("== CLI wiring and the undecided-root case ==")
    ns = np.build_parser().parse_args(["trend", "--roots", str(root_a), str(root_b),
                                       "--out", str(tmp / "x.md")])
    check("`trend` is a root-free, read-only subcommand",
          ns.cmd == "trend" and ns.func is np.cmd_trend and ns.roots == [str(root_a), str(root_b)]
          and ns.out == str(tmp / "x.md") and "trend" not in np.LOGGING_COMMANDS)
    missing = tmp / "never-decided"
    missing.mkdir(exist_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        np.cmd_trend(argparse.Namespace(root=str(missing), roots=[str(root_a), str(missing)],
                                        out=None, csv=None))
    check("an undecided root is reported as an empty run, not a crash",
          "no readable reports/decision.json" in buf.getvalue()
          and root_a.name in buf.getvalue(), buf.getvalue()[-200:])


def main() -> int:
    test_order()
    test_rows()
    test_render_and_writes()
    test_cli_and_missing_roots()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL TREND CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""decide must not certify a final champion the panel judged worse than the original.

`select_champion` deliberately exempts the round's own base from the vs-original
anti-regression gate: the base is the incumbent, and the no-progress fallback
crowns it even when nothing clears the gate. In round 2+ that base is the
inherited champion, so a stricter panel can judge it WORSE than the pristine
original while every fresh arm fails the gate -- and the round keeps it. Before
this suite's fix, `decide` then signed that winner with `problems=[]` and exit 0.

The suite drives a real two-round stub run whose judge is this file
(`--as-judge`): round 1 lets a fresh arm win (so a distinct pin exists), round 2
scores the pinned incumbent below `orig/` and every fresh arm below the
incumbent. The assertions are the certificate: the final champion's
`vs_original` is negative and `decide` refuses to certify it.

Run:  python3 .paper_test/test_decide_antiregression.py
`PAPER_WS` retargets the suite at another copy of the tree (red before the fix).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
STUB = HERE / "stub_agent.py"
ORIGINAL = "orig"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def basis(score: int) -> dict:
    """The graded basis (judge contract v2) for a forced +-2 stub score."""
    if score > 0:
        return {"basis": "consistency",
                "resolved": [{"check": "M1", "tier": "consistency", "severity": "major",
                              "evidence": "antiregression stub: target keeps this version stable"}],
                "introduced": []}
    if score < 0:
        return {"basis": "consistency", "resolved": [],
                "introduced": [{"check": "M1", "tier": "consistency", "severity": "major",
                                "evidence": "antiregression stub: opponent is the worse version"}]}
    return {"basis": "none", "resolved": [], "introduced": []}


JUDGE_CHECK_IDS = ([f"M{i}" for i in range(1, 18)]
                   + ["M18", "M19", "M20", "M21", "M22", "M23", "M24"]
                   + [f"J{i}" for i in range(1, 5)])


def checks_map(score: int) -> dict:
    """Contract v3 coverage: every frozen check id disposed for every opponent."""
    out = {c: "clean -- antiregression stub: forced profile" for c in JUDGE_CHECK_IDS}
    if score:
        out["M1"] = "findings -- antiregression stub: forced profile comparison"
    return out


def judge_main() -> int:
    """The instrumented judge: read its own issued labels, force the panel profile."""
    sb = Path.cwd()
    prompt = (sb / "PROMPT.md").read_text(encoding="utf-8")
    name = sb.name
    token = re.search(r'"target_id":\s*"([^"]+)"', prompt).group(1)
    jidx = int(re.search(r'"judge_index":\s*(\d+)', prompt).group(1))
    labels = [x.strip() for x in
              re.findall(r"no more, no fewer:\s*(.+)", prompt)[0].strip().split(",")]
    root = sb.parent.parent
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    runs = state.get("runs") or {}
    runs = list(runs.values()) if isinstance(runs, dict) else runs
    rec = next(r for r in runs if r.get("id") == name)
    vid = rec.get("target_id")
    r = int(rec.get("round") or 1)
    # The round record is saved after the judge wave, so the pinned champion of
    # the PREVIOUS round is read from the persistent pin list instead.
    pins = [p for p in (state.get("pinned") or []) if int(p.get("round") or 0) < r]
    base = (max(pins, key=lambda p: int(p.get("round") or 0))["id"] if pins else ORIGINAL)
    lmap = dict(rec.get("label_map") or {})
    comps = []
    round_one = (base == ORIGINAL)
    for lab in labels:
        opp = lmap.get(lab)
        if vid == ORIGINAL:
            # Round 1: the base IS the original, so every comparison is a clean 0.
            # Later rounds: the original beats the inherited (regressing) champion.
            score = 0 if round_one else (2 if opp == base else 0)
        elif vid == base:
            score = -2 if opp == ORIGINAL else 2
        else:
            # Round 1: let a fresh arm win so a distinct pin exists for round 2.
            # Later rounds: every fresh arm fails the gate against the original.
            score = (2 if opp == base else 0) if round_one else \
                (-2 if opp in (base, ORIGINAL) else 0)
        comps.append({"opponent_label": lab, "score": score,
                      "reason": "antiregression-certificate stub: forced panel profile",
                      "checks": checks_map(score),
                      **basis(score)})
    (sb / "scores.json").write_text(json.dumps({
        "run_id": name, "target_id": token, "judge_index": jidx,
        "comparisons": comps, "notes": "forced panel: incumbent below the original"}),
        encoding="utf-8")
    jr = sb / "judge_review"
    (jr / "artifacts").mkdir(parents=True, exist_ok=True)
    (jr / "inventory.md").write_text("# inventory (antiregression stub judge)\n",
                                     encoding="utf-8")
    (jr / "artifacts" / "M1_acronyms.md").write_text("| row |\n|---|\n", encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(json.dumps(
        {"stage": "judge", "run_id": name, "status": "complete", "error": None}),
        encoding="utf-8")
    return 0


def test_decide_refuses_to_certify_a_regression():
    print("== decide: a final champion judged below the original is not certified ==")
    tmp = Path(tempfile.mkdtemp(prefix="paper_antireg_"))
    TMPDIRS.append(tmp)
    source = tmp / "source"
    (source / "raw_figs").mkdir(parents=True)
    (source / "manuscript-b.md").write_text("title\n", encoding="utf-8")
    (source / "raw_figs" / "data.tsv").write_text("a\tb\n", encoding="utf-8")
    root = tmp / "root"
    setup = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                            "--source", str(source), "--root", str(root),
                            "--rounds", "2", "--judges", "1",
                            "--rewrites", "1", "--revises", "1"],
                           capture_output=True, text=True, timeout=600)
    check("setup succeeds", setup.returncode == 0, (setup.stdout + setup.stderr)[-300:])
    run = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "run",
                          "--root", str(root), "--jobs", "4",
                          "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
                          "--judge-agent-cmd",
                          json.dumps([sys.executable, str(Path(__file__).resolve()),
                                      "--as-judge"]),
                          "--retries", "0", "--retry-backoff", "0"],
                         capture_output=True, text=True, timeout=1800)
    out = run.stdout + run.stderr
    check("both rounds complete", run.returncode == 0, out[-400:])
    dec = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "decide",
                          "--root", str(root)],
                         capture_output=True, text=True, timeout=900)
    dj_path = root / "reports" / "decision.json"
    check("decide wrote decision.json", dj_path.is_file())
    dj = json.loads(dj_path.read_text(encoding="utf-8"))
    last = (dj.get("rounds") or [{}])[-1]
    champion = last.get("stored_champion")
    rep = (last.get("selection") or {}).get("champion_rep")
    row = ((last.get("stats") or {}).get(rep) or {})
    check("the scenario materialized: the inherited base is the final champion",
          champion == "a1" and bool(rep) and rep != ORIGINAL,
          f"champion={champion!r} rep={rep!r}")
    check("the panel judged the final champion worse than the pristine original",
          row.get("anti_regression_ok") is False and (row.get("vs_original") or 0) < 0,
          f"vs_original={row.get('vs_original')!r} anti_regression_ok="
          f"{row.get('anti_regression_ok')!r}")
    problems = dj.get("problems") or []
    check("decide records the anti-regression problem",
          any("WORSE than the pristine original" in str(p) for p in problems),
          str(problems)[:300])
    check("decide refuses to certify (exit 5)", dec.returncode == 5,
          f"rc={dec.returncode} out={(dec.stdout + dec.stderr)[-300:]}")


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    if "--as-judge" in sys.argv[1:]:
        return judge_main()
    test_decide_refuses_to_certify_a_regression()
    cleanup()
    if FAILS:
        print(f"\n[FAIL] {len(FAILS)} check(s) failed: {', '.join(FAILS)}")
        return 1
    print("\n[ok ] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

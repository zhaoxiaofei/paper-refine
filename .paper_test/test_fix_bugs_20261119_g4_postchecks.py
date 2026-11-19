#!/usr/bin/env python3
"""Regression checks for fix-bugs group g4_postchecks (run 2026-11-19_232857).

One hermetic check per confirmed candidate: F021, F023, F046, F048, F063,
F095, F096 and the documentation mismatch F152. Fixtures live in tempfile
directories; no network, no pipeline root, no real agent.

Run:  python3 .paper_test/test_fix_bugs_20261119_g4_postchecks.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1119g4_pp", "paper_pipeline.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


# ---------------------------------------------------------------- F021
def test_f021_truncated_trial_record() -> None:
    print("\n== F021: a truncated trial record is UNKNOWN, not zero FAIL messages ==")
    root = scratch("g4_f021_") / "root"
    (root / "runs").mkdir(parents=True)

    class Ctx:
        def __init__(self, root: Path):
            self.root = root
            self.runs_dir = root / "runs"

        def sandbox_of(self, rec):
            return self.root / rec["sandbox"]

    def trial(n: int, record: dict) -> Path:
        sb = root / "runs" / f"r1_x_try{n}_failed"
        (sb / pp.REWRITTEN_DIR).mkdir(parents=True)
        (sb / "record.json").write_text(json.dumps(record), encoding="utf-8")
        (sb / pp.REWRITTEN_DIR / "a.txt").write_text("a", encoding="utf-8")
        (sb / pp.MARKER_FILE).write_text(json.dumps(
            {"stage": "rewrite", "run_id": "r1_x", "status": "complete"}),
            encoding="utf-8")
        return sb

    truncated = trial(1, {"attempt": 1})
    real = trial(2, {"attempt": 2, "errors": ["boom"], "warnings": []})
    rec = {"id": "r1_x", "kind": "rewrite", "round": 1, "sandbox": "runs/r1_x"}
    best = pp.best_failed_trial(Ctx(root), rec) or {}
    check("F021 the real attempt beats the truncated record",
          Path(best.get("sandbox") or "") == real
          and truncated != Path(best.get("sandbox") or ""),
          str(best.get("sandbox")))
    check("F021 the chosen record is known and carries its FAIL message",
          best.get("record_known") is True and best.get("fail_messages") == 1, str(best))

    only_root = scratch("g4_f021b_") / "root"
    (only_root / "runs").mkdir(parents=True)
    only = only_root / "runs" / "r1_x_try1_failed"
    (only / pp.REWRITTEN_DIR).mkdir(parents=True)
    (only / "record.json").write_text('{"attempt": 1}', encoding="utf-8")
    (only / pp.REWRITTEN_DIR / "a.txt").write_text("a", encoding="utf-8")
    (only / pp.MARKER_FILE).write_text(json.dumps(
        {"stage": "rewrite", "run_id": "r1_x", "status": "complete"}), encoding="utf-8")
    best2 = pp.best_failed_trial(Ctx(only_root), rec) or {}
    check("F021 a record with no errors list is reported UNKNOWN",
          best2.get("record_known") is False and best2.get("fail_messages") == 0,
          str(best2))
    check("F021 the truncated trial is still the only candidate found",
          Path(best2.get("sandbox") or "") == only, str(best2.get("sandbox")))


# ---------------------------------------------------------------- F023
def test_f023_root_completion_signal() -> None:
    print("\n== F023: a root completion signal must name THIS run ==")
    root = scratch("g4_f023_")
    sb = root / "runs" / "r1_review"
    sb.mkdir(parents=True)
    rec = {"id": "r1_review", "kind": "guided_review", "round": 1,
           "sandbox": "runs/r1_review"}

    class Ctx:
        def __init__(self, root: Path):
            self.root = root

        def sandbox_of(self, rec):
            return self.root / rec["sandbox"]

    ctx = Ctx(root)

    def signal(data) -> bool:
        (sb / pp.MARKER_FILE).write_text(json.dumps(data), encoding="utf-8")
        return pp.completion_signal_exists(ctx, rec)

    check("F023 an empty root object is not a completion signal", signal({}) is False)
    check("F023 another stage's root marker is not a completion signal",
          signal({"stage": "audit", "run_id": "r1_audit", "status": "complete"}) is False)
    check("F023 another run's root marker is not a completion signal",
          signal({"stage": "guided_review", "run_id": "r1_other",
                  "status": "complete"}) is False)
    check("F023 this run's own marker is a completion signal",
          signal({"stage": "guided_review", "run_id": "r1_review",
                  "status": "complete"}) is True)
    check("F023 a marker without stage still names this run by its root context",
          signal({"run_id": "r1_review", "status": "complete"}) is True)
    # A failed marker is this attempt's TERMINAL signal: the postcheck must see
    # it to record the failure and retry (requiring status=='complete' here
    # would leave a crashed attempt waiting forever).
    check("F023 an own failed marker still reaches the postcheck",
          signal({"stage": "guided_review", "run_id": "r1_review",
                  "status": "failed"}) is True)

    # The judge sheet branch is root-authoritative for a NON-empty sheet, but an
    # anonymous sheet is not adoptable either (F189).
    (sb / pp.MARKER_FILE).unlink()
    jsb = pp.find_signal_path(sb, "guided_review", pp.MARKER_FILE).parent
    scores = jsb / pp.SCORES_FILE
    scores.write_text("{}", encoding="utf-8")
    jrec = {"id": "r1_judge_w1_j1", "kind": "judge", "round": 1,
            "sandbox": "runs/r1_review", "target_id": "w1"}
    check("F023 an empty scores.json is not a completion signal",
          pp.completion_signal_exists(ctx, jrec) is False)
    scores.write_text(json.dumps({"run_id": "r1_judge_w1_j1", "comparisons": []}),
                      encoding="utf-8")
    check("F023 a scores.json naming this run is a completion signal",
          pp.completion_signal_exists(ctx, jrec) is True)


# ---------------------------------------------------------------- F046 / F048
def test_f046_manual_required_verdict() -> None:
    print("\n== F046: a one-column manual-required row is its final outcome ==")
    row = {"id": "F-1", "verdict": "manual-required", "final_status": ""}
    check("F046 the verdict column supplies the final outcome",
          pp._ledger_final_status(row) == "manual-required",
          repr(pp._ledger_final_status(row)))
    check("F046 a confirmed re-verification verdict is NOT a final status",
          pp._ledger_final_status({"id": "F-2", "verdict": "confirmed"}) == "")
    errs, warns = pp.finding_removal_messages(
        [{"id": "F-1", "final": pp._ledger_final_status(row),
          "lost": ["the removed sentence"]}])
    check("F046 the legitimate manual-required removal is not an error",
          errs == [] and len(warns) == 1, f"errs={errs} warns={warns}")
    pkg = scratch("g4_f046_")
    (pkg / "revision_report.json").write_text(json.dumps([row]), encoding="utf-8")
    got = pp.revision_ledger_final_status(pkg)
    check("F046 the package ledger reads the manual-required outcome",
          got.get("F-1") == "manual-required", str(got))


def test_f048_non_vocabulary_final_status() -> None:
    print("\n== F048: a present non-vocabulary final_status fails closed ==")
    check("F048 'not fixed' does not fall through to status='fixed'",
          pp._ledger_final_status({"final_status": "not fixed",
                                   "status": "fixed"}) == "")
    check("F048 'partially fixed' does not fall through to status='manual-required'",
          pp._ledger_final_status({"final_status": "partially fixed",
                                   "status": "manual-required"}) == "")
    check("F048 a documented final status still wins",
          pp._ledger_final_status({"final_status": "fixed",
                                   "status": "manual-required"}) == "fixed")
    check("F048 an EMPTY final_status still falls through to the next column",
          pp._ledger_final_status({"final_status": "",
                                   "status": "fixed"}) == "fixed")


# ---------------------------------------------------------------- F063
def test_f063_absent_pristine_raw_data() -> None:
    print("\n== F063: a package cannot create raw_data/ when the pristine has none ==")
    root = scratch("g4_f063_") / "root"
    pristine = root / "non_revised"
    pristine.mkdir(parents=True)
    cand = root / "sandbox"
    (cand / "raw_data").mkdir(parents=True)
    (cand / "raw_data" / "fabricated.csv").write_text("fake", encoding="utf-8")
    outside = root / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (cand / "raw_data" / "link.tsv").symlink_to(outside)
    warns = []
    ctx = pp.Ctx(root)
    ctx.pristine = pristine
    info = pp.enforce_readonly_raw_data(ctx, cand, warns)
    check("F063 the fabricated files are dropped",
          "raw_data/fabricated.csv" in (info.get("dropped") or [])
          and "raw_data/link.tsv" in (info.get("dropped") or []), str(info))
    check("F063 the fabricated area is gone",
          not (cand / "raw_data" / "fabricated.csv").exists()
          and not (cand / "raw_data" / "link.tsv").is_symlink(), str(info))
    check("F063 the fabrication fails the attempt",
          bool(info.get("failures")), str(info.get("failures")))
    check("F063 the fabrication is warned about", bool(warns), str(warns))

    cand2 = root / "sandbox2"
    (cand2 / "raw_data").mkdir(parents=True)
    (cand2 / "raw_data" / "fake.txt").write_text("fake", encoding="utf-8")
    vinfo = pp.verify_readonly_raw_data(ctx, cand2, [])
    check("F063 verify turns the fabrication into the error channel",
          bool(vinfo.get("readonly_failures")), str(vinfo.get("readonly_failures")))

    clean = root / "sandbox3"
    clean.mkdir()
    info3 = pp.enforce_readonly_raw_data(ctx, clean, [])
    check("F063 a package with no raw_data/ is still a clean no-op",
          info3.get("present") is False and info3.get("failures") == []
          and info3.get("dropped") == [], str(info3))


# ---------------------------------------------------------------- F095
def _agg_ctx(tmp: Path, runs: dict):
    root = tmp / "root"
    (root / "reports").mkdir(parents=True)
    (root / "runs").mkdir()
    ctx = pp.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": 0, "revises": 0}
    ctx.state = {"version": pp.STATE_VERSION, "runs": dict(runs), "rounds": {},
                 "pinned": [], "log": [], "original_digest": "d_orig",
                 "config": ctx.cfg}
    ctx.state["rounds"]["1"] = {
        "id": 1, "status": "pending",
        "plan": {"rewrites": 0, "revises": 0, "integrated": [], "judges": 1}}
    return ctx


def _judge_rec(rid: str, target: str, comps: list) -> dict:
    return {"id": rid, "kind": "judge", "round": 1, "status": "done",
            "target_id": target, "judge_index": 1,
            "label_map": {"v1": "w1", "v2": "orig"},
            "created": "2026-01-01T00:00:00Z",
            "scores": {"comparisons": comps}}


def test_f095_duplicate_comparison_does_not_incomplete_opponent() -> None:
    print("\n== F095: a duplicate in one sheet does not disqualify the opponent ==")
    tmp = scratch("g4_f095_")
    ctx = _agg_ctx(tmp, {
        "j_o": _judge_rec("j_o", "orig", [{"opponent_label": "v1", "score": 0}]),
        "j_w": _judge_rec("j_w", "w1", [{"opponent_label": "v2", "score": 0},
                                        {"opponent_label": "v2", "score": 0}]),
    })
    agg = pp.aggregate_round(ctx, 1, ["orig", "w1"])
    orig = agg["stats"]["orig"]
    w1 = agg["stats"]["w1"]
    check("F095 the opponent's directed counts are exactly expected",
          orig["n"] == orig["expected_n"] == 2, f"n={orig['n']} exp={orig['expected_n']}")
    check("F095 the innocent opponent stays eligible",
          orig["complete"] is True, str(orig["complete"]))
    check("F095 the duplicated sheet's TARGET is still incomplete",
          w1["complete"] is False, str(w1["complete"]))
    check("F095 the duplicate is still diagnosed",
          any("reported twice" in d
              for d in (agg["diagnostics"].get("duplicate_comparisons") or [])),
          str(agg["diagnostics"].get("duplicate_comparisons")))


# ---------------------------------------------------------------- F096
def test_f096_one_pin_per_round() -> None:
    print("\n== F096: re-deciding a round replaces its pin ==")
    tmp = scratch("g4_f096_")
    root = tmp / "root"
    (root / "reports").mkdir(parents=True)
    (root / "runs").mkdir()
    ctx = pp.Ctx(root)
    ctx.cfg = {"rounds": 2, "judges": 1, "rewrites": 0, "revises": 0}
    ctx.state = {"version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "original_digest": "d_orig", "config": ctx.cfg}

    def fake_build(_ctx, _r, vid, dst):
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "main.md").write_text("bytes " + vid, encoding="utf-8")

    def digest_for(vid: str) -> str:
        d = tmp / ("corpus_" + vid)
        d.mkdir(exist_ok=True)
        (d / "main.md").write_text("bytes " + vid, encoding="utf-8")
        return pp.manifest_digest(pp.corpus_dir_manifest(d))

    saved = {n: getattr(pp, n) for n in (
        "build_corpus_dir", "recorded_version_digest", "stats_row_for",
        "caption_info_for", "scan_captions_in_sources", "effective_content_fingerprint",
        "placeholder_info_for", "working_original_digest")}
    pp.build_corpus_dir = fake_build
    pp.recorded_version_digest = lambda c, r, vid: digest_for(vid)
    pp.stats_row_for = lambda *a: {}
    pp.caption_info_for = lambda *a: {}
    pp.scan_captions_in_sources = lambda *a, **k: {}
    pp.effective_content_fingerprint = lambda c, r, vid: "FP-" + vid
    pp.placeholder_info_for = lambda *a: {}
    pp.working_original_digest = lambda c: "d_orig"
    try:
        pp.pin_champion(ctx, 1, "w1", {})
        pp.pin_champion(ctx, 1, "a2", {})
        pinned = [p["id"] for p in ctx.state["pinned"]]
        check("F096 the re-decided round keeps exactly its new pin",
              pinned == ["r1_a2"], str(pinned))
        field, _dropped = pp.build_field(ctx, 2)
        ids = [e["id"] for e in field]
        check("F096 the superseded version is not a member of the next field",
              "r1_a2" in ids and "r1_w1" not in ids, str(ids))
        check("F096 the superseded pin directory is archived, not deleted",
              not (ctx.pins_dir / "r1_w1").exists()
              and any(p.name.startswith("r1_w1.")
                      for p in (ctx.pins_dir / "_superseded").iterdir()),
              str(sorted(p.name for p in (ctx.pins_dir / "_superseded").iterdir())))
        pp.pin_champion(ctx, 1, "a2", {})
        check("F096 pinning the same champion again stays one pin",
              [p["id"] for p in ctx.state["pinned"]] == ["r1_a2"],
              str([p["id"] for p in ctx.state["pinned"]]))
    finally:
        for name, value in saved.items():
            setattr(pp, name, value)


# ---------------------------------------------------------------- F152
def test_f152_readme_names_the_written_artifact() -> None:
    print("\n== F152: the README's artifact table names FORMAT_FIX_<id>.json ==")
    readme = (WS / "README.md").read_text(encoding="utf-8")
    check("F152 the artifact table uses the suffixed name",
          "runs/<id>/FORMAT_FIX_<id>.json" in readme)
    check("F152 the table no longer names the file nobody writes",
          "runs/<id>/FORMAT_FIX.json" not in readme)
    writer = (WS / "paper_pipeline_parts" / "p05_state_corpus.py").read_text(encoding="utf-8")
    check("F152 the writer still creates the suffixed artifact",
          'f"{sb}/FORMAT_FIX_{ff_name}.json"' in writer)


def main() -> int:
    for fn in (test_f021_truncated_trial_record,
               test_f023_root_completion_signal,
               test_f046_manual_required_verdict,
               test_f048_non_vocabulary_final_status,
               test_f063_absent_pristine_raw_data,
               test_f095_duplicate_comparison_does_not_incomplete_opponent,
               test_f096_one_pin_per_round,
               test_f152_readme_names_the_written_artifact):
        fn()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("all g4_postchecks regression checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

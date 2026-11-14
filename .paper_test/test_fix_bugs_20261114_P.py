#!/usr/bin/env python3
"""Regression checks for the 2026-11-14 fix-bugs group P selection/round fixes.

F181  finalize_round freezes the tiebreak floor selection ACTUALLY used
F182  a review-archive failure is recorded on the round record (best-effort kept)
F183  pin idempotence compares the SAME manifest rule on both sides
F184  pin_champion's docstring states the intended one-pin-per-round chain
F185  select_champion's trace survives a complete row with missing statistics
F186  round_member_table_rows renders '-' for a member with no stats row
F189  vs_base_expected uses the enabled per-version judge counts

Self-contained and fast: every probe builds a throwaway root under
tempfile.mkdtemp().
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("paperp", WS / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp"] = np
spec.loader.exec_module(np)

FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[ok ] " if ok else "[FAIL] ") + name
          + (f"  [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


def mkctx(tmp: Path, cfg: dict):
    root = tmp / "root"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    ctx = np.Ctx(root)
    ctx.cfg = dict(cfg)
    ctx.state = {"version": np.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "original_digest": "d_orig", "config": ctx.cfg}
    return ctx


def full_row(vid: str, **over) -> dict:
    row = {"id": vid, "digest": "d_" + vid, "n": 4, "expected_n": 4, "complete": True,
           "median": 0.0, "mean": 0.0, "iqr": 0.0, "vs_original": 0.0,
           "vs_original_n": 4, "vs_original_expected": 4, "vs_original_complete": True,
           "vs_original_wins": 0, "vs_original_losses": 0, "vs_original_ties": 4,
           "vs_original_sign_p": 1.0, "anti_regression_rule": None,
           "anti_regression_ok": True, "vs_base": 0.0, "vs_base_n": 4,
           "vs_base_vals": [], "vs_base_expected": 4, "is_base": False,
           "own_counts": {}, "received_counts": {}, "judges_seen": 1,
           "judges_expected": 1, "caption_gate_ok": True, "caption_note": None,
           "captions": None, "author_placeholders": 0, "placeholder_documents": []}
    row.update(over)
    return row


def round_one_ctx(tmp: Path, **cfg):
    c = {"rounds": 1, "judges": 2, "rewrites": 1, "revises": 0}
    c.update(cfg)
    ctx = mkctx(tmp, c)
    ctx.state["rounds"]["1"] = {"id": 1, "status": "pending",
                                "plan": {"rewrites": 1, "revises": 0,
                                         "integrated": [], "judges": 2}}
    agg = {"stats": {"w1": full_row("w1")}, "base_rep": None, "issue_census": {},
           "field": ["w1"], "field_size": 1, "scores_per_version": 2,
           "diagnostics": {}, "dedup_mode": None, "anti_regression_rule": None}
    return ctx, agg, [{"id": "w1", "digest": "d_w1"}]


# ---------------------------------------------------------------- F181
def test_f181() -> None:
    print("\n== F181: the used tiebreak floor is frozen ==")
    with tempfile.TemporaryDirectory(prefix="fixP-f181-") as tmp:
        ctx, agg, field = round_one_ctx(Path(tmp), tiebreak_defect_floor=10)
        sel = np.select_champion(ctx, 1, agg, floor=3)
        rrec = np.finalize_round(ctx, 1, field, [], agg, sel,
                                 {"id": "r1_w1", "digest": "d_w1"})
        check("F181 the round record freezes floor 3, not today's config floor 10",
              (sel.get("tiebreak") or {}).get("floor") == 3
              and rrec.get("tiebreak_defect_floor") == 3,
              f"used={(sel.get('tiebreak') or {}).get('floor')} "
              f"recorded={rrec.get('tiebreak_defect_floor')}")
        disk = json.loads((ctx.reports_dir / "round1.json").read_text(
            encoding="utf-8"))["round_record"]
        check("F181 the frozen floor is in the on-disk round record too",
              disk.get("tiebreak_defect_floor") == 3, str(disk.get("tiebreak_defect_floor")))


# ---------------------------------------------------------------- F182
def test_f182() -> None:
    print("\n== F182: an archive failure is recorded, not just printed ==")
    with tempfile.TemporaryDirectory(prefix="fixP-f182-") as tmp:
        ctx, agg, field = round_one_ctx(Path(tmp))
        sel = np.select_champion(ctx, 1, agg)
        real = np.archive_review_outputs
        np.archive_review_outputs = lambda c, r: (_ for _ in ()).throw(
            RuntimeError("disk full"))
        try:
            rrec = np.finalize_round(ctx, 1, field, [], agg, sel,
                                     {"id": "r1_w1", "digest": "d_w1"})
        finally:
            np.archive_review_outputs = real
        disk = json.loads((ctx.reports_dir / "round1.json").read_text(
            encoding="utf-8"))["round_record"]
        check("F182 the failure is on the round record (state and artifact)",
              rrec.get("review_archive_error") == "disk full"
              and disk.get("review_archive_error") == "disk full",
              f"state={rrec.get('review_archive_error')!r} "
              f"disk={disk.get('review_archive_error')!r}")
        check("F182 the archive stays best-effort: the round is still done",
              rrec.get("status") == "done" and rrec.get("completed"))


# ---------------------------------------------------------------- F183
def test_f183() -> None:
    print("\n== F183: pin idempotence compares like with like ==")
    with tempfile.TemporaryDirectory(prefix="fixP-f183-") as tmp:
        ctx, _agg, _field = round_one_ctx(Path(tmp))
        docs = ctx.pins_dir / "r1_w1" / "documents"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "main.md").write_text("same bytes\n", encoding="utf-8")
        # Legacy pin carrying the pipeline's own bookkeeping: the corpus rule
        # strips it, so it must not make identical bytes look different.
        (docs / "CHANGELOG.md").write_text("bookkeeping\n", encoding="utf-8")
        saved = (np.build_corpus_dir, np.recorded_version_digest, np.caption_info_for,
                 np.scan_captions_in_sources, np.effective_content_fingerprint,
                 np.placeholder_info_for)
        np.build_corpus_dir = lambda c, r, vid, dst: (
            dst.mkdir(parents=True, exist_ok=True),
            (dst / "main.md").write_text("same bytes\n", encoding="utf-8"))
        np.recorded_version_digest = lambda c, r, vid: None
        np.caption_info_for = lambda c, r, vid: None
        np.scan_captions_in_sources = lambda *a, **k: None
        np.effective_content_fingerprint = lambda c, r, vid: "FP"
        np.placeholder_info_for = lambda c, r, vid: {}
        try:
            np.pin_champion(ctx, 1, "w1", {})
        finally:
            (np.build_corpus_dir, np.recorded_version_digest, np.caption_info_for,
             np.scan_captions_in_sources, np.effective_content_fingerprint,
             np.placeholder_info_for) = saved
        check("F183 an identical existing pin is kept (no _superseded churn)",
              not (ctx.pins_dir / "_superseded").exists()
              and (docs / "main.md").is_file(),
              str(sorted(p.name for p in (ctx.pins_dir / "r1_w1").iterdir())))
        check("F183 the legacy bookkeeping file was not treated as content",
              (docs / "CHANGELOG.md").is_file()
              and (ctx.pins_dir / "r1_w1" / "documents.tmp").exists() is False,
              "documents.tmp should have been removed as identical")


# ---------------------------------------------------------------- F184
def test_f184() -> None:
    print("\n== F184: pin_champion documents the per-round pin chain ==")
    doc = " ".join((np.pin_champion.__doc__ or "").lower().split())
    check("F184 the docstring promises one pin record per round",
          "one pin record per round" in doc, doc[:200])
    check("F184 the docstring no longer promises digest-deduplicated pins",
          "deduplicated by content digest" not in doc, doc[:200])


# ---------------------------------------------------------------- F185
def test_f185() -> None:
    print("\n== F185: a complete row with missing statistics does not crash ==")
    with tempfile.TemporaryDirectory(prefix="fixP-f185-") as tmp:
        ctx = mkctx(Path(tmp), {"rounds": 1, "judges": 1, "rewrites": 1, "revises": 0})
        ctx.state["rounds"]["1"] = {"id": 1, "status": "pending",
                                    "plan": {"rewrites": 1, "revises": 0,
                                             "integrated": [], "judges": 1}}
        ctx.state["runs"]["r1_w1"] = {"id": "r1_w1", "kind": "rewrite", "round": 1,
                                      "status": "done", "corpus_digest": "d_w1",
                                      "summary": {}}
        agg = {"stats": {"w1": full_row("w1", median=None, mean=None, iqr=None)},
               "base_rep": None, "issue_census": {}, "field": ["w1"]}
        try:
            sel = np.select_champion(ctx, 1, agg)
            outcome = "no error"
            trace = "\n".join(sel.get("trace") or [])
        except Exception as e:                                  # noqa: BLE001
            outcome = f"{type(e).__name__}: {e}"
            trace = ""
        check("F185 select_champion returns a ranking despite the missing stats",
              outcome == "no error", outcome)
        check("F185 the trace renders the missing statistics as n/a",
              "median=n/a" in trace and "mean=n/a" in trace and "iqr=n/a" in trace,
              trace[:300])


# ---------------------------------------------------------------- F186
def test_f186() -> None:
    print("\n== F186: a member with no stats row renders '-' ==")
    with tempfile.TemporaryDirectory(prefix="fixP-f186-") as tmp:
        ctx = mkctx(Path(tmp), {"rounds": 1, "judges": 1})
        agg = {"stats": {"w1": full_row("w1")}, "issue_census": {}}
        sel = {"ranking": [], "champion": "w1", "champion_rep": "w1"}
        try:
            rows = np.round_member_table_rows(
                ctx, 1, [{"id": "w1"}, {"id": "gone"}], agg, sel, "w1")
            outcome = "no error"
        except Exception as e:                                  # noqa: BLE001
            rows, outcome = [], f"{type(e).__name__}: {e}"
        check("F186 the table is built for a field member without a stats row",
              outcome == "no error" and len(rows) == 3, outcome)
        missing = [r for r in rows[1:] if r[0] == "gone"]
        check("F186 the missing member's statistics are all '-'",
              bool(missing) and missing[0][2:9] == ["-"] * 7,
              str(missing[0]) if missing else "row absent")


# ---------------------------------------------------------------- F189
def test_f189() -> None:
    print("\n== F189: vs_base_expected follows the enabled judge panel ==")
    with tempfile.TemporaryDirectory(prefix="fixP-f189-") as tmp:
        ctx = mkctx(Path(tmp), {"rounds": 2, "judges": 2, "rewrites": 0, "revises": 1})
        ctx.state["pinned"] = [{"id": "r1_a2", "round": 1, "digest": "d_pin",
                                "content_fingerprint": "FP"}]
        ctx.state["runs"]["r2_a1"] = {"id": "r2_a1", "kind": "a1", "round": 2,
                                      "status": "done", "corpus_digest": "d_pin",
                                      "content_fingerprint": "FP",
                                      "sandbox": "runs/r2_a1"}
        ctx.state["rounds"]["2"] = {
            "id": 2, "status": "pending",
            "plan": {"rewrites": 0, "revises": 1, "integrated": [], "integrators": 0,
                     "judges": 2, "judges_enabled": "r2_a2_j1 r2_r1_a2_j2"}}
        agg = np.aggregate_round(ctx, 2, ["orig", "r1_a2", "a2"])
        check("F189 the base representative is the previous pin", agg.get("base_rep") == "r1_a2",
              str(agg.get("base_rep")))
        check("F189 a2's vs_base expectation is J(a2)+J(base)=2, not 2*judges=4",
              agg["stats"]["a2"]["vs_base_expected"] == 2,
              str(agg["stats"]["a2"]["vs_base_expected"]))
        check("F189 the original's vs_base expectation is J(orig)+J(base)=1",
              agg["stats"]["orig"]["vs_base_expected"] == 1,
              str(agg["stats"]["orig"]["vs_base_expected"]))


def main() -> int:
    for fn in (test_f181, test_f182, test_f183, test_f184,
               test_f185, test_f186, test_f189):
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all group P regression checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

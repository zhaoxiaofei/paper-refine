#!/usr/bin/env python3
"""Grading-scheme redesign: the graded basis, panel robustness, tie-breaks.

The judge panel is the pipeline's measurement instrument, so its own failure
modes are tested here like any other code path. Each check below is a bug or a
calibration gap found by reading the aggregation code against the production
panel (`reports/raw_scores.csv`: 294 directed scores, -3..+3 used, +-4 never):

  A. panel integrity -- a superseded/duplicate judge sheet and a sheet whose
     judge index is outside the configured range must not poison the panel
     (before: n > expected was reported as "PANEL INCOMPLETE" and the round
     silently fell back to the base);
  B. tie-breaks -- a perfect statistical tie must not be decided by the arm's
     NAME (a2 < i1 < w1 silently favoured the revise arm on every tie);
  C. the graded basis (judge contract v2) -- a score must be checkable:
     basis tier + ledger items, with the arithmetic rules enforced and legacy
     sheets tolerated-but-counted instead of silently mixed in;
  D. reporting -- calibration diagnostics, the score model in decision.json,
     the raw-score audit trail and the judge prompt itself.

Run:  python3 .paper_test/test_grading_scheme.py
`PAPER_WS` retargets the harness at a baseline copy (pre-change -> red).
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paperp", WS / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp"] = np
spec.loader.exec_module(np)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


FIELD = ["orig", "r1_a2", "w1", "a2", "i1", "i2", "i3"]
DIGESTS = {"orig": "d_orig", "r1_a2": "d_pin", "w1": "a_w1", "a2": "z_a2",
           "i1": "m_i1", "i2": "m_i2", "i3": "m_i3"}


def make_ctx(tmp: Path, judges=1, digests=None, summaries=None):
    """A round-2 root whose field is FIELD (base pin = r1_a2, digest d_pin)."""
    dig = dict(DIGESTS)
    dig.update(digests or {})
    ctx = np.Ctx(tmp)
    ctx.cfg = {"rounds": 2, "judges": judges, "caption_limit": 0,
               "rewrites": [1, 1], "revises": [1, 1]}
    ctx.state = {"version": np.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": {"files": {}, "count": 0},
                 "original_digest": dig["orig"], "config": ctx.cfg}
    ctx.state["pinned"] = [{"id": "r1_a2", "round": 1, "digest": dig["r1_a2"],
                            "source_id": "a2", "captions": None}]
    ctx.state["runs"]["r2_a1"] = {"id": "r2_a1", "kind": "a1", "round": 2,
                                  "sandbox": "runs/r2_a1", "status": "done",
                                  "corpus_digest": dig["r1_a2"], "attempts": 1, "summary": None}
    for vid in ("w1", "a2", "i1", "i2", "i3"):
        rid = np.rid_for_fresh(2, vid)
        summ = {"critical_remaining": 0, "manual_items": 0}
        summ.update((summaries or {}).get(vid) or {})
        ctx.state["runs"][rid] = {
            "id": rid, "kind": ("rewrite" if vid.startswith("w")
                                else "revise" if vid.startswith("a") else "integrate"),
            "round": 2, "sandbox": f"runs/{rid}", "status": "done",
            "corpus_digest": dig[vid], "attempts": 1,
            "summary": summ}
    (tmp / "reports").mkdir(parents=True, exist_ok=True)
    return ctx


def add_judge(ctx, vid, judge_index, scores, suffix="", contract=None, finished=None,
              basis=True):
    others = [w for w in FIELD if w != vid]
    labels = [f"v{i + 1}" for i in range(len(others))]
    tok = np.judge_target_token(2, vid)
    rid = np.rid_judge(2, tok, judge_index) + suffix
    comps = []
    for lab, opp in zip(labels, others):
        c = {"opponent_label": lab, "score": int(scores.get(opp, 0)), "reason": "synthetic"}
        if basis:
            c.update(stub_basis(c["score"]))
        comps.append(c)
    rec = {"id": rid, "kind": "judge", "round": 2, "status": "done", "target_id": vid,
           "judge_index": judge_index, "label_map": dict(zip(labels, others)), "attempts": 1,
           "sandbox": f"runs/{rid}", "finished": finished or f"2026-01-01T00:00:{judge_index:02d}",
           "scores": {"run_id": rid, "round": 2, "target_id": vid, "judge_index": judge_index,
                      "comparisons": comps}}
    if contract is not None:
        rec["contract"] = contract
    ctx.state["runs"][rid] = rec
    return rid


def stub_basis(score: int) -> dict:
    """A valid ledger for a synthetic |score| <= 2 (contract v2)."""
    if score > 0:
        return {"basis": "consistency",
                "resolved": [{"tier": "consistency", "severity": "minor",
                              "evidence": "synthetic unit-test item, target side"}],
                "introduced": []}
    if score < 0:
        return {"basis": "consistency", "resolved": [],
                "introduced": [{"tier": "consistency", "severity": "minor",
                                "evidence": "synthetic unit-test item, opponent side"}]}
    return {"basis": "none", "resolved": [], "introduced": []}


def full_panel(ctx, matrix, judges=1):
    for vid in FIELD:
        for j in range(1, judges + 1):
            add_judge(ctx, vid, j, {o: matrix.get((vid, o), 0) for o in FIELD if o != vid})


def tie_matrix():
    """Every challenger beats the base (+1 both ways); nothing else differs."""
    m = {}
    for x in ("w1", "a2", "i1", "i2", "i3"):
        m[(x, "r1_a2")] = 1
        m[("r1_a2", x)] = -1
    return m


# =====================================================================
# A. panel integrity
# =====================================================================
tmp = Path(tempfile.mkdtemp(prefix="paper_grade_a1_"))
ctx = make_ctx(tmp)
full_panel(ctx, tie_matrix())
add_judge(ctx, "a2", 1, {o: 0 for o in FIELD if o != "a2"}, suffix="_dup",
          finished="2026-06-01T00:00:00")
agg = np.aggregate_round(ctx, 2, FIELD)
check("A1 a superseded judge sheet does not poison the panel",
      agg["stats"]["a2"]["n"] == agg["stats"]["a2"]["expected_n"]
      and agg["stats"]["a2"]["complete"] is True,
      f"n={agg['stats']['a2']['n']} expected={agg['stats']['a2']['expected_n']} "
      f"complete={agg['stats']['a2']['complete']}")
check("A1 the superseded sheet is reported",
      len(agg["diagnostics"].get("superseded_sheets") or []) == 1,
      str(agg["diagnostics"].get("superseded_sheets")))
sel = np.select_champion(ctx, 2, agg)
check("A1 the round is decidable (the champion is not the no-progress fallback)",
      sel["champion"] != "a1"
      and {"w1", "a2", "i1", "i2", "i3"} <= set(sel["eligible"]),
      f"champion={sel['champion']} eligible={sel['eligible']}")
shutil.rmtree(tmp, ignore_errors=True)

tmp = Path(tempfile.mkdtemp(prefix="paper_grade_a2_"))
ctx = make_ctx(tmp, judges=1)
full_panel(ctx, tie_matrix())
add_judge(ctx, "w1", 2, {o: 0 for o in FIELD if o != "w1"})       # stale --judges=2 ghost
agg = np.aggregate_round(ctx, 2, FIELD)
check("A2 a judge index outside the configured range is ignored, not counted",
      all(agg["stats"][v]["complete"] for v in FIELD)
      and "w1" in ((agg["diagnostics"].get("out_of_range_sheets") or [""])[0] or ""),
      f"out_of_range={agg['diagnostics'].get('out_of_range_sheets')}")
shutil.rmtree(tmp, ignore_errors=True)

# =====================================================================
# B. tie-breaks
# =====================================================================
tmp = Path(tempfile.mkdtemp(prefix="paper_grade_b1_"))
ctx = make_ctx(tmp)
full_panel(ctx, tie_matrix())
agg = np.aggregate_round(ctx, 2, FIELD)
tied = {v: (agg["stats"][v]["median"], agg["stats"][v]["mean"], agg["stats"][v]["iqr"])
        for v in ("w1", "a2", "i1", "i2", "i3")}
check("B1 the fixture really is an exact five-way tie",
      len(set(tied.values())) == 1,
      str(tied))
sel = np.select_champion(ctx, 2, agg)
check("B1 an exact tie is decided by the CONTENT DIGEST, not by the arm's name",
      sel["champion"] == "w1",
      f"champion={sel['champion']} (id order would pick a2) "
      f"ranking={[r['id'] for r in sel['ranking']]}")
check("B1 the trace documents the provenance-free tie-break",
      any("digest" in ln and "NAME never decides" in ln for ln in sel["trace"]),
      str([ln for ln in sel["trace"] if "ranking key" in ln])[:160])
shutil.rmtree(tmp, ignore_errors=True)

# =====================================================================
# B2. the category-2 writing tie-break (severity > style > digest)
# =====================================================================
tmp = Path(tempfile.mkdtemp(prefix="paper_grade_b2_"))
ctx = make_ctx(tmp, summaries={"w1": {"writing_remaining": 2},
                               "a2": {"writing_remaining": 0},
                               "i1": {"writing_remaining": 1},
                               "i2": {"writing_remaining": 1},
                               "i3": {"writing_remaining": 3}})
full_panel(ctx, tie_matrix())
agg = np.aggregate_round(ctx, 2, FIELD)
sel = np.select_champion(ctx, 2, agg)
check("B2 an exact statistical tie is broken by writing_remaining, not the digest",
      sel["champion"] == "a2",
      f"champion={sel['champion']} ranking={[(r['id'], r['writing_remaining']) for r in sel['ranking']]}")
check("B2 the trace names the writing key in the ranking order",
      any("writing_remaining" in ln and "ranking key" in ln for ln in sel["trace"]),
      str([ln for ln in sel["trace"] if "ranking key" in ln])[:200])

# a nonsensical (negative) or absent count is the +inf sentinel: it never wins
ctx2 = make_ctx(tmp, summaries={"w1": {"writing_remaining": -5},
                                "a2": {"writing_remaining": 0},
                                "i1": {"writing_remaining": None},
                                "i2": {"writing_remaining": 0}})
full_panel(ctx2, tie_matrix())
sel2 = np.select_champion(ctx2, 2, np.aggregate_round(ctx2, 2, FIELD))
check("B2 a negative/absent writing count never wins a tie",
      sel2["champion"] in ("a2", "i2")
      and all(r["writing_remaining"] == np.MISSING_TIEBREAK
              for r in sel2["ranking"] if r["id"] == "w1"),
      f"champion={sel2['champion']} "
      f"w1={[r['writing_remaining'] for r in sel2['ranking'] if r['id'] == 'w1']}")

# the incumbent-retention rule stays strictly statistical: a challenger with a
# BETTER writing count cannot dethrone a base the panel cannot distinguish
ctx3 = make_ctx(tmp, summaries={"w1": {"writing_remaining": 0},
                                "a2": {"writing_remaining": 0}})
full_panel(ctx3, {})
sel3 = np.select_champion(ctx3, 2, np.aggregate_round(ctx3, 2, FIELD))
check("B2 a writing count never dethrones the incumbent on an exact statistical tie",
      sel3["champion_rep"] == "r1_a2"
      and any("incumbent base is retained" in ln for ln in sel3["trace"]),
      f"champion={sel3['champion']} rep={sel3['champion_rep']}")

# the frozen-review cross-check source: category 2 only
sb = tmp / "runs" / np.rid_for_fresh(2, "a2")
(sb / "review").mkdir(parents=True, exist_ok=True)
(sb / "review" / "findings.json").write_text(json.dumps({
    "findings": [{"id": "F-001", "category": 2, "severity": "Minor"},
                 {"id": "F-002", "category": "2", "severity": "Minor"},
                 {"id": "F-003", "category": 1, "severity": "Critical"}]}),
    encoding="utf-8")
rec = ctx3.run(np.rid_for_fresh(2, "a2"))
check("B2 writing_findings_input counts the frozen review's category-2 findings",
      np.writing_findings_input(ctx3, rec) == 2, str(np.writing_findings_input(ctx3, rec)))
check("B2 critical_findings_input still counts only Critical severity",
      np.critical_findings_input(ctx3, rec) == 1, str(np.critical_findings_input(ctx3, rec)))
shutil.rmtree(tmp, ignore_errors=True)

# =====================================================================
# C. the graded basis (judge contract v2)
# =====================================================================
CONTRACT = getattr(np, "JUDGE_CONTRACT_VERSION", 2)
basis_problems = getattr(np, "judge_basis_problems",
                         lambda c, w, strict: ([], []))
rec2 = {"id": "r2_judge_tX_j1", "round": 2, "target_id": "a2", "judge_index": 1,
        "label_map": {"v1": "orig", "v2": "w1"}, "contract": CONTRACT}
rec_legacy = {k: v for k, v in rec2.items() if k != "contract"}
FULL = [{"opponent_label": "v1", "score": 1, "reason": "target is better",
         "basis": "consistency",
         "resolved": [{"check": "M8", "tier": "consistency", "severity": "minor",
                       "evidence": "Fig. 2: metric count now consistent"}],
         "introduced": [],
         "checks": {c: "clean -- unit fixture" for c in np.JUDGE_COVERAGE_CHECKS}},
        {"opponent_label": "v2", "score": 0, "reason": "no net difference",
         "basis": "none", "resolved": [], "introduced": [],
         "checks": {c: "clean -- unit fixture" for c in np.JUDGE_COVERAGE_CHECKS}}]
sheet = {"run_id": rec2["id"], "target_id": "a2", "round": 2, "judge_index": 1,
         "comparisons": FULL}
errs, warns = np.validate_judge_sheet(sheet, rec2)
check("C1 a well-formed graded sheet passes the strict contract",
      not errs, f"errs={errs[:1]}")

no_basis = {"run_id": rec2["id"], "target_id": "a2", "round": 2, "judge_index": 1,
            "comparisons": [{"opponent_label": "v1", "score": 1, "reason": "better"},
                            FULL[1]]}
errs2, _ = np.validate_judge_sheet(no_basis, rec2)
check("C2 a contract-v2 sheet without a basis/ledger fails its run",
      bool(errs2) and any("basis" in e for e in errs2), f"errs={errs2[:2]}")
errs3, warns3 = np.validate_judge_sheet(no_basis, rec_legacy)
check("C3 the SAME sheet from a legacy sandbox is accepted with an UNCALIBRATED warning "
      "(never a silent mix)",
      not errs3 and any("UNCALIBRATED" in w for w in warns3),
      f"errs={errs3[:1]} warns={warns3[:1]}")
check("C4 an unledgered score never counts as a complete sheet under contract v2",
      np.judge_sheet_complete(no_basis, rec2) is False
      and np.judge_sheet_complete(no_basis, rec_legacy) is True)

def comp(score, basis="consistency", resolved=None, introduced=None):
    return {"opponent_label": "v1", "score": score, "reason": "unit",
            "basis": basis, "resolved": resolved if resolved is not None else [],
            "introduced": introduced if introduced is not None else [],
            "checks": {c: "clean -- unit fixture" for c in np.JUDGE_COVERAGE_CHECKS}}


MAJOR = [{"tier": "consistency", "severity": "major", "evidence": "metric count conflict"}]
MINOR_CONS = [{"tier": "consistency", "severity": "minor", "evidence": "one more instance"}]
MAJOR3 = MAJOR + MINOR_CONS
MINOR_FMT = [{"tier": "formatting", "severity": "minor", "evidence": "7.5pt vs 8pt period"}]
CRIT = [{"tier": "correctness", "severity": "critical", "evidence": "wrong DOI in ref 12"}]
rules = [
    ("+3 on a minor formatting item is rejected", comp(3, "formatting", MINOR_FMT, []), True),
    ("+3 on a major + minor consistency item is accepted", comp(3, "consistency", MAJOR3, []),
     False),
    ("+4 without a critical item is rejected", comp(4, "consistency", MAJOR, []), True),
    ("+4 with a critical + minor item is accepted",
     comp(4, "correctness", CRIT + MINOR_CONS, []), False),
    ("+1 with an empty ledger is rejected", comp(1, "consistency", [], []), True),
    ("0 with an empty ledger is accepted", comp(0, "none", [], []), False),
    ("-2 with an introduced item is accepted", comp(-2, "consistency", [], MAJOR), False),
    ("a malformed item is rejected",
     comp(2, "consistency", [{"tier": "nonsense", "severity": "major", "evidence": "x"}], []),
     True),
]
for label, c, want_err in rules:
    e, _w = basis_problems(c, "comparisons[0]", strict=True)
    check(f"C5 {label}", bool(e) is want_err, f"errs={[x[:90] for x in e[:1]]}")
low_basis = comp(2, "formatting", MAJOR, [])
_e, w = basis_problems(low_basis, "comparisons[0]", strict=True)
check("C6 a basis that understates its own ledger is reported",
      any("highest-priority tier" in x for x in w), str(w[:1]))

# the stubs that drive the end-to-end suites must satisfy the strict contract
sa_spec = importlib.util.spec_from_file_location(
    "stub_agent_mod", Path(__file__).resolve().parent / "stub_agent.py")
sa = importlib.util.module_from_spec(sa_spec)
sys.modules["stub_agent_mod"] = sa
sa_spec.loader.exec_module(sa)
stub_sheet = {"run_id": rec2["id"], "target_id": "a2", "round": 2, "judge_index": 1,
              "comparisons": [
                  {"opponent_label": "v1", "score": 1, "reason": "stub",
                   "checks": sa.stub_checks(1), **sa.stub_basis(1)},
                  {"opponent_label": "v2", "score": -1, "reason": "stub",
                   "checks": sa.stub_checks(-1), **sa.stub_basis(-1)}]}
serrs, _sw = np.validate_judge_sheet(stub_sheet, rec2)
check("C7 the end-to-end stubs emit contract-v3-valid sheets",
      not serrs, f"errs={serrs[:1]}")

# =====================================================================
# D. reporting, score model, prompt
# =====================================================================
tmp = Path(tempfile.mkdtemp(prefix="paper_grade_d1_"))
ctx = make_ctx(tmp)
full_panel(ctx, tie_matrix())
agg = np.aggregate_round(ctx, 2, FIELD)
pq = agg["diagnostics"]["panel_quality"]
check("D1 panel calibration is reported (histogram, basis counts, sheet counts)",
      pq.get("calibrated_sheets") == 7 and pq.get("uncalibrated_sheets") == 0
      and (pq.get("basis_counts") or {}).get("consistency") == 10
      and (pq.get("basis_counts") or {}).get("none") == 32 and pq.get("score_histogram")
      and pq.get("max_abs_score") == 1,
      f"cal={pq.get('calibrated_sheets')} uncal={pq.get('uncalibrated_sheets')} "
      f"basis={pq.get('basis_counts')} hist={pq.get('score_histogram')}")
# D1b: the calibration flag must require EVERY comparison to carry a basis, not
# just the last one (the old loop overwrote the flag per comparison).
tmp1b = Path(tempfile.mkdtemp(prefix="paper_grade_d1b_"))
ctx1b = make_ctx(tmp1b)
full_panel(ctx1b, tie_matrix())
_rec1b = ctx1b.state["runs"][np.rid_judge(2, np.judge_target_token(2, "w1"), 1)]
for _k in ("basis", "resolved", "introduced"):
    _rec1b["scores"]["comparisons"][0].pop(_k, None)     # basis only on the LAST one
pq1b = np.aggregate_round(ctx1b, 2, FIELD)["diagnostics"]["panel_quality"]
check("D1b a basis only on the LAST comparison is not a calibrated sheet",
      pq1b.get("uncalibrated_sheets") == 1 and pq1b.get("calibrated_sheets") == 6,
      f"cal={pq1b.get('calibrated_sheets')} uncal={pq1b.get('uncalibrated_sheets')}")

# D1c: a sign conflict (score +1 with no resolved item) must be reported.
tmp1c = Path(tempfile.mkdtemp(prefix="paper_grade_d1c_"))
ctx1c = make_ctx(tmp1c)
full_panel(ctx1c, tie_matrix())
_rec1c = ctx1c.state["runs"][np.rid_judge(2, np.judge_target_token(2, "w1"), 1)]
_rec1c["scores"]["comparisons"][0].update(
    {"score": 1, "basis": "consistency", "resolved": [], "introduced": []})
pq1c = np.aggregate_round(ctx1c, 2, FIELD)["diagnostics"]["panel_quality"]
check("D1 a ledger contradiction is reported, not averaged away",
      len(pq1c.get("ledger_sign_conflicts") or []) == 1
      and "score +1 with resolved=0" in pq1c["ledger_sign_conflicts"][0],
      str(pq1c.get("ledger_sign_conflicts")))
tmp2 = Path(tempfile.mkdtemp(prefix="paper_grade_d2_"))
ctx2 = make_ctx(tmp2)
for vid in FIELD:
    others = [w for w in FIELD if w != vid]
    labels = [f"v{i+1}" for i in range(len(others))]
    tok = np.judge_target_token(2, vid)
    rid = np.rid_judge(2, tok, 1)
    comps = [{"opponent_label": lab, "score": 1, "reason": "x"}      # no ledger at all
             for lab in labels]
    ctx2.state["runs"][rid] = {"id": rid, "kind": "judge", "round": 2, "status": "done",
                              "target_id": vid, "judge_index": 1,
                              "label_map": dict(zip(labels, others)),
                              "finished": "2026-01-01T00:00:01", "sandbox": f"runs/{rid}",
                              "scores": {"run_id": rid, "round": 2, "target_id": vid,
                                         "judge_index": 1, "comparisons": comps}}
agg2 = np.aggregate_round(ctx2, 2, FIELD)
pq2 = agg2["diagnostics"]["panel_quality"]
check("D2 uncalibrated sheets and ledger contradictions are counted",
      pq2.get("uncalibrated_sheets") == 7
      and len(pq2.get("ledger_sign_conflicts") or []) == 42,
      f"uncal={pq2.get('uncalibrated_sheets')} "
      f"conflicts={len(pq2.get('ledger_sign_conflicts') or [])}")
shutil.rmtree(tmp2, ignore_errors=True)

csvp = np.write_raw_scores(ctx, [{"round": 2}])
csv_text = csvp.read_text(encoding="utf-8")
check("D3 raw_scores.csv carries the graded basis and the ledger",
      "basis" in csv_text.splitlines()[0] and "resolved" in csv_text.splitlines()[0]
      and "introduced" in csv_text.splitlines()[0]
      and "consistency/minor" in csv_text,
      csv_text.splitlines()[0][:120])
shutil.rmtree(tmp, ignore_errors=True)

sm = (getattr(np, "score_model_doc", lambda: {})() or {})
check("D4 the score model documents the contract, the rules and the tie-breaks",
      sm.get("judge_contract") == CONTRACT
      and sm.get("tiebreaks") == ["-median", "-mean", "IQR", "critical_remaining",
                                  "writing_remaining", "digest", "id"]
      and sm.get("scale") == [np.SCORE_MIN, np.SCORE_MAX]
      and any("CRITICAL" in r for r in (sm.get("graded_basis") or {}).get("rules") or [])
      and "unused rungs" in sm.get("scale_note", ""),
      str(sm.get("tiebreaks")))

prompt = np.judge_prompt(Path("/tmp/x"), "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1", "v2"])
checks = [
    ("the graded-basis section is in the prompt", "GRADED BASIS" in prompt),
    ("the schema lists basis/resolved/introduced",
     all(k in prompt for k in ('"basis"', '"resolved"', '"introduced"'))),
    ("the scale is documented as fixed", "FIXED" in prompt and "schema error" in prompt),
    ("the reason must be written in the target's frame", "TARGET's frame" in prompt),
    ("the arithmetic rules are spelled out",
     "|score| >= 3" in prompt and "|score| = 4" in prompt),
    # The writing tie-break is a PRODUCING-session self-report: the judge must
    # never be asked for it (blinding -- it would learn a provenance-flavoured
    # quality channel and could optimise for it).
    ("the judge prompt carries no writing_remaining field",
     "writing_remaining" not in prompt),
]
for label, ok in checks:
    check(f"D5 {label}", ok)

stage_prompts = {
    "rewrite": np.rewrite_prompt(Path("/tmp/x"), "r1_w1", 1),
    "revise": np.revise_prompt(Path("/tmp/x"), "r1_a2_revise", 1),
    "integrate": np.integrate_prompt(Path("/tmp/x"), "r1_i1", 1, "a1", ["w1"]),
    "review": np.review_prompt(Path("/tmp/x"), "r1_review", 1),
}
for name in ("rewrite", "revise", "integrate"):
    flat = " ".join(stage_prompts[name].split())
    check(f"D5 the {name} prompt asks for writing_remaining "
          f"(tie-break only, below the critical count)",
          '"writing_remaining"' in flat
          and "tie" in flat.lower()
          and "never as a score or a gate" in flat)
check("D5 the review prompt is not asked for a writing_remaining field",
      "writing_remaining" not in stage_prompts["review"])

# Every EDITING stage must validate what it produced, with a bounded loop, and
# the orchestrator re-runs the session when the package it produced is invalid.
for name in ("rewrite", "revise", "integrate"):
    flat = " ".join(stage_prompts[name].split())
    check(f"D5 the {name} prompt carries the post-edit validation rule",
          "VALIDATION AFTER EDITING" in flat
          and "paper_docx_format.py validate" in flat
          and "at most THREE times" in flat
          and "NEVER \"fix\" a validation error by deleting content" in flat,
          flat[flat.find("VALIDATION AFTER EDITING"):][:120])
# 2026-09-22: validation is a SHARED rule -- a review or a comparison session can
# be handed a package that does not even parse, so it gets the same duty. The
# comparison session's copy differs ONLY by the bookkeeping file it must not learn.
check("D5 the review prompt carries the shared validation rule",
      np.validation_block("review") in stage_prompts["review"])
judge_prompt_text = np.judge_prompt(Path("/tmp/x"), "judge_t1_j1", 1, "t1", 1, 3, ["v1"])
check("D5 the judge prompt carries the validation rule in its provenance-neutral variant",
      np.validation_block("judge") in judge_prompt_text
      and "VALIDATION AFTER EDITING" in judge_prompt_text
      and "MANUAL_STEPS" not in judge_prompt_text)

# =====================================================================
# E. the rubric's own wording vs the enforced arithmetic (2026-09-30 audit)
#
# Two independent write-ups of this rubric claimed the docs disagree with the
# code and the anchors disagree with the derivation. Re-checked here against
# the tree: the class vocabulary is SIX tiers (BASIS_TIERS) but five of the
# places that state it stopped at `formatting`; the judge prompt's +4/+3
# anchors read as if one critical / one major row reached those rungs while the
# enforced derivation gives +3 / +2; the writing rubric offered no rule for a
# Q1-Q3 row whose evidence shows the meaning changed (the class rule files it
# as `correctness`); and the basis check skipped `none`, so a sheet with ledger
# items could carry the value the prompt reserves for a clean 0.
# =====================================================================
order6 = " > ".join(np.BASIS_TIERS)
five_only = re.compile(r"correctness\s*>\s*consistency\s*>\s*preservation\s*>\s*completeness"
                       r"\s*>\s*formatting(?!\s*>\s*writing)")
doc_sources = {
    "README.md": (WS / "README.md").read_text(encoding="utf-8"),
    "sweeps.md": (WS / "paper-skills/paper-review/references/sweeps.md").read_text(
        encoding="utf-8"),
    "ledger.md": (WS / "paper-skills/paper-revise/references/ledger.md").read_text(
        encoding="utf-8"),
    "paper_pipeline.py": (WS / "paper_pipeline.py").read_text(encoding="utf-8"),
}
for name, text in doc_sources.items():
    flat = " ".join(text.split())
    check(f"E1 {name} states the full six-tier class order", order6 in flat, "")
    check(f"E1 {name} never states the five-tier order",
          not five_only.search(text), "")
sweeps_text = doc_sources["sweeps.md"]
row2 = next((l for l in sweeps_text.splitlines() if l.startswith("| 2 ")), "")
check("E1 sweeps.md's category-2 mapping row carries `writing`",
      "`writing`" in row2, row2[:120])
readme_row2 = next((l for l in doc_sources["README.md"].splitlines()
                    if l.startswith("| 2 ")), "")
check("E1 README.md's category-2 mapping row carries `writing`",
      "`writing`" in readme_row2, readme_row2[:120])
rule_text = np.defect_class_rule()
check("E1 the defect-class prompt's class count matches BASIS_TIERS",
      f"{len(np.BASIS_TIERS)} scored classes" in rule_text
      and "Five classes" not in rule_text,
      rule_text[:90])

# E2: the anchors must not promise a rung the derived integer cannot reach.
judge_flat = " ".join(judge_prompt_text.split())
check("E2 the +4 anchor states the capped-sum requirement",
      "the capped sum" in judge_flat and "a single critical row derives +3" in judge_flat)
check("E2 the +3 anchor states the capped-sum requirement",
      "a single major row derives +2" in judge_flat)
for score, rowset, want_err, label in (
        (4, CRIT, True, "one critical row with +4 is rejected"),
        (3, CRIT, False, "one critical row with +3 is accepted"),
        (3, MAJOR, True, "one major row with +3 is rejected"),
        (2, MAJOR, False, "one major row with +2 is accepted")):
    e, _w = basis_problems(comp(score, "correctness", rowset, []), "comparisons[0]", strict=True)
    check(f"E2 {label}", bool(e) is want_err, str(e[:1]))

# E3: the writing rubric must refile a meaning-changing row as `correctness`.
check("E3 the writing rubric carries the refile rule for meaning-changing rows",
      "REFILE RULE" in judge_flat
      and "belongs to the `correctness` tier" in judge_flat)

# E4: `basis: none` is reserved for a clean 0 with no item on either side.
net_zero_none = comp(0, "none", MINOR_CONS, MINOR_CONS)
_e, w_none = basis_problems(net_zero_none, "comparisons[0]", strict=True)
check("E4 a net-zero sheet with items and basis 'none' is reported",
      any("'none'" in x for x in w_none), str(w_none[:1]))
net_zero_tier = comp(0, "consistency", MINOR_CONS, MINOR_CONS)
_e2, w_tier = basis_problems(net_zero_tier, "comparisons[0]", strict=True)
check("E4 the same sheet with a tier basis stays clean", not w_tier, str(w_tier[:1]))
_e3, w_empty = basis_problems(comp(0, "none", [], []), "comparisons[0]", strict=True)
check("E4 basis 'none' with empty lists stays clean", not w_empty, str(w_empty[:1]))

# =====================================================================
# F. judge-contract second pass (2026-09-30 audit round 2): severity as a
#    distance rung in EVERY class, artifact damage scored where it damages,
#    the basis on the sign's side, the speculative-AI non-decisiveness rule,
#    reasoned `unable` coverage, and the cross-arm tie-break cross-check.
# =====================================================================
judge_flat2 = " ".join(judge_prompt_text.split())


def grow(tier, sev, check_id="M8", ev="Fig. 2 legend: five vs six metrics"):
    return {"check": check_id, "tier": tier, "severity": sev, "evidence": ev}


def gcomp(score, basis, resolved=(), introduced=(), checks=None):
    c = {"opponent_label": "v1", "score": score, "reason": "unit", "basis": basis,
         "resolved": list(resolved), "introduced": list(introduced)}
    if checks is not None:
        c["checks"] = checks
    return c


# F1: severity is a distance from correct in every class, not a factual-only scale.
check("F1 the judge prompt states the distance ladder for every class",
      "Severity is shared too, and it is a DISTANCE FROM CORRECT" in judge_flat2
      and "MINOR = a detail" in judge_flat2
      and "MAJOR = the error changes a reported fact" in judge_flat2
      and "CRITICAL = the error changes a conclusion" in judge_flat2)
check("F1 the judge prompt states the same-rung distance rule",
      "scored by the DISTANCE between the two errors" in judge_flat2)
check("F1 the judge prompt scores artifact damage where it damages",
      "FORMATTING IS GRADED BY WHAT IT DAMAGES" in judge_flat2
      and "content missing from the delivered artifact" in judge_flat2)
check("F1 the blank-page ladder is stated for the judge",
      "one displaced page/figure = MINOR" in judge_flat2
      and "several pages or a whole section/figure = MAJOR" in judge_flat2)
check("F1 the shared class rule carries the artifact-damage classification",
      "ARTIFACT DAMAGE IS NOT COSMETIC FORMATTING" in np.defect_class_rule())
check("F1 'a factual error is not automatically Critical' is stated",
      "does NOT make every\n    rung CRITICAL" in np.defect_class_rule())

# F2: the basis names the tier on the SIGN's side; a losing-tier basis is reported.
mix = gcomp(1, "correctness",
            resolved=[grow("consistency", "minor"), grow("consistency", "minor")],
            introduced=[grow("correctness", "minor", "M4",
                             "abstract: n = 12, shipped table has 3 rows")])
_e, w_basis = basis_problems(mix, "comparisons[0]", strict=True)
check("F2 a basis that names the losing tier is reported",
      any("highest-priority tier" in x and "'consistency'" in x for x in w_basis),
      str(w_basis[:1])[:160])
_e2, w_basis2 = basis_problems(dict(mix, basis="consistency"), "comparisons[0]", strict=True)
check("F2 the same sheet with the sign-side basis stays clean", not w_basis2, str(w_basis2[:1]))
check("F2 the judge prompt defines the basis as the sign-side tier",
      "the tier that BACKS THE SIGN" in judge_flat2
      and "never a tier the integer did not win on" in judge_flat2)

# F3: a speculative-AI row can never decide a comparison on its own.
ai_minor = grow("correctness", "minor", "J4",
                "possible AI-generated stylistic patterns in the discussion")
e_ai, _w_ai = basis_problems(gcomp(1, "correctness", [ai_minor]), "c0", True)
check("F3 a score backed only by a speculative-AI row is rejected",
      any("speculative AI-content" in x for x in e_ai), str(e_ai[:1])[:160])
ai_crit = grow("correctness", "critical", "J4", "possible AI-generated text in the Methods")
e_ai2, _w = basis_problems(gcomp(3, "correctness", [ai_crit]), "c0", True)
check("F3 a 'clearly better' rung cannot rest on a speculative-AI row",
      any("rests only on speculative AI-content" in x for x in e_ai2), str(e_ai2)[:160])
e_ai3, _w = basis_problems(gcomp(4, "correctness", [ai_crit, MINOR_CONS[0]]), "c0", True)
check("F3 the decisive rung needs a non-AI CRITICAL row",
      any("decisive rung needs a CRITICAL item that is not" in x for x in e_ai3),
      str(e_ai3)[:160])
plag = grow("correctness", "critical", "J4",
            "verbatim duplication of a published figure legend")
e_plag, _w = basis_problems(gcomp(4, "correctness", [plag, MINOR_CONS[0]]), "c0", True)
check("F3 a confirmed plagiarism/policy row (no 'possible AI' label) is not restricted",
      not e_plag, str(e_plag[:1]))
e_ai4, _w = basis_problems(gcomp(3, "correctness",
                                 [grow("correctness", "major", "J4", "possible AI patterns"),
                                  grow("consistency", "major")]), "c0", True)
check("F3 a speculative-AI row may contribute beside a non-AI strong row",
      not e_ai4, str(e_ai4[:1]))
check("F3 the judge prompt requires the literal 'possible AI' prefix and the rule",
      "BEGIN its evidence with the literal words `possible AI`" in judge_flat2
      and "A non-zero score therefore needs at least one item on its side that is not such a row"
      in judge_flat2)

# F4: `unable` coverage must say why, and an all-`unable` map is a non-judgment.
clean_checks = {c: "clean -- unit fixture" for c in np.JUDGE_COVERAGE_CHECKS}
bare = dict(clean_checks)
bare["M8"] = "unable"
e_cov, _w_cov = np.judge_coverage_problems(gcomp(0, "none", checks=bare), "c0", True)
check("F4 a bare `unable` with no reason is rejected",
      any("states no reason" in x for x in e_cov), str(e_cov[:1])[:160])
reasoned = dict(clean_checks)
reasoned["M8"] = "unable -- the figure is image-only"
e_cov2, _w_cov2 = np.judge_coverage_problems(gcomp(0, "none", checks=reasoned), "c0", True)
check("F4 a reasoned `unable` passes", not e_cov2, str(e_cov2[:1])[:160])
all_unable = {c: "unable -- the corpus is image-only" for c in np.JUDGE_COVERAGE_CHECKS}
e_cov3, w_cov3 = np.judge_coverage_problems(gcomp(0, "none", checks=all_unable), "c0", True)
check("F4 an all-`unable` map is reported as a non-judgment",
      not e_cov3 and any("judged nothing" in x for x in w_cov3), str(w_cov3[:1])[:160])

# F5: the review-path classes with no coverage row get a scoring bridge.
check("F5 the judge prompt bridges M25-M29/J5 into the frozen ids",
      "M25-M29" in judge_flat2 and "cite the closest frozen id" in judge_flat2
      and "J5 (architecture/organization)" in judge_flat2)
check("F5 the J1 routing rule is stated",
      "has no tier of its own" in judge_flat2 and "J1's coverage row" in judge_flat2)
check("F5 the shared-ceiling note is stated",
      "Consistency and preservation share the same" in judge_flat2)

# F6: the distance ladders the user's examples imply.
check("F6 'man' is a MAJOR and 'fish' a CRITICAL correctness row",
      np.derived_comparison_score(gcomp(2, "correctness",
                                        [grow("correctness", "major")])) == 2
      and np.derived_comparison_score(gcomp(3, "correctness",
                                            [grow("correctness", "critical")])) == 3)
check("F6 the fish->man swap is the distance (+1), not 0",
      np.derived_comparison_score(gcomp(1, "correctness",
                                        [grow("correctness", "critical")],
                                        [grow("correctness", "major")])) == 1)
check("F6 the blank-page ladder is representable and strictly ordered",
      np.derived_comparison_score(gcomp(2, "completeness",
                                        [grow("completeness", "major", "M20")])) == 2
      and np.derived_comparison_score(gcomp(1, "completeness",
                                            [grow("completeness", "minor", "M20")])) == 1
      and np.derived_comparison_score(gcomp(0, "none")) == 0)
check("F6 a one-off stray empty line is cosmetic (0), not a page-sized defect",
      "is COSMETIC (0)" in judge_flat2 and "A blank LINE is not a blank PAGE" in judge_flat2)
check("F6 cosmetic formatting stays MINOR-only (+-1) and cannot be decisive",
      bool(basis_problems(gcomp(2, "formatting", [grow("formatting", "major")]),
                          "c0", True)[0]))

# F7: the self-reported tie-break counts are cross-checked for every arm, not
# only for the revise arm that happens to carry a review/ copy.
root_ctx = Path(tempfile.mkdtemp(prefix="paper_tiebreak_")) / "root"
ctx_tb = np.Ctx(root_ctx)
ctx_tb.cfg = {"audit": "off"}
rev_sb = root_ctx / "runs" / "r1_review"
(rev_sb / "review").mkdir(parents=True)
(rev_sb / "review" / "findings.json").write_text(json.dumps({"findings": [
    {"id": "F-001", "check": "M4", "category": 0, "severity": "Critical"},
    {"id": "F-002", "check": "M8", "category": 2, "severity": "Minor"}]}),
    encoding="utf-8")
rew_sb = root_ctx / "runs" / "r1_w1"
rew_sb.mkdir(parents=True)
ctx_tb.state = {"runs": {
    "r1_review": {"id": "r1_review", "kind": "review", "round": 1, "status": "done",
                  "sandbox": "runs/r1_review"},
    "r1_w1": {"id": "r1_w1", "kind": "rewrite", "round": 1,
              "sandbox": "runs/r1_w1"}},
    "rounds": {"1": {}}, "pinned": [], "log": []}
rec_tb = {"id": "r1_w1", "kind": "rewrite", "round": 1, "sandbox": "runs/r1_w1"}
check("F7 the round's frozen review is found for an arm without a review/ copy",
      np.critical_findings_input(ctx_tb, rec_tb) == 1
      and np.writing_findings_input(ctx_tb, rec_tb) == 1)
warns_tb = []
np.tiebreak_selfreport_warnings(ctx_tb, rec_tb,
                                {"critical_remaining": 0, "writing_remaining": 0}, warns_tb)
check("F7 a zero claim is cross-checked for a rewrite arm too",
      sum("critical_remaining=0" in w for w in warns_tb) == 1
      and sum("writing_remaining=0" in w for w in warns_tb) == 1, str(warns_tb)[:200])

# F8: the README matches the code's auditor default.
readme_text = (WS / "README.md").read_text(encoding="utf-8")
check("F8 the README states the auditor default the code records",
      np.DEFAULT_AUDIT == "on" and "on by default" in readme_text
      and "off by default" not in readme_text)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
    sys.exit(1)
print("ALL GRADING-SCHEME CHECKS PASSED")

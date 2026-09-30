#!/usr/bin/env python3
"""The reported ISSUE CENSUS: issues per version, tier and severity.

The operator's improvement metric over many rounds and many runs is "how many
issues of each tier does each version still carry, and who found them". The
judges' own ledger rows answer that (`introduced` rows name the target's
defects, `resolved` rows name the opponent's), so the census is pure CODE-side
counting of the sheets the panel already produced:

  * `own`  -- a version's own sessions (it was their sweep target);
  * `peer` -- the other versions' sessions (it was their comparison opponent);
  * deduplicated per (session, version, tier, severity, check, evidence), so one
    defect a judge repeats in every opponent comparison counts once;
  * normalized by the sessions that could have mentioned the version, so the
    number is comparable across rounds, fields and runs.

This suite also pins the two strategy fixes that make the census trustworthy:
the DIRECTION-FLIP diagnostic (both sides claiming the same side is better) and
the rule that the census is REPORTED, never a ranking input.

Run:  python3 .paper_test/test_issue_census.py
"""
from __future__ import annotations

import csv
import importlib.util
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


FIELD = ["orig", "r1_a2", "w1"]


def row(tier, sev, ev, check_id):
    return {"check": check_id, "tier": tier, "severity": sev, "evidence": ev}


def comp(label, score, resolved=(), introduced=()):
    return {"opponent_label": label, "score": score, "basis": "none",
            "reason": "unit fixture", "resolved": list(resolved),
            "introduced": list(introduced),
            "checks": {c: "clean -- unit fixture" for c in np.JUDGE_COVERAGE_CHECKS}}


# One round-2 field of three versions (base pin r1_a2), one judge session each,
# with hand-written ledgers exercising every attribution rule:
#
#   A (target orig)   vs r1_a2: -2   vs w1:  +2
#   B (target r1_a2)  vs orig:  +2   vs w1:  +2
#   C (target w1)     vs orig:  +2   vs r1_a2: 0
#
# so (orig, r1_a2) is a CONSISTENT pair (opposite own signs) and (orig, w1) is a
# real direction flip (both sides claim to be better).
DEFECT_ORIG = row("correctness", "major", "abstract: n = 12 vs shipped table 13", "M4")
DEFECT_R1 = row("correctness", "minor", "Methods: unit written as uM, table uses uM/mL", "M8")
FMT_R1 = row("consistency", "minor", "Fig. 2 legend: units differ from panel labels", "M20")
SHEETS = {
    "sess_a": {"target": "orig", "label_map": {"v1": "r1_a2", "v2": "w1"}, "comps": [
        comp("v1", -2, resolved=[FMT_R1], introduced=[DEFECT_ORIG]),
        # the SAME orig defect is repeated in this session's second comparison --
        # it must count once for orig, not once per opponent.
        comp("v2", 2, introduced=[DEFECT_ORIG,
                                  row("formatting", "minor", "the DOI line wraps oddly", "M20")])]},
    "sess_b": {"target": "r1_a2", "label_map": {"v1": "orig", "v2": "w1"}, "comps": [
        comp("v1", 2, resolved=[DEFECT_ORIG], introduced=[DEFECT_R1]),
        comp("v2", 2, introduced=[DEFECT_R1,
                                  row("completeness", "critical", "Fig. 3 absent from the PDF", "M3")])]},
    "sess_c": {"target": "w1", "label_map": {"v1": "orig", "v2": "r1_a2"}, "comps": [
        comp("v1", 2, resolved=[DEFECT_ORIG],
             introduced=[row("completeness", "minor", "panel C legend missing", "M3")]),
        comp("v2", 0, resolved=[FMT_R1], introduced=[
            row("completeness", "minor", "panel C legend missing", "M3")])]},
}


def make_ctx(tmp: Path):
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
    for n, (sid, sheet) in enumerate(SHEETS.items(), start=1):
        tok = np.judge_target_token(2, sheet["target"])
        rid = np.rid_judge(2, tok, 1)
        ctx.state["runs"][rid] = {
            "id": rid, "kind": "judge", "round": 2, "status": "done",
            "target_id": sheet["target"], "judge_index": 1,
            "label_map": sheet["label_map"], "attempts": 1, "sandbox": f"runs/{rid}",
            "finished": f"2026-01-01T00:00:0{n}",
            "contract": np.JUDGE_CONTRACT_VERSION,
            "scores": {"run_id": rid, "target_id": sheet["target"], "judge_index": 1,
                       "comparisons": sheet["comps"]}}
    (tmp / "reports").mkdir(parents=True, exist_ok=True)
    return ctx


def test_census_attribution():
    print("== the census: own/peer attribution, per-session dedup, tier x severity ==")
    tmp = Path(tempfile.mkdtemp(prefix="paper_census_"))
    ctx = make_ctx(tmp)
    agg = np.aggregate_round(ctx, 2, FIELD)
    census = agg.get("issue_census") or {}
    check("the aggregate carries an issue census for every field member",
          set(census) == set(FIELD), str(sorted(census)))
    check("each version's census is normalized by the sessions that could mention it",
          all(c.get("sessions_expected") == 3 for c in census.values()),
          str({v: c.get("sessions_expected") for v, c in census.items()}))
    orig, r1, w1 = census["orig"], census["r1_a2"], census["w1"]
    check("orig: the repeated correctness/major row counts ONCE in its own session",
          orig["tiers"]["correctness"]["severities"]["major"]["own"] == 1
          and orig["tiers"]["correctness"]["severities"]["major"]["peer"] == 2,
          str(orig["tiers"]["correctness"]["severities"]["major"]))
    check("orig: the formatting/minor row is attributed to him by his own session",
          orig["tiers"]["formatting"]["severities"]["minor"]["total"] == 1
          and orig["tiers"]["formatting"]["severities"]["minor"]["own"] == 1,
          str(orig["tiers"]["formatting"]))
    check("r1_a2: own minor + critical, peer minor -- no leakage between versions or tiers",
          all(r1["tiers"]["correctness"]["severities"]["minor"].get(k) == v
              for k, v in (("own", 1), ("peer", 0), ("total", 1), ("per_session", 0.3333)))
          and r1["tiers"]["completeness"]["severities"]["critical"]["total"] == 1
          and r1["tiers"]["consistency"]["severities"]["minor"]["peer"] == 2
          and r1["tiers"]["completeness"]["severities"]["minor"]["total"] == 0,
          str(r1["tiers"]))
    cm = orig["tiers"]["correctness"]["severities"]["major"]
    check("the same defect mentioned by three sessions deduplicates to ONE own + ONE peer row",
          (cm["own"], cm["peer"], cm["total"]) == (1, 2, 3)
          and (cm["dedup_own"], cm["dedup_peer"], cm["dedup_total"]) == (1, 1, 2),
          str(cm))
    check("the rates divide the deduplicated counts by the OPPORTUNITIES (own 1, peer 2)",
          (orig["own_opps"], orig["peer_opps"]) == (1, 2)
          and abs(cm["own_rate"] - 1.0) < 1e-9 and abs(cm["peer_rate"] - 0.5) < 1e-9,
          f"opps={orig['own_opps']}/{orig['peer_opps']} rates={cm['own_rate']}/{cm['peer_rate']}")
    check("w1: the same row repeated across one session's comparisons counts once",
          w1["total"] == 1 and w1["tiers"]["completeness"]["severities"]["minor"]["own"] == 1
          and w1["own"] == 1 and w1["peer"] == 0, str(w1))
    check("the severity totals sum the tiers and the rate divides by the expected sessions",
          orig["severities"]["major"]["total"] == 3
          and orig["severities"]["minor"]["total"] == 1
          and orig["total"] == 4 and orig["per_session"] == round(4 / 3, 4)
          and orig["own"] == 2 and orig["peer"] == 2
          and orig["own_sessions"] == 1 and orig["peer_sessions"] == 2,
          f"sev={orig['severities']} total={orig['total']} rate={orig['per_session']}")
    check("a malformed ledger row is ignored, never counted",
          np.build_issue_census(
              [("s", "orig", "w1", {"score": 0, "resolved": [
                  {"tier": "nonsense", "severity": "major", "evidence": "x"}],
                  "introduced": []})], FIELD)["orig"]["total"] == 0)
    return tmp, ctx, agg


def test_census_is_reported_never_ranked(tmp, ctx, agg):
    print()
    print("== the census never moves a score, a median or a champion ==")
    # Strip every ledger row: the scores are identical, so every statistic and
    # the selection must be identical too.
    for rec in ctx.state["runs"].values():
        if rec.get("kind") == "judge":
            for c in rec["scores"]["comparisons"]:
                c["resolved"], c["introduced"] = [], []
    agg2 = np.aggregate_round(ctx, 2, FIELD)
    same = all(agg["stats"][v].get("median") == agg2["stats"][v].get("median")
               and agg["stats"][v].get("mean") == agg2["stats"][v].get("mean")
               for v in FIELD)
    check("stripping the ledger changes no median/mean (it is reported, not ranked)", same,
          str({v: (agg["stats"][v].get("median"), agg2["stats"][v].get("median"))
               for v in FIELD}))
    check("the stripped panel's census is empty (the counts came from the rows)",
          all((agg2["issue_census"][v] or {}).get("total") == 0 for v in FIELD),
          str({v: agg2["issue_census"][v]["total"] for v in FIELD}))
    model = np.score_model_doc()
    check("the census IS the tie-break the score model documents",
          any("census" in str(x) for x in (model.get("tiebreaks") or []))
          and "census" in str(model.get("tiebreak_notes")))
    check("the self-reported counts are reported but no longer ranked",
          any("critical_remaining" in str(x)
              for x in (model.get("reported_but_not_ranked") or []))
          and any("writing_remaining" in str(x)
                  for x in (model.get("reported_but_not_ranked") or []))
          and not any("critical_remaining" in str(x) for x in (model.get("tiebreaks") or [])))


def test_direction_flips(tmp):
    print()
    print("== panel quality: a flip is BOTH sides claiming to be better ==")
    ctx = make_ctx(Path(tempfile.mkdtemp(prefix="paper_census_flip_")))
    agg = np.aggregate_round(ctx, 2, FIELD)
    flips = agg["diagnostics"]["panel_quality"]["direction_flips"]
    check("the consistent pair (orig vs r1_a2) is NOT reported as a flip",
          not any(x.startswith("orig vs r1_a2") for x in flips), str(flips))
    check("the pair where both sides claim to be better IS reported",
          len(flips) == 1 and flips[0].startswith("orig vs w1"), str(flips))
    report_gloss = "the two sides' judges disagree about who is better"
    src = (WS / "paper_pipeline.py").read_text(encoding="utf-8")
    check("the report's gloss for the list matches the fixed condition",
          report_gloss in " ".join(src.split()))


def test_census_file_and_table(tmp, ctx, agg):
    print()
    print("== the census file and the report table ==")
    p = np.write_round_issue_census(ctx, 2, agg)
    check("reports/round2_issue_census.csv is written", p.is_file(), str(p))
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    check("ONE row per (version, tier, severity), with the run name on each",
          len(rows) == len(FIELD) * len(np.BASIS_TIERS) * len(np.SEVERITIES)
          and all(r["run"] == ctx.root.name for r in rows), str(len(rows)))
    by = {(r["version"], r["tier"], r["severity"]): r for r in rows}
    r = by[("orig", "correctness", "major")]
    check("the correctness/major row carries the raw counts and the deduplicated rates",
          (r["own"], r["peer"], r["total"]) == ("1", "2", "3")
          and abs(float(r["per_session"]) - 1.0) < 1e-6
          and (r["own_sessions"], r["peer_sessions"], r["sessions_expected"]) == ("1", "2", "3")
          and (r["dedup_own"], r["dedup_peer"], r["dedup_total"]) == ("1", "1", "2")
          and abs(float(r["own_rate"]) - 1.0) < 1e-9
          and abs(float(r["peer_rate"]) - 0.5) < 1e-9
          and (r["own_opps"], r["peer_opps"]) == ("1", "2"),
          str(r))
    r2 = by[("r1_a2", "completeness", "critical")]
    check("a critical defect appears in its own tier and its own severity",
          (r2["own"], r2["total"], r2["severity"]) == ("1", "1", "critical"), str(r2))
    head = list(np.ISSUE_CENSUS_TABLE_HEAD)
    table = np.issue_census_table(agg)
    check("the report table has one row per member and the same numbers",
          len(table) == len(FIELD) and [x[0] for x in table] == FIELD, str(table))
    orow = dict(zip(head, table[0]))
    check("the table's tier and severity columns read the census",
          orow["correctness"] == "3" and orow["formatting"] == "1"
          and orow["major"] == "3" and orow["minor"] == "1"
          and orow["critical"] == "0" and orow["own/peer"] == "2/2",
          str(orow))


def main() -> int:
    tmp, ctx, agg = test_census_attribution()
    test_census_is_reported_never_ranked(tmp, ctx, agg)
    test_direction_flips(tmp)
    test_census_file_and_table(tmp, ctx, agg)
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL ISSUE-CENSUS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

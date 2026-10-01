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
    defect a judge repeats in every opponent comparison counts once; NO
    cross-sheet matching happens in the default mode (a row two sessions both
    filed counts twice), and the OPT-IN `dedup="location"` mode merges rows
    across sheets only on the structured key (defect class + exact line number +
    a fuzzy-matched >= 7-word excerpt);
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
import itertools
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
    check("three sessions' mentions count as three reported mentions (NO cross-session dedup)",
          (cm["own"], cm["peer"], cm["total"]) == (1, 2, 3),
          str(cm))
    check("the rates divide the reported counts by the OPPORTUNITIES (own 1, peer 2)",
          (orig["own_opps"], orig["peer_opps"]) == (1, 2)
          and abs(cm["own_rate"] - 1.0) < 1e-9 and abs(cm["peer_rate"] - 1.0) < 1e-9,
          f"opps={orig['own_opps']}/{orig['peer_opps']} rates={cm['own_rate']}/{cm['peer_rate']}")
    # The selection's adaptive defect-prefix tie-break: the cells are the
    # canonical severity_tier_category order and the prefix sums are accumulated
    # per version.
    names, matrix, cumulative = np.issue_matrix_and_cumulative(census, FIELD)
    check("the tie-break cells are severity_tier_category (fatal first, minor last, peer/own)",
          names[:4] == ["fatal_correctness_peer", "fatal_correctness_own",
                        "fatal_preservation_peer", "fatal_preservation_own"]
          and names[-1] == "minor_formatting_own"
          and len(names) == len(np.SEVERITY_TIE_ORDER) * len(np.BASIS_TIERS) * 2,
          str(names[:4] + names[-2:]))
    check("the cumulative matrix is the prefix sum of the non-cumulative matrix",
          all(list(itertools.accumulate(matrix[v])) == list(cumulative[v]) for v in FIELD)
          and cumulative["orig"][-1] == orig["total"],
          f"orig last={cumulative['orig'][-1]} total={orig['total']}")
    check("a fatal_correctness_peer cell reads the census's peer count",
          matrix["orig"][0] ==
          orig["tiers"]["correctness"]["severities"]["fatal"]["peer"],
          f"{matrix['orig'][0]}")
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
    check("the adaptive defect prefix IS the tie-break the score model documents",
          any("severity_tier_category" in str(x) for x in (model.get("tiebreaks") or []))
          and "issue_matrix" in str(model.get("tiebreak_notes"))
          and model.get("tiebreak_defect_floor") == np.DEFAULT_TIEBREAK_DEFECT_FLOOR)
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
          and abs(float(r["own_rate"]) - 1.0) < 1e-9
          and abs(float(r["peer_rate"]) - 1.0) < 1e-9
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
    # fileA (the non-cumulative severity_tier_category matrix) and its prefix-sum
    # sibling, stored beside the census file.
    p_m = np.write_round_issue_matrix(ctx, 2, agg)
    p_c = np.write_round_issue_cumulative(ctx, 2, agg)
    check("the matrix and cumulative files sit beside the census file",
          p_m.is_file() and p_c.is_file()
          and p_m.parent == p.parent == p_c.parent, f"{p_m} {p_c}")
    with open(p_m, newline="", encoding="utf-8") as f:
        mrows = list(csv.DictReader(f))
    with open(p_c, newline="", encoding="utf-8") as f:
        crows = list(csv.DictReader(f))
    mhead, chead = list(mrows[0]), list(crows[0])
    cells = np.tiebreak_cell_names()
    check("both files have the same version rows and the same severity_tier_category columns",
          mhead == chead == ["run", "round", "version"] + cells
          and [r["version"] for r in mrows] == FIELD
          and [r["version"] for r in crows] == FIELD,
          str(mhead[:5]))
    by_v = {r["version"]: r for r in mrows}
    cy_v = {r["version"]: r for r in crows}
    check("the cumulative file is the prefix sum of the matrix file",
          all(list(itertools.accumulate(int(by_v[v][c]) for c in cells))
             == [int(cy_v[v][c]) for c in cells] for v in FIELD),
          str({v: cy_v[v][cells[-1]] for v in FIELD}))


def test_location_dedup_optin(tmp):
    print()
    print("== the OPT-IN structured-location dedup (off by default) ==")
    # Two sessions own-sweep the SAME version; both file the identical M4
    # correctness/major row at the same line with the same long excerpt. With
    # dedup off they are two mentions; with "location" on they are ONE, and the
    # merge is audited.
    ev = ("line 42: the treated group showed a higher median than the control "
          "group in every cohort")
    rows = [("sess_1", "orig", "peer_1", comp("v1", 0, introduced=[row(
        "correctness", "major", ev, "M4")])),
            ("sess_2", "orig", "peer_2", comp("v1", 0, introduced=[row(
                "correctness", "major", ev, "M4")]))]
    off = np.build_issue_census(rows, ["orig"])["orig"]
    check("dedup off (the default): the two sheets' rows are two mentions",
          off["total"] == 2 and off["merged"] == 0
          and off["tiers"]["correctness"]["severities"]["major"]["own"] == 2,
          str(off["total"]))
    on = np.build_issue_census(rows, ["orig"], dedup="location")["orig"]
    check("dedup=location: the same class+line+fuzzy excerpt merges to ONE mention",
          on["total"] == 1 and on["merged"] == 1
          and on["tiers"]["correctness"]["severities"]["major"]["own"] == 1
          and on["tiers"]["correctness"]["severities"]["major"]["raw_own"] == 2
          and on["tiers"]["correctness"]["severities"]["major"]["merged_own"] == 1,
          str(on["total"]))
    check("the merge is recorded in the audit with the kept session",
          len(on["dedup_audit"]) == 1
          and on["dedup_audit"][0]["session"] == "sess_2"
          and on["dedup_audit"][0]["kept_session"] == "sess_1"
          and on["dedup_audit"][0]["class"] == "M04"
          and on["dedup_audit"][0]["line"] == 42 and "line 42" in on["dedup_audit"][0]["excerpt"],
          str(on["dedup_audit"]))
    check("the defect classes are normalized to the padded M01/M02 form",
          np.dedup_class_id("M4") == "M04" and np.dedup_class_id("M04") == "M04"
          and np.dedup_class_id("fmt-3") == "M20"
          and np.dedup_class_id("J3") == "J3" and np.dedup_class_id("") == "",
          f"{np.dedup_class_id('M4')}/{np.dedup_class_id('fmt-3')}")
    # Every guard: each row below differs in exactly ONE component from `ev`,
    # so it must NOT merge.
    def one(ev2, check2="M4", sess="sess_2"):
        return np.build_issue_census(
            [("sess_1", "orig", "p1", comp("v1", 0, introduced=[row(
                "correctness", "major", ev, "M4")])),
             (sess, "orig", "p2", comp("v1", 0, introduced=[row(
                 "correctness", "major", ev2, check2)]))],
            ["orig"], dedup="location")["orig"]["total"]
    check("a different defect class does NOT merge",
          one(ev, "M5") == 2, str(one(ev, "M5")))
    check("a row with NO check id never merges (the class key would be incomplete)",
          one(ev, "") == 2, str(one(ev, "")))
    check("a different line number does NOT merge",
          one(ev.replace("line 42", "line 43")) == 2,
          str(one(ev.replace("line 42", "line 43"))))
    check("a missing line number does NOT merge (conservative)",
          one(ev.replace("line 42: ", "")) == 2,
          str(one(ev.replace("line 42: ", ""))))
    check("an excerpt shorter than 7 words does NOT merge",
          one("line 42: treated higher than control") == 2,
          str(one("line 42: treated higher than control")))
    check("one side short is enough to block the merge (both must be long)",
          np.build_issue_census(
              [("sess_1", "orig", "p1", comp("v1", 0, introduced=[row(
                  "correctness", "major",
                  "line 42: the treated group showed a higher median than the control "
                  "group in every cohort", "M4")])),
               ("sess_2", "orig", "p2", comp("v1", 0, introduced=[row(
                   "correctness", "major", "line 42: treated group median higher", "M4")]))],
              ["orig"], dedup="location")["orig"]["total"] == 2,
          "asymmetric excerpts")
    check("a fuzzy near-duplicate at the same line DOES merge (Jaccard >= 0.8)",
          one("line 42: the treated group showed a higher median than the control "
              "group, in every cohort.") == 1,
          str(one("line 42: the treated group showed a higher median than the control "
                  "group, in every cohort.")))
    check("a reworded excerpt below the fuzzy threshold does NOT merge",
          one("line 42: the treated arm had a bigger middle value than the "
              "comparison arm overall") == 2,
          str(one("line 42: the treated arm had a bigger middle value than the "
                  "comparison arm overall")))
    check("the threshold is a parameter (a low threshold lets the rewording merge)",
          np.build_issue_census(
              [("sess_1", "orig", "p1", comp("v1", 0, introduced=[row(
                  "correctness", "major", ev, "M4")])),
               ("sess_2", "orig", "p2", comp("v1", 0, introduced=[row(
                   "correctness", "major",
                   "line 42: the treated arm had a bigger middle value than the "
                   "comparison arm overall", "M4")]))],
              ["orig"], dedup="location", dedup_threshold=0.1)["orig"]["total"] == 1,
          "threshold=0.1")
    # The own/peer split survives the merge: the merge happens WITHIN a source,
    # because each source's count is normalized by its own opportunities.
    mixed = np.build_issue_census(
        [("sess_1", "orig", "p1", comp("v1", 0, introduced=[row(
            "correctness", "major", ev, "M4")])),
         ("sess_2", "r1_a2", "orig", comp("v1", 0, resolved=[row(
             "correctness", "major", ev, "M4")]))],
        ["orig", "r1_a2"], dedup="location")
    check("a merge never crosses the own/peer boundary (the split stays normalized)",
          mixed["orig"]["total"] == 2 and mixed["orig"]["own"] == 1
          and mixed["orig"]["peer"] == 1 and mixed["orig"]["merged"] == 0
          and mixed["r1_a2"]["total"] == 0,
          f"orig={mixed['orig']['total']} own/peer={mixed['orig']['own']}/"
          f"{mixed['orig']['peer']} merged={mixed['orig']['merged']}")
    check("an unknown mode falls back to off inside build_issue_census",
          np.build_issue_census(rows, ["orig"], dedup="junk")["orig"]["total"] == 2)
    # dedup_mode_of: the config reader, its default and its rejection of junk.
    check("dedup_mode_of defaults to off and reads the config key",
          np.dedup_mode_of(None) == "off"
          and np.dedup_mode_of(type("C", (), {"cfg": {}})()) == "off"
          and np.dedup_mode_of(type("C", (), {"cfg": {"dedup_mode": "Location"}})()) == "location")
    bad = type("C", (), {"cfg": {"dedup_mode": "fuzzy"}})()
    try:
        np.dedup_mode_of(bad)
        rejected = False
    except SystemExit:
        rejected = True
    check("dedup_mode_of rejects an unknown configured mode", rejected)
    # The judge prompt carries the location rule ONLY in the opt-in mode: the
    # default prompt is byte-identical (the rule block is never concatenated).
    p_off = np.judge_prompt(Path("/tmp/x"), "r1_t1_j1", 1, "t1", 1, 2, ["v1"])
    p_on = np.judge_prompt(Path("/tmp/x"), "r1_t1_j1", 1, "t1", 1, 2, ["v1"],
                           dedup_mode="location")
    check("the judge prompt gains the line+excerpt rule only in location mode",
          "ISSUE-LOCATION RULE" not in p_off and "ISSUE-LOCATION RULE" in p_on
          and p_on.startswith(p_off.rstrip("\n")[:400]))
    check("the location rule asks for `line N` and >= 7 words",
          "`line N`" in p_on and "7 words" in p_on)
    # The audit file rides beside the census/matrix/cumulative files.
    ctx = make_ctx(Path(tempfile.mkdtemp(prefix="paper_census_dedup_")))
    ctx.cfg["dedup_mode"] = "location"
    agg = np.aggregate_round(ctx, 2, FIELD)
    p_a = np.write_round_dedup_audit(ctx, 2, agg)
    check("reports/round2_dedup_audit.json is written beside the census",
          p_a.is_file() and p_a.name == "round2_dedup_audit.json", str(p_a))
    payload = np.json.loads(p_a.read_text(encoding="utf-8"))
    check("the audit records the mode and the merge count",
          payload.get("mode") == "location"
          and payload.get("merged_rows") == len(payload.get("merges") or [])
          and payload.get("min_words") == np.DEDUP_MIN_WORDS,
          str({k: payload.get(k) for k in ("mode", "merged_rows", "min_words")}))
    # The mode flows through the census file's columns, too.
    p = np.write_round_issue_census(ctx, 2, agg)
    with open(p, newline="", encoding="utf-8") as f:
        rows_c = list(csv.DictReader(f))
    check("the census CSV carries the raw/merged counters and the mode",
          all(r["dedup_mode"] == "location" for r in rows_c)
          and all(k in rows_c[0] for k in ("raw_own", "raw_peer", "merged_own", "merged_peer")),
          str(rows_c[0]))


def test_dedup_mode_cli(tmp):
    print()
    print("== the dedup mode is a CLI parameter (setup + set-dedup-mode) ==")
    import json
    import shutil
    import subprocess
    root = tmp / "root"
    src = tmp / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "manuscript.md").write_text("Abstract\n\nwords here.\n", encoding="utf-8")
    cli = [sys.executable, str(WS / "paper_pipeline.py")]
    r = subprocess.run(cli + ["setup", "--source", str(src), "--root", str(root),
                              "--rounds", "1", "--judges", "1", "--rewrites", "0",
                              "--revises", "1", "--dedup-mode", "location"],
                       capture_output=True, text=True)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("setup --dedup-mode location records the key",
          r.returncode == 0 and cfg.get("dedup_mode") == "location",
          (r.stderr or r.stdout)[-200:])
    r = subprocess.run(cli + ["setup", "--source", str(src), "--root", str(tmp / "root2"),
                              "--rounds", "1", "--judges", "1", "--rewrites", "0",
                              "--revises", "1"],
                       capture_output=True, text=True)
    cfg2 = json.loads((tmp / "root2" / "pipeline_config.json").read_text(encoding="utf-8"))
    check("setup without the flag records off (the default)",
          r.returncode == 0 and cfg2.get("dedup_mode") == "off",
          (r.stderr or r.stdout)[-200:])
    r = subprocess.run(cli + ["setup", "--source", str(src), "--root", str(tmp / "root3"),
                              "--rounds", "1", "--dedup-mode", "junk"],
                       capture_output=True, text=True)
    check("setup rejects an unknown --dedup-mode", r.returncode != 0,
          (r.stderr or r.stdout)[-160:])
    r = subprocess.run(cli + ["set-dedup-mode", "location", "--root", str(root)],
                       capture_output=True, text=True)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("set-dedup-mode changes an existing root",
          r.returncode == 0 and cfg.get("dedup_mode") == "location",
          (r.stderr or r.stdout)[-200:])
    r = subprocess.run(cli + ["set-dedup-mode", "off", "--root", str(root)],
                       capture_output=True, text=True)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("set-dedup-mode off restores the default",
          r.returncode == 0 and cfg.get("dedup_mode") == "off",
          (r.stderr or r.stdout)[-200:])
    r = subprocess.run(cli + ["set-dedup-mode", "--show", "--root", str(root)],
                       capture_output=True, text=True)
    check("set-dedup-mode --show prints the current mode",
          r.returncode == 0 and "mode: off" in r.stdout, (r.stdout or r.stderr)[-160:])
    r = subprocess.run(cli + ["set-dedup-mode", "junk", "--root", str(root)],
                       capture_output=True, text=True)
    check("set-dedup-mode rejects an unknown mode", r.returncode != 0,
          (r.stdout or r.stderr)[-160:])
    r = subprocess.run(cli + ["status", "--root", str(root)], capture_output=True, text=True)
    check("status prints the dedup mode",
          r.returncode == 0 and "dedup mode:" in r.stdout, (r.stdout or r.stderr)[-160:])
    for p in (root, tmp / "root2", tmp / "root3"):
        shutil.rmtree(p, ignore_errors=True)


def main() -> int:
    tmp, ctx, agg = test_census_attribution()
    test_census_is_reported_never_ranked(tmp, ctx, agg)
    test_direction_flips(tmp)
    test_census_file_and_table(tmp, ctx, agg)
    test_location_dedup_optin(tmp)
    test_dedup_mode_cli(tmp)
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL ISSUE-CENSUS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""LLM defect audit: TP/FP labelling + the auditedTP_* diagnostic family.

Run:  python3 .paper_test/test_defect_audit.py

The audit is DIAGNOSTIC ONLY: it labels the rows of
`reports/round<N>_defects.csv`, writes the TP-only report family, and must never
touch the aggregation the champion selection reads.  This suite pins:

  * the audit.json schema check (unknown ids, bad labels and junk rows dropped);
  * the backend policy (on with an agent preset, off for manual/custom backends,
    explicit --defect-audit[-cmd] / PAPER_DEFECT_AUDIT_CMD wins, --no-defect-audit
    wins over everything, a recorded "--no-defect-audit" stays off);
  * `census_from_filtered_rows` reproducing the original per-cell counts when
    every row is kept, and the arithmetic when only the TP rows remain;
  * the whole auditedTP file family, written from a stub-agent audit;
  * the idempotent reuse of a stored audit (a `run` + `decide` pair pays once);
  * THE INVARIANT: the input aggregation (and therefore the champion selection)
    is byte-identical before and after the audit, and the non-audited files are
    never rewritten by it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_defect_audit", str(WS / "paper_pipeline.py"))
pd = importlib.util.module_from_spec(spec)
sys.modules["paper_defect_audit"] = pd
spec.loader.exec_module(pd)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(F"OK {name}")
    else:
        FAILS.append(F"{name}: {detail}")
        print(F"FAIL {name}: {detail}")


def make_ctx(root: Path):
    ctx = types.SimpleNamespace(
        root=root,
        reports_dir=root / "reports",
        state={},
        runs=lambda kind=None, round_no=None: [],
        round_rec=lambda r: {"field": ["a", "b"]},
        save_state=lambda: None,
    )
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    return ctx


def synthetic_agg():
    """Two versions, three sessions, four defect rows (two per version)."""
    obs = [
        ("judge_j1", "a", "b", {
            "score": 2, "basis": "correctness",
            "resolved": [{"check": "M4", "tier": "correctness", "severity": "minor",
                          "evidence": "alpha claim"}] * 0,
            "introduced": [{"check": "J3", "tier": "writing", "severity": "minor",
                            "evidence": "alpha wording row"}]}),
        ("judge_j2", "b", "a", {
            "score": -2, "basis": "correctness",
            "resolved": [{"check": "M4", "tier": "correctness", "severity": "minor",
                          "evidence": "beta boundary row"}],
            "introduced": []}),
        ("judge_j3", "a", "b", {
            "score": 0, "basis": "none",
            "resolved": [],
            "introduced": [{"check": "M10", "tier": "consistency", "severity": "minor",
                            "evidence": "alpha reference-dash row"}]}),
    ]
    census = pd.build_issue_census(obs, ["a", "b"], sessions_expected=3)
    rows = pd.build_issue_ledger_rows(obs, ["a", "b"])
    agg = {"field": ["a", "b"], "issue_census": census, "issue_rows": rows,
           "score_rows": [{"round": 1, "member": "a", "credited": 2, "direction": "own",
                           "opponent_id": "b", "opponent_label": "v1",
                           "source_judge_run": "judge_j1", "source_judge_index": 1,
                           "sheet_target": "a", "score_as_written": 2,
                           "basis": "correctness", "resolved": "", "introduced": "",
                           "reason": "synthetic"}],
           "stats": {"a": {"n": 1, "expected_n": 1, "median": 2, "mean": 2.0,
                           "iqr": 0, "vs_original": 2, "vs_base": 2,
                           "digest": "aaaaaaaaaaaa", "author_placeholders": 0},
                     "b": {"n": 1, "expected_n": 1, "median": -2, "mean": -2.0,
                           "iqr": 0, "vs_original": -2, "vs_base": -2,
                           "digest": "bbbbbbbbbbbb", "author_placeholders": 0}}}
    return agg


def stub_agent_code():
    """A tiny auditor: the first row FP, every other row TP."""
    return (
        "import json;"
        "d=json.load(open('defects.json'));"
        "v=[{'defect_id':x['defect_id'],'label':('FP' if i==0 else 'TP'),"
        "'reason':'stub reason'} for i,x in enumerate(d['defects'])];"
        "json.dump({'verdicts':v},open('audit.json','w'))"
    )


def main() -> int:
    # ---- 1. audit.json schema check -----------------------------------------
    norm = pd._normalize_defect_audit(
        {"verdicts": [
            {"defect_id": "r1-D0001", "label": "TP", "reason": "quoted text present"},
            {"defect_id": "r1-D0002", "label": "false_positive", "reason": "label present"},
            {"defect_id": "r1-D0002", "label": "TP"},          # duplicate -> first wins
            {"defect_id": "r1-D9999", "label": "TP"},          # unknown -> dropped
            {"defect_id": "r1-D0003", "label": "MAYBE"},       # bad label -> dropped
            "junk",
        ]}, {"r1-D0001", "r1-D0002", "r1-D0003"})
    check("schema check keeps the two valid, unique verdicts",
          norm == {"r1-D0001": ("TP", "quoted text present"),
                   "r1-D0002": ("FP", "label present")}, norm)
    check("a bare list is accepted",
          pd._normalize_defect_audit([{"defect_id": "x", "label": True}], {"x"})
          == {"x": ("TP", "")})

    # ---- 2. backend policy --------------------------------------------------
    off = types.SimpleNamespace(no_defect_audit=True, defect_audit=None,
                                defect_audit_cmd=None)
    check("--no-defect-audit wins",
          pd.resolve_defect_audit_cmd(off, ["codex"], False, {}) == (None, "disabled"))
    plain = types.SimpleNamespace(no_defect_audit=False, defect_audit=None,
                                  defect_audit_cmd=None)
    stub_judge = [sys.executable, "stub_judge.py"]
    got = pd.resolve_defect_audit_cmd(plain, stub_judge, False, {})
    check("a custom/stub judge backend stays off unless asked",
          got == (None, "custom-backend"), got)
    got = pd.resolve_defect_audit_cmd(plain, None, True, {})
    check("a manual judge wave stays off", got == (None, "manual"), got)
    got = pd.resolve_defect_audit_cmd(plain, ["codex"], False,
                                      {"cmd": None, "source": "disabled"})
    check("a recorded --no-defect-audit stays off", got == (None, "disabled"), got)
    saved = os.environ.pop("PAPER_DEFECT_AUDIT_CMD", None)
    try:
        os.environ["PAPER_DEFECT_AUDIT_CMD"] = json.dumps([sys.executable, "-c", "pass"])
        got = pd.resolve_defect_audit_cmd(plain, stub_judge, False, {})
        check("PAPER_DEFECT_AUDIT_CMD enables the audit for any backend",
              got[1] == "defect-audit-env" and got[0][0] == sys.executable, got)
    finally:
        del os.environ["PAPER_DEFECT_AUDIT_CMD"]
        if saved is not None:
            os.environ["PAPER_DEFECT_AUDIT_CMD"] = saved
    if shutil.which("codex"):
        got = pd.resolve_defect_audit_cmd(plain, ["codex", "exec", "-"], False, {})
        check("an agent-preset judge backend turns the audit on by default",
              got[1] == "lightweight-default" and bool(got[0]), got)

    # ---- 3. census filtering + the champion invariant -----------------------
    agg = synthetic_agg()
    census_before = json.dumps(pd._json_safe(agg["issue_census"]), sort_keys=True)
    all_rows = pd.defect_list_rows(make_ctx(Path(tempfile.mkdtemp())), 1, agg)
    check("the synthetic round has three defect rows", len(all_rows) == 3, len(all_rows))
    same = pd.census_from_filtered_rows(agg["issue_census"], all_rows)
    check("keeping every row reproduces the original census counts",
          json.dumps(pd._json_safe(same), sort_keys=True) == census_before)
    tp_rows = [r for r in all_rows if "beta boundary" in r["evidence"]
               or "alpha wording" in r["evidence"]]
    fp_rows = [r for r in all_rows if r not in tp_rows]
    check("the synthetic split is 2 TP / 1 FP", len(tp_rows) == 2 and len(fp_rows) == 1,
          (len(tp_rows), len(fp_rows)))
    filtered = pd.census_from_filtered_rows(agg["issue_census"], tp_rows)
    def total(c):
        return sum(int((((((c.get(v) or {}).get("tiers") or {}).get(t) or {})
                         .get("severities") or {}).get(s, {}) or {}).get("total") or 0)
                   for v in ("a", "b") for t in pd.BASIS_TIERS for s in pd.SEVERITIES)
    check("the filtered census counts only the TP rows", total(filtered) == 2,
          total(filtered))
    check("the template census is untouched",
          json.dumps(pd._json_safe(agg["issue_census"]), sort_keys=True) == census_before)

    # ---- 4. the file family + the no-mutation invariant ---------------------
    root = Path(tempfile.mkdtemp(prefix="defect_audit_test_"))
    try:
        ctx = make_ctx(root)
        (ctx.reports_dir / "round1_defects.csv").write_text("sentinel\n", encoding="utf-8")
        agg_snapshot = json.dumps(pd._json_safe(agg), sort_keys=True)
        labelled = pd.apply_defect_audit(all_rows, {
            **{r["defect_id"]: ("FP", "stub") for r in fp_rows},
            **{r["defect_id"]: ("TP", "stub") for r in tp_rows},
        })
        audited = pd.audited_defect_agg(ctx, 1, agg, labelled)
        check("the audited agg is a copy (the original aggregation is unchanged)",
              json.dumps(pd._json_safe(agg), sort_keys=True) == agg_snapshot)
        check("the audited agg keeps the recorded score rows and stats",
              audited["score_rows"] is agg["score_rows"]
              and audited["stats"] is agg["stats"])
        check("the audited census counts only the TP rows", total(audited["issue_census"]) == 2,
              total(audited["issue_census"]))
        # The audited TABLE must re-read defects@K / the severity totals from the
        # audited census, not from the ranking rows `select_champion` wrote.
        sel = {"champion": "a",
               "ranking": [
                   {"id": "a", "issues": {"minor": {"own": 3, "peer": 0}},
                    "defect_prefix_total": 3, "writing_remaining": 0,
                    "is_base": False},
                   {"id": "b", "issues": {"minor": {"own": 0, "peer": 0}},
                    "defect_prefix_total": 0, "writing_remaining": 0,
                    "is_base": False}],
               "tiebreak": {"cells_used": 48, "cells_total": 48, "floor": 10}}
        def member_row(rows, mid):
            return next(r for r in rows[1:] if r[0] == mid)
        plain_row = member_row(pd.round_member_table_rows(
            ctx, 1, [{"id": "a"}, {"id": "b"}], agg, sel, "a"), "a")
        aud_row = member_row(pd.round_member_table_rows(
            ctx, 1, [{"id": "a"}, {"id": "b"}], audited,
            pd.audited_table_sel(sel), "a"), "a")
        check("the non-audited table keeps the ranking row's defect numbers",
              plain_row[1] == "3" and plain_row[9].endswith("/3"),
              (plain_row[1], plain_row[9]))
        check("the audited table re-reads defects@K from the audited census",
              aud_row[1] == "2" and aud_row[9].endswith("/2"),
              (aud_row[1], aud_row[9]))
        check("the audited table keeps the score columns and the champion note",
              plain_row[2:9] == aud_row[2:9] and plain_row[-1] == aud_row[-1] == "CHAMPION",
              (plain_row[2:9], aud_row[2:9]))
        files = pd.write_defect_audit_reports(ctx, 1, agg, labelled, audited=audited)
        names = sorted(p.name for p in files)
        for want in ("round1_auditedTP_defects.csv", "round1_auditedTP_issue_census.csv",
                     "round1_auditedTP_issue_matrix.csv",
                     "round1_auditedTP_issue_cumulative.csv",
                     "round1_auditedTP_raw_scores.csv",
                     "round1_auditedTP_dedup_audit.json"):
            check(F"wrote {want}", (ctx.reports_dir / want).is_file())
        fields = (ctx.reports_dir / "round1_auditedTP_defects.csv") \
            .read_text(encoding="utf-8").splitlines()
        check("the audited defect list keeps the TP rows and the audit columns",
              len(fields) == 3 and "audit_label" in fields[0] and "audit_reason" in fields[0],
              fields[:1])

        # ---- 5. the full orchestration with a stub agent + reuse ------------
        res = pd.write_round_defect_audit(
            ctx, 1, agg=agg,
            agent_cmd=[sys.executable, "-c", stub_agent_code()], timeout=60)
        check("the stub audit ran and labelled every row",
              res.get("ok") and res.get("rows") == 3 and res.get("tp") == 2
              and res.get("fp") == 1, res)
        check("the audit metadata records the verdicts",
              (ctx.reports_dir / "round1_defect_audit.json").is_file())
        sandbox = ctx.reports_dir / "defect_audit_round1"
        check("the audit sandbox carries the defect list, the judge sessions and the sheets",
              all((sandbox / n).is_file() for n in
                  ("defects.json", "judge_runs.json", "judge_opinions.json",
                   "audit.json", "PROMPT.md")),
              sorted(p.name for p in sandbox.iterdir()) if sandbox.is_dir() else None)
        meta = json.loads((ctx.reports_dir / "round1_defect_audit.json")
                          .read_text(encoding="utf-8"))
        check("the verdicts are stored for reuse",
              meta.get("ok") and len(meta.get("verdicts") or []) == 3, meta.get("rows"))
        check("the audit never rewrote the non-audited defect list",
              (ctx.reports_dir / "round1_defects.csv").read_text(encoding="utf-8")
              == "sentinel\n")
        check("the original aggregation survived the full orchestration",
              json.dumps(pd._json_safe(agg), sort_keys=True) == agg_snapshot)
        again = pd.write_round_defect_audit(
            ctx, 1, agg=agg,
            agent_cmd=[sys.executable, "-c", "raise SystemExit(3)"], timeout=60)
        check("a stored audit is reused without running the agent again",
              again.get("reused") and again.get("ok") and again.get("tp") == 2, again)
        off_res = pd.write_round_defect_audit(ctx, 1, agg=agg, agent_cmd=None,
                                              use_agent=False)
        check("a disabled audit writes nothing and mutates nothing",
              off_res.get("used") is False
              and json.dumps(pd._json_safe(agg), sort_keys=True) == agg_snapshot, off_res)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if FAILS:
        print(F"\n{len(FAILS)} defect-audit check(s) FAILED")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("\nAll defect-audit checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

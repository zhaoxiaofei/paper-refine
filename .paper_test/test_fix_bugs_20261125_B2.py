#!/usr/bin/env python3
"""Regression checks for the 2026-11-25 fix-bugs wave, group B2.

One check block per confirmed candidate:

  F111 a cached conflict report still rewrites the printed per-round .md
  F112 an LLM echo with a different judge set is one conflict, not two
  F113 a non-array conflicts.json is a failed audit, never a clean one
  F114 the conflict-report cache key covers _JUDGE_CONFLICT_MANUAL
  F117 the cumulative TODO names a round whose conflict audit produced no JSON
  F118 a malformed findings.json is not "nothing was reviewed"; the CSV retries
  F121 a malformed pdfs/manifest.json is skipped, not AttributeError
  F122 a non-dict conflict row cannot crash the report/TODO writers

Run:  python3 .paper_test/test_fix_bugs_20261125_B2.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1125b2_pp", "paper_pipeline.py")

FAILS = []
TMPDIRS = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


class FakeCtx:
    def __init__(self, root: Path):
        self.root = root
        self.reports_dir = root / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._rounds = 1

    def rounds_count(self) -> int:
        return self._rounds

    def round_rec(self, r):
        return {"round": int(r), "status": "done", "field": ["a", "b"]}

    def runs(self, **kwargs):
        return []


# ---------------------------------------------------------------------------
# F111 -- a cached report still writes the per-round .md its caller prints
# ---------------------------------------------------------------------------
def test_f111_cached_report_rewrites_markdown() -> None:
    ctx = FakeCtx(scratch("b2_f111_"))
    old_ops = pp.round_judge_opinions
    try:
        pp.round_judge_opinions = lambda *a, **k: []
        first = pp.write_round_judge_conflicts(ctx, 1, agg={"field": ["a", "b"]},
                                               agent_cmd=None, use_agent=False)
        md = ctx.reports_dir / "round1_judge_conflicts.md"
        md.unlink()
        second = pp.write_round_judge_conflicts(ctx, 1, agg={"field": ["a", "b"]},
                                                agent_cmd=None, use_agent=False)
        cached = (second.get("input_fingerprint") == first.get("input_fingerprint")
                  and second.get("generated") == first.get("generated"))
    finally:
        pp.round_judge_opinions = old_ops
    check("F111 a cached conflict report rewrites its missing .md",
          md.is_file() and cached and "manual checks" in md.read_text("utf-8"),
          f"exists={md.is_file()} cached={cached}")


# ---------------------------------------------------------------------------
# F112 -- the LLM echo of a mechanical conflict is one row, not two
# ---------------------------------------------------------------------------
def test_f112_merge_by_pair() -> None:
    mech = [{"kind": "claim_inversion", "severity": "major", "member": "m",
             "opponent": "o", "judges": ["j1", "j2"],
             "subject": "claim:the x was fixed", "summary": "mechanical",
             "evidence": [{"judge_run": "j1", "side": "resolved", "text": "t1"}],
             "manual_check": "m"}]
    llm = [{"kind": "claim_inversion", "severity": "major", "member": "m",
            "opponent": "o", "judges": ["j1"], "subject": "",
            "summary": "the auditor echoes the same conflict",
            "evidence": [{"judge_run": "j1", "side": "resolved", "text": "t1"}],
            "manual_check": "m"}]
    merged = pp._merge_judge_conflicts(mech, llm)
    counts = pp._judge_conflict_counts(merged)
    # ... while two genuinely different subjects plus a subjectless echo stay apart.
    a = {"kind": "check_disposition", "severity": "minor", "member": "x",
         "opponent": "y", "judges": ["j1"], "subject": "check:M15",
         "summary": "M15", "evidence": [], "manual_check": "m"}
    b = {"kind": "check_disposition", "severity": "minor", "member": "x",
         "opponent": "y", "judges": ["j1"], "subject": "check:J3",
         "summary": "J3", "evidence": [], "manual_check": "m"}
    echo = {"kind": "check_disposition", "severity": "blocker", "member": "x",
            "opponent": "y", "judges": ["j1"], "summary": "one of them",
            "evidence": [], "manual_check": "m"}
    distinct = pp._merge_judge_conflicts([a, b], [echo])
    check("F112 one real conflict is one row (union of judges)",
          len(merged) == 1 and counts.get("total") == 1
          and set(merged[0].get("judges") or []) == {"j1", "j2"}
          and len(distinct) == 3,
          f"merged={len(merged)} counts={counts} distinct={len(distinct)}")


# ---------------------------------------------------------------------------
# F113 -- a conflicts.json whose conflicts is not an array is a failed audit
# ---------------------------------------------------------------------------
def test_f113_non_array_conflicts() -> None:
    ctx = FakeCtx(scratch("b2_f113_"))
    old_exec = pp._execute_attempt_in
    try:
        def fake(sb, rec, cmd, seconds, **kw):
            (Path(sb) / "conflicts.json").write_text(
                json.dumps({"conflicts": {"kind": "claim_inversion"}}), "utf-8")
            return {"rc": 0, "dur": 0, "error": None, "log": None}

        pp._execute_attempt_in = fake
        kept, info = pp.run_judge_conflict_agent(ctx, 1, {"opinions": []},
                                                 ["/bin/true"], timeout=10)
    finally:
        pp._execute_attempt_in = old_exec
    check("F113 a non-array conflicts.json is not a clean cached audit",
          kept == [] and info.get("ok") is False and info.get("error"),
          f"kept={kept} ok={info.get('ok')} error={info.get('error')}")


# ---------------------------------------------------------------------------
# F114 -- the cache fingerprint covers the manual_check text
# ---------------------------------------------------------------------------
def test_f114_fingerprint_covers_manual_text() -> None:
    old_manual = dict(pp._JUDGE_CONFLICT_MANUAL)
    try:
        before = pp._judge_conflict_rules_fingerprint()
        pp._JUDGE_CONFLICT_MANUAL["numeric_contradiction"] = "TOTALLY DIFFERENT ADVICE"
        after = pp._judge_conflict_rules_fingerprint()
    finally:
        pp._JUDGE_CONFLICT_MANUAL.clear()
        pp._JUDGE_CONFLICT_MANUAL.update(old_manual)
    check("F114 editing the manual_check text invalidates the report cache",
          before != after, f"{before[:12]} == {after[:12]}")


# ---------------------------------------------------------------------------
# F117 -- the cumulative TODO names a round with no conflict JSON
# ---------------------------------------------------------------------------
def test_f117_todo_names_unaudited_round() -> None:
    ctx = FakeCtx(scratch("b2_f117_"))
    ctx._rounds = 2
    (ctx.reports_dir / "round1_judge_conflicts.json").write_text(
        json.dumps({"round": 1, "conflicts": [], "counts": {"total": 0}}), "utf-8")
    p = pp.write_judge_conflicts_todo(ctx)
    text = p.read_text("utf-8")
    check("F117 an unaudited round is a named gap, not a silent skip",
          "Round 2" in text and "NOT AUDITED" in text
          and "not audited" in text.lower(),
          text[-400:])


# ---------------------------------------------------------------------------
# F118 -- a malformed findings.json is recovered / reported, and the CSV retries
# ---------------------------------------------------------------------------
def test_f118_review_findings_malformed() -> None:
    ctx = FakeCtx(scratch("b2_f118_"))
    arch = ctx.reports_dir / "round1_review"
    arch.mkdir(parents=True)
    (arch / "findings.json").write_text(json.dumps(
        {"findings": {"F-7": {"check": "M4", "severity": "major",
                              "location": "main.md:4", "evidence": "e",
                              "explanation": "x"}}}), "utf-8")
    rows = pp.review_findings_rows(ctx, 1)
    csv_path = pp.write_round_review_findings(ctx, 1)
    csv_text = csv_path.read_text("utf-8")
    # The retry half: a header-only CSV left by an earlier malformed write is
    # regenerated once the archive parses.
    ctx2 = FakeCtx(scratch("b2_f118b_"))
    arch2 = ctx2.reports_dir / "round1_review"
    arch2.mkdir(parents=True)
    (arch2 / "findings.json").write_text(json.dumps(
        {"findings": [{"id": "F-9", "check": "M4", "severity": "major",
                       "location": "main.md:9", "evidence": "e",
                       "explanation": "x"}]}), "utf-8")
    (ctx2.reports_dir / "round1_review_findings.csv").write_text(
        ",".join(pp.REVIEW_FINDINGS_FIELDS) + "\n", "utf-8")
    saved = {name: getattr(pp, name) for name in
             ("write_round_raw_scores", "write_round_issue_census",
              "write_round_issue_matrix", "write_round_issue_cumulative",
              "write_round_dedup_audit", "write_round_defects")}
    try:
        for name in saved:
            setattr(pp, name, lambda ctx, r: ctx.reports_dir / "noop")
        pp.backfill_round_raw_scores(ctx2)
    finally:
        for name, fn in saved.items():
            setattr(pp, name, fn)
    retried = (ctx2.reports_dir / "round1_review_findings.csv").read_text("utf-8")
    check("F118 a dict-shaped findings list is recovered and the CSV retries",
          len(rows) == 1 and rows[0].get("finding_id") == "F-7"
          and "F-7" in csv_text and "F-9" in retried,
          f"rows={rows} csv={csv_text[:120]!r} retried={retried[:120]!r}")


# ---------------------------------------------------------------------------
# F122 -- a non-dict conflict row is skipped, never AttributeError
# ---------------------------------------------------------------------------
def test_f122_non_dict_conflict_row() -> None:
    try:
        md = pp.judge_conflicts_markdown({"round": 1, "conflicts": ["x"]})
        md_ok = isinstance(md, str)
    except Exception as e:                                          # noqa: BLE001
        md, md_ok = f"{type(e).__name__}: {e}", False
    ctx = FakeCtx(scratch("b2_f122_"))
    (ctx.reports_dir / "round1_judge_conflicts.json").write_text(
        json.dumps({"round": 1, "conflicts": ["x"],
                    "counts": {"total": 1}}), "utf-8")
    try:
        todo = pp.write_judge_conflicts_todo(ctx).read_text("utf-8")
        todo_ok = True
    except Exception as e:                                          # noqa: BLE001
        todo, todo_ok = f"{type(e).__name__}: {e}", False
    check("F122 a non-dict conflict row cannot crash the report/TODO writers",
          md_ok and todo_ok and "malformed" in md.lower() and "malformed" in todo.lower(),
          f"md={md!r} todo={todo!r}")


# ---------------------------------------------------------------------------
# F121 -- a malformed pdfs/manifest.json is skipped, never AttributeError
# ---------------------------------------------------------------------------
def test_f121_malformed_pdf_manifest() -> None:
    direct = []
    for stored in ({"sets": {"a": 1}}, {"sets": [{"documents": "x"}]},
                   {"sets": [None]}, {"sets": [{"documents": [None]}]}):
        try:
            direct.append(pp._pdf_previous_records(stored) == {})
        except Exception as e:                                      # noqa: BLE001
            direct.append(f"{type(e).__name__}: {e}")
    root = scratch("b2_f121_")
    pdfs = root / "pdfs"
    pdfs.mkdir(parents=True)
    (pdfs / "manifest.json").write_text(json.dumps({"sets": 5}), "utf-8")
    try:
        pp.run_pdf_conversion(SimpleNamespace(root=root), rounds=[],
                              include_original=False)
        end_to_end = True
    except Exception as e:                                          # noqa: BLE001
        end_to_end = f"{type(e).__name__}: {e}"
    check("F121 a malformed PDF manifest is unusable data, not a crash",
          all(ok is True for ok in direct) and end_to_end is True,
          f"direct={direct} end_to_end={end_to_end}")


def main() -> int:
    test_f111_cached_report_rewrites_markdown()
    test_f112_merge_by_pair()
    test_f113_non_array_conflicts()
    test_f114_fingerprint_covers_manual_text()
    test_f117_todo_names_unaudited_round()
    test_f122_non_dict_conflict_row()
    test_f118_review_findings_malformed()
    test_f121_malformed_pdf_manifest()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED: " + ", ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

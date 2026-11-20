#!/usr/bin/env python3
"""Regression checks for fix_bugs run 2026-11-20 / wave 1.

Every check pins a candidate this stage re-validated on the tree. On the
unpatched tree the check FAILS; after the smallest confirmed fix it passes.

  F014 a failed bounded repair is reported in the decision/report/certification
  F016 the adopted-check block enumerates the whole M1-M36 / J1-J5 set
  F020 a prose-only audit drop is not a usable basis
  F028 an unreadable feedback file is a failure, not silently absent
  F031 TODO/XXX inside ordinary prose is a claim, not a removable artifact
  F035 a legacy round re-aggregates under the historical dedup default
  F037 ordinary Methods prose is not a PKG-1 stage note
  F046 a record without the soft-deletions key is bound to its prompt (off)
  F047 an uppercase trailing identity letter is not a version token
  F048 an absent pristine feedback area may not be created by the candidate
  F061 LaTeX root detection strips comments before blanking verbatim bodies
  F073 a non-numeric claim with a dangling pointer is held, never deleted
  F077 a multi-paragraph reference entry keeps every continuation paragraph
  F084 dir_size does not count a symlink target it will not reclaim
  F096 numeric ledger ids are read by every ledger reader

Run:  python3 .paper_test/test_fix_bugs_20261120_wave1.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402

FAILS: list[str] = []


def check(label: str, cond, detail="") -> None:
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class FakeCtx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------------------------------------------------------- F014
def test_f014_revision_repair_reported() -> None:
    print("\n== F014: a failed bounded repair reaches the decision/report ==")
    rounds = [{"round": 1,
               "stored": {"revision_repair": {
                   "status": "failed", "rows": 3, "rolled_back": True,
                   "error": "the bounded repair changed file(s) outside its plan"}}}]
    fn = getattr(pp, "revision_repair_failures", None)
    got = fn(rounds) if fn else None
    check("F014 a failed repair is extracted from the round record",
          bool(got) and got[0].get("round") == 1
          and "outside its plan" in str(got[0].get("error")),
          got)
    summary = getattr(pp, "revision_repair_summary", None)
    summ = summary(rounds[0]["stored"]) if summary else None
    check("F014 the round summary carries status/rolled_back/error",
          isinstance(summ, dict) and summ.get("status") == "failed"
          and summ.get("rolled_back") is True and "outside its plan" in str(summ.get("error")),
          summ)
    # p08 stores it on the RUN record, not the round record: the decision path
    # must resolve it from the round's pin (`produced_by_run`).
    ctx = FakeCtx(state={"runs": {"r1_a2_revise": {
        "revision_repair": {"status": "failed", "rows": 3, "rolled_back": True,
                            "error": "the bounded repair changed file(s) outside its plan"}}}})
    via_run = [{"round": 1, "stored": {"pin_id": "p1"},
                "pin": {"produced_by_run": "r1_a2_revise"}}]
    got2 = fn(via_run, ctx) if fn else None
    check("F014 the outcome is resolved from the champion's producing run",
          bool(got2) and got2[0].get("round") == 1, got2)
    p12 = (ROOT / "paper_pipeline_parts" / "p12_conflicts_decide.py").read_text("utf-8")
    check("F014 the report renders the failed repair",
          "bounded repair" in p12 and "FAILED" in p12
          and "revision_repair_failures(" in p12,
          "report wiring")
    check("F014 decision.json carries the round's revision_repair",
          '"revision_repair": revision_repair_record(ctx, rd) or None' in p12,
          "decision wiring")
    check("F014 certification records the failed repair",
          'certification["revision_repair"]' in p12,
          "certification wiring")


# ---------------------------------------------------------------- F016
def test_f016_adopted_checks_complete() -> None:
    print("\n== F016: the adopted-check block enumerates M1-M36 / J1-J5 ==")
    block = pp.ADOPTED_SWEEPS_BLOCK
    seen = set(re.findall(r"\b(?:M|J)\d{1,2}\b", block))
    for a, b in re.findall(r"\bM(\d{1,2})\s*[-\u2013]\s*M(\d{1,2})\b", block):
        seen |= {f"M{i}" for i in range(int(a), int(b) + 1)}
    for a, b in re.findall(r"\bJ(\d)\s*[-\u2013]\s*J(\d)\b", block):
        seen |= {f"J{i}" for i in range(int(a), int(b) + 1)}
    missing = [f"M{i}" for i in range(1, 25) if f"M{i}" not in seen]
    missing += [f"J{i}" for i in range(1, 5) if f"J{i}" not in seen]
    check("F016 the judge panel's M1-M24/J1-J4 map is fully named", not missing, missing)
    check("F016 the block names the guided review's additional M25-M36 and J5",
          "M25-M36" in block and "J5" in block)
    # The block is injected into the JUDGE prompt too: adding the phase blocks'
    # provenance vocabulary here would blind-break the judge (test_llm... LL3).
    leaked = re.findall(r"(?i)\brewrite\b|\brevision\b", block)
    check("F016 the shared block adds no judge-visible provenance vocabulary",
          not leaked, leaked)


# ---------------------------------------------------------------- F020
def test_f020_audit_drop_needs_evidence() -> None:
    print("\n== F020: an audit drop needs re-runnable evidence ==")
    prose = {"verdicts": [{"defect_id": "r1-D1", "label": "FP",
                           "reason": "the rule says so"}]}
    cov = pp._defect_audit_coverage(prose, {"r1-D1"}, {"r1-D1": ("FP", "the rule says so")})
    check("F020 a prose-only FP drop leaves the audit incomplete",
          pp._defect_audit_coverage_incomplete(cov) and cov.get("empty_reasons") == ["r1-D1"],
          cov)
    good = {"verdicts": [{"defect_id": "r1-D1", "label": "FP",
                          "reason": "`quoted text` is absent at main.md:12"}]}
    cov2 = pp._defect_audit_coverage(good, {"r1-D1"},
                                     {"r1-D1": ("FP", "`quoted text` is absent at main.md:12")})
    check("F020 an evidence-bearing FP drop is accepted",
          not pp._defect_audit_coverage_incomplete(cov2), cov2)
    calc = {"verdicts": [{"defect_id": "r1-D3", "label": "FP",
                          "reason": "the p-value is 0.04, not 0.4"}]}
    cov_calc = pp._defect_audit_coverage(calc, {"r1-D3"},
                                         {"r1-D3": ("FP", "the p-value is 0.04, not 0.4")})
    check("F020 a repeatable numeric computation is evidence",
          not pp._defect_audit_coverage_incomplete(cov_calc), cov_calc)
    tp = {"verdicts": [{"defect_id": "r1-D2", "label": "TP",
                        "reason": "quoted text present"}]}
    cov3 = pp._defect_audit_coverage(tp, {"r1-D2"}, {"r1-D2": ("TP", "quoted text present")})
    check("F020 a TP reason keeps the existing (weaker) bar",
          not pp._defect_audit_coverage_incomplete(cov3), cov3)
    # A bare `word/word` phrase is ordinary prose, not a re-runnable path: the
    # old "directory path" alternative accepted it, so an FP drop still needed
    # no evidence (F020 follow-up).
    slash_prose = "the code/analysis path is not followed"
    cov4 = pp._defect_audit_coverage(
        {"verdicts": [{"defect_id": "r1-D4", "label": "FP", "reason": slash_prose}]},
        {"r1-D4"}, {"r1-D4": ("FP", slash_prose)})
    check("F020 a prose word/word phrase is not a directory-path evidence basis",
          pp._defect_audit_coverage_incomplete(cov4), cov4)
    slash_prose2 = "checked Methods/Results and it is fine"
    cov5 = pp._defect_audit_coverage(
        {"verdicts": [{"defect_id": "r1-D5", "label": "FP", "reason": slash_prose2}]},
        {"r1-D5"}, {"r1-D5": ("FP", slash_prose2)})
    check("F020 'checked Methods/Results' is not evidence",
          pp._defect_audit_coverage_incomplete(cov5), cov5)
    real_path = "raw_data/survival.tsv has no such column"
    cov6 = pp._defect_audit_coverage(
        {"verdicts": [{"defect_id": "r1-D6", "label": "FP", "reason": real_path}]},
        {"r1-D6"}, {"r1-D6": ("FP", real_path)})
    check("F020 a real evidence file path is still accepted",
          not pp._defect_audit_coverage_incomplete(cov6), cov6)


# ---------------------------------------------------------------- F028
def test_f028_unreadable_feedback_file() -> None:
    print("\n== F028: an unreadable feedback file is a failure ==")
    tmp = scratch("f028_")
    area = tmp / "human_review_feedback"
    area.mkdir()
    write(area / "readable.txt", "hello")
    bad = write(area / "unreadable.txt", "secret")
    os.chmod(bad, 0o000)
    try:
        try:
            entries = pp.feedback_area_entries(tmp, "human_review_feedback", failures=[])
        except TypeError:
            entries = pp.feedback_area_entries(tmp, "human_review_feedback")
        failures: list = []
        try:
            pp.feedback_area_entries(tmp, "human_review_feedback", failures=failures)
        except TypeError:
            failures = []
        check("F028 the unreadable file is not silently absent",
              any("unreadable.txt" in f for f in failures), failures)
        check("F028 the readable sibling is still hashed",
              "human_review_feedback/readable.txt" in entries, list(entries))
    finally:
        os.chmod(bad, 0o600)


# ---------------------------------------------------------------- F031
def test_f031_todo_inside_prose_is_a_claim() -> None:
    print("\n== F031: TODO/XXX inside a claim is not a removable artifact ==")
    for text in ("The XXX domain is required for binding.",
                 "We TODO the analysis of cohort 2."):
        check(f"F031 {text[:24]!r} is a claim",
              pp._removal_is_artifact(text) is False)
    for text in ("TODO", "TODO: add the Methods section.", "[CITE]", "TBD"):
        check(f"F031 {text!r} is a placeholder unit",
              pp._removal_is_artifact(text) is True)
    missing = [{"text": "The XXX domain is required for binding.",
                "norm": "the xxx domain is required for binding.",
                "document": "main.md", "tokens": set()}]
    kept = pp.soft_deletion_missing_units(missing, [])
    check("F031 a claim-bearing XXX sentence is not exempted from removal accounting",
          len(kept) == 1, [u.get("text") for u in kept])


# ---------------------------------------------------------------- F035
def test_f035_legacy_dedup_default() -> None:
    print("\n== F035: a legacy round re-aggregates under the recorded default ==")
    seen = {}
    real = pp.aggregate_round

    def spy(c, r, field, dedup=None, rule=None):
        seen["dedup"] = dedup
        return {"issue_census": {}, "issue_rows": [], "field": field}

    try:
        pp.aggregate_round = spy
        ctx = FakeCtx(cfg={"dedup_mode": "location"},
                      round_rec=lambda r: {"field": ["a", "b"]})
        pp._issue_file_agg(ctx, 1)
        pp._defect_rows_by_reaggregation(ctx, 1)
        seen_rows = seen.get("dedup")
        ctx2 = FakeCtx(cfg={"dedup_mode": "location"},
                       round_rec=lambda r: {"field": ["a", "b"]},
                       runs=lambda **kw: [])
        pp.write_round_defect_audit(ctx2, 1, agg=None, agent_cmd=None)
        seen_audit = seen.get("dedup")
    finally:
        pp.aggregate_round = real
    check("F035 a round with no recorded dedup_mode uses the historical default 'off'",
          seen.get("dedup") is not None and seen_rows == "off" and seen_audit == "off",
          (seen_rows, seen_audit))
    # The census and its long-form defect list must re-aggregate under the SAME
    # mode; so must decision.json's score_model (F035 follow-up).
    p10 = (ROOT / "paper_pipeline_parts" / "p10_reports.py").read_text("utf-8")
    check("F035 the defect-list re-aggregation uses the same default",
          'dedup=rec.get("dedup_mode") or "off"' in p10, "p10 defect rows")
    p11 = (ROOT / "paper_pipeline_parts" / "p11_defect_audit.py").read_text("utf-8")
    check("F035 the defect audit re-aggregates under the same default",
          'dedup=rec.get("dedup_mode") or "off"' in p11, "p11 audit")
    p12 = (ROOT / "paper_pipeline_parts" / "p12_conflicts_decide.py").read_text("utf-8")
    check("F035 decide re-derives a legacy round under the same default",
          'dedup=rrec.get("dedup_mode") or "off"' in p12, "p12 fallback")
    check("F035 decision.json's score_model records the same historical default",
          'dedup=(final["stored"] or {}).get("dedup_mode") or "off"' in p12,
          "p12 score_model")


# ---------------------------------------------------------------- F037
def test_f037_stage_note_precision() -> None:
    print("\n== F037: ordinary Methods prose is not a stage note ==")
    text = "Each sample was measured once; this run's temperature was 37 C."
    hits = [(label, m.group(0)) for label, pat in pp.INTERNAL_ARTIFACT_RES
            for m in [pat.search(text)] if m]
    check("F037 a Methods sentence with \"this run's\" is not internal material",
          not hits, hits)
    hits2 = [(label, m.group(0)) for label, pat in pp.INTERNAL_ARTIFACT_RES
             for m in [pat.search("The review session filed the frozen finding list.")] if m]
    check("F037 a real stage note is still caught", bool(hits2), hits2)
    check("F037 the pipeline's own ledger is still caught",
          any(pat.search("the pipeline's own ledger")
              for _label, pat in pp.INTERNAL_ARTIFACT_RES))


# ---------------------------------------------------------------- F046
def test_f046_soft_deletions_binding() -> None:
    print("\n== F046: a record without the soft key is bound to its prompt ==")
    ctx = FakeCtx(cfg={"soft_deletions": True})
    rec_missing = {"content_edit_policy": {"insertions": True, "deletions": True,
                                           "prefer_rewrite_over_deletion": True}}
    check("F046 a policy dict without the soft key means the historical off",
          pp.soft_deletions_allowed(ctx, rec_missing) is False)
    rec_on = {"content_edit_policy": {"insertions": True, "deletions": True,
                                      "soft_deletions": True}}
    rec_off = {"content_edit_policy": {"insertions": True, "deletions": True,
                                       "soft_deletions": False}}
    check("F046 an explicit on/off still wins",
          pp.soft_deletions_allowed(ctx, rec_on) is True
          and pp.soft_deletions_allowed(ctx, rec_off) is False)
    check("F046 a record with no policy at all keeps the live fallback",
          pp.soft_deletions_allowed(ctx, {"id": "r1"}) is True)


# ---------------------------------------------------------------- F047
def test_f047_token_regex() -> None:
    print("\n== F047: an uppercase trailing identity letter is not a version token ==")
    for name, want in (("Appendix_A", "Appendix_A"), ("Figure_B", "Figure_B"),
                       ("sample-A", "sample-A"), ("main-a", "main"),
                       ("main-v2", "main"), ("main-4f3a9c1", "main")):
        got = pp.DOC_TOKEN_RE.sub("", name)
        check(f"F047 {name} -> {want}", got == want, got)


# ---------------------------------------------------------------- F048
def test_f048_absent_pristine_feedback_area() -> None:
    print("\n== F048: a candidate may not create an absent feedback area ==")
    tmp = scratch("f048_")
    pristine = tmp / "pristine"
    pristine.mkdir()
    cand = tmp / "cand"
    write(cand / "human_review_feedback" / "fabricated.md", "made up")
    ctx = FakeCtx(pristine=pristine)
    warns: list = []
    res = pp.enforce_readonly_feedback_area(ctx, cand, warns)
    check("F048 the fabricated feedback area is dropped",
          not (cand / "human_review_feedback" / "fabricated.md").exists(),
          res)
    check("F048 the drop is recorded as a failure",
          bool(res.get("dropped")) and bool(res.get("failures")), res)
    check("F048 the operator is warned", bool(warns), warns)


# ---------------------------------------------------------------- F061
def test_f061_latex_comment_order() -> None:
    print("\n== F061: comments are stripped before verbatim bodies ==")
    tmp = scratch("f061_")
    write(tmp / "a.tex",
          "% \\begin{verbatim}\n\\documentclass{article}\n% \\end{verbatim}\n")
    check("F061 a real \\documentclass between commented-out verbatim markers is a root",
          pp.latex_root_documents(tmp) == ["a.tex"], pp.latex_root_documents(tmp))
    tmp2 = scratch("f061b_")
    write(tmp2 / "b.tex",
          "\\begin{verbatim}\n\\documentclass{article}\n\\end{verbatim}\n")
    check("F061 a \\documentclass inside a real verbatim body is not a root",
          pp.latex_root_documents(tmp2) == [], pp.latex_root_documents(tmp2))


# ---------------------------------------------------------------- F073
def test_f073_non_numeric_claim_held() -> None:
    print("\n== F073: a non-numeric claim with a dangling pointer is held ==")
    text = "The treatment improved survival, as described in raw_data/survival.tsv.\n"
    pats = pp._pkg2_area_patterns(["raw_data", "code"])
    idx = ({"x"}, set(), {}, {}, ())
    spans = pp.pkg2_reference_spans(text, pats, idx)
    new, removed, structural, held = pp._drop_reference_sentences_text(text, spans)
    check("F073 the claim sentence is not deleted",
          removed == [] and new == text and bool(held), (removed, held))
    pointer = "See figures/fig1.png for the effect.\n"
    spans2 = pp.pkg2_reference_spans(pointer,
                                     pp._pkg2_area_patterns(["figures"]), idx)
    _n2, removed2, _s2, _h2 = pp._drop_reference_sentences_text(pointer, spans2)
    check("F073 a pointer-only sentence is still removed", bool(removed2), removed2)


# ---------------------------------------------------------------- F077
def test_f077_reference_continuations() -> None:
    print("\n== F077: a multi-paragraph reference keeps every continuation ==")
    paras = ["References", "1.", "Nurk, S. et al. The complete sequence",
             "of a human genome. Science 372,", "984 (2021). doi:10.1126/science.abj6987"]
    got = pp._numbered_reference_titles(paras)
    entry = got.get(1, "")
    check("F077 the whole entry is joined", "984 (2021)" in entry and "doi:" in entry,
          entry)
    one = pp._numbered_reference_titles(
        ["References", "1. Nurk, S. et al. Title. Science 372, 984 (2021)."])
    check("F077 a one-line entry still parses", 1 in one and "984" in one.get(1, ""), one)
    # A one-line entry can also run over the next paragraph; the old branch
    # cleared `current`, so that continuation was dropped (F077 follow-up).
    one_cont = pp._numbered_reference_titles(
        ["References", "1. Nurk, S. et al. The complete sequence",
         "of a human genome. Science 372, 984 (2021)."])
    check("F077 a one-line entry keeps its continuation paragraph",
          "of a human genome" in one_cont.get(1, "")
          and "984 (2021)" in one_cont.get(1, ""), one_cont)
    two_entries = pp._numbered_reference_titles(
        ["References", "1. Nurk, S. et al. Title A. Science 1, 1 (2021).",
         "2. Smith, J. et al. Title B. Nature 2, 2 (2022)."])
    check("F077 a following one-line entry is not swallowed by the previous one",
          "Title A" in two_entries.get(1, "")
          and "Title B" in two_entries.get(2, ""), two_entries)
    body = pp._numbered_reference_titles(
        ["Introduction", "1. First body item", "continued body prose"])
    check("F077 a numbered body list outside a references section is not an entry",
          body == {}, body)


# ---------------------------------------------------------------- F084
def test_f084_dir_size_symlink() -> None:
    print("\n== F084: dir_size does not count a symlink target ==")
    tmp = scratch("f084_")
    tree = tmp / "sandbox"
    write(tree / "small.txt", "0123456789")
    outside = write(tmp / "outside.bin", "x" * 200000)
    link = tree / "huge-link.bin"
    try:
        link.symlink_to(outside)
    except OSError as e:                                       # pragma: no cover
        check("F084 symlink fixture could be created", False, str(e))
        return
    size = pp.dir_size(tree)
    check("F084 only the real file is counted", size == 10, size)


# ---------------------------------------------------------------- F096
def test_f096_numeric_ledger_ids() -> None:
    print("\n== F096: numeric ledger ids are read by every reader ==")
    rows = [{"id": 1, "verdict": "confirmed",
             "rationale": "checked the claim at line 2", "evidence": "quote"}]
    check("F096 row counts read a numeric id",
          pp._ledger_row_counts(rows, ["1"]) == {"1": 1},
          pp._ledger_row_counts(rows, ["1"]))
    check("F096 the verdict map reads a numeric id",
          bool(pp._ledger_verdict_map(rows, ["1"])), pp._ledger_verdict_map(rows, ["1"]))
    bare = [{"id": 2, "verdict": "confirmed"}]
    check("F096 the explanation check reads a numeric id",
          pp._ledger_rows_without_explanation(bare, ["2"]) == {"2": ["rationale", "evidence"]},
          pp._ledger_rows_without_explanation(bare, ["2"]))
    check("F096 the disposed set reads a numeric id",
          pp.ledger_disposed_ids(rows, ["1"]) == {"1"},
          pp.ledger_disposed_ids(rows, ["1"]))
    final_rows = [{"id": 3, "final_status": "fixed"}]
    check("F096 the removal-accounting final-status map reads a numeric id",
          pp.ledger_final_status_map(final_rows, ["3"]) == {"3": "fixed"},
          pp.ledger_final_status_map(final_rows, ["3"]))
    # The named-id reader was the one ledger reader the first F096 fix missed;
    # a numeric row / plain numeric id list must name the frozen id (F096
    # follow-up), and a complete numeric-ledger must pass the postcheck.
    check("F096 the named-id reader reads a numeric row id",
          pp.ledger_named_ids(rows, ["1"]) == {"1"},
          pp.ledger_named_ids(rows, ["1"]))
    check("F096 a plain numeric id list names the frozen id",
          pp.ledger_named_ids([1], ["1"]) == {"1"}, pp.ledger_named_ids([1], ["1"]))
    pkg = scratch("f096_ledger_") / "revised"
    write(pkg / "revision_report.json",
          '[{"id": 1, "verdict": "confirmed", "rationale": "checked the claim", '
          '"evidence": "main.md:4 quote"}]')
    errs, _warns = pp.revision_ledger_problems(pkg, ["1"], 1)
    check("F096 a complete numeric-id ledger passes revision_ledger_problems",
          not errs, errs)
    write(pkg / "revision_report.json",
          '[{"id": 2, "verdict": "confirmed", "rationale": "checked the claim", '
          '"evidence": "main.md:4 quote"}]')
    errs2, _warns2 = pp.revision_ledger_problems(pkg, ["1"], 1)
    check("F096 a ledger naming a different id still fails",
          bool(errs2) and "does not name" in errs2[0], errs2)


def main() -> int:
    test_f014_revision_repair_reported()
    test_f016_adopted_checks_complete()
    test_f020_audit_drop_needs_evidence()
    test_f028_unreadable_feedback_file()
    test_f031_todo_inside_prose_is_a_claim()
    test_f035_legacy_dedup_default()
    test_f037_stage_note_precision()
    test_f046_soft_deletions_binding()
    test_f047_token_regex()
    test_f048_absent_pristine_feedback_area()
    test_f061_latex_comment_order()
    test_f073_non_numeric_claim_held()
    test_f077_reference_continuations()
    test_f084_dir_size_symlink()
    test_f096_numeric_ledger_ids()
    if FAILS:
        print(f"\n{len(FAILS)} fix-bugs check(s) FAILED")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("\nAll fix-bugs checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

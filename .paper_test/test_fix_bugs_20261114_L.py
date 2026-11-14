#!/usr/bin/env python3
"""Regression checks for the group-L stage-quality fixes (fix_bugs 20261114).

Run:  conda run -n paper-refine-test python .paper_test/test_fix_bugs_20261114_L.py

Pinned here (all in paper_pipeline_parts/p07_stage_quality_journal.py):
  F125 the integration ledger gate requires a non-empty `verdict` (edit class)
  F126 the `re_validation` header spelling is a real column, not a legacy table
  F127 the integrate pre-flight runs the postcheck's Rule 1B checks
  F128 an audit coverage cell must name an object/basis, not be a bare verb
  F129 the split-review merge keeps a differing severity/category classification
  F130 zero-padded language-pass ids (L01) normalise to L1
  F131 every seeded concern id is rendered into the feedback prompt
  F132 a separator-only `source` cannot silently skip the quote binding
  F133 a heading+prose text block is seeded for the deletion audit
  F134 an `edit` with both spans empty proves nothing
  F135 a missing package fails the strict content policy instead of passing
  F136 the scoped finding list validates severity and category
  F137 the judge FMT-CL1 gate is outside the broad code-side `try`
  F138 a `remove` change still needs its `location`
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_fix_bugs_20261114_L",
                                              str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["paper_fix_bugs_20261114_L"] = pp
spec.loader.exec_module(pp)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def ledger(text: str, donors=("a1",)) -> dict:
    out = scratch("fbL_led_") / "integrated"
    out.mkdir()
    write(out / "DIFF_LEDGER.md", text)
    return pp.integration_ledger_report(out, list(donors), False)


# ---------------------------------------------------------------- F125 / F126
def test_integration_ledger_contract() -> None:
    print("\n== F125/F126: the DIFF_LEDGER Rule 1B gate ==")
    no_verdict = ("| donor | artifact | size | finding effect | revalidated |\n"
                  "|---|---|---|---|---|\n"
                  "| a1 | work/diffs/a.md | small | preserves F-001 | confirmed |\n")
    rep = ledger(no_verdict)
    check("F125 a ledger with no `verdict` column is reported",
          bool(rep.get("missing_verdict")), str(rep))
    blank = ("| donor | artifact | size | verdict | finding effect | revalidated |\n"
             "|---|---|---|---|---|---|\n"
             "| a1 | work/diffs/a.md | small |  | preserves F-001 | confirmed |\n")
    check("F125 a blank `verdict` cell is reported",
          bool(ledger(blank).get("missing_verdict")) is True)
    good = ("| donor | artifact | size | verdict | finding effect | revalidated |\n"
            "|---|---|---|---|---|---|\n"
            "| a1 | work/diffs/a.md | small | keep-self | preserves F-001 | rejected |\n")
    check("F125 a fully specified ledger is clean",
          ledger(good).get("missing_verdict") == [])
    alt = ("| donor | artifact | size | verdict | finding effect | re_validation |\n"
           "|---|---|---|---|---|---|\n"
           "| a1 | work/diffs/a.md | small | port | preserves F-001 | confirmed |\n")
    rep_alt = ledger(alt)
    check("F126 a `re_validation` port row is not a legacy/no-column ledger",
          rep_alt["legacy_no_revalidated"] is False and rep_alt["legacy_ports"] is False
          and rep_alt["invalid_ports"] == [], str(rep_alt))


# ---------------------------------------------------------------- F127
def test_integrate_preflight_parity() -> None:
    print("\n== F127: the integrate pre-flight applies the postcheck's Rule 1B checks ==")
    sb = scratch("fbL_selfcheck_")
    out = sb / "integrated"
    (out / "work").mkdir(parents=True)
    write(out / "DIFF_LEDGER.md",
          "| donor | artifact | size | verdict | finding effect | revalidated |\n"
          "|---|---|---|---|---|---|\n"
          "| w2 | work/diffs/a.md | small | port | preserves F-001 |  |\n")
    rep = pp.integration_ledger_report(out, ["w2"], False)
    _ok, errs, _warns = pp.sandbox_selfcheck(sb, "integrate", "r1_i1", 1)
    check("F127 the postcheck's own detector flags the unverified port",
          bool(rep["invalid_ports"]), str(rep))
    check("F127 the pre-flight reports the same unverified port",
          any("revalidated" in e for e in errs), str(errs))


# ---------------------------------------------------------------- F128
def test_audit_disposition_filler() -> None:
    print("\n== F128: a bare audit coverage verb is filler ==")
    for text in ("checked", "confirmed", "verified the", "re-derived"):
        check(f"F128 {text!r} is refused", pp._audit_disposition_ok(text) is False)
    for text in ("the sweep was re-derived against the corpus",
                 "confirmed by re-opening every cited artifact",
                 "checked M1-M36 against the corpus", "3 findings",
                 "clean -- basis: artifacts/M1.md"):
        check(f"F128 {text[:38]!r} is accepted", pp._audit_disposition_ok(text) is True)


# ---------------------------------------------------------------- F129
def test_split_merge_classification() -> None:
    print("\n== F129: split-review merge keeps a differing classification ==")
    d = scratch("fbL_split_")
    a, b = d / "a", d / "b"
    for s in (a, b):
        (s / "guided_review" / "round2").mkdir(parents=True)
    row = {"id": "F-001", "check": "M1", "location": "main.md:1",
           "evidence": "a sentence about the thing", "category": 1}
    write(a / "guided_review" / "findings.json",
          json.dumps({"findings": [dict(row, severity="Major")]}))
    write(b / "guided_review" / "findings.json",
          json.dumps({"findings": [dict(row, severity="Critical")]}))
    for s in (a, b):
        write(s / "guided_review" / "round2" / "findings_extra.json",
              json.dumps({"findings": []}))

    class Ctx:
        cfg = {"review_split": "phases"}

        def run(self, _rid):
            return {"sandbox": str(a)}

        def sandbox_of(self, rec):
            return Path(rec["sandbox"])

    merged = pp.merge_review_parts(Ctx(), {"round": 1, "sandbox": str(b)})
    rows = json.loads((b / "guided_review" / "findings.json").read_text())["findings"]
    severities = sorted(str(r.get("severity")) for r in rows)
    check("F129 the worse classification survives the merge",
          severities == ["Critical", "Major"], str(severities))
    check("F129 the classification disagreement is recorded",
          bool(merged.get("classification_conflicts")), str(merged))


# ---------------------------------------------------------------- F130
def test_language_pass_ids() -> None:
    print("\n== F130: zero-padded language-pass ids ==")
    pkg = scratch("fbL_lang_")
    rows = "\n".join(f"| L{i:02d} | 0 | no change found |" for i in range(1, 12))
    write(pkg / "work" / "R6_language.md",
          "| step | rows changed | note |\n|---|---|---|\n" + rows + "\n")
    rep = pp.language_pass_report(pkg)
    check("F130 an L01-L11 coverage table covers all eleven steps",
          rep["missing"] == [] and rep["steps_seen"] == [f"L{i}" for i in range(1, 12)],
          str(rep))


# ---------------------------------------------------------------- F131
def test_seed_ids_shown() -> None:
    print("\n== F131: every seeded concern id reaches the prompt ==")
    sb = scratch("fbL_seed_")
    cands = [{"seed_id": f"S{i:03d}", "source": "editor_letter.txt",
              "heading": f"Heading {i}", "excerpt": "some words"} for i in range(1, 82)]
    write(sb / "feedback" / "CONCERN_SEED.json", json.dumps({"candidates": cands}))
    text = pp._journal_seed_text(None, sb)
    shown = set(re.findall(r"\[S(\d{3})\]", text))
    check("F131 all 81 seeded ids are rendered", len(shown) == 81 and "081" in shown,
          f"{len(shown)} shown")


# ---------------------------------------------------------------- F132
def test_concern_source_separators() -> None:
    print("\n== F132: a separator-only `source` cannot skip the quote binding ==")
    sb = scratch("fbL_concern_")
    for d in ("feedback/files", "feedback/text", "feedback/llm/files",
              "feedback/llm/text", "concerns"):
        (sb / d).mkdir(parents=True)
    write(sb / "feedback/files/letter.txt", "x\n")
    write(sb / "feedback/text/letter.txt.txt",
          "The sample size is too small for the claim.\n")
    row = {"id": "R1-1", "source": ";", "author": "Reviewer 1",
           "quote": "a completely invented sentence that appears nowhere in the letter at all",
           "summary": "s", "action": "text", "manuscript_location": None,
           "disposition": "to-fix", "evidence_needed": ""}
    write(sb / "concerns/JF_concerns.json", json.dumps({"concerns": [row]}))
    write(sb / "concerns/JF_concerns.md", "| id |\n|---|\n| R1-1 |\n")
    errs, _warns = [], []
    pp.journal_ledger_problems(None, sb, errs, _warns)
    check("F132 the separator-only source is an error",
          any("names no feedback file" in e for e in errs), str(errs))


# ---------------------------------------------------------------- F133
def test_deletion_audit_heading_blocks() -> None:
    print("\n== F133: a heading+prose text block reaches the deletion audit ==")
    d = scratch("fbL_del_")
    base, rev = d / "base", d / "revised"
    base.mkdir()
    rev.mkdir()
    write(base / "manuscript.md",
          "# Methods\n"
          "The treated group received 50 mM of the compound every morning for six weeks.\n\n"
          "# Results\n"
          "Treated plants were significantly taller than the control group in this trial.\n")
    write(rev / "manuscript.md",
          "# Results\n"
          "Treated plants were significantly taller than the control group in this trial.\n")
    paras = pp.deletion_audit_paragraphs(base)
    rows = pp.deletion_audit_rows(base, rev)
    check("F133 the deleted Methods prose is seeded",
          any("treated group received" in str(p[2]).lower() for p in paras), str(paras))
    check("F133 the deleted Methods prose becomes a deletion row",
          any("treated group received" in str(r.get("paragraph", "")).lower()
              for r in rows), str(rows))
    # The helper still refuses a STANDALONE heading paragraph (DOCX shape).
    check("F133 a standalone heading is still not a deletion row",
          pp._deleted_para_candidate("# Results") == "")


# ---------------------------------------------------------------- F134 / F138
def test_response_spans() -> None:
    print("\n== F134/F138: the response map's change gates ==")
    sb = scratch("fbL_resp_")
    (sb / "previous_package").mkdir()
    (sb / "target").mkdir()
    write(sb / "previous_package/manuscript.md", "The old sentence was here.\n")
    write(sb / "target/manuscript.md",
          "# Methods\n\nThe revised sentence is now here.\n")
    write(sb / "previous_package/obsolete.md", "the obsolete appendix said things\n")
    empty_edit = [{"id": "C1", "changes": [
        {"file": "manuscript.md", "location": "Methods", "operation": "edit",
         "before": "", "after": ""}]}]
    probs = pp._response_change_span_problems(sb, sb / "target", empty_edit)
    check("F134 an edit with both spans empty is reported", bool(probs), str(probs))
    ok_edit = [{"id": "C2", "changes": [
        {"file": "manuscript.md", "location": "Methods", "operation": "edit",
         "before": "", "after": "The revised sentence is now here."}]}]
    check("F134 a pure insertion still passes",
          pp._response_change_span_problems(sb, sb / "target", ok_edit) == [],
          str(pp._response_change_span_problems(sb, sb / "target", ok_edit)))
    no_loc = [{"id": "C3", "changes": [
        {"file": "obsolete.md", "location": "", "operation": "remove",
         "before": "", "after": ""}]}]
    probs_rm = pp._response_change_span_problems(sb, sb / "target", no_loc)
    check("F138 a `remove` with no location is reported", bool(probs_rm), str(probs_rm))
    loc_rm = [{"id": "C4", "changes": [
        {"file": "obsolete.md", "location": "whole file", "operation": "remove",
         "before": "", "after": ""}]}]
    check("F138 a located `remove` still passes",
          pp._response_change_span_problems(sb, sb / "target", loc_rm) == [])


# ---------------------------------------------------------------- F135
def test_content_policy_missing_package() -> None:
    print("\n== F135: a missing package does not silently disable the content policy ==")
    d = scratch("fbL_content_")
    probs = pp.content_edit_problems(None, d / "nope" / "base", d / "nope" / "cand",
                                     "revise", insertions_allowed=False,
                                     deletions_allowed=False)
    check("F135 the missing package is reported", bool(probs), str(probs))


# ---------------------------------------------------------------- F136
def test_scoped_finding_classification() -> None:
    print("\n== F136: the scoped finding list validates severity/category ==")
    sb = scratch("fbL_jf_")
    write(sb / "concerns/JF_concerns.json", json.dumps({"concerns": []}))
    write(sb / "guided_review/findings.json", json.dumps({"findings": [
        {"id": "JF-1", "check": "JF", "concern": "R1-1",
         "evidence": "a verbatim reviewer quote", "location": "main.md:1",
         "status": "resolvable", "severity": "banana", "category": 99}],
        "coverage": []}))
    write(sb / "guided_review" / "artifacts" / "JF_concerns.md", "| id |\n|---|\n")
    data = {"concerns": [{"id": "R1-1", "disposition": "to-fix"}]}
    errs, _warns, _counts = pp.concerns_finding_list_problems(sb, data)
    check("F136 an unclassifiable severity is rejected",
          any("severity" in e for e in errs), str(errs))
    check("F136 an out-of-schema category is rejected",
          any("category" in e for e in errs), str(errs))
    check("F136 a well-formed JF row still passes the classification gate",
          not any("severity" in e or "category" in e for e in
                  _jf_errors(severity="Major", category=0)))


def _jf_errors(**overrides) -> list:
    sb = scratch("fbL_jf_ok_")
    write(sb / "concerns/JF_concerns.json", json.dumps({"concerns": []}))
    row = {"id": "JF-1", "check": "JF", "concern": "R1-1",
           "evidence": "a verbatim reviewer quote", "location": "main.md:1",
           "status": "resolvable", "severity": "Major", "category": 0}
    row.update(overrides)
    write(sb / "guided_review/findings.json",
          json.dumps({"findings": [row], "coverage": []}))
    write(sb / "guided_review" / "artifacts" / "JF_concerns.md", "| id |\n|---|\n")
    errs, _warns, _counts = pp.concerns_finding_list_problems(
        sb, {"concerns": [{"id": "R1-1", "disposition": "to-fix"}]})
    return errs


# ---------------------------------------------------------------- F137
def test_judge_fmt_cl1_outside_try() -> None:
    print("\n== F137: the judge FMT-CL1 gate is outside the broad try ==")
    src = (WS / "paper_pipeline_parts" / "p07_stage_quality_journal.py").read_text(
        encoding="utf-8")
    start = src.index("def postcheck_judge(")
    end = src.index("\ndef ", start + 10)
    body = src[start:end]
    try_at = body.index("try:")
    except_at = body.index("except Exception as e:")
    cl_at = body.index("judge_cover_letter_artifact_problems(sb, cl_target)")
    check("F137 the FMT-CL1 call is not inside the broad try",
          not (try_at < cl_at < except_at), f"try={try_at} except={except_at} call={cl_at}")


def main() -> int:
    try:
        test_integration_ledger_contract()
        test_integrate_preflight_parity()
        test_audit_disposition_filler()
        test_split_merge_classification()
        test_language_pass_ids()
        test_seed_ids_shown()
        test_concern_source_separators()
        test_deletion_audit_heading_blocks()
        test_response_spans()
        test_content_policy_missing_package()
        test_scoped_finding_classification()
        test_judge_fmt_cl1_outside_try()
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} GROUP-L CHECK(S) FAILED")
        for f in FAILS:
            print("  -", f)
        return 1
    print("all group-L regression checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

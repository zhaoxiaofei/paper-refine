#!/usr/bin/env python3
"""Regression checks for the 2026-11-05 PR536 fix-bugs wave.

Each check pins one candidate the verify-findings stage kept as a true
positive (PR536-004 .. PR536-172).  The pre-fix tree fails the behavioural
checks; the prose checks fail on the pre-fix wording.  Hermetic: temporary
roots only.

Run:  python3 .paper_test/test_fix_bugs_20261105_pr536.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FAILS = []
TMPDIRS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1105pr536_pp", "paper_pipeline.py")
cc = load("fixbugs1105pr536_cc", "paper-skills/paper-review/scripts/convert_corpus.py")
pw = load("fixbugs1105pr536_pw", "pairwise_scores.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def text(rel: Path) -> str:
    return (WS / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# PR536-004 -- one ledger item per defect instance
# ---------------------------------------------------------------------------
def test_pr004_duplicate_ledger_rows() -> None:
    print("\n== PR536-004: an identical ledger row is one defect instance ==")
    row = {"tier": "correctness", "severity": "minor",
           "evidence": "the reported p value is transcribed twice", "check": "M2"}
    comp = {"resolved": [row, dict(row)], "introduced": [], "score": 1,
            "basis": "correctness"}
    check("PR536-004 two identical minor rows derive +1, not +2",
          pp.derived_comparison_score(comp) == 1, pp.derived_comparison_score(comp))
    errs, _warns = pp.judge_basis_problems(comp, "sheet", True)
    check("PR536-004 the duplicate is reported as a contract problem",
          any("duplicates an earlier ledger row" in e for e in errs), str(errs)[:300])
    # The documented padded spelling `M01` is the same frozen check as `M1`
    # (`_frozen_check_id`), so the derivation and the validator must agree on it.
    comp_padded = {"resolved": [dict(row, check="M1"), dict(row, check="M01")],
                   "introduced": [], "score": 1, "basis": "correctness"}
    check("PR536-004 the padded M01 spelling is the same instance as M1",
          pp.derived_comparison_score(comp_padded) == 1,
          pp.derived_comparison_score(comp_padded))
    errs, _warns = pp.judge_basis_problems(comp_padded, "sheet", True)
    check("PR536-004 the M1/M01 duplicate is still reported",
          any("duplicates an earlier ledger row" in e for e in errs), str(errs)[:300])


# ---------------------------------------------------------------------------
# PR536-010 -- a quote is bound to the FILE its source names
# ---------------------------------------------------------------------------
def _ledger_fixture(quote: str, source: str) -> list:
    sb = scratch("pr536ledger_")
    for d in ("concerns", "feedback/files", "feedback/text",
              "feedback/llm/files", "feedback/llm/text"):
        (sb / d).mkdir(parents=True, exist_ok=True)
    (sb / "feedback/files/human_review_feedback__a.txt").write_text("x")
    (sb / "feedback/text/human_review_feedback__a.txt.txt").write_text(
        "The sample is too small for the main claim.\n")
    (sb / "feedback/files/human_review_feedback__b.txt").write_text("x")
    (sb / "feedback/text/human_review_feedback__b.txt.txt").write_text(
        "The analysis is not reproducible from the supplement.\n")
    (sb / "feedback/CONCERN_SEED.json").write_text(json.dumps({
        "files": ["human_review_feedback/a.txt", "human_review_feedback/b.txt"],
        "llm_files": []}))
    row = {"id": "L1", "source": source, "author": "Reviewer 1", "quote": quote,
           "summary": "s", "action": "text", "manuscript_location": None,
           "disposition": "to-fix", "evidence_needed": ""}
    (sb / "concerns/JF_concerns.json").write_text(json.dumps({"concerns": [row]}))
    errs, _warns = [], []
    pp.journal_ledger_problems(None, sb, errs, _warns)
    return errs


def test_pr010_quote_wrong_file() -> None:
    print("\n== PR536-010: a quote cannot come from another file in the stream ==")
    errs = _ledger_fixture("The analysis is not reproducible from the supplement.",
                           "human_review_feedback/a.txt")
    check("PR536-010 a quote from b.txt fails when the source names a.txt",
          any("not verbatim" in e and "a.txt" in e for e in errs), str(errs)[:400])
    errs = _ledger_fixture("The sample is too small for the main claim.",
                           "human_review_feedback/a.txt")
    check("PR536-010 the named file's own quote passes", errs == [], str(errs)[:400])
    errs = _ledger_fixture("The sample is too small for the main claim.",
                           "a.txt")
    check("PR536-010 the documented basename form still binds", errs == [], str(errs)[:400])
    errs = _ledger_fixture("The sample is too small for the main claim.",
                           "not-a-staged-file.txt")
    check("PR536-010 a fabricated source is rejected",
          any("does not name any file" in e for e in errs), str(errs)[:400])


def _sibling_ledger_fixture(source: str, quote: str) -> list:
    """Two staged files with the SAME basename in different subdirectories."""
    sb = scratch("pr536sibling_")
    for d in ("concerns", "feedback/files", "feedback/text",
              "feedback/llm/files", "feedback/llm/text"):
        (sb / d).mkdir(parents=True, exist_ok=True)
    (sb / "feedback/files/human_review_feedback__a__report.txt").write_text("x")
    (sb / "feedback/files/human_review_feedback__b__report.txt").write_text("x")
    (sb / "feedback/text/human_review_feedback__a__report.txt.txt").write_text(
        "The sample is too small for the main claim.\n")
    (sb / "feedback/text/human_review_feedback__b__report.txt.txt").write_text(
        "The analysis is not reproducible from the supplement.\n")
    (sb / "feedback/CONCERN_SEED.json").write_text(json.dumps({
        "files": ["human_review_feedback/a/report.txt",
                  "human_review_feedback/b/report.txt"], "llm_files": []}))
    row = {"id": "L1", "source": source, "author": "Reviewer 1", "quote": quote,
           "summary": "s", "action": "text", "manuscript_location": None,
           "disposition": "to-fix", "evidence_needed": ""}
    (sb / "concerns/JF_concerns.json").write_text(json.dumps({"concerns": [row]}))
    errs, _warns = [], []
    pp.journal_ledger_problems(None, sb, errs, _warns)
    return errs


def test_pr010_sibling_basename() -> None:
    print("\n== PR536-010: a same-basename sibling cannot satisfy a full-path source ==")
    errs = _sibling_ledger_fixture("human_review_feedback/a/report.txt",
                                   "The analysis is not reproducible from the supplement.")
    check("PR536-010 a quote from b/report.txt fails when the source names a/report.txt",
          any("not verbatim" in e for e in errs), str(errs)[:400])
    errs = _sibling_ledger_fixture("human_review_feedback/b/report.txt",
                                   "The sample is too small for the main claim.")
    check("PR536-010 the mirror direction fails too",
          any("not verbatim" in e for e in errs), str(errs)[:400])
    errs = _sibling_ledger_fixture("human_review_feedback/a/report.txt",
                                   "The sample is too small for the main claim.")
    check("PR536-010 the named sibling's own quote still passes", errs == [], str(errs)[:400])



# ---------------------------------------------------------------------------
# PR536-012 -- a renamed Python module keeps its binding
# ---------------------------------------------------------------------------
def test_pr012_python_import_binding() -> None:
    print("\n== PR536-012: anonymized Python imports keep the module binding ==")
    d = scratch("pr536import_")
    (d / "main.py").write_text("import helper\nprint(helper.value)\n")
    (d / "helper.py").write_text("value = 42\n")
    data, _notes = pp._transform_view_file(
        "main.py", d / "main.py", {"main.py": "f1.py", "helper.py": "f2.py"})
    (d / "f1.py").write_bytes(data)
    (d / "f2.py").write_text("value = 42\n")
    r = subprocess.run([sys.executable, str(d / "f1.py")], capture_output=True,
                       text=True, cwd=d)
    check("PR536-012 the renamed import keeps the `helper` binding and still runs",
          r.returncode == 0 and r.stdout.strip() == "42"
          and b"helper = f2" in data,
          f"rc={r.returncode} out={r.stdout!r} src={data!r} err={r.stderr[-200:]!r}")
    (d / "main2.py").write_text("from helper import value\nprint(value)\n")
    data2, _notes = pp._transform_view_file(
        "main2.py", d / "main2.py", {"main2.py": "f3.py", "helper.py": "f2.py"})
    check("PR536-012 a `from` import is rewritten without an invalid alias",
          b"from f2 import" in data2 and b" as " not in data2, data2)


# ---------------------------------------------------------------------------
# PR536-018 -- split discovery ids are namespaced
# ---------------------------------------------------------------------------
def test_pr018_split_discovery_ids() -> None:
    print("\n== PR536-018: two split parts cannot share one discovery id ==")
    d = scratch("pr536split_")
    a, b = d / "a", d / "b"
    for sb in (a, b):
        (sb / "guided_review/round2").mkdir(parents=True)
    (a / "guided_review/findings.json").write_text(json.dumps({"findings": [
        {"id": "FA-1", "location": "x", "evidence": "e"}]}))
    (b / "guided_review/findings.json").write_text(json.dumps({"findings": [
        {"id": "FB-1", "location": "y", "evidence": "f"}]}))
    (a / "guided_review/round2/findings_extra.json").write_text(json.dumps({
        "findings": [{"id": "X-001", "location": "a", "evidence": "A"}]}))
    (b / "guided_review/round2/findings_extra.json").write_text(json.dumps({
        "findings": [{"id": "X-001", "location": "b", "evidence": "B",
                      "check": "X-001"}],
        "coverage": [{"check": "X-001"}]}))

    class Ctx:
        cfg = {"review_split": "phases"}

        def run(self, _rid):
            return {"sandbox": str(a)}

        def sandbox_of(self, rec):
            return Path(rec["sandbox"])

    merged = pp.merge_review_parts(Ctx(), {"round": 1, "sandbox": str(b)})
    extra = json.loads((b / "guided_review/round2/findings_extra.json").read_text())
    ids = [f["id"] for f in extra["findings"]]
    new_id = merged.get("x_id_remap", {}).get("X-001")
    check("PR536-018 both observations survive under distinct ids",
          len(ids) == 2 and len(set(ids)) == 2 and new_id == ids[1],
          f"ids={ids} merge={merged}")
    check("PR536-018 the B row's references are rewritten with its id",
          bool(new_id) and extra["findings"][1].get("check") == new_id
          and extra["coverage"][-1].get("check") == new_id, extra)


# ---------------------------------------------------------------------------
# PR536-019 -- cold-start findings carry check and status
# ---------------------------------------------------------------------------
def test_pr019_cold_start_shape() -> None:
    print("\n== PR536-019: a cold-start finding needs its class label and status ==")
    sb = scratch("pr536cold_")
    (sb / "cold_start_review").mkdir()
    (sb / "cold_start_review/findings_cold_start_review.json").write_text(json.dumps({
        "checked": [{"area": "docs", "examined": 1, "findings": 2}],
        "findings": [
            {"id": "X-901", "location": "a", "evidence": "e", "explanation": "x",
             "severity": "Major", "category": 1, "status": "made-up"},
            {"id": "X-902", "location": "b", "evidence": "e", "explanation": "x",
             "severity": "Major", "category": 1, "check": "stale sidecar",
             "status": "resolvable"}]}))
    errs, _warns, _findings = pp._cold_start_contract_problems(sb)
    check("PR536-019 a missing check and an invented status are rejected",
          any("no check" in e for e in errs) and any("made-up" in e for e in errs),
          str(errs)[:400])
    check("PR536-019 the valid sibling row still passes",
          not any("X-902" in e for e in errs), str(errs)[:400])


# ---------------------------------------------------------------------------
# PR536-021 -- contradictory duplicate dispositions
# ---------------------------------------------------------------------------
def test_pr021_conflicting_ledger() -> None:
    print("\n== PR536-021: one finding id cannot be fixed AND discarded ==")
    d = scratch("pr536rev_")
    pkg = d / "revised"
    pkg.mkdir()
    (pkg / "revision_report.json").write_text(json.dumps([
        {"id": "F-001", "status": "fixed", "rationale": "a"},
        {"id": "F-001", "status": "discarded", "rationale": "b"}]))
    errs, _warns = pp.revision_ledger_problems(pkg, ["F-001"], 1)
    check("PR536-021 conflicting verdicts fail the revise gate",
          any("CONFLICTING dispositions" in e and "F-001" in e for e in errs),
          str(errs)[:400])


# ---------------------------------------------------------------------------
# PR536-030 -- a response change path names a file, not a directory
# ---------------------------------------------------------------------------
def test_pr030_response_directory_path() -> None:
    print("\n== PR536-030: `figures/` is not a changed file ==")
    d = scratch("pr536resp_")
    sb, src = d / "r1_response", d / "r1_concerns"
    (sb / "response").mkdir(parents=True)
    (sb / "target/figures").mkdir(parents=True)
    (src / "concerns").mkdir(parents=True)
    (src / "concerns/JF_concerns.json").write_text(json.dumps({"concerns": [{
        "id": "C1", "quote": "The treated group improved markedly in this study.",
        "summary": "x"}]}))
    (sb / "response/response_map.json").write_text(json.dumps({"rows": [{
        "id": "C1", "status": "addressed", "response": "We revised it.",
        "changes": [{"file": "figures/", "location": "x",
                     "before": "a", "after": "b"}]}]}))
    (sb / "response/RESPONSE_TO_REVIEWERS.md").write_text(
        '## C1 - x\n**Comment:** "The treated group improved markedly in this study."'
        '\n**Response:** ok\n')

    class Ctx:
        cfg = {}

        def sandbox_of(self, rec):
            return sb if rec.get("id") == "r1_response" else src

        def run(self, _rid):
            return {"id": "r1_concerns", "sandbox": str(src)}

    saved = {}
    for name in ("original_submission_staging_problems", "structured_output_problems",
                 "inherited_structured_output_notes", "input_mismatches", "_marker_checks"):
        saved[name] = getattr(pp, name)
        setattr(pp, name, (lambda *a, **k: None) if name == "_marker_checks"
                else (lambda *a, **k: []))
    try:
        _ok, errs, _warns, _x = pp.postcheck_response(
            Ctx(), {"id": "r1_response", "round": 1, "kind": "response"})
        check("PR536-030 a directory cannot stand in for a changed file",
              any("figures/" in e and "does not exist" in e for e in errs),
              str(errs)[:400])
    finally:
        for name, fn in saved.items():
            setattr(pp, name, fn)


# ---------------------------------------------------------------------------
# PR536-035/036/037 -- the response quote and heading parsers
# ---------------------------------------------------------------------------
def test_pr035_036_037_response_parsers() -> None:
    print("\n== PR536-035/036/037: verbatim, complete-id and fenced-example gates ==")
    check("PR536-035 a case change is not verbatim",
          not pp.response_comment_is_verbatim("US", "us"))
    check("PR536-035 a word fragment is not verbatim",
          not pp.response_comment_is_verbatim("valid", "invalid"))
    check("PR536-035 a real sub-excerpt still passes",
          pp.response_comment_is_verbatim(
              "sample size is too small", "The sample size is too small for the claims."))
    check("PR536-036 R1-1-extra is not a second R1-1 heading",
          pp.response_heading_occurrences("R1-1", "## R1-1-extra\n") == 0)
    check("PR536-036 a genuine duplicate heading is counted",
          pp.response_heading_occurrences("R1-1", "## R1-1 -- a\n## R1-1 -- b\n") == 2)
    fenced = '```\n## R1-1\n**Comment:** "quoted"\n```\n'
    check("PR536-037 a fenced example supplies no Comment quote",
          pp.response_comment_quotes(fenced) == {}, pp.response_comment_quotes(fenced))
    check("PR536-037 a real block still supplies its quote",
          pp.response_comment_quotes('## R1-1\n**Comment:** "quoted"\n')
          == {"R1-1": "quoted"})


# ---------------------------------------------------------------------------
# PR536-038 -- colliding feedback labels keep both files
# ---------------------------------------------------------------------------
def test_pr038_feedback_staging_collision() -> None:
    print("\n== PR536-038: a/b.txt and a__b.txt do not overwrite each other ==")
    corpus = scratch("pr536stage_") / "submission"
    (corpus / "human_review_feedback/a").mkdir(parents=True)
    (corpus / "human_review_feedback/a/b.txt").write_text("FIRST source text.\n")
    (corpus / "human_review_feedback/a__b.txt").write_text("SECOND source text.\n")

    class Ctx:
        cfg = {}
        pristine = corpus

    sb = scratch("pr536stage_sb_")
    saved_prev, saved_orig = pp.journal_previous_responses, pp._stage_original_submission
    pp.journal_previous_responses = lambda ctx: []
    pp._stage_original_submission = lambda ctx, sb: None
    try:
        pp._write_journal_feedback_inputs(Ctx(), sb)
    finally:
        pp.journal_previous_responses = saved_prev
        pp._stage_original_submission = saved_orig
    staged = json.loads((sb / "feedback/CONCERN_SEED.json").read_text())["staged"]
    texts = {p.name: p.read_text() for p in (sb / "feedback/text").iterdir()}
    check("PR536-038 both staged files exist under distinct names",
          len(list((sb / "feedback/files").iterdir())) == 2, str(staged))
    check("PR536-038 both converted texts survive byte-for-byte content",
          any("FIRST" in t for t in texts.values())
          and any("SECOND" in t for t in texts.values()), str(texts))
    (sb / "concerns").mkdir()
    row = {"id": "L1", "source": "human_review_feedback/a/b.txt",
           "author": "Reviewer 1", "quote": "FIRST source text.",
           "summary": "s", "action": "text", "manuscript_location": None,
           "disposition": "to-fix", "evidence_needed": ""}
    (sb / "concerns/JF_concerns.json").write_text(json.dumps({"concerns": [row]}))
    errs, _warns = [], []
    pp.journal_ledger_problems(None, sb, errs, _warns)
    check("PR536-038 the first source's quote still resolves after staging",
          not any("not verbatim" in e for e in errs), str(errs)[:400])


# ---------------------------------------------------------------------------
# PR536-044 -- the judge continuation is blind and names scores.json
# ---------------------------------------------------------------------------
def test_pr044_judge_continuation() -> None:
    print("\n== PR536-044: the judge continuation stays blind ==")
    p = pp.resume_prompt({"id": "judge_t1abc", "kind": "judge", "round": 3},
                         ["bad sheet"], "unfinished", 0)
    run_line = [ln for ln in p.splitlines() if ln.startswith("Run:")]
    check("PR536-044 the round is not emitted to the judge",
          run_line and "round:" not in run_line[0], str(run_line))
    check("PR536-044 scores.json is named as the completion signal",
          "scores.json" in p and "only completion signal" not in p)
    revise = pp.resume_prompt({"id": "r1_a2_revise", "kind": "revise", "round": 3},
                              [], "x", 0)
    check("PR536-044 a non-judge continuation still names the round",
          "round: 3" in revise)


# ---------------------------------------------------------------------------
# PR536-066 -- a dropped X id still gets a ledger row
# ---------------------------------------------------------------------------
def test_pr066_dropped_x_row() -> None:
    print("\n== PR536-066: every dropped X id is accounted for ==")
    note = pp._discovery_dropped_note([("X-004", "not a defect")])
    check("PR536-066 the dropped note REQUIRES one row per dropped id",
          "one explicit `dropped -- not in force` row per dropped id" in note
          and "if the ledger needs a row" not in note, note[:400])


# ---------------------------------------------------------------------------
# PR536-078 -- the ledger schema can name the llm-only mode
# ---------------------------------------------------------------------------
def test_pr078_ledger_schema_llm() -> None:
    print("\n== PR536-078: the feedback schema names the active llm mode ==")
    check("PR536-078 the schema mode enum includes llm",
          "|llm>" in pp.JOURNAL_LEDGER_SCHEMA, pp.JOURNAL_LEDGER_SCHEMA[:200])


# ---------------------------------------------------------------------------
# PR536-093 / PR536-105 -- one severity rung per fabrication; M15 undecidable
# ---------------------------------------------------------------------------
def test_pr093_105_sweep_rules() -> None:
    print("\n== PR536-093/105: severity and M15 rules are decidable ==")
    sweeps = text(Path("paper-skills/paper-review/references/sweeps.md"))
    prompt = text(Path("paper-skills/prompts/identify_issues.prompt.md"))
    for name, blob in (("sweeps.md", sweeps), ("identify_issues.prompt.md", prompt)):
        check(f"PR536-093 {name}: a fabrication's rung depends on what rests on it",
              "a fabricated result or citation that is presented as\n  established AND that "
              "the submission's conclusion rests on" in blob
              and "a localized fabrication is Critical; the\n  same fabrication carrying the "
                  "conclusion is Fatal" in blob, name)
        check(f"PR536-105 {name}: a placeholder cannot prove a numeric mismatch",
              "prose total ≠ column sum, only when the sum CAN be computed" in blob
              and "including when a placeholder cell makes the sum\n  impossible" not in blob,
              name)
    # The scale is ONE text in every session. The shared defect-class block and
    # the judge's directives are what the PIPELINE's sessions are handed; leaving
    # them at the old "any fabrication presented as established is Fatal" rule
    # put two severity definitions in one prompt (and the review's own
    # `sweeps.md` supplied a third).
    for name in ("paper_pipeline_parts/p02_journal_modes.py",
                 "paper_pipeline_parts/p03_prompts.py",
                 "README.md"):
        blob = text(Path(name))
        low = blob.lower()
        check(f"PR536-093 {name}: the embedded scale carries the fabrication-reach rule",
              "fabricated result or citation" in low
              and "reach is local" in low and "conclusion rests on" in low, name)


# ---------------------------------------------------------------------------
# PR536-140 / PR536-143 -- the revise reference keeps the role contract
# ---------------------------------------------------------------------------
def test_pr140_143_revise_reference() -> None:
    print("\n== PR536-140/143: no auditor AU rows; no invented support ==")
    rules = text(Path("paper-skills/paper-revise/references/edit_rules.md"))
    check("PR536-140 E7 says the auditor generates no new finding",
          "The auditor GENERATES NO NEW FINDING" in rules
          and "may add `AU-*` findings" not in rules
          and "every `AU-*` finding is a NORMAL finding" not in rules)
    for name in ("README.md",
                 "paper-skills/paper-revise/references/edit_rules.md",
                 "paper-skills/prompts/adress_issues.prompt.md",
                 "paper_pipeline_parts/p03_prompts.py"):
        blob = text(Path(name))
        check(f"PR536-143 {name}: no instruction to invent support or a sibling",
              "give the claim its support" not in blob
              and "add the sibling the section is" not in blob
              and "record the gap for the finding-generating role" in blob, name)


# ---------------------------------------------------------------------------
# PR536-147 -- an uncached formula is not a blank cell
# ---------------------------------------------------------------------------
def test_pr147_uncached_formula() -> None:
    print("\n== PR536-147: an uncached formula is distinct from blank ==")
    formula = cc._xlsx_cell_value('r="A1"', "<f>SUM(A1:A3)</f>", [])
    blank = cc._xlsx_cell_value('r="A2"', None, [])
    check("PR536-147 the formula text is recorded",
          formula == "[uncached formula: =SUM(A1:A3)]", repr(formula))
    check("PR536-147 the formula no longer equals the blank cell",
          formula != blank and blank == "", repr((formula, blank)))
    check("PR536-147 a cached value still wins",
          cc._xlsx_cell_value('r="A3"', "<f>SUM(A1:A2)</f><v>3</v>", []) == "3")


# ---------------------------------------------------------------------------
# PR536-155/156/157 -- pairwise workbook labels and head-dump parsing
# ---------------------------------------------------------------------------
def test_pr155_workbook_labels() -> None:
    print("\n== PR536-155: CSV labels are string cells, not formulas ==")
    from openpyxl import load_workbook
    d = scratch("pr536xlsx_")
    reports = d / "cnb-demo/reports"
    reports.mkdir(parents=True)
    csv = reports / "round1_raw_scores.csv"
    csv.write_text("member,direction,opponent_id,credited,round,source_judge_run,"
                   "source_judge_index\n=1+1,own,v2,1,1,j1,1\nv2,own,=1+1,1,1,j1,1\n")
    out = d / "out.xlsx"
    r = subprocess.run([sys.executable, str(WS / "pairwise_scores.py"), str(csv),
                        "-o", str(out)], capture_output=True, text=True)
    check("PR536-155 the workbook is written", r.returncode == 0, r.stderr[-300:])
    ws = load_workbook(out).worksheets[1]
    cells = [ws["B1"], ws["A2"]]
    check("PR536-155 the untrusted labels are explicit strings",
          all(c.data_type == "s" and c.value == "=1+1" for c in cells),
          [(c.coordinate, c.value, c.data_type) for c in cells])
    # The Description sheet's index table repeats the run directory name: it is
    # the same untrusted input and cannot be allowed to become a formula.
    run = d / "=1+1"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "round1_raw_scores.csv").write_text(
        "member,direction,opponent_id,credited,round,source_judge_run,"
        "source_judge_index\na,own,b,1,1,j1,1\nb,own,a,-1,1,j1,1\n")
    out2 = d / "out2.xlsx"
    r = subprocess.run([sys.executable, str(WS / "pairwise_scores.py"), str(run),
                        "-o", str(out2)], capture_output=True, text=True)
    check("PR536-155 the run-directory workbook is written", r.returncode == 0,
          r.stderr[-300:])
    desc = load_workbook(out2)["Description"]
    rows = [row for row in desc.iter_rows() if row[0].value == "=1+1_r1"]
    check("PR536-155 the Description index cells are explicit strings",
          len(rows) == 1 and rows[0][1].value == "=1+1"
          and all(c.data_type == "s" for c in rows[0][:2]),
          [(c.value, c.data_type) for c in rows[0][:2]] if rows else "no row")


def test_pr156_157_head_dump() -> None:
    print("\n== PR536-156/157: head-dump detection and record fidelity ==")
    d = scratch("pr536head_")
    head = d / "head.txt"
    head.write_text(
        "==> a/round1_raw_scores.csv <==\n"
        "member,direction,opponent_id,credited,reason\n"
        'a,own,b,1,"line one\n\nline two"\n'
        "==> b/round1_raw_scores.csv <==\n"
        "member,direction,opponent_id,credited,reason\n"
        "b,own,a,1,ok\n")
    check("PR536-156 a dump whose header uses opponent_id is recognized",
          pw.is_head_dump(head) is True)
    blocks = list(pw.iter_head_dump(head))
    rows = pw.read_rows(blocks[0][0], blocks[0][1])
    check("PR536-157 the quoted blank line and newlines survive",
          rows[0].get("reason") == "line one\n\nline two", repr(rows[0].get("reason")))
    marker = d / "marker.txt"
    marker.write_text(
        "==> a/x.csv <==\nmember,direction,opponent_id,credited,reason\n"
        'a,own,b,1,"one\n==> fake/path <==\ntwo"\n')
    blocks = list(pw.iter_head_dump(marker))
    check("PR536-157 a marker-shaped line inside a quote is field text",
          len(blocks) == 1
          and "==> fake/path <==" in pw.read_rows(blocks[0][0], blocks[0][1])[0]["reason"],
          repr(blocks))


# ---------------------------------------------------------------------------
# PR536-158/161/162 -- corpus conversion: lossy bytes, long names, FIFOs
# ---------------------------------------------------------------------------
def test_pr158_lossy_bytes() -> None:
    print("\n== PR536-158: invalid UTF-8 is recorded, not silently replaced ==")
    p = scratch("pr536utf_") / "bad.txt"
    p.write_bytes(b"Result was 10 \xff 20\n")
    decoded, notes = cc.plain_copy(str(p))
    check("PR536-158 the replacement is reported in a note",
          "\ufffd" in decoded and any("decoding gap" in n for n in notes), str(notes))
    rec = cc.convert_one(str(p), "bad.txt")
    check("PR536-158 the file is a partial conversion, not a clean one",
          rec["status"] == "converted-partial", rec["status"])
    # A partial CONVERSION is not a read-only DOCUMENT: `.txt`/`.tex`/`.md` are
    # editable sources, so a substituted byte must not silently drop them from
    # the inventory's editable set (the review would route their findings to
    # manual items although they can be edited).
    d = scratch("pr536editable_")
    sub = d / "sub"
    sub.mkdir()
    (sub / "paper.tex").write_bytes(b"Result was 10 \xff 20\n")
    (sub / "paper.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    work = d / "work"
    subprocess.run([sys.executable,
                    str(WS / "paper-skills/paper-review/scripts/convert_corpus.py"),
                    "--submission", str(sub), "--work", str(work)],
                   capture_output=True, text=True, timeout=60)
    inv = {row["path"]: row for row in
           json.loads((work / "inventory.json").read_text(encoding="utf-8"))}
    check("PR536-158 a lossy .tex stays an editable submission document",
          inv.get("paper.tex", {}).get("status") == "converted-partial"
          and inv["paper.tex"]["editable"] is True, str(inv.get("paper.tex")))
    check("PR536-158 a non-editable partial conversion (pdf) stays read-only",
          inv.get("paper.pdf", {}).get("editable") is False, str(inv.get("paper.pdf")))



def test_pr161_long_flattened_name() -> None:
    print("\n== PR536-161: a valid nested path cannot overflow the corpus name ==")
    d = scratch("pr536long_")
    sub = d / "sub"
    nested = sub / ("d" * 100)
    nested.mkdir(parents=True)
    name = ("n" * 203) + ".txt"
    (nested / name).write_text("Long path body.\n")
    work = d / "work"
    r = subprocess.run([sys.executable,
                        str(WS / "paper-skills/paper-review/scripts/convert_corpus.py"),
                        "--submission", str(sub), "--work", str(work)],
                       capture_output=True, text=True, timeout=60)
    corpus = list((work / "corpus").glob("*.txt")) if (work / "corpus").is_dir() else []
    check("PR536-161 conversion completes instead of ENAMETOOLONG",
          r.returncode == 0 and corpus, f"rc={r.returncode} err={r.stderr[-300:]}")
    check("PR536-161 the truncated name stays within the filesystem limit",
          corpus and all(len(p.name.encode("utf-8")) <= 255 for p in corpus),
          [(p.name, len(p.name.encode("utf-8"))) for p in corpus])
    # NAME_MAX is a BYTE limit. A valid multibyte nested path flattens to fewer
    # than 180 characters but several hundred UTF-8 bytes, and open() raised
    # ENAMETOOLONG before the cap learned to measure bytes.
    sub2 = d / "sub2"
    (sub2 / ("目" * 80)).mkdir(parents=True)
    (sub2 / ("目" * 80) / (("文" * 80) + ".txt")).write_text("Multibyte path body.\n")
    work2 = d / "work2"
    r = subprocess.run([sys.executable,
                        str(WS / "paper-skills/paper-review/scripts/convert_corpus.py"),
                        "--submission", str(sub2), "--work", str(work2)],
                       capture_output=True, text=True, timeout=60)
    corpus = list((work2 / "corpus").glob("*.txt")) if (work2 / "corpus").is_dir() else []
    check("PR536-161 a multibyte nested path converts instead of ENAMETOOLONG",
          r.returncode == 0 and corpus, f"rc={r.returncode} err={r.stderr[-300:]}")
    check("PR536-161 every generated multibyte name fits NAME_MAX in bytes",
          corpus and all(len(p.name.encode("utf-8")) <= 255 for p in corpus),
          [(p.name, len(p.name.encode("utf-8"))) for p in corpus])


def test_pr162_fifo_enumeration() -> None:
    print("\n== PR536-162: a FIFO cannot hang conversion ==")
    d = scratch("pr536fifo_")
    sub = d / "sub"
    sub.mkdir()
    (sub / "ok.txt").write_text("ok\n")
    os.mkfifo(sub / "fixture.txt")
    work = d / "work"
    try:
        r = subprocess.run([sys.executable,
                            str(WS / "paper-skills/paper-review/scripts/convert_corpus.py"),
                            "--submission", str(sub), "--work", str(work)],
                           capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        check("PR536-162 conversion does not block on the FIFO", False, "timed out")
        return
    check("PR536-162 conversion completes and reports the skipped FIFO",
          r.returncode == 0 and "non-regular" in (r.stdout + r.stderr),
          f"rc={r.returncode} out={r.stdout[-300:]} err={r.stderr[-300:]}")
    check("PR536-162 plain_copy refuses the FIFO without blocking",
          cc.plain_copy(str(sub / "fixture.txt"))[1]
          and "not a regular file" in cc.plain_copy(str(sub / "fixture.txt"))[1][0])


# ---------------------------------------------------------------------------
# PR536-163 -- a stale package PDF is not a fresh build
# ---------------------------------------------------------------------------
def test_pr163_stale_pdf() -> None:
    print("\n== PR536-163: a compiler that writes nothing is not a success ==")
    d = scratch("pr536pdf_")
    pkg = d / "pkg"
    pkg.mkdir()
    (pkg / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}x\\end{document}\n")
    (pkg / "main.pdf").write_bytes(b"NOT A PDF AT ALL")
    binp = d / "bin"
    binp.mkdir()
    fake = binp / "latexmk"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    old = os.environ.get("PATH", "")
    os.environ["PATH"] = str(binp) + os.pathsep + old
    try:
        res = pp.compile_latex_pdf(pkg, "main.tex", d / "out.pdf")
    finally:
        os.environ["PATH"] = old
    check("PR536-163 the pre-existing PDF is not reported as a fresh build",
          res.get("ok") is False, str(res))
    check("PR536-163 no stale bytes are copied to the output",
          not (d / "out.pdf").exists())


# ---------------------------------------------------------------------------
# PR536-164/165 -- citation bibliography scope and shared roots
# ---------------------------------------------------------------------------
def _citations(files: dict, seed: str = "0") -> dict:
    d = scratch("pr536cite_")
    work = d / "work"
    (work / "corpus").mkdir(parents=True)
    for name, body in files.items():
        (work / "corpus" / name).write_text(body)
    env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable,
                        str(WS / "paper-skills/paper-review/scripts/extract_citations.py"),
                        "--work", str(work), "--out", str(d / "out")],
                       capture_output=True, text=True, env=env)
    p = d / "out/artifacts/M2_citations.json"
    if not p.is_file():
        return {"error": r.stderr[-400:]}
    return json.loads(p.read_text())


def test_pr164_165_citation_scope() -> None:
    print("\n== PR536-164/165: bibliography paths and shared fragments ==")
    out = _citations({
        "main.tex.txt": "\\documentclass{article}\n\\begin{document}\n\\cite{wrong}\n"
                        "\\bibliography{left/refs}\n\\end{document}\n",
        "left__refs.bib.txt": "@article{leftonly, title={L}}\n",
        "right__refs.bib.txt": "@article{wrong, title={R}}\n"})
    check("PR536-164 right/refs cannot resolve a cite whose root loads left/refs",
          out.get("tex_orphan_keys") == ["wrong"],
          str(out.get("tex_orphan_keys_by_file")))
    files = {
        "main_a.tex.txt": "\\documentclass{article}\n\\begin{document}\n"
                          "\\input{shared}\n\\bibliography{a}\n\\end{document}\n",
        "main_b.tex.txt": "\\documentclass{article}\n\\begin{document}\n"
                          "\\input{shared}\n\\bibliography{b}\n\\end{document}\n",
        "shared.tex.txt": "\\cite{akey}\n",
        "a.bib.txt": "@article{akey, title={A}}\n",
        "b.bib.txt": "@article{bkey, title={B}}\n"}
    results = [_citations(files, seed) for seed in ("0", "3", "5")]
    check("PR536-165 the shared fragment's orphan result is hash-seed stable",
          all(r.get("tex_orphan_keys") == ["akey"] for r in results),
          [r.get("tex_orphan_keys") for r in results])
    check("PR536-165 the fragment's context is named, not an arbitrary single root",
          all(any("shared.tex.txt [root " in k
                  for k in (r.get("tex_orphan_keys_by_file") or {}))
              for r in results),
          [r.get("tex_orphan_keys_by_file") for r in results])
    # LaTeX/BibTeX resolve a bibliography command against the compile ROOT's
    # working directory, not the directory of the fragment that carries it.
    main = ("\\documentclass{article}\n\\begin{document}\n"
            "\\input{chapters/ch1}\n\\end{document}\n")
    ch1 = "\\cite{akey}\n\\bibliography{refs}\n"
    out = _citations({"main.tex.txt": main, "chapters__ch1.tex.txt": ch1,
                      "refs.bib.txt": "@article{akey, title={A}}\n"})
    check("PR536-164 a fragment's bibliography resolves at the compile root",
          out.get("tex_orphan_keys") == [],
          str(out.get("tex_orphan_keys_by_file")))
    out = _citations({"main.tex.txt": main, "chapters__ch1.tex.txt": ch1,
                      "chapters__refs.bib.txt": "@article{akey, title={A}}\n"})
    check("PR536-164 a fragment-directory bibliography does not resolve from the root",
          out.get("tex_orphan_keys") == ["akey"],
          str(out.get("tex_orphan_keys_by_file")))
    out = _citations({
        "paper__main.tex.txt": "\\documentclass{article}\n\\begin{document}\n"
                               "\\cite{akey}\n\\bibliography{../refs}\n"
                               "\\end{document}\n",
        "refs.bib.txt": "@article{akey, title={A}}\n"})
    check("PR536-164 a ../ bibliography path is normalised against the compile root",
          out.get("tex_orphan_keys") == [],
          str(out.get("tex_orphan_keys_by_file")))


# ---------------------------------------------------------------------------
# PR536-169 -- the README profile table follows the live render
# ---------------------------------------------------------------------------
def test_pr169_profile_table() -> None:
    print("\n== PR536-169: the execution-profile table matches the live prompts ==")
    import re
    sys.path.insert(0, str(WS / ".paper_test"))
    render = load("pr536_render", ".paper_test/render_stage_prompts.py")
    old = os.environ.get("PAPER_RENDER_SANDBOX")
    try:
        os.environ["PAPER_RENDER_SANDBOX"] = str(scratch("pr536render_") / "sb")
        high = render.render(WS, "high")
        medium = render.render(WS, "medium")
    finally:
        if old is None:
            os.environ.pop("PAPER_RENDER_SANDBOX", None)
        else:
            os.environ["PAPER_RENDER_SANDBOX"] = old
    readme = (WS / "README.md").read_text(encoding="utf-8")
    m = re.search(r"^\| rewrite \| (\d+) KB \| (\d+) KB \| (\d+)% \|$",
                  readme, re.M)
    want = (len(high["rewrite"]) // 1024, len(medium["rewrite"]) // 1024,
            round(100 * (1 - len(medium["rewrite"]) / len(high["rewrite"]))))
    got = tuple(int(x) for x in m.groups()) if m else None
    check("PR536-169 the rewrite row is the live floored measurement",
          got == want, f"table {got} live {want}")


# ---------------------------------------------------------------------------
# PR536-172 -- MCP output decoding spans child reads
# ---------------------------------------------------------------------------
def test_pr172_mcp_decoder() -> None:
    print("\n== PR536-172: a split UTF-8 sequence decodes once ==")
    if not shutil.which("node"):
        print("[skip] node is not installed")
        return
    script = r"""
import { runFile } from 'WS/mcp-docx-converter/run-child.mjs';
import { runFile as runCompare } from 'WS/mcp-docx-compare/run-child.mjs';
const child = 'process.stdout.write(Buffer.from([0xC3]));setTimeout(()=>{process.stdout.write(Buffer.from([0xA9]));},150)';
const out = {};
for (const [n, f] of [['converter', runFile], ['compare', runCompare]]) {
  try { out[n] = (await f(process.execPath, ['-e', child])).stdout; }
  catch (e) { out[n] = 'ERR ' + e.message; }
}
console.log(JSON.stringify(out));
""".replace("WS/", str(WS) + "/")
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=30)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        out = {"error": r.stdout + r.stderr}
    check("PR536-172 both wrappers return the intact character",
          out.get("converter") == "\u00e9" and out.get("compare") == "\u00e9",
          str(out)[:400])


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    try:
        for fn in tests:
            fn()
    finally:
        for tmp in TMPDIRS:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("OK: all PR536 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

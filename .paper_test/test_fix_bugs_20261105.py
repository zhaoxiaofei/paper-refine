#!/usr/bin/env python3
"""Regression checks for the 2026-11-05 fix-bugs wave 1.

Run:  python3 .paper_test/test_fix_bugs_20261105.py

Every check pins one candidate the verify-findings stage kept as a true
positive (PR-003 .. PR-216).  The pre-fix tree fails the checks that name a
behavioural defect; the prose checks fail on the pre-fix wording.  The suite is
hermetic (temporary roots only).
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

WS = Path(__file__).resolve().parent.parent
FAILS = []
TMPDIRS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1105_pp", "paper_pipeline.py")

PROMPTS = WS / "paper_pipeline_parts" / "p03_prompts.py"
JOURNAL = WS / "paper_pipeline_parts" / "p07_stage_quality_journal.py"
STATE = WS / "paper_pipeline_parts" / "p05_state_corpus.py"
SKILL_REVISE = WS / "paper-skills" / "paper-revise" / "SKILL.md"
RULES_REVISE = WS / "paper-skills" / "paper-revise" / "references" / "edit_rules.md"
SWEEPS = WS / "paper-skills" / "paper-review" / "references" / "sweeps.md"


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def text(rel: Path) -> str:
    return rel.read_text(encoding="utf-8")


def flat(value: str) -> str:
    """Whitespace-normalised text (line wrapping is not a wording change)."""
    return " ".join(str(value or "").split())


def generated(prefix: str, fn, *args, **kwargs) -> str:
    sb = scratch(prefix)
    return fn(sb, *args, **kwargs)


# ---------------------------------------------------------------------------
# PR-003 -- the paged integrate sidecar follows the readme transform
# ---------------------------------------------------------------------------
def test_pr003_paged_sidecar_uses_readme_paths():
    print()
    print("== PR-003: paged integration rules use the policy's hand-off path ==")
    sb = scratch("pr003_")
    pp.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"], author_to_complete="readme",
                        execution_profile="medium")
    sidecar = (sb / pp.PROFILE_RULES_REL).read_text(encoding="utf-8")
    check("PR-003 the paged sidecar carries no integrated/MANUAL_STEPS.md",
          "integrated/MANUAL_STEPS.md" not in sidecar,
          sidecar[:200])
    check("PR-003 the paged sidecar names the readme policy path",
          "README-AUTHOR-TO-COMPLETE.md" in sidecar,
          sidecar[:200])


# ---------------------------------------------------------------------------
# PR-009 -- the retry brief does not call every failure non-transient
# ---------------------------------------------------------------------------
def test_pr009_retry_wording():
    print()
    print("== PR-009: a recorded timeout is not described as a non-transient crash ==")
    timeout = pp.prior_failure_block({"attempts": 1, "last_error": "TIMEOUT after 60s"})
    check("PR-009 a timeout-only retry does not assert 'NOT a transient crash'",
          "NOT a transient crash" not in timeout, timeout[:200])
    check("PR-009 a timeout-only retry still carries the failure text",
          "TIMEOUT after 60s" in timeout, timeout[:200])
    checked = pp.prior_failure_block({
        "attempts": 1,
        "postcheck": {"errors": ["bad output"]},
        "attempts_log": [{"attempt": 1, "ok": False, "errors": ["bad output"]}],
    })
    check("PR-009 a postcheck failure keeps the specific-failure wording",
          "bad output" in checked and "NOT a transient crash" in checked, checked[:200])
    # The REAL shape the producer writes for a process failure: the timeout text
    # is in `errors` (p08 `record_attempt(..., source="process")`), so an
    # errors-based test alone sent it the postcheck-rejection wording.
    for source in ("process", "manual-timeout"):
        real = pp.prior_failure_block({
            "attempts": 1,
            "last_error": "TIMEOUT after 60s",
            "attempts_log": [{"attempt": 1, "ok": False, "source": source,
                              "errors": ["TIMEOUT after 60s"]}],
        })
        check(f"PR-009 a real {source} failure gets the conditional process wording",
              "NOT a transient crash" not in real and "may still work" in real,
              real[:240])


# ---------------------------------------------------------------------------
# PR-015 -- split review B is cold with respect to A's output
# ---------------------------------------------------------------------------
def test_pr015_split_review_is_cold():
    print()
    print("== PR-015: split review B does not receive A's review output ==")
    src = text(STATE)
    body = src[src.index("def materialize_review"):src.index("def materialize_audit")]
    check("PR-015 materialize_review no longer copies A's guided_review/ into B",
          "GUIDED_REVIEW_A_DIR" not in body and "guided_review_a" not in body, body[:400])
    check("PR-015 A's findings digest is NOT stored inside inputs_manifest",
          'inputs["review_a_findings"]' not in body)
    check("PR-015 A's findings digest is stored on the run record",
          'rec["review_a_findings"]' in body)
    check("PR-015 the B manifest check no longer freezes A's output",
          "no longer matches session A's current review" not in src)
    check("PR-015 the split prompt does not hand B the other session's findings",
          "guided_review_a" not in text(PROMPTS))


# ---------------------------------------------------------------------------
# PR-021 -- split review ids are rendered consistently
# ---------------------------------------------------------------------------
def test_pr021_split_ids():
    print()
    print("== PR-021: a split reviewer gets one id namespace ==")
    a = generated("pr021a_", pp.review_prompt, "r1_guided_review", 1, split="a")
    b = generated("pr021b_", pp.review_prompt, "r1_guided_review_b", 1, split="b")
    check("PR-021 split A's schema example uses FA-001",
          '"id": "FA-001"' in a and '"id": "F-001"' not in a)
    check("PR-021 split A's stability rule uses FA ids",
          "(FA-001, FA-002, ...)" in a and "(F-001, F-002, ...)" not in a)
    check("PR-021 split B's schema example uses FB-001",
          '"id": "FB-001"' in b and '"id": "F-001"' not in b)


# ---------------------------------------------------------------------------
# PR-022 -- the cold-start review gets no adopted checklist
# ---------------------------------------------------------------------------
def test_pr022_cold_start_has_no_checklist():
    print()
    print("== PR-022: the cold-start review receives no adopted checklist ==")
    sb = scratch("pr022_")
    probe = pp.cold_start_review_prompt(sb, "r1_cold_start_review", 1,
                                        execution_profile="medium")
    sidecar = (sb / pp.PROFILE_RULES_REL).read_text(encoding="utf-8")
    check("PR-022 the cold-start prompt carries no adopted checks block",
          "THE ADOPTED CHECKS" not in probe)
    check("PR-022 the cold-start sidecar carries no adopted checks block",
          "THE ADOPTED CHECKS" not in sidecar)
    check("PR-022 the cold-start text still carries the shared decision rules",
          "THE SHARED DECISION RULES" in probe or "THE SHARED DECISION RULES" in sidecar)


# ---------------------------------------------------------------------------
# PR-026 -- a skipped verifier is not counted as verified
# ---------------------------------------------------------------------------
def test_pr026_skipped_verifier():
    print()
    print("== PR-026: an over-budget verifier is not a verified computation ==")
    sb = scratch("pr026_")
    findings = [
        {"id": "X-901", "verifier": {"script": "cold_start_review/scripts/v1.py",
                                     "computed": "1", "shows": "x"}},
        {"id": "X-902", "verifier": {"script": "cold_start_review/scripts/v2.py",
                                     "computed": "2", "shows": "y"}},
    ]
    old = pp.COLD_START_REPRO_TOTAL_BUDGET
    try:
        pp.COLD_START_REPRO_TOTAL_BUDGET = -1
        repro = pp.cold_start_reproduction(sb, findings)
    finally:
        pp.COLD_START_REPRO_TOTAL_BUDGET = old
    check("PR-026 skipped verifiers are not counted in `verified`",
          repro["verified"] == 0, str(repro))
    check("PR-026 skipped verifiers are named separately",
          repro.get("skipped") == ["X-901", "X-902"], str(repro))
    check("PR-026 skipped verifiers are broken (the stage cannot pass)",
          repro.get("broken") == ["X-901", "X-902"], str(repro))


def test_r04_selfcheck_reports_skipped_verifier():
    """The pre-flight must report what the final postcheck rejects."""
    print()
    print("== R04: the cold-start self-check reports an over-budget verifier ==")
    sb = scratch("r04_selfcheck_")
    (sb / "cold_start_review" / "scripts").mkdir(parents=True)
    (sb / "cold_start_review" / "scripts" / "v1.py").write_text("print(42)\n",
                                                               encoding="utf-8")
    findings = {
        "checked": [{"area": "documents", "examined": 1, "findings": 1}],
        "findings": [{
            "id": "X-901", "category": 0, "severity": "major",
            "location": "manuscript.md:1", "evidence": "e", "explanation": "x",
            "verifier": {"script": "cold_start_review/scripts/v1.py",
                         "computed": "42", "shows": "s"},
        }],
    }
    (sb / pp.COLD_START_FINDINGS_REL).write_text(json.dumps(findings), encoding="utf-8")
    (sb / pp.COLD_START_COVERAGE_REL).write_text(
        "documents: examined 1, filed 1\n", encoding="utf-8")
    (sb / pp.MARKER_FILE).write_text(json.dumps({
        "stage": "cold_start_review", "status": "complete",
        "run_id": "r1_cold_start_review", "round": 1}), encoding="utf-8")
    old = pp.COLD_START_REPRO_TOTAL_BUDGET
    try:
        pp.COLD_START_REPRO_TOTAL_BUDGET = -1
        ok, errs, _warns = pp.sandbox_selfcheck(
            sb, "cold_start_review", "r1_cold_start_review", 1)
    finally:
        pp.COLD_START_REPRO_TOTAL_BUDGET = old
    check("R04 the self-check does not stay green for a skipped verifier",
          ok is False and any("NOT re-run because the aggregate verifier budget" in e
                             for e in errs), str(errs)[:500])


# ---------------------------------------------------------------------------
# PR-037 -- the review auditor gets a read-only validation rule
# ---------------------------------------------------------------------------
def test_pr037_audit_validation_readonly():
    print()
    print("== PR-037: the auditor is told to observe validation, not repair ==")
    audit = generated("pr037b_", pp.audit_prompt, "r1_audit", 1)
    check("PR-037 the audit prompt does not tell the auditor to repair a package file",
          "repair the file it names" not in audit)
    check("PR-037 the audit prompt still carries a validation duty",
          "VALIDATION" in audit and "validator" in audit)
    check("PR-037 the audit validation duty is read-only",
          "do NOT edit" in audit or "record" in audit.lower())


# ---------------------------------------------------------------------------
# PR-043 -- the repair-ledger example is a container document
# ---------------------------------------------------------------------------
def test_pr043_repair_ledger_example():
    print()
    print("== PR-043: the bounded-repair ledger example wraps its rows ==")
    prompt = generated("pr043_", pp.revision_repair_prompt, "r1_repair", 1, 1)
    idx = prompt.index("REPAIR_LEDGER.json")
    snippet = prompt[idx:idx + 400]
    check("PR-043 the REPAIR_LEDGER.json example carries a rows container",
          '{"rows": [' in snippet, snippet[:300])


# ---------------------------------------------------------------------------
# PR-045 -- the revision-audit lead lists every writable artifact
# ---------------------------------------------------------------------------
def test_pr045_revision_audit_authority():
    print()
    print("== PR-045: the revision-audit lead agrees with the deletion audit ==")
    prompt = generated("pr045_", pp.revision_audit_prompt, "r1_revision_audit", 1)
    check("PR-045 the lead no longer forbids every other file",
          "or any other file" not in prompt)
    check("PR-045 the seeded deletion table is named as writable",
          "DELETED_PARAGRAPHS.md" in prompt and "IN PLACE" in prompt)


# ---------------------------------------------------------------------------
# PR-049 -- the repair prompt uses the canonical revision statuses
# ---------------------------------------------------------------------------
def test_pr049_repair_statuses():
    print()
    print("== PR-049: the artifact-repair prompt uses the revision contract's statuses ==")
    prompt = pp._repair_prompt_body(None, {"id": "r1_a2", "kind": "revise", "round": 1}, ["x"])
    check("PR-049 the repair prompt does not advertise not_applicable as a ledger status",
          "not_applicable" not in prompt)
    check("PR-049 the repair prompt names the canonical manual-required status",
          "manual-required" in prompt)


# ---------------------------------------------------------------------------
# PR-072 -- the judge prompt does not renumber the tier order
# ---------------------------------------------------------------------------
def test_pr072_priority_ordinal():
    print()
    print("== PR-072: consistency is fourth in the one tier order ==")
    judge = flat(generated("pr072_", pp.judge_prompt, "judge_tok_j1", 1, "tok", 1, 1, ["v1"]))
    check("PR-072 the judge prompt does not call consistency second",
          "second in the priority order" not in judge)
    check("PR-072 the judge prompt keeps the canonical tier order",
          "correctness > preservation > completeness > consistency > writing > formatting" in judge)


# ---------------------------------------------------------------------------
# PR-073 -- the documented length contribution limit is enforced
# ---------------------------------------------------------------------------
def test_pr073_length_limit():
    print()
    print("== PR-073: M18/M19 length rows move a comparison by at most one point ==")
    comp = {"score": 1, "basis": "formatting",
            "resolved": [
                {"tier": "formatting", "severity": "minor", "check": "M18",
                 "evidence": "legend is twenty words over the proxy cap"},
                {"tier": "formatting", "severity": "minor", "check": "M19",
                 "evidence": "abstract is ten words over the relaxed cap"}],
            "introduced": []}
    check("PR-073 two length rows derive +1, not +2",
          pp.derived_comparison_score(comp) == 1,
          str(pp.derived_comparison_score(comp)))
    comp2 = {"score": 2, "basis": "formatting",
             "resolved": [
                 {"tier": "formatting", "severity": "minor", "check": "M18",
                  "evidence": "legend is twenty words over the proxy cap"},
                 {"tier": "formatting", "severity": "minor", "check": "M20",
                  "evidence": "one paragraph indent differs from its siblings"}],
             "introduced": []}
    check("PR-073 one length row plus one other formatting row still derives +2",
          pp.derived_comparison_score(comp2) == 2,
          str(pp.derived_comparison_score(comp2)))


# ---------------------------------------------------------------------------
# PR-091 -- the scoped concerns prompt names both ledger paths
# ---------------------------------------------------------------------------
def test_pr091_concerns_ledger_paths():
    print()
    print("== PR-091: the scoped concerns prompt names the canonical ledger paths ==")
    tmp = scratch("pr091_")
    (tmp / "feedback").mkdir()
    (tmp / "feedback" / "CONCERN_SEED.json").write_text('{"candidates": []}\n',
                                                       encoding="utf-8")
    ctx = SimpleNamespace(cfg={"revision_mode": "major"}, pristine=tmp / "pristine",
                          runs_dir=tmp / "runs", root=None)
    (tmp / "pristine").mkdir()
    prompt = pp.concerns_prompt(ctx, tmp, 1, [])
    check("PR-091 the prompt names concerns/JF_concerns.json",
          "concerns/JF_concerns.json" in prompt)
    check("PR-091 the prompt names concerns/JF_concerns.md",
          "concerns/JF_concerns.md" in prompt)


# ---------------------------------------------------------------------------
# PR-094 -- appended words cannot pass as a verbatim reviewer quote
# ---------------------------------------------------------------------------
def test_pr094_verbatim_comment():
    print()
    print("== PR-094: a Comment may not add invented words to the verified quote ==")
    true = "The sample size is too small for the claims."
    check("PR-094 an exact quote passes",
          pp.response_comment_is_verbatim(true, true))
    check("PR-094 a sub-excerpt still passes",
          pp.response_comment_is_verbatim("sample size is too small", true))
    check("PR-094 an expanded quote with invented words fails",
          not pp.response_comment_is_verbatim(
              "The sample size is too small for the claims, as the editor agreed", true))


# ---------------------------------------------------------------------------
# PR-100 / PR-101 -- the concern ledger's quote gate is bounded and attributed
# ---------------------------------------------------------------------------
def _ledger_fixture(quote, source="reviewer1.txt", author="Reviewer 1"):
    sb = scratch("ledger_")
    (sb / "concerns").mkdir(parents=True)
    (sb / "feedback" / "text").mkdir(parents=True)
    (sb / "feedback" / "files").mkdir(parents=True)
    (sb / "feedback" / "llm" / "text").mkdir(parents=True)
    (sb / "feedback" / "llm" / "files").mkdir(parents=True)
    (sb / "feedback" / "files" / "reviewer1.txt").write_text("x\n", encoding="utf-8")
    (sb / "feedback" / "text" / "reviewer1.txt").write_text(
        "The sample size is too small for the claims. " + "y " * 300 + "\n",
        encoding="utf-8")
    (sb / "feedback" / "llm" / "files" / "claude.txt").write_text("x\n", encoding="utf-8")
    (sb / "feedback" / "llm" / "text" / "claude.txt").write_text(
        "The LLM says the sample is too small.\n", encoding="utf-8")
    row = {"id": "R1-1", "source": source, "author": author, "quote": quote,
           "summary": "s", "action": "text", "manuscript_location": None,
           "disposition": "to-fix", "evidence_needed": ""}
    (sb / "concerns" / "JF_concerns.json").write_text(
        json.dumps({"concerns": [row]}), encoding="utf-8")
    errs, warns = [], []
    pp.journal_ledger_problems(None, sb, errs, warns)
    return errs, warns


def test_pr100_quote_maximum():
    print()
    print("== PR-100: the advertised 300-character quote maximum is enforced ==")
    long_quote = "The sample size is too small for the claims. " + "y " * 210
    errs, _ = _ledger_fixture(long_quote[:431])
    check("PR-100 a 431-character quote is rejected",
          any("300" in e or "too long" in e for e in errs), str(errs)[:400])


def test_pr101_quote_source_binding():
    print()
    print("== PR-101: a quote is checked against the stream its source names ==")
    errs, _ = _ledger_fixture("The LLM says the sample is too small.",
                              source="reviewer1.txt", author="Reviewer 1")
    check("PR-101 an LLM quote attributed to the human letter is rejected",
          any("feedback" in e or "verbatim" in e for e in errs), str(errs)[:400])
    errs2, _ = _ledger_fixture("The sample size is too small for the claims.")
    check("PR-101 a correctly attributed human quote passes", errs2 == [], str(errs2)[:400])
    errs3, _ = _ledger_fixture("The sample size is too small for the claims.",
                               source="", author="")
    check("PR-101 a row with no source/author is rejected",
          len(errs3) >= 2, str(errs3)[:400])


# ---------------------------------------------------------------------------
# R01 (repair round) -- the seed's corpus-relative feedback labels bind
# ---------------------------------------------------------------------------
def _area_ledger_fixture(quote, source):
    """A ledger whose sources are the documented feedback labels, not safe names."""
    sb = scratch("ledger_area_")
    (sb / "concerns").mkdir(parents=True)
    for d in ("feedback/files", "feedback/text", "feedback/llm/files", "feedback/llm/text"):
        (sb / d).mkdir(parents=True)
    (sb / "feedback/files/human_review_feedback__editor_letter.txt").write_text("x")
    (sb / "feedback/text/human_review_feedback__editor_letter.txt.txt").write_text(
        "Reviewer 1\n1. The sample size is too small for the main claim.\n")
    (sb / "feedback/llm/files/llm_review_feedback__llm_review.md").write_text("x")
    (sb / "feedback/llm/text/llm_review_feedback__llm_review.md.txt").write_text(
        "LLM says the sample size is too small.\n")
    (sb / "feedback/CONCERN_SEED.json").write_text(json.dumps({
        "files": ["human_review_feedback/editor_letter.txt"],
        "llm_files": ["llm_review_feedback/llm_review.md"]}))
    row = {"id": "L1", "source": source, "author": "Reviewer 1", "quote": quote,
           "summary": "s", "action": "text", "manuscript_location": None,
           "disposition": "to-fix", "evidence_needed": ""}
    (sb / "concerns" / "JF_concerns.json").write_text(
        json.dumps({"concerns": [row]}), encoding="utf-8")
    errs, warns = [], []
    pp.journal_ledger_problems(None, sb, errs, warns)
    return errs


def test_r01_documented_feedback_labels_bind():
    print()
    print("== R01: a seed-provided corpus-relative feedback label binds ==")
    quote = "The sample size is too small for the main claim."
    for source in ("human_review_feedback/editor_letter.txt",
                   "editor_letter.txt",
                   "human_review_feedback__editor_letter.txt"):
        errs = _area_ledger_fixture(quote, source)
        check(f"R01 the documented source {source!r} binds to the staged file",
              errs == [], str(errs)[:400])
    errs = _area_ledger_fixture("LLM says the sample size is too small.",
                                "llm_review_feedback/llm_review.md")
    check("R01 the documented LLM label binds to the LLM stream", errs == [], str(errs)[:400])
    errs = _area_ledger_fixture("LLM says the sample size is too small.",
                                "human_review_feedback/editor_letter.txt")
    check("R01 a documented human label still rejects an LLM quote",
          any("not verbatim" in e for e in errs), str(errs)[:400])


# ---------------------------------------------------------------------------
# R05 (repair round) -- the split-review docs describe the cold-B design
# ---------------------------------------------------------------------------
def test_r05_split_review_docs_match_cold_b():
    print()
    print("== R05: no on-disk shape or dead constant still promises A's copy ==")
    readme = text(WS / "README.md")
    check("R05 README no longer lists guided_review_a/ in the current shape",
          "guided_review_a" not in readme)
    check("R05 README names the cold split-B sandbox",
          "session B is cold" in readme)
    p02 = text(WS / "paper_pipeline_parts" / "p02_journal_modes.py")
    check("R05 the dead GUIDED_REVIEW_A_DIR constant is gone",
          "GUIDED_REVIEW_A_DIR" not in p02)


# ---------------------------------------------------------------------------
# PR-107 -- only headings count as response blocks
# ---------------------------------------------------------------------------
def test_pr107_response_blocks():
    print()
    print("== PR-107: a cross-reference does not duplicate a response block ==")
    letter = ("## R1-1 -- sample size\n\n**Comment:** \"too small\"\n\n"
              "**Response:** We also address R1-2 below.\n\n"
              "## R1-2 -- claims\n\n**Comment:** \"overstated\"\n\n**Response:** Fixed.\n")
    check("PR-107 a cross-reference is not a second block",
          pp.response_heading_occurrences("R1-2", letter) == 1,
          str(pp.response_heading_occurrences("R1-2", letter)))
    check("PR-107 a genuinely duplicated heading is counted",
          pp.response_heading_occurrences(
              "R1-1", "## R1-1 -- a\n\n## R1-1 -- b\n") == 2)


# ---------------------------------------------------------------------------
# PR-110 -- a plain citation is not required to invent Zotero field data
# ---------------------------------------------------------------------------
def test_pr110_plain_citation():
    print()
    print("== PR-110: an originally plain citation keeps its text and records a gap ==")
    src = text(WS / "paper_pipeline_parts" / "p04_utils.py")
    idx = src.index("CARRY EVERY LIVE ZOTERO FIELD OVER UNCHANGED")
    snippet = src[idx:idx + 900]
    check("PR-110 the re-creation duty is conditional on source field data",
          "when that data exists" in snippet, snippet[:500])
    check("PR-110 an originally plain citation may stay plain with a recorded gap",
          "originally plain" in snippet and "REPLACEMENT_LEDGER.md" in snippet,
          snippet[:500])


# ---------------------------------------------------------------------------
# PR-117 -- the defect audit's final instruction allows UNVERIFIED
# ---------------------------------------------------------------------------
def test_pr117_unverified_label():
    print()
    print("== PR-117: the final audit instruction matches the three-label schema ==")
    prompt = pp._defect_audit_prompt(1, 3)
    check("PR-117 the final instruction names UNVERIFIED",
          'label "TP", "FP" or "UNVERIFIED"' in prompt,
          prompt[-400:])
    check("PR-117 the two-label wording is gone",
          'with label "TP" or\n"FP"' not in prompt and 'with label "TP" or "FP"' not in prompt)


# ---------------------------------------------------------------------------
# PR-120 -- the language-pass guard has the gated-repair exception
# ---------------------------------------------------------------------------
def test_pr120_language_guard():
    print()
    print("== PR-120: the final language guard allows a finding-authorised repair ==")
    rule = pp.LANGUAGE_PASS_RULE
    check("PR-120 the guard names the frozen-finding exception",
          "except where a frozen finding authorises" in rule)
    check("PR-120 the guard still forbids unauthorised number changes",
          "never change a number" in rule)


# ---------------------------------------------------------------------------
# PR-124 -- bare L1-L11 labels do not satisfy the coverage gate
# ---------------------------------------------------------------------------
def test_pr124_language_coverage():
    print()
    print("== PR-124: the language coverage gate needs a table row per step ==")
    pkg = scratch("pr124_")
    (pkg / "work").mkdir()
    (pkg / "work" / "R6_language.md").write_text(
        "\n".join(f"L{i}" for i in range(1, 12)) + "\n", encoding="utf-8")
    rep = pp.language_pass_report(pkg)
    check("PR-124 bare labels leave every step missing",
          rep["missing"] == [f"L{i}" for i in range(1, 12)], str(rep))
    (pkg / "work" / "R6_language.md").write_text(
        "| step | location | before | after | reason |\n|---|---|---|---|---|\n"
        "| L1 | a | b | c | d |\n\n"
        "| step | rows changed | note |\n|---|---|---|\n"
        + "\n".join(f"| L{i} | 0 | no change found |" for i in range(1, 12)) + "\n",
        encoding="utf-8")
    rep2 = pp.language_pass_report(pkg)
    check("PR-124 a proper coverage table satisfies every step",
          rep2["missing"] == [], str(rep2))


# ---------------------------------------------------------------------------
# PR-129 / PR-139 / PR-140 / PR-144 / PR-151 / PR-175 / PR-176 / PR-182 /
# PR-184 / PR-187 -- the standalone skills' prose
# ---------------------------------------------------------------------------
def test_pr129_caption_tool_route():
    print()
    print("== PR-129: the script table does not claim a caption mode count_words lacks ==")
    skill = text(WS / "paper-skills" / "paper-review" / "SKILL.md")
    prompt = text(WS / "paper-skills" / "prompts" / "identify_issues.prompt.md")
    row = next(line for line in skill.splitlines() if "scripts/count_words.py" in line)
    prow = next(line for line in prompt.splitlines() if "scripts/count_words.py" in line)
    check("PR-129 count_words.py is described as the M19 section counter",
          "M19" in row and "M18/M19" not in row, row[:300])
    check("PR-129 the prompt's script table carries the corrected M19 route",
          "M19" in prow and "M18/M19" not in prow, prow[:300])


def test_pr139_140_page_budget():
    print()
    print("== PR-139/140: page budgets are stated by the venue and decided by a render ==")
    sweeps = text(SWEEPS)
    check("PR-139 the cached page count is not an alternative decision source",
          "when a render or the cached count shows it" not in sweeps)
    check("PR-140 the front-page/two-page budgets are conditional on a stated rule",
          "When the venue profile (or the operator) states" in sweeps
          or "when the active venue profile states" in sweeps.lower())


def test_pr144_acronym_synonym():
    print()
    print("== PR-144: the acronym sweep does not treat a different quantity as a synonym ==")
    sweeps = text(SWEEPS)
    rules = text(RULES_REVISE)
    script = text(WS / "paper-skills" / "paper-review" / "scripts" / "extract_acronyms.py")
    prompt = text(WS / "paper-skills" / "prompts" / "identify_issues.prompt.md")
    check("PR-144 the unsafe example is gone from the review sweep",
          "aberration burden" not in sweeps)
    check("PR-144 the unsafe example is gone from the revise rules",
          "aberration burden" not in rules)
    check("PR-144 the unsafe example is gone from the script's limit note",
          "aberration burden" not in script)
    check("PR-144 the unsafe example is gone from the prompt asset",
          "aberration burden" not in prompt)
    check("PR-144 an entity-equivalence guard is stated",
          "same measured quantity" in flat(rules) or "same quantity" in flat(rules))


def test_pr151_prefixed_units():
    print()
    print("== PR-151: mM and M are quantities, not presentation variants ==")
    sweeps = text(SWEEPS)
    check("PR-151 mM vs M is not listed as a presentation variant",
          "mM vs M" not in sweeps)
    check("PR-151 the 1,000x difference is stated",
          "factor of 1,000" in sweeps or "factor of 1000" in sweeps)


def test_pr175_176_statistics():
    print()
    print("== PR-175/176: the Holm procedure is step-down and the floor is a floor ==")
    sweeps = text(SWEEPS)
    check("PR-175 the single 0.05/family threshold is not presented as Holm",
          "0.05/family" not in sweeps)
    check("PR-175 the step-down thresholds are stated",
          "0.05 / (m" in sweeps)
    check("PR-176 the minimum attainable p-value is not called a ceiling",
          "with the ceiling named" not in sweeps)
    check("PR-176 the floor wording is used",
          "minimum attainable p-value" in sweeps)


def test_pr182_z3_rule():
    print()
    print("== PR-182: every FMT-Z3 subtype has a finding rule ==")
    sweeps = text(SWEEPS)
    idx = sweeps.index("## M36")
    end = sweeps.index("## New code-side rule ids", idx)
    block = sweeps[idx:end]
    check("PR-182 the finding rules classify FMT-Z3",
          "FMT-Z3" in block[block.index("**Finding rules.**"):])


def test_pr184_zotero_scan_vs_refresh():
    print()
    print("== PR-184: the scan is read-only; the refresh may rewrite cached results ==")
    sweeps = text(SWEEPS)
    idx = sweeps.index("## M36")
    end = sweeps.index("## New code-side rule ids", idx)
    block = sweeps[idx:end]
    check("PR-184 the immutable-field absolute is scoped to the scan",
          "a field result is never edited by the tools" not in flat(block)
          and "the scan reads field results and never edits them" in flat(block))


def test_pr187_venue_ai_policy():
    print()
    print("== PR-187: the AI policy is the resolved venue's, not one publisher's ==")
    sweeps = text(SWEEPS)
    rules = text(RULES_REVISE)
    idx = sweeps.index("## J4")
    j4 = sweeps[idx:sweeps.index("## J5", idx)]
    idx2 = rules.index("## E4")
    e4 = rules[idx2:rules.index("## E5", idx2)]
    check("PR-187 J4 no longer applies Springer Nature policy unconditionally",
          "Springer Nature generative-AI policy:" not in j4)
    check("PR-187 J4 names the active venue's recorded policy and the gap",
          "active venue" in j4.lower() and "policy gap" in j4.lower())
    check("PR-187 E4 no longer applies Springer Nature policy unconditionally",
          "ensure disclosure complies with Springer Nature policy" not in e4)
    check("PR-187 E4 names the active venue's policy and the gap",
          "active venue" in e4.lower() and "policy gap" in e4.lower())


# ---------------------------------------------------------------------------
# PR-196 / PR-205 / PR-215 / PR-216 -- the revision skill / edit rules
# ---------------------------------------------------------------------------
def test_pr196_final_token():
    print()
    print("== PR-196: the content token is recomputed after the payload edits ==")
    skill = text(SKILL_REVISE)
    check("PR-196 the skill requires a final recompute after the payload edits",
          "recompute the token" in skill.lower()
          or "recompute the final content token" in skill.lower())
    check("PR-196 the final recompute happens after P and C",
          "after P and C" in skill or "after the last payload edit" in skill)


def test_pr205_readonly_field_recreation():
    print()
    print("== PR-205: field re-creation is qualified by the Zotero edit mode ==")
    rules = text(RULES_REVISE)
    idx = rules.index("**Continuity")
    block = rules[idx:idx + 1200]
    check("PR-205 the read-only mode is told to record the re-creation instead",
          "`off`/`read`" in block or "read` mode" in block)
    check("PR-205 the rebuild is not unconditional",
          "in `edit` or `apply` mode" in block)
    # The top-level SKILL.md summary must agree with the rules file: pipeline
    # revise prompts tell the session to read SKILL.md first, and it used to
    # command the same unconditional rebuild.
    skill = text(SKILL_REVISE)
    sidx = skill.index("Field continuity (rule E2)")
    sblock = skill[sidx:sidx + 1200]
    check("PR-205 SKILL.md qualifies the rebuild by the Zotero edit mode",
          "in `edit` or `apply` mode" in sblock and "`off`/`read`" in sblock,
          sblock[:400])
    check("PR-205 SKILL.md keeps an originally plain citation plain",
          "originally plain" in sblock, sblock[:400])


def test_pr215_code_scope():
    print()
    print("== PR-215: analysis code is revision content even when it is not submitted ==")
    rules = text(RULES_REVISE)
    check("PR-215 the code heading no longer conditions on the submission",
          "## C — Code revisions (only if analysis code is part of the submission)" not in rules)
    check("PR-215 E13 no longer conditions code revision on submit-code",
          "only when the operator submits it" not in rules)


def test_pr216_language_default():
    print()
    print("== PR-216: E9 states the effective strict-artifacts default ==")
    rules = text(RULES_REVISE)
    idx = rules.index("## E9")
    block = rules[idx:idx + 1200]
    check("PR-216 E9 no longer says missing rows only warn by default",
          "it warns\nby default and fails the attempt under" not in block)
    check("PR-216 E9 states that missing rows fail by default",
          "fails the attempt by default" in flat(block))


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print(f"workspace: {WS}")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as e:                                    # noqa: BLE001
            check(f"{fn.__name__} raised {type(e).__name__}", False, str(e)[:300])
    cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s): {', '.join(FAILS[:8])}"
              + (" ..." if len(FAILS) > 8 else ""))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

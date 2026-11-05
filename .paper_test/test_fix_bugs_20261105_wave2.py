#!/usr/bin/env python3
"""Regression checks for the 2026-11-05 fix-bugs wave 2 (PR151-007 .. PR151-151).

Run:  python3 .paper_test/test_fix_bugs_20261105_wave2.py

Every check below pins one candidate the verify-findings stage kept and wave 2
re-confirmed on this tree. The suite is hermetic (temporary roots only).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
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


pp = load("fixbugs1105w2_pp", "paper_pipeline.py")
AGENTS = WS / "AGENTS.md"
RULES = WS / "paper-skills/paper-revise/references/edit_rules.md"
ADDRESS = WS / "paper-skills/prompts/adress_issues.prompt.md"


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


# ---------------------------------------------------------------- PR151-007
def test_pr151_007_occurrence_identity():
    print("\n== PR151-007: one disposition per seeded deletion occurrence ==")
    p1 = "A" * 1200 + " ending one"
    p2 = "A" * 1200 + " ending two"
    rows = [{"document": "a.md", "line": 3, "paragraph": p1},
            {"document": "b.md", "line": 7, "paragraph": p2}]
    seed = pp.deletion_audit_markdown(rows)
    lines = seed.splitlines()
    header = next(x for x in lines if x.startswith("| #"))
    first = next(x for x in lines if x.startswith("| D1-"))
    disposed = first.rsplit("|", 2)[0] + "| OK — duplicate; no fact lost |"
    sb = scratch("w2p7_")
    (sb / "revision_audit").mkdir()
    (sb / "revision_audit" / "DELETED_PARAGRAPHS.md").write_text(
        "\n".join([header, "|---|---|---|---|---|", disposed, disposed]) + "\n",
        encoding="utf-8")
    probs = pp.deletion_audit_problems(
        sb, expected_rows=2, expected_paragraphs=[p1, p2], expected_occurrences=rows)
    check("PR151-007 a duplicated seed row cannot cover the other occurrence",
          any("seeded row id" in p for p in probs), probs)
    # A verbatim, one-per-row disposition still passes.
    body = []
    for i, line in enumerate(seed.splitlines()):
        if line.startswith("| D"):
            body.append(line.rsplit("|", 2)[0]
                        + f"| OK — row {i} duplicate; the facts survive elsewhere |")
        else:
            body.append(line)
    (sb / "revision_audit" / "DELETED_PARAGRAPHS.md").write_text(
        "\n".join(body) + "\n", encoding="utf-8")
    check("PR151-007 the verbatim disposed seed still passes",
          pp.deletion_audit_problems(
              sb, expected_rows=2, expected_paragraphs=[p1, p2],
              expected_occurrences=rows) == [],
          pp.deletion_audit_problems(
              sb, expected_rows=2, expected_paragraphs=[p1, p2],
              expected_occurrences=rows))


# ---------------------------------------------------------------- PR151-008
def test_pr151_008_cell_roundtrip():
    print("\n== PR151-008: a backslash before a pipe round-trips ==")
    para = ("We compared the wild type " + chr(92) * 2 +
            "| mutant strains in every block and found a consistent effect.")
    rows = [{"document": "main.md", "line": 4, "paragraph": para}]
    sb = scratch("w2p8_")
    p = sb / "seed.md"
    p.write_text(pp.deletion_audit_markdown(rows), encoding="utf-8")
    block = pp.parse_markdown_blocks(p)[0]
    check("PR151-008 the seeded row keeps the header's column count",
          block["widths"] == [len(block["header"])], block["widths"])
    check("PR151-008 the paragraph identity round-trips",
          pp._deletion_audit_identity(block["rows"][0].get("paragraph"))
          == pp._deletion_audit_identity(para),
          (block["rows"][0].get("paragraph"), para))
    check("PR151-008 the disposition cell is not shifted",
          block["rows"][0].get("disposition") == "", block["rows"][0])
    check("PR151-008 an ordinary LaTeX token survives the pair intact",
          pp._split_table_cells(pp.md_table_cell(r"\alpha + \beta"))[0]
          == r"\alpha + \beta")


# ---------------------------------------------------------------- PR151-012
def test_pr151_012_prior_audit_dispositions():
    print("\n== PR151-012: every prior-audit observation gets one disposition ==")
    sb = scratch("w2p12_")
    (sb / "prior_audit").mkdir()
    (sb / "prior_audit" / "UNRESOLVED.md").write_text(
        "# observations\n\n- base/main.md:12 — n differs between text and table (11 vs 12)\n"
        "- base/main.md:40 — the cited DOI resolves to a different article\n",
        encoding="utf-8")
    (sb / "guided_review").mkdir()
    (sb / "guided_review" / "findings.md").write_text("# summary\n\nnothing\n",
                                                      encoding="utf-8")
    probs = pp.prior_audit_disposition_problems(sb, {"findings": []})
    check("PR151-012 ignoring the whole handoff fails",
          len(probs) == 1 and "AU-OBS-001" in probs[0] and "AU-OBS-002" in probs[0],
          probs)
    fj = {"findings": [
        {"id": "F-001", "explanation": "from prior audit observation AU-OBS-001"},
        {"id": "F-002", "explanation": "from prior audit observation AU-OBS-002"},
    ]}
    (sb / "guided_review" / "findings.md").write_text(
        "prior AU-OBS-002: not reproducible in base/\n", encoding="utf-8")
    check("PR151-012 two dispositions for one id fail",
          any("more than one" in p for p in pp.prior_audit_disposition_problems(sb, fj)),
          pp.prior_audit_disposition_problems(sb, fj))
    fj = {"findings": [{"id": "F-001",
                        "explanation": "from prior audit observation AU-OBS-001"}]}
    check("PR151-012 one finding + one not-reproducible note pass",
          pp.prior_audit_disposition_problems(sb, fj) == [],
          pp.prior_audit_disposition_problems(sb, fj))
    fj = {"findings": [{"id": "F-001",
                        "explanation": "from prior audit observation AU-OBS-099"}]}
    check("PR151-012 an unknown observation id fails",
          any("not present" in p for p in pp.prior_audit_disposition_problems(sb, fj)),
          pp.prior_audit_disposition_problems(sb, fj))


# ---------------------------------------------------------------- PR151-024
def test_pr151_024_provisional_champion():
    print("\n== PR151-024: the auto-promotion exception is written down ==")
    rule5 = AGENTS.read_text(encoding="utf-8").split("Rule 5.")[1].split("Rule 6.")[0]
    check("PR151-024 AGENTS rule 5 names the operator override",
          "--champion-select" in rule5 and "provisional" in rule5, rule5[:200])
    check("PR151-024 the exception is labelled, not certified",
          "provisional: true" in rule5 and "certified: false" in rule5
          and "AUTO-PROMOTED — PROVISIONAL (NOT JUDGED)" in rule5)
    check("PR151-024 the code path still marks the decision unjudged/provisional",
          '"judged": False' in Path(
              WS / "paper_pipeline_parts/p08_selection_driver.py").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- PR151-033
def _response_fixture(tmp: Path, letter: str, map_rows: list):
    sb, src = tmp / "r1_response", tmp / "r1_concerns"
    (sb / "response").mkdir(parents=True)
    (sb / "target").mkdir()
    (sb / "target" / "manuscript.md").write_text("text\n", encoding="utf-8")
    (src / "concerns").mkdir(parents=True)
    (src / "concerns" / "JF_concerns.json").write_text(json.dumps({"concerns": [{
        "id": "C1", "quote": "The treated group improved markedly in this study.",
        "summary": "x", "disposition": "to-fix", "action": "edit"}]}), encoding="utf-8")
    (sb / "response" / "response_map.json").write_text(
        json.dumps({"rows": map_rows}), encoding="utf-8")
    (sb / "response" / "RESPONSE_TO_REVIEWERS.md").write_text(letter, encoding="utf-8")

    class Ctx:
        cfg = {}

        def sandbox_of(self, rec):
            return sb if rec.get("id") == "r1_response" else src

        def run(self, _rid):
            return {"id": "r1_concerns", "sandbox": str(src)}

    return Ctx(), sb


def test_pr151_033_letter_changes_binding():
    print("\n== PR151-033: the letter's Changes lines are bound to the map ==")
    check("PR151-033 the Changes parser finds each cited path",
          pp.response_letter_change_paths(
              "## C1 - x\n**Changes:** manuscript.md:Results — a -> b\n"
              "**Changes:** figures/fig1.png:panel A — c -> d\n")
          == {"C1": ["manuscript.md", "figures/fig1.png"]})
    tmp = scratch("w2p33_")
    letter = ('## C1 - x\n**Comment:** "The treated group improved markedly in this study."'
              '\n**Response:** ok\n**Changes:** other.md:Results — a -> b\n')
    ctx, sb = _response_fixture(tmp, letter, [{
        "id": "C1", "status": "addressed", "response": "ok",
        "changes": [{"file": "manuscript.md", "location": "Results",
                     "before": "a", "after": "b"}]}])
    saved = {}
    for name in ("original_submission_staging_problems", "structured_output_problems",
                 "inherited_structured_output_notes", "input_mismatches", "_marker_checks"):
        saved[name] = getattr(pp, name)
        setattr(pp, name, (lambda *a, **k: None) if name == "_marker_checks"
                else (lambda *a, **k: []))
    try:
        _ok, errs, _w, _x = pp.postcheck_response(
            ctx, {"id": "r1_response", "round": 1, "kind": "response"})
        check("PR151-033 a change the map does not record fails",
              any("letter" in e and "other.md" in e for e in errs), errs[:3])
        letter2 = ('## C1 - x\n**Comment:** "The treated group improved markedly in this study."'
                   '\n**Response:** ok\n**Changes:** manuscript.md:Results — a -> b\n')
        (sb / "response" / "RESPONSE_TO_REVIEWERS.md").write_text(letter2, encoding="utf-8")
        _ok2, errs2, _w2, _x2 = pp.postcheck_response(
            ctx, {"id": "r1_response", "round": 1, "kind": "response"})
        check("PR151-033 the same path in both outputs passes",
              not any("letter" in e for e in errs2), errs2[:3])
    finally:
        for name, fn in saved.items():
            setattr(pp, name, fn)


# ---------------------------------------------------------------- PR151-037
def test_pr151_037_conflict_validation():
    print("\n== PR151-037: LLM conflicts are bound to the real panel ==")
    op = [{"judge_run": "r1_judge_w1_j1", "judge_index": 1, "target": "w1",
           "opponent": "a2", "score": 3, "reason": "n=11 while the table says 12.",
           "basis": "results", "resolved": [],
           "introduced": [{"check": "M4", "tier": "correctness",
                           "severity": "major", "evidence": "n=11 vs 12"}]}]
    good = [{"member": "w1", "opponent": "a2", "judges": ["r1_judge_w1_j1"],
             "summary": "x",
             "evidence": [{"judge_run": "r1_judge_w1_j1",
                           "text": "n=11 while the table says 12"}]}]
    kept, rejected = pp._validate_llm_conflicts(good, op)
    check("PR151-037 a quoted, real conflict survives", len(kept) == 1 and not rejected,
          (kept, rejected))
    for label, bad in (
            ("a nonexistent version", [dict(good[0], member="w9")]),
            ("a nonexistent judge run", [dict(good[0], judges=["r9_fake"])]),
            ("an invented quote", [dict(good[0], evidence=[
                {"judge_run": "r1_judge_w1_j1", "text": "a sentence no judge wrote"}])])):
        kept2, rejected2 = pp._validate_llm_conflicts(bad, op)
        check(f"PR151-037 {label} is dropped with a reason",
              not kept2 and bool(rejected2), rejected2)
    # One judge run scores several opponents; the quote must bind to the named
    # pair's own opinion, not to whichever comparison of that run came last.
    two_ops = [dict(op[0]),
               dict(op[0], opponent="a3", reason="the abstract promises a result the "
                    "table does not carry.", basis="completeness", introduced=[])]
    first_pair = [dict(good[0])]
    kept3, rejected3 = pp._validate_llm_conflicts(first_pair, two_ops)
    check("PR151-037 a quote from the first of one run's comparisons survives",
          len(kept3) == 1 and not rejected3, (kept3, rejected3))
    cross_pair = [dict(good[0], evidence=[
        {"judge_run": "r1_judge_w1_j1",
         "text": "the abstract promises a result the table does not carry"}])]
    kept4, rejected4 = pp._validate_llm_conflicts(cross_pair, two_ops)
    check("PR151-037 a quote from another comparison of the same run is dropped",
          not kept4 and bool(rejected4), rejected4)


# ---------------------------------------------------------------- PR151-068
def test_pr151_068_decidable_pairs():
    print("\n== PR151-068: an undecidable class is not a scored difference ==")
    block = pp.judge_discovery_block()
    check("PR151-068 the judge is told both sides must be decidable",
          "BOTH SIDES MUST BE DECIDABLE" in block, block[-1200:])
    check("PR151-068 a limitation yields an explicit unknown, not a clean side",
          "unknown -- counterpart undecidable" in block
          and "award NO row" in block)


# ---------------------------------------------------------------- PR151-072
def test_pr151_072_retry_archive():
    print("\n== PR151-072: the complete retry list is in the sandbox ==")
    errs = [f"error {i}: " + ("x" * 180) for i in range(1, 101)]
    rec = {"attempts_log": [{"ok": False, "attempt": 1, "errors": errs,
                             "n_errors": len(errs), "warnings": []}],
           "attempts": 1}
    sb = scratch("w2p72_")
    note = pp.prior_failure_block(rec, sb)
    check("PR151-072 the in-sandbox archive exists",
          (sb / "PREVIOUS_ATTEMPT_ERRORS.md").is_file())
    full = (sb / "PREVIOUS_ATTEMPT_ERRORS.md").read_text(encoding="utf-8")
    check("PR151-072 every error reaches the archive",
          all(f"error {i}:" in full for i in (1, 50, 100)))
    lines = note.splitlines()
    pointer_at = next((i for i, line in enumerate(lines)
                       if "PREVIOUS_ATTEMPT_ERRORS.md" in line), None)
    first_error = next((i for i, line in enumerate(lines) if "error 1:" in line), None)
    check("PR151-072 the pointer precedes the truncated error list",
          pointer_at is not None and first_error is not None
          and pointer_at < first_error, (pointer_at, first_error))
    error_lines = [line for line in lines if ". error " in line]
    check("PR151-072 the inline cut falls on a line boundary, not inside an error",
          error_lines and all(line.rstrip().endswith("x" * 180) for line in error_lines),
          [len(x) for x in error_lines[-3:]])


# ---------------------------------------------------------------- PR151-078
def test_pr151_078_cold_start_ids():
    print("\n== PR151-078: the cold-start id block has a lossless overflow ==")
    used = [f"X-{i}" for i in range(901, 1000)]
    out, remap = pp.cold_start_findings_for_merge(used, [{"id": "X-950"}])
    check("PR151-078 the 100th finding moves to X-9001",
          out and out[0]["id"] == "X-9001", (out, remap))
    check("PR151-078 X-9001 is inside the reserved block",
          bool(pp.COLD_START_ID_RE.match("X-9001")))
    try:
        pp.cold_start_findings_for_merge(
            used + [f"X-{i}" for i in range(9001, 10000)], [{"id": "X-950"}])
        check("PR151-078 both blocks exhausted -> named refusal", False)
    except RuntimeError as e:
        check("PR151-078 both blocks exhausted -> named refusal",
              "X-9001..X-9999" in str(e), str(e))
    prompt = pp.cold_start_review_prompt(
        scratch("w2p78prompt_"), "r1_cold_start_review", 1) \
        if hasattr(pp, "cold_start_review_prompt") else ""
    if prompt:
        check("PR151-078 the prompt documents the four-digit overflow",
              "X-9001" in prompt and "X-9999" in prompt)


# ---------------------------------------------------------------- PR151-081
def test_pr151_081_revision_audit_checklist():
    print("\n== PR151-081: the revision audit gets no general-review checklist ==")
    sb = scratch("w2p81_")
    prompt = pp.revision_audit_prompt(sb, "r1_revision_audit", 1)
    check("PR151-081 the adopted M/J checklist is not appended",
          "THE ADOPTED CHECKS" not in prompt)
    check("PR151-081 the shared decision rules are still present",
          "SHARED DECISION RULES" in prompt or "DEFECT CLASS RULE" in prompt)
    check("PR151-081 the prompt still limits the object to the revision",
          "audit the REVISION" in prompt or "do not re-review" in prompt)


# ---------------------------------------------------------------- PR151-151
def test_pr151_151_normalization_gates():
    print("\n== PR151-151: E9b has pre- and post-normalization gates ==")
    text = RULES.read_text(encoding="utf-8")
    check("PR151-151 the two gates are named",
          "PRE-NORMALIZATION" in text and "POST-NORMALIZATION" in text)
    check("PR151-151 the deferred rows are a named set",
          all(x in text for x in ("FMT-S8", "FMT-S6", "FMT-P4", "FMT-G1", "FMT-IM1")))
    check("PR151-151 the delivered-package sentence is no longer absolute",
          "must show no mechanical row and no new editorial instance" not in text)
    appendix = ADDRESS.read_text(encoding="utf-8")
    check("PR151-151 the standalone prompt appendix is in sync",
          "PRE-NORMALIZATION" in appendix and "POST-NORMALIZATION" in appendix)


# ---------------------------------------------------------------- PR151-067
def test_pr151_067_reference_contradiction():
    print("\n== PR151-067: a broken blinded path is not scored as a defect ==")
    sb = scratch("w2p67_")
    prompt = pp.judge_prompt(sb, "r1_judge", 1, "w1", 1, 2, ["x"])
    check("PR151-067 the judge prompt still allows scoring a TEXTUAL stale reference",
          "still naming an old file name" in prompt or "stale reference" in prompt)
    check("PR151-067 a path that does not resolve is never itself a scored defect",
          "NEVER" in prompt and "itself a scored defect" in prompt)
    check("PR151-067 an undecidable path becomes a named limitation",
          "named LIMITATION" in prompt)


# ---------------------------------------------------------------- PR151-069
def test_pr151_069_response_removal():
    print("\n== PR151-069: a justified whole-file deletion can be represented ==")
    tmp = scratch("w2p69_")
    letter = ('## C1 - x\n**Comment:** "The treated group improved markedly in this study."'
              '\n**Response:** removed the obsolete appendix.\n'
              '**Changes:** old.md:whole file — obsolete appendix -> removed\n')
    ctx, sb = _response_fixture(tmp, letter, [{
        "id": "C1", "status": "addressed", "response": "removed the obsolete appendix.",
        "changes": [{"file": "old.md", "location": "whole file",
                     "operation": "remove", "before": "obsolete appendix", "after": ""}]}])
    (sb / "feedback" / "original_submission").mkdir(parents=True)
    (sb / "feedback" / "original_submission" / "old.md").write_text(
        "obsolete appendix\n", encoding="utf-8")
    saved = {}
    for name in ("original_submission_staging_problems", "structured_output_problems",
                 "inherited_structured_output_notes", "input_mismatches", "_marker_checks"):
        saved[name] = getattr(pp, name)
        setattr(pp, name, (lambda *a, **k: None) if name == "_marker_checks"
                else (lambda *a, **k: []))
    try:
        _ok, errs, _w, _x = pp.postcheck_response(
            ctx, {"id": "r1_response", "round": 1, "kind": "response"})
        check("PR151-069 a removal verified against the preimage passes",
              not any("remove" in e or "does not exist" in e for e in errs), errs[:4])
        (sb / "target" / "old.md").write_text("still here\n", encoding="utf-8")
        _ok2, errs2, _w2, _x2 = pp.postcheck_response(
            ctx, {"id": "r1_response", "round": 1, "kind": "response"})
        check("PR151-069 a `remove` of a file the package still carries fails",
              any("still carries" in e for e in errs2), errs2[:4])
    finally:
        for name, fn in saved.items():
            setattr(pp, name, fn)


# ---------------------------------------------------------------- PR151-036
def test_pr151_036_before_after_spans():
    print("\n== PR151-036: a change's before/after spans are bound to packages ==")
    tmp = scratch("w2p36_")
    letter = ('## C1 - x\n**Comment:** "The treated group improved markedly in this study."'
              '\n**Response:** rewrote the sentence.\n'
              '**Changes:** manuscript.md:Results — old -> new\n')
    ctx, sb = _response_fixture(tmp, letter, [{
        "id": "C1", "status": "addressed", "response": "rewrote it.",
        "changes": [{"file": "manuscript.md", "location": "Results",
                     "before": "The old sentence was here.",
                     "after": "The revised sentence is now here."}]}])
    (sb / "target" / "manuscript.md").write_text(
        "The revised sentence is now here.\n", encoding="utf-8")
    (sb / "previous_package").mkdir()
    (sb / "previous_package" / "manuscript.md").write_text(
        "The old sentence was here.\n", encoding="utf-8")
    saved = {}
    for name in ("original_submission_staging_problems", "structured_output_problems",
                 "inherited_structured_output_notes", "input_mismatches", "_marker_checks"):
        saved[name] = getattr(pp, name)
        setattr(pp, name, (lambda *a, **k: None) if name == "_marker_checks"
                else (lambda *a, **k: []))
    try:
        _ok, errs, _w, _x = pp.postcheck_response(
            ctx, {"id": "r1_response", "round": 1, "kind": "response"})
        check("PR151-036 a verbatim before/after pair passes",
              not any("span" in e for e in errs), errs[:4])
        (sb / "response" / "response_map.json").write_text(json.dumps({"rows": [{
            "id": "C1", "status": "addressed", "response": "rewrote it.",
            "changes": [{"file": "manuscript.md", "location": "Results",
                         "before": "A sentence nobody ever wrote there.",
                         "after": "A revision that does not exist in the file."}]}]}),
            encoding="utf-8")
        _ok2, errs2, _w2, _x2 = pp.postcheck_response(
            ctx, {"id": "r1_response", "round": 1, "kind": "response"})
        check("PR151-036 an invented before/after pair fails",
              sum(1 for e in errs2 if "span" in e) >= 2, errs2[:4])
        shutil.rmtree(sb / "previous_package")
        _ok3, errs3, _w3, _x3 = pp.postcheck_response(
            ctx, {"id": "r1_response", "round": 1, "kind": "response"})
        check("PR151-036 an invented after span still fails without previous_package",
              any("`after` span" in e for e in errs3), errs3[:4])
    finally:
        for name, fn in saved.items():
            setattr(pp, name, fn)


# ---------------------------------------------------------------- PR151-071
def test_pr151_071_literal_tokens():
    print("\n== PR151-071: literal prompt values survive every placeholder pass ==")
    tmp = scratch("w2p71_")
    sandbox = tmp / "@@ROUND@@_@@CAPTION_LIMIT@@_@@MARKER_ROOT@@_@@SELFCHECK@@"
    sandbox.mkdir()
    prior = ("prev error: the prompt had @@ROUND@@, @@CAPTION_LIMIT@@, "
             "@@MARKER_ROOT@@ and @@SELFCHECK@@ literally")
    review = pp.review_prompt(sandbox, "r1_guided_review", 2, prior_failure=prior)
    revise = pp.revise_prompt(sandbox, "r1_a2_revise", 2, prior_failure=prior)
    for label, prompt in (("review", review), ("revise", revise)):
        check(f"PR151-071 {label} prompt keeps a literal sandbox path",
              str(sandbox.resolve()) in prompt)
        check(f"PR151-071 {label} prompt keeps a literal prior-failure diagnostic",
              prior in prompt)


# ---------------------------------------------------------------- PR151-035
def test_pr151_035_seed_coverage():
    print("\n== PR151-035: every seeded feedback block needs a disposition ==")
    sb = scratch("w2p35_")
    (sb / "concerns").mkdir()
    (sb / "feedback").mkdir()
    seed = {"candidates": [
        {"seed_id": "S001", "heading": "Reviewer 1", "source": "letter.txt"},
        {"seed_id": "S002", "heading": "2. Statistics", "source": "letter.txt"}]}
    (sb / "feedback" / "CONCERN_SEED.json").write_text(json.dumps(seed), encoding="utf-8")
    rows = [{"id": "R1-1"}]
    check("PR151-035 a single valid concern cannot stand in for the whole seed",
          any("SEED_COVERAGE" in p for p in
              pp.journal_seed_coverage_problems(sb, seed, rows)),
          pp.journal_seed_coverage_problems(sb, seed, rows))
    (sb / "concerns" / "SEED_COVERAGE.md").write_text(
        "| seed id | concern ids | disposition |\n|---|---|---|\n"
        "| S001 | R1-1 | enumerated |\n"
        "| S002 | — | skipped — the reviewer thanks the authors |\n",
        encoding="utf-8")
    check("PR151-035 a complete seed inventory passes",
          pp.journal_seed_coverage_problems(sb, seed, rows) == [],
          pp.journal_seed_coverage_problems(sb, seed, rows))
    (sb / "concerns" / "SEED_COVERAGE.md").write_text(
        "| seed id | concern ids | disposition |\n|---|---|---|\n"
        "| S001 | R1-1 | enumerated |\n", encoding="utf-8")
    check("PR151-035 an undisposed seed block fails",
          any("S002" in p for p in
              pp.journal_seed_coverage_problems(sb, seed, rows)),
          pp.journal_seed_coverage_problems(sb, seed, rows))


def main() -> int:
    for fn in (test_pr151_007_occurrence_identity, test_pr151_008_cell_roundtrip,
               test_pr151_012_prior_audit_dispositions, test_pr151_024_provisional_champion,
               test_pr151_033_letter_changes_binding, test_pr151_037_conflict_validation,
               test_pr151_068_decidable_pairs, test_pr151_072_retry_archive,
               test_pr151_078_cold_start_ids, test_pr151_081_revision_audit_checklist,
               test_pr151_067_reference_contradiction, test_pr151_069_response_removal,
               test_pr151_071_literal_tokens,
               test_pr151_035_seed_coverage,
               test_pr151_036_before_after_spans,
               test_pr151_151_normalization_gates):
        fn()
    for p in TMPDIRS:
        shutil.rmtree(p, ignore_errors=True)
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s): " + "; ".join(FAILS))
        return 1
    print("ALL WAVE-2 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

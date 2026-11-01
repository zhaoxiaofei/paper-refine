#!/usr/bin/env python3
"""The 2026-11-02 stage-parity + contradiction-rule wave.

Run:  python3 .paper_test/test_fix_bugs_20261102_120000.py

Follow-up to the 2026-11-01 brief_communication incident: the same class of
defect was hunted across the OTHER stages and the skills, and every agent prompt
gained a contradiction-resolution rule.

  P1  The package-stage source gates (`email_address_change_problems`,
      `fact_token_change_problems`, the finding-tier regression scan) ran in the
      postcheck for rewrite/revise/integrate but in the pre-flight for NONE of
      them (the regression scan: revise only). A package that inferred an
      e-mail address passed the pre-flight and failed the postcheck.
  P2  The cold-start pre-flight tested only `is_file()` for COVERAGE.md, so a
      symlinked, unreadable or EMPTY file passed it and failed the postcheck.
  P3  The judge pre-flight never ran the target's FMT-CL1 family, so an M20
      artifact that ignored a cover letter stamped with the manuscript template
      passed it (the postcheck derives those rows from `code_side_evidence`,
      which needs the root; the format scan needs only the seeded policy).
  P4  Every LLM agent prompt now carries the contradiction-resolution rule:
      prohibition > this-run statement > more specific rule > the postcheck,
      with the surviving conflict REPORTED, never resolved by doing both.
  S1  The revision skill and its edit rules named the `[AUTHOR TO COMPLETE: ...]`
      scaffold as the default without the run's hand-off policy, which under
      `readme` forbids the marker in a document.
  S4  `sweeps.md` offered a bare `clean` as a coverage disposition, which the
      review gate REJECTS (it requires `clean -- basis: <artifact>`).
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []
RULE_MARK = "BEFORE YOU READ THE INSTRUCTIONS BELOW"


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fix_bugs_pipeline_1102", WS / "paper_pipeline.py")


def _marker(sb: Path, kind: str, run_id: str) -> None:
    (sb / "_pipeline_done.json").write_text(
        f'{{"stage": "{kind}", "run_id": "{run_id}", "round": 1, "status": "complete",'
        f' "error": null}}', encoding="utf-8")


# ---------------------------------------------------------------------------
# P1 -- the source gates reach the pre-flight for every package stage.
# ---------------------------------------------------------------------------
PAPER_EMAILS = "Correspondence: ada.lind@helsinki.fi and mart.kask@ut.ee.\n"


def _package_sandbox(root: Path, kind: str, pkg_name: str, document: str) -> Path:
    sb = root / kind
    sb.mkdir(parents=True)
    for area in ("base", "self", "non_revised", "raw_data"):
        (sb / area).mkdir()
        (sb / area / "brief.md").write_text(PAPER_EMAILS, encoding="utf-8")
    pkg = sb / pkg_name
    pkg.mkdir()
    (pkg / "brief.md").write_text(document, encoding="utf-8")
    _marker(sb, kind, f"r1_{kind}")
    return sb


def test_p1_source_gates() -> None:
    print("\n== P1: package-stage source gates run in the pre-flight ==")
    root = scratch("p1_")
    inferred = PAPER_EMAILS + "New contact: someone@elsewhere.example\n"
    for kind, pkg_name in (("revise", "revised"), ("rewrite", "rewritten"),
                           ("integrate", "integrated")):
        sb = _package_sandbox(root, kind, pkg_name, inferred)
        errs, _warns = pp.stage_source_gates(sb, kind, sb / pkg_name)
        check(f"P1 {kind}: an inferred address fails the source gate",
              any("introduces e-mail address" in e for e in errs), str(errs)[:200])
        _ok, serrs, _sw = pp.sandbox_selfcheck(sb, kind, f"r1_{kind}", 1)
        check(f"P1 {kind}: the pre-flight reports it",
              any("introduces e-mail address" in e for e in serrs), str(serrs)[:200])

    # The corpus-verbatim address stays accepted (no false positive).
    clean = _package_sandbox(root, "revise_ok", "revised", PAPER_EMAILS)
    errs, _w = pp.stage_source_gates(clean, "revise", clean / "revised")
    check("P1 an unchanged address passes", not errs, str(errs)[:160])


# ---------------------------------------------------------------------------
# P2 -- the cold-start coverage file's full contract.
# ---------------------------------------------------------------------------
COLD_FINDINGS = """{
  "findings": [],
  "checked": [{"area": "whole submission", "files": ["base/brief.md"],
               "classes": ["correctness"], "result": "no defect found"}]
}
"""


def _cold_sandbox(root: Path, name: str, coverage_writer) -> Path:
    sb = root / name
    (sb / pp.COLD_START_DIR).mkdir(parents=True)
    (sb / pp.COLD_START_FINDINGS_REL).write_text(COLD_FINDINGS, encoding="utf-8")
    coverage_writer(sb / pp.COLD_START_COVERAGE_REL)
    _marker(sb, "cold_start_review", "r1_cold_start_review")
    return sb


def test_p2_cold_start_coverage() -> None:
    print("\n== P2: the cold-start coverage file is checked fully ==")
    root = scratch("p2_")

    def empty(p):
        p.write_text("   \n", encoding="utf-8")

    def good(p):
        p.write_text("# COVERAGE\n\nAreas examined: the whole submission (1 file).\n", encoding="utf-8")

    sb = _cold_sandbox(root, "empty", empty)
    _ok, errs, _w = pp.sandbox_selfcheck(sb, "cold_start_review", "r1_cold_start_review", 1)
    check("P2 an EMPTY coverage file fails the pre-flight",
          any("is EMPTY" in e for e in errs), str(errs)[:200])

    sb = _cold_sandbox(root, "linked", good)
    target = sb / "target_coverage.md"
    target.write_text("# COVERAGE\n\nbody\n", encoding="utf-8")
    cov = sb / pp.COLD_START_COVERAGE_REL
    cov.unlink()
    cov.symlink_to(target)
    _ok2, errs2, _w2 = pp.sandbox_selfcheck(sb, "cold_start_review", "r1_cold_start_review", 1)
    check("P2 a SYMLINKED coverage file fails the pre-flight",
          any("could not be read" in e or "is missing" in e for e in errs2), str(errs2)[:200])

    sb = _cold_sandbox(root, "good", good)
    _ok3, errs3, _w3 = pp.sandbox_selfcheck(sb, "cold_start_review", "r1_cold_start_review", 1)
    check("P2 a real coverage file passes",
          not [e for e in errs3 if "COVERAGE" in e], str(errs3)[:200])


# ---------------------------------------------------------------------------
# P3 -- the judge pre-flight runs the target's FMT-CL1 family.
# ---------------------------------------------------------------------------
def test_p3_judge_cover_letter() -> None:
    print("\n== P3: the judge pre-flight reproduces the FMT-CL1 family ==")
    # A text-only target carries no FMT-CL1 row, so the family must stay silent
    # (no false positive) ...
    root = scratch("p3_")
    sb = root / "judge"
    (sb / "target").mkdir(parents=True)
    (sb / "target" / "paper.md").write_text("# paper\n\nText only.\n", encoding="utf-8")
    (sb / "judge_review" / "artifacts").mkdir(parents=True)
    (sb / "judge_review" / "artifacts" / "M20_formatting.md").write_text(
        "| rule | disposition |\n|---|---|\n| FMT-T1 | OK — checked |\n", encoding="utf-8")
    _marker(sb, "judge", "judge_tok_j1")
    (sb / "scores.json").write_text("{}", encoding="utf-8")
    _ok, errs, _w = pp.sandbox_selfcheck(sb, "judge", "judge_tok_j1", 0)
    check("P3 a text-only target raises no cover-letter problem",
          not [e for e in errs if "FMT-CL1" in e], str(errs)[:200])

    # ... and the detector itself still refuses a silent M20 when the target has
    # the row (the helper the pre-flight now calls).
    problems = pp.judge_cover_letter_artifact_problems(
        sb, [{"rule": "FMT-CL1", "document": "letter.docx"}])
    check("P3 a silent M20 is refused when the target carries FMT-CL1",
          bool(problems) and "FMT-CL1" in problems[0], str(problems)[:200])

    # Static wiring: the pre-flight branch calls it.
    src = (WS / "paper_pipeline_parts" / "p07_stage_quality_journal.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "sandbox_selfcheck":
            seg = ast.get_source_segment(src, node) or ""
            found = "judge_cover_letter_artifact_problems" in seg
    check("P3 the judge pre-flight branch calls the cover-letter family", found)


def test_p4b_journal_finding_list_and_preview_claim() -> None:
    print("\n== P4b: the journal pre-flights and the preview claim ==")
    # The `concerns` pre-flight used to run only the ledger schema; the finding
    # list the scoped revision consumes is a postcheck error family too.
    sb = scratch("p4b_concerns_")
    (sb / "feedback" / "files").mkdir(parents=True)
    (sb / "feedback" / "text").mkdir(parents=True)
    quote = "the sample is too small for the claim"
    (sb / "feedback" / "files" / "r.txt").write_text(f"Reviewer: {quote}.", encoding="utf-8")
    (sb / "feedback" / "text" / "r.txt").write_text(f"Reviewer: {quote}.", encoding="utf-8")
    (sb / pp.JOURNAL_CONCERNS_JSON_REL).parent.mkdir(parents=True, exist_ok=True)
    (sb / pp.JOURNAL_CONCERNS_JSON_REL).write_text(
        '{"concerns": [{"id": "C1", "quote": "%s", "disposition": "to-fix",'
        ' "severity": "major", "action": "analysis", "summary": "the claim outruns the data"}]}'
        % quote, encoding="utf-8")
    _marker(sb, "concerns", sb.name)
    _ok, errs, _w = pp.sandbox_selfcheck(sb, "concerns", sb.name, 1)
    check("P4b the concerns pre-flight reports a missing finding list",
          any("findings.json is missing/unparsable" in e for e in errs), str(errs)[:200])

    # The shared prompt text must not claim more than the pre-flight can do: the
    # root-state families stay at postcheck time.
    sb_block = pp.selfcheck_block("revise", "r1_a2_revise", 1)
    check("P4b the self-check block says a pass is a preview, not a certification",
          "PREVIEW, NEVER A CERTIFICATION" in " ".join(sb_block.split()))
    j_block = pp.judge_selfcheck_block("judge_tok_j1")
    check("P4b the judge block says the same",
          "PREVIEW, NEVER A CERTIFICATION" in " ".join(j_block.split()))

    # The marker sentence must not tell a journal session the marker is the last
    # step and then add a pre-marker instruction without saying so.
    src = (WS / "paper_pipeline_parts" / "p07_stage_quality_journal.py").read_text(
        encoding="utf-8")
    check("P4b the journal marker sentence points at the pre-flight below",
          src.count("as the very LAST step, AFTER the pre-flight below.") == 3,
          str(src.count("as the very LAST step, AFTER the pre-flight below.")))


# ---------------------------------------------------------------------------
# P4 -- every agent prompt carries the contradiction rule.
# ---------------------------------------------------------------------------
def test_p4_contradiction_rule() -> None:
    print("\n== P4: every agent prompt carries the contradiction rule ==")
    sb = Path("/tmp/sb")
    prompts = {
        "review": pp.review_prompt(sb, "r1_guided_review", 1),
        "review_split_a": pp.review_prompt(sb, "r1_guided_review_a", 1, split="phases"),
        "cold_start_review": pp.cold_start_review_prompt(sb, "r1_cold_start_review", 1),
        "audit": pp.audit_prompt(sb, "r1_audit", 1),
        "revise": pp.revise_prompt(sb, "r1_a2_revise", 1),
        "integrate": pp.integrate_prompt(sb, "r1_i1", 1, "v1", ["v2"]),
        "rewrite": pp.rewrite_prompt(sb, "r1_w1", 1),
        "judge": pp.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, []),
        "revision_audit": pp.revision_audit_prompt(sb, "r1_revision_audit", 1),
        "revision_repair": pp.revision_repair_prompt(sb, "r1_repair", 1, 3),
        "defect_audit": pp._defect_audit_prompt(1, 4),
        "judge_conflict": pp._judge_conflict_agent_prompt(1),
        "add_venue": pp.add_venue_prompt("generic", Path("/tmp/x")),
        "resume": pp.resume_prompt({"id": "r1_a2_revise", "kind": "revise", "round": 1},
                                   ["p"], "why", 0),
    }
    for name, text in prompts.items():
        check(f"P4 {name} carries the rule", RULE_MARK in text,
              f"missing in {name}")
        check(f"P4 {name} carries it once", text.count(RULE_MARK) == 1,
              f"{text.count(RULE_MARK)} copies")
    # The ctx-built prompts: verify their FUNCTIONS reference the constant (they
    # need a full root to render, so this is the build-time guarantee).
    wired = {
        "paper_pipeline_parts/p04_utils.py": ["apply_template_prompt",
                                              "apply_guideline_conform_prompt"],
        "paper_pipeline_parts/p06_postchecks.py": ["resume_prompt", "repair_prompt"],
        "paper_pipeline_parts/p07_stage_quality_journal.py": ["feedback_prompt",
                                                              "concerns_prompt",
                                                              "response_prompt"],
        "paper_pipeline_parts/p11_defect_audit.py": ["_defect_audit_prompt"],
        "paper_pipeline_parts/p12_conflicts_decide.py": ["_judge_conflict_agent_prompt"],
        "paper_pipeline_parts/p09_setup.py": ["add_venue_prompt"],
        "paper_pipeline_parts/p19_profiles.py": ["page_stage_prompt"],
    }
    for rel, names in wired.items():
        src = (WS / rel).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name in names:
                seg = ast.get_source_segment(src, node) or ""
                check(f"P4 {rel.split('/')[-1]}:{node.name} is wired",
                      "CONTRADICTION_RULE" in seg)
    # The rule states the precedence AND the reporting duty, and stays free of
    # the judges' forbidden provenance vocabulary.
    rule = pp.CONTRADICTION_RULE
    flat_rule = " ".join(rule.split())
    check("P4 the rule names the four precedence levels",
          all(k in flat_rule for k in ("PROHIBITION", "THIS RUN", "SPECIFIC",
                                       "ORCHESTRATOR CHECKS")))
    check("P4 the rule requires the surviving conflict to be REPORTED",
          "NAME the conflict" in flat_rule and "final report" in flat_rule)
    check("P4 the rule forbids satisfying both readings at once",
          "doing both at once" in flat_rule)
    check("P4 the rule does not point at a pre-flight block every prompt lacks",
          "the pre-flight command where this prompt gives you one" in flat_rule)
    for pat, label in ((r"\bround\b", "round"), (r"\barm\b", "arm"),
                       (r"\brewrite\b", "rewrite"), (r"\brevised\b", "revised"),
                       (r"\brevision\b", "revision"), (r"\bintegration\b", "integration"),
                       (r"\bmerge\b", "merge"), (r"\bchampion\b", "champion"),
                       (r"CHANGELOG", "CHANGELOG"), (r"MANUAL_STEPS", "MANUAL_STEPS"),
                       (r"AUTHOR TO COMPLETE", "the marker token")):
        import re as _re
        check(f"P4 the rule carries no {label}", not _re.search(pat, flat_rule, _re.I))
    # It must not be the AGENTS.md rule verbatim.
    agents = (WS / "AGENTS.md").read_text(encoding="utf-8")
    agents_rule = agents[agents.index("Last rule."):]
    check("P4 the rule is not the AGENTS.md last rule verbatim",
          "the earlier text wins" not in rule
          and "the sentence that appears first prevails" not in rule
          and rule.strip() not in agents_rule)


# ---------------------------------------------------------------------------
# S1 / S4 -- the skill surfaces agree with the pipeline.
# ---------------------------------------------------------------------------
def test_skill_surfaces() -> None:
    print("\n== S1/S4: the skill surfaces agree with the pipeline ==")
    sweeps = (WS / "paper-skills/paper-review/references/sweeps.md").read_text(encoding="utf-8")
    flat = " ".join(sweeps.split())
    check("S4 sweeps.md no longer offers a bare `clean` disposition",
          "N findings / clean / unable" not in sweeps)
    check("S4 sweeps.md shows `clean -- basis:`",
          "clean — basis:" in sweeps or "clean -- basis:" in sweeps)
    check("S4 sweeps.md names the four accepted shapes",
          all(s in flat for s in ("N findings", "clean — basis:", "unable — <reason>",
                                  "out of scope — <reason>")))

    for rel in ("paper-skills/paper-revise/SKILL.md",
                "paper-skills/prompts/adress_issues.prompt.md",
                "paper-skills/paper-revise/references/edit_rules.md"):
        text = " ".join((WS / rel).read_text(encoding="utf-8").split())
        check(f"S1 {rel} qualifies the marker default with the run's policy",
              "hand-off policy" in text and "outranks this default" in text,
              rel)


def cleanup() -> None:
    import shutil
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_p1_source_gates()
        test_p2_cold_start_coverage()
        test_p3_judge_cover_letter()
        test_p4_contradiction_rule()
        test_p4b_journal_finding_list_and_preview_claim()
        test_skill_surfaces()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-11-02 STAGE-PARITY + CONTRADICTION-RULE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

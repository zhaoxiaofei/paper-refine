#!/usr/bin/env python3
"""Regression checks for the 2026-11-06 verified fixes.

Run:  python3 .paper_test/test_fix_bugs_20261106.py

Each block pins one confirmed defect on the current tree:

  * the judge prompt said "the first tier in which the two versions differ
    decides" while the same prompt's formula takes the first tier whose NET is
    not zero -- a net-zero higher tier would have been read as deciding;
  * the revise prompt invited a reviser to re-open an audited-and-dropped
    finding, which would be filing and applying a new finding in one run
    (AGENTS.md rule 1A);
  * the cold-start prompt never stated the hard verifier budget (50 scripts /
    600 s aggregate) that its postcheck enforces, so a valid 51-script attempt
    failed after the fact;
  * the bounded-repair plan required a non-empty `correct`, so a confirmed pure
    DELETION could not be represented although the repair ledger and span audit
    support an empty postimage;
  * the self-check command interpolated the driver path inside double quotes,
    where a legal `$` or backtick is expanded by the shell;
  * medium's paged rules are written to one fixed path, so the revision audit
    and bounded repair (which run in the revise sandbox) overwrote the
    reviser's nine sections while its PROMPT.md still pointed at the file;
  * the persistent-PDF cache and the in-process renderer accepted any nonempty
    file as a successful render (no `%PDF-` header or `%%EOF` trailer), so a
    broken converter could be recorded `ok` and its garbage reused for every
    later run whose source digest was unchanged;
  * the M4 AUC pattern accepted only 0.x and 1.0, so an impossible `AUC = 1.2`
    produced no occurrence at all and the inventory could not expose it;
  * the Zotero stage clauses called every citation without a live field a
    preservation defect, so a LaTeX/plain-text corpus -- where citations never
    have fields -- would be flagged (and scored) as if every citation were
    unlinked; an originally plain citation is now explicitly exempt.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
if str(WS) not in sys.path:
    sys.path.insert(0, str(WS))

import paper_pipeline as pp  # noqa: E402

FAILS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"[ok ] {name}")
    else:
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))
        FAILS.append(name)


def flat(value: str) -> str:
    return " ".join(str(value or "").split())


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


# ---------------------------------------------------------------------------
# 1. The judge's priority prose agrees with its own net-zero formula.
# ---------------------------------------------------------------------------
def test_judge_priority_uses_net_difference() -> None:
    print()
    print("== judge: the deciding tier is the first with a NON-ZERO NET ==")
    sb = scratch("jnet_")
    judge = flat(pp.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, []))
    check("judge: the priority sentence says NET difference",
          "the first tier whose NET difference is not zero decides the comparison" in judge,
          judge[:120])
    check("judge: the stale 'differ...decides' sentence is gone",
          "the first tier in which the two versions differ decides" not in judge)
    check("judge: the formula's net-zero rule is still stated",
          "the FIRST tier whose net is not zero DECIDES the comparison" in judge)
    # The basis field must keep the net-zero row exception: for a 0, the basis
    # names the highest tier that carries rows.
    check("judge: a net-zero comparison still names its row-bearing tier",
          "for a clean 0" in judge and "tier in which the two versions differ at all" in judge)


# ---------------------------------------------------------------------------
# 2. A dropped finding is not re-opened and patched by the reviser.
# ---------------------------------------------------------------------------
def test_reviser_does_not_reopen_dropped_findings() -> None:
    print()
    print("== revise: a dropped finding is routed to the next review, not patched ==")
    sb = scratch("rreopen_")
    prompt = flat(pp.revise_prompt(sb, "r1_a2_revise", 1, audit=True))
    check("revise: the audited-list rule still forbids re-litigation",
          "a dropped finding is NOT yours to re-litigate" in prompt)
    check("revise: the old re-opening permission is gone",
          "re-opening one requires new evidence" not in prompt)
    check("revise: the next-review route cites rule 1A",
          "rule 1A" in prompt and "NEXT round's review" in prompt)
    check("revise: the observation route is still stated",
          "audit/UNRESOLVED.md" in prompt and "observation for the" in prompt)


# ---------------------------------------------------------------------------
# 3. The cold-start prompt states the verifier budget its postcheck enforces.
# ---------------------------------------------------------------------------
def test_cold_start_verifier_budget_is_stated() -> None:
    print()
    print("== cold start: the prompt states the hard verifier budget ==")
    sb = scratch("cbudget_")
    prompt = flat(pp.cold_start_review_prompt(sb, "r1_cold_start_review", 1))
    check("cold start: the maximum number of verifiers is stated",
          f"at most {pp.COLD_START_REPRO_MAX_VERIFIERS} declared verifiers" in prompt,
          prompt[:160])
    check("cold start: the aggregate seconds budget is stated",
          f"{pp.COLD_START_REPRO_TOTAL_BUDGET} s" in prompt)
    check("cold start: the unrun verifier's failure is stated",
          "did not run FAILS the attempt" in prompt)
    # The numbers in the prompt must come from the same constants the postcheck
    # uses; a hard-coded copy would drift.
    check("cold start: the budgets are interpolated, not copied",
          str(pp.COLD_START_REPRO_MAX_VERIFIERS) in prompt
          and str(pp.COLD_START_REPRO_TOTAL_BUDGET) in prompt)


# ---------------------------------------------------------------------------
# 4. A bounded-repair plan can represent a pure deletion.
# ---------------------------------------------------------------------------
def _plan(sb: Path, rows: list) -> None:
    (sb / "revision_audit").mkdir(parents=True, exist_ok=True)
    (sb / "revised").mkdir(parents=True, exist_ok=True)
    (sb / "revision_audit" / "REPAIR_PLAN.json").write_text(
        json.dumps({"rows": rows}), encoding="utf-8")


def _row(**over) -> dict:
    row = {"id": "RP-001", "finding": "F-001", "file": "paper.md",
           "location": "Results, paragraph 3", "wrong": "the duplicated sentence",
           "correct": "the corrected sentence", "basis": "paper.md:12",
           "edit": "replace the duplicated sentence", "evidence": "the quote"}
    row.update(over)
    return row


def test_repair_plan_accepts_pure_deletion() -> None:
    print()
    print("== revision audit: REPAIR_PLAN represents a pure deletion ==")
    sb = scratch("rplan_")
    _plan(sb, [_row(correct="", edit="delete the duplicated sentence")])
    rows = pp._revision_plan_rows(sb)
    check("plan: a pure deletion (empty correct, quoted wrong) is valid",
          isinstance(rows, list) and len(rows) == 1 and rows[0]["correct"] == "",
          str(rows)[:200])

    _plan(sb, [_row(wrong="", edit="insert the missing sentence")])
    check("plan: a pure insertion (empty wrong) is still valid",
          isinstance(pp._revision_plan_rows(sb), list))

    _plan(sb, [_row(wrong="", correct="", edit="nothing to quote")])
    check("plan: a row with neither wrong nor correct is rejected",
          pp._revision_plan_rows(sb) is None)

    _plan(sb, [_row(correct="", basis="")])
    check("plan: an empty basis still invalidates the plan",
          pp._revision_plan_rows(sb) is None)

    prompt = flat(pp.revision_audit_prompt(scratch("rprompt_"), "r1_revision_audit", 1))
    check("plan: the auditor prompt documents the pure-deletion shape",
          "A PURE DELETION" in prompt and '"correct": ""' in prompt)


# ---------------------------------------------------------------------------
# 5. The self-check command is shell-quoted, not double-quoted.
# ---------------------------------------------------------------------------
def test_selfcheck_command_is_shell_quoted() -> None:
    print()
    print("== self-check: the ROOT driver is named by env var, not a literal path ==")
    real, real_fb = pp.pipeline_self_path, pp.pipeline_fallback_paths
    # A legal root path may carry `$` or a backtick. The prompt names the
    # environment variable; the orchestrator sets its value for the session.
    dangerous = "/tmp/paper-check-$PAPER_SELF_DIR/paper_pipeline.py"
    try:
        pp.pipeline_self_path = lambda: Path(dangerous)
        pp.pipeline_fallback_paths = lambda: []
        block = pp.selfcheck_block("revise", "r1_a2_revise", 1)
        env = pp.agent_session_env(Path("/tmp/paper-selfcheck-session"))
    finally:
        pp.pipeline_self_path, pp.pipeline_fallback_paths = real, real_fb
    check("selfcheck: the prompt names the exported ROOT driver",
          'python "$PAPER_PIPELINE_SELF" selfcheck' in block)
    check("selfcheck: no machine path is baked into the prompt",
          dangerous not in block)
    check("selfcheck: the session environment carries the ROOT driver",
          env.get("PAPER_PIPELINE_SELF") == dangerous,
          str(env.get("PAPER_PIPELINE_SELF")))
    check("selfcheck: the session environment carries the harness mount",
          env.get("PAPER_PIPELINE_MOUNT") == pp.HARNESS_PIPELINE_MOUNT,
          str(env.get("PAPER_PIPELINE_MOUNT")))
    got = subprocess.run(["bash", "-c", 'printf "%s" "$PAPER_PIPELINE_SELF"'],
                         capture_output=True, text=True, env=env)
    check("selfcheck: a literal `$` in the path survives the shell",
          got.returncode == 0 and got.stdout == dangerous,
          f"{got.stdout!r} != {dangerous!r}")
    check("selfcheck: the path is not merely double-quoted in prose",
          f'python "{dangerous}"' not in block)

    # The judge pre-flight carries the same env-var command.
    try:
        pp.pipeline_self_path = lambda: Path(dangerous)
        pp.pipeline_fallback_paths = lambda: []
        judge = pp.judge_selfcheck_block("judge_x_j1")
    finally:
        pp.pipeline_self_path, pp.pipeline_fallback_paths = real, real_fb
    check("selfcheck: the judge's pre-flight names the exported ROOT driver",
          'python "$PAPER_PIPELINE_SELF" selfcheck --sandbox . --stage judge' in judge)
    check("selfcheck: the judge's prompt carries no machine path",
          dangerous not in judge)


# ---------------------------------------------------------------------------
# 6. Medium's paged rules are per-stage when auxiliary sessions share a sandbox.
# ---------------------------------------------------------------------------
def test_medium_auxiliary_sidecar_does_not_overwrite_reviser() -> None:
    print()
    print("== medium: the audit/repair sidecars leave the reviser's rules intact ==")
    sb = scratch("rsidecar_") / "r1_a2_revise"
    sb.mkdir(parents=True)
    pp.revise_prompt(sb, "r1_a2_revise", 1, audit=True, execution_profile="medium")
    reviser_file = sb / "INSTRUCTIONS" / "PROFILE_RULES.md"
    before = reviser_file.read_text(encoding="utf-8")
    check("sidecar: the reviser's paged file is the documented path",
          reviser_file.is_file() and "_Stage: revise_" in before)
    sections = before.count("\n## ")

    audit = pp.revision_audit_prompt(sb, "r1_revision_audit", 1,
                                     execution_profile="medium")
    after = reviser_file.read_text(encoding="utf-8")
    audit_sidecar = sb / "INSTRUCTIONS" / "PROFILE_RULES_revision_audit.md"
    check("sidecar: the audit does not shorten the reviser's file",
          re.sub(r"\s+", " ", after) == re.sub(r"\s+", " ", before)
          and after.count("\n## ") == sections, f"{sections} -> {after.count(chr(10)+'## ')}")
    check("sidecar: the audit gets its own stage-named file",
          audit_sidecar.is_file() and "_Stage: revision_audit_" in
          audit_sidecar.read_text(encoding="utf-8"))
    check("sidecar: the audit prompt points at its own file",
          "PROFILE_RULES_revision_audit.md" in audit
          and "INSTRUCTIONS/PROFILE_RULES.md" not in audit)

    pp.revision_repair_prompt(sb, "r1_revision_repair", 1, 1,
                              execution_profile="medium")
    repair_sidecar = sb / "INSTRUCTIONS" / "PROFILE_RULES_revision_repair.md"
    check("sidecar: the bounded repair gets its own stage-named file",
          repair_sidecar.is_file()
          and "_Stage: revision_repair_" in repair_sidecar.read_text(encoding="utf-8"))
    check("sidecar: the reviser's file survives both auxiliary prompts",
          reviser_file.read_text(encoding="utf-8").count("\n## ") == sections)


# ---------------------------------------------------------------------------
# 7. A nonempty file is not a PDF: renderer output and the persistent cache
#    both require the header and the trailer.
# ---------------------------------------------------------------------------
def test_pdf_signature_and_cache() -> None:
    print()
    print("== PDFs: a nonempty file is not a render ==")
    d = scratch("pdfsig_")

    def write(name: str, data: bytes) -> Path:
        p = d / name
        p.write_bytes(data)
        return p

    good = write("good.pdf", b"%PDF-1.4\nbody\n" + b"x" * 3000 + b"\n%%EOF\n")
    no_eof = write("no_eof.pdf", b"%PDF-1.4\nbody\n")
    no_header = write("no_header.pdf", b"not a pdf\n" + b"x" * 3000)
    late_eof = write("late_eof.pdf",
                     b"%PDF-1.4\n" + b"x" * 5000 + b"%%EOF\n" + b"y" * 3000)
    empty = write("empty.pdf", b"")
    check("pdf: a complete PDF has no problem",
          pp.pdf_signature_problem(good) == "")
    check("pdf: a missing %%EOF trailer is reported",
          "%%EOF" in pp.pdf_signature_problem(no_eof))
    check("pdf: a missing %PDF- header is reported",
          "%PDF-" in pp.pdf_signature_problem(no_header))
    check("pdf: an %%EOF far from the end does not pass the trailer check",
          "%%EOF" in pp.pdf_signature_problem(late_eof))
    check("pdf: an empty file is reported", pp.pdf_signature_problem(empty) != "")

    import hashlib
    prev = {("label", "paper.docx"): {
        "ok": True, "sha256": "abc", "kind": "docx",
        "out_sha256": hashlib.sha256(good.read_bytes()).hexdigest()}}
    check("cache: a corrupt cached render is NOT reused",
          pp._reuse_pdf_record(prev, "label", "paper.docx", "abc", no_header,
                               "docx") is None)
    reused = pp._reuse_pdf_record(prev, "label", "paper.docx", "abc", good, "docx")
    check("cache: a complete cached render is reused",
          isinstance(reused, dict) and reused.get("cached") is True)
    check("cache: an unchanged source with a changed digest is not reused",
          pp._reuse_pdf_record(prev, "label", "paper.docx", "other", good,
                               "docx") is None)

    # A fake Word renderer that writes garbage must be a FAILED render, and the
    # garbage must not be moved into the output directory.
    docx = d / "paper.docx"
    docx.write_bytes(b"fake docx")
    out = d / "out"
    out.mkdir()
    bad_sh = d / "bad_word.sh"
    bad_sh.write_text('#!/bin/sh\necho "not a pdf" > "${1%.docx}.pdf"\n',
                      encoding="utf-8")
    bad_sh.chmod(0o755)
    res = pp.render_docx_visual(docx, out, ("word", str(bad_sh)), timeout=30,
                                page_images=False)
    check("render: a non-PDF renderer output is rejected",
          res.get("ok") is False and "non-PDF" in str(res.get("error")),
          str(res)[:180])
    check("render: the rejected output is not moved into place",
          not (out / "paper.pdf").exists())

    ok_sh = d / "ok_word.sh"
    ok_sh.write_text('#!/bin/sh\nprintf \'%%PDF-1.4\\nbody\\n%%%%EOF\\n\' > "${1%.docx}.pdf"\n',
                     encoding="utf-8")
    ok_sh.chmod(0o755)
    good_res = pp.render_docx_visual(docx, out, ("word", str(ok_sh)), timeout=30,
                                     page_images=False)
    check("render: a complete PDF output still succeeds",
          good_res.get("ok") is True and (out / "paper.pdf").is_file(),
          str(good_res)[:180])


# ---------------------------------------------------------------------------
# 8. An impossible AUC is still a labelled metric and must be inventoried.
# ---------------------------------------------------------------------------
def test_auc_out_of_range_is_inventoried() -> None:
    print()
    print("== M4: an impossible AUC value reaches the inventory ==")
    scripts = WS / "paper-skills" / "paper-review" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import extract_numbers as en
    # The explicit-assignment form takes a full numeric literal and the prose
    # form keeps the single-leading-digit guard, so the label has two patterns.
    aucs = [pat for label, pat in en.LABEL_PATTERNS if label == "AUC"]

    def auc_match(text):
        return next((m for pat in aucs if (m := pat.search(text))), None)

    cases = {
        "AUC = 1.2": "1.2",
        "AUC 2": "2",
        "AUC = 0.85": "0.85",
        "an AUC of 0.72": "0.72",
    }
    for text, want in cases.items():
        m = auc_match(text)
        check(f"AUC: {text!r} is inventoried as {want}",
              m is not None and m.group(1) == want,
              str(m.group(1)) if m else "no match")
    for text in ("AUC of 12 patients", "AUC 95%"):
        check(f"AUC: {text!r} is not read as an AUC",
              auc_match(text) is None,
              str(auc_match(text).group(0)) if auc_match(text) else "")


# ---------------------------------------------------------------------------
# 9. A plain citation is not a lost live field.
# ---------------------------------------------------------------------------
def test_plain_citations_are_not_field_defects() -> None:
    print()
    print("== Zotero: an originally plain citation is not a field-continuity defect ==")
    clauses = {
        "review": pp.ZOTERO_STAGE_REVIEW,
        "rewrite": pp.ZOTERO_STAGE_REWRITE,
        "judge": pp.ZOTERO_STAGE_JUDGE,
    }
    for name, clause in clauses.items():
        flat_clause = " ".join(clause.split())
        check(f"{name}: the rule is scoped to a citation that carried a base field",
              "base" in flat_clause.lower() and "live field" in flat_clause.lower(),
              flat_clause[:160])
        check(f"{name}: an originally plain citation is exempt",
              "originally plain" in flat_clause.lower()
              or "never had a live field" in flat_clause.lower(),
              flat_clause[:160])

    skill = (WS / "paper-skills" / "paper-review" / "SKILL.md").read_text(encoding="utf-8")
    sweeps = (WS / "paper-skills" / "paper-review" / "references" / "sweeps.md").read_text(
        encoding="utf-8")
    for name, text in (("review SKILL", skill), ("review sweeps", sweeps)):
        flat_text = " ".join(text.split()).lower()
        check(f"{name}: the field-continuity rule requires a base field",
              "carried a live field in the base" in flat_text)
        check(f"{name}: an originally plain citation is exempt",
              "originally plain" in flat_text
              and "never had a live field" in flat_text)

    # The rule must reach the generated review and judge prompts, not only the
    # constants: a LaTeX/plain-text corpus has no live fields anywhere.
    sb = scratch("zplain_")
    review = " ".join(pp.review_prompt(sb, "r1_guided_review", 1).split()).lower()
    judge = " ".join(pp.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, []).split()).lower()
    check("review prompt: an originally plain citation is exempt",
          "originally plain" in review and "never had a live field" in review,
          review[:160])
    check("judge prompt: an originally plain citation is exempt",
          "originally plain" in judge or "never had a live field" in judge,
          judge[:160])


# ---------------------------------------------------------------------------
# 10. The no-under-length rule is an UPPER-bound rule; the cover letter has a
#     configured floor and an under-length part is not padded.
# ---------------------------------------------------------------------------
def test_cover_letter_under_length_path() -> None:
    print()
    print("== M19: the cover-letter floor is the one under-length item ==")
    files = {
        "review SKILL": WS / "paper-skills" / "paper-review" / "SKILL.md",
        "review sweeps": WS / "paper-skills" / "paper-review" / "references" / "sweeps.md",
        "identify prompt": WS / "paper-skills" / "prompts" / "identify_issues.prompt.md",
    }
    texts = {name: " ".join(path.read_text(encoding="utf-8").split())
             for name, path in files.items()}
    check("review SKILL: under-length is scoped to abstract/main text",
          "under-length abstract or main text" in texts["review SKILL"],
          texts["review SKILL"][:160])
    check("review sweeps: under-length is scoped to abstract/main text",
          "UNDER-length abstract or main text" in texts["review sweeps"])
    check("review sweeps: the cover-letter preference is the one floor",
          "cover-letter preference is the one configured floor" in texts["review sweeps"])
    check("identify prompt: the mission sentence carries the scoping",
          "under-length abstract or main text" in texts["identify prompt"]
          and "cover-letter preference is the one configured floor"
          in texts["identify prompt"])
    check("identify prompt: the sweeps appendix carries the scoping",
          "UNDER-length abstract or main text" in texts["identify prompt"])

    revise = {
        "revise SKILL": WS / "paper-skills" / "paper-revise" / "SKILL.md",
        "edit rules": WS / "paper-skills" / "paper-revise" / "references" / "edit_rules.md",
        "adress prompt": WS / "paper-skills" / "prompts" / "adress_issues.prompt.md",
    }
    rtexts = {name: " ".join(path.read_text(encoding="utf-8").split())
              for name, path in revise.items()}
    check("revise SKILL: an under-length letter is not padded",
          "under-length part is not padded or invented" in rtexts["revise SKILL"])
    check("edit rules: an under-length letter is a manual item, not padding",
          "UNDER-length part is not padded or invented" in rtexts["edit rules"]
          and "record the shortfall in MANUAL_STEPS.md" in rtexts["edit rules"])
    check("adress prompt: the summary and the edit-rules appendix both carry it",
          "under-length part is not padded or invented" in rtexts["adress prompt"]
          and "UNDER-length part is not padded or invented" in rtexts["adress prompt"])


# ---------------------------------------------------------------------------
# 11. False-positive guards in the review references: DOI identity, M20 field
#     flattening, and M8's consolidated artifact.
# ---------------------------------------------------------------------------
def test_reference_precision_guards() -> None:
    print()
    print("== review rules: DOI identity, field flattening and the M8 artifact ==")
    sweeps = " ".join((WS / "paper-skills/paper-review/references/sweeps.md")
                      .read_text(encoding="utf-8").split())
    identify = " ".join((WS / "paper-skills/prompts/identify_issues.prompt.md")
                        .read_text(encoding="utf-8").split())
    skill = " ".join((WS / "paper-skills/paper-review/SKILL.md")
                      .read_text(encoding="utf-8").split())
    for name, text in (("sweeps", sweeps), ("identify prompt", identify)):
        check(f"{name}: a title/year variant is not automatically a different work",
              "names a different work" in text
              and "not merely a shorter/fuller title or an online-first vs issue year" in text,
              text[:160])
        check(f"{name}: flattening is a final-export action, not a candidate repair",
              "FINAL SUBMISSION EXPORT only" in text
              and "never a repair to a revised, rewritten or integrated candidate" in text,
              text[:160])
    for name, text in (("review SKILL", skill), ("identify prompt", identify)):
        check(f"{name}: M8's raw enumerations are not the whole artifact",
              "RAW enumerations" in text
              and "M8_terms.md" in text and "consolidated" in text,
              text[:160])
        check(f"{name}: the acceptance check names the consolidated M8 artifact",
              "the consolidated `guided_review/artifacts/M8_terms.md` is the artifact"
              in text, text[:160])


if __name__ == "__main__":
    test_judge_priority_uses_net_difference()
    test_reviser_does_not_reopen_dropped_findings()
    test_cold_start_verifier_budget_is_stated()
    test_repair_plan_accepts_pure_deletion()
    test_selfcheck_command_is_shell_quoted()
    test_medium_auxiliary_sidecar_does_not_overwrite_reviser()
    test_pdf_signature_and_cache()
    test_auc_out_of_range_is_inventoried()
    test_plain_citations_are_not_field_defects()
    test_cover_letter_under_length_path()
    test_reference_precision_guards()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): " + ", ".join(FAILS))
        sys.exit(1)
    print("ALL 2026-11-06 FIX CHECKS PASSED")

#!/usr/bin/env python3
"""Regression checks for the 2026-11-07 self-check and coverage-schema fixes.

Run:  python3 .paper_test/test_fix_bugs_20261107_selfcheck_and_coverage.py

What this suite pins:

  * every stage sandbox carries its own copy of the FROZEN driver and its
    ordered parts under `selfcheck/`, so the pre-flight survives a jailed
    harness that hides both the run root and the origin snapshot.  The eval
    harness's results-tree mask did exactly that: the prompt named only the
    root and the snapshot, both invisible, so the session finished with the
    postcheck's own detectors never run (the 2026-11-07 run's guided-review
    failures were exactly the rows the self-check reports);
  * the stage prompt runs that staged copy FIRST, then the ROOT's frozen copy,
    then the origin snapshot and the harness's read-only `/paper-pipeline`
    mount (the jail's new neutral mount);
  * the staged copy is COMPLETE: the driver loads its companion OOXML
    formatter from beside itself, so the formatter and its ordered parts are
    staged next to the driver too (a driver-only bundle made the package-stage
    pre-flight report the scanner as unavailable -- a failure the session could
    never repair);
  * the COLD-START REVIEW sandbox gets the staged bundle as well: its prompt
    carries the same SELF-CHECK block, and it was the one stage whose
    materializer never staged it;
  * the coverage row's verdict belongs in `disposition`; `detail` is free text.
    The canonical JSON example is what a session copies, so it shows a clean row
    (`clean -- basis: <artifact>`) rather than a bare `clean`;
  * a row that spells the verdict bare in `disposition` is still accepted when
    its `detail` carries an explicit `Basis:`/`Reason:` (on any line) -- and is
    refused when that tail is filler or absent;
  * every accepted spelling of an out-of-scope row (`out of scope`,
    `out-of-scope`, `out_of_scope`) is read as the SAME disposition: the
    in-scope guard catches all of them, and the split-review merge lets B's
    real examination replace A's placeholder in any spelling.
"""
from __future__ import annotations

import json
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


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def prompt_sandbox() -> Path:
    sb = scratch("pr-selfcheck-prompt-")
    (sb / "base").mkdir()
    (sb / "base" / "manuscript.md").write_text("# m\n\ntext.\n", encoding="utf-8")
    return sb


def test_staged_driver_runs_in_the_sandbox() -> None:
    sb = scratch("pr-selfcheck-stage-")
    pp._copy_session_tools(sb)
    check("the driver is staged under selfcheck/",
          (sb / pp.SELFCHECK_TOOL_DIR / pp.SELFCHECK_DRIVER).is_file())
    check("the driver's ordered parts are staged beside it",
          (sb / pp.SELFCHECK_TOOL_DIR / "paper_pipeline_parts").is_dir())
    proc = subprocess.run(
        [sys.executable, pp.SELFCHECK_DRIVER_REL, "selfcheck", "--sandbox", ".",
         "--stage", "guided_review", "--run-id", "r1_guided_review", "--round", "1"],
        cwd=sb, capture_output=True, text=True, timeout=180,
    )
    check("the staged driver's selfcheck actually runs",
          "SELF-CHECK" in proc.stdout,
          (proc.stderr or proc.stdout)[-300:])
    check("the staged driver is not a missing-parts stub",
          "missing paper_pipeline_parts" not in (proc.stdout + proc.stderr),
          (proc.stdout + proc.stderr)[-300:])


def test_review_prompt_names_the_staged_copy_first() -> None:
    sb = prompt_sandbox()
    prof = pp.load_venue_profile("generic")
    text = pp.review_prompt(sb, "r1_guided_review", 1, venue=prof, scope="full",
                            execution_profile="high")
    staged = f"python {pp.SELFCHECK_DRIVER_REL} selfcheck"
    root = f"python {pp.pipeline_self_path()} selfcheck"
    check("the staged selfcheck is a command line", staged in text)
    check("the staged copy is named before the ROOT's absolute path",
          staged in text and root in text
          and text.index(staged) < text.index(root))
    check("the harness's neutral mount is a named fallback",
          pp.HARNESS_DRIVER_REL in text)
    check("the bridge text still explains a jailed session",
          "jailed harness may mount the run root elsewhere" in text)


def test_judge_prompt_uses_the_harness_mount() -> None:
    sb = prompt_sandbox()
    prof = pp.load_venue_profile("generic")
    text = pp.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, [], venue=prof,
                           execution_profile="high")
    check("the judge pre-flight runs the ROOT's frozen copy",
          f"python {pp.pipeline_self_path()} selfcheck --sandbox . --stage judge" in text)
    check("the judge pre-flight does NOT stage the driver in its blinded sandbox",
          f"python {pp.SELFCHECK_DRIVER_REL} selfcheck" not in text)
    check("the judge pre-flight names the harness mount",
          pp.HARNESS_DRIVER_REL in text)


def test_judge_tool_staging_omits_the_driver() -> None:
    sb = scratch("pr-judge-tools-")
    pp._copy_session_tools(sb, include_driver=False)
    check("a blinded judge sandbox gets no selfcheck/ bundle",
          not (sb / pp.SELFCHECK_TOOL_DIR).exists())
    check("a blinded judge sandbox still gets the public formatter",
          (sb / pp.DOCX_FORMAT_MODULE).is_file())


def test_staged_driver_carries_the_formatter() -> None:
    """The staged driver loads `paper_docx_format.py` from beside ITSELF.

    Staging only the driver + parts made `python selfcheck/paper_pipeline.py
    selfcheck --stage revise` report "the OOXML formatting scanner is
    UNAVAILABLE next to the driver": the sandbox-root copy is not where
    `__file__` points, so the session could never clear the false failure.
    """
    sb = scratch("pr-selfcheck-fmt-")
    pp._copy_session_tools(sb)
    tool = sb / pp.SELFCHECK_TOOL_DIR
    check("the formatter is staged beside the driver",
          (tool / pp.DOCX_FORMAT_MODULE).is_file())
    check("the formatter's ordered parts are staged beside it",
          (tool / pp.DOCX_FORMAT_PARTS_DIR).is_dir())
    (sb / "base").mkdir()
    (sb / "base" / "manuscript.md").write_text("# m\n\ntext.\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, pp.SELFCHECK_DRIVER_REL, "selfcheck", "--sandbox", ".",
         "--stage", "revise", "--run-id", "r1_a2_revise", "--round", "1"],
        cwd=sb, capture_output=True, text=True, timeout=300,
    )
    out = proc.stdout + proc.stderr
    check("the package-stage pre-flight does not report the scanner unavailable",
          "UNAVAILABLE next to the driver" not in out, out[-400:])


def test_cold_start_sandbox_stages_the_driver() -> None:
    """The cold-start review prompt names the staged copy; its sandbox must hold it."""
    root = scratch("pr-coldstart-root-")
    (root / "runs").mkdir()
    (root / "reports").mkdir()
    (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
    a1sb = root / "runs" / pp.rid_a1(1)
    (a1sb / "base").mkdir(parents=True)
    (a1sb / "base" / "manuscript.md").write_text("# m\n\nbody.\n", encoding="utf-8")
    prist = root / "non_revised"
    prist.mkdir()
    (prist / "manuscript.md").write_text("# m\n\nbody.\n", encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.cfg = {}
    ctx.state["runs"][pp.rid_a1(1)] = {
        "id": pp.rid_a1(1), "kind": "a1", "round": 1, "sandbox": "runs/r1_a1",
        "status": "done", "source_id": pp.ORIGINAL_ID}
    real_seed = pp.seed_cold_start_surfaces
    pp.seed_cold_start_surfaces = lambda ctx, sb, r: {}
    try:
        rec = pp.materialize_cold_start_review(ctx, 1)
    finally:
        pp.seed_cold_start_surfaces = real_seed
    sb = ctx.sandbox_of(rec)
    prompt = (sb / "PROMPT.md").read_text(encoding="utf-8")
    check("the cold-start prompt names the staged driver",
          pp.SELFCHECK_DRIVER_REL in prompt)
    check("the cold-start sandbox actually carries the staged driver",
          (sb / pp.SELFCHECK_TOOL_DIR / pp.SELFCHECK_DRIVER).is_file())
    check("the cold-start sandbox carries the staged formatter for its pre-flight",
          (sb / pp.SELFCHECK_TOOL_DIR / pp.DOCX_FORMAT_MODULE).is_file())


def test_review_prompt_shows_a_clean_disposition_verdict() -> None:
    sb = prompt_sandbox()
    prof = pp.load_venue_profile("generic")
    text = pp.review_prompt(sb, "r1_guided_review", 1, venue=prof, scope="full",
                            execution_profile="high")
    check("the canonical example carries a clean row with its basis",
          '"disposition": "clean -- basis: guided_review/artifacts/M2_references.md"'
          in text)
    check("the canonical example says detail is free text",
          "`detail` is free text" in text)
    check("the no-silent-skips rule says the verdict goes in disposition",
          "THE VERDICT GOES IN" in text and "`detail` is free text" in text)
    # The gate DOES read `detail` for a bare verdict's Basis:/Reason:, and the
    # prompt must not claim otherwise.
    check("the prompt states the one case in which detail is read",
          "is read only to accept a BARE" in text, "")


def test_coverage_row_accepts_only_a_named_detail_basis() -> None:
    check("canonical clean -- basis row is accepted",
          pp._coverage_row_disposition_ok(
              {"disposition": "clean -- basis: artifacts/M8_terms.md"}))
    check("a bare clean with an explicit Basis: in detail is accepted",
          pp._coverage_row_disposition_ok(
              {"disposition": "clean", "detail": "Basis: artifacts/M8_terms.md"}))
    check("a multi-line detail whose Basis: is on the FIRST line is accepted",
          pp._coverage_row_disposition_ok(
              {"disposition": "clean",
               "detail": "Basis: artifacts/M8_terms.md\n8 entries, 0 orphans"}))
    check("a multi-line detail whose Basis: is on the LAST line is accepted",
          pp._coverage_row_disposition_ok(
              {"disposition": "clean",
               "detail": "8 entries, 0 orphans\nBasis: artifacts/M8_terms.md"}))
    check("a bare clean with a bare detail is refused",
          not pp._coverage_row_disposition_ok(
              {"disposition": "clean", "detail": "no findings"}))
    check("a bare clean with no detail is refused",
          not pp._coverage_row_disposition_ok({"disposition": "clean"}))
    check("a one-character basis is still filler",
          not pp._coverage_row_disposition_ok(
              {"disposition": "clean", "detail": "Basis: x"}))
    check("an explicit Reason: in detail is accepted for unable",
          pp._coverage_row_disposition_ok(
              {"disposition": "unable", "detail": "Reason: no rendered artwork"}))
    check("the canonical unable -- reason row is accepted",
          pp._coverage_row_disposition_ok(
              {"disposition": "unable -- no rendered artwork"}))


def _full_review_findings(m1_row: dict) -> dict:
    """A findings.json coverage table that disposes every required check."""
    checks = [f"M{i}" for i in range(1, 37)] + [f"J{i}" for i in range(1, 6)]
    rows = [{"check": cid, "disposition": "clean -- basis: artifacts/M1_acronyms.md"}
            for cid in checks]
    rows[0] = dict(m1_row, check="M1")
    return {"submission_dir": "./base", "findings": [], "coverage": rows}


def test_out_of_scope_spellings_are_one_disposition() -> None:
    for value in ("out of scope -- formatting-only", "out-of-scope",
                  "out_of_scope", "OUT OF SCOPE"):
        check(f"the out-of-scope spelling {value!r} is recognized",
              pp._coverage_is_out_of_scope(value))
    check("a clean verdict is not out of scope",
          not pp._coverage_is_out_of_scope("clean"))
    check("a hyphenated out-of-scope row WITH a reason is a real disposition",
          pp._coverage_row_disposition_ok(
              {"disposition": "out-of-scope -- formatting-only pass"}))
    check("a hyphenated out-of-scope row with NO reason is still filler",
          not pp._coverage_row_disposition_ok({"disposition": "out-of-scope"}))

    # The in-scope guard: a FULL review may not dispose a required check as out
    # of scope in ANY spelling. The hyphenated form used to slip past it.
    sb = prompt_sandbox()
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    (sb / "guided_review" / "artifacts" / "M1_acronyms.md").write_text(
        "| acronym | disposition |\n|---|---|\n| DNA | OK |\n", encoding="utf-8")
    errs, warns = [], []
    pp.check_review_contract(
        None, sb, _full_review_findings(
            {"disposition": "out-of-scope", "detail": "Reason: session B owns it"}),
        errs, warns, scope="full", split="off")
    hit = [e for e in errs if "disposes in-scope check" in e and "'M1'" in e]
    check("the hyphenated out-of-scope row is caught by the in-scope guard",
          bool(hit), "\n".join(errs)[-500:])

    # A genuinely out-of-scope check of a formatting-writing round may be
    # disposed as out of scope in any spelling: M2 is not one of that scope's
    # checks. (M1 is IN that scope, so it must be caught above.)
    errs2, warns2 = [], []
    fj2 = _full_review_findings(
        {"disposition": "clean -- basis: artifacts/M1_acronyms.md"})
    for _row in fj2["coverage"]:
        if _row["check"] == "M2":
            _row["disposition"] = "out-of-scope"
            _row["detail"] = "Reason: formatting-only pass"
    pp.check_review_contract(
        None, sb, fj2, errs2, warns2, scope="formatting-writing", split="off")
    check("a check the round scoped out may be disposed out of scope in any spelling",
          not [e for e in errs2 if "'M2'" in e
               and ("scoped OUT" in e or "disposes in-scope" in e)],
          "\n".join(errs2)[-500:])


def test_check_id_spelling_is_normalized() -> None:
    """`m1` / `M01` must not read as a missing `M1` (the judge gate already does this)."""
    check("a lowercase check id normalizes", pp.normalise_check_id("m1") == "M1")
    check("a padded check id normalizes", pp.normalise_check_id("M01") == "M1")
    check("a padded J id normalizes", pp.normalise_check_id("j05") == "J5")
    check("an adopted proposal id is left alone", pp.normalise_check_id("M37") == "M37")
    check("a non-check id is left alone", pp.normalise_check_id("scope") == "scope")
    sb = prompt_sandbox()
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    (sb / "guided_review" / "artifacts" / "M1_acronyms.md").write_text(
        "| acronym | disposition |\n|---|---|\n| DNA | OK |\n", encoding="utf-8")
    fj = _full_review_findings(
        {"disposition": "clean -- basis: artifacts/M1_acronyms.md"})
    fj["coverage"][0]["check"] = "m01"
    errs, warns = [], []
    pp.check_review_contract(None, sb, fj, errs, warns, scope="full", split="off")
    check("a lowercase/padded M1 row satisfies the M1 requirement",
          not [e for e in errs if "missing check id" in e],
          "\n".join(errs)[-400:])


def test_split_review_merge_replaces_a_hyphenated_placeholder() -> None:
    """A's `out-of-scope` placeholder must not hide B's real examination."""
    root = scratch("pr-split-merge-")
    (root / "runs").mkdir()
    (root / "reports").mkdir()
    (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
    a = root / "runs" / pp.rid_guided_review(1)
    (a / "guided_review").mkdir(parents=True)
    (a / "guided_review" / "findings.json").write_text(json.dumps(
        _full_review_findings(
            {"disposition": "out-of-scope", "detail": "Reason: session B owns M1"})),
        encoding="utf-8")
    b = root / "runs" / pp.rid_guided_review_b(1)
    (b / "guided_review").mkdir(parents=True)
    b_fj = _full_review_findings(
        {"disposition": "clean -- basis: artifacts/M1_acronyms.md"})
    (b / "guided_review" / "findings.json").write_text(json.dumps(b_fj),
                                                      encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.cfg = {}
    rec_b = {"id": pp.rid_guided_review_b(1), "round": 1,
             "sandbox": f"runs/{pp.rid_guided_review_b(1)}"}
    pp.merge_review_parts(ctx, rec_b)
    merged = json.loads((b / "guided_review" / "findings.json").read_text(encoding="utf-8"))
    m1 = next((r for r in merged.get("coverage") or []
               if str(r.get("check") or "") == "M1"), {})
    check("the merge keeps B's real M1 examination, not A's hyphenated placeholder",
          str(m1.get("disposition") or "").startswith("clean -- basis:"), repr(m1))


def main() -> int:
    test_staged_driver_runs_in_the_sandbox()
    test_review_prompt_names_the_staged_copy_first()
    test_judge_prompt_uses_the_harness_mount()
    test_judge_tool_staging_omits_the_driver()
    test_staged_driver_carries_the_formatter()
    test_cold_start_sandbox_stages_the_driver()
    test_review_prompt_shows_a_clean_disposition_verdict()
    test_coverage_row_accepts_only_a_named_detail_basis()
    test_out_of_scope_spellings_are_one_disposition()
    test_check_id_spelling_is_normalized()
    test_split_review_merge_replaces_a_hyphenated_placeholder()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return 1
    print(f"\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Removal accounting for review findings (insertions/deletions are ON).

A deleted sentence is a permitted revision choice, so the gate must never ask
for it back. What it must catch is the ACCOUNTING: a ledger that reports a
removed finding's sentence as `fixed` claims a repair the package does not
contain. The deletion audit's fact gate tracks numbers/identifiers, so a
removed wrong-word sentence (a premise, a verb, a pointer, a caption quantity)
left no value to lose and passed as `OK -- no fact is lost`.

Run with: python3 .paper_test/test_finding_removal_accounting.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def tmpdir(tag):
    return Path(tempfile.mkdtemp(prefix=f"fra_{tag}_"))


def package(tag, base_text, revised_text, findings, statuses=None,
            exempt=(), ledger=None):
    root = tmpdir(tag)
    (root / "base").mkdir()
    (root / "pkg").mkdir()
    (root / "base" / "brief.md").write_text(base_text, encoding="utf-8")
    (root / "pkg" / "brief.md").write_text(revised_text, encoding="utf-8")
    if ledger is not None:
        (root / "pkg" / "revision_report.json").write_text(
            json.dumps(ledger), encoding="utf-8")
    removals = pp.finding_removal_problems(
        root / "base", root / "pkg", findings,
        final_status=statuses or {}, exempt_removed=exempt)
    return removals


def test_fixed_removal_is_error():
    base = ("# Title\n\nThe dawn census was timed to the Sun's rise in the "
            "north. The sample table was checked twice.\n")
    revised = "# Title\n\nThe sample table was checked twice.\n"
    findings = [{"id": "F-1",
                 "evidence": "The dawn census was timed to the Sun's rise in the south."}]
    rem = package("fixed", base, revised, findings, {"F-1": "fixed"})
    errs, warns = pp.finding_removal_messages(rem)
    check("fixed removal -> one error", len(errs) == 1 and not warns,
          f"errs={len(errs)} warns={len(warns)}")
    check("error names the finding and the allowed deletion",
          errs and "F-1" in errs[0] and "manual-required" in errs[0],
          errs[0][:120] if errs else "")


def test_manual_removal_is_warning():
    base = "# Title\n\nThe dawn census was timed to the Sun's rise in the south.\n"
    revised = "# Title\n\nSomething else entirely was done that morning.\n"
    findings = [{"id": "F-1",
                 "evidence": "The dawn census was timed to the Sun's rise in the south."}]
    rem = package("manual", base, revised, findings, {"F-1": "manual-required"})
    errs, warns = pp.finding_removal_messages(rem)
    check("manual-required removal -> warning only", not errs and len(warns) == 1,
          f"errs={len(errs)} warns={len(warns)}")
    check("warning tells the author about the removed claim",
          warns and "manual list" in warns[0], warns[0][:120] if warns else "")


def test_in_place_correction_passes():
    base = "# Title\n\nThe field crew recorded the mass of every sample.\n"
    revised = "# Title\n\nThe field crew measured the mass of every sample.\n"
    findings = [{"id": "F-1",
                 "evidence": "The field crew recorded the mass of every sample."}]
    rem = package("corrected", base, revised, findings, {"F-1": "fixed"})
    check("in-place correction is not a removal", not rem,
          [r["id"] for r in rem])


def test_duplicate_surviving_copy_passes():
    sentence = "Soil moisture was measured at five points per plot."
    base = f"# Title\n\n{sentence} {sentence}\n"
    revised = f"# Title\n\n{sentence}\n"
    findings = [{"id": "F-1", "evidence": sentence}]
    rem = package("dupe", base, revised, findings, {"F-1": "fixed"})
    check("duplicate with a surviving copy is not a removal", not rem,
          [r["id"] for r in rem])


def test_artifact_removal_exempt():
    base = ("# Title\n\nImprove the academic tone of the following text. "
            "Output only the revised paragraph.\n")
    revised = "# Title\n\nThe analysis was run on the entered table.\n"
    findings = [{"id": "F-1",
                 "evidence": "Improve the academic tone of the following text. "
                             "Output only the revised paragraph."}]
    rem = package("artifact", base, revised, findings, {"F-1": "fixed"})
    check("leaked-prompt removal is exempt", not rem, [r["id"] for r in rem])


def test_pipeline_exempt_removal():
    sentence = "The counts are archived in the source data table."
    base = f"# Title\n\n{sentence}\n"
    revised = "# Title\n\nThe counts are stated in the text.\n"
    findings = [{"id": "F-1", "evidence": sentence}]
    rem = package("pipeline", base, revised, findings, {"F-1": "fixed"},
                  exempt=[("brief.md", sentence)])
    check("pipeline's own removal is exempt", not rem, [r["id"] for r in rem])


def test_non_verbatim_quote_skipped():
    base = "# Title\n\nThe sample table was checked twice before the analysis.\n"
    revised = "# Title\n\nThe sample table was checked three times before the analysis.\n"
    findings = [{"id": "F-1",
                 "evidence": "Results: the table looks fine versus 3.1: it was checked."}]
    rem = package("summary", base, revised, findings, {"F-1": "fixed"})
    check("non-verbatim/composite evidence is skipped", not rem,
          [r["id"] for r in rem])


def test_partial_quote_of_longer_sentence_skipped():
    base = ("# Title\n\nWe fitted a GLM (gradient log magnitude) with a "
            "negative-binomial error for counts and a Gaussian error for "
            "height, with block as a fixed factor.\n")
    revised = ("# Title\n\nWe fitted a generalised linear model (GLM) with a "
               "negative-binomial error for counts and a Gaussian error for "
               "height, with block as a fixed factor.\n")
    findings = [{"id": "F-1",
                 "evidence": "We fitted a GLM (gradient log magnitude) with a "
                             "negative-binomial error"}]
    rem = package("partial", base, revised, findings, {"F-1": "fixed"})
    check("partial quote of a longer sentence is skipped", not rem,
          [r["id"] for r in rem])


def test_ledger_final_status_map():
    root = tmpdir("ledger")
    (root / "revision_report.json").write_text(json.dumps({
        "ledger": [
            {"id": "F-1", "verdict": "confirmed", "final_status": "manual-required"},
            {"id": "F-2", "verdict": "confirmed", "final_status": "fixed"},
            {"id": "F-3", "verdict": "false-positive", "final_status": "discarded"},
        ]}), encoding="utf-8")
    got = pp.revision_ledger_final_status(root)
    check("ledger final statuses are read per finding id",
          got.get("F-1") == "manual-required" and got.get("F-2") == "fixed"
          and got.get("F-3") == "discarded", got)


def test_missing_base_is_silent():
    root = tmpdir("nobase")
    (root / "pkg").mkdir()
    (root / "pkg" / "brief.md").write_text("# Title\n\nText.\n", encoding="utf-8")
    got = pp.finding_removal_problems(root / "base", root / "pkg",
                                      [{"id": "F-1", "evidence": "x" * 40}])
    check("no base -> no problems", got == [], got)


def _ctx():
    import types
    return types.SimpleNamespace(cfg={})


def _policy_problems(tag, base_text, revised_text, **kw):
    root = tmpdir(tag)
    (root / "base").mkdir()
    (root / "pkg").mkdir()
    (root / "base" / "brief.md").write_text(base_text, encoding="utf-8")
    (root / "pkg" / "brief.md").write_text(revised_text, encoding="utf-8")
    return pp.content_edit_problems(
        _ctx(), root / "base", root / "pkg", "revise",
        insertions_allowed=True, deletions_allowed=True, prefer_rewrite=False,
        soft_deletions=True, **kw)


def test_middle_policy_blocks_claim_deletion():
    base = ("# Title\n\nThe dawn census was timed to the Sun's rise in the "
            "north.\n")
    revised = "# Title\n\nThe counts were entered and checked.\n"
    probs = _policy_problems("mid_claim", base, revised)
    check("middle policy fails a claim-bearing deletion",
          len(probs) == 1 and "--enable-soft-deletions" in probs[0],
          probs[0][:160] if probs else probs)


def test_middle_policy_allows_duplicate_removal():
    sentence = "Soil moisture was measured at five points per plot."
    base = f"# Title\n\n{sentence} {sentence}\n"
    revised = f"# Title\n\n{sentence}\n"
    probs = _policy_problems("mid_dupe", base, revised)
    check("middle policy allows a duplicate removal", not probs, probs)


def test_middle_policy_allows_prompt_removal():
    base = ("# Title\n\nImprove the academic tone of the following text. "
            "Output only the revised paragraph.\n")
    revised = "# Title\n\nThe analysis was run on the entered table.\n"
    probs = _policy_problems("mid_prompt", base, revised)
    check("middle policy allows a leaked-prompt removal", not probs, probs)


def test_middle_policy_allows_in_place_correction():
    base = "# Title\n\nThe field crew recorded the mass of every sample.\n"
    revised = "# Title\n\nThe field crew measured the mass of every sample.\n"
    probs = _policy_problems("mid_fix", base, revised)
    check("middle policy allows an in-place correction", not probs, probs)


def test_middle_policy_allows_a_merge_covered_unit():
    base = ("# Title\n\nThe sample table was checked twice before the analysis "
            "was run. The sample table was checked twice before the analysis.\n")
    revised = ("# Title\n\nThe sample table was checked twice before the "
               "analysis was run.\n")
    probs = _policy_problems("mid_merge", base, revised)
    check("middle policy accepts a unit fully covered by a delivered sentence",
          not probs, probs)


def test_default_policy_is_unchanged():
    block = pp.content_edit_policy_block(True, True, False, False)
    check("default policy block stays empty", block == "", repr(block))
    rec = pp.content_edit_policy_record(_ctx(), True, True, False, False)
    check("default policy needs no run record", rec is None, rec)


def test_deletion_scope_precedence():
    ctx = _ctx()
    ctx.cfg["soft_deletions"] = "on"
    check("scope is removable when the middle mode is on",
          pp.deletion_scope(ctx) == "removable", pp.deletion_scope(ctx))
    ctx.cfg["deletions"] = "off"
    check("strict no-deletions wins over the middle mode",
          pp.deletion_scope(ctx) == "none", pp.deletion_scope(ctx))
    ctx.cfg = {}
    check("default scope is all", pp.deletion_scope(ctx) == "all",
          pp.deletion_scope(ctx))


def test_prompt_block_roundtrip():
    block = pp.content_edit_policy_block(True, True, False, True)
    check("middle policy block names its heading",
          "SOFT DELETIONS ARE LIMITED TO REMOVABLE UNITS." in block, block[:80])
    root = tmpdir("prompt")
    prompt = root / "PROMPT.md"
    prompt.write_text(block, encoding="utf-8")
    check("prompt matcher accepts the middle policy",
          pp.prompt_content_edit_policy_matches(prompt, True, True, False, True))
    check("prompt matcher rejects a default prompt for the middle policy",
          not pp.prompt_content_edit_policy_matches(prompt, True, True, False, False))
    check("prompt parser reads the middle policy",
          pp.soft_deletions_from_prompt(prompt) is True)
    rec = pp.content_edit_policy_record(_ctx(), True, True, False, True)
    check("middle policy is recorded on the run",
          isinstance(rec, dict) and rec.get("soft_deletions") is True
          and rec.get("insertions") is True and rec.get("deletions") is True, rec)


if __name__ == "__main__":
    test_fixed_removal_is_error()
    test_manual_removal_is_warning()
    test_in_place_correction_passes()
    test_duplicate_surviving_copy_passes()
    test_artifact_removal_exempt()
    test_pipeline_exempt_removal()
    test_non_verbatim_quote_skipped()
    test_partial_quote_of_longer_sentence_skipped()
    test_ledger_final_status_map()
    test_missing_base_is_silent()
    test_middle_policy_blocks_claim_deletion()
    test_middle_policy_allows_duplicate_removal()
    test_middle_policy_allows_prompt_removal()
    test_middle_policy_allows_in_place_correction()
    test_middle_policy_allows_a_merge_covered_unit()
    test_default_policy_is_unchanged()
    test_deletion_scope_precedence()
    test_prompt_block_roundtrip()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {FAILS}")
        sys.exit(1)
    print("all checks passed")

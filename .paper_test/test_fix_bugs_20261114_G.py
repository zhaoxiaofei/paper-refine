#!/usr/bin/env python3
"""Regression checks for the 2026-11-14 fix-bugs wave, group G (F63-F73).

Every check names the verified candidate it pins and re-runs the minimal
behaviour that was shown broken on the pre-fix tree. Self-contained: it loads
the assembled `paper_pipeline.py`, uses tempfile fixtures only, and exits 1 if
any check fails.

Run:  python3 .paper_test/test_fix_bugs_20261114_G.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FAILS = []
KEEP = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    d = Path(tempfile.mkdtemp(prefix="gfix_" + prefix + "_"))
    KEEP.append(d)
    return d


def load():
    spec = importlib.util.spec_from_file_location("gfix_pp", str(WS / "paper_pipeline.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gfix_pp"] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load()

HDR = ("| TODO item ID | importance | author action | description |\n"
       "|---|---|---|---|\n")


# --- F63: the M19 band between the venue base and the relaxed cap is rendered -
def test_f63_band():
    nbt = pp.load_venue_profile("nature-biotechnology")
    blocks = pp.m19_blocks(nbt)
    for key in ("review", "revise", "integrate", "rewrite", "judge"):
        flat = " ".join(blocks[key].split())
        check(f"F63 the {key} M19 mandate reports the band",
              "THE BAND IS REPORTED, NOT ENFORCED" in flat
              and "abstract base 150 +10% = 165 words" in flat
              and "main text base 3000 +25% = 3750 words" in flat, key)
    generic = pp.load_venue_profile("generic")
    flat_generic = " ".join(" ".join(v.split()) for v in pp.m19_blocks(generic).values())
    check("F63 a profile with no relaxed cap renders no band clause",
          "THE BAND IS REPORTED" not in flat_generic)
    flat_review = " ".join(blocks["review"].split())
    check("F63 the band row is never a finding, compression or score",
          "it is within the limit applied here, so it is never a finding, "
          "never compressed and never scored" in flat_review.lower())
    check("F63 the band row records the base, not a claimed compliance",
          "the row says the section is within the relaxed cap, not that the venue's "
          "base was met" in flat_review)


# --- F64: the profile cover-letter TOTAL cap reaches the class rule ---------
def test_f64_cover_total():
    prof = pp.VenueProfile({
        "id": "c650probe", "label": "C650 Probe", "short": "C",
        "article_types": [{"id": "a", "label": "Article", "length_limits": {
            "cover_letter": {"min": 300, "max": 500, "total_max": 650,
                             "source": "probe"}}}],
        "default_article_type": "a"})
    rule = pp.defect_class_rule(prof)
    check("F64 a configured cover-letter total cap is rendered",
          "within 650 words" in " ".join(rule.split()))
    generic_rule = " ".join(pp.defect_class_rule().split())
    check("F64 a profile with no total cap renders no number",
          "within 650 words" not in generic_rule
          and "no total-word cap (this profile configures none)" in generic_rule)
    check("F64 the template carries the substitution token",
          "@@COVER_LETTER_TOTAL_CLAUSE@@" in pp.DEFECT_CLASS_RULE_TEMPLATE)


# --- F65: hand-off T-ids are allocated across the ONE id space --------------
def test_f65_tid_collision():
    pkg = scratch("f65")
    (pkg / "MANUAL_STEPS.md").write_text(
        "# MANUAL STEPS\n\n" + HDR
        + f"| T-001 | minor | {pp.MANUAL_ACTIONS[2]} | legacy row |\n\n"
        "- Supply the accession [AUTHOR TO COMPLETE: accession]\n", encoding="utf-8")
    ctx = pp.Ctx(scratch("f65root"), False)
    rec = pp.ensure_handoff_readme(ctx, pkg, warns=[])
    readme = (pkg / pp.AUTHOR_TO_COMPLETE_README).read_text(encoding="utf-8")
    check("F65 the moved item gets an id that does not collide with MANUAL_STEPS.md",
          rec.get("items") == 1 and "| T-002 |" in readme and "| T-001 |" not in readme,
          readme)
    errs, _warns = pp.manual_todo_gate(pkg)
    check("F65 the package passes its own duplicate-id gate",
          not any("duplicate TODO item ID" in e for e in errs), str(errs))
    check("F65 a second pass is idempotent",
          pp.ensure_handoff_readme(ctx, pkg, warns=[]) == {})


# --- F66: an applied correction asks the author to CONFIRM/REJECT -----------
def test_f66_applied_action():
    root = scratch("f66")
    pp.write_published_handoff_readme(root, {"items": [
        {"id": "F-1", "status": "fixed-with-caveat", "check": "M1",
         "severity": "major", "location": "a.md:1", "evidence": "x"},
    ]})
    row = [ln for ln in (root / pp.AUTHOR_TO_COMPLETE_README).read_text(
        encoding="utf-8").splitlines() if "| T-001 |" in ln]
    check("F66 fixed-with-caveat selects author action 1",
          row and pp.MANUAL_ACTIONS[0] in row[0], row)
    root2 = scratch("f66b")
    pp.write_published_handoff_readme(root2, {"items": [
        {"id": "F-2", "status": "manual-required", "check": "M1",
         "severity": "major", "location": "a.md:1", "evidence": "y"},
    ]})
    row2 = [ln for ln in (root2 / pp.AUTHOR_TO_COMPLETE_README).read_text(
        encoding="utf-8").splitlines() if "| T-001 |" in ln]
    check("F66 manual-required keeps the no-applied-correction action",
          row2 and pp.MANUAL_ACTIONS[2] in row2[0], row2)


# --- F67: one classified table, never two side by side ----------------------
def test_f67_one_table():
    root = scratch("f67")
    (root / pp.AUTHOR_TO_COMPLETE_README).write_text(
        "# Author to complete\n\n" + HDR
        + f"| T-001 | minor | {pp.MANUAL_ACTIONS[2]} | stage row |\n",
        encoding="utf-8")
    pp.write_published_handoff_readme(root, {"items": [
        {"id": "F-1", "status": "manual-required", "check": "M1",
         "severity": "major", "location": "a.md:1", "evidence": "y"},
    ]})
    text = (root / pp.AUTHOR_TO_COMPLETE_README).read_text(encoding="utf-8")
    check("F67 the checklist carries exactly ONE classified table",
          text.count("| TODO item ID |") == 1, text)
    check("F67 both the author row and the generated row survive",
          "stage row" in text and "| T-002 |" in text, text)


# --- F68: a profile counts-only caption block is not an operator override ---
def test_f68_counts_only_profile():
    counts_only = pp.VenueProfile({
        "id": "cvprobe", "label": "CV Probe", "short": "CVP",
        "article_types": [{"id": "art", "label": "Article", "captions": {
            "published_limit": 250, "default_cap": 0, "source": "venue says 250"}}],
        "default_article_type": "art"})
    report = pp.caption_report_text(counts_only)
    check("F68 the profile's counts-only choice is named as the profile's",
          "COUNTS ONLY" in report and "profile selects counts only" in report)
    check("F68 the profile's counts-only choice is not blamed on the operator",
          "OPERATOR DISABLED" not in report)
    override = pp.VenueProfile({
        "id": "cvprobe2", "label": "CV Probe 2", "short": "CVP2",
        "article_types": [{"id": "art", "label": "Article", "captions": {
            "published_limit": 250, "source": "venue says 250"}}],
        "default_article_type": "art"})
    check("F68 an operator-disabled cap on a publishing venue still says so",
          "OPERATOR DISABLED" in pp.caption_report_text(override))


# --- F69: `_` is a list separator for integrator masks too ------------------
def test_f69_mask_underscore():
    check("F69 '1_2' parses as two masks",
          pp.parse_round_masks(["1_2"], 2, "--integrators") == [1, 2],
          str(pp.parse_round_masks(["1_2"], 2, "--integrators")))
    check("F69 ordinary mask lists are unchanged",
          pp.parse_round_masks(["0x5,3"], 2, "--integrators") == [5, 3])


# --- F70: a partial plan is honoured key by key, a broken read is surfaced --
class FakeCtx:
    def __init__(self, cfg, plan=None, raises=False):
        self.cfg = cfg
        self.plan = plan
        self.raises = raises

    def round_get(self, r):
        if self.raises:
            raise RuntimeError("corrupt round record")
        return {"plan": self.plan} if self.plan is not None else {}


def test_f70_partial_plan():
    cfg = {"rewrites": [0], "revises": [1], "rounds": 1}
    ctx = FakeCtx(cfg, {"rewrites": 2})
    check("F70 a partially recorded plan keeps its recorded half",
          pp.round_counts(ctx, 1) == (2, 1), str(pp.round_counts(ctx, 1)))
    ctx2 = FakeCtx({"rewrites": [0], "revises": [1], "rounds": 1}, {"revises": 3})
    check("F70 the other recorded half is honoured too",
          pp.round_counts(ctx2, 1) == (0, 3), str(pp.round_counts(ctx2, 1)))
    ctx3 = FakeCtx(cfg, {"judges": 4})
    check("F70 a recorded judges count survives a missing rewrites/revises plan",
          pp.round_judges(ctx3, 1) == 4)
    ctx4 = FakeCtx(cfg, raises=True)
    try:
        pp.round_counts(ctx4, 1)
        raised = False
    except SystemExit:
        raised = True
    check("F70 an unreadable round record refuses to re-derive from config", raised)


# --- F71: judgeable ids honour the recorded integrated list -----------------
def test_f71_judgeable_integrated():
    ctx = FakeCtx({"rewrites": [0], "revises": [1], "rounds": 1,
                   "integrators": [0], "judges": [1]},
                  {"rewrites": 0, "revises": 1, "integrators": 0,
                   "integrated": ["i2"], "judges_enabled": "i2_j1"})
    ctx.state = {"pinned": []}
    check("F71 the recorded integrated id is judgeable",
          "i2" in pp.judgeable_ids(ctx, 1), str(pp.judgeable_ids(ctx, 1)))
    check("F71 the recorded judge selector is not discarded",
          pp.judge_selection(ctx, 1) == {("i2", 1)},
          str(pp.judge_selection(ctx, 1)))
    fallback = FakeCtx({"rewrites": [0], "revises": [1], "rounds": 1,
                        "integrators": [2], "judges": [1]}, {"rewrites": 0, "revises": 1})
    fallback.state = {"pinned": []}
    check("F71 a round with no recorded list still uses the mask",
          pp.round_integrated_run_ids(fallback, 1) == ["i2"],
          str(pp.round_integrated_run_ids(fallback, 1)))


# --- F72: llm-only mode reads no human-stream previous response ------------
def test_f72_previous_responses():
    root = scratch("f72")
    pristine = root / "non_revised"
    (pristine / "human_review_feedback").mkdir(parents=True)
    (pristine / "llm_review_feedback").mkdir(parents=True)
    (pristine / "human_review_feedback" / "response_to_reviewers.txt").write_text(
        "old reply", encoding="utf-8")
    (pristine / "llm_review_feedback" / "review.md").write_text(
        "llm review", encoding="utf-8")
    llm = FakeCtx({"revision_mode": "llm"})
    llm.pristine = pristine
    check("F72 llm mode stages no human previous response",
          pp.journal_previous_responses(llm) == [])
    human = FakeCtx({"revision_mode": "transfer"})
    human.pristine = pristine
    check("F72 a human-feedback mode still reads the previous response",
          [label for _p, label in pp.journal_previous_responses(human)]
          == ["human_review_feedback/response_to_reviewers.txt"])


# --- F73: classified TODO ids use the documented T-### form ----------------
def test_f73_tid_format():
    for bad in ("not-a-tid", "T-1", "T-0001", "id 7", "T-000"):
        rows, problems = pp.manual_todo_rows_from_text(
            HDR + f"| {bad} | minor | {pp.MANUAL_ACTIONS[0]} | x |\n")
        check(f"F73 {bad!r} is refused", not rows and bool(problems), str(problems))
    rows, problems = pp.manual_todo_rows_from_text(
        HDR + f"| T-001 | minor | {pp.MANUAL_ACTIONS[0]} | x |\n")
    check("F73 T-001 is accepted", len(rows) == 1 and not problems)
    rows, problems = pp.manual_todo_rows_from_text(
        HDR + f"| T-1000 | minor | {pp.MANUAL_ACTIONS[0]} | x |\n")
    check("F73 T-1000 is accepted", len(rows) == 1 and not problems)
    root = scratch("f73b")
    target = root / pp.AUTHOR_TO_COMPLETE_README
    target.write_text(HDR + f"| T-001 | minor | {pp.MANUAL_ACTIONS[2]} | kept row |\n",
                      encoding="utf-8")
    stage = root / "stage" / pp.AUTHOR_TO_COMPLETE_README
    stage.parent.mkdir()
    stage.write_text(HDR + f"| T-2 | minor | {pp.MANUAL_ACTIONS[2]} | bad stage row |\n",
                     encoding="utf-8")
    rec = pp.write_published_handoff_readme(
        root, {"items": []}, {"items": []}, existing_from=stage)
    check("F73 a stage row with a malformed id is reported, not silently dropped",
          bool(rec.get("problems"))
          and any("T-###" in str(p) for p in rec.get("problems") or []),
          str(rec.get("problems")))


def main():
    test_f63_band()
    test_f64_cover_total()
    test_f65_tid_collision()
    test_f66_applied_action()
    test_f67_one_table()
    test_f68_counts_only_profile()
    test_f69_mask_underscore()
    test_f70_partial_plan()
    test_f71_judgeable_integrated()
    test_f72_previous_responses()
    test_f73_tid_format()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: " + "; ".join(FAILS))
        return 1
    print("all group-G fix checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

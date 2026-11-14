#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 2, group `modes_prompts`.

Each check pins one candidate this wave re-validated on the tree and repaired:
  p02_journal_modes.py  F83 F84 F85 F86 F94
  p03_prompts.py        F01 F95 F96 F97 F98 F99 F102

Hermetic: every fixture lives under tempfile.mkdtemp(). Prompt defects are
proven by calling the builder and asserting on the emitted text; mode defects
by calling the mode functions with a tiny fake ctx.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_modes_prompts.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1115wave2modes_pp", "paper_pipeline.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def flat(text: str) -> str:
    return " ".join(str(text or "").split())


class FakeCtx:
    """The smallest ctx the mode readers/planners actually touch."""

    def __init__(self, cfg: dict, round_record=None, raises: str = ""):
        self.cfg = dict(cfg)
        self.state = {}
        self.root = None
        self._record = round_record
        self._raises = raises

    def rounds_count(self) -> int:
        return int(self.cfg.get("rounds") or 1)

    def round_get(self, r):
        if self._raises:
            raise RuntimeError(self._raises)
        return {} if self._record is None else self._record

    def round_rec(self, r):
        return self.round_get(r)


def scoped_cfg(mode: str = "major") -> dict:
    return {"revision_mode": mode, "rewrites": [2], "revises": [1], "rounds": 1,
            "judges": [1], "integrators": [0x0]}


def profile_with(**length_limits) -> "pp.VenueProfile":
    data = copy.deepcopy(pp._DEFAULT_VENUE_PROFILE)
    for art in data["article_types"]:
        if art["id"] == "article":
            art["length_limits"].update(length_limits)
    return pp.VenueProfile(data, origin="test")


# ---------------------------------------------------------------------------
# F83 -- a scoped mode runs no rewrite arm, whatever the config/plan records
# ---------------------------------------------------------------------------
def test_f83_scoped_mode_forbids_rewrites() -> None:
    print("\n== F83: major/minor enforce M=0 at the plan reader ==")
    ctx = FakeCtx(scoped_cfg("major"))
    check("F83 journal_rewrites_allowed is False for major",
          pp.journal_rewrites_allowed(ctx) is False)
    m, n = pp.round_counts(ctx, 1)
    check("F83 a hand-edited major config with rewrites [2] plans M=0", (m, n) == (0, 1),
          f"got {(m, n)}")
    pool = pp.round_pool_ids(m, n)
    check("F83 the pool carries no w arm", pool == ["a1", "a2"], str(pool))
    kinds = [e["kind"] for e in pp.round_run_plan(ctx, 1)]
    check("F83 the round run plan stages no rewrite session",
          "rewrite" not in kinds, str(kinds))
    check("F83 the scoped stages are still planned",
          {"concerns", "revise"} <= set(kinds), str(kinds))
    # A minor revision, same invariant.
    minor = FakeCtx(scoped_cfg("minor"))
    check("F83 minor also plans M=0", pp.round_counts(minor, 1) == (0, 1),
          str(pp.round_counts(minor, 1)))
    # The ordinary mode is untouched: the configured rewrites still run.
    normal = FakeCtx({"revision_mode": "continue", "rewrites": [2], "revises": [1],
                      "rounds": 1, "judges": [1], "integrators": [0x0]})
    check("F83 continue mode still plans M=2", pp.round_counts(normal, 1) == (2, 1),
          str(pp.round_counts(normal, 1)))
    rewritten = [e["kind"] for e in pp.round_run_plan(normal, 1)]
    check("F83 continue mode still stages its rewrite arms",
          "rewrite" in rewritten, str(rewritten))


# ---------------------------------------------------------------------------
# F84 -- every recorded-plan reader hard-fails on an unreadable round record
# ---------------------------------------------------------------------------
def test_f84_recorded_plan_readers_fail_closed() -> None:
    print("\n== F84: recorded-plan readers no longer re-derive from mutable config ==")
    corrupt = FakeCtx({"rounds": 1, "review_scope": ["formatting-writing"],
                       "champion_select": "judge", "judges": [2],
                       "rewrites": [2], "revises": [1]},
                      raises="corrupt round record")
    for name in ("round_counts", "round_review_scope", "round_champion_select",
                 "judges_enabled_spec", "round_judges", "round_integrators",
                 "round_integrated_run_ids"):
        fn = getattr(pp, name)
        try:
            if name in ("round_integrated_run_ids",):
                fn(corrupt, 1, 0, 1)
            else:
                fn(corrupt, 1)
            raised = False
        except SystemExit as exc:
            raised = exc.code not in (None, 0)
        check(f"F84 {name} dies on an unreadable round record", raised)
    # A READABLE recorded plan still wins over a different current config.
    recorded = FakeCtx({"rounds": 1, "review_scope": ["full"],
                        "champion_select": "judge", "judges": [2]},
                       round_record={"plan": {"champion_select": "revise",
                                              "review_scope": "formatting-writing",
                                              "judges": 3,
                                              "judges_enabled": "r1_w2_j1"}})
    check("F84 round_review_scope reads the recorded scope",
          pp.round_review_scope(recorded, 1) == "formatting-writing")
    check("F84 round_champion_select reads the recorded mode",
          pp.round_champion_select(recorded, 1) == "revise")
    check("F84 judges_enabled_spec reads the recorded selector",
          pp.judges_enabled_spec(recorded, 1) == "r1_w2_j1")
    # NO plan at all (not an error) still falls back to the config.
    plain = FakeCtx({"rounds": 1, "review_scope": ["formatting-writing"],
                     "champion_select": "judge"}, round_record={})
    check("F84 an absent plan falls back to the config scope",
          pp.round_review_scope(plain, 1) == "formatting-writing")
    check("F84 an absent plan falls back to the config champion mode",
          pp.round_champion_select(plain, 1) == "judge")


# ---------------------------------------------------------------------------
# F85 -- a venue-guideline cover-letter bound is not called a user preference
# ---------------------------------------------------------------------------
def test_f85_cover_letter_provenance() -> None:
    print("\n== F85: the cover-letter provenance follows the profile's own source ==")
    venue_src = ("Example Journal author guidelines: the cover letter's persuading part "
                 "is at most 200 words")
    venue = profile_with(**{"cover_letter": {"min": None, "max": 200, "total_max": None,
                                             "source": venue_src}})
    rule = flat(pp.length_rule_text(venue))
    check("F85 the length rule attributes a venue-sourced bound to the profile",
          "preference recorded by the venue profile" in rule
          and "master prompt's own preference" not in rule, rule[-300:])
    check("F85 the length rule does not call a venue bound a non-rule",
          "THE VENUE PROFILE'S RECORDED LIMIT" in rule
          and "NOT A COVER-LETTER WORD LIMIT" not in rule
          and "never presented as a journal requirement" not in rule, rule[:400])
    blocks = {k: flat(v) for k, v in pp.m19_blocks(venue).items()}
    denied = [k for k, v in blocks.items() if "publishes no cover-letter limit" in v]
    check("F85 no M19 block denies a limit the profile records", not denied, str(denied))
    userpref = [k for k, v in blocks.items()
                if "user's preference" in v or "USER PREFERENCE" in v]
    check("F85 no M19 block calls a venue bound a user preference", not userpref,
          str(userpref))
    check("F85 the M19 revise names the recorded limit and its number",
          "recorded" in blocks["revise"] and "at most 200 words" in blocks["revise"],
          blocks["revise"])
    check("F85 the judge block does not call a venue bound user-set",
          "user-set" not in blocks["judge"], blocks["judge"])
    standing = flat(pp.standing_exemptions_text(venue))
    check("F85 the standing exemption names the venue profile's recorded rule",
          "venue profile's recorded COVER-LETTER limit" in standing, standing[:400])
    check("F85 the standing exemption does not blame the master prompt",
          "master prompt's COVER-LETTER rule" not in standing)
    # The default master-prompt preference keeps its original provenance wording.
    default = pp.VenueProfile(copy.deepcopy(pp._DEFAULT_VENUE_PROFILE), origin="test")
    default_blocks = {k: flat(v) for k, v in pp.m19_blocks(default).items()}
    check("F85 the master-prompt preference still reads as a user preference",
          "publishes no cover-letter limit" in default_blocks["revise"]
          and "USER PREFERENCE" in default_blocks["review"], default_blocks["revise"][:300])
    check("F85 the default standing exemption still names the master prompt",
          "master prompt's COVER-LETTER rule"
          in flat(pp.standing_exemptions_text(default)))
    default_rule = flat(pp.length_rule_text(default))
    check("F85 the default length rule keeps the preference/non-requirement wording",
          "A RECORDED PREFERENCE, NOT A COVER-LETTER WORD LIMIT" in default_rule
          and "never presented as a journal requirement" in default_rule)


# ---------------------------------------------------------------------------
# F86 -- one checklist row per item, with one consistent author action
# ---------------------------------------------------------------------------
HDR = ("| TODO item ID | importance | author action | description |\n"
       "|---|---|---|---|\n")


def test_f86_handoff_readme_one_row_per_item() -> None:
    print("\n== F86: the hand-off README deduplicates by item identity ==")
    tmp = scratch("fbw2_f86_")
    root = tmp / "root"
    root.mkdir()
    (root / "a.txt").write_text("We used [AUTHOR TO COMPLETE: software version] here.\n",
                                encoding="utf-8")
    stage = tmp / "stage.md"
    stage.write_text(
        HDR + "| T-001 | major | MANUALLY DO/DO_NOT correct without any "
        "LLMs-recommended corrections | software version |\n", encoding="utf-8")
    out = root / pp.AUTHOR_TO_COMPLETE_README
    res = pp.write_published_handoff_readme(
        root,
        open_items={"items": [{"id": "F-1", "status": "fixed", "location": "a.txt",
                               "evidence": "software version", "check": "M1",
                               "severity": "major"}]},
        target_path=out, existing_from=stage)
    text = out.read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if re.match(r"^\|\s*T-\d{3}\s*\|", ln)]
    check("F86 the three spellings of one item become ONE row", len(rows) == 1, text)
    check("F86 the surviving row carries the applied correction's action",
          rows and pp.MANUAL_ACTIONS[0] in rows[0], rows)
    check("F86 the reported item count matches the single row",
          res.get("items") == 1, json.dumps(res))
    check("F86 the item text is preserved in the row",
          rows and "software version" in rows[0], rows)
    errs, _warns = pp.manual_todo_gate(root)
    check("F86 the package passes its own manual-TODO gate",
          not any("duplicate TODO item ID" in e for e in errs), str(errs))
    # A marker + ledger pair (no stage table) is still one row.
    tmp2 = scratch("fbw2_f86b_")
    root2 = tmp2 / "root"
    root2.mkdir()
    (root2 / "b.txt").write_text("We used [AUTHOR TO COMPLETE: software version] here.\n",
                                 encoding="utf-8")
    out2 = root2 / pp.AUTHOR_TO_COMPLETE_README
    pp.write_published_handoff_readme(
        root2, open_items={"items": [{"id": "F-1", "status": "fixed",
                                      "location": "b.txt",
                                      "evidence": "software version"}]},
        target_path=out2)
    text2 = out2.read_text(encoding="utf-8")
    check("F86 a ledger row and its marker row become one row",
          len([ln for ln in text2.splitlines()
               if re.match(r"^\|\s*T-\d{3}\s*\|", ln)]) == 1, text2)
    # Two DIFFERENT items that happen to share a payload are never merged.
    tmp3 = scratch("fbw2_f86c_")
    root3 = tmp3 / "root"
    root3.mkdir()
    (root3 / "a.txt").write_text("x\n", encoding="utf-8")
    (root3 / "b.txt").write_text("x\n", encoding="utf-8")
    out3 = root3 / pp.AUTHOR_TO_COMPLETE_README
    pp.write_published_handoff_readme(
        root3, open_items={"items": [
            {"id": "F-1", "status": "fixed", "location": "a.txt",
             "evidence": "software version"},
            {"id": "F-2", "status": "fixed", "location": "b.txt",
             "evidence": "software version"}]},
        target_path=out3)
    text3 = out3.read_text(encoding="utf-8")
    check("F86 two locations with the same payload stay two rows",
          len([ln for ln in text3.splitlines()
               if re.match(r"^\|\s*T-\d{3}\s*\|", ln)]) == 2, text3)


# ---------------------------------------------------------------------------
# F94 -- the no-cap branch keeps the profile's unmodelled-rule notes
# ---------------------------------------------------------------------------
def test_f94_no_cap_keeps_recorded_notes() -> None:
    print("\n== F94: a no-cap profile still states the rules its notes record ==")
    prof = profile_with(**{
        "abstract": {"base": None, "relaxation": None,
                     "note": "venue caps display items at 8; not modelled"},
        "main_text": {"base": None, "relaxation": None,
                      "note": "venue caps references at 50; not modelled"},
    })
    note = prof.length_limit_note("abstract")
    check("F94 the fixture carries the note", note == "venue caps display items at 8; not modelled",
          note)
    caps = pp._caps_clause(prof)
    check("F94 the no-cap clause names the recorded rules",
          "display items at 8" in caps and "references at 50" in caps, caps)
    blocks = {k: flat(v) for k, v in pp.m19_blocks(prof).items()}
    missing = [k for k, v in blocks.items()
               if "display items at 8" not in v or "references at 50" not in v]
    check("F94 every M19 mandate carries the recorded gaps", not missing, str(missing))
    rule = flat(pp.length_rule_text(prof))
    check("F94 the length rule names the recorded gaps",
          "display items at 8" in rule and "references at 50" in rule, rule[-400:])
    # A capped profile still renders its note (no regression).
    capped = profile_with(**{"main_text": {
        "note": "venue caps references at 50; not modelled"}})
    capped_caps = pp._caps_clause(capped)
    check("F94 a capped profile still renders its note",
          "references at 50" in capped_caps, capped_caps)
    # The generic profile records no note: no empty gap sentence is invented.
    generic = pp.load_venue_profile("generic")
    check("F94 a note-less profile adds no gap sentence",
          "profile's own notes" not in pp._caps_clause(generic),
          pp._caps_clause(generic))


# ---------------------------------------------------------------------------
# F01 -- the strict block keys its ban on the direction actually forbidden
# ---------------------------------------------------------------------------
def test_f01_strict_block_direction() -> None:
    print("\n== F01: the legacy content-edit block forbids only what the gate forbids ==")
    ins_only = flat(pp.content_edit_policy_block(False, True, False))
    check("F01 insertions-only block does not ban removal",
          "rather than removing or adding text" not in ins_only
          and "would add or remove a unit" not in ins_only, ins_only[-400:])
    check("F01 insertions-only block bans only additions",
          "rather than adding text" in ins_only and "would add a unit" in ins_only,
          ins_only[-400:])
    check("F01 insertions-only block keeps a deletion allowed",
          "a deletion remains allowed" in ins_only, ins_only[-400:])
    check("F01 insertions-only block states NO INSERTIONS and no NO DELETIONS",
          "NO INSERTIONS:" in ins_only and "NO DELETIONS:" not in ins_only)
    del_only = flat(pp.content_edit_policy_block(True, False, False))
    check("F01 deletions-only block bans only removals",
          "rather than removing text" in del_only
          and "would remove a" in del_only
          and "rather than removing or adding" not in del_only, del_only[-400:])
    check("F01 deletions-only block states NO DELETIONS and no NO INSERTIONS",
          "NO DELETIONS:" in del_only and "NO INSERTIONS:" not in del_only)
    both = flat(pp.content_edit_policy_block(False, False, False))
    check("F01 both-forbidden block is unchanged",
          "rather than removing or adding text" in both
          and "overrides every later instruction that would add or remove a unit" in both,
          both[-400:])


# ---------------------------------------------------------------------------
# F95/F96 -- operator-supplied text (retry diagnostic, sandbox path) is literal
# ---------------------------------------------------------------------------
def test_f95_f96_literal_operator_values() -> None:
    print("\n== F95/F96: retry diagnostics and sandbox paths stay literal ==")
    tmp = scratch("fbw2_f95_")
    base = tmp / "root@@ROUND@@"
    sb = base / "r1_cold_start_review"
    sb.mkdir(parents=True)
    prior = ("previous attempt failed: the checker said @@SELFCHECK@@ and "
             "@@DEFECT_CLASS_RULE@@ and @@MARKER_ROOT@@")
    text = pp.cold_start_review_prompt(sb, "r1_cold_start_review", 2,
                                       prior_failure=prior)
    check("F95 the prior failure never expands to a second self-check block",
          text.count("SELF-CHECK BEFORE THE MARKER") == 1,
          str(text.count("SELF-CHECK BEFORE THE MARKER")))
    check("F95 the prior-failure text is preserved literally",
          "@@SELFCHECK@@" in text and "@@DEFECT_CLASS_RULE@@" in text
          and "@@MARKER_ROOT@@" in text)
    check("F96 the cold-start prompt names the real sandbox",
          str(sb.resolve()) in text and "root2" not in text, str(sb.resolve()))
    for name, build in (
        ("judge", lambda s: pp.judge_prompt(s, "r1_judge_w2_j1", 1, "w2", 1, 2,
                                            ["w1", "a2"])),
        ("revision_audit", lambda s: pp.revision_audit_prompt(s, "r1_audit", 1)),
        ("revision_repair", lambda s: pp.revision_repair_prompt(s, "r1_repair", 1, 2)),
    ):
        built = build(sb)
        check(f"F96 the {name} prompt names the real sandbox",
              str(sb.resolve()) in built and "root2" not in built)


# ---------------------------------------------------------------------------
# F97 -- venue-profile values are data: their @@...@@ is never re-interpreted
# ---------------------------------------------------------------------------
def test_f97_venue_values_stay_literal() -> None:
    print("\n== F97: venue-profile values are not template syntax ==")
    sb = scratch("fbw2_f97_") / "r1_guided_review"
    sb.mkdir(parents=True)
    prof = copy.deepcopy(pp.load_venue_profile("generic"))
    prof.prompt["guidelines_source"] = "GUIDE @@SELFCHECK@@ and @@CAPTION_LIMIT@@"
    prof.prompt["subject"] = "SUBJ @@VENUE_EDITOR@@"
    prof.prompt["editor"] = "THE-EDITOR"
    text = pp.review_prompt(sb, "r1_guided_review", 1, venue=prof)
    check("F97 a token inside a venue value does not inject a rule block",
          text.count("SELF-CHECK BEFORE THE MARKER") == 1,
          str(text.count("SELF-CHECK BEFORE THE MARKER")))
    check("F97 the venue value keeps its literal tokens",
          "GUIDE @@SELFCHECK@@ and @@CAPTION_LIMIT@@" in text)
    check("F97 a value is not re-substituted by a later venue pass",
          "SUBJ @@VENUE_EDITOR@@" in text and "SUBJ THE-EDITOR" not in text)
    # The medium profile decodes the same values in its paged file.
    sb2 = scratch("fbw2_f97m_") / "r1_guided_review"
    sb2.mkdir(parents=True)
    pp.review_prompt(sb2, "r1_guided_review", 1, venue=prof, execution_profile="medium")
    paged = ""
    for p in sb2.rglob("PROFILE_RULES*.md"):
        paged += p.read_text(encoding="utf-8")
    check("F97 the paged file carries the decoded venue value",
          "SUBJ @@VENUE_EDITOR@@" in paged and "\x00" not in paged, paged[:200])


# ---------------------------------------------------------------------------
# F98 -- the judge gets no production-only base/ edit workflow
# ---------------------------------------------------------------------------
def test_f98_judge_shared_block() -> None:
    print("\n== F98: the judge prompt carries no `base/` production instruction ==")
    sb = scratch("fbw2_f98_")
    text = pp.judge_prompt(sb, "r1_judge_w2_j1", 1, "w2", 1, 2, ["w1", "a2"])
    check("F98 the judge prompt never says edits are made in base/",
          "all edits are made" not in text and "`base/`" not in text)
    check("F98 the judge prompt does not name a CURRENT manuscript in base/",
          "CURRENT manuscript" not in text)
    check("F98 the evidence rule is still present and view-neutral",
          "THE EVIDENCE AREAS ARE READ-ONLY" in text
          and "package under view" in text
          and "evidence/" in text)
    check("F98 the judge's own target/ framing survives",
          "target/       \u2014 the ONE package you judge" in text)


# ---------------------------------------------------------------------------
# F99 -- both auxiliary prompts state the source hierarchy they must apply
# ---------------------------------------------------------------------------
def test_f99_auxiliary_prompts_state_hierarchy() -> None:
    print("\n== F99: revision-audit/repair prompts define the source hierarchy ==")
    sb = scratch("fbw2_f99_")
    audit = pp.revision_audit_prompt(sb, "r1_audit", 1)
    repair = pp.revision_repair_prompt(sb, "r1_repair", 1, 2)
    for name, text in (("revision_audit", audit), ("revision_repair", repair)):
        check(f"F99 the {name} prompt carries the hierarchy order",
              "github code >" in text and pp.SOURCE_HIERARCHY in text)
        check(f"F99 the {name} prompt resolves its hierarchy token",
              "@@HIERARCHY_RECONCILE@@" not in text
              and "@@SOURCE_HIERARCHY@@" not in text)
        check(f"F99 the {name} prompt ties the hierarchy to a WRONG-VALUE decision",
              "SOURCE-HIERARCHY" in text and "READ-ONLY" in text)


# ---------------------------------------------------------------------------
# F102 -- the plan contract names every field the gate requires
# ---------------------------------------------------------------------------
def test_f102_plan_contract_matches_gate() -> None:
    print("\n== F102: the repair-plan contract matches the reader's required fields ==")
    sb = scratch("fbw2_f102_")
    audit = pp.revision_audit_prompt(sb, "r1_audit", 1)
    words = flat(audit)
    for needle in ("SIX keys", "REJECTS THE WHOLE PLAN", "`edit`", "`evidence`"):
        check(f"F102 the prompt states {needle!r}", needle in words)
    # The gate the prompt now describes: all six keys, non-empty location/basis/
    # edit/evidence, at least one of wrong/correct.
    (sb / "revised").mkdir(parents=True)
    (sb / "revised" / "manuscript.md").write_text("The value is 5.\n", encoding="utf-8")
    (sb / "revision_audit").mkdir()
    row = {"id": "RP-001", "file": "manuscript.md", "location": "Results p3",
           "wrong": "value is 5", "correct": "value is 6", "basis": "raw_data/x.csv",
           "edit": "replace 5 with 6"}
    plan = sb / "revision_audit" / "REPAIR_PLAN.json"
    plan.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    check("F102 a row without `evidence` invalidates the plan",
          pp._revision_plan_rows(sb) is None)
    row["evidence"] = "raw_data/x.csv row 2: 6"
    plan.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    parsed = pp._revision_plan_rows(sb)
    check("F102 a row with all six fields is accepted",
          bool(parsed) and parsed[0]["evidence"] == row["evidence"])
    row["edit"] = "  "
    plan.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    check("F102 an empty `edit` invalidates the plan",
          pp._revision_plan_rows(sb) is None)


def main() -> int:
    test_f83_scoped_mode_forbids_rewrites()
    test_f84_recorded_plan_readers_fail_closed()
    test_f85_cover_letter_provenance()
    test_f86_handoff_readme_one_row_per_item()
    test_f94_no_cap_keeps_recorded_notes()
    test_f01_strict_block_direction()
    test_f95_f96_literal_operator_values()
    test_f97_venue_values_stay_literal()
    test_f98_judge_shared_block()
    test_f99_auxiliary_prompts_state_hierarchy()
    test_f102_plan_contract_matches_gate()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL modes_prompts WAVE-2 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup()

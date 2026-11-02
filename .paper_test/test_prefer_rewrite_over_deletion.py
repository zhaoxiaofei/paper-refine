#!/usr/bin/env python3
"""Checks for the prefer-rewrite-over-deletion mode.

Run: python3 .paper_test/test_prefer_rewrite_over_deletion.py

The mode is OFF by default and must leave the off path byte-identical to the
pre-feature pipeline: the prompt block is the verbatim legacy function, the
run/prompt records are unchanged, and only the new flag turns the extra text on.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
import paper_pipeline as pp  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class Ctx:
    def __init__(self, **cfg):
        self.cfg = dict(cfg)
        self.root = None


def main() -> int:
    # OFF: the default and the strict block are the legacy text verbatim.
    check("off default block is empty",
          pp.content_edit_policy_block(True, True, False) == "")
    legacy = pp.content_edit_policy_block(False, False, False)
    check("off strict has the old duplicate sentence",
          "A true duplicate is" in legacy
          and "still a unit: keep it and record the recommendation for the author."
          in legacy)
    check("off strict has no prefer marker",
          "PREFER REWRITE OVER DELETION." not in legacy)

    # ON: the marker and the rewrite-before-manual-required instruction.
    prefer = pp.content_edit_policy_block(False, False, True)
    check("on strict has the marker", "PREFER REWRITE OVER DELETION." in prefer)
    check("on strict keeps NO DELETIONS", "NO DELETIONS:" in prefer)
    check("on strict tells the retry to rewrite", "retry message asks" in prefer)
    check("on strict has no manual-required-first sentence",
          "If the only way to resolve a finding is to remove text, record\n"
          "the finding as `manual-required`" not in prefer)
    soft = pp.content_edit_policy_block(True, True, True)
    check("on soft has the marker", "PREFER REWRITE OVER DELETION." in soft)
    check("on soft has no NO DELETIONS", "NO DELETIONS:" not in soft)
    check("on soft allows a best deletion",
          "A deletion is a last resort" in soft)
    check("on soft does not claim a strict block override",
          "does not forbid a content-unit edit" in soft)
    check("on strict still forbids deletion",
          "A deletion is never a" in prefer)

    # Config/override.
    check("default off", pp.prefer_rewrite_over_deletion(Ctx()) is False)
    check("cfg on", pp.prefer_rewrite_over_deletion(
        Ctx(prefer_rewrite_over_deletion="on")) is True)
    check("cfg off", pp.prefer_rewrite_over_deletion(
        Ctx(prefer_rewrite_over_deletion="off")) is False)
    c = Ctx(prefer_rewrite_over_deletion="on")
    c._prefer_rewrite_override = False
    check("run override off", pp.prefer_rewrite_over_deletion(c) is False)

    # Run records: the default is absent; the strict shape is unchanged when
    # the mode is off; the prefer key appears only when the mode is on.
    check("default record is None",
          pp.content_edit_policy_record(Ctx(), True, True, False) is None)
    strict = pp.content_edit_policy_record(Ctx(), False, False, False)
    check("strict record keeps the old shape",
          strict == {"insertions": False, "deletions": False})
    prefer_rec = pp.content_edit_policy_record(Ctx(), False, False, True)
    check("prefer record includes the flag",
          prefer_rec is not None
          and prefer_rec.get("prefer_rewrite_over_deletion") is True
          and prefer_rec.get("insertions") is False)
    # A stage prompted with the mode OFF must not be judged under a later
    # invocation's mode ON: the record carries the explicit False.
    bound_off = pp.content_edit_policy_record(
        Ctx(prefer_rewrite_over_deletion="on"), False, False, False)
    check("bound-off record carries False",
          bound_off is not None
          and bound_off.get("prefer_rewrite_over_deletion") is False)
    check("bound-off stage stays off under a current on",
          pp.prefer_rewrite_allowed(
              Ctx(prefer_rewrite_over_deletion="on"),
              {"content_edit_policy": bound_off}) is False)
    # Prompt matching and the prompt-bound mode.
    tmp = Path(tempfile.mkdtemp(prefix="prefer_rewrite_"))
    prompt = tmp / "PROMPT.md"
    prompt.write_text("a default prompt with no policy block\n", encoding="utf-8")
    check("default prompt matches off",
          pp.prompt_content_edit_policy_matches(prompt, True, True, False))
    prompt.write_text(legacy, encoding="utf-8")
    check("legacy strict prompt matches off",
          pp.prompt_content_edit_policy_matches(prompt, False, False, False))
    check("legacy strict prompt does not match prefer",
          not pp.prompt_content_edit_policy_matches(prompt, False, False, True))
    prompt.write_text(prefer, encoding="utf-8")
    check("prefer prompt matches prefer",
          pp.prompt_content_edit_policy_matches(prompt, False, False, True))
    check("prefer prompt states the mode",
          pp.prefer_rewrite_from_prompt(prompt) is True)
    check("prefer prompt does not match off",
          not pp.prompt_content_edit_policy_matches(prompt, False, False, False))
    check("prefer sandbox fallback from the prompt",
          pp.prefer_rewrite_for_sandbox(Ctx(), None, prompt) is True)

    # Applying the block: OFF is the legacy block; ON inserts the marker.
    text = "@@CONTENT_EDIT_POLICY@@\nbody text"
    off = pp.apply_content_edit_policy(text, False, False, False)
    on = pp.apply_content_edit_policy(text, False, False, True)
    check("apply off has no marker", "PREFER REWRITE OVER DELETION." not in off)
    check("apply off has NO DELETIONS", "NO DELETIONS:" in off)
    check("apply on has the marker", "PREFER REWRITE OVER DELETION." in on)

    # The revise prompt: OFF is the old prompt; ON adds the block.
    sb = tmp / "sandbox"
    sb.mkdir()
    old_prompt = pp.revise_prompt(sb, "r1_a2_revise", 1)
    new_prompt = pp.revise_prompt(
        sb, "r1_a2_revise", 1, deletions_allowed=False, prefer_rewrite=True)
    check("revise off has no marker", "PREFER REWRITE OVER DELETION." not in old_prompt)
    check("revise on has the marker", "PREFER REWRITE OVER DELETION." in new_prompt)
    check("revise on strict keeps NO DELETIONS", "NO DELETIONS:" in new_prompt)

    # The postcheck retry message.
    base = tmp / "base"
    cand = tmp / "cand"
    base.mkdir()
    cand.mkdir()
    (base / "a.md").write_text(
        "The treatment was effective in the first cohort of patients.\n", encoding="utf-8")
    (cand / "a.md").write_text(
        "Unrelated text stands in this paragraph without the original claim at all.\n",
        encoding="utf-8")
    old_problems = pp.content_edit_problems(
        None, base, cand, "x", insertions_allowed=False, deletions_allowed=False,
        prefer_rewrite=False)
    new_problems = pp.content_edit_problems(
        None, base, cand, "x", insertions_allowed=False, deletions_allowed=False,
        prefer_rewrite=True)
    check("postcheck off keeps the old message",
          bool(old_problems) and "REWRITE the missing unit" not in old_problems[0])
    check("postcheck on asks for a rewrite",
          bool(new_problems) and "REWRITE the missing unit" in new_problems[0])

    # CLI: setup/run accept the pair; the run default is None (config wins).
    parser = pp.build_parser()
    setup = parser.parse_args(
        ["setup", "--source", str(tmp / "src"), "--prefer-rewrite-over-deletion"])
    check("setup parser sets the flag",
          setup.prefer_rewrite_over_deletion is True
          and getattr(setup, "_prefer_rewrite_over_deletion_explicit", False) is True)
    setup = parser.parse_args(["setup", "--source", str(tmp / "src")])
    check("setup parser default is None",
          setup.prefer_rewrite_over_deletion is None)
    run = parser.parse_args(["run", "--root", str(tmp / "root")])
    check("run parser default is None",
          run.prefer_rewrite_over_deletion is None)
    run = parser.parse_args(
        ["run", "--root", str(tmp / "root"), "--no-prefer-rewrite-over-deletion"])
    check("run parser can turn it off",
          run.prefer_rewrite_over_deletion is False
          and getattr(run, "_prefer_rewrite_over_deletion_explicit", False) is True)

    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s)")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

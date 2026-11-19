#!/usr/bin/env python3
"""Regression tests for the 2026-11-19 fix-bugs wave 1, g7 (docs/config).

Run: python3 .paper_test/test_fix_bugs_20261119_g7_docs_config.py
"""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))

import paper_pipeline as pp  # noqa: E402

TMPDIRS = []
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def text(rel):
    return (WS / rel).read_text(encoding="utf-8")


def test_prompt_ranges():
    src = text("paper_pipeline_parts/p03_prompts.py")
    check("F109 the attached Phase-1 brief names M1-M36",
          "mechanical sweeps M1–M36" in src and "mechanical sweeps M1–M17" not in src)
    check("F109 the attached Phase-1 brief names J1-J5",
          "passes J1–J5" in src and "passes J1–J4" not in src)
    check("F112 the revise prompt names edit rules E1-E13",
          "the edit rules E1–E13" in src and "under rules E1-E13" in src
          and "E1–E12" not in src and "E1-E12" not in src)
    rules = text("paper-skills/paper-revise/references/edit_rules.md")
    check("F112 the edit-rules title covers E13", "Edit Rules E1–E13" in rules)
    skill = text("paper-skills/paper-revise/SKILL.md")
    check("F112 the SKILL text covers E13", "rules E1–E13" in skill)
    prompt = text("paper-skills/prompts/adress_issues.prompt.md")
    check("F112 the standalone adress_issues body covers E13",
          "under rules E1–E13" in prompt and "E1–E12" not in prompt)
    readme = text("paper-skills/README.md")
    check("F112 the skills README indexes E13",
          "E1–E13, P1, C" in readme and "E1–E12" not in readme)
    check("F116 the legend-spacing rule is venue-conditional",
          "blanket" in text("paper-skills/paper-review/references/sweeps.md")
          and "`w:line=240`), or legend" not in
          text("paper-skills/paper-review/references/sweeps.md"))


def test_aux_stage_sidecar():
    sb = scratch("fbg7_rules_")
    instr = sb / "INSTRUCTIONS"
    instr.mkdir()
    (instr / "PROFILE_RULES.md").write_text("_Stage: revise_\n# rules\n", encoding="utf-8")
    old = pp.read_text_bounded
    pp.read_text_bounded = lambda _p: None
    try:
        got = pp._stage_rules_rel(sb, "revision_audit")
        got_repair = pp._stage_rules_rel(sb, "revision_repair")
        got_revise = pp._stage_rules_rel(sb, "revise")
    finally:
        pp.read_text_bounded = old
    check("F119 revision_audit gets its own sidecar when the paged file is unreadable",
          got == "INSTRUCTIONS/PROFILE_RULES_revision_audit.md", got)
    check("F119 revision_repair gets its own sidecar",
          got_repair == "INSTRUCTIONS/PROFILE_RULES_revision_repair.md", got_repair)
    check("F119 revise keeps the documented path",
          got_revise == pp.PROFILE_RULES_REL, got_revise)


def test_readme_mismatches():
    readme = text("README.md")
    check("F151 README names the emitted score_model key",
          "its `score_model` defines" in readme and "score_model_doc` defines" not in readme)
    check("F153 README heading covers FMT-PDF1-7",
          "FMT-PDF1–7" in readme and "FMT-PDF1–4)" not in readme)
    check("F154 README judge example says two of w2's judges",
          "two of w2's judges" in readme and "three judges" not in readme)
    check("F155 README records the external-dependency absolute-path exception",
          "except a dependency installed outside the checkout" in readme
          and "Zotero bridge" in readme)
    check("F159 README frozen-runtime row includes dsh_events.py",
          "`dsh_events.py`" in readme)
    check("F185 README package-consistency heading reaches PKG-26",
          "Package self-consistency: PKG-11 to PKG-26" in readme)


def test_venue_length_limits_fallback():
    prof = copy.deepcopy(pp.load_venue_profile("generic").to_dict())
    prof["length_limits"] = {
        "source": "venue table",
        "abstract": {"base": 150, "relaxation": 1.1},
        "main_text": {"base": 3000, "relaxation": 1.1},
    }
    for entry in prof.get("article_types") or []:
        entry["length_limits"] = None
    norm = pp.normalize_venue_profile(prof)
    limits = pp.VenueProfile(norm).length_limits()
    check("F178 venue-level abstract limit survives an article types table",
          limits["abstract"]["base"] == 150, repr(limits["abstract"]))
    check("F178 venue-level main-text limit survives too",
          limits["main text"]["base"] == 3000, repr(limits["main text"]))
    check("F178 the cap is computed from the inherited base/relaxation",
          limits["abstract"]["cap"] is not None, repr(limits["abstract"]))


def test_explicit_empty_setup_args():
    for key in ("venue", "article_type"):
        args = SimpleNamespace(rounds=1, venue="generic", venue_profile=None,
                               journal=None, article_type=None, strict_venue=False)
        setattr(args, key, "")
        try:
            pp.cmd_setup(args)
        except SystemExit as e:
            check(f"F182 setup --{key} '' is a usage error", e.code == 2, repr(e.code))
        else:
            check(f"F182 setup --{key} '' is a usage error", False, "exited 0")


def test_setup_freezes_validated_profile_bytes():
    src = text("paper_pipeline_parts/p09_setup.py")
    check("F179 setup installs the validated in-memory bytes",
          "write_json_atomic(_dest, _pdata)" in src
          and "shutil.copyfile(pf, _dest)" not in src)
    check("F179 setup refuses a symlinked --venue-profile",
          "is a symlink; pass the real file" in src)
    check("F184 an unreadable prior profile is refused before install",
          "refusing to overwrite bytes that cannot be restored" in src)
    cli = text("paper_pipeline_parts/p17_cli.py")
    check("F181 set-venue --article-type help no longer promises an explicit fallback",
          "is rejected, while a type " in cli
          and "recorded from the old profile falls back" in cli
          and "does not carry falls back to that profile's default" not in cli)


def test_required_parts_preflight():
    tmp = scratch("fbg7_parts_")
    for name in pp.PIPELINE_ASSET_DIRS:
        (tmp / name).mkdir(parents=True, exist_ok=True)
    for name in list(pp.PIPELINE_MODULE_FILES) + list(pp.PIPELINE_REQUIRED_ASSET_FILES):
        dest = tmp / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x", encoding="utf-8")
    missing = pp._missing_bundle_assets(tmp)
    check("F186 a parts tree missing p21 fails the startup preflight",
          "paper_pipeline_parts/p21_removal_accounting.py" in missing, repr(missing[:4]))


def main():
    test_prompt_ranges()
    test_aux_stage_sidecar()
    test_readme_mismatches()
    test_venue_length_limits_fallback()
    test_explicit_empty_setup_args()
    test_setup_freezes_validated_profile_bytes()
    test_required_parts_preflight()
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("\nG7 PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        import shutil
        for tmp in TMPDIRS:
            shutil.rmtree(tmp, ignore_errors=True)

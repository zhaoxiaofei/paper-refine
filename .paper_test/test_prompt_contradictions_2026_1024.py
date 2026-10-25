#!/usr/bin/env python3
"""Contradiction-audit regressions (2026-1024).

Pins the fixes for the internal rule contradictions confirmed against the
2026-10-24 audit folder (`audit_data/2026-1024-1247-contradiction-audit/`).
Every check that pins a changed rule surface fails on the pre-fix tree and
passes after the corresponding patch; the few checks that pin preserved
behaviour (the default profile's provenance wording, for example) pass on both
trees. The checks read the shipped rule surfaces, not a scratch copy.

Run:  python3 .paper_test/test_prompt_contradictions_2026_1024.py
"""
from __future__ import annotations

import copy
import importlib.util
import os
import re
import sys
from pathlib import Path

from bundle_source_lib import source_text
WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_contradictions", str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["paper_contradictions"] = pp
spec.loader.exec_module(pp)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def read(rel):
    p = WS / rel
    if rel in ("paper_pipeline.py", "paper_docx_format.py"):
        return source_text(p, encoding="utf-8")
    return p.read_text(encoding="utf-8")


def flat(text):
    return " ".join(text.split())


def profile_with_total_cap(total=650):
    data = copy.deepcopy(pp.default_venue_profile().data)
    data["article_types"][0]["length_limits"]["cover_letter"]["total_max"] = total
    return pp.VenueProfile(data)


# ---------------------------------------------------------------- C01
sweeps = read("paper-skills/paper-review/references/sweeps.md")
edit_rules = read("paper-skills/paper-revise/references/edit_rules.md")
revise_skill = read("paper-skills/paper-revise/SKILL.md")
identify_prompt = read("paper-skills/prompts/identify_issues.prompt.md")
adress_prompt = read("paper-skills/prompts/adress_issues.prompt.md")
check("C01 sweeps calls the list propagation order, not the value authority",
      "Conflict resolution priority (which occurrence is authoritative" not in sweeps
      and "Propagation order" in sweeps
      and "source hierarchy decides" in flat(sweeps))
check("C01 edit_rules P1 no longer says the list picks the authoritative value",
      "authoritative value follows the review's resolution priority" not in flat(edit_rules)
      and "this propagation order" in flat(edit_rules)
      and "never decides which VALUE wins" in flat(edit_rules))
check("C01 revise SKILL P bullet is propagation-order wording",
      "Propagation order" in revise_skill and "source hierarchy in E12 decides" in flat(revise_skill))
check("C01 adress prompt P bullet is propagation-order wording",
      "Propagation order" in adress_prompt and "source hierarchy in E12 decides" in flat(adress_prompt))

# ---------------------------------------------------------------- C02
prof = pp.default_venue_profile()
assembled = pp.shared_blocks() + pp.attached_phase1(prof)
check("C02 no unqualified 'never flag abstract/main-text' in the assembled prompt",
      "Standing exemption (my preference, applies to every mode)" not in flat(assembled)
      and "WITHDRAWN here" in flat(assembled))
check("C02 the master excerpt states the withdrawal and points at M19",
      "WITHDRAWN" in pp.ATTACHED_PHASE1 and "M19" in pp.ATTACHED_PHASE1)
check("C02 the M19 rule no longer says the excerpt below still carries the exemption",
      "excerpt below still carries" not in flat(pp.length_rule_text(prof)))

# ---------------------------------------------------------------- C03
check("C03 rewrite M30 block reports, never resolves",
      "do NOT resolve it here" in flat(pp.HIERARCHY_RECONCILE_REWRITE)
      and "resolve it only when" not in flat(pp.HIERARCHY_RECONCILE_REWRITE))
pipeline_src = read("paper_pipeline.py")
check("C03 rewrite hard rule 7 uses RECORD, not RESOLVE",
      "RESOLVE a source conflict" not in pipeline_src
      and "do NOT resolve it here" in flat(pipeline_src))
check("C03 rewrite layout never says to touch/revise code",
      "only touch it if the rewritten text genuinely requires it" not in pipeline_src
      and "Do not edit it: a code change is the revision stage's job" in flat(pipeline_src))

# ---------------------------------------------------------------- C04
code_paths = [p for p in (WS / "paper-skills").rglob("*")
              if p.is_file() and p.suffix in (".md", ".py", ".txt")]
upper = [str(p.relative_to(WS)) for p in code_paths
         if re.search(r"\bCODE/", p.read_text(encoding="utf-8", errors="ignore"))]
check("C04 no skill document uses the uppercase CODE/ path", not upper, ", ".join(upper))
check("C04 the pipeline's code directory is lowercase", pp.CODE_DIR == "code")

# ---------------------------------------------------------------- C05
check("C05 FMT-CL1 revise rule keeps the defect only on a journal requirement",
      "LEAVE it only when" in pp.M20_REVISE_RULE
      and "Fix it only when" not in pp.M20_REVISE_RULE)
check("C05 postcheck claim is narrowed to newly introduced rows",
      "NEWLY introduces the row" in flat(pp.M20_REVISE_RULE))

# ---------------------------------------------------------------- C06
check("C06 M32 qualifies 'never adjust a number' against E12",
      "never adjust a number to make the stated correction pass" in flat(pp.EVIDENCE_INTEGRITY_REVISE)
      and "E12" in pp.EVIDENCE_INTEGRITY_REVISE)

# ---------------------------------------------------------------- C07
check("C07 M36 defers to the automatic offline refresh, author only on refusal",
      "automatic offline `zotero-refresh`" in pp.EVIDENCE_INTEGRITY_REVISE
      and "only when that refresh refuses" in flat(pp.EVIDENCE_INTEGRITY_REVISE))

# ---------------------------------------------------------------- C08
default_caption = pp.caption_rule_text(50, prof)
check("C08 caption precedence scopes the blanket rule to the persuading part",
      "for its persuading part" in default_caption
      and "TOTAL-content cap" in default_caption)
check("C08 the caption rule no longer quotes the withdrawn blanket sentence",
      "length-driven cuts in either direction" not in flat(default_caption))
length_rule = pp.length_rule_text(prof)
check("C08 'never flag under-length' is scoped to abstract/main text",
      "Never flag UNDER-length abstract or main text" in flat(length_rule)
      and "cover-letter preference is the one configured floor" in flat(length_rule))
cap_prof = profile_with_total_cap()
cap_caption = pp.caption_rule_text(50, cap_prof)
cap_revise = pp.m19_blocks(cap_prof)["revise"]
check("C08 a configured total cap is an allowed cover-letter length cut",
      "TOTAL-content cap" in cap_caption
      and "bring its TOTAL content within 650 words" in flat(cap_revise))

# ---------------------------------------------------------------- C11
check("C11 identify prompt protects all three evidence areas",
      "llm_review_feedback/" in identify_prompt
      and "human_review_feedback/" in identify_prompt
      and "original_submission/" in identify_prompt)
check("C11 adress prompt protects all three evidence areas",
      "llm_review_feedback/" in adress_prompt
      and "human_review_feedback/" in adress_prompt
      and "original_submission/" in adress_prompt)

# ---------------------------------------------------------------- C15
check("C15 integration class (d) means every donor, not at least one",
      "a defect present in the base AND in EVERY donor" in flat(pipeline_src)
      and "a defect present in the base AND in at least one donor" not in flat(pipeline_src))

# ---------------------------------------------------------------- C16
check("C16 E1 calls M25-M29 in-place parity edits, not scoped restructuring",
      "in-place parity edits for the rewrite-parity" in flat(edit_rules)
      and "scoped restructuring** for the review's architecture findings (J5) and rewrite-parity" not in flat(edit_rules))

# ---------------------------------------------------------------- C20
check("C20 integration rescan names its own frozen set, not the revise V3",
      "as the revision skill's V3 requires" not in flat(pipeline_src)
      and "frozen integration rescan set" in flat(pipeline_src))

# ---------------------------------------------------------------- C21
check("C21 improvement rows accept the full check-id range",
      "(M1-M36 / J1-J5)" in pipeline_src
      and "(M1-M20 / J1-J4)" not in pipeline_src)

# ---------------------------------------------------------------- C22
check("C22 revise directives use E1-E12",
      "rules E1-E12" in pipeline_src and "rules E1-E6" not in pipeline_src
      and "rules E1–E12" in pipeline_src and "rules E1–E6" not in pipeline_src)

# ---------------------------------------------------------------- C23
check("C23 language pass gates claim calibration on a frozen finding",
      "CLAIM CALIBRATION IS GATED" in pp.LANGUAGE_PASS_RULE
      and "frozen" in flat(pp.LANGUAGE_PASS_RULE)
      and "J3/CLAIM_STRENGTH" in pp.LANGUAGE_PASS_RULE)

# ---------------------------------------------------------------- C24
frontiers = pp.load_venue_profile("frontiers-in-immunology", root=str(WS))
front_rule = pp.length_rule_text(frontiers)
check("C24 Frontiers cover-letter provenance names the profile, not the master prompt",
      "master prompt's own preference" not in front_rule
      and "preference recorded by the venue profile" in flat(front_rule)
      and "at most 200 words" in front_rule)
check("C24 default profile keeps the master-prompt preference wording",
      "master prompt's own preference" in pp.length_rule_text(prof))
check("C24 cover-letter heading does not call the venue rule a non-rule",
      "NOT A FRONT IMMUNOL RULE" not in front_rule)

# ---------------------------------------------------------------- C26
readme = read("README.md")
check("C26 README states the judge's own frozen M1-M24 + J1-J4 set",
      "the judge runs the same frozen sweep set as the review" not in flat(readme)
      and "M1–M24 + J1–J4" in readme)

# ---------------------------------------------------------------- C27
brief = pp.load_venue_profile("nature-biotechnology", root=str(WS)).with_article_type(
    "brief-communication")
check("C27 Frontiers counts Methods inside its main text (not the NBT Article rule)",
      "methods" not in frontiers.main_text_excludes()
      and "Methods INSIDE the count" in flat(pp.length_rule_text(frontiers)))
check("C27 the default profile keeps the NBT Article convention (Methods excluded)",
      "methods" in prof.main_text_excludes()
      and "the abstract, Methods, references and figure legends EXCLUDED"
      in flat(pp.length_rule_text(prof)))
check("C27 the Brief Communication counts abstract/references/legends inside",
      {"abstract", "references", "figure-legends"}.isdisjoint(brief.main_text_excludes())
      and "INSIDE the count" in flat(pp.length_rule_text(brief)))
check("C27 the counting convention is profile data, not prompt prose",
      "counting.main_text.excludes" in flat(sweeps))

# ---------------------------------------------------------------- C28
check("C28 no dangling reference-chat pointer",
      "reference-chat" not in sweeps)
check("C28 no dangling standing-exemption pointer in M1(h)",
      "standing exemption on length-driven cuts" not in flat(sweeps))
check("C28 discovery pointer says M37, not M18",
      "proposals start at M18" not in flat(pipeline_src)
      and "proposals start at M37" in flat(pipeline_src))

print(f"\n{len(FAILS)} failed")
if FAILS:
    for f in FAILS:
        print("  FAILED:", f)
sys.exit(1 if FAILS else 0)

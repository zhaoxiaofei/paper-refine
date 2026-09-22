#!/usr/bin/env python3
"""Cross-agent consistency: ONE rule set for the reviewer, auditor, rewriter,
reviser, integrator and (blind) comparison session; and the new defaults.

Run:  python3 .nbt_test/test_agent_consistency_2026_0922.py

The operator found the sessions applying different rules -- an integration
session invited to IGNORE a "cosmetic-only difference" that the comparison
sessions SCORE as a counted minor row, adopted checks that only some sessions
knew about, an auditor with no disposition bar. The cure is mechanical: one text
in one place, injected verbatim into every prompt, plus this suite, which fails
if any prompt loses a block or grows a private rule. The ONLY allowed asymmetry
is the comparison session's blindness to provenance (which session produced
which package, when, in what order).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nb = _load("nbt_consistency", WS / "nbt_pipeline.py")
stub_agent = _load("nbt_consistency_stub", WS / ".nbt_test" / "stub_agent.py")
stub_judge = _load("nbt_consistency_judge", WS / ".nbt_test" / "stub_judge.py")
FAILS = []
TMPDIRS = []

PROVENANCE_WORDS = {
    r"\bround\b": "round", r"\barm\b": "arm", r"\brewrite\b": "rewrite",
    r"\brevised\b": "revised", r"\brevision\b": "revision",
    r"\bintegration\b": "integration", r"\bmerge\b": "merge",
    r"\bchampion\b": "champion", r"\b(?:a1|a2|w1|i1)\b": "arm id",
    r"\br\d+_judge": "round-prefixed run id", r"CHANGELOG": "bookkeeping name",
    r"MANUAL_STEPS": "bookkeeping name", r"REVISION_REPORT": "bookkeeping name",
    r"DIFF_LEDGER": "bookkeeping name", r"AUTHOR TO COMPLETE": "marker token",
}


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def cli(*argv, timeout=900):
    return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def prompts() -> dict:
    P = Path("/tmp/x")
    return {
        "review": nb.review_prompt(P, "r1_review", 1),
        "audit": nb.audit_prompt(P, "r1_audit", 1),
        "rewrite": nb.rewrite_prompt(P, "r1_w1", 1, index=1, total=2),
        "revise": nb.revise_prompt(P, "r1_a2_revise", 1),
        "integrate": nb.integrate_prompt(P, "r1_i1", 1, self_id="a1", other_ids=["w1"]),
        "judge": nb.judge_prompt(P, "judge_tok_j1", 1, "tok", 1, 1, ["v1"]),
    }


# ---------------------------------------------------------------------------
# 1. one rule set in every prompt
# ---------------------------------------------------------------------------


def test_shared_blocks_everywhere():
    print()
    print("== the same decision rules and the same adopted checks in every session ==")
    P = prompts()
    shared = nb.shared_blocks()
    for role, text in P.items():
        check(f"{role}: carries the shared rules + adopted checks verbatim",
              text.count(shared) == 1,
              f"occurrences={text.count(shared)}")
        check(f"{role}: no unresolved token", not re.search(r"@@[A-Z_]+@@", text))
    rules = {role: text[text.index("=== THE SHARED DECISION RULES"):
                       text.index("=== THE ADOPTED CHECKS")]
             for role, text in P.items()}
    check("the rule text is byte-identical across all six sessions",
          len(set(rules.values())) == 1, str({k: len(v) for k, v in rules.items()}))
    for key in ("D1. ONE vocabulary", "D2. FOUR dispositions", "D3. NOTHING NAMEABLE",
                "D4. ONE bar", "D5. ONE manual list", "D6. ONE reading", "D7. ONE exception"):
        check(f"the shared rules carry {key!r}",
              all(key in t for t in P.values()))


def test_role_applicable_blocks():
    print()
    print("== a rule applicable to one session is applicable to every session it can affect ==")
    P = prompts()
    # These blocks are provenance-free and apply to every session that reads a
    # package: the checklist, the evidence reading, the vocabulary, the bars, the
    # standing exemptions, the auxiliary/derived-output rules and the validator.
    universal = {
        "CONCLUSION/VOCABULARY": "DEFECT CLASSES — ONE VOCABULARY",
        "STANDING EXEMPTIONS": "Standing exemptions",
        "HAND-OFF AUXILIARIES": "PIPELINE AUXILIARY FILES",
        "DERIVED OUTPUTS": "DERIVED BUILD OUTPUTS",
        "VISUAL INSPECTION": "VISUAL INSPECTION",
        "DOCX CLI": "OPTIONAL TOOLING",
        "ZOTERO ROUTE": "ZOTERO REFERENCE TOOLING",
        "VALIDATION": "VALIDATION AFTER EDITING",
        "CAPTION RULE": "FIGURE-LEGEND LENGTH",
        "LENGTH RULE": "ABSTRACT / MAIN-TEXT LENGTH",
        "ADOPTED CHECKS": "=== THE ADOPTED CHECKS",
    }
    for label, needle in universal.items():
        missing = [role for role, text in P.items() if needle not in text]
        check(f"{label} is in all six sessions", not missing, f"missing in {missing}")
    # The placeholder rule has exactly one documented variant: the comparison
    # session's provenance-neutral wording.
    check("the hand-off marker rule is in the five non-comparison sessions",
          all("PIPELINE HAND-OFF PLACEHOLDERS" in P[r]
              for r in ("review", "audit", "rewrite", "revise", "integrate")))
    check("the comparison session carries the neutral placeholder rule instead",
          "PLACEHOLDER TEXT IN A PACKAGE" in P["judge"]
          and "PIPELINE HAND-OFF PLACEHOLDERS" not in P["judge"])
    # Role-specific rules stay role-specific, and the ones that look universal
    # are named here so a future drift has to argue with this list.
    check("the language pass is in the three package-producing sessions",
          all("LANGUAGE PASS" in P[r] for r in ("rewrite", "revise", "integrate"))
          and all("LANGUAGE PASS" not in P[r] for r in ("review", "audit")))
    check("the difference ledger is in the integration session only",
          "INTEGRATION DIFFERENCE LEDGER" in P["integrate"]
          and all("INTEGRATION DIFFERENCE LEDGER" not in P[r]
                  for r in ("review", "audit", "rewrite", "revise")))
    check("the comparison session maps its rubric onto the same eleven checks",
          "Q1-Q11 correspond one-to-one to the" in P["judge"])
    check("the two validation variants differ only by the bookkeeping name",
          nb.validation_block("judge").replace("your own review note", "")
          == nb.VALIDATION_RULE.replace("MANUAL_STEPS.md", ""))


def test_cosmetic_rule_is_one_rule():
    print()
    print("== a nameable difference is never 'cosmetic' -- for anyone ==")
    P = prompts()
    rule = nb.DEFECT_CLASS_RULE_TEMPLATE
    check("the shared vocabulary says a nameable difference is never cosmetic",
          "A difference that\n    cannot be named in this vocabulary is COSMETIC" in rule
          or "cannot be named in this vocabulary is COSMETIC" in rule.replace("\n", " "))
    check("it says formatting/writing are counted minor rows, not cosmetic",
          "formatting` and `writing` included" in rule)
    check("the integration session's difference classes no longer say 'IGNORE'",
          "-> IGNORE" not in P["integrate"] and "cosmetic-only difference" not in P["integrate"])
    check("the integration rule tells the session what a drop requires",
          "not nameable" in P["integrate"] and "Dropping a NAMEABLE difference" in P["integrate"])
    check("the comparison session scores formatting/writing rows instead of ignoring them",
          "MINOR-ONLY" in P["judge"] and "can never decide a comparison" in P["judge"])
    check("both sessions read the same cosmetic sentence from the shared rules",
          P["judge"].count("cannot be named in this vocabulary is COSMETIC") == 1
          and P["integrate"].count("cannot be named in this vocabulary is COSMETIC") == 1)


def test_check_id_coverage():
    print()
    print("== every session disposes the same check ids ==")
    P = prompts()
    for cid in ("M21", "M22", "M23", "M24"):
        check(f"{cid} is named in every session's prompt",
              all(cid in t for t in P.values()),
              str([r for r, t in P.items() if cid not in t]))
    expected = tuple(nb.JUDGE_COVERAGE_CHECKS)
    check("the pipeline's judge coverage list carries M1-M24 + J1-J4",
          all(f"M{i}" in expected for i in range(1, 25))
          and all(f"J{i}" in expected for i in range(1, 5)),
          str(len(expected)))
    check("the two judge stubs dispose exactly the pipeline's check ids (same set)",
          set(stub_judge.JUDGE_CHECK_IDS) == set(expected)
          and set(stub_agent.JUDGE_CHECK_IDS) == set(expected),
          f"{len(stub_judge.JUDGE_CHECK_IDS)} vs {len(expected)}")
    # The review postcheck requires M18-M24 coverage, so the SKILL the reviewer
    # actually reads must list the same ids: a coverage table built from the
    # skill's own list (M1-M17, J1-J4, M18-M20) fails the run with "coverage
    # table is missing check id(s) ['M21', 'M22', 'M23', 'M24']". This check is
    # the runtime proof of the contract (the old one was `... or True`, which
    # could never fail).
    tmp = scratch("nbt_cov_")
    sb = tmp / "r1_review"
    (sb / "base").mkdir(parents=True)
    skill_ids = ([f"M{i}" for i in range(1, 18)] + ["M18", "M19", "M20"]
                 + [f"J{i}" for i in range(1, 5)])
    fj = {"submission_dir": "base",
          "coverage": [{"check": c, "disposition": "clean -- basis: x"} for c in skill_ids]}
    errs, warns = [], []
    nb.check_review_contract(None, sb, fj, errs, warns)
    check("the review postcheck really requires M21-M24",
          any(all(c in e for c in ("M21", "M22", "M23", "M24")) for e in errs),
          str(errs)[:160])
    skill = (WS / "nbt-skills" / "nbt-review" / "SKILL.md").read_text(encoding="utf-8")
    sweeps = (WS / "nbt-skills" / "nbt-review" / "references" / "sweeps.md").read_text(
        encoding="utf-8")
    coverage_line = next((l for l in skill.splitlines() if l.startswith("5. Coverage table")), "")
    acceptance_line = next((l for l in skill.splitlines() if "coverage table lists every" in l), "")
    format_line = next((l for l in sweeps.splitlines() if l.startswith("check:")), "")
    check("SKILL.md's coverage table lists the adopted M21-M24",
          "M21–M24" in coverage_line or all(c in coverage_line
                                            for c in ("M21", "M22", "M23", "M24")),
          coverage_line[:160])
    check("SKILL.md's acceptance list no longer calls M21+ 'once adopted'",
          ("M21–M24" in acceptance_line
           or all(c in acceptance_line for c in ("M21", "M22", "M23", "M24")))
          and "once proposals are adopted" not in acceptance_line, acceptance_line[:160])
    check("sweeps.md's FINDING FORMAT admits M21-M24 finding ids",
          "M1–M24" in format_line and "M1–M20|J1–J4" not in format_line,
          format_line[:160])
    src = (WS / "nbt_pipeline.py").read_text(encoding="utf-8")
    check("the review postcheck's required-coverage list names M21-M24",
          'wanted += ["M21", "M22", "M23", "M24"]' in src)


def test_judge_tier_and_sweep_scope():
    """The comparison session's own directives must carry its own contract.

    Contract v3 requires a disposition for every frozen check id M1-M17,
    M18-M24, J1-J4, and the graded basis has six tiers -- but the directive's
    task-1 sentence stopped the frozen set at M1-M17 (+M18-M20) "ONLY", and its
    PRIORITY ORDER listed five tiers (no `writing`, the tier the WRITING RUBRIC
    in the same prompt scores). A judge that obeys the sentence cannot honestly
    fill the M21-M24 dispositions, and one that obeys the priority order has no
    place for the writing rows.
    """
    print()
    print("== the judge's scope sentence and priority order match its own contract ==")
    jp = prompts()["judge"]
    jl = jp.splitlines()
    start = next((i for i, l in enumerate(jl) if "FROZEN SWEEP SET" in l), None)
    # The sentence wraps across lines, and the ids may be written as a range
    # ("M18-M24"), exactly like the skill's own "M1-M17".
    frozen = " ".join(jl[start:start + 4]) if start is not None else ""
    check("the frozen-set sentence names the adopted M21-M24",
          "M18-M24" in frozen or "M21-M24" in frozen
          or all(f"M{i}" in frozen for i in range(21, 25)), frozen[:200])
    priority = next((l for l in jp.splitlines() if "correctness  >" in l), "")
    positions = [priority.find(t) for t in nb.BASIS_TIERS]
    check("the priority order lists every graded-basis tier, in order",
          all(p >= 0 for p in positions) and positions == sorted(positions),
          f"{priority.strip()[:120]} vs BASIS_TIERS={nb.BASIS_TIERS}")
    check("the prior-round sweep rule names the adopted M18-M24 too",
          all(c in nb.PRIOR_ROUND_RULE for c in ("M18", "M24")),
          nb.PRIOR_ROUND_RULE[:160])


def test_judge_blind_exception():
    print()
    print("== the one allowed asymmetry: the comparison session knows no provenance ==")
    P = prompts()
    hits = {label: re.findall(pat, P["judge"], re.I)
            for pat, label in PROVENANCE_WORDS.items()}
    hits = {k: v for k, v in hits.items() if v}
    check("the comparison session's prompt is free of provenance vocabulary",
          not hits, str(list(hits))[:200])
    check("it states the blinding rule", "BLINDING RULE" in P["judge"])
    check("every other session DOES get the provenance it needs to act",
          all(("round" in P[r].lower()) or (r == "revise") for r in ("review", "audit")))
    check("the judge's check ids are provenance-free ids only",
          all(re.fullmatch(r"M\d+|J\d+", c) for c in nb.JUDGE_COVERAGE_CHECKS))


# ---------------------------------------------------------------------------
# 2. the new defaults
# ---------------------------------------------------------------------------


def test_defaults_and_flags():
    print()
    print("== the safer policy is the default; the `--non-…` flags restore the old one ==")
    check("DEFAULT_AUDIT is on", nb.DEFAULT_AUDIT == "on")
    check("DEFAULT_PLACEHOLDER_LOOKUP is online", nb.DEFAULT_PLACEHOLDER_LOOKUP == "online")
    check("DEFAULT_STRICT_ARTIFACTS is True", nb.DEFAULT_STRICT_ARTIFACTS is True)
    check("DEFAULT_RESIDUAL_GATE is True", nb.DEFAULT_RESIDUAL_GATE is True)
    setup_help = cli("setup", "--help").stdout
    for flag in ("--no-audit", "--no-placeholder-lookup", "--non-strict-artifacts"):
        check(f"setup documents {flag}", flag in setup_help)
    decide_help = cli("decide", "--help").stdout
    check("decide documents --non-residual-gate", "--non-residual-gate" in decide_help)
    tmp = scratch("nbt_consistency_cfg_")
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text("Abstract\n\nwords here.\n", encoding="utf-8")
    r = cli("setup", "--source", str(src), "--root", str(tmp / "root"), "--rounds", "1",
            "--judges", "1", "--rewrites", "0", "--revises", "1")
    check("setup succeeds with defaults", r.returncode == 0, (r.stderr or r.stdout)[-200:])
    cfg = json.loads((tmp / "root" / "pipeline_config.json").read_text(encoding="utf-8"))
    check("a fresh root records the new defaults",
          cfg.get("audit") == "on" and cfg.get("placeholder_lookup") == "online"
          and cfg.get("strict_artifacts") is True,
          json.dumps({k: cfg.get(k) for k in ("audit", "placeholder_lookup",
                                              "strict_artifacts")}))
    ctx = type("C", (), {"cfg": cfg})()
    check("audit_enabled/strict_dispositions read those defaults",
          nb.audit_enabled(ctx) is True and nb.strict_dispositions(ctx) is True)
    # The `--no-…` flags must actually switch the policy off.
    r2 = cli("setup", "--source", str(src), "--root", str(tmp / "root2"), "--rounds", "1",
             "--judges", "1", "--rewrites", "0", "--revises", "1",
             "--no-audit", "--no-placeholder-lookup", "--non-strict-artifacts")
    cfg2 = json.loads((tmp / "root2" / "pipeline_config.json").read_text(encoding="utf-8"))
    ctx2 = type("C", (), {"cfg": cfg2})()
    check("the --no-... flags restore the advisory, two-step plan",
          cfg2.get("audit") == "off" and cfg2.get("placeholder_lookup") == "off"
          and cfg2.get("strict_artifacts") is False
          and nb.audit_enabled(ctx2) is False and nb.strict_dispositions(ctx2) is False,
          json.dumps({k: cfg2.get(k) for k in ("audit", "placeholder_lookup",
                                               "strict_artifacts")}))
    check("the resolve-aware flags parse in one invocation",
          r2.returncode == 0, (r2.stderr or r2.stdout)[-200:])


def test_residual_gating_split():
    print()
    print("== the gate carries what the pipeline can decide; advisory stays advisory ==")
    state = {"runs": {
        "r1_a2_revise": {"id": "r1_a2_revise", "kind": "revise", "status": "done",
                         "residual": {"answerable_placeholders": 1,
                                      "unsourced_numbers_in_abstract_legends": 2}},
        "r1_review": {"id": "r1_review", "kind": "review", "status": "done",
                      "artifact_quality": {"artifacts/M20_formatting.md": ["boilerplate"]}},
        "r1_i1": {"id": "r1_i1", "kind": "integrate", "status": "done",
                  "diff_ledger": {"rows": 3, "undoes": ["w1: undoes F-002"],
                                  "missing_artifact": ["w2"]}},
    }}
    ctx = type("C", (), {"state": state})()
    res = nb.collect_residuals(ctx)
    gating = " | ".join(res["gating"])
    advisory = " | ".join(res["advisory"])
    check("an answered marker in a delivered package is GATING",
          "searchable hand-off marker" in gating)
    check("a boilerplate decision artifact is GATING", "decision artifact" in gating)
    check("an integration row that would undo a resolved finding is GATING",
          "UNDO a resolved finding" in gating)
    check("an unsourced abstract/legend number is ADVISORY only",
          "not proved by any shipped data table" in advisory
          and "not proved by any shipped data table" not in gating)


def main() -> int:
    try:
        test_shared_blocks_everywhere()
        test_role_applicable_blocks()
        test_cosmetic_rule_is_one_rule()
        test_check_id_coverage()
        test_judge_tier_and_sweep_scope()
        test_judge_blind_exception()
        test_defaults_and_flags()
        test_residual_gating_split()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("all cross-agent consistency checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

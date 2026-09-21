#!/usr/bin/env python3
"""W-11 (arm levels, integration difference artifacts, regression compare) and
W-12 (the language pass in every package-producing stage, the judge's writing
rubric).

Run:  python3 .nbt_test/test_arm_levels_and_language_2026_0922.py

W-11: a round with more than one rewrite stages BOTH levels -- one structural
(organization) arm and one sentence-level arm -- so the integration pool carries
large and small differences and the DIFF_LEDGER has both kinds of rows to weigh.
Every ledger row needs its own artifact (a before/after pair for a small row, an
outline diff for a large one) and a statement of what it does to a resolved
finding, and a stage may not introduce a NEW finding-tier defect family.

W-12: the L1-L11 language pass runs in every package-producing stage with one
coverage row per step, and the judge scores prose against a named 12-check
rubric (Q1-Q12) instead of taste -- kept free of provenance vocabulary so the
blind panel stays blind.
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


nb = _load("nbt_armlang", WS / "nbt_pipeline.py")
STUB = WS / ".nbt_test" / "stub_agent.py"
FAILS = []
TMPDIRS = []


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


def make_text_corpus(dirp: Path) -> None:
    dirp.mkdir(parents=True, exist_ok=True)
    (dirp / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 80).strip() + "\n\nIntroduction\n\n"
        + ("text " * 110).strip() + "\n\nFigure 1 | A legend here.\n\nMethods\n\nx\n",
        encoding="utf-8")


# ---------------------------------------------------------------------------
# W-11a: the rewrite arms work at declared levels
# ---------------------------------------------------------------------------


def test_rewrite_levels():
    print()
    print("== the round stages a structural arm and a sentence-level arm ==")
    check("a single rewrite arm is structural (organization is what a rewrite is for)",
          nb.rewrite_level_of(1, 1) == "structural")
    check("two arms are one of each",
          [nb.rewrite_level_of(k, 2) for k in (1, 2)] == ["structural", "sentence"])
    check("three arms alternate, structural first",
          [nb.rewrite_level_of(k, 3) for k in (1, 2, 3)]
          == ["structural", "sentence", "structural"])
    structural = nb.rewrite_prompt(Path("/tmp/x"), "r1_w1", 1, index=1, total=2,
                                   level="structural")
    sentence = nb.rewrite_prompt(Path("/tmp/x"), "r1_w2", 1, index=2, total=2,
                                 level="sentence")
    check("the structural arm's prompt declares STRUCTURAL and asks for moves",
          "THIS ARM'S LEVEL: STRUCTURAL" in structural
          and "Level: structural" in structural
          and "ORGANIZATION level" in structural)
    check("the sentence arm's prompt declares SENTENCE and forbids reorganization",
          "THIS ARM'S LEVEL: SENTENCE" in sentence
          and "Level: sentence" in sentence
          and "same paragraphs in the same" in sentence)
    check("the level default follows the index/total when not given",
          "THIS ARM'S LEVEL: SENTENCE" in nb.rewrite_prompt(Path("/tmp/x"), "r1_w2", 1,
                                                            index=2, total=2))
    check("no unresolved token remains in either prompt",
          not re.search(r"@@[A-Z_]+@@", structural + sentence))


# ---------------------------------------------------------------------------
# W-11b: the integration ledger's per-difference artifacts
# ---------------------------------------------------------------------------


def test_diff_ledger_rule_and_report():
    print()
    print("== every difference row needs its own artifact and a finding effect ==")
    rule = nb.DIFF_LEDGER_RULE
    check("the rule names the two new columns",
          "artifact (a path under integrated/work/)" in rule
          and "finding effect (preserves <id> / undoes <id> / none)" in rule)
    check("the rule requires an artifact per row and both size classes",
          "EVERY row carries an ARTIFACT" in rule
          and "BOTH `size` classes" in rule)
    tmp = scratch("nbt_armlang_ledger_")
    out = tmp / "integrated"
    (out / "work" / "diffs").mkdir(parents=True)
    (out / "work" / "diffs" / "D-001.md").write_text("before/after", encoding="utf-8")
    (out / "DIFF_LEDGER.md").write_text(
        "| id | donor | location | size | donor says | self says | verdict | why | effect | "
        "artifact | finding effect |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| D-001 | w1 | p3 | large | x | y | port | better flow | none | "
        "integrated/work/diffs/D-001.md | preserves F-002 |\n"
        "| D-002 | w2 | p9 | small | a | b | keep-self | self is precise | none |  | "
        " |\n", encoding="utf-8")
    rep = nb.integration_ledger_report(out, ["w1", "w2"], expect_both_levels=True)
    check("both size classes are seen", rep["both_levels"] is True, str(rep))
    check("the row without an artifact is reported",
          rep["missing_artifact"] == ["w2"], str(rep["missing_artifact"]))
    check("the row without a finding effect is reported",
          rep["missing_finding"] == ["w2"], str(rep["missing_finding"]))
    check("a `preserves` row is not an undo", not rep["undoes"], str(rep["undoes"]))
    (out / "DIFF_LEDGER.md").write_text(
        (out / "DIFF_LEDGER.md").read_text(encoding="utf-8").replace("preserves F-002",
                                                                     "undoes F-002"),
        encoding="utf-8")
    rep2 = nb.integration_ledger_report(out, ["w1", "w2"], expect_both_levels=True)
    check("an `undoes` row is surfaced", rep2["undoes"] and "F-002" in rep2["undoes"][0],
          str(rep2["undoes"]))
    check("a donor missing from the table is surfaced",
          nb.integration_ledger_report(out, ["w1", "w3"], expect_both_levels=True)
          ["donors_absent"] == ["w3"])


# ---------------------------------------------------------------------------
# W-11c: a stage may not introduce a NEW finding-tier family
# ---------------------------------------------------------------------------


def test_scan_regression_compare():
    print()
    print("== 'the fix introduced a new class of defect' is a comparison, not an opinion ==")
    tmp = scratch("nbt_armlang_scan_")
    before = tmp / "base"
    after = tmp / "out"
    before.mkdir()
    after.mkdir()
    (before / "m.md").write_text("A short clean sentence. Another one.\n", encoding="utf-8")
    (after / "m.md").write_text(
        "A short clean sentence. Another one. " + ("word " * 60).strip() + ".\n",
        encoding="utf-8")
    ctx = type("C", (), {"cfg": {}})()
    errs, warns = nb.scan_regression_problems(ctx, [(before, "", ())], [(after, "", ())],
                                              "fixture")
    check("a NEW finding-tier family (a Methods-length sentence in a body paragraph) is an ERROR",
          any("NEW finding-tier defect family" in e for e in errs), str(errs)[:220])
    (after / "m.md").write_text((before / "m.md").read_text(encoding="utf-8"), encoding="utf-8")
    errs2, warns2 = nb.scan_regression_problems(ctx, [(before, "", ())], [(after, "", ())],
                                                "fixture")
    check("an unchanged package has no regression", not errs2 and not warns2,
          f"{errs2} {warns2}")


# ---------------------------------------------------------------------------
# W-12a: the language pass in every package-producing stage
# ---------------------------------------------------------------------------


def test_language_pass_contract_and_prompts():
    print()
    print("== the L1-L11 pass runs in every package-producing stage ==")
    rule = nb.LANGUAGE_PASS_RULE
    check("the rule demands a coverage row per step",
          "COVERAGE: the file ENDS with one row per step" in rule
          and "UNAUDITED" in rule)
    check("the rule demands a code-side re-scan after each step",
          "AFTER EACH STEP, re-run the code-side scan" in rule)
    for builder, args in ((nb.rewrite_prompt, ("r1_w1", 1)),
                          (nb.integrate_prompt, ("r1_i1", 1)),
                          (nb.revise_prompt, ("r1_a2_revise", 1))):
        if builder is nb.rewrite_prompt:
            text = builder(Path("/tmp/x"), args[0], args[1], index=1, total=2)
        elif builder is nb.integrate_prompt:
            text = builder(Path("/tmp/x"), args[0], args[1], self_id="a1",
                           other_ids=["w1"], )
        else:
            text = builder(Path("/tmp/x"), args[0], args[1])
        check(f"{builder.__name__} carries the language pass with its own R6 path",
              "LANGUAGE PASS" in text and "work/R6_language.md" in text
              and not re.search(r"@@R6_PATH@@", text))
    tmp = scratch("nbt_armlang_r6_")
    pkg = tmp / "pkg"
    (pkg / "work").mkdir(parents=True)
    rep = nb.language_pass_report(pkg)
    check("a missing artifact reports all eleven steps missing",
          rep["present"] is False and len(rep["missing"]) == 11, str(rep))
    (pkg / "work" / "R6_language.md").write_text(
        "| step | location | before | after | reason |\n|---|---|---|---|---|\n"
        "| L9 | p3 | stiff | smoother | flow |\n\n## coverage\n\n"
        "| step | rows changed | note |\n|---|---|---|\n"
        + "\n".join(f"| L{i} | 0 | none found |" for i in range(1, 12)) + "\n",
        encoding="utf-8")
    rep2 = nb.language_pass_report(pkg)
    check("a complete coverage table is accepted",
          rep2["present"] and not rep2["missing"] and rep2["rows"] >= 1, str(rep2))
    (pkg / "work" / "R6_language.md").write_text(
        "| step | location | before | after | reason |\n|---|---|---|---|---|\n"
        "| L9 | p3 | stiff | smoother | flow |\n"
        "| L4 | p4 | vague referent | named | clarity |\n", encoding="utf-8")
    rep3 = nb.language_pass_report(pkg)
    check("the steps with no coverage row are named",
          set(rep3["missing"]) == {f"L{i}" for i in range(1, 12)} - {"L4", "L9"},
          str(rep3["missing"])[:80])
    # 2026-09-22: strict is the DEFAULT, so an uncovered step fails the attempt;
    # `--non-strict-artifacts` is the opt-out that records it as a warning.
    ctx_strict = type("C", (), {"cfg": {}})()
    errs2, warns2 = [], []
    nb.check_language_pass(ctx_strict, {"id": "r1_w1"}, pkg, "rewrite", errs2, warns2)
    check("under the default (strict) policy the gap is an ERROR", bool(errs2), str(errs2)[:160])
    ctx = type("C", (), {"cfg": {"strict_artifacts": False}})()
    errs, warns = [], []
    nb.check_language_pass(ctx, {"id": "r1_w1"}, pkg, "rewrite", errs, warns)
    check("under --non-strict-artifacts the gap is a recorded WARNING",
          not errs and any("language pass" in w for w in warns), str(warns)[:160])


# ---------------------------------------------------------------------------
# W-12b: the judge's writing rubric
# ---------------------------------------------------------------------------


def test_judge_writing_rubric():
    print()
    print("== the judge scores prose against a named rubric, blind ==")
    prompt = nb.judge_prompt(Path("/tmp/x"), "judge_tok9_j3", 1, "tok9", 1, 1, ["v1"])
    check("the rubric is in the judge prompt",
          "WRITING RUBRIC" in prompt and "Q12 segmentation" in prompt
          and "Q7" in prompt)
    check("the rubric maps the tier's checks to the same ideas the pass fixes",
          all(k in prompt for k in ("Q1 ", "Q4 ", "Q5 ", "Q6 ", "Q10 ", "Q11 ")))
    forbidden = {
        r"\bround\b": "round", r"\barm\b": "arm", r"\brewrite\b": "rewrite",
        r"\brevised\b": "revised", r"\brevision\b": "revision",
        r"\bintegration\b": "integration", r"\bmerge\b": "merge",
        r"\bchampion\b": "champion", r"\b(?:a1|a2|w1|i1)\b": "arm id",
        r"\br\d+_judge": "round-prefixed run id", r"CHANGELOG": "bookkeeping name",
        r"MANUAL_STEPS": "bookkeeping name", r"REVISION_REPORT": "bookkeeping name",
        r"DIFF_LEDGER": "bookkeeping name", r"AUTHOR TO COMPLETE": "marker",
    }
    hits = {label: re.findall(pat, prompt, re.I) for pat, label in forbidden.items()}
    hits = {k: v for k, v in hits.items() if v}
    check("the rubric keeps the judge prompt free of provenance vocabulary", not hits,
          str(list(hits))[:160])
    check("the tier is still minor-only in the prompt",
          "MINOR-ONLY" in prompt and "can never decide a comparison" in prompt
          and "writing +-1" in prompt)


# ---------------------------------------------------------------------------
# end to end: a stub round with two arms, one of each level
# ---------------------------------------------------------------------------


def test_stub_round_arm_levels():
    print()
    print("== stub round: the two arms declare different levels, the integration ledger "
          "carries both ==")
    tmp = scratch("nbt_armlang_e2e_")
    src = tmp / "src"
    make_text_corpus(src)
    root = tmp / "root"
    r = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1",
            "--judges", "1", "--rewrites", "2", "--revises", "0",
            "--placeholder-lookup", "off")
    check("setup succeeds", r.returncode == 0, (r.stderr or r.stdout)[-200:])
    r = cli("run", "--root", str(root), "--only", "rewrite",
            "--agent-cmd", json.dumps([sys.executable, str(STUB)]), "--retries", "0")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    levels = {rid: (rec.get("rewrite_level") or "")
              for rid, rec in state["runs"].items() if rec.get("kind") == "rewrite"}
    check("the two rewrite runs carry the two levels",
          sorted(levels.values()) == ["sentence", "structural"],
          json.dumps(levels))
    check("the levels are also written into the prompts",
          any("THIS ARM'S LEVEL: SENTENCE" in
              (root / "runs" / rid / "PROMPT.md").read_text(encoding="utf-8")
              for rid in levels),
          str(list(levels))[:80])
    reported = {}
    for rid in levels:
        rep = root / "runs" / rid / "rewritten" / "REWRITE_REPORT.md"
        m = re.search(r"(?im)^Level:\s*(\w+)", rep.read_text(encoding="utf-8")) if rep.is_file() else None
        reported[rid] = m.group(1).lower() if m else ""
        check(f"{rid}: the report declares its level and the language pass exists",
              reported[rid] == levels[rid]
              and (root / "runs" / rid / "rewritten" / "work" / "R6_language.md").is_file(),
              f"{reported[rid]} vs {levels[rid]}")
        rec = state["runs"][rid]
        check(f"{rid}: the postcheck recorded the language-pass coverage",
              (rec.get("language_pass") or {}).get("present") is True
              and not (rec.get("language_pass") or {}).get("missing"),
              json.dumps(rec.get("language_pass") or {})[:160])
    r = cli("run", "--root", str(root), "--only", "integrate",
            "--agent-cmd", json.dumps([sys.executable, str(STUB)]), "--retries", "0")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    integ = [rec for rec in state["runs"].values() if rec.get("kind") == "integrate"
             and rec.get("status") == "done"]
    check("the integration runs completed", bool(integ), str(len(integ)))
    if integ:
        led = integ[0].get("diff_ledger") or {}
        check("the integration ledger reports both size classes",
              led.get("both_levels") is True, json.dumps(led)[:200])
        check("the integration ledger's rows carry artifacts",
              not led.get("missing_artifact"), json.dumps(led)[:200])
        check("the integration ledger's rows state their finding effect",
              not led.get("missing_finding"), json.dumps(led)[:200])
        out = root / "runs" / integ[0]["id"] / "integrated"
        check("the per-difference artifact files exist",
              bool(list((out / "work" / "diffs").glob("D-*.md"))))


def main() -> int:
    try:
        test_rewrite_levels()
        test_diff_ledger_rule_and_report()
        test_scan_regression_compare()
        test_language_pass_contract_and_prompts()
        test_judge_writing_rubric()
        test_stub_round_arm_levels()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("all arm-level / language-pass checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

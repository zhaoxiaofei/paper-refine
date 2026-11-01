#!/usr/bin/env python3
"""The 2026-11-01 brief_communication incident: verified defect regressions.

Run:  python3 .paper_test/test_fix_bugs_20261101_220000.py

The evaluation run at results-261101-1130-5428e7d/default-pr/cases/
brief_communication/ spent 4h08m of its 8h05m on three rejected attempts and
finished with `active champion=None`. Every rejection was a paperwork contract
failure, and every one of them was invisible to the session's own pre-flight:

  D1  `audit` attempt 1 -- the coverage table had 28 of 41 rows and 12 cells the
      disposition gate refused. `sandbox_selfcheck` never called
      `audit_coverage_problems`, so it printed "the paperwork checks passed" on
      a table `postcheck_audit` then rejected 14 times. It also could not be run
      at all: the prompt's absolute driver path is masked in a jailed harness.
  D2  the disposition gate rejected TRUE rows: `... X-910 confirmed (CI does not
      contain point estimate)` failed on the word "not", and `No findings; ...` /
      `unable to check <object>` failed on wording that names the same verdict.
  D3  `revise` attempt 1 -- the SAME T-001..T-013 table in MANUAL_STEPS.md and
      README-AUTHOR-TO-COMPLETE.md. The prompt sent "unfixable issues" to
      MANUAL_STEPS.md under `readme` mode while the rules named the README as
      the manual list, and nothing said the two files share ONE id space.
      `sandbox_selfcheck` never called the TODO gate: "passed" 23 seconds
      before the rejection.
  D4  `revise` attempt 2 -- 53 of 53 seeded M30 rows EMPTY in the sandbox copy,
      all 53 disposed in `revised/work/`. The postcheck read only the sandbox
      copy, so a reviser that did the work lost the attempt. The message also
      reported `len(problems)` as "1 undisposed row(s)" and pasted 80 characters
      of the first problem into it, cut mid-word and leaving a parenthesis open.
  D5  the round summary clipped `last_error` at 200 characters, so the log ended
      "... must record the producer" instead of the requirement.

Each check names the defect id above it regresses.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fix_bugs_pipeline_1101", WS / "paper_pipeline.py")

ACTIONS = ("CONFIRM/REJECT correction made by LLMs",
           "MANUALLY DO/DO_NOT correct with LLMs-recommended corrections provided",
           "MANUALLY DO/DO_NOT correct without any LLMs-recommended corrections")


# ---------------------------------------------------------------------------
# D2 -- the audit coverage gate accepts a true disposition and still refuses
#       filler and a negated re-derivation.
# ---------------------------------------------------------------------------
# Every disposition below is quoted from the rejected audit/audit.json. The
# verdict is "is this a recorded disposal?", not "is it well written".
LOG_DISPOSITIONS = (
    # rejected only because the EVIDENCE contained a negation ("not"/"does not")
    ("M4", "F-002, F-003, F-004, F-009, F-010, F-029 confirmed (p-value labels, CI "
           "direction, unit error); X-901, X-902, X-907, X-908, X-909, X-947 dropped as "
           "duplicates; X-910 confirmed (CI does not contain point estimate)", True),
    ("M26", "F-030 confirmed (normalized vs -ise); X-949 dropped (exposure is a standard "
            "term, not a defect)", True),
    # "No findings; <evidence>" is the same verdict as "0 findings"
    ("M18", "No findings; legend word count recorded (13 words for Figure 1)", True),
    ("M19", "No findings; abstract 133 words, main text 1600 words; no venue caps configured",
     True),
    ("M21", "No cover letter in submission; no findings", True),
    ("M23", "No supplementary material in submission; no findings", True),
    # "unable to check <object>" is the same verdict as "unable -- <reason>"
    ("M25", "No rendered artwork files in corpus; unable to check artwork/text parity", True),
    ("M31", "No rendered artwork files; unable to check artwork/legend parity", True),
    ("M34", "No shipped source data files for figures; unable to check source data coverage",
     True),
    # these two name no verdict and no artifact: they stay refused
    ("M22", "No data/code availability locators with DOIs or repository URLs; F-031 covers "
            "the raw_data reference", False),
    ("M24", "No competing term families found (see M24_concepts.md)", False),
    ("M28", "No sibling-definition asymmetry detected", False),
    # a bare `clean` with no basis is the filler shape the gate was built to refuse
    ("M36", "No Zotero fields in corpus (markdown-only submission); clean", False),
)

REFUSED = ("never verified at all", "the sweep was not re-derived", "could not be checked",
           "not checked", "x", "done", "", "unable -- no", "clean -- basis: x",
           "out of scope", "out of scope --", "unable to check")

ACCEPTED = ("stub: the sweep was re-derived; clean",
            "confirmed by re-opening every cited artifact",
            "clean -- basis: artifacts/M1.md", "3 findings", "0 findings",
            "out of scope -- formatting-only pass", "unable -- no PDF renderer",
            # A finding COUNT is a complete verdict: an inability clause in the
            # EVIDENCE must not veto it. The first version of the prose-`unable`
            # branch answered first and refused both of these.
            "3 findings; unable to see",
            "3 findings confirmed (the reviewer was unable to tell)",
            "confirmed by re-opening every cited artifact; unable to tell")


def test_d2_dispositions() -> None:
    print("\n== D2: the audit coverage gate accepts a true disposition ==")
    for cid, text, want in LOG_DISPOSITIONS:
        got = pp._audit_disposition_ok(text)
        check(f"D2 {cid} is {'accepted' if want else 'refused'}", got == want,
              f"got={got} text={text[:70]!r}")
    for text in REFUSED:
        check(f"D2 filler/negation {text!r} is refused", not pp._audit_disposition_ok(text))
    for text in ACCEPTED:
        check(f"D2 {text!r} is accepted", pp._audit_disposition_ok(text))
    # The gate is still the REVIEW gate's filler gate: a reason must name
    # something, not one letter.
    check("D2 the shared reason check is what refuses filler reasons",
          not pp._coverage_reason_named("x")
          and not pp._coverage_reason_named("no")
          and pp._coverage_reason_named("no PDF renderer"))


# ---------------------------------------------------------------------------
# D1 -- a coverage table with missing rows / refused cells fails the gate, and
#       that gate is the one the PRE-FLIGHT runs.
# ---------------------------------------------------------------------------
def _coverage_table(disposition_by_check: dict) -> dict:
    return {"coverage": [{"check": c, "disposition": disposition_by_check.get(
        c, "clean -- basis: work/x.md")} for c in pp.AUDIT_COVERAGE_CHECKS]}


def test_d1_preflight_coverage() -> None:
    print("\n== D1: the audit pre-flight runs the coverage gate ==")
    full = _coverage_table({})
    check("D1 a complete coverage table passes", pp.audit_coverage_problems(full) == [])
    # The exact shape of the rejected table: 28 of 41 rows.
    partial = {"coverage": [{"check": c, "disposition": "clean -- basis: work/x.md"}
                            for c in list(pp.AUDIT_COVERAGE_CHECKS)[:28]]}
    problems = pp.audit_coverage_problems(partial)
    check("D1 a 28-of-41 table is refused", bool(problems), str(problems)[:120])
    check("D1 the missing-row message names the ids",
          any("missing" in p for p in problems), str(problems)[:160])
    # Filler still passes no row.
    filler = _coverage_table({c: "never verified at all" for c in pp.AUDIT_COVERAGE_CHECKS})
    check("D1 a table of negations is refused for every row",
          len(pp.audit_coverage_problems(filler)) == len(pp.AUDIT_COVERAGE_CHECKS))


# ---------------------------------------------------------------------------
# D1b -- the self-check's audit branch now runs the coverage gate too.
# ---------------------------------------------------------------------------
AUDIT_JSON = """{
  "round": 1,
  "dispositions": [],
  "adds": [],
  "counts": {"confirmed": 0, "dropped": 0, "added": 0},
  "coverage": [{"check": "M1", "disposition": "clean -- basis: work/x.md"}],
  "notes": ""
}
"""


def _audit_sandbox(root: Path, table: str) -> Path:
    sb = root / "r1_audit"
    (sb / "audit").mkdir(parents=True, exist_ok=True)
    (sb / "audit" / "audit.json").write_text(table, encoding="utf-8")
    (sb / "audit" / "AUDIT.md").write_text("# audit\n", encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(
        '{"stage": "audit", "run_id": "r1_audit", "round": 1, "status": "complete",'
        ' "error": null, "findings_total": 0, "confirmed": 0, "dropped": 0, "added": 0,'
        ' "finding_tier_rows_examined": 0, "promoted": 0}', encoding="utf-8")
    return sb


def test_d1b_selfcheck_audit() -> None:
    print("\n== D1b: the audit pre-flight reports the coverage rejection ==")
    root = scratch("d1b_")
    short = _audit_sandbox(root / "short_root", AUDIT_JSON)
    ok, errs, _warns = pp.sandbox_selfcheck(short, "audit", "r1_audit", 1)
    check("D1b a 1-of-41 coverage table FAILS the pre-flight", not ok, str(errs)[:160])
    check("D1b the pre-flight names the missing coverage rows",
          any("coverage row(s) are missing" in e for e in errs), str(errs)[:200])

    good = _audit_sandbox(
        root / "good_root",
        '{"round": 1, "dispositions": [], "adds": [],'
        ' "counts": {"confirmed": 0, "dropped": 0, "added": 0}, "coverage": ['
        + ",".join('{"check": "%s", "disposition": "clean -- basis: work/x.md"}' % c
                   for c in pp.AUDIT_COVERAGE_CHECKS)
        + '], "notes": ""}')
    ok2, errs2, _w2 = pp.sandbox_selfcheck(good, "audit", "r1_audit", 1)
    check("D1b a complete coverage table passes the pre-flight",
          not [e for e in errs2 if "coverage" in e], str(errs2)[:160])


# ---------------------------------------------------------------------------
# D3 -- a duplicate id across MANUAL_STEPS.md and the hand-off README is an
#       error, and the PRE-FLIGHT reports it.
# ---------------------------------------------------------------------------
def _table(ids, note="x") -> str:
    rows = "".join(f"| {i} | minor | {ACTIONS[0]} | {note} |\n" for i in ids)
    return ("| TODO item ID | importance | author action | description |\n"
            "|---|---|---|---|\n" + rows)


def test_d3_duplicate_ids() -> None:
    print("\n== D3: the TODO id space is shared across the two files ==")
    root = scratch("d3_")
    pkg = root / "revised"
    pkg.mkdir()
    (pkg / "MANUAL_STEPS.md").write_text(_table(["T-001", "T-002"], "manual"), encoding="utf-8")
    (pkg / "README-AUTHOR-TO-COMPLETE.md").write_text(
        _table(["T-001", "T-002"], "readme"), encoding="utf-8")
    errs, _warns = pp.manual_todo_problems(pkg)
    dup = [e for e in errs if "duplicate TODO item ID" in e]
    check("D3 the same ids in both files are errors", len(dup) == 2, str(errs)[:200])
    check("D3 the message names the README file",
          any("README-AUTHOR-TO-COMPLETE.md" in e for e in dup), str(dup)[:160])

    # The read-only half never rewrites the CSV the postcheck owns.
    check("D3 manual_todo_problems writes no MANUAL_TODO.csv",
          not (pkg / "MANUAL_TODO.csv").exists())

    # A clean split passes.
    pkg2 = root / "revised2"
    pkg2.mkdir()
    (pkg2 / "README-AUTHOR-TO-COMPLETE.md").write_text(
        _table(["T-001", "T-002"], "readme"), encoding="utf-8")
    (pkg2 / "MANUAL_STEPS.md").write_text(
        "Long-form detail for T-001 and T-002; no second table here.\n", encoding="utf-8")
    errs2, _w2 = pp.manual_todo_problems(pkg2)
    check("D3 one table plus prose detail passes", not errs2, str(errs2)[:200])


def test_d3b_prompt_contract() -> None:
    print("\n== D3b: the prompt and skill state the one-id-space contract ==")
    rule = " ".join(pp.placeholder_rule_text("readme").split())
    check("D3b the readme mode names the README as the manual list",
          "record it in ONE file in the package root, `README-AUTHOR-TO-COMPLETE.md`" in rule)
    check("D3b the readme mode forbids a second table beside it",
          "must NOT repeat the table and must NOT reuse a `T-` id" in rule)
    check("D3b the shared rule states the one-id-space contract",
          "ONE ID SPACE ACROSS BOTH FILES" in rule
          and "may appear in at most ONE of the two files" in rule)

    P = Path("/tmp/x")
    revise = pp.revise_prompt(P, "r1_a2_revise", 1)
    # The old excerpt says "report them in ...", not "record them in ...": the
    # check pinned a string that never existed, so deleting the rewrite row
    # would not have failed it (the 2026-11-02 verify pass's F53).
    check("D3b the revise prompt's item 5 no longer sends items to MANUAL_STEPS.md "
          "as the manual list", "report them in revised/MANUAL_STEPS.md" not in revise)
    check("D3b the revise prompt's item 5 names the README's classified table",
          "README-AUTHOR-TO-COMPLETE.md" in revise
          and "classified TODO table" in revise)
    check("D3b the revise prompt carries the one-row/one-file rule",
          "TODO item ID" in revise and "ONE ID SPACE" in revise)

    skill = (WS / "paper-skills" / "paper-revise" / "SKILL.md").read_text(encoding="utf-8")
    check("D3b the revise skill states the shared id space",
          "share ONE id space" in skill or "ONE id space" in skill)


# ---------------------------------------------------------------------------
# D4 -- the M30 ledger is judged wherever the reviser wrote it.
# ---------------------------------------------------------------------------
M30_HEADER = (
    "# M30 — source-hierarchy reconciliation\n\n"
    "| # | document | kind | number | unit | sentence | candidate producer | producer summary "
    "| seed check | disposition |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n")


def _m30_row(n: int, disposition: str) -> str:
    return (f"| {n} | paper.md | body | {n} | cm | the height is {n} | "
            f"raw_data/plot.csv:height | 3 values | read the column | {disposition} |\n")


def test_d3c_preflight_todo_for_every_package_stage() -> None:
    print("\n== D3c: the duplicated-id rejection reaches rewrite/integrate pre-flights ==")
    # `add_stage_quality_checks` runs the TODO gate for ALL THREE package kinds,
    # so the pre-flight must too; it ran only for revise in the first cut.
    for kind, pkg_name in (("rewrite", "rewritten"), ("integrate", "integrated")):
        root = scratch(f"d3c_{kind}_")
        sb = root / "sb"
        pkg = sb / pkg_name
        pkg.mkdir(parents=True)
        (pkg / "MANUAL_STEPS.md").write_text(_table(["T-001"], "m"), encoding="utf-8")
        (pkg / "README-AUTHOR-TO-COMPLETE.md").write_text(
            _table(["T-001"], "r"), encoding="utf-8")
        errs, _w = pp.manual_todo_problems(pkg)
        check(f"D3c a duplicate id in the {pkg_name}/ package is an error",
              any("duplicate TODO item ID" in e for e in errs), str(errs)[:160])
        _ok, serrs, _sw = pp.sandbox_selfcheck(sb, kind, f"r1_{kind}", 1)
        check(f"D3c the {kind} pre-flight reports that duplicate",
              any("duplicate TODO item ID" in e for e in serrs), str(serrs)[:200])


def test_d4_m30_location() -> None:
    print("\n== D4: the M30 ledger is read from the copy the reviser disposed ==")
    frozen = [{"id": "F-900", "check": "M30"}]
    root = scratch("d4_")

    # (a) the 2026-11-01 shape: seed EMPTY in work/, disposed in revised/work/
    sb = root / "a"
    (sb / "work").mkdir(parents=True)
    (sb / "revised" / "work").mkdir(parents=True)
    (sb / "work" / "M30_hierarchy_reconciliation.md").write_text(
        M30_HEADER + _m30_row(1, "") + _m30_row(2, ""), encoding="utf-8")
    (sb / "revised" / "work" / "M30_hierarchy_reconciliation.md").write_text(
        M30_HEADER + _m30_row(1, "OK — matches raw_data/plot.csv") + _m30_row(2, "OK — same"),
        encoding="utf-8")
    errs, warns = pp.m30_hierarchy_problems(sb, frozen, pkg="revised")
    check("D4 a disposed package copy passes", not errs, f"{errs} {warns}")
    check("D4 ... and the record names the copy it judged",
          any("revised/work/M30_hierarchy_reconciliation.md was judged" in w for w in warns),
          f"{warns}")

    # (b) the reverse: disposed in place, no package copy
    sb = root / "b"
    (sb / "work").mkdir(parents=True)
    (sb / "work" / "M30_hierarchy_reconciliation.md").write_text(
        M30_HEADER + _m30_row(1, "OK — matches"), encoding="utf-8")
    errs, _w = pp.m30_hierarchy_problems(sb, frozen, pkg="revised")
    check("D4 a disposed sandbox copy passes", not errs, str(errs)[:160])

    # (c) nothing disposed anywhere still fails, with a message an operator can read
    sb = root / "c"
    (sb / "work").mkdir(parents=True)
    (sb / "work" / "M30_hierarchy_reconciliation.md").write_text(
        M30_HEADER + _m30_row(1, "") + _m30_row(2, ""), encoding="utf-8")
    errs, _w = pp.m30_hierarchy_problems(sb, frozen, pkg="revised")
    check("D4 an all-empty ledger fails", bool(errs), str(errs)[:160])
    msg = errs[0] if errs else ""
    check("D4 the message counts ROWS, not problems", "2 of 2 seeded row(s)" in msg, msg[:160])
    check("D4 the message has balanced parentheses", msg.count("(") == msg.count(")"), msg)
    check("D4 the message is not cut mid-word", " dispos)" not in msg and " dispos:" not in msg,
          msg)
    check("D4 the message names the dispositions the rows accept",
          "OK -- <the reconciling reason>" in msg, msg[:200])

    # (d) no ledger at all is a warning, not a failure
    sb = root / "d"
    (sb / "work").mkdir(parents=True)
    errs, warns = pp.m30_hierarchy_problems(sb, frozen, pkg="revised")
    check("D4 a missing ledger is a named warning", not errs and bool(warns),
          f"{errs} {warns}")
    check("D4 the missing-ledger warning names both copies",
          "revised/work/M30_hierarchy_reconciliation.md" in warns[0]
          and "work/M30_hierarchy_reconciliation.md" in warns[0], warns[0][:200])

    # (e) an EMPTY package copy must not hide an undisposed real seed: a file
    #     with nothing to report must never win just because it has no rows.
    sb = root / "e"
    (sb / "revised" / "work").mkdir(parents=True)
    (sb / "work").mkdir(parents=True)
    (sb / "revised" / "work" / "M30_hierarchy_reconciliation.md").write_text("", encoding="utf-8")
    (sb / "work" / "M30_hierarchy_reconciliation.md").write_text(
        M30_HEADER + _m30_row(1, "") + _m30_row(2, ""), encoding="utf-8")
    errs, _w = pp.m30_hierarchy_problems(sb, frozen, pkg="revised")
    check("D4 an empty package copy does not mask the undisposed seed", bool(errs),
          str(errs)[:160])
    check("D4 that error names the seed it judged",
          errs and "work/M30_hierarchy_reconciliation.md" in errs[0], str(errs)[:160])

    # (f) with no package name, the message must not invent a "/work/..." path
    sb = root / "f"
    (sb / "work").mkdir(parents=True)
    errs, warns = pp.m30_hierarchy_problems(sb, frozen, pkg="")
    check("D4 an unnamed package leaves no stray '/work/' path",
          not errs and warns and " nor /work/" not in warns[0], warns[0][:200])


def test_d4b_selfcheck_m30() -> None:
    print("\n== D4b: the revise pre-flight runs the M30 check ==")
    frozen = [{"id": "F-900", "check": "M30"}]
    root = scratch("d4b_")
    sb = root / "sb"
    (sb / "work").mkdir(parents=True)
    (sb / "revised").mkdir()
    (sb / "work" / "M30_hierarchy_reconciliation.md").write_text(
        M30_HEADER + _m30_row(1, ""), encoding="utf-8")
    errs, _w = pp.m30_hierarchy_problems(sb, frozen, pkg="revised")
    check("D4b an empty ledger is an ERROR the pre-flight can report", bool(errs),
          str(errs)[:120])
    check("D4b the empty-ledger error names the ledger path",
          "work/M30_hierarchy_reconciliation.md" in errs[0], errs[0][:120])


# ---------------------------------------------------------------------------
# D5 -- the round recap never cuts mid-word.
# ---------------------------------------------------------------------------
def test_d5_clip() -> None:
    print("\n== D5: the round recap cuts on a word boundary ==")
    msg = ("work/M30_hierarchy_reconciliation.md still carries 53 of 53 seeded row(s) with a "
           "candidate producer whose disposition cell is EMPTY: an M30 finding's fix must "
           "record the producer it reconciled against (rule E12).")
    clipped = pp.clip_error_line(msg, 200)
    check("D5 a long message is marked as cut", clipped.endswith("[...]"), clipped[-40:])
    check("D5 the cut lands on a word boundary",
          not clipped[:-6].rstrip().endswith(("dispo", "reconcil")), clipped[-40:])
    check("D5 a short message is untouched", pp.clip_error_line("short text", 200) == "short text")
    check("D5 internal whitespace is normalised",
          pp.clip_error_line("a\n\n b\tc", 200) == "a b c")


def test_d6_fallback_rule11() -> None:
    print("\n== D6: the fallback path never hands a session unfrozen code ==")
    # `state.json -> pipeline.path` is where setup was RUN FROM; for a normal root
    # that is the maintained checkout. Offering it to a session would run code
    # that may have drifted from the root's frozen bundle (AGENTS.md rule 11), so
    # the candidate is gated on the recorded bundle manifest.
    import json
    root = scratch("d6_")
    root.joinpath("paper_pipeline.py").write_text("# loader stub\n", encoding="utf-8")
    manifest = pp.module_manifest(WS)
    saved = pp.__file__
    try:
        pp.__file__ = str(root / "paper_pipeline.py")
        state = {"pipeline": {"path": str(WS / "paper_pipeline.py"), "modules": manifest}}
        (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
        check("D6 a byte-identical origin is offered",
              pp.pipeline_fallback_paths() == [str(WS / "paper_pipeline.py")],
              str(pp.pipeline_fallback_paths()))
        drifted = dict(manifest)
        drifted["paper_pipeline.py"] = "0" * 64
        (root / "state.json").write_text(
            json.dumps({"pipeline": {"path": str(WS / "paper_pipeline.py"),
                                     "modules": drifted}}), encoding="utf-8")
        check("D6 a drifted bundle is withheld", pp.pipeline_fallback_paths() == [],
              str(pp.pipeline_fallback_paths()))
        (root / "state.json").write_text(
            json.dumps({"pipeline": {"path": str(WS / "paper_pipeline.py")}}),
            encoding="utf-8")
        check("D6 no recorded manifest means no fallback", pp.pipeline_fallback_paths() == [])
        (root / "state.json").write_text(
            json.dumps({"pipeline": {"path": str(root / "paper_pipeline.py"),
                                     "modules": manifest}}), encoding="utf-8")
        check("D6 an in-place root offers no second path", pp.pipeline_fallback_paths() == [])
        (root / "state.json").write_text("{}", encoding="utf-8")
        check("D6 an unrecorded origin offers nothing", pp.pipeline_fallback_paths() == [])
    finally:
        pp.__file__ = saved


def cleanup() -> None:
    import shutil
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_d2_dispositions()
        test_d1_preflight_coverage()
        test_d1b_selfcheck_audit()
        test_d3_duplicate_ids()
        test_d3b_prompt_contract()
        test_d3c_preflight_todo_for_every_package_stage()
        test_d4_m30_location()
        test_d4b_selfcheck_m30()
        test_d5_clip()
        test_d6_fallback_rule11()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-11-01 BRIEF_COMMUNICATION INCIDENT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

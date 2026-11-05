#!/usr/bin/env python3
"""Regression checks for the failures in the 2026-11-04 paper-refine eval run.

Run:  python3 .paper_test/test_fix_bugs_20261105_eval.py

Each check pins one root cause read from the eval's `pipeline.log` files:

  * biology_journal: the revision audit failed with "the deletion audit is
    incomplete: DELETED_PARAGRAPHS.md no longer carries ... seeded paragraph
    row(s)" on an audit that kept every paragraph (twice, then the round
    failed);
  * biology_journal: the same run's revise was finally reported as "marker
    stage mismatch: expected 'revise', got 'revision_audit'", because the
    auxiliary audit session overwrote the revise attempt's completion marker;
  * linguistics_review: the bounded repair failed with "changed file(s) no
    CONFIRMED plan row covers: MANUAL_TODO.csv, README-AUTHOR-TO-COMPLETE.md"
    for the bookkeeping it is documented to update;
  * brief_communication: the same failure for `work/render/*`, which is stage
    scratch (`CORPUS_EXCLUDE_TOP`) re-rendered after the planned edit.

The suite is hermetic (temporary roots only).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FAILS = []
TMPDIRS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1105eval_pp", "paper_pipeline.py")

PROMPTS = WS / "paper_pipeline_parts" / "p03_prompts.py"


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


# A table-heavy paragraph: >1200 raw characters, one Markdown table with no
# blank line inside it (so the deletion audit sees the whole table as ONE
# paragraph), exactly like the Table 1 that tripped the eval.
TABLE_HEADER = ("| Stand | Region | Elevation (m) | Planted (open/closed) | "
                "Year-1 survival (open/closed) | Stand p | PPFD (mol m-2 d-1) |")
TABLE_ROWS = "\n".join(
    f"| S{i:02d} | coastal Finland | {100 + i} | {40 + i}/{38 + i} | "
    f"0.{50 + i % 40}/0.{30 + i % 30} | 0.{20 + i % 60} | {10 + i % 15}.4 |"
    for i in range(30))
TABLE_PARA = TABLE_HEADER + "\n| " + " | ".join(["---"] * 7) + " |\n" + TABLE_ROWS


def _table_package(tmp: Path):
    """base/ with the table paragraph, revised/ without it (the audit seed)."""
    base, revised = tmp / "base", tmp / "revised"
    base.mkdir()
    revised.mkdir()
    (base / "paper.md").write_text(
        "Intro paragraph that survives.\n\n" + TABLE_PARA + "\n\n"
        + "A second prose paragraph that was deleted and needs a disposition "
          "sentence naming where its facts survive.\n",
        encoding="utf-8")
    (revised / "paper.md").write_text("Intro paragraph that survives.\n",
                                      encoding="utf-8")
    return base, revised


def _fill_dispositions(markdown: str) -> str:
    """What an auditor does: keep every row, write only its last cell."""
    out = []
    for line in markdown.splitlines():
        if line.startswith("| ") and line.endswith(" |  |"):
            line = line[:-4] + " | OK — every fact survives in revised/paper.md |"
        out.append(line)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- A1
def test_a1_deletion_seed_roundtrip():
    print("\n== A1: a seeded paragraph survives verbatim; a dropped one still fails ==")
    tmp = scratch("evala1_")
    base, revised = _table_package(tmp)
    rows = pp.deletion_audit_rows(base, revised)
    check("the table paragraph is one seeded row", len(rows) >= 2, rows)
    seed = pp.deletion_audit_markdown(rows)
    # The identity form of the table paragraph must be reachable from the seed
    # row: this is the exact comparison the post-check performs.
    table_row = None
    for line in seed.splitlines():
        if line.startswith("| ") and "Stand" in line:
            table_row = line
    check("the table paragraph's seed row exists", table_row is not None)
    seeded_identity = pp._deletion_audit_identity(rows[0]["paragraph"])
    check("the seed row's cell is the identity form (truncate BEFORE escape)",
          seeded_identity.replace("|", "\\|") in (table_row or ""),
          (seeded_identity[:60], (table_row or "")[:80]))
    # The old code cut the ESCAPED cell at 1200 characters; a pipe-heavy
    # paragraph decoded to far fewer real characters and every table row this
    # agent kept verbatim was reported as a dropped seeded row.
    seed_path = _write(tmp, "audit_seed_only", seed) / "DELETED_PARAGRAPHS.md"
    seeded_rows = list(pp.parse_markdown_blocks(seed_path))[0]["rows"]
    table_cell = next(str(r.get("paragraph") or "") for r in seeded_rows
                      if "Stand" in str(r.get("paragraph") or ""))
    check("the seeded cell decodes to the full identity form",
          pp._deletion_audit_identity(table_cell) == seeded_identity,
          (len(pp._deletion_audit_identity(table_cell)), len(seeded_identity)))

    # The seeded row must still carry its disposition column: a truncation cut
    # inside `\|` used to leave a dangling backslash that escaped the cell
    # separator, swallowing the disposition cell of the row.
    widths = list(pp.parse_markdown_blocks(seed_path))[0]["widths"]
    check("every seeded row keeps the header's column count",
          len(set(widths)) == 1, widths)

    # A verbatim copy with every disposition filled must pass the identity
    # check. (The shared boilerplate check is separate and is given distinct
    # dispositions here.)
    audit = scratch("evala1_audit_")
    (audit / "revision_audit").mkdir()
    lines = []
    for i, line in enumerate(seed.splitlines()):
        if line.startswith("| ") and line.endswith(" |  |"):
            line = line[:-4] + f" | OK — row {i} is a duplicate; facts survive |"
        lines.append(line)
    (audit / "revision_audit" / "DELETED_PARAGRAPHS.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    probs = pp.deletion_audit_problems(
        audit, expected_rows=len(rows),
        expected_paragraphs=[r.get("paragraph") for r in rows], plan_ids=[])
    check("a verbatim audit with dispositions has no row problem",
          not any("no longer carries" in p for p in probs), probs[:2])

    # ...and the identity check still catches a short re-summary of the cell.
    lines = []
    for line in seed.splitlines():
        if line.startswith("| ") and "Stand" in line:
            prefix = line.split("|", 4)
            line = "|".join(prefix[:4]) + "| shortened summary of the table |" + \
                " OK — facts survive in revised/paper.md |"
        elif line.startswith("| ") and line.endswith(" |  |"):
            line = line[:-4] + " | OK — facts survive in revised/paper.md |"
        lines.append(line)
    (audit / "revision_audit" / "DELETED_PARAGRAPHS.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    probs = pp.deletion_audit_problems(
        audit, expected_rows=len(rows),
        expected_paragraphs=[r.get("paragraph") for r in rows], plan_ids=[])
    check("a replaced paragraph cell is still reported",
          any("no longer carries" in p for p in probs), probs[:2])


def test_a2_md_table_cell_never_splits_an_escape():
    print("\n== A2: a capped Markdown cell cannot end on a dangling escape ==")
    value = "x" * 5 + "|" + "y"
    escaped_after_cut = value.replace("|", "\\|")[:6]
    check("(the old order really did leave a lone backslash)",
          escaped_after_cut.endswith("\\") and not escaped_after_cut.endswith("\\|"),
          escaped_after_cut)
    cell = pp.md_table_cell(value, 6)
    check("the helper truncates before escaping", cell == "xxxxx\\|", repr(cell))
    check("the escaped cell never ends on a lone backslash",
          not (cell.endswith("\\") and not cell.endswith("\\|")), repr(cell))
    check("a newline cannot break the row", "\n" not in pp.md_table_cell("a\nb|c"))
    # Every seeded decision-artifact row keeps its column count even when the
    # evidence text is pipe-heavy and capped.
    table = pp._evidence_artifact_table(
        [{"rule": "FMT-1", "evidence": ("a|" * 100), "location": "x",
          "disposition": ""}],
        ["rule", "evidence", "location"], "none")
    p = scratch("evala2_") / "m20.md"
    p.write_text(table, encoding="utf-8")
    widths = list(pp.parse_markdown_blocks(p))[0]["widths"]
    check("a capped evidence cell keeps every row's column count",
          len(set(widths)) == 1, widths)


def _write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.mkdir(parents=True, exist_ok=True)
    (p / "DELETED_PARAGRAPHS.md").write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------- B1
def test_b1_repair_bookkeeping_and_scratch():
    print("\n== B1: bookkeeping/scratch changes are not unplanned manuscript edits ==")
    tmp = scratch("evalb1_")
    pre, cur = tmp / "pre", tmp / "cur"
    for d in (pre, cur):
        d.mkdir()
        (d / "paper.md").write_text("Intro A.\n", encoding="utf-8")
        (d / "work" / "render").mkdir(parents=True)
        (d / "work" / "render" / "paper.md").write_text("Intro A.\n", encoding="utf-8")
        (d / "MANUAL_TODO.csv").write_text("id\n", encoding="utf-8")
        (d / "README-AUTHOR-TO-COMPLETE.md").write_text("# T\n", encoding="utf-8")
    (cur / "paper.md").write_text("Intro B.\n", encoding="utf-8")
    (cur / "work" / "render" / "paper.md").write_text("Intro B.\n", encoding="utf-8")
    (cur / "work" / "render" / "paper.html").write_text("<p>B</p>\n", encoding="utf-8")
    (cur / "work" / "render" / "paper.pdf").write_bytes(b"%PDF-1.4 B\n")
    (cur / "MANUAL_TODO.csv").write_text("id\nT-005\n", encoding="utf-8")
    (cur / "README-AUTHOR-TO-COMPLETE.md").write_text("# T\nT-005 row\n",
                                                      encoding="utf-8")
    rows = [{"id": "RP-001", "file": "paper.md", "location": "l1",
             "wrong": "Intro A.", "correct": "Intro B.", "basis": "b",
             "edit": "e", "evidence": "x"}]
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-001", "verdict": "confirmed", "reason": "r",
         "before": "Intro A.", "after": "Intro B.", "files": ["revised/paper.md"]}]}),
        encoding="utf-8")
    bad = pp._revised_repair_violations(pre, cur, rows, {"RP-001"})
    check("rerendered scratch and derived bookkeeping pass", bad == [], bad)

    # A manuscript file outside the plan is still caught.
    (cur / "other.md").write_text("unplanned\n", encoding="utf-8")
    bad = pp._revised_repair_violations(pre, cur, rows, {"RP-001"})
    check("an unplanned manuscript edit is still caught", bad == ["other.md"], bad)
    (cur / "other.md").unlink()

    # A plan row that names bookkeeping is not span-bounded: its ledger quote
    # may be (as in the eval) a description of the row rather than a quote.
    rows2 = rows + [{"id": "RP-002", "file": "README-AUTHOR-TO-COMPLETE.md",
                     "location": "TODO table", "wrong": "no T-005 row",
                     "correct": "T-005 row added", "basis": "b", "edit": "e",
                     "evidence": "x"}]
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-001", "verdict": "confirmed", "reason": "r",
         "before": "Intro A.", "after": "Intro B.", "files": ["revised/paper.md"]},
        {"id": "RP-002", "verdict": "confirmed", "reason": "r",
         "before": "TODO rows T-001..T-004",
         "after": "TODO rows T-001..T-005 (described, not quoted)",
         "files": ["revised/README-AUTHOR-TO-COMPLETE.md"]}]}), encoding="utf-8")
    bad = pp._revised_repair_violations(pre, cur, rows2, {"RP-001", "RP-002"})
    check("a bookkeeping plan row with a descriptive quote passes", bad == [], bad)

    # A described manuscript row whose quote does not cover the change is
    # reported WITH the reason, so the operator is not sent looking for a
    # missing plan row that exists.
    (cur / "paper.md").write_text("Intro B. Plus an unquoted second edit.\n",
                                  encoding="utf-8")
    bad = pp._revised_repair_violations(pre, cur, rows, {"RP-001"})
    check("an unquoted manuscript change is reported", bad == ["paper.md"], bad)
    reasons = pp._revised_repair_violations(pre, cur, rows, {"RP-001"},
                                            with_reasons=True)
    check("the reported reason distinguishes a span problem",
          isinstance(reasons, dict) and "quoted" in (reasons.get("paper.md") or ""),
          reasons)


# ---------------------------------------------------------------- B2
def test_b2_repair_ledger_quote_forms():
    print("\n== B2: insertion and deletion quote forms are both accepted ==")
    tmp = scratch("evalb2_")
    sb = tmp / "sb"
    (sb / "revised").mkdir(parents=True)
    plan = [{"id": "RP-001", "file": "paper.md", "location": "l1", "wrong": "w",
             "correct": "c", "basis": "b", "edit": "e", "evidence": "x"}]

    def ledger(row):
        (sb / "revised" / "REPAIR_LEDGER.json").write_text(
            json.dumps({"rows": [row]}), encoding="utf-8")
        return pp._revision_repair_ledger(sb, plan, with_ids=True)

    problem, _counts, ids = ledger({"id": "RP-001", "verdict": "confirmed",
                                    "reason": "r", "before": "",
                                    "after": "added sentence"})
    check("a pure insertion (empty before, quoted after) is valid",
          problem == "" and ids == {"RP-001"}, problem)
    problem, _counts, ids = ledger({"id": "RP-001", "verdict": "confirmed",
                                    "reason": "r", "before": "removed sentence",
                                    "after": ""})
    check("a pure deletion (quoted before, empty after) is valid",
          problem == "" and ids == {"RP-001"}, problem)
    problem, _counts, _ids = ledger({"id": "RP-001", "verdict": "confirmed",
                                     "reason": "r", "before": "", "after": ""})
    check("a row with neither quote is still rejected", problem != "", problem)


# ---------------------------------------------------------------- C1
def test_c1_parent_marker_restored():
    print("\n== C1: an auxiliary session cannot relabel the parent's marker ==")
    tmp = scratch("evalc1_")
    sb = tmp
    parent = {"stage": "revise", "run_id": "r1_a2_revise", "round": 1,
              "status": "complete", "summary": {"findings_total": 3}}
    parent_bytes = json.dumps(parent, indent=2).encode("utf-8")
    (sb / pp.MARKER_FILE).write_bytes(parent_bytes)

    def fake_execute(sandbox, rec, cmd, timeout, prompt_file, log_name, archive):
        # The audit session's real behaviour: it writes its OWN marker last.
        (Path(sandbox) / pp.MARKER_FILE).write_text(json.dumps(
            {"stage": "revision_audit", "run_id": rec["id"], "round": 1,
             "status": "complete"}), encoding="utf-8")
        return {"rc": 0, "dur": 1.0, "error": "", "log": ""}

    original = pp._execute_attempt_in
    pp._execute_attempt_in = fake_execute
    try:
        rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1}
        pp._run_aux_session(sb, rec, ["/bin/true"], 5, "PROMPT.md", "_aux.log")
    finally:
        pp._execute_attempt_in = original
    check("the revise marker is restored byte-for-byte",
          (sb / pp.MARKER_FILE).read_bytes() == parent_bytes,
          (sb / pp.MARKER_FILE).read_text()[:120])
    check("the aux stage does not leak into the parent marker",
          "revision_audit" not in (sb / pp.MARKER_FILE).read_text())
    # With no parent marker, the aux marker must not linger as the stage's own.
    sb2 = tmp / "nomarker"
    sb2.mkdir()

    def fake_execute2(sandbox, rec, cmd, timeout, prompt_file, log_name, archive):
        (Path(sandbox) / pp.MARKER_FILE).write_text("{}", encoding="utf-8")
        return {"rc": 0, "dur": 1.0, "error": "", "log": ""}

    pp._execute_attempt_in = fake_execute2
    try:
        pp._run_aux_session(sb2, {"id": "x", "kind": "revise", "round": 1},
                            ["/bin/true"], 5, "PROMPT.md", "_aux.log")
    finally:
        pp._execute_attempt_in = original
    check("no parent marker -> no lingering aux marker",
          not (sb2 / pp.MARKER_FILE).exists())


# ---------------------------------------------------------------- P1
def test_p1_prompt_states_the_contract():
    print("\n== P1: the prompts state what the checks enforce ==")
    src = " ".join(PROMPTS.read_text(encoding="utf-8").split())
    check("the audit prompt says to keep the seeded identity cells",
          "keep them byte-identical" in src and "pipe escapes (`\\\\|`) included" in src)
    check("the repair prompt says before/after are verbatim quotes",
          "are QUOTES of the applied text, not a summary" in src)


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print(f"workspace: {WS}")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as e:                                    # noqa: BLE001
            check(f"{fn.__name__} raised {type(e).__name__}", False, str(e)[:300])
    cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s): {', '.join(FAILS[:8])}"
              + (" ..." if len(FAILS) > 8 else ""))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

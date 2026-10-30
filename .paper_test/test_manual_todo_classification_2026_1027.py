#!/usr/bin/env python3
"""The classified manual TODO inventory and its four-column CSV.

Run:  python3 .paper_test/test_manual_todo_classification_2026_1027.py

Every manual/hand-off item is one row in the package's classified TODO table
(TODO item ID | importance | author action | description).  The orchestrator
writes `MANUAL_TODO.csv` from that markdown table and publishes the sibling
`final_clean_version.manual_todo.csv`; the markdown remains the source, so a
prose-only item is not classified.

The action labels are exactly:
  CONFIRM/REJECT correction made by LLMs
  MANUALLY DO/DO_NOT correct with LLMs-recommended corrections provided
  MANUALLY DO/DO_NOT correct without any LLMs-recommended corrections
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
ACTIONS = (
    "CONFIRM/REJECT correction made by LLMs",
    "MANUALLY DO/DO_NOT correct with LLMs-recommended corrections provided",
    "MANUALLY DO/DO_NOT correct without any LLMs-recommended corrections",
)
FAILS: list[str] = []
TMPDIRS: list[Path] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def table(rows: str) -> str:
    return ("# MANUAL_STEPS\n\n## TODO list\n\n"
            "| TODO item ID | importance | author action | description |\n"
            "|---|---|---|---|\n" + rows)


def make_pkg(tmp: Path, name: str, md: str, readme: str = None) -> Path:
    pkg = tmp / name
    pkg.mkdir(parents=True)
    (pkg / "MANUAL_STEPS.md").write_text(md, encoding="utf-8")
    if readme is not None:
        (pkg / "README-AUTHOR-TO-COMPLETE.md").write_text(readme, encoding="utf-8")
    return pkg


def test_policy_text():
    print("\n== the prompt and skill policy ==")
    p02 = (WS / "paper_pipeline_parts" / "p02_journal_modes.py").read_text(encoding="utf-8")
    p03 = (WS / "paper_pipeline_parts" / "p03_prompts.py").read_text(encoding="utf-8")
    check("p02 defines the classified table and CSV",
          "MANUAL_TODO_RULE" in p02 and "MANUAL_TODO_COLUMNS" in p02
          and "MANUAL_TODO.csv" in p02)
    check("all four importances are named",
          all(x in p02 for x in ("fatal", "critical", "major", "minor")))
    check("all three author actions are named",
          all(a in p02 for a in ACTIONS))
    check("all three author-to-complete modes insert the table rule",
          p02.count("\n@@MANUAL_TODO_RULE@@\n") == 3)
    check("the audit/repair prompt names the classified table",
          "classif" in p03.lower() and "MANUAL_TODO.csv" in p03)
    check("the manual TODO CSV is bookkeeping",
          'manual_todo.csv' in p02.lower())
    for rel in ("paper-skills/paper-revise/references/edit_rules.md",
                "paper-skills/prompts/adress_issues.prompt.md",
                "paper-skills/paper-revise/SKILL.md",
                "README.md"):
        text = (WS / rel).read_text(encoding="utf-8")
        check(f"{rel}: carries the four-column table/CSV rule",
              "TODO item ID" in text and "MANUAL_TODO.csv" in text)
        check(f"{rel}: names every author action",
              all(a in text for a in ACTIONS))

    pp = load("manual_todo_prompts", WS / "paper_pipeline.py")
    P = Path("/tmp/x")
    prompts = {
        "review": pp.review_prompt(P, "r1_targeted_review", 1),
        "audit": pp.audit_prompt(P, "r1_audit", 1),
        "rewrite": pp.rewrite_prompt(P, "r1_w1", 1, index=1, total=2),
        "revise": pp.revise_prompt(P, "r1_a2_revise", 1),
        "integrate": pp.integrate_prompt(P, "r1_i1", 1, self_id="a1", other_ids=["w1"]),
    }
    for role, text in prompts.items():
        check(f"{role} prompt carries the table/CSV rule",
              "TODO item ID" in text and "MANUAL_TODO.csv" in text
              and all(a in text for a in ACTIONS))
        check(f"{role} prompt leaves no unresolved token", "@@" not in text)
    for mode in ("document", "readme", "off"):
        text = pp.placeholder_rule_text(mode)
        check(f"{mode} mode carries the table/CSV rule",
              "TODO item ID" in text and "MANUAL_TODO.csv" in text)
    check("the readme mode still does not name MANUAL_STEPS.md",
          "MANUAL_STEPS.md" not in pp.placeholder_rule_text("readme"))


def test_gate():
    print("\n== the package gate ==")
    pp = load("manual_todo_gate", WS / "paper_pipeline.py")
    tmp = scratch("manual_todo_")
    md = table(
        f"| T-001 | critical | {ACTIONS[0]} | Re-verify the corrected address. |\n"
        f"| T-002 | major | {ACTIONS[1]} | Check DOI 10.1000/x; suggested: 10.1000/y (unverified). |\n"
        f"| T-003 | minor | {ACTIONS[2]} | Obtain the accession from the author. |\n"
        f"| T-004 | minor | {ACTIONS[0]} | A note with a literal \\| pipe. |\n")
    pkg = make_pkg(tmp, "good", md)
    errs, warns = pp.manual_todo_gate(pkg)
    check("a valid classified table passes", not errs and not warns, f"{errs} {warns}")
    csvp = pkg / "MANUAL_TODO.csv"
    check("the four-column CSV is written", csvp.is_file())
    text = csvp.read_text(encoding="utf-8")
    lines = text.splitlines()
    check("the CSV header is exactly the four columns",
          lines[0] == "TODO item ID,importance,author_action,description", lines[0])
    check("the CSV carries every categorized value",
          all(v in text for v in ("T-001", "critical", ACTIONS[0], "T-004"))
          and "literal | pipe" in text, text)
    check("the markdown table carries the same information", all(
        v in md for v in ("T-001", "critical", ACTIONS[0], "T-004")))

    bad = make_pkg(tmp, "bad", table(
        "| T-001 | huge | do it somehow | x |\n"))
    errs, _ = pp.manual_todo_gate(bad)
    check("a bad importance/action is a hard table error", bool(errs), str(errs))

    duplicate = make_pkg(tmp, "duplicate", table(
        f"| T-001 | minor | {ACTIONS[0]} | one |\n"
        f"| T-001 | major | {ACTIONS[0]} | two |\n"))
    errs, _ = pp.manual_todo_gate(duplicate)
    check("a duplicate TODO item ID is a table error", bool(errs), str(errs))

    legacy = make_pkg(tmp, "legacy",
                      "# MANUAL_STEPS\n\n- Verify the accession number.\n")
    errs, warns = pp.manual_todo_gate(legacy)
    check("a legacy prose-only list gets a NAMED warning, not a fake CSV",
          not errs and any("no classified" in w for w in warns)
          and not (legacy / "MANUAL_TODO.csv").exists(), f"{errs} {warns}")

    csv_only = tmp / "csv_only"
    csv_only.mkdir()
    (csv_only / "MANUAL_TODO.csv").write_text(
        "TODO item ID,importance,author_action,description\n", encoding="utf-8")
    errs, warns = pp.manual_todo_gate(csv_only)
    check("a CSV with no manual-list markdown is removed, not shipped",
          not errs and not (csv_only / "MANUAL_TODO.csv").exists()
          and any("no manual-list markdown" in w for w in warns), f"{errs} {warns}")

    legacy_csv = make_pkg(tmp, "legacy_csv",
                          "# MANUAL_STEPS\n\n- Verify the accession number.\n")
    (legacy_csv / "MANUAL_TODO.csv").write_text(
        "TODO item ID,importance,author_action,description\n", encoding="utf-8")
    errs, warns = pp.manual_todo_gate(legacy_csv)
    check("a CSV without a classified table is removed with a named warning",
          not errs and not (legacy_csv / "MANUAL_TODO.csv").exists()
          and any("no classified" in w for w in warns), f"{errs} {warns}")

    header_only = make_pkg(tmp, "header_only", table(""))
    errs, warns = pp.manual_todo_gate(header_only)
    csv_text = (header_only / "MANUAL_TODO.csv").read_text(encoding="utf-8")
    check("an empty classified table writes a header-only CSV",
          not errs and not warns and csv_text.strip()
          == "TODO item ID,importance,author_action,description", f"{errs} {warns}")

    readme = ("# README-AUTHOR-TO-COMPLETE\n\n"
              "| TODO item ID | importance | author action | description |\n"
              "|---|---|---|---|\n"
              f"| T-002 | minor | {ACTIONS[2]} | README item. |\n")
    merged = make_pkg(tmp, "merged", table(
        f"| T-001 | minor | {ACTIONS[0]} | MANUAL item. |\n"), readme)
    errs, warns = pp.manual_todo_gate(merged)
    csv_text = (merged / "MANUAL_TODO.csv").read_text(encoding="utf-8")
    check("tables in the manual list and the hand-off README are merged",
          not errs and not warns and "T-001" in csv_text and "T-002" in csv_text,
          f"{errs} {warns}")

    mismatch = make_pkg(tmp, "mismatch", table(
        f"| T-001 | minor | {ACTIONS[0]} | MANUAL item. |\n"))
    (mismatch / "MANUAL_TODO.csv").write_text("old,table\n", encoding="utf-8")
    errs, warns = pp.manual_todo_gate(mismatch)
    check("a stale CSV is regenerated from the markdown with a warning",
          not errs and any("regenerated" in w for w in warns)
          and "T-001" in (mismatch / "MANUAL_TODO.csv").read_text(encoding="utf-8"),
          f"{errs} {warns}")

    short = make_pkg(tmp, "short", table(
        f"| T-001 | minor | {ACTIONS[0]} | only three? |\n"))
    # A raw pipe in the description makes 5 cells; the table is malformed.
    (short / "MANUAL_STEPS.md").write_text(
        table(f"| T-001 | minor | {ACTIONS[0]} | x | y |\n"), encoding="utf-8")
    errs, _ = pp.manual_todo_gate(short)
    check("an unescaped pipe in a description is a table error", bool(errs), str(errs))


def test_publication_sibling():
    print("\n== the published sibling CSV ==")
    pp = load("manual_todo_publish", WS / "paper_pipeline.py")
    tmp = scratch("manual_todo_pub_")
    ctx = type("C", (), {"root": tmp})()
    body = table(
        f"| T-001 | critical | {ACTIONS[0]} | Re-verify the address. |\n"
        f"| T-002 | major | {ACTIONS[1]} | Check the DOI. |\n")
    info = {"run": "r1_a2_revise", "kind": "revise", "items": [], "discarded": [],
            "manual_steps_text": body, "manual_steps_items": 2}
    out = pp.write_open_items_sibling(ctx, info)
    steps = tmp / pp.FINAL_CLEAN_STEPS_NAME
    csvp = tmp / pp.FINAL_CLEAN_TODO_CSV_NAME
    check("the published manual list is still written",
          steps.is_file() and out.get("path"), out)
    check("the published CSV sibling is written from the table",
          csvp.is_file() and (out.get("todo_csv") or "").endswith(
              pp.FINAL_CLEAN_TODO_CSV_NAME), out)
    if csvp.is_file():
        text = csvp.read_text(encoding="utf-8")
        check("the published CSV is the same four columns",
              text.splitlines()[0]
              == "TODO item ID,importance,author_action,description", text)

    empty_ctx = type("C", (), {"root": scratch("manual_todo_pub_empty_")})()
    stale = empty_ctx.root / pp.FINAL_CLEAN_TODO_CSV_NAME
    stale.write_text("stale\n", encoding="utf-8")
    pp.write_open_items_sibling(empty_ctx, {"items": [], "manual_steps_text": ""})
    check("no items removes a stale published CSV sibling", not stale.exists())

    # readme mode: the package CSV is the only list (no MANUAL_STEPS.md body).
    csv_ctx = type("C", (), {"root": scratch("manual_todo_pub_csv_")})()
    (csv_ctx.root / "runs").mkdir()
    (csv_ctx.root / "runs" / "MANUAL_TODO.csv").write_text(
        "TODO item ID,importance,author_action,description\n"
        f"T-009,critical,{ACTIONS[0]},From the hand-off README.\n",
        encoding="utf-8")
    out2 = pp.write_open_items_sibling(csv_ctx, {
        "items": [], "manual_steps_text": "",
        "manual_todo_csv": "runs/MANUAL_TODO.csv"})
    steps2 = csv_ctx.root / pp.FINAL_CLEAN_STEPS_NAME
    check("a package CSV alone still publishes the markdown table and CSV",
          out2.get("items") == 1
          and "T-009" in steps2.read_text(encoding="utf-8")
          and (csv_ctx.root / pp.FINAL_CLEAN_TODO_CSV_NAME).is_file(), out2)


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_policy_text()
        test_gate()
        test_publication_sibling()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL MANUAL-TODO CLASSIFICATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

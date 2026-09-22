#!/usr/bin/env python3
"""Stub agent for the scoped ARTIFACT-REPAIR tests (`--strict-artifacts fix`).

The pipeline runs a repair session with the SAME `--agent-cmd` as a stage, so
this wrapper decides from the prompt what it is:

  * a REPAIR prompt (`ARTIFACT REPAIR — SCOPED SESSION`): repair ONE bookkeeping
    file of the failed stage, the way that stage's profile allows -- review fills
    the decision tables' judged cells; audit adds the missing `confirm`
    dispositions; rewrite writes the missing REWRITE_REPORT.md; revise completes
    the revision ledger; integrate writes the missing donor ledger; judge adds the
    `unable` coverage entries its sheet is missing -- and touches nothing else.
    Variants, all driven by the environment:
      NBT_REPAIR_STUB_NOFIX=1  change nothing (the repair does not clear the
                               problem: the attempt must fail like any other)
      NBT_REPAIR_STUB_EVIL=1   ALSO edit a file outside that stage's scope
                               (`review/findings.json`, or a manuscript document
                               inside the package): the guard must reject it
      NBT_REPAIR_STUB_DROP=1   delete the last seeded row of a DECISION table
                               instead of filling it (the guard must reject a
                               table "fixed" by removing what it had to dispose)
      NBT_REPAIR_STUB_DROP_OTHER=1
                               rewrite a row of an artifact that is NOT one of
                               the cell-editable decision tables (its bytes must
                               stay identical)
  * any other prompt: delegate to `stub_agent.py`, i.e. a complete stage
    deliverable, and then -- when NBT_REPAIR_STUB_BAD matches this run id --
    BREAK that stage's own bookkeeping (blank the review's judged cells, drop two
    audit dispositions, delete the rewrite report, drop a revision-ledger row,
    delete the integration ledger, or strip a judge comparison's `checks` map).
    Those are the failures the repair mode exists for.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("stub_agent", HERE / "stub_agent.py")
stub = importlib.util.module_from_spec(spec)
sys.modules["stub_agent"] = stub
spec.loader.exec_module(stub)

BLANK_COLUMNS = ("disposition", "resolution", "summary")
# The check ids a judge's `checks` map must cover (the pipeline's frozen set).
JUDGE_CHECKS = tuple(f"M{i}" for i in range(1, 18)) + ("M18", "M19", "M20", "M21", "M22", "M23",
                                                       "M24") + tuple(f"J{i}" for i in range(1, 5))
# The decision tables whose cells the artifact-quality layer judges: the ones the
# repair may edit, and the only ones this stub's "unfilled review" touches. The
# OTHER artifact files (`M1_acronyms.md`, `IDENTIFIERS.md`, the M2-M17 tables)
# are read by later stages and must stay byte-identical.
DECISION_TABLES = ("M20_formatting.md", "M18_caption_words.md", "M19_length.md", "M8_terms.md",
                   "M24_concepts.md", "GLOSSARY.md", "PLACEHOLDERS.md", "PLACEHOLDER_LOOKUP.md",
                   "OUTLINE.md")


def stage_of(name: str) -> str:
    """The stage a sandbox belongs to ('' when it is not a stage sandbox)."""
    if name.endswith("_review"):
        return "review"
    if name.endswith("_audit"):
        return "audit"
    if re.search(r"_w\d+$", name):
        return "rewrite"
    if re.search(r"_a\d+_revise$", name):
        return "revise"
    if re.search(r"_i\d+$", name):
        return "integrate"
    if "_judge_" in name or name.startswith("judge_"):
        return "judge"
    return ""


def package_dir(sb: Path, stage: str) -> Path:
    return sb / {"rewrite": "rewritten", "revise": "revised",
                 "integrate": "integrated"}.get(stage, "")


def decision_tables(sb: Path):
    art = sb / "review" / "artifacts"
    if not art.is_dir():
        return []
    return [art / name for name in DECISION_TABLES if (art / name).is_file()]


def fill_decision_tables(sb: Path) -> None:
    """`stub_agent.fill_seeded_tables`, restricted to the decision tables."""
    art = sb / "review" / "artifacts"
    if not art.is_dir():
        return
    untouched = {p: p.read_bytes() for p in sorted(art.glob("*.md"))
                 if p.name not in DECISION_TABLES}
    stub.fill_seeded_tables(art)
    for path, data in untouched.items():
        path.write_bytes(data)


def rewrite_cells(path: Path, *, blank: bool, drop_row: bool = False) -> None:
    """Blank the judged cells of one table (or drop its last data row)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    head_i = next((i for i, l in enumerate(lines) if l.strip().startswith("|")), None)
    if head_i is None:
        return
    header = [c.lower() for c in stub.table_cells(lines[head_i])]
    data = [i for i in range(head_i + 1, len(lines)) if lines[i].strip().startswith("|")
            and not all("-" in c and set(c) <= set("-: ")
                        for c in stub.table_cells(lines[i]))]
    if drop_row and data:
        del lines[data[-1]]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    for i in data:
        cells = stub.table_cells(lines[i])
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        for k, key in enumerate(header):
            if k < len(cells) and key in BLANK_COLUMNS:
                cells[k] = ""
        lines[i] = "| " + " | ".join(cells) + " |"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# breaking a stage's bookkeeping (the failure the repair mode exists for)
# ---------------------------------------------------------------------------
def break_stage(sb: Path, stage: str) -> str:
    """Break ONE bookkeeping file of `stage`; return a note for the log."""
    if stage == "review":
        for table in decision_tables(sb):
            rewrite_cells(table, blank=True)
        return f"left {len(decision_tables(sb))} decision table(s) unfilled"
    if stage == "audit":
        p = sb / "audit" / "audit.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        rows = data.get("dispositions") or []
        # Drop at least one disposition (the stub's frozen review can be tiny).
        data["dispositions"] = rows[:-1] if len(rows) > 1 else []
        p.write_text(json.dumps(data), encoding="utf-8")
        return f"dropped {len(rows) - len(data['dispositions'])} audit disposition(s)"
    if stage == "rewrite":
        rep = package_dir(sb, stage) / "REWRITE_REPORT.md"
        if rep.is_file():
            rep.unlink()
        return "deleted rewritten/REWRITE_REPORT.md"
    if stage == "revise":
        p = package_dir(sb, stage) / "revision_report.json"
        rows = json.loads(p.read_text(encoding="utf-8"))
        rows = rows if isinstance(rows, list) else (rows or {}).get("rows") or []
        rows = rows[:-1] if len(rows) > 1 else []
        p.write_text(json.dumps(rows), encoding="utf-8")
        return "dropped one revision-ledger row"
    if stage == "integrate":
        led = package_dir(sb, stage) / "DIFF_LEDGER.md"
        if led.is_file():
            led.unlink()
        return "deleted integrated/DIFF_LEDGER.md"
    if stage == "judge":
        p = sb / "scores.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        comps = data.get("comparisons") or []
        if comps:
            comps[0].pop("checks", None)
        p.write_text(json.dumps(data), encoding="utf-8")
        return "stripped the `checks` map from one judge comparison"
    return ""


# ---------------------------------------------------------------------------
# repairing a stage's bookkeeping (only what that stage's profile allows)
# ---------------------------------------------------------------------------
def frozen_findings(sb: Path) -> list:
    """The frozen review's finding rows (audit/revise repairs read these)."""
    p = sb / "review" / "findings.json"
    if not p.is_file():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = doc.get("findings") if isinstance(doc, dict) else doc
    return [f for f in (found or []) if isinstance(f, dict) and f.get("id")]


def repair_audit(sb: Path) -> str:
    """Add the missing dispositions -- `confirm` only, from the frozen review."""
    p = sb / "audit" / "audit.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    rows = data.get("dispositions") if isinstance(data.get("dispositions"), list) else []
    seen = {str((r or {}).get("id") or "").strip() for r in rows}
    added = 0
    for f in frozen_findings(sb):
        fid = str(f["id"])
        if fid in seen:
            continue
        rows.append({"id": fid, "verdict": "confirm",
                     "reason": f"repair: the frozen review carries {fid} at "
                               f"{str(f.get('location') or 'its location')[:60]}; a finding with "
                               f"no disposition is confirmed, never dropped",
                     "evidence": str(f.get("evidence") or "(the finding's own row)")[:200],
                     "severity_after": str(f.get("severity") or "Minor")})
        added += 1
    data["dispositions"] = rows
    data.setdefault("adds", [])
    p.write_text(json.dumps(data), encoding="utf-8")
    return f"confirmed {added} previously undisposed finding id(s)"


def repair_rewrite(sb: Path, name: str) -> str:
    """Write the missing REWRITE_REPORT.md from what the package shows."""
    pkg = package_dir(sb, "rewrite")
    docs = sorted(d.name for d in pkg.glob("*") if d.is_file()) if pkg.is_dir() else []
    level = "structural" if re.search(r"_w1$", name) else "sentence"
    (pkg / "REWRITE_REPORT.md").write_text(
        "# rewrite report (repaired by the scoped session)\n\n"
        f"Level: {level}\n\n"
        "## Organization map\n\n"
        + ("\n".join(f"- `{d}` -- carried over unchanged by the rewrite session; the repair "
                     f"session did not re-organize it" for d in docs) or "- (empty package)")
        + "\n\n## Deliberately unchanged\n\n"
          "- the scientific content: the repair session may not edit the package, so every claim, "
          "number and citation stands as the rewrite session delivered it\n\n"
          "## Problems surfaced\n\n"
          "- unable — manual verification required: the rewrite session did not record the "
          "problems it surfaced, and a repair session cannot invent them; the author must check "
          "the package against the review\n",
        encoding="utf-8")
    return "wrote rewritten/REWRITE_REPORT.md (level + the package's own file list)"


def repair_revise(sb: Path) -> str:
    """Name every frozen id in the revision ledger; the repair may not judge it."""
    p = package_dir(sb, "revise") / "revision_report.json"
    try:
        rows = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
    except (OSError, ValueError):
        rows = []
    if isinstance(rows, dict):
        rows = rows.get("rows") or []
    if not isinstance(rows, list):
        rows = []
    have = {str((r or {}).get("id") or "") for r in rows if isinstance(r, dict)}
    added = 0
    for f in frozen_findings(sb):
        fid = str(f["id"])
        if fid in have:
            continue
        rows.append({"id": fid, "verdict": "unable",
                     "rationale": "unable — manual verification required: the repair session may "
                                  "not judge whether the package fixed this finding, and the "
                                  "revision session's own row is missing",
                     "evidence": f"frozen review: {str(f.get('location') or '')[:60]}"})
        added += 1
    p.write_text(json.dumps(rows), encoding="utf-8")
    return f"named {added} previously missing finding id(s) in the revision ledger"


def repair_integrate(sb: Path) -> str:
    """Write the donor ledger: one explicit no-difference row per donor."""
    pkg = package_dir(sb, "integrate")
    donors = sorted(d.name for d in (sb / "others").iterdir() if d.is_dir()) \
        if (sb / "others").is_dir() else []
    rows = []
    for i, donor in enumerate(donors, 1):
        rows.append(f"| R-{i:03d} | {donor} | (whole package) | small | (not read by the repair) "
                    f"| self wording | keep-self | the repair session may not read a donor's "
                    f"judgement | no ported difference | self/(unchanged) | none |")
    (pkg / "DIFF_LEDGER.md").write_text(
        "# diff ledger (repaired by the scoped session)\n\n"
        "Every donor of this run's pool gets one explicit row. The repair session may not port a "
        "difference (that would edit the package), so each row records that the donors were left "
        "unread by this session and the self package stands.\n\n"
        "| id | donor | location | size | donor says | self says | verdict | why | effect | "
        "artifact | finding effect |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        + ("\n".join(rows) if rows else "| R-000 | (no donor) | - | small | - | - | keep-self | "
                                        "`others/` carries no donor | none | self/(unchanged) | none |")
        + "\n", encoding="utf-8")
    return f"wrote integrated/DIFF_LEDGER.md with {len(rows)} donor row(s)"


def repair_judge(sb: Path) -> str:
    """Add the `unable` coverage entries a sheet is missing (never a judgement)."""
    p = sb / "scores.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    added = 0
    for comp in data.get("comparisons") or []:
        checks = comp.get("checks")
        if not isinstance(checks, dict) or not checks:
            checks = comp["checks"] = {}
        for cid in JUDGE_CHECKS:
            if cid not in checks:
                checks[cid] = ("unable — added by the scoped repair session: this comparison "
                               "carries no disposition for it, and a repair may not judge")
                added += 1
    p.write_text(json.dumps(data), encoding="utf-8")
    return f"added {added} `unable` coverage entry/entries to scores.json"


def do_repair(sb: Path, name: str) -> str:
    """Run the repair the stage's profile allows; return a note."""
    stage = stage_of(name)
    if stage == "review":
        fill_decision_tables(sb)
        return "filled the seeded decision tables"
    if stage == "audit":
        return repair_audit(sb)
    if stage == "rewrite":
        return repair_rewrite(sb, name)
    if stage == "revise":
        return repair_revise(sb)
    if stage == "integrate":
        return repair_integrate(sb)
    if stage == "judge":
        return repair_judge(sb)
    return "no repair profile for this sandbox"


def go_out_of_scope(sb: Path, name: str) -> str:
    """Touch a file the stage's profile protects (the guard must reject it)."""
    stage = stage_of(name)
    if stage == "review":
        fj = sb / "review" / "findings.json"
        data = json.loads(fj.read_text(encoding="utf-8"))
        data.setdefault("findings", []).append({"id": "F-999"})
        fj.write_text(json.dumps(data), encoding="utf-8")
        return "edited review/findings.json"
    pkg = package_dir(sb, stage)
    # A MANUSCRIPT file: the stage's bookkeeping reports and its work/ scratch are
    # legitimately writable, so pick a file that is neither.
    bookkeeping = {"changelog.md", "manual_steps.md", "revision_report.md",
                   "revision_report.json", "diff_ledger.md", "rewrite_report.md",
                   "visual_check.md"}
    docs = [d for d in sorted(pkg.rglob("*"))
            if d.is_file() and d.name.lower() not in bookkeeping
            and "work" not in d.relative_to(pkg).parts] if pkg.is_dir() else []
    target = docs[0] if docs else (pkg / "manuscript-b.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(target.read_text(encoding="utf-8", errors="replace") + "\nedited\n",
                      encoding="utf-8")
    return f"edited the package file {target.relative_to(sb)}"


def main() -> int:
    sb = Path.cwd()
    name = sb.name
    prompt = sys.stdin.read()
    if "ARTIFACT REPAIR" in prompt[:2000]:
        stage = stage_of(name)
        # The review-only structural fixtures (they prove the guard's row rules)
        # stay available for every stage that owns a decision table.
        if os.environ.get("NBT_REPAIR_STUB_DROP"):
            tables = [t for t in decision_tables(sb)
                      if t.name in ("OUTLINE.md", "M20_formatting.md")] or decision_tables(sb)
            if tables:
                rewrite_cells(tables[0], blank=False, drop_row=True)
            return 0
        if os.environ.get("NBT_REPAIR_STUB_DROP_OTHER"):
            other = sb / "review" / "artifacts" / "M1_acronyms.md"
            if other.is_file():
                lines = other.read_text(encoding="utf-8").splitlines()
                # Rewrite a row's content in place: bytes change, no cell is filled.
                for i, line in enumerate(lines):
                    if line.strip().startswith("|") and "acronym" not in line.lower():
                        lines[i] = line.rstrip(" |") + " | edited by the repair |"
                        break
                other.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return 0
        note = "left the bookkeeping alone (NBT_REPAIR_STUB_NOFIX)"
        if not os.environ.get("NBT_REPAIR_STUB_NOFIX"):
            note = do_repair(sb, name)
        if os.environ.get("NBT_REPAIR_STUB_EVIL"):
            note += "; " + go_out_of_scope(sb, name)
        print(f"stub repair ({stage or 'unknown stage'}): {note}")
        return 0
    rc = stub.main()
    bad = os.environ.get("NBT_REPAIR_STUB_BAD") or ""
    if bad and bad in name:
        note = break_stage(sb, stage_of(name))
        print(f"stub: broke the {stage_of(name) or 'unknown'} bookkeeping: {note}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())

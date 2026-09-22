#!/usr/bin/env python3
"""Stub agent for the scoped ARTIFACT-REPAIR tests (`--strict-artifacts fix`).

The pipeline runs a repair session with the SAME `--agent-cmd` as a stage, so
this wrapper decides from the prompt what it is:

  * a REPAIR prompt (`ARTIFACT REPAIR — SCOPED SESSION`): fill the decision tables
    the way the mode allows -- `stub_agent.fill_seeded_tables()` writes a
    row-specific reason per row and a generated (non-echo) summary -- and touch
    nothing else. Variants, all driven by the environment:
      NBT_REPAIR_STUB_NOFIX=1  leave the tables alone (the repair does not clear
                               the problem: the attempt must fail like any other)
      NBT_REPAIR_STUB_EVIL=1   ALSO rewrite review/findings.json (out of scope:
                               the orchestrator's guard must reject the repair)
      NBT_REPAIR_STUB_DROP=1   delete the last seeded row of a DECISION table
                               instead of filling it (the guard must reject a
                               table "fixed" by removing what it had to dispose)
      NBT_REPAIR_STUB_DROP_OTHER=1
                               rewrite a row of an artifact that is NOT one of
                               the cell-editable decision tables (its bytes must
                               stay identical)
  * any other prompt: delegate to `stub_agent.py`, i.e. a complete stage
    deliverable, and then -- when NBT_REPAIR_STUB_BAD matches this run id --
    BLANK the cells the artifact-quality layer judges (disposition/resolution
    and OUTLINE `summary`). That is the unfilled artifact the mode exists for.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("stub_agent", HERE / "stub_agent.py")
stub = importlib.util.module_from_spec(spec)
sys.modules["stub_agent"] = stub
spec.loader.exec_module(stub)

BLANK_COLUMNS = ("disposition", "resolution", "summary")
# The decision tables whose cells the artifact-quality layer judges: the ones the
# repair may edit, and the only ones this stub's "unfilled review" touches. The
# OTHER artifact files (`M1_acronyms.md`, `IDENTIFIERS.md`, the M2-M17 tables)
# are read by later stages and must stay byte-identical.
DECISION_TABLES = ("M20_formatting.md", "M18_caption_words.md", "M19_length.md", "M8_terms.md",
                   "M24_concepts.md", "GLOSSARY.md", "PLACEHOLDERS.md", "PLACEHOLDER_LOOKUP.md",
                   "OUTLINE.md")


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


def main() -> int:
    sb = Path.cwd()
    prompt = sys.stdin.read()
    if "ARTIFACT REPAIR" in prompt[:2000]:
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
        if not os.environ.get("NBT_REPAIR_STUB_NOFIX"):
            fill_decision_tables(sb)
        if os.environ.get("NBT_REPAIR_STUB_EVIL"):
            fj = sb / "review" / "findings.json"
            data = json.loads(fj.read_text(encoding="utf-8"))
            data.setdefault("findings", []).append(
                {"id": "F-999", "location": "base", "category": 0, "check": "M1",
                 "severity": "Minor", "evidence": "stub", "explanation": "stub",
                 "status": "resolvable"})
            fj.write_text(json.dumps(data), encoding="utf-8")
        print("stub repair: filled the seeded decision tables")
        return 0
    rc = stub.main()
    bad = os.environ.get("NBT_REPAIR_STUB_BAD") or ""
    if bad and bad in sb.name:
        for table in decision_tables(sb):
            rewrite_cells(table, blank=True)
        print(f"stub: left {len(decision_tables(sb))} decision table(s) unfilled", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())

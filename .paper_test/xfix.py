"""Shared fixture helpers for the suites (policy change 2026-09-22).

Three pipeline contracts changed and every suite that *simulates an agent's
output* now has to satisfy them:

  * the review's coverage table must dispose the adopted checks M21-M24 as well
    as M1-M20 and J1-J4;
  * every package-producing stage's output must carry its L1-L11 language-pass
    artifact (`work/R6_language.md`: one row per change plus one coverage row
    per step), because `--strict-artifacts` is ON by default;
  * the round plan contains the auditor by default, so a fixture that
    materializes a downstream session either stages the audit run too or runs
    with `audit: "off"` in its config.

Keeping the shapes here stops twenty suites from re-implementing them and from
silently drifting apart again.
"""
from __future__ import annotations

from pathlib import Path

CHECK_IDS = ([f"M{i}" for i in range(1, 18)]
             + ["M18", "M19", "M20", "M21", "M22", "M23", "M24"]
             + [f"J{i}" for i in range(1, 5)])

# Config for a fixture that does NOT stage the auditor (the pre-default plan).
AUDIT_OFF_CFG = {"audit": "off"}


def coverage_rows(detail: dict = None) -> list:
    """A complete review coverage table, one row per required check id."""
    detail = detail or {}
    return [{"check": cid, "disposition": detail.get(cid, "clean -- basis: fixture"),
             "detail": "fixture"} for cid in CHECK_IDS]


def write_language_pass(pkg, label: str = "fixture") -> None:
    """The L1-L11 artifact a package-producing stage owes (all 11 coverage rows)."""
    work = Path(pkg) / "work"
    work.mkdir(parents=True, exist_ok=True)
    lines = ["# language pass (fixture)", "",
             "| step | location | before | after | reason |", "|---|---|---|---|---|",
             f"| L9 | {label} | fixture: stiff | fixture: smoother | fixture row |", "",
             "| step | rows changed | note |", "|---|---|---|"]
    for i in range(1, 12):
        lines.append(f"| L{i} | {'1' if i == 9 else '0'} | fixture: no further change |")
    (work / "R6_language.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_language_pass_if_package(pkg) -> None:
    """Write the artifact only when the directory looks like a package root."""
    p = Path(pkg)
    if p.is_dir():
        write_language_pass(p)

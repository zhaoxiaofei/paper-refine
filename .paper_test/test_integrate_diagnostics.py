#!/usr/bin/env python3
"""The integration stage's rules and two reader/guard fixes.

Run:  python3 .paper_test/test_integrate_diagnostics.py

Pinned here:
  1. the integration prompt demands a FULL-CORPUS read of every donor and forbids
     diff-driven porting ("read self/ and EVERY others/<id>/ IN FULL YOURSELF ...
     do NOT rely on a shell `diff`"). An earlier experiment replaced that with a
     mechanically generated difference index; it was reverted (operator decision,
     2026-09-23) because the content context is what decides whether one version
     is better, and the index is no longer generated or used anywhere.
  2. the ledger READER took the FIRST table of DIFF_LEDGER.md. A session that
     opened the file with an orientation table (`| version | payload files | ... |`)
     had those four rows parsed AS the ledger and failed with "4 ledger row(s)
     carry no `artifact`" although its ledger was complete (`integration_ledger_rows`).
  3. the repair-scope guard counted `__pycache__/*.pyc` -- written by RUNNING the
     helper scripts the prompts tell the session to run -- as an out-of-scope edit
     and failed a repair that had cleared every problem it was given
     (`is_bytecode_cache`).
"""
from __future__ import annotations

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_integrate_diag", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_integrate_diag"] = nb
spec.loader.exec_module(nb)

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


# ---------------------------------------------------------------------------
# 1. the ledger reader picks the LEDGER table, not the session's summary table
# ---------------------------------------------------------------------------
def test_ledger_table_selection():
    print()
    print("== DIFF_LEDGER.md: the ledger is the table with the ledger's columns ==")
    out = scratch("paper_int_led_") / "integrated"
    (out / "work" / "diffs").mkdir(parents=True)
    (out / "work" / "diffs" / "L-001.md").write_text("before/after pair", encoding="utf-8")
    (out / "DIFF_LEDGER.md").write_text(
        "# DIFF_LEDGER\n\n"
        "## 0. State of the package (orientation)\n\n"
        "| version | payload files | differing | M20 rows |\n"
        "|---|---|---|---|\n"
        "| integrated/ | 29 | - | 68 |\n"
        "| others/a1/ | 38 | 7 | 127 |\n"
        "| others/w2/ | 30 | 7 | 119 |\n\n"
        "## 1. The ledger\n\n"
        "| id | donor | location | size | donor says | self says | verdict | why | effect | "
        "artifact | finding effect |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| L-001 | a1 | cover letter p5 | small | the donor's sentence | the base's sentence | "
        "keep-self | base wins | none | `integrated/work/diffs/L-001.md` | none |\n"
        "| L-002 | w2 | main text headings | large | a different tree | the base tree | "
        "keep-self | no M20 row attaches to it | none | `integrated/work/diffs/L-001.md` | none |\n",
        encoding="utf-8")
    rep = nb.integration_ledger_report(out, ["a1", "w2"], True)
    check("the 3-row orientation table is NOT read as the ledger",
          rep["rows"] == 2, f"rows={rep['rows']}")
    check("every ledger row's artifact is found",
          rep["missing_artifact"] == [] and rep["missing_finding"] == [],
          f"missing_artifact={rep['missing_artifact']} missing_finding={rep['missing_finding']}")
    check("both donors and both size classes are read from the LEDGER",
          rep["donors_absent"] == [] and rep["both_levels"] is True,
          f"absent={rep['donors_absent']} sizes={rep['sizes']}")
    # A file that really has no ledger table still reports the rows it does have.
    out2 = scratch("paper_int_led2_") / "integrated"
    out2.mkdir(parents=True)
    (out2 / "DIFF_LEDGER.md").write_text(
        "| version | payload files |\n|---|---|\n| integrated/ | 29 |\n| others/a1/ | 38 |\n",
        encoding="utf-8")
    rep2 = nb.integration_ledger_report(out2, ["a1"], False)
    check("a file with no ledger columns keeps the old (failing) reading",
          rep2["rows"] == 2 and len(rep2["missing_artifact"]) == 2,
          f"rows={rep2['rows']} missing={rep2['missing_artifact']}")


# ---------------------------------------------------------------------------
# 2. a repair that runs the seeded tools is not "out of scope"
# ---------------------------------------------------------------------------
def test_repair_guard_ignores_bytecode():
    print()
    print("== repair scope: `__pycache__/*.pyc` is a cache of RUNNING a tool, not an edit ==")
    sb = scratch("paper_int_guard_")
    (sb / "integrated" / "work").mkdir(parents=True)
    (sb / "integrated" / "DIFF_LEDGER.md").write_text("| donor | artifact |\n|---|---|\n", encoding="utf-8")
    (sb / "paper_docx_format.py").write_text("# the seeded tool\n", encoding="utf-8")
    guard = nb.snapshot_repair_guard(sb, {"kind": "integrate", "id": "r1_i3", "round": 1})
    # what the session's own tool runs produce, plus one REAL violation
    (sb / "__pycache__").mkdir()
    (sb / "__pycache__" / "paper_docx_format.cpython-312.pyc").write_bytes(b"pyc")
    (sb / "integrated" / "work" / "__pycache__").mkdir()
    (sb / "integrated" / "work" / "__pycache__" / "helper.pyc").write_bytes(b"pyc")
    (sb / "integrated" / "work" / "helper.pyo").write_bytes(b"pyc")
    (sb / "EVIL.md").write_text("a real out-of-scope create", encoding="utf-8")
    problems = nb.repair_guard_problems(sb, guard, {"kind": "integrate"})
    check("bytecode caches are ignored, a real out-of-scope file is still caught",
          len(problems) == 1 and "EVIL.md" in problems[0], str(problems))
    check("a `__pycache__` created inside the package is ignored too",
          not any("pyc" in p or "__pycache__" in p for p in problems), str(problems))


# ---------------------------------------------------------------------------
# 3. the integration prompt: full corpora, no diff-driven porting
# ---------------------------------------------------------------------------
def test_integrate_prompt_reads_the_corpora():
    print()
    print("== the integration prompt: read every donor in full, decide on the material ==")
    p = nb.integrate_prompt(Path("/tmp/paper_sb"), "r1_i3", 1, "w2", ["a1", "w1", "a2"],
                            caption_limit=0, zotero="edit")
    flat = " ".join(p.split())
    check("no unresolved placeholder is left in the prompt",
          not __import__("re").search(r"@@[A-Z_]+@@", p))
    check("the prompt demands a FULL read of the base and every donor",
          "Read self/ and EVERY others/<id>/ IN FULL YOURSELF" in flat
          and "enumerate their differences yourself" in flat)
    check("a diff-driven port is explicitly forbidden (figures/layout are invisible to it)",
          "Do NOT rely on a shell `diff`" in flat and "a diff-driven port silently drops" in flat)
    check("the ledger rule asks for the whole donor, not a sampled one",
          "read each donor whole (no sampling)" in flat)
    check("no trace of the (reverted) difference index is left in the prompt",
          "DIFF_MATRIX" not in p and "difference index" not in flat.lower()
          and "donor_diff" not in p)
    check("the prompt does NOT promise a repair for an unfinished session",
          "WRITE THE BOOKKEEPING AS YOU GO" not in p
          and "the orchestrator's scoped repair session can finish" not in flat)
    check("the completion marker is still the session's own LAST step",
          "very last step" in p)
    rep = nb.repair_prompt(type("C", (), {"sandbox_of": lambda self, rec: Path("/tmp")})(),
                           {"id": "r1_i3", "kind": "integrate", "round": 1},
                           ["integrate: 4 ledger row(s) carry no `artifact` -- x"])
    check("the repair prompt states the ledger columns and variant B",
          "`donor` and `artifact` above all" in rep
          and "a missing ledger is a failed attempt, not a repair job" in " ".join(rep.split()))


# ---------------------------------------------------------------------------
# 4. a freshly materialized integration sandbox is clean/unstarted
# ---------------------------------------------------------------------------
def test_fresh_integration_sandbox_is_clean():
    print()
    print("== the leftover guard: an untouched integration sandbox is not 'already worked in' ==")
    root = scratch("paper_int_left_")
    sb = root / "runs" / "r1_i1"
    (sb / "integrated").mkdir(parents=True)          # materialize_integrate creates it empty
    ctx = nb.Ctx(root)
    rec = {"kind": "integrate", "sandbox": "runs/r1_i1"}
    check("an EMPTY integrated/ is not agent work",
          nb.leftovers_present(ctx, rec) is False)
    (sb / "integrated" / "DIFF_LEDGER.md").write_text("a real ledger", encoding="utf-8")
    check("anything the session writes in the package DOES count as work already done",
          nb.leftovers_present(ctx, rec) is True)
    (sb / "integrated" / "DIFF_LEDGER.md").unlink()
    (sb / "code").mkdir()
    (sb / "code" / "run.sh").write_text("x", encoding="utf-8")
    check("code/ still counts as work already done",
          nb.leftovers_present(ctx, rec) is True)


def main() -> int:
    try:
        test_ledger_table_selection()
        test_repair_guard_ignores_bytecode()
        test_integrate_prompt_reads_the_corpora()
        test_fresh_integration_sandbox_is_clean()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} INTEGRATION-DIAGNOSTICS CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL INTEGRATION-DIAGNOSTICS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

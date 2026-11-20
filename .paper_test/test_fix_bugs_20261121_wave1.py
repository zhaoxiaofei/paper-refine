#!/usr/bin/env python3
"""Two failure-diagnosis fixes from a 2026-11-19 long-manuscript run.

Run:  python3 .paper_test/test_fix_bugs_20261121_wave1.py

1. THE BOUNDED REPAIR'S PLAN NAMES THE PACKAGE, NOT ITS MANIFEST. The revision
   auditor writes `"file": "revised/manuscript.md"` (the package it audited);
   `_revised_repair_violations` compares a row's file with the manifests of
   `revised/`, whose keys are `manuscript.md`. Every such row was reported as
   "changed without a confirmed plan row naming it" and a legitimate repair
   failed its application audit while its (rejected) edit still had to be
   rolled back. `_package_rel_under_revised` normalizes the two spellings; the
   stored row is always package-relative.

2. THE FAILURE CLASSIFIER READS THE END OF THE TRANSCRIPT. `_read_stream_capped`
   kept the first 16 MiB of each stream and discarded the rest, so the CLI's
   dying words -- and the provider error that caused them -- were invisible on
   a long session, while a phrase the agent merely read from a source file
   could be anywhere. It now also keeps a bounded TAIL, and
   `_execute_attempt_in` classifies on that tail.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_fixes", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_fixes"] = nb
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
# 1. a plan row's `file` is package-relative under revised/
# ---------------------------------------------------------------------------
def test_plan_row_path() -> None:
    print()
    print("== the repair plan's `file` is relative to revised/ ==")
    for raw, want in (
        ("manuscript.md", "manuscript.md"),
        ("revised/manuscript.md", "manuscript.md"),
        ("./revised/manuscript.md", "manuscript.md"),
        ("revised\\manuscript.md", "manuscript.md"),
        ("revised/", ""),
        ("../outside.md", "../outside.md"),
        ("/etc/passwd", "/etc/passwd"),
    ):
        got = nb._package_rel_under_revised(raw)
        check(f"{raw!r} -> {want!r}", got == want, got)

    tmp = scratch("paper_plan_rel_")
    sb = tmp / "sb"
    (sb / "revised").mkdir(parents=True)
    (sb / "revision_audit").mkdir()
    (sb / "revised" / "manuscript.md").write_text(
        "preamble alpha beta postamble\n", encoding="utf-8")
    (sb / "revision_audit" / "REPAIR_PLAN.json").write_text(json.dumps({"rows": [{
        "id": "RP-001", "finding": "none",
        "file": "revised/manuscript.md",
        "location": "Results, paragraph 3",
        "wrong": "alpha", "correct": "gamma",
        "basis": "fixture", "edit": "replace the word", "evidence": "fixture",
    }]}), encoding="utf-8")
    rows = nb._revision_plan_rows(sb)
    check("the plan row loads with a package-relative file",
          bool(rows) and rows[0]["file"] == "manuscript.md", str(rows))

    pre = tmp / "pre"
    shutil.copytree(sb / "revised", pre)
    (sb / "revised" / "manuscript.md").write_text(
        "preamble gamma beta postamble\n", encoding="utf-8")
    # The bounded-repair session records the applied text in its own ledger; the
    # span audit compares the real diff with THESE quotes.
    (sb / "revised" / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [{
        "id": "RP-001", "verdict": "confirmed", "reason": "fixture",
        "before": "alpha beta", "after": "gamma beta",
        "files": ["revised/manuscript.md"],
        "files": ["revised/manuscript.md"], "basis": "fixture",
    }]}), encoding="utf-8")
    bad = nb._revised_repair_violations(pre, sb / "revised", rows, {rows[0]["id"]},
                                        with_reasons=True)
    check("the row's own edit is inside its scope (no false 'unplanned change')",
          not bad, str(bad))
    # The regression pin: the UN-normalized spelling is exactly what failed.
    old_rows = [dict(rows[0], file="revised/manuscript.md")]
    old_bad = nb._revised_repair_violations(pre, sb / "revised", old_rows,
                                            {rows[0]["id"]}, with_reasons=True)
    check("the un-normalized spelling is what used to fail the repair",
          "manuscript.md" in old_bad, str(old_bad))


# ---------------------------------------------------------------------------
# 2. the classifier reads the TAIL of the transcript
# ---------------------------------------------------------------------------
def test_stream_tail() -> None:
    print()
    print("== the failure classifier reads the END of a long transcript ==")
    body = ("A" * 1000) + "TAILMAGIC"
    head, size, tail = nb._read_stream_capped(io.StringIO(body), 100, tail_cap=24)
    check("the head keeps the first `cap` characters",
          head == "A" * 100, head[:20])
    check("the total is the whole stream", size == len(body), size)
    check("the tail keeps the END, not the head", tail.endswith("TAILMAGIC"), tail)

    # A source comment the agent read (the old false positive) in the head, and
    # the provider's real error at the end: only the tail may decide.
    head_text = ('    # a bare status line (`413 Payload Too Large`, `Error: 413 - '
                 'payload too\n' + ("x" * 200))
    tail_text = ("\nOpenAI Codex v0.155.1\nERROR: unexpected status 413 Payload "
                 "Too Large: length limit exceeded\n")
    check("a trigger in the head is not provider evidence",
          nb.agent_failure_kind(head_text, "") == "",
          nb.agent_failure_kind(head_text, ""))
    check("the same trigger at the end classifies",
          nb.agent_failure_kind(tail_text, "") == "context_overflow")
    # And the real end-to-end shape: a >cap stream whose end carries the error.
    stream = io.StringIO(("x" * 5000) + tail_text)
    _head, _size, _tail = nb._read_stream_capped(stream, 64, tail_cap=4096)
    check("a long stream still classifies from its tail",
          nb.agent_failure_kind(_tail, "") == "context_overflow")


# ---------------------------------------------------------------------------
# 3. a corrected e-mail address is not a removed contact fact
# ---------------------------------------------------------------------------
def test_email_correction() -> None:
    print()
    print("== a corrected e-mail address is not a deletion surface ==")
    tmp = scratch("paper_email_fix_")
    base = tmp / "base"
    rev = tmp / "revised"
    (base / "work").mkdir(parents=True)
    (rev / "work").mkdir(parents=True)
    # The base carries the planted typo AND the corpus's correct copy (the
    # protected metadata block), which is a 2026-11-19 revision's shape.
    (base / "ms.md").write_text(
        "Correspondence: a.lind@uni-leipzig.dde\n"
        "Metadata: a.lind@uni-leipzig.de\n", encoding="utf-8")
    (rev / "ms.md").write_text(
        "Correspondence: a.lind@uni-leipzig.de\n"
        "Metadata: a.lind@uni-leipzig.de\n", encoding="utf-8")
    errs, warns = nb.email_address_change_problems(
        [(base, "", ())], [(rev, "", ("work",))], rev, "revise")
    check("the corpus-carried correction raises no 'no longer carries' warning",
          not any("no longer carries" in w for w in warns), str(warns))
    check("the correction is not an invented address (no error)",
          not errs, str(errs))

    (base / "ms.md").write_text("Correspondence: a.lind@uni-leipzig.de\n",
                                encoding="utf-8")
    (rev / "ms.md").write_text("Correspondence: (address withheld)\n",
                               encoding="utf-8")
    errs2, warns2 = nb.email_address_change_problems(
        [(base, "", ())], [(rev, "", ("work",))], rev, "revise")
    check("an address that actually vanished is still reported",
          any("no longer carries" in w for w in warns2), str(warns2))


def main() -> int:
    try:
        test_plan_row_path()
        test_stream_tail()
        test_email_correction()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FIX CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL FIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

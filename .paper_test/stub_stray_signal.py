#!/usr/bin/env python3
"""A stub session that finishes its stage but files the completion signal WRONG.

Wraps `stub_agent.py` (the deterministic offline session) and then, on purpose,
moves or forges the completion signal. It reproduces the 2026-09-23 root's two
paperwork failures end to end, so the pipeline's own layers can be asserted
against a real CLI run instead of a fixture:

    PAPER_STRAY_MARKER=<substring of the run id>
        the session does its work correctly and then MOVES `_pipeline_done.json`
        into the stage's own directory (`audit/`, `review/`, `revised/`, ...).
        The pipeline must ADOPT it (the work is the work; only its address is
        wrong) and record a warning naming the stray path.

    PAPER_STRAY_STAGE=<substring of the run id>
        the session leaves a marker in the stage's own directory that names the
        WRONG stage (`definitely-not-this-stage`). That is never adopted: the
        attempt must FAIL with a message naming the stray file.

    PAPER_STRAY_DELIVERABLE=<run-id substring>:<basename>
        the session files one of its REQUIRED deliverables one level up (a
        reviser's `revision_report.json` moved from `revised/` to the sandbox
        root). The pipeline must ADOPT it into place, like a misplaced marker.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def stage_dir(name: str) -> str:
    """The stage's own output directory for a run id ("" when it has none)."""
    if "_judge_" in name or name.startswith("judge_"):
        return "judge_review"
    if name.endswith("_review"):
        return "review"
    if name.endswith("_audit"):
        return "audit"
    if re.search(r"_a\d+_revise$", name):
        return "revised"
    if re.search(r"_w\d+$", name):
        return "rewritten"
    if re.search(r"_i\d+$", name):
        return "integrated"
    return ""


def round_of(name: str) -> int:
    m = re.search(r"r(\d+)_", name)
    return int(m.group(1)) if m else 1


def package_of(name: str) -> str:
    """The stage's package directory (the one the stage delivers into)."""
    if re.search(r"_w\d+$", name):
        return "rewritten"
    if re.search(r"_a\d+_revise$", name):
        return "revised"
    if re.search(r"_i\d+$", name):
        return "integrated"
    return ""


def main() -> int:
    sb = Path.cwd()
    name = sb.name
    spec = importlib.util.spec_from_file_location("stub_agent", HERE / "stub_agent.py")
    stub = importlib.util.module_from_spec(spec)
    sys.modules["stub_agent"] = stub
    spec.loader.exec_module(stub)
    rc = stub.main()
    if rc != 0:
        return rc
    out = stage_dir(name)
    marker = sb / "_pipeline_done.json"
    move_for = os.environ.get("PAPER_STRAY_MARKER") or ""
    forge_for = os.environ.get("PAPER_STRAY_STAGE") or ""
    deliver_for = os.environ.get("PAPER_STRAY_DELIVERABLE") or ""
    if out and move_for and move_for in name and marker.is_file():
        dest = sb / out / marker.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        marker.replace(dest)
        print(f"stub_stray_signal: moved the marker to {out}/", file=sys.stderr)
    if out and forge_for and forge_for in name:
        dest = sb / out / marker.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({"stage": "definitely-not-this-stage", "run_id": name,
                                    "round": round_of(name), "status": "complete"}),
                        encoding="utf-8")
        if marker.is_file():
            marker.unlink()
        print(f"stub_stray_signal: forged a wrong-stage marker in {out}/", file=sys.stderr)
    if deliver_for and ":" in deliver_for:
        want_run, name_del = deliver_for.split(":", 1)
        pkg = package_of(name)
        if pkg and want_run in name and name_del:
            src = sb / pkg / name_del
            if src.is_file():
                dest = sb / name_del
                dest.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dest)
                print(f"stub_stray_signal: moved {pkg}/{name_del} to the sandbox root",
                      file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

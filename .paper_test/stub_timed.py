#!/usr/bin/env python3
"""Timing-instrumented stub agent for the scheduling tests.

Wraps `stub_agent.py`: it appends "<event> <run-id> <epoch>" lines to the file
named by PAPER_TIMING_LOG (start/end of the session) and sleeps for a
per-stage duration before doing the real stub work, so a test can measure which
round steps actually ran concurrently.

The sleep is chosen by the run-id suffix:
    ..._w<k>        PAPER_TIMING_SLEEP_W   (rewrite)
    ..._review      PAPER_TIMING_SLEEP_R   (review)
    ..._a<k>_revise PAPER_TIMING_SLEEP_V   (revise)
    ..._i<k>        PAPER_TIMING_SLEEP_I   (integration)
    ..._judge_...   PAPER_TIMING_SLEEP_J   (judge)
falling back to PAPER_TIMING_SLEEP (default 0, i.e. no sleep).
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def kind_of(name: str) -> str:
    # Judge run ids are opaque tokens ("judge_<token>_j<k>", no round/arm prefix).
    if "_judge_" in name or name.startswith("judge_"):
        return "J"
    if re.search(r"_w\d+$", name):
        return "W"
    if name.endswith("_review"):
        return "R"
    if name.endswith("_audit"):
        return "AU"
    if re.search(r"_a\d+_revise$", name):
        return "V"
    if re.search(r"_i\d+$", name):
        return "I"
    return "?"


def append_log(event: str, name: str) -> None:
    path = os.environ.get("PAPER_TIMING_LOG")
    if not path:
        return
    line = f"{event} {name} {time.time():.3f}\n"
    try:
        # One small O_APPEND write per line: concurrent stub processes interleave
        # whole lines, never partial ones.
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def intentionally_fail(name: str) -> bool:
    """Fail this attempt once (PAPER_TIMING_FAIL_ONCE) or always (…_ALWAYS_FAIL).

    Used by the scheduling tests to prove that a failed session is retried with
    a rebuilt sandbox and that a permanently failed session keeps the round
    undecided instead of silently shrinking the panel.
    """
    always = os.environ.get("PAPER_TIMING_ALWAYS_FAIL") or ""
    if always and always in name:
        append_log("fail", name)
        return True
    once = os.environ.get("PAPER_TIMING_FAIL_ONCE") or ""
    if once and once in name:
        log_path = os.environ.get("PAPER_TIMING_LOG") or "/tmp/paper_timing_fail"
        flag = Path(log_path).with_name(f"failed_once_{name}")
        if not flag.exists():
            try:
                flag.write_text("failed once\n", encoding="utf-8")
            except OSError:
                pass
            append_log("fail", name)
            return True
    return False


def write_bad_marker(name: str) -> bool:
    """Write a marker whose stage/payload is wrong (PAPER_TIMING_BAD_MARKER).

    The pipeline must treat "a completion signal exists but the postcheck
    fails" as a FAILED ATTEMPT: rebuild the sandbox and retry, never re-check
    the same broken marker in a loop.
    """
    target = os.environ.get("PAPER_TIMING_BAD_MARKER") or ""
    if not target or target not in name:
        return False
    import json
    (Path.cwd() / "_pipeline_done.json").write_text(
        json.dumps({"stage": "definitely-not-this-stage", "run_id": name,
                    "round": 1, "status": "complete"}), encoding="utf-8")
    append_log("bad-marker", name)
    return True


def main() -> int:
    sb = Path.cwd()
    name = sb.name
    kind = kind_of(name)
    sleep_s = float(os.environ.get(f"PAPER_TIMING_SLEEP_{kind}",
                                   os.environ.get("PAPER_TIMING_SLEEP", "0")) or 0)
    append_log("start", name)
    if intentionally_fail(name):
        print(f"stub_timed: intentional failure for {name}", file=sys.stderr)
        return 2
    if write_bad_marker(name):
        print(f"stub_timed: wrote a wrong-stage marker for {name}", file=sys.stderr)
        return 0
    if sleep_s > 0:
        time.sleep(sleep_s)
    spec = importlib.util.spec_from_file_location("stub_agent", HERE / "stub_agent.py")
    stub = importlib.util.module_from_spec(spec)
    sys.modules["stub_agent"] = stub
    spec.loader.exec_module(stub)
    rc = stub.main()
    append_log("end", name)
    return rc


if __name__ == "__main__":
    sys.exit(main())

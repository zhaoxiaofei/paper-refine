#!/usr/bin/env python3
"""The retry policy rides on the scheduler: a failed session is retried with backoff and the round still completes

Part 5 of the parallel_scheduling suite. The shared helpers/fixtures live in
`parallel_scheduling_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_parallel_scheduling_5_retry.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("parallel_scheduling_lib", HERE / "parallel_scheduling_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["parallel_scheduling_lib"] = lib
_spec.loader.exec_module(lib)

if __name__ == "__main__":
    sys.exit(lib.run_parts([lib.test_retry_policy_survives_the_scheduler], "PART 5 (retry policy) PASSED"))

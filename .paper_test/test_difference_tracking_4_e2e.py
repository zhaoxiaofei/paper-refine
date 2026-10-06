#!/usr/bin/env python3
"""DO NOT change any end result: a stub round with the passes ON vs a --no-track control

Part 4 of the difference_tracking suite. The shared helpers/fixtures live in
`difference_tracking_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_difference_tracking_4_e2e.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("difference_tracking_lib", HERE / "difference_tracking_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["difference_tracking_lib"] = lib
_spec.loader.exec_module(lib)

if __name__ == "__main__":
    sys.exit(lib.run_parts([lib.test_end_to_end_end_results_are_unchanged], "PART 4 (end results unchanged) PASSED"))

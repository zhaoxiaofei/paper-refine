#!/usr/bin/env python3
"""Recovery from a failed attempt: misplaced/trapped deliverables are rescued or adopted

Part 2 of the stage_signals suite. The shared helpers/fixtures live in
`stage_signals_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_stage_signals_and_rebuild_2_recovery.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("stage_signals_lib", HERE / "stage_signals_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["stage_signals_lib"] = lib
_spec.loader.exec_module(lib)

if __name__ == "__main__":
    sys.exit(lib.run_parts([lib.test_foreign_stray_marker_fails_with_its_path, lib.test_short_rows_are_named, lib.test_misplaced_deliverable_is_rescued], "PART 2 (recovery from failed attempts) PASSED"))

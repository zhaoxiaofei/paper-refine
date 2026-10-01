#!/usr/bin/env python3
"""Arm levels and the diff-ledger rule in the prompts

Part 1 of the arm levels suite, split out of `arm_levels_lib.py` so GNU parallel can run
the independent sections concurrently. The shared helpers/fixtures live in
`arm_levels_lib.py`; this file only selects the functions of this part.

Run:  python3 .paper_test/test_arm_levels_1_prompts.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("arm_levels_lib", HERE / "arm_levels_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["arm_levels_lib"] = lib
_spec.loader.exec_module(lib)

if __name__ == "__main__":
    sys.exit(lib.run_parts([lib.test_rewrite_levels, lib.test_diff_ledger_rule_and_report], "PART 1 (arm levels) PASSED"))

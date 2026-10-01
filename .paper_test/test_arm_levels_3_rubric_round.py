#!/usr/bin/env python3
"""The judge writing rubric and a full stub round

Part 3 of the arm levels suite, split out of `arm_levels_lib.py` so GNU parallel can run
the independent sections concurrently. The shared helpers/fixtures live in
`arm_levels_lib.py`; this file only selects the functions of this part.

Run:  python3 .paper_test/test_arm_levels_3_rubric_round.py
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
    sys.exit(lib.run_parts([lib.test_judge_writing_rubric, lib.test_stub_round_arm_levels], "PART 3 (rubric + stub round) PASSED"))

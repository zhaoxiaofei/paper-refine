#!/usr/bin/env python3
"""Session selection: config edits, judge sessions, pinned-base judging

Part 2 of the only rounds suite, split out of `only_rounds_lib.py` so GNU parallel can run
the independent sections concurrently. The shared helpers/fixtures live in
`only_rounds_lib.py`; this file only selects the functions of this part.

Run:  python3 .paper_test/test_only_rounds_2_session_selection.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("only_rounds_lib", HERE / "only_rounds_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["only_rounds_lib"] = lib
_spec.loader.exec_module(lib)

if __name__ == "__main__":
    sys.exit(lib.run_parts([lib.test_plan_survives_a_config_edit, lib.test_only_judge_sessions, lib.test_only_judge_the_pinned_base], "PART 2 (session selection) PASSED"))

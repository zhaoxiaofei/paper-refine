#!/usr/bin/env python3
"""The session selfcheck and the judge artifacts it validates

Part 3 of the stage_signals suite. The shared helpers/fixtures live in
`stage_signals_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_stage_signals_and_rebuild_3_selfcheck.py
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
    sys.exit(lib.run_parts([lib.test_selfcheck, lib.test_prompts_state_the_marker_location, lib.test_selfcheck_covers_the_other_stages, lib.test_judge_check_ids_the_prompt_names_are_accepted, lib.test_judge_prompt_gets_a_blinding_safe_preflight, lib.test_judge_selfcheck_catches_a_bad_sheet], "PART 3 (selfcheck + judge artifacts) PASSED"))

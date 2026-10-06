#!/usr/bin/env python3
"""The tracking name family (baseline tokens) and its exclusion from every corpus

Part 1 of the difference_tracking suite. The shared helpers/fixtures live in
`difference_tracking_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_difference_tracking_1_names.py
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
    sys.exit(lib.run_parts([lib.test_name_family_and_aux_rule, lib.test_auxiliaries_never_change_an_identity], "PART 1 (names + exclusion) PASSED"))

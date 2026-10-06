#!/usr/bin/env python3
"""Stage signals: kind tables, sandbox rebuild, marker relocation, stray markers

Part 1 of the stage_signals suite. The shared helpers/fixtures live in
`stage_signals_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_stage_signals_and_rebuild_1_signals.py
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
    sys.exit(lib.run_parts([lib.test_kind_support_tables, lib.test_rebuild_recreates_an_audit_sandbox, lib.test_audit_retry_completes_the_round, lib.test_relocation_semantics, lib.test_misplaced_marker_is_adopted_end_to_end], "PART 1 (kind tables + marker relocation) PASSED"))

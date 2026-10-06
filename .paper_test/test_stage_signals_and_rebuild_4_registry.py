#!/usr/bin/env python3
"""The registry reader's backup/compaction and the process-death window

Part 4 of the stage_signals suite. The shared helpers/fixtures live in
`stage_signals_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_stage_signals_and_rebuild_4_registry.py
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
    sys.exit(lib.run_parts([lib.test_registry_reader_backup_and_compaction, lib.test_process_died_after_the_audit_finished], "PART 4 (registry reader + process death) PASSED"))

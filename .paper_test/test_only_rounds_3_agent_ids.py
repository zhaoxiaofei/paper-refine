#!/usr/bin/env python3
"""Agent sessions, printed ids and the `agents` command

Part 3 of the only rounds suite, split out of `only_rounds_lib.py` so GNU parallel can run
the independent sections concurrently. The shared helpers/fixtures live in
`only_rounds_lib.py`; this file only selects the functions of this part.

Run:  python3 .paper_test/test_only_rounds_3_agent_ids.py
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
    sys.exit(lib.run_parts([lib.test_only_agent_sessions, lib.test_only_accepts_the_printed_ids], "PART 3 (agent ids) PASSED"))

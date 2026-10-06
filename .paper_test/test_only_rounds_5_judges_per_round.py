#!/usr/bin/env python3
"""Per-round judge counts and their plan-time reporting

Part 5 of the only-rounds suite (judges per round). The shared helpers/fixtures live in
`only_rounds_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_only_rounds_5_judges_per_round.py
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
    sys.exit(lib.run_parts([lib.test_judges_per_round], "PART 5 (judges per round) PASSED"))

#!/usr/bin/env python3
"""One judge SESSION at a time: --only judge selections stay reproducible

Part 6 of the only-rounds suite (judge-session selection). The shared helpers/fixtures live in
`only_rounds_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_only_rounds_6_judge_sessions.py
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
    sys.exit(lib.run_parts([lib.test_only_judge_sessions], "PART 6 (judge sessions) PASSED"))

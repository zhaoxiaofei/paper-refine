#!/usr/bin/env python3
"""Session selection: a config edit does not resurrect sessions the root never ran

Part 2 of the only-rounds suite (the judge-session and pinned-base selections live in
their own parts). The shared helpers/fixtures live in `only_rounds_lib.py`; this file
only selects the functions of this part.

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
    sys.exit(lib.run_parts([lib.test_plan_survives_a_config_edit], "PART 2 (session selection) PASSED"))

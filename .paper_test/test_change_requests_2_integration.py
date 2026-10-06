#!/usr/bin/env python3
"""The integration arms: every pool member reworked once with the whole pool as donors

Part 2 of the change_requests suite. The shared helpers/fixtures live in
`change_requests_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_change_requests_2_integration.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("change_requests_lib", HERE / "change_requests_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["change_requests_lib"] = lib
_spec.loader.exec_module(lib)

if __name__ == "__main__":
    sys.exit(lib.run_parts([lib.test_integration_materialization, lib.test_integration_postcheck, lib.test_rewrite_and_revise_arms, lib.test_field_and_selection], "PART 2 (integration arms) PASSED"))

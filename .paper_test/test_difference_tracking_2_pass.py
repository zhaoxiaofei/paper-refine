#!/usr/bin/env python3
"""The difference-tracking pass: copies, digest-gated reuse, fallbacks, no agent session

Part 2 of the difference_tracking suite. The shared helpers/fixtures live in
`difference_tracking_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_difference_tracking_2_pass.py
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
    sys.exit(lib.run_parts([lib.test_tracking_pass_outputs, lib.test_redline_reuse_is_digest_gated, lib.test_latexdiff_and_fallbacks, lib.test_fallback_names_are_uniformly_logging, lib.test_identical_baselines_are_tracked_once, lib.test_tool_none_writes_no_copy, lib.test_no_agent_session_is_started], "PART 2 (tracking pass) PASSED"))

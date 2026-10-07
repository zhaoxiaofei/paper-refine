#!/usr/bin/env python3
"""Stage-time difference tracking: siblings, rewiring, compiled tracking PDFs.

Part 5 of the difference_tracking suite. The shared helpers/fixtures live in
`difference_tracking_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_difference_tracking_5_stage_hooks.py
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
    sys.exit(lib.run_parts([lib.test_stage_hook_tracks_beside_the_version,
                            lib.test_round_close_skips_fresh_stage_copies,
                            lib.test_rewire_and_fallback_regressions,
                            lib.test_template_stage_tracking_is_sibling_first],
                           "PART 5 (stage-time hooks) PASSED"))

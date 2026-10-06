#!/usr/bin/env python3
"""PART 4

Part 4 of the docx_format suite. The shared helpers/fixtures live in
`docx_format_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_docx_format_4_pipeline.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("docx_format_lib", HERE / "docx_format_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["docx_format_lib"] = lib
_spec.loader.exec_module(lib)

if __name__ == "__main__":
    sys.exit(lib.run_parts([lib.test_pipeline_wiring, lib.test_setup_normalization, lib.test_stage_normalization, lib.test_review_m20_seeding], "PART 4 (pipeline wiring) PASSED"))

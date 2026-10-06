#!/usr/bin/env python3
"""PART 2

Part 2 of the docx_format suite. The shared helpers/fixtures live in
`docx_format_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_docx_format_2_rules.py
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
    sys.exit(lib.run_parts([lib.test_layout_budget_rules, lib.test_journal_emphasis, lib.test_text_consistency_rules, lib.test_quality_engines, lib.test_tab_scan_ignores_tab_stop_definitions, lib.test_unreadable_docx_reports_fmt_x1, lib.test_cover_letter_stamp_rule], "PART 2 (style/text rules) PASSED"))

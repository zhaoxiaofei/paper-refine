#!/usr/bin/env python3
"""PART 3

Part 3 of the docx_format suite. The shared helpers/fixtures live in
`docx_format_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_docx_format_3_render_validate.py
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
    sys.exit(lib.run_parts([lib.test_deliverable_validation, lib.test_lookup_404_is_a_verified_negative, lib.test_accession_lookup_uses_the_matching_ncbi_database, lib.test_cli, lib.test_render_blank_page_if_available], "PART 3 (renders, validation, lookups) PASSED"))

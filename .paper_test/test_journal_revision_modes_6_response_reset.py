#!/usr/bin/env python3
"""The response postcheck verifies its input manifest; an integrator reset reaches the response letter

Part 6 of the journal revision-mode suite. The shared helpers/fixtures live in
`journal_revision_modes_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_journal_revision_modes_6_response_reset.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("journal_revision_modes_lib",
                                               HERE / "journal_revision_modes_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["journal_revision_modes_lib"] = lib
_spec.loader.exec_module(lib)

if __name__ == "__main__":
    sys.exit(lib.run_parts([lib.test_response_postcheck_verifies_its_input_manifest, lib.test_integrator_reset_reaches_the_response_letter], "PART 6 PASSED"))

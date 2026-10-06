#!/usr/bin/env python3
"""Option 2 (resubmit) and the scoped scope guard

Part 3 of the journal revision-mode suite. The shared helpers/fixtures live in
`journal_revision_modes_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_journal_revision_modes_3_resubmit_guard.py
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
    sys.exit(lib.run_parts([lib.test_j4_narrative, lib.test_j5_narrative], "PART 3 PASSED"))

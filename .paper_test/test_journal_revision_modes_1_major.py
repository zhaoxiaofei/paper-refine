#!/usr/bin/env python3
"""Option 3 (major revision): the scoped revision, its concerns ledger, the response letter and the submission package

Part 1 of the journal revision-mode suite. The shared helpers/fixtures live in
`journal_revision_modes_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_journal_revision_modes_1_major.py
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
    sys.exit(lib.run_parts([lib.test_j1_narrative], "PART 1 PASSED"))

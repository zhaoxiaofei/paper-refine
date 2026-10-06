#!/usr/bin/env python3
"""Prune keeps a scoped round's published winner; leaving a scoped mode restores the default plan

Part 7 of the journal revision-mode suite. The shared helpers/fixtures live in
`journal_revision_modes_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_journal_revision_modes_7_scoped_prune.py
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
    sys.exit(lib.run_parts([lib.test_scoped_prune_keeps_a_published_winner, lib.test_leaving_a_scoped_mode_restores_the_default_plan], "PART 7 PASSED"))

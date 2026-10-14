#!/usr/bin/env python3
"""PART 5

Part 5 of the docx_format suite: the caption/legend BLOCK rules
(FMT-T2a..FMT-T2d) -- a caption is one paragraph, the paragraphs of one caption
carry the caption's spacing and style, and the fixer merges what it can while
the Live-field fence guards what it moves. The shared helpers/fixtures live in
`docx_format_lib.py`; this file only selects the sections of this part.

Run:  python3 .paper_test/test_docx_format_5_caption_blocks.py
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
    sys.exit(lib.run_parts([lib.test_caption_blocks, lib.test_caption_bold_merge],
                           "PART 5 (caption blocks) PASSED"))

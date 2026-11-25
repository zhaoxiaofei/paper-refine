#!/usr/bin/env python3
"""Regression checks for the 2026-11-25 02:31:07 fix-bugs wave, group D.

  F003  a two-column Markdown table WITHOUT outer pipes is read by the hand-off
        README parser (its rows used to be dropped, so author work repeated)
  F022  `[1]Smith` (no space after a bracketed label) is a reference entry
  F024  `--only 1-100` is accepted when setup supports MAX_ROUNDS=1000 rounds
  F101  `feedback_text_of` honours the shared text byte budget
  F102  feedback discovery refuses a symlink out of the corpus
  F103  a UTF-16 "Save as text" feedback letter decodes to real text
  F104  `seed_concern_candidates` keeps the editor preamble before the first
        reviewer/heading
  F119  an author README in `llm_review_feedback/` is not reviewer feedback

The suite is hermetic: temp dirs only, no network, no Word/Office.

Run:  python3 .paper_test/test_fix_bugs_20261125_D.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1125d_pp", "paper_pipeline.py")

FAILS = []
TMPDIRS = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        for p in [tmp, *tmp.rglob("*")]:
            with contextlib.suppress(OSError):
                if p.is_dir() and not p.is_symlink():
                    p.chmod(0o755)
                elif not p.is_symlink():
                    p.chmod(0o644)
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# F003 -- no-outer-pipe two-column README checklist table
# ---------------------------------------------------------------------------
def test_f003() -> None:
    print("\n== F003: no-outer-pipe two-column checklist table ==")
    text = "Item | Action\n--- | ---\nFix X | Do Y\nFix Z | Do W\n"
    rows = pp._readme_action_rows(text)
    check("F003 a valid no-outer-pipe two-column table yields its data rows",
          rows == ["Fix X | Do Y", "Fix Z | Do W"], repr(rows))
    # The existing outer-pipe behaviour must be untouched.
    outer = "| Item | Action |\n| --- | --- |\n| Fix X | Do Y |\n"
    check("F003 an outer-pipe table still yields its data rows",
          pp._readme_action_rows(outer) == ["Fix X | Do Y"],
          repr(pp._readme_action_rows(outer)))
    check("F003 a standalone no-outer-pipe separator is not a row",
          pp._readme_action_rows("--- | ---\n") == [],
          repr(pp._readme_action_rows("--- | ---\n")))
    # A bare `---` is a horizontal rule, not a table delimiter: the one-pipe
    # prose above it must not become a row.
    check("F003 a horizontal rule does not turn one-pipe prose into a row",
          pp._readme_action_rows("Item | Action\n---\n") == [],
          repr(pp._readme_action_rows("Item | Action\n---\n")))


# ---------------------------------------------------------------------------
# F022 -- glued bracketed reference label
# ---------------------------------------------------------------------------
def test_f022() -> None:
    print("\n== F022: `[1]Smith` is a reference entry ==")
    glued = pp._reference_entries_in_lines(
        ["References", "[1]Smith J. A title. Journal. 2020."], set())
    check("F022 a bracketed reference with no space after the label is collected",
          glued == {"[1]smith j. a title. journal. 2020."}, repr(glued))
    spaced = pp._reference_entries_in_lines(
        ["References", "[1] Smith J. A title. Journal. 2020."], set())
    check("F022 the spaced form is still collected",
          spaced == {"[1] smith j. a title. journal. 2020."}, repr(spaced))
    bare = pp._reference_entries_in_lines(
        ["References", "1.Smith J. A title. Journal. 2020"], set())
    check("F022 a bare ordinal still needs the space (`1.Smith` is not an entry)",
          bare == set(), repr(bare))


# ---------------------------------------------------------------------------
# F024 -- a supported 100-round plan can be selected in one range
# ---------------------------------------------------------------------------
def test_f024() -> None:
    print("\n== F024: `--only 1-100` on a supported 100-round plan ==")
    try:
        spec = pp.parse_only_spec("1-100")
        rounds = sorted(spec.rounds)
    except SystemExit:
        rounds = []
    check("F024 parse_only_spec('1-100') names all 100 rounds",
          rounds == list(range(1, 101)), f"{len(rounds)} rounds")
    check("F024 the hard cap is not below the supported round count",
          pp.ONLY_ROUND_RANGE_CAP >= pp.MAX_ROUNDS,
          f"{pp.ONLY_ROUND_RANGE_CAP} < {pp.MAX_ROUNDS}")
    try:
        pp.parse_only_spec("1-1001")
        too_big = False
    except SystemExit as e:
        too_big = e.code == 2
    check("F024 an implausible `1-1001` span is still refused", too_big)


# ---------------------------------------------------------------------------
# F101 -- feedback text honours the shared byte budget
# ---------------------------------------------------------------------------
def test_f101() -> None:
    print("\n== F101: feedback text is byte-bounded ==")
    d = scratch("fixbugs1125d_f101_")
    p = d / "letter.txt"
    p.write_text("x" * 4096, encoding="utf-8")
    old = pp.MAX_JSON_BYTES
    pp.MAX_JSON_BYTES = 1024
    try:
        check("F101 read_text_bounded refuses the same oversize file",
              pp.read_text_bounded(p) is None)
        text, note = pp.feedback_text_of(p)
        check("F101 feedback_text_of refuses the oversize file and says why",
              text == "" and bool(note), f"len={len(text)} note={note!r}")
    finally:
        pp.MAX_JSON_BYTES = old


# ---------------------------------------------------------------------------
# F102 -- a feedback symlink does not escape the corpus
# ---------------------------------------------------------------------------
def test_f102() -> None:
    print("\n== F102: feedback discovery refuses a symlink ==")
    d = scratch("fixbugs1125d_f102_")
    outside = d / "outside.txt"
    outside.write_text("SECRET-OUTSIDE-CORPUS", encoding="utf-8")
    area = d / "human_review_feedback"
    area.mkdir()
    link = area / "decision_letter.txt"
    link.symlink_to(outside)
    real = area / "referee_report.txt"
    real.write_text("Reviewer 1: the sample size is not justified.", encoding="utf-8")
    found = [label for _p, label in pp.human_feedback_files_in(d)]
    check("F102 a symlinked feedback file is not discovered",
          "human_review_feedback/decision_letter.txt" not in found, repr(found))
    check("F102 a regular feedback file is still discovered",
          "human_review_feedback/referee_report.txt" in found, repr(found))
    text, note = pp.feedback_text_of(link)
    check("F102 opening the symlink through the reader yields no outside text",
          text == "" and bool(note) and "SECRET" not in text,
          f"text={text!r} note={note!r}")


# ---------------------------------------------------------------------------
# F103 -- UTF-16 "Save as text" feedback letter
# ---------------------------------------------------------------------------
def test_f103() -> None:
    print("\n== F103: a UTF-16 feedback letter decodes ==")
    d = scratch("fixbugs1125d_f103_")
    p = d / "decision_letter.txt"
    wanted = "Reviewer 1: The sample size is not justified.\n"
    p.write_text(wanted, encoding="utf-16")
    text, note = pp.feedback_text_of(p)
    check("F103 a UTF-16 letter decodes to the text the reviewer wrote",
          text == wanted and note == "", f"{text[:40]!r} note={note!r}")
    check("F103 the decoded text carries no NUL mojibake", "\x00" not in text,
          repr(text[:40]))


# ---------------------------------------------------------------------------
# F104 -- the editor preamble is kept by the concern seed
# ---------------------------------------------------------------------------
def test_f104() -> None:
    print("\n== F104: the concern seed keeps the editor preamble ==")
    text = ("Dear authors, we cannot accept this paper until the sample size "
            "is justified.\nThe editor also requires a data availability statement.\n\n"
            "Reviewer 1: The sample size is not justified.\n"
            "Reviewer 2: The methods are unclear.\n")
    rows = pp.seed_concern_candidates(text)
    joined = " ".join(r.get("excerpt", "") for r in rows)
    check("F104 the editor demands before the first heading are seeded",
          "sample size is justified" in joined
          and "data availability statement" in joined, repr(rows))
    check("F104 the reviewer rows are still seeded",
          any("methods are unclear" in r.get("excerpt", "") for r in rows),
          repr(rows))
    check("F104 the preamble seed row is bounded like the other rows",
          all(len(r.get("excerpt", "")) <= 400 for r in rows), repr(rows))


# ---------------------------------------------------------------------------
# F119 -- an author README in llm_review_feedback is not feedback
# ---------------------------------------------------------------------------
def test_f119() -> None:
    print("\n== F119: a README in llm_review_feedback/ is not feedback ==")
    d = scratch("fixbugs1125d_f119_")
    area = d / "llm_review_feedback"
    area.mkdir()
    (area / "README.md").write_text("operator notes, not a review", encoding="utf-8")
    (area / "review.md").write_text("Reviewer: the claims are overstated.", encoding="utf-8")
    got = [label for _p, label in pp.llm_feedback_files_in(d)]
    check("F119 README.md in the LLM area is not ingested as LLM feedback",
          "llm_review_feedback/README.md" not in got, repr(got))
    check("F119 the real LLM review is still ingested",
          "llm_review_feedback/review.md" in got, repr(got))


def main() -> int:
    try:
        test_f003()
        test_f022()
        test_f024()
        test_f101()
        test_f102()
        test_f103()
        test_f104()
        test_f119()
    finally:
        cleanup()
    print(f"\n{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failed check(s)")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())

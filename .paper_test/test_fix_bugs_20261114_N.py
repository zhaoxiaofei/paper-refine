#!/usr/bin/env python3
"""Regression checks for the 2026-11-14 fix-bugs wave, group N (F154-F161, F164).

Repairs the shipped paper-review / paper-revise skill pack:
  * F154/F155 bundled scripts are documented and runnable only with their
    sibling modules (`evidence_names.py`, `manuscript_words.py`);
  * F156 convert_corpus refuses an oversized plain-text source with an
    inventory note instead of dying with MemoryError;
  * F157/F158/F164 revision_token reports skipped payloads, refuses a symlinked
    package root, and documents the exit status it actually implements;
  * F159/F160 one evidence-name rule (`review.md`/`comments.md` are feedback,
    a scientific `treatment_response.md` is prose in every extractor);
  * F161 count_words' cover-letter predicate accepts the pipeline's `letter`
    token.

Hermetic: every fixture lives under tempfile.mkdtemp().

Run:  python3 .paper_test/test_fix_bugs_20261114_N.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
REV_SCRIPTS = WS / "paper-skills" / "paper-revise" / "scripts"
TMPDIRS = []
FAILS = []


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def test_f154_f155_copies_are_runnable() -> None:
    print("\n== F154/F155: a copied script carries the siblings it imports ==")
    review_skill = (WS / "paper-skills/paper-review/SKILL.md").read_text("utf-8")
    check("F154 SKILL.md lists evidence_names.py as a companion",
          "scripts/evidence_names.py" in review_skill
          and "required companion" in review_skill)
    check("F154 SKILL.md lists manuscript_words.py as a companion",
          "scripts/manuscript_words.py" in review_skill)
    revise_skill = (WS / "paper-skills/paper-revise/SKILL.md").read_text("utf-8")
    check("F155 paper-revise no longer says to copy the script alone",
          "copy it together with its sibling module `evidence_names.py`" in revise_skill)

    d = scratch("fbn154_")
    for name in ("count_words.py", "manuscript_words.py", "evidence_names.py"):
        shutil.copy(SCRIPTS / name, d / name)
    (d / "m.md").write_text("Abstract\nOne two three.\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, "count_words.py", "m.md"], cwd=d,
                          capture_output=True, text=True)
    check("F154 a full copy of count_words runs", proc.returncode == 0
          and "abstract: 3 words" in proc.stdout, proc.stdout + proc.stderr)

    d2 = scratch("fbn155_")
    for name in ("extract_occurrences.py", "evidence_names.py"):
        shutil.copy(SCRIPTS / name, d2 / name)
    (d2 / "work" / "corpus").mkdir(parents=True)
    (d2 / "work" / "corpus" / "a.txt").write_text("The PCR assay used 5 mg.\n",
                                                  encoding="utf-8")
    proc = subprocess.run([sys.executable, "extract_occurrences.py", "--work", "work",
                           "--term", "PCR"], cwd=d2, capture_output=True, text=True)
    check("F155 a copy of extract_occurrences with evidence_names runs",
          proc.returncode == 0 and "1 occurrences" in proc.stdout,
          proc.stdout + proc.stderr)


def test_f156_oversized_plain_text() -> None:
    print("\n== F156: an over-budget plain-text source is recorded, not read ==")
    cc = load("fbn156_cc", SCRIPTS / "convert_corpus.py")
    d = scratch("fbn156_")
    big = d / "big.md"
    big.write_bytes(b"x" * 32)
    small = d / "small.md"
    small.write_text("Abstract\nOne two.\n", encoding="utf-8")
    old = cc.MAX_PLAIN_BYTES
    cc.MAX_PLAIN_BYTES = 16
    try:
        text, notes = cc.plain_copy(str(big))
    finally:
        cc.MAX_PLAIN_BYTES = old
    check("F156 the oversized file is refused before the decode",
          text == "" and any("conversion budget, not read" in n for n in notes),
          f"{text!r} {notes!r}")
    text2, notes2 = cc.plain_copy(str(small))
    check("F156 an under-budget file still converts", "Abstract" in text2 and not notes2,
          f"{text2!r} {notes2!r}")


def test_f157_f158_f164_revision_token() -> None:
    print("\n== F157/F158/F164: revision_token reports what it could not hash ==")
    rt = load("fbn157_rt", REV_SCRIPTS / "revision_token.py")
    d = scratch("fbn157_")
    pkg = d / "pkg"
    pkg.mkdir()
    (pkg / "a.md").write_text("body\n", encoding="utf-8")
    old = rt.MAX_PAYLOAD_BYTES
    rt.MAX_PAYLOAD_BYTES = 1
    try:
        info = rt.revision_token(pkg)
    finally:
        rt.MAX_PAYLOAD_BYTES = old
    check("F157 an all-skipped package reports its payload count",
          info["files"] == 1, str(info))
    check("F157 the skipped-file diagnostic is returned",
          any("payload budget" in n for n in info["notes"]), str(info["notes"]))
    empty = d / "empty"
    empty.mkdir()
    check("F157 a genuinely empty package still says no payload file found",
          rt.revision_token(empty)["notes"] == ["no payload file found"],
          str(rt.revision_token(empty)))

    link = d / "link"
    os.symlink(str(pkg), link)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = rt.main([str(link)])
    check("F158 the CLI refuses a symlinked package root with a clear error",
          rc == 2 and "symlinked package root" in err.getvalue(), f"rc={rc} {err.getvalue()!r}")
    check("F158 the API still does not walk the link (pipeline parity)",
          rt.revision_token(link)["files"] == 0)

    doc = rt.__doc__ or ""
    check("F164 the docstring no longer promises exit 1 on a read error",
          "1 on a verify mismatch or a\nread error" not in doc and "SKIPPED" in doc,
          doc[:200])
    check("F164 the docstring names the symlink-root exit status",
          "2 on a symlinked package root" in doc, doc[:200])


def test_f159_f160_evidence_names() -> None:
    print("\n== F159/F160: one evidence-name rule for every extractor ==")
    en = load("fbn159_en", SCRIPTS / "evidence_names.py")
    fb = re.compile("feedback|referee|reviewer|editor", re.I)
    rp = re.compile("response|reply|rebuttal", re.I)
    for name in ("review.md", "comments.md", "review.report.md", "paper.review.md"):
        check(f"F159 {name} is a feedback document",
              en.is_evidence(name, fb, rp) is True, name)
    check("F159 a bare notes.md stays authors' prose (existing behaviour)",
          en.is_evidence("notes.md", fb, rp) is False)
    check("F159 a dotted *.notes.md stays a notes document",
          en.is_evidence("editorial.notes.txt", fb, rp) is True)

    ec = load("fbn160_ec", SCRIPTS / "extract_citations.py")
    ea = load("fbn160_ea", SCRIPTS / "extract_acronyms.py")
    for name in ("treatment_response.md", "clinical_response.md", "immune_response.md"):
        check(f"F160 all extractors call {name} manuscript prose",
              ec.is_non_manuscript(name) is False
              and ea.is_evidence_name(name) is False,
              f"citations={ec.is_non_manuscript(name)} acronyms={ea.is_evidence_name(name)}")


def test_f161_cover_letter_token() -> None:
    print("\n== F161: count_words accepts the pipeline's `letter` token ==")
    cw = load("fbn161_cw", SCRIPTS / "count_words.py")
    check("F161 letter_to_editor.md is a cover letter",
          cw.is_cover_letter("", "letter_to_editor.md") is True)
    check("F161 the selected article type still outranks the token",
          cw.is_cover_letter("", "letter_to_the_editor.md",
                             type_names=("Letter to the Editor",)) is False)
    check("F161 a newsletter is not a cover letter",
          cw.is_cover_letter("", "newsletter.md") is False)


def main() -> int:
    for fn in (test_f154_f155_copies_are_runnable, test_f156_oversized_plain_text,
               test_f157_f158_f164_revision_token, test_f159_f160_evidence_names,
               test_f161_cover_letter_token):
        try:
            fn()
        except Exception as e:                                   # noqa: BLE001
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL GROUP-N FIX-BUGS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

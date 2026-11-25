#!/usr/bin/env python3
"""Regression checks for the 2026-11-25 02:31:07 fix-bugs wave, group G.

Every check pins one candidate that was re-verified on this tree: the failure
mode is reproduced from the cited code (temp fixtures / a direct call), never
copied from the candidate write-up.  Hermetic: temp dirs only, no network, no
Word/Office.

Run:  python3 .paper_test/test_fix_bugs_20261125_G.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
REVIEW = WS / "paper-skills" / "paper-review" / "scripts"
TESTS = WS / "paper-skills" / "tests"

FAILS: list[str] = []
TMPDIRS: list[Path] = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def run(args, **kw):
    return subprocess.run([sys.executable, *map(str, args)],
                          capture_output=True, text=True, **kw)


# --------------------------------------------------------------------- F054
def test_f054() -> None:
    print("\n== F054: count_words reads the venue-level cover-letter block ==")
    tmp = scratch("g_f054_")
    profile = {
        "id": "test-venue",
        "label": "Test Venue",
        "article_type": "Article",
        "article_type_id": "article",
        "default_article_type": "article",
        "article_types": [{
            "id": "article", "label": "Article",
            "length_limits": {"abstract": {"base": 150, "relaxation": 1.1},
                              "main_text": {"base": 3000, "relaxation": 1.1}},
        }],
        # The venue-wide fallback: VenueProfile.length_limits() inherits
        # type -> default type -> this block.
        "length_limits": {"cover_letter": {"min": 100, "max": 200,
                                           "source": "venue-wide preference"}},
    }
    prof_path = tmp / "test-venue.json"
    prof_path.write_text(json.dumps(profile), encoding="utf-8")
    letter = tmp / "letter.md"
    letter.write_text("Dear Editor,\n\n" + ("word " * 150) + "\n", encoding="utf-8")
    res = run([REVIEW / "count_words.py", letter, "--section", "cover-letter",
               "--venue-profile", prof_path, "--json"])
    try:
        rows = json.loads(res.stdout or "{}")
    except ValueError:
        rows = {}
    cover = next((r for r in rows.get("rows") or []
                  if r.get("section") == "cover letter"), {})
    check("F054 the venue-level 100-200 bound bounds the cover letter",
          res.returncode == 0 and (cover.get("min"), cover.get("max")) == (100, 200)
          and cover.get("within_preference") is True,
          f"rc={res.returncode} row={cover} err={res.stderr.strip()[:160]}")


# --------------------------------------------------------------------- F058
def test_f058() -> None:
    print("\n== F058: a long figure legend is its own M4 context ==")
    en = load("g_f058_numbers", "paper-skills/paper-review/scripts/extract_numbers.py")
    long_legend = ("Fig. 1 | A long legend with enough words to exceed sixty "
                   "characters and reports n = 15 samples")
    short_legend = "Fig. 1 | Design n = 15."
    body_sentence = ("Figure 1. We next tested the samples and found nothing at "
                     "all in this line")
    got = en.section_label(long_legend)
    check("F058 a >60-char figure legend labels 'figure legend' (M1 parity)",
          got == "figure legend", got)
    check("F058 a short legend keeps its label and a citing sentence stays out",
          en.section_label(short_legend) == "figure legend"
          and en.section_label(body_sentence) is None,
          f"{en.section_label(short_legend)!r} / {en.section_label(body_sentence)!r}")


# --------------------------------------------------------------------- F059
def test_f059() -> None:
    print("\n== F059: the default --min-count keeps a lone multi-omics ==")
    tmp = scratch("g_f059_")
    corpus = tmp / "corpus"
    corpus.mkdir()
    (corpus / "ms.txt").write_text("We used multi-omics data.\n"
                                   "The multiomics view was merged.\n",
                                   encoding="utf-8")
    # The documented invocation: no --min-count override.
    res = run([REVIEW / "enumerate_conventions.py", "--work", tmp, "--corpus", corpus])
    data = {}
    with contextlib.suppress(ValueError, OSError):
        data = json.loads((tmp / "STYLE_VARIANTS.json").read_text(encoding="utf-8"))
    keys = {c.get("key") for c in data.get("hyphen_families") or []}
    rows = [r for r in data.get("hyphen_families") or []
            if {"multi-omics", "multiomics"} <= set(r.get("forms") or [])]
    check("F059 the default invocation enumerates multi-omics/multiomics",
          res.returncode == 0 and "multiomics" in keys and rows,
          f"rc={res.returncode} keys={sorted(k for k in keys if k)} "
          f"out={res.stdout.strip()[:180]}")


# --------------------------------------------------------------------- F060
def test_f060() -> None:
    print("\n== F060: a symlinked --run-dir cannot rmtree the skill tree ==")
    ph = load("g_f060_hardcases", "paper-skills/tests/probe_hardcases.py")
    tmp = scratch("g_f060_")
    root = tmp / "skillroot"
    (root / "case").mkdir(parents=True)
    victim = root / "case" / "data.txt"
    victim.write_text("real content", encoding="utf-8")
    link = tmp / "link"
    os.symlink(root, link)
    refused, msg = False, ""
    try:
        ph._fresh_run_dir(str(link / "case"), str(root))
    except SystemExit as exc:
        refused = True
        msg = str(exc)
    check("F060 a run dir reached through a symlinked parent is refused",
          refused and victim.exists(),
          f"refused={refused} msg={msg[:120]} survived={victim.exists()}")


# --------------------------------------------------------------------- F061
def test_f061() -> None:
    print("\n== F061: a legal '>' in a w:t attribute does not leak bytes ==")
    cc = load("g_f061_convert", "paper-skills/paper-review/scripts/convert_corpus.py")
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
           '2006/main"><w:body><w:p><w:r><w:t xml:space="preserve" data-x="a>b">'
           'Hello visible world</w:t></w:r></w:p></w:body></w:document>')
    lines, notes = cc.docx_part_to_lines(xml)
    check("F061 the attribute tail is not part of the extracted text",
          lines == ["Hello visible world"], f"{lines!r} notes={notes!r}")


# --------------------------------------------------------------------- F062
def test_f062() -> None:
    print("\n== F062: --verify '' fails closed on an unreadable package ==")
    if os.geteuid() == 0:
        print("[ok ] F062 skipped: chmod 000 cannot make a file unreadable for root")
        return
    tmp = scratch("g_f062_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    payload = pkg / "ms.md"
    payload.write_text("hello world\n", encoding="utf-8")
    os.chmod(payload, 0)
    try:
        script = WS / "paper-skills" / "paper-revise" / "scripts" / "revision_token.py"
        plain = run([script, pkg])
        verify = run([script, pkg, "--verify", ""])
    finally:
        os.chmod(payload, 0o644)
    check("F062 an unhashed package cannot match an empty --verify",
          plain.returncode == 1 and verify.returncode == 1
          and "token is empty" in verify.stderr,
          f"plain rc={plain.returncode} verify rc={verify.returncode} "
          f"verify out={verify.stdout.strip()!r} err={verify.stderr.strip()!r}")


# --------------------------------------------------------------------- F063
def test_f063() -> None:
    print("\n== F063: M26 reference text is a recorded gap, not a promised row ==")
    tmp = scratch("g_f063_")
    corpus = tmp / "corpus"
    corpus.mkdir()
    (corpus / "ms.txt").write_text(
        "We analysed the colour scale.\n\nReferences\n"
        "1. Smith J. Colour vision in tumours. Nature. 2019.\n", encoding="utf-8")
    res = run([REVIEW / "enumerate_conventions.py", "--work", tmp, "--corpus", corpus,
               "--min-count", "1"])
    md = ""
    with contextlib.suppress(OSError):
        md = (tmp / "STYLE_VARIANTS.md").read_text(encoding="utf-8")
    sweeps = (WS / "paper-skills" / "paper-review" / "references" / "sweeps.md").read_text(
        encoding="utf-8")
    prompt = (WS / "paper-skills" / "prompts" / "identify_issues.prompt.md").read_text(
        encoding="utf-8")
    stale = "the references' own text that the manuscript controls"
    check("F063 the sweep text no longer promises reference-list rows, and the "
          "artifact names the reference-list gap",
          res.returncode == 0 and "Colour vision" not in md
          and stale not in sweeps and stale not in prompt
          and "references' own text" not in sweeps
          and "references' own text" not in prompt
          and "reference list" in sweeps.lower()
          and "recorded gap" in md.lower() and "reference list" in md.lower(),
          f"rc={res.returncode} stale_sweeps={stale in sweeps} "
          f"stale_prompt={stale in prompt} gap_in_artifact="
          f"{'recorded gap' in md.lower()}")


def cleanup() -> None:
    for tmp in TMPDIRS:
        for p in [tmp, *tmp.rglob("*")]:
            with contextlib.suppress(OSError):
                p.chmod(0o755 if p.is_dir() else 0o644)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_f054()
    test_f058()
    test_f059()
    test_f060()
    test_f061()
    test_f062()
    test_f063()
    cleanup()
    print(f"\n{len(FAILS)} failed")
    for name in FAILS:
        print("  FAILED:", name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

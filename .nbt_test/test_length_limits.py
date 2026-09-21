#!/usr/bin/env python3
"""The abstract/main-text length rule (M19): journal limits, relaxed margins.

Run:  python3 .nbt_test/test_length_limits.py

Asserts:
  * the base limits are the Nature Biotechnology ARTICLE numbers (abstract
    <= 150 words, main text <= 3,000 words excluding abstract, Methods,
    references and figure legends) and the pipeline's relaxed caps are the
    largest integer counts inside +15% / +25% (172 and 3,750);
  * the counting rule is "maximal runs of non-space characters, newline treated
    as space" -- `state-of-the-art` is one word, `2026` is one word, and the
    caption counter uses the same definition;
  * every prompt carries the length rule and its stage mandate (review sweep +
    coverage row, revise compression, integration porting, rewrite surfacing,
    judge formatting tier), with no unresolved @@TOKEN@@ left behind, and the
    old blanket exemption is gone;
  * the pipeline reserves M18, M19 AND M20, so discovery proposals start at M21 in
    both the caption-on and caption-off numbering sentences;
  * length is never a gate in the prompt text (the winner keeps its place);
  * the code-side proxy scan counts an abstract and a body correctly, stops the
    main text at Methods/References, skips supplementary-named files and
    renderings, reports unparseable sources as "unparsed", and refuses to count
    a document that has no manuscript shape at all;
  * the review postcheck requires both the M19 and the M18 coverage row
    (both always active), and `setup` records the source length scan in
    state.json and prints it.

`NBT_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_len", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_len"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data, encoding="utf-8")


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def all_prompts() -> dict:
    sb = Path("/tmp/nbt_len_prompt")
    return {
        "review": nb.review_prompt(sb, "r1_review", 1),
        "rewrite": nb.rewrite_prompt(sb, "r1_w1", 1),
        "revise": nb.revise_prompt(sb, "r1_a2_revise", 1),
        "integrate": nb.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"]),
        "judge": nb.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"]),
    }


# =====================================================================
# LT1 - the numbers
# =====================================================================

def test_limits():
    print()
    print("== LT1: NBT Article limits, relaxed by +15% / +25% ==")
    check("LT1 abstract base is the journal's 150 words", nb.NBT_ARTICLE_ABSTRACT_WORDS == 150,
          str(nb.NBT_ARTICLE_ABSTRACT_WORDS))
    check("LT1 main-text base is the journal's 3,000 words",
          nb.NBT_ARTICLE_MAIN_TEXT_WORDS == 3000, str(nb.NBT_ARTICLE_MAIN_TEXT_WORDS))
    check("LT1 the margins are +15% and +25%",
          nb.ABSTRACT_RELAXATION == 1.15 and nb.MAIN_TEXT_RELAXATION == 1.25,
          f"{nb.ABSTRACT_RELAXATION} {nb.MAIN_TEXT_RELAXATION}")
    check("LT1 the relaxed caps are 172 (floor of 172.5) and 3,750",
          nb.NBT_ARTICLE_ABSTRACT_CAP == 172 and nb.NBT_ARTICLE_MAIN_TEXT_CAP == 3750,
          f"{nb.NBT_ARTICLE_ABSTRACT_CAP} {nb.NBT_ARTICLE_MAIN_TEXT_CAP}")
    check("LT1 the cap helper floors, never rounds up",
          nb.lenient_word_limit(150, 1.15) == 172 and nb.lenient_word_limit(100, 1.5) == 150)
    limits = nb.length_limits()
    check("LT1 length_limits() carries base, relaxation and cap for both sections",
          limits["abstract"] == {"base": 150, "relaxation": 1.15, "cap": 172}
          and limits["main text"] == {"base": 3000, "relaxation": 1.25, "cap": 3750},
          str(limits))
    check("LT1 the provenance names the journal table",
          "Nature Biotechnology content-types table" in nb.NBT_LENGTH_LIMITS_SOURCE)


# =====================================================================
# LT2 - the counting definition
# =====================================================================

def test_counting():
    print()
    print("== LT2: words are runs of non-space characters, newline = space ==")
    cases = [("state-of-the-art", 1), ("2026", 1), ("a\nb", 2), ("a\tb", 2),
             ("  a  b ", 2), ("et al.", 2), ("", 0), ("\n\n", 0),
             ("Copy-number (CN) profiling in 2026", 5)]
    for text, want in cases:
        got = nb.count_words(text)
        check(f"LT2 count_words({text!r}) == {want}", got == want, str(got))
    caption = "Figure 1 | A state-of-the-art, 2026 result."
    check("LT2 the caption counter uses the same definition",
          nb.count_caption_words(caption) == nb.count_words(caption),
          f"{nb.count_caption_words(caption)} vs {nb.count_words(caption)}")


# =====================================================================
# LT3 - the rule travels in every prompt
# =====================================================================

def test_prompts():
    print()
    print("== LT3: the M19 rule and its stage mandate are in every prompt ==")
    texts = all_prompts()
    for name, text in texts.items():
        unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
        check(f"LT3 {name} prompt has no unresolved @@TOKEN@@", not unresolved, str(unresolved))
        check(f"LT3 {name} prompt carries the length rule",
              "ABSTRACT / MAIN-TEXT LENGTH" in text and "COUNTING RULE" in text)
        check(f"LT3 {name} prompt names both relaxed caps",
              "172" in text and "3750" in text)
        check(f"LT3 {name} prompt states the counting examples",
              '"state-of-the-art" is ONE' in text and '"2026" is ONE' in text)
        check(f"LT3 {name} prompt says length is never a gate",
              "LENGTH IS NEVER A GATE" in text)
        check(f"LT3 {name} prompt has dropped the blanket exemption",
              "LENGTH IS EXEMPT" not in text and "abstract or main-text word\n    limits, never"
              not in text)
    check("LT3 the review prompt mandates the M19 sweep and its artifact",
          "review/artifacts/M19_length.md" in texts["review"]
          and "Give M19 its own coverage row" in texts["review"])
    check("LT3 the review prompt reports over-cap sections as category-4 findings",
          "CATEGORY-4 (technical formatting) finding" in texts["review"])
    check("LT3 the revise prompt compresses without deleting content",
          "bring EVERY over-cap abstract" in texts["revise"]
          and "revised/MANUAL_STEPS.md" in texts["revise"])
    check("LT3 the integration prompt owns the porting rule",
          "FORMATTING-tier difference class" in texts["integrate"])
    check("LT3 the rewrite prompt reports instead of cutting",
          "REPORTED here, not fixed" in texts["rewrite"]
          and '"PROBLEMS SURFACED"' in texts["rewrite"])
    check("LT3 the judge prompt keeps length in the formatting tier",
          "Length is FORMATTING-tier evidence" in texts["judge"]
          and "score 0" in texts["judge"])
    on = nb.review_prompt(Path("/tmp/x"), "r1_review", 1, caption_limit=300)
    off = nb.review_prompt(Path("/tmp/x"), "r1_review", 1, caption_limit=0)
    check("LT3 the caption rule now names both narrowed places",
          "check id M19" in on and "cover letter keeps" in on
          and "blanket rule unchanged" in on)
    check("LT3 discovery proposals start at M21 with the caption rule on",
          "M21" in on and "number them from M21 upwards" in on)
    check("LT3 discovery proposals start at M21 with the caption rule off",
          "M21" in off and "M18" in off and "M19" in off and "M20" in off)


# =====================================================================
# LT4 - the code-side proxy scan
# =====================================================================

def test_scanner():
    print()
    print("== LT4: the code-side proxy scan (advisory, never a gate) ==")
    tmp = scratch("nbt_len_scan_")
    write(tmp / "ms-over.md",
          "Abstract\n\n" + ("word " * 200).strip() + "\n\nKeywords: a, b.\n\n"
          "Introduction\n\n" + ("text " * 4000).strip() + "\n\nMethods\n\n"
          + ("method " * 900).strip() + "\n\nReferences\n\n1. Someone 2026.\n")
    write(tmp / "ms-ok.md",
          "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
          + ("text " * 1000).strip() + "\n\nMethods\n\nx\n")
    write(tmp / "supp-extra.md", "Abstract\n\n" + ("word " * 500).strip() + "\n")
    write(tmp / "figure.pdf", "%PDF-1.4\n")
    write(tmp / "legacy.doc", "old binary\n")
    write(tmp / "cover-letter.md",
          "Dear Editor,\n\n" + ("persuade " * 400).strip()
          + "\n\nRelated manuscripts: none.\nSuggested reviewers: Alice, Bob.\n"
            "\nSincerely,\nJane Doe\n")
    write(tmp / "short-cover.md", "Dear Editor,\n\nWe submit our manuscript.\n\nSincerely,\nJane\n")
    info = nb.scan_lengths_in_sources([(tmp, "", ())])
    rows = {(r["document"], r["section"]): r for r in info["rows"]}
    over = rows.get(("ms-over.md", "abstract"))
    check("LT4 the over-cap abstract is counted", over and over["words"] == 200,
          str(over))
    check("LT4 the over-cap abstract is flagged", over and over["over_limit"] is True)
    body = rows.get(("ms-over.md", "main text"))
    check("LT4 the main text stops at Methods and excludes it",
          body and body["words"] == 4000, str(body))
    check("LT4 the over-cap main text is flagged", body and body["over_limit"] is True)
    ok_body = rows.get(("ms-ok.md", "main text"))
    ok_abs = rows.get(("ms-ok.md", "abstract"))
    check("LT4 a within-cap manuscript is counted and not flagged",
          ok_abs and ok_abs["words"] == 100 and not ok_abs["over_limit"]
          and ok_body and ok_body["words"] == 1000 and not ok_body["over_limit"],
          f"{ok_abs} {ok_body}")
    check("LT4 the Keywords line ends the abstract (not counted into it)",
          over and over["words"] == 200)
    check("LT4 supplementary-named files are skipped",
          any(d.endswith("supp-extra.md") for d in info["skipped"])
          and not any(r["document"].endswith("supp-extra.md") for r in info["rows"]))
    check("LT4 renderings are skipped, not counted or 'unparsed'",
          any(d.endswith("figure.pdf") for d in info["skipped"])
          and not any(d.endswith("figure.pdf") for d in info["unparsed"]))
    check("LT4 a legacy .doc is reported as unparsed",
          any(d.endswith("legacy.doc") for d in info["unparsed"]))
    cover = rows.get(("cover-letter.md", "cover letter"))
    short = rows.get(("short-cover.md", "cover letter"))
    check("LT4 a cover letter gets its own M19 row, never a 'main text' row",
          cover is not None and short is not None
          and not any(r["section"] == "main text" and r["document"].endswith("cover.md")
                      for r in info["rows"]))
    check("LT4 the persuading part is counted (disclosures/signature excluded)",
          cover and cover["words"] == 400 and cover["within_preference"] is True,
          str(cover))
    check("LT4 a too-short cover letter is outside the user's preference, not a cap",
          short and short["words"] < 300 and short["within_preference"] is False
          and short["under_preference"] is True, str(short))
    check("LT4 the cover-letter row names its provenance (user preference, no NBT limit)",
          cover and "not an NBT limit" in cover["note"] and "no cover-letter word limit"
          in cover["source"])
    note = nb.length_note(info)
    check("LT4 the one-line note reports the over-cap sections and the caps",
          "OVER" in note and "172" in note and "3750" in note, note)
    check("LT4 the note never claims a gate",
          "advisory only -- never a gate" in note)
    check("LT4 the scan carries its provenance",
          "Nature Biotechnology content-types table" in info["source"])
    check("LT4 the note names the cover-letter preference",
          "cover letter" in note and "user's 300-500-word preference" in note)
    check("LT4 an empty scan is 'not verified', not a failure",
          "not verified" in nb.length_note(None))
    only_pdf = scratch("nbt_len_pdf_")
    write(only_pdf / "manuscript.pdf", "%PDF-1.4\n")
    pdf_info = nb.scan_lengths_in_sources([(only_pdf, "", ())])
    check("LT4 a PDF-only package is reported as needing manual counting",
          pdf_info["needs_manual"] and "not verified" in nb.length_note(pdf_info),
          str(pdf_info)[:200])


# =====================================================================
# LT5 - the orchestrator requires M19 and records the source scan
# =====================================================================

def test_orchestrator_wiring():
    print()
    print("== LT5: M19 coverage is mandatory and setup records the scan ==")
    tmp = scratch("nbt_len_pc_")
    sb = tmp / "runs" / "r1_a2_review"
    write(sb / "base" / "ms.md", "text\n")
    write(sb / "review" / "artifacts" / "M1_acronyms.md", "| row |\n|---|\n")
    ctx = type("C", (), {"cfg": {}})()

    def coverage(include_m19=True):
        rows = [{"check": c, "disposition": "clean -- basis: x"} for c in
                [f"M{i}" for i in range(1, 18)] + [f"J{i}" for i in range(1, 5)]]
        rows.append({"check": "M18", "disposition": "legend lengths recorded"})
        rows.append({"check": "M20", "disposition": "formatting rows disposed"})
        for cid in ("M21", "M22", "M23", "M24"):      # adopted checks (2026-09-22)
            rows.append({"check": cid, "disposition": f"clean -- basis: fixture {cid}"})
        if include_m19:
            rows.append({"check": "M19", "disposition": "0 findings"})
        return rows

    fj = {"submission_dir": "./base", "findings": [{"id": "F-001", "check": "M1"}],
          "artifacts": {}, "coverage": coverage()}
    errs, warns = [], []
    nb.check_review_contract(ctx, sb, fj, errs, warns)
    check("LT5 a review with an M19 coverage row passes the contract", not errs, str(errs))
    fj_missing = dict(fj, coverage=coverage(include_m19=False))
    errs2, warns2 = [], []
    nb.check_review_contract(ctx, sb, fj_missing, errs2, warns2)
    check("LT5 a review without the M19 coverage row fails the contract",
          any("M19" in e for e in errs2), str(errs2))

    source = tmp / "source"
    write(source / "manuscript-b.md",
          "Abstract\n\n" + ("word " * 200).strip() + "\n\nIntroduction\n\n"
          + ("text " * 100).strip() + "\n\nMethods\n\nx\n")
    root = tmp / "root"
    proc = subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "setup",
                           "--source", str(source), "--root", str(root)],
                          capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    check("LT5 setup succeeds", proc.returncode == 0, out[-200:])
    check("LT5 setup prints the length scan and the caps",
          "abstract/main-text length" in out and "172" in out and "3750" in out,
          out[-400:])
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    scan = state.get("original_lengths") or {}
    rows = {(r["document"], r["section"]): r for r in scan.get("rows", [])}
    check("LT5 state.json records the source scan",
          (("manuscript-b.md", "abstract") in rows
           and rows[("manuscript-b.md", "abstract")]["words"] == 200
           and rows[("manuscript-b.md", "abstract")]["over_limit"] is True),
          str(scan)[:200])


def main() -> int:
    sections = (("limits", test_limits),
                ("counting", test_counting),
                ("prompts", test_prompts),
                ("scanner", test_scanner),
                ("wiring", test_orchestrator_wiring))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL LENGTH-LIMIT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regression checks for the paper-skills candidates of the 2026-11-22 11:28
fix-bugs wave (batch O).

Run: python3 .paper_test/test_fix_wave1_O_skills.py

  F109 count_words.py subtracts EVERY caption on one .tex line (M19 parity)
  F114 a nobiliary-particle reference ("van der Waals, ...") is its own entry
  F123 revision_token.py caps the walk at MAX_TREE_DEPTH like the pipeline
  F190 an acronym-first "IQR (interquartile range)" is a definition and M1b
  F191 "Table 1 shows ..." prose does not switch the number context to table
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    p = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(p)
    return p


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script)]
                          + [str(a) for a in args],
                          capture_output=True, text=True, timeout=300)


def corpus_work(prefix, files):
    tmp = scratch(prefix)
    work, out = tmp / "work", tmp / "out"
    (work / "corpus").mkdir(parents=True)
    for name, text in files.items():
        (work / "corpus" / name).write_text(text, encoding="utf-8")
    return work, out


def test_f109_two_captions():
    tmp = scratch("f109")
    tex = tmp / "paper.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\section{Introduction}\nIntro words one two.\n"
        "\\section{Results}\nBody words here four five.\n"
        "\\begin{figure}\\caption{First legend text.}"
        "\\caption{Second legend text here.}\\end{figure}\n"
        "\\end{document}\n", encoding="utf-8")
    p = run("count_words.py", tex, "--venue-profile", "nature-biotechnology",
            "--article-type", "article")
    m = re.search(r"main text:\s*(\d+)\s*words.*?(\d+)\s*caption word\(s\) subtracted",
                  p.stdout)
    check("F109 count_words subtracts both captions on one line",
          bool(m) and m.group(2) == "7", p.stdout[-300:])
    # Parity with the pipeline's M19 scan on the same file.
    import importlib.util
    spec = importlib.util.spec_from_file_location("pp", WS / "paper_pipeline.py")
    pp = importlib.util.module_from_spec(spec)
    sys.modules["pp"] = pp
    spec.loader.exec_module(pp)
    lines, caps, absend = pp._tex_length_scan(tex.read_text(encoding="utf-8"))
    rows = pp._length_rows_for_lines(lines, tex.name, caps, absend)
    main = next((r for r in rows if r.get("section") == "main text"), None)
    check("F109 count_words agrees with the pipeline M19 main-text count",
          bool(m) and bool(main) and int(m.group(1)) == int(main["words"]),
          f"count_words={m.group(1) if m else None} pipeline={main}")
    # R01: the caption KIND lives in the `\captionof{<kind>}` token itself;
    # the F109 loop probed the text BEFORE the caption, so both kinds were None
    # and a table caption outside a table float was subtracted as a legend.
    import importlib.util
    cw_spec = importlib.util.spec_from_file_location("cw_r01", SCRIPTS / "count_words.py")
    cw = importlib.util.module_from_spec(cw_spec)
    sys.modules["cw_r01"] = cw
    cw_spec.loader.exec_module(cw)
    kinds = [cw.tex_lines(x)[2] for x in (
        r"\captionof{figure}{A caption line.}",
        r"\captionof{table}{A table caption.}",
        r"\captionof*{table}{A table caption.}")]
    check("R01 \\captionof keeps its declared kind",
          kinds == [[(0, "figure")], [(0, "table")], [(0, "table")]], kinds)
    table_tex = tmp / "table_caption.tex"
    table_tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\section{Introduction}\nIntro one two.\n"
        "\\section{Results}\nBody three four.\n"
        "\\captionof{table}{A table caption here.}\n\\end{document}\n",
        encoding="utf-8")
    p2 = run("count_words.py", table_tex, "--venue-profile", "nature-biotechnology",
             "--article-type", "article")
    m2 = re.search(r"main text:\s*(\d+)\s*words", p2.stdout)
    check("R01 a table caption outside a float is not subtracted as a legend",
          bool(m2) and m2.group(1) == "10", p2.stdout[-300:])


def test_f114_nobiliary_entry():
    work, out = corpus_work("f114", {"refs.md.txt": (
        "# References\n\n"
        "Smith, J. (2019). A study of things. Nature, 570, 1-9.\n"
        "van der Waals, J. (2020). Another study of forces. Science, 11, 20-30.\n"
        "Brown, L. (2021). Third paper. Cell, 12, 33-44.\n")})
    p = run("extract_citations.py", "--work", work, "--out", out)
    data = json.loads((out / "artifacts" / "M2_citations.json").read_text(encoding="utf-8"))
    entries = data.get("ref_entries") or []
    check("F114 the nobiliary-particle entry is kept as its own row",
          len(entries) == 3
          and any(str(e.get("text", "")).startswith("van der Waals")
                  for e in entries),
          f"entries={[(e.get('line'), str(e.get('text'))[:30]) for e in entries]}"
          f" rc={p.returncode}")


def test_f123_depth_cap():
    tmp = scratch("f123")
    deep = tmp / "deep"
    for _ in range(250):
        deep = deep / "d"
    deep.mkdir(parents=True)
    (deep / "ms.tex").write_text("x", encoding="utf-8")
    p = run(SCRIPTS.parent.parent / "paper-revise" / "scripts" / "revision_token.py",
            tmp / "deep")
    out = p.stdout + p.stderr
    check("F123 the script records the depth gap instead of tokenising",
          p.returncode == 0 and "payload files: 0" in out
          and f"{200}-level depth cap" in out, out[-300:])
    import importlib.util
    spec = importlib.util.spec_from_file_location("pp2", WS / "paper_pipeline.py")
    pp = importlib.util.module_from_spec(spec)
    sys.modules["pp2"] = pp
    spec.loader.exec_module(pp)
    twin = pp.revision_token_for_dir(tmp / "deep")
    check("F123 the script and the pipeline twin agree on the empty token",
          twin.get("token") == "" and twin.get("files") == 0, repr(twin))


def test_f190_acronym_first():
    work, out = corpus_work("f190", {"main.md.txt": (
        "# Results\n\n"
        "The IQR (interquartile range) was 12 points.\n\n"
        "The interquartile range was wide in the cohort.\n")})
    run("extract_acronyms.py", "--work", work, "--out", out)
    doc = json.loads((out / "artifacts" / "M1_acronyms.json").read_text(encoding="utf-8"))
    recs = doc.get("acronyms") if isinstance(doc, dict) else doc
    rec = next((r for r in recs or [] if r.get("acronym") == "IQR"), None)
    check("F190 the acronym-first definition is recorded",
          bool(rec) and "interquartile range" in (rec.get("expansions") or [])
          and rec.get("defined_at_first_use") != "never", repr(rec))
    check("F190 M1b sees the later long-form use",
          bool(rec) and rec.get("long_form_after_first_use_total") == 1, repr(rec))


def test_f191_table_sentence_is_prose():
    work, out = corpus_work("f191", {"main.md.txt": (
        "# Results\n\n"
        "The cohort had a mean age of 54 years (p = 0.021).\n\n"
        "Table 1 shows the baseline characteristics of the cohort.\n\n"
        "The treatment effect remained significant (p = 0.034).\n")})
    run("extract_numbers.py", "--work", work, "--out", out)
    doc = json.loads((out / "artifacts" / "M4_numbers.json").read_text(encoding="utf-8"))
    pvals = [occ for m in doc.get("metrics") or []
             if m.get("label") == "p-value" and m.get("value") == "0.034"
             for occ in m.get("occurrences") or []]
    check("F191 a 'Table N <verb>' sentence does not switch the context",
          bool(pvals) and all(o.get("context") == "main text" for o in pvals),
          repr(pvals))


def main() -> int:
    test_f109_two_captions()
    test_f114_nobiliary_entry()
    test_f123_depth_cap()
    test_f190_acronym_first()
    test_f191_table_sentence_is_prose()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL O-BATCH SKILL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for tmp in TMPDIRS:
            shutil.rmtree(tmp, ignore_errors=True)

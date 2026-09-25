#!/usr/bin/env python3
"""Hard-case probes for the v0.4 heuristics (blank-line lists, wrapped entries,
noise control). Not part of the acceptance gate, but they guard the two rules
most likely to misfire: the reference-region end heuristic and the widened
gene-symbol detector.

Usage: python3 tests/probe_hardcases.py --skill-root . --run-dir /tmp/paper_hard
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

FAILS = []


def run(root, script, *args):
    return subprocess.run(
        [sys.executable, os.path.join(root, "paper-review", "scripts", script)] + list(args),
        capture_output=True, text=True)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def analyse(root, case, files):
    sub, work, out = (os.path.join(case, x) for x in ("sub", "work", "out"))
    shutil.rmtree(case, ignore_errors=True)
    for name, text in files.items():
        write(os.path.join(sub, name), text)
    run(root, "convert_corpus.py", "--submission", sub, "--work", work)
    for script in ("extract_acronyms.py", "extract_citations.py", "extract_numbers.py"):
        run(root, script, "--work", work, "--out", out)
    return work, out


def check(cid, desc, ok, detail=""):
    print("%-4s %-5s %-52s %s" % ("PASS" if ok else "FAIL", cid, desc, detail[:110]))
    if not ok:
        FAILS.append(cid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-root", required=True)
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    root, base = os.path.abspath(args.skill_root), os.path.abspath(args.run_dir)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)

    # H1: blank-line-separated numbered list must not be truncated
    work, out = analyse(root, os.path.join(base, "h1"), {"main.md":
        "Results\nWe saw n = 7 samples [1].\n\nReferences\n\n"
        "1. A. One. 2019.\n\n2. B. Two. 2020.\n\n3. C. Three. 2021.\n\n"
        "Figure legends\nFig. 1 | Treg counts with n = 12 samples [2].\n"})
    m2 = load(os.path.join(out, "artifacts", "M2_citations.json"))
    m4 = read(os.path.join(out, "artifacts", "M4_numbers.md"))
    check("H1", "blank-line-separated reference list kept in full",
          len(m2.get("ref_entries", [])) == 3 and "| n | 12 |" in m4,
          "refs=%d" % len(m2.get("ref_entries", [])))

    # H2: wrapped entry (continuation line without a year) must not end the list
    work, out = analyse(root, os.path.join(base, "h2"), {"main.md":
        "Results\nn = 7 [1].\n\nReferences\n"
        "1. Smith J, Jones A, Lee B, Park C, Kim D, et al. A very long title\n"
        "without any year on the continuation line.\n"
        "Nature. 2019;570:1-9.\n"
        "2. Doe A. Another study. Science. 2020;11:20-30.\n\n"
        "Figure legends\nFig. 1 | Design with n = 12 [2].\n"})
    m2 = load(os.path.join(out, "artifacts", "M2_citations.json"))
    m4 = read(os.path.join(out, "artifacts", "M4_numbers.md"))
    check("H2", "wrapped reference entry does not end the list",
          len(m2.get("ref_entries", [])) == 2 and "| n | 12 |" in m4,
          "refs=%d" % len(m2.get("ref_entries", [])))

    # H3: gene-symbol detector must not fill the artifact with measurement nouns
    para = ("Methods\nCells were seeded at week12 and day3 in group1 of phase2. "
            "Samples from patient5 and batch2 were run at step2 of round3. "
            "Expression of p53, stat3, mbd3 and CD8 was measured.\n")
    work, out = analyse(root, os.path.join(base, "h3"), {"m.md": para})
    rows = {r["acronym"] for r in load(os.path.join(out, "artifacts", "M1_acronyms.json"))}
    noise = sorted(t for t in rows if t.lower() in
                   {"week12", "day3", "group1", "phase2", "patient5", "batch2", "step2", "round3"})
    check("H3", "gene detector adds no measurement-noun noise", not noise,
          "noise=%s kept=%s" % (noise, sorted(t for t in rows if t in ("p53", "stat3", "mbd3", "CD8"))))

    # H4: a real citation after a measurement noun is still a citation
    work, out = analyse(root, os.path.join(base, "h4"), {"paper.md":
        "Results\nAs reported in 12 patients [12], the effect was large.\n\n"
        "References\n1. A. One. 2019.\n"})
    m2 = load(os.path.join(out, "artifacts", "M2_citations.json"))
    check("H4", "citation after a measurement noun still detected",
          any(c["raw"] == "[12]" for c in m2.get("callouts", [])),
          "callouts=%s" % [c["raw"] for c in m2.get("callouts", [])])

    print("\n%d hard case(s) failed%s" % (len(FAILS), (": " + ", ".join(FAILS)) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

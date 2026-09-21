#!/usr/bin/env python3
"""extract_occurrences.py — term/value occurrence enumeration.

Used by BOTH skills:
  nbt-review  — M8 terminology-consistency sweep (term variants, one-term-per-
                entity, scRNAseq vs scRNA-seq style variants, species italics
                candidates, decimal formats)
  nbt-revise  — P1 propagation: enumerate EVERY occurrence of a corrected
                value/label/term BEFORE editing, so propagation is by
                enumeration, never by attention.

Modes:
  --term "scRNA-seq"        exact + fuzzy variants (case, hyphens, plural)
  --value "0.031"           numeric value with equivalent notations
  --variants-file FILE      JSON propagation-map input. Accepted shapes:
                            {"canonical": ..., "variants": [...]} (single map),
                            [{"canonical": ..., "variants": [...]}, ...], or
                            ["term", "other term", ...].

Output: WORK/occurrences_<slug>.md + .json with one row per occurrence
(multi-target runs get a short hash suffix so two runs cannot overwrite each
other). Use --out DIR to write the artifacts somewhere else.

stdlib-only. Usage:
  python extract_occurrences.py --work ./review/work --term "scRNA-seq"
  python extract_occurrences.py --work ./revised/work --value "0.031"
  python extract_occurrences.py --work ./revised/work --value "0.021" --value "0.031"
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata


def slugify(s):
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:40] or "term"


def variant_pattern(term, mode):
    """Build a regex matching the term plus common typographic variants."""
    esc = re.escape(term)
    if mode == "value":
        # 0.031 ~ .031 ~ 0.0310 ~ 3.1e-2
        num = term.replace(",", ".")
        pats = [re.escape(num)]
        if num.startswith("0."):
            pats.append(re.escape(num[1:]))           # .031
        if num.startswith("."):
            pats.append("0" + re.escape(num))         # 0.031
        stripped = num.rstrip("0").rstrip(".") if "." in num else num
        if stripped and stripped != num:
            pats.append(re.escape(stripped))
        try:
            v = float(num)
            sci = "%.1e" % v
            mant, exp = sci.split("e")
            pats.append(re.escape(mant + "e" + exp))
            # "%.1e" always pads the exponent to two digits (3.1e-02) while
            # manuscripts usually write 3.1e-2 -- the short form (and the
            # uppercase E) must be enumerated too, or those occurrences of the
            # value are invisible to the M4 number sweep.
            pats.append(re.escape(mant + "E" + exp))
            pats.append(re.escape(mant + "e" + str(int(exp))))
            pats.append(re.escape(mant + "E" + str(int(exp))))
            pats.append(re.escape(mant + " × 10^" + str(int(exp))))
            # The multiplication sign is also written without the caret and
            # with a U+2212 minus ("3.1 × 10−2"); those occurrences were
            # invisible to the M4 sweep.
            pats.append(re.escape(mant + " × 10" + str(int(exp))))
            for mul in (" × 10^", " × 10"):
                pats.append(re.escape(mant + mul + "\u2212" + str(abs(int(exp)))))
            # Unicode superscripts ("3.1 × 10⁻²") and the LaTeX \times forms
            # ("3.1 \times 10^{-2}") are the same value in other manuscripts.
            _sup = str(int(exp)).translate(str.maketrans(
                "0123456789-", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207b"))
            pats.append(re.escape(mant + " × 10" + _sup))
            for mul in (r" \times 10^", r" \times 10^{"):
                close = r"\}" if mul.endswith("{") else ""
                pats.append(re.escape(mant + mul + str(int(exp))) + close)
                pats.append(re.escape(mant + mul + "\u2212" + str(abs(int(exp)))) + close)
        except ValueError:
            pass
        # A trailing comma is only a separator when no digit follows: without
        # the ",digit" guard the value 5 also matched inside "5,000".
        return re.compile(r"(?<![\w.])(" + "|".join(sorted(set(pats), key=len, reverse=True))
                          + r")(?![\w]|,\d)")
    # term mode: allow hyphen/space interchange, case-insensitive, optional 's'
    base = re.escape(term)
    hyphen_ins = base.replace(r"\-", r"[\s\-]?")
    pat = r"(?i)\b" + hyphen_ins + r"(?:es|s)?\b"
    return re.compile(pat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--term", action="append", default=None, help="term to enumerate (repeatable)")
    ap.add_argument("--value", action="append", default=None,
                    help="numeric value to enumerate (repeatable)")
    ap.add_argument("--variants-file", action="append", default=None,
                    help="JSON propagation-map input (repeatable)")
    ap.add_argument("--out", default=None, help="artifact dir (default: WORK)")
    args = ap.parse_args()
    work = os.path.abspath(args.work)
    corpus = os.path.join(work, "corpus")
    if not os.path.isdir(corpus):
        print("ERROR: corpus dir not found: %s. Run convert_corpus.py first." % corpus)
        sys.exit(2)

    targets = []
    for term in (args.term or []):
        targets.append(("term", term))
    for value in (args.value or []):
        targets.append(("value", value))
    for vf in (args.variants_file or []):
        try:
            with open(vf, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            # Malformed agent input must use the tool's error style, not a
            # traceback out of the middle of target collection.
            print("ERROR: cannot read variants file %s: %s" % (vf, e))
            sys.exit(2)
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, str):
                targets.append(("term", item))
            elif isinstance(item, dict):
                canonical = item.get("canonical") or item.get("term") or item.get("value")
                if canonical:
                    targets.append(("term", str(canonical)))
                variants = item.get("variants") or item.get("forms") or []
                if isinstance(variants, str):
                    variants = [variants]
                for v in variants:
                    if v:
                        targets.append(("term", str(v)))
            elif isinstance(item, list):
                for v in item:
                    if v:
                        targets.append(("term", str(v)))
    seen = set()
    targets = [t for t in targets if not (t in seen or seen.add(t))]
    if not targets:
        print("ERROR: give --term, --value, or --variants-file")
        sys.exit(2)

    all_results = []
    for mode, target in targets:
        pat = variant_pattern(target, mode)
        results = []
        if os.path.isdir(corpus):
            for fname in sorted(os.listdir(corpus)):
                if not fname.endswith(".txt"):
                    continue
                lines = open(os.path.join(corpus, fname), encoding="utf-8",
                             errors="replace").read().split("\n")
                for li, raw in enumerate(lines, 1):
                    for m in pat.finditer(raw):
                        results.append({"file": fname, "line": li,
                                        "match": m.group(0),
                                        "exact": m.group(0) == target,
                                        "excerpt": raw.strip()[:140]})
        all_results.append({"target": target, "mode": mode, "n": len(results),
                            "occurrences": results})

    # write artifacts (multi-target runs get a hash suffix so runs cannot collide)
    if len(targets) == 1:
        stem = slugify(targets[0][1])
    else:
        joined = "|".join("%s:%s" % (m, t) for m, t in targets)
        stem = "%s_%s" % (slugify(targets[0][1]),
                          hashlib.md5(joined.encode("utf-8")).hexdigest()[:6])
    out_dir = os.path.abspath(args.out) if args.out else work
    os.makedirs(out_dir, exist_ok=True)
    out_md = os.path.join(out_dir, "occurrences_%s.md" % stem)
    out_js = os.path.join(out_dir, "occurrences_%s.json" % stem)
    md = ["# Occurrence enumeration (artifact)", ""]
    for block in all_results:
        md.append("## Target: %r (%s) — %d occurrences" % (
            block["target"], block["mode"], block["n"]))
        md.append("")
        md.append("| file | line | match | exact? | excerpt |")
        md.append("|---|---|---|---|---|")
        for o in block["occurrences"]:
            md.append("| %s | %d | %s | %s | %s |" % (
                o["file"], o["line"], o["match"].replace("|", "\\|"),
                "Y" if o["exact"] else "N",
                o["excerpt"].replace("|", "\\|")))
        md.append("")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(out_js, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    for block in all_results:
        print("Target %r: %d occurrences (%d inexact variants)" % (
            block["target"], block["n"],
            sum(1 for o in block["occurrences"] if not o["exact"])))
    print("Artifacts: %s, %s" % (out_md, out_js))


if __name__ == "__main__":
    main()

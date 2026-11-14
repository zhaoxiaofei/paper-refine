#!/usr/bin/env python3
"""extract_occurrences.py — term/value occurrence enumeration.

Used by BOTH skills:
  paper-review  — M8 terminology-consistency sweep (term variants, one-term-per-
                entity, scRNAseq vs scRNA-seq style variants, species italics
                candidates, decimal formats)
  paper-revise  — P1 propagation: enumerate EVERY occurrence of a corrected
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
  python extract_occurrences.py --work ./guided_review/work --term "scRNA-seq"
  python extract_occurrences.py --work ./revised/work --value "0.031"
  python extract_occurrences.py --work ./revised/work --value "0.021" --value "0.031"
"""
import argparse
import hashlib
from decimal import Decimal, InvalidOperation
import json
import os
import re
import sys
import unicodedata

from pathlib import Path

# Allow direct execution and import by filename.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from evidence_names import EVIDENCE_DIRNAMES, is_evidence as _is_evidence
finally:
    sys.path.pop(0)

# Role words are NAME TOKENS, not substrings: a manuscript named
# `immune_response.md` or `biofeedback_results.txt` is real prose, while a role
# word preceded by a role qualifier (`reviewer_response`, `author_feedback`)
# still names the authors' reply / the editors' letter.
_NON_MANUSCRIPT_RE = re.compile(
    r"(?<![a-z])(?:feedbacks?(?:[-_ ]?(?:form|report|letter|comments?|summary|"
    r"to[-_ ]?authors))*|"
    r"(?:referees?|reviewers?)(?:[-_ ]?(?:comments?|reports?|critiques?|forms?))*|"
    r"(?<![a-z_])editors?(?:[-_ ]?(?:comments?|decisions?|reports?|letters?|"
    r"notices?|emails?|critiques?|forms?))|"
    r"editorial|decision[_ \-]*(?:letter|notice|email))(?![a-z])", re.I)
# The pipeline's `AUTHORED_REPLY_NAME_RE` is a bare role WORD, so
# `ReviewerResponse.md` and `reviewerresponse.md` are the authors' reply there.
# The boundary form here missed both and swept reviewer prose as the manuscript.
# The science-compound carve-out below still protects `immune_response.md`.
_REPLY_RE = re.compile(
    r"(?:responses?|repl(?:y|ies)|rebuttal|point[-_ ]?by[-_ ]?point)",
    re.I)


def is_non_manuscript(name: str) -> bool:
    return _is_evidence(name, _NON_MANUSCRIPT_RE, _REPLY_RE)


# A reference list is quoted bibliography, not the authors' prose: an
# occurrence inside a cited title must never be enumerated as a propagation
# target (F275).  The sibling extractors already skip the region and a
# reference-role file; this enumerator did neither.
REF_HEAD_RE = re.compile(
    r"^\s*(?:"
    r"\\(?:section|subsection|chapter)\*?\s*\{\s*(?:references?|bibliography)\s*\}\s*(?:\\label\{[^{}]*\})?"
    r"|\\begin\{thebibliography\}"
    r"|\\(?:bibliography|printbibliography)\b.*"
    r"|(?:#{1,6}\s*)?(?:\*{1,2}|_{1,2})?\s*(?:\d+(?:\.\d+)*[.)]?\s*)?"
    r"(?:references?|bibliography|reference\s+list|literature\s+cited)"
    r"\s*(?:\*{1,2}|_{1,2})?\s*[:.\u2014\u2013-]?\s*"
    r")\s*(?:%.*)?$", re.I)
REF_END_RE = re.compile(
    r"^\s*(?:\\end\{thebibliography\}|\\(?:section|subsection|chapter)\*?\s*\{|"
    r"#{1,6}\s+\S|"
    r"(?:abstract|introduction|background|methods?|materials and methods|"
    r"results?|discussion|conclusions?|acknowledg\w*|author contributions?|"
    r"data availability|code availability|competing interests?|"
    r"conflicts? of interest|funding|supplementary(?:\s+\w+)?|"
    r"figure legends?|tables?)\s*(?::|\s*$))", re.I)
NUM_ENTRY_RE = re.compile(r"^\s*(?:\[?\d{1,3}[\].)]|\d{1,3}[.)])\s+")
REF_ROLE_RE = re.compile(r"\brefs?\b|\breferences?\b")


def is_reference_file(name: str) -> bool:
    """A bibliography file by name, with the siblings' role-word rule."""
    raw = os.path.basename(name or "").lower()
    base = re.sub(r"\.(?:txt|md)$", "", raw)
    base = re.sub(r"\.[a-z0-9]{1,5}$", "", base)
    return bool(REF_ROLE_RE.search(base) or "bibliograph" in base
                or re.search(r"\.bib(\.|$)", raw))


def find_reference_region(lines):
    """(start, end) line indices of a reference list, or None."""
    start = None
    for i, ln in enumerate(lines):
        if REF_HEAD_RE.match(ln.strip()):
            # The LAST heading is the real list (a table-of-contents line or a
            # superseded list must not latch the sweep onto the wrong region).
            start = i + 1
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if not s or NUM_ENTRY_RE.match(s):
            continue  # blank lines and numbered entries are inside the list
        if REF_END_RE.match(s):
            end = j
            break
    return start, end


def slugify(s):
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:40] or "term"


def variant_pattern(term, mode):
    """Build a regex matching the term plus common typographic variants."""
    esc = re.escape(term)
    if mode == "value":
        # 0.031 ~ .031 ~ 0.0310 ~ 3.1e-2. A COMMA is a thousands separator,
        # never a decimal point: reading "1,234" as 1.234 generated an
        # alternative spelling for a different magnitude.
        num = term
        # U+2212 MINUS SIGN and ASCII '-' are the same sign in typeset text, so
        # a target written in one spelling must enumerate the other (F278).
        sign_forms = []
        if num.startswith("\u2212"):
            sign_forms.append("-" + num[1:])
            num = sign_forms[0]
        elif num.startswith("-"):
            sign_forms.append("\u2212" + num[1:])
        # The LITERAL spelling is always one of the forms: with a thousands
        # separator (`1,234`) the decimal-normalised `num` is "1.234", which
        # never matches the text that carries the number, so the sweep reported
        # an occurrence the manuscript still carries as missing.
        pats = [re.escape(num), esc]
        pats.extend(re.escape(form) for form in sign_forms if form != num)
        if num.startswith("0."):
            pats.append(re.escape(num[1:]))           # .031
        if num.startswith("."):
            pats.append("0" + re.escape(num))         # 0.031
        stripped = num.rstrip("0").rstrip(".") if "." in num else num
        if stripped and stripped != num:
            pats.append(re.escape(stripped))
        if "." in num:
            # A trailing zero after the decimal point is the same value
            # ("0.031" ~ "0.0310", ".031" ~ ".0310"): the header has always
            # promised the padded spelling, but the trailing-digit guard below
            # stops the short pattern from matching inside a padded one and no
            # padded pattern existed, so `0.0310` was reported as an occurrence
            # the manuscript no longer carries.
            pats.append(re.escape(num) + "0*")
            if num.startswith("0."):
                pats.append(re.escape(num[1:]) + "0*")
        # A grouped integer (`1,234`) is the same value as its plain form.
        # float() rejects the comma, so the plain spelling has to be added
        # explicitly.
        grouped = bool(re.fullmatch(r"[+\-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", num))
        norm = num.replace(",", "") if grouped else num
        if norm != num:
            pats.append(re.escape(norm))
        # The other direction: a plain integer target must also enumerate its
        # comma-grouped spelling ("1234" ~ "1,234").  The leading guard keeps
        # the plain digits from matching inside the grouped form, so without
        # this pattern the other spelling was invisible (F278).
        if not grouped and re.fullmatch(r"[+\-]?\d{4,}", num):
            _sign = num[0] if num[0] in "+-" else ""
            _digits = num[len(_sign):]
            if not _digits.startswith("0"):
                _grouped = _sign + format(int(_digits), ",")
                pats.append(re.escape(_grouped))
                if _sign == "-":
                    pats.append(re.escape("\u2212" + format(int(_digits), ",")))
                elif not _sign:
                    # The explicit plus sign is the same value as the plain one.
                    pats.append(r"\+" + re.escape(_grouped))
        try:
            # Decimal, not float: `float("9007199254740993")` is
            # 9007199254740992, so the generated scientific spelling named a
            # DIFFERENT integer (F59). Decimal keeps the written value exact.
            _dec = Decimal(norm.replace("\u2212", "-"))
        except InvalidOperation:
            _dec = None
        if _dec is not None and _dec.is_finite():
            sci = format(_dec, "e")
            mant, exp = sci.split("e")
            exp_i = int(exp)
            # Decimal preserves the written integer's trailing zeros
            # (`1500` -> `1.500e+3`); the shortest exact mantissa is the one
            # manuscripts write (`1.5e+3`). The `0*` padding below still
            # enumerates the longer spellings.
            if "." in mant:
                mant = mant.rstrip("0").rstrip(".")
            # An INTEGER mantissa may not be padded with zeros: `5` + `0*` +
            # `e+0` matched `50e+00`, a different value (F55). Only a written
            # decimal point makes trailing zeros value-preserving.
            mant_pad = "0*" if "." in mant else ""
            pats.append(re.escape(mant) + "e" + re.escape(exp))
            # The same value written in plain decimal is an equivalent
            # notation ("1e-3" ~ "0.001"), and the mode promises to
            # enumerate equivalents. Decimal keeps the written value exact.
            if "e" in str(norm).lower():
                try:
                    dec = format(_dec, "f")
                except (InvalidOperation, ValueError):
                    dec = ""
                if dec and dec not in ("0", "0.0"):
                    pats.append(re.escape(dec))
                    if "." in dec:
                        short = dec.rstrip("0").rstrip(".")
                        if short and short != dec:
                            pats.append(re.escape(short))
            # Manuscripts write "e+2" and "3.10e+2" as well as the padded
            # "e+02"; all are the same value and must be enumerated.
            short = ("+" if exp.startswith("+") else "") + str(exp_i)
            padded = ("+" if exp_i >= 0 else "-") + f"{abs(exp_i):02d}"
            for e_char in ("e", "E"):
                pats.append(re.escape(mant) + mant_pad + re.escape(e_char + short))
                # The UNSIGNED short form (`3.1e2`, `3.1E2`) is the same value
                # as `3.1e+2`: adding the sign must not drop it.
                pats.append(re.escape(mant) + mant_pad + re.escape(e_char + str(exp_i)))
                # %.2e pads the exponent to two digits (`2.15e-02`).
                pats.append(re.escape(mant) + mant_pad + re.escape(e_char + padded))
                pats.append(re.escape(mant) + mant_pad + re.escape(e_char + exp))
            pats.append(re.escape(mant) + mant_pad + re.escape(" × 10^" + str(exp_i)))
            # The multiplication sign is also written without the caret and
            # with a U+2212 minus ("3.1 × 10−2"); those occurrences were
            # invisible to the M4 sweep. Exponent 0 is the exception: "3 × 100"
            # is three hundred, not 3, so only the caret/superscript forms
            # ("3 × 10^0"/"3 × 10⁰") name that value.
            if exp_i != 0:
                pats.append(re.escape(mant) + mant_pad + " × 10" + re.escape(str(exp_i)))
            # The U+2212 spelling is the SAME value only when the exponent is
            # negative. Emitting it for a positive exponent also matched the
            # different value ("1.5 × 10^−3" for a target of 1500).
            if exp_i < 0:
                for mul in (" × 10^", " × 10"):
                    pats.append(re.escape(mant) + mant_pad + re.escape(mul + "\u2212"
                                          + str(abs(exp_i))))
            # Unicode superscripts ("3.1 × 10⁻²") and the LaTeX \times forms
            # ("3.1 \times 10^{-2}") are the same value in other manuscripts.
            _sup = str(exp_i).translate(str.maketrans(
                "0123456789-", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207b"))
            pats.append(re.escape(mant) + mant_pad + " × 10" + re.escape(_sup))
            for mul in (r" \times 10^", r" \times 10^{"):
                close = r"\}" if mul.endswith("{") else ""
                pats.append(re.escape(mant) + mant_pad + re.escape(mul + str(exp_i)) + close)
                if exp_i < 0:
                    pats.append(re.escape(mant) + mant_pad + re.escape(mul + "\u2212"
                                          + str(abs(exp_i))) + close)
        # An explicit positive sign names the same value; the leading guard
        # rejected it, so `--value 5` never found "+5" (F58).
        if not str(num).startswith(("+", "-", "\u2212")):
            pats.append(r"\+" + re.escape(num))
        # A trailing comma or period is only a separator when no digit follows:
        # without the ",digit" guard the value 5 also matched inside "5,000",
        # and without the ".digit" one the value 12 matched inside the DIFFERENT
        # value "12.5" (the leading guard only covers "X.y" -> y). A SIGN or a
        # preceding thousands separator changes the value just as much: `--value
        # 5` must not match "-5" and `--value 234` must not match "1,234".
        return re.compile(r"(?<![\w.,+\-\u2212])(" + "|".join(sorted(set(pats), key=len, reverse=True))
                          + r")(?![\w]|,\d|\.\d|\s*(?:[×x*]|\\times)\s*10(?:\^|\{)?)")
    # term mode: allow hyphen/space interchange, case-insensitive, optional 's'.
    # EVERY inter-word separator in the given term becomes the same class, so a
    # term written with a space also matches its hyphenated spelling and a
    # double space -- the old literal `-` replacement only fired when the term
    # itself contained a hyphen ("copy number" never matched "copy-number").
    # The class is `*` (not `+`) so the hyphenless spelling the old code
    # accepted for hyphenated terms ("scRNA-seq" ~ "scRNAseq") keeps matching.
    raw_parts = [p for p in re.split(r"[\s\-]+", term.strip()) if p]
    if not raw_parts:
        raise ValueError(f"empty term {term!r}: a term to enumerate must carry at least "
                         f"one character")

    def _last_word_pattern(word: str) -> str:
        """Regex for ONE term word plus its REGULAR plural (never impossible forms).

        The old blanket `(?:es|s)?` matched `copyes`/`analysises` while missing
        `copies`/`analyses`: a propagation pass could then claim a plural was
        seen when it never occurred. The stem is rewritten where the plural
        changes it (`copy` -> `cop(?:y|ies)`).
        """
        low = word.lower()
        if not re.fullmatch(r"[A-Za-z]+", word):
            return re.escape(word)
        if low.endswith("is"):
            return re.escape(word[:-2]) + r"(?:is|es)"      # analysis -> analyses
        if low.endswith("y") and len(low) > 1 and low[-2] not in "aeiou":
            return re.escape(word[:-1]) + r"(?:y|ies)"      # copy -> copies
        if low.endswith(("s", "x", "z", "ch", "sh")):
            return re.escape(word) + r"(?:es)?"
        return re.escape(word) + r"s?"

    parts = [re.escape(p) for p in raw_parts[:-1]] + [_last_word_pattern(raw_parts[-1])]
    # `(?<!\\w)`/`(?!\\w)` rather than `\\b`: a trailing `\\b` cannot match after
    # a term whose last character is not a word character, so `--term "CD4+"` and
    # `--term "C++"` matched NOTHING while the artifact still asserted "0
    # occurrences" -- and a P1 propagation pass read that as "fully propagated".
    # The lookarounds keep the ordinary word-edge semantics (scRNA-seq still
    # matches) and tolerate a non-word edge on either side. An empty term used to
    # compile to `(?i)(?<!\\w)(?:es|s)?(?!\\w)`, which MATCHED empty strings in
    # every word (6 matches inside a three-word sentence).
    pat = r"(?i)(?<!\w)" + r"[\s\-\u2013\u2014]*".join(parts) + r"(?!\w)"
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
        if not str(term).strip():
            print("ERROR: --term must not be empty")
            sys.exit(2)
        targets.append(("term", term))
    for value in (args.value or []):
        if not str(value).strip():
            print("ERROR: --value must not be empty")
            sys.exit(2)
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
        try:
            pat = variant_pattern(target, mode)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)
        results = []
        if os.path.isdir(corpus):
            for fname in sorted(os.listdir(corpus)):
                if not fname.endswith(".txt"):
                    continue
                if is_non_manuscript(fname):
                    continue  # occurrences are counted in the manuscript only
                if is_reference_file(fname):
                    continue  # a bibliography file is quoted text, not prose
                try:
                    lines = open(os.path.join(corpus, fname), encoding="utf-8",
                                 errors="replace").read().split("\n")
                except OSError as e:
                    print("WARNING: file-unreadable: %s: %s" % (fname, e), file=sys.stderr)
                    continue
                region = find_reference_region(lines)
                for li, raw in enumerate(lines, 1):
                    if region and region[0] <= li - 1 < region[1]:
                        continue  # a cited title is never a propagation target
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

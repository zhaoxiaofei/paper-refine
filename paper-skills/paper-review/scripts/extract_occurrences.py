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

EVIDENCE_DIRNAMES = ("raw_data", "human_review_feedback", "llm_review_feedback")
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
# A scientific compound that merely ENDS in a role word is not a reply: these
# were silently dropped from every manuscript sweep (M1/M2/M4/M19).
_SCIENCE_ROLE_COMPOUND_RE = re.compile(
    r"(?<![a-z])(?:dose|immune|stress|apoptotic|inflammatory|transcriptional|"
    r"pharmacodynamic)[-_ ]?response"
    r"|(?<![a-z])response[-_ ]?(?:time|rate|curve|latency|element|surface|variable)"
    r"|(?<![a-z])feedback[-_ ]?(?:loop|control|gain|signal)"
    r"|(?<![a-z])(?:bio|neuro|video|audio)[-_ ]?feedback", re.I)
# A venue ARTICLE TYPE is the authors' manuscript, not the editors' letter:
# `letter_to_the_editor.docx` / `Editorial.docx` must reach M1/M2/M4/M19.
_ARTICLE_TYPE_MANUSCRIPT_RE = re.compile(
    r"^(?:(?:the[.\s_-]+)?editorial(?:[.\s_-]+board)?|"
    r"letters?[.\s_-]+(?:to|for)[.\s_-]+(?:the[.\s_-]+)?editor)"
    r"(?:[.\s_-]+(?:v|rev|version|revision|draft)?[.\s_-]*\d{1,3})?$", re.I)
# A semantic suffix (`paper.reply.txt`, `editorial.review.txt`) names the
# DOCUMENT KIND, not an arbitrary extension: test it before stripping
# extensions, or `.reply`/`.review`/`.notes` disappear into the base name.
_SEMANTIC_SUFFIX_RE = re.compile(
    r"\.(?:reply|response|rebuttal|review|notes?|comments?)\.[A-Za-z0-9]+$", re.I)
# The WORD "cover" (and the camelCase "coverLetter"), not the substring: a bare
# `"cover" in name` also named `discovery.md`, `coverage_table.txt` and
# `recovered_samples.md` a cover letter (forcing them into the submission runs)
# and masked a reply file whose name merely contains the substring.
_COVER_WORD_RE = re.compile(
    r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
    r"(?:[Cc]over|COVER|(?i:coverletter|plainletter))(?![a-z])")


def _is_evidence_part(part: str) -> bool:
    """True for an evidence area, including its inert `<area>.disabled` form.

    The pipeline's `is_disabled_evidence_rel` treats `llm_review_feedback.disabled/`
    and `.off/` as inert evidence: not submission content, not readable evidence.
    Testing exact membership here swept that area as the authors' manuscript.
    """
    low = str(part or "").strip().lower()
    if low in EVIDENCE_DIRNAMES:
        return True
    return any(low.startswith(area + ".")
               and low[len(area) + 1:] in ("disabled", "off")
               for area in EVIDENCE_DIRNAMES)


def is_non_manuscript(name: str) -> bool:
    """True for an evidence-area / feedback / response file (never author prose)."""
    parts = str(name).replace("\\", "/").split("/")
    if any(_is_evidence_part(part) for part in parts[:-1]):
        return True
    base = parts[-1]
    if any(base.startswith(d + "__") for d in EVIDENCE_DIRNAMES):
        return True
    if _COVER_WORD_RE.search(base):
        return False            # a cover letter IS a submission document
    if _SEMANTIC_SUFFIX_RE.search(base):
        return True             # a reply/review/notes DOCUMENT, never author prose
    # Strip ALL extension layers: `letter_to_the_editor.final.docx.txt` and
    # `letter_to_the_editor.tar.gz.txt` are still the article-type manuscript.
    stem = base
    while True:
        _stripped = re.sub(
            r"\.(?:txt|docx?|md|tex|pdf|rtf|bib|csv|tsv|bak|final|tar|gz|zip)$",
            "", stem, flags=re.I)
        if _stripped == stem:
            break
        stem = _stripped
    if _ARTICLE_TYPE_MANUSCRIPT_RE.match(stem):
        return False            # the authors' article-type manuscript, not a letter
    cleaned = _SCIENCE_ROLE_COMPOUND_RE.sub(" ", base)
    if _REPLY_RE.search(cleaned):
        return True
    return bool(_NON_MANUSCRIPT_RE.search(cleaned))


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
        # The LITERAL spelling is always one of the forms: with a thousands
        # separator (`1,234`) the decimal-normalised `num` is "1.234", which
        # never matches the text that carries the number, so the sweep reported
        # an occurrence the manuscript still carries as missing.
        pats = [re.escape(num), esc]
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
        try:
            v = float(num)
            # One decimal of mantissa is NOT the value: for 1234.5 it produced
            # "1.2e+03" (1200) and for 0.0215 "2.1e-02" (0.021). Derive the
            # precision from the target's own significant digits (trailing
            # zeros are not significant) so the scientific spelling is exactly
            # the same number, no rounding in either direction.
            # The exponent's digits are part of the SPELLING, not the
            # mantissa: "1e-3" must yield 1e-03 (0.001), not 1.3e-03.
            _mantissa = re.split(r"[eE]", str(num), 1)[0]
            _digits = re.sub(r"[^0-9]", "", _mantissa).lstrip("0").rstrip("0") or "0"
            sci = "%.*e" % (len(_digits) - 1, v)
            mant, exp = sci.split("e")
            pats.append(re.escape(mant + "e" + exp))
            # The same value written in plain decimal is an equivalent
            # notation ("1e-3" ~ "0.001"), and the mode promises to
            # enumerate equivalents. Decimal(str(num)) keeps the written
            # value exact (no float formatting noise).
            if "e" in str(num).lower():
                try:
                    dec = format(Decimal(str(num)), "f")
                except InvalidOperation:
                    dec = ""
                if dec and dec not in ("0", "0.0"):
                    pats.append(re.escape(dec))
                    if "." in dec:
                        short = dec.rstrip("0").rstrip(".")
                        if short and short != dec:
                            pats.append(re.escape(short))
            # "%.1e" always pads the exponent to two digits (3.1e-02) while
            # manuscripts usually write 3.1e-2 -- the short form (and the
            # uppercase E) must be enumerated too, or those occurrences of the
            # value are invisible to the M4 number sweep.
            # `%.*e` pads a positive exponent ("+02") and drops a trailing zero
            # from the mantissa; manuscripts write "e+2" and "3.10e+2". Both
            # spellings (and uppercase E, and the padded exponent) are the same
            # value and must be enumerated.
            short = ("+" if exp.startswith("+") else "") + str(int(exp))
            for e_char in ("e", "E"):
                pats.append(re.escape(mant) + "0*" + re.escape(e_char + short))
                # The UNSIGNED short form (`3.1e2`, `3.1E2`) is the same value
                # as `3.1e+2`: adding the sign must not drop it.
                pats.append(re.escape(mant) + "0*" + re.escape(e_char + str(int(exp))))
                pats.append(re.escape(mant) + "0*" + re.escape(e_char + exp))
            pats.append(re.escape(mant + " × 10^" + str(int(exp))))
            # The multiplication sign is also written without the caret and
            # with a U+2212 minus ("3.1 × 10−2"); those occurrences were
            # invisible to the M4 sweep.
            pats.append(re.escape(mant + " × 10" + str(int(exp))))
            # The U+2212 spelling is the SAME value only when the exponent is
            # negative. Emitting it for a positive exponent also matched the
            # different value ("1.5 × 10^−3" for a target of 1500).
            if int(exp) < 0:
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
                if int(exp) < 0:
                    pats.append(re.escape(mant + mul + "\u2212" + str(abs(int(exp)))) + close)
        except ValueError:
            pass
        # A trailing comma or period is only a separator when no digit follows:
        # without the ",digit" guard the value 5 also matched inside "5,000",
        # and without the ".digit" one the value 12 matched inside the DIFFERENT
        # value "12.5" (the leading guard only covers "X.y" -> y). A SIGN or a
        # preceding thousands separator changes the value just as much: `--value
        # 5` must not match "-5" and `--value 234` must not match "1,234".
        return re.compile(r"(?<![\w.,+\-\u2212])(" + "|".join(sorted(set(pats), key=len, reverse=True))
                          + r")(?![\w]|,\d|\.\d)")
    # term mode: allow hyphen/space interchange, case-insensitive, optional 's'.
    # EVERY inter-word separator in the given term becomes the same class, so a
    # term written with a space also matches its hyphenated spelling and a
    # double space -- the old literal `-` replacement only fired when the term
    # itself contained a hyphen ("copy number" never matched "copy-number").
    # The class is `*` (not `+`) so the hyphenless spelling the old code
    # accepted for hyphenated terms ("scRNA-seq" ~ "scRNAseq") keeps matching.
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip()) if p]
    if not parts:
        raise ValueError(f"empty term {term!r}: a term to enumerate must carry at least "
                         f"one character")
    # `(?<!\\w)`/`(?!\\w)` rather than `\\b`: a trailing `\\b` cannot match after
    # a term whose last character is not a word character, so `--term "CD4+"` and
    # `--term "C++"` matched NOTHING while the artifact still asserted "0
    # occurrences" -- and a P1 propagation pass read that as "fully propagated".
    # The lookarounds keep the ordinary word-edge semantics (scRNA-seq still
    # matches) and tolerate a non-word edge on either side. An empty term used to
    # compile to `(?i)(?<!\\w)(?:es|s)?(?!\\w)`, which MATCHED empty strings in
    # every word (6 matches inside a three-word sentence).
    pat = r"(?i)(?<!\w)" + r"[\s\-\u2013\u2014]*".join(parts) + r"(?:es|s)?(?!\w)"
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
                try:
                    lines = open(os.path.join(corpus, fname), encoding="utf-8",
                                 errors="replace").read().split("\n")
                except OSError as e:
                    print("WARNING: file-unreadable: %s: %s" % (fname, e), file=sys.stderr)
                    continue
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

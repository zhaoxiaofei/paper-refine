#!/usr/bin/env python3
"""enumerate_conventions.py — M26 house-style/orthographic convention ledger.

Used by:
  paper-review  — M26 house-style/orthographic convention sweep: every
                occurrence of a US/UK spelling, hyphenation or preverb variant
                is enumerated BEFORE any judgement, so the reviewer decides ONE
                authoritative form per family and files one finding per
                deviating occurrence (never one blanket finding).
  paper-revise  — the convention propagation pass after a substitution: re-run
                it over the revised corpus to prove every edited occurrence is
                gone (or carries a recorded reason).

Enumeration is two-layered:
  * a curated family list (US/UK spelling pairs that are real, stable
    alternatives: -ize/-ise, -yze/-yse, -or/-our, -er/-re, ae/e, oe/e,
    -logue/-log, -ement/-ment, and the -l/-ll inflection list);
  * data-driven candidates: tokens that become identical under the licensed
    orthographic transformations and whose alternative surface forms BOTH
    occur in the corpus (an unlisted family is exactly the case a curated list
    misses).
Hyphenation and preverb families (`re-analysis`/`reanalysis`,
`down-sample`/`downsample`, `multi-omics`/`multiomics`, ...) are derived from
the corpus the same way: surfaces that differ only by hyphens are one family.

The script NEVER decides. It writes:
  WORK/STYLE_VARIANTS.md    — one row per occurrence (family | variant |
                              document | line | excerpt | disposition)
  WORK/STYLE_VARIANTS.json  — the same rows, machine-readable
  WORK/STYLE_CONVENTIONS.md — the DECISION table the reviewer must fill
                              (family | surfaces seen | authoritative form |
                              basis | forbidden variants | disposition)
A family with only ONE surface form is not a finding and is only listed in the
decision table for the record.

stdlib-only. Usage:
  python enumerate_conventions.py --work ./review/work
  python enumerate_conventions.py --work ./revised/work --corpus ./revised/work/corpus
  python enumerate_conventions.py --work ./review/work --out ./review/artifacts
  python enumerate_conventions.py --work ./review/work --families my_families.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

TEXT_EXTS = (".txt", ".md", ".tex", ".csv")


def _ize_family(stems, name="-ize/-ise verb family"):
    """Both the -ize and the -ise surface of every stem (stem ends in `iz`)."""
    variants = []
    for stem in stems:
        base = stem[:-2] if stem.endswith("iz") else stem
        for suffix in ("ize", "izes", "ized", "izing", "ization", "izations",
                       "ise", "ises", "ised", "ising", "isation", "isations"):
            variants.append(base + suffix)
    return name, variants


def _pair_family(pairs, name, suffixes=("", "s")):
    variants = []
    for a, b in pairs:
        for suffix in suffixes:
            variants.append(a + suffix)
            variants.append(b + suffix)
    return name, variants


# Each family: (name, [surface forms]). Both spellings are listed explicitly
# (the family exists because the corpus may use either), and every surface is
# matched as a whole word, case-insensitively.
IZE_STEMS = ["normaliz", "characteriz", "organiz", "optimiz",
             "minimiz", "maximiz", "summariz", "prioritiz", "standardiz",
             "categoriz", "visualiz", "recogniz", "utiliz", "hypothesiz",
             "generaliz", "randomiz", "regulariz", "harmoniz", "synchroniz"]
YZE_STEMS = ["analy", "cataly", "hydroly", "electroly"]
OUR_PAIRS = [("color", "colour"), ("behavior", "behaviour"),
             ("favor", "favour"), ("labor", "labour"),
             ("neighbor", "neighbour"), ("humor", "humour"),
             ("tumor", "tumour"), ("vapor", "vapour"),
             ("vigor", "vigour"), ("odor", "odour"),
             ("colorimetric", "colourimetric")]
RE_PAIRS = [("center", "centre"), ("meter", "metre"), ("liter", "litre"),
            ("fiber", "fibre"), ("theater", "theatre"),
            ("caliber", "calibre"), ("somber", "sombre")]
AE_PAIRS = [("artifact", "artefact"), ("pediatric", "paediatric"),
            ("anesthesia", "anaesthesia"), ("anesthetic", "anaesthetic"),
            ("encyclopedia", "encyclopaedia"), ("edema", "oedema"),
            ("fetus", "foetus"), ("fetal", "foetal"),
            ("hemoglobin", "haemoglobin"), ("leukemia", "leukaemia"),
            ("maneuver", "manoeuvre"), ("diarrhea", "diarrhoea"),
            ("esophagus", "oesophagus"), ("aging", "ageing"),
            ("orthopedic", "orthopaedic"), ("etiology", "aetiology")]
LOGUE_PAIRS = [("catalog", "catalogue"), ("dialog", "dialogue"),
               ("analog", "analogue"), ("program", "programme")]
EMENT_PAIRS = [("judgment", "judgement"),
               ("acknowledgment", "acknowledgement")]
LL_PAIRS = [("labeled", "labelled"), ("labeling", "labelling"),
            ("modeled", "modelled"), ("modeling", "modelling"),
            ("traveled", "travelled"), ("traveling", "travelling"),
            ("traveler", "traveller"), ("canceled", "cancelled"),
            ("canceling", "cancelling"), ("focused", "focussed"),
            ("focusing", "focussing"), ("signaled", "signalled"),
            ("signaling", "signalling"), ("fueled", "fuelled"),
            ("counselor", "counsellor")]
ENCE_PAIRS = [("defense", "defence"), ("offense", "offence"),
              ("pretense", "pretence")]

CURATED_FAMILIES = [
    _ize_family(IZE_STEMS),
    ("-yze/-yse verb family",
     [stem + s for stem in YZE_STEMS
      for s in ("ze", "zes", "zed", "zing", "se", "ses", "sed", "sing")]),
    _pair_family(OUR_PAIRS, "-or/-our spelling family",
                 suffixes=("", "s", "ed", "ing", "al", "ous")),
    _pair_family(RE_PAIRS, "-er/-re spelling family",
                 suffixes=("", "s", "ed", "ing")),
    _pair_family(AE_PAIRS, "ae/e and oe/e spelling family", suffixes=("", "s")),
    _pair_family(LOGUE_PAIRS, "-logue/-log spelling family", suffixes=("", "s")),
    _pair_family(EMENT_PAIRS, "-ement/-ment spelling family", suffixes=("", "s")),
    ("-l/-ll inflection family", [v for pair in LL_PAIRS for v in pair]),
    _pair_family(ENCE_PAIRS, "-ance/-ence spelling family", suffixes=("", "s")),
    ("among/amongst, while/whilst",
     ["among", "amongst", "while", "whilst", "toward", "towards",
      "afterward", "afterwards", "forward", "forwards"]),
]

# Licensed orthographic transformations for the data-driven layer: each maps a
# token to the key under which its alternatives collapse. Only keys with TWO OR
# MORE distinct surface forms in the corpus are reported as candidate families.


def _candidate_key(token: str) -> str:
    t = token
    t = re.sub(r"isation\b", "ization", t)
    t = re.sub(r"ises\b", "izes", t)
    t = re.sub(r"ised\b", "ized", t)
    t = re.sub(r"ising\b", "izing", t)
    t = re.sub(r"ise\b", "ize", t)
    t = re.sub(r"ysed\b", "yzed", t)
    t = re.sub(r"yses\b", "yzes", t)
    t = re.sub(r"ysing\b", "yzing", t)
    t = re.sub(r"yse\b", "yze", t)
    t = re.sub(r"our(s|al|able|ed|ing|ite|ism|ist)?\b", r"or\1", t)
    t = re.sub(r"ae", "e", t)
    t = re.sub(r"oe", "e", t)
    t = re.sub(r"logue\b", "log", t)
    t = re.sub(r"ement\b", "ment", t)
    t = re.sub(r"ll(ed|ing|er)\b", r"l\1", t)
    return t


EVIDENCE_DIRNAMES = ("raw_data", "raw_figs", "human_review_feedback", "llm_review_feedback")
_NON_MANUSCRIPT_RE = re.compile(
    r"feedback|referee|reviewers?|editors?|editorial|decision[_ \-]*(?:letter|notice|email)"
    r"|response|repl(?:y|ies)|rebuttal|point[-_ ]?by[-_ ]?point", re.I)
_REPLY_RE = re.compile(r"response|repl(?:y|ies)|rebuttal|point[-_ ]?by[-_ ]?point", re.I)


def _non_manuscript(name: str) -> bool:
    """True for an evidence-area / feedback / response path (never manuscript text)."""
    parts = str(name).replace("\\", "/").split("/")
    if any(part in EVIDENCE_DIRNAMES for part in parts[:-1]):
        return True
    base = parts[-1]
    if any(base.startswith(d + "__") for d in EVIDENCE_DIRNAMES):
        return True
    if _REPLY_RE.search(base):
        return True
    if "cover" in base.lower():
        return False            # a cover letter IS a submission document
    return bool(_NON_MANUSCRIPT_RE.search(base))


def read_text_files(corpus: str):
    """(name, lines) for every text file under corpus, sorted by name."""
    out = []
    for root, _dirs, files in os.walk(corpus):
        for fname in sorted(files):
            if not fname.lower().endswith(TEXT_EXTS):
                continue
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, corpus).replace(os.sep, "/")
            if _non_manuscript(rel):
                continue        # evidence / feedback / response text is not the manuscript
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            out.append((rel, text.split("\n")))
    out.sort(key=lambda p: p[0])
    return out


def load_families(path):
    """Optional project families: [{"family": ..., "variants": [...]}, ...]."""
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    fams = []
    for row in data if isinstance(data, list) else [data]:
        if not isinstance(row, dict):
            continue
        fams.append((str(row.get("family") or "project family"),
                     [str(v) for v in (row.get("variants") or [])]))
    return fams


def word_pattern(variant: str) -> re.Pattern:
    v = variant.strip()
    if not v:
        return None
    # The variant is literal text, not a pattern: "C++" (and "N.B.", "IL-6"),
    # interpolated raw, matched a lone "C" (or any character where "." sat) and
    # over-reported occurrences of the family.
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])",
                      re.IGNORECASE)


def collect_family_rows(docs, families):
    """One row per occurrence of every variant in the curated/project families."""
    rows = []
    for family, variants in families:
        # A family may list the same surface twice (an identity pair in the
        # curated list, or a project family that repeats one); dedupe so no
        # occurrence is reported twice.
        for variant in dict.fromkeys(variants):
            pat = word_pattern(variant)
            if pat is None:
                continue
            for name, lines in docs:
                for li, raw in enumerate(lines, 1):
                    for m in pat.finditer(raw):
                        rows.append({
                            "family": family,
                            "variant": m.group(0),
                            "pattern": variant,
                            "document": name,
                            "line": li,
                            "excerpt": raw.strip()[:140],
                        })
    return rows


def collect_candidates(docs, min_len=5, min_count=1):
    """Surface forms that collapse to one licensed key, with occurrence counts.

    Counts are REAL occurrence counts (the decision table's corpus-majority
    basis), and up to three example locations per surface are kept.
    """
    by_key = defaultdict(Counter)
    where = defaultdict(list)
    token_re = re.compile(r"[A-Za-z]{5,}")
    for name, lines in docs:
        for li, raw in enumerate(lines, 1):
            for m in token_re.finditer(raw):
                tok = m.group(0)
                if "-" in tok:
                    continue
                low = tok.lower()
                key = _candidate_key(low)
                if key == low or len(key) < min_len:
                    continue
                by_key[key][low] += 1
                if len(where[(key, low)]) < 3:
                    where[(key, low)].append((name, li, raw.strip()[:100]))
    cands = []
    for key, counter in sorted(by_key.items()):
        forms = sorted(counter)
        if len(forms) < 2:
            continue
        if min(counter.values()) < min_count:
            continue
        cands.append({"key": key, "forms": forms,
                      "counts": {f: counter[f] for f in forms},
                      "examples": {f: where[(key, f)] for f in forms}})
    return cands


def collect_hyphen_families(docs, min_len=5, min_count=2):
    """Surfaces that differ only by hyphens (`re-analyzed` / `reanalyzed`).

    Hyphenated AND plain tokens are collected under the hyphen-stripped key, so
    a corpus that mixes the two surfaces reports the family; a group whose
    surfaces are all hyphenated differently (or all plain) is not a family.
    """
    forms = defaultdict(Counter)
    examples = defaultdict(list)
    tok_re = re.compile(r"[A-Za-z][A-Za-z-]{4,}")
    for name, lines in docs:
        for li, raw in enumerate(lines, 1):
            for m in tok_re.finditer(raw):
                tok = m.group(0).strip("-")
                key = tok.lower().replace("-", "")
                if len(key) < min_len:
                    continue
                forms[key][tok.lower()] += 1
                if len(examples[(key, tok.lower())]) < 3:
                    examples[(key, tok.lower())].append((name, li, raw.strip()[:100]))
    out = []
    for key, counter in sorted(forms.items()):
        if len(counter) < 2:
            continue
        if not any("-" in f for f in counter):
            continue
        if min(counter.values()) < min_count:
            continue
        out.append({"key": key, "forms": sorted(counter),
                    "counts": dict(counter),
                    "examples": {f: examples[(key, f)] for f in counter}})
    return out


def write_outputs(rows, candidates, hyphens, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "STYLE_VARIANTS.md")
    js_path = os.path.join(out_dir, "STYLE_VARIANTS.json")
    dec_path = os.path.join(out_dir, "STYLE_CONVENTIONS.md")

    fam_counts = Counter(r["family"] for r in rows)
    md = ["# M26 — house-style/orthographic convention ledger (code-side enumeration)", "",
          "One row per occurrence. Decide ONE authoritative form per family in "
          "`STYLE_CONVENTIONS.md`, then dispose every row here (finding id / "
          "`OK — <the row's own bar>` / `unable — <reason>`). A variant that is "
          "not the authoritative form and is not a first use, a quoted title or a "
          "proper name is a finding (one per occurrence, never one per family).", "",
          "## Curated family occurrences", "",
          "| # | family | variant | document | line | excerpt | disposition |",
          "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        md.append("| %d | %s | %s | %s | %d | %s | |" % (
            i, r["family"], r["variant"], r["document"], r["line"],
            r["excerpt"].replace("|", "\\|")))
    md += ["", "## Candidate families (data-driven; both surfaces occur in the corpus)", "",
           "| # | family key | surface forms (counts) | example locations | disposition |",
           "|---|---|---|---|---|"]
    for i, c in enumerate(candidates, 1):
        forms = "; ".join("%s×%d" % (f, c["counts"][f]) for f in c["forms"])
        ex = "; ".join("%s:%d" % (l[0], l[1])
                       for f in c["forms"] for l in c["examples"][f][:1])
        md.append("| %d | %s | %s | %s | |" % (i, c["key"], forms, ex))
    md += ["", "## Hyphenation / preverb families (surfaces differing only by hyphens)", "",
           "| # | family key | surface forms (counts) | example locations | disposition |",
           "|---|---|---|---|---|"]
    for i, c in enumerate(hyphens, 1):
        forms = "; ".join("%s×%d" % (f, c["counts"][f]) for f in c["forms"])
        ex = "; ".join("%s:%d" % (l[0], l[1])
                       for f in c["forms"] for l in c["examples"][f][:1])
        md.append("| %d | %s | %s | %s | |" % (i, c["key"], forms, ex))
    md.append("")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    with open(js_path, "w", encoding="utf-8") as fh:
        json.dump({"occurrences": rows, "candidate_families": candidates,
                   "hyphen_families": hyphens,
                   "family_counts": dict(fam_counts)}, fh, indent=2)

    # The decision table: one row per family, authoritative form EMPTY on
    # purpose — the reviewer decides, the script never does.
    fams = sorted({r["family"] for r in rows})
    dec = ["# STYLE_CONVENTIONS — one decision per family (fill every row)", "",
           "| family | surfaces seen (counts) | authoritative form | basis "
           "(corpus majority / first use / venue rule) | forbidden variants | disposition |",
           "|---|---|---|---|---|---|"]
    surfaces = defaultdict(Counter)
    for r in rows:
        surfaces[r["family"]][r["variant"].lower()] += 1
    for fam in fams:
        seen = "; ".join("%s×%d" % (k, v) for k, v in sorted(surfaces[fam].items()))
        dec.append("| %s | %s | | | | |" % (fam, seen))
    for c in candidates:
        seen = "; ".join("%s×%d" % (f, c["counts"][f]) for f in c["forms"])
        dec.append("| candidate:%s | %s | | | | |" % (c["key"], seen))
    for c in hyphens:
        seen = "; ".join("%s×%d" % (f, c["counts"][f]) for f in c["forms"])
        dec.append("| hyphen:%s | %s | | | | |" % (c["key"], seen))
    dec.append("")
    with open(dec_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(dec) + "\n")
    return md_path, js_path, dec_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", default=".", help="WORK dir (default: .)")
    ap.add_argument("--corpus", default=None,
                    help="converted corpus dir (default: <work>/corpus)")
    ap.add_argument("--out", default=None,
                    help="output dir for the ledger (default: <work>)")
    ap.add_argument("--families", default=None,
                    help="optional JSON project family list")
    ap.add_argument("--min-count", type=int, default=2,
                    help="min occurrences of EACH surface for a candidate family "
                         "(default 2)")
    args = ap.parse_args(argv)

    work = os.path.abspath(args.work)
    corpus = os.path.abspath(args.corpus) if args.corpus else os.path.join(work, "corpus")
    out_dir = os.path.abspath(args.out) if args.out else work
    if not os.path.isdir(corpus):
        print("no corpus dir: %s (run convert_corpus.py first)" % corpus, file=sys.stderr)
        return 2
    docs = read_text_files(corpus)
    if not docs:
        print("no text files under %s" % corpus, file=sys.stderr)
        return 2
    families = CURATED_FAMILIES + load_families(args.families)
    rows = collect_family_rows(docs, families)
    candidates = collect_candidates(docs, min_count=args.min_count)
    hyphens = collect_hyphen_families(docs, min_count=args.min_count)
    md, js, dec = write_outputs(rows, candidates, hyphens, out_dir)
    print("occurrence rows: %d (%d families)" % (len(rows), len({r["family"] for r in rows})))
    print("candidate families: %d; hyphen families: %d" % (len(candidates), len(hyphens)))
    print("Artifacts: %s, %s, %s" % (md, js, dec))
    return 0


if __name__ == "__main__":
    sys.exit(main())

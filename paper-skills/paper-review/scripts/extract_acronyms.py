#!/usr/bin/env python3
"""extract_acronyms.py — M1 acronym/abbreviation sweep (the original pain point).

Reads the plain-text corpus produced by convert_corpus.py, extracts every
acronym-like token, and builds the ACRONYM INVENTORY artifact:
  OUT/artifacts/M1_acronyms.md    — one row per unique token (including OK rows)
                                    + the M1b instance table: every use of a
                                    defined acronym's un-abbreviated LONG FORM
                                    AFTER its first use in the same context
  OUT/artifacts/M1_acronyms.json  — machine-readable copy for findings.json

The M1b table is the evidence base for finding rule M1(k). The convention is
the master prompt's own: "repeating fully expanded long-forms after their first
use". So in every context (abstract / introduction / main text / Methods / each
legend / table footnote / supplementary document), the FIRST occurrence of the
long form is legitimate -- it is that context's first use, and it may carry the
definition -- while every LATER occurrence of the long form is a residue, for
every acronym whose definition the sweep recorded. The audit is NOT licensed by
a local definition, because the reported failure mode is exactly a definition in
one context followed by long-form re-use in another: "copy-number (CN)" defined
in the abstract, "copy-number" re-used 50+ times in the main text. That error
class was invisible to a plain token inventory -- the M1 row for CN read
"defined at first use: Y, consistent: Y" while the long form carried the prose.

The matcher is variant-tolerant -- case (Copy-Number), hyphenation (copy number
vs copy-number vs en-dash), and plurals (copy numbers) -- because those are the
authoring slips authors actually make, and it is context-scoped: each context
gets one legitimate first use. Matches inside the definition parenthetical
itself ("copy-number (CN)", "CN (copy-number)") and matches inside double quotes
(a quoted title must stay verbatim) are counted separately and never listed as
rows.

Exclusions (per skill spec): reference-list region, DOIs, accession numbers,
URLs, file paths, SI units. Universal abbreviations (DNA, RNA, ATP, SDS-PAGE,
PBS, SD, SEM, ANOVA, ...) are listed but marked EXEMPT — the model audits the
rest row by row. Statistical symbols and generic tokens are listed as EXEMPT
rows too, so nothing disappears silently.

Token coverage: the strict pattern catches tokens with an internal capital
(qPCR, mRNA, scRNA-seq, IL-6) and all-caps tokens (PCR, CRISPR). Gene-symbol
shapes (Foxp3, Nrf2, CD8, p53, C1) and a curated set of digit-free cell-type symbols
(Treg, Tregs, cDC, Eomes, ...) are caught by two extra patterns. Any
single-leading-capital token still missed is a known limit of regex: the manual
pass in references/sweeps.md M1 covers it, and project-specific tokens can be
declared one per line in WORK/extra_acronyms.txt.

Known limits of the M1b long-form matcher (the manual pass covers them): a
reworded synonym of the long form ("aberration burden" for "copy-number") is
not matched, and a definition written without parentheses ("copy-number,
hereafter CN") is recorded only through its long-form occurrence, not as a
definition.

stdlib-only. Usage:
  python extract_acronyms.py --work ./review/work [--out ./review]
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

# Universal abbreviations exempt from redefinition anywhere
UNIVERSAL = {
    "DNA", "RNA", "mRNA", "rRNA", "tRNA", "siRNA", "miRNA", "ATP", "ADP", "AMP",
    "SDS-PAGE", "PBS", "SD", "SEM", "ANOVA", "PCR", "ELISA", "FACS", "GFP",
    "YFP", "RFP", "DAPI", "HEK", "FBS", "DMEM", "EDTA", "DMSO", "PAGE",
}
# SI unit tokens & common non-acronym fragments to exclude outright
SI_UNITS = {"ml", "mL", "µL", "ul", "uL", "l", "L", "kg", "mg", "ug", "µg", "g",
            "min", "h", "hr", "s", "ms", "mM", "uM", "µM", "nM", "pM", "M",
            "kb", "Mb", "Gb", "bp", "kDa", "Da", "V", "mV", "kV", "W", "mW",
            "J", "kJ", "cal", "kcal", "C", "°C"}
STAT_SYMBOLS = {"n", "p", "P", "t", "F", "R", "r", "q", "N", "CI", "HR", "OR",
                "SE", "AUC", "ROC", "SDs"}
MONTHS = {"Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct",
          "Nov", "Dec", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
GENERIC = {"et", "al", "vs", "Fig", "Figs", "Supplementary", "Supp", "Note",
           "MS", "PhD", "MD", "MSc", "BSc", "USA", "UK", "EU", "LLC", "GmbH",
           "Inc", "Ltd", "Dept", "Univ", "approx", "ca", "cf", "Fig.",
           "St", "Dr", "Prof", "Ms", "Mr", "Mrs"}

# Why a token is exempt (listed, never silently dropped)
EXEMPT_REASON = {}
for _t in sorted(UNIVERSAL):
    EXEMPT_REASON.setdefault(_t, "universal")
for _t in sorted(STAT_SYMBOLS):
    EXEMPT_REASON.setdefault(_t, "statistical symbol")
for _t in sorted(MONTHS):
    EXEMPT_REASON.setdefault(_t, "month/roman numeral")
for _t in sorted(GENERIC):
    EXEMPT_REASON.setdefault(_t, "generic token")
# Real biomedical tokens that look like roman numerals: listed (never dropped)
# rather than filtered by the roman-numeral rule below.
for _t in sorted({"CV", "CLL", "CLI", "CCL", "CXCL", "LV", "ICL", "LCL"}):
    EXEMPT_REASON.setdefault(_t, "roman-numeral look-alike (real token)")

# strict: internal capital or all-caps (qPCR, scRNA-seq, IL-6, CRISPR).
# "/" is deliberately NOT part of a token: slashed pairs (scRNA-seq/scATAC-seq,
# CD4/CD8) must enumerate as two tokens, not one composite.
TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9\-–—]*[A-Z][A-Za-z0-9\-–—]*\b|\b[A-Z]{2,}[0-9]*\b")
# gene/protein shapes the strict pattern cannot catch: Foxp3, Nrf2, CD8, Il6,
# p53, nf1, il6, stat3, mbd3, nrf2, S100, GRCh38, C1, E2 …
GENE_SYMBOL_RE = re.compile(r"\b[A-Za-z]{1,6}\d{1,4}[a-z]?\b")
# measurement nouns that would otherwise look like gene symbols (week12, day3)
GENE_STOPWORDS = {
    "week", "day", "hour", "hr", "min", "phase", "group", "step", "round", "sample",
    "patient", "batch", "cycle", "dose", "tube", "well", "lane", "plate", "kit",
    "file", "page", "line", "table", "figure", "fig", "supp", "eq", "eqn", "scheme",
    "version", "time", "trial", "stage", "cohort", "replicate", "mouse", "cell",
    "scan", "slide", "chip", "series", "part", "set", "item", "row", "col", "column",
    "grade", "type", "class", "level", "point", "site", "arm", "visit", "run", "read",
}
VERSION_TOKEN_RE = re.compile(r"^v\d+(?:\.\d+)*[a-z]?$", re.I)
GENE_PREFIX_RE = re.compile(r"^([A-Za-z]+)\d")
CAPTION_REF_RE = re.compile(r"(?i)^(?:fig(?:ure)?s?|tabs?|tables?|supp|eq|eqn|scheme)s?\.?\d+[a-z]?$")
# digit-free cell-type / gene symbols (Treg, Tregs, cDC, Eomes, ...)
CELL_TYPE_RE = re.compile(
    r"\b(?:Tregs?|Bregs?|Tconv|Teff|Tfh|Tfr|Trm|Tcm|Tem|Tscm|cDC|pDC|moDC|"
    r"Nanog|Eomes|Tbet|Gzmb|Ifng|Rorc|Klf4|Sox2|Myc)\b")
EXTRA_TOKENS_FILE = "extra_acronyms.txt"

URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s]+", re.I)
DOI_RE = re.compile(r"(?:doi\.?org/|DOI:?)[\s]*[^\s]+", re.I)
ACCESSION_RE = re.compile(r"\b(?:GSE\d+|PRJNA\d+|PRJDB\d+|SR[APRX]\d+|E-MTAB-\d+|EGAS\d+|HPA\d+|PDB:\s?\w{4}|ChEMBL\d+|Zenodo\.\d+)\b", re.I)
# only path-looking strings and real filenames — "and/or" or "scRNA-seq/scATAC-seq" are prose
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|(?:^|\s)[.~]{0,2}/)[\w.\-]+(?:[\\/][\w.\-]+)+")
FILE_RE = re.compile(
    r"\b[\w.\-]+\.(?:py|r|ipynb|md|txt|csv|tsv|xlsx?|docx?|pdf|png|jpe?g|tiff?|eps|svg|"
    r"bib|tex|zip|gz|json|ya?ml|sh|xls|pptx|xml|rels|fa|fq|fastq|bam|h5ad|rds|loom)\b", re.I)

REF_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:references?|bibliography|reference\s+list|literature\s+cited)\s*:?\s*$", re.I)
STOP_SECTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s+)?(?:figure\s+legends?|figures?|table\s+legends?|tables?|"
    r"supplementary(?:\s+\w+)?|extended\s+data(?:\s+\w+)?|methods?|materials\s+and\s+methods|"
    r"experimental\s+procedures|results?|discussion|conclusions?|introduction|background|"
    r"abstract|acknowledge?ments?|author\s+contributions?|competing\s+interests?|"
    r"conflicts?\s+of\s+interest|data\s+availability|code\s+availability|funding|"
    r"ethics(?:\s+statement)?|appendix|list\s+of\s+(?:figures|tables))\s*:?\s*$", re.I)
MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
# a display-item caption needs a separator after the label ("Fig. 1 |", "Fig. 1.",
# "Table 2:") — otherwise a Results sentence like "Fig. 1 shows …" would be
# mistaken for a caption and would flip the section context
CAP_SEP = r"[.:|–—,](?:\s*\S|\s*$)"
FIG_CAPTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:extended\s+data|supplementary\s+)?fig(?:ure)?s?\.?\s*"
    r"(?:s\d+|\d+[a-z]?)\s*" + CAP_SEP, re.I)
TABLE_CAPTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:extended\s+data|supplementary\s+)?tables?\.?\s*"
    r"(?:s\d+|\d+[a-z]?)\s*" + CAP_SEP, re.I)
NUM_ENTRY_RE = re.compile(r"^\s*(?:\[?\d{1,3}[\].)]|\d{1,3}[.)])\s+")
BULLET_ENTRY_RE = re.compile(r"^\s*[-*•]\s+\S")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")
ENTRY_HINT_RE = re.compile(
    r"(\bdoi\b|https?://|arxiv|biorxiv|medrxiv|preprint|\bet al\.?\b|\bpp?\.\s*\d+)", re.I)
AUTHOR_START_RE = re.compile(r"^\s*[A-Z][A-Za-z'\-]+,\s*(?:[A-Z]\.|[A-Z][a-z]+)")


def looks_like_reference_entry(s):
    if NUM_ENTRY_RE.match(s) or BULLET_ENTRY_RE.match(s):
        return True
    if YEAR_RE.search(s) or ENTRY_HINT_RE.search(s):
        return True
    return bool(AUTHOR_START_RE.match(s))

SECTION_PATTERNS = [
    ("cover letter", re.compile(r"^(?:cover letter|dear editor)\b", re.I)),
    ("title page", re.compile(r"^(?:title|title page|running title)\b", re.I)),
    ("abstract", re.compile(r"^abstract\b", re.I)),
    ("introduction", re.compile(r"^(?:introduction|background)\b", re.I)),
    ("main text", re.compile(r"^(?:results?|discussion|conclusions?)\b", re.I)),
    ("Methods", re.compile(r"^(?:methods?|materials and methods|experimental procedures|star methods)\b", re.I)),
    # End-anchored: a prose line that merely starts with "References are …"
    # is not a heading and must stay in the sweep (its tokens were silently
    # dropped when the prefix alone was enough).
    ("references", re.compile(r"^(?:references?|bibliography|reference list|literature cited)\s*$", re.I)),
    ("acknowledgements", re.compile(r"^acknowledge?ments?\b", re.I)),
    ("author contributions", re.compile(r"^author contributions?\b", re.I)),
    ("competing interests", re.compile(r"^(?:competing interests?|conflicts? of interest|declaration of interests?)\b", re.I)),
    ("data availability", re.compile(r"^(?:data|code) availability\b", re.I)),
    ("supplementary", re.compile(r"^(?:supplementary|extended data|appendix)\b", re.I)),
    ("figure legend", re.compile(r"^(?:figure legends?|legends?)\b", re.I)),
    ("table", re.compile(r"^(?:tables?|table legends?)\b", re.I)),
    # synthetic corpus markers written by convert_corpus.py
    ("table", re.compile(r"^sheet\b", re.I)),
    ("header", re.compile(r"^header\b", re.I)),
    ("footer", re.compile(r"^footer\b", re.I)),
    ("footnotes", re.compile(r"^footnotes?\b", re.I)),
    ("endnotes", re.compile(r"^endnotes?\b", re.I)),
]

# reading order used for "defined at first use" (never filename sort order)
CONTEXT_RANK = {"title page": 5, "abstract": 10, "introduction": 15, "main text": 20,
                "Methods": 30, "figure legend": 40, "table": 45, "reporting summary": 50,
                "supplementary": 60, "acknowledgements": 70, "author contributions": 71,
                "competing interests": 72, "data availability": 73, "cover letter": 90,
                "references": 95, "footnotes": 96, "endnotes": 97, "header": 98, "footer": 99}


def rank(ctx):
    return CONTEXT_RANK.get(ctx, 25)


def find_reference_region(lines):
    """(start, end, note) line indices of the reference list, or None.

    The region ends at the next heading/caption, or — when the list is followed
    by a plain paragraph with no heading — at the first paragraph that does not
    look like a reference entry. The boundary note is printed in the artifact so
    a cut is never silent.
    """
    start = None
    for i, ln in enumerate(lines):
        if REF_HEADING_RE.match(ln.strip()):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    note = "to end of file"
    prev_blank = True
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if not s:
            prev_blank = True
            continue
        if NUM_ENTRY_RE.match(s):
            prev_blank = False
            continue  # a numbered reference entry is never a section heading
        if STOP_SECTION_RE.match(s) or MD_HEADING_RE.match(s) or \
                FIG_CAPTION_RE.match(s) or TABLE_CAPTION_RE.match(s):
            end = j
            note = "ends at the next heading/caption (line %d)" % (j + 1)
            break
        if prev_blank and not looks_like_reference_entry(s) and len(s.split()) >= 5:
            end = j
            note = "ends at the first non-reference paragraph (line %d)" % (j + 1)
            break
        prev_blank = False
    return start, end, note


def classify_context(fname):
    """Role of a corpus file, derived from its name (falls back to main text)."""
    raw = os.path.basename(fname).lower()
    f = re.sub(r"\.(?:txt|md)$", "", raw)
    f = re.sub(r"\.[a-z0-9]{1,5}$", "", f)
    if "cover" in f: return "cover letter"
    if "title" in f: return "title page"
    # A bibliography is a bibliography even when it belongs to the supplement:
    # "suppAll-d.bib" matched the "supp" heuristic below and was swept as
    # supplementary text, so reference entries (their titles and abstracts)
    # fed the M1 inventory and the M1b long-form table with prose that is not
    # the authors' own. The reference-list exclusion in the spec applies to
    # these files exactly like it applies to a "References" section.
    if re.search(r"(^|[^a-z])ref", f) or "bibliograph" in f or re.search(r"\.bib(\.|$)", raw):
        return "references"
    if "abstract" in f: return "abstract"
    if "supp" in f or "extended_data" in f or "appendix" in f: return "supplementary"
    if "method" in f or "m&m" in f: return "Methods"
    if "fig" in f or "legend" in f: return "figure legend"
    if "table" in f: return "table"
    if "reporting" in f or "summary" in f: return "reporting summary"
    return "main text"


def section_label(raw):
    """In-file section heading or display-item caption, else None."""
    s = raw.strip()
    if not s or len(s) > 60:
        return None
    if FIG_CAPTION_RE.match(raw):
        return "figure legend"
    if TABLE_CAPTION_RE.match(raw):
        return "table"
    s = re.sub(r"^#{1,6}\s*", "", s).rstrip(":.").strip()
    for label, pat in SECTION_PATTERNS:
        if pat.match(s):
            return label
    return None


def mask_nonprose(line):
    """Blank out URLs, DOIs, accession numbers, file paths and filenames."""
    for pat in (URL_RE, DOI_RE, ACCESSION_RE, PATH_RE, FILE_RE):
        line = pat.sub(lambda m: " " * len(m.group(0)), line)
    return line


def load_extra_tokens(work):
    path = os.path.join(work, EXTRA_TOKENS_FILE)
    if not os.path.exists(path):
        return []
    tokens = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            t = ln.strip()
            if t and not t.startswith("#"):
                tokens.append(t)
    return tokens


def _expansion_before(tail):
    """Best-effort expansion for 'expansion (TOKEN)': last clause minus filler."""
    clause = re.split(r"[.;:!?]\s+|\n", tail.strip())[-1]
    words = clause.split()
    while words and words[0].lower().strip(",;") in FILLER_WORDS:
        words.pop(0)
    exp = " ".join(words[-8:]).strip(" ,;:")
    return exp if len(exp) >= 6 else ""


# Fillers shared by _expansion_before and the M1b long-form matcher.
FILLER_WORDS = {"we", "the", "our", "in", "and", "using", "used", "with", "a", "an",
                "this", "that", "of", "from", "by", "for", "all", "were", "was", "is",
                "are", "performed", "then", "also", "here", "assessed", "measured",
                "analyzed", "analysed", "evaluated", "scored", "called", "denoted",
                "denotes", "hereafter", "abbreviated", "namely", "termed"}

# ---- M1b: un-abbreviated long forms re-used after their first use ----------
# Separators allowed BETWEEN the words of a long form: a space, a hyphen or any
# dash. Authors mix them ("copy number" / "copy-number" / "copy–number") and the
# mix is exactly the slip this audit exists to catch; at least one separator is
# required, so the fused "copynumber" never matches.
LF_SEPARATOR = r"[\s\-\u2010\u2011\u2012\u2013\u2014]+"
TERM_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-\u2010\u2011\u2012\u2013\u2014]*")
QUOTE_SPAN_RE = re.compile(r"[“\"]([^”\"]{0,300})[”\"]")
# Abbreviation-list form: "CN, copy number" (a legend's own key). The
# expansion is bounded at the next ; | or sentence end.
COMMA_DEF_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9\-\u2010\u2011\u2012\u2013\u2014]*)\s*,\s*([^;|]{6,80})")


def _longform_candidates(phrase):
    """Variant word-lists to match for one recorded expansion / definition head.

    Suffixes of the word list are tried, so a noisy capture ("we measured
    copy-number") still yields the real long form ("copy-number"). PRECISION
    RULES -- an acronym sweep that floods the reviewer with false rows is worse
    than one that misses a little (the manual pass covers the rest):
      * a candidate is at least two words, or one HYPHENATED compound
        (copy-number) -- a bare word like "sequencing", "genome" or "number"
        matches unrelated prose and is dropped;
      * candidates starting with a generic noun/quantifier are dropped;
      * LaTeX page markers, braces, backslashes and parentheticals are dropped;
      * a candidate that is itself another acronym token of the corpus is
        dropped (a noisy expansion of one acronym often quotes another).
    """
    words = [w.strip(",;:.()[]") for w in str(phrase).split()]
    words = [w for w in words if w]
    if not words:
        return []
    out = []
    for i in range(len(words)):
        tail = words[i:]
        if tail[0].lower() in FILLER_WORDS:
            continue
        if len(tail) < 2 and "-" not in tail[0]:
            continue
        if tail[0].lower().rstrip(",;:") in GENERIC_HEAD_WORDS:
            continue
        if any(("\\" in w) or ("{" in w) or ("}" in w) or ("(" in w) for w in tail):
            continue
        out.append(tail)
    seen, uniq = set(), []
    for t in out:
        key = " ".join(t).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return uniq


GENERIC_HEAD_WORDS = {
    "number", "numbers", "reference", "value", "values", "total", "count", "counts",
    "level", "levels", "set", "sets", "list", "lists", "file", "files", "table",
    "tables", "figure", "figures", "page", "pages", "line", "lines", "row", "rows",
    "data", "dataset", "datasets", "sample", "samples", "cell", "cells", "type",
    "types", "group", "groups", "result", "results", "method", "methods", "case",
    "cases", "part", "parts", "end", "ends", "use", "uses", "name", "names",
}


def _phrase_pattern(words):
    """Case/hyphen/plural-tolerant regex for one long-form candidate."""
    subparts = []
    for w in words:
        subparts.extend(p for p in re.split(r"[\-\u2010\u2011\u2012\u2013\u2014]+", w) if p)
    if not subparts:
        raise ValueError("empty phrase")
    body = LF_SEPARATOR.join(re.escape(p) for p in subparts) + r"(?:s|es)?"
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I)


SKIP_IN_INITIALS = {"and", "or", "of", "the", "for", "in", "to", "with", "using",
                    "based", "from", "on", "a", "an", "at", "by", "as", "that"}


def _initials_ok(tok, words):
    """Do the candidate's word initials spell out the acronym (in order)?

    The classical test for "is this phrase really the acronym's expansion":
    the acronym's letters must appear, in order, as the initials of the
    candidate's words (an all-caps word such as RNA contributes all its
    letters; hyphenated compounds contribute a letter per part; the usual
    joining words are skipped). Requiring the first letter to match and >= 75%
    of the acronym to be covered rejects the junk that a loose clause capture
    produces -- "independent modality" can never be scWGS, "reference genome"
    can never be hg19, "number of base pairs with copy number" can never be CN
    -- while keeping every real expansion (copy-number -> CN, single-cell
    whole-genome sequencing -> scWGS, direct nuclear tagmentation and RNA
    sequencing -> DNTR-seq, Pearson correlation coefficient -> PCC).
    """
    want = [c for c in str(tok).lower() if c.isalnum()]
    if not want:
        return True
    letters = []
    for word in words:
        for part in re.split(r"[\-\u2010\u2011\u2012\u2013\u2014]+", word):
            part = part.strip("(),.;:")
            if not part or part.lower() in SKIP_IN_INITIALS:
                continue
            if part.isupper() and len(part) > 1:
                letters.extend(c.lower() for c in part if c.isalnum())
            else:
                letters.append(part[0].lower())
    if not letters or letters[0] != want[0]:
        return False
    i = 0
    for c in letters:
        if i < len(want) and c == want[i]:
            i += 1
    return i >= max(1, int(0.75 * len(want) + 0.999))


def _term_window_before(raw, pos, limit=5):
    """The last few term words immediately before `pos` on one line."""
    words = TERM_TOKEN_RE.findall(raw[:pos])
    window = words[-limit:]
    while window and window[0].lower().strip(",;:") in FILLER_WORDS:
        window.pop(0)
    return window


def _quoted_spans(line):
    """(start, end) of double-quoted spans on one line (quoted titles)."""
    return [(m.start(1), m.end(1)) for m in QUOTE_SPAN_RE.finditer(line)]


def _is_quoted(spans, s, e):
    """Is the match raw[s:e] inside one of the line's double-quoted spans?"""
    return any(qs <= s and e <= qe for qs, qe in spans)


def _window_start(raw, pos):
    """Where the term a parenthetical defines begins (clause start, max 90 chars)."""
    cut = max([m.end() for m in re.finditer(r"[.;:!?]\s+", raw[:pos])] or [0])
    return max(cut, pos - 90)


def _comma_definitions(raw):
    """{acronym_lower: (expansion, span_start, span_end)} for one line's key entries.

    Handles the legend convention "CN, copy number; PCC, Pearson correlation
    coefficient." -- the abbreviation key itself must not be mistaken for
    long-form residue, and an acronym defined only in a key must still count as
    defined. Guards keep ordinary prose out: the entry must end at ";", "|" or
    the end of the line (no sentence-internal period), the expansion is at most
    four words, and its initials must spell the acronym (_initials_ok).
    """
    out = {}
    for m in re.finditer(COMMA_DEF_RE, raw):
        tok = m.group(1).lower()
        if tok in out:
            continue
        body = re.split(r"[;|]", m.group(2))[0].rstrip()
        if body.endswith("."):
            body = body[:-1].rstrip()
        if not body or "." in body:
            continue                      # a sentence, not a key entry
        words = body.split()
        if not (1 <= len(words) <= 4):
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9\-\u2010\u2011\u2012\u2013\u2014]*"
                            r"(?:\s+[A-Za-z][A-Za-z0-9\-\u2010\u2011\u2012\u2013\u2014]*)*",
                            body):
            continue
        if not _initials_ok(tok, words):
            continue
        out[tok] = (body, m.start(1), m.start(2) + len(body))
    return out


def _line_definitions(raw, known_tokens):
    """[(span_start, span_end, acronym)] for the definition parentheticals on one line.

    Both orders are recognised and attributed to the acronym they define:
      * "copy-number (CN)"      -> span covers "copy-number (CN)", acronym cn
      * "DNTR-seq (direct ...)" -> span covers "(direct ...)", acronym dntr-seq
    The abbreviation-list form "CN, copy number" (comma, as in a legend's own
    key; the expansion stops at ; | or the end of the sentence) is recognised
    too, so an abbreviation list is never mistaken for long-form residue.
    A definition whose acronym is not a token of this corpus is ignored.
    """
    out = []
    for m in re.finditer(r"\(([^)]{0,200})\)", raw):
        inner = m.group(1).strip()
        before = raw[:m.start()].rstrip()
        pre = re.search(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9\-\u2010\u2011\u2012\u2013\u2014]*)\s*$",
                        before)
        prev = pre.group(1).lower() if pre else ""
        if len(inner) >= 2 and inner.lower() in known_tokens:
            out.append((_window_start(raw, m.start()), m.end(), inner.lower()))
        elif prev in known_tokens and len(inner) >= 6 and inner.lower() != prev:
            out.append((m.start(), m.end(), prev))
    for tok, (expansion, span_start, span_end) in _comma_definitions(raw).items():
        if tok in known_tokens and expansion.lower() not in known_tokens:
            out.append((span_start, span_end, tok))
    return out


def _prep_lines(swept, known_tokens):
    """Precompute, once per line: masked text, definition spans and quotes.

    Doing this per LINE instead of per (acronym, line) is what keeps the audit
    linear: the naive version re-scanned every line once per acronym (664
    acronyms x 20k lines) and took minutes on a real submission.
    """
    prep = {}
    for fname, li, ctx, masked, raw in swept:
        prep[(fname, li)] = {
            "masked": masked,
            "raw": raw,
            "context": ctx,
            "defs": _line_definitions(raw, known_tokens),
            "quotes": _quoted_spans(raw),
        }
    return prep


# M1b scope: audit the long form only for acronyms whose definition the sweep
# actually recorded. An acronym with no recorded definition is rule (b)'s
# problem ("never defined anywhere"), and its loose clause capture is not
# reliable enough to drive an edit.
M1B_REQUIRE_DEFINITION = True


def _norm_line(raw):
    """Whitespace-insensitive key for one rendered line (page furniture)."""
    return " ".join(str(raw).split())


def audit_long_forms(acro, swept):
    """M1b: long-form uses AFTER the first long-form use of the same context.

    `swept` is every (file, line, context, masked, raw) tuple the token sweep
    saw. A context is a section (abstract / introduction / main text / Methods /
    each legend / table) WITHIN one file. Inside a context the FIRST occurrence
    of the long form is legitimate -- it is that context's own first use, and it
    is where the definition belongs ("copy-number (CN)", or "CN (copy-number)"
    reported as "CN, copy number") -- while every LATER occurrence is a residue,
    because the acronym is available and must be used.

    The audit is deliberately NOT licensed by a local definition. The reported
    production bug is exactly "copy-number (CN)" defined once (abstract) and the
    long form re-used 50+ times in the main text: with local licensing the main
    text had no rows at all, and the M1 token row for CN read "defined at first
    use: Y / consistent: Y" -- invisible end to end. An acronym defined in one
    context and re-used long-form in another is the case this table exists for.

    Returns {token: {"rows": {ctx: [instance, ...]}, "first": {ctx: pos},
                     "short_after": {ctx: n}, "quoted": {ctx: n},
                     "variants": set()}} where instance =
    {file, line, variant, excerpt}.
    """
    by_ctx = defaultdict(list)
    for fname, li, ctx, masked, raw in swept:
        by_ctx[(fname, ctx)].append((fname, li, masked, raw))
    for lines in by_ctx.values():
        lines.sort(key=lambda t: t[1])          # reading order inside the file

    result = {}
    known_tokens = {t.lower() for t in acro}
    prep = _prep_lines(swept, known_tokens)     # definitions/quotes, once per line
    # Page furniture (running heads/footers of a converted PDF) repeats one
    # physical line once per page. Rows stay one-per-occurrence, but the
    # repetition is recorded so the auditor can dispose the family with a
    # single look instead of re-reading the same line 20 times.
    line_repeats = defaultdict(int)
    for fname, _li, _ctx, _masked, raw in swept:
        line_repeats[(fname, _norm_line(raw))] += 1
    for tok, rec in acro.items():
        if rec["exempt"] or not rec["occurrences"]:
            continue
        if M1B_REQUIRE_DEFINITION and not rec.get("defined_lines"):
            continue
        # The definition HEAD ("copy-number (CN)" -> "copy-number") is the most
        # reliable long form; the loose clause capture is only a fallback, and
        # both go through the precision rules of _longform_candidates().
        phrases = list(rec.get("def_phrases", [])) or list(rec["expansions"])
        cands = set()
        for exp in phrases:
            for tail in _longform_candidates(exp):
                cands.add(" ".join(tail))
        if not cands:
            continue
        patterns = []
        for cand in sorted(cands):
            words = cand.split()
            if not any(re.search(r"[A-Za-z]", w) for w in words):
                continue
            # A candidate that is itself an atomic corpus token (RNA, PCR) is
            # another acronym, not this one's long form -- but a hyphenated
            # compound must never be suppressed this way: "Copy-Number" is
            # matched by the strict token detector as well, and dropping
            # "copy-number" as "another acronym" silently killed the whole
            # copy-number -> CN audit on corpora with one capitalised slip.
            if " " not in cand and "-" not in cand and "–" not in cand \
                    and "—" not in cand and cand.lower() in known_tokens:
                continue
            if not _initials_ok(tok, words):
                continue                      # not this acronym's expansion
            try:
                patterns.append((cand, _phrase_pattern(words)))
            except (re.error, ValueError):                       # noqa: PERF203
                continue
        if not patterns:
            continue
        fam = {tok, tok + "s"}
        if tok.endswith("s") and len(tok) >= 3:
            fam.add(tok[:-1])
        out = {"rows": {}, "first": {}, "short_after": {}, "quoted": {}, "variants": set()}
        # _line_definitions() records lowercase acronyms (the artifact keys),
        # while `tok` keeps the casing it was written with -- compare
        # case-insensitively or the acronym's OWN definition site is misread as
        # another term's and its first-use slot is handed to a later residue.
        tkey = tok.lower()
        for (fname_ctx, ctx), lines in sorted(by_ctx.items()):
            first_seen = False
            for (_f, li, masked, raw) in lines:
                info = prep[(fname_ctx, li)]
                def_spans = [d[:2] for d in info["defs"] if d[2] == tkey]
                other_def_spans = [d[:2] for d in info["defs"] if d[2] != tkey]
                hits = []
                for _cand, pat in patterns:
                    for m in pat.finditer(info["masked"]):
                        s, e = m.start(), m.end()
                        if any(ds <= s and e <= de for ds, de in other_def_spans):
                            continue              # another term's definition site
                        # A match inside the acronym's OWN definition span is
                        # this context's legitimate first use ("copy-number
                        # (CN)"), so it consumes the first-use slot but can
                        # never be a residue row itself.
                        own_def = any(ds <= s and e <= de for ds, de in def_spans)
                        hits.append((s, e, m.group(0), own_def))
                # several candidate phrases can match the same span: keep the
                # longest one, one instance per text occurrence
                hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
                taken = []
                for (s, e, text, own_def) in hits:
                    if any(ts <= s and e <= te for ts, te, _t, _d in taken):
                        continue
                    taken.append((s, e, text, own_def))
                for (s, e, text, own_def) in taken:
                    if _is_quoted(info["quotes"], s, e):
                        # A long form inside a quotation (a quoted paper title)
                        # is not this context's first use and must not consume
                        # the slot, or the first real prose use is reported as
                        # a false M1b residue row.
                        out["quoted"][ctx] = out["quoted"].get(ctx, 0) + 1
                        continue
                    if not first_seen:
                        # the FIRST long-form occurrence of this context is the
                        # context's own first use (definition or plain mention)
                        first_seen = True
                        if ctx not in out["first"]:
                            # Files are swept in sorted order; keep the earliest
                            # file's first use instead of overwriting it with
                            # the alphabetically-last file's occurrence.
                            out["first"][ctx] = {"file": fname_ctx, "line": li,
                                                 "variant": text}
                        continue
                    if own_def:
                        continue              # the definition itself, never a residue
                    out["rows"].setdefault(ctx, []).append(
                        {"file": fname_ctx, "line": li, "variant": text,
                         "excerpt": raw.strip()[:120],
                         "line_repeats": line_repeats[(fname_ctx, _norm_line(raw))]})
                    out["variants"].add(text)
            n_short = 0
            for member in fam:
                for occ in acro.get(member, {}).get("occurrences", []):
                    if occ["context"] == ctx and occ["file"] == fname_ctx:
                        n_short += 1
            if n_short:
                out["short_after"][ctx] = n_short
        if out["rows"] or out["first"]:
            result[tok] = out
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    work = os.path.abspath(args.work)
    # OUT defaults to the parent of WORK (e.g. ./review when WORK=./review/work)
    out = os.path.abspath(args.out) if args.out else os.path.dirname(work.rstrip("/"))
    corpus = os.path.join(work, "corpus")
    art_dir = os.path.join(out, "artifacts")
    os.makedirs(art_dir, exist_ok=True)
    if not os.path.isdir(corpus):
        print("ERROR: corpus dir not found: %s. Run convert_corpus.py first." % corpus)
        sys.exit(2)

    extras = load_extra_tokens(work)
    patterns = [("strict", TOKEN_RE), ("gene-symbol", GENE_SYMBOL_RE), ("cell-type", CELL_TYPE_RE)]
    if extras:
        patterns.append(("extra-tokens", re.compile(
            r"\b(?:%s)\b" % "|".join(re.escape(t) for t in sorted(extras, key=len, reverse=True)),
            re.I)))

    acro = defaultdict(lambda: {"occurrences": [], "expansions": set(), "exempt": False,
                                "reason": None, "detectors": set(), "def_phrases": set()})
    reference_notes = []
    swept = []  # (file, line, context, masked, raw) for the M1b long-form audit

    for fname in sorted(os.listdir(corpus)):
        if not fname.endswith(".txt"):
            continue
        role = classify_context(fname)
        if role == "references":
            continue  # reference list excluded per spec
        text = open(os.path.join(corpus, fname), encoding="utf-8", errors="replace").read()
        lines = text.split("\n")
        region = find_reference_region(lines)
        if region:
            reference_notes.append("%s lines %d-%d (%s)" % (
                fname, region[0] + 1, region[1], region[2]))
        current_section = role
        seen_here = set()
        for li, raw in enumerate(lines, 1):
            if region and region[0] <= li - 1 < region[1]:
                continue  # inside the reference list
            label = section_label(raw)
            if label == "references":
                continue  # heading line; the region covers the list itself
            if label:
                current_section = label
            elif current_section == "references":
                current_section = role  # never stay stuck on the reference section
            if raw.lstrip().startswith("### "):
                continue  # synthetic corpus marker (sheet/header/footer)
            line = mask_nonprose(raw)
            swept.append((fname, li, current_section, line, raw))
            # Abbreviation-key entries ("CN, copy number;") are definitions too:
            # without this an acronym defined only in a legend key would be
            # reported as "never defined" AND would skip the M1b audit.
            comma_defs = _comma_definitions(raw)
            for detector, pat in patterns:
                for m in pat.finditer(line):
                    tok = m.group(0).strip("-–—/")
                    if not tok or len(tok) < 2:
                        continue
                    if tok in SI_UNITS:
                        continue
                    if CAPTION_REF_RE.match(tok):
                        continue  # "Fig1"/"Table2" style caption references
                    if detector == "strict" and not re.search(r"[A-Z]", tok):
                        continue
                    if detector != "extra-tokens":
                        if (re.fullmatch(r"[IVXLC]+", tok) and len(tok) < 5
                                and tok not in EXEMPT_REASON):
                            continue  # roman numerals; real look-alikes are EXEMPT above
                        if VERSION_TOKEN_RE.match(tok):
                            continue  # "v4" from "v4.3.0" is a version prefix, not a symbol
                        prefix = GENE_PREFIX_RE.match(tok)
                        if prefix and prefix.group(1).lower() in GENE_STOPWORDS:
                            continue  # week12 / day3 / group1
                    key = (tok, li, m.start())
                    if key in seen_here:
                        continue
                    seen_here.add(key)
                    rec = acro[tok]
                    rec["detectors"].add(detector)
                    rec["occurrences"].append({"file": fname, "line": li,
                                               "context": current_section,
                                               "excerpt": raw.strip()[:120]})
                    if tok in EXEMPT_REASON and not rec["reason"]:
                        rec["exempt"] = True
                        rec["reason"] = EXEMPT_REASON[tok]
                    # definition candidate: "TOKEN (expansion)" or "expansion (TOKEN)"
                    # The left boundary matters: without it "RT-PCR (reverse
                    # transcription PCR)" attributes the RT-PCR expansion to
                    # PCR, and "Single-cell RNA (scRNA-seq)" does the same for
                    # RNA -- a phantom "inconsistent expansion" in the artifact.
                    dm = re.search(r"(?<![A-Za-z0-9])" + re.escape(tok)
                                   + r"\s*\(([^)]{6,})\)", raw)
                    if dm and tok in dm.group(1):
                        # The parenthetical repeats the token itself, so it
                        # defines the longer phrase, not this token.
                        dm = None
                    if dm and not _initials_ok(tok, dm.group(1).split()):
                        # "PCR (see Fig. 2)" is a cross-reference, not a
                        # definition: the parenthetical's words do not spell the
                        # token. Recording it as an expansion fabricated both an
                        # expansion and a "defined at first use: Y".
                        dm = None
                    defines = bool(dm)
                    if dm:
                        rec["expansions"].add(dm.group(1).strip())
                    else:
                        pos = raw.find("(" + tok + ")")
                        if pos > 0:
                            exp = _expansion_before(raw[:pos])
                            if exp:
                                rec["expansions"].add(exp)
                                defines = True
                    if not defines and tok.lower() in comma_defs:
                        expansion = comma_defs[tok.lower()][0]
                        if expansion.lower() != tok.lower():
                            rec["expansions"].add(expansion)
                            rec["def_phrases"].add(expansion)
                            defines = True
                    if defines:
                        rec.setdefault("defined_lines", []).append((fname, li))
                        # The expansion-first form ("copy-number (CN)") also
                        # records the exact term window before the parenthetical,
                        # so the M1b matcher sees the long form as written even
                        # when the clause-based expansion picked up extra words.
                        pos2 = raw.find("(" + tok + ")")
                        if pos2 > 0:
                            head = TERM_TOKEN_RE.findall(raw[:pos2])
                            window = head[-6:]
                            while window and window[0].lower().strip(",;:") in FILLER_WORDS:
                                window.pop(0)
                            phrase = " ".join(window).strip(" ,;:")
                            if len(phrase) >= 6 and re.search(r"[A-Za-z]", phrase):
                                rec["def_phrases"].add(phrase)

    longform = audit_long_forms(acro, swept)

    rows = []
    for tok in sorted(acro, key=lambda t: t.lower()):
        rec = acro[tok]
        occs = rec["occurrences"]
        ordered = sorted(occs, key=lambda o: (rank(o["context"]), o["file"], o["line"]))
        firsts = {}
        for o in ordered:
            firsts.setdefault(o["context"], o)
        first = ordered[0] if ordered else None
        defined_lines = rec.get("defined_lines", [])
        if first and (first["file"], first["line"]) in defined_lines:
            defined_at_first = "Y"
        elif defined_lines:
            defined_at_first = "defined-later"
        else:
            defined_at_first = "never"
        lf = longform.get(tok, {})
        long_rows = lf.get("rows", {})
        repeats = {}
        for insts in long_rows.values():
            for inst in insts:
                if inst.get("line_repeats", 1) > 1:
                    repeats["%s:%d" % (inst["file"], inst["line"])] = inst["line_repeats"]
        rows.append({
            "acronym": tok,
            "exempt": rec["exempt"],
            "exempt_reason": rec["reason"],
            "detector": "+".join(sorted(rec["detectors"])),
            "expansions": sorted(rec["expansions"]),
            "n_occurrences": len(occs),
            "first_occurrence_per_context": {k: "%s:%d" % (v["file"], v["line"])
                                             for k, v in firsts.items()},
            "files": sorted({o["file"] for o in occs}),
            "defined_at_first_use": defined_at_first,
            "expansion_consistent": len(rec["expansions"]) <= 1,
            # M1b (rule (k)): long forms re-used after this context's first use.
            # `short_form_uses` counts the acronym's own inflectional family
            # (CN + CNs) per context, so rule (c) can tell an orphan definition
            # from a definition whose long form is still in use.
            "short_form_uses": lf.get("short_after", {}),
            "long_form_after_first_use": {k: ["%s:%d" % (i["file"], i["line"])
                                              for i in v] for k, v in long_rows.items()},
            "long_form_after_first_use_total": sum(len(v) for v in long_rows.values()),
            "long_form_variants_seen": sorted(lf.get("variants", set())),
            "long_form_first_use": {k: "%s:%d" % (i["file"], i["line"])
                                    for k, i in (lf.get("first") or {}).items()},
            "long_form_quoted_skipped": lf.get("quoted", {}),
            # Page furniture repeats (identical line rendered once per page):
            # the markdown table annotates these rows, and this map carries the
            # same information into findings.json.
            "long_form_repeat_notes": repeats,
        })

    md = ["# M1 — ACRONYM INVENTORY (artifact)", "",
          "Every unique acronym-like token in the corpus (reference lists, DOIs, accessions, URLs, file paths, SI units excluded).",
          "Rows whose exempt? cell is `audit` must be audited row by row; EXEMPT rows are universal abbreviations, statistical symbols or generic tokens.",
          "Detectors: strict (internal capital / all-caps), gene-symbol, cell-type, extra-tokens (WORK/extra_acronyms.txt).",
          "Known limit: a token with no internal capital and no digit (e.g. a lowercase `tnf`) needs WORK/extra_acronyms.txt or the manual pass in references/sweeps.md M1.",
          "'long form after first use' = uses of the un-abbreviated long form AFTER this context's own first use (case/hyphen/plural-tolerant); each one is one M1b row below (finding rule M1(k)). The audit covers every acronym with a recorded definition, in every context, because the reported failure mode is a definition in one context (e.g. the abstract) followed by long-form re-use in another (e.g. the main text).",
          "",
          "Reference-list regions skipped (boundary is explicit, never silent):",
          ] + (["- " + n for n in reference_notes] or ["- none"]) + [
          "",
          "| acronym | exempt? | expansion(s) as written | n | defined at first use? | long form after first use (n) | files | first per context | consistent? |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        exp = "; ".join(r["expansions"]) or "—"
        fpc = "; ".join("%s: %s" % (k, v) for k, v in
                        sorted(r["first_occurrence_per_context"].items(),
                               key=lambda kv: (rank(kv[0]), kv[1])))
        lfa = "; ".join("%s: %d" % (k, len(v)) for k, v in
                        sorted(r["long_form_after_first_use"].items(), key=lambda kv: rank(kv[0])))
        if r.get("long_form_quoted_skipped"):
            lfa += (" (plus %d inside double quotes -- quoted titles stay verbatim)"
                    % sum(r["long_form_quoted_skipped"].values()))
        exempt_cell = ("EXEMPT (%s)" % r["exempt_reason"]) if r["exempt"] else "audit"
        md.append("| %s | %s | %s | %d | %s | %s | %s | %s | %s |" % (
            r["acronym"], exempt_cell,
            exp.replace("|", "\\|"), r["n_occurrences"], r["defined_at_first_use"],
            lfa.replace("|", "\\|") or "—",
            ", ".join(r["files"]).replace("|", "\\|"),
            fpc.replace("|", "\\|"),
            "Y" if r["expansion_consistent"] else "N"))

    # M1b — one row per long-form instance after its first use (rule M1(k))
    lf_rows = []
    for r in rows:
        lf = longform.get(r["acronym"]) or {}
        for ctx, insts in sorted(lf.get("rows", {}).items(), key=lambda kv: rank(kv[0])):
            for inst in insts:
                lf_rows.append((r["acronym"], ctx, inst))
    md += ["",
           "## M1b — LONG FORMS RE-USED AFTER THEIR FIRST USE (rule M1(k); one row = one finding)", "",
           "Each row is an occurrence of an acronym's un-abbreviated long form, after that "
           "context's own first use of the long form. The first long-form occurrence per context "
           "(including a definition such as `copy-number (CN)`) and any long form inside double "
           "quotes are never rows. "
           "The remedy is rule M1(k) + P1a in the revise skill: substitute the ACRONYM (never "
           "expand a short form), keep the context's first-use/definition occurrence, pluralise "
           "to match (`copy numbers` -> `CNs`), and leave quoted titles verbatim (dispose those "
           "as OK with a reason).",
           "",
           "| acronym | context | file:line | long form as written | excerpt |",
           "|---|---|---|---|---|"]
    for (acr, ctx, inst) in lf_rows:
        note = (" [same line x%d in this file]" % inst["line_repeats"]
                if inst.get("line_repeats", 1) > 1 else "")
        md.append("| %s | %s | %s:%d | %s | %s%s |" % (
            acr, ctx, inst["file"], inst["line"], inst["variant"].replace("|", "\\|"),
            inst["excerpt"].replace("|", "\\|"), note))
    if not lf_rows:
        md.append("| — | — | — | — | no long-form re-use detected |")
    with open(os.path.join(art_dir, "M1_acronyms.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(art_dir, "M1_acronyms.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    n_audit = sum(1 for r in rows if not r["exempt"])
    n_lf = len(lf_rows)
    print("M1 artifact: %d unique tokens (%d to audit, %d exempt); M1b: %d long-form re-use "
          "row(s) across %d acronym(s). Artifacts in %s" % (
              len(rows), n_audit, len(rows) - n_audit, n_lf,
              len({r[0] for r in lf_rows}), art_dir))


if __name__ == "__main__":
    main()

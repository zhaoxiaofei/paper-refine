# -*- coding: utf-8 -*-
# Part 01/03 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations


# ---- text-level style & consistency (rules FMT-T8a..FMT-T8e) --------------
# These run over the PARAGRAPH TEXT of a document (docx here, and the LaTeX/
# markdown sources through the pipeline's scanner), because the classes they
# catch are not OOXML problems: citation formats, parentheses, redundancy and
# term variants. Findings are reported; the citation/spelling fixes apply only
# where the edit is mechanical and policy-driven (see fix_document).

CIT_AUTHOR = (r"[A-Z][a-z\u2019'.\-]+(?:\s+[A-Z][A-Za-z\u2019'.\-]+)?"
              r"(?:\s+(?:&|and)\s+[A-Z][A-Za-z\u2019'.\-]+)?(?:\s+et\s+al\.?)?")
CIT_YEAR = r"(?:19|20)\d\d[a-z]?"
_J = JOURNAL_RE.pattern
CIT_YEAR_JOURNAL = re.compile(rf"\(({CIT_AUTHOR}),\s*({CIT_YEAR}),\s*({_J})\)")
CIT_JOURNAL_YEAR = re.compile(rf"\(({CIT_AUTHOR}),\s*({_J}),\s*({CIT_YEAR})\)")
CIT_YEAR_ONLY = re.compile(
    rf"\(({CIT_AUTHOR}),\s*{CIT_YEAR}(?:[a-z])?(?:,\s*{CIT_YEAR})?"
    rf"(?:;\s*{CIT_AUTHOR},\s*{CIT_YEAR}(?:[a-z])?(?:,\s*{CIT_YEAR})?)*\)")

# Lexical variants that mean the same word (US/UK spelling). Only these are
# normalized automatically: "analyses" is also the plural of "analysis", so that
# pair is deliberately absent.
SPELLING_PAIRS = (("tumour", "tumor"), ("tumours", "tumors"), ("tumoural", "tumoral"),
                  ("colour", "color"), ("colours", "colors"), ("behaviour", "behavior"),
                  ("modelling", "modeling"), ("labelled", "labeled"),
                  ("catalogue", "catalog"), ("acknowledgement", "acknowledgment"))


def spelling_nonprose_mask(text: str) -> str:
    """`text` with URLs/e-mails and inline code spans blanked, same length.

    A spelling rule is a rule about prose. Rewriting the minority spelling
    inside `https://example.org/colour-chart` (or a code literal) corrupts the
    link while making the finding look cleared.
    """
    out = URL_RE.sub(lambda m: " " * len(m.group(0)), text or "")
    # A scheme-less DOI path is a URL too: the spelling rule must never rewrite
    # a minority spelling inside `doi.org/10.1000/colour-map`.
    out = re.sub(r"\b(?:dx\.)?doi\.org/[^\s<>\"']+|\b10\.\d{4,9}/[^\s<>\"']+",
                 lambda m: " " * len(m.group(0)), out)
    return re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), out)


def spelling_minority_targets(prose_texts: list) -> dict:
    """{minority_form: target_form} for every mixed US/UK spelling pair.

    The document's own majority decides. On an exact count tie the form that
    occurs FIRST in the document is the target -- a deterministic choice, so a
    1:1 mix (`modelling` x1 vs `modeling` x1) no longer produces a mechanical
    row the fixer cannot clear (that tie made the whole file's repairs fail
    their self-verification and the original was kept).
    """
    blob = "\n".join(spelling_nonprose_mask(t) for t in prose_texts)
    out = {}
    for a, b in SPELLING_PAIRS:
        ca = len(re.findall(rf"\b{re.escape(a)}\b", blob, re.I))
        cb = len(re.findall(rf"\b{re.escape(b)}\b", blob, re.I))
        if not (ca and cb):
            continue
        if ca != cb:
            out[a if ca < cb else b] = a if ca > cb else b
            continue
        first_a = re.search(rf"\b{re.escape(a)}\b", blob, re.I)
        first_b = re.search(rf"\b{re.escape(b)}\b", blob, re.I)
        pa = first_a.start() if first_a else len(blob)
        pb = first_b.start() if first_b else len(blob)
        out[b if pa <= pb else a] = a if pa <= pb else b
    return out

# Hyphenated compounds whose ATTRIBUTIVE use must be hyphenated. The noun use
# ("the copy number of a locus") is correct without a hyphen and is untouched.
HYPHEN_COMPOUNDS = (("copy-number", "copy number"), ("single-cell", "single cell"),
                    ("whole-genome", "whole genome"), ("long-read", "long read"),
                    ("short-read", "short read"))

# Function words that introduce the compound's NOUN use ("the copy number of a
# locus", "a single cell was counted") rather than an attributive noun. The
# fixer must leave those open: the rule's own documentation promises the noun
# use is untouched, and a mechanical rewrite cannot know a following open-class
# word is a noun, but these are unambiguous. The coordinators "and"/"or" stay
# here on purpose: "a single cell and its nucleus" coordinates nouns, and a
# mechanical rewrite of it ("a single-cell and its nucleus") would corrupt the
# text; a coordinated ATTRIBUTIVE use ("single cell and bulk RNA-seq") is a
# reported-only gap rather than a safe automatic edit.
HYPHEN_NOUN_FOLLOWERS = ("of", "the", "a", "an", "and", "or", "in", "on", "at",
                         "to", "for", "with", "from", "by", "as", "that", "which",
                         "who", "whose", "is", "are", "was", "were", "be", "been",
                         "being", "has", "have", "had", "does", "do", "did", "can",
                         "could", "may", "might", "must", "should", "would", "will",
                         "per")

# Finite verbs that make the preceding compound the SUBJECT ("Each single cell
# expressed ...", "The copy number increased ..."), i.e. the documented noun
# use. Every regular -ed form is caught by the suffix rule below; this list
# carries the common irregular and third-person forms that a mechanical
# rewrite used to hyphenate ("single cell shows ..." -> "single-cell shows").
HYPHEN_VERB_FOLLOWERS = frozenset({
    "shows", "remains", "varies", "differs", "depends", "contains", "comprises",
    "includes", "requires", "provides", "yields", "produces", "allows", "enables",
    "affects", "drives", "causes", "predicts", "reflects", "occurs", "exists",
    "appears", "rose", "fell", "grew", "grows", "led", "leads", "made", "makes",
    "took", "takes", "gave", "gives", "found", "finds", "drove", "held", "kept",
    "left", "met", "ran", "runs", "came", "comes", "went", "goes", "stood", "stands",
})


def hyphen_attributive_re(split: str):
    """The open form hyphenates only when a NOUN follows it.

    A following function word or finite verb opens the compound's noun use, so
    the mechanical fixer leaves it alone; the same pattern drives the scanner's
    FMT-T8e count and the fixer's rewrite (parity: the fixer must never edit an
    occurrence the scanner does not report). `-ed` covers the regular past
    forms ("expressed", "increased") without a verb lexicon.
    """
    followers = "|".join(re.escape(w) for w in
                         tuple(HYPHEN_NOUN_FOLLOWERS) + tuple(sorted(HYPHEN_VERB_FOLLOWERS)))
    return re.compile(
        rf"\b{re.escape(split)}(?=\s+(?!(?:(?:{followers})\b|[A-Za-z]+ed\b))[A-Za-z])")


# Words that make a repeated phrase part of the document scaffolding rather than
# a distinctive name ("Supplementary Table S1 three times in a paragraph").
REPETITION_STOPWORDS = {"supplementary", "note", "figure", "table", "section", "extended",
                        "data", "methods", "fig", "eq", "equation", "chapter", "panel",
                        "professor", "dr", "supp", "respectively", "significantly"}

# Pairs that mean DIFFERENT things and are routinely confused in manuscripts.
# A row fires when both members appear in the same document (paragraph-level
# co-occurrence is reported in the row), and the agent must dispose it by
# choosing the precise term and (where useful) defining it once.
CONFUSABLE_PAIRS = (
    ("emulate", "simulate"), ("emulation", "simulation"), ("emulated", "simulated"),
    ("accuracy", "precision"), ("sensitivity", "specificity"),
    ("validate", "verify"), ("validation", "verification"),
    ("correlation", "corroboration"), ("correlate", "corroborate"),
    ("quantitative", "qualitative"),
    ("ranking", "score"), ("rank", "score"),
    ("effective", "efficient"), ("comprise", "compose"),
    ("incidence", "prevalence"), ("mortality", "morbidity"),
    ("detection", "quantification"), ("limit of detection", "limit of quantification"),
    ("infer", "impute"), ("estimate", "measure"),
)

# Terms whose occurrence pattern a manuscript-wide ledger should show (M8).
KEY_TERMS = ("CNV", "CN ", "copy number", "copy-number", "integer CN", "CNV call",
             "copy-number call", "caller", "calling", "emulated", "simulated",
             "qualitative", "quantitative", "mean", "median", "accuracy", "precision",
             "scWGS", "scRNA-seq", "ground truth", "benchmark", "ploidy")

# Quantity units for the LaTeX formatting rule (a number+unit should be \SI/\num).
UNIT_RE = re.compile(
    r"^\s*(?:%|percent|fold|×|x\b|kb|Mb|Gb|bp|nm|µm|um|mm|cm|mL|µL|uL|ng|µg|ug|mg|"
    r"h\b|min\b|s\b|ms\b|°C|K\b|mM|µM|uM|nM|pM|mol|M\b)", re.I)
# The exponent is part of the number: reading `1.2e-4` as the two numbers `1`
# and `4` put values the author never wrote into the M30 numbers ledger (and
# left the real p-value out of it).
NUMBER_RE = re.compile(
    # Thin/NBSP separators are thousands separators too (`12 000` with U+2009
    # must be one number, not 12 and 000). The exponent sign may be the
    # typographic minus Word/journals emit, or `1.2e−4` splits into 1 and 4.
    # A LEADING sign is part of the value (`-80` is not `80`), but a hyphen
    # BETWEEN two digits is a range separator: the lookbehind sits before the
    # sign, so `10-20` is 10 then 20, while ` -80`/`(-80)` keep the minus.
    # The decimal alternative allows a glued unit (`7.5mg`) and does NOT let
    # the engine backtrack the fraction away to record the integer 7.
    r"(?<![\w.])((?:[-\u2212]?\d[\d,\u2009\u202f\u00a0]*\.\d+"
    r"(?:[eE][+\-\u2212]?\d+)?)(?![\d]|\.\d)"
    r"|(?:[-\u2212]?\d[\d\u2009\u202f\u00a0]*(?:,\d{3})*"
    r"(?:[eE][+\-\u2212]?\d+)?)(?![\w]|\.\d))")

# --------------------------------------------------------------------------
# Spelled-out numbers as NUMERIC artifacts (2026-10-17).
#
# The M4 ledger and the M30 seed read digits only, so a claim written in words
# escaped both: "three karyotype-defined subpopulations", "seven parental
# antigens", "four of the five neural-network outputs", "one row per sequencing
# run". Those are counts a shipped table can prove or contradict exactly like a
# digit, so they belong to the same artifact family -- otherwise a count claim
# can be wrong and no mechanical check ever sees it.
#
# Precision matters more than recall here (every row asks a session to dispose
# it): a word number is a COUNT only in a count context -- before a plural noun,
# in "N of the M", before a unit, or in "one X per Y". The pronoun and idiom
# uses ("one of them", "one another", "at once", "no one", "one may") are not
# counts and are dropped by the context test below.
NUMBER_WORD_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
NUMBER_WORD_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy",
                    "eighty", "ninety")
_WORD_NUMBER_ALT = "|".join(
    sorted(list(NUMBER_WORD_UNITS) + ["hundred", "thousand", "million", "billion"],
           key=len, reverse=True))
# "twenty-one", "twenty one", "one hundred", "one hundred and five",
# "one hundred and twenty five", "two million". A bounded number of tokens
# covers every count a manuscript states (the scale words carry the magnitude),
# and the whole phrase must match: the old three-token cap split
# "one hundred and twenty five" into 120 and 5, and the missing million/billion
# alternatives read "two million" as 2.
NUMBER_WORD_RE = re.compile(
    r"(?<![\w-])((?:" + _WORD_NUMBER_ALT + r")"
    r"(?:[-\s](?:and[-\s])?(?:" + _WORD_NUMBER_ALT + r")){0,20})(?![\w-])", re.I)
# Plural nouns that are real count targets, plus the plural-looking words that
# are not nouns (so "one is", "two was", "three as" never count).
PLURAL_NOUN_EXCEPTIONS = frozenset({
    "is", "was", "has", "does", "this", "his", "hers", "ours", "yours", "theirs",
    "its", "as", "less", "always", "various", "perhaps", "across", "unless",
    "thus", "plus", "versus", "towards", "afterwards", "nevertheless", "whereas",
    "yes", "class", "process", "analysis", "basis", "status",
    "hypothesis", "synthesis", "emphasis", "diagnosis", "prognosis", "thesis",
    "crisis", "focus", "virus", "apparatus", "census", "consensus", "bias",
    "means", "news", "physics", "mathematics", "economics", "genomics", "omics",
})
IRREGULAR_PLURALS = frozenset({
    "data", "criteria", "phenomena", "analyses", "children", "people", "mice",
    "indices", "matrices", "vertices", "axes", "genera", "loci", "taxa",
})
# Idiom/pronoun followers that make "one" (and only "one") a non-count.
ONE_NON_COUNT_FOLLOWERS = frozenset({
    "another", "hand", "side", "way", "thing", "time", "day", "bit", "step",
    "of", "that", "which", "who", "whom", "whose", "where", "such", "may",
    "can", "could", "should", "is", "was", "does", "did", "has", "had", "will",
    "would", "must", "might", "shall", "needs", "wants", "might",
})
# A label noun immediately before the number makes it part of a NAME ("Run two",
# "Patient three", "Table four"), not a count of that many things.
WORD_NUMBER_LABEL_RE = re.compile(
    r"(?i)\b(?:run|step|phase|group|round|patient|donor|sample|dataset|figure|"
    r"table|experiment|trial|cohort|method|version|set|batch|replicate|timepoint|"
    r"condition|arm|case|panel|clone|cell\s+line)\s+$")
COUNT_ADJECTIVES = (
    "additional", "further", "other", "more", "different", "independent",
    "separate", "distinct", "major", "minor", "main", "key", "novel", "new",
    "paired", "single", "principal", "primary", "secondary", "remaining",
)


_WORD_NUMBER_SCALES = frozenset({"hundred", "thousand", "million", "billion"})


def _word_number_value(words: str):
    """The integer a spelled-out number denotes, or None when unparsable."""
    total, current = 0, 0
    toks = [t for t in re.split(r"[-\s]+", str(words or "").lower()) if t]
    for idx, tok in enumerate(toks):
        if tok == "and":
            # "one hundred and five" is one number; "three and five" is a list
            # of two. `and` joins digits only after a scale word.
            if idx == 0 or toks[idx - 1] not in _WORD_NUMBER_SCALES:
                return None
            continue
        if tok == "hundred":
            current = (current or 1) * 100
        elif tok == "thousand":
            total += (current or 1) * 1000
            current = 0
        elif tok == "million":
            total += (current or 1) * 1_000_000
            current = 0
        elif tok == "billion":
            total += (current or 1) * 1_000_000_000
            current = 0
        elif tok in NUMBER_WORD_UNITS:
            current += NUMBER_WORD_UNITS[tok]
        else:
            return None
    value = total + current
    return value if value > 0 else None


def _word_number_is_count(text: str, start: int, end: int, written: str) -> bool:
    """True when the spelled-out number at [start, end) is used as a count."""
    tail = text[end:]
    first = re.split(r"[-\s]+", (written or "").strip().lower())[0]
    single_one = (written or "").strip().lower() == "one"
    if WORD_NUMBER_LABEL_RE.search(text[max(0, start - 24):start]):
        return False
    if first in ("hundred", "thousand", "million", "billion"):
        # "a hundred samples" is a count even though the match starts at the
        # scale word. The indefinite article is the count's determiner; without
        # this branch the very common "a hundred"/"a thousand" form escaped the
        # numbers ledger and the M30 seed.
        if not re.search(r"(?i)\ba\s+$", text[max(0, start - 4):start]):
            return False
    # "one another", "one of them", "one may", "no one", "at once": pronouns and
    # idioms, not counts.
    m = re.match(r"\s+([A-Za-z][A-Za-z'-]*)", tail)
    follower = (m.group(1).lower() if m else "")
    # "four of the five ...", "three of the nine donors": a count pair. This
    # must win BEFORE the pronoun test: `one` has `of` as a non-count follower,
    # which silently dropped the most common count-pair subject ("one of the
    # five donors").
    if re.match(r"\s+of\s+(?:the\s+|these\s+|those\s+|its\s+|their\s+)?"
                r"(?:" + _WORD_NUMBER_ALT + r"|\d+)\b", tail, re.I):
        # "Four of the five ..." is a count pair; "one of the five ..." uses
        # `one` as a pronoun, so only the explicit count is a numeric artifact.
        return not single_one
    if first == "one" and follower in ONE_NON_COUNT_FOLLOWERS:
        return False
    if re.search(r"(?i)\b(?:no|for|at|in)\s+$", text[max(0, start - 12):start]) \
            and first == "one":
        return False
    # "two orders of magnitude", "threefold", "four percent", "five times".
    if re.match(r"\s*(?:percent|%|fold\b|times\b|orders?\s+of\s+magnitude)", tail, re.I):
        return True
    # "one row per sample", "three callers per dataset".
    if re.match(r"\s+(?:[A-Za-z][A-Za-z-]*\s+){0,2}per\s+", tail):
        return True
    if single_one:
        # A bare "one" is usually a pronoun or a label ("Run one used 3
        # samples", "one currently requires ..."). It counts only when a
        # determiner introduces it ("the one caller") -- the plural rule below
        # then still applies -- or when a plural noun follows immediately.
        before = text[max(0, start - 16):start].lower()
        if not re.search(r"\b(?:the|a|an|this|that|these|those|its|their|our|all|"
                         r"both|any|each|every|only|exactly)\s+$", before):
            m_one = re.match(r"\s+([A-Za-z][A-Za-z-]*)\b", tail)
            if not (m_one and (
                    m_one.group(1).lower().strip("-") in IRREGULAR_PLURALS
                    or (len(m_one.group(1)) >= 4
                        and m_one.group(1).lower().endswith("s")
                        and m_one.group(1).lower() not in PLURAL_NOUN_EXCEPTIONS))):
                return False
    # Number + (optional adjectives) + noun: the head noun must be PLURAL (or an
    # irregular plural). Look a few tokens ahead because authors put attributive
    # nouns and hyphenated compounds between the number and the head noun
    # ("three karyotype-defined cell subpopulations", "seven parental antigens");
    # a singular head ("one hand", "one case") is left out on purpose, which
    # keeps the ledger's precision.
    for tok in re.findall(r"[A-Za-z][A-Za-z-]*", tail)[:4]:
        noun = tok.lower().strip("-")
        if noun.endswith("ly"):
            # An adverb between the number and its noun ("one currently
            # requires ..."): skip it and keep looking.
            continue
        if noun in IRREGULAR_PLURALS:
            return True
        if len(noun) >= 4 and noun.endswith("s") and noun not in PLURAL_NOUN_EXCEPTIONS:
            return True
    return False


def word_number_rows(text: str) -> list:
    """[{start, end, number, written}] for spelled-out COUNT artifacts."""
    out = []
    for m in NUMBER_WORD_RE.finditer(str(text or "")):
        raw = m.group(1)
        written = raw.strip()
        # A conjunctive list ("three and five patients") is not one number: the
        # regex consumes it as a phrase, so split at an `and` that does not
        # follow a scale word and record each member's own count.
        parts = re.split(r"(\s+and\s+)", raw)
        conjunctive = any(
            part.lower().strip() == "and" for part in parts) and (
                _word_number_value(written) is None)
        if conjunctive:
            pos = m.start(1)
            for part in parts:
                if re.fullmatch(r"\s+and\s+", part):
                    pos += len(part)
                    continue
                piece = part.strip()
                lead = len(part) - len(part.lstrip())
                start, end = pos + lead, pos + lead + len(piece)
                value = _word_number_value(piece)
                if value is not None and _word_number_is_count(text, start, end, piece):
                    out.append({"start": start, "end": end,
                                "number": str(value), "written": piece})
                pos += len(part)
            continue
        value = _word_number_value(written)
        if value is None:
            continue
        if not _word_number_is_count(text, m.start(), m.end(), written):
            continue
        out.append({"start": m.start(), "end": m.end(),
                    "number": str(value), "written": written})
    return out

# --------------------------------------------------------------------------
# Disposition tiers.
#
# A "finding"-tier row is not a style preference: it is a defect an editor, a
# reviewer or a copyeditor would raise, so the review must either turn it into
# a finding or close it with a reason about ITS OWN bar ("the sentence is inside
# a Methods enumeration and the Methods bar is 60 words"), never with a generic
# "no journal rule".  The pipeline records (and, with --strict-dispositions,
# fails) a disposition column that repeats one boilerplate reason across many
# rows, because that is how a real run closed 96 rows at once and shipped the
# very sentences the operator then flagged.
FINDING_TIER_RULES = {
    "FMT-S1",    # break-only paragraph / blank page
    "FMT-S3",    # running head on the title page
    "FMT-S4",    # tracked changes in a final package
    "FMT-T1",    # mixed quotation marks
    # The M20 sweep's dash/quote family: sweeps.md lists "mixed straight/curly
    # quotation marks, a spaced hyphen used as a dash, or em-dash density above
    # the user's cap -> finding (editorial: the revision arm rewrites)", and the
    # pipeline's own M20 seed text calls the em-dash density a findings row for
    # the revision/integration arms. Leaving FMT-P1/FMT-P2 advisory let a
    # reviewer close them as "editorial preference only" -- a disposition the
    # finding-tier bar forbids -- and the auditor, which attacks finding-tier
    # rows only, never saw them.
    "FMT-P1",    # em-dash density above the policy cap
    "FMT-P2",    # a spaced hyphen used as a dash
    "FMT-T8b",   # nested parentheses
    "FMT-T8c",   # a distinctive term repeated inside one short passage
    "FMT-T9c",   # long sentence / long list-paragraph (tiered by section)
    "FMT-T9d",   # confusable term pairs (emulate/simulate, ...)
    "FMT-T9f",   # a term the manuscript itself has to gloss
    "FMT-T9g",   # LaTeX quantity outside \SI/\num
    "FMT-T9i",   # paragraph structure (mega-paragraph)
    "FMT-T9j",   # two term families competing for one concept (CN vs CNV)
    "FMT-T9k",   # a narrative paragraph built from ONE sentence
    "FMT-T10f",  # a heading whose section holds exactly ONE subsection
    "FMT-T8f",   # indentation convention broken between sibling paragraphs/captions
    "FMT-T8g",   # the front page is split by a rendered page break (keywords on page 2)
    "FMT-T8h",   # the cover letter exceeds its two-page budget
    # The cover letter formatted in the MANUSCRIPT template (Title/Author-List
    # front matter, logo header, page furniture) although the venue ships no
    # cover-letter template: the reported operator failure. The journal's own
    # guideline/template text that REQUIRES that formatting is the only override
    # the disposition gate accepts.
    "FMT-CL1",
    # Text hygiene and embedded-artifact integrity: a doubled word is a typo an
    # editor raises, and an image delivered off its own aspect ratio changes the
    # geometry the figure shows.
    "FMT-G1",    # a doubled article/preposition ("the the")
    "FMT-IM1",   # an embedded image rescaled without its aspect ratio
    "FMT-IM4",   # a raster placed below the venue's stated resolution floor
    # Layout integrity (2026-10-19): a table's grid disagrees with its cells, an
    # identifier cannot fit its column, a footer carries two PAGE fields, or a
    # figure's own label spells a manuscript term differently. All four are
    # visible in the delivered artifact and are the classes a text scan misses.
    "FMT-TB4",   # w:tblGrid disagrees with the cells' w:tcW
    "FMT-TB5",   # an identifier token cannot fit its column
    "FMT-S10",   # more than one PAGE field in a referenced header/footer part
    "FMT-IM5",   # a figure label spells a manuscript term differently
    "FMT-IM6",   # a figure's own text is below the venue's printed-point floor
    "FMT-T6h",   # a bibliography bold run covers a year or a page range
    "FMT-AV3",   # a "shipped/deposited" claim with no locator
    "FMT-AV4",   # two submitted surfaces make opposite availability claims
    # Cross-surface / argument-level defects (2026-10-19): these are the classes
    # the two round-2 winners shipped while every sentence-local rule passed.
    "FMT-T9L",   # a logic inversion (test asserts its premise; expectation implies a result)
    "FMT-T9A",   # "the X described above" with no antecedent X
    "FMT-T9U",   # a coined/quantified term the manuscript never defines
    "FMT-CN1",   # a count sentence ("the six metrics are ...") enumerates a different number
    "FMT-LG1",   # a legend asserts the paper's conclusion from a descriptive panel
    "FMT-LG2",   # one legend enumeration uses several connectives
    "FMT-ST1",   # a Holm-adjusted p is below the stated family's floor
    "FMT-SR1",   # a Reporting Summary field is unanswered
    "J6-CONTRADICTION",  # two submitted surfaces/paragraphs make opposite claims
    # A comma with no space after it inside a list ("Ginkgo d7c7790,
    # AneuFinder 1.34.0,copynumber 1.38.0"): a copy-editing defect a reviewer
    # raises, and one that has shipped twice (the CNB Reporting Summary PDF and
    # the supplementary .bib's keyword lists, 2026-10-15).
    "FMT-G4",
    # The venue's own TABLE rule (declared in the profile, never invented here):
    # a table without its caption, a caption on the wrong side, a table before
    # the tables area. An editor/copyeditor raises all three, so they are
    # findings the review must dispose and a producing stage must fix.
    "FMT-TB1",   # the table carries no caption
    "FMT-TB2",   # the caption sits on the other side than the venue requires
    "FMT-TB3",   # the table appears before the tables area
    # The same rule for FIGURES (a graphical abstract and the like are the
    # profile's `figures.special` entries, never a silent exemption here).
    "FMT-FG1",   # the figure carries no caption / legend next to it
    "FMT-FG2",   # the caption sits on the other side than the venue requires
    "FMT-FG3",   # the figure (or its collected legend) appears before the figures area
    # Reference-entry shape (FMT-R1..R5): an editor/copyeditor raises a malformed
    # or unretrievable reference, so the review must dispose every one; a venue
    # whose profile does not ask for preprint rows simply gets no R5 row.
    "FMT-R1",    # the journal/volume field is malformed ("Volume 11-2020")
    "FMT-R2",    # the entry names no venue/locator at all
    "FMT-R3",    # a repository/software citation with no version or DOI
    "FMT-R4",    # a bioRxiv-style identifier carrying a foreign DOI prefix
    "FMT-R5",    # a preprint / trial-in-progress abstract (profile-gated)
    # Display-item order (FMT-O1): a numbered item is first cited out of order
    # (profile-gated by `"numbering": "citation"`).
    "FMT-O1",
    # Glued front matter (FMT-X2): two words/addresses fused with no separator.
    "FMT-X2",
    # Publisher leftovers (FMT-L1): the profile's own list of another
    # publisher's boilerplate phrases.
    "FMT-L1",
    # Availability statements (FMT-AV1/A2): a future/conditional locator, or one
    # repository pinned to two commits across the statements.
    "FMT-AV1",
    "FMT-AV2",
    # Zotero live-field refresh parity (FMT-Z1..FMT-Z5): a stale citation
    # marker, a bibliography order that disagrees with the citation order, a
    # cited item with two numbers, a half-updated field, or two conflicting
    # style stores in one document. An editor (and the next Word/Zotero refresh)
    # acts on every one, and only Zotero can re-render them.
    "FMT-Z1",
    "FMT-Z2",
    "FMT-Z3",
    "FMT-Z4",
    "FMT-Z5",
}


def tier_of(rule: str) -> str:
    """`finding` (must be decided against its own bar) or `advisory`."""
    return "finding" if rule in FINDING_TIER_RULES else "advisory"


# Section-aware sentence-length bars.  An abstract, a cover letter and a figure
# legend are skim surfaces with their own word budgets; a Methods paragraph is
# an enumeration and is allowed longer sentences.  Bars are inclusive lower
# bounds (a sentence of exactly `bar` words is a row), which is what the old
# `> 45` rule got wrong: the abstract sentence the operator flagged was exactly
# 45 words and produced no row at all.
LONG_SENTENCE_BARS = {"front": 40, "abstract": 40, "legend": 40, "body": 46,
                      "methods": 61, "heading": 10 ** 6, "refs": 10 ** 6}
STRICT_KINDS = ("front", "abstract", "legend")

# One-sentence-paragraph exclusions (FMT-T9k). A paragraph in one of these
# SECTIONS is a statement list by convention (an acronym list, a funding or
# ethics statement, an availability note), never a narrative paragraph; and a
# paragraph of one of these SHAPES is a statement wherever it sits.
SINGLE_SENTENCE_SKIP_SECTION_RE = re.compile(
    r"^(?:acknowledg|funding|author contributions?|contributions?|competing interests?|"
    r"conflict of interest|ethics|data availability|code availability|"
    r"materials? availability|resource availability|supplementary|abbreviations?|"
    r"references|graphical abstract|highlights?|lead contact)\b", re.I)
SINGLE_SENTENCE_SKIP_TEXT_RE = re.compile(
    r"^(?:the authors? declares?|the author declares|this (?:work|study|project) "
    r"(?:was|is|did|has)|we (?:thank|are grateful)|"
    r"(?-i:[A-Z][A-Z0-9\-\u2010-\u2015]{1,7}),\s|"
    r"keywords?\s*:|key words\s*:|https?://|doi:|orcid)", re.I)


def _table_row_like(text: str) -> bool:
    """A table row in a TEXT source -- never a paragraph for FMT-T9k.

    The DOCX path excludes table cells by their container; a `.md`/`.tex`/`.txt`
    source has no containers, so the row shapes are the test: a markdown pipe
    row, a LaTeX `cell & cell \\\\` row, or a converted row whose cells became
    tab-separated lines.
    """
    t = (text or "").strip()
    if t.startswith("|") and t.endswith("|") and t.count("|") >= 3:
        return True
    if t.count("&") >= 2 and ("\\\\" in t or t.endswith("\\")):
        return True
    return t.count("\t") >= 2

ABSTRACT_HEAD_RE = re.compile(r"^\s*(?:abstract|summary)\s*:?\s*$", re.I)
# End-anchored to the label's own punctuation: a prose sentence that happens to
# begin "Keywords are ..." is not a keywords heading (and must not switch the
# rest of the document to body mode).
KEYWORDS_HEAD_RE = re.compile(r"^\s*(?:key\s?words?|keywords)\s*(?::|$)", re.I)
METHODS_HEAD_RE = re.compile(
    r"^\s*(?:\d+[.)]?\s*)?(?:materials\s*(?:&|and)\s*methods|online methods|methods)"
    r"\s*$", re.I)
BODY_HEAD_RE = re.compile(
    r"^\s*(?:\d+[.)]?\s*)?(?:introduction|results|discussion|conclusions?|background|"
    r"related work|results\s*(?:&|and)\s*discussion|"
    r"discussion\s*(?:&|and)\s*conclusions?)\s*:?\s*$", re.I)


def section_kinds(paras: list, headings: list = None) -> list:
    """One section label per paragraph: front/abstract/body/methods/legend/refs.

    The label decides the sentence-length bar (see LONG_SENTENCE_BARS), so the
    scan can be strict exactly where a real reader is strict.  The walk uses the
    document's own headings when the caller has them (the pipeline passes its
    `is_heading` flags) and falls back to a heading heuristic.
    """
    kinds, mode = [], "front"
    for i, text in enumerate(paras):
        t = (text or "").strip()
        head = bool(headings[i]) if headings and i < len(headings) else False
        if LEGEND_RE.match(t):
            kinds.append("legend")
            continue
        if ABSTRACT_HEAD_RE.match(t) and (
                mode == "front" or re.match(r"^\s*abstract\b", t, re.I)):
            # A bare "Summary" heading later in the document is a section
            # heading, not a second abstract: letting it reset mode put every
            # following body paragraph under the abstract's sentence bar.
            mode, kinds = "abstract", kinds + ["heading"]
            continue
        if KEYWORDS_HEAD_RE.match(t):
            mode, kinds = "body", kinds + ["body"]
            continue
        if METHODS_HEAD_RE.match(t):
            mode, kinds = "methods", kinds + ["heading"]
            continue
        if BODY_HEAD_RE.match(t):
            mode, kinds = "body", kinds + ["heading"]
            continue
        if head or (t and len(t.split()) <= 8 and not re.search(r"[.;:,]$", t)
                    and t[:1].isupper() and " " in t):
            kinds.append("heading")
            continue
        kinds.append(mode)
    return kinds


# Two term families that routinely compete for one concept.  The scanner cannot
# decide which family is right -- that is the author's glossary decision -- but
# it can prove that both are in use and name the occurrences, which is what the
# term ledger (one row per surface form, each disposed "OK" on its own) can
# never see.
CONCEPT_FAMILIES = (
    ("copy-number STATE (CN) vs copy-number VARIATION (CNV/CNA)",
     (r"\bCN\b", r"\bCNs\b",
      # The bare prefix of family B's "copy-number variation" is not a family-A
      # hit: one CNV-only paragraph was counted in both families.
      r"\bcopy[-\s]number\b(?!\s*(?:variations?|alterations?))"),
     (r"\bCNVs?\b", r"\bCNAs?\b", r"\bcopy[-\s]number variations?\b",
      r"\bcopy[-\s]number alterations?\b")),
    ("simulation (a model generates the data) vs emulation (real data behaves "
     "as if from a known condition)",
     (r"\bsimulat(?:e|es|ed|ing|ion|ions)\b",),
     (r"\bemulat(?:e|es|ed|ing|ion|ions)\b",)),
)


def _family_hits(text: str, patterns) -> list:
    hits = []
    for pat in patterns:
        hits += list(re.finditer(pat, text))
    return hits


# A term glossed in place: "average spot length (sequencing read length, which
# is associated with single-cell sequencing technology)".
SELF_GLOSS_RE = re.compile(
    r"\b([a-z][a-z0-9\-]{2,}(?:\s+[a-z][a-z0-9\-]{2,}){0,3})\s+"
    r"\(([^()]{12,160})\)")
GLOSS_MARKERS = ("which", "that is", "i.e.", "e.g.", "meaning", "denotes", "refers",
                 "associated with", "defined as", "also known as", "we call")
GLOSS_TERM_STOPWORDS = {"figure", "table", "section", "note", "panel", "equation",
                        "supplementary", "for example", "in particular"}
# A relative clause or an example list is an APPOSITIVE, not a definition: the
# first cut of this rule reported 22 rows on a real manuscript, and 20 of them
# were "term (e.g., ...)" / "term (which ...)". A term-definition is recognized
# by a definitional marker in the gloss ("which is associated with", "denotes",
# ...) and by a term that is a noun phrase (no finite verb, no leading
# preposition).
GLOSS_REJECT_STARTS = ("e.g", "i.e", "for example", "such as", "which", "that", "who",
                       "we ", "it ", "they ", "this ", "these ", "those ")
GLOSS_MARKERS_STRICT = ("which is", "which are", "meaning", "denotes", "refers to",
                        "defined as", "also known as", "we call", "is associated with",
                        "is the", "are the", "is a", "is an", "are a", "are an")
GLOSS_TERM_VERBS = {"should", "include", "includes", "included", "using", "use", "used",
                    "uses", "is", "are", "was", "were", "can", "may", "might", "will",
                    "would", "marks", "mark", "exceeds", "lacks", "requires", "require",
                    "shows", "show", "has", "have", "had", "does", "do", "did"}
GLOSS_TERM_LEAD_STOPWORDS = {"with", "for", "and", "or", "of", "in", "on", "at", "by",
                             "to", "from", "as", "than", "between", "the", "a", "an"}



def number_ledger(paras: list) -> list:
    """Every numeric literal with the sentence it sits in (the M4 artifact).

    The ledger is what makes "verify the source of each number" a mechanical
    task: the agent adds a source (data file / table / figure / formula) to each
    row, and `number_format_rows()` reports the formatting side (thousands
    separators, LaTeX quantities outside \\SI).
    """
    rows = []
    for i, text in enumerate(paras):
        sentences = re.split(r"(?<=[.!?])\s+", text)
        bounds, pos = [], 0
        for sentence in sentences:
            bounds.append((pos, pos + len(sentence)))
            pos += len(sentence)
            while pos < len(text) and text[pos].isspace():
                pos += 1
        # Digit artifacts and spelled-out count artifacts go through the same
        # attribution: a word number is a NUMERIC artifact, so the ledger, the
        # M30 seed and the provenance report treat it like any other count.
        found = [(m.start(), m.end(), m.group(0), None)
                 for m in NUMBER_RE.finditer(text)]
        found += [(r["start"], r["end"], r["number"], r["written"])
                  for r in word_number_rows(text)]
        for start, end, number, written in sorted(found):
            # Attribute by the match POSITION, not by substring membership: a
            # paragraph that repeats a number would otherwise put every
            # instance in the first sentence that happens to contain the digits.
            idx = 0
            for k, (start_, _end) in enumerate(bounds):
                if start_ <= start:
                    idx = k
                else:
                    break
            sentence = sentences[idx] if sentences else text
            row = {"document_paragraph": i, "number": number,
                   "thousands_separated": "," in number,
                   "unit": (UNIT_RE.match(text[end:]).group(0).strip()
                            if UNIT_RE.match(text[end:]) else None),
                   "sentence": sentence.strip()[:200], "source": ""}
            if written:
                # Keep the author's spelling: the ledger row must be locatable in
                # the sentence, and a session disposing it needs to see that the
                # number is written as a word.
                row["written"] = written
            rows.append(row)
    return rows


# --------------------------------------------------------------------------
# The claim-strength ledger (check id J3: overclaiming AND underclaiming).
#
# J3's calibration check is TWO-SIDED, and only one side is loud enough to be
# noticed by a plain read: a claim that outruns its evidence ("demonstrates",
# "proves", "for the first time", a causal verb over a correlation) draws the
# eye, while a claim that undersells its own evidence ("may", "could",
# "suggests", "a trend", "preliminary") reads as careful writing and is never
# enumerated -- so an underclaim survives every instance-level sweep of the
# corpus.  This ledger makes BOTH directions a row a session must dispose: one
# row per paragraph per direction, carrying the markers the code found and the
# sentence that carries them.
#
# The code cannot decide the calibration (that is the evidence judgement the
# reviewer/auditor/reviser makes); it only guarantees that the session looks at
# the underclaim direction as well as the overclaim direction.  A marker whose
# strength MATCHES the evidence is a legitimate disposition, not a defect: the
# row asks "does this sentence's strength match what the corpus shows?", never
# "delete the hedge".
# --------------------------------------------------------------------------

# Direction 1 -- UNDERCLAIM markers: the sentence weakens what the evidence
# supports.  Deliberately conservative: each row is a QUESTION, not a verdict.
CLAIM_HEDGE_MARKERS = (
    r"\bmay\b", r"\bmight\b", r"\bcould\b", r"\bpossibly\b", r"\bperhaps\b",
    r"\bpotentially\b", r"\bpresumably\b", r"\bseems?\b", r"\bappear(?:s|ed)? to\b",
    r"\bsuggests?\b", r"\bsuggesting\b", r"\bsuggestive\b", r"\bwe speculate\b",
    r"\bspeculation\b", r"\bplausibl[ey]\b", r"\btends? to\b", r"\ba trend\b",
    r"\btrend(?:ed)? toward\b", r"\bborderline\b", r"\bmarginal(?:ly)?\b",
    r"\bmodest(?:ly)?\b", r"\bsubtle\b", r"\bpreliminary\b", r"\bexploratory\b",
    r"\bdescriptive\b", r"\bconsistent with\b", r"\bwe cannot exclude\b",
    r"\bcannot exclude\b", r"\bremains? (?:to be|unclear)\b", r"\byet to be\b",
    r"\bfurther (?:work|study|studies)\b", r"\bnot conclusive\b",
    r"\bno definitive\b", r"\bwould seem\b",
)

# Direction 2 -- OVERCLAIM markers: the sentence claims more than the evidence
# shown supports (the class J3 has always named: unsupported first/novel
# claims, causal language over a correlation, generalization past the tested
# conditions).  Listed here so the ledger is symmetric, and so a REVIEWER/
# JUDGE sees the two directions side by side in one artifact.
CLAIM_ABSOLUTE_MARKERS = (
    r"\bfor the first time\b", r"\bfirst (?:report|demonstration|evidence)\b",
    r"\bnovel\b", r"\bunprecedented\b", r"\bstate[- ]of[- ]the[- ]art\b",
    r"\buniquely\b", r"\bproves?\b", r"\bproven\b", r"\bdemonstrates?\b",
    r"\bestablishes?\b", r"\bconfirms?\b", r"\bclearly\b", r"\bundoubtedly\b",
    r"\bdecisively\b", r"\bdramatic(?:ally)?\b", r"\bremarkabl[ey]\b",
    r"\bstriking\b", r"\bcauses?\b", r"\bdrives?\b", r"\bleads? to\b",
    r"\bresponsible for\b", r"\bwe prove\b",
)

# A claim's home surfaces.  Methods paragraphs describe protocols, not claims,
# and reference lists/quoted titles are not the manuscript's own voice, so they
# are not enumerated -- the ledger must stay small enough to be disposed row by
# row (the repository's own "70 rows of noise" lesson).
CLAIM_KINDS = ("front", "abstract", "body", "legend")


def _first_marker_sentence(text: str, pattern) -> str:
    """The sentence carrying the first match of `pattern` (trimmed for a cell)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]
    for s in sentences:
        if pattern.search(s):
            return s[:200]
    return (text or "").strip()[:200]


def claim_strength_rows(paras: list, is_ref: list = None, kinds: list = None) -> list:
    """J3's two-sided claim-strength ledger: one row per paragraph per direction.

    Columns: paragraph | kind | direction (`under` = a hedge the evidence may
    not require; `over` = a maximal claim the evidence may not support) |
    markers | sentence.  Both directions are enumerated for every claim-bearing
    paragraph, so a session cannot report the loud direction and leave the quiet
    one unexamined.
    """
    rows = []
    is_ref = list(is_ref or [False] * len(paras))
    kinds = list(kinds) if kinds else section_kinds(paras)
    hedge_re = re.compile("|".join(CLAIM_HEDGE_MARKERS), re.I)
    absolute_re = re.compile("|".join(CLAIM_ABSOLUTE_MARKERS), re.I)
    for i, text in enumerate(paras):
        if i < len(is_ref) and is_ref[i]:
            continue
        kind = kinds[i] if i < len(kinds) else "body"
        if kind not in CLAIM_KINDS:
            continue
        if len((text or "").split()) < 5:
            continue
        for direction, pattern in (("under", hedge_re), ("over", absolute_re)):
            # `finditer` + group(0), never `findall`: a capture group added to a
            # marker later would silently turn every match into its group text.
            found = [m.group(0) for m in pattern.finditer(text or "")]
            if not found:
                continue
            markers = sorted({str(m).strip().lower() for m in found})
            rows.append({"paragraph": i, "kind": kind, "direction": direction,
                         "markers": "; ".join(markers[:6]),
                         "n markers": len(found),
                         "sentence": _first_marker_sentence(text, pattern)})
    return rows


def number_format_rows(paras: list) -> list:
    """FMT-T9h: a document mixes 4+-digit numbers with and without separators."""
    rows = []
    nums = []
    for text in paras:
        # NUMBER_RE has two alternatives (decimal / integer); `findall` would
        # return a tuple of their group captures, so take group(1) explicitly.
        nums += [m.group(1) for m in NUMBER_RE.finditer(text)]
    # 4-digit years and list-position numbers are not quantities: only numbers
    # with 5+ digits (or a 4+-digit number that already carries a separator)
    # take part in the convention check.
    def _is_quantity(n: str) -> bool:
        # `1.2e-4` is one value, not a 6-character integer: it has no bearing on
        # the thousands-separator convention (before the exponent was part of
        # NUMBER_RE it was read as `1` and `4` and never reached this check).
        # Only the NEW shape is excluded: a plain decimal (`1,234.5`) stays a
        # separator case exactly as it was before the exponent was accepted.
        if not re.fullmatch(r"\d[\d,]*(?:\.\d+)?", n):
            return False
        # A comma is a THOUSANDS separator only when it groups three digits:
        # the token "1," (from "1, 2") is not a separated quantity.
        if "," in n and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", n):
            return False
        digits = n.replace(",", "")
        # The 4-digit year test must run BEFORE the <=4 return, which otherwise
        # made it unreachable ("2,019" was read as a separated quantity).
        if len(digits) == 4 and digits[:2] in ("19", "20"):
            return False
        if len(digits) <= 4:
            return "," in n
        return True
    big = [n for n in nums if _is_quantity(n)]
    sep = [n for n in big if "," in n]
    plain = [n for n in big if "," not in n]
    if sep and plain:
        rows.append({"rule": "FMT-T9h", "severity": "low",
                     "evidence": f"4+-digit numbers mix thousands separators "
                                 f"({len(sep)} with, {len(plain)} without: e.g. "
                                 f"{sep[0]!r} vs {plain[0]!r})",
                     "detail": "use ONE convention for 4+-digit numbers (a separator or a "
                               "thin space) throughout the document; a journal may also "
                               "require the plain form in tables and figures",
                     "protected": False})
    return rows


# LaTeX spans whose numbers are NOT quantities and must never be re-wrapped:
# code/verbatim identifiers, URLs, citations and cross-references, inline math,
# and generated tables (those are fixed at the generator, never in the file the
# generator overwrites).
LATEX_MASK_PATTERNS = (
    r"\\(?:SI|SIrange|qty|qtyrange|num|si|SIlist|qtylist)\{[^{}]*\}(?:\{[^{}]*\})?",
    r"\\code\{[^{}]*\}",
    r"\\verb\*?([^A-Za-z\s])(?:(?!\1).)*\1",
    r"\\url\{[^{}]*\}",
    r"\\href\{[^{}]*\}\{[^{}]*\}",
    r"\\cite[a-zA-Z]*\{[^{}]*\}",
    r"\\(?:ref|eqref|cref|Cref|label|bibitem|nocite)\{[^{}]*\}",
    r"\$[^$]*\$",
    r"\\\([^)]*\\\)",
    r"\\begin\{tabular\}.*?\\end\{tabular\}",
    r"\\begin\{pgfplotstable\}.*?\\end\{pgfplotstable\}",
)
LATEX_UNIT_RE = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)[~\s]*(?:\\,\s*)?(?:\\text\{)?"
    r"(?:\\%|%|percent|fold|×|kbp|kb|Mbp|Mb|Gbp|Gb|bp|µm|um|nm|mm|cm|mL|µL|uL|ng|"
    r"µg|ug|mg|h\b|min\b|s\b|ms\b|°C|mM|µM|uM|nM|pM|mol|GB|MB|GHz)")


def latex_number_rows(text: str) -> list:
    """FMT-T9g: LaTeX quantities not wrapped in siunitx (raw .tex input).

    Accepts both spellings of the macro family: `\\SI`/`\\SIrange` (siunitx v2
    and the v3 compatibility aliases) and `\\qty`/`\\qtyrange` (the v3 names), so
    the rule never forces a siunitx version.  Numbers inside `\\code{}`,
    verbatim, URLs, citations, cross-references, inline math and generated tables
    are exempt by construction.
    """
    rows = []
    masked = text
    for pat in LATEX_MASK_PATTERNS:
        masked = re.sub(pat, lambda m: " " * len(m.group(0)), masked, flags=re.S)
    units = list(LATEX_UNIT_RE.finditer(masked))
    if units:
        rows.append({"rule": "FMT-T9g", "severity": "low", "tier": "finding",
                     "evidence": f"{len(units)} quantity/quantities with units outside "
                                 f"siunitx (e.g. {units[0].group(0)[:40]!r})",
                     "detail": "format numbers with units through siunitx (\\qty{<value>}"
                               "{<unit>} -- \\SI{}{} is the v2/deprecated spelling and is "
                               "accepted; \\num{...} for bare numbers; \\qtyrange for a "
                               "range) unless the value cannot be expressed that way (then "
                               "record why in the disposition)",
                     "protected": False})
    return rows


def confusable_pair_rows(paras: list, pairs=None) -> list:
    """FMT-T9d: both members of a confusable pair appear in one document."""
    rows = []
    for a, b in (pairs or CONFUSABLE_PAIRS):
        pa = [i for i, t in enumerate(paras) if re.search(rf"\b{re.escape(a)}\w*", t, re.I)]
        pb = [i for i, t in enumerate(paras) if re.search(rf"\b{re.escape(b)}\w*", t, re.I)]
        if not pa or not pb:
            continue
        both = sorted(set(pa) & set(pb))
        rows.append({"rule": "FMT-T9d", "severity": "medium",
                     "evidence": f"confusable terms are both used: {a!r} in {len(pa)} "
                                 f"paragraph(s) and {b!r} in {len(pb)}"
                                 + (f", together in para {both[:3]}" if both else ""),
                     "detail": "these words mean different things: pick the precise one "
                               "everywhere (and define it at first use); if both are truly "
                               "needed, say which is which in the sentence",
                     "protected": False})
    return rows


def key_term_rows(paras: list, terms=None) -> list:
    """Occurrence ledger for the manuscript's key terms (the M8 artifact rows)."""
    rows = []
    for term in (terms or KEY_TERMS):
        core = term.strip()
        # A term written with a trailing space ("CN ") means "standalone only":
        # the `\w*` suffix that lets "caller" count "callers" would otherwise
        # make it a prefix that also swallows CNV/CNVs/CNA (the M8 ledger then
        # overstates CN and double-counts the CNV family).
        pattern = (re.compile(rf"\b{re.escape(core)}\b", re.I)
                   if term != core and term.endswith(" ") else
                   re.compile(rf"\b{re.escape(core)}\w*", re.I))
        hits = [(i, t) for i, t in enumerate(paras) if pattern.search(t)]
        if not hits:
            continue
        ctx = pattern.search(hits[0][1])
        s = ctx.start() if ctx else 0
        rows.append({"term": core, "count": len(hits),
                     "first_paragraph": hits[0][0],
                     "first_context": hits[0][1][max(0, s - 60):s + 60].strip(),
                     "variant": ""})
    return rows


def long_text_rows(paras: list, is_ref: list = None, kinds: list = None,
                   headings: list = None, in_container: list = None,
                   in_area: list = None) -> list:
    """FMT-T9c (long sentence), FMT-T9c/T9i (list paragraph / mega paragraph)
    and FMT-T9k (a narrative paragraph built from ONE sentence).

    The sentence bar is section-aware (LONG_SENTENCE_BARS): 40 words in an
    abstract, a cover letter or a legend; 46 in the body; 61 in Methods.  Every
    row carries its `tier`, and the strict sections are finding-tier, so the
    review can no longer close them with "no journal rule".

    The mega-paragraph rule (FMT-T9i) skips legends: a legend is ONE paragraph
    by the caption rule (FMT-T2c), and its length is the venue's M18 word-budget
    question -- "split it at the natural boundary" is the wrong advice there.

    `headings`/`in_container`/`in_area` (optional) let the one-sentence rule
    read the paragraph's section (end-matter sections are statement lists, not
    narrative) and skip table-cell paragraphs and a display area's own notes.
    """
    rows, is_ref = [], list(is_ref or [False] * len(paras))
    kinds = list(kinds) if kinds else section_kinds(paras)
    heads = list(headings) if headings else None
    container = list(in_container) if in_container else None
    area = list(in_area) if in_area else None
    # The nearest preceding heading's text, for the end-matter exclusions of
    # the one-sentence rule (an acronym list or a funding statement is not a
    # narrative paragraph, whatever the paragraph looks like in isolation).
    section_of = [""] * len(paras)
    if heads:
        current = ""
        for i in range(len(paras)):
            if i < len(heads):
                flag = heads[i][1] if isinstance(heads[i], tuple) else heads[i]
                if flag:
                    current = str(paras[i] or "").strip()
            section_of[i] = current
    for i, text in enumerate(paras):
        if i < len(is_ref) and is_ref[i]:
            continue
        kind = kinds[i] if i < len(kinds) else "body"
        bar = LONG_SENTENCE_BARS.get(kind, 46)
        for s in re.split(r"(?<=[.!?])\s+", text):
            n = len(s.split())
            if n < bar:
                continue
            strict = kind in STRICT_KINDS
            rows.append({"rule": "FMT-T9c",
                         "severity": "medium" if strict else "low",
                         "tier": "finding" if kind != "methods" else "advisory",
                         "evidence": f"long sentence ({n} words; {kind} bar {bar}) in "
                                     f"para {i}: {s.strip()[:80]!r}...",
                         "detail": "split it (one idea per sentence) or move the "
                                   "qualification into a following sentence; an abstract "
                                   "or legend sentence this long hides its own claim",
                         "protected": False})
        marks = re.findall(r"\((\d)\)", text)
        words = len(text.split())
        if len(marks) >= 3 and words > 200:
            rows.append({"rule": "FMT-T9c", "severity": "medium", "tier": "finding",
                         "evidence": f"paragraph {i} carries {len(marks)} enumerated "
                                     f"items in {words} words",
                         "detail": "structural list inside one prose paragraph: give every "
                                   "item its own paragraph (consistently) or break the "
                                   "paragraph at a natural boundary; keep the treatment of "
                                   "the items identical",
                         "protected": False})
        elif words > 250 and kind not in ("methods", "legend"):
            # A legend is ONE paragraph by the caption rule (FMT-T2c): telling a
            # caption to "split at the natural boundary" contradicts it, and a
            # long legend's length is the venue's M18/word-budget question, not
            # a paragraph-shape defect.
            rows.append({"rule": "FMT-T9i", "severity": "low", "tier": "finding",
                         "evidence": f"paragraph {i} is {words} words long ({kind})",
                         "detail": "a paragraph this long carries several messages: split it "
                                   "at the natural boundary so each paragraph makes one point",
                         "protected": False})
        # FMT-T9k -- the paragraph-level "lone division": a narrative paragraph
        # built from ONE sentence. A paragraph carries a claim plus its support;
        # a short single sentence standing alone reads as an accident (the
        # 2026-10-14 winners shipped seven of them in the Results/Discussion
        # narrative, and the rewrite that produced them could always have merged
        # the sentence into the paragraph it belongs to or given it its support).
        # Skipped where a one-line paragraph is the convention: captions and
        # legends, end-matter sections (funding/ethics/availability/acronym
        # lists), statement shapes, keywords, table cells, and anything shorter
        # than five words.
        if kind in ("body", "abstract") and 5 <= words <= 45:
            stripped = (text or "").strip()
            sentences = [s for s in re.split(r"(?<=[.!?])\s+", stripped) if s.strip()]
            if (len(sentences) == 1
                    and re.search(r"[.!?][\"\u2019\u201d)\]]?$", stripped)
                    and not (container and i < len(container) and container[i])
                    and not (area and i < len(area) and area[i])
                    and not SINGLE_SENTENCE_SKIP_TEXT_RE.match(stripped)
                    and not SINGLE_SENTENCE_SKIP_SECTION_RE.match(section_of[i])
                    and not _table_row_like(stripped)
                    and not caption_label_kind(stripped)
                    and not LEGEND_RE.match(stripped)):
                rows.append({
                    "rule": "FMT-T9k", "severity": "low", "tier": "finding",
                    "evidence": (f"paragraph {i} is ONE {words}-word sentence "
                                 f"({kind}): {stripped[:80]!r}"),
                    "detail": ("a paragraph carries a claim plus its support: merge this "
                               "sentence into the paragraph it belongs to, or give it the "
                               "support the claim needs -- a one-sentence paragraph reads "
                               "as a formatting accident"),
                    "protected": False})
    return rows


def self_gloss_rows(paras: list, is_ref: list = None) -> list:
    """FMT-T9f: the manuscript glosses its own term -- a precision defect.

    "average spot length (sequencing read length, which is associated with
    single-cell sequencing technology)" is the text admitting that the term it
    just used is not the reader's term.  Either use the standard term or keep
    the gloss deliberately (that is a legitimate disposition, and it has to be
    recorded as one).  An acronym long form ("MALBAC (multiple annealing ...)")
    is NOT a row: the expansion of a defined abbreviation is a different thing.
    """
    rows = []
    is_ref = list(is_ref or [False] * len(paras))
    seen = set()
    for i, text in enumerate(paras):
        if i < len(is_ref) and is_ref[i]:
            continue
        for m in SELF_GLOSS_RE.finditer(text):
            term, gloss = m.group(1).strip(), m.group(2).strip()
            low_gloss, words_gloss = gloss.lower(), gloss.split()
            if len(gloss.split()) < 4 or URL_RE.search(gloss) or "@" in gloss:
                continue
            if low_gloss.startswith(GLOSS_REJECT_STARTS):
                continue                      # appositive / example list, not a definition
            if not any(k in low_gloss for k in GLOSS_MARKERS_STRICT):
                continue
            before = text[max(0, m.start() - 1):m.start()]
            if before.isupper() or before.isdigit():
                continue                      # acronym long form, not a gloss
            if term.lower() in GLOSS_TERM_STOPWORDS:
                continue
            term_words = [w.lower() for w in term.split()]
            if term_words and term_words[0] in GLOSS_TERM_LEAD_STOPWORDS:
                continue                      # a sentence fragment, not a term
            if any(w in GLOSS_TERM_VERBS for w in term_words):
                continue                      # "should include ...", "marks ..."
            key = (term.lower(), " ".join(low_gloss.split())[:60])
            if key in seen:
                continue                      # the same legend repeated per page
            seen.add(key)
            rows.append({"rule": "FMT-T9f", "severity": "low", "tier": "finding",
                         "evidence": f"term glossed in place: {term!r} ({gloss[:70]!r})",
                         "detail": "the manuscript has to explain this term, so either use "
                                   "the standard term everywhere or keep the gloss and say "
                                   "why the term is used (a recorded disposition, not a "
                                   "silent pass)",
                         "protected": False})
    return rows


def concept_family_rows(paras: list, is_ref: list = None) -> list:
    """FMT-T9j: two term families compete for one concept."""
    rows = []
    is_ref = list(is_ref or [False] * len(paras))
    prose = [(i, t) for i, t in enumerate(paras) if not (i < len(is_ref) and is_ref[i])]
    for label, fam_a, fam_b in CONCEPT_FAMILIES:
        hits_a, hits_b = [], []
        for i, text in prose:
            hits_a += [(i, m.group(0)) for m in _family_hits(text, fam_a)]
            hits_b += [(i, m.group(0)) for m in _family_hits(text, fam_b)]
        if not hits_a or not hits_b:
            continue
        both = sorted({i for i, _ in hits_a} & {i for i, _ in hits_b})
        rows.append({"rule": "FMT-T9j", "severity": "medium", "tier": "finding",
                     "evidence": f"two families for one concept -- A: "
                                 f"{sorted({t.lower() for _, t in hits_a})[:4]} "
                                 f"x{len(hits_a)}; B: "
                                 f"{sorted({t.lower() for _, t in hits_b})[:4]} "
                                 f"x{len(hits_b)}"
                                 + (f"; together in para {both[:3]}" if both else ""),
                     "detail": f"{label}: fix ONE term per concept in GLOSSARY.md and use it "
                               "everywhere (the metric names decide the sense: intCN_* is a "
                               "copy-number state, breakpoint/gain-loss scoring is an event)",
                     "protected": False})
    return rows


def glossary_seed_rows(paras: list, is_ref: list = None) -> list:
    """The GLOSSARY.md scaffold: every concept the corpus mixes, with counts."""
    rows = []
    is_ref = list(is_ref or [False] * len(paras))
    text = "\n".join(t for i, t in enumerate(paras)
                     if not (i < len(is_ref) and is_ref[i]))
    for label, fam_a, fam_b in CONCEPT_FAMILIES:
        a = _family_hits(text, fam_a)
        b = _family_hits(text, fam_b)
        if not a and not b:
            continue
        rows.append({"concept": label,
                     "family A forms": ", ".join(sorted({m.group(0).lower() for m in a})[:6]),
                     "A count": len(a),
                     "family B forms": ", ".join(sorted({m.group(0).lower() for m in b})[:6]),
                     "B count": len(b),
                     "definition": "", "authoritative term": "", "forbidden synonyms": ""})
    for a, b in CONFUSABLE_PAIRS:
        ca = len(re.findall(rf"\b{re.escape(a)}\w*", text, re.I))
        cb = len(re.findall(rf"\b{re.escape(b)}\w*", text, re.I))
        if not ca or not cb:
            continue
        rows.append({"concept": f"{a} vs {b}",
                     "family A forms": a, "A count": ca,
                     "family B forms": b, "B count": cb,
                     "definition": "", "authoritative term": "", "forbidden synonyms": ""})
    return rows


def _label_key(text: str) -> str:
    """Key of a parenthetical label ('(Co-corresponding author; …)' -> the label)."""
    body = text.strip().lstrip("(").split(";")[0].split(",")[0]
    return " ".join(re.findall(r"[A-Za-z][A-Za-z\-']*", body)[:4]).lower()


def emphasis_consistency(styles: dict, doc_paras: list) -> tuple:
    """(rows, fixes) for the same phrase italic in one place and roman in another.

    Covers a real cover letter where "(Co-corresponding author; …)" is italic on
    one author and roman on the next: every italics check was journal-specific,
    so a *label* formatted two ways was invisible. Phrase candidates are
    parenthetical labels and capitalized 2-4-word names inside one run (journal
    titles are left to FMT-T6). The fix is applied only to LABEL-like phrases
    (<=5 words, starts upper-case, no digits): the majority treatment wins, and
    an exact tie resolves to roman, because a parenthesis label is not emphasis.
    """
    seen = {}
    for idx, (p0, p1, para) in enumerate(doc_paras):
        style = para_style(para)
        runs_info, text = [], ""
        for r0, r1, run in runs(para):
            rtext = text_of(run)
            runs_info.append((len(text), len(text) + len(rtext), r0, r1, run, rtext))
            text += rtext
        # parenthetical labels: the group can SPAN runs ("(Co-corresponding
        # author; " + the e-mail in the next run), so it is found in the
        # paragraph text and each overlapping run keeps its OWN state -- that is
        # exactly the defect (one half italic, the other roman).
        for start, end, _depth, inner in balanced_paren_groups(text):
            key = _label_key(inner)
            words = re.findall(r"[A-Za-z][A-Za-z\-']*", inner)
            if not key or len(words) < 2 or not re.match(r"^[A-Z]", inner.strip()) \
                    or (len(words) > 6 and ";" not in inner) \
                    or journal_matches(inner):
                continue
            overlap = [ri for ri in runs_info
                       if ri[0] < end and ri[1] > start and ri[5].strip()]
            rec = seen.setdefault(key, {"phrase": inner[:60], "label": True,
                                        "ital": [], "roman": []})
            for ri in overlap:
                state = "ital" if run_is_italic(styles, style, ri[4]) else "roman"
                # Only the part of the run that lies INSIDE the parenthetical
                # label is the fix span. Recording the whole run restyled text
                # the row never reported ("… label; zhenxie@host) and tail").
                local = (max(start, ri[0]) - ri[0], min(end, ri[1]) - ri[0])
                rec[state].append((idx, ri[2], ri[3], local))
        for r0, r1, run in runs(para):
            rtext = text_of(run)
            if len(rtext.strip()) < 4:
                continue
            ital = run_is_italic(styles, style, run)
            for m in re.finditer(
                    r"\b[A-Z][A-Za-z\-']+(?:\s+(?:of|the|and|&)?\s*[A-Z][A-Za-z\-']+){1,3}\b",
                    rtext):
                if journal_matches(m.group(0)):
                    continue
                rec = seen.setdefault(m.group(0).lower(),
                                      {"phrase": m.group(0), "label": False,
                                       "ital": [], "roman": []})
                rec["ital" if ital else "roman"].append((idx, r0, r1, None))
    rows, fixes = [], []
    for key, rec in sorted(seen.items()):
        if not (rec["ital"] and rec["roman"]):
            continue
        n_i, n_r = len(rec["ital"]), len(rec["roman"])
        where_i = ", ".join(f"p{idx}" for idx, _r0, _r1, _loc in rec["ital"][:3])
        where_r = ", ".join(f"p{idx}" for idx, _r0, _r1, _loc in rec["roman"][:3])
        rows.append({"rule": "FMT-T9a", "severity": "medium",
                     "evidence": f"{rec['phrase']!r} is italic in {n_i} place(s) "
                                 f"({where_i}) and roman in {n_r} ({where_r})",
                     "detail": "the same phrase must carry ONE treatment; a parenthetical "
                               "label is roman unless the document emphasises all of them",
                     "protected": False})
        if rec["label"] and not any(re.search(r"\d", p) for p in [rec["phrase"]]) \
                and len(rec["phrase"].split()) <= 5:
            want = n_i > n_r                      # majority; a tie -> roman
            for idx, r0, r1, local in (rec["roman"] if want else rec["ital"]):
                fixes.append((idx, r0, r1, want, local))
    return rows, fixes


def placeholder_ledger(paras: list) -> list:
    """Classify every hand-off placeholder: searchable vs author-only.

    A placeholder that asks for a *findable* fact (a preprint, DOI, accession,
    database ID, version, trial registration) can be resolved by the pipeline's
    lookup (or the agent's web search) and filled with a caveat; an author-only
    one (a competing-interest statement, an author decision) stays.
    """
    rows = []
    searchable = re.compile(r"preprint|doi|accession|database|repository|zenodo|figshare|"
                            r"geo\b|sra\b|arrayexpress|version|registration|url", re.I)
    for i, text in enumerate(paras):
        for m in re.finditer(r"\[\s*AUTHOR\s+TO\s+COMPLETE\b([^\]]*)\]", text, re.I):
            payload = m.group(1).strip(" :;-")
            kind = ""
            low = payload.lower()
            if "preprint" in low:
                kind = "preprint"
            elif "persistent identifier" in low or re.search(r"\bdoi\b", low):
                kind = "archive" if re.search(r"archiv|zenodo|figshare|persistent", low) \
                    else "doi"
            elif "accession" in low or re.search(r"\b(?:geo|sra|bioproject)\b", low):
                kind = "accession"
            elif "orcid" in low:
                kind = "orcid"
            elif re.search(r"repositor|github|url|commit", low):
                kind = "repository"
            rows.append({"document_paragraph": i, "payload": payload[:200],
                         "class": "searchable" if searchable.search(payload) else "author-only",
                         "kind": kind, "resolved": ""})
    return rows


def lookup_preprint(query: str, timeout: int = 30) -> dict:
    """Query Europe PMC / OpenAlex / Crossref for a title/tool name.

    Returns {"query", "hits": [{"source", "title", "doi", "date"}], "errors": [...]}.
    Used by `--placeholder-lookup online` (the pipeline writes the result as an
    artifact and the agent disposes it). Network failures are reported, never
    fatal.
    """
    import urllib.parse
    import urllib.request
    out = {"query": query, "hits": [], "errors": []}
    q = urllib.parse.quote(query)
    apis = (("europepmc",
             f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q}&format=json&pageSize=5"),
            ("openalex", f"https://api.openalex.org/works?search={q}&per-page=5"))
    for name, url in apis:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:                                        # noqa: BLE001
            out["errors"].append(f"{name}: {type(e).__name__}: {e}")
            continue
        if name == "europepmc":
            for item in (data.get("resultList") or {}).get("result") or []:
                out["hits"].append({"source": name, "title": item.get("title"),
                                    "doi": item.get("doi"),
                                    "date": item.get("firstPublicationDate")})
        else:
            for item in data.get("results") or []:
                out["hits"].append({"source": name, "title": item.get("display_name"),
                                    "doi": item.get("doi"),
                                    "date": item.get("publication_date")})
    return out


# A DOI suffix is not bracket-free: a legacy Wiley SICI DOI carries balanced
# parentheses AND angle-bracketed volume/page text AND a `;` before its check
# characters ("10.1002/(SICI)1097-0258(19980215)19:8<1001::AID-SIM743>3.0.CO;2-5").
# A `)`/`>`/`;` continues the identifier only when an identifier character
# follows; a closing bracket or a citation separator ends it.
DOI_RE = re.compile(
    r"\b10\.\d{4,9}/(?:[^\s,;)\]}>\"']"
    r"|[)](?=[A-Za-z0-9<])"
    r"|[>](?=[A-Za-z0-9<])"
    r"|[;](?=\d))+")
ACCESSION_RE = re.compile(r"\b(?:SRP|SRR|PRJNA|GSE|GSM|ERP|ERS|ERR|SAMN|SAMD)\d{3,}\b")
ORCID_RE = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")
GITHUB_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+"
                       r"(?:/(?:tree|commit)/[0-9a-fA-F]{7,40})?")


# ACCESSION_RE recognises ids that live in three different NCBI archives. A
# lookup that always searched `db=sra` answered 0 for the GEO/BioProject/
# BioSample ids (a real `GSE...` series is invisible there), and a 0 count sets
# `verdict` to `absent` -- the VERIFIED NEGATIVE the seeded
# `PLACEHOLDER_LOOKUP.md` turns into "not yet deposited". Each prefix is
# therefore resolved to the database that actually indexes it.
ACCESSION_DATABASES = (
    ("GSE", "gds"), ("GSM", "gds"),                 # GEO series / sample
    ("PRJNA", "bioproject"),                        # NCBI BioProject
    ("SAMN", "biosample"), ("SAMD", "biosample"),   # NCBI BioSample
)
ACCESSION_DEFAULT_DB = "sra"                        # SRP/SRR, ERP/ERS/ERR


def accession_database(accession: str) -> str:
    """The NCBI eutils database (`db=`) that indexes this accession id."""
    up = str(accession or "").strip().upper()
    for prefix, db in ACCESSION_DATABASES:
        if up.startswith(prefix):
            return db
    return ACCESSION_DEFAULT_DB


def _text_docs(docs) -> list:
    """Normalise [[(name, rows)], [(name, str)]] to [(name, text blob)]."""
    out = []
    for name, rows in (docs or []):
        if isinstance(rows, str):
            out.append((name, rows))
            continue
        parts = []
        for r in rows or []:
            parts.append(r[0] if isinstance(r, (list, tuple)) else str(r))
        out.append((name, "\n".join(parts)))
    return out


# Gene/protein symbols: a letter run followed by digits (KRAS, CD3D, IL7R, TP53),
# 2-6 characters, not a unit, not a version token, not inside a `\code{}` span.
GENE_SYMBOL_RE = re.compile(r"\b(?![A-Z]{1,2}\d*\b(?:\s*(?:kb|Mb|GB|GHz)\b))"
                            r"(?!(?:v|hg|grch|GRCh)\d)"
                            r"([A-Z][A-Z0-9]{1,5}\d[A-Z0-9]?\d?|[A-Z]{3,5}\d|[A-Z]{3,5})\b")
GENE_STOPWORDS = {"COVID19", "SARS2", "PCR2", "R2", "N50", "L2", "T2", "M1", "M2",
                  "S1", "S2", "F1", "F2", "P1", "P2", "CD8", "CD4", "DNA", "RNA",
                  "ATP", "SDS", "PBS", "PCR", "FACS", "DAPI", "SNP", "INDEL", "WGA",
                  "BAM", "BED", "TSV", "CSV", "DOI", "URL", "GPU", "CPU", "RAM",
                  "SI", "IQR", "ROC", "AUC", "PCC", "CN", "CNV", "CNA", "ITH", "WGD",
                  "HMM", "GMM", "BIC", "SD", "SEM", "ANOVA", "GIAB", "NIST", "ACT",
                  "MALBAC", "META", "CHM", "GRCH", "HG", "T2T", "MDA", "DLP", "GEO",
                  "SRA", "NCBI", "MIT", "TCGA", "GTF", "FASTQ", "FALSE", "TRUE", "NONE",
                  "NULL", "COLO", "UMI", "MCMC", "BAF", "ATAC", "SBS", "CPM", "TPM",
                  "FPKM", "HVG", "PCA", "UMAP", "TSNE", "KF", "NMD", "SCOPE", "STAR",
                  "EAGLE", "SEURAT", "COSMIC", "GINKGO", "CHISEL", "FLCNA", "SCYN",
                  "SCEVAN", "CONICSMAT", "CASPER", "INFERCNV", "COPYCAT", "NUMBAT"}


def gene_symbol_rows(docs) -> list:
    """Gene/protein symbols in the prose, for the HGNC nomenclature check.

    A gene symbol is a checkable fact (is it an approved HGNC symbol, or an
    alias?) and a typography convention (human gene symbols are italic, proteins
    roman).  Numbers and units are excluded, as are obvious non-symbols; the
    project lists (`extra_acronyms.txt`-style) stay the reviewer's job.
    """
    rows, seen = [], set()
    from collections import Counter as _Counter
    freq = _Counter()
    for _n, _t in _text_docs(docs):
        for _m in GENE_SYMBOL_RE.finditer(_t):
            freq[_m.group(1)] += 1
    gene_ctx = re.compile(r"\b(?:gene|genes|protein|mutation|mutations|expression|amplification|"
                          r"amplified|deletion|locus|oncogene|tumou?r suppressor|wild-type|"
                          r"knockdown|knockout|CRISPR|transcript|allele|isoform|rearrangement)\b",
                          re.I)
    for name, text in _text_docs(docs):
        masked = re.sub(r"\\code\{[^{}]*\}|\\url\{[^{}]*\}|\$[^$]*\$", " ", text)
        for m in GENE_SYMBOL_RE.finditer(masked):
            sym = m.group(1)
            if sym in GENE_STOPWORDS or sym in seen:
                continue
            ctx = re.sub(r"\s+", " ", masked[max(0, m.start() - 60):m.end() + 60]).strip()
            # The guard must look at the text BEFORE the symbol, not at an
            # 80-char window that mostly lies after it.
            before = re.sub(r"\s+", " ", masked[max(0, m.start() - 80):m.start()]).strip()
            if re.search(r"(?:Fig|Table|Eq|Ref|Supplementary|Section)\.?\s*$", before):
                continue
            if re.match(r"^S\d{1,3}$", sym):
                continue                      # a supplementary figure/table label
            seen.add(sym)
            # Rank candidates so a small lookup budget is spent on the likely
            # genes first: an all-letter symbol near gene language scores
            # highest, a letters+digits token near no gene language lowest (it is
            # usually a tool name with its citation superscript glued on).
            score = (2 if not any(ch.isdigit() for ch in sym) else 0) \
                + (2 if gene_ctx.search(ctx) else 0) \
                + (1 if re.search(rf"\b{re.escape(sym)}\b(?!\d)", ctx) else 0)
            rows.append({"document": name, "symbol": sym, "context": ctx[:150],
                         "score": score, "count": freq[sym], "verification": ""})
    rows.sort(key=lambda r: (-r["score"], -r["count"], r["symbol"]))
    return rows


def identifier_rows(docs) -> list:
    """Every external identifier in the corpus, with its sentence context.

    DOIs, SRA/BioProject/GEO accessions, repository URLs (and pinned commits)
    and ORCIDs are *checkable* facts, so the availability statements stop being
    verified by hand (`MANUAL_STEPS` item 14 in the reviewed run) and start
    being verified by the orchestrator.
    """
    rows, seen = [], set()
    for name, text in _text_docs(docs):
        for kind, rx in (("doi", DOI_RE), ("accession", ACCESSION_RE),
                         ("repository", GITHUB_RE), ("orcid", ORCID_RE)):
            for m in rx.finditer(text):
                value = m.group(0).rstrip(".,;)")
                key = (kind, value)
                if key in seen:
                    continue
                seen.add(key)
                ctx = re.sub(r"\s+", " ", text[max(0, m.start() - 70):m.end() + 70]).strip()
                rows.append({"document": name, "kind": kind, "value": value,
                             "context": ctx[:170], "verification": ""})
    return rows


# ---------------------------------------------------------------------------
# M2 reference-integrity seed: the identifiers a reference list CARRIES
# ---------------------------------------------------------------------------
# The citation sweep (M2) pairs call-outs with entries and M10 judges an entry's
# own format; neither can tell whether the identifier an entry carries is the
# identifier OF THE WORK THE ENTRY NAMES. That is a fact about the entry, and a
# one-character corruption (10.1890 -> 10.1891) leaves author, title, journal
# and year untouched, so every format check passes and re-reading the line finds
# nothing. This seed enumerates, per ENTRY, what the code can establish locally
# (the entry's own year, the DOI's own year token, a DOI stated twice, a DOI the
# syntax rejects) and hands the entry's DOI to the pipeline's lookup engine; the
# review disposes every row against the entry's own text.
# The heading that opens a reference list, normalized per line: markdown's `##`,
# a list ordinal, emphasis markers and a trailing colon are furniture, and a
# DOCX/markdown heading is the only thing that opens the region (a `.tex`
# bibliography is found by its own `\bibitem` markers instead).
REFERENCE_HEADING_WORDS = frozenset((
    "references", "references cited", "references and notes", "reference list",
    "bibliography", "literature cited", "works cited", "reference literature"))
# The numbered markers are read anywhere whitespace precedes them: the corpus
# scanner hands markdown/LaTeX text over as PARAGRAPHS (a reference list written
# without blank lines between entries arrives as ONE paragraph), so an anchored
# `^` pattern sees a single line and no entries at all.
REFERENCE_NUMBERED_RE = re.compile(r"(?:^|\s)(?:\[(\d{1,3})\]|(\d{1,3})[.)])\s+")
REFERENCE_AY_YEAR_RE = re.compile(r"[\(\[]\d{4}[\)\]]")
# An author-year entry opens with a surname run whose year follows in
# parentheses or brackets ("Berg, J. K. (2016).", "Berg and Smith (2016)",
# "Berg JK [2016]"): the same joined-paragraph problem, and a split that is
# never made would leave every row's body holding the WHOLE list -- which would
# make the resolved-title comparison vacuous (every title "appears" in it).
# The run between the name and the year may hold the rest of the author block
# (initials, commas, "&", "and") but NOT a digit and not a sentence boundary: a
# journal volume ("Nature 511. 430-440 (2014)") carries digits, and a second
# year inside the SAME entry ("Cell 165, 1-10 (2016)") is announced by "word.
# Word" -- both put a capitalized word within 40 characters of a parenthetical
# year, which is the shape this lookahead keys on.
REFERENCE_AY_START_RE = re.compile(
    r"(?<=[\s.;])(?=[A-Z][A-Za-z'`\-]{1,24}"
    r"(?:[^()\[\]\d.]|\.(?!\s*[A-Za-z]{2,})){0,40}?[\(\[]\d{4}[\)\]](?:[.,]\s*)?)")
REFERENCE_BIBITEM_RE = re.compile(
    r"(?m)^[ \t]*\\bibitem[ \t]*(?:\[[^\]]*\])?[ \t]*\{([^}]*)\}")
REFERENCE_BIBENTRY_RE = re.compile(r"(?m)^[ \t]*@\w+[ \t]*\{[ \t]*([^,\s]+)[ \t]*,")
REFERENCE_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
# The entry SAYS it carries a DOI (`doi`, `DOI:`, `https://doi.org/`): only then
# is a DOI-shaped token the syntax rejects worth a row.
REFERENCE_DOI_CLAIM_RE = re.compile(r"(?i)(?:\bdoi\b[ \t]*[:\s]|https?://(?:dx\.)?doi\.org/)")
REFERENCE_DOI_TOKEN_RE = re.compile(r"(?i)(?:doi[ \t]*[:\s]*|doi\.org/)[ \t]*(\S{4,90})")
# Words a resolver's title shares with the entry for grammatical reasons: they
# decide nothing about whether the entry and the record are the same work.
REF_HIT_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over", "under",
    "between", "using", "used", "are", "was", "were", "its", "their", "more",
    "than", "not", "but", "data", "study", "studies", "analysis", "results",
    "based", "among", "during", "after", "before", "across", "within", "without",
}


def _fold_space(text: str) -> str:
    """One line, no runs of whitespace (the seeded cells are single lines)."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _entry_year(body: str) -> str:
    """The entry's own year token ('' when the entry carries none).

    The FIRST year in the text is not always the entry's own: a title may carry
    one ("The 2015 Paris Agreement and forest loss. Nature Climate Change 2021;
    ..."), and every comparison downstream -- the resolver's year against it and
    the DOI's own year token against it -- is made with this value, so reading
    the title's year turned a correct entry into a year disagreement. A year in
    a BIBLIOGRAPHIC position therefore wins: one in parentheses or brackets (the
    author-year shape), else the first one the entry states as its own field
    (followed by the punctuation that delimits one -- `;`, `,`, `.`, `)` or `]`,
    or the end of the entry), which is also what keeps a year buried in a DOI
    suffix (`gb-2019-0002`) from being read as the entry's. The first year in
    the text stays the fallback for the shapes neither rule reaches.
    """
    body = body or ""
    years = list(REFERENCE_YEAR_RE.finditer(body))
    if not years:
        return ""
    # A year followed by the volume separator `;` is in the bibliographic
    # slot even when the title also carries a parenthesized year: checking
    # parentheses first read "A reply (2014). Nature 2016; ..." as 2014.
    for m in years:
        if body[m.end():m.end() + 1] == ";":
            return m.group(1)
    for m in years:
        if m.start() and body[m.start() - 1] in "([":
            return m.group(1)
    for m in years:
        if body[m.end():m.end() + 1] in ("", ",", ".", ")", "]"):
            return m.group(1)
    return years[0].group(1)


def _is_reference_heading(line: str) -> bool:
    """True for a line that is ONLY a reference-list heading (any furniture)."""
    t = str(line or "").strip().strip("*_#=\\{}").strip()
    t = re.sub(r"^\d+[.)]\s*", "", t).strip().rstrip(":").strip()
    return t.lower() in REFERENCE_HEADING_WORDS


def _is_section_heading(line: str) -> bool:
    """True for a line that opens a NEW section (which ends the region).

    Markdown's `#`/`##` heading and LaTeX's `\\section{}` are the two the region
    reader was written for; a line that is ENTIRELY bold (`**Acknowledgements**`)
    is a third shape the same text uses for a section, and without it the region
    ran on through the acknowledgements and glued them onto the LAST reference
    entry -- which made that entry's own text something other than the entry,
    the one thing the seeded rows are compared against.
    """
    t = str(line or "").strip()
    return bool(re.match(r"#{1,6}[ \t]+\S", t) or re.match(r"\\section\*?\{", t)
                or re.match(r"\*\*[^*]+\*\*$", t))


def _numbered_marker_run(spans: list) -> list:
    """The consecutive-number run inside the numbered marker's candidate spans.

    `(?:^|\\s)(\\d{1,3})[.)]` is not only how a reference list numbers itself:
    it is also how an ENTRY carries a journal volume ("Nature 511. 430-440") or
    a figure reference ("Fig. 3."), and trusting those cut real entries in half
    -- the row whose DOI the reviewer has to dispose then held "430-440 (2014).
    doi:..." and had lost the title it belongs to. A reference list's own
    markers run 1, 2, 3, ..., so the candidates are reduced to the longest run
    that steps by one: an in-entry number is SKIPPED, never trusted, and a later
    real marker is therefore not lost to it either.
    """
    best = []
    for i, m in enumerate(spans):
        run, n = [m], int(m.group(1) or m.group(2) or 0)
        for other in spans[i + 1:]:
            nxt = int(other.group(1) or other.group(2) or 0)
            if nxt == n + 1:
                run.append(other)
                n = nxt
        if len(run) >= len(best):
            best = run
    return best


def _split_reference_entries(text: str, allow_paragraphs: bool) -> list:
    """[(label, entry_text)] for one reference-list region.

    Markers first (`\\bibitem{key}` / `@type{key,` carry their own labels, then a
    numbered list), because they delimit entries exactly; the numbered shape
    needs three or more CONSECUTIVE markers (a lone `1.` line is a list, not a
    reference list) and is read only inside a reference region.
    `allow_paragraphs` is True only after a reference HEADING: an unlabelled
    author-year list is read as its paragraph blocks, and prose that merely
    happens to sit in a file is never read that way -- not even when it numbers
    its own sentences ("Test 1. ... Test 2. ... Test 3. ..."), which is the same
    shape and used to seed a row for a DOI the body merely mentioned.
    """
    shapes = [(REFERENCE_BIBITEM_RE, True, 1), (REFERENCE_BIBENTRY_RE, True, 1)]
    if allow_paragraphs:
        shapes.append((REFERENCE_NUMBERED_RE, False, 3))
    for pattern, keyed, minimum in shapes:
        spans = list(pattern.finditer(text))
        if not keyed:
            spans = _numbered_marker_run(spans)
        if len(spans) < minimum:
            continue
        entries = []
        for i, m in enumerate(spans):
            end = spans[i + 1].start() if i + 1 < len(spans) else len(text)
            label = (m.group(1) or "").strip() if keyed \
                else str(m.group(1) or m.group(2) or "").strip()
            entries.append((label, _fold_space(text[m.end():end])))
        return entries
    if not allow_paragraphs:
        return []
    # One sentinel space, so the FIRST entry (whose lookbehind has no character
    # before it) is a start too, and every index shifts back by one.
    cands = [m.start() - 1 for m in REFERENCE_AY_START_RE.finditer(" " + (text or ""))]
    cands = [s for s in cands if s >= 0]
    # A candidate is only an entry START when the text it would close already
    # carries a year of its own: the lookahead finds every capitalized word whose
    # parenthetical year sits near it, and in a real entry a CO-AUTHOR surname
    # ("Berg, J. K., & Smith, A. (2016).") is exactly that shape. Splitting
    # there left the first author on a ghost entry -- with no year and no DOI --
    # and handed the reviewer the row's text starting at the SECOND author.
    starts = []
    for s in cands:
        # A candidate preceded by "and"/"&" is the SECOND author of the entry
        # being read, not a new entry ("Smith, A. and Doe, B. (2019)").
        if re.search(r"(?:\band|&)\s+$", text[max(0, s - 12):s], re.I):
            continue
        if not starts or REFERENCE_AY_YEAR_RE.search(text[starts[-1]:s]):
            starts.append(s)
    if len(starts) >= 2:
        if starts[0] > 0:
            starts = [0] + starts
        ends = starts[1:] + [len(text)]
        return [("", _fold_space(text[a:b])) for a, b in zip(starts, ends)]
    blocks = [b for b in re.split(r"\n[ \t]*\n", text or "") if b.strip()]
    return [("", _fold_space(b)) for b in blocks]


def reference_entries(docs) -> list:
    """[(document, label, entry_text)] for every reference entry the code can read.

    DOCX paragraphs whose style map flags them as the bibliography are one entry
    each; a LaTeX/BibTeX list is read from its own markers wherever it sits; a
    plain-text list is read after a reference heading. A document with no
    heading, no marker and no flagged paragraph yields NOTHING -- the seed never
    guesses that prose is a reference list.
    """
    out = []
    for name, rows in (docs or []):
        if isinstance(rows, str):
            rows = [(rows, False, False)]
        rows = list(rows or [])
        flagged = [r for r in rows
                   if isinstance(r, (list, tuple)) and len(r) > 2 and r[1]]
        if flagged:
            for r in flagged:
                body = _fold_space(str(r[0]))
                if body:
                    out.append((name, "", body))
            continue
        text = "\n".join(str(r[0]) if isinstance(r, (list, tuple)) else str(r)
                         for r in rows)
        lines = text.splitlines()
        start = next((i for i, l in enumerate(lines) if _is_reference_heading(l)), None)
        if start is not None:
            # The region ends at the next section heading: a "Supplementary" or
            # "Acknowledgements" section after the list is not more entries.
            end = next((j for j in range(start + 1, len(lines))
                        if _is_section_heading(lines[j])), len(lines))
            region = "\n".join(lines[start + 1:end])
        else:
            region = text
        for label, body in _split_reference_entries(region, allow_paragraphs=start is not None):
            if body:
                out.append((name, label, body))
    return out


def doi_year_token_signal(doi: str, year: str) -> str:
    """'' when the DOI's own year token cannot contradict the entry's year.

    A DOI frequently embeds the publication year in its SUFFIX (`gb-2019-0002`;
    old Springer suffixes carry a two-digit one). The registrant prefix is
    never read: `10.1111/...` is Wiley's prefix, and reading it as a year would
    fire on every 2011 entry. A four-digit suffix token that agrees with the
    entry's year only in its LAST TWO DIGITS and sits within a century of it is
    the classic one-character corruption of that year (2019 -> 2119), and the
    entry's own year is the only place the true value is written -- so the
    disagreement is a SIGNAL for the reviewer to dispose, never a verdict. A
    token whose last two digits differ is not the entry's year at all (a series
    or volume number) and stays silent, and so does a date far outside the
    entry's era.
    """
    year = str(year or "").strip()
    if not re.fullmatch(r"\d{4}", year):
        return ""
    doi = str(doi or "")
    suffix = doi.split("/", 1)[1] if "/" in doi else ""
    for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", suffix):
        tok = m.group(1)
        delta = abs(int(tok) - int(year))
        if tok != year and tok[-2:] == year[-2:] and 2 <= delta <= 100:
            return (f"the DOI's own year token {tok} disagrees with the entry's {year} "
                    f"(same last two digits: a one-character corruption?)")
    return ""


def reference_entry_hit_signal(entry_text: str, hit: dict) -> str:
    """'' when the resolver's record agrees with the entry, else the disagreement.

    Two comparisons, each only when the record carries enough to make one: the
    year the resolver reports against the entry's own year (two years apart or
    more), and the resolved TITLE against the entry's text. The title test asks
    for an ABSOLUTE overlap, never a fraction of the record's own words: a
    registration record often carries a subtitle, a species name and a
    parenthetical the reference list legitimately abbreviates, so a fraction
    calls a correct entry "a different work" (the 2026-10-16 check: a real
    Crossref title ran 13 significant words against the entry's 8, and the
    fraction rule fired on the entry that was RIGHT). A record too thin to
    judge stays silent: the verdict itself is then all the reviewer has to
    dispose, and guessing past that is what the seed exists to prevent.

    Both sides are compared as WORDS with their punctuation folded: a record's
    "Single-cell RNA sequencing" and an entry's "Single cell RNA sequencing" are
    the same title (the hyphen is a typesetting choice, and the entry was
    reported as a different work for it), while a bare substring test let the
    record's "cell" match the entry's "cells" and hid a record that really was
    another work. Hyphens, dashes and other punctuation therefore become spaces
    on both sides, and each record token must appear as a WORD of the entry.
    """
    out = []
    year = _entry_year(entry_text)
    hy = str((hit or {}).get("date") or "").strip()
    if year and re.fullmatch(r"\d{4}", hy) and abs(int(hy) - int(year)) >= 2:
        out.append(f"the resolved work's year {hy} disagrees with the entry's {year}")
    title = str((hit or {}).get("title") or "")
    toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", title)
            if t.lower() not in REF_HIT_STOPWORDS]
    if len(toks) >= 3:
        low = _fold_space(re.sub(r"[^a-z0-9]+", " ", str(entry_text or "").lower()))

        def _found(t: str) -> bool:
            word = _fold_space(re.sub(r"[^a-z0-9]+", " ", t.lower()))
            return bool(word) and re.search(r"\b" + re.escape(word) + r"\b", low) is not None

        present = [t for t in toks if _found(t)]
        need = max(3, (len(toks) + 3) // 4)
        if len(present) < need:
            missing = [t for t in toks if not _found(t)][:6]
            out.append(f"the resolved work's title ({_fold_space(title)[:80]!r}) is not this "
                       f"entry's: only {len(present)} of its {len(toks)} significant words "
                       f"appear in the entry (missing: {', '.join(missing)})")
    return "; ".join(out)


def reference_integrity_rows(docs) -> list:
    """One row per reference ENTRY that carries a DOI (or claims one it lacks).

    Row fields: `document`, `entry` (the entry's own label), `year` (the entry's
    year token), `identifier`, `kind`, `signal` (what the code established
    locally) and `evidence` (the quoted token the reviewer re-checks), plus the
    entry text under `text` for the resolver comparison. The resolver verdict is
    joined in by the orchestrator; this function never guesses a citation's
    target and never touches the network.
    """
    entries = reference_entries(docs)
    by_doi = {}
    for i, (doc, label, body) in enumerate(entries):
        for doi in dict.fromkeys(m.group(0).rstrip(".,;") for m in DOI_RE.finditer(body)):
            # The OTHER entries are identified by their POSITION, never by
            # (document, label): a flagged DOCX bibliography paragraph and an
            # unlabelled author-year entry both carry the empty label, so keying
            # on it made every pair of them look like the same entry and the
            # duplicate-DOI signal never fired for the two shapes the seed was
            # extended to read.
            by_doi.setdefault(doi.lower(), []).append((i, doc, label))
    rows = []
    for i, (doc, label, body) in enumerate(entries):
        year = _entry_year(body)
        dois = list(dict.fromkeys(m.group(0).rstrip(".,;") for m in DOI_RE.finditer(body)))
        if not dois:
            if REFERENCE_DOI_CLAIM_RE.search(body):
                tok = REFERENCE_DOI_TOKEN_RE.search(body)
                rows.append({"document": doc, "entry": label, "year": year, "identifier": "",
                             "kind": "doi", "text": body, "signal": "doi-malformed",
                             "evidence": "the entry names a DOI but no well-formed DOI can be "
                                         "read beside it ("
                                         + repr((tok.group(1) if tok else "")[:60]) + ")"})
            continue
        for doi in dois:
            signal = doi_year_token_signal(doi, year)
            evidence = ""
            if signal:
                evidence = signal
            others = [f"{d} entry {l}" if l else f"another entry of {d}"
                      for j, d, l in by_doi.get(doi.lower(), []) if j != i]
            if others:
                dup = "the same DOI appears on " + ", ".join(others[:3]) + " too"
                signal = (signal + "; " + dup) if signal else "duplicate-doi"
                evidence = (evidence + "; " + dup) if evidence else dup
            rows.append({"document": doc, "entry": label, "year": year, "identifier": doi,
                         "kind": "doi", "text": body, "signal": signal, "evidence": evidence})
    return rows


def lookup_kind(kind: str, query: str, timeout: int = 30) -> dict:
    """One public-API lookup, per identifier/placeholder class.

    Verdict vocabulary (the orchestrator records it, the session disposes it):
      found   -- the thing exists (hits carry its identifier/title/date)
      absent  -- the query was answered and the thing does NOT exist (a
                 *verified negative*: this is what "not posted" is made of)
      error   -- the lookup could not be performed (network/HTTP); never fatal
    """
    import urllib.parse
    import urllib.request
    from datetime import datetime, timezone
    kind = (kind or "").strip().lower()
    out = {"kind": kind, "query": str(query), "hits": [], "verdict": "error",
           "errors": [], "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not str(query).strip():
        out["errors"].append("empty query")
        return out
    q = urllib.parse.quote(str(query))

    def fetch(url, headers=None):
        rq = urllib.request.Request(
            url, headers=headers or {"User-Agent": "paper-pipeline/3.5 (identifier lookup)"})
        with urllib.request.urlopen(rq, timeout=timeout) as r:      # noqa: S310
            return r.read().decode("utf-8", "replace")

    try:
        if kind in ("preprint", "paper", "title"):
            res = lookup_preprint(query, timeout=timeout)
            out["hits"] = res.get("hits") or []
            out["errors"] = res.get("errors") or []
            if out["hits"]:
                out["verdict"] = "found"
            elif not out["errors"]:
                out["verdict"] = "absent"
        elif kind == "doi":
            doi = re.sub(r"^https?://doi\.org/", "", str(query).strip())
            try:
                msg = json.loads(fetch("https://api.crossref.org/works/"
                                       + urllib.parse.quote(doi)
                                       + "?mailto=paper-pipeline@example.org"))["message"]
                out["hits"] = [{"source": "crossref",
                                "title": (msg.get("title") or [""])[0],
                                "doi": msg.get("DOI"),
                                "date": ((msg.get("issued", {}).get("date-parts")
                                          or [[None]])[0] or [None])[0]}]
                out["verdict"] = "found"
            except Exception as crossref_err:                         # noqa: BLE001
                # A DOI is registered with ONE registration agency and Crossref
                # answers only for its own: a DataCite DOI (Zenodo, OSF,
                # Dataverse, Dryad, ...) 404s there, and recording that as
                # `absent` turned a perfectly resolvable deposit into a
                # "verified negative" -- wrong evidence for an availability
                # statement and a false finding for a reference entry. The
                # second registry is therefore asked before nonexistence is
                # claimed, and `absent` now means BOTH registries answered no.
                try:
                    d = json.loads(fetch(
                        "https://api.datacite.org/dois/" + urllib.parse.quote(doi),
                        headers={"User-Agent": "paper-pipeline/3.5 (identifier lookup)",
                                 "Accept": "application/vnd.api+json"}))
                    attrs = ((d.get("data") or {}).get("attributes") or {})
                    title = ((attrs.get("titles") or [{}])[0] or {}).get("title") or ""
                    out["hits"] = [{"source": "datacite", "title": title,
                                    "doi": (d.get("data") or {}).get("id"),
                                    "date": attrs.get("publicationYear")
                                    or str(attrs.get("published") or "")[:4],
                                    "publisher": attrs.get("publisher")}]
                    out["verdict"] = "found"
                except Exception as datacite_err:                     # noqa: BLE001
                    if getattr(crossref_err, "code", None) == 404 \
                            and getattr(datacite_err, "code", None) == 404:
                        # Neither metadata agency serves every DOI: mEDRA, CNKI,
                        # JaLC and KISTI register DOIs of their own, and calling
                        # one of theirs "not registered" would be a false
                        # accusation. The handle registry answers for ALL
                        # agencies (responseCode 1 = the handle exists, 100 =
                        # it does not), so it is the arbiter and only its own
                        # answer licenses `absent`.
                        h, code = {}, -1
                        try:
                            h = json.loads(fetch("https://doi.org/api/handles/"
                                                 + urllib.parse.quote(doi)))
                            code = int(h.get("responseCode") or 0)
                        except Exception as handle_err:               # noqa: BLE001
                            # A nonexistent handle is answered with HTTP 404
                            # (and `{"responseCode": 100}` in the body when the
                            # registry sends one): the BODY is the answer where
                            # there is one, and the status is the answer where
                            # there is not -- reading the status alone turned
                            # every unregistered DOI into a lookup ERROR instead
                            # of the verified negative `absent` is for.
                            body = ""
                            if hasattr(handle_err, "read"):
                                try:
                                    body = handle_err.read().decode("utf-8", "replace")
                                except Exception:                      # noqa: BLE001
                                    body = ""
                            try:
                                h = json.loads(body)
                                code = int(h.get("responseCode") or 0)
                            except Exception:                          # noqa: BLE001
                                h, code = {}, -1
                            if code == -1 and getattr(handle_err, "code", None) == 404:
                                # The handle is not there (both metadata agencies
                                # have already said the same), so this IS the
                                # verified negative -- never a lookup failure.
                                code = 100
                            if code != 100:
                                out["errors"] += [f"crossref: {crossref_err}",
                                                  f"datacite: {datacite_err}",
                                                  f"doi.org: {handle_err}"]
                                out["verdict"] = "error"
                                return out
                        if code == 1:
                            url = next((((v.get("data") or {}).get("value") or "")
                                        for v in (h.get("values") or [])
                                        if str(v.get("type")) == "URL"), "")
                            out["hits"] = [{"source": "doi.org", "title": "",
                                            "doi": doi, "date": "", "url": url}]
                            out["verdict"] = "found"
                        elif code == 100:
                            out["verdict"] = "absent"
                        else:
                            out["errors"].append(f"doi.org handle API: {str(h)[:120]}")
                            out["verdict"] = "error"
                            return out
                    else:
                        out["errors"] += [f"crossref: {crossref_err}",
                                          f"datacite: {datacite_err}"]
                        out["verdict"] = "error"
                        return out
        elif kind == "accession":
            db = accession_database(query)
            d = json.loads(fetch("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
                                 "?db=" + db + "&retmode=json&term=" + q))
            n = int((d.get("esearchresult") or {}).get("count") or 0)
            if n:
                out["hits"] = [{"source": "ncbi-" + db, "count": n, "title": str(query)}]
                out["verdict"] = "found"
            else:
                out["verdict"] = "absent"
        elif kind in ("repository", "repo", "commit"):
            slug = re.sub(r"^https?://github\.com/", "", str(query).strip()).strip("/")
            parts = slug.split("/")
            if len(parts) < 2:
                out["errors"].append(f"not an owner/repo target: {query!r}")
                return out
            d = json.loads(fetch(f"https://api.github.com/repos/{parts[0]}/{parts[1]}",
                                 headers={"User-Agent": "paper-pipeline/3.5",
                                          "Accept": "application/vnd.github+json"}))
            if isinstance(d, dict) and d.get("full_name") and not d.get("message"):
                out["hits"] = [{"source": "github", "title": d.get("full_name"),
                                "date": d.get("pushed_at"), "private": bool(d.get("private")),
                                "license": (d.get("license") or {}).get("spdx_id")}]
                # A REACHABLE repository EXISTS even when it is private: this
                # vocabulary's `absent` is "the query was answered and the thing
                # does NOT exist" (a verified negative, what "not posted" is made
                # of), so a 200 answer that names the repo is `found` -- the hit
                # itself carries `private: true` for the session to dispose.
                out["verdict"] = "found"
            else:
                out["verdict"] = "absent"
            m = re.search(r"/(?:tree|commit)/([0-9a-fA-F]{7,40})", str(query))
            if m:
                sha = m.group(1)
                cd = json.loads(fetch(
                    f"https://api.github.com/repos/{parts[0]}/{parts[1]}/commits/{sha}",
                    headers={"User-Agent": "paper-pipeline/3.5",
                             "Accept": "application/vnd.github+json"}))
                if isinstance(cd, dict) and cd.get("sha"):
                    out["hits"].append({"source": "github-commit", "sha": cd["sha"][:12],
                                        "date": ((cd.get("commit") or {}).get("committer")
                                                 or {}).get("date"),
                                        "title": ((cd.get("commit") or {}).get("message")
                                                  or "").split("\n")[0][:80]})
                else:
                    out["errors"].append(f"pinned commit {sha} does not resolve")
        elif kind in ("archive", "deposit"):
            # A SEARCH always returns something: keep only records that actually
            # name the thing being looked for (a distinctive token of the query
            # in the record's title/description), or "found" would mean "the API
            # answered", not "the deposit exists". Derive the token BEFORE the
            # request: with none, the lookup cannot be answered.
            toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{5,}", str(query))
                    if t.lower() not in ("github", "https", "zenodo", "figshare",
                                         "research", "science", "single", "whole")]
            toks = sorted(toks, key=len, reverse=True)[:2]
            if not toks:
                out["errors"].append(
                    "the archive query carries no distinctive token (>= 6 "
                    "characters): relevance cannot be checked")
                return out
            d = json.loads(fetch("https://zenodo.org/api/records?size=5&q=" + q))
            hits = (d.get("hits") or {}).get("hits") or []

            def _relevant(h) -> bool:
                blob = " ".join(str(x or "") for x in (
                    (h.get("metadata") or {}).get("title"),
                    (h.get("metadata") or {}).get("description"),
                    h.get("doi"))).lower().replace("-", "").replace("_", "")
                return any(t.lower().replace("-", "") in blob for t in toks)
            hits = [h for h in hits if _relevant(h)]
            out["hits"] = [{"source": "zenodo",
                            "title": ((h.get("metadata") or {}).get("title") or "")[:120],
                            "doi": h.get("doi"),
                            "date": (h.get("metadata") or {}).get("publication_date")}
                           for h in hits]
            out["verdict"] = "found" if hits else "absent"
        elif kind == "orcid":
            d = json.loads(fetch("https://pub.orcid.org/v3.0/expanded-search/?q=" + q,
                                 headers={"User-Agent": "paper-pipeline/3.5",
                                          "Accept": "application/json"}))
            hits = d.get("expanded-result") or []
            out["hits"] = [{"source": "orcid",
                            "title": f"{h.get('given-names') or ''} "
                                     f"{h.get('family-name') or ''}".strip(),
                            "orcid": h.get("orcid-id"),
                            "affiliation": (h.get("institution-name") or [None])[0]}
                           for h in hits]
            out["verdict"] = "found" if hits else "absent"
        elif kind == "gene":
            sym = str(query).strip()
            d = json.loads(fetch("https://rest.genenames.org/fetch/symbol/"
                                 + urllib.parse.quote(sym),
                                 headers={"User-Agent": "paper-pipeline/3.5",
                                          "Accept": "application/json"}))
            docs_ = ((d.get("response") or {}).get("docs") or [])
            if docs_:
                out["hits"] = [{"source": "hgnc", "title": docs_[0].get("name"),
                                "symbol": sym, "hgnc_id": docs_[0].get("hgnc_id"),
                                "locus_type": docs_[0].get("locus_type"),
                                "aliases": (docs_[0].get("alias_symbol") or [])[:4]}]
                out["verdict"] = "found"
            else:
                out["hits"] = []
                out["verdict"] = "absent"
        else:
            out["errors"].append(f"unknown lookup kind {kind!r}")
    except Exception as e:                                            # noqa: BLE001
        out["errors"].append(f"{type(e).__name__}: {e}")
        # Crossref/HGNC answer "no such entity" with HTTP 404: that is the
        # VERIFIED NEGATIVE the verdict vocabulary calls `absent` (what "not
        # posted" is made of) -- recording it as a lookup ERROR left every
        # unknown DOI/accession/gene in the residual-hand-off list and made
        # `lookup_kind` unable to ever return `absent` for those kinds. GitHub
        # is deliberately excluded: it answers 404 for PRIVATE repositories
        # too, so a repo/commit 404 cannot claim nonexistence and stays an
        # `error` -- a reachable private repository is `found` with
        # `private: true` in its hit, and only an answered query with no hit at
        # all is `absent`.
        if getattr(e, "code", None) == 404 and kind not in ("repository", "repo", "commit"):
            out["verdict"] = "absent"
        else:
            out["verdict"] = "error"
    return out


def _corpus_title(blob: str) -> str:
    m = re.search(r"Manuscript title:\s*(.+)", blob)
    if m:
        return m.group(1).strip().split("\n")[0][:200]
    for line in blob.splitlines():
        t = line.strip()
        words = t.split()
        if 6 <= len(words) <= 30 and ":" in t \
                and not t.lower().startswith(("http", "figure", "table", "supplementary",
                                              "keywords")):
            return t.split("|")[0].strip()[:200]
    return ""


def placeholder_lookup_plan(ph_rows: list, docs=None) -> list:
    """Which public lookup answers which searchable hand-off marker."""
    blob = "\n".join(t for _n, t in _text_docs(docs or []))
    title = _corpus_title(blob)
    repos = [m.group(0) for m in GITHUB_RE.finditer(blob)]
    accs = [m.group(0) for m in ACCESSION_RE.finditer(blob)]
    dois = [m.group(0) for m in DOI_RE.finditer(blob)]
    plan = []
    for r in ph_rows or []:
        if str(r.get("class") or "") != "searchable":
            continue
        payload = (r.get("payload") or "").lower()
        kind = str(r.get("kind") or "").strip().lower()
        if not kind:
            if "preprint" in payload:
                kind = "preprint"
            elif "persistent identifier" in payload or "doi" in payload:
                kind = "archive"
            elif "accession" in payload:
                kind = "accession"
            elif "orcid" in payload:
                kind = "orcid"
            else:
                kind = "preprint"
        if kind in ("preprint", "paper", "title"):
            queries = [q for q in (title,) if q]
        elif kind in ("doi", "archive", "deposit", "repository", "repo", "commit"):
            queries = list(repos[:3]) + list(dois[:2])
            if kind in ("doi", "archive", "deposit") and title:
                queries.append(title)
        elif kind == "accession":
            queries = list(accs[:6])
        else:                                   # ORCID / author identity
            queries = []
        for q in dict.fromkeys(queries):
            # The lookup kind follows the QUERY's own class: a GitHub URL or a
            # title handed to `lookup_kind("doi", ...)` was answered as a DOI
            # and could report a false verified-negative. A DOI placeholder
            # gets DOI-shaped queries only; repository URLs keep the
            # repository kind and the title the preprint/title kind.
            qkind = kind
            if DOI_RE.fullmatch(str(q).strip()):
                qkind = "doi"
            elif GITHUB_RE.fullmatch(str(q).strip()):
                qkind = "repository"
            elif q in repos:
                qkind = "repository"
            elif q in dois:
                qkind = "doi"
            elif kind in ("doi", "archive", "deposit", "repository", "repo",
                          "commit"):
                qkind = "title"
            plan.append({"document": r.get("document"),
                         "paragraph": r.get("document_paragraph"),
                         "kind": qkind, "query": q,
                         "payload": (r.get("payload") or "")[:120]})
    return plan


def _num_candidates(value: float) -> set:
    out = set()
    # A rounded spelling that is ZERO for a nonzero cell proves the wrong
    # number ("0.00" from 4e-7); keep the documented 1.773 -> 1.77 rounding,
    # but never emit a zero-only rounding of a nonzero value.
    for dec in (0, 1, 2, 3):
        # A whole-number spelling must EQUAL the value: dec-0 formatting turns
        # 6.6 into "7", and the reconciliation then "proved" a written 7 from a
        # 6.6 cell. Two-or-more-decimal rounding stays: 1.773 -> 1.77 is the
        # documented "value in a table proves the rounded written form".
        # Zero-padding (7 -> 7.0) is always a valid spelling.
        if dec < 2 and abs(round(float(value), dec) - float(value)) > 1e-9:
            continue
        if dec >= 2 and float(value) != 0 and round(float(value), dec) == 0:
            continue
        s = f"{value:,.{dec}f}"
        out.add(s)
        out.add(s.replace(",", ""))
    # The cell's own exact spelling, scientific notation and the typographic
    # minus are the same value; without them a written 0.00012 / 1.2e-4 / −80
    # was never proved by its own source cell.
    for fmt_s in (f"{float(value):.15g}", f"{float(value):.6e}"):
        out.add(fmt_s)
        mant, _, exp = fmt_s.partition("e")
        if exp:
            try:
                out.add(f"{mant}e{int(exp)}")
                out.add(f"{mant}E{int(exp)}")
            except ValueError:
                pass
    try:
        from decimal import Decimal
        exact = format(Decimal(str(float(value))), "f")
        if exact not in ("0", "0.0"):
            out.add(exact)
    except Exception:                                            # noqa: BLE001
        pass
    for cand in list(out):
        if cand.startswith("-"):
            out.add("\u2212" + cand[1:])
    return out


ROW_COUNT_SOURCE_PREFIX = "number of data rows in "


def table_value_index(tables: list) -> dict:
    """{value string: 'sum of column X in file'} for tabular data files.

    The point is provenance, not statistics: when a number in the manuscript
    equals a column sum / min / max of a file the package ships, the code can
    PROVE where it came from (45,365 = the sum of `n_cells_total`; 2,055 = its
    maximum; 1.77 = the minimum sample-mean ploidy).  Numbers that no shipped
    file proves stay for the agent/author and are reported as such.
    """
    index = {}
    for name, text in tables or []:
        header, body = _simple_table(text)
        if header is None:
            continue
        for c in range(min(len(header), max(len(r) for r in body))):
            vals = []
            col_has_unit = False
            for r in body:
                if c >= len(r):
                    continue
                # A percentage or a currency amount is not the plain number it
                # contains: indexing "50" from a "50%" cell let the M30
                # reconciliation prove an unrelated count 50 (the 2026-10-28
                # audit's F42). The unit-bearing cell is not indexed, and the
                # column's aggregates are not either.
                if any(u in str(r[c]) for u in ("%", "$")):
                    col_has_unit = True
                    continue
                fv = _cell_number(r[c])
                if fv is None:
                    continue
                vals.append(fv)
                label = r[0].strip() if r else ""
                for cand in _num_candidates(fv):
                    index.setdefault(
                        cand, f"value in column {header[c]!r}, row {label!r} in {name}"
                        if label else f"value in column {header[c]!r} in {name}")
            if col_has_unit or len(vals) < 3:
                continue
            # The table's SHAPE is a reported statistic: G-041 requires the row
            # count to be every data row, not only the cells a column holds. It
            # is indexed for the operator, but `reconcile_number_rows` never
            # treats it as provenance: an unrelated table's height cannot prove
            # an arbitrary written small integer (the 2026-10-28 audit's F42).
            for cand in _num_candidates(float(len(body))):
                index.setdefault(cand, f"{ROW_COUNT_SOURCE_PREFIX}{name}")
            for kind, val in (("sum", sum(vals)), ("min", min(vals)), ("max", max(vals))):
                for cand in _num_candidates(val):
                    index.setdefault(cand, f"{kind} of column {header[c]!r} in {name}")
    return index


# --------------------------------------------------------------------------
# M30 -- THE SOURCE-HIERARCHY RECONCILIATION SEED.
#
# The hierarchy (github code > raw data > main figures > ... > supplementary
# text) is stated as a RESOLUTION rule: it decides which side wins when two
# sources already disagree.  Nothing enumerated the DETECTION side -- a written
# number, parameter, sample size or label that disagrees with the code or the
# raw data that produced it was found only if a human happened to compare them.
# The M30 sweep closes that gap in the review; these functions are the part of
# it the code can prove for itself:
#   * `table_column_stats` describes every shipped table column (size, min/max/
#     mean/sum, example values), so a written value has something to be
#     reconciled AGAINST;
#   * `hierarchy_seed_rows` pairs every written number the shipped tables do NOT
#     already prove with its candidate producer column(s), and states the
#     mechanical check it can make (a cohort-size sentence against the table's
#     own row count; a value against the column's values and statistics);
#   * `code_literal_rows` extracts the module-level literals code/config files
#     declare (`N_SAMPLES = 15`, `"threshold": 0.05`), which is the producer
#     side of a Methods parameter.
# None of these decide anything: every row is seeded for the session to dispose
# (OK with the reconciling reason / finding id / `unable -- producer not in the
# corpus`).  The code's job is to make the quiet half of the comparison a row,
# not to guess the answer.
# --------------------------------------------------------------------------

TABLE_STATS_FILE_LIMIT = 40
CODE_FILE_BYTES_LIMIT = 400_000
CODE_SOURCE_EXTS = (".py", ".r", ".jl", ".m", ".sh", ".bash", ".c", ".cc", ".cpp",
                    ".h", ".hpp", ".java", ".scala", ".nf", ".smk", ".yaml", ".yml",
                    ".json", ".toml", ".cfg", ".ini", ".ipynb")

# A module-level literal: `NAME = 15`, `NAME: 0.05,`, `export const N = 12;`.
CODE_LITERAL_RE = re.compile(
    r"^\s*(?:export\s+|public\s+|static\s+|final\s+|const\s+|let\s+|var\s+)*"
    r"(?P<name>[\"']?[A-Za-z_][A-Za-z0-9_.]{1,40}[\"']?)\s*[:=]\s*"
    r"(?P<value>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|'[^']{1,60}'|\"[^\"]{1,60}\")"
    r"\s*[,;]?\s*(?:#|//|$)")
# Names that carry an operational parameter (a Methods-relevant constant).
CODE_NAME_HINT_RE = re.compile(
    r"(?i)(n_|num|count|sample|patient|donor|cell|dataset|cohort|subject|param|"
    r"threshold|cutoff|seed|alpha|beta|rate|size|dim|epoch|iter|fold|limit|window|"
    r"min|max|version|batch|depth|coverage|resolution|kmer|fdr|pval|qval|tolerance)")

_M30_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]{2,}")
_M30_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those", "were",
    "was", "are", "has", "have", "had", "into", "over", "under", "than", "then",
    "each", "per", "all", "its", "our", "their", "which", "when", "where", "using",
    "used", "use", "was", "we", "of", "in", "on", "at", "by", "to", "as", "is",
}
_M30_ID_HEADER_RE = re.compile(
    r"(?i)(^|[_\s])(id|sample|patient|donor|cell|barcode|dataset|subject|case|"
    r"cohort|file|name)([_\s]|$)")


def _simple_table(text: str):
    """(header, body) of one tabular text file, or (None, None).

    ONE parser for `table_value_index` (a value a shipped table proves) and
    `table_column_stats` (M30: the column a written value is reconciled
    against), so the two can never read the same table differently.
    """
    lines = [l for l in str(text or "").splitlines() if l.strip()]
    if len(lines) < 3:
        return None, None
    head = lines[0]
    delim = ("\t" if "\t" in head else
             ("|" if head.count("|") >= 2 else
              ("," if head.count(",") >= 1 else None)))
    if delim is None:
        return None, None
    def cells(line: str) -> list:
        if delim == "|":
            # Markdown row: the leading/trailing pipes are delimiters, not
            # empty first/last columns (they each used to emit a phantom
            # empty-name column of statistics).
            line = line.strip()
            if line.startswith("|"):
                line = line[1:]
            if line.endswith("|"):
                line = line[:-1]
        # csv.reader honours quoted delimiters: `"Smith, Jr.",1,ok` is three
        # columns, not four. The pipe form has already had its outer pipes
        # stripped above.
        return [c.strip() for c in next(csv.reader([line], delimiter=delim,
                                                   skipinitialspace=True))]

    header = cells(head)
    body = [cells(l) for l in lines[1:]]
    if delim == "|" and body and body[0]:
        # `|---|---|` (with optional alignment colons) is the separator row, not
        # a data row: counting it made every table's row count off by one.
        if all(re.fullmatch(r":?-{2,}:?", c or "") for c in body[0]):
            body = body[1:]
    if len(header) < 2 or not body:
        return None, None
    return header, body


def _cell_number(cell: str):
    """The float a table cell carries, or None (empty/NaN/non-numeric)."""
    v = (str(cell or "").replace(",", "").replace("$", "").replace("%", "")
         .replace("\u2009", "").replace("\u202f", "").replace("\u00a0", "")
         .replace("\u2212", "-").strip())
    if v.lower() in ("", "nan", "na", "n/a", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _fmt_number(value: float) -> str:
    """A human number: thousands separators, no trailing zeros."""
    if value and abs(value) < 5e-7:
        # Six decimals rounded every real p-value below 5e-7 to "0" (and a
        # negative one to "-0"): keep the magnitude in scientific notation.
        return f"{value:.6g}"
    out = f"{value:,.6f}".rstrip("0").rstrip(".")
    return out or "0"


def table_column_stats(tables: list) -> list:
    """One row per (shipped table, column): its size and numeric shape.

    This is the producer-side half of an M30 row: `n rows` is what a
    cohort-size claim must reconcile against, and min/max/mean/sum are what a
    rounded or aggregated written value can be checked against. `values` stays
    on the row for the seed's own exactness test (the artifact table prints the
    other columns).
    """
    stats = []
    for name, text in (tables or [])[:TABLE_STATS_FILE_LIMIT]:
        header, body = _simple_table(text)
        if header is None:
            continue
        ncols = min(len(header), max(len(r) for r in body))
        for c in range(ncols):
            values, examples = [], []
            for r in body:
                if c >= len(r):
                    continue
                fv = _cell_number(r[c])
                if fv is None:
                    continue
                values.append(fv)
                if len(examples) < 3 and str(r[c]).strip():
                    examples.append(str(r[c]).strip())
            stats.append({"file": name, "column": header[c],
                          "n rows": len(body), "numeric n": len(values),
                          "min": _fmt_number(min(values)) if values else "",
                          "max": _fmt_number(max(values)) if values else "",
                          "mean": _fmt_number(sum(values) / len(values)) if values else "",
                          "sum": _fmt_number(sum(values)) if values else "",
                          "examples": ", ".join(examples),
                          "values": values[:200]})
    return stats


def code_literal_rows(sources: list, limit: int = 200, skip_name=None) -> list:
    """Module-level literals in the corpus's code/config files (M30 producer side).

    A Methods parameter ("we used a threshold of 0.05", "15 samples") has a
    producer in the analysis code; this extracts the constants the code itself
    declares, so the session can pair them with the written statements instead
    of hoping to notice both. Deliberately bounded (extension allow-list, a file
    size cap, a row cap) and name-filtered (ALL_CAPS or an operational hint) --
    a code file's every assignment is not a claim.

    `skip_name` is the caller's bookkeeping predicate (the pipeline passes its
    own `is_bookkeeping_name`, so a `revision_report.json` never reads as an
    analysis constant); the module always skips revision auxiliaries, editor
    lock files and process scratch.
    """
    rows, seen = [], set()
    for src, prefix, excluded in sources or []:
        if not src.is_dir():
            continue
        for p in sorted(src.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in CODE_SOURCE_EXTS:
                continue
            try:
                if p.stat().st_size > CODE_FILE_BYTES_LIMIT:
                    continue
            except OSError:
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if "work" in rel.split("/")[:-1] or _is_aux_name(p.name) \
                    or p.name.startswith("~$") or (skip_name and skip_name(p.name)):
                continue
            try:
                text = p.read_text("utf-8", "replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                m = CODE_LITERAL_RE.match(line)
                if not m:
                    continue
                name = m.group("name").strip().strip("\"'")
                value = m.group("value").strip()
                upper_caps = name.upper() == name and any(c.isalpha() for c in name)
                if not (upper_caps or CODE_NAME_HINT_RE.search(name)):
                    continue
                key = (prefix + rel, name, value)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"file": prefix + rel, "line": i, "symbol": name, "value": value,
                             "context": re.sub(r"\s+", " ", line.strip())[:100]})
                if len(rows) >= limit:
                    return rows
    return rows


# --------------------------------------------------------------------------
# M30, the NON-NUMERIC half: a written NEGATIVE claim against the shipped
# tables' own VALUES.
#
# M30 enumerated only numbers, so the hierarchy's detection side never saw the
# other direction: the manuscript says a method "could not be run" (or produced
# no output / was not evaluated / was excluded) while the figure's own source
# data ships rows FOR that method with finite values. That is exactly the
# contradiction the hierarchy exists to resolve (raw data > manuscript prose),
# and nothing compared the two. The rows below pair such a sentence with the
# table rows that contradict it. A token that appears in the sentence only as an
# ordinary word (an author's surname, a place) is filtered by requiring the
# token to be a VALUE of a tool-like column (header hint) or a repeated
# categorical value of a small-cardinality column.
# --------------------------------------------------------------------------

NEGATIVE_CLAIM_RE = re.compile(
    r"(?i)\b(?:could\s+not\s+be\s+(?:run|executed|evaluated|included|applied)|"
    r"was\s+not\s+run|were\s+not\s+run|not\s+(?:run|evaluated|included)|"
    r"did\s+not\s+produce\s+(?:any\s+)?output|produced\s+no\s+output|"
    r"failed\s+to\s+produce\s+(?:any\s+)?output|"
    r"could\s+not\s+be\s+assessed|is\s+not\s+evaluated|are\s+not\s+evaluated|"
    r"was\s+excluded|were\s+excluded)\b")
# The "excluded / not included" branches routinely talk about SAMPLES, not
# about a method ("Samples from the pilot cohort were excluded before the SCYN
# caller was applied"); the subject rule below keeps a categorical value of an
# unrelated column (the cohort's own label) from producing a row that claims
# the text says that value "was not run".
NEGATIVE_SUBJECT_METHOD_ONLY_RE = re.compile(
    r"(?i)\b(?:(?:was|were)\s+excluded|not\s+included|could\s+not\s+be\s+included)\b")
TABLE_TOOL_HEADER_RE = re.compile(
    r"(?i)^\s*(?:tool|method|caller|software|pipeline|package|program|algorithm|"
    r"model|scorer|name)\s*$")
TABLE_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{1,24}$")


def table_value_tokens(tables: list, max_tokens: int = 400, min_rows: int = 4,
                       max_producers: int = 6) -> dict:
    """{value token -> [(tool_like, where, context tokens), ...]}.

    Two column shapes qualify: a header that names a tool/method/caller field,
    and any column whose values are short, repeated, and few (a categorical
    column). Free-text columns never contribute tokens.

    A token is kept under EVERY table that carries it (up to `max_producers`),
    not just the first one: one caller's name appears in the simulated-data
    table, the ACT table and the scRNA tables alike, and the 2026-10-17 audit of
    the CopyNumBench package showed why that matters -- the Methods say CHISEL
    was "not evaluated" on ACT while the ACT table carries its rows, but the
    seed named the FIRST table where "chisel" appears (the germline MCB table,
    where it WAS evaluated) and the session correctly disposed that pairing as a
    false positive. The claim's own context (the word "ACT", a sample id) now
    chooses among the producers instead of the file order. `context tokens` are
    the other categorical values of the same table, so a sentence that names one
    of them ranks that table first.
    """
    tokens = {}
    for name, text in tables or []:
        header, body = _simple_table(text)
        if header is None or len(body) < min_rows:
            continue
        width = min(len(header), max(len(r) for r in body))
        # First pass: which columns are categorical (the context vocabulary).
        cat_values = {}
        for c in range(width):
            values = [str(r[c]).strip() for r in body if c < len(r) and str(r[c]).strip()]
            if not values:
                continue
            distinct = set(values)
            categorical = (len(distinct) <= 40 and len(distinct) < len(values)
                           and all(len(v) <= 24 for v in distinct))
            if categorical:
                cat_values[c] = sorted(distinct)
        for c in range(width):
            values = [str(r[c]).strip() for r in body if c < len(r) and str(r[c]).strip()]
            if not values:
                continue
            distinct = set(values)
            tool_like = bool(TABLE_TOOL_HEADER_RE.match(str(header[c])))
            categorical = (len(distinct) <= 40 and len(distinct) < len(values)
                           and all(len(v) <= 24 for v in distinct))
            if not (tool_like or categorical):
                continue
            for v in sorted(distinct):
                if not TABLE_TOKEN_RE.match(v) or v.lower() in ("true", "false", "nan", "inf"):
                    continue
                key = v.lower()
                ctx = set()
                for c2, vals in cat_values.items():
                    if c2 == c:
                        continue
                    ctx.update(x.lower() for x in vals if len(x) >= 2)
                entry = (tool_like, f"value {v!r} of column {header[c]!r} in {name}",
                         tuple(sorted(ctx))[:40])
                bucket = tokens.setdefault(key, [])
                # A tool-like column wins over a categorical one for the same
                # table; keep at most `max_producers` distinct tables.
                if any(e[1] == entry[1] for e in bucket):
                    continue
                bucket.append(entry)
                bucket.sort(key=lambda e: (not e[0], e[1]))
                del bucket[max_producers:]
    out = {}
    for key in sorted(tokens)[:max_tokens]:
        out[key] = tokens[key]
    return out


def negative_claim_rows(texts: list, tables: list, limit: int = 40) -> list:
    """M30 seed: a "not run / no output" claim a shipped table contradicts."""
    tokens = table_value_tokens(tables)
    if not tokens:
        return []
    rows, seen = [], set()
    for text in texts or []:
        s = re.sub(r"\s+", " ", str(text or "")).strip()
        if not s:
            continue
        for m in NEGATIVE_CLAIM_RE.finditer(s):
            sentence = s[max(0, m.start() - 200):m.end() + 200]
            lowered = sentence.lower()
            # The claim's SUBJECT, inferred from word order: only a token that
            # PRECEDES the negative phrase can be what the sentence says was
            # "not run" ("SCYN could not be run"). A token that merely follows
            # it ("... were excluded before the SCYN caller was applied") is
            # not the subject, and pairing it reported the opposite of the text.
            claim_at = m.start() - max(0, m.start() - 200)
            method_only = NEGATIVE_SUBJECT_METHOD_ONLY_RE.search(m.group(0)) is not None
            hits = []
            for token, entries in tokens.items():
                tm = re.search(r"(?<![A-Za-z0-9])" + re.escape(token)
                               + r"(?![A-Za-z0-9])", lowered)
                if tm is None or tm.start() >= claim_at:
                    continue
                for tool_like, where, ctx in entries:
                    if method_only and not tool_like:
                        # "excluded"/"not included" is a claim about the samples
                        # unless it names a tool/method column's own value.
                        continue
                    # The sentence's own context (a panel/sample name the table
                    # also carries) decides WHICH producer the claim is about;
                    # with no context the tool-like column still ranks first.
                    ctx_hit = 1 if any(re.search(
                        r"(?<![A-Za-z0-9])" + re.escape(x) + r"(?![A-Za-z0-9])", lowered)
                        for x in ctx) else 0
                    hits.append((-ctx_hit, 0 if tool_like else 1, token, where))
            # One sentence usually names ONE method and several of the table's
            # other categorical values (the cohort, the cell line). Report the
            # tool-like tokens first and cap the sentence's rows, so the seed
            # names the contradiction instead of the whole column.
            per_token = {}
            for _ctx, _rank, token, where in sorted(hits):
                if per_token.get(token, 0) >= 2:
                    continue
                key = (token, where, sentence[:80])
                if key in seen:
                    continue
                seen.add(key)
                per_token[token] = per_token.get(token, 0) + 1
                rows.append({
                    "rule": "M30-NC", "severity": "medium",
                    "claim": sentence[:220], "token": token, "producer": where,
                    "detail": (f"the text says {token!r} was not run / produced no output while "
                               f"a shipped table carries it ({where}); the hierarchy makes the "
                               f"raw-data side authoritative -- either the table's rows are "
                               f"stale and must be removed, or the written claim is wrong"),
                })
                if len(rows) >= limit:
                    return rows
                if sum(per_token.values()) >= 4:
                    break
    return rows


def _cohort_reference_re(number: str):
    """The sentence shape that makes a written number a cohort SIZE."""
    num = re.escape(str(number))
    return re.compile(
        r"(?i)(\bn\s*=\s*" + num + r"\b|\b" + num +
        r"\s+(?:samples?|patients?|donors?|cells?|datasets?|cohorts?|subjects?|cases?|"
        r"participants?|individuals?|libraries?|replicates?))")


def _m30_header_tokens(column) -> set:
    """The nouns of a table header, split on `_` and camelCase boundaries.

    A shipped analysis table writes its header as `Age_years` / `nSamples`
    where the prose says "age" / "samples". With the raw underscore compound as
    ONE token there is no overlap, so `hierarchy_seed_rows` reported "no
    shipped table column matches this sentence" and the session was told to
    record `unable — producer not in the corpus` while the producing column sat
    in the package.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(column or ""))
    tokens = set()
    for token in _M30_TOKEN_RE.findall(spaced.lower()):
        tokens.add(token)
        tokens.update(part for part in token.split("_") if len(part) >= 3)
    return tokens


def hierarchy_seed_rows(number_rows: list, tables: list, limit: int = 200) -> list:
    """M30 seed: every un-proved written number paired with candidate producers.

    `number_rows` is the pipeline's numbers ledger (a `source` already filled by
    `reconcile_number_rows` means a shipped table PROVED the value: it is not a
    candidate). For each remaining row on a claim-bearing surface, find the
    table column(s) whose header shares the sentence's own nouns -- plus, for a
    cohort-size sentence ("n = 12", "15 samples"), every ID-shaped column -- and
    state the mechanical check the code can make: the written number against the
    table's OWN row count, and against the column's values/statistics. The
    verdict column is left empty: the session reconciles, or records that the
    producer is not in the corpus.
    """
    stats = table_column_stats(tables)
    rows, seen = [], set()
    for r in number_rows or []:
        if len(rows) >= limit:
            break
        if str(r.get("source") or "").strip():
            continue
        kind = str(r.get("kind") or "body")
        if kind not in ("front", "abstract", "body", "legend"):
            continue
        num = str(r.get("number") or "").strip()
        if not num:
            continue
        sentence = re.sub(r"\s+", " ", str(r.get("sentence") or "")).strip()
        if not sentence:
            continue
        # A display-item label is not a claim about a quantity: "Figure 1 | ..."
        # and "Table 2 shows ..." carry the item's NUMBER, not a value to
        # reconcile against a producer.
        if re.search(r"(?i)\b(?:fig(?:ure)?s?|tables?|equations?|sections?|notes?)"
                     r"\s*\.?\s*" + re.escape(num) + r"\b", sentence):
            continue
        tokens = {t for t in _M30_TOKEN_RE.findall(sentence.lower())
                  if t not in _M30_STOPWORDS}
        cohort = bool(_cohort_reference_re(num).search(sentence))
        candidates = []
        for s in stats:
            head_tokens = _m30_header_tokens(s.get("column"))
            overlap = len(head_tokens & tokens)
            id_col = bool(_M30_ID_HEADER_RE.search(str(s.get("column") or "")))
            if overlap or (cohort and id_col):
                candidates.append((overlap + (2 if cohort and id_col else 0),
                                   bool(cohort and id_col), s))
        candidates.sort(key=lambda x: (-x[0], x[2]["file"], x[2]["column"]))
        picked, seen_cols = [], set()
        for score, rowcount_hit, s in candidates:
            key = (s["file"], s["column"])
            if key in seen_cols:
                continue
            seen_cols.add(key)
            picked.append((rowcount_hit, s))
            if len(picked) >= 3:
                break
        paragraph = r.get("document_paragraph")
        if paragraph is None:
            paragraph = r.get("paragraph")
        key = (str(r.get("document") or ""), str(paragraph), num, sentence[:60])
        if key in seen:
            continue
        seen.add(key)
        base = {"document": r.get("document"), "paragraph": paragraph, "kind": kind,
                "number": num,
                "unit": str(r.get("unit") or ""), "sentence": sentence[:120]}
        if not picked:
            rows.append(dict(base, **{
                "candidate producer": "(no shipped table column matches this sentence)",
                "producer summary": "",
                "seed check": "look for the producer in code/ or raw_data/ (the figure or "
                              "analysis that prints this value); if it is not in the corpus, "
                              "record `unable -- producer not in the corpus`"}))
            continue
        for rowcount_hit, s in picked:
            if rowcount_hit and s["n rows"]:
                same = _cell_number(num) == float(s["n rows"])
                check = (f"the sentence reads {num}; {s['file']} has {s['n rows']} data row(s) "
                         f"in column {s['column']!r}"
                         + ("" if same else " -- reconcile (or record the reconciling reason)"))
            else:
                col_values = set()
                for v in s["values"]:
                    col_values |= _num_candidates(v)
                # The same separator normalization reconcile_number_rows()
                # uses: a thin/NBSP/space-grouped written value is the same
                # number as the plain cell.
                key = re.sub(r"[,\u2009\u202f\u00a0\s]", "", num).rstrip(".")
                if num in col_values or key in col_values:
                    check = (f"the value matches a cell in column {s['column']!r} -- record why "
                             f"the ledger has no source, or cite this column")
                else:
                    seen_txt = s["examples"] or "none"
                    check = (f"no exact match in column {s['column']!r} (examples: {seen_txt}; "
                             f"min {s['min'] or '-'} / max {s['max'] or '-'} / mean "
                             f"{s['mean'] or '-'}) -- compare the written value against it")
            rows.append(dict(base, **{
                "candidate producer": f"{s['file']}:{s['column']}",
                "producer summary": (f"{s['n rows']} row(s); {s['numeric n']} numeric; "
                                     f"min {s['min'] or '-'} / max {s['max'] or '-'} / mean "
                                     f"{s['mean'] or '-'} / sum {s['sum'] or '-'}"),
                "seed check": check}))
    return rows[:limit]


def reconcile_number_rows(rows: list, tables: list) -> dict:
    """Fill `source` on ledger rows that a shipped DATA file proves, by code."""
    index = table_value_index(tables)
    filled = 0
    for r in rows:
        if (r.get("source") or "").strip():
            continue
        num = str(r.get("number") or "").strip()
        if not num:
            continue
        key = re.sub(r"[,\u2009\u202f\u00a0\s]", "", num).rstrip(".")
        hit = index.get(num) or index.get(key)
        if hit and not hit.startswith(ROW_COUNT_SOURCE_PREFIX):
            r["source"] = f"recomputed: {hit}"
            r["source_kind"] = "shipped-table"
            r["status"] = "proved"
            filled += 1
    return {"filled": filled, "candidates": len(index)}


def citation_mentions(paras: list) -> list:
    """[(para, shape, text, fixable)] for every parenthetical author-year citation.

    shape: "year-journal" | "journal-year" | "year-only". `fixable` is True when
    a journal-carrying mention matches one of the two precise shapes, so its
    redundant journal segment can be deleted mechanically.
    """
    out = []
    for i, text in enumerate(paras):
        for m in CIT_YEAR_JOURNAL.finditer(text):
            out.append((i, "year-journal", m.group(0), True))
        for m in CIT_JOURNAL_YEAR.finditer(text):
            out.append((i, "journal-year", m.group(0), True))
        for m in CIT_YEAR_ONLY.finditer(text):
            out.append((i, "year-only", m.group(0), True))
        # a parenthetical that carries a journal name but matches no shape above
        for m in re.finditer(r"\(([^()]{4,120})\)", text):
            inner = m.group(1)
            if not re.search(r"\b(?:19|20)\d\d", inner) or not journal_matches(inner):
                continue
            if not re.match(CIT_AUTHOR, inner):
                continue                  # not a citation: prose that happens to name
                                          # journals and years ("published in ... 2021")
            if any(t == m.group(0) for _i, _s, t, _f in out):
                continue
            out.append((i, "other", m.group(0), False))
    return out


def citation_format_row(paras: list, field_spans: list = None) -> dict | None:
    """One row when a document mixes citation formats (None when consistent)."""
    mentions = [m for m in citation_mentions(paras) if m[1] != "other"
                or journal_matches(m[2])]
    shapes = {m[1] for m in mentions}
    if len(shapes) < 2 or not any(journal_matches(m[2]) for m in mentions):
        return None
    counts = Counter(m[1] for m in mentions)
    example = "; ".join(sorted({m[2] for m in mentions if m[1] != "year-only"})[:3])
    # A citation inside a live field RESULT is regenerated by Word: the fixer
    # refuses it, so the row must be field-held or the whole repair is rejected.
    held = {i for i, ranges in enumerate(field_spans or []) if ranges}
    unfixable = [m for m in mentions if not m[3] or m[0] in held]
    return {"rule": "FMT-T8a", "severity": "medium",
            "evidence": f"citations mix {len(shapes)} formats: "
                        + ", ".join(f"{s} x{c}" for s, c in sorted(counts.items()))
                        + (f" -- e.g. {example[:90]}" if example else ""),
            "detail": "one citation format per document: the journal name is redundant in "
                      "an author-year citation (the reference list carries it), so the "
                      "dominant form decides (policy citation_journal_names)",
            "protected": bool(unfixable)}


def balanced_paren_groups(text: str) -> list:
    """[(start, end, depth, inner_text)] for balanced ASCII parenthesis groups.

    A plain regex cannot see "(A (B), C (D))": the inner groups are siblings, so
    the pattern's `[^()]*` between them never matches. A depth counter does.
    """
    stack, out = [], []
    for i, ch in enumerate(text):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            start = stack.pop()
            # `end` is EXCLUSIVE: both consumers slice text[start:end] and map
            # fixes with a half-open span, so returning the closing ')' index
            # dropped it from the evidence and from the restyled span.
            out.append((start, i + 1, len(stack), text[start + 1:i]))
    return out


def nested_parentheses_rows(paras: list) -> list:
    """One row per OUTERMOST parenthesis group that contains another group.

    Mathematical calls are excluded (`T(·,·)` has no letters inside), and only
    the outermost group of a cluster is reported, so a list of six nested
    references is one row, not six.
    """
    rows = []
    for i, text in enumerate(paras):
        groups = balanced_paren_groups(text)
        for start, end, _depth, inner in groups:
            children = [g for g in groups if start < g[0] < end]
            if not children:
                continue
            if all(not re.search(r"[A-Za-z]", g[3]) for g in children):
                continue                      # T(.,.) and friends: notation, not style
            if any(other[0] < start < other[1] for other in groups):
                continue                      # report the outermost group only
            rows.append({"rule": "FMT-T8b", "severity": "medium",
                         "evidence": text[start:end][:110],
                         "detail": "parentheses inside parentheses read badly; move the "
                                   "inner item out (comma or em dash) or restructure the "
                                   "sentence", "protected": False})
    return rows


def term_repetition_rows(paras: list, is_ref: list) -> list:
    """Rows for a DISTINCTIVE term repeated many times in one paragraph.

    Deliberately narrow: a technical noun repeating three times in a methods
    paragraph is normal writing, so only (a) a repeated PROPER NAME (2-3
    capitalized words with no document-structure word, used at least four times
    in the document -- a journal name such as "Nature Biotechnology" four times
    in one cover-letter paragraph, whichever venue the pipeline is configured
    for) and (b) a single long content word used five times or more inside
    one paragraph qualify. URLs/e-mails are masked out, the reference list is
    skipped (it repeats names by design), and nothing is ever auto-edited.
    """
    rows = []
    prose = [t for i, t in enumerate(paras) if not (i < len(is_ref) and is_ref[i])]
    blob = "\n".join(URL_RE.sub(" ", t) for t in prose).lower()
    for i, text in enumerate(paras):
        if i < len(is_ref) and is_ref[i]:
            continue
        masked = URL_RE.sub(lambda m: " " * len(m.group(0)), text)
        words = re.findall(r"[A-Za-z][A-Za-z\-']+", masked)
        if len(words) > 300 or len(words) < 40:
            continue                          # not a short passage
        low = [w.lower() for w in words]
        hits = {}
        for n in (2, 3):
            for j in range(len(low) - n + 1):
                if not all(w[:1].isupper() for w in words[j:j + n]):
                    continue                  # proper names only
                gram = " ".join(low[j:j + n])
                if any(w in REPETITION_STOPWORDS for w in gram.split()):
                    continue
                hits[gram] = hits.get(gram, 0) + 1
        for w in sorted(set(low)):
            if len(w) >= 8 and w not in REPETITION_STOPWORDS:
                hits[w] = low.count(w)
        for term, count in sorted(hits.items(), key=lambda kv: (-kv[1], -len(kv[0])))[:3]:
            if len(term.split()) >= 2:
                if count < 3 or len(re.findall(rf"\b{re.escape(term)}", blob)) < 4:
                    continue                  # a one-off list of names, not redundancy
            elif count < 5:
                continue
            rows.append({"rule": "FMT-T8c", "severity": "medium",
                         "evidence": f"{term!r} appears {count}x in one paragraph "
                                     f"({len(words)} words)",
                         "detail": "redundancy in a short passage: name the thing once and "
                                   "refer back to it (pronoun, ellipsis, or the short form); "
                                   "a proper name three or more times in one paragraph (and "
                                   "four or more times in the document) -- a journal name "
                                   "above all -- reads as padding, and it is a "
                                   "writing-quality defect even when no journal rule names it",
                         "protected": False})
    return rows


def variant_rows(paras: list, is_ref: list, field_spans: list = None) -> list:
    """FMT-T8d (US/UK spelling) and FMT-T8e (attributive hyphenation).

    `field_spans` (per-paragraph live-field result ranges) marks a row whose
    offending occurrence the fixer is forbidden to edit: the row is reported
    as field-held rather than mechanical, so the fixer's self-verification does
    not demand an edit it must refuse.
    """
    rows = []
    prose = [(i, t) for i, t in enumerate(paras)
             if not (i < len(is_ref) and is_ref[i])]

    def field_held(i, start, end) -> bool:
        if not field_spans or i >= len(field_spans):
            return False
        spans = field_spans[i]
        return bool(spans) and in_field_result(spans, start, end)

    targets = spelling_minority_targets([t for _i, t in prose])
    for a, b in SPELLING_PAIRS:
        # Count on the SAME prose the target set and the fixer read: a URL or
        # code span keeps its own spelling, so its occurrence must not make the
        # pair look mixed and file a mechanical row the fixer cannot repair.
        ca = sum(len(re.findall(rf"\b{re.escape(a)}\b", spelling_nonprose_mask(t), re.I))
                 for _i, t in prose)
        cb = sum(len(re.findall(rf"\b{re.escape(b)}\b", spelling_nonprose_mask(t), re.I))
                 for _i, t in prose)
        if ca and cb:
            target = targets.get(a) or targets.get(b) or ""
            minority = (a if target == b else b) if target else ""
            held = False
            if minority:
                held = any(
                    field_held(i, m.start(), m.end())
                    for i, t in prose
                    for m in re.finditer(rf"\b{re.escape(minority)}\b", t, re.I))
            rows.append({"rule": "FMT-T8d", "severity": "medium",
                         "evidence": f"spelling variants in body text: {a!r} x{ca} and "
                                     f"{b!r} x{cb}"
                                     + (f" (tie; the first occurrence wins: {target!r})"
                                        if ca == cb and target else ""),
                         "detail": "one spelling per submission (policy "
                                   "term_spelling='dominant' normalizes the minority form "
                                   "outside the reference list)", "protected": held})
    for hy, split in HYPHEN_COMPOUNDS:
        # Count only ATTRIBUTIVE uses. "the copy number of a locus" and "each
        # single cell expressed" are the documented noun uses and must not make
        # the scanner demand a fix the fixer (correctly) refuses to apply.
        split_re = hyphen_attributive_re(split)
        attr_split = sum(len(split_re.findall(t)) for _i, t in prose)
        attr_hy = sum(len(hyphen_attributive_re(hy).findall(t)) for _i, t in prose)
        if attr_split and attr_hy:
            # The fixer rewrites the open form; an open-form occurrence it must
            # leave inside a field result keeps this rule alive, so the row is
            # field-held rather than mechanical.
            held = any(field_held(i, m.start(), m.end())
                       for i, t in prose for m in split_re.finditer(t))
            rows.append({"rule": "FMT-T8e", "severity": "low",
                         "evidence": f"attributive {hy!r} x{attr_hy} vs {split!r} "
                                     f"x{attr_split} before a noun",
                         "detail": "a compound modifier is hyphenated when it precedes the "
                                   "noun (policy term_hyphenation='dominant' hyphenates the "
                                   "minority attributive form)", "protected": held})
    return rows


def text_style_rows(paras: list, is_ref: list = None, headings: list = None,
                    in_container: list = None, in_area: list = None,
                    field_spans: list = None) -> list:
    """All FMT-T8/T9 rows for a document's paragraphs.

    Every row carries `tier` (see FINDING_TIER_RULES): finding-tier rows must be
    decided against their own bar, advisory rows are recorded and disposed.
    `field_spans` is the per-paragraph live-field result ranges (the same
    `field_result_text_ranges` the fixer fences edits with): a spelling or
    hyphenation occurrence the fixer may not touch must make its row
    field-held, never mechanical.
    """
    is_ref = list(is_ref or [False] * len(paras))
    prose = [t for i, t in enumerate(paras) if not (i < len(is_ref) and is_ref[i])]
    rows = []
    cit = citation_format_row(paras, field_spans=field_spans)
    if cit:
        rows.append(cit)
    rows += nested_parentheses_rows(paras)
    rows += term_repetition_rows(paras, is_ref)
    rows += variant_rows(paras, is_ref, field_spans=field_spans)
    rows += long_text_rows(paras, is_ref, section_kinds(paras, headings),
                           headings=headings, in_container=in_container,
                           in_area=in_area)
    rows += self_gloss_rows(paras, is_ref)
    rows += confusable_pair_rows(prose)
    rows += concept_family_rows(paras, is_ref)
    rows += number_format_rows(prose)
    # Argument-level and cross-claim checks (2026-10-19). They read the prose as
    # an argument, not as isolated sentences: the round-2 winners satisfied every
    # sentence-local rule while shipping a premise asserted as its own test, an
    # expectation offered as evidence, a count that did not match its list, and a
    # legend that argued the paper's conclusion.
    rows += logic_rows(paras, is_ref)
    rows += count_claim_rows(prose)
    rows += stats_floor_rows(prose)
    rows += legend_claim_rows(prose)
    # FMT-G4: comma-glued list items. The DOCX path reaches this through
    # `hygiene_rows`; text sources (.tex, .md, .bib) have no OOXML hygiene pass,
    # and the 2026-10-15 CNB package carried this defect in BOTH -- the
    # Reporting Summary's rendered version list and the supplementary .bib's
    # keyword lists -- with no row anywhere in the root.
    for i, t in enumerate(paras):
        if i < len(is_ref) and is_ref[i]:
            continue
        for r in comma_glue_rows(t):
            rows.append({"rule": r["rule"], "severity": r["severity"],
                         "evidence": r["evidence"], "detail": r["detail"]})
    for r in rows:
        r.setdefault("tier", tier_of(r.get("rule") or ""))
    return rows


def outline_rows(paras: list, headings: list = None, doc: str = "") -> list:
    """Hierarchical outline rows (document -> heading -> paragraph).

    The "summaries at each level" workflow needs a scaffold to hang the
    summaries on: one row per paragraph with its heading context, word count,
    first/last sentence, list markers and figure/table references. The agent
    fills the `summary` column and checks sibling/parent/child coherence.
    """
    headings = list(headings or [False] * len(paras))
    rows, current = [], ""
    for i, text in enumerate(paras):
        if i < len(headings) and headings[i]:
            current = text.strip()[:120]
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        rows.append({"heading": current or "(front matter)", "paragraph": i,
                     "words": len(text.split()),
                     "list_markers": ",".join(re.findall(r"\((\d)\)", text)) or "",
                     "refs": ",".join(sorted(set(re.findall(
                         r"(?:Fig\.|Figure|Table|Supplementary (?:Fig\.|Table|Note))"
                         r"\s*[A-Z]?\d+[a-z]?", text)))[:6]),
                     "first_sentence": (sentences[0][:120] if sentences else ""),
                     "last_sentence": (sentences[-1][:120] if sentences else ""),
                     "summary": ""})
    return rows

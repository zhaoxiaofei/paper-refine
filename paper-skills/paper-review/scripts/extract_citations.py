#!/usr/bin/env python3
r"""extract_citations.py — M2 citation ↔ reference-list sweep.

Enumerates every in-text citation call-out (numeric [1] / [1,2] / [1-3] and
author-year "(Smith et al., 2019)", "Smith et al. (2019)", "Smith and Jones
2019"), every LaTeX `\cite`-family key and every reference-list entry
(numbered, unnumbered, `\bibitem` and `.bib`), then compares them. One row per
reference entry AND per call-out occurrence in the artifact:

  OUT/artifacts/M2_citations.md / .json

Checks derivable from the artifact: cited-but-not-listed (orphan call-out),
listed-but-never-cited (uncited entry), duplicate entries within one list,
misordered numeric call-outs within one document, and suspect/nonexistent
reference candidates (flag, never guess).

Each file that carries its own numbered list is its own numbering space:
orphans, uncited entries, duplicates and order violations are computed per
document, never merged across documents (a cover letter citing [5] while the
manuscript starts at [1] is not an ordering defect).

LaTeX sources (`*.tex.txt`/`*.ltx.txt` in the corpus) cite by KEY, so the key
space of `\cite{a,b}` / `\citep[see][p. 3]{a}` is compared against this
document's own `\bibitem{a}` entries and the package's `.bib` entries; a
`\nocite{a}` counts as cited without being an in-text call-out. `%` comments
and verbatim bodies never contribute a key. When the corpus carries `\cite`
call-outs but no key list at all, the artifact says the check is UNRESOLVED
instead of printing an empty "orphans: none" (the reference list is simply not
in the corpus).

stdlib-only. Usage:
  python extract_citations.py --work ./review/work [--out ./review]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

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
# The supplement role is a WORD too: the old `"supp" in f` swept `support.docx`
# and `suppress.md` as supplementary text, exactly the files the pipeline keeps
# as main text. `supp`, `suppl`, `supplement*` and `supplementary` still match.
SUPP_ROLE_RE = re.compile(
    r"(?<![a-z])supp(?:l(?:ement\w*)?|lement\w*)?(?![a-z])"
    r"|extended_?data|appendix", re.I)
# The reference-role file names: "ref", "refs", "references", "ref-list",
# "cnb-26-4-refs" -- the SAME word-boundary rule convert_corpus.py's role
# guesser uses. Deliberately not a bare "ref" PREFIX: `refined_draft.txt` and
# `refresh_log.txt` are not bibliographies.
REF_ROLE_RE = re.compile(r"\brefs?\b|\breferences?\b")


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
        # A cover letter IS a submission document -- and this test must come
        # FIRST: with the reply test above it, `cover_letter_response.docx.txt`
        # was dropped as non-manuscript even though the cover-letter rule (and
        # the M19 length sweep) treats a letter as the authors' own submission
        # text.
        return False
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


# The OOXML marker parser accepts an en/em dash as a range separator; an em
# dash citation was invisible to this sweep and fabricated orphan rows.
NUM_CIT_RE = re.compile(r"\[(\d{1,4}(?:\s*[,;–—-]\s*\d{1,4})*)\]")
AY_CIT_RE = re.compile(
    r"(?P<a1>[A-Z][A-Za-z'\-]+)\s+et al\.?\s*,?\s*\(?(?P<y1>(?:1[5-9]|20)\d{2}[a-z]?)\)?"
    r"|(?P<a2>[A-Z][A-Za-z'\-]+)\s+(?:and|&)\s+(?P<a2b>[A-Z][A-Za-z'\-]+)\s*,?\s*"
    r"\(?(?P<y2>(?:1[5-9]|20)\d{2}[a-z]?)\)?"
    r"|\((?P<a3>[A-Z][A-Za-z'\-]+)(?:\s+(?:et al\.?|and|&)\s+[A-Z][A-Za-z'\-]+)?\s*,\s*"
    r"(?P<y3>(?:1[5-9]|20)\d{2}[a-z]?)\)"
    r"|(?P<a4>[A-Z][A-Za-z'\-]+)\s+\((?P<y4>(?:1[5-9]|20)\d{2}[a-z]?)\)")
# a bracketed number right after these words is a measurement interval, not a citation
SUSPECT_PRECEDERS = re.compile(
    r"(?:interval|range|between|cut-?off|threshold|score|coordinate|temperature|"
    r"duration|period|dose|concentration|voltage|pressure|radius|band|window|"
    r"percentile|quartile|value|level|age|cycle|time|hour|day|week|month|year|"
    r"size|length|width|volume|mass|weight|height|area|depth|distance|speed|"
    r"unit|replicate|ratio|fold|bound|limit|baseline|score)s?"
    r"\s*(?:of|is|was|:|=|are|were)?\s*$", re.I)
# The closing parenthesis is a numbering style several journals use, and the
# call-out pattern two pages below already accepts it (NUM_ENTRY_RE's
# `[\].)]`). Without it a `1) Smith J. Nature 2019.` list parsed to ZERO
# entries, so the orphan/uncited/duplicate checks silently fell back to the
# cross-file union and the M2 inventory was wrong for that style.
# A bracket may be omitted, and a following non-digit may be glued to the
# number ("[1]Smith"); a DIGIT after the separator is a decimal, not a new
# entry ("12.5 mg was given" is not reference 12).
REF_ENTRY_RE = re.compile(r"^\s*\[?(\d{1,4})[\].)](?!\d)\s*(.*)$")
BIB_ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,]+),")
# LaTeX: the call-out is a KEY inside a \cite-family macro (`\cite`, `\citep`,
# `\citet`, `\citealp`, `\textcite`, `\parencite`, `\autocite`, `\nocite`, ...),
# the list entry is a `\bibitem[...]{key}`. Without these, a .tex submission
# reported zero call-outs and a clean "orphans: none" for a document that cites
# every sentence.
# Only real citation macros. A bare `*cite*` name also matched `\citestyle`
# and `\citetext`, inventing call-outs whose key was a style name or text.
TEX_CITE_RE = re.compile(
    r"\\(?P<macro>(?i:cite|citep|citet|citealt|citealp|citeauthor|citeyear|"
    r"citeyearpar|citenum|citeurl|nocite|textcite|parencite|autocite|"
    r"footcite|footfullcite|smartcite|supercite|fullcite|notecite|citeA|citeN))\*?"
    r"(?:\s*\[[^\]]*\]){0,3}\s*\{(?P<keys>[^{}]*)\}")
TEX_BIBITEM_RE = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{(?P<key>[^{}]+)\}")
TEX_BEGIN_VERBATIM_RE = re.compile(r"\\begin\{(?P<env>verbatim|lstlisting|minted|Verbatim)\}")


def strip_tex_comment(line: str) -> str:
    """`line` up to its first unescaped `%` (the escape pair kept)."""
    out, i = [], 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            out.append(line[i:i + 2])
            i += 2
            continue
        if line[i] == "%":
            break
        out.append(line[i])
        i += 1
    return "".join(out)


def latex_source_text(text: str) -> str:
    """The compilable part of a LaTeX source (line count preserved).

    A `%` comment (any unescaped `%` to the end of the line) and a verbatim
    body are not manuscript text: a commented-out `\\cite{old}` must not enter
    the key space and a verbatim sample must not become an orphan call-out.
    Every line is replaced in place, so the reported line numbers stay the
    source's own.
    """
    kept, in_verbatim = [], None
    for line in text.split("\n"):
        if in_verbatim is not None:
            if ("\\end{%s}" % in_verbatim) in line:
                in_verbatim = None
            kept.append("")
            continue
        # Strip the comment BEFORE looking for the environment fence: a
        # commented-out `% \begin{verbatim}` used to blank the rest of the file.
        line = strip_tex_comment(line)
        m = TEX_BEGIN_VERBATIM_RE.search(line)
        if m:
            # A one-line `\begin{verbatim}...\end{verbatim}` closes on the
            # SAME line; leaving the scanner in verbatim mode dropped every
            # citation after it until a later end marker.
            end = re.search(r"\\end\{" + re.escape(m.group("env")) + r"\}",
                            line[m.end():])
            if end:
                kept.append(line[: m.start()] + line[m.end() + end.end():])
            else:
                in_verbatim = m.group("env")
                kept.append(line[: m.start()])
            continue
        kept.append(line)
    return "\n".join(kept)

REF_HEAD_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*[.)]?\s*)?"
    r"(?:references?|bibliography|reference\s+list|literature\s+cited)\s*:?\s*$", re.I)
STOP_SECTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s+)?(?:\d+(?:\.\d+)*[.)]?\s*)?"
    r"(?:figure\s+legends?|figures?|table\s+legends?|tables?|"
    r"supplementary(?:\s+\w+)?|extended\s+data(?:\s+\w+)?|methods?|materials\s+and\s+methods|"
    r"experimental\s+procedures|results?|discussion|conclusions?|introduction|background|"
    r"abstract|acknowledge?ments?|author\s+contributions?|competing\s+interests?|"
    r"conflicts?\s+of\s+interest|data\s+availability|code\s+availability|funding|"
    r"ethics(?:\s+statement)?|appendix|list\s+of\s+(?:figures|tables))\s*:?\s*$", re.I)
MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
# captions carry a separator after the label; "Fig. 1 shows …" is prose
CAP_SEP = r"[.:|–—,](?:\s*\S|\s*$)"
FIG_CAPTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:extended\s+data|supplementary\s+)?fig(?:ure)?s?\.?\s*"
    r"(?:s\d+|\d+[a-z]?)\s*" + CAP_SEP, re.I)
TABLE_CAPTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:extended\s+data|supplementary\s+)?tables?\.?\s*"
    r"(?:s\d+|\d+[a-z]?)\s*" + CAP_SEP, re.I)
NUM_ENTRY_RE = re.compile(r"^\s*(?:\[?\d{1,3}[\].)]|\d{1,3}[.)])\s+")
BULLET_ENTRY_RE = re.compile(r"^\s*[-*•]\s+\S")
YEAR_RE = re.compile(r"\b(?:1[5-9]|20)\d{2}[a-z]?\b")
ENTRY_HINT_RE = re.compile(
    r"(\bdoi\b|https?://|arxiv|biorxiv|medrxiv|preprint|\bet al\.?\b|\bpp?\.\s*\d+)", re.I)
AUTHOR_START_RE = re.compile(r"^\s*[A-Z][A-Za-z'\-]+,\s*(?:[A-Z]\.|[A-Z][a-z]+)")
# tail of a wrapped entry: "Nature. 2019;570:1-9." / "Science 2020;11:20-30."
JOURNAL_TAIL_RE = re.compile(r"^[A-Z][A-Za-z&.\s]{2,40}[.,;:]?\s*\(?(?:19|20)\d{2}\b")


# A reference entry's author block: "Smith J.", "Smith JA,", "Smith, J.".
# A bare capitalised word is not enough -- "In 2020 ..." starts a sentence too.
_ENTRY_AUTHOR_RE = re.compile(
    r"^\s*[A-Z][A-Za-z'\-]+(?:\s+[A-Z]{1,3}[,.]|\s+[A-Z]\.|\s*,\s*(?:[A-Z]\.|[A-Z][a-z]+))")


def looks_like_reference_entry(s):
    if NUM_ENTRY_RE.match(s) or BULLET_ENTRY_RE.match(s):
        return True
    # A year or "et al." alone is ordinary prose ("In 2020 we reanalysed ...",
    # "Smith et al. showed ..."). A reference entry also has an author-name
    # start, a volume:page marker, a DOI, or an organisation-author shape.
    if _ENTRY_AUTHOR_RE.match(s) or AUTHOR_START_RE.match(s):
        return True
    if re.search(r"\bdoi\b|https?://", s, re.I):
        return True
    if YEAR_RE.search(s) and re.search(r"\b\d+\s*[:(]\s*\d+", s):
        return True
    if re.match(r"^\s*(?:[A-Z][\w'’\-&.]+\s+){2,}\(?(?:19|20)\d{2}\)?\s*[.;:,)]", s):
        return True
    return False


def classify_context(fname):
    """Role of a corpus file, derived from its name (falls back to main text)."""
    raw = os.path.basename(fname).lower()
    f = re.sub(r"\.(?:txt|md)$", "", raw)
    f = re.sub(r"\.[a-z0-9]{1,5}$", "", f)
    # The WORD "cover" (or the camelCase "coverLetter"), never the substring: the bare
    # test named `discovery.md`, `coverage_table.txt` and `recovered_samples.md` a cover
    # letter and a "reply" name that merely contains "cover" was masked (see
    # `_COVER_WORD_RE`, which `is_evidence_name` already uses).
    if _COVER_WORD_RE.search(f): return "cover letter"
    toks = set(re.findall(r"[a-z0-9]+", f))
    if "title" in toks: return "title page"
    # "ref"/"refs"/"references"/"ref-list" name a bibliography; a word that
    # merely STARTS with those letters does not. `(^|[^a-z])ref` matched
    # "refined_draft.txt" and "refresh_log.txt", and a "references"-role file
    # with no heading is consumed as the reference region below -- so such a
    # file's in-text call-outs were never counted and its prose was read as
    # entries.
    if REF_ROLE_RE.search(f) or "bibliograph" in f or re.search(r"\.bib(\.|$)", raw):
        return "references"
    if "abstract" in toks or "abstracts" in toks: return "abstract"
    if SUPP_ROLE_RE.search(f): return "supplementary"
    if "m&m" in f or any(t.startswith("method") for t in toks): return "Methods"
    if any(t.startswith(("fig", "legend")) for t in toks): return "figure legend"
    if any(t.startswith("table") for t in toks): return "table"
    if any(t.startswith(("reporting", "summary")) for t in toks):
        return "reporting summary"
    return "main text"


def find_reference_region(lines):
    """(start, end, note) line indices of the reference list, or None.

    The region ends at the next heading/caption, or — when the list is followed
    by a plain paragraph with no heading — at the first paragraph that does not
    look like a reference entry. The note is printed in the artifact so the
    boundary is never a silent cut.
    """
    start = None
    for i, ln in enumerate(lines):
        if REF_HEAD_RE.match(ln.strip()):
            # The LAST heading is the real list: an early "References" line
            # (table of contents, or a superseded first list) must not latch
            # the sweep onto the wrong section.
            start = i + 1
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


# Calendar month names are never author surnames. The TWO-AUTHOR branch needs no
# parentheses, so ordinary date prose ("between January and February 2019") was
# read as an author-year call-out and every cover letter / Methods section fed
# the M2 inventory phantom rows that a human then audits by hand. Only a pair
# where BOTH tokens are months is rejected: "May and Smith 2019" is a citation.
MONTH_NAMES = frozenset((
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec").split())


_NON_AUTHOR_WORDS = frozenset((
    "results discussion methods introduction background conclusion conclusions "
    "table tables figure figures supplementary appendix section chapter see "
    "this these those the a an in on at by for from with and or").split())


def is_date_prose(m) -> bool:
    """True when an author-year match is prose, not a real call-out."""
    if m.group("a1") or m.group("a3") or m.group("a4"):
        # The "X et al., YYYY" and "(X, YYYY)" branches carry their own anchors; a
        # month CAN be a surname there ("(May, 2019)").
        return False
    names = [m.group("a2"), m.group("a2b")]
    if not (names[0] and names[1]):
        return True
    if names[0].lower() in MONTH_NAMES and names[1].lower() in MONTH_NAMES:
        return True
    # "See Results and Discussion 2020" / "DNA and RNA 2020" have the same
    # capitalised-pair shape as "Smith and Jones 2020" but are not call-outs.
    if any(n.lower() in _NON_AUTHOR_WORDS for n in names):
        return True
    if all(len(n) > 1 and n.isupper() for n in names):
        return True
    return False


def ay_callout(m):
    """Normalise an author-year match into (raw, author string, year)."""
    if m.group("y1"):
        return m.group(0), m.group("a1"), m.group("y1")
    if m.group("y2"):
        return m.group(0), "%s and %s" % (m.group("a2"), m.group("a2b")), m.group("y2")
    if m.group("y4"):
        return m.group(0), m.group("a4"), m.group("y4")
    return m.group(0), m.group("a3"), m.group("y3")


def parse_nums(inner):
    nums = []
    for part in re.split(r"[,;]", inner):
        part = part.strip()
        # The formatter's `_marker_range_numbers` accepts en dash, EM dash and
        # hyphen. Omitting the em dash made "[12—14]" fall through to int(),
        # store the raw string, and report 12-14 as listed-but-never-cited.
        rm = re.match(r"(\d+)\s*[\u2013\u2014-]\s*(\d+)$", part)
        if rm:
            a, b = int(rm.group(1)), int(rm.group(2))
            # The cap is the OOXML twin's own constant
            # (paper_docx_format._MARKER_RANGE_MAX) and the two must agree: this
            # file expanded a range of 81-200 into all 120 numbers while the
            # twin kept the two endpoints, so the same cluster read differently
            # on the two sides.
            if 0 < b - a <= 80:
                nums.extend(range(a, b + 1))
            else:
                # A range the parser will not expand -- longer than this review's
                # cap, or written backwards -- still NAMES its two endpoints.
                # Storing the raw string meant every later check (which keeps
                # only ints) treated the call-out as citing nothing: no orphan,
                # no order violation, and every entry of a `[1-250]` review
                # looked "listed but never cited". The OOXML twin
                # (`paper_docx_format._marker_range_numbers`) keeps the endpoints
                # for exactly this reason.
                nums.extend(sorted({a, b}))
        elif part:
            try:
                nums.append(int(part))
            except ValueError:
                nums.append(part)
    return nums


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    work = os.path.abspath(args.work)
    out = os.path.abspath(args.out) if args.out else os.path.dirname(work.rstrip("/"))
    corpus = os.path.join(work, "corpus")
    art_dir = os.path.join(out, "artifacts")
    os.makedirs(art_dir, exist_ok=True)
    if not os.path.isdir(corpus):
        print("ERROR: corpus dir not found: %s. Run convert_corpus.py first." % corpus)
        sys.exit(2)

    callouts = []       # every in-text citation instance
    ref_entries = []    # every reference-list entry
    bib_entries = []    # .bib entries
    tex_bibitems = []   # LaTeX \bibitem entries (the document's own list)
    nocite_keys = defaultdict(list)   # \nocite{a}: cited, but not an in-text call-out
    nocite_all_files = set()          # \nocite{*}: the WHOLE list is cited
    suspect_brackets = []
    reference_notes = []

    for fname in sorted(os.listdir(corpus)):
        if not fname.endswith(".txt"):
            continue
        if is_non_manuscript(fname):
            continue  # a letter or a data table carries no manuscript citations
        try:
            text = open(os.path.join(corpus, fname), encoding="utf-8",
                        errors="replace").read()
        except OSError as e:
            print("WARNING: file-unreadable: %s: %s" % (fname, e), file=sys.stderr)
            continue
        lines = text.split("\n")
        # Call-outs are read from the compilable text (LaTeX comments and
        # verbatim bodies removed) while reference-list entries keep the
        # source lines. Without this a commented-out `% see [7]` became a
        # numeric call-out and an orphan.
        callout_lines = (latex_source_text(text).split("\n")
                         if fname.endswith((".tex.txt", ".ltx.txt")) else lines)
        if fname.endswith(".bib.txt"):
            for m in BIB_ENTRY_RE.finditer(text):
                bib_entries.append({"file": fname, "key": m.group(1).strip()})
            continue
        is_latex = fname.endswith((".tex.txt", ".ltx.txt"))
        if is_latex:
            for li, pline in enumerate(latex_source_text(text).split("\n"), 1):
                for m in TEX_CITE_RE.finditer(pline):
                    keys = [k.strip() for k in m.group("keys").split(",") if k.strip()]
                    if m.group("macro").lower() == "nocite" and "*" in keys:
                        # `\nocite{*}` has no key to record: every entry of the
                        # document's list is cited, which the key space below
                        # turns into "cited" for this file (before this, the
                        # star was dropped and EVERY \bibitem was reported as
                        # listed-but-never-cited).
                        nocite_all_files.add(fname)
                    keys = [k for k in keys if k != "*"]   # \nocite{*} = the whole list
                    if m.group("macro").lower() == "nocite":
                        nocite_keys[fname].extend(keys)
                        continue
                    for key in keys:
                        # one row per KEY, so "every call-out on one row" holds for
                        # `\cite{a,b}` too; the numeric/author-year bookkeeping below
                        # ignores the string `refs` (only ints enter a number space)
                        callouts.append({"file": fname, "line": li, "raw": m.group(0)[:120],
                                         "refs": [key], "excerpt": pline.strip()[:120],
                                         "style": "latex-key", "key": key,
                                         "macro": m.group("macro")})
                for m in TEX_BIBITEM_RE.finditer(pline):
                    tex_bibitems.append({"file": fname, "line": li,
                                         "key": m.group("key").strip(),
                                         "text": pline.strip()[:200]})

        region = find_reference_region(lines)
        if region is None and classify_context(fname) == "references":
            # Exporters often put the reference list in its own file and drop
            # the "References" heading. Without a region the whole list is
            # swept as prose, every numbered entry is read as a call-out, and
            # the real citations are reported as orphans.
            first = next((i for i, ln in enumerate(lines)
                          if looks_like_reference_entry(ln.strip())), 0)
            region = (first, len(lines), "reference-role file (no heading)")
        prev_line = ""
        if region:
            reference_notes.append("%s lines %d-%d (%s)" % (
                fname, region[0] + 1, region[1], region[2]))
        for li, raw in enumerate(lines, 1):
            in_refs = bool(region and region[0] <= li - 1 < region[1])
            if in_refs:
                em = REF_ENTRY_RE.match(raw)
                if em:
                    ref_entries.append({"file": fname, "line": li, "num": int(em.group(1)),
                                        "text": em.group(2).strip()[:200]})
                elif raw.strip():
                    s = raw.strip()
                    prev = ref_entries[-1] if ref_entries else None
                    if prev and prev["file"] == fname and prev_line.strip() and \
                            (s[:1].islower() or JOURNAL_TAIL_RE.match(s)):
                        prev["text"] = (prev["text"] + " " + s)[:300]  # wrapped entry
                    else:
                        ref_entries.append({"file": fname, "line": li, "num": None,
                                            "text": s[:200]})
                prev_line = raw
                continue
            prev_line = raw
            scan_raw = callout_lines[li - 1] if li - 1 < len(callout_lines) else raw
            for m in NUM_CIT_RE.finditer(scan_raw):
                before = scan_raw[:m.start()].rstrip()
                suspect = bool(SUSPECT_PRECEDERS.search(before))
                inner = m.group(1)
                # An interval SHAPE after a measurement word ("in the interval
                # [2, 5]", "CI [1.2-3.4]") is a measurement interval, not a
                # call-out: counting it fabricated order violations and orphan
                # numbers (C10/C24 in the skill harness pin exactly that).
                interval_shape = bool(re.search(r"[,;]", inner)
                                      or re.search(r"\d\s*[\u2013\u2014-]\s*\d", inner))
                if suspect and interval_shape:
                    suspect_brackets.append({"file": fname, "line": li, "raw": m.group(0),
                                             "excerpt": scan_raw.strip()[:120],
                                             "why": "bracketed range after a measurement word"})
                    continue
                if suspect:
                    # A SINGLE bracketed number after one of the generic
                    # measurement words (level, value, age, time, size...) is a
                    # real call-out candidate: dropping it removed the reference
                    # from the cited set entirely, so the sweep could assert
                    # "reference 12 is listed but never cited" -- a false finding.
                    # It IS counted, and still recorded here (and flagged
                    # `suspect` in the call-out) for the human to check.
                    suspect_brackets.append({"file": fname, "line": li, "raw": m.group(0),
                                             "excerpt": scan_raw.strip()[:120],
                                             "why": "single bracketed number after a "
                                                    "measurement word (counted; verify)"})
                callouts.append({"file": fname, "line": li, "raw": m.group(0),
                                 "refs": parse_nums(inner),
                                 "excerpt": scan_raw.strip()[:120], "style": "numeric",
                                 "suspect": suspect})
            for m in AY_CIT_RE.finditer(scan_raw):
                if is_date_prose(m):
                    continue
                raw_cit, author, year = ay_callout(m)
                callouts.append({"file": fname, "line": li, "raw": raw_cit,
                                 "refs": ["%s %s" % (author, year)],
                                 "excerpt": scan_raw.strip()[:120], "style": "author-year"})

    # ---- per-document bookkeeping (each numbered list is its own space)
    lists_by_file = defaultdict(list)
    for e in ref_entries:
        if e["num"] is not None:
            lists_by_file[e["file"]].append(e["num"])
    all_listed = {n for nums in lists_by_file.values() for n in nums}
    # A bracketed publication year or year range ("[2015-2020]") is prose, not a
    # numeric call-out. NUM_CIT_RE accepts four digits for reference numbers
    # >999; without this guard every bracketed year became a phantom citation
    # (six orphan call-outs, an order violation, and an inflated max_cited). A
    # year-shaped number that IS in this document's reference list is a real
    # call-out and is kept.
    kept_callouts = []
    for c in callouts:
        if c.get("style") == "numeric":
            space = (set(lists_by_file[c["file"]]) if c["file"] in lists_by_file
                     else all_listed)
            kept = [r for r in c["refs"]
                    if not (isinstance(r, int) and 1900 <= r <= 2099 and r not in space)]
            if not kept:
                continue
            c["refs"] = kept
        kept_callouts.append(c)
    callouts = kept_callouts
    cited_by_file = defaultdict(list)
    for c in callouts:
        for r in c["refs"]:
            if isinstance(r, int):
                cited_by_file[c["file"]].append(r)
    all_cited = {n for nums in cited_by_file.values() for n in nums}

    orphan_callouts_by_file = {}
    for f, nums in cited_by_file.items():
        space = set(lists_by_file[f]) if f in lists_by_file else all_listed
        orphans = sorted({n for n in nums if n not in space})
        if orphans:
            orphan_callouts_by_file[f] = orphans
    orphan_callouts = sorted({n for nums in orphan_callouts_by_file.values() for n in nums})

    uncited_by_list = {}
    for f, nums in lists_by_file.items():
        # Per-document numbering space, mirroring the orphan check above: a
        # call-out in another document (cover letter, supplement) must not mask
        # an uncited entry of THIS document's list.
        space = set(cited_by_file[f]) if f in cited_by_file else all_cited
        uncited = sorted({n for n in nums if n not in space})
        if uncited:
            uncited_by_list[f] = uncited
    uncited_entries = sorted({n for nums in uncited_by_list.values() for n in nums})

    # ---- LaTeX key space (a .tex cites by KEY; the list is \bibitem or a .bib)
    tex_callouts = [c for c in callouts if c.get("style") == "latex-key"]
    tex_key_space = {b["key"] for b in tex_bibitems} | {b["key"] for b in bib_entries}
    tex_cited_by_file = defaultdict(list)
    for c in tex_callouts:
        tex_cited_by_file[c["file"]].append(c["key"])
    for f, keys in nocite_keys.items():
        tex_cited_by_file[f].extend(keys)
    for f in sorted(nocite_all_files):
        tex_cited_by_file[f].extend(b["key"] for b in tex_bibitems if b["file"] == f)
        tex_cited_by_file[f].extend(b["key"] for b in bib_entries if b["file"] == f)
    all_tex_cited = {k for keys in tex_cited_by_file.values() for k in keys}
    tex_orphans_by_file = {}
    if tex_key_space:
        for f, keys in tex_cited_by_file.items():
            orphans = sorted({k for k in keys if k not in tex_key_space})
            if orphans:
                tex_orphans_by_file[f] = orphans
    tex_orphans = sorted({k for keys in tex_orphans_by_file.values() for k in keys})
    tex_uncited = sorted({b["key"] for b in tex_bibitems} - all_tex_cited)
    # \cite keys with no list in the corpus at all: the reference list was not
    # submitted, so the orphan/uncited checks cannot run. That is `unable`,
    # never an empty "none".
    tex_unresolved = bool(tex_callouts) and not tex_key_space

    duplicate_entries = {}
    for f, nums in lists_by_file.items():
        dupes = {n: c for n, c in Counter(nums).items() if c > 1}
        if dupes:
            duplicate_entries[f] = dupes

    order_violations = []
    # Numeric styles number a reference at its FIRST call-out: a later call-out
    # that repeats an already-cited number is normal and must not be reported
    # ("[1], [2], then [1] again" was a guaranteed false order violation).
    # Only a NEW number that arrives below the highest one already introduced
    # is out of order.
    max_by_file = defaultdict(int)
    seen_by_file = defaultdict(set)
    for c in callouts:
        for r in c["refs"]:
            if isinstance(r, int) and r not in seen_by_file[c["file"]]:
                prev = max_by_file[c["file"]]
                if r < prev:
                    order_violations.append({"file": c["file"], "line": c["line"],
                                             "raw": c["raw"],
                                             "issue": "citation %d after %d" % (r, prev)})
                seen_by_file[c["file"]].add(r)
                max_by_file[c["file"]] = max(prev, r)

    max_cited = max(all_cited) if all_cited else 0
    md = ["# M2 — CITATION INVENTORY (artifact)", "",
          "Reference-list regions read (boundary is explicit, never silent):",
          ] + (["- " + n for n in reference_notes] or ["- none"]) + [
          "",
          "## Reference-list entries (%d)" % len(ref_entries), "",
          "| # | file | line | entry (truncated) |", "|---|---|---|---|"]
    for e in ref_entries:
        md.append("| %s | %s | %d | %s |" % (e["num"] if e["num"] is not None else "—",
                                             e["file"], e["line"],
                                             e["text"].replace("|", "\\|")))
    md += ["", "## In-text call-outs (%d)" % len(callouts), "",
           "| file | line | call-out | refs | excerpt |", "|---|---|---|---|---|"]
    for c in callouts:
        md.append("| %s | %d | %s | %s | %s |" % (
            c["file"], c["line"], c["raw"].replace("|", "\\|"),
            ", ".join(str(r) for r in c["refs"]), c["excerpt"].replace("|", "\\|")))
    md += ["", "## Bibliography-file entries (%d)" % len(bib_entries), ""]
    for b in bib_entries:
        md.append("- %s :: %s" % (b["file"], b["key"]))
    if tex_callouts or tex_bibitems:
        md += ["", "## LaTeX key space (%d call-out key(s), %d \\bibitem entr(y|ies))" % (
            len(tex_callouts), len(tex_bibitems)), ""]
        for c in tex_callouts:
            md.append("- `\\%s{%s}` at %s:%d" % (c["macro"], c["key"], c["file"], c["line"]))
        for b in tex_bibitems:
            md.append("- `\\bibitem{%s}` at %s:%d" % (b["key"], b["file"], b["line"]))
        for f, keys in sorted(nocite_keys.items()):
            md.append("- `\\nocite` (cited without a call-out) in %s: %s" % (f, ", ".join(keys)))
    md += ["", "## Auto-derived mismatches (audit each; one finding per instance)", "",
           "Each numbered reference list is its own numbering space — the checks below are per document.",
           "",
           "- Orphan call-outs (cited, not listed): %s" % (orphan_callouts or "none"),
           "  - per document: %s" % (orphan_callouts_by_file or "none"),
           "- Uncited entries (listed, never cited anywhere): %s" % (uncited_entries or "none"),
           "  - per list: %s" % (uncited_by_list or "none"),
           "- LaTeX orphan keys (a \\cite key with no \\bibitem/.bib entry): %s" % (
               tex_orphans or "none"),
           "  - per document: %s" % (tex_orphans_by_file or "none"),
           "- LaTeX \\bibitem entries never cited by any \\cite: %s" % (tex_uncited or "none"),
           "- Duplicate entry numbers within one list: %s" % (duplicate_entries or "none"),
           "- Order violations (numeric style, within one document): %d" % len(order_violations),
           "- Max cited number: %d; entries listed: %d (across %d list(s))" % (
               max_cited, len(ref_entries), len(lists_by_file)),
           "- Author-year call-outs cannot be matched to a list mechanically — audit by hand.",
           "- Bracketed numbers FLAGGED as possible measurement intervals: %d "
           "(kept in the cited set so a reference is never falsely reported as never "
           "cited)%s" % (
               len(suspect_brackets),
               "" if not suspect_brackets else " (recorded in the JSON as suspect_brackets)")]
    if tex_unresolved:
        md.append("- LaTeX citations UNRESOLVED (unable — not a clean pass): the corpus carries "
                  "\\cite call-outs but no \\bibitem/.bib key list, so the LaTeX orphan/uncited "
                  "checks above did not run; the reference list is not in the corpus")

    with open(os.path.join(art_dir, "M2_citations.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(art_dir, "M2_citations.json"), "w", encoding="utf-8") as f:
        json.dump({"ref_entries": ref_entries, "callouts": callouts,
                   "bib_entries": bib_entries,
                   "tex_callouts": tex_callouts,
                   "tex_bibitem_entries": tex_bibitems,
                   "tex_nocite_keys": {f: sorted(set(keys)) for f, keys in nocite_keys.items()},
                   "orphan_callouts": orphan_callouts,
                   "orphan_callouts_by_file": orphan_callouts_by_file,
                   "uncited_entries": uncited_entries,
                   "uncited_entries_by_list": uncited_by_list,
                   "tex_orphan_keys": tex_orphans,
                   "tex_orphan_keys_by_file": tex_orphans_by_file,
                   "tex_uncited_keys": tex_uncited,
                   "tex_unresolved": tex_unresolved,
                   "duplicate_entries": duplicate_entries,
                   "order_violations": order_violations,
                   "suspect_brackets": suspect_brackets}, f, indent=2)

    print("M2 artifact: %d ref entries (%d list(s)), %d call-outs. Orphans: %s | Uncited: %s" % (
        len(ref_entries), len(lists_by_file), len(callouts),
        orphan_callouts or "none", uncited_entries or "none")
        + ("" if not (tex_callouts or tex_bibitems) else
           " | LaTeX keys: %d call-out(s), orphans: %s, uncited \\bibitem(s): %s%s" % (
               len(tex_callouts), tex_orphans or "none", tex_uncited or "none",
               " (UNRESOLVED: no \\bibitem/.bib list in the corpus)" if tex_unresolved else "")))


if __name__ == "__main__":
    main()

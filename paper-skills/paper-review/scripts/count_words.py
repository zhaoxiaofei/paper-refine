#!/usr/bin/env python3
r"""Word counts for the abstract/main-text length rule (check id M19).

Stdlib-only, like the other bundled scripts. The counting rule is the
pipeline's: a word is a maximal run of NON-SPACE characters with a newline
treated as space, so `state-of-the-art` is ONE word and `2026` is ONE word.

    python3 count_words.py FILE [FILE ...] [--section whole|abstract|main-text|cover-letter|auto]
                                [--json] [--base-abstract N] [--base-main-text N]
                                [--venue-profile venue_profiles/<id>.json]
                                [--article-type ID]

`auto` (the default) reports the abstract and the main text when the document
has a manuscript shape (an "Abstract" heading, or an Introduction/Main-text
heading); otherwise it reports the whole file and says so. WHICH sections end
the main-text span is the VENUE's own counting convention, read from the
profile's `counting.main_text.excludes` (see venue_profiles/README.md): the
default is the Nature Biotechnology Article rule (the abstract, Methods,
references and figure legends are outside the count), Frontiers counts the main
body WITH Methods and in-text citations, and NBT's Brief Communication counts
the abstract, references and figure legends too. Detected figure legends are
subtracted only when the venue leaves figure legends out; table captions are
subtracted only when the profile names `table-captions`. `.tex`/`.ltx`
sources are read as LaTeX: the abstract environment's own `\end{abstract}` ends
the abstract (paragraph breaks inside it do not), and `\caption`/`\captionof`
text is a legend even though its "Figure N" label is added at typesetting time.

The cover letter is counted twice: its PERSUADING part against the user's
300-500-word preference, and its TOTAL content (salutation, body, disclosures
and signature) against the profile's `cover_letter.total_max` when one is set;
the shipped profiles record no total cap.

This script assumes NO journal: without a profile it only COUNTS (no cap). Pass
`--venue-profile venue_profiles/<id>.json` to read the limits from the profile
the run is configured with (the pipeline's prompts state the same numbers), plus
`--article-type <id>` to use that type's own entry from the profile's
`article_types` table (Article, Brief Communication, Review, ...); without it
the profile's `default_article_type` is used. A type the profile carries no
numbers for -- and a profile that declares no limit -- produces counts with no
cap (`cap: null`, never "over the cap"). `--base-abstract` / `--base-main-text`
set the bases for a profile-less use (they default to no cap).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ABSTRACT_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary)\s*[:.\u2014\u2013-]?\s*$", re.I)
# The common inline layout: "Abstract: We studied ..." on one line. The heading
# itself must be recognised so the abstract is not left inside the main text;
# the remainder is its first paragraph.
INLINE_ABSTRACT_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary)\s*[:.\u2014\u2013-]\s*(\S.*)$",
    re.I)
MAIN_START = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:introduction|main text|background)\s*[:.\u2014\u2013-]?\s*$",
    re.I)
SECTION_BOUND = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary|keywords?|introduction|background|"
    r"results?|discussion|conclusions?|materials (?:and|&) methods|online methods?|methods?|"
    r"star methods|experimental procedures|"
    r"references?|bibliography|(?:literature|works) cited|figure legends?|acknowledg\w*|"
    r"author contributions?|"
    r"(?:data|code) availability|competing interests?|conflicts? of interest|funding|"
    r"supplementary (?:information|materials?|methods|figures|tables|notes?))"
    r"\s*[:.\u2014\u2013-]?\s*$", re.I)
# The venue's main-text counting convention (check id M19): the section kinds a
# word limit may leave OUT of its count. A profile states them in
# `counting.main_text.excludes` (per venue, or per article type where the types
# differ); a kind NOT listed is INSIDE the count. Without a profile the
# pipeline's historical default applies -- the Nature Biotechnology Article
# convention -- so a profile written before this field counts as it always did.
MAIN_TEXT_SECTION_KINDS = ("abstract", "methods", "references", "figure-legends",
                           "acknowledgements", "author-contributions",
                           "data-availability", "competing-interests", "funding",
                           "supplementary", "table-captions", "table-contents")
# Table captions are opt-in profile data (Frontiers groups "figure and table
# captions"); the historical default excludes figure legends only.
# `table-contents` is opt-in too: it excludes the CONTENTS of tables, which the
# DOCX reader must skip before counting (F08).
DEFAULT_MAIN_TEXT_EXCLUDES = tuple(
    kind for kind in MAIN_TEXT_SECTION_KINDS
    if kind not in ("table-captions", "table-contents"))
SECTION_KIND_RES = (
    ("methods", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:materials (?:and|&) methods|online methods?|methods?|"
        r"star methods|experimental procedures)\s*(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("references", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:references?|bibliography|"
        r"(?:literature|works) cited)\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("figure-legends", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?figure legends?\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("acknowledgements", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?acknowledg\w*\s*(?:[:.\u2014\u2013-]\s*|\s*$)",
        re.I)),
    ("author-contributions", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?author contributions?\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("data-availability", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:data|code) availability\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("competing-interests", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:competing interests?|conflicts? of interest)\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("funding", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?funding\s*(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("supplementary", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?supplementary "
        r"(?:information|materials?|methods|figures|tables|notes?)\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
)


def _heading_text(line: str) -> str:
    """A heading line with a Markdown ATX prefix or emphasis removed.

    The pipeline's own length scan strips `#{1,6}` (`_length_heading_text`);
    without the same step here `## Methods` was body text to this counter and
    a heading to the gate, so a .md manuscript got one `whole file` row and
    skipped the M19 cap check. The same holds for `**Abstract**`-style
    emphasis headings, which the pipeline scanner now recognises too.
    """
    text = re.sub(r"^\s*#{1,6}\s+", "", (line or "").strip())
    m = re.match(r"^(\*\*|__|\*|_)(\S.*?)\1(.*)$", text)
    if m and m.group(2).strip():
        text = (m.group(2) + m.group(3)).strip()
    return text


def section_kind(line: str) -> str:
    """The M19 counting-convention kind of a boundary heading ("" when not one)."""
    text = _heading_text(line)
    if not text:
        return ""
    for kind, pattern in SECTION_KIND_RES:
        if pattern.match(text):
            return kind
    return ""
KEYWORDS = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:key\s?words?)\s*"
    r"(?:[:.\u2014\u2013-]|$)", re.I)


def keyword_continuation(line: str) -> bool:
    """Does this line continue the keyword LIST, or start the body?

    The pipeline's twin `_length_keyword_continuation` must return the same
    answer on the same line, or the two M19 counters disagree. A comma/semicolon
    list of short items is a continuation; a sentence with a terminator is body;
    a short lowercase unpunctuated line is a list; anything longer is body.
    """
    text = (line or "").strip()
    if not text:
        return False
    words = text.split()
    terminated = bool(re.search(r"[.!?]\s*$", text))
    if "," in text or ";" in text:
        # Keep the pipeline twin's rule: a comma-bearing sentence is body, but a
        # capitalized one-word item ("COVID-19, SARS-CoV-2") can still be a list.
        if terminated:
            return False
        parts = [p.strip() for p in re.split(r"[,;]", text) if p.strip()]
        if not parts:
            return False
        if not text[:1].islower() and len(parts[0].split()) > 1:
            return False
        return (2 <= len(parts) <= 20 and len(words) <= 24
                and all(len(p.split()) <= 4 for p in parts))
    if terminated:
        return False
    return len(words) <= 4 and text[:1].islower()


# A caption line starts with the label, the number AND its separator ("Figure 2
# | ...", "Fig. 1: ...", "Figure 3. ..."). Without the separator guard a BODY
# sentence that merely opens with a figure reference ("Figure 2A shows that p53
# levels rose ...") was subtracted as a legend, systematically undercounting the
# main text toward a false "ok" -- `extract_numbers.FIG_CAPTION_RE` enforces the
# same separator for exactly this reason.
# The label, number and separator are the PIPELINE's own set
# (`paper_pipeline.CAPTION_START_RE`): `Figures 2 | ...` and `Fig. 3(a). ...` are
# captions there and were counted as main text here, and the counter's whole
# contract is that it reads a document the way the M19 row the venue gate uses
# reads it.
CAPTION = re.compile(r"^\s*(?:(?:supplementary|extended\s+data|supp\.?)\s+)?fig(?:ure)?s?\.?\s*"
                     r"\|?\s*"
                     r"(?:S?\d+[A-Za-z]?|(?-i:[IVXLCDM]+))"
                     r"(?:\s*\([A-Za-z0-9][A-Za-z0-9,.\u2013\-]*\))?"
                     r"\s*(?:(?:\||:|\u2014|\u2013|-)(?![A-Za-z])|\.)\s*", re.I)
# A caption-LOOKING line the strict pattern does NOT recognise: a bare label on a
# line of its own ("Fig. S3", "Figure 3"), which two-column and PDF-extracted
# text produce. The pipeline reports these as suspected captions and ENDS the
# legend at them; merging one in subtracted the NEXT figure's legend from the
# main text and reported fewer words than the pipeline's own row.
CAPTION_SUSPECT = re.compile(r"^\s*(?:(?:supplementary|extended\s+data|supp\.?)\s+)?fig(?:ure)?s?\.?\s*\|?\s*"
                             r"(?:S?\d+[A-Za-z]?|(?-i:[IVXLCDM]+))"
                             r"\s*(?:\([^)]*\)|$|[|:\u2014\u2013\-])", re.I)
# Table captions are a display-caption span only for a profile whose
# `counting.main_text.excludes` names `table-captions` (Frontiers groups
# "figure and table captions" in its main-body rule). They are never read as
# figure legends for the M18 scan.
TABLE_CAPTION = re.compile(r"^\s*(?:(?:supplementary|extended\s+data|supp\.?)\s+)?tables?\.?\s*"
                           r"(S?\d+[A-Za-z]?|(?-i:[IVXLCDM]+))"
                           r"\s*(?:\||:|\u2014|\u2013|-|\.)\s*", re.I)
COVER_SALUTATION = re.compile(r"^\s*(?:dear\b|to the (?:editor|editors)\b)", re.I)
COVER_CLOSING = re.compile(
    # The phrase must END the line's sentence (optionally with punctuation). A
    # `\b` alone read "Regards the statistical concern, ..." and "Best regards
    # are due to ..." as the close and reported 0 persuading words.
    r"^\s*(?:sincerely|yours (?:sincerely|faithfully|truly)|best regards|kind regards|regards|"
    r"with (?:best|kind) regards)\s*[,.;!]?\s*$|"
    # A bare courtesy line closes the letter; "Thank you for considering our
    # manuscript ..." is a body OPENER, and treating it as the closing set the
    # persuading count to 0 and reported a false OUTSIDE-PREFERENCE row.
    r"^\s*thank you(?:\s+(?:very much|again))?[.,!]?\s*$", re.I)
COVER_DISCLOSURE = re.compile(
    r"^\s*(?:manuscript title|title|authors?|author list|affiliations?|corresponding author|"
    r"running title|related manuscripts?|prior discussions?|suggested reviewers?|"
    r"excluded reviewers?|reviewers?|double-anonymized|orcid|competing interests?|"
    r"data availability|word counts?)\s*[:.\u2014\u2013-]", re.I)

# LaTeX sources state two boundaries that plain text leaves implicit: the
# abstract environment and the captions. Both are tracked explicitly below, so
# a `.tex` manuscript is counted with the same rule as a .md/.docx one instead
# of being answered with a markup-inclusive "whole file" row.
TEX_EXTS = (".tex", ".ltx")
TEX_SECTION = re.compile(r"^\\(?:sub)*section\*?(?:\[[^\]]*\])?\{([^{}]*)\}")
TEX_CAPTION = re.compile(r"\\caption(?:of)?\*?\s*(?:\{[^{}]*\}\s*)?(?:\[[^\]]*\]\s*)?\{")
TEX_ENV_TOKEN = re.compile(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\s*\[[^\]]*\])?")
TEX_SCAFFOLD = re.compile(
    r"\\(?:documentclass|usepackage|RequirePackage|bibliography|bibliographystyle|"
    r"includegraphics|includesvg|input|include|vspace|hspace|setlength|geometry|"
    r"graphicspath|hypersetup|newcommand|renewcommand)\*?(?:\[[^\]]*\])?"
    r"(?:\{[^{}]*\})*")
# A LaTeX comment: an UNESCAPED ``%`` and everything after it on the line. The
# escape count is what matters: ``\%`` is a literal percent sign (prose), while
# ``\\%`` is a line break followed by a comment. The old ``(?<!\\)%`` looked at
# ONE preceding backslash, so every ``\\%`` kept its comment and the comment's
# words were counted as the authors'.
TEX_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*$", re.M)


def strip_tex_comment(text: str) -> str:
    """`text` without its LaTeX comments (the escape pair kept in place)."""
    return TEX_COMMENT.sub(r"\1", text or "")


TEX_INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")


def _tex_include_path(base: Path, arg: str):
    """The .tex file an \\input/\\include/\\subfile argument names, or None."""
    arg = str(arg or "").strip().strip('"')
    if not arg:
        return None
    cand = Path(arg)
    if cand.suffix.lower() not in TEX_EXTS:
        cand = Path(str(cand) + ".tex")
    path = cand if cand.is_absolute() else (base / cand)
    try:
        resolved = path.resolve()
        resolved.relative_to(base.resolve())
    except (OSError, ValueError):
        return None                     # a path outside the manuscript directory
    return resolved if resolved.is_file() else None


_DOCX_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# A binary format this counter cannot read as text. Counting its ZIP bytes with
# errors="replace" produced a meaningless number (a small DOCX reported 1359
# words, F06), so an unsupported binary is refused with a real error instead.
BINARY_DOCUMENT_EXTS = {".pdf", ".doc", ".xls", ".xlsx", ".ppt", ".pptx",
                        ".zip", ".gz", ".tar", ".rar", ".7z"}


def docx_paragraph_text(path: Path, include_tables: bool = True):
    """The paragraphs of a .docx as text, or None when it cannot be parsed.

    The count is the text a reader sees: `w:t` runs in document order, with a
    soft break/tab rendered as a newline. Stdlib-only (zipfile + ElementTree),
    like the rest of this script; table-cell paragraphs are included because
    they are visible text, unless the venue's counting rule excludes table
    contents (`table-contents`, F08).
    """
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("word/document.xml")
        root = ET.fromstring(data)
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None
    table_paras = set()
    if not include_tables:
        for tbl in root.iter(_DOCX_W + "tbl"):
            for para in tbl.iter(_DOCX_W + "p"):
                table_paras.add(id(para))
    out = []
    for para in root.iter(_DOCX_W + "p"):
        if id(para) in table_paras:
            continue
        parts = []
        for node in para.iter():
            if node.tag == _DOCX_W + "t":
                parts.append(node.text or "")
            elif node.tag in (_DOCX_W + "br", _DOCX_W + "cr", _DOCX_W + "tab"):
                parts.append("\n")
        out.append("".join(parts))
    return "\n".join(out)


def _tex_expand_includes(text: str, base: Path, seen=None, source: Path = None,
                         _stack=None):
    """Inline \\input/\\include/\\subfile children so a multi-file paper counts.

    The pipeline's M19 scan expands includes; this counter only stripped the
    command, so a master `main.tex` that inputs its sections was reported as
    one body word (or as a whole-file count) while the orchestrator counted the
    expanded text (the 2026-10-28 audit's F06). Every occurrence of an include
    expands (the reader sees that text twice); `seen`/`_stack` carry only the
    ANCESTORS of the frame being expanded, so a true cycle is still broken.
    """
    # A COPY: an include that is a sibling of this one is not on the current
    # path, so it must expand again; discarding `child` after the recursive
    # call is what makes the set an ancestry set (F03).
    seen = set() if seen is None else set(seen)
    if source is not None:
        try:
            seen.add(Path(source).resolve())
        except (OSError, RuntimeError):
            pass
    stack = [] if _stack is None else _stack
    body = strip_tex_comment(text or "")
    stack.append(body)

    def repl(match):
        child = _tex_include_path(base, match.group(1))
        if child is None or child in seen:
            return match.group(0)
        seen.add(child)
        try:
            child_text = child.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return match.group(0)
        if child_text in stack:
            return match.group(0)
        try:
            return _tex_expand_includes(child_text, base, seen, source=child,
                                        _stack=stack)
        finally:
            seen.discard(child)

    try:
        return TEX_INCLUDE.sub(repl, body)
    finally:
        stack.pop()

ABSTRACT_RELAXATION = 1.10
MAIN_TEXT_RELAXATION = 1.25
COVER_LETTER_MIN = 300
# No built-in TOTAL-content cap: the shipped profiles record none, and the
# pipeline reports no total cap for them. A profile may set
# `cover_letter.total_max`; that value is the operator's cap.
COVER_LETTER_TOTAL_MAX = None
COVER_LETTER_MAX = 500


def count_words(text: str) -> int:
    """Maximal runs of non-space characters; a newline is a space."""
    return len(re.findall(r"\S+", text or ""))


def lenient_cap(base: int, factor: float) -> int:
    """Largest integer word count within `base` relaxed by `factor`."""
    # floor(base*factor), tolerant of the float representation error that made
    # "100 words +15%" 114.99999999999999 -> 114 instead of 115. This must stay
    # identical to paper_pipeline.lenient_word_limit(): an agent trimming to a
    # cap one word stricter than the orchestrator's turns a boundary document
    # into a spurious M19 finding.
    return math.floor(float(base) * float(factor) + 1e-9)


def _strip_latex(text: str) -> str:
    """Prose of a LaTeX line: commands removed, math blanked, braces as spaces."""
    # The OPTIONAL arguments come first: the brace-only pattern left `[p.5]` and
    # `x` behind as prose for `\cite[p.5]{x}` (and for the `\citep[see][p.5]{x}`
    # form), so M19 counted phantom words on exactly the manuscripts whose
    # counting must be trusted.
    # `[a-zA-Z]*ref` covers the whole reference family (`\pageref{p12}`,
    # `\eqref{}`, `\autoref{}`, `\cref{}`): the bare `ref` alternative missed
    # every prefixed form, so `\pageref{p12}` left the phantom word `p12` in the
    # M19 count. An ESCAPED dollar (`\$5`) is a literal, not math: the math
    # pattern is lookbehind-guarded (keep this in step with
    # paper_pipeline._strip_latex).
    text = re.sub(r"\\(?:cite[a-zA-Z]*|[a-zA-Z]*ref|label|url|href)\s*"
                  r"(?:\[[^\[\]]*\]\s*)*\{[^{}]*\}", " ", text)
    # Inline and single-line display math (`$p<0.05$`, `\(x\)`, `\[x\]`) is not
    # prose; only the command names used to be stripped, so the body's tokens
    # were counted.
    # An even run of backslashes before the math is a line break, not an
    # escape: `\\$x$` is still math, `\$5` is a literal dollar.
    text = re.sub(r"(?<!\\)(?:\\\\)*\$\$[\s\S]*?\$\$"
                  r"|(?<!\\)(?:\\\\)*\$[^$]*\$|\\\[[\s\S]*?\\\]|"
                  r"\\\([\s\S]*?\\\)", " ",
                  text)
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)
    return re.sub(r"\s+", " ", text.replace("{", " ").replace("}", " ")).strip()


# Display-math environments whose BODY is not prose. Their `\begin`/`\end`
# tokens were already stripped, so the equation's own tokens were counted as the
# authors' words -- an upward drift on an equation-heavy .tex, the dangerous
# direction against a venue cap.
TEX_MATH_ENV = re.compile(
    r"\\begin\{(equation\*?|align\*?|alignat\*?|eqnarray\*?|gather\*?|multline\*?|"
    r"displaymath|math|split|flalign\*?)\}[\s\S]*?\\end\{\1\}", re.M)


def blank_math_environments(text: str) -> str:
    """`text` without the bodies of display-math environments.

    Each blanked body keeps its own newlines, so the surrounding paragraph
    structure (and therefore the abstract/main-text line accounting) survives.
    """
    return TEX_MATH_ENV.sub(lambda m: "\n" * m.group(0).count("\n"), text or "")


def _brace_delta(text: str) -> int:
    """Unescaped ``{`` minus unescaped ``}`` in `text`."""
    delta, esc = 0, False
    for ch in text:
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1
    return delta


def _split_group(text: str):
    """(inside, after) for the rest of a ``{...}`` group whose ``{`` was consumed.

    `text` starts INSIDE the group (the caller matched up to and including the
    opening brace), so the depth starts at 1; an unclosed group returns the
    whole text as ``inside`` and an empty remainder.
    """
    depth, esc = 1, False
    for i, ch in enumerate(text):
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[:i], text[i + 1:]
    return text, ""


def _line_text(line: str) -> str:
    """Prose of one LaTeX line: environment tokens and command arguments gone."""
    return _strip_latex(TEX_SCAFFOLD.sub(" ", TEX_ENV_TOKEN.sub(" ", line)))


def _tex_float_env_after(line: str, state):
    """The figure/table float environment state after one source line."""
    for tok in re.finditer(r"\\(begin|end)\{(table\*?|figure\*?)\}", line or ""):
        kind = "table" if tok.group(2).startswith("table") else "figure"
        if tok.group(1) == "begin":
            state = kind
        elif state == kind:
            state = None
    return state


def tex_lines(text: str):
    """(lines, abstract_end, caption_lines) for a LaTeX source.

    `lines` are heading/paragraph lines; `abstract_end` is the line index the
    abstract's text stops at (`\\end{abstract}`, so paragraph breaks inside the
    environment stay inside the abstract); `caption_lines` are `(line index,
    kind)` entries for the single lines holding a `\\caption`/`\\captionof`
    text (each such group becomes its own line, so subtracting that line
    removes exactly the legend's words). The kind is `figure`/`table`, so the
    caller subtracts only the caption kinds its venue excludes (F04).
    """
    lines, captions, abstract_end = [], [], None
    env_kind = None
    raw_lines = blank_math_environments(text or "").splitlines()
    # A verbatim/listing environment is code, not prose. It was stripped of
    # its command tokens but its BODY stayed, so a code listing inflated the
    # venue's word count (the citation sweep already treats the same text as
    # non-manuscript). Handles an inline begin/end pair on one line too.
    _clean, _in_verb = [], None
    for _raw in raw_lines:
        _line = _raw
        if _in_verb is not None:
            _end = re.search(r"\\end\{" + re.escape(_in_verb) + r"\}", _line)
            if not _end:
                _clean.append("")
                continue
            _line = _line[_end.end():]
            _in_verb = None
        # A comment is not source: `% \begin{verbatim}` must not open the
        # environment, or the rest of the document is blanked as code.
        _line = strip_tex_comment(_line)
        while True:
            _b = re.search(r"\\begin\{(verbatim|lstlisting|minted|Verbatim)\}",
                           _line)
            if not _b:
                break
            _e = re.search(r"\\end\{" + re.escape(_b.group(1)) + r"\}",
                           _line[_b.end():])
            if _e:
                _line = _line[:_b.start()] + _line[_b.end() + _e.end():]
            else:
                _in_verb = _b.group(1)
                _line = _line[:_b.start()]
                break
        _clean.append(_line)
    raw_lines = _clean
    i, n = 0, len(raw_lines)
    while i < n:
        raw = raw_lines[i]
        i += 1
        line = strip_tex_comment(raw).strip()
        env_at_start = env_kind
        env_kind = _tex_float_env_after(line, env_kind)
        # `re.search`, not `re.match`: a legal one-line abstract preceded by
        # title text on the same source line is still an abstract environment,
        # exactly as the pipeline's scan treats it (F05).
        begins = re.search(r"\\begin\{abstract\}", line)
        ends = re.search(r"\\end\{abstract\}", line)
        if begins or ends:
            # Both tokens may sit ANYWHERE on the line (`\begin{abstract} ...
            # \end{abstract}`, or the usual `Last sentence.\end{abstract}`):
            # the old start-anchored tests left `abstract_end` unset on the
            # usual ending, so the next paragraph was counted as abstract text
            # and the main-text count lost it.
            if begins:
                lines.append("Abstract")
            head_from = begins.end() if begins else 0
            if ends is None:
                rest = _line_text(line[head_from:])
                if rest:
                    lines.append(rest)
            else:
                head = _line_text(line[head_from:ends.start()])
                if head:
                    lines.append(head)
                abstract_end = len(lines)
                after = _line_text(line[ends.end():])
                if after:
                    lines.append(after)
            continue
        if re.search(r"\\begin\s*\{thebibliography\}", line) \
                or re.search(r"\\bibliography\s*\{", line) \
                or re.search(r"\\printbibliography\b", line):
            # The reference list is not main text when the venue excludes
            # references. `\begin{thebibliography}` is stripped as an
            # environment token, `\bibliography{...}` as scaffold, and
            # biblatex's `\printbibliography` matched neither.
            lines.append("References")
            continue
        m = TEX_SECTION.match(line)
        if m:
            lines.append(m.group(1).strip())
            continue
        cap = TEX_CAPTION.search(line)
        if cap:
            before = _line_text(line[:cap.start()])
            if before:
                lines.append(before)
            group = line[cap.end():]
            depth = 1 + _brace_delta(group)
            while depth > 0 and i < n:
                nxt = strip_tex_comment(raw_lines[i]).strip()
                i += 1
                group = f"{group}\n{nxt}"
                depth += _brace_delta(nxt)
            cap_text, after = _split_group(group)
            cap_kind = _tex_float_env_after(line[:cap.start()], env_at_start)
            of = re.match(r"\\captionof\*?\s*\{([^{}]*)\}", line[cap.start():])
            if of:
                cap_kind = of.group(1).strip().lower()
            captions.append((len(lines), cap_kind))
            lines.append(_strip_latex(cap_text))
            after = _line_text(after)
            if after:
                lines.append(after)
            continue
        stripped = _line_text(line)
        if stripped:
            lines.append(stripped)
    return lines, abstract_end, captions


def _abstract_end(lines, start):
    """Index where the abstract's text ends.

    A section heading (or the Keywords line) is the boundary the manuscript
    itself states. A blank line is only a fallback for a document that has no
    such boundary at all: a multi-paragraph abstract is legitimate, and
    stopping at its first blank line undercounted the abstract while charging
    the later paragraphs to the main text.
    """
    j = start
    seen_text = False
    first_blank = None
    while j < len(lines):
        line = lines[j].strip()
        heading = _heading_text(line)
        if SECTION_BOUND.match(heading) or MAIN_START.match(heading) \
                or KEYWORDS.match(heading):
            return j
        if not line:
            if seen_text and first_blank is None:
                first_blank = j
            j += 1
            continue
        seen_text = True
        j += 1
    return first_blank if first_blank is not None else j


def _caption_match(line: str, kinds=("figure",)):
    """The regex match for one caption line of a selected kind, or None."""
    if "figure" in kinds:
        m = CAPTION.match(line)
        if m:
            return m
    if "table" in kinds:
        m = TABLE_CAPTION.match(line)
        if m:
            return m
    return None


def caption_ranges(lines: list, kinds=("figure",)) -> list:
    """(start, end) line ranges of captions, continuation lines merged.

    `kinds` is the caption kinds the venue excludes: figure legends always for
    `figure-legends`, table captions only for `table-captions`.

    Mirrors the pipeline's ``_caption_units_from_lines`` boundary rule: a legend
    continues while the next line is non-empty, is not a heading (markdown's
    ``#`` or a bound section name), is not a new caption or a caption-SUSPECT
    line (a bare "Fig. S3" label, which the pipeline ends the legend at), and
    (once the legend text ends in sentence-final punctuation) does not start a
    new flush-left paragraph.
    """
    ranges, i, n = [], 0, len(lines)
    while i < n:
        if not _caption_match(lines[i].strip(), kinds):
            i += 1
            continue
        j = i + 1
        while j < n:
            raw = lines[j]
            nxt = raw.strip()
            if not nxt or nxt.startswith("#") or _caption_match(nxt, kinds) \
                    or CAPTION_SUSPECT.match(nxt) or SECTION_BOUND.match(nxt):
                break
            if lines[j - 1].rstrip().endswith((".", "!", "?")) and not raw[:1].isspace():
                break
            j += 1
        ranges.append((i, j))
        i = j
    return ranges


def sections(text: str, abstract_end=None, caption_lines=None, excludes=None) -> list:
    """[(section, words, note)] for a document's text lines.

    `abstract_end` and `caption_lines` are the explicit LaTeX boundaries from
    `tex_lines()`: the abstract stops there whatever blank lines it contains,
    and only captions inside the counted main-text span are subtracted.
    `excludes` is the venue's counting convention (the section kinds its
    main-text limit leaves OUT, from `counting.main_text.excludes`); None keeps
    the pipeline's default (the Nature Biotechnology Article convention). The
    abstract is still reported as its own row when the venue counts it inside
    the main text, and figure legends / table captions are subtracted only when
    the venue excludes that caption kind.
    """
    excludes = set(DEFAULT_MAIN_TEXT_EXCLUDES if excludes is None else excludes)
    include_abstract = "abstract" not in excludes
    caption_kinds = tuple(
        kind for kind, section in (("figure", "figure-legends"),
                                   ("table", "table-captions"))
        if section in excludes)
    subtract_captions = bool(caption_kinds)
    lines = (text or "").splitlines()
    n = len(lines)
    abs_start = abs_end = None
    for i, raw in enumerate(lines):
        heading = _heading_text(raw)
        inline = INLINE_ABSTRACT_HEAD.match(heading)
        if inline:
            # Keep the remainder as the abstract's first paragraph; the heading
            # itself is not counted.
            lines[i] = inline.group(1)
            abs_start = i
            abs_end = (max(abs_start, min(int(abstract_end), n)) if abstract_end is not None
                       else _abstract_end(lines, abs_start))
            break
        if ABSTRACT_HEAD.match(heading):
            abs_start = i + 1
            abs_end = (max(abs_start, min(int(abstract_end), n)) if abstract_end is not None
                       else _abstract_end(lines, abs_start))
            break
        # "Summary" is also a common CLOSING heading. The pipeline scan stops
        # at a body heading before accepting a later Summary; this loop did not,
        # so a paper that starts with Introduction and ends with Summary was
        # treated as abstract-only and its main text reported as 0 (F05).
        if MAIN_START.match(heading) or section_kind(heading):
            break
    main_start = None
    for i, raw in enumerate(lines):
        if MAIN_START.match(_heading_text(raw)):
            main_start = i + 1
            break
    if abs_start is None and main_start is None and not include_abstract:
        return [("whole file", count_words(text), "no abstract/main-text shape detected")]
    rows = []
    if abs_start is not None:
        rows.append(("abstract", count_words(" ".join(lines[abs_start:abs_end])), ""))
    # The main-text span starts after an excluded abstract; when the venue
    # counts the abstract inside the main text, it starts at the abstract's own
    # text (title/author block stays out), or at the beginning of a document
    # with no headings at all (NBT's Brief Communication).
    if abs_start is not None:
        start = abs_start if include_abstract else abs_end
    elif main_start is not None:
        start = main_start
    else:
        start = 0
    offset = start
    # Build the counted set line by line. An excluded section heading starts a
    # skip; a later heading whose kind the venue does NOT exclude resumes the
    # count. Stopping at the first excluded heading silently dropped a Results
    # or Discussion section that follows a mid-paper Methods block, although
    # the profile says that kind is inside the count.
    included = [False] * n
    excluded_now = False
    end_found = False
    in_keyword_block = False
    for i in range(start, n):
        stripped = _heading_text(lines[i])
        if KEYWORDS.match(stripped):
            # A Keywords line is not a section kind: the old generic branch
            # resumed the count after it, putting the keyword list and any
            # Methods prose after it back into the main text. The following
            # continuation lines of the keyword block are not prose either.
            in_keyword_block = True
            excluded_now = True
            continue
        if in_keyword_block:
            if not stripped:
                in_keyword_block = False
                excluded_now = False
                continue
            if keyword_continuation(stripped):
                continue                # a wrapped keyword list is not prose
            # A non-empty line that is not a keyword continuation ends the
            # block AND is body text: a Brief Communication written as
            # "Keywords: ..." directly followed by its body (no blank line, no
            # headings) used to lose the whole body and report 0 main-text words.
            in_keyword_block = False
            excluded_now = False
        if SECTION_BOUND.match(stripped) or MAIN_START.match(stripped):
            in_keyword_block = False
        if SECTION_BOUND.match(stripped) or MAIN_START.match(stripped):
            kind = section_kind(stripped)
            if kind and kind in excludes:
                excluded_now = True
                end_found = True
            else:
                excluded_now = False
            continue
        included[i] = not excluded_now
    body = [lines[i] for i in range(start, n) if included[i]]
    cap_ranges = []
    if subtract_captions:
        if caption_lines is None:
            cap_ranges = [(offset + a, offset + b)
                          for a, b in caption_ranges(lines[offset:], kinds=caption_kinds)]
        else:
            # `caption_lines` from tex_lines() carries (index, kind): subtract
            # only the caption kinds the venue excludes. A flat integer list is
            # a legacy caller that has no kind information, so it is subtracted
            # when any caption kind is excluded (its old behaviour).
            keep = []
            for entry in caption_lines:
                if isinstance(entry, (tuple, list)):
                    idx, kind = entry[0], str(entry[1] or "").strip().lower()
                    if kind and kind not in caption_kinds:
                        continue
                else:
                    idx = entry
                keep.append(int(idx))
            cap_ranges = [(i, i + 1) for i in sorted(set(keep))]
    captions = sum(
        count_words(" ".join(lines[j] for j in range(max(a, start), min(b, n))
                            if included[j]))
        for a, b in cap_ranges
        if any(included[i] for i in range(max(a, start), min(b, n)))
    )
    words = max(0, count_words(" ".join(body)) - captions)
    notes = []
    if abs_start is None:
        # The count does not always start at line 0: with a main-text heading
        # and no Abstract, `start` is the line AFTER that heading, and the note
        # the M19 artifact carries must say so (it fed the audit trail a span
        # that began earlier than the counted one).
        notes.append("no Abstract heading; counted from the start of the document"
                     if not start else
                     "no Abstract heading; counted from after the main-text heading")
    if not end_found:
        if set(excludes) != set(DEFAULT_MAIN_TEXT_EXCLUDES):
            notes.append("counted through the sections the venue includes; no excluded "
                         "section heading found")
        else:
            notes.append("no Methods/References heading; counted to the end")
    if captions:
        notes.append(f"{captions} caption word(s) subtracted")
    counting_inside = [kind for kind in ("abstract", "methods", "references", "figure-legends")
                       if kind not in excludes]
    if counting_inside and set(excludes) != set(DEFAULT_MAIN_TEXT_EXCLUDES):
        notes.append("the venue's counting rule includes "
                     + ", ".join(kind.replace("-", " ") for kind in counting_inside)
                     + " in the main text")
    rows.append(("main text", words, "; ".join(notes)))
    return rows


def _name_is_type_manuscript(name: str, type_names=()) -> bool:
    """True when a filename IS one of the selected article type's spellings."""
    stem = Path(str(name or "")).stem
    norm = re.sub(r"[^a-z0-9]+", " ", stem.lower()).strip()
    if not norm:
        return False
    for t in type_names:
        t = re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip()
        if not t:
            continue
        if norm == t:
            return True
        if norm.startswith(t + " ") and re.fullmatch(
                r"(?:v|rev|version|revision|draft)? ?\d{1,3}", norm[len(t) + 1:]):
            return True
    return False


def is_cover_letter(text: str, name: str = "", type_names=()) -> bool:
    """A cover letter, by filename or opening salutation.

    The selected article type's own manuscript name outranks the salutation:
    a Letter-to-the-Editor manuscript opens "Dear Editor," too. Same order as
    the pipeline's `_is_cover_letter_lines()`.
    """
    if _name_is_type_manuscript(name, type_names):
        return False
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    if _COVER_REPLY_RE.search(base):
        return False
    if _COVER_WORD_RE.search(name or ""):
        return True
    for line in (text or "").splitlines()[:12]:
        if COVER_SALUTATION.match(line.strip()):
            return True
    return False


RAW_DATA_DIRNAMES = ("raw_data",)
HUMAN_FEEDBACK_DIR = "human_review_feedback"
LLM_FEEDBACK_DIR = "llm_review_feedback"
EVIDENCE_DIRNAMES = RAW_DATA_DIRNAMES + (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR)
# `<evidence area>.disabled` / `.off` is inert evidence (the pipeline's
# `is_disabled_evidence_rel`); exact-name membership swept it as manuscript.
DISABLED_EVIDENCE_SUFFIXES = ("disabled", "off")


def _is_evidence_part(part: str) -> bool:
    low = str(part or "").strip().lower()
    if low in EVIDENCE_DIRNAMES:
        return True
    return any(low.startswith(area + ".")
               and low[len(area) + 1:] in DISABLED_EVIDENCE_SUFFIXES
               for area in EVIDENCE_DIRNAMES)
# A venue ARTICLE TYPE is the authors' manuscript, not the editors' letter:
# `letter_to_the_editor.docx` / `Editorial.docx` must reach M1/M2/M4/M19.
_ARTICLE_TYPE_MANUSCRIPT_RE = re.compile(
    r"^(?:(?:the[.\s_-]+)?editorial(?:[.\s_-]+board)?|"
    r"letters?[.\s_-]+(?:to|for)[.\s_-]+(?:the[.\s_-]+)?editor)"
    r"(?:[.\s_-]+(?:v|rev|version|revision|draft)?[.\s_-]*\d{1,3})?$", re.I)
# `.reply`/`.review`/`.notes` name the DOCUMENT kind, not another extension.
_SEMANTIC_SUFFIX_RE = re.compile(
    r"\.(?:reply|response|rebuttal|review|notes?|comments?)\.[A-Za-z0-9]+$", re.I)
EXTERNAL_FEEDBACK_RE = re.compile(
    r"(?<![a-z])(?:feedbacks?(?:[-_ ]?(?:form|report|letter|comments?|summary|"
    r"to[-_ ]?authors))*|"
    r"(?:referees?|reviewers?)(?:[-_ ]?(?:comments?|reports?|critiques?|forms?))*|"
    r"(?<![a-z_])editors?(?:[-_ ]?(?:comments?|decisions?|reports?|letters?|"
    r"notices?|emails?|critiques?|forms?))|"
    r"editorial|decision[_ \-]*(?:letter|notice|email))(?![a-z])",
    re.I)
# The pipeline's `AUTHORED_REPLY_NAME_RE` is a bare role WORD, so
# `ReviewerResponse.md` and `reviewerresponse.md` are the authors' reply there.
# The science-compound carve-out below still protects `immune_response.md`.
AUTHORED_REPLY_RE = re.compile(
    r"(?:responses?|repl(?:y|ies)|rebuttal|point[-_ ]?by[-_ ]?point)",
    re.I)
# A scientific compound that merely ENDS in a role word is not a reply or a
# feedback file: `dose_response.txt` / `immune_response.md` / `biofeedback_results.txt`
# are real manuscripts and must reach the M19 count.
_SCIENCE_ROLE_COMPOUND_RE = re.compile(
    r"(?<![a-z])(?:dose|immune|stress|apoptotic|inflammatory|transcriptional|"
    r"pharmacodynamic)[-_ ]?response"
    r"|(?<![a-z])response[-_ ]?(?:time|rate|curve|latency|element|surface|variable)"
    r"|(?<![a-z])feedback[-_ ]?(?:loop|control|gain|signal)"
    r"|(?<![a-z])(?:bio|neuro|video|audio)[-_ ]?feedback", re.I)
# The WORD "cover" (and the camelCase "coverLetter"/"plainLetter"), not the
# substring: a bare `"cover" in name` also named `discovery.md`,
# `coverage_table.txt` and `recovered_samples.md` the cover letter (forcing them
# into the submission runs) and masked a reply file whose name merely contains the
# substring. A word starts at the start, after a non-letter, or at a lower->UPPER
# camelCase boundary; it ends at a non-lowercase character.
_COVER_WORD_RE = re.compile(
    r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
    r"(?:[Cc]over|COVER|(?i:coverletter|plainletter))(?![a-z])")
# An authored REPLY is not a cover letter, whatever else its name contains.
# The pipeline's `_is_cover_letter_lines` has excluded these all along; this
# predicate did not, so a response-to-reviewers package was measured against
# the 300-500-word cover-letter preference (the 2026-10-28 audit's F08).
_COVER_REPLY_RE = re.compile(
    r"response|repl(?:y|ies)|rebuttal|point[\s_-]?by[\s_-]?point|"
    r"decision[\s_-]?(?:letter|notice)|referee|reviewer", re.I)


def is_evidence_path(path: str) -> bool:
    """True when the given file is raw-data EVIDENCE, not a submission document.

    A file under `raw_data/`, or an editors'/reviewers'
    feedback file, is never counted against a submission's abstract/main-text/
    cover-letter limits, whatever its name suggests.
    """
    parts = str(path).replace("\\", "/").split("/")
    if any(_is_evidence_part(part) for part in parts[:-1]):
        return True
    # The converter FLATTENS an evidence file's directory into its name
    # ("raw_data/table1.txt" -> "raw_data__table1.txt"); the two sibling
    # extractors (extract_citations.py, extract_acronyms.py) already gate on
    # that spelling, and without it raw-data text was counted against the
    # submission's abstract/main-text limits.
    if any(parts[-1].startswith(d + "__") for d in EVIDENCE_DIRNAMES):
        return True
    # A cover letter IS a submission document -- and this test must come FIRST,
    # exactly as in extract_citations.py: with the reply/feedback test below it,
    # `cover_letter_response.md` was dropped as reviewers' feedback and the
    # letter never reached the M19 length sweep.
    if _COVER_WORD_RE.search(parts[-1]):
        return False
    base = parts[-1]
    if _SEMANTIC_SUFFIX_RE.search(base):
        return True             # a reply/review/notes DOCUMENT, never author prose
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
    return bool(EXTERNAL_FEEDBACK_RE.search(cleaned)
                or AUTHORED_REPLY_RE.search(cleaned))


def cover_letter_words(text: str) -> int:
    """Words in the PERSUADING part (salutation, signature, disclosures excluded)."""
    lines = (text or "").splitlines()
    start = 0
    for i, line in enumerate(lines[:12]):
        if COVER_SALUTATION.match(line.strip()):
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if COVER_CLOSING.match(lines[i].strip()):
            end = i
            break
    body = [ln for ln in lines[start:end] if not COVER_DISCLOSURE.match(ln.strip())]
    return count_words(" ".join(body))


def _venue_profile_path(value: str) -> Path:
    """The profile FILE a `--venue-profile` argument names.

    The sweep documents show `--venue-profile <id>` (the profile's id, not a
    path). A bare id resolves against the repository's `venue_profiles/` (or the
    current directory's), while an existing path keeps working exactly as
    before: a caller that already passes `venue_profiles/<id>.json` is not
    touched.
    """
    p = Path(str(value)).expanduser()
    if p.is_file():
        return p
    raw = str(value).strip()
    if raw and not raw.lower().endswith(".json") and "/" not in raw and "\\" not in raw:
        # The pipeline lowercases a bare id and resolves it case-insensitively;
        # `--venue-profile NATURE-BIOTECHNOLOGY` must not fail while
        # `load_venue_profile` accepts it.
        for stem in dict.fromkeys((raw, raw.lower())):
            for base in (Path(__file__).resolve().parents[3], Path.cwd()):
                candidate = base / "venue_profiles" / f"{stem}.json"
                if candidate.is_file():
                    return candidate
    return p


def _article_type_id(entry: dict) -> str:
    """The id a raw article-type entry resolves to, exactly as the pipeline does.

    `normalize_venue_profile` derives a missing id from the label
    (`Brief Communication` -> `brief-communication`) and only then falls back
    to `default`; reading only `entry["id"]` skipped a legal first entry and
    inherited the cover-letter rule from a later type.
    """
    if not isinstance(entry, dict):
        return ""
    explicit = str(entry.get("id") or "").strip().lower()
    if explicit:
        return explicit
    slug = re.sub(r"[^a-z0-9]+", "-",
                  str(entry.get("label") or "").strip().lower()).strip("-")
    return slug or "default"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--section", choices=["auto", "whole", "abstract", "main-text", "cover-letter"],
                    default="auto")
    ap.add_argument("--base-abstract", type=int, default=None,
                    help="article-type abstract base for a profile-less use "
                         "(default: no cap)")
    ap.add_argument("--base-main-text", type=int, default=None,
                    help="article-type main-text base for a profile-less use "
                         "(default: no cap)")
    ap.add_argument("--venue-profile", metavar="ID_OR_FILE",
                    help="venue profile id or JSON file (venue_profiles/<id>.json): take the "
                         "abstract/main-text base and margins and the cover-letter preference "
                         "from its article_types table")
    ap.add_argument("--article-type", default=None, metavar="ID",
                    help="which of the profile's article types this submission is (default: the "
                         "profile's default_article_type); a type the profile carries no numbers "
                         "for is counted with no cap instead of borrowing another type's")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    base_abstract, base_main = args.base_abstract, args.base_main_text
    rel_abstract, rel_main = ABSTRACT_RELAXATION, MAIN_TEXT_RELAXATION
    cover_min, cover_max = COVER_LETTER_MIN, COVER_LETTER_MAX
    cover_total_max = COVER_LETTER_TOTAL_MAX
    counting_excludes = None
    manuscript_type_names = []
    venue = "(no venue profile: counts only, no cap)"
    if args.venue_profile:
        profile_path = _venue_profile_path(args.venue_profile)
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"error: cannot read --venue-profile {args.venue_profile} "
                  f"(resolved {profile_path}): {e}", file=sys.stderr)
            return 2
        # The profile's article_types table is authoritative; a profile written in
        # the older single-type shape (top-level length_limits) is read as one
        # entry, and a type that carries no numbers keeps cap: null.
        types = (profile or {}).get("article_types") or []
        type_id = str(args.article_type or (profile or {}).get("default_article_type")
                      or "").strip().lower()
        if types and not type_id:
            # Mirror the pipeline's own rule (normalize_venue_profile):
            # `default_article_type or clean_types[0]["id"]` -- with no
            # --article-type and no default, the FIRST type is the default. The
            # loop below matched every candidate on `not type_id` and broke on
            # none, so the LAST type won silently: an arbitrary type's caps were
            # applied to the submission (110/1875 where the profile meant
            # 150/3000) with no hint in the output.
            first = next((c for c in types
                          if isinstance(c, dict) and _article_type_id(c)), None)
            if first is not None:
                type_id = _article_type_id(first)
        entry = None
        if types:
            for candidate in types:
                if not isinstance(candidate, dict):
                    continue
                cid = _article_type_id(candidate)
                if cid and (not type_id or cid == type_id):
                    entry = candidate
                    if cid == type_id:
                        break
            if entry is None:
                known = ", ".join(_article_type_id(c) for c in types
                                  if isinstance(c, dict))
                print(f"error: --article-type {args.article_type!r} is not one of this venue "
                      f"profile's types ({known})", file=sys.stderr)
                return 2
            type_id = _article_type_id(entry) or type_id or "default"
        venue = str((profile or {}).get("id") or args.venue_profile)
        if types:
            venue += f" [{entry.get('label') or type_id}]"
        manuscript_type_names = [x for x in
                                 ((entry or {}).get("label"), type_id) if x]
        limits = ((entry or {}).get("length_limits")
                  if types else (profile or {}).get("length_limits")) or {}

        def _limit(key, default_base, default_relaxation):
            spec = limits.get(key)
            if isinstance(spec, (int, float)) and not isinstance(spec, bool):
                # The profile loader's bare-number shorthand: a number means
                # base=N with relaxation=1.0. Reading only dicts reported no cap
                # for a legal profile the pipeline enforced.
                return float(spec), 1.0
            if not isinstance(spec, dict) or "base" not in spec or "relaxation" not in spec:
                # The profile was loaded and this type states no USABLE number
                # for the section (absent, null, an empty block, or an unpaired
                # base): never borrow the built-in default or another type's cap
                # (the pipeline reports cap: null for the same profile and its
                # validator requires base+relaxation together).
                return None, None
            base = spec.get("base", default_base)
            relaxation = spec.get("relaxation", default_relaxation)
            if base is None or relaxation is None:
                return None, None           # the profile carries no number here
            try:
                return float(base), float(relaxation)
            except (TypeError, ValueError):
                # A hand-edited profile can carry `"base": "abc"`. The tool's
                # contract is a clean row with no cap, not a float() traceback
                # out of the middle of the count.
                print(f"warning: venue profile {args.venue_profile!r} has a "
                      f"non-numeric {key!r} length limit; reporting no cap",
                      file=sys.stderr)
                return None, None

        if limits.get("abstract") is not None or limits.get("main_text") is not None:
            base_abstract, rel_abstract = _limit("abstract", base_abstract, rel_abstract)
            base_main, rel_main = _limit("main_text", base_main, rel_main)
        else:
            base_abstract = base_main = rel_abstract = rel_main = None
        cover_stated = isinstance(limits.get("cover_letter"), dict)
        cover = limits.get("cover_letter") or {}
        if not cover_stated and types:
            # The cover-letter preference is venue-wide: a type that states NO
            # cover_letter block at all inherits the default type's, exactly as
            # the pipeline does. An explicit block with null min/max MEANS
            # "none" (venue_profiles/README.md), so it is not inherited.
            default_id = str((profile or {}).get("default_article_type") or "").strip().lower()
            if not default_id:
                # The pipeline's normalizer fills `default_article_type` with
                # the FIRST type when the raw file omits it, deriving a missing
                # id from that entry's label; this tool reads the raw file, so
                # it must apply the same fallback instead of silently using the
                # built-in preference (or skipping an id-less first entry).
                first = next((c for c in types if isinstance(c, dict)), None)
                default_id = _article_type_id(first) if first is not None else ""
            for candidate in types:
                if isinstance(candidate, dict) and \
                        _article_type_id(candidate) == default_id:
                    cover = ((candidate.get("length_limits") or {}).get("cover_letter")
                             or cover)
                    break
        def _profile_number(value, key):
            """A profile's numeric limit, or None (with a warning) when malformed."""
            if value is None:
                return None
            try:
                number = float(value)
            except (TypeError, ValueError):
                print(f"warning: venue profile {args.venue_profile!r} has a "
                      f"non-numeric {key!r} cover-letter limit; reporting no "
                      f"cap", file=sys.stderr)
                return None
            return int(number) if number.is_integer() else number

        cover_min = _profile_number(cover.get("min", cover_min), "cover_letter.min")
        cover_max = _profile_number(cover.get("max", cover_max), "cover_letter.max")
        # A profile is authoritative: an absent total_max MEANS "no TOTAL cap"
        # (the pipeline's rule). The no-profile path has no built-in cap either,
        # so the total count is reported without one.
        cover_total_max = (_profile_number(cover.get("total_max"), "cover_letter.total_max")
                           if args.venue_profile else None)
        if not limits:
            print(f"note: {args.venue_profile} carries no numbers for "
                  f"{type_id or 'its default type'}; reporting counts with no cap",
                  file=sys.stderr)
        # The MAIN-TEXT COUNTING CONVENTION is profile data too: the selected
        # article type's own block wins, else the venue's, else the pipeline
        # default. An explicit empty list means "nothing is excluded".
        counting = (entry or {}).get("counting") if types else None
        if counting is None:
            counting = (profile or {}).get("counting")
        if isinstance(counting, dict):
            spec = counting.get("main_text") or {}
            if isinstance(spec.get("excludes"), list):
                counting_excludes = [str(kind).strip().lower().replace("_", "-")
                                     for kind in spec["excludes"] if str(kind).strip()]
    caps = {"abstract": (lenient_cap(base_abstract, rel_abstract)
                         if base_abstract is not None and rel_abstract is not None else None),
            "main text": (lenient_cap(base_main, rel_main)
                          if base_main is not None and rel_main is not None else None)}
    if cover_min is not None and cover_max is not None:
        cover_pref = f"the {cover_min}-{cover_max}-word range"
    elif cover_max is not None:
        cover_pref = f"at most {cover_max} words"
    elif cover_min is not None:
        cover_pref = f"at least {cover_min} words"
    else:
        cover_pref = ""
    cover_pref_note = (
        f"persuading part only; {cover_pref} is the user's preference, not a venue limit"
        if cover_pref else
        "persuading part only; this venue profile configures no cover-letter preference")
    cover_total_note = (
        f"TOTAL content (salutation, body, disclosures and signature); the "
        f"{cover_total_max}-word cap is the operator's default, not a venue limit"
        if cover_total_max is not None else
        "TOTAL content; no operator cap configured")
    out, failed = [], False
    for name in args.files:
        p = Path(name)
        if is_evidence_path(name):
            print(f"error: {name} is raw-data EVIDENCE (or editors'/reviewers' feedback), "
                  f"not a submission document — it is never counted against an "
                  f"abstract/main-text/cover-letter limit", file=sys.stderr)
            failed = True
            continue
        ext = p.suffix.lower()
        if ext == ".docx":
            # A DOCX is a ZIP: reading it as UTF-8 text counted replacement
            # characters as words (F06). Extract the visible paragraphs, and
            # refuse an unparseable package rather than inventing a count. A
            # venue that excludes table CONTENTS must not see cell paragraphs.
            text = docx_paragraph_text(
                p, include_tables=not counting_excludes
                or "table-contents" not in counting_excludes)
            if text is None:
                print(f"error: cannot parse {name} as a DOCX package", file=sys.stderr)
                failed = True
                continue
        elif ext in BINARY_DOCUMENT_EXTS:
            print(f"error: {name} is a binary document ({ext}); convert it to text "
                  f"or DOCX first -- counting its bytes is meaningless", file=sys.stderr)
            failed = True
            continue
        else:
            try:
                # utf-8-sig: a Windows-authored manuscript can start with a UTF-8
                # BOM; read as plain utf-8 it turns the first line into
                # "\ufeffAbstract" and the abstract heading is never seen.
                text = p.read_text(encoding="utf-8-sig", errors="replace")
            except OSError as e:
                print(f"error: cannot read {name}: {e}", file=sys.stderr)
                failed = True
                continue
        if ext in TEX_EXTS:
            # A multi-file manuscript's body lives in the children; counting
            # the master alone reported 1-2 words (F06).
            text = _tex_expand_includes(text, p.parent, source=p)
            lines, abstract_end, caption_lines = tex_lines(text)
            prepared = "\n".join(lines)
            rows = ([("whole file", count_words(prepared),
                      "the whole file (requested with --section whole)")]
                    if args.section == "whole"
                    else sections(prepared, abstract_end=abstract_end,
                                  caption_lines=caption_lines,
                                  excludes=counting_excludes))
        else:
            rows = ([("whole file", count_words(text),
                      "the whole file (requested with --section whole)")]
                    if args.section == "whole"
                    else sections(text, excludes=counting_excludes))
        if (args.section in ("auto", "cover-letter")) and is_cover_letter(
                text, p.name, manuscript_type_names):
            rows = [("cover letter", cover_letter_words(text),
                     cover_pref_note),
                    ("cover letter total", count_words(text), cover_total_note)]
        elif args.section == "cover-letter":
            # Never answer a cover-letter request with silence: an empty rows
            # list is indistinguishable from a crashed/ignored run.
            rows = [("not a cover letter", count_words(text),
                     "no salutation and no 'cover' in the filename; the cover-letter word "
                     "check does not apply -- counted the whole file")]
        keep = []
        for section, words, note in rows:
            if args.section == "whole" and section != "whole file":
                continue
            if args.section == "abstract" and section != "abstract":
                continue
            if args.section == "main-text" and section != "main text":
                continue
            cap = caps.get(section)
            row = {"file": str(p), "section": section, "words": words, "cap": cap,
                   "over_limit": bool(cap and words > cap), "note": note}
            if section == "cover letter":
                row["min"] = cover_min
                row["max"] = cover_max
                row["within_preference"] = ((cover_min is None or words >= cover_min)
                                            and (cover_max is None or words <= cover_max))
                row["over_limit"] = False                 # the preference is not a cap
            if section == "cover letter total":
                row["total_max"] = cover_total_max
                row["over_limit"] = bool(cover_total_max and words > cover_total_max)
            keep.append(row)
        if not keep and args.section in ("abstract", "main-text"):
            # The principle the cover-letter branch above already honours: an
            # empty rows list is indistinguishable from a crashed or ignored run.
            # A document with no abstract / no main-text shape answered with
            # NOTHING (stdout and JSON both silent, exit 0), which an M19 sweep
            # reads as "not checked" -- a missing data point, not a clean one.
            whole = count_words(text)
            keep.append({"file": str(p), "section": f"no {args.section} section detected",
                         "words": whole, "cap": None, "over_limit": False,
                         "note": f"no {args.section} shape was detected in this document; the "
                                 f"whole file was counted instead ({whole} words)"})
        out.extend(keep)
    if args.json:
        print(json.dumps({"caps": caps,
                          "counting": {"main_text": {"excludes": list(
                              DEFAULT_MAIN_TEXT_EXCLUDES if counting_excludes is None
                              else counting_excludes)}},
                          "rows": out}, indent=2))
    else:
        cap_text = (f"abstract <= {caps['abstract']} words, main text <= {caps['main text']} "
                    f"words" if caps["abstract"] is not None and caps["main text"] is not None
                    else "no abstract/main-text cap configured (counts recorded)")
        _cov = (f"{cover_min}-{cover_max} words" if cover_min is not None and cover_max is not None
                else f"at most {cover_max} words" if cover_min is None and cover_max is not None
                else f"at least {cover_min} words" if cover_min is not None else "")
        counting_note = ""
        if counting_excludes is not None \
                and set(counting_excludes) != set(DEFAULT_MAIN_TEXT_EXCLUDES):
            inside = [kind for kind in ("abstract", "methods", "references", "figure-legends")
                      if kind not in counting_excludes]
            if inside:
                counting_note = ("; main text counted with "
                                 + ", ".join(kind.replace("-", " ") for kind in inside)
                                 + " inside")
        print(f"venue: {venue}; caps: {cap_text}; cover letter "
              + (f"{_cov} in the persuading part (user preference)" if _cov
                 else "no preference configured")
              + (f"; TOTAL content <= {cover_total_max} words (operator cap)"
                 if cover_total_max is not None else "")
              + " -- words = non-space runs, newline = space"
              + counting_note)
        for r in out:
            mark = ("OUTSIDE-PREFERENCE" if r["section"] == "cover letter"
                    and not r.get("within_preference") else
                    "OVER" if r["over_limit"] else "ok")
            cap = f" cap={r['cap']}" if r["cap"] else ""
            note = f"  [{r['note']}]" if r["note"] else ""
            print(f"{r['file']} | {r['section']}: {r['words']} words{cap} -> {mark}{note}")
    if args.section == "cover-letter" and not any(r["section"] == "cover letter" for r in out):
        print("note: no cover letter detected in the requested file(s); --section cover-letter "
              "reported each file as 'not a cover letter' instead of an empty result",
              file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

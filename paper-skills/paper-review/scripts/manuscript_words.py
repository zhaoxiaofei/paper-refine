"""Text rules shared by the standalone review skill and pipeline M19 scan."""
from __future__ import annotations

import math
import re


def count_words(text: str) -> int:
    """Maximal runs of non-space characters; a newline is a space."""
    return len(re.findall(r"\S+", text or ""))


def lenient_cap(base: int, factor: float) -> int:
    """Largest integer word count within `base` relaxed by `factor`."""
    # floor(base*factor), tolerant of the float representation error that made
    # "100 words +15%" 114.99999999999999 -> 114 instead of 115. This must stay
    # consistent at the rounding boundary for both callers.
    return math.floor(float(base) * float(factor) + 1e-9)


# Inline verbatim is CODE, not prose (`\verb|x y|`, `\lstinline[opts]{x y}`):
# the command-name stripper removed only the command, so the delimiters and the
# code tokens would otherwise stay in the prose count.
TEX_INLINE_VERBATIM = re.compile(
    r"\\mintinline\*?(?:\[[^\[\]]*\]\s*)?\{[^{}]*\}\s*"
    r"(?:\{[^{}]*\}|(?P<md>[^\sA-Za-z0-9])(?:\\.|(?!(?P=md))[\s\S])*?(?P=md))")
TEX_INLINE_VERB = re.compile(
    r"\\(?:verb|lstinline)\*?(?:\[[^\[\]]*\]\s*)?"
    r"(?:\{[^{}]*\}|(?P<vd>[^\sA-Za-z0-9])"
    r"(?:\\.|(?!(?P=vd))[\s\S])*?(?P=vd))")


def strip_latex(text: str) -> str:
    """Prose of a LaTeX line: commands removed, math blanked, braces as spaces."""
    # The OPTIONAL arguments come first: the brace-only pattern left `[p.5]` and
    # `x` behind as prose for `\cite[p.5]{x}` (and for the `\citep[see][p.5]{x}`
    # form), so M19 counted phantom words on exactly the manuscripts whose
    # counting must be trusted.
    # `[a-zA-Z]*ref` covers the whole reference family (`\pageref{p12}`,
    # `\eqref{}`, `\autoref{}`, `\cref{}`): the bare `ref` alternative missed
    # every prefixed form, so `\pageref{p12}` left the phantom word `p12` in the
    # M19 count. An ESCAPED dollar (`\$5`) is a literal, not math: the math
    # pattern is lookbehind-guarded.
    # The CITATION family is matched case-insensitively and on BOTH sides of
    # `cite`: the biblatex-prefixed commands (`\nocite`, `\autocite`,
    # `\parencite`, `\textcite`, `\footcite`) and the capitalized natbib forms
    # (`\Cite`, `\Citet`, `\Citep`) used to leave their keys as prose.
    text = re.sub(r"\\(?:[a-zA-Z]*cite[a-zA-Z]*|[a-zA-Z]*ref|label|url|href)\s*"
                  r"(?:\[[^\[\]]*\]\s*)*\{[^{}]*\}", " ", text, flags=re.I)
    text = TEX_INLINE_VERBATIM.sub(" ", text)
    text = TEX_INLINE_VERB.sub(" ", text)
    # A colour, font or graphics-file argument is an identifier, not prose.
    text = re.sub(r"\\(?:includegraphics|includesvg|includepdf)\*?\s*"
                  r"(?:\[[^\[\]]*\]\s*)*\{[^{}]*\}", " ", text, flags=re.I)
    text = re.sub(r"\\textcolor\s*(?:\[[^\[\]]*\]\s*)*\{[^{}]*\}", " ", text,
                  flags=re.I)
    text = re.sub(r"\\colorbox\s*(?:\[[^\[\]]*\]\s*)*\{[^{}]*\}", " ", text,
                  flags=re.I)
    text = re.sub(r"\\fcolorbox\s*(?:\[[^\[\]]*\]\s*)*\{[^{}]*\}\s*\{[^{}]*\}",
                  " ", text, flags=re.I)
    text = re.sub(r"\\(?:color|pagecolor|definecolor)\s*(?:\[[^\[\]]*\]\s*)*"
                  r"(?:\{[^{}]*\}\s*){1,3}", " ", text, flags=re.I)
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


ABSTRACT_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary)\s*[:.\u2014\u2013-]?\s*$", re.I)


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


KEYWORDS = re.compile(
    # The optional section number is the one thing count_words.KEYWORDS accepts
    # that this twin used to reject: "2 Keywords: ..." was body text here and a
    # keyword boundary there, so the two M19 counters disagreed on the abstract.
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:key\s?words?)\s*(?:[:.\u2014\u2013-]|$)", re.I)


def heading_text(line: str) -> str:
    text = re.sub(r"^\s*#{1,6}\s+", "", (line or "").strip())
    m = re.match(r"^(\*\*|__|\*|_)(\S.*?)\1(.*)$", text)
    if m and m.group(2).strip():
        text = (m.group(2) + m.group(3)).strip()
    return text


def section_kind(line: str) -> str:
    """The M19 counting-convention kind of a boundary heading ("" when not one)."""
    text = heading_text(line)
    if not text:
        return ""
    for kind, pattern in SECTION_KIND_RES:
        if pattern.match(text):
            return kind
    return ""


def keyword_continuation(line: str) -> bool:
    """Does this line continue the keyword LIST, or start the body?

    A comma/semicolon list of short items is a continuation; a comma-bearing
    sentence is body; a short lowercase unpunctuated line is a list.
    """
    text = (line or "").strip()
    if not text:
        return False
    words = text.split()
    if "," in text or ";" in text:
        parts = [p.strip() for p in re.split(r"[,;]", text) if p.strip()]
        return (bool(parts) and not re.search(r"[.!?]\s*$", text)
                and (text[:1].islower() or len(parts[0].split()) <= 1)
                and 2 <= len(parts) <= 20 and len(words) <= 24
                and all(len(p.split()) <= 4 for p in parts))
    if re.search(r"[.!?]\s*$", text):
        return False
    return len(words) <= 4 and text[:1].islower()


def section_bounds(lines, abstract_end=None):
    """Return abstract and main heading boundaries, stripping an inline Abstract label."""
    n = len(lines)

    abs_start = abs_end = None
    inline_abs = False
    for i in range(n):
        heading = heading_text(lines[i])
        inline = INLINE_ABSTRACT_HEAD.match(heading)
        if inline:
            # Keep the remainder as the abstract's first paragraph; the
            # heading itself is not text.
            lines[i] = inline.group(1)
            abs_start, inline_abs = i, True
            break
        if ABSTRACT_HEAD.match(heading):
            abs_start = i + 1
            break
        # "Summary" is also a common CLOSING heading. Once a body heading has
        # appeared (Introduction/Background or any excluded section kind), a
        # later "Summary" is a concluding section, not a second abstract: the
        # old whole-document search took it as abs_start=end-of-document and
        # removed the body before it (the 2026-10-28 audit's F35).
        if MAIN_START.match(heading) or section_kind(heading):
            break
    if abs_start is not None:
        if abstract_end is not None:
            abs_end = max(abs_start, min(int(abstract_end), n))
        else:
            j = abs_start
            seen_text = inline_abs
            first_blank = None
            boundary = False
            while j < n:
                line = (lines[j] or "").strip()
                heading = heading_text(line)
                if SECTION_BOUND.match(heading) or \
                        MAIN_START.match(heading) or KEYWORDS.match(heading):
                    boundary = True
                    break
                if not line:
                    if seen_text and first_blank is None:
                        first_blank = j
                    j += 1              # leading blanks right after the heading
                    continue
                seen_text = True
                j += 1
            # A multi-paragraph abstract is legitimate; only a document
            # with no section boundary at all falls back to its first
            # blank line, so the later paragraphs are not charged to the
            # main text.
            if not boundary and first_blank is not None:
                j = first_blank
            abs_end = j
    main_start = None
    for i in range(n):
        if MAIN_START.match(heading_text(lines[i])):
            main_start = i + 1
            break
    return abs_start, abs_end, main_start


def main_text_lines(lines, bounds, excludes, *, normalize_keywords=False):
    """Return the start, included-line mask, and presence of an excluded heading."""
    abs_start, abs_end, main_start = bounds
    include_abstract = "abstract" not in excludes
    n = len(lines)
    if abs_start is not None:
        start = abs_start if include_abstract else abs_end
    elif main_start is not None:
        start = main_start
    else:
        start = 0
    # The abstract block ends ON the next heading line ("Introduction" in most
    # venues' Articles, which is written without a heading in the final layout).
    # Build the counted set line by line: an excluded section heading starts a
    # skip, and a later heading whose kind the venue does NOT exclude resumes
    # the count. Truncating at the first excluded heading dropped a Results or
    # Discussion section after a mid-paper Methods block even though the
    # profile says that kind is inside the count.
    included = [False] * n
    excluded_now = False
    end_found = False
    in_keyword_block = False
    for i in range(start, n):
        line = (lines[i] or "").strip()
        heading = heading_text(line)
        if normalize_keywords:
            line = heading
        if KEYWORDS.match(heading):
            # A Keywords line is a boundary, not a section kind: the generic
            # branch below reset `excluded_now` for it, which put the keyword
            # list (and any Methods prose after it) back into the main-text
            # count.
            in_keyword_block = True
            excluded_now = True
            continue
        if in_keyword_block:
            if not line:
                in_keyword_block = False
                excluded_now = False
                continue
            if keyword_continuation(line):
                continue                # a wrapped keyword list is not prose
            # A non-empty line that is not a keyword continuation ends the
            # block AND is body text. The old branch kept skipping every such
            # line until a blank or a heading, so a Brief Communication written
            # as "Keywords: ..." immediately followed by its body (no blank
            # line, no headings) lost the whole body and reported 0 main-text
            # words (the 2026-10-28 audit's F34).
            in_keyword_block = False
            excluded_now = False
        if SECTION_BOUND.match(heading) or \
                MAIN_START.match(heading):
            in_keyword_block = False
            kind = section_kind(heading)
            if kind and kind in excludes:
                excluded_now = True
                end_found = True
            else:
                excluded_now = False
            continue
        included[i] = not excluded_now
    return start, included, end_found


def count_main_text(lines, start, included, caption_spans, caption_counter=count_words):
    """Count the included prose and subtract captions only where the prose includes them."""
    body = " ".join(lines[i] for i in range(start, len(lines)) if included[i])
    caption_words = 0
    for first, last in caption_spans:
        span = [lines[i] for i in range(max(first, start), min(last, len(lines)))
                if included[i]]
        if span:
            caption_words += caption_counter(" ".join(span))
    return max(0, count_words(body) - caption_words), caption_words

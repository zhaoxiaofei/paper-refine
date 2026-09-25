#!/usr/bin/env python3
r"""Word counts for the abstract/main-text length rule (check id M19).

Stdlib-only, like the other bundled scripts. The counting rule is the
pipeline's: a word is a maximal run of NON-SPACE characters with a newline
treated as space, so `state-of-the-art` is ONE word and `2026` is ONE word.

    python3 count_words.py FILE [FILE ...] [--section whole|abstract|main-text|cover-letter|auto]
                                [--json] [--base-abstract N] [--base-main-text N]
                                [--venue-profile venue_profiles/<id>.json]

`auto` (the default) reports the abstract and the main text when the document
has a manuscript shape (an "Abstract" heading, or an Introduction/Main-text
heading); otherwise it reports the whole file and says so. The main text stops
at the first Methods / References / Figure-legends / Acknowledgements heading
(those are excluded from the journal's main-text limit) and subtracts detected
figure captions INSIDE that span, which the journal also excludes. `.tex`/`.ltx`
sources are read as LaTeX: the abstract environment's own `\end{abstract}` ends
the abstract (paragraph breaks inside it do not), and `\caption`/`\captionof`
text is a legend even though its "Figure N" label is added at typesetting time.

The default caps are the relaxed limits of the pipeline's DEFAULT venue profile
(nature-biotechnology Article): abstract <= 172 words (150 +15%) and main text
<= 3,750 words (3,000 +25%). Pass `--venue-profile venue_profiles/<id>.json`
to read the base, the margins and the cover-letter preference from the profile
the run is configured with (the pipeline's prompts state the same numbers), or
`--base-abstract` / `--base-main-text` for another content type's numbers with
the default margins. A profile that declares no limit produces counts with no
cap (`cap: null`, never "over the cap").
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ABSTRACT_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary)\s*[:.\u2014\u2013-]?\s*$", re.I)
MAIN_START = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:introduction|main text|background)\s*[:.\u2014\u2013-]?\s*$",
    re.I)
SECTION_BOUND = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary|keywords?|introduction|background|"
    r"results?|discussion|conclusions?|materials and methods|online methods?|methods?|"
    r"star methods|experimental procedures|"
    r"references?|bibliography|figure legends?|acknowledg\w*|author contributions?|"
    r"data availability|competing interests?|conflict of interest|funding|"
    r"supplementary (?:information|methods|figures|tables|notes))\s*[:.\u2014\u2013-]?\s*$", re.I)
MAIN_END = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:materials and methods|online methods?|methods?|"
    r"star methods|experimental procedures|"
    r"references?|bibliography|figure legends?|acknowledg\w*|author contributions?|"
    r"data availability|competing interests?|conflict of interest|funding|"
    r"supplementary (?:information|methods|figures|tables|notes))"
    r"\s*(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)
KEYWORDS = re.compile(r"^\s*(?:key\s?words?)\s*[:.\u2014\u2013-]", re.I)
CAPTION = re.compile(r"^\s*(?:(?:supplementary|extended\s+data|supp)\s+)?"
                     r"(?:figure|fig\.?)\s*S?\d+", re.I)
COVER_SALUTATION = re.compile(r"^\s*(?:dear\b|to the (?:editor|editors)\b)", re.I)
COVER_CLOSING = re.compile(
    r"^\s*(?:sincerely|yours (?:sincerely|faithfully|truly)|best regards|kind regards|regards|"
    r"with (?:best|kind) regards|thank you)\b", re.I)
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

ABSTRACT_RELAXATION = 1.15
MAIN_TEXT_RELAXATION = 1.25
COVER_LETTER_MIN = 300
COVER_LETTER_MAX = 500


def count_words(text: str) -> int:
    """Maximal runs of non-space characters; a newline is a space."""
    return len(re.findall(r"\S+", text or ""))


def lenient_cap(base: int, factor: float) -> int:
    """Largest integer word count within `base` relaxed by `factor`."""
    return int(float(base) * float(factor))


def _strip_latex(text: str) -> str:
    """Prose of a LaTeX line: commands removed, braces treated as spaces."""
    text = re.sub(r"\\(?:cite[a-zA-Z]*|ref|label|url|href)\s*\{[^{}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)
    return re.sub(r"\s+", " ", text.replace("{", " ").replace("}", " ")).strip()


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


def tex_lines(text: str):
    """(lines, abstract_end, caption_lines) for a LaTeX source.

    `lines` are heading/paragraph lines; `abstract_end` is the line index the
    abstract's text stops at (`\\end{abstract}`, so paragraph breaks inside the
    environment stay inside the abstract); `caption_lines` are the indices of
    the single lines holding a `\\caption`/`\\captionof` text (each such group
    becomes its own line, so subtracting that line removes exactly the legend's
    words), which the main-text count subtracts.
    """
    lines, captions, abstract_end = [], [], None
    raw_lines = (text or "").splitlines()
    i, n = 0, len(raw_lines)
    while i < n:
        raw = raw_lines[i]
        i += 1
        line = re.sub(r"(?<!\\)%.*$", "", raw).strip()
        if re.match(r"\\begin\{abstract\}", line):
            rest = re.sub(r"^\\begin\{abstract\}", "", line)
            rest = re.sub(r"\\end\{abstract\}.*$", "", rest).strip()
            lines.append("Abstract")
            if rest:
                lines.append(_line_text(rest))
            if "\\end{abstract}" in line:
                abstract_end = len(lines)
            continue
        if re.match(r"\\end\{abstract\}", line):
            abstract_end = len(lines)
            rest = re.sub(r"^\\end\{abstract\}", "", line).strip()
            if rest:
                lines.append(_line_text(rest))
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
                nxt = re.sub(r"(?<!\\)%.*$", "", raw_lines[i]).strip()
                i += 1
                group = f"{group}\n{nxt}"
                depth += _brace_delta(nxt)
            cap_text, after = _split_group(group)
            captions.append(len(lines))
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
    j = start
    seen_text = False
    while j < len(lines):
        line = lines[j].strip()
        if SECTION_BOUND.match(line) or KEYWORDS.match(line):
            break
        if not line:
            if seen_text:
                break
            j += 1
            continue
        seen_text = True
        j += 1
    return j


def caption_ranges(lines: list) -> list:
    """(start, end) line ranges of figure legends, continuation lines merged.

    Mirrors the pipeline's ``_caption_units_from_lines`` boundary rule: a legend
    continues while the next line is non-empty, is not a heading or a new
    caption, and (once the legend text ends in sentence-final punctuation) does
    not start a new flush-left paragraph.
    """
    ranges, i, n = [], 0, len(lines)
    while i < n:
        if not CAPTION.match(lines[i].strip()):
            i += 1
            continue
        j = i + 1
        while j < n:
            raw = lines[j]
            nxt = raw.strip()
            if not nxt or CAPTION.match(nxt) or SECTION_BOUND.match(nxt):
                break
            if lines[j - 1].rstrip().endswith((".", "!", "?")) and not raw[:1].isspace():
                break
            j += 1
        ranges.append((i, j))
        i = j
    return ranges


def sections(text: str, abstract_end=None, caption_lines=None) -> list:
    """[(section, words, note)] for a document's text lines.

    `abstract_end` and `caption_lines` are the explicit LaTeX boundaries from
    `tex_lines()`: the abstract stops there whatever blank lines it contains,
    and only captions inside the counted main-text span are subtracted.
    """
    lines = (text or "").splitlines()
    n = len(lines)
    abs_start = abs_end = None
    for i, raw in enumerate(lines):
        if ABSTRACT_HEAD.match(raw.strip()):
            abs_start = i + 1
            abs_end = (max(abs_start, min(int(abstract_end), n)) if abstract_end is not None
                       else _abstract_end(lines, abs_start))
            break
    main_start = None
    for i, raw in enumerate(lines):
        if MAIN_START.match(raw.strip()):
            main_start = i + 1
            break
    if abs_start is None and main_start is None:
        return [("whole file", count_words(text), "no abstract/main-text shape detected")]
    rows = []
    if abs_start is not None:
        rows.append(("abstract", count_words(" ".join(lines[abs_start:abs_end])), ""))
    start = abs_end if abs_end is not None else main_start
    if start is not None and start < n and SECTION_BOUND.match(lines[start].strip()):
        start += 1
    end, end_found = n, False
    for i in range(start or 0, n):
        if MAIN_END.match(lines[i].strip()):
            end, end_found = i, True
            break
    body = [ln for ln in lines[start or 0:end]
            if not (SECTION_BOUND.match(ln.strip()) or MAIN_START.match(ln.strip())
                    or KEYWORDS.match(ln.strip()))]
    offset = start or 0
    segment = lines[offset:end]
    if caption_lines is None:
        cap_ranges = caption_ranges(segment)
    else:
        cap_ranges = []
        for i in sorted(set(caption_lines)):
            if not (offset <= i < end):
                continue                       # outside the counted span
            rel = i - offset
            if cap_ranges and rel == cap_ranges[-1][1]:
                cap_ranges[-1][1] = rel + 1
            else:
                cap_ranges.append([rel, rel + 1])
    captions = sum(count_words(" ".join(segment[a:b])) for a, b in cap_ranges)
    words = max(0, count_words(" ".join(body)) - captions)
    notes = []
    if abs_start is None:
        notes.append("no Abstract heading; counted from the start of the document")
    if not end_found:
        notes.append("no Methods/References heading; counted to the end")
    if captions:
        notes.append(f"{captions} caption word(s) subtracted")
    rows.append(("main text", words, "; ".join(notes)))
    return rows


def is_cover_letter(text: str, name: str = "") -> bool:
    """A cover letter, by filename or opening salutation."""
    if "cover" in (name or "").lower():
        return True
    for line in (text or "").splitlines()[:12]:
        if COVER_SALUTATION.match(line.strip()):
            return True
    return False


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--section", choices=["auto", "whole", "abstract", "main-text", "cover-letter"],
                    default="auto")
    ap.add_argument("--base-abstract", type=int, default=150)
    ap.add_argument("--base-main-text", type=int, default=3000)
    ap.add_argument("--venue-profile", metavar="FILE",
                    help="venue profile JSON (venue_profiles/<id>.json): take the abstract/"
                         "main-text base and margins and the cover-letter preference from it")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    base_abstract, base_main = args.base_abstract, args.base_main_text
    rel_abstract, rel_main = ABSTRACT_RELAXATION, MAIN_TEXT_RELAXATION
    cover_min, cover_max = COVER_LETTER_MIN, COVER_LETTER_MAX
    venue = "nature-biotechnology (the default profile)"
    if args.venue_profile:
        try:
            profile = json.loads(Path(args.venue_profile).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"error: cannot read --venue-profile {args.venue_profile}: {e}",
                  file=sys.stderr)
            return 2
        limits = (profile or {}).get("length_limits") or {}
        venue = str((profile or {}).get("id") or args.venue_profile)

        def _limit(key, default_base, default_relaxation):
            spec = limits.get(key) or {}
            base = spec.get("base", default_base)
            relaxation = spec.get("relaxation", default_relaxation)
            return base, (None if relaxation is None else float(relaxation))

        base_abstract, rel_abstract = _limit("abstract", base_abstract, rel_abstract)
        base_main, rel_main = _limit("main_text", base_main, rel_main)
        cover = limits.get("cover_letter") or {}
        cover_min = cover.get("min", cover_min)
        cover_max = cover.get("max", cover_max)
        if len((profile or {}).get("length_limits") or {}) == 0 and "description" in (profile or {}):
            print(f"note: {args.venue_profile} carries no length_limits; using the default caps",
                  file=sys.stderr)
    caps = {"abstract": (lenient_cap(base_abstract, rel_abstract)
                         if base_abstract is not None and rel_abstract is not None else None),
            "main text": (lenient_cap(base_main, rel_main)
                          if base_main is not None and rel_main is not None else None)}
    out, failed = [], False
    for name in args.files:
        p = Path(name)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"error: cannot read {name}: {e}", file=sys.stderr)
            failed = True
            continue
        if p.suffix.lower() in TEX_EXTS:
            lines, abstract_end, caption_lines = tex_lines(text)
            prepared = "\n".join(lines)
            rows = ([("whole file", count_words(prepared),
                      "the whole file (requested with --section whole)")]
                    if args.section == "whole"
                    else sections(prepared, abstract_end=abstract_end,
                                  caption_lines=caption_lines))
        else:
            rows = ([("whole file", count_words(text),
                      "the whole file (requested with --section whole)")]
                    if args.section == "whole" else sections(text))
        if (args.section in ("auto", "cover-letter")) and is_cover_letter(text, p.name):
            rows = [("cover letter", cover_letter_words(text),
                     (f"persuading part only; the {cover_min}-{cover_max}-word range is the "
                      f"user's preference, not a venue limit" if cover_min is not None else
                      "persuading part only; this venue profile configures no cover-letter "
                      "preference"))]
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
                row["within_preference"] = (cover_min is None or cover_max is None
                                            or cover_min <= words <= cover_max)
                row["over_limit"] = False                 # the preference is not a cap
            keep.append(row)
        out.extend(keep)
    if args.json:
        print(json.dumps({"caps": caps, "rows": out}, indent=2))
    else:
        cap_text = (f"abstract <= {caps['abstract']} words, main text <= {caps['main text']} "
                    f"words" if caps["abstract"] is not None and caps["main text"] is not None
                    else "no abstract/main-text cap configured (counts recorded)")
        print(f"venue: {venue}; caps: {cap_text}; cover letter "
              + (f"{cover_min}-{cover_max} words in the persuading part (user preference)"
                 if cover_min is not None else "no preference configured")
              + " -- words = non-space runs, newline = space")
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

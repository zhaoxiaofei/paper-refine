from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import os
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from bisect import bisect_right
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import unescape as xml_unescape

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# A corpus's read-only EVIDENCE areas (`raw_data/`,
# and the human/LLM editors'-reviewers' feedback -- keep in step with
# `paper_pipeline.EVIDENCE_DIRNAMES`): never submission content, never a
# formatting/validation target.
RAW_DATA_DIRNAMES = ("raw_data",)
HUMAN_FEEDBACK_DIR = "human_review_feedback"
LLM_FEEDBACK_DIR = "llm_review_feedback"
EVIDENCE_DIRNAMES = RAW_DATA_DIRNAMES + (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR)

POLICY_DEFAULTS = {
    # FMT-IM4: a raster placed below this effective resolution is reported
    # (advisory). 0 disables it; a venue profile that states a number sets it.
    "min_image_dpi": 0,
    "min_image_dpi_source": "0 = not gated; the venue profile may state a number",
    # FMT-IM5: OCR the submitted figure rasters and compare their labels with the
    # manuscript's own vocabulary. Off only for a scan that must not spend the
    # OCR time; a missing tesseract is recorded as a gap by the rule itself.
    "figure_ocr": True,
    # FMT-IM6: the smallest visible text in a raster figure, measured at the
    # placed width. 0 = not gated (no venue rule recorded); Nature's guide says
    # 5 pt and Frontiers' says 8 pt, so a venue profile supplies the number and
    # its source. `figure_print_width_in` is the fallback for a standalone figure
    # file (a DOCX-embedded image uses its own wp:extent instead).
    "min_figure_text_pt": 0,
    "figure_print_width_in": 6.5,

    "journal_italics": "refs-only",     # refs-only | everywhere | off
    # Text-level consistency (rules FMT-T8a/T8d/T8e). "drop" deletes the redundant
    # journal name from an author-year citation so one format is used throughout;
    # the spelling/hyphenation policies normalize the minority variant in body text
    # only (reference titles and noun uses are never touched). All three record the
    # exact text edits they made; the fixer's verification checks that NOTHING else
    # in the document text changed.
    "citation_journal_names": "drop",   # drop | keep
    "term_spelling": "dominant",        # dominant | keep
    "term_hyphenation": "dominant",     # dominant | keep
    "quote_style": "keep",              # keep | straight | curly
    "caption_line": 240,                # twentieths of a point (240 = single)
    "caption_space": 200,               # before/after on every legend
    "heading_keep_with_next": True,
    "align_heading_sizes": False,       # drop direct sz overrides on headings
    "title_page_header": "suppress",    # suppress | keep
    "url_style": "plain",               # plain | keep-links
    "max_em_dashes_per_1000": 2.0,
    "max_empty_paragraph_run": 1,
    # Empty paragraphs the VENUE's own template prescribes -- signature
    # triples [own style, previous non-empty style, next non-empty style],
    # styles normalised to `H1`..`H9` when they are heading styles. Derived
    # from the official Word template by the pipeline (one list for the main
    # and the supplementary template) and carried into every session's
    # `format_policy.json`; [] means "nothing is known to be prescribed", and
    # an empty paragraph BEFORE the first non-empty paragraph (the title-page
    # spacer above a title) is always exempt.
    "empty_paragraph_slots": [],
    # An embedded image whose delivered width/height ratio differs from its own
    # pixel ratio by more than this is `FMT-IM1` and is corrected.
    "image_aspect_tolerance": 0.02,
    "strip_proofing_markers": True,
    "unlink_zotero_fields": False,
    # The local Zotero refresh (see `refresh_zotero_parts`): re-derive the
    # numbering from the document's own citation order, rebuild the
    # bibliography order, and reconcile the style stores -- automatically, at
    # every stage postcheck and at publication. `off` leaves the fields exactly
    # as authored and only reports them. `zotero_style` pins the CSL style the
    # stores are reconciled TO ("" = keep the newer store's style).
    "refresh_zotero_fields": True,
    # The reference-entry repairs (FMT-R1/R2/R3) a sibling .bib proves; `off`
    # reports the shapes and never touches the bibliography text.
    "repair_reference_entries": True,
    "zotero_style": "",
    "blank_page_tolerance": 0,
    # The venue's TABLE rule (see DISPLAY_PLACEMENTS / display_item_rows):
    # {} = this format policy declares no table rule, so the scan reports none.
    "tables": {},
    # The venue's FIGURE rule (see display_item_rows / FIGURE_CAPTION_RE): {} =
    # this format policy declares no figure rule, so the scan reports none.
    "figures": {},
    # Display-item NUMBERING ("citation" = first-mention order, the rule both
    # shipped venues state; "" = the venue states none, so FMT-O1 reports
    # nothing). The rule is about the venue's own numbering convention, so a
    # profile that does not declare it gets no rows.
    "numbering": "",
    # Another publisher's boilerplate the venue's profile lists as a leftover
    # (FMT-L1). [] = this profile declares none.
    "leftover_phrases": [],
    # Reference-entry policy (rules FMT-R1..R5). FMT-R1..R4 are objective shape
    # defects and always run; this block adds the venue's own preference.
    "references": {},                   # {"flag_preprints": true}
}


def _policy_flag(policy: dict, key: str, default: bool = True) -> bool:
    """A policy key as a boolean ("off"/"false"/"no"/"0" disable)."""
    if key not in (policy or {}):
        return default
    value = policy.get(key)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in ("off", "false", "no", "0")


JOURNAL_RE = re.compile(
    r"\b(?:Nature(?:\s+(?:Biotechnology|Methods|Genetics|Communications|Medicine))?|"
    r"Science|Cell(?:\s+(?:Reports|Systems|Research))?|"
    r"Genome\s+(?:Biology|Medicine|Research)|Nucleic\s+Acids\s+Research|Bioinformatics|"
    r"Brief(?:\.|ings)?\s+Bioinform(?:atics|\.)|Nat(?:\.|ure)\s+Methods|Genome\s+Biol\.|"
    r"PLOS\s+Comput\.\s+Biol\.|Annu\.\s+Rev\.\s+Genomics\s+Hum\.\s+Genet\.|Cell\s+Syst\.|"
    r"eLife|PNAS|BMC\s+Genomics|Front\.\s+Genet\.|Nat\.\s+Biotechnol\.|Lancet(?:\s+\w+)?|"
    r"EMBO\s+\w+|Scientific\s+Reports|Mol(?:\.|ecular)\s+Cell)\b")
URL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|https?://[^\s<>\"]+|www\.[^\s<>\"]+|\bdoi:[^\s]+", re.I)

PARA_TOKENS = re.compile(r"<w:p(?=[\s/>])|</w:p>")
RUN_TOKENS = re.compile(r"<w:r(?=[\s/>])|</w:r>")
# The BODY walker's tokens: the two block-level children of `<w:body>` a table
# rule has to see in DOCUMENT ORDER (a `w:p` holds no `w:tbl`, and a nested
# table inside a cell is part of its outer table).
BODY_BLOCK_TOKENS = re.compile(r"<w:(p|tbl)(?=[\s/>])")
ROW_TOKENS = re.compile(r"<w:tr(?=[\s/>])|</w:tr>")
CELL_TOKENS = re.compile(r"<w:tc(?=[\s/>])|</w:tc>")
# The opening arm must NOT match a self-closing `<w:t .../>`: without the
# `(?<!/)` guard the tag was read as an opening one and the lazy body ran to the
# NEXT run's `</w:t>`, so `text_of` returned literal markup and the writer
# escaped it into the first run, deleting the following run wrapper.
TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?(?<!/)>.*?</w:t>", re.S)
# A soft break/tab inside a paragraph (`<w:br/>`, `<w:cr/>`, `<w:tab/>`).
# `text_of` renders each as a NEWLINE: it is a delimiter, not content, so every
# text comparison still sees the same words AND the line-edge rules see the
# space a line edge carries. Dropping it made a three-line correspondence block
# read as one glued token (FMT-X2, 2026-10-15b).
BREAK_TOKENS = re.compile(r"<w:(?:br|cr|tab)(?=[\s/>])[^>]*/?>")
# Verbatim, non-text OOXML tokens: a non-breaking hyphen and a symbol glyph are
# glyphs, not characters of `text_of`, and must be copied through unchanged. A
# text writer that treated one as a `<w:t>` fragment emitted `<w:t><w:sym/>`
# with no closing tag and corrupted the whole document.
NON_TEXT_TOKENS = re.compile(r"<w:(?:noBreakHyphen|sym)(?=[\s/>])[^>]*/?>")
# The same walk, in DOCUMENT ORDER, for the callers that need both kinds of
# piece at once (the text writer splices a fragment's new text at its own
# offset, so a break counts as one character exactly like `text_of` says).
_FRAG_OR_BREAK_RE = re.compile(r"<w:t(?:\s[^>]*)?(?<!/)>.*?</w:t>"
                               r"|<w:(?:br|cr|tab|noBreakHyphen|sym)(?=[\s/>])[^>]*/?>",
                               re.S)
RUN_RE = re.compile(r"<w:r(?=[\s/>]).*?</w:r>|<w:r(?=[\s/>])[^>]*/>", re.S)
FIELD_CHAR_RE = re.compile(r"<w:fldChar[^>]*w:fldCharType=\"(\w+)\"[^>]*/?>")
INSTR_RE = re.compile(r"<w:instrText(?:\s[^>]*)?>.*?</w:instrText>", re.S)
# A paragraph can carry no text and still hold an anchor a reader needs: a
# footnote/endnote/comment reference, a bookmark, a simple field or a content
# control. Deleting that "empty" paragraph loses the target/structure.
ANCHOR_RE = re.compile(
    r"<w:(?:footnoteReference|endnoteReference|commentReference|"
    r"bookmarkStart|bookmarkEnd|fldSimple|sdt)(?=[\s/>])")
# Reading a DOCUMENT's sections: a legal self-closing `<w:sectPr .../>` (an
# empty section) must match as the element it is, never run to the NEXT
# section's closing tag -- that reported the wrong section's page-1 furniture.
SECT_READ_RE = re.compile(r"<w:sectPr(?=[\s/>])[^>]*/>|<w:sectPr(?=[\s>])[\s\S]*?</w:sectPr>")
PROOFERR_RE = re.compile(r"<w:proofErr[^>]*/>")
# Revision marks beyond the run-level w:ins/w:del pair: Word records tracked
# table/cell edits and property changes with their own elements, and a final
# package that carries only those is still carrying revision marks.
OTHER_REVISION_MARK_RE = re.compile(
    r"<w:(?:moveFrom|moveTo|cellIns|cellDel|cellMerge|"
    r"pPrChange|rPrChange|tblPrChange|trPrChange|tcPrChange|sectPrChange|"
    r"numberingChange)(?=[\s/>])")
DRAWING_RE = re.compile(r"<w:(?:drawing|pict|object|txbxContent)(?=[\s/>])")
PAGEBREAK_RE = re.compile(r"<w:br[^>]*w:type=\"page\"[^>]*/?>")
# A figure legend LABEL. The vocabulary matches the display rules' own caption
# labels (see DISPLAY_CAPTION_* below): the plain "Fig. 2 |"/"Figure 1." form
# plus the numbered supplementary forms the venues collect in a legends area --
# "Figure S1.", "Supplementary Fig. 4:", "Extended Data Figure 3 |". The old
# `\d+`-only pattern never saw "Figure S1.", so a supplementary legend kept the
# body style's spacing while its siblings were normalized (the 2026-10-14
# packages) and stayed invisible to the section/word model as well. A roman
# label needs at least TWO numeral characters: a single capital after "Figure"
# ("Figure C.", "Fig. I.") is a body sentence/panel, not figure 100.
LEGEND_RE = re.compile(
    r"^\s*(?:supplementary\s+|supp\.?\s+|extended\s+data\s+)?fig(?:ure)?s?\.?\s*"
    r"(?:S?\d+[A-Za-z]?|[IVXLC]{2,})\s*[|:.\u2014\u2013-]", re.I)
STRAIGHT_RE = re.compile(r"[\"']")
CURLY_RE = re.compile("[\u2018\u2019\u201c\u201d]")
EM, EN = "\u2014", "\u2013"


def log(*a):
    print(*a, file=sys.stderr)


def write_json(path, obj) -> None:
    """Write the tool's JSON reports with ONE formatting contract.

    Every CLI handler wrote `Path(...).write_text(json.dumps(..., indent=2,
    ensure_ascii=False))` itself (13 copies); a machine-readable report must not
    drift in indentation/encoding between subcommands.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def esc(text: str) -> str:
    return xml_escape(text or "")


def unesc(text: str) -> str:
    """XML text with entities decoded exactly once.

    `xml.sax.saxutils.unescape` only knows `&amp;`/`&lt;`/`&gt;`, but Word also
    writes `&#8212;`-style references for dashes and smart quotes; leaving those
    literal made the punctuation rules blind to them. The XML predefined
    entities `&quot;`/`&apos;` are decoded for the same reason: `esc()` escapes
    the resulting `&`, so a paragraph carrying `&quot;` used to be re-written as
    `&amp;quot;` and Word printed the reference itself.

    The decode is ONE pass: decoding `&amp;` first and then looking for numeric
    references decoded `&amp;#38;` (the literal text `&#38;`) into an ampersand.
    """
    named = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
    ref_re = re.compile(r"&(?:#x([0-9a-fA-F]+)|#(\d+)|(amp|lt|gt|quot|apos));")

    def repl(m):
        """The decoded character, or the literal reference when it is not valid.

        A hand-edited/LLM-edited `&#x110000;` (or an absurd decimal) raised
        ValueError/OverflowError straight out of the scanner: the scan never
        parses the XML, so nothing caught it and one bad reference took the
        whole formatting run down. Invalid references stay literal.
        """
        if m.group(3):
            return named[m.group(3)]
        try:
            cp = int(m.group(1) or m.group(2), 16 if m.group(1) else 10)
        except (ValueError, OverflowError):
            return m.group(0)
        # XML 1.0's Char production: a reference to NUL, a C0 control other
        # than tab/LF/CR, or a non-character such as U+FFFE is NOT a legal
        # character. Decoding it made `esc()` emit the raw byte and the fixed
        # document could not be parsed at all; the reference stays literal.
        if (cp in (0x9, 0xA, 0xD) or 0x20 <= cp <= 0xD7FF
                or 0xE000 <= cp <= 0xFFFD or 0x10000 <= cp <= 0x10FFFF):
            return chr(cp)
        return m.group(0)

    return ref_re.sub(repl, text or "")


def load_policy(path) -> dict:
    pol = dict(POLICY_DEFAULTS)
    if path:
        # Every other bad CLI input exits 2 with a message; a missing or
        # malformed --policy used to escape as a raw traceback.
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"error: cannot read --policy {path}: {e}", file=sys.stderr)
            raise SystemExit(2)
        if not isinstance(data, dict):
            print(f"error: --policy {path} must be a JSON object, not "
                  f"{type(data).__name__}", file=sys.stderr)
            raise SystemExit(2)
        pol.update(data)
    # A venue profile writes the measured rules as `image_dpi`/`figure_text`;
    # the formatter's own scalars are what the scans read. Derive them here so a
    # profile passed with --policy behaves the same as the pipeline's
    # format_policy (which does this derivation in format_policy_of).
    if not pol.get("min_image_dpi"):
        _dpi_block = pol.get("image_dpi")
        _dpi = (_dpi_block.get("min_dpi")
                if isinstance(_dpi_block, dict) else None)
        if _dpi:
            pol["min_image_dpi"] = float(_dpi)
    if not pol.get("min_figure_text_pt"):
        _ft_block = pol.get("figure_text")
        _pt = (_ft_block.get("min_pt") if isinstance(_ft_block, dict) else None)
        if _pt:
            pol["min_figure_text_pt"] = float(_pt)
    return pol


# --------------------------------------------------------------------------
# byte-level scanning (never re-serialize)
# --------------------------------------------------------------------------

def _spans(xml: str, tokens: re.Pattern) -> list:
    """(start, end, text) for balanced elements; nested elements each get a span."""
    out, depth, start = [], 0, None
    for m in tokens.finditer(xml):
        if m.group(0).startswith("</"):
            # A hand-edited package can carry an unmatched close tag; without
            # the clamp the depth goes negative and every later span is lost
            # (the closer never brings a -1 depth back to 0).
            depth = max(0, depth - 1)
            if depth <= 0 and start is not None:
                out.append((start, m.end(), xml[start:m.end()]))
                start, depth = None, 0
            continue
        tag_end = xml.find(">", m.start())
        if tag_end == -1:
            break
        if depth == 0:
            start = m.start()
        if xml[tag_end - 1] == "/":
            if depth == 0 and start is not None:
                out.append((start, tag_end + 1, xml[start:tag_end + 1]))
                start = None
            continue
        depth += 1
    if start is not None:
        out.append((start, len(xml), xml[start:]))
    return out


def paragraphs(xml: str) -> list:
    return _spans(xml, PARA_TOKENS)


def runs(frag: str) -> list:
    return _spans(frag, RUN_TOKENS)


def text_of(frag: str) -> str:
    """The text of `frag`, with each soft break/tab rendered as a NEWLINE.

    The offset table stays 1-for-1 with the piece each delimiter replaces, so a
    caller that maps a span back into `frag` keeps working, and the text a
    reader sees is the text these scans compare (a line break starts a new line
    for FMT-P4).
    """
    # DOCUMENT ORDER: a break sits BETWEEN two `<w:t>` parts (and can also sit
    # inside a run), so ONE walk over both kinds of token yields text and
    # delimiters as it meets them -- emitting the markup that lies between two
    # `<w:t>` parts would put the tags into the text.
    parts = []
    for m in _FRAG_OR_BREAK_RE.finditer(frag):
        tok = m.group(0)
        if BREAK_TOKENS.fullmatch(tok):
            parts.append("\n")
        elif tok.startswith("<w:noBreakHyphen"):
            # A non-breaking hyphen is a hyphen, not nothing: dropping it fused
            # `ten<w:noBreakHyphen/>year` into "tenyear".
            parts.append("-")
        elif tok.startswith("<w:sym"):
            # A symbol glyph has no portable character; keep ONE placeholder so
            # the surrounding words do not fuse.
            parts.append("\ufffd")
        else:
            parts.append(unesc(tok[tok.find(">") + 1:tok.rfind("<")]))
    return "".join(parts)


def has_drawing(frag: str) -> bool:
    return bool(DRAWING_RE.search(frag))


def has_field(frag: str) -> bool:
    """True when the fragment carries complex-field structure.

    A paragraph whose only content is a field run (`w:fldChar` begin/separate/
    end) or an `w:instrText` has NO `w:t` text and no drawing, but it is not an
    empty paragraph: deleting it destroys the field it belongs to. A real
    Zotero bibliography's closing `w:fldChar w:fldCharType="end"` lives alone
    in the no-text paragraph after the last reference, immediately before the
    next heading -- exactly the shape the stray-empty-paragraph rule used to
    delete, leaving the bibliography field unterminated.
    """
    return bool(FIELD_CHAR_RE.search(frag) or INSTR_RE.search(frag)
                or re.search(r"<w:fldSimple(?=[\s/>])", frag))


def has_anchor(frag: str) -> bool:
    """True when a no-text paragraph still carries a footnote/comment/bookmark."""
    return bool(ANCHOR_RE.search(frag))


def _property_element(frag: str, tag: str) -> str | None:
    """The WHOLE `<w:tag>` property element, balanced through nested copies.

    A tracked-formatting paragraph carries `<w:pPrChange><w:pPr>…</w:pPr>
    </w:pPrChange>` INSIDE its own pPr (and a run's rPr can carry
    `<w:rPrChange>`); the lazy regex used to stop at the inner closing tag, so a
    caller that spliced the returned block back replaced only its prefix and
    left the rest of the element dangling. `element_span` is the balanced reader
    the pPrChange-aware edits already use.
    """
    m = re.search(rf"<w:{tag}(?=[\s/>])", frag)
    if not m:
        return None
    s, e = element_span(frag, m.start(), tag)
    block = frag[s:e]
    if block.endswith("/>") or re.search(rf"</w:{tag}\s*>$", block):
        return block
    return None


def ppr_of(frag: str) -> str | None:
    # The self-closing form comes FIRST: `python-docx` writes an empty
    # properties element as `<w:pPr/>`, and the old single-lookahead pattern
    # matched it as "no pPr at all" -- every later insertion then ADDED a
    # second `<w:pPr>` (invalid OOXML) instead of filling the existing one.
    return _property_element(frag, "pPr")


def first_section_props(xml: str) -> str | None:
    """The FIRST `w:sectPr` in document order: the section that governs page 1.

    A manuscript with a separate title-page section carries one `w:sectPr` at
    the end of that section and the body's own at the end of `w:body`; the
    title page's header comes from the FIRST one, never the last.

    A self-closing `<w:sectPr .../>` is a legal empty section and must match as
    the element it is: the old pattern ran to the NEXT section's closing tag, so
    page 1 was reported with the following section's furniture.
    """
    m = SECT_READ_RE.search(xml)
    return m.group(0) if m else None


def rpr_of(frag: str) -> str | None:
    return _property_element(frag, "rPr")


def attr(frag: str | None, name: str) -> str | None:
    if not frag:
        return None
    m = re.search(rf'w:{name}="([^"]*)"', frag)
    return m.group(1) if m else None


def elem(frag: str | None, tag: str) -> str | None:
    """The raw `<w:tag .../>` or `<w:tag ...>…</w:tag>` element, if present."""
    if not frag:
        return None
    m = re.search(rf"<w:{tag}(?=[\s/>])[^>]*/>|<w:{tag}(?=[\s/>])[^>]*>.*?</w:{tag}>", frag, re.S)
    return m.group(0) if m else None


_CHILD_TAG_RE = re.compile(r"<(/?)([A-Za-z0-9:_.-]+)(?=[\s/>])([^>]*)>")


def child_elem(frag: str | None, tag: str) -> str | None:
    """The DIRECT child `<w:tag>` of `frag`, never a descendant.

    `elem()` searches the whole fragment, so `elem(ppr, "spacing")` returned a
    paragraph MARK's character spacing (`<w:pPr><w:rPr><w:spacing .../>`) as
    if it were the paragraph's line spacing -- the scanner reported FMT-T2
    rows that did not exist and the fixer wrote a paragraph-level element
    inside `w:rPr`, which is invalid OOXML.
    """
    if not frag:
        return None
    depth = 0
    start = None
    start_depth = None
    for m in _CHILD_TAG_RE.finditer(frag):
        closing, name, rest = m.group(1), m.group(2), m.group(3)
        self_closing = bool(closing == "") and rest.rstrip().endswith("/")
        if closing:
            depth -= 1
            if (start is not None and depth == start_depth
                    and name.split(":")[-1] == tag):
                return frag[start:m.end()]
            continue
        if depth == 1 and name.split(":")[-1] == tag:
            if self_closing:
                return m.group(0)
            start = m.start()
            start_depth = depth
        if not self_closing:
            depth += 1
    return None


def ppr_style(ppr: str | None) -> str | None:
    """The LIVE paragraph style (`pStyle` direct child of pPr).

    `elem()` searches descendants, so a tracked-formatting record
    (`w:pPrChange/w:pPr/w:pStyle`) was read as the paragraph's style: the
    scanner called a Normal paragraph a Heading and the fixer spliced
    keepNext/keepLines inside the revision record.
    """
    el = child_elem(ppr, "pStyle")
    return (attr(el, "val") or "1") if el is not None else None


def para_style(para: str) -> str | None:
    """The LIVE paragraph style of one `<w:p>` fragment."""
    return ppr_style(ppr_of(para))


def elem_val(frag: str | None, tag: str) -> str | None:
    el = elem(frag, tag)
    if el is None:
        return None
    return attr(el, "val") or "1"


def is_on(frag: str | None, tag: str) -> bool:
    v = elem_val(frag, tag)
    return v is not None and str(v).lower() not in ("0", "false", "off", "none")


def field_ranges(xml: str) -> list:
    """(start, end, instruction) of every complex field, in document order."""
    out, stack = [], []
    for m in FIELD_CHAR_RE.finditer(xml):
        kind = m.group(1)
        if kind == "begin":
            stack.append(m.start())
        elif kind == "end" and stack:
            start = stack.pop()
            instr = INSTR_RE.search(xml, start, m.end())
            raw = instr.group(0) if instr else ""
            out.append((start, m.end(),
                        unesc(raw[raw.find(">") + 1:raw.rfind("<")]).strip() if raw else ""))
    return out


def in_field(ranges: list, pos: int) -> str:
    for s, e, instr in ranges:
        if s <= pos < e:
            return instr[:44]
    return ""


def in_field_result(ranges: list, start: int, end: int) -> bool:
    """True when the text span [start, end) lies inside a field RESULT.

    Word (and Zotero's refresh) regenerates a field's result runs from the
    stored item, so a text edit inside them is lost on refresh while it still
    changes what the citation/reference currently shows -- the formatter
    reports such findings as field-protected and never applies them.
    """
    return any(start < r_end and r_start < end for r_start, r_end in ranges)


def _field_result_spans(xml: str) -> list:
    """[(result_start, result_end)] XML offsets of every complex field's RESULT.

    The stack walks begin/separate/end across the WHOLE xml, so a field whose
    result spans paragraphs (a Zotero bibliography field: begin+separate in the
    first entry paragraph, a lone end at the last) still yields one span.
    """
    out, stack = [], []
    for m in FIELD_CHAR_RE.finditer(xml):
        kind = m.group(1)
        if kind == "begin":
            stack.append({"sep": None})
        elif kind == "separate":
            if stack and stack[-1]["sep"] is None:
                stack[-1]["sep"] = m.end()
        elif kind == "end" and stack:
            frame = stack.pop()
            if frame["sep"] is not None:
                out.append((frame["sep"], m.start()))
    # `w:fldSimple` is the other live-field serialization: its result is the
    # element's own content, not a fldChar separate region. The spelling fixer
    # rewrote those results because this walk only knew complex fields.
    simple_stack = []
    for m in re.finditer(r"<w:fldSimple\b[^>]*>|</w:fldSimple>", xml):
        tag = m.group(0)
        if tag.startswith("</"):
            if simple_stack:
                out.append((simple_stack.pop(), m.start()))
        elif not tag.rstrip().endswith("/>"):
            simple_stack.append(m.end())
    return out


def field_result_text_ranges(para: str, doc_spans=None, para_start: int = 0) -> list:
    """[(text_start, text_end)] of every complex field's RESULT text in `para`.

    The offsets are in `text_of(para)` coordinates -- the space `hygiene_spans`
    and the fixer's text edits use. Only the runs AFTER the field's `fldChar
    separate` and before its `end` are a result; the instruction runs and the
    field characters themselves are outside. `doc_spans` is the document-wide
    `_field_result_spans(xml)` list for the xml `para` was sliced from and
    `para_start` that slice's offset: a field that STARTS in an earlier
    paragraph (the Zotero bibliography) protects its result paragraphs too,
    which the paragraph-scoped stack could not see.
    """
    runs, pos = [], 0
    for m in _FRAG_OR_BREAK_RE.finditer(para):
        tok = m.group(0)
        if BREAK_TOKENS.fullmatch(tok) or NON_TEXT_TOKENS.fullmatch(tok):
            # `text_of` renders each break/tab as one character and a
            # noBreakHyphen/sym as ONE glyph character too. Advancing only over
            # `<w:t>` shifted every later protected range, so a hygiene edit
            # could land inside a live Zotero field result.
            pos += 1
            continue
        text = unesc(tok[tok.find(">") + 1:tok.rfind("<")])
        runs.append((m.start(), m.end(), pos, pos + len(text)))
        pos += len(text)
    if doc_spans is None:
        spans = _field_result_spans(para)
    else:
        end = para_start + len(para)
        spans = [(max(s, para_start) - para_start, min(e, end) - para_start)
                 for s, e in doc_spans if s < end and para_start < e]
    out = []
    for s, e in spans:
        for xs, xe, ts, te in runs:
            if xs >= s and xe <= e:
                out.append((ts, te))
    return out


# ---- live-field inventory and continuity -----------------------------------
# Word stores a Zotero citation as a complex field: begin -> instrText
# ("ADDIN ZOTERO_ITEM CSL_CITATION {...}") -> separate -> visible result ->
# end; the bibliography is one ADDIN ZOTERO_BIBL field whose result spans the
# whole reference list. The functions below inventory those fields without
# re-serializing anything, report malformed structure, and compare one
# version's inventory with its successor's so no stage can silently drop the
# fields or leave their visible text behind as plain text.

ZOTERO_FIELD_ITEM_INSTR = "ADDIN ZOTERO_ITEM"
ZOTERO_FIELD_BIBL_INSTR = "ADDIN ZOTERO_BIBL"
# The parts that can carry a live field. Zotero's citations are complex fields
# in word/document.xml, but a note-style manuscript (and any Word conversion)
# can hold them in footnotes/endnotes -- and the template pass rewrites those
# parts too, so the inventory must see them or the gate protects nothing there.
ZOTERO_FIELD_PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
ZOTERO_FIELD_AUX_PARTS_RE = re.compile(r"word/(?:header|footer)\d*\.xml$|word/comments\.xml$")
ZOTERO_FIELD_TOKEN_RE = re.compile(
    r"<w:fldChar\b[^>]*?w:fldCharType=\"(begin|separate|end)\"[^>]*?/?>"
    r"|<w:instrText\b[^>]*>(.*?)</w:instrText>"
    r"|<w:t\b[^>]*>(.*?)</w:t>"
    r"|<w:fldSimple\b([^>]*)>(.*?)</w:fldSimple>",
    re.S)


def _zotero_field_kind(instr: str) -> str:
    up = (instr or "").upper()
    if ZOTERO_FIELD_ITEM_INSTR in up:
        return "item"
    if ZOTERO_FIELD_BIBL_INSTR in up:
        return "bibliography"
    if "ADDIN ZOTERO_" in up:
        return "zotero-other"
    return "other"


def _zotero_citation_id(instr: str) -> tuple:
    """(citationID | None, problem | None) for one ADDIN ZOTERO_ITEM field."""
    text = instr or ""
    m = re.search(r"CSL_CITATION\s*(\{)", text, re.S)
    if not m:
        return None, "the field instruction carries no CSL_CITATION JSON"
    try:
        # Decode the FIRST complete JSON value instead of requiring it to run to
        # the end of the instruction: Word may append a field switch
        # ("... } \* MERGEFORMAT"), and the anchored pattern then reported a
        # perfectly good citation as unparseable -- dropping that field from
        # every base-vs-output comparison.
        data, end = json.JSONDecoder().raw_decode(text[m.start(1):].strip())
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"the citation JSON does not parse ({e})"
    tail = text[m.start(1):].strip()[end:].strip()
    if tail and not tail.startswith("\\"):
        return None, (f"the field instruction carries text after the citation JSON "
                      f"({tail[:40]!r})")
    if not isinstance(data, dict):
        return None, "the citation JSON is not an object"
    cid = data.get("citationID")
    if not isinstance(cid, str) or not cid.strip():
        return None, "the citation JSON carries no citationID"
    return cid.strip(), None


def _zotero_field_identity(kind: str, instr: str) -> str:
    """A stable identity for a malformed field, for base-vs-next comparisons."""
    if kind == "item":
        cid, _problem = _zotero_citation_id(instr)
        if cid:
            return f"citationID {cid!r}"
    return f"instruction {(instr or '')[:60]!r}"


def zotero_field_report(xml: str) -> dict:
    """Inventory every complex field in one `word/document.xml` string.

    Each field entry carries `kind` (item|bibliography|zotero-other|other),
    `complete`, `has_separate`, `instr`, `citationID` (item fields),
    `visible_text` (the field RESULT runs) and byte `begin`/`end`. `errors`
    names every structural fault -- an unclosed begin, an `end`/`separate` or
    a Zotero instruction outside any field, a Zotero field without its
    separate, unparseable citation JSON, a missing or duplicate citationID --
    so a stage gate can compare one version with the next and refuse to ship a
    version whose fields got worse.
    """
    fields, errors, codes, stack = [], [], Counter(), []

    def fail(code: str, message: str) -> None:
        errors.append(f"[{code}] {message}")
        codes[code] += 1

    for m in ZOTERO_FIELD_TOKEN_RE.finditer(xml):
        raw = m.group(0)
        if raw.startswith("<w:fldSimple"):
            # The single-element field form: the instruction is the w:instr
            # ATTRIBUTE and the element's own content is the result. Word can
            # rewrite a complex field as fldSimple, so it must be inventoried --
            # a Zotero field invisible here is a field the gate cannot protect.
            attrs = m.group(4) or ""
            instr_m = re.search(r'w:instr="([^"]*)"', attrs)
            # An ATTRIBUTE also escapes the quote characters (`&quot;` around
            # every JSON key); `unesc` decodes text-node entities only.
            instr = (unesc(instr_m.group(1)).replace("&quot;", '"').replace("&apos;", "'")
                     if instr_m else "")
            fields.append({"begin": m.start(), "end": m.end(), "instr": [instr],
                           "separate": m.start(),
                           "result": [text_of(m.group(5) or "")]})
        elif raw.startswith("<w:fldChar"):
            kind = m.group(1)
            if kind == "begin":
                stack.append({"begin": m.start(), "end": None, "instr": [],
                              "separate": None, "result": []})
            elif kind == "separate":
                if stack:
                    if stack[-1]["separate"] is None:
                        stack[-1]["separate"] = m.start()
                    else:
                        # Name the field kind when it is Zotero's: the
                        # consumer (`zotero_structural_faults`) deliberately
                        # ignores a duplicate separator on an arbitrary Word
                        # field, so a message without the kind made a broken
                        # citation field print CLEAN.
                        _kind = _zotero_field_kind("".join(stack[-1]["instr"]))
                        _kind_note = (f"the {_kind} field; " if _kind != "other" else "")
                        fail("duplicate-separate",
                             f"a second field separator at byte {m.start()} is inside one "
                             f"field ({_kind_note}the first is at byte "
                             f"{stack[-1]['separate']}); Word renders the extra separator "
                             f"unpredictably")
                else:
                    fail("separate-outside-field",
                         f"a field separator at byte {m.start()} is outside any field")
            else:
                if stack:
                    frame = stack.pop()
                    frame["end"] = m.end()
                    fields.append(frame)
                else:
                    fail("end-outside-field",
                         f"a field end at byte {m.start()} has no matching begin")
        elif m.group(2) is not None:
            text = unesc(m.group(2))
            if stack:
                stack[-1]["instr"].append(text)
            elif "ADDIN ZOTERO_" in text.upper():
                fail("zotero-instr-outside-field",
                     f"a Zotero field instruction at byte {m.start()} is not inside a field")
        elif stack and stack[-1]["separate"] is not None:
            stack[-1]["result"].append(unesc(m.group(3)))
    for frame in stack:
        instr = "".join(frame["instr"]).strip()
        fail("unclosed-field",
             f"the {_zotero_field_kind(instr)} field beginning at byte {frame['begin']} "
             f"has no closing fldChar end "
             f"({_zotero_field_identity(_zotero_field_kind(instr), instr)})")
        fields.append(frame)

    out_fields = []
    for idx, frame in enumerate(fields):
        instr = "".join(frame["instr"]).strip()
        kind = _zotero_field_kind(instr)
        entry = {
            "index": idx, "kind": kind, "complete": frame["end"] is not None,
            "has_separate": frame["separate"] is not None,
            "instr": instr, "citationID": None,
            "visible_text": "".join(frame["result"]).strip(),
            "begin": frame["begin"], "end": frame["end"],
        }
        if kind != "other" and not entry["has_separate"]:
            fail("no-separate",
                 f"the {kind} field at byte {frame['begin']} has no fldChar separate "
                 f"({_zotero_field_identity(kind, instr)})")
        if kind == "item":
            cid, problem = _zotero_citation_id(instr)
            if problem:
                fail("bad-citation-json",
                     f"the citation field at byte {frame['begin']} "
                     f"(instruction {instr[:60]!r}): {problem}")
            else:
                entry["citationID"] = cid
        out_fields.append(entry)

    ids = [f["citationID"] for f in out_fields
           if f["kind"] == "item" and f["citationID"]]
    for cid in sorted({c for c, n in Counter(ids).items() if n > 1}):
        fail("duplicate-citation-id", f"citationID {cid!r} appears more than once")
    kinds = Counter(f["kind"] for f in out_fields)
    zotero_total = (kinds.get("item", 0) + kinds.get("bibliography", 0)
                    + kinds.get("zotero-other", 0))
    text = "\n".join(t for t in (text_of(p[2]) for p in paragraphs(xml)) if t.strip())
    return {
        "fields": out_fields, "errors": errors, "error_codes": dict(codes),
        "counts": {"item": kinds.get("item", 0),
                   "bibliography": kinds.get("bibliography", 0),
                   "zotero_other": kinds.get("zotero-other", 0),
                   "zotero": zotero_total, "other": kinds.get("other", 0),
                   "fields": len(out_fields),
                   "incomplete": sum(1 for f in out_fields if not f["complete"])},
        "text": text,
    }


def zotero_field_signature(report: dict) -> list:
    """The formatter's invariant: which live fields exist and how they are built."""
    sig = []
    for f in report.get("fields") or []:
        if f["kind"] == "other":
            continue
        sig.append((f["kind"], f.get("citationID") or "",
                    " ".join((f.get("instr") or "").split()),
                    f.get("visible_text") or "",
                    bool(f["complete"]), bool(f.get("has_separate"))))
    return sorted(sig)


def _merge_zotero_reports(reports: list) -> dict:
    """One inventory out of several parts' inventories (each is (part, report))."""
    fields, errors, codes, texts = [], [], Counter(), []
    counts = Counter()
    for part, rep in reports:
        for f in rep.get("fields") or []:
            merged = dict(f)
            merged["index"] = len(fields)
            merged["part"] = part
            fields.append(merged)
        errors.extend(f"{part}: {e}" for e in (rep.get("errors") or []))
        codes.update(rep.get("error_codes") or {})
        counts.update({k: int(v) for k, v in (rep.get("counts") or {}).items()})
        if rep.get("text"):
            texts.append(rep["text"])
    return {"fields": fields, "errors": errors, "error_codes": dict(codes),
            "counts": dict(counts), "text": "\n".join(texts)}


def zotero_report_for_docx(path) -> dict:
    """`zotero_field_report` for a .docx path, over EVERY part that can hold fields.

    Only word/document.xml was read once; a note-style manuscript keeps its
    citations in word/footnotes.xml (or endnotes.xml, a header/footer or a
    comment), where they were invisible to the stage gate -- zero fields means
    "all fields deleted" can never fire either. An unreadable package reports it.
    """
    try:
        with zipfile.ZipFile(path) as pkg:
            names = list(pkg.namelist())
            if "word/document.xml" not in names:
                # Every .docx has a main part; reading several parts must not
                # turn a package WITHOUT it into an empty "no fields" verdict
                # (that was the `unreadable DOCX package` report before).
                raise KeyError("word/document.xml")
            parts = [n for n in names
                     if n in ZOTERO_FIELD_PARTS or ZOTERO_FIELD_AUX_PARTS_RE.search(n)]
            xmls = [(n, pkg.read(n).decode("utf-8", "replace")) for n in parts]
    # RuntimeError is what `zipfile` raises for an ENCRYPTED entry and
    # NotImplementedError for an unsupported compression method (see
    # `analyse_package`): a password-protected .docx is unreadable like any
    # other, never a crash out of a reader that returns a fallback verdict.
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as e:
        return {"fields": [], "errors": [f"unreadable DOCX package: {type(e).__name__}: {e}"],
                "error_codes": {"unreadable-docx": 1},
                "counts": {"item": 0, "bibliography": 0, "zotero_other": 0, "zotero": 0,
                           "other": 0, "fields": 0, "incomplete": 0},
                "text": ""}
    if not xmls:
        return zotero_field_report("")
    reports = [(name, zotero_field_report(xml)) for name, xml in xmls]
    # The live-field PARITY rows travel with the inventory (FMT-Z1..Z5): the
    # stage gate compares them version to version, so a Word/Zotero refresh that
    # renumbers the text is visible even though every field is still "present".
    try:
        with zipfile.ZipFile(path) as pkg:
            style_parts = {n: pkg.read(n).decode("utf-8", "replace")
                           for n in ("word/settings.xml", "docProps/custom.xml")
                           if n in pkg.namelist()}
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        style_parts = {}
    parity = zotero_parity_rows_for_parts(xmls, zotero_style_ids(style_parts))
    if len(reports) == 1:
        merged = reports[0][1]
    else:
        merged = _merge_zotero_reports(reports)
    merged["parity_rows"] = parity
    return merged


def zotero_field_continuity_problems(base: dict, out: dict) -> dict:
    """Compare one DOCX version's field inventory with its successor's.

    This is the pipeline's stage gate. HARD errors:
      * the successor has a field-integrity fault the predecessor did not have
        (an unterminated field, a stray field char, unparseable citation JSON,
        a missing/duplicate citationID);
      * a predecessor that carried Zotero fields lost every one of them;
      * a baseline citation or bibliography field disappeared while its visible
        text is still in the document -- a field replaced by plain text.

    Allowed and reported: new fields, an edited field (same citationID, changed
    instruction or result) and the deletion of a field together with its visible
    text (the citation was really removed).
    """
    errors, warnings = [], []
    deleted, added, edited, plain_text = [], [], [], []
    base_fields = [f for f in base.get("fields") or [] if f["kind"] != "other"]
    out_fields = [f for f in out.get("fields") or [] if f["kind"] != "other"]

    # Compare the FAULTS, not just their per-code counts: byte offsets change
    # between versions, but the rest of the message identifies the field (its
    # kind, citationID and instruction) and the fault. This way "fixed one,
    # broke another of the same kind" is still a new error.
    def _err_sig(message: str) -> str:
        return re.sub(r"byte \d+", "byte #", message)

    base_err_sigs = Counter(_err_sig(e) for e in base.get("errors") or [])
    out_err_sigs = Counter(_err_sig(e) for e in out.get("errors") or [])
    new_sigs = out_err_sigs - base_err_sigs
    inherited_sigs = out_err_sigs & base_err_sigs
    repaired_sigs = base_err_sigs - out_err_sigs
    for sig, n in sorted(new_sigs.items()):
        errors.append(f"{n} NEW field-integrity error(s): {sig} "
                      f"(the previous version did not carry this fault)")
    if inherited_sigs:
        warnings.append(f"{sum(inherited_sigs.values())} field-integrity condition(s) are "
                        f"inherited from the previous version: "
                        + "; ".join(s[:90] for s in sorted(inherited_sigs)[:3])
                        + "; repair the missing structure if you can identify it")
    if repaired_sigs:
        warnings.append(f"{sum(repaired_sigs.values())} field-integrity condition(s) from the "
                        f"previous version are gone in this version")

    if base_fields and not out_fields:
        errors.append(f"ALL {len(base_fields)} Zotero field(s) were deleted (a version may add, "
                      f"edit or delete fields, but never remove every live field at once)")
    elif not base_fields and (base.get("error_codes") or {}):
        # The previous version carries Zotero structure that could NOT be
        # inventoried (a stripped fldChar run leaves its instruction behind): the
        # comparison below runs against an empty baseline, so "all fields were
        # deleted" can never fire. Report the degraded baseline instead of
        # comparing empty-to-empty in silence.
        warnings.append("the previous version's Zotero structure could not be inventoried "
                        "(" + ", ".join(sorted(base["error_codes"])) + "), so this comparison "
                        "has no field baseline; repair the baseline before trusting it")

    base_text, out_text = base.get("text") or "", out.get("text") or ""
    # ---- the live-field PARITY verdict (FMT-Z*) --------------------------------
    # Every field can be present and structurally sound while its cached
    # numbering is stale -- that is exactly what a Word/Zotero refresh rewrites.
    # A version that INTRODUCES a high-severity parity row is an error (the
    # refresh renumbered the citations inconsistently); one that replaces a
    # broken state with a consistent one is a recorded repair, never silent.
    # Compare the faults, not just their count (the structural comparison above
    # does the same): a version that repairs one stale field while breaking
    # another keeps the count identical and used to pass as "carried".
    def _high_parity_sigs(report: dict) -> Counter:
        return Counter(f"{r.get('rule')}|{r.get('location')}"
                       for r in (report.get("parity_rows") or [])
                       if r.get("rule") in ("FMT-Z1", "FMT-Z2", "FMT-Z4"))

    base_sigs, out_sigs = _high_parity_sigs(base), _high_parity_sigs(out)
    base_high, out_high = sum(base_sigs.values()), sum(out_sigs.values())
    new_sigs = out_sigs - base_sigs
    if new_sigs:
        sample = "; ".join(sig for sig, _n in sorted(new_sigs.items())[:3])[:240]
        errors.append(f"{sum(new_sigs.values())} NEW stale-citation fault(s) (FMT-Z1/Z2/Z4) "
                      f"that the previous version did not carry (it had {base_high}, this one "
                      f"has {out_high}) -- the citation numbering no longer agrees with the "
                      f"document's own citation order ({sample})")
    elif base_high and not out_high:
        warnings.append(f"the stale-citation faults of the previous version are GONE "
                        f"({base_high} -> 0): the field state is now consistent with the "
                        f"document's citation order")
    elif out_high:
        warnings.append(f"{out_high} stale-citation fault(s) (FMT-Z1/Z2/Z4) are carried in "
                        f"this version: a Word/Zotero refresh will renumber the text and the "
                        f"bibliography; refresh, re-run the scan, and only then flatten")

    def occurrences(hay: str, needle: str) -> int:
        if not needle:
            return 0
        # A numeric citation result ("19", "1,2", "10-12") must not match inside
        # a larger number ("2019", "100"); non-numeric results count as plain
        # substrings.
        pattern = re.escape(needle)
        if re.fullmatch(r"[0-9][0-9,;\-\u2013\u2014\s]*", needle):
            pattern = rf"(?<![0-9]){pattern}(?![0-9])"
        return len(re.findall(pattern, hay))

    base_items = {f["citationID"]: f for f in base_fields
                  if f["kind"] == "item" and f.get("citationID")}
    out_items = {f["citationID"]: f for f in out_fields
                 if f["kind"] == "item" and f.get("citationID")}
    missing_visible = Counter()
    for cid, f in base_items.items():
        if cid in out_items:
            o = out_items[cid]
            if (" ".join((f.get("instr") or "").split())
                    != " ".join((o.get("instr") or "").split())
                    or (f.get("visible_text") or "") != (o.get("visible_text") or "")):
                edited.append(cid)
            continue
        deleted.append(cid)
        vis = (f.get("visible_text") or "").strip()
        if vis:
            missing_visible[vis] += 1
    # A NEW field at another location may carry the same visible text (a
    # re-cited source). Its own result occurrence is a live field, not plain
    # text, so it is excluded from the count below.
    added_visible = Counter()
    for cid, f in out_items.items():
        if cid in base_items:
            continue
        vis = (f.get("visible_text") or "").strip()
        if vis:
            added_visible[vis] += 1
    for vis, gone in sorted(missing_visible.items()):
        base_n, out_n = occurrences(base_text, vis), occurrences(out_text, vis)
        if added_visible.get(vis):
            warnings.append(f"{added_visible[vis]} NEW field(s) carry the visible text {vis!r} "
                            f"that {gone} missing baseline citation(s) used to carry; keep the "
                            f"baseline citationID when the same citation is edited in place")
        if out_n - added_visible.get(vis, 0) > max(0, base_n - gone):
            plain_text.append({"visible_text": vis, "removed_fields": gone,
                               "occurrences_before": base_n, "occurrences_after": out_n})
            errors.append(
                f"field->plain-text replacement: {gone} citation field(s) with visible text "
                f"{vis!r} disappeared but that text still occurs {out_n}x in the new version "
                f"(was {base_n}x); re-create the live field from the baseline's citationID/"
                f"itemData, or remove the citation text")

    base_bib = [f for f in base_fields if f["kind"] == "bibliography"]
    out_bib = [f for f in out_fields if f["kind"] == "bibliography"]
    if base_bib and not out_bib:
        probe = "".join((" ".join((base_bib[0].get("visible_text") or "").split()))[:160].split())
        if probe and probe in "".join(out_text.split()):
            errors.append("the bibliography field disappeared but its reference text is still "
                          "in the document (field->plain-text replacement); re-create the "
                          "ADDIN ZOTERO_BIBL field")
        else:
            warnings.append("the bibliography field was deleted together with its reference text")
    elif base_bib and out_bib:
        # The bibliography has no citationID, so only its complete disappearance
        # was probed -- references could vanish from the list with no row at all.
        # A shrinking result is reported (a growing one is an ordinary revision).
        base_vis = " ".join((base_bib[0].get("visible_text") or "").split())
        out_vis = " ".join((out_bib[0].get("visible_text") or "").split())
        if base_vis and len(out_vis) < len(base_vis):
            warnings.append(f"the bibliography field's visible reference text shrank "
                            f"({len(base_vis)} -> {len(out_vis)} characters); confirm the "
                            f"reference list was edited as intended and not truncated")
    added = [cid for cid in out_items if cid not in base_items]
    return {"errors": errors, "warnings": warnings, "deleted": deleted, "added": added,
            "edited": edited, "plain_text": plain_text,
            "baseline_fields": len(base_fields), "output_fields": len(out_fields)}


def parse_styles(pkg: zipfile.ZipFile) -> dict:
    """styleId -> {sz, basedOn, type, spacing, i, iCs, b}.

    `i`/`iCs` are the OOXML tri-state toggles of the style's own rPr (True =
    italic, False = explicitly roman, None = inherited). They are what makes an
    italic that lives in a CHARACTER STYLE (`w:rStyle w:val="Emphasis"`) or in a
    paragraph style visible: a run can be italic without carrying `<w:i/>`
    itself, and only checking the run's direct rPr misses it. `b` is the same
    tri-state for bold, which the caption-block merge needs to keep a moved
    continuation run from inheriting a bold caption label's weight.
    """
    out = {}
    if "word/styles.xml" not in pkg.namelist():
        return out
    root = ET.fromstring(pkg.read("word/styles.xml"))
    defaults = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
    if defaults is not None:
        out["@docDefaults"] = {"i": _tri_state(defaults.find(W + "i")),
                               "iCs": _tri_state(defaults.find(W + "iCs")),
                               "b": _tri_state(defaults.find(W + "b"))}
    for st in root.iter(W + "style"):
        sid = st.get(W + "styleId") or ""
        rpr, ppr = st.find(W + "rPr"), st.find(W + "pPr")
        base = st.find(W + "basedOn")
        out[sid] = {
            "sz": (rpr.find(W + "sz").get(W + "val")
                   if rpr is not None and rpr.find(W + "sz") is not None else None),
            "i": _tri_state(rpr.find(W + "i")) if rpr is not None else None,
            "iCs": _tri_state(rpr.find(W + "iCs")) if rpr is not None else None,
            "b": (_tri_state(rpr.find(W + "b")) if rpr is not None else None),
            "basedOn": base.get(W + "val") if base is not None else None,
            "type": st.get(W + "type") or "",
            "spacing": (ppr.find(W + "spacing") if ppr is not None else None),
        }
    return out


def docx_style_ids(path: Path) -> list:
    """The style ids one DOCX package declares ([] when unreadable).

    Used by the venue-template conformance scan: a package restyled into the
    journal's template carries the template's style ids; one that still carries
    only its own styles does not.
    """
    try:
        with zipfile.ZipFile(path) as pkg:
            xml = pkg.read("word/styles.xml").decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return []
    return sorted(set(re.findall(r'w:styleId="([^"]+)"', xml)))


def _template_uses_even_odd(template: Path) -> bool:
    """True when the template's furniture depends on page parity.

    Either its settings.xml turns the parity switch on, or its own document
    references an even-typed header/footer part.
    """
    try:
        with zipfile.ZipFile(template) as tpkg:
            names = set(tpkg.namelist())
            settings = (tpkg.read("word/settings.xml").decode("utf-8", "replace")
                        if "word/settings.xml" in names else "")
            doc = tpkg.read("word/document.xml").decode("utf-8", "replace") \
                if "word/document.xml" in names else ""
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return False
    if "evenAndOddHeaders" in settings:
        return True
    sects = SECT_READ_RE.findall(doc)
    # Every section, not only the last, and any attribute order: Word writes
    # `w:type` before or after `r:id` depending on the producer.
    return any(re.search(r'<w:(?:header|footer)Reference\b[^>]*\bw:type="even"', sect)
               for sect in sects)


def docx_front_matter_report(path: Path, template: Path = None, containers=()) -> dict:
    """Template-conformance facts about a DOCX's front matter and headings.

    Used by the venue-template scanner to name the layout gaps a review/rewrite
    session must dispose: the first-page logo header, the page-number footer,
    the Title/AuthorList/Abstract/Keywords front matter, sub-sub-sections
    (Heading 3) and the Cell Press container headings.
    """
    try:
        with zipfile.ZipFile(path) as pkg:
            names = set(pkg.namelist())
            doc = pkg.read("word/document.xml").decode("utf-8", "replace")
            rels = (pkg.read("word/_rels/document.xml.rels").decode("utf-8", "replace")
                    if "word/_rels/document.xml.rels" in names else "")
            settings = (pkg.read("word/settings.xml").decode("utf-8", "replace")
                        if "word/settings.xml" in names else "")
            hf_parts = {n: pkg.read(n) for n in names
                        if n.startswith(("word/header", "word/footer")) and n.endswith(".xml")}
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return {}
    rel_map = {e["id"]: (e["type"], e["target"]) for e in _rels_entries(rels)}
    # The section that governs page 1 decides the FIRST-PAGE furniture (see
    # `first_section_props`): reading the last one let a two-section manuscript
    # whose page 1 was not the venue's layout report no gap at all.
    sects = SECT_READ_RE.findall(doc)
    sect = first_section_props(doc) or (sects[-1] if sects else "")
    refs = {}
    for m in re.finditer(r"<w:(header|footer)Reference\b[^>]*>", sect):
        typ = attr_of(m.group(0), "w:type")
        rid = attr_of(m.group(0), "r:id")
        if typ and rid:
            refs[(m.group(1), typ)] = rid

    def part(kind: str, typ: str) -> str:
        rid = refs.get((kind, typ))
        k, target = rel_map.get(rid, ("", ""))
        if k == kind and target and not target.startswith("http"):
            return target
        return ""

    first_header = part("header", "first") or part("header", "default")
    logo = False
    if first_header:
        name = f"word/{first_header}" if not first_header.startswith("word/") else first_header
        if name in hf_parts:
            hx = hf_parts[name].decode("utf-8", "replace")
            logo = bool(re.search(r"<w:drawing|<w:pict|<v:imagedata|<a:blip", hx))
    styles, texts = [], []
    for p in paragraphs(doc):
        t = text_of(p[2]).strip()
        if t:
            texts.append(t)
            styles.append(para_style(p[2]) or "")
    corr = next((p[2] for p in paragraphs(doc)
                 if _CORRESP_RE.match(text_of(p[2]).strip())), "")
    title_style = styles[0] if styles else ""
    author_style = next((styles[i] for i in range(1, min(4, len(styles)))
                         if "," in texts[i] or " and " in texts[i]), "")
    abstract_style = next((styles[i] for i, t in enumerate(texts)
                           if t.lower() == "abstract"), "")
    keywords_style = next((styles[i] for i, t in enumerate(texts)
                           if t.lower().startswith("keywords")), "")
    roles = template_style_roles(Path(template)) if template is not None else {}
    heading_level_of = {sid: lvl for lvl, sid in (roles.get("headings") or {}).items()}
    depth = int(roles.get("max_heading_level") or 2)
    deep = sum(1 for s in styles if heading_level_of.get(s, 0) > depth)
    container_rows = [t for t, s in zip(texts, styles)
                      if t in tuple(containers or _FOREIGN_CONTAINERS_DEFAULT)
                      and (s.startswith("Heading") or not s)]
    out = {"title_style": title_style, "author_style": author_style,
           "abstract_style": abstract_style, "keywords_style": keywords_style,
           "first_header": bool(first_header), "logo_header": logo,
           "first_footer": bool(part("footer", "first") or part("footer", "default")),
           "correspondence": bool(corr),
           "correspondence_bold": bool(corr and _label_is_bold(corr)),
           "correspondence_lines": (corr.count("<w:br") if corr else None),
           "even_odd": "evenAndOddHeaders" in settings,
           "deep_headings": deep,
           "heading3": sum(1 for s in styles if heading_level_of.get(s) == 3),
           "container_headings": container_rows}
    if template is None:
        return out
    title_id = roles.get("title")
    author_id = roles.get("author")
    rows = []
    if not logo:
        rows.append("the venue's first-page header/logo is missing")
    if not out["first_footer"]:
        rows.append("the venue's page-number footer is missing")
    if title_id and title_style != title_id:
        rows.append("the article title is not in the template's title style (centered)")
    if author_id and author_style != author_id:
        rows.append("the author list is not in the template's front-matter style (bold)")
    if abstract_style and abstract_style in heading_level_of:
        rows.append("Abstract is a numbered heading; the template keeps it as unnumbered "
                    "front matter")
    if any(t.strip().lower() == "keywords" for t in texts):
        rows.append("Keywords are a separate heading; the template uses one 'Keywords: ...' line")
    h1_id = (roles.get("headings") or {}).get(1)
    if h1_id and not any(s == h1_id for s in styles):
        rows.append("no section heading uses the template's Heading 1 style")
    if deep:
        rows.append(f"{deep} heading(s) sit deeper than the template's own heading depth "
                    f"-- flatten them")
    if _template_uses_even_odd(Path(template)) and not out["even_odd"]:
        rows.append("the template's even-page header/footer cannot render: the document does "
                    "not set <w:evenAndOddHeaders/>")
    tpl_doc, layout = "", {}
    try:
        with zipfile.ZipFile(template) as tpkg:
            tpl_doc = tpkg.read("word/document.xml").decode("utf-8", "replace")
        layout = _template_front_layout(tpl_doc)
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        layout = {}
    if layout:
        if corr:
            if not out["correspondence_bold"]:
                rows.append("the '* Correspondence:' label is not bold (the template's own is)")
            if layout.get("correspondence") \
                    and not re.search(r"<w:spacing\b", ppr_of(corr) or ""):
                rows.append("the correspondence block does not carry the template's own paragraph "
                            "spacing")
            if out["correspondence_lines"] is not None and out["correspondence_lines"] < 2:
                rows.append("the correspondence block is not the template's three-line form: "
                            "BOLD '* Correspondence:', the corresponding author, the email")
        affs = [p[2] for p in paragraphs(doc)
                if re.match(r"^\d+[A-Z]", text_of(p[2]).strip())]
        if affs and layout.get("affiliation_first") and not any(
                re.search(r"<w:spacing\b", ppr_of(a) or "") for a in affs[:2]):
            rows.append("the affiliation lines do not carry the template's before=240/after=0 "
                        "spacing")
    for container in container_rows:
        rows.append(f"source-template container heading {container!r} is not part of the "
                    f"venue's structure")
    out["rows"] = rows
    out["roles"] = {k: v for k, v in roles.items() if k != "headings"}
    return out


def _tri_state(node) -> bool | None:
    """True/False for an OOXML on/off toggle, None when the element is absent."""
    if node is None:
        return None
    val = node.get(W + "val")
    if val is None:
        return True
    return str(val).strip().lower() not in ("0", "false", "off")


def style_chain(styles: dict, sid: str | None) -> list:
    """[base, ..., derived] style ids for a style, cycle-safe."""
    chain, seen = [], set()
    while sid and sid in styles and sid not in seen:
        seen.add(sid)
        chain.append(sid)
        sid = styles[sid].get("basedOn")
    return list(reversed(chain))


def live_rpr(rpr: str | None) -> str:
    """The LIVE direct rPr: the revision history in `w:rPrChange` removed.

    `w:rPrChange` records the formatting the run had BEFORE a tracked change;
    it is not live formatting. Reading `<w:i>` anywhere inside the rPr reported
    a roman run as italic and made the mechanical fixer unable to clear its own
    row (it must not edit the change record).
    """
    return re.sub(r"<w:rPrChange\b.*?</w:rPrChange>", "", rpr or "", flags=re.S)


def effective_emphasis(styles: dict, para_style: str | None, run_style: str | None,
                       direct_rpr: str | None) -> bool:
    """Is this run effectively italic (by direct formatting, character style,
    paragraph style or document defaults)?

    Word's own precedence, lowest to highest: document defaults, the paragraph
    style chain, the run's character style chain, the run's direct rPr. Each
    level can set `w:i` and/or `w:iCs` (complex script) to on or explicitly off;
    the effective run is italic when either ends up on.
    """
    direct_rpr = live_rpr(direct_rpr)
    i_val, ics_val = None, None
    defaults = styles.get("@docDefaults") or {}
    i_val = defaults.get("i") if i_val is None else i_val
    ics_val = defaults.get("iCs") if ics_val is None else ics_val
    for sid in style_chain(styles, para_style or "Normal"):
        st = styles[sid]
        if st.get("i") is not None:
            i_val = st["i"]
        if st.get("iCs") is not None:
            ics_val = st["iCs"]
    for sid in style_chain(styles, run_style):
        st = styles[sid]
        if st.get("i") is not None:
            i_val = st["i"]
        if st.get("iCs") is not None:
            ics_val = st["iCs"]
    if direct_rpr:
        i_node = re.search(r"<w:i(?=[\s/>])[^>]*/?>", direct_rpr)
        ics_node = re.search(r"<w:iCs(?=[\s/>])[^>]*/?>", direct_rpr)
        if i_node:
            val = re.search(r'w:val="([^"]*)"', i_node.group(0))
            i_val = True if val is None else \
                str(val.group(1)).strip().lower() not in ("0", "false", "off")
        if ics_node:
            val = re.search(r'w:val="([^"]*)"', ics_node.group(0))
            ics_val = True if val is None else \
                str(val.group(1)).strip().lower() not in ("0", "false", "off")
    return bool(i_val) or bool(ics_val)


def run_is_italic(styles: dict, para_style: str | None, run: str) -> bool:
    """effective_emphasis() for one run fragment."""
    rpr = live_rpr(rpr_of(run))
    return effective_emphasis(styles, para_style, elem_val(rpr, "rStyle"), rpr)

def run_is_bold(styles: dict, para_style: str | None, run: str) -> bool:
    """Is this run effectively bold (direct rPr > character style > paragraph style)?

    The same precedence as `effective_emphasis`, for the `w:b`/`w:bCs` pair.
    """
    rpr = live_rpr(rpr_of(run))
    b_val = bcs_val = None
    defaults = styles.get("@docDefaults") or {}
    b_val = defaults.get("b") if b_val is None else b_val
    for sid in style_chain(styles, para_style or "Normal"):
        st = styles.get(sid) or {}
        if st.get("b") is not None:
            b_val = st["b"]
    for sid in style_chain(styles, elem_val(rpr, "rStyle")):
        st = styles.get(sid) or {}
        if st.get("b") is not None:
            b_val = st["b"]
    for node, key in ((r"<w:b(?=[\s/>])[^>]*/?>", "b"),
                      (r"<w:bCs(?=[\s/>])[^>]*/?>", "bCs")):
        m = re.search(node, rpr)
        if m:
            val = re.search(r'w:val="([^"]*)"', m.group(0))
            on = True if val is None else \
                str(val.group(1)).strip().lower() not in ("0", "false", "off")
            if key == "b":
                b_val = on
            else:
                bcs_val = on
    return bool(b_val) or bool(bcs_val)


# Words that may sit between a journal title and the italic words that wrongly
# continue its emphasis ("Nature Methods AND OTHER LEADING JOURNALS"). Articles
# ("a", "an") are deliberately NOT connectors: "published in Nature Methods, a
# KEY venue" must end the span at the comma, not swallow the emphasis.
EMPHASIS_CONNECTORS = {"and", "or", "of", "the", "in", "for", "to", "with", "as",
                       "such", "other", "its", "their", "by", "on", "&"}


def _words(text: str) -> list:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", text)]


def _has_word(text: str) -> bool:
    """True when the fragment carries a real word (>= 3 letters), not punctuation."""
    return any(len(w) >= 3 for w in _words(text))


def _has_lowercase_word(text: str) -> bool:
    """True when the fragment carries an ordinary lowercase prose word.

    This is what separates "Nature Methods AND OTHER LEADING JOURNALS" (prose
    folded into the journal's emphasis) from "Cell Syst." or "Cell Rep. Methods"
    (an abbreviated journal TITLE whose second word merely keeps the title's
    capitalisation): a title keeps its capitals, prose does not.
    """
    return any(w.islower() and len(w) >= 3 for w in _words(text))


def _title_only(text: str, name: str) -> bool:
    """True when the run carries the journal title and nothing else.

    Only case, whitespace and trailing sentence punctuation may differ: the old
    letters-only normalization made "Nature Methods 11, 1-2 (2024)" equal to
    "Nature Methods", so the fixer italicized the volume, pages and year too.
    """
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", str(s or "")).strip().strip(".,;:").casefold()
    return norm(text) == norm(name)


_J_BEFORE = set("([{<\u201c\"' \t\n\u2014\u2013")
_J_AFTER = set(")]}>.,;:!?\u201d\"' \t\n\u2014\u2013")


def journal_matches(text: str) -> list:
    """Journal titles in `text`, with real word boundaries around the match.

    `JOURNAL_RE` alone reads "Cell" out of "Cell-line", "(Single-Cell)" or
    "github.com/.../single-Cell-...", which would make the reference-list rules
    fire on ordinary prose and URLs. A journal TITLE stands as its own token.
    """
    out = []
    for m in JOURNAL_RE.finditer(text):
        before = text[m.start() - 1] if m.start() else " "
        after = text[m.end()] if m.end() < len(text) else " "
        if before in _J_BEFORE and after in _J_AFTER:
            out.append(m.group(0))
    return out


def _only_connectors(text: str) -> bool:
    """True when the fragment is whitespace, punctuation and connector words."""
    words = _words(text)
    return all(w.lower() in EMPHASIS_CONNECTORS for w in words)


def journal_emphasis_runs(styles: dict, para_style: str | None, para: str) -> dict:
    """Per-paragraph journal-emphasis analysis (one definition for scan and fix).

    Returns {"italic":    [(r0, r1, run, [journal names in the run])],
             "roman":     [(r0, r1, run, [journal names in the run])],
             "continuation": [(r0, r1, run, extra text, journal name)]}

    "continuation" is the real-world defect this exists for: a journal title is
    emphasised (often through Word's `Emphasis` CHARACTER STYLE, so the run
    carries no `<w:i/>` of its own) and the emphasis runs on over ordinary words
    -- "Nature Methods and other leading journals" -- because the phrase was
    formatted as one unit.

    The run offsets are relative to the paragraph, so the fixer can edit exactly
    the run it means (a paragraph can hold two identical run fragments).
    """
    out = {"italic": [], "roman": [], "continuation": []}
    info = []
    for r0, r1, run in runs(para):
        rtext = text_of(run)
        if not rtext:
            continue
        info.append((r0, r1, run, rtext, run_is_italic(styles, para_style, run)))
    for i, (r0, r1, run, rtext, ital) in enumerate(info):
        # A URL, DOI or e-mail can contain a journal-like word ("github.com/
        # Single-Cell-RNA-Seq"); never read a journal title out of one.
        probe = URL_RE.sub(lambda m: " " * len(m.group(0)), rtext)
        names = journal_matches(probe)
        if names and ital:
            out["italic"].append((r0, r1, run, names))
            extra = probe
            for name in names:
                extra = extra.replace(name, " ", 1)
            if _has_lowercase_word(extra):
                out["continuation"].append((r0, r1, run, extra.strip(), names[0]))
        elif names:
            out["roman"].append((r0, r1, run, names))
        if not names or not ital:
            continue
        # italic words that continue the same emphasis (the span does not end at
        # the title): connectors and whitespace may sit between them
        words_seen = 0
        for r0b, r1b, runb, textb, italb in info[i + 1:]:
            head = re.split(r"[.;:?!]", textb)[0]
            ends = bool(re.search(r"[.;:?!]", textb))
            if italb:
                if head.strip() and _has_lowercase_word(head) \
                        and not journal_matches(URL_RE.sub(" ", head)):
                    out["continuation"].append((r0b, r1b, runb, head.strip(),
                                                names[0]))
                words_seen += len(head.split())
            elif not _only_connectors(head):
                break
            if ends or words_seen > 6:
                break
    return out


def _rpr_set_emphasis(rpr: str | None, on: bool) -> tuple:
    """(new_rpr, changed) with an explicit italic ON/OFF override.

    The override is direct run formatting, which wins over a character style, a
    paragraph style and the document defaults -- the point when the italics come
    from `w:rStyle w:val="Emphasis"`. `w:i` must sit in schema order (after
    b/bCs, before caps/color/...), so the insert position respects that.
    """
    if rpr is None:
        rpr = "<w:rPr></w:rPr>"
    before = rpr
    # `w:rPrChange` holds the OLD formatting record of a tracked change. It is
    # not the live run formatting: deleting/inserting `w:i` there corrupts the
    # revision record while the run itself keeps its emphasis. Edit only the
    # live segments and leave every revision subtree byte-identical.
    _segs = re.split(r"(<w:rPrChange\b.*?</w:rPrChange>)", rpr, flags=re.S)
    for _i in range(0, len(_segs), 2):
        _seg = _segs[_i]
        _seg = re.sub(r"<w:i(?=[\s/>])[^>]*/>", "", _seg)
        _seg = re.sub(r"<w:iCs(?=[\s/>])[^>]*/>", "", _seg)
        _seg = re.sub(r"<w:i(?=[\s/>])[^>]*>.*?</w:i>", "", _seg, flags=re.S)
        _seg = re.sub(r"<w:iCs(?=[\s/>])[^>]*>.*?</w:iCs>", "", _seg, flags=re.S)
        _segs[_i] = _seg
    rpr = "".join(_segs)
    insert = "<w:i/>" if on else '<w:i w:val="0"/><w:iCs w:val="0"/>'
    if re.fullmatch(r"<w:rPr(?=[\s/>])[^>]*/>", rpr, re.S):
        # A self-closing properties element has no `</w:rPr>` tail to anchor
        # the insert on; splicing at len(rpr) - len("</w:rPr>") cut INTO the
        # tag and produced unparseable XML. Expand the element first.
        rpr = rpr[:rpr.rfind("/>")] + ">" + insert + "</w:rPr>"
        return rpr, rpr != before
    after_tags = ("caps", "smallCaps", "strike", "dstrike", "outline", "shadow", "emboss",
                  "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color",
                  "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u",
                  "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em",
                  "lang", "eastAsianLayout", "specVanish", "oMath")
    # The closing tag may carry whitespace before `>` (`</w:rPr >`, legal XML);
    # anchoring on the exact spelling spliced INTO the tag. Find the real end.
    _close = re.search(r"</w:rPr\s*>\s*$", rpr)
    at = _close.start() if _close else len(rpr)
    # `w:rPrChange` is the LAST child of a live rPr. Its own (old) rPr may
    # carry a schema-successor tag such as w:color even when the live rPr has
    # none; scanning the whole string would then splice the explicit override
    # INTO the revision record. Never insert past the start of the record.
    _change_at = rpr.find("<w:rPrChange")
    if _change_at != -1:
        at = min(at, _change_at)
    for tag in after_tags:
        m = re.search(rf"<w:{tag}(?=[\s/>])", rpr)
        if m:
            # The EARLIEST schema-successor wins, not the first tag in this
            # list that happens to be present: with <w:sz/> before <w:color/>
            # the old `break` inserted <w:i/> after sz, violating CT_RPr order.
            at = min(at, m.start())
    rpr = rpr[:at] + insert + rpr[at:]
    return rpr, rpr != before


def _emphasis_run(run: str, want: bool) -> str:
    """`run` with an explicit italic ON/OFF override (unchanged if already so)."""
    rpr = rpr_of(run)
    new_rpr, changed = _rpr_set_emphasis(rpr, want)
    if rpr is None:
        open_tag = re.match(r"<w:r(?=[\s/>])[^>]*>", run)
        if open_tag is None:
            return run
        return run[:open_tag.end()] + new_rpr + run[open_tag.end():]
    if changed:
        return run.replace(rpr, new_rpr, 1)
    return run


def split_run_text_span(run: str, start: int, end: int):
    """`(head, middle, tail)` runs, split at DECODED character offsets.

    `start`/`end` are offsets into `text_of(run)`. A parenthetical label can
    share a run with a prefix/suffix that is NOT part of the label; recording
    the whole run as the fix span used to restyle that neighbouring text too.
    The caller applies the emphasis to `middle` only, so every character
    outside the reported span keeps its own formatting.

    Returns None when the span cannot be mapped onto exactly one `w:t` (a run
    carrying a break, a symbol, several text nodes, or a middle that is empty):
    the caller then reports the row without a mechanical edit, rather than
    restyling bytes it cannot address.
    """
    tm = re.search(r"(<w:t(?=[\s>])[^>]*>)([\s\S]*?)(</w:t>)", run)
    if tm is None or len(re.findall(r"<w:t(?=[\s>])", run)) != 1:
        return None
    # A run may also carry a footnote/comment reference, a drawing or another
    # run-level child. Returning three copies of the run would replicate that
    # child (a labelled run with one footnote became three footnotes), so only
    # a run whose remaining content is its `w:rPr` is safe to split.
    if re.fullmatch(
            r"\s*<w:r(?=[\s/>])[^>]*>\s*"
            r"(?:<w:rPr(?=[\s/>])[^>]*/>|<w:rPr(?=[\s/>])[\s\S]*?</w:rPr>)?\s*"
            r"</w:r>\s*", run[:tm.start()] + run[tm.end():]) is None:
        return None
    text = unesc(tm.group(2))
    if text != text_of(run):
        return None
    start = max(0, min(int(start), len(text)))
    end = max(0, min(int(end), len(text)))
    if end <= start:
        return None
    def piece(txt: str) -> str:
        if not txt:
            return ""
        open_tag = tm.group(1)
        # A split can turn an internal space into a leading/trailing one; Word
        # strips an edge space from a w:t without xml:space="preserve".
        if (txt[:1].isspace() or txt[-1:].isspace()) \
                and "xml:space" not in open_tag:
            open_tag = open_tag[:-1] + ' xml:space="preserve">'
        return run[:tm.start()] + open_tag + xml_escape(txt) + tm.group(3) + run[tm.end():]

    return piece(text[:start]), piece(text[start:end]), piece(text[end:])


def style_sz(styles: dict, sid: str | None) -> str | None:
    seen = set()
    while sid and sid in styles and sid not in seen:
        seen.add(sid)
        if styles[sid]["sz"]:
            return styles[sid]["sz"]
        sid = styles[sid]["basedOn"]
    return None


def style_spacing(styles: dict, sid: str | None) -> dict:
    """Line/before/after a paragraph style inherits (None when unset)."""
    seen, out = set(), {}
    while sid and sid in styles and sid not in seen:
        seen.add(sid)
        sp = styles[sid]["spacing"]
        if sp is not None:
            for k in ("line", "before", "after"):
                if out.get(k) is None and sp.get(W + k) is not None:
                    out[k] = sp.get(W + k)
        sid = styles[sid]["basedOn"]
    return out


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

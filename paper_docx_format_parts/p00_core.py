from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import math
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
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import unescape as xml_unescape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
W = "{" + W_NS + "}"

# A corpus's read-only EVIDENCE areas (`raw_data/`,
# and the human/LLM editors'-reviewers' feedback -- keep in step with
# `paper_pipeline.EVIDENCE_DIRNAMES`): never submission content, never a
# formatting/validation target.
RAW_DATA_DIRNAMES = ("raw_data",)
HUMAN_FEEDBACK_DIR = "human_review_feedback"
LLM_FEEDBACK_DIR = "llm_review_feedback"
EVIDENCE_DIRNAMES = RAW_DATA_DIRNAMES + (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR)
# `<evidence area>.disabled` / `.off` is the documented OFF-SWITCH: the
# pipeline's `is_disabled_evidence_rel` treats the area as inert (not
# submission content, not readable evidence). The formatter tested exact names
# only, so a disabled area was still scanned, validated and repaired.
DISABLED_EVIDENCE_SUFFIXES = ("disabled", "off")


def is_evidence_part(part: str) -> bool:
    """True for an evidence-area path part, including its disabled form."""
    low = str(part or "").strip().lower()
    if low in EVIDENCE_DIRNAMES:
        return True
    return any(low.startswith(area + ".")
               and low[len(area) + 1:] in DISABLED_EVIDENCE_SUFFIXES
               for area in EVIDENCE_DIRNAMES)

def xml_guard_text(data: bytes) -> str:
    """Decoded text for the DTD/ENTITY refusal, honouring BOM-less UTF-16.

    `ElementTree` reads a BOM-less UTF-16 part from its own XML declaration, but
    a guard that only decoded UTF-16 when a BOM was present saw `<!DOCTYPE` /
    `<!ENTITY` as interleaved NULs and let the declaration through. Pick the
    endianness from the first non-NUL byte the way the XML declaration does.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "ignore")
    head = data[:400]
    if b"\x00" in head:
        enc = "utf-16-be" if head[:1] == b"\x00" else "utf-16-le"
        return data.decode(enc, "ignore")
    return data.decode("utf-8", "ignore")


def ooxml_part_text(data: bytes) -> str:
    """Decoded text of one untrusted OOXML XML part, honouring UTF-16.

    A legal OOXML part may be UTF-16 (BOM-bearing or, with its XML declaration,
    BOM-less). Decoding every content part with `.decode("utf-8", "replace")`
    turned such a part into NUL-interleaved text, so the regex readers matched
    nothing and returned an EMPTY, error-free inventory. Reuse the DTD guard's
    encoding picker; a plain UTF-8 part keeps the previous `replace` behaviour.

    The decoded part is then canonicalised: the WordprocessingML and
    Markup-Compatibility namespaces may be bound to ANY prefix in legal OOXML
    (`xmlns:word=...`, `xmlns:x=...`), while every reader in this module matches
    the conventional `w:`/`mc:` spellings. Canonicalising at the package-read
    boundary gives every reader one spelling, so an aliased package is read (and
    reported) instead of being silently certified clean. A part already using
    `w:`/`mc:` is returned byte-for-byte unchanged.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:400]:
        text = xml_guard_text(data)
    else:
        text = data.decode("utf-8", "replace")
    return canonicalize_ooxml_prefixes(text)


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
    # The venue's own text-style limits (FMT-T9c/T9i). {} = the venue profile
    # states no sentence/paragraph-length rule, so the scan records the long
    # text as an ADVISORY policy gap, never a finding (AGENTS rule 3). A venue
    # that DOES state a limit supplies
    # {"sentence_words": {"body": 46, ...}, "paragraph_words": 250}.
    "style_limits": {},
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
    r"eLife|PNAS|BMC\s+Genomics|Front\.\s+Genet\.|Nat\.\s+Biotechnol\.|"
    r"Lancet(?:\s+[A-Z][A-Za-z]*)?|"
    r"EMBO\s+[A-Z][A-Za-z]*|Scientific\s+Reports|Mol(?:\.|ecular)\s+Cell)\b")
URL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|https?://[^\s<>\"]+|www\.[^\s<>\"]+|\bdoi:[^\s]+", re.I)

PARA_TOKENS = re.compile(r"<w:p(?=[\s/>])|</w:p\s*>")
RUN_TOKENS = re.compile(r"<w:r(?=[\s/>])|</w:r\s*>")
# The BODY walker's tokens: the two block-level children of `<w:body>` a table
# rule has to see in DOCUMENT ORDER (a `w:p` holds no `w:tbl`, and a nested
# table inside a cell is part of its outer table).
BODY_BLOCK_TOKENS = re.compile(r"<w:(p|tbl)(?=[\s/>])")
ROW_TOKENS = re.compile(r"<w:tr(?=[\s/>])|</w:tr\s*>")
CELL_TOKENS = re.compile(r"<w:tc(?=[\s/>])|</w:tc\s*>")
# The opening arm must NOT match a self-closing `<w:t .../>`: without the
# `(?<!/)` guard the tag was read as an opening one and the lazy body ran to the
# NEXT run's `</w:t>`, so `text_of` returned literal markup and the writer
# escaped it into the first run, deleting the following run wrapper.
TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?(?<!/)>.*?</w:t\s*>", re.S)
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
_FRAG_OR_BREAK_PATTERN = re.compile(r"<w:t(?:\s[^>]*)?(?<!/)>.*?</w:t\s*>"
                                    r"|<w:(?:br|cr|tab|noBreakHyphen|sym)(?=[\s/>])[^>]*/?>",
                                    re.S)
# The tab-STOP definitions a paragraph carries in `<w:pPr><w:tabs>`: `<w:tab>`
# there is formatting (where the next tab lands), never a character of the text.
_TAB_STOP_SPANS_RE = re.compile(r"<w:tabs(?=[\s/>])[^>]*>.*?</w:tabs\s*>", re.S)
_ROOT_TAG_RE = re.compile(r"<\s*([A-Za-z_][\w:.-]*)(?=[\s/>])")


def _root_element_tag(frag: str) -> str:
    """The first element name in `frag` (`w:p`, `w:r`, `w:document`, ...)."""
    m = _ROOT_TAG_RE.search(frag or "")
    return m.group(1) if m else ""


def _vanish_run_spans(text: str) -> list:
    """(start, end) of runs whose rPr turns hidden text ON (`w:vanish`).

    Hidden text is not rendered by Word, so it is not a character a reader
    sees: counting it inflated word counts and made every FMT text rule judge
    text the submission does not show (F032). `w:vanish w:val="0"` is the
    explicit OFF spelling and is not hidden; `w:specVanish` is the same switch
    for a style's own text.
    """
    spans, depth, start = [], 0, None
    for m in re.finditer(r"<w:r(?=[\s/>])[^>]*>|</w:r\s*>", text or ""):
        tok = m.group(0)
        if tok.startswith("</"):
            depth = max(0, depth - 1)
            if depth == 0 and start is not None:
                frag = text[start:m.end()]
                if _run_rpr_hidden(frag):
                    spans.append((start, m.end()))
                start = None
            continue
        if tok.endswith("/>"):
            continue                     # a self-closing empty run owns no text
        if depth == 0:
            start = m.start()
        depth += 1
    return spans


def _run_rpr_hidden(run: str) -> bool:
    """True when one run's LIVE properties mark its text hidden.

    `w:rPrChange` records the formatting the run had BEFORE a tracked change:
    `w:vanish` inside it says the text USED to be hidden, not that it is hidden
    now. Scanning the whole run blanked a currently visible sentence whose
    previous formatting was hidden, so only the live rPr is read here.
    """
    run = re.sub(r"<w:rPrChange(?=[\s/>])[\s\S]*?</w:rPrChange\s*>", "",
                 run or "")
    for tag in re.findall(r"<w:(?:vanish|specVanish)(?=[\s/>])[^>]*/?>", run):
        value = attr(tag, "val")
        if value is None or str(value).strip().lower() not in ("0", "false", "off"):
            return True
    return False


class _FragOrBreakFinder:
    """`finditer` over text/break tokens that skips non-content tokens.

    Two tokens match the data-only pattern but are NOT characters a reader sees:
    a `<w:tab>` inside `<w:tabs>` (a tab-STOP definition, rendered as a spurious
    newline per stop) and every token inside a `<w:p>` nested in another `<w:p>`
    (a text-box paragraph that `paragraphs()` now emits as its own paragraph).
    Filtering them here keeps `text_of`, `field_result_text_ranges`, the field
    offset table and the fixer's `rewrite_text_spans` on one offset model.
    """

    pattern = _FRAG_OR_BREAK_PATTERN.pattern

    def finditer(self, frag: str):
        # Non-content spans (comments, the unrendered Fallback, tracked
        # deletions) are blanked to spaces first: the yielded tokens keep their
        # offsets into `frag`, and a hidden token is never a text character.
        text = _mask_noncontent(frag)
        if "<w:vanish" in text or "<w:specVanish" in text:
            text = _blank_spans(text, _vanish_run_spans(text))
        if _root_element_tag(text) == "w:r":
            # A RUN never owns a paragraph: any `<w:p>` inside a drawing it
            # carries is a text-box paragraph, not this run's text.
            nested = [(s, e) for s, e, _parent in _paragraph_offsets(text)]
        else:
            nested = _nested_paragraph_spans(text)
        stops = [(m.start(), m.end()) for m in _TAB_STOP_SPANS_RE.finditer(text)]
        for m in _FRAG_OR_BREAK_PATTERN.finditer(text):
            if any(a <= m.start() < b for a, b in nested):
                continue
            if stops and m.group(0).startswith("<w:tab") \
                    and any(a <= m.start() < b for a, b in stops):
                continue
            yield m


_FRAG_OR_BREAK_RE = _FragOrBreakFinder()
RUN_RE = re.compile(r"<w:r(?=[\s/>]).*?</w:r\s*>|<w:r(?=[\s/>])[^>]*/>", re.S)
FIELD_CHAR_RE = re.compile(
    # OOXML is XML: `w:fldCharType = "end"` (spaces around `=`) and
    # `w:fldCharType='end'` (single quotes) are legal spellings Word accepts.
    # The double-quote-only, no-space pattern read neither, so `has_field()` was
    # False for a lone closing-fldChar paragraph and the stray-empty rule
    # deleted the bibliography field's terminator; `field_ranges()` and the
    # Zotero inventory were blind to the same fields.
    r"<w:fldChar\b[^>]*?w:fldCharType\s*=\s*[\"'](\w+)[\"'][^>]*?/?>")
INSTR_RE = re.compile(r"<w:instrText(?:\s[^>]*)?(?<!/)>.*?</w:instrText\s*>", re.S)
# A paragraph can carry no text and still hold an anchor a reader needs: a
# footnote/endnote/comment reference, a bookmark, a simple field or a content
# control. Deleting that "empty" paragraph loses the target/structure.
ANCHOR_RE = re.compile(
    r"<w:(?:footnoteReference|endnoteReference|commentReference|"
    r"bookmarkStart|bookmarkEnd|fldSimple|sdt)(?=[\s/>])")
# OOXML math: its text lives in `<m:t>`, never in `<w:t>`, so every `<w:t>`-only
# walker read an equation-only paragraph as blank (see `has_math`).
MATH_RE = re.compile(r"<m:(?:oMath|oMathPara)(?=[\s/>])")
# Reading a DOCUMENT's sections: a legal self-closing `<w:sectPr .../>` (an
# empty section) must match as the element it is, never run to the NEXT
# section's closing tag -- that reported the wrong section's page-1 furniture.
# A LIVE section carries its tracked-change record at the end as
# `<w:sectPrChange><w:sectPr>...old...</w:sectPr></w:sectPrChange>`; the lazy
# arm stopped at that NESTED old section's close, so the "live" span held the
# obsolete header/footer references (and cut the element unbalanced). The
# lookahead skips a close that ends a change record, so the match ends at the
# LIVE section's own `</w:sectPr>`.
SECT_READ_RE = re.compile(
    r"<w:sectPr(?=[\s/>])[^>]*/>"
    r"|<w:sectPr(?=[\s>])[\s\S]*?</w:sectPr\s*>(?!\s*</w:sectPrChange\s*>)")
# The tracked-change record itself: its `<w:sectPr>` is the section properties
# BEFORE the edit and is not attached to the document any more.
_SECT_CHANGE_RE = re.compile(r"<w:sectPrChange(?=[\s/>])[\s\S]*?</w:sectPrChange\s*>")
PROOFERR_RE = re.compile(r"<w:proofErr[^>]*/>")
# Revision marks beyond the run-level w:ins/w:del pair: Word records tracked
# table/cell edits and property changes with their own elements, and a final
# package that carries only those is still carrying revision marks.
OTHER_REVISION_MARK_RE = re.compile(
    r"<w:(?:moveFrom|moveTo|cellIns|cellDel|cellMerge|"
    r"pPrChange|rPrChange|tblPrChange|trPrChange|tcPrChange|sectPrChange|"
    r"numberingChange)(?=[\s/>])")
DRAWING_RE = re.compile(r"<w:(?:drawing|pict|object|txbxContent)(?=[\s/>])")
# OOXML is XML: `w:type = "page"` (spaces around `=`) and
# `w:type='page'` (single quotes) are legal spellings Word accepts. The old
# double-quote-only, no-space pattern read neither, so `_break_only_paragraph`
# and the FMT-S1 scanner reported the document clean and never repaired it.
PAGEBREAK_RE = re.compile(r"<w:br\b[^>]*\bw:type\s*=\s*[\"']page[\"']")
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
    r"(?:S?\d+[A-Za-z]?|[IVXLC]{2,})\s*[|:.\u2014\u2013-](?=\s|$)", re.I)
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

    The report is written to an exclusive sibling and renamed into place: a
    direct `write_text` followed a symlink at the report path (clobbering an
    arbitrary file) and could leave truncated JSON after a crash (the
    2026-10-28 audit's F32).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(prefix="." + p.name + ".", suffix=".tmp",
                               dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    # The keys the caller actually WROTE, not merely the ones the merged dict
    # carries: POLICY_DEFAULTS seeds both scalars with 0, so the derivation
    # below cannot tell a default 0 from an explicit "0 = not gated" unless the
    # configured set is kept. `not pol.get(key)` made an explicit 0 look unset
    # and overwrote it with the venue's number, so the documented disable
    # switch was unusable whenever the profile also stated `image_dpi` /
    # `figure_text`.
    configured = set()
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
        configured = set(data)
    # A venue profile writes the measured rules as `image_dpi`/`figure_text`;
    # the formatter's own scalars are what the scans read. Derive them here so a
    # profile passed with --policy behaves the same as the pipeline's
    # format_policy (which does this derivation in format_policy_of, keyed on
    # the configured key's PRESENCE too).
    if "min_image_dpi" not in configured or pol.get("min_image_dpi") is None:
        _dpi_block = pol.get("image_dpi")
        _dpi = (_dpi_block.get("min_dpi")
                if isinstance(_dpi_block, dict) else None)
        if _dpi:
            pol["min_image_dpi"] = float(_dpi)
    if "min_figure_text_pt" not in configured or pol.get("min_figure_text_pt") is None:
        _ft_block = pol.get("figure_text")
        _pt = (_ft_block.get("min_pt") if isinstance(_ft_block, dict) else None)
        if _pt:
            pol["min_figure_text_pt"] = float(_pt)
    return pol


# --------------------------------------------------------------------------
# byte-level scanning (never re-serialize)
# --------------------------------------------------------------------------
# The tag walkers below are regex token walks, and a token regex cannot tell
# live markup from markup a READER never sees. Three classes were read as live
# content (and, for the fixer, edited as if they were):
#   * an XML comment / processing instruction -- `<!-- <w:p><w:t>retired</w:t>
#     </w:p> -->` supplied text, paragraphs and spelling rows, and a tag inside
#     a comment desynchronised every later paragraph span;
#   * the `mc:Fallback` branch of an `mc:AlternateContent` (Word renders Choice)
#     -- once NESTED, the lazy regex stopped at the inner element and the
#     unrendered OUTER Fallback was returned as manuscript prose;
#   * tracked deletions -- a run-level `w:del` / `w:moveFrom`, a table ROW whose
#     `w:trPr` carries `w:del`, and a CELL whose `w:tcPr` carries `w:cellDel`
#     keep their `<w:t>`/`<w:delText>` text, which Word's Final view hides.
# `_mask_noncontent` blanks them to same-length spaces before a walk, so every
# span found on the masked copy addresses the ORIGINAL bytes.
_XML_MISC_SPAN_RE = re.compile(r"<!--(?:[^-]|-(?!->))*-->|<\?(?:[^?]|\?(?!>))*\?>", re.S)


def _blank_spans(text: str, spans: list) -> str:
    """`text` with each span replaced by spaces, newlines preserved.

    The replacement keeps the byte length, so a span found on the blanked copy
    still addresses the original bytes; callers that splice keep working.
    """
    if not spans:
        return text
    out, pos = [], 0
    for a, b in sorted(spans):
        if b <= pos:
            continue
        a = max(a, pos)
        out.append(text[pos:a])
        out.append(re.sub(r"[^\n]", " ", text[a:b]))
        pos = b
    out.append(text[pos:])
    return "".join(out)


def _element_spans_by_name(xml: str, tag: str) -> list:
    """(start, end) of every balanced element whose LOCAL name is `tag`.

    `_CHILD_TAG_RE` skips XML comments and processing instructions, so a
    commented-out element is never live, and it balances nested copies of the
    SAME element -- a `w:tr` of a nested table, an `mc:AlternateContent` inside
    a text box -- which the old lazy single-match regexes did not. Every nested
    copy is returned (outer before inner when they share a start).
    """
    if not xml:
        return []
    spans, stack = [], []
    for m in _CHILD_TAG_RE.finditer(xml):
        closing, name, rest = m.group(1), m.group(2), m.group(3)
        if name is None or name.split(":")[-1] != tag:
            continue
        self_closing = (closing == "") and (rest or "").rstrip().endswith("/")
        if closing:
            if stack:
                spans.append((stack.pop(), m.end()))
        elif self_closing:
            spans.append((m.start(), m.end()))
        else:
            stack.append(m.start())
    spans.sort()
    return spans


def _mc_hidden_spans(xml: str) -> list:
    """XML spans of the `mc:Fallback` branches Word does NOT render.

    `text_of` reads only the branch Word renders (Choice when present, else
    Fallback), but the paragraph walker returned both branches' `w:p` elements
    (and the text-offset walk counted both branches' runs), duplicating text-box
    content and shifting every later field span. Only a Fallback that has a
    DIRECT-child Choice beside it is hidden: a nested AlternateContent inside the
    Fallback has its own Choice, and reading that one as the outer branch made
    the outer Fallback -- the branch Word does not render -- look visible.
    """
    out = []
    for s, e in _element_spans_by_name(xml, "AlternateContent"):
        block = xml[s:e]
        choice = _child_element_span(block, "Choice")
        fallback = _child_element_span(block, "Fallback")
        if choice is not None and fallback is not None:
            out.append((s + fallback[0], s + fallback[1]))
    return out


def _tracked_delete_spans(xml: str) -> list:
    """Spans whose content Word's Final view does not render (tracked deletes).

    A run-level `<w:del>` / `<w:moveFrom>` keeps its text (as `w:delText`, or as
    `w:t` from other producers); a deleted table ROW marks itself with a
    `<w:del/>` child of its own `w:trPr`, and a deleted CELL with a
    `<w:cellDel/>` child of its own `w:tcPr`. Reading them as live prose inflated
    every word / em-dash / spelling count, and a move was counted twice.
    """
    spans = list(_element_spans_by_name(xml, "del"))
    spans.extend(_element_spans_by_name(xml, "moveFrom"))
    for row_tag, prop_tag, mark in (("tr", "trPr", "del"),
                                    ("tc", "tcPr", "cellDel")):
        if f"<w:{mark}" not in xml:
            continue
        for s, e in _element_spans_by_name(xml, row_tag):
            props = child_elem(xml[s:e], prop_tag)
            if props and re.search(rf"<w:{mark}(?=[\s/>])", props):
                spans.append((s, e))
    return spans


def _mask_noncontent(xml: str) -> str:
    """`xml` with comments/PIs, hidden Fallback branches and tracked deletes blank.

    The blanking is length-preserving, so a walker over the result reports
    offsets that still address `xml` and callers that splice stay correct.
    """
    if not xml:
        return xml
    text = xml
    if "<!--" in text or "<?" in text:
        text = _XML_MISC_SPAN_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    spans = []
    if "<mc:AlternateContent" in text:
        spans.extend(_mc_hidden_spans(text))
    if "<w:del" in text or "<w:moveFrom" in text or "<w:cellDel" in text:
        spans.extend(_tracked_delete_spans(text))
    return _blank_spans(text, spans)


def _spans(xml: str, tokens: re.Pattern) -> list:
    """(start, end, text) for balanced elements; nested elements each get a span."""
    text = _mask_noncontent(xml)
    out, depth, start = [], 0, None
    for m in tokens.finditer(text):
        if m.group(0).startswith("</"):
            # A hand-edited package can carry an unmatched close tag; without
            # the clamp the depth goes negative and every later span is lost
            # (the closer never brings a -1 depth back to 0).
            depth = max(0, depth - 1)
            if depth <= 0 and start is not None:
                out.append((start, m.end(), xml[start:m.end()]))
                start, depth = None, 0
            continue
        tag_end = text.find(">", m.start())
        if tag_end == -1:
            break
        if depth == 0:
            start = m.start()
        if text[tag_end - 1] == "/":
            if depth == 0 and start is not None:
                out.append((start, tag_end + 1, xml[start:tag_end + 1]))
                start = None
            continue
        depth += 1
    if start is not None:
        out.append((start, len(text), xml[start:]))
    return out


def _paragraph_offsets(xml: str) -> list:
    """Return paragraph offsets and their parent starts in opening order."""
    text = _mask_noncontent(xml)
    offsets, stack = [], []
    for m in PARA_TOKENS.finditer(text):
        if m.group(0).startswith("</"):
            if stack:
                offsets[stack.pop()][1] = m.end()
            continue
        start = m.start()
        tag_end = text.find(">", start)
        if tag_end == -1:
            break
        parent = offsets[stack[-1]][0] if stack else None
        self_closing = text[tag_end - 1] == "/"
        end = tag_end + 1 if self_closing else len(text)
        offsets.append([start, end, parent])
        if not self_closing:
            stack.append(len(offsets) - 1)
    return offsets


def _nested_paragraph_spans(xml: str) -> list:
    """Return the ranges of paragraphs inside another paragraph."""
    return [(start, end) for start, end, parent in _paragraph_offsets(xml)
            if parent is not None]


def _text_box_paragraph_indices(xml: str, paras: list) -> set:
    """Identify text-box paragraphs even when their host is absent from paras."""
    if not xml:
        return set()
    starts = {start for start, _end in _nested_paragraph_spans(xml)}
    return {i for i, (start, _end, _para) in enumerate(paras) if start in starts}


def paragraphs(xml: str, *, include_empty_hosts: bool = False) -> list:
    hidden = _mc_hidden_spans(xml)
    offsets = _paragraph_offsets(xml)
    hosts = {parent for _start, _end, parent in offsets if parent is not None}
    out = []
    for start, end, _parent in offsets:
        if any(a <= start < b for a, b in hidden):
            continue
        para = xml[start:end]
        # A host with only text-box content contributes no body text.
        if not include_empty_hosts and start in hosts and not text_of(para):
            continue
        out.append((start, end, para))
    return out


def runs(frag: str) -> list:
    """Every run in `frag`, skipping the branches/paragraphs text_of does not read."""
    spans = _spans(frag, RUN_TOKENS)
    hidden = _mc_hidden_spans(frag) + _nested_paragraph_spans(frag)
    if not hidden:
        return spans
    return [sp for sp in spans if not any(a <= sp[0] < b for a, b in hidden)]


def text_of(frag: str) -> str:
    """The text of `frag`, with each soft break/tab rendered as a NEWLINE.

    The offset table stays 1-for-1 with the piece each delimiter replaces, so a
    caller that maps a span back into `frag` keeps working, and the text a
    reader sees is the text these scans compare (a line break starts a new line
    for FMT-P4).
    """
    # The walker masks what a reader never sees (comments, the unrendered
    # mc:Fallback branch, tracked deletions) BEFORE tokenizing, so the text and
    # its offsets stay aligned with `frag` -- substituting a branch here moved
    # every later offset.
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
    # A commented-out/PI-hidden `<w:drawing>` is not live content; the other
    # token predicates (`has_field`, `has_anchor`) already mask, and without it
    # the fixer refused to repair a real page-break paragraph (F036).
    return bool(DRAWING_RE.search(_mask_noncontent(str(frag or ""))))


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
    frag = _mask_noncontent(str(frag or ""))
    return bool(FIELD_CHAR_RE.search(frag) or INSTR_RE.search(frag)
                or re.search(r"<w:fldSimple(?=[\s/>])", frag))


def has_anchor(frag: str) -> bool:
    """True when a no-text paragraph still carries a footnote/comment/bookmark."""
    return bool(ANCHOR_RE.search(_mask_noncontent(str(frag or ""))))


def has_math(frag: str) -> bool:
    """True when the fragment carries OOXML math (a display equation is content).

    Math is `<m:oMath>`/`<m:oMathPara>` with `<m:t>` text, which the `<w:t>`
    text walkers cannot see: an equation-only paragraph therefore looked empty
    to the stray-empty and break-only predicates, and the mechanical fixer
    deleted the WHOLE paragraph -- equation included -- while its text-based
    self-verification reported nothing lost.
    """
    return bool(MATH_RE.search(_mask_noncontent(str(frag or ""))))


def _property_element_span(frag: str, tag: str) -> tuple[int, int] | None:
    """(start, end) of the WHOLE live `<w:tag>` property element, or None.

    A tracked-formatting paragraph carries `<w:pPrChange><w:pPr>…</w:pPr>
    </w:pPrChange>` INSIDE its own pPr (and a run's rPr can carry
    `<w:rPrChange>`); the lazy regex used to stop at the inner closing tag, so a
    caller that spliced the returned block back replaced only its prefix and
    left the rest of the element dangling. The walk below balances the nested
    copies of the SAME tag, which is how the pPrChange-aware edits read it.

    The scan runs over `_CHILD_TAG_RE`, the same tokenizer `child_elem` uses, so
    a COMMENTED-OUT property (`<!-- <w:pPr><w:pStyle .../></w:pPr> -->`) is not
    the live element: `re.search` + `element_span` used to return the commented
    copy, which made the scanner read the comment's style while the fixer (which
    now splices the paragraph's OWN pPr) repaired the live one -- the re-scan
    still saw the comment and `fix` rejected the whole document. Quoted `>`
    inside an attribute is handled there too, so an attribute value can no
    longer be mistaken for the tag's end. Callers that splice bytes need the
    SPAN, not the text: an identical element can also sit inside a comment
    before the live one, which is why `str.find` is not enough.
    """
    if not frag:
        return None
    start = None
    depth = 0
    for m in _CHILD_TAG_RE.finditer(frag):
        closing, name, rest = m.group(1), m.group(2), m.group(3)
        if name is None:                       # a comment or processing instruction
            continue
        short = name.split(":")[-1]
        self_closing = (closing == "") and (rest or "").rstrip().endswith("/")
        if start is None:
            if not closing and short == tag:
                if self_closing:
                    return m.start(), m.end()
                start, depth = m.start(), 1
            continue
        if short != tag:                       # a nested element of another name
            continue
        if closing:
            depth -= 1
            if depth <= 0:
                return start, m.end()
        elif not self_closing:
            depth += 1
    return None


def _property_element(frag: str, tag: str) -> str | None:
    """The WHOLE live `<w:tag>` property element, balanced through nested copies."""
    span = _property_element_span(frag, tag)
    return frag[span[0]:span[1]] if span is not None else None


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

    The tracked-change record (`w:sectPrChange`) inside the live section is
    blanked out of the returned text: its nested `<w:sectPr>` is the OLD section
    and its header/footer references are not attached any more, so a reader that
    looped over the returned refs let the obsolete rId win.
    """
    m = SECT_READ_RE.search(xml)
    if not m:
        return None
    return _strip_sect_changes(m.group(0))


def _strip_sect_changes(xml: str | None) -> str:
    """`xml` with every `<w:sectPrChange>` record blanked (length-preserving)."""
    if not xml or "<w:sectPrChange" not in xml:
        return xml or ""
    return _SECT_CHANGE_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), xml)


def rpr_of(frag: str) -> str | None:
    return _property_element(frag, "rPr")


def attr(frag: str | None, name: str) -> str | None:
    if not frag:
        return None
    # XML allows either quote character and whitespace around `=`; the old
    # double-quote-only pattern returned None for `w:val='Heading1'`, so
    # `elem_val` fell back to "1" and heading/style detection read the wrong
    # value. Both spellings are accepted here (single quotes are the second
    # alternative, never matched by the first).
    m = re.search(rf"w:{name}\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", frag)
    if not m:
        return None
    return m.group(1) if m.group(1) is not None else m.group(2)


def elem(frag: str | None, tag: str) -> str | None:
    """The LIVE `<w:tag .../>` or `<w:tag ...>…</w:tag>` element, if present.

    Revision records (`w:pPrChange`/`w:rPrChange`) preserve the property as it
    was BEFORE the edit. They are history, never live formatting: reading a
    `w:ind` from inside one reported a flush paragraph as indented and a
    `w:rFonts` from one entered the style survey. `child_elem` already takes
    the direct live child; this helper removes the change records before the
    descendant search so every `elem()` caller reads live formatting.
    """
    if not frag:
        return None
    frag = re.sub(r"<w:(pPrChange|rPrChange)\b[^>]*>.*?</w:\1>", "", frag, flags=re.S)
    # A comment/processing instruction inside the properties is not live
    # formatting either: `<!-- <w:ind w:firstLine="720"/> -->` before the live
    # `<w:ind w:firstLine="0"/>` was returned as the paragraph's indentation.
    # Masking is length-preserving, so the returned slice is the live element's
    # own bytes.
    masked = _mask_noncontent(frag)
    m = re.search(rf"<w:{tag}(?=[\s/>])[^>]*/>|<w:{tag}(?=[\s/>])[^>]*>.*?</w:{tag}>",
                  masked, re.S)
    return frag[m.start():m.end()] if m else None


_XML_MISC = r"<!--(?:[^-]|-(?!->))*-->|<\?(?:[^?]|\?(?!>))*\?>"
_XML_ATTRIBUTES = r"""(?:[^>"']|"[^"]*"|'[^']*')*"""
_CHILD_TAG_RE = re.compile(rf"{_XML_MISC}|<(/?)([A-Za-z0-9:_.-]+)(?=[\s/>])({_XML_ATTRIBUTES})>")

# Namespace declarations and QName-valued mc: attributes. `_CANON_TAG_RE` is
# deliberately wider than `_CHILD_TAG_RE`: it must also capture a self-closing
# tag with no attributes (`<w:p/>`) so its name can be canonicalised.
_CANON_TAG_RE = re.compile(
    rf"{_XML_MISC}|<(/?)([A-Za-z_][\w.\-]*(?::[A-Za-z_][\w.\-]*)?)({_XML_ATTRIBUTES})>", re.S)
_MC_QNAME_ATTRS = {"Ignorable", "MustUnderstand", "ProcessContent",
                   "PreserveElements", "PreserveAttributes", "Requires"}


def _iter_attrs(attrs: str):
    """Yield (name, value) for one tag's attribute text.

    A quoted value is consumed as a unit, so an `=` or a name-shaped fragment
    INSIDE a value (`w:instr="a b='c'"`) can never be read as another attribute.
    A self-closing tag's trailing `/` is not an attribute and ends the walk.
    """
    i, n = 0, len(attrs or "")
    while i < n:
        while i < n and attrs[i].isspace():
            i += 1
        if i >= n or attrs[i] == "/":
            break
        start = i
        while i < n and attrs[i] not in " \t\r\n=/>":
            i += 1
        name = attrs[start:i]
        if not name:                       # malformed: never loop forever
            i += 1
            continue
        while i < n and attrs[i].isspace():
            i += 1
        value = None
        if i < n and attrs[i] == "=":
            i += 1
            while i < n and attrs[i].isspace():
                i += 1
            if i < n and attrs[i] in "\"'":
                quote = attrs[i]
                i += 1
                vstart = i
                while i < n and attrs[i] != quote:
                    i += 1
                value = attrs[vstart:i]
                if i < n:
                    i += 1
            else:
                vstart = i
                while i < n and attrs[i] not in " \t\r\n/":
                    i += 1
                value = attrs[vstart:i]
        yield name, value


def _ooxml_ns_bindings(xml: str) -> dict:
    """prefix -> namespace URI from a part's own xmlns declarations.

    Comments and processing instructions are skipped by `_CANON_TAG_RE`, so a
    commented-out declaration is never read as live. The first binding of a
    prefix wins; a later re-binding of the same prefix is non-conforming OOXML
    and is not guessed at.
    """
    bindings = {}
    for m in _CANON_TAG_RE.finditer(xml):
        if m.group(2) is None:                 # comment / processing instruction
            continue
        for name, value in _iter_attrs(m.group(3)):
            if name == "xmlns":
                prefix = ""
            elif name.startswith("xmlns:"):
                prefix = name[len("xmlns:"):]
            else:
                continue
            bindings.setdefault(prefix, value or "")
    return bindings


def _canonical_name(name: str, renames: dict) -> str:
    """Canonical spelling of one element/attribute name."""
    if ":" in name:
        prefix, local = name.split(":", 1)
        return f"{renames.get(prefix, prefix)}:{local}"
    target = renames.get("")
    # The default namespace applies to ELEMENT names only; attribute handling
    # never passes an unprefixed name here (see `_canon_attr`).
    return f"{target}:{name}" if target else name


def _rename_qname_list(value: str, renames: dict) -> str:
    """Rename the prefixes inside one mc: QName/prefix-list attribute value."""
    out = []
    for token in str(value or "").split():
        if ":" in token:
            prefix, local = token.split(":", 1)
            out.append(f"{renames.get(prefix, prefix)}:{local}")
        else:
            out.append(renames.get(token, token))
    return " ".join(out)


def canonicalize_ooxml_prefixes(xml: str) -> str:
    """Spell the WordprocessingML/markup-compatibility namespaces as `w:`/`mc:`.

    Namespace prefixes are arbitrary in legal OOXML: a producer may declare
    `xmlns:word=<WordprocessingML>` and write `<word:p>`, or bind the markup
    compatibility namespace to `x:`. Every reader in this module matches the
    conventional `w:`/`mc:` tokens, so such a package was read as zero
    paragraphs / empty text and reported clean -- a false negative, not a
    documented Word-only assumption. Rewriting the prefixes ONCE at the part-read
    boundary (`ooxml_part_text`) gives every reader (and every offset-taking
    fixer) one coordinate space.

    Only bindings to those two namespaces are touched; a part already using the
    conventional spelling is returned unchanged. Canonical declarations are
    added when an alias/default binding was the only declaration, and QName-list
    values (`mc:Ignorable`, `mc:ProcessContent`, ...) are updated so no value
    names a prefix that no longer exists.
    """
    if not xml or "xmlns" not in xml:
        return xml
    bindings = _ooxml_ns_bindings(xml)
    if not bindings:
        return xml
    renames, rename_decls, drop_decls, add_decls = {}, {}, set(), {}
    for target, uri in (("w", W_NS), ("mc", MC_NS)):
        current = bindings.get(target)
        if current is not None and current != uri:
            # The canonical spelling is taken by a different namespace; do not
            # invent a second declaration for the same prefix.
            continue
        canonical_is = current == uri
        default_is = bindings.get("") == uri
        aliases = [p for p, u in bindings.items()
                   if u == uri and p not in ("", target)]
        if default_is:
            renames[""] = target
        if canonical_is:
            for prefix in aliases:
                drop_decls.add(prefix)
                renames[prefix] = target
        elif aliases:
            first = aliases[0]
            rename_decls[first] = target
            renames[first] = target
            for prefix in aliases[1:]:
                drop_decls.add(prefix)
                renames[prefix] = target
        elif default_is:
            add_decls[target] = uri
    if not renames and not drop_decls:
        return xml

    def attr_value(value):
        # The walker re-emits values in double quotes. A value that arrived in
        # single quotes may legally contain a raw `"`; escape it so the rewrite
        # cannot produce malformed XML.
        return str(value).replace('"', "&quot;")

    def rewrite_attrs(attrs):
        trimmed = attrs.strip()
        self_closing = trimmed.endswith("/")
        body = trimmed[:-1] if self_closing else trimmed
        parts = []
        for name, value in _iter_attrs(body):
            if name == "xmlns":
                parts.append(f'xmlns="{attr_value(value)}"')
                continue
            if name.startswith("xmlns:"):
                alias = name[len("xmlns:"):]
                if alias in drop_decls:
                    continue
                if alias in rename_decls:
                    parts.append(f'xmlns:{rename_decls[alias]}="{attr_value(value)}"')
                else:
                    parts.append(f'{name}="{attr_value(value)}"')
                continue
            target = _canonical_name(name, {p: t for p, t in renames.items() if p})
            if target.startswith("mc:") and target.split(":", 1)[1] in _MC_QNAME_ATTRS:
                value = _rename_qname_list(value, renames)
            if value is None:
                parts.append(target)
            else:
                parts.append(f'{target}="{attr_value(value)}"')
        out = (" " + " ".join(parts)) if parts else ""
        if self_closing:
            out += " /"
        return out

    def canon_tag(m):
        if m.group(2) is None:             # comment / processing instruction
            return m.group(0)
        closing, name, attrs = m.group(1), m.group(2), m.group(3)
        new_name = _canonical_name(name, renames)
        new_attrs = rewrite_attrs(attrs)
        return f"<{closing}{new_name}{new_attrs}>"

    out = _CANON_TAG_RE.sub(canon_tag, xml)
    missing = {p: u for p, u in add_decls.items()
               if not re.search(rf"\bxmlns:{re.escape(p)}\s*=", out)}
    if missing:
        insert = "".join(f' xmlns:{p}="{esc(u)}"' for p, u in sorted(missing.items()))
        # The first tag-shaped match can be the XML declaration or a comment;
        # a namespace declaration belongs on the first ELEMENT start tag. Doing
        # this with `count=1` stopped at the declaration and left every `w:`
        # name unbound, so a legal default-namespace part failed to parse.
        for m in _CANON_TAG_RE.finditer(out):
            if m.group(2) is None or m.group(1):
                continue
            out = (f"{out[:m.start()]}<{m.group(2)}{insert}{m.group(3)}>"
                   f"{out[m.end():]}")
            break
    return out


def _child_element_span(frag: str | None, tag: str) -> tuple[int, int] | None:
    """Offsets of the direct child named tag."""
    if not frag:
        return None
    depth = 0
    start = None
    start_depth = None
    for m in _CHILD_TAG_RE.finditer(frag):
        closing, name, rest = m.group(1), m.group(2), m.group(3)
        if name is None:
            continue
        self_closing = bool(closing == "") and rest.rstrip().endswith("/")
        if closing:
            depth -= 1
            if (start is not None and depth == start_depth
                    and name.split(":")[-1] == tag):
                return start, m.end()
            continue
        if depth == 1 and name.split(":")[-1] == tag:
            if self_closing:
                return m.span()
            start = m.start()
            start_depth = depth
        if not self_closing:
            depth += 1
    return None


def child_elem(frag: str | None, tag: str) -> str | None:
    """The direct child of frag, excluding descendant properties."""
    span = _child_element_span(frag, tag)
    return frag[span[0]:span[1]] if span is not None else None


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


def _fld_simple_instruction(tag: str) -> str:
    """The `w:instr` ATTRIBUTE of a `w:fldSimple` element, decoded once.

    XML allows either quote character and whitespace around `=`; the old
    double-quote-only pattern read a legal `w:instr='...'` as an EMPTY
    instruction, so the live-field fence could not see the citation (F028).
    """
    value = attr(tag, "instr")
    if value is None:
        return ""
    return (unesc(value).replace("&quot;", '"').replace("&apos;", "'")).strip()


def field_ranges(xml: str) -> list:
    """(start, end, instruction) of every live field, in document order.

    Both serializations Word uses are inventoried: the complex field
    (`w:fldChar` begin/separate/end) and the single-element `w:fldSimple`.
    `in_field` is the fixer's fence, so reading only the complex form left a
    simple field's cached result unprotected although `_field_result_spans()`
    already protects it.
    """
    out, stack = [], []
    scan = _mask_noncontent(xml)
    for m in FIELD_CHAR_RE.finditer(scan):
        kind = m.group(1)
        if kind == "begin":
            stack.append(m.start())
        elif kind == "end" and stack:
            start = stack.pop()
            instr = INSTR_RE.search(scan, start, m.end())
            raw = instr.group(0) if instr else ""
            out.append((start, m.end(),
                        unesc(raw[raw.find(">") + 1:raw.rfind("<")]).strip() if raw else ""))
    simple_stack = []
    for m in re.finditer(r"<w:fldSimple\b[^>]*>|</w:fldSimple\s*>", scan):
        tag = m.group(0)
        if tag.startswith("</"):
            if simple_stack:
                start, opening = simple_stack.pop()
                out.append((start, m.end(), _fld_simple_instruction(opening)))
        elif tag.rstrip().endswith("/>"):
            # A legal EMPTY simple field (`<w:fldSimple w:instr="..."/>`) was
            # skipped here although `has_field()` treats it as a field: the
            # paragraph was protected from deletion while the field was absent
            # from this inventory and from the live-field signature. Its result
            # is empty, but the field itself must be accounted for.
            out.append((m.start(), m.end(), _fld_simple_instruction(tag)))
        else:
            simple_stack.append((m.start(), tag))
    out.sort(key=lambda r: r[0])
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
    scan = _mask_noncontent(xml)
    for m in FIELD_CHAR_RE.finditer(scan):
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
    for m in re.finditer(r"<w:fldSimple\b[^>]*>|</w:fldSimple\s*>", scan):
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
    hidden = _mc_hidden_spans(para)
    for m in _FRAG_OR_BREAK_RE.finditer(para):
        tok = m.group(0)
        if any(a <= m.start() < b for a, b in hidden):
            # The raw walk used to count the Fallback branch's text, which
            # `text_of` does not return: every protected range after an
            # AlternateContent was shifted by the fallback's length.
            continue
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
# Header/footer parts can carry a VENUE name (`header_venue_default.xml`), not
# only Word's numbered one; the narrow `\d*` here missed every descriptive part
# the scanner reads, so zotero-check could report CLEAN with a live field in it.
ZOTERO_FIELD_AUX_PARTS_RE = re.compile(
    r"word/(?:header|footer)(?:\d+|[_-][A-Za-z0-9_\-]*)?\.xml$|word/comments\.xml$")
ZOTERO_FIELD_TOKEN_RE = re.compile(
    r"<w:fldChar\b[^>]*?w:fldCharType\s*=\s*[\"'](begin|separate|end)[\"'][^>]*?/?>"
    # A self-closing `<w:t/>`/`<w:instrText/>` is an EMPTY element, never an
    # opening tag: without the `(?<!/)` guard the lazy body ran to the next
    # run's closing tag and fed markup into the field result.
    r"|<w:instrText\b[^>]*?(?<!/)>(.*?)</w:instrText\s*>"
    r"|<w:t\b[^>]*?(?<!/)>(.*?)</w:t\s*>"
    # The SELF-CLOSING simple field must come FIRST: the paired alternative's
    # `([^>]*)>` would otherwise swallow its closing `/>` as an attribute and
    # run its lazy body to the NEXT simple field's closing tag (one field read
    # as two, with the wrong instruction).
    r"|<w:fldSimple\b([^>]*?)/>"
    r"|<w:fldSimple\b([^>]*)>(.*?)</w:fldSimple\s*>"
    # A soft break/tab is a text delimiter in a field result too: `text_of()`
    # renders it as a newline, so the inventory must not join the words it
    # separates ("Smith\n2020" is not "Smith2020").
    r"|<w:(?:br|cr|tab)\b[^>]*/?>",
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

    scan = _mask_noncontent(xml)
    for m in ZOTERO_FIELD_TOKEN_RE.finditer(scan):
        raw = m.group(0)
        if raw.startswith("<w:fldSimple"):
            # The single-element field form: the instruction is the w:instr
            # ATTRIBUTE and the element's own content is the result. Word can
            # rewrite a complex field as fldSimple, so it must be inventoried --
            # a Zotero field invisible here is a field the gate cannot protect.
            # A self-closing element is the legal EMPTY form: it has the
            # instruction and no result, and it must not be dropped from the
            # inventory (group 4) nor read as opening a paired field.
            self_closing = m.group(4) is not None
            attrs = (m.group(4) if self_closing else m.group(5)) or ""
            body = "" if self_closing else (m.group(6) or "")
            # An ATTRIBUTE also escapes the quote characters (`&quot;` around
            # every JSON key); `unesc` decodes text-node entities only. The
            # value is read through the shared attribute parser: XML permits
            # BOTH quote characters and whitespace around `=`, and the old
            # double-quote-only pattern made a legal single-quoted citation
            # invisible to this inventory (F028).
            _instr_raw = attr(attrs, "instr")
            instr = (unesc(_instr_raw).replace("&quot;", '"').replace("&apos;", "'")
                     if _instr_raw is not None else "")
            fields.append({"begin": m.start(), "end": m.end(), "instr": [instr],
                           "separate": m.start(),
                           "result": [text_of(body)]})
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
        elif raw.startswith(("<w:br", "<w:cr", "<w:tab")):
            if stack and stack[-1]["separate"] is not None:
                stack[-1]["result"].append("\n")
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
            # Untrusted input budget: this reader used to decompress every
            # field-carrying part unbounded, so a small zip bomb allocated
            # gigabytes and an XML DTD/entity was handed to the regex readers.
            # The guarded reader (size cap + entity refusal) is the same one the
            # scanner/validator use.
            problem = _docx_zip_problem(pkg)
            if problem:
                raise OSError(problem)
            xmls = [(n, ooxml_part_text(_docx_xml_part_guarded(pkg, n)))
                    for n in parts]
            style_parts = {n: ooxml_part_text(_docx_xml_part_guarded(pkg, n))
                           for n in ("word/settings.xml", "docProps/custom.xml")
                           if n in pkg.namelist()}
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

    # An UNREADABLE package is not an empty field inventory. The degraded
    # baseline used to be a warning only, and the template gate skipped the
    # whole check when both counts and `errors` were empty, so an unreadable
    # source shipped with "checked: 0" instead of a recorded failure.
    if "unreadable-docx" in (base.get("error_codes") or {}):
        errors.append("the previous version's DOCX package could not be read "
                      "(unreadable-docx), so this comparison has no field baseline: "
                      "restore a readable baseline before trusting it")
    if "unreadable-docx" in (out.get("error_codes") or {}):
        errors.append("this version's DOCX package could not be read (unreadable-docx), "
                      "so its Zotero fields could not be inventoried: an unreadable "
                      "package is not a field-clean one")
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
    if base_items and out_items and not (set(base_items) & set(out_items)):
        # Every baseline citationID replaced by new ones is the SAME loss as
        # "all fields deleted": Zotero can no longer repair the fields from the
        # base. Counting fields missed it (F103).
        errors.append(
            f"ALL {len(base_items)} baseline citationID(s) were replaced: deleted "
            f"{', '.join(sorted(base_items)[:5])}"
            + (f" (+{len(base_items) - 5} more)" if len(base_items) > 5 else "")
            + f"; added {', '.join(sorted(out_items)[:5])}"
            + (f" (+{len(out_items) - 5} more)" if len(out_items) > 5 else "")
            + ". A version may edit fields in place, but replacing every live citationID "
              "removes the only baseline Zotero can repair from")
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
    raw = pkg.read("word/styles.xml")
    # The same untrusted-DOCX rule as the pipeline reader: a part carrying an
    # XML DTD/entity declaration is refused before ElementTree expands it.
    text = xml_guard_text(raw)
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        # The SAME refusal the document part gets -- but only for a real styles
        # part. Returning an empty table made the scan report "no style
        # findings" for a package that evaded the DTD guard and silently lost
        # every style-derived check; the caller's unreadable-package path turns
        # this into the FMT-X1 row. A part with no `<w:styles>` root has no
        # style table to lose and keeps the historical empty result.
        if re.search(r"<[A-Za-z0-9_.-]*:?styles(?=[\s/>])", text):
            raise OSError("part 'word/styles.xml' carries an XML DTD/entity declaration")
        return out
    root = ET.fromstring(raw)
    defaults = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
    if defaults is not None:
        out["@docDefaults"] = {"i": _tri_state(defaults.find(W + "i")),
                               "iCs": _tri_state(defaults.find(W + "iCs")),
                               "b": _tri_state(defaults.find(W + "b")),
                               "bCs": _tri_state(defaults.find(W + "bCs"))}
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
            "bCs": (_tri_state(rpr.find(W + "bCs")) if rpr is not None else None),
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
            # The package is UNTRUSTED (a submitted manuscript or a downloaded
            # template). `pkg.read` alone allocates the decompressed part with
            # no per-part/total budget or entity check, so a small zip bomb
            # could exhaust memory here; use the same guarded readers the
            # scanner path already uses (F75).
            problem = _docx_zip_problem(pkg)
            if problem:
                raise OSError(problem)
            xml = ooxml_part_text(_docx_xml_part_guarded(pkg, "word/styles.xml"))
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return []
    # XML permits single-quoted attributes: use the shared parser instead of a
    # double-quote-only pattern, which made a legal `w:styleId='Heading1'`
    # invisible to style resolution (F097).
    return sorted({sid for sid in (attr(tag, "styleId")
                                   for tag in re.findall(r"<w:style\b[^>]*>", xml))
                   if sid})


def docx_style_name_map(path: Path) -> dict:
    """{style id: declared style name} from a DOCX's word/styles.xml ({} when unreadable).

    Word style ids are arbitrary: a real Heading 1 may carry the id `H1` while
    its declared name is `heading 1`, so the venue-template scan resolves the id
    through this map. The package is UNTRUSTED submitted input, so the read goes
    through the same per-part/total budget and DTD/entity refusal as
    `docx_style_ids` (F75): `pkg.read` alone would decompress a small zip bomb
    with no cap, and ElementTree would expand an entity declaration.
    """
    try:
        with zipfile.ZipFile(path) as pkg:
            problem = _docx_zip_problem(pkg)
            if problem:
                raise OSError(problem)
            raw = _docx_xml_part_guarded(pkg, "word/styles.xml")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    out = {}
    for style_el in root.iter(W + "style"):
        sid = style_el.get(W + "styleId") or ""
        name_el = style_el.find(W + "name")
        if sid and name_el is not None:
            out[sid] = name_el.get(W + "val") or ""
    return out


def _template_uses_even_odd(template: Path) -> bool:
    """True when the template's furniture depends on page parity.

    Either its settings.xml turns the parity switch on, or its own document
    references an even-typed header/footer part.
    """
    try:
        with zipfile.ZipFile(template) as tpkg:
            # Same untrusted-package budget as docx_style_ids (F75). The
            # sibling template paths use the guarded reader; these two reads
            # bypassed it.
            problem = _docx_zip_problem(tpkg)
            if problem:
                raise OSError(problem)
            names = set(tpkg.namelist())
            settings = (ooxml_part_text(_docx_xml_part_guarded(tpkg, "word/settings.xml"))
                if "word/settings.xml" in names else "")
            doc = (ooxml_part_text(_docx_xml_part_guarded(tpkg, "word/document.xml"))
                if "word/document.xml" in names else "")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return False
    if is_on(settings, "evenAndOddHeaders"):
        return True
    # A sectPrChange record holds the OLD section: an even-page reference there
    # is not attached to the document any more.
    sects = SECT_READ_RE.findall(_strip_sect_changes(doc))
    # Every section, not only the last, and any attribute order: Word writes
    # `w:type` before or after `r:id` depending on the producer.
    for sect in sects:
        for tag in re.findall(r"<w:(?:header|footer)Reference\b[^>]*>", sect):
            if (attr(tag, "type") or "").strip().lower() == "even":
                return True
    return False


def docx_front_matter_report(path: Path, template: Path = None, containers=()) -> dict:
    """Template-conformance facts about a DOCX's front matter and headings.

    Used by the venue-template scanner to name the layout gaps a review/rewrite
    session must dispose: the first-page logo header, the page-number footer,
    the Title/AuthorList/Abstract/Keywords front matter, sub-sub-sections
    (Heading 3) and the Cell Press container headings.
    """
    try:
        with zipfile.ZipFile(path) as pkg:
            problem = _docx_zip_problem(pkg)
            if problem:
                raise OSError(problem)
            names = set(pkg.namelist())
            doc = ooxml_part_text(_docx_xml_part_guarded(pkg, "word/document.xml"))
            rels = (ooxml_part_text(_docx_xml_part_guarded(pkg, "word/_rels/document.xml.rels"))
                    if "word/_rels/document.xml.rels" in names else "")
            settings = (ooxml_part_text(_docx_xml_part_guarded(pkg, "word/settings.xml"))
                        if "word/settings.xml" in names else "")
            hf_parts = {n: _docx_xml_part_guarded(pkg, n) for n in names
                        if n.startswith(("word/header", "word/footer")) and n.endswith(".xml")}
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return {}
    rel_map = {e["id"]: (e["type"], e["target"]) for e in _rels_entries(rels)}
    # The section that governs page 1 decides the FIRST-PAGE furniture (see
    # `first_section_props`): reading the last one let a two-section manuscript
    # whose page 1 was not the venue's layout report no gap at all.
    sects = SECT_READ_RE.findall(_strip_sect_changes(doc))
    sect = first_section_props(doc) or (sects[-1] if sects else "")
    # first_section_props() already blanks the change record; strip again so a
    # caller that only has the raw section text behaves the same.
    sect = _strip_sect_changes(sect)
    refs = {}
    for m in re.finditer(r"<w:(header|footer)Reference\b[^>]*>", sect):
        typ = attr_of(m.group(0), "w:type")
        rid = attr_of(m.group(0), "r:id")
        # The FIRST reference of a type is the live one: a later copy can only
        # sit in a change record (blanked above) or be a duplicate.
        if typ and rid:
            refs.setdefault((m.group(1), typ), rid)

    def part(kind: str, typ: str) -> str:
        rid = refs.get((kind, typ))
        k, target = rel_map.get(rid, ("", ""))
        if k == kind and target and not target.startswith("http"):
            # A legal package target may be written '/word/header1.xml'; the
            # sibling reader strips that leading slash, so this one must too
            # (otherwise it built 'word//word/header1.xml' and never resolved).
            return target.lstrip("/")
        return ""

    first_header = part("header", "first") or part("header", "default")
    logo = False
    if first_header:
        name = f"word/{first_header}" if not first_header.startswith("word/") else first_header
        if name in hf_parts:
            hx = ooxml_part_text(hf_parts[name])
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
           "even_odd": is_on(settings, "evenAndOddHeaders"),
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
            problem = _docx_zip_problem(tpkg)
            if problem:
                raise OSError(problem)
            tpl_doc = ooxml_part_text(_docx_xml_part_guarded(
                tpkg, "word/document.xml"))
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
        # The direct-property regexes below are token regexes, so they cannot
        # tell live markup from markup a READER never sees: a commented-out
        # `<w:i/>` inside the rPr was read as live italic and the fixer then
        # wrote a `w:val="0"` override onto a run that was never italic.
        # Masking is length-preserving, so the offsets still address the rPr.
        direct_rpr = _mask_noncontent(direct_rpr)
        i_node = re.search(r"<w:i(?=[\s/>])[^>]*/?>", direct_rpr)
        ics_node = re.search(r"<w:iCs(?=[\s/>])[^>]*/?>", direct_rpr)
        if i_node:
            # XML allows single-quoted attributes: a legal `w:val='0'` was read
            # as ABSENT and turned the run italic ON (F096).
            val = attr(i_node.group(0), "val")
            i_val = True if val is None else \
                str(val).strip().lower() not in ("0", "false", "off")
        if ics_node:
            val = attr(ics_node.group(0), "val")
            ics_val = True if val is None else \
                str(val).strip().lower() not in ("0", "false", "off")
    return bool(i_val) or bool(ics_val)


def run_is_italic(styles: dict, para_style: str | None, run: str) -> bool:
    """effective_emphasis() for one run fragment."""
    rpr = live_rpr(rpr_of(run))
    return effective_emphasis(styles, para_style, elem_val(rpr, "rStyle"), rpr)

def run_is_bold(styles: dict, para_style: str | None, run: str) -> bool:
    """Is this run effectively bold (direct rPr > character style > paragraph style)?

    The same precedence as `effective_emphasis`, for the `w:b`/`w:bCs` pair.
    """
    # `live_rpr` removes the revision record, but a comment/PI inside the rPr is
    # still there; mask it (length-preserving) so a commented-out `<w:b/>` is not
    # read as live bold -- the same non-content rule the token walkers follow.
    rpr = _mask_noncontent(live_rpr(rpr_of(run)))
    b_val = bcs_val = None
    defaults = styles.get("@docDefaults") or {}
    b_val = defaults.get("b") if b_val is None else b_val
    bcs_val = defaults.get("bCs") if bcs_val is None else bcs_val
    for sid in style_chain(styles, para_style or "Normal"):
        st = styles.get(sid) or {}
        if st.get("b") is not None:
            b_val = st["b"]
        if st.get("bCs") is not None:
            bcs_val = st["bCs"]
    for sid in style_chain(styles, elem_val(rpr, "rStyle")):
        st = styles.get(sid) or {}
        if st.get("b") is not None:
            b_val = st["b"]
        if st.get("bCs") is not None:
            bcs_val = st["bCs"]
    for node, key in ((r"<w:b(?=[\s/>])[^>]*/?>", "b"),
                      (r"<w:bCs(?=[\s/>])[^>]*/?>", "bCs")):
        m = re.search(node, rpr)
        if m:
            # Both quote styles are legal XML; a single-quoted `w:val='0'` was
            # read as absent and flipped an explicit OFF to ON (F096).
            val = attr(m.group(0), "val")
            on = True if val is None else \
                str(val).strip().lower() not in ("0", "false", "off")
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
        if before not in _J_BEFORE or after not in _J_AFTER:
            continue
        # A possessive is ordinary prose, not a journal title ("Cell's
        # membrane"); the quote boundary still accepts a quoted title.
        if after == "'" and text[m.end():m.end() + 2].lower() == "'s":
            continue
        # "The Lancet published ..." / "EMBO today announced ...": a journal
        # name is a title, so a bare Lancet/EMBO followed by a lowercase word
        # is prose. A title-case continuation (Lancet Oncology, EMBO Journal)
        # is part of the title; the word after it is ordinary sentence prose.
        head = m.group(0).split()[0].lower()
        if (head in ("lancet", "embo") and len(m.group(0).split()) == 1
                and re.match(r"\s+[a-z]", text[m.end():])):
            continue
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
    tm = re.search(r"(<w:t(?=[\s>])[^>]*>)([\s\S]*?)(</w:t\s*>)", run)
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

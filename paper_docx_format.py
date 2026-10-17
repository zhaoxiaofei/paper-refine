#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OOXML style/formatting audit and safe normalizer for submission packages.

The review/revise pipeline reads DOCX text only (the corpus converters keep
`w:t`/`w:instrText`), so layout and character formatting are invisible to it:
a break-only paragraph produced a blank page after the title page, journal
italics live half in a Zotero bibliography field and half in the body, the same
GitHub URL is hyperlinked in one section and plain text in another, quotes are
mixed straight/curly, and figure legends were hand-formatted with per-figure
spacing. This tool makes those defects checkable and fixes the mechanical ones.

    python3 paper_docx_format.py scan  PACKAGE_DIR [--pdf FILE.pdf] [--json OUT.json]
    python3 paper_docx_format.py fix   FILE.docx --out FILE.fixed.docx [--json OUT.json]
    python3 paper_docx_format.py check-pdf FILE.pdf
    python3 paper_docx_format.py zotero-check   FILE.docx      # what a refresh would rewrite
    python3 paper_docx_format.py zotero-refresh FILE.docx      # repair it offline (in place)
    python3 paper_docx_format.py xfa-export     FORM.pdf       # readable rendering of the answers
    # policy overrides:  --policy policy.json  (see POLICY_DEFAULTS)

Design rules, each one the result of an observed failure:

* reading uses ElementTree; WRITING never re-serializes the XML. Re-serializing
  `word/document.xml` drops namespace declarations that `mc:Ignorable` still
  references and Word then refuses the file ("the file appears to be
  corrupted"). Every edit is a byte-level splice of the original text, so all
  untouched bytes stay untouched.
* every edit is collected against one parse of the current XML and applied from
  the END of the document backwards, so earlier offsets stay valid.
* `fix` verifies itself: `w:t` text is unchanged unless the policy asks for
  punctuation normalization, the parts stay byte-identical, the package still
  parses (plus `docx validate` when that CLI is installed), and a re-scan shows
  every mechanical finding gone. The LIVE-FIELD FENCE additionally requires
  every Zotero field signature (kind, citationID, instruction, begin/separate/
  end balance) to come through the repair unchanged -- a fix that would add,
  remove or unbalance a field fails its own verification and the original file
  is kept -- unless the policy explicitly asks to unlink fields for a
  submission copy. Anything the fixer cannot repair is reported with
  `fix=style-field|policy|editorial|manual` instead of being "fixed" by
  guesswork.
* a finding inside a Zotero field (`w:fldChar begin ... end` + `ADDIN ZOTERO_*`
  instruction) is a field RESULT: Word cannot restyle it persistently because a
  refresh regenerates it. Such rows carry `protected=true`; the fix is the CSL
  style, or `unlink_zotero_fields: true` in the policy for a submission copy.

The module also carries the text-side ledgers the pipeline seeds for its
sessions (`number_ledger`, `key_term_rows`, `identifier_rows`,
`concept_family_rows`, `outline_rows`, `placeholder_ledger`). One of them is
two-sided on purpose: `claim_strength_rows` (check id J3) enumerates the `under`
(hedge) AND `over` (maximal claim) directions of every claim-bearing paragraph,
so a review cannot report the loud direction and leave the quiet one unexamined.

The scan also applies the VENUE's own display-item rules when the policy
declares them: `policy["tables"]` / `policy["figures"]` state where those items
belong and which side carries their caption (a venue profile's rules, rendered
into `format_policy.json` by the pipeline), and the scan reports
`FMT-TB1..FMT-TB3` for a table and `FMT-FG1..FMT-FG3` for a figure -- no
caption / caption on the wrong side / item before its area -- with
`policy[...].special` naming the items the venue itself treats differently
(a key-resources table inside the methods, a graphical abstract). A policy that
declares no rule for a kind reports nothing for it.

A display item's caption is ONE paragraph with ONE spacing and ONE style, and
the scan and the fixer read the same CAPTION BLOCK definition (a figure/table
label -- `Fig. 2 |`, `Figure S1.`, `Table 3 ...` -- plus the paragraphs that
continue it, inside the venue's own figures/tables area): `FMT-T2a`/`FMT-T2b`
check every paragraph of the block (a continuation left without direct spacing
renders one caption at two line spacings), `FMT-T2c` reports a caption split
across paragraphs and the fixer MERGES it into the label paragraph (runs
verbatim, the verifier told the join via `verified.caption_joins`; a block
carrying a drawing, a text box, a tracked change or a section break is left for
the revision arms), and `FMT-T2d` aligns a caption carrying a paragraph style
its sibling captions in the same area do not.

The text-level rules include the "lone division" pair: a narrative paragraph
built from ONE sentence is `FMT-T9k` and a section holding exactly ONE
subsection is `FMT-T10f` -- the same shape rule at two levels of the outline
(a container that divides at all divides into more than one part), both
finding-tier, with end-matter statements, acronym lists, captions and table
cells exempt by construction.

The same policy carries the VENUE TEMPLATE's own blank-line slots
(`policy["empty_paragraph_slots"]`, derived from the journal's official Word
template by the pipeline): an empty paragraph whose (own, previous, next) style
signature is one of them is template chrome (a spacer before the title, a
placeholder between two headings) and is never reported or deleted. Stray empty
paragraphs that are NOT prescribed -- a lone blank line between a section head
and its first subsection, a run longer than `max_empty_paragraph_run` -- are
`FMT-S8`/`FMT-S6` and the fixer deletes them. The text-hygiene family catches
what a text-only corpus cannot see: a space that renders at the start or end of
a visual line (the correspondence e-mail one space to the right, a dangling
trailing space) is `FMT-P4` and mechanical; doubled spaces, bracket spacing and
zero-width marks are `FMT-P3`; a doubled word is `FMT-G1`; a possible lowercase
sentence start is `FMT-G2`; a missing space after punctuation is `FMT-G3`. The
style-convention family (`FMT-T10a`..`FMT-T10e`) reports mixed direct fonts,
spacing/indent/alignment drift inside one style, and heading numbering/level
anomalies for the editing arms. Embedded images are checked against their own
pixels: a figure rescaled without its aspect ratio is `FMT-IM1` and the fixer
restores the ratio in `wp:extent`/`a:ext` (and the VML size). `policy
["cover_letter"]` carries the venue MANUSCRIPT template's front-matter style
ids and its header/footer part hashes plus the venue's cover-letter template
when one ships: a cover letter that uses those styles or carries those parts
while the venue ships no cover-letter template is `FMT-CL1` -- a letter
formatted as a manuscript, cleared only by the journal's own template/guideline
text quoted that REQUIRES the formatting.
"""
from __future__ import annotations

import argparse
import contextlib
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

# A corpus's read-only EVIDENCE areas (`raw_data/`, legacy spelling `raw_figs/`,
# and the human/LLM editors'-reviewers' feedback -- keep in step with
# `paper_pipeline.EVIDENCE_DIRNAMES`): never submission content, never a
# formatting/validation target.
RAW_DATA_DIRNAMES = ("raw_data", "raw_figs")
HUMAN_FEEDBACK_DIR = "human_review_feedback"
LLM_FEEDBACK_DIR = "llm_review_feedback"
EVIDENCE_DIRNAMES = RAW_DATA_DIRNAMES + (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR)

POLICY_DEFAULTS = {
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
TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?>.*?</w:t>", re.S)
# A soft break/tab inside a paragraph (`<w:br/>`, `<w:cr/>`, `<w:tab/>`).
# `text_of` renders each as a NEWLINE: it is a delimiter, not content, so every
# text comparison still sees the same words AND the line-edge rules see the
# space a line edge carries. Dropping it made a three-line correspondence block
# read as one glued token (FMT-X2, 2026-10-15b).
BREAK_TOKENS = re.compile(r"<w:(?:br|cr|tab)(?=[\s/>])[^>]*/?>")
# The same walk, in DOCUMENT ORDER, for the callers that need both kinds of
# piece at once (the text writer splices a fragment's new text at its own
# offset, so a break counts as one character exactly like `text_of` says).
_FRAG_OR_BREAK_RE = re.compile(r"<w:t(?:\s[^>]*)?>.*?</w:t>"
                               r"|<w:(?:br|cr|tab)(?=[\s/>])[^>]*/?>", re.S)
RUN_RE = re.compile(r"<w:r(?=[\s/>]).*?</w:r>|<w:r(?=[\s/>])[^>]*/>", re.S)
FIELD_CHAR_RE = re.compile(r"<w:fldChar[^>]*w:fldCharType=\"(\w+)\"[^>]*/?>")
INSTR_RE = re.compile(r"<w:instrText(?:\s[^>]*)?>.*?</w:instrText>", re.S)
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
# packages) and stayed invisible to the section/word model as well.
LEGEND_RE = re.compile(
    r"^\s*(?:supplementary\s+|supp\.?\s+|extended\s+data\s+)?fig(?:ure)?s?\.?\s*"
    r"(?:S?\d+[A-Za-z]?|[IVXLC]+)\s*[|:.\u2014\u2013-]", re.I)
STRAIGHT_RE = re.compile(r"[\"']")
CURLY_RE = re.compile("[\u2018\u2019\u201c\u201d]")
EM, EN = "\u2014", "\u2013"


def log(*a):
    print(*a, file=sys.stderr)


def esc(text: str) -> str:
    return xml_escape(text or "")


def unesc(text: str) -> str:
    """XML text with entities decoded, including numeric character references.

    `xml.sax.saxutils.unescape` only knows `&amp;`/`&lt;`/`&gt;`, but Word also
    writes `&#8212;`-style references for dashes and smart quotes; leaving those
    literal made the punctuation rules blind to them. The XML predefined
    entities `&quot;`/`&apos;` are decoded for the same reason: `esc()` escapes
    the resulting `&`, so a paragraph carrying `&quot;` used to be re-written as
    `&amp;quot;` and Word printed the reference itself.
    """
    text = xml_unescape(text or "", {"&quot;": '"', "&apos;": "'"})

    def charref(m, base):
        """The decoded character, or the literal reference when it is not valid.

        A hand-edited/LLM-edited `&#x110000;` (or an absurd decimal) raised
        ValueError/OverflowError straight out of the scanner: the scan never
        parses the XML, so nothing caught it and one bad reference took the
        whole formatting run down. Invalid references stay literal.
        """
        try:
            cp = int(m.group(1), base)
        except (ValueError, OverflowError):
            return m.group(0)
        if 0 <= cp <= 0x10FFFF and not (0xD800 <= cp <= 0xDFFF):
            return chr(cp)
        return m.group(0)

    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: charref(m, 16), text)
    return re.sub(r"&#(\d+);", lambda m: charref(m, 10), text)


def load_policy(path) -> dict:
    pol = dict(POLICY_DEFAULTS)
    if path:
        pol.update(json.loads(Path(path).read_text(encoding="utf-8")))
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
    return bool(FIELD_CHAR_RE.search(frag) or INSTR_RE.search(frag))


def ppr_of(frag: str) -> str | None:
    # The self-closing form comes FIRST: `python-docx` writes an empty
    # properties element as `<w:pPr/>`, and the old single-lookahead pattern
    # matched it as "no pPr at all" -- every later insertion then ADDED a
    # second `<w:pPr>` (invalid OOXML) instead of filling the existing one.
    m = re.search(r"<w:pPr(?=[\s/>])[^>]*/>|<w:pPr(?=[\s/>]).*?</w:pPr>", frag, re.S)
    return m.group(0) if m else None


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
    m = re.search(r"<w:rPr(?=[\s/>])[^>]*/>|<w:rPr(?=[\s/>]).*?</w:rPr>", frag, re.S)
    return m.group(0) if m else None


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
    for m in TEXT_RE.finditer(para):
        raw = m.group(0)
        text = unesc(raw[raw.find(">") + 1:raw.rfind("<")])
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
                        fail("duplicate-separate",
                             f"a second field separator at byte {m.start()} is inside one "
                             f"field (the first is at byte {stack[-1]['separate']}); Word "
                             f"renders the extra separator unpredictably")
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
    return bool(re.search(r'<w:(?:header|footer)Reference w:type="even"',
                          sects[-1] if sects else ""))


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
    rel_map = {m.group(1): (m.group(2).lower(), m.group(3))
               for m in _RELS_RE.finditer(rels)}
    # The section that governs page 1 decides the FIRST-PAGE furniture (see
    # `first_section_props`): reading the last one let a two-section manuscript
    # whose page 1 was not the venue's layout report no gap at all.
    sects = SECT_READ_RE.findall(doc)
    sect = first_section_props(doc) or (sects[-1] if sects else "")
    refs = {}
    for m in re.finditer(r'<w:(header|footer)Reference w:type="(\w+)" r:id="([^"]+)"', sect):
        refs[(m.group(1), m.group(2))] = m.group(3)

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
            styles.append(elem_val(ppr_of(p[2]), "pStyle") or "")
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


def effective_emphasis(styles: dict, para_style: str | None, run_style: str | None,
                       direct_rpr: str | None) -> bool:
    """Is this run effectively italic (by direct formatting, character style,
    paragraph style or document defaults)?

    Word's own precedence, lowest to highest: document defaults, the paragraph
    style chain, the run's character style chain, the run's direct rPr. Each
    level can set `w:i` and/or `w:iCs` (complex script) to on or explicitly off;
    the effective run is italic when either ends up on.
    """
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
    rpr = rpr_of(run)
    return effective_emphasis(styles, para_style, elem_val(rpr, "rStyle"), rpr)


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
    """True when the run carries the journal title and nothing else."""
    norm = lambda s: re.sub(r"[^A-Za-z]", "", s).lower()
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
    rpr = re.sub(r"<w:i(?=[\s/>])[^>]*/>", "", rpr)
    rpr = re.sub(r"<w:iCs(?=[\s/>])[^>]*/>", "", rpr)
    rpr = re.sub(r"<w:i(?=[\s/>])[^>]*>.*?</w:i>", "", rpr, flags=re.S)
    rpr = re.sub(r"<w:iCs(?=[\s/>])[^>]*>.*?</w:iCs>", "", rpr, flags=re.S)
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
    at = len(rpr) - len("</w:rPr>")
    for tag in after_tags:
        m = re.search(rf"<w:{tag}(?=[\s/>])", rpr)
        if m and m.start() < at:
            at = m.start()
            break
    rpr = rpr[:at] + insert + rpr[at:]
    return rpr, rpr != before


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


def spelling_minority_targets(prose_texts: list) -> dict:
    """{minority_form: target_form} for every mixed US/UK spelling pair.

    The document's own majority decides. On an exact count tie the form that
    occurs FIRST in the document is the target -- a deterministic choice, so a
    1:1 mix (`modelling` x1 vs `modeling` x1) no longer produces a mechanical
    row the fixer cannot clear (that tie made the whole file's repairs fail
    their self-verification and the original was kept).
    """
    blob = "\n".join(prose_texts)
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
NUMBER_RE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\w])")

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
_WORD_NUMBER_ALT = "|".join(sorted(list(NUMBER_WORD_UNITS) + ["hundred", "thousand"],
                                   key=len, reverse=True))
# "twenty-one", "twenty one", "one hundred", "one hundred and five".
NUMBER_WORD_RE = re.compile(
    r"(?<![\w-])((?:" + _WORD_NUMBER_ALT + r")"
    r"(?:[-\s](?:and[-\s])?(?:" + _WORD_NUMBER_ALT + r")){0,2})(?![\w-])", re.I)
# Plural nouns that are real count targets, plus the plural-looking words that
# are not nouns (so "one is", "two was", "three as" never count).
PLURAL_NOUN_EXCEPTIONS = frozenset({
    "is", "was", "has", "does", "this", "his", "hers", "ours", "yours", "theirs",
    "its", "as", "less", "always", "various", "perhaps", "across", "unless",
    "thus", "plus", "versus", "towards", "afterwards", "nevertheless", "whereas",
    "yes", "class", "process", "analysis", "basis", "status", "series", "species",
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


def _word_number_value(words: str):
    """The integer a spelled-out number denotes, or None when unparsable."""
    total, current = 0, 0
    for tok in re.split(r"[-\s]+", str(words or "").lower()):
        if tok == "and":
            continue
        if tok == "hundred":
            current = (current or 1) * 100
        elif tok == "thousand":
            total += (current or 1) * 1000
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
    if first in ("hundred", "thousand"):
        return False
    # "one another", "one of them", "one may", "no one", "at once": pronouns and
    # idioms, not counts.
    m = re.match(r"\s+([A-Za-z][A-Za-z'-]*)", tail)
    follower = (m.group(1).lower() if m else "")
    if first == "one" and follower in ONE_NON_COUNT_FOLLOWERS:
        return False
    if re.search(r"(?i)\b(?:no|for|at|in)\s+$", text[max(0, start - 12):start]) \
            and first == "one":
        return False
    # "four of the five ...", "three of the nine donors": a count pair.
    if re.match(r"\s+of\s+(?:the\s+|these\s+|those\s+|its\s+|their\s+)?"
                r"(?:" + _WORD_NUMBER_ALT + r"|\d+)\b", tail, re.I):
        return True
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
        written = m.group(1).strip()
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
KEYWORDS_HEAD_RE = re.compile(r"^\s*(?:key\s?words?|keywords)\b", re.I)
METHODS_HEAD_RE = re.compile(
    r"^\s*(?:\d+[.)]?\s*)?(?:materials and methods|online methods|methods)\s*$", re.I)
BODY_HEAD_RE = re.compile(
    r"^\s*(?:\d+[.)]?\s*)?(?:introduction|results|discussion|conclusions?|background|"
    r"related work)\s*:?\s*$", re.I)


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
        if ABSTRACT_HEAD_RE.match(t):
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
     (r"\bCN\b", r"\bCNs\b", r"\bcopy[-\s]number\b"),
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
        nums += NUMBER_RE.findall(text)
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
        digits = n.replace(",", "")
        if len(digits) <= 4:
            return "," in n
        if len(digits) == 4 and digits[:2] in ("19", "20"):
            return False
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
        style = elem_val(ppr_of(para), "pStyle")
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
                rec[state].append((idx, [(ri[2], ri[3])]))
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
                rec["ital" if ital else "roman"].append((idx, [(r0, r1)]))
    rows, fixes = [], []
    for key, rec in sorted(seen.items()):
        if not (rec["ital"] and rec["roman"]):
            continue
        n_i, n_r = len(rec["ital"]), len(rec["roman"])
        where_i = ", ".join(f"p{i}" for i, _runs in rec["ital"][:3])
        where_r = ", ".join(f"p{i}" for i, _runs in rec["roman"][:3])
        rows.append({"rule": "FMT-T9a", "severity": "medium",
                     "evidence": f"{rec['phrase']!r} is italic in {n_i} place(s) "
                                 f"({where_i}) and roman in {n_r} ({where_r})",
                     "detail": "the same phrase must carry ONE treatment; a parenthetical "
                               "label is roman unless the document emphasises all of them",
                     "protected": False})
        if rec["label"] and not any(re.search(r"\d", p) for p in [rec["phrase"]]) \
                and len(rec["phrase"].split()) <= 5:
            want = n_i > n_r                      # majority; a tie -> roman
            for idx, run_offsets in (rec["roman"] if want else rec["ital"]):
                for r0, r1 in run_offsets:
                    fixes.append((idx, r0, r1, want))
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


DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s,;)\]}>\"']+")
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
            if re.search(r"(?:Fig|Table|Eq|Ref|Supplementary|Section)\.?\s*$", ctx[:80]):
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
    for m in years:
        if m.start() and body[m.start() - 1] in "([":
            return m.group(1)
    for m in years:
        if body[m.end():m.end() + 1] in ("", ";", ",", ".", ")", "]"):
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
            d = json.loads(fetch("https://zenodo.org/api/records?size=5&q=" + q))
            hits = (d.get("hits") or {}).get("hits") or []
            # A SEARCH always returns something: keep only records that actually
            # name the thing being looked for (a distinctive token of the query
            # in the record's title/description), or "found" would mean "the API
            # answered", not "the deposit exists".
            toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{5,}", str(query))
                    if t.lower() not in ("github", "https", "zenodo", "figshare",
                                         "research", "science", "single", "whole")]
            toks = sorted(toks, key=len, reverse=True)[:2]
            def _relevant(h) -> bool:
                if not toks:
                    return True
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
            plan.append({"document": r.get("document"),
                         "paragraph": r.get("document_paragraph"),
                         "kind": kind, "query": q,
                         "payload": (r.get("payload") or "")[:120]})
    return plan


def _num_candidates(value: float) -> set:
    out = set()
    for dec in (0, 1, 2, 3):
        s = f"{value:,.{dec}f}"
        out.add(s)
        out.add(s.replace(",", ""))
    return out


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
            for r in body:
                if c >= len(r):
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
            if len(vals) < 3:
                continue
            for cand in _num_candidates(float(len(vals))):
                index.setdefault(cand, f"number of data rows in {name}")
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
        return [c.strip() for c in line.split(delim)]

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
    v = str(cell or "").replace(",", "").replace("$", "").replace("%", "").strip()
    if v.lower() in ("", "nan", "na", "n/a", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _fmt_number(value: float) -> str:
    """A human number: thousands separators, no trailing zeros."""
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
                if num in col_values or num.replace(",", "") in col_values:
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
        key = num.replace(",", "").rstrip(".")
        hit = index.get(num) or index.get(key)
        if hit:
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


def citation_format_row(paras: list) -> dict | None:
    """One row when a document mixes citation formats (None when consistent)."""
    mentions = [m for m in citation_mentions(paras) if m[1] != "other"
                or journal_matches(m[2])]
    shapes = {m[1] for m in mentions}
    if len(shapes) < 2 or not any(journal_matches(m[2]) for m in mentions):
        return None
    counts = Counter(m[1] for m in mentions)
    example = "; ".join(sorted({m[2] for m in mentions if m[1] != "year-only"})[:3])
    unfixable = [m for m in mentions if not m[3]]
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
            out.append((start, i, len(stack), text[start + 1:i]))
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
        for w in set(low):
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


def variant_rows(paras: list, is_ref: list) -> list:
    """FMT-T8d (US/UK spelling) and FMT-T8e (attributive hyphenation)."""
    rows = []
    prose = [(i, t) for i, t in enumerate(paras)
             if not (i < len(is_ref) and is_ref[i])]
    targets = spelling_minority_targets([t for _i, t in prose])
    for a, b in SPELLING_PAIRS:
        ca = sum(len(re.findall(rf"\b{re.escape(a)}\b", t, re.I)) for _i, t in prose)
        cb = sum(len(re.findall(rf"\b{re.escape(b)}\b", t, re.I)) for _i, t in prose)
        if ca and cb:
            target = targets.get(a) or targets.get(b) or ""
            rows.append({"rule": "FMT-T8d", "severity": "medium",
                         "evidence": f"spelling variants in body text: {a!r} x{ca} and "
                                     f"{b!r} x{cb}"
                                     + (f" (tie; the first occurrence wins: {target!r})"
                                        if ca == cb and target else ""),
                         "detail": "one spelling per submission (policy "
                                   "term_spelling='dominant' normalizes the minority form "
                                   "outside the reference list)", "protected": False})
    for hy, split in HYPHEN_COMPOUNDS:
        attr_split = sum(len(re.findall(rf"\b{re.escape(split)}(?=\s+[A-Za-z])", t))
                         for _i, t in prose)
        attr_hy = sum(len(re.findall(rf"\b{re.escape(hy)}(?=\s+[A-Za-z])", t))
                      for _i, t in prose)
        if attr_split and attr_hy:
            rows.append({"rule": "FMT-T8e", "severity": "low",
                         "evidence": f"attributive {hy!r} x{attr_hy} vs {split!r} "
                                     f"x{attr_split} before a noun",
                         "detail": "a compound modifier is hyphenated when it precedes the "
                                   "noun (policy term_hyphenation='dominant' hyphenates the "
                                   "minority attributive form)", "protected": False})
    return rows


def text_style_rows(paras: list, is_ref: list = None, headings: list = None,
                    in_container: list = None, in_area: list = None) -> list:
    """All FMT-T8/T9 rows for a document's paragraphs.

    Every row carries `tier` (see FINDING_TIER_RULES): finding-tier rows must be
    decided against their own bar, advisory rows are recorded and disposed.
    """
    is_ref = list(is_ref or [False] * len(paras))
    prose = [t for i, t in enumerate(paras) if not (i < len(is_ref) and is_ref[i])]
    rows = []
    cit = citation_format_row(paras)
    if cit:
        rows.append(cit)
    rows += nested_parentheses_rows(paras)
    rows += term_repetition_rows(paras, is_ref)
    rows += variant_rows(paras, is_ref)
    rows += long_text_rows(paras, is_ref, section_kinds(paras, headings),
                           headings=headings, in_container=in_container,
                           in_area=in_area)
    rows += self_gloss_rows(paras, is_ref)
    rows += confusable_pair_rows(prose)
    rows += concept_family_rows(paras, is_ref)
    rows += number_format_rows(prose)
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


def _text_fragments(para: str) -> list:
    """[(start, end, unescaped_text, raw_fragment)] for every <w:t> in a paragraph."""
    out = []
    for m in re.finditer(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", para, re.S):
        out.append((m.start(), m.end(), unesc(m.group(1)), m.group(0)))
    return out


def rewrite_text_spans(para: str, edits: list) -> tuple:
    """(new_para, applied) rewriting character spans of a paragraph's TEXT.

    `edits` are (start, end, replacement) offsets into the paragraph TEXT
    (`text_of`), so an edit can cross runs -- the journal segment of "(Garvin et
    al., 2015, Nature Methods)" lives in its own italic run. `<w:t>` contents are
    rewritten; a run that ends up with no text and no other content is dropped,
    everything else (formatting, breaks, drawings) is left alone. Returns the
    applied [(start, end, removed_text, replacement)] so callers can prove that
    NOTHING else in the document changed.

    A BREAK (`w:br`/`w:cr`/`w:tab`) is one character of that text -- `text_of`
    renders it as a newline -- so this walk counts it exactly like `text_of`
    does, and an edit positioned after a break splices into the run it names
    (before 2026-10-16 a line-edge space after a break was deleted from the NEXT
    run's text, which tripped the fixer's own text-identity verification). The
    break is emitted verbatim unless an edit's span covers its position, which
    no rule does today.
    """
    # ONE walk over both kinds of piece, in DOCUMENT ORDER, each carrying the
    # text offset it starts at. A `None` marker means "this piece is a break".
    frags = []
    for m in _FRAG_OR_BREAK_RE.finditer(para):
        tok = m.group(0)
        if BREAK_TOKENS.fullmatch(tok):
            frags.append((m.start(), m.end(), "\n", None))
        else:
            frags.append((m.start(), m.end(),
                          unesc(tok[tok.find(">") + 1:tok.rfind("<")]), tok))
    text = "".join(f[2] for f in frags)
    edits = sorted((s, e, r) for s, e, r in edits if 0 <= s <= e <= len(text) and (e > s or r))
    if not edits:
        return para, []
    # Overlapping edits: keep the first-started of each group (the sort is by
    # start then end, so of two sharing a start the narrower one wins) and drop
    # what it subsumes, so `applied` describes exactly what the result holds.
    deduped = []
    for s, e, r in edits:
        if deduped and s < deduped[-1][1]:
            continue
        deduped.append((s, e, r))
    edits = deduped
    applied = [(s, e, text[s:e], r) for s, e, r in edits]
    # A NON-OVERLAPPING cover of the text as (start, end, new_text): the
    # untouched gap before each edit, then the edit's own replacement ("" for a
    # deletion). Each piece already carries the text that REPLACES its span, so
    # the per-fragment splice below is a plain slice of `new_text`.
    # Each cover piece carries (start, end, new_text, is_edit). The flag is what
    # distinguishes a replacement from copied text -- inferring it from the
    # LENGTH would keep the OLD text of an edit that happens to preserve the
    # length (`tumour` -> `tumor `), which is the kind of silent no-op this walk
    # must never produce.
    keep, pos = [], 0
    for s, e, r in edits:
        if s > pos:
            keep.append((pos, s, text[pos:s], False))
        keep.append((s, e, "" if r is None else r, True))
        pos = e
    if pos < len(text):
        keep.append((pos, len(text), text[pos:], False))
    keep_starts = [a for a, _b, _t, _e in keep]

    def carry(local: int, old: str) -> str:
        """The new text of ONE piece starting at text offset `local`."""
        out, at = [], local
        end = local + len(old)
        while at < end:
            # The cover piece holding `at`: the binary search finds the last
            # piece that starts at or before it.
            idx = bisect_right(keep_starts, at) - 1
            if idx < 0:
                out.append(old[at - local:end - local])
                break
            a, b, new_piece, is_edit = keep[idx]
            if not is_edit:
                # An untouched stretch: copy it -- and the FINAL stretch copies
                # everything to the piece's end rather than stopping at `b`, so
                # no text is lost when the cover and the fragments disagree
                # about a boundary.
                if idx == len(keep) - 1:
                    out.append(old[at - local:end - local])
                    break
                take = min(b, end) - at
                out.append(new_piece[at - a:at - a + take])
                at += take
                continue
            # An edit's replacement: it is emitted ONCE, by the first piece its
            # span touches, then the span is consumed (so a span crossing a
            # break does not repeat or drop the text around the break).
            if at <= a:
                out.append(new_piece)
            at = min(b, end)
        return "".join(out)

    pieces, cursor, here = [], 0, 0
    for start_at, end_at, old_text, raw in frags:
        pieces.append(para[cursor:start_at])
        cursor = end_at
        local = here
        here += len(old_text)
        if raw is None:
            # The break is kept unless an edit's span covers its position.
            covered = next((r for s, e, r, is_edit in keep
                            if is_edit and s <= local < e), None)
            if covered:
                pieces.append('<w:t xml:space="preserve">' + esc(covered) + "</w:t>")
            else:
                pieces.append(para[start_at:end_at])
            continue
        new_text = carry(local, old_text)
        open_tag = raw[:raw.find(">") + 1]
        close_tag = raw[raw.rfind("<"):]
        keep_space = ' xml:space="preserve"' if (new_text != new_text.strip()
                                                 or "xml:space" in open_tag) else ""
        tag = "<w:t" + keep_space + ">"
        pieces.append(tag + esc(new_text) + close_tag if new_text else tag + close_tag)
    pieces.append(para[cursor:])
    new_para = "".join(pieces)

    def _drop_empty_runs(mm):
        body = mm.group(0)
        if re.search(r"<w:(?:drawing|pict|object|br|cr|tab|ptab|fldChar|instrText|"
                     r"noBreakHyphen|sym|commentReference|footnoteReference|"
                     r"endnoteReference|delText|softHyphen|footnoteRef|"
                     r"annotationRef)(?=[\s/>])", body):
            return body
        if re.search(r"<w:t(?:\s[^>]*)?>[^<]", body):
            return body
        return ""
    new_para = re.sub(r"<w:r(?=[\s/>]).*?</w:r>|<w:r(?=[\s/>])[^>]*/>",
                      _drop_empty_runs, new_para, flags=re.S)
    return new_para, applied


def delete_text_spans(para: str, spans: list) -> tuple:
    """(new_para, removed_texts) -- rewrite_text_spans() with empty replacements."""
    new_para, applied = rewrite_text_spans(para, [(s, e, "") for s, e in spans])
    return new_para, [a[2] for a in applied]


# --- removal of the SENTENCE a caller's finder names -------------------------
#
# The pipeline's PKG-2 cleanup uses these: a to-be-submitted document may not
# point at what the submission does not carry (AGENTS.md, "nothing that ships
# points at what does not ship"), and a pointer no shipped locator can replace
# is REMOVED here instead of shipping dangling. The removal is deliberately
# coarse -- the whole sentence that carries the pointer, never a splice inside
# it -- and it is verified (well-formed XML, the same text minus exactly the
# removed sentences, every live citation field carried over unchanged).

# Tokens whose trailing period does NOT end a sentence: abbreviations and
# initials ("e.g.", "et al.", "J. Smith", "Fig. 2"). Over-merging only widens a
# window a caller is about to DELETE, so the set stays small and explicit.
SENTENCE_ABBREV_TAIL_RE = re.compile(
    r"(?i)(?:\b(?:e\.g|i\.e|c\.f|cf|vs|al|approx|ca|dr|prof|st|no|vol|pp|p|fig|figs|"
    r"eq|eqs|ref|refs|sec|tab|suppl|supp|ext|data)\.|(?:\b[A-Za-z]\.|\b[A-Z]\.){1,3})$")
# A sentence that resumes with one of these after a terminator+space did not end
# there ("... (Figure 2). ..." vs "... the value).").
SENTENCE_CONTINUATION_CHARS = ")]}\u201d\u2019'\""


def sentence_spans(text: str) -> list:
    """(start, end) of every SENTENCE in `text` (boundary-aligned spans).

    The splitter is the repo's own (`(?<=[.!?])\\s+`, see the outline scaffold)
    with the two continuations that would otherwise cut a sentence in half: a
    piece that starts with a lowercase letter or a closing bracket/quote
    continues the previous sentence, and so does a piece whose previous token is
    an abbreviation or initials. A caller that only MEASURES is insensitive to a
    wrong merge; a caller that DELETES a window is not, so the merge set is
    deliberately small and documented.
    """
    text = text or ""
    spans, start = [], 0
    for m in re.finditer(r"(?<=[.!?])\s+", text):
        nxt = text[m.end():m.end() + 1]
        if nxt and (nxt.islower() or nxt in SENTENCE_CONTINUATION_CHARS):
            continue
        if SENTENCE_ABBREV_TAIL_RE.search(text[start:m.start()].strip()):
            continue
        spans.append((start, m.start()))
        start = m.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def sentence_windows(text: str, spans: list, eat_whitespace: bool = True) -> list:
    """(start, end) of the smallest sentence window(s) covering `spans`.

    A window is expanded over the whitespace the deletion leaves behind: the
    trailing run when the sentence has a successor, the leading run when it is
    the last one (a removal that left a leading/trailing space would become a
    new FMT-P4 "space at a visual line edge" row). `eat_whitespace=False` stops
    the expansion at the first newline and then trims only spaces/tabs: a
    line-oriented document (`.md`, `.txt`, `.tex`) keeps its line structure, so
    deleting a sentence never JOINS the lines around it.
    """
    text = text or ""
    bounds = sentence_spans(text)
    out = []
    for s, e in sorted(tuple(x) for x in (spans or ())):
        for a, b in bounds:
            if a <= s and e <= b:
                out.append((a, b))
                break
    merged = []
    for a, b in sorted(out):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    fixed = []
    for a, b in merged:
        while b < len(text) and (text[b].isspace() if eat_whitespace else text[b] in " \t"):
            b += 1
        if eat_whitespace and b >= len(text):
            while a > 0 and text[a - 1].isspace():
                a -= 1
        fixed.append((a, b))
    return fixed


def _wt_fragments(frag: str) -> list:
    """[(xml_start, xml_end, unescaped_text)] for every `<w:t>` in a paragraph.

    The same enumeration `rewrite_text_spans` works on (`_text_fragments`), kept
    local so the caller's text offsets and the XML offsets a field lookup needs
    can never drift apart.
    """
    return [(m.start(), m.end(), unesc(m.group(1)))
            for m in re.finditer(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", frag, re.S)]


def _xml_span_for_text_range(frag: str, a: int, b: int):
    """The XML range of a paragraph whose TEXT range [a, b) lives, or None."""
    lo = hi = None
    pos = 0
    for s, e, t in _wt_fragments(frag):
        if pos + len(t) > a and lo is None:
            lo = s
        if pos < b:
            hi = e
        pos += len(t)
    if lo is None or hi is None:
        return None
    return (lo, hi) if lo <= hi else None


def strip_reference_sentences(src: Path, out: Path, finder) -> dict:
    """Remove every SENTENCE of `src` that `finder` names as a dangling pointer.

    `finder(text) -> [(start, end), ...]` names the reference spans inside one
    paragraph's own text (the pipeline passes its PKG-2 matcher). Every span is
    widened to the sentence that carries it and that sentence is deleted from
    the document text; nothing else in the package is touched.

    A sentence that carries a live citation FIELD is NOT removed: dropping a
    field would renumber the bibliography and break the base-to-candidate
    field-continuity gate, so the pointer stays and the caller reports it (the
    author or the next revision session fixes that one in prose). The same
    refusal covers a text range the OOXML cannot address as plain text.

    Returns {"source", "output", "ok", "removed": [{"paragraph", "sentence",
    "references"}], "skipped": [reason], "verified": {...}, "error"} -- the
    removed sentences VERBATIM, so a caller can print exactly what left the
    document. `ok` is False and `src` is carried over unchanged when the result
    would not verify.
    """
    out = Path(out)
    res = {"source": str(src), "output": str(out), "ok": False, "removed": [],
           "skipped": [], "verified": {}}
    try:
        if Path(src).resolve() == out.resolve():
            res["error"] = ("the output path is the source document: the caller must hand in "
                            "a DIFFERENT path (the zip rewrite would truncate the source)")
            return res
    except OSError:                                                    # pragma: no cover
        pass
    try:
        with zipfile.ZipFile(src) as pkg:
            parts = {i.filename: pkg.read(i.filename) for i in pkg.infolist()}
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError, NotImplementedError) as e:
        res["error"] = f"unreadable DOCX package: {type(e).__name__}: {e}"
        return res
    if "word/document.xml" not in parts:
        res["error"] = "unreadable DOCX package: no word/document.xml"
        return res
    try:
        # OOXML is UTF-8 (or UTF-16 with a BOM, which `.decode("utf-8")` refuses):
        # a wrongly encoded part is an unreadable document, reported through this
        # function's own record -- the ValueError used to escape as a traceback.
        xml = parts["word/document.xml"].decode("utf-8")
    except UnicodeDecodeError as e:
        res["error"] = f"unreadable DOCX package: word/document.xml is not UTF-8 ({e})"
        return res
    paras = paragraphs(xml)
    edits, removed = [], []
    for index, (p0, p1, frag) in enumerate(paras):
        text = "".join(t for _s, _e, t in _wt_fragments(frag))
        spans = [tuple(s) for s in (finder(text) or ())]
        if not spans:
            continue
        windows = sentence_windows(text, spans)
        if not windows:
            res["skipped"].append(
                f"paragraph {index}: the reference could not be widened to a sentence")
            continue
        fields_before = zotero_field_report(frag)
        keep = []
        for a, b in windows:
            span = _xml_span_for_text_range(frag, a, b)
            hit_field = False
            if span is not None:
                lo, hi = span
                for m in re.finditer(r"<w:fldChar\b[^>]*/>|<w:instrText\b[^>]*>.*?</w:instrText>"
                                     r"|<w:fldSimple\b[^>]*>.*?</w:fldSimple>", frag, re.S):
                    if m.start() < hi and lo < m.end():
                        hit_field = True
                        break
            if hit_field:
                res["skipped"].append(
                    f"paragraph {index}: the sentence carrying a dangling reference also "
                    f"carries a live citation field ({text[a:b].strip()[:80]!r}); dropping it "
                    f"would renumber the bibliography -- fix it in prose")
                continue
            keep.append((a, b))
        if not keep:
            continue
        new_frag, applied = rewrite_text_spans(frag, [(a, b, "") for a, b in keep])
        if not applied:
            res["skipped"].append(
                f"paragraph {index}: the text edit could not be applied (a match crossing "
                f"formatted runs)")
            continue
        if parts_has_field(frag) and zotero_field_report(new_frag) != fields_before:
            res["skipped"].append(
                f"paragraph {index}: the removal would change the paragraph's citation fields")
            continue
        expected, pos = [], 0
        for a, b in keep:
            expected.append(text[pos:a])
            pos = b
        expected.append(text[pos:])
        expected_text = "".join(expected)
        got_text = "".join(t for _s, _e, t in _wt_fragments(new_frag))
        if got_text != expected_text or text_of(new_frag) != expected_text:
            res["skipped"].append(
                f"paragraph {index}: the edit did not reproduce the text it was supposed to "
                f"(refused rather than shipped)")
            continue
        edits.append((p0, p1, new_frag))
        for (a, b) in keep:
            removed.append({
                "paragraph": index, "sentence": text[a:b].strip(),
                "references": [text[s:e] for s, e in spans if a <= s and e <= b],
                "expected_text": expected_text})
    if not edits:
        res["verified"] = {"removed": 0, "xml": True, "fields": True, "text": True}
        res["ok"] = True
        return res
    new_xml = apply_edits(xml, edits)
    try:
        ET.fromstring(new_xml)
    except ET.ParseError as e:
        res["error"] = f"the removal produced malformed XML: {e}"
        return res
    if zotero_field_signature(zotero_field_report(xml)) \
            != zotero_field_signature(zotero_field_report(new_xml)):
        res["error"] = ("the removal would change which live citation fields the document "
                        "carries")
        return res
    # Text identity over the WHOLE document: every paragraph that was not edited
    # carries the same text as before, and every edited one carries exactly the
    # text the removal computed (a structural splice would show up here).
    want_by_para = {int(r["paragraph"]): r["expected_text"] for r in removed}
    paras_before = paragraphs(xml)
    paras_after = paragraphs(new_xml)
    if len(paras_before) != len(paras_after):
        res["error"] = "the removal changed the paragraph count"
        return res
    for i, ((_s0, _e0, frag0), (_s1, _e1, frag1)) in enumerate(zip(paras_before, paras_after)):
        if text_of(frag1) != want_by_para.get(i, text_of(frag0)):
            res["error"] = (f"the removal changed paragraph {i} beyond the sentences it "
                            f"removed")
            return res
    parts_new = dict(parts)
    parts_new["word/document.xml"] = new_xml.encode("utf-8")
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts_new.items():
                z.writestr(name, data)
    except (OSError, RuntimeError, NotImplementedError) as e:
        res["error"] = f"could not write the repaired DOCX: {type(e).__name__}: {e}"
        return res
    res["removed"] = removed
    res["verified"] = {"removed": len(removed), "xml": True, "fields": True, "text": True}
    res["ok"] = True
    return res


def parts_has_field(frag: str) -> bool:
    """True when a paragraph fragment carries any complex/simple field."""
    return bool(re.search(r"<w:fldChar\b|<w:instrText\b|<w:fldSimple\b", frag or ""))


# A relationship TARGET that names a path on somebody's own machine: a `file:`
# URI (`file:///C:\Users\hannah.eccles\...\frontiers_template.dotx`, what the
# venue's Word template carries into every restyled package), a Windows drive or
# UNC path. It is not content -- the reader cannot open it, and it leaks a
# machine/user name -- while an internal part (`/word/styles.xml`), a
# `http(s)`/`mailto` link or a relative target is not one of these.
LOCAL_PATH_TARGET_RE = re.compile(r"^(?:file:|[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/]|[\\/]{2,}\?)")
ATTACHED_TEMPLATE_REL = ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
                         "attachedTemplate")
_REL_ENTRY_RE = re.compile(r"<Relationship\b[^>]*/>")


def local_path_link_rows(path: Path) -> list:
    """[(part, relationship_id, relationship_type, target)] of local-path links.

    Every `.rels` part of the package is inspected: a relationship whose Target
    is an absolute local path (`file:` URI, a drive letter, a UNC share) is a
    pointer no reader can resolve -- and, for the attached-template link the
    venue's own template carries, a path that names a third party's machine.
    """
    rows = []
    try:
        with zipfile.ZipFile(path) as pkg:
            for name in sorted(pkg.namelist()):
                if not name.endswith(".rels"):
                    continue
                try:
                    text = pkg.read(name).decode("utf-8", "replace")
                except (KeyError, RuntimeError, NotImplementedError):
                    continue
                for m in _REL_ENTRY_RE.finditer(text):
                    entry = m.group(0)
                    target = (attr_of(entry, "Target") or "")
                    if not LOCAL_PATH_TARGET_RE.match(target.strip()):
                        continue
                    rows.append((name, attr_of(entry, "Id") or "",
                                 attr_of(entry, "Type") or "", target.strip()))
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError, NotImplementedError):
        return []
    return rows


def strip_local_path_links(src: Path, out: Path) -> dict:
    """Remove the package's attached-template link when it names a local path.

    The venue's Word templates carry `w:attachedTemplate` -> `file:///C:\\Users\\
    <someone>\\...\\template.dotx`; a restyled package inherits it, so the
    submitted file points at a document no reader can open and leaks the machine
    it was authored on. The element and ITS OWN relationship are dropped (the
    element is what references the relationship, so both go together and no
    dangling `r:id` is left); every other part is carried over verbatim, and the
    result must re-open, parse and keep its text.

    Any OTHER local-path relationship is left alone (a live field or hyperlink
    referencing it would break) and is reported by `local_path_link_rows`.
    Returns {"source", "output", "ok", "removed": [{"part", "target"}],
    "skipped": [...], "verified": {...}, "error"}.
    """
    out = Path(out)
    res = {"source": str(src), "output": str(out), "ok": False, "removed": [],
           "skipped": [], "verified": {}}
    try:
        if Path(src).resolve() == out.resolve():
            res["error"] = ("the output path is the source document: the caller must hand in "
                            "a DIFFERENT path (the zip rewrite would truncate the source)")
            return res
        with zipfile.ZipFile(src) as pkg:
            parts = {i.filename: pkg.read(i.filename) for i in pkg.infolist()}
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError, NotImplementedError) as e:
        res["error"] = f"unreadable DOCX package: {type(e).__name__}: {e}"
        return res
    settings = "word/_rels/settings.xml.rels"
    if settings not in parts:
        res["skipped"].append("no word/_rels/settings.xml.rels part")
        res["ok"] = True
        res["verified"] = {"removed": 0, "parts": len(parts)}
        return res
    rels = parts[settings].decode("utf-8", "replace")
    kill = []
    for m in _REL_ENTRY_RE.finditer(rels):
        entry = m.group(0)
        target = (attr_of(entry, "Target") or "").strip()
        if (attr_of(entry, "Type") or "").strip() != ATTACHED_TEMPLATE_REL:
            continue
        if not LOCAL_PATH_TARGET_RE.match(target):
            continue
        kill.append((m.start(), m.end(), target, attr_of(entry, "Id") or ""))
    if not kill:
        res["skipped"].append("no attached-template link to a local path")
        res["ok"] = True
        res["verified"] = {"removed": 0, "parts": len(parts)}
        return res
    # Rebuild by splicing from the end so earlier offsets stay valid.
    new_rels = rels
    for a, b, _t, _rid in sorted(kill, key=lambda k: -k[0]):
        new_rels = new_rels[:a] + new_rels[b:]
    doc = "word/settings.xml"
    removed = []
    parts_new = dict(parts)
    parts_new[settings] = new_rels.encode("utf-8")
    ids = {rid for _a, _b, _t, rid in kill if rid}
    if doc in parts and ids:
        settings_xml = parts[doc].decode("utf-8", "replace")
        new_settings = settings_xml
        for rid in ids:
            # Both element spellings (Word writes the empty element; be safe
            # about the paired form) and both with and without the `r:id`.
            rid_pat = re.escape(rid)
            new_settings = re.sub(
                r"<w:attachedTemplate\b[^>]*r:id=\"" + rid_pat + r"\"[^>]*/>"
                r"|<w:attachedTemplate\b[^>]*r:id=\"" + rid_pat
                + r"\"[^>]*>.*?</w:attachedTemplate>"
                r"|<w:attachedTemplate\b[^>]*/>", "", new_settings)
        # NO dangling reference may survive: the relationship is gone, so every
        # element that referenced it must be gone too (a live `r:id` naming a
        # dropped relationship is what makes Word offer "unreadable content").
        for rid in ids:
            if re.search(r'r:id="' + re.escape(rid) + r'"', new_settings):
                res["error"] = (f"the attached-template element referencing {rid!r} could "
                                f"not be removed, so the relationship was left in place")
                return res
        if new_settings == settings_xml:
            # The relationship was not (or no longer) referenced by an element:
            # the drop is still safe, but say so instead of pretending.
            res["skipped"].append("the attached-template element was not present in "
                                  "word/settings.xml (the relationship alone was dropped)")
        parts_new[doc] = new_settings.encode("utf-8")
    try:
        ET.fromstring(parts_new[settings].decode("utf-8"))
        if doc in parts:
            ET.fromstring(parts_new[doc].decode("utf-8"))
    except ET.ParseError as e:
        res["error"] = f"the removal produced malformed XML: {e}"
        return res
    for _a, _b, target, rid in kill:
        removed.append({"part": settings, "target": target, "id": rid})
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts_new.items():
                z.writestr(name, data)
    except (OSError, RuntimeError, NotImplementedError) as e:
        res["error"] = f"could not write the repaired DOCX: {type(e).__name__}: {e}"
        return res
    # Verification: the copy re-opens, and every part OTHER than the two edited
    # ones is byte-identical to the source.
    try:
        with zipfile.ZipFile(out) as chk:
            names = set(chk.namelist())
            same = all(chk.read(n) == parts[n] for n in names - {settings, doc})
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        res["error"] = f"the repaired DOCX could not be re-read: {type(e).__name__}: {e}"
        return res
    if names != set(parts) or not same:
        res["error"] = "the repair changed more than the attached-template link"
        return res
    res["removed"] = removed
    res["verified"] = {"removed": len(removed), "parts": len(parts), "others_identical": True}
    res["ok"] = True
    return res


def attr_of(element: str, name: str):
    """The value of one XML attribute in an element fragment (None when absent).

    `attr()` is the `w:`-prefixed accessor; a `.rels` entry's attributes
    (`Target`, `Type`, `Id`) carry no prefix, so this is the plain-name variant.
    """
    m = re.search(r"\b" + re.escape(name) + r"""\s*=\s*("([^"]*)"|'([^']*)')""", element or "")
    if not m:
        return None
    return m.group(2) if m.group(2) is not None else m.group(3)


def style_survey(xml: str, styles: dict) -> dict:
    """Per-document font / paragraph-style inventory (the STYLE artifact).

    The rules below only cover defect classes the scanner knows. When a human or
    an agent LOOKS at a rendered page and sees something else -- a font that
    differs between sections, a size that drifts, the same word set in two
    different emphases -- this inventory makes the OOXML facts visible: every
    font, size, paragraph style and character style actually in use (with
    counts), and how many runs are italic and through which mechanism (direct
    formatting vs a character style such as Word's "Emphasis" vs the paragraph
    style). It rides along in every scan result, so `FORMAT_SCAN.json`,
    `CODE_SCANS.json` and the M20 artifact carry it.
    """
    fonts, sizes, pstyles, cstyles = Counter(), Counter(), Counter(), Counter()
    it_direct = it_char = it_para = 0
    runs_n = no_font = 0
    for _p0, _p1, para in paragraphs(xml):
        style = elem_val(ppr_of(para), "pStyle") or "Normal"
        pstyles[style] += 1
        p_italic = effective_emphasis(styles, style, None, None)
        for _r0, _r1, run in runs(para):
            rpr = rpr_of(run)
            if not text_of(run).strip() and not rpr:
                continue
            runs_n += 1
            rf = elem(rpr, "rFonts") if rpr else None
            font = next((attr(rf, k) for k in ("ascii", "hAnsi", "cs")
                         if rf is not None and attr(rf, k)), None)
            if font:
                fonts[font] += 1
            else:
                no_font += 1                 # inherits the theme / document default
            sz = elem_val(rpr, "sz")
            if sz:
                sizes[sz] += 1
            rstyle = elem_val(rpr, "rStyle")
            if rstyle:
                cstyles[rstyle] += 1
            if run_is_italic(styles, style, run):
                if rpr and re.search(r"<w:i(?=[\s/>])[^>]*/?>", rpr):
                    it_direct += 1
                elif rstyle:
                    it_char += 1
                elif p_italic:
                    it_para += 1
    return {"fonts": dict(fonts.most_common()),
            "fonts_inherited_or_theme": no_font,
            "sizes_half_points": dict(sizes.most_common()),
            "paragraph_styles": dict(pstyles.most_common()),
            "character_styles": dict(cstyles.most_common()),
            "runs": runs_n,
            "italic_runs": {"direct": it_direct, "character_style": it_char,
                            "paragraph_style": it_para}}


def _fix_kind(rule: str, policy: dict) -> str:
    if rule in ("FMT-S1", "FMT-T2a", "FMT-T2b", "FMT-T2c", "FMT-T2d", "FMT-T3a"):
        return "mechanical"
    if rule in ("FMT-S6", "FMT-S8",          # stray empty paragraphs (template-aware)
                "FMT-P4",                    # a space at a visual line edge
                "FMT-G1",                    # a doubled article/preposition
                "FMT-IM1"):                  # an image rescaled off its own ratio
        return "mechanical"
    if rule == "FMT-S3":
        return "mechanical" if policy["title_page_header"] == "suppress" else "policy"
    if rule == "FMT-S5":
        return "mechanical" if policy["strip_proofing_markers"] else "policy"
    if rule == "FMT-T1":
        return "mechanical" if policy["quote_style"] in ("straight", "curly") else "policy"
    if rule == "FMT-T3b":
        return "mechanical" if policy["align_heading_sizes"] else "policy"
    if rule in ("FMT-T7a", "FMT-T7b"):
        return "mechanical" if policy["url_style"] == "plain" else "policy"
    if rule in ("FMT-T6a", "FMT-T6b"):
        return "style-field"
    if rule in ("FMT-T6c", "FMT-T6f", "FMT-T6g"):
        # The treatment of a journal title is a DECIDED policy (refs-only /
        # everywhere / off), so the fixer can apply it run by run; it stays
        # "style-field" only where the run sits inside a Zotero field.
        return "mechanical" if policy["journal_italics"] in ("refs-only", "everywhere",
                                                             "off") else "policy"
    if rule == "FMT-T8a":
        return "mechanical" if policy["citation_journal_names"] == "drop" else "policy"
    if rule == "FMT-T8d":
        return "mechanical" if policy["term_spelling"] == "dominant" else "policy"
    if rule == "FMT-T8e":
        return "mechanical" if policy["term_hyphenation"] == "dominant" else "policy"
    if rule in ("FMT-T6d", "FMT-T6e"):
        return "style-field"
    if rule in ("FMT-S2", "FMT-S4"):
        return "manual"
    if rule in ("FMT-R5", "FMT-AV1", "FMT-AV2") or rule.startswith("FMT-Z"):
        # A preprint/trial-only reference, a future/conditional locator and two
        # pinned revisions of one repository all need an AUTHOR decision (deposit
        # the data, pin one commit, replace the citation): the code reports them
        # and never edits around them. The Zotero field-state rows are the same:
        # only Word/Zotero can re-render a citation field, and a field RESULT is
        # never edited by this tool.
        return "manual"
    return "editorial"


MECHANICAL_RULES = {"FMT-S1", "FMT-S3", "FMT-S5", "FMT-T1", "FMT-T2a", "FMT-T2b",
                    "FMT-T2c", "FMT-T2d",
                    "FMT-T3a", "FMT-T3b", "FMT-T6a", "FMT-T6b", "FMT-T6c", "FMT-T6f",
                    "FMT-T6g", "FMT-T7a", "FMT-T7b", "FMT-T8a", "FMT-T8d", "FMT-T8e",
                    "FMT-S6", "FMT-S8", "FMT-P4", "FMT-G1", "FMT-IM1"}


# ---- layout consistency and page budgets (rules FMT-T8f/T8g/T8h) ----------
# Three layout defects the text-only pass cannot see and a reader notices at
# once: sibling paragraphs/captions that disagree on first-line indentation, a
# front page whose abstract and keywords are split by a page break, and a cover
# letter that renders past its two-page budget. Two of the three are read from
# the OOXML itself (no renderer needed): the indent is the paragraph's own
# `w:ind`, and the page break is Word's own `w:lastRenderedPageBreak` record.
# The cover-letter page count uses a rendered PDF beside the .docx when one
# ships, and otherwise reports the cached `docProps/app.xml <Pages>` value.
CAPTION_LIKE_RE = re.compile(
    r"^\s*(?:fig(?:ure)?s?\.?|tables?|extended\s+data|supplementary\s+(?:fig(?:ure)?s?|tables?))"
    r"\b", re.I)
KEYWORDS_RE = re.compile(r"^\s*(?:keywords?|key\s+words)\s*[:\-–—]", re.I)
LIST_LIKE_RE = re.compile(r"^\s*(?:[\(\[]?[a-z0-9]{1,3}[\)\].、]|[-•*·])\s+", re.I)
PAGE_BREAK_RE = re.compile(r"<w:lastRenderedPageBreak(?=[\s/>])[^>]*/>")

# ---- the venue's DISPLAY-ITEM rules (tables FMT-TB1..3, figures FMT-FG1..3) --
# Where a display item belongs and what labels it is a DECIDED venue fact, so it
# comes from the venue profile through the format policy (`policy["tables"]` /
# `policy["figures"]`), never from this module: a venue whose template says
# "tables at the end of the manuscript, caption immediately before the table"
# gets exactly that check, a venue whose guidelines say "figure legends should be
# placed at the end of the manuscript" gets the figure counterpart, and a venue
# that declares no rule for one kind gets NO rows for it (a rule no venue stated
# is never invented here). Both policy blocks have the same shape:
#   {"source": ..., "placement": "end"|"inline"|"any",
#    "caption": "before"|"after"|"any", "note": ...,
#    "special": [{"match": <regex>, "placement": ..., "caption": ...,
#                 "source": ..., "note": ...}]}
# `special` is the escape hatch the checks need to stay honest: a publisher can
# genuinely treat ONE item differently -- a key-resources/STAR-Methods table that
# lives inside the methods with no "Table N." label, or a front-matter figure
# such as a graphical abstract that is not part of the numbered figure sequence
# -- and the profile names it by the text above the item, its own section heading
# or (tables only) its first-row header. A special entry overrides only the
# fields it states; the rest of the venue rule still applies to that item.
#
# The items are found where a reader sees them in the document BODY:
#   * a table is a `<w:tbl>` block; its caption is the adjacent paragraph that
#     starts with a table label ("Table 3 | ...", "Table 3. ...", "Table 3");
#   * a figure is a paragraph carrying an embedded drawing/picture, or a
#     COLLECTED legend -- a paragraph that starts with a figure label
#     ("Figure 2 | ...", "Fig. 2. ...", "Figure S1 ...") and is NOT attached to
#     an embedded image (the legends-collected-at-the-end layout the venue
#     guidelines ask for). Its caption is the adjacent label paragraph, or the
#     legend paragraph itself.
# Three findings can come out of one item:
#   *1 -- the item carries no caption at all (only when the venue pins the
#         caption to one side of the item: a venue that collects legends
#         elsewhere declares `caption: "any"`, and then a figure is not
#         captioned next to its image by design);
#   *2 -- the caption sits on the other side of the item than the venue
#         requires (e.g. after a table whose captions belong before it);
#   *3 -- the item appears BEFORE the item's area (the venue's own
#         tables/figures heading, else the first captioned item of that kind)
#         although the venue puts them at the end.
# All of them are finding-tier: an editor or a copyeditor raises them, so the
# review must dispose them and a package-producing stage must fix them.
DISPLAY_PLACEMENTS = ("end", "inline", "any")
DISPLAY_CAPTION_SIDES = ("before", "after", "any")
# The area headings carry the supplementary prefix too: a supplementary-material
# file collects "Supplementary Figures" / "Supplementary Tables" exactly as the
# main manuscript collects "Figures" / "Tables", and the caption-block rule
# below must find that area in either document.
_AREA_PREFIX = r"(?:(?:supplementary|supp\.?|extended\s+data)\s+)?"
TABLES_HEADING_RE = re.compile(
    r"^\s*" + _AREA_PREFIX + r"(?:list\s+of\s+)?tables?\s*:?\s*$", re.I)
FIGURES_HEADING_RE = re.compile(
    r"^\s*" + _AREA_PREFIX + r"(?:list\s+of\s+figures?|figures?|figure\s+titles?\s+and"
    r"\s+legends?|figure\s+legends?|captions?)\s*:?\s*$", re.I)
# "Table 3. Title", "Table 3 | Title", "Table 3: Title", "Table S3 -- Title",
# "TABLE 4 - Title" are captions; "Table 3 shows ..." is prose, not a caption
# (the separator right after the number is what tells them apart). The figure
# patterns below are the same rule for "Figure 2 |", "Fig. 2.", "Figure S1",
# "Extended Data Figure 3 |", "Supplementary Fig. 4:".
_CAPTION_LABEL_RE = (r"(?:supplementary\s+|extended\s+data\s+|supp\s+)?%s\.?\s*")
DISPLAY_CAPTION_NUM_RE = r"(?:S?\d+[A-Za-z]?|[IVXLC]+)"
TABLE_CAPTION_RE = re.compile(
    r"^\s*" + (_CAPTION_LABEL_RE % "tables?") + DISPLAY_CAPTION_NUM_RE
    + r"\s*(?:\||:|\u2014|\u2013|-|\.)(?=\s|$)", re.I)
TABLE_CAPTION_BARE_RE = re.compile(
    r"^\s*" + (_CAPTION_LABEL_RE % "tables?") + DISPLAY_CAPTION_NUM_RE + r"\s*$", re.I)
FIGURE_CAPTION_RE = re.compile(
    r"^\s*" + (_CAPTION_LABEL_RE % "fig(?:ure)?s?") + DISPLAY_CAPTION_NUM_RE
    + r"\s*(?:\||:|\u2014|\u2013|-|\.)(?=\s|$)", re.I)
FIGURE_CAPTION_BARE_RE = re.compile(
    r"^\s*" + (_CAPTION_LABEL_RE % "fig(?:ure)?s?") + DISPLAY_CAPTION_NUM_RE + r"\s*$",
    re.I)
# An EMBEDDED figure, as the OOXML body shows it (the header/footer furniture --
# the journal's logo -- lives in its own part and is never seen here).
FIGURE_DRAWING_RE = re.compile(r"<w:(?:drawing|pict|object)(?=[\s/>])")
# The venue's manuscript rule is about the MANUSCRIPT: a supplementary-material
# file, a cover letter or a feedback/response document has its own conventions
# (supplementary figures and tables legitimately sit inside their own file), so
# the display rules never run on one. "supp" in the name is the same test the
# M19 length scan uses for the same reason; the feedback/response names mirror
# the pipeline's `is_non_manuscript_rel` (authors' replies are not the letter).
DISPLAY_SKIP_NAME_RE = re.compile(
    r"cover|response|repl(?:y|ies)|rebuttal|point[-_ ]?by[-_ ]?point|feedback|referee|"
    r"reviewers?|decision[-_ ]?(?:letter|notice)|highlight|eTOC|graphical[-_ ]?abstract",
    re.I)
DISPLAY_TABLE_RULES = ("FMT-TB1", "FMT-TB2", "FMT-TB3")
DISPLAY_FIGURE_RULES = ("FMT-FG1", "FMT-FG2", "FMT-FG3")
DISPLAY_KINDS = {
    "table": {"policy_key": "tables", "noun": "table",
              "rules": DISPLAY_TABLE_RULES, "heading_re": TABLES_HEADING_RE,
              "caption_re": TABLE_CAPTION_RE, "caption_bare_re": TABLE_CAPTION_BARE_RE},
    "figure": {"policy_key": "figures", "noun": "figure",
               "rules": DISPLAY_FIGURE_RULES, "heading_re": FIGURES_HEADING_RE,
               "caption_re": FIGURE_CAPTION_RE, "caption_bare_re": FIGURE_CAPTION_BARE_RE},
}


# ---- caption/legend BLOCKS (rules FMT-T2a..FMT-T2d) -------------------------
# A display item's caption is ONE paragraph -- the venues that collect legends
# state it ("Please use only a single paragraph for the caption") and the
# collected-legends layout reads that way -- and every paragraph of a caption
# block carries the caption's own line spacing. Both the scan and the fixer read
# the same definition:
#
#   * a LABEL opens a block: a paragraph whose text starts with a figure or
#     table caption label ("Fig. 2 | ...", "Figure S1. ...", "Table 3 ...");
#   * a CONTINUATION is the paragraph right after the label (or after another
#     continuation): non-empty text, no embedded drawing, not a heading, not
#     another label, not a reference entry, no section break, not inside a
#     table/text box;
#   * an empty paragraph, a heading, another label, an image or a table closes
#     the block.
#
# The BLOCK rules (a multi-paragraph caption -> merge it; a caption carrying a
# foreign paragraph style -> align it with its sibling captions; a continuation
# inheriting the body's line spacing -> give it the caption's) run where the
# venue's own display AREA holds the captions -- the "Figure legends"/"Figures"
# and "Tables" areas the collected-legend layouts declare. Outside such an area
# the paragraph after a label may be ordinary body prose, so no block is formed
# there and the label alone is normalized.

def container_spans(xml: str) -> list:
    """(start, end) of every table / text-box container in `xml`.

    A paragraph inside a table cell (or a text box) is part of that container,
    never a continuation of a caption above it -- the flattened paragraph list
    holds one entry per cell paragraph, and merging those into the caption
    would move a table's content into prose.
    """
    spans, stack = [], []
    tokens = re.compile(r"<w:(tbl|txbxContent)(?=[\s>])|</w:(tbl|txbxContent)>")
    for m in tokens.finditer(xml):
        if m.group(1):
            stack.append(m.start())
        elif stack:
            spans.append((stack.pop(), m.end()))
    for start in stack:                       # hand-edited XML: close at EOF
        spans.append((start, len(xml)))
    return spans


def caption_label_kind(text: str) -> str:
    """`"figure"`, `"table"` or `""` -- the display kind a caption label opens."""
    t = text or ""
    if FIGURE_CAPTION_RE.match(t):
        return "figure"
    if TABLE_CAPTION_RE.match(t):
        return "table"
    return ""


def display_area_kinds(paras: list) -> list:
    """The display area each paragraph sits in: "figure" / "table" / "".

    A figures/tables heading (the venue's collected legends/tables area) opens
    the area; the next heading of any kind closes it.
    """
    out, area = [], ""
    for _, _, para in paras:
        text = text_of(para).strip()
        style = _para_style(para)
        heading = bool(style and style.startswith("Heading"))
        if heading:
            if FIGURES_HEADING_RE.match(text):
                area = "figure"
            elif TABLES_HEADING_RE.match(text):
                area = "table"
            else:
                area = ""
        out.append(area)
    return out


def _caption_continuation(para: str) -> bool:
    """True when `para` continues the caption block opened above it."""
    if not text_of(para).strip():
        return False
    if has_drawing(para):
        return False
    if "<w:sectPr" in para:
        return False
    style = _para_style(para)
    if style.startswith("Heading") or style == "Bibliography":
        return False
    if caption_label_kind(text_of(para)):
        return False
    return True


def caption_block_ranges(paras: list, areas: list = None, containers=(),
                         xml: str = None) -> list:
    """[{"kind", "label", "continuations", "in_area"}] for every caption block.

    `areas` is `display_area_kinds(paras)` when the caller has it; `containers`
    is `container_spans(xml)` so a table cell's paragraph is never read as a
    caption continuation. `xml` (when given) also marks whether the block is
    MERGEABLE -- its bytes are exactly the block's own paragraphs and nothing
    Word owns sits in them; the scan reports a block the fixer must refuse as an
    editorial row instead of a mechanical one.
    """
    areas = list(areas) if areas is not None else [""] * len(paras)
    containers = list(containers or ())

    def inside_container(i: int) -> bool:
        p0 = paras[i][0]
        return any(a <= p0 < b for a, b in containers)

    blocks, i = [], 0
    while i < len(paras):
        kind = caption_label_kind(text_of(paras[i][2]))
        if not kind:
            i += 1
            continue
        conts, j = [], i + 1
        while (j < len(paras) and not inside_container(j)
               and _caption_continuation(paras[j][2])):
            conts.append(j)
            j += 1
        parts = [paras[k] for k in [i] + conts]
        mergeable = bool(conts) and caption_block_mergeable(parts)
        if mergeable and xml is not None:
            # Only whitespace may sit between the block's paragraphs: anything
            # else (a bookmark, a proof marker) would be dropped by the splice.
            mergeable = all(not xml[parts[k][1]:parts[k + 1][0]].strip()
                            for k in range(len(parts) - 1))
        blocks.append({"kind": kind, "label": i, "continuations": conts,
                       "in_area": bool(areas[i] == kind) if i < len(areas) else False,
                       "mergeable": mergeable})
        i = j
    return blocks


# ---- caption-block repairs (the FMT-T2c merge, the FMT-T2d alignment) -------
# A caption is merged into ONE paragraph by moving the continuation paragraphs'
# run content into the label paragraph and deleting the continuation
# paragraphs. The merge never rewrites text: every run travels verbatim, and
# the only byte added is the single separator space between the label's text
# and the continuation's. The verifier is told about the joins
# (`meta["text_baseline"]`), because the flattened document text then holds one
# paragraph where the input held two.
#
# What the merge refuses (the block is left as it is, and the scan row stays a
# report for the revision arms):
#   * an embedded drawing/object, a text box, a note/comment reference, content
#     control or a tracked change inside the block -- moving those across a
#     paragraph boundary can unbalance what Word owns;
#   * a section break inside the block;
#   * a paragraph whose bytes are not exactly the block's own paragraphs (a
#     bookmark or proof-error element BETWEEN them would be dropped by the
#     splice).
# A Zotero citation field is NOT a refusal: its runs travel verbatim and in
# order, so the field stays balanced, and the LIVE-FIELD FENCE (the field
# signature compare in `fix_package`) rejects the file if it does not.
CAPTION_MERGE_REFUSE_RE = re.compile(
    r"<w:(?:drawing|pict|object|txbxContent|footnoteReference|"
    r"endnoteReference|commentReference|sdt|ins|del|moveFrom|moveTo|cellIns|cellDel)"
    r"(?=[\s/>])")
JOIN_SEP = " "
# CT_RPr child order (ECMA-376 17.3.2): the merge's own overrides are spliced
# in schema order, exactly as `insert_into_ppr` does for pPr children.
RPR_CHILD_ORDER = (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike",
    "dstrike", "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid",
    "vanish", "webHidden", "color", "spacing", "w", "kern", "position", "sz",
    "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign",
    "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath")


def _join_texts(left: str, right: str) -> str:
    """The caption's text after `right` joins it: one space between the parts."""
    if not left or not right:
        return left + right
    if left[-1].isspace() or right[0].isspace():
        return left + right
    return left + JOIN_SEP + right


def _flatten_with_joins(texts: list, joins: list) -> str:
    """The verifier's flattened document text, with the caption joins applied."""
    drop, joined = set(), {}
    for j in joins:
        joined[j["label"]] = j["continuations"]
        drop.update(j["continuations"])
    out = []
    for i, t in enumerate(texts):
        if i in drop:
            continue
        if i in joined:
            text = t
            for c in joined[i]:
                text = _join_texts(text, texts[c])
            out.append(text)
        else:
            out.append(t)
    return "\n".join(t for t in out if t.strip())


def _style_flag(styles: dict, sid: str | None, key: str):
    """A tri-state style property (bold/italic) down the `basedOn` chain."""
    seen = set()
    while sid and sid in (styles or {}) and sid not in seen:
        seen.add(sid)
        if styles[sid].get(key) is not None:
            return styles[sid][key]
        sid = styles[sid].get("basedOn")
    return None


def _effective_run_flag(styles: dict, para_style: str, run: str, key: str):
    """The run's effective bold/italic: its own direct rPr, else the style."""
    node = {"b": "b", "i": "i"}[key]
    rpr = rpr_of(run)
    direct = _tri_state(_find_elem(rpr, node))
    if direct is not None:
        return direct
    return _style_flag(styles, para_style, key)


def _find_elem(frag: str | None, tag: str):
    """The `<w:tag>` ELEMENT of `frag` (ElementTree view), or None."""
    if not frag:
        return None
    try:
        return ET.fromstring(f'<r xmlns:w="{W[1:-1]}">{frag}</r>').find(W + tag)
    except ET.ParseError:
        return None


def _rpr_splice(rpr: str, element: str, tag: str) -> str:
    """Insert `element` (one `<w:tag .../>`) into `rpr` in schema order.

    The scan runs over the rPr's INNER children only: the wrapper itself is not
    a child of the sequence, and treating it as one put the new element after
    `</w:rPr>` -- schema-invalid XML `docx validate` rejected.
    """
    want = RPR_CHILD_ORDER.index(tag) if tag in RPR_CHILD_ORDER else len(RPR_CHILD_ORDER)
    stripped = rpr.rstrip()
    if stripped.endswith("/>"):
        return f"<w:rPr>{element}</w:rPr>"
    head_end = rpr.find(">") + 1
    head, inner = rpr[:head_end], rpr[head_end:]
    close = inner.rfind("</w:rPr>")
    body, tail = (inner[:close], inner[close:]) if close >= 0 else (inner, "")
    # place it after the LAST child that must precede it
    last_before = 0
    for m in re.finditer(r"<w:([A-Za-z]+)(?=[\s/>])", body):
        child = m.group(1)
        idx = RPR_CHILD_ORDER.index(child) if child in RPR_CHILD_ORDER else want
        if idx <= want:
            end = element_span(body, m.start(), child)[1]
            last_before = max(last_before, end)
    return head + body[:last_before] + element + body[last_before:] + tail


def _run_with_override(run: str, element: str, tag: str) -> str:
    """`run` with `element` spliced into its rPr (created when absent)."""
    rpr = rpr_of(run)
    if rpr is None:
        head_end = run.find(">") + 1
        return run[:head_end] + f"<w:rPr>{element}</w:rPr>" + run[head_end:]
    return run.replace(rpr, _rpr_splice(rpr, element, tag), 1)


def _caption_continuation_runs(inner: str, styles: dict, src_style: str,
                               dst_style: str) -> str:
    """`inner` (a continuation's run content) with the label style's own
    bold/italic/size pinned OFF the moved runs where the two styles disagree.

    The label paragraph keeps its pPr, so a caption label styled with a bold
    Caption style would otherwise turn its whole legend bold when the
    continuation is merged into it. A run that already carries its own direct
    property keeps it; only the inherited difference is pinned.
    """
    props = []
    for key in ("b", "i"):
        src, dst = _style_flag(styles, src_style, key), _style_flag(styles, dst_style, key)
        if src != dst:
            props.append(key)
    src_sz, dst_sz = style_sz(styles, src_style), style_sz(styles, dst_style)
    if src_sz and dst_sz and src_sz != dst_sz:
        props.append("sz")
    if not props:
        return inner
    out, pos = [], 0
    for r0, r1, run in runs(inner):
        out.append(inner[pos:r0])
        new_run = run
        for key in props:
            rpr = rpr_of(new_run)
            if elem(rpr, key) is not None:
                continue
            if key in ("b", "i"):
                src = _effective_run_flag(styles, src_style, new_run, key)
                dst = _effective_run_flag(styles, dst_style, new_run, key)
                if src == dst:
                    continue
                value = "0" if not (src or False) else "1"
                latin = f'<w:{key} w:val="{value}"/>'
                complex_script = f'<w:{key}Cs w:val="{value}"/>'
            else:
                latin = f'<w:sz w:val="{src_sz}"/>'
                complex_script = f'<w:szCs w:val="{src_sz}"/>'
            new_run = _run_with_override(new_run, latin, key)
            new_run = _run_with_override(
                new_run, complex_script, "szCs" if key == "sz" else key + "Cs")
        out.append(new_run)
        pos = r1
    out.append(inner[pos:])
    return "".join(out)


def merged_caption_paragraph(parts: list, styles: dict) -> str | None:
    """The single paragraph a caption block collapses to, or None to refuse.

    `parts` is [(start, end, xml)] -- the label paragraph first, then its
    continuation paragraphs, all byte-adjacent in the body. Every run travels
    verbatim; the only bytes added are the separator space(s) and the
    schema-ordered rPr overrides that keep a moved run's own bold/italic/size
    (`_caption_continuation_runs`). Callers must verify the splice's byte range
    covers exactly these paragraphs and nothing between them.
    """
    if not caption_block_mergeable(parts):
        return None

    label = parts[0][2]
    split_label = _caption_para_split(label)
    if split_label is None:
        return None
    head, ppr, content = split_label
    out = head + ppr + content
    text = text_of(label)
    for _, _, cont in parts[1:]:
        split_cont = _caption_para_split(cont)
        if split_cont is None:
            return None
        _, _, ccontent = split_cont
        ctext = text_of(cont)
        if ctext and text and not text[-1:].isspace() and not ctext[:1].isspace():
            out += '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        out += _caption_continuation_runs(ccontent, styles,
                                          _para_style(cont), _para_style(label))
        text = _join_texts(text, ctext)
    return out + "</w:p>"


def _caption_para_split(para: str):
    """(head, pPr, content) of one paragraph, or None when the shape is unusual."""
    head_end = para.find(">") + 1
    if head_end <= 0:
        return None
    head, inner = para[:head_end], para[head_end:]
    ppr = ppr_of(para) or ""
    if ppr and not inner.startswith(ppr):
        return None
    content = inner[len(ppr):]
    if not content.endswith("</w:p>"):
        return None
    return head, ppr, content[:-len("</w:p>")]


def caption_block_mergeable(parts: list) -> bool:
    """Whether `parts` (label + continuations) can be merged without loss.

    The scan and the fixer read this one predicate: a block it refuses is not a
    mechanical row (`fix=editorial`, for the revision arms), so a caption
    carrying a Zotero field or an image never makes the fixer's own
    "mechanical findings cleared" verification fail.
    """
    if not parts or not text_of(parts[0][2]).strip():
        return False
    for _, _, para in parts:
        if CAPTION_MERGE_REFUSE_RE.search(para) or "<w:sectPr" in para:
            return False
        if _caption_para_split(para) is None:
            return False
    return True


def display_rules_apply(doc_name: str) -> bool:
    """Does the venue's display rule apply to this document?

    The rule is about the MANUSCRIPT body: a supplementary-material file, a
    cover letter or a feedback/response document is skipped (see
    DISPLAY_SKIP_NAME_RE), exactly as the M19 length scan skips supplementary
    text. The docx and the text-source paths both call this one test.
    """
    base = str(doc_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not base:
        return True
    if DISPLAY_SKIP_NAME_RE.search(base):
        return False
    return "supp" not in base.lower()


def element_span(xml: str, start: int, tag: str) -> tuple:
    """(start, end) of the whole `<w:tag ...>` element whose open tag is at `start`.

    A hand-edited package can carry an unmatched tag; the span then runs to the
    end of the document instead of raising (the scanner must never take the
    formatting run down).
    """
    tag_end = xml.find(">", start)
    if tag_end == -1:
        return start, len(xml)
    if xml[tag_end - 1] == "/":
        return start, tag_end + 1
    depth = 0
    for m in re.finditer(rf"<w:{tag}(?=[\s/>])|</w:{tag}\s*>", xml[start:]):
        if m.group(0).startswith("</"):
            depth -= 1
            if depth <= 0:
                return start, start + m.end()
        else:
            depth += 1
    return start, len(xml)


def body_block_spans(xml: str) -> list:
    """[('p'|'tbl', start, end, frag)] of the document body, in document order.

    Only the block-level children of the body are walked: the paragraphs inside
    a table cell are part of that table, and a nested table is part of its outer
    table, so neither is returned as a body block of its own.
    """
    out, pos = [], 0
    for m in BODY_BLOCK_TOKENS.finditer(xml):
        if m.start() < pos:
            continue
        s, e = element_span(xml, m.start(), m.group(1))
        out.append((m.group(1), s, e, xml[s:e]))
        pos = e
    return out


def table_shape(frag: str) -> tuple:
    """(rows, columns) of one `<w:tbl>`: rows counted, columns = max cells."""
    rows = _spans(frag, ROW_TOKENS)
    cols = 0
    for _r0, _r1, row in rows:
        cols = max(cols, len(_spans(row, CELL_TOKENS)))
    return len(rows), cols


def table_first_row_cells(frag: str) -> list:
    """The text of the first row's cells (the table's own header, if any)."""
    rows = _spans(frag, ROW_TOKENS)
    if not rows:
        return []
    return [" ".join(text_of(c[2]).split()) for c in _spans(rows[0][2], CELL_TOKENS)]


def display_policy(policy: dict, kind: str) -> dict:
    """The venue's rule for one display kind (empty when none is declared)."""
    cfg = DISPLAY_KINDS[kind]
    raw = (policy or {}).get(cfg["policy_key"])
    if not isinstance(raw, dict):
        return {}
    placement = str(raw.get("placement") or "").strip().lower()
    caption = str(raw.get("caption") or "").strip().lower()
    specials = []
    for entry in raw.get("special") or []:
        if not isinstance(entry, dict):
            continue
        match = str(entry.get("match") or "").strip()
        if not match:
            continue
        specials.append({
            "match": match,
            "placement": str(entry.get("placement") or "").strip().lower(),
            "caption": str(entry.get("caption") or "").strip().lower(),
            "source": str(entry.get("source") or "").strip(),
            "note": str(entry.get("note") or "").strip()})
    out = {"source": str(raw.get("source") or "").strip(),
           "placement": placement if placement in DISPLAY_PLACEMENTS else "",
           "caption": caption if caption in DISPLAY_CAPTION_SIDES else "",
           "note": str(raw.get("note") or "").strip(),
           "special": specials}
    if not (out["placement"] or out["caption"] or out["special"]):
        return {}
    return out


def display_caption_text(text, kind: str) -> str:
    """`text` when it is a caption line of `kind` ("Table 3. ..."), else ""."""
    cfg = DISPLAY_KINDS[kind]
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    return t if (cfg["caption_re"].match(t) or cfg["caption_bare_re"].match(t)) else ""


def _special_item_match(specials: list, candidates: list):
    """The first `special` entry one of whose regexes matches an item's context."""
    for entry in specials or ():
        pat = str((entry or {}).get("match") or "")
        if not pat:
            continue
        try:
            rx = re.compile(pat, re.I)
        except re.error:
            rx = re.compile(re.escape(pat), re.I)
        for cand in candidates:
            if cand and rx.search(cand):
                return entry
    return None


def display_item_rows(xml: str, policy: dict, doc: str, kind: str) -> tuple:
    """(rows, inventory) for one venue display rule over one document body.

    `rows` are the findings the venue's DECLARED rule implies for `kind`
    ([] when the policy declares no rule for it -- the module never invents one,
    and a document the rule does not cover -- see `display_rules_apply` -- gets
    nothing at all). `inventory` carries one dict per item (index, kind, shape,
    first-row header for a table, the caption found and its side, the section it
    sits in, whether it is inside the item's area, and the special-item
    exemption that applied) so the scan artifact and the pipeline's gate can
    name the item, not just the rule.
    """
    cfg = DISPLAY_KINDS[kind]
    pol = display_policy(policy, kind)
    if not display_rules_apply(doc):
        return [], []
    blocks = body_block_spans(xml)
    texts, styles = {}, {}
    for i, (tag, _s, _e, frag) in enumerate(blocks):
        if tag != "p":
            continue
        t = " ".join(text_of(frag).split())
        styles[i] = elem_val(ppr_of(frag), "pStyle") or ""
        if t:
            texts[i] = t

    def attach(i, step):
        """(block index, text) of the nearest non-empty paragraph attached to the
        item on one side; stops at a table (a caption belongs to the item it
        touches, never to the one two blocks away)."""
        j = i + step
        while 0 <= j < len(blocks) and blocks[j][0] == "p":
            if j in texts:
                return j, texts[j]
            j += step
        return None, ""

    def section_of(i):
        j = i - 1
        while j >= 0:
            st = styles.get(j) or ""
            if st.startswith("Heading") and texts.get(j):
                return texts[j]
            j -= 1
        return ""

    def caption_adjacent(i):
        """(block index, text, side) of the item's caption paragraph, or Nones."""
        own = texts.get(i, "")
        if display_caption_text(own, kind):
            # An image and its legend can share one paragraph in Word ("self"):
            # the caption is then neither before nor after, but it IS there.
            return i, own, "self"
        for step, side in ((-1, "before"), (+1, "after")):
            j, t = attach(i, step)
            if display_caption_text(t, kind):
                return j, t, side
        return None, "", ""

    # The ITEMS: a table block for a table; an image paragraph and every
    # COLLECTED legend (a caption paragraph not attached to an image) for a
    # figure.
    items = []                                  # (block index, frag, item kind)
    if kind == "table":
        items = [(i, frag, "object")
                 for i, (tag, _s, _e, frag) in enumerate(blocks) if tag == "tbl"]
    else:
        for i, (tag, _s, _e, frag) in enumerate(blocks):
            if tag == "p" and FIGURE_DRAWING_RE.search(frag):
                items.append((i, frag, "image"))
        attached = set()
        for i, _frag, _k in items:
            cap_i, _t, _side = caption_adjacent(i)
            if cap_i is not None:
                attached.add(cap_i)
        image_blocks = {i for i, _frag, _k in items}
        for i in sorted(texts):
            if i in attached or i in image_blocks \
                    or not display_caption_text(texts[i], kind):
                continue
            items.append((i, blocks[i][3], "legend"))
        items.sort(key=lambda x: x[0])
    if not items:
        return [], []

    # The ITEM AREA: the venue's own tables/figures heading before the last item
    # when the document carries one, else the area starts at the first item that
    # carries a caption of its own (either side; for a figure that is its first
    # attached legend caption or its first collected legend). A document with
    # neither has no verifiable area, so the placement rule cannot be checked
    # there (the caption rule still can).
    last_item_block = items[-1][0]
    anchor = None
    for i, t in texts.items():
        if i < last_item_block and cfg["heading_re"].match(t):
            anchor = i if anchor is None else max(anchor, i)
    if anchor is None:
        for block_i, _frag, item_kind in items:
            if item_kind == "legend":
                anchor = block_i
                break
            cap_i, _t, _side = caption_adjacent(block_i)
            if cap_i is not None:
                anchor = min(block_i, cap_i)
                break
    inventory, rows = [], []
    for n, (block_i, frag, item_kind) in enumerate(items, 1):
        prev_t = attach(block_i, -1)[1]
        if item_kind == "legend":
            cap_t, cap_side = texts.get(block_i, ""), "self"
        else:
            _cap_i, cap_t, cap_side = caption_adjacent(block_i)
        caption = cap_t if display_caption_text(cap_t, kind) else ""
        caption_side = cap_side if caption else ""
        row_count, col_count = (table_shape(frag) if kind == "table" else (0, 0))
        header = table_first_row_cells(frag) if kind == "table" else []
        section = section_of(block_i)
        special = _special_item_match(pol.get("special") or (),
                                      [prev_t, section, " | ".join(header)])
        want_placement = (special or {}).get("placement") or pol.get("placement") or ""
        want_caption = (special or {}).get("caption") or pol.get("caption") or ""
        in_area = (anchor is None) or (block_i >= anchor)
        loc = f"{cfg['noun']} {n} (block {block_i}"
        if item_kind == "legend":
            loc += ", collected legend"
        if section:
            loc += f", section {section[:40]!r}"
        if prev_t:
            loc += f", above: {prev_t[:60]!r}"
        loc += ")"
        entry = {"index": n, "kind": kind, "item": item_kind, "block": block_i,
                 "rows": row_count, "columns": col_count,
                 "header": " | ".join(header)[:160], "caption": caption[:200],
                 "caption_side": caption_side, "section": section[:80],
                 "in_area": bool(in_area), "special": (special or {}).get("match") or "",
                 "wants_placement": want_placement, "wants_caption": want_caption,
                 "document": doc}
        inventory.append(entry)
        if not pol:
            continue
        # `none` (a SPECIAL item the venue itself exempts from captioning) and
        # `any` both mean "no caption rule applies to this item".
        if want_caption in ("before", "after") and item_kind != "legend":
            if not caption:
                rows.append({
                    "rule": cfg["rules"][0], "severity": "medium", "document": doc,
                    "location": loc,
                    "evidence": f"the {cfg['noun']} has no caption"
                                + (f" (above it: {prev_t[:60]!r})" if prev_t else ""),
                    "detail": f"the venue requires a {cfg['noun']} caption on the "
                              f"{want_caption} side of the {cfg['noun']}; give this "
                              f"{cfg['noun']} its own caption paragraph (and cite/edit it like "
                              f"the venue's other {cfg['noun']}s), or move it to the venue's "
                              f"own slot for it"})
            elif caption_side != want_caption and caption_side != "self":
                # A caption inside the item's OWN paragraph ("self", e.g. an
                # image and its legend in one paragraph) is with the item on
                # either reading of the venue's side rule.
                rows.append({
                    "rule": cfg["rules"][1], "severity": "low", "document": doc,
                    "location": loc,
                    "evidence": f"the caption sits {caption_side} the {cfg['noun']}: "
                                f"{caption[:80]!r}",
                    "detail": f"the venue sets the caption {want_caption} the {cfg['noun']}; "
                              f"move the caption paragraph to the {want_caption} side"})
        if want_placement == "end" and not in_area:
            rows.append({
                "rule": cfg["rules"][2], "severity": "medium", "document": doc,
                "location": loc,
                "evidence": f"the {cfg['noun']} appears before the document's "
                            f"{cfg['noun']} area"
                            + (f" ({row_count}x{col_count}; header {entry['header'][:60]!r})"
                               if row_count else ""),
                "detail": f"the venue puts {cfg['noun']}s at the end of the manuscript: move "
                          f"this {cfg['noun']}"
                          + (" (with its caption)" if item_kind != "legend" else "")
                          + f" into the {cfg['noun']} area with the other {cfg['noun']}s -- or, "
                          f"when the venue declares this {cfg['noun']} special (e.g. a "
                          f"graphical abstract), record it in the venue profile's "
                          f"`{cfg['policy_key']}.special` instead of moving it"})
    for r in rows:
        r["fix"] = _fix_kind(r["rule"], policy or {})
        r["protected"] = False
        r["tier"] = tier_of(r["rule"])
    return rows, inventory


def table_conformance_rows(xml: str, policy: dict, doc: str) -> tuple:
    """(rows, inventory) of the venue's TABLE rule over one document body."""
    return display_item_rows(xml, policy, doc, "table")


def figure_conformance_rows(xml: str, policy: dict, doc: str) -> tuple:
    """(rows, inventory) of the venue's FIGURE rule over one document body."""
    return display_item_rows(xml, policy, doc, "figure")


def display_rule_rows_from_text(text: str, policy: dict, doc: str) -> list:
    r"""The display CAPTION rules over one LaTeX/plain-text source.

    Placement is not read from a text source: its pagination and float placement
    are the renderer's, and this scanner never guesses them. A caption-less
    float of a kind the venue requires captions for is reported; a caption that
    is not the caption the venue wants (wrong side of `\begin`/`\end`) is not
    modelled in LaTeX, where the caption lives inside the float by construction.
    """
    if not display_rules_apply(doc):
        return []
    out = []
    kinds = {
        "table": r"table|table\*|longtable|sidewaystable",
        "figure": r"figure|figure\*|sidewaysfigure|wrapfigure",
    }
    for kind, envs in kinds.items():
        cfg = DISPLAY_KINDS[kind]
        pol = display_policy(policy, kind)
        if not pol or pol.get("caption") not in ("before", "after"):
            continue
        for m in re.finditer(r"\\begin\{(" + envs + r")\}([\s\S]*?)\\end\{\1\}", text):
            body = m.group(2)
            if re.search(r"\\caption\s*[\[{]", body):
                continue
            line = text[:m.start()].count("\n") + 1
            if any(s.get("match") and re.search(s["match"], body, re.I)
                   for s in pol.get("special") or ()):
                continue
            out.append({"rule": cfg["rules"][0], "severity": "medium", "document": doc,
                        "location": f"line {line} (\\begin{{{m.group(1)}}})",
                        "evidence": f"the {cfg['noun']} float carries no \\caption",
                        "detail": f"the venue requires a {cfg['noun']} caption; add the float's "
                                  f"own \\caption{{...}}",
                        "fix": _fix_kind(cfg["rules"][0], policy or {}), "protected": False,
                        "tier": tier_of(cfg["rules"][0])})
    return out


def paragraph_first_line_indent(frag: str) -> int:
    """The paragraph's own first-line indent in twips (0 = none).

    `w:hanging` is a LEFT PULL on the following lines, not a first-line
    indent: a bibliography-style hanging paragraph is flush on its first line,
    so reporting the hanging value as a first-line indent misclassifies it in
    the FMT-T8f convention check.
    """
    ind = elem(ppr_of(frag), "ind")
    if ind is None:
        return 0
    for k in ("firstLine", "firstLineChars"):
        v = attr(ind, k)
        if v and re.fullmatch(r"-?\d+", v.strip()):
            n = int(v)
            if n:
                return n
    return 0


def layout_consistency_rows(xml: str, paras: list, title_block_end, doc: str) -> list:
    """FMT-T8f: sibling paragraphs and captions must share one indent convention."""
    styles_of = [elem_val(ppr_of(p), "pStyle") or "" for (_a, _b, p) in paras]
    # The front matter (title block, abstract, keywords) is its own layout family:
    # abstracts are conventionally flush while body paragraphs are first-line
    # indented, so never count the abstract as a body-paragraph outlier. The
    # family ends at the first heading after the keywords line (Introduction ...).
    kw_i = next((i for i, (_a, _b, p) in enumerate(paras)
                 if KEYWORDS_RE.match(text_of(p).strip())), None)
    heading_after_kw = next((i for i in range((kw_i + 1) if kw_i is not None else 0, len(paras))
                             if styles_of[i].startswith("Heading")), None)
    front_end = heading_after_kw if heading_after_kw is not None else 0
    cats = {"caption": [], "body": []}
    for i, (_p0, _p1, p) in enumerate(paras):
        if i < front_end:
            continue
        text = text_of(p).strip()
        if not text:
            continue
        style = elem_val(ppr_of(p), "pStyle") or ""
        if style.startswith("Heading") or style == "Bibliography":
            continue
        if title_block_end is not None and i < title_block_end:
            continue
        # Captions first: "Fig. 1 | ..." would otherwise look like a list item
        # (a 3-character label plus a period), and a caption is never a list.
        if CAPTION_LIKE_RE.match(text):
            cats["caption"].append((i, text, paragraph_first_line_indent(p)))
            continue
        if LIST_LIKE_RE.match(text):
            continue
        # A run-in label ("Software.", "Randomization.") is a heading-like
        # paragraph: flush-left is its convention, so it is not a body outlier.
        first_sentence = re.match(r"^\s*([^.!?]{1,80}[.!?])(?:\s|$)", text)
        if first_sentence and len(first_sentence.group(1).split()) <= 6:
            continue
        if len(text.split()) >= 25:
            cats["body"].append((i, text, paragraph_first_line_indent(p)))
    rows = []
    names = {"caption": "figure/table caption(s)", "body": "body paragraph(s)"}
    for key, items in cats.items():
        if len(items) < 2:
            continue
        indented = [x for x in items if x[2] > 0]
        plain = [x for x in items if x[2] == 0]
        if not (indented and plain):
            continue
        minority = indented if len(indented) <= len(plain) else plain
        examples = "; ".join(f"p{i} {t[:40]!r}" for i, t, _v in minority[:4])
        rows.append({"rule": "FMT-T8f", "severity": "medium", "document": doc,
                     "location": "document",
                     "evidence": (f"{len(indented)} {names[key]} first-line indented, "
                                  f"{len(plain)} not (e.g. {examples})"),
                     "detail": ("one indentation convention per document: every body paragraph "
                                "and every caption in a family must agree (a caption indented "
                                "like its siblings, never half of them) -- align the minority "
                                "with the majority"),
                     "fix": "manual", "protected": False})
    return rows


def front_matter_page_break_row(xml: str, paras: list, doc: str) -> dict:
    """FMT-T8g: title + abstract + keywords must fit the front page.

    Read from Word's own `w:lastRenderedPageBreak` record (the pipeline zeroes
    nothing here; a file that was never rendered carries no markers and the row
    is skipped -- the agents' own render covers that case). The first recorded
    break must come AFTER the keywords line.
    """
    first_break = PAGE_BREAK_RE.search(xml)
    if first_break is None:
        return None
    kw = next(((i, text_of(p).strip()) for i, (_p0, _p1, p) in enumerate(paras)
               if KEYWORDS_RE.match(text_of(p).strip())), None)
    if kw is None:
        return None
    kw_i, kw_text = kw
    # The break element sits INSIDE the paragraph it starts: Word records the
    # break at the beginning of the first paragraph on the new page. So the
    # front matter is split when the first break belongs to the keywords
    # paragraph itself or to any paragraph before it.
    break_para = next((i for i, (p0, p1, _p) in enumerate(paras)
                       if p0 <= first_break.start() < p1), None)
    if break_para is None or break_para > kw_i:
        return None
    after = next(((i, text_of(p).strip()) for i, (p0, _p1, p) in enumerate(paras)
                  if p0 >= paras[break_para][0] and text_of(p).strip()), (break_para, ""))
    return {"rule": "FMT-T8g", "severity": "medium", "document": doc,
            "location": "front page",
            "evidence": (f"the first rendered page break starts paragraph {after[0]} "
                         f"{after[1][:50]!r} (the keywords are at paragraph "
                         f"{kw_i} {kw_text[:40]!r}), so the front page does not hold them "
                         f"together"),
            "detail": ("the front page must carry the title, the authors, the affiliations, "
                       "the abstract AND the keywords together; shorten the front matter (or "
                       "trim lines from the abstract) so the keywords stay on page 1"),
            "fix": "manual", "protected": False}


def cover_letter_page_row(path: Path, pages, source: str) -> dict:
    """FMT-T8h: the cover letter's two-page budget."""
    return {"rule": "FMT-T8h", "severity": "medium", "document": path.name,
            "location": "document",
            "evidence": f"the cover letter is {pages} page(s) ({source}); the budget is 2",
            "detail": ("a cover letter that runs past two pages is not acceptable; trim the "
                       "non-persuading boilerplate (statement blocks, reviewer lists, "
                       "restated affiliations) first, never a claim about the work"),
            "fix": "manual", "protected": False}


# --------------------------------------------------------------------------
# Cover letter vs the MANUSCRIPT template (FMT-CL1)
#
# A journal's official Word template is built for MANUSCRIPT preparation: its
# Title/Author-List front matter, its logo header and its page-number footers
# style an article, not a letter. A cover letter adopts such a template only
# when the JOURNAL ITSELF ships a cover-letter template
# (`policy["cover_letter"].cover_template`); with none, the letter follows the
# journal's own cover-letter guidance and then academic convention. The
# pipeline derives the manuscript template's own front-matter style ids and its
# header/footer part hashes into the policy, so the scan can PROVE -- instead
# of guessing -- that the letter was formatted in the manuscript template. The
# row clears only with the journal's own template/guideline text quoted that
# REQUIRES the formatting; the pipeline's disposition gate enforces that.
# --------------------------------------------------------------------------

# A letter by name: "cover letter", "coverLetter", "letter to the editor", ...
# A response/rebuttal/decision document also carries "letter" and is NOT a
# cover letter. The words are matched as WORDS: a bare `cover|letter` substring
# also named `discovery.docx`, `coverage_stats.docx` and `newsletter.docx` the
# cover letter, so FMT-CL1 checked the wrong file (and the file the sweeps were
# counting as submission prose is a discovery note, not the letter). A word
# starts at the string's start, after a non-letter, or at a lower->UPPER
# camelCase boundary ("plainLetter"), and it ends at a non-lowercase character
# (so "coverage"/"newsletter"/"discovered" do not match, while "coverLetter"
# and "plainLetter" do); the plural is allowed for `letter` so
# "cover_letters.docx" still names the letter.
_WORD_EDGE = r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
COVER_LETTER_NAME_RE = re.compile(
    _WORD_EDGE + r"(?:[Cc]over|COVER)(?![a-z])"
    r"|" + _WORD_EDGE + r"(?:[Ll]etter|LETTER)s?(?![a-z])")
NON_COVER_LETTER_NAME_RE = re.compile(
    r"response|repl(?:y|ies)|rebuttal|point[\s_-]?by[\s_-]?point|"
    r"decision[\s_-]?(?:letter|notice)|referee|reviewer", re.I)


def _names_the_article_type(name: str, type_names=()) -> bool:
    """Is this DOCX name one of the run's own article-type spellings?

    `letter-to-the-editor.docx` names the MANUSCRIPT of a run whose selected
    article type is `letter-to-the-editor`; a trailing version token (`-v2`,
    ` 2`) is ignored and the match is on the FULL name, so `main_letter.docx`
    and `letter_to_the_editor_comments.docx` are not the type's name. The
    spellings come from the run's own policy, so in every OTHER run a
    "letter to the editor" name stays the cover letter it looks like.
    """
    if not type_names:
        return False
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
        if norm.startswith(t + " ") \
                and re.fullmatch(r"(?:v|rev|version|revision|draft)? ?\d{1,3}",
                                 norm[len(t) + 1:]):
            return True
    return False


def is_cover_letter_doc(name: str, article_type_names=()) -> bool:
    """Does this document NAME advertise a cover letter (not a reply letter)?

    `article_type_names` are the run's own article-type spellings: a document
    named for the selected type is that type's manuscript, never the letter.
    """
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    if _names_the_article_type(base, article_type_names):
        return False
    return bool(COVER_LETTER_NAME_RE.search(base)) \
        and not NON_COVER_LETTER_NAME_RE.search(base)


def cover_letter_stamp_rows(path: Path, policy: dict) -> list:
    """FMT-CL1: the cover letter was formatted in the MANUSCRIPT template.

    Two signals, both read from the venue policy the pipeline derives from the
    journal's OWN Word template: the letter USES the manuscript template's
    front-matter style ids (`cover_letter.manuscript_front_matter_styles`), or
    it carries one of the manuscript template's header/footer parts
    byte-identically (`cover_letter.manuscript_furniture_hashes`). Skipped when
    the venue ships a cover-letter template of its own (that file governs the
    letter) and when the venue has no Word template to compare against.
    """
    cv = (policy or {}).get("cover_letter")
    if not isinstance(cv, dict) or not cv:
        return []
    if str(cv.get("cover_template") or "").strip():
        return []
    if not is_cover_letter_doc(path.name, cv.get("manuscript_article_type_names") or ()):
        return []
    want_styles = {str(s).strip() for s in
                   (cv.get("manuscript_front_matter_styles") or []) if str(s).strip()}
    want_parts = {str(h).strip().lower() for h in
                  (cv.get("manuscript_furniture_hashes") or []) if str(h).strip()}
    if not want_styles and not want_parts:
        return []
    used_styles, carried = set(), []
    try:
        with zipfile.ZipFile(path) as pkg:
            xml = pkg.read("word/document.xml").decode("utf-8", "replace")
            used_styles = set(re.findall(r'<w:pStyle w:val="([^"]+)"', xml))
            if want_parts:
                for name in pkg.namelist():
                    if not re.match(r"word/(?:header|footer)\w*\.xml$", name):
                        continue
                    if hashlib.sha256(pkg.read(name)).hexdigest() in want_parts:
                        carried.append(posixpath.basename(name))
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return []
    hits = sorted(used_styles & want_styles)
    if not hits and not carried:
        return []
    template = str(cv.get("manuscript_template") or "the venue's manuscript template")
    bits = []
    if hits:
        bits.append("it uses the manuscript template's front-matter style(s) "
                    + ", ".join(repr(h) for h in hits))
    if carried:
        bits.append("it carries the manuscript template's own header/footer part(s) "
                    + ", ".join(sorted(set(carried))[:3]))
    return [{"rule": "FMT-CL1", "severity": "high", "document": path.name,
             "location": "document",
             "evidence": (f"the cover letter was formatted in the MANUSCRIPT template "
                          f"({template}): " + "; ".join(bits)),
             "detail": ("a cover letter is a submission letter, not a manuscript: when the "
                        "venue ships no cover-letter template it follows the journal's own "
                        "cover-letter guidance and then academic convention, so the manuscript "
                        "template's Title/Author-List front matter and its logo/page furniture "
                        "must not appear. An OK disposition is valid ONLY with the journal's own "
                        "template or guideline text quoted that REQUIRES this formatting"),
             "fix": "editorial", "protected": False, "tier": tier_of("FMT-CL1")}]


# ---- stray empty paragraphs (template-aware) --------------------------------
# A text-only corpus cannot see a blank paragraph at all (the converter keeps
# only non-empty lines), so a stray blank line between "Materials and Methods"
# and its first subsection shipped through two rounds. The rule below separates
# the blanks a VENUE TEMPLATE prescribes (its own empty paragraphs -- the
# front-matter spacer above the title, a placeholder slot between two headings)
# from the ones an author or a converter introduced. Prescribed slots travel in
# `policy["empty_paragraph_slots"]`: signature triples of (own style, previous
# non-empty paragraph's style, next non-empty paragraph's style), heading styles
# normalised to `H1`..`H9` so a template's `Heading 1` matches a manuscript's
# `Heading1`.

_HEADING_STYLE_RE = re.compile(r"heading[\s_-]*([1-9])\b", re.I)


def _para_style(para: str) -> str:
    return elem_val(ppr_of(para), "pStyle") or ""


def _style_kind(style: str) -> str:
    """`H<n>` for a heading style id, '' otherwise (style ids are venue data)."""
    m = _HEADING_STYLE_RE.search(style or "")
    return f"H{m.group(1)}" if m else ""


def _style_key(style: str) -> str:
    return _style_kind(style) or (style or "")


def empty_paragraph_slots_from_template(template) -> list:
    """The signature triples of the EMPTY paragraphs one template prescribes.

    `template` is a .docx path or a `word/document.xml` string. The signature
    normalises heading styles to their level (H1..H9) and leaves other styles
    by id; the pipeline puts the union of a venue's main and supplementary
    templates into `format_policy.empty_paragraph_slots`.
    """
    if isinstance(template, (str, Path)) and not str(template).lstrip().startswith("<"):
        try:
            with zipfile.ZipFile(template) as pkg:
                xml = pkg.read("word/document.xml").decode("utf-8", "replace")
        except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
            return []
    else:
        xml = str(template)
    paras = paragraphs(xml)
    texts = [text_of(p[2]).strip() for p in paras]
    styles = [_style_key(_para_style(p[2])) for p in paras]
    slots = []
    for idx in range(len(paras)):
        if texts[idx] or has_drawing(paras[idx][2]) or has_field(paras[idx][2]):
            continue
        prev_style = next((styles[j] for j in range(idx - 1, -1, -1) if texts[j]), "")
        next_style = next((styles[j] for j in range(idx + 1, len(styles)) if texts[j]), "")
        key = [styles[idx], prev_style, next_style]
        if key not in slots:
            slots.append(key)
    return slots


def prescribed_empty_indices(paras: list, policy: dict) -> set:
    """Indices of empty paragraphs the venue/template prescribes (never touched).

    An empty paragraph BEFORE the first non-empty paragraph of the body is
    always prescribed: that is the title-page spacer the journal's own Word
    template carries above the article title, and the operator asked for it to
    survive. Everything else needs a signature match against
    `policy["empty_paragraph_slots"]`; with no slots recorded nothing else is
    exempt.
    """
    slots = set()
    for s in policy.get("empty_paragraph_slots") or []:
        try:
            if len(s) == 3:
                slots.add(tuple(str(x) for x in s))
        except TypeError:
            continue
    texts = [text_of(p[2]).strip() for p in paras]
    styles = [_style_key(_para_style(p[2])) for p in paras]
    first_nonempty = next((i for i, t in enumerate(texts) if t), len(paras))
    out = set()
    for idx, (_, _, para) in enumerate(paras):
        if texts[idx] or has_drawing(para) or has_field(para):
            continue
        if idx < first_nonempty:
            out.add(idx)
            continue
        if not slots:
            continue
        prev_style = next((styles[j] for j in range(idx - 1, -1, -1) if texts[j]), "")
        next_style = next((styles[j] for j in range(idx + 1, len(styles)) if texts[j]), "")
        if (styles[idx], prev_style, next_style) in slots:
            out.add(idx)
    return out


def _table_paragraph_indices(xml: str, paras: list) -> set:
    """Indices of the paragraphs that live inside a `<w:tbl>` (a table cell's own).

    A `w:tc` must hold at least one block-level element: splicing out a cell's
    only (empty) paragraph leaves `<w:tc></w:tc>`, which Word reports as a
    corrupt file, and the fixer's well-formedness/text-identity verification
    cannot see it. Table paragraphs are therefore never stray.
    """
    spans = _table_spans(xml)
    if not spans:
        return set()
    return {i for i, (p0, _p1, _frag) in enumerate(paras)
            if any(a <= p0 < b for a, b in spans)}


def _table_spans(xml: str) -> list:
    """(start, end) spans of the document's `<w:tbl>` blocks, NESTING-aware.

    Balance the `<w:tbl>`/`</w:tbl>` pairs: a lazy `<w:tbl>.*?</w:tbl>` regex
    stops at the FIRST `</w:tbl>`, so with a NESTED table (a table inside a cell)
    everything of the outer table after the inner one escapes the span -- the
    paragraphs of a following cell lose their table-cell protection (the fixer
    could then splice out a cell's ONLY paragraph, leaving `<w:tc></w:tc>`, a
    file Word reports as corrupt) and the heading detector read those cell
    paragraphs as body text. Both call sites use this one definition.
    """
    if not xml:
        return []
    spans, depth, start = [], 0, 0
    for m in re.finditer(r"<w:tbl(?=[\s>])|</w:tbl>", xml):
        if m.group(0) == "</w:tbl>":
            depth = max(0, depth - 1)
            if depth == 0:
                spans.append((start, m.end()))
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return spans


def stray_empty_paragraph_groups(paras: list, policy: dict, xml: str = None) -> tuple:
    """([(indices_to_delete, kind)], prescribed_indices).

    Two classes are stray: a blank line ATTACHED to a heading (immediately
    before or after it -- the heading's own style carries the spacing, and this
    is the "extra blank line between 2 Materials and Methods and 2.1 Study
    design" case), and a run of empty paragraphs longer than
    `max_empty_paragraph_run` (only the non-prescribed excess is deleted; a
    template-prescribed spacer counts as one of the allowed blanks). `kind` is
    "heading" or "run".

    `xml` is the document the paragraphs were read from; when it is given,
    paragraphs inside a table cell are never in a delete group (see
    `_table_paragraph_indices`).
    """
    prescribed = prescribed_empty_indices(paras, policy)
    texts = [text_of(p[2]).strip() for p in paras]
    in_table = _table_paragraph_indices(xml, paras)
    is_empty = [not texts[i] and i not in in_table
                and not has_drawing(paras[i][2])
                and not has_field(paras[i][2])                # a field run is content
                and not PAGEBREAK_RE.search(paras[i][2])       # FMT-S1 owns breaks
                for i in range(len(paras))]

    def heading_adjacent(i: int) -> bool:
        prev_style = next((_para_style(paras[j][2]) for j in range(i - 1, -1, -1)
                           if texts[j]), "")
        next_style = next((_para_style(paras[j][2]) for j in range(i + 1, len(texts))
                           if texts[j]), "")
        return bool(_style_kind(prev_style) or _style_kind(next_style))

    keep = max(0, int(policy.get("max_empty_paragraph_run", 1)))
    groups = []
    i = 0
    while i < len(paras):
        if not is_empty[i]:
            i += 1
            continue
        j = i
        while j < len(paras) and is_empty[j]:
            j += 1
        run = list(range(i, j))
        free = [k for k in run if k not in prescribed]
        if free:
            if any(heading_adjacent(k) for k in free):
                groups.append((free, "heading"))
            else:
                room = max(0, keep - (len(run) - len(free)))
                drop = free[room:]
                if drop:
                    groups.append((drop, "run"))
        i = j
    return groups, prescribed


def stray_empty_paragraph_rows(paras: list, policy: dict, doc: str, xml: str = None) -> list:
    """FMT-S8 (blank attached to a heading) / FMT-S6 (run beyond the cap)."""
    groups, _prescribed = stray_empty_paragraph_groups(paras, policy, xml)
    rows = []
    for drop, kind in groups:
        lo, hi = drop[0], drop[-1]
        if kind == "heading":
            rows.append({"rule": "FMT-S8", "severity": "low",
                         "document": doc, "location": (f"p{lo}" if lo == hi else f"p{lo}-p{hi}"),
                         "evidence": ("a stray empty paragraph attached to a heading "
                                      "(the heading style already carries the spacing)"
                                      if lo == hi else
                                      f"{len(drop)} stray empty paragraphs attached to a "
                                      "heading (the heading style already carries the spacing)"),
                         "detail": ("a blank line next to a section heading renders as an extra "
                                    "empty line; delete it unless the journal's own template "
                                    "prescribes that exact slot"),
                         "fix": "mechanical", "protected": False, "tier": tier_of("FMT-S8")})
        else:
            rows.append({"rule": "FMT-S6", "severity": "low",
                         "document": doc, "location": (f"p{lo}" if lo == hi else f"p{lo}-p{hi}"),
                         "evidence": (f"{len(drop)} extra consecutive empty paragraph(s) "
                                      f"(cap {policy.get('max_empty_paragraph_run', 1)})"),
                         "detail": "stray empty paragraphs shift pagination and create blank space",
                         "fix": "mechanical", "protected": False, "tier": tier_of("FMT-S6")})
    return rows


# ---- text hygiene: spaces at line edges, doubled spacing, doubled words -----
# All spans are offsets into the paragraph's TEXT (`text_of`), so the fixer can
# rewrite them through `rewrite_text_spans` and record exactly what changed.

_TEXT_EDGE_TOKENS = re.compile(
    r"<w:t(?:\s[^>]*)?>.*?</w:t>|<w:br(?=[\s/>])[^>]*/>|<w:cr(?=[\s/>])[^>]*/>|"
    r"<w:tab(?=[\s/>])[^>]*/>", re.S)

# Articles and prepositions where a doubled word is a typo. "in" is deliberately
# absent: "studies in in vitro systems" is a valid construction, and a
# mechanical rule must never rewrite it.
_DOUBLED_WORDS = ("the", "a", "an", "of", "and", "or", "but", "for", "with", "at",
                  "by", "on", "to", "is", "are", "was", "were", "it")
_DOUBLED_WORD_RE = re.compile(r"\b(" + "|".join(_DOUBLED_WORDS) + r")\s+\1\b", re.I)
_DOUBLE_SPACE_RE = re.compile(r"(?<=\S) {2,}(?=\S)")
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +(?=[,.;:!?])")
_SPACE_AFTER_OPEN_RE = re.compile(r"(?<=[([])[ \t]+")
_ZERO_WIDTH_RE = re.compile("[\u200b\u200e\u200f\u2060\ufeff]")
_MATH_LINE_RE = re.compile(r"[=∑∈∉∕√±×÷≤≥≈∝∫∞]")
_MISSING_SPACE_RE = re.compile(r"(?<![A-Za-z0-9/])([a-z]{2,}),([a-z]{2,})\b")

# FMT-G4 (2026-10-15): a comma with NO space after it inside a list of names,
# versions or keywords. `_MISSING_SPACE_RE` above covers the lowercase shape
# ("default,however"); the shapes that SHIPPED and no rule saw are the other two:
#   * "<version-or-id>,<Capitalised name>" -- the CNB Reporting Summary's own
#     "AneuFinder 1.34.0,copynumber 1.38.0" / "FLCNA 89902690,SCYN eeef200" /
#     "CaSpER 0.2.0,CONICSmat 0.0.0.1", rendered verbatim into the submitted PDF;
#   * "<lowercase word>,<Capitalised word>" -- the CNB supplementary .bib's own
#     keyword lists ("DNA aneuploidy,Molecular subtyping,Prognosis").
# Both are the same editorial defect (an editor inserts one space). Each shape
# is narrowed by the false positives the real corpora produced, and the test
# suite names every one of them:
#   * a version string (`1.34.0`, `0.2.0`) or an identifier that ends in a short
#     hex/alnum run (`89902690`, `d7c7790`, `3c9047f`) -- the second lookahead
#     needs TWO following characters, because a citation key continues with one
#     ("(Mallory et al., 2020a,b)") and an item never does;
#   * a lowercase word, or an acronym that contains a lowercase letter, followed
#     by a Capitalised word -- the .bib keyword lists. A bare all-caps two-letter
#     token ("AL,Mehling") is deliberately NOT matched: it is as likely to be an
#     author's initials as a glued item, and `et al.,2020` never matches because
#     what follows a comma there is not a word.
_COMMA_GLUE_ID_RE = re.compile(
    r"(?<![A-Za-z0-9,.;:/-])(?:[\w+-]*\d[0-9a-f]{3,}|(?:\d+\.)+\d+),(?=[A-Za-z0-9]{2})")
_COMMA_GLUE_WORD_RE = re.compile(
    r"(?<![A-Za-z0-9,.;:/-])(?:[a-z][a-z]+|(?:[A-Z]*[a-z])[A-Z]{2,}),(?=[A-Z][a-z])")


def comma_glue_rows(text: str, limit: int = 24) -> list:
    """FMT-G4 rows in ONE text (a paragraph, a .tex/.bib line, a PDF's text).

    Returns [{"rule", "severity", "evidence", "detail"}] -- one row per glued
    comma, with the surrounding words as evidence, so a reviewer can see the
    list it belongs to instead of a bare offset. The rule is EDITORIAL: the
    repair is one space, but a mechanical writer that guessed at it would also
    rewrite the citation ranges this rule exists to leave alone.
    """
    rows = []
    s = str(text or "")
    seen = set()
    for m in _COMMA_GLUE_ID_RE.finditer(s):
        if m.end() in seen:
            continue
        seen.add(m.end())
        rows.append({
            "rule": "FMT-G4", "severity": "medium",
            "evidence": f"no space after the comma: {s[max(0, m.start()-30):m.end()+30]!r}",
            "detail": "a comma inside a list of names/versions/keywords is followed "
                      "directly by the next item: insert one space after the comma"})
        if len(rows) >= limit:
            return rows
    for m in _COMMA_GLUE_WORD_RE.finditer(s):
        if m.end() in seen:
            continue
        seen.add(m.end())
        rows.append({
            "rule": "FMT-G4", "severity": "medium",
            "evidence": f"no space after the comma: {s[max(0, m.start()-30):m.end()+30]!r}",
            "detail": "a comma inside a list of names/versions/keywords is followed "
                      "directly by the next item: insert one space after the comma"})
        if len(rows) >= limit:
            break
    return rows


def visual_text_lines(para: str) -> list:
    """[(start, end)] text-space spans of a paragraph's rendered lines.

    `w:br`/`w:cr` start a new line; `w:tab` starts a new alignment field, and a
    space right after one is redundant either way. The break itself is ONE
    character of `text_of` (its newline) and sits BETWEEN the spans: a trailing
    space is the last character of one line, and deleting it must not delete the
    line break with it.
    """
    lines, start, offset = [], 0, 0
    for m in _TEXT_EDGE_TOKENS.finditer(para):
        tok = m.group(0)
        if tok.startswith("<w:t"):
            offset += len(unesc(tok[tok.find(">") + 1:tok.rfind("<")]))
        else:
            lines.append((start, offset))
            offset += 1                      # the break's own newline in text space
            start = offset
    lines.append((start, offset))
    return lines


def hygiene_spans(para: str) -> list:
    """[span dicts] of every text-hygiene edit in one paragraph.

    `fix` says who owns the edit: FMT-P4 (a space at a line edge) and FMT-G1
    (a doubled article/preposition) are mechanical and the fixer applies them;
    FMT-P3 (doubled spaces, bracket spacing, zero-width marks), FMT-G2 (a
    possible lowercase sentence start) and FMT-G3 (a missing space after
    punctuation) are reported for the editing arms, because mathematics,
    notation and subscripts legitimately carry those shapes.

    FMT-X2's two GLUE shapes are mechanical here as well (2026-10-15): a
    front-matter label fused to its value (`Correspondence:Zhen Xie`) and an
    e-mail address fused to the name before it are each ONE missing space, and
    the repair is verifiable as an insertion (the fixer's recorded edit keeps the
    text identical otherwise). The ambiguous shapes stay with the editing arms:
    when the address's local part is neither a prefix nor a suffix of the word it
    touches, the correct split needs a reader's judgement, so no span is emitted
    and the FMT-X2 row stands.
    """
    out = []
    text = text_of(para)
    if not text.strip():
        return out
    # ---- front-matter glue (FMT-X2) ------------------------------------------
    for m in FURNITURE_LABEL_RE.finditer(text):
        if m.end() >= len(text) or text[m.end()].isspace():
            continue
        if text[m.end():m.end() + 2] == "//":       # a URL scheme, not glue
            continue
        out.append({"rule": "FMT-X2", "fix": "mechanical", "start": m.end(), "end": m.end(),
                    "repl": " ",
                    "evidence": f"{text[max(0, m.start() - 8):m.end() + 18]!r}: no space after "
                                f"the label's colon",
                    "detail": "insert the missing space between the front-matter label and its "
                              "value"})
    for m in EMAIL_RE.finditer(text):
        word_m = EMAIL_GLUE_BEFORE_RE.search(text[:m.start()])
        local = m.group(0).split("@", 1)[0]
        cut = None
        if word_m:
            word = word_m.group(0)
            if local and len(word) > len(local) and word.lower().endswith(local.lower()):
                cut = m.start() - len(local)
            elif local and len(word) > len(local) and word.lower().startswith(local.lower()):
                cut = m.start() + len(local)
        if cut is None:
            # The match ITSELF carries the glue (`Xiezhenxie@host`). Splitting it
            # needs to know where the author's name ends and the address begins,
            # and a guess here REWRITES a correct address into a wrong one (the
            # first cut of this repair turned a healthy
            # `zhenxie@tsinghua.edu.cn` into `zhen xie@tsinghua.edu.cn`). No span
            # is emitted: the FMT-X2 row stands, the review/revise arms fix it in
            # prose, and the published copy keeps the glue REPORTED (advisory)
            # rather than silently re-spaced.
            continue
        out.append({"rule": "FMT-X2", "fix": "mechanical", "start": cut, "end": cut, "repl": " ",
                    "evidence": f"{text[max(0, m.start() - 24):m.end() + 12]!r}: the address is "
                                f"glued to the word before it",
                    "detail": "insert the missing space between the name and the e-mail address"})
    for s, e in visual_text_lines(para):
        seg = text[s:e]
        if not seg:
            continue
        lead = len(seg) - len(seg.lstrip())
        trail = len(seg) - len(seg.rstrip())
        if lead and lead == len(seg):
            out.append({"rule": "FMT-P4", "fix": "mechanical", "start": s, "end": e,
                        "repl": "",
                        "evidence": "a whitespace-only line inside the paragraph",
                        "detail": "delete the stray spaces; the paragraph break already "
                                  "renders the line"})
            continue
        if lead:
            out.append({"rule": "FMT-P4", "fix": "mechanical", "start": s, "end": s + lead,
                        "repl": "",
                        "evidence": f"a leading space at the start of a line: {seg[:48]!r}",
                        "detail": "a space after a line break or at a paragraph start "
                                  "renders as an unintended indent"})
        if trail:
            out.append({"rule": "FMT-P4", "fix": "mechanical", "start": e - trail, "end": e,
                        "repl": "",
                        "evidence": f"a trailing space at the end of a line: {seg[-48:]!r}",
                        "detail": "a dangling space at the end of a visual line; delete it"})
    if not _MATH_LINE_RE.search(text):
        for m in _DOUBLE_SPACE_RE.finditer(text):
            out.append({"rule": "FMT-P3", "fix": "editorial", "start": m.start(),
                        "end": m.end(), "repl": " ",
                        "evidence": f"double space: {text[max(0, m.start()-30):m.end()+30]!r}",
                        "detail": "use one space between words; when the spacing is "
                                  "intentional alignment, record that in the disposition"})
        for m in _SPACE_BEFORE_PUNCT_RE.finditer(text):
            out.append({"rule": "FMT-P3", "fix": "editorial", "start": m.start(),
                        "end": m.end(), "repl": "",
                        "evidence": f"space before punctuation: "
                                    f"{text[max(0, m.start()-30):m.end()+30]!r}",
                        "detail": "no space belongs before a punctuation mark"})
        for m in _SPACE_AFTER_OPEN_RE.finditer(text):
            out.append({"rule": "FMT-P3", "fix": "editorial", "start": m.start(),
                        "end": m.end(), "repl": "",
                        "evidence": f"space after an opening bracket: "
                                    f"{text[max(0, m.start()-30):m.end()+30]!r}",
                        "detail": "no space belongs right after '(' or '['"})
    for m in _ZERO_WIDTH_RE.finditer(text):
        out.append({"rule": "FMT-P3", "fix": "editorial", "start": m.start(), "end": m.end(),
                    "repl": "",
                    "evidence": f"zero-width/bidi mark at offset {m.start()}",
                    "detail": "an invisible control character; remove it unless the text "
                              "is RTL and the mark is meaningful"})
    for m in _DOUBLED_WORD_RE.finditer(text):
        out.append({"rule": "FMT-G1", "fix": "mechanical", "start": m.start(), "end": m.end(),
                    "repl": m.group(1),
                    "evidence": f"doubled word: {text[max(0, m.start()-30):m.end()+30]!r}",
                    "detail": "the same article/preposition twice in a row"})
    for m in _MISSING_SPACE_RE.finditer(text):
        out.append({"rule": "FMT-G3", "fix": "editorial", "start": max(0, m.end() - 1),
                    "end": max(0, m.end() - 1), "repl": None,
                    "evidence": f"missing space after punctuation: "
                                f"{text[max(0, m.start()-30):m.end()+30]!r}",
                    "detail": "insert one space after the comma unless the token is a "
                              "subscript or notation"})
    for r in comma_glue_rows(text):
        # FMT-G4 needs no offsets: the repair (one space) is editorial, and the
        # row is disposed by the editing arms like every other `fix=editorial`
        # hygiene row. The offset fields stay for the schema's shape.
        out.append({"rule": r["rule"], "fix": "editorial", "start": -1, "end": -1,
                    "repl": None, "evidence": r["evidence"], "detail": r["detail"]})
    return out


def hygiene_rows(paras: list, is_ref: list, doc: str, protected=None) -> list:
    """One row per text-hygiene instance (references and empty paragraphs skipped).

    `protected` is the per-paragraph `field_result_text_ranges` list: a
    mechanical hygiene edit inside a live field's result is reported as
    `fix=style-field` (protected) so the fixer, which must never rewrite a
    field result, is not asked to apply it.
    """
    rows = []
    for idx, (_, _, para) in enumerate(paras):
        if idx < len(is_ref) and is_ref[idx]:
            continue
        text = text_of(para)
        if not text.strip():
            continue
        prot = protected[idx] if protected and idx < len(protected) else []
        for sp in hygiene_spans(para):
            if sp["rule"] == "FMT-X2":
                # The front-matter GLUE spans are APPLIED by the fixer but never
                # reported from here: the authoritative row for that class is
                # `correspondence_glue_rows`, which reports `fix=editorial` (the
                # shapes the mechanical repair cannot split stay for the editing
                # arms). Reporting them as mechanical rows made the fixer's own
                # verification fail on a document it had just repaired -- the
                # residue is the unsplittable name/address glue by design.
                continue
            in_result = bool(prot) and in_field_result(prot, sp["start"], sp["end"])
            rows.append({"rule": sp["rule"], "severity": "low", "document": doc,
                         "location": f"p{idx}", "evidence": sp["evidence"],
                         "detail": sp["detail"],
                         "fix": ("style-field" if (in_result and sp["fix"] == "mechanical")
                                 else sp["fix"]),
                         "protected": in_result, "tier": tier_of(sp["rule"])})
    return rows


# A conservative capitalization check: a lowercase word after a sentence-ending
# mark, restricted to words that almost never start a sentence in lowercase and
# skipping the abbreviation tails that end with a period. It reports (the arms
# decide); it never edits.
_SENTENCE_START_WORDS = frozenset(
    "the this these those it they we he she you i in on at for with by from as that "
    "which who whose is are was were be been being have has had not no all any each "
    "every more most other such than then there here when where while if because "
    "however thus therefore and but or so also can could may might must should would "
    "will do does did both few many some our their its his her your my one two three".split())
_ABBREV_TAILS = ("e.g.", "i.e.", "cf.", "vs.", "etc.", "al.", "fig.", "figs.", "eq.",
                 "eqs.", "ref.", "refs.", "sec.", "no.", "approx.", "ca.", "dr.",
                 "prof.", "st.", "mr.", "ms.", "mrs.", "v.", "vol.", "pp.", "ed.",
                 "eds.", "min.", "max.", "inc.", "ltd.", "co.", "univ.", "dept.",
                 "ave.", "suppl.")


def capitalization_rows(paras: list, is_ref: list, doc: str) -> list:
    """FMT-G2: a possible lowercase sentence start the arms should look at."""
    rows = []
    for idx, (_, _, para) in enumerate(paras):
        if idx < len(is_ref) and is_ref[idx]:
            continue
        text = text_of(para)
        if len(text) < 40:
            continue
        for m in re.finditer(r"(?<=[.!?])\s+([a-z]{2,})\b", text):
            word = m.group(1)
            if word not in _SENTENCE_START_WORDS:
                continue
            before = text[:m.start()].rstrip()
            tail = before[-24:].lower()
            if any(tail.endswith(a) for a in _ABBREV_TAILS):
                continue
            if re.search(r"(?:^|[^A-Za-z])[A-Za-z]\.$", before):
                continue                     # an initial ("J. zhang" is a name)
            rows.append({"rule": "FMT-G2", "severity": "low", "document": doc,
                         "location": f"p{idx}",
                         "evidence": f"possible lowercase sentence start: "
                                     f"{text[max(0, m.start()-40):m.end()+40]!r}",
                         "detail": "capitalize the first word of the sentence unless the "
                                   "lowercase token is a unit, gene, chemical or species name "
                                   "(then record that in the disposition)",
                         "fix": "editorial", "protected": False, "tier": tier_of("FMT-G2")})
    return rows


# ---- style conventions: fonts, paragraph formatting, heading levels ---------
# The classes a copy editor fixes by hand. The scanner enumerates the objective
# outliers inside one paragraph style (a direct font override, direct spacing /
# indentation / alignment on some paragraphs and not others) and a heading-level
# jump, so the review disposes each row and the revision/integration arms align
# the package; nothing here is edited mechanically (a gene name in a monospace
# font and a deliberately centred line are legitimate).

_FONT_RPR_RE = re.compile(r"<w:rFonts(?=[\s/>])[^>]*/>")


def _run_font(run: str) -> str:
    """The run's DIRECT font family ('' when the run inherits it)."""
    rpr = rpr_of(run)
    m = _FONT_RPR_RE.search(rpr or "")
    if not m:
        return ""
    return attr(m.group(0), "ascii") or attr(m.group(0), "hAnsi") or ""


def _headings_in(paras: list) -> list:
    """[(idx, level)] for paragraphs whose style is a heading."""
    out = []
    for idx, (_, _, para) in enumerate(paras):
        kind = _style_kind(_para_style(para))
        if kind:
            out.append((idx, int(kind[1:])))
    return out


def style_convention_rows(paras: list, styles: dict, doc: str) -> list:
    """FMT-T10a..e: direct formatting drift and heading-level anomalies."""
    rows = []
    # (a) more than one DIRECT font among the letter-bearing plain runs of one
    # paragraph (subscripts, character styles and non-letter runs excluded).
    for idx, (_, _, para) in enumerate(paras):
        if len(text_of(para).split()) < 6:
            continue
        fonts = {}
        for _, _, run in runs(para):
            rtext = text_of(run)
            if not re.search(r"[A-Za-z]{2,}", rtext):
                continue
            rpr = rpr_of(run)
            if elem_val(rpr, "vertAlign") or elem_val(rpr, "rStyle"):
                continue
            font = _run_font(run)
            if font:
                fonts.setdefault(font, []).append(rtext[:20])
        if len(fonts) > 1:
            names = ", ".join(f"{f!r} x{len(v)}" for f, v in sorted(fonts.items()))
            rows.append({"rule": "FMT-T10a", "severity": "low", "document": doc,
                         "location": f"p{idx}",
                         "evidence": f"one paragraph carries {len(fonts)} direct fonts: {names}",
                         "detail": "keep one font convention per paragraph (the template's "
                                   "style owns the family); a deliberate monospace token is "
                                   "the exception to record",
                         "fix": "editorial", "protected": False, "tier": tier_of("FMT-T10a")})
    # (b..d) direct spacing / indentation / alignment overrides that only SOME
    # paragraphs of one style carry: the style owns the typography.
    groups = defaultdict(list)
    headings = _headings_in(paras)
    first_heading = headings[0][0] if headings else 0
    for idx, (_, _, para) in enumerate(paras):
        text = text_of(para).strip()
        # Front matter, headings, legends, captions and short table cells are
        # their own layout families: their spacing is policy/template-owned
        # (the venue's legend-spacing rule is applied mechanically), so they are
        # not "drift" in the body prose's convention.
        if (not text or idx < first_heading or len(text.split()) < 8
                or not para.strip() or LEGEND_RE.match(text)
                or TABLE_CAPTION_RE.match(text) or FIGURE_CAPTION_RE.match(text)):
            continue
        if _para_style(para) == "Caption":
            continue
        style = _para_style(para) or "(body)"
        ppr = ppr_of(para)
        groups[style].append((idx, ppr or ""))
    checks = (("FMT-T10b", "spacing", "vertical paragraph spacing",
               "horizontal-and-vertical spacing"),
              ("FMT-T10c", "ind", "indentation",
               "indentation"),
              ("FMT-T10d", "jc", "alignment", "alignment"))
    for style, members in sorted(groups.items()):
        if len(members) < 4:
            continue
        for rule, tag, label, what in checks:
            direct = [idx for idx, ppr in members if elem(ppr, tag)]
            if not direct or len(direct) == len(members):
                continue                    # none, or every paragraph carries one
            if direct[-1] - direct[0] + 1 == len(direct):
                continue                    # one contiguous block (deliberate front matter)
            listed = ", ".join(f"p{i}" for i in direct[:4])
            if len(direct) > 4:
                listed += f", +{len(direct) - 4} more"
            sigs = Counter(elem(ppr, tag) for idx, ppr in members if elem(ppr, tag))
            example = sigs.most_common(1)[0][0][:120]
            rows.append({"rule": rule, "severity": "low", "document": doc,
                         "location": f"p{direct[0]}",
                         "evidence": (f"style {style!r}: {len(members)} paragraph(s), "
                                      f"{len(direct)} carry a direct {label} ({listed}); "
                                      f"e.g. {example!r}"),
                         "detail": (f"the same style renders with two different "
                                    f"{what} conventions; let the style own it (remove the "
                                    "direct override) or apply it consistently"),
                         "fix": "editorial", "protected": False, "tier": tier_of(rule)})
    # (e) a heading level jump (H1 -> H3 skips a level).
    prev = None
    for idx, level in _headings_in(paras):
        if prev is not None and level > prev + 1:
            rows.append({"rule": "FMT-T10e", "severity": "low", "document": doc,
                         "location": f"p{idx}",
                         "evidence": (f"heading level {level} follows level {prev} "
                                      f"({'->'.join(f'H{n}' for n in (prev, level))})"),
                         "detail": ("a heading level may not be skipped; demote it to the "
                                    "missing level or restore the intermediate heading"),
                         "fix": "editorial", "protected": False, "tier": tier_of("FMT-T10e")})
        prev = level
    # (f) a heading whose section holds exactly ONE child heading: FMT-T9k's
    # "lone division" one level up. A section that divides at all divides into
    # more than one part -- the lone subsection is either the parent's own
    # content (promote it) or the section is missing the sibling it needs.
    heads = _headings_in(paras)
    for k, (idx, level) in enumerate(heads):
        kids = []
        for idx2, level2 in heads[k + 1:]:
            if level2 <= level:
                break
            if level2 == level + 1:
                kids.append(idx2)
        if len(kids) != 1:
            continue
        parent = text_of(paras[idx][2]).strip()
        child = text_of(paras[kids[0]][2]).strip()
        rows.append({"rule": "FMT-T10f", "severity": "low", "document": doc,
                     "location": f"p{idx}",
                     "evidence": (f"the section {parent[:60]!r} (H{level}) holds exactly "
                                  f"ONE subsection {child[:60]!r} (H{level + 1})"),
                     "detail": ("a section that divides at all divides into more than one "
                                "part: promote the lone subsection into its parent, or add "
                                "the sibling the section is missing"),
                     "fix": "editorial", "protected": False, "tier": tier_of("FMT-T10f")})
    return rows


# ---- embedded-image geometry: the delivered aspect ratio vs the pixels ------
# A figure rescaled without keeping its ratio is a real defect (it changes the
# plotted geometry): the supplementary figures of the 2026-10-04 run were shown
# at 1.199 and 1.333 while their PNGs are 1.749 and 1.596. The scanner resolves
# every `wp:extent`/VML size to its media part and compares the delivered ratio
# with the image's own; the fixer keeps the width and restores the height.

_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|bmp|tiff?|svg|emf|wmf)$", re.I)


def image_pixel_size(data: bytes):
    """(width, height) of PNG/JPEG/GIF/BMP/TIFF/SVG/EMF/WMF bytes, or None.

    Vector art carries its own aspect ratio too: an SVG's `viewBox`/width+
    height, an EMF header's `rclFrame` and a placeable WMF's bounding box. The
    unit does not matter (only the ratio is compared).
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", data[16:24])
            return (w, h) if w and h else None
        if data[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", data[6:10])
            return (w, h) if w and h else None
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker == 0xFF or 0xD0 <= marker <= 0xD8 or marker == 0x01:
                    i += 2
                    continue
                if marker == 0xD9:
                    break
                seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return (w, h) if w and h else None
                i += 2 + seglen
            return None
        if data[:2] == b"BM":
            w, h = struct.unpack("<ii", data[18:26])
            return (abs(w), abs(h)) if w and h else None
        if data[:4] == b"\x01\x00\x00\x00" and len(data) >= 40:
            # EMF header: rclFrame (0.01 mm units) at offset 24.
            left, top, right, bottom = struct.unpack("<4i", data[24:40])
            w, h = right - left, bottom - top
            return (w, h) if w > 0 and h > 0 else None
        if data[:4] == b"\xd7\xcd\xc6\x9a" and len(data) >= 14:
            # Placeable WMF: bounding box (device units) at offset 6.
            left, top, right, bottom = struct.unpack("<4h", data[6:14])
            w, h = right - left, bottom - top
            return (w, h) if w > 0 and h > 0 else None
        if data[:5] == b"<?xml" or data[:4] == b"<svg" or b"<svg" in data[:200]:
            head = data[:4000].decode("utf-8", "replace")
            box = re.search(r'viewBox\s*=\s*"([-\d.eE\s,]+)"', head)
            if box:
                nums = [float(x) for x in re.split(r"[\s,]+", box.group(1).strip()) if x]
                if len(nums) == 4 and nums[2] > 0 and nums[3] > 0:
                    return (nums[2], nums[3])
            wm = re.search(r'\bwidth\s*=\s*"([\d.]+)', head)
            hm = re.search(r'\bheight\s*=\s*"([\d.]+)', head)
            if wm and hm and float(wm.group(1)) > 0 and float(hm.group(1)) > 0:
                return (float(wm.group(1)), float(hm.group(1)))
            return None
        if data[:4] in (b"II*\x00", b"MM\x00*"):
            endian = "<" if data[:2] == b"II" else ">"
            off = struct.unpack(endian + "I", data[4:8])[0]
            if off + 2 > len(data):
                return None
            count = struct.unpack(endian + "H", data[off:off + 2])[0]
            w = h = 0
            for k in range(count):
                base = off + 2 + 12 * k
                if base + 12 > len(data):
                    break
                tag, typ = struct.unpack(endian + "HH", data[base:base + 4])
                raw = data[base + 8:base + 12]
                value = (struct.unpack(endian + "H", raw[:2])[0] if typ == 3
                         else struct.unpack(endian + "I", raw)[0])
                if tag == 256:
                    w = value
                elif tag == 257:
                    h = value
            return (w, h) if w and h else None
    except (struct.error, IndexError, ValueError, TypeError):
        return None
    return None


def media_pixel_sizes(pkg: zipfile.ZipFile) -> dict:
    """{'media/image1.png': (w, h), ...} for every image part in a package."""
    out = {}
    for name in pkg.namelist():
        if "/media/" not in name or not _IMAGE_EXT_RE.search(name):
            continue
        try:
            size = image_pixel_size(pkg.read(name))
        except (KeyError, OSError, zipfile.BadZipFile):
            size = None
        if not size:
            continue
        out[name] = size
        out[name.split("/", 1)[1] if "/" in name else name] = size
    return out


def part_rels(pkg: zipfile.ZipFile, part: str) -> dict:
    """{rId: media target} for one part's relationship file (images only)."""
    relname = posixpath.join(posixpath.dirname(part), "_rels",
                             posixpath.basename(part) + ".rels")
    if relname not in pkg.namelist():
        return {}
    out = {}
    xml = pkg.read(relname).decode("utf-8", "replace")
    for m in re.finditer(r"<Relationship(?=[\s/>])[^>]*/>", xml):
        attrs = dict(re.findall(r'([A-Za-z]+)="([^"]*)"', m.group(0)))
        if attrs.get("Id") and attrs.get("Type", "").endswith("/image"):
            out[attrs["Id"]] = attrs.get("Target", "").lstrip("/").replace("\\", "/")
    return out


def _pixel_size_for(sizes: dict, target: str):
    t = (target or "").lstrip("/").replace("\\", "/")
    for key in (t, "word/" + t, t.split("/", 1)[1] if "/" in t else t):
        if key in sizes:
            return sizes[key]
    base = t.rsplit("/", 1)[-1]
    hits = {v for k, v in sizes.items() if k.rsplit("/", 1)[-1] == base}
    return next(iter(hits)) if len(hits) == 1 else None


def _attr_any(frag: str, name: str):
    m = re.search(rf'\b{name}="([^"]*)"', frag)
    return m.group(1) if m else None


def _ratio_fixes(block: str, expected: float) -> list:
    """[(start, end, new)] byte-level fixes restoring one drawing's ratio."""
    fixes = []
    for m in re.finditer(r"<(?:wp:extent|a:ext)(?=[\s/>])[^>]*/>", block):
        tag = m.group(0)
        cx, cy = _attr_any(tag, "cx"), _attr_any(tag, "cy")
        if not (cx and cy):
            continue
        try:
            cxi, cyi = int(cx), int(cy)
        except ValueError:
            continue
        if cyi <= 0:
            continue
        new_cy = max(1, round(cxi / expected))
        if new_cy == cyi:
            continue
        fixes.append((m.start(), m.end(),
                      re.sub(r'\bcy="[^"]*"', f'cy="{new_cy}"', tag, count=1)))
    for m in re.finditer(r"<v:shape(?=[\s/>])[^>]*>", block):
        tag = m.group(0)
        style = re.search(r'style="([^"]*)"', tag)
        if not style:
            continue
        width = re.search(r"width:\s*([0-9.]+)([a-z%]+)", style.group(1), re.I)
        height = re.search(r"height:\s*([0-9.]+)([a-z%]+)", style.group(1), re.I)
        if not (width and height) or width.group(2).lower() != height.group(2).lower():
            continue
        want = round(float(width.group(1)) / expected, 2)
        if abs(want - float(height.group(1))) < 0.01:
            continue
        new_style = style.group(1)[:height.start()] + \
            f"height:{want:g}{height.group(2)}" + style.group(1)[height.end():]
        fixes.append((m.start(), m.end(), tag.replace(style.group(1), new_style, 1)))
    return fixes


def drawing_geometry_rows(part_xml: str, rels: dict, sizes: dict, doc: str,
                          policy: dict, location_prefix: str = "p") -> tuple:
    """(rows, fixes) for every distorted embedded image in one XML part.

    `fixes` are (start, end, new) against `part_xml`; the scanner uses the rows
    only, the fixer applies the fixes.
    """
    tol = float(policy.get("image_aspect_tolerance", 0.02) or 0.02)
    rows, fixes = [], []
    for idx, (p0, _p1, para) in enumerate(paragraphs(part_xml)):
        for m in re.finditer(r"<w:(?:drawing|pict)(?=[\s/>]).*?</w:(?:drawing|pict)>",
                             para, re.S):
            block = m.group(0)
            # A 90/270-degree rotation swaps the displayed axes: the extent
            # cannot be compared with the source ratio directly, so skip a
            # deliberately rotated drawing instead of "repairing" it.
            xfrm = re.search(r"<a:xfrm(?=[\s/>])[^>]*>", block)
            if xfrm:
                rot = _attr_any(xfrm.group(0), "rot")
                try:
                    if rot and int(rot) % 10800000 != 0:
                        continue
                except ValueError:
                    continue
            emb = re.search(r'r:(?:embed|id|link)="([^"]+)"', block)
            if not emb:
                continue
            target = rels.get(emb.group(1))
            size = _pixel_size_for(sizes, target) if target else None
            if not size:
                continue
            pw, ph = size
            expected = pw / ph
            # A CROPPED picture shows only part of the source: `a:srcRect` cuts
            # a fraction off each side, so the displayed extent must match the
            # cropped region's ratio. Comparing against the full image flagged a
            # deliberate crop (FMT-IM1) and the "fix" then distorted it by
            # rewriting cy. A degenerate crop cannot be verified: skip it, like a
            # rotated drawing.
            src_rect = re.search(r"<a:srcRect(?=[\s/>])([^>]*)/?>", block)
            if src_rect:
                rect = {k: v for k, v in re.findall(r'([A-Za-z]+)="([^"]*)"',
                                                    src_rect.group(1))}
                try:
                    frac_w = 1 - (float(rect.get("l") or 0)
                                  + float(rect.get("r") or 0)) / 100000.0
                    frac_h = 1 - (float(rect.get("t") or 0)
                                  + float(rect.get("b") or 0)) / 100000.0
                except ValueError:
                    continue
                if frac_w <= 0 or frac_h <= 0:
                    continue
                expected = (pw * frac_w) / (ph * frac_h)
            cx = cy = None
            unit = "EMU"
            emit = re.search(r"<wp:extent(?=[\s/>])[^>]*/>", block)
            if emit:
                cx, cy = _attr_any(emit.group(0), "cx"), _attr_any(emit.group(0), "cy")
            if not (cx and cy):
                vm = re.search(r"<v:shape(?=[\s/>])[^>]*>", block)
                if vm:
                    style = re.search(r'style="([^"]*)"', vm.group(0))
                    wm = re.search(r"width:\s*([0-9.]+)([a-z%]+)",
                                   style.group(1) if style else "", re.I)
                    hm = re.search(r"height:\s*([0-9.]+)([a-z%]+)",
                                   style.group(1) if style else "", re.I)
                    if wm and hm and wm.group(2).lower() == hm.group(2).lower():
                        cx, cy = float(wm.group(1)), float(hm.group(1))
                        unit = wm.group(2)
            try:
                cxf, cyf = float(cx), float(cy)
            except (TypeError, ValueError):
                continue
            if cyf <= 0:
                continue
            ratio = cxf / cyf
            err = abs(ratio - expected) / expected
            if err <= tol:
                continue
            label = (target or "image").rsplit("/", 1)[-1]
            drawn = (f"{cxf:,.0f} x {cyf:,.0f} {unit}" if float(cxf).is_integer()
                     else f"{cxf:g} x {cyf:g} {unit}")
            rows.append({"rule": "FMT-IM1", "severity": "medium", "document": doc,
                         "location": f"{location_prefix}{idx}",
                         "evidence": (f"image {label}: {pw:g}x{ph:g} px (ratio {expected:.4f}) "
                                      f"delivered at {drawn} "
                                      f"(ratio {ratio:.4f}; {err * 100:.1f}% off)"),
                         "detail": ("resizing an image must preserve its aspect ratio; keep "
                                    "the width and set the height from the image's own "
                                    "pixels"),
                         "fix": "mechanical", "protected": False, "tier": tier_of("FMT-IM1")})
            for s, e, new in _ratio_fixes(block, expected):
                fixes.append((p0 + m.start() + s, p0 + m.start() + e, new))
    return rows, fixes


# --------------------------------------------------------------------------
# REFERENCE-ENTRY SHAPE (rules FMT-R1..FMT-R5).
#
# M10 enumerates every reference entry's SHAPE only as prose for the agent
# ("does the entry name a venue, a year, a locator?"). A malformed entry then
# ships because nothing mechanical ever read it: a journal field written
# "Front. Genet. Volume 11-2020", a citation that stops at "(2013)." with no
# venue at all, a software tool cited as a bare GitHub URL with no version, a
# bioRxiv identifier carrying a DOI from another registration agency, and a
# reference that is a preprint or a trial-in-progress abstract rather than a
# published article. The five rows below enumerate exactly those shapes so the
# review must dispose them (the preprint/trial row is profile-gated: a venue
# that allows preprints gets no row).
#
# They read TEXT, never a field result: an entry inside a live Zotero field is
# reported `fix=style-field` like every other reference-level row, because Word
# and Zotero regenerate the visible list.
# --------------------------------------------------------------------------

# "Front. Genet. Volume 11-2020", "Volume 11-2020", "Vol. 11-2020": a volume
# field glued to a year instead of "11, 565825 (2020)".
REF_VOLUME_MALFORMED_RE = re.compile(
    r"\bvol(?:ume)?\.?\s*\d+\s*[-\u2013\u2014]\s*(?:19|20)\d{2}\b", re.I)
# A DOI anywhere in the entry (the identifier, not the resolver URL only).
REF_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s,;)\]]+")
# The evidence a reference entry names SOME venue: a journal-like token, a
# book/publisher, a preprint server, or any locator. Deliberately generous --
# the row exists to catch an entry with NO venue at all, so a false "has a
# venue" is a missed row, never a wrong one.
REF_VENUE_HINT_RE = re.compile(
    r"(?i)(?:"
    r"doi:|10\.\d{4,9}/|https?://|www\.|"
    r"\barXiv\b|\bbioRxiv\b|\bmedRxiv\b|\bPreprint\b|\bZenodo\b|\bFigshare\b|\bDryad\b|"
    r"\b(?:journal|proceedings|press|publishing|springer|elsevier|wiley|plos|elife|"
    r"frontiers|academic|university press|cold spring harbor|oxford)\b|"
    r"\b(?:nature|science|cell|lancet|blood|bioinformatics|nucleic|genome|giga|gigascience|"
    r"brief|immunol|methods|medicine|oncol|cancer|bioinform|genet|biol|biochem|biophys|"
    r"commun|adv|rep|rev|lett|bull|proc|ann|arch|am|eur|int|mol|syst|clin|hum|"
    r"sci|jco|n\s*engl)\b\s*[.,:]?|"
    # a volume, page shape: "10, giab008", "16, 8777", "12, e431"
    r"\b\d+\s*,\s*(?:e?\d+|[a-z]{2,}\d+)\b"
    r")")
REF_BARE_YEAR_END_RE = re.compile(r"\(\s*(?:19|20)\d{2}\s*\)\.?\s*$")
REF_REPO_HOST_RE = re.compile(
    r"\b(?:github\.com|gitlab\.com|bitbucket\.org|sourceforge\.net|codeberg\.org)\b", re.I)
REF_VERSION_HINT_RE = re.compile(
    r"(?i)(?:\bv?\d+\.\d+(?:\.\d+)?\b|\bcommit\b|\bversion\b|\brelease\b|"
    r"\bdoi\b|\bzenodo\b|\bfigshare\b|\baccess(?:ed)?\b|"
    # a repository URL pinned by path IS a version pin: /tree/<sha>,
    # /commit/<sha>, /blob/<sha> -- the same three spellings REPO_PIN_RE
    # (FMT-AV2) counts as a pin (the old hint read only the words around it and
    # called a commit-pinned software citation "no version"; the missing /blob
    # spelling made FMT-R3 disagree with FMT-AV2 on the same URL).
    r"/(?:tree|commit|blob)/[0-9a-fA-F]{7,40}\b)")
# A bioRxiv/medRxiv-style identifier: the server's YYYY.MM.DD.NNNNNN code (with
# or without the server's name) must carry the server's own DOI prefix.
REF_SERVER_CODE_RE = re.compile(r"\b(?:19|20)\d{2}\.\d{2}\.\d{2}\.\d{5,}\b")
REF_PREPRINT_RE = re.compile(r"(?i)\b(?:bioRxiv|medRxiv|arXiv|Preprint)\b")
REF_TRIAL_ABSTRACT_RE = re.compile(r"\bTPS\d{3,}\b")
BIORXIV_DOI_PREFIX = "10.1101"


def reference_entry_rows(paras: list, is_ref: list, policy: dict = None,
                         limit: int = 80) -> list:
    """FMT-R1..R5: malformed / unsupported reference-entry shapes.

    `paras` are paragraph texts, `is_ref` the parallel "this is a reference
    entry" flags. Rows are ordered by paragraph and capped; each carries the
    entry's first ~120 characters as evidence so the reviewer can find it.
    """
    rows = []
    policy = policy or {}
    ref_policy = policy.get("references") or {}
    flag_preprints = bool(ref_policy.get("flag_preprints"))

    def entry_ref(idx: int) -> str:
        return f"reference entry at paragraph {idx}"

    for idx, (text, is_reference) in enumerate(zip(paras or [], is_ref or [])):
        if not is_reference:
            continue
        entry = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(entry.split()) < 4:
            continue
        head = entry[:120]
        if REF_VOLUME_MALFORMED_RE.search(entry):
            rows.append({"rule": "FMT-R1", "severity": "medium",
                         "location": entry_ref(idx), "evidence": head,
                         "detail": "the journal/volume field is malformed (a volume glued to a "
                                   "year, e.g. 'Volume 11-2020'); a reference needs the venue's "
                                   "own volume/page form (e.g. '11, 565825 (2020)')",
                         "protected": False})
        has_venue = bool(REF_VENUE_HINT_RE.search(entry))
        if not has_venue and REF_BARE_YEAR_END_RE.search(entry):
            rows.append({"rule": "FMT-R2", "severity": "medium",
                         "location": entry_ref(idx), "evidence": head,
                         "detail": "the entry ends at a bare '(YEAR).' and names no venue, "
                                   "locator or publisher; an entry a reader cannot retrieve is "
                                   "not a citation",
                         "protected": False})
        repo_only = (REF_REPO_HOST_RE.search(entry)
                     and not REF_DOI_RE.search(entry)
                     and not REF_PREPRINT_RE.search(entry))
        if repo_only and not REF_VERSION_HINT_RE.search(entry):
            rows.append({"rule": "FMT-R3", "severity": "low",
                         "location": entry_ref(idx), "evidence": head,
                         "detail": "a software/repository citation with no version, release or "
                                   "DOI; cite the used version (a release tag, a commit, or the "
                                   "archived DOI) so the reader can retrieve the same code",
                         "protected": False})
        if REF_SERVER_CODE_RE.search(entry):
            # EVERY DOI of the entry decides: an entry that names a published
            # DOI first and the server's own 10.1101/ DOI after it was flagged
            # although the preprint identifier carries the right prefix.
            dois = REF_DOI_RE.findall(entry)
            doi = dois[0] if dois else ""
            if not any(d.startswith(BIORXIV_DOI_PREFIX + "/") for d in dois):
                rows.append({"rule": "FMT-R4", "severity": "medium",
                             "location": entry_ref(idx), "evidence": head,
                             "detail": "the entry carries a bioRxiv/medRxiv-style identifier "
                                       f"({(REF_SERVER_CODE_RE.search(entry).group(0))}) but its "
                                       f"DOI {'is ' + doi if doi else 'is missing'} instead of "
                                       f"the server's own {BIORXIV_DOI_PREFIX}/ prefix",
                             "protected": False})
        if flag_preprints and (REF_PREPRINT_RE.search(entry)
                               or REF_TRIAL_ABSTRACT_RE.search(entry)):
            kind = ("a trial-in-progress abstract" if REF_TRIAL_ABSTRACT_RE.search(entry)
                    else "a preprint")
            rows.append({"rule": "FMT-R5", "severity": "low",
                         "location": entry_ref(idx), "evidence": head,
                         "detail": f"the entry is {kind}, not a published article, and this "
                                   "venue's profile asks for a row on every one: confirm the "
                                   "venue accepts it, or cite the published version",
                         "protected": False})
        if len(rows) >= limit:
            break
    return rows[:limit]


# --------------------------------------------------------------------------
# DISPLAY-ITEM ORDER (rule FMT-O1).
#
# A venue that numbers display items by first appearance (both shipped profiles
# do) rejects a manuscript whose tables and figures are cited out of order: a
# reader meets Table 4 before Table 1, and the numbering the submission system
# builds disagrees with the file. Nothing in the checklist compared the order
# of the first call-outs with the numbers themselves; M3 only asks whether a
# call-out exists. This is a text rule (the numbers are read from the prose, not
# from the caption blocks), profile-gated by `"numbering": "citation"`.
# --------------------------------------------------------------------------

_DISPLAY_ITEM_TOKEN = r"(?:S?\d+[A-Za-z]?|[IVXLC]+)"
# The tokens a CONJUNCTION/range list may continue with: the digit form only.
# A trailing English word that happens to be roman-numeral letters must not
# date a phantom item -- "Figure 1 and C. elegans ..." is not a call-out of
# "figure 100", nor "Figure 2 and X-ray ..." of "figure 10" -- while the
# confirmed case ("Figures 3 and 4", "Fig. 2 and 3", "Figures 3-5") is
# unchanged. Roman-numeral call-outs stay supported as the FIRST token.
#
# Bounded to three digits and closed with a `(?!\d)` guard: a continuation
# token is an item NUMBER, never a year or another long number that merely
# starts with digits. "Figure 1, 2020 update" dated a phantom figure 2020 and
# the next real "Figure 2" was reported as first cited after it.
_DISPLAY_LIST_TOKEN = r"S?\d{1,3}[A-Za-z]?(?!\d)"
# The separators that name a RANGE rather than a list: "Figures 3-5",
# "Figs. 2–4", "Figures 3 to 5". A range call-out mentions every item inside
# it, so all of them are first cited at that paragraph; reading only the
# endpoints made a later "Figure 4" look like a first mention out of order.
_DISPLAY_RANGE_JOIN_RE = re.compile(r"(?:[-\u2013]|\b(?:to|through)\b)", re.I)
# A gap wider than this is not a display-item range (more likely two numbers
# that happen to sit around a dash); the fill is skipped.
_DISPLAY_RANGE_MAX = 100
# "figure 3" / "figures 3 and 4" / "fig. 3" / "figs. 3" / "fig 3" -- the
# plural `figures` is the most common call-out form of all, and a call-out
# names EVERY item of its conjunction; matching only the first number
# ("Figures 3 and 4" -> "Figures 3") mis-dated 4's first mention and could
# report it as first cited later than a smaller number.
NUMBERING_MENTION_RES = {
    "figure": re.compile(
        r"(?i)\b(?:figures?|figs?\.?)\s*" + _DISPLAY_ITEM_TOKEN
        + r"(?:\s*(?:,\s*(?:and|&)?\s*|\s+(?:and|&|to|through)\s+|[-\u2013]\s*)"
          + _DISPLAY_LIST_TOKEN + r")*"),
    "table": re.compile(
        r"(?i)\btables?\s*" + _DISPLAY_ITEM_TOKEN
        + r"(?:\s*(?:,\s*(?:and|&)?\s*|\s+(?:and|&|to|through)\s+|[-\u2013]\s*)"
          + _DISPLAY_LIST_TOKEN + r")*"),
}
# Every item token of one matched call-out phrase (the leading keyword has no
# digit and no roman letter that follows a non-word character, so the
# lookbehind keeps word interiors out).
DISPLAY_ITEM_TOKEN_RE = re.compile(r"(?i)(?<![A-Za-z0-9])" + _DISPLAY_ITEM_TOKEN)
SUPPLEMENTARY_ITEM_RE = re.compile(r"^S\d+", re.I)
ROMAN_NUMERAL_RE = re.compile(r"^[IVXLC]+$")
# The phrase a call-out may carry IN FRONT of the keyword: "Supplementary
# Figure 2" and "Extended Data Figure 3" are their own families, not main
# figures (the main/supplementary split the row logic promises above). Reading
# only the keyword+token shape recorded both as MAIN figures, so a later
# "Figure 1" produced a false FMT-O1.
DISPLAY_SUPP_PREFIX_RE = re.compile(r"(?i)(?:supplementary|supplemental|suppl\.?)\s*$")
DISPLAY_EDATA_PREFIX_RE = re.compile(r"(?i)extended\s+data\s*$")


def _display_family_prefix(before: str):
    """The family a call-out phrase's PREFIX names, or "" for the token's own."""
    zone = (before or "")[-24:]
    if DISPLAY_EDATA_PREFIX_RE.search(zone):
        return "edata"
    if DISPLAY_SUPP_PREFIX_RE.search(zone):
        return "supp"
    return ""


def _roman_value(token: str):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, prev = 0, 0
    for ch in reversed(token.upper()):
        if ch not in vals:
            return None
        v = vals[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total or None


def _display_item_key(kind: str, token: str):
    """(family, number) for a display-item mention; None when unparsable."""
    supp = bool(SUPPLEMENTARY_ITEM_RE.match(token))
    digits = re.match(r"^S?(\d+)", token, re.I)
    if digits:
        return (kind, "supp" if supp else "main", int(digits.group(1)), token.upper())
    if ROMAN_NUMERAL_RE.match(token):
        return (kind, "supp" if supp else "main", _roman_value(token), token.upper())
    return None


def _display_phrase_tokens(phrase: str) -> list:
    """[(token, is_range_continuation)] for one matched call-out phrase.

    The gap text BEFORE a token decides whether it continues a range ("3-5",
    "3 to 5") or a plain list ("3 and 4", "3, 4"): only the range joins every
    item between the two numbers into the call-out.
    """
    out, prev_end = [], None
    for m in DISPLAY_ITEM_TOKEN_RE.finditer(phrase):
        gap = phrase[prev_end:m.start()] if prev_end is not None else ""
        out.append((m.group(0), bool(prev_end is not None
                                     and _DISPLAY_RANGE_JOIN_RE.search(gap))))
        prev_end = m.end()
    return out


def display_order_rows(paras: list, is_ref: list = None, is_caption: list = None,
                       is_heading: list = None, order_policy: bool = False) -> list:
    """FMT-O1: a numbered display item is first mentioned out of numeric order.

    Only the FIRST call-out of every item counts (a later repeat is free), the
    reference list and the caption/legend blocks are skipped (a caption is not a
    call-out), and the main and supplementary families are compared separately:
    a supplementary figure may legitimately follow a main figure of any number.
    """
    if not order_policy:
        return []
    is_ref = list(is_ref or [False] * len(paras))
    first = {}
    for idx, text in enumerate(paras or []):
        if idx < len(is_ref) and is_ref[idx]:
            continue
        if is_caption and idx < len(is_caption) and is_caption[idx]:
            continue
        if is_heading and idx < len(is_heading) and is_heading[idx]:
            continue
        for kind, pattern in NUMBERING_MENTION_RES.items():
            for m in pattern.finditer(str(text or "")):
                prefix_family = _display_family_prefix(str(text or "")[:m.start()])
                filled, prev = [], None
                for token, is_range in _display_phrase_tokens(m.group(0)):
                    key = _display_item_key(kind, token)
                    if key is None or key[2] is None:
                        prev = None
                        continue
                    if prefix_family and key[1] == "main":
                        key = (key[0], prefix_family, key[2], key[3])
                    if (is_range and prev is not None and prev[0] == key[0]
                            and prev[1] == key[1]
                            and 0 < key[2] - prev[2] <= _DISPLAY_RANGE_MAX):
                        filled.extend((key[0], key[1], n, str(n))
                                      for n in range(prev[2] + 1, key[2]))
                    filled.append(key)
                    prev = key
                for key in filled:
                    if key not in first:
                        first[key] = idx
    rows = []
    for (kind, family) in sorted({(k[0], k[1]) for k in first}):
        seq = sorted(((idx, key) for key, idx in first.items()
                      if key[0] == kind and key[1] == family))
        seen_after = []
        for idx, key in seq:
            for prev_idx, prev_key in seen_after:
                if key[2] < prev_key[2]:
                    rows.append({
                        "rule": "FMT-O1", "severity": "medium", "location": f"p{idx}",
                        "evidence": f"{key[3]} first cited at p{idx} after {prev_key[3]} "
                                    f"(p{prev_idx})",
                        "detail": (f"the {kind} numbering does not follow the order of first "
                                   f"citation: {prev_key[3]} is cited before {key[3]}"),
                        "protected": False})
                    break
            seen_after.append((idx, key))
    return rows


# --------------------------------------------------------------------------
# CORRESPONDENCE / GLUED-FURNITURE (rule FMT-X2).
#
# A front-matter edit that deletes a separator leaves two words fused with no
# space -- "* Correspondence:Zhen Xie, lead contactzhenxie@tsinghua.edu.cn" is
# what the reader and the submission system see. The address itself is a valid
# e-mail, so the bibliography/identifier checks pass it; the defect is the
# MISSING SPACE around it, which no rule looked for.
# --------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
EMAIL_GLUE_BEFORE_RE = re.compile(r"[A-Za-z0-9]{2,}$")
FURNITURE_LABEL_RE = re.compile(
    r"(?i)\b(?:correspondence|corresponding author|e-?mail|contact|author list|"
    r"affiliations?|orcid|keywords?)\s*:")


def _glue_text(text: str) -> tuple:
    """(folded text, break positions) for the FMT-X2 checks.

    The folded text is what the READER sees on one line: each `w:br`/`w:cr`
    becomes ONE space, and each resulting space is recorded in `breaks`, the
    set of folded-text indices the break introduced. (`\n`, `\r` and the
    two-character `\r\n` each fold to a single space; the other two spellings
    never appear in a paragraph's text, and folding one to a space would leave
    the position sets misaligned, so they are not detected.)

    A caller whose text carries NO newlines gets an empty set: nothing was
    folded, so nothing counts as a break-made separator.
    """
    s = text
    if "\r\n" in s:
        out = []
        for i, ch in enumerate(s):
            if ch == "\r" and i + 1 < len(s) and s[i + 1] == "\n":
                continue
            out.append(" " if ch in "\r\n" else ch)
        s = "".join(out)
    elif "\r" in s or "\n" in s:
        s = s.replace("\r", " ").replace("\n", " ")
    breaks = {i for i, ch in enumerate(s) if ch == " " and (
        i < len(text) and text[i] in "\r\n")} if len(s) == len(text) else set()
    return s, breaks


def _glue_separated(s: str, at: int, breaks) -> bool:
    """True when the character just before `at` is a REAL space or a break.

    `at` is where the e-mail match starts. A break whose space sits directly
    before it is a separator; a break one further left does not reach it (a
    genuinely glued `Zhen Xiezhenxie@host` keeps its row).
    """
    j = at - 1
    if j >= 0 and j in (breaks or ()):
        return True
    return j >= 0 and s[j] == " "


def correspondence_glue_rows(paras: list, is_ref: list = None, limit: int = 12) -> list:
    """FMT-X2: a fused word/address or a label with no space after its colon.

    A SOFT BREAK separates two words exactly like a space does, so the checks
    run over the paragraph's visual lines with each `w:br`/`w:cr` folded to a
    space. Reading ACROSS the break turned the perfectly normal three-line
    correspondence block of the 2026-10-15b neohet package

        * Correspondence:
        Zhen Xie
        zhenxie@tsinghua.edu.cn

    into "the address is glued to the word before it" -- reported by the
    delivered status and re-found by the operator's audit, on a line that
    renders correctly. The zero-width fallback is what keeps this honest for a
    caller that passes text WITHOUT the newlines (the fixer's own 1:1 coordinate
    space): no newline means no separator was removed from the text.
    """
    rows = []
    is_ref = list(is_ref or [False] * len(paras))
    for idx, text in enumerate(paras or []):
        if idx < len(is_ref) and is_ref[idx]:
            continue
        raw = str(text or "")
        s, breaks = _glue_text(raw)
        evidence = None
        for m in EMAIL_RE.finditer(s):
            before = s[:m.start()]
            if EMAIL_GLUE_BEFORE_RE.search(before):
                if not _glue_separated(s, m.start(), breaks):
                    evidence = (f"{s[max(0, m.start() - 24):m.end() + 12]!r}: the address is "
                                f"glued to the word before it")
                    break
            after = s[m.end():m.end() + 1]
            if after and after.isalpha():
                evidence = (f"{s[max(0, m.start() - 12):m.end() + 16]!r}: the address is glued "
                            f"to the text after it")
                break
        if evidence is None:
            for m in FURNITURE_LABEL_RE.finditer(s):
                rest = s[m.end():m.end() + 1]
                if rest and not rest.isspace() and evidence is None:
                    # An URL scheme right after a colon is not glue.
                    if s[m.end():m.end() + 2].startswith("//"):
                        continue
                    evidence = (f"{s[max(0, m.start() - 6):m.end() + 24]!r}: no space after the "
                                f"label's colon")
                    break
        if evidence:
            rows.append({"rule": "FMT-X2", "severity": "medium", "location": f"p{idx}",
                         "evidence": evidence,
                         "detail": "two words/addresses are fused with no separator; a "
                                   "front-matter edit removed a space (or a word)",
                         "protected": False})
            if len(rows) >= limit:
                break
    return rows


# --------------------------------------------------------------------------
# PUBLISHER LEFTOVERS (rule FMT-L1).
#
# A manuscript transferred from another publisher's template keeps that
# publisher's boilerplate: "lead contact", "this study did not generate new
# unique reagents", "requests for resources". Which phrases are leftovers is a
# VENUE fact (the profile declares them in `leftover_phrases`; a profile that
# declares none gets no row), and the row is a finding the review must dispose
# -- an editor reading a Frontiers submission that says "lead contact" sees a
# manuscript prepared for another journal.
# --------------------------------------------------------------------------


def leftover_phrase_rows(paras: list, phrases, is_ref: list = None,
                         limit: int = 40) -> list:
    """FMT-L1: a phrase the venue's profile lists as another publisher's."""
    wanted = [str(p).strip() for p in (phrases or []) if str(p).strip()]
    if not wanted:
        return []
    rows = []
    is_ref = list(is_ref or [False] * len(paras))
    for idx, text in enumerate(paras or []):
        if idx < len(is_ref) and is_ref[idx]:
            continue
        s = str(text or "")
        for phrase in wanted:
            m = re.search(r"(?i)(?<![A-Za-z0-9])" + re.escape(phrase)
                          + r"(?![A-Za-z0-9])", s)
            if not m:
                continue
            rows.append({"rule": "FMT-L1", "severity": "low", "location": f"p{idx}",
                         "evidence": (f"{s[max(0, m.start() - 30):m.end() + 30]!r}: "
                                      f"{phrase!r}"),
                         "detail": f"{phrase!r} is another publisher's boilerplate, not this "
                                   f"venue's; remove it or replace it with the venue's own "
                                   f"statement",
                         "protected": False})
            break
        if len(rows) >= limit:
            break
    return rows


# --------------------------------------------------------------------------
# AVAILABILITY STATEMENTS (rules FMT-AV1/A2).
#
# The availability contract already checks that a locator EXISTS and that a
# DOI/accession resolves. Two shapes slip through: a locator that is FUTURE or
# CONDITIONAL ("not yet deposited", "will be deposited before publication",
# "available from the lead contact in the meantime", "on request"), and the
# same repository pinned to TWO commits across the data- and code-availability
# statements -- which silently separates the numbers from the code that made
# them. Both are mechanical text shapes, so both become rows.
# --------------------------------------------------------------------------

AVAIL_UNRESOLVED_RES = (
    ("not yet deposited", re.compile(r"(?i)\bnot\s+yet\s+deposited\b")),
    ("to be deposited", re.compile(r"(?i)\b(?:to|will)\s+be\s+deposited\b")),
    ("deposited ... before publication",
     re.compile(r"(?i)\bdeposit(?:ed|ing)?\b[^.]{0,80}\bbefore\s+publication\b")),
    # A future promise whose verb is a DISSEMINATION sibling of "deposit": the
    # shipped NeoHeteroclitic package said the Figure-4 matrices "will be added
    # to that repository before publication" -- the same deferred locator as
    # "will be deposited ... before publication" above, and exactly the class
    # this rule exists for, but no pattern named that verb family, so the row
    # was never filed for it (the CNB sibling statement, "not yet deposited",
    # WAS filed). The deferral marker in the SAME sentence as the future form
    # is required, which keeps ordinary future prose out; either order counts
    # ("Before publication, the matrices will be added ...").
    ("promised ... before publication",
     re.compile(r"(?i)(?:\b(?:will|shall|to)\s+be\s+"
                r"(?:added|uploaded|released|shared|posted|archived|deposited|"
                r"made\s+available|available)\b[^.]{0,80}\b"
                r"(?:before|prior\s+to|(?:up)?on|after)\s+(?:publication|acceptance)\b"
                r"|\b(?:before|prior\s+to|(?:up)?on|after)\s+(?:publication|acceptance)\b"
                r"[^.]{0,80}\b(?:will|shall|to)\s+be\s+"
                r"(?:added|uploaded|released|shared|posted|archived|deposited|"
                r"made\s+available|available)\b)")),
    ("available from the lead contact",
     re.compile(r"(?i)\bavailable\s+from\s+the\s+(?:lead\s+)?contact\b")),
    ("available on request",
     re.compile(r"(?i)\bavailable\s+(?:up)?on\s+(?:reasonable\s+)?request\b")),
    ("available from the authors",
     re.compile(r"(?i)\bavailable\s+from\s+the\s+authors\b")),
    # "in the meantime" alone is ordinary English ("the discussion continues in
    # the meantime"): like every sibling pattern here, the conditional locator
    # needs the availability context in the same sentence.
    ("in the meantime",
     re.compile(r"(?i)\b(?:availab\w*|deposit\w*|request|share\w*|archiv\w*|obtain\w*)"
                r"\b[^.]{0,80}\bin\s+the\s+meantime\b|"
                r"\bin\s+the\s+meantime\b[^.]{0,80}\b"
                r"(?:availab\w*|deposit\w*|request|share\w*|archiv\w*|obtain\w*)\b")),
    ("archived on acceptance",
     re.compile(r"(?i)\barchived\b[^.]{0,60}\b(?:on|upon|after)\s+acceptance\b")),
    # The locator is CONDITIONAL even when the sentence does not glue
    # "available" to "on request": the common phrasings put the depositor
    # between them ("available from the corresponding author on reasonable
    # request", "shared upon request").
    ("available ... on request",
     re.compile(r"(?i)\bavailab\w*[^.]{0,60}\b(?:up)?on\s+(?:reasonable\s+)?request\b")),
    ("available ... upon publication",
     re.compile(r"(?i)\bavailab\w*[^.]{0,40}\b(?:up)?on\s+publication\b")),
    ("shared ... on request",
     re.compile(r"(?i)\bshar(?:ed|ing)\b[^.]{0,60}\b(?:up)?on\s+(?:reasonable\s+)?request\b")),
)
REPO_PIN_RE = re.compile(
    r"https?://(?:www\.)?(github\.com|gitlab\.com|bitbucket\.org|codeberg\.org)/"
    r"([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)"
    # A commit PIN, in every host's own spelling: GitHub's
    # /tree|commit|blob/<sha> and GitLab's /-/tree|commit|blob/<sha>. Only this
    # family is a pin; release TAGS are deliberately not -- citing two releases
    # of one tool is a legitimate comparison, not an inconsistent statement.
    r"(?:/-)?/(?:tree|commit|blob)/([0-9a-fA-F]{7,40})", re.I)


def availability_rows(paras: list, is_ref: list = None, limit: int = 20) -> list:
    """FMT-AV1 (future/conditional locator) and FMT-AV2 (two pinned commits)."""
    rows = []
    is_ref = list(is_ref or [False] * len(paras))
    pins = {}
    for idx, text in enumerate(paras or []):
        if idx < len(is_ref) and is_ref[idx]:
            continue
        s = str(text or "")
        for label, pattern in AVAIL_UNRESOLVED_RES:
            m = pattern.search(s)
            if not m:
                continue
            rows.append({"rule": "FMT-AV1", "severity": "medium", "location": f"p{idx}",
                         "evidence": (f"{s[max(0, m.start() - 30):m.end() + 40]!r}: {label}"),
                         "detail": "the availability statement points at a future or "
                                   "conditional locator; a submission must name where the data "
                                   "and code ARE, not where they will be",
                         "protected": False})
            break
        for m in REPO_PIN_RE.finditer(s):
            repo = f"{m.group(1).lower()}/{m.group(2)}"
            commit = m.group(3)
            if commit:
                pins.setdefault(repo, []).append((idx, commit[:12]))

    def _same_pin(a: str, b: str) -> bool:
        """One commit id is a prefix of the other (7-char vs full SHA)."""
        n = min(len(a), len(b))
        return n >= 7 and a[:n].lower() == b[:n].lower()

    for repo, found in sorted(pins.items()):
        # Compare commits by PREFIX: the same revision cited once as a short
        # SHA and once in full (or at two truncation lengths) is ONE pin, not
        # two conflicting ones.
        distinct = []
        for _i, c in found:
            if not any(_same_pin(c, d) for d in distinct):
                distinct.append(c)
        if len(distinct) > 1:
            where = ", ".join(f"{c} (p{i})" for i, c in found[:4])
            rows.append({"rule": "FMT-AV2", "severity": "medium",
                         "location": f"{repo}", "evidence": where,
                         "detail": "the same repository is pinned to more than one commit "
                                   "across the availability statements; the pinned code and the "
                                   "pinned results must be the same revision",
                         "protected": False})
    return rows[:limit]


# --------------------------------------------------------------------------
# ZOTERO LIVE-FIELD REFRESH PARITY (rules FMT-Z1..FMT-Z5).
#
# The pipeline byte-preserves live Zotero fields (it never refreshes them), so
# whatever NUMBERING the upstream document carried travels into the certified
# package. A Word/Zotero "Refresh" then re-derives the numbering from the
# document's own citation order: every marker whose cached number disagrees with
# that order is rewritten, the bibliography is regenerated, and the reference
# FORMATTING follows whichever CSL style the document's preference store names.
# That is how a certified package whose markers were stale came back with
# different numbers, a reordered bibliography and a different reference style.
#
# Everything below is checkable in the DOCX ALONE -- each citation field embeds
# its own `citationItems[].itemData`, and the bibliography entries are ordinary
# paragraphs -- so the check needs no Zotero library and no network:
#   FMT-Z1  a citation marker whose number is not the item's own rank in the
#           document's citation order (a STALE marker; the refresh will change
#           it, and every later reference number in the text shifts);
#   FMT-Z2  the bibliography entry at an item's rank does not describe that item
#           (the cached bibliography order disagrees with the citation order);
#   FMT-Z3  one item renders two different numbers, or a cited number is outside
#           1..N (the citation set is not a bijection onto the entry list);
#   FMT-Z4  a field's stored `formattedCitation` disagrees with its VISIBLE text
#           (a half-updated document: Word shows a different number than the one
#           the next refresh will write);
#   FMT-Z5  the document carries CONFLICTING Zotero style identifiers (the
#           docVars copy in `word/settings.xml` vs the `docProps/custom.xml`
#           property), so a refresh may re-render every entry in another CSL
#           style than the one the package was built with.
# --------------------------------------------------------------------------

ZOTERO_STYLE_REF_RE = re.compile(r"https?://www\.zotero\.org/styles/([A-Za-z0-9._\-]+)")


def zotero_style_ids(parts: dict) -> dict:
    """{part name -> style id} for every Zotero preference store in a package.

    `parts` is {part name: xml text}. Zotero records the document's CSL style in
    `word/settings.xml` (`w:docVars`) and, in newer versions, again in
    `docProps/custom.xml`; the two can disagree after a version upgrade or a
    partial re-save, and the next refresh then renders in the OTHER style.
    """
    found = {}
    for name, xml in (parts or {}).items():
        if not isinstance(xml, str):
            continue
        m = ZOTERO_STYLE_REF_RE.search(xml)
        if m:
            found[name] = m.group(1)
    return found


def _zotero_marker_text(marker: str) -> str:
    """A citation field's `formattedCitation` LaTeX-ish marker as visible text.

    Zotero stores the marker with its own escapes (`\\super 3,39\\nosupersub{}`,
    `19\\uc0\\u8211{}23`). Normalizing it is what lets the stored instruction be
    compared with the runs a reader sees.
    """
    s = str(marker or "")
    s = re.sub(r"\\nosupersub\{\}", "", s)
    s = re.sub(r"\\super\s*", "", s)
    s = re.sub(r"\\uc0", "", s)
    # Zotero writes its unicode escapes as DECIMAL codepoints (`\u8211{}` is the
    # en dash U+2013), like RTF/Word field syntax -- not hexadecimal.
    s = re.sub(r"\\u(\d{1,5})\{\}", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"\{\}", "", s)
    s = re.sub(r"\\(?:emph|textit|textbf|textsuperscript)\{([^{}]*)\}", r"\1", s)
    return re.sub(r"\s+", "", s)


_MARKER_RANGE_MAX = 80


def _marker_range_numbers(a: int, b: int) -> list:
    """The numbers one ``a-b`` citation range names.

    An expandable range expands. A range the parser will not expand -- longer
    than `_MARKER_RANGE_MAX`, or written backwards -- keeps its two ENDPOINTS:
    dropping it made the field look like it cites NOTHING, so every later check
    skipped it (FMT-Z1/Z3 read no numbers, and the offline refresh's count guard
    refused the document on a number list of length 0). A year range
    ("2019-2020") is not a citation range at all and still yields nothing.

    The two endpoints keep the WRITTEN order (the round's pin:
    `5-3` -> `[5, 3]`) but are never repeated: an EQUAL-ended range ("12-12",
    which the pre-round code expanded to `[12]`) would otherwise return the same
    number TWICE, and the refresh's count guard (`len(current) != len(ranks)`)
    and FMT-Z3's pairing would then read a one-item field as a two-number
    cluster -- a false "half-updated cluster" row on a document Zotero rendered
    correctly. The skill twin (`extract_citations.parse_nums`) keeps the same
    endpoint SET and the same CAP (80), so a one-number cluster and an 81-200
    range read the same on both sides.
    """
    if 1000 <= a and b <= 2999:
        return []
    if 0 < b - a <= _MARKER_RANGE_MAX:
        return list(range(a, b + 1))
    return list(dict.fromkeys((a, b)))


def _marker_numbers(marker: str, text: str = None) -> list:
    """The numbers a numeric citation marker names, en-dash ranges expanded."""
    raw = text if text is not None else _zotero_marker_text(marker)
    out = []
    for chunk in re.split(r"[;]", str(raw or "")):
        for part in chunk.split(","):
            part = part.strip()
            if not part:
                continue
            m = re.fullmatch(r"(\d+)\s*[\u2013\u2014-]\s*(\d+)", part)
            if m:
                out.extend(_marker_range_numbers(int(m.group(1)), int(m.group(2))))
                continue
            # "12-14p.5" -- `_zotero_marker_text` deletes every space, so the
            # page locator of a range written "12-14 p. 5" arrives GLUED to the
            # range. The old parse fell through to the leading-number branch,
            # read the cluster as the single number 12 and dropped 13 and 14,
            # while the same cluster written "12-14, p. 5" expanded. A locator
            # names a place, not a reference: expand the range, ignore the
            # locator.
            m = re.fullmatch(r"(\d+)\s*[\u2013\u2014-]\s*(\d+)([A-Za-z][A-Za-z.\s]*?)"
                             r"(\d{1,4})", part)
            if m and m.group(3).strip().rstrip(".").lower() in MARKER_LOCATOR_WORDS:
                out.extend(_marker_range_numbers(int(m.group(1)), int(m.group(2))))
                continue
            m = re.fullmatch(r"\d+", part)
            if m:
                # A bare publication year is not a reference number: an
                # author-year marker like "Smith et al., 2019" (or a
                # suppress-author "2019") used to cross the numeric threshold
                # and report "item shows 2019 (its rank is 2)" for a healthy
                # manuscript. No real bibliography ranks an item 2019.
                if not _is_pub_year(int(part)):
                    out.append(int(part))
                continue
            # A citing field may carry PREFIX text inside its own marker
            # ("(hg19)37" -- the residue the 2026-10-09 Zotero forensics
            # measured on the shipped CNB file). The citation number is the
            # trailing cluster after the parenthesized prefix; refusing the
            # whole marker made the field invisible to every numbering rule.
            m = re.fullmatch(r"\([^()]*\)\s*(\d+(?:\s*[,;\u2013\u2014-]\s*\d+)*)", part)
            if m:
                out.extend(_marker_numbers(None, m.group(1)))
                continue
            # "2 p. 5" -- the number comes FIRST and a page locator follows; the
            # reference is the leading number (the old parse dropped the whole
            # part, so a 3-number cluster read as 2 and fired a false FMT-Z3).
            m = re.match(r"(\d+)(?!\d)", part)
            if m:
                if not _is_pub_year(int(m.group(1))):
                    out.append(int(m.group(1)))
                continue
            # "see 39" -- a CSL prefix word in front of the number. A locator
            # word ("p. 5", "fig. 3") names a place, not a reference, and the
            # prefix of a year ("Smith 2019") is not a number either. The
            # separator is optional because the marker the rules read has
            # already been whitespace-stripped by `_zotero_marker_text`
            # ("see 39" -> "see39").
            m = re.fullmatch(r"([A-Za-z][A-Za-z.\s]*?)\s*(\d{1,4})", part)
            if m:
                words = m.group(1).strip().split()
                if words and words[-1].rstrip(".").lower() not in MARKER_LOCATOR_WORDS:
                    n = int(m.group(2))
                    if not _is_pub_year(n):
                        out.append(n)
                continue
    return out


def _is_pub_year(n: int) -> bool:
    """A bare 4-digit number in the plausible publication-year window."""
    return 1000 <= n <= 2999


# Words that can precede a NUMBER without naming a reference ("p. 5",
# "fig. 3"): their trailing integer is a location, not a citation number.
MARKER_LOCATOR_WORDS = frozenset(
    "p pp page pages vol volume no n number ch chap chapter sec section fig "
    "figure figs eq equation ref reference col para app appendix suppl table "
    "note line".split())


ZOTERO_TOKEN_STOPWORDS = {"the", "and", "for", "with", "from", "into", "using", "their",
                          "this", "that", "single", "cell", "cells", "human", "data"}

# The bibliography container headings. Entries are numbered paragraphs, but so
# are numbered section headings ("1. Introduction") and numbered body lists, and
# `setdefault` let the FIRST "N. text" paragraph of the whole document own the
# entry at rank N -- a healthy manuscript then reported FMT-Z2/FMT-Z3 rows
# ("entry 1: 'Introduction' does not describe the cited item").
BIBLIO_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:references|bibliography|literature\s+cited|"
    r"works\s+cited|references\s+cited|bibliography\s+and\s+notes)\s*:?\s*$", re.I)


def _bibliography_entry_start(para_texts: list) -> int:
    """Index of the first paragraph after the LAST usable bibliography heading.

    The entries are scanned from there; a document with no container heading
    keeps the historical whole-document scan (a heading-less numbered
    bibliography still needs the check), so this can only REMOVE the numbered
    heading/body-list false positives.

    "Usable" = at least one numbered entry follows it, which skips the Zotero
    bibliography FIELD's own result paragraph (its placeholder text is literally
    "bibliography" and it can sit after the entries).
    """
    start = 0
    texts = list(para_texts or [])
    for i, text in enumerate(texts):
        if not BIBLIO_HEADING_RE.match(str(text or "")):
            continue
        if any(re.match(r"^\s*\d+\s*[\.\)]\s*\S", str(t or "")) for t in texts[i + 1:]):
            start = i + 1
    return start


def _zotero_word_in(hay: str, token: str) -> bool:
    """True when `token` appears in `hay` as a WORD, not as a substring.

    `hay` is the normalised entry text (lowercase, alphanumerics and single
    spaces), so the boundary is the string's own alphanumeric run. A plain
    `token in hay` made the parity check blind: the family "He" matched "The
    method ...", "Li" matched "Applied ..." and the title token "model" matched
    "Remodeling ...", so FMT-Z2 could not see an entry that describes a
    DIFFERENT work -- the check that catches a stale numbered bibliography.
    """
    if not token:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(str(token)) + r"(?![a-z0-9])",
                     hay or "") is not None


def _entry_describes_item(entry: str, item: dict) -> bool:
    """Does a bibliography ENTRY text describe the citation's embedded itemData?

    A first-author family name or a distinctive title token is enough: the row
    exists to catch an entry that is a different WORK (the mis-numbered
    bibliography), never to grade the reference formatting.
    """
    if not entry or not isinstance(item, dict):
        return True                      # nothing to judge: never a false row
    hay = re.sub(r"[^a-z0-9 ]+", " ", unicodedata.normalize(
        "NFKD", str(entry)).lower())
    creators = item.get("author") or item.get("editor") or []
    if isinstance(creators, list) and creators:
        first = creators[0] if isinstance(creators[0], dict) else {}
        family = str(first.get("family") or first.get("literal") or "").strip()
        if family:
            token = re.sub(r"[^a-z0-9 ]+", " ", family.lower()).split()
            if token and _zotero_word_in(hay, token[0]):
                return True
    title = str(item.get("title") or "")
    tokens = [t for t in re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split()
              if len(t) > 4 and t not in ZOTERO_TOKEN_STOPWORDS]
    if tokens and any(_zotero_word_in(hay, t) for t in tokens[:8]):
        return True
    return False


def zotero_citation_state(xml: str, para_texts: list = None,
                          style_ids: dict = None) -> dict:
    """The live-field citation state of one document.xml (see the FMT-Z rules)."""
    report = zotero_field_report(xml)
    fields = []
    for f in report["fields"]:
        if f["kind"] != "item":
            continue
        js = None
        try:
            # Decode the FIRST complete JSON value, not the brace-to-brace span:
            # Word may append a field switch ("... } \* MERGEFORMAT") or the
            # instruction may carry braces of its own, and the greedy pattern
            # then raised, silently dropping the field from every Z-rule. The
            # field inventory's own reader (`_zotero_citation_id`) already
            # decodes it this way.
            m = re.search(r"CSL_CITATION\s*(\{)", f["instr"], re.S)
            if m:
                js, _end = json.JSONDecoder().raw_decode(f["instr"][m.start(1):].strip())
        except (ValueError, TypeError):
            js = None
        props = (js or {}).get("properties") or {}
        marker = props.get("formattedCitation") or props.get("formatted citation") or ""
        items, data = [], []
        for ci in (js or {}).get("citationItems") or []:
            if not isinstance(ci, dict):
                continue
            uri = (ci.get("uris") or [ci.get("uri") or ""])[0]
            items.append(str(uri or ci.get("id") or ""))
            data.append(ci.get("itemData") or {})
        fields.append({"citationID": f.get("citationID"), "marker": marker,
                       "visible": f.get("visible_text") or "",
                       "shown": _zotero_marker_text(marker),
                       "numbers": _marker_numbers(marker),
                       "items": items, "itemData": data, "begin": f.get("begin")})
    order = {}
    for f in fields:
        for key in f["items"]:
            order.setdefault(key, len(order) + 1)
    entries = {}
    entry_order = []
    for text in (para_texts or [])[_bibliography_entry_start(para_texts):]:
        m = re.match(r"^\s*(\d+)\s*[\.\)]\s*(.+)$", str(text or ""))
        if m:
            entries.setdefault(int(m.group(1)), m.group(2).strip())
            entry_order.append(int(m.group(1)))
    numeric = bool(fields) and sum(1 for f in fields if f["numbers"]) >= max(1, 0.6 * len(fields))
    return {"fields": fields, "order": order, "entries": entries, "numeric": numeric,
            "entry_order": entry_order,
            "distinct_items": len(order),
            "style_ids": dict(style_ids or {}), "report": report}


def _cluster_numbers_are_the_ranks(f: dict, order: dict) -> bool:
    """True when a field's rendered numbers ARE exactly its items' ranks.

    Zotero renders a numeric cluster in NUMBER order while `citationItems` keep
    insertion order, so a correctly rendered field ([a(rank 4), b(rank 3)]
    shown "3,4") is not stale in any reader-visible sense: the numbers are the
    right numbers, only the display order differs. Pairing positionally
    reports two false stale rows on it, and the FMT-Z3 pairing rule then reads
    one item rendering two numbers; both rules skip such a cluster.
    """
    if len(f.get("numbers") or []) != len(f.get("items") or []):
        return False
    ranks = [order.get(k) for k in f["items"]]
    return None not in ranks and sorted(f["numbers"]) == sorted(ranks)


def zotero_parity_rows(xml: str, para_texts: list = None, style_ids: dict = None,
                       limit: int = 60, order: dict = None, numeric: bool = None,
                       state: dict = None) -> list:
    """FMT-Z1..Z5: the live-field state a Word/Zotero refresh would rewrite."""
    # `state` lets a multi-part caller reuse the inventory it already built
    # (one full parse per part instead of two); it must have been built from
    # the SAME xml/para_texts/style_ids.
    state = state if state is not None else zotero_citation_state(xml, para_texts, style_ids)
    if not state["fields"]:
        return []
    if order is not None:
        # A caller that reads several parts of one package (document.xml plus
        # footnotes/endnotes/headers) supplies the package-wide citation order,
        # so every part is judged against the SAME ranks.
        state["order"] = dict(order)
        state["distinct_items"] = len(state["order"])
    if numeric is not None:
        # ... and the same is true of the "is this a numeric-style document"
        # gate: a footnotes part that mixes one numeric marker with an
        # author-year one falls under the 60% line on its own, and the STALE
        # numeric marker beside it stayed invisible to every FMT-Z rule.
        state["numeric"] = bool(numeric)
    rows = []
    order, entries = state["order"], state["entries"]
    numeric = state["numeric"]
    # FMT-Z1 -- a stale marker (the item's number is not its rank).
    stale_items = set()
    if numeric:
        for f in state["fields"]:
            if _cluster_numbers_are_the_ranks(f, order):
                continue             # consistent cluster: only the display order differs
            pairs = list(zip(f["items"], f["numbers"]))
            if len(pairs) != len(f["items"]) or len(f["numbers"]) != len(f["items"]):
                continue                 # a marker whose shape cannot be paired: FMT-Z3 covers it
            bad = [(k, order.get(k), n) for k, n in pairs if order.get(k) != n]
            if not bad:
                continue
            stale_items.update(k for k, _r, _n in bad)
            shown = ", ".join(f"item ...{str(k).split('/')[-1]} shows {n} (its rank is {r})"
                              for k, r, n in bad[:3])
            rows.append({"rule": "FMT-Z1", "severity": "high",
                         "location": f"field {f['citationID']}", "evidence": shown,
                         "detail": "the citation's cached NUMBER disagrees with the item's own "
                                   "position in this document's citation order: the field is "
                                   "STALE. A Word/Zotero refresh rewrites it (and reorders the "
                                   "bibliography), so the submitted numbers are not the ones a "
                                   "reader of the published version will see",
                         "protected": True})
            if len(rows) >= limit:
                return rows
    # FMT-Z2 -- the entry at the item's rank describes another work.
    if entries and numeric:
        for f in state["fields"]:
            for key, data in zip(f["items"], f["itemData"]):
                rank = order.get(key)
                entry = entries.get(rank)
                if not entry or _entry_describes_item(entry, data):
                    continue
                rows.append({"rule": "FMT-Z2", "severity": "high",
                             "location": f"reference {rank}",
                             "evidence": f"cited item title {str(data.get('title'))[:70]!r} vs "
                                         f"entry {rank}: {entry[:70]!r}",
                             "detail": "the bibliography entry at this cited item's number "
                                       "describes a different work: the cached bibliography order "
                                       "disagrees with the citation order, so every reader "
                                       "lookup lands on the wrong reference",
                             "protected": True})
                if len(rows) >= limit:
                    return rows
        # ... and the entries must APPEAR in rank order: a list whose numbers
        # run 2,1 (or whose paragraphs are otherwise out of order) is a stale
        # bibliography a Word/Zotero refresh re-sorts, even though every
        # numbered entry happens to describe the right work.
        seq = [n for n in (state.get("entry_order") or []) if n in entries]
        expected = sorted(entries)
        if seq and sorted(seq) == expected and seq != expected:
            rows.append({"rule": "FMT-Z2", "severity": "medium", "location": "bibliography",
                         "evidence": f"entries appear in the order {seq[:10]}",
                         "detail": "the bibliography's paragraphs are not in citation-rank "
                                   "order: a Word/Zotero refresh re-sorts the list (the "
                                   "numbered entries may still describe the right works, so "
                                   "nothing else notices)",
                         "protected": True})
    # FMT-Z3 -- one item showing two numbers, or a number outside 1..N.
    seen = {}
    for f in state["fields"]:
        if len(f["numbers"]) != len(f["items"]) or _cluster_numbers_are_the_ranks(f, order):
            continue
        for key, n in zip(f["items"], f["numbers"]):
            seen.setdefault(key, {}).setdefault(n, f["citationID"])
    # An un-pairable marker is NOT invisible: a numeric field that renders a
    # different COUNT of numbers than it cites items (a half-updated cluster,
    # one number left for two items, a dropped number) is judged by neither
    # FMT-Z1 (needs a pair per item) nor the rule above (needs equal counts).
    if numeric:
        for f in state["fields"]:
            if f["numbers"] and len(f["numbers"]) != len(f["items"]):
                rows.append({"rule": "FMT-Z3", "severity": "medium",
                             "location": f"field {f['citationID']}",
                             "evidence": f"{len(f['numbers'])} rendered number(s) ("
                                         + ", ".join(str(n) for n in f["numbers"][:6])
                                         + f") for {len(f['items'])} cited item(s)",
                             "detail": "the marker cannot be paired with the field's own "
                                       "citation items (a half-updated cluster, a dropped "
                                       "number, or a marker the normalizer cannot read): the "
                                       "visible number(s) cannot be trusted, and a Word/Zotero "
                                       "refresh rewrites the field",
                             "protected": True})
    for key, numbers in sorted(seen.items()):
        # A stale marker is already a FMT-Z1 row; this rule adds the *pairing*
        # fault only where the ranks agreed but the numbers still differ (a
        # subtler half-updated document), so the two do not double-report.
        if len(numbers) > 1 and key not in stale_items:
            rows.append({"rule": "FMT-Z3", "severity": "medium",
                         "location": f"item ...{str(key).split('/')[-1]}",
                         "evidence": "numbers " + ", ".join(
                             f"{n} (field {c})" for n, c in sorted(numbers.items())[:4]),
                         "detail": "the same cited item renders two different numbers in one "
                                   "document: at least one field was not updated with the rest",
                         "protected": True})
    if numeric and state["distinct_items"]:
        over = sorted({n for f in state["fields"] for n in f["numbers"]
                       if n > state["distinct_items"]})
        uncited = sorted(set(entries) - {n for f in state["fields"] for n in f["numbers"]}) \
            if entries else []
        if over:
            rows.append({"rule": "FMT-Z3", "severity": "medium", "location": "numbering",
                         "evidence": f"cited number(s) {over[:6]} exceed the "
                                     f"{state['distinct_items']} distinct cited item(s)",
                         "detail": "a citation number points outside the bibliography the "
                                   "document's own citations define",
                         "protected": True})
        if uncited:
            rows.append({"rule": "FMT-Z3", "severity": "low", "location": "bibliography",
                         "evidence": f"entry number(s) {uncited[:6]} are never cited",
                         "detail": "the cached bibliography lists an entry no citation marker "
                                   "uses: the bibliography is stale (a refresh drops it, which "
                                   "renumbers everything after it)",
                         "protected": True})
    # FMT-Z4 -- the stored marker and the visible runs disagree.
    for f in state["fields"]:
        if not f["shown"]:
            continue
        # Judge only a marker this normalization FULLY understands: after the
        # handled commands are removed, any LaTeX left over (a locale note, a
        # custom style) could look like a disagreement, so it is not judged.
        residue = re.sub(
            r"\\super\s*|\\nosupersub\{\}|\\uc0|\\u\d{1,5}\{\}|"
            r"\\(?:emph|textit|textbf|textsuperscript)\{[^{}]*\}", "", str(f["marker"]))
        if "\\" in residue:
            continue
        visible = re.sub(r"\s+", "", str(f.get("visible") or ""))
        if visible and visible != f["shown"]:
            rows.append({"rule": "FMT-Z4", "severity": "high",
                         "location": f"field {f['citationID']}",
                         "evidence": f"stored {f['shown']!r} vs visible {visible!r}",
                         "detail": "the field's stored marker and the text a reader sees "
                                   "disagree: the document was saved half-updated, and the next "
                                   "refresh will change the visible number",
                         "protected": True})
    # FMT-Z5 -- conflicting Zotero style stores.
    styles = state.get("style_ids") or {}
    distinct = sorted(set(styles.values()))
    if len(distinct) > 1:
        where = "; ".join(f"{part} -> {sid}" for part, sid in sorted(styles.items()))
        rows.append({"rule": "FMT-Z5", "severity": "medium", "location": "document preferences",
                     "evidence": where,
                     "detail": "the document carries more than one Zotero citation-style "
                               "identifier; a refresh re-renders every entry in whichever store "
                               "it honours, so the bibliography FORMAT can change (and no "
                               "longer match the target journal's style) without any warning",
                     "protected": True})
    return rows[:limit]


def zotero_package_order(parts: list) -> dict:
    """The document-first package-wide citation order over one package's parts.

    `parts` is [(part name, that part's XML)]. document.xml first, then the
    rest in name order: taking the order from the caller's list made the main
    part's ranks depend on zip member order (a package listing footnotes.xml
    first would shift every in-text citation and report false stale rows).
    """
    main = [(n, x) for n, x in parts if n == "word/document.xml"]
    rest = sorted(((n, x) for n, x in parts if n != "word/document.xml"), key=lambda t: t[0])
    order = {}
    for _name, xml in main + rest:
        for key in zotero_citation_state(xml)["order"]:
            order.setdefault(key, len(order) + 1)
    return order


def zotero_parity_rows_for_parts(parts: list, style_ids: dict = None,
                                 limit: int = 60) -> list:
    """FMT-Z1..Z5 over EVERY field-carrying part of one package.

    `parts` is [(part name, that part's XML)]. The parts are judged against ONE
    package-wide citation order -- document.xml first, then footnotes/endnotes/
    headers/comments in name order -- because a per-part order makes footnote
    ranks local to the footnotes and produces false stale rows; a version whose
    footnote citations are stale must not look clean to the stage gate while
    `zotero-check` reports them.
    """
    main = [(n, x) for n, x in parts if n == "word/document.xml"]
    rest = sorted(((n, x) for n, x in parts if n != "word/document.xml"), key=lambda t: t[0])
    # One document-first pass builds BOTH the package-wide order and each
    # part's inventory; `zotero_parity_rows` then reuses the inventory instead
    # of re-parsing the same multi-megabyte XML (it used to parse every part
    # twice per call, which dominated `zotero-check` and the stage gate).
    order = {}
    states = []
    for _name, xml in main + rest:
        paras = [text_of(p[2]) for p in paragraphs(xml)]
        st = zotero_citation_state(xml, paras, style_ids)
        states.append((_name, xml, st))
        for key in st["order"]:
            order.setdefault(key, len(order) + 1)
    # The numeric gate is PACKAGE-wide, like the order: any part whose markers
    # meet the 60% numeric rule makes the document numeric-style, so a stale
    # numeric marker in a mixed footnotes part is judged by the same ranks as
    # the main text instead of dropping out of every FMT-Z rule.
    numeric = any(st["numeric"] for _n, _x, st in states)
    rows = []
    for name, xml, st in states:
        part_rows = zotero_parity_rows(xml, limit=limit, order=order,
                                       numeric=numeric, state=st)
        if name != "word/document.xml":
            part_rows = [dict(r, location=f"{name}: {r['location']}") for r in part_rows]
        rows.extend(part_rows)
        if len(rows) >= limit:
            break
    return rows[:limit]


# --------------------------------------------------------------------------
# THE LOCAL REFRESH — a deterministic Zotero "Refresh" (2026-10-11)
#
# `zotero-check` (FMT-Z1..Z5) proves that a live-field document is stale, and
# the old contract stopped there: the numbers were repaired only by a human
# running Zotero → Refresh in Word. This section closes the loop offline.
# Every citation item's number is re-derived from the document's own citation
# order, the markers and their cached JSON are rewritten to it, and the
# bibliography is rebuilt in the same order — the same repair the plugin
# performs, restricted to the part a machine can verify.
#
# Contract (each clause is a refusal, not a warning):
#   * only a NUMERIC citation style is refreshed; a marker shape this module
#     cannot rebuild byte-for-byte is left for the author;
#   * every cited item must resolve to a rank, and every marker must be
#     rebuildable, or NOTHING is written;
#   * the bibliography is rebuilt only when it is needed AND every entry can
#     be matched to its item with confidence, or NOTHING is written;
#   * the result must pass the FMT-Z checks that reported the staleness; if it
#     does not, the ORIGINAL xml is returned with the reason recorded.
# --------------------------------------------------------------------------

ZOTERO_MARKER_CLUSTER_RE = re.compile(r"\d+(?:\s*[,;\u2013\u2014-]\s*\d+)*")
ZOTERO_MARKER_COMMAND_RE = re.compile(
    r"\\super\b|\\nosupersub\{\}|\\nosupersub\b|\\uc0|\\u\d{1,5}\{\}")


def _zotero_marker_cluster(marker: str):
    """(start, end, cluster) of a formattedCitation's numeric cluster, or None.

    Only a marker that is NOTHING but Zotero's own commands around one numeric
    cluster is refreshable: a marker carrying prose, a locator or a command
    this normalizer does not know stays with the author, exactly as it does in
    the FMT-Z rules.

    The cluster's INTERIOR may itself carry Zotero escapes: an en dash inside
    "20\u201324,29,44" is serialized `\\uc0\\u8211{}24,29,44`, so the cluster is
    taken from the first to the last digit and the interior is accepted once
    the known commands are removed and only digits/separators remain.
    """
    s = str(marker or "")
    digits = [i for i, ch in enumerate(s) if ch.isdigit()]
    if not digits:
        return None
    start, stop = digits[0], digits[-1] + 1
    interior = s[start:stop]
    if not re.fullmatch(r"[\d\s,;.\u2013\u2014-]*",
                        ZOTERO_MARKER_COMMAND_RE.sub("", interior)):
        return None
    residue = ZOTERO_MARKER_COMMAND_RE.sub("", s[:start] + s[stop:])
    if residue.strip():
        return None
    return start, stop, interior


def _zotero_cluster_for_ranks(ranks, original_cluster: str) -> str:
    """(raw, visible) clusters Zotero prints for `ranks`.

    A contiguous run of >2 ranks that the ORIGINAL cluster printed as a range
    stays a range (the same dash serialization); everything else is a comma
    list, which is what the numeric styles use for two items and for gaps.
    `raw` keeps Zotero's escape (`\\uc0\\u8211{}`) when the original used it;
    `visible` is what the result runs carry.
    """
    ranks = sorted({int(r) for r in ranks})
    if not ranks:
        return "", ""
    if "\\uc0\\u8211{}" in original_cluster or "\\u8211{}" in original_cluster:
        dash_raw, dash_vis = "\\uc0\\u8211{}", "\u2013"
    elif "\u2013" in original_cluster:
        dash_raw = dash_vis = "\u2013"
    elif "\u2014" in original_cluster:
        dash_raw = dash_vis = "\u2014"
    elif "-" in original_cluster:
        dash_raw = dash_vis = "-"
    else:
        dash_raw, dash_vis = "\\uc0\\u8211{}", "\u2013"
    raw_parts, vis_parts = [], []
    i = 0
    while i < len(ranks):
        j = i
        while j + 1 < len(ranks) and ranks[j + 1] == ranks[j] + 1:
            j += 1
        if j - i >= 2:                       # >= 3 contiguous: a range
            raw_parts.append(f"{ranks[i]}{dash_raw}{ranks[j]}")
            vis_parts.append(f"{ranks[i]}{dash_vis}{ranks[j]}")
        else:
            for k in range(i, j + 1):
                raw_parts.append(str(ranks[k]))
                vis_parts.append(str(ranks[k]))
        i = j + 1
    return ",".join(raw_parts), ",".join(vis_parts)


def _zotero_json_span(text: str):
    """(start, end, parsed) of the first CSL_CITATION JSON value in `text`."""
    m = re.search(r"CSL_CITATION\s*\{", text or "")
    if not m:
        return None
    start = m.end() - 1
    try:
        js, n = json.JSONDecoder().raw_decode(text[start:].strip())
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    lead = len(text[start:]) - len(text[start:].lstrip())
    start += lead
    return start, start + n, js


def _zotero_run_span(xml: str, start: int, end: int, kind: str):
    """Span of the run holding the `kind` fldChar inside [start, end).

    `zotero_field_report` records the fldChar ELEMENT's offsets, which sit
    inside a run (the closing `</w:r>` follows them); the search window is
    widened by a few hundred bytes so a run that only *contains* the element
    can still match, and the element's own position decides which field it
    belongs to.
    """
    end = end if end is not None else len(xml)
    w0, w1 = max(0, start - 4000), min(len(xml), end + 4000)
    for m in RUN_RE.finditer(xml, w0, w1):
        fc = FIELD_CHAR_RE.search(m.group(0))
        if not fc or fc.group(1) != kind:
            continue
        at = m.start() + fc.start()
        if start <= at <= end:
            return m.start(), m.end()
    return None


def _zotero_result_region(xml: str, frame: dict):
    """(runs, template_run) of one field's RESULT runs, or None when unsafe.

    The result region is everything between the run that carries the field's
    `separate` fldChar and the run that carries its `end`. A refresh replaces
    the region's text runs with one rebuilt run, so every run in it must be a
    simple text run: a drawing, a `w:tab` or a nested field makes the region
    unsafe and the field is left untouched.
    """
    sep = _zotero_run_span(xml, frame["begin"], frame["end"], "separate")
    end = _zotero_run_span(xml, frame["begin"], frame["end"], "end")
    if not sep or not end or sep[1] > end[0]:
        return None
    s, e = sep[1], end[0]
    region_runs = list(RUN_RE.finditer(xml, s, e))
    # Only whitespace may live outside the runs.
    residue = RUN_RE.sub("", xml[s:e])
    # ... and a PROOFING MARKER: Word inserts `w:proofErr` inside field results
    # constantly, and the module strips them under `strip_proofing_markers`
    # anyway. Refusing the whole field for one left every such field unrefreshed
    # ("has no simple result runs") in a real Word-saved document, while the
    # region is rebuilt as ONE run here, so a marker inside it is dropped either
    # way.
    residue = PROOFERR_RE.sub("", residue)
    if residue.strip():
        return None
    template = None
    for m in region_runs:
        run = m.group(0)
        if FIELD_CHAR_RE.search(run) or INSTR_RE.search(run) or DRAWING_RE.search(run) \
                or "<w:tab" in run or "<w:br" in run:
            return None
        # EXACTLY one `w:t`: the rebuilt result run is cloned from the first
        # run and its text replaced, so a run carrying a second `w:t` would
        # keep that element's stale text beside the new number.
        if len(re.findall(r"<w:t(?:\s[^>]*)?>.*?</w:t>", run, re.S)) != 1:
            return None
        if template is None:
            template = run
    if template is None:
        return None
    return (s, e, [(m.start(), m.end(), m.group(0)) for m in region_runs], template)


def _zotero_result_run(template_run: str, text: str) -> str:
    """A run cloned from the field's own result run, carrying `text`."""
    return re.sub(r"<w:t(?:\s[^>]*)?>.*?</w:t>",
                  '<w:t xml:space="preserve">' + esc(text) + "</w:t>",
                  template_run, count=1, flags=re.S)


def _zotero_entry_span_of_run(content: str):
    """(start, end, number) of an entry's leading 'N.' text run, or None."""
    m = re.match(r"^\s*(<w:r(?: [^>]*)?>.*?</w:r>)", content, flags=re.S)
    if not m:
        return None
    run = m.group(1)
    t = text_of(run)
    nm = re.fullmatch(r"\s*(\d+)\s*[\.\)]?\s*", t)
    if not nm:
        return None
    return m.start(1), m.end(1), int(nm.group(1))


def _zotero_entry_match_score(entry_text: str, item: dict) -> int:
    """Confidence that a bibliography ENTRY text describes one itemData."""
    hay = re.sub(r"[^a-z0-9 ]+", " ", unicodedata.normalize(
        "NFKD", str(entry_text or "")).lower())
    score = 0
    creators = item.get("author") or item.get("editor") or []
    if isinstance(creators, list) and creators and isinstance(creators[0], dict):
        family = str(creators[0].get("family") or creators[0].get("literal") or "").strip()
        token = re.sub(r"[^a-z0-9 ]+", " ", family.lower()).split()
        if token and _zotero_word_in(hay, token[0]):
            score += 3
            if _zotero_word_in(hay[:80], token[0]):
                score += 1
    issued = item.get("issued") or {}
    try:
        year = str(issued.get("date-parts", [[None]])[0][0])
    except (KeyError, IndexError, TypeError, AttributeError):
        # A hand- or agent-edited citation JSON can carry "issued": "2020" (a
        # string) or a list: `issued.get` then raises AttributeError, which
        # escaped through _zotero_bibliography_plan into the fixer. The module
        # already treats malformed itemData as in-scope (the isinstance guard
        # around the creators above), so this is the same guard, completed.
        year = ""
    if year and year != "None" and f"({year})" in re.sub(r"\s+", " ", entry_text):
        score += 1
    title = str(item.get("title") or "")
    for t in re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split():
        if len(t) > 4 and t not in ZOTERO_TOKEN_STOPWORDS and _zotero_word_in(hay, t):
            score += 1
            if score >= 8:
                break
    return score


def zotero_bibliography_state(xml: str, frame: dict):
    """The bibliography field's paragraphs, its entry texts and the rebuild parts.

    Returns {"skip": reason|None, "heads": [...], "contents": [...],
    "numbers": [...], "spine": xml, "tail": xml, "start": i, "end": i,
    "end_in_last_entry": bool, "entries": [(number, text), ...]} or a skip
    reason when the field is not a simple numbered list the rebuild can own.
    `spine` is everything from the field's first paragraph through the run
    that carries `separate`; `tail` is everything after the last ENTRY
    paragraph (or, when the closing fldChar lives in that paragraph, from the
    run that carries `end`). Zotero writes the closing fldChar alone in a
    trailing no-text paragraph, so the tail is regularly a whole paragraph.
    """
    if frame.get("end") is None:
        return {"skip": "the bibliography field has no closing fldChar"}
    p_start = p_last = None
    for p0, p1, _para in paragraphs(xml):
        if p_start is None and p0 <= frame["begin"] < p1:
            p_start = (p0, p1)
        if p0 <= frame["end"] <= p1:
            p_last = (p0, p1)
    if p_start is None or p_last is None:
        return {"skip": "the bibliography field's paragraphs were not found"}
    sep = _zotero_run_span(xml, frame["begin"], frame["end"], "separate")
    end = _zotero_run_span(xml, frame["begin"], frame["end"], "end")
    if not sep or not end:
        return {"skip": "the bibliography field has no separate/end pair"}
    p0_start, _p1_start = p_start
    _p0_last, p1_last = p_last
    spine = xml[p0_start:sep[1]]
    heads, contents, numbers, entries, spans = [], [], [], [], []
    gap_after_entry = False
    for k, (p0, p1, para) in enumerate(paragraphs(xml)):
        if p0 < p0_start or p1 > p1_last:
            continue
        open_m = re.match(r"<w:p(?: [^>]*)?>", para)
        if not open_m:
            return {"skip": "a bibliography paragraph has no opening tag"}
        head_end = open_m.end()
        ppr = ppr_of(para)
        if ppr:
            ppr_at = para.find(ppr)
            if ppr_at < 0:
                return {"skip": "a bibliography paragraph's pPr was not found"}
            head_end = ppr_at + len(ppr)
        # The CONTENT runs: everything after the paragraph's properties (or
        # after the `separate` run for the first paragraph), up to the closing
        # tag -- or up to the `end` run when the field closes inside this very
        # paragraph.
        content_start = (sep[1] - p0) if p0 == p0_start else head_end
        end_here = end[0] >= p0 and end[1] <= p1
        if end_here:
            content = para[content_start:end[0] - p0]
        else:
            close_at = para.rfind("</w:p>")
            content = para[content_start:close_at if close_at >= 0 else len(para)]
        span = _zotero_entry_span_of_run(content)
        if span is None:
            # Allowed only AFTER the entries (a trailing paragraph with no text,
            # e.g. the one that carries the closing fldChar alone): it is kept
            # verbatim in `tail`. A text-less paragraph BETWEEN two entries
            # would have no place in a rank-ordered rebuild -- refusing beats
            # silently dropping a paragraph the author put there.
            if entries and not text_of(content).strip():
                gap_after_entry = True
                continue
            return {"skip": (f"bibliography paragraph {k} does not start with a numbered "
                             f"entry: {text_of(content)[:60]!r}")}
        if gap_after_entry:
            return {"skip": ("a text-less paragraph sits between bibliography entries; "
                             "the rebuild cannot place it")}
        numbers.append(span[2])
        entries.append((span[2], re.sub(r"\s+", " ", text_of(content)).strip()))
        heads.append(para[:head_end])
        contents.append(content)
        spans.append((p0, p1, end_here))
    if not contents:
        return {"skip": "the bibliography field carries no entries"}
    last_p1 = spans[-1][1]
    end_in_last_entry = spans[-1][2]
    tail = xml[end[0]:last_p1] if end_in_last_entry else xml[last_p1:p1_last]
    return {"skip": None, "heads": heads, "contents": contents,
            "numbers": numbers, "entries": entries, "spine": spine, "tail": tail,
            "start": p0_start, "end": p1_last, "sep_end": sep[1], "end_start": end[0],
            "end_in_last_entry": end_in_last_entry, "para_count": len(contents)}


def _zotero_bibliography_plan(xml: str, frame: dict, items_by_rank: dict):
    """Decide whether the bibliography needs a rebuild, and build it.

    `items_by_rank` maps rank -> itemData for every cited item. Returns
    {"needed": bool, "xml": rebuilt_region|None, "skip": reason|None,
    "entries": n, "reordered": bool, "renumbered": n}.
    """
    st = zotero_bibliography_state(xml, frame)
    if st.get("skip"):
        return {"needed": True, "xml": None, "skip": st["skip"]}
    ranks = sorted(items_by_rank)
    mismatched = [n for n in st["numbers"] if n not in items_by_rank]
    for n, text in st["entries"]:
        item = items_by_rank.get(n)
        if item is not None and not _entry_describes_item(text, item):
            mismatched.append(n)
    needed = bool(mismatched) or st["numbers"] != ranks
    if not needed:
        return {"needed": False, "xml": None, "skip": None, "entries": len(st["numbers"]),
                "reordered": False, "renumbered": 0}
    # ---- match every entry to one item; a full bijection or nothing ---------
    candidates = []
    for idx, (_n, text) in enumerate(st["entries"]):
        for rank, item in items_by_rank.items():
            score = _zotero_entry_match_score(text, item)
            if score:
                candidates.append((score, idx, rank))
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    taken_entry, taken_rank, assignment = set(), set(), {}
    for score, idx, rank in candidates:
        if score < 4:
            break
        if idx in taken_entry or rank in taken_rank:
            continue
        assignment[idx] = rank
        taken_entry.add(idx)
        taken_rank.add(rank)
    if len(assignment) != len(st["entries"]) or taken_rank != set(ranks):
        return {"needed": True, "xml": None,
                "skip": (f"only {len(assignment)} of {len(st['entries'])} bibliography "
                         f"entries could be matched to a cited item")}
    # ---- rebuild: target paragraph k carries the entry whose item rank is k --
    contents_by_rank = {}
    for idx, rank in assignment.items():
        span = _zotero_entry_span_of_run(st["contents"][idx])
        if span is None:
            return {"needed": True, "xml": None, "skip": "a bibliography entry lost its number"}
        run = st["contents"][idx][span[0]:span[1]]
        new_run = re.sub(r"(<w:t(?:\s[^>]*)?>)(\d+)([\.\)]?)(\s*)(</w:t>)",
                         lambda m: m.group(1) + str(rank) + m.group(3) + m.group(4)
                         + m.group(5), run, count=1)
        contents_by_rank[rank] = (st["contents"][idx][:span[0]] + new_run
                                  + st["contents"][idx][span[1]:])
    reordered = any(rank != idx + 1 for idx, rank in assignment.items())
    pieces = []
    for k, rank in enumerate(ranks):
        head = st["spine"] if k == 0 else st["heads"][k]
        close = "" if (k == len(ranks) - 1 and st["end_in_last_entry"]) else "</w:p>"
        pieces.append(head + contents_by_rank[rank] + close)
    pieces.append(st["tail"])
    rebuilt = "".join(pieces)
    return {"needed": True, "xml": rebuilt, "skip": None, "entries": len(ranks),
            "reordered": reordered,
            "renumbered": sum(1 for idx, rank in assignment.items()
                              if st["numbers"][idx] != rank)}


def zotero_refresh_document(xml: str, para_texts: list = None,
                            style_ids: dict = None, limit: int = 1000) -> dict:
    """Apply the local refresh to one document.xml. See the section contract.

    Returns {"xml": <original or repaired>, "changed": bool, "fields_fixed":
    int, "entries": int, "reordered": bool, "changes": [str], "skip": reason,
    "nothing_to_do": bool}. `skip` with `nothing_to_do` is the clean no-op (the
    document already is what a refresh would write), not a refusal.
    """
    out = {"xml": xml, "changed": False, "fields_fixed": 0, "entries": 0,
           "reordered": False, "renumbered": 0, "changes": [], "skip": None}
    report = zotero_field_report(xml)
    state = zotero_citation_state(xml, para_texts, style_ids)
    item_frames = [f for f in report["fields"] if f["kind"] == "item"]
    if not item_frames:
        out["skip"] = "no live citation fields"
        return out
    if any(not f.get("complete") or not f.get("has_separate") for f in item_frames):
        out["skip"] = "a citation field is structurally incomplete"
        return out
    if not state["numeric"]:
        out["skip"] = ("the document's markers are not a numeric citation style; a refresh "
                       "of an author-year style is not reproduced offline")
        return out
    order = state["order"]
    items_by_rank = {}
    edits = []
    fields_fixed = 0
    for frame in item_frames:
        instr_m = INSTR_RE.search(xml, frame["begin"], frame["end"] or len(xml))
        if not instr_m:
            out["skip"] = "a citation field carries no instruction"
            return out
        inner = re.sub(r"^<w:instrText[^>]*>|</w:instrText>$", "",
                       instr_m.group(0), flags=re.S)
        instr_text = unesc(inner)
        js_span = _zotero_json_span(instr_text)
        if js_span is None:
            out["skip"] = "a citation field's JSON does not parse"
            return out
        js_start, js_end, js = js_span
        props = js.get("properties") or {}
        marker = props.get("formattedCitation") or ""
        cluster = _zotero_marker_cluster(marker)
        if cluster is None:
            out["skip"] = f"field {frame.get('citationID')!r} carries a marker shape the " \
                          f"refresh cannot rebuild"
            return out
        keys, ranks = [], []
        for ci in js.get("citationItems") or []:
            if not isinstance(ci, dict):
                out["skip"] = "a citation item is malformed"
                return out
            uri = (ci.get("uris") or [ci.get("uri") or ""])[0]
            key = str(uri or ci.get("id") or "")
            keys.append(key)
            ranks.append(order.get(key))
            data = ci.get("itemData") or {}
            if key and isinstance(data, dict) and data:
                items_by_rank.setdefault(order.get(key), data)
        if not keys or any(r is None for r in ranks):
            out["skip"] = f"field {frame.get('citationID')!r} cites an item with no rank"
            return out
        region = _zotero_result_region(xml, frame)
        if region is None:
            out["skip"] = f"field {frame.get('citationID')!r} has no simple result runs"
            return out
        current = _marker_numbers(marker)
        if len(current) != len(ranks):
            out["skip"] = (f"field {frame.get('citationID')!r} renders a different count of "
                           f"numbers ({len(current)}) than it cites items ({len(ranks)}); the "
                           f"cluster cannot be rebuilt safely")
            return out
        if sorted(current) == sorted(ranks):
            continue                      # consistent: nothing to rewrite
        new_cluster_raw, new_cluster = _zotero_cluster_for_ranks(ranks, cluster[2])
        new_marker = marker[:cluster[0]] + new_cluster_raw + marker[cluster[1]:]
        new_js = json.loads(json.dumps(js))
        new_js.setdefault("properties", {})
        new_js["properties"]["formattedCitation"] = new_marker
        new_js["properties"]["plainCitation"] = new_cluster
        new_json = json.dumps(new_js, ensure_ascii=False, separators=(",", ":"))
        new_instr = instr_text[:js_start] + new_json + instr_text[js_end:]
        open_tag = instr_m.group(0)[:instr_m.group(0).find(">") + 1]
        edits.append((instr_m.start(), instr_m.end(), open_tag + esc(new_instr)
                      + "</w:instrText>"))
        r_s, r_e, _runs, template = region
        edits.append((r_s, r_e, _zotero_result_run(template, new_cluster)))
        fields_fixed += 1
        if fields_fixed >= limit:
            out["skip"] = "too many stale fields for one refresh pass"
            return out
    # The marker edits are applied even when there are none: a document whose
    # markers already match can still carry a bibliography whose ORDER disagrees
    # (every entry describes the right work, but the paragraphs run 2,1), and
    # that is exactly what a Word/Zotero refresh re-sorts -- so the bibliography
    # phase below must not be skipped just because nothing was renumbered.
    refreshed = apply_edits(xml, edits) if edits else xml
    # ---- the bibliography ------------------------------------------------
    # Fresh offsets: the marker edits above changed the byte positions of
    # everything after them, so the bibliography frame must be re-read from the
    # REFRESHED text (the original frame's offsets would fall inside another
    # field's region and the separate/end probe would fail).
    bib_frames = [f for f in zotero_field_report(refreshed)["fields"]
                  if f["kind"] == "bibliography"]
    bib_info = {"needed": False, "entries": 0, "reordered": False, "renumbered": 0}
    bib_rebuilt = False
    if len(bib_frames) > 1:
        out["skip"] = "more than one bibliography field in one document"
        return out
    if bib_frames:
        st = zotero_bibliography_state(refreshed, bib_frames[0])
        if st.get("skip") == "the bibliography field carries no entries":
            # The numbered list lives OUTSIDE the field (a plain list, or a
            # Word variant that keeps only a placeholder inside it). The field
            # cannot rebuild it; the marker refresh may still proceed when the
            # list is already consistent with the new ranks -- otherwise a
            # half-refresh would point the markers at the wrong entries.
            probe = zotero_parity_rows(refreshed, [text_of(p[2]) for p in paragraphs(refreshed)],
                                       style_ids)
            bad = [r for r in probe
                   if r["rule"] == "FMT-Z2"
                   or (r["rule"] == "FMT-Z3" and "never cited" in r["evidence"])]
            if bad:
                out["skip"] = ("the bibliography list is outside its field and does not match "
                               "the citation order: " + str(bad[0]["evidence"])[:120])
                return out
        else:
            plan = _zotero_bibliography_plan(refreshed, bib_frames[0], items_by_rank)
            if plan.get("skip"):
                out["skip"] = f"bibliography rebuild refused: {plan['skip']}"
                return out
            if plan["needed"]:
                bib_info = plan
                if plan.get("xml") is None:
                    out["skip"] = "bibliography rebuild refused"
                    return out
                st2 = zotero_bibliography_state(refreshed, bib_frames[0])
                if st2 is None or st2.get("skip"):
                    out["skip"] = "bibliography rebuild refused (paragraph spans changed)"
                    return out
                refreshed = (refreshed[:st2["start"]] + plan["xml"]
                             + refreshed[st2["end"]:])
                bib_rebuilt = True
    if not edits and not bib_rebuilt:
        out["skip"] = ("every marker already matches the document's citation order and the "
                       "bibliography already runs in rank order; only the style store can "
                       "still differ")
        # Nothing to repair is a SUCCESS, not a refusal. `cmd_zotero_refresh`
        # distinguishes the two by this flag: a document a Word/Zotero refresh
        # would leave alone must not exit 1, or every stage's session reads a
        # healthy file as "the offline refresh refused it" and files a hand-off
        # for numbering that is already correct.
        out["nothing_to_do"] = True
        return out
    # ---- verify -----------------------------------------------------------
    try:
        import xml.etree.ElementTree as _ET
        _ET.fromstring(refreshed)
    except _ET.ParseError as e:                                        # noqa: F821
        out["skip"] = f"the refreshed XML does not parse ({e})"
        return out
    new_paras = [text_of(p[2]) for p in paragraphs(refreshed)]
    rows_before = zotero_parity_rows(xml, para_texts, style_ids)
    rows_after = zotero_parity_rows(refreshed, new_paras, style_ids)
    high_before = sum(1 for r in rows_before if r["rule"] in ("FMT-Z1", "FMT-Z2", "FMT-Z4"))
    high_after = sum(1 for r in rows_after if r["rule"] in ("FMT-Z1", "FMT-Z2", "FMT-Z4"))
    if high_after > high_before or (high_after and not high_before):
        out["skip"] = (f"the refreshed document still carries {high_after} high-severity "
                       f"parity row(s); nothing was written")
        return out
    new_state = zotero_citation_state(refreshed, new_paras, style_ids)
    old_keys = [(f["citationID"], tuple(f["items"])) for f in state["fields"]]
    new_keys = [(f["citationID"], tuple(f["items"])) for f in new_state["fields"]]
    if old_keys != new_keys:
        out["skip"] = "the refresh would change which items the fields cite; nothing was written"
        return out
    changes = []
    if fields_fixed:
        changes.append(f"Zotero refresh (offline): renumbered {fields_fixed} stale citation "
                       f"marker(s) to the document's own citation order")
    if bib_rebuilt:
        changes.append(f"rebuilt the bibliography in citation order "
                       f"({bib_info.get('entries', 0)} entries, "
                       f"{bib_info.get('renumbered', 0)} renumbered"
                       + (", reordered" if bib_info.get("reordered") else "") + ")")
    out.update({"xml": refreshed, "changed": True, "fields_fixed": fields_fixed,
                "entries": bib_info.get("entries", 0),
                "reordered": bool(bib_info.get("reordered")),
                "renumbered": bib_info.get("renumbered", 0),
                "changes": changes, "skip": None,
                "rows_before": [r["rule"] for r in rows_before],
                "rows_after": [r["rule"] for r in rows_after]})
    return out


def zotero_style_reconcile(parts: dict, preferred: str = "") -> dict:
    """Make every Zotero style store name ONE style (FMT-Z5's repair).

    The style URL is the only byte touched. The preferred style is the
    caller's (the venue's own CSL style when the profile names one); otherwise
    the store `docProps/custom.xml` names is kept, because that is the store
    the current Zotero Word plugin writes and the one the rendered entries in
    this document lineage were produced with.
    """
    ids = zotero_style_ids(parts)
    distinct = sorted(set(ids.values()))
    out = {"changed": False, "from": dict(ids), "to": {}, "changes": []}
    if len(distinct) <= 1:
        return out
    target = preferred if preferred in distinct else ""
    if not target:
        target = ids.get("docProps/custom.xml") or distinct[-1]
    new_parts = dict(parts)
    for name, sid in sorted(ids.items()):
        if sid == target:
            continue
        raw = new_parts.get(name)
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
        # Zotero 6 writes an `http://` store and the XML text may carry
        # `&quot;` right after the id, so the whole URL is replaced by pattern
        # (a literal `https://` replace missed the legacy store entirely).
        new_text = re.sub(r"https?://www\.zotero\.org/styles/" + re.escape(sid) + r"\b",
                          f"https://www.zotero.org/styles/{target}", text)
        if new_text != text:
            new_parts[name] = new_text.encode("utf-8") if isinstance(raw, bytes) else new_text
            out["to"][name] = target
    if out["to"]:
        out["changed"] = True
        out["parts"] = new_parts
        out["changes"].append(
            "Zotero style stores reconciled to "
            f"{target!r} (" + "; ".join(f"{n}: {ids[n]} -> {target}"
                                        for n in sorted(out["to"])) + ")")
    return out


def refresh_zotero_parts(parts: dict, policy: dict = None) -> dict:
    """The local refresh + style reconcile over one package's parts (in memory).

    `parts` is {zip name: bytes}. Returns {"parts": updated|None, "changed":
    bool, "changes": [str], "skip": reason|None, "zotero": report|None,
    "nothing_to_do": bool}. `skip` with `nothing_to_do` is the clean no-op (the
    document's numbering and bibliography already are what the refresh would
    write); any other `skip` is a refusal. The caller decides whether to swap
    the parts in; nothing is written here.
    """
    policy = policy or {}
    rep = {"parts": None, "changed": False, "changes": [], "skip": None, "zotero": None,
           "nothing_to_do": False}
    if "word/document.xml" not in parts:
        rep["skip"] = "no word/document.xml"
        return rep
    style_names = [n for n in ("word/settings.xml", "docProps/custom.xml") if n in parts]
    style_names += [n for n in parts if re.match(r"customXml/item\d*\.xml$", n)]
    style_parts = {n: parts[n].decode("utf-8", "replace") for n in style_names}
    # The parts the FIELD READER (`ZOTERO_FIELD_PARTS` +
    # `ZOTERO_FIELD_AUX_PARTS_RE`, i.e. the set `zotero-check` scans) treats as
    # citation surfaces must all be REFUSED here, not just footnotes/endnotes: a
    # stale live field in a header, footer or comment was neither refreshed nor
    # named, so the refresh reported success and `zotero-check` then failed on
    # the same package.
    other_field_parts = [n for n in parts
                         if (n in ZOTERO_FIELD_PARTS
                             or ZOTERO_FIELD_AUX_PARTS_RE.search(n))
                         and n != "word/document.xml"
                         and b"ADDIN ZOTERO_ITEM" in parts[n]]
    style_info = zotero_style_reconcile(style_parts,
                                        str(policy.get("zotero_style") or ""))
    new_parts = dict(parts)
    if style_info.get("changed"):
        # Only the stores whose style id changed are re-encoded; every other
        # part keeps its original bytes.
        for n in sorted(style_info.get("to") or {}):
            text = style_info["parts"][n]
            new_parts[n] = text.encode("utf-8") if isinstance(text, str) else text
            style_parts[n] = text.decode("utf-8", "replace") if isinstance(text, bytes) else text
        rep["changes"].extend(style_info["changes"])
    xml = new_parts["word/document.xml"].decode("utf-8", "replace")
    if other_field_parts:
        rep["skip"] = ("citation fields live outside word/document.xml "
                       f"({', '.join(other_field_parts)}); the offline refresh is limited to "
                       f"the main part -- no numbering was written")
    else:
        zot = zotero_refresh_document(xml, [text_of(p[2]) for p in paragraphs(xml)],
                                      style_ids=zotero_style_ids(style_parts))
        rep["zotero"] = {k: v for k, v in zot.items() if k != "xml"}
        if zot.get("changed"):
            new_parts["word/document.xml"] = zot["xml"].encode("utf-8")
            rep["changes"].extend(zot["changes"])
        elif zot.get("skip"):
            rep["skip"] = zot["skip"]
            rep["nothing_to_do"] = bool(zot.get("nothing_to_do"))
    rep["changed"] = bool(rep["changes"])
    if rep["changed"]:
        rep["parts"] = new_parts
    return rep


def refresh_zotero_package(src, out=None, policy: dict = None) -> dict:
    """Apply the local refresh + style reconcile to one DOCX (zip-level).

    All other parts are copied byte-identically; `out` defaults to an in-place
    replace. Returns a report with `changed`, `changes`, `skip`,
    `nothing_to_do` (a skip that is NOT a refusal: the document was already
    clean), the field counts before/after and the parity rows before/after.
    """
    src = Path(src)
    rep = {"source": str(src), "output": str(out or src), "ok": True, "changed": False,
           "changes": [], "skip": None, "zotero": None, "nothing_to_do": False}
    try:
        with zipfile.ZipFile(src) as pkg:
            names = [n for n in pkg.namelist() if not n.endswith("/")]
            if "word/document.xml" not in names:
                return dict(rep, ok=False, skip="no word/document.xml")
            parts = {n: pkg.read(n) for n in names}
    except (OSError, zipfile.BadZipFile) as e:
        return dict(rep, ok=False, skip=f"unreadable DOCX ({type(e).__name__}: {e})")
    inner = refresh_zotero_parts(parts, policy)
    rep["changes"] = list(inner.get("changes") or [])
    rep["skip"] = inner.get("skip")
    rep["nothing_to_do"] = bool(inner.get("nothing_to_do"))
    rep["zotero"] = inner.get("zotero")
    if not inner.get("changed"):
        return rep
    rep["changed"] = True
    parts = inner["parts"]
    dst = Path(out) if out is not None else src
    tmp = dst.with_name(f".{dst.name}.zotrefresh{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for n in names:
                z.writestr(n, parts[n])
        os.replace(tmp, dst)
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return dict(rep, ok=False, skip=f"could not write the refreshed DOCX ({e})")
    rep["output"] = str(dst)
    return rep


# --------------------------------------------------------------------------
# REFERENCE-ENTRY REPAIRS (the FMT-R1/R2/R3 classes, auto-repaired)
#
# A malformed entry inside a live Zotero bibliography field cannot be fixed by
# the numbering refresh: its TEXT is wrong ("Front. Genet. Volume 11-2020"),
# not its number. The facts needed to repair it are usually already in the
# submission: a sibling .bib the paper's own supplementary ships. When a
# record there carries what a flagged entry is missing (a fused volume, a
# locator for a bare year, a year for a software URL), the repair is applied
# to the entry's own runs and re-checked against the same rules. Nothing is
# invented: no record, no repair.
# --------------------------------------------------------------------------

BIB_ENTRY_START_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.S)


def _strip_bib_comments(text: str) -> str:
    """`text` with BibTeX `%` comments removed, quote-, brace- and escape-aware.

    A `%` starts a comment only where BibTeX allows one: outside a value. That
    means outside a quoted string AND outside a brace GROUP -- a `%` inside
    `title = "Growth was 100%"` or inside `title = {A 50% effect}` is data (a
    brace value runs from depth 2 down), while a `%` at the entry-body level
    (depth 1) or between entries (depth 0) comments out the rest of the line. An
    escaped `\\%` is a literal percent, not a comment start. Newlines survive so
    line structure -- and the field regexes that read it -- stay intact. Without
    this, ANY `%` on an entry's `@` line dropped the whole entry, and a `%`
    comment carrying a brace (`% TODO: check the } case`) closed the entry
    early: the live `pages`/`year` fields after it were lost, and a commented
    `% pages = {111}` OVERWROTE the live `pages = {7}` because the comment's
    text was scanned as fields. Treating a `%` inside a brace value as a
    comment, in turn, destroyed the field it sits in (`title = {A 50% effect}`
    came back as `A 50 pages = {7}, year = {2020}`).
    """
    out = []
    i, n = 0, len(text)
    quote = False
    depth = 0
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            out.append(ch)
            out.append(text[i + 1])
            i += 2
            continue
        if ch == '"' and depth <= 1:
            # A quote delimits a value only at the entry level; inside a brace
            # value it is ordinary text, exactly as the entry scanner reads it.
            quote = not quote
            out.append(ch)
            i += 1
            continue
        if ch == "%" and not quote and depth <= 1:
            j = text.find("\n", i)
            if j < 0:
                break
            i = j                     # the newline itself is kept
            continue
        if not quote:
            if ch == "{":
                depth += 1
            elif ch == "}" and depth:
                depth -= 1
        out.append(ch)
        i += 1
    return "".join(out)


def load_bib_facts(paths) -> list:
    """Parse .bib files into fact records for entry repair (stdlib only)."""
    records = []
    for p in paths or []:
        try:
            text = Path(p).read_text("utf-8", "replace")
        except OSError:
            continue
        text = _strip_bib_comments(text)
        pos = 0
        while True:
            m = BIB_ENTRY_START_RE.search(text, pos)
            if not m:
                break
            # Body = up to the matching closing brace of this entry.
            i = m.end()
            depth = 1
            quote = False
            while i < len(text) and depth:
                ch = text[i]
                if ch == "\\":
                    i += 2
                    continue
                if ch == '"' and depth == 1:
                    # A brace inside a quoted value ("A title with a } brace")
                    # is text, not the entry's closing brace. The quote is a
                    # DELIMITER only at the entry level, though: inside a brace
                    # value BibTeX treats it as an ordinary character, so
                    # `title = {A 5" incision}` -- an ODD number of quotes -- must
                    # not unbalance the walk and swallow the following entries.
                    quote = not quote
                elif not quote and ch == "{":
                    depth += 1
                elif not quote and ch == "}":
                    depth -= 1
                i += 1
            body = text[m.end():i - 1]
            pos = i
            # A commented-out entry ("% @article{...}") is not a fact the
            # bibliography states; its comment text is already gone above.
            fields = {}
            for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)",
                                  body):
                name = fm.group(1).lower()
                value = fm.group(2).strip()
                if value.startswith("{") and value.endswith("}"):
                    value = value[1:-1]
                elif value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                fields[name] = re.sub(r"\s+", " ", value).strip()
            author = fields.get("author") or ""
            first_family = ""
            if author:
                first = author.split(" and ")[0]
                first_family = (first.split(",")[0] if "," in first
                                else first.split()[-1]).strip()
            year = ""
            date = fields.get("date") or fields.get("year") or ""
            ym = re.search(r"(?:19|20)\d{2}", date)
            if ym:
                year = ym.group(0)
            records.append({
                "key": m.group(2), "type": m.group(1).lower(),
                "title": fields.get("title", ""), "first_family": first_family,
                "year": year, "journal": fields.get("journaltitle")
                or fields.get("journal") or fields.get("shortjournal", ""),
                "volume": fields.get("volume", ""), "pages": fields.get("pages", ""),
                "doi": (fields.get("doi", "") or "").strip(),
                "eprint": fields.get("eprint", ""),
                "eprinttype": fields.get("eprinttype", ""),
                "url": fields.get("url", ""),
                "file": str(p)})
    return records


def _bib_record_for_entry(entry_text: str, records: list):
    """The record a reference entry is about (DOI first, then name+title)."""
    text = re.sub(r"\s+", " ", entry_text or "")
    dois = {d.lower().rstrip(".,;)") for d in REF_DOI_RE.findall(text)}
    if dois:
        for r in records:
            if r.get("doi") and r["doi"].lower().rstrip(".,;)") in dois:
                return r
    low = text.lower()
    best, best_score = None, 0
    for r in records:
        score = 0
        fam = (r.get("first_family") or "").lower()
        if fam and fam in low:
            score += 3
        if r.get("year") and f"({r['year']})" in text:
            score += 1
        title = str(r.get("title") or "")
        for t in re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split():
            if len(t) > 4 and t not in ZOTERO_TOKEN_STOPWORDS and t in low:
                score += 1
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= 4 else None


def _iter_wt_elements(para: str):
    for m in re.finditer(r"<w:t(?:\s[^>]*)?>.*?</w:t>", para, re.S):
        inner = m.group(0)
        text = unesc(inner[inner.find(">") + 1:inner.rfind("<")])
        yield m.start(), m.end(), text


def _set_wt_text(para: str, start: int, end: int, text: str) -> str:
    """The replacement for one w:t element's [start, end) span.

    The opening tag is kept verbatim (attributes such as `xml:space` survive);
    only the element's content changes. A replacement that BEGINS or ENDS with
    whitespace at the element's boundary needs `xml:space="preserve"`: without
    it Word ignores that whitespace on load, so a "verified" repair delivered a
    text the pipeline had not written. `rewrite_text_spans` -- the sibling
    emitter -- has always added the attribute for exactly this case.
    """
    inner_open = para.find(">", start) + 1
    open_tag = para[start:inner_open]
    if text != text.strip():
        if "xml:space" not in open_tag:
            open_tag = open_tag[:open_tag.rfind(">")] + ' xml:space="preserve">'
        elif not re.search(r"""xml:space\s*=\s*(?:"preserve"|'preserve')""", open_tag):
            # An existing `xml:space="default"` explicitly tells the reader to
            # trim the boundary whitespace this replacement writes (the exact
            # bug the attribute exists to prevent), and the `"xml:space" not in
            # open_tag` test above waved it through because the NAME was there.
            open_tag = re.sub(r"""xml:space\s*=\s*(?:"[^"]*"|'[^']*')""",
                              'xml:space="preserve"', open_tag, count=1)
    return open_tag + esc(text) + "</w:t>"


def _replace_text_in_para(para: str, old: str, new: str):
    """Replace one substring of the paragraph's visible text.

    A match inside ONE `w:t` element keeps that element's run untouched. A match
    spanning several elements is allowed ONLY when every touched run is plain
    (carries no `w:rPr`): the replacement then lands in the first element and
    the others are emptied, so no run property is silently dropped. Anything
    else is refused (`None`) -- the caller records the skip.
    """
    spans = list(_iter_wt_elements(para))
    joined, offsets = "", []
    for s, e, t in spans:
        offsets.append((len(joined), s, e, t))
        joined += t
    at = joined.find(old)
    if at < 0:
        return None
    touched = []
    for pos, s, e, t in offsets:
        if pos + len(t) <= at:
            continue
        if pos >= at + len(old):
            break
        touched.append((pos, s, e, t))
    if not touched:
        return None
    first, last = touched[0], touched[-1]
    head = first[3][:at - first[0]]
    tail_off = at + len(old) - last[0]
    if tail_off < 0 or tail_off > len(last[3]):
        return None
    tail = last[3][tail_off:]
    if len(touched) > 1:
        # The run that OWNS the w:t is the enclosing `<w:r>`: `w:rPr` lives
        # there, never inside the `w:t` span, so the old `<w:rPr" in
        # para[s:e]` test could not fire -- a multi-run match happily dropped
        # the italic/bold a half-replaced entry carried.
        for _pos, s, e, _t in touched:
            run_start = max(para.rfind("<w:r>", 0, s), para.rfind("<w:r ", 0, s))
            run_end = para.find("</w:r>", e)
            if run_start < 0 or run_end < 0:
                continue                  # not a well-formed run: leave it alone
            if "<w:rPr" in para[run_start:run_end]:
                return None
    edits = []
    for k, (_pos, s, e, t) in enumerate(touched):
        text = (head + new + tail) if k == 0 else ""
        edits.append((s, e, _set_wt_text(para, s, e, text)))
    return apply_edits(para, edits)


def repair_reference_entries(xml: str, records: list) -> dict:
    """Apply the FMT-R1/R2/R3 repairs a sibling bibliography proves.

    Returns {"xml", "changed", "repairs": [{entry, rule, before, after}],
    "skipped": [reason]}. `records` comes from `load_bib_facts`.
    """
    out = {"xml": xml, "changed": False, "repairs": [], "skipped": []}
    if not records:
        out["skipped"].append("no bibliography file supplied any facts")
        return out
    paras = paragraphs(xml)
    texts = [text_of(p[2]) for p in paras]
    first = _bibliography_entry_start(texts)
    # Keyed by the paragraph's ORIGINAL span: `apply_edits` splices every edit at
    # its own offsets, so two edits for one paragraph spliced the second
    # replacement on shifted coordinates and ate the bytes that followed the
    # paragraph (`</w:p>` became `:p>`), and fix_package's well-formedness check
    # then aborted the ENTIRE fix run with a misleading "repaired file was not
    # accepted". An entry that trips two rules at once is realistic: FMT-R1 (a
    # fused volume-year) plus FMT-R2 (a bare year with no venue). The loop chains
    # `para`, so the last write for a span IS the paragraph both repairs produced.
    edits, repairs = {}, []
    for idx in range(first, len(paras)):
        p0, p1, para = paras[idx]
        entry = re.sub(r"\s+", " ", texts[idx]).strip()
        m = re.match(r"^\s*(\d+)\s*[\.\)]\s*(.+)$", entry)
        if not m or len(entry.split()) < 4:
            continue
        rec = _bib_record_for_entry(entry, records)
        if rec is None:
            continue
        cands = []
        # P1 -- a volume fused to a year ("Volume 11-2020"): use the volume and
        # article/page number the bibliography records.
        vm = REF_VOLUME_MALFORMED_RE.search(entry)
        page = (rec.get("pages") or "").strip()
        if vm and rec.get("volume") and page:
            old = vm.group(0)
            tail = entry[vm.end():]
            rest = tail[2:] if tail.startswith(", ") else None
            # A tail that already carries a locator ("Volume 11-2020, 565825
            # (2020)", "Volume 11-2020: 565825 (2020)", "Volume 11-2020
            # (565825)") must not gain the article number again -- writing it
            # twice printed it twice ("11, 565825 565825 (2020)"). A locator is
            # a token that CARRIES A NUMBER: the old first-character-is-
            # alphanumeric test also read prose as a locator, so
            # "Volume 11-2020, online (2020)." had its volume deleted and no
            # article number inserted at all. The brackets/colon form
            # ("(565825)", ": 565825") is a locator too, so leading punctuation
            # is skipped first; a bare year is not a locator.
            head_text = (rest if rest is not None else tail).lstrip(" \t:;,.-")
            lead = head_text.split(None, 1)[0] if head_text else ""
            core = lead.strip("()[]{}.,;:'\"")
            has_locator = bool(re.search(r"\d", core)) \
                and not re.fullmatch(r"(?:19|20)\d{2}", core)
            if rest is not None:
                old = old + ", "
                new = (f"{rec['volume']}, " if has_locator
                       else f"{rec['volume']}, {page} ")
            else:
                new = f"{rec['volume']}" if has_locator else f"{rec['volume']}, {page}"
            cands.append(("FMT-R1", old, new))
        # P2 -- an entry that ends at a bare "(YEAR)" with no venue at all: the
        # bibliography's own locator makes it retrievable.
        if not REF_VENUE_HINT_RE.search(entry) and REF_BARE_YEAR_END_RE.search(entry):
            year = rec.get("year") or ""
            locator = ""
            if rec.get("eprint") and (rec.get("eprinttype") or "").lower().endswith("arxiv"):
                locator = f"Preprint at https://arxiv.org/abs/{rec['eprint']}"
            elif rec.get("eprint") and "arxiv" in (rec.get("url") or "").lower():
                locator = f"Preprint at https://arxiv.org/abs/{rec['eprint']}"
            elif rec.get("doi"):
                locator = f"Preprint at https://doi.org/{rec['doi']}"
            if locator and year:
                ym = re.search(r"\(\s*" + re.escape(year) + r"\s*\)", entry)
                if ym:
                    cands.append(("FMT-R2", ym.group(0),
                                  f"{locator} ({year})"))
        # P3 -- a repository/software citation with no year: the bibliography
        # dates it.
        if (REF_REPO_HOST_RE.search(entry) and not REF_DOI_RE.search(entry)
                and not REF_PREPRINT_RE.search(entry)
                and not REF_VERSION_HINT_RE.search(entry)
                and rec.get("year") and not re.search(r"(?:19|20)\d{2}", entry)):
            um = re.search(r"(?P<lead>\.\s+)(?P<url>https?://\S+)", entry)
            if um:
                cands.append(("FMT-R3", um.group(0),
                              f" ({rec['year']}). " + um.group("url")))
        for rule, old, new in cands:
            new_para = _replace_text_in_para(para, old, new)
            if new_para is None:
                out["skipped"].append(
                    f"{rule}: the text to replace in entry {m.group(1)} spans runs")
                continue
            edits[p0, p1] = new_para
            repairs.append({"entry": m.group(1), "rule": rule,
                            "before": old[:80], "after": new[:80]})
            para = new_para
    if not edits:
        return out
    new_xml = apply_edits(xml, [(s, e, v) for (s, e), v in edits.items()])
    # Verify with the same rule set: no repair may leave its own rule firing.
    new_texts = [text_of(p[2]) for p in paragraphs(new_xml)]
    # The entry flag must accept the number fused to the text ("15.Dong"):
    # Word renders the separator as a TAB, which `text_of` drops, and a
    # whitespace-requiring pattern then read every entry as "not a reference"
    # and the verification counted zero rows on both sides.
    is_ref = lambda t: bool(re.match(r"^\s*\d+\s*[\.\)]\s*\S", t))  # noqa: E731
    before_rows = reference_entry_rows(texts, [is_ref(t) for t in texts])
    after_rows = reference_entry_rows(new_texts, [is_ref(t) for t in new_texts])
    rules = {r["rule"] for r in repairs}
    before_n = sum(1 for r in before_rows if r["rule"] in rules)
    after_n = sum(1 for r in after_rows if r["rule"] in rules)
    if after_n >= before_n:
        out["skipped"].append("the repair did not clear its own rule; nothing was written")
        return out
    out.update({"xml": new_xml, "changed": True, "repairs": repairs})
    return out


def analyse_document(xml: str, styles: dict, policy: dict, doc: str,
                     sizes: dict = None, rels: dict = None) -> dict:
    rows = []
    paras = paragraphs(xml)
    franges = field_ranges(xml)

    def row(rule, severity, location, evidence, detail, protected=False, fix=None):
        # A finding inside a Zotero field is reported, never silently edited --
        # the fix kind has to say so, or the fixer's "all mechanical findings
        # resolved" verification would fail on a row it is not allowed to touch.
        # `fix` overrides the rule's default: a caption block the merge must
        # refuse (a field or an image inside it) is an editorial row even though
        # the rule is mechanical for the blocks the fixer can merge.
        fix = fix or _fix_kind(rule, policy)
        if protected and fix == "mechanical":
            fix = "style-field"
        rows.append({"rule": rule, "severity": severity, "document": doc, "location": location,
                     "evidence": evidence, "detail": detail,
                     "fix": fix, "protected": protected, "tier": tier_of(rule)})

    title_block_end = None
    for idx, (_, _, para) in enumerate(paras):
        if re.match(r"^\s*(abstract|summary)\s*:?\s*$", text_of(para), re.I):
            title_block_end = idx
            break

    # ---- structural -----------------------------------------------------------
    for idx, (p0, p1, para) in enumerate(paras):
        text = text_of(para)
        # A field run is CONTENT, never an empty paragraph: the fixer refuses to
        # touch one (moving its page break would unbalance the field), so a row
        # the scan still filed `mechanical` could never be repaired and made the
        # whole fix verify as failed. The two sides read the same definition.
        empty = not text.strip() and not has_drawing(para) and not has_field(para)
        if PAGEBREAK_RE.search(para) and empty:
            row("FMT-S1", "high", f"p{idx}", "empty paragraph holding a page break",
                "break-only paragraphs render as a blank page (or a stray empty line); delete it "
                "and put w:pageBreakBefore on the paragraph that should start the page")
        ppr = ppr_of(para)
        style = elem_val(ppr, "pStyle")
        if style and style.startswith("Heading"):
            if policy["heading_keep_with_next"] and not (ppr and "<w:keepNext" in ppr):
                row("FMT-T3a", "medium", f"p{idx}", f"heading {text[:40]!r} has no keepNext",
                    "headings can be orphaned at the bottom of a page; add keepNext + keepLines")
            direct = {elem_val(rpr_of(r[2]), "sz") for r in runs(para)
                      if text_of(r[2]).strip() and elem_val(rpr_of(r[2]), "sz")}
            want = style_sz(styles, style)
            if want and direct and any(s != want for s in direct):
                row("FMT-T3b", "medium", f"p{idx}",
                    f"heading runs sz={sorted(direct)} vs style {style} sz={want}",
                    "direct run sizes contradict the heading style definition")

    # Stray empty paragraphs: template-prescribed blanks (the front-matter spacer
    # above the title, a slot the journal's own template carries) are exempt; a
    # blank attached to a heading is FMT-S8, a run beyond the cap is FMT-S6.
    rows.extend(stray_empty_paragraph_rows(paras, policy, doc, xml))

    # ---- legends / captions ---------------------------------------------------
    # The unit is the caption BLOCK: a label ("Fig. 2 | ...", "Figure S1. ...",
    # "Table 3 ...") plus the paragraphs that continue it. A caption is ONE
    # paragraph (FMT-T2c) and every paragraph of one caption carries the
    # caption's spacing (FMT-T2a/T2b): a continuation left without direct
    # spacing inherits the document default and renders 1.5-spaced beside a
    # single-spaced caption -- the 2026-10-14 packages' Fig. 3 defect. Blocks
    # are read inside the venue's own display areas (see
    # `caption_block_ranges`); a figure label outside one still gets its own
    # spacing rows, exactly as before.
    areas = display_area_kinds(paras)
    blocks = caption_block_ranges(paras, areas, container_spans(xml), xml=xml)
    legend_rows = []
    for b in blocks:
        members = [b["label"]] + (b["continuations"] if b["in_area"] else [])
        for m in members:
            legend_rows.append((m, b))
    in_blocks = {m for m, _ in legend_rows}
    for i, (_, _, p) in enumerate(paras):
        if LEGEND_RE.match(text_of(p)) and i not in in_blocks:
            legend_rows.append((i, None))
    legend_idx = sorted({m for m, _ in legend_rows})
    for i, b in sorted(legend_rows):
        para = paras[i][2]
        if b is not None and i != b["label"]:
            what = (f"continuation paragraph of the {b['kind']} caption "
                    f"{text_of(paras[b['label']][2]).strip()[:40]!r} (p{b['label']})")
        elif b is not None:
            what = f"{b['kind']} caption {text_of(para).strip()[:40]!r}"
        else:
            what = f"legend {text_of(para).strip()[:40]!r}"
        sp = elem(ppr_of(para), "spacing")
        line, before, after = attr(sp, "line"), attr(sp, "before"), attr(sp, "after")
        if line != str(policy["caption_line"]):
            row("FMT-T2a", "medium", f"p{i}",
                f"{what} line spacing {line or 'inherit'} != {policy['caption_line']} "
                f"(single)",
                "a caption is single-spaced: a continuation left at the body's own "
                "spacing renders one caption at two line spacings")
        if before != str(policy["caption_space"]) or after != str(policy["caption_space"]):
            row("FMT-T2b", "low", f"p{i}",
                f"{what} spacing before={before} after={after} != "
                f"{policy['caption_space']}",
                "legend paragraph spacing differs between captions")
    for b in blocks:
        if not (b["in_area"] and b["continuations"]):
            continue
        conts = ", ".join(f"p{c}" for c in b["continuations"][:4])
        if len(b["continuations"]) > 4:
            conts += f", +{len(b['continuations']) - 4} more"
        row("FMT-T2c", "medium", f"p{b['label']}",
            f"the {b['kind']} caption {text_of(paras[b['label']][2]).strip()[:50]!r} "
            f"continues in {len(b['continuations'])} more paragraph(s) ({conts})",
            "a caption is one paragraph: merge the continuation paragraph(s) into the "
            "caption so the legend renders (and is read) as one block",
            fix=None if b.get("mergeable") else "editorial")
    # One caption family, one paragraph style: a caption that carries a
    # different style from the majority of its siblings in the same area (a
    # front-matter 'Author List' style on the first supplementary legend, say)
    # renders differently from every other caption. A tie reports nothing --
    # there is no majority to follow.
    for area_kind in ("figure", "table"):
        members = [b["label"] for b in blocks if b["in_area"] and b["kind"] == area_kind]
        if len(members) < 2:
            continue
        seen = Counter(_para_style(paras[i][2]) for i in members)
        if len(seen) < 2:
            continue
        majority, count = seen.most_common(1)[0]
        if count * 2 <= len(members):
            continue
        for i in members:
            style = _para_style(paras[i][2])
            if style == majority:
                continue
            row("FMT-T2d", "low", f"p{i}",
                f"the {area_kind} caption {text_of(paras[i][2]).strip()[:50]!r} carries "
                f"paragraph style {style or '(body)'!r} while {count} of "
                f"{len(members)} captions in this area use "
                f"{majority or '(body)'!r}",
                "one caption family, one paragraph style: align the minority with its "
                "siblings")

    # ---- italics / journal emphasis -------------------------------------------
    # What is italic is decided by the FULL style precedence (direct rPr >
    # character style > paragraph style > document defaults). Reading only the
    # run's own `<w:i/>` misses an italic that lives in a character style such as
    # Word's "Emphasis" -- on a real cover letter that made "Nature
    # Biotechnology" italic in one sentence, roman in the next, and looked clean
    # to this scanner.
    policy_j = policy["journal_italics"]
    journal_regions = defaultdict(lambda: defaultdict(lambda: {True: [], False: []}))
    for idx, (p0, p1, para) in enumerate(paras):
        text = text_of(para)
        style = elem_val(ppr_of(para), "pStyle")
        analysis = journal_emphasis_runs(styles, style, para)
        region = "refs" if style == "Bibliography" else "prose"
        for r0, r1, run in runs(para):
            rtext = text_of(run)
            if not rtext.strip() or not run_is_italic(styles, style, run):
                continue
            field = in_field(franges, p0 + r0)
            protect = bool(field)
            if title_block_end is not None and idx < title_block_end \
                    and re.search(r"@|Correspondence|ORCID", text, re.I):
                row("FMT-T6a", "medium", f"p{idx}",
                    f"italic run in the title/correspondence block: {rtext[:50]!r}",
                    "the correspondence and affiliation blocks must be roman"
                    + (f" (Zotero field: {field})" if field else ""), protected=protect)
            if style == "Bibliography" and re.search(r"\bet\s+al\.", rtext):
                row("FMT-T6b", "medium", f"p{idx}", f"italic 'et al.' in a reference: {rtext[:40]!r}",
                    "only the journal title is italic in a reference"
                    + (f" (Zotero field: {field})" if field else ""), protected=protect)
        for r0, _r1, run, names in analysis["italic"]:
            field_here = in_field(franges, p0 + r0)
            journal_regions[region][names[0].lower()][True].append((idx, field_here))
            if region == "prose" and policy_j in ("refs-only", "off"):
                row("FMT-T6c", "low", f"p{idx}",
                    f"italic journal name outside the reference list: {', '.join(names)!r}",
                    "policy: journal titles are italic only in the reference list"
                    + (f" (Zotero field: {field_here})" if field_here else ""),
                    protected=bool(field_here))
        for r0, _r1, run, names in analysis["roman"]:
            field_here = in_field(franges, p0 + r0)
            journal_regions[region][names[0].lower()][False].append((idx, field_here))
            # Only a run that IS the journal title is auto-fixable: italicising a
            # run that also carries the volume and page numbers would rewrite more
            # than the title (the mixed-treatment row T6e still reports it).
            if (((region == "refs" and policy_j in ("refs-only", "everywhere"))
                 or (region == "prose" and policy_j == "everywhere"))
                    and all(_title_only(text_of(run), n) for n in names)):
                row("FMT-T6g", "low", f"p{idx}",
                    f"roman journal title where the policy asks for italics: "
                    f"{', '.join(names)!r}",
                    "policy: journal titles are italic in the reference list"
                    + (" and in the body text" if region == "prose" else "")
                    + (f" (Zotero field: {field_here})" if field_here else ""),
                    protected=bool(field_here))
        for r0, _r1, _run, extra, name in analysis["continuation"]:
            field_here = in_field(franges, p0 + r0)
            # Prose only: a reference list legitimately emphasises a title that
            # contains several capitalised words (see _has_lowercase_word).
            if region != "prose":
                continue
            row("FMT-T6f", "medium", f"p{idx}",
                f"emphasis continues past the journal title ({name!r}): {extra[:40]!r}",
                "only the journal title itself may be emphasised; the surrounding "
                "words are ordinary prose"
                + (f" (Zotero field: {field_here})" if field_here else ""),
                protected=bool(field_here))
    for region, by_name in journal_regions.items():
        for name, seen in by_name.items():
            if seen[True] and seen[False]:
                paras_i = ", ".join(str(i) for i, _f in seen[True][:4])
                paras_r = ", ".join(str(i) for i, _f in seen[False][:4])
                any_field = any(f for _i, f in seen[True] + seen[False])
                row("FMT-T6e", "medium", f"{region}: {name}",
                    f"'{name}' is formatted italic in {len(seen[True])} place(s) "
                    f"(para {paras_i}) and roman in {len(seen[False])} place(s) "
                    f"(para {paras_r})",
                    "the same journal name must carry ONE treatment throughout a region "
                    "(the reference list italicises journal titles; body text does not)"
                    + (" (partly inside a Zotero field)" if any_field else ""),
                    protected=any_field)

    for i, (p0, p1, p) in enumerate(paras):
        if elem_val(ppr_of(p), "pStyle") != "Bibliography":
            continue
        text = text_of(p)
        ital = [text_of(r[2]) for r in runs(p)
                if text_of(r[2]).strip() and run_is_italic(styles, "Bibliography", r[2])]
        field = in_field(franges, p0)
        if re.search(r"\(\d{4}[a-z]?\)", text) and not ital:
            row("FMT-T6d", "medium", f"p{i}", f"reference with no italic journal title: {text[:60]!r}",
                "an article reference must italicize the journal title"
                + (f" (Zotero field: {field})" if field else ""), protected=bool(field))

    # ---- URLs / emails --------------------------------------------------------
    treatments = defaultdict(set)
    for idx, (_, _, para) in enumerate(paras):
        in_link = "<w:hyperlink" in para
        for r0, r1, run in runs(para):
            rtext = text_of(run)
            if not URL_RE.search(rtext):
                continue
            rpr = rpr_of(run)
            t = ("link" if in_link else "plain",
                 elem_val(rpr, "rStyle") or "-",
                 elem_val(rpr, "color") or "-",
                 # `w:u w:val="none"` is an EXPLICIT "not underlined": it renders
                 # exactly like no `w:u` at all, so counting it as underlined made
                 # a document that mixes both spellings report mixed treatments.
                 "u" if is_on(rpr, "u") else "-",
                 "i" if is_on(rpr, "i") else "-")
            for m in URL_RE.finditer(rtext):
                treatments[m.group(0)].add(t)
    for u, ts in list(treatments.items()):
        if len(ts) > 1:
            row("FMT-T7a", "medium", "document", f"URL {u[:60]!r} rendered {len(ts)} different ways",
                "the same URL is hyperlinked in one place and plain text in another")
    shapes = {(t[0], t[1] != "-", t[2] != "-", t[3] != "-", t[4] != "-")
              for ts in treatments.values() for t in ts}
    if len(shapes) > 1:
        detail = "; ".join(sorted(f"{t}" for t in
                                  {t for ts in treatments.values() for t in ts}))
        row("FMT-T7b", "medium", "document", f"mixed URL/email treatments: {detail}",
            "pick one treatment (plain black, or one link colour/underline) everywhere")

    # ---- text hygiene ---------------------------------------------------------
    full = "\n".join(text_of(p[2]) for p in paras)
    n_straight, n_curly = len(STRAIGHT_RE.findall(full)), len(CURLY_RE.findall(full))
    if n_straight and n_curly:
        row("FMT-T1", "medium", "document",
            f"mixed quotation marks: {n_straight} straight vs {n_curly} curly",
            "use one apostrophe/quote style throughout", )
    words = max(1, len(re.findall(r"\S+", full)))
    em = full.count(EM)
    density = em * 1000.0 / words
    if density > policy["max_em_dashes_per_1000"]:
        ctx = [full[max(0, m.start() - 35):m.start() + 20] for m in list(re.finditer(EM, full))[:3]]
        row("FMT-P1", "medium", "document",
            f"{em} em-dashes = {density:.1f} per 1000 words (cap {policy['max_em_dashes_per_1000']})",
            "over-used em-dashes: rewrite parenthetical dashes as commas/parentheses. e.g. "
            + " | ".join(ctx))
    spaced = len(re.findall(r"\s-\s", full))
    if spaced:
        row("FMT-P2", "low", "document", f"{spaced} spaced hyphen(s) used as a dash",
            "use a comma or a spaced en-dash instead of ' - '")
    # Per-instance text hygiene: FMT-P4 (a space at a line edge) and FMT-G1 (a
    # doubled article/preposition) are mechanical and the fixer applies them;
    # FMT-P3 (doubled spaces, bracket spacing, zero-width marks), FMT-G2
    # (possible lowercase sentence start) and FMT-G3 (missing space after
    # punctuation) are reported for the editing arms.
    is_ref_para = [elem_val(ppr_of(p[2]), "pStyle") == "Bibliography" for p in paras]
    doc_field_results = _field_result_spans(xml)
    field_result_text = [field_result_text_ranges(p[2], doc_field_results, p[0])
                         for p in paras]
    rows.extend(hygiene_rows(paras, is_ref_para, doc, protected=field_result_text))
    rows.extend(capitalization_rows(paras, is_ref_para, doc))
    # Fonts, paragraph formatting and heading levels: the copy-editor classes
    # the editing arms align (FMT-T10a..e; report-only, like the text rules).
    rows.extend(style_convention_rows(paras, styles, doc))
    # Embedded-image geometry: a figure rescaled without its own aspect ratio.
    if sizes is not None:
        geo_rows, _geo_fixes = drawing_geometry_rows(xml, rels or {}, sizes, doc, policy)
        rows.extend(geo_rows)

    # ---- header / title page / tracked changes --------------------------------
    first_sect = first_section_props(xml)
    if first_sect and re.search(r"<w:headerReference", first_sect) \
            and "<w:titlePg" not in first_sect \
            and policy["title_page_header"] == "suppress":
        row("FMT-S3", "low", "document", "the running head is printed on the title page",
            "add w:titlePg to the section properties so page 1 carries no header")
    n_ins = len(re.findall(r"<w:ins(?=[\s/>])", xml))
    n_del = len(re.findall(r"<w:del(?=[\s/>])", xml))
    n_other_rev = len(OTHER_REVISION_MARK_RE.findall(xml))
    if n_ins or n_del or n_other_rev:
        other = f" / {n_other_rev} other revision mark(s)" if n_other_rev else ""
        row("FMT-S4", "high", "document",
            f"tracked changes present: {n_ins} ins / {n_del} del{other}",
            "a final package must not carry revision marks; accept or reject them first")
    n_proof = len(PROOFERR_RE.findall(xml))
    if n_proof:
        row("FMT-S5", "low", "document", f"{n_proof} proofing marker(s) (w:proofErr)",
            "the file was last saved with unaccepted spelling/grammar marks")
    # A literal tab is a run-level `<w:tab/>` or a TAB character in the text.
    # `<w:tab w:val=".." w:pos=".."/>` inside `<w:pPr><w:tabs>` DEFINES a tab
    # stop -- counting it reported "1 literal tab character" on paragraphs that
    # carry no tab at all (the `<w:tab[^>]*/>` regex cannot tell them apart).
    n_tabs, _tab_depth = 0, 0
    for _tok in re.finditer(r"<w:tabs(?=[\s/>])[^>]*>|</w:tabs>|<w:tab(?=[\s/>])[^>]*/>",
                            xml):
        _raw = _tok.group(0)
        if _raw.startswith("</"):
            _tab_depth = max(0, _tab_depth - 1)
        elif _raw.startswith("<w:tabs"):
            _tab_depth += 0 if _raw.endswith("/>") else 1
        elif not _tab_depth:
            n_tabs += 1
    n_tabs += full.count("\t")
    if n_tabs:
        row("FMT-S7", "low", "document", f"{n_tabs} literal tab character(s)",
            "tabs used for layout; prefer paragraph indentation/spacing")

    # ---- text-level style & consistency (FMT-T8a..FMT-T8e) --------------------
    # Citation formats, nested parentheses, redundant repetition and term variants
    # are document-TEXT problems: they are read from the paragraph text so the same
    # rules can also run over the LaTeX/markdown sources (paper_pipeline scans those).
    para_texts = [text_of(p[2]) for p in paras]
    para_is_ref = [elem_val(ppr_of(p[2]), "pStyle") == "Bibliography" for p in paras]
    # The reference-SHAPE rules must survive a venue template that remaps style
    # ids by NAME (apply_word_template rewrites them): a package restyled that
    # way carries its reference list under another style id and every FMT-R
    # rule switched off silently. When no paragraph uses the literal id but the
    # document HAS an explicit bibliography heading, fall back to the numbered
    # entries under it (the same structural primitive FMT-Z2 uses).
    para_is_ref_rows = para_is_ref
    if not any(para_is_ref):
        bib_start = _bibliography_entry_start(para_texts)
        if bib_start > 0:
            para_is_ref_rows = [bool(para_is_ref[i])
                                or (i >= bib_start
                                    and bool(re.match(r"^\s*\d+\s*[\.\)]\s*\S",
                                                      str(para_texts[i] or ""))))
                                for i in range(len(para_is_ref))]
    para_is_head = [bool((elem_val(ppr_of(p[2]), "pStyle") or "").startswith("Heading"))
                    for p in paras]
    # A caption/legend paragraph is not a display-item CALL-OUT: the ordering
    # rule below (FMT-O1) reads the prose, so the caption blocks are excluded the
    # same way the length scan excludes them from the main text.
    para_is_caption = [bool(TABLE_CAPTION_RE.match(t) or FIGURE_CAPTION_RE.match(t)
                            or TABLE_CAPTION_BARE_RE.match(t)
                            or FIGURE_CAPTION_BARE_RE.match(t))
                       for t in para_texts]
    # Table-cell and text-box paragraphs are not narrative paragraphs: the
    # one-sentence rule (FMT-T9k) reads prose, and a cell holding a description
    # is a table's cell however many words it carries.
    _containers = container_spans(xml)
    para_in_container = [any(a <= paras[i][0] < b for a, b in _containers)
                         for i in range(len(paras))]
    para_in_area = [bool(x) for x in display_area_kinds(paras)]
    # Reference-entry shape (FMT-R1..R5), glued front matter (FMT-X2),
    # publisher leftovers (FMT-L1) and the availability statements (FMT-AV1/A2)
    # are RETRIEVABILITY/HYGIENE classes: they hold wherever the text appears
    # (a supplementary file carries its own reference list and availability
    # note, a cover letter can carry another publisher's boilerplate), so they
    # run on every document the package scan opens.
    for r in reference_entry_rows(para_texts, para_is_ref_rows, policy):
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": bool(r.get("protected")),
                     "tier": tier_of(r["rule"])})
    for r in correspondence_glue_rows(para_texts, para_is_ref):
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": False, "tier": tier_of(r["rule"])})
    for r in leftover_phrase_rows(para_texts, policy.get("leftover_phrases"),
                                  para_is_ref):
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": False, "tier": tier_of(r["rule"])})
    for r in availability_rows(para_texts, para_is_ref):
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": False, "tier": tier_of(r["rule"])})
    # The live Zotero field state (FMT-Z1..Z4): a document whose citation
    # markers/bibliography disagree with its own citation order is rewritten by
    # the next Word/Zotero refresh, so it must never be treated as clean. Every
    # row is a field-held fact, hence `protected` (the fixer never edits a
    # field result) and `fix=manual` (only Zotero can re-render it). FMT-Z5
    # (the conflicting style stores) is added by `analyse_package`, which has
    # the other package parts.
    for r in zotero_parity_rows(xml, para_texts):
        if r["rule"] == "FMT-Z5":
            continue
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": r["location"], "evidence": r["evidence"],
                     "detail": r["detail"], "fix": "manual",
                     "protected": True, "tier": tier_of(r["rule"])})
    # Display-item ORDER (FMT-O1) is a MANUSCRIPT-BODY convention: a
    # supplementary file references the main figures and arranges its own
    # (the first call-out test would compare mentions of another document's
    # items), and a cover letter has no numbered display items of its own.
    if display_rules_apply(doc):
        for r in display_order_rows(para_texts, para_is_ref, para_is_caption,
                                    para_is_head,
                                    order_policy=str(policy.get("numbering") or "") == "citation"):
            rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                         "location": r["location"], "evidence": r["evidence"],
                         "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                         "protected": False, "tier": tier_of(r["rule"])})
    for r in text_style_rows(para_texts, para_is_ref, para_is_head,
                             in_container=para_in_container,
                             in_area=para_in_area):
        fix = _fix_kind(r["rule"], policy)
        if r.get("protected") and fix == "mechanical":
            fix = "style-field"
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": "document", "evidence": r["evidence"],
                     "detail": r["detail"], "fix": fix,
                     "protected": bool(r.get("protected")),
                     "tier": r.get("tier") or tier_of(r["rule"])})
    emphasis_rows, _emphasis_fixes = emphasis_consistency(styles, paras)
    for r in emphasis_rows:
        rows.append({"rule": r["rule"], "severity": r["severity"], "document": doc,
                     "location": "document", "evidence": r["evidence"],
                     "detail": r["detail"], "fix": _fix_kind(r["rule"], policy),
                     "protected": False})

    # ---- layout consistency and the front-page budget (FMT-T8f/T8g) ----------
    rows.extend(layout_consistency_rows(xml, paras, title_block_end, doc))
    _fm_row = front_matter_page_break_row(xml, paras, doc)
    if _fm_row:
        rows.append(_fm_row)

    # ---- the venue's DISPLAY rules (FMT-TB1..3 tables, FMT-FG1..3 figures) ---
    # The venue's rules come from `policy["tables"]`/`policy["figures"]` (the
    # profile's own blocks): a kind with no block contributes no rows, and one
    # with a block names the exact item so the review and the producing arms do
    # not have to guess. Neither runs on a supplementary/cover/response document
    # (`display_rules_apply`): the rule is about the manuscript body.
    table_rows, table_inventory = table_conformance_rows(xml, policy, doc)
    figure_rows, figure_inventory = figure_conformance_rows(xml, policy, doc)
    rows.extend(table_rows)
    rows.extend(figure_rows)

    return {"rows": rows, "paras": len(paras), "words": words, "legend_idx": legend_idx,
            "fields": [f[2][:60] for f in franges],
            "style_survey": style_survey(xml, styles),
            "treatments": {k: sorted(v) for k, v in treatments.items()},
            "title_block_end": title_block_end,
            "tables": table_inventory,
            "figures": figure_inventory}


def analyse_package(path: Path, policy: dict) -> dict:
    app_pages = None
    sizes, doc_rels, aux_parts, aux_xml = {}, {}, [], {}
    try:
        with zipfile.ZipFile(path) as pkg:
            styles = parse_styles(pkg)
            xml = pkg.read("word/document.xml").decode("utf-8")
            # Embedded-image geometry: the image parts' own pixels, resolved
            # through each part's relationship file (document + header/footer,
            # where the logo lives).
            sizes = media_pixel_sizes(pkg)
            doc_rels = part_rels(pkg, "word/document.xml")
            for name in sorted(pkg.namelist()):
                if re.match(r"word/(?:header|footer)\d*\.xml$", name):
                    aux_parts.append((name, part_rels(pkg, name)))
                    aux_xml[name] = pkg.read(name).decode("utf-8", "replace")
            if "docProps/app.xml" in pkg.namelist():
                m = re.search(r"<Pages>(\d+)</Pages>",
                              pkg.read("docProps/app.xml").decode("utf-8", "replace"))
                if m:
                    app_pages = int(m.group(1))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeDecodeError, OSError,
            RuntimeError, NotImplementedError) as e:
        # RuntimeError is what `zipfile` raises for an ENCRYPTED entry (and
        # NotImplementedError for an unsupported compression method): a
        # password-protected .docx is unreadable like any other, not a crash.
        row = {"rule": "FMT-X1", "severity": "high", "document": path.name, "location": "-",
               "evidence": f"{type(e).__name__}: {e}", "detail": "unreadable DOCX package",
               "fix": "manual", "protected": False}
        return {"file": str(path), "rows": [row], "by_rule": {"FMT-X1": 1},
                "high": 1, "medium": 0, "low": 0, "documents": {}}
    res = analyse_document(xml, styles, policy, path.name, sizes=sizes, rels=doc_rels)
    # FMT-Z5: the document's Zotero citation STYLE is recorded in more than one
    # place (`word/settings.xml` docVars and, in newer versions, the
    # `docProps/custom.xml` property). They can disagree after an upgrade or a
    # partial re-save, and the next refresh then re-renders every bibliography
    # entry in the other CSL style -- a whole-package formatting change with no
    # other warning. Only this package-level pass can see both stores.
    try:
        with zipfile.ZipFile(path) as pkg:
            zotero_parts = {}
            for cand in ("word/settings.xml", "docProps/custom.xml"):
                if cand in pkg.namelist():
                    zotero_parts[cand] = pkg.read(cand).decode("utf-8", "replace")
            for cand in pkg.namelist():
                if re.match(r"customXml/item\d*\.xml$", cand):
                    zotero_parts[cand] = pkg.read(cand).decode("utf-8", "replace")
            styles_found = zotero_style_ids(zotero_parts)
            if len(set(styles_found.values())) > 1:
                res["rows"].append({
                    "rule": "FMT-Z5", "severity": "medium", "document": path.name,
                    "location": "document preferences",
                    "evidence": "; ".join(f"{p} -> {s}" for p, s in sorted(styles_found.items())),
                    "detail": "the document carries more than one Zotero citation-style "
                              "identifier; a Word/Zotero refresh re-renders every "
                              "bibliography entry in whichever store it honours, so the "
                              "reference FORMAT can change (and no longer match the target "
                              "journal's style) without any other warning",
                    "fix": "manual", "protected": True, "tier": tier_of("FMT-Z5")})
    except (zipfile.BadZipFile, KeyError, OSError):
        pass
    for name, rels in aux_parts:
        aux_rows, _aux_fixes = drawing_geometry_rows(
            aux_xml.get(name, ""), rels, sizes, path.name, policy,
            location_prefix=f"{posixpath.basename(name)} p")
        res["rows"].extend(aux_rows)
    # The cover letter's two-page budget: a rendered PDF beside the .docx is
    # authoritative; without one, the cached Pages value is reported (and the
    # row says which source it came from -- the cache can be stale).
    if re.search(r"cover[\s_-]?letter", path.name, re.I):
        pages, src = None, ""
        pdf = path.with_suffix(".pdf")
        if pdf.is_file() and shutil.which("pdftotext"):
            try:
                txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                                     capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", timeout=60).stdout
                pages, src = (blank_pages_in_text(txt)["pages"],
                              "the rendered PDF beside it")
            except (OSError, subprocess.SubprocessError) as e:
                # A wedged or erroring pdftotext must degrade to the cached value,
                # never abort the whole corpus scan (the sibling helpers catch
                # exactly this tuple). `pages` stays None so the fallback runs.
                print(f"warning: pdftotext failed on {pdf.name} ({type(e).__name__}); "
                      f"using the cached page count", file=sys.stderr)
        if pages is None and app_pages is not None:
            pages, src = app_pages, "the cached docProps/app.xml value -- render to confirm"
        if pages and pages > 2:
            res["rows"].append(cover_letter_page_row(path, pages, src))
    # The cover letter formatted in the MANUSCRIPT template (FMT-CL1): the venue
    # policy carries the manuscript template's own front-matter style ids and
    # header/footer part hashes, so a stamped letter is a deterministic row --
    # never only an agent's visual impression.
    res["rows"].extend(cover_letter_stamp_rows(path, policy))
    counts = Counter(r["rule"] for r in res["rows"])
    return {"file": str(path), "rows": res["rows"], "by_rule": dict(counts),
            "high": sum(1 for r in res["rows"] if r["severity"] == "high"),
            "medium": sum(1 for r in res["rows"] if r["severity"] == "medium"),
            "low": sum(1 for r in res["rows"] if r["severity"] == "low"),
            "documents": {path.name: res}}


def docx_files_under(dirp: Path) -> list:
    """Every .docx under a directory, EITHER extension case.

    `rglob("*.docx")` is case-SENSITIVE on Linux, so a Word-authored
    `REPORT.DOCX` was invisible to the scan and validate paths (the corpus
    itself copies any file, so the document was in the package but never
    checked). The set dedupes on case-insensitive filesystems.
    """
    return sorted(set(dirp.rglob("*.docx")) | set(dirp.rglob("*.DOCX")))


def scan_paths(paths: list, policy: dict) -> dict:
    """Scan the corpus documents under `paths`.

    Difference-tracking auxiliaries (`*.tracking-<token>.<ext>` and their
    `*.logging-<token>.<ext>` fallbacks -- see `_is_aux_name()`) and the stage
    scratch under any `work/` directory are NOT corpus content (the pipeline
    strips both from every judged/pinned corpus), so they are skipped: scanning
    them inflated one real sandbox report to 971 findings and hid the signal.
    There is deliberately no switch back: they are never corpus content.
    """
    docs = []
    for p in paths:
        if not p.exists():
            continue
        files = docx_files_under(p) if p.is_dir() else [p]
        for f in files:
            if f.name.startswith("~$") or _is_aux_name(f.name):
                continue
            if any(part == "work" for part in f.parts[:-1]):
                continue
            if any(part in EVIDENCE_DIRNAMES for part in f.parts[:-1]):
                # The EVIDENCE areas are not submission content: a reviewer's
                # .docx report or a data-source document is never a submission
                # formatting finding.
                continue
            docs.append(analyse_package(f, policy))
    rows = [r for d in docs for r in d["rows"]]
    return {"files": [d["file"] for d in docs], "documents": docs, "rows": rows,
            "by_rule": dict(Counter(r["rule"] for r in rows)),
            "high": sum(1 for r in rows if r["severity"] == "high"),
            "medium": sum(1 for r in rows if r["severity"] == "medium"),
            "low": sum(1 for r in rows if r["severity"] == "low")}


def format_note(info) -> str:
    """One-line summary for the pipeline's setup/decide output."""
    if not info:
        return "not verified (no formatting scan recorded)"
    rows = info.get("rows") or []
    if not rows:
        return "OOXML formatting: clean (no structural/typographic findings)"
    top = ", ".join(f"{k} x{v}" for k, v in sorted((info.get("by_rule") or {}).items())[:5])
    return (f"OOXML formatting: {len(rows)} finding(s) [{info.get('high', 0)} high, "
            f"{info.get('medium', 0)} medium, {info.get('low', 0)} low]: {top}")


# --------------------------------------------------------------------------
# fixing (byte-level splices, applied back-to-front, self-verified)
# --------------------------------------------------------------------------

def apply_edits(xml: str, edits: list) -> str:
    for start, end, new in sorted(edits, key=lambda e: -e[0]):
        xml = xml[:start] + new + xml[end:]
    return xml


# CT_PPrBase's children that PRECEDE `w:spacing`, in schema order: a child spliced
# into a `w:pPr` must land after every one of them or the emitter produces a
# schema-invalid property bag that only a real OOXML validator notices.
PPR_SPACING_AFTER = ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
                     "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs",
                     "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
                     "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
                     "snapToGrid")


def insert_into_ppr(para: str, element: str, after=("pStyle", "keepNext", "keepLines")) -> str:
    ppr = ppr_of(para)
    if ppr is None:
        tag_end = para.find(">") + 1
        head, tail = para[:tag_end], para[tag_end:]
        if head.rstrip().endswith("/>"):
            # A self-closing paragraph (`<w:p w:rsidR="..."/>`, what python-docx
            # emits for an empty paragraph) has no `>` that closes an open tag:
            # inserting after it would orphan the properties OUTSIDE the
            # paragraph and produce schema-invalid XML. Expand the tag first.
            head = head.rstrip()[:-2].rstrip() + ">"
            tail = "</w:p>" + tail
        return head + "<w:pPr>" + element + "</w:pPr>" + tail
    pos = 0
    for tag in after:
        m = re.search(rf"<w:{tag}(?=[\s/>])[^>]*/>|<w:{tag}(?=[\s/>])[^>]*>.*?</w:{tag}>", ppr, re.S)
        if m:
            pos = max(pos, m.end())
    if pos == 0:
        # Anchor at the END of the `w:pPr` open tag, not at a fixed offset: Word
        # writes attributes on it (`<w:pPr w:rsidR="...">`), and splicing a child
        # in after a fixed `len("<w:pPr>")` corrupts the tag. A self-closing
        # `w:pPr` has to be expanded before the child can go inside it.
        m = re.match(r"<w:pPr(?=[\s/>])[^>]*>", ppr)
        if m and m.group(0).rstrip().endswith("/>"):
            head = m.group(0).rstrip()[:-2].rstrip() + ">"
            return para.replace(ppr, head + element + "</w:pPr>", 1)
        pos = m.end() if m else len("<w:pPr>")
    return para.replace(ppr, ppr[:pos] + element + ppr[pos:], 1)


def _unlink_fields(xml: str) -> tuple:
    """Drop fldChar/instrText runs; keep field RESULT runs (Zotero unlinking)."""
    edits, depth, removed = [], 0, 0
    for m in RUN_RE.finditer(xml):
        run = m.group(0)
        fld = FIELD_CHAR_RE.search(run)
        is_instr = bool(INSTR_RE.search(run))
        if fld:
            kind = fld.group(1)
            if kind == "begin":
                depth += 1
            elif kind == "end":
                depth = max(0, depth - 1)
            edits.append((m.start(), m.end(), ""))
            removed += 1
        elif is_instr and depth > 0:
            edits.append((m.start(), m.end(), ""))
            removed += 1
    return apply_edits(xml, edits), removed


def fix_document(xml: str, styles: dict, policy: dict,
                 sizes: dict = None, rels: dict = None) -> tuple:
    """(new_xml, changes, meta) — byte-level edits; rules run in dependency order."""
    changes = []

    # 1. unlink fields first, so run-level fixes stick ---------------------------
    if policy["unlink_zotero_fields"]:
        xml, removed = _unlink_fields(xml)
        if removed:
            changes.append(f"unlinked {removed} field run(s): Zotero citations/bibliography "
                           f"are now plain text (refreshable in the Zotero copy only)")

    # 2. break-only empty paragraph -> pageBreakBefore on the next paragraph ----
    # A paragraph inside a table cell is NEVER the target and never the
    # paragraph the break moves onto: splicing a cell's only (empty) paragraph
    # out leaves `<w:tc></w:tc>`, which Word reports as a corrupt file (the same
    # hazard `_table_paragraph_indices` documents for step 2b), and a
    # `w:pageBreakBefore` written into a cell is not the document-level break
    # the rule means. The next BODY paragraph still receives the break.
    for _ in range(50):
        plist = paragraphs(xml)
        in_table = _table_paragraph_indices(xml, plist)
        target = None
        for idx, (p0, p1, para) in enumerate(plist):
            if idx in in_table:
                continue
            if PAGEBREAK_RE.search(para) and not text_of(para).strip() \
                    and not has_drawing(para) and not has_field(para):
                target = (idx, p0, p1, para)
                break
        if target is None:
            break
        idx, p0, p1, para = target
        edits = [(p0, p1, "")]
        nxt = next((j for j in range(idx + 1, len(plist)) if j not in in_table), None)
        if nxt is not None:
            np0, np1, npara = plist[nxt]
            edits.append((np0, np1, insert_into_ppr(npara, "<w:pageBreakBefore/>")))
            changes.append(f"moved the page break onto the following paragraph (was the empty p{idx})")
        else:
            changes.append(f"removed the trailing break-only paragraph p{idx}")
        xml = apply_edits(xml, edits)

    # 2b. stray empty paragraphs (template-aware) --------------------------------
    # A blank line attached to a heading, or a run beyond the cap, that the
    # venue's own template does NOT prescribe. Deleting an empty paragraph does
    # not change the document text (the fixer's verification compares non-empty
    # paragraph texts), and the prescribed blanks -- the front-matter spacer
    # above the title, the template's own placeholder slots -- are never in the
    # group.
    groups, _prescribed = stray_empty_paragraph_groups(paragraphs(xml), policy, xml)
    drop = sorted({i for indices, _kind in groups for i in indices})
    if drop:
        plist = paragraphs(xml)
        edits = [(plist[i][0], plist[i][1], "") for i in drop if i < len(plist)]
        xml = apply_edits(xml, edits)
        changes.append(f"deleted {len(edits)} stray empty paragraph(s): a blank line "
                       f"next to a heading or beyond the max_empty_paragraph_run cap "
                       f"(template-prescribed blanks kept)")

    # 3. caption/legend blocks ---------------------------------------------------
    # One caption, one paragraph, one spacing, one style (see
    # `caption_block_ranges`): the merge (FMT-T2c) first, so the spacing below
    # runs on the paragraphs the file will actually ship.
    # 3a. the caption's own paragraph style (FMT-T2d) ---------------------------
    plist = paragraphs(xml)
    areas = display_area_kinds(plist)
    blocks = caption_block_ranges(plist, areas, container_spans(xml), xml=xml)
    edits, n = [], 0
    for area_kind in ("figure", "table"):
        members = [x["label"] for x in blocks
                   if x["in_area"] and x["kind"] == area_kind]
        if len(members) < 2:
            continue
        seen = Counter(_para_style(plist[i][2]) for i in members)
        majority, count = seen.most_common(1)[0]
        if len(seen) < 2 or count * 2 <= len(members):
            continue
        for i in members:
            para = plist[i][2]
            if _para_style(para) == majority:
                continue
            pstyle = elem(ppr_of(para), "pStyle")
            if pstyle is None:
                continue
            at = plist[i][0] + para.find(pstyle)
            replacement = f'<w:pStyle w:val="{majority}"/>' if majority else ""
            edits.append((at, at + len(pstyle), replacement))
            n += 1
    if edits:
        xml = apply_edits(xml, edits)
        changes.append(f"aligned {n} caption paragraph(s) with the paragraph style "
                       f"their sibling captions in the same area use")

    # 3b. merge multi-paragraph captions (FMT-T2c) ------------------------------
    plist = paragraphs(xml)
    areas = display_area_kinds(plist)
    blocks = caption_block_ranges(plist, areas, container_spans(xml), xml=xml)
    edits, joins, refused = [], [], 0
    for b in blocks:
        if not (b["in_area"] and b["continuations"]):
            continue
        parts = [plist[i] for i in [b["label"]] + b["continuations"]]
        merged = merged_caption_paragraph(parts, styles)
        if merged is None or not b.get("mergeable"):
            refused += 1
            continue
        edits.append((parts[0][0], parts[-1][1], merged))
        joins.append({"label": b["label"], "continuations": b["continuations"],
                      "caption": text_of(parts[0][2]).strip()[:60]})
    joined_baseline = None
    if edits:
        # The verifier compares the flattened document text; the merge turns two
        # paragraphs into one, so it gets the joined baseline of THIS list.
        joined_baseline = _flatten_with_joins([text_of(p[2]) for p in plist], joins)
        xml = apply_edits(xml, edits)
        changes.append(f"merged {len(edits)} multi-paragraph caption(s) into one "
                       f"paragraph" + (f" ({refused} left for the revision arms: a "
                                       f"field/image inside)" if refused else ""))

    # 3c. the caption's line spacing (FMT-T2a/T2b) ------------------------------
    want_sp = (f'<w:spacing w:before="{policy["caption_space"]}" '
               f'w:after="{policy["caption_space"]}" w:line="{policy["caption_line"]}" '
               f'w:lineRule="auto"/>')
    plist = paragraphs(xml)
    areas = display_area_kinds(plist)
    blocks = caption_block_ranges(plist, areas, container_spans(xml), xml=xml)
    targets = set()
    for b in blocks:
        targets.add(b["label"])
        if b["in_area"]:
            targets.update(b["continuations"])
    for i, (_, _, para) in enumerate(plist):
        if LEGEND_RE.match(text_of(para)):
            targets.add(i)
    edits, n = [], 0
    for i in sorted(targets):
        p0, p1, para = plist[i]
        ppr = ppr_of(para)
        if ppr and elem(ppr, "spacing"):
            old = elem(ppr, "spacing")
            already = (attr(old, "line") == str(policy["caption_line"])
                       and attr(old, "before") == str(policy["caption_space"])
                       and attr(old, "after") == str(policy["caption_space"]))
            if not already:
                at = p0 + para.find(old)
                edits.append((at, at + len(old), want_sp))
                n += 1
        else:
            # `w:spacing` is late in CT_PPrBase's child sequence: anchoring it
            # after pStyle/keepNext/keepLines alone put it BEFORE an existing
            # numPr/pBdr/shd/tabs, which the schema orders ahead of it (the
            # well-formedness fence cannot see the difference, and the optional
            # `docx validate` may not be installed).
            edits.append((p0, p1, insert_into_ppr(para, want_sp, after=PPR_SPACING_AFTER)))
            n += 1
    if edits:
        xml = apply_edits(xml, edits)
        changes.append(f"unified figure-legend spacing on {n} caption paragraph(s) "
                       f"(line={policy['caption_line']}, before/after={policy['caption_space']})")

    # 4. heading keepNext (+ optional size alignment) ---------------------------
    edits, kept, aligned = [], 0, 0
    for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
        ppr = ppr_of(para)
        style = elem_val(ppr, "pStyle")
        if not style or not style.startswith("Heading"):
            continue
        new_para = para
        if policy["heading_keep_with_next"] and not (ppr and "<w:keepNext" in ppr):
            new_para = insert_into_ppr(new_para, "<w:keepNext/><w:keepLines/>")
            kept += 1
        if policy["align_heading_sizes"]:
            want = style_sz(styles, style)
            if want:
                for _, _, run in runs(new_para):
                    rpr = rpr_of(run)
                    if elem_val(rpr, "sz") and elem_val(rpr, "sz") != want:
                        new_run = run.replace(
                            rpr, re.sub(r"<w:sz(?=[\s/>])[^>]*/>", "", rpr), 1)
                        new_para = new_para.replace(run, new_run, 1)
                        aligned += 1
        if new_para != para:
            edits.append((p0, p1, new_para))
    if edits:
        xml = apply_edits(xml, edits)
        if kept:
            changes.append(f"added keepNext/keepLines to {kept} heading(s)")
        if aligned:
            changes.append(f"aligned {aligned} heading run size(s) with their heading style")

    # 5. title-page header ------------------------------------------------------
    if policy["title_page_header"] == "suppress":
        # SECT_READ_RE is the reader that also matches a legal self-closing
        # `<w:sectPr .../>`; the old non-greedy pattern ran past it to the NEXT
        # section's closing tag, so a self-closing first section never got its
        # w:titlePg added.
        s = next(SECT_READ_RE.finditer(xml), None)
        if s is not None and "<w:headerReference" in s.group(0) \
                and "<w:titlePg" not in s.group(0):
            body = s.group(0)
            if body.rstrip().endswith("/>"):
                # A legal self-closing (empty) section has no closing tag to
                # insert before: expand it, or the splice lands OUTSIDE the
                # element and the scanner keeps reporting FMT-S3 while the fixer
                # believes it repaired it.
                head = body.rstrip()[:-2].rstrip() + ">"
                xml = apply_edits(xml, [(s.start(), s.end(), head + "<w:titlePg/></w:sectPr>")])
            else:
                at = s.start() + body.find("</w:sectPr>")
                for tag in ("docGrid", "printerSettings"):
                    t = body.find(f"<w:{tag}")
                    if t != -1:
                        at = min(at, s.start() + t)
                xml = apply_edits(xml, [(at, at, "<w:titlePg/>")])
            changes.append("added w:titlePg: the running head no longer prints on page 1")

    # 6. unintended italics (title block, italic 'et al.' outside fields) -------
    plist = paragraphs(xml)
    franges = field_ranges(xml)
    title_end = None
    for i, (_, _, p) in enumerate(plist):
        if re.match(r"^\s*(abstract|summary)\s*:?\s*$", text_of(p), re.I):
            title_end = i
            break
    edits, n = [], 0
    for idx, (p0, p1, para) in enumerate(plist):
        text = text_of(para)
        style = elem_val(ppr_of(para), "pStyle")
        block = (title_end is not None and idx < title_end
                 and re.search(r"@|Correspondence|ORCID", text, re.I))
        for r0, r1, run in runs(para):
            rtext = text_of(run)
            if not rtext.strip():
                continue
            rpr = rpr_of(run)
            if not (is_on(rpr, "i") or is_on(rpr, "iCs")):
                continue
            in_field_run = bool(in_field(franges, p0 + r0))
            if in_field_run and not policy["unlink_zotero_fields"]:
                continue                      # reported as style-field, never silently "fixed"
            if block or (style == "Bibliography" and re.search(r"\bet\s+al\.", rtext)):
                if rpr:
                    edits.append((p0 + r0, p0 + r1, run.replace(
                        rpr, re.sub(r"<w:i(?:Cs)?(?=[\s/>])[^>]*/>", "", rpr), 1)))
                    n += 1
    if edits:
        xml = apply_edits(xml, edits)
        changes.append(f"removed {n} unintended italic run(s) (title/correspondence block, "
                       f"italic 'et al.')")

    # 6b. journal emphasis: one treatment for a journal title in each region ----
    # This is the fix for the class the direct-rPr check could not see: an italic
    # that comes from a character style (Word's "Emphasis"), a journal emphasised
    # in some sentences and not others, and an emphasis span that runs on over
    # ordinary words ("Nature Methods and other leading journals").
    policy_j = policy["journal_italics"]
    if policy_j in ("refs-only", "everywhere", "off"):
        edits, flipped = [], 0
        franges = field_ranges(xml)
        for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
            style = elem_val(ppr_of(para), "pStyle")
            region = "refs" if style == "Bibliography" else "prose"
            want_italic = (region == "refs" and policy_j in ("refs-only", "everywhere")) \
                or (region == "prose" and policy_j == "everywhere")
            analysis = journal_emphasis_runs(styles, style, para)
            targets = []                      # (r0, r1, run, desired italic)
            if want_italic:
                targets += [(r0, r1, run, True)
                            for r0, r1, run, names in analysis["roman"]
                            if all(_title_only(text_of(run), n) for n in names)]
                targets += [(r0, r1, run, False)
                            for r0, r1, run, _extra, _name in analysis["continuation"]]
            else:
                targets += [(r0, r1, run, False)
                            for r0, r1, run, _names in analysis["italic"]]
                targets += [(r0, r1, run, False)
                            for r0, r1, run, _extra, _name in analysis["continuation"]]
            for r0, r1, run, want in targets:
                if run_is_italic(styles, style, run) == want:
                    continue
                if in_field(franges, p0 + r0):
                    continue                  # field-protected: reported, never silently edited
                new_run = run
                rpr = rpr_of(run)
                new_rpr, changed = _rpr_set_emphasis(rpr, want)
                if rpr is None:
                    open_tag = re.match(r"<w:r(?=[\s/>])[^>]*>", new_run)
                    if open_tag is None:
                        continue
                    new_run = new_run[:open_tag.end()] + new_rpr + new_run[open_tag.end():]
                elif changed:
                    new_run = new_run.replace(rpr, new_rpr, 1)
                if new_run != run:
                    edits.append((p0 + r0, p0 + r1, new_run))
                    flipped += 1
        if edits:
            xml = apply_edits(xml, edits)
            changes.append(f"normalized journal emphasis on {flipped} run(s) "
                           f"(policy: journal_italics={policy_j})")

    # 6c. mixed emphasis for the SAME phrase (label italic once, roman once) ----
    # A parenthetical label is not emphasis: the majority treatment wins and a
    # tie resolves to roman. Non-label phrases are reported by the scanner, never
    # silently restyled (a name may legitimately be italic, e.g. a gene).
    _t9a_rows, t9a_fixes = emphasis_consistency(styles, paragraphs(xml))
    if t9a_fixes:
        plist = paragraphs(xml)
        edits, flipped = [], 0
        for idx, r0, r1, want in t9a_fixes:
            p0 = plist[idx][0]
            run = plist[idx][2][r0:r1]
            if run_is_italic(styles, elem_val(ppr_of(plist[idx][2]), "pStyle"), run) == want:
                continue
            rpr = rpr_of(run)
            new_rpr, changed = _rpr_set_emphasis(rpr, want)
            new_run = run
            if rpr is None:
                open_tag = re.match(r"<w:r(?=[\s/>])[^>]*>", new_run)
                if open_tag is None:
                    continue
                new_run = new_run[:open_tag.end()] + new_rpr + new_run[open_tag.end():]
            elif changed:
                new_run = new_run.replace(rpr, new_rpr, 1)
            if new_run != run:
                edits.append((p0 + r0, p0 + r1, new_run))
                flipped += 1
        if edits:
            xml = apply_edits(xml, edits)
            changes.append(f"unified {flipped} mixed-emphasis label run(s)")

    # 7. URL/email treatment ----------------------------------------------------
    if policy["url_style"] == "plain":
        edits, n = [], 0
        for m in re.finditer(r"<w:hyperlink(?=[\s>]).*?</w:hyperlink>", xml, re.S):
            block = m.group(0)
            inner = block[block.find(">") + 1:block.rfind("</w:hyperlink>")]
            inner = re.sub(r"<w:rStyle[^>]*/>", "", inner)
            inner = re.sub(r"<w:color[^>]*/>", "", inner)
            inner = re.sub(r"<w:u[^>]*/>", "", inner)
            edits.append((m.start(), m.end(), inner))
            n += 1
        if edits:
            xml = apply_edits(xml, edits)
            changes.append(f"unwrapped {n} hyperlink(s) into plain black text (url_style=plain)")
        # plain runs that carry a URL/email must match: no link style, no colour,
        # no underline, no italic (the correspondence block used dark-grey italic)
        edits, n2 = [], 0
        for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
            for r0, r1, run in runs(para):
                if not URL_RE.search(text_of(run)):
                    continue
                rpr = rpr_of(run)
                if not rpr:
                    continue
                stripped = rpr
                for tag in ("rStyle", "color", "u", "i", "iCs"):
                    stripped = re.sub(rf"<w:{tag}(?=[\s/>])[^>]*/>", "", stripped)
                    stripped = re.sub(rf"<w:{tag}(?=[\s/>])[^>]*>.*?</w:{tag}>", "", stripped)
                if stripped != rpr:
                    edits.append((p0 + r0, p0 + r1, run.replace(rpr, stripped, 1)))
                    n2 += 1
        if edits:
            xml = apply_edits(xml, edits)
            changes.append(f"removed leftover link/colour/italic styling from {n2} URL/email run(s)")

    # 8. quotes / proofing markers ---------------------------------------------
    if policy["quote_style"] in ("straight", "curly"):
        # Characters after which a straight quote OPENS. Anything else closes
        # (letters/digits/.,:;!?)]} and the closing curly quotes). The openers
        # are whitespace, brackets, dashes and the opening curly quotes -- a
        # `("quoted")` must not become `(”quoted”)`, and a nested `"'...'"`
        # must open both.
        quote_openers = frozenset(" \t\n\r\f\v([{<\u2012\u2013\u2014\u2015\u2018\u201c-")

        # A quotation can span several `<w:t>` runs -- Word splits them freely
        # (a spell-check boundary, a language change, a deleted revision) -- so
        # the open/close decision needs the last visible character BEFORE this
        # run, not a flag that restarts at run 1. Restarting per run turned the
        # closing quote of a two-run `"hello` + ` there"` into an opening one,
        # and keying `'` off the `"` state flipped a quoted phrase inside-out
        # (`'quoted'` -> '\u2018quoted\u2018'); the text-identity verifier strips
        # quotes before comparing, so that corruption shipped silently.
        def conv(mm, prev_open):
            raw = mm.group(0)
            open_tag = raw[:raw.find(">") + 1]
            close_tag = raw[raw.rfind("<"):]
            text = unesc(raw[raw.find(">") + 1:raw.rfind("<")])
            if policy["quote_style"] == "curly":
                # An apostrophe inside a word is always a right single quote.
                text = re.sub(r"(?<=\w)'(?=\w)", "\u2019", text)
                out = []
                for ch in text:
                    if ch in "\"'":
                        opening = prev_open
                        out.append(("\u201c" if ch == '"' else "\u2018") if opening
                                   else ("\u201d" if ch == '"' else "\u2019"))
                        # An OPENING quote leaves the next quote free to open
                        # again (nested quotes); a closing one does not.
                        prev_open = opening
                    else:
                        out.append(ch)
                        prev_open = ch in quote_openers
                text = "".join(out)
            else:
                text = (text.replace("\u2019", "'").replace("\u2018", "'")
                        .replace("\u201c", '"').replace("\u201d", '"'))
                if text:
                    prev_open = text[-1] in quote_openers
            return open_tag + esc(text) + close_tag, prev_open

        def _paragraph(xml_frag: str) -> str:
            """Normalize one paragraph's text runs with state across runs."""
            prev_open = True
            pieces, pos = [], 0
            for mm in TEXT_RE.finditer(xml_frag):
                gap = xml_frag[pos:mm.start()]
                # A tab or a line break starts a new visual line: the next
                # quote opens. (Both live OUTSIDE `<w:t>`, so the text scan
                # alone would keep the previous character's state.)
                if re.search(r"<w:(?:tab|br|cr)(?=[\s/>])", gap):
                    prev_open = True
                pieces.append(gap)
                new_frag, prev_open = conv(mm, prev_open)
                pieces.append(new_frag)
                pos = mm.end()
            pieces.append(xml_frag[pos:])
            return "".join(pieces)

        pieces, pos = [], 0
        for pm in re.finditer(r"<w:p(?=[\s/>])[\s\S]*?</w:p>", xml):
            pieces.append(_paragraph(xml[pos:pm.end()]))
            pos = pm.end()
        pieces.append(_paragraph(xml[pos:]))
        new = "".join(pieces)
        if new != xml:
            xml = new
            changes.append(f"normalized quotation marks (policy: {policy['quote_style']})")
    if policy["strip_proofing_markers"] and PROOFERR_RE.search(xml):
        n = len(PROOFERR_RE.findall(xml))
        xml = PROOFERR_RE.sub("", xml)
        changes.append(f"removed {n} proofing marker(s) (w:proofErr)")

    # 9. text-level consistency: citations / spelling / hyphenation ------------
    # These DO change document text, so each edit is recorded and the fixer's
    # verification proves that nothing beyond the recorded edits moved (the
    # reference list is never rewritten: its titles are quotations).
    # The edits below are enumerated and offset against THIS XML (after the
    # structural fixes and the quote normalisation), so the verification must
    # reconstruct its expectation from the same stage -- reconstructing from the
    # original XML applied them to the wrong paragraphs once a break-only
    # paragraph had been deleted above (and mismatched quotes whenever
    # quote_style also fired).
    text_stage_xml = xml
    text_edits, cit_n, spell_n, hy_n, hyg_n = [], 0, 0, 0, 0
    want_cit = policy["citation_journal_names"] == "drop"
    want_spell = policy["term_spelling"] == "dominant"
    want_hy = policy["term_hyphenation"] == "dominant"
    # This block ALWAYS runs: text hygiene is mechanical and unconditional, and
    # the three consistency rules below are policy-gated (`keep` pre-judge).
    doc_field_results = _field_result_spans(xml)
    bodies = []
    for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
        if elem_val(ppr_of(para), "pStyle") == "Bibliography":
            continue
        bodies.append((idx, p0, p1, para, text_of(para)))
    blob = "\n".join(b[4] for b in bodies)
    spell_target = (spelling_minority_targets([b[4] for b in bodies])
                    if want_spell else {})
    hy_target = set()
    if want_hy:
        for hy, split in HYPHEN_COMPOUNDS:
            if re.search(rf"\b{re.escape(hy)}(?=\s+[A-Za-z])", blob):
                hy_target.add((hy, split))
    edits = []
    for idx, p0, p1, para, text in bodies:
        spans = []
        # A live field's RESULT text is regenerated by Word, so a text edit
        # inside it would be lost on refresh: the scanner reports those rows as
        # field-protected (`fix=style-field`) and the fixer must not apply them
        # (the unlink policy is the one explicit opt-out).
        protected = ([] if policy["unlink_zotero_fields"]
                     else field_result_text_ranges(para, doc_field_results, p0))
        # Text hygiene: a space at a line edge (FMT-P4) and a doubled
        # article/preposition (FMT-G1) are mechanical. Both are recorded
        # below like every other text edit, so the fixer's verification can
        # prove that nothing beyond them moved.
        hygiene = [(sp["start"], sp["end"], sp["repl"])
                   for sp in hygiene_spans(para) if sp["fix"] == "mechanical"]
        if protected:
            hygiene = [h for h in hygiene if not in_field_result(protected, h[0], h[1])]
        spans.extend(hygiene)
        if want_cit:
            for m in CIT_YEAR_JOURNAL.finditer(text):
                if not in_field_result(protected, m.end(2), m.end(3)):
                    spans.append((m.end(2), m.end(3), ""))
            for m in CIT_JOURNAL_YEAR.finditer(text):
                if not in_field_result(protected, m.end(1), m.end(2)):
                    spans.append((m.end(1), m.end(2), ""))
        if want_spell:
            for minority, majority in spell_target.items():
                for m in re.finditer(rf"\b{re.escape(minority)}\b", text, re.I):
                    rep = (majority.capitalize()
                           if m.group(0)[:1].isupper() else majority)
                    spans.append((m.start(), m.end(), rep))
        if want_hy:
            for hy, split in hy_target:
                for m in re.finditer(rf"\b{re.escape(split)}(?=\s+[A-Za-z])", text):
                    spans.append((m.start(), m.end(), hy))
        if not spans:
            continue
        new_para, applied = rewrite_text_spans(para, spans)
        if new_para == para:
            continue
        edits.append((p0, p1, new_para))
        hygiene_set = set(hygiene)
        for s, e, removed, repl in applied:
            text_edits.append((idx, s, e, repl))
            if (s, e, repl) in hygiene_set:
                hyg_n += 1
            elif repl == "":
                cit_n += 1
            elif repl in {h for h, _s in hy_target}:
                hy_n += 1
            else:
                spell_n += 1
    if edits:
        xml = apply_edits(xml, edits)
        bits = []
        if cit_n:
            bits.append(f"dropped the redundant journal name from {cit_n} citation(s)")
        if spell_n:
            bits.append(f"normalized {spell_n} spelling variant(s)")
        if hy_n:
            bits.append(f"hyphenated {hy_n} attributive compound(s)")
        if hyg_n:
            bits.append(f"cleaned {hyg_n} stray-space/doubled-word hygiene instance(s)")
        if bits:
            changes.append("text consistency: " + "; ".join(bits))

    # 10. embedded-image aspect ratio ------------------------------------------
    # The fix runs LAST (it is computed against the final XML); only the
    # drawing's geometry attributes change, never its text.
    if sizes is not None:
        _geo_rows, geo_fixes = drawing_geometry_rows(xml, rels or {}, sizes,
                                                     "stage", policy)
        if geo_fixes:
            xml = apply_edits(xml, geo_fixes)
            changes.append(f"restored the aspect ratio of {len(geo_fixes)} embedded "
                           f"image extent(s) from the image's own pixels")

    return xml, changes, {"text_edits": text_edits, "text_stage_xml": text_stage_xml,
                          "caption_joins": joins, "text_baseline": joined_baseline}


def fix_package(src: Path, out: Path, policy: dict) -> dict:
    # The scanner reports an unreadable package as a FMT-X1 row and never
    # raises; the fixer must fail the same way (a clean `ok: false` report the
    # CLI turns into exit 1) instead of leaking a zip/KeyError traceback.
    try:
        with zipfile.ZipFile(src) as probe:
            probe_names = set(probe.namelist())
    except (zipfile.BadZipFile, OSError) as e:
        return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                "error": f"unreadable DOCX package: {type(e).__name__}: {e}", "ok": False}
    if "word/document.xml" not in probe_names:
        return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                "error": "unreadable DOCX package: no word/document.xml", "ok": False}
    # The same contract covers the READ phase: an encrypted entry (RuntimeError),
    # an unsupported compression method, a malformed styles.xml (ParseError) or
    # a non-UTF-8 document.xml must come back as `ok: false`, not a traceback.
    sizes, doc_rels, aux = {}, {}, {}
    try:
        with zipfile.ZipFile(src) as pkg:
            parts = {i.filename: pkg.read(i.filename) for i in pkg.infolist()}
            styles = parse_styles(pkg)
            sizes = media_pixel_sizes(pkg)
            doc_rels = part_rels(pkg, "word/document.xml")
            for name in sorted(pkg.namelist()):
                if re.match(r"word/(?:header|footer)\d*\.xml$", name):
                    aux[name] = (pkg.read(name).decode("utf-8", "replace"),
                                 part_rels(pkg, name))
        xml_before = parts["word/document.xml"].decode("utf-8")
    except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeDecodeError, OSError,
            RuntimeError, NotImplementedError) as e:
        return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                "error": f"unreadable DOCX package: {type(e).__name__}: {e}", "ok": False}

    # 0. THE LOCAL ZOTERO REFRESH (and the style-store reconcile), so every
    # later rule -- and the delivered file -- sees the numbering a Word/Zotero
    # refresh would produce. A refusal (an unresolvable field, a bibliography
    # the rebuild cannot own) leaves the document untouched and is reported:
    # the flatten guard below then still refuses to freeze a stale numbering.
    zotero_refresh = {"changed": False, "skip": "disabled by policy"}
    if _policy_flag(policy, "refresh_zotero_fields", True):
        _zr = refresh_zotero_parts(parts, policy)
        zotero_refresh = {k: v for k, v in _zr.items() if k != "parts"}
        if _zr.get("changed"):
            parts = _zr["parts"]
            xml_before = parts["word/document.xml"].decode("utf-8")
    # 0b. REFERENCE-ENTRY REPAIRS: the facts a sibling .bib supplies repair the
    # FMT-R1/R2/R3 shapes in the bibliography text; the Zotero library itself is
    # not written (a later refresh would restore the library's own values, and
    # the rules would report that again -- never a silent drift).
    reference_repair = {"changed": False, "repairs": [], "skipped": []}
    if _policy_flag(policy, "repair_reference_entries", True):
        bibs = sorted(p for p in Path(src).parent.glob("*.bib") if p.is_file())
        if bibs:
            _rr = repair_reference_entries(xml_before, load_bib_facts(bibs))
            reference_repair = {k: v for k, v in _rr.items() if k != "xml"}
            if _rr.get("changed"):
                xml_before = _rr["xml"]
    xml_after, changes, meta = fix_document(xml_before, styles, policy,
                                            sizes=sizes, rels=doc_rels)
    if zotero_refresh.get("changed"):
        changes = list(zotero_refresh.get("changes") or []) + list(changes)
    if reference_repair.get("changed"):
        changes = [f"reference-entry repair: {len(reference_repair['repairs'])} entr(y/ies) "
                   f"repaired from the package's own bibliography ("
                   + ", ".join(sorted({r['rule'] for r in reference_repair['repairs']})) + ")"
                   ] + list(changes)
    try:
        ET.fromstring(xml_after)
        xml_wellformed, xml_detail = True, ""
    except ET.ParseError as e:
        # The byte-level splices must never unbalance the document. `docx
        # validate` is optional, so the parse check is the always-on fence: a
        # malformed output must fail the fixer's own verification, not ship.
        xml_wellformed, xml_detail = False, str(e)
    # LIVE-FIELD FENCE: a mechanical fix must carry every Zotero field over
    # unchanged. The stray-empty-paragraph rule once deleted the no-text
    # paragraph holding a Zotero bibliography's closing fldChar end, leaving
    # the field unterminated; the gate below turns any such change into a
    # failed self-verification, so the caller keeps the original file.
    fields_before = zotero_field_report(xml_before)
    fields_after = zotero_field_report(xml_after)
    field_problems = zotero_field_continuity_problems(fields_before, fields_after)
    field_signature_kept = (zotero_field_signature(fields_before)
                            == zotero_field_signature(fields_after))
    if policy.get("unlink_zotero_fields"):
        # Explicit submission-copy policy: the fields are MEANT to become plain
        # text, so the continuity gate stands down for this one caller. It does
        # NOT stand down for a STALE document: the documented workflow is
        # "refresh, re-run zotero-check, and only then flatten", and flattening
        # a stale document freezes the wrong numbers in the submission copy (no
        # later refresh can repair a field that is no longer a field).
        field_parts = [(name, parts[name].decode("utf-8", "replace"))
                       for name in sorted(parts)
                       if name in ZOTERO_FIELD_PARTS
                       or ZOTERO_FIELD_AUX_PARTS_RE.search(name)]
        stale = [r for r in zotero_parity_rows_for_parts(field_parts)
                 if r.get("rule") in ("FMT-Z1", "FMT-Z2", "FMT-Z4")]
        if stale:
            return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                    "error": (f"refusing to flatten a stale document: "
                              f"{len(stale)} stale-citation fault(s) (FMT-Z1/Z2/Z4) must be "
                              f"repaired in Word/Zotero and `zotero-check` re-run before "
                              f"`unlink_zotero_fields` unlinks the fields -- flattening now "
                              f"freezes the wrong numbering in the submission copy"),
                    "ok": False}
        field_errors = []
    else:
        field_errors = list(field_problems["errors"])
        if not field_signature_kept:
            field_errors.append("a mechanical fix changed which live fields exist (one was "
                                "added, removed or left unterminated); the formatter must carry "
                                "every field over unchanged")
    parts_new = dict(parts)
    parts_new["word/document.xml"] = xml_after.encode("utf-8")
    for name, (axml, arels) in aux.items():
        _arows, afixes = drawing_geometry_rows(axml, arels, sizes, src.name, policy)
        if afixes:
            parts_new[name] = apply_edits(axml, afixes).encode("utf-8")
            changes.append(f"restored the aspect ratio of {len(afixes)} embedded "
                           f"image extent(s) in {posixpath.basename(name)}")
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts_new.items():
                z.writestr(name, data)
    except (OSError, RuntimeError, NotImplementedError) as e:
        return {"source": str(src), "output": str(out), "changes": [], "verified": {},
                "error": f"could not write the fixed DOCX: {type(e).__name__}: {e}",
                "ok": False}

    # Text identity is about the DOCUMENT TEXT, not about paragraph count: a
    # fix may delete an empty paragraph or split a run, which changes the
    # newline count but not a single character of text. A caption the fixer
    # MERGED is the one structural change that joins two paragraph texts into
    # one; `fix_document` records the joined baseline, and the comparison uses
    # it so the merge is verified against the same text it started from.
    text_before = "\n".join(t for t in (text_of(p[2]) for p in paragraphs(xml_before)) if t.strip())
    text_after = "\n".join(t for t in (text_of(p[2]) for p in paragraphs(xml_after)) if t.strip())
    text_baseline = meta.get("text_baseline") or text_before
    quote_free = lambda s: re.sub(r"[\"'\u2018\u2019\u201c\u201d]", "", s)
    # The recorded text edits (citation journals, spelling, hyphenation) are the
    # only allowed text differences; rebuild the expected text by applying them to
    # the STAGE the edits were recorded against (descending offsets, so they stay
    # valid). `text_stage` differs from the input only by the structural fixes --
    # which delete empty paragraphs, never text -- and the quote normalisation.
    stage_xml = meta.get("text_stage_xml") or xml_before
    stage_paras = [text_of(p[2]) for p in paragraphs(stage_xml)]
    text_stage = "\n".join(t for t in stage_paras if t.strip())
    expected_paras = list(stage_paras)
    by_para = {}
    for idx, s, e, repl in meta.get("text_edits") or []:
        by_para.setdefault(idx, []).append((s, e, repl))
    for idx, spans in by_para.items():
        t = expected_paras[idx]
        for s, e, repl in sorted(spans, key=lambda x: -x[0]):
            t = t[:s] + repl + t[e:]
        expected_paras[idx] = t
    text_expected = "\n".join(t for t in expected_paras if t.strip())
    with zipfile.ZipFile(out) as pkg:
        same_parts = all(pkg.read(n) == d for n, d in parts_new.items())
        styles_after = parse_styles(pkg)
    before_rows = analyse_document(xml_before, styles, policy, src.name,
                                   sizes=sizes, rels=doc_rels)["rows"]
    after_rows = analyse_document(xml_after, styles_after, policy, src.name,
                                  sizes=sizes, rels=doc_rels)["rows"]
    mech_before = {r["rule"] for r in before_rows if r["rule"] in MECHANICAL_RULES and r["fix"] == "mechanical"}
    mech_after = {r["rule"] for r in after_rows if r["fix"] == "mechanical"}
    remaining = sorted(mech_before & mech_after)
    schema = validate_package(out)
    verified = {
        "zip_readable": True,
        "parts_intact": same_parts,
        "text_identical": text_baseline == text_after,
        "text_diff_only_quotes": quote_free(text_baseline) == quote_free(text_after),
        "text_stage_diff_only_quotes": quote_free(text_baseline) == quote_free(text_stage),
        "text_diff_only_recorded_edits": text_after == text_expected,
        "text_edits": len(meta.get("text_edits") or []),
        "caption_joins": len(meta.get("caption_joins") or []),
        "mechanical_findings_before": len([r for r in before_rows if r["fix"] == "mechanical"]),
        "mechanical_findings_after": len([r for r in after_rows if r["fix"] == "mechanical"]),
        "remaining_mechanical_rules": remaining,
        "schema_ok": schema[0], "schema_detail": schema[1],
        "xml_wellformed": xml_wellformed, "xml_detail": xml_detail,
        "zotero_fields_before": dict(fields_before["counts"]),
        "zotero_fields_after": dict(fields_after["counts"]),
        "zotero_field_signature_kept": field_signature_kept,
        "zotero_field_problems": field_problems["errors"],
        "zotero_field_warnings": field_problems["warnings"],
        "zotero_field_deleted": field_problems["deleted"],
        "zotero_field_plain_text": field_problems["plain_text"],
    }
    ok = bool(same_parts
              and (verified["text_identical"] or verified["text_diff_only_quotes"]
                   or (verified["text_stage_diff_only_quotes"]
                       and verified["text_diff_only_recorded_edits"]))
              and not remaining
              and xml_wellformed
              and schema[0] is not False
              and not field_errors)
    return {"source": str(src), "output": str(out), "changes": changes, "verified": verified,
            "zotero_refresh": zotero_refresh, "reference_repair": reference_repair, "ok": ok}


def validate_package(path: Path):
    """(ok, detail) with the optional `docx` CLI; (None, reason) when unavailable."""
    exe = shutil.which("docx")
    if not exe:
        return None, "docx CLI not on PATH: schema check skipped"
    try:
        proc = subprocess.run([exe, "validate", str(path)], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"docx validate could not run: {e}"
    lines = [ln for ln in (proc.stdout or proc.stderr).strip().splitlines() if ln.strip()]
    return proc.returncode == 0, (lines[-1] if lines else f"rc={proc.returncode}")


def blank_pages_in_text(text: str) -> dict:
    """Pages whose body is empty once running head/footer/page numbers are ignored."""
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    stripped = [[ln.strip() for ln in p.splitlines() if ln.strip()] for p in pages]
    n = len(stripped)
    freq = Counter(ln for page in stripped for ln in page)
    furniture = {ln for ln, c in freq.items() if n and c >= max(2, int(0.6 * n))}
    blank = [i for i, page in enumerate(stripped, 1)
             if not [ln for ln in page if ln not in furniture and not re.fullmatch(r"\d+", ln)]]
    return {"pages": n, "blank_pages": blank, "furniture": sorted(furniture)}


# ---- deliverable validation (DOCX XML + LaTeX) ----------------------------
# What the editing stages must run after every edit: a DOCX whose parts do not
# parse (or that fails the `docx` schema check) and a .tex that does not compile
# are broken deliverables, no matter how good the prose is.

LATEX_ENGINES = (("latexmk", ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error"]),
                 ("xelatex", ["xelatex", "-interaction=nonstopmode", "-halt-on-error"]),
                 ("pdflatex", ["pdflatex", "-interaction=nonstopmode", "-halt-on-error"]),
                 ("lualatex", ["lualatex", "-interaction=nonstopmode", "-halt-on-error"]))


def latex_engine() -> tuple | None:
    """(name, argv) of the first available TeX engine, or None."""
    for name, argv in LATEX_ENGINES:
        exe = shutil.which(argv[0])
        if exe:
            return name, [exe] + argv[1:]
    return None


def validate_docx_parts(path: Path) -> dict:
    """Validate one DOCX: zip readable, every XML/rels part parses, optional schema."""
    errs = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                errs.append("word/document.xml is missing from the package")
            for name in names:
                if not (name.endswith(".xml") or name.endswith(".rels")):
                    continue
                try:
                    ET.fromstring(z.read(name))
                except ET.ParseError as e:
                    errs.append(f"{name}: malformed XML ({e})")
                except (OSError, RuntimeError, NotImplementedError) as e:  # noqa: PERF203
                    errs.append(f"{name}: unreadable ({e})")
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as e:
        errs.append(f"not a readable .docx zip ({type(e).__name__}: {e})")
    schema_ok, schema_detail = validate_package(path)
    if schema_ok is False:
        errs.append(f"schema check failed: {schema_detail}")
    return {"file": str(path), "kind": "docx", "ok": not errs, "errors": errs,
            "schema_ok": schema_ok, "detail": schema_detail if schema_ok is None else "valid"}


# --------------------------------------------------------------------------
# Official venue templates: restyle a package into the journal's own DOCX
# --------------------------------------------------------------------------

_STYLE_REF_RE = re.compile(r'<w:(pStyle|rStyle)\b[^>]*?w:val="([^"]+)"')
# Direct properties the template's styles are supposed to own. Semantic run
# formatting (b/i/u/color/vertAlign/...) is deliberately NOT stripped.
_DIRECT_FORMAT_PATTERNS = (
    r"<w:spacing(?=[\s/>])[^>]*/>",
    r"<w:ind(?=[\s/>])[^>]*/>",
    r"<w:jc(?=[\s/>])[^>]*/>",
    r"<w:rFonts(?=[\s/>])[^>]*/>",
    r"<w:sz(?=[\s/>])[^>]*/>",
    r"<w:szCs(?=[\s/>])[^>]*/>",
)
_SECT_RE = re.compile(r"<w:sectPr(?=[\s>])[\s\S]*?</w:sectPr>")
_RELS_RE = re.compile(r'<Relationship Id="([^"]+)"[^>]*Type="[^"]*/([a-zA-Z]+)"'
                      r'[^>]*Target="([^"]+)"')
# Another publisher's block headings ("Lead contact", "Key resources", ...) are
# VENUE DATA, never pipeline knowledge: the calling venue profile passes its own
# `foreign_container_headings` list and this default is empty, so the formatter
# carries no journal's vocabulary and stays venue-agnostic.
_FOREIGN_CONTAINERS_DEFAULT = ()
_SIMPLE_PAGE_FOOTER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:p><w:pPr><w:jc w:val="right"/></w:pPr>'
    '<w:fldSimple w:instr=" PAGE \\* Arabic "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
    '</w:p></w:ftr>')


def _set_para_style(para: str, style: str) -> str:
    """Force `w:pStyle` on a paragraph fragment (insert or replace)."""
    m = re.search(r"<w:pPr(?=[\s/>])[^>]*/>|<w:pPr(?=[\s>])[^>]*>[\s\S]*?</w:pPr>", para)
    if m:
        block = m.group(0)
        if block.rstrip().endswith("/>"):
            new = (block[:block.rfind("/>")].rstrip() + ">"
                   + f'<w:pStyle w:val="{style}"/>' + "</w:pPr>")
        elif "<w:pStyle" in block:
            new = re.sub(r"<w:pStyle(?=[\s>])[^>]*/>", f'<w:pStyle w:val="{style}"/>',
                         block, count=1)
        else:
            om = re.match(r"<w:pPr(?=[\s>])[^>]*>", block)
            new = block[:om.end()] + f'<w:pStyle w:val="{style}"/>' + block[om.end():]
        return para.replace(block, new, 1)
    om = re.match(r"<w:p(?=[\s>])[^>]*>", para)
    return para[:om.end()] + f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' + para[om.end():]


def _style_index(styles_xml: str) -> tuple:
    """({styleId: (type, normalized-name)}, {(type, name): styleId})."""
    try:
        root = ET.fromstring(styles_xml)
    except ET.ParseError:
        return {}, {}
    by_id, by_name = {}, {}
    for st in root.iter(W + "style"):
        sid = str(st.get(W + "styleId") or "")
        if not sid:
            continue
        typ = str(st.get(W + "type") or "paragraph")
        name_el = st.find(W + "name")
        name = (str(name_el.get(W + "val")) if name_el is not None
                and name_el.get(W + "val") else sid)
        key = re.sub(r"[^a-z0-9]+", "", name.lower())
        by_id[sid] = (typ, key)
        by_name.setdefault((typ, key), sid)
    return by_id, by_name


def _strip_direct_format(para: str) -> tuple:
    """(fragment, removed_count): drop direct props that defeat a template style."""
    removed = 0
    for pat in _DIRECT_FORMAT_PATTERNS:
        para, n = re.subn(pat, "", para)
        removed += n
    return para, removed


def _remap_style_refs(xml: str, mapping: dict) -> tuple:
    """(xml, count): rewrite pStyle/rStyle ids through the manuscript->template map."""
    count = [0]

    def sub(m):
        new = mapping.get(m.group(2))
        if not new or new == m.group(2):
            return m.group(0)
        count[0] += 1
        return m.group(0).replace(f'w:val="{m.group(2)}"', f'w:val="{new}"')

    return _STYLE_REF_RE.sub(sub, xml), count[0]


def _adopt_page_geometry(doc_xml: str, template_doc_xml: str) -> tuple:
    """(xml, applied): give EVERY manuscript section the template's geometry.

    The template's own (single) sectPr is the SOURCE. Page 1 is governed by the
    FIRST `w:sectPr` in document order (see `first_section_props`) and a
    title-page break splits the body into sections, so writing only the LAST one
    left page 1 -- and every middle section -- in the author's geometry: the
    delivered package was not the journal's layout, while the conformance
    report, which read the same last section, showed no gap.
    """
    t_sects = list(_SECT_RE.finditer(template_doc_xml or ""))
    # The MANUSCRIPT side reads the same way `first_section_props` reads it: a
    # legal self-closing `<w:sectPr .../>` is an empty section and must not be
    # skipped, or page 1 silently keeps the author's geometry while the report
    # (which reads the first section correctly) shows the template's.
    m_sects = list(SECT_READ_RE.finditer(doc_xml))
    if not t_sects or not m_sects:
        return doc_xml, False
    # CT_SectPr's child order; a replacement must keep the sequence valid even
    # when the manuscript carries elements between the geometry children
    # (lnNumType/pgNumType/...), which re-serializing from scratch would move.
    order = ("headerReference", "footerReference", "footnotePr", "endnotePr", "type",
             "pgSz", "pgMar", "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols",
             "formProt", "vAlign", "noEndnote", "titlePg", "textDirection", "bidi",
             "rtlGutter", "docGrid", "printerSettings", "sectPrChange")
    tpl_sect = t_sects[-1].group(0)
    geo = {tag: elem(tpl_sect, tag) for tag in ("pgSz", "pgMar", "cols", "docGrid")}
    geo = {k: v for k, v in geo.items() if v}
    if not geo:
        return doc_xml, False

    def adopt(body: str) -> str:
        if body.rstrip().endswith("/>"):
            # Expand the empty section first: the geometry children belong
            # INSIDE it, and a splice before the tag's `/>` would orphan them.
            body = body[:body.rfind("/>")].rstrip() + ">" + "</w:sectPr>"
        for tag in ("pgSz", "pgMar", "cols", "docGrid"):
            el = elem(body, tag)
            new_el = geo.get(tag)
            if el and new_el:
                body = body.replace(el, new_el, 1)
            elif new_el:
                pos = body.rfind("</w:sectPr>")
                idx = order.index(tag)
                for m in re.finditer(r"<w:([A-Za-z]+)(?=[\s/>])", body):
                    name = m.group(1)
                    if name in order and order.index(name) > idx:
                        pos = min(pos, m.start())
                        break
                body = body[:pos] + new_el + body[pos:]
        return body

    for m in reversed(m_sects):                     # backwards: offsets stay valid
        doc_xml = doc_xml[:m.start()] + adopt(m.group(0)) + doc_xml[m.end():]
    return doc_xml, True


def _template_front_parts(tpkg: zipfile.ZipFile, parts: dict, tnames: set) -> dict:
    """Copy the template's whole header/footer role map into the package.

    Every role the template defines -- first, default (odd) and EVEN -- is
    carried, together with the `w:evenAndOddHeaders` parity setting the
    template relies on: a template whose furniture alternates by page parity
    (Frontiers: the page number on odd pages and its typeset-provisional note on
    even ones; a running head defined for even pages only) loses half of its
    furniture when only first+default are copied.

    The FIRST-page footer is always a plain synthetic PAGE field, and an EVEN
    footer that is not plain pagination -- a VML/DrawingML text box, or a part
    carrying the template's own typesetting prose ("This is a provisional
    file...") -- is replaced by the same plain footer. Word refuses a template
    text-box footer re-roled to first/even ("the file appears to be corrupted"
    on open), and the pipeline takes STRUCTURE from a template, never its
    prose. Every substitution is reported in `footer_replaced`.
    """
    try:
        tdoc = tpkg.read("word/document.xml").decode("utf-8", "replace")
        trels = (tpkg.read("word/_rels/document.xml.rels").decode("utf-8", "replace")
                 if "word/_rels/document.xml.rels" in tnames else "")
        tset = (tpkg.read("word/settings.xml").decode("utf-8", "replace")
                if "word/settings.xml" in tnames else "")
    except (KeyError, OSError, RuntimeError, NotImplementedError):
        return {}
    rel_map = {m.group(1): (m.group(2).lower(), m.group(3))
               for m in _RELS_RE.finditer(trels)}
    refs = {"header": {}, "footer": {}}
    sect = _SECT_RE.findall(tdoc)
    ref_re = r'<w:(header|footer)Reference w:type="(\w+)" r:id="([^"]+)"'

    def harvest(xml: str, roles: tuple) -> None:
        for m in re.finditer(ref_re, xml):
            if m.group(2) in roles and m.group(2) not in refs[m.group(1)]:
                refs[m.group(1)][m.group(2)] = m.group(3)

    # Page 1 is governed by the FIRST section (`_apply_front_refs` writes the
    # "first" role there), while the running head/footer belong to the
    # template's body section. Reading every role from sect[-1] copied the
    # running head into the first-page role -- the logo header of a template
    # that splits its title page off was left behind while the change log
    # still claimed it had been copied.
    for role, order in (("first", sect),
                        ("default", list(reversed(sect))),
                        ("even", list(reversed(sect)))):
        for one in order:
            harvest(one, (role,))
    if not (refs["header"] or refs["footer"]):
        return {}
    copied, issued = [], {}

    def copy_part(src_name: str, dest_name: str) -> bool:
        full = f"word/{src_name}"
        if full not in tnames:
            return False
        parts[f"word/{dest_name}"] = tpkg.read(full)
        copied.append(dest_name)
        rels_name = f"word/_rels/{src_name}.rels"
        if rels_name in tnames:
            rxml = tpkg.read(rels_name).decode("utf-8", "replace")
            for rm in list(_RELS_RE.finditer(rxml)):
                if rm.group(2).lower() != "image":
                    continue
                # The relationship target is RELATIVE TO THE HEADER/FOOTER PART
                # (`word/`), so the rewritten target must keep the media
                # directory: `media/logo.png` -> `media/venue_logo.png`, never a
                # bare `venue_logo.png` (which resolves to word/venue_logo.png,
                # a missing part -- the logo then renders as an empty frame).
                media = rm.group(3)
                src_media = posixpath.normpath(posixpath.join("word", media))
                if not src_media.startswith("word/") or ".." in Path(src_media).parts:
                    continue
                dest_media = posixpath.join(posixpath.dirname(src_media),
                                            f"venue_{posixpath.basename(media)}")
                if dest_media not in parts and src_media in tnames:
                    parts[dest_media] = tpkg.read(src_media)
                rel_target = posixpath.relpath(dest_media, "word")
                rxml = rxml.replace(f'Target="{media}"', f'Target="{rel_target}"')
            parts[f"word/_rels/{dest_name}.rels"] = rxml.encode("utf-8")
        hdr = tpkg.read(full).decode("utf-8", "replace")
        issued[dest_name] = bool(re.search(r"<w:drawing|<w:pict|<v:imagedata|<a:blip", hdr))
        return True

    def target_of(kind: str, role: str) -> str:
        rid = refs[kind].get(role)
        k, target = rel_map.get(rid, ("", "")) if rid else ("", "")
        return target if k == kind and target and f"word/{target}" in tnames else ""

    by_target = {}

    def carry(kind: str, role: str, dest: str) -> str:
        """Copy the template part for one role (deduped by source part)."""
        target = target_of(kind, role)
        if not target:
            return ""
        if target in by_target:
            return by_target[target]
        if copy_part(target, dest):
            by_target[target] = dest
            return dest
        return ""

    def synthesize(dest: str) -> str:
        parts[f"word/{dest}"] = _SIMPLE_PAGE_FOOTER.encode("utf-8")
        copied.append(dest)
        issued[dest] = False
        return dest

    def footer_part_is_plain_pagination(role: str) -> bool:
        """Pagination only: a PAGE field, no text box and no visible prose.

        Word accepts the template's AlternateContent (VML/DrawingML text-box)
        footer as the DEFAULT footer, but refuses the very same part in the
        first/even roles ("the file appears to be corrupted" on open), and a
        role-tagged part is what the schema asks for -- so only plain
        pagination parts are re-roled.
        """
        target = target_of("footer", role)
        if not target:
            return False
        xml = tpkg.read(f"word/{target}").decode("utf-8", "replace")
        if not re.search(r'<w:instrText[^>]*>[^<]*\bPAGE\b'
                         r'|<w:fldSimple[^>]*w:instr="[^"]*\bPAGE\b', xml, re.I):
            return False
        if re.search(r"<w:txbxContent|<wps:wsp|<w:pict\b", xml):
            return False
        visible = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
        return not re.search(r"[A-Za-z]", visible)

    out = {"footer_replaced": []}
    for role, dest in (("first", "header_venue_first.xml"),
                       ("default", "header_venue_default.xml"),
                       ("even", "header_venue_even.xml")):
        # A template with a single header uses it on every page, first included.
        part = carry("header", role, dest) if role != "first" \
            else (carry("header", "first", dest) or carry("header", "default", dest))
        if part:
            out[f"header_{role}"] = part
    for role, dest in (("first", "footer_venue_first.xml"),
                       ("default", "footer_venue_default.xml"),
                       ("even", "footer_venue_even.xml")):
        target = target_of("footer", role)
        # first: always the plain synthetic page number (a re-roled template
        # text box corrupts the file); even: only plain pagination (the
        # template's typeset-provisional prose must not reach the manuscript);
        # default: the template's own part, as before.
        if not target or role == "first":
            keep = False
        elif role == "even":
            keep = footer_part_is_plain_pagination(role)
        else:
            keep = True
        part = carry("footer", role, dest) if keep else ""
        if not keep and target:
            out["footer_replaced"].append(role)
        if not part and (role == "first" or target):
            # pagination the manuscript must have; first page included
            part = synthesize(dest)
        if part:
            out[f"footer_{role}"] = part
    out["even_odd"] = ("evenAndOddHeaders" in tset
                       or any(k.startswith(("header_even", "footer_even")) for k in out))
    out["logo"] = bool(issued.get(out.get("header_first", ""), False))
    out["copied"] = copied
    # content-type overrides for the new parts + media defaults
    ct = parts.get("[Content_Types].xml", b"").decode("utf-8", "replace")
    for name in copied:
        kind = "header" if name.startswith("header") else "footer"
        if f'PartName="/word/{name}"' not in ct:
            ct = ct.replace("</Types>",
                            f'<Override PartName="/word/{name}" ContentType="application/vnd.'
                            f'openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>'
                            f'</Types>')
    for media in [n for n in parts if n.startswith("word/media/venue_")]:
        ext = Path(media).suffix.lstrip(".").lower()
        ctype = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png",
                 "gif": "image/gif", "emf": "image/x-emf", "wmf": "image/x-wmf"}.get(ext)
        if ctype and f'Extension="{ext}"' not in ct:
            ct = ct.replace("</Types>", f'<Default Extension="{ext}" ContentType="{ctype}"/>'
                                       f'</Types>')
    parts["[Content_Types].xml"] = ct.encode("utf-8")
    # document relationships (fresh ids)
    rels = parts.get("word/_rels/document.xml.rels", b"").decode("utf-8", "replace")
    used = set(re.findall(r'Id="([^"]+)"', rels))
    n = 2001
    for key, dest in (("header_default", out.get("header_default")),
                      ("header_first", out.get("header_first")),
                      ("header_even", out.get("header_even")),
                      ("footer_default", out.get("footer_default")),
                      ("footer_first", out.get("footer_first")),
                      ("footer_even", out.get("footer_even"))):
        if not dest:
            continue
        while f"rId{n}" in used:
            n += 1
        rid = f"rId{n}"
        used.add(rid)
        n += 1
        kind = "header" if key.startswith("header") else "footer"
        rels = rels.replace("</Relationships>",
                            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
                            f'officeDocument/2006/relationships/{kind}" Target="{dest}"/>'
                            f'</Relationships>')
        out[key + "_rid"] = rid
    parts["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    return out


def template_style_roles(template: Path) -> dict:
    """The style ids a TEMPLATE uses for its front matter and heading levels.

    Venue-agnostic: the roles are read from the template's own styles.xml
    (`title`, `author list`/`authors`, the styles whose aliases cover both
    keywords and abstract, `heading 1..5`, `caption`), and the deepest heading
    level the template's own document actually uses at least twice becomes the
    level cap -- a template that never nests sub-sub-sections does not get them
    imposed on the manuscript.
    """
    try:
        with zipfile.ZipFile(template) as tpkg:
            styles = tpkg.read("word/styles.xml").decode("utf-8", "replace")
            doc = tpkg.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return {}
    roles = {"headings": {}}
    try:
        root = ET.fromstring(styles)
    except ET.ParseError:
        return {}
    for st in root.iter(W + "style"):
        sid = str(st.get(W + "styleId") or "")
        if not sid:
            continue
        name_el = st.find(W + "name")
        name = str(name_el.get(W + "val")) if name_el is not None else sid
        keys = {re.sub(r"[^a-z0-9]+", "", name.lower())}
        aliases_el = st.find(W + "aliases")
        if aliases_el is not None and aliases_el.get(W + "val"):
            keys |= {re.sub(r"[^a-z0-9]+", "", a.lower())
                     for a in str(aliases_el.get(W + "val")).split(",")}
        if "title" in keys and "title" not in roles:
            roles["title"] = sid
        if keys & {"authorlist", "authors", "author"} and "author" not in roles:
            roles["author"] = sid
        if "keywords" in keys and "abstract" in keys and "author" not in roles:
            roles["author"] = sid          # the front-matter style by its aliases
        for level in range(1, 6):
            if f"heading{level}" in keys:
                roles["headings"].setdefault(level, sid)
        if "caption" in keys and "caption" not in roles:
            roles["caption"] = sid
    used = {}
    for m in re.finditer(r'<w:pStyle w:val="([^"]+)"', doc):
        used[m.group(1)] = used.get(m.group(1), 0) + 1
    depth = 0
    for level, sid in roles["headings"].items():
        if used.get(sid, 0) >= 2:
            depth = max(depth, level)
    roles["max_heading_level"] = depth or 2
    return roles


_HEADING_MAX_CHARS = 90
_HEADING_MAX_WORDS = 12
_HEADING_SKIP_PREFIXES = ("figure ", "fig. ", "fig ", "table ", "supplementary figure",
                          "supplementary table", "extended data ", "box ")


def _body_run_size(doc_xml: str):
    """The document's dominant run size (its body-text size), or None.

    Weighted by TEXT, over the long paragraphs that actually carry the prose: a
    short document's figure legends, tables and captions can outnumber its body
    runs, and their small sizes must not become the body baseline (that would
    turn every bold line above them into a "heading").
    """
    weights = Counter()
    for _p0, _p1, frag in paragraphs(doc_xml):
        if len(text_of(frag).split()) < 25:
            continue
        for run in re.findall(r"<w:r\b[\s\S]*?</w:r>", frag):
            t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run))
            for s in re.findall(r'<w:sz w:val="(\d+)"', run):
                weights[int(s)] += len(t)
    if weights:
        return weights.most_common(1)[0][0]
    sizes = Counter(re.findall(r'<w:sz w:val="(\d+)"', doc_xml))
    if not sizes:
        return None
    return int(sizes.most_common(1)[0][0])


def heading_like_paragraphs(doc_xml: str, containers=()) -> list:
    """[(paragraph index, text, size)] of DIRECTLY-formatted section headings.

    A manuscript written in Word often carries its section headings as direct
    formatting -- a short bold line one or two points larger than the body text,
    with NO paragraph style at all. The template's Heading 1..N styles cannot
    apply to such a paragraph until it is tagged, and the normalizer's own
    direct-format strip (which exists so the template's typography shows) would
    otherwise flatten the heading into body text. Pure detection: the retag pass
    and the conformance report read the same rows.

    Deliberately conservative: only unstyled/Normal paragraphs whose every
    non-empty run is bold, whose size is at least 1 pt above the document's
    dominant run size, whose text is a short single line without a terminal
    period/comma/semicolon, and that are not captions, lists, table cells, front
    matter or a known foreign-publisher container heading.
    """
    body = _body_run_size(doc_xml)
    if body is None:
        return []
    paras = list(paragraphs(doc_xml))
    # `_table_spans` balances nested tables; the lazy regex this used to run
    # stopped at the inner `</w:tbl>`, so a paragraph of the OUTER table after a
    # nested one was read as body text and `_retag_headings` could stamp a
    # Heading style onto a short bold line inside a table cell.
    tables = _table_spans(doc_xml)
    entries = [i for i, p in enumerate(paras) if text_of(p[2]).strip()]
    skip = set(entries[:1])                       # the article title
    for i in entries[1:4]:                        # the author line
        t = text_of(paras[i][2]).strip()
        if len(t) < 400 and "@" not in t and ("," in t or " and " in t):
            skip.add(i)
            break
    for i in entries:                             # abstract / keywords front matter
        low = text_of(paras[i][2]).strip().lower()
        if low == "abstract" or low.startswith("keywords"):
            skip.add(i)
    out = []
    for i, (p0, p1, frag) in enumerate(paras):
        if i in skip or any(a <= p0 < b for a, b in tables):
            continue
        text = text_of(frag).strip()
        if not text or len(text) > _HEADING_MAX_CHARS \
                or len(text.split()) > _HEADING_MAX_WORDS:
            continue
        if not text[0].isalpha() or text[-1] in ".,;":
            continue
        low = text.lower()
        if low.startswith(_HEADING_SKIP_PREFIXES) \
                or low in {c.lower() for c in (containers or _FOREIGN_CONTAINERS_DEFAULT)}:
            continue
        pstyle = elem_val(ppr_of(frag), "pStyle")
        if pstyle and pstyle != "Normal":
            continue
        if "<w:numPr" in frag:
            continue
        sizes, all_bold, has_text = [], True, False
        for run in re.findall(r"<w:r\b[\s\S]*?</w:r>", frag):
            if not "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run)).strip():
                continue
            has_text = True
            if not re.search(r"<w:b/>|<w:b w:val=\"(?:1|true|on)\"", run):
                all_bold = False
                break
            sizes += [int(s) for s in re.findall(r'<w:sz w:val="(\d+)"', run)]
        if not (has_text and all_bold and sizes) or max(sizes) < body + 2:
            continue
        out.append((i, text, max(sizes)))
    return out


def _retag_headings(doc_xml: str, roles: dict, containers=()) -> tuple:
    """(xml, retagged): tag directly-formatted headings with the template's styles.

    The paragraph STYLE IS the only thing changed -- the text stays byte-identical,
    and the normalizer's direct-format strip that follows removes the local
    font/size/spacing so the template's Heading 1..N own the typography (and its
    automatic numbering comes along). The largest heading size becomes level 1,
    the next level 2, and so on, capped at the depth the template's own document
    uses. Every retag is reported so a review session can correct a mis-tag.
    """
    headings = dict(roles.get("headings") or {})
    if not headings:
        return doc_xml, []
    cands = heading_like_paragraphs(doc_xml, containers)
    if not cands:
        return doc_xml, []
    depth = max(1, int(roles.get("max_heading_level") or 2))
    level_of = {size: min(i + 1, depth)
                for i, size in enumerate(sorted({s for _i, _t, s in cands}, reverse=True))}
    paras = list(paragraphs(doc_xml))
    edits, done = [], []
    for i, text, size in cands:
        style = headings.get(level_of[size]) or headings.get(depth)
        if not style:
            continue
        p0, p1, frag = paras[i]
        edits.append((p0, p1, _set_para_style(frag, style)))
        done.append({"text": text[:80], "level": level_of[size], "style": style})
    return (apply_edits(doc_xml, edits) if edits else doc_xml), done


_CORRESP_RE = re.compile(r"^\s*\*\s*Correspondence\s*:", re.I)


def _ppr_extra(ppr_xml: str) -> str:
    """A template paragraph's NON-style pPr children (spacing/ind/jc/rPr)."""
    if not ppr_xml:
        return ""
    keep = []
    for tag in ("spacing", "ind", "jc", "keepNext", "keepLines", "rPr"):
        keep += re.findall(rf"<w:{tag}(?=[\s/>])[^>]*/>|<w:{tag}(?=[\s>])[^>]*>[\s\S]*?</w:{tag}>",
                           ppr_xml)
    return "".join(keep)


def _template_front_layout(tpl_doc: str) -> dict:
    """The TEMPLATE's own paragraph properties for the first-page block.

    The title/author/keywords/abstract roles come from style ids, but a Word
    template formats its affiliation lines and its correspondence block with
    DIRECT `w:spacing` (before=240/after=0) and a Times New Roman cs font. The
    normalizer strips direct paragraph properties, so unless those values are
    copied from the template the block ends up under Normal's spacing -- which is
    exactly the "line spacing between the affiliation/correspondence lines is
    wrong" deviation. Returns {role: pPr-snippet} for affiliation (first and
    rest), correspondence, keywords, abstract_head and abstract_body.
    """
    out = {}
    paras = list(paragraphs(tpl_doc))
    affil = 0
    abstract_seen = False
    for _p0, _p1, frag in paras:
        text = text_of(frag).strip()
        ppr = ppr_of(frag)
        extra = _ppr_extra(ppr)
        if not text:
            continue
        style = elem_val(ppr, "pStyle")
        if _CORRESP_RE.match(text):
            out.setdefault("correspondence", extra)
        elif style == "AuthorList" and text.lower().startswith("keywords"):
            out.setdefault("keywords", extra)
        elif style == "AuthorList" and text.lower() == "abstract":
            out.setdefault("abstract_head", extra)
            abstract_seen = True
        elif abstract_seen and "abstract_body" not in out and style not in ("Heading1", "Heading2"):
            out["abstract_body"] = extra
        elif re.match(r"^\d+[A-Z]", text) and "correspondence" not in text.lower():
            affil += 1
            out.setdefault("affiliation_first" if affil == 1 else "affiliation_rest", extra)
    return out


def _bold_label_runs(para_xml: str) -> str:
    """Make the leading `* Correspondence:` label BOLD (template's own look).

    The label is often one run that also carries the name/email; the run is split
    at the colon so only the label is bold -- the concatenated w:t text stays
    byte-identical.
    """
    RPR_RE = re.compile(r"<w:rPr(?=[\s/>])(?:[^>]*/>|[^>]*>[\s\S]*?</w:rPr>)")

    m = _CORRESP_RE.match(text_of(para_xml).strip())
    if not m:
        return para_xml
    left = len(m.group(0))
    out = para_xml
    for rm in list(re.finditer(r"<w:r\b[\s\S]*?</w:r>", out)):
        run = rm.group(0)
        tm = re.search(r"(<w:t[^>]*>)([\s\S]*?)(</w:t>)", run)
        if not tm:
            continue
        # `unesc`, not `xml.sax.saxutils.unescape`: the sax decoder only knows
        # `&amp;`/`&lt;`/`&gt;`, so a run carrying a numeric reference
        # (`&#8211;`, Word's own serialization for a dash) was under-decoded and
        # then re-escaped by with_text into `&amp;#8211;` -- visible junk in the
        # correspondence line. The text-identity check could not see it either
        # (both sides decode back to the same character through unesc), and the
        # bold/roman split point drifted because `left` counts decoded
        # characters while the under-decoded text is longer.
        text = unesc(tm.group(2))
        if not text.strip():
            continue
        take = min(left, len(text))
        head, tail = text[:take], text[take:]
        left -= take
        rpr = RPR_RE.search(run)
        props = rpr.group(0) if rpr else ""
        if "<w:b/>" in props or re.search(r'<w:b w:val="(?:1|true|on)"', props):
            bold = props
        elif not props:
            bold = "<w:rPr><w:b/></w:rPr>"
        elif props.endswith("/>"):
            bold = props[:-2].rstrip() + "><w:b/></w:rPr>"
        else:
            # Merge the bold INTO the existing property bag. Word writes the
            # routine w:rsidRPr attribute on run properties, and CT_R allows
            # exactly ONE w:rPr child, so the old insert-a-second-<w:rPr>
            # splice produced a schema-invalid run (Word: "unreadable
            # content") for any rsid-carrying run.
            open_tag = re.match(r"<w:rPr(?=[\s/>])[^>]*>", props).group(0)
            bold = props.replace(open_tag, open_tag + "<w:b/>", 1)

        def with_text(txt: str, want: str) -> str:
            frag = run[:tm.start(2)] + xml_escape(txt) + run[tm.end(2):]
            fm = RPR_RE.search(frag)
            if fm:
                return frag[:fm.start()] + want + frag[fm.end():]
            om = re.match(r"<w:r\b[^>]*>", frag)
            return frag[:om.end()] + want + frag[om.end():]

        new_runs = with_text(head, bold)
        if tail:
            new_runs += with_text(tail, props)
        out = out.replace(run, new_runs, 1)
        if left <= 0:
            break
    return out


def _label_is_bold(para_xml: str) -> bool:
    """Is the `* Correspondence: ` label (up to the colon) actually bold?"""
    m = _CORRESP_RE.match(text_of(para_xml).strip())
    if not m:
        return False
    left = len(m.group(0))
    for run in re.findall(r"<w:r\b[\s\S]*?</w:r>", para_xml):
        text = "".join(unesc(t) for t in re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run))
        if not text.strip():
            continue
        take = min(left, len(text))
        if take > 0 and not re.search(r"<w:b/>|<w:b w:val=\"(?:1|true|on)\"", run):
            return False
        left -= take
        if left <= 0:
            return True
    return False


def _insert_ppr_extra(ppr_xml: str, extra: str) -> str:
    """Add template pPr children (spacing/ind/jc/rPr) in schema-safe positions."""
    if not extra:
        return ppr_xml
    # `w:pPrChange` (a recorded formatting change) is the LAST child of a pPr
    # and carries a nested `w:pPr` of its own: the `<w:rPr>` inside it is
    # revision RECORD, not this paragraph's property bag, so every edit below
    # stays in the part before it -- and a target with no direct rPr lands its
    # children there too, never after the change (CT_PPr's child order forbids
    # that).
    ci = ppr_xml.find("<w:pPrChange")
    head, change = (ppr_xml[:ci], ppr_xml[ci:]) if ci >= 0 else (ppr_xml, "")
    open_tag = re.match(r"<w:pPr(?=[\s/>])[^>]*>", head)
    if open_tag and open_tag.group(0).endswith("/>"):
        # `<w:pPr/>`: an empty property bag with no closing tag. Open it so the
        # template's children have a home; the old fallback appended a SECOND
        # pPr to the paragraph (CT_P allows one). The test is on the pPr's OWN
        # open tag -- a head that merely ENDS with a self-closing child
        # (`<w:pPr><w:jc w:val="center"/>`) is not an empty bag.
        return (open_tag.group(0)[:-2].rstrip() + ">" + extra + "</w:pPr>" + change)
    if re.search(r"<w:rPr(?=[\s>])", extra):
        # CT_PPr carries at most ONE w:rPr child, and it must sit after every
        # other pPr child except sectPr/pPrChange. The template's own rPr
        # REPLACES the paragraph's direct one -- the same way `_apply_ppr_extra`
        # drops the direct spacing/ind/jc before inserting -- so the existing
        # rPr is removed first. Splicing the template's rPr BESIDE the existing
        # one emitted two rPr children, schema-invalid OOXML that Word reports
        # as unreadable content (the shipped NeoHeteroclitic main text carries
        # exactly that on its affiliation and correspondence lines, and its
        # `docx validate` fails on it).
        head = re.sub(r"<w:rPr(?=[\s/>])[^>]*/>|<w:rPr(?=[\s>])[^>]*>[\s\S]*?</w:rPr>",
                      "", head, count=1)
    rm = re.search(r"<w:rPr(?=[\s>])", head)
    if rm:
        head = head[:rm.start()] + extra + head[rm.start():]
    elif change:
        head = head + extra
    else:
        head = head.replace("</w:pPr>", extra + "</w:pPr>", 1)
    return head + change


def _apply_ppr_extra(frag: str, extra: str) -> str:
    """Give a paragraph the TEMPLATE's own pPr children (its direct spacing)."""
    if not extra:
        return frag
    om = re.match(r"<w:p\b[^>]*>", frag)
    if not om:
        return frag
    # The paragraph's OWN pPr: a balanced span, so a nested `w:pPrChange`
    # (which carries a `</w:pPr>` of its own) is not mistaken for its end --
    # the lazy regex that stopped at the first `</w:pPr>` truncated the block
    # inside the recorded change and spliced the template's children into the
    # revision record.
    pm = re.compile(r"<w:pPr(?=[\s/>])").search(frag, om.end())
    if not pm:
        return frag[:om.end()] + f"<w:pPr>{extra}</w:pPr>" + frag[om.end():]
    s, e = element_span(frag, pm.start(), "pPr")
    block = frag[s:e]
    # The direct spacing/ind/jc the template replaces: confined to the part
    # BEFORE a recorded `w:pPrChange`, whose nested pPr is revision record
    # (stripping inside it edited the author's tracked formatting history).
    ci = block.find("<w:pPrChange")
    head, change = (block[:ci], block[ci:]) if ci >= 0 else (block, "")
    head = re.sub(r"<w:(?:spacing|ind|jc)(?=[\s/>])[^>]*/>", "", head)
    return frag[:s] + _insert_ppr_extra(head + change, extra) + frag[e:]


def _front_matter_styles(doc_xml: str, roles: dict, tpl_doc: str = "") -> tuple:
    """(xml, info): template front matter + the template's heading depth.

    Title on the first paragraph, AuthorList on the author line (bold),
    Abstract/Keywords as unnumbered front matter, headings deeper than the
    template's own depth demoted one level, and direct indents/spacing/
    alignment removed from all styled paragraphs so the template's styles own
    the typography. All ids come from the template.
    """
    title_id = roles.get("title") or ""
    author_id = roles.get("author") or ""
    headings = dict(roles.get("headings") or {})
    depth = int(roles.get("max_heading_level") or 2)
    layout = _template_front_layout(tpl_doc) if tpl_doc else {}
    info = {"title": False, "authors": False, "abstract": False, "keywords": False,
            "correspondence": False, "deep_headings_demoted": 0}
    if not (title_id or author_id or headings):
        return doc_xml, info
    paras = paragraphs(doc_xml)
    entries = [(i, p) for i, p in enumerate(paras) if text_of(p[2]).strip()]
    if not entries:
        return doc_xml, info
    edits = []

    def style_para(idx, style, role=None):
        p0, p1, frag = paras[idx]
        new = _strip_direct_props(_set_para_style(frag, style), strip_num=True)
        if role and layout.get(role):
            new = _apply_ppr_extra(new, layout[role])
        edits.append((p0, p1, new))

    if title_id:
        style_para(entries[0][0], title_id)
        info["title"] = True
    if author_id:
        for idx, p in entries[1:4]:
            t = text_of(p[2]).strip()
            if len(t) < 400 and "@" not in t and ("," in t or " and " in t):
                style_para(idx, author_id)
                info["authors"] = True
                break
    kw_heading = None
    kw_pending = False
    for idx, p in entries:
        t = text_of(p[2]).strip()
        low = t.lower()
        if low == "abstract":
            style_para(idx, author_id or "AuthorList", "abstract_head")
            info["abstract"] = True
        elif low == "keywords":
            kw_heading = idx
            style_para(idx, author_id or "AuthorList")
            kw_pending = True
        elif low.startswith("keywords:") or low.startswith("keywords :"):
            style_para(idx, author_id or "AuthorList")
            info["keywords"] = True
        elif kw_pending:
            # The template uses ONE "Keywords: ..." line; styling the heading and
            # the list keeps the TEXT byte-identical (the merge itself is a
            # content edit the review/rewrite sessions are told to make).
            style_para(idx, author_id or "AuthorList")
            info["keywords"] = True
            kw_pending = False
    # The FIRST page's block order and its direct spacing come from the template:
    # the affiliation lines (before=240/after=0) and the correspondence block
    # (* Correspondence: in BOLD, then the name and the email on their own lines).
    affil = 0
    after_front = len(paras)
    for idx, p in entries:
        t = text_of(p[2]).strip()
        if _CORRESP_RE.match(t) or t.lower() == "abstract" or t.lower().startswith("keywords"):
            after_front = min(after_front, idx)
    for idx, p in entries:
        t = text_of(p[2]).strip()
        if _CORRESP_RE.match(t):
            p0, p1, frag = p
            new = _strip_direct_props(frag, strip_num=True)
            if layout.get("correspondence"):
                new = _apply_ppr_extra(new, layout["correspondence"])
            new = _bold_label_runs(new)
            if new != frag:
                edits.append((p0, p1, new))
            info["correspondence"] = True
        elif idx < after_front and re.match(r"^\d+[A-Z]", t):
            affil += 1
            role = "affiliation_first" if affil == 1 else "affiliation_rest"
            if layout.get(role):
                p0, p1, frag = p
                new = _strip_direct_props(frag, strip_num=True)
                new = _apply_ppr_extra(new, layout[role])
                if new != frag:
                    edits.append((p0, p1, new))
    deep = {sid: level for level, sid in headings.items() if level > depth}
    for idx, p in enumerate(paras):
        pstyle = elem_val(ppr_of(p[2]), "pStyle")
        if pstyle in deep:
            level = deep[pstyle]
            target = headings.get(level - 1) or headings.get(depth)
            if target:
                p0, p1, frag = p
                edits.append((p0, p1, _strip_direct_props(
                    _set_para_style(frag, target), strip_num=False)))
                info["deep_headings_demoted"] += 1
    styled = {sid for sid in (title_id, author_id, roles.get("caption"),
                              *headings.values()) if sid}
    for idx, p in enumerate(paras):
        if elem_val(ppr_of(p[2]), "pStyle") in styled:
            p0, p1, frag = p
            new = _strip_direct_props(frag, strip_num=(elem_val(ppr_of(frag), "pStyle") ==
                                                       "AuthorList"))
            if new != frag:
                edits.append((p0, p1, new))
    if edits:
        # `apply_edits` is only correct for DISJOINT spans. Two passes here (the
        # front-matter roles, then the styled-paragraph strip) can append an edit
        # for the SAME paragraph twice -- e.g. an Abstract heading already styled
        # AuthorList, or a demoted deep heading -- and the second replacement is
        # computed from the unedited fragment, so splicing it at the original
        # offsets removes the text the first replacement inserted. Keep the FIRST
        # (richer: style + template layout) edit per span.
        seen_spans, deduped = set(), []
        for e in edits:
            if (e[0], e[1]) in seen_spans:
                continue
            seen_spans.add((e[0], e[1]))
            deduped.append(e)
        doc_xml = apply_edits(doc_xml, deduped)
    return doc_xml, info


def _strip_direct_props(frag: str, strip_num: bool = False) -> str:
    for pat in (r"<w:ind(?=[\s/>])[^>]*/>", r"<w:spacing(?=[\s/>])[^>]*/>",
                r"<w:jc(?=[\s/>])[^>]*/>"):
        frag = re.sub(pat, "", frag)
    if strip_num:
        frag = re.sub(r"<w:numPr>[\s\S]*?</w:numPr>", "", frag, count=1)
    return frag


def _apply_front_refs(doc_xml: str, front: dict) -> tuple:
    """(xml, applied): point the document's sections at the venue headers/footers.

    Page 1 is governed by the FIRST `w:sectPr` (see `first_section_props`), so
    the template's first-page furniture -- `w:titlePg`, the "first" role and the
    default/even fallbacks -- lands THERE. Every later section gets the
    template's default/even roles but NOT `w:titlePg`: its pages continue the
    run with the venue's running head / page-number footer instead of repeating
    the title page's logo header. Writing only the LAST section (the old
    behaviour) left page 1 in the author's own furniture.
    """
    # A self-closing `<w:sectPr .../>` IS the page-1 section (see
    # `first_section_props`): skipping it put the venue's logo/title-page
    # furniture on the BODY section while page 1 kept the author's own.
    sects = list(SECT_READ_RE.finditer(doc_xml))
    if not sects:
        return doc_xml, False
    refs_all, refs_body = "", ""
    for key, tag, typ in (("header_default_rid", "headerReference", "default"),
                          ("header_first_rid", "headerReference", "first"),
                          ("header_even_rid", "headerReference", "even"),
                          ("footer_default_rid", "footerReference", "default"),
                          ("footer_first_rid", "footerReference", "first"),
                          ("footer_even_rid", "footerReference", "even")):
        if front.get(key):
            ref = f'<w:{tag} w:type="{typ}" r:id="{front[key]}"/>'
            refs_all += ref
            if typ != "first":
                refs_body += ref
    out = doc_xml
    for idx in range(len(sects) - 1, -1, -1):       # backwards: offsets stay valid
        m = sects[idx]
        body = re.sub(r"<w:(?:header|footer)Reference[^>]*/>", "", m.group(0))
        body = re.sub(r"<w:titlePg[^>]*/>", "", body)
        # The OPENING tag only: `[^>]*` greedily consumed the `/` of a legal
        # `<w:sectPr att="x"/>`, so the references were inserted AFTER the
        # self-closing element -- as siblings of `w:sectPr`, which is
        # schema-invalid OOXML -- instead of inside it.
        om = re.match(r"<w:sectPr(?=[\s>])(?:[^>/]|/(?!>))*>", body)
        if om:
            body = body[:om.end()] + (refs_all if idx == 0 else refs_body) + body[om.end():]
        else:
            # A self-closing empty section: expand it so the references land
            # INSIDE the element instead of after its `/>`.
            body = (body[:body.rfind("/>")].rstrip() + ">"
                    + (refs_all if idx == 0 else refs_body) + "</w:sectPr>")
        if idx == 0 and "<w:titlePg" not in body:
            body = (body.replace("<w:docGrid", "<w:titlePg/><w:docGrid", 1)
                    if "<w:docGrid" in body else
                    body.replace("</w:sectPr>", "<w:titlePg/></w:sectPr>", 1))
        out = out[:m.start()] + body + out[m.end():]
    if refs_all:
        root = re.search(r"<w:document\b[^>]*>", out)
        if root and "xmlns:r=" not in root.group(0):
            out = out.replace(
                root.group(0), root.group(0)[:-1] + ' xmlns:r="http://schemas.'
                'openxmlformats.org/officeDocument/2006/relationships">', 1)
    return out, True


def _with_even_odd_headers(parts: dict) -> bool:
    """Make `word/settings.xml` carry `w:evenAndOddHeaders` (the parity switch).

    A template that defines even-page headers/footers only renders them when the
    document turns this setting on. The element is inserted where the schema --
    and the templates themselves -- put it: immediately before
    `w:characterSpacingControl`, or before the first later element present.
    Returns True when the setting was added (the package is modified in place).
    """
    ct = parts.get("[Content_Types].xml", b"").decode("utf-8", "replace")
    settings = parts.get("word/settings.xml")
    if settings is None:
        parts["word/settings.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
            '2006/main"><w:evenAndOddHeaders/></w:settings>').encode("utf-8")
        if 'PartName="/word/settings.xml"' not in ct:
            ct = ct.replace(
                "</Types>", '<Override PartName="/word/settings.xml" ContentType='
                            '"application/vnd.openxmlformats-officedocument.wordprocessingml.'
                            'settings+xml"/></Types>')
            parts["[Content_Types].xml"] = ct.encode("utf-8")
        rels = parts.get("word/_rels/document.xml.rels", b"").decode("utf-8", "replace")
        if "relationships/settings" not in rels:
            used = set(re.findall(r'Id="([^"]+)"', rels))
            n = 3001
            while f"rId{n}" in used:
                n += 1
            rels = rels.replace(
                "</Relationships>",
                f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/'
                f'officeDocument/2006/relationships/settings" Target="settings.xml"/>'
                f"</Relationships>")
            parts["word/_rels/document.xml.rels"] = rels.encode("utf-8")
        return True
    text = settings.decode("utf-8", "replace")
    if "evenAndOddHeaders" in text:
        return False
    element = "<w:evenAndOddHeaders/>"
    anchors = [i for i in (text.find("<w:characterSpacingControl"),
                           text.find("<w:footnotePr"),
                           text.find("<w:endnotePr"),
                           text.find("<w:compat"),
                           text.find("<w:rsids"))
               if i != -1]
    if anchors:
        i = min(anchors)
        text = text[:i] + element + text[i:]
    else:
        i = text.find("<w:defaultTabStop")
        j = text.find("/>", i) if i != -1 else -1
        if j != -1:
            text = text[:j + 2] + element + text[j + 2:]
        else:
            text = text.replace("</w:settings>", element + "</w:settings>", 1)
    parts["word/settings.xml"] = text.encode("utf-8")
    return True


_NUMBERING_GROUP_RE = re.compile(
    r"<w:(numPicBullet|abstractNum|num|numIdMacAtCleanup)(?=[\s/>])")


def _reorder_numbering_groups(xml: str, pics: str, abstracts: str, nums: str) -> str:
    """Rebuild `word/numbering.xml` with the carried blocks in schema order.

    CT_Numbering is a strict sequence (`numPicBullet*`, `abstractNum*`,
    `num*`, `numIdMacAtCleanup?`); splicing the carried definitions before
    `</w:numbering>` leaves an `abstractNum` after the template's own `num`
    whenever the template already defined one, and Word/`docx validate` refuses
    the part. Each existing top-level block keeps its bytes; only the group
    order changes, and the three carried groups join their own group.
    """
    close_at = xml.rfind("</w:numbering>")
    open_m = re.search(r"<w:numbering(?=[\s/>])[^>]*>", xml)
    if close_at == -1 or not open_m:
        return xml
    inner = xml[open_m.end():close_at]
    entries, other = [], []
    pos = 0
    for m in _NUMBERING_GROUP_RE.finditer(inner):
        if m.start() > pos:
            other.append(inner[pos:m.start()])
        open_end = (m.end() if inner[m.end() - 1:m.end()] == ">"
                    else inner.find(">", m.end()) + 1)
        if inner[open_end - 2:open_end] == "/>":
            end = open_end
        else:
            close = inner.find(f"</w:{m.group(1)}>", open_end)
            end = close + len(f"</w:{m.group(1)}>") if close != -1 else open_end
        entries.append((m.group(1), inner[m.start():end]))
        pos = end
    if pos < len(inner):
        other.append(inner[pos:])
    groups = {k: [] for k in ("numPicBullet", "abstractNum", "num", "numIdMacAtCleanup")}
    for tag, block in entries:
        groups[tag].append(block)
    # Anything that is not a numbering group (comments, whitespace) is kept,
    # appended at the end: XML comments are legal between the sequence
    # children, and silently dropping them would be a data loss of its own.
    return (xml[:open_m.end()]
            + "".join(groups["numPicBullet"]) + pics
            + "".join(groups["abstractNum"]) + abstracts
            + "".join(groups["num"]) + nums
            + "".join(groups["numIdMacAtCleanup"])
            + "".join(other)
            + xml[close_at:])


def _merge_source_lists(parts: dict, src_numbering: str, doc_part_re) -> dict:
    """Keep the source's list definitions that the template does not define.

    `apply_word_template` swaps the template's `word/numbering.xml` in; a
    paragraph whose DIRECT `w:numPr` names a source numId the template does not
    define then points at nothing and Word silently drops its bullet/number.
    Copy those definitions into the template's part under fresh ids (fresh
    abstractNum/num/picture-bullet ids, so nothing can collide) and rewrite the
    document's references. Returns {old numId: new numId} for what it carried;
    a numId the template DOES define keeps the template's definition.
    """
    tpl_numbering = parts.get("word/numbering.xml", b"").decode("utf-8", "replace")
    if not tpl_numbering or "</w:numbering>" not in tpl_numbering:
        return {}
    doc_names = [n for n in sorted(parts) if doc_part_re.fullmatch(n)]
    referenced = set()
    for name in doc_names:
        referenced |= set(re.findall(r'<w:numId(?=[\s/>])[^>]*w:val="(\d+)"',
                                     parts[name].decode("utf-8", "replace")))
    defined = set(re.findall(r'<w:num(?=[\s/>])[^>]*w:numId="(\d+)"', tpl_numbering))
    missing = sorted(referenced - defined, key=lambda s: (len(s), s))
    if not missing:
        return {}
    both = tpl_numbering + src_numbering
    next_abs = max((int(x) for x in re.findall(r'w:abstractNumId="(\d+)"', both)), default=0) + 1
    next_num = max((int(x) for x in re.findall(r'<w:num(?=[\s/>])[^>]*w:numId="(\d+)"', both)),
                   default=0) + 1
    next_pic = max((int(x) for x in re.findall(r'w:numPicBulletId="(\d+)"', both)), default=0) + 1
    abs_map, abs_blocks, num_blocks, pic_blocks = {}, [], [], []
    num_map = {}
    for old_num in missing:
        num_block = re.search(
            rf'<w:num(?=[\s/>])[^>]*w:numId="{re.escape(old_num)}"[\s\S]*?</w:num>', src_numbering)
        if not num_block:
            continue
        abs_ref = re.search(r'<w:abstractNumId(?=[\s/>])[^>]*w:val="(\d+)"', num_block.group(0))
        if not abs_ref:
            continue
        old_abs = abs_ref.group(1)
        if old_abs not in abs_map:
            abs_block = re.search(
                rf'<w:abstractNum(?=[\s/>])[^>]*w:abstractNumId="{re.escape(old_abs)}"'
                r'[\s\S]*?</w:abstractNum>', src_numbering)
            if not abs_block:
                continue
            new_abs = str(next_abs)
            next_abs += 1
            block = re.sub(rf'w:abstractNumId="{re.escape(old_abs)}"',
                           f'w:abstractNumId="{new_abs}"', abs_block.group(0), count=1)
            # a picture-bullet level references a numPicBullet element that must
            # travel with the copied list (schema order: numPicBullet, abstractNum, num)
            pic_map = {}
            for pid in sorted(set(re.findall(
                    r'<w:lvlPicBulletId(?=[\s/>])[^>]*w:val="(\d+)"', block))):
                pic = re.search(
                    rf'<w:numPicBullet(?=[\s/>])[^>]*w:numPicBulletId="{re.escape(pid)}"'
                    r'[\s\S]*?</w:numPicBullet>', src_numbering)
                if not pic:
                    continue
                new_pid = str(next_pic)
                next_pic += 1
                pic_map[pid] = new_pid
                pic_blocks.append(re.sub(rf'w:numPicBulletId="{re.escape(pid)}"',
                                         f'w:numPicBulletId="{new_pid}"', pic.group(0), count=1))
            for pid, new_pid in pic_map.items():
                block = re.sub(rf'(<w:lvlPicBulletId(?=[\s/>])[^>]*w:val="){re.escape(pid)}(")',
                               rf'\g<1>{new_pid}\g<2>', block)
            abs_map[old_abs] = new_abs
            abs_blocks.append(block)
        new_num = str(next_num)
        next_num += 1
        carried = re.sub(r'(<w:abstractNumId(?=[\s/>])[^>]*w:val=")[^"]*(")',
                         rf'\g<1>{abs_map[old_abs]}\g<2>', num_block.group(0), count=1)
        carried = re.sub(r'(<w:num(?=[\s/>])[^>]*w:numId=")[^"]*(")',
                         rf'\g<1>{new_num}\g<2>', carried, count=1)
        num_blocks.append(carried)
        num_map[old_num] = new_num
    if not num_map:
        return {}
    # ECMA-376 requires the numbering part's children in schema order:
    # numPicBullet*, abstractNum*, num*, numIdMacAtCleanup?. Appending the three
    # groups at the end is only correct when the template has no w:num yet --
    # a template that already defines one made the merged part run
    # `abstractNum, num, abstractNum, num`, and `docx validate` rejected it
    # ("abstractNum: This element is not expected. Expected is num").
    parts["word/numbering.xml"] = _reorder_numbering_groups(
        parts["word/numbering.xml"].decode("utf-8", "replace"),
        "".join(pic_blocks), "".join(abs_blocks), "".join(num_blocks)).encode("utf-8")
    for name in doc_names:
        xml = parts[name].decode("utf-8", "replace")
        new_xml = re.sub(
            r'(<w:numId(?=[\s/>])[^>]*w:val=")(\d+)(")',
            lambda m: m.group(1) + num_map.get(m.group(2), m.group(2)) + m.group(3), xml)
        if new_xml != xml:
            parts[name] = new_xml.encode("utf-8")
    return num_map


def apply_word_template(src: Path, out: Path, template: Path, containers=()) -> dict:
    """Restyle one DOCX into the venue's official Word template.

    The template's styles/theme/font table/numbering REPLACE the manuscript's
    (the names are mapped by style NAME, so a manuscript that uses its own ids
    still lands on the template's Heading 1/2, Title, Caption, ...), the
    template's page geometry is adopted, and the direct fonts/sizes/spacing/
    indentation that would otherwise override the styles are dropped on
    styled paragraphs. A heading the source only DIRECT-formatted (a short bold
    line above the body size, no paragraph style) is first retagged onto the
    template's Heading 1..N (`headings_retagged`), so the strip below cannot
    flatten it into body text and the template's heading styles -- and their
    numbering -- actually apply. Content, media, fields, headers/footers and
    relationships are preserved; the document TEXT must be byte-identical
    (reported as `text_unchanged`, and the caller keeps the original when it is
    not).
    """
    try:
        with zipfile.ZipFile(src) as spkg, zipfile.ZipFile(template) as tpkg:
            tnames = set(tpkg.namelist())
            if "word/styles.xml" not in tnames or "word/document.xml" not in tnames:
                return {"file": str(src), "ok": False,
                        "error": "the template is not a readable Word template "
                                 "(word/styles.xml / word/document.xml missing)"}
            parts = {i.filename: spkg.read(i.filename) for i in spkg.infolist()}
            src_styles = parts.get("word/styles.xml", b"").decode("utf-8", "replace")
            src_numbering = parts.get("word/numbering.xml", b"").decode("utf-8", "replace")
            tpl_styles = tpkg.read("word/styles.xml").decode("utf-8", "replace")
            s_by_id, _s_names = _style_index(src_styles)
            t_by_id, t_by_name = _style_index(tpl_styles)
            mapping = {}
            for sid, (typ, key) in s_by_id.items():
                if sid in t_by_id:
                    mapping[sid] = sid
                elif (typ, key) in t_by_name:
                    mapping[sid] = t_by_name[(typ, key)]
            mapped_ids = set(mapping.values())
            copied = []
            for name in ("word/styles.xml", "word/fontTable.xml", "word/numbering.xml"):
                if name in tnames:
                    parts[name] = tpkg.read(name)
                    copied.append(name)
            for name in sorted(tnames):
                if name.startswith("word/theme/"):
                    parts[name] = tpkg.read(name)
                    copied.append(name)
            tpl_doc = tpkg.read("word/document.xml").decode("utf-8", "replace")

            # A manuscript-only style the document still references must survive
            # the styles.xml replacement (otherwise its pStyle/rStyle points at
            # a definition that no longer exists).
            doc_part_re = re.compile(r"word/(?:document|header\d*|footer\d*|footnotes|endnotes)\.xml")
            ref_ids = set()
            for name in sorted(parts):
                if doc_part_re.fullmatch(name):
                    xml = parts[name].decode("utf-8", "replace")
                    ref_ids |= {m.group(2) for m in _STYLE_REF_RE.finditer(xml)}
            kept_styles = []
            for sid in sorted(ref_ids - set(t_by_id) - set(mapping)):
                m = re.search(rf'<w:style\b[^>]*w:styleId="{re.escape(sid)}"[\s\S]*?</w:style>',
                              src_styles)
                if m:
                    kept_styles.append(m.group(0))
            if kept_styles:
                tpl_styles = tpl_styles.replace("</w:styles>",
                                                "".join(kept_styles) + "</w:styles>")
                parts["word/styles.xml"] = tpl_styles.encode("utf-8")

            remapped = stripped = carried_lists = 0
            page_ok = False
            front_info = {}
            headings_retagged = []
            roles = template_style_roles(template)
            for name in sorted(parts):
                if not doc_part_re.fullmatch(name):
                    continue
                xml = parts[name].decode("utf-8", "replace")
                new_xml, n = _remap_style_refs(xml, mapping)
                remapped += n
                retag_styles = set()
                if name == "word/document.xml":
                    # Heading STYLE first, then strip: a source heading that only
                    # carries direct formatting must not be flattened into body
                    # text by the strip below.
                    new_xml, headings_retagged = _retag_headings(new_xml, roles, containers)
                    retag_styles = {t["style"] for t in headings_retagged}
                # A paragraph whose style exists in the template follows that
                # style: drop the direct geometry/typography that would hide it.
                edits = []
                for p0, p1, para in paragraphs(new_xml):
                    pstyle = elem_val(ppr_of(para), "pStyle")
                    # The reference was already rewritten to the TEMPLATE id, so
                    # test against the mapped ids, not the manuscript's old ids.
                    # An UNSTYLED paragraph also follows the template's default
                    # (Normal/theme) once its direct font/size/spacing overrides
                    # are gone; a paragraph with an unmapped custom style is left
                    # alone (there is no template equivalent to fall back to).
                    if pstyle and pstyle not in mapped_ids and pstyle not in retag_styles:
                        continue
                    stripped_para, k = _strip_direct_format(para)
                    if k:
                        stripped += k
                        edits.append((p0, p1, stripped_para))
                if edits:
                    new_xml = apply_edits(new_xml, edits)
                if name == "word/document.xml":
                    new_xml, page_ok = _adopt_page_geometry(new_xml, tpl_doc)
                    new_xml, front_info = _front_matter_styles(new_xml, roles, tpl_doc)
                if new_xml != xml:
                    parts[name] = new_xml.encode("utf-8")
            if "word/numbering.xml" in copied and src_numbering:
                carried_lists = len(_merge_source_lists(parts, src_numbering, doc_part_re))
            front_parts = _template_front_parts(tpkg, parts, tnames)
            if front_parts:
                doc_xml = parts["word/document.xml"].decode("utf-8", "replace")
                doc_xml, refs_ok = _apply_front_refs(doc_xml, front_parts)
                if refs_ok:
                    parts["word/document.xml"] = doc_xml.encode("utf-8")
                if front_parts.get("even_odd"):
                    _with_even_odd_headers(parts)
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for name, data in parts.items():
                    z.writestr(name, data)
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as e:
        return {"file": str(src), "ok": False, "error": f"{type(e).__name__}: {e}"}

    def _text(p: Path) -> str:
        with zipfile.ZipFile(p) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        return "\n".join(t for t in (text_of(par[2]) for par in paragraphs(xml)) if t.strip())

    try:
        text_ok = _text(src) == _text(out)
        with zipfile.ZipFile(out) as z:
            check_parts = ["word/document.xml", "word/styles.xml"]
            if "word/numbering.xml" in copied or carried_lists:
                check_parts.append("word/numbering.xml")
            for name in check_parts:
                ET.fromstring(z.read(name))
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, RuntimeError,
            NotImplementedError) as e:
        return {"file": str(src), "ok": False, "error": f"verification failed: {e}"}
    changes = [f"copied {len(copied)} template part(s)",
               f"remapped {remapped} style reference(s)"]
    if carried_lists:
        changes.append(f"carried {carried_lists} source list definition(s) the template "
                       f"does not define")
    if stripped:
        changes.append(f"removed {stripped} direct formatting propert(ies)")
    if page_ok:
        changes.append("adopted the template page geometry")
    if front_info.get("title"):
        changes.append("front matter: article title -> Title (centered)")
    if front_info.get("authors"):
        changes.append("front matter: author line -> AuthorList (bold)")
    if front_info.get("abstract"):
        changes.append("front matter: Abstract -> unnumbered AuthorList")
    if front_info.get("keywords"):
        changes.append("front matter: Keywords -> the template's front-matter style")
    if front_info.get("deep_headings_demoted"):
        changes.append(f"demoted {front_info['deep_headings_demoted']} heading(s) deeper than "
                       f"the template's own depth")
    if headings_retagged:
        changes.append(f"tagged {len(headings_retagged)} directly-formatted heading(s) with the "
                       f"template's heading styles")
    if front_parts:
        # Describe what was actually copied: a template with no logo header
        # still made the old line claim "first-page header (logo)".
        got = []
        if front_parts.get("logo"):
            got.append("first-page header (logo)")
        elif front_parts.get("header_first"):
            got.append("first-page header")
        if front_parts.get("header_default"):
            got.append("default header")
        if any(front_parts.get(k) for k in ("footer_first", "footer_default", "footer_even")):
            got.append("page-number footers")
        changes.append("copied the venue's " + ", ".join(got)
                       if got else "copied the venue's front-page furniture")
        if front_parts.get("even_odd"):
            changes.append("enabled the template's odd/even (evenAndOddHeaders) page furniture")
        for role in front_parts.get("footer_replaced") or []:
            changes.append(f"replaced the template's {role}-page footer with the plain "
                           f"page-number footer")
    return {"file": str(src), "template": str(template), "ok": bool(text_ok),
            "text_unchanged": bool(text_ok), "changes": changes,
            "styles_copied": copied, "style_refs_remapped": remapped,
            "direct_format_removed": stripped, "page_geometry": page_ok,
            "headings_retagged": headings_retagged,
            "front_matter": front_info,
            "template_roles": {k: v for k, v in (roles or {}).items() if k != "headings"},
            "front_parts": {k: v for k, v in (front_parts or {}).items() if k != "copied"}}


def validate_latex(path: Path, workdir: Path = None, timeout: int = 300) -> dict:
    """Compile one STANDALONE .tex in a scratch copy of its directory.

    A `.tex` without `\\documentclass` is a FRAGMENT (a `\\input`ed section or a
    generated table): compiling it alone fails on the missing preamble, so it is
    reported SKIP and validated through the document that inputs it -- the main
    file's compile is what proves it.
    """
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:8000]
    except OSError as e:
        return {"file": str(path), "kind": "tex", "ok": False,
                "errors": [f"unreadable: {e}"], "detail": str(e)}
    if "\\documentclass" not in head and "\\documentclass" not in \
            path.read_text(encoding="utf-8", errors="replace"):
        return {"file": str(path), "kind": "tex", "ok": None,
                "detail": "fragment (no \\documentclass): validated through the document "
                          "that inputs it"}
    engine = latex_engine()
    if engine is None:
        return {"file": str(path), "kind": "tex", "ok": None,
                "detail": "no TeX engine (latexmk/xelatex/pdflatex) on PATH; "
                          "compilation not verified"}
    name, argv = engine
    scratch = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="paper_tex_check_"))
    owns_scratch = workdir is None
    try:
        try:
            target_dir = scratch / path.parent.name if not workdir else scratch
            if not target_dir.is_dir():
                # A name-based ignore callback (not glob patterns): the tracking
                # token space is open (a1/w2/a3/winner1/...), so only the shared
                # `_is_aux_name()` rule can decide what to leave out.
                shutil.copytree(path.parent, target_dir,
                                ignore=lambda _d, names: [n for n in names
                                                          if n == "work" or _is_aux_name(n)])
            proc = subprocess.run(argv + [path.name], cwd=str(target_dir),
                                  capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError, shutil.Error) as e:
            return {"file": str(path), "kind": "tex", "ok": False, "engine": name,
                    "errors": [f"{type(e).__name__}: {e}"],
                    "detail": "the compile step itself failed"}
        out = (proc.stdout or "") + (proc.stderr or "")
        errors = [ln.strip() for ln in out.splitlines() if ln.startswith("!")][:5]
        return {"file": str(path), "kind": "tex", "ok": proc.returncode == 0, "engine": name,
                "errors": errors, "detail": (errors[0] if errors else
                                             ("compiled" if proc.returncode == 0
                                              else f"engine exited {proc.returncode}"))}
    finally:
        # A validation pass over N .tex files must not leak N full project
        # copies; an operator-supplied workdir is not ours to remove.
        if owns_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def validate_paths(paths: list, json_out: Path = None, timeout: int = 300) -> dict:
    """Validate every DOCX (XML/schema) and .tex (compile) under `paths`."""
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += [q for q in docx_files_under(p)
                      if not q.name.startswith("~$") and not _is_aux_name(q.name)
                      and not any(part in EVIDENCE_DIRNAMES for part in q.parts[:-1])]
            files += [q for q in sorted(p.rglob("*.tex")) + sorted(p.rglob("*.ltx"))
                      if not any(part in EVIDENCE_DIRNAMES for part in q.parts[:-1])
                      # A difference-tracking copy (a latexdiff file, or the
                      # commented-out logging fallback) is not a document of the
                      # package: compiling it would report the AUXILIARY as a
                      # failed deliverable (a fragment's copy has no preamble).
                      and not _is_aux_name(q.name)]
        elif p.is_file():
            files.append(p)
    results = []
    for p in files:
        if p.suffix.lower() == ".docx":
            results.append(validate_docx_parts(p))
        elif p.suffix.lower() in (".tex", ".ltx"):
            results.append(validate_latex(p, timeout=timeout))
    bad = [r for r in results if r["ok"] is False]
    report = {"files": len(results), "failed": len(bad), "results": results,
              "ok": not bad}
    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    return report


def _is_aux_name(name: str) -> bool:
    """A difference-tracking auxiliary (see AUX_FILES_RULE in paper_pipeline.py).

    The rule has to match THE PIPELINE'S (`TRACKING_AUX_NAME_RE`): the scanner
    and the corpus builder must agree on which files are submission content, or
    a scan of a package reports rows on files the pipeline itself wrote. The
    name is `<anything>.tracking-<token>.<ext>` (or `.logging-<token>.<ext>` for
    the fallback log), where <token> names the baseline: `original`, a version
    id (`a1`, `w2`, ...) or a published round winner (`winner1`, ...). The
    extension set covers the `.docx`/`.tex`/`.bib` copies AND the compiled
    `.pdf` of a tracking `.tex` compile root.
    """
    low = name.lower()
    return re.search(r"\.(?:tracking|logging)-(?:original|winner[0-9]+|[awi][0-9]+)"
                     r"\.(?:docx|tex|bib|pdf)$", low) is not None


# --------------------------------------------------------------------------
# PDF ARTIFACT SANITY (rules FMT-PDF1..FMT-PDF3).
#
# A submission package ships PDFs that must OPEN and SHOW their content outside
# the author's own machine. Two shapes pass every existing check because they
# are valid PDFs with a valid page:
#   * an Adobe LiveCycle/XFA FORM: the page is a JavaScript shell, so a reader
#     that is not Adobe Acrobat (a journal's converter, a browser view, the
#     submission system's text extractor) renders "Please wait..." and nothing
#     else. A "reporting summary filled.pdf" can therefore be COMPLETELY blank
#     while being 1.6 MB of XFA template.
#   * a PDF whose XFA dataset exists but carries no value: the form was never
#     filled in (or the fill was never saved into the dataset).
# Both are reported as high findings (the pipeline must not certify a package
# whose required form is blank), and the check degrades to the raw byte scan
# when `pdfinfo` is unavailable.
# --------------------------------------------------------------------------

PDF_PLACEHOLDER_RE = re.compile(
    r"(?is)if this message is not eventually replaced by the proper contents")
PDF_PLACEHOLDER_BYTES_RE = re.compile(
    rb"(?is)if this message is not eventually replaced by the proper contents")
# The XFA shell renders "Please wait..." (the ellipsis is part of the
# placeholder). Without it the pattern matched the ordinary English phrase in
# any sentence -- "Please wait for the reviewer assignment..." -- and a healthy
# one-page letter was reported FMT-PDF1 at high severity.
PDF_PLACEHOLDER_STRONG_RE = re.compile(r"(?is)please\s+wait\s*(?:\.{2,3}|\u2026)")
PDF_VERSION_EXTS = (".pdf",)


def _pdfinfo_form(path: Path) -> str:
    """The raw `Form:` value pdfinfo prints ("" when pdfinfo is absent/unreadable).

    `pdfinfo` prints "Form: none" for an ordinary PDF and the form TECHNOLOGY
    (XFA/LiveCycle/AcroForm) for a form, and the two must stay distinguishable:
    a caller that asks "is this (or may it be) a form?" tests for the empty
    string (pdfinfo could not tell) and for "none" (pdfinfo proved there is no
    form) separately, exactly as `pdf_artifact_rows` does.
    """
    exe = shutil.which("pdfinfo")
    if not exe:
        return ""
    try:
        proc = subprocess.run([exe, str(path)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in (proc.stdout or "").splitlines():
        if line.lower().startswith("form:"):
            value = line.split(":", 1)[1].strip()
            return value
    return ""


def _xfa_dataset_packets(data: bytes) -> list:
    """Every decompressed `xfa:datasets` packet in a PDF, as (offset, text).

    A LiveCycle form saved more than once carries SEVERAL dataset packets: the
    original template's empty one and the current filled one (an incremental
    update appends the newer). The scan returns all of them, and the caller
    treats the form as filled when ANY packet carries an answer -- the older
    "the first packet decides" reading is how a genuinely filled Reporting
    Summary was reported as UNFILLED by both the round-1 review and the
    publish-time scanner.
    """
    packets = []
    for m in re.finditer(rb"(?<!end)stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        raw = data[start:end]
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            # An UNCOMPRESSED stream is legal (`/Length` with no `/Filter`) and
            # the XFA packet set may be written that way by a non-Adobe tool:
            # skipping it made `all_datasets` read 0 on a form that carries two
            # packet sets (the 2026-10-15 hand-off test).
            dec = raw
        if b"xfa:datasets" in dec:
            packets.append((start, dec.decode("utf-8", "replace")))
    return packets


# XFA answers serialize with whitespace before the closing bracket
# (`<author\n>Xuegong Zhang</author\n>`), which is why the old
# `<tag>value</tag>` pattern counted ZERO answers on a filled form.
# The value class is deliberately unbounded: `[^<>]` cannot cross a tag
# boundary, so the match is confined to one text node and there is nothing to
# backtrack over. The old `{1,400}` cap made a LONGER answer invisible -- a
# filled form whose answer ran past 400 characters counted as UNFILLED
# (FMT-PDF2) and `xfa_export_text` (which promises "every answer") dropped it.
XFA_LEAF_RE = re.compile(r"<([A-Za-z_][\w.\-]*)\s*>\s*([^<>]*?)\s*</\1\s*>")


def _xfa_dataset_report(path: Path):
    """(is_xfa, non_empty_values, is_livecycle_shell) for a PDF's XFA dataset.

    `is_livecycle_shell` is True when the PDF's own rendered text is the Adobe
    placeholder, i.e. the document is a FORM DEFINITION, not a document.
    `non_empty_values` counts the answer leaves of EVERY dataset packet; an
    XFA form with no dataset packet at all returns -1 (unverifiable), which
    never produces the "unfilled" finding.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return (False, -1, False)
    form_line = _pdfinfo_form(Path(path))
    # The byte test requires the AcroForm/XFA object structure, not the bare
    # string: a normal compiled PDF can contain "/XFA" inside its own text.
    is_xfa = ("xfa" in form_line.lower()
              or (b"AcroForm" in data and re.search(rb"/XFA[\s/\[]", data) is not None))
    is_shell = bool(PDF_PLACEHOLDER_RE.search(data.decode("latin-1", "replace")))
    packets = _xfa_dataset_packets(data) if is_xfa else []
    non_empty = -1 if is_xfa and not packets else 0
    for _off, text in packets:
        for em in XFA_LEAF_RE.finditer(text):
            if em.group(2).strip():
                non_empty += 1
    if not is_shell:
        for m in re.finditer(rb"(?<!end)stream\r?\n", data):
            start = m.end()
            end = data.find(b"endstream", start)
            if end < 0:
                continue
            try:
                dec = zlib.decompress(data[start:end])
            except zlib.error:
                continue
            if PDF_PLACEHOLDER_BYTES_RE.search(dec):
                # The placeholder lives in a COMPRESSED stream: the shell is
                # real even when pdftotext cannot render the page.
                is_shell = True
                break
    return (is_xfa, non_empty, is_shell)


def _pdf_object_bodies(data: bytes) -> dict:
    """{object number: raw body} for a PDF, object streams expanded.

    The one thing `_xfa_dataset_packets` cannot see: WHICH packet the form
    actually reads. The AcroForm's `/XFA` array names it by object number, and on
    a form saved more than once those numbers live inside an object stream
    (`/ObjStm`) -- so the array has to be read from the DECOMPRESSED objects, not
    from the raw bytes. Text-level reading served the earlier rounds; it is what
    made a form's live dataset unidentifiable (2026-10-15).
    """
    objs: dict = {}
    # NOT line-anchored: a PDF may use `\r` line endings, and `(?m)^` then
    # matches almost nothing (two top-level objects out of 54 in this file's
    # case), so the object carrying the live /XFA array was never read. A wrong
    # hit inside a stream is harmless as long as it is not the LAST definition
    # of the number we resolve -- the dictionary guard below drops those.
    for m in re.finditer(rb"(\d+)\s+0\s+obj", data):
        num = int(m.group(1))
        start = m.end()
        end = data.find(b"endobj", start)
        body = data[start:end if end >= 0 else len(data)]
        stripped = body.lstrip(b"\r\n \t")
        if not stripped.startswith(b"<<") and b"stream" not in body[:200]:
            continue
        if stripped.startswith(b"<<") and b"stream" not in body:
            close = stripped.find(b">>")
            if close < 0:
                continue
        objs[num] = body
    for num in list(objs):
        body = objs[num]
        if b"/ObjStm" not in body[:400]:
            continue
        sm = re.search(rb"(?<!end)stream\r?\n", body)
        if not sm:
            continue
        raw = body[sm.end():]
        stop = raw.find(b"endstream")
        if stop >= 0:
            raw = raw[:stop]
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            continue
        fm = re.search(rb"/First (\d+)", body)
        nm = re.search(rb"/N (\d+)", body)
        if not (fm and nm):
            continue
        first, count = int(fm.group(1)), int(nm.group(1))
        hdr = dec[:first].split()
        for i in range(count):
            try:
                onum, off = int(hdr[2 * i]), int(hdr[2 * i + 1])
            except (IndexError, ValueError):
                break
            nxt = int(hdr[2 * i + 3]) if 2 * i + 3 < len(hdr) else len(dec) - first
            # LAST definition wins: an incremental update appends the newer
            # objects, and a PDF reader resolves an object number to its LATEST
            # definition. `setdefault` kept the first, i.e. the stale XFA packet
            # array -- which is how this helper first read a filled form's live
            # dataset as the empty duplicate (2026-10-15).
            objs[onum] = dec[first + off:first + nxt]
    return objs


def _obj_stream_text(body: bytes):
    """The decompressed (or plain) stream of one object body, or None."""
    sm = re.search(rb"(?<!end)stream\r?\n", body)
    if not sm:
        return None
    raw = body[sm.end():]
    stop = raw.find(b"endstream")
    if stop >= 0:
        raw = raw[:stop]
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return raw


def xfa_live_packets(path: Path) -> dict:
    """Which XFA packets the AcroForm READS, and what each one carries.

    Returns {"resolved", "packets": {name: (object number, non-empty leaves,
    text)}, "live_datasets": [names], "all_datasets": <count of dataset packets
    in the file>}. `resolved` is False when the /XFA array cannot be read (an
    older reader's guess is then the best available), and the 2026-10-15
    Audit's question -- "is the empty copy the one the form uses, or a stale
    duplicate?" -- is answered by the /XFA array itself, never by packet order.
    """
    out = {"resolved": False, "packets": {}, "live_datasets": [], "all_datasets": 0}
    try:
        data = Path(path).read_bytes()
    except OSError:
        return out
    objs = _pdf_object_bodies(data)
    out["all_datasets"] = len(_xfa_dataset_packets(data))
    acro = [(num, body) for num, body in objs.items() if re.search(rb"/XFA[\s/\[]", body)]
    if not acro:
        return out
    # An incremental update appends: the object with the HIGHEST number is the
    # live AcroForm (a later save never lowers an object number).
    num, body = max(acro, key=lambda kv: kv[0])
    m = re.search(rb"/XFA\s*\[(.*?)\]", body, re.S)
    if m:
        for name, onum in re.findall(rb"\(([^)]*)\)\s*(\d+)\s+0\s+R", m.group(1)):
            pname = name.decode("latin-1")
            onum = int(onum)
            pbody = objs.get(onum)
            text = _obj_stream_text(pbody) if pbody is not None else None
            if text is None:
                continue
            if b"xfa:datasets" in text or b"<xfa:data" in text:
                answers = [(em.group(1), em.group(2).strip())
                           for em in XFA_LEAF_RE.finditer(text.decode("utf-8", "replace"))
                           if em.group(2).strip()]
                out["packets"][pname] = (onum, len(answers), text)
            else:
                out["packets"][pname] = (onum, 0, text)
        out["resolved"] = bool(out["packets"])
    else:
        # A single-stream /XFA: the whole XDP is in one object; its datasets
        # packet is the part this report needs.
        sm = re.search(rb"/XFA\s+(\d+)\s+0\s+R", body)
        if sm:
            text = _obj_stream_text(objs.get(int(sm.group(1)), b""))
            if text and b"xfa:data" in text:
                answers = [(em.group(1), em.group(2).strip())
                           for em in XFA_LEAF_RE.finditer(text.decode("utf-8", "replace"))
                           if em.group(2).strip()]
                out["packets"]["<single-stream>"] = (int(sm.group(1)), len(answers), text)
                out["resolved"] = True
    out["live_datasets"] = [k for k, v in out["packets"].items()
                            if v[2] and (b"xfa:datasets" in v[2] or b"<xfa:data" in v[2])]
    return out


def _xfa_packet_summary(path: Path) -> dict:
    """The LIVE dataset's answer count, plus any STALE duplicate packet set.

    A form saved twice carries the original (often empty) packet set AND the
    saved one, and the two disagree -- the 2026-10-15 operator's audit of the
    CopyNumBench Reporting Summary reported "the XFA dataset the file actually
    uses is empty" about a form whose live dataset carries 48 answers (the
    empty one is the STALE copy, object 76, while the live /XFA array names
    object 275). Both readings are reachable: a strict reader resolves the
    latest object (the answers show), some XFA processors and text tools take the
    first packet (the form reads BLANK). That is a deliverable defect either way,
    so the count of each side is reported and the caller words its row from
    them.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return {}
    is_xfa, _all_answers, is_shell = _xfa_dataset_report(Path(path))
    live = xfa_live_packets(Path(path))
    out = {"is_xfa": is_xfa, "is_shell": is_shell, "resolved": bool(live.get("resolved")),
           "live_answers": 0, "live_objects": [], "stale_answers": 0, "stale_objects": [],
           "packets": live.get("all_datasets") or 0}
    live_nums = set()
    for name, (onum, count, text) in (live.get("packets") or {}).items():
        if not text or not (b"xfa:datasets" in text or b"<xfa:data" in text):
            continue
        live_nums.add(onum)
        out["live_objects"].append(onum)
        out["live_answers"] = max(out["live_answers"], int(count))
    live_texts = {v[2].decode("utf-8", "replace")
                  for v in (live.get("packets") or {}).values() if v[2]}
    for _off, text in _xfa_dataset_packets(data):
        if not out["resolved"] or text in live_texts:
            continue
        # A dataset packet the /XFA array does not name: a stale copy from an
        # earlier save. Its own answer count is what a reader taking "the first
        # packet" would see.
        answers = sum(1 for em in XFA_LEAF_RE.finditer(text) if em.group(2).strip())
        out["stale_answers"] = max(out["stale_answers"], answers)
    return out


def xfa_dataset_answers(path: Path, limit: int = 400) -> list:
    """[(field name, answer)] of the richest XFA dataset packet (or []).

    `limit` bounds a caller's listing; `None` returns every answer. The
    readable export passes None: it promises "every answer", while the FMT gate
    counts every non-empty leaf (`_xfa_dataset_report`), so a form with more
    than `limit` answers was reported as N filled and exported as N-1.

    The LIVE packet wins when the AcroForm's own `/XFA` array can be read: the
    export must show the answers the form actually carries, and reading a stale
    duplicate instead is how "the form is filled" and "the form is blank" were
    both argued about the same file in 2026-10-15.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    live = xfa_live_packets(Path(path))
    if live.get("resolved"):
        for name in live.get("live_datasets") or []:
            text = live["packets"].get(name, (None, 0, None))[2]
            if not text:
                continue
            answers = [(em.group(1), em.group(2).strip())
                       for em in XFA_LEAF_RE.finditer(text.decode("utf-8", "replace"))
                       if em.group(2).strip()]
            if answers:
                return answers if limit is None else answers[:limit]
    best = []
    for _off, text in _xfa_dataset_packets(data):
        answers = [(em.group(1), em.group(2).strip())
                   for em in XFA_LEAF_RE.finditer(text) if em.group(2).strip()]
        if len(answers) > len(best):
            best = answers
    return best if limit is None else best[:limit]


def xfa_export_text(path: Path) -> str:
    """A readable rendering of a filled XFA form (the answer to the shell).

    This is what the pipeline can produce offline: the editor/reviewer can
    read every answer even when their viewer shows the Adobe placeholder. It is
    NOT a layout reproduction of the journal's form (that needs Acrobat), so the
    pipeline ships it beside the original and says so.
    """
    answers = xfa_dataset_answers(path, limit=None)
    if not answers:
        return ""
    lines = [f"Readable export of the XFA form data in {Path(path).name}",
             "Generated by paper_docx_format.py xfa-export (the PDF's own text layer "
             "shows the Adobe placeholder outside Acrobat).", ""]
    for name, value in answers:
        lines.append(f"[{name}]")
        lines.append(value)
        lines.append("")
    return "\n".join(lines)


def _pdf_carries_an_image(path: Path) -> bool:
    """True when the PDF embeds an image (a text-less figure/scan is EXPECTED).

    `FMT-PDF3` exists for an export that lost its content, not for a figure
    saved as a PDF: the common case of a raster figure (or a scanned page) has
    no extractable text and is perfectly valid, so the check must not report it.
    Reads the object structure first, then looks for a JPEG/PNG stream when the
    object dictionary is compressed.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    if re.search(rb"/Subtype\s*/Image", data):
        return True
    for m in re.finditer(rb"(?<!end)stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        raw = data[start:end]
        if raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n":
            return True
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            continue
        if dec[:3] == b"\xff\xd8\xff" or dec[:8] == b"\x89PNG\r\n\x1a\n":
            return True
    return False


def pdf_artifact_rows(path: Path, text: str = None, pages=None) -> list:
    """FMT-PDF1..6 for one PDF (empty list = nothing proven wrong)."""
    rows = []
    name = Path(path).name
    if text is None:
        exe = shutil.which("pdftotext")
        if exe:
            try:
                proc = subprocess.run([exe, "-layout", str(path), "-"],
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=60)
                text = proc.stdout or ""
            except (OSError, subprocess.SubprocessError) as e:
                # The module's contract is to REPORT a row, never to raise out of
                # a scan; a stalled/failing pdftotext degrades exactly like the
                # "pdftotext not available" branch below (the sibling helpers
                # catch this same tuple).
                print(f"warning: pdftotext failed on {Path(path).name} "
                      f"({type(e).__name__}); the PDF's text layer was not read",
                      file=sys.stderr)
                text = ""
        else:
            text = ""
    body = (text or "").strip()
    is_xfa, non_empty, is_shell = _xfa_dataset_report(Path(path))
    pack = _xfa_packet_summary(Path(path)) if is_xfa else {}
    if pack.get("resolved"):
        # With the live packet known, the FILLED/UNFILLED question is decided by
        # the packet the AcroForm actually reads (`live_answers`), not by "some
        # packet somewhere has text".
        non_empty = int(pack.get("live_answers") or 0)
    strong = bool(PDF_PLACEHOLDER_STRONG_RE.search(body)) and len(body) < 1500
    if strong and not is_shell:
        # The bare "Please wait..." fallback must not flag ordinary prose. It
        # fires only for a document that is (or may be) a form: pdfinfo reported
        # one, or pdfinfo is unavailable to disprove it.
        form_line = _pdfinfo_form(Path(path))
        strong = form_line == "" or "none" not in form_line.lower()
    placeholder = bool(PDF_PLACEHOLDER_RE.search(body)) or strong or is_shell
    if placeholder:
        evidence = (f"rendered text is the Adobe placeholder ({len(body)} chars)"
                    if body else "the PDF's own streams carry the Adobe placeholder text")
        rows.append({"rule": "FMT-PDF1", "severity": "high", "document": name,
                     "location": "-",
                     "evidence": evidence,
                     "detail": "this PDF is a form SHELL: readers other than Adobe "
                               "Acrobat render only 'Please wait...', so any content it is "
                               "supposed to carry is invisible to the editor, the reviewer "
                               "and the submission system; flatten it before shipping",
                     "fix": "manual", "protected": False})
    if is_xfa and non_empty == 0:
        if pack.get("resolved") and int(pack.get("stale_answers") or 0) > 0:
            # The answers EXIST, but only in a packet set the /XFA array does not
            # name: no reader reaches them, and the form reads blank.
            rows.append({"rule": "FMT-PDF5", "severity": "high", "document": name,
                         "location": "-",
                         "evidence": f"the /XFA array names a dataset with 0 answers while the "
                                     f"file carries a SECOND (unreferenced) packet set with "
                                     f"{pack['stale_answers']} non-empty value(s)",
                         "detail": "the mandatory form's OWN data layer is EMPTY: the answers "
                                   "live in an unreferenced copy of the packet set that no "
                                   "reader, conversion or submission system resolves. Open the "
                                   "file in Adobe Acrobat, re-enter/confirm the answers and "
                                   "export a flattened PDF (the pipeline's `xfa-export` renders "
                                   "the unreferenced copy so nothing is lost in the meantime)",
                         "fix": "manual", "protected": False})
        else:
            rows.append({"rule": "FMT-PDF2", "severity": "high", "document": name,
                         "location": "-",
                         "evidence": "XFA/LiveCycle form whose dataset packet(s) carry no "
                                     "non-empty answer",
                         "detail": "the form ships UNFILLED (every field is empty or default); "
                                   "fill it in the Adobe reader (or replace it with a flattened "
                                   "PDF) before submitting",
                         "fix": "manual", "protected": False})
    elif is_xfa and non_empty > 0 and placeholder:
        # The form IS filled; the defect is only the delivery format. Reported
        # separately so the instruction is "flatten" (an export step), never
        # "fill" (which would overwrite real answers). `xfa-export` writes the
        # readable rendering this row's detail points at.
        rows.append({"rule": "FMT-PDF4", "severity": "high", "document": name,
                     "location": "-",
                     "evidence": f"XFA/LiveCycle form with {non_empty} non-empty answer(s) "
                                 f"but the placeholder is what a non-Acrobat reader shows",
                     "detail": "the mandatory form is FILLED but delivered as a shell: the "
                               "answers live only in the XFA data layer. Open it in Adobe "
                               "Acrobat Reader and export a flattened, text-readable PDF (the "
                               "pipeline's `xfa-export` writes a readable rendering of every "
                               "answer beside the package for reference)",
                     "fix": "manual", "protected": False})
        if pack.get("resolved") and int(pack.get("packets") or 0) > 1:
            # The file carries TWO packet sets. The live one is read here; a
            # strict XFA processor that takes the first shows the other, and the
            # 2026-10-15 audit of this very file read it as BLANK for that reason.
            rows.append({"rule": "FMT-PDF6", "severity": "medium", "document": name,
                         "location": "-",
                         "evidence": f"{pack['packets']} XFA packet set(s) in one file: the "
                                     f"/XFA array names the filled one "
                                     f"({pack.get('live_answers')} answer(s), object(s) "
                                     f"{pack.get('live_objects')}), and a stale copy with "
                                     f"{pack.get('stale_answers')} non-empty value(s) is still "
                                     f"in the file",
                         "detail": "this form was saved twice, so it carries an older and a "
                                   "newer packet set. A reader that resolves PDF objects "
                                   "strictly shows the answers; one that takes the first packet "
                                   "shows an empty form (that is how the same file reads as "
                                   "'blank' to a text tool or a strict XFA processor, including "
                                   "some editorial systems and the operator's own audit). "
                                   "Open it in Adobe Acrobat and use 'Save As' to write a "
                                   "single-set file, or export a flattened PDF "
                                   "(`xfa-export` renders the live answers for reference)",
                         "fix": "manual", "protected": False})
    elif not body and (pages or 0) >= 1 and not _pdf_carries_an_image(Path(path)):
        rows.append({"rule": "FMT-PDF3", "severity": "medium", "document": name,
                     "location": "-",
                     "evidence": f"{pages} page(s), no extractable text",
                     "detail": "the PDF carries no extractable text and no embedded image: "
                               "an empty export rather than a rendered document",
                     "fix": "manual", "protected": False})
    if body:
        note = pdf_production_note(body)
        if note:
            rows.append({"rule": "FMT-PDF7", "severity": "medium", "document": name,
                         "location": "-", "evidence": f"the opening text explains how the "
                         f"document was produced: {note!r}",
                         "detail": "a submitted document may not narrate its own PRODUCTION: "
                                   "this reads as an internal step note to a reviewer, and it "
                                   "tells the journal the file is a substitute for the "
                                   "document it asked for. Ship the document itself (the "
                                   "venue's own form where one was requested), or keep the "
                                   "explanatory note outside the submission.",
                         "fix": "manual", "protected": False})
    return rows


# FMT-PDF7 (2026-10-15): a submitted PDF whose OPENING text narrates how the file
# was produced. The CNB package shipped a rebuilt Reporting Summary whose first
# paragraph read "Reporting Summary Nature Portfolio life-sciences reporting
# summary: a static rendering of the form's own questions and the author's own
# answers, because the submitted PDF is an Adobe LiveCycle form whose static page
# shows only a viewer placeholder. Sections the form leaves empty are omitted."
# -- a reviewer's opening line was an explanation of the pipeline's substitute,
# and the round's own judge filed it (r1-D0016) while no delivered status line
# mentioned it. The match is deliberately narrow: a MANUSCRIPT never opens with
# these phrases, and the pattern is anchored to the first ~1200 characters so a
# Methods sentence about "the rendering pipeline" cannot trigger it.
PDF_PRODUCTION_NOTE_RE = re.compile(
    r"(?i)\b(?:a\s+)?static\s+rendering\s+of\s+the\s+form\b"
    r"|\bsubmitted\s+PDF\s+is\s+an?\s+(?:Adobe\s+)?(?:LiveCycle|XFA|AcroForm)\b"
    r"|\bviewer\s+placeholder\b"
    r"|\bsections\s+the\s+form\s+leaves\s+empty\s+are\s+omitted\b"
    r"|\brendering\s+of\s+the\s+form'?s\s+own\s+questions\b")


def pdf_production_note(text: str) -> str:
    """The FMT-PDF7 evidence string for a PDF's text ("" = no production note)."""
    head = str(text or "")[:1200]
    m = PDF_PRODUCTION_NOTE_RE.search(head)
    if not m:
        return ""
    return head[max(0, m.start() - 60):m.end() + 60].replace("\n", " ").strip()


def check_pdf(path: Path, policy: dict) -> dict:
    if not shutil.which("pdftotext"):
        return {"file": str(path), "pages": 0, "blank_pages": [], "ok": None,
                "rows": [{"rule": "FMT-S2", "severity": "low", "document": path.name,
                          "location": "-", "evidence": "pdftotext not available",
                          "detail": "cannot check pages for blankness", "fix": "manual",
                          "protected": False}]}
    try:
        proc = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        # A timeout/wedged child re-raised subprocess.TimeoutExpired straight out
        # of the scan (60 s in, on exactly the large or pathological PDF this
        # check exists for). Report it like any other unreadable input instead.
        return {"file": str(path), "pages": 0, "blank_pages": [], "ok": False,
                "rows": [{"rule": "FMT-S2", "severity": "high", "document": path.name,
                          "location": "-",
                          "evidence": f"pdftotext failed: {type(e).__name__}"
                                      + (f": {e}" if str(e) else ""),
                          "detail": "the PDF could not be read (pdftotext did not finish); "
                                    "no blank-page verdict is possible",
                          "fix": "manual", "protected": False}]}
    if proc.returncode != 0:
        # An unreadable/missing PDF yields empty text, which parses as 0 pages
        # and 0 blank pages: reporting that as clean is a false pass on the one
        # input the check must never pass.
        detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")[:200]
        return {"file": str(path), "pages": 0, "blank_pages": [], "ok": False,
                "rows": [{"rule": "FMT-S2", "severity": "high", "document": path.name,
                          "location": "-",
                          "evidence": f"pdftotext exited {proc.returncode}"
                                      + (f": {detail}" if detail else ""),
                          "detail": "the PDF could not be read; no blank-page verdict "
                                    "is possible",
                          "fix": "manual", "protected": False}]}
    txt = proc.stdout
    res = blank_pages_in_text(txt)
    blank = res["blank_pages"]
    rows = [{"rule": "FMT-S2", "severity": "high", "document": path.name,
             "location": f"page {i}", "evidence": "page carries no body text",
             "detail": "blank page in the rendered document (header/footer only)",
             # a PDF page is re-rendered, never patched in place: `_fix_kind`
             # classes FMT-S2 as manual, and a "mechanical" label here promised
             # a repair no tool can perform on the artifact
             "fix": "manual", "protected": False}
            for i in blank if len(blank) > policy["blank_page_tolerance"]]
    # The artifact checks (FMT-PDF1..3) run on the SAME extraction: a form shell
    # has one non-blank page and would otherwise pass as clean.
    rows.extend(pdf_artifact_rows(path, text=txt, pages=res["pages"]))
    return {"file": str(path), "pages": res["pages"], "blank_pages": blank,
            "furniture": res["furniture"][:5], "rows": rows,
            "ok": not rows}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _missing_paths(paths) -> list:
    """The paths the CALLER named that do not exist.

    `scan_paths`/`validate_paths` skip an absent path silently, which is right
    inside a directory walk but wrong for a path the operator typed: a typo
    printed "OOXML formatting: clean" / "validation: 0 file(s), 0 failure(s)"
    with exit 0, i.e. a check that read nothing reported a clean result
    (AGENTS.md: a skipped integrity check is reported as skipped).
    """
    return [str(p) for p in paths if not Path(p).exists()]


def cmd_scan(args) -> int:
    policy = load_policy(args.policy)
    missing = _missing_paths(args.paths)
    if missing:
        for m in missing:
            log(f"error: no such file or directory: {m}")
        return 2
    info = scan_paths([Path(p) for p in args.paths], policy)
    if args.pdf:
        pdf = check_pdf(Path(args.pdf), policy)
        info["pdf"] = pdf
        info["rows"].extend(pdf["rows"])
        info["by_rule"] = dict(Counter(r["rule"] for r in info["rows"]))
        for sev in ("high", "medium", "low"):
            info[sev] = sum(1 for r in info["rows"] if r["severity"] == sev)
    out = {"policy": policy, **info}
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(format_note(out))
    for r in out["rows"]:
        flag = " (field-protected)" if r.get("protected") else ""
        print(f"  [{r['severity']:6s}] {r['rule']:9s} {r['location']:>12s}  {r['evidence'][:100]}{flag}")
    return 1 if (args.strict and out["rows"]) else 0


def cmd_fix(args) -> int:
    policy = load_policy(args.policy)
    if getattr(args, "unlink_zotero_fields", False):
        # The explicit submission-copy opt-in (README's `--unlink-zotero-fields`):
        # the refresh runs first, then the fields are flattened to their correct
        # visible text. Refused (exit 1) when the refresh cannot make the
        # numbering clean -- flattening stale numbering freezes the wrong numbers.
        policy = dict(policy)
        policy["unlink_zotero_fields"] = True
    src, out = Path(args.file), Path(args.out)
    if src.resolve() == out.resolve():
        log("error: --out must differ from the input")
        return 2
    rep = fix_package(src, out, policy)
    if not rep.get("verified"):
        log(f"error: {rep.get('error') or 'the fix could not be verified'}")
        if args.json:
            Path(args.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
        return 1
    v = rep["verified"]
    # `ok: false` is a FAILURE (exit 1): the summary line must not read as a
    # success the exit code contradicts.
    head = "fixed" if rep["ok"] else "fix FAILED for"
    print(f"{head} {src.name} -> {out.name}: {len(rep['changes'])} change(s); "
          f"mechanical findings {v['mechanical_findings_before']} -> {v['mechanical_findings_after']}; "
          f"text identical={v['text_identical']}; parts intact={v['parts_intact']}; "
          f"schema={v['schema_detail']}")
    if not rep["ok"]:
        print(f"  the repaired file was NOT accepted: "
              f"{rep.get('error') or 'a verification check failed -- see the JSON report'}")
        # The rejected artifact must not sit at the requested --out path where a
        # caller (a script that ignores the exit code, a later run) reads it as a
        # good file: the fixer already wrote it there, so it is removed again.
        # The JSON report keeps the verification detail.
        try:
            out.unlink()
            print(f"  removed the rejected output {out.name}")
        except OSError as e:
            log(f"warning: could not remove the rejected output {out}: {e}")
    for c in rep["changes"]:
        print(f"  - {c}")
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if rep["ok"] else 1


def cmd_check_pdf(args) -> int:
    policy = load_policy(args.policy)
    res = check_pdf(Path(args.pdf), policy)
    print(f"{args.pdf}: {res['pages']} page(s); blank pages: {res['blank_pages'] or 'none'}")
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if res["ok"] is not False else 1


# Field-integrity faults that are Zotero's own shapes ("bad-citation-json", a
# Zotero field without its separate, a duplicate citationID, a stray Zotero
# instruction). `unclosed-field`/`duplicate-separate` can belong to ANY Word
# field, so they count only when their message names a Zotero field kind.
ZOTERO_FAULT_CODES = ("bad-citation-json", "no-separate", "duplicate-citation-id",
                      "zotero-instr-outside-field")
ZOTERO_FAULT_KIND_WORDS = ("the item field", "the bibliography field",
                           "the zotero-other field")


def zotero_structural_faults(report: dict) -> list:
    """The Zotero field-integrity errors of one `zotero_report_for_docx` report.

    A citation field whose instruction does not parse (or which has no
    separate, a duplicate citationID, an unclosed field) drops out of every
    FMT-Z rule, so the parity rows alone read "CLEAN" on a corrupt document.
    These are the faults `zotero-check` must report and fail on before an author
    flattens the fields.

    A multi-part inventory prefixes each message with its part
    ("word/footnotes.xml: [bad-citation-json] ..."), so the code is read after
    an optional part name: a document that carries footnotes.xml (every
    Word-produced file does) is otherwise declared clean again.
    """
    out = []
    for msg in report.get("errors") or []:
        # The part-name prefix can contain a space ("word/my notes.xml: ..."),
        # which `\S+:` could never span: the fault code read as "" and the row
        # was dropped, so `zotero-check` printed CLEAN (exit 0) on a broken
        # field -- the exact regression the multi-part prefix parse closed.
        m = re.match(r"(?:\S[^\n]*?: )?\[([a-z][a-z\-]*)\]", str(msg))
        code = m.group(1) if m else ""
        if code in ZOTERO_FAULT_CODES:
            out.append(str(msg))
        elif code in ("unclosed-field", "duplicate-separate") and \
                any(word in str(msg) for word in ZOTERO_FAULT_KIND_WORDS):
            out.append(str(msg))
    return out


def cmd_zotero_check(args) -> int:
    """`zotero-check`: what a Word/Zotero refresh would rewrite in this DOCX.

    Read-only and library-free: the citation fields embed their own itemData and
    the bibliography entries are ordinary paragraphs, so the check runs on any
    machine. Exit 1 when a high-severity row exists (FMT-Z1/Z2/Z4) -- i.e. the
    document's numbering is not the numbering a refresh produces -- or when a
    Zotero field itself is structurally broken (unparseable citation JSON, no
    separate, duplicate citationID, an unclosed field): such a field is absent
    from every numbering rule, so "no rows" would otherwise print CLEAN on a
    document whose citation cache cannot be trusted.
    """
    path = Path(args.file)
    try:
        with zipfile.ZipFile(path) as pkg:
            names = list(pkg.namelist())
            if "word/document.xml" not in names:
                raise KeyError("word/document.xml")
            # EVERY part that can hold fields, not just the main one: a
            # note-style manuscript keeps its citations in word/footnotes.xml
            # (or endnotes/header/footer/comments), and reading only
            # document.xml printed CLEAN, exit 0 for a document whose
            # footnotes a Word/Zotero refresh would rewrite.
            part_names = [n for n in names
                          if n in ZOTERO_FIELD_PARTS or ZOTERO_FIELD_AUX_PARTS_RE.search(n)]
            parts = [(n, pkg.read(n).decode("utf-8", "replace")) for n in part_names]
            # EVERY store the package-level scan reads, customXml payloads
            # included: the CLI printed "style store(s): ..." and CLEAN while a
            # third store in customXml/item<N>.xml was visible only to the
            # stage gate's scan.
            style_names = [n for n in ("word/settings.xml", "docProps/custom.xml")
                           if n in names]
            style_names += [n for n in names if re.match(r"customXml/item\d*\.xml$", n)]
            style_parts = {n: pkg.read(n).decode("utf-8", "replace")
                           for n in style_names}
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as e:
        print(f"[FAIL] {path}: unreadable DOCX ({type(e).__name__}: {e})")
        return 1
    xml = next(x for n, x in parts if n == "word/document.xml")
    paras = [text_of(p[2]) for p in paragraphs(xml)]
    styles = zotero_style_ids(style_parts)
    rows = zotero_parity_rows_for_parts(parts, styles)
    state = zotero_citation_state(xml, paras, styles)
    # ... over EVERY field-carrying part: the count beside the citation count
    # (itself package-wide) read only document.xml, so a note-style manuscript
    # printed "N citation(s); 0 distinct cited item(s)".
    distinct_items = len(zotero_package_order(parts))
    report = zotero_report_for_docx(path)
    faults = zotero_structural_faults(report)
    counts_report = report.get("counts") or state["report"]["counts"]
    counts = Counter(r["rule"] for r in rows)
    print(f"{path}")
    print(f"  live field(s): {counts_report.get('item', 0)} citation, "
          f"{counts_report.get('bibliography', 0)} bibliography; "
          f"{distinct_items} distinct cited item(s); "
          f"style store(s): {styles or 'none'}")
    if not rows and not faults:
        print("  CLEAN -- the markers, the bibliography order and the style store(s) agree; "
              "a Word/Zotero refresh reproduces this numbering")
    for fault in faults:
        print(f"  [field-integrity] {fault}")
    for r in rows:
        print(f"  [{r['rule']}] {r['severity']}: {r['evidence']}")
        print(f"      {r['detail']}")
    if faults:
        print(f"  {len(faults)} field-integrity fault(s): a field this broken is not "
              f"inventoried by the numbering rules; repair it in Word/Zotero and re-run "
              f"this check before flattening the fields")
    print(f"  {len(rows)} row(s): "
          + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"))
    if args.json:
        Path(args.json).write_text(json.dumps({"file": str(path), "rows": rows,
                                               "style_ids": styles,
                                               "counts": dict(counts),
                                               "field_integrity_faults": faults},
                                              indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if faults or any(r["severity"] == "high" for r in rows) else 0


def cmd_zotero_refresh(args) -> int:
    """`zotero-refresh`: repair the stale numbering/bibliography offline.

    The repair runs only when every field resolves and the result passes the
    same FMT-Z checks `zotero-check` runs; otherwise nothing is written and the
    reason is printed (exit 1). The NOTHING-TO-DO cases exit 0: "no live citation
    fields" (a document that carries no field to refresh) and the CLEAN document
    whose markers/bibliography already are what a refresh would write (the
    report carries `nothing_to_do: true`). `--out` writes a copy; without it the
    file is replaced in place (the pipeline's own callers do the same on a temp
    copy).
    """
    policy = load_policy(args.policy)
    if getattr(args, "unlink", False):
        # refresh → verify → unlink, as ONE fixer chain: the flatten is refused
        # whenever the refresh could not make the numbering clean.
        src = Path(args.file)
        dst = Path(args.out) if args.out else src
        tmp = dst.with_name(f".{dst.name}.zotunlink{os.getpid()}.tmp")
        upolicy = dict(policy)
        upolicy["unlink_zotero_fields"] = True
        rep = fix_package(src, tmp, upolicy)
        if not rep.get("ok"):
            with contextlib.suppress(OSError):
                tmp.unlink()
            print(f"  no change: {rep.get('error') or 'the fixer refused the chain'}")
            if args.json:
                Path(args.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
            return 1
        try:
            os.replace(tmp, dst)
        except OSError as e:                                            # noqa: BLE001
            with contextlib.suppress(OSError):
                tmp.unlink()
            print(f"  could not write {dst}: {e}")
            return 1
        v = rep.get("verified") or {}
        print(f"  unlinked: Zotero fields {v.get('zotero_fields_before', {}).get('zotero', '?')}"
              f" -> {v.get('zotero_fields_after', {}).get('zotero', '?')}"
              f" in {dst}")
        for line in rep.get("changes") or []:
            print(f"  [refresh] {line}")
        if args.json:
            Path(args.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
        return 0
    res = refresh_zotero_package(Path(args.file), args.out, policy)
    for line in res.get("changes") or []:
        print(f"  [refresh] {line}")
    zot = res.get("zotero") or {}
    if zot.get("fields_fixed"):
        print(f"  renumbered {zot['fields_fixed']} stale marker(s); "
              f"parity rows: {zot.get('rows_before')} -> {zot.get('rows_after')}")
    if not res.get("changed"):
        print(f"  no change: {res.get('skip') or 'nothing to repair'}")
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    # The docstring's contract: the repair runs only when every field resolves and
    # the result passes the FMT-Z checks; otherwise the reason is printed and the
    # exit status is 1. `ok=True, changed=False` with a recorded skip reason IS
    # that refusal (an unresolvable field, a non-numeric style, a rebuild it
    # declined), and returning 0 here let a caller gating on the exit status read
    # a refused/stale refresh as success. The NOTHING-TO-DO skips stay 0: "no
    # live citation fields" (no field exists to refresh) and a document the
    # refresh found ALREADY clean (`nothing_to_do`) -- a document that needs no
    # repair is a success, not a refusal, and a session that read the exit
    # status as "refused" would file a hand-off for correct numbering.
    refused = (bool(res.get("skip")) and not res.get("nothing_to_do")
               and str(res.get("skip")) != "no live citation fields")
    if not res.get("ok") or refused:
        return 1
    return 0


def cmd_xfa_export(args) -> int:
    """`xfa-export`: readable rendering of a filled XFA form PDF."""
    text = xfa_export_text(Path(args.file))
    if not text:
        print(f"{args.file}: no XFA dataset answers found (nothing to export)")
        return 1
    out = Path(args.out) if args.out else Path(args.file).with_suffix(".xfa-answers.txt")
    out.write_text(text, encoding="utf-8")
    print(f"{args.file}: answers rendered to {out}")
    return 0


def cmd_validate(args) -> int:
    missing = _missing_paths(args.paths)
    if missing:
        for m in missing:
            log(f"error: no such file or directory: {m}")
        return 2
    report = validate_paths([Path(p) for p in args.paths], Path(args.json) if args.json else None,
                            timeout=args.timeout)
    for r in report["results"]:
        mark = {True: "OK  ", False: "FAIL", None: "SKIP"}[r["ok"]]
        detail = r.get("detail") or ""
        if r["ok"] is False and r.get("errors"):
            detail = r["errors"][0]
        print(f"{mark} {r['kind']:4s} {r['file']}  {str(detail)[:140]}")
    print(f"validation: {report['files']} file(s), {report['failed']} failure(s)"
          + ("" if report["ok"] else " -- fix and re-run"))
    return 0 if report["ok"] else 1


def cmd_lookup(args) -> int:
    """`lookup [--kind KIND] Q`: resolve a searchable placeholder.

    Verdicts: found / absent (a verified negative) / error (never fatal).  The
    positional form `lookup "<title>"` still means a preprint search.
    """
    queries = [q for q in ([args.query] if args.query else []) + list(args.q or []) if q]
    if not queries:
        print("ERROR: give at least one query (positional or --q)", file=sys.stderr)
        return 2
    results = [lookup_kind(args.kind, q, timeout=args.timeout) for q in queries]
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    for res in results:
        print(f"[{res['kind']}] {res['query']!r} -> {res['verdict']} "
              f"({len(res['hits'])} hit(s))")
        for h in res["hits"]:
            print(f"  {h.get('source')}: {str(h.get('title'))[:90]} | "
                  f"{h.get('doi') or h.get('orcid') or h.get('sha') or ''} | "
                  f"{h.get('date') or ''}")
        for e in res["errors"]:
            print(f"  [warn] {e}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="report style/formatting findings")
    s.add_argument("paths", nargs="+")
    s.add_argument("--policy")
    s.add_argument("--json")
    s.add_argument("--pdf", help="also check a rendered PDF for blank pages")
    s.add_argument("--strict", action="store_true", help="exit 1 when any finding exists")
    s.set_defaults(func=cmd_scan)
    f = sub.add_parser("fix", help="write a fixed copy of one DOCX")
    f.add_argument("file")
    f.add_argument("--out", required=True)
    f.add_argument("--policy")
    f.add_argument("--unlink-zotero-fields", action="store_true",
                   help="also flatten the (refreshed) Zotero citations/bibliography to plain "
                        "text: the submission-copy policy. Refused when the offline refresh "
                        "cannot make the numbering clean first.")
    f.add_argument("--json")
    f.set_defaults(func=cmd_fix)
    p = sub.add_parser("check-pdf", help="blank-page check of a rendered PDF")
    p.add_argument("pdf")
    p.add_argument("--policy")
    p.add_argument("--json")
    p.set_defaults(func=cmd_check_pdf)
    z = sub.add_parser("zotero-check", help="what a Word/Zotero refresh would rewrite "
                                            "(stale markers, bibliography order, style stores)")
    z.add_argument("file")
    z.add_argument("--json")
    z.set_defaults(func=cmd_zotero_check)
    zr = sub.add_parser("zotero-refresh", help="repair stale Zotero numbering and the "
                                               "bibliography order offline (no Word/Zotero)")
    zr.add_argument("file")
    zr.add_argument("--out", help="output path (default: replace the file in place)")
    zr.add_argument("--policy")
    zr.add_argument("--unlink", action="store_true",
                    help="after the refresh, flatten the citation fields to plain text (the "
                         "submission copy; runs the full fixer chain so the ordering "
                         "refresh→verify→unlink is enforced)")
    zr.add_argument("--json")
    zr.set_defaults(func=cmd_zotero_refresh)
    xe = sub.add_parser("xfa-export", help="render a filled XFA form PDF's answers as "
                                           "readable text (the shell workaround)")
    xe.add_argument("file")
    xe.add_argument("--out")
    xe.set_defaults(func=cmd_xfa_export)
    v = sub.add_parser("validate", help="validate DOCX XML/schema and compile .tex files")
    v.add_argument("paths", nargs="+")
    v.add_argument("--json")
    v.add_argument("--timeout", type=int, default=300)
    v.set_defaults(func=cmd_validate)
    lk = sub.add_parser("lookup", help="resolve a searchable placeholder (preprint / DOI / "
                                       "accession / repository / archive / ORCID)")
    lk.add_argument("query", nargs="?", help="the query (default kind: preprint)")
    lk.add_argument("--q", action="append",
                    help="another query (repeatable; batch a whole placeholder list)")
    lk.add_argument("--kind", default="preprint",
                    choices=["preprint", "paper", "title", "doi", "accession", "repository",
                             "repo", "commit", "archive", "deposit", "orcid", "gene"])
    lk.add_argument("--json")
    lk.add_argument("--timeout", type=int, default=30)
    lk.set_defaults(func=cmd_lookup)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

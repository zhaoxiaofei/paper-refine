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

    python3 nbt_docx_format.py scan  PACKAGE_DIR [--pdf FILE.pdf] [--json OUT.json]
    python3 nbt_docx_format.py fix   FILE.docx --out FILE.fixed.docx [--json OUT.json]
    python3 nbt_docx_format.py check-pdf FILE.pdf
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
  every mechanical finding gone. Anything the fixer cannot repair is reported
  with `fix=style-field|policy|editorial|manual` instead of being "fixed" by
  guesswork.
* a finding inside a Zotero field (`w:fldChar begin ... end` + `ADDIN ZOTERO_*`
  instruction) is a field RESULT: Word cannot restyle it persistently because a
  refresh regenerates it. Such rows carry `protected=true`; the fix is the CSL
  style, or `unlink_zotero_fields: true` in the policy for a submission copy.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import unescape as xml_unescape

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

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
    "strip_proofing_markers": True,
    "unlink_zotero_fields": False,
    "blank_page_tolerance": 0,
}

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
TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?>.*?</w:t>", re.S)
RUN_RE = re.compile(r"<w:r(?=[\s/>]).*?</w:r>|<w:r(?=[\s/>])[^>]*/>", re.S)
FIELD_CHAR_RE = re.compile(r"<w:fldChar[^>]*w:fldCharType=\"(\w+)\"[^>]*/?>")
INSTR_RE = re.compile(r"<w:instrText(?:\s[^>]*)?>.*?</w:instrText>", re.S)
PROOFERR_RE = re.compile(r"<w:proofErr[^>]*/>")
DRAWING_RE = re.compile(r"<w:(?:drawing|pict|object|txbxContent)(?=[\s/>])")
PAGEBREAK_RE = re.compile(r"<w:br[^>]*w:type=\"page\"[^>]*/?>")
LEGEND_RE = re.compile(r"^\s*(?:Fig(?:ure)?\.?)\s*\d+\s*[|:.\u2014\u2013-]")
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
    literal made the punctuation rules blind to them.
    """
    text = xml_unescape(text or "")
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)


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
            depth -= 1
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
    return "".join(unesc(m.group(0)[m.group(0).find(">") + 1:m.group(0).rfind("<")])
                   for m in TEXT_RE.finditer(frag))


def has_drawing(frag: str) -> bool:
    return bool(DRAWING_RE.search(frag))


def ppr_of(frag: str) -> str | None:
    m = re.search(r"<w:pPr(?=[\s>]).*?</w:pPr>|<w:pPr(?=[\s>])[^>]*/>", frag, re.S)
    return m.group(0) if m else None


def rpr_of(frag: str) -> str | None:
    m = re.search(r"<w:rPr(?=[\s>]).*?</w:rPr>|<w:rPr(?=[\s>])[^>]*/>", frag, re.S)
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


def parse_styles(pkg: zipfile.ZipFile) -> dict:
    """styleId -> {sz, basedOn, type, spacing, i, iCs}.

    `i`/`iCs` are the OOXML tri-state toggles of the style's own rPr (True =
    italic, False = explicitly roman, None = inherited). They are what makes an
    italic that lives in a CHARACTER STYLE (`w:rStyle w:val="Emphasis"`) or in a
    paragraph style visible: a run can be italic without carrying `<w:i/>`
    itself, and only checking the run's direct rPr misses it.
    """
    out = {}
    if "word/styles.xml" not in pkg.namelist():
        return out
    root = ET.fromstring(pkg.read("word/styles.xml"))
    defaults = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
    if defaults is not None:
        out["@docDefaults"] = {"i": _tri_state(defaults.find(W + "i")),
                               "iCs": _tri_state(defaults.find(W + "iCs"))}
    for st in root.iter(W + "style"):
        sid = st.get(W + "styleId") or ""
        rpr, ppr = st.find(W + "rPr"), st.find(W + "pPr")
        base = st.find(W + "basedOn")
        out[sid] = {
            "sz": (rpr.find(W + "sz").get(W + "val")
                   if rpr is not None and rpr.find(W + "sz") is not None else None),
            "i": _tri_state(rpr.find(W + "i")) if rpr is not None else None,
            "iCs": _tri_state(rpr.find(W + "iCs")) if rpr is not None else None,
            "basedOn": base.get(W + "val") if base is not None else None,
            "type": st.get(W + "type") or "",
            "spacing": (ppr.find(W + "spacing") if ppr is not None else None),
        }
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
NUMBER_RE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w])")

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
        for m in NUMBER_RE.finditer(text):
            sentence = next((s for s in sentences if m.group(0) in s), text)
            rows.append({"document_paragraph": i, "number": m.group(0),
                         "thousands_separated": "," in m.group(0),
                         "unit": (UNIT_RE.match(text[m.end():]).group(0).strip()
                                  if UNIT_RE.match(text[m.end():]) else None),
                         "sentence": sentence.strip()[:200], "source": ""})
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
        pattern = re.compile(rf"\b{re.escape(term.strip())}\w*", re.I)
        hits = [(i, t) for i, t in enumerate(paras) if pattern.search(t)]
        if not hits:
            continue
        ctx = pattern.search(hits[0][1])
        s = ctx.start() if ctx else 0
        rows.append({"term": term.strip(), "count": len(hits),
                     "first_paragraph": hits[0][0],
                     "first_context": hits[0][1][max(0, s - 60):s + 60].strip(),
                     "variant": ""})
    return rows


def long_text_rows(paras: list, is_ref: list = None, kinds: list = None) -> list:
    """FMT-T9c (long sentence), FMT-T9c/T9i (list paragraph / mega paragraph).

    The sentence bar is section-aware (LONG_SENTENCE_BARS): 40 words in an
    abstract, a cover letter or a legend; 46 in the body; 61 in Methods.  Every
    row carries its `tier`, and the strict sections are finding-tier, so the
    review can no longer close them with "no journal rule".
    """
    rows, is_ref = [], list(is_ref or [False] * len(paras))
    kinds = list(kinds) if kinds else section_kinds(paras)
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
        elif words > 250 and kind != "methods":
            rows.append({"rule": "FMT-T9i", "severity": "low", "tier": "finding",
                         "evidence": f"paragraph {i} is {words} words long ({kind})",
                         "detail": "a paragraph this long carries several messages: split it "
                                   "at the natural boundary so each paragraph makes one point",
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
            url, headers=headers or {"User-Agent": "nbt-pipeline/3.5 (identifier lookup)"})
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
            msg = json.loads(fetch("https://api.crossref.org/works/"
                                   + urllib.parse.quote(doi)
                                   + "?mailto=nbt-pipeline@example.org"))["message"]
            out["hits"] = [{"source": "crossref",
                            "title": (msg.get("title") or [""])[0],
                            "doi": msg.get("DOI"),
                            "date": ((msg.get("issued", {}).get("date-parts")
                                      or [[None]])[0] or [None])[0]}]
            out["verdict"] = "found"
        elif kind == "accession":
            d = json.loads(fetch("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
                                 "?db=sra&retmode=json&term=" + q))
            n = int((d.get("esearchresult") or {}).get("count") or 0)
            if n:
                out["hits"] = [{"source": "ncbi-sra", "count": n, "title": str(query)}]
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
                                 headers={"User-Agent": "nbt-pipeline/3.5",
                                          "Accept": "application/vnd.github+json"}))
            if isinstance(d, dict) and d.get("full_name") and not d.get("message"):
                out["hits"] = [{"source": "github", "title": d.get("full_name"),
                                "date": d.get("pushed_at"), "private": bool(d.get("private")),
                                "license": (d.get("license") or {}).get("spdx_id")}]
                out["verdict"] = "absent" if d.get("private") else "found"
            else:
                out["verdict"] = "absent"
            m = re.search(r"/(?:tree|commit)/([0-9a-fA-F]{7,40})", str(query))
            if m:
                sha = m.group(1)
                cd = json.loads(fetch(
                    f"https://api.github.com/repos/{parts[0]}/{parts[1]}/commits/{sha}",
                    headers={"User-Agent": "nbt-pipeline/3.5",
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
                                 headers={"User-Agent": "nbt-pipeline/3.5",
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
                                 headers={"User-Agent": "nbt-pipeline/3.5",
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
        lines = [l for l in str(text).splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        delim = ("\t" if "\t" in lines[0] else
                 ("|" if lines[0].count("|") >= 2 else
                  ("," if lines[0].count(",") >= 1 else None)))
        if delim is None:
            continue
        header = [c.strip() for c in lines[0].split(delim)]
        body = [[c.strip() for c in l.split(delim)] for l in lines[1:]]
        if len(header) < 2 or not body:
            continue
        for c in range(min(len(header), max(len(r) for r in body))):
            vals = []
            for r in body:
                if c >= len(r):
                    continue
                v = r[c].replace(",", "").replace("$", "").replace("%", "").strip()
                if v.lower() in ("", "nan", "na", "n/a", "-"):
                    continue
                try:
                    fv = float(v)
                except ValueError:
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
                                   "a proper name three or more times in one paragraph -- a "
                                   "journal name above all -- reads as padding, and it is a "
                                   "writing-quality defect even when no journal rule names it",
                         "protected": False})
    return rows


def variant_rows(paras: list, is_ref: list) -> list:
    """FMT-T8d (US/UK spelling) and FMT-T8e (attributive hyphenation)."""
    rows = []
    prose = [(i, t) for i, t in enumerate(paras)
             if not (i < len(is_ref) and is_ref[i])]
    for a, b in SPELLING_PAIRS:
        ca = sum(len(re.findall(rf"\b{re.escape(a)}\b", t, re.I)) for _i, t in prose)
        cb = sum(len(re.findall(rf"\b{re.escape(b)}\b", t, re.I)) for _i, t in prose)
        if ca and cb:
            rows.append({"rule": "FMT-T8d", "severity": "medium",
                         "evidence": f"spelling variants in body text: {a!r} x{ca} and "
                                     f"{b!r} x{cb}",
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


def text_style_rows(paras: list, is_ref: list = None, headings: list = None) -> list:
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
    rows += long_text_rows(paras, is_ref, section_kinds(paras, headings))
    rows += self_gloss_rows(paras, is_ref)
    rows += confusable_pair_rows(prose)
    rows += concept_family_rows(paras, is_ref)
    rows += number_format_rows(prose)
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
    """
    frags = _text_fragments(para)
    text = "".join(f[2] for f in frags)
    edits = sorted((s, e, r) for s, e, r in edits if 0 <= s <= e <= len(text) and (e > s or r))
    if not edits:
        return para, []
    applied = [(s, e, text[s:e], r) for s, e, r in edits]
    keep, pos = [], 0
    for s, e, _r in edits:
        keep.append((pos, s, None))
        keep.append((s, e, _r))
        pos = e
    keep.append((pos, len(text), None))
    pieces, cursor, offset = [], 0, 0
    for start, end, old, raw in frags:
        pieces.append(para[cursor:start])
        local = offset
        buf = []
        for a, b, repl in keep:
            if b <= local or a >= local + len(old):
                continue
            if repl is not None:                       # replacement at its start run
                if local <= a < local + len(old):
                    buf.append(repl)
            else:
                buf.append(old[max(a - local, 0):max(min(b - local, len(old)), 0)])
        new_text = "".join(buf)
        open_tag = raw[:raw.find(">") + 1]
        close_tag = raw[raw.rfind("<"):]
        keep_space = ' xml:space="preserve"' if (new_text != new_text.strip()
                                                 or "xml:space" in open_tag) else ""
        tag = "<w:t" + keep_space + ">"
        pieces.append(tag + esc(new_text) + close_tag if new_text else tag + close_tag)
        cursor = end
        offset += len(old)
    pieces.append(para[cursor:])
    new_para = "".join(pieces)

    def _drop_empty_runs(mm):
        body = mm.group(0)
        if re.search(r"<w:(?:drawing|pict|object|br|tab|fldChar|instrText|noBreakHyphen|sym)",
                     body):
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
    if rule in ("FMT-S1", "FMT-T2a", "FMT-T2b", "FMT-T3a"):
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
    return "editorial"


MECHANICAL_RULES = {"FMT-S1", "FMT-S3", "FMT-S5", "FMT-T1", "FMT-T2a", "FMT-T2b",
                    "FMT-T3a", "FMT-T3b", "FMT-T6a", "FMT-T6b", "FMT-T6c", "FMT-T6f",
                    "FMT-T6g", "FMT-T7a", "FMT-T7b", "FMT-T8a", "FMT-T8d", "FMT-T8e"}


def analyse_document(xml: str, styles: dict, policy: dict, doc: str) -> dict:
    rows = []
    paras = paragraphs(xml)
    franges = field_ranges(xml)

    def row(rule, severity, location, evidence, detail, protected=False):
        # A finding inside a Zotero field is reported, never silently edited --
        # the fix kind has to say so, or the fixer's "all mechanical findings
        # resolved" verification would fail on a row it is not allowed to touch.
        fix = _fix_kind(rule, policy)
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
        empty = not text.strip() and not has_drawing(para)
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

    run_len, run_start = 0, None
    for idx in range(len(paras) + 1):
        if idx < len(paras):
            _, _, para = paras[idx]
            empty = not text_of(para).strip() and not has_drawing(para)
        else:
            empty = False
        if empty:
            run_len += 1
            run_start = idx if run_start is None else run_start
        else:
            if run_len > policy["max_empty_paragraph_run"] and run_start is not None:
                row("FMT-S6", "low", f"p{run_start}-p{run_start + run_len - 1}",
                    f"{run_len} consecutive empty paragraphs",
                    "stray empty paragraphs shift pagination and create blank space")
            run_len, run_start = 0, None

    # ---- legends --------------------------------------------------------------
    legend_idx = [i for i, (_, _, p) in enumerate(paras) if LEGEND_RE.match(text_of(p))]
    for i in legend_idx:
        para = paras[i][2]
        sp = elem(ppr_of(para), "spacing")
        line, before, after = attr(sp, "line"), attr(sp, "before"), attr(sp, "after")
        if line != str(policy["caption_line"]):
            row("FMT-T2a", "medium", f"p{i}",
                f"legend line spacing {line or 'inherit'} != {policy['caption_line']} (single)",
                "figure legends must be single-spaced")
        if before != str(policy["caption_space"]) or after != str(policy["caption_space"]):
            row("FMT-T2b", "low", f"p{i}",
                f"legend spacing before={before} after={after} != {policy['caption_space']}",
                "legend paragraph spacing differs between figures")

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
                 elem_val(rpr, "u") or "-",
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
    for label, n in (("double spaces", len(re.findall(r"\S {2,}\S", full))),
                     ("space before punctuation", len(re.findall(r"\s+[,.;:!?]", full))),
                     ("zero-width/bidi marks", len(re.findall("[\u200b\u200e\u200f\ufeff]", full)))):
        if n:
            row("FMT-P3", "low", "document", f"{n} {label}", "text hygiene", )

    # ---- header / title page / tracked changes --------------------------------
    if re.search(r"<w:headerReference", xml) and "<w:titlePg" not in xml \
            and policy["title_page_header"] == "suppress":
        row("FMT-S3", "low", "document", "the running head is printed on the title page",
            "add w:titlePg to the section properties so page 1 carries no header")
    n_ins = len(re.findall(r"<w:ins(?=[\s/>])", xml))
    n_del = len(re.findall(r"<w:del(?=[\s/>])", xml))
    if n_ins or n_del:
        row("FMT-S4", "high", "document", f"tracked changes present: {n_ins} ins / {n_del} del",
            "a final package must not carry revision marks; accept or reject them first")
    n_proof = len(PROOFERR_RE.findall(xml))
    if n_proof:
        row("FMT-S5", "low", "document", f"{n_proof} proofing marker(s) (w:proofErr)",
            "the file was last saved with unaccepted spelling/grammar marks")
    n_tabs = len(re.findall(r"<w:tab[^>]*/>", xml)) + full.count("\t")
    if n_tabs:
        row("FMT-S7", "low", "document", f"{n_tabs} literal tab character(s)",
            "tabs used for layout; prefer paragraph indentation/spacing")

    # ---- text-level style & consistency (FMT-T8a..FMT-T8e) --------------------
    # Citation formats, nested parentheses, redundant repetition and term variants
    # are document-TEXT problems: they are read from the paragraph text so the same
    # rules can also run over the LaTeX/markdown sources (nbt_pipeline scans those).
    para_texts = [text_of(p[2]) for p in paras]
    para_is_ref = [elem_val(ppr_of(p[2]), "pStyle") == "Bibliography" for p in paras]
    para_is_head = [bool((elem_val(ppr_of(p[2]), "pStyle") or "").startswith("Heading"))
                    for p in paras]
    for r in text_style_rows(para_texts, para_is_ref, para_is_head):
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

    return {"rows": rows, "paras": len(paras), "words": words, "legend_idx": legend_idx,
            "fields": [f[2][:60] for f in franges],
            "style_survey": style_survey(xml, styles),
            "treatments": {k: sorted(v) for k, v in treatments.items()},
            "title_block_end": title_block_end}


def analyse_package(path: Path, policy: dict) -> dict:
    try:
        with zipfile.ZipFile(path) as pkg:
            styles = parse_styles(pkg)
            xml = pkg.read("word/document.xml").decode("utf-8")
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        row = {"rule": "FMT-X1", "severity": "high", "document": path.name, "location": "-",
               "evidence": f"{type(e).__name__}: {e}", "detail": "unreadable DOCX package",
               "fix": "manual", "protected": False}
        return {"file": str(path), "rows": [row], "by_rule": {"FMT-X1": 1},
                "high": 1, "medium": 0, "low": 0, "documents": {}}
    res = analyse_document(xml, styles, policy, path.name)
    counts = Counter(r["rule"] for r in res["rows"])
    return {"file": str(path), "rows": res["rows"], "by_rule": dict(counts),
            "high": sum(1 for r in res["rows"] if r["severity"] == "high"),
            "medium": sum(1 for r in res["rows"] if r["severity"] == "medium"),
            "low": sum(1 for r in res["rows"] if r["severity"] == "low"),
            "documents": {path.name: res}}


def scan_paths(paths: list, policy: dict) -> dict:
    """Scan the corpus documents under `paths`.

    Revision-skill auxiliaries (`*.tracked.docx`, `*.before-after.docx`) and the
    stage scratch under any `work/` directory are NOT corpus content (the
    pipeline strips both from every judged/pinned corpus), so they are skipped:
    scanning them inflated one real sandbox report to 971 findings and hid the
    signal. Use `include_scratch=True` to look at them anyway.
    """
    docs = []
    for p in paths:
        if not p.exists():
            continue
        files = sorted(p.rglob("*.docx")) if p.is_dir() else [p]
        for f in files:
            if f.name.startswith("~$") or f.name.lower().endswith(
                    (".tracked.docx", ".before-after.docx")):
                continue
            if any(part == "work" for part in f.parts[:-1]):
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


def insert_into_ppr(para: str, element: str, after=("pStyle", "keepNext", "keepLines")) -> str:
    ppr = ppr_of(para)
    if ppr is None:
        tag_end = para.find(">") + 1
        return para[:tag_end] + "<w:pPr>" + element + "</w:pPr>" + para[tag_end:]
    pos = 0
    for tag in after:
        m = re.search(rf"<w:{tag}(?=[\s/>])[^>]*/>|<w:{tag}(?=[\s/>])[^>]*>.*?</w:{tag}>", ppr, re.S)
        if m:
            pos = max(pos, m.end())
    if pos == 0:
        pos = len("<w:pPr>")
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


def fix_document(xml: str, styles: dict, policy: dict) -> tuple:
    """(new_xml, changes) — byte-level edits; rules run in dependency order."""
    changes = []

    # 1. unlink fields first, so run-level fixes stick ---------------------------
    if policy["unlink_zotero_fields"]:
        xml, removed = _unlink_fields(xml)
        if removed:
            changes.append(f"unlinked {removed} field run(s): Zotero citations/bibliography "
                           f"are now plain text (refreshable in the Zotero copy only)")

    # 2. break-only empty paragraph -> pageBreakBefore on the next paragraph ----
    for _ in range(50):
        plist = paragraphs(xml)
        target = None
        for idx, (p0, p1, para) in enumerate(plist):
            if PAGEBREAK_RE.search(para) and not text_of(para).strip() and not has_drawing(para):
                target = (idx, p0, p1, para)
                break
        if target is None:
            break
        idx, p0, p1, para = target
        edits = [(p0, p1, "")]
        if idx + 1 < len(plist):
            np0, np1, npara = plist[idx + 1]
            edits.append((np0, np1, insert_into_ppr(npara, "<w:pageBreakBefore/>")))
            changes.append(f"moved the page break onto the following paragraph (was the empty p{idx})")
        else:
            changes.append(f"removed the trailing break-only paragraph p{idx}")
        xml = apply_edits(xml, edits)

    # 3. legend spacing ----------------------------------------------------------
    want_sp = (f'<w:spacing w:before="{policy["caption_space"]}" '
               f'w:after="{policy["caption_space"]}" w:line="{policy["caption_line"]}" '
               f'w:lineRule="auto"/>')
    edits, n = [], 0
    for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
        if not LEGEND_RE.match(text_of(para)):
            continue
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
            edits.append((p0, p1, insert_into_ppr(para, want_sp)))
            n += 1
    if edits:
        xml = apply_edits(xml, edits)
        changes.append(f"unified figure-legend spacing on {n} legend(s) "
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
                        new_run = run.replace(rpr, re.sub(r"<w:sz[^>]*/>", "", rpr), 1)
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
    if policy["title_page_header"] == "suppress" and "<w:headerReference" in xml \
            and "<w:titlePg" not in xml:
        sects = list(re.finditer(r"<w:sectPr(?=[\s>]).*?</w:sectPr>", xml, re.S))
        if sects:
            s = sects[-1]
            at = s.start() + s.group(0).find("</w:sectPr>")
            for tag in ("docGrid", "printerSettings"):
                t = s.group(0).find(f"<w:{tag}")
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
                    edits.append((p0 + r0, p0 + r1, run.replace(rpr, re.sub(r"<w:i(?:Cs)?[^>]*/>", "", rpr), 1)))
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
        def conv(mm):
            raw = mm.group(0)
            open_tag = raw[:raw.find(">") + 1]
            close_tag = raw[raw.rfind("<"):]
            text = unesc(raw[raw.find(">") + 1:raw.rfind("<")])
            if policy["quote_style"] == "curly":
                text = re.sub(r"(?<=\w)'(?=\w)", "\u2019", text)
                out, open_dq = [], True
                for ch in text:
                    if ch == '"':
                        out.append("\u201c" if open_dq else "\u201d")
                        open_dq = not open_dq
                    elif ch == "'":
                        out.append("\u2018" if open_dq else "\u2019")
                    else:
                        out.append(ch)
                text = "".join(out)
            else:
                text = (text.replace("\u2019", "'").replace("\u2018", "'")
                        .replace("\u201c", '"').replace("\u201d", '"'))
            return open_tag + esc(text) + close_tag
        new = TEXT_RE.sub(conv, xml)
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
    text_edits, cit_n, spell_n, hy_n = [], 0, 0, 0
    want_cit = policy["citation_journal_names"] == "drop"
    want_spell = policy["term_spelling"] == "dominant"
    want_hy = policy["term_hyphenation"] == "dominant"
    if want_cit or want_spell or want_hy:
        bodies = []
        for idx, (p0, p1, para) in enumerate(paragraphs(xml)):
            if elem_val(ppr_of(para), "pStyle") == "Bibliography":
                continue
            bodies.append((idx, p0, p1, para, text_of(para)))
        blob = "\n".join(b[4] for b in bodies)
        spell_target = {}
        if want_spell:
            for a, b in SPELLING_PAIRS:
                ca = len(re.findall(rf"\b{re.escape(a)}\b", blob, re.I))
                cb = len(re.findall(rf"\b{re.escape(b)}\b", blob, re.I))
                if ca and cb:
                    spell_target[a if ca < cb else b] = a if ca > cb else b
        hy_target = set()
        if want_hy:
            for hy, split in HYPHEN_COMPOUNDS:
                if re.search(rf"\b{re.escape(hy)}(?=\s+[A-Za-z])", blob):
                    hy_target.add((hy, split))
        edits = []
        for idx, p0, p1, para, text in bodies:
            spans = []
            if want_cit:
                for m in CIT_YEAR_JOURNAL.finditer(text):
                    spans.append((m.end(2), m.end(3), ""))
                for m in CIT_JOURNAL_YEAR.finditer(text):
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
            for s, e, removed, repl in applied:
                text_edits.append((idx, s, e, repl))
                if repl == "":
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
            if bits:
                changes.append("text consistency: " + "; ".join(bits))

    return xml, changes, {"text_edits": text_edits}


def fix_package(src: Path, out: Path, policy: dict) -> dict:
    with zipfile.ZipFile(src) as pkg:
        parts = {i.filename: pkg.read(i.filename) for i in pkg.infolist()}
        styles = parse_styles(pkg)
    xml_before = parts["word/document.xml"].decode("utf-8")
    xml_after, changes, meta = fix_document(xml_before, styles, policy)
    parts_new = dict(parts)
    parts_new["word/document.xml"] = xml_after.encode("utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts_new.items():
            z.writestr(name, data)

    # Text identity is about the DOCUMENT TEXT, not about paragraph count: a
    # fix may delete an empty paragraph or split a run, which changes the
    # newline count but not a single character of text.
    text_before = "\n".join(t for t in (text_of(p[2]) for p in paragraphs(xml_before)) if t.strip())
    text_after = "\n".join(t for t in (text_of(p[2]) for p in paragraphs(xml_after)) if t.strip())
    quote_free = lambda s: re.sub(r"[\"'\u2018\u2019\u201c\u201d]", "", s)
    # The recorded text edits (citation journals, spelling, hyphenation) are the
    # only allowed text differences; rebuild the expected text by applying them to
    # the ORIGINAL paragraph texts (descending offsets, so they stay valid).
    before_paras = [text_of(p[2]) for p in paragraphs(xml_before)]
    expected_paras = list(before_paras)
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
    before_rows = analyse_document(xml_before, styles, policy, src.name)["rows"]
    after_rows = analyse_document(xml_after, styles_after, policy, src.name)["rows"]
    mech_before = {r["rule"] for r in before_rows if r["rule"] in MECHANICAL_RULES and r["fix"] == "mechanical"}
    mech_after = {r["rule"] for r in after_rows if r["fix"] == "mechanical"}
    remaining = sorted(mech_before & mech_after)
    schema = validate_package(out)
    verified = {
        "zip_readable": True,
        "parts_intact": same_parts,
        "text_identical": text_before == text_after,
        "text_diff_only_quotes": quote_free(text_before) == quote_free(text_after),
        "text_diff_only_recorded_edits": text_after == text_expected,
        "text_edits": len(meta.get("text_edits") or []),
        "mechanical_findings_before": len([r for r in before_rows if r["fix"] == "mechanical"]),
        "mechanical_findings_after": len([r for r in after_rows if r["fix"] == "mechanical"]),
        "remaining_mechanical_rules": remaining,
        "schema_ok": schema[0], "schema_detail": schema[1],
    }
    ok = bool(same_parts
              and (verified["text_identical"] or verified["text_diff_only_quotes"]
                   or verified["text_diff_only_recorded_edits"])
              and not remaining
              and schema[0] is not False)
    return {"source": str(src), "output": str(out), "changes": changes, "verified": verified, "ok": ok}


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
                except OSError as e:                              # noqa: PERF203
                    errs.append(f"{name}: unreadable ({e})")
    except (zipfile.BadZipFile, OSError) as e:
        errs.append(f"not a readable .docx zip ({type(e).__name__}: {e})")
    schema_ok, schema_detail = validate_package(path)
    if schema_ok is False:
        errs.append(f"schema check failed: {schema_detail}")
    return {"file": str(path), "kind": "docx", "ok": not errs, "errors": errs,
            "schema_ok": schema_ok, "detail": schema_detail if schema_ok is None else "valid"}


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
    scratch = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="nbt_tex_check_"))
    try:
        target_dir = scratch / path.parent.name if not workdir else scratch
        if not target_dir.is_dir():
            shutil.copytree(path.parent, target_dir,
                            ignore=shutil.ignore_patterns("work", "*.tracked.docx"))
        proc = subprocess.run(argv + [path.name], cwd=str(target_dir),
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError, shutil.Error) as e:
        return {"file": str(path), "kind": "tex", "ok": False, "engine": name,
                "errors": [f"{type(e).__name__}: {e}"], "detail": "the compile step itself failed"}
    out = (proc.stdout or "") + (proc.stderr or "")
    errors = [ln.strip() for ln in out.splitlines() if ln.startswith("!")][:5]
    return {"file": str(path), "kind": "tex", "ok": proc.returncode == 0, "engine": name,
            "errors": errors, "detail": (errors[0] if errors else
                                         ("compiled" if proc.returncode == 0
                                          else f"engine exited {proc.returncode}"))}


def validate_paths(paths: list, json_out: Path = None, timeout: int = 300) -> dict:
    """Validate every DOCX (XML/schema) and .tex (compile) under `paths`."""
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += [q for q in sorted(p.rglob("*.docx"))
                      if not q.name.startswith("~$") and not _is_aux_name(q.name)]
            files += sorted(p.rglob("*.tex")) + sorted(p.rglob("*.ltx"))
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
    low = name.lower()
    return low.endswith((".tracked.docx", ".before-after.docx"))


def check_pdf(path: Path, policy: dict) -> dict:
    if not shutil.which("pdftotext"):
        return {"file": str(path), "pages": 0, "blank_pages": [], "ok": None,
                "rows": [{"rule": "FMT-S2", "severity": "low", "document": path.name,
                          "location": "-", "evidence": "pdftotext not available",
                          "detail": "cannot check pages for blankness", "fix": "manual",
                          "protected": False}]}
    txt = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                         capture_output=True, text=True).stdout
    res = blank_pages_in_text(txt)
    blank = res["blank_pages"]
    rows = [{"rule": "FMT-S2", "severity": "high", "document": path.name,
             "location": f"page {i}", "evidence": "page carries no body text",
             "detail": "blank page in the rendered document (header/footer only)",
             "fix": "mechanical", "protected": False}
            for i in blank if len(blank) > policy["blank_page_tolerance"]]
    return {"file": str(path), "pages": res["pages"], "blank_pages": blank,
            "furniture": res["furniture"][:5], "rows": rows,
            "ok": not rows}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_scan(args) -> int:
    policy = load_policy(args.policy)
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
    src, out = Path(args.file), Path(args.out)
    if src.resolve() == out.resolve():
        log("error: --out must differ from the input")
        return 2
    rep = fix_package(src, out, policy)
    v = rep["verified"]
    print(f"fixed {src.name} -> {out.name}: {len(rep['changes'])} change(s); "
          f"mechanical findings {v['mechanical_findings_before']} -> {v['mechanical_findings_after']}; "
          f"text identical={v['text_identical']}; parts intact={v['parts_intact']}; "
          f"schema={v['schema_detail']}")
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


def cmd_validate(args) -> int:
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
    """`lookup --kind KIND --query Q`: resolve a searchable placeholder.

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
    f.add_argument("--json")
    f.set_defaults(func=cmd_fix)
    p = sub.add_parser("check-pdf", help="blank-page check of a rendered PDF")
    p.add_argument("pdf")
    p.add_argument("--policy")
    p.add_argument("--json")
    p.set_defaults(func=cmd_check_pdf)
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
                             "repo", "commit", "archive", "deposit", "orcid"])
    lk.add_argument("--json")
    lk.add_argument("--timeout", type=int, default=30)
    lk.set_defaults(func=cmd_lookup)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

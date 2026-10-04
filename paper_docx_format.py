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
"""
from __future__ import annotations

import argparse
import json
import posixpath
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

# A corpus's read-only EVIDENCE areas (`raw_data/`, legacy spelling `raw_figs/`,
# and the human editors'/reviewers' feedback): never submission content, never a
# formatting/validation target.
RAW_DATA_DIRNAMES = ("raw_data", "raw_figs")
HUMAN_FEEDBACK_DIR = "human_review_feedback"
EVIDENCE_DIRNAMES = RAW_DATA_DIRNAMES + (HUMAN_FEEDBACK_DIR,)

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
    # The venue's TABLE rule (see DISPLAY_PLACEMENTS / display_item_rows):
    # {} = this format policy declares no table rule, so the scan reports none.
    "tables": {},
    # The venue's FIGURE rule (see display_item_rows / FIGURE_CAPTION_RE): {} =
    # this format policy declares no figure rule, so the scan reports none.
    "figures": {},
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
# The BODY walker's tokens: the two block-level children of `<w:body>` a table
# rule has to see in DOCUMENT ORDER (a `w:p` holds no `w:tbl`, and a nested
# table inside a cell is part of its outer table).
BODY_BLOCK_TOKENS = re.compile(r"<w:(p|tbl)(?=[\s/>])")
ROW_TOKENS = re.compile(r"<w:tr(?=[\s/>])|</w:tr>")
CELL_TOKENS = re.compile(r"<w:tc(?=[\s/>])|</w:tc>")
TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?>.*?</w:t>", re.S)
RUN_RE = re.compile(r"<w:r(?=[\s/>]).*?</w:r>|<w:r(?=[\s/>])[^>]*/>", re.S)
FIELD_CHAR_RE = re.compile(r"<w:fldChar[^>]*w:fldCharType=\"(\w+)\"[^>]*/?>")
INSTR_RE = re.compile(r"<w:instrText(?:\s[^>]*)?>.*?</w:instrText>", re.S)
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
    return "".join(unesc(m.group(0)[m.group(0).find(">") + 1:m.group(0).rfind("<")])
                   for m in TEXT_RE.finditer(frag))


def has_drawing(frag: str) -> bool:
    return bool(DRAWING_RE.search(frag))


def ppr_of(frag: str) -> str | None:
    m = re.search(r"<w:pPr(?=[\s>]).*?</w:pPr>|<w:pPr(?=[\s>])[^>]*/>", frag, re.S)
    return m.group(0) if m else None


def first_section_props(xml: str) -> str | None:
    """The FIRST `w:sectPr` in document order: the section that governs page 1.

    A manuscript with a separate title-page section carries one `w:sectPr` at
    the end of that section and the body's own at the end of `w:body`; the
    title page's header comes from the FIRST one, never the last.
    """
    m = re.search(r"<w:sectPr(?=[\s>]).*?</w:sectPr>", xml, re.S)
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


def docx_style_ids(path: Path) -> list:
    """The style ids one DOCX package declares ([] when unreadable).

    Used by the venue-template conformance scan: a package restyled into the
    journal's template carries the template's style ids; one that still carries
    only its own styles does not.
    """
    try:
        with zipfile.ZipFile(path) as pkg:
            xml = pkg.read("word/styles.xml").decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError):
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
    except (OSError, zipfile.BadZipFile, KeyError):
        return False
    if "evenAndOddHeaders" in settings:
        return True
    sects = _SECT_RE.findall(doc)
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
    except (OSError, zipfile.BadZipFile, KeyError):
        return {}
    rel_map = {m.group(1): (m.group(2).lower(), m.group(3))
               for m in _RELS_RE.finditer(rels)}
    sects = _SECT_RE.findall(doc)
    sect = sects[-1] if sects else ""
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
    except (OSError, zipfile.BadZipFile, KeyError):
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
    "FMT-T8f",   # indentation convention broken between sibling paragraphs/captions
    "FMT-T8g",   # the front page is split by a rendered page break (keywords on page 2)
    "FMT-T8h",   # the cover letter exceeds its two-page budget
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
        bounds, pos = [], 0
        for sentence in sentences:
            bounds.append((pos, pos + len(sentence)))
            pos += len(sentence)
            while pos < len(text) and text[pos].isspace():
                pos += 1
        for m in NUMBER_RE.finditer(text):
            # Attribute by the match POSITION, not by substring membership: a
            # paragraph that repeats a number would otherwise put every
            # instance in the first sentence that happens to contain the digits.
            idx = 0
            for k, (start, _end) in enumerate(bounds):
                if start <= m.start():
                    idx = k
                else:
                    break
            sentence = sentences[idx] if sentences else text
            rows.append({"document_paragraph": i, "number": m.group(0),
                         "thousands_separated": "," in m.group(0),
                         "unit": (UNIT_RE.match(text[m.end():]).group(0).strip()
                                  if UNIT_RE.match(text[m.end():]) else None),
                         "sentence": sentence.strip()[:200], "source": ""})
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
            msg = json.loads(fetch("https://api.crossref.org/works/"
                                   + urllib.parse.quote(doi)
                                   + "?mailto=paper-pipeline@example.org"))["message"]
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
                                 headers={"User-Agent": "paper-pipeline/3.5",
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
        # `error` (the same caveat the reachable-private branch documents).
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


def _cohort_reference_re(number: str):
    """The sentence shape that makes a written number a cohort SIZE."""
    num = re.escape(str(number))
    return re.compile(
        r"(?i)(\bn\s*=\s*" + num + r"\b|\b" + num +
        r"\s+(?:samples?|patients?|donors?|cells?|datasets?|cohorts?|subjects?|cases?|"
        r"participants?|individuals?|libraries?|replicates?))")


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
            head_tokens = set(_M30_TOKEN_RE.findall(str(s.get("column") or "").lower()))
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
TABLES_HEADING_RE = re.compile(r"^\s*(?:list\s+of\s+)?tables?\s*:?\s*$", re.I)
FIGURES_HEADING_RE = re.compile(
    r"^\s*(?:list\s+of\s+figures?|figures?|figure\s+titles?\s+and\s+legends?|"
    r"figure\s+legends?|captions?)\s*:?\s*$", re.I)
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
    try:
        with zipfile.ZipFile(path) as pkg:
            styles = parse_styles(pkg)
            xml = pkg.read("word/document.xml").decode("utf-8")
            if "docProps/app.xml" in pkg.namelist():
                m = re.search(r"<Pages>(\d+)</Pages>",
                              pkg.read("docProps/app.xml").decode("utf-8", "replace"))
                if m:
                    app_pages = int(m.group(1))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeDecodeError, OSError) as e:
        row = {"rule": "FMT-X1", "severity": "high", "document": path.name, "location": "-",
               "evidence": f"{type(e).__name__}: {e}", "detail": "unreadable DOCX package",
               "fix": "manual", "protected": False}
        return {"file": str(path), "rows": [row], "by_rule": {"FMT-X1": 1},
                "high": 1, "medium": 0, "low": 0, "documents": {}}
    res = analyse_document(xml, styles, policy, path.name)
    # The cover letter's two-page budget: a rendered PDF beside the .docx is
    # authoritative; without one, the cached Pages value is reported (and the
    # row says which source it came from -- the cache can be stale).
    if re.search(r"cover[\s_-]?letter", path.name, re.I):
        pages, src = None, ""
        pdf = path.with_suffix(".pdf")
        if pdf.is_file() and shutil.which("pdftotext"):
            txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                                 capture_output=True, text=True).stdout
            pages, src = blank_pages_in_text(txt)["pages"], "the rendered PDF beside it"
        elif app_pages is not None:
            pages, src = app_pages, "the cached docProps/app.xml value -- render to confirm"
        if pages and pages > 2:
            res["rows"].append(cover_letter_page_row(path, pages, src))
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
        m = re.match(r"<w:pPr(?=[\s>])[^>]*>", ppr)
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
        sects = list(re.finditer(r"<w:sectPr(?=[\s>]).*?</w:sectPr>", xml, re.S))
        if sects and re.search(r"<w:headerReference", sects[0].group(0)) \
                and "<w:titlePg" not in sects[0].group(0):
            s = sects[0]
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

    return xml, changes, {"text_edits": text_edits, "text_stage_xml": text_stage_xml}


def fix_package(src: Path, out: Path, policy: dict) -> dict:
    with zipfile.ZipFile(src) as pkg:
        parts = {i.filename: pkg.read(i.filename) for i in pkg.infolist()}
        styles = parse_styles(pkg)
    xml_before = parts["word/document.xml"].decode("utf-8")
    xml_after, changes, meta = fix_document(xml_before, styles, policy)
    try:
        ET.fromstring(xml_after)
        xml_wellformed, xml_detail = True, ""
    except ET.ParseError as e:
        # The byte-level splices must never unbalance the document. `docx
        # validate` is optional, so the parse check is the always-on fence: a
        # malformed output must fail the fixer's own verification, not ship.
        xml_wellformed, xml_detail = False, str(e)
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
        "text_stage_diff_only_quotes": quote_free(text_before) == quote_free(text_stage),
        "text_diff_only_recorded_edits": text_after == text_expected,
        "text_edits": len(meta.get("text_edits") or []),
        "mechanical_findings_before": len([r for r in before_rows if r["fix"] == "mechanical"]),
        "mechanical_findings_after": len([r for r in after_rows if r["fix"] == "mechanical"]),
        "remaining_mechanical_rules": remaining,
        "schema_ok": schema[0], "schema_detail": schema[1],
        "xml_wellformed": xml_wellformed, "xml_detail": xml_detail,
    }
    ok = bool(same_parts
              and (verified["text_identical"] or verified["text_diff_only_quotes"]
                   or (verified["text_stage_diff_only_quotes"]
                       and verified["text_diff_only_recorded_edits"]))
              and not remaining
              and xml_wellformed
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


def _set_para_text(para: str, text: str) -> str:
    """Replace the visible text, keeping the FIRST run's properties."""
    spans = list(re.finditer(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", para, re.S))
    if not spans:
        return para
    out, pos = [], 0
    for i, m in enumerate(spans):
        out.append(para[pos:m.start()])
        inner = (text if i == 0 else "").replace("&", "&amp;").replace("<", "&lt;")
        out.append(f"<w:t>{inner}</w:t>")
        pos = m.end()
    out.append(para[pos:])
    return "".join(out)


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
    """(xml, applied): give the manuscript the template's last sectPr geometry."""
    t_sects = list(_SECT_RE.finditer(template_doc_xml or ""))
    m_sects = list(_SECT_RE.finditer(doc_xml))
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
    body = m_sects[-1].group(0)
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
    return doc_xml[:m_sects[-1].start()] + body + doc_xml[m_sects[-1].end():], True


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
    except (KeyError, OSError):
        return {}
    rel_map = {m.group(1): (m.group(2).lower(), m.group(3))
               for m in _RELS_RE.finditer(trels)}
    refs = {"header": {}, "footer": {}}
    sect = _SECT_RE.findall(tdoc)
    for m in re.finditer(r'<w:(header|footer)Reference w:type="(\w+)" r:id="([^"]+)"',
                         sect[-1] if sect else ""):
        refs[m.group(1)][m.group(2)] = m.group(3)
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
    except (OSError, zipfile.BadZipFile, KeyError):
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
    tables = [(m.start(), m.end()) for m in re.finditer(r"<w:tbl\b[\s\S]*?</w:tbl>", doc_xml)]
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
        text = xml_unescape(tm.group(2))
        if not text.strip():
            continue
        take = min(left, len(text))
        head, tail = text[:take], text[take:]
        left -= take
        rpr = re.search(r"<w:rPr>[\s\S]*?</w:rPr>", run)
        props = rpr.group(0) if rpr else ""
        bold = props if ("<w:b/>" in props or re.search(r'<w:b w:val="(?:1|true|on)"', props)) \
            else (props.replace("<w:rPr>", "<w:rPr><w:b/>", 1) if props
                  else "<w:rPr><w:b/></w:rPr>")

        def with_text(txt: str, want: str) -> str:
            frag = run[:tm.start(2)] + xml_escape(txt) + run[tm.end(2):]
            if re.search(r"<w:rPr>[\s\S]*?</w:rPr>", frag):
                return re.sub(r"<w:rPr>[\s\S]*?</w:rPr>", want, frag, count=1)
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
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run))
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
    rm = re.search(r"<w:rPr(?=[\s>])", ppr_xml)
    if rm:
        return ppr_xml[:rm.start()] + extra + ppr_xml[rm.start():]
    return ppr_xml.replace("</w:pPr>", extra + "</w:pPr>", 1)


def _apply_ppr_extra(frag: str, extra: str) -> str:
    """Give a paragraph the TEMPLATE's own pPr children (its direct spacing)."""
    if not extra:
        return frag
    m = re.search(r"<w:pPr(?=[\s>])[^>]*>[\s\S]*?</w:pPr>", frag)
    if m:
        block = re.sub(r"<w:(?:spacing|ind|jc)(?=[\s/>])[^>]*/>", "", m.group(0))
        return frag.replace(m.group(0), _insert_ppr_extra(block, extra), 1)
    om = re.match(r"<w:p\b[^>]*>", frag)
    return frag[:om.end()] + f"<w:pPr>{extra}</w:pPr>" + frag[om.end():]


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
    """(xml, applied): point the document's sectPr at the venue headers/footers."""
    sects = _SECT_RE.findall(doc_xml)
    if not sects:
        return doc_xml, False
    sect = sects[-1]
    body = re.sub(r"<w:(?:header|footer)Reference[^>]*/>", "", sect)
    body = re.sub(r"<w:titlePg[^>]*/>", "", body)
    om = re.match(r"<w:sectPr(?=[\s>])[^>]*>", body)
    refs = ""
    for key, tag, typ in (("header_default_rid", "headerReference", "default"),
                          ("header_first_rid", "headerReference", "first"),
                          ("header_even_rid", "headerReference", "even"),
                          ("footer_default_rid", "footerReference", "default"),
                          ("footer_first_rid", "footerReference", "first"),
                          ("footer_even_rid", "footerReference", "even")):
        if front.get(key):
            refs += f'<w:{tag} w:type="{typ}" r:id="{front[key]}"/>'
    if refs:
        root = re.search(r"<w:document\b[^>]*>", doc_xml)
        if root and "xmlns:r=" not in root.group(0):
            doc_xml = doc_xml.replace(
                root.group(0), root.group(0)[:-1] + ' xmlns:r="http://schemas.'
                'openxmlformats.org/officeDocument/2006/relationships">', 1)
    body = body[:om.end()] + refs + body[om.end():]
    if "<w:titlePg" not in body:
        body = (body.replace("<w:docGrid", "<w:titlePg/><w:docGrid", 1)
                if "<w:docGrid" in body else
                body.replace("</w:sectPr>", "<w:titlePg/></w:sectPr>", 1))
    return doc_xml.replace(sect, body, 1), True


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
    except (OSError, zipfile.BadZipFile, KeyError) as e:
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
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as e:
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
        changes.append("copied the venue's first-page header (logo), default header and "
                       "page-number footers")
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
                shutil.copytree(path.parent, target_dir,
                                ignore=shutil.ignore_patterns("work", "*.tracked.docx"))
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
            files += [q for q in sorted(p.rglob("*.docx"))
                      if not q.name.startswith("~$") and not _is_aux_name(q.name)
                      and not any(part in EVIDENCE_DIRNAMES for part in q.parts[:-1])]
            files += [q for q in sorted(p.rglob("*.tex")) + sorted(p.rglob("*.ltx"))
                      if not any(part in EVIDENCE_DIRNAMES for part in q.parts[:-1])]
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
    proc = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                          capture_output=True, text=True)
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

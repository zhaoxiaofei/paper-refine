#!/usr/bin/env python3
"""convert_corpus.py — Phase 1 setup for the paper-review skill.

Recursively inventories SUBMISSION_DIR, converts every text-based editable file
(doc/docx/tex/bib/md/txt/xlsx/csv, plus pdf via pdftotext when available) to
plain text under WORK/corpus/, and writes:
  WORK/inventory.md     — human-readable inventory table
  WORK/inventory.json   — machine-readable inventory
  WORK/corpus/<rel>.txt — converted plain text (structure-aware)
  WORK/evidence/<rel>.txt — converted text of the raw-data EVIDENCE area

The EVIDENCE areas are NOT part of the submission: `raw_data/` carries data
tables, figure/table sources and the analysis
snapshot — and an older corpus may also keep the editors'/reviewers' feedback
there; `human_review_feedback/` (sibling of raw_data/) carries the real
editors'/reviewers' comments from the previous submission (and any previous
response-to-reviewers, as context), plus — when present — its child
`original_submission/` with the manuscript version those reviewers actually
saw (evidence for resolving a concern, never the current submission); and
`llm_review_feedback/` carries a machine-generated review whose false-positive
findings were filtered out, so its remaining findings have the same standing as
human concerns. Their files are inventoried with `area: raw_data` /
`area: human_review_feedback` / `area: llm_review_feedback`, are never marked
editable, and their converted text goes to `WORK/evidence/` — never to
`WORK/corpus/` — so no submission sweep (M1 acronyms, M4 numbers, M9 file roles,
M18/M19 lengths, …) can read a data table, a reviewer's sentence, an editor's
decision letter or an LLM review as if it were the authors' manuscript. The
evidence text stays available to the review for fact-checking, the M30 producer
comparison and the concern reconciliation.

Conversion details that matter downstream:
  * .docx — body paragraphs, plus header/footer and footnote/endnote parts,
    each introduced by a `### HEADER (word/header1.xml)` style marker so
    metadata living outside the body is never invisible to M12/M14.
    Zotero/live field instructions are kept as `[[FIELD: ...]]`; tracked
    changes and residual comments are recorded in the inventory notes.
  * .xlsx — shared strings are resolved to their text (a stream of raw shared
    string indexes would poison M15's column sums) and sheet names are mapped
    through workbook relationships, not by sorted file name.
  * .rtf — converted with a small stdlib stripper (formatting is not
    preserved). The conversion is flagged EDITABLE (the C19 contract: .tsv,
    .rtf and .ltx are converted and marked editable), so an edit to an .rtf
    document must be applied to the .rtf itself through an RTF-aware tool --
    paste the stripped text back over the file and the markup is destroyed.

Why this exists: sweeps must run over a uniform plain-text corpus so that every
enumeration is deterministic and reproducible. Conversion failures are RECORDED,
never skipped silently.

stdlib-only by design (docx/xlsx read via zipfile + XML) so it runs in any
Python 3.8+ environment, including sandboxed Codex sandboxes.

Usage:
  python convert_corpus.py --submission ./non_revised --work ./guided_review/work
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as _ET
from html import unescape as _html_unescape

EDITABLE_EXTS = {".doc", ".docx", ".tex", ".ltx", ".bib", ".md", ".txt", ".xlsx", ".csv",
                 ".tsv", ".rtf"}
BINARY_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".svg", ".eps", ".zip",
               ".gz", ".tar", ".xlsx.lock", ".py", ".r", ".ipynb", ".xls", ".pptx", ".docx~"}

# A corpus text name is one filesystem component: NAME_MAX is 255 BYTES, not
# characters. Reserve room for the collision suffix (".__" + 8 hex) and ".txt"
# so even a name that later collides stays within the limit.
NAME_MAX_BYTES = 255
_CORPUS_NAME_RESERVE = len(".__12345678") + len(".txt")


def _bounded_corpus_stem(stem: str, rel: str) -> tuple:
    """Return (stem, truncated) with a generated name that always fits NAME_MAX."""
    encoded = stem.encode("utf-8")
    budget = NAME_MAX_BYTES - _CORPUS_NAME_RESERVE
    if len(encoded) <= budget:
        return stem, False
    digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:8]
    suffix = ".__" + digest
    budget -= len(suffix.encode("utf-8"))
    return encoded[:budget].decode("utf-8", "ignore") + suffix, True

ROLE_PATTERNS = [
    ("title page", re.compile(r"title|titlepage|first_page", re.I)),
    ("abstract", re.compile(r"abstract", re.I)),
    ("main text", re.compile(
        r"(?<![a-z])(?:manuscript|main(?:text)?|article|paper)(?![a-z])"
        r"|(?:^|[_\-. ])ms(?:[_\-. ]|$)", re.I)),
    ("methods", re.compile(r"methods|m&m", re.I)),
    ("references", re.compile(r"\brefs?\b|\breferences?\b|bibliograph|\.bib$", re.I)),
    ("supplementary", re.compile(
        r"(?<![a-z])supp(?:l(?:ement\w*)?|lement\w*)?(?![a-z])"
        r"|extended_?data|appendix", re.I)),
    ("figure", re.compile(r"\bfig|figure|legend", re.I)),
    ("table", re.compile(r"table", re.I)),
    ("reporting summary", re.compile(r"reporting|summary", re.I)),
    ("code", re.compile(r"\.py$|\.r$|\.ipynb$|code|script|(?:^|[_\-. ])src(?:[_\-. ]|$)", re.I)),
    ("data", re.compile(r"\.csv$|\.tsv$|data", re.I)),
]

# The cover-letter ROLE, tested against the name's OWN case (guess_role tests
# the other patterns on the lowercased name, where "plainLetter" and
# "newsletter" are indistinguishable): a word starts at the start, after a
# non-letter, or at a lower->UPPER camelCase boundary, so `cover_letter`,
# `coverLetter` and `plainLetter` are the letter while `discovery`, `coverage`
# and `newsletter` are not.
COVER_LETTER_ROLE_RE = re.compile(
    r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
    r"(?:[Cc]over|COVER|(?i:coverletter|plainletter))(?![a-z])"
    r"|(?i:(?<![a-z])letter[_\-. ]+to[_\-. ]+editor(?![a-z]))"
    r"|(?i:(?<![a-z])tocover(?![a-z]))")

RAW_DATA_DIRNAMES = ("raw_data",)
HUMAN_FEEDBACK_DIR = "human_review_feedback"
LLM_FEEDBACK_DIR = "llm_review_feedback"
# The manuscript version the PREVIOUS journal's editors/reviewers actually saw,
# optionally kept inside the feedback area. It is EVIDENCE (an earlier,
# reviewer-visible version), never the current submission.
ORIGINAL_SUBMISSION_DIRNAME = "original_submission"
EVIDENCE_DIRNAMES = RAW_DATA_DIRNAMES + (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR)
# `<evidence area>.disabled` / `.off` is INERT: not submission content and not
# readable evidence -- the documented off-switch for `llm_review_feedback/`.
DISABLED_EVIDENCE_SUFFIXES = ("disabled", "off")
EVIDENCE_DIRNAME = "evidence"
FEEDBACK_NAME_RE = re.compile(
    r"(?<![a-z])(?:feedbacks?(?:[-_ ]?(?:form|report|letter|comments?|summary|"
    r"to[-_ ]?authors))*|"
    r"(?:referees?|reviewers?)(?:[-_ ]?(?:comments?|reports?|critiques?|forms?))*|"
    r"(?<![a-z_])editors?(?:[-_ ]?(?:comments?|decisions?|reports?|letters?|"
    r"notices?|emails?|critiques?|forms?))|"
    r"editorial|(?<![a-z_])decision(?:[-_ ]?(?:letter|notice|email)))(?![a-z])",
    re.I)
REPLY_NAME_RE = re.compile(
    r"(?<![a-z_])(?:responses?|repl(?:y|ies)|rebuttal|point[-_ ]?by[-_ ]?point)"
    r"(?![a-z])"
    r"|(?i:(?:author|reviewer|referee|editor)[_-]+(?:responses?|repl(?:y|ies)))")


def guess_role(rel_path: str) -> str:
    raw = os.path.basename(rel_path)
    if COVER_LETTER_ROLE_RE.search(raw):
        return "cover letter"
    base = raw.lower()
    for role, pat in ROLE_PATTERNS:
        if pat.search(base):
            return role
    return "other"


def is_raw_data_rel(rel_path: str) -> bool:
    """True for a submission-relative path inside the raw-data evidence area.

    The check looks at the DIRECTORY parts only: a submission file that happens
    to be *named* raw_data... is still a submission file.
    """
    parts = rel_path.replace("\\", "/").split("/")
    return any(part in RAW_DATA_DIRNAMES for part in parts[:-1])


def evidence_area_of(rel_path: str) -> str:
    """The canonical EVIDENCE area a path belongs to ("" when none).

    `human_review_feedback/` is the real editors'/reviewers' comments and
    `llm_review_feedback/` the false-positive-filtered LLM review (siblings of
    raw_data/); every area is an input, never submission text.
    """
    parts = rel_path.replace("\\", "/").split("/")[:-1]
    for part in parts:
        if part in RAW_DATA_DIRNAMES:
            return "raw_data"
        if part in (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR):
            return part
    return ""


def is_disabled_evidence_rel(rel_path: str) -> bool:
    """True when a path lives in an inert `<evidence area>.disabled/` tree."""
    top = str(rel_path or "").replace("\\", "/").lstrip("/").split("/", 1)[0]
    for area in EVIDENCE_DIRNAMES:
        if top.startswith(area + ".") \
                and top[len(area) + 1:].strip().lower() in DISABLED_EVIDENCE_SUFFIXES:
            return True
    return False


def is_original_submission_rel(rel_path: str) -> bool:
    """True for a path inside `human_review_feedback/original_submission/`."""
    parts = rel_path.replace("\\", "/").split("/")
    return (len(parts) >= 3 and parts[0] == HUMAN_FEEDBACK_DIR
            and parts[1] == ORIGINAL_SUBMISSION_DIRNAME)


def is_feedback_rel(rel_path: str) -> bool:
    """True when a raw-data file is editors'/reviewers' feedback.

    Feedback is external prose: it is evidence about the review, never the
    authors' submission text and never a document to sweep, count or edit.
    """
    return bool(FEEDBACK_NAME_RE.search(os.path.basename(rel_path)))


# ---------------------------------------------------------------- docx / xlsx

TEXT_RUN_RE = re.compile(
    # Word stores a tab/soft break as its own element; extracting only w:t
    # glued "Dose[tab]50" into "Dose50" and two lines into one word. A
    # non-breaking hyphen and a symbol glyph have no w:t either: `text_of`
    # renders them as "-" and U+FFFD, and dropping them fused
    # `ten<w:noBreakHyphen/>year` into "tenyear".
    r"<w:(instrText|t)(?:\s[^>]*)?>(.*?)</w:\1>"
    r"|<w:(br|cr|tab|noBreakHyphen|sym)(?=[\s/>])[^>]*/?>", re.S)

# `mc:AlternateContent` carries the same content twice (Choice + Fallback);
# Word renders ONE of them. Splitting the raw XML read both and doubled every
# text-box / DrawingML fallback in the review corpus. Substituting the visible
# branch first is the same rule the pipeline's text_of applies.
_MC_ALTERNATE_RE = re.compile(r"<mc:AlternateContent\b.*?</mc:AlternateContent>", re.S)
_MC_CHOICE_RE = re.compile(r"<mc:Choice\b.*?</mc:Choice>", re.S)
_MC_FALLBACK_RE = re.compile(r"<mc:Fallback\b.*?</mc:Fallback>", re.S)


def _mc_visible_branch(m) -> str:
    block = m.group(0)
    branch = _MC_CHOICE_RE.search(block) or _MC_FALLBACK_RE.search(block)
    return branch.group(0) if branch else ""


# Untrusted DOCX parts: cap the DECOMPRESSED size before reading and refuse an
# XML DTD/entity outright. The pipeline applies the same 64 MiB budget (see
# paper_pipeline `_docx_xml_part`); without it here, the agents' converter
# expanded a 70 MiB part from a 70 KiB submission while the orchestrator
# refused it, so the two readers disagreed about the corpus.
MAX_DOCX_PART_BYTES = 64 * 1024 * 1024


def _docx_part(z, name: str):
    """Bytes of one DOCX part inside the size/entity budget, or None."""
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_DOCX_PART_BYTES:
        return None
    data = z.read(name)
    text = data.decode("utf-16", "ignore") if data[:2] in (b"\xff\xfe", b"\xfe\xff") \
        else data.decode("utf-8", "ignore")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    return data


def _xml_well_formed(raw):
    """None when `raw` parses as one XML document, else the parse error text.

    Accepts the DECODED text as well as bytes: `docx_part_to_lines` works on
    the text `_docx_xml_text` produced, so a part whose stale encoding
    declaration disagrees with its BOM is readable, not malformed (F25).
    """
    try:
        _ET.fromstring(raw)
        return None
    except _ET.ParseError as e:
        return str(e)


def _docx_xml_text(raw: bytes) -> str:
    """Decode a DOCX part using its BOM/declaration, not an assumed UTF-8."""
    if raw[:2] == b"\xff\xfe" or raw[:2] == b"\xfe\xff":
        return raw.decode("utf-16", "replace")
    if b"\x00" in raw[:200] and raw[:4].lower() in (b"<\x00?\x00", b"\x00<\x00?"):
        return raw.decode("utf-16-le" if raw[:1] == b"<" else "utf-16-be", "replace")
    return raw.decode("utf-8", "replace")


_WORD_NS_TEXT = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD_NS_DECL_RE = re.compile(
    r"xmlns(?::(?P<prefix>[A-Za-z_][\w.-]*))?\s*=\s*(?P<q>[\"'])"
    + re.escape(_WORD_NS_TEXT) + r"(?P=q)")


def _word_prefix_xml(xml: str) -> str:
    """Rename a legal non-`w` Word namespace declaration to `w`.

    The reader's regexes name elements by prefix; OOXML binds the namespace,
    not the spelling, so `a:document/a:p/a:t` is valid WordprocessingML and
    must yield the same text (F24).

    Either quote style, whitespace around `=`, and the Word namespace as the
    DEFAULT namespace (`<document xmlns="...">`) are legal XML; the
    double-quote-only pattern produced no text for them (R02).
    """
    m = _WORD_NS_DECL_RE.search(xml)
    if not m:
        return xml
    prefix = m.group("prefix")
    if prefix == "w":
        return xml
    if prefix is not None:
        out = re.sub(r"(?<=[<\s/])" + re.escape(prefix) + r":", "w:", xml)
        return _WORD_NS_DECL_RE.sub(
            lambda mm: "xmlns:w=" + mm.group("q") + _WORD_NS_TEXT + mm.group("q"),
            out, count=1)
    # Default namespace: qualify every unprefixed element name so the
    # `w:`-based reader sees the document.
    if re.search(r"xmlns\s*=", _WORD_NS_DECL_RE.sub("", xml, count=1)):
        return xml                # another default declaration: not resolvable here
    out = _WORD_NS_DECL_RE.sub(
        lambda mm: "xmlns:w=" + mm.group("q") + _WORD_NS_TEXT + mm.group("q"),
        xml, count=1)
    return re.sub(r"<(?P<close>/?)(?P<name>[A-Za-z_][\w.-]*)(?=[\s/>])",
                  lambda mm: "<" + mm.group("close") + "w:" + mm.group("name"), out)


_VANISH_OFF = frozenset(("false", "0", "off"))


def _run_is_hidden(run: str) -> bool:
    """True when the run carries a `w:vanish` property that is ON.

    `w:vanish` is an OOXML on/off property: `w:val="false"`/`"0"`/`"off"`
    leaves the run VISIBLE. Treating the bare element as "hidden" dropped
    visible prose from the corpus (R05).
    """
    for m in re.finditer(r"<w:vanish\b([^>]*?)/?>", run):
        val = re.search(r"\b(?:[\w.-]+:)?val\s*=\s*(?:\"([^\"]*)\"|'([^']*)')",
                        m.group(1))
        if val is None:
            return True                        # val absent = ON
        value = (val.group(1) if val.group(1) is not None else val.group(2))
        if value.strip().lower() not in _VANISH_OFF:
            return True
    return False


def docx_part_to_lines(xml: str):
    """Paragraph lines + notes for one WordprocessingML part."""
    notes, out_lines = [], []
    xml = _word_prefix_xml(xml)
    # XML comments are markup, not document text: a commented-out paragraph
    # used to be extracted as a visible claim (F30).
    xml = re.sub(r"<!--.*?-->", "", xml, flags=re.S)
    # Moved-FROM content is the pre-move position (deleted); only moveTo is the
    # current text. Extracting both duplicated passages (F26).
    xml = re.sub(r"<w:moveFrom\b.*?</w:moveFrom>", "", xml, flags=re.S)
    xml = re.sub(r"<w:moveFrom\b[^>]*/>", "", xml)
    # Hidden runs (`w:vanish`) are not visible prose. Dropping them (with a
    # note) keeps a hidden draft value from entering the manuscript corpus as
    # an ordinary claim (F27). Only a property that is ON hides the run.
    _visible = xml
    for _run in re.findall(r"<w:r\b[^>]*>.*?</w:r>", xml, flags=re.S):
        if _run_is_hidden(_run):
            _visible = _visible.replace(_run, "", 1)
    if _visible != xml:
        notes.append("hidden text omitted (w:vanish)")
        xml = _visible
    for para in re.split(r"</w:p>", _MC_ALTERNATE_RE.sub(_mc_visible_branch, xml)):
        if "<w:ins " in para:
            notes.append("tracked-insertion present in a paragraph")
        if "<w:del " in para:
            notes.append("tracked-deletion present in a paragraph")
        texts = []
        for m in TEXT_RUN_RE.finditer(para):
            if m.group(3):
                # The pipeline's own `text_of` renders br/cr as a newline, a tab
                # as a separator, a non-breaking hyphen as "-" and a symbol as
                # one placeholder; the converter must agree or the sweeps read
                # words the author never wrote.
                tok = m.group(3)
                texts.append("\n" if tok in ("br", "cr")
                             else "-" if tok == "noBreakHyphen"
                             else "\ufffd" if tok == "sym" else " ")
                continue
            content = _html_unescape(m.group(2))
            # Test the TAG NAME, never a substring of the whole match: a visible
            # w:t whose sentence merely mentions "instrText" became a fake
            # [[FIELD: ...]] marker that polluted every downstream sweep.
            if m.group(1) == "instrText":
                texts.append("[[FIELD: %s]]" % content.strip())
                notes.append("live field instruction present (possible Zotero citation)")
            else:
                texts.append(content)
        line = "".join(texts).strip()
        if line:
            out_lines.append(line)
    return out_lines, notes


def docx_to_text(path: str) -> tuple:
    """Return (text, notes) — body plus headers/footers/footnotes/endnotes."""
    notes = []
    out_lines = []
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return "", ["docx-unreadable: %s" % e]
    with z:
        raw = _docx_part(z, "word/document.xml")
        if raw is None:
            return "", ["docx-unreadable: word/document.xml is over the size/"
                        "entity budget and was refused"]
        body = _docx_xml_text(raw)
        malformed = _xml_well_formed(body)
        if malformed:
            notes.append("docx-part-unreadable: word/document.xml is not well-formed "
                         "XML (%s); its text was not extracted" % malformed)
        else:
            lines, part_notes = docx_part_to_lines(body)
            out_lines.extend(lines)
            notes.extend(part_notes)
        names = z.namelist()
        extra_parts = []
        for pattern, kind in ((r"word/header\d*\.xml$", "HEADER"),
                              (r"word/footer\d*\.xml$", "FOOTER"),
                              (r"word/footnotes\.xml$", "FOOTNOTES"),
                              (r"word/endnotes\.xml$", "ENDNOTES")):
            extra_parts.extend((n, kind) for n in sorted(names) if re.match(pattern, n))
        for name, kind in extra_parts:
            raw = _docx_part(z, name)
            if raw is None:
                notes.append("%s part refused: over the size/entity budget: %s"
                             % (kind.lower(), name))
                continue
            xml = _docx_xml_text(raw)
            malformed = _xml_well_formed(xml)
            if malformed:
                notes.append("docx-part-unreadable: %s is not well-formed XML (%s); "
                             "its text was not extracted" % (name, malformed))
                continue
            part_lines, part_notes = docx_part_to_lines(xml)
            if part_lines:
                # lowercase marker: an all-caps marker would itself be inventoried as an acronym.
                # The `corpus-marker:` prefix is deliberately NOT a plain markdown heading:
                # the extractors skip these synthetic parts, and a real manuscript H3
                # (a methods subsection) must stay in the corpus (F47).
                out_lines.append("### corpus-marker: %s (%s)" % (kind.lower(), name))
                out_lines.extend(part_lines)
                notes.append("%s text included: %s" % (kind.lower(), name))
            notes.extend(part_notes)
        try:
            if any(n.startswith("word/comments") for n in names):
                notes.append("word/comments*.xml present — residual comments in docx")
            if "docProps/core.xml" in names:
                raw_core = _docx_part(z, "docProps/core.xml")
                if raw_core is None:
                    notes.append("docProps/core.xml refused: over the size/entity budget")
                else:
                    core = _docx_xml_text(raw_core)
                    for tag in ("lastModifiedBy", "creator"):
                        m = re.search(r"<[^>]*%s[^>]*>(.*?)</[^>]*%s" % (tag, tag),
                                      core, re.S)
                        if m and m.group(1).strip():
                            notes.append("docx property %s = %r (metadata/PII check)"
                                         % (tag, m.group(1)[:60]))
        except Exception:
            pass
    return "\n".join(out_lines), notes


CELL_RE = re.compile(r"<c(?P<attrs>\s[^>]*)?(?:(?:/>)|>(?P<body>.*?)</c>)", re.S)
ROW_RE = re.compile(r"<row[^>]*>(.*?)</row>", re.S)
SHEET_TAG_RE = re.compile(r"<sheet\b[^>]*/?>")


def _xlsx_shared_strings(z):
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = z.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
        for si in re.findall(r"<si>(.*?)</si>", ss, re.S):
            # Shared strings carry XML entities ("A&amp;B", "caf&eacute;") and the
            # inline-string path already unescapes them; leaving them literal here
            # made the two paths disagree and poisoned the corpus with "&amp;".
            shared.append(_xlsx_unescape(_html_unescape(
                "".join(re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", si, re.S)))))
    return shared


def _xlsx_sheet_plan(z):
    """[(sheet name, worksheet path)] in workbook order, via the rels map."""
    try:
        wb = z.read("xl/workbook.xml").decode("utf-8", errors="replace")
    except KeyError:
        return []
    rels = {}
    if "xl/_rels/workbook.xml.rels" in z.namelist():
        rx = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", errors="replace")
        for m in re.finditer(r"<Relationship\b[^>]*/?>", rx):
            tag = m.group(0)
            rid = re.search(r'Id="([^"]*)"', tag)
            tgt = re.search(r'Target="([^"]*)"', tag)
            typ = re.search(r'Type="([^"]*)"', tag)
            if not (rid and tgt):
                continue
            if typ and "worksheet" not in typ.group(1):
                continue
            t = tgt.group(1).replace("\\", "/")
            if t.startswith("/"):
                t = t.lstrip("/")
            elif not t.startswith("xl/"):
                t = "xl/" + t
            rels[rid.group(1)] = t
    plan = []
    for m in SHEET_TAG_RE.finditer(wb):
        tag = m.group(0)
        name = re.search(r'name="([^"]*)"', tag)
        rid = re.search(r'r:id="([^"]*)"', tag)
        plan.append((_html_unescape(name.group(1)) if name else None,
                     rels.get(rid.group(1)) if rid else None))
    return plan


def _xlsx_unescape(text: str) -> str:
    """Decode SpreadsheetML's `_xHHHH_` escapes after XML decoding (F33)."""
    return re.sub(r"_x([0-9A-Fa-f]{4})_",
                  lambda m: chr(int(m.group(1), 16)), text or "")


def _xlsx_cell_value(attrs, body, shared):
    if body is None:
        return ""
    # A rich inline string is a sequence of runs; taking only the first <t>
    # silently truncated the cell (F31).
    if "<is>" in body:
        texts = re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", body, re.S)
        if texts:
            return _xlsx_unescape("".join(_html_unescape(t) for t in texts))
    tm = re.search(r"<t(?:\s[^>]*)?>(.*?)</t>", body, re.S)
    if tm:
        return _xlsx_unescape(_html_unescape(tm.group(1)))
    vm = re.search(r"<v(?:\s[^>]*)?>(.*?)</v>", body, re.S)
    if not vm:
        # A FORMULA cell without a cached result (the producer did not
        # recalculate before saving) used to become an empty string -- exactly
        # the same as a genuinely blank cell. Keep the formula in the corpus and
        # mark its value unavailable until calculated.
        fm = re.search(r"<f(?:\s[^>]*)?>(.*?)</f>", body, re.S)
        if fm:
            formula = _xlsx_unescape(_html_unescape(fm.group(1))).strip().lstrip("=")
            return ("[uncached formula: =%s]" % formula) if formula \
                else "[uncached formula]"
        if "<f" in body:
            return "[uncached formula]"       # a shared/array formula with no text
        return ""
    v = _html_unescape(vm.group(1))
    if not v.strip() and re.search(r"<f(?=\s|>)", body, re.S) \
            and not re.search(r't="(?:str|inlineStr)"', attrs or ""):
        # `<f>1+1</f><v></v>` is an UNEVALUATED formula, not a cached empty
        # result. A genuinely cached empty text result carries t="str".
        fm = re.search(r"<f(?:\s[^>]*)?>(.*?)</f>", body, re.S)
        if fm is not None:
            formula = _xlsx_unescape(_html_unescape(fm.group(1))).strip().lstrip("=")
            return ("[uncached formula: =%s]" % formula) if formula \
                else "[uncached formula]"
        return "[uncached formula]"
    if re.search(r't="s"', attrs or "") and v.strip().isdigit():
        idx = int(v)
        if 0 <= idx < len(shared):
            return shared[idx]
        # A dangling index is corruption, not a blank cell: keep it visible so
        # the evidence view cannot silently lose the value (F-082).
        return "[dangling shared-string index: %d]" % idx
    return v


CELL_REF_RE = re.compile(r"^\s*([A-Za-z]{1,3})(\d{1,7})\s*$")


def _col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _xlsx_row_cells(row_xml, shared):
    """{column index: value} for one row, keyed by the cell reference."""
    cells = {}
    for m in CELL_RE.finditer(row_xml):
        ref = re.search(r'r="([^"]*)"', m.group("attrs") or "")
        col = 0
        if ref:
            rm = CELL_REF_RE.match(ref.group(1))
            if rm:
                col = _col_index(rm.group(1))
        value = _xlsx_cell_value(m.group("attrs"), m.group("body"), shared)
        if col:
            cells[col] = value
        else:
            # The fallback column is the one AFTER the highest keyed so far, not
            # `len(cells)+1`: a row whose first labeled cell is B1 made the next
            # unlabeled cell overwrite column 2 instead of taking column 3.
            cells[max(cells, default=0) + 1] = value
    return cells


def _xlsx_escape_cell(value) -> str:
    """One cell in the line-delimited evidence view, reversibly escaped.

    A literal `|` or newline in a cell used to fabricate extra columns/rows in
    the rendered table (F-075). Backslash-escape the delimiter and the escape
    itself, and spell line breaks as `\n`; the text stays decodable.
    """
    return (str(value or "").replace("\\", "\\\\").replace("|", "\\|")
            .replace("\r\n", "\\n").replace("\n", "\\n")
            .replace("\r", "\\n"))


def _xlsx_cached_formulas(row_xml: str, shared) -> list:
    """`<ref> =formula -> cached-value` for formula cells WITH a cached result."""
    out = []
    for cm in CELL_RE.finditer(row_xml):
        attrs, body = cm.group("attrs") or "", cm.group("body") or ""
        fm = re.search(r"<f(?:\s[^>]*)?>(.*?)</f>", body, re.S)
        if fm is None or not re.search(r"<v(?:\s[^>]*)?>", body):
            continue
        ref = re.search(r'r="([^"]*)"', attrs)
        value = _xlsx_cell_value(attrs, body, shared)
        if not value or value.startswith("[uncached formula"):
            continue
        formula = _xlsx_unescape(_html_unescape(fm.group(1))).strip().lstrip("=")
        out.append("%s =%s -> %s" % (ref.group(1) if ref else "?", formula, value))
    return out


def xlsx_to_text(path: str) -> tuple:
    notes = []
    try:
        with zipfile.ZipFile(path) as z:
            shared = _xlsx_shared_strings(z)
            names = z.namelist()
            plan = _xlsx_sheet_plan(z)
            known = {p for _n, p in plan if p in names}
            leftovers = [n for n in sorted(n for n in names
                                            if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
                         if n not in known]
            resolved = []
            for name, p in plan:
                if p in names:
                    resolved.append((name, p))
                else:
                    # A named sheet whose relationship target is missing must
                    # not borrow the next unclaimed worksheet: their values
                    # would be presented under the wrong title (F-073).
                    why = ("has no resolvable worksheet relationship"
                           if not p else "targets a missing part %s" % p)
                    notes.append("xlsx-partial: sheet %r %s; its data are not "
                                 "rendered under that name" % (name, why))
            for p in leftovers:
                resolved.append((None, p))
            lines = []
            for name, sf in resolved:
                sname = name or sf
                lines.append("### corpus-marker: sheet: %s" % _xlsx_escape_cell(sname))
                sh = z.read(sf).decode("utf-8", errors="replace")
                try:
                    _ET.fromstring(sh)
                except _ET.ParseError as e:
                    # The row regex below can still salvage complete rows, but a
                    # malformed part is a PARTIAL conversion and must say so
                    # (F-072); a truncated row silently disappeared before.
                    notes.append("xlsx-partial: %s: malformed worksheet XML (%s)" % (sf, e))
                rows = []
                cached_formulas = []
                saw_dangling = False
                max_col = 0
                for rm in re.finditer(r"<row\b([^>]*)>(.*?)</row>", sh, re.S):
                    cells = _xlsx_row_cells(rm.group(2), shared)
                    cached_formulas.extend(_xlsx_cached_formulas(rm.group(2), shared))
                    if any(str(v).startswith("[dangling shared-string index:")
                           for v in cells.values()):
                        saw_dangling = True
                    if not cells:
                        continue
                    rn = re.search(r'r="(\d+)"', rm.group(1))
                    # A row the producer wrote WITHOUT `r=` follows the highest
                    # row number seen so far. `len(rows)+1` collided with an
                    # explicit number (a sheet that starts at r="2", or a
                    # fallback index equal to a later row's), and `sorted` then
                    # compared the two cell dicts -> TypeError -> the blanket
                    # handler dropped the WHOLE workbook as "xlsx-unreadable".
                    row_idx = int(rn.group(1)) if rn else (max(r[0] for r in rows) + 1
                                                           if rows else 1)
                    rows.append((row_idx, cells))
                    max_col = max(max_col, max(cells))
                # pad every row to the widest column so a sparse row (data only in
                # column C, or a merged/omitted cell) cannot silently shift values
                # into the wrong column when the table is summed downstream (M15)
                for _row_idx, cells in sorted(rows, key=lambda r: r[0]):
                    # Keep each row's ORIGINAL sheet coordinate. The values were
                    # sorted by `r=` but the output carried only the cells, so
                    # rows 1 and 100 became output lines 1 and 2: an evidence
                    # view could not cite the producer's own row, and a sparse
                    # sheet read as consecutive rows. The marker line keeps the
                    # row shape unchanged (and is skipped by the number/acronym
                    # scanners like the sheet marker above).
                    lines.append("### corpus-marker: row: %s!%d"
                                 % (_xlsx_escape_cell(sname), _row_idx))
                    lines.append(" | ".join(_xlsx_escape_cell(cells.get(c, ""))
                                             for c in range(1, max_col + 1)))
                for marker in cached_formulas:
                    # Keep the cached number in its cell (the reconciliation
                    # reads it) and record the formula beside it (F-086).
                    lines.append("### corpus-marker: cached-formula %s!%s"
                                 % (_xlsx_escape_cell(sname), marker))
                if saw_dangling:
                    notes.append("xlsx-partial: %s: a cell references a shared string "
                                 "outside the shared-string table" % sf)
            if not resolved:
                notes.append("xlsx-unreadable: no workbook/worksheet parts found")
            return "\n".join(lines), notes
    except Exception as e:
        notes.append("xlsx-unreadable: %s" % e)
        return "", notes


# ------------------------------------------------------------------- generic

def plain_copy(path: str) -> tuple:
    # A FIFO (or device/socket) passes os.walk's name-only enumeration and then
    # BLOCKS in open() until a writer appears; a submission carrying one used to
    # hang conversion before the review could start. Require a regular file
    # before opening (the enumeration applies the same test and reports it).
    if not os.path.isfile(path):
        return "", ["unreadable — not a regular file"]
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        # Every other converter records a failed conversion; this path (all
        # .md/.txt/.tex/.bib/.csv sources) used to propagate the error out of
        # main() before any inventory or corpus was written.
        return "", ["unreadable — %s" % e]
    # A BOM is authoritative: Word/Notepad exports a .txt as UTF-16 on Windows,
    # and reading it as UTF-8 "succeeded" with NUL-separated mojibake that then
    # fed the corpus sweeps as if it were text. The UTF-8 BOM matters too: left
    # in place it glues an invisible character to the first heading ("\ufeffAbstract"),
    # so the abstract row silently disappears from every downstream sweep.
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig"), []
        except UnicodeDecodeError as e:
            return raw.decode("utf-8-sig", errors="replace"), [
                "decoding gap — invalid UTF-8 at byte %d: %s; U+FFFD was substituted, so "
                "this text is lossy" % (e.start, e.reason)]
    for bom, enc in ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
                     (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            try:
                return raw.decode(enc), []
            except UnicodeDecodeError as e:
                return "", ["unable — %s decode failed: %s" % (enc, e)]
    try:
        return raw.decode("utf-8"), []
    except UnicodeDecodeError as e:
        # Never substitute silently: the converter reports "converted" and the
        # damaged value then reaches a numeric/text sweep as the authors' own
        # evidence. Record the byte and the reason in the inventory.
        return raw.decode("utf-8", errors="replace"), [
            "decoding gap — invalid UTF-8 at byte %d: %s; U+FFFD was substituted, so this "
            "text is lossy" % (e.start, e.reason)]


RTF_META_WORDS = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object",
                  "themedata", "datastore", "generator", "listtable", "listoverridetable",
                  # A tracked deletion lives in its own destination group; the
                  # body is not current prose (F38).
                  "deleted"}


def rtf_to_text(path: str) -> tuple:
    """Small stdlib RTF -> text stripper (formatting is not preserved)."""
    notes = []
    try:
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            raw = f.read()
    except Exception as e:
        return "", ["rtf-unreadable: %s" % e]
    if not raw.lstrip("\ufeff \t\r\n").startswith("{\\rtf"):
        # A wrong file type named .rtf used to disappear as a readable-but-empty
        # RTF with a generic success note. Require the RTF header.
        return "", ["rtf-unreadable: the file does not start with an RTF header "
                    "(expected '{\\rtf'); '.rtf' is only a suffix, not a format check"]
    out, i, depth, skip_depth = [], 0, 0, None
    pending_high = None
    # RTF state is GROUP-scoped: `\ucN` changes how many fallback characters
    # follow each `\uN`, and `\ansicpgN` selects the code page for `\'hh`.
    uc_stack, uc, skip_chars, codepage = [1], 1, 0, 1252
    n = len(raw)
    while i < n:
        ch = raw[i]
        if skip_chars and ch == "\\":
            # The `\ucN` fallback is a CHARACTER, so a `\'hh` escape is that
            # fallback: consume it without emitting its text (R07). A following
            # `\uN` is decoded as a REAL escape, not consumed as the fallback:
            # producers omit the fallback after a BMP escape, and the surrogate
            # pair path (`\uD83D\uDE00`) needs its second half (pinned by the
            # 2026-10-09 audit's E3a/E3b). A control WORD (`\par`) is not a
            # character either, so it ends the fallback run.
            _hex = (re.match(r"'[0-9A-Fa-f]{2}", raw[i + 1:])
                    if i + 1 < n and raw[i + 1] == "'" else None)
            if _hex:
                skip_chars -= 1
                i += 1 + len(_hex.group(0))
                continue
            skip_chars = 0
        if skip_chars and ch not in "{}":
            # The fallback characters after a Unicode escape are an alternate
            # rendering, not a second copy of the text.
            skip_chars -= 1
            i += 1
            continue
        if ch == "{":
            depth += 1
            uc_stack.append(uc)
            i += 1
        elif ch == "}":
            depth -= 1
            if len(uc_stack) > 1:
                uc = uc_stack.pop()
            if skip_depth is not None and depth < skip_depth:
                skip_depth = None
            i += 1
        elif ch == "\\":
            i += 1
            if i >= n:
                break
            nxt = raw[i]
            if nxt in "\\{}":
                if skip_depth is None:
                    out.append(nxt)
                i += 1
            elif nxt == "*":
                skip_depth = depth
                i += 1
            elif nxt in "~_-":
                # Text-producing control symbols: a non-breaking space, a
                # non-breaking hyphen and an optional hyphen. Skipping them
                # merged distinct words (F37).
                if skip_depth is None:
                    out.append({"~": "\u00a0", "_": "\u2011", "-": ""}[nxt])
                i += 1
            elif nxt == "'":
                try:
                    if skip_depth is None:
                        _enc = ("cp%d" % codepage) if codepage else "latin-1"
                        try:
                            out.append(bytes.fromhex(raw[i + 1:i + 3]).decode(_enc, errors="replace"))
                        except LookupError:
                            out.append(bytes.fromhex(raw[i + 1:i + 3]).decode("latin-1", errors="replace"))
                except ValueError:
                    pass
                i += 3
            elif nxt == "u" and re.match(r"u-?\d", raw[i:]):
                # ONLY `\uNNNN` (the RTF unicode escape). A control word that
                # merely STARTS with `u` (`\ul`, `\ulnone`, `\up6`, `\uc1`) must
                # fall through to the generic control-word path below and be
                # consumed whole -- matching `u` and advancing one character
                # leaked the tail ("ul" -> "l") into the corpus text.
                # The delimiter after `\uNNNN` is a SPACE (or nothing); it is
                # never the next escape's backslash -- `\D?` ate it, so
                # `\u9731\u9733` leaked as "☃u9733" and a following control word
                # (`\u9786\par`) collapsed to the literal "par" while the escape
                # that should have produced the character vanished. Dropping the
                # backslash from the delimiter class also lets the surrogate-pair
                # path see its second half.
                m = re.match(r"u(-?\d+)(?: )?", raw[i:])
                code = int(m.group(1))
                if code < 0:
                    code += 65536
                if skip_depth is None:
                    try:
                        if 0xD800 <= code <= 0xDBFF:
                            if pending_high is not None:
                                out.append(chr(pending_high))
                            pending_high = code
                        elif 0xDC00 <= code <= 0xDFFF and pending_high is not None:
                            out.append(chr(0x10000 + ((pending_high - 0xD800) << 10)
                                           + (code - 0xDC00)))
                            pending_high = None
                        else:
                            if pending_high is not None:
                                out.append(chr(pending_high))
                                pending_high = None
                            out.append(chr(code))
                    except ValueError:
                        pending_high = None
                # Skip exactly the group's declared fallback count.
                skip_chars = uc
                i += len(m.group(0))
            else:
                m = re.match(r"([A-Za-z]+)(-?\d+)?[ ]?", raw[i:])
                if m:
                    word = m.group(1)
                    if skip_depth is None:
                        if word in ("par", "line", "sect", "page"):
                            out.append("\n")
                        elif word == "tab":
                            out.append("\t")
                    if word == "ansicpg" and m.group(2):
                        codepage = int(m.group(2))
                    elif word == "uc" and m.group(2):
                        uc = max(0, int(m.group(2)))
                    if word in RTF_META_WORDS:
                        skip_depth = depth
                    i += len(m.group(0))
                else:
                    i += 1
        else:
            if skip_depth is None and depth > 0:
                out.append(ch)
            i += 1
    if pending_high is not None:
        out.append(chr(pending_high))
    text = "".join(out)
    # A lone surrogate (unpaired \u escape) would crash the utf-8 corpus write;
    # replace it here so one malformed escape cannot abort the whole run.
    text = text.encode("utf-8", "replace").decode("utf-8")
    text = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    notes.append("rtf converted by stdlib stripper (formatting not preserved) — "
                 "read-only here; edit the submission in a word processor")
    if not text:
        notes.append("rtf produced no extractable text")
    return text, notes


def pdf_to_text(path: str) -> tuple:
    notes = []
    if shutil.which("pdftotext"):
        try:
            proc = subprocess.run(["pdftotext", "-layout", path, "-"],
                                  capture_output=True, timeout=60)
            text = proc.stdout.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                # A non-zero pdftotext exit with partial stdout is NOT a full
                # conversion: later pages may be missing (F39).
                notes.append("pdftotext-incomplete: exited %d; the extracted text may "
                             "cover only part of the document; stderr: %s"
                             % (proc.returncode,
                                proc.stderr.decode("utf-8", errors="replace").strip()[:200]))
            if not text.strip():
                notes.append("pdftotext produced no text (scanned/image PDF?) — "
                             "visually unverifiable; first stderr: %s"
                             % proc.stderr.decode("utf-8", errors="replace").strip()[:120])
            return text, notes
        except Exception as e:
            notes.append("pdftotext-failed: %s" % e)
            return "", notes
    notes.append("pdf-unconvertible: pdftotext not available — read-only/unreadable")
    return "", notes


def convert_one(path: str, rel: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if path.lower().endswith(".xlsx.lock"):
        # splitext reports ".lock" here, so the BINARY_EXTS entry never matched
        # and an Office lock file was bucketed as "read-only/unknown-ext"
        # instead of the read-only/binary bucket it is listed under.
        ext = ".xlsx.lock"
    text, notes = "", []
    status = "not-attempted"
    if ext in (".md", ".txt", ".tex", ".ltx", ".bib", ".csv", ".tsv"):
        text, notes = plain_copy(path)
        # A decode failure (plain_copy reports it in `notes`) is a FAILED
        # conversion, not an empty document: otherwise the "N files could not be
        # converted" warning never counts it and an unreadable file looks like a
        # legitimately empty editable one.
        status = "converted" if text else ("converted-empty" if not notes else "failed")
        if any(n.startswith("decoding gap") for n in notes):
            # Readable, but with substituted bytes: the inventory must show a
            # partial conversion, never a clean one.
            status = "converted-partial"
    elif ext == ".rtf":
        text, notes = rtf_to_text(path)
        # An unreadable file is a FAILED conversion: rtf_to_text returns an
        # "rtf-unreadable: ..." note and no text, and recording that as a
        # legitimately empty editable file kept it out of the "N files could
        # not be converted" warning while the sweeps saw "(empty file)". But
        # rtf_to_text also appends an informational note on SUCCESS, so the
        # readable-but-empty document must stay `converted-empty` -- the same
        # shape the .xlsx branch below uses.
        status = "converted" if text else (
            "converted-empty" if any("unreadable" not in n for n in notes) else "failed")
    elif ext == ".docx":
        text, notes = docx_to_text(path)
        # Same predicate as the .rtf/.xlsx branches: `docx_to_text` appends an
        # INFORMATIONAL note on success (the metadata/PII line fires whenever
        # docProps/core.xml exists -- i.e. every real Word file -- plus
        # header/footer and tracked-change notes), so "empty text and any note at
        # all" classified an image-only or empty-shell .docx as FAILED, counted
        # it in the could-not-convert warning and wrote no corpus file at all.
        # A readable but EMPTY document is not a failed conversion. The test is
        # "did any note say unreadable?", not "is there at least one note?":
        # an empty document with no metadata note used to be `failed`, while
        # the same content plus an incidental creator note became
        # `converted-empty` (F29).
        status = "converted" if text else (
            "converted-empty" if not any("unreadable" in n for n in notes) else "failed")
        if any(n.startswith("docx-part-unreadable") for n in notes):
            # Some text may have come from other parts, but a malformed body is
            # a PARTIAL conversion, never a clean one.
            status = "converted-partial" if text else "failed"
    elif ext == ".xlsx":
        text, notes = xlsx_to_text(path)
        status = "converted" if text else ("converted-empty"
                                           if any("unreadable" not in n for n in notes) else "failed")
    elif ext == ".doc":
        status = "needs-conversion-to-docx"
        notes.append(".doc is legacy binary — convert to .docx before editing; treat as read-only here")
    elif ext == ".pdf":
        text, notes = pdf_to_text(path)
        if any(n.startswith("pdftotext-incomplete") for n in notes):
            status = "converted-partial" if text.strip() else "read-only/unreadable"
        else:
            status = "converted" if text.strip() else "read-only/unreadable"
    elif ext in BINARY_EXTS:
        status = "read-only/binary"
        if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".svg", ".eps"):
            notes.append("image — visually unverifiable without OCR/VLM")
        if ext in (".py", ".r", ".ipynb"):
            notes.append("code file — reviewed only if code findings are in scope; "
                         "copy into code/ before editing")
    else:
        status = "read-only/unknown-ext"
    return {"path": rel, "abs": path, "ext": ext, "text": text, "notes": notes,
            "status": status}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", required=True, help="SUBMISSION_DIR")
    ap.add_argument("--work", required=True, help="WORK dir (e.g. ./guided_review/work)")
    args = ap.parse_args()

    sub = os.path.abspath(args.submission)
    work = os.path.abspath(args.work)
    if not os.path.isdir(sub):
        print("ERROR: SUBMISSION_DIR %s does not exist. Stop and ask the user." % sub)
        sys.exit(2)
    sub_real, work_real = os.path.realpath(sub), os.path.realpath(work)
    if sub_real == work_real or sub_real.startswith(work_real + os.sep):
        print("ERROR: the work directory overlaps the submission (work is the "
              "submission or one of its parents): %s vs %s" % (work, sub))
        sys.exit(2)
    corpus_dir = os.path.join(work, "corpus")
    evidence_dir = os.path.join(work, EVIDENCE_DIRNAME)
    # Re-conversion is a FRESH corpus: a document removed from the submission
    # must not survive as stale generated text in the same work directory
    # (F40). Only the generated corpus/evidence trees are removed.
    for _generated in (corpus_dir, evidence_dir):
        if os.path.isdir(_generated):
            shutil.rmtree(_generated, ignore_errors=True)
    os.makedirs(corpus_dir, exist_ok=True)
    os.makedirs(evidence_dir, exist_ok=True)

    files = []
    skipped_links = []
    skipped_special = []
    for root, dirs, names in os.walk(sub):
        kept_dirs = []
        for d in sorted(dirs):
            dp = os.path.join(root, d)
            # A work directory INSIDE the submission must not be inventoried:
            # the previous run's own inventory/corpus would be re-read and
            # recursively amplified (F41).
            if os.path.realpath(dp) == work_real:
                continue
            if os.path.islink(dp):
                # os.walk(followlinks=False) does not descend into a linked
                # directory, but naming it in the warning keeps the omission
                # visible instead of silently dropping part of the submission.
                skipped_links.append(os.path.relpath(dp, sub))
                continue
            if not is_disabled_evidence_rel(os.path.relpath(dp, sub)):
                kept_dirs.append(d)
        dirs[:] = kept_dirs
        for n in sorted(names):
            p = os.path.join(root, n)
            rel = os.path.relpath(p, sub)
            if os.path.islink(p):
                # A submission link is not package content: open()/convert_one
                # would follow it and copy an arbitrary local file into
                # WORK/corpus as the authors' text. The pipeline's copy_into
                # refuses exactly this, so the review corpus must too.
                skipped_links.append(rel)
                continue
            if is_disabled_evidence_rel(rel):
                continue
            if not os.path.isfile(p):
                # A FIFO/socket/device is not package content: opening it can
                # block forever (a FIFO with no writer hangs conversion before
                # the review starts) and it cannot be converted meaningfully.
                skipped_special.append(rel)
                continue
            files.append(rel)
    if skipped_links:
        print("WARNING: skipped %d symlink(s) in SUBMISSION_DIR (a link is not package "
              "content and its target may be outside the submission): %s"
              % (len(skipped_links), ", ".join(sorted(skipped_links)[:5])
                 + (" ..." if len(skipped_links) > 5 else "")))
    if skipped_special:
        print("WARNING: skipped %d non-regular file(s) in SUBMISSION_DIR (a FIFO/device "
              "cannot be read as package content): %s"
              % (len(skipped_special), ", ".join(sorted(skipped_special)[:5])
                 + (" ..." if len(skipped_special) > 5 else "")))
    if not files:
        print("ERROR: SUBMISSION_DIR %s is empty. Stop and ask the user." % sub)
        sys.exit(2)

    inventory = []
    corpus_names = set()      # flattened corpus stems written so far
    evidence_names = set()    # flattened evidence stems written so far
    for rel in files:
        p = os.path.join(sub, rel)
        entry = convert_one(p, rel)
        area = evidence_area_of(rel)
        if area:
            # The EVIDENCE areas (raw_data/, human_review_feedback/) are inputs:
            # the submission does not include them, so they get no document role
            # (never "main text", "cover letter" or "supplementary"), are never
            # editable, and their converted text must not enter the corpus the
            # sweeps read.
            entry["area"] = area
            if area == HUMAN_FEEDBACK_DIR:
                if is_original_submission_rel(rel):
                    entry["role"] = "reviewer-visible original submission (evidence)"
                else:
                    entry["role"] = ("previous response to reviewers (evidence context)"
                                     if REPLY_NAME_RE.search(os.path.basename(rel))
                                     else "human review feedback (evidence)")
            elif area == LLM_FEEDBACK_DIR:
                entry["role"] = ("LLM review feedback (evidence; false positives "
                                 "pre-filtered)")
            else:
                entry["role"] = ("reviewer/editor feedback (raw-data evidence)"
                                 if is_feedback_rel(rel) else "raw data (evidence)")
            entry["editable"] = False
            if area == HUMAN_FEEDBACK_DIR:
                if is_original_submission_rel(rel):
                    entry["notes"].append(
                        "the manuscript version the PREVIOUS journal's editors/reviewers "
                        "actually saw — EVIDENCE, never the current submission; use it only to "
                        "resolve what a raised concern refers to and whether base/ already "
                        "answers it; never swept, counted, quoted as the authors' current prose "
                        "or edited")
                else:
                    entry["notes"].append(
                        "human editors'/reviewers' feedback — external prose, never the authors' "
                        "submission text; read as evidence for the concern reconciliation, the "
                        "response letter and the judge's concern-addressing check; never swept, "
                        "counted or edited")
            elif area == LLM_FEEDBACK_DIR:
                entry["notes"].append(
                    "machine-generated review feedback — its false positives were filtered out "
                    "upstream, so every remaining finding is a real concern with the same standing "
                    "as a human reviewer's point; external prose, never the authors' submission "
                    "text; read as evidence for the concern reconciliation, the response letter "
                    "and the judge's concern-addressing check; never swept, counted or edited")
            elif is_feedback_rel(rel):
                entry["notes"].append(
                    "editors'/reviewers' feedback — external prose, never the authors' "
                    "submission text; read as evidence only (M30/fact-check), never swept, "
                    "counted or edited")
            entry["notes"].append(
                "%s evidence area — not part of the submission; converted text goes to "
                "WORK/%s/, never WORK/corpus/" % (area, EVIDENCE_DIRNAME))
        else:
            entry["area"] = "submission"
            entry["role"] = guess_role(rel)
            # `converted-partial` is a COMMENT on how clean the text extraction
            # was, never a change of the document's kind: a plain-text manuscript
            # with one invalid byte is still an editable source (the decoding-gap
            # note says what was substituted). Excluding it here silently turned
            # every such document read-only in the inventory, and the review then
            # routed its findings to manual items although the file is editable.
            # The non-editable partial conversions (`pdf`) never reach this test
            # because their extension is not in EDITABLE_EXTS.
            entry["editable"] = os.path.splitext(rel)[1].lower() in EDITABLE_EXTS and \
                entry["status"] in ("converted", "converted-empty", "converted-partial")
        entry["size_bytes"] = os.path.getsize(p)
        inventory.append(entry)
        if entry["status"] in ("converted", "converted-empty", "converted-partial"):
            stem = rel.replace(os.sep, "__")
            # A nested path can flatten PAST the filesystem's NAME_MAX (a
            # 203-character basename in a 100-character directory is a valid
            # nested path but a 305-character single component, and open() then
            # fails with ENAMETOOLONG). Cap the generated component by UTF-8
            # BYTES and keep a digest of the full path; the inventory still
            # records the original.
            stem, truncated = _bounded_corpus_stem(stem, rel)
            if truncated:
                entry["notes"].append(
                    "corpus text name truncated to fit the filesystem limit; the inventory "
                    "records the original path")
            if entry["area"] in EVIDENCE_DIRNAMES:
                out_txt = os.path.join(evidence_dir, stem + ".txt")
                used_names = evidence_names
            else:
                out_txt = os.path.join(corpus_dir, stem + ".txt")
                used_names = corpus_names
            if stem in used_names:
                # Two files can flatten to one corpus name ("figs/notes.md" and
                # "figs__notes.md"): the second used to overwrite the first, so a
                # document silently vanished from the review corpus.
                suffix = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:8]
                out_txt = os.path.join(os.path.dirname(out_txt),
                                       "%s.__%s.txt" % (stem, suffix))
                entry["notes"].append(
                    "corpus text written as %s.__%s.txt -- another file converts to the "
                    "same flattened corpus name" % (stem, suffix))
            used_names.add(stem)
            os.makedirs(os.path.dirname(out_txt), exist_ok=True)
            with open(out_txt, "w", encoding="utf-8") as f:
                f.write(entry["text"] if entry["text"] else "(empty file)")

    md = ["# File inventory", "",
          "| path | area | role | ext | editable | size | conversion status | notes |",
          "|---|---|---|---|---|---|---|---|"]
    for e in inventory:
        notes = "; ".join(sorted(set(e["notes"]))) or "—"
        md.append("| %s | %s | %s | %s | %s | %d | %s | %s |" % (
            e["path"], e["area"], e["role"], e["ext"], "yes" if e["editable"] else "no",
            e["size_bytes"], e["status"], notes.replace("|", "\\|")))
    with open(os.path.join(work, "inventory.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    js = [{"path": e["path"], "area": e["area"], "role": e["role"], "ext": e["ext"],
           "editable": e["editable"], "size_bytes": e["size_bytes"],
           "status": e["status"], "notes": sorted(set(e["notes"]))}
          for e in inventory]
    with open(os.path.join(work, "inventory.json"), "w", encoding="utf-8") as f:
        json.dump(js, f, indent=2)

    n_ev = sum(1 for e in inventory if e["area"] in EVIDENCE_DIRNAMES)
    print("Inventoried %d files (%d submission, %d evidence-area)."
          % (len(inventory), len(inventory) - n_ev, n_ev))
    print("Converted text corpus in %s" % corpus_dir)
    if n_ev:
        print("Evidence text (never swept as submission content) in %s" % evidence_dir)
    print("Artifacts: inventory.md, inventory.json")
    n_fail = sum(1 for e in inventory if e["status"] in ("failed", "read-only/unreadable"))
    if n_fail:
        print("WARNING: %d files could not be converted — recorded (never skipped)." % n_fail)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
# Part 02/03 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

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
        elif NON_TEXT_TOKENS.fullmatch(tok):
            # `text_of` renders these as ONE placeholder character (a hyphen or
            # U+FFFD), and that character keeps the offsets aligned. Emit the
            # token itself, never a `<w:t>` wrapper around it.
            frags.append((m.start(), m.end(),
                          "-" if tok.startswith("<w:noBreakHyphen") else "\ufffd",
                          tok))
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
    # Insertions are emitted at most once ACROSS fragments: one anchored on a
    # `w:t` boundary is reached both as the previous piece's end and as the next
    # piece's start, so a per-piece set emitted it twice ("abcX" + "Xdef").
    emitted_zero = set()

    def carry(local: int, old: str) -> str:
        """The new text of ONE piece starting at text offset `local`."""
        out, at = [], local
        end = local + len(old)

        def emit_zero_edits(at_pos: int) -> None:
            """Emit every zero-length insertion anchored exactly at `at_pos`.

            `keep_starts` holds the edit and the FOLLOWING untouched piece at
            the same start (and the untouched piece wins `bisect_right`), so a
            zero-length insertion used to be skipped while `applied` reported it
            as done -- the FMT-X2 repair was silently a no-op.
            """
            for i, (a, b, new_piece, is_edit) in enumerate(keep):
                if is_edit and a == b == at_pos and i not in emitted_zero:
                    emitted_zero.add(i)
                    out.append(new_piece)

        while at < end:
            emit_zero_edits(at)
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
        # An insertion anchored at the END of this piece has no `at < end`
        # iteration to reach it; emit it here (once, across fragments).
        emit_zero_edits(end)
        return "".join(out)

    pieces, cursor, here = [], 0, 0
    for start_at, end_at, old_text, raw in frags:
        pieces.append(para[cursor:start_at])
        cursor = end_at
        local = here
        here += len(old_text)
        if raw is None:
            # The break is consumed by an edit that covers its position. An
            # EMPTY replacement consumes it too (the old `if covered` treated
            # "" as "no edit" and left the break in place); and a replacement
            # that began inside the preceding text fragment was already emitted
            # by `carry`, so emit it here only when the edit begins AT the
            # break, never twice.
            cover = next(((s, e, r) for s, e, r, is_edit in keep
                          if is_edit and s <= local < e), None)
            if cover is not None:
                s, _e, repl = cover
                if repl and s == local:
                    pieces.append('<w:t xml:space="preserve">' + esc(repl) + "</w:t>")
            else:
                pieces.append(para[start_at:end_at])
            continue
        if NON_TEXT_TOKENS.fullmatch(raw):
            # The one placeholder character is part of the paragraph text; an
            # edit that covers it consumes it, otherwise the glyph survives.
            cover = next(((s, e, r) for s, e, r, is_edit in keep
                          if is_edit and s <= local < e), None)
            if cover is None:
                pieces.append(raw)
            else:
                s, _e, repl = cover
                if repl and s == local:
                    pieces.append('<w:t xml:space="preserve">' + esc(repl) + "</w:t>")
            continue
        new_text = carry(local, old_text)
        open_tag = raw[:raw.find(">") + 1]
        close_tag = raw[raw.rfind("<"):]
        keep_space = ' xml:space="preserve"' if (new_text != new_text.strip()
                                                 or "xml:space" in open_tag) else ""
        tag = "<w:t" + keep_space + ">"
        pieces.append(tag + esc(new_text) + close_tag if new_text else tag + close_tag)
    pieces.append(para[cursor:])
    # A zero-length insertion anchored at the FINAL text offset has no following
    # `w:t` fragment to reach it: a trailing break/tab/noBreakHyphen/sym leaves
    # `carry()` uncalled for that offset, so the insertion was reported in
    # `applied` but never written. Emit it as a run at the end of the paragraph.
    _tail_zero = []
    for i, (a, b, new_piece, is_edit) in enumerate(keep):
        if is_edit and a == b == here and i not in emitted_zero:
            emitted_zero.add(i)
            _tail_zero.append(new_piece)
    new_para = "".join(pieces)
    if _tail_zero:
        _ins = ('<w:r><w:t xml:space="preserve">' + esc("".join(_tail_zero))
                + "</w:t></w:r>")
        _close = new_para.rfind("</w:p>")
        if _close != -1 and not new_para[_close + len("</w:p>"):].strip():
            new_para = new_para[:_close] + _ins + new_para[_close:]
        else:
            new_para += _ins

    def _drop_empty_runs(mm):
        body = mm.group(0)
        if re.search(r"<w:(?:drawing|pict|object|br|cr|tab|ptab|fldChar|instrText|"
                     r"lastRenderedPageBreak|"
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
# window a caller is about to DELETE, so the set stays small and explicit. A
# SINGLE-letter tail is not evidence by itself: "github.com/a/y." and "...cluster
# A." are sentence ends, not initials, and merging them into the next sentence
# made `strip_reference_sentences` delete that sentence too. The conservative
# single-initial case is handled by `_single_initial_continues` below, which
# needs a name context (start of text, a comma/paren, or an introducer such as
# "by"); a wrong SPLIT only narrows a deletion window, a wrong MERGE widens it.
SENTENCE_ABBREV_TAIL_RE = re.compile(
    r"(?:(?i:\b(?:e\.g|i\.e|c\.f|cf|vs|al|approx|ca|dr|prof|mr|mrs|ms|st|no|vol|pp|p|fig|figs|"
    r"eq|eqs|ref|refs|sec|tab|suppl|supp|ext)\.)|(?:\b[A-Z]\.\s*){2,3})$")
# A sentence that resumes with one of these after a terminator+space did not end
# there ("... (Figure 2). ..." vs "... the value).").
SENTENCE_CONTINUATION_CHARS = ")]}\u201d\u2019'\""
# Words that introduce a personal initial ("written by J. Smith"). Only these
# let a ONE-letter tail continue the sentence; any other preceding word makes it
# a sentence end.
_SENTENCE_INITIAL_INTRODUCERS = {
    "by", "from", "with", "and", "of", "for", "et", "al", "dr", "prof", "mr",
    "mrs", "ms", "miss", "sir", "dame",
}


def _single_initial_continues(text: str, start: int, boundary: int) -> bool:
    """True when the text before `boundary` ends in one INITIAL, not a sentence.

    `text[start:boundary]` is the candidate sentence. A single capital followed
    by "." is an initial only in a name context: at the start of the text, after
    an opening/comma, or after one of the introducer words. `... cluster A.` and
    `... github.com/a/y.` have none of those, so the period ends the sentence.
    """
    tail = text[start:boundary].strip()
    m = re.search(r"(?<![A-Za-z0-9])([A-Z])\.$", tail)
    if not m:
        return False
    before = tail[:m.start()].rstrip()
    if not before:
        return True
    if before[-1] in ",([{:\"'":
        return True
    word = re.search(r"([A-Za-z]+)$", before)
    return bool(word and word.group(1).lower() in _SENTENCE_INITIAL_INTRODUCERS)


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
        if _single_initial_continues(text, start, m.start()):
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
    # The last window's leading-whitespace eat can reach into the whitespace a
    # previous window already consumed, producing overlapping windows
    # ([(0,50),(49,99)]). `rewrite_text_spans` keeps only the first of an
    # overlapping group, so the second edit vanished and the whole removal was
    # refused as "the edit did not reproduce the text". Clamp instead: the
    # whitespace belongs to the earlier window, and a window fully consumed by
    # its predecessor is dropped (nothing of its sentence is left to remove).
    clamped, prev_end = [], 0
    for a, b in fixed:
        a = max(a, prev_end)
        if b <= a:
            continue
        clamped.append((a, b))
        prev_end = b
    return clamped


def _wt_fragments(frag: str) -> list:
    """[(xml_start, xml_end, unescaped_text)] for every `<w:t>` in a paragraph.

    The same enumeration `rewrite_text_spans` works on (`_text_fragments`), kept
    local so the caller's text offsets and the XML offsets a field lookup needs
    can never drift apart.
    """
    return [(m.start(), m.end(), unesc(m.group(1)))
            for m in re.finditer(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", frag, re.S)]


def _xml_span_for_text_range(frag: str, a: int, b: int):
    """The XML range of a paragraph whose TEXT range [a, b) lives, or None.

    Walks the SAME pieces as `text_of`/`rewrite_text_spans`: a `w:br`/`w:cr`/
    `w:tab` is one character of text (its rendered newline), so an offset after
    a break maps to the right XML fragment.
    """
    lo = hi = None
    pos = 0
    for m in _FRAG_OR_BREAK_RE.finditer(frag):
        tok = m.group(0)
        if BREAK_TOKENS.fullmatch(tok):
            length = 1
        elif NON_TEXT_TOKENS.fullmatch(tok):
            length = 1                          # the hyphen/U+FFFD placeholder
        else:
            length = len(unesc(tok[tok.find(">") + 1:tok.rfind("<")]))
        if pos + length > a and lo is None:
            lo = m.start()
        if pos < b:
            hi = m.end()
        pos += length
    if lo is None or hi is None:
        return None
    return (lo, hi) if lo <= hi else None


_FACT_LABEL_RE = re.compile(
    r"\b(?:fig(?:ure)?|table|section|eq(?:uation)?|appendix|supp(?:lementary)?|"
    r"data|code)\.?\s*[A-Za-z]?\d+[A-Za-z0-9.-]*", re.I)


def sentence_carries_scientific_fact(text: str) -> bool:
    """True when a sentence carries a number outside a figure/table/section label.

    PKG-2 may remove a pointer-only sentence; it must not remove a data value,
    count or p-value. Such a sentence stays and is reported for rewriting.
    """
    stripped = _FACT_LABEL_RE.sub(" ", str(text or ""))
    return bool(re.search(r"\d", stripped))


def _write_zip_parts_atomic(out: Path, parts: dict) -> None:
    """Write one DOCX package through an O_EXCL descriptor, then replace `out`.

    The PKG-2 writers used `zipfile.ZipFile(out, "w")` on a pathname another
    agent can list: unlinking the reserved temp and planting a symlink there
    redirected the package bytes (F02/F09). `mkstemp()` owns the name and the
    archive is written through that descriptor, so no reopen-by-path can be
    swapped for a link.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
                for part_name, data in parts.items():
                    z.writestr(part_name, data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def strip_reference_sentences(src: Path, out: Path, finder) -> dict:
    """Remove every SENTENCE of `src` that `finder` names as a dangling pointer.

    `finder(text) -> [(start, end), ...]` names the reference spans inside one
    paragraph's own text (the pipeline passes its PKG-2 matcher). Every span is
    widened to the sentence that carries it and that sentence is deleted from
    the document text; nothing else in the package is touched.

    A sentence that carries a live citation FIELD is NOT removed: dropping a
    field would renumber the bibliography and break the base-to-candidate
    field-continuity gate, so the pointer stays and the caller reports it (the
    author or the next revision session fixes that one in prose). A sentence
    carrying a numeric fact is held for the same reason -- a packaging repair
    must not delete a data value. The same refusal covers a text range the
    OOXML cannot address as plain text.

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
        # `text_of`, not a plain join of the w:t pieces: `rewrite_text_spans`
        # (and the expected-text fence below) count each w:br/w:cr/w:tab as one
        # newline. Joining only w:t put the spans in a different coordinate
        # space, so every cleanup in a break-containing paragraph refused itself.
        text = text_of(frag)
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
            if sentence_carries_scientific_fact(text[a:b]):
                res["skipped"].append(
                    f"paragraph {index}: the sentence carrying a dangling reference also "
                    f"carries a numeric fact ({text[a:b].strip()[:80]!r}); a packaging repair "
                    f"must not delete it -- rewrite the pointer in prose")
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
        if parts_has_field(frag) and (
                zotero_field_signature(zotero_field_report(new_frag))
                != zotero_field_signature(fields_before)):
            # Compare the FIELD SIGNATURE, not the raw report: the report
            # carries begin/end offsets and the paragraph text, both of which
            # change with any prose edit, so the old comparison rejected every
            # citation-bearing paragraph even when no field was touched.
            res["skipped"].append(
                f"paragraph {index}: the removal would change the paragraph's citation fields")
            continue
        expected, pos = [], 0
        for a, b in keep:
            expected.append(text[pos:a])
            pos = b
        expected.append(text[pos:])
        expected_text = "".join(expected)
        if text_of(new_frag) != expected_text:
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
        _write_zip_parts_atomic(out, parts_new)
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
_REL_ENTRY_RE = re.compile(
    r"<Relationship\b[^>]*(?:/>|>.*?</Relationship>)", re.S)


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
            # about the paired form). Only elements that reference THIS dropped
            # relationship are removed: the old unconditional `<w:attachedTemplate
            # .../>` alternative also deleted an attachedTemplate whose `r:id`
            # named a REMOTE template, killing a link that was not a local path.
            rid_pat = re.escape(rid)
            new_settings = re.sub(
                r"<w:attachedTemplate\b[^>]*r:id=\"" + rid_pat + r"\"[^>]*/>"
                r"|<w:attachedTemplate\b[^>]*r:id=\"" + rid_pat
                + r"\"[^>]*>.*?</w:attachedTemplate>", "", new_settings)
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
        _write_zip_parts_atomic(out, parts_new)
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
        style = para_style(para) or "Normal"
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
    if rule in ("FMT-TB4", "FMT-TB5", "FMT-S10"):
        return "mechanical"
    if rule == "FMT-T6h":
        return "style-field"
    if rule in ("FMT-IM4", "FMT-IM5", "FMT-AV3"):
        return "manual"
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
                    "FMT-S6", "FMT-S8", "FMT-P4", "FMT-G1", "FMT-IM1",
                    "FMT-TB4", "FMT-TB5", "FMT-S10"}


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
_CAPTION_LABEL_RE = (r"(?:supplementary\s+|extended\s+data\s+|supp\.?\s+)?%s\.?\s*")
# The formatter's caption grammar must accept the SAME display numbers the
# pipeline's M19 scan counts (`Table I. Title` is a caption there). The old
# `[IVXLC]{2,}` refused a single roman numeral and the D/M forms, so a common
# "Table I" caption was a caption to the length scan and invisible to FMT-TB1/2/3.
# Tables use the pipeline's full roman grammar (`[IVXLCDM]+`, so Table C/D/L/M
# are captions too). Figures keep the narrower single-letter class (I/V/X only):
# "Figure C. We next tested ..." is a body sentence/panel label the format
# regression F-215 requires us to leave alone, so the two grammars differ.
DISPLAY_TABLE_NUM_RE = r"(?:S?\d+[A-Za-z]?|(?-i:[IVXLCDM]+))"
DISPLAY_CAPTION_NUM_RE = r"(?:S?\d+[A-Za-z]?|(?-i:[IVXLCDM]{2,}|[IVX]))"
TABLE_CAPTION_RE = re.compile(
    r"^\s*" + (_CAPTION_LABEL_RE % "tables?") + DISPLAY_TABLE_NUM_RE
    + r"\s*(?:\||:|\u2014|\u2013|-|\.)(?=\s|$)", re.I)
TABLE_CAPTION_BARE_RE = re.compile(
    r"^\s*" + (_CAPTION_LABEL_RE % "tables?") + DISPLAY_TABLE_NUM_RE + r"\s*$", re.I)
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
    r"endnoteReference|commentReference|sdt|ins|del|moveFrom|moveTo|cellIns|cellDel|"
    # The merge keeps the label's pPr and drops the continuation's, so any
    # tracked property change there is revision history the "mechanical" fix
    # would silently delete. Refuse every *PrChange (and the table-cell merge
    # mark) the pipeline's own OTHER_REVISION_MARK_RE treats as a revision.
    r"pPrChange|rPrChange|tblPrChange|trPrChange|tcPrChange|sectPrChange|"
    r"numberingChange|cellMerge)"
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
    """The run's effective bold/italic: direct rPr > character style > paragraph
    style (Word's precedence). `w:rPrChange` holds the OLD formatting and is
    never read; a character style such as Emphasis must outrank the paragraph
    style, or pinning the paragraph-style difference turns its italics off."""
    node = {"b": "b", "i": "i"}[key]
    rpr = live_rpr(rpr_of(run))
    direct_el = elem(rpr, node)
    if direct_el is not None:
        val = attr(direct_el, "val")
        return True if val is None else str(val).strip().lower() not in ("0", "false", "off")
    run_style = elem_val(rpr, "rStyle")
    if run_style:
        val = None
        for sid in style_chain(styles, run_style):
            st = styles.get(sid) or {}
            if st.get(key) is not None:
                val = st[key]
        if val is not None:
            return bool(val)
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
    ppr = ppr_of(para)
    if ppr is None:
        # No pPr at all is the normal body shape. A `<w:pPr` that ppr_of could
        # not balance is not: falling through would treat the malformed block
        # as content and drop it from the merged paragraph.
        if inner.startswith("<w:pPr"):
            return None
        ppr = ""
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
        styles[i] = para_style(frag) or ""
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

    used_captions = set()
    caption_cache = {}

    def caption_adjacent(i):
        """(block index, text, side) of the item's caption paragraph, or Nones."""
        if i in caption_cache:
            return caption_cache[i]
        own = texts.get(i, "")
        if display_caption_text(own, kind):
            # An image and its legend can share one paragraph in Word ("self"):
            # the caption is then neither before nor after, but it IS there.
            used_captions.add(i)
            caption_cache[i] = (i, own, "self")
            return caption_cache[i]
        for step, side in ((-1, "before"), (+1, "after")):
            j, t = attach(i, step)
            if j is None or j in used_captions:
                continue
            if display_caption_text(t, kind):
                # ONE caption belongs to ONE item: `[captionless table][caption]
                # [table]` made the caption the AFTER caption of the first table
                # and the BEFORE caption of the second, so its fix could move a
                # sibling's legend. Cache the answer because the item's inventory
                # and rule passes both ask the same question.
                used_captions.add(j)
                caption_cache[i] = (j, t, side)
                return caption_cache[i]
        caption_cache[i] = (None, "", "")
        return caption_cache[i]

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
    styles_of = [para_style(p) or "" for (_a, _b, p) in paras]
    # The front matter (title block, abstract, keywords) is its own layout family:
    # abstracts are conventionally flush while body paragraphs are first-line
    # indented, so never count the abstract as a body-paragraph outlier. The
    # family ends at the first heading after the keywords line (Introduction ...).
    kw_i = next((i for i, (_a, _b, p) in enumerate(paras)
                 if KEYWORDS_RE.match(text_of(p).strip())), None)
    heading_after_kw = next((i for i in range((kw_i + 1) if kw_i is not None else 0, len(paras))
                             if styles_of[i].startswith("Heading")), None)
    # A directly formatted Introduction carries no Heading style. The front
    # matter still ends after the Keywords line; falling back to 0 counted the
    # flush abstract as a body paragraph and named it the indentation minority.
    front_end = (heading_after_kw if heading_after_kw is not None
                 else (kw_i + 1 if kw_i is not None else 0))
    cats = {"caption": [], "body": []}
    for i, (_p0, _p1, p) in enumerate(paras):
        if i < front_end:
            continue
        text = text_of(p).strip()
        if not text:
            continue
        style = para_style(p) or ""
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


def cover_letter_page_row(path: Path, pages, source: str, max_pages: int = 2) -> dict:
    """FMT-T8h: the cover letter's venue-recalled page budget."""
    return {"rule": "FMT-T8h", "severity": "medium", "document": path.name,
            "location": "document",
            "evidence": f"the cover letter is {pages} page(s) ({source}); the budget is {max_pages}",
            "detail": (f"a cover letter that runs past {max_pages} page(s) is not acceptable; "
                       "trim the non-persuading boilerplate (statement blocks, reviewer lists, "
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
    _WORD_EDGE + r"(?:[Cc]over|COVER|(?i:coverletter))(?![a-z])"
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
    return para_style(para) or ""


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
                and not has_anchor(paras[i][2])                # footnote/comment/bookmark
                and not PAGEBREAK_RE.search(paras[i][2])       # FMT-S1 owns breaks
                and "<w:sectPr" not in paras[i][2]             # a section break is layout
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
    r"<w:tab(?=[\s/>])[^>]*/>|<w:noBreakHyphen(?=[\s/>])[^>]*/>|"
    r"<w:sym(?=[\s/>])[^>]*/>", re.S)

# Articles and prepositions where a doubled word is a typo. "in" is deliberately
# absent: "studies in in vitro systems" is a valid construction, and a
# mechanical rule must never rewrite it.
_DOUBLED_WORDS = ("the", "a", "an", "of", "and", "or", "but", "for", "with", "at",
                  "by", "on", "to", "is", "are", "was", "were", "it")
# The SECOND token must not start uppercase. The case-insensitive pattern is
# needed for a sentence-initial "The the" typo, but it also matched the real
# tokens in "a A-to-I" and "NOR or OR" and the fixer deleted one.
_DOUBLED_WORD_RE = re.compile(
    r"\b(" + "|".join(_DOUBLED_WORDS) + r")\s+(?!(?-i:[A-Z]))\1\b"
    r"(?:\s+(?!(?-i:[A-Z]))\1\b)*", re.I)   # consume every consecutive repeat
_DOUBLE_SPACE_RE = re.compile(r"(?<=\S) {2,}(?=\S)")
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +(?=[,.;:!?])")
_SPACE_AFTER_OPEN_RE = re.compile(r"(?<=[([])[ \t]+")
_ZERO_WIDTH_RE = re.compile("[\u200b\u200e\u200f\u2060\ufeff]")
_MATH_LINE_RE = re.compile(r"[=∑∈∉∕√±×÷≤≥≈∝∫∞]")
_MISSING_SPACE_RE = re.compile(
    # A URL's query/fragment is not prose: `?x=ab,cd`, `#ab,cd` and `&ab,cd`
    # are one address, so the character before the lowercase run excludes the
    # URL delimiters too (the original class covered only a path segment).
    r"(?<![A-Za-z0-9/=&#?])([a-z]{2,}),([a-z]{2,})\b")

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
        # `<w:tab/>` also starts with "<w:t", so the old prefix test read it as
        # a text token of length 0: the tab neither advanced the text offset nor
        # split the line, and every line-edge span after it was mispositioned.
        if re.match(r"<w:t(?=[\s>])", tok):
            offset += len(unesc(tok[tok.find(">") + 1:tok.rfind("<")]))
        elif NON_TEXT_TOKENS.fullmatch(tok):
            # `text_of` renders noBreakHyphen/sym as ONE character but they do
            # not start a new visual line; advancing zero shifted every later
            # span and could make a whitespace-only "line" cover a real break.
            offset += 1
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
        cut, kind = _email_glue_cut(text, m)
        if cut is None:
            # The match carries a glue shape we cannot split without guessing
            # (`Xiezhenxie@host`): no span is emitted, the FMT-X2 row stands and
            # the review/revise arms fix it in prose. (The first cut of this
            # repair turned a healthy `zhenxie@tsinghua.edu.cn` into
            # `zhen xie@tsinghua.edu.cn`.)
            continue
        where = ("glued to the word before it" if kind == "before"
                 else "glued to the text after it")
        out.append({"rule": "FMT-X2", "fix": "mechanical", "start": cut, "end": cut, "repl": " ",
                    "evidence": f"{text[max(0, m.start() - 24):m.end() + 12]!r}: the address is "
                                f"{where}",
                    "detail": ("insert the missing space between the name and the e-mail address"
                               if kind == "before" else
                               "insert the missing space between the e-mail address and the "
                               "following text")})
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
        # A soft break between the two words is part of the match. Replacing the
        # whole match with the bare word deleted the break, and a replacement
        # that spans the break is refused by rewrite_text_spans. Delete only the
        # SECOND word (and any spaces after the last break), keeping the break.
        second_start = m.end() - len(m.group(1))
        sep = text[m.end(1):second_start]
        start, end, repl = m.start(), m.end(), m.group(1)
        if "\n" in sep or "\r" in sep:
            # Delete the repeats after the LAST break, keeping the break itself
            # (FMT-P4 owns the whitespace at the line edge). Starting at the
            # space made both spans share a start, and the overlap policy
            # (narrower wins) then dropped G1 while the summary still claimed
            # the duplicate was cleaned. A tripled word deletes every repeat,
            # not just the last one.
            start = m.end(1) + max(sep.rfind("\n"), sep.rfind("\r")) + 1
            while start < len(text) and text[start] in " \t":
                start += 1              # FMT-P4 owns the line-edge space
            end = m.end()
            while end < len(text) and text[end] in " \t":
                end += 1              # the space after the deleted duplicate
            repl = ""
        out.append({"rule": "FMT-G1", "fix": "mechanical", "start": start, "end": end,
                    "repl": repl,
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
    for m in _REL_ENTRY_RE.finditer(xml):
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
            # A GROUP drawing has one canvas extent plus a geometry per child;
            # the first child's pixel ratio says nothing about the other
            # extents. Rewriting every `a:ext` from that ratio squashed the
            # portrait panels of a grouped figure, so skip the group (the
            # visual check owns composite geometry).
            if re.search(r"<wpg:(?:wgp|grpSp)(?=[\s/>])", block) or \
                    "drawingml/2006/wordprocessingGroup" in block:
                continue
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
            # FMT-IM4: a raster placed below the policy's effective-resolution
            # floor. Vector art (EMF/WMF/SVG) has no pixel grid and is skipped.
            min_dpi = float(policy.get("min_image_dpi") or 0)
            if (min_dpi and unit == "EMU" and target
                    and RASTER_IMAGE_EXT_RE.search(str(target))):
                dpi = pw / (cxf / 914400.0) if cxf else 0
                if 0 < dpi < min_dpi:
                    rows.append({
                        "rule": "FMT-IM4", "severity": "medium", "document": doc,
                        "location": f"{location_prefix}{idx}",
                        "evidence": (f"image {(target or '').rsplit('/', 1)[-1]}: "
                                     f"{pw}x{ph} px placed {cxf / 914400.0:.2f} in wide "
                                     f"= {dpi:.0f} dpi (policy floor {min_dpi:g} dpi)"),
                        "detail": ("a raster below the venue's effective-resolution floor "
                                   "prints soft/pixelated; re-export at the stated dpi at "
                                   "the placed width, never upsample a screenshot"),
                        "fix": "manual", "protected": False, "tier": tier_of("FMT-IM4"),
                        "_dpi": dpi})
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
# FIGURE TEXT SIZE (FMT-IM6).
#
# FMT-IM4 answers "is the raster sharp enough" (dpi); it does not answer "can a
# reader read the labels at the printed width". The CNB round-2 winner shipped
# Figs. 2-5 at 2.0-3.2 pt and the SI panels at 2-4 pt while every dpi check
# passed, because a 300-dpi image drawn at half its native width still halves
# the type. This rule measures the OCR word-box height in the placed raster and
# converts it to points at the placed width; the venue profile supplies the
# floor (Nature 5 pt, Frontiers 8 pt) and its source, never this file.
# --------------------------------------------------------------------------

def _median(values: list) -> float:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return 0.0
    i = len(vals) // 2
    return vals[i] if len(vals) % 2 else (vals[i - 1] + vals[i]) / 2.0


_OCR_HEIGHT_CACHE: dict = {}


def _ocr_word_heights(data: bytes) -> list:
    """Word-box heights (px) from tesseract TSV, or [] when OCR cannot read it.

    The same image bytes are measured by `analyse_package` and by the
    standalone-figure loop; a content hash keeps one scan from paying tesseract
    twice for the same raster.
    """
    if not shutil.which("tesseract"):
        return []
    try:
        key = hashlib.sha256(data).hexdigest()
    except (TypeError, ValueError):
        key = ""
    if key and key in _OCR_HEIGHT_CACHE:
        return _OCR_HEIGHT_CACHE[key]
    try:
        proc = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "11", "tsv"],
            input=data, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []
    out = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            h = int(cols[9])
            conf = float(cols[10])
        except (TypeError, ValueError):
            continue
        text = cols[11].strip()
        if conf >= 50 and text and len(text) >= 1 and 3 <= h <= 200:
            out.append(h)
    if key:
        _OCR_HEIGHT_CACHE[key] = out
    return out


def figure_text_size_rows(docx_path: Path, policy: dict = None) -> list:
    """FMT-IM6: embedded raster figures whose own text is below the floor."""
    policy = dict(POLICY_DEFAULTS, **(policy or {}))
    floor = float(policy.get("min_figure_text_pt")
                  or ((policy.get("figure_text") or {}).get("min_pt")) or 0)
    if floor <= 0:
        return []
    rows = []
    if not shutil.which("tesseract"):
        return [{
            "rule": "FMT-IM6", "severity": "low", "document": Path(docx_path).name,
            "location": "figures",
            "evidence": "tesseract is not installed",
            "detail": ("the figure-text size class was NOT examined: OCR is the only "
                       "way to measure the placed raster's own type size; install "
                       "tesseract or measure the artwork manually"),
            "fix": "manual", "protected": False, "tier": "advisory"}]
    try:
        with zipfile.ZipFile(docx_path) as pkg:
            xml = pkg.read("word/document.xml").decode("utf-8", "replace")
            sizes = media_pixel_sizes(pkg)
            rels = part_rels(pkg, "word/document.xml")
            seen = set()
            for idx, (_p0, _p1, para) in enumerate(paragraphs(xml)):
                for m in re.finditer(
                        r"<w:(?:drawing|pict)(?=[\s/>]).*?</w:(?:drawing|pict)>",
                        para, re.S):
                    block = m.group(0)
                    emb = re.search(r'r:(?:embed|id|link)="([^"]+)"', block)
                    if not emb:
                        continue
                    target = rels.get(emb.group(1))
                    if not target or not RASTER_IMAGE_EXT_RE.search(str(target)):
                        continue                       # vector art has no pixel grid
                    size = _pixel_size_for(sizes, target)
                    if not size:
                        continue
                    pw, ph = size
                    ext = re.search(r"<wp:extent(?=[\s/>])[^>]*/>", block)
                    if ext:
                        cx = _attr_any(ext.group(0), "cx")
                        try:
                            cx = float(cx)
                        except (TypeError, ValueError):
                            continue
                    else:
                        # Legacy `w:pict`/VML figures carry the placed width in
                        # the shape's style, not in `<wp:extent>`
                        # (drawing_geometry_rows already reads that fallback).
                        vm = re.search(r"<v:shape(?=[\s/>])[^>]*>", block)
                        style = re.search(r'style="([^"]*)"', vm.group(0)) if vm else None
                        wm = re.search(r"width:\s*([0-9.]+)\s*([a-z%]+)",
                                       style.group(1) if style else "", re.I)
                        factor = {"in": 914400.0, "pt": 12700.0, "cm": 360000.0,
                                  "mm": 36000.0, "px": 9525.0}.get(
                                      (wm.group(2).lower() if wm else ""))
                        if not wm or factor is None:
                            continue
                        cx = float(wm.group(1)) * factor
                    if cx <= 0:
                        continue
                    key = (str(target), round(cx))
                    if key in seen:
                        continue
                    seen.add(key)
                    zip_name = "word/" + str(target).lstrip("/").replace("\\", "/")
                    try:
                        data = pkg.read(zip_name)
                    except KeyError:
                        continue
                    heights = _ocr_word_heights(data)
                    if not heights:
                        continue
                    printed_in = cx / 914400.0
                    dpi = pw / printed_in if printed_in else 0
                    if dpi <= 0:
                        continue
                    med = _median(heights)
                    p25 = sorted(heights)[max(0, int(len(heights) * 0.25) - 1)]
                    pt_med = med / dpi * 72.0
                    pt_small = p25 / dpi * 72.0
                    if pt_small >= floor:
                        continue
                    rows.append({
                        "rule": "FMT-IM6", "severity": "high",
                        "document": Path(docx_path).name,
                        "location": f"p{idx} ({Path(str(target)).name})",
                        "evidence": (f"{pw}x{ph} px placed {printed_in:.2f} in wide "
                                     f"({dpi:.0f} dpi); OCR text height {pt_small:.1f}-"
                                     f"{pt_med:.1f} pt at the printed width (floor "
                                     f"{floor:g} pt)"),
                        "detail": ("the figure's own labels are below the venue's printed-"
                                   "point floor. Re-export from the vector source at the "
                                   "placed width so the text is 5-7 pt (or the venue's "
                                   "stated minimum); do not merely upsample the raster"),
                        "fix": "manual", "protected": False, "tier": tier_of("FMT-IM6")})
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        return rows
    return rows


def image_resolution_rows(path: Path, printed_in: float = 6.5,
                          policy: dict = None) -> list:
    """FMT-IM4 for a standalone submitted raster (no DOCX extent to read).

    The neohet package ships `figures/*.png` separately, so the DOCX-only
    `drawing_geometry_rows` never saw their effective dpi. The venue's own floor
    (Frontiers 300, Nature 450) is in the profile and its source.
    """
    policy = dict(POLICY_DEFAULTS, **(policy or {}))
    floor = float(policy.get("min_image_dpi") or 0)
    if floor <= 0 or printed_in <= 0:
        return []
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    size = image_pixel_size(data)
    if not size:
        return []
    pw, ph = size
    dpi = pw / float(printed_in)
    if dpi >= floor:
        return []
    return [{
        "rule": "FMT-IM4", "severity": "medium", "document": Path(path).name,
        "location": "artwork",
        "evidence": (f"{pw}x{ph} px at a {printed_in:.2f} in print width = {dpi:.0f} dpi "
                     f"(venue floor {floor:g} dpi)"),
        "detail": ("a raster below the venue's stated resolution prints soft/pixelated; "
                   "re-export at the stated dpi at the final width (do not upsample a "
                   "screenshot)"),
        "fix": "manual", "protected": False, "tier": tier_of("FMT-IM4")}]


def figure_text_size_for_image(path: Path, printed_in: float = 6.5,
                               policy: dict = None) -> list:
    """FMT-IM6 for a standalone submitted figure (no DOCX extent to read)."""
    policy = dict(POLICY_DEFAULTS, **(policy or {}))
    floor = float(policy.get("min_figure_text_pt")
                  or ((policy.get("figure_text") or {}).get("min_pt")) or 0)
    if floor <= 0:
        return []
    if not shutil.which("tesseract"):
        return [{
            "rule": "FMT-IM6", "severity": "low", "document": Path(path).name,
            "location": "artwork text",
            "evidence": "tesseract is not installed",
            "detail": ("the standalone figure's text size was NOT examined; install "
                       "tesseract or measure the artwork manually"),
            "fix": "manual", "protected": False, "tier": "advisory"}]
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    size = image_pixel_size(data)
    if not size:
        return []
    pw, _ph = size
    heights = _ocr_word_heights(data)
    if not heights or printed_in <= 0:
        return []
    dpi = pw / float(printed_in)
    med = _median(heights)
    p25 = sorted(heights)[max(0, int(len(heights) * 0.25) - 1)]
    pt_med = med / dpi * 72.0
    pt_small = p25 / dpi * 72.0
    if pt_small >= floor:
        return []
    return [{
        "rule": "FMT-IM6", "severity": "high", "document": Path(path).name,
        "location": "artwork text",
        "evidence": (f"{pw}x{_ph} px at a {printed_in:.2f} in print width "
                     f"({dpi:.0f} dpi); OCR text height {pt_small:.1f}-{pt_med:.1f} pt "
                     f"(floor {floor:g} pt)"),
        "detail": ("the figure's own labels are below the venue's printed-point floor; "
                   "re-export the artwork at the final size with legible type"),
        "fix": "manual", "protected": False, "tier": tier_of("FMT-IM6")}]


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

_DISPLAY_ITEM_TOKEN = r"(?:S?\d{1,3}[A-Za-z]?(?!\d)|[IVXLC]{2,})"
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
DISPLAY_SUPP_PREFIX_RE = re.compile(
    r"(?i)(?:supplementary|supplemental|suppl\.?)"
    r"(?:\s+(?:information|materials?|data|methods?|figures?|tables?|notes?|appendix))?\s*$")
DISPLAY_EDATA_PREFIX_RE = re.compile(r"(?i)extended\s+data\s*$")


def _display_family_prefix(before: str):
    """The family a call-out phrase's PREFIX names, or "" for the token's own."""
    # 64 chars, not 24: "Supplementary Information " alone is 27, so the
    # prefix was already truncated before the family regex saw it.
    zone = (before or "")[-64:]
    if DISPLAY_EDATA_PREFIX_RE.search(zone):
        return "edata"
    if DISPLAY_SUPP_PREFIX_RE.search(zone):
        return "supp"
    return ""


_ROMAN_PAIRS = ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))


def _roman_canonical(value: int) -> str:
    out = []
    for amount, digits in _ROMAN_PAIRS:
        while value >= amount:
            out.append(digits)
            value -= amount
    return "".join(out)


def _roman_value(token: str):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, prev = 0, 0
    for ch in reversed(token.upper()):
        if ch not in vals:
            return None
        v = vals[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    # Reject non-standard forms (IIX, IL, VX, VV, IC, IIII): they have a
    # numeric value but are not the numeral an author wrote, and two spellings
    # of one number collided in the first-citation map.
    if total <= 0 or total >= 400 or _roman_canonical(total) != token.upper():
        return None
    return total


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
    callout_order = 0
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
                            and 0 < abs(key[2] - prev[2]) <= _DISPLAY_RANGE_MAX):
                        if key[2] > prev[2]:
                            filled.extend((key[0], key[1], n, str(n))
                                          for n in range(prev[2] + 1, key[2]))
                            filled.append(key)
                        else:
                            # "Figures 5 to 3" mentions 3, 4 and 5. Record them
                            # in ASCENDING order: a descending range is not
                            # itself a numbering violation.
                            if filled and filled[-1] == prev:
                                filled.pop()
                            filled.extend((key[0], key[1], n, str(n))
                                          for n in range(key[2], prev[2] + 1))
                        prev = key
                        continue
                    if (is_range and prev is not None and prev[0] == key[0]
                            and prev[1] == key[1]):
                        # A wider-than-100 gap is not a display-item range. Do
                        # not record its far endpoint as a first citation: the
                        # earlier "Figure 1" stays, and a later "Figure 2" is
                        # not reported as cited after 200.
                        prev = None
                        continue
                    filled.append(key)
                    prev = key
                for key in filled:
                    if key not in first:
                        # (paragraph, order within it). Sorting by the number
                        # before this hid an inversion INSIDE one paragraph
                        # ("Figure 3 is cited before Figure 1").
                        first[key] = (idx, callout_order)
                        callout_order += 1
    rows = []
    for (kind, family) in sorted({(k[0], k[1]) for k in first}):
        seq = sorted(((slot, key) for key, slot in first.items()
                      if key[0] == kind and key[1] == family))
        seen_after = []
        for slot, key in seq:
            idx = slot[0]
            for prev_slot, prev_key in seen_after:
                if key[2] < prev_key[2]:
                    rows.append({
                        "rule": "FMT-O1", "severity": "medium", "location": f"p{idx}",
                        "evidence": f"{key[3]} first cited at p{idx} after {prev_key[3]} "
                                    f"(p{prev_slot[0]})",
                        "detail": (f"the {kind} numbering does not follow the order of first "
                                   f"citation: {prev_key[3]} is cited before {key[3]}"),
                        "protected": False})
                    break
            seen_after.append((slot, key))
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
# Role words a front-matter line puts directly before the address. A match that
# STARTS with one and continues is glued: `lead contactzhenxie@host` is the
# documented shipped shape. The old probe looked for alphanumerics BEFORE
# `m.start()`, which `EMAIL_RE`'s greedy local part makes impossible (they are
# absorbed into the match), so the branch was dead code.
_EMAIL_ROLE_PREFIXES = ("correspondence", "correspondingauthor", "affiliations",
                        "affiliation", "keywords", "contact", "orcid")
# `email` is NOT a role prefix: `emailaddress@journal.com` and `emailupdates@...`
# are healthy addresses whose local part merely begins with the word. `contact`
# IS a role word only in the documented front-matter shape "lead contact<name>@";
# otherwise `contactjohn@university.edu` is a healthy address too. Both shapes
# are structurally identical to the glue, so the mechanical cut requires the
# "lead" context and every ambiguous address is left alone (the FMT-X2 row is
# still reported for the editing arms when the address touches text).
_EMAIL_ROLE_PREFIX_CONTEXT = {
    "contact": re.compile(r"(?:^|\s)lead\s+$", re.I),
}
# The residue after a role word is a PERSONAL NAME in the glued shipped shape
# (`contactzhenxie@`), not a routine mailbox word. `emailupdates@list.edu` is a
# healthy address whose local part merely begins with a role word; the old cut
# split it into "email updates". These are the words a mailbox local part uses
# after a role prefix; a residue in this set (or one with no vowel at all, like
# `contactsxyz@` -> "sxyz") is not a name and is never cut.
_EMAIL_MAILBOX_WORDS = frozenset({
    "updates", "update", "info", "support", "admin", "office", "team", "list",
    "lists", "news", "alerts", "notifications", "events", "press", "media",
    "sales", "help", "service", "services", "enquiries", "inquiries", "careers",
    "jobs", "billing", "accounts", "privacy", "legal", "security", "noreply",
    "webmaster", "postmaster", "hello", "mail", "marketing", "research",
    "editorial", "submissions", "authors", "reviewers", "permissions",
    "reprints", "subscriptions", "feedback", "questions", "comments", "general",
    "reception", "hr", "it", "contact", "email",
})


def _email_glue_cut(text: str, m) -> tuple:
    """(cut_offset, kind) for an address glued INSIDE its own token, else None.

    Kinds: "before" (`contactzhenxie@`) and "after"
    (`zhenxie@tsinghua.edu.cnHowever`). Both are detectable from the match
    itself -- no word-boundary guess outside it -- so the mechanical repair can
    insert exactly one space without re-spacing a healthy address.
    """
    token = m.group(0)
    local, host = token.split("@", 1)
    low = local.lower()
    for word in _EMAIL_ROLE_PREFIXES:
        context = _EMAIL_ROLE_PREFIX_CONTEXT.get(word)
        if context is not None and not context.search(text[:m.start()]):
            # `contactjohn@` is a healthy address; only the documented
            # "lead contact<name>@" front-matter glue has the context.
            continue
        if low.startswith(word) and len(local) - len(word) >= 3 \
                and low[len(word)].isalpha():
            residue = low[len(word):]
            if residue in _EMAIL_MAILBOX_WORDS or not re.search(r"[aeiou]", residue):
                # A routine mailbox word, or a consonant run that is not a name:
                # the address is valid as written, so do not cut inside it.
                continue
            return m.start() + len(word), "before"
    # The TLD class `[A-Za-z]{2,}` otherwise absorbs the following word
    # ("cnHowever"). Only a lower->upper transition inside the FINAL label is
    # glue: an uppercase letter in an earlier label ("myExample.com") is a
    # legitimate address and must not be re-spaced.
    final = host.rfind(".")
    for i in range(max(1, final + 1), len(host)):
        if host[i - 1].islower() and host[i].isupper():
            return m.start() + len(local) + 1 + i, "after"
    return None, None


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
        s, _breaks = _glue_text(raw)
        evidence = None
        for m in EMAIL_RE.finditer(s):
            _cut, kind = _email_glue_cut(s, m)
            if kind == "before":
                evidence = (f"{s[max(0, m.start() - 24):m.end() + 12]!r}: the address is "
                            f"glued to the word before it")
                break
            if kind == "after":
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
    if 1900 <= a <= 2099 and 1900 <= b <= 2099:
        # A plausible publication-year range ("2019-2020") is not a citation
        # range. The old 1000..2999 window also swallowed expandable citation
        # ranges such as 1000-1020 and backwards spans such as 2019-3, which
        # the written-order endpoint rule must keep.
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
        # The decoded value is whatever the instruction carries: a hand- or
        # LLM-edited field can put a list (or a scalar) where the object's
        # `properties` belongs. Malformed citation JSON is in-scope input (the
        # sibling readers guard the same shapes and report `bad-citation-json`),
        # so a non-dict here must not escape as an AttributeError.
        js = js if isinstance(js, dict) else {}
        props = js.get("properties") if isinstance(js.get("properties"), dict) else {}
        marker = props.get("formattedCitation") or props.get("formatted citation") or ""
        items, data = [], []
        for ci in (js or {}).get("citationItems") or []:
            if not isinstance(ci, dict):
                continue
            uris = ci.get("uris")
            uri = uris[0] if isinstance(uris, list) and uris else (ci.get("uri") or "")
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
    # Only an ORIGINAL range stays a range: a cluster written `1,2,3` must not
    # be rebuilt `1-3` (refresh parity for styles with collapse disabled).
    _orig_range = bool(re.search(
        r"\d\s*(?:\\uc0\\u8211\{\}|\\u8211\{\}|\u2013|\u2014|-)\s*\d",
        original_cluster or ""))
    raw_parts, vis_parts = [], []
    i = 0
    while i < len(ranks):
        j = i
        while j + 1 < len(ranks) and ranks[j + 1] == ranks[j] + 1:
            j += 1
        if j - i >= 2 and _orig_range:       # a printed range stays a range
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
    for t in _zotero_title_tokens(title):
        if _zotero_word_in(hay, t):
            score += 1
            if score >= 8:
                break
    return score


def _zotero_title_tokens(title: str) -> list:
    """Distinctive title tokens, shortest useful length included.

    The old >4 filter dropped four-letter scientific nouns ("data", "cell",
    "gene", "CNV"): two same-author entries then tied on the shared title word
    ("notes"), and the greedy assignment handed the earlier rank to the wrong
    entry. Four-letter tokens are exactly what distinguishes such titles.
    """
    return [t for t in re.sub(r"[^a-z0-9 ]+", " ", str(title or "").lower()).split()
            if len(t) >= 4 and t not in ZOTERO_TOKEN_STOPWORDS]


def _zotero_title_overlap(entry_text: str, item: dict) -> int:
    hay = re.sub(r"[^a-z0-9 ]+", " ", unicodedata.normalize(
        "NFKD", str(entry_text or "")).lower())
    return sum(1 for t in _zotero_title_tokens(item.get("title") or "")
               if _zotero_word_in(hay, t))


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
                # The SCORE alone ties for same-author, near-title entries
                # ("Notes on data" / "Notes on cell"): both match the family
                # and the shared word "notes". Title overlap is the
                # discriminating evidence and must break the tie BEFORE the
                # earlier entry index does -- the old key kept the first free
                # pair and assigned the swapped bibliography backwards.
                candidates.append((score, idx, rank,
                                   _zotero_title_overlap(text, item)))
    candidates.sort(key=lambda t: (-t[0], -t[3], t[1], t[2]))
    taken_entry, taken_rank, assignment = set(), set(), {}
    for score, idx, rank, _overlap in candidates:
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
        # Word can split the number run as `" 12."` (a leading space or tab
        # inside the same w:t). The old pattern required the digit immediately
        # after the tag, so the run matched by `_zotero_entry_span_of_run` was
        # never rewritten and the report still claimed a renumber.
        new_run = re.sub(r"(<w:t(?:\s[^>]*)?>)(\s*)(\d+)([\.\)]?)(\s*)(</w:t>)",
                         lambda m: m.group(1) + m.group(2) + str(rank) + m.group(4)
                         + m.group(5) + m.group(6), run, count=1)
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
        # Same malformed-input class as `zotero_citation_state`: the field's
        # `properties` is not guaranteed to be an object.
        if not isinstance(js, dict):
            out["skip"] = "a citation field's JSON is not an object"
            return out
        props = js.get("properties") if isinstance(js.get("properties"), dict) else {}
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
        # The MARKER is not the rendered text: a field whose formattedCitation
        # is "1" can still display "2". Compare the result runs too, or the
        # refresh reports `nothing_to_do` while `zotero-check` files FMT-Z4.
        _visible = "".join(text_of(run) for _s, _e, run in region[2])
        _visible_nums = _marker_numbers(_visible)
        if sorted(current) == sorted(ranks) and sorted(_visible_nums) == sorted(ranks):
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
    def _high_key(r):
        # Location is an OFFSET-bearing label and may move with the edit; the
        # rule + evidence signature is the stable identity of the row.
        return (r.get("rule"), str(r.get("evidence") or ""))

    high_rules = ("FMT-Z1", "FMT-Z2", "FMT-Z4")
    high_before_rows = [r for r in rows_before if r["rule"] in high_rules]
    high_after_rows = [r for r in rows_after if r["rule"] in high_rules]
    high_before = len(high_before_rows)
    high_after = len(high_after_rows)
    # Equal COUNTS can still hide a NEW row (one fixed, one introduced). A
    # refresh may only retire high rows, never add one.
    new_high = [r for r in high_after_rows
                if _high_key(r) not in {_high_key(b) for b in high_before_rows}]
    if high_after > high_before or new_high or (high_after and not high_before):
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


def _part_has_zotero_item_field(raw) -> bool:
    """True when a part's WORD FIELD INSTRUCTIONS carry a Zotero item field.

    The checker joins `w:instrText` pieces across runs and matches
    case-insensitively; a raw byte containment test missed an instruction Word
    split into two runs (`ADDIN ` + `ZOTERO_ITEM`) or spelled lowercase.
    """
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    instr = "".join(re.findall(r"<w:instrText\b[^>]*>(.*?)</w:instrText>",
                               text, re.S | re.I))
    return "ADDIN ZOTERO_ITEM" in re.sub(r"\s+", " ", instr).upper()


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
                         and _part_has_zotero_item_field(parts[n])]
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
    if rep["skip"] and not rep["nothing_to_do"]:
        # A REFUSAL is write-free: the style reconcile that ran before the
        # refusal was detected must not be returned as a change, or the caller
        # rewrites the DOCX even though the numbering operation was refused.
        rep["changed"] = False
        rep["parts"] = None
        rep["changes"] = []
    else:
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
            # Untrusted input budget: this used to `pkg.read()` EVERY part with
            # no per-part or total cap, so a small zip bomb allocated gigabytes.
            problem = _docx_zip_problem(pkg)
            if problem:
                raise OSError(problem)
            parts = {n: pkg.read(n) for n in names}
            # Validate the part the refresh EDITS before the regex readers: a
            # malformed main part (an unclosed tag) used to reach them, yield
            # "no live citation fields", and print "no change" with exit 0.
            # `scan` reports the same package as FMT-X1. A DTD/entity
            # declaration is refused here too (never handed to the parser).
            problem = _docx_entity_problem(parts["word/document.xml"],
                                           "word/document.xml")
            if problem:
                raise OSError(problem)
            ET.fromstring(parts["word/document.xml"])
    except (OSError, zipfile.BadZipFile, ET.ParseError, RuntimeError,
            NotImplementedError, UnicodeDecodeError) as e:
        # An unsupported compression method or a malformed part is an unreadable
        # package like any other, never a traceback out of a documented command.
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
    # Random sibling, created exclusively: the old
    # `.{name}.zotrefresh<pid>.tmp` was predictable, so a sandbox agent could
    # pre-create a symlink there and receive the ZIP bytes through it (and
    # os.replace then moved the link to the destination). Same rule as the
    # other formatter temps.
    tmp = dst.with_name(f".{dst.name}.zotrefresh{os.getpid()}.{os.urandom(6).hex()}.tmp")
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                     | getattr(os, "O_NOFOLLOW", 0), 0o666)
        with os.fdopen(fd, "wb") as f:
            with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
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
    low = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    low = re.sub(r"\s+", " ", low).strip()
    best, best_score = None, 0
    for r in records:
        score = 0
        fam = (r.get("first_family") or "").lower()
        # Word boundaries, not `in`: the family "He" matched "The method …"
        # and the title token "model" matched "Remodeling …", so a wrong .bib
        # record could be selected and its volume/pages written into the entry.
        if fam and _zotero_word_in(low, fam):
            score += 3
        if r.get("year") and f"({r['year']})" in text:
            score += 1
        title = str(r.get("title") or "")
        for t in re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split():
            if len(t) > 4 and t not in ZOTERO_TOKEN_STOPWORDS \
                    and _zotero_word_in(low, t):
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
                # A DOI is a locator, not evidence that the record is a
                # preprint. Calling every DOI-bearing article "Preprint at"
                # invented a publication type (and fired FMT-R5 on the text the
                # repair itself added).
                locator = f"Available at https://doi.org/{rec['doi']}"
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

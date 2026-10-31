# -*- coding: utf-8 -*-
# Part 14/20 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# DIFFERENCE TRACKING (per version, per baseline, per document)
#
# Every submission version the pipeline produces is tracked against the
# PRE-CONFORMED ORIGINAL (the byte-identical copy `setup --source` made into
# non_revised/) and against the version it was derived FROM. The copy's name
# NAMES THAT BASELINE (`<token>`), so a reader never has to guess what
# "previous" meant:
#
#     <name>.tracking-<token>.<ext>    real tracked copy (word/latexdiff)
#     <name>.tracking-<token>.pdf      the compiled marked-up PDF of a
#                                      latexdiff .tex copy (rewired to its
#                                      tracked includes/bibliography first)
#     <name>.logging-<token>.<ext>     its fallback log when the tool failed
#     (.ext in .docx / .tex / .bib)
#
#     token = original      the pre-conformed submission (non_revised/)
#             a1            the round base (from round 2: the pinned champion of
#                           round r-1, published as round<r-1>_winner/)
#             w<k> / a<k>   the k-th rewrite / revision of this round -- the
#                           base an integration run reworked (its self/ member)
#             winner<r>     the published winner of round r
#
# Every PUBLISHED winner (`round<r>_winner/`) is tracked in place too: against
# the pristine original, and -- for r > 1 -- against the previous round's winner
# (`<name>.tracking-winner<r-1>.<ext>`).
#
# A `.docx` pair goes through redline_one_pair() -- Word's own comparison
# engine (the `docx-compare` MCP tool) FIRST, then the documented redline chain.
# A `.tex`/`.bib` pair goes through `latexdiff`; a latexdiff `.tex` is then
# REWIRED (its `\input{}`/`\include{}`/`\addbibresource{}`/`\bibliography{}`
# references point at the tracked copies of those files when this baseline
# produced them) and compiled into the sibling tracking PDF. EVERY tracking
# `.tex` compile ROOT gets its PDF -- a byte-identical pair yields the clean
# PDF of the version (with its tracked includes) -- while a fragment is
# compiled through its master. The fallback file is a human-readable
# before/after log (a marker .docx for a .docx pair) -- never a file that only
# looks like a real tracked copy.
#
# The copies are AUXILIARIES (TRACKING_AUX_NAME_RE): they are written BESIDE
# the documents the stage produced -- the template-first stage's `out/`
# included -- THE MOMENT THAT STAGE IS ACCEPTED (postcheck -> track_after_stage;
# template stage -> maybe_track_template_stage), and mirrored under
# <root>/tracking/ with a manifest and a README. The round-close pass keeps a
# fresh entry, fills in what a stage did not write, and tracks each published
# winner in place (a1's raw hash-verified `base/` input is never written into).
# They never enter a corpus digest, a pin, a judge view, a fingerprint or the
# revision token. The pass is PURE CODE: it starts no agent session, so it
# cannot change a champion, a score or a ranking -- both properties are pinned
# by the `.paper_test/test_difference_tracking_*_*.py` parts.
# =====================================================================

TRACKING_DIRNAME = "tracking"
TRACKING_MANIFEST = "manifest.json"
# The run kinds whose accepted output is a submission VERSION: their postcheck
# writes the difference-tracking copies immediately (see track_after_stage), so
# the marked-up copy of a version exists as soon as the version does. a1 has no
# agent stage (it is a byte-identical copy of its source) and the winner
# directory is published at round close.
TRACKING_STAGE_KINDS = ("rewrite", "revise", "integrate")
LATEXDIFF_CMD = "latexdiff"
LATEXDIFF_TIMEOUT = 600

TRACKING_TOKEN_SCHEME = (
    "<token> is the baseline a copy was compared against: `original` for the "
    "pre-conformed submission (non_revised/), or the baseline version's id -- the "
    "round base `a1`, a rewrite `w<k>`, a revision `a<k>` (an integration's own "
    "self/ member), or `winner<r>` for the published winner of round r")
TRACKING_MANIFEST_NOTES = (
    "A copy named <name>.tracking-<token>.<ext> shows the difference between the "
    "candidate document and the baseline named by <token>: real Word tracked changes "
    "for .docx (the docx-compare MCP tool / redline chain), a latexdiff copy for "
    ".tex/.bib. <name>.logging-<token>.<ext> is the readable before/after log written "
    "instead when the difference tool failed.",
    "Every copy here is an AUXILIARY (the compiled tracking PDF included): it is excluded "
    "from every judged/pinned corpus, fingerprint and revision token, and the pass starts "
    "no agent session.",
    "The copies are written BESIDE the version's documents (the template-first "
    "stage's out/ included) right after that stage is accepted, and mirrored here; "
    "the round's close only fills in what a stage did not write (and every "
    "published round<r>_winner/ is tracked in place: against the pre-conformed "
    "original, and -- for r > 1 -- against the winner of round r-1, "
    "`tracking-winner<r-1>`).",
)


def tracking_manifest(ctx: Ctx, tool: str, extra_notes=()) -> dict:
    """The fresh manifest header (the caller fills `versions`)."""
    return {"generated": utcnow(), "pipeline_root": str(ctx.root), "tool": tool,
            "token_scheme": TRACKING_TOKEN_SCHEME, "versions": [],
            "notes": list(TRACKING_MANIFEST_NOTES) + list(extra_notes)}


def merge_tracking_entries(ctx: Ctx, entries: list, *, tool: str = "auto",
                           extra_notes=()) -> dict:
    """Merge freshly written entries into <root>/tracking/ (manifest + README).

    The manifest ACCUMULATES: the stage-time hooks and the round-close pass each
    merge their own entries, and an entry for a (round, version) key already on
    disk is replaced by the fresh one.
    """
    out_root = ensure_aux_output_root(ctx.root, TRACKING_DIRNAME)
    stored = read_json(out_root / TRACKING_MANIFEST) or {}
    manifest = tracking_manifest(ctx, tool, extra_notes=extra_notes)
    prev = {(str(v.get("round")), str(v.get("version"))): v
            for v in stored.get("versions") or []}
    order = list(prev)
    for entry in entries:
        key = (str(entry.get("round")), str(entry.get("version")))
        if key not in prev:
            order.append(key)
        prev[key] = entry
    manifest["versions"] = [prev[k] for k in order]
    write_json_atomic(out_root / TRACKING_MANIFEST, manifest)
    write_text_atomic(out_root / "README.md", tracking_readme(manifest))
    return manifest


def fresh_package_sources(ctx: Ctx, r: int, vid: str) -> list:
    """The version's own produced package as corpus sources (code/ excluded).

    `corpus_sources()` folds the stage's `code/` directory in under a prefix;
    the tracked manuscript differences are the PACKAGE documents, so the
    prefixed sources are dropped and the result is exactly the directory the
    stage wrote (`revised/`, `rewritten/`, `integrated/`, or `base/` for a1)
    with its own `work/` scratch excluded.
    """
    return [s for s in corpus_sources(ctx, r, vid) if not s[1]]


def tracking_previous_baseline(ctx: Ctx, r: int, vid: str) -> tuple:
    """(token, sources, note) of the version `vid` was derived FROM.

    The token is the baseline's id in the pipeline's own vocabulary, so the
    auxiliary name says what the difference is against:

    rewrite   -> `a1` (the round base = the version before it was rewritten)
    revise    -> `a1` (the round base = the version before it was reviewed)
    integrate -> the integration's own `self/` member id, which is a pool id
                 (`a1`, `w<k>` or `a<k>`) -- the version it reworked
    a1/other  -> none: a1 IS the previous version (round 1: a copy of the
                 pristine original; round r>1: a copy of the previous
                 champion), so a copy against itself would say nothing.
    """
    arm = arm_of_vid(vid)
    if arm == "integrate":
        rec = ctx.run(rid_for_fresh(r, vid)) or {}
        self_id = str(rec.get("self_id") or A1_ID)
        return self_id, corpus_sources(ctx, r, self_id), (
            f"the integration's own base (self/{self_id}: the version this "
            f"integration reworked)")
    if arm in ("rewrite", "revise"):
        note = (f"the round base (a1: the pinned champion of round {r - 1}, published as "
                f"round{r - 1}_winner/)" if r > 1
                else "the round base (a1: the pristine original's round-1 copy)")
        return A1_ID, corpus_sources(ctx, r, A1_ID), note
    return "", [], ""


def tracking_baselines(ctx: Ctx, r: int, vid: str) -> list:
    """[(token, sources, note)] for one version, original first."""
    out = [(TRACK_TOKEN_ORIGINAL, [(ctx.pristine, "", ())],
            "the pre-conformed original (non_revised/)")]
    token, prev_sources, note = tracking_previous_baseline(ctx, r, vid)
    if token and any(src.is_dir() for src, _p, _e in prev_sources):
        out.append((token, prev_sources, note))
    return out


def winner_tracking_baselines(ctx: Ctx, r: int) -> list:
    """[(token, sources, note)] for the round's published winner, original first.

    Round 1 has no previous winner to track, so its list holds the original
    ONLY. The empty-baseline tuple (`""`, no sources, no note) used to be passed
    to `_track_one_entry` anyway, which appended a phantom
    `{"baseline": "", "reason": "no base corpus"}` skip row to every round-1
    winner manifest -- while the freshness reader (`tracking_entry_is_fresh`)
    skips empty tokens, so writer and reader disagreed and every round-1 entry
    carried one bogus skip.
    """
    out = [(TRACK_TOKEN_ORIGINAL, [(ctx.pristine, "", ())],
            "the pre-conformed original (non_revised/)")]
    if r > 1:
        out.append((f"winner{r - 1}", [(winner_dir_of(ctx, r - 1), "", ())],
                    f"the published winner of round {r - 1} (round{r - 1}_winner/)"))
    return out


def latexdiff_one_pair(base: Path, cand: Path, out: Path,
                       timeout: int = LATEXDIFF_TIMEOUT) -> dict:
    """Write a `latexdiff` copy of one `.tex`/`.bib` pair; never raises."""
    exe = shutil.which(LATEXDIFF_CMD)
    if not exe:
        return {"ok": False, "tool": LATEXDIFF_CMD, "attempts": [
            {"backend": LATEXDIFF_CMD, "cmd": [LATEXDIFF_CMD, str(base), str(cand)],
             "rc": None, "ok": False,
             "detail": f"{LATEXDIFF_CMD} is not on PATH; the logging fallback was written"}]}
    argv = [exe, "--no-label", str(base), str(cand)]
    try:
        # latexdiff prints the diff on stdout; capture it in a bounded temp
        # file, not a PIPE whose whole content lands in memory (F61).
        rc, stdout, stderr = run_bounded(argv, timeout)
        err = (stderr or b"").decode("utf-8", "replace").strip().replace("\n", " ")
    except FileNotFoundError as e:                              # noqa: BLE001
        rc, stdout, err = None, b"", f"not found: {e}"
    except subprocess.TimeoutExpired:
        rc, stdout, err = None, b"", f"timeout after {timeout}s"
    except ToolOutputOverBudget as e:                           # noqa: BLE001
        rc, stdout, err = None, b"", str(e)[:300]
    except OSError as e:                                        # noqa: BLE001
        rc, stdout, err = None, b"", f"exec error: {e}"
    ok = bool(rc == 0 and stdout.strip())
    if ok:
        out.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(tmp_path_for(out), out,
                            lambda f: f.write(stdout), binary=True)
    else:
        with contextlib.suppress(OSError):
            out.unlink()
    detail = err[:300] if err else ("clean" if ok else "no output")
    return {"ok": ok, "tool": LATEXDIFF_CMD, "warning": (err[:200] or None) if ok else None,
            "attempts": [{"backend": LATEXDIFF_CMD, "cmd": argv, "rc": rc, "ok": ok,
                          "detail": detail}]}


def _note_para(text: str):
    """One plain paragraph element carrying `text`."""
    p = ET.Element(_w("p"))
    r = ET.SubElement(p, _w("r"))
    t = ET.SubElement(r, _w("t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = str(text)
    return p


def _write_minimal_docx(out: Path, paragraphs: list) -> None:
    """A minimal, readable OOXML document of plain paragraphs (stdlib only).

    The logging fallback of a `.docx` pair has to be a REAL readable .docx even
    when the pair itself could not be opened (that is exactly when the fallback
    fires), so the note cannot be smuggled into a broken package.
    """
    def esc(text: str) -> str:
        return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{esc(t)}</w:t></w:r></w:p>'
                   for t in paragraphs)
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                     'content-types"><Default Extension="rels" ContentType="application/'
                     'vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" '
                     'ContentType="application/xml"/><Override PartName="/word/document.xml" '
                     'ContentType="application/vnd.openxmlformats-officedocument.'
                     'wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    out.parent.mkdir(parents=True, exist_ok=True)

    def _write_minimal(f) -> None:
        with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", document)

    _atomic_write_bytes(tmp_path_for(out), out, _write_minimal, binary=True)


def _before_after_lines(base: Path, cand: Path) -> list:
    """A bounded plain-text before/after listing of two documents' paragraphs."""
    lines = []
    try:
        base_texts = [_para_text(p) for p in _docx_root(base)[1].iter(_w("p"))]
        cand_texts = [_para_text(p) for p in _docx_root(cand)[1].iter(_w("p"))]
    except Exception as e:                                      # noqa: BLE001
        return [f"[the documents could not be read as OOXML: {type(e).__name__}: {e}]"]
    sm = difflib.SequenceMatcher(None, base_texts, cand_texts, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        for t in base_texts[i1:i2]:
            if t.strip():
                lines.append(f"[BEFORE: {t}]")
        for t in cand_texts[j1:j2]:
            if t.strip():
                lines.append(f"[AFTER: {t}]")
        if len(lines) > 400:
            lines.append("[... more differences truncated ...]")
            break
    return lines or ["[no textual difference found between the two documents]"]


def write_docx_logging_fallback(base: Path, cand: Path, out: Path, baseline: str,
                                reason: str) -> dict:
    """The `.logging-*` fallback for a `.docx` pair (never raises).

    When the revised copy is readable the fallback is a COPY of it whose changed
    paragraphs carry bracketed `[BEFORE: ...]` / `[AFTER: ...]` markers plus a
    first-paragraph note (the documented before/after fallback the revision
    skill uses). When it is not readable, a minimal readable .docx carries the
    note and the reason, so the reader still gets a file they can open.
    """
    note = (f"[LOGGING FALLBACK -- not a tracked-changes document] difference tracking "
            f"against the {baseline} version failed: {reason}")
    try:
        cand_raw = cand.read_bytes()
        _, cand_root = _docx_root(cand)
        body = cand_root.find(_w("body"))
        if body is None:
            raise RuntimeError("the revised document carries no w:body")
        # Body-level paragraphs only. Table-cell paragraphs are represented by
        # their whole `w:tbl` block, which is copied once below as non-paragraph
        # body content: lifting them with `.iter(w:p)` appended each cell again
        # at top level AND inside the copied table, doubling every unchanged
        # cell and leaving changed cells both marked and unmarked.
        base_body = _docx_root(base)[1].find(_w("body"))
        base_texts = ([_para_text(p) for p in base_body.findall(_w("p"))]
                      if base_body is not None else [])
        cand_children = list(body)
        cand_paras = [c for c in cand_children if c.tag == _w("p")]
        new_body = ET.Element(_w("body"))
        new_body.append(copy.deepcopy(_note_para(note)))
        sm = difflib.SequenceMatcher(None, base_texts,
                                     [_para_text(p) for p in cand_paras], autojunk=False)
        # Build the rewritten paragraph stream by INDEX so the body's other
        # children (a mid-document table, a sectPr) keep their original slots.
        # Appending every non-paragraph child at the end moved an inline table
        # to the bottom of the document.
        before, out_para, emitted = {}, {}, 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for j in range(j1, j2):
                    out_para[j] = copy.deepcopy(cand_paras[j])
                continue
            notes = [copy.deepcopy(_note_para(f"[BEFORE: {t}]"))
                     for t in base_texts[i1:i2] if t.strip()]
            if notes:
                before.setdefault(j1, []).extend(notes)
                emitted += len(notes)
            for j in range(j1, j2):
                out_para[j] = copy.deepcopy(_note_para(f"[AFTER: {_para_text(cand_paras[j])}]"))
                emitted += 1
        para_no = 0
        for child in cand_children:
            if child.tag == _w("p"):
                for extra in before.pop(para_no, []):
                    new_body.append(extra)
                new_body.append(out_para[para_no])
                para_no += 1
            else:
                new_body.append(copy.deepcopy(child))
        for extra in before.pop(para_no, []):
            new_body.append(extra)
        if not emitted:
            # The body paragraphs are identical; the difference may still be
            # inside a table or another non-paragraph object, which is copied
            # verbatim above. Record those changed cell/paragraph texts the
            # same way `_before_after_lines` does -- the old blanket "no
            # textual difference" line hid a table-only edit entirely.
            deep_diff = _before_after_lines(base, cand)
            if deep_diff and deep_diff != ["[no textual difference found between the two documents]"]:
                new_body.append(copy.deepcopy(_note_para(
                    "[the body text is unchanged; the difference is inside a table/object]")))
                for line in deep_diff[:400]:
                    new_body.append(copy.deepcopy(_note_para(line)))
            else:
                new_body.append(copy.deepcopy(_note_para(
                    "[no textual difference found between the two documents]")))
        body.clear()
        for child in list(new_body):
            body.append(child)
        payload = _serialize_document(cand_root, cand_raw)
        out.parent.mkdir(parents=True, exist_ok=True)

        def _write_tracked(f) -> None:
            with zipfile.ZipFile(cand) as zin, \
                    zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "word/document.xml":
                        data = payload
                    zout.writestr(item, data)

        _atomic_write_bytes(tmp_path_for(out), out, _write_tracked, binary=True)
    except Exception as e:                                      # noqa: BLE001
        try:
            _write_minimal_docx(out, [
                note,
                f"[the revised document could not be copied: {type(e).__name__}: {e}]"]
                + _before_after_lines(base, cand))
        except Exception as e2:                                 # noqa: BLE001
            return {"ok": False, "error": f"the logging fallback failed too: {e2}"}
    return {"ok": True, "out": out}


def write_text_logging_fallback(base: Path, cand: Path, out: Path, baseline: str,
                                reason: str) -> dict:
    """The `.logging-*` fallback for a `.tex`/`.bib` pair (never raises).

    Every emitted line is commented out, so the file is inert if a build tool
    picks it up; the content is a unified before/after diff the reader can
    inspect without any LaTeX toolchain.
    """
    def read_lines(p: Path) -> list:
        try:
            return p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:                                    # noqa: BLE001
            return [f"[unreadable: {type(e).__name__}: {e}]"]

    lines = [
        f"LOGGING FALLBACK -- not a latexdiff copy of {cand.name}",
        f"difference tracking against the {baseline} version failed: {reason}",
        "the unified diff below is commented out (both TeX and BibTeX treat a leading % as "
        "a comment)",
        "", f"--- {base.name}", f"+++ {cand.name}"]
    lines += list(difflib.unified_diff(read_lines(base), read_lines(cand),
                                       fromfile=base.name, tofile=cand.name, lineterm=""))[2:]
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_text_atomic(out, "\n".join("% " + ln for ln in lines) + "\n")
    except OSError as e:                                        # noqa: BLE001
        return {"ok": False, "error": f"the logging fallback could not be written: {e}"}
    return {"ok": True, "out": out}


def redline_index(manifest: dict) -> dict:
    """{(round, version, source, revised_rel): comparison} from a redlines manifest."""
    out = {}
    for v in (manifest or {}).get("versions") or []:
        for c in v.get("comparisons") or []:
            out[(int(v.get("round") or 0), str(v.get("version") or ""),
                 str(c.get("source") or ""), str(c.get("revised_rel") or ""))] = c
    return out


def _reusable_redline(index: dict, r: int, vid: str, source: str, pair: dict) -> dict:
    """The already-produced redline for this exact pair, when there is one.

    The round-close call runs `run_redlines()` first, so the docx pairs against
    the original (and, for the rewrite/revise arms, against the round base) are
    usually already on disk. Reusing them keeps one Word/COM call per pair
    instead of two -- and the reuse is GATED ON THE TWO CONTENT DIGESTS: a
    redline of the same relative name but of DIFFERENT bytes (the integration
    arms' `from-base` is the round base, not their own `self/` member) must never
    be copied, because it would show the wrong difference. A manifest written by
    an older pipeline carries no digests and is therefore never reused.
    """
    if not source:
        return {}
    rec = index.get((r, vid, source, pair["cand_rel"])) or {}
    if (rec.get("ok") and rec.get("base_digest") == pair.get("base_digest")
            and rec.get("cand_digest") == pair.get("cand_digest")):
        return rec
    return {}


def _track_one_entry(ctx: Ctx, entry: dict, *, out_key: str, r: int, vid: str,
                     token: str, base_sources: list, note: str, srcs: list,
                     tool: str, redline_cmd: list, index: dict, in_package: bool,
                     quiet: bool, memo: dict = None) -> None:
    """Track ONE baseline (token) of one entry (a version or a published winner)."""
    if token != TRACK_TOKEN_ORIGINAL:
        entry["previous_baseline"] = token
    if not any(s.is_dir() for s, _p, _e in base_sources):
        entry["skipped"].append({"baseline": token, "reason": "no base corpus"})
        return
    for ext in TRACKABLE_EXTS:
        pairs, unmatched_base, unmatched_cand = match_track_pairs(base_sources, srcs, ext)
        for rel in unmatched_base:
            entry["skipped"].append({
                "baseline": token, "base_rel": rel,
                "reason": f"no corresponding {ext} in this version"})
        for rel in unmatched_cand:
            entry["skipped"].append({
                "baseline": token, "revised_rel": rel,
                "reason": f"new {ext} with no counterpart in the {token} baseline"})
        for pair in pairs:
            # Which redlines-tree label may stand in for THIS pair: the original
            # baseline is `from-original`; a baseline that really is the round
            # base (the `a1` token, or a previous winner whose content IS the
            # round base) is `from-base`. Anything else (an integration's own
            # `self/` member) is compared fresh -- the digest gate in
            # _reusable_redline would refuse a mismatched file anyway.
            reuse = ""
            if token == TRACK_TOKEN_ORIGINAL:
                reuse = "from-original"
            elif token == A1_ID or token.lower().startswith("winner"):
                reuse = "from-base"
            rec = track_one_pair(ctx, r, vid, token, ext, pair, tool,
                                 redline_cmd, index, out_key=out_key,
                                 in_package=in_package, reuse_source=reuse, memo=memo)
            rec["baseline_note"] = note
            entry["comparisons"].append(rec)
            if not quiet:
                if rec.get("ok") and rec.get("tool"):
                    result = f"({rec.get('tool')})"
                elif rec.get("ok"):
                    result = f"logging fallback ({rec.get('fallback')})"
                elif rec.get("skipped"):
                    result = "skipped (tool=none)"
                else:
                    result = "FAILED"
                print(f"  [track] {out_key}: {pair['cand_rel']} <- {token} {result}")


def _close_tracking_entry(entry: dict) -> None:
    """Fill in the status line of one tracking entry."""
    written = sum(1 for c in entry["comparisons"] if c.get("ok") and c.get("tool"))
    fallbacks = sum(1 for c in entry["comparisons"] if c.get("ok") and not c.get("tool"))
    skipped = sum(1 for c in entry["comparisons"] if c.get("skipped"))
    failed = sum(1 for c in entry["comparisons"] if not c.get("ok") and not c.get("skipped"))
    entry["status"] = ((f"{written} tracked copy(ies) written"
                        + (f", {fallbacks} logging fallback(s)" if fallbacks else "")
                        + (f", {skipped} skipped (tool=none)" if skipped else "")
                        + (f", {failed} FAILED" if failed else ""))
                       if entry["comparisons"] else "no trackable document pairs")


def run_difference_tracking(ctx: Ctx, rounds=None, versions=None, tool: str = "auto",
                            redline_cmd: list = None, quiet: bool = False,
                            redlines_manifest: dict = None,
                            skip_fresh: bool = False) -> dict:
    """Write the per-version difference-tracking copies + manifest.

    `versions=None` means every version of each requested round (the pool --
    base, rewrites, revisions -- plus the integration arms the round's mask
    really selected), which is the same set `run_redlines()` resolves. The
    round's PUBLISHED winner is tracked as well: against the pre-conformed
    original and, for r > 1, against the previous round's winner.

    `skip_fresh` keeps a version (or winner) whose copies a stage-time hook
    already wrote -- see `track_after_stage()` -- instead of driving Word/
    latexdiff a second time over unchanged content. The round-close pass sets
    it; the explicit `track` command leaves it off so an operator can always
    force a refresh.
    """
    rounds = [int(r) for r in (rounds if rounds is not None
                               else range(1, ctx.rounds_count() + 1))]
    versions = list(versions) if versions else None
    out_root = ensure_aux_output_root(ctx.root, TRACKING_DIRNAME)
    index = redline_index(redlines_manifest)
    manifest = tracking_manifest(ctx, tool)
    if not index:
        manifest["notes"].append(
            "no fresh redlines manifest was supplied: every .docx pair is compared by this "
            "pass itself (docx-compare MCP first, then the redline chain)")
    # The manifest ACCUMULATES: re-running one round (or one version) refreshes
    # that set's rows and keeps the rows of the sets it did not touch -- the
    # copies themselves persist, so dropping their rows would make the manifest
    # claim the tree is empty. A full `run` therefore ends with one manifest
    # covering every round it tracked.
    stored = read_json(out_root / TRACKING_MANIFEST) or {}
    prev_versions = {(str(v.get("round")), str(v.get("version"))): v
                     for v in stored.get("versions") or []}
    version_order = [k for k in prev_versions]

    def put_version(entry: dict) -> None:
        key = (str(entry.get("round")), str(entry.get("version")))
        if key not in prev_versions:
            version_order.append(key)
        prev_versions[key] = entry

    def flush_versions() -> None:
        manifest["versions"] = [prev_versions[k] for k in version_order]

    # {(base_digest, cand_digest, ext): out path} shared by EVERY entry of this
    # invocation: the round-1 pairs repeat (the `a1` baseline is the pristine
    # original's byte-identical copy, and a winner directory holds the
    # champion's bytes), so a pair already produced is copied instead of driving
    # Word/latexdiff again.
    memo = {}
    for r in rounds:
        round_versions = (versions if versions is not None else round_produced_ids(ctx, r))
        for vid in round_versions:
            if not is_fresh_vid(vid):
                continue
            srcs = fresh_package_sources(ctx, r, vid)
            if not any(s.is_dir() for s, _p, _e in srcs):
                put_version({"round": r, "version": vid, "status": "not materialized",
                             "comparisons": [], "skipped": []})
                continue
            baselines = tracking_baselines(ctx, r, vid)
            stored_entry = prev_versions.get((str(r), str(vid)))
            if skip_fresh and stored_entry and tracking_entry_is_fresh(
                    ctx, stored_entry, baselines, srcs):
                # The stage-time hook already wrote this version's copies and
                # they still match the documents on disk: keep the entry and
                # do not drive Word/latexdiff a second time.
                continue
            entry = {"round": r, "version": vid, "tool": tool,
                     "out_dir": f"{TRACKING_DIRNAME}/r{r}_{vid}/",
                     "previous_baseline": "", "comparisons": [], "skipped": []}
            for token, base_sources, note in baselines:
                _track_one_entry(ctx, entry, out_key=f"r{r}_{vid}", r=r, vid=vid,
                                 token=token, base_sources=base_sources,
                                 note=note, srcs=srcs, tool=tool, redline_cmd=redline_cmd,
                                 index=index, in_package=(arm_of_vid(vid) != "base"),
                                 quiet=quiet, memo=memo)
            compile_tracking_pdfs(ctx, entry, quiet=quiet)
            _close_tracking_entry(entry)
            put_version(entry)
        # The round's published winner: tracked in place (round<r>_winner/) and
        # mirrored under <root>/tracking/round<r>_winner/. Every winner tracks
        # the pre-conformed original; the winner of round r > 1 also tracks the
        # previous round's winner (the `winner<r-1>` token).
        wrec = ctx.round_get(r) or {}
        wname = str(wrec.get("winner_dir") or "")
        wdir = (ctx.root / wname) if wname else None
        if wdir is None or not wdir.is_dir():
            continue
        winner_srcs = [(wdir, "", ())]
        # The round record carries `champion` (`finalize_round`), not
        # `winner_id`: that key exists only on reports/round<r>_winner.json.
        # Reading it here always fell back to the literal "round<r>_winner",
        # which never matches a redlines-manifest candidate id, so the winner's
        # copy was re-driven through the full compare chain instead of reusing
        # the round-close redline.
        champ_vid = str(wrec.get("champion") or wrec.get("champion_rep")
                        or f"round{r}_winner")
        winner_baselines = winner_tracking_baselines(ctx, r)
        stored_winner = prev_versions.get((str(r), f"round{r}_winner"))
        if skip_fresh and stored_winner and tracking_entry_is_fresh(
                ctx, stored_winner, winner_baselines, winner_srcs):
            continue
        entry = {"round": r, "version": f"round{r}_winner", "winner": True, "tool": tool,
                 "out_dir": f"{TRACKING_DIRNAME}/round{r}_winner/",
                 "previous_baseline": "", "comparisons": [], "skipped": []}
        # The reuse lookup runs against the CHAMPION's version id: the winner
        # directory holds exactly the champion's bytes, so a redline the
        # round-close redlines pass already produced for that version is valid
        # here too (and saves a second Word/COM round trip per pair).
        for token, base_sources, note in winner_baselines:
            _track_one_entry(ctx, entry, out_key=f"round{r}_winner", r=r,
                             vid=champ_vid, token=token,
                             base_sources=base_sources, note=note, srcs=winner_srcs,
                             tool=tool, redline_cmd=redline_cmd, index=index,
                             in_package=True, quiet=quiet, memo=memo)
        compile_tracking_pdfs(ctx, entry, quiet=quiet)
        _close_tracking_entry(entry)
        put_version(entry)
    flush_versions()
    write_json_atomic(out_root / TRACKING_MANIFEST, manifest)
    write_text_atomic(out_root / "README.md", tracking_readme(manifest))
    return manifest


def tracking_entry_counts(entry: dict) -> tuple:
    """(tracked, fallbacks, skipped, failed) rows of one manifest entry."""
    rows = [c for c in (entry or {}).get("comparisons") or []]
    tracked = sum(1 for c in rows if c.get("ok") and c.get("tool"))
    fallbacks = sum(1 for c in rows if c.get("ok") and not c.get("tool"))
    skipped = sum(1 for c in rows if c.get("skipped"))
    failed = sum(1 for c in rows if not c.get("ok") and not c.get("skipped"))
    return tracked, fallbacks, skipped, failed


def tracking_force_writable(path) -> None:
    """Make an EXISTING auxiliary writable before it is overwritten.

    A tracking copy inherits the mode of the document it was copied from
    (`shutil.copy2`), and a template-first package is staged read-only -- so a
    re-run would otherwise fail with PermissionError on its own mirror file.
    Only our own auxiliary path is ever passed here; a missing file is a no-op.

    A destination the agent replaced with a symlink is REMOVED, never chmodded
    through: `p.chmod(p.stat().st_mode ...)` changed the mode of the external
    target the link named.
    """
    if not path:
        return
    try:
        p = Path(path)
        if p.is_symlink():
            p.unlink()
            return
        if p.exists():
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
    except OSError:
        pass


def _tracking_write_copy(src, dest) -> None:
    """Atomically replace `dest` with a copy of `src`, never through a symlink."""
    dest = Path(dest)
    if dest.is_symlink():
        dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.track-{os.getpid()}-{time.time_ns()}")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def tracking_summary_line(entry: dict, where: str = "") -> str:
    """One console line: what a manifest entry wrote and where."""
    tracked, fallbacks, skipped, failed = tracking_entry_counts(entry)
    tools = sorted({str(c.get("tool")) for c in (entry.get("comparisons") or [])
                    if c.get("ok") and c.get("tool")})
    line = (f"{tracked} tracked copy(ies)"
            + (f" with {', '.join(tools)}" if tools else "")
            + (f", {fallbacks} logging fallback(s)" if fallbacks else "")
            + (f", {skipped} skipped" if skipped else "")
            + (f", {failed} FAILED" if failed else ""))
    return line + (f" -> {where}" if where else "")


def tracking_entry_is_fresh(ctx: Ctx, entry: dict, baselines: list, srcs: list) -> bool:
    """Does a stored manifest entry still describe THIS version's copies?

    Used by `skip_fresh` (the automatic round-close pass and the template-stage
    re-check) to keep the copies a stage-time hook already wrote instead of
    driving Word/latexdiff over unchanged content twice. Conservative: a FAILED
    or skipped row, a missing copy (real or logging fallback, mirrored or
    in-package), or a pair whose two digests no longer match the documents on
    disk makes the entry stale, and the version is tracked again.
    """
    try:
        rows = [c for c in (entry or {}).get("comparisons") or []]
        if not rows or "FAILED" in str(entry.get("status") or ""):
            return False
        expected = {}
        for token, base_sources, _note in baselines:
            if not token or not any(s.is_dir() for s, _p, _e in base_sources):
                continue
            for ext in TRACKABLE_EXTS:
                pairs, _ub, _uc = match_track_pairs(base_sources, srcs, ext)
                for pair in pairs:
                    expected[(token, ext, pair["base_rel"], pair["cand_rel"])] = (
                        pair["base_digest"], pair["cand_digest"])
        have = {}
        for c in rows:
            if not c.get("ok") or c.get("skipped"):
                return False
            fallback = bool(c.get("fallback"))
            out_rel = c.get("fallback_out") if fallback else c.get("out")
            if not out_rel or not (ctx.root / str(out_rel)).is_file():
                return False
            in_pkg = c.get("in_package")
            if in_pkg:
                if fallback:
                    # The in-package fallback carries the `logging-<token>`
                    # suffix (the recorded `in_package` path names the real
                    # copy's name), so it is derived, never assumed. A stale
                    # REAL copy beside it means the fallback is not fresh.
                    if (ctx.root / str(in_pkg)).is_file():
                        return False
                    sib = (ctx.root / str(in_pkg)).parent / (
                        Path(str(c.get("revised_rel"))).stem
                        + tracking_aux_suffix(str(c.get("baseline")), str(c.get("ext")),
                                              fallback=True))
                else:
                    sib = ctx.root / str(in_pkg)
                if not sib.is_file():
                    return False
            if c.get("pdf_ok"):
                # The compiled marked-up PDF is part of the same auxiliary
                # family: a row whose PDF vanished is refreshed, not reused.
                for field in ("pdf", "pdf_in_package"):
                    rel = c.get(field)
                    if not rel or not (ctx.root / str(rel)).is_file():
                        return False
            elif c.get("ext") == ".tex" and c.get("in_package") \
                    and not c.get("fallback") and not c.get("pdf_error") \
                    and not str(c.get("pdf_skipped") or "").startswith("not a LaTeX root"):
                # A .tex row with NO recorded PDF outcome -- or one skipped for
                # a reason the current code no longer uses ("the copy carries no
                # latexdiff markup") -- predates the tracking-PDF step: refresh
                # it instead of keeping a PDF-less entry. A LOGGING-FALLBACK row
                # is excluded: compile_tracking_pdfs never compiles one (a
                # commented-out diff is not a document), so judging it by the
                # missing PDF would make every fallback row permanently stale and
                # the round-close pass would re-drive the tools it exists to skip.
                return False
            have[(c.get("baseline"), c.get("ext"), c.get("base_rel"),
                  c.get("revised_rel"))] = (c.get("base_digest"), c.get("cand_digest"))
        return bool(expected) and have == expected
    except Exception:                                        # noqa: BLE001
        # A malformed manifest row is treated as stale: the version is simply
        # tracked again (and the refreshed entry replaces the odd one).
        return False


def stage_tracking_enabled(ctx: Ctx) -> bool:
    """Whether this invocation may write difference-tracking copies.

    `run --no-track` records the choice on the context before any stage starts;
    every other entry point (`conform`, `retry`, `decide`, `track`, direct API
    calls) defaults to enabled.
    """
    return bool(getattr(ctx, "stage_tracking", True))


def track_after_stage(ctx: Ctx, rec: dict, *, quiet: bool = False) -> str:
    """Track ONE just-accepted version; "" on success, else a warning string.

    Called by `postcheck()` the moment a rewrite/revise/integrate attempt
    passes: the copies go BESIDE the documents the stage wrote (its own
    `rewritten/`, `revised/` or `integrated/` directory) and are mirrored under
    <root>/tracking/r<R>_<vid>/. The pass is code-only and can never fail the
    stage -- a problem is returned as a warning for the attempt record.
    """
    if not stage_tracking_enabled(ctx):
        return ""
    r = int(rec.get("round") or 0)
    vid = freshness_vid(rec)
    if not r or not vid or not is_fresh_vid(vid):
        return ""
    try:
        mf = run_difference_tracking(ctx, rounds=[r], versions=[vid], tool="auto",
                                     redline_cmd=None, quiet=quiet, skip_fresh=True)
    except Exception as e:                                   # noqa: BLE001
        return (f"difference tracking after the stage failed "
                f"({type(e).__name__}: {e}); the stage itself is unaffected")
    entry = next((v for v in mf.get("versions") or []
                  if str(v.get("round")) == str(r) and str(v.get("version")) == str(vid)),
                 {})
    if not quiet:
        print(f"  [track] {rec.get('id')}: "
              + tracking_summary_line(entry, f"{TRACKING_DIRNAME}/r{r}_{vid}/"))
    _t, _f, _s, failed = tracking_entry_counts(entry)
    if failed:
        return (f"difference tracking wrote {failed} pair(s) with NO copy "
                f"(see {TRACKING_DIRNAME}/README.md)")
    return ""


def track_template_stage(ctx: Ctx, sb, *, quiet: bool = False) -> dict:
    """Difference-tracking copies for the template-first stage's package.

    The conformed package `<sb>/out/` is round 1's working original (a1), so it
    is tracked like any stage version: against the pre-conformed submission
    (`non_revised/`), with the copies BESIDE the documents in `out/` and
    mirrored under `<root>/tracking/r1_a1/`. Idempotent: a stored r1_a1 entry
    whose copies still match the documents is kept, so a re-check never drives
    Word/latexdiff again.
    """
    out = Path(sb) / "out"
    if not out.is_dir():
        return {"ok": False, "error": f"{out} is missing"}
    srcs = [(out, "", CORPUS_EXCLUDE_TOP)]
    baselines = [(TRACK_TOKEN_ORIGINAL, [(ctx.pristine, "", ())],
                  "the pre-conformed submission (non_revised/)")]
    out_root = ensure_aux_output_root(ctx.root, TRACKING_DIRNAME)
    stored = read_json(out_root / TRACKING_MANIFEST) or {}
    prev = {(str(v.get("round")), str(v.get("version"))): v
            for v in stored.get("versions") or []}
    key = ("1", A1_ID)
    if key in prev and tracking_entry_is_fresh(ctx, prev[key], baselines, srcs):
        return {"ok": True, "entry": prev[key], "skipped": True}
    entry = {"round": 1, "version": A1_ID, "tool": "auto", "stage": "template-rewrite",
             "out_dir": f"{TRACKING_DIRNAME}/r1_{A1_ID}/", "previous_baseline": "",
             "comparisons": [], "skipped": []}
    memo = {}
    index = redline_index(None)
    for token, base_sources, note in baselines:
        if not any(s.is_dir() for s, _p, _e in base_sources):
            entry["skipped"].append({"baseline": token, "reason": "no base corpus"})
            continue
        _track_one_entry(ctx, entry, out_key=f"r1_{A1_ID}", r=1, vid=A1_ID,
                         token=token, base_sources=base_sources, note=note,
                         srcs=srcs, tool="auto", redline_cmd=None, index=index,
                         in_package=True, quiet=quiet, memo=memo)
    compile_tracking_pdfs(ctx, entry, quiet=quiet)
    _close_tracking_entry(entry)
    manifest = merge_tracking_entries(ctx, [entry], tool="auto")
    return {"ok": True, "entry": entry, "manifest": manifest, "skipped": False}


def maybe_track_template_stage(ctx: Ctx, sb, *, quiet: bool = False) -> str:
    """Write/refresh the template stage's copies; never fatal (returns a warning)."""
    if not stage_tracking_enabled(ctx):
        return ""
    try:
        res = track_template_stage(ctx, sb, quiet=quiet)
    except Exception as e:                                   # noqa: BLE001
        msg = (f"difference tracking after the template stage failed "
               f"({type(e).__name__}: {e})")
        print(f"[track] template-first stage: WARNING: {msg}")
        return msg + "; the stage itself is unaffected"
    if not res.get("ok"):
        msg = str(res.get("error") or "unknown error")
        print(f"[track] template-first stage: WARNING: {msg}")
        return f"difference tracking failed: {msg}"
    if not res.get("skipped") and not quiet:
        print(f"[track] template-first stage: "
              + tracking_summary_line(res.get("entry") or {},
                                      f"{TRACKING_DIRNAME}/r1_{A1_ID}/")
              + f" (beside {Path(sb) / 'out'}/)")
    return ""


# `\input`/`\include`/`\addbibresource`/`\bibliography` references inside a
# latexdiff copy: a reference whose target has its OWN tracked copy is pointed at
# that copy, so the compiled marked-up PDF shows the tracked version of every
# part (an include's own diff, the tracked bibliography).
TEX_TRACK_REF_RE = re.compile(
    r"\\(?P<cmd>input|include|addbibresource|bibliography)\s*"
    r"(?P<opt>\[[^\]\n]*\])?\s*\{(?P<args>[^{}\n]*)\}")

# A tracked `.bib` inside a `plain`-style BibTeX run is CASE-CHANGED by the
# style (`change.case$` lowercases the field text, `\DIFdel{...}` ->
# `\difdel{...}`), and the lowercase control sequences are undefined. The
# rewired tracking `.tex` therefore carries aliases for them.
BIB_TRACK_ALIAS_BLOCK = (
    "% latexdiff aliases (paper_pipeline): BibTeX styles may change.case$ the\n"
    "% tracked bibliography fields, lowercasing \\DIFdel/\\DIFadd.\n"
    "\\providecommand{\\difdelbegin}{\\DIFdelbegin}\n"
    "\\providecommand{\\difdelend}{\\DIFdelend}\n"
    "\\providecommand{\\difaddbegin}{\\DIFaddbegin}\n"
    "\\providecommand{\\difaddend}{\\DIFaddend}\n"
    "\\providecommand{\\difdel}[1]{\\DIFdel{#1}}\n"
    "\\providecommand{\\difadd}[1]{\\DIFadd{#1}}\n"
    "\\providecommand{\\difdelbeginFL}{\\DIFdelbeginFL}\n"
    "\\providecommand{\\difdelendFL}{\\DIFdelendFL}\n"
    "\\providecommand{\\difaddbeginFL}{\\DIFaddbeginFL}\n"
    "\\providecommand{\\difaddendFL}{\\DIFaddendFL}\n"
    "\\providecommand{\\difdelFL}[1]{\\DIFdelFL{#1}}\n"
    "\\providecommand{\\difaddFL}[1]{\\DIFaddFL{#1}}\n")


def _track_tex_ref_target(name: str, cmd: str) -> tuple:
    """(the rel path whose tracked sibling may exist, its target extension)."""
    p = Path(str(name).strip())
    ext = p.suffix.lower()
    if ext in (".tex", ".bib"):
        return p.as_posix(), ext
    target = ".bib" if cmd in ("addbibresource", "bibliography") else ".tex"
    return p.as_posix() + target, target


def rewire_tracking_tex(text: str, tex_path: Path, tracked: dict) -> tuple:
    """Point a latexdiff copy's file references at the TRACKED siblings.

    `tracked` maps a usable tracked file's ORIGINAL corpus-relative path
    (`refs.bib`, `sections/intro.tex`) to the path of its tracked copy on disk.
    A reference with no tracked sibling is left exactly as written -- an
    unchanged include must keep loading the shared file, and a failed
    comparison's logging fallback (commented-out diff) must never be loaded.
    Returns (new text, [{command, from, to}, ...]); the caller writes the text
    only when the list is non-empty.
    """
    rewrites = []
    bib_rewired = False
    base = Path(tex_path).parent

    def repl(m):
        nonlocal bib_rewired
        cmd = m.group("cmd")
        names = [n.strip() for n in m.group("args").split(",")]
        new_names, changed = [], False
        for name in names:
            if not name or re.search(r"\.(?:tracking|logging)-", name, re.IGNORECASE):
                new_names.append(name)
                continue
            rel, _ext = _track_tex_ref_target(name, cmd)
            target = tracked.get(rel) or tracked.get(name)
            if target is None:
                new_names.append(name)
                continue
            new_name = os.path.relpath(str(target), str(base)).replace(os.sep, "/")
            if not Path(name).suffix and cmd != "addbibresource":
                # LaTeX/BibTeX supply the extension for \input/\include/\bibliography,
                # so the tracked copy may keep the caller's extension-less spelling;
                # biblatex's \addbibresource REQUIRES the .bib extension, so a
                # reference that omitted it must gain it (never lose it).
                new_name = str(Path(new_name).with_suffix("")).replace(os.sep, "/")
            new_names.append(new_name)
            rewrites.append({"command": cmd, "from": name, "to": new_name})
            if cmd in ("addbibresource", "bibliography"):
                bib_rewired = True
            changed = True
        if not changed:
            return m.group(0)
        return "\\" + cmd + (m.group("opt") or "") + "{" + ", ".join(new_names) + "}"

    out = TEX_TRACK_REF_RE.sub(repl, text)
    if bib_rewired and "\\difdelbegin" not in out:
        pos = out.find("\\begin{document}")
        if pos < 0:
            out = out + "\n" + BIB_TRACK_ALIAS_BLOCK
        else:
            out = out[:pos] + BIB_TRACK_ALIAS_BLOCK + out[pos:]
    return out, rewrites


def compile_tracking_pdfs(ctx: Ctx, entry: dict, *, quiet: bool = False) -> None:
    """Compile every tracking `.tex` ROOT into `*.tracking-<token>.pdf`.

    The copy is first rewired to the tracked siblings of the files it includes
    or loads (see rewire_tracking_tex); the build runs in a disposable copy of
    the package (compile_latex_pdf with keep_aux=True), so no `.aux`/`.log`
    by-product lands in the package. The PDF is written BESIDE the tracking
    `.tex`, mirrored under <root>/tracking/, and recorded on the row (`pdf`,
    `pdf_in_package`, `pdf_ok`, `pdf_error`). A compile failure is a WARNING:
    the tracked `.tex` stays, and the round is never failed.

    A byte-identical pair (an unmarked `identical-copy` row) is compiled too:
    the marked-up PDF of a version with no textual change is its clean PDF, and
    a copy whose INCLUDES changed still shows those tracked includes. Only a
    LaTeX FRAGMENT is skipped -- it is compiled through its master.
    """
    rows = list((entry or {}).get("comparisons") or [])
    tracked = {}
    for c in rows:
        if c.get("ok") and c.get("tool") and not c.get("fallback") and c.get("in_package"):
            rel = str(c.get("revised_rel") or "")
            if rel:
                # Keyed by (baseline token, rel path): the tracked include/
                # bibliography for a token is only valid for that token's copy.
                tracked[(str(c.get("baseline") or ""), rel)] = ctx.root / str(c["in_package"])
    memo = {}
    for c in rows:
        if not c.get("ok") or c.get("ext") != ".tex" or not c.get("tool"):
            continue
        if c.get("fallback") or not c.get("in_package"):
            # a1's raw base has no in-package copy to build beside; a logging
            # fallback is a commented-out diff, not a compilable document.
            continue
        src = ctx.root / str(c["in_package"])
        token = str(c.get("baseline") or "")
        if not src.is_file():
            c["pdf_ok"], c["pdf_error"] = False, "the tracking .tex is missing"
            continue
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            if not re.search(r"\\documentclass\b", text):
                # A fragment is compiled through its master; standalone it is
                # not a document (`!\begin{document}`).
                c["pdf_skipped"] = "not a LaTeX root (a fragment compiled through its master)"
                continue
            token_refs = {rel: path for (tok, rel), path in tracked.items() if tok == token}
            new_text, rewrites = rewire_tracking_tex(text, src, token_refs)
            if rewrites:
                c["ref_rewrites"] = rewrites
                for target in (src, ctx.root / str(c.get("out") or "")):
                    if target.is_file():
                        # The copy may have inherited a read-only mode from a
                        # read-only staged source (the template-first package):
                        # our own auxiliary is made writable before the rewrite.
                        tracking_force_writable(target)
                        target.write_text(new_text, encoding="utf-8")
        except OSError as e:                                 # noqa: BLE001
            c["pdf_ok"], c["pdf_error"] = (
                False, f"the tracking .tex could not be rewritten: {e}")
            continue
        # The package root is the ancestor the row's own rel path descends to
        # (the file name is the tracked spelling, so the depth is unchanged).
        pkg = src
        for _part in Path(str(c.get("revised_rel") or "")).parts:
            pkg = pkg.parent
        out_pdf = src.with_suffix(TRACKING_PDF_EXT)
        digest = sha256_file(src)
        earlier = memo.get(digest)
        if earlier is not None:
            shutil.copy2(earlier, out_pdf)
            res = {"ok": True, "tool": "copied-from-identical-tracking-tex",
                   "pages": _pdf_page_count(out_pdf), "error": None}
        else:
            try:
                rel_in_pkg = src.relative_to(pkg).as_posix()
            except ValueError:                               # pragma: no cover
                rel_in_pkg = src.name
            res = compile_latex_pdf(pkg, rel_in_pkg, out_pdf, keep_aux=True,
                                    link_evidence=True)
        c["pdf_ok"] = bool(res.get("ok"))
        c["pdf_error"] = res.get("error")
        c["pdf_pages"] = int(res.get("pages") or 0)
        c["pdf_tool"] = res.get("tool")
        if not c["pdf_ok"]:
            if not quiet:
                print(f"  [track] PDF WARNING: {c.get('revised_rel')} vs {token}: "
                      f"{c.get('pdf_error')}")
            continue
        c["pdf_in_package"] = out_pdf.relative_to(ctx.root).as_posix()
        if c.get("out"):
            mirror_pdf = (ctx.root / str(c["out"])).with_suffix(TRACKING_PDF_EXT)
            mirror_pdf.parent.mkdir(parents=True, exist_ok=True)
            tracking_force_writable(mirror_pdf)
            shutil.copy2(out_pdf, mirror_pdf)
            c["pdf"] = mirror_pdf.relative_to(ctx.root).as_posix()
        memo.setdefault(digest, out_pdf)


def track_one_pair(ctx: Ctx, r: int, vid: str, token: str, ext: str, pair: dict,
                   tool: str, redline_cmd: list, index: dict, out_key: str = None,
                   in_package: bool = True, reuse_source: str = "",
                   memo: dict = None) -> dict:
    """Produce ONE tracking copy (+ its logging fallback) for one pair.

    `out_key` is the directory under <root>/tracking/ the copy is mirrored into
    (`r<R>_<vid>` for a version, `round<R>_winner` for a published winner);
    `in_package` writes the copy beside the candidate document as well -- false
    only for a1, whose `base/` is a raw hash-verified input manifest.

    `token` names the baseline (it is the copy's file-name token and the
    manifest row's `baseline`); `reuse_source` is the REDLINES-tree label whose
    already-produced redline may stand in for this pair -- "from-original" only
    for the original baseline, "from-base" only when the baseline really is the
    round base. The reuse itself is digest-gated (see `_reusable_redline`).

    `memo` is the entry's {(base_digest, cand_digest, ext, destination dir): out
    path} map: the round-1 tracks repeat the SAME comparison twice (against the
    pristine original and against the round base `a1`, which is its
    byte-identical copy), so a pair already produced for the same destination is
    copied instead of driving the difference tool again.
    """
    base, cand = pair["base_path"], pair["cand_path"]
    suffix = tracking_aux_suffix(token, ext)
    fb_suffix = tracking_aux_suffix(token, ext, fallback=True)
    rel_dir = Path(pair["cand_rel"]).parent
    persist_root = ctx.root / TRACKING_DIRNAME / (out_key or f"r{r}_{vid}") / token
    persist_out = persist_root / rel_dir / f"{cand.stem}{suffix}"
    persist_fallback = persist_root / rel_dir / f"{cand.stem}{fb_suffix}"
    # The in-package copy: written beside the candidate document, EXCEPT for the
    # a1 base, whose `base/` is a raw hash-verified input manifest (writing into
    # it would read as a modified input). a1 keeps its copies under <root>/tracking/.
    in_pkg_out = (cand.parent / f"{cand.stem}{suffix}") if in_package else None
    # Re-tracking an entry must be able to REPLACE its own previous copies, and
    # those inherited the (possibly read-only) mode of the staged package.
    for existing in (persist_out, persist_fallback, in_pkg_out):
        tracking_force_writable(existing)
    rec = {"baseline": token, "ext": ext,
           "base_rel": pair["base_rel"], "revised_rel": pair["cand_rel"],
           "basis": pair["basis"], "out": persist_out.relative_to(ctx.root).as_posix(),
           "in_package": (in_pkg_out.relative_to(ctx.root).as_posix() if in_pkg_out else None),
           # The two digests the row describes: the freshness gate of the
           # automatic round-close pass compares them against the documents on
           # disk, so a copy written for superseded bytes is never reused.
           "base_digest": pair.get("base_digest"), "cand_digest": pair.get("cand_digest"),
           "fallback": None, "fallback_out": None, "tool": None, "ok": False,
           "attempts": [], "warning": None, "identical": False, "reused_from": None}
    if tool == "none":
        # `--tool none` asks for NO difference tool at all (the same contract as
        # `redline --tool none`): the row is reported as skipped and no copy --
        # not even a logging fallback -- is written for the pair.
        rec["skipped"] = True
        rec["reason"] = "tool=none: only the manifest/report was requested"
        return rec
    # A produced copy is only reusable by a pair that lands in the SAME place:
    # compile_tracking_pdfs rewires a .tex copy relative to its directory, so the
    # same digests moved elsewhere (a structural rewrite that moves the master
    # into a subdirectory) must be produced fresh, never copied pre-rewired.
    memo_dir = in_pkg_out.parent if in_pkg_out is not None else persist_out.parent
    try:
        memo_dir = memo_dir.relative_to(ctx.root).as_posix()
    except ValueError:                                       # pragma: no cover
        memo_dir = memo_dir.as_posix()
    key = (pair["base_digest"], pair["cand_digest"], ext, memo_dir)
    if memo is not None and memo.get(key):
        earlier = ctx.root / str(memo[key])
        if earlier.is_file():
            persist_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(earlier, persist_out)
            rec["ok"] = True
            rec["tool"] = "copied-from-identical-baseline"
            rec["reused_from"] = str(memo[key])
            rec["attempts"] = [{"backend": "identical-baseline-copy", "cmd": [], "rc": 0,
                                "ok": True,
                                "detail": f"the same pair was already tracked as "
                                          f"{memo[key]}; the copy is byte-identical"}]
            if in_pkg_out is not None:
                try:
                    _tracking_write_copy(persist_out, in_pkg_out)
                except OSError as e:                            # noqa: BLE001
                    rec["warning"] = f"the in-package copy failed: {e}"
            return rec
    if pair["base_digest"] == pair["cand_digest"] and ext == ".docx":
        # Byte-identical pair: no difference to mark. The built-in writer emits a
        # valid, mark-free copy (cheap and deterministic), so no Word/COM round
        # trip is spent on a pair nothing changed.
        rec["identical"] = True
        res = redline_one_pair("builtin", [], base, cand, persist_out)
    elif pair["base_digest"] == pair["cand_digest"]:
        # A .tex/.bib pair with identical bytes: the tracked copy IS the source.
        rec["identical"] = True
        persist_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cand, persist_out)
        res = {"ok": True, "tool": "identical-copy", "attempts": [
            {"backend": "identical-copy", "cmd": [], "rc": 0, "ok": True,
             "detail": "the two documents are byte-identical; the copy carries no marks"}]}
    elif ext == ".docx":
        reused = _reusable_redline(index, r, vid, reuse_source, pair)
        reused_path = (ctx.root / str(reused.get("out"))) if reused.get("out") else None
        if reused.get("ok") and reused_path and reused_path.is_file():
            persist_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reused_path, persist_out)
            res = {"ok": True, "tool": f"{reused.get('tool')} (reused from {REDLINE_DIRNAME}/)",
                   "warning": reused.get("warning"),
                   "attempts": [{"backend": "reused-redline", "cmd": [], "rc": 0, "ok": True,
                                 "detail": f"copied {reused.get('out')}"}]}
        else:
            res = redline_one_pair(tool, redline_cmd, base, cand, persist_out)
    else:
        res = latexdiff_one_pair(base, cand, persist_out)
    if res.get("ok"):
        rec["ok"], rec["tool"] = True, res.get("tool")
        rec["attempts"], rec["warning"] = res.get("attempts") or [], res.get("warning")
        if memo is not None:
            memo.setdefault(key, rec["out"])
        if in_pkg_out is not None:
            try:
                _tracking_write_copy(persist_out, in_pkg_out)
            except OSError as e:                                # noqa: BLE001
                rec["warning"] = ((rec.get("warning") or "")
                                  + f"; the in-package copy failed: {e}").strip("; ")
        return rec
    # The real comparison failed: write the LOGGING fallback (never a file that
    # looks like a tracked copy).
    reason = ""
    for a in reversed(res.get("attempts") or []):
        if a.get("detail"):
            reason = str(a["detail"])[:200]
            break
    reason = reason or "the difference tool produced no output"
    # A failed re-track must not leave the PREVIOUS real tracking copy beside
    # the new document: its name says "tracked copy of this version", and the
    # fallback branch of the freshness gate only looked at the logging sibling.
    for _stale in (persist_out, in_pkg_out):
        if _stale is not None:
            with contextlib.suppress(OSError):
                Path(_stale).unlink(missing_ok=True)
    if ext == ".docx":
        fb = write_docx_logging_fallback(base, cand, persist_fallback, token, reason)
    else:
        fb = write_text_logging_fallback(base, cand, persist_fallback, token, reason)
    rec["attempts"] = res.get("attempts") or []
    if fb.get("ok"):
        rec["ok"] = True
        rec["tool"] = None
        rec["fallback"] = Path(persist_fallback).name
        rec["fallback_out"] = persist_fallback.relative_to(ctx.root).as_posix()
        rec["warning"] = f"difference tracking failed ({reason}); the logging fallback was written"
        if in_pkg_out is not None:
            in_pkg_fb = in_pkg_out.parent / f"{cand.stem}{fb_suffix}"
            tracking_force_writable(in_pkg_fb)
            try:
                _tracking_write_copy(persist_fallback, in_pkg_fb)
            except OSError as e:                                # noqa: BLE001
                rec["warning"] += f"; the in-package fallback failed: {e}"
    else:
        rec["warning"] = (f"difference tracking failed ({reason}) AND the logging fallback "
                          f"failed: {fb.get('error')}")
    return rec


def _md_cell(text, limit: int = 160) -> str:
    """One table/bullet-safe rendering of arbitrary (tool) output.

    A warning or an error message carries a command line or a renderer's stderr:
    an unescaped `|` would split a markdown table cell and a newline would break
    the row, so both are neutralized here -- the manifest.json keeps the raw text.
    """
    return (str(text or "").replace("|", "\\|").replace("\r", " ").replace("\n", " "))[:limit]


def tracking_readme(manifest: dict) -> str:
    L = ["# Difference tracking (one copy per baseline)", "",
         f"Generated: {manifest['generated']}  |  requested tool: `{manifest['tool']}`", "",
         "Every submission version is tracked against the PRE-CONFORMED ORIGINAL and against",
         "the version it was derived from; every PUBLISHED winner (`round<r>_winner/`) is",
         "tracked against the original and (from round 2) against the previous round's winner.",
         "", "The file name names the BASELINE it was compared against (the token):", "",
         "| file (`.ext` = `.docx` / `.tex` / `.bib`) | meaning |", "|---|---|",
         "| `<name>.tracking-original.ext` | vs the pre-conformed submission (`non_revised/`) |",
         "| `<name>.tracking-a1.ext` | vs the round base `a1` (for round r > 1: the pinned "
         "champion of round r-1, published as `round<r-1>_winner/`) |",
         "| `<name>.tracking-w<k>.ext` | vs the k-th rewritten candidate (an integration's own "
         "base) |",
         "| `<name>.tracking-a<k>.ext` | vs the k-th revised candidate (an integration's own "
         "base) |",
         "| `<name>.tracking-winner<r>.ext` | vs the published winner of round r |",
         "| `<name>.tracking-<token>.pdf` | the compiled PDF of a tracking `.tex` root "
         "(marked-up where the copy differs, clean where it is identical) |",
         "| `<name>.logging-<token>.ext` | the fallback log whenever that comparison could not "
         "be produced |", "",
         "`.docx` pairs use Word's own comparison engine through the `docx-compare` MCP tool",
         "(`Word.Application.CompareDocuments`) when it is configured, then the documented",
         "redline chain (python-redlines[docxodus] -> docx-trackdiff -> --redline-cmd -> the",
         "built-in OOXML writer). `.tex`/`.bib` pairs use `latexdiff`; every tracking `.tex`",
         "copy that is a compile root is rewired to the tracked copies of the files it",
         "includes/loads and compiled into a sibling `.tracking-<token>.pdf` (a fragment is",
         "skipped; an identical pair yields the clean PDF). The copies sit BESIDE the documents the version was",
         "written with (the template-first stage's `out/` included; a1's hash-verified `base/`",
         "excepted), written the moment that stage was accepted; this tree is the prune-proof",
         "mirror.", "",
         "Every file here is an AUXILIARY: it is excluded from every corpus digest, pin, judge",
         "view, fingerprint and revision token, and this pass starts no agent session -- it can",
         "never change a score, a ranking or a champion.", "",
         "| round | version | baseline | pair | tool | result |", "|---|---|---|---|---|---|"]
    for v in manifest["versions"]:
        for c in v["comparisons"]:
            result = ("tracked" if c.get("ok") and c.get("tool")
                      else "LOGGING FALLBACK" if c.get("ok")
                      else "skipped (tool=none)" if c.get("skipped") else "FAILED")
            L.append(f"| {v['round']} | {v['version']} | {c['baseline']} | "
                     f"`{_md_cell(c['base_rel'], 80)}` -> `{_md_cell(c['revised_rel'], 80)}` | "
                     f"{_md_cell(c.get('tool') or '-')} | {result} |")
    warn_rows = [(v["round"], v["version"], c) for v in manifest["versions"]
                 for c in v["comparisons"] if c.get("warning")]
    if warn_rows:
        L += ["", "## Caveats", ""]
        for r, vid, c in warn_rows:
            L.append(f"- r{r} {vid} `{_md_cell(c['revised_rel'], 80)}` ({c['baseline']}): "
                     f"{_md_cell(c['warning'], 240)}")
    skipped = [(v["round"], v["version"], s) for v in manifest["versions"]
               for s in v["skipped"]]
    L += ["", "## Skipped", ""]
    if not skipped:
        L.append("- (none)")
    for r, vid, s in skipped:
        L.append(f"- r{r} {vid}: {s.get('base_rel') or s.get('revised_rel') or ''} "
                 f"({s.get('baseline')}) -- {s['reason']}")
    L += ["", "## Notes", ""] + [f"- {n}" for n in manifest.get("notes") or []]
    L.append("")
    return "\n".join(L)


def cmd_track(args) -> None:
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    # See cmd_redline: an empty/typo root is not a pipeline root.
    ctx.load()
    with ctx.lock("track"):
        _cmd_track_locked(ctx, args)


def _cmd_track_locked(ctx: Ctx, args) -> None:
    cmd_template = None
    if args.redline_cmd:
        try:
            cmd_template = json.loads(args.redline_cmd)
        except ValueError:
            die("--redline-cmd must be a JSON argv list")
        if not isinstance(cmd_template, list) or not cmd_template:
            die("--redline-cmd must be a non-empty JSON argv list with {base}/{revised}/{out}")
    if args.round is not None and int(args.round) < 1:
        die(f"--round takes a 1-based round number, got {args.round!r}")
    rounds = [int(args.round)] if args.round else None
    versions = (None if args.version == "all"
                else [v.strip() for v in str(args.version).split(",") if v.strip()])
    if versions is not None and not all(is_fresh_vid(v) for v in versions):
        bad = [v for v in versions if not is_fresh_vid(v)]
        die(f"--version takes a round-local candidate version id or a comma-separated list "
            f"of them, or 'all'; got {', '.join(bad)}")
    print(f"[track] root={ctx.root} tool={args.tool} rounds={rounds or 'all'} "
          f"versions={versions or 'all versions of each round'}")
    manifest = run_difference_tracking(ctx, rounds=rounds, versions=versions, tool=args.tool,
                                       redline_cmd=cmd_template)
    tracking_summary(manifest, rounds=rounds)
    if not getattr(args, "no_pdf", False):
        pdfs = run_pdf_conversion(ctx, rounds=rounds, versions=versions)
        pdf_summary(pdfs, rounds=rounds)


def tracking_summary(manifest: dict, rounds=None) -> None:
    """One-line-per-fact summary of a tracking manifest (optionally one round)."""
    rounds = set(int(r) for r in rounds) if rounds else None
    versions = [v for v in manifest["versions"]
                if rounds is None or int(v.get("round") or 0) in rounds]
    ok_n = sum(1 for v in versions for c in v["comparisons"]
               if c.get("ok") and c.get("tool"))
    fb_n = sum(1 for v in versions for c in v["comparisons"]
               if c.get("ok") and not c.get("tool"))
    bad_n = sum(1 for v in versions for c in v["comparisons"]
                if not c.get("ok") and not c.get("skipped"))
    skip_n = sum(1 for v in versions for c in v["comparisons"] if c.get("skipped"))
    tools = sorted({c["tool"] for v in versions for c in v["comparisons"]
                    if c.get("ok") and c.get("tool")})
    print(f"[track] {ok_n} tracked copy(ies) written"
          + (f" with {', '.join(tools)}" if tools else "")
          + (f", {fb_n} logging fallback(s)" if fb_n else "")
          + (f", {skip_n} skipped (tool=none)" if skip_n else "")
          + (f", {bad_n} FAILED (no file)" if bad_n else ""))
    root = Path(str(manifest.get("pipeline_root") or "."))
    print(f"[track] manifest: {root / TRACKING_DIRNAME / TRACKING_MANIFEST}")
    print(f"[track] summary:  {root / TRACKING_DIRNAME / 'README.md'}")

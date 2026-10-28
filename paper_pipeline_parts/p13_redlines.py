# -*- coding: utf-8 -*-
# Part 13/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# TRACKED CHANGES (REDLINES)
#
# Every candidate version gets a tracked-changes .docx for each of its sources:
#   from-base          the round's own starting document (runs/r<R>_a1/base/)
#   from-original      the pristine original (non_revised/)
#   from-setup-source  the directory passed to `setup --source` (when it still
#                      exists; otherwise non_revised/ and the manifest says so)
# Pairs are matched like the document-set check (version-token-insensitive name
# plus content), so "manuscript-o.docx" -> "manuscript-p.docx" is one document.
# Tool chain: the docx-compare MCP tool (Word's own CompareDocuments engine,
# via the docxcompare.sh WSL/Git-Bash shim) -> python-redlines[docxodus] (via
# paper_redlines_adapter.py) -> docx-trackdiff ->
# --redline-cmd '<json argv with {base} {revised} {out}>' -> the built-in OOXML
# writer. Every attempt lands in redlines/manifest.json, so a file is never
# presented as a Word redline when it is not one.
# =====================================================================

REDLINE_DIRNAME = "redlines"
REDLINE_AUTHOR = "paper_pipeline"
# The python-redlines adapter ships in the repo root next to the orchestrator;
# `setup` copies it into the root with `paper_docx_format.py` so the tracking
# stage's second backend is available where the run actually executes. A root
# without it used to skip `python-redlines[docxodus]` silently and fall through
# to the weaker engines (see `redline_fidelity`).
REDLINE_ADAPTER_NAME = "paper_redlines_adapter.py"
REDLINE_TOOLS = ("auto", "docx-compare", "redlines", "docx-trackdiff", "builtin", "none")
# The backend NAME every manifest/README row uses for the Word-native compare.
REDLINE_COMPARE_BACKEND = "docx-compare (Word CompareDocuments via MCP)"


# The document kinds the difference-tracking pass covers. `.docx` goes through
# the redline chain (Word's own compare engine first), `.tex`/`.bib` through
# `latexdiff`; anything else is carried verbatim and never diffed.
TRACKABLE_EXTS = (".docx", ".tex", ".bib")


def list_track_files(sources: list, exts=TRACKABLE_EXTS) -> list:
    """[{rel, path, key, digest, ext}] for the trackable files of one corpus view."""
    out = []
    overrides = corpus_source_overrides(sources)
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        for p in sorted(src.rglob("*")):
            # A symlinked candidate document is not package content: the
            # materializer refuses to copy it, and hashing/opening it here read
            # an outside file as a tracked manuscript (the 2026-10-28 audit's
            # F29).
            if p.is_symlink() or not p.is_file() or p.suffix.lower() not in exts \
                    or _is_aux_doc(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if is_evidence_rel(rel):
                # The EVIDENCE areas are read-only inputs, not submission
                # documents (see is_evidence_rel): a reviewer's report or a data
                # table is never tracked as a manuscript difference. The
                # candidate side reaches them through a directory SYMLINK, which
                # the walk does not follow, so without this filter every
                # evidence document would read as a base-only file.
                continue
            full = prefix + rel
            if full in overrides[i]:
                continue
            out.append({"rel": full, "path": p, "key": _doc_key(full),
                        "digest": sha256_file(p), "ext": p.suffix.lower()})
    return out


def list_docx_files(sources: list) -> list:
    """[{rel, path, key, digest}] for the .docx files of one corpus view."""
    return list_track_files(sources, exts=(".docx",))


def match_track_pairs(base_sources: list, cand_sources: list, ext: str) -> tuple:
    """(pairs, unmatched_base, unmatched_candidate) -- 1:1, content-aware.

    Only documents of the SAME extension are ever paired: a `.docx` revision of
    a `.tex` source is a different document, not a tracked change.
    """
    base = [f for f in list_track_files(base_sources) if f["ext"] == ext]
    cand = [f for f in list_track_files(cand_sources) if f["ext"] == ext]
    pool, used = list(enumerate(cand)), set()

    def take(match):
        for i, c in pool:
            if i not in used and match(c):
                used.add(i)
                return c
        return None

    pairs, unmatched = [], []
    for b in base:
        c = (take(lambda c, b=b: c["key"] == b["key"] and c["digest"] == b["digest"])
             or take(lambda c, b=b: c["key"] == b["key"])
             or take(lambda c, b=b: c["digest"] == b["digest"]))
        if c is None:
            unmatched.append(b["rel"])
            continue
        if c["key"] == b["key"] and c["digest"] == b["digest"]:
            basis = "same name + same bytes"
        elif c["key"] == b["key"]:
            basis = "same name (edited)"
        else:
            basis = "same content, other name"
        pairs.append({"base_rel": b["rel"], "base_path": b["path"],
                      "base_digest": b["digest"], "cand_digest": c["digest"],
                      "cand_rel": c["rel"], "cand_path": c["path"], "basis": basis})
    return pairs, unmatched, [c["rel"] for i, c in pool if i not in used]


def match_docx_pairs(base_sources: list, cand_sources: list) -> tuple:
    """(pairs, unmatched_base, unmatched_candidate) for `.docx` -- 1:1, content-aware."""
    return match_track_pairs(base_sources, cand_sources, ".docx")


def redline_adapter_path() -> Path:
    """The python-redlines adapter shipped next to this script.

    `setup` copies it into the root with the other modules (see
    `REDLINE_ADAPTER_NAME`); a root created before that copy existed resolves a
    path that is not there, which is why the backend now also runs the
    engine IN PROCESS (`_redlines_inproc`) before giving up.
    """
    return Path(__file__).resolve().with_name(REDLINE_ADAPTER_NAME)


def _redlines_inproc(base: Path, revised: Path, out: Path) -> dict:
    """Run `python-redlines` in THIS process (no adapter file needed).

    The docxodus engine extracts a binary lazily; a read-only user cache (a
    sandboxed home) makes the first call fail, so the engine is retried against
    a writable temp cache -- the same two-step the adapter performs, minus the
    file-path dependency that silently skipped this backend on every root.
    """
    try:
        import python_redlines as mod                             # noqa: PLC0415
    except ImportError as e:
        return {"backend": "python-redlines[docxodus]", "ok": False, "rc": None,
                "detail": f"python-redlines is not importable: {e}"}
    attempts = []
    for eng_name in ("DocxodusEngine", "XmlPowerToolsEngine"):
        cls = getattr(mod, eng_name, None)
        if cls is None:
            continue
        tmp_cache = None
        for use_tmp in (False, True):
            if use_tmp and tmp_cache is None:
                tmp_cache = tempfile.mkdtemp(prefix="paper-redlines-")
            try:
                data, _stdout, _stderr = (cls(tmp_cache) if use_tmp else cls()).run_redline(
                    REDLINE_AUTHOR, str(base), str(revised))
            except Exception as e:                                # noqa: BLE001
                attempts.append(f"{eng_name}: {type(e).__name__}: {e}")
                continue
            if data:
                try:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    # Write through the reserved descriptor and rename: the
                    # cleared OUT pathname could have been re-linked before this
                    # write, landing the bytes outside the root (F38).
                    _atomic_write_bytes(tmp_path_for(out), out,
                                        lambda f, _data=data: f.write(_data),
                                        binary=True)
                except OSError as e:
                    attempts.append(f"{eng_name}: cannot write {out}: {e}")
                    continue
                if tmp_cache:
                    shutil.rmtree(tmp_cache, ignore_errors=True)
                return {"backend": "python-redlines[docxodus]", "cmd": ["in-process", eng_name],
                        "rc": 0, "ok": True,
                        "detail": f"python-redlines:{eng_name}.run_redline (in process)"}
        if tmp_cache:
            shutil.rmtree(tmp_cache, ignore_errors=True)
    return {"backend": "python-redlines[docxodus]", "ok": False, "rc": None,
            "detail": "; ".join(attempts)[:300] or "no supported engine class"}


def _argv_from_template(template: list, base: Path, revised: Path, out: Path) -> list:
    subs = {"{base}": str(base), "{revised}": str(revised), "{out}": str(out),
            "{base_name}": base.name, "{revised_name}": revised.name,
            "{out_name}": out.name}
    argv = []
    for tok in template:
        for k, v in subs.items():
            tok = tok.replace(k, v)
        argv.append(tok)
    return argv


def _redline_popen_kwargs() -> dict:
    """Run a backend in its OWN process group so a timeout can kill its helpers.

    Word/PowerShell wrappers spawn grandchildren that keep the output file open
    after the direct child is killed; `subprocess.run(timeout=...)` kills only
    the direct child.
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _kill_redline_tree(proc) -> None:
    """Kill the timed-out backend AND every process it spawned."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):           # noqa: PERF203
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):   # noqa: PERF203
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _run_redline_cmd(argv: list, out: Path, timeout: int = 900) -> dict:
    try:
        # A backend that prints a flood must not accumulate it in memory: its
        # stdout/stderr go to temporary files and are read back under a budget
        # (F61).
        with tempfile.TemporaryFile() as out_tmp, tempfile.TemporaryFile() as err_tmp:
            proc = subprocess.Popen(
                [str(a) for a in argv], stdout=out_tmp, stderr=err_tmp,
                **_redline_popen_kwargs())
            try:
                proc.wait(timeout=timeout)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                _kill_redline_tree(proc)
                try:
                    proc.wait(timeout=30)      # reap; never leave a zombie
                except subprocess.TimeoutExpired:
                    pass
                rc = None
            out_tmp.seek(0, os.SEEK_END)
            err_tmp.seek(0, os.SEEK_END)
            over = (out_tmp.tell() > MAX_TOOL_OUTPUT_BYTES
                    or err_tmp.tell() > MAX_TOOL_OUTPUT_BYTES)
            out_tmp.seek(0)
            err_tmp.seek(0)
            so = out_tmp.read(MAX_TOOL_OUTPUT_BYTES + 1).decode("utf-8", "replace")
            err = err_tmp.read(MAX_TOOL_OUTPUT_BYTES + 1).decode("utf-8", "replace")
        if over:
            rc, err, so = None, (f"backend output over the {MAX_TOOL_OUTPUT_BYTES}-byte "
                                 f"budget; refusing it"), ""
        elif rc is None:
            err, so = f"timeout after {timeout}s", ""
        else:
            err, so = (err or "").strip(), (so or "").strip()
    except FileNotFoundError as e:                              # noqa: BLE001
        rc, err, so = None, f"not found: {e}", ""
    except OSError as e:                                        # noqa: BLE001
        rc, err, so = None, f"exec error: {e}", ""
    ok = bool(rc == 0 and out.is_file() and out.stat().st_size > 0)
    ooxml_ok, ooxml_detail = (False, "no output file")
    if ok:
        ooxml_ok, ooxml_detail = docx_is_readable(out)
        ok = ooxml_ok
    detail = (so or err or ooxml_detail)[:300]
    if rc == 0 and not ooxml_ok and out.is_file():
        detail = f"output is not a readable tracked-changes .docx: {ooxml_detail}"
    return {"cmd": [str(a) for a in argv], "rc": rc, "ok": ok, "detail": detail,
            "validated_ooxml": ooxml_ok}


def docx_is_readable(path: Path) -> tuple:
    """(ok, detail): the file is an OOXML package with a parseable document body.

    A tracked-changes deliverable is only ever announced as produced after this
    check: a backend that exits 0 while writing a text file, a truncated zip or a
    marker file must not be reported to the human gate as a redline.
    """
    try:
        with zipfile.ZipFile(path) as z:
            xml = _docx_xml_part(z, "word/document.xml")
        if xml is None:
            return False, "word/document.xml is over the size/entity budget"
        ET.fromstring(xml)
        return True, "readable OOXML (word/document.xml parses)"
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError, RuntimeError,
            NotImplementedError) as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


WORDML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(tag: str) -> str:
    return f"{{{WORDML_NS}}}{tag}"


MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _serialize_document(root, raw: bytes) -> bytes:
    """Serialise `root`, restoring the xmlns declarations ElementTree dropped.

    ElementTree keeps no xmlns:* declaration that no element or attribute uses,
    but it keeps the mc:Ignorable ATTRIBUTE VALUE verbatim. The result then names
    prefixes that are no longer declared anywhere -- a Markup Compatibility
    violation Word answers with "unreadable content"/repair -- while
    `docx_is_readable` still passes it (the package parses fine). Re-add only the
    declarations this serialisation actually lost, so nothing is declared twice.
    """
    out = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    wanted = (root.get("{%s}Ignorable" % MC_NS) or "").split()
    if not wanted:
        return out
    head = out[:4000].decode("utf-8", "replace")
    missing = [p for p in dict.fromkeys(wanted) if ("xmlns:%s=" % p) not in head]
    if not missing:
        return out
    declared = dict(re.findall(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"',
                               raw[:6000].decode("utf-8", "replace")))
    for prefix in missing:
        uri = declared.get(prefix)
        if uri:
            root.set("xmlns:%s" % prefix, uri)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _docx_root(path: Path):
    with zipfile.ZipFile(path) as z:
        raw = _docx_xml_part(z, "word/document.xml")
    if raw is None:
        raise OSError("word/document.xml is over the size/entity budget")
    head = raw[:6000].decode("utf-8", "replace")
    for m in re.finditer(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"', head):
        try:
            ET.register_namespace(m.group(1), m.group(2))
        except ValueError:
            pass
    return raw, ET.fromstring(raw)


def _para_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(_w("t")))


def _track_change(tag: str, counter: list, ts: str):
    el = ET.Element(_w(tag))
    counter[0] += 1
    el.set(_w("id"), str(counter[0]))
    el.set(_w("author"), REDLINE_AUTHOR)
    el.set(_w("date"), ts)
    return el


def _wrap_para(p, tag: str, del_text: bool, counter: list, ts: str):
    """Copy one paragraph, wrapping its run content in w:ins / w:del."""
    new_p = ET.Element(_w("p"))
    pr = p.find(_w("pPr"))
    if pr is not None:
        new_p.append(copy.deepcopy(pr))
    tc = _track_change(tag, counter, ts)
    for child in list(p):
        if child is not pr:
            tc.append(copy.deepcopy(child))
    if del_text:
        for t in tc.iter(_w("t")):
            t.tag = _w("delText")
    new_p.append(tc)
    return new_p


def _para_atoms(p) -> list:
    """[{kind, text, element, rpr, split}] of one paragraph, in document order.

    kind "text": `text` is the run's text, `element` its source element (a run
    or an opaque container such as a hyperlink), `rpr` its own rPr XML, `split`
    True when the writer may cut the text at a character boundary. kind "mark":
    `text` is the XML of an inline element with no text of its own (a SOFT LINE
    BREAK, a tab, a field char, a drawing). "".join(text) is the paragraph text.
    """
    atoms = []
    for ch in list(p):
        if ch.tag == _w("pPr"):
            continue
        if ch.tag == _w("r"):
            rpr_xml = None
            simple = all(g.tag in (_w("rPr"), _w("t"), _w("br"), _w("cr"), _w("tab"),
                                   _w("lastRenderedPageBreak"), _w("noBreakHyphen"),
                                   _w("softHyphen")) for g in ch)
            if not simple:
                # A run carrying something the writer must not split
                # (fldChar/instrText/drawing): keep the WHOLE run.
                atoms.append({"kind": "mark", "text": ET.tostring(ch).decode(),
                              "element": None, "rpr": None, "split": True})
                continue
            for g in list(ch):
                if g.tag == _w("rPr"):
                    rpr_xml = ET.tostring(g).decode()
                elif g.tag == _w("t"):
                    atoms.append({"kind": "text", "text": g.text or "", "element": ch,
                                  "rpr": rpr_xml, "split": True})
                else:
                    mark = ("<w:r>" + (rpr_xml or "") + ET.tostring(g).decode() + "</w:r>")
                    atoms.append({"kind": "mark", "text": mark, "element": None,
                                  "rpr": None, "split": True})
        else:
            text = "".join(t.text or "" for t in ch.iter(_w("t")))
            if text:
                atoms.append({"kind": "text", "text": text, "element": ch,
                              "rpr": None, "split": False})
            else:
                atoms.append({"kind": "mark", "text": ET.tostring(ch).decode(),
                              "element": None, "rpr": None, "split": True})
    return atoms


def _atoms_digest(atoms: list):
    """(text, spans, marks) of an atom list; spans are [start, end, atom]."""
    text, spans, marks, pos = [], [], [], 0
    for atom in atoms:
        if atom["kind"] == "text":
            spans.append([pos, pos + len(atom["text"]), atom])
            text.append(atom["text"])
            pos += len(atom["text"])
        else:
            marks.append([pos, atom])
    return "".join(text), spans, marks


class _ReplaceFallback(Exception):
    """The paragraph cannot be rewritten piecewise: use whole-paragraph markup."""


def _emit_text(out: list, text: str, spans: list, marks: list, start: int, end: int,
               mode: str, counter: list, ts: str) -> None:
    """Append `text[start:end]` to `out`, as tracked changes of `mode`.

    Text pieces are cut at the stream's own run boundaries, and the marks (soft
    line breaks, tabs, field chars) are interleaved at their OWN offsets: a
    SHIFT+ENTER break must stay between the same two words in the redline as in
    the paragraph it came from. A mark inside a deleted piece is a deleted
    break (`<w:delText>` conversion included); a container the stream may not
    split (`atom["split"]` False) only travels whole, else the paragraph falls
    back to whole-paragraph markup.
    """
    if end <= start:
        return

    def text_pieces(s: int, e: int) -> list:
        pieces, pos = [], s
        while pos < e:
            span = next((sp for sp in spans if sp[0] <= pos < sp[1]), None)
            if span is None:
                raise _ReplaceFallback()
            atom = span[2]
            stop = min(e, span[1])
            whole = (pos == span[0] and stop == span[1])
            if not atom["split"] and not whole:
                raise _ReplaceFallback()
            if whole and not atom["split"] and atom["element"] is not None:
                pieces.append(("element", atom["element"]))
            else:
                run = ET.Element(_w("r"))
                if atom["rpr"]:
                    run.append(ET.fromstring(atom["rpr"]))
                t = ET.SubElement(run, _w("delText") if mode == "del" else _w("t"))
                piece_text = text[pos:stop]
                if piece_text[:1].isspace() or piece_text[-1:].isspace():
                    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                t.text = piece_text
                pieces.append(("run", run))
            pos = stop
        return pieces

    def mark_elements(atom) -> list:
        try:
            parsed = ET.fromstring(f'<w:wrap xmlns:w="{WORDML_NS}">'
                                   f'{atom["text"]}</w:wrap>')
        except ET.ParseError:
            return []
        children = [copy.deepcopy(c) for c in list(parsed)]
        if mode == "del":
            for child in children:
                for t in child.iter(_w("t")):
                    t.tag = _w("delText")
        return children

    events = []                                    # ("text", pieces) | ("mark", atom)
    pos = start
    # A mark at the paragraph's FINAL offset (a trailing soft line break) is
    # part of this range: `< end` dropped it, and accepting the redline then did
    # not reproduce the revised paragraph. Boundary marks between two ops are
    # still emitted by exactly one side (the later op's `start`).
    for at, atom in sorted([(a, m) for a, m in marks
                            if start <= a < end
                            or (a == end and end == len(text) and start < end)],
                           key=lambda pair: pair[0]):
        if at > pos:
            events.append(("text", text_pieces(pos, at)))
            pos = at
        events.append(("mark", atom))
    if pos < end:
        events.append(("text", text_pieces(pos, end)))

    if mode == "eq":
        for kind, payload in events:
            if kind == "mark":
                out.extend(mark_elements(payload))
                continue
            for piece_kind, value in payload:
                out.append(copy.deepcopy(value) if piece_kind == "element" else value)
        return
    wrapper = _track_change("del" if mode == "del" else "ins", counter, ts)
    for kind, payload in events:
        if kind == "mark":
            for element in mark_elements(payload):
                wrapper.append(element)
            continue
        for piece_kind, value in payload:
            if piece_kind != "element":
                wrapper.append(value)
                continue
            element = copy.deepcopy(value)
            if mode == "del":
                for t in element.iter(_w("t")):
                    t.tag = _w("delText")
            wrapper.append(element)
    out.append(wrapper)


def _replace_para(bp, rp, counter: list, ts: str):
    """Word-level tracked changes inside one changed paragraph.

    The diff is walked OP BY OP (equal / insert / delete / replace), so the
    tracked-changes document keeps both contracts Word readers rely on:
    ACCEPTING every change reproduces the revised paragraph, and REJECTING every
    change reproduces the base paragraph. Every run's own rPr rides with its
    text, and the non-text inline elements (a SOFT LINE BREAK from SHIFT+ENTER,
    a tab, a Zotero field char) keep their places in both streams -- the old
    writer rebuilt the paragraph from plain text and silently dropped them (the
    2026-10-14 NeoHetero redline's correspondence block lost both of its soft
    line breaks and read as one line).

    A paragraph the walk cannot split piecewise (an opaque hyperlink/field
    container whose text takes part in a change, an unwalkable structure) falls
    back to WHOLE-PARAGRAPH markup: the base paragraph deleted and the revised
    paragraph inserted with its own XML, so nothing inside it is lost either.
    """
    try:
        base_text, base_spans, base_marks = _atoms_digest(_para_atoms(bp))
        rev_text, rev_spans, rev_marks = _atoms_digest(_para_atoms(rp))
    except (ET.ParseError, RecursionError):
        return _whole_paragraph_change(bp, rp, counter, ts)
    if base_text != _para_text(bp) or rev_text != _para_text(rp):
        return _whole_paragraph_change(bp, rp, counter, ts)

    # Token offsets must be the offsets in the FULL paragraph. `\S+\s*`
    # drops a paragraph's leading whitespace, so the cumulative-length offsets
    # below started at 0 and every later slice was shifted by that prefix:
    # accepting "  Hello world" -> "  Hello there" produced "  Hello the".
    base_tok = [(m.start(), m.end(), m.group(0))
                for m in re.finditer(r"\S+\s*", base_text)]
    rev_tok = [(m.start(), m.end(), m.group(0))
               for m in re.finditer(r"\S+\s*", rev_text)]
    base_words = [t[2] for t in base_tok]
    rev_words = [t[2] for t in rev_tok]
    base_off = ([0] + [t[0] for t in base_tok[1:]] + [len(base_text)])
    rev_off = ([0] + [t[0] for t in rev_tok[1:]] + [len(rev_text)])

    out = []
    try:
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, base_words, rev_words, autojunk=False).get_opcodes():
            if tag == "equal":
                _emit_text(out, rev_text, rev_spans, rev_marks,
                           rev_off[j1], rev_off[j2], "eq", counter, ts)
            elif tag == "insert":
                _emit_text(out, rev_text, rev_spans, rev_marks,
                           rev_off[j1], rev_off[j2], "ins", counter, ts)
            elif tag == "delete":
                _emit_text(out, base_text, base_spans, base_marks,
                           base_off[i1], base_off[i2], "del", counter, ts)
            else:
                _emit_text(out, base_text, base_spans, base_marks,
                           base_off[i1], base_off[i2], "del", counter, ts)
                _emit_text(out, rev_text, rev_spans, rev_marks,
                           rev_off[j1], rev_off[j2], "ins", counter, ts)
    except (_ReplaceFallback, ET.ParseError, RecursionError):
        return _whole_paragraph_change(bp, rp, counter, ts)

    new_p = ET.Element(_w("p"))
    pr = rp.find(_w("pPr")) if rp.find(_w("pPr")) is not None else bp.find(_w("pPr"))
    if pr is not None:
        new_p.append(copy.deepcopy(pr))
    for element in out:
        new_p.append(element)
    return new_p


def _whole_paragraph_change(bp, rp, counter: list, ts: str):
    """The fallback: the base paragraph deleted, the revised one inserted AS IS.

    Nothing inside the revised paragraph is rebuilt from text, so every soft
    line break, tab, field and drawing survives; the markup is paragraph-level
    (and the attempt log records that), never lossy.
    """
    wrapper = ET.Element(_w("p"))
    pr = rp.find(_w("pPr")) if rp.find(_w("pPr")) is not None else bp.find(_w("pPr"))
    if pr is not None:
        wrapper.append(copy.deepcopy(pr))
    del_el = _track_change("del", counter, ts)
    for child in list(bp):
        if child is not bp.find(_w("pPr")):
            del_el.append(copy.deepcopy(child))
    for t in del_el.iter(_w("t")):
        t.tag = _w("delText")
    ins_el = _track_change("ins", counter, ts)
    for child in list(rp):
        if child is not rp.find(_w("pPr")):
            ins_el.append(copy.deepcopy(child))
    wrapper.append(del_el)
    wrapper.append(ins_el)
    return wrapper


def builtin_tracked_changes(base_docx: Path, revised_docx: Path, out_docx: Path) -> dict:
    """Write a tracked-changes .docx using the standard library only.

    Paragraph- and word-level w:ins/w:del built from the BASE package, so the
    surrounding document survives. Byte-identical paragraphs are copied
    verbatim; a paragraph whose text is equal but whose XML differs (a soft line
    break, tab, drawing, field or formatting-only run changed) is marked as a
    whole-paragraph change, so accepting it yields the revised paragraph and
    rejecting it yields the base; a changed paragraph is rebuilt from its own
    runs, and each run's `rPr` (character formatting) is carried into the
    w:del/w:ins copy, so only the changed paragraph's text is re-derived. This
    backend is still last in the chain and is named as such in the manifest: it
    cannot represent edits inside tables/content controls (see below).

    What it canNOT represent: edits INSIDE non-paragraph body content. Tables,
    content controls (w:sdt) and section properties are taken from the revised
    package at their revised positions, but no w:ins/w:del is written inside
    them, so an edit inside a table is not marked. That is detected and reported
    (``non_paragraph_changed``) rather than silently dropped; use a real
    tracked-changes backend when the diff touches tables.
    """
    base_raw, base_root = _docx_root(base_docx)
    _, rev_root = _docx_root(revised_docx)
    base_body, rev_body = base_root.find(_w("body")), rev_root.find(_w("body"))
    if base_body is None or rev_body is None:
        raise RuntimeError("docx without a w:body element")
    base_paras, rev_paras = list(base_body.findall(_w("p"))), list(rev_body.findall(_w("p")))
    base_texts = [_para_text(p) for p in base_paras]
    rev_texts = [_para_text(p) for p in rev_paras]
    base_extra = [ET.tostring(c) for c in base_body if c.tag != _w("p")]
    rev_extra = [ET.tostring(c) for c in rev_body if c.tag != _w("p")]
    non_paragraph_changed = base_extra != rev_extra
    counter, ts = [0], datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_body = ET.Element(_w("body"))
    n_ins = n_del = 0
    # Non-paragraph body children (w:tbl, w:sdt, w:sectPr, ...) must keep their
    # position RELATIVE to the paragraphs around them. Appending them all after
    # the paragraph diff relocated every inline table to the end of the redline
    # -- silent layout corruption, and non_paragraph_changed stays False when the
    # table bytes are identical in base and revised.
    # Anchor the non-paragraph body children on BOTH sequences. The revised
    # count keeps a table after an INSERTED paragraph (D-052); the base count
    # keeps a table after a DELETED paragraph from jumping ahead of the w:del,
    # so rejecting all changes reproduces the base order. A child is emitted
    # only once the paragraphs before it in EACH body have been emitted.
    base_extra_anchor, base_seen = [], 0
    for child in list(base_body):
        if child.tag == _w("p"):
            base_seen += 1
        else:
            base_extra_anchor.append(base_seen)
    rev_anchored, rev_seen = [], 0
    for child in list(rev_body):
        if child.tag == _w("p"):
            rev_seen += 1
        else:
            rev_anchored.append([rev_seen, 0, child])  # (rev paras before, base paras before)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, base_extra, rev_extra, autojunk=False).get_opcodes():
        if tag in ("equal", "replace"):
            # Pair each revised child with its base counterpart (a changed table
            # is a replace: same slot, different bytes).
            for off in range(min(i2 - i1, j2 - j1)):
                rev_anchored[j1 + off][1] = base_extra_anchor[i1 + off]
    emitted_base = emitted_rev = flushed = 0

    def flush_anchored() -> None:
        nonlocal flushed
        while (flushed < len(rev_anchored)
               and rev_anchored[flushed][0] <= emitted_rev
               and rev_anchored[flushed][1] <= emitted_base):
            new_body.append(copy.deepcopy(rev_anchored[flushed][2]))
            flushed += 1

    def emit(element, base_after=None, rev_after=None) -> None:
        """Append one element, then flush every anchored child whose base AND
        revised paragraph prefixes have now been emitted."""
        nonlocal emitted_base, emitted_rev
        new_body.append(element)
        if base_after is not None:
            emitted_base = max(emitted_base, base_after)
        if rev_after is not None:
            emitted_rev = max(emitted_rev, rev_after)
        flush_anchored()

    def same_para_xml(a, b) -> bool:
        """Paragraph CONTENT equality: the tail (inter-paragraph whitespace)
        is not part of the paragraph, and a different pretty-print must not
        turn every equal paragraph into a whole-paragraph change.

        Word stamps a new w:rsidR/w:rsidRPr/w:rsidP (and may renumber
        paraId/textId) on every save, even when no character changed. Comparing
        the raw serialisation made a resaved, unchanged manuscript one giant
        delete+insert, which the fidelity check then reported as over-marking.
        Those ids are per-save bookkeeping, not content: strip them (and the
        proofing marks) before the comparison.
        """
        _volatile = re.compile(
            rb"\s(?:[A-Za-z0-9_]+:)?(?:rsid[A-Za-z]*|paraId|textId|durableId)=\"[^\"]*\"")

        def body(el):
            cp = copy.deepcopy(el)
            cp.tail = None
            raw = ET.tostring(cp)
            raw = _volatile.sub(b"", raw)
            raw = re.sub(rb"<w:proofErr\b[^>]*/>", b"", raw)
            return raw
        return body(a) == body(b)

    flush_anchored()                                    # before the first revised para
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, base_texts, rev_texts, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                rp_index = j1 + (k - i1)
                bp, rp = base_paras[k], rev_paras[rp_index]
                if same_para_xml(bp, rp):
                    emit(copy.deepcopy(bp), base_after=k + 1, rev_after=rp_index + 1)
                else:
                    # The text is equal, but the paragraph XML is not: a soft
                    # line break, tab, drawing, field char or formatting-only run
                    # changed. Copying the base paragraph (the old branch) lost
                    # that edit from the redline entirely. Whole-paragraph
                    # markup keeps both contracts: accept-all yields the revised
                    # paragraph, reject-all yields the base.
                    emit(_whole_paragraph_change(bp, rp, counter, ts),
                         base_after=k + 1, rev_after=rp_index + 1)
                    n_del += 1
                    n_ins += 1
        elif tag == "delete":
            for k in range(i1, i2):
                emit(_wrap_para(base_paras[k], "del", True, counter, ts), base_after=k + 1)
                n_del += 1
        elif tag == "insert":
            for off, p in enumerate(rev_paras[j1:j2]):
                emit(_wrap_para(p, "ins", False, counter, ts),
                     base_after=i1, rev_after=j1 + off + 1)
                n_ins += 1
        else:
            common = min(i2 - i1, j2 - j1)
            for k in range(common):
                emit(_replace_para(base_paras[i1 + k], rev_paras[j1 + k], counter, ts),
                     base_after=i1 + k + 1, rev_after=j1 + k + 1)
                n_del += 1
                n_ins += 1
            for k in range(i1 + common, i2):
                emit(_wrap_para(base_paras[k], "del", True, counter, ts), base_after=k + 1)
                n_del += 1
            for off, p in enumerate(rev_paras[j1 + common:j2]):
                emit(_wrap_para(p, "ins", False, counter, ts),
                     base_after=i2, rev_after=j1 + common + off + 1)
                n_ins += 1
    emitted_base = max(emitted_base, len(base_paras))
    emitted_rev = max(emitted_rev, len(rev_paras))
    flush_anchored()                                    # remainder, incl. a trailing sectPr
    base_body.clear()
    for child in list(new_body):
        base_body.append(child)
    payload = _serialize_document(base_root, base_raw)
    out_docx.parent.mkdir(parents=True, exist_ok=True)

    def _write_zip(f) -> None:
        with zipfile.ZipFile(base_docx) as zin, \
                zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    data = payload
                zout.writestr(item, data)

    _atomic_write_bytes(tmp_path_for(out_docx), out_docx, _write_zip, binary=True)
    info = {"paragraphs_inserted": n_ins, "paragraphs_deleted": n_del,
            "revision_ids": counter[0],
            "non_paragraph_changed": non_paragraph_changed}
    if non_paragraph_changed:
        info["warning"] = ("tables/content-controls/section properties differ between base and "
                           "revised; the built-in writer keeps the revised ones in place but "
                           "does NOT mark changes inside them -- inspect the diff with a real "
                           "tracked-changes backend")
    return info


def redline_markup_weight(docx: Path) -> dict:
    """Words the tracked-changes document marks: {"ins": n, "del": n}."""
    ins = dele = 0
    try:
        _, base_root = _docx_root(docx)
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError):
        return {"ins": 0, "del": 0}
    for el in base_root.iter(_w("ins")):
        ins += len(" ".join(t.text or "" for t in el.iter(_w("t"))).split())
    for el in base_root.iter(_w("del")):
        dele += len(" ".join(t.text or "" for t in el.iter(_w("delText"))).split())
    return {"ins": ins, "del": dele}


def redline_minimal_weight(base: Path, revised: Path) -> dict:
    """The least markup a FAITHFUL redline needs for this pair.

    Paragraph-aligned, then word-level inside the paired paragraphs (the
    built-in writer's own alignment). A redline may legitimately exceed it (a
    moved paragraph is delete+insert to every engine that does not track
    moves), so the check this feeds only fires on the order-of-magnitude
    over-marking a whole-paragraph fallback produces -- the 2026-10-14 CNB
    main-text redline marked 624 words for 84 words of real change.
    """
    words = lambda s: len(re.findall(r"\S+\s*", s or ""))          # noqa: E731
    try:
        _, base_root = _docx_root(base)
        _, rev_root = _docx_root(revised)
        base_body, rev_body = base_root.find(_w("body")), rev_root.find(_w("body"))
        base_texts = [_para_text(p) for p in base_body.findall(_w("p"))]
        rev_texts = [_para_text(p) for p in rev_body.findall(_w("p"))]
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError, AttributeError):
        return {"ins": 0, "del": 0}
    ins = dele = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, base_texts, rev_texts, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            ins += sum(words(t) for t in rev_texts[j1:j2])
            continue
        if tag == "delete":
            dele += sum(words(t) for t in base_texts[i1:i2])
            continue
        common = min(i2 - i1, j2 - j1)
        for k in range(common):
            a = re.findall(r"\S+\s*", base_texts[i1 + k])
            b = re.findall(r"\S+\s*", rev_texts[j1 + k])
            for op, a1, a2, b1, b2 in difflib.SequenceMatcher(
                    None, a, b, autojunk=False).get_opcodes():
                if op in ("insert", "replace"):
                    ins += b2 - b1
                if op in ("delete", "replace"):
                    dele += a2 - a1
        ins += sum(words(t) for t in rev_texts[j1 + common:j2])
        dele += sum(words(t) for t in base_texts[i1 + common:i2])
    return {"ins": ins, "del": dele}


def redline_fidelity(base: Path, revised: Path, out: Path) -> dict:
    """How faithful `out` is, as far as a code-side check can tell.

    `over_marked` is the red-flag the 2026-10-14 run needed: a backend that
    rewrites whole paragraphs when it cannot diff their runs (docx-trackdiff's
    granular fallback) marks an order of magnitude more words than the pair
    really changes, which a reader takes for "a huge edit". The tracking stage
    records these numbers per attempt and prefers the least-marked backend.
    """
    marked = redline_markup_weight(out)
    minimal = redline_minimal_weight(base, revised)
    marked_w = marked["ins"] + marked["del"]
    minimal_w = minimal["ins"] + minimal["del"]
    over = bool(minimal_w) and marked_w > max(3 * minimal_w, minimal_w + 200)
    return {"marked_words": marked_w, "minimal_words": minimal_w,
            "marked_ins": marked["ins"], "marked_del": marked["del"],
            "minimal_ins": minimal["ins"], "minimal_del": minimal["del"],
            "over_marked": over}


def redline_one_pair(tool: str, cmd_template: list, base: Path, revised: Path,
                     out: Path) -> dict:
    """Create one tracked-changes docx; returns the attempt log (never raises)."""
    # The Word-native compare engine (Word's own CompareDocuments through the
    # operator's `docx-compare` MCP server) is the FIRST choice for tracking the
    # differences between two .docx files. It is probed once per pair: an
    # unconfigured server is simply not in the chain, while a configured server
    # whose call fails is recorded and the next backend takes over.
    compare_spec = docx_compare_mcp_spec()
    if tool == "none":
        order = ()
    elif tool == "auto":
        order = ["docx-compare"] + ["redlines", "docx-trackdiff"] \
            + (["redline-cmd"] if cmd_template else []) + ["builtin"]
    elif tool == "builtin":
        # a user-supplied command is a request, not a last-resort fallback
        order = (["redline-cmd"] if cmd_template else []) + ["builtin"]
    else:
        order = [tool] + (["redline-cmd"] if cmd_template else [])
    out.parent.mkdir(parents=True, exist_ok=True)      # external tools need the directory

    # OUT must never be one of the INPUTS: drop_stale_out() unlinks it before
    # the first backend, so an operator typo or a caller deriving OUT from an
    # input destroyed the manuscript the diff was about. paper_redlines_adapter
    # already refuses this; the in-tree backend chain did not.
    for label, src in (("base", base), ("revised", revised)):
        try:
            same = out.resolve() == src.resolve()
            if not same and out.exists() and src.exists():
                same = os.path.samefile(out, src)
        except OSError:
            same = False
        if same:
            return [{"backend": "input-guard", "cmd": [], "rc": None, "ok": False,
                     "detail": f"refusing to use the {label} file as OUT: it would be "
                               f"deleted before the diff"}]

    def drop_stale_out(backend_name: str):
        """Claim OUT for the next attempt; returns an attempt record on failure.

        `_run_redline_cmd` scores a backend by "rc == 0 and OUT is a readable
        OOXML package", so a file left at OUT by an earlier backend (or by a
        previous run) would be credited to a backend that wrote nothing at all.
        """
        try:
            out.unlink()
            return None
        except FileNotFoundError:
            return None
        except OSError as e:                                    # noqa: BLE001
            return {"backend": backend_name, "cmd": [], "rc": None, "ok": False,
                    "detail": f"cannot clear a stale output file: {e}"}

    attempts = []
    winner = None
    best = None                     # (marked words, temp copy, attempt record)
    for backend in order:
        stale = drop_stale_out(backend)
        if stale:
            attempts.append(stale)
            continue
        if backend == "redline-cmd":
            res = _run_redline_cmd(_argv_from_template(cmd_template, base, revised, out), out)
            res["backend"] = "redline-cmd"
            attempts.append(res)
        elif backend == "docx-compare":
            if not compare_spec:
                # Not an attempt: the machine has no usable compare server, so
                # the chain moves on. Recorded, so the manifest says why the
                # first-choice engine was not the one that produced the file --
                # WITH the probe's own reason (a missing command, a deleted
                # script, an uninstalled Node dependency), which is what tells
                # the operator what to fix.
                reason = mcp_server_unusable_reason(DOCX_COMPARE_MCP_SERVER)
                attempts.append({
                    "backend": REDLINE_COMPARE_BACKEND,
                    "cmd": ["mcp", DOCX_COMPARE_MCP_SERVER, DOCX_COMPARE_MCP_TOOL],
                    "rc": None, "ok": False, "skipped": True,
                    "detail": f"the {DOCX_COMPARE_MCP_SERVER!r} MCP server is not configured/"
                              f"startable on this machine"
                              + (f" ({reason})" if reason else "")
                              + "; the next redline backend was used"})
                continue
            res = mcp_compare_docx(compare_spec, base, revised, out)
            ooxml_ok, ooxml_detail = (docx_is_readable(out) if res.get("ok")
                                      else (False, "no output file"))
            detail = ooxml_detail if res.get("ok") else str(res.get("error") or "")[:300]
            attempts.append({
                "backend": REDLINE_COMPARE_BACKEND,
                "cmd": ["mcp", DOCX_COMPARE_MCP_SERVER, DOCX_COMPARE_MCP_TOOL,
                        str(base), str(revised), str(out)],
                "rc": 0 if (res.get("ok") and ooxml_ok) else None,
                "ok": bool(res.get("ok") and ooxml_ok), "detail": detail,
                "validated_ooxml": bool(ooxml_ok)})
        elif backend == "redlines":
            stale = drop_stale_out(backend)
            if stale:
                attempts.append(stale)
                continue
            res = _redlines_inproc(base, revised, out)
            ooxml_ok, ooxml_detail = (docx_is_readable(out) if res.get("ok")
                                      else (False, "no output file"))
            res["validated_ooxml"] = bool(ooxml_ok)
            if res.get("ok") and not ooxml_ok:
                res["ok"] = False
                res["detail"] = f"the engine wrote an unreadable package: {ooxml_detail}"
                attempts.append(res)
                continue
            attempts.append(res)
            if not res.get("ok"):
                # The engine was not importable (or failed): fall back to the
                # adapter CLI, which probes further interface shapes.
                adapter = redline_adapter_path()
                if not adapter.is_file():
                    attempts.append({"backend": "python-redlines[docxodus]", "ok": False,
                                     "rc": None, "detail": f"adapter missing: {adapter}"})
                else:
                    res2 = _run_redline_cmd([sys.executable, str(adapter), str(base),
                                             str(revised), str(out)], out)
                    res2["backend"] = "python-redlines[docxodus]"
                    attempts.append(res2)
        elif backend == "docx-trackdiff":
            for argv in (["docx-trackdiff", str(base), str(revised), str(out)],
                         ["docx-trackdiff", "--base", str(base), "--revised", str(revised),
                          "--out", str(out)],
                         [sys.executable, "-m", "docx_trackdiff", str(base), str(revised),
                          str(out)]):
                stale = drop_stale_out(backend)
                if stale:
                    attempts.append(stale)
                    break
                res = _run_redline_cmd(argv, out)
                res["backend"] = "docx-trackdiff"
                attempts.append(res)
                if res["ok"]:
                    break
        else:
            try:
                info = builtin_tracked_changes(base, revised, out)
                attempts.append({"backend": "builtin-ooxml", "cmd": ["builtin"], "rc": 0,
                                 "ok": True,
                                 "detail": f"w:ins paragraphs={info['paragraphs_inserted']} "
                                           f"w:del paragraphs={info['paragraphs_deleted']}",
                                 "non_paragraph_changed": info.get("non_paragraph_changed"),
                                 "warning": info.get("warning")})
            except Exception as e:                              # noqa: BLE001
                attempts.append({"backend": "builtin-ooxml", "cmd": ["builtin"], "rc": None,
                                 "ok": False, "detail": str(e)[:300]})
        last = attempts[-1] if attempts else None
        if not (last and last.get("ok")):
            continue
        # A backend that produced a readable redline is not yet a usable one:
        # Word's own compare can mark a moved paragraph delete+insert, but a
        # backend that cannot diff a paragraph's runs rewrites the WHOLE
        # paragraph for a small edit. Measure the markup against the least a
        # faithful redline needs and prefer the quietest engine: a backend that
        # over-marks hands the pair to the next one, and the best (least marked)
        # result is kept when every backend over-marks.
        fidelity = redline_fidelity(base, revised, out)
        last["fidelity"] = fidelity
        if fidelity["over_marked"]:
            last["warning"] = (f"over-marked redline: {fidelity['marked_words']} marked word(s) "
                               f"for {fidelity['minimal_words']} word(s) of real change (the "
                               f"backend rewrites whole paragraphs when a run is not plain "
                               f"text)")
        # An operator's EXPLICIT choice of backend (`--redline-tool`, or a
        # `--redline-cmd` they wired) is honoured: the numbers are recorded and
        # the caveat is reported, but the chain does not shop for a quieter
        # engine. Under `auto`, the quietest engine wins.
        if not fidelity["over_marked"] or tool != "auto":
            winner = last
            break
        fd, saved_name = tempfile.mkstemp(prefix="paper-redline-", suffix=".docx")
        os.close(fd)
        saved = Path(saved_name)
        shutil.copyfile(out, saved)
        if best is None or fidelity["marked_words"] < best[0]:
            if best is not None:
                with contextlib.suppress(OSError):
                    best[1].unlink()
            best = (fidelity["marked_words"], saved, last)
        else:
            with contextlib.suppress(OSError):
                saved.unlink()
    if winner is None and best is not None:
        # No backend stayed inside the fidelity bar: keep the least-marked one
        # (the last backend's output is already at OUT; restore when needed).
        try:
            shutil.copyfile(best[1], out)
        except OSError as exc:
            # The restore failed: OUT is still the LAST backend's (wrong) file.
            # Setting `winner` here made ok=True and the manifest attribute that
            # file to the least-marked backend. Record the failure and leave
            # `winner` unset so the pair is reported as failed.
            attempts.append({"backend": best[2].get("backend", tool), "ok": False,
                             "detail": f"the least-marked candidate could not be restored: {exc}"})
        else:
            winner = best[2]
            winner["fidelity_selected"] = True
            winner["detail"] = (f"{winner.get('detail') or ''} -- kept as the least-marked of "
                                f"{len(attempts)} over-marking attempt(s) ({best[0]} word(s))"
                                ).strip()
    if best is not None:
        with contextlib.suppress(OSError):
            best[1].unlink()
    if not winner and order:
        # The manifest will say FAILED: do not leave a file at OUT for a later
        # reader to mistake for this pair's redline.
        try:
            out.unlink()
        except OSError:
            pass
    validated, validation_detail = (docx_is_readable(out) if winner else (False, "no output"))
    return {"ok": bool(winner), "tool": (winner or {}).get("backend", tool),
            "attempts": attempts, "validated_ooxml": bool(validated),
            "validation_detail": validation_detail,
            "warning": (winner or {}).get("warning")}


def redline_readme(manifest: dict) -> str:
    L = ["# Tracked changes (redlines)", "",
         f"Generated: {manifest['generated']}  |  requested tool: `{manifest['tool']}`", "",
         "Tool chain (first one that works wins):",
         "1. the `docx-compare` MCP tool -- Microsoft Word's OWN comparison engine "
         "(`Word.Application.CompareDocuments`, driven by `docxcompare.sh` through COM "
         "automation) -- when that server is configured on this machine",
         "2. `python-redlines[docxodus]` (through `paper_redlines_adapter.py`, which reports the "
         "interface it used)",
         "3. `docx-trackdiff` (CLI, two argument forms, then `python -m docx_trackdiff`)",
         "4. `--redline-cmd '<json argv with {base} {revised} {out}>'` when you supply one",
         "5. the built-in OOXML word/paragraph-level tracked-changes writer (stdlib only; "
         "unchanged paragraphs are copied verbatim, a changed paragraph carries word-level "
         "w:ins/w:del IN PLACE of its runs -- soft line breaks, tabs and field chars keep their "
         "positions, accepting every change reproduces the revised paragraph and rejecting "
         "every change reproduces the base paragraph).", "",
         "Each row names the backend that actually produced the file; `manifest.json` keeps every "
         "attempt (command, exit code, stderr tail).", "",
         "FIDELITY: every successful attempt is weighed -- the words its w:ins/w:del markup "
         "marks against the least a faithful redline needs for that pair. A backend that marks "
         "an order of magnitude more (it rewrites whole paragraphs when a run is not plain "
         "text, e.g. a Word paragraph carrying `w:lastRenderedPageBreak`) is passed over for "
         "the next one, and the least-marked result is kept when every backend over-marks; "
         "`fidelity` in `manifest.json` carries the numbers, and `over_marked` names the "
         "caveat here.", "",
         "| round | version | source | pair | basis | tool | result |",
         "|---|---|---|---|---|---|---|"]
    for v in manifest["versions"]:
        for c in v["comparisons"]:
            _result = ("skipped (tool=none)" if c.get("skipped")
                       else ("ok" if c["ok"] else "FAILED"))
            L.append(f"| {v['round']} | {v['version']} | {c['source']} | `{c['base_rel']}` -> "
                     f"`{c['revised_rel']}` | {c['basis']} | {c['tool'] or '-'} | "
                     f"{_result} |")
    L += ["", "`ok` means the backend exited 0 AND the file it wrote is a readable OOXML package "
              "(a zip whose `word/document.xml` parses) -- a text dump, a truncated zip or a "
              "marker file is reported as FAILED.", ""]
    warn_rows = [(v["round"], v["version"], c) for v in manifest["versions"]
                 for c in v["comparisons"] if c.get("warning")]
    if warn_rows:
        L += ["## Caveats on files that were still written", ""]
        for r, vid, c in warn_rows:
            L.append(f"- r{r} {vid} `{c['revised_rel']}` ({c['tool']}): {c['warning']}")
        L.append("")
    if manifest["notes"]:
        L += ["", "## Notes", ""] + [f"- {n}" for n in manifest["notes"]]
    L += ["", "## Skipped", ""]
    skipped = [(v["round"], v["version"], s) for v in manifest["versions"] for s in v["skipped"]]
    if not skipped:
        L.append("- (none)")
    for r, vid, s in skipped:
        L.append(f"- r{r} {vid}: {s.get('base_rel') or s.get('revised_rel') or s.get('source')} "
                 f"-- {s['reason']}")
    L.append("")
    return "\n".join(L)


def run_redlines(ctx: Ctx, rounds=None, versions=None, tool: str = "auto",
                 redline_cmd: list = None, quiet: bool = False) -> dict:
    """Generate tracked changes for the requested rounds/versions + manifest.

    `versions=None` means "every candidate of each requested round", which is
    the round's own pool minus the base (M rewrites + N revisions + K
    integrations) -- the set depends on the per-round plan, so it is resolved
    per round rather than from a fixed list.
    """
    rounds = [int(r) for r in (rounds if rounds is not None
                               else range(1, ctx.rounds_count() + 1))]
    versions = list(versions) if versions else None
    out_root = ensure_aux_output_root(ctx.root, REDLINE_DIRNAME)
    src_setup = Path(ctx.state.get("source") or ".")
    # The setup source is only a trustworthy baseline while it still matches the
    # manifest recorded at `setup`: the operator may have edited their working
    # copy since then, and a redline against different bytes would misrepresent
    # what actually changed.
    source_sources, source_note = None, None
    if src_setup.is_dir():
        try:
            setup_manifest = (ctx.state.get("source_manifest_raw")
                              or ctx.source_manifest)
            if setup_manifest and manifests_equal(hash_manifest(src_setup),
                                                  setup_manifest):
                source_sources = [(src_setup, "", ())]
            else:
                source_note = (f"the setup --source directory {str(src_setup)!r} no longer "
                               f"matches the setup-time manifest (it changed on disk); "
                               f"'from-setup-source' used the pristine copy")
        except OSError as e:                                     # noqa: BLE001
            source_note = (f"the setup --source directory {str(src_setup)!r} could not be "
                           f"re-hashed ({e}); 'from-setup-source' used the pristine copy")
    else:
        source_note = (f"the setup --source directory {str(src_setup)!r} no longer exists; "
                       f"'from-setup-source' used the pristine copy")
    manifest = {"generated": utcnow(), "pipeline_root": str(ctx.root), "tool": tool,
                "redline_cmd": redline_cmd,
                "sources": {"from-base": "the round's own base (runs/r<R>_a1/base/)",
                            "from-original": "the pristine original (non_revised/)",
                            "from-setup-source": (str(src_setup) if source_sources else
                                                  "MISSING/UNVERIFIED -- used non_revised/ "
                                                  "instead (see notes)")},
                "versions": [], "notes": []}
    if not source_sources:
        manifest["notes"].append(source_note or
                                 f"the setup --source directory {str(src_setup)!r} is unusable; "
                                 f"'from-setup-source' used the pristine copy")
    for r in rounds:
        # `all` means every candidate the round REALLY produced: the pool minus
        # the base, plus the integration arms its integrator mask selected (a
        # skipped arm has no corpus, so listing it would only add "not
        # materialized" noise to the manifest).
        round_versions = versions if versions is not None else round_candidate_ids_run(ctx, r)
        for vid in round_versions:
            if not is_fresh_vid(vid):
                continue
            srcs = corpus_sources(ctx, r, vid)
            if not any(s.is_dir() for s, _p, _e in srcs):
                manifest["versions"].append({"round": r, "version": vid,
                                             "status": "not materialized",
                                             "comparisons": [], "skipped": []})
                continue
            entry = {"round": r, "version": vid, "out_dir": f"{REDLINE_DIRNAME}/r{r}_{vid}/",
                     "comparisons": [], "skipped": []}
            sources = [("from-base", corpus_sources(ctx, r, A1_ID), None),
                       ("from-original", [(ctx.pristine, "", ())], None),
                       ("from-setup-source", source_sources or [(ctx.pristine, "", ())],
                        None if source_sources else "setup source path missing; used non_revised")]
            for label, base_sources, note in sources:
                if not any(s.is_dir() for s, _p, _e in base_sources):
                    entry["skipped"].append({"source": label, "reason": "no base corpus"})
                    continue
                if note:
                    entry["skipped"].append({"source": label, "reason": note})
                pairs, unmatched_base, unmatched_cand = match_docx_pairs(base_sources, srcs)
                for rel in unmatched_base:
                    entry["skipped"].append({"source": label, "base_rel": rel,
                                             "reason": "no corresponding .docx in the revised "
                                                       "package"})
                for rel in unmatched_cand:
                    entry["skipped"].append({"source": label, "revised_rel": rel,
                                             "reason": "new .docx with no counterpart in this "
                                                       "source"})
                for pair in pairs:
                    out = out_root / f"r{r}_{vid}" / label / pair["cand_rel"]
                    if tool == "none":
                        entry["comparisons"].append({
                            "source": label, "base_rel": pair["base_rel"],
                            "revised_rel": pair["cand_rel"], "basis": pair["basis"],
                            "out": out.relative_to(ctx.root).as_posix(),
                            "tool": None, "ok": False, "skipped": True,
                            "reason": "tool=none: only the manifest/report was requested",
                            "attempts": []})
                        continue
                    else:
                        result = redline_one_pair(tool, redline_cmd, pair["base_path"],
                                                  pair["cand_path"], out)
                    entry["comparisons"].append({
                        "source": label, "base_rel": pair["base_rel"],
                        "revised_rel": pair["cand_rel"], "basis": pair["basis"],
                        # The pair's two content digests: recorded so a LATER
                        # pass (the difference-tracking reuse) can prove the
                        # redline it copies really is the redline of THESE two
                        # documents before it is presented as one.
                        "base_digest": pair.get("base_digest"),
                        "cand_digest": pair.get("cand_digest"),
                        "out": out.relative_to(ctx.root).as_posix(),
                        "tool": result["tool"] if result["ok"] else None,
                        "ok": bool(result["ok"]), "attempts": result["attempts"],
                        "validated_ooxml": bool(result.get("validated_ooxml")),
                        "validation_detail": result.get("validation_detail"),
                        "warning": result.get("warning")})
                    if not quiet:
                        print(f"  [redline] r{r}_{vid}: {pair['cand_rel']} <- {label} "
                              + (f"({result['tool']})" if result["ok"] else "FAILED"))
            ok_n = sum(1 for c in entry["comparisons"] if c["ok"])
            entry["status"] = (f"{ok_n}/{len(entry['comparisons'])} written"
                               if entry["comparisons"] else "no .docx pairs")
            manifest["versions"].append(entry)
    write_json_atomic(out_root / "manifest.json", manifest)
    write_text_atomic(out_root / "README.md", redline_readme(manifest))
    return manifest


def cmd_redline(args) -> None:
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    # A pipeline root has a config/state; an apparent root produced by a typo
    # (or an empty directory) is refused instead of answered with an empty
    # manifest and exit 0.
    ctx.load()
    with ctx.lock("redline"):
        _cmd_redline_locked(ctx, args)


def _cmd_redline_locked(ctx: Ctx, args) -> None:
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
        die(f"--version takes a round-local candidate version id or a comma-separated list of "
            f"them (the round's own plan decides which exist: a1/w1../a2../i1..), or 'all'; "
            f"got {', '.join(bad)}")
    print(f"[redline] root={ctx.root} tool={args.tool} rounds={rounds or 'all'} "
          f"versions={versions or 'all candidates of each round'}")
    manifest = run_redlines(ctx, rounds=rounds, versions=versions, tool=args.tool,
                            redline_cmd=cmd_template)
    ok_n = sum(1 for v in manifest["versions"] for c in v["comparisons"] if c["ok"])
    fail_n = sum(1 for v in manifest["versions"] for c in v["comparisons"]
                 if not c["ok"] and not c.get("skipped"))
    skip_n = sum(1 for v in manifest["versions"] for c in v["comparisons"] if c.get("skipped"))
    warn_n = sum(1 for v in manifest["versions"] for c in v["comparisons"] if c.get("warning"))
    print(f"[redline] {ok_n} tracked-changes docx written, {fail_n} failed"
          + (f", {skip_n} skipped (tool=none)" if skip_n else "")
          + (f", {warn_n} with caveats (see README)" if warn_n else ""))
    print(f"[redline] manifest: {ctx.root / REDLINE_DIRNAME / 'manifest.json'}")
    print(f"[redline] summary:  {ctx.root / REDLINE_DIRNAME / 'README.md'}")
    if fail_n and args.tool != "none":
        sys.exit(4)

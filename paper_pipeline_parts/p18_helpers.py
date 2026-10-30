# -*- coding: utf-8 -*-
# Part 18/18 of the pipeline -- executed by the loader AFTER the command
# functions, in the loader's own module globals. These are pure helpers
# (no module-level side effects): the lower-numbered parts call them at
# runtime, so they may live after the CLI definitions. Split out of
# p04_utils.py to keep every maintained source file under 10,000 lines.
from __future__ import annotations


def ensure_aux_output_root(root, dirname: str) -> Path:
    """Create `<root>/<dirname>/` and refuse a symlinked/escaping root.

    The redline, tracking and PDF manifests, READMEs and rendered artifacts are
    written under these directories. `mkdir(parents=True, exist_ok=True)`
    succeeds when the path is a symlink to an outside directory, so a planted
    `<root>/redlines|tracking|pdfs` link redirected the whole auxiliary tree
    outside --root while the operator saw success (the 2026-10-28 audit's F73).
    """
    root = Path(root)
    out = root / dirname
    if out.is_symlink() or not is_within(out, root):
        die(f"refusing to use {dirname}/: it is a symlink or resolves outside --root "
            f"({root}). Remove the link and re-run.")
    out.mkdir(parents=True, exist_ok=True)
    if out.is_symlink() or not is_within(out, root):
        die(f"refusing to use {dirname}/: it became a symlink or resolves outside --root "
            f"({root}); remove it and re-run.")
    return out


# ---------------------------------------------------------------------------
# Venue profile + M30 seed helpers moved here to keep p04_utils.py under
# the repository's 10,000-line cap; the loader shares one namespace.
# ---------------------------------------------------------------------------

def _venue_style_limits(ctx: Ctx) -> dict:
    """The venue profile's `style_limits` block, validated and copied.

    `{}` when the profile states none. The shape is
    `{"sentence_words": {kind: positive int},
      "paragraph_words": positive int}`; an invalid entry is dropped rather than
    letting a malformed profile crash every scan, and an absent family stays
    absent (the formatter records it as a policy gap).
    """
    prof = venue_profile_of(ctx, required=False)
    data = getattr(prof, "data", {}) or {}
    block = data.get("style_limits")
    if not isinstance(block, dict):
        return {}
    out = {}
    bars = block.get("sentence_words")
    if isinstance(bars, dict):
        clean = {}
        for kind, value in bars.items():
            try:
                n = int(value)
            except (TypeError, ValueError):
                continue
            if n > 0:
                clean[str(kind)] = n
        if clean:
            out["sentence_words"] = clean
    try:
        cap = int(block.get("paragraph_words") or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap > 0:
        out["paragraph_words"] = cap
    return out


def m30_seed_disposition(row) -> str:
    """The disposition the M30 seed already carries for one written value.

    A written number the shipped tables do not prove and the scan could pair
    with NO candidate producer is a recorded `unable` (the hierarchy has no
    producer in this corpus), not an agent task. Pre-filling those rows is what
    keeps a 165-row seed from being skipped wholesale: the agent disposes the
    handful of rows that actually have a producer.
    """
    producer = str((row or {}).get("candidate producer") or "").strip()
    if producer.startswith("(truncated"):
        return ("unable — the M30 seed reached its row cap; the omitted rows were not "
                "compared (this is a coverage gap, not a source-hierarchy conflict)")
    if not producer or producer.startswith("(no shipped table column"):
        return ("unable — no shipped producer in the corpus (M30 structural "
                "row; not a source-hierarchy conflict)")
    return ""


MAX_TOOL_OUTPUT_BYTES = 16 * 1024 * 1024


class ToolOutputOverBudget(Exception):
    """A child process printed more than MAX_TOOL_OUTPUT_BYTES on one stream."""


def _kill_process_group(proc):
    """Kill a `start_new_session=True` child's whole group, not just the child.

    A tool may spawn a helper (a verifier, a converter's worker) that inherits
    the child's process group. `proc.kill()` left those grandchildren running
    after the orchestrator had timed out and moved on (the 2026-10-30 F51).
    """
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def run_bounded(argv, timeout, cwd=None, env=None):
    """Run a child with stdout/stderr bounded in size AND lifetime.

    `subprocess.run(..., stdout=PIPE)` accumulates every byte a verbose or
    malicious tool prints; the timeout does not bound memory (the 2026-10-28
    audit's F61). Two further escapes are closed here:

    * the child gets its OWN session, and a timeout kills the process GROUP,
      so a grandchild spawning `sleep` does not survive the timeout (F51);
    * stdout/stderr are drained through capped reader threads. The old code
      wrote into an unbounded TemporaryFile and checked its size only after
      `proc.wait()`, so a hostile/verbose child could fill the disk for the
      whole timeout (F52). The reader keeps at most MAX_TOOL_OUTPUT_BYTES+1
      bytes, kills the group the moment the cap is crossed, and continues to
      drain (without storing) so the child cannot block on a full pipe.

    The returned bytes are the first MAX_TOOL_OUTPUT_BYTES of each stream; an
    over-budget stream raises `ToolOutputOverBudget` instead.
    """
    cap = MAX_TOOL_OUTPUT_BYTES
    with tempfile.TemporaryFile(buffering=0) as out_f, \
            tempfile.TemporaryFile(buffering=0) as err_f:
        proc = subprocess.Popen(
            [str(a) for a in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        over_budget = threading.Event()

        def _pump(pipe, sink):
            total = 0
            try:
                while True:
                    chunk = pipe.read(65536)
                    if not chunk:
                        break
                    before = total
                    total += len(chunk)
                    if total <= cap:
                        sink.write(chunk)
                    else:
                        # Crossed the cap: keep at most cap+1 bytes (so the
                        # error reports a real size), record the overrun, kill
                        # the whole group, and keep draining without storing.
                        keep = cap + 1 - before
                        if keep > 0:
                            sink.write(chunk[:keep])
                        over_budget.set()
                        _kill_process_group(proc)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    pipe.close()
                except OSError:
                    pass

        readers = [threading.Thread(target=_pump, args=(proc.stdout, out_f), daemon=True),
                   threading.Thread(target=_pump, args=(proc.stderr, err_f), daemon=True)]
        for t in readers:
            t.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_group(proc)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
        for t in readers:
            t.join(timeout=10)
        # A grandchild that escaped the group can keep a pipe open; closing our
        # end forces the reader to EOF instead of leaving it blocked forever.
        for t, pipe in zip(readers, (proc.stdout, proc.stderr)):
            if t.is_alive():
                try:
                    pipe.close()
                except OSError:
                    pass
                t.join(timeout=2)
        out_f.seek(0, os.SEEK_END)
        out_size = out_f.tell()
        err_f.seek(0, os.SEEK_END)
        err_size = err_f.tell()
        if over_budget.is_set() or out_size > cap or err_size > cap:
            raise ToolOutputOverBudget(
                f"tool output over {cap} bytes "
                f"(stdout={out_size}, stderr={err_size})")
        out_f.seek(0)
        err_f.seek(0)
        out = out_f.read(cap + 1)
        err = err_f.read(cap + 1)
    if timed_out:
        raise subprocess.TimeoutExpired(str(argv[0]), timeout)
    return proc.returncode, out, err


TEX_VERBATIM_ENVS = ("verbatim", "lstlisting", "minted", "Verbatim")


def _blank_tex_verbatim(text: str) -> str:
    """`text` with verbatim/listing bodies blanked (newlines kept).

    A code listing is not manuscript prose. count_words.py has always blanked
    these environments; the pipeline's `_tex_length_scan` stripped only their
    command tokens, so the listing's words were charged to the main-text cap
    while the stage script the author is told to run excluded them (the
    2026-10-28 audit's F07). The line count is preserved so caption spans and
    `abstract_end` keep pointing at the same source lines.
    """
    env_names = "|".join(re.escape(name) for name in TEX_VERBATIM_ENVS)
    begin_re = re.compile(r"\\begin\{(" + env_names + r")\}")
    out, in_verb = [], None
    for raw in (text or "").splitlines():
        line = strip_tex_comment(raw)
        if in_verb is not None:
            end = re.search(r"\\end\{" + re.escape(in_verb) + r"\}", line)
            if end is None:
                out.append("")
                continue
            line = line[end.end():]
            in_verb = None
        while True:
            begin = begin_re.search(line)
            if begin is None:
                break
            end = re.search(r"\\end\{" + re.escape(begin.group(1)) + r"\}",
                            line[begin.end():])
            if end is not None:
                line = line[:begin.start()] + line[begin.end() + end.end():]
            else:
                in_verb = begin.group(1)
                line = line[:begin.start()]
                break
        out.append(line)
    return "\n".join(out)


def _tex_float_env_after(line: str, state):
    """The figure/table float environment state after one source line."""
    for tok in re.finditer(r"\\(begin|end)\{(table\*?|figure\*?)\}", line or ""):
        kind = "table" if tok.group(2).startswith("table") else "figure"
        if tok.group(1) == "begin":
            state = kind
        elif state == kind:
            state = None
    return state


def _tex_include_path(base: Path, arg: str):
    """The .tex file an \\input/\\include/\\subfile argument names, or None."""
    arg = str(arg or "").strip().strip('"')
    if not arg:
        return None
    cand = Path(arg)
    if cand.suffix.lower() not in (".tex", ".ltx"):
        cand = Path(str(cand) + ".tex")
    path = cand if cand.is_absolute() else (base / cand)
    try:
        resolved = path.resolve()
        resolved.relative_to(base.resolve())
    except (OSError, ValueError):
        return None                     # a path outside the manuscript directory
    return resolved if resolved.is_file() else None


def _tex_expand_includes(text: str, base: Path, seen=None, source: Path = None,
                         _stack=None):
    """Inline \\input/\\include/\\subfile children so a multi-file paper counts.

    The scan iterated each .tex file independently: the master's
    `\\input{intro}` was stripped as scaffolding, so the master had no body,
    while `intro.tex` had no Abstract/Introduction heading and was skipped. A
    multi-file manuscript was reported as 0 body words (F36). Every occurrence
    of an include expands (the reader sees that text twice); a true cycle is
    broken by the ancestry set; comments are stripped first; an unresolved
    include is named as a gap by the caller.

    `source` is the file `text` was read from. It is seeded into `seen`: an
    a -> b -> a cycle returns to the ROOT, which is not a child and so was
    expanded a second time before the include was suppressed (the 2026-10-28
    audit's F02). `_stack` carries the text of every frame being expanded, so
    even a direct caller that does not know the root's path still stops a cycle
    when the same source text is re-entered.
    """
    # A COPY: siblings on one frame are not ancestors of each other, so the
    # second `\input{body}` must expand again; `child` is discarded after the
    # recursive call (F03).
    seen = set() if seen is None else set(seen)
    if source is not None:
        try:
            seen.add(Path(source).resolve())
        except (OSError, RuntimeError):
            pass
    stack = [] if _stack is None else _stack
    body = strip_tex_comment(text or "")
    stack.append(body)

    def repl(match):
        child = _tex_include_path(base, match.group(1))
        if child is None or child in seen:
            return match.group(0)
        seen.add(child)
        try:
            child_text = child.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return match.group(0)
        if child_text in stack:
            return match.group(0)       # the same source text is already open
        try:
            return _tex_expand_includes(child_text, base, seen, source=child,
                                        _stack=stack)
        finally:
            seen.discard(child)

    try:
        return TEX_INCLUDE_RE.sub(repl, body)
    finally:
        stack.pop()



def _tex_caption_units(text: str) -> list:
    """(float kind, caption text) for \\caption / \\captionof, in file order.

    The kind is `figure`/`table` so M18's figure-legend inventory does not file
    a table caption as a figure legend (F09). `\\captionof{table}{...}` states
    the kind itself; a bare `\\caption` takes the enclosing float environment.
    """
    out = []
    # \*? -- \caption*{...} is the unnumbered form of the same caption.
    # The type argument exists ONLY on \captionof: treating it as optional on
    # \caption let `\caption{Alpha} {gamma}` capture the trailing body brace.
    for m in re.finditer(
            r"\\(?:captionof\*?\s*\{[^{}]*\}\s*(?:\[[^\]]*\]\s*)?"
            r"|caption\*?\s*(?:\[[^\]]*\]\s*)?)\{", text):
        i, depth, j, esc = m.end() - 1, 1, m.end(), False
        while j < len(text):
            ch = text[j]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth:                      # unbalanced: never swallow the rest of the file
            continue
        kind = None
        of = re.match(r"\\captionof\*?\s*\{([^{}]*)\}", text[m.start():])
        if of:
            kind = of.group(1).strip().lower()
        else:
            kind = _tex_float_env_after(text[:m.start()], None)
        out.append((kind or "figure", text[i + 1:j]))
    return out


# ---------------------------------------------------------------------------
# Bounded readers and the DOCX part reader (moved from p04_utils.py to keep
# that part under the repository's 10,000-line cap; the loader executes every
# part in one module namespace, so the lower-numbered parts call these at
# runtime exactly as before).
# ---------------------------------------------------------------------------
# Agent-written JSON is untrusted input of unbounded size: a runaway agent can
# write a multi-gigabyte findings.json/scores.json, and json.loads() would either
# exhaust memory (crashing the orchestrator, which is never acceptable) or spend
# minutes on prose scanning in the lenient path. Anything above this cap is
# treated as a malformed agent deliverable, which the retry policy handles.
MAX_JSON_BYTES = 64 * 1024 * 1024


def json_file_too_big(path: Path) -> bool:
    """True when `path` is not a regular file or is larger than MAX_JSON_BYTES.

    `lstat` (not `stat`) and `S_ISREG`: a FIFO reports st_size 0, so the old
    check passed it to `open()`/`read()`, which blocks forever -- an agent could
    hang the orchestrator by replacing findings.json with a FIFO. A symlink is
    refused for the same reason (its target can be a special file).
    """
    try:
        st = path.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return True
    return st.st_size > MAX_JSON_BYTES


# Untrusted DOCX parts: cap the DECOMPRESSED size before reading, and refuse
# an XML DTD outright. A 563-byte part with eight nested internal entities
# expanded to 65,536 characters here, and a ZIP entry's declared size was never
# checked at all (a small compressed entry can allocate gigabytes).
MAX_DOCX_PART_BYTES = 64 * 1024 * 1024


def _docx_xml_part(z: zipfile.ZipFile, name: str):
    """Bytes of one DOCX XML part, or None over the size/DTD budget."""
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


def _docx_paragraphs(path: Path, include_tables: bool = True):
    """Paragraph texts of a .docx, or None when it cannot be parsed.

    `include_tables=False` leaves out every paragraph inside a `w:tbl`: a venue
    whose counting source excludes the CONTENTS of tables (Frontiers) must not
    charge table-cell text to the main-text cap (F08).

    A `w:br`/`w:cr` (a soft line break) and a `w:tab` render as a NEWLINE: the
    text is the text a READER sees, and a caller that compares two written
    forms (FMT-X2's correspondence block) must be able to tell a line break
    from a missing space. Dropping the break made the shipped three-line
    `* Correspondence: / Zhen Xie / zhenxie@…` read as one glued token and
    FMT-X2 reported a line that renders perfectly (the 2026-10-15b neohet
    package, re-found by the operator's audit).
    """
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    mc = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
    try:
        with zipfile.ZipFile(path) as z:
            data = _docx_xml_part(z, "word/document.xml")
        if data is None:
            return None
        root = ET.fromstring(data)
    except (OSError, KeyError, zipfile.BadZipFile, zipfile.LargeZipFile,
            ET.ParseError, RuntimeError, NotImplementedError):
        return None
    table_paras = set()
    if not include_tables:
        # Namespace-agnostic: every w:p under any w:tbl is table CONTENT.
        for tbl in root.iter(ns + "tbl"):
            for para in tbl.iter(ns + "p"):
                table_paras.add(id(para))
    out = []
    for para in _docx_visible_paragraphs(root, ns, mc):
        if not include_tables and id(para) in table_paras:
            continue
        parts = []
        for node in _docx_visible_nodes(para):
            if node.tag in (ns + "br", ns + "cr", ns + "tab"):
                parts.append("\n")
            elif node.tag == ns + "noBreakHyphen":
                # The formatter's `text_of` renders a hyphen here; dropping it
                # fused `ten<w:noBreakHyphen/>year` into "tenyear", so the two
                # extractors of the SAME module disagreed on the same DOCX.
                parts.append("-")
            elif node.tag == ns + "sym":
                parts.append("\ufffd")
            elif node.tag == ns + "t":
                parts.append(node.text or "")
        out.append("".join(parts))
    return out

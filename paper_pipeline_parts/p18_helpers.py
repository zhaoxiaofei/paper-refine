# -*- coding: utf-8 -*-
# Part 18/23 of the pipeline -- executed by the loader AFTER the command
# functions, in the loader's own module globals. These are pure helpers
# (no module-level side effects): the lower-numbered parts call them at
# runtime, so they may live after the CLI definitions. Split out of
# p04_utils.py (and, later, p06_postchecks.py / p07_stage_quality_journal.py)
# to keep every maintained source file under 10,000 lines.
from __future__ import annotations

import html as _html


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
    if out.exists() and not out.is_dir():
        die(f"refusing to use {dirname}/: {out} exists and is not a directory. Remove it "
            f"and re-run.")
    out.mkdir(parents=True, exist_ok=True)
    if out.is_symlink() or not is_within(out, root):
        die(f"refusing to use {dirname}/: it became a symlink or resolves outside --root "
            f"({root}); remove it and re-run.")
    return out


# ---------------------------------------------------------------------------
# Venue profile + M30 seed helpers moved here to keep p04_utils.py under
# the repository's 10,000-line cap; the loader shares one namespace.
# ---------------------------------------------------------------------------

def _style_limit_int(value):
    """A positive int style limit, or None for an invalid entry (F181).

    `int(3.9)` truncates to 3 and `int(True)` is 1, so the old blind conversion
    silently enforced a STRICTER bar than the profile recorded while the
    docstring promised the invalid entry was dropped. Accept only a real
    positive int -- the rule `normalize_venue_profile` applies to a profile's
    `style_limits` block (a bool is not an int here).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


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
            n = _style_limit_int(value)
            if n is None:
                continue
            clean[str(kind)] = n
        if clean:
            out["sentence_words"] = clean
    cap = _style_limit_int(block.get("paragraph_words"))
    if cap is not None:
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
# The last bytes of each agent stream, kept separately from the head above and
# used ONLY for failure classification. A provider error, a guard sentence and
# the CLI's dying words are at the END of the transcript; classifying the head
# made the diagnosis depend on where in a >16 MiB transcript a phrase landed.
EVIDENCE_TAIL_BYTES = 512 * 1024


class ToolOutputOverBudget(Exception):
    """A child process printed more than MAX_TOOL_OUTPUT_BYTES on one stream."""


def _tool_popen_kwargs() -> dict:
    """Run a tool in its OWN process group so a timeout can kill its helpers.

    On POSIX that is `start_new_session`; on Windows the parameter is ignored,
    and the group is created with CREATE_NEW_PROCESS_GROUP so `taskkill /T` can
    reach the children. The siblings (_render_popen_kwargs in p06 and
    _redline_popen_kwargs in p13) already branch this way.
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _kill_process_group(proc):
    """Kill a tool's whole process group, not just the direct child.

    A tool may spawn a helper (a verifier, a converter's worker) that inherits
    the child's process group. `proc.kill()` left those grandchildren running
    after the orchestrator had timed out and moved on (the 2026-10-30 F51).

    `os.killpg` is POSIX-only: on Windows the attribute does not exist. The
    old `except OSError` caught AttributeError too but then fell back to
    `proc.kill()`, which leaves latexmk/bibtex or a verifier's grandchildren
    running. Use the Windows tree-kill the sibling modules already use.
    """
    if os.name == "nt":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (AttributeError, OSError):
            pass
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
            **_tool_popen_kwargs())
        over_budget = threading.Event()

        def _pump(pipe, sink):
            total = 0
            try:
                while True:
                    # Read the raw descriptor: `BufferedReader.read` holds the
                    # buffer lock, and a grandchild that keeps the pipe open
                    # then made the main thread's `pipe.close()` wait on it
                    # forever after the timeout.
                    chunk = os.read(pipe.fileno(), 65536)
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
        except BaseException:
            # Ctrl-C (KeyboardInterrupt) and every other non-timeout exception
            # out of wait() used to abandon the child: it leads its OWN
            # session, so the tool and its grandchildren kept running after the
            # orchestrator stopped (F129). Kill the whole group, reap it, and
            # let the exception propagate.
            _kill_process_group(proc)
            try:
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
            raise
        for t in readers:
            t.join(timeout=10)
        # A grandchild that escaped the group can keep a pipe open; closing our
        # end forces the reader to EOF instead of leaving it blocked forever.
        for t, pipe in zip(readers, (proc.stdout, proc.stderr)):
            if t.is_alive():
                # Never close a pipe a live reader still owns: its close waits
                # on the reader's lock (the hang). The pipe is left to the
                # daemon reader, which exits at EOF or with the process.
                t.join(timeout=2)
                continue
            try:
                pipe.close()
            except OSError:
                pass
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


def safe_mkdir(path) -> Path:
    """Create a pipeline-owned OUTPUT directory without following a link.

    A sandbox is reused across attempts, so a previous attempt can leave
    `sb/revised` (or `sb/guided_review`) as a symlink to an outside directory.
    `mkdir(exist_ok=True)` follows it and the stage's candidate is written
    outside `--root`. Refuse any symlinked component, and a symlink at the
    target itself, BEFORE creating or using the directory (F061).
    """
    path = Path(path)
    try:
        _refuse_symlinked_parent(path / "_")
    except OSError as e:
        die(f"refusing to create output directory {path}: {e}. An output "
            f"directory must be a real directory inside the run sandbox, never a "
            f"link to an outside path")
    if path.is_symlink():
        die(f"refusing to create output directory {path}: it is a symlink (an output "
            f"directory must be a real directory inside the run sandbox)")
    if path.exists() and not path.is_dir():
        die(f"refusing to create output directory {path}: it exists and is not a directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


# A spreadsheet treats a cell beginning with one of these as a FORMULA. The
# reports carry agent-written evidence/check text verbatim, so an untrusted row
# could execute a formula when the operator opens the CSV (F087).
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _csv_safe_cell(value):
    """Neutralise a spreadsheet formula in one CSV cell.

    Only STRINGS are touched: a numeric `-12` is a number, not a formula, and
    prefixing it would turn a real value into text. A string that starts with a
    formula character gets the conventional leading apostrophe.
    """
    if isinstance(value, str) and value[:1] in _CSV_FORMULA_PREFIXES:
        return "'" + value
    return value


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
    except (OSError, ValueError, RuntimeError):
        # Path.resolve() raises RuntimeError for a symlink loop; an
        # unresolvable include must not abort the whole TeX scan (F261).
        return None                     # a path outside the manuscript directory
    return resolved if resolved.is_file() else None


# An include DAG may legitimately repeat a child, so the expansion is not a
# tree walk: a diamond doubles at every level. Cap the work rather than let a
# 25-line manuscript-shaped file expand to tens of megabytes. An include left
# unexpanded is reported by the caller as an unresolved include (a named gap).
TEX_MAX_EXPANDED_CHARS = 8 * 1024 * 1024
TEX_MAX_INCLUDE_EXPANSIONS = 2000
TEX_MAX_INCLUDE_DEPTH = 32


def _tex_expand_includes(text: str, base: Path, seen=None, source: Path = None,
                         _stack=None, _budget=None):
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
    budget = _budget if _budget is not None else {
        "chars": len(body), "expansions": 0}
    if len(stack) >= TEX_MAX_INCLUDE_DEPTH:
        # Too deep: leave this frame's includes as markup. The caller records
        # each one as an unresolved include instead of expanding forever.
        return body
    stack.append(body)

    def repl(match):
        if (budget["expansions"] >= TEX_MAX_INCLUDE_EXPANSIONS
                or budget["chars"] >= TEX_MAX_EXPANDED_CHARS):
            return match.group(0)       # over budget: leave a named gap
        child = _tex_include_path(base, match.group(1))
        if child is None or child in seen:
            return match.group(0)
        seen.add(child)
        # Read AT MOST the remaining budget (+1 to detect an overrun). Reading
        # the child whole and charging its length afterwards allocated a
        # multi-gigabyte \input before the budget check (F171).
        remaining = max(0, TEX_MAX_EXPANDED_CHARS - int(budget["chars"]))
        try:
            with child.open("r", encoding="utf-8", errors="replace") as handle:
                child_text = handle.read(remaining + 1)
        except OSError:
            return match.group(0)
        if len(child_text) > remaining:
            # The include alone exceeds the budget: leave it as a named gap and
            # stop expanding any later include.
            budget["chars"] = TEX_MAX_EXPANDED_CHARS
            return match.group(0)
        if child_text in stack:
            return match.group(0)       # the same source text is already open
        budget["expansions"] += 1
        budget["chars"] += len(child_text)
        try:
            return _tex_expand_includes(child_text, base, seen, source=child,
                                        _stack=stack, _budget=budget)
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
    # A commented-out `% \caption{...}` is not a caption: M19 strips comments
    # from the length scan, so the caption inventory must use the same text.
    text = _blank_tex_verbatim(strip_tex_comment(text or ""))
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


def _visible_docx_part_texts(xml: str) -> list:
    """Paragraph texts of one DOCX XML part as Word RENDERS them.

    `text_of` counts a `w:vanish` run, so a hidden e-mail address looked
    present to the e-mail gate while the visibility-aware content/fact readers
    could not see it (F129). The same visible-node walk the content policy uses
    is applied here.
    """
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    mc = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        # A part that is not well-formed XML has no visible-node walk, and the
        # old tag-strip fallback returned the text of HIDDEN/deleted runs -- a
        # hidden e-mail address became visible to the gate, contrary to this
        # function's "as Word RENDERS them" contract (F182). Word cannot render
        # such a part either: report no visible text rather than raw markup.
        return []
    out = []
    for para in _docx_visible_paragraphs(root, ns, mc):
        parts = []
        for node in _docx_visible_nodes(para):
            if node.tag in (ns + "br", ns + "cr", ns + "tab"):
                parts.append("\n")
            elif node.tag == ns + "noBreakHyphen":
                parts.append("-")
            elif node.tag == ns + "t":
                parts.append(node.text or "")
        text = "".join(parts)
        if text.strip():
            out.append(text)
    return out


# ---------------------------------------------------------------------------
# Rendered reference-list comparison. Moved here from p07 (same shared
# namespace, called at runtime) to keep p07 under the 10,000-line cap.
# ---------------------------------------------------------------------------

_HTML_BLOCK_TAG_RE = re.compile(
    r"(?is)</?(?:address|article|aside|blockquote|br|dd|div|dl|dt|fieldset|"
    r"figcaption|figure|footer|form|h[1-6]|header|hr|li|main|nav|ol|p|pre|"
    r"section|table|tbody|td|tfoot|th|thead|tr|ul)\b[^>]*>")
_HTML_TAG_RE = re.compile(r"(?s)<[^>]+>")


def _html_text_lines(text: str) -> list:
    """Text lines of an HTML document, with block boundaries preserved.

    `.html`/`.htm` was added to the reference-entry surface list but the
    heading/entry regexes need one element per line; a rendered list written as
    `<h1>References</h1><p>[1] ...</p>` produced no entries at all, so a
    fabricated or deleted HTML reference still passed the strict gates (F38).
    Block tags become line breaks, the remaining tags are dropped, and entities
    are decoded so the entry text compares like the other prose surfaces.
    """
    text = _HTML_BLOCK_TAG_RE.sub("\n", str(text or ""))
    text = _HTML_TAG_RE.sub("", text)
    return [_html.unescape(line) for line in text.splitlines()]


_REFERENCE_HEADING_RE = re.compile(
    r"(?i)^\s*(?:#{1,6}\s*)?(?:references?|bibliography|works\s+cited|"
    r"literature\s+cited|cited\s+literature|"
    r"references?\s+(?:and|&)\s+notes|notes\s+(?:and|&)\s+references?)\s*$|"
    r"\\begin\{thebibliography\}|"
    r"\\(?:sub)?section\*?\s*\{\s*(?:references?|bibliography|"
    r"references?\s+(?:and|&)\s+notes)\s*\}")
_REFERENCE_ENTRY_LINE_RE = re.compile(r"^\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\d{1,4}[.)])\s+\S")


def _reference_entries_in_lines(lines, entries: set) -> set:
    """Collect rendered reference entries from an iterable of text lines.

    Shared by the text and DOCX readers so the two surfaces cannot drift: the
    DOCX reference list used to be invisible to this scan while its entries
    were also skipped as content units (F09). `lines` may be plain strings.
    """
    in_refs = False
    for raw in lines:
        stripped = str(raw or "").strip()
        if _REFERENCE_HEADING_RE.search(stripped):
            in_refs = True
            continue
        if in_refs and (re.match(r"(?i)^(?:#{1,6}\s|\\(?:sub)?section)", stripped)
                        or (is_heading_line(stripped)
                            # A reference entry can itself be heading-shaped
                            # ("WHO 2020"); a year means ENTRY, not heading.
                            and not re.search(r"\b(?:18|19|20)\d{2}\b", stripped))):
            # A plain-text/.rst/.html/DOCX heading carries no Markdown `#` or
            # LaTeX `\section` marker, so a following Methods list item was
            # collected as a reference entry and reported as an added/removed
            # reference (F007). `is_heading_line` is the pipeline's heading
            # detector; the DOCX reader additionally prefixes a style-based
            # heading with `# ` (see _reference_entry_keys).
            in_refs = False
            continue
        if not in_refs:
            continue
        m = re.match(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}", stripped)
        if m:
            entries.add(f"key:{m.group(1).strip().lower()}")
            continue
        if stripped and (_REFERENCE_ENTRY_LINE_RE.match(stripped)
                         or (re.search(r"\b(?:18|19|20)\d{2}\b", stripped)
                             and "," in stripped)):
            entries.add(re.sub(r"\s+", " ", stripped).lower())
    return entries


def _reference_entry_keys(package: Path) -> set:
    """Normalised reference-list ENTRIES the submitted package carries.

    Reference entries were stripped before they became content units, so a
    fabricated entry could be added (or a real one deleted) with no
    missing/added unit and no fact loss (F005). The entries are compared as
    text (a .tex `\\bibitem` by its key); a `.bib`/`.bbl` database is not a
    rendered reference-list entry and is deliberately not read here, so adding
    an uncited key to it changes nothing.
    """
    entries = set()
    package = Path(package)
    if not package.is_dir():
        return entries
    _decl, _is_submitted = declared_submission_filter(package)
    for p in _iter_tree_files(package):
        try:
            rel = p.relative_to(package).as_posix()
        except ValueError:
            continue
        if not _is_submitted(rel):
            continue
        top = rel.split("/", 1)[0].lower()
        if top in CORPUS_EXCLUDE_TOP or top in EVIDENCE_DIRNAMES or top == CODE_DIR:
            continue
        if (is_bookkeeping_name(p.name) or _is_aux_doc(p.name)
                or is_non_submitted_readme_name(p.name)
                or is_non_shippable_name(p.name)
                or is_non_manuscript_rel(rel)):
            continue
        ext = p.suffix.lower()
        # Only a RENDERED reference-list entry is a content unit. A .bib/.bbl
        # is a source database: adding an uncited key there does not insert a
        # reference into the manuscript (F31), and a corrected key is covered
        # by the citation-key gate (F02). The SAME prose surfaces the content
        # scan reads (.rst/.html included) are scanned here, and a submitted
        # DOCX is read through the shared visibility-aware paragraph reader:
        # otherwise a new/removed entry in either format is invisible (F09/F38).
        if ext in (".md", ".markdown", ".txt", ".tex", ".ltx", ".rst", ".html", ".htm"):
            text = read_text_bounded(p)
            if text:
                lines = (_html_text_lines(text) if ext in (".html", ".htm")
                         else text.splitlines())
                _reference_entries_in_lines(lines, entries)
        elif ext == ".docx":
            paras = _docx_paragraphs_with_styles(p, include_notes=True)
            if paras:
                # A Word heading carries a STYLE, not a Markdown marker; a
                # numbered/differently spelled style heading would not look
                # like a heading in its text alone. Mark it so the shared scan
                # ends the reference list on it (F007).
                _reference_entries_in_lines(
                    (("# " + line) if _style_id_is_heading(style) else line
                     for line, style in paras), entries)
    return entries


_REFERENCE_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s,;]+", re.I)
_REFERENCE_ARXIV_RE = re.compile(r"\barxiv:\s*(\d{4}\.\d{4,5})", re.I)
_REFERENCE_YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")


def _reference_entry_identity(entry: str) -> tuple:
    """Identity evidence that two rendered reference entries name the SAME work.

    Similarity alone is NOT a correction: "Smith J. ... 2020" and "Brown K. ...
    2020" pair at ratio 0.87, so a fabricated replacement was hidden from the
    added/removed reference gate (F150). Pair only when the entries share a
    DOI/arXiv id, or the same first-author token AND year. A `key:` entry (a
    .tex `\\bibitem`) is identified by the key itself: a changed key is a
    removal + insertion, never an in-place correction.
    """
    text = str(entry or "").strip().lower()
    if not text:
        return ("", None)
    if text.startswith("key:"):
        return ("key", text)
    doi = _REFERENCE_DOI_RE.search(text)
    if doi:
        return ("doi", doi.group(0).rstrip(".,;)]}"))
    arxiv = _REFERENCE_ARXIV_RE.search(text)
    if arxiv:
        return ("arxiv", arxiv.group(1))
    year = _REFERENCE_YEAR_RE.search(text)
    if year is None:
        return ("", None)
    body = re.sub(r"^\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\d{1,4}[.)])\s+", "", text)
    first = re.split(r"[\s,;]+", body, 1)[0]
    if not first:
        return ("", None)
    return ("author-year", (first, year.group(0)))


def _reference_entry_corrections(base_package: Path, candidate_package: Path) -> tuple:
    """(pairs, added, removed) for the reference lists of one package pair.

    A typo fix changes one entry's text; a removed entry is paired with a very
    similar added one (ratio >= 0.80) so an in-place correction is not reported
    as delete+add. Similarity is not sufficient on its own: the pair must also
    carry IDENTITY evidence for the same work (see
    `_reference_entry_identity`), or a fabricated replacement (Smith -> Brown)
    is accepted as a correction and never reaches the gate (F150). The pairs
    are returned because the PROSE comparison must exclude the same correction:
    it used to re-report a corrected entry as a missing+added content unit even
    though this comparator accepted it (F126).
    """
    base = _reference_entry_keys(base_package)
    cand = _reference_entry_keys(candidate_package)
    added, removed = sorted(cand - base), sorted(base - cand)
    pairs = []
    for old in list(removed):
        old_id = _reference_entry_identity(old)
        if not old_id[0]:
            # No identity evidence: a similar-looking new entry must not hide
            # this removal.
            continue
        best, score = None, 0.0
        for new in added:
            if _reference_entry_identity(new) != old_id:
                continue
            ratio = difflib.SequenceMatcher(None, old, new).ratio()
            if ratio > score:
                best, score = new, ratio
        if best is not None and score >= 0.80:
            removed.remove(old)
            added.remove(best)
            pairs.append((old, best))
    return pairs, added, removed


def _reference_entry_changes(base_package: Path, candidate_package: Path) -> tuple:
    """(added, removed) reference entries, treating near-identical text as a fix."""
    _pairs, added, removed = _reference_entry_corrections(
        base_package, candidate_package)
    return added, removed


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
# A per-part cap does not bound the PACKAGE: many legal parts are still
# decompressed together by the readers that materialize every member.
MAX_DOCX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_DOCX_ENTRIES = 4096


def _docx_xml_part(z: zipfile.ZipFile, name: str):
    """Bytes of one DOCX XML part, or None over the size/DTD budget."""
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_DOCX_PART_BYTES:
        return None
    # `file_size` is attacker-controlled central-directory metadata, and
    # `ZipFile.read(name)` (no length) decompresses the WHOLE stream before the
    # CRC check, so a forged small size still expanded without bound (F017).
    # Read through a bounded length and reject the one byte that proves the
    # real part is over budget.
    with z.open(info) as fh:
        data = fh.read(MAX_DOCX_PART_BYTES + 1)
    if len(data) > MAX_DOCX_PART_BYTES:
        return None
    text = data.decode("utf-16", "ignore") if data[:2] in (b"\xff\xfe", b"\xfe\xff") \
        else data.decode("utf-8", "ignore")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    return data


def _docx_paragraphs(path: Path, include_tables: bool = True,
                     include_notes: bool = False):
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
    pairs = _docx_paragraphs_with_styles(path, include_tables=include_tables,
                                          include_notes=include_notes)
    return None if pairs is None else [text for text, _style in pairs]


def _docx_paragraphs_with_styles(path: Path, include_tables: bool = True,
                                 include_notes: bool = False):
    """[(paragraph text, paragraph style id)] of a .docx, or None.

    The style id is the LIVE `w:pPr/w:pStyle` value ("" when the paragraph sets
    none). A Word style heading (`Heading1`, `Title`, ...) carries no Markdown
    `#` marker, so a text-only reader cannot tell it from prose: the content
    policy treated a style-based heading as a content unit and reported a
    heading edit as added/removed prose (F70). Style ids are matched by the
    codebase's existing `Heading*` convention (see `corpus_text_documents`).
    """
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    mc = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
    try:
        with zipfile.ZipFile(path) as z:
            # A per-part cap does not bound the PACKAGE: a small DOCX with
            # thousands of compressible header parts (or parts that together
            # declare hundreds of MiB) forced the whole decompression on every
            # scan. Charge the entry count and the DECLARED decompressed total
            # before reading anything (F132).
            infos = z.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                return None
            if sum(info.file_size for info in infos) > MAX_DOCX_TOTAL_BYTES:
                return None
            data = _docx_xml_part(z, "word/document.xml")
            note_data = []
            if include_notes:
                _hf_names = [n for n in z.namelist()
                             if re.match(r"word/(?:header|footer)[A-Za-z0-9_\-]*\.xml$", n)]
                note_data = [_docx_xml_part(z, name) for name in
                             ("word/footnotes.xml", "word/endnotes.xml")]
                # F202: header/footer prose was invisible to the content and fact
                # gates; read the parts too (the visible-paragraph walker skips
                # Fallback branches). Only when the caller asked for notes:
                # materializing and parsing them for a body-only read was pure
                # decompression surface (F132).
                note_data += [_docx_xml_part(z, name) for name in _hf_names]
        if data is None:
            return None
        root = ET.fromstring(data)
        note_roots = []
        for nd in note_data:
            if nd is None:
                continue
            try:
                note_roots.append(ET.fromstring(nd))
            except ET.ParseError:
                # A malformed footnotes/endnotes/header part must make the
                # WHOLE read fail closed: silently dropping it hid a deleted
                # footnote fact from every content/fact gate (F154). The
                # caller treats None as an unscannable submitted file.
                return None
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

    def _paragraph_pairs(container) -> list:
        pairs = []
        for para in _docx_visible_paragraphs(container, ns, mc):
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
            ppr = para.find(ns + "pPr")
            style_el = ppr.find(ns + "pStyle") if ppr is not None else None
            style = (style_el.get(ns + "val") or "") if style_el is not None else ""
            pairs.append(("".join(parts), style))
        return pairs

    out = _paragraph_pairs(root)
    # Footnotes/endnotes are manuscript text a reader sees; reading only
    # word/document.xml made footnote-only facts invisible and reported a body
    # sentence moved into a footnote as a deletion (F193).
    if not include_notes:
        return out
    for note_root in note_roots:
        # A header/footer root's children ARE the visible paragraphs (w:hdr /
        # w:ftr); feeding it through the footnote record filter skipped every
        # one of them, so the F202 addition changed nothing observable.
        if note_root.tag in (ns + "hdr", ns + "ftr"):
            out.extend(_paragraph_pairs(note_root))
            continue
        for note in list(note_root):
            if note.tag not in (ns + "footnote", ns + "endnote"):
                continue
            if str(note.get(ns + "type") or "").lower() in (
                    "separator", "continuationseparator", "continuationnotice"):
                continue
            out.extend(_paragraph_pairs(note))
    return out


def _declaration_readme_from_author(root: Path, p: Path) -> bool:
    """Whether `p`'s submission declaration comes from the AUTHOR's copy.

    The package README is agent-writable, so a session could add
    `README.md` saying "only `cover*` will be submitted": the publisher then
    dropped the main manuscript from the journal submission, and the content and
    format gates skipped it too (F23). A declaration is honoured only when the
    README is byte-identical to the copy the author supplied in
    `non_revised/` (or the stage's own read-only `base/`/`self/` copy). A
    README the session created or changed does not narrow the submitted set.
    Outside a run root (a unit fixture, or the pristine corpus itself) there is
    no agent-session context, so the declaration stands.
    """
    root = Path(root)
    run_root = _enclosing_run_root(root)
    if run_root is None:
        return True
    pristine = run_root / PRISTINE_DIR
    for anchor_root in (pristine,):
        try:
            root.resolve().relative_to(anchor_root.resolve())
            return True                      # we ARE the author's corpus copy
        except (ValueError, OSError):
            pass
    try:
        rel = p.relative_to(root)
        digest = sha256_file(p)
    except (OSError, ValueError):
        return False
    for anchor in (pristine / rel, root.parent / "base" / rel,
                   root.parent / "self" / rel):
        try:
            if anchor.is_file() and not anchor.is_symlink() \
                    and sha256_file(anchor) == digest:
                return True
        except OSError:
            continue
    return False


class _DocumentTexts(list):
    """[(rel, [paragraph, ...], full_text)] plus the inputs that could not read.

    The list carries the scan payload; `gaps` carries one line per submitted
    document the shared reader could NOT parse. Returning the payload alone
    made "could not parse the submitted document" indistinguishable from "the
    document has no matching statement", so the package looked clean (F14).
    """

    def __init__(self, items=(), gaps=()):
        super().__init__(items)
        self.gaps = list(gaps)


def _document_read_gap_rows(docs, rule: str = "PKG-17..25", limit: int = 20) -> list:
    """The named coverage gap for documents the shared reader could not parse."""
    gaps = list(getattr(docs, "gaps", None) or ())
    if not gaps:
        return []
    return _with_table_gaps([], gaps, rule, limit)


def _with_table_gaps(rows: list, gaps: list, rule: str, limit: int) -> list:
    """Prepend the scan's named coverage gap (when any) to its rows."""
    if not gaps:
        return rows[:limit]
    gap_files = []
    for g in gaps:
        name = str(g).split(":", 1)[0].strip()
        if name and name not in gap_files:
            gap_files.append(name)
    gap = {
        "rule": rule, "severity": "low", "fix": "none", "file": "", "line": 0,
        "reference": "", "gap": True, "advisory": True,
        # A gap that names exactly one unreadable input is attributable to that
        # document, so a consumer that reports findings by `document` does not
        # lose it (F14/R04). Several unreadable inputs stay in `detail`.
        "document": gap_files[0] if len(gap_files) == 1 else None,
        "detail": (f"{rule} was NOT evaluated on {len(gaps)} input(s): "
                   + "; ".join(gaps[:6]) + (" ..." if len(gaps) > 6 else "")
                   + ". Examine them by hand; a defect there would not appear in this list"),
    }
    return [gap] + rows[:max(0, limit - 1)]


# =====================================================================
# `--only`: the ROUND/STAGE/SESSION selection grammar
#
# Moved here from p04_utils.py, which is capped at 10,000 lines by the
# source-layout contract. The grammar resolves a `--only`/`--runs` item into
# rounds, stage classes and session tokens; `ONLY_STAGES`, `ONLY_ALIASES` and
# `ONLY_STAGE_GROUPS` (p02) are read at CALL time, so the split is invisible.
# =====================================================================

ONLY_ROUND_RANGE_CAP = 64


def parse_only_rounds(text: str, item: str, flag: str = "--only") -> set:
    """Parse the round side of an `--only` item: "2", "1-3" or "1,2,4" -> set.

    `text` is the raw (un-normalized) round side, `item` the whole item for the
    error message. Round ordinals are 1-based and are range-checked against the
    pipeline's `--rounds` later, when the config is known.
    """
    rounds = set()
    for chunk in re.split(r"[,\s]+", text.strip()):
        if not chunk:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", chunk)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo < 1 or hi < 1:
                die(f"{flag}: round ordinals are 1-based, got {item!r}", code=2)
            if hi < lo:
                die(f"{flag}: empty round range {chunk!r} in {item!r}", code=2)
            # Refuse an implausible span HERE: `1-999999999` used to expand
            # into a billion-element set -- the process died (MemoryError, no
            # message) long before `validate` could range-check it against the
            # configured round count.
            if hi - lo + 1 > ONLY_ROUND_RANGE_CAP:
                die(f"{flag}: round range {chunk!r} in {item!r} names "
                    f"{hi - lo + 1} rounds; the pipeline's round count is a handful "
                    f"(rounds are 1-based)", code=2)
            rounds.update(range(lo, hi + 1))
            continue
        if not chunk.isdigit():
            die(f"{flag}: {chunk!r} in {item!r} is not a round ordinal (1, 2, ... "
                f"or a range like 1-3)", code=2)
        if int(chunk) < 1:
            die(f"{flag}: round ordinals are 1-based, got {item!r}", code=2)
        rounds.add(int(chunk))
    if not rounds:
        die(f"{flag}: {item!r} names no round", code=2)
    return rounds


def parse_only_stages_for(token: str, item: str, flag: str = "--only") -> tuple:
    """Resolve one stage name/alias to the stages it names, or die.

    The result is a TUPLE because one token can name a STEP: `review` selects the
    guided review and the cold-start review together (see ONLY_STAGE_GROUPS),
    while each stage's own name selects only that stage.
    """
    name = ONLY_ALIASES.get(token, token)
    if name in ONLY_STAGE_GROUPS:
        return ONLY_STAGE_GROUPS[name]
    if name not in ONLY_STAGES:
        die(f"{flag}: unknown stage {item!r}; choose from {', '.join(ONLY_STAGES)} "
            f"(aliases: review=guided_review+cold_start_review, merge=integrate, "
            f"w=rewrite, a/a2=revise, j=judge, fb=feedback, resp=response)", code=2)
    return (name,)


def plan_stage_of(entry: dict) -> str:
    """The bare stage name of a round-plan entry.

    `round_run_plan` labels entries with their plan position ("revise 1/1",
    "integrate 2/2", "rewrite 1/2", "guided_review"); `--only` filters on the bare
    name, so map the label back to it.
    """
    return str((entry or {}).get("stage") or "").strip().lower().split(" ")[0]


class OnlySpec:
    """The parsed `run --only` selection: which ROUNDS and which STAGES run.

    Every accepted item selects something, and the items are a UNION:

        1,2          rounds 1 and 2 in full (every stage of those rounds)
        1-3          rounds 1..3 in full
        review       the review STEP of every round: the guided AND the
                     cold-start review (see ONLY_STAGE_GROUPS)
        2:review     round 2's review step only (`2.review`, `2/review` work too)
        cold_start_review
                     only that stage, in every round
        1,3:merge    round 1 in full and round 3's integrate (a bare ordinal
                     runs a whole round; `ROUND:STAGE` runs only that stage)
        all          everything (the default)

    Items on the right of a `:` are stage names (or `all`); items without a
    `:` are either a round ordinal (with optional ranges/lists) or a stage name.
    A round named by a bare ordinal runs ALL its stages; a round named only by
    `ROUND:STAGE` items runs only those stages. `parse_only_spec` rejects an
    out-of-range round only when the pipeline's round count is known -- see
    validate().
    """

    def __init__(self):
        self.rounds = set()      # rounds named by any item
        # rounds named by a BARE ordinal (`--only 1`, `--only 1-3`): a round in
        # FULL, every step of its DAG including the judge step's downstream
        # (the round decision). A round that appears in `rounds` only because a
        # session item resolved to it is NOT in here.
        self.rounds_in_full = set()
        self.pairs = {}          # round -> set of stages (empty set = all stages)
        self.stages = set()      # stages named without a round (all rounds)
        self.all_stages = False  # an `all`/`everything`/`*` item was given
        # round (or None = every round that has it) -> [session tokens], from
        # `r1_w2`, `rewriter1`, `integrator2`, `r2_a2`, ...: WHICH producing
        # session runs (a whitelist; see entry_selected(), which run_round_runs
        # and drive_round read).
        self.sessions = {}
        # round (or None = every round that has it) -> [judge-session selectors]
        # from `r1_judge_w2_j1`, `2:judge_i1_j1`, `w2_j1`, `judge1`: WHICH judge
        # sessions run (see judge_spec_for(), which expands them through
        # judges_enabled_spec/parse_judges_enabled).
        self.judge_selectors = {}
        # [(run id, item as typed)] for a judge RUN ID (`judge_<token>_j<k>`, the
        # id `agents` prints). The token is salted and round-free, so these are
        # resolved against the root's plan by resolve_judge_run_ids() (which needs
        # a Ctx) and then folded into judge_selectors.
        self.judge_run_ids = []
        self.raw = ""            # the item text as typed, for the run log

    def validate(self, rounds_count: int, flag: str = "--only") -> "OnlySpec":
        """Reject round ordinals the pipeline does not have."""
        R = max(1, int(rounds_count))
        unknown = sorted(r for r in self.rounds if r > R or r < 1)
        if unknown:
            die(f"{flag}: round(s) {', '.join(str(r) for r in unknown)} do not exist: this "
                f"pipeline is configured with --rounds {R} (rounds are 1-based)", code=2)
        return self

    def covers_round(self, r: int) -> bool:
        """Can this selection touch round `r` at all (the run loop's round filter)?

        The items are a UNION, so a ROUNDLESS item (a stage name, or a session
        without a round) keeps every round in play even when another item named
        only some rounds: `--only review,2:judge` is round 1's review plus round
        2's review and judge, not "round 2 only".
        """
        if self.all_stages or not self.rounds or int(r) in self.rounds:
            return True
        return bool(self.stages or self.sessions.get(None)
                    or self.judge_selectors.get(None))

    def is_everything(self) -> bool:
        """True when the selection restricts nothing (so `run` behaves as a
        plain `run` and prints no `--only` notes)."""
        return bool(self.all_stages) or (not self.rounds and not self.pairs
                                         and not self.stages and not self.sessions
                                         and not self.judge_selectors
                                         and not self.judge_run_ids)

    def session_tokens_for(self, r: int) -> list:
        """The session tokens this invocation gives round `r` (roundless + its own)."""
        return list(self.sessions.get(None) or []) + list(self.sessions.get(int(r)) or [])

    def judge_spec_for(self, r: int) -> str:
        """The judge-session selector this invocation gives round `r` ("" = none).

        Roundless items (`w2_j1`) apply to every round; a round that has no such
        version simply expands to nothing (see parse_judges_enabled). A
        round-qualified item keeps its round in the selector (`r1_w2_j1`), so the
        expansion is scoped to THAT round even when the rounds have different
        `--judges` counts.
        """
        items = self.judge_selectors
        toks = [str(t) for t in (items.get(None) or [])] \
            + [f"r{int(r)}_{t}" for t in (items.get(int(r)) or [])]
        return ",".join(toks) if toks else ""

    def classes_for(self, r: int) -> set:
        """The stage CLASSES selected in full for round `r` (empty = none named).

        A judge selector counts as the judge class here: it selects the judge
        wave of the round (with a whitelist), never the producing sessions.
        """
        if self.all_stages:
            return set()
        out = set(self.stages) | set(self.pairs.get(int(r)) or ())
        if self.judge_selectors.get(None) or self.judge_selectors.get(int(r)):
            out.add("judge")
        return out

    def judge_class_named(self, r: int) -> bool:
        """Was the WHOLE judge stage named for round `r` (`judge`, `2:judge`, `all`)?

        A judge SESSION selector (`r1_judge_w2_j1`, `w2_j1`) is not the class: it
        asks for a smaller panel and must never clear one recorded earlier.
        """
        if self.all_stages:
            return True
        return "judge" in (set(self.stages) | set(self.pairs.get(int(r)) or ()))

    def judge_step_in_full(self, r: int) -> bool:
        """Was the WHOLE judge STEP asked for in round `r` (panel AND its downstream)?

        The round's DAG has steps, and the judge step's downstream is the round
        DECISION (select the champion, pin it) and, through that pin, the next
        round. `--only` runs the steps the operator asked for and stops there:

          * `all`, a bare round in full (`--only 1`, `1:all`) and the judge stage
            class (`judge`, `2:judge`) select the whole step -- its panel is the
            CONFIGURED panel (`round_judges` per version) and the decision may run
            once that panel is complete;
          * a judge SESSION selector (`r1_judge_w2_j1`, `judge1`, `w2_j1`, a
            version without an index) runs exactly those sessions and NOTHING
            downstream: no winner is selected, nothing is pinned and the next
            round is not entered, even if the sessions it ran happen to complete
            the panel. A later `--only judge` (or a plain `run`) finishes the
            panel and decides.
        """
        if self.all_stages:
            return True
        if "judge" in (set(self.stages) | set(self.pairs.get(int(r)) or ())):
            return True
        if int(r) in self.rounds_in_full:
            return True
        # `2:all` names every stage of round 2 without listing a stage
        return int(r) in self.pairs and not self.pairs[int(r)]

    @staticmethod
    def _token_stage(tok: str) -> str:
        """The stage a session token belongs to (`w2` -> rewrite, `a2` -> revise...)."""
        vid = str(tok)
        if vid in ("guided_review", "guided_review_b", "review", "review_b"):
            return "guided_review"
        # Exact stage names win over the single-letter prefixes below: "audit"
        # must not be read as "a" (revise), and the journal chain's stages are
        # their own classes.
        if vid == "cold_start_review":
            return "cold_start_review"
        if vid in ("audit", "feedback", "concerns", "response"):
            return vid
        if vid == "conform":
            return "conform"
        if vid.startswith("w"):
            return "rewrite"
        if vid.startswith("a"):
            return "revise"
        if vid.startswith("i"):
            return "integrate"
        return "guided_review"

    def stage_selected(self, r: int, stage: str) -> bool:
        """Is `stage` selected in round `r` (as a class, or through a session)?

        The historical convention applies: when NOTHING restricts round `r` (no
        class item and no session item names it), the round runs in full.
        """
        if self.all_stages:
            return True
        classes = self.classes_for(r)
        if stage in classes:
            return True
        tokens = self.session_tokens_for(r)
        if any(self._token_stage(tok) == stage for tok in tokens):
            return True
        return not classes and not tokens

    def entry_selected(self, r: int, entry: dict) -> bool:
        """Is one round-plan entry selected by this `--only` spec?

        The rules, in order: an `all` item selects everything; a stage CLASS item
        selects every session of that stage; a session token selects exactly its own
        session. When no session token applies to this round, a round named without
        any stage runs all of its stages (the historical behaviour).
        """
        if self.all_stages:
            return True
        stage = plan_stage_of(entry)
        tokens = self.session_tokens_for(r)
        if tokens:
            if session_id_of_entry(entry) in tokens:
                return True
            return stage in self.classes_for(r)
        classes = self.classes_for(r)
        return (stage in classes) if classes else True

    def selects_round(self, ctx: "Ctx", r: int) -> bool:
        """Does ANY session of round `r` run under this selection?

        A roundless item (`w2`) applies to every round that has it, so a round
        whose plan never mentions the session is not "incomplete": it is simply
        untouched by this invocation (see _cmd_run_locked's round loop).
        """
        if self.all_stages or self.stage_selected(r, "judge"):
            return True
        return any(self.entry_selected(r, e) for e in round_run_plan(ctx, r))

    def stages_for(self, r: int) -> set:
        """The stage names selected in round `r`; an empty set means every stage."""
        if self.all_stages:
            return set()
        allowed = set(self.stages) | set(self.pairs.get(int(r)) or ())
        return allowed

    def stage_filter(self) -> set:
        """The stage filter when it is the same for every round, else an empty
        set (= every stage, the filter is per-round -- see stages_for())."""
        if self.pairs or self.all_stages:
            return set()
        return set(self.stages)

    def label(self) -> str:
        """The selection as the operator typed it (`--only` text), for the log."""
        return self.raw or self.describe()

    def describe(self) -> str:
        """A one-line human description of the selection (for the run log)."""
        if self.is_everything():
            return "all rounds, all stages"
        bits = []
        bare = sorted(r for r in self.rounds
                      if r not in self.pairs and not self.sessions.get(r)
                      and not self.judge_selectors.get(r))
        if bare:
            bits.append("round(s) " + ",".join(str(r) for r in bare) + " in full")
        if self.stages:
            bits.append("stage(s) " + ",".join(sorted(self.stages)) + " in every round")
        for r in sorted(self.pairs):
            st = ",".join(sorted(self.pairs[r])) if self.pairs[r] else "all stages"
            sel = self.session_tokens_for(r)
            bits.append(f"round {r}: {st}" + (f" (sessions: {','.join(sel)})" if sel else ""))
        for r in sorted(k for k in self.sessions if k is not None and k not in self.pairs):
            bits.append(f"round {r}: session(s) " + ",".join(self.sessions[r]))
        for r in sorted(k for k in self.judge_selectors if k is not None):
            bits.append(f"round {r}: judge session(s) " + ",".join(self.judge_selectors[r]))
        if self.sessions.get(None):
            bits.append("session(s) " + ",".join(self.sessions[None])
                        + " in every round that has them")
        if self.judge_selectors.get(None):
            bits.append("judge session(s) " + ",".join(self.judge_selectors[None])
                        + " in every round that has them")
        for tok, _part in self.judge_run_ids:
            bits.append(f"judge run id {tok}")
        return " | ".join(bits) if bits else "all rounds, all stages"

    def __bool__(self) -> bool:
        return bool(self.rounds or self.pairs or self.stages or self.all_stages
                    or self.sessions or self.judge_selectors or self.judge_run_ids)


def parse_only_spec(raw, flag: str = "--only") -> OnlySpec:
    """Parse `run --only` into an OnlySpec (None/empty/`all` = everything).

    Round ordinals and stage names combine as described on OnlySpec. Accepted
    stage names are rewrite, review, audit, revise, integrate and judge, plus the
    aliases people use in the round plan (w, a/a2, i, merge, j) and the plural
    spellings. A single AGENT session can be named instead of a whole stage:
    `rewriter1`, `reviser1` (the a2 arm), `integrator2`, `w2`, `r1_w2`, `2:w2`,
    `reviewer`, `audit`; a judge session adds either the `judge` keyword
    (`r1_judge_w2_j1`) or a `_j<k>` suffix (`w2_j1`), and `judge1`/`j1` is judge
    index 1 of every version.
    """
    if raw is None:
        return None
    if isinstance(raw, (list, tuple, set)):
        text = ", ".join(str(x) for x in raw)
        parts = [str(x) for x in raw]
        raw_text = text
        had_selection_text = bool(text)
    else:
        raw_text = str(raw)
        text = raw_text.strip()
        parts = re.split(r"[,\s]+", text)
        had_selection_text = bool(raw_text)
    spec = OnlySpec()
    spec.raw = text
    for part in parts:
        token = part.strip().lower()
        if not token:
            continue
        if token in ("all", "everything", "*"):
            spec.all_stages = True
            continue
        # `r1_judge_w2_j1` / `1_judge_w2` / `r1:judge:w2:j1`: WHICH judge sessions
        # of one round run (see OnlySpec.judge_selectors).
        sel = re.fullmatch(r"r?(\d+)\s*[_:/.-]\s*judge\s*[_:/.-]\s*(.+)", token)
        if sel:
            _add_judge_selector(spec, int(sel.group(1)), sel.group(2), part, flag)
            continue
        # `r1_judge1` / `1_judge2`: judge index k of every version of one round.
        sel = re.fullmatch(r"r?(\d+)\s*[_:/.-]\s*judge\s*(\d+)\s*$", token)
        if sel:
            _add_judge_selector(spec, int(sel.group(1)), f"j{int(sel.group(2))}", part, flag)
            continue
        # `r2_r1_w2` / `r2_r1_w2_j1`: a PIN id as the version of one round's
        # judge panel (the inherited base of round 2). `judge_item_parts()`
        # already reads this spelling; the parser used to reject it as an
        # unknown stage, so the documented selector could not reach a run.
        sel = re.fullmatch(r"r(\d+)\s*[_:/.-]\s*(r\d+[_:/.-](?:w\d+|a\d+|i\d+))"
                           r"((?:[_:/.-]j\d+)?)", token)
        if sel:
            _add_judge_selector(spec, int(sel.group(1)), sel.group(2) + sel.group(3),
                                part, flag)
            continue
        # `r1_w2` / `r1_guided_review` / `r1_audit`: ONE session of one round (a
        # `_j<k>` tail makes it a judge session); the old spellings still work.
        sel = re.fullmatch(r"r(\d+)\s*[_:/.-]\s*(w\d+|a\d+|i\d+|guided_review|"
                           r"cold_start_review|audit|feedback|concerns|response|"
                           r"rewriter\d+|reviser\d+|integrator\d+|reviewer|reviewer_b|"
                           r"review_b)((?:[_:/.-](?:b|j\d+))?)",
                           token)
        if sel:
            session = sel.group(2) + sel.group(3)
            if re.fullmatch(r"[_:/.-]j\d+", sel.group(3)):
                _add_judge_selector(spec, int(sel.group(1)), session, part, flag)
            elif re.fullmatch(r"a\d+", session):
                # `r1_a2` names the round's a2 ARM (the id the round plan and
                # `agents` use), while `r1_reviser2` keeps the friendly count.
                _add_session_id(spec, int(sel.group(1)), session, part, flag)
            else:
                _add_session_token(spec, int(sel.group(1)), session, part, flag)
            continue
        # `r1_a2_revise`: the exact RUN ID `agents` prints for a revise arm (the
        # others -- `r1_w1`, `r1_i1`, `r1_guided_review`, `r1_audit` -- are already
        # session ids, so only the revise arm needs the suffix).
        sel = re.fullmatch(r"r(\d+)\s*[_:/.-]\s*(a\d+)[_:/.-]revise", token)
        if sel:
            _add_session_id(spec, int(sel.group(1)), sel.group(2), part, flag)
            continue
        m = re.fullmatch(r"([0-9][0-9,\-\s]*)\s*[:/.]\s*(.+?)\s*", token)
        if m and re.match(r"^\s*\d", m.group(1)):
            # `ROUND[:.]STAGE` (or `ROUND:all`): a per-round stage selection; the
            # stage side may itself name one session (`2:w2`, `2:rewriter1`) or
            # carry judge sessions (`2:judge_i1_j1`, `2:judge1`).
            rounds = parse_only_rounds(m.group(1), part, flag)
            stage_token = m.group(2).strip()
            st = re.fullmatch(r"judge\s*[_:/.-]\s*(.+)", stage_token)
            if st:
                for r in rounds:
                    _add_judge_selector(spec, r, st.group(1), part, flag)
                continue
            if stage_token in ("all", "everything", "*"):
                stages = set()
            elif stage_token in ONLY_ALIASES or stage_token in ONLY_STAGES:
                # A stage name always wins over a session spelling: `2:a2` stays
                # round 2's revise stage (the documented `a`/`a2` alias).
                stages = set(parse_only_stages_for(stage_token, part, flag))
            elif re.fullmatch(r"(?:judge|j)\d+", stage_token):       # `2:judge1`
                for r in rounds:
                    _add_judge_selector(spec, r, stage_token, part, flag)
                continue
            elif re.fullmatch(r"(?:w\d+|a\d+|i\d+|rewriter\d+|reviser\d+|revise\d+|"
                              r"integrator\d+|integrate\d+|reviewer|reviewer_b|review_b)"
                              r"(?:[_:/.-]j\d+)?", stage_token):
                is_judge = re.fullmatch(r".+?[_:/.-]j\d+", stage_token)
                is_arm = re.fullmatch(r"a\d+", stage_token)     # `2:a3` = the a3 ARM
                for r in rounds:
                    if is_judge:
                        _add_judge_selector(spec, r, stage_token, part, flag)
                    elif is_arm:
                        _add_session_id(spec, r, stage_token, part, flag)
                    else:
                        _add_session_token(spec, r, stage_token, part, flag)
                continue
            else:
                stages = set(parse_only_stages_for(stage_token, part, flag))
            spec.rounds |= rounds
            for r in rounds:
                spec.pairs.setdefault(r, set()).update(stages)
            continue
        if re.fullmatch(r"[0-9][0-9,\-\s]*", token):
            bare = parse_only_rounds(token, part, flag)
            spec.rounds |= bare
            spec.rounds_in_full |= bare      # a round in FULL (every step of its DAG)
            continue
        # `judge1` / `j1` / `judge_1`: judge index 1 of every version of every
        # round that has it.
        if re.fullmatch(r"(?:judge|j)[_:/.-]?\d+", token):
            _add_judge_selector(spec, None, token, part, flag)
            continue
        # The exact RUN ID `agents` prints for a judge session
        # (`judge_t497f106d_j1`): the token is salted and carries no round by
        # design, so the round/version it names is resolved against this root's
        # plan right after parsing (see resolve_judge_run_ids()).
        if re.fullmatch(r"judge_[0-9a-z]+(?:_j\d+)?", token):
            _add_judge_run_id(spec, token, part)
            continue
        # `w2_j1` / `i1_j2` / `a2_j1` / `orig_j2`: a judge session named WITHOUT a
        # round applies to every round that has that version.
        if re.fullmatch(r"(?:a\d+|w\d+|i\d+|orig)[_:/.-]j\d+", token):
            _add_judge_selector(spec, None, token, part, flag)
            continue
        # `w2` / `rewriter2` / `integrator1` / `reviser1` / `reviewer`: ONE
        # producing session, in every round that has it. `a2` alone stays the
        # documented revise ALIAS (the stage branch below), so the un-suffixed
        # revise spelling must be `reviser1`. The guided review's own session
        # tokens are accepted in BOTH spellings -- the canonical
        # `guided_review`/`guided_review_b` and the pre-rename
        # `review`/`review_b` -- because a bare `guided_review` is also a
        # legitimate STAGE name, and the stage branch below handles that one.
        if re.fullmatch(r"(?:w\d+|i\d+|rewriter\d+|writer\d+|reviser\d+|revise\d+|"
                        r"integrator\d+|integrate\d+|reviewer|review_b|guided_review_b)",
                        token):
            _add_session_token(spec, None, token, part, flag)
            continue
        spec.stages.update(parse_only_stages_for(token, part, flag))
    if not spec and had_selection_text:
        # A non-empty selection that consumed no token (',', ' ', ',,'): the
        # caller treats a falsy spec as "no selection" and used to run the
        # WHOLE pipeline from a typo or an empty shell expansion (F131). Only
        # an absent/empty flag means everything.
        die(f"{flag}: {raw_text!r} names no round or stage", code=2)
    return spec if spec else None


def _add_judge_selector(spec: "OnlySpec", r, session: str, part: str,
                        flag: str = "--only") -> None:
    """Record one JUDGE-session selector on an OnlySpec (`r` None = every round).

    The round's judge stage is implied (the selector is a WHITELIST of its
    sessions), and the round filter picks up a round-qualified item so
    `--only r1_judge_w2_j1` never looks at the other rounds.
    """
    if r is not None and int(r) < 1:
        die(f"{flag}: {part!r} names round {r}; rounds are 1-based", code=2)
    sel = _judge_selector_token(session, part, flag)
    if r is not None:
        spec.rounds.add(int(r))
    spec.judge_selectors.setdefault(None if r is None else int(r), []).append(sel)


def _add_judge_run_id(spec: "OnlySpec", run_id: str, part: str) -> None:
    """Record a judge RUN ID (`judge_<token>_j<k>`, the id `agents` prints).

    The token is the salted per-version token, so it names a (round, version,
    judge index) only together with the root's plan and salt: the pair stays
    pending here and is resolved by resolve_judge_run_ids() once a Ctx exists.
    """
    spec.judge_run_ids.append((str(run_id), part))


def resolve_judge_run_ids(ctx: Ctx, only, label: str = "[run]", sink=None,
                          flag: str = "--only") -> None:
    """Turn `--only judge_<token>_j<k>` items into the selectors they name.

    `agents` prints each judge session as its run id, and the token in it is
    salted and round-free ON PURPOSE (a judge's sandbox must not reveal which
    version or round it scores). Resolving it costs one sha256 per (round,
    version) of the plan -- no document hash -- so the printed id can be fed
    straight back into `--only`. With `sink` (a list) the resolution notes are
    collected instead of printed, so `agents --json` stays parseable.
    """
    if only is None or not getattr(only, "judge_run_ids", None):
        return
    index = {}
    for r in range(1, ctx.rounds_count() + 1):
        for vid in judgeable_ids(ctx, r):
            key = judge_token_for(ctx, r, vid)
            if key not in index:
                index[key] = (int(r), str(vid))
    for tok, part in list(only.judge_run_ids):
        m = re.fullmatch(r"judge_([0-9a-z]+?)(?:_j(\d+))?", str(tok))
        hit = index.get(m.group(1)) if m else None
        if hit is None:
            die(f"{flag}: {part!r} is not a judge session of this root. The ids `agents` prints "
                f"are accepted (e.g. `judge_{JUDGE_TOKEN_PREFIX}1a2b3c4d_j1`); run `agents --root "
                f"{ctx.root}` to see the ones that exist here.", code=2)
        r, vid = hit
        # the round stays in the KEY: judge_spec_for() re-adds `r<round>_` to a
        # round-qualified token, so the token itself carries only the version
        sel = f"{vid}" + (f"_j{m.group(2)}" if m.group(2) else "")
        only.judge_selectors.setdefault(r, []).append(sel)
        only.rounds.add(int(r))
        line = (f"{label} {flag} {part!r}: judge run id -> round {r}, version {vid}"
                + (f", judge {m.group(2)}" if m.group(2) else " (that version's whole panel)"))
        if sink is None:
            print(line)
        else:
            sink.append(line)
    only.judge_run_ids = []


def _add_session_token(spec: "OnlySpec", r, session: str, part: str,
                       flag: str = "--only") -> None:
    """Record one session selector on an OnlySpec (`r` None = every round that has it).

    A token is a producing session's id (`w2`, `a2`, `i1`, `review`, `review_b`,
    `audit`); the stage class it belongs to is implied (see
    `OnlySpec._token_stage`).
    """
    if r is not None and int(r) < 1:
        die(f"{flag}: {part!r} names round {r}; rounds are 1-based", code=2)
    session = _session_token(session, part, flag)
    if r is not None:
        spec.rounds.add(int(r))
    spec.sessions.setdefault(None if r is None else int(r), []).append(session)


def _add_session_id(spec: "OnlySpec", r, session_id: str, part: str,
                    flag: str = "--only") -> None:
    """Record one session by its EXACT pipeline id (`a2`, `w1`, `i3`, `review`...).

    This is the spelling the round plan, the run ids and `agents` use, so nothing
    is re-indexed here: `a2` is the a2 ARM (the friendly "reviser 2" spelling,
    which maps onto a3, goes through _session_token() instead).
    """
    sid = str(session_id).strip("_:/.-").lower()
    if sid == "a1":
        die(f"{flag}: {part!r} names a1, the round base COPY -- it has no agent session "
            f"(use `reviser1` for the first reviser, which edits a1 into a2)", code=2)
    if not re.fullmatch(r"(?:w\d+|a\d+|i\d+|guided_review|guided_review_b|"
                        r"cold_start_review|audit|feedback|concerns|response)", sid):
        die(f"{flag}: {part!r} is not a session this pipeline knows (use a stage name, or a "
            f"session such as `rewriter1`, `reviser1`, `integrator1`, `review`, `audit`, `w2`, "
            f"`w2_j1`, `r1_w2`, `r1_judge_w2_j1`)", code=2)
    if r is not None:
        spec.rounds.add(int(r))
    spec.sessions.setdefault(None if r is None else int(r), []).append(sid)


def _judge_selector_token(raw: str, part: str, flag: str = "--only") -> str:
    """Normalize one JUDGE-session selector (`integrator2_j1` -> `i2_j1`).

    `judge1`/`j1` is judge index 1 of every version; a version id without an
    index (`w2`, `i1`) is every judge session of that version (the historical
    behaviour). An un-indexed `a2` keeps the pipeline's own arm id (unlike the
    producing spelling, where `a2` is the revise ALIAS and `reviser1` is the
    first reviser -> a2).
    """
    tok = str(raw).strip().strip("_:/.-").lower().replace(" ", "")
    m = re.fullmatch(r"(judge|j)[_:/.-]?(\d+)", tok)
    if m:
        return f"j{int(m.group(2))}"
    if re.fullmatch(r"\d+", tok):        # `r1_judge_1` / `2:judge_2` -> `j<k>`
        return f"j{int(tok)}"
    m = re.fullmatch(r"(rewriter|writer|w|reviser|revise|a|integrator|integrate|i)"
                     r"(\d+)(?:[_:/.-]j(\d+))?", tok)
    if m:
        cls, idx, j = m.group(1), int(m.group(2)), m.group(3)
        if cls in ("rewriter", "writer", "w"):
            vid = f"w{idx}"
        elif cls in ("reviser", "revise"):
            vid = f"a{idx + 1}"          # reviser N is the a{N+1} arm
        elif cls == "a":
            vid = f"a{idx}"              # the pipeline's own arm id, as before
        else:
            vid = f"i{idx}"
        return vid + (f"_j{j}" if j else "")
    if re.fullmatch(r"orig(?:[_:/.-]j\d+)?", tok):
        return tok
    if re.fullmatch(r"r\d+[_:/.-](?:w\d+|a\d+|i\d+)(?:[_:/.-]j\d+)?", tok):
        # A PIN id (`r1_w2`) is a legal judge-field version: it names the
        # inherited base of a later round.
        return tok
    die(f"{flag}: {part!r} is not a judge session this pipeline knows (use `judge` for the whole "
        f"stage, or a session such as `r1_judge_w2_j1`, `w2_j1`, `integrator2_j1` or `judge1`)", code=2)


def _session_token(raw: str, part: str, flag: str = "--only") -> str:
    """Normalize one session token: `rewriter2` -> `w2`, `reviser1` -> `a2`, ...

    The friendly class+index spellings the operator is most likely to type are
    mapped onto the pipeline's own version ids. An empty token is refused with
    the spellings that always work.
    """
    tok = str(raw).strip().strip("_:/.-").lower().replace(" ", "")
    if not tok:
        die(f"{flag}: {part!r} names no session (use a stage name, or a session such as "
            f"`rewriter1`, `integrator2`, `w2`, `r1_w2` or `r1_judge_w2_j1`)", code=2)
    m = re.fullmatch(r"(rewriter|writer|w)(\d+)", tok)
    if m:
        n = int(m.group(2))
        if n < 1:
            die(f"{flag}: {part!r} names {tok}: session indices are 1-based "
                f"(`rewriter1`/`w1` is the first rewrite arm)", code=2)
        return f"w{n}"
    m = re.fullmatch(r"(reviser|revise|a)(\d+)", tok)
    if m:
        # The pipeline numbers its revise arms a2, a3, ... (a1 is the base copy),
        # so reviser N is the a{N+1} arm. N=0 would therefore map onto a1, the
        # round base COPY that _add_session_id() refuses; returning it here made
        # `--only reviser0` select a session no round-plan entry carries (a
        # silent no-op) instead of dying like every other a1 spelling (F96).
        n = int(m.group(2))
        if n < 1:
            die(f"{flag}: {part!r} names {tok}: revise sessions are 1-based "
                f"(`reviser1` is the first reviser, which edits a1 into a2)", code=2)
        return f"a{n + 1}"
    m = re.fullmatch(r"(integrator|integrate|i)(\d+)", tok)
    if m:
        n = int(m.group(2))
        if n < 1:
            die(f"{flag}: {part!r} names {tok}: session indices are 1-based "
                f"(`integrator1`/`i1` is the first integrate arm)", code=2)
        return f"i{n}"
    # Canonical `guided_review`/`guided_review_b`, plus the pre-rename
    # `review`/`reviewer`/`review_b` spellings the CLI help and README still
    # document: the parser accepts them, so this mapper must too (F12).
    m = re.fullmatch(r"(guided_review|reviewer|review)(_?b)?", tok)
    if m:
        return "guided_review_b" if m.group(2) else "guided_review"
    if re.fullmatch(r"(?:a1|w\d+|a\d+|i\d+|orig|guided_review|guided_review_b|"
                    r"cold_start_review|audit|feedback|concerns|response)", tok):
        if tok == "a1":
            die(f"{flag}: {part!r} names a1, the round base COPY -- it has no agent session "
                f"(use `reviser1` for the first reviser, which edits a1 into a2)", code=2)
        if tok == "orig":
            die(f"{flag}: {part!r} names the pristine original, which has no agent session", code=2)
        return tok
    die(f"{flag}: {part!r} is not a session this pipeline knows (use a stage name, or a session "
        f"such as `rewriter1`, `reviser1`, `integrator1`, `guided_review`, `audit`, `w2`, `w2_j1`, "
        f"`r1_w2`, `r1_judge_w2_j1`)", code=2)


def session_id_of_entry(entry: dict) -> str:
    """The id of the agent session a round-plan entry runs (`w2`, `a2`, `review`...).

    Review and audit entries carry no `vid`; their session id is the bare stage
    name, except the second review session of `--review-split`, which is
    `guided_review_b` (the id `--only r1_guided_review_b` selects).
    """
    vid = str((entry or {}).get("vid") or "")
    if vid:
        return vid
    rid = str((entry or {}).get("id") or "")
    return "guided_review_b" if rid.endswith("_guided_review_b") else plan_stage_of(entry)


def _non_editable_entries(sources: list) -> dict:
    """{corpus-relative path: digest} for the NON-editable submission files.

    `collect_documents` keeps only EDITABLE_DOC_EXTS, which is what the
    one-to-one document pairing needs. The ADDED direction of
    `document_set_check` also has to see the other half of a submission -- a new
    PDF, figure or archive the base never had -- because a non-editable file
    added to a package used to be invisible to the check (the collector dropped
    it before the comparison). The same corpus exclusions apply, and the
    editable suffixes are left out because `added` already covers them.

    The DIGEST is carried so a pure rename is not reported as an invented file.
    """
    out = {}
    overrides = corpus_source_overrides(sources)
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        for p in _iter_tree_files(src):
            if _is_aux_doc(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded_corpus_component(rel, excluded):
                continue
            if (prefix + rel) in overrides[i]:
                continue
            if is_evidence_rel(rel):
                continue
            if is_author_to_complete_readme_name(p.name):
                continue
            if is_bookkeeping_name(p.name):
                continue
            if p.suffix.lower() in EDITABLE_DOC_EXTS:
                continue
            out[prefix + rel] = sha256_files([p], on_error="<unreadable>")[0]
    return out


def parse_only_stages(raw) -> set:
    """The STAGE side of `--only` (`run --only rewrite,review,merge`).

    Kept for the stage-only callers and tests: None/empty/`all` selects every
    stage (the default). A round-qualified item (`2:review`) contributes its
    stage -- `stage_filter()` returns `set()` as soon as ANY round-qualified
    item exists, so returning it here gave the broadest possible filter for a
    narrow selection (F194). The round filter itself lives in
    parse_only_spec(), which is what the `run` command uses.
    """
    spec = parse_only_spec(raw)
    if spec is None or spec.all_stages or spec.rounds_in_full:
        return set()
    if any(not stages for stages in spec.pairs.values()):
        return set()                    # `2:all` -- every stage of round 2
    stages = set(spec.stages)
    for round_stages in spec.pairs.values():
        stages |= set(round_stages)
    return stages


# --- filesystem/path helpers (moved here from p04 to keep every part under
#     the 10,000-line structural limit; all callers resolve these at run time) --
def make_writable(path: Path, *, directory: bool = None) -> bool:
    """Give one entry its owner write bit back; True when the mode changed."""
    if directory is None:
        try:
            directory = path.is_dir() and not path.is_symlink()
        except OSError:
            directory = False
    bits = 0o700 if directory else 0o600
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    if mode & bits == bits:
        return False
    try:
        os.chmod(path, mode | bits)
    except OSError:
        return False
    return True


def make_tree_writable(root: Path, skip_top=()) -> list:
    """Give the pipeline's own copy of a tree back the write bits it needs.

    Returns `[(path, mode_before), ...]` for every entry whose mode changed, so
    a caller that must leave the tree exactly as it found it (restoring raw_data
    from the pristine copy) can put the modes back with `restore_modes`.
    `skip_top` names top-level entries whose modes must not be touched at all:
    the read-only raw-data directory is the reason this helper exists, so callers
    that may write anywhere BUT raw_data pass `skip_top=RAW_DATA_DIRNAMES`.
    """
    if Path(root).is_symlink():
        # chmod() follows links, and iterdir() would list the target's entries:
        # descending through a symlinked root would hand write bits to the
        # SHARED read-only evidence store. A link is never the pipeline's own
        # copy to make writable.
        return []
    plan: list = []
    skipped = set(skip_top or ())

    def bump(p: Path, bits: int) -> None:
        if p.is_symlink():
            # chmod() follows symlinks, so bumping one would change the SHARED
            # canonical target's modes (the read-only evidence store). Links are
            # never the thing that needs write bits.
            return
        try:
            mode = p.lstat().st_mode
        except OSError:
            return
        if mode & bits == bits:
            return
        try:
            os.chmod(p, mode | bits)
        except OSError:
            return
        plan.append((p, stat.S_IMODE(mode)))

    def visit(p: Path, is_root: bool) -> None:
        bump(p, 0o700)                  # directories: rwx (list, descend, unlink)
        try:
            entries = sorted(p.iterdir())
        except OSError:
            return
        for entry in entries:
            if is_root and entry.name in skipped:
                continue
            try:
                is_dir = entry.is_dir() and not entry.is_symlink()
            except OSError:
                is_dir = False
            if is_dir:
                visit(entry, False)
            else:
                bump(entry, 0o600)      # files: rw (rewrite, unlink, replace)

    visit(Path(root), True)
    return plan


def restore_modes(plan) -> None:
    """Put back the modes recorded by `make_tree_writable` (deepest first)."""
    for path, mode in reversed(list(plan or [])):
        try:
            os.chmod(path, mode)
        except OSError:
            continue


def _rmtree_retry(func, path, _exc=None) -> None:
    """shutil.rmtree error hook: clear the blocking mode and retry the call."""
    if os.path.islink(path):
        # Never chmod THROUGH a link: the shared evidence store must keep its
        # modes. On Python 3.12 shutil.rmtree raises for a link and calls this
        # hook with func=os.path.islink; calling that func again is a no-op and
        # suppresses the error, so the link used to survive while rmtree
        # reported success. Unlink it for real.
        with contextlib.suppress(OSError):
            os.unlink(path)
        return
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)
    with contextlib.suppress(OSError):
        func(path)


def rmtree_force(path: Path, ignore_errors: bool = False) -> bool:
    """Delete a tree the pipeline owns, even when it carries read-only entries.

    `shutil.rmtree` cannot descend into or unlink from a directory without the
    execute/write bits -- exactly how a copy of a read-only `raw_data/` behaves
    inside a scratch tree. The ordinary delete is the fast path; only when it
    fails do we hand the write bits back (to the whole tree, since shutil may
    stop at the first refusal) and retry. Returns True when the tree is gone.
    """
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return True
    if p.is_symlink():
        # rmtree never descends a link; remove the LINK itself (the target is
        # not ours to delete and must survive).
        try:
            p.unlink()
            return True
        except OSError:
            if ignore_errors:
                return False
            raise
    if p.exists() and not p.is_dir():
        # A plain file where a directory was expected is not a tree: rmtree
        # raises NotADirectoryError, make_tree_writable then changed the file's
        # mode, and ensure_copy's repair failed with FileExistsError (F130).
        # Unlink it so the materializer can rebuild the directory.
        try:
            p.unlink()
            return True
        except OSError:
            if ignore_errors:
                return False
            raise
    try:
        shutil.rmtree(p)
        return True
    except OSError:
        pass
    make_tree_writable(p)
    retry_kwargs = ({"onexc": _rmtree_retry} if sys.version_info >= (3, 12)
                    else {"onerror": _rmtree_retry})
    try:
        shutil.rmtree(p, **retry_kwargs)
    except OSError:
        if not ignore_errors:
            raise
    # A 3.12 `onexc`/3.11 `onerror` callback that returns is treated by shutil
    # as "handled": rmtree can return normally while the tree survives. Report
    # the truth instead of unconditional success (F120).
    return not (p.exists() or p.is_symlink())


# ---- read-only evidence areas: ONE copy per root, symlinked into sandboxes ----
# raw_data/ and human_review_feedback/ are INPUTS: nothing may write them, and
# every stage sandbox needs them. Copying them into every sandbox (each round
# materializes ~10 stage sandboxes) duplicated gigabytes for nothing, so the
# sandbox's copy is a SYMLINK to the root's canonical pristine copy
# (<root>/non_revised/<area>), which is chmod-protected read-only. If the
# platform cannot create symlinks the copy path is used unchanged.
def _try_symlink_dir(target: Path, link: Path) -> bool:
    """Create `link` -> `target` as a RELATIVE directory symlink; False on failure."""
    try:
        rel = os.path.relpath(str(target), str(link.parent))
        os.symlink(rel, str(link), target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


def make_tree_readonly(root: Path, skip_top=()) -> int:
    """Clear the write bits of a tree (never following symlinks); count entries.

    The write bits are cleared on FILES first and on DIRECTORIES last, so the
    caller can still traverse while working. A symlink is left alone (chmod
    would follow it).
    """
    changed = 0
    root = Path(root)
    if root.is_symlink():
        # `is_dir()` follows the link, and `rglob` then walks the TARGET; the
        # docstring promises no symlink is followed, but chmod cleared the write
        # bits on a foreign raw-data tree when the evidence root was a link.
        return 0
    if not root.is_dir():
        return 0
    dirs = []
    for p in [root, *sorted(root.rglob("*"))]:
        if p.is_symlink():
            continue
        try:
            if p.relative_to(root).parts[:1] and p.relative_to(root).parts[0] in skip_top:
                continue
        except (ValueError, IndexError):
            pass
        try:
            if p.is_dir():
                dirs.append(p)
                continue
            mode = stat.S_IMODE(p.lstat().st_mode)
            if mode & 0o222:
                os.chmod(p, mode & ~0o222)
                changed += 1
        except OSError:
            continue
    for d in sorted(dirs, key=lambda x: len(x.parts), reverse=True):
        try:
            mode = stat.S_IMODE(d.lstat().st_mode)
            if mode & 0o222:
                os.chmod(d, mode & ~0o222)
                changed += 1
        except OSError:
            continue
    return changed


def evidence_areas_of(dirp: Path) -> list:
    """The top-level ENABLED evidence area names present in one corpus directory.

    A `<area>.disabled` / `<area>.off` directory is INERT (README): it is never
    read as feedback or evidence, never part of the submission and never shown
    to a judge. It is therefore not an evidence area, and listing it here made
    every sandbox symlink it (F35).
    """
    out = []
    for name in EVIDENCE_DIRNAMES:
        p = Path(dirp) / name
        if p.is_dir() or p.is_symlink():
            out.append(name)
    return out


def inert_evidence_names(dirp: Path) -> list:
    """The top-level `<area>.disabled`/`.off` names under one corpus directory."""
    out = []
    try:
        for child in sorted(Path(dirp).iterdir()):
            if is_disabled_evidence_name(child.name):
                out.append(child.name)
    except OSError:
        pass
    return out


def ensure_pristine_input(ctx: Ctx, dst: Path) -> dict:
    """Materialize a sandbox's pristine input with SYMLINKED evidence areas.

    Everything else is copied (the manuscript sources are edited/copied by the
    stages); the evidence areas (raw_data/, human_review_feedback/,
    llm_review_feedback/)
    become RELATIVE symlinks to the root's canonical pristine copy -- one
    physical copy per root, no per-sandbox duplication. The canonical areas are
    chmod-protected read-only, so a write through a link fails at the filesystem
    level instead of corrupting every sandbox. Falls back to real copies when
    the platform refuses symlinks. Returns a small record for the run/print:
    {"rebuilt", "linked": [...], "copied": [...], "fallback_reason"}.
    """
    areas = evidence_areas_of(ctx.pristine)
    # An inert `<area>.disabled/` is neither linked nor copied into a sandbox
    # (copy_into skips it unconditionally); exclude it from the manifests too,
    # or every rebuild would see a permanently mismatching expected tree.
    inert = inert_evidence_names(ctx.pristine)
    excluded = set(areas) | set(inert)
    want = {name: ctx.pristine / name for name in areas}
    info = {"rebuilt": False, "linked": [], "copied": [], "fallback_reason": None}
    for name in areas:
        # The canonical copy is read-only: a write through a sandbox's link
        # fails instead of corrupting every sandbox's evidence.
        make_tree_readonly(want[name])
    ok = dst.is_dir()
    if ok:
        # The non-evidence part must match the pristine corpus exactly, and every
        # evidence area must be a link to the canonical copy.
        if not manifests_equal(
                hash_manifest(ctx.pristine, exclude_top_only=excluded),
                hash_manifest(dst, follow_dir_links=True,
                              exclude_top_only=excluded)):
            # `files` alone hid a difference inside an unreadable subtree (F112).
            ok = False
        for name in areas:
            link = dst / name
            if link.is_symlink():
                if link.resolve() != want[name].resolve():
                    ok = False
                    break
            elif link.is_dir():
                # Symlinks are unavailable: the fallback copied the area as a
                # REAL directory. Accepting it when it byte-matches the
                # canonical area makes the second call converge instead of
                # deleting and re-copying the whole input every time (F87).
                if (hash_manifest(link, follow_dir_links=True).get("files")
                        != hash_manifest(want[name]).get("files")):
                    ok = False
                    break
            else:
                ok = False
                break
    if ok:
        return info
    if dst.exists() and not rmtree_force(dst, ignore_errors=True):
        # copy_into overwrites by NAME but never deletes a stale entry, so a
        # wipe that failed must not be merged into a "rebuilt" copy (F146).
        raise RuntimeError(
            f"refusing to rebuild {dst}: the stale tree could not be removed, so "
            f"copying into it would merge stale content with the fresh copy")
    dst.mkdir(parents=True, exist_ok=True)
    copy_into(ctx.pristine, dst, exclude_top_only=set(areas), root=ctx.root)
    for name in areas:
        link = dst / name
        if _try_symlink_dir(want[name], link):
            info["linked"].append(name)
        else:
            copy_into(want[name], link, root=ctx.root)
            info["copied"].append(name)
            if info["fallback_reason"] is None:
                info["fallback_reason"] = ("symlinks are unavailable on this filesystem; the "
                                           "evidence areas were copied (no space saving)")
    info["rebuilt"] = True
    return info


def _corpus_ignore(skip_aux: bool, strip_bookkeeping: bool):
    """shutil.copytree ignore-callback for a VERSION CORPUS copy."""
    def _ignore(dirpath, names):
        out = []
        # Exclude only REGULAR FILES: the manifest functions filter `is_file()`,
        # so a DIRECTORY whose name happens to look auxiliary/bookkeeping (e.g.
        # `notes.tracking-a1.docx/`) stayed in the manifest while the copy
        # dropped it, and the digest no longer described the copied corpus
        # (F062).
        def _file(name):
            full = os.path.join(dirpath, name)
            return os.path.isfile(full) and not os.path.islink(full)
        if skip_aux:
            out += [n for n in names if _is_aux_doc(n) and _file(n)]
        if strip_bookkeeping:
            out += [n for n in names if is_bookkeeping_name(n) and _file(n)]
        return out
    return _ignore


def copy_into(src: Path, dst: Path, exclude_top=(), skip_aux: bool = False,
              strip_bookkeeping: bool = False, normalize_mtime: bool = False,
              root: Path = None, exclude_top_only=()) -> None:
    """Copy the CONTENTS of src into dst (idempotent; overwrites files).

    root: the pipeline root that owns `src`. A top-level evidence link is
    followed only when it resolves to THIS root's canonical
    `<root>/non_revised/<area>` store (see `is_canonical_evidence_link`); a
    caller that omits it follows no evidence link at all.

    exclude_top: SCRATCH names to skip (used to keep a candidate's process
    scratch, e.g. revised/work/, out of its submission corpus). A name in this
    list is excluded as a DIRECTORY at ANY depth: a nested `supp/work/` is the
    same stage scratch as a top-level `work/`, and the revision token already
    excludes it at every depth.
    exclude_top_only: entry names to skip ONLY as the first path component. This
    is the distinct meaning `ensure_pristine_input` needs for the evidence-area
    names (`raw_data/` ...): a nested `supp/raw_data/` is ordinary submission
    content, not the root's evidence area (`evidence_area_of` recognises only a
    top-level name), so the any-depth rule above must not drop it (R02).
    skip_aux: leave out the difference-tracking auxiliaries
    ("*.tracking-<token>.<ext>" and their "*.logging-<token>.<ext>" fallbacks)
    -- set by every call that
    materializes a VERSION CORPUS (base, judge target, pin, published winner), so
    the corpus the judges score is exactly the corpus that is pinned. A raw
    sandbox copy (a read-only input) keeps every file.
    strip_bookkeeping: additionally leave out the pipeline's own mandated
    reports (CHANGELOG.md, MANUAL_STEPS.md, REVISION_REPORT.md,
    revision_report.json, DIFF_LEDGER.md, VISUAL_CHECK.md). Set by the same
    VERSION CORPUS callers: those files are written by the agent that wrote the
    version, so handing them to a judge would leak provenance and let
    self-written claims influence a relative score. The sandbox keeps them for
    the postchecks, the manual-item count and the decision report.

    An `is_non_shippable_name` file (the WSL/Windows `figS3.png:Zone.Identifier`
    stub, a `*.pyc`, a Word `~$` owner file) is carried through a CORPUS copy
    unchanged, junk included: a corpus materialized here is exactly the corpus
    the judges scored. The stage postcheck removes these files BEFORE the
    corpus digest is taken; `publish_final_clean` reports any that a package
    built by an older orchestrator still carries rather than changing judged
    bytes after the pin.
    normalize_mtime: give every copied file and directory ONE timestamp. Set by
    the VIEW builders: shutil.copy2 preserves the source mtimes, so content
    written later would otherwise carry newer timestamps than content written
    earlier -- an ordering signal the blind protocol must not hand over. Content
    hashes are unaffected.

    Symlinks are NEVER followed: a link inside a submission may point at a local
    secret outside the package, and copying its target leaked that file into the
    pristine root, sandboxes, judge views and the published package. The one
    exception is a TOP-LEVEL link to the root's CANONICAL evidence store
    (`<root>/non_revised/<area>`): a version corpus legitimately carries that
    link, and materializing it is what keeps the corpus digest equal to the
    recorded input manifest. A top-level entry merely NAMED `raw_data` does not
    qualify (`is_canonical_evidence_link`) -- its target may be any local
    directory or file. Nested links inside the area are still skipped.
    Every skipped link is named in a warning so the loss is visible instead of
    silent.
    """
    dst = Path(dst)
    # A planted destination ROOT symlink (`dst -> outside`) received every
    # copied file: `_refuse_symlinked_parent` checks the parent chain, never the
    # final component (F43). Refuse the link itself before the mkdir, and
    # re-check after it against a race.
    if dst.is_symlink():
        raise OSError(f"refusing to copy into a symlinked destination directory {dst}")
    _refuse_symlinked_parent(dst)
    dst.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink():
        raise OSError(f"refusing to copy into a symlinked destination directory {dst}")
    skipped = []
    skipped_special = []
    # A symlinked SOURCE ROOT was followed even though every entry inside it is
    # checked individually: `src.iterdir()` traversed the link and copied the
    # target tree (agent-writable run output is passed as `src`). Refuse it
    # unless it is this root's canonical evidence store.
    if src.is_symlink() and not (root is not None and is_canonical_evidence_link(src, root)):
        print(f"warning: skipped symlinked source directory {src} while copying -> {dst} "
              f"(a link is not package content; its target may be outside the package)",
              file=sys.stderr)
        return

    def _ignore(dirpath, names):
        out = set(_corpus_ignore(skip_aux, strip_bookkeeping)(dirpath, names) or ())
        rel = os.path.relpath(dirpath, src)
        for name in names:
            # A symlink planted at the DESTINATION was followed by copy2 (the
            # source link checks below never looked at it): refuse to write
            # through it, which would overwrite an arbitrary outside file.
            dest = dst if rel == "." else dst / rel
            if (dest / name).is_symlink():
                raise OSError(f"refusing to copy onto a symlinked destination entry {dest / name}")
            full = os.path.join(dirpath, name)
            if name in exclude_top and os.path.isdir(full) and not os.path.islink(full):
                # A NAMED DIRECTORY at ANY depth is process scratch, not corpus
                # content: `supp/work/scratch.md` used to be copied into the
                # judged corpus (and pin/published package) while the revision
                # token excluded `work/` at every depth -- the two identity
                # rules disagreed about the same file.
                out.add(name)
                continue
            if os.path.islink(full):
                skipped.append(full)
                out.add(name)
                continue
            try:
                mode = os.lstat(full).st_mode
            except OSError:
                skipped_special.append(full)
                out.add(name)
                continue
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                # A FIFO/socket/device is not package content. copytree raises
                # a raw shutil.Error on a named pipe and left a partially
                # built destination behind (F135); record the skip instead.
                skipped_special.append(full)
                out.add(name)
        return sorted(out)

    for entry in sorted(src.iterdir()):
        if entry.name in exclude_top or entry.name in exclude_top_only:
            continue
        if is_disabled_evidence_rel(entry.name):
            # `<evidence area>.disabled/` is inert: never carried into a
            # version corpus, a sandbox copy or a published package.
            continue
        if entry.is_symlink() and not (
                is_evidence_rel(entry.name) and is_canonical_evidence_link(entry, root)):
            # A top-level link is followed ONLY when it is the canonical
            # `<root>/non_revised/<area>` store; the NAME alone never authorizes
            # copying an arbitrary target into a corpus, sandbox or judge view.
            skipped.append(str(entry))
            continue
        if skip_aux and entry.is_file() and _is_aux_doc(entry.name):
            # Only a FILESYSTEM FILE is an auxiliary document: a DIRECTORY with
            # an auxiliary-looking name must be copied, because the corpus
            # manifest includes its files (F062).
            continue
        if strip_bookkeeping and entry.is_file() \
                and is_bookkeeping_name(entry.name):
            continue
        target = dst / entry.name
        if target.is_symlink():
            raise OSError(f"refusing to copy onto a symlinked destination entry {target}")
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True, ignore=_ignore)
        elif entry.is_file():
            shutil.copy2(entry, target)
        else:
            # A top-level non-regular entry cannot be copied; name it rather
            # than silently dropping it from the corpus (F135).
            skipped_special.append(str(entry))
    if skipped:
        print(f"warning: skipped {len(skipped)} symlink(s) while copying {src} -> {dst} "
              f"(a link is not package content; its target may be outside the package): "
              + ", ".join(sorted(str(s) for s in skipped)[:5])
              + (" ..." if len(skipped) > 5 else ""), file=sys.stderr)
    if skipped_special:
        print(f"warning: skipped {len(skipped_special)} non-regular file(s) while copying "
              f"{src} -> {dst} (a FIFO/socket/device is not package content): "
              + ", ".join(sorted(str(s) for s in skipped_special)[:5])
              + (" ..." if len(skipped_special) > 5 else ""), file=sys.stderr)
    if normalize_mtime:
        # One timestamp for the whole view (the copy just completed, so any
        # moment is honest); an mtime a judge can read is a provenance leak.
        stamp = time.time()
        for p in [dst, *sorted(dst.rglob("*"))]:
            try:
                os.utime(p, (stamp, stamp))
            except OSError:
                continue


def dir_matches(dst: Path, expected_files: dict) -> bool:
    """True when `dst` is a directory whose files hash exactly like expected_files."""
    if not dst.is_dir():
        return False
    return dict(hash_manifest(dst, follow_dir_links=True).get("files") or {}) \
        == dict(expected_files or {})


def ensure_copy(src: Path, dst: Path, **kw) -> bool:
    """Copy src -> dst, REBUILDING dst when it is missing or does not match src.

    Materialization has to be idempotent and self-healing: a sandbox killed in
    the middle of a copy leaves a PARTIAL input directory behind, and a plain
    "copy only when the directory does not exist" rule then froze that
    truncation in place -- the agent worked from a corpus that had silently lost
    files, the truncated state was recorded as the run's frozen input manifest,
    and no later check could see the loss (the candidate was compared against
    the truncated base). Returns True when dst had to be rebuilt.
    """
    # The destination was built WITH the caller's copy options, so the expected
    # manifest must use them too: comparing a full source manifest against a
    # copy that deliberately left `work/` (or an auxiliary/bookkeeping file)
    # out made the mismatch permanent and rebuilt the whole directory on every
    # re-entry.
    want = hash_manifest(
        src, exclude_top=tuple(kw.get("exclude_top") or ()),
        exclude_top_only=tuple(kw.get("exclude_top_only") or ())).get("files") or {}
    # An inert `<area>.disabled/` is never copied (copy_into skips it
    # unconditionally), so it must not make the expected manifest mismatch.
    want = {rel: dig for rel, dig in want.items()
            if not is_disabled_evidence_rel(rel)}
    if kw.get("skip_aux"):
        want = {rel: dig for rel, dig in want.items()
                if not _is_aux_doc(Path(rel).name)}
    if kw.get("strip_bookkeeping"):
        # copy_into's ignore-callback strips a bookkeeping NAME at any depth,
        # so the expected manifest must do the same or a nested report makes
        # the copy rebuild forever.
        want = {rel: dig for rel, dig in want.items()
                if not is_bookkeeping_name(Path(rel).name)}
    if dir_matches(dst, want):
        return False
    if dst.exists() and not rmtree_force(dst, ignore_errors=True):
        raise RuntimeError(
            f"refusing to rebuild {dst}: the stale tree could not be removed, so "
            f"copying into it would merge stale content with the fresh copy")
    copy_into(src, dst, **kw)
    return True


def ensure_corpus_dir(ctx: "Ctx", r: int, vid: str, dst: Path) -> bool:
    """build_corpus_dir() with the same partial-copy repair (see ensure_copy)."""
    want = corpus_manifest(ctx, r, vid).get("files") or {}
    if dir_matches(dst, want):
        return False
    if dst.exists() and not rmtree_force(dst, ignore_errors=True):
        raise RuntimeError(
            f"refusing to rebuild {dst}: the stale tree could not be removed, so "
            f"building the corpus into it would merge stale content with the fresh copy")
    build_corpus_dir(ctx, r, vid, dst)
    return True


def stamp_tree(root: Path, stamp: float) -> None:
    """Give every entry under (and including) `root` one and the same mtime."""
    for p in [root, *sorted(root.rglob("*"))]:
        try:
            os.utime(p, (stamp, stamp))
        except OSError:
            continue


def unique_path(base: Path) -> Path:
    """`base`, or base-2/base-3/... when that name is already taken.

    Archive names carry a UTC timestamp with SECOND resolution (the superseded
    pin/winner copies, displaced `final/` packages, stashed agent logs). Two
    operations inside the same second -- a `decide --package-winner` right after
    a `run`, or two retries of the same run -- produced the same name, and
    shutil.move() then moved the fresh archive INSIDE the existing directory
    instead of replacing it, silently nesting one archive inside another.
    """
    if not base.exists():
        return base
    for i in range(2, 1000):
        cand = base.with_name(f"{base.name}-{i}")
        if not cand.exists():
            return cand
    return base.with_name(f"{base.name}-{os.getpid()}")


def _same_file_bytes(a: Path, b: Path) -> bool:
    """True when two files carry identical bytes (size first, then a hash).

    Used where a MOVE would otherwise create a second copy of the same file
    `unique_path`-style (`publish_final_clean` holding a package's internal-note
    README outside it: a repeat decision over an unchanged package must not
    accumulate `README.md-2`). Compares content, never mtime: the two copies are
    written by different steps and their timestamps say nothing.
    """
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return sha256_file(a) == sha256_file(b)
    except OSError:
        return False


def _pid_alive_windows(pid: int) -> bool:
    """Windows liveness probe that NEVER signals the process it tests.

    CPython's `os.kill(pid, 0)` on Windows opens the process with
    PROCESS_ALL_ACCESS and calls `TerminateProcess(handle, sig)` for every
    signal except CTRL_C_EVENT/CTRL_BREAK_EVENT, so the old probe KILLED the
    lock holder it was deciding about (F133). Open a synchronize-only handle
    instead and wait on it for zero milliseconds: the handle is signaled only
    when the process has terminated.

    Any failure opens are treated as "alive": a permission error means the
    process exists for another user, and a probe that cannot tell must never
    let a stale-lock check steal a live lock.
    """
    if pid <= 0:
        return False
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        wait_for_single = kernel32.WaitForSingleObject
        wait_for_single.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        wait_for_single.restype = ctypes.c_ulong
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
    except (ImportError, AttributeError, OSError):
        return True
    # SYNCHRONIZE is what WaitForSingleObject needs and is the least privilege
    # that answers "is it still running": the handle carries no
    # PROCESS_TERMINATE, so this probe cannot kill the process it tests.
    handle = open_process(0x1000 | 0x00100000, 0, int(pid))
    if not handle:
        err = ctypes.get_last_error()
        # ERROR_INVALID_PARAMETER: no such process. ERROR_ACCESS_DENIED: the
        # process exists but belongs to another user (still alive).
        return err != 87
    try:
        result = wait_for_single(handle, 0)
        # WAIT_OBJECT_0 (0) means the process has TERMINATED. WAIT_TIMEOUT
        # (0x102) means it is still running; any other result (WAIT_FAILED) is
        # unknown, and an unknown probe must read as alive so a live lock is
        # never stolen.
        return result != 0
    finally:
        close_handle(handle)


def pid_alive(pid: int) -> bool:
    """Is a process with this pid running (best effort, POSIX + Windows)?

    Used only to decide whether a lock file is STALE: a permission error means
    the process exists but belongs to another user, which still counts as alive.
    On Windows the POSIX `os.kill(pid, 0)` probe is replaced by a handle wait:
    that call TERMINATES the process it is asked about (F133).
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid > 2_147_483_647:
        # os.kill() raises OverflowError for a pid outside C long/pid_t; a
        # malformed lock file must read as stale, not abort the command.
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # A POSIX signal-0 probe that failed for any other reason cannot tell
        # us the process is gone; never steal a live lock. ProcessLookupError
        # is the ONLY dead result, matching the Windows probe's unknown=>alive
        # rule (F195).
        return True
    return True


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ---- moved from paper_pipeline_parts/p04_utils.py to keep every ordered part under 10,000 lines ----
def scan_lengths_in_sources(sources: list, profile=None) -> dict:
    """Abstract/main-text word counts over [(dir, prefix, excluded_top)] sources.

    A code-side PROXY for the agents' M19 sweep: it reports what it can measure
    and says "not verified"/"skipped" where it cannot. It never gates candidate
    ranking, but an over-cap FINAL published package is reported by readiness.
    The caps and their provenance come from the venue profile: a profile without
    caps (the shipped `generic` one) yields counts with `cap: null` and
    `over_limit: false`, which is what the note and the decision report print.
    """
    prof = _as_profile(profile)
    limits = prof.length_limits()
    source = prof.length_limits_source
    # A document named for the run's OWN article type is that type's
    # manuscript: its opening salutation (a Letter to the Editor) must not
    # divert the count to the cover-letter preference.
    manuscript_names = _normalized_article_type_names(prof)
    # Which display captions this venue leaves out: figure legends always for
    # "figure-legends", table captions only when "table-captions" is named.
    # Passing the selected kinds (rather than one global caption list) keeps a
    # profile that excludes only one of them from subtracting the other.
    _excludes = set(prof.main_text_excludes())
    caption_kinds = tuple(
        kind for kind, section in (("figure", "figure-legends"),
                                   ("table", "table-captions"))
        if section in _excludes)
    overrides = corpus_source_overrides(sources)
    rows, unparsed, skipped, rendered, docs = [], [], [], [], set()
    unreadable = []
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        # Multi-file LaTeX: a master .tex carries only \input/\include lines and
        # its children carry the prose. Cache every source and remember which
        # files are INCLUDED by another, so the master counts the expanded text
        # and a child is not counted a second time on its own (F36).
        tex_cache, tex_included = {}, set()
        src_gaps = []
        for q in _iter_tree_files(src, gaps=src_gaps):
            if q.suffix.lower() not in LENGTH_TEX_EXTS:
                continue
            qtext = read_text_bounded(q)
            if qtext is None:
                continue
            tex_cache[q.resolve()] = qtext
        # Resolve includes exactly as _tex_expand_includes() does: from the
        # directory of the MASTER being expanded, at every nesting level. The
        # old per-file `q.parent` lookup matched only a child-relative
        # convention, so a nested `\input{chapters/method}` inside
        # `chapters/intro.tex` was expanded into the master's count yet left
        # out of `tex_included`, and method.tex was counted a second time on
        # its own (F75). Each cached .tex is a potential master (the second
        # loop scans every one that is not itself included), so walk from each
        # with that master's own base.
        for master in list(tex_cache):
            base = master.parent
            pending, reachable = [(master, 0)], {master}
            while pending:
                cur, depth = pending.pop()
                if depth + 1 >= TEX_MAX_INCLUDE_DEPTH:
                    continue            # expansion stops here too (named gap)
                cur_text = tex_cache.get(cur)
                if cur_text is None:
                    continue
                for inc in TEX_INCLUDE_RE.finditer(strip_tex_comment(cur_text)):
                    child = _tex_include_path(base, inc.group(1))
                    if child is None or child in reachable:
                        continue
                    reachable.add(child)
                    tex_included.add(child)
                    pending.append((child, depth + 1))
        for p in _iter_tree_files(src, gaps=src_gaps):
            # `_iter_tree_files` is the corpus walker: a file symlink is not
            # package content (copy_into refuses it), so a scan that followed
            # one verified a corpus the materializer never produced.
            if _is_aux_doc(p.name) or is_bookkeeping_name(p.name) \
                    or is_non_submitted_readme_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and excluded_corpus_component(rel, excluded):
                continue
            if is_code_rel(prefix + rel):
                # `code/` is not manuscript prose (see scan_captions_in_sources).
                continue
            if (prefix + rel) in overrides[i]:
                continue                      # a later source provides this path
            if is_non_manuscript_rel(rel):
                # Evidence areas and feedback/response documents are never
                # counted against the article's word limits (M19 measures the
                # submission's abstract, body and cover letter only).
                continue
            doc = prefix + rel
            ext = p.suffix.lower()
            if docx_document_role(p.name, manuscript_names) == "supp":
                skipped.append(doc)         # supplementary text is not under the article caps
                continue
            lines, caption_spans, abstract_end = None, [], None
            if ext in LENGTH_DOCX_EXTS:
                # Frontiers' counting source excludes the CONTENTS of tables and
                # boxes; a profile that says so must not count cell paragraphs
                # as main text (F08).
                paras = _docx_paragraphs(p, include_tables="table-contents" not in _excludes)
                if paras is None:
                    unparsed.append(doc)
                    continue
                lines = paras
                # A wrapped DOCX legend is usually split over several
                # paragraphs. `_caption_units` sees one paragraph at a time, so
                # only its first line was excluded and the continuation was
                # charged to the article cap (F04). The line-oriented reader
                # merges continuations with the SAME rules the text extractor
                # uses.
                caption_spans = [(a, b) for _, _, a, b
                                 in _caption_units_from_lines(paras, with_spans=True,
                                                              kinds=caption_kinds)]
            elif ext in LENGTH_TEX_EXTS:
                if p.resolve() in tex_included:
                    skipped.append(doc)     # counted in the master that includes it
                    continue
                text = tex_cache.get(p.resolve())
                if text is None:
                    # The cache loop skips a .tex whose read_text_bounded()
                    # returned None; the old "" default then counted that
                    # unreadable manuscript as an EMPTY source within every
                    # cap. An unreadable source is a NAMED gap, exactly like
                    # the .md/.txt branch below (F103).
                    unparsed.append(doc)
                    continue
                expanded = _tex_expand_includes(text, p.parent, source=p)
                for inc in TEX_INCLUDE_RE.finditer(expanded):
                    unparsed.append(f"{doc}: unresolved include {inc.group(1)}")
                lines, caption_spans, abstract_end = _tex_length_scan(expanded)
            elif ext in LENGTH_TEXT_EXTS:
                text = read_text_bounded(p)
                if text is None:
                    # An unreadable manuscript source is a NAMED gap, not an
                    # empty rendering (F65).
                    unparsed.append(doc)
                    continue
                lines = text.splitlines()
                caption_spans = [(a, b) for _, _, a, b
                                 in _caption_units_from_lines(lines, with_spans=True,
                                                              kinds=caption_kinds)]
            elif ext in LENGTH_UNPARSED_EXTS:
                unparsed.append(doc)
                continue
            elif ext in LENGTH_RENDERED_EXTS:
                skipped.append(doc)         # a rendering, not an editable source
                rendered.append(doc)
                continue
            else:
                continue
            if _is_cover_letter_lines(lines, p.name, manuscript_names):
                docs.add(doc)
                rows.append(_cover_letter_row(lines, doc, limits=limits, profile=prof))
                continue
            found = _length_rows_for_lines(lines, doc, caption_spans=caption_spans,
                                           abstract_end=abstract_end, limits=limits,
                                           counting=prof.counting,
                                           whole_doc_as_main=bool(
                                               _name_is_article_type_manuscript(
                                                   p.name, manuscript_names)))
            if not found:
                skipped.append(doc)
                continue
            docs.add(doc)
            rows.extend(found)
        # An unreadable subdirectory hides its documents from the walk; name it
        # so the note can tell "no manuscript" from "nothing readable" (F049).
        unreadable.extend(prefix + g for g in src_gaps)
    over = [r for r in rows if r["over_limit"]]
    return {"limits": limits, "counting": prof.counting, "source": source,
            "venue": prof.id,
            "rows": rows, "count": len(rows), "over_limit": over,
            "unparsed": sorted(set(unparsed)), "skipped": sorted(set(skipped)),
            "rendered": sorted(set(rendered)),
            "needs_manual": sorted(set(rendered)) if not rows else [],
            "documents": sorted(docs), "checked": bool(rows),
            "unreadable_dirs": sorted(set(unreadable))}


# ---- moved from paper_pipeline_parts/p06_postchecks.py to keep every ordered part under 10,000 lines ----
def mcp_server_spec(name: str) -> dict:
    """{command, args} for one configured MCP server, {} when unreadable.

    The operator's own `~/.codex/config.toml` entry is the authority (same
    regex-scoped read as `mcp_server_configured`): the orchestrator must drive
    EXACTLY the server the agent sessions are configured with.
    """
    try:
        text = codex_config_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    quoted = re.escape(name)
    # A legal trailing comment (`[mcp_servers.x] # note`) does not unconfigure
    # the server: with `\]\s*$` the header never matched, so a configured server
    # probed as absent.
    header = re.compile(r"^\s*\[\s*mcp_servers\s*\.\s*(?:\"" + quoted + r"\"|'"
                        + quoted + r"'|" + quoted + r")\s*\]\s*(?:#.*)?$", re.MULTILINE)
    # The header itself is a line of TOML STRUCTURE: a `[mcp_servers.x]` line
    # inside another entry's multi-line string does not configure a server. The
    # mask keeps every offset, so the body slice still indexes the real text.
    m = header.search(_toml_unquoted_mask(text))
    if not m:
        return {}
    rest = text[m.end():]
    # The entry's body ends at the next table header, and its keys are found by
    # a line regex -- but neither a header nor a key can legally live inside a
    # TOML string or comment. Mask those bodies first (same length, same
    # offsets) so an `args` value carrying a `command = "evil"` line is not
    # read as the executable (F011), and a `[section]` line inside that string
    # does not truncate the body and hide the real `command`.
    masked_rest = _toml_unquoted_mask(rest)
    nxt = re.search(r"^\s*\[", masked_rest, re.MULTILINE)
    body = rest[:nxt.start()] if nxt else rest
    keys = masked_rest[:nxt.start()] if nxt else masked_rest
    cm = re.search(r"^[ \t]*command[ \t]*=[ \t]*", keys, re.MULTILINE)
    if not cm:
        return {}
    got = _toml_string_at(body, cm.end())
    if got is None or not got[0].strip():
        return {}
    # The TOML basic string decodes its escapes: `command = "C:\\Program
    # Files\\node.exe"` names `C:\Program Files\node.exe`, and the raw
    # `C:\\Program Files\\node.exe` never started on Windows.
    command = os.path.expanduser(got[0])
    args = []
    am = re.search(r"^\s*args\s*=\s*", keys, re.MULTILINE)
    if am:
        raw = _toml_array_at(body, am.end())
        if raw is None:
            # The `args` KEY is present but its value is not a readable TOML
            # array (an unterminated array, `args = "server.js"`, a malformed
            # quote). That is UNREADABLE, never "configured with no arguments":
            # leaving `args` empty launched the server with no argv at all --
            # the silent wrong configuration the block below claims to prevent
            # (F113). The `_toml_array_values` failure path returns {} for the
            # same reason.
            return {}
    else:
        raw = None
    if raw is not None:
        values = _toml_array_values(raw)
        if values is None:
            # A malformed entry is UNREADABLE, never "configured with no
            # arguments": `json.loads` alone rejects TOML's own literal strings
            # (`args = ['a']`) and TOML's trailing comma (`["a", "b",]`), and
            # the old `except ValueError: args = []` then launched the server
            # with no argv at all -- the silent wrong configuration
            # `_toml_array_at` exists to prevent. Returning {} makes the caller
            # report the entry instead of using it half-read.
            return {}
        args = values
    spec = {"command": command, "args": args}
    # `scripts/README-codex-mcp.md` lists command,args,env,cwd as the SAME
    # fields in a Codex MCP entry. Dropping env/cwd launched the orchestrator's
    # server with the pipeline's environment and working directory instead of
    # the operator's configured one (F28).
    wm = re.search(r"^[ \t]*cwd[ \t]*=[ \t]*", keys, re.MULTILINE)
    if wm:
        cwd_got = _toml_string_at(body, wm.end())
        if cwd_got is None:
            return {}
        spec["cwd"] = os.path.expanduser(cwd_got[0])
    em = re.search(r"^[ \t]*env[ \t]*=[ \t]*", keys, re.MULTILINE)
    if em:
        raw_env = _toml_inline_table_at(body, em.end())
        env_values = _toml_inline_table_values(raw_env) if raw_env is not None else None
        if env_values is None:
            return {}                   # a malformed env block: unreadable entry
        spec["env"] = env_values
    if "env" not in spec:
        # TOML also allows a subtable form: `[mcp_servers.<name>.env]` followed
        # by `KEY = "value"` lines. It configures the same field, so ignoring it
        # would keep launching with the pipeline's environment.
        env_header = re.compile(
            r"^\s*\[\s*mcp_servers\s*\.\s*(?:\"" + quoted + r"\"|'"
            + quoted + r"'|" + quoted + r")\s*\.\s*env\s*\]\s*(?:#.*)?$",
            re.MULTILINE)
        # The header is TOML STRUCTURE, exactly like the main entry's header:
        # search the unquoted mask so a `[mcp_servers.<name>.env]` line inside
        # another entry's multi-line string is not read as a real subtable.
        # The mask keeps every offset, so the body slice below indexes the real
        # text (F119).
        eh = env_header.search(_toml_unquoted_mask(text))
        if eh:
            rest_env = text[eh.end():]
            next_hdr = re.search(r"^\s*\[", rest_env, re.MULTILINE)
            env_body = rest_env[:next_hdr.start()] if next_hdr else rest_env
            values = {}
            for raw_line in env_body.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    return {}
                key_part, value_part = line.split("=", 1)
                key_part, value_part = key_part.strip(), value_part.strip()
                if key_part[:1] in "\"'":
                    key_got = _toml_string_at(key_part, 0)
                    if key_got is None or key_got[1] != len(key_part):
                        return {}
                    key = key_got[0]
                elif re.fullmatch(r"[A-Za-z0-9_.\-]+", key_part):
                    key = key_part
                else:
                    return {}
                if value_part[:1] in "\"'":
                    val_got = _toml_string_at(value_part, 0)
                    if val_got is None:
                        return {}
                    value = val_got[0]
                else:
                    value = value_part.split("#", 1)[0].strip()
                values[key] = value
            spec["env"] = values
    return spec


# ---- moved from paper_pipeline_parts/p07_stage_quality_journal.py to keep every ordered part under 10,000 lines ----
def m30_hierarchy_problems(sb: Path, frozen_all, pkg: str = "") -> tuple:
    """(errs, warns) for the M30 source-hierarchy reconciliation record.

    The evidence is the stage's own seeded ledger: every row disposed means the
    revision looked at the written value AND its producer, so an empty
    disposition cell means the comparison the finding rests on was never
    recorded (rule E12).

    WHERE THE ROWS LIVE was ambiguous and cost the 2026-11-01 revise arm its
    second attempt. The seed is `work/<name>` in the SANDBOX (`decide` writes it
    next to PROMPT.md), but the stage's deliverables are all under the package,
    so one reviser disposed `revised/work/<name>` (53/53 rows answered) while
    the postcheck read the untouched sandbox copy and failed it on "53 of 165
    ... EMPTY". The check therefore reads BOTH copies and judges the disposed
    one; a run that answered either copy did the work. The message names which
    copy was read.

    The old message also reported `len(block_problems)` as "N undisposed
    row(s)" and then pasted 80 characters of the first problem into it,
    truncated mid-word, producing
      "still carries 1 undisposed row(s) (53 of 165 row(s) have an EMPTY
       disposition cell (every seeded row must be dispos)"
    -- a count of problems labelled as a count of rows, an unbalanced
    parenthesis and a cut word, which is what reached the operator's log.
    """
    m30_ids = [str(f.get("id") or "").strip() for f in frozen_all
               if str(f.get("check") or "").strip().upper() == "M30"]
    errs, warns = [], []
    if not m30_ids:
        return errs, warns
    candidates = []
    if pkg:
        package_copy = Path(sb) / pkg / M30_HIERARCHY_REL
        if package_copy.is_file():
            candidates.append((f"{pkg}/{M30_HIERARCHY_REL}", package_copy))
    sandbox_copy = Path(sb) / M30_HIERARCHY_REL
    if sandbox_copy.is_file():
        candidates.append((M30_HIERARCHY_REL, sandbox_copy))
    if not candidates:
        looked_for = ([f"{pkg}/{M30_HIERARCHY_REL}"] if pkg else []) + [M30_HIERARCHY_REL]
        warns.append(f"the frozen review carries {len(m30_ids)} M30 source-hierarchy "
                     f"finding(s) but no {' or '.join(looked_for)} exists: rule E12 requires the "
                     f"written side to be aligned with the authoritative producer, with the "
                     f"reconciling reason recorded")
        return errs, warns
    judged, judged_state, judged_score, states = None, None, None, {}
    for label, path in candidates:
        try:
            state = _m30_ledger_state(path)
        except Exception as e:                                      # noqa: BLE001
            warns.append(f"{label}: could not be read ({type(e).__name__}: {e}); the M30 rows "
                         f"there stay unverified")
            continue
        states[label] = state
        # The DISPOSED copy is the reviser's answer: a stale seed left empty
        # beside a filled package copy is not a defect (and the reverse is the
        # case this check was written for). Ordering: a copy that still holds
        # seeded candidate rows is evidence of the check; one with none (an
        # empty or unparsed file) must never beat it just because it has nothing
        # left to report. Among copies that hold such rows, the one with the
        # fewest empty dispositions wins (a tie keeps the package copy, listed
        # first).
        score = (0 if state["actionable"] else 1, state["empty"])
        if judged_score is None or score < judged_score:
            judged, judged_state, judged_score = label, state, score
    if judged_state is None:
        return errs, warns
    sandbox_state = states.get(M30_HIERARCHY_REL)
    if (judged != M30_HIERARCHY_REL and sandbox_state
            and sandbox_state["actionable"]
            and sandbox_state["empty"] == sandbox_state["actionable"]):
        # The reviser answered the package copy and left the seed in place. That
        # is accepted (the work is done), but the record should say which copy
        # was judged so nobody reads the untouched seed as the evidence.
        warns.append(f"{judged} was judged; the sandbox seed {M30_HIERARCHY_REL} is still "
                     f"undisposed ({sandbox_state['empty']} of "
                     f"{sandbox_state['actionable']} row(s) EMPTY)")
    if not judged_state["readable"]:
        # A zero-byte, unreadable or table-less ledger is missing EVIDENCE, not
        # a clean ledger: the old all-zero state returned no error and silently
        # removed the gate (F02).
        errs.append(
            f"{judged} exists but carries no readable M30 table (zero-byte, over the byte "
            f"budget, a symlink/non-regular file, or no markdown table): the source-hierarchy "
            f"reconciliation is unverified. Restore the seeded table and dispose every row.")
        return errs, warns
    actionable, empty = judged_state["actionable"], judged_state["empty"]
    # ROW IDENTITY: a candidate copy that drops seeded rows cannot pass on the
    # strength of the one row it kept. The old score compared only
    # (has actionable rows, empty count), so a one-row package copy with a
    # filled disposition beat a full seed with three empty rows and the gate
    # reported nothing (F01). The reference is the identity PIN the orchestrator
    # wrote BESIDE the sandbox, not the live seed file -- that file is also the
    # documented answer ("dispose every seeded row in place"), so a rewrite of it
    # (or of both it and the ledger) used to pass the check it was supposed to
    # fail (R04/F39). The live sandbox seed is the fallback only for a
    # PROMPT-less unit fixture.
    judged_keys = set(judged_state["rows"])
    reference_rows, reference_available, reference_label = _m30_seed_reference_state(sb)
    if not reference_available:
        if (Path(sb) / "PROMPT.md").is_file():
            # Every real session sandbox carries PROMPT.md, and the seed pin is
            # written beside it. If the pin is gone/unreadable the identity
            # check CANNOT run: report that instead of silently trusting the
            # agent-writable live copy (F39).
            errs.append(
                f"{judged}: the M30 seed reference {reference_label} is missing, "
                f"unreadable or carries no hierarchy rows, so the seeded row identities "
                f"cannot be checked. Restore the evidence pin (or re-run the stage): "
                f"the identity check is not skipped.")
            reference_rows = []
        else:
            # A unit fixture / legacy sandbox without an evidence pin: fall back
            # to the live sandbox seed (the pre-R04 behaviour).
            reference_rows = (sandbox_state["rows"]
                              if (judged != M30_HIERARCHY_REL and sandbox_state
                                  and sandbox_state["readable"]) else [])
            reference_label = M30_HIERARCHY_REL
    dropped = [k for k in reference_rows if k not in judged_keys]
    if dropped:
        errs.append(
            f"{judged} is missing {len(dropped)} of the {len(reference_rows)} seeded M30 "
            f"row(s) recorded in {reference_label} that name a candidate producer: "
            f"{len(dropped)} seeded row(s) were DROPPED instead of disposed. Copy every "
            f"seeded row into the answer and dispose it in place (`OK -- ...` / "
            f"`contradiction -- ...` / `unable -- ...`).")
    if actionable and empty == actionable:
        # None of the rows that actually need a comparison was disposed: the
        # check was not run at all, not merely left one row short. Fail the
        # attempt (the retry prompt carries this message) instead of accepting
        # the warning the evaluation run ignored.
        errs.append(
            f"{judged} still carries {empty} of {actionable} seeded row(s) with a candidate "
            f"producer whose disposition cell is EMPTY: an M30 finding's fix must record the "
            f"producer it reconciled against (rule E12). Dispose every such row in place -- "
            f"`OK -- <the reconciling reason>`, `contradiction -- <finding id>` or "
            f"`unable -- <what is missing>` -- in the ledger you were given.")
    else:
        # EVERY block problem is now an ERROR, not a warning: an empty or
        # boilerplate disposition recorded no comparison, and the gate exists to
        # enforce exactly that (F03). The old code downgraded boilerplate to a
        # warning and never looked at an arbitrary non-empty cell at all.
        detail = "; ".join(str(p) for p in judged_state["block_problems"][:3])
        if judged_state["block_problems"]:
            more = len(judged_state["block_problems"]) - 3
            errs.append(
                f"{judged}: {len(judged_state['block_problems'])} disposition problem(s) -- "
                f"{detail}" + (f" (and {more} more)" if more > 0 else "")
                + ". Every seeded row needs its own disposition: `OK -- <the reconciling "
                  "reason>`, `contradiction -- <finding id>` or `unable -- <what is missing>`.")
        if judged_state["bad_dispositions"]:
            quotes = "; ".join(repr(x[:80]) for x in judged_state["bad_dispositions"][:3])
            errs.append(
                f"{judged}: {len(judged_state['bad_dispositions'])} non-empty disposition "
                f"cell(s) do not use the documented shape ({quotes}): an arbitrary value is "
                f"not a recorded comparison. Use `OK -- ...`, `contradiction -- ...` or "
                f"`unable -- ...`.")
    return errs, warns


# ===========================================================================
# Helpers split out of `p04_utils.py`, `p06_postchecks.py` and
# `p07_stage_quality_journal.py` when those parts crossed the repository's
# 10,000-line limit. The parts are executed in filename order into the same
# globals, so these functions see every earlier constant/helper, and every
# caller sees them once all parts have loaded.
# ===========================================================================

# ---------------------------------------------------------------------------
# Split out of `p04_utils.py`: the Zotero field-continuity gate.
# ---------------------------------------------------------------------------


def zotero_field_continuity_check(base_dir: Path, out_dir: Path, label: str,
                                  errs: list, warns: list) -> dict:
    """Every Zotero field of `base_dir` must survive into the version in `out_dir`.

    The stage gate for every agent that produces a DOCX. A version may ADD a
    field, EDIT a field (same citationID, changed item data/result) and DELETE
    a field together with its visible citation text; it may never delete every
    live field at once, leave a field malformed (an unterminated begin, a
    stray field char, unparseable citation JSON, a missing/duplicate
    citationID), or replace a field by its plain-text result. A failure is an
    attempt error, so the retry policy hands the session another go with the
    exact fields it has to restore.

    Documents are paired by their version-token-free basename, so
    `...-mainText-181c700.docx` matches `...-mainText-<newtoken>.docx`. A
    document the agent did not deliver at all is left to the document-set /
    backfill layer, which restores the base bytes itself.
    """
    mod = _format_module()
    rep = {"label": label, "checked": 0, "documents": [], "errors": 0, "warnings": 0,
           "fields_before": 0, "fields_after": 0, "deleted": [], "plain_text": []}
    if mod is None or not hasattr(mod, "zotero_report_for_docx"):
        rep["skipped"] = f"{DOCX_FORMAT_MODULE} carries no field inventory"
        return rep
    if not (base_dir.is_dir() and out_dir.is_dir()):
        rep["skipped"] = "the base or the output directory is missing"
        return rep
    if errs is None:
        errs = []
    def doc_map(root: Path, gaps: list) -> tuple:
        """({pairing key: path}, collisions) for one side of the comparison.

        The version-token-free key pairs `manuscript-4f3a9c1.docx` with
        `manuscript.docx`, but two DIFFERENT documents can strip to one key
        (`appendix-a.docx` / `appendix-b.docx`): the dict comprehension kept
        only the last, so one document was never field-checked at all. The
        collision is reported instead of being silent.
        """
        out, seen = {}, {}
        for p in _fmt_corpus_files(root, gaps):
            key = _docx_field_key(p.relative_to(root).as_posix())
            seen.setdefault(key, []).append(p)
            out[key] = p
        clashes = {k: v for k, v in seen.items() if len(v) > 1}
        return out, clashes

    base_gaps, out_gaps = [], []
    base_docs, base_clash = doc_map(base_dir, base_gaps)
    out_docs, out_clash = doc_map(out_dir, out_gaps)
    rep["unreadable_dirs"] = {"base": sorted(set(base_gaps)),
                              "output": sorted(set(out_gaps))}
    if base_gaps or out_gaps:
        # A DOCX under an unreadable directory is invisible to the walk. The
        # continuity report must name it: otherwise it claims every document was
        # field-checked while one was never opened (F107).
        for _side, _gaps in (("base", base_gaps), ("output", out_gaps)):
            for _gap in sorted(set(_gaps)):
                _msg = (f"ZOTERO FIELD CONTINUITY: the {_side} directory {_gap!r} "
                        f"could not be read; its DOCX documents were NOT "
                        f"field-checked")
                warns.append(_msg)
                rep["warnings"] += 1
                # A skipped subsection is NOT a clean check: this gate fails only
                # on rep["errors"], so a warning alone let an unreadable base
                # directory pass the hard field gate with 0 errors (F063).
                errs.append(_msg)
                rep["errors"] += 1
    for side, clashes in (("base", base_clash), ("output", out_clash)):
        for key, paths in sorted(clashes.items()):
            warns.append(f"ZOTERO FIELD CONTINUITY: two {side} documents pair to one key "
                         f"({key!r}): {', '.join(p.name for p in paths)}; only "
                         f"{max(paths).name} is compared -- "
                         f"rename them so their names differ by more than a version token")
            rep["warnings"] += 1
    if not base_docs:
        if base_gaps:
            # Do not report "carries no DOCX" for a tree whose DOCX documents
            # were merely unreadable: that misstates the cause (F063).
            rep["skipped"] = ("the base's DOCX documents could not be read: "
                              + ", ".join(sorted(set(base_gaps))))
        else:
            rep["skipped"] = "the base carries no DOCX"
        return rep
    pairs = [(base_docs[k], out_docs[k]) for k in sorted(set(base_docs) & set(out_docs))]
    # A pairing-key collision (`appendix-a.docx` / `appendix-b.docx`) leaves one
    # of the documents out of the comparison entirely (the key maps to a single
    # path). Pair every colliding document whose counterpart carries the same
    # name, so a field deleted or garbled in the shadowed file is still caught;
    # the collision warning above still names the group.
    paired = {(b.resolve(), o.resolve()) for b, o in pairs}
    for key in sorted(set(base_clash) & set(out_clash)):
        for base in sorted(base_clash[key]):
            cand = [o for o in out_clash[key]
                    if o.name.lower() == base.name.lower()
                    and not any(p[0] == base.resolve() for p in paired)
                    and not any(p[1] == o.resolve() for p in paired)]
            if len(cand) == 1:
                pairs.append((base, cand[0]))
                paired.add((base.resolve(), cand[0].resolve()))
    rest_base = [base_docs[k] for k in sorted(base_docs) if k not in out_docs]
    rest_out = [out_docs[k] for k in sorted(out_docs) if k not in base_docs]
    # A stage may rename a document (a template stage hands back the template's
    # own file name). Exact name wins, then a unique document role, then the
    # sole remainder; a document the stage did not deliver at all is left to
    # the document-set/backfill layer, which restores the base bytes itself.
    for base in list(rest_base):
        exact = [o for o in rest_out if o.name.lower() == base.name.lower()]
        role = docx_document_role(base.name)
        # `docx_document_role` returns "main" for EVERY unrecognized name, so a
        # role of "main" cannot tell an explicit main manuscript from a deleted
        # `appendix.docx`. Pairing on it made a deletion look like a rename and
        # compared the wrong documents (F115); "main" renames are handled by
        # the sole-remainder fallback below.
        cands = exact or ([o for o in rest_out
                           if role and role != "main"
                           and docx_document_role(o.name) == role] if role else [])
        if len(cands) == 1:
            pairs.append((base, cands[0]))
            rest_out.remove(cands[0])
            rest_base.remove(base)
    if len(rest_base) == 1 and len(rest_out) == 1:
        pairs.append((rest_base[0], rest_out[0]))
    for base, out in pairs:
        before = mod.zotero_report_for_docx(base)
        after = mod.zotero_report_for_docx(out)
        cont = mod.zotero_field_continuity_problems(before, after)
        rel = out.relative_to(out_dir).as_posix()
        entry = {"file": rel, "baseline": base.relative_to(base_dir).as_posix(),
                 "fields_before": cont["baseline_fields"], "fields_after": cont["output_fields"],
                 "errors": cont["errors"], "warnings": cont["warnings"],
                 "deleted": cont["deleted"], "added": cont["added"], "edited": cont["edited"],
                 "plain_text": cont["plain_text"]}
        rep["checked"] += 1
        rep["fields_before"] += cont["baseline_fields"]
        rep["fields_after"] += cont["output_fields"]
        for msg in cont["errors"]:
            if not cont["plain_text"]:
                msg += (" -- restore the whole complex field (begin -> instrText -> separate -> "
                        "result -> end) from the base version, or delete the citation text with "
                        "it; see the $zotero-use DOCX reference")
            errs.append(f"ZOTERO FIELD CONTINUITY: {rel}: {msg}")
            rep["errors"] += 1
        rep["plain_text"].extend(cont["plain_text"])
        for msg in cont["warnings"]:
            warns.append(f"ZOTERO FIELD CONTINUITY: {rel}: {msg}")
            rep["warnings"] += 1
        rep["deleted"].extend(cont["deleted"])
        rep["documents"].append(entry)
    return rep


# ---------------------------------------------------------------------------
# Split out of `p06_postchecks.py`: the prior-audit observation readers.
# `PRIOR_AUDIT_ID_RE` stays in p06; the globals are shared at call time.
# ---------------------------------------------------------------------------


def _prior_audit_is_divider(cells) -> bool:
    """True for a markdown table's `|---|:--:|` divider row."""
    cells = [str(c or "").strip() for c in (cells or [])]
    # `_split_table_cells` keeps the empty cells outside the outer pipes.
    while cells and not cells[0]:
        cells.pop(0)
    while cells and not cells[-1]:
        cells.pop()
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", c) for c in cells)


def prior_audit_observation_lines(text: str) -> list:
    """The observation lines of `prior_audit/UNRESOLVED.md`, in file order.

    The recorded format is ONE line per observation (location + re-runnable
    evidence). Headings, blank lines, table separators and fenced blocks are
    structure, not observations; a leading list marker or number is stripped so
    the same observation yields the same text across rounds.

    A record written as a markdown TABLE is still a record: every data row of
    every `|` block is one observation. Skipping every line that starts with
    `|` (the old rule) returned [] for a table-form handoff, so the whole
    prior-audit record vanished from the convergence gate (F120).
    """
    rows, fence, table = [], None, []

    def flush_table() -> None:
        block, table[:] = list(table), []
        if not block:
            return
        cells_list = [_split_table_cells(line) for line in block]
        if len(cells_list) >= 2 and _prior_audit_is_divider(cells_list[1]):
            for cells in cells_list[2:]:
                row = " ".join(" ".join(str(c or "").split()) for c in cells).strip()
                if row and set(row) - set("| -:"):
                    rows.append(row)
            return
        # No divider: not a GFM table, but every `|` line still carries content.
        # Treat the lines as prose rather than dropping them silently.
        for line in block:
            s = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line).strip()
            if s and set(s) - set("| -:"):
                rows.append(s)

    for line in str(text or "").splitlines():
        s = line.strip()
        m = re.match(r"^(`{3,}|~{3,})", s)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            flush_table()
            fence = m.group(1)
            continue
        if s.startswith("|"):
            table.append(s)
            continue
        flush_table()
        if not s or s.startswith("#") or set(s) <= set("-:| "):
            continue
        s = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", s).strip()
        if s:
            rows.append(s)
    flush_table()
    return rows


def _prior_audit_index_rows(path: Path) -> list:
    """[(id, observation)] of the staged indexed view (`OBSERVATIONS.md`)."""
    out = []
    for block in parse_markdown_blocks(path):
        header = [str(h or "").strip().lower() for h in block["header"]]
        if "id" not in header:
            continue
        text_col = next((h for h in header if h in ("observation", "text", "line", "detail")), None)
        if text_col is None:
            continue
        for row in block["rows"]:
            oid = str(row.get("id") or "").strip().upper()
            if not PRIOR_AUDIT_ID_RE.fullmatch(oid):
                continue
            text = " ".join(str(row.get(text_col) or "").split())
            out.append((oid, text))
    return out


def prior_audit_observation_ids(sb: Path) -> list:
    """[(id, observation)] for the staged prior-audit record.

    `[]` when no record was staged. `None` when a staged record EXISTS but
    cannot be read (permissions, a link/FIFO, an over-budget file): that is
    UNKNOWN, not "the audit observed nothing", exactly as `prior_proposal_ids()`
    treats an unreadable prior-round file. An unreadable `UNRESOLVED.md` used to
    return [] and the disposition gate passed vacuously (F120).
    """
    dirp = Path(sb) / "prior_audit"
    # The indexed read-only view p05 stages is the authoritative id list (it is
    # what the review is told to cite), so prefer it when it is readable.
    idx = dirp / "OBSERVATIONS.md"
    p = dirp / "UNRESOLVED.md"

    def _staged_irregular(path: Path) -> bool:
        """True for a lexically present entry that is not a regular file.

        A directory, FIFO or symlink (including a BROKEN one, where exists() is
        false) is staged content that cannot be read -- UNKNOWN, never "no
        record staged" (F011).
        """
        try:
            st = path.lstat()
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return not stat.S_ISREG(st.st_mode)

    if _staged_irregular(idx) or _staged_irregular(p):
        return None
    if idx.is_file():
        rows = _prior_audit_index_rows(idx)
        if rows:
            return rows
    if p.is_file():
        text = read_text_bounded(p)
        if text is None:
            return None
        return [(f"AU-OBS-{i:03d}", line)
                for i, line in enumerate(prior_audit_observation_lines(text), 1)]
    if idx.is_file():
        return None
    return []


# ---------------------------------------------------------------------------
# Split out of `p07_stage_quality_journal.py`: the self-check helpers.
# ---------------------------------------------------------------------------


def _usable_deliverable(p: Path) -> bool:
    """Is this file worth ADOPTING into its canonical path?

    Non-empty, and (for JSON) parseable: a truncated file moved into place would
    only turn a "missing" failure into a "malformed" one, and the rescue exists
    to preserve work, not to shuffle garbage.
    """
    try:
        if not p.is_file() or p.stat().st_size == 0:
            return False
    except OSError:
        return False
    if p.suffix.lower() == ".json":
        return read_json(p, revive=False, lenient=True) is not None
    return True


def _selfcheck_artifact_policy(sb: Path) -> str:
    """The artifact policy the sandbox's enclosing run root recorded.

    The pre-flight has no `Ctx`; it must read the same recorded policy the
    postcheck's `strict_dispositions(ctx)` reads, or the two disagree (F113).
    A sandbox outside a run root keeps the documented default (`on`).
    """
    root = _enclosing_run_root(sb)
    if root is not None:
        cfg = read_json(root / "pipeline_config.json", revive=False, lenient=True)
        if isinstance(cfg, dict):
            raw = str(cfg.get("artifact_policy") or "").strip().lower()
            if raw in ARTIFACT_POLICIES:
                return raw
    return DEFAULT_ARTIFACT_POLICY


# =====================================================================
# LENIENT JSON RECOVERY
#
# Split out of p04_utils.py to keep every part under the documented
# 10,000-line limit (the 2026-11-22 fix-bugs wave pushed p04 over). Resolved at
# CALL time from the shared globals, so the later part position is irrelevant.
# =====================================================================

JSON_MAX_NESTING = 1000


def _json_from_text(text: str, lenient: bool):
    """Parse `text` as JSON, optionally recovering JSON embedded in prose.

    `lenient` is for AGENT-written files only. Models very often wrap the
    document they were told to write in a markdown fence (```json ... ```) or
    introduce it ("Here is the marker:"), which is not a content error -- the
    JSON is complete and unambiguous. Trying `raw_decode` at each `{`/`[` start
    token recovers exactly that document and nothing else: a TRUNCATED payload
    still fails to parse (the decoder demands the closing brace), and a document
    whose JSON is followed by lots of prose around it is not accepted unless the
    parsed value spans the text (`min_end` guard), so this cannot turn a
    half-written file into a pass.
    """
    text = text.lstrip("\ufeff")
    if not lenient:
        try:
            return json.loads(text)
        except (ValueError, RecursionError):
            # A deeply nested but valid JSON document raises RecursionError,
            # not ValueError: it is malformed AGENT OUTPUT for this pipeline's
            # purposes and must take the retry path, not crash the postcheck.
            return None
    decoder = json.JSONDecoder()
    total = len(text)
    # Only BALANCED values are document candidates. Trying every `{`/`[` made
    # a truncated payload quadratic. Top-level values are preferred; a value
    # that closes while an EARLIER, still-unmatched prose opener is on the
    # stack is kept as a fallback, so one literal "{" in the prose cannot hide
    # a complete JSON document that follows it (F13). The lists are separate
    # and bounded: counting nested values against one cap made a large ordinary
    # JSON document exceed the cap before its own closing brace.
    top_starts, nested_starts = [], []      # (start, end) / (start, end, outer_start)
    stack = []                              # (expected closer, start), innermost last
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(("}" if ch == "{" else "]", i))
            if len(stack) > JSON_MAX_NESTING:
                # The input byte cap bounds the FILE, not this scanner's
                # auxiliary stack: one tuple per unmatched opener made a 64 MiB
                # brace file allocate several GB during a lenient parse (F056).
                # Nothing this pipeline can parse nests this deep -- json.loads
                # itself raises RecursionError around the interpreter limit --
                # so a deeper stack is malformed agent input, not a document.
                return None
        elif ch in "}]":
            if stack and stack[-1][0] == ch:
                _closer, start = stack.pop()
                if not stack:
                    if len(top_starts) < 64:
                        top_starts.append((start, i + 1))
                elif len(nested_starts) < 64:
                    # `stack[0]` is the OUTERMOST still-open bracket: the opener
                    # this value is nested inside.
                    nested_starts.append((start, i + 1, stack[0][1]))
            elif stack:
                # Mismatched prose brackets: no value can start here.
                stack.clear()
    # Try BOTH candidate lists, in document order: an earlier `{}` in prose is
    # a complete top-level value, and it must not hide a later complete
    # document that closes while that prose opener is still unmatched.
    top_start_at = {s for s, _e in top_starts}
    starts = list(top_starts)
    for s, _end, outer in nested_starts:
        # A nested value is a FALLBACK for a stray prose opener, never a
        # replacement for the document itself (F86): an opener that is a
        # complete top-level value (the malformed `[{"a":1},]`) or that opens
        # the text -- bare or right after a markdown fence (the truncated
        # `[{"a":1}`, "```json\n[{"a":1}") -- is the document's own bracket,
        # so a complete child of it is a fragment, not the payload.
        prefix = text[:outer].strip()
        if (outer in top_start_at or not prefix
                or re.fullmatch(r"[`~]{3,}[^\n]*", prefix)):
            continue
        # The unmatched opener must be PROVABLY PROSE, not the truncated
        # document's own bracket. An opener directly followed by JSON syntax (a
        # key/`:` pair or a value token) opens a value of the half-written
        # document, so its complete child is a fragment: `Here is the
        # document:\n{"findings": [{"id": "F1"}]` used to return the child list
        # although the object never closed (F07). A prose opener (`prose {
        # unclosed then {"a":1}`) keeps the fallback, so one literal brace in
        # prose still cannot hide the document (F13/F86).
        gap = text[outer + 1:s].lstrip()
        if not gap or re.match(r'["\[\{\-0-9]|true\b|false\b|null\b', gap):
            continue
        starts.append((s, _end))
    starts = sorted(set(starts))
    found = []                       # (start, end, value)
    for i, _end in starts:
        try:
            obj, end = decoder.raw_decode(text, i)
        except (ValueError, RecursionError):
            continue
        found.append((i, end, obj))
    if not found:
        return None

    def outside_prose(i: int, end: int) -> int:
        """Text outside [i, end) that is not another candidate's own JSON.

        Counting an earlier candidate as prose is what let a trailing in-prose
        EXAMPLE outscore the payload that preceded it.
        """
        other = 0
        for s, e, _o in found:
            if (s, e) == (i, end):
                continue
            other += max(0, min(e, i) - s) + max(0, e - max(s, end))
        return max(0, total - (end - i) - other)

    # The document is the candidate that SPANS the text -- the LARGEST parsed
    # value, not merely the first `{` ("The schema is {"example": true}. And the
    # data is: {…}" returned the in-prose EXAMPLE) and not merely the last one
    # (a file ending in an example -- "… Note the schema example is {"example":
    # true}" -- returned the example). A value whose surrounding prose dwarfs it
    # is a fragment: "A"*1000 + '{...}' + "B"*1000 names an example, not a
    # document, and is still refused. A value that runs to the end of the text
    # is the document whatever precedes it (a fenced or introduced file); the
    # prose counted here is the text outside this value that is not another
    # candidate's own JSON, so a document carrying a nested object or a second
    # value is not penalized for either.
    best, best_key = None, None
    best_end = None
    rejected = []                    # (start, end) refused only by the prose test
    accepted = []                    # (start, end, obj)
    for i, end, obj in found:
        json_len = end - i
        tail = text[end:].strip()
        fenced = not tail or set(tail) <= set("`~")
        prose = outside_prose(i, end)
        # A short trailing EXAMPLE annotation does not make the value before it
        # a prose fragment: `{"a":1}\nNote: schema example is {…}` keeps the
        # document at the start (F30). Long arbitrary prose still disqualifies
        # it (a document buried in text is ambiguous).
        _tail_note = tail if len(tail) < 120 else ""
        _example_note = bool(re.search(
            r"(?i)\b(?:example|schema|sample|e\.g\.|for\s+instance)\b", _tail_note))
        if not fenced and prose > 2 * json_len and not _example_note:
            rejected.append((i, end))
            continue
        accepted.append((i, end, obj))
        # A value that runs to the end of the text is the document even when an
        # earlier top-level value is the same length: prefer it on a tie.
        key = (json_len, 1 if fenced else 0)
        if best_key is None or key > best_key:
            best, best_key, best_end = obj, key, end
    if best is not None and not text[best_end:].strip():
        # The winner runs to the end, so its `fenced` admission is what let it
        # through. When a LARGER complete candidate before it was rejected only
        # by the prose test, the tail is an in-prose EXAMPLE that must not be
        # returned as the document ("… Here is why. One row looks like
        # {"foo": 1}") -- report the ambiguity as malformed instead (F105).
        best_len = best_key[0] if best_key else 0
        best_start = best_end - best_len
        if any(s < best_start and (e - s) > best_len for s, e in rejected):
            return None
        # A trailing value introduced by an EXAMPLE marker ("Note: schema
        # example is {…}") is not the document when an earlier complete
        # candidate was accepted (F30).
        _prefix = text[:best_start]
        # Blank every earlier JSON value first: an "example" key INSIDE the
        # document must not be read as prose introducing the trailing value.
        for _s, _e, _o in accepted:
            if _e <= best_start:
                _prefix = _prefix[:_s] + (" " * (_e - _s)) + _prefix[_e:]
        _prefix = _prefix.rstrip()
        # The marker must introduce THIS value: a sentence boundary between
        # the marker and the value means it introduced an earlier sentence.
        _marker = re.search(r"(?i)\b(?:example|schema|sample|e\.g\.|for\s+instance)\b"
                            r"[^.!?\n]{0,40}$", _prefix[-120:])
        if _marker:
            _marker_start = len(_prefix) - len(_prefix[-120:]) + _marker.start()
            earlier = [c for c in accepted if c[1] <= best_start]
            # An earlier candidate can be the document the marker's value is an
            # example of only when it is ADJACENT to the marker: a fenced schema
            # block separated from the marker by fence syntax is itself an
            # example, not the document (R01). Among adjacent candidates the
            # LAST/largest is the document -- returning the earliest promoted a
            # leading schema example over the real one.
            _adjacent = [c for c in earlier
                         if c[1] <= _marker_start
                         and not re.search(r"[`~]", text[c[1]:_marker_start])]
            if _adjacent:
                return max(_adjacent, key=lambda c: (c[1], c[1] - c[0]))[2]
            if earlier:
                return best
            return None
    return best


# ---- shared postcheck gate helpers (fix-bugs wave 1; moved here to keep
# p06/p07 under the 10,000-line source cap) ----------------------------------

def _unable_reason_present(rest: str) -> bool:
    """True when an `unable -- ...` status states a reason (>= 2 words).

    The token list is case-insensitive: an all-caps reason ("HPC QUOTA
    EXCEEDED") is exactly as usable as a lowercase one, and the old
    `[0-9a-z]+` read it as no reason at all and failed a valid session.
    """
    text = " ".join(str(rest or "").split()).strip(" \t.;:,—–-")
    # `see above`, `N/A` and `all good` are not reasons why execution was
    # impossible (F08).
    if re.fullmatch(
            r"(?i)(?:n/?a|none|tbd|todo|see\s+(?:above|below|here|there|report|details?)|"
            r"as\s+(?:above|discussed|before|noted)|all\s+good|no\s+reason|unknown)",
            text):
        return False
    if _nowork_token_is_reason(text):
        return False
    return len(re.findall(r"[0-9A-Za-z]+", text)) >= 2


# A reason made only of generic approval/placeholder prose names no artifact,
# check or evidence. `lorem ipsum dolor sit amet`, `all good` and `no problems`
# passed every reason-bearing gate because each required only length or a few
# words (F12, 2026-11-23). This is the shared "common words only" test; a real
# reason keeps at least one token outside this vocabulary (a path, check id,
# location, quoted value or the object it examined).
_REASON_GENERIC_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_REASON_GENERIC_WORDS = frozenset("""
    a an the this that these those it its they them he she we you i
    is are was were be been being am do does did has have had
    and or but nor not no none all any some very quite pretty well
    for of to in on at as with by from into over under about
    ok okay good fine great excellent nice clean pass passed yes true false
    done checked check checks checking review reviewed verify verified test tested
    inspect inspected examined examine looked look seems seem appears appear
    find finding findings
    problem problems issue issues wrong nothing everything anything stuff misc
    things thing pending tbd todo n/a na
    lorem ipsum dolor sit amet consectetur adipiscing elit sed eiusmod tempor
    incididunt labore et dolore magna aliqua ut enim ad minim veniam quis
    nostrud exercitation ullamco laboris nisi aliquip ex ea commodo consequat
    foo bar baz qux quux asdf qwerty blah blahblah
    basis unable out of scope see above below here there discussed noted
""".split())


# `no problems found` / `no issues detected` are pure result closures: the
# `found` token was the only substantive-looking word, but it names no
# artifact or check. `examined, nothing found` stays a legitimate clean basis
# (it states the work that was done; the `clean` contract spells it out).
_GENERIC_RESULT_PHRASE_RE = re.compile(
    r"(?i)\b(?:no|zero)\s+(?:problems?|issues?|errors?|defects?|findings?)\s+"
    r"(?:found|detected|seen|identified)\b")


def _reason_is_generic_filler(text) -> bool:
    """True when `text` is made ONLY of generic approval/placeholder words."""
    raw = str(text or "")
    m = _GENERIC_RESULT_PHRASE_RE.search(raw)
    if m:
        # The closure is filler only when nothing outside it names the object
        # it examined; `no problems found in section 3` names section 3.
        rest = raw[:m.start()] + " " + raw[m.end():]
        rest_words = _REASON_GENERIC_WORD_RE.findall(rest.lower())
        if not rest_words or all(w in _REASON_GENERIC_WORDS for w in rest_words):
            return True
    words = _REASON_GENERIC_WORD_RE.findall(raw.lower())
    if not words:
        return True
    return all(w in _REASON_GENERIC_WORDS for w in words)


# An inability clause in a POSITIVE count's tail is evidence about one item
# (`3 findings; unable to see`), not approval filler: a finding count is a
# complete verdict and an inability in the EVIDENCE must not veto it (F01/F68).
# A ZERO count gets no such exemption -- `0 findings -- unable to check` names
# nothing and is refused by the count gate itself (F12).
_COUNT_TAIL_INABILITY_RE = re.compile(
    r"(?i)\b(?:unable|not\s+able|failed|could\s+not|couldn['\u2019]t|cannot|"
    r"can['\u2019]t)\s+to\s+\w+")


def _count_tail_is_filler(tail, count=None) -> bool:
    """A count form's tail must name a check/artifact, not just approval prose.

    A bare `none`/`no`/`zero`/`nothing` is the complete zero verdict and stays
    accepted (`0 findings; none`); `0 findings -- lorem ipsum` does not (R03).
    ``count`` (when the caller has it) lets a positive count keep an inability
    clause as evidence; the zero-count forms are refused by the caller's own
    negation gate.
    """
    t = str(tail or "").strip(" \t;:,.\u2014\u2013-")
    if not t:
        return False
    if re.fullmatch(r"(?i)(?:none|no|zero|nothing)", t):
        return False
    if count and _COUNT_TAIL_INABILITY_RE.search(t):
        return False
    return _reason_is_generic_filler(t)


def _is_recorded_reason(cell: str) -> bool:
    """Is this disposition cell a reason rather than a bare verdict word?

    Length alone is not a reason: `OK — see above` is 13 characters and names
    nothing, so the shared verdict/filler closure is applied too (F049).
    """
    text = re.sub(r"\s+", " ", str(cell or "")).strip()
    if len(text) < 12 or re.search(r"[A-Za-z]{3}", text) is None:
        return False
    if _disposition_filler_closure(text) or _reason_is_generic_filler(text):
        return False
    return True


# A cell that is ONLY a separator or a bare filler token ("-", "\u2014", "n/a",
# "none", "TBD") is an empty disposition, not a reason: the bare-closure test
# above fires only for verdict words, so a short table could be "disposed" with
# `-` and pass (F45). `m1b_rows_disposed` already reads these tokens as NOT
# disposed, and the gate must share that contract.
_DISPOSITION_FILLER_ONLY_RE = re.compile(
    r"(?i)^[-\u2014\u2013_.:,;\s]*(?:x+|n/?a|none|nil|null|tbd|todo)?"
    r"[-\u2014\u2013_.:,;\s]*$")


# A whole-cell no-work token is not a disposition, with or without a verdict
# prefix; `not attempted`/`pending` disposed every seeded row (F04). A
# verdict-prefixed anonymous pointer (`OK — see above for details`) names no
# row-specific reason either (F14).
_DISPOSITION_NOWORK_RE = re.compile(
    r"(?i)\b(?:pending|not\s+attempted|not\s+done|no\s+work\s+(?:was\s+)?done|"
    r"no\s+analysis\s+(?:was\s+)?performed|checked\s+nothing|"
    r"nothing\s+(?:was\s+)?(?:checked|done)|unable\s+to\s+(?:check|verify|review)|"
    r"did\s+not\s+(?:check|verify|review)|never\s+(?:checked|verified))\b")
_DISPOSITION_ANON_POINTER_RE = re.compile(
    r"(?i)\b(?:see\s+(?:above|below|here|there|report|details?)|"
    r"as\s+(?:discussed|above|before|noted|stated))\b")

# A no-work token is a disposition only when it IS the reason (or its whole
# tail): a named, evidence-bearing reason may mention the word ("the data are
# pending release by the consortium; see base/main.md:4") without recording
# that no work happened (R06). A named location is the documented evidence
# form, so its presence distinguishes the two.
_NOWORK_REASON_LOCATION_RE = re.compile(
    r"(?i)(?:[\w./\\-]+\.(?:md|txt|tex|docx|doc|json|csv|tsv|py|bib|pdf|"
    r"xlsx?|html?|xml|yaml|yml)(?::\d+(?:-\d+)?)?"
    r"|\bline\s*\d+|\bp{1,2}\.?\s*\d+\b|\bparagraph\s+\d+"
    r"|\bsec(?:tion)?\.?\s*\d+)")


def _nowork_token_is_reason(text: str) -> bool:
    """True when a no-work token IS the reason, not a clause naming evidence.

    `pending`, `not attempted` and `unable to check` record that no work
    happened and must be refused; `the data are pending release by the
    consortium; see base/main.md:4` names a location and is a real reason (R06).
    """
    text = str(text or "")
    if not (_COVERAGE_NOWORK_TOKEN_RE.search(text)
            or _DISPOSITION_NOWORK_RE.search(text)):
        return False
    return not _NOWORK_REASON_LOCATION_RE.search(text)


def _disposition_is_filler_only(cell: str) -> bool:
    """True for a disposition cell that is only a separator or a filler token."""
    return bool(_DISPOSITION_FILLER_ONLY_RE.match(str(cell or "").strip()))


def _disposition_filler_closure(cell: str) -> bool:
    """True for a verdict whose reason tail is only a separator or filler token.

    A whole cell that is a no-work token (`not attempted`, `pending`) or an
    anonymous pointer (`see above`) is filler even without a verdict prefix,
    and a verdict-prefixed anonymous pointer is filler too (F04/F14).
    """
    text = re.sub(r"\s+", " ", str(cell or "")).strip()
    if _reason_is_generic_filler(text):
        return True
    if _nowork_token_is_reason(text) or _DISPOSITION_ANON_POINTER_RE.search(text):
        return True
    m = _DISPOSITION_VERDICT_PREFIX_RE.match(text)
    if m is None:
        return False
    tail = text[m.end():].strip()
    return bool(tail) and bool(_DISPOSITION_FILLER_TAIL_RE.match(tail))


SEED_COVERAGE_REL = "concerns/SEED_COVERAGE.md"


def journal_seed_coverage_problems(sb: Path, seed: dict, rows: list,
                                   require_missing: bool = False) -> list:
    """One disposition per mechanical feedback candidate (seed block).

    The ledger checks each row it is GIVEN but never proved that every seed block
    was considered: a single valid item passed a letter with several demands
    (PR151-035). The session now records a coverage table (`S001...`, the ids the
    prompt shows) mapping each block to the concern rows it produced, or saying
    why it produced none. The parse is lenient about cell wording but strict
    about the seed-id set and about every named concern id existing.
    """
    candidates = [c for c in (seed.get("candidates") or []) if isinstance(c, dict)]
    seed_ids = [str(c.get("seed_id") or "").strip() for c in candidates]
    seed_ids = [x for x in seed_ids if x]
    if not seed_ids:
        if not require_missing:
            return []
        # Distinguish an ABSENT/unreadable seed (hard error: the coverage gate
        # was silently disabled) from a readable empty candidate list (F17).
        seed_path = Path(sb) / "feedback" / "CONCERN_SEED.json"
        if not seed_path.is_file():
            return ["feedback/CONCERN_SEED.json is missing: the per-candidate feedback "
                    "coverage gate cannot be verified"]
        raw_seed = read_json(seed_path, revive=False, lenient=True)
        if not isinstance(raw_seed, dict) or not isinstance(raw_seed.get("candidates"), list):
            return ["feedback/CONCERN_SEED.json cannot be read as the seeded candidate "
                    "ledger: the per-candidate feedback coverage gate is UNVERIFIED"]
        # A present candidate block whose entries carry no `seed_id` is NOT an
        # empty seed: treating it as one silently disabled per-candidate
        # coverage, so a renamed id key let a concern escape the letter (F17).
        raw_candidates = raw_seed.get("candidates") or []
        if raw_candidates:
            return ["feedback/CONCERN_SEED.json carries "
                    f"{len(raw_candidates)} candidate block(s) but no `seed_id`: the "
                    "per-candidate feedback coverage gate cannot match them"]
        return []
    p = Path(sb) / SEED_COVERAGE_REL
    if not p.is_file():
        return [f"{SEED_COVERAGE_REL} is missing: the feedback split {len(seed_ids)} candidate "
                f"block(s) and EACH needs a disposition row (its concern ids, or why it "
                f"produced none) -- one valid concern row does not prove the rest were read"]
    blocks = parse_markdown_blocks(p)
    if not blocks:
        return [f"{SEED_COVERAGE_REL} carries no table"]
    known = set(seed_ids)
    ledger_ids = {str(r.get("id")) for r in rows if isinstance(r, dict)}
    seen, problems = set(), []
    for block in blocks:
        header = [str(h).strip().lower() for h in block.get("header") or []]
        if not any("seed" in h for h in header):
            continue
        for row in block.get("rows") or []:
            sid = str(row.get("seed id") or row.get("seed") or "").strip()
            if not sid:
                problems.append(f"{SEED_COVERAGE_REL}: a coverage row has no seed id")
                continue
            if sid in seen:
                problems.append(f"{SEED_COVERAGE_REL}: seed id {sid!r} appears twice")
            seen.add(sid)
            if sid not in known:
                problems.append(f"{SEED_COVERAGE_REL}: {sid!r} is not a seeded candidate id")
                continue
            raw_ids = str(row.get("concern ids") or row.get("concerns") or "").strip()
            ids = [x.strip() for x in re.split(r"[,;]", raw_ids) if x.strip()
                   and x.strip().lower() not in ("—", "-", "none", "n/a")]
            disposition = str(row.get("disposition") or "").strip()
            low = disposition.lower()
            if low.startswith(("no concern", "skipped", "not-a-concern", "no demand")):
                # Strip the skip PREFIX before splitting: splitting the raw
                # `not-a-concern` on its hyphens left `a-concern` as the start
                # of the "reason", so the three-word bar was never enforced.
                _pref = re.match(
                    r"(?i)^(?:no concern|skipped|not-a-concern|no demand)\b", disposition)
                rest = disposition[_pref.end():] if _pref else disposition
                reason = re.split(r"[—–:\-]", rest, maxsplit=1)
                words = re.findall(r"\S+", reason[1] if len(reason) > 1 else "")
                if len(words) < 3:
                    problems.append(f"{SEED_COVERAGE_REL}: {sid} is skipped without a real "
                                    f"reason (at least three words after the dash)")
                if ids:
                    problems.append(f"{SEED_COVERAGE_REL}: {sid} is skipped but names "
                                    f"concern ids {', '.join(ids)}")
            elif ids:
                unknown = [x for x in ids if x not in ledger_ids]
                if unknown:
                    problems.append(f"{SEED_COVERAGE_REL}: {sid} names concern id(s) "
                                    f"{', '.join(unknown)} that the ledger does not carry")
            else:
                problems.append(f"{SEED_COVERAGE_REL}: {sid} names neither a concern id nor "
                                f"a skip disposition")
    missing = [x for x in seed_ids if x not in seen]
    if missing:
        problems.append(f"{SEED_COVERAGE_REL} does not dispose {len(missing)} seeded "
                        f"candidate(s): {', '.join(missing[:8])}")
    return problems

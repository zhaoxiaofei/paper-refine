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


MAX_TOOL_OUTPUT_BYTES = 16 * 1024 * 1024


class ToolOutputOverBudget(Exception):
    """A child process printed more than MAX_TOOL_OUTPUT_BYTES on one stream."""


def run_bounded(argv, timeout, cwd=None, env=None):
    """Run a child with stdout/stderr in temporary FILES, capped in size.

    `subprocess.run(..., stdout=PIPE)` accumulates every byte a verbose or
    malicious tool prints; the timeout does not bound memory (the 2026-10-28
    audit's F61). The files are read back only up to the budget, and an
    over-budget stream raises instead of allocating it.
    """
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        proc = subprocess.Popen(
            [str(a) for a in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=out_f, stderr=err_f)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
        out_f.seek(0, os.SEEK_END)
        out_size = out_f.tell()
        err_f.seek(0, os.SEEK_END)
        err_size = err_f.tell()
        if out_size > MAX_TOOL_OUTPUT_BYTES or err_size > MAX_TOOL_OUTPUT_BYTES:
            raise ToolOutputOverBudget(
                f"tool output over {MAX_TOOL_OUTPUT_BYTES} bytes "
                f"(stdout={out_size}, stderr={err_size})")
        out_f.seek(0)
        err_f.seek(0)
        out = out_f.read(MAX_TOOL_OUTPUT_BYTES + 1)
        err = err_f.read(MAX_TOOL_OUTPUT_BYTES + 1)
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
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError, RuntimeError,
            NotImplementedError):
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

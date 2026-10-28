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
    multi-file manuscript was reported as 0 body words (F36). Includes expand
    once (cycle-safe); comments are stripped first; an unresolved include is
    named as a gap by the caller.

    `source` is the file `text` was read from. It is seeded into `seen`: an
    a -> b -> a cycle returns to the ROOT, which is not a child and so was
    expanded a second time before the include was suppressed (the 2026-10-28
    audit's F02). `_stack` carries the text of every frame being expanded, so
    even a direct caller that does not know the root's path still stops a cycle
    when the same source text is re-entered.
    """
    seen = set() if seen is None else seen
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
        return _tex_expand_includes(child_text, base, seen, source=child,
                                    _stack=stack)

    try:
        return TEX_INCLUDE_RE.sub(repl, body)
    finally:
        stack.pop()

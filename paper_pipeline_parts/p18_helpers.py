# -*- coding: utf-8 -*-
# Part 18/20 of the pipeline -- executed by the loader AFTER the command
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


# =====================================================================
# `--only`: the ROUND/STAGE/SESSION selection grammar
#
# Moved here from p04_utils.py, which is capped at 10,000 lines by the
# source-layout contract. The grammar resolves a `--only`/`--runs` item into
# rounds, stage classes and session tokens; `ONLY_STAGES`, `ONLY_ALIASES` and
# `ONLY_STAGE_GROUPS` (p02) are read at CALL time, so the split is invisible.
# =====================================================================


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
                f"pipeline is configured with --rounds {R} (rounds are 1-based)")
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
    else:
        text = str(raw).strip()
        parts = re.split(r"[,\s]+", text)
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
                           r"rewriter\d+|reviser\d+|integrator\d+)((?:[_:/.-](?:b|j\d+))?)",
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
                              r"integrator\d+|integrate\d+)(?:[_:/.-]j\d+)?", stage_token):
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
    return spec if spec else None


def _add_judge_selector(spec: "OnlySpec", r, session: str, part: str,
                        flag: str = "--only") -> None:
    """Record one JUDGE-session selector on an OnlySpec (`r` None = every round).

    The round's judge stage is implied (the selector is a WHITELIST of its
    sessions), and the round filter picks up a round-qualified item so
    `--only r1_judge_w2_j1` never looks at the other rounds.
    """
    if r is not None and int(r) < 1:
        die(f"{flag}: {part!r} names round {r}; rounds are 1-based")
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
                f"{ctx.root}` to see the ones that exist here.")
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
        die(f"{flag}: {part!r} names round {r}; rounds are 1-based")
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
            f"(use `reviser1` for the first reviser, which edits a1 into a2)")
    if not re.fullmatch(r"(?:w\d+|a\d+|i\d+|guided_review|guided_review_b|"
                        r"cold_start_review|audit|feedback|concerns|response)", sid):
        die(f"{flag}: {part!r} is not a session this pipeline knows (use a stage name, or a "
            f"session such as `rewriter1`, `reviser1`, `integrator1`, `review`, `audit`, `w2`, "
            f"`w2_j1`, `r1_w2`, `r1_judge_w2_j1`)")
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
        f"stage, or a session such as `r1_judge_w2_j1`, `w2_j1`, `integrator2_j1` or `judge1`)")


def _session_token(raw: str, part: str, flag: str = "--only") -> str:
    """Normalize one session token: `rewriter2` -> `w2`, `reviser1` -> `a2`, ...

    The friendly class+index spellings the operator is most likely to type are
    mapped onto the pipeline's own version ids. An empty token is refused with
    the spellings that always work.
    """
    tok = str(raw).strip().strip("_:/.-").lower().replace(" ", "")
    if not tok:
        die(f"{flag}: {part!r} names no session (use a stage name, or a session such as "
            f"`rewriter1`, `integrator2`, `w2`, `r1_w2` or `r1_judge_w2_j1`)")
    m = re.fullmatch(r"(rewriter|writer|w)(\d+)", tok)
    if m:
        return f"w{int(m.group(2))}"
    m = re.fullmatch(r"(reviser|revise|a)(\d+)", tok)
    if m:
        # The pipeline numbers its revise arms a2, a3, ... (a1 is the base copy),
        # so reviser N is the a{N+1} arm.
        return f"a{int(m.group(2)) + 1}"
    m = re.fullmatch(r"(integrator|integrate|i)(\d+)", tok)
    if m:
        return f"i{int(m.group(2))}"
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
                f"(use `reviser1` for the first reviser, which edits a1 into a2)")
        if tok == "orig":
            die(f"{flag}: {part!r} names the pristine original, which has no agent session")
        return tok
    die(f"{flag}: {part!r} is not a session this pipeline knows (use a stage name, or a session "
        f"such as `rewriter1`, `reviser1`, `integrator1`, `guided_review`, `audit`, `w2`, `w2_j1`, "
        f"`r1_w2`, `r1_judge_w2_j1`)")


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


def parse_only_stages(raw) -> set:
    """The STAGE side of `--only` (`run --only rewrite,review,merge`).

    Kept for the stage-only callers and tests: None/empty/`all` selects every
    stage (the default). A round-qualified item (`2:review`) contributes its
    stage; the round filter itself lives in parse_only_spec(), which is what the
    `run` command uses.
    """
    spec = parse_only_spec(raw)
    return spec.stage_filter() if spec else set()

# -*- coding: utf-8 -*-
# Part 22/24 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
# Session continuation: capture the CLI session id, build its resume argv, decide
# whether an unfinished attempt may continue, and write the continuation prompt.
# Also carries the audit coverage/disposition gates, moved here when p07 crossed
# the repository's 10,000-line limit (2026-11-22 wave).
#
# Split out of `p06_postchecks.py` when that part crossed the repository's
# 10,000-line limit. The parts are executed in filename order into the same
# globals, so these functions see every `p06` constant/helper and `p08` calls them
# after all parts have loaded.
#
# NO module docstring here: `_load_parts()` execs each part into the loader's
# globals, and exec stores the part's docstring in `__doc__`; a docstring in
# this (last) part overwrote `paper_pipeline.__doc__`, breaking the module
# docstring/CR1a check.
from __future__ import annotations

# =====================================================================
# CONTINUATION OF A STOPPED SESSION (`codex exec resume <session-id>`)
# =====================================================================
def capture_agent_session_id(ctx: Ctx, rec: dict) -> str:
    """The CLI session id of the attempt whose transcript is in this sandbox.

    The agents print `session id: <uuid>` in their banner (codex does; a claude
    build that prints one is picked up the same way), a claude
    `--output-format json` run reports it in its result object, and `dsh --json`
    opens its event stream with `"sessionId": "session-<uuid>"`;
    `_execute_attempt_in` tees every one of them into `_agent.log`, so the id a
    CONTINUATION needs is already on disk -- no extra channel and no guessing
    from timestamps. The LAST id in the file wins (the transcript is appended
    per attempt), whichever of the three forms it was written in.
    """
    try:
        sb = ctx.sandbox_of(rec)
    except Exception:                                            # noqa: BLE001
        return ""
    log = sb / "_agent.log"
    # The transcript is append-only and can exceed the shared read budget after
    # two long attempts; the LAST id is at the END, so read a bounded TAIL
    # instead of treating an over-budget file as empty (F065).
    try:
        with _open_regular_no_follow(log) as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 16 * 1024 * 1024))
            text = fh.read(16 * 1024 * 1024).decode("utf-8", "replace")
    except OSError:
        return ""
    if not text:
        return ""
    hits = [(m.start(), m.group(1))
            for pattern in (SESSION_ID_RE, DSH_SESSION_ID_RE)
            for m in pattern.finditer(text)]
    hits.sort()
    if hits:
        return str(hits[-1][1])
    # dsh emits its `sessionId` ONCE at the HEAD of the NDJSON stream; a log
    # over 16 MiB lost it entirely because only the tail was scanned (F047).
    # Fall back to the first 64 KiB (the id is at the stream head) and prefer
    # the last id on that side.
    try:
        with _open_regular_no_follow(log) as fh:
            head = fh.read(64 * 1024).decode("utf-8", "replace")
    except OSError:
        return ""
    head_hits = [(m.start(), m.group(1))
                 for pattern in (SESSION_ID_RE, DSH_SESSION_ID_RE)
                 for m in pattern.finditer(head)]
    head_hits.sort()
    return str(head_hits[-1][1]) if head_hits else ""


def resume_argv_for(cmd: list, session_id: str) -> list:
    """The argv that CONTINUES `session_id` with the same backend ([] if none).

    codex:  `codex exec <overrides> -`  ->  `codex exec resume <id> <overrides> -`
            (the prompt still arrives on stdin; note that `resume` accepts no
            `-s/--sandbox` -- it reuses the policy recorded in the session)
    claude: `claude --permission-mode ... --print` -> the same argv plus
            `--resume <id>` (or `--continue`, which resumes the most recent
            conversation of THIS directory -- every run has its own sandbox, so
            that is this run's session -- when no id was captured)
    dsh:    `dsh --profile headless --json -` -> the same argv plus
            `--session-id <id>`, inserted BEFORE the `-` task positional (the
            one-shot app reads its task from stdin and requires `-` to be its
            only positional, and the id must be exact: an unknown one is an
            error, so a continuation can never silently start a fresh session)
    Anything else (a custom --agent-cmd/PAPER_AGENT_CMD) has no known resume form
    and is left alone HERE: `resume_gate` then continues the stage in the SAME
    sandbox with its own command as a fresh process (every artifact on disk
    survives; only the chat transcript does not), instead of rebuilding the
    sandbox and paying for the work again.
    """
    argv = [str(x) for x in (cmd or [])]
    if not argv:
        return []
    name = Path(argv[0]).name.lower()
    if name.startswith("codex") and len(argv) > 1 and argv[1] == "exec":
        if not session_id:
            return []                    # `resume --last` is GLOBAL: too risky in parallel
        return [argv[0], "exec", "resume", session_id, *argv[2:]]
    if name.startswith("claude"):
        return [*argv, *(["--resume", session_id] if session_id else ["--continue"])]
    if name.startswith("dsh"):
        if not session_id:
            # No `--continue` equivalent: the harness persists many sessions and
            # adopts one only by exact id, which is precisely the continuation
            # we want -- a fresh session would answer the continuation prompt
            # with no memory of the work it is supposed to finish.
            return []
        if argv[-1] == "-":
            return [*argv[:-1], "--session-id", session_id, "-"]
        return [*argv, "--session-id", session_id]
    return []


def resume_unfinished_reason(ctx: Ctx, rec: dict) -> str:
    """Why this failed attempt looks UNFINISHED ("" = it finished and was rejected).

    Only an unfinished attempt is a continuation candidate: a stage that wrote
    its deliverables and was rejected on their content is the retry/repair path's
    business. The signature is (a) a process-level failure (timeout, killed CLI)
    or (b) a postcheck error that names a deliverable which does NOT exist.
    """
    if rec.get("status") != "failed":
        return ""
    errors = [str(e) for e in ((rec.get("postcheck") or {}).get("errors") or [])]
    if not errors:
        if rec.get("last_error"):
            return ("the agent process failed before the attempt could be judged: "
                    + str(rec["last_error"])[:120])
        return ""
    missing = repair_missing_deliverable(ctx, rec, errors)
    if missing:
        return f"the stage stopped before writing {missing}"
    return ""


def resume_gate(ctx: Ctx, rec: dict, cmd: list) -> tuple:
    """(argv, key, reason, mode): the continuation to run, or ([], key, "", "").

    `mode` is `"cli"` when the backend's OWN session is continued (`codex exec
    resume <id>`, `claude --resume`, `dsh --session-id`) and `"sandbox"` when it
    cannot be: a custom `--agent-cmd`/`PAPER_AGENT_CMD` has no resume form, and
    a resumed CLI session can only repeat an oversized context or a loop. A
    sandbox continuation runs the stage's own command again, as a FRESH
    process, in the SAME sandbox with the continuation prompt: every artifact
    on disk survives, so the stage resumes from its own files instead of the
    orchestrator throwing them away and paying for a rebuild.

    A failed attempt that looks UNFINISHED but cannot be continued at all still
    says so on the console, so the operator can tell "no continuation form",
    "the continuation limit is spent" and "the attempt finished and was
    rejected on its content" apart.
    """
    sid = str(rec.get("agent_session_id") or "")
    key = sid or "__continue__"
    reason = resume_unfinished_reason(ctx, rec)
    if not reason:
        return [], key, "", ""
    if not cmd:
        print(f"  [resume] {rec.get('id', '?')}: no continuation -- the stage "
              f"recorded no resumable command")
        return [], key, "", ""
    used = int((rec.get("resume_attempts") or {}).get(key) or 0)
    if used >= RESUME_ATTEMPT_LIMIT:
        why = (f"{used} continuation(s) already spent on this session "
               f"(limit {RESUME_ATTEMPT_LIMIT})")
        print(f"  [resume] {rec['id']}: no continuation -- {why}; a fresh attempt follows")
        return [], key, "", ""
    kind = str(rec.get("last_failure_kind") or "")
    if kind in {"context_overflow", "runaway"}:
        # `codex exec resume` resends the whole session, so a CLI continuation
        # of an oversized context (or of a loop) can only fail the same way.
        # A fresh process against the files on disk is a fresh context, which
        # is exactly what the stage needs; the continuation budget still bounds
        # how many times that can happen.
        why = ("the provider already rejected this session's request as too large"
               if kind == "context_overflow" else
               "the session was stopped for looping instead of finishing the stage")
        print(f"  [resume] {rec['id']}: the CLI session is not continued -- {why}; "
              f"continuing in the SAME SANDBOX with a fresh context (artifacts kept)")
        return list(cmd), key, reason, "sandbox"
    argv = resume_argv_for(cmd, sid)
    if not argv:
        print(f"  [resume] {rec['id']}: this backend has no CLI resume form; continuing "
              f"in the SAME SANDBOX with a fresh process (artifacts kept)")
        return list(cmd), key, reason, "sandbox"
    return argv, key, reason, "cli"


def resume_prompt(rec: dict, problems: list, reason: str, used: int,
                  author_to_complete: str = DEFAULT_AUTHOR_TO_COMPLETE,
                  resumed_cli: bool = True) -> str:
    """The CONTINUATION prompt: finish the stage's own work, marker last.

    `author_to_complete` is the run's hand-off policy: the escape item goes to
    THAT mode's manual-list file. The prompt was policy-blind and always said
    MANUAL_STEPS.md, the file the readme policy reserves for long-form detail
    (F17).

    `resumed_cli` says whether the CLI session itself was continued. When the
    backend has no resume form the orchestrator still continues in the SAME
    sandbox with a FRESH process (every artifact on disk survives); the chat
    transcript does not, so the prompt must not promise that it does.
    """
    manual_target = handoff_target(author_to_complete)
    listed = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(problems)) or "  (none recorded)"
    is_judge = str(rec.get("kind") or "") == "judge"
    # The judge is blind by design: its initial prompt carries no round, and its
    # postcheck accepts `scores.json` alone. The generic continuation revealed
    # the round and called the marker the ONLY signal -- two contradictions with
    # the prompt it resumes.
    where = (f"Run: {rec['id']}   stage: judge\n" if is_judge else
             f"Run: {rec['id']}   stage: {rec.get('kind')}   round: {rec.get('round')}\n")
    if resumed_cli:
        context_line = (
            "Your working directory is the same sandbox you were in, holding exactly the files "
            "you left; nothing was rebuilt and nothing was thrown away. Your context -- the "
            "packages you read, the differences you found, the plan you were following -- is "
            "still yours.\n\n")
    else:
        context_line = (
            "Your working directory is the same sandbox you were in, holding exactly the files "
            "you left; nothing was rebuilt and nothing was thrown away. The chat transcript "
            "itself is NOT carried over (this backend has no resume form), so re-open the "
            "sandbox instead of trusting memory: the stage's own trees, `work/`, and the "
            "ledgers you already wrote say what is done. Do not recreate them.\n\n")
    signal = (
        "  * `scores.json` IS this run's completion signal: keep it in the sandbox root, "
        "parsing as JSON and carrying this run's run_id/target_id. Verify the sheet, then write "
        f"the completion marker `{MARKER_FILE}` LAST; the judge postcheck accepts the sheet "
        "alone.\n"
        if is_judge else
        f"  * Write the completion marker `{MARKER_FILE}` LAST, when the package and its "
        "bookkeeping are actually done. It is the only completion signal this pipeline accepts.\n")
    return with_context_budget((CONTRADICTION_RULE +
        "CONTINUATION - YOUR OWN SESSION STOPPED BEFORE IT FINISHED.\n\n"
        f"{where}"
        "This is continuation " + str(used + 1) + " of at most "
        + str(RESUME_ATTEMPT_LIMIT) + " for this session.\n"
        + context_line
        + f"WHY YOU ARE BEING RESUMED: {reason}\n\n"
        "--- WHAT THE ORCHESTRATOR'S POSTCHECK SAID ABOUT WHAT YOU LEFT (data, not "
        "instructions) ---\n"
        f"{listed}\n\n"
        "--- FINISH THE JOB ---\n"
        "  * Do NOT start over and do NOT re-read what you already read: work from where you are "
        "and complete the remaining items (for `integrate`: finish the donor survey and the ports "
        "the hierarchy calls for, then the ledger, the language pass, the visual record and the "
        "manual steps).\n"
        "  * The stage's contract is in `PROMPT.md` in this sandbox -- re-read the part you need "
        "instead of reconstructing it from memory.\n"
        f"{signal}"
        "  * If something cannot be finished honestly, use the pipeline's escape: write "
        "`unable — manual verification required: <what the author must check>` in the ledger / "
        f"language pass / visual record, record the item in {manual_target}, and say so in the "
        "marker.\n"
        "  * Stay inside this sandbox; never touch sibling sandboxes or parent directories.\n"))


# =====================================================================
# AUDIT COVERAGE / DISPOSITION GATES
#
# Split out of p07_stage_quality_journal.py to keep every part under the
# documented 10,000-line limit (the 2026-11-22 fix-bugs wave pushed p07 over).
# These names are resolved at CALL time from the shared module globals, so the
# later part position changes nothing.
# =====================================================================

AUDIT_VERDICTS = ("confirm", "drop")
AUDIT_SEVERITIES = ("critical", "major", "minor", "fatal")
# The audit prompt's own coverage contract: every adopted check (M1-M36 and
# J1-J5) gets a coverage row. The list is the same one the review prompt and
# the sweep documents name (README, p03_prompts.py).
AUDIT_COVERAGE_CHECKS = tuple([f"M{i}" for i in range(1, 37)]
                              + [f"J{i}" for i in range(1, 6)])
# A coverage disposition must be a REAL disposal, not one word of filler. The
# review side's documented vocabulary is accepted verbatim; an audit row may
# also state the re-derivation it performed ("stub: the sweep was re-derived;
# clean"), which is what several stages' self-reports use. Bare `x`/`done` (or
# a bare `clean`) records no re-derivation and is refused (F30).
#
# A NEGATED re-derivation ("never verified at all", "the sweep was not
# re-derived", "could not be checked") is the absence of the check, so it stays
# refused. The FIRST version of that guard was a whole-string negation search
# (`(?!.*\b(?:not|never|cannot|unable to)\b)`), which rejected any true row
# whose EVIDENCE happened to contain one of those words: the 2026-11-01 audit
# lost an entire 39-minute attempt on
#   "F-002, ... confirmed (...); X-910 confirmed (CI does not contain point estimate)"
# and on "F-030 confirmed (...); X-949 dropped (... not a defect)". The negation
# is only disqualifying when it GOVERNS THE VERB, so `_AUDIT_NEGATED_VERB_RE`
# matches a negation, at most two words, and then the re-derivation verb; the
# gate rejects a cell only when that phrase occurs. A negation elsewhere in the
# sentence is evidence, not a missing check.
#
# The verdict may be preceded by a qualifier: "No cover letter in submission;
# no findings" and "No rendered artwork files in corpus; unable to check
# artwork/text parity" were refused by the anchored match although both are
# real dispositions. Every shape is therefore searched anywhere in the cell,
# while bare filler ("x", "done", "not checked") still matches nothing.
#
# `No findings ...` is the same verdict as `0 findings` and `unable to check X`
# the same verdict as `unable -- <reason>`; both spellings are accepted, and the
# reason-bearing ones still pass the shared filler gate in `_audit_disposition_ok`.
_AUDIT_REDERIVATION_VERB = (
    r"(?:re-?derived|confirmed|checked|verified|re-?derive|confirm|check|verify|"
    r"review(?:ed)?)")
_AUDIT_NEGATED_VERB_RE = (
    r"\b(?:not|never|cannot|can\s+not|could\s+not|unable\s+to|no\s+longer)\b"
    r"(?:\s+\w+){0,2}\s+" + _AUDIT_REDERIVATION_VERB + r"\b")
_AUDIT_COUNT_RE = re.compile(r"(?i)(?:\b\d+\s+finding|\bno\s+finding)")
_AUDIT_CANONICAL_TAIL_RE = re.compile(
    r"(?i)(?:clean\s*(?:--|—|–)\s*basis\s*:\s*"
    r"|unable\s*(?:--|—|–)\s*"
    r"|out\s+of\s+scope\s*(?:--|—|–)\s*)(.*)$")
_AUDIT_VERB_RE = re.compile(r"(?i)\b" + _AUDIT_REDERIVATION_VERB + r"\b")
_AUDIT_NEGATED_VERB_COMPILED = re.compile(_AUDIT_NEGATED_VERB_RE, re.I)
_AUDIT_PROSE_UNABLE_RE = re.compile(r"(?i)\bunable\s+to\s+(.*)$")
# A re-derivation sentence must NAME what was re-derived or on what basis; a
# one-word verb (`checked`, `confirmed`) records no object and is filler (F128).
# A check id, a finding id or a named artifact satisfies that bar on its own.
_AUDIT_NAMED_BASIS_RE = re.compile(
    r"(?i)\b(?:[MJ]\d{1,2}|(?:F|X|AU)-\d+)\b"
    r"|\b[\w-]+\.(?:md|markdown|json|txt|tex|docx|csv|pdf)\b")
# F40: an inability must NAME an object or a reason. The old prose test counted
# six alphanumeric characters after "unable to", so the bare verb plus a
# determiner ("unable to check the", "unable to verify the") passed although it
# names nothing; `_coverage_reason_named` likewise accepted `unable -- the`.
# A reason/object therefore has to carry one CONTENT word (not a determiner,
# pronoun, auxiliary or preposition), and a prose inability has to name one
# after its verb.
_AUDIT_FILLER_WORDS = frozenset("""
    a an the this that these those it its they them their there here some any all
    both each other another such own same so than then to of in on at by for with
    from into onto over under about after before as and or but nor if while when
    where which who whom whose what is are was were be been being am do does did
    doing have has had having will would shall should may might must can could not
    no none nothing nor too very also just only
""".split())
_AUDIT_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-/]*")
# The verb that follows "unable to": it is the action, not its object, so the
# object test strips it before asking whether anything is named.
_AUDIT_PROSE_VERB_RE = re.compile(
    r"(?i)^(?:re-?derive|re-?derived|confirm|confirmed|check|checked|verify|verified|"
    r"review|reviewed|inspect|inspected|examine|examined|run|perform|performed|"
    r"read|see|tell|assess|assessed|compare|compared|render)\b")
# F01/F68: the count form answers the count first, but a count whose own tail
# says the CHECK ITSELF did not run is not a verdict (`0 findings; the sweep
# could not run`, `3 findings; the pass wasn't run`). A negation whose SUBJECT is
# one item or one finding/check id is an EVIDENCE clause (`3 findings; unable to
# check one quoted line`, `3 findings; X-910 could not be re-derived`) and must
# not veto a legal count -- that is the F68 shape the whole-cell veto broke.
_AUDIT_CHECK_SUBJECT_RE = re.compile(
    r"(?i)\b(?:sweep|pass|check|review|audit|scan|re-?derivation|verification|"
    r"coverage|table|session|attempt)\b")
# A count whose tail records NO work at all ("the sweep was skipped",
# "we could not check anything", "nobody looked") is not a disposition, even
# though none of the negated-verb spellings above matches it (F001/F005).
_AUDIT_NO_WORK_RE = re.compile(
    r"(?i)(?:\b(?:skip(?:ped|s)?|deferred?|postponed?|not\s+attempted|tbd|todo)\b"
    r"|\b(?:never|nobody|no\s+one)\s+(?:looked|checked|reviewed|examined|verified|"
    r"inspected)\b"
    r"|\bdid\s+not\s+happen\b"
    r"|\b(?:work|check|sweep|pass|review|audit|scan)\s+(?:was|were|is|are)\s+"
    r"(?:not\s+(?:done|performed|run|completed)|skipped|deferred)\b"
    r"|\b(?:could|can)\s+not\s+(?:check|verify|review|examine|inspect)\s+anything\b)")
_AUDIT_COUNT_NEGATION_RE = re.compile(
    r"(?i)\b(?:not|never|without|could\s+not|cannot|did\s+not|was\s+not|were\s+not|"
    r"has\s+not|have\s+not|is\s+not|are\s+not)\b"
    r"[^.;\n]{0,25}?\b(?:run(?:s|ning)?|execut(?:e|ed|ing)?|perform(?:ed|s|ing)?|"
    r"check(?:ed|s|ing)?|verif(?:y|ied|ies)|re-?deriv(?:e|ed)?|examin(?:e|ed|ing)?|"
    r"review(?:ed|s|ing)?|inspect(?:ed|s|ing)?)\b")

AUDIT_COVERAGE_DISPOSITION_RE = re.compile(
    # A verdict shape anywhere in the cell (the leading `.*?` lets a qualifier
    # precede it).
    r"(?i)^(?:.*?(?:\b\d+\s+finding"
    r"|\bno\s+finding"
    r"|clean\s*(?:--|—|–)\s*basis\s*:\s*\S"
    r"|unable\s*(?:--|—|–)\s*\S"
    r"|out\s+of\s+scope\s*(?:--|—|–)\s*\S"
    # A prose inability that names an object ("unable to check artwork/text
    # parity"): the `unable --` dash form is preferred, but the same recorded
    # fact in a sentence is still a disposition, not filler.
    r"|unable\s+to\s+\w+\s+\S)"
    # ... or a re-derivation verb that no negation governs.
    r"|(?!.*?" + _AUDIT_NEGATED_VERB_RE + r")"
    r".*?\b" + _AUDIT_REDERIVATION_VERB + r"\b.*$)")


def _audit_negated_verb(text: str) -> bool:
    """Whether a negation governs the re-derivation verb in `text`.

    `_AUDIT_NEGATED_VERB_RE` listed only `not/never/cannot/can not/could
    not/unable to/no longer`, so a true refusal written with a contraction
    ("wasn't re-derived") or with punctuation between the negation and the verb
    ("was not, in fact, re-derived") was read as a POSITIVE re-derivation and
    accepted by the coverage gate (F06). Normalise contractions to their
    two-word form and the punctuation that separates the negation from the verb
    to spaces, then apply the same bounded-window match.
    """
    probe = re.sub(r"n['\u2019]t\b", " not", str(text or ""), flags=re.I)
    probe = re.sub(r"[,;:\u2014\u2013]", " ", probe)
    return bool(_AUDIT_NEGATED_VERB_COMPILED.search(probe))


def _audit_rederivation_named(text: str) -> bool:
    """Whether a re-derivation sentence names an object/basis (not a bare verb).

    `checked`, `confirmed`, `verified the` and `re-derived` are one- or two-word
    labels: they state that a verb was said, not what was re-derived or on what
    basis, so they are the filler shape the coverage gate must refuse. Three
    words ("checked all rows") or any check/finding id or named artifact file
    clears the bar.
    """
    stripped = str(text or "").strip()
    return len(stripped.split()) >= 3 or bool(_AUDIT_NAMED_BASIS_RE.search(stripped))


def _audit_names_content(text) -> bool:
    """Whether `text` carries a content word, not only determiners/auxiliaries."""
    return any(word.lower() not in _AUDIT_FILLER_WORDS
               for word in _AUDIT_WORD_RE.findall(str(text or "")))


def _audit_prose_names_object(tail) -> bool:
    """Whether `unable to <verb> <tail>` names an object after the verb (F40).

    `unable to check the` / `unable to verify the` name a determiner, and
    `unable to check` names nothing at all: both are filler, while
    `unable to check artwork/text parity` names the object it could not check.
    """
    rest = _AUDIT_PROSE_VERB_RE.sub("", str(tail or ""), count=1)
    rest = rest.strip(" \t.,;:-\u2014\u2013")
    # `unable to check x` names a one-letter object, which is filler exactly
    # like a bare `unable to check` (F082): require a real content token.
    return (_audit_names_content(rest)
            and len(re.findall(r"[A-Za-z0-9]", rest)) >= 3)


def _audit_count_tail_negates_check(text: str) -> bool:
    """Whether a count's own tail says the CHECK did not run (F01), not an item.

    A negated check whose subject is the check itself (the sweep/pass/check/
    review...), or that names no subject at all (`0 findings -- not checked`), is
    a non-run: the count in front of it is not a verdict. A negated check whose
    subject is one item or one id (`one location could not be verified`,
    `X-910 could not be re-derived`) is EVIDENCE about that item and must not
    veto a legal count (F68).
    """
    probe = re.sub(r"(?i)can['\u2019]t\b", "cannot", str(text or ""))
    probe = re.sub(r"n['\u2019]t\b", " not", probe, flags=re.I)
    for m in _AUDIT_COUNT_NEGATION_RE.finditer(probe):
        # Only the negation's OWN clause decides its subject; an earlier clause
        # ("0 findings; the check was clean ...") is not its subject.
        clause = re.split(r"[;,:()\u2014\u2013]|\s--?\s", probe[:m.start()])[-1]
        subject = _AUDIT_WORD_RE.findall(clause)[-4:]
        if not subject or _AUDIT_CHECK_SUBJECT_RE.search(" ".join(subject)):
            return True
    return False


def _audit_disposition_ok(value) -> bool:
    """A real audit coverage disposition (negation- and filler-proof).

    The regex alone accepts `unable -- no`, `clean -- basis: x` and a bare
    `out of scope`; those are the review gate's documented FILLER shapes, so
    route every reason-bearing form through the shared reason check
    (`_coverage_reason_named` knows the difference between a named
    artifact/reason and a one-letter or filler token). The prose equivalents get
    the same treatment: `unable to <verb> <object>` must name an object, not
    just the verb.

    THE SHAPES ARE TESTED IN ORDER, STRONGEST FIRST, and each shape accepts on
    its OWN evidence. Testing the prose-`unable` heuristic first let an inability
    clause in an EVIDENCE sentence veto a perfectly good count:
    `3 findings; unable to see` and `3 findings confirmed (the reviewer was
    unable to tell)` were refused because the tail after "unable to" was short.
    A finding count is a complete verdict, so it is answered first.
    """
    text = str(value or "").strip()
    if not AUDIT_COVERAGE_DISPOSITION_RE.match(text):
        return False
    if _reason_is_generic_filler(text):
        # `no findings` is the documented zero-count spelling and is made ONLY
        # of generic words, so the shared filler gate refused the very verdict
        # the prompt accepts as `0 findings`'s equivalent (F021). The count is
        # the evidence; only a filler TAIL is refused, exactly as the numeric
        # zero form is below.
        _zero = re.match(r"(?i)^\s*no\s+finding(?:s)?\b", text)
        if _zero is None or _count_tail_is_filler(text[_zero.end():], 0):
            return False
    if _AUDIT_COUNT_RE.search(text):
        # The count prefix itself is a complete verdict, but a TAIL made only
        # of generic filler (`0 findings -- lorem ipsum`, `0 findings; all
        # good`) names no check or artifact and is not a disposition (F12).
        # The tail is read with the SHARED helper: the hand-rolled strip
        # pattern put ".", "-" and the dashes in one class, which Python read
        # as a RANGE from "." through the em dash, so every letter of a
        # `;`/`:`/`,` tail was eaten and the filler check never saw it, while
        # a `--` tail kept its hyphens and refused the complete zero verdict
        # `0 findings -- none`. The coverage gate already had the right rule
        # (and the bare-none exemption); both gates now read a count tail the
        # same way.
        _count = re.match(r"(?i)^\s*(\d+)\s+finding(?:s)?\b", text)
        if _count is not None and _count_tail_is_filler(
                text[_count.end():], int(_count.group(1))):
            return False
        # A count is a complete verdict, so the WHOLE-CELL negation veto is
        # wrong in both directions (F01/F68). A tail that negates the check
        # itself (`0 findings; the sweep could not run`, `3 findings; the pass
        # wasn't run`) is refused; a tail that negates ONE item is evidence and
        # leaves the count standing (`3 findings; unable to check one quoted
        # line`). "nothing/nobody checked" names no negation verb at all, so the
        # shared no-work test is applied as well (F008). A ZERO count whose tail
        # carries a bare inability names no object and is not a verdict either
        # (`0 findings -- unable to check`).
        if (_COVERAGE_NOWORK_RE.search(text) or _AUDIT_NO_WORK_RE.search(text)
                or _audit_count_tail_negates_check(text)):
            return False
        if re.search(r"(?i)\b(?:0|zero|no)\s+finding", text):
            m = _AUDIT_PROSE_UNABLE_RE.search(text)
            if m is not None and not _audit_prose_names_object(m.group(1)):
                return False
        return True
    m = _AUDIT_CANONICAL_TAIL_RE.search(text)
    if m is not None:
        # `unable -- <why it could not run>` is the documented inability form;
        # its reason legitimately negates the check (F014), unlike `clean`.
        # The reason must NAME something: `unable -- the` is filler (F40).
        return (_audit_names_content(m.group(1))
                and _coverage_reason_named(
                    m.group(1),
                    allow_negated=bool(re.match(r"(?i)^\s*unable\b", text))))
    if _AUDIT_VERB_RE.search(text) and not _audit_negated_verb(text):
        # a re-derivation sentence, e.g. "the sweep was re-derived". A BARE
        # verb ("checked", "confirmed", "verified the") records no object and
        # no basis, so it is the filler shape this gate exists to refuse (F128):
        # a real disposition names what was re-derived, on what basis, or a
        # finding/check id (the same bar the other shapes meet).
        return _audit_rederivation_named(text)
    m = _AUDIT_PROSE_UNABLE_RE.search(text)
    if m is not None:
        # "unable to check artwork/text parity" names what could not be
        # checked; "unable to check" and "unable to check the" are filler (F40).
        return _audit_prose_names_object(m.group(1))
    if _AUDIT_VERB_RE.search(text) and _audit_negated_verb(text):
        # The coverage regex's negative lookahead only knows the literal
        # negation spellings; a contraction/punctuated negation reaches here and
        # must still be REFUSED (F06).
        return False
    return True              # the gate regex matched some other accepted shape

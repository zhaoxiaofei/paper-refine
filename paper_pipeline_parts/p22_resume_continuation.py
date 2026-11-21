# -*- coding: utf-8 -*-
# Part 22/23 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
# Session continuation: capture the CLI session id, build its resume argv, decide
# whether an unfinished attempt may continue, and write the continuation prompt.
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
    # The transcript is agent-written: the shared reader refuses a symlink and
    # applies the byte budget (F38).
    text = read_text_bounded(log)
    if not text:
        return ""
    hits = [(m.start(), m.group(1))
            for pattern in (SESSION_ID_RE, DSH_SESSION_ID_RE)
            for m in pattern.finditer(text)]
    hits.sort()
    return str(hits[-1][1]) if hits else ""


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

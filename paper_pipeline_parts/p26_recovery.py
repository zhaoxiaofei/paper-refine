# -*- coding: utf-8 -*-
# Part 26/26 of the pipeline -- executed by the loader, in order, in the
# loader's own module globals.
#
# Shared severity tiers, recovery records and the ``--fail-tier`` policy for
# paper-refine.  The engine (taxonomy, record schema, bounded retries, JSONL
# journal, markdown rendering) comes from the shared
# ``agent-common/agent_common/recovery.py`` module that both repositories
# mount; this part supplies the manuscript-specific diagnostics and the
# ``<resolved --root>/RECOVERY.md`` destination.
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent_common import recovery as _shared

RECOVERY_REPORT_FILENAME = "RECOVERY.md"
RECOVERY_STATE_DIRNAME = ".recovery"
RECOVERY_JOURNAL_FILENAME = "recovery.jsonl"

#: Commands that only read an existing root.  They must not create
#: RECOVERY.md (or anything else) in that root.
RECOVERY_READ_ONLY_COMMANDS = frozenset({"status", "trend", "agents", "selfcheck"})

#: Diagnostic catalogue: stable code -> (tier, recovery routine summary).
RECOVERY_CATEGORIES = {
    "CHECKS_SKIPPED": (
        _shared.TIER_INFO,
        "record the skipped verification, mark the output as not fully verified, continue.",
    ),
    "RUN_NOTE": (
        _shared.TIER_INFO,
        "record the note and continue the requested command.",
    ),
    "RETRY_ATTEMPT": (
        _shared.TIER_WARNING,
        "retry the affected session within its bounded attempt budget; the previous "
        "attempt's artifacts are preserved.",
    ),
    "OPTIONAL_CAPABILITY_DISABLED": (
        _shared.TIER_WARNING,
        "disable only the optional capability, record the resulting limitation, and "
        "continue the main revision.",
    ),
    "PARTIAL_RESULT": (
        _shared.TIER_WARNING,
        "keep the verified subset, mark the affected manuscript outputs PARTIAL, and "
        "list the omitted or unverified work for human review.",
    ),
    "RETRY_EXHAUSTED": (
        _shared.TIER_ERROR,
        "preserve all attempt artifacts, mark the affected stage and its outputs "
        "incomplete, and continue independent stages where the schedule allows.",
    ),
    "INPUT_UNREADABLE": (
        _shared.TIER_ERROR,
        "retry through the lenient decoder; on exhaustion skip the affected input and "
        "record it as an omission.",
    ),
    "OUTPUT_WRITE_FAILED": (
        _shared.TIER_ERROR,
        "retry through the atomic writer, then through the documented fallback; if both "
        "fail, keep the earlier output and mark this run's output incomplete.",
    ),
    "ROOT_UNUSABLE": (
        _shared.TIER_ERROR,
        "do not create or modify the root; write the recovery report to the documented "
        "fallback and report its location.",
    ),
    "REPORT_WRITE_FAILED": (
        _shared.TIER_WARNING,
        "retain the run in the incremental journal and write RECOVERY.md to the "
        "documented fallback; report the fallback location.",
    ),
    "COMMAND_REFUSED": (
        _shared.TIER_ERROR,
        "refuse the request, leave existing outputs unchanged, and report the reason "
        "for human review; no new output is claimed.",
    ),
    "RUN_VERDICT": (
        _shared.TIER_WARNING,
        "the command completed its work but stopped on a non-certified verdict (for "
        "example an incomplete decision or failed render); report the verdict, keep the "
        "written outputs, and require an explicit follow-up.",
    ),
    "UNEXPECTED_EXCEPTION": (
        _shared.TIER_CRITICAL,
        "preserve intermediate work and the journal, mark the affected stage and outputs "
        "incomplete, and report the failure for human review.",
    ),
    "SAFETY_GUARD_TRIPPED": (
        _shared.TIER_CRITICAL,
        "refuse the unsafe action, preserve the existing outputs, and pause for human "
        "intervention.",
    ),
}

#: Set by die() (p18_helpers) so main() can record a refusal with its message.
LAST_REFUSAL = None
_RECOVERY_SESSION = None


def recovery_code_tier(code: str) -> int:
    """Documented tier for a catalogue code (CRITICAL for an unknown code)."""
    return RECOVERY_CATEGORIES.get(code, (_shared.TIER_CRITICAL, ""))[0]


def recovery_diagnostic(code: str, operation: str, message: str, **context):
    """Build a shared Diagnostic using the catalogue tier for ``code``."""
    return _shared.Diagnostic(
        recovery_code_tier(code), code, operation, message, context=context
    )


def recovery_fail_tier_arg(value):
    """argparse type: a case-insensitive tier name or an integer rank 0..4."""
    try:
        return _shared.parse_fail_tier(value)
    except _shared.FailTierError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def recovery_root_for(args) -> Path:
    """Resolve ``--root`` exactly as the commands do (``Path(...).resolve()``)."""
    raw = getattr(args, "root", None)
    if raw is None:
        return Path.cwd()
    # Match every command's own resolution (`Path(args.root).resolve()`); in
    # particular do NOT expand ``~`` here, or the report would land somewhere
    # different from the root the command actually used.
    return Path(str(raw)).resolve()


def _probe_writable(directory):
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / (".write-probe-%s" % os.getpid())
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def recovery_fallback_root() -> Path:
    """The documented fallback when ``<root>/RECOVERY.md`` cannot be written.

    The first writable candidate wins: ``$PAPER_RECOVERY_FALLBACK_DIR``,
    ``~/.cache/paper-refine/recovery``, then a temporary directory.
    """
    import tempfile

    configured = os.environ.get("PAPER_RECOVERY_FALLBACK_DIR")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    try:
        cache = os.environ.get("XDG_CACHE_HOME")
        candidates.append(
            (Path(cache).expanduser() if cache else Path.home() / ".cache")
            / "paper-refine"
            / "recovery"
        )
    except (OSError, RuntimeError):
        # A home-less/daemon account must still get a writable fallback.
        pass
    candidates.append(Path(tempfile.gettempdir()) / ".paper-recovery")
    for candidate in candidates:
        if _probe_writable(candidate):
            return candidate
    return Path(tempfile.gettempdir()) / ".paper-recovery"


class PaperRecovery:
    """One invocation's recovery session and its ``RECOVERY.md`` destination.

    Example: ``PaperRecovery(root, fail_tier, "run", argv).start()`` writes an
    in-progress section to ``<root>/RECOVERY.md`` and journals every event.

    Counterexample: constructing a session for ``status`` would modify a root
    that the read-only command promised not to touch.
    """

    def __init__(self, root, *, fail_tier, command, argv=(), run_id=None, persist=True):
        self.root = Path(root).resolve()
        self.fail_tier = _shared.parse_fail_tier(fail_tier)
        self.policy = _shared.FailurePolicy(self.fail_tier)
        self.command = str(command)
        self.argv = list(argv)
        self.run_id = run_id or _shared.new_run_id("paper")
        self.persist = persist
        self.run_dir = None
        self.fallback_dir = recovery_fallback_root() / self.run_id
        self.journal = _shared.RecoveryJournal(
            self.fallback_dir / "journal",
            self.run_id,
            fallback_directory=self.fallback_dir,
            filename=RECOVERY_JOURNAL_FILENAME,
        )
        # `setup` must not write into a root it has not yet validated (a
        # non-empty directory is a valid refusal case). It starts on the
        # fallback report and moves to the root report only in bind_root(),
        # after setup has created a real root.
        if self.command == "setup":
            self.report = _shared.MarkdownReport(
                self.fallback_dir / RECOVERY_REPORT_FILENAME,
                title="Recovery report (setup)",
            )
        else:
            self.report = _shared.MarkdownReport(
                self.root / RECOVERY_REPORT_FILENAME,
                fallback_path=self.fallback_dir / RECOVERY_REPORT_FILENAME,
                title="Recovery report",
            )
        self.controller = _shared.RecoveryController(
            run_id=self.run_id,
            policy=self.policy,
            journal=self.journal,
            report_callback=self._refresh_in_progress,
            logger=self._log,
        )
        self.status = "in_progress"
        self.started = False
        self.finalized = False
        self._bound = False
        self.last_report_path = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Start the journal and mark any earlier interrupted run."""
        metadata = {
            "tool": "paper-refine",
            "command": self.command,
            "argv": self.argv,
            "root": str(self.root),
            "fail_tier": _shared.TIER_NAMES[self.fail_tier],
            "fail_tier_rank": self.fail_tier,
        }
        ok = self.journal.start(metadata)
        self.started = True
        try:
            self.report.mark_interrupted(self.run_id)
        except _shared.ReportWriteError as exc:
            self._audit_alert("REPORT_READ_FAILED", exc)
        self._refresh("IN PROGRESS")
        return ok

    def bind_root(self) -> bool:
        """Move the journal into ``<root>/.recovery`` when the root exists.

        The root is never created here: a mistyped ``--root`` must stay a
        missing path, not become an empty pipeline root.  When the root does
        exist (the normal ``run``/``decide`` case, or a successful ``setup``),
        the journal moves under it and ``RECOVERY.md`` moves to the root.
        """
        if self._bound or not self.persist:
            return False
        if not self.root.is_dir():
            return False
        # Only a real pipeline root may receive a report. A random existing
        # directory passed as --root (including a non-empty directory that
        # `setup` is about to refuse) must not be polluted with .recovery/.
        looks_like_root = (
            (self.root / "pipeline_config.json").is_file()
            or (self.root / "state.json").is_file()
        )
        if not looks_like_root:
            return False
        previous = self.journal.records()
        primary = self.root / RECOVERY_STATE_DIRNAME
        self.journal = _shared.RecoveryJournal(
            primary,
            self.run_id,
            fallback_directory=self.fallback_dir,
            filename=RECOVERY_JOURNAL_FILENAME,
        )
        self.journal.start(
            {
                "tool": "paper-refine",
                "command": self.command,
                "root": str(self.root),
                "fail_tier": _shared.TIER_NAMES[self.fail_tier],
                "fail_tier_rank": self.fail_tier,
                "resumed_from_fallback": str(self.fallback_dir),
            }
        )
        existing = {str(item.get("event_id")) for item in self.journal.records()}
        for record in previous:
            if str(record.get("event_id")) not in existing:
                self.journal.append(record)
        self.controller.journal = self.journal
        self.report = _shared.MarkdownReport(
            self.root / RECOVERY_REPORT_FILENAME,
            fallback_path=self.fallback_dir / RECOVERY_REPORT_FILENAME,
            title="Recovery report",
        )
        self._bound = True
        try:
            self.report.mark_interrupted(self.run_id)
        except _shared.ReportWriteError as exc:
            self._audit_alert("REPORT_READ_FAILED", exc)
        self._refresh("IN PROGRESS")
        return True

    def finalize(self, status: str, *, exit_code=None):
        """Write the final run section and return every report path."""
        if self.finalized:
            return self.report_paths()
        self.status = status
        # `setup` owns the decision of whether a root exists. On a failed setup
        # (the root was non-empty, or an already-existing root was rejected)
        # the report belongs in the fallback, not in a directory `setup` just
        # refused to use.
        setup_failed = self.command == "setup" and str(status).split()[0] in (
            "blocked", "failed", "terminated",
        )
        if not setup_failed:
            self.bind_root()
        self.journal.finalize(status, summary=self.controller.summary(), exit_code=exit_code)
        self.finalized = True
        self._refresh(status, exit_code=exit_code)
        self.controller.flush_audit()
        return self.report_paths()

    def report_paths(self):
        """Every location where this invocation's report was written."""
        # `last_report_path` is the path MarkdownReport actually used: the
        # root report normally, or the documented fallback when the root is
        # unavailable. Never report an unwritten path as the destination.
        return [self.last_report_path or (self.root / RECOVERY_REPORT_FILENAME)]

    def _refresh(self, status: str, *, exit_code=None):
        body = _shared.render_run_markdown(
            self.run_id,
            status=status,
            records=self._records(),
            started_at=self._started_at(),
            finished_at=_shared._timestamp(),
            command="%s %s" % ("paper_pipeline.py", self.command),
            configuration={
                "root": str(self.root),
                "fail_tier": _shared.TIER_NAMES[self.fail_tier],
                "fail_tier_rank": self.fail_tier,
                "exit_code": exit_code,
            },
            summary=self.controller.summary(),
            empty_text=(
                "No recovery events were recorded for this run. This states only that no "
                "diagnostic recovery occurred; it is not a claim that every check ran."
            ),
        )
        report = self.report
        try:
            written = report.upsert_section(self.run_id, body)
            self.last_report_path = written
        except _shared.ReportWriteError as exc:
            # The root report is unreadable/unwritable (for example the path is
            # a directory or sits on a read-only mount). The journal still has
            # every event; write the human report to the documented fallback so
            # the run has a durable destination and report that path.
            self._audit_alert("REPORT_WRITE_FAILED", exc)
            fallback = _shared.MarkdownReport(
                self.fallback_dir / RECOVERY_REPORT_FILENAME,
                title="Recovery report (fallback)",
            )
            try:
                written = fallback.upsert_section(self.run_id, body)
                self.last_report_path = written
            except _shared.ReportWriteError as fallback_exc:
                self._audit_alert("REPORT_FALLBACK_WRITE_FAILED", fallback_exc)
            return
        # `MarkdownReport` already uses its fallback on a write error; record
        # that substitution so the console and the journal say where it went.
        if written != report.path:
            self._audit_alert(
                "REPORT_WRITE_FAILED",
                OSError("RECOVERY.md written to fallback %s" % written),
                path=written,
            )

    def _refresh_in_progress(self, controller):
        try:
            self._refresh("IN PROGRESS")
        except Exception:  # a report must never break the diagnostic path
            pass

    def _records(self):
        merged = {}
        for record in self.journal.records():
            merged[str(record.get("event_id") or len(merged))] = record
        for record in self.controller.records:
            merged.setdefault(record.event_id, record.to_dict())
        return sorted(
            merged.values(),
            key=lambda item: (_shared.record_sequence(item), str(item.get("event_id"))),
        )

    def _started_at(self):
        try:
            return json.loads(self.journal.run_path.read_text(encoding="utf-8")).get(
                "started_at"
            ) or ""
        except (OSError, ValueError):
            return ""

    def _audit_alert(self, code, exc, *, path=None):
        alert = {
            "code": code,
            "message": _shared.redact_text(str(exc)),
            "timestamp": _shared._timestamp(),
            "fallback": str(self.fallback_dir),
            "path": str(path or self.report.path),
        }
        self.journal.audit_errors.append(alert)
        self._log(
            "TIER-WARNING-REPORT_WRITE_FAILED: %s; recovery records remain in %s"
            % (alert["message"], self.fallback_dir)
        )

    def _log(self, line):
        try:
            print(line, file=sys.stderr)
        except Exception:
            pass


def begin_recovery(args):
    """Create and start the session for one invocation (None when read-only).

    Example: ``begin_recovery(args)`` for ``run`` starts a journal and the
    ``RECOVERY.md`` section before the first stage.

    Counterexample: ``status`` returns ``None``; a read-only command must not
    write into the root it is inspecting.
    """
    global _RECOVERY_SESSION
    command = str(getattr(args, "cmd", "") or "")
    if command in RECOVERY_READ_ONLY_COMMANDS:
        _RECOVERY_SESSION = None
        return None
    raw_root = getattr(args, "root", None)
    if raw_root is None:
        _RECOVERY_SESSION = None
        return None
    try:
        session = PaperRecovery(
            recovery_root_for(args),
            fail_tier=getattr(args, "fail_tier", _shared.DEFAULT_FAIL_TIER),
            command=command,
            argv=list(sys.argv[1:]),
        )
    except _shared.FailTierError as exc:
        print(f"usage error: invalid --fail-tier: {exc}", file=sys.stderr)
        raise SystemExit(2)
    session.start()
    # `setup` may be pointed at a non-existent or non-empty root; do not create
    # anything in it before setup validates. A valid existing root is bound;
    # a new/refused root stays on the fallback and binds in finalize only after
    # setup has created a real root.
    if command != "setup":
        session.bind_root()
    _RECOVERY_SESSION = session
    if bool(getattr(args, "skip_hash", False)):
        session.controller.info(
            "CHECKS_SKIPPED",
            "integrity verification",
            "the invocation skipped the integrity verification passes (--skip-hash); "
            "the chain is REPORTED, not verified by this run",
            recovery_action="record the skipped verification and mark every report that "
            "depends on it as not fully verified; a later invocation without --skip-hash "
            "re-verifies the same chain",
            affected_outputs=[str(session.root)],
            output_effects="digests are still recorded, but this run did not verify the "
            "pristine copy, pins, winners, frozen inputs or judge-view digests; treat the "
            "run's integrity as reported-only",
            remaining_uncertainty="an unchanged-looking chain was not verified in this run",
            human_review=False,
        )
    return session


def active_recovery():
    """The session configured for this invocation, or ``None``."""
    return _RECOVERY_SESSION


def record_recovery(code, operation, message, *, tier=None, **fields):
    """Record one diagnostic on the active session (a no-op without a session).

    Example: a retry exhaustion calls
    ``record_recovery("RETRY_EXHAUSTED", "round 2 judge", "...", outcome="exhausted")``.

    Counterexample: calling it from a read-only command has no destination and
    must not create one; it is a documented no-op there.
    """
    session = _RECOVERY_SESSION
    if session is None:
        return None
    diagnostic = _shared.Diagnostic(
        recovery_code_tier(code) if tier is None else tier,
        code,
        operation,
        message,
    )
    return session.controller.emit(diagnostic, **fields)


def record_incomplete_round(ctx, rounds, *, tolerated=False, detail=""):
    """Record an incomplete round (or a tolerated failed trial) and its consequence.

    Example: a round that exhausted its retries is recorded as ERROR with the
    completed rounds preserved and the round left pending for resume.

    Counterexample: a ``TOLERATED_FAIL`` trial is recorded as WARNING/degraded,
    never as a success, because the decision remains PROVISIONAL.
    """
    numbers = ", ".join(str(item) for item in rounds) if rounds else "unknown"
    if tolerated:
        return record_recovery(
            "PARTIAL_RESULT",
            "round %s" % numbers,
            detail or "the round used a tolerated failed trial instead of a completed stage",
            recovery_action="preserve the completed rounds and the failed attempt's best "
            "trial; mark the decision PROVISIONAL and continue only as configured",
            outcome="degraded",
            omissions=[
                "round(s) %s used a best failed trial; the decision is PROVISIONAL and "
                "uncertified" % numbers
            ],
            affected_outputs=[str(ctx.root)],
            validation="the round's attempt records are authoritative; a tolerated trial is "
            "not a verified complete stage",
            remaining_uncertainty="what the failed session(s) would have produced",
            human_review=True,
            output_effects="the decision is not certified and must not be presented as a "
            "complete revision",
            failure=detail or "a stage exhausted its retries and a failed trial was tolerated",
        )
    return record_recovery(
        "RETRY_EXHAUSTED",
        "round %s" % numbers,
        detail or "the round is incomplete after its bounded retries",
        recovery_action="preserve every completed round and failed attempt; leave the "
        "incomplete round pending for an explicit resume or retry",
        outcome="degraded",
        omissions=["round(s) %s did not complete" % numbers],
        affected_outputs=[str(ctx.root)],
        validation="the round's own attempt records are authoritative; missing work is not "
        "counted as complete",
        remaining_uncertainty="what the failed session(s) would have produced",
        human_review=True,
        output_effects="the run is incomplete from this round onward; completed outputs are "
        "preserved, but the manuscript is not the final answer for this configuration",
        failure=detail or "the round did not finish after its bounded retries",
    )


def finish_recovery(status, *, exit_code=None, quiet=False):
    """Finalize the active session, print its location, and return the paths.

    Example: normal completion finalizes with status ``completed``.

    Counterexample: a read-only command returns ``[]`` and prints nothing. A
    ``--json`` command passes ``quiet=True`` so the location goes to stderr and
    does not corrupt the machine-readable document on stdout.
    """
    global _RECOVERY_SESSION
    session = _RECOVERY_SESSION
    if session is None:
        return []
    paths = session.finalize(status, exit_code=exit_code)
    _RECOVERY_SESSION = None
    if paths:
        destination = Path(paths[0])
        try:
            if destination.is_file():
                print(
                    f"[recovery] report: {destination}",
                    file=sys.stderr if quiet else sys.stdout,
                )
            else:
                print(
                    "[recovery] no report file could be written; recovery records remain "
                    f"in {session.fallback_dir}",
                    file=sys.stderr,
                )
        except Exception:
            pass
        if not session._bound:
            try:
                print(
                    "[recovery] the resolved --root was not a directory; the report "
                    "was written to the documented fallback (shown above).",
                    file=sys.stderr,
                )
            except Exception:
                pass
    return paths


def note_command_refusal(message, code):
    """Record a command refusal surfaced through ``die`` before the process exits.

    Example: an unsafe output path is refused; the record states that no
    output was written and why.

    Counterexample: a normal completion does not call this; there is no refusal
    to record. ``SAFETY_GUARD_TRIPPED`` is reserved for an explicit safety
    guard; a usage/unusable-environment refusal is ``COMMAND_REFUSED``.
    """
    return record_recovery(
        "COMMAND_REFUSED",
        "command",
        str(message),
        recovery_action="refuse the unsafe or unusable request, leave existing outputs "
        "unchanged, and report the reason",
        outcome="paused",
        human_review=True,
        output_effects="the command did not complete; no new output was written by this "
        "invocation",
        failure=_shared.redact_text(str(message)),
    )


def note_run_verdict(command, code):
    """Record a command that finished its work but stopped on a non-certified verdict.

    Example: ``decide`` exits 5 after writing its report because the decision
    is not certified; the record keeps that report and states the follow-up.

    Counterexample: a usage error or ``die()`` refusal is not a run verdict;
    that path is ``note_command_refusal``.
    """
    return record_recovery(
        "RUN_VERDICT",
        "command %s" % command,
        "the command completed with non-certified verdict exit status %s" % code,
        recovery_action="keep the written outputs and report the verdict; a later "
        "invocation may change the outcome after the named problems are addressed",
        outcome="degraded",
        affected_outputs=["%s" % (getattr(_RECOVERY_SESSION, "root", "the output root"))],
        validation="the command's own report/decision is authoritative; this record does "
        "not certify it",
        remaining_uncertainty="whether the reported problems can be resolved",
        human_review=True,
        output_effects="the command wrote its outputs, but they are not a certified "
        "answer; read its verdict report before downstream use",
        failure="non-certified verdict exit status %s" % code,
    )

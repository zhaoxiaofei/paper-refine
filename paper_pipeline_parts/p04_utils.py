# -*- coding: utf-8 -*-
# Part 04/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# UTILITIES
# =====================================================================

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_stamp() -> str:
    """The current LOCAL wall-clock time as "YYYY-MM-DD HH:MM:SS"."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class TimestampedStream:
    """Wrap a text stream so every line is prefixed with the current datetime.

    A long pipeline run produces interleaved progress messages, retry notices
    and warnings; without a timestamp the operator cannot tell when a step
    started, how long a stage idled, or whether two messages came from the same
    attempt. The prefix is evaluated AT WRITE TIME (format: year-month-day
    hour-minute-second, local time) and applies to every line of a multi-line
    message, so pasted tracebacks and the tabular summaries stay readable.
    It is installed AFTER argument parsing, so `-h`/`--help` and usage errors
    (which argparse prints during the parse) stay un-prefixed.
    """

    def __init__(self, stream):
        self._stream = stream
        self._at_line_start = True
        self._lock = threading.Lock()

    def write(self, text) -> int:
        if not isinstance(text, str):
            text = str(text)
        if not text:
            return 0
        written = 0
        with self._lock:
            for line in text.splitlines(keepends=True):
                if self._at_line_start and line not in ("\n", "\r\n"):
                    stamp = f"{local_stamp()} "
                    self._stream.write(stamp)
                    written += len(stamp)
                    self._at_line_start = False
                if line.endswith(("\n", "\r")):
                    self._at_line_start = True
                self._stream.write(line)
                written += len(line)
            self._stream.flush()
        return written

    def flush(self) -> None:
        try:
            self._stream.flush()
        except OSError:
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except (AttributeError, OSError):
            return False

    def __getattr__(self, name):
        return getattr(self._stream, name)


def install_timestamped_streams() -> None:
    """Timestamp every stdout/stderr line the pipeline itself prints."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if isinstance(stream, TimestampedStream):
            continue
        try:
            setattr(sys, name, TimestampedStream(stream))
        except Exception:                                        # noqa: BLE001
            pass


def print_raw(text: str) -> None:
    """Print WITHOUT the datetime prefix (machine-readable output, `--json`)."""
    stream = sys.stdout
    raw = getattr(stream, "_stream", stream)
    raw.write(text if text.endswith("\n") else text + "\n")
    raw.flush()


class RunLogStream:
    """Tee everything the pipeline prints into the root's per-invocation run log.

    The attempt history (`state.json` -> `attempts_log`, `runs/<run>_try<N>_failed/`) keeps
    each ATTEMPT's diagnostics; this keeps the INVOCATION's console, line for
    line, next to the reports it produced -- including the retry/backoff lines,
    the judge-panel advisories and the `[repair] ...` decisions that belong to no
    single attempt. Installed INSIDE `TimestampedStream` (see `install_run_log`):
    the tee sits between the stamper and the terminal, so the file carries the
    same stamped lines the operator saw.
    """

    def __init__(self, stream, path: Path):
        self._stream = stream
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")

    def write(self, text) -> int:
        if not isinstance(text, str):
            text = str(text)
        try:
            self._fh.write(text)
            self._fh.flush()
        except (OSError, ValueError):
            pass
        return self._stream.write(text)

    def flush(self) -> None:
        try:
            self._fh.flush()
        except (OSError, ValueError):
            pass
        try:
            self._stream.flush()
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._fh.close()
        except (OSError, ValueError):
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except (AttributeError, OSError):
            return False

    def __getattr__(self, name):
        return getattr(self._stream, name)


# Commands that drive or mutate a root keep their console in
# reports/<cmd>-<stamp>.log (see begin_run_log). `conform --agent`, `add-venue`
# and `track` run FULL agent sessions / Word compare work like `redline` does,
# so their retry, backoff and advisory lines must land in the root too instead
# of only in a disposable sandbox log.
LOGGING_COMMANDS = ("setup", "run", "run-decide", "decide", "retry", "prune", "redline",
                    "conflicts", "conform", "add-venue", "track")
# Every command that can change a root, its package, or its bookkeeping. The
# read-only audit commands are deliberately absent. Keeping the list here makes
# the stale-driver fence independent of which command function was extended.
FOREIGN_GUARD_COMMANDS = (
    "run", "run-decide", "decide", "redline", "track", "conflicts", "conform",
    "retry", "prune", "add-venue", "build-venue-templates", "adopt-sweep",
    "set-venue", "set-journal", "set-article-type", "set-revision-mode",
    "set-submit-code", "set-author-to-complete", "set-placeholder-file",
    "set-tiebreak-defect-floor", "set-dedup-mode", "set-probe-review",
    "set-champion-select",
)
# The path of the invocation's run log (set by `main`, recorded by
# `save_state`): a root accumulates the console of its invocations, so the
# retry/backoff lines and the judge advisories of an old run are still readable.
CURRENT_RUN_LOG = None


def start_run_log(cmd: str, root, argv=None) -> Path:
    """Open `reports/<cmd>-<stamp>.log` and mirror stdout/stderr into it.

    Returns the path, or None when the log could not be opened. `Path("")` is
    Path(".") and TRUTHY, so the old empty-Path sentinel defeated every caller's
    `if path` guard: a failed open printed "run log: .", set CURRENT_RUN_LOG to
    '.', and appended '.' to the root's `run_logs` history. Called by `main()`
    for the commands that drive or mutate a root: `status`/`--help` stay quiet.
    The file is also recorded on the root as `run_logs` so a later inspection can
    find the console of any invocation, and `setup` writes into the root it is
    creating.
    """
    try:
        reports = Path(root) / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = reports / f"{cmd}-{stamp}.log"
        path = base
        n = 2
        while True:
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                break
            except FileExistsError:
                # A second invocation inside the same UTC second must not
                # truncate the first one's log (it is opened before the root
                # lock, so a racing double-start is exactly this case).
                path = base.with_name(f"{base.stem}-{n}{base.suffix}")
                n += 1
        header = (f"# paper_pipeline {cmd} -- {utcnow()}\n"
                  f"# root: {Path(root).resolve()}\n"
                  f"# argv: {' '.join(str(a) for a in (argv or []))}\n")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(header)
        return path
    except OSError:
        return None


def install_run_log(path: Path) -> None:
    """Mirror both console streams into `path` (see `RunLogStream`).

    The tee goes INSIDE `TimestampedStream`: the stamper writes through the log
    stream, so the file receives the stamped lines that reach the console. The
    old order (log stream outermost) wrote the raw text to the file and the
    console-only stamps never reached it.
    """
    if not path or not str(path):
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        stamper = stream if isinstance(stream, TimestampedStream) else None
        inner = getattr(stamper, "_stream", stream) if stamper is not None else stream
        if isinstance(inner, RunLogStream):
            continue
        try:
            logged = RunLogStream(inner, path)
            setattr(sys, name, TimestampedStream(logged) if stamper is not None else logged)
        except Exception:                                        # noqa: BLE001
            pass


def begin_run_log(cmd: str, root, argv=None) -> Path:
    """Start the invocation's run log, mirror the console into it, say where it is."""
    global CURRENT_RUN_LOG
    path = start_run_log(cmd, root, argv or sys.argv)
    if path is not None:
        CURRENT_RUN_LOG = path
        install_run_log(path)
        print(f"[{cmd}] run log: {path}")
    return path


def pipeline_identity() -> dict:
    """{path, sha256, version, modules} of the script RUNNING right now.

    `setup` records it on the root, so a later invocation can say whether the copy
    it is executing is the one the root was created with. The 2026-09-22 roots made
    this worth printing: `setup` had been run from a stale checkout, so the root
    contained a pipeline WITHOUT the scoped-repair code, silently -- five hours of
    retries later the operator asked why `--strict-artifacts fix` never fired.

    `modules` records every sibling module a run executes (the docx formatter,
    the redlines adapter and the Qwen adapter). The 2026-10-19 round-2 roots showed why
    the driver's digest alone is insufficient: the roots ran an old
    `paper_pipeline.py` AND an old `paper_docx_format.py`, so the layout rules
    added to the workspace never executed even though the driver version string
    was unchanged.
    """
    p = Path(__file__).resolve()
    try:
        digest = sha256_file(p)
    except OSError:
        digest = ""
    return {"path": str(p), "sha256": digest, "version": VERSION,
            "modules": module_manifest(p.parent)}


def asset_dir_digest(base_dir: Path, name: str):
    """One digest for a frozen asset directory (None when it is absent).

    Every shipped file is hashed, not just `*.py`: the skills pack's prompts and
    reference tables change a stage's behaviour as much as a script does. Only
    `__pycache__`/`.pyc` are skipped -- execution by-products differ between a
    checkout that ran and a fresh copy and must never make a frozen bundle look
    edited.
    """
    dirp = Path(base_dir) / name
    if not dirp.is_dir():
        return None
    try:
        paths = sorted(p for p in dirp.rglob("*")
                       if p.is_file()
                       and "__pycache__" not in p.parts
                       and p.suffix.lower() not in (".pyc", ".pyo"))
        digest = hashlib.sha256()
        for p in paths:
            digest.update(p.relative_to(dirp).as_posix().encode("utf-8"))
            digest.update(sha256_file(p).encode("ascii"))
        return digest.hexdigest()
    except OSError:
        return None


def module_manifest(base_dir: Path) -> dict:
    """{name: sha256} for the driver's sibling modules and frozen asset dirs."""
    out = {}
    for name in PIPELINE_MODULE_FILES:
        q = Path(base_dir) / name
        try:
            out[name] = sha256_file(q) if q.is_file() else None
        except OSError:
            out[name] = None
    for name in (PIPELINE_ASSET_DIRS + PIPELINE_VENUE_ASSET_DIRS
                 + PIPELINE_SKILL_ASSET_DIRS):
        out[name] = asset_dir_digest(base_dir, name)
    return out


def copy_asset_dirs(src_dir, dst_dir, names=None) -> list:
    """Copy the ordered parts/skills directories, atomically and without bytecode.

    Returns the directory names actually copied. A missing source directory is
    skipped (a trimmed checkout may legitimately carry only the pipeline parts),
    but `module_manifest` then records None for it, so a later run can say the
    bundle is incomplete instead of silently executing a loader with no parts.
    """
    copied = []
    wanted = (PIPELINE_ASSET_DIRS + PIPELINE_VENUE_ASSET_DIRS
              + PIPELINE_SKILL_ASSET_DIRS
              if names is None else names)
    for name in wanted:
        src = Path(src_dir) / name
        if not src.is_dir():
            continue
        dst = Path(dst_dir) / name
        # A per-process unique staging name: two concurrent syncs must never
        # share (and one must never delete) the other's half-built tree.
        tmp = dst.with_name(f"{dst.name}.copy-tmp-{os.getpid()}-{time.time_ns()}")
        backup = None
        try:
            shutil.copytree(src, tmp,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            if dst.exists() or dst.is_symlink():
                # Move the live bundle aside instead of deleting it: a failed
                # replace can then put the old tree back, so an interrupted
                # setup/sync-code never leaves the root with no parts directory.
                backup = dst.with_name(f"{dst.name}.copy-old-{os.getpid()}-{time.time_ns()}")
                os.replace(dst, backup)
            try:
                os.replace(tmp, dst)
            except BaseException:
                if backup is not None and backup.exists():
                    os.replace(backup, dst)
                    backup = None
                raise
            if backup is not None:
                rmtree_force(backup)
            copied.append(name)
        except BaseException:
            if tmp.exists():
                rmtree_force(tmp)
            raise
    return copied


def pipeline_identity_note(ctx: Ctx) -> str:
    """A one-paragraph warning when the running script is not the recorded one."""
    recorded = (ctx.state or {}).get("pipeline") or {}
    now = pipeline_identity()
    old = str(recorded.get("sha256") or "")
    if not old or not now["sha256"] or old == now["sha256"]:
        return ""
    return (f"[pipeline] NOTE: the script running now is NOT the copy recorded at setup "
            f"(sha256 {now['sha256'][:16]}... vs {old[:16]}..., recorded v"
            f"{recorded.get('version') or '?'} from {recorded.get('path')}). The root is being "
            f"driven by a PATCHED or different pipeline; if that is not what you intended, "
            f"re-run `setup` from the tree you mean to use (the root keeps the copy it was "
            f"created with).")


def frozen_snapshot_root(path=None) -> dict:
    """The pipeline ROOT that holds the running script as its frozen copy ({} = none).

    `setup` freezes the running script into the new root on purpose ("THIS copy
    is frozen into the root and is what every later `run` executes"), so running
    a ROOT's own copy is the documented way to drive that root. It is NOT a way
    to create a NEW root: the 2026-10-15 neohet-12to13 run was set up that way
    -- `python3 <neohet-10to11>.../paper_pipeline.py setup --root <neohet-12to13>`
    -- so the new root froze a two-day-old snapshot (commit e15c869) and EVERY
    later command in it ran that code: the PKG-2 dangling-reference scan, the
    README rule and the M31-M36 evidence-integrity sweeps committed between then
    and the run's start were all silently absent, and the operator's audit found
    the same defects in the "new" package that the fixes had already closed.

    Detection is structural -- the running file sits directly inside a directory
    that holds a pipeline registry (`state.json`/`pipeline_config.json`) -- so it
    needs no marker in the file itself and cannot be fooled by a rename. The
    returned record names that root, when its snapshot was last written, the
    ORIGIN pipeline the snapshot was frozen from (its own `state.json` records
    it) and the sha256 of both, so the caller can say exactly which code would
    run and which tree the operator meant to use.
    """
    try:
        here = Path(path).resolve() if path else Path(__file__).resolve()
    except (NameError, OSError):                                      # pragma: no cover
        return {}
    holder = here.parent
    if not ((holder / "state.json").is_file() or (holder / "pipeline_config.json").is_file()):
        return {}
    try:
        rec = read_json(holder / "state.json") or {}
    except Exception:                                                 # noqa: BLE001
        rec = {}
    origin = rec.get("pipeline") or {}
    frozen_at = ""
    try:
        frozen_at = datetime.fromtimestamp(here.stat().st_mtime, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except OSError:                                                   # pragma: no cover
        pass
    origin_path = str(origin.get("path") or "")
    origin_digest = ""
    if origin_path and Path(origin_path).is_file():
        try:
            origin_digest = sha256_file(Path(origin_path))
        except OSError:                                               # pragma: no cover
            origin_digest = ""
    try:
        own_digest = sha256_file(here)
    except OSError:                                                   # pragma: no cover
        own_digest = ""
    return {"root": str(holder), "script": str(here), "frozen_at": frozen_at,
            "origin_path": origin_path, "origin_digest": origin_digest,
            "origin_version": origin.get("version"),
            "digest": own_digest,
            "origin_differs": bool(origin_digest and own_digest
                                   and origin_digest != own_digest)}


def root_pipeline_staleness(ctx: Ctx) -> dict:
    """How this ROOT's frozen pipeline relates to the ORIGIN tree it was frozen from.

    `setup` records the script it ran (`state.json` -> `pipeline: {path, sha256,
    version}`), and a root keeps that frozen copy on purpose: every later `run`
    executes the snapshotted code, which is what makes a verdict reproducible.
    The price is that fixes committed to the origin tree afterwards are NOT in
    the run -- and nothing said so. The 2026-10-15 neohet-12to13 root is the
    case: it was set up from an old root's copy, so all later commands ran
    commit e15c869's code and re-found defects the origin tree had already
    closed. This reports that state (used by `status`); it never changes a run.

    The FROZEN COPY is measured too (2026-10-15): the 30to31/13to14 roots
    recorded the CURRENT `paper_pipeline.py` sha256 while the file frozen beside
    their `state.json` was four commits older -- the operator had opened late
    sessions from the fixed repo, so the record said "frozen from here" while the
    run still drove the stale bundle (the delivered neohet package shipped an OS
    junk stub and a `code/README.md` full of stage notes because of it). A
    recorded path that still hashes to the recorded value is therefore not proof:
    `frozen_sha256` is what the next command in this root will actually execute.
    """
    recorded = (ctx.state or {}).get("pipeline") or {}
    origin_path = str(recorded.get("path") or "")
    frozen = ctx.root / "paper_pipeline.py"
    out = {"frozen": str(frozen) if frozen.is_file() else None,
           "frozen_at": None, "origin": origin_path or None,
           "recorded_sha256": str(recorded.get("sha256") or "") or None,
           "origin_sha256": None, "origin_differs": False, "snapshot_of_root": None,
           "frozen_sha256": None, "frozen_differs": False,
           "recorded_modules": dict(recorded.get("modules") or {}),
           "frozen_modules": module_manifest(ctx.root),
           "maintained_modules": {}, "module_diffs": []}
    if frozen.is_file():
        try:
            out["frozen_at"] = datetime.fromtimestamp(
                frozen.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:                                               # pragma: no cover
            pass
        try:
            out["frozen_sha256"] = sha256_file(frozen)
        except OSError:                                               # pragma: no cover
            pass
        holder = frozen_snapshot_root(frozen)
        out["snapshot_of_root"] = holder.get("root") if holder else None
    if origin_path and Path(origin_path).is_file():
        try:
            out["origin_sha256"] = sha256_file(Path(origin_path))
        except OSError:                                               # pragma: no cover
            pass
    out["origin_differs"] = bool(out["origin_sha256"] and out["recorded_sha256"]
                                 and out["origin_sha256"] != out["recorded_sha256"])
    out["frozen_differs"] = bool(out["frozen_sha256"] and out["recorded_sha256"]
                                 and out["frozen_sha256"] != out["recorded_sha256"])
    # THE MAINTENANCE CHAIN (2026-10-16): a root set up from ANOTHER root's copy
    # records that copy as its origin, and the two then agree with each other
    # while both drift from the tree the operator maintains. The 2026-10-15b
    # neohet root is the case -- its recorded origin is the 2026-10-10
    # neohet-10to11 root, whose own `pipeline.path` names this repository -- so
    # `maintained_*` is the first link in the chain that is NOT a frozen
    # snapshot (three hops is more than any real chain, and a cycle must not
    # hang a status command).
    out["maintained_path"] = None
    out["maintained_sha256"] = None
    out["maintained_differs"] = False
    out["frozen_foreign"] = bool(origin_path and Path(origin_path).is_file()
                                 and frozen_snapshot_root(origin_path))
    seen, cursor = set(), origin_path
    for _hop in range(3):
        if not cursor or cursor in seen or not Path(cursor).is_file():
            break
        seen.add(cursor)
        holder = frozen_snapshot_root(cursor)
        if not holder:
            out["maintained_path"] = cursor
            try:
                out["maintained_sha256"] = sha256_file(Path(cursor))
            except OSError:                                           # pragma: no cover
                out["maintained_sha256"] = None
            break
        try:
            rec = read_json(Path(cursor).parent / "state.json") or {}
        except Exception:                                             # noqa: BLE001
            rec = {}
        cursor = str((rec.get("pipeline") or {}).get("path") or "")
    out["maintained_differs"] = bool(out["maintained_sha256"] and out["frozen_sha256"]
                                     and out["maintained_sha256"] != out["frozen_sha256"])
    # A module the state.json manifest RECORDS must still hash to the recorded
    # value. `module_diffs` only compares a frozen file with the maintained
    # tree, so an edited or deleted frozen sibling (the maintained copy
    # unchanged) produced no diff at all and `refuse_foreign_pipeline` let the
    # root run. Record that local drift separately: it is a different repair
    # from "the maintained tree has moved on".
    out["recorded_module_diffs"] = []
    for name in (PIPELINE_MODULE_FILES + PIPELINE_ASSET_DIRS
                 + PIPELINE_VENUE_ASSET_DIRS + PIPELINE_SKILL_ASSET_DIRS):
        if name == "paper_pipeline.py":
            continue
        recorded_hash = out["recorded_modules"].get(name)
        frozen_hash = out["frozen_modules"].get(name)
        if recorded_hash and recorded_hash != frozen_hash:
            out["recorded_module_diffs"].append(name)
    # The module manifest (2026-10-19): a root can run a fresh driver with
    # a stale formatter, and the driver digest alone cannot see it. Compare the
    # FROZEN modules with the MAINTAINED tree's modules when the maintenance
    # chain names one. The skills pack is part of the frozen bundle too (setup
    # copies and records it), so a stale skills copy must be visible here.
    if out.get("maintained_path"):
        out["maintained_modules"] = module_manifest(Path(out["maintained_path"]).parent)
        for name in (PIPELINE_MODULE_FILES + PIPELINE_ASSET_DIRS
                     + PIPELINE_VENUE_ASSET_DIRS + PIPELINE_SKILL_ASSET_DIRS):
            # The driver has its own, stronger check (`running_pipeline_mismatch`
            # / `frozen_differs`): including it here made a foreign driver die
            # with the generic "stale sibling module" message instead of the
            # actionable "DIFFERENT paper_pipeline.py" one.
            if name == "paper_pipeline.py":
                continue
            a = out["frozen_modules"].get(name)
            b = out["maintained_modules"].get(name)
            if a and b and a != b:
                out["module_diffs"].append(name)
    return out


def _sync_code_hint(root, maintained_path=None) -> str:
    """The command that actually works: sync-code from the maintained checkout.

    `sync-code` refuses when run from a root's frozen `paper_pipeline.py`, so a
    recovery message may never suggest the running `__file__` when that file is
    the root's snapshot. Name the maintained driver when the maintenance chain
    has one, else tell the operator what to run instead of inventing a path.
    """
    if maintained_path and Path(maintained_path).is_file() \
            and not frozen_snapshot_root(maintained_path):
        return (f"python3 {shlex.quote(str(maintained_path))} sync-code "
                f"--root {shlex.quote(str(root))}")
    return ("run `sync-code` from the MAINTAINED checkout (the tree holding the "
            "`paper_pipeline.py` you mean to ship), not from this root's frozen copy")


def pipeline_snapshot_note(ctx: Ctx) -> str:
    """One paragraph for `status`: which code this root actually runs."""
    st = root_pipeline_staleness(ctx)
    if not st.get("frozen"):
        return ""
    if st.get("recorded_module_diffs"):
        # The record and the FILE disagree: state.json records one digest, the
        # frozen sibling hashes to another (or is gone). This is LOCAL drift --
        # not "the maintained tree moved on" -- and the two have different
        # repairs, so say which one it is.
        return (f"[pipeline] **WARNING**: this root's frozen bundle does NOT match the "
                f"module manifest in its state.json: "
                f"{', '.join(st['recorded_module_diffs'])}. The frozen copy was edited or "
                f"deleted after setup, so every command here runs code its own record does "
                f"not describe. Restore the recorded copy, or deliberately replace the "
                f"bundle: {_sync_code_hint(ctx.root, st.get('maintained_path'))}.")
    if st.get("module_diffs"):
        return (f"[pipeline] **WARNING**: this root's frozen bundle differs from the "
                f"maintained tree in {', '.join(st['module_diffs'])}. Every command here "
                f"still executes the frozen copy, so rules added to the maintained tree "
                f"after setup do NOT run. Run "
                f"{_sync_code_hint(ctx.root, st.get('maintained_path'))} (or recreate the "
                f"root from the maintained tree) before the next stage if the new rules "
                f"must apply.")
    if st.get("frozen_foreign") and st.get("maintained_differs"):
        # The recorded origin is ANOTHER root's snapshot, and the tree the
        # operator maintains has moved on: this root and its origin agree with
        # each other while both run replaced code. A warning, never a refusal --
        # the root still runs, reproducibly, on the code it froze. A root set up
        # from the maintained tree is NOT warned about here: its origin is that
        # tree, and the ordinary "origin has moved on" sentence below covers it.
        return (f"[pipeline] **WARNING**: this root runs the FROZEN "
                f"{st.get('frozen')} (sha256 {str(st.get('frozen_sha256'))[:16]}...), and that "
                f"snapshot came from `{st.get('origin')}`, which is itself a root's copy. The "
                f"tree being maintained ({st.get('maintained_path')}) has moved on since "
                f"(sha256 {str(st.get('maintained_sha256'))[:16]}...). Every command here "
                f"executes the frozen code, so fixes committed since the snapshot will NOT run "
                f"in this root. Re-create the root from the maintained tree (same `--source`), "
                f"or copy the current `paper_pipeline.py`, `paper_docx_format.py` and "
                f"`paper_redlines_adapter.py` and `paper_qwen_agent.py` beside this "
                f"root's `state.json`.")
    if st.get("frozen_differs"):
        # The record and the FILE disagree: state.json says one sha256, the
        # frozen script hashes to another. That is not "origin moved on" -- it is
        # a run that will execute code its own record does not describe, and the
        # 2026-10-15 roots reached publication in exactly this state.
        return (f"[pipeline] **WARNING**: this root runs the FROZEN {st['frozen']} "
                f"(sha256 {str(st.get('frozen_sha256'))[:16]}...), which is NOT the copy its "
                f"state.json records (sha256 {str(st.get('recorded_sha256'))[:16]}...). Fixes "
                f"made in the recorded tree are not in effect here. Copy the recorded "
                f"`paper_pipeline.py` over the frozen one (and re-run) if the run must carry "
                f"them.")
    if not st.get("origin"):
        return (f"[pipeline] this root runs the pipeline frozen into it "
                f"({st.get('frozen_at') or 'date unknown'}); the recorded origin is unknown")
    if not st.get("origin_differs"):
        return (f"[pipeline] this root runs the pipeline snapshot frozen into it "
                f"({st.get('frozen_at') or 'date unknown'}), and the ORIGIN tree "
                f"{st['origin']} is unchanged since")
    return (f"[pipeline] NOTE: this root runs the snapshot frozen into it "
            f"({st.get('frozen_at') or 'date unknown'}, sha256 "
            f"{str(st.get('recorded_sha256'))[:16]}...), while the ORIGIN tree "
            f"{st['origin']} has changed since (sha256 "
            f"{str(st.get('origin_sha256'))[:16]}...). Keeping the snapshot is what makes this "
            f"root's verdicts reproducible, but fixes committed to the origin tree after it are "
            f"NOT in this run: create a NEW root with the origin tree's `paper_pipeline.py` "
            f"(same --source) when you want them.")


def running_pipeline_mismatch(ctx: Ctx) -> dict:
    """The RUNNING script vs the pipeline frozen into this root.

    `setup` freezes one `paper_pipeline.py` into the root so every later
    command is reproducible. A plain `python /another/root/paper_pipeline.py
    run --root THIS_ROOT` bypassed that contract: the 2026-10-17 `cnb-to35` and
    `neohet-to17` roots were created from this tree's 6671581 snapshot but
    driven by the older `cnb-to34`/`neohet-to16` copies. Their decision records
    then said `submission_ready: true` beside a gating marker residual the
    current code already rejected, and the stale driver left duplicate
    pre-revision documents in the published package. The run log warned about
    this; the command still mutated the root and stamped a verdict. A warning
    is not enough for a state-changing command: refuse before the lock unless
    the operator deliberately replaces the frozen copy.
    """
    st = root_pipeline_staleness(ctx)
    ident = pipeline_identity()
    frozen = str(st.get("frozen_sha256") or "")
    running = str(ident.get("sha256") or "")
    recorded = str(st.get("recorded_sha256") or "")
    return {"mismatch": bool(frozen and running and frozen != running),
            # A frozen copy EDITED after setup hashes to whatever the running
            # script is (frozen == running) but no longer to the digest the root
            # recorded. The old expression only compared frozen with running, so
            # `frozen_differs` was computed and never consulted and the mutation
            # proceeded with a NOTE.
            "frozen_differs": bool(frozen and recorded and frozen != recorded),
            # A DELETED frozen copy has frozen_sha256 == ""; the old
            # `st.get("frozen") and not frozen` was then falsy (the path key was
            # cleared too), so a root without its frozen driver was mutated.
            "unverifiable": bool((recorded and not frozen) or not running),
            "frozen": st.get("frozen"), "frozen_sha256": frozen or None,
            "running": ident.get("path"), "running_sha256": running or None,
            "recorded": recorded or None}


def refuse_foreign_pipeline(ctx: Ctx, command: str) -> None:
    """Refuse a state-changing command driven by another copy of the script.

    2026-10-19: the root also freezes `paper_docx_format.py` and
    `paper_redlines_adapter.py` and `paper_qwen_agent.py`. A root created after the module manifest
    existed (`state.pipeline.modules`) must not run when the maintained tree's
    formatter or adapter differs from the frozen one: the round-2 roots ran an
    old formatter while the workspace already carried FMT-AV3/IM5/TB5/T6h, so
    defects those rules target shipped although the driver looked current. The
    deliberate escape is `sync-code` (copy the maintained modules and record
    their digests), not an environment variable.
    """
    st = root_pipeline_staleness(ctx)

    def _strict_diffs(names) -> list:
        # venue_profiles/ is root-local BY CONTRACT (`set-venue --profile` and a
        # hand-added file are documented custom routes), so its drift is reported
        # by `status` (pipeline_snapshot_note) but must not refuse the very
        # `set-venue --list` that follows the install. The other frozen modules
        # are never legitimately edited in place.
        return [n for n in (names or []) if n not in PIPELINE_VENUE_ASSET_DIRS]

    recorded_diffs = _strict_diffs(st.get("recorded_module_diffs"))
    maintained_diffs = _strict_diffs(st.get("module_diffs"))
    if st.get("recorded_modules") and recorded_diffs:
        die(
            f"{command} would run this root with sibling module(s) that do NOT match its "
            f"state.json manifest: {', '.join(recorded_diffs)}.\n"
            f"    frozen     : {ctx.root}\n"
            f"The frozen copy was edited or deleted after setup; every stage prompt, scan and "
            f"postcheck would come from code the root's own record does not describe. "
            f"Restore the recorded bundle, or deliberately replace it from the maintained "
            f"tree:\n"
            f"    {_sync_code_hint(ctx.root, st.get('maintained_path'))}\n"
            f"then retry.", code=2)
    if st.get("recorded_modules") and maintained_diffs:
        die(
            f"{command} would run this root with STALE sibling module(s): "
            f"{', '.join(maintained_diffs)}.\n"
            f"    frozen     : {ctx.root}\n"
            f"    maintained : {st.get('maintained_path')}\n"
            f"The root's state.json records a module manifest; the maintained tree's "
            f"copy of at least one of them has changed since. The stage prompts, scans and "
            f"postchecks must come from the same bundle. Run:\n"
            f"    {_sync_code_hint(ctx.root, st.get('maintained_path'))}\n"
            f"to copy the maintained modules into the root and record the new digests, "
            f"then retry.", code=2)
    mm = running_pipeline_mismatch(ctx)
    if mm["frozen_differs"] and not mm["mismatch"]:
        # The running script IS the frozen one (frozen == running) but that file
        # is no longer the digest setup recorded: the local-edit bypass. When the
        # running script is a DIFFERENT copy too, the message below is the more
        # actionable one (the operator is not driving the frozen copy at all).
        die(
            f"{command} would run a FROZEN paper_pipeline.py that was EDITED after setup:\n"
            f"    frozen copy : {mm.get('frozen')} (sha256 {str(mm.get('frozen_sha256'))[:16]}...)\n"
            f"    recorded at : setup (sha256 {str(mm.get('recorded'))[:16]}...)\n"
            f"Running this copy makes the root's records describe code its own setup never "
            f"recorded (the fence exists to stop exactly that). Restore the recorded copy, or "
            f"deliberately replace it from the maintained tree with `sync-code`, then retry.",
            code=2)
    if not mm["mismatch"] and not mm["unverifiable"]:
        return
    if mm["unverifiable"]:
        die(
            f"{command} cannot verify which paper_pipeline.py this root would run: "
            f"frozen={mm.get('frozen')!r} (sha256 {mm.get('frozen_sha256')}), "
            f"running={mm.get('running')!r} (sha256 {mm.get('running_sha256')}).\n"
            f"Refusing to mutate a root whose reproducibility cannot be established. "
            f"Restore/read the root's frozen copy, or deliberately replace it with the "
            f"copy you intend to run, then retry.", code=2)
    die(
        f"{command} is running a DIFFERENT paper_pipeline.py than the one frozen into this "
        f"root:\n"
        f"    running now : {mm['running']} (sha256 {str(mm['running_sha256'])[:16]}...)\n"
        f"    frozen copy : {mm['frozen']} (sha256 {str(mm['frozen_sha256'])[:16]}...)\n"
        f"Every stage prompt, postcheck and decision in this root must come from the frozen "
        f"copy; otherwise the root's records describe code that did not run (the 2026-10-17 "
        f"cnb-to35/neohet-to17 roots were driven by older root copies this way). Run:\n"
        f"    python3 {shlex.quote(str(mm['frozen']))} {command} "
        f"--root {shlex.quote(str(ctx.root))}\n"
        f"or deliberately replace the frozen `paper_pipeline.py` with the copy you intend to "
        f"run, then retry.", code=2)


def nat_key(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(s))]


# ---- hashing: the same digests, without reading the same bytes twice ---------
#
# `decide` re-verifies the whole content-addressed chain: the pristine copy, the
# pinned champions, the published winners and EVERY completed run's frozen
# inputs (each judge sandbox carries a full target + field copy). A real root
# therefore re-hashes the same corpus dozens of times, which dominated `decide`
# (measured: ~85% of the command in sha256_file). Two changes remove that cost
# WITHOUT changing a single digest:
#
#   1. a process-local cache keyed by the file's FULL stat identity (size,
#      mtime_ns, ctime_ns, inode, device). Any content or metadata change --
#      including one that restores the mtime with `touch -r`, which still moves
#      ctime -- produces a new key and is hashed again. The cache only avoids
#      re-reading bytes this process already hashed and which provably did not
#      change since; `PAPER_HASH_CACHE=0` switches it off.
#   2. batched, concurrent first-pass hashing (`sha256_files`), because the
#      manifests are built from hundreds of files and hashlib releases the GIL
#      while hashing. `PAPER_HASH_WORKERS=N` sets the worker count (default: two
#      per CPU, capped at 32; 1 = strictly serial).
def _env_hash_cache():
    """True/False when PAPER_HASH_CACHE forces it, None for the automatic rule."""
    v = os.environ.get("PAPER_HASH_CACHE", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


_HASH_CACHE_FORCED = _env_hash_cache()
# Default OFF. configure_hash_cache_for_command() enables it for the READ-ONLY
# audit (`status`), and only while no other pipeline process holds the root
# lock. The reason for the restriction is measured, not theoretical:
# this machine's /tmp lives on an ext4 mount whose mtime/ctime move only once
# per second, so a same-second, same-size rewrite of a file can leave the whole
# stat identity unchanged -- a stat-keyed cache would then serve a stale digest
# and HIDE exactly the kind of tampering the integrity checks exist to catch.
# Commands that run agents (notably `run`) or write the trees they hash
# (`decide` repoints references inside final_clean_version.tmp AFTER hashing
# it) may hash a file, rewrite it in place with the same size inside one
# filesystem timestamp tick, and hash it again, so they must not use the
# cache. `PAPER_HASH_CACHE=1` forces it on (only for operators who know their
# tree is quiescent) and `PAPER_HASH_CACHE=0` forces it off.
HASH_CACHE_ENABLED = bool(_HASH_CACHE_FORCED)
HASH_CACHE_AUTO_COMMANDS = ("status",)
try:
    HASH_WORKERS = max(1, int(os.environ.get("PAPER_HASH_WORKERS", "")
                              or min(32, (os.cpu_count() or 4) * 2)))
except ValueError:
    HASH_WORKERS = 1
_HASH_CACHE: dict = {}
_HASH_CACHE_LOCK = threading.Lock()
_HASH_CACHE_MAX = 1_000_000
_HASH_POOL = None
_HASH_POOL_LOCK = threading.Lock()


def _hash_pool():
    global _HASH_POOL
    if _HASH_POOL is None:
        with _HASH_POOL_LOCK:
            if _HASH_POOL is None:
                _HASH_POOL = ThreadPoolExecutor(max_workers=HASH_WORKERS,
                                                thread_name_prefix="paper-hash")
    return _HASH_POOL


def hash_cache_stats() -> dict:
    """Cache/worker state (diagnostic only; nothing depends on it)."""
    with _HASH_CACHE_LOCK:
        n = len(_HASH_CACHE)
    return {"entries": n, "enabled": HASH_CACHE_ENABLED, "forced": _HASH_CACHE_FORCED,
            "workers": HASH_WORKERS}


def _root_lock_holder(root):
    """(pid, what) of the live process holding this root's lock, or None."""
    try:
        info = read_json(Path(root) / LOCK_FILE, revive=False) or {}
    except (OSError, TypeError, ValueError):
        return None
    pid = info.get("pid")
    if isinstance(pid, int) and pid_alive(pid):
        return pid, str(info.get("what") or "")
    return None


def configure_hash_cache_for_command(cmd: str, root) -> str:
    """Turn the digest cache on only for a quiescent, read-only audit.

    Returns a note for the operator ("" when there is nothing to say). The
    automatic rule: the cache is ON for `status` (which never writes the tree it
    hashes) unless another live pipeline process holds the root lock (a
    `run`/`decide`/`retry`/`prune`/`redline` can be writing that tree right
    now), in which case the audit re-reads every byte; it is OFF for everything
    else -- `decide` included, because it rewrites final_clean_version.tmp
    after hashing it. PAPER_HASH_CACHE=1/0 overrides the whole rule.
    """
    global HASH_CACHE_ENABLED
    if _HASH_CACHE_FORCED is not None:
        HASH_CACHE_ENABLED = _HASH_CACHE_FORCED
        return ""
    if cmd not in HASH_CACHE_AUTO_COMMANDS or not root:
        HASH_CACHE_ENABLED = False
        return ""
    holder = _root_lock_holder(root)
    if holder:
        HASH_CACHE_ENABLED = False
        return (f"another pipeline process (pid {holder[0]}, {holder[1] or 'unknown command'}) "
                f"holds {LOCK_FILE}: the digest cache is disabled for this audit so every byte "
                f"is read again")
    HASH_CACHE_ENABLED = True
    return ""


# ---- --skip-hash: the operator's switch for the VERIFICATION passes ---------
# `--skip-hash` skips the integrity VERIFICATION passes -- the audits that
# re-read bytes and compare them with what a finished root recorded: the
# pristine copy, the pinned champions, the published winners, every completed
# run's frozen inputs, the judge-view digests and the a1 base digest. On a big,
# trusted root that is most of the wall time of `status`/`run`/`decide`.
#
# It NEVER skips RECORDING a digest: state.json, the pins, the content
# fingerprints and every run's own corpus_digest are still computed, so content
# addressing, deduplication and the pins stay intact, and a later invocation
# WITHOUT the flag verifies exactly the same chain. The within-invocation
# FRESHNESS checks (does this sandbox still match the upstream it is about to
# hand to an agent?) are not skipped either: they decide what an agent reads,
# not what an audit believes. The flag is per invocation, OFF by default, and
# every report says the checks were SKIPPED -- never that they were verified.
SKIP_HASH_CHECKS = False


def hash_checks_skipped() -> bool:
    """True while this invocation runs with `--skip-hash`."""
    return bool(SKIP_HASH_CHECKS)


def hash_skip_note() -> str:
    """The report line for a `--skip-hash` invocation ("" while verifying)."""
    if not SKIP_HASH_CHECKS:
        return ""
    return ("--skip-hash: the integrity VERIFICATION passes were SKIPPED (the pristine copy, "
            "pinned champions, published winners, frozen run inputs, judge-view digests and the "
            "a1 base digest). Digests are still RECORDED, so a later invocation without the flag "
            "verifies the same chain.")


def configure_hash_checks(skip: bool) -> str:
    """Turn the verification passes off for THIS invocation; returns the note."""
    global SKIP_HASH_CHECKS
    SKIP_HASH_CHECKS = bool(skip)
    return hash_skip_note()


def sha256_file(p: Path) -> str:
    """SHA-256 of one file, reusing this process's cached digest when the
    file's full stat identity is unchanged (see the block comment above)."""
    key = None
    try:
        st = os.stat(p)
        key = (str(p), st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino, st.st_dev)
    except OSError:
        pass
    if HASH_CACHE_ENABLED and key is not None:
        with _HASH_CACHE_LOCK:
            hit = _HASH_CACHE.get(key)
        if hit is not None:
            return hit
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if HASH_CACHE_ENABLED and key is not None:
        with _HASH_CACHE_LOCK:
            if len(_HASH_CACHE) < _HASH_CACHE_MAX:
                _HASH_CACHE[key] = digest
    return digest


def sha256_files(paths, on_error=None) -> list:
    """Digests of `paths`, in the SAME order, hashed concurrently.

    `on_error` is returned for a file that cannot be read (callers that must
    keep such files visible pass "<unreadable>"); when it is None the OSError is
    raised, exactly as the per-file call did.
    """
    paths = list(paths)

    def one(p):
        try:
            return sha256_file(p)
        except OSError:
            if on_error is None:
                raise
            return on_error

    if len(paths) <= 1 or HASH_WORKERS <= 1:
        return [one(p) for p in paths]
    return list(_hash_pool().map(one, paths))


def _iter_tree_files(root: Path, follow_dir_links: bool = False) -> list:
    """Every file under `root`; optionally descend into EVIDENCE-area links.

    `pathlib.rglob` does NOT follow directory symlinks -- and the read-only
    evidence areas of a sandbox ARE symlinks to the root's canonical copy (see
    ensure_pristine_input). Every walk that defines a corpus, a judge view or an
    INPUT manifest must therefore ask for the followed variant explicitly, or a
    linked `raw_data/` would be invisible to the identity it is supposed to
    contribute to.

    `follow_dir_links=True` follows ONLY a TOP-LEVEL link whose name is an
    evidence area (`_followable_evidence_dir`): a nested link, or a package's
    `sub -> /outside`, is skipped, because following it put outside files in
    blinded judge views and content manifests. An ancestor-inode set keeps a
    link cycle finite.
    """
    if not root.is_dir():
        return []
    out = []

    def dir_key(p: Path):
        try:
            st = os.stat(p)
        except OSError:
            return None
        return (st.st_dev, st.st_ino)

    def _followable_evidence_dir(p: Path, top_level: bool) -> bool:
        """True for a TOP-LEVEL link to a directory shaped like the evidence area.

        `follow_dir_links=True` used to follow EVERY directory symlink, so a
        package's nested `sub -> /outside` put outside files in a blinded judge
        view and in the content manifest. Only the corpus-level
        `<root>/non_revised/<raw_data|...>` link is legitimate
        (ensure_pristine_input); the name alone never authorizes the follow.

        This walker is not handed the owning run root, so the test below is a
        TARGET-SHAPE test, not a root-identity proof: an outside tree that
        merely has the same `.../non_revised/<area>` shape is followed too. The
        strict containment proof is `is_canonical_evidence_link`, which the
        writers that DO receive the owning root (`copy_into`,
        `ensure_pristine_input`) use before following or copying a link.
        """
        if not p.is_symlink() or not top_level or not is_evidence_rel(p.name):
            return False
        try:
            target = p.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        return (target.is_dir() and target.name == p.name
                and target.parent.name == PRISTINE_DIR)

    def walk(d: Path, ancestors: frozenset) -> None:
        for p in sorted(d.iterdir()):
            if p.is_symlink() and p.is_dir():
                if not follow_dir_links or not _followable_evidence_dir(p, d == root):
                    continue
                key = dir_key(p)
                if key is None or key in ancestors:
                    continue
                walk(p, ancestors | {key})
            elif p.is_dir():
                key = dir_key(p)
                if key is None or key in ancestors:
                    continue
                walk(p, ancestors | {key})
            elif p.is_file() and not p.is_symlink():
                # A FILE symlink is not package content: copy_into() refuses it,
                # so hashing its target here made the input manifest/digest claim
                # bytes the sandbox never received -- ensure_copy/dir_matches then
                # saw a mismatch on every call and rebuilt forever.
                out.append(p)

    # Seed the ancestor set with the ROOT's own inode: a link that points back
    # at the tree being walked (canon/loop -> canon) would otherwise duplicate
    # every file once under the link's path.
    root_key = dir_key(root)
    walk(root, frozenset({root_key}) if root_key is not None else frozenset())
    return sorted(out)


def hash_manifest(dirp: Path, follow_dir_links: bool = False, exclude_top=(),
                  on_error=None) -> dict:
    """SHA-256 manifest of every file under dirp (relative posix paths).

    `on_error` is passed through to sha256_files; an integrity caller uses a
    sentinel so one unreadable file is REPORTED as changed instead of raising
    PermissionError out of every command that checks the pristine/pinned chain.
    """
    if not dirp.is_dir():
        return {"files": {}, "count": 0}
    paths = _iter_tree_files(dirp, follow_dir_links=follow_dir_links)
    if exclude_top:
        blocked = set(exclude_top)
        paths = [p for p in paths
                 if p.relative_to(dirp).parts[:1] and
                 p.relative_to(dirp).parts[0] not in blocked]
    digs = sha256_files(paths, on_error=on_error)
    files = {p.relative_to(dirp).as_posix(): d for p, d in zip(paths, digs)}
    return {"files": files, "count": len(files)}


def manifests_equal(a, b) -> bool:
    """Manifest equality on the file map (the count is derived from it)."""
    return (a or {}).get("files") == (b or {}).get("files")


def manifest_digest(m) -> str:
    payload = json.dumps(m or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def corpus_tree_manifest(dirp: Path) -> dict:
    """Manifest of a VERSION CORPUS: the read-only auxiliaries are left out.

    A difference-tracking auxiliary -- "<name>.tracking-<baseline>.<ext>"
    (baseline = original | a1 | w<k> | a<k> | winner<r>), its
    "<name>.logging-<baseline>.<ext>" fallback -- is a derived copy, not
    submission content (see AUX_FILES_RULE). Every version corpus --
    the pristine reference, the round bases, the judge targets, the pins and the
    published winners -- is defined by this same rule, so a pin can never
    disagree with the corpus a judge scored.
    """
    if not dirp.is_dir():
        return {"files": {}, "count": 0}
    paths = [p for p in _iter_tree_files(dirp, follow_dir_links=True)
             if not _is_aux_doc(p.name)]
    digs = sha256_files(paths)
    files = {p.relative_to(dirp).as_posix(): d for p, d in zip(paths, digs)}
    return {"files": files, "count": len(files)}


def corpus_dir_manifest(dirp: Path, exclude_top=()) -> dict:
    """Manifest of a MATERIALIZED version corpus (a judge target/field, a pin, a
    published winner).

    This is the corpus identity: the same rule as `corpus_manifest()`, which
    defines the digest a run records. One rule for both sides is what makes
    "the pin equals the corpus the judges scored" checkable -- mixing in the
    pipeline's own bookkeeping (which build_corpus_dir() strips, because the
    agent that wrote the version also wrote those reports) would make every pin
    verification fail.

    `exclude_top` adds the top-level exclusions of a SOURCE directory that is not
    a materialized corpus: a stage writes its process scratch INSIDE its output
    directory (`revised/work/`, `rewritten/work/`), so a code-side scan of that
    directory has to pass `CORPUS_EXCLUDE_TOP` to see the same file set the pin,
    the judge view and the recorded digest use. Left empty (the default) the
    function is byte-compatible with every digest a root has already recorded.

    This is NOT where an `is_non_shippable_name` file (the WSL/Windows
    `figS3.png:Zone.Identifier` stub, a `*.pyc`, a Word `~$` owner file) is
    filtered out. It was tried here and reverted because that changed the
    identity of every corpus built before it. The stage postcheck removes such
    files before recording a candidate's identity; publication preserves the
    pin's bytes and reports any legacy residue.
    """
    if not dirp.is_dir():
        return {"files": {}, "count": 0}

    def keep(p: Path) -> bool:
        if not p.is_file() or _is_aux_doc(p.name):
            return False
        if is_bookkeeping_name(p.name):
            return False
        if exclude_top and p.relative_to(dirp).as_posix().split("/", 1)[0] in exclude_top:
            return False
        return True

    paths = [p for p in _iter_tree_files(dirp, follow_dir_links=True) if keep(p)]
    digs = sha256_files(paths)
    files = {p.relative_to(dirp).as_posix(): d for p, d in zip(paths, digs)}
    # `count` is `len(files)`, not `len(paths)`: `manifest_digest` hashes this
    # whole dict, so a count that included a file `keep()` rejected would put
    # the junk class back into the identity through the back door (and make the
    # pin check fail again the moment a delivery-side strip ran first).
    return {"files": files, "count": len(files)}


def corpus_tree_digest(dirp: Path) -> str:
    return manifest_digest(corpus_tree_manifest(dirp))


def manifest_file_list(manifest: dict) -> list:
    """The corpus-relative PATHS of a manifest (the delivery surface, sorted).

    A manifest maps `{relative path: content digest}`; two trees can carry the
    same champion bytes and still differ in WHICH files they hand over (a
    hygiene filter that now holds one back) -- this list is that surface.
    `publish_final_clean` compares the whole MANIFESTS, not this list alone: a
    same-list/different-bytes pair used to be read as "unchanged" while the
    served directory still held the old bytes.
    """
    return sorted((manifest or {}).get("files") or [])


_JSON_SENTINELS = ("Infinity", "-Infinity", "NaN")


def _json_safe(obj):
    """Recursively make an object strict-JSON serialisable.

    RFC 8259 has no Infinity/NaN literals; json.dump would emit a bare
    `Infinity` for the +inf tie-break sentinels, which strict parsers
    (JSON.parse, jq, most CI gates) reject. They are written as the strings
    "Infinity"/"-Infinity"/"NaN" and revived by read_json(), so the pipeline
    keeps the sentinel semantics across a save/load round trip.

    A *string* with one of those exact spellings (an agent's legitimate "NaN"
    field) is escaped with a leading NUL so the revive pass returns the string
    unchanged instead of corrupting its type to float.
    """
    if isinstance(obj, str):
        return "\u0000" + obj if obj in _JSON_SENTINELS else obj
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _json_revive(obj):
    """Inverse of _json_safe (used by read_json)."""
    if isinstance(obj, str):
        if obj in ("Infinity", "-Infinity", "NaN"):
            return float("inf") if obj == "Infinity" else (
                float("-inf") if obj == "-Infinity" else float("nan"))
        if obj[:1] == "\u0000" and obj[1:] in _JSON_SENTINELS:
            return obj[1:]
    if isinstance(obj, dict):
        return {k: _json_revive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_revive(v) for v in obj]
    return obj


_TMP_SEQ = itertools.count(1)


def tmp_path_for(path: Path) -> Path:
    """A UNIQUE, exclusively-created temporary sibling for `path`.

    A fixed "<name>.tmp" is a cross-process hazard: two writers (a doubly
    started `run`, a `run` and a `retry`, a monitoring `decide`) shared the same
    temporary file, so one could rename the other's HALF-WRITTEN bytes into
    place -- or fail with FileNotFoundError because the other had already
    renamed the shared temporary away. `pid` + a process-local counter was still
    PREDICTABLE: an agent in a writable sandbox pre-created
    `PROMPT.md.<pid>.<n>.tmp` symlinks to an outside file, and the writer
    followed them. The name now carries random bits and the file is created
    here with O_CREAT|O_EXCL|O_NOFOLLOW, so a link at that path can neither be
    predicted nor followed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        tmp = path.with_name(
            f".{path.name}.{os.getpid()}.{next(_TMP_SEQ)}.{os.urandom(6).hex()}.tmp")
        try:
            fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                          | getattr(os, "O_NOFOLLOW", 0), 0o666)
        except FileExistsError:
            continue
        os.close(fd)
        return tmp
    raise OSError(f"could not create a unique temporary for {path}")


def _atomic_write_bytes(tmp: Path, dst: Path, write) -> None:
    """write(tmp) -> fsync -> os.replace(tmp, dst); remove tmp on any failure."""
    try:
        write(tmp)
        try:
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
        except OSError:
            pass                     # fsync is best-effort (some mounts refuse it)
        os.replace(tmp, dst)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, obj) -> None:
    """Write strict JSON atomically: unique .tmp, fsync, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)

    def do(p: Path) -> None:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_json_safe(obj), f, indent=2, ensure_ascii=False)
            f.flush()

    _atomic_write_bytes(tmp, path, do)


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` atomically; an existing entry (including a symlink) is
    replaced, never written through. Prompt files live in agent-writable
    sandboxes, so a planted link must not receive the orchestrator's bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)

    def do(p: Path) -> None:
        with open(p, "w", encoding=encoding) as f:
            f.write(text)

    _atomic_write_bytes(tmp, path, do)


def append_text_no_follow(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Append to a log without following a symlink planted at its path."""
    path = Path(path)
    if path.is_symlink():
        path.unlink()
    with open(path, "a", encoding=encoding) as f:
        f.write(text)


def write_csv_atomic(path, fields, rows) -> Path:
    """Write a DictWriter CSV atomically (header + rows, unique temp sibling).

    The report family wrote this block at eight call sites; one helper keeps the
    encoding/newline/replace semantics identical everywhere, including the
    crash-safe rename.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)

    def do(p: Path) -> None:
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(fields))
            w.writeheader()
            w.writerows(rows)

    _atomic_write_bytes(tmp, path, do)
    return path


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
    # Only BALANCED TOP-LEVEL values are document candidates. Trying every
    # `{`/`[` made a truncated payload quadratic: each start re-scanned to its
    # failure point, so a 64 MiB file with many braces stalled for a very long
    # time before the malformed-output retry could fire. A nested value is never
    # the document (the outer value, when it parses, is), and a start with no
    # matching close cannot parse, so recording the balanced span first keeps the
    # total decode work proportional to the text. The cap bounds the pathological
    # prose case where a file carries hundreds of `{...}` snippets.
    starts = []                      # (start, end) of balanced top-level values
    stack = []                       # expected closers, innermost last
    in_string = False
    escaped = False
    cand_start = None
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
            if not stack:
                if len(starts) >= 64:
                    break
                cand_start = i
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
                if not stack:
                    starts.append((cand_start, i + 1))
                    cand_start = None
            elif stack:
                # Mismatched prose brackets: no value can start here.
                stack.clear()
                cand_start = None
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
    best, best_len = None, -1
    for i, end, obj in found:
        json_len = end - i
        tail = text[end:].strip()
        fenced = not tail or set(tail) <= set("`~")
        prose = outside_prose(i, end)
        if not fenced and prose > 2 * json_len:
            continue
        if json_len > best_len:
            best, best_len = obj, json_len
    return best


def read_json(path: Path, revive: bool = True, lenient: bool = False):
    """Read a JSON file.

    `revive=True` (default) restores the pipeline's own Infinity/NaN sentinels and
    is only correct for files THIS pipeline writes (state.json, config, winner
    records). Agent-written files (findings.json, scores.json, markers) are read
    with `revive=False`: an agent's legitimate string "NaN" must not silently
    become a float, which would break every downstream `isinstance(x, str)` check.

    Reading is BOM-tolerant (a UTF-8 BOM is a common editor/agent artifact and
    json.load rejects it). `lenient=True` additionally recovers a complete JSON
    document that the agent wrapped in a markdown fence or prose -- see
    `_json_from_text`; callers pass it only for agent-written files, never for
    the pipeline's own state/config (those must parse exactly).
    """
    if json_file_too_big(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            # Cap the bytes ACTUALLY read: a FIFO/`/dev/zero` has st_size 0, so
            # the stat check says nothing and an unbounded read blocked the
            # orchestrator forever on an agent-planted deliverable.
            text = f.read(MAX_JSON_BYTES + 1)
    except OSError:
        return None
    if len(text) > MAX_JSON_BYTES:
        return None
    obj = _json_from_text(text, lenient)
    if obj is None:
        return None
    return _json_revive(obj) if revive else obj


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


def fmt_dur(sec) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return "-"
    if sec < 0:
        return "-"
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m{sec % 60:02d}s"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def backoff_delay(base, attempt_no: int, cap=None) -> float:
    """Exponential retry backoff: base * 2**(attempt_no-1), capped.

    `attempt_no` is the number of attempts that have already FAILED for the run,
    so the wait before attempt 2 is `base`, before attempt 3 `2*base`, before
    attempt 4 `4*base`, ... (capped by `cap`). A base of 0 disables waiting.
    """
    try:
        base, attempt_no = float(base or 0), int(attempt_no or 0)
    except (TypeError, ValueError):
        return 0.0
    if base <= 0 or attempt_no <= 0:
        return 0.0
    delay = base * (2 ** (attempt_no - 1))
    try:
        cap = float(cap or 0)
    except (TypeError, ValueError):
        cap = 0.0
    return min(delay, cap) if cap > 0 else delay


def wait_backoff(seconds: float, cap, label: str, ids: list, ctx: "Ctx" = None) -> None:
    """Sleep before a retry wave, visibly and interruptibly."""
    if seconds <= 0:
        return
    cap_note = f", cap {fmt_dur(cap)}" if cap and float(cap) > 0 else ""
    print(f"  [{label}] backoff {fmt_dur(seconds)} before retrying {', '.join(ids)} "
          f"(exponential{cap_note})")
    if ctx is not None:
        ctx.log("retry-backoff", detail=f"{round(float(seconds), 1)}s before {', '.join(ids)}")
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        print("\n[backoff] interrupted; state is saved. Re-run "
              "`run --root <root>` to continue.")
        sys.exit(130)


def is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def count_manual_steps(path: Path):
    """Count actionable items in a MANUAL_STEPS.md; None if the file is absent.

    Counts bullet/numbered lines AND Markdown table data rows (minus the header
    row of EACH table). The table branch exists because a report that lists
    manual items in a table would otherwise report 0 items. The number is
    REPORTED only (it is not a ranking key: reporting more hand-off items must
    never cost a package a round). This stays a heuristic: prose paragraphs are
    not counted, and nested bullets are counted individually.
    """
    try:
        # errors="replace", like every sibling reader: a non-UTF-8 byte raises
        # UnicodeDecodeError (a ValueError, NOT an OSError) and crashed a count
        # that exists to REPORT how much work is handed to the author.
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    # A numbered item is at most two digits: `2024. We repeated the assay.` is a
    # sentence starting with a year, not step 2024. The same pattern lets the
    # table loop below tell a bullet that happens to contain pipes from a table
    # row (the old code counted such a bullet twice).
    bullet = re.compile(r"^\s*(?:[-*+]|\d{1,2}[.)])\s+\S")
    n = sum(1 for line in lines if bullet.match(line))
    # One header row PER TABLE, not one for the whole file: subtracting a single
    # header from every table row at once over-counts by one per extra table.
    separator = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")
    in_table = False
    for line in lines:
        if bullet.match(line):
            in_table = False
            continue
        if line.count("|") >= 2 and not separator.match(line):
            if in_table:
                n += 1                  # a data row
            in_table = True             # the first row of a block is its header
        elif in_table and separator.match(line):
            continue                    # the |---| rule keeps the table open
        else:
            in_table = False
    return n


# ---------------------------------------------------------------------
# Code-side caption checking (M18) -- active only when the operator opts into the
# caption suggestion. These helpers let the ORCHESTRATOR measure the lengths
# wherever the text is extractable and to say "not verified" where it is not.
# They are a proxy (LaTeX commands and Word fields are stripped, word counts are
# whitespace-based), so the agents' own caption sweep stays authoritative for
# prose. Nothing here gates a version: see caption_gate().
# ---------------------------------------------------------------------

def _strip_latex(text: str) -> str:
    # Keep in step with paper-skills/paper-review/scripts/count_words.py: the
    # same two gaps made the two word counters disagree with each other AND
    # overcount prose. Optional arguments first (`\cite[p.5]{x}` left `[p.5]` and
    # `x` behind as prose); then inline/single-line display math (`$p<0.05$`,
    # `\(x\)`, `\[x\]`), which is not prose either.
    # `[a-zA-Z]*ref` covers the whole reference family (`\pageref{p12}`,
    # `\eqref{}`, `\autoref{}`, `\cref{}`): the bare `ref` alternative missed
    # every prefixed form, so `\pageref{p12}` left the phantom word `p12` in the
    # M19 count. And an ESCAPED dollar (`\$5`) is a literal, not math: the math
    # pattern is lookbehind-guarded, so `\$5 to \$6` no longer swallows `5 to $`.
    text = re.sub(r"\\(?:cite[a-zA-Z]*|[a-zA-Z]*ref|label|url|href)\s*"
                  r"(?:\[[^\[\]]*\]\s*)*\{[^{}]*\}", " ", text)
    # `(?:\\\\)*` consumes an EVEN run of backslashes before the math: after a
    # LaTeX line break (`\\$x$`) the dollar is still math, while `\$5` (one
    # backslash) is an escaped literal and stays prose.
    text = re.sub(r"(?<!\\)(?:\\\\)*\$\$[\s\S]*?\$\$"
                  r"|(?<!\\)(?:\\\\)*\$[^$]*\$|\\\[[\s\S]*?\\\]|"
                  r"\\\([\s\S]*?\\\)", " ",
                  text)
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)
    return re.sub(r"\s+", " ", text.replace("{", " ").replace("}", " ")).strip()


def count_words(text: str) -> int:
    """The pipeline's word definition, used for EVERY word count it reports.

    A word is a maximal run of NON-SPACE characters, with a newline treated as
    space (and, for the same reason, tabs and other whitespace). "state-of-the-
    art" is ONE word, "2026" is ONE word, and an abbreviation with an inner
    space ("et al.") is two. Nothing else is normalised here: callers that need
    LaTeX commands or Word field instructions removed strip them first.
    """
    return len(re.findall(r"\S+", text or ""))


def count_caption_words(text: str) -> int:
    return count_words(_strip_latex(text or ""))


def _docx_visible_nodes(el):
    """Descendants of `el` as Word renders them: ONE AlternateContent branch.

    `mc:AlternateContent` carries the same text in a Choice and a Fallback.
    Walking every descendant read both, doubling the paragraph text and every
    count derived from it. A nested `w:p` (a text box's own paragraph) is a
    separate entry of the paragraph walk, so it is not folded into this one.
    """
    mc = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for child in list(el):
        if child.tag == mc + "AlternateContent":
            branch = child.find(mc + "Choice")
            if branch is None:
                branch = child.find(mc + "Fallback")
            if branch is not None:
                yield from _docx_visible_nodes(branch)
            continue
        if child.tag == w + "p":
            continue
        yield child
        yield from _docx_visible_nodes(child)


def _docx_visible_paragraphs(el, ns: str, mc: str):
    """The `w:p` elements Word renders, in document order.

    Only ONE AlternateContent branch is walked, so the paragraphs inside an
    `mc:Fallback` are never returned. Nested paragraphs (a text box's content)
    are yielded after their containing paragraph, so each is its own entry.
    """
    for child in list(el):
        if child.tag == mc + "AlternateContent":
            branch = child.find(mc + "Choice")
            if branch is None:
                branch = child.find(mc + "Fallback")
            if branch is not None:
                yield from _docx_visible_paragraphs(branch, ns, mc)
            continue
        if child.tag == ns + "p":
            yield child
        yield from _docx_visible_paragraphs(child, ns, mc)


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


def _docx_paragraphs(path: Path):
    """Paragraph texts of a .docx, or None when it cannot be parsed.

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
    out = []
    for para in _docx_visible_paragraphs(root, ns, mc):
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


def _tex_captions(text: str) -> list:
    """Texts of \\caption / \\captionof with brace balancing.

    Handles the optional arguments of both forms:
      \\caption[short]{long}                 (optional short title)
      \\captionof{figure}[short]{long}       (optional type AND short title)
    Missing the bracketed argument was a real false negative: a LaTeX caption the
    scan never saw was reported as "within the suggested length".
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
        out.append(text[i + 1:j])
    return out


def _caption_match(line: str, kinds=("figure",)):
    """(label prefix, regex match) for one caption line, or (None, None).

    `kinds` is the set of caption kinds the caller recognises. The M18 legend
    scan asks for figures only; the M19 subtraction adds table captions when the
    venue profile excludes them.
    """
    if "figure" in kinds:
        m = CAPTION_START_RE.match(line)
        if m:
            return "Figure", m
    if "table" in kinds:
        m = TABLE_CAPTION_START_RE.match(line)
        if m:
            return "Table", m
    return None, None


def _caption_units(texts, with_spans: bool = False, kinds=("figure",)) -> list:
    """(label, text) -- or (label, text, start, end) -- for docx paragraph captions.

    The paragraph index span is what lets the M19 subtraction stay inside the
    main-text span: a legend that sits after the Methods heading is not part of
    the text the main-text count is measuring, so subtracting it there would
    under-report the main text.
    """
    units = []
    for i, t in enumerate(texts):
        t = (t or "").strip()
        prefix, m = _caption_match(t, kinds)
        if m:
            label = f"{prefix} {m.group(1)}"
            units.append((label, t, i, i + 1) if with_spans else (label, t))
    return units


def _caption_units_from_lines(lines, with_spans: bool = False, kinds=("figure",)) -> list:
    """(label, text) for line-oriented captions (md/txt); continuation lines merged.

    A caption that wraps over several lines has to be counted in full: counting
    only the first line under-reports the word count. Continuation stops at a
    blank line, a heading (markdown's ``#`` or a bound section name, the SAME
    test ``caption_ranges`` in count_words.py uses), the start of another
    caption, or -- when the caption
    already ends in sentence-final punctuation -- at a line that starts in column
    0 with further prose (that is usually the next paragraph; merging it made a
    short legend look far longer than it is). An INDENTED continuation is always
    kept, because indentation is how a wrapped legend usually continues.

    In ``with_spans`` mode each unit carries its (start, end) line span, which
    the M19 subtraction intersects with the main-text span.
    """
    units, cur, start = [], None, None
    for idx, raw in enumerate(lines):
        line = (raw or "").strip()
        if not line:
            if cur:
                units.append((cur[0], cur[1], start, idx) if with_spans else cur)
                cur = None
            continue
        prefix, m = _caption_match(line, kinds)
        if m:
            if cur:
                units.append((cur[0], cur[1], start, idx) if with_spans else cur)
            cur = (f"{prefix} {m.group(1)}", line)
            start = idx
            continue
        indented = bool(raw) and raw[:1].isspace()
        sentence_done = bool(re.search(r"[.!?]\s*$", cur[1])) if cur else False
        if cur is not None and not line.startswith("#") \
                and not CAPTION_SUSPECT_RE.match(line) \
                and not LENGTH_SECTION_BOUND_RE.match(line) \
                and (indented or not sentence_done):
            cur = (cur[0], cur[1] + " " + line)
            continue
        if cur:
            units.append((cur[0], cur[1], start, idx) if with_spans else cur)
            cur = None
    if cur:
        units.append((cur[0], cur[1], start, len(lines)) if with_spans else cur)
    return units


def _caption_suspects(texts) -> list:
    """Caption-looking lines the strict pattern did not recognise."""
    out = []
    for t in texts:
        t = (t or "").strip()
        if not t or CAPTION_START_RE.match(t):
            continue
        if CAPTION_SUSPECT_RE.match(t):
            out.append(t[:120])
    return out


def corpus_source_overrides(sources: list) -> list:
    """Per source, the corpus-relative paths a LATER source also provides.

    corpus_manifest() and build_corpus_dir() let a later source override an
    earlier one for the same relative path (that is how a candidate's own
    revised/code/ wins over code/). The caption scan and the document-set
    comparison have to see the same corpus, otherwise one file is counted twice.
    """
    def keys_of(src, prefix, excluded):
        ks = set()
        if not src.is_dir():
            return ks
        for p in _iter_tree_files(src, follow_dir_links=True):
            if not p.is_file() or _is_aux_doc(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            ks.add(prefix + rel)
        return ks

    per_source = [keys_of(*s) for s in sources]
    out, later = [], set()
    for ks in reversed(per_source):
        out.append(set(later))
        later |= ks
    return list(reversed(out))


def scan_captions_in_sources(sources: list, limit=None) -> dict:
    """Caption scan over [(dir, prefix, excluded_top)] corpus sources.

    `limit` is the SUGGESTED length the rows are compared against (0 = no
    suggestion, the default). Nothing in this pipeline is gated on the result:
    over-limit captions are reported, never enforced. Pipeline bookkeeping files
    (CHANGELOG/MANUAL_STEPS/REVISION_REPORT/…) are skipped: a caption quoted
    inside a changelog is not a manuscript caption. Lines that LOOK like a
    figure caption but are not recognised by the strict pattern are reported
    under "suspected" instead of being dropped silently, so a scanner miss stays
    visible to the operator.
    """
    limit = DEFAULT_CAPTION_LIMIT if limit is None else max(0, int(limit))
    overrides = corpus_source_overrides(sources)
    captions, unparsed, docs, suspects = [], [], set(), []
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        for p in _iter_tree_files(src, follow_dir_links=True):
            if not p.is_file():
                continue
            if is_non_document_name(p.name):
                # tracked-changes auxiliaries duplicate their parent's captions,
                # and a Word owner / OS stub is not a document at all (without
                # this the caption scan reported "1 file(s) not parseable" for a
                # 162-byte `~$…docx` and a legend count for a `:Zone.Identifier`).
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if (prefix + rel) in overrides[i]:
                continue                      # a later source provides this path
            if is_bookkeeping_name(p.name):
                continue                      # pipeline bookkeeping, not submission
            if is_non_manuscript_rel(rel):
                # Evidence areas AND feedback/response documents anywhere are
                # not submission text: a data table, a reviewer's report or an
                # editor's decision letter can print "Figure 1" without carrying
                # a manuscript caption (M18 enumerates the submission's legends).
                continue
            doc = prefix + rel
            ext = p.suffix.lower()
            units = None
            if ext in CAPTION_DOCX_EXTS:
                paras = _docx_paragraphs(p)
                units = None if paras is None else _caption_units(paras)
                if paras:
                    suspects.extend(_caption_suspects(paras))
            elif ext in CAPTION_TEX_EXTS:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                units = []
                for idx, cap in enumerate(_tex_captions(text), 1):
                    m = CAPTION_START_RE.match(cap.strip())
                    units.append((f"Figure {m.group(1)}" if m else f"caption {idx}", cap))
                # a \caption the strict pattern did not recognise must stay visible
                suspects.extend(_caption_suspects(text.splitlines()))
            elif ext in CAPTION_TEXT_EXTS:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                lines = text.splitlines()
                units = _caption_units_from_lines(lines)
                suspects.extend(_caption_suspects(lines))
            elif ext in CAPTION_UNPARSED_EXTS:
                unparsed.append(doc)
                continue
            else:
                continue
            if units is None:
                unparsed.append(doc)
                continue
            if units:
                docs.add(doc)
            for label, text in units:
                w = count_caption_words(text)
                captions.append({"document": doc, "caption": label, "words": w,
                                 "over_limit": bool(limit) and w > limit,
                                 "excerpt": re.sub(r"\s+", " ", text)[:80]})
    over = [c for c in captions if c["over_limit"]]
    return {"limit": limit, "rule_enabled": bool(limit),
            "captions": captions, "count": len(captions),
            "over_limit": over, "unparsed": sorted(set(unparsed)),
            "suspected": suspects[:50], "suspected_count": len(suspects),
            "files_with_captions": sorted(docs), "checked": bool(captions)}


def scan_version_captions(ctx: Ctx, r: int, vid: str) -> dict:
    return scan_captions_in_sources(corpus_sources(ctx, r, vid),
                                    limit=caption_limit_of(ctx))


def caption_info_for(ctx: Ctx, r: int, vid: str):
    """The recorded caption scan for a version (no rescan when recorded)."""
    if vid == ORIGINAL_ID:
        info = ctx.state.get("original_captions")
    elif is_fresh_vid(vid):
        info = (ctx.run(rid_for_fresh(r, vid)) or {}).get("captions")
    else:
        info = (find_pin(ctx, vid) or {}).get("captions")
    return info if isinstance(info, dict) else None


def caption_gate(info) -> tuple:
    """(within_suggestion, note) for the advisory legend check (M18).

    The name is kept for the recorded-state schema, but this is no longer a
    gate: the boolean is advisory information ("within the suggested length or
    not") and NOTHING in the pipeline may use it to drop, rank down, fail or
    reject a version. An over-limit caption is reported; the package stays fully
    eligible, exactly like the master prompt's cover-letter word rule.
    """
    if not info:
        return True, "captions: not verified (no scan recorded)"
    limit = int(info.get("limit", DEFAULT_CAPTION_LIMIT) or 0)
    if not info.get("rule_enabled", bool(limit)):
        n = int(info.get("count") or 0)
        note = (f"legend lengths: {n} legend(s) counted; no proxy cap configured -- the venue "
                f"profile publishes no per-type legend number, so the author compares the counts")
        if info.get("unparsed"):
            note += (f"; {len(info['unparsed'])} file(s) could not be parsed (legend length not "
                     f"verified there -- manual item)")
        return True, note
    n_over = len(info.get("over_limit") or [])
    if n_over:
        note = (f"captions: {n_over} caption(s) over the suggested {limit} words "
                f"(advisory only -- a reporting rule of this pipeline, never a gate; "
                f"report/compress by removing redundancy only)")
        return False, note
    elif not info.get("checked"):
        note = "captions: no extractable captions found"
    else:
        note = f"captions: {info.get('count', 0)} within the suggested {limit}-word limit"
    n_susp = int(info.get("suspected_count") or 0)
    if n_susp:
        note += (f"; {n_susp} figure-like line(s) were NOT recognised as captions "
                 f"(verify M18 manually)")
    return True, note


# ---------------------------------------------------------------------
# Code-side abstract/main-text length scan (M19).
#
# The agents' M19 sweep is authoritative (they read the packages in full); this
# scan gives the operator a deterministic count over the corpus at setup and
# over the pinned winner at `decide`. It is a PROXY:
#   * only documents whose text is extractable are counted (.docx/.tex/.md/.txt);
#     legacy .doc/.rtf are reported as "unparsed", PDF/slide renderings and
#     supplementary-named files are listed as "skipped" (the journal's article
#     caps apply to the article, not to supplementary information);
#   * the abstract is counted only when an "Abstract" heading (or a LaTeX
#     abstract environment) is found, and it ends at the abstract's own
#     paragraph (blank-line boundary), a Keywords line, or the next heading --
#     whichever comes first. In a .tex source the abstract environment's own
#     \end{abstract} is the boundary and wins over any blank line inside it;
#   * a document is only counted as a manuscript when it has an Abstract heading
#     or an Introduction/Main-text heading -- a supplementary table dump or a
#     Methods-only file is skipped rather than counted as a "main text" it is
#     not. A cover-letter document is detected (name or opening salutation) and
#     gets its own row for the PERSUADING part against the user's 300-500-word
#     preference (NBT publishes no cover-letter limit);
#   * when no editable manuscript or cover letter exists and the text lives only
#     in renderings (.pdf/.ppt), the affected files are returned as
#     "needs_manual" so the operator must convert/count them -- they are never
#     silently treated as "clean";
#   * the main text runs from the end of the abstract (or from the start of the
#     document when there is no abstract heading) to the first Methods /
#     References / Figure-legends / Acknowledgements heading, minus the figure
#     captions INSIDE that span (a legend after Methods is not part of the text
#     the count already stopped at), and the row says which text was counted.
#     When no end heading is found the count runs to the end of the document
#     and the row says so.
# Nothing here gates a version: over-cap rows are reported, never enforced.
# ---------------------------------------------------------------------

LENGTH_DOCX_EXTS = (".docx",)
LENGTH_TEX_EXTS = (".tex", ".ltx")
LENGTH_TEXT_EXTS = (".md", ".txt", ".markdown", ".rst")
LENGTH_UNPARSED_EXTS = (".doc", ".rtf")
LENGTH_RENDERED_EXTS = (".pdf", ".ppt", ".pptx")

LENGTH_ABSTRACT_HEAD_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary)\s*[:.\u2014\u2013-]?\s*$", re.I)
# The common inline layout: "Abstract: We studied ..." on one line. The heading
# must be recognised or the abstract is left inside the main text; the rest of
# the line is its first paragraph (count_words.py has the same branch).
LENGTH_ABSTRACT_INLINE_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary)\s*[:.\u2014\u2013-]\s*(\S.*)$",
    re.I)
LENGTH_MAIN_START_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:introduction|main text|background)\s*[:.\u2014\u2013-]?\s*$",
    re.I)
LENGTH_SECTION_BOUND_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:abstract|summary|keywords?|introduction|background|"
    r"results?|discussion|conclusions?|materials (?:and|&) methods|online methods?|methods?|"
    r"star methods|experimental procedures|"
    r"references?|bibliography|(?:literature|works) cited|figure legends?|acknowledg\w*|"
    r"author contributions?|"
    r"(?:data|code) availability|competing interests?|conflicts? of interest|funding|"
    r"supplementary (?:information|materials?|methods|figures|tables|notes?))"
    r"\s*[:.\u2014\u2013-]?\s*$", re.I)
# The SAME boundary headings, classified by the section kind that a profile's
# `counting.main_text.excludes` names. The scan ends the main-text span at the
# first boundary heading whose kind the venue EXCLUDES; a kind the venue counts
# (Frontiers counts Methods) does not end it, and legends are not subtracted
# when the venue counts them.
LENGTH_SECTION_KIND_RES = (
    ("methods", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:materials (?:and|&) methods|online methods?|methods?|"
        r"star methods|experimental procedures)\s*(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("references", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:references?|bibliography|"
        r"(?:literature|works) cited)\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("figure-legends", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?figure legends?\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("acknowledgements", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?acknowledg\w*\s*(?:[:.\u2014\u2013-]\s*|\s*$)",
        re.I)),
    ("author-contributions", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?author contributions?\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("data-availability", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:data|code) availability\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("competing-interests", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:competing interests?|conflicts? of interest)\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("funding", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?funding\s*(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
    ("supplementary", re.compile(
        r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?supplementary "
        r"(?:information|materials?|methods|figures|tables|notes?)\s*"
        r"(?:[:.\u2014\u2013-]\s*|\s*$)", re.I)),
)


def _length_heading_text(line: str) -> str:
    """A heading line with a Markdown ATX prefix removed.

    The M19 scan reads .md too, and `## Methods` is the same heading as
    `Methods`; the anchored patterns saw the hashes as text and never matched,
    so the excluded section stayed in the count.
    """
    return re.sub(r"^\s*#{1,6}\s+", "", (line or "").strip())


def _length_section_kind(line: str) -> str:
    """The M19 counting-convention kind of a boundary heading ("" when not one)."""
    text = _length_heading_text(line)
    if not text:
        return ""
    for kind, pattern in LENGTH_SECTION_KIND_RES:
        if pattern.match(text):
            return kind
    return ""


LENGTH_KEYWORDS_RE = re.compile(
    # The optional section number is the one thing count_words.KEYWORDS accepts
    # that this twin used to reject: "2 Keywords: ..." was body text here and a
    # keyword boundary there, so the two M19 counters disagreed on the abstract.
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:key\s?words?)\s*(?:[:.\u2014\u2013-]|$)", re.I)
LENGTH_COVER_SALUTATION_RE = re.compile(
    r"^\s*(?:dear\b|to the (?:editor|editors)\b)", re.I)
LENGTH_COVER_CLOSING_RE = re.compile(
    # A closing phrase must END the line's sentence: `\b` alone matched a body
    # line that merely STARTS with "Regards the statistical concern, ..." or
    # "Best regards are due to ...", cutting the persuading body at that line.
    # A comma/period after the phrase still closes ("Sincerely, The Authors").
    r"^\s*(?:sincerely|yours (?:sincerely|faithfully|truly)|best regards|kind regards|regards|"
    r"with (?:best|kind) regards)\s*[,.;!]?\s*$|"
    # A BARE courtesy line closes the letter; "Thank you for considering our
    # manuscript ..." is a body OPENER. The old bare `|thank you)\b` alternative
    # matched that opener and reported 0 persuading words (see count_words.py,
    # whose COVER_CLOSING carries the same rule).
    r"^\s*thank you(?:\s+(?:very much|again))?[.,!]?\s*$", re.I)
LENGTH_COVER_DISCLOSURE_RE = re.compile(
    r"^\s*(?:manuscript title|title|authors?|author list|affiliations?|corresponding author|"
    r"running title|related manuscripts?|prior discussions?|suggested reviewers?|"
    r"excluded reviewers?|reviewers?|double-anonymized|orcid|competing interests?|"
    r"data availability|word counts?)\s*[:.\u2014\u2013-]", re.I)


TEX_CAPTION_TOKEN_RE = re.compile(
    r"\\(?:captionof\*?\s*\{[^{}]*\}\s*(?:\[[^\]]*\]\s*)?"
    r"|caption\*?\s*(?:\[[^\]]*\]\s*)?)\{")
# LaTeX scaffolding the length scan must not count as prose: environment tokens
# (\begin{document}, \end{figure}) and the arguments of setup/graphics commands
# used to leak literal words ("document", "article", "fig1.pdf") into the
# main-text count.
TEX_ENV_TOKEN_RE = re.compile(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\s*\[[^\]]*\])?")
TEX_SCAFFOLD_RE = re.compile(
    r"\\(?:documentclass|usepackage|RequirePackage|bibliography|bibliographystyle|"
    r"includegraphics|includesvg|input|include|vspace|hspace|setlength|geometry|"
    r"graphicspath|hypersetup|newcommand|renewcommand)\*?(?:\[[^\]]*\])?"
    r"(?:\{[^{}]*\})*")
# A LaTeX comment: an UNESCAPED ``%`` and everything after it on the line.
# The escape count is what matters: ``\%`` is a literal percent sign (prose),
# while ``\\%`` is a line break followed by a comment. The old ``(?<!\\)%``
# looked at ONE preceding backslash, so every ``\\%`` kept its comment text and
# the length/style scans counted it as the authors' prose.
TEX_COMMENT_RE = re.compile(r"(?<!\\)((?:\\\\)*)%.*$", re.M)


def strip_tex_comment(text: str) -> str:
    """`text` without its LaTeX comments (the escape pair kept in place)."""
    return TEX_COMMENT_RE.sub(r"\1", text or "")


def _tex_brace_delta(text: str) -> int:
    """Unescaped ``{`` minus unescaped ``}`` in `text`."""
    delta, esc = 0, False
    for ch in text:
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1
    return delta


# Display-math environments: the twin of count_words.TEX_MATH_ENV. Their
# `\begin`/`\end` tokens were stripped but the BODY was counted as the authors'
# prose, drifting a .tex count upward against the venue cap.
TEX_MATH_ENV_RE = re.compile(
    r"\\begin\{(equation\*?|align\*?|alignat\*?|eqnarray\*?|gather\*?|multline\*?|"
    r"displaymath|math|split|flalign\*?)\}[\s\S]*?\\end\{\1\}", re.M)


def blank_math_environments(text: str) -> str:
    """`text` without the bodies of display-math environments (newlines kept)."""
    return TEX_MATH_ENV_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text or "")


def _tex_split_group(text: str):
    """(inside, after) for the rest of a ``{...}`` group whose ``{`` was consumed.

    `text` starts INSIDE the group (the caller matched up to and including the
    opening brace), so the depth starts at 1; an unclosed group returns the
    whole text as ``inside`` and an empty remainder.
    """
    depth, esc = 1, False
    for i, ch in enumerate(text):
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[:i], text[i + 1:]
    return text, ""


def _tex_line_text(line: str) -> str:
    """Prose of one LaTeX line: environment tokens and command arguments gone."""
    return _strip_latex(TEX_SCAFFOLD_RE.sub(" ", TEX_ENV_TOKEN_RE.sub(" ", line)))


def text_source_paragraphs(path: Path) -> list:
    """Prose paragraphs of a TEXT source (.tex/.md/.txt) for the style rules.

    LaTeX scaffolding is stripped the same way the length scan strips it, so the
    citation/parenthesis/repetition rules see prose, not markup. Paragraphs are
    split on blank lines and sectioning commands; a source written as one huge
    paragraph simply becomes one long paragraph (the repetition rule skips those).
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if path.suffix.lower() in (".tex", ".ltx"):
        raw = strip_tex_comment(raw)
        raw = blank_math_environments(raw)
        raw = TEX_ENV_TOKEN_RE.sub("\n\n", raw)
        raw = re.sub(r"\\(?:section|subsection|subsubsection|paragraph|chapter)\*?"
                     r"\s*\{[^{}]*\}", "\n\n", raw)
        raw = raw.replace("~", " ")          # LaTeX non-breaking space
        # `_strip_latex` collapses ALL whitespace, including the blank lines
        # the paragraph split depends on. Split first, then strip each chunk:
        # the reverse order merged a whole .tex source into one paragraph and
        # made every per-paragraph ledger see one row per file.
        paras = []
        for chunk in re.split(r"\n\s*\n", raw):
            text = re.sub(r"\s+", " ", _strip_latex(chunk)).strip()
            if text:
                paras.append(text)
        return paras
    paras = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"\n\s*\n", raw)]
    return [p for p in paras if p]


def _tex_length_scan(text: str):
    """(lines, caption_spans, abstract_end) for a LaTeX source.

    ``lines`` are the heading/paragraph lines the length scan works on. LaTeX
    states two boundaries that plain text leaves implicit, so they are tracked
    here instead of being guessed from blank lines:

      * a ``\\caption``/``\\captionof`` group is a legend even though its text
        carries no "Figure N" label (the label is generated at typesetting
        time): its text becomes its own line, so the span-subtraction equals the
        legend's word count and text sharing that source line still counts;
      * ``\\end{abstract}`` ends the abstract, whatever paragraph breaks it
        contains, and any text on the ``\\begin{abstract}`` line belongs to it
        (a one-line abstract used to be replaced by the bare heading and lost).
    """
    out, captions, abstract_end = [], [], None
    raw_lines = blank_math_environments(text or "").splitlines()
    i, n = 0, len(raw_lines)
    while i < n:
        raw = raw_lines[i]
        i += 1
        line = strip_tex_comment(raw).strip()
        begins = re.search(r"\\begin\{abstract\}", line)
        ends = re.search(r"\\end\{abstract\}", line)
        if begins or ends:
            # Both environment tokens may sit ANYWHERE on the line: a one-line
            # abstract is `\begin{abstract} ... \end{abstract}`, and the usual
            # ending is `Last sentence.\end{abstract}`. The old start-anchored
            # tests honoured only a token at position 0, so on the usual ending
            # `abstract_end` stayed unset, the NEXT paragraph was counted as
            # abstract text and the main-text count lost it.
            if begins:
                out.append("Abstract")
            head_from = begins.end() if begins else 0
            if ends is None:
                rest = _tex_line_text(line[head_from:])
                if rest:
                    out.append(rest)
            else:
                head = _tex_line_text(line[head_from:ends.start()])
                if head:
                    out.append(head)
                abstract_end = len(out)
                after = _tex_line_text(line[ends.end():])
                if after:
                    out.append(after)
            continue
        if re.search(r"\\begin\s*\{thebibliography\}", line) \
                or re.search(r"\\bibliography\s*\{", line):
            # The reference list is not main text when the venue excludes
            # references. `\begin{thebibliography}` is stripped as an environment
            # token and `\bibliography{...}` as scaffold, so without this heading
            # every entry stayed inside the main-text span (the count_words twin
            # already inserted it).
            out.append("References")
            continue
        m = re.match(r"\\(?:sub)*section\*?(?:\[[^\]]*\])?\{([^{}]*)\}", line)
        if m:
            out.append(m.group(1).strip())
            continue
        cap = TEX_CAPTION_TOKEN_RE.search(line)
        if cap:
            # Text before the caption stays prose; the caption's own group
            # (which may wrap over several source lines) becomes one line, so
            # subtracting its span never removes a neighbouring word.
            before = _tex_line_text(line[:cap.start()])
            if before:
                out.append(before)
            group = line[cap.end():]
            depth = 1 + _tex_brace_delta(group)
            while depth > 0 and i < n:
                nxt = strip_tex_comment(raw_lines[i]).strip()
                i += 1
                group = f"{group}\n{nxt}"
                depth += _tex_brace_delta(nxt)
            cap_text, after = _tex_split_group(group)
            captions.append((len(out), len(out) + 1))
            out.append(_strip_latex(cap_text))
            after = _tex_line_text(after)
            if after:
                out.append(after)
            continue
        stripped = _tex_line_text(line)
        if stripped:
            out.append(stripped)
    return out, captions, abstract_end


def _tex_length_lines(text: str) -> list:
    """LaTeX source as heading/paragraph lines for the length scan."""
    return _tex_length_scan(text)[0]


def _length_rows_for_lines(lines: list, doc: str, caption_spans=None,
                           abstract_end: int = None, limits: dict = None,
                           whole_doc_as_main: bool = False, counting: dict = None) -> list:
    """M19 rows (abstract and/or main text) for one document's text lines.

    ``caption_spans`` are (start, end) line spans of the document's captions and
    ``abstract_end`` an explicit end index (LaTeX's ``\\end{abstract}``); only
    the captions inside the main-text span are subtracted, because only those
    words are inside the text this row counts.

    ``counting`` is the venue/article type's main-text counting convention
    (`VenueProfile.counting()`): its `main_text.excludes` names the section
    kinds the venue leaves OUT of its count, so a venue that counts Methods
    (Frontiers) or the abstract/references/legends (NBT Brief Communication)
    is counted the way its own rule says, not the NBT Article way.

    ``whole_doc_as_main`` is for a document the run's OWN article type names
    (`Correspondence.docx`, `letter-to-the-editor.docx`): a letter-format
    manuscript carries no Abstract/Introduction heading, but the venue's cap
    for that type still applies, so its whole text is counted instead of being
    skipped as unshaped.
    """
    limits = limits or length_limits()
    counting = counting or {"main_text": {"excludes": list(DEFAULT_MAIN_TEXT_EXCLUDES)}}
    excludes = set((counting.get("main_text") or {}).get("excludes") or [])
    include_abstract = "abstract" not in excludes
    subtract_captions = ("figure-legends" in excludes
                         or "table-captions" in excludes)
    n = len(lines)

    def clean(s):
        return (s or "").strip()

    abs_start = abs_end = None
    inline_abs = False
    for i in range(n):
        heading = _length_heading_text(lines[i])
        inline = LENGTH_ABSTRACT_INLINE_RE.match(heading)
        if inline:
            # Keep the remainder as the abstract's first paragraph; the
            # heading itself is not text.
            lines[i] = inline.group(1)
            abs_start, inline_abs = i, True
            break
        if LENGTH_ABSTRACT_HEAD_RE.match(heading):
            abs_start = i + 1
            break
    if abs_start is not None:
        if abstract_end is not None:
            abs_end = max(abs_start, min(int(abstract_end), n))
        else:
            j = abs_start
            seen_text = inline_abs
            first_blank = None
            boundary = False
            while j < n:
                line = clean(lines[j])
                heading = _length_heading_text(line)
                if LENGTH_SECTION_BOUND_RE.match(heading) or \
                        LENGTH_MAIN_START_RE.match(heading) or LENGTH_KEYWORDS_RE.match(heading):
                    boundary = True
                    break
                if not line:
                    if seen_text and first_blank is None:
                        first_blank = j
                    j += 1              # leading blanks right after the heading
                    continue
                seen_text = True
                j += 1
            # A multi-paragraph abstract is legitimate; only a document
            # with no section boundary at all falls back to its first
            # blank line, so the later paragraphs are not charged to the
            # main text.
            if not boundary and first_blank is not None:
                j = first_blank
            abs_end = j
    main_start = None
    for i in range(n):
        if LENGTH_MAIN_START_RE.match(_length_heading_text(lines[i])):
            main_start = i + 1
            break
    if abs_start is None and main_start is None:
        if not whole_doc_as_main and not include_abstract:
            return []                # not manuscript-shaped: skip, never guess
        if whole_doc_as_main:
            # A document the run's own article type names (Correspondence, a
            # letter to the editor) carries no Abstract/Introduction heading by
            # design: the type's cap applies to its WHOLE text (the LT4
            # contract), so this branch stays unfiltered.
            caption_words = 0
            if subtract_captions:
                caption_words = sum(
                    count_caption_words(" ".join(lines[max(a, 0):min(b, n)]))
                    for a, b in (caption_spans or []) if a < n and b > 0)
            words = max(0, count_words(" ".join(lines)) - caption_words)
            main_cap = limits["main text"].get("cap")
            return [{"document": doc, "section": "main text", "words": words,
                     "relaxation": limits["main text"].get("relaxation"),
                     "cap": main_cap,
                     "over_limit": main_cap is not None and words > main_cap,
                     "note": ("no Abstract/Introduction heading found: this document carries "
                              "the selected article type's own name, so the whole text is "
                              "counted against the main-text cap")}]
        # A venue that counts the abstract inside the main text (the NBT Brief
        # Communication: "contains no headings") starts at line 0, but it does
        # NOT thereby count the whole document: the same excluded-kind end scan
        # and body filtering below apply, so back matter the profile leaves out
        # (acknowledgements, references, funding, ...) is not charged to the
        # main-text cap. Falling through to the shaped path keeps the two
        # counters (count_words.py and this scan) on one span.
    rows = []
    if abs_start is not None:
        words = count_words(" ".join(lines[abs_start:abs_end]))
        abs_cap = limits["abstract"].get("cap")
        rows.append({"document": doc, "section": "abstract", "words": words,
                     "relaxation": limits["abstract"].get("relaxation"),
                     "cap": abs_cap,
                     "over_limit": abs_cap is not None and words > abs_cap, "note": ""})
    # The main-text span starts after an excluded abstract; when the venue counts
    # the abstract INSIDE the main text, it starts at the abstract's own text.
    if abs_start is not None:
        start = abs_start if include_abstract else abs_end
    elif main_start is not None:
        start = main_start
    else:
        start = 0 if include_abstract else None
    # The abstract block ends ON the next heading line ("Introduction" in most
    # venues' Articles, which is written without a heading in the final layout).
    # Build the counted set line by line: an excluded section heading starts a
    # skip, and a later heading whose kind the venue does NOT exclude resumes
    # the count. Truncating at the first excluded heading dropped a Results or
    # Discussion section after a mid-paper Methods block even though the
    # profile says that kind is inside the count.
    span_start = start or 0
    included = [False] * n
    excluded_now = False
    end_found = False
    in_keyword_block = False
    for i in range(span_start, n):
        line = clean(lines[i])
        heading = _length_heading_text(line)
        if LENGTH_KEYWORDS_RE.match(heading):
            # A Keywords line is a boundary, not a section kind: the generic
            # branch below reset `excluded_now` for it, which put the keyword
            # list (and any Methods prose after it) back into the main-text
            # count. count_words.py's M19 counter already keeps the state; this
            # is the same rule for the deterministic scan.
            in_keyword_block = True
            excluded_now = True
            continue
        if in_keyword_block and not heading:
            in_keyword_block = False
            excluded_now = False
            continue
        if in_keyword_block and not (LENGTH_SECTION_BOUND_RE.match(heading)
                                     or LENGTH_MAIN_START_RE.match(heading)):
            continue
        if LENGTH_SECTION_BOUND_RE.match(heading) or \
                LENGTH_MAIN_START_RE.match(heading):
            in_keyword_block = False
            kind = _length_section_kind(heading)
            if kind and kind in excludes:
                excluded_now = True
                end_found = True
            else:
                excluded_now = False
            continue
        included[i] = not excluded_now
    body = [lines[i] for i in range(span_start, n) if included[i]]
    caption_words = 0
    if subtract_captions:
        caption_words = sum(
            count_caption_words(" ".join(lines[max(a, span_start):min(b, n)]))
            for a, b in (caption_spans or [])
            if a < n and b > span_start
            and any(included[i] for i in range(max(a, span_start), min(b, n)))
        )
    words = max(0, count_words(" ".join(body)) - caption_words)
    notes = []
    if abs_start is None:
        if main_start is None:
            notes.append("no Abstract/Introduction heading found; the count starts at the "
                         "beginning of the document (title/author block included)")
        else:
            notes.append("no Abstract heading found; the count starts after the main-text "
                         "heading (title/author block excluded)")
    if not end_found:
        if set(excludes) != set(DEFAULT_MAIN_TEXT_EXCLUDES):
            notes.append("counted through the sections the venue includes; no excluded "
                         "section heading found")
        else:
            notes.append("no Methods/References/legends heading found; the count runs to the end "
                         "of the document")
    if caption_words:
        notes.append(f"{int(caption_words)} caption word(s) subtracted")
    counting_inside = [kind for kind in ("abstract", "methods", "references", "figure-legends")
                       if kind not in excludes]
    if counting_inside:
        notes.append("the venue's counting rule includes "
                     + ", ".join(kind.replace("-", " ") for kind in counting_inside)
                     + " in the main text")
    main_cap = limits["main text"].get("cap")
    rows.append({"document": doc, "section": "main text", "words": words,
                 "relaxation": limits["main text"].get("relaxation"),
                 "cap": main_cap,
                 "over_limit": main_cap is not None and words > main_cap,
                 "note": "; ".join(notes)})
    return rows


def _is_cover_letter_lines(lines: list, name: str = "", manuscript_names=()) -> bool:
    """A cover-letter document: by name, or by an opening salutation.

    `manuscript_names` are the run's own article-type spellings: a Letter to
    the Editor MANUSCRIPT opens with the same salutation a cover letter does,
    so the selected type's own document name outranks the salutation test.
    """
    if _name_is_article_type_manuscript(name, manuscript_names):
        return False
    tokens = _document_role_tokens(name)
    if "cover" in tokens or "coverletter" in tokens or "letter" in tokens:
        return True
    for raw in lines[:12]:
        if LENGTH_COVER_SALUTATION_RE.match((raw or "").strip()):
            return True
    return False


def _cover_letter_row(lines: list, doc: str, limits: dict = None, profile=None) -> dict:
    """One M19 row for a cover letter's PERSUADING part (a user preference).

    The configured venue profile states no official cover-letter word limit, so
    the profile's range is the master prompt's own preference and is reported as
    such. The persuading part excludes the salutation, the signature block and
    the required disclosure lines (manuscript metadata, related manuscripts,
    reviewer suggestions, ...).
    """
    limits = limits or length_limits()
    prof = _as_profile(profile)
    cover = limits["cover letter"]
    pref_min, pref_max = cover.get("min"), cover.get("max")
    start = 0
    for i, raw in enumerate(lines[:12]):
        if LENGTH_COVER_SALUTATION_RE.match((raw or "").strip()):
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if LENGTH_COVER_CLOSING_RE.match((lines[i] or "").strip()):
            end = i
            break
    body = [ln for ln in lines[start:end]
            if not LENGTH_COVER_DISCLOSURE_RE.match((ln or "").strip())]
    words = count_words(" ".join(body))
    # The letter's TOTAL content is the operator's cap: every line counts
    # (salutation, body, disclosures and signature), unlike the persuading-part
    # preference above.
    total_words = count_words(" ".join(lines))
    total_max = cover.get("total_max")
    over_total = total_max is not None and total_words > total_max
    within = ((pref_min is None or words >= pref_min)
              and (pref_max is None or words <= pref_max))
    pref_text = _cover_bound_text(pref_min, pref_max)
    if pref_min is not None and pref_max is not None:
        pref_clause = (f"; the {pref_min}-{pref_max} range is the user's preference, not "
                       f"{_indefinite(prof.short)} limit")
    elif pref_text:
        pref_clause = (f"; the user's preference is {pref_text}, not "
                       f"{_indefinite(prof.short)} limit")
    else:
        pref_clause = "; this venue profile configures no cover-letter preference"
    return {"document": doc, "section": "cover letter", "words": words,
            "total_words": total_words, "total_max": total_max,
            "relaxation": None, "cap": None,
            "min": pref_min, "max": pref_max,
            "within_preference": within,
            # `over_limit` is the TOTAL-content cap only: the 300-500
            # persuading range is a preference, not a venue cap, and marking it
            # over_limit made `decide` warn about a "relaxed caps (cap None)"
            # breach for a merely long letter.
            "over_limit": over_total,
            "over_total_cap": over_total,
            "over_preference": pref_max is not None and words > pref_max,
            "under_preference": pref_min is not None and words < pref_min,
            "source": cover.get("source") or "",
            "note": (f"persuading part only (salutation, signature and required disclosures "
                     f"excluded)"
                     + pref_clause
                     + (f"; TOTAL content {total_words} words against the operator's "
                        f"{total_max}-word cap" if total_max is not None else ""))}


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
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        for p in _iter_tree_files(src):
            # `_iter_tree_files` is the corpus walker: a file symlink is not
            # package content (copy_into refuses it), so a scan that followed
            # one verified a corpus the materializer never produced.
            if _is_aux_doc(p.name) or is_bookkeeping_name(p.name) \
                    or is_non_submitted_readme_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
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
                paras = _docx_paragraphs(p)
                if paras is None:
                    unparsed.append(doc)
                    continue
                lines = paras
                caption_spans = [(a, b) for _, _, a, b
                                 in _caption_units(paras, with_spans=True,
                                                   kinds=caption_kinds)]
            elif ext in LENGTH_TEX_EXTS:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                lines, caption_spans, abstract_end = _tex_length_scan(text)
            elif ext in LENGTH_TEXT_EXTS:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
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
    over = [r for r in rows if r["over_limit"]]
    return {"limits": limits, "counting": prof.counting, "source": source,
            "venue": prof.id,
            "rows": rows, "count": len(rows), "over_limit": over,
            "unparsed": sorted(set(unparsed)), "skipped": sorted(set(skipped)),
            "rendered": sorted(set(rendered)),
            "needs_manual": sorted(set(rendered)) if not rows else [],
            "documents": sorted(docs), "checked": bool(rows)}


def length_note(info) -> str:
    """One line describing an M19 scan and the package-level consequence.

    A venue profile with no caps prints the counts and says so instead of
    naming a cap: the comparison is then the target journal's own guidelines'
    job, exactly as the M19 mandates say. Length is advisory for ranking and
    candidate eligibility; an over-cap final package is not submission-ready.
    """
    if not info:
        return "not verified (no scan recorded)"
    if info.get("error"):
        return f"not verified -- the length scan failed ({info['error']})"
    rows = info.get("rows") or []
    limits = info.get("limits") or length_limits()
    if not rows:
        if info.get("needs_manual"):
            return ("not verified -- no editable manuscript or cover letter was found; the text "
                    "lives in non-editable file(s): " + ", ".join(info["needs_manual"][:4])
                    + " (the author must convert/count it; the agents' M19 sweep is authoritative)")
        return ("no manuscript-shaped document found to count "
                "(the agents' M19 sweep is authoritative)")
    parts = []
    for r in rows:
        if r["section"] == "cover letter":
            parts.append(f"cover letter {r.get('total_words', r['words'])} words total"
                         + (" OVER-TOTAL-CAP" if r.get("over_total_cap") else "")
                         + ("" if r.get("within_preference") else " OUTSIDE-PREFERENCE"))
        else:
            parts.append(f"{r['section'].replace('main text', 'main-text')} {r['words']} words"
                         + (" OVER" if r.get("over_limit") else ""))
    over_n = len([r for r in rows if r.get("over_limit")])
    pref_n = len([r for r in rows if r["section"] == "cover letter"
                  and not r.get("within_preference")])
    abs_cap, main_cap = limits["abstract"].get("cap"), limits["main text"].get("cap")
    cover_cap = limits["cover letter"].get("total_max")
    caps_text = (f"caps: abstract {abs_cap if abs_cap is not None else 'none'}, "
                 f"main text {main_cap if main_cap is not None else 'none'}"
                 + (f", cover letter TOTAL {cover_cap}" if cover_cap is not None else ""))
    if abs_cap is None and main_cap is None and cover_cap is None:
        caps_text = ("no venue cap configured: the counts are recorded for the author to compare "
                     "with the target journal's own guidelines")
    tail = (f"; {over_n} over the cap (advisory for ranking -- never a word-count gate; "
            f"an over-cap FINAL package is NOT submission-ready; compress by removing "
            f"redundancy only)" if over_n else "; all within the relaxed caps")
    cover_min = limits["cover letter"].get("min")
    cover_max = limits["cover letter"].get("max")
    if pref_n:
        # Name the venue the preference is NOT: "not an NBT limit" for the
        # default profile, the generic noun when the profile has no brand. A
        # one-sided profile is printed as that side ("at most 200 words"), never
        # as "None-200" or "no preference".
        preference_owner = "a venue limit"
        venue_id = str(info.get("venue") or "").strip()
        if venue_id:
            try:
                preference_owner = f"{_indefinite(load_venue_profile(venue_id).short)} limit"
            except VenueProfileError:
                pass
        if cover_min is not None and cover_max is not None:
            pref_label = f"the user's {cover_min}-{cover_max}-word preference"
        else:
            pref_label = (f"the user's cover-letter preference "
                          f"({_cover_bound_text(cover_min, cover_max)})")
        tail += (f"; {pref_n} cover letter(s) outside {pref_label} (the user's preference, "
                 f"not {preference_owner}, never a gate)")
    return (f"{len(rows)} section(s) "
            f"[{', '.join(parts[:6])}] ({caps_text}{tail})")


# ---------------------------------------------------------------------
# Code-side OOXML style/formatting scan (companion module).
#
# The corpus converters read text only, so character formatting and pagination
# are invisible to every agent: the round-2 final package shipped a break-only
# paragraph that rendered as a blank page, journal italics that lived half
# inside a Zotero bibliography field, the same URL hyperlinked in one section
# and plain in another, and mixed straight/curly apostrophes. This scan reports
# those classes (and the mechanical ones `paper_docx_format.py fix` can repair).
# It never gates on its own: `decide --format-gate` turns the high-severity
# findings into decision problems.
# ---------------------------------------------------------------------

_FORMAT_MODULE_CACHE = {}


def _format_module():
    """The companion module loaded from next to this script (or None)."""
    path = Path(__file__).resolve().with_name(DOCX_FORMAT_MODULE)
    if not path.is_file():
        return None
    cached = _FORMAT_MODULE_CACHE.get(str(path))
    if cached is not None:
        return cached
    import importlib.util
    spec = importlib.util.spec_from_file_location("paper_docx_format", str(path))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _FORMAT_MODULE_CACHE[str(path)] = mod
    return mod


def format_policy_of(ctx: Ctx) -> dict:
    """The formatting policy: module defaults + the venue's table rule + config.

    The venue's DISPLAY rules (`tables` and `figures`) ride in the same policy
    dict the formatter reads, so the code-side scan checks exactly what the
    venue profile declares and a profile that declares none for a kind gets no
    rows for it. An operator's own `format_policy.tables` / `.figures` in
    `pipeline_config.json` wins over the profile's block, exactly like every
    other policy key.

    The policy also carries the venue TEMPLATE's own blank-paragraph slots
    (`empty_paragraph_slots`), derived from the journal's official Word
    template(s), so the stray-empty-paragraph rule can tell a template spacer
    (the blank the template carries above the title, a placeholder between two
    headings) from an author's extra blank line. No template -> no slots, and
    the rule still exempts anything before the first non-empty paragraph.

    `cover_letter` carries the cover-letter rule's DATA: the manuscript
    template's own front-matter style ids and header/footer part hashes, plus
    the venue's cover-letter template when it ships one. The scan's FMT-CL1 rule
    uses it to PROVE that a letter was formatted in the manuscript template.
    """
    mod = _format_module()
    policy = dict(getattr(mod, "POLICY_DEFAULTS", {}) or {}) if mod else {}
    configured = (ctx.cfg or {}).get("format_policy") or {}
    policy.update(configured)
    for key, block in _venue_display_blocks(ctx).items():
        if key not in configured:
            policy[key] = copy.deepcopy(block)
    if "min_image_dpi" not in configured:
        _dpi = (policy.get("image_dpi") or {}).get("min_dpi")
        if _dpi:
            policy["min_image_dpi"] = float(_dpi)
    if "empty_paragraph_slots" not in configured:
        policy["empty_paragraph_slots"] = _venue_empty_paragraph_slots(ctx)
    if "cover_letter" not in configured:
        policy["cover_letter"] = _venue_cover_letter_block(ctx)
    # The venue's own reference-entry preference (`flag_preprints`) and its
    # display-item numbering convention (`numbering`), plus the leftover-phrase
    # list another publisher's boilerplate is matched against. All three are
    # profile data; an operator's `format_policy.<key>` still wins.
    for key, block in _venue_reference_blocks(ctx).items():
        if key not in configured:
            policy[key] = copy.deepcopy(block)
    return policy


def publication_format_policy(ctx: Ctx, policy: dict, cli_flatten: bool = False) -> tuple:
    """(publication policy, whether a Zotero flatten was requested).

    Publication preserves the judged bytes, so a flatten request cannot be
    executed there. `pre_judge_format_policy` translates the recorded publish
    preference into the stage-side formatter; a command-line request arriving
    at `decide` is refused explicitly. By default the published copy keeps LIVE
    Zotero fields, and unlinking them remains the author's own final step.

    This helper remains the one parser for the legacy `cli_flatten` flag and
    `format_policy.unlink_zotero_fields_at_publish`; callers use its second
    value to report or refuse a request whose timing is incompatible with the
    pin.
    """
    cfg = (ctx.cfg or {}).get("format_policy") or {}
    if cli_flatten:
        flatten = True
    elif "unlink_zotero_fields_at_publish" in cfg:
        flatten = bool(cfg.get("unlink_zotero_fields_at_publish"))
    else:
        flatten = DEFAULT_PUBLISH_FLATTEN_ZOTERO
    out = dict(policy)
    if flatten:
        out["unlink_zotero_fields"] = True
    return out, flatten


def _venue_reference_blocks(ctx: Ctx) -> dict:
    """The reference/numbering/leftover keys the venue profile declares.

    Every key is optional and ABSENT when the profile does not declare it, so a
    venue that states no numbering convention and lists no leftover phrase gets
    no `FMT-O1`/`FMT-L1` rows (the "never invent a rule" contract of
    `venue_profiles/README.md`). The values are copied verbatim from the
    profile: `references` ({"flag_preprints": bool}), `numbering`
    ("citation" or ""), `leftover_phrases` (list of strings). Memoized exactly
    like `_venue_display_blocks`: `format_policy_of` runs on every scan and
    every stage postcheck, and resolving the venue profile is not free.
    """
    cfg = _ctx_cfg(ctx)
    key = (id(cfg), id(cfg.get("venue_profile")), venue_id_of(ctx),
           str(cfg.get("article_type") or ""))
    cached = getattr(ctx, "_venue_reference_blocks", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    prof = venue_profile_of(ctx, required=False)
    data = getattr(prof, "data", {}) or {}
    out: dict = {}
    refs = data.get("references")
    if isinstance(refs, dict):
        out["references"] = {"flag_preprints": bool(refs.get("flag_preprints"))}
    numbering = str(data.get("numbering") or "").strip().lower()
    if numbering:
        out["numbering"] = numbering
    phrases = data.get("leftover_phrases")
    if isinstance(phrases, (list, tuple)):
        out["leftover_phrases"] = [str(p) for p in phrases if str(p).strip()]
    try:
        ctx._venue_reference_blocks = (key, out)
    except Exception:                                       # noqa: BLE001 -- stub ctx
        pass
    return out


def _venue_cover_letter_block(ctx: Ctx) -> dict:
    """The cover-letter rule's data, derived from the venue's OWN templates.

    `{}` when the venue ships no Word template (nothing to compare against);
    `{"manuscript_template", "manuscript_front_matter_styles",
    "manuscript_furniture_hashes", "cover_template"}` otherwise. A venue that
    ships its own cover-letter template puts its name in `cover_template` and
    the scan's FMT-CL1 rule stands down: that file governs the letter.
    Memoized like the other venue-level blocks (it opens the template package).
    """
    cfg = _ctx_cfg(ctx)
    # The block now also carries the SELECTED article type's name spellings, so
    # the key includes the recorded type (`set-article-type` rewrites it).
    key = (id(cfg), id(cfg.get("venue_profile")), venue_id_of(ctx),
           str(cfg.get("article_type") or ""))
    cached = getattr(ctx, "_venue_cover_block", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    block: dict = {}
    try:
        tpls = venue_word_templates(ctx) or {}
        main = tpls.get("main")
        cover = tpls.get("cover")
        styles = sorted(_manuscript_front_matter_styles(Path(main))) if main else []
        hashes = []
        if main:
            for name, digest in (_protected_template_parts(Path(main)) or {}).items():
                # Only the header/footer parts: a journal logo, a running head or
                # a page-number footer copied byte-identically is proof of the
                # manuscript-template restyle, while theme/fontTable bytes are
                # too generic (two default-theme documents can share them).
                if re.match(r"word/(header|footer)\w*\.xml$", name):
                    hashes.append(digest)
        if styles or hashes or cover:
            block = {"manuscript_template": Path(main).name if main else "",
                     "manuscript_front_matter_styles": styles,
                     "manuscript_furniture_hashes": sorted(set(hashes)),
                     "cover_template": Path(cover).name if cover else "",
                     # The selected article type's own name spellings: a
                     # document named for the type is that type's MANUSCRIPT,
                     # never the cover letter the FMT-CL1 rule hunts for.
                     "manuscript_article_type_names": article_type_manuscript_names(ctx)}
    except Exception:                                         # noqa: BLE001 -- never gate setup
        block = {}
    try:
        ctx._venue_cover_block = (key, block)
    except Exception:                                         # noqa: BLE001 -- stub ctx
        pass
    return block


def _venue_empty_paragraph_slots(ctx: Ctx) -> list:
    """The signature triples of the venue templates' own empty paragraphs.

    Memoized like `_venue_display_blocks`: reading the small template packages
    is cheap but `format_policy_of` runs on every scan and postcheck. A venue
    with no official Word template contributes no slots.
    """
    cfg = _ctx_cfg(ctx)
    key = (id(cfg), id(cfg.get("venue_profile")), venue_id_of(ctx))
    cached = getattr(ctx, "_venue_empty_slots", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    slots = []
    mod = _format_module()
    fn = getattr(mod, "empty_paragraph_slots_from_template", None) if mod else None
    if fn is not None:
        try:
            for p in (venue_word_templates(ctx) or {}).values():
                for sig in fn(p) or []:
                    if sig not in slots:
                        slots.append(sig)
        except Exception:                                     # noqa: BLE001 -- never gate setup
            slots = []
    try:
        ctx._venue_empty_slots = (key, slots)
    except Exception:                                         # noqa: BLE001 -- stub ctx
        pass
    return slots


def _venue_display_blocks(ctx: Ctx) -> dict:
    """The venue's declared `tables`/`figures` blocks, memoized for this ctx.

    `format_policy_of` runs on every scan and every stage postcheck, and
    resolving the venue profile (parse + deep-copy + validate the recorded
    snapshot) is not free; the memo keeps that cost off the hot path and is
    invalidated whenever the config object, its recorded snapshot, the venue id
    or the article type changes (the identity-based key a `set-venue`/
    `set-article-type` in one process replaces).
    """
    cfg = _ctx_cfg(ctx)
    key = (id(cfg), id(cfg.get("venue_profile")), venue_id_of(ctx),
           str(cfg.get("article_type") or ""))
    cached = getattr(ctx, "_venue_display_blocks", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    blocks: dict = {}
    prof = venue_profile_of(ctx, required=False)
    if prof is not None:
        for name in ("tables", "figures"):
            block = prof.data.get(name) or {}
            if _declares_display_rule(block):
                blocks[name] = copy.deepcopy(block)
        # The venue's recorded figure-type minimum (Nature 5 pt, Frontiers 8 pt)
        # is a measured rule, not a formatting preference: carry it into the
        # format policy so FMT-IM6 runs with the venue's own number and source.
        figure_text = prof.data.get("figure_text") or {}
        if isinstance(figure_text, dict) and figure_text.get("min_pt"):
            blocks["figure_text"] = copy.deepcopy(figure_text)
        image_dpi = prof.data.get("image_dpi") or {}
        if isinstance(image_dpi, dict) and image_dpi.get("min_dpi"):
            blocks["image_dpi"] = copy.deepcopy(image_dpi)
    try:
        ctx._venue_display_blocks = (key, blocks)
    except Exception:                                       # noqa: BLE001 -- stub ctx
        pass
    return blocks


# The three TEXT-level consistency rules (citation dialect, US/UK spelling,
# attributive hyphenation) are the one judge-visible class the fixer used to
# equalize for every version before judging: with the same policy at setup and
# in every stage postcheck, no arm could ever be seen to have made a package
# consistent. They are therefore applied at PUBLICATION only (the published
# final copy keeps the configured policy); the pre-judge paths run with them set
# to `keep`, so the corpus the panel reads still carries the difference and the
# arm that repaired it can be scored for it. Mechanical OOXML repairs (blank
# page, legend spacing, keepNext, hyperlink/proofing treatment) are unaffected.
TEXT_CONSISTENCY_KEYS = ("citation_journal_names", "term_spelling", "term_hyphenation")


def pre_judge_format_policy(ctx: Ctx) -> dict:
    """format_policy_of() with the text-level consistency rules left unfixed."""
    policy = format_policy_of(ctx)
    configured = (ctx.cfg or {}).get("format_policy") or {}
    if configured.get("unlink_zotero_fields_at_publish"):
        # The old publication-time flatten cannot run after the panel has
        # scored the bytes: the delivered package must remain the pin. Apply
        # the request to every candidate before it is fingerprinted instead.
        policy["unlink_zotero_fields"] = True
    for key in TEXT_CONSISTENCY_KEYS:
        policy[key] = "keep"
    return policy


def _files_under_ci(dirp: Path, suffixes) -> list:
    """Files under `dirp` whose extension matches case-INsensitively.

    `Path.rglob("*.pdf")` is case-sensitive on Linux, so a Reporting Summary
    saved as `REPORTING_SUMMARY.PDF` (or a Word-authored `REPORT.DOCX`) was
    invisible to every scan while the corpus carried it. Symlinks are not
    submission content (see `copy_into`) and are not followed here either.
    """
    want = {s.lower() for s in suffixes}
    return sorted({p for p in Path(dirp).rglob("*")
                   if p.is_file() and not p.is_symlink()
                   and p.suffix.lower() in want})


def _docx_files_under(dirp: Path) -> list:
    """Every .docx under a directory, EITHER extension case (and mixed case)."""
    return _files_under_ci(dirp, (".docx",))


def scan_format_in_sources(sources: list, policy=None) -> dict:
    """Style/formatting findings over [(dir, prefix, excluded_top)] sources.

    A code-side PROXY for the review's category-4 (technical formatting) checks:
    it reports the OOXML facts the text-only corpus drops -- break-only
    paragraphs, blank pages, header-on-title-page, tracked changes and proofing
    marks, hand-formatted legend spacing, heading style drift, unintended
    italics (with Zotero field protection), mixed URL/email treatment, mixed
    quotation marks and em-dash density. Never gates anything by itself.

    The TEXT-level consistency rules (`FMT-T8a..e`: citation formats, nested
    parentheses, redundancy, spelling/hyphenation variants) run over the LaTeX
    and markdown sources too, so a package-wide problem is found in the .tex as
    well as in the .docx files -- the reference list of a docx is skipped, and
    text sources are report-only (they are edited by the agents, not the
    fixer).
    """
    mod = _format_module()
    if mod is None:
        return {"files": [], "rows": [], "by_rule": {}, "high": 0, "medium": 0, "low": 0,
                "unavailable": f"{DOCX_FORMAT_MODULE} not found next to the pipeline script"}
    resolved = dict(getattr(mod, "POLICY_DEFAULTS", {}) or {})
    resolved.update(policy or {})
    policy = resolved
    # The same "a later source overrides the earlier one" filter the caption and
    # length scanners apply: without it a path provided by two sources (a
    # candidate's own revised/code/ over code/) was reported from BOTH copies --
    # one of them a file the corpus builder never ships.
    overrides = corpus_source_overrides(sources)
    docs, rows = [], []
    # Every submitted surface's text, for the cross-document claim check at the
    # end of the sweep. The CNB Reporting Summary and the neohet supplement are
    # separate documents from the main text; a contradiction between them is
    # invisible to a per-file scan, so collect first and compare once.
    claim_docs = []
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        # The package's OWN README declares the submitted set (`Only ... will be
        # submitted`). A format sweep is about the submission surface: a carried
        # README/MANUAL_STEPS/raw-data file is not manuscript prose, and gating a
        # revision on it was a real false failure (a 667-word hand-off README
        # produced an FMT-T9i row). When no declaration is honoured, every file
        # counts as before.
        _decl, is_submitted = declared_submission_filter(src)
        for p in _docx_files_under(src):
            if not p.is_file() or is_non_document_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if not is_submitted(rel):
                continue                      # carried, never submitted
            if (prefix + rel) in overrides[i]:
                continue                      # a later source provides this path
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if is_non_manuscript_rel(rel):
                # Evidence areas and feedback/response documents are inputs: a
                # reviewer's .docx report is not a submission file whose OOXML
                # style the M20 scan may report (and it may be mode-locked).
                continue
            if "work" in rel.split("/")[:-1]:
                continue                      # stage scratch is never corpus content
            if is_bookkeeping_name(p.name) or is_non_submitted_readme_name(p.name):
                continue
            info = mod.analyse_package(p, policy)
            for r in info.get("rows") or []:
                r["document"] = prefix + r["document"]
            docs.append(info)
            rows.extend(info.get("rows") or [])
            try:
                with zipfile.ZipFile(p) as z:
                    dxml = z.read("word/document.xml").decode("utf-8", "replace")
                claim_docs.append((prefix + rel, "\n".join(
                    mod.text_of(pp[2]) for pp in mod.paragraphs(dxml))))
            except (KeyError, zipfile.BadZipFile, OSError, RuntimeError,
                    NotImplementedError):
                pass
        # TEXT sources (LaTeX/markdown/plain text): the same consistency rules,
        # report-only -- the agents edit these files, the OOXML fixer does not.
        # `.bib` is a TEXT source too (2026-10-15): the CNB supplementary
        # bibliography -- the file the journal compiles its reference list from --
        # carried comma-glued keyword lists ("DNA aneuploidy,Molecular subtyping")
        # and no scan read it at all.
        for p in _files_under_ci(src, (".tex", ".ltx", ".md", ".markdown",
                                       ".txt", ".bib")):
            if _is_aux_doc(p.name) or is_bookkeeping_name(p.name) \
                    or is_non_submitted_readme_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if not is_submitted(rel):
                continue                      # carried, never submitted
            if (prefix + rel) in overrides[i]:
                continue                      # a later source provides this path
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if is_non_manuscript_rel(rel):
                continue        # evidence area, not submission prose (see above)
            if "work" in rel.split("/")[:-1]:
                continue
            if p.suffix.lower() == ".bib":
                # A .bib is a DATABASE: its abstract/keyword/DOI fields are
                # quotations, not the authors' prose. The CNB scan filed 44
                # long-sentence rows on `abstract = {...}` fields.
                try:
                    paras = mod.bib_prose_paragraphs(p.read_text("utf-8", "replace"))
                except OSError:
                    paras = []
            else:
                paras = text_source_paragraphs(p)
            claim_docs.append((prefix + rel, "\n".join(paras)))
            text_rows = list(mod.text_style_rows(paras))
            if p.suffix.lower() in (".tex", ".ltx"):
                # The siunitx rule only has meaning in a LaTeX source (a DOCX
                # cannot carry \qty{}{}), and it is the rule the operator asked
                # for by name: a value+unit outside siunitx is a finding-tier row.
                text_rows += mod.latex_number_rows("\n".join(paras))
                # The venue's table-caption rule over a LaTeX float (placement
                # is the renderer's, so the text scan checks the caption only).
                text_rows += mod.display_rule_rows_from_text("\n".join(paras), policy,
                                                             prefix + rel)
            for r in text_rows:
                rows.append({"rule": r["rule"], "severity": r["severity"],
                             "document": prefix + rel, "location": "document",
                             "evidence": r["evidence"], "detail": r["detail"],
                             "fix": "editorial", "protected": False,
                             "tier": r.get("tier") or mod.tier_of(r["rule"])})
        # PDF SUBMISSIONS. The CNB supplement and the Reporting Summary are the
        # documents the journal actually reads as PDFs; before 2026-10-19 the
        # scan opened only DOCX/text, so the supplement's Table S3 arithmetic,
        # the Summary's unanswered "Eukaryotic cell lines" field and every
        # availability claim in them were outside the sweep.
        _pdf_tool = shutil.which("pdftotext")
        for p in _files_under_ci(src, (".pdf",)):
            if _is_aux_doc(p.name) or is_bookkeeping_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if not is_submitted(rel):
                continue
            if (prefix + rel) in overrides[i]:
                continue
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if is_non_manuscript_rel(rel):
                continue
            if "work" in rel.split("/")[:-1]:
                continue
            if not _pdf_tool:
                # A missing poppler is an ENVIRONMENT gap, not a clean PDF.
                # Record it per unexamined file (rule 8) instead of letting the
                # absence of rows read as "no PDF findings".
                rows.append({
                    "rule": "FMT-PDF0", "severity": "low",
                    "document": prefix + rel, "location": "PDF text scan",
                    "evidence": "pdftotext is not installed",
                    "detail": ("the PDF text class (logic/count/availability/statistics/"
                               "Reporting Summary claims) was NOT examined for this file; "
                               "install poppler-utils or read the PDF against the submitted "
                               "surfaces"),
                    "fix": "manual", "protected": False, "tier": "advisory"})
                continue
            text, pdf_error = _pdf_text_info(p)
            if not text:
                # An image-only PDF has no reader-visible prose to scan; the
                # visual checks own its figures. The PDF path is a text scan,
                # never a claim that the document is clean. A pdftotext FAILURE
                # (corrupt/encrypted/unsupported PDF) is NOT image-only: its text
                # class was not examined, so record the gap instead of silence.
                if pdf_error:
                    rows.append({
                        "rule": "FMT-PDF0", "severity": "low",
                        "document": prefix + rel, "location": "PDF text scan",
                        "evidence": f"pdftotext failed: {pdf_error}",
                        "detail": ("the PDF text class (logic/count/availability/statistics/"
                                   "Reporting Summary claims) was NOT examined for this file; "
                                   "repair the PDF or read it against the submitted surfaces"),
                        "fix": "manual", "protected": False, "tier": "advisory"})
                continue
            claim_docs.append((prefix + rel, text))
            pdf_paras = [" ".join(block.split())
                         for block in re.split(r"\n\s*\n", text) if block.strip()]
            # Targeted rules only: a PDF is a rendered document, not the
            # manuscript source, and running the full text-style sweep over 52
            # pages produced 170 long-sentence rows that buried the three real
            # findings. The argument-level rules and the statistics/summary
            # checks are the ones that need the reader-visible PDF text.
            for _fn in ("logic_rows", "count_claim_rows", "legend_claim_rows"):
                _f = getattr(mod, _fn, None)
                if _f is None:
                    continue
                try:
                    for r in _f(pdf_paras):
                        rows.append({"rule": r["rule"], "severity": r["severity"],
                                     "document": prefix + rel, "location": "document",
                                     "evidence": r["evidence"], "detail": r["detail"],
                                     "fix": "editorial", "protected": False,
                                     "tier": r.get("tier") or mod.tier_of(r["rule"])})
                except Exception:                                     # noqa: BLE001
                    pass
            if hasattr(mod, "availability_claim_rows"):
                for r in mod.availability_claim_rows(pdf_paras, prefix + rel):
                    r["document"] = prefix + rel
                    rows.append(r)
            if hasattr(mod, "stats_floor_rows"):
                for r in mod.stats_floor_rows(text.splitlines()):
                    r["document"] = prefix + rel
                    rows.append(r)
            if (hasattr(mod, "reporting_summary_gap_rows")
                    and re.search(r"reporting[-_ ]?summary", p.name, re.I)):
                for r in mod.reporting_summary_gap_rows(text):
                    r["document"] = prefix + rel
                    rows.append(r)
        # FIGURE LABELS (FMT-IM5): OCR the submitted figure rasters and compare
        # their words with the manuscript's own vocabulary. Only declared
        # figures, never an evidence area; a missing OCR engine is recorded as a
        # gap by the rule itself. FMT-IM4 is NOT OCR: `figure_ocr=false` must
        # not switch off a deterministic resolution check, so the image loop
        # runs either way and only FMT-IM5/FMT-IM6 are gated below.
        ocr_on = policy.get("figure_ocr", True)
        images = []
        try:
            for q in _iter_tree_files(src):
                if q.suffix.lower() not in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
                    continue
                rel = q.relative_to(src).as_posix()
                if not is_submitted(rel) or is_evidence_rel(rel):
                    continue
                if (prefix + rel) in overrides[i]:
                    continue                  # a later source provides this path
                if excluded and rel.split("/", 1)[0] in excluded:
                    continue
                if "work" in rel.split("/")[:-1]:
                    continue                  # stage scratch is never corpus content
                if _is_aux_doc(q.name) or is_bookkeeping_name(q.name) \
                        or is_non_submitted_readme_name(q.name):
                    continue
                images.append(q)
        except Exception as e:                                        # noqa: BLE001
            rows.append({
                "rule": "FMT-IM4", "severity": "low",
                "document": prefix + "figures", "location": "artwork",
                "evidence": f"the figure scan failed: {type(e).__name__}: {e}",
                "detail": ("the figure resolution/OCR classes were NOT examined in this "
                           "sweep; re-run the scan or inspect the submitted figures"),
                "fix": "manual", "protected": False, "tier": "advisory"})
        if images:
            try:
                width = float(policy.get("figure_print_width_in") or 6.5)
            except (TypeError, ValueError):
                width = 6.5
                rows.append({
                    "rule": "FMT-IM4", "severity": "low",
                    "document": prefix + "figures", "location": "artwork",
                    "evidence": "figure_print_width_in is not numeric",
                    "detail": ("the figure-text-size class used the 6.5 in default because the "
                               "policy value is not a number; re-run after fixing the policy"),
                    "fix": "manual", "protected": False, "tier": "advisory"})
            if ocr_on:
                try:
                    texts = []
                    for p in _docx_files_under(src):
                        rel = p.relative_to(src).as_posix()
                        # The SAME filters as the image loop above: evidence
                        # (read-only review feedback), a later source's
                        # override, an excluded top, scratch and non-content
                        # names are not "the manuscript's own vocabulary".
                        if not is_submitted(rel) or is_evidence_rel(rel):
                            continue
                        if (prefix + rel) in overrides[i]:
                            continue
                        if excluded and rel.split("/", 1)[0] in excluded:
                            continue
                        if "work" in rel.split("/")[:-1]:
                            continue
                        if _is_aux_doc(p.name) or is_bookkeeping_name(p.name) \
                                or is_non_submitted_readme_name(p.name):
                            continue
                        try:
                            with zipfile.ZipFile(p) as z:
                                dxml = z.read("word/document.xml").decode("utf-8", "replace")
                            texts.append("\n".join(mod.text_of(pp[2])
                                                    for pp in mod.paragraphs(dxml)))
                        except (KeyError, zipfile.BadZipFile, OSError, RuntimeError,
                                NotImplementedError):
                            continue
                    for r in mod.figure_label_rows(images, mod.vocabulary_terms(texts)):
                        r["document"] = prefix + r["document"]
                        rows.append(r)
                    if hasattr(mod, "figure_text_size_for_image"):
                        for q in images:
                            try:
                                for r in mod.figure_text_size_for_image(q, width, policy):
                                    r["document"] = prefix + r["document"]
                                    rows.append(r)
                            except Exception:                         # noqa: BLE001
                                continue
                except Exception as e:                                    # noqa: BLE001
                    # OCR is a sampling pass, never a reason to abort the sweep; an
                    # unexpected failure is still a RECORDED gap (rule 8), not a
                    # silent pass over the figure-label class.
                    rows.append({
                        "rule": "FMT-IM5", "severity": "low",
                        "document": prefix + "figures", "location": "artwork text",
                        "evidence": f"the figure-label OCR pass failed: {type(e).__name__}: {e}",
                        "detail": ("the figure-label class was NOT examined in this sweep; "
                                   "re-run the scan / install tesseract and inspect the "
                                   "submitted figures"),
                        "fix": "manual", "protected": False, "tier": "advisory"})
            else:
                try:
                    min_text_pt = float(policy.get("min_figure_text_pt")
                                        or (policy.get("figure_text") or {}).get("min_pt")
                                        or 0)
                except (TypeError, ValueError):
                    min_text_pt = 0.0
                    rows.append({
                        "rule": "FMT-IM6", "severity": "low",
                        "document": prefix + "figures", "location": "artwork text",
                        "evidence": "min_figure_text_pt is not numeric",
                        "detail": ("the figure-text-size class was not examined because the "
                                   "policy value is not a number"),
                        "fix": "manual", "protected": False, "tier": "advisory"})
                if min_text_pt > 0:
                    # OCR is the only way to measure FMT-IM6. When the operator
                    # deliberately turns OCR off, the class is a recorded gap rather
                    # than a silent pass.
                    rows.append({
                        "rule": "FMT-IM6", "severity": "low",
                        "document": prefix + "figures", "location": "artwork text",
                        "evidence": "figure_ocr is off",
                        "detail": ("the figure-text-size class (FMT-IM6) was NOT examined: "
                                   "measure the artwork's type at the printed width or re-run "
                                   "with figure_ocr on"),
                        "fix": "manual", "protected": False, "tier": "advisory"})
            # FMT-IM4 needs no OCR and is always checked.
            if hasattr(mod, "image_resolution_rows"):
                for q in images:
                    try:
                        for r in mod.image_resolution_rows(q, width, policy):
                            r["document"] = prefix + r["document"]
                            rows.append(r)
                    except Exception:                             # noqa: BLE001
                        continue
    # CROSS-SURFACE CLAIMS (J6/FMT-AV4): compare the submitted surfaces once,
    # after every DOCX/text/PDF paragraph has been collected. A per-file scan
    # cannot see the supplement saying "shipped" while the main text says "not
    # in the repository", or the Summary saying "no overlap" while Methods say
    # the threshold was tuned on evaluated data.
    if claim_docs and hasattr(mod, "claim_contradiction_rows"):
        try:
            rows.extend(mod.claim_contradiction_rows(claim_docs))
        except Exception as e:                                        # noqa: BLE001
            rows.append({
                "rule": "J6-CONTRADICTION", "severity": "low",
                "document": "cross-surface", "location": "claim scan",
                "evidence": f"the cross-surface claim scan failed: {type(e).__name__}: {e}",
                "detail": ("the cross-document contradiction class was NOT examined in "
                           "this sweep; re-run the scan or read the submitted surfaces "
                           "against each other"),
                "fix": "manual", "protected": False, "tier": "advisory"})
    # Deduplicate the same row reached by two passes (the DOCX figure-text rule
    # and the standalone figure loop; a PDF paragraph scan and the explicit
    # table scan). The key includes the document, location and evidence so two
    # genuinely different instances of one rule are kept.
    _seen = set()
    _unique = []
    for r in rows:
        key = (r.get("rule"), r.get("document"), r.get("location"),
               str(r.get("evidence") or "")[:300])
        if key in _seen:
            continue
        _seen.add(key)
        _unique.append(r)
    rows = _unique
    by_rule = {}
    for r in rows:
        by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1
    return {"files": [d["file"] for d in docs], "documents": docs, "rows": rows,
            "by_rule": by_rule,
            "high": sum(1 for r in rows if r["severity"] == "high"),
            "medium": sum(1 for r in rows if r["severity"] == "medium"),
            "low": sum(1 for r in rows if r["severity"] == "low"),
            "policy": policy}


def format_note(info) -> str:
    """One line describing the formatting scan (advisory; never a gate)."""
    mod = _format_module()
    if not info:
        return "not verified (no formatting scan recorded)"
    if info.get("unavailable"):
        return f"not verified ({info['unavailable']})"
    if mod is not None and hasattr(mod, "format_note"):
        return mod.format_note(info)
    rows = info.get("rows") or []
    return (f"{len(rows)} OOXML formatting finding(s)" if rows
            else "OOXML formatting: clean")


def _fmt_corpus_files(dirp: Path) -> list:
    """Corpus .docx files under `dirp` (the same filter the corpus builder uses)."""
    out = []
    for p in _docx_files_under(dirp):
        if not p.is_file() or p.name.startswith("~$") or _is_aux_doc(p.name):
            continue
        rel = p.relative_to(dirp).as_posix()
        if is_evidence_rel(rel):
            # The EVIDENCE areas are READ-ONLY BY CONTRACT (recursively): their
            # files are the author's inputs, so the formatter never opens one --
            # and an operator may have removed the write bits, which would make
            # the attempt fail on a file the pipeline must not touch anyway.
            continue
        if "work" in rel.split("/")[:-1] or is_bookkeeping_name(p.name):
            continue
        out.append(p)
    return out


def fix_docx_in_place(path: Path, policy: dict, template: Path = None,
                      containers=()) -> dict:
    """Repair one corpus DOCX in place, or leave it untouched and say why.

    The fixer's own verification decides: a file is replaced only when the
    document text is unchanged (quote-policy edits excepted), the other parts
    stayed byte-identical, the schema check passed when available, and every
    mechanical finding is gone. A failed verification keeps the original file.

    When `template` (the venue's OWN Word template) is given, the package is
    additionally restyled into it: template styles/theme/font-table/numbering,
    style-name mapping, page geometry, and removal of the direct font/size/
    spacing overrides that would hide the styles. The text must stay identical;
    a template step that cannot prove that is skipped and reported.
    """
    mod = _format_module()
    if mod is None:
        return {"file": path.name, "error": f"{DOCX_FORMAT_MODULE} not found"}
    tmp = path.with_name(f".{path.name}.paperfmt{os.getpid()}.tmp")
    try:
        rep = mod.fix_package(path, tmp, policy)
    except Exception as e:                                        # noqa: BLE001
        with contextlib.suppress(OSError):
            tmp.unlink()
        return {"file": path.name, "error": f"fixer failed: {type(e).__name__}: {e}"}
    if rep.get("changes") and not rep.get("ok"):
        with contextlib.suppress(OSError):
            tmp.unlink()
        return {"file": path.name, "changes": rep.get("changes") or [], "applied": False,
                "error": "self-verification failed (the original file was kept)",
                "verified": rep.get("verified")}
    if rep.get("error") and not rep.get("ok"):
        # `fix_package` reports an unreadable package as `ok: false` with NO
        # changes; without this branch the walk below fell through to
        # `base = path` and returned `note: already clean`, dropping the error
        # -- a corrupt/encrypted/non-DOCX manuscript passed the formatting pass
        # as CLEAN.
        with contextlib.suppress(OSError):
            tmp.unlink()
        return {"file": path.name, "changes": [], "applied": False,
                "error": str(rep.get("error")),
                "verified": rep.get("verified")}
    if rep.get("ok") is False:
        # A fixer that wrote no change and raised no error but failed its own
        # verification (a mechanical rule it could not repair) reached the
        # `base == path and not changes` branch below and was reported "already
        # clean", dropping the failed verdict. Any ok=False is a failure.
        with contextlib.suppress(OSError):
            tmp.unlink()
        remaining = ", ".join(
            str(r) for r in (rep.get("verified") or {}).get("remaining_mechanical_rules") or [])
        return {"file": path.name, "changes": [], "applied": False,
                "error": "self-verification failed (the original file was kept)"
                         + (f"; remaining: {remaining}" if remaining else ""),
                "verified": rep.get("verified")}
    base = tmp if rep.get("changes") else path
    changes = list(rep.get("changes") or [])
    template_report = None
    tpl_tmp = None
    redo = None
    if template is not None:
        tpl_tmp = path.with_name(f".{path.name}.papertpl{os.getpid()}.tmp")
        try:
            template_report = mod.apply_word_template(base, tpl_tmp, Path(template),
                                                      containers=containers)
        except Exception as e:                                    # noqa: BLE001
            template_report = {"file": path.name, "ok": False,
                               "error": f"{type(e).__name__}: {e}"}
        if template_report.get("ok"):
            if base == tmp:
                with contextlib.suppress(OSError):
                    tmp.unlink()
            base = tpl_tmp
            changes.append("venue template: "
                           + "; ".join(template_report.get("changes") or []))
            # The template step owns the typography and strips the direct
            # font/size/spacing overrides that hid the template's styles -- which
            # can remove a mechanical repair the pass above had just applied
            # (the legend-spacing policy vs the template's own Caption style).
            # Re-run the mechanical pass ON the restyled package so the file the
            # pipeline delivers satisfies the template AND the policy, and let
            # the second pass's verification be the one the report carries.
            redo = path.with_name(f".{path.name}.paperfmt2{os.getpid()}.tmp")
            try:
                rep2 = mod.fix_package(base, redo, policy)
            except Exception as e:                                # noqa: BLE001
                rep2 = {"ok": False, "changes": [],
                        "error": f"{type(e).__name__}: {e}"}
            if rep2.get("changes") and rep2.get("ok"):
                base = redo
                changes.extend(rep2.get("changes") or [])
                rep = rep2
            else:
                with contextlib.suppress(OSError):
                    redo.unlink()
                if rep2.get("changes"):
                    changes.append("the post-template mechanical pass could not be "
                                   "verified and was skipped ("
                                   + str(rep2.get("error") or "verification failed") + ")")
        else:
            with contextlib.suppress(OSError):
                tpl_tmp.unlink()
    if base != path and not policy.get("unlink_zotero_fields"):
        # FINAL FIELD FENCE: the template restyle runs outside fix_package's own
        # verification, so the whole chain (mechanical repair + template restyle
        # + second mechanical pass) is re-checked against the ORIGINAL file
        # before the swap. A chain that would drop, unlink or malform a live
        # field is skipped and the original is kept.
        if hasattr(mod, "zotero_report_for_docx"):
            cont = mod.zotero_field_continuity_problems(
                mod.zotero_report_for_docx(path), mod.zotero_report_for_docx(base))
            if cont["errors"]:
                for leftover in (tmp, tpl_tmp, redo, base):
                    if leftover is not None and leftover != path:
                        with contextlib.suppress(OSError):
                            leftover.unlink()
                return {"file": path.name, "changes": changes, "applied": False,
                        "error": "field-continuity self-check failed (the original file was "
                                 "kept): " + "; ".join(cont["errors"])[:300],
                        "verified": rep.get("verified")}
    if base == path and not changes:
        with contextlib.suppress(OSError):
            tmp.unlink()
        out = {"file": path.name, "changes": [], "applied": False, "note": "already clean"}
        if template_report is not None:
            out["template"] = template_report
        return out
    try:
        os.replace(base, path)
    except OSError:
        # The formatter writes the repaired package NEXT TO the original and
        # swaps it in: replacing an entry needs WRITE on the directory, which an
        # author may have removed (a read-only corpus directory). The copy is the
        # pipeline's own (raw_data/ never reaches this function -- see
        # _fmt_corpus_files), so clearing the blocking mode is safe.
        make_writable(path.parent, directory=True)
        try:
            os.replace(base, path)
        except OSError as e:
            with contextlib.suppress(OSError):
                Path(base).unlink()
            return {"file": path.name, "changes": changes, "applied": False,
                    "error": f"the repaired file could not replace the original: {e}",
                    "verified": rep.get("verified")}
    for leftover in (tmp, tpl_tmp, redo):
        if leftover is not None and leftover != base:
            with contextlib.suppress(OSError):
                leftover.unlink()
    out = {"file": path.name, "changes": changes, "applied": True,
           "verified": {k: (rep.get("verified") or {}).get(k) for k in
                        ("parts_intact", "text_identical", "text_diff_only_quotes",
                         "schema_ok", "mechanical_findings_before",
                         "mechanical_findings_after",
                         "zotero_fields_before", "zotero_fields_after",
                         "zotero_field_signature_kept", "zotero_field_warnings")}}
    if template_report is not None:
        out["template"] = template_report
    return out


def normalize_formatting_in_dir(dirp: Path, policy: dict, label: str,
                                warns=None, artifacts_dir=None, template=None,
                                containers=()) -> dict:
    """Repair every corpus DOCX in `dirp` and record a machine-readable artifact.

    Called by `setup` (the pristine copy), by every package-producing stage's
    postcheck (before the corpus fingerprint/pin, so the version that is judged
    and pinned is the repaired one) and by `publish_final_clean`. The artifact
    (`FORMAT_FIX.json`, plus before/after scans) lands in `artifacts_dir` (the
    run sandbox), never inside the package: `work/` scratch is stripped from the
    corpus but a top-level JSON would become submission content.

    `template` is the venue's OWN Word template: a path, or
    `{"main": path, "supplementary": path, "cover": path}` so a supplementary-
    material file is restyled into the journal's supplementary template and a
    cover letter ONLY into a cover-letter template. Every restyle keeps the
    document text byte-identical or the original file is kept and the failure is
    recorded. A cover letter whose venue ships no cover-letter template is left
    as authored: it follows the journal's guidelines and academic convention,
    never the manuscript template.
    """
    info_before = scan_format_in_sources([(dirp, "", ())], policy=policy)
    per_file, applied, failed = [], [], []
    # The run's OWN article-type spellings (the policy carries them): a
    # document named for the selected type is that type's manuscript.
    manuscript_names = list(((policy or {}).get("cover_letter") or {})
                            .get("manuscript_article_type_names") or [])

    def template_for(f: Path):
        if template is None:
            return None
        if isinstance(template, dict):
            role = docx_document_role(f.name, manuscript_names)
            if role == "cover":
                cover = template.get("cover")
                return Path(cover) if cover else None
            supp = template.get("supplementary")
            if supp and role == "supp":
                return supp
            return template.get("main")
        p = Path(template)
        # A single template path: it may be the cover-letter template itself,
        # but a manuscript template must never be applied to a cover letter.
        if docx_document_role(f.name, manuscript_names) == "cover" \
                and docx_document_role(p.name) != "cover":
            return None
        return p

    for f in _fmt_corpus_files(dirp):
        rep = fix_docx_in_place(f, policy, template=template_for(f), containers=containers)
        per_file.append(rep)
        if rep.get("applied"):
            applied.append(rep)
        elif rep.get("error"):
            failed.append(rep)
    info_after = scan_format_in_sources([(dirp, "", ())], policy=policy)
    # `name` was assigned only inside the artifacts branch below, but the
    # caller-facing warning used it too: artifacts_dir=None + a non-empty warns
    # list raised NameError while reporting a successful fix.
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", label) or "format"
    summary = {
        "label": label,
        "directory": str(dirp),
        "documents": per_file,
        "fixed": len(applied),
        "changes": sum(len(r.get("changes") or []) for r in applied),
        "failed": [r["file"] for r in failed],
        "findings_before": {"all": len(info_before.get("rows") or []),
                            "high": info_before.get("high", 0),
                            "medium": info_before.get("medium", 0),
                            "low": info_before.get("low", 0)},
        "findings_after": {"all": len(info_after.get("rows") or []),
                           "high": info_after.get("high", 0),
                           "medium": info_after.get("medium", 0),
                           "low": info_after.get("low", 0)},
        "scan_before": info_before,
        "scan_after": info_after,
    }
    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(artifacts_dir / f"FORMAT_FIX_{name}.json", summary)
    if warns is not None and (applied or failed):
        msg = (f"FORMAT-FIX: {len(applied)} document(s) normalized "
               f"({summary['changes']} mechanical formatting change(s); findings "
               f"{summary['findings_before']['all']} -> {summary['findings_after']['all']}); "
               f"text identity verified, details in FORMAT_FIX_{name}.json")
        if failed:
            msg += (f" -- {len(failed)} file(s) left untouched after a failed "
                    f"self-verification: {', '.join(summary['failed'][:3])}")
        tpl_n = sum(1 for r in per_file if (r.get("template") or {}).get("ok"))
        if tpl_n:
            msg += f"; {tpl_n} restyled into the venue's official Word template"
        warns.append(msg)
    return summary


def _docx_field_key(rel: str) -> str:
    """A DOCX path whose basename carries no version token (see DOC_TOKEN_RE)."""
    p = Path(rel)
    stem, dot, ext = p.name.rpartition(".")
    name = (DOC_TOKEN_RE.sub("", stem) + dot + ext) if dot else DOC_TOKEN_RE.sub("", p.name)
    parent = "" if p.parent.as_posix() == "." else p.parent.as_posix() + "/"
    return (parent + name).lower()


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
    def doc_map(root: Path) -> tuple:
        """({pairing key: path}, collisions) for one side of the comparison.

        The version-token-free key pairs `manuscript-4f3a9c1.docx` with
        `manuscript.docx`, but two DIFFERENT documents can strip to one key
        (`appendix-a.docx` / `appendix-b.docx`): the dict comprehension kept
        only the last, so one document was never field-checked at all. The
        collision is reported instead of being silent.
        """
        out, seen = {}, {}
        for p in _fmt_corpus_files(root):
            key = _docx_field_key(p.relative_to(root).as_posix())
            seen.setdefault(key, []).append(p)
            out[key] = p
        clashes = {k: v for k, v in seen.items() if len(v) > 1}
        return out, clashes

    base_docs, base_clash = doc_map(base_dir)
    out_docs, out_clash = doc_map(out_dir)
    for side, clashes in (("base", base_clash), ("output", out_clash)):
        for key, paths in sorted(clashes.items()):
            warns.append(f"ZOTERO FIELD CONTINUITY: two {side} documents pair to one key "
                         f"({key!r}): {', '.join(p.name for p in paths)}; only "
                         f"{max(paths).name} is compared -- "
                         f"rename them so their names differ by more than a version token")
            rep["warnings"] += 1
    if not base_docs:
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
        cands = exact or ([o for o in rest_out
                           if role and docx_document_role(o.name) == role] if role else [])
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


VALIDATE_TEX_TIMEOUT = 600


TEMPLATE_PACKAGE_DIRNAME = "template_package"
TEMPLATE_REWRITE_DIRNAME = "template_rewrite"


def apply_template_prompt(ctx: Ctx, sb: Path, src: Path, templates: dict) -> str:
    """The TEMPLATE-FIRST rewrite prompt: copy the journal's templates, fill them.

    Venue-agnostic by construction: the file names and the venue label come from
    the resolved profile/templates, and every rule is about the SHAPE of the job
    (copy the template, replace its placeholders with the submission's content,
    change nothing else), never about a journal's vocabulary.

    The manuscript templates cover the manuscript. A cover letter follows a
    cover-letter template only when the journal publishes one; with none, the
    prompt sends it down the journal-guideline -> academic-convention chain (the
    manuscript template's front matter is for the manuscript, not the letter).

    A venue with no official template gets the guideline/convention variant:
    the authority chain starts at the journal's own author guidelines instead of
    a template file.
    """
    if not templates:
        return apply_guideline_conform_prompt(ctx, src)
    # `Path("")` is Path(".") and truthy: an absent role must stay None so the
    # "ships no ... template" wording is what the prompt carries. `main` used to
    # take the `Path(templates.get("main") or "")` shortcut while supp/cover were
    # fixed, so an official pack whose only Word file is a cover/supplementary
    # template rendered a REQUEST to fill an empty file name in the main-text
    # slot, while the checker side (`template_for_package_file`) read main as
    # absent -- the session was told to satisfy a requirement nothing could meet.
    main = Path(templates["main"]) if templates.get("main") else None
    supp = Path(templates["supplementary"]) if templates.get("supplementary") else None
    cover = Path(templates["cover"]) if templates.get("cover") else None
    main_read = (f"venue_template/word/{main.name}  -- the journal's MAIN-TEXT template "
                 f"(fill it)" if main else
                 "(the venue ships no MAIN-TEXT template: the manuscript keeps its own file "
                 "from source/, edited in place and formatted per the venue's guidelines)")
    main_src = ("venue_template/word/" + main.name) if main else \
        "the source document itself (no main-text template ships)"
    docs = sorted(p.name for p in Path(src).glob("*.docx")) or ["(no .docx in source/)"]
    prof = venue_profile_of(ctx, required=False)
    label = (prof.label if prof is not None else venue_id_of(ctx))
    guide_clause = (cover_letter_guidance_clause(cover_letter_guidance(prof))
                    if prof is not None else "")
    guide_line = (f"    The venue profile records: {guide_clause}\n") if guide_clause else ""
    supp_line = ("venue_template/word/" + supp.name) if supp else \
        "(the venue ships no separate supplementary template)"
    # The supplementary's WRITE target mirrors `template_for_package_file`'s own
    # chain (the supplementary template, else the main template, else nothing):
    # naming "the main template" in a pack that ships NO main template was the
    # same dangling reference the MAIN-TEXT line above stopped rendering -- the
    # session was pointed at a file the pack does not carry.
    supp_src = (("venue_template/word/" + supp.name) if supp else
                ("the main template (no separate supplementary template ships)" if main else
                 "the source document itself (no supplementary or main-text template ships)"))
    cover_line = (("  * venue_template/word/" + cover.name
                   + "  -- the journal's COVER-LETTER template (fill it)\n") if cover else
                  "  * NO cover-letter template ships with this venue: author the cover letter\n"
                  "    under the authority chain of step 5 -- the journal's own cover-letter /\n"
                  "    scope-statement guidance (recorded in the venue profile) first, then\n"
                  "    established academic convention for a submission letter. Never use the\n"
                  "    MAIN-TEXT template for it: its Title/Author/Abstract front matter is for\n"
                  "    the manuscript, not the letter\n") + guide_line
    cover_src = (("venue_template/word/" + cover.name) if cover else
                 "the source letter, a plain submission letter: recipient block, date, salutation,\n"
                 "         body, closing and signature -- the letter's own convention (never the\n"
                 "         manuscript's Title/Author List/Abstract styles)")
    return with_context_budget(f"""TEMPLATE-FIRST REWRITE -- fill {label}'s own Word templates with this submission's content

The deliverable of THIS session is the ENTIRE submission package authored INSIDE
the journal's official Word templates. The files you hand back ARE copies of the
templates: their styles, theme, fonts, numbering, page geometry, headers/footers,
front-matter block and section skeleton are the journal's own. Your job is to
REPLACE the templates' placeholder/sample content with the actual content of
`source/` -- never the other way round, and never by restyling a copy of the
source. ONE exception: a cover letter is not a manuscript document -- see the
cover-letter rule below (a cover-letter template, or the guideline/convention
chain when this venue ships none).

READ (read-only, hash-verified):
  * {main_read}
  * {supp_line}
{cover_line.rstrip()}
  * source/ -- the package whose content you carry over:
{chr(10).join('      - ' + n for n in docs)}
    (figures, tables, data and the cover letter included; copy them into out/
    unchanged unless the venue's own template covers them)

WRITE (only inside out/):
  1. COPY each template FILE byte-for-byte (`cp`; the staged copies are
     read-only) and edit IN PLACE inside the copy's `word/document.xml`. The copy
     must keep the template's `[Content_Types].xml`, `word/styles.xml`,
     `word/theme/`, `word/fontTable.xml`, `word/numbering.xml`,
     `word/settings.xml`, every `word/header*.xml` and `word/footer*.xml` (with
     their `_rels`) and every `word/media/*` file BYTE-IDENTICAL -- never rebuild
     the package, never re-save it through a converter, and never regenerate the
     styles. The checker compares those parts against the template: a rebuilt
     package fails.
  1b. EDIT A PLACEHOLDER BY REPLACING ITS TEXT, NEVER ITS FORMATTING. The template
     is a fill-in form: each sample paragraph (title, author list, affiliation,
     correspondence block, keywords, abstract, headings, body text, bullet/
     numbered list items, figure and table captions, the statement blocks, the
     reference entries, the supplementary items) carries the style, indentation,
     numbering/bullet, spacing and run properties the journal wants. For every
     one of them:
       - keep the paragraph's `w:pPr` (its `pStyle`, `numPr` bullet/numbering,
         indentation, spacing, keepNext, ...) EXACTLY as the template wrote it;
       - keep the run's `w:rPr` (font, size, bold/italic, colour, `vertAlign` for
         superscript affiliation markers, ...) EXACTLY as the template wrote it;
       - change ONLY the text inside `w:t` (splitting a run when the real content
         needs differently formatted pieces, e.g. a superscript affiliation
         number);
       - when the real content needs MORE items than the template shows (a
         reference list, a bullet list, several affiliations, several figure
         captions), DUPLICATE the sample paragraph once per item and keep its
         `w:pPr`/`w:rPr` in every copy; when it needs FEWER, DELETE the surplus
         samples;
       - never invent a style, font, size, colour, indentation or bullet, and
         never re-tag a paragraph with a style the template does not use for that
         kind of content.
       - the main text     <- {main_src}
       - the supplementary <- {supp_src}
       - a cover letter    <- {cover_src}
         (a letter, never a manuscript: when this venue ships no cover-letter
         template, do NOT copy the main template's front-matter styles onto the
         letter -- keep the letter's own text byte-identical and give it the
         plain layout of a submission letter)
  2. REPLACE every placeholder / sample element with the matching content from
     `source/`: article title, author list, affiliations, the correspondence
     block, keywords, abstract, every section and subsection (KEEP the
     template's Heading styles and their numbering), figures/tables and their
     captions, the declaration/statement blocks the template carries, the
     reference list, and the supplementary items.
     CARRY EVERY LIVE ZOTERO FIELD OVER: when you move a citation, its whole
     complex field (begin -> instrText -> separate -> result -> end) moves with
     it; when the template's placeholder carried no field, insert the field the
     source document carries for that citation location. If the text you are
     placing carries a citation NUMBER or author-year text but no live field
     (because a previous stage unlinked it, or the template sample had plain
     text), RE-CREATE the field from the source document's own field data
     (citationID, itemData, item URIs) -- never leave plain text in a citation
     position. You may add, edit or individually delete fields, but the output
     must not delete all fields, make a field malformed, or replace a field by
     its visible text. The code side audits the output against source/ and fails
     the attempt on any of those, so run the same check yourself before you
     finish:
       python3 <zotero-use>/scripts/validate_zotero_docx.py <your.docx> \\
         --baseline <the matching source/ document.docx> --preserve-baseline-citations
  3. DELETE the template's own guide text and samples: every sentence that
     teaches the author how to use the template, and every sample name,
     laboratory, affiliation, email, keyword, citation and caption placeholder.
     The template's STRUCTURE and FURNITURE stay; its PROSE does not.
  4. CARRY THE SOURCE COMPLETELY -- the code side now verifies this EXACTLY:
     every non-empty source paragraph, SHORT LINES INCLUDED, must appear in the
     outputs at least as many times as it appears in the source, unless you
     declare it in step 7 (as a re-wrap, or -- only for what the venue's own
     structure has no place for -- as a drop). Never invent, summarize, merge or
     drop content. Rewording is allowed only where the template's structure
     demands it (for example folding a separate "Lead contact"/"Corresponding
     author" line into the correspondence block as "<Name>, lead contact"), and
     every such paragraph must be declared in the ledger's machine-readable block.
     The reverse direction is checked too: no output paragraph of 5+ words may
     be absent from the source unless it is declared (as an addition, or as a
     re-wrap's declared output).
  5. Keep the template's first-page block, running head/logo, page numbers and
     even/odd furniture exactly as the template defines them.
     FALL BACK IN LEVELS, moving to the next level ONLY for what the current
     one leaves unspecified: (1) the template itself; (2) the journal's own
     official author guidelines on its website (anything the template leaves
     open -- table font size, spacing inside a table, caption size, list
     indentation ...); (3) established academic convention (for example table
     text one step smaller than the body text, single-spaced inside the table,
     captions in the body font at body size). Record which level each choice
     came from in the ledger. Never invent a requirement no level states, never
     let the template override the guidelines for something it leaves open, and
     never leave such a style unset. THE COVER LETTER IS THE ONE DOCUMENT THE
     MANUSCRIPT TEMPLATE DOES NOT COVER: when no cover-letter template ships,
     the letter's authority chain starts at level (2) -- the journal's own
     cover-letter / scope-statement guidance (the venue profile records it) --
     and falls to level (3), the academic convention of a submission letter
     (recipient block, date, salutation, body, closing and signature), never to
     the manuscript template's Title/Author/Abstract front matter.

{display_rule_text(prof)}

  6. Render each output and LOOK at it (the visual-inspection rule below), then
     SELF-CHECK, at minimum: the template's own first-page header furniture (its
     logo, when the template carries one) is present; the footer furniture is
     there on odd AND even pages (the template's own -- never another journal's,
     whatever it says); affiliation numbers (and other superscripts) are still
     superscript; the styles/theme are the template's; and -- unless a cover-
     letter template ships -- the cover letter still LOOKS like a letter (no
     manuscript Title/Author/Abstract front matter, logo header or running
     head). The code side re-checks
     the package for leftover template prose, content coverage, the template's
     styles, its header/footer roles, its protected furniture parts and the
     superscript runs.
  7. Write `out/REPLACEMENT_LEDGER.md`: one row per template placeholder or
     sample element -- the style it carried, what replaced it (file + section),
     how many copies the real content needed, and any template element you
     deliberately KEPT because the venue's structure requires it. The ledger
     MUST end with ONE fenced ```json block declaring every occurrence that
     breaks exact parity, with the paragraphs quoted VERBATIM (the checker
     matches them by normalized text; one entry accounts for ONE occurrence, so
     a paragraph that appears N times and is re-wrapped N times needs N
     entries):
       ```json
       {{"exceptions": [
         {{"kind": "rewrap",
          "source": "<verbatim source paragraph that was not carried verbatim>",
          "output": "<verbatim replacement paragraph>",
          "reason": "<the template element/structure that forces the re-wrap>"}},
         {{"kind": "addition",
          "output": "<verbatim output paragraph not present in the source>",
          "reason": "<why the venue's structure requires it>"}},
         {{"kind": "drop",
          "source": "<verbatim source paragraph this package does not carry anywhere>",
          "reason": "<the template element/structure that leaves no slot for it>"}}
       ]}}
       ```
     `drop` is for a source paragraph the venue's own structure genuinely has no
     place for -- a previous journal's submission-metrics note, a structural
     heading the template replaces. It is NEVER a way to drop the paper's
     content: quote the paragraph, name the structure that leaves no slot, and
     the checker verifies the outputs really do not carry it.
     `{{"exceptions": []}}` when nothing needed re-wrapping, adding or dropping.
     A missing, empty or non-matching declaration FAILS the code-side check: the
     ledger is the machine-readable accounting, not prose commentary.

@@VISUAL_INSPECTION_RULE@@

@@DOCX_CLI_RULE@@
""" .replace("@@VISUAL_INSPECTION_RULE@@", visual_inspection_block("out/VISUAL_CHECK.md")) \
    .replace("@@DOCX_CLI_RULE@@", docx_cli_block()))


def apply_guideline_conform_prompt(ctx: Ctx, src: Path) -> str:
    """The conform prompt for a venue that ships NO official Word template.

    The authority chain starts one level down from the template: the journal's
    own author guidelines (the venue profile's recorded guidance), then
    established academic convention. The deliverable is the WHOLE package in
    `out/`, content-identical to `source/` and re-authored to those rules.
    """
    docs = sorted(p.name for p in Path(src).glob("*.docx")) or ["(no .docx in source/)"]
    prof = venue_profile_of(ctx, required=False)
    label = (prof.label if prof is not None else venue_id_of(ctx))
    prompt = (prof.prompt if prof is not None else {})
    guideline_lines = []
    if str(prompt.get("guidelines_source") or "").strip():
        guideline_lines.append(f"  * guidelines: {prompt['guidelines_source']}")
    if str(prompt.get("requirements") or "").strip():
        guideline_lines.append(f"  * requirements: {prompt['requirements']}")
    cguide = (cover_letter_guidance_clause(cover_letter_guidance(prof))
              if prof is not None else "")
    if cguide:
        guideline_lines.append(f"  * cover letter: {cguide}")
    guidelines = ("\n".join(guideline_lines) if guideline_lines
                  else "  * (this profile records no guideline text: use established academic "
                       "convention)")
    return with_context_budget(f"""SUBMISSION CONFORM -- author this submission to {label}'s own rules

This venue ships NO official Word template (`venue_template/` is empty), so
there is no template layout to copy. The deliverable is the WHOLE submission
package in `out/`, re-authored to the venue's own rules with EXACTLY the same
content as `source/`.

AUTHORITY, in order -- move to the next level ONLY for what the current one
leaves open:
  1. the journal's own official author guidelines, as recorded for this venue:
{guidelines}
  2. established academic convention (for example table text one step smaller
     than the body text, single-spaced inside the table, captions in the body
     font at body size).
The COVER LETTER follows the same chain: the guidelines' cover-letter /
scope-statement rules first, then the academic convention of a submission
letter (recipient block, date, salutation, body, closing and signature) --
there is no manuscript template to copy onto it.
Never invent a requirement no level states, and never leave such a style unset.

{display_rule_text(prof)}

{venue_norm_for(ctx)}

READ (read-only, hash-verified):
  * source/ -- the package whose content you carry over:
{chr(10).join('      - ' + n for n in docs)}
    (figures, tables, data and the cover letter included; copy them into out/)

WRITE (only inside out/):
  1. COPY the whole source package into out/ -- every .docx, figure, table, data
     file and the cover letter -- then edit the documents to follow the
     authority chain above. Never rebuild a package through a converter and
     never regenerate its styles from scratch.
  2. CHANGE FORMATTING ONLY: the text of every paragraph stays as the source
     wrote it. Never invent, summarize, merge or drop content.
     CARRY EVERY LIVE ZOTERO FIELD OVER UNCHANGED: keep each citation's whole
     complex field (begin -> instrText -> separate -> result -> end) in place
     while you restyle around it. If a citation position carries a NUMBER or
     author-year text with no live field (a previous stage unlinked it), RE-CREATE
     the field from the source document's own field data (citationID, itemData,
     item URIs) -- never leave plain text in a citation position. You may add,
     edit or individually delete fields, but the output must not delete all
     fields, make a field malformed, or replace a field by its visible text. The
     code side audits the output against source/ and fails the attempt on any of
     those; prove it yourself before finishing:
       python3 <zotero-use>/scripts/validate_zotero_docx.py <your.docx> \\
         --baseline <the matching source/ document.docx> --preserve-baseline-citations
  3. The code side verifies this EXACTLY: every non-empty source paragraph,
     SHORT LINES INCLUDED, must appear in the outputs at least as many times as
     in the source, unless you declare it as a re-wrap in step 5; and no output
     paragraph of 5+ words may be absent from the source unless it is declared.
  4. Render each output and LOOK at it (the visual-inspection rule below), then
     SELF-CHECK: the guidelines' mandatory sections and statements are present,
     headings/captions/tables/list labels follow the rules above, affiliation
     numbers (and other superscripts) are still superscript, and no other
     journal's furniture has been imported.
  5. Write `out/REPLACEMENT_LEDGER.md`: one row per formatting decision and every
     exception, and it MUST end with ONE fenced ```json block declaring every
     occurrence that breaks exact parity, with the paragraphs quoted VERBATIM
     (one entry accounts for ONE occurrence):
       ```json
       {{"exceptions": [
         {{"kind": "rewrap", "source": "<verbatim source paragraph that was not carried verbatim>",
          "output": "<verbatim replacement paragraph>", "reason": "<rule that forces it>"}},
         {{"kind": "addition", "output": "<verbatim output paragraph not present in the source>",
          "reason": "<why the venue's structure requires it>"}}
       ]}}
       ```
     `{{"exceptions": []}}` when nothing needed re-wrapping or adding. A missing,
     empty or non-matching declaration FAILS the code-side check: the ledger is
     the machine-readable accounting, not prose commentary.

@@VISUAL_INSPECTION_RULE@@

@@DOCX_CLI_RULE@@
""" .replace("@@VISUAL_INSPECTION_RULE@@", visual_inspection_block("out/VISUAL_CHECK.md")) \
    .replace("@@DOCX_CLI_RULE@@", docx_cli_block()))


def _docx_paragraph_texts(path: Path) -> list:
    """The non-empty paragraph texts of one DOCX, whitespace-normalized."""
    mod = _format_module()
    if mod is None:
        return []
    try:
        with zipfile.ZipFile(path) as z:
            data = _docx_xml_part(z, "word/document.xml")
        if data is None:
            return []
        xml = data.decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return []
    out = []
    for _p0, _p1, frag in mod.paragraphs(xml):
        text = re.sub(r"\s+", " ", mod.text_of(frag)).strip()
        if text:
            out.append(text)
    return out


# ---------------------------------------------------------------------
# E-MAIL ADDRESSES ARE CONTACT FACTS, NOT INFERABLE TYPOS
#
# The observed failure: a review finding inferred `helsinki.fi` from the
# printed affiliation and replaced the valid `mart.ksk@ut.ee` / `elea.ross@
# stir.ac.uk` domains. The reviewer could not verify the real address (its own
# note said so), but the reviser applied the guess and the judge read the
# change as an improvement. The prompt rule now forbids the inference; this
# code-side gate makes the rule enforceable on the PACKAGE:
#
#   * an address may be ADDED only when the input corpus already
#     carries it verbatim (reconciliation, not invention) or when the package
#     records a web-search verification for the exact string in
#     `work/EMAIL_VERIFICATION.json`;
#   * an address may not be DELETED to resolve a finding (a warning is
#     recorded; a duplicate or a placeholder domain is not a reason to guess);
#   * a case-only rewrite is not a change (address comparison is case-folded).
#
# The gate reads manuscript documents only: evidence areas (`raw_data/`,
# review feedback), `code/`, `work/` and the package's own bookkeeping are not
# submission prose. They ARE read as evidence for an in-corpus address.
# ---------------------------------------------------------------------

EMAIL_VERIFICATION_JSON_REL = "work/EMAIL_VERIFICATION.json"
EMAIL_DOC_SUFFIXES = (".docx", ".tex", ".ltx", ".md", ".txt", ".rtf", ".html", ".htm")
EMAIL_UNSCANNED_SUFFIXES = (".doc", ".odt")        # editable, no text reader here
EMAIL_EVIDENCE_SUFFIXES = EMAIL_DOC_SUFFIXES + (
    ".csv", ".tsv", ".bib", ".json", ".yaml", ".yml", ".py", ".r", ".ipynb",
    ".sh", ".c", ".h", ".cpp", ".java", ".js", ".ts", ".sql", ".toml", ".ini",
    ".cfg",
)
EMAIL_MAX_FILE_BYTES = 8 * 1024 * 1024
EMAIL_ADDRESS_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])"
    r"([A-Za-z0-9][A-Za-z0-9._%+\-]*@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?\.[A-Za-z]{2,})"
    r"(?![A-Za-z0-9.\-])")
EMAIL_FULL_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._%+\-]*@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?\.[A-Za-z]{2,}")
_EMAIL_RESERVED_DOMAINS = ("example.com", "example.edu", "example.org",
                           "example.net", "example.info", "example.biz")


def _clean_email_address(raw: str) -> str:
    """One address, without the punctuation a sentence puts around it."""
    return str(raw or "").strip().strip(".,;:)]}>'\"")


def _email_domain(addr: str) -> str:
    return str(addr or "").rsplit("@", 1)[-1].strip().strip(".").lower()


def _is_placeholder_email(addr: str) -> bool:
    """A reserved/example domain (never a real contact address)."""
    domain = _email_domain(addr)
    if not domain:
        return False
    if any(domain == d or domain.endswith("." + d) for d in _EMAIL_RESERVED_DOMAINS):
        return True
    return (domain == "localhost" or domain.endswith(".test")
            or domain.endswith(".invalid") or domain.endswith(".example"))


def _email_texts_in_file(path: Path) -> tuple:
    """(texts, gap): the text of one scannable file, or why it was not read."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as z:
                # Body + foot/endnotes: a contact address belongs to the
                # manuscript text. Header/footer parts are layout furniture a
                # journal template legitimately supplies (a journal contact
                # e-mail there is not the author's), so they are not part of
                # this comparison.
                names = [n for n in z.namelist()
                         if re.match(r"word/(?:document|footnotes|endnotes)\.xml$", n)]
                if "word/document.xml" not in names:
                    return [], "unreadable DOCX (no word/document.xml)"
                parts = []
                for n in names:
                    data = _docx_xml_part(z, n)
                    if data is None:
                        return [], f"unreadable DOCX ({n} is over the size/entity budget)"
                    parts.append((n, data.decode("utf-8", "replace")))
        except (OSError, zipfile.BadZipFile, KeyError, RuntimeError,
                NotImplementedError) as e:
            return [], f"unreadable DOCX ({type(e).__name__}: {e})"
        mod = _format_module()

        def part_texts(xml: str) -> list:
            if mod is not None:
                try:
                    return [mod.text_of(frag) for _a, _b, frag in mod.paragraphs(xml)]
                except Exception:                                  # noqa: BLE001
                    pass
            try:
                root = ET.fromstring(xml)
            except ET.ParseError:
                return [re.sub(r"<[^>]+>", " ", xml)]
            return ["\n".join(node.itertext()) for node in root.iter()
                    if isinstance(node.tag, str)
                    and node.tag.rsplit("}", 1)[-1] == "p"]

        texts = []
        for _name, xml in parts:
            texts.extend(part_texts(xml))
        return texts, ""
    try:
        return [path.read_text("utf-8", "replace")], ""
    except OSError as e:
        return [], f"unreadable ({type(e).__name__}: {e})"


def _email_addresses_in_sources(sources, evidence: bool = False) -> tuple:
    """({case-folded address: display string}, coverage gaps) over sources.

    `sources` is the `[(dir, prefix, excluded_top)]` shape every scan uses.
    `evidence=True` reads the evidence/code areas and machine-readable tables;
    the manuscript scan skips them. Every unreadable/oversize file is returned
    as a NAMED gap, never silently skipped.
    """
    found, gaps = {}, []
    suffixes = EMAIL_EVIDENCE_SUFFIXES if evidence else EMAIL_DOC_SUFFIXES

    def skipped(rel: str, name: str, excluded) -> bool:
        parts = rel.split("/")
        if excluded and parts and parts[0] in excluded:
            return True
        if "work" in parts[:-1] or name.startswith("~$"):
            return True
        if (is_bookkeeping_name(name)
                or is_non_submitted_readme_name(name)
                or is_non_document_name(name)):
            return True
        if evidence:
            area = evidence_area_of(rel)
            if area in (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR):
                return True
            return bool(is_journal_feedback_name(name)
                        or AUTHORED_REPLY_NAME_RE.search(name))
        return bool(is_non_manuscript_rel(rel) or parts[0] == CODE_DIR)

    for src, prefix, excluded in sources or []:
        try:
            src = Path(src)
        except TypeError:
            continue
        if not src.is_dir():
            continue
        for path in _files_under_ci(src, suffixes):
            try:
                rel = path.relative_to(src).as_posix()
            except ValueError:                                     # pragma: no cover
                continue
            if skipped(rel, path.name, excluded):
                continue
            try:
                if path.stat().st_size > EMAIL_MAX_FILE_BYTES:
                    gaps.append(f"{prefix + rel}: larger than "
                                f"{EMAIL_MAX_FILE_BYTES // (1024 * 1024)} MB; not scanned "
                                f"for e-mail addresses")
                    continue
            except OSError as e:
                gaps.append(f"{prefix + rel}: stat failed ({type(e).__name__}: {e})")
                continue
            texts, gap = _email_texts_in_file(path)
            if gap:
                gaps.append(f"{prefix + rel}: {gap}; not scanned for e-mail addresses")
                continue
            for text in texts:
                for m in EMAIL_ADDRESS_RE.finditer(text or ""):
                    addr = _clean_email_address(m.group(1))
                    if addr:
                        found.setdefault(addr.casefold(), addr)
        # `--revision-mode` also accepts a legacy `.doc`, and LibreOffice/Word
        # can open an `.odt`; neither has a text reader here. The coverage gap
        # is NAMED for that file instead of pretending its addresses were seen.
        for path in _files_under_ci(src, EMAIL_UNSCANNED_SUFFIXES):
            try:
                rel = path.relative_to(src).as_posix()
            except ValueError:                                     # pragma: no cover
                continue
            if skipped(rel, path.name, excluded):
                continue
            gaps.append(f"{prefix + rel}: unsupported editable format "
                        f"({path.suffix.lower()}); not scanned for e-mail addresses")
    return found, gaps


def _email_url_host(url: str) -> str:
    """The host of a verification URL, or '' (no scheme / no host)."""
    text = re.sub(r"^https?://", "", str(url or "").strip(), flags=re.I)
    return text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0] \
        .split(":", 1)[0].strip().lower()


def _email_verification_rows(pkg: Path) -> tuple:
    """(valid web-search rows, problems) from the package's own record.

    The record is package bookkeeping under `work/` (never submitted). A row is
    usable only when it names the exact corrected address, an http(s) source
    URL, the search query, the checked date and a verbatim quote that CONTAINS
    the address. The gate cannot re-run the search, but it can reject a guess
    dressed as a record.
    """
    path = Path(pkg) / EMAIL_VERIFICATION_JSON_REL
    if not path.is_file():
        return [], []
    data = read_json(path, revive=False, lenient=True)
    if data is None:
        return [], [f"{EMAIL_VERIFICATION_JSON_REL}: not readable as JSON"]
    if isinstance(data, dict):
        rows_raw = None
        for key in ("verifications", "verified", "rows", "records"):
            value = data.get(key)
            if isinstance(value, list):
                rows_raw = value
                break
        if rows_raw is None:
            rows_raw = [data] if data else []
    elif isinstance(data, list):
        rows_raw = data
    else:
        return [], [f"{EMAIL_VERIFICATION_JSON_REL}: expected a list or an object"]
    records, problems = [], []

    def pick(row: dict, *keys) -> str:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    for i, row in enumerate(rows_raw):
        where = f"{EMAIL_VERIFICATION_JSON_REL}[{i}]"
        if not isinstance(row, dict):
            problems.append(f"{where}: not an object")
            continue
        after = _clean_email_address(
            pick(row, "after", "address", "verified_address", "corrected"))
        before = _clean_email_address(pick(row, "before", "original", "old"))
        source_url = pick(row, "source_url", "url", "source", "lookup_url")
        query = pick(row, "query", "search", "search_query", "lookup")
        checked_at = pick(row, "checked_at", "date", "verified_at", "checked")
        evidence = pick(row, "evidence", "quote", "excerpt", "finding")
        verdict = pick(row, "verdict", "status", "result").lower()
        bad = []
        if not after or not EMAIL_FULL_RE.fullmatch(after):
            bad.append("no valid `after` address")
        if before and not EMAIL_FULL_RE.fullmatch(before):
            bad.append("`before` is not a valid address")
        if not re.match(r"https?://", source_url, re.I):
            bad.append("`source_url` must be an http(s) URL")
        else:
            host = _email_url_host(source_url)
            if not host:
                bad.append("`source_url` has no host")
            elif _is_placeholder_email("x@" + host):
                bad.append("`source_url` uses a reserved/example host, not a real page")
        if len(query) < 3:
            bad.append("`query` is missing (the search string)")
        if not re.match(r"\d{4}-\d{2}-\d{2}\b", checked_at):
            bad.append("`checked_at` must be YYYY-MM-DD")
        if len(evidence) < 10 or (after and after.casefold() not in evidence.casefold()):
            bad.append("`evidence` must be a verbatim quote that contains the corrected "
                       "address")
        if verdict and verdict not in ("verified", "confirmed", "found", "ok",
                                       "correct", "corrected"):
            bad.append(f"`verdict` is {verdict!r}, not a verification")
        if bad:
            problems.append(f"{where}: " + "; ".join(bad))
            continue
        records.append({
            "after": after, "after_key": after.casefold(),
            "before": before, "before_key": before.casefold() if before else "",
            "source_url": source_url, "query": query,
            "checked_at": checked_at, "evidence": evidence,
        })
    return records, problems


def email_address_change_problems(before_sources, after_sources, pkg: Path,
                                  label: str, evidence_sources=()) -> tuple:
    """(errors, warnings): the package may not fabricate an e-mail address.

    A NEW address is allowed only when the input corpus already
    carries it verbatim or `work/EMAIL_VERIFICATION.json` verifies the exact
    string. A removed address is a recorded warning (a contact fact is not a
    deletion surface); a replacement trips both checks, so an inferred domain
    cannot pass. The caller feeds the result into the stage postcheck, making
    this a hard gate for revise/rewrite/integrate and the template rewrite.
    """
    before, before_gaps = _email_addresses_in_sources(before_sources)
    after, after_gaps = _email_addresses_in_sources(after_sources)
    evidence, evidence_gaps = _email_addresses_in_sources(
        list(evidence_sources or ()), evidence=True)
    records, record_problems = _email_verification_rows(Path(pkg))
    errs = list(record_problems)
    warns = [f"{label}: e-mail address coverage gap -- {g}"
             for g in (before_gaps + after_gaps + evidence_gaps)]
    verified_after = {r["after_key"] for r in records}
    verified_before = {r["before_key"] for r in records
                       if r["before_key"] and r["after_key"] in after}
    added = set(after) - set(before)
    removed = set(before) - set(after)
    for key in sorted(added):
        addr = after[key]
        if key in evidence or key in verified_after:
            continue
        errs.append(
            f"{label}: the delivered package introduces e-mail address {addr!r}, which is "
            f"not in the input corpus and has no matching row in "
            f"{EMAIL_VERIFICATION_JSON_REL}. An e-mail address is a CONTACT FACT, not an "
            f"inferable typo: its domain cannot be inferred from an affiliation, a name or a "
            f"journal. Restore the input address, carry the exact address the corpus already "
            f"contains, or record a web-search result (query, source_url, checked_at and a "
            f"verbatim `evidence` quote containing {addr!r}) before changing it")
    for key in sorted(removed):
        addr = before[key]
        if _is_placeholder_email(addr) or key in verified_before:
            continue
        warns.append(
            f"{label}: the delivered package no longer carries e-mail address {addr!r}. An "
            f"address is a contact fact and is not a deletion surface: restore it, or record "
            f"the author query in the manual list; never remove it to resolve a finding")
    for r in records:
        if (r["before_key"] and r["before_key"] != r["after_key"]
                and r["before_key"] in after):
            warns.append(
                f"{label}: the recorded correction {r['before']!r} -> {r['after']!r} left the "
                f"superseded address in the package; reconcile every occurrence to the SAME "
                f"verified string (or record why the two addresses belong to different people)")
    return errs, warns


def _docx_hf_signature(path: Path) -> dict:
    """What header/footer furniture one DOCX actually carries.

    {roles: [(kind, type), ...] from the sectPr that governs page 1 (the FIRST
     in document order), parts: [part names], logo: a drawing/pict in some
     header/footer, page: a PAGE field there}. The first-page sectPr is the one
     the template's furniture lands in (`_apply_front_refs`) and the one the
     delivered page 1 renders from; reading the last one reported no gap on a
     two-section manuscript whose page 1 was not the venue's layout.
    """
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            doc = z.read("word/document.xml").decode("utf-8", "replace")
            hf = {n: z.read(n).decode("utf-8", "replace") for n in names
                  if re.search(r"word/(header|footer)\w*\.xml$", n)}
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return {}
    # A self-closing `<w:sectPr .../>` (a legal empty section) must match as the
    # element it is: the old fallback ran to the NEXT section's closing tag, so
    # the first section was read as a later one and the page-1 furniture check
    # compared against the wrong section. `_SECT_RE` was never defined in this
    # module, so the fallback was the only path.
    sects = re.findall(r"<w:sectPr(?=[\s/>])[^>]*/>|<w:sectPr(?=[\s>])[\s\S]*?</w:sectPr>", doc)
    roles, seen = [], set()
    # OOXML attribute ORDER is not significant: Word writes `r:id` before
    # `w:type` in some files, and the old positional regex then read no roles at
    # all and reported the template's furniture as missing. Read the attributes
    # by name instead.
    for m in re.finditer(r"<w:(header|footer)Reference(?=[\s/>])[^>]*/?>",
                         sects[0] if sects else ""):
        tag = m.group(0)
        typ = re.search(r'\bw:type="([^"]*)"', tag)
        if not typ:
            continue
        key = (m.group(1), typ.group(1))
        if key not in seen:
            seen.add(key)
            roles.append(key)
    return {"roles": sorted(roles), "parts": sorted(hf),
            "logo": any("<w:drawing" in x or "<w:pict" in x or "<v:imagedata" in x
                        for x in hf.values()),
            "page": any("PAGE" in x for x in hf.values())}


def _hf_gap(want: dict, got: dict) -> dict:
    """What the template's furniture has that the output lacks ({} when complete)."""
    if not want:
        return {}
    missing_roles = [r for r in want.get("roles") or [] if r not in (got.get("roles") or [])]
    gap = {}
    if missing_roles:
        gap["missing_roles"] = missing_roles
    if want.get("logo") and not got.get("logo"):
        gap["logo_missing"] = True
    if want.get("page") and not got.get("page"):
        gap["page_field_missing"] = True
    return gap


def _style_usage(docx: Path) -> set:
    """The paragraph style ids a DOCX's body actually uses."""
    mod = _format_module()
    if mod is None:
        return set()
    try:
        with zipfile.ZipFile(docx) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return set()
    return {sid for sid in re.findall(r'<w:pStyle w:val="([^"]+)"', xml) if sid}


def _manuscript_front_matter_styles(template: Path) -> set:
    """The manuscript template's own Title/Author-List style ids ({} when unreadable).

    A cover letter the venue ships no cover-letter template for must never
    carry these: they style an article's front page, not a letter.
    """
    mod = _format_module()
    fn = getattr(mod, "template_style_roles", None)
    if fn is None:
        return set()
    try:
        roles = fn(Path(template))
    except Exception:                                          # noqa: BLE001 -- never gate
        return set()
    return {str(sid) for sid in (roles.get("title"), roles.get("author")) if sid}


def _defined_styles(docx: Path) -> set:
    try:
        with zipfile.ZipFile(docx) as z:
            styles = z.read("word/styles.xml").decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return set()
    return set(re.findall(r'w:styleId="([^"]+)"', styles))


def _protected_template_parts(tpl: Path) -> dict:
    """{part name: sha256} of the template parts a template-DERIVED copy must keep.

    The theme, font table, numbering, and every header/footer part (the logo
    drawing, the journal's colored/numbered footers) are furniture, not content:
    an agent that copies the template and edits its text keeps them byte-for-byte.
    A rebuilt package loses them, which is exactly the failure this catches.
    """
    out = {}
    try:
        with zipfile.ZipFile(tpl) as z:
            for name in z.namelist():
                low = name.lower()
                if low.startswith("word/theme/") or low in ("word/fonttable.xml",
                                                            "word/numbering.xml"):
                    out[name] = hashlib.sha256(z.read(name)).hexdigest()
                    continue
                if re.match(r"word/(header|footer)\w*\.xml$", low):
                    body = z.read(name).decode("utf-8", "replace")
                    text = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", body))
                    # A part that carries the template's own PROSE (its typesetting
                    # note) or a VML/DrawingML TEXT BOX may be intentionally replaced
                    # by a plain page-number footer; the logo header, the empty
                    # headers and the plain page-number parts must stay.
                    if len(text.split()) >= 6 \
                            or re.search(r"<w:txbxContent|<wps:wsp|<w:pict\b", body):
                        continue
                    out[name] = hashlib.sha256(z.read(name)).hexdigest()
    except (OSError, zipfile.BadZipFile, KeyError):
        return {}
    return out


def _out_part_hashes(docx: Path) -> set:
    hashes = set()
    try:
        with zipfile.ZipFile(docx) as z:
            for name in z.namelist():
                if name.endswith((".xml", ".rels", ".jpeg", ".jpg", ".png", ".emf", ".wmf")):
                    hashes.add(hashlib.sha256(z.read(name)).hexdigest())
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return set()
    return hashes


_SUP_RUN_RE = re.compile(r"<w:r\b[^>]*>([\s\S]*?)</w:r>")
_SUP_ALIGN_RE = re.compile(r'<w:vertAlign\b[^>]*w:val="superscript"')
_SUP_TEXT_RE = re.compile(r"<w:t\b[^>]*>([\s\S]*?)</w:t>")


def _superscript_run_count(frag: str) -> int:
    """How many superscript RUNS THAT CARRY TEXT one paragraph fragment holds.

    An empty (or whitespace-only) superscript run is a formatting residue -- a
    Zotero field whose result text was lost, a leftover `\\nosupersub{}` -- not
    a citation or affiliation marker. Counting the runs themselves made a
    package that preserved every VISIBLE marker fail ("source_superscripts": 4
    against "output_superscripts": 1) on three empty runs, and a run whose text
    merely contains the word "superscript" would have been counted too.
    """
    n = 0
    for m in _SUP_RUN_RE.finditer(frag or ""):
        run = m.group(1)
        if not _SUP_ALIGN_RE.search(run):
            continue
        if any(t.strip() for t in _SUP_TEXT_RE.findall(run)):
            n += 1
    return n


def _superscripts_by_paragraph(path: Path) -> dict:
    """{normalized paragraph text: superscript-run count} for one DOCX."""
    mod = _format_module()
    out = {}
    if mod is None:
        return out
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return out
    for _p0, _p1, frag in mod.paragraphs(xml):
        text = re.sub(r"\s+", " ", mod.text_of(frag)).strip().lower()
        n = _superscript_run_count(frag)
        if text and n:
            out[text] = max(out.get(text, 0), n)
    return out


TEMPLATE_LEDGER_ADD_MIN_WORDS = 5


def _template_norm_para(text) -> str:
    """The comparison form of one paragraph: whitespace-collapsed, lower-case."""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _template_word_count(text) -> int:
    return len(_template_norm_para(text).split())


def _template_ledger_exceptions(ledger: Path) -> tuple:
    """Parse the machine-readable exceptions block(s) of REPLACEMENT_LEDGER.md.

    Every discrepancy between the source package and the template-authored
    output has to be ACCOUNTED FOR, not merely summarized in prose: the ledger
    must carry one fenced JSON object with an `exceptions` list whose entries are

        {"kind": "rewrap",   "source": "<source paragraph>",
         "output": "<replacement paragraph>", "reason": "<template element>"}
        {"kind": "addition", "output": "<new output paragraph>",
         "reason": "<why the venue's structure requires it>"}
        {"kind": "drop",     "source": "<source paragraph>",
         "reason": "<the venue's structure that leaves no slot for it>"}

    `drop` is the escape hatch for a source paragraph the target venue's own
    structure genuinely has no place for (a previous journal's submission
    metrics line, a structural heading the template replaces): it excuses ONE
    occurrence of that paragraph from the parity multiset, and only when the
    output really does not carry it. A source paragraph with a replacement is a
    `rewrap` (its output must be NEW text the source did not already carry), not
    a drop.

    Returns (exceptions, problems). A missing ledger yields no exceptions and no
    problem here -- the caller already fails the stage when the ledger is absent.
    """
    path = Path(ledger)
    if not path.is_file():
        return [], []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [], [f"unreadable: {e}"]
    out, problems = [], []
    # Only ```json blocks are the machine-readable accounting; a fenced example
    # of anything else must never make the stage fail as "unparsable ledger".
    blocks = re.findall(r"```([A-Za-z0-9_+-]*)\s*([\s\S]*?)```", text)
    for tag, raw in blocks:
        if tag.strip().lower() != "json":
            continue
        try:
            data = json.loads(raw)
        except ValueError as e:
            problems.append(f"the machine-readable exceptions block does not parse as JSON: {e}")
            continue
        rows = data if isinstance(data, list) else (
            data.get("exceptions") if isinstance(data, dict) else None)
        if rows is None:
            continue
        if not isinstance(rows, list):
            problems.append("`exceptions` must be a list")
            continue
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                problems.append(f"exceptions[{i}] is not an object")
                continue
            kind = str(row.get("kind") or "").strip().lower()
            if kind not in ("rewrap", "addition", "drop"):
                problems.append(f"exceptions[{i}]: kind {kind!r} is not 'rewrap', 'addition' or "
                                f"'drop'")
                continue
            entry = {"kind": kind,
                     "source": _template_norm_para(row.get("source")),
                     "output": _template_norm_para(row.get("output")),
                     "reason": str(row.get("reason") or "").strip()}
            if not entry["reason"]:
                problems.append(f"exceptions[{i}] ({kind}) has no reason")
            if kind == "rewrap" and (not entry["source"] or not entry["output"]):
                problems.append(f"exceptions[{i}] (rewrap) needs both `source` and `output` -- a "
                                f"paragraph the venue's structure does not carry is declared as "
                                f'{{"kind": "drop", "source": ..., "reason": ...}}')
                continue
            if kind == "addition" and not entry["output"]:
                problems.append(f"exceptions[{i}] (addition) needs `output`")
                continue
            if kind == "drop" and not entry["source"]:
                problems.append(f"exceptions[{i}] (drop) needs `source`")
                continue
            out.append(entry)
    return out, problems


def _match_source_output_docs(src_docs: list, out_docs: list, templates: dict,
                              src_root: Path = None, out_root: Path = None,
                              manuscript_names=()) -> tuple:
    """Map every source document to the output document that carries it.

    The template-first session is told to hand back COPIES OF THE TEMPLATES, so
    output names are often the template's (`Frontiers_Template.docx`), not the
    source's (`...-mainText.docx`). Matching by exact name, then by the
    main/supplementary/cover role, then by the sole remaining output lets the
    content checks run PER DOCUMENT instead of falling back to the joined text of
    the whole package. Documents may sit in subdirectories (a `supp/` folder),
    so the match prefers the same RELATIVE PATH, then an unambiguous basename,
    then the role. Returns ({source key: output Path}, used output keys, errors)
    where the key is the source's relative path when `src_root` is given (a
    basename otherwise), so sibling documents that share a name cannot collide.
    """
    mapping, used, errs = {}, set(), []

    def key_of(root: Path, p: Path) -> str:
        if root is None:
            return p.name
        try:
            return p.relative_to(root).as_posix()
        except ValueError:                                  # pragma: no cover
            return p.as_posix()

    def assign(doc: Path, cand: Path) -> None:
        mapping[key_of(src_root, doc)] = cand
        used.add(key_of(out_root, cand))

    def uniq(cands: list):
        return cands[0] if len(cands) == 1 else None

    for doc in src_docs:                                    # 1. exact relative path
        cands = [p for p in out_docs if key_of(out_root, p) not in used
                 and key_of(out_root, p) == key_of(src_root, doc)]
        cand = uniq(cands)
        if cand is not None:
            assign(doc, cand)
    for doc in src_docs:                                    # 2. exact file name
        if key_of(src_root, doc) in mapping:
            continue
        cands = [p for p in out_docs if p.name == doc.name and key_of(out_root, p) not in used]
        cand = uniq(cands)
        if cand is not None:
            assign(doc, cand)
    for doc in src_docs:                                    # 3. advertised role
        if key_of(src_root, doc) in mapping:
            continue
        role = docx_document_role(doc.name, manuscript_names)
        cands = [p for p in out_docs
                 if key_of(out_root, p) not in used
                 and docx_document_role(p.name, manuscript_names) == role]
        if not cands and role in ("main", "supp"):
            tpl = templates.get("main" if role == "main" else "supplementary")
            if tpl:
                cands = [p for p in out_docs
                         if key_of(out_root, p) not in used and p.name == Path(tpl).name]
        cand = uniq(cands)
        if cand is not None:
            assign(doc, cand)
    remaining = [doc for doc in src_docs if key_of(src_root, doc) not in mapping]
    rest_out = [p for p in out_docs if key_of(out_root, p) not in used]
    if len(remaining) == 1 and len(rest_out) == 1:          # 4. sole remainder
        assign(remaining[0], rest_out[0])
    for doc in remaining:
        if key_of(src_root, doc) not in mapping:
            errs.append(f"cannot tell which output document carries "
                        f"{key_of(src_root, doc)!r}: copy each "
                        f"source document into its template under a name that keeps its "
                        f"main/supplementary/cover role recognizable")
    return mapping, used, errs


def template_rewrite_postcheck(sb: Path, src: Path, templates: dict,
                               policy: dict = None) -> dict:
    """Verify a template-first rewrite session (venue-agnostic verifiers).

    Two questions decide it:
      * PARITY -- the source package's paragraph MULTISET is carried over
        exactly (every non-empty paragraph, short lines included, at least as
        many times as in the source), except for the exceptions the session
        declares in the machine-readable block of out/REPLACEMENT_LEDGER.md
        (`rewrap` -- a declared replacement -- or `drop` -- a paragraph the
        venue's own structure has no slot for, which must really be gone); and
        no content-bearing output paragraph (>= TEMPLATE_LEDGER_ADD_MIN_WORDS
        words) exists that is neither in the source nor declared as an
        addition. A 95% threshold or a blanket allowance for short paragraphs
        is NOT enough: this package becomes the pipeline's `original`, so a
        silent drop or reword would corrupt every later round;
      * TEMPLATE PROSE -- none of the template's own guide sentences/sample
        elements survives (the templates were COPIED and FILLED), while the
        template's style set is still present in every output the template
        governs -- a cover letter with no cover-letter template keeps its own
        letter styling and is not measured against the manuscript's.

    The DOCUMENT set is the submission's own `.docx` files: the corpus's
    evidence areas (the previous journal's `original_submission/` under
    `human_review_feedback/`, `raw_data/`) are read-only INPUTS, not documents
    to re-house, and a new journal's package need not even match the old one's
    file names (see `_template_docs`).
    """
    out = sb / "out"
    if not out.is_dir():
        return {"ok": False, "errors": ["out/ is missing: the session produced no package"]}
    # The run's own article-type spellings (from the policy the caller built
    # with ctx): a `letter-to-the-editor` manuscript is not a cover letter.
    manuscript_names = list(((policy or {}).get("cover_letter") or {})
                            .get("manuscript_article_type_names") or [])
    # rglob, not glob: template_package_files() copies the WHOLE tree (figures,
    # tables, a package's own `supp/supp.docx`, ...), and the prompt tells the
    # session to re-house every package document. Reading only the top level let
    # an output that dropped a nested supplementary document pass with a vacuous
    # 2/2 coverage. Deeper paths follow shallower ones so an exact
    # `mainText.docx` still wins, and a session's `out/work/` scratch is never
    # part of the package.
    def _template_docs(root: Path) -> list:
        """The rewrite's DOCUMENT set: every submission .docx, and only those.

        rglob (not glob) because the package's own `supp/` folder is part of it
        -- but the corpus's EVIDENCE areas (`human_review_feedback/` with the
        previous journal's `original_submission/`, `raw_data/`) and
        feedback/response documents are the authors' INPUTS,
        exactly as `is_non_manuscript_rel` defines for every other corpus scan.
        A new journal's package need not match the old one's file set (renames,
        files the new venue does not require), so requiring each of those
        documents to be re-housed -- or counting their paragraphs in the parity
        multiset -- failed a compliant session.
        """
        out = []
        for p in _docx_files_under(root):
            if not p.is_file() or _is_aux_doc(p.name) or p.name.startswith("~$"):
                continue
            rel = p.relative_to(root)
            if "work" in rel.parts[:-1]:
                continue
            if is_non_manuscript_rel(rel.as_posix()):
                continue
            out.append(p)
        return sorted(out, key=lambda p: (len(p.relative_to(root).parts), p.as_posix()))

    src_docs = _template_docs(Path(src))
    out_docs = _template_docs(out)
    if not src_docs:
        return {"ok": False, "errors": [f"{Path(src)} carries no .docx to re-house: the "
                                        f"template-first stage has nothing to fill"]}
    if not out_docs:
        return {"ok": False, "errors": ["out/ carries no .docx deliverable"]}
    errs, warns = [], []
    # Discover the ledger ONCE and use that path for both the existence check and
    # the parse: the check was case-insensitive while the parser was hardcoded to
    # out/REPLACEMENT_LEDGER.md, so a lower-case `replacement_ledger.md` passed
    # the existence check and then silently contributed zero exceptions. The
    # canonical name still WINS over any other `*ledger*.md`: an integration- or
    # revision-shaped package carries its own `DIFF_LEDGER.md`, and sorted order
    # made that prose file shadow the real exceptions block ("declared_exceptions:
    # 0" -> a valid package was refused).
    ledgers = [p for p in sorted(out.iterdir())
               if p.is_file() and p.match("*[Ll][Ee][Dd][Gg][Ee][Rr]*.md")]
    ledger = next((p for p in ledgers if p.name.lower() == "replacement_ledger.md"),
                  ledgers[0] if ledgers else None)
    exceptions, exception_problems = _template_ledger_exceptions(
        ledger if ledger is not None else out / "REPLACEMENT_LEDGER.md")
    mapping, _used_out, map_errs = _match_source_output_docs(src_docs, out_docs,
                                                             templates or {},
                                                             src_root=Path(src), out_root=out,
                                                             manuscript_names=manuscript_names)

    def _src_key(doc: Path) -> str:
        try:
            return doc.relative_to(src).as_posix()
        except ValueError:                                  # pragma: no cover
            return doc.as_posix()

    # A source document with no output counterpart is a DROPPED document, not a
    # text-only discrepancy: the parity counters below are package-wide, so a
    # dropped nested `.docx` whose paragraphs also occur elsewhere could pass.
    for doc in src_docs:
        if mapping.get(_src_key(doc)) is None:
            errs.append(f"{_src_key(doc)!r} has no output document: every "
                        f"source package document must be re-housed in the template")
    errs.extend(map_errs)
    # ZOTERO FIELD CONTINUITY: re-housing a document into the venue template --
    # or re-authoring it by hand -- may not drop, unlink or malform any live
    # field of the source document. This package becomes round 1's working
    # original, so a field lost here would be lost for every later round.
    zotero_rep = {"checked": 0, "errors": [], "documents": []}
    mod = _format_module()
    if mod is not None and hasattr(mod, "zotero_report_for_docx"):
        for doc in src_docs:
            target = mapping.get(_src_key(doc))
            if target is None:
                continue
            cont = mod.zotero_field_continuity_problems(
                mod.zotero_report_for_docx(doc), mod.zotero_report_for_docx(target))
            if not (cont["baseline_fields"] or cont["output_fields"] or cont["errors"]):
                continue
            where = f"{_src_key(doc)} -> {target.relative_to(out).as_posix()}"
            zotero_rep["checked"] += 1
            for msg in cont["errors"]:
                errs.append(f"ZOTERO FIELD CONTINUITY: {where}: {msg}")
            for msg in cont["warnings"]:
                warns.append(f"ZOTERO FIELD CONTINUITY: {where}: {msg}")
            zotero_rep["errors"].extend(cont["errors"])
            zotero_rep["documents"].append(
                {"source": _src_key(doc), "output": target.relative_to(out).as_posix(),
                 "fields_before": cont["baseline_fields"], "fields_after": cont["output_fields"],
                 "errors": cont["errors"], "deleted": cont["deleted"], "added": cont["added"],
                 "edited": cont["edited"], "plain_text": cont["plain_text"]})
    src_counter, out_counter = Counter(), Counter()
    for doc in src_docs:
        src_counter.update(_template_norm_para(t) for t in _docx_paragraph_texts(doc))
    out_text = {}
    for doc in out_docs:
        texts = _docx_paragraph_texts(doc)
        out_counter.update(_template_norm_para(t) for t in texts)
        out_text[doc.name] = " \u241f ".join(texts).lower()
    joined = " \u241f ".join(out_text.values())
    rewraps = [e for e in exceptions if e["kind"] == "rewrap"]
    additions = [e for e in exceptions if e["kind"] == "addition"]
    drops = [e for e in exceptions if e["kind"] == "drop"]
    for e in exceptions:
        if e["kind"] == "rewrap":
            if e["source"] and e["source"] not in src_counter:
                exception_problems.append(
                    f"a declared re-wrap's SOURCE paragraph is not in the source package: "
                    f"{e['source'][:70]!r}")
            if e["output"] and e["output"] not in out_counter:
                exception_problems.append(
                    f"a declared re-wrap's OUTPUT paragraph is not in the outputs: "
                    f"{e['output'][:70]!r}")
            elif e["output"] and out_counter[e["output"]] <= src_counter.get(e["output"], 0):
                # A re-wrap must carry the dropped paragraph into OUTPUT text the
                # source did not already provide. Pointing at a paragraph that is
                # present in the source and not duplicated lets one declaration
                # excuse a real drop on the source side and a real addition on the
                # output side at once: content is lost and the gate still passes.
                exception_problems.append(
                    f"a declared re-wrap's OUTPUT paragraph is already fully accounted for by "
                    f"the source package (it occurs {out_counter[e['output']]}x in the outputs "
                    f"and {src_counter.get(e['output'], 0)}x in the source), so it cannot carry "
                    f"the dropped paragraph: {e['output'][:70]!r}")
        elif e["kind"] == "drop":
            if e["source"] and e["source"] not in src_counter:
                exception_problems.append(
                    f"a declared drop's SOURCE paragraph is not in the source package: "
                    f"{e['source'][:70]!r}")
            elif e["source"] and out_counter.get(e["source"], 0) >= src_counter[e["source"]]:
                # A drop has to point at a paragraph that is actually gone: a
                # declaration against text the outputs still carry excuses
                # nothing (the parity counter already credits it) and hides a
                # mis-specified re-wrap, whose replacement must be NEW text.
                exception_problems.append(
                    f"a declared drop is not needed: the paragraph occurs "
                    f"{out_counter.get(e['source'], 0)}x in the outputs and "
                    f"{src_counter[e['source']]}x in the source: {e['source'][:70]!r}")
        elif e["output"] not in out_counter:
            exception_problems.append(
                f"a declared addition is not in the outputs: {e['output'][:70]!r}")
    leftover = []
    for role in sorted(templates or {}):
        tpl = templates.get(role)
        for text in (_docx_paragraph_texts(Path(tpl)) if tpl else []):
            norm = _template_norm_para(text)
            # A long template paragraph the SOURCE also carries is source
            # content (a required statement the authors wrote), not leftover
            # template prose; everything else must have been filled in.
            if len(norm.split()) >= 6 and norm in out_counter and norm not in src_counter:
                leftover.append({"role": role, "text": text[:120]})
    if leftover:
        errs.append(f"{len(leftover)} template guide sentence(s) survive in the outputs "
                    f"(the templates must be FILLED, not paraphrased): "
                    + "; ".join(repr(l["text"][:60]) for l in leftover[:3]))
    # The parity counters are normalized (whitespace-collapsed, lower-case);
    # the declared exceptions must use the SAME key or a re-wrap whose source
    # differs only in case/spacing excuses nothing (and the superscript check
    # above could not recognize it).
    declared_rewrap_sources = Counter(
        _template_norm_para(e["source"]) for e in rewraps if e["source"])
    declared_rewrap_outputs = Counter(
        _template_norm_para(e["output"]) for e in rewraps if e["output"])
    declared_additions = Counter(
        _template_norm_para(e["output"]) for e in additions if e["output"])
    declared_drops = Counter(
        _template_norm_para(e["source"]) for e in drops if e["source"])
    missing = []
    for text in sorted(src_counter):
        want_n = src_counter[text]
        have_n = out_counter.get(text, 0)
        deficit = (want_n - have_n - declared_rewrap_sources.get(text, 0)
                   - declared_drops.get(text, 0))
        if deficit > 0:
            missing.append({"text": text[:120], "source_count": want_n,
                            "output_count": have_n, "unaccounted": deficit})
    checked = sum(src_counter.values())
    if checked == 0:
        errs.append("no paragraph could be read from the source package's .docx file(s): the "
                    "exact-parity gate would pass vacuously (an empty or unreadable source "
                    "document is never a valid template-fill result)")
    missing_occurrences = sum(m["unaccounted"] for m in missing)
    covered = checked - missing_occurrences
    ratio = (covered / checked) if checked else 1.0
    if missing:
        errs.append(f"content coverage is not exact: {missing_occurrences} of {checked} source "
                    f"paragraph occurrence(s) are missing or reworded and no matching re-wrap is "
                    f"declared in out/REPLACEMENT_LEDGER.md (e.g. {missing[0]['text'][:70]!r}); "
                    f"every source paragraph -- short ones included -- must appear in the "
                    f"outputs at least as many times as in the source, or be declared as a "
                    f"re-wrap or drop")
    unaccounted_additions, short_additions = [], 0
    for text in sorted(out_counter):
        extra = (out_counter[text] - src_counter.get(text, 0)
                 - declared_rewrap_outputs.get(text, 0) - declared_additions.get(text, 0))
        if extra <= 0:
            continue
        if _template_word_count(text) >= TEMPLATE_LEDGER_ADD_MIN_WORDS:
            unaccounted_additions.append({"text": text[:120], "count": extra})
        else:
            short_additions += extra
    if unaccounted_additions:
        errs.append(f"{len(unaccounted_additions)} output paragraph(s) of "
                    f">= {TEMPLATE_LEDGER_ADD_MIN_WORDS} words are not present in any source "
                    f"document and are not declared in out/REPLACEMENT_LEDGER.md "
                    f"(e.g. {unaccounted_additions[0]['text'][:70]!r}); never invent content -- "
                    f"declare every new content-bearing paragraph as an `addition` with its "
                    f"reason")
    if short_additions:
        warns.append(f"{short_additions} short output line(s) (< "
                     f"{TEMPLATE_LEDGER_ADD_MIN_WORDS} words) have no source counterpart: "
                     f"template labels/headings are fine, content-bearing additions are not")
    if exception_problems:
        errs.extend(f"REPLACEMENT_LEDGER.md: {p}" for p in exception_problems)
    style_gap = []
    for doc in out_docs:
        try:
            with zipfile.ZipFile(doc) as z:
                have = set(re.findall(r'w:styleId="([^"]+)"',
                                      z.read("word/styles.xml").decode("utf-8", "replace")))
        except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
            style_gap.append({"file": doc.name, "error": "no readable word/styles.xml"})
            continue
        tpl_for_doc = template_for_package_file(doc, templates or {}, manuscript_names)
        if tpl_for_doc is None:
            # A cover letter with no cover-letter template is authored to the
            # guideline/convention chain: the manuscript template's styles are
            # not a requirement for it.
            continue
        try:
            with zipfile.ZipFile(tpl_for_doc) as z:
                want = set(re.findall(r'w:styleId="([^"]+)"',
                                      z.read("word/styles.xml").decode("utf-8", "replace")))
        except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
            continue
        gone = sorted(want - have)
        if gone:
            style_gap.append({"file": doc.name, "template": Path(tpl_for_doc).name,
                              "missing_styles": gone[:8]})
    if style_gap:
        errs.append("the outputs do not carry the template's styles: " + json.dumps(style_gap)[:300])
    # A cover letter the template does NOT govern must not be STAMPED with the
    # manuscript template's front matter: the reported failure was the journal's
    # manuscript template (title/author-list styles) applied to the letter.
    letter_stamp = []
    main_tpl = (templates or {}).get("main")
    if main_tpl and not (templates or {}).get("cover"):
        stamp_styles = _manuscript_front_matter_styles(Path(main_tpl))
        if stamp_styles:
            for doc in out_docs:
                if docx_document_role(doc.name, manuscript_names) != "cover":
                    continue
                carried = sorted(_style_usage(doc) & stamp_styles)
                if carried:
                    letter_stamp.append({"file": doc.name, "manuscript_styles": carried})
    if letter_stamp:
        errs.append("the cover letter carries the MANUSCRIPT template's front-matter styles "
                    "(this venue ships no cover-letter template): the letter's authority is the "
                    "journal's cover-letter guidance / academic convention, never the manuscript "
                    "template -- restyle it as a plain submission letter: "
                    + json.dumps(letter_stamp)[:300])
    # The template's HEADERS/FOOTERS (logo, running head, page numbers, odd/even
    # furniture) are part of the deliverable: every output must carry the roles
    # the template it was built from defines.
    hf_gap = []
    for doc in out_docs:
        tpl = template_for_package_file(doc, templates or {}, manuscript_names)
        if not tpl:
            continue
        gap = _hf_gap(_docx_hf_signature(Path(tpl)), _docx_hf_signature(doc))
        if gap:
            hf_gap.append({"file": doc.name, "template": Path(tpl).name, **gap})
    if hf_gap:
        errs.append("the outputs do not carry the template's headers/footers: "
                    + json.dumps(hf_gap)[:300])
    # TEMPLATE-DERIVED PARTS: the theme, font table, numbering and every header/
    # footer part of the template must still be in the output (byte-identical, any
    # part name -- a copied template keeps the names; a re-style may rename them).
    derived_gap = []
    for doc in out_docs:
        tpl = template_for_package_file(doc, templates or {}, manuscript_names)
        if not tpl:
            continue
        want = _protected_template_parts(Path(tpl))
        have = _out_part_hashes(doc)
        gone = sorted(name for name, h in want.items() if h not in have)
        if gone:
            derived_gap.append({"file": doc.name, "template": Path(tpl).name,
                                "missing_template_parts": gone[:8]})
    if derived_gap:
        errs.append("the outputs are not derived from the templates: furniture parts of the "
                    "template are gone (theme/fonts/numbering/headers/footers) -- COPY the "
                    "template and edit it, never rebuild the package: "
                    + json.dumps(derived_gap)[:300])
    # SUPERSCRIPTS (affiliation markers, footnotes) are content-level formatting:
    # every source paragraph found in an output must keep at least as many
    # superscript runs as the source had.
    sub_lost = []
    for doc in src_docs:
        target = mapping.get(_src_key(doc))
        if target is None:
            continue
        want_sup = _superscripts_by_paragraph(doc)
        got_sup = _superscripts_by_paragraph(target)
        for text, n in want_sup.items():
            if text in got_sup and got_sup[text] < n:
                sub_lost.append({"file": doc.name, "text": text[:80],
                                 "source_superscripts": n, "output_superscripts": got_sup[text]})
            elif text not in got_sup and text in " ".join(out_text.values()):
                # The paragraph was merged into a longer one by a DECLARED
                # re-wrap: the exact paragraph key cannot exist any more, so
                # require the superscripts on the declared OUTPUT paragraph
                # instead of demanding the old paragraph boundary. Skipping the
                # check outright let a re-wrap drop a marker and still pass.
                merged_outputs = [
                    _template_norm_para(e.get("output") or "")
                    for e in rewraps
                    if _template_norm_para(e.get("source") or "") == text
                    and e.get("output")]
                if merged_outputs:
                    got = max(got_sup.get(o, 0) for o in merged_outputs)
                    if got >= n:
                        continue
                    sub_lost.append({"file": doc.name, "text": text[:80],
                                     "source_superscripts": n,
                                     "output_superscripts": got})
                    continue
                sub_lost.append({"file": doc.name, "text": text[:80],
                                 "source_superscripts": n, "output_superscripts": 0})
    if sub_lost:
        errs.append("superscript runs were dropped (affiliation numbers / footnote markers): "
                    + json.dumps(sub_lost[:4])[:300])
    # STYLE PRESERVATION: every style the SOURCE content uses must still be used
    # by the output for the styles the TEMPLATE'S OWN documents use (the
    # placeholders' styles carry the content), and the output may not invent a
    # style the template does not define. A source package authored for ANOTHER
    # journal carries that journal's style names (a `Bibliography` reference
    # style, its own title style, a style the template defines but never uses):
    # demanding those back would contradict the `invented` check below -- the
    # output would have to use a style the template's own grammar does not. This
    # is a TEMPLATE-conformance rule: without an official template the guideline
    # chain may legitimately restyle the content, so only the content parity
    # checks above apply.
    style_use_gap = []
    if templates:
        for doc in src_docs:
            target = mapping.get(_src_key(doc))
            if target is None:
                continue
            tpl_for_doc = template_for_package_file(target, templates or {}, manuscript_names)
            required = _style_usage(Path(tpl_for_doc)) if tpl_for_doc else set()
            lost = sorted((_style_usage(doc) - _style_usage(target)) & required)
            if lost:
                style_use_gap.append({"file": doc.name, "styles_lost": lost[:8]})
        if style_use_gap:
            errs.append("the outputs no longer USE the styles this source content carried in "
                        "the template (each placeholder keeps its style while its text is "
                        "replaced, and surplus samples are duplicated/deleted, never re-tagged): "
                        + json.dumps(style_use_gap)[:300])
    invented = []
    for doc in out_docs:
        tpl = template_for_package_file(doc, templates or {}, manuscript_names)
        if not tpl:
            continue
        extra = sorted(_style_usage(doc) - _defined_styles(Path(tpl)))
        if extra:
            invented.append({"file": doc.name, "undefined_styles": extra[:8]})
    if invented:
        errs.append("the outputs use paragraph styles the template does not define "
                    "(never invent a style): " + json.dumps(invented)[:300])
    if ledger is None:
        errs.append("out/REPLACEMENT_LEDGER.md is missing: record every "
                    + ("template placeholder and what replaced it" if templates else
                       "formatting decision and every parity exception"))
    # The venue's own TABLE rule (rules FMT-TB1..FMT-TB3): the package this
    # stage hands back BECOMES round 1's working original, so a table the venue
    # profile declares must already be captioned and placed the venue's way --
    # this is the one stage whose output every later round inherits. The check
    # is silent when the profile declares no table rule.
    if policy is not None:
        errs.extend(display_rule_errors(
            scan_format_in_sources([(out, "", ())], policy=policy),
            "template-first stage"))
    # CONTACT FACTS: re-housing a package into a template may not infer or
    # replace an author e-mail address. The source package is the in-corpus
    # evidence; a correction outside it needs the output's own
    # work/EMAIL_VERIFICATION.json row.
    if Path(src).is_dir():
        email_errs, email_warns = email_address_change_problems(
            [(Path(src), "", ())], [(out, "", ())], out, "template-first stage",
            evidence_sources=[(Path(src), "", ())])
        errs.extend(email_errs)
        warns.extend(email_warns)
        fact_errs, fact_warns = fact_token_change_problems(
            [(Path(src), "", ())], [(out, "", ())], out, "template-first stage",
            evidence_sources=[(Path(src), "", ())])
        errs.extend(fact_errs)
        warns.extend(fact_warns)
        todo_errs, todo_warns = manual_todo_gate(out)
        errs.extend(todo_errs)
        warns.extend(todo_warns)
    return {"ok": not errs, "errors": errs, "warnings": warns,
            "zotero_fields": zotero_rep,
            "coverage": {"mode": "exact-multiset", "checked": checked, "covered": covered,
                         "ratio": round(ratio, 4), "missing_samples": missing[:8],
                         "unaccounted_additions": unaccounted_additions[:8],
                         "short_unaccounted_additions": short_additions,
                         "declared_exceptions": len(exceptions)},
            "document_mapping": {k: v.name for k, v in sorted(mapping.items())},
            "ledger_exception_problems": exception_problems[:8],
            "template_prose_left": leftover[:8],
            "headers_footers": {p.name: _docx_hf_signature(p) for p in out_docs},
            "template_derived_gaps": derived_gap[:8],
            "styles_lost": style_use_gap[:8],
            "styles_invented": invented[:8],
            "superscripts_lost": sub_lost[:8],
            "documents": [p.name for p in out_docs]}


def template_for_package_file(path: Path, templates: dict, manuscript_names=()):
    """The venue Word template one package DOCX should be rebuilt in.

    A cover letter adopts ONLY a cover-letter template (`templates["cover"]`).
    When the venue ships none, this returns None and the letter keeps the
    styling it was authored with -- its authority chain is the journal's own
    cover-letter guidance, then academic convention, never the manuscript
    template (which exists for the manuscript, not the letter).
    `manuscript_names` is `article_type_manuscript_names(ctx)`: the selected
    article type's own document name is its manuscript, not a letter.
    """
    role = docx_document_role(path.name, manuscript_names)
    if role == "cover":
        cover = templates.get("cover")
        return Path(cover) if cover else None
    supp = templates.get("supplementary")
    if supp and role == "supp":
        return Path(supp)
    main = templates.get("main")
    return Path(main) if main else None


def template_package_files(src: Path) -> list:
    """Every file of a submission package, minus process scratch/auxiliaries.

    `work/` is the pipeline's own scratch and the
    `*.tracking-<token>.<ext>` / `*.logging-<token>.<ext>` auxiliaries are
    difference-tracking copies -- neither belongs to a submission, so the rebuilt
    package leaves them out (the same rule the corpus builder and the judges
    apply). Everything else -- figures, tables, data,
    bibliography, the author's own notes -- is copied byte-for-byte.
    An inert `<evidence area>.disabled/` tree is left out entirely: it is not
    submission content and not readable evidence.
    """
    out = []
    for p in sorted(Path(src).rglob("*")):
        if not p.is_file() or p.name.startswith("~$"):
            continue
        rel = p.relative_to(src)
        if "work" in rel.parts[:-1] or _is_aux_doc(p.name):
            continue
        if is_disabled_evidence_rel(rel.as_posix()):
            continue
        out.append(p)
    return out


def _stage_source_package(srcdir: Path, src: Path) -> None:
    """Copy the WHOLE package into the session's read-only `source/`, paths kept.

    The prompt tells the agent that `source/` is the package it carries into
    `out/` -- figures, tables and data included. Copying only `.docx` by
    basename left those files unreachable (and silently overwrote two nested
    same-named documents), so they could never reach the output package that
    becomes round 1's working original.
    """
    for f in template_package_files(src):
        dest = srcdir / f.relative_to(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        with contextlib.suppress(OSError):
            os.chmod(dest, 0o444)


def rebuild_package_from_templates(templates: dict, src: Path, dest: Path,
                                   force: bool = False, containers=(),
                                   manuscript_names=(), protected=()) -> dict:
    """Rebuild a WHOLE submission package inside the venue's own Word templates.

    Every package DOCX is restyled into the journal's template by
    `apply_word_template`: the template's styles/theme/font table/numbering and
    page geometry, its front matter (title/author/affiliations/correspondence/
    keywords/abstract, with the template's own paragraph spacing and the bold
    `* Correspondence:` label), its first-page logo header and page-number
    footers with the template's odd/even parity, and the template's Heading 1..N
    for section headings the source only direct-formatted. A COVER LETTER is
    restyled only into the venue's cover-letter template; with none, it is
    copied as authored because it follows the journal's guidelines and academic
    convention, never the manuscript template. The manuscript TEXT of every
    restyled file must stay byte-identical or THAT file is copied unchanged and
    reported as failed. Every non-DOCX file is copied byte-for-byte; `work/` and
    tracked-change auxiliaries are left out. The report is written BESIDE the
    package (`<dest>.template_report.json` / `.md`), never inside it -- a
    submission package must not carry pipeline artifacts.

    `manuscript_names` is `article_type_manuscript_names(ctx)`: the selected
    article type's own document name is its manuscript, not a letter.

    `protected` names trees `--force` must never delete. The caller passes the
    pipeline root: a non-empty root usually carries a `.docx` somewhere (its
    source corpus, a winner, a published clean version), so a `.docx`-presence
    test alone cannot tell a package directory from the root itself.
    """
    mod = _format_module()
    if mod is None:
        return {"ok": False, "error": f"{DOCX_FORMAT_MODULE} not found"}
    if not templates:
        return {"ok": False, "error": "the venue ships no official Word template"}
    src, dest = Path(src), Path(dest)
    if not src.is_dir():
        return {"ok": False, "error": f"the source package {src} is not a directory"}
    for guard in protected or ():
        guard = Path(guard)
        if is_within(dest, guard) or is_within(guard, dest):
            # Equal, inside or an ancestor: `--force` would replace the
            # pipeline's own tree (the confirmed `--dest <root> --force` repro).
            return {"ok": False,
                    "error": f"{dest} overlaps the pipeline tree {guard}; refusing to replace "
                             f"it (a --force destination must be a package directory outside "
                             f"the root, or <root>/{TEMPLATE_PACKAGE_DIRNAME})"}
    if is_within(dest, src) or is_within(src, dest):
        return {"ok": False, "error": "the source and the destination must not be nested"}
    if dest.exists() and not dest.is_dir():
        return {"ok": False, "error": f"{dest} exists and is not a directory"}
    if dest.is_dir():
        if not any(dest.iterdir()):
            pass
        elif force:
            # `--force` deletes the destination tree. Refuse to do that to a
            # directory that is plainly NOT a submission package: a mistyped
            # `--dest` must never recursively remove an arbitrary directory.
            if not any(p.is_file() and p.suffix.lower() == ".docx"
                       for p in dest.rglob("*")):
                return {"ok": False,
                        "error": f"{dest} is not empty and carries no .docx package document; "
                                 f"refusing to delete it (--force only replaces a built "
                                 f"submission package)"}
            rmtree_force(dest)
        else:
            return {"ok": False, "error": f"{dest} exists and is not empty (use --force)"}
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for p in template_package_files(src):
        target = dest / p.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() != ".docx":
            shutil.copy2(p, target)
            files.append({"file": p.relative_to(src).as_posix(), "kind": "copied"})
            continue
        tpl = template_for_package_file(p, templates, manuscript_names)
        if tpl is None and docx_document_role(p.name, manuscript_names) == "cover":
            # The venue ships no cover-letter template: the letter follows the
            # guideline/academic-convention chain, so it is carried as authored
            # -- NOT an error, and never restyled with the manuscript template.
            note = ("cover letter: no cover-letter template for this venue; kept as "
                    "authored (journal guidelines, then academic convention)")
            warning = ""
            if templates.get("main"):
                carried = sorted(_manuscript_front_matter_styles(Path(templates["main"]))
                                 & _style_usage(p))
                if carried:
                    warning = ("the letter still carries the manuscript template's front-matter "
                               f"style(s) {', '.join(carried)}: restyle it as a plain submission "
                               "letter")
            shutil.copy2(p, target)
            entry = {"file": p.relative_to(src).as_posix(), "kind": "copied",
                     "ok": True, "note": note}
            if warning:
                entry["warning"] = warning
            files.append(entry)
            continue
        rep = mod.apply_word_template(p, target, tpl, containers=containers) if tpl else \
            {"ok": False, "error": "no matching Word template for this document"}
        if rep.get("ok") and hasattr(mod, "zotero_report_for_docx"):
            # The restyle may not drop, unlink or malform a live field: with a
            # broken rebuild the ORIGINAL document (fields intact) is carried
            # instead -- a field-less template copy would poison every round.
            cont = mod.zotero_field_continuity_problems(
                mod.zotero_report_for_docx(p), mod.zotero_report_for_docx(target))
            if cont["errors"]:
                with contextlib.suppress(OSError):
                    target.unlink()
                rep = {"ok": False,
                       "error": "the template rebuild would change the live Zotero fields: "
                                + "; ".join(cont["errors"])[:300]}
        gap = _hf_gap(_docx_hf_signature(tpl), _docx_hf_signature(target)) if rep.get("ok") else {}
        if rep.get("ok") and not gap:
            files.append({"file": p.relative_to(src).as_posix(), "kind": "docx-rebuilt",
                          "ok": True, "text_unchanged": rep.get("text_unchanged"),
                          "template": rep.get("template"),
                          "headers_footers": _docx_hf_signature(target),
                          "headings_retagged": rep.get("headings_retagged"),
                          "changes": rep.get("changes")})
        elif rep.get("ok") and gap:
            files.append({"file": p.relative_to(src).as_posix(),
                          "kind": "docx-rebuilt-incomplete", "ok": False,
                          "template": rep.get("template"),
                          "error": "the rebuild did not carry the template's "
                                   "headers/footers: " + json.dumps(gap)})
        else:
            shutil.copy2(p, target)
            files.append({"file": p.relative_to(src).as_posix(),
                          "kind": "docx-kept-original", "ok": False,
                          "error": rep.get("error")})
    rebuilt = [f for f in files if f["kind"] == "docx-rebuilt"]
    failed = [f for f in files if f.get("ok") is False]
    report = {"ok": not failed, "source": str(src), "dest": str(dest),
              "templates": {k: str(v) for k, v in templates.items()},
              "documents_rebuilt": len(rebuilt), "files_copied":
                  sum(1 for f in files if f["kind"] == "copied"),
              "failed": [f["file"] for f in failed],
              "warnings": [f"{f['file']}: {f['warning']}" for f in files if f.get("warning")],
              "files": files}
    write_json_atomic(dest.parent / (dest.name + ".template_report.json"), report)
    (dest.parent / (dest.name + ".template_report.md")).write_text(
        template_package_md(report), encoding="utf-8")
    return report


def template_package_md(report: dict) -> str:
    """The readable sibling of the package rebuild's JSON report."""
    L = [f"# Template package: `{report['dest']}`", "",
         f"- source: `{report['source']}`",
         f"- templates: " + ", ".join(f"{k}=`{v}`" for k, v in report["templates"].items()),
         f"- rebuilt documents: {report['documents_rebuilt']}",
         f"- other files copied: {report['files_copied']}",
         f"- failures: {', '.join(report['failed']) if report['failed'] else 'none'}",
         f"- warnings: {len(report.get('warnings') or [])}", ""]
    for f in report["files"]:
        if f["kind"] == "docx-rebuilt":
            L.append(f"- `{f['file']}`: template text preserved="
                     f"{f.get('text_unchanged')}; headings retagged="
                     f"{len(f.get('headings_retagged') or [])}")
        elif f["kind"] == "docx-kept-original":
            L.append(f"- `{f['file']}`: KEPT ORIGINAL -- {f.get('error')}")
        elif f.get("note"):
            L.append(f"- `{f['file']}`: carried as authored -- {f['note']}")
        if f.get("warning"):
            L.append(f"- `{f['file']}`: WARNING -- {f['warning']}")
    return "\n".join(L) + "\n"


def _package_rel_key(path, root) -> str:
    """A produced/input file's path relative to its package root, version-token free.

    Used to pair a validation failure with the SAME file in the package the
    stage started from. The version token is PART of a stage's file name
    (`...-supp-b.tex` -> `...-supp-c.tex`), so it is stripped exactly as
    `_docx_field_key` strips it for the Zotero field gate (falls back to the
    basename for a file outside the root).
    """
    rel = os.path.relpath(str(path), str(root))
    if rel.startswith(".."):
        rel = Path(path).name
    return _docx_field_key(rel)


def _package_rel_path(path, root) -> str:
    """The file's exact path relative to its package root (basename when outside)."""
    rel = os.path.relpath(str(path), str(root))
    return Path(path).name if rel.startswith("..") else rel


def _validation_targets(root: Path) -> list:
    """The files validation may fail on: the declared submitted set, else all.

    A stage's package also carries hand-off READMEs, ledgers and scratch. A
    malformed scratch `.docx` under `work/` is not a deliverable, and failing an
    attempt for it (the neohet revise attempt 1) is a false failure. When the
    package declares its submitted set, validate exactly that; otherwise keep
    the old whole-directory behaviour.
    """
    decl = declared_submission_set(Path(root))
    if decl.get("declared") and decl.get("files"):
        out = []
        for rel in decl["files"]:
            q = Path(root) / rel
            if q.is_file() and q.suffix.lower() in (".docx", ".tex", ".ltx"):
                out.append(q)
        if out:
            return out
    return [Path(root)]


def _validate_stage_package(ctx: Ctx, rec: dict, pkg_dir: Path, input_dir: Path,
                            errs: list, warns: list) -> dict:
    """DOCX-XML/schema + LaTeX-compile validation of a produced package.

    A DOCX that does not parse, or a LaTeX document that no longer compiles when
    the SAME document in the package the stage started from DID compile, is a
    broken deliverable: it fails the attempt so the retry policy hands the
    session another go. A compile failure that already exists in the same file
    of the input package is reported, not failed (the pipeline must not punish
    an agent for the author's broken source). The pairing is per file: a
    sibling that was already broken must not excuse a break this stage
    introduced in a document that did compile before, while the stage's own
    version token (`...-supp-b.tex` -> `...-supp-c.tex`) still pairs with the
    SAME document. The result is recorded on the run (`rec["validation"]`) and
    printed.
    """
    mod = _format_module()
    res = {"docx_ok": None, "tex_ok": None, "files": 0, "failures": []}
    if mod is None:
        return res
    rep = mod.validate_paths(_validation_targets(pkg_dir), timeout=VALIDATE_TEX_TIMEOUT)
    res["files"] = rep.get("files", 0)
    docx_fail = [r for r in rep["results"] if r["kind"] == "docx" and r["ok"] is False]
    tex_fail = [r for r in rep["results"] if r["kind"] == "tex" and r["ok"] is False]
    tex_done = [r for r in rep["results"] if r["kind"] == "tex" and r["ok"] is True]
    res["docx_ok"] = not docx_fail
    res["tex_ok"] = (not tex_fail) if tex_done else None
    for r in docx_fail:
        first = (r.get("errors") or [r.get("detail") or "invalid"])[0]
        msg = f"VALIDATION: {Path(r['file']).name} is not a valid DOCX: {first}"
        res["failures"].append(msg)
        errs.append(msg)
    if tex_fail:
        base_by_rel, base_by_key = {}, {}
        if input_dir.is_dir():
            brep = mod.validate_paths(_validation_targets(input_dir),
                                      timeout=VALIDATE_TEX_TIMEOUT)
            for r in brep["results"]:
                if r["kind"] != "tex":
                    continue
                base_by_rel[_package_rel_path(r["file"], input_dir)] = r
                base_by_key.setdefault(_package_rel_key(r["file"], input_dir), []).append(r)
        introduced, inherited = [], []
        for r in tex_fail:
            first = (r.get("errors") or [r.get("detail") or "failed"])[0]
            # The exact path wins; a version-token rename pairs only when it is
            # unambiguous (two documents that strip to one key stay unmatched
            # rather than being paired at random).
            before = base_by_rel.get(_package_rel_path(r["file"], pkg_dir))
            if before is None:
                same_key = base_by_key.get(_package_rel_key(r["file"], pkg_dir)) or []
                before = same_key[0] if len(same_key) == 1 else None
            (inherited if before is not None and before.get("ok") is False
             else introduced).append((r, first))
        if introduced:
            detail = "; ".join(f"{Path(r['file']).name}: {first}" for r, first in introduced)
            msg = f"VALIDATION: the LaTeX in this package no longer compiles ({detail})"
            res["failures"].append(msg)
            errs.append(msg)
        if inherited:
            detail = "; ".join(f"{Path(r['file']).name}: {first}" for r, first in inherited)
            warns.append(f"VALIDATION: the LaTeX does not compile ({detail}); the same file did "
                         f"not compile in the package this stage started from either, so this is "
                         f"reported, not failed")
    return res


def _scan_rule_delta(summary: dict) -> list:
    """Finding-tier rules the format fixer's OWN scans gained (before -> after).

    The caption merge (FMT-T2c) changes the text model: a continuation
    paragraph becomes part of its legend, so rules that read the model (the
    legend sentence bar, term repetition) can gain rows without the AGENT
    having changed a character of text. The stage regression check reads this
    attribution together with the fixer's own change list (see
    `scan_regression_problems(..., fixer_reclassified=...)`).
    """
    def _counts(info) -> Counter:
        return Counter(str(r.get("rule") or "")
                       for r in ((info or {}).get("rows") or []))
    before = _counts((summary or {}).get("scan_before"))
    after = _counts((summary or {}).get("scan_after"))
    return sorted(rule for rule, n in after.items() if rule and n > before.get(rule, 0))


def _format_fix_stage_package(ctx: Ctx, rec: dict, pkg_dir: Path, warns: list,
                             errs: list = None) -> dict:
    """Normalize one stage package BEFORE it is fingerprinted, pinned or judged.

    Runs inside the stage postchecks, so the repaired bytes are what the
    document-set check, the corpus digest, the pins, the judge views and the
    next round's base all see -- the content-addressed invariant ("the pin
    equals the corpus the judges scored") stays true. The artifact is written
    next to the run (`FORMAT_FIX_<stage>.json`) because a top-level JSON inside
    the package would become submission content.

    The ZOTERO FIELD CONTINUITY gate runs on the FINAL bytes whatever the
    format-fix policy says (including `--format-fix off`): the package this
    stage hands on must carry every live field of the base version, may edit
    or delete individual fields with their citation text, and may never drop
    them all or leave one malformed.

    The PKG-2 removal (a to-be-submitted document may not point at what the
    submission does not carry) runs the same way, for the same reason: it is a
    submission-surface fact, not a style preference, so `--format-fix off` does
    not switch it off.
    """
    sb = ctx.sandbox_of(rec)
    inp = sb / ("self" if rec.get("kind") == "integrate" else "base")
    if errs is None:
        errs = []

    # A stage package is the session's OWN output directory, written inside the
    # sandbox. A symlinked `revised/` (or `rewritten/`, `integrated/`) is not
    # that directory: every destructive pass below would follow the link and
    # rewrite/delete the TARGET's files while the postcheck reports a normal
    # package. Refuse it before any helper runs -- the hand-off README move,
    # the format normalizer and the non-shippable/PKG-2 sweeps all write.
    if Path(pkg_dir).is_symlink():
        errs.append(
            f"{rec['id']}: {Path(pkg_dir).name}/ is a SYMLINK; a stage package must be a "
            f"real directory inside the run sandbox. Refusing to normalize or sweep it "
            f"(the linked target is outside this stage's output)")
        rec["format_fix"] = {"label": rec.get("id"),
                             "skipped": "symlinked package root",
                             "symlink": str(Path(pkg_dir))}
        return rec["format_fix"]

    # `author_to_complete: readme` (the default): the stage's missing-item
    # hand-off belongs in the package's README, beside the cover letter and main
    # text. The prompt asks the session to write it; if the session instead left
    # the item in MANUAL_STEPS.md in marker form, move it into the README here so
    # the hand-off cannot disappear when the bookkeeping file is stripped from
    # the version corpus. This is a MOVE of the stage's own text, never new
    # content, and it runs before the package is fingerprinted.
    if pkg_dir.is_dir():
        try:
            rec["handoff_readme"] = ensure_handoff_readme(ctx, pkg_dir, warns=warns, rec=rec)
        except Exception as e:                                        # noqa: BLE001
            rec["handoff_readme"] = {"error": f"{type(e).__name__}: {e}"}
            warns.append(f"AUTH-2: the hand-off README could not be generated from "
                         f"MANUAL_STEPS.md ({type(e).__name__}: {e}); the stage's own README "
                         f"(when it wrote one) is unchanged")

    def _field_gate() -> dict:
        rep = zotero_field_continuity_check(inp, pkg_dir, rec["id"], errs, warns)
        rec["zotero_fields"] = rep
        if rep.get("errors"):
            warns.append(f"ZOTERO FIELD CONTINUITY: {rec['id']}: {rep['errors']} field "
                         f"error(s) across {rep['checked']} document(s); the attempt fails until "
                         f"every baseline field is a live, well-formed field in the delivered "
                         f"package (see zotero_fields in the run record)")
        return rep

    # PKG-2 repair FIRST (and whatever the format-fix policy says): a
    # to-be-submitted document may not point at what the submission does not
    # carry, and the pointer is REMOVED here (the sentence that carries it)
    # rather than shipped dangling. Running before the format normalization
    # means that pass sees the final text (and cleans up an emptied paragraph).
    # The session was told the rule by the code-side pack; this is the
    # mechanical guarantee.
    try:
        # BOTH corpus halves: corpus_sources() folds the run's code/ area into
        # the version corpus, so sweeping only the package let a .pyc reach the
        # digest/pin/publication.
        rec["non_shippable_strip"] = strip_stage_non_shippable(sb, pkg_dir)
    except Exception as e:                                            # noqa: BLE001
        rec["non_shippable_strip"] = {"error": f"{type(e).__name__}: {e}",
                                      "removed": []}
        warns.append(f"PKG-1: the non-shippable-file strip could not run "
                     f"({type(e).__name__}: {e}); the package is reported, not repaired")
    if pkg_dir.is_dir():
        _reports_root = getattr(ctx, "reports_dir", None)
        if _reports_root is None and getattr(ctx, "root", None) is not None:
            _reports_root = Path(ctx.root) / "reports"
        if _reports_root is not None:
            try:
                _held_before = list(rec.get("held_internal_readme_notes") or [])
                _held_now = hold_internal_readme_notes(
                    pkg_dir,
                    Path(_reports_root) / README_NOTE_HOLD_DIRNAME / rec["id"],
                    warns=warns)
                _held_seen = {
                    (str(h.get("file")), str(h.get("held_at"))) for h in _held_before}
                rec["held_internal_readme_notes"] = _held_before + [
                    h for h in _held_now
                    if (str(h.get("file")), str(h.get("held_at"))) not in _held_seen]
            except Exception as e:                                    # noqa: BLE001
                rec["held_internal_readme_notes"] = []
                warns.append(f"PKG-1: the internal-note README pass could not run "
                             f"({type(e).__name__}: {e}); the package is reported")
        try:
            rec["reference_strip"] = strip_dangling_references_in_dir(
                pkg_dir, submission_not_carried_areas(ctx), rec["id"], warns=warns,
                artifacts_dir=ctx.sandbox_of(rec),
                artifact_name=f"PKG2_{rec['id']}.json")
        except Exception as e:                                        # noqa: BLE001
            rec["reference_strip"] = {"label": rec["id"], "error": f"{type(e).__name__}: {e}"}
            warns.append(f"PKG-2: the dangling-reference removal could not run "
                         f"({type(e).__name__}: {e}); the package is reported, not repaired")
    if str((ctx.cfg or {}).get("format_fix") or DEFAULT_FORMAT_FIX) == "off":
        rec["format_fix"] = {"label": rec["id"], "skipped": "format_fix=off"}
        _field_gate()
        return rec["format_fix"]
    if not pkg_dir.is_dir():
        rec["format_fix"] = {"label": rec["id"], "skipped": f"{pkg_dir.name}/ is missing"}
        _field_gate()
        return rec["format_fix"]
    try:
        rec["format_fix"] = normalize_formatting_in_dir(
            pkg_dir, pre_judge_format_policy(ctx), rec["id"], warns=warns,
            artifacts_dir=ctx.sandbox_of(rec), template=venue_word_templates(ctx) or None,
            containers=venue_containers(ctx))
        # Finding-tier rules the fixer's OWN before/after scans gained in this
        # package (see `_scan_rule_delta`): the caption merge changes the text
        # model, so the stage regression check reads them with that attribution.
        rec["format_fix_rules_introduced"] = _scan_rule_delta(rec["format_fix"])
    except Exception as e:                                            # noqa: BLE001
        rec["format_fix"] = {"label": rec["id"], "error": f"{type(e).__name__}: {e}"}
        warns.append(f"FORMAT-FIX: the code-side formatting normalization could not run "
                     f"({type(e).__name__}: {e}); the package is reported, not repaired")
    # Field continuity is checked on the package as it now stands (after the
    # repair), against the stage's own base/self input.
    _field_gate()
    # DELIVERABLE VALIDATION: the package the stage produced must be readable
    # (every DOCX part parses; the `docx` schema check when the CLI exists) and
    # its LaTeX must compile when the package it started from compiled. A failure
    # is an ERROR, so the retry policy gives the session another attempt (the
    # agent prompt asks for the same check, with up to three iterations).
    try:
        rec["validation"] = _validate_stage_package(ctx, rec, pkg_dir, inp, errs, warns)
    except Exception as e:                                            # noqa: BLE001
        warns.append(f"VALIDATION: the deliverable check could not run "
                     f"({type(e).__name__}: {e})")
    # Consistency check: re-derive the SAME code-side evidence the other sessions
    # were given, for the package this stage produced, and compare it with the
    # package the stage started from. Regressions are reported (never silently
    # accepted), because the review, the change-ledger and the judge panel all
    # quote these numbers.
    input_dir = sb / ("self" if rec.get("kind") == "integrate" else "base")
    try:
        # The produced package's corpus is not just its output directory: the
        # run's own `code/` directory ships with it under the `code/` prefix (see
        # corpus_sources), so the pack is scanned from the SAME source list the
        # recorded corpus digest uses -- otherwise the pack's identity would
        # differ from the digest the pin, the judge target and the next round's
        # base are built from.
        vid = freshness_vid(rec)
        after_sources = None
        if vid and rec.get("round"):
            after_sources = corpus_sources(ctx, int(rec["round"]), vid) or None
        after = code_side_evidence(ctx, pkg_dir, f"{rec['id']}:after", sources=after_sources)
        before = code_side_evidence(ctx, input_dir, f"{rec['id']}:before") \
            if input_dir.is_dir() else None
        delta = {}
        if before:
            def _over_cap(ev):
                return len(((ev or {}).get("lengths") or {}).get("over_limit") or [])

            def _placeholders(ev):
                return int(((ev or {}).get("placeholders") or {}).get("count") or 0)

            delta = {
                "over_cap_sections": {"before": _over_cap(before), "after": _over_cap(after)},
                "placeholders": {"before": _placeholders(before), "after": _placeholders(after)},
                "format_rows": {
                    "before": len((before.get("format") or {}).get("rows") or []),
                    "after": len((after.get("format") or {}).get("rows") or []),
                    "high_before": (before.get("format") or {}).get("high", 0),
                    "high_after": (after.get("format") or {}).get("high", 0)},
            }
            if delta["over_cap_sections"]["after"] > delta["over_cap_sections"]["before"]:
                warns.append(
                    f"EVIDENCE: this stage left MORE over-cap section(s) than it started with "
                    f"({delta['over_cap_sections']['before']} -> "
                    f"{delta['over_cap_sections']['after']}); the length rows are in "
                    f"CODE_SCANS.json and the agents' M19 artifact is authoritative")
            ph_delta = delta["placeholders"]["after"] - delta["placeholders"]["before"]
            if ph_delta:
                msg = (f"EVIDENCE: hand-off placeholders "
                       f"{delta['placeholders']['before']} -> "
                       f"{delta['placeholders']['after']} (+{ph_delta}); they are the stage's "
                       f"declared hand-offs, never scored, and are listed in CODE_SCANS.json")
                _atc = author_to_complete_mode_of(ctx)
                if _atc == "document":
                    warns.append(msg)
                else:
                    # `readme` / `off`: the operator forbade the marker in a
                    # document, so a stage that WROTE one disobeyed its own
                    # prompt. The attempt FAILS (the declaration is what the
                    # operator asked for, not a preference): the item belongs in
                    # the package's hand-off README or in MANUAL_STEPS.md.
                    (errs if isinstance(errs, list) else warns).append(
                        f"EVIDENCE: the stage ADDED {ph_delta} hand-off placeholder(s) "
                        f"({delta['placeholders']['before']} -> "
                        f"{delta['placeholders']['after']}) although this root runs with "
                        f"`author_to_complete: {_atc}`: no document may carry the "
                        f"[AUTHOR TO COMPLETE: ...] token. Remove the marker(s) from the "
                        f"files (keeping whatever content around them is real) and record the "
                        f"hand-off item(s) in the package's own {handoff_target(_atc)}"
                        f"{' / CHANGELOG.md' if _atc == 'off' else ''} "
                        f"instead -- the rows are in CODE_SCANS_after.json")
                    warns.append(msg)
        rec["evidence_after"] = after
        rec["evidence_delta"] = delta
        write_json_atomic(sb / "CODE_SCANS_after.json", {"after": after, "before": before,
                                                         "delta": delta})
        write_json_atomic(sb / "CODE_SCANS_before.json", before or {})
    except Exception as e:                                            # noqa: BLE001
        warns.append(f"EVIDENCE: the code-side evidence re-scan failed "
                     f"({type(e).__name__}: {e})")
    return rec["format_fix"]


def _seed_write(path: Path, text: str) -> bool:
    """Write a seeded file UNLESS it already exists (atomic when it does write).

    The seeded evidence tables are INPUTS the session disposes IN PLACE, and the
    materializers run again on every invocation: `run` re-materializes a failed
    run whose completion marker exists so its postcheck can be re-evaluated, and
    it re-materializes a dirty sandbox without launching a second agent. Blindly
    rewriting the seed there HASHED THE SESSION'S VERDICTS AWAY (the M20/M18/M19/
    OUTLINE tables came back empty and undisposed), which turned every such
    re-postcheck into a guaranteed failure and made a completed review
    unrecoverable. Writes are atomic so an existing file is never a truncated
    seed, and a genuinely missing one is still created.
    """
    if path.exists():
        return False
    # tmp + rename (NOT write_text_atomic's extra fsync): the content is complete
    # before the rename, so an interrupted write can never leave a truncated
    # seed, while the fsync would cost one disk sync per seeded file on every
    # materialization -- ~20 files per session, measured as ~0.7s per sandbox on
    # the operator's mount, which is exactly the latency the scheduling tests
    # (and the real run) pay for a pure input.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return True


def _seed_review_format_artifact(ctx: Ctx, sb: Path) -> dict:
    """Seed the M20 sweep for a review run: the code-side scan IS the enumeration.

    Text-only converters cannot see layout or character formatting, so the
    orchestrator enumerates it (`review/work/FORMAT_SCAN.json`) and seeds the
    artifact table (`review/artifacts/M20_formatting.md`) with one row per
    finding; the review prompt requires the agent to dispose every row (and to
    add the classes the scan cannot see). The review postcheck requires the M20
    coverage row like M18/M19.
    """
    policy = format_policy_of(ctx)
    base = sb / "base"
    info = (scan_format_in_sources([(base, "", ())], policy=policy) if base.is_dir()
            else {"rows": [], "by_rule": {}, "high": 0, "medium": 0, "low": 0,
                  "unavailable": "base/ is missing"})
    work = sb / REVIEW_DIR / "work"
    work.mkdir(parents=True, exist_ok=True)
    write_json_atomic(work / "FORMAT_SCAN.json", info)
    lines = [
        "# M20 — OOXML style/formatting (pipeline-mandated)",
        "",
        f"Enumeration: the code-side scan of base/ is in `{M20_FORMAT_SCAN_REL}`; "
        "the rows are repeated below.",
        "AUDIT every row: write a finding id or `OK — <reason>` in the disposition column. "
        "Add rows for formatting defects the scan cannot see (font family/size, justification, "
        "line spacing, legend placement, table formatting, heading numbering). "
        "\"Not checked\" is not an allowed value.",
        "",
        "Mechanical rows (break-only paragraph/blank page, legend spacing, heading keepNext, "
        "running head on the title page, unintended italics outside Zotero fields, mixed "
        "hyperlink/plain URL+email treatments, proofing markers, a stray empty paragraph that is "
        "not template-prescribed, a space at a visual line edge, a doubled word, an image "
        f"delivered off its own aspect ratio) are repaired by the orchestrator before judging "
        f"(`{M20_FIX_CMD}`); the editorial rows (em-dash density, quotation style, "
        "journal-italic policy, doubled spaces / bracket spacing / zero-width marks, a possible "
        "lowercase sentence start, missing space after punctuation, mixed direct fonts, "
        "paragraph spacing/indentation/alignment drift, heading-level jumps) are findings for "
        "the revision/integration arms. The venue template's own blank-paragraph slots travel in "
        "`format_policy.json`: a blank the template prescribes (the spacer above the title, a "
        "placeholder between two headings) is never a row here, and dispositioning one as "
        "`OK — template-prescribed slot` is the correct close.",
        "",
        "DISPOSITION BAR — a `tier=finding` row is a defect an editor or a copyeditor would "
        "raise, so its disposition must be about THAT row's own bar: a finding id, or "
        "`OK — <the rule's bar, and why this instance is inside it>`. \"No journal rule\" and "
        "\"editorial preference only\" are NOT reasons for a finding-tier row (a writing-quality "
        "defect does not need a journal rule to exist), and the SAME sentence repeated across "
        "many rows is treated as an undisposed row by the postcheck and by "
        "`decide --residual-gate`.",
        "",
        "FMT-CL1 (the cover letter formatted in the MANUSCRIPT template: it uses the manuscript "
        "template's Title/Author-List styles or carries its header/footer parts although the "
        "venue ships no cover-letter template) can be closed `OK` ONLY with the journal's own "
        "template/guideline text quoted that REQUIRES this formatting (its source and what it "
        "requires). \"The run carries the letter in the journal's styles\" is the pipeline's "
        "rule, not the journal's: the postcheck fails that closure. Otherwise dispose it with a "
        "finding (M20).",
        "",
        "| # | rule | tier | severity | location | evidence | fix kind | disposition |",
        "|---|---|---|---|---|---|---|---|",
    ]
    rows = info.get("rows") or []
    for i, r in enumerate(rows, 1):
        evidence = str(r.get("evidence", "")).replace("|", "\\|")[:140]
        lines.append(f"| {i} | {r['rule']} | {r.get('tier') or 'advisory'} | {r['severity']} | "
                     f"{r['location']} | {evidence} | {r['fix']} |  |")
    if not rows:
        lines.append("| - | — | — | — | — | no code-side formatting finding | — |  |")
    art = sb / REVIEW_DIR / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    _seed_write(art / "M20_formatting.md", "\n".join(lines) + "\n")
    return info


def code_side_evidence(ctx: Ctx, corpus_dir: Path, label: str, sources: list = None) -> dict:
    """The deterministic evidence every session is given, in one structure.

    The same functions the pipeline uses at `setup`/`decide` scan the corpus:
    M18 legend counts, M19 abstract/main-text lengths, M20 OOXML style/
    formatting rows, the hand-off placeholder count and the corpus identity
    (digest, file list, revision token). Seeding this pack into every session
    means the review, the rewritten/revised/integrated packages and the judge
    panel all see the SAME numbers and rows, instead of three different
    agent-side re-counts.

    The scans apply the SAME file-set rules the rest of the pipeline applies to
    a version corpus: the revision auxiliaries and the pipeline's own
    bookkeeping are dropped by the scanners, and the process scratch
    (`CORPUS_EXCLUDE_TOP`, i.e. `work/`) is excluded here. That is not cosmetic:
    a stage writes its scratch INSIDE its output directory, so a raw walk of
    `runs/<stage>/revised/` counted the agent's snapshot/render/note files as if
    they were manuscript documents -- a real run reported "this stage left MORE
    over-cap section(s) (0 -> 7)" and "hand-off placeholders 4 -> 73" purely from
    its own `work/` copies, and handed the pack a corpus digest that no other
    part of the pipeline used (the recorded, pinned and judged digest is the one
    `corpus_manifest()` computes, which excludes `work/`).
    """
    evidence = {"label": label, "generated_at": utcnow(), "corpus": str(corpus_dir)}
    if sources is None:
        # A plain directory (a sandbox input copy, the blinded target, the
        # pristine original): its own top-level `work/` is scratch, never content.
        sources = [(corpus_dir, "", CORPUS_EXCLUDE_TOP)]
    try:
        evidence["captions"] = scan_captions_in_sources(sources, limit=caption_limit_of(ctx))
    except Exception as e:                                            # noqa: BLE001
        evidence["captions"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        evidence["lengths"] = scan_lengths_in_sources(sources,
                                                       profile=venue_profile_of(ctx, required=False))
    except Exception as e:                                            # noqa: BLE001
        evidence["lengths"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        evidence["format"] = scan_format_in_sources(sources, policy=format_policy_of(ctx))
    except Exception as e:                                            # noqa: BLE001
        evidence["format"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        evidence["placeholders"] = scan_placeholders_in_sources(sources)
    except Exception as e:                                            # noqa: BLE001
        evidence["placeholders"] = {"error": f"{type(e).__name__}: {e}"}
    # PKG-2 (AGENTS.md): a to-be-submitted document may not point at what the
    # submission does not carry. The mechanical half runs in every
    # package-producing stage's postcheck (the sentence is REMOVED there); this
    # seed puts the rows in front of the review/audit/revise sessions FIRST, so
    # the sentence is rewritten in prose instead of lost, and so a document the
    # mechanical edit cannot touch (a structural file, a pointer inside a live
    # citation field) is still fixed by someone.
    try:
        areas = submission_not_carried_areas(ctx)
        evidence["submission_references"] = {
            "not_carried": list(areas),
            "rows": non_submitted_reference_rows(corpus_dir, areas)}
    except Exception as e:                                            # noqa: BLE001
        evidence["submission_references"] = {"error": f"{type(e).__name__}: {e}"}
    # PLACEHOLDER FILES (2026-10-17): a file that stands in for data it does not
    # contain (the operator's example: the ACT haplotypes are really HG008's) is
    # NEVER evidence. The report names the declared placeholders and the detected
    # duplicate-under-another-sample-name copies, and every role is told (in the
    # evidence pack and the prompt rule) to ignore them as producers.
    try:
        evidence["placeholder_files"] = placeholder_files_report(
            corpus_dir,
            extra_globs=_placeholder_globs_from_ctx(ctx),
            area_names=submission_not_carried_areas(ctx))
    except Exception as e:                                            # noqa: BLE001
        evidence["placeholder_files"] = {"error": f"{type(e).__name__}: {e}"}
    # The two families that only the PUBLISHED package used to see, seeded here
    # so a review/audit/revise session can ADDRESS them in prose (the mechanical
    # layer reports them; only the editing arms can ship a figure, embed it, or
    # re-point a citation):
    #   * PKG-4 -- a display item the documents cite (and legend) while the
    #     package carries no figure file for it (the operator's "Figure S3 is
    #     cited and has a legend, but it is not in the submission");
    #   * FMT-TP1 -- the title page does not print the content type this run is
    #     configured for (a GAP the venue profile states no rule for, so it is
    #     counted and named, never turned into a requirement).
    try:
        evidence["display_items"] = {
            "rows": package_display_item_rows(corpus_dir, submission_not_carried_areas(ctx))}
    except Exception as e:                                            # noqa: BLE001
        evidence["display_items"] = {"error": f"{type(e).__name__}: {e}"}
    # PKG-5: two shipped surfaces disagreeing about a display item's PRODUCER
    # (a resources-table row vs the item's own legend). Seeded so the review
    # files it and the reviser reconciles it in prose -- the pipeline never picks
    # a side.
    try:
        evidence["display_provenance"] = {
            "rows": display_provenance_rows(corpus_dir, submission_not_carried_areas(ctx))}
    except Exception as e:                                            # noqa: BLE001
        evidence["display_provenance"] = {"error": f"{type(e).__name__}: {e}"}
    # PKG-6..9 (2026-10-15): statements the package makes ABOUT ITSELF that
    # contradict each other -- an AI-use denial beside the AI workflow it denies,
    # one identifier written at two lengths, and one comparison described with
    # two units of analysis (the operator's result-driven audit of the two
    # delivered packages found all three, and every existing rule compares a
    # surface against itself or against the raw data, never two statements).
    # Seeded so the review/revise arms can repair the PROSE -- the mechanical
    # layer reports them and never rewrites a sentence it cannot adjudicate.
    try:
        evidence["contradictions"] = {"rows": package_contradiction_rows(corpus_dir)}
    except Exception as e:                                            # noqa: BLE001
        evidence["contradictions"] = {"error": f"{type(e).__name__}: {e}"}
    # PKG-11/12/14/15/16 (2026-10-17): package self-consistency. Seeded for the
    # review, audit and revision arms -- most of these can only be repaired by
    # the author (rename a header / regenerate a table / correct a letter), so the
    # row must reach prose that says what was done.
    try:
        _pkg_texts = _package_document_texts(corpus_dir)
        evidence["package_consistency"] = {
            "column_near_misses": scan_column_name_near_misses(corpus_dir),
            "mcb_rule_conflicts": scan_mcb_rule_conflicts(corpus_dir),
            "pooled_table_mismatches": scan_pooled_table_mismatches(corpus_dir),
            "form_software_coverage": scan_form_software_coverage(corpus_dir),
            "prior_submission_disclosure": scan_prior_submission_disclosure(corpus_dir),
            "form_method_conflicts": scan_form_method_conflicts(corpus_dir, texts=_pkg_texts),
            "ranking_claim_conflicts": scan_ranking_claim_conflicts(corpus_dir,
                                                                   texts=_pkg_texts),
            "recovered_structure_claims": scan_recovered_structure_claims(corpus_dir,
                                                                         texts=_pkg_texts),
            "sd_estimator_ambiguity": scan_sd_estimator_ambiguity(corpus_dir,
                                                                 texts=_pkg_texts),
            "definition_overreach": scan_definition_overreach(corpus_dir, texts=_pkg_texts),
            "cited_note_negations": scan_cited_note_negations(corpus_dir, texts=_pkg_texts),
            "single_cell_citation_mismatch": scan_single_cell_citation_mismatch(
                corpus_dir, texts=_pkg_texts),
            "caption_definition_gaps": scan_caption_definition_gaps(corpus_dir,
                                                                   texts=_pkg_texts),
            "form_failure_claims": scan_form_failure_claims(corpus_dir, texts=_pkg_texts),
        }
    except Exception as e:                                            # noqa: BLE001
        evidence["package_consistency"] = {"error": f"{type(e).__name__}: {e}"}
    # WHICH FILES THE SUBMISSION ACTUALLY CARRIES: the package's own README may
    # declare the submitted set (a glob); when it does and the declaration is
    # plausible, the scans above already used it, and every session is told, so a
    # "does this reference resolve?" judgement is made against what ships.
    try:
        _decl = declared_submission_set(corpus_dir)
        evidence["submission_declaration"] = {
            "readme": _decl.get("readme"), "patterns": _decl.get("patterns") or [],
            "declared": bool(_decl.get("declared")),
            "ignored_reason": _decl.get("ignored_reason"),
            "submitted_files": (_decl.get("files") or [])[:60],
            "submitted_count": len(_decl.get("files") or []) if _decl.get("declared") else None,
            "not_submitted_count": (len(_decl.get("carried_not_submitted") or [])
                                    if _decl.get("declared") else None)}
    except Exception as e:                                            # noqa: BLE001
        evidence["submission_declaration"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        evidence["front_matter_gaps"] = {"rows": front_matter_gap_rows(ctx, corpus_dir)}
    except Exception as e:                                            # noqa: BLE001
        evidence["front_matter_gaps"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        man = manifest_for_sources(sources)
        evidence["corpus_identity"] = {
            "digest": manifest_digest(man),
            "files": sorted(man["files"]),
            # The TOKEN string, not the whole report dict: the one consumer
            # (the EVIDENCE_PACK writer) interpolates this field, and the
            # prompts tell sessions to quote a 7-hex token -- a Python dict repr
            # was noise exactly where a token was promised.
            "revision_token": (revision_token_for_dir(corpus_dir) or {}).get("token")}
    except Exception as e:                                            # noqa: BLE001
        evidence["corpus_identity"] = {"error": f"{type(e).__name__}: {e}"}
    # ---- artifact engines (numbers M4, terms M8, outline, placeholders) -------
    # The same text the style rules see, turned into the tables the sessions must
    # dispose: every number with its sentence (source column to fill), the key
    # terms' occurrences, a hierarchy scaffold for the summary pass, and the
    # hand-off placeholders classified searchable vs author-only.
    mod = _format_module()
    if mod is not None:
        try:
            docs = corpus_text_documents(sources)
            numbers, terms, outline, ph_rows = [], [], [], []
            claim_rows = []
            all_texts = []
            for name, rows in docs:
                paras = [r[0] for r in rows]
                all_texts.extend(paras)
                is_ref = [r[1] for r in rows]
                headings = [r[2] for r in rows]
                prose = [t for i, t in enumerate(paras) if not is_ref[i]]
                prose_doc_idx = [i for i in range(len(paras)) if not is_ref[i]]
                prose_kinds = mod.section_kinds(
                    prose, [h for i, h in enumerate(headings) if not is_ref[i]])
                for r in mod.number_ledger(prose):
                    # The section kind travels with the number: M30 seeds only
                    # claim-bearing surfaces (front/abstract/body/legend), the
                    # same rule the claim-strength ledger uses.
                    idx = int(r.get("document_paragraph") or 0)
                    kind = prose_kinds[idx] if idx < len(prose_kinds) else "body"
                    # number_ledger enumerates the PROSE list; the evidence
                    # must print the DOCUMENT paragraph number (a bibliography
                    # before the body offset every row).
                    if idx < len(prose_doc_idx):
                        r["document_paragraph"] = prose_doc_idx[idx]
                    numbers.append(dict(r, document=name, kind=kind))
                # J3's two-sided claim-strength ledger: the OVER direction
                # (maximal claims) and the UNDER direction (hedges) are
                # enumerated together, so a session cannot report the loud
                # direction and leave the quiet one unexamined. The section
                # kinds come from the document's own headings (a Methods
                # paragraph is a protocol, not a claim surface).
                # Guarded: a mismatch between this script and an older
                # companion module must degrade to "no ledger", never abort the
                # whole artifact-engine block (numbers/terms/outline share it).
                claim_fn = getattr(mod, "claim_strength_rows", None)
                if claim_fn is not None:
                    for r in claim_fn(paras, is_ref, mod.section_kinds(paras, headings)):
                        claim_rows.append(dict(r, document=name))
                for r in mod.key_term_rows(paras):
                    terms.append(dict(r, document=name))
                for r in mod.outline_rows(paras, headings, name):
                    outline.append(dict(r, document=name))
                for r in mod.placeholder_ledger(paras):
                    ph_rows.append(dict(r, document=name))
            evidence["numbers"] = {"rows": numbers, "count": len(numbers)}
            evidence["terms"] = {"rows": terms, "count": len(terms)}
            evidence["outline"] = {"rows": outline, "count": len(outline)}
            evidence["placeholder_ledger"] = {"rows": ph_rows, "count": len(ph_rows)}
            evidence["claims"] = {"rows": claim_rows, "count": len(claim_rows)}
            # M30's seed: the written values no shipped table PROVES, paired with
            # their candidate producer columns, and the code/config literals that
            # are the producer side of a Methods parameter.
            tables = data_table_texts(sources)
            seed_rows = mod.hierarchy_seed_rows(numbers, tables)
            code_rows = mod.code_literal_rows(sources, skip_name=is_bookkeeping_name)
            # M30's NON-numeric half: a written "not run / no output" claim the
            # shipped tables contradict. Guarded like the rest of the block, so
            # an older companion module degrades to no rows instead of failing.
            neg_fn = getattr(mod, "negative_claim_rows", None)
            neg_rows = neg_fn(all_texts, tables) if neg_fn is not None else []
            evidence["hierarchy"] = {"rows": seed_rows, "count": len(seed_rows),
                                     "tables_read": len(tables)}
            evidence["code_literals"] = {"rows": code_rows, "count": len(code_rows)}
            evidence["negative_claims"] = {"rows": neg_rows, "count": len(neg_rows)}
        except Exception as e:                                        # noqa: BLE001
            evidence["numbers"] = {"error": f"{type(e).__name__}: {e}"}
            for key in ("terms", "outline", "placeholder_ledger", "claims",
                        "hierarchy", "code_literals", "negative_claims"):
                evidence.setdefault(key, {"error": f"{type(e).__name__}: {e}"})
    return evidence


def corpus_text_documents(sources: list, raw_text: bool = False,
                          include_bib: bool = False) -> list:
    """[(document name, [(text, is_reference, is_heading)])] for the corpus.

    DOCX text is read with the full paragraph map (styles drive the reference
    and heading flags); .tex/.md text goes through the same LaTeX stripping the
    style rules use. Stage scratch (`work/`) and bookkeeping are skipped, exactly
    like every other corpus scan.

    `raw_text` hands a TEXT source over as ONE row holding the file's own bytes
    (decoded), and `include_bib` adds `*.bib` to the suffixes read. The M2
    reference seed reads that view and every other scan keeps the stripped one:
    the paragraph reader folds each paragraph onto one line and strips the LaTeX
    scaffolding, which destroys the `\\bibitem{key}` marker a LaTeX bibliography
    is found by -- so a `thebibliography` documented ZERO entries on the
    production path, and a `.bib` file (whose `@type{key,` markers the same
    reader knows) was never read at all.
    """
    mod = _format_module()
    out = []
    # The same later-source-override filter `corpus_manifest` applies by
    # construction (its {path: digest} map) and the DOCX branch of
    # scan_format_in_sources applies explicitly: without it a path provided by
    # two sources was read TWICE -- every paragraph of the collided document
    # fed the placeholder / number-provenance / prose scans under one name, from
    # stale bytes the corpus builder never ships.
    overrides = corpus_source_overrides(sources)
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir() or mod is None:
            continue
        for p in _docx_files_under(src):
            if not p.is_file() or p.name.startswith("~$") or _is_aux_doc(p.name) \
                    or is_bookkeeping_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if (prefix + rel) in overrides[i]:
                continue                      # a later source provides this path
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if is_non_manuscript_rel(rel):
                # Evidence areas and feedback/response documents are never
                # submission prose: placeholder and number-provenance scans read
                # the submission documents only.
                continue
            if "work" in rel.split("/")[:-1]:
                continue
            try:
                with zipfile.ZipFile(p) as z:
                    # errors="replace", like every other reader: a legacy byte
                    # must not throw a UnicodeDecodeError straight past the
                    # unreadable-package guard and abort the whole scan.
                    xml = z.read("word/document.xml").decode("utf-8", "replace")
            except (zipfile.BadZipFile, KeyError, OSError, RuntimeError,
                    NotImplementedError):
                continue
            rows = []
            for _p0, _p1, para in mod.paragraphs(xml):
                style = mod.elem_val(mod.ppr_of(para), "pStyle")
                rows.append((mod.text_of(para), style == "Bibliography",
                             bool(style and style.startswith("Heading"))))
            out.append((prefix + rel, rows))
        suffixes = (".tex", ".ltx", ".md", ".markdown", ".txt") \
            + ((".bib",) if include_bib else ())
        for p in _files_under_ci(src, suffixes):
            if _is_aux_doc(p.name) or is_bookkeeping_name(p.name):
                continue
            if (prefix + p.relative_to(src).as_posix()) in overrides[i]:
                continue                      # a later source provides this path
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if is_non_manuscript_rel(rel):
                continue        # evidence area, not submission prose (see above)
            if "work" in rel.split("/")[:-1]:
                continue
            if raw_text:
                try:
                    raw = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                out.append((prefix + rel, [(raw, False, False)]))
                continue
            paras = text_source_paragraphs(p)
            out.append((prefix + rel, [(t, False, False) for t in paras]))
    return out


def placeholder_lookup_rows(ctx: Ctx, queries: list, timeout: int = 30) -> list:
    """Online lookup for searchable placeholders (opt-in via --placeholder-lookup).

    Every query is run against Europe PMC and OpenAlex by the public module; the
    result is seeded as `work/PLACEHOLDER_LOOKUP.md` (and the review's artifact
    copy) and the agent disposes
    each row (fill with the found DOI, or with "not posted" + this evidence when
    the search is clean).
    """
    mod = _format_module()
    if mod is None:
        return []
    return [mod.lookup_preprint(q, timeout=timeout) for q in queries if str(q).strip()]


def evidence_pack_summary(ev: dict) -> str:
    """One line per artifact family for the setup/report output."""
    cap = (ev.get("captions") or {})
    lng = (ev.get("lengths") or {})
    fmt = (ev.get("format") or {})
    ph = (ev.get("placeholders") or {})
    ident = (ev.get("corpus_identity") or {})
    over_l = len(lng.get("over_limit") or [])
    return (f"M18 {cap.get('count', '?')} legend(s)"
            + (f", {len(cap.get('over_limit') or [])} over the proxy cap" if cap.get("limit") else "")
            + f"; M19 {len(lng.get('rows') or [])} section(s), {over_l} over cap"
            + f"; M20 {len(fmt.get('rows') or [])} row(s) "
              f"({fmt.get('high', 0)} high); placeholders {ph.get('count', '?')}"
            + f"; J3 claim-strength rows "
              f"{(ev.get('claims') or {}).get('count', '?')}"
            + f"; PKG-2 dangling references "
              f"{len((ev.get('submission_references') or {}).get('rows') or [])}"
            + f"; PKG-4 missing display items "
              f"{len((ev.get('display_items') or {}).get('rows') or [])}"
            + f"; PKG-5 producer contradiction(s) "
              f"{len((ev.get('display_provenance') or {}).get('rows') or [])}"
            + f"; PKG-6/7/8/9 self-contradiction(s) "
              f"{len((ev.get('contradictions') or {}).get('rows') or [])}"
            + (f"; submitted set from the package README "
               f"{(ev.get('submission_declaration') or {}).get('submitted_count')}"
               if (ev.get("submission_declaration") or {}).get("declared") else "")
            + (f"; FMT-TP1 title-page gap(s) "
               f"{len((ev.get('front_matter_gaps') or {}).get('rows') or [])}"
               if (ev.get("front_matter_gaps") or {}).get("rows") else "")
            + f"; M30 hierarchy rows "
              f"{(ev.get('hierarchy') or {}).get('count', '?')}"
              f" (+{(ev.get('code_literals') or {}).get('count', '?')} literal(s))"
            + f"; digest {str(ident.get('digest'))[:12]}")


def _evidence_artifact_table(rows: list, columns: list, empty_note: str) -> str:
    out = ["| # | " + " | ".join(columns) + " | disposition |",
           "|---|" + "---|" * (len(columns) + 1)]
    for i, r in enumerate(rows, 1):
        cells = " | ".join(str(r.get(c, "")).replace("|", "\\|")[:140] for c in columns)
        out.append(f"| {i} | {cells} |  |")
    if not rows:
        out.append("| - | " + " | ".join("—" for _ in columns) + f" | {empty_note} |")
    # The reminder sits AFTER the table (and outside it: the block ends at the
    # last `|` line), where a session that rewrites the rows by script will see
    # it. A row that is one cell short is read positionally and its verdict is
    # counted as an UNDISPOSED row -- see disposition_artifact_problems.
    out.append("")
    out.append("_One cell per seeded column, in order: write your verdict IN the last "
               "(`disposition` / `resolution`) cell. A row that is one cell short is read "
               "positionally, so a verdict written after the seeded cells counts as an "
               "undisposed row._")
    return "\n".join(out)


DATA_TABLE_EXTS = (".tsv", ".csv")


def data_table_texts(sources: list, limit: int = 40) -> list:
    """[(rel, text)] for the corpus files that can PROVE a number.

    Machine-readable tables (`.tsv`/`.csv`) and tabular-looking `.tex`/`.txt`
    sources (a pipe table, an `&` table, a tab-separated header) are the only
    files whose values the reconciliation may use: a number that also appears in
    the *prose* proves nothing about where it came from.
    """
    out = []
    # Later sources override earlier ones for the same relative path (the rule
    # corpus_manifest enforces by construction): without the filter a collided
    # document's values were read twice, and a stale copy's numbers could be the
    # ones a reconciliation "proves".
    overrides = corpus_source_overrides(sources or [])
    for i, (src, prefix, excluded) in enumerate(sources or []):
        if not src.is_dir():
            continue
        for p in _iter_tree_files(src):
            if len(out) >= limit:
                return out
            try:
                if is_bookkeeping_name(p.name) or _is_aux_doc(p.name):
                    continue
            except OSError:
                continue
            rel = p.relative_to(src).as_posix()
            if (prefix + rel) in overrides[i]:
                continue                      # a later source provides this path
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if "work" in rel.split("/")[:-1]:
                continue
            ext = p.suffix.lower()
            if ext not in DATA_TABLE_EXTS + (".tex", ".ltx", ".txt", ".md"):
                continue
            try:
                text = p.read_text("utf-8", "replace")
            except OSError:
                continue
            if ext not in DATA_TABLE_EXTS:
                first = next((l for l in text.splitlines() if l.strip()), "")
                if not (first.count("|") >= 2 or first.count("&") >= 2
                        or first.count("\t") >= 1):
                    continue
            out.append((prefix + rel, text))
    return out


def lookup_network_available(timeout: float = None) -> bool:
    """One cached probe per process: can the lookup engine reach a public API?"""
    if "ok" in _LOOKUP_PROBE:
        return bool(_LOOKUP_PROBE["ok"])
    ok = False
    try:
        import urllib.error
        import urllib.request
        rq = urllib.request.Request(
            LOOKUP_PROBE_URL, headers={"User-Agent": "paper-pipeline/3.5 (probe)"})
        try:
            with urllib.request.urlopen(rq, timeout=timeout or LOOKUP_PROBE_TIMEOUT) as r:
                ok = int(getattr(r, "status", 200)) == 200
        except urllib.error.HTTPError:
            # The API ANSWERED (any status): it is reachable, and the engine's
            # own per-query verdicts are what the rows must record.
            ok = True
    except Exception:                                                 # noqa: BLE001
        ok = False
    _LOOKUP_PROBE["ok"] = ok
    return ok


def _lookup_cache(ctx: Ctx) -> dict:
    """{kind|query: result} carried across the sandboxes of one root."""
    path = ctx.root / LOOKUP_CACHE_REL
    data = read_json(path, revive=False, lenient=True)
    return data if isinstance(data, dict) else {}


def _lookup_cache_store(ctx: Ctx, cache: dict) -> None:
    try:
        (ctx.root / "reports").mkdir(parents=True, exist_ok=True)
        write_json_atomic(ctx.root / LOOKUP_CACHE_REL, cache)
    except OSError:
        pass


def _lookup_cache_fresh(entry: dict) -> bool:
    stamp = str((entry or {}).get("checked_at") or "")
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - when).days
    return 0 <= age <= LOOKUP_CACHE_TTL_DAYS


# The order matters twice: each class first takes its reserved share, then the
# REMAINDER of these lists is spent in this same order (see
# _select_lookup_targets), so the reference list gets the leftover budget before
# any other class -- and the other classes keep their own reserves, so a long
# reference list can no longer crowd them out.
LOOKUP_BUDGET_SHARES = {"reference": 16, "identifier": 8, "placeholder": 2, "gene": 10}


def _select_lookup_targets(targets: list, budget: int) -> list:
    """Trim the lookup list to `budget`, with an allocation per source class.

    Every class first takes up to its reserved share; the remaining budget is
    then filled with the REMAINDER of those same lists (reserved classes first,
    then any other source), so the cap is actually spent. Popping each class's
    list before slicing it silently discarded that remainder: a corpus of 30
    identifiers checked 4 of a 24-lookup budget and left everything else
    unexamined.
    """
    if len(targets) <= budget:
        return list(targets)
    by_source = {}
    for t in targets:
        by_source.setdefault(str(t.get("source") or ""), []).append(t)
    picked, used = [], 0
    taken = {}
    for source, share in LOOKUP_BUDGET_SHARES.items():
        take = (by_source.get(source) or [])[:share]
        taken[source] = len(take)
        for t in take:
            picked.append(t)
            used += 1
    rest = list(LOOKUP_BUDGET_SHARES)
    rest += [s for s in sorted(by_source) if s not in LOOKUP_BUDGET_SHARES]
    for source in rest:
        for t in (by_source.get(source) or [])[taken.get(source, 0):]:
            if used >= budget:
                break
            picked.append(t)
            used += 1
    return picked[:budget]


def _lookup_batch(ctx: Ctx, targets: list, label: str) -> list:
    """Run the capped public-API lookups for one stage, never fatally.

    Each target is {"kind", "query", ...}; the result keeps the target's own
    fields and adds the lookup's verdict/hits/errors. With the lookup mode off,
    or without the companion module, every row is returned with
    verdict="skipped" so a session can see that the pipeline did NOT check.
    """
    mod = _format_module()
    mode = placeholder_lookup_of(ctx)
    out = []
    online = mode == "online" and mod is not None
    if online and targets and not lookup_network_available():
        online = False
    cache = _lookup_cache(ctx) if online else {}
    cache_dirty = False
    for t in targets:
        row = dict(t)
        if not online:
            why = ("lookup disabled (`--placeholder-lookup off`)"
                   if mode != "online" or mod is None
                   else "no network (the probe could not reach a public API)")
            row.update({"verdict": "skipped", "hits": [], "errors": [],
                        "checked_at": utcnow()})
            row["why"] = why
            out.append(row)
            continue
        key = f"{str(t.get('kind') or '').strip().lower()}|{str(t.get('query') or '').strip()}"
        cached = cache.get(key)
        # A transient network/API error is not a fact about the identifier;
        # serving it for the 14-day TTL made one failed lookup permanent.
        if isinstance(cached, dict) and _lookup_cache_fresh(cached) \
                and cached.get("verdict") != "error":
            row.update({"verdict": cached.get("verdict") or "error",
                        "hits": cached.get("hits") or [],
                        "errors": cached.get("errors") or [],
                        "checked_at": cached.get("checked_at") or utcnow(),
                        "cached": True})
            out.append(row)
            continue
        try:
            res = mod.lookup_kind(t.get("kind"), t.get("query"), timeout=LOOKUP_TIMEOUT)
        except Exception as e:                                        # noqa: BLE001
            res = {"verdict": "error", "hits": [], "errors": [f"{type(e).__name__}: {e}"]}
        row.update({"verdict": res.get("verdict") or "error",
                    "hits": res.get("hits") or [],
                    "errors": res.get("errors") or [],
                    "checked_at": res.get("checked_at") or utcnow()})
        if row.get("verdict") != "error":
            cache[key] = {k: row.get(k) for k in ("verdict", "hits", "errors", "checked_at")}
        cache_dirty = True
        out.append(row)
    if cache_dirty:
        _lookup_cache_store(ctx, cache)
    if out:
        found = sum(1 for r in out if r["verdict"] == "found")
        absent = sum(1 for r in out if r["verdict"] == "absent")
        errs = sum(1 for r in out if r["verdict"] == "error")
        skipped = sum(1 for r in out if r["verdict"] == "skipped")
        print(f"  [{label}] lookups: {len(out)} target(s) -> {found} found, {absent} absent, "
              f"{errs} error, {skipped} skipped")
    return out


def seed_provenance_pack(ctx: Ctx, sb: Path, sources: list, ev: dict,
                         work: Path, art: Path = None, where: str = "") -> dict:
    """Numbers-with-provenance, identifier verification, glossary, placeholder lookups.

    Everything here is CODE-SIDE and reproducible: a session disposes rows, it
    never re-derives them. The one part that touches the network (the lookup
    engine) is capped, reports its verdicts (`found` / `absent` / `error` /
    `skipped`) together with the endpoint's own title/date, and degrades to
    `skipped` under `--placeholder-lookup off`.
    """
    mod = _format_module()
    if mod is None:
        return {"unavailable": f"{DOCX_FORMAT_MODULE} not found"}
    work.mkdir(parents=True, exist_ok=True)
    if art is not None:
        # The review layout's artifacts/ directory is created HERE because the
        # provenance pack is seeded before the M18/M19/M20 skeleton block; a
        # missing directory made the artifact copies silently not happen (the
        # work/ copies and PROVENANCE.json are written by the same loop).
        art.mkdir(parents=True, exist_ok=True)
    docs = corpus_text_documents(sources)
    tables = data_table_texts(sources)
    num_rows = [dict(r) for r in ((ev.get("numbers") or {}).get("rows") or [])]
    reconcile = mod.reconcile_number_rows(num_rows, tables)
    ident_rows = mod.identifier_rows(docs)
    gene_rows = mod.gene_symbol_rows(docs)
    # The reference seed reads the sources' OWN text (`raw_text=True`,
    # `include_bib=True`): the stripped paragraph view above has already folded
    # every paragraph onto one line and removed the LaTeX scaffolding, so a
    # `\bibitem{key}` marker -- the one thing a LaTeX reference list is read by
    # -- could never reach `reference_entries()`, and a `.bib` file was not read
    # at all. Both shapes carry the DOIs this seed exists to check, and the
    # DOCX branch is unchanged (its style flags are what the flagged paragraphs
    # need), so no other scan sees the raw text.
    ref_rows = mod.reference_integrity_rows(
        corpus_text_documents(sources, raw_text=True, include_bib=True))
    ph_rows = ((ev.get("placeholder_ledger") or {}).get("rows") or [])
    plan = mod.placeholder_lookup_plan(ph_rows, docs)
    # The reference list's own DOIs are resolved FIRST (see _select_lookup_targets):
    # a bibliography DOI is the entry's claim about WHERE the cited work lives, so
    # an unanswered, absent or mismatching verdict is a correctness row, not a
    # style one -- and it is the only way a one-character corruption of an
    # identifier is ever seen (every format check passes on such an entry).
    targets = [{"source": "reference", "kind": r["kind"], "query": r["identifier"],
                "document": r["document"], "value": r["identifier"],
                "entry": r.get("entry") or "", "year": r.get("year") or ""}
               for r in ref_rows if r.get("identifier")]
    targets += [{"source": "identifier", "kind": r["kind"], "query": r["value"],
                "document": r["document"], "value": r["value"]} for r in ident_rows]
    targets += [{"source": "gene", "kind": "gene", "query": r["symbol"],
                 "document": r["document"], "value": r["symbol"]} for r in gene_rows]
    targets += [{"source": "placeholder", "kind": r["kind"], "query": r["query"],
                 "document": r["document"], "paragraph": r.get("paragraph"),
                 "payload": r.get("payload")} for r in plan]
    # Budget the lookups by class: availability identifiers first (they carry
    # correctness claims), then the markers the operator asked about, then the
    # gene symbols (nomenclature). Without the split, a corpus with many DOIs
    # consumed the whole budget and the gene check silently never ran.
    lookups = _lookup_batch(ctx, _select_lookup_targets(targets, LOOKUP_MAX_TARGETS),
                            f"{where or sb.name} provenance")
    by_value = {}
    for row in lookups:
        if row.get("source") == "identifier":
            by_value[(row.get("kind"), row.get("value"))] = row
    ref_hits = {(row.get("kind"), row.get("value")): row for row in lookups
                if row.get("source") == "reference"}
    for r in ref_rows:
        hit = ref_hits.get((r["kind"], r["identifier"]))
        r["verdict"] = (hit or {}).get("verdict") or "not selected"
        r["resolved"] = ""
        r["signal_extra"] = ""
        if hit and (hit.get("hits") or []):
            h = hit["hits"][0]
            r["resolved"] = " ".join(
                f"{h.get('date') or ''} {str(h.get('title') or '')[:80]}".split())
            if hit.get("verdict") == "found":
                r["signal_extra"] = mod.reference_entry_hit_signal(r.get("text") or "", h)
        elif hit and hit.get("errors"):
            r["resolved"] = " ".join("; ".join(hit["errors"])[:100].split())
    for r in ident_rows:
        hit = by_value.get((r["kind"], r["value"]))
        if hit:
            hits_txt = "; ".join(
                f"{h.get('source')}:{str(h.get('title'))[:60]}"
                f"{' | ' + str(h.get('date')) if h.get('date') else ''}"
                for h in (hit.get("hits") or [])[:2])
            r["verification"] = f"{hit['verdict']}: " + (
                hits_txt or ("; ".join(hit.get("errors") or [])[:120] or "no hit"))
            r["verdict"] = hit["verdict"]
    gene_hits = {(row.get("kind"), row.get("value")): row for row in lookups
                 if row.get("source") == "gene"}
    for r in gene_rows:
        hit = gene_hits.get(("gene", r["symbol"]))
        if hit:
            titles = "; ".join(f"{h.get('hncg_id') or h.get('hgnc_id')}:{str(h.get('title'))[:50]}"
                               for h in (hit.get("hits") or [])[:1])
            r["verification"] = f"{hit['verdict']}: " + (
                titles or ("; ".join(hit.get("errors") or [])[:100] or "no hit"))
            r["verdict"] = hit["verdict"]
    glossary_rows, concept_rows = [], []
    for name, rows in docs:
        paras = [r[0] for r in rows]
        is_ref = [r[1] for r in rows]
        for r in mod.concept_family_rows(paras, is_ref):
            concept_rows.append(dict(r, document=name))
        for r in mod.glossary_seed_rows(paras, is_ref):
            glossary_rows.append(dict(r, document=name))
    result = {"reconcile": reconcile, "identifiers": len(ident_rows),
              "references": len(ref_rows),
              "genes": len(gene_rows), "lookups": lookups, "concepts": len(concept_rows),
              "glossary": len(glossary_rows)}

    def write_both(stem: str, header: str, columns: list, rows: list, empty: str) -> None:
        text = ("# " + header + "\n\n" + _evidence_artifact_table(rows, columns, empty) + "\n")
        _seed_write(work / stem, text)
        if art is not None:
            _seed_write(art / stem, text)

    write_both(
        "NUMBERS_LEDGER.md",
        "NUMBERS_LEDGER — every number, with the source the CODE could prove\n\n"
        "`source` is filled by the orchestrator when a shipped data table PROVES the value "
        "(a column sum/min/max or a single cell). A row whose source is still empty is the "
        "session's job: find the analysis output, the cited value or the Methods parameter "
        "behind the number, or record why it cannot be sourced. A number in the abstract, a "
        "legend or the cover letter may not stay unsourced: it is proved, cited, a declared "
        "parameter, or removed as decoration -- never silently, and never by changing a "
        "scientific claim.",
        ["document", "paragraph", "number", "unit", "sentence", "source", "source_kind",
         "status"],
        [{"document": r.get("document"), "paragraph": r.get("document_paragraph"),
          "number": r.get("number"), "unit": r.get("unit") or "",
          "sentence": (r.get("sentence") or "")[:90], "source": r.get("source") or "",
          "source_kind": r.get("source_kind") or "", "status": r.get("status") or ""}
         for r in num_rows],
        "no numeric literal found")
    write_both(
        "IDENTIFIERS.md",
        "IDENTIFIERS — every DOI/accession/repository/ORCID, verified by the orchestrator\n\n"
        "The verification column is the pipeline's own public-API lookup (`found` / `absent` / "
        "`error` / `skipped`). `absent` is evidence too: it is what makes \"not posted\" or "
        "\"not yet deposited\" a VERIFIED statement instead of a guess -- a DOI is `absent` "
        "only after Crossref, DataCite AND the handle registry each failed to find it, so a "
        "deposit registered with another agency (mEDRA, CNKI, JaLC, KISTI) is never called "
        "unregistered. A locator that does not "
        "resolve, or a claim the locator cannot support (a \"permanent archive\" carried by a "
        "version-pinned repository URL), is a finding. Limit: a DOCX bibliography that lives in "
        "a Zotero field is not text-readable here, so its entries are resolved through M2 / the "
        "`zot` CLI, not by this table.",
        ["document", "kind", "value", "verification", "context"],
        [{"document": r.get("document"), "kind": r.get("kind"), "value": r.get("value"),
          "verification": r.get("verification") or "not checked",
          "context": (r.get("context") or "")[:110]} for r in ident_rows],
        "no external identifier found")
    # M2's reference-INTEGRITY seed: one row per reference ENTRY that carries a
    # DOI, with the orchestrator's own verdict for that DOI and what the code
    # could establish without the network. The M2 sweep pairs call-outs with
    # entries and M10 judges an entry's format; neither can see that an entry's
    # DOI belongs to a DIFFERENT work (a one-character corruption leaves author,
    # title, journal and year intact, so every format check passes). This table
    # is the only place that fact is enumerated, so it is disposed row by row
    # and gated like the other decision tables.
    write_both(
        "M2_references.md",
        "M2 — reference-integrity seed (one row per reference entry carrying a DOI)\n\n"
        "`resolver` is the orchestrator's own public-API verdict for this entry's DOI "
        "(`found` / `absent` = no registration agency returned a record AND the DOI handle "
        "itself is not registered (Crossref, DataCite and the handle registry were all asked) "
        "/ `error` / `skipped` / `not selected` = the lookup budget did not reach it); "
        "`resolved work` is what the endpoint returned (its own year and title); "
        "`code signal` is what the code established by itself -- the entry's own year against "
        "a year token INSIDE the DOI, the same DOI on two entries, a stated DOI the syntax "
        "rejects -- plus the comparison between the returned record and the entry. Dispose "
        "EVERY row against the entry's own text:\n"
        "  * `found` and the record agrees with the entry -> `OK — resolves: <year> <title>`;\n"
        "  * `found` and the record is a DIFFERENT work (the code signal says so, or the "
        "title/author/journal you read does) -> a finding: the entry's DOI belongs to another "
        "work, which makes the cited source unresolvable for the reader;\n"
        "  * `absent` -> a finding: the entry states a DOI that is not registered (evidence: "
        "the verdict; every registry was asked, so this is a VERIFIED negative);\n"
        "  * `error` / `skipped` / `not selected` -> `unable — the lookup did not answer "
        "(<why>)`; re-derive it in your own sandbox (the `zot` route, or the endpoint itself) "
        "before filing, and never mark such a row clean;\n"
        "  * a `code signal` row -> dispose it with evidence (`OK — the year token is the "
        "volume/series number`, `OK — both entries are the same work`) or file it (a DOI whose "
        "own year contradicts the entry's is a corruption candidate; one DOI on two entries is "
        "one of the two entries' mistake).\n"
        "An entry that carries NO DOI has no row here -- M2's own artifact covers call-out "
        "pairing and M10 the entry's format, and an entry without an identifier is not a "
        "defect. A bibliography that only exists inside a Word/Zotero field is not readable "
        "here: resolve those through M2 / the `zot` CLI.",
        ["document", "entry", "year", "identifier", "code signal", "resolver", "resolved work"],
        [{"document": r.get("document"), "entry": r.get("entry") or "—",
          "year": r.get("year") or "", "identifier": r.get("identifier") or "(no DOI read)",
          "code signal": "; ".join(x for x in (r.get("signal") or "",
                                               r.get("signal_extra") or "") if x),
          "resolver": r.get("verdict") or "not selected",
          "resolved work": r.get("resolved") or ""} for r in ref_rows],
        "no reference entry carrying a DOI found")
    write_both(
        "GENE_LEDGER.md",
        "GENE_LEDGER — gene/protein symbols the orchestrator RESOLVED against HGNC\n\n"
        f"Candidates extracted from the prose: {len(gene_rows)}; resolved as approved HGNC "
        f"symbols: {sum(1 for r in gene_rows if r.get('verdict') == 'found')}. Only the "
        "resolved ones are listed (a candidate the HGNC does not know is normally a tool "
        "name, a cell line or an accession, and listing those was 70 rows of noise on a real "
        "corpus); a MISSPELLED symbol is still caught by the review's acronym/nomenclature "
        "sweeps. Typography is the second half of the rule: a human gene symbol is italic in "
        "running text, the protein is roman.",
        ["document", "symbol", "verification", "context"],
        [{"document": r.get("document"), "symbol": r.get("symbol"),
          "verification": r.get("verification") or "not checked",
          "context": (r.get("context") or "")[:110]}
         for r in gene_rows if r.get("verdict") == "found"],
        "no HGNC-resolved gene symbol found (or the lookup did not run: "
        "`setup --placeholder-lookup online` resolves them)")
    write_both(
        "PLACEHOLDER_LOOKUP.md",
        "PLACEHOLDER_LOOKUP — what the orchestrator could answer for the hand-off markers\n\n"
        "One row per lookup the pipeline ran for a `searchable` marker. `found` -> write the "
        "fact (with its identifier) into the document; `absent` -> write the verified negative "
        "(\"not posted\" / \"not yet deposited\") with the search date; an author-only fact "
        "stays for the author. Never leave a marker this table answers.",
        ["source", "kind", "query", "verdict", "hits", "errors"],
        [{"source": r.get("source"), "kind": r.get("kind"), "query": r.get("query"),
          "verdict": r.get("verdict"),
          "hits": "; ".join(f"{h.get('source')}:{str(h.get('title'))[:50]}"
                            f"{' | ' + str(h.get('date')) if h.get('date') else ''}"
                            for h in (r.get("hits") or [])[:3]),
          "errors": "; ".join(r.get("errors") or [])[:100]} for r in lookups],
        "no lookup target found")
    write_both(
        "M24_concepts.md",
        "M24 — concept families (one concept, two competing term families)\n\n"
        "Each row proves the corpus uses BOTH families for one concept. Decide the "
        "authoritative term in GLOSSARY.md and fix every occurrence: this is a consistency "
        "defect, not a style preference. The metric names decide the sense -- `intCN_*` is a "
        "copy-number STATE, breakpoint/gain-loss scoring is an EVENT.",
        ["document", "rule", "severity", "evidence", "detail"],
        [{"document": r.get("document"), "rule": r.get("rule"), "severity": r.get("severity"),
          "evidence": r.get("evidence"), "detail": (r.get("detail") or "")[:140]}
         for r in concept_rows],
        "no competing term family found")
    write_both(
        "GLOSSARY.md",
        "GLOSSARY — the term/concept decisions the submission must be consistent with\n\n"
        "The code seeds the CONCEPTS it can prove are in play (with counts per surface form). "
        "Fill `definition`, `authoritative term` and `forbidden synonyms`, then check every "
        "later occurrence against the glossary. A concept with no decision is an open row, "
        "not a pass.",
        ["document", "concept", "family A forms", "A count", "family B forms", "B count",
         "definition", "authoritative term", "forbidden synonyms"],
        [{"document": r.get("document"), "concept": r.get("concept"),
          "family A forms": r.get("family A forms"), "A count": r.get("A count"),
          "family B forms": r.get("family B forms"), "B count": r.get("B count"),
          "definition": "", "authoritative term": "", "forbidden synonyms": ""}
         for r in glossary_rows],
        "no concept to decide")
    # Plain write (no fsync): the provenance pack is a SEEDED INPUT -- a crash
    # just re-materializes the sandbox -- and the atomic writer's fsync costs
    # ~80 ms per file on a drvfs root, which the round's dependency timing is
    # sensitive to (a revise must start the moment the review finishes).
    try:
        (work / "PROVENANCE.json").write_text(
            json.dumps(_json_safe({"numbers": num_rows, "identifiers": ident_rows,
                       "references": ref_rows,
                       "lookups": lookups, "glossary": glossary_rows,
                       "genes": gene_rows,
                                   "concepts": concept_rows}),
                       indent=2, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass
    return result


def seed_format_policy_file(ctx: Ctx, sb: Path) -> Path:
    """Write the venue's formatting policy (its DISPLAY rules) into a session.

    The scanner the sessions run themselves (`python paper_docx_format.py scan
    <dir> --policy format_policy.json`) cannot know a venue's table/figure rule:
    it is profile DATA, so it travels with the sandbox. The file sits at the
    sandbox ROOT (never inside `review/`, which `leftovers_present` reads as
    agent work), carries only venue-level data (the `tables`/`figures` blocks,
    the template's `empty_paragraph_slots`, the image-aspect tolerance), and is
    identical for every session of a root -- it is venue-level, not derived
    from any package, so handing it to a judge blinds nothing.
    """
    p = sb / "format_policy.json"
    policy = format_policy_of(ctx)
    # The venue template's own blank-paragraph slots travel too: the session's
    # own scan must exempt exactly the blanks the journal's template prescribes
    # (the spacer above the title, a placeholder slot between two headings),
    # never flag them as stray.
    body = {"tables": copy.deepcopy(policy.get("tables") or {}),
            "figures": copy.deepcopy(policy.get("figures") or {}),
            "empty_paragraph_slots": copy.deepcopy(policy.get("empty_paragraph_slots") or []),
            # The cover-letter rule's data travels too: the scan the session runs
            # itself must be able to prove a letter was formatted in the
            # manuscript template (FMT-CL1), exactly like the postcheck does.
            "cover_letter": copy.deepcopy(policy.get("cover_letter") or {}),
            # Reference-entry preference (FMT-R5), display-item numbering
            # (FMT-O1) and the other publisher's leftover phrases (FMT-L1) are
            # venue-level DATA as well: without them the session's own scan
            # reports fewer rows than the postcheck does.
            "numbering": policy.get("numbering") or "",
            "references": copy.deepcopy(policy.get("references") or {}),
            "leftover_phrases": copy.deepcopy(policy.get("leftover_phrases") or []),
            "image_aspect_tolerance": policy.get("image_aspect_tolerance", 0.02),
            # Venue image rules (FMT-IM4/FMT-IM6): the session's own scan must
            # gate the same DPI/figure-text rules the postcheck does.
            "figure_text": copy.deepcopy(policy.get("figure_text") or {}),
            "image_dpi": copy.deepcopy(policy.get("image_dpi") or {}),
            "min_image_dpi": policy.get("min_image_dpi", 0),
            "min_figure_text_pt": policy.get("min_figure_text_pt", 0)}
    # tmp + rename, NOT write_json_atomic's extra fsync: this file is a pure
    # INPUT every session reads, and the pipeline seeds one per session
    # materialization. On this box each fsync costs ~0.08 s (measured: the
    # fsynced version added 24 fsyncs and ~4 s to one round of the scheduling
    # suite -- the same latency the seeded evidence tables avoid, see
    # `_seed_write`). The atomic rename still guarantees a reader never sees a
    # truncated file, and the content is reproducible from the profile.
    tmp = tmp_path_for(p)
    try:
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    return p


def seed_evidence_pack(ctx: Ctx, sb: Path, corpus_dir: Path, where: str) -> dict:
    """Write the code-side evidence pack into one session sandbox.

    `where` selects the layout:
      * "review"  -> review/work/ + review/artifacts/ (M18/M19/M20 skeletons)
      * "judge"   -> judge_review/work/ + judge_review/artifacts/ (same skeletons,
                     scanned from the judge's own target/ view)
      * "stage"   -> work/ at the sandbox root (rewrite/revise/integrate see the
                     numbers of the package they are about to edit)
    The returned dict is also written as work/CODE_SCANS.json; EVIDENCE_PACK.md
    is the human-readable form. Keys: captions, lengths, format, placeholders,
    corpus_identity.
    """
    if where == "review":
        work, art = sb / REVIEW_DIR / "work", sb / REVIEW_DIR / "artifacts"
    elif where == "judge":
        work, art = sb / "judge_review" / "work", sb / "judge_review" / "artifacts"
    else:
        work, art = sb / "work", None
    work.mkdir(parents=True, exist_ok=True)
    ev = code_side_evidence(ctx, corpus_dir, f"{sb.name}:{where}")
    write_json_atomic(work / "FORMAT_SCAN.json", ev.get("format") or {})
    seed_format_policy_file(ctx, sb)
    # Provenance / identifier / concept packs: the numbers ledger (with the
    # sources the CODE could prove), the verified identifiers, the glossary
    # scaffold and the placeholder lookups. Seeded for every non-judge session;
    # the judge gets nothing (blinding) -- it re-derives its own rows.
    prov = {}
    if where in ("review", "audit", "stage"):
        try:
            prov = seed_provenance_pack(
                ctx, sb, [(corpus_dir, "", CORPUS_EXCLUDE_TOP)], ev, work,
                art=(sb / REVIEW_DIR / "artifacts") if where == "review" else None,
                where=where)
            ev["provenance"] = {"numbers_proved":
                                (prov.get("reconcile") or {}).get("filled"),
                                "identifiers": prov.get("identifiers"),
                                "references": prov.get("references"),
                                "concepts": prov.get("concepts"),
                                "lookups": [{k: r.get(k) for k in
                                             ("source", "kind", "query", "verdict")}
                                            for r in (prov.get("lookups") or [])]}
        except Exception as e:                                        # noqa: BLE001
            prov = {}
            ev["provenance"] = {"error": f"{type(e).__name__}: {e}"}
        # Official-template conformance: a code-side measurement of the row the
        # venue's OWN template demands (mandatory sections, class file,
        # statement blocks). Evidence only, never a gate; the review disposes it
        # under J5/M20 and the producing arms apply it.
        try:
            req = official_template_requirements(venue_id_of(ctx), ctx.root)
            if req:
                _w = venue_word_templates(ctx) or {}
                word_tpl = _w.get("main")
                conf = scan_template_conformance([(corpus_dir, "", CORPUS_EXCLUDE_TOP)], req,
                                                 word_template=word_tpl,
                                                 word_template_supplementary=_w.get("supplementary"),
                                                 word_template_cover=_w.get("cover"),
                                                 containers=venue_containers(ctx),
                                                 manuscript_names=article_type_manuscript_names(ctx))
                ev["official_template"] = conf
                write_json_atomic(work / "OFFICIAL_TEMPLATE.json", conf)
                rows = ([{"row": f"mandatory section missing: {s}"} for s in
                         conf["missing_sections"]]
                        + [{"row": f"statement block missing: {s}"} for s in
                           conf["missing_statements"]]
                        + ([] if conf["class_ok"] else
                           [{"row": f"documentclass {conf['found']['documentclass']!r} != "
                                    f"required {conf['required']['documentclass']!r}"}])
                        + [{"row": r} for r in conf.get("order_rows") or []]
                        + [{"row": r} for r in conf.get("label_rows") or []]
                        + [{"row": r} for r in conf.get("front_matter_rows") or []]
                        + [{"row": f"{m['missing_count']} template style(s) missing from "
                                   f"{m['document']}: {', '.join(m['missing'][:6])}"}
                           for m in conf.get("word_styles_missing") or []])
                md = ["# OFFICIAL TEMPLATE — code-side conformance (advisory evidence)", "",
                      f"Required by the venue's own template pack: class "
                      f"`{conf['required']['documentclass'] or '(unspecified)'}`; mandatory "
                      f"sections: {', '.join(conf['required']['mandatory_sections']) or '(none)'}.",
                      "",
                      ("The corpus CONFORMS to every code-checkable requirement."
                       if conf["conforms"] else
                       "Consistency check: the review disposes every row below under J5/M20 and "
                       "the producing arms apply the fixes (a requirement the manuscript cannot "
                       "supply becomes a manual item, never invented text)."),
                      ""]
                md += [f"- {r['row']}" for r in rows] or ["- (no rows)"]
                write_text_atomic(work / "OFFICIAL_TEMPLATE.md", "\n".join(md) + "\n")
        except Exception as e:                                        # noqa: BLE001
            ev["official_template"] = {"error": f"{type(e).__name__}: {e}"}
    # ONE atomic write per seeded scan (provenance included): a second one cost
    # another fsync on the critical path with no benefit.
    write_json_atomic(work / "CODE_SCANS.json", ev)
    lines = [f"# Code-side evidence pack ({where}: {sb.name})",
             "",
             f"Corpus: `{corpus_dir}`  |  {utcnow()}",
             "",
             "- " + evidence_pack_summary(ev),
             "",
             ("- provenance pack: "
              f"{(prov.get('reconcile') or {}).get('filled', 0)} number(s) proved from shipped "
              f"data tables; {prov.get('identifiers', 0)} identifier(s) resolved; "
              f"{len(prov.get('lookups') or [])} lookup(s); "
              f"{prov.get('concepts', 0)} concept-family row(s); "
              f"`work/NUMBERS_LEDGER.md`, `work/IDENTIFIERS.md`, "
              f"`work/PLACEHOLDER_LOOKUP.md`, `work/M24_concepts.md`, `work/GLOSSARY.md`"
              if prov else "- provenance pack: unavailable"),
             "",
             "These are the ORCHESTRATOR's measurements of this corpus (the same functions "
             "used at setup and at `decide`). Every session sees the same pack, so a review "
             "row, the revised/integrated/rewritten package and the judge panel cannot "
             "disagree about a number without saying why. Re-derive with:",
             "",
             f"    python {DOCX_FORMAT_MODULE} scan {corpus_dir}",
             "",
             ]
    if art is not None:
        art.mkdir(parents=True, exist_ok=True)
        cap = ev.get("captions") or {}
        cap_rows = [{"document": c.get("document"), "caption": c.get("caption"),
                     "words": c.get("words"), "over_limit": c.get("over_limit"),
                     "excerpt": c.get("excerpt")} for c in (cap.get("captions") or [])]
        _seed_write(art / "M18_caption_words.md", "# M18 — figure-legend word counts (code-side enumeration)\n\n"
            f"Proxy cap: {cap.get('limit') or 'none configured'}. Dispose every row "
            "(finding id / OK — reason / unable — reason).\n\n"
            + _evidence_artifact_table(cap_rows,
                                       ["document", "caption", "words", "over_limit", "excerpt"],
                                       "no caption found by the code-side scan")
            + "\n")
        lng = ev.get("lengths") or {}
        len_rows = [{"document": r.get("document"), "section": r.get("section"),
                     "words": r.get("words"), "cap": r.get("cap"),
                     "note": r.get("note")} for r in (lng.get("rows") or [])]
        _seed_write(art / "M19_length.md", "# M19 — abstract/main-text length (code-side enumeration)\n\n"
            f"Caps: {json.dumps((lng.get('limits') or {}).get('abstract', {}))} / "
            f"{json.dumps((lng.get('limits') or {}).get('main text', {}))}. "
            f"Counting rule: {main_text_counting_text(venue_profile_of(ctx, required=False))}. "
            "Dispose every row.\n\n"
            + _evidence_artifact_table(len_rows,
                                       ["document", "section", "words", "cap", "note"],
                                       "no manuscript-shaped document found")
            + "\n")
        # M4 numbers: the "verify the source of each number" ledger. The agent
        # fills `source` (data file / table / figure / formula) or removes the
        # claim; an empty source cell is an unfinished row.
        num = ev.get("numbers") or {}
        num_rows = [{"document": r.get("document"), "paragraph": r.get("document_paragraph"),
                     "number": r.get("number"), "unit": r.get("unit") or "",
                     "thousands": "yes" if r.get("thousands_separated") else "",
                     "sentence": (r.get("sentence") or "")[:90], "source": ""}
                    for r in (num.get("rows") or [])]
        _seed_write(art / "M4_numbers.md", "# M4 — number ledger (code-side enumeration; one row per numeric literal)\n\n"
            "Fill `source` for every row (the data file, table, figure or formula the number "
            "comes from), or remove the claim from the text. A number with no verifiable source "
            "must not stay.\n\n"
            + _evidence_artifact_table(num_rows,
                                       ["document", "paragraph", "number", "unit", "thousands",
                                        "sentence", "source"],
                                       "no numeric literal found")
            + "\n")
        # M8 terms: occurrence ledger + the confusable pairs the style rules found.
        ter = ev.get("terms") or {}
        term_rows = [{"document": r.get("document"), "term": r.get("term"),
                      "count": r.get("count"), "first paragraph": r.get("first_paragraph"),
                      "first context": (r.get("first_context") or "")[:80],
                      "decision": ""} for r in (ter.get("rows") or [])]
        _seed_write(art / "M8_terms.md", "# M8 — key-term occurrence ledger (code-side enumeration)\n\n"
            "For every term: confirm it is used with ONE precise meaning, note the chosen "
            "term in `decision` (and the definition site if the manuscript needs one). Rows "
            "for confusable pairs (emulate/simulate, accuracy/precision, ...) are the "
            "FMT-T9d rows in the format scan.\n\n"
            + _evidence_artifact_table(term_rows,
                                       ["document", "term", "count", "first paragraph",
                                        "first context", "decision"],
                                       "no key term found")
            + "\n")
        # Hierarchy scaffold for the summary/coherence pass (suggestion: summarize
        # each level, then check sibling/parent/child coherence).
        outl = ev.get("outline") or {}
        outline_rows = [{"document": r.get("document"), "heading": r.get("heading"),
                         "paragraph": r.get("paragraph"), "words": r.get("words"),
                         "lists": r.get("list_markers") or "", "refs": r.get("refs") or "",
                         "first sentence": (r.get("first_sentence") or "")[:70],
                         "summary": ""} for r in (outl.get("rows") or [])]
        _seed_write(art / "OUTLINE.md", "# OUTLINE — hierarchy scaffold for the summary/coherence pass\n\n"
            "Write a GENERATED one-line summary in `summary` for every row: what the paragraph "
            "CLAIMS (its own words, not the first sentence copied back — a row whose summary is "
            "a prefix of `first sentence` counts as unfilled). Then check each summary against "
            "its siblings (no two rows may carry the same summary), its parent heading (does "
            "the paragraph belong to that heading's topic?) and its children, and check that "
            "the paragraph makes one point. Report incoherence as a finding (J3/category 2), "
            "never by rewriting silently.\n\n"
            "The `disposition` column takes a rule-specific verdict "
            "(`OK — one topic: …` / `incoherent — <finding id>` / "
            "`child-mismatch — <finding id>`). One identical sentence across most rows is "
            "treated by the postcheck as an unfilled artifact, and "
            "`decide --residual-gate` refuses to certify the run on it.\n\n"
            + _evidence_artifact_table(outline_rows,
                                       ["document", "heading", "paragraph", "words", "lists",
                                        "refs", "first sentence", "summary"],
                                       "no paragraph found")
            + "\n")
        # Hand-off placeholders, classified searchable vs author-only.
        phl = ev.get("placeholder_ledger") or {}
        ph_rows = [{"document": r.get("document"), "paragraph": r.get("document_paragraph"),
                    "class": r.get("class"), "payload": (r.get("payload") or "")[:100],
                    "resolution": ""} for r in (phl.get("rows") or [])]
        _seed_write(art / "PLACEHOLDERS.md", "# PLACEHOLDERS — hand-off markers, classified\n\n"
            "`searchable` rows ask for a findable fact (preprint, DOI, accession, database ID, "
            "version): search for it (or use work/PLACEHOLDER_LOOKUP.md when the "
            "operator enabled the lookup) and fill the placeholder with the answer, or with "
            "the negative plus the search evidence; an `author-only` row stays for the author. "
            "Record what you did in `resolution`.\n\n"
            + _evidence_artifact_table(ph_rows,
                                       ["document", "paragraph", "class", "payload",
                                        "resolution"],
                                       "no hand-off placeholder found")
            + "\n")
    # J3's claim-strength ledger: BOTH directions of the calibration check.
    # The code enumerates the sentences that hedge below their evidence
    # (`under`) and the sentences that claim beyond it (`over`); the
    # disposition decides, per row, whether the sentence's strength matches
    # what the corpus shows. An overclaim has always been a finding; an
    # underclaim (a supported result reported as "may"/"a trend"/
    # "preliminary") is the same defect in the other direction and is the side
    # an instance-level review used to leave unexamined. Seeded for every
    # layout (work/) and, like the other decision tables, copied under the
    # review's artifacts/ directory so the disposition layer reads it.
    cl = ev.get("claims") or {}
    claim_rows = [{"document": r.get("document"), "paragraph": r.get("paragraph"),
                   "kind": r.get("kind"), "direction": r.get("direction"),
                   "markers": r.get("markers"), "n": r.get("n markers"),
                   "sentence": (r.get("sentence") or "")[:110]}
                  for r in (cl.get("rows") or [])]
    claim_text = (
        "# CLAIM_STRENGTH — claim strength vs evidence, BOTH directions (check id J3)\n\n"
        "One row per paragraph per direction: `under` = a hedge the evidence may not "
        "require (a potential UNDERCLAIM); `over` = a maximal claim the evidence may not "
        "support (a potential OVERCLAIM). Dispose EVERY row against the evidence the "
        "corpus shows: `OK — the hedge matches the evidence (reason)` / "
        "`OK — the claim is supported by <data/table/figure>` / "
        "`underclaim — <finding id>` / `overclaim — <finding id>`. A marker whose strength "
        "MATCHES the evidence is a legitimate row; the ledger never licenses deleting a "
        "hedge that carries the claim's own strength. A session that reports one direction "
        "and leaves the other rows undisposed has not run the check.\n\n"
        + _evidence_artifact_table(
            claim_rows,
            ["document", "paragraph", "kind", "direction", "markers", "n", "sentence"],
            "no claim-bearing paragraph with a hedge or a maximal claim was found")
        + "\n")
    _seed_write(work / "CLAIM_STRENGTH.md", claim_text)
    if art is not None:
        _seed_write(art / "CLAIM_STRENGTH.md", claim_text)
    # M30 -- the source-hierarchy reconciliation ledger. The hierarchy is the
    # RESOLUTION rule; this table is its DETECTION side: every written value the
    # shipped tables do not already PROVE, paired with the candidate producer
    # column(s) and the mechanical check the code can make, plus the code/config
    # literals that are the producer side of a Methods parameter. The session
    # disposes every row and ADDS the producers the code cannot see (a figure's
    # generating code, a protocol step's implementation, a sample set against
    # the data's own rows); a producer that is not in the corpus is a recorded
    # `unable`, never a silent clean.
    hrows = (ev.get("hierarchy") or {}).get("rows") or []
    crows = (ev.get("code_literals") or {}).get("rows") or []
    nrows = (ev.get("negative_claims") or {}).get("rows") or []
    h_rows = [{"document": r.get("document"), "kind": r.get("kind"),
               "number": r.get("number"), "unit": r.get("unit") or "",
               "sentence": (r.get("sentence") or "")[:110],
               "candidate producer": r.get("candidate producer"),
               "producer summary": r.get("producer summary"),
               "seed check": r.get("seed check")} for r in hrows]
    c_rows = [{"file": r.get("file"), "line": r.get("line"), "symbol": r.get("symbol"),
               "value": r.get("value"), "context": (r.get("context") or "")[:90]}
              for r in crows]
    n_rows = [{"written claim": (r.get("claim") or "")[:110],
               "method token": r.get("token"),
               "shipped table says": r.get("producer"),
               "detail": (r.get("detail") or "")[:120]}
              for r in nrows]
    m30_text = (
        "# M30 — source-hierarchy reconciliation (code-side seed)\n\n"
        "The hierarchy `" + SOURCE_HIERARCHY + "` is the RESOLUTION rule; this table is its "
        "DETECTION side. Table A pairs every written number the shipped data tables do NOT prove "
        "with the candidate producer column(s) and the check the code could make (a table's own "
        "row count against a cohort-size sentence; a written value against a column's values and "
        "statistics). Table B lists the module-level literals the corpus's code/config files "
        "declare — the producer side of a Methods parameter. Dispose EVERY seeded row "
        "(`OK — <the reconciling reason>` / `contradiction — <finding id>` / "
        "`unable — the producer is not in the corpus`), then ADD the rows the code cannot see: "
        "figure/panel ↔ the code or raw data that generates it, protocol step ↔ the code that "
        "implements it, sample/cohort set ↔ the data's rows, a Methods parameter ↔ the code's "
        "constant. One finding per incompatible instance, naming BOTH sides and the authoritative "
        "one per the hierarchy. A producer that is not in the corpus (an external repository, an "
        "image-only figure, a binary the text tools cannot read) is a recorded `unable` row, never "
        "a silent clean; a difference a stated unit, rounding, conversion or Methods-stated "
        "run-time override reconciles is `OK` with that reason. Never \"fix\" the code here: the "
        "review reports; rule C owns a code fix and a regenerated figure/table is a manual item.\n\n"
        "A COUNT of the form \"N scenario-by-metric blocks\" is a written number with a shipped "
        "producer: count the DISTINCT (scenario, metric) pairs in the deposited grid table the "
        "figure is drawn from, and check the metric IDs the Results names against the figure's "
        "OWN row labels (the 2026-10-17 audit: the CopyNumBench Results named six metric IDs "
        "while Fig. 2 drew eight row labels -- breakpoint precision and recall included -- and "
        "15 blocks, while the deposited MCB table keeps 16 because intCN_modal_frac is repeated "
        "under both scenario labels).\n\n"
        "## A. written values with candidate producers\n\n"
        + _evidence_artifact_table(
            h_rows,
            ["document", "kind", "number", "unit", "sentence", "candidate producer",
             "producer summary", "seed check"],
            "no claim-surface number the shipped tables fail to prove")
        + "\n\n## B. code/config literals (producer side)\n\n"
        + _evidence_artifact_table(
            c_rows, ["file", "line", "symbol", "value", "context"],
            "no module-level literal found in the corpus's code/config files")
        + "\n\n## C. written NEGATIVE claims a shipped table contradicts\n\n"
        "A sentence that says a method was not run, was not evaluated or produced no output, "
        "while a shipped table carries that method's own rows with finite values. The hierarchy "
        "makes the raw-data side authoritative: either the table's stale rows are removed (a "
        "regenerated figure/table is a manual item) or the written claim is corrected.\n\n"
        + _evidence_artifact_table(
            n_rows,
            ["written claim", "method token", "shipped table says", "detail"],
            "no written negative claim contradicts a shipped table")
        + "\n")
    _seed_write(work / "M30_hierarchy_reconciliation.md", m30_text)
    if art is not None:
        _seed_write(art / "M30_hierarchy_reconciliation.md", m30_text)
    if where == "review":
        # Keep the M20 skeleton the review contract points at.
        _seed_review_format_artifact(ctx, sb)
    elif where == "judge":
        fmt = ev.get("format") or {}
        fmt_rows = [{"rule": r.get("rule"), "severity": r.get("severity"),
                     "location": r.get("location"), "evidence": r.get("evidence"),
                     "fix": r.get("fix")} for r in (fmt.get("rows") or [])]
        _seed_write(art / "M20_formatting.md", "# M20 — OOXML style/formatting (code-side enumeration of this judge's target)\n\n"
            "Audit every row; mechanical rows were already normalized by the orchestrator "
            "before this view was built.\n\n"
            + _evidence_artifact_table(fmt_rows,
                                       ["rule", "severity", "location", "evidence", "fix"],
                                       "no code-side formatting finding")
            + "\n")
    plc = ev.get("placeholders") or {}
    sref = ev.get("submission_references") or {}
    sref_rows = sref.get("rows") or []
    lines += ["## Submission-surface references (PKG-2)", "",
              "A to-be-submitted document may only point at content the submission itself "
              "carries. Every row below names a file of THIS package that refers at what the "
              "submission does not carry ("
              + (", ".join(f"`{a}/`" for a in (sref.get("not_carried") or [])) or "no area")
              + ", plus the author's `README*.md`/`README*.txt` files). REWRITE the sentence so "
              "it points at shipped content or carries the fact itself -- the pipeline removes "
              "the sentence mechanically if it is still there when the package is published, "
              "and a removed sentence loses the science it carried. A row whose rule is `PKG-3` "
              "is the other shape: the document names a file this package carries NOWHERE (not "
              "in the submission, not in `code/`, not in `raw_data/`), so no reader can resolve "
              "it and the mechanical layer will NOT touch it -- the sentence must be rewritten "
              "to ship the file, name a locator the submission carries, or drop the pointer.",
              ""]
    if sref_rows:
        lines += [f"| file | line | rule | reference | resolves to |", "|---|---|---|---|---|"]
        for r in sref_rows[:40]:
            lines.append(f"| {r.get('file')} | {r.get('line')} | {r.get('rule') or 'PKG-2'} | "
                         f"`{r.get('reference')}` | "
                         + (", ".join(f"`{x}`" for x in (r.get("resolves_to") or [])) or "—")
                         + " |")
    else:
        lines.append("(no dangling reference in a to-be-submitted file)")
    # PLACEHOLDER FILES: named so no role reads one as evidence (see the block
    # above `declared_placeholder_paths`). Seeded for every working session; the
    # judge's view never carries a producer list, so it is not appended there.
    if where not in ("judge",):
        pfr = ev.get("placeholder_files") or {}
        if pfr.get("error"):
            lines += ["", "## Placeholder files (ignored)", "",
                      f"(the placeholder-file check could not run: {pfr['error']})"]
        elif pfr.get("ignored"):
            lines += ["", "## Placeholder files -- ignored", "",
                      "These files stand in for data they do not contain (declared by the "
                      "operator, or detected as identical bytes under another sample/dataset "
                      "name). They are NOT evidence and NOT a producer: never cite one to "
                      "support, strengthen or contradict a claim, and do not score a claim by "
                      "them. A claim that rests only on one of them is `unable -- placeholder "
                      "input; the real data is not in the corpus`, and the author is the one "
                      "who supplies or removes the file.", "",
                      "| file | why it is a placeholder |", "|---|---|"]
            for rel in pfr["ignored"][:40]:
                why = (pfr.get("reasons") or {}).get(rel, "placeholder")
                lines.append(f"| `{rel}` | {why} |")
        if pfr.get("declared_patterns"):
            lines += ["", "Declared placeholder pattern(s): "
                      + ", ".join(f"`{x}`" for x in pfr["declared_patterns"][:12])]
    # PKG-11/12/14/15/16: package self-consistency. Every row is a defect of the
    # package, not a style note -- the fix is a renamed header, a regenerated
    # table, or a corrected letter, so the session must STATE what it did.
    pc = ev.get("package_consistency") or {}
    pc_rows = []
    for key in ("column_near_misses", "mcb_rule_conflicts", "pooled_table_mismatches",
                "form_software_coverage", "prior_submission_disclosure",
                "form_method_conflicts", "ranking_claim_conflicts",
                "recovered_structure_claims", "sd_estimator_ambiguity",
                "definition_overreach", "cited_note_negations",
                "single_cell_citation_mismatch", "caption_definition_gaps",
                "form_failure_claims"):
        pc_rows.extend(pc.get(key) or [])
    if pc.get("error"):
        lines += ["", "## Package self-consistency (PKG-11 to PKG-25)", "",
                  f"(the scans could not run: {pc['error']})"]
    elif pc_rows:
        lines += ["", "## Package self-consistency (PKG-11 to PKG-25)", "",
                  "Each row is one package surface contradicting another (or the analysis it "
                  "carries). The pipeline never edits these: renaming a table's header, "
                  "regenerating a statistics table and correcting a cover letter are the "
                  "author's acts. Resolve or record each one in the change ledger and the "
                  "manual-steps report; do not leave a row undisposed.", "",
                  "| rule | file | line | detail |", "|---|---|---|---|"]
        for r in pc_rows[:30]:
            detail = str(r.get("detail") or "").replace("|", "/")[:260]
            lines.append(f"| {r.get('rule')} | `{r.get('file')}` | {r.get('line')} | "
                         f"{detail} |")
    dis = ev.get("display_items") or {}
    dis_rows = dis.get("rows") or []
    if dis_rows or dis.get("error"):
        lines += ["",
                  "## Display items the submission does not carry (PKG-4)", "",
                  "A document that CITES (and usually legends) a figure the package carries no "
                  "file for leaves the reader nothing to look at. Ship the figure, embed it in "
                  "the document that legends it, or drop the citation -- say which in the "
                  "package, and say where the figure now lives.", ""]
        if dis_rows:
            lines += ["| file | line | item | the package holds it only as |",
                      "|---|---|---|---|"]
            for r in dis_rows[:20]:
                lines.append(f"| {r.get('file')} | {r.get('line')} | `{r.get('reference')}` | "
                             + (", ".join(f"`{x}`" for x in (r.get("resolves_to") or [])) or "—")
                             + " |")
        else:
            lines.append(f"(the check could not run: {dis.get('error')})")
    gap = ev.get("front_matter_gaps") or {}
    gap_rows = gap.get("rows") or []
    if gap_rows:
        lines += ["",
                  "## Title-page gaps (FMT-TP1)", "",
                  "The venue profile records this run's content type; it states NO rule that the "
                  "type is printed on the title page. These rows COUNT AND NAME the gap (a rule "
                  "this rule set does not state is never invented): if the target journal's own "
                  "guidelines ask for the type on the title page, print it; otherwise record the "
                  "confirmation.", ""]
        for r in gap_rows[:8]:
            lines.append(f"- `{r.get('file')}`: {r.get('detail')}")
    prov = ev.get("display_provenance") or {}
    prov_rows = prov.get("rows") or []
    if prov_rows or prov.get("error"):
        lines += ["",
                  "## Display-item provenance contradictions (PKG-5)", "",
                  "Two shipped surfaces attribute ONE display item to different tools (a "
                  "resources/software table row against the item's own legend). The pipeline "
                  "reports it and picks no side: correct the table row or the legend, and check "
                  "which item the real producer belongs to. M35's disclosure sweep is where this "
                  "class is disposed.", ""]
        if prov_rows:
            lines += ["| file | item | tools the table claims | the legend's producer |",
                      "|---|---|---|---|"]
            for r in prov_rows[:20]:
                lines.append(f"| {r.get('file')} | {r.get('item')} | `{r.get('reference')}` | "
                             + str(r.get("detail", "")).split("attributes it to ", 1)[-1][:80]
                             + " |")
        else:
            lines.append(f"(the check could not run: {prov.get('error')})")
    contr = ev.get("contradictions") or {}
    contr_rows = contr.get("rows") or []
    if contr_rows or contr.get("error"):
        lines += ["",
                  "## Statements that contradict each other (PKG-6/7/8/9)", "",
                  "Each row quotes TWO statements the same submission makes. The pipeline "
                  "picks no side and never rewrites either one: decide which is true and make "
                  "the other agree. PKG-6 = one text both denies generative-AI use and "
                  "describes the AI workflow it used; PKG-7 = one identifier (commit hash, "
                  "accession, DOI) written at two lengths, so the short one resolves to "
                  "nothing; PKG-8 = the same comparison described with two different units of "
                  "analysis (a caption counting cells while the table's note counts donors).", ""]
        if contr_rows:
            lines += ["| rule | file | the two statements |", "|---|---|---|"]
            for r in contr_rows[:20]:
                lines.append(f"| {r.get('rule')} | {r.get('file')} | "
                             + str(r.get("evidence", "")).replace("|", "\\|")[:200] + " |")
        else:
            lines.append(f"(the check could not run: {contr.get('error')})")
    decl_ev = ev.get("submission_declaration") or {}
    if decl_ev.get("declared"):
        lines += ["",
                  "## What the submission actually carries", "",
                  f"The package's own `{decl_ev.get('readme')}` declares the submitted set: "
                  + " / ".join(f"`{p}`" for p in decl_ev.get("patterns") or [])
                  + f" -- {decl_ev.get('submitted_count')} submitted file(s), "
                  f"{decl_ev.get('not_submitted_count')} carried-but-NOT-submitted. Every "
                  "reference judgement above was made against THAT set: a file this package "
                  "carries but the declaration excludes is unreachable for the reader.", ""]
        if decl_ev.get("submitted_files"):
            for f in decl_ev["submitted_files"][:40]:
                lines.append(f"- `{f}`")
    elif decl_ev.get("ignored_reason"):
        lines += ["",
                  "## What the submission actually carries", "",
                  f"The package's own README declares a submission rule that was IGNORED: "
                  f"{decl_ev['ignored_reason']}. The scans fell back to the pipeline's own model "
                  f"(the corpus minus the evidence areas, `code/` and the author's READMEs).", ""]
    lines += ["",
              "## Hand-off placeholders", "",
              f"- count: {plc.get('count', '?')}",
              f"- files: {', '.join(plc.get('files') or []) or '(none)'}", "",
              "## Corpus identity", "",
              f"- digest: `{str((ev.get('corpus_identity') or {}).get('digest'))[:16]}`",
              f"- revision token: `{(ev.get('corpus_identity') or {}).get('revision_token') or '(none)'}`",
              f"- files: {len((ev.get('corpus_identity') or {}).get('files') or [])}", ""]
    (work / "EVIDENCE_PACK.md").write_text("\n".join(lines), encoding="utf-8")
    (sb / "EVIDENCE_PACK.md").write_text("\n".join(lines), encoding="utf-8")
    if where in ("review", "judge"):
        # also inside the session's OUT directory, where the agent's own report
        # lives, so the pack is one path away from the artifact tables
        (sb / (REVIEW_DIR if where == "review" else "judge_review")
         / "EVIDENCE_PACK.md").write_text("\n".join(lines), encoding="utf-8")
    return ev


def seeded_evidence_paths(sb: Path) -> set:
    """Every file `seed_evidence_pack` may write into a session sandbox.

    `leftovers_present` must treat these as INPUTS, not as agent work: a freshly
    materialized review/judge sandbox already contains them.
    """
    rels = ["EVIDENCE_PACK.md", "work/CODE_SCANS.json", "work/FORMAT_SCAN.json",
            "work/EVIDENCE_PACK.md", "work/PROVENANCE.json",
            "work/OFFICIAL_TEMPLATE.json", "work/OFFICIAL_TEMPLATE.md",
            "format_policy.json"]
    # The provenance pack is seeded into EVERY non-judge layout, so the review
    # sandbox's copies live under review/work/ and the stage sandboxes' under
    # work/; `leftovers_present` must treat both as inputs, or a freshly
    # materialized review sandbox looks "already worked in" and never starts.
    prov_stems = ("PROVENANCE.json", "NUMBERS_LEDGER.md", "IDENTIFIERS.md",
                  "GENE_LEDGER.md", "PLACEHOLDER_LOOKUP.md", "M24_concepts.md",
                  "GLOSSARY.md", "CLAIM_STRENGTH.md", "M2_references.md",
                  "M30_hierarchy_reconciliation.md")
    rels += [f"work/{s}" for s in prov_stems]
    rels += [f"{REVIEW_DIR}/work/{s}" for s in prov_stems]
    rels += [f"{REVIEW_DIR}/work/OFFICIAL_TEMPLATE.json",
             f"{REVIEW_DIR}/work/OFFICIAL_TEMPLATE.md"]
    # Judge sandboxes are deliberately absent: nothing is seeded there (blinding).
    rels += [f"{REVIEW_DIR}/EVIDENCE_PACK.md", f"{REVIEW_DIR}/work/CODE_SCANS.json",
             f"{REVIEW_DIR}/work/FORMAT_SCAN.json", f"{REVIEW_DIR}/work/EVIDENCE_PACK.md",
             f"{REVIEW_DIR}/artifacts/M18_caption_words.md",
             f"{REVIEW_DIR}/artifacts/M19_length.md",
             f"{REVIEW_DIR}/artifacts/M20_formatting.md",
             f"{REVIEW_DIR}/artifacts/M4_numbers.md",
             f"{REVIEW_DIR}/artifacts/M8_terms.md",
             f"{REVIEW_DIR}/artifacts/OUTLINE.md",
             f"{REVIEW_DIR}/artifacts/PLACEHOLDERS.md",
             f"{REVIEW_DIR}/artifacts/CLAIM_STRENGTH.md",
             f"{REVIEW_DIR}/artifacts/M30_hierarchy_reconciliation.md",
             f"{REVIEW_DIR}/artifacts/M2_references.md",
             f"{REVIEW_DIR}/artifacts/NUMBERS_LEDGER.md",
             f"{REVIEW_DIR}/artifacts/IDENTIFIERS.md",
             f"{REVIEW_DIR}/artifacts/GENE_LEDGER.md",
             f"{REVIEW_DIR}/artifacts/PLACEHOLDER_LOOKUP.md",
             f"{REVIEW_DIR}/artifacts/M24_concepts.md",
             f"{REVIEW_DIR}/artifacts/GLOSSARY.md"]
    return {sb / r for r in rels}


def evidence_pack_block(where: str) -> str:
    """The prompt block that tells a session where its evidence pack is."""
    if where == "review":
        paths = ("`review/work/CODE_SCANS.json` / `review/work/EVIDENCE_PACK.md` (and the "
                 "seeded `review/artifacts/M18_caption_words.md`, `M19_length.md`, "
                 "`M20_formatting.md`, `M4_numbers.md`, `NUMBERS_LEDGER.md`, `M8_terms.md`, "
                 "`M24_concepts.md`, `GLOSSARY.md`, `IDENTIFIERS.md`, `M2_references.md`, "
                 "`OUTLINE.md`, "
                 "`PLACEHOLDERS.md`, `PLACEHOLDER_LOOKUP.md` and `CLAIM_STRENGTH.md` tables; "
                 "CLAIM_STRENGTH enumerates BOTH directions of the J3 claim-strength check, "
                 "`under` (a hedge the evidence may not require) and `over` (a maximal claim the "
                 "evidence may not support), and every row must be disposed. "
                 "`M30_hierarchy_reconciliation.md` is the source-hierarchy seed: table A pairs "
                 "the written values no shipped data table proves with their candidate producer "
                 "columns (and the check the code could make), table B lists the code/config "
                 "literals; dispose both and ADD the producers the code cannot see. "
                 "`M2_references.md` is the reference-INTEGRITY seed: one row per reference "
                 "entry that carries a DOI, with the orchestrator's own resolver verdict for it "
                 "(`found` / `absent` = both registration agencies answered no / `error` / "
                 "`skipped`) and the code-side signals (a year token inside the DOI that "
                 "contradicts the entry's year, one DOI on two entries); a `found` record that "
                 "names a DIFFERENT work than the entry, and an `absent` DOI an entry states, "
                 "are both findings)")
    elif where == "audit":
        paths = ("`work/CODE_SCANS.json` / `EVIDENCE_PACK.md` next to your PROMPT.md, the "
                 "seeded `work/FORMAT_SCAN.json` rows (each with a `tier`), "
                 "`work/NUMBERS_LEDGER.md`, `work/IDENTIFIERS.md`, `work/PLACEHOLDER_LOOKUP.md`, "
                 "`work/M24_concepts.md`, `work/GLOSSARY.md` and `work/CLAIM_STRENGTH.md` (the "
                 "J3 claim-strength ledger, BOTH directions), and the reviewer's disposed tables "
                 "under `review/artifacts/` -- including the reviewer's disposed "
                 "`review/artifacts/M30_hierarchy_reconciliation.md` and the "
                 "`review/artifacts/M2_references.md` seed it disposed row by row (each "
                 "reference entry's DOI with the orchestrator's resolver verdict) -- a closure "
                 "there is only as good as the verdict it names, so attack it: an `absent` DOI "
                 "or a `found` record that names another work is a finding, not a formality")
    elif where == "judge":
        # BLINDING: a judge is handed NOTHING but the blinded packages. It must
        # derive every measurement itself (and its own discovery findings -- see
        # the discovery pass); the orchestrator verifies the judge's rows
        # afterwards and never seeds them.
        return """BLINDING RULE (read first) -- you are handed the blinded packages and NOTHING else: no
   findings or reviews from other sessions, no discovery list, no change ledger,
   no orchestrator measurements, no digests or version tokens, no pre-computed check rows, and
   no history of any package. (ONE
   venue-level exception: when the venue ships an official template, `visual_template/` holds
   that template's own render -- identical for every session and every package, derived from
   nothing in the field, so it names no provenance; see the visual-inspection rule.) Your
   session identifier, your sandbox path and the number of opponents are the only session facts
   you get; they are opaque and deliberately carry no ordering, age or origin information. Judge
   each package on its CONTENT alone: names, timestamps and document metadata were stripped from
   every view precisely so that no package can be recognised, dated, ranked by anything but
   content, or identified as having (or not having) a history at all. Everything you write must be
   derived by YOU from `target/` and `field/<label>/` with the tools named in this
   prompt -- for code-side measurements use `python paper_docx_format.py scan <dir>` (and the
   counting in the sweeps) and record the rows in `judge_review/artifacts/`. If you find yourself
   relying on a file that is not part of a submission package, stop: that information is not
   available to a blind judge, and the panel's validity depends on your judging the CONTENT in
   front of you only."""
    else:
        paths = ("`work/CODE_SCANS.json` / `EVIDENCE_PACK.md` next to your PROMPT.md (the "
                 "numbers of the package you are about to edit) plus the code-side provenance "
                 "pack: `work/NUMBERS_LEDGER.md` (every number, with the source the orchestrator "
                 "could PROVE from the shipped data tables), `work/IDENTIFIERS.md` (every "
                 "DOI/accession/repository/ORCID with its verification verdict), "
                 "`work/PLACEHOLDER_LOOKUP.md` (the answers the pipeline already found for the "
                 "searchable hand-off markers), `work/M24_concepts.md` (competing term families "
                 "for one concept), `work/GLOSSARY.md` (the term decisions to conform to) and "
                 "`work/CLAIM_STRENGTH.md` (the J3 claim-strength ledger: `under` = hedges the "
                 "evidence may not require, `over` = maximal claims the evidence may not "
                 "support -- your own edits must not move a claim in EITHER direction), plus "
                 "`work/M30_hierarchy_reconciliation.md` (the source-hierarchy seed: a written "
                 "value its own shipped code/raw data contradicts must be aligned to the "
                 "authoritative side, never silently changed to match either) and "
                 "`work/M2_references.md` (the reference-integrity seed: every reference entry "
                 "that carries a DOI, with the orchestrator's resolver verdict and the code-side "
                 "signals -- an entry whose DOI does not resolve, or resolves to a DIFFERENT "
                 "work than the entry names, is a wrong citation to correct, never to delete)")
    return f"""CODE-SIDE EVIDENCE PACK (identical measurements in every session) -- the
   orchestrator has already scanned this corpus with the same functions it uses at setup and at
   `decide`, and seeded the result as {paths}. Treat those numbers as the session's baseline:
   use them instead of re-estimating, dispose or reconcile every seeded row in your own artifact,
   and when your work changes one of them (a section grows past its cap, a legend loses words, a
   formatting row appears or disappears, a hand-off placeholder is added), say so explicitly in
   your report with the before -> after numbers. Never contradict the pack silently; never
   "fix" a number by editing the pack."""


# ---------------------------------------------------------------------
# Code-side hand-off-placeholder count (M18's sibling, id M6-adjacent).
#
# The revision stages are forbidden from inventing content and mark everything
# they must hand to the author with the literal token "[AUTHOR TO COMPLETE: ...]".
# The review skill's M6 hygiene sweep would otherwise read that token as leftover
# template text and file a finding against the very version that obeyed the
# pipeline, and a judge comparing it with an unmarked package would count it as a
# defect the revision introduced. The prompts therefore neutralise the marker,
# and the orchestrator keeps its own count so the operator can see the hand-off
# items. The count is a DIAGNOSTIC: it never ranks, gates, filters or delays
# anything (a package is never punished for carrying hand-off markers).
# ---------------------------------------------------------------------

def scan_placeholders_in_sources(sources: list) -> dict:
    """Count "[AUTHOR TO COMPLETE: ...]" markers per corpus document."""
    overrides = corpus_source_overrides(sources)
    hits, unparsed = [], []
    for i, (src, prefix, excluded) in enumerate(sources):
        if not src.is_dir():
            continue
        for p in _iter_tree_files(src):
            if is_non_document_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if (prefix + rel) in overrides[i]:
                continue                      # a later source provides this path
            if is_non_manuscript_rel(rel):
                continue        # evidence area: a hand-off marker can only be a
                                # submission document's marker, never evidence's
            if is_bookkeeping_name(p.name):
                continue                      # the reports legitimately list them
            ext = p.suffix.lower()
            texts = None
            if ext == ".docx":
                texts = _docx_paragraphs(p)
            elif ext == ".pdf":
                # An accepted PDF is a submission rendering, not a document the
                # OOXML reader can open. Read its text when poppler exists (so a
                # real letter/statement is still marker-scanned); only an
                # untextractable PDF is UNKNOWN below.
                _pdf_text_value = _pdf_text(p)
                if _pdf_text_value:
                    texts = _pdf_text_value.splitlines()
                else:
                    unparsed.append(prefix + rel)
                    continue
            elif ext in PLACEHOLDER_SOURCE_EXTS:
                try:
                    texts = p.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    texts = None
            elif ext in CAPTION_UNPARSED_EXTS:
                unparsed.append(prefix + rel)
                continue
            else:
                continue
            if texts is None:
                unparsed.append(prefix + rel)
                continue
            n = sum(len(PLACEHOLDER_RE.findall(t or "")) for t in texts)
            if n:
                hits.append({"document": prefix + rel, "count": n})
    return {"count": sum(h["count"] for h in hits), "documents": hits,
            "files": [h["document"] for h in hits], "unparsed": sorted(set(unparsed))}


def placeholder_info_for(ctx: Ctx, r: int, vid: str):
    """Recorded hand-off-placeholder count for a version (never a ranking input)."""
    info = None
    if vid == ORIGINAL_ID:
        info = ctx.state.get("original_placeholders")
    elif is_fresh_vid(vid):
        info = (ctx.run(rid_for_fresh(r, vid)) or {}).get("placeholders")
    else:
        info = (find_pin(ctx, vid) or {}).get("placeholders")
    return info if isinstance(info, dict) else None


# ---------------------------------------------------------------------
# Code-side document-set checking: a revision must not lose a document.
# Names are compared after stripping a trailing version token, and a document
# whose content survives under a different name is reported but not failed.
# ---------------------------------------------------------------------

def _is_aux_doc(name: str) -> bool:
    """Is this ONE document a difference-tracking auxiliary (never content)?

    The rule is a NAME rule, deliberately: it has to hold for a file the
    pipeline just wrote next to its parent document, for a file an agent wrote
    in a sandbox the pipeline never opened, and for a file inside a pin that a
    later `status`/`decide` invocation walks. See `TRACKING_AUX_NAME_RE` for the
    token vocabulary and `tracking_aux_suffix()` for the one place the names are
    built.
    """
    return bool(TRACKING_AUX_NAME_RE.search(name))


def tracking_aux_suffix(token: str, ext: str, fallback: bool = False) -> str:
    """The auxiliary suffix for one (baseline token, extension) pair.

    `original` + `.docx` -> ".tracking-original.docx" (or ".logging-original.docx"
    when `fallback`); `a1` + `.tex` -> ".tracking-a1.tex" (or ".logging-a1.tex");
    `winner2` + `.bib` -> ".tracking-winner2.bib"; a tracking `.tex` root's
    compiled PDF is `a1` + ".pdf" -> ".tracking-a1.pdf". This is the ONLY place
    the names are built, so a reader and a writer can never drift apart.
    """
    tok = str(token).strip().lower()
    if not TRACK_TOKEN_RE.match(tok):
        raise ValueError(f"unknown tracking baseline token: {token!r}")
    if ext not in TRACKING_EXTS + (TRACKING_PDF_EXT,):
        raise ValueError(f"unknown tracking extension: {ext!r}")
    return f".{'logging' if fallback else 'tracking'}-{tok}{ext}"


def _doc_key(rel: str) -> str:
    p = Path(rel)
    stem = DOC_TOKEN_RE.sub("", p.stem)
    # The stage's content token is not the only renameable part. A package
    # produced from `mainText-FrontiersTemplate-zotero-<old>` may correctly
    # become `mainText-<new>`; pairing only the token-stripped stem made the
    # first look lost and the second look invented, so recovery restored the
    # superseded copy and every retry recreated the same two-token package.
    prev = None
    while prev != stem:
        prev = stem
        stem = DOC_PROVENANCE_SUFFIX_RE.sub("", stem)
    parent = p.parent.as_posix()
    prefix = "" if parent in (".", "") else parent + "/"
    return prefix + stem.lower() + p.suffix.lower()


def collect_documents(sources: list) -> dict:
    """{normalized name: [(relative path, sha256), ...]} for submission docs.

    Bookkeeping files are skipped (they are regenerated, not submission
    content) and a path a later source also provides is skipped, so this view
    matches the corpus that corpus_manifest()/build_corpus_dir() materialise.
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
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if (prefix + rel) in overrides[i]:
                continue
            if is_evidence_rel(rel):
                # The evidence area is not the submission's document set: a
                # reviewer's feedback file or a data table is never a "lost
                # document" or an "invented document" (its byte-level contract
                # is enforced by verify_readonly_raw_data instead).
                continue
            if is_author_to_complete_readme_name(p.name):
                # The hand-off README is generated/updated by the mode, never a
                # manuscript document: its appearance or disappearance is not
                # an invented/lost submission document.
                continue
            if is_bookkeeping_name(p.name):
                continue
            if p.suffix.lower() not in EDITABLE_DOC_EXTS:
                continue
            out.setdefault(_doc_key(prefix + rel), []).append((prefix + rel, sha256_file(p)))
    return out


def document_set_check(base_sources: list, cand_sources: list) -> dict:
    """Did every base document survive, and does the candidate carry rename twins?

    Base documents are matched to candidate documents ONE-TO-ONE: same
    normalised name + same bytes, then same normalised name with edited bytes,
    then the same bytes under any other name. A key-level test is not enough:
    two real documents can share a normalised name ("Supplementary-Table-1.csv"
    and "...-2.csv" both reduce to "supplementary-table.csv"), so a key that
    survives in the candidate would silently hide a deleted sibling.

    The comparison is run in BOTH directions, because the defect is two-sided:
    a document the base had and the candidate lost is a preservation failure,
    and a submission document the candidate carries that the base never had is
    the same comparison read the other way (content that was added/invented --
    or a declared scaffolding addition under the mandatory-item rule). Both are
    REPORTED, neither is failed here: a lost document is restored from the base
    by `backfill_missing_files` wherever recovery is legal (a deliberately
    dropped derived output stays dropped), and only a human can tell a
    legitimate scaffold from invented content in the added direction.
    """
    base, cand = collect_documents(base_sources), collect_documents(cand_sources)
    cand_pool = [(key, rel, dig) for key, entries in cand.items() for rel, dig in entries]
    used = set()

    def take(match) -> bool:
        for i, item in enumerate(cand_pool):
            if i in used:
                continue
            if match(*item):
                used.add(i)
                return True
        return False

    missing, content_only, unmatched = [], [], []
    for key, entries in sorted(base.items()):
        for rel, dig in entries:
            if take(lambda k, r, d, key=key, dig=dig: k == key and d == dig):
                continue                        # renamed file, bytes unchanged
            if take(lambda k, r, d, key=key, rel=rel: k == key and r == rel):
                continue                        # survived under the same name, edited
            if take(lambda k, r, d, dig=dig: d == dig):
                content_only.append(rel)         # moved/renamed, bytes preserved
                continue
            unmatched.append((key, rel))
    # A version-stripped key can stand in for a document name ONLY after every
    # exact-name pairing is done. When several base documents share a key
    # (Dataset-a.csv / Dataset-b.csv), pairing the first one by key consumes the
    # surviving sibling's slot and reports the WRONG file as lost -- the same
    # collision the byte/digest steps above exist to prevent.
    for key, rel in unmatched:
        if take(lambda k, r, d, key=key: k == key):
            continue                            # rename family (...-b.docx -> ...-c.docx)
        missing.append(rel)
    duplicates = {}
    base_names = {key: {r for r, _d in entries} for key, entries in base.items()}
    for key, entries in sorted(cand.items()):
        if len(entries) < 2:
            continue
        names = [r for r, _d in entries]
        if key in base_names and [r for r in names if r not in base_names[key]]:
            # A name that was NOT in the base collides with a sibling name of a
            # document family the base actually had (a pre-existing sibling pair
            # like Table-1/Table-2 is left alone; two brand-new documents that
            # merely share a stripped name are not this defect):
            # exactly the pre/post-rename twin this check exists to surface
            duplicates[key] = names
    added = [rel for i, (_k, rel, _d) in enumerate(cand_pool) if i not in used]
    return {"missing": missing, "content_preserved_under_other_name": content_only,
            "added": added,
            "duplicates": duplicates,
            "base_count": sum(len(v) for v in base.values()),
            "candidate_count": sum(len(v) for v in cand.values())}


def judge_target_token(r: int, vid: str) -> str:
    """Deterministic UNSALTED token: a test/fixture helper, never a run token.

    Production tokens go through judge_token_for(), which mixes in the root's
    random salt so a token cannot be recomputed from (round, version id) alone;
    a root without a salt is refused rather than falling back to this function.
    """
    h = hashlib.sha256(f"paper-judge-target|{int(r)}|{vid}".encode("utf-8")).hexdigest()[:8]
    return JUDGE_TOKEN_PREFIX + h


def judge_salt_of(ctx: "Ctx") -> str:
    """The per-root secret that keeps judge-side identity unguessable.

    One reader for the salt so the session token and the label permutation
    cannot drift apart. An empty value is invalid: a root without a salt is a
    corrupt/legacy root, and `judge_token_for` refuses it.
    """
    try:
        return str((getattr(ctx, "state", None) or {}).get("judge_salt") or "")
    except Exception:                                           # noqa: BLE001
        return ""


def judge_token_for(ctx: "Ctx", r: int, vid: str) -> str:
    """The judge session token for a version (salted; no unsalted fallback)."""
    salt = judge_salt_of(ctx)
    if not salt:
        die("this root has no judge_salt: its judge ids cannot be made unguessable. "
            "Recreate the root with `setup` (or restore state.json's judge_salt) before "
            "materializing judges.")
    h = hashlib.sha256(f"paper-judge-target|{salt}|{int(r)}|{vid}".encode("utf-8")).hexdigest()
    return JUDGE_TOKEN_PREFIX + h[:8]


def iqr_of(vals: list) -> float:
    if len(vals) >= 2:
        try:
            q = statistics.quantiles(vals, n=4, method="inclusive")
            return float(q[2] - q[0])
        except Exception:
            pass
    return 0.0


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        # RuntimeError is what Path.resolve raises on a symlink loop
        # (ELOOP); a path that cannot be resolved is not contained.
        return False


def contained_under(root, rel) -> Path:
    """Resolve a recorded root-relative path and REFUSE one that escapes.

    State records (`winner_dir`, ...) are data, not trusted path fragments: an
    absolute path or `../outside` must never make a destructive move or a
    publication read outside the pipeline root.
    """
    base = Path(root).resolve()
    raw = Path(str(rel or ""))
    target = raw if raw.is_absolute() else base / raw
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError) as e:
        die(f"the recorded path {rel!r} cannot be resolved under {base}: {e}")
    try:
        resolved.relative_to(base)
    except ValueError:
        die(f"the recorded path {rel!r} escapes the pipeline root {base}; refusing to "
            f"touch it (repair state.json)")
    return resolved


def _aux_ignore(_dir, names):
    return [n for n in names if _is_aux_doc(n)]


def _corpus_ignore(skip_aux: bool, strip_bookkeeping: bool):
    """shutil.copytree ignore-callback for a VERSION CORPUS copy."""
    def _ignore(_dir, names):
        out = []
        if skip_aux:
            out += [n for n in names if _is_aux_doc(n)]
        if strip_bookkeeping:
            out += [n for n in names if is_bookkeeping_name(n)]
        return out
    return _ignore


# ---- permissions: the raw-data directory is READ-ONLY by contract -----------
# The corpus's raw-data directory (`raw_data/`) is an
# INPUT: the pipeline never edits its content, and an operator may well have
# made the whole subtree read-only (`chmod -R a-w`) as their own protection --
# which is exactly the assumption this section implements. A pipeline-owned copy
# of a corpus can therefore contain read-only FILES and read-only DIRECTORIES,
# and that breaks two mechanical operations that have nothing to do with
# content:
#   * deleting a tree the pipeline owns (a scratch copy, a pruned sandbox, a
#     stale final_clean_version.tmp): unlinking an entry needs WRITE on the
#     directory that holds it;
#   * rewriting the pipeline's own copy of a package (a stage-side repair or
#     restoring raw_data from the pristine copy): writing a file needs WRITE on
#     the file, and replacing an entry needs WRITE on its directory.
# `make_tree_writable` hands the write bits back and returns a plan that
# `restore_modes` can put back verbatim; `rmtree_force` clears them only when an
# ordinary delete fails. Neither ever changes content.

def is_raw_data_rel(rel: str) -> bool:
    """True when a corpus-relative path lives inside raw_data/."""
    top = str(rel or "").replace("\\", "/").lstrip("/").split("/", 1)[0]
    return top in RAW_DATA_DIRNAMES


def is_code_rel(rel: str) -> bool:
    """True when a corpus-relative path lives inside the analysis-code area.

    `code/` is the revision's own code deliverable (a stage may revise it), but
    it is NEVER a submitted file: the journal submission copy strips it exactly
    like the raw-data evidence area, and no to-be-submitted document (the
    response letter in particular) may cite a path inside it.
    """
    top = str(rel or "").replace("\\", "/").lstrip("/").split("/", 1)[0]
    return top == CODE_DIR


# The author's own documentation is never submitted either: any FILE whose name
# matches the glob `README*.md` / `README*.txt` (at any depth) is treated like
# `code/` for submission purposes. It stays in the corpus (and therefore in a
# pin and a published winner), but the journal submission copy drops it, no
# to-be-submitted document may refer into it, and `journal_submission.json`
# records every file that was dropped. The match is case-insensitive: a
# `readme.md` must not ship by accident.
README_NAME_RE = re.compile(r"^readme.*\.(?:md|txt)$", re.IGNORECASE)


def is_non_submitted_readme_name(name: str) -> bool:
    """True for a `README*.md` / `README*.txt` file name (never submitted)."""
    return bool(README_NAME_RE.match(str(name or "").strip()))


def is_author_to_complete_readme_name(name: str) -> bool:
    """True for the pipeline's own hand-off README (an author checklist).

    The file matches `README*.md`, so the submission copy already drops it.
    The distinct predicate exists because the PACKAGE-side hygiene must NOT
    treat it like an author's stray internal note: it is the deliberate
    hand-off surface of `author_to_complete: readme`, it sits beside the cover
    letter and main text, and it must survive into the published package.
    """
    return (str(name or "").strip().lower()
            == AUTHOR_TO_COMPLETE_README.lower())


# The author's README files are never submitted (see `is_non_submitted_readme_name`),
# but the CORPUS carries them so the package's own submitted-set declaration
# travels with it (`declared_submission_set`). One class of them must not travel
# any further than that: the `code/README*.md` a revision session WRITES beside
# the code it revised, narrating that session's findings and hand-offs. The
# 2026-10-15 neohet package reached its certified state carrying one (PKG-1
# reported it, and the delivered package shipped it anyway). These constants let
# the producing stage postcheck holds such a file back before the corpus digest,
# routing it to the root's `reports/readme_notes/` and naming it in the sibling
# status readme, so the operator keeps the text while no future round, pin or
# delivered package carries it as manuscript content.
README_NOTE_HOLD_DIRNAME = "readme_notes"


def readme_internal_note_rows(p: Path, limit: int = 12) -> list:
    """The PKG-1 rows a `README*.md`/`README*.txt` file carries (see above).

    Returns [{"line", "evidence"}] -- empty when the file reads as ordinary
    documentation (an author's own README, or a `README_RERUN.md` written for a
    reader who will actually run the code). An unreadable or oversized file
    yields no rows: this is a hygiene filter, never a reader.
    """
    p = Path(p)
    try:
        if p.stat().st_size > PACKAGE_TEXT_BYTES_LIMIT:
            return []
        text = p.read_text("utf-8", "replace")
    except OSError:
        return []
    rows = []
    for i, line in enumerate(text.splitlines(), 1):
        for _label, pattern in INTERNAL_ARTIFACT_RES:
            if not pattern.search(line):
                continue
            rows.append({"line": i, "evidence": line.strip()[:180]})
            break
        if len(rows) >= limit:
            break
    return rows


def hold_internal_readme_notes(dirp: Path, dest_dir: Path,
                               warns: list = None) -> list:
    """Move internal-note README files out of `dirp` into `dest_dir`.

    Returns the moved records [{"file", "held_at", "rows"}]. `dest_dir` must be
    OUTSIDE the package (the stage postcheck passes the root's
    `reports/readme_notes/<run>/`): the file is documentation the operator may
    want, but it may not be shipped, and a sibling would become manuscript
    content in the next round. A move that fails leaves the file in place and is
    recorded in `warns`.
    """
    out = []
    dirp, dest_dir = Path(dirp), Path(dest_dir)
    for p in sorted(dirp.rglob("*")):
        if not p.is_file() or not is_non_submitted_readme_name(p.name) \
                or is_author_to_complete_readme_name(p.name):
            continue
        rows = readme_internal_note_rows(p)
        if not rows:
            continue
        rel = p.relative_to(dirp).as_posix()
        target = dest_dir / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and _same_file_bytes(p, target):
                # The identical note is already held from an earlier decision:
                # the destination is *idempotent*, so a second `decide` over the
                # same package does not accumulate `README.md-2`, `-3`, ...
                # copies of one file. Only a note whose TEXT changed gets a new
                # name (the author's older wording is still worth keeping).
                p.unlink()
            elif target.exists():
                target = unique_path(target)
            if p.exists():
                shutil.move(str(p), str(target))
        except OSError as e:                                          # noqa: BLE001
            if warns is not None:
                warns.append(f"{rel}: the internal-note README could not be held back "
                             f"({type(e).__name__}: {e}); it is still in the package")
            continue
        out.append({"file": rel, "held_at": str(target), "rows": rows})
    return out


# A Word OWNER (lock) file: `<~$><document name>` beside the document Word has
# open. It is never manuscript content: it holds the opening user's name, it is
# not a document (converting it fails "not a zip file"), and it matches no
# submission name pattern. The pipeline's version corpora and published copies
# therefore never carry one -- exactly like a difference-tracking auxiliary --
# and the recovery layer never restores one a stage dropped. Readers that list
# the corpus (the review's file inventory, the M9/M6 sweeps) already skip it by
# this same prefix; this predicate is the ONE place the rule is spelled.
def is_word_owner_name(name: str) -> bool:
    """True for a Word owner/lock file name (`~$document.docx`)."""
    return str(name or "").strip().startswith("~$")


# PLATFORM JUNK (2026-10-15): a file the OPERATING SYSTEM wrote beside a real
# one. WSL/Windows "Mark of the Web" leaves an alternate-data-stream stub when a
# file is copied out of a download (`figures/figS3.png:Zone.Identifier`, 25
# bytes of `[ZoneTransfer] ZoneId=3`) and the two desktops leave an index file
# (`.DS_Store`, `Thumbs.db`, `desktop.ini`). None of them is manuscript content:
# they are not documents, they carry no text, and the 2026-10-15 neohet package
# shipped one inside `figures/` -- a name that looks like a figure the
# submission does not contain. Reported and stripped at publication; never
# counted as a document by any scan.
PLATFORM_JUNK_SUFFIXES = (":zone.identifier", ":zone.identifier:$data")
PLATFORM_JUNK_NAMES = frozenset({".ds_store", "thumbs.db", "ehthumbs.db", "desktop.ini"})


def is_platform_junk_name(name: str) -> bool:
    """True for an OS by-product that is never part of a submission."""
    low = str(name or "").strip().lower()
    if not low:
        return False
    base = low.replace("\\", "/").rsplit("/", 1)[-1]
    if base.strip() in PLATFORM_JUNK_NAMES:
        return True
    return any(sfx in low for sfx in PLATFORM_JUNK_SUFFIXES)


def is_bytecode_cache_name(name: str) -> bool:
    """True for a Python bytecode-cache FILE name (`*.pyc`/`*.pyo`).

    `is_bytecode_cache` answers the same question for a corpus-RELATIVE path
    (it also recognises a `__pycache__` DIRECTORY in the path). This is the
    name-only spelling a copytree ignore-callback and a directory sweep need,
    so the two questions have one vocabulary each instead of three call sites
    each spelling their own suffix list.
    """
    return str(name or "").strip().lower().endswith(BYTECODE_SUFFIXES)


def is_non_shippable_name(name: str) -> bool:
    """A file name that must NEVER reach a published/delivered package.

    Three classes, one predicate, so the copy filter, the directory sweep and
    the readiness scan can never disagree about what "junk" means:
      * an OS by-product (`figS3.png:Zone.Identifier`, `.DS_Store`, ...);
      * a Python bytecode cache (`foo.pyc` -- a side effect of RUNNING a helper
        script, never a deliverable);
      * a Word OWNER (lock) file (`~$doc.docx`).

    A file that is AREA content by a different rule (`code/`, `raw_data/`) is
    NOT in this class: this predicate is only about names no submission, no
    corpus and no next round can use.
    """
    return bool(is_platform_junk_name(name) or is_bytecode_cache_name(name)
                or is_word_owner_name(name))


def strip_non_shippable_files_in_dir(dirp: Path) -> dict:
    """Delete `is_non_shippable_name` files below `dirp`; return what went.

    The stage-side sweep before a package's corpus identity is recorded (and
    the last-resort helper for a package built by an older orchestrator; a
    publication that meets such a package preserves the pin and reports the
    residue instead of changing judged bytes). Files inside an EVIDENCE area
    are never touched -- that
    subtree is read-only by contract (`raw_data/` is a byte-frozen input) -- and
    `__pycache__/` DIRECTORIES are skipped on purpose: removing one would empty
    the directory a bytecode file's name lives in, and an empty directory is
    still a directory the next round would carry.

    Returns `{"removed": [rel, ...], "kept_in_evidence": [rel, ...]}`.
    """
    out = {"removed": [], "kept_in_evidence": []}
    dirp = Path(dirp)
    if dirp.is_symlink():
        # `rglob` would descend through a root link and `unlink()` the target's
        # files. A package root is a real directory; a link is a different tree
        # and is never this function's to delete.
        out["skipped_symlink"] = str(dirp)
        return out
    if not dirp.is_dir():
        return out
    for q in sorted(dirp.rglob("*")):
        if not q.is_file() or not is_non_shippable_name(q.name):
            continue
        rel = q.relative_to(dirp).as_posix()
        if is_evidence_rel(rel):
            out["kept_in_evidence"].append(rel)
            continue
        try:
            q.unlink()
        except OSError:
            continue
        out["removed"].append(rel)
    return out


def strip_stage_non_shippable(sb: Path, pkg_dir: Path) -> dict:
    """The stage-side sweep over BOTH halves of the version corpus.

    `corpus_sources()` folds the run's `code/` directory into the corpus under
    the `code/` prefix, but the postcheck used to sweep only the stage package:
    a `code/__pycache__/*.pyc` (or a `.DS_Store`) therefore entered the corpus
    digest, the pin and the published copy. Both halves are swept BEFORE the
    digest is recorded; the return shape keeps the package's own `removed` list
    (the delivery report's existing consumer) and adds the code area separately.
    """
    sb, pkg_dir = Path(sb), Path(pkg_dir)
    out = {"removed": [], "kept_in_evidence": [], "package": {},
           "code": {}}
    if pkg_dir.is_dir():
        out["package"] = strip_non_shippable_files_in_dir(pkg_dir)
        out["removed"].extend(out["package"].get("removed") or [])
        out["kept_in_evidence"].extend(out["package"].get("kept_in_evidence") or [])
    code = sb / CODE_DIR
    if code.is_dir():
        out["code"] = strip_non_shippable_files_in_dir(code)
        out["removed"].extend(f"{CODE_DIR}/{rel}" for rel in (out["code"].get("removed") or []))
        out["kept_in_evidence"].extend(
            f"{CODE_DIR}/{rel}" for rel in (out["code"].get("kept_in_evidence") or []))
    return out


def is_non_document_name(name: str) -> bool:
    """A name that is never manuscript content: auxiliary, lock or OS junk."""
    return bool(_is_aux_doc(name) or is_word_owner_name(name) or is_platform_junk_name(name))


def evidence_area_of(rel: str) -> str:
    """The EVIDENCE area a corpus-relative path belongs to ("" when none).

    Evidence areas (`raw_data/`, `human_review_feedback/`, `llm_review_feedback/`)
    are inputs: never submission documents, never written-surface text.
    """
    top = str(rel or "").replace("\\", "/").lstrip("/").split("/", 1)[0]
    return top if top in EVIDENCE_DIRNAMES else ""


def is_disabled_evidence_name(name: str) -> bool:
    """True for `<evidence area>.disabled` / `.off` -- an INERT top-level name."""
    base = Path(str(name or "")).name
    for area in EVIDENCE_DIRNAMES:
        if base.startswith(area + ".") \
                and base[len(area) + 1:].strip().lower() in DISABLED_EVIDENCE_SUFFIXES:
            return True
    return False


def is_disabled_evidence_rel(rel: str) -> bool:
    """True when a corpus-relative path lives in an inert disabled area."""
    top = str(rel or "").replace("\\", "/").lstrip("/").split("/", 1)[0]
    return is_disabled_evidence_name(top)


def is_evidence_rel(rel: str) -> bool:
    """True when a corpus-relative path lives inside an EVIDENCE area."""
    return bool(evidence_area_of(rel)) or is_disabled_evidence_rel(rel)


def is_canonical_evidence_link(link: Path, root: Path = None) -> bool:
    """True when `link` is a symlink to THIS root's canonical evidence area.

    The ONE evidence link a corpus legitimately carries is the relative
    `<root>/non_revised/<area>` link that
    `ensure_pristine_input` creates. A top-level entry *named* `raw_data` is not
    evidence by itself: following it would copy whatever local directory or file
    it points at into the pristine root, every judge view and the published
    package. The name alone never authorizes the follow; the resolved target must
    be the canonical store of the root that owns the copy (`root`). Without a
    root there is nothing to prove containment against, so the link is refused.
    """
    if root is None:
        return False
    try:
        link = Path(link)
        root = Path(root).resolve(strict=True)
        if not link.is_symlink():
            return False
        target = link.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if not target.is_dir():
        return False
    if target.name != link.name or not is_evidence_rel(link.name):
        return False
    for dirname in PRISTINE_DIRNAMES:
        try:
            if (root / dirname / link.name).resolve(strict=True) == target:
                return True
        except (OSError, RuntimeError):
            continue
    return False


def is_human_feedback_rel(rel: str) -> bool:
    """True when a path lives in the human editors'/reviewers' feedback area."""
    return evidence_area_of(rel) == HUMAN_FEEDBACK_DIR


def is_llm_feedback_rel(rel: str) -> bool:
    """True when a path lives in the (pre-filtered) LLM review feedback area."""
    return evidence_area_of(rel) == LLM_FEEDBACK_DIR


def is_non_manuscript_rel(rel: str) -> bool:
    """True when a corpus path is NOT the authors' manuscript prose.

    Either it lives in an EVIDENCE area, or its name says it is a feedback or
    response-to-reviewers document wherever it sits. Used by the written-surface
    scans (captions, lengths, formatting, numbers, placeholders): such text is
    never the manuscript, even when the operator kept it beside the documents
    instead of in `human_review_feedback/`. A COVER LETTER is not excluded here
    -- it is a submission document and M19 counts it as one.
    """
    if is_evidence_rel(rel):
        return True
    base = str(rel or "").replace("\\", "/").rsplit("/", 1)[-1]
    if AUTHORED_REPLY_NAME_RE.search(base):
        return True
    # A COVER LETTER is a submission document (M19 counts it as one) even when
    # its name says "to_editor"; only its "cover" spelling protects it here.
    # The word is matched as a WORD (see _COVER_WORD_RE): a bare `cover`
    # substring also matched `discovery.md`, `coverage_table.txt` and
    # `recovered_notes.tex`, forcing those back into the manuscript scans.
    if _COVER_WORD_RE.search(base):
        return False
    return is_journal_feedback_name(base)


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
        return True
    except OSError:
        if ignore_errors:
            return not p.exists()
        raise


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
    """The top-level evidence area names present in one corpus directory."""
    out = []
    for name in EVIDENCE_DIRNAMES:
        p = Path(dirp) / name
        if p.is_dir() or p.is_symlink():
            out.append(name)
    try:
        for child in sorted(Path(dirp).iterdir()):
            if is_disabled_evidence_name(child.name) \
                    and (child.is_dir() or child.is_symlink()):
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
        if (hash_manifest(ctx.pristine, exclude_top=set(areas)).get("files")
                != hash_manifest(dst, follow_dir_links=True,
                                 exclude_top=set(areas)).get("files")):
            ok = False
        for name in areas:
            link = dst / name
            if not link.is_symlink() or link.resolve() != want[name].resolve():
                ok = False
                break
    if ok:
        return info
    if dst.exists():
        rmtree_force(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    copy_into(ctx.pristine, dst, exclude_top=set(areas), root=ctx.root)
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


def copy_into(src: Path, dst: Path, exclude_top=(), skip_aux: bool = False,
              strip_bookkeeping: bool = False, normalize_mtime: bool = False,
              root: Path = None) -> None:
    """Copy the CONTENTS of src into dst (idempotent; overwrites files).

    root: the pipeline root that owns `src`. A top-level evidence link is
    followed only when it resolves to THIS root's canonical
    `<root>/non_revised/<area>` store (see `is_canonical_evidence_link`); a
    caller that omits it follows no evidence link at all.

    exclude_top: top-level entry names to skip (used to keep a candidate's
    process scratch, e.g. revised/work/, out of its submission corpus).
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
    dst.mkdir(parents=True, exist_ok=True)
    skipped = []
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
        for name in names:
            if os.path.islink(os.path.join(dirpath, name)):
                skipped.append(os.path.join(dirpath, name))
                out.add(name)
        return sorted(out)

    for entry in sorted(src.iterdir()):
        if entry.name in exclude_top:
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
        if skip_aux and _is_aux_doc(entry.name):
            continue
        if strip_bookkeeping and entry.is_file() \
                and is_bookkeeping_name(entry.name):
            continue
        target = dst / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True, ignore=_ignore)
        elif entry.is_file():
            shutil.copy2(entry, target)
    if skipped:
        print(f"warning: skipped {len(skipped)} symlink(s) while copying {src} -> {dst} "
              f"(a link is not package content; its target may be outside the package): "
              + ", ".join(sorted(str(s) for s in skipped)[:5])
              + (" ..." if len(skipped) > 5 else ""), file=sys.stderr)
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
        src, exclude_top=tuple(kw.get("exclude_top") or ())).get("files") or {}
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
    if dst.exists():
        rmtree_force(dst, ignore_errors=True)
    copy_into(src, dst, **kw)
    return True


def ensure_corpus_dir(ctx: "Ctx", r: int, vid: str, dst: Path) -> bool:
    """build_corpus_dir() with the same partial-copy repair (see ensure_copy)."""
    want = corpus_manifest(ctx, r, vid).get("files") or {}
    if dir_matches(dst, want):
        return False
    if dst.exists():
        rmtree_force(dst, ignore_errors=True)
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


def pid_alive(pid: int) -> bool:
    """Is a process with this pid running (best effort, POSIX + Windows)?

    Used only to decide whether a lock file is STALE: a permission error means
    the process exists but belongs to another user, which still counts as alive.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # On Windows os.kill(pid, 0) raises OSError for an existing process in
        # some shells; fall back to "assume alive" so a live lock is never stolen.
        return os.name == "nt"
    return True


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


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
                die(f"{flag}: round ordinals are 1-based, got {item!r}")
            if hi < lo:
                die(f"{flag}: empty round range {chunk!r} in {item!r}")
            # Refuse an implausible span HERE: `1-999999999` used to expand
            # into a billion-element set -- the process died (MemoryError, no
            # message) long before `validate` could range-check it against the
            # configured round count.
            if hi - lo + 1 > ONLY_ROUND_RANGE_CAP:
                die(f"{flag}: round range {chunk!r} in {item!r} names "
                    f"{hi - lo + 1} rounds; the pipeline's round count is a handful "
                    f"(rounds are 1-based)")
            rounds.update(range(lo, hi + 1))
            continue
        if not chunk.isdigit():
            die(f"{flag}: {chunk!r} in {item!r} is not a round ordinal (1, 2, ... "
                f"or a range like 1-3)")
        if int(chunk) < 1:
            die(f"{flag}: round ordinals are 1-based, got {item!r}")
        rounds.add(int(chunk))
    if not rounds:
        die(f"{flag}: {item!r} names no round")
    return rounds


def parse_only_stage(token: str, item: str, flag: str = "--only") -> str:
    """Resolve one stage name or alias, or die with the accepted list."""
    name = ONLY_ALIASES.get(token, token)
    if name not in ONLY_STAGES:
        die(f"{flag}: unknown stage {item!r}; choose from {', '.join(ONLY_STAGES)} "
            f"(aliases: merge=integrate, w=rewrite, a/a2=revise, j=judge, "
            f"fb=feedback, resp=response)")
    return name


class OnlySpec:
    """The parsed `run --only` selection: which ROUNDS and which STAGES run.

    Every accepted item selects something, and the items are a UNION:

        1,2          rounds 1 and 2 in full (every stage of those rounds)
        1-3          rounds 1..3 in full
        review       the review stage of every round
        2:review     round 2's review only  (`2.review`, `2/review` also work)
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
        # `run --only review` also drives the round's PROBE session (see
        # entry_selected: the probe is part of the review STEP, and the auditor
        # and revisers consume its findings). `retry --runs` clears this: a
        # retry resets exactly the runs the operator named, so redoing the
        # review never silently re-pays for the probe.
        self.probe_with_review = True

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
        if vid in ("review", "review_b"):
            return "review"
        # Exact stage names win over the single-letter prefixes below: "audit"
        # must not be read as "a" (revise), and the journal chain's stages are
        # their own classes.
        if vid in ("probe", "audit", "feedback", "concerns", "response"):
            return vid
        if vid == "conform":
            return "conform"
        if vid.startswith("w"):
            return "rewrite"
        if vid.startswith("a"):
            return "revise"
        if vid.startswith("i"):
            return "integrate"
        return "review"

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
        if stage == "probe" and self.probe_with_review and "review" in self.classes_for(r):
            # The PROBE is part of the review STEP: selecting the review stage
            # (`--only review`, `2:review`) runs the probe beside it, because the
            # auditor and the revisers consume its findings -- without this, the
            # documented `--only review` -> `--only audit` sequence would block
            # on the probe dependency. A session-level token (`r1_review`) stays
            # exact: run `--only r1_probe` / a plain `run` to complete the step.
            return True
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


def parse_only_spec(raw, flag: str = "--only", probe_with_review: bool = True) -> OnlySpec:
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
    spec.probe_with_review = bool(probe_with_review)
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
        # `r1_w2` / `r1_a2` / `r1_i1` / `r1_review` / `r1_review_b` / `r1_audit`:
        # ONE session of one round. A `_j<k>` tail makes it a judge session
        # (`r1_w2_j1`), the same selection as `r1_judge_w2_j1`.
        sel = re.fullmatch(r"r(\d+)\s*[_:/.-]\s*(w\d+|a\d+|i\d+|review|reviewer|probe|audit|"
                           r"feedback|concerns|response|"
                           r"rewriter\d+|reviser\d+|integrator\d+)"
                           r"((?:[_:/.-](?:b|j\d+))?)", token)
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
        # others -- `r1_w1`, `r1_i1`, `r1_review`, `r1_audit` -- are already
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
                stages = {parse_only_stage(stage_token, part, flag)}
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
                stages = {parse_only_stage(stage_token, part, flag)}
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
        # revise spelling must be `reviser1`.
        if re.fullmatch(r"(?:w\d+|i\d+|rewriter\d+|writer\d+|reviser\d+|revise\d+|"
                        r"integrator\d+|integrate\d+|reviewer|review_b)", token):
            _add_session_token(spec, None, token, part, flag)
            continue
        spec.stages.add(parse_only_stage(token, part, flag))
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
    if not re.fullmatch(r"(?:w\d+|a\d+|i\d+|review|review_b|probe|audit|feedback|concerns|"
                        r"response)", sid):
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
    m = re.fullmatch(r"(reviewer|review)(_?b)?", tok)
    if m:
        return "review_b" if m.group(2) else "review"
    if re.fullmatch(r"(?:a1|w\d+|a\d+|i\d+|orig|probe|audit|feedback|concerns|response)", tok):
        if tok == "a1":
            die(f"{flag}: {part!r} names a1, the round base COPY -- it has no agent session "
                f"(use `reviser1` for the first reviser, which edits a1 into a2)")
        if tok == "orig":
            die(f"{flag}: {part!r} names the pristine original, which has no agent session")
        return tok
    die(f"{flag}: {part!r} is not a session this pipeline knows (use a stage name, or a session "
        f"such as `rewriter1`, `reviser1`, `integrator1`, `review`, `audit`, `w2`, `w2_j1`, "
        f"`r1_w2`, `r1_judge_w2_j1`)")


def session_id_of_entry(entry: dict) -> str:
    """The id of the agent session a round-plan entry runs (`w2`, `a2`, `review`...).

    Review and audit entries carry no `vid`; their session id is the bare stage
    name, except the second review session of `--review-split`, which is
    `review_b` (the id `--only r1_review_b` selects).
    """
    vid = str((entry or {}).get("vid") or "")
    if vid:
        return vid
    rid = str((entry or {}).get("id") or "")
    return "review_b" if rid.endswith("_review_b") else plan_stage_of(entry)


def parse_only_stages(raw) -> set:
    """The STAGE side of `--only` (`run --only rewrite,review,merge`).

    Kept for the stage-only callers and tests: None/empty/`all` selects every
    stage (the default). A round-qualified item (`2:review`) contributes its
    stage; the round filter itself lives in parse_only_spec(), which is what the
    `run` command uses.
    """
    spec = parse_only_spec(raw)
    return spec.stage_filter() if spec else set()


def plan_stage_of(entry: dict) -> str:
    """The bare stage name of a round-plan entry.

    `round_run_plan` labels entries with their plan position ("revise 1/1",
    "integrate 2/2", "rewrite 1/2", "review"); `--only` filters on the bare
    name, so map the label back to it.
    """
    return str((entry or {}).get("stage") or "").strip().lower().split(" ")[0]

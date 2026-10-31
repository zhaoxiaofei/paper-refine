# -*- coding: utf-8 -*-
# Part 06/20 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# COMPLETION SIGNALS
# =====================================================================

# --- where a completion signal may legitimately be found ---------------------
# The prompts ask for `_pipeline_done.json` (and, for a judge, `scores.json`)
# in the sandbox ROOT, next to PROMPT.md, and the postcheck reads it there.
# Two real 2026-09-23 failures came from a signal that was written ONE
# DIRECTORY DOWN instead: the auditor wrote `audit/_pipeline_done.json` (the
# audit prompt's own "write everything inside `audit/`" invited exactly that)
# while its audit.json/AUDIT.md were complete and its own summary said
# `"status": "complete"`, and the run then cost 20 minutes of agent time plus a
# full sandbox rebuild. The layers below are independent of each other:
#
#   1. every prompt states the marker's exact location (see marker_root_rule),
#   2. every session can run the orchestrator's own pre-flight check before it
#      writes the marker (see `sandbox_selfcheck` / `selfcheck_block`),
#   3. `relocate_stray_signal()` ADOPTS a signal that names THIS run and stage
#      from the run's own output directory -- the work is the same work, and
#      only its address is wrong -- while a signal naming another run or stage
#      is reported (never adopted, never silently ignored), and
#   4. the failure message names the stray file, so an operator reading
#      `[FAIL]` sees where the signal actually is.
SIGNAL_ALT_DIRS = {
    "audit": ("audit",),
    "judge": ("judge_review",),
    "guided_review": (GUIDED_REVIEW_DIR,),
    "cold_start_review": (COLD_START_DIR,),
    "rewrite": (REWRITTEN_DIR,),
    "revise": (REVISED_DIR,),
    "integrate": (INTEGRATED_DIR,),
    # The journal stages write their own ledgers, not a revised/ package.
    "feedback": ("concerns",),
    "concerns": ("concerns",),
    "response": ("response",),
}


def signal_names_of(kind: str) -> tuple:
    """The completion-signal file names this run may deliver (root-relative)."""
    return (SCORES_FILE, MARKER_FILE) if kind == "judge" else (MARKER_FILE,)


def signal_search_dirs(sb: Path, kind: str) -> list:
    """The directories this stage's OWN signal may sit in (the root first)."""
    return [sb] + [sb / d for d in SIGNAL_ALT_DIRS.get(str(kind or ""), ())]


def stray_signal_path(sb: Path, kind: str, name: str):
    """The signal file when it sits in the stage's own directory, else None."""
    for d in signal_search_dirs(sb, kind)[1:]:
        p = d / name
        try:
            if p.is_file():
                return p
        except OSError:                                          # noqa: BLE001
            continue
    return None


def _signal_names_this_run(data, rec: dict, name: str) -> bool:
    """Does this candidate signal name THIS run (and stage) and nothing else?

    Deliberately strict: the stage is what makes a stray file unambiguous (a
    revise sandbox carries the auditor's `audit/` copy, so a marker that names
    `audit` must never be adopted as the reviser's own), and a `run_id` that
    names another run is another session's property. A file that does not parse
    is never adopted.
    """
    if not isinstance(data, dict):
        return False
    if name == SCORES_FILE:
        # The judge's sheet carries an OPAQUE target token while the run record
        # holds the raw version id: comparing the two id spaces rejected every
        # modern stray sheet. A sheet that names THIS run is this run's signal.
        if data.get("run_id") == rec.get("id"):
            return True
        if rec.get("target_id") and data.get("target_id") not in (None, rec["target_id"]):
            return False
    elif data.get("stage") != rec.get("kind"):
        return False
    return data.get("run_id") in (None, rec.get("id"))


def stray_signal_note(sb: Path, rec: dict, name: str) -> str:
    """One sentence naming a stray signal file, or "" when there is none."""
    p = stray_signal_path(sb, rec.get("kind"), name)
    if p is None:
        return ""
    rel = p.relative_to(sb).as_posix()
    data = read_json(p, revive=False, lenient=True)              # agent-written
    if isinstance(data, dict) and name == MARKER_FILE:
        what = f"it names stage {data.get('stage')!r} / run {data.get('run_id')!r}"
    elif isinstance(data, dict):
        what = f"it names run {data.get('run_id')!r} / target {data.get('target_id')!r}"
    else:
        what = "it does not parse as a JSON object"
    return (f"a `{name}` exists at `{rel}` instead of the sandbox root -- {what}, this run is "
            f"{rec.get('id')!r} / stage {rec.get('kind')!r}; write `{name}` in the sandbox ROOT")


def relocate_stray_signal(ctx: Ctx, rec: dict) -> list:
    """Adopt this run's OWN completion signal when it was written one level down.

    Returns the notes to record as warnings. Nothing is adopted unless the
    signal names this run and this stage (see `_signal_names_this_run`), and a
    signal that is NOT adoptable is left exactly where it is -- the postcheck's
    "missing marker" error then names its location (see `stray_signal_note`).
    """
    if rec.get("kind") == "a1":
        return []
    sb = ctx.sandbox_of(rec)
    notes = []
    for name in signal_names_of(rec.get("kind")):
        if not sb.is_dir() or (sb / name).is_file():
            continue
        found = stray_signal_path(sb, rec.get("kind"), name)
        if found is None:
            continue
        rel = found.relative_to(sb).as_posix()
        if not _signal_names_this_run(read_json(found, revive=False, lenient=True), rec, name):
            continue
        try:
            shutil.move(str(found), str(sb / name))
        except OSError as e:                                     # noqa: BLE001
            notes.append(f"the `{name}` written to `{rel}` could not be moved to the sandbox "
                         f"root ({type(e).__name__}: {e}); it will not be read from there")
            continue
        notes.append(f"the completion signal `{name}` was written to `{rel}` instead of the "
                     f"sandbox root; it is ADOPTED (moved to `{name}` in the root). The prompt "
                     f"asks for `{name}` in the sandbox root, next to PROMPT.md")
        print(f"  [warn] {rec.get('id')}: {notes[-1]}")
    return notes


def find_signal_path(sb: Path, kind: str, name: str) -> Path:
    """The path a stage's signal was found at, root-first, falling back to the root."""
    for d in signal_search_dirs(sb, kind):
        p = d / name
        if p.is_file():
            return p
    return sb / name


def marker_json(sb: Path, kind: str = ""):
    m = read_json(find_signal_path(sb, kind, MARKER_FILE),
                  revive=False, lenient=True)                    # agent-written
    return m if isinstance(m, dict) else None


def scores_json_of(sb: Path, kind: str = ""):
    sj = read_json(find_signal_path(sb, kind, SCORES_FILE),
                   revive=False, lenient=True)                   # agent-written
    return sj if isinstance(sj, dict) else None


def completion_signal_exists(ctx: Ctx, rec: dict) -> bool:
    """The strict agent-written signal (never a bare non-empty revised/)."""
    if rec["kind"] == "a1":
        return True
    sb = ctx.sandbox_of(rec)
    if rec["kind"] == "judge":
        return (scores_json_of(sb, rec["kind"]) is not None
                or marker_json(sb, rec["kind"]) is not None)
    return marker_json(sb, rec["kind"]) is not None


def likely_complete_artifacts(ctx: Ctx, rec: dict) -> bool:
    """Permissive signal for the 'process died after the agent finished' path."""
    if completion_signal_exists(ctx, rec):
        return True
    sb = ctx.sandbox_of(rec)
    if rec["kind"] == "guided_review":
        return (sb / FINDINGS_REL).is_file()
    if rec["kind"] in ("rewrite", "revise", "integrate"):
        out = sb / output_dir_of(rec)
        return out.is_dir() and any(out.iterdir())
    if rec["kind"] == "judge":
        # A partial sheet from a crashed attempt must not be adopted silently:
        # require the full comparison set for this session's labels.
        return judge_sheet_complete(scores_json_of(sb, rec["kind"]), rec)
    if rec["kind"] == "audit":
        # The auditor's whole product is `audit/audit.json` (its dispositions are
        # what the revisers consume). Without this branch the "process died after
        # the agent finished" path never fired for the audit stage, so a session
        # whose CLI exited non-zero with a complete, valid sheet was re-run
        # instead of re-verified.
        aj = read_json(sb / "audit" / "audit.json", revive=False, lenient=True)
        return isinstance(aj, dict)
    if rec["kind"] == "cold_start_review":
        # The cold-start session's product is the machine-readable findings/verifier
        # file; REPRODUCTION.md is written by the postcheck, so it is not a
        # completion signal of its own.
        return (sb / COLD_START_FINDINGS_REL).is_file()
    return False


def judge_sheet_complete(sj, rec: dict) -> bool:
    """True when a judge sheet is valid AND carries one comparison per issued label."""
    if not isinstance(sj, dict):
        return False
    errs, _warns = validate_judge_sheet(sj, rec)
    if errs:
        return False
    labels = set(rec.get("label_map") or {})
    seen = {_norm_opponent_label(c.get("opponent_label")) for c in (sj.get("comparisons") or [])
            if isinstance(c, dict)}
    return labels <= seen


def _copy_session_tools(sb: Path, stamp: float = None) -> None:
    """Put the code-side scanner/validator next to PROMPT.md.

    The stage prompts call `python paper_docx_format.py scan|validate <dir>` by
    name, so the module has to be reachable from the session's cwd. It is the
    public, stateless tool the orchestrator itself uses (no per-run data, no
    answers), and `leftovers_present()` ignores it, so copying it never makes a
    fresh sandbox look like it holds agent work. A judge sandbox gets it too
    (its prompt names the same command) and the file is stamped with the view
    timestamp, so it cannot date the packages around it.
    """
    src = Path(__file__).resolve().with_name(DOCX_FORMAT_MODULE)
    dst = sb / DOCX_FORMAT_MODULE
    try:
        if src.is_file() and (not dst.is_file() or dst.read_bytes() != src.read_bytes()):
            shutil.copyfile(src, dst)
        # The formatter is a thin loader too: its ordered parts must sit beside
        # it, or the stage's `python paper_docx_format.py scan` call cannot run.
        parts_name = "paper_docx_format_parts"
        if (src.parent / parts_name).is_dir():
            copy_asset_dirs(src.parent, sb, names=(parts_name,))
    except OSError as e:
        # A partial/refused copy used to be swallowed: the stage then called a
        # missing or incomplete formatter and the agent had no scan tool, with
        # no diagnostic naming the staging failure. Fail the stage loudly.
        raise RuntimeError(
            f"could not stage {DOCX_FORMAT_MODULE} and paper_docx_format_parts "
            f"into {sb}: {type(e).__name__}: {e}") from e
    # Stamping is cosmetic (it keeps the copy from dating the sandbox): a
    # timestamp failure must not turn into a staging failure.
    if stamp is not None:
        with contextlib.suppress(OSError):
            if dst.is_file():
                os.utime(dst, (stamp, stamp))
        parts_name = "paper_docx_format_parts"
        if (sb / parts_name).is_dir():
            with contextlib.suppress(OSError):
                for p in (sb / parts_name).rglob("*.py"):
                    os.utime(p, (stamp, stamp))
                os.utime(sb / parts_name, (stamp, stamp))


def leftovers_present(ctx: Ctx, rec: dict) -> bool:
    """True when a pending sandbox already holds AGENT output (never re-enter).

    Kind-aware on purpose: a revise sandbox is materialized WITH a read-only
    guided_review/ copy, and an integration/judge sandbox is materialized with its
    inputs, so those directories must not be mistaken for partial work by the
    agent.
    """
    if rec["kind"] == "a1":
        return False
    sb = ctx.sandbox_of(rec)
    if rec["kind"] == "judge":
        # BLINDING: nothing is seeded into a judge sandbox, so any judge_review/
        # content is the agent's own work (scores.json alone is also accepted as
        # the completion signal elsewhere).
        return (sb / SCORES_FILE).exists() or (sb / "judge_review").is_dir()
    if rec["kind"] == "guided_review":
        d = sb / GUIDED_REVIEW_DIR
        if not (d.is_dir() and any(d.iterdir())):
            return False
        # The orchestrator SEEDS the M20 formatting sweep (the code-side scan is
        # the enumeration), so those two files are inputs, not agent work: a
        # review sandbox holding only them is still clean/unstarted.
        seeded = seeded_evidence_paths(sb)
        return any(p.is_file() and p not in seeded for p in d.rglob("*"))
    if rec["kind"] == "audit":
        # The auditor's deliverable IS `audit/` (materialization creates it
        # empty; the seeded evidence pack goes to `work/`), so anything in it is
        # the agent's own work. Without this branch the guard fell through to
        # the package-dir probe below (`output_dir_of` returns `revised/` for
        # every non-package kind), which an audit sandbox never has -- so a
        # crashed auditor's half-written sheet looked like an untouched sandbox
        # and a second agent was launched straight into it.
        d = sb / "audit"
        if not d.is_dir():
            return False
        seeded = seeded_evidence_paths(sb)
        return any(p.is_file() and p not in seeded for p in d.rglob("*"))
    if rec["kind"] == "cold_start_review":
        # The cold-start session's output directory is created (with the seeded claim
        # surface/producer lists) by the materializer; anything else under it is
        # the agent's own work, and the repro record the postcheck writes cannot
        # exist yet for a pending run.
        d = sb / COLD_START_DIR
        if not d.is_dir():
            return False
        seeded = seeded_cold_start_paths(sb)
        return any(p.is_file() and p not in seeded for p in d.rglob("*"))
    if rec["kind"] in ("feedback", "concerns"):
        # The journal stages' deliverables live in concerns/, not revised/;
        # without this branch a partial JF_concerns.json was invisible and a
        # second agent was launched into the first one's work.
        d = sb / "concerns"
        return d.is_dir() and any(d.iterdir())
    if rec["kind"] == "response":
        d = sb / "response"
        return d.is_dir() and any(d.iterdir())
    # rewrite / revise / integrate: the output package and code/ are the agent's.
    for rel in (output_dir_of(rec), CODE_DIR):
        d = sb / rel
        if d.is_dir() and any(d.iterdir()):
            return True
    return False


# =====================================================================
# POST-RUN CHECKS
# =====================================================================

def _marker_checks(rec: dict, marker, stage: str, errs: list, warns: list,
                   sb: Path = None) -> None:
    """The marker's LOCATION and fields.

    `sb` is optional only for callers that hold no sandbox (the prompt fixtures
    of the test suites); the postchecks pass it, because the failure message
    must name a stray marker's real path (see `stray_signal_note`) instead of
    sending an operator hunting for a file that exists one directory down.
    """
    # The address is checked FIRST and separately from the content: a marker that
    # exists but is not in the sandbox root has not been found by the pipeline
    # (the postcheck adopts an unambiguous one before this runs, so reaching here
    # with `where` set means it was NOT adoptable -- another run's or another
    # stage's file -- or could not be moved). The message names the path and the
    # provenance it really carries.
    where = ""
    if sb is not None and not (sb / MARKER_FILE).is_file():
        where = stray_signal_note(sb, rec, MARKER_FILE)
    if not isinstance(marker, dict):
        errs.append(f"completion marker {MARKER_FILE} missing (it is prompted as the very last "
                    f"step; a non-empty output directory is NOT completion)"
                    + (f" -- {where}" if where else
                       (f" -- write `{MARKER_FILE}` in the sandbox ROOT, next to PROMPT.md")))
        return
    if where:
        errs.append(f"the completion marker is NOT in the sandbox root: {where}")
    marker_stage = marker.get("stage")
    if marker_stage is None:
        # The marker is already at THIS run's sandbox root, so the run's own
        # context identifies the stage unambiguously. The audit marker from
        # `cnb-to33` omitted `stage` and carried a valid summary; rebuilding a
        # complete 13-minute audit over one optional label wasted a whole
        # attempt. A WRONG non-empty stage is still a hard error, and a stray
        # marker in an alternate directory still needs the field to be adopted.
        warns.append(f"completion marker has no 'stage' field; accepted at the sandbox root "
                     f"as stage {stage!r}")
    elif marker_stage != stage:
        errs.append(f"marker stage mismatch: expected {stage!r}, got {marker_stage!r}")
    if marker.get("run_id") not in (None, rec["id"]):
        errs.append(f"marker run_id mismatch: expected {rec['id']!r}, "
                    f"got {marker.get('run_id')!r}")
    if marker.get("round") is not None and rec.get("round") is not None \
            and marker.get("round") != rec["round"]:
        # Same rule as the judge sheet (see validate_judge_sheet): a judge is
        # never told the round, so an invented value there is a note, not a
        # failure. The other stages ARE told their round and stay strict.
        if rec.get("kind") == "judge":
            warns.append(f"the marker names round {marker.get('round')!r} but this run is round "
                         f"{rec['round']}; the round is never part of a judge prompt and is "
                         f"ignored")
        else:
            errs.append(f"marker round mismatch: expected {rec['round']}, "
                        f"got {marker.get('round')!r}")
    if marker.get("status") == "failed":
        errs.append(f"agent reported failure: {str(marker.get('error'))[:300]}")
    elif marker.get("status") != "complete":
        # The marker is the pipeline's ONLY completion signal. Accepting an
        # absent status made an empty `{}` (and any file with an unrelated JSON
        # body) a successful stage; `stage` may be omitted at the run's own
        # sandbox root, but the COMPLETION claim may not. The audit prompt used
        # to ask for counters only, so it now names this field too.
        if marker.get("status") is None:
            errs.append("completion marker has no 'status' field (write "
                        "\"status\": \"complete\" -- a marker is not a completion signal "
                        "without it)")
        else:
            errs.append(f"marker status is {marker.get('status')!r} (expected 'complete')")
    summ = marker.get("summary")
    if isinstance(summ, dict):
        rec["summary"] = summ
    elif stage in ("audit", "cold_start_review") and any(
            isinstance(marker.get(k), int)
            for k in ("findings_total", "confirmed", "dropped", "added",
                      "finding_tier_rows_examined", "promoted", "findings",
                      "verified", "areas")):
        # The audit and probe prompts specify FLAT counters (and p07 reads
        # them from the marker itself); warning "no summary object" on a
        # marker that exactly follows its own prompt was noise on every run.
        rec["summary"] = {k: marker[k] for k in
                          ("findings_total", "confirmed", "dropped", "added",
                           "finding_tier_rows_examined", "promoted", "findings",
                           "verified", "areas") if k in marker}
    else:
        warns.append("marker carries no summary object")


def _check_pristine_copy(ctx: Ctx, rec: dict, area: str, errs: list,
                         content_only: bool = False, expected=None, warns=None) -> None:
    """A sandbox's pristine copy must match the SETUP-TIME manifest, not merely
    its own pre-run manifest (the two are equal because `run` refuses to start
    when the pristine original changed).

    `content_only` is for the judge's `original/` view: it is ANONYMIZED (see
    build_judge_view), so its paths are placeholders and cannot be compared --
    the guarantee that survives anonymization is that the multiset of file
    CONTENTS matches the expected TRANSFORMED view (`expected`, computed with
    the session's view seed: rewritten references, sanitized metadata).
    """
    if hash_checks_skipped():
        return                  # not verified (--skip-hash)
    p = area_dir(ctx.sandbox_of(rec), area)
    if not p.is_dir():
        errs.append(f"{area}/ copy is missing from the sandbox")
        return
    if content_only:
        want = expected if expected is not None else content_multiset([ctx.pristine])
        got = content_multiset([p])
        if got != want:
            if got == content_multiset([ctx.pristine]) and warns is not None:
                warns.append(f"{area}/ carries the pristine content but is NOT anonymized "
                             f"(the view transform was not applied) -- acceptable only for a "
                             f"legacy/manual sandbox; rebuilt sandboxes are anonymized")
            else:
                errs.append(f"{area}/ does not carry the pristine original's content any more "
                            f"(an anonymized view must keep the expected transformed content)")
        return
    if not manifests_equal(hash_manifest(p, follow_dir_links=True), ctx.source_manifest):
        errs.append(f"{area}/ is not byte-identical to the setup-time pristine original")


def audit_record_of(ctx: Ctx, r) -> dict:
    """The round's audit record ({} when the audit is off, unfinished or unreadable)."""
    try:
        r = int(r)
    except (TypeError, ValueError):
        return {}
    if not audit_enabled(ctx):
        return {}
    arec = ctx.run(rid_audit(r))
    if not arec or arec.get("status") != "done":
        return {}
    data = read_json(ctx.sandbox_of(arec) / "audit" / "audit.json",
                     revive=False, lenient=True)          # agent-written
    return data if isinstance(data, dict) else {}


def findings_from_sandbox(sb: Path, audit=None) -> list:
    """The frozen review's finding rows as THIS sandbox carries them.

    `sb/guided_review/findings.json` (+ `guided_review/round2/findings_extra.json`), with the
    AUDITED list applied when `audit` (an `audit/audit.json` payload) is given:
    the auditor's drops removed, its `AU-` additions appended.

    Pure and sandbox-local on purpose: the revise sandbox holds its OWN copy of
    both the frozen review and the auditor's record, so this is the list the
    SESSION must resolve -- and the same function backs the postcheck
    (`consumed_findings`) and the session's own pre-flight, which therefore
    cannot disagree about which ids a ledger has to name.
    """
    out = []
    for rel in (FINDINGS_REL, "guided_review/round2/findings_extra.json"):
        fj = read_json(sb / rel, revive=False, lenient=True)   # agent-written
        if not isinstance(fj, dict):
            continue
        for f in fj.get("findings") or []:
            if isinstance(f, dict):
                out.append(f)
    if not audit:
        return out
    drops = {str(d.get("id") or "").strip()
             for d in (audit.get("dispositions") or []) if isinstance(d, dict)
             and str(d.get("verdict") or "").strip().lower() == "drop"}
    kept = [f for f in out if str(f.get("id") or "").strip() not in drops]
    kept += [f for f in (audit.get("adds") or []) if isinstance(f, dict)]
    return kept


def consumed_findings(ctx: Ctx, rec: dict) -> list:
    """The finding list a stage must resolve: the frozen review, AUDITED.

    guided_review/findings.json (+ guided_review/round2/findings_extra.json) minus the
    auditor's drops, plus the auditor's `AU-` additions.  With `--audit off`
    this is byte-for-byte the frozen list, so every existing contract keeps its
    meaning; with the auditor on, the revisers act on the dispositions an
    independent session produced, and every drop remains visible in
    `audit/audit.json` for the human.
    """
    return findings_from_sandbox(ctx.sandbox_of(rec),
                                 audit_record_of(ctx, rec.get("round") or 0))


def sandbox_audit_record(sb: Path) -> dict:
    """The auditor's `audit/audit.json` as a package sandbox carries it ({} if none).

    `audit_record_of()` reads the audit RUN's record; a revise/integration
    sandbox has the same file copied into its own `audit/` (that is the
    authoritative list the revisers act on), and the session's pre-flight must
    read what the session can see.
    """
    data = read_json(sb / "audit" / "audit.json", revive=False, lenient=True)
    return data if isinstance(data, dict) else {}


def round_consumed_findings(ctx: Ctx, r) -> list:
    """The round's frozen (audited) review list, for arms whose sandbox carries none.

    The rewrite and integration arms do not consume findings, so they never get
    a `guided_review/` copy -- but the round's frozen list is the SAME list the auditor
    disposed and the revision arm acted on, so the self-reported tie-break
    counts of every arm can be cross-checked against it. An unreadable or
    pruned round yields [] (no cross-check), never a guess.
    """
    try:
        r = int(r)
    except (TypeError, ValueError):
        return []
    # Under `--review-split` the round has ONE frozen list: the merged A+B file,
    # and `merge_review_parts` writes it into session B's `guided_review/` (the directory
    # the revise sessions copy). Reading session A unconditionally therefore
    # handed every consumer a PARTIAL list: the rewrite/integration arms'
    # self-reported remaining counts were cross-checked against A alone, and the
    # decision report's remaining-work figure undercounted by every finding only
    # session B filed. Session A stays the source only when no split is
    # configured (or B never produced a list).
    rev = ctx.run(review_producer_rid(ctx, r))
    if (rev is None or rev.get("status") != "done") and review_split_of(ctx) != "off":
        rev = ctx.run(rid_guided_review(r))
    if not rev or rev.get("status") != "done":
        return []
    if frozen_review_is_synthesized(ctx):
        # `--no-guided-review`: the producer is the cold-start review and the
        # frozen review is synthesized in the AUDIT/REVISE sandboxes, not on the
        # producer's disk. Return its X-9xx rows instead of [] (F04).
        return list(cold_start_findings_rows(ctx, r) or [])
    sb = ctx.sandbox_of(rev)
    if not (sb / FINDINGS_REL).is_file():
        return []
    findings = findings_from_sandbox(sb, audit_record_of(ctx, r))
    # The COLD-START REVIEW is the round's second producer in the same frozen list: arms
    # whose sandbox carries no guided_review/ copy (rewrite, integration) must count
    # its findings here too, or their self-reported critical/writing counts are
    # cross-checked against an incomplete list.
    cold_start_rows, _remap = cold_start_findings_for_merge(
        [f.get("id") for f in findings], cold_start_findings_rows(ctx, r))
    have = {str(f.get("id")) for f in findings}
    findings += [f for f in cold_start_rows if str(f.get("id")) not in have]
    return findings


# ---------------------------------------------------------------------
# The discovery round's X-* list, seeded into the INTEGRATION stage (the one
# stage that needs the round's own list and is not blind). The judges never
# receive it: they re-derive their own pass (`judge_discovery_block`).
# See DISCOVERY_SEED_DIR above and AGENT.md.
# ---------------------------------------------------------------------

def discovery_findings_of(dirp: Path) -> list:
    """The X-* finding rows of a `guided_review/round2/`-shaped directory or its seed copy."""
    data = read_json(dirp / "findings_extra.json", revive=False, lenient=True)
    rows = data.get("findings") if isinstance(data, dict) else None
    out, seen = [], set()
    for f in rows or ():
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "").strip()
        if fid and DISCOVERY_X_ID_RE.match(fid) and fid not in seen:
            seen.add(fid)
            out.append(f)
    return out


def discovery_dropped_ids(audit, ids) -> list:
    """[(id, one-line reason)] for the discovery ids the round's auditor DROPPED.

    The auditor's `drop` is the disposal the revisers honoured, so a dropped X
    finding is NOT in force: the integration stage must not port or reconcile
    anything for it (the prompt tells it to record `dropped -- not in force`
    when the ledger needs a row).
    """
    if not isinstance(audit, dict):
        return []
    reasons = {}
    for row in (audit.get("dispositions") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("verdict") or "").strip().lower() != "drop":
            continue
        fid = str(row.get("id") or "").strip()
        if fid:
            reasons[fid] = " ".join(str(row.get("reason") or "").split())[:200]
    return [(str(i), reasons[str(i)]) for i in ids if str(i) in reasons]


def round_discovery_dir(ctx: Ctx, r: int):
    """The `guided_review/round2/` directory that owns round r's discovery list.

    Prefers the review session the discovery round actually lives in -- part B
    under a split review (the merge copies the discovery there), the single
    review run otherwise -- and falls back to the archived copy under
    `reports/round<r>_review/`, so a decided or pruned root still seeds the same
    list. None when the round carries no discovery deliverables (a
    formatting-writing scope round, a concern-scoped journal round, or a
    first-generation root).
    """
    try:
        r = int(r)
    except (TypeError, ValueError):
        return None
    cands = []
    try:
        split = review_split_of(ctx) != "off"
    except Exception:                                             # noqa: BLE001
        split = False
    first, second = ((rid_guided_review_b(r), rid_guided_review(r)) if split
                     else (rid_guided_review(r), rid_guided_review_b(r)))
    for rid_ in (first, second):
        rec = ctx.run(rid_)
        # Only a FINISHED review owns a discovery round: a pending/failed
        # sandbox can hold a partial round2/ from an interrupted attempt, and
        # seeding half a list would be worse than seeding none.
        if rec is not None and str(rec.get("status") or "") == "done":
            cands.append(ctx.sandbox_of(rec) / GUIDED_REVIEW_DIR / "round2")
    cands.append(ctx.reports_dir / f"round{r}_review")
    for c in cands:
        if (c / "findings_extra.json").is_file():
            return c
    return None


def round_discovery_seed(ctx: Ctx, r: int) -> dict:
    """Round r's discovery list as the INTEGRATION stage receives it.

    {"source", "findings", "ids", "dropped"}: `source` is the review directory
    the list came from (None when the round has none), `findings` the X-* rows in
    file order, `ids` their ids, `dropped` the [(id, reason)] rows the round's
    auditor dropped (never scored; see `discovery_dropped_ids`).
    """
    src = round_discovery_dir(ctx, r)
    findings = discovery_findings_of(src) if src is not None else []
    ids = [str(f.get("id") or "").strip() for f in findings]
    # The COLD-START REVIEW session is a second producer in the same namespace: its X-9xx
    # rows ride in the frozen list the integration ledger must reconcile, and
    # the same collision rule the merged review copies used is applied here, so
    # every consumer names the same ids.
    probe_findings, remap = cold_start_findings_for_merge(ids, cold_start_findings_rows(ctx, r))
    findings = findings + probe_findings
    ids = ids + [str(f.get("id") or "").strip() for f in probe_findings]
    return {"source": src, "findings": findings, "ids": ids,
            "probe_findings": len(probe_findings), "cold_start_remap": remap,
            "dropped": discovery_dropped_ids(audit_record_of(ctx, r), ids)}


def _copy_bytes_if_different(src: Path, dst: Path) -> bool:
    """Copy one small input file byte-for-byte when it differs (idempotent).

    The source is an agent-writable artifact path: a FILE symlink planted there
    (`findings_extra.md -> /etc/hostname`) must not copy its target into the
    frozen seed, and an unbounded file must not be allocated. Same rule the
    bounded text reader applies (`read_text_bounded`): lstat first, refuse a
    link or a non-regular file, enforce the agent-output byte budget.
    """
    try:
        st = src.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return False
    if st.st_size > MAX_JSON_BYTES:
        return False
    try:
        data = src.read_bytes()
    except OSError:
        return False
    if dst.is_file():
        try:
            if dst.read_bytes() == data:
                return False
        except OSError:
            pass
    dst.parent.mkdir(parents=True, exist_ok=True)

    def do(f) -> None:
        f.write(data)

    # A UNIQUE temporary sibling + os.replace, exactly like every other writer
    # here: a fixed ".tmp" could be renamed into place half-written by a second
    # materializer running at the same time.
    _atomic_write_bytes(tmp_path_for(dst), dst, do, binary=True)
    return True


def seed_discovery_findings(ctx: Ctx, r: int, sb: Path) -> dict:
    """Materialize round r's frozen discovery list under `sb/frozen_discovery/`.

    The list is copied VERBATIM from the review's own `round2/` deliverables
    (`findings_extra.json` + `findings_extra.md`; see DISCOVERY_SEED_DIR), so the
    integration stage reads exactly the list the revision arms merged. A round
    whose discovery round found NO X finding seeds nothing either: an empty list
    carries no id to reconcile, and the sandbox surface stays as small as it can
    be (any stale seed is removed). Returns `round_discovery_seed()` plus the
    seed directory in `dir`.
    """
    seed = round_discovery_seed(ctx, r)
    dst = sb / DISCOVERY_SEED_DIR
    if not seed["ids"]:
        if dst.exists():
            rmtree_force(dst, ignore_errors=True)
        seed["dir"] = None
        return seed
    if seed.get("probe_findings"):
        # The probe findings have no file of their own in the review copy: write
        # the MERGED list (the review's rows plus the cold-start review's X-9xx rows) as the
        # frozen seed, so the integration ledger reconciles the same ids the
        # merged review copies carried.
        base = (read_json(seed["source"] / "findings_extra.json",
                          revive=False, lenient=True)
                if seed["source"] is not None else {})
        base = base if isinstance(base, dict) else {}
        write_json_atomic(dst / "findings_extra.json",
                          {"findings": seed["findings"],
                           "coverage": base.get("coverage") or [],
                           "cold_start_merge": {"rows": seed["probe_findings"],
                                           "id_remap": seed.get("cold_start_remap") or {}}})
        md = ""
        src_md = (seed["source"] / "findings_extra.md") if seed["source"] is not None else None
        if src_md is not None and src_md.is_file():
            # Bounded and no-follow: an agent can make this path a symlink to
            # outside content, and the seed must never carry the target's bytes
            # (read_text_bounded returns None for a link, a FIFO or an
            # over-budget file).
            md = read_text_bounded(src_md) or ""
        cold_start_part = seed["findings"][-int(seed["probe_findings"]):]
        cold_start_md = "\n".join(
            f"- {f.get('id')}: {f.get('location')} -- {f.get('explanation')}"
            for f in cold_start_part)
        md = ((md + "\n\n" if md else "")
              + "## Cold-start review findings (X-9xx, recomputed by the orchestrator)\n\n"
              + (cold_start_md or "(none)") + "\n")
        write_text_atomic(dst / "findings_extra.md", md)
        seed["dir"] = dst if dst.is_dir() else None
        return seed
    for name in DISCOVERY_SEED_FILES:
        src = seed["source"] / name
        if src.is_file():
            _copy_bytes_if_different(src, dst / name)
    seed["dir"] = dst if dst.is_dir() else None
    return seed


def discovery_ledger_missing(ledger_text: str, ids) -> list:
    """The discovery ids an integration ledger never names (whole-token match)."""
    return [str(i) for i in (ids or ()) if not _finding_id_mentioned(str(i), ledger_text or "")]


def discovery_ledger_reconciliation_problems(ledger: Path, ids) -> list:
    """Errors for an integration DIFF_LEDGER.md that does not reconcile every X id.

    Contract: the round's frozen discovery list is reconciled BY ID in the
    integration ledger (ported / kept-base / no-donor-fix), so a resolution one
    of the revise arms made cannot be silently lost in the integrated package.
    """
    ids = [str(i) for i in (ids or ()) if str(i).strip()]
    if not ids:
        return []
    # The ledger is agent-written: refuse a symlink/non-regular or over-budget
    # file exactly like the donor-ledger read in postcheck_integrate (F59).
    text = read_text_bounded(ledger) or ""
    missing = discovery_ledger_missing(text, ids)
    if not missing:
        return []
    return [f"{INTEGRATION_LEDGER_REL} never names {len(missing)} discovery finding id(s) "
            f"({', '.join(missing[:6])}" + (" ...)" if len(missing) > 6 else ")")
            + ": the round's frozen X-* list (frozen_discovery/findings_extra.json) must be "
              "reconciled row by row -- ported, kept-base, or one explicit no-donor-fix row per "
              "id -- so a revision cannot be lost between the revise arm and the integrated "
              "package"]


def critical_findings_input(ctx: Ctx, rec: dict):
    """Number of Critical findings in the frozen review the run consumed (or None).

    Used only as a sanity signal for the self-reported `critical_remaining`
    count (which no longer ranks -- the panel's issue census does): it is the
    count the run started from, not the count that remains, so it never gates a
    run. An arm whose own sandbox has no `guided_review/` copy
    (rewrite, integration) falls back to the round's frozen list, so the
    cross-check below is not revise-only.
    """
    findings = consumed_findings(ctx, rec)
    if not findings:
        findings = round_consumed_findings(ctx, rec.get("round"))
    if not findings and not (ctx.sandbox_of(rec) / FINDINGS_REL).exists():
        return None
    return sum(1 for f in findings
               if str(f.get("severity") or "").strip().lower() in ("critical", "fatal"))


def writing_findings_input(ctx: Ctx, rec: dict):
    """Number of category-2 (writing quality / logic / repetition) findings in
    the frozen review the run consumed (or None).

    The cross-check for the self-reported `writing_remaining` count, exactly as
    `critical_findings_input` is for `critical_remaining` (neither ranks any
    more -- the panel's issue census does): it is the count the run started
    from, not the count that remains, so it never gates a run. The
    category scale is the review skill's (`sweeps.md` -> CLASSIFICATION); the
    defect CLASS those findings map to for scoring is the shared
    DEFECT_CLASS_RULE, which is why this number is a tie-break and not a score.
    """
    findings = consumed_findings(ctx, rec)
    if not findings:
        findings = round_consumed_findings(ctx, rec.get("round"))
    if not findings and not (ctx.sandbox_of(rec) / FINDINGS_REL).exists():
        return None
    return _category2_count(findings)


def _category2_count(findings) -> int:
    """Category-2 (writing quality / logic / repetition) rows in a finding list."""
    total = 0
    for f in findings or ():
        if not isinstance(f, dict):
            continue
        cat = f.get("category")
        if isinstance(cat, str) and cat.strip().isdigit():
            cat = int(cat.strip())
        if cat == 2:
            total += 1
    return total


def round_writing_remaining(ctx: Ctx, r: int):
    """Category-2 findings in the round's frozen review -- the review the round's
    BASE was examined by.

    The version the review inspected has no producing session YET (the pristine
    original in round 1, the incumbent later on), so it cannot self-report
    `writing_remaining` the way every fresh arm does; the review's category-2
    finding count IS its number at the start of the round (nothing has been
    revised from it yet). Prefers the review sandbox (the AUDITED list), then the
    archived `reports/round<r>_review/findings.json` (+ its discovery sibling),
    which the pipeline keeps after a prune. None when neither is readable --
    absence must print as '-', never as a fabricated 0.
    """
    findings = round_consumed_findings(ctx, r)
    if not findings:
        archive = ctx.reports_dir / f"round{int(r)}_review"
        for name in ("findings.json", "findings_extra.json"):
            data = read_json(archive / name, revive=False, lenient=True)
            if isinstance(data, dict):
                findings.extend(f for f in data.get("findings") or []
                                if isinstance(f, dict))
    if not findings:
        return None
    return _category2_count(findings)


def original_writing_remaining(ctx: Ctx, r: int, agg: dict):
    """Open category-2 findings of the PRISTINE ORIGINAL.

    The original is never edited, so the review that examined it (round 1 -- the
    original is that round's base) still describes its writing findings: every
    one of them is open. When the current round's base IS the original the
    current round's review is that same document's review; later rounds fall
    back to round 1's review (sandbox or archive). None when no review of the
    original is readable.
    """
    if str((agg or {}).get("base_rep") or "") == ORIGINAL_ID:
        return round_writing_remaining(ctx, r)
    return round_writing_remaining(ctx, 1)


def tiebreak_selfreport_warnings(ctx: Ctx, rec: dict, summ: dict, warns: list) -> None:
    """Report a self-reported tie-break count that claims ZERO while the round's
    frozen review lists findings of that kind.

    `critical_remaining` and `writing_remaining` are reported and cross-checked
    (the ranking's tie-break is the panel-derived issue census), so an
    unverifiable under-report must at least be visible.
    Only the zero claim is checkable: a non-zero remaining count cannot be
    distinguished from a genuine partial fix, so it is taken at face value.
    `critical_findings_input`/`writing_findings_input` fall back to the round's
    own frozen review, so the check covers the rewrite and integration arms too
    -- they carry no `guided_review/` copy, which is exactly why their self-reports
    used to be unverified.
    """
    if not isinstance(summ, dict):
        return
    n_crit_in = critical_findings_input(ctx, rec)
    if is_int(summ.get("critical_remaining")) and n_crit_in:
        rec["critical_findings_input"] = n_crit_in
        if summ["critical_remaining"] == 0:
            warns.append(f"marker reports critical_remaining=0 while the frozen review lists "
                         f"{n_crit_in} Critical finding(s); that self-reported number is only "
                         f"used to break a statistical tie in the ranking -- verify it in the "
                         f"package's report before trusting the ranking")
    n_writing_in = writing_findings_input(ctx, rec)
    if is_int(summ.get("writing_remaining")) and n_writing_in:
        rec["writing_findings_input"] = n_writing_in
        if summ["writing_remaining"] == 0:
            warns.append(f"marker reports writing_remaining=0 while the frozen review lists "
                         f"{n_writing_in} category-2 (writing quality/logic/repetition) "
                         f"finding(s); that self-reported number is only used to break a "
                         f"statistical tie in the ranking -- verify it in the package's report "
                         f"before trusting the ranking")


def frozen_findings_total(ctx: Ctx, rec: dict):
    """Number of findings in the frozen review the run consumed (None if unreadable).

    Used by the revision postcheck to tell a legitimate all-clean ledger (the
    review carried no findings) from an agent that simply wrote no rows.
    """
    if not (ctx.sandbox_of(rec) / FINDINGS_REL).exists():
        return None
    return len(consumed_findings(ctx, rec))


def frozen_finding_ids(ctx: Ctx, rec: dict) -> list:
    """Ids of the findings this run must resolve (frozen review, AUDITED)."""
    ids = []
    for f in consumed_findings(ctx, rec):
        fid = f.get("id")
        if isinstance(fid, str) and fid.strip() and fid.strip() not in ids:
            ids.append(fid.strip())
    return ids


def revision_ledger_problems(pkg: Path, frozen_ids: list, frozen_total, rel: str = None) -> tuple:
    """(errors, warnings) for one package stage's machine-readable revision ledger.

    The contract this enforces (`revision_report.json`, the deliverable that
    proves no finding was silently dropped): the file exists, it IS a ledger
    (a list of finding rows -- bare or under ANY key, a mapping keyed by finding
    id, or a report object naming the ids; the prompts fix the path and the row
    contract, not the key names), and it NAMES every finding id the stage had to
    resolve. An empty-but-typed ledger is accepted (with a warning) only when the
    review carried no findings at all.

    Shared verbatim by the revise postcheck and by the session's own pre-flight
    (`sandbox_selfcheck`): a reviser that omits an id finds out before it writes
    the marker instead of after a rebuilt 30-minute attempt.
    """
    pkg_rel = rel or f"{pkg.name}/revision_report.json"
    errs, warns = [], []
    path = pkg / "revision_report.json"
    if not path.is_file():
        errs.append(f"{pkg_rel} is missing: it is the revision ledger (one row per finding id, "
                    f"with verdict, rationale and evidence) that proves no finding was silently "
                    f"dropped")
        return errs, warns
    ledger = read_json(path, revive=False, lenient=True)          # agent-written
    if not isinstance(ledger, (list, dict)):
        errs.append(f"{pkg_rel} does not carry the revision ledger (expected a list of finding "
                    f"rows, an object whose rows live under any key, a mapping keyed by finding "
                    f"id, or an id list): it is the deliverable that proves no finding was "
                    f"silently dropped, so the run is retried rather than reported as complete")
        return errs, warns
    if not ledger:
        if frozen_total == 0:
            warns.append(f"{pkg_rel} lists no rows (the frozen review carried no findings); "
                         f"accepted as an all-clean ledger")
        else:
            errs.append(f"{pkg_rel} is EMPTY/unfinished (structured output): it lists no "
                        f"revision row at all -- write the ledger per finding id (verdict, "
                        f"rationale, evidence)")
        return errs, warns
    # A ledger that omits a finding is the "silently dropped" case the
    # deliverable exists to prevent: the row count alone says nothing about
    # WHICH findings were addressed.
    if frozen_ids:
        named = ledger_named_ids(ledger, frozen_ids)
        missing = [i for i in frozen_ids if i not in named]
        if missing:
            errs.append(
                f"{pkg_rel} does not name {len(missing)} of the frozen review's "
                f"{len(frozen_ids)} finding id(s): {', '.join(missing[:6])}"
                + (" ..." if len(missing) > 6 else "")
                + " -- the ledger is one row per finding id (the deliverable that proves no "
                  "finding was silently dropped); an id must appear as structured data (a row's "
                  "id field, a mapping key or an id list), not only in prose")
        # Naming an id is not disposing it: the A1 contract is one row per finding
        # with a verdict (and its rationale). `{"F-001": "", "F-002": "fixed"}`
        # named every id and passed with no verdict on any of them.
        disposed = ledger_disposed_ids(ledger, frozen_ids)
        undisposed = [i for i in frozen_ids if i in named and i not in disposed]
        if undisposed:
            errs.append(
                f"{pkg_rel} names {len(undisposed)} finding id(s) without a VERDICT: "
                f"{', '.join(undisposed[:6])}"
                + (" ..." if len(undisposed) > 6 else "")
                + " -- naming an id (a bare mapping value or an id-only row) is "
                  "not a disposal; every row must carry its documented verdict "
                  "(`confirmed` / `false-positive` / `clarification` / `manual-required` / "
                  "`not-found-in-source`) or final status (`fixed` / `fixed-with-caveat` / "
                  "`placeholder-inserted` / `discarded`) and a rationale")
    return errs, warns


# How deep `ledger_named_ids` walks a machine-readable ledger. Real reports are
# flat or one level deep (rows under a key, a mapping of rows); the bound only
# exists so a pathological payload cannot make the postcheck expensive.
LEDGER_SCAN_DEPTH = 8


def ledger_named_ids(ledger, wanted=()) -> set:
    """Finding ids a revision ledger names as STRUCTURED data.

    The revision contract is "one row per finding id, with verdict, rationale and
    evidence" (paper-revise SKILL.md), but the row container's NAME is not pinned:
    the skill calls it the coverage table, and real runs have written the rows
    under `ledger`, `rows`, `findings`, `coverage`, `coverage_table`, as a
    mapping keyed by finding id, or as a plain id list. Failing a complete ledger
    for choosing one synonym over another is a false failure -- r1_a2_revise and
    r2_a2_revise both failed every attempt that way -- so the gate asks the only
    question it is about: does the payload name every frozen finding id?

    An id counts when it appears as a JSON string that EQUALS a frozen id -- a
    row field's value, a list element, or a mapping key -- at any nesting level.
    Prose that merely mentions an id does not count, so a report object that
    names no finding still fails the gate.
    """
    want = {str(w).strip() for w in (wanted or ()) if str(w).strip()}
    named = set()

    def note(value):
        if isinstance(value, str):
            token = value.strip()
            if token and (not want or token in want):
                named.add(token)

    def visit(node, depth: int):
        if depth > LEDGER_SCAN_DEPTH:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if want and isinstance(key, str) and key.strip() in want:
                    named.add(key.strip())          # {"F-001": {...}}
                if isinstance(value, (dict, list, tuple)):
                    visit(value, depth + 1)
                else:
                    note(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                if isinstance(item, (dict, list, tuple)):
                    visit(item, depth + 1)
                else:
                    note(item)                      # ["F-001", "F-002"]

    visit(ledger, 0)
    return named


# The row's own verdict/final-status field. One is required, and its value must
# be one of the documented A1 values: the R1 VERDICT vocabulary
# (`paper-revise/references/ledger.md`: confirmed / false-positive /
# clarification / manual-required / not-found-in-source) or the FINAL STATUS
# vocabulary that the same ledger records (fixed / fixed-with-caveat /
# clarification / placeholder-inserted / discarded / manual-required). Accepting
# ANY non-empty string let `{"id": "F-001", "verdict": "whatever"}` satisfy the
# disposal gate without recording what happened to the finding. A trailing
# rationale after the verdict word is allowed; the verdict itself is not.
LEDGER_VERDICT_FIELDS = ("verdict", "final_status", "status", "disposition")
LEDGER_VERDICT_RE = re.compile(
    r"(?i)^(confirmed|false[\s_-]*positive|clarification|"
    r"manual[\s_-]*required|not[\s_-]*found[\s_-]*in[\s_-]*source|"
    r"fixed(?:[\s_-]*with[\s_-]*caveat)?|placeholder[\s_-]*inserted|discarded)\b")
LEDGER_VERDICTS = ("confirmed", "false-positive", "clarification",
                   "manual-required", "not-found-in-source",
                   "fixed", "fixed-with-caveat", "placeholder-inserted", "discarded")


def _ledger_row_verdict(row) -> str:
    for key in LEDGER_VERDICT_FIELDS:
        val = re.sub(r"\s+", " ", str((row or {}).get(key) or "").strip())
        if not val:
            continue
        m = LEDGER_VERDICT_RE.match(val)
        if m:
            token = re.sub(r"[\s_]+", "-", m.group(1).lower())
            # `false positive` / `not found in source` normalize onto the
            # documented hyphenated spellings.
            for allowed in LEDGER_VERDICTS:
                if token == allowed:
                    return allowed
            return token
    return ""


def ledger_disposed_ids(ledger, wanted=()) -> set:
    """Finding ids a ledger disposes.

    `ledger_named_ids()` answers "does the payload mention the id?" -- a bare
    mapping value, an id list or an id-only row all passed, so a ledger
    `{"F-001": "", "F-002": null}` satisfied the contract with no verdict at
    all. This reader requires a VERDICT for every structured row: an object whose
    id field equals the frozen id, or a mapping entry `{"F-001": {...verdict...}}`,
    and the verdict must be a documented one (`_ledger_row_verdict`). The one
    non-row shape it accepts is the documented plain ID LIST (`["F-001", ...]`):
    the prompt fixes the row contract but not the container's name, and real
    ledgers have used an id list as their container. Such a list proves no id was
    dropped; it does not pretend to record a per-row verdict.
    """
    want = {str(w).strip() for w in (wanted or ()) if str(w).strip()}
    out = set()

    def row_id(row: dict):
        for key in ("id", "finding", "finding_id", "frozen_id"):
            val = row.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    def visit(node, depth: int, keyed_id: str = ""):
        if depth > LEDGER_SCAN_DEPTH:
            return
        if isinstance(node, dict):
            rid = row_id(node) or keyed_id
            if (not want or rid in want) and _ledger_row_verdict(node):
                out.add(rid)
            for key, value in node.items():
                if isinstance(value, (dict, list, tuple)):
                    visit(value, depth + 1, key.strip() if isinstance(key, str) else "")
        elif isinstance(node, (list, tuple)):
            for item in node:
                if isinstance(item, (dict, list, tuple)):
                    visit(item, depth + 1)
                elif isinstance(item, str) and (not want or item.strip() in want):
                    # A plain ID LIST is the documented "naming" shape (the row
                    # container's name is not pinned); it proves no id was
                    # dropped even though it carries no per-row verdict. The
                    # unsupported shape this gate REJECTS is a mapping key whose
                    # value is a bare string/null (`{"F-001": ""}`): that reads
                    # as a row and records no verdict.
                    out.add(item.strip())

    visit(ledger, 0)
    return out


# ---------------------------------------------------------------------
# Contract helpers shared by the postchecks: the review's coverage table,
# duplicate finding ids, the revision ledger, the judge's grounding artifacts
# and the visual-inspection record (see VISUAL_INSPECTION_RULE).
# ---------------------------------------------------------------------

REQUIRED_REVIEW_CHECKS = tuple([f"M{i}" for i in range(1, 18)] + [f"J{i}" for i in range(1, 5)])
# Contract v2+: the judge must also DISPOSE every frozen check id for every
# opponent, so a sheet that never looked at an opponent is detectable code-side
# (the check ids are provenance-free: they are the journal/format checks, not a
# pipeline history).
JUDGE_COVERAGE_CHECKS = tuple(REQUIRED_REVIEW_CHECKS) + ("M18", "M19", "M20",
                                                         "M21", "M22", "M23", "M24")
JUDGE_DISPOSITIONS = ("clean", "findings", "unable")


# The REVIEW coverage row's documented disposition vocabulary: a finding count,
# a clean basis, a named inability, or an explicit out-of-scope disposal (a
# scoped round, or a check the round honestly declares outside its scope). The
# gate used to accept any non-empty cell that did not start with "not checked",
# so a row of filler ("x", "done") proved a sweep that never ran.
COVERAGE_DISPOSITION_RE = re.compile(
    r"(?i)^(?:\d+\s+finding"
    r"|clean\s*(?:--|—|–)\s*basis\s*:\s*\S"
    r"|unable\s*(?:--|—|–)\s*\S"
    r"|out\s+of\s+scope\b)")


def _coverage_disposition_ok(value) -> bool:
    """True for a REAL review-coverage disposition (see COVERAGE_DISPOSITION_RE)."""
    return bool(COVERAGE_DISPOSITION_RE.match(str(value or "").strip()))


def visual_tools_available() -> bool:
    return bool([label for label, spec in VISUAL_TOOL_PROBES if probe_available(spec)])


RENDER_EVIDENCE_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff")


def render_evidence_files(render_roots) -> list:
    """Rendered page files (PDF/PNG/...) in a version's `work/` scratch.

    The visual-inspection rule tells every session to COPY the document into its
    own `OUT/work/` and render there (`VISUAL_INSPECTION_RULE`), precisely so the
    render cannot touch a read-only input. Scanning the whole package instead
    made any shipped figure asset (`figures/fig1.png`) count as a rendered page,
    so a session could satisfy the "I looked at the pages" gate with a figure it
    never rendered. Only the documented scratch location is evidence; a package
    figure or a shipped PDF is submission content, not proof of inspection.
    """
    out = []
    for root in render_roots or ():
        try:
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                # is_file() follows symlinks: a `work/fig1.png -> figures/fig1.png`
                # link is NOT a rendered page (the visual pass produced nothing).
                if (not p.is_file() or p.is_symlink()
                        or p.suffix.lower() not in RENDER_EVIDENCE_EXTS):
                    continue
                try:
                    parts = p.relative_to(root).parts
                except ValueError:
                    continue
                if parts and parts[0] == "work":
                    # The documented scratch location is the TOP-LEVEL `work/`
                    # of the session's own OUT. A package figure under
                    # `figures/work/` (or any other nested `work/`) is still
                    # submission content, not evidence of a render.
                    out.append(p)
        except OSError:
            continue
    return out


VISUAL_TEMPLATE_DIR = "visual_template"
VISUAL_CACHE_DIRNAME = ".visual_cache"
VISUAL_PAGE_DPI = 110
VISUAL_MAX_RENDER_ATTEMPTS = 2
VISUAL_TEMPLATE_RENDER_TIMEOUT = 300


def _toml_array_at(text: str, start: int):
    """The balanced `[...]` starting at `start`, or None (quoted brackets kept).

    `\\[[^\\]]*\\]` stopped at the FIRST `]`, so ONE argument containing a
    bracket truncated the array, `json.loads` failed and every argument was
    silently dropped -- the server then launched with no args at all, a wrong
    configuration that looked like a successful launch.
    """
    i = start
    while i < len(text) and text[i] in " \t":
        i += 1
    if i >= len(text) or text[i] != "[":
        return None
    j, depth, quote = i, 0, None
    while j < len(text):
        ch = text[j]
        if quote:
            if quote == '"' and ch == "\\":
                j += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            # A TOML comment inside the array may carry a bracket; it is not
            # part of the array (and `args = ["a", # note with ]\n "b"]` must
            # not stop at that bracket).
            nl = text.find("\n", j)
            if nl < 0:
                return None
            j = nl
            continue
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    return None


def _toml_string_at(text: str, i: int):
    """(value, index after) for the TOML string literal at `text[i]`, else None.

    A basic (`"…"`) string decodes TOML's own escapes (`\\"`, `\\\\`, `\\t`,
    `\\uXXXX`); a literal (`'…'`) string does not. An unterminated multi-line
    (triple-quoted) string, an unknown escape or an unterminated literal returns
    None: the caller reports the entry as UNREADABLE instead of launching a
    server with a wrong argv or a Windows path that still carries its double
    backslashes.
    """
    if i >= len(text) or text[i] not in "\"'":
        return None
    q = text[i]
    if text.startswith(q * 3, i):
        return None
    out, j, n = [], i + 1, len(text)
    while j < n:
        c = text[j]
        if c == q:
            return "".join(out), j + 1
        if c == "\\" and q == '"':
            if j + 1 >= n:
                return None
            e = text[j + 1]
            simple = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r",
                      '"': '"', "\\": "\\"}
            if e in simple:
                out.append(simple[e])
                j += 2
                continue
            if e in "uU":
                width = 4 if e == "u" else 8
                hexs = text[j + 2:j + 2 + width]
                if len(hexs) < width or not re.fullmatch(r"[0-9A-Fa-f]+", hexs):
                    return None
                try:
                    out.append(chr(int(hexs, 16)))
                except (ValueError, OverflowError):
                    return None
                j += 2 + width
                continue
            return None                       # unknown escape: refuse, never guess
        out.append(c)
        j += 1
    return None                                # unterminated


def _toml_array_values(raw: str):
    """The string values of a TOML array (`raw`), or None when unreadable.

    `json.loads` is the fast path, but the operator's own `config.toml` may use
    TOML's literal strings (`args = ['node', 'server.js']`) or a trailing comma
    (`args = ["node", "server.js",]`) -- both legal TOML, both a `ValueError`
    for `json.loads`. The fallback scans the bracketed body quote-aware and
    accepts only quoted elements, so a genuinely malformed array still reports
    as unreadable instead of silently dropping every argument. The fallback also
    decodes TOML's string escapes and ignores `#` comments, so a legal entry
    like `args = ["say \\"hi\\"",]` or one carrying a comment is read correctly
    instead of coming back with the backslashes still in it (the server would
    then be launched with a wrong argv).
    """
    try:
        return [str(a) for a in json.loads(raw)]
    except ValueError:
        pass
    except TypeError:
        return None
    body = (raw or "").strip()
    if len(body) < 2 or body[0] != "[" or body[-1] != "]":
        return None
    inner, out, i, n = body[1:-1], [], 0, len(body) - 2
    while i < n:
        ch = inner[i]
        if ch in " \t\r\n,":
            i += 1
            continue
        if ch == "#":
            nl = inner.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        got = _toml_string_at(inner, i)
        if got is None:
            return None
        value, i = got
        out.append(value)
    return out


def _toml_inline_table_at(text: str, start: int):
    """The balanced `{...}` starting at `start`, or None (quoted braces kept)."""
    i = start
    while i < len(text) and text[i] in " \t":
        i += 1
    if i >= len(text) or text[i] != "{":
        return None
    j, depth, quote = i, 0, None
    while j < len(text):
        ch = text[j]
        if quote:
            if quote == '"' and ch == "\\":
                j += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            nl = text.find("\n", j)
            if nl < 0:
                return None
            j = nl
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    return None


def _toml_inline_table_values(raw: str):
    """{key: value} of a TOML inline table, or None when unreadable."""
    body = (raw or "").strip()
    if len(body) < 2 or body[0] != "{" or body[-1] != "}":
        return None
    inner, out, i, n = body[1:-1], {}, 0, len(body) - 2
    while i < n:
        ch = inner[i]
        if ch in " \t\r\n,":
            i += 1
            continue
        if ch == "#":
            nl = inner.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if ch in "\"'":
            got = _toml_string_at(inner, i)
            if got is None:
                return None
            key, i = got
        else:
            m = re.match(r"[A-Za-z0-9_.-]+", inner[i:])
            if not m:
                return None
            key, i = m.group(0), i + len(m.group(0))
        while i < n and inner[i] in " \t":
            i += 1
        if i >= n or inner[i] != "=":
            return None
        i += 1
        while i < n and inner[i] in " \t":
            i += 1
        if i < n and inner[i] in "\"'":
            got = _toml_string_at(inner, i)
            if got is None:
                return None
            value, i = got
        else:
            m = re.match(r"[^\s,]+", inner[i:])
            if not m:
                return None
            value, i = m.group(0), i + len(m.group(0))
        out[str(key)] = str(value)
    return out


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
    m = header.search(text)
    if not m:
        return {}
    rest = text[m.end():]
    nxt = re.search(r"^\s*\[", rest, re.MULTILINE)
    body = rest[:nxt.start()] if nxt else rest
    cm = re.search(r"^[ \t]*command[ \t]*=[ \t]*", body, re.MULTILINE)
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
    am = re.search(r"^\s*args\s*=\s*", body, re.MULTILINE)
    if am:
        raw = _toml_array_at(body, am.end())
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
    wm = re.search(r"^[ \t]*cwd[ \t]*=[ \t]*", body, re.MULTILINE)
    if wm:
        cwd_got = _toml_string_at(body, wm.end())
        if cwd_got is None:
            return {}
        spec["cwd"] = os.path.expanduser(cwd_got[0])
    em = re.search(r"^[ \t]*env[ \t]*=[ \t]*", body, re.MULTILINE)
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
        eh = env_header.search(text)
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


def mcp_stdio_tool_call(spec: dict, tool: str, arguments: dict,
                        timeout: float = 300) -> dict:
    """Drive one configured MCP stdio server for ONE tool call, then stop it.

    Minimal newline-delimited JSON-RPC: `initialize` ->
    `notifications/initialized` -> `tools/call`. The orchestrator seeds the
    venue-template renders itself, so it uses the SAME first-choice converter
    the agent prompts mandate (the operator's docx-converter MCP tool, i.e.
    Microsoft Word through PowerShell interop) instead of silently falling back
    to a lower-fidelity shim.
    """
    argv = [str(spec.get("command") or ""), *[str(a) for a in spec.get("args") or []]]
    if not argv[0]:
        return {"ok": False, "error": "the MCP server entry names no command"}
    launch_env = None
    if spec.get("env"):
        launch_env = dict(os.environ, **{str(k): str(v) for k, v in spec["env"].items()})
    launch_cwd = spec.get("cwd") or None
    try:
        # Its OWN process group: a timeout must kill the whole chain
        # (bash -> PowerShell -> Word), not only the node wrapper (F29).
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1,
                                encoding="utf-8", errors="replace",
                                env=launch_env, cwd=launch_cwd,
                                **_render_popen_kwargs())
    except OSError as e:
        return {"ok": False, "error": f"the MCP server would not start: {e}"}
    # A misbehaving MCP server must not grow memory without bound: queue only a
    # bounded number of lines/bytes and record a flood instead of blocking the
    # producer or allocating until OOM (the 2026-10-28 audit's F80).
    MAX_MCP_LINES = 4096
    MAX_MCP_LINE_BYTES = 1 << 20
    MAX_MCP_QUEUED_BYTES = 8 << 20      # TOTAL bytes waiting in the queue
    MAX_MCP_STDERR_KEEP = 4096          # per-line tail kept for the error report
    lines = queue.Queue(maxsize=MAX_MCP_LINES)
    queued_bytes = [0]
    queue_lock = threading.Lock()
    flooded = threading.Event()
    stderr_flooded = threading.Event()
    err_tail = deque(maxlen=6)

    def pump(stream) -> None:
        try:
            while True:
                line = stream.readline(MAX_MCP_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_MCP_LINE_BYTES:
                    flooded.set()
                    continue
                with queue_lock:
                    if queued_bytes[0] + len(line) > MAX_MCP_QUEUED_BYTES:
                        flooded.set()
                        continue
                    try:
                        lines.put_nowait(line)
                    except queue.Full:
                        flooded.set()
                    else:
                        queued_bytes[0] += len(line)
        finally:
            try:
                lines.put_nowait(None)
            except queue.Full:
                pass

    def pump_err(stream) -> None:
        try:
            while True:
                line = stream.readline(MAX_MCP_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_MCP_LINE_BYTES:
                    stderr_flooded.set()
                    continue
                err_tail.append(line[-MAX_MCP_STDERR_KEEP:])
        except (OSError, ValueError):
            pass

    threading.Thread(target=pump, args=(proc.stdout,), daemon=True).start()
    threading.Thread(target=pump_err, args=(proc.stderr,), daemon=True).start()

    def stop_tree() -> None:
        """Kill the server AND its grandchildren (F29)."""
        if os.name == "nt":
            if proc.poll() is None:
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, timeout=30)
                with contextlib.suppress(OSError):
                    proc.kill()
        else:
            # killpg by the WRAPPER's pid works even after the wrapper exited:
            # start_new_session made that pid the group id.
            with contextlib.suppress(OSError, ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            with contextlib.suppress(OSError):
                proc.kill()

    def failure(prefix: str) -> dict:
        """`prefix` plus what the SERVER itself said, when saying nothing.

        The handshake used to discard the server's stderr, so a server that
        died on startup (a missing npm dependency -- the 2026-10-14 state of
        the docx-compare/docx-converter copies) surfaced as the bare "did not
        answer initialize()". One bounded wait drains the pipe, and the tail
        travels into the manifest, so the operator sees the real error.
        """
        # Stop the tree BEFORE the 2-second drain: waiting first let a
        # grandchild (bash -> PowerShell -> Word) keep running and writing for
        # the whole diagnostic window (F29).
        stop_tree()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2)
        time.sleep(0.05)
        text = "".join(err_tail).strip().replace("\n", " | ")
        bits = [prefix]
        if proc.returncode is not None:
            bits.append(f"the server exited with code {proc.returncode}")
        if text:
            bits.append(f"stderr: {text[-300:]}")
        if flooded.is_set():
            bits.append("the server flooded its stdout; excess output was dropped")
        if stderr_flooded.is_set():
            bits.append("the server flooded its stderr; excess output was dropped")
        return {"ok": False, "error": "; ".join(bits)}

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def wait_for(rid: int, deadline: float):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                line = lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if line is None:
                return None
            with queue_lock:
                if queued_bytes[0]:
                    queued_bytes[0] = max(0, queued_bytes[0] - len(line))
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == rid:
                return msg

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "paper_pipeline", "version": VERSION}}})
        init = wait_for(1, time.monotonic() + min(float(timeout), 60.0))
        if init is None:
            return failure("the MCP server did not answer initialize()")
        if init.get("error"):
            return {"ok": False, "error": f"initialize() failed: {init['error']}"}
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": tool, "arguments": arguments}})
        rep = wait_for(2, time.monotonic() + float(timeout))
        if rep is None:
            return failure(f"the MCP tool {tool} did not answer within {int(timeout)}s")
        if rep.get("error"):
            return {"ok": False, "error": f"the MCP tool {tool} failed: {rep['error']}"}
        out = {"ok": True, "result": rep.get("result") or {}}
        flood_warnings = []
        if flooded.is_set():
            flood_warnings.append("the server flooded its stdout; excess output was dropped")
        if stderr_flooded.is_set():
            flood_warnings.append("the server flooded its stderr; excess output was dropped")
        if flood_warnings:
            out["warnings"] = flood_warnings
        return out
    except (OSError, ValueError) as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        with contextlib.suppress(OSError):
            proc.stdin.close()
        stop_tree()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def mcp_convert_docx_to_pdf(spec: dict, docx: Path, timeout: float = 300) -> dict:
    """Convert one DOCX through the operator's docx-converter MCP tool.

    The tool writes `<stem>.pdf` NEXT TO the file it is handed, so callers pass
    a disposable copy and read-only inputs never change.
    """
    rep = mcp_stdio_tool_call(spec, DOCX_MCP_TOOL, {"docxPath": str(docx)}, timeout=timeout)
    if not rep.get("ok"):
        return rep
    result = rep.get("result") or {}
    if result.get("isError"):
        text = " ".join(str(c.get("text") or "") for c in result.get("content") or []
                        if isinstance(c, dict))
        return {"ok": False, "error": f"the MCP tool reported an error: {text[:200]}"}
    pdf = Path(docx).with_suffix(".pdf")
    if not pdf.is_file() or pdf.stat().st_size == 0:
        return {"ok": False,
                "error": f"the MCP tool returned success but wrote no PDF next to {Path(docx).name}"}
    return {"ok": True, "pdf": pdf}


def docx_compare_mcp_spec() -> dict:
    """The configured `docx-compare` MCP server entry, {} when it is unusable.

    Being configured is not enough: the entry has to name a command that is
    still on this machine (the same probe `mcp_server_configured` applies). An
    empty dict sends the redline chain to its next backend and is reported in
    the manifest, so a missing server is never mistaken for a failed compare.
    """
    if not mcp_server_configured(DOCX_COMPARE_MCP_SERVER):
        return {}
    spec = mcp_server_spec(DOCX_COMPARE_MCP_SERVER)
    cmd = str(spec.get("command") or "")
    if not cmd:
        return {}
    # `~` IS expanded here, like the sibling probe in `mcp_server_configured`:
    # a home-relative command used to read as "not installed" and silently
    # vanish from the redline chain.
    present = (Path(os.path.expanduser(cmd)).exists() if cmd.startswith(("/", "~"))
               else bool(shutil.which(cmd)))
    return spec if present else {}


def mcp_compare_docx(spec: dict, base: Path, revised: Path, out: Path,
                     timeout: float = 900) -> dict:
    """Write a Word-native tracked-changes redline through the compare MCP tool.

    The tool drives `docxcompare.sh` -> PowerShell -> `Word.Application
    .CompareDocuments`; it is handed the real base/revised paths and an explicit
    output path (`<pipeline-managed auxiliary>.docx`), never an input path as its
    output. Success is "the tool answered AND `out` is a readable OOXML package"
    -- the same bar every other redline backend is held to.
    """
    rep = mcp_stdio_tool_call(spec, DOCX_COMPARE_MCP_TOOL,
                              {"originalPath": str(base), "revisedPath": str(revised),
                               "outputPath": str(out)}, timeout=timeout)
    if not rep.get("ok"):
        return {"ok": False, "error": rep.get("error")}
    result = rep.get("result") or {}
    if result.get("isError"):
        text = " ".join(str(c.get("text") or "") for c in result.get("content") or []
                        if isinstance(c, dict))
        return {"ok": False, "error": f"the MCP tool reported an error: {text[:300]}"}
    if not out.is_file() or out.stat().st_size == 0:
        return {"ok": False,
                "error": f"the MCP tool returned success but wrote no output at {out}"}
    return {"ok": True}


def visual_renderer_choices() -> list:
    """Every usable DOCX->PDF renderer, in the order the prompts mandate.

    The operator's docx-converter MCP tool comes FIRST (Microsoft Word through
    PowerShell interop, the highest-fidelity renderer); `docx2pdf.sh` -- the
    script that MCP tool drives internally -- is the fallback when the server is
    not installed or cannot start, and LibreOffice is the last resort.
    """
    out = []
    if mcp_server_configured(DOCX_MCP_SERVER):
        spec = mcp_server_spec(DOCX_MCP_SERVER)
        cmd = str(spec.get("command") or "")
        present = (Path(os.path.expanduser(cmd)).exists() if cmd.startswith(("/", "~"))
                   else bool(shutil.which(cmd)))
        if cmd and present:
            out.append((f"mcp:{DOCX_MCP_SERVER}", spec))
    here = Path(__file__).resolve().parent
    for cand in (here / "docx2pdf.sh", shutil.which("docx2pdf.sh")):
        if cand and Path(cand).is_file() and os.access(str(cand), os.X_OK):
            out.append(("word", Path(cand)))
            break
    for exe in ("soffice", "libreoffice"):
        p = shutil.which(exe)
        if p:
            out.append(("libreoffice", Path(p)))
            break
    return out


def visual_renderer_choice() -> tuple:
    """(name, payload) for the BEST renderer: MCP first, then Word, then LibreOffice."""
    choices = visual_renderer_choices()
    return choices[0] if choices else ("none", None)


def _pdf_page_count(pdf: Path) -> int:
    exe = shutil.which("pdfinfo")
    if exe:
        try:
            out = subprocess.run([exe, str(pdf)], capture_output=True, timeout=60).stdout
            m = re.search(rb"^Pages:\s*(\d+)", out or b"", re.M)
            if m:
                return int(m.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
    return 0


def _child_output(raw) -> str:
    """A child process's stdout/stderr as text, never fatal on a non-UTF-8 locale.

    The renderers this pipeline drives are Windows-interop shims; their
    diagnostics arrive in the console's own code page, and decoding those as
    strict UTF-8 must not turn a rendered PDF into a failed session.
    """
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw or ""


def _page_png_names(out_dir: Path, stem: str) -> list:
    """The page PNGs pdftoppm wrote for `stem`, in PAGE order.

    `stem` is matched literally (a stem like `Papers[1]` is not a glob
    character class), and the trailing page number sorts numerically so
    page-10 follows page-2.
    """
    def key(name: str):
        m = re.search(r"-(\d+)\.png$", name)
        return (int(m.group(1)) if m else 10 ** 9, name)
    # EXACT `stem-<page>.png`: the old prefix test also kept another document's
    # pages when `main.tex` and `main.docx` shared an output directory
    # (`main-docx-1.png`), mixing two documents into one visual pass.
    pat = re.compile(r"^" + re.escape(stem) + r"-\d+\.png$", re.I)
    return sorted((p.name for p in Path(out_dir).iterdir()
                   if p.is_file() and pat.match(p.name)), key=key)


def _render_popen_kwargs() -> dict:
    """Run the renderer in its own process group (timeout must kill the tree)."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _kill_render_tree(proc) -> None:
    """Kill a timed-out Word/LibreOffice renderer AND its grandchildren."""
    if os.name == "nt":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
    else:
        with contextlib.suppress(OSError, ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _run_render_subprocess(argv, timeout, cwd=None):
    """`subprocess.run` with a timeout that kills the renderer's whole tree.

    stdout/stderr go to TEMPORARY FILES and are read back only up to
    MAX_TOOL_OUTPUT_BYTES: the renderer is driven by an untrusted package, so a
    flood must fail the render instead of allocating without bound (F25).
    """
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        proc = subprocess.Popen(
            [str(a) for a in argv], stdout=out_f, stderr=err_f, stdin=subprocess.DEVNULL,
            cwd=cwd, **_render_popen_kwargs())
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_render_tree(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=30)              # reap; never leave a zombie
            raise
        out_f.seek(0, os.SEEK_END)
        err_f.seek(0, os.SEEK_END)
        out_size, err_size = out_f.tell(), err_f.tell()
        if out_size > MAX_TOOL_OUTPUT_BYTES or err_size > MAX_TOOL_OUTPUT_BYTES:
            raise ToolOutputOverBudget(
                f"renderer output over {MAX_TOOL_OUTPUT_BYTES} bytes "
                f"(stdout={out_size}, stderr={err_size})")
        out_f.seek(0)
        err_f.seek(0)
        out = out_f.read(MAX_TOOL_OUTPUT_BYTES + 1).decode("utf-8", "replace")
        err = err_f.read(MAX_TOOL_OUTPUT_BYTES + 1).decode("utf-8", "replace")
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def render_docx_visual(docx: Path, out_dir: Path, renderer=None,
                       timeout: float = 900, page_images: bool = True) -> dict:
    """Render ONE DOCX to PDF + page PNGs under `out_dir`.

    `renderer` pins ONE renderer (tests, retries); None tries the whole choice
    list in order -- the docx-converter MCP tool first, then docx2pdf.sh, then
    LibreOffice -- because pagination, fonts and headers/footers differ between
    Word and LibreOffice. The renderer that actually produced the PDF, and any
    lower-fidelity fallbacks, are recorded so the agents and the decision report
    can state them.

    `page_images=False` skips the page-PNG pass (the persistent PDF store of
    `run_pdf_conversion()` needs the PDF only; the agents' visual passes keep
    the default).
    """
    if renderer is None:
        choices = visual_renderer_choices()
        if not choices:
            return {"ok": False, "renderer": "none",
                    "error": "no DOCX->PDF renderer is installed (docx-converter MCP tool, "
                             "docx2pdf.sh or LibreOffice)"}
        failures = []
        for cand in choices:
            # The fallback loop must carry the caller's policy: dropping them
            # here silently restored the 900 s default and re-enabled the page
            # PNGs that `page_images=False` exists to skip.
            res = render_docx_visual(docx, out_dir, cand, timeout=timeout,
                                     page_images=page_images)
            if res.get("ok"):
                if failures:
                    res["fallbacks"] = failures
                return res
            failures.append({"renderer": cand[0], "error": res.get("error")})
        return {"ok": False, "renderer": choices[0][0], "attempts": failures,
                "error": "no renderer produced a PDF: "
                         + "; ".join(f"{f['renderer']}: {f['error']}" for f in failures)[:300]}
    name, exe = renderer
    out_dir.mkdir(parents=True, exist_ok=True)
    if name == "none" or exe is None:
        return {"ok": False, "renderer": "none", "error": "no DOCX->PDF renderer on PATH"}
    tmp = Path(tempfile.mkdtemp(prefix="vrender_", dir=str(out_dir)))
    try:
        src = tmp / docx.name
        shutil.copy2(docx, src)
        proc = None
        if name.startswith("mcp:"):
            conv = mcp_convert_docx_to_pdf(exe, src, timeout=timeout)
            if not conv.get("ok"):
                return {"ok": False, "renderer": name, "error": conv.get("error")}
            pdf = Path(conv["pdf"])
        elif name == "word":
            try:
                proc = _run_render_subprocess([str(exe), str(src)], timeout=timeout,
                                              cwd=str(tmp))
            except ToolOutputOverBudget as exc:
                return {"ok": False, "renderer": name, "error": str(exc)}
            pdf = src.with_suffix(".pdf")
        else:
            profile = tmp / "lo_profile"
            try:
                proc = _run_render_subprocess(
                    [str(exe), "--headless",
                     f"-env:UserInstallation=file://{profile}",
                     "--convert-to", "pdf", "--outdir", str(tmp), str(src)],
                    timeout=timeout)
            except ToolOutputOverBudget as exc:
                return {"ok": False, "renderer": name, "error": str(exc)}
            pdf = tmp / (src.stem + ".pdf")
        if not pdf.is_file() or pdf.stat().st_size == 0:
            detail = (_child_output(getattr(proc, "stderr", None))
                      + _child_output(getattr(proc, "stdout", None))) \
                .strip().replace("\n", " ")[:200]
            return {"ok": False, "renderer": name,
                    "error": f"the renderer produced no PDF: {detail}"}
        final_pdf = out_dir / (docx.stem + ".pdf")
        shutil.move(str(pdf), str(final_pdf))
        pages = _pdf_page_count(final_pdf)
        pngs = []
        warnings = []
        if page_images and shutil.which("pdftoppm"):
            prefix = out_dir / docx.stem
            try:
                subprocess.run(["pdftoppm", "-r", str(VISUAL_PAGE_DPI), "-png",
                                str(final_pdf), str(prefix)],
                               capture_output=True, timeout=600)
            except (OSError, subprocess.SubprocessError) as e:      # noqa: BLE001
                # The PDF has already been moved into place: a page-image
                # timeout must not turn a successful render into a failure and
                # send the chain to a lower-fidelity renderer.
                warnings.append(f"page images not produced ({type(e).__name__}: {e})")
            # Page numbers sort numerically (page-10 after page-2), and the
            # stem is matched literally: a stem like `Papers[1]` made the old
            # glob a character class and returned zero pages.
            pngs = _page_png_names(out_dir, docx.stem)
            pages = pages or len(pngs)
        result = {"ok": True, "renderer": name, "pdf": final_pdf.name,
                  "pages": pages or 0, "pngs": pngs}
        if warnings:
            result["warnings"] = warnings
        return result
    except (OSError, subprocess.SubprocessError) as e:                  # noqa: BLE001
        return {"ok": False, "renderer": name, "error": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _cached_visual_render(cache: Path, choice: str) -> tuple:
    """(reusable cached record or None, render attempts already made).

    A successful render is reused. A FAILED one is retried until
    VISUAL_MAX_RENDER_ATTEMPTS: one flaked Word/COM call must not silently
    disable the template comparison for the whole root, and a renderer that
    cannot work here must not be re-driven once per session either. `choice` is
    the FIRST renderer the machine offers (the MCP tool); a record made by a
    lower-fidelity fallback of the same choice is still reusable.
    """
    try:
        stored = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, 0
    if not isinstance(stored, dict) \
            or (stored.get("choice") or stored.get("renderer")) != choice:
        return None, 0
    try:
        attempts = int(stored.get("attempts") or 1)
    except (TypeError, ValueError):
        attempts = 1
    if stored.get("ok") or attempts >= VISUAL_MAX_RENDER_ATTEMPTS:
        return stored, attempts
    return None, attempts


def seed_template_visuals(ctx: Ctx, sb: Path) -> dict:
    """Render the venue's official Word templates into `sb/visual_template/`.

    Cached per root by template digest, so one Word render serves every session.
    Venue-level and identical for every session -- no provenance, so the judge
    sandboxes may receive it (unlike package renders, which stay blinding-safe
    because the judge renders its own target/field views). The renderer chain is
    the operator's own order: the docx-converter MCP tool first, docx2pdf.sh
    next, LibreOffice last.
    """
    tpls = venue_word_templates(ctx)
    if not tpls:
        return {}
    choices = visual_renderer_choices()
    choice = choices[0][0] if choices else "none"
    manifest = {"renderer": choice, "choice": choice, "documents": []}
    out = sb / VISUAL_TEMPLATE_DIR
    for role, path in sorted(tpls.items()):
        try:
            digest = sha256_file(path)
        except OSError:
            continue
        cache = ctx.root / VISUAL_CACHE_DIRNAME / digest[:2] / digest
        rec, attempts = _cached_visual_render(cache, choice)
        if rec is None:
            cache.mkdir(parents=True, exist_ok=True)
            # a retry after a failed attempt must not inherit its partial pages
            for stale in list(cache.glob("*.pdf")) + list(cache.glob("*.png")):
                with contextlib.suppress(OSError):
                    stale.unlink()
            r = render_docx_visual(path, cache, None,
                                    timeout=VISUAL_TEMPLATE_RENDER_TIMEOUT)
            rec = {"ok": r.get("ok"), "renderer": r.get("renderer"), "choice": choice,
                   "pages": r.get("pages", 0), "pdf": r.get("pdf"),
                   "pngs": r.get("pngs") or [], "error": r.get("error"),
                   "fallbacks": r.get("fallbacks"),
                   "source": str(path), "sha256": digest, "attempts": attempts + 1}
            write_json_atomic(cache / "manifest.json", rec)
        dest = out / role
        dest.mkdir(parents=True, exist_ok=True)
        if rec.get("pdf") and (cache / rec["pdf"]).is_file():
            shutil.copy2(cache / rec["pdf"], dest / rec["pdf"])
        for png in rec.get("pngs") or []:
            if (cache / png).is_file():
                shutil.copy2(cache / png, dest / Path(png).name)
        manifest["documents"].append({
            "role": role, "source": Path(path).name, "sha256": digest,
            "renderer": rec.get("renderer"), "pages": rec.get("pages"),
            "pdf": rec.get("pdf"), "ok": rec.get("ok"), "error": rec.get("error")})
    if manifest["documents"]:
        rendered = [d.get("renderer") for d in manifest["documents"] if d.get("ok")]
        manifest["renderer"] = rendered[0] if rendered else choice
        write_json_atomic(out / "manifest.json", manifest)
    return manifest


def word_docs_present(paths) -> bool:
    for p in paths:
        try:
            if not p.is_dir():
                continue
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in (".doc", ".docx"):
                    return True
        except OSError:
            continue
    return False


def check_visual_artifact(path: Path, label: str, errs: list, warns: list,
                          render_roots=None, sandbox: Path = None) -> None:
    """The visual pass must be RECORDED -- and EVIDENCED.

    A .docx cannot be visually inspected by reading it (see VISUAL_INSPECTION_RULE),
    so the artifact must list the rendered pages that were actually looked at --
    or state explicitly that rendering was impossible and hand the check to the
    author. Silence is not an acceptable outcome.

    `render_roots` is where the converted pages may live (the version corpus for
    revise/integration, guided_review/ for the review, judge_review/ for a judge). When the
    artifact claims the pass was done and a renderer exists on this machine, at
    least one rendered file (PDF/PNG/...) must be present -- otherwise the claim
    is only a sentence, which is exactly what the prompt forbids ("Never write
    'visually inspected' without having seen rendered pages"). The documented
    escape hatch stays open: an artifact that says the pages were NOT visually
    verified is accepted with a warning and the manual step.
    """
    if not path.is_file():
        errs.append(f"{label} is missing: the prompts require a visual-inspection record "
                    f"(convert the Word documents to PDF, render the pages to images and LOOK "
                    f"at them). If that is impossible here, the file must say so explicitly "
                    f"and hand the check to the author -- an unrecorded visual pass is a "
                    f"failed deliverable, because reading a .docx is not a visual inspection")
        return
    _raw = read_text_bounded(path)
    if _raw is None:
        errs.append(f"{label} could not be read (unreadable, non-regular, or over the "
                    f"agent-output byte budget)")
        return
    text = _raw.lower()
    if not visual_tools_available():
        warns.append(f"{label}: no PDF renderer was detected on this machine, so the visual "
                     f"pass can only be partial; confirm the artifact's limitation note")
    elif render_roots:
        # The claim is on record and a renderer exists: require the rendered pages
        # themselves. Absence is the failure mode this closes (an artifact that
        # asserts a full pass over pages nobody converted).
        not_verified_in_text = "not visually verified" in text
        if not not_verified_in_text and not render_evidence_files(render_roots):
            roots = ", ".join(str(r) for r in render_roots)
            errs.append(f"{label} claims the documents were visually inspected, but no rendered "
                        f"page (PDF/PNG/...) exists under: {roots}. Convert the documents, render "
                        f"the pages and LOOK at them (VISUAL_INSPECTION_RULE), or state "
                        f"explicitly in the artifact that they were NOT visually verified and "
                        f"hand the rendering step to the author")
    if "not visually verified" in text:
        warns.append(f"{label}: the agent reports that (some) documents were NOT visually "
                     f"verified -- the human gate must complete those pages")
    if sandbox is not None and "not visually verified" not in text:
        tpl_manifest = sandbox / VISUAL_TEMPLATE_DIR / "manifest.json"
        if tpl_manifest.is_file():
            try:
                tpl = json.loads(tpl_manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                tpl = {}
            docs = [d for d in (tpl.get("documents") or []) if d.get("ok")]
            if docs:
                missing = []
                for d in docs:
                    name = str(d.get("source") or "").lower()
                    pages = str(d.get("pages") or "")
                    if name and name not in text:
                        missing.append(name)
                    elif pages and not re.search(
                            rf"\b{re.escape(pages)}[\s-]+pages?\b", text, re.I):
                        missing.append(f"{name} ({pages} page(s))")
                if "template" not in text:
                    missing.append("a template-comparison section")
                if missing:
                    errs.append(f"{label}: the code-seeded venue-template render is present "
                                f"(renderer {tpl.get('renderer')}), but the artifact does not "
                                f"compare against it: missing {', '.join(missing[:4])}")


def cover_letter_row_survival_problems(ctx: Ctx, sb: Path) -> list:
    """The review table cannot DELETE a code-proven FMT-CL1 row.

    The disposition gate forbids closing the row `OK` without the journal's own
    quoted override; this closes the remaining escape -- dropping the row. The
    same policy the seed used is re-applied to `base/`, so every letter the
    code proves is manuscript-template-formatted still needs a row in the M20
    table, whatever the reviewer writes in it.
    """
    if ctx is None:
        return []
    try:
        policy = format_policy_of(ctx)
        info = scan_format_in_sources([(sb / "base", "", CORPUS_EXCLUDE_TOP)], policy=policy)
    except Exception as e:                                     # noqa: BLE001 -- never gate on scan
        # A skipped scan is UNKNOWN, not clean: returning [] let a review that
        # deleted every seeded FMT-CL1 row ship whenever the scan crashed.
        return [f"{GUIDED_REVIEW_DIR}/artifacts/M20_formatting.md cannot be verified: the code-side "
                f"FMT-CL1 scan FAILED ({type(e).__name__}: {e}); the row state is UNKNOWN, "
                f"not clean"]
    want = {str(r.get("document") or "").strip()
            for r in (info.get("rows") or [])
            if str(r.get("rule") or "").upper() in COVER_LETTER_STAMP_RULES}
    want = {w for w in want if w}
    if not want:
        return []
    path = sb / GUIDED_REVIEW_DIR / "artifacts" / "M20_formatting.md"
    text = read_text_bounded(path)
    if text is None:
        return [f"{GUIDED_REVIEW_DIR}/artifacts/M20_formatting.md is missing or unreadable: the "
                f"code-side scan proves {len(want)} FMT-CL1 cover-letter row(s) "
                f"({', '.join(sorted(want)[:3])}) the review must dispose"]
    # Rows are per DOCUMENT, not per mention: three rows about one letter do not
    # dispose the other two letters.
    rows_cl = [ln for ln in text.splitlines()
               if ln.strip().startswith("|") and "FMT-CL1" in ln.upper()]
    named = {w for w in want if any(w.lower() in ln.lower() for ln in rows_cl)}
    if named == want or (len(want) == 1 and rows_cl):
        # With one code-proven letter a single FMT-CL1 row disposes it, even
        # when the table's own document column carries the name implicitly.
        return []
    missing = sorted(want - named)
    return [f"{GUIDED_REVIEW_DIR}/artifacts/M20_formatting.md carries FMT-CL1 row(s) for "
            f"{len(named)} of the {len(want)} cover letter(s) the code-side scan proves "
            f"({', '.join(missing[:3])} missing): a seeded row cannot be deleted -- dispose "
            f"every cover letter the scan flags (an M20 finding, or OK with the journal's own "
            f"quoted override)"]


# =====================================================================
# THE DISCOVERY ROUND'S CONTRACT (D0-D5)
#
# `references/discovery.md` defines the round; until now nothing verified it.
# These helpers turn its deliverables into an auditable contract: the
# enumerations exist, every row carries a disposition, the X-* findings have
# the standard finding shape, proposals are sweeps.md-shaped and numbered from
# M37, and the previous round's proposals are re-probed instead of vanishing.
# They verify STRUCTURE only -- the truth of a disposition stays the auditor's
# and the revisers' job.
# =====================================================================

def _discovery_nonempty(p: Path) -> bool:
    """True when `p` is a regular file with at least one byte."""
    try:
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def _discovery_rows(path: Path) -> list:
    """Every data row of every markdown table block of one discovery artifact."""
    return [r for block in parse_markdown_blocks(path) for r in block["rows"]]


def _row_text(row) -> str:
    """One table row's cells flattened for keyword reads (whitespace-normalized)."""
    return " ".join(" ".join(str(v or "").split()) for v in row.values())


def _discovery_status_cells(row) -> list:
    """(token, rest) for every cell that STARTS with a probe status token.

    D2/D3's probe rows carry a status cell (`pending` / `executed` /
    `unable -- reason`), and D3's clean closure starts `no anomalies -- checked:
    <locations>`. Reading the CELL START keeps prose that merely mentions
    "pending" from being read as the row's own status.
    """
    out = []
    for v in row.values():
        cell = " ".join(str(v or "").split())
        low = cell.lower()
        for token in _DISCOVERY_STATUS_TOKENS:
            if low.startswith(token):
                out.append((token, cell[len(token):].strip(" :;,-—–")))
                break
    return out


def _unable_reason_present(rest: str) -> bool:
    """True when an `unable -- ...` status states a reason (>= 2 words).

    The token list is case-insensitive: an all-caps reason ("HPC QUOTA
    EXCEEDED") is exactly as usable as a lowercase one, and the old
    `[0-9a-z]+` read it as no reason at all and failed a valid session.
    """
    return len(re.findall(r"[0-9A-Za-z]+", rest or "")) >= 2


def discovery_gap_summary(sb: Path) -> dict:
    """{rows, covered, uncovered, unmarked} of guided_review/round2/gap_table.md."""
    covered = uncovered = unmarked = 0
    rows = _discovery_rows(sb / GUIDED_REVIEW_DIR / "round2" / "gap_table.md")
    for r in rows:
        low = _row_text(r).lower()
        # The UNCOVERED spellings D1's own prose uses: "UNCOVERED", "not covered",
        # the hyphenated "not-covered"/"not-yet-covered", "partially covered",
        # "covered by nothing" and "no check". Reading the hyphenated forms as
        # COVERED made a table whose every UNCOVERED row is spelled that way fail
        # with the wrong message ("marks every row COVERED ... has not run D1")
        # and, worse, never required a probe for those rows.
        if _DISCOVERY_UNCOVERED_RE.search(low):
            uncovered += 1
        elif re.search(r"\bcovered\b", low):
            covered += 1
        else:
            unmarked += 1
    return {"rows": len(rows), "covered": covered, "uncovered": uncovered,
            "unmarked": unmarked}


def discovery_probe_ids(sb: Path) -> list:
    """The P2-* probe ids declared in guided_review/round2/probes.md, in file order."""
    ids = []
    for r in _discovery_rows(sb / GUIDED_REVIEW_DIR / "round2" / "probes.md"):
        m = DISCOVERY_PROBE_ID_RE.search(_row_text(r))
        if m and m.group(0) not in ids:
            ids.append(m.group(0))
    return ids


def discovery_probe_result_ids(sb: Path) -> list:
    """The P2-* probe ids recorded in guided_review/round2/probe_results.md."""
    ids = []
    for r in _discovery_rows(sb / GUIDED_REVIEW_DIR / "round2" / "probe_results.md"):
        m = DISCOVERY_PROBE_ID_RE.search(_row_text(r))
        if m and m.group(0) not in ids:
            ids.append(m.group(0))
    return ids


def prior_proposal_ids(sb: Path) -> list:
    """Sweep ids proposed by the PREVIOUS round (prior_round/new_sweeps.md).

    `None` when the file EXISTS but cannot be read (permissions, a link/FIFO,
    or over the byte budget): that is UNKNOWN, not "the prior round proposed
    nothing", and the convergence gate must say so instead of going quiet
    (F73).
    """
    path = sb / "prior_round" / "new_sweeps.md"
    if not path.exists():
        return []
    text = read_text_bounded(path)
    if text is None:
        return None
    out = []
    for m in re.finditer(r"(?m)^#{2,3}\s*(M\d+)\b", text):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def prior_proposal_dispositioned(pid: str, probe_blob: str, note_blob: str) -> bool:
    """Is a prior proposal id re-probed or explicitly dispositioned THIS round?

    A bare mention anywhere in the round-2 artifacts used to satisfy the
    convergence gate -- "No new sweep proposals: numbering starts at M37" in
    the summary passed it without any re-probe, which voids the loop D5
    promises. The two routes the prompt names are what count now: the id
    appears in a probe/result row (the re-probe route), or it appears in a note
    that says the word `prior` beside it (the
    "prior proposal <id>: no instances in base/" disposition).
    """
    _pid_re = re.compile(r"(?<![A-Za-z0-9])" + re.escape(pid) + r"(?![A-Za-z0-9])")
    _probe_hit = None
    for _m in _pid_re.finditer(probe_blob):
        _window = probe_blob[max(0, _m.start() - 80):_m.end() + 80].lower()
        if re.search(r"\b(?:not|never|no|without)\b", _window):
            continue          # "we did not re-probe M37" is not a re-probe
        _probe_hit = _m
        break
    if _probe_hit is None:
        for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(pid) + r"(?![A-Za-z0-9])",
                             note_blob):
            window = note_blob[max(0, m.start() - 90):m.end() + 90].lower()
            if re.search(r"\bprior\b", window):
                break
        else:
            return False
    return True


def discovery_contract_problems(sb: Path) -> tuple:
    """(errors, warnings) for one review sandbox's D0-D5 deliverables.

    Structural, never judgemental: every enumeration the round's own guide
    requires exists, every enumerated row carries a disposition, the X-*
    findings have the standard finding shape, proposals are sweeps.md-shaped
    and numbered from M37, and the previous round's proposals are re-probed
    (the convergence loop D5 promises, made code-enforced). Callers apply the
    `--strict-artifacts` policy -- see `check_discovery_contract`.
    """
    r2 = sb / GUIDED_REVIEW_DIR / "round2"
    errors, warns = [], []
    missing = [name for name in DISCOVERY_ROUND_FILES if not _discovery_nonempty(r2 / name)]
    if missing:
        errors.append(
            "guided_review/round2/ is missing the discovery round's deliverable(s) "
            f"{', '.join(missing)}: the D0-D5 phase must leave all of "
            f"{', '.join(DISCOVERY_ROUND_FILES)} (references/discovery.md). A phase whose "
            "artifacts are absent cannot be told apart from one that never ran -- the review's "
            "own sweeps are held to the same bar (a zero-finding sweep is invalid unless its "
            "artifact exists and every row is disposed)")
    # D0 -- the dedup base names the frozen class range.
    ki = r2 / "known_index.md"
    if _discovery_nonempty(ki):
        try:
            text = read_text_bounded(ki) or ""
        except OSError:
            text = ""
        # Both spellings of the range ends count: the frozen ids are unpadded
        # (M1/J5) but a session may write the padded forms (M01/J05) the census
        # docs also use; a hard failure over id spelling would be an id trap,
        # not a quality signal.
        def _class_id_mentioned(tok: str) -> bool:
            return re.search(rf"(?<![A-Za-z0-9]){re.escape(tok[0])}0*{int(tok[1:])}"
                             rf"(?![A-Za-z0-9])", text) is not None

        if not (_class_id_mentioned("M1") and _class_id_mentioned("J5")):
            errors.append(
                "guided_review/round2/known_index.md never names both ends of the frozen class range "
                "(M1 and J5 must appear as whole tokens): D0's KNOWN-CLASSES index is what keeps "
                "the round from re-reporting an already-owned class, and an index built without "
                "it cannot exclude anything")
    # D1 -- the gap table: >= 25 class rows, each COVERED/UNCOVERED, at least
    # one uncovered (the two-sided-defect seed alone is a standing gap).
    gap = discovery_gap_summary(sb)
    if _discovery_nonempty(r2 / "gap_table.md"):
        if gap["rows"] < DISCOVERY_MIN_GAP_ROWS:
            errors.append(
                f"guided_review/round2/gap_table.md carries {gap['rows']} row(s); D1's gap table must "
                f"enumerate at least {DISCOVERY_MIN_GAP_ROWS} issue-class rows "
                f"(references/discovery.md: seed the table, then ask 'what else?' twice more)")
        if gap["unmarked"]:
            errors.append(
                f"guided_review/round2/gap_table.md leaves {gap['unmarked']} of its {gap['rows']} "
                f"row(s) without a COVERED/UNCOVERED marking: every class row must state "
                f"whether a frozen check owns it (and which)")
        if gap["rows"] and not gap["uncovered"] and not gap["unmarked"]:
            errors.append(
                "guided_review/round2/gap_table.md marks every row COVERED: a discovery round that "
                "found no uncovered class has not run D1 -- the two-sided-defect seed alone (a "
                "known class whose definition reads only ONE direction) is a gap row until both "
                "directions have been reported, and so are the D3 anomaly hunts")
    # D2 -- probes: every UNCOVERED row becomes a probe (or a recorded
    # analysis limitation); probe rows carry a status cell and a reason.
    probe_rows = _discovery_rows(r2 / "probes.md")
    probe_ids, probeless, bad_probe_rows = [], 0, []
    limitations = 0
    for r in probe_rows:
        text = _row_text(r)
        m = DISCOVERY_PROBE_ID_RE.search(text)
        if not m:
            if re.search(r"\blimitation\b", text, re.I):
                limitations += 1
            elif text.strip():
                probeless += 1
            continue
        pid = m.group(0)
        if pid not in probe_ids:
            probe_ids.append(pid)
        statuses = _discovery_status_cells(r)
        if not statuses:
            bad_probe_rows.append(f"{pid} has no status cell (state pending/executed/unable)")
        for token, rest in statuses:
            if token == "unable" and not _unable_reason_present(rest):
                bad_probe_rows.append(f"{pid} is `unable` with no reason")
    if _discovery_nonempty(r2 / "probes.md") and gap["uncovered"]:
        have = len(probe_ids) + limitations
        if have < gap["uncovered"]:
            errors.append(
                f"guided_review/round2/probes.md declares {have} probe/limitation row(s) for "
                f"{gap['uncovered']} UNCOVERED gap row(s): D2 converts EVERY uncovered row "
                f"into a concrete probe (P2-...); a row that cannot be probed is recorded as an "
                f"analysis limitation, never silently dropped")
    if bad_probe_rows:
        errors.append(
            "guided_review/round2/probes.md has probe row(s) without a usable disposition "
            f"({'; '.join(bad_probe_rows[:4])}): every probe row states its status, and `unable` "
            f"states why execution was impossible")
    if probeless:
        warns.append(
            f"guided_review/round2/probes.md carries {probeless} non-empty row(s) with neither a P2-* "
            f"probe id nor an analysis-limitation note -- check they are not dropped root rows")
    # D3 -- results: one executed disposition per probe; a clean probe names the
    # locations it checked; `unable` states its reason.
    result_problems, unable_short, no_checked = [], [], []
    result_ids, dup_result_ids = [], []
    for r in _discovery_rows(r2 / "probe_results.md"):
        text = _row_text(r)
        m = DISCOVERY_PROBE_ID_RE.search(text)
        if not m:
            continue
        pid = m.group(0)
        if pid in result_ids:
            # EVERY row of a declared probe is judged: a stale `pending` row after
            # a good row used to be dropped silently, so the probe that never ran
            # (or was never retracted) could hide behind file order.
            if pid not in dup_result_ids:
                dup_result_ids.append(pid)
        else:
            result_ids.append(pid)
        low = text.lower()
        statuses = _discovery_status_cells(r)
        tokens = [t for t, _ in statuses]
        if "pending" in tokens:
            result_problems.append(f"{pid} is still `pending` (`executed`/`unable` required)")
        for token, rest in statuses:
            if token == "unable" and not _unable_reason_present(rest):
                unable_short.append(pid)
        # Only a real `unable` STATUS CELL needs a reason. Free prose such as
        # "the previous round was unable." is not an unable disposition.
        if re.search(r"\bno anomalies?\b", low):
            tail = re.split(r"\bno anomalies?\b", low, maxsplit=1)[1]
            # The closure is exactly `no anomalies -- checked: <locations>`;
            # a question that happens to contain "checked" is not that closure.
            if not re.match(r"\s*(?:[-\u2013\u2014]|:)\s*checked\s*:\s*\S", tail):
                no_checked.append(pid)
        if len(re.findall(r"[A-Za-z0-9]+", text)) < 6:
            result_problems.append(f"{pid} records no usable disposition")
    if _discovery_nonempty(r2 / "probe_results.md"):
        missing_res = [p for p in probe_ids if p not in result_ids]
        if missing_res:
            errors.append(
                f"guided_review/round2/probe_results.md records no result for probe(s) "
                f"{', '.join(missing_res[:6])}" + (" ..." if len(missing_res) > 6 else "")
                + ": D3 executes EVERY probe and records one disposition per row (a clean probe "
                  "records 'no anomalies -- checked: <locations>')")
        extra = [p for p in result_ids if p not in probe_ids]
        if extra:
            warns.append(
                f"guided_review/round2/probe_results.md reports probe id(s) {', '.join(extra[:6])} "
                f"that probes.md never declares -- declare them there or drop the rows")
        if dup_result_ids:
            warns.append(
                f"guided_review/round2/probe_results.md records probe id(s) "
                f"{', '.join(dup_result_ids[:6])} more than once: every row is judged, so "
                f"retract the superseded disposition instead of leaving both in place")
        if result_problems:
            errors.append("guided_review/round2/probe_results.md: "
                          + "; ".join(sorted(set(result_problems))[:4]))
        if unable_short:
            errors.append(
                f"guided_review/round2/probe_results.md closes {len(set(unable_short))} probe(s) "
                f"`unable` with no reason ({', '.join(sorted(set(unable_short))[:4])}): an "
                f"unable probe states WHY it "
                f"could not be executed")
        if no_checked:
            errors.append(
                f"guided_review/round2/probe_results.md closes {len(set(no_checked))} probe(s) 'no "
                f"anomalies' without naming the checked locations "
                f"({', '.join(sorted(set(no_checked))[:4])}): D3's clean closure is "
                f"'no anomalies -- checked: <locations>'")
    # D4 -- the X-* findings carry the standard finding shape.
    if _discovery_nonempty(r2 / "findings_extra.json"):
        xj = read_json(r2 / "findings_extra.json", revive=False, lenient=True)
        if not isinstance(xj, dict) or not isinstance(xj.get("findings"), list):
            errors.append(
                "guided_review/round2/findings_extra.json does not carry a 'findings' list (the D4 "
                "deliverable: {'findings': [...], 'coverage': [...]})")
        else:
            bad, seen = [], set()
            for f in xj["findings"]:
                if not isinstance(f, dict):
                    bad.append("a non-object row")
                    continue
                fid = str(f.get("id") or "").strip()
                if not DISCOVERY_X_ID_RE.match(fid):
                    bad.append(f"{fid or '(no id)'}: the id must be X-001...")
                    continue
                if fid in seen:
                    bad.append(f"{fid}: duplicate id")
                seen.add(fid)
                for key in ("location", "check", "evidence", "explanation"):
                    if not str(f.get(key) or "").strip():
                        bad.append(f"{fid}: no {key}")
                if str(f.get("severity") or "").strip().lower() not in DISCOVERY_SEVERITIES:
                    bad.append(f"{fid}: severity {f.get('severity')!r} is not one of "
                               f"Fatal/Critical/Major/Minor")
                try:
                    ok_cat = 0 <= int(f.get("category")) <= 5
                except (TypeError, ValueError):
                    ok_cat = False
                if not ok_cat:
                    bad.append(f"{fid}: category {f.get('category')!r} is not an integer 0-5")
            if bad:
                errors.append(
                    "guided_review/round2/findings_extra.json carries malformed X-finding(s): "
                    + "; ".join(bad[:6]) + (" ..." if len(bad) > 6 else "")
                    + " (an X-* finding has the standard finding shape: id X-NNN, location, "
                      "category 0-5, check = the gap-row class label, severity, evidence quote, "
                      "explanation)")
    # D5 -- proposals are sweeps.md-shaped, numbered from M37, or the file
    # states explicitly that there were none (and why).
    if _discovery_nonempty(r2 / "new_sweeps.md"):
        try:
            text = read_text_bounded(r2 / "new_sweeps.md") or ""
        except OSError:
            text = ""
        # `parse_sweep_proposals` is the ONE reader the `adopt-sweep` command uses
        # too: a contract that accepted a heading the adopter cannot parse (a
        # `## M37 Foo` block without the `-- <name>` separator) passed the review
        # and then died at adoption time with "carries no proposal block".
        proposals, problems = parse_sweep_proposals(text)
        if proposals or problems:
            if problems:
                errors.append(
                    "guided_review/round2/new_sweeps.md does not carry sweeps.md-shaped proposal(s): "
                    + "; ".join(problems[:6])
                    + " (each proposal is `## M<NN> -- <name>` with Purpose, Enumeration, "
                      "Artifact and Finding rules, numbered from M37)")
        elif re.search(r"(?m)^#{2,3}\s*(M\d+)\b", text):
            errors.append(
                "guided_review/round2/new_sweeps.md carries a `## M<NN>` heading that is not a "
                "sweeps.md-shaped proposal block: a proposal is `## M<NN> -- <name>` with "
                "Purpose, Enumeration, Artifact and Finding rules, numbered from M37, and the "
                "`adopt-sweep` command reads the same shape")
        elif not DISCOVERY_NO_PROPOSAL_RE.search(text):
            errors.append(
                "guided_review/round2/new_sweeps.md carries no `## M<NN>` proposal and does not state "
                "that there were no new sweeps to propose: D5's zero-proposal outcome must be "
                "explicit (and say why), never a placeholder like '# none'")
    # The round's summary (the D5 output section of references/discovery.md) reports its
    # counts and its honest limits.
    if _discovery_nonempty(r2 / "round2_summary.md"):
        try:
            text = read_text_bounded(r2 / "round2_summary.md") or ""
        except OSError:
            text = ""
        low = text.lower()
        missing_bits = [w for w in ("gap", "probe") if w not in low]
        if missing_bits:
            errors.append(
                f"guided_review/round2/round2_summary.md does not state its {'/'.join(missing_bits)} "
                f"count(s): the summary reports gap rows (covered/uncovered), probes "
                f"(executed/clean/findings/unable), X-findings, proposed sweeps and the round's "
                f"honest limits")
        elif not re.search(r"could not|cannot|limit", low):
            warns.append(
                "guided_review/round2/round2_summary.md carries no honest-limits statement ('what "
                "this round could NOT check'); the round's guide requires one")
    # Continuity -- a class the previous round proposed is re-probed (or
    # explicitly dispositioned) now; D5's convergence loop must not depend on an
    # operator re-reading per-run files.
    gone = []
    prior_ids = prior_proposal_ids(sb)
    if prior_ids is None:
        errors.append(
            "prior_round/new_sweeps.md exists but cannot be read (unreadable, non-regular, "
            "or over the byte budget): the previous round's proposals cannot be re-probed, "
            "so the convergence gate has no evidence either way")
    elif prior_ids:
        def _blob(rels) -> str:
            out = []
            for rel in rels:
                p = sb / rel
                if p.is_file():
                    t = read_text_bounded(p)
                    if t is None:
                        warns.append(f"{rel} exists but cannot be read (unreadable, "
                                     f"non-regular, or over the byte budget)")
                        continue
                    out.append(t)
            return "\n".join(out)

        probe_blob = _blob(("guided_review/round2/probes.md", "guided_review/round2/probe_results.md"))
        note_blob = _blob((FINDINGS_REL, FINDINGS_MD_REL, "guided_review/round2/new_sweeps.md",
                           "guided_review/round2/round2_summary.md"))
        gone = [pid for pid in prior_ids
                if not prior_proposal_dispositioned(pid, probe_blob, note_blob)]
        if gone:
            errors.append(
                f"the previous round's discovery round proposed sweep(s) {', '.join(gone)} "
                f"that this round re-checks NOWHERE (a passing mention does not count): every "
                f"prior proposal must be re-probed against the current corpus and recorded -- "
                f"run it as a probe row in guided_review/round2/probes.md / probe_results.md, or "
                f"disposition it as 'prior proposal <id>: no instances in base/' in "
                f"guided_review/round2/new_sweeps.md or round2_summary.md. A proposed class must not "
                f"vanish between rounds; the proposal's purpose is to converge into a "
                f"mechanical check")
    return errors, warns


def check_discovery_contract(ctx: Ctx, sb: Path, errs: list, warns: list) -> list:
    """Apply `discovery_contract_problems` under the review's artifact policy.

    Under the default `--strict-artifacts on` the problems FAIL the attempt
    (like the review's own decision tables); under `--strict-artifacts off`
    they are recorded as warnings, and `decide --residual-gate` still refuses
    to certify a run whose record carries them. Returns the ERROR list for the
    run record (the advisory problems are recorded as warnings only).
    """
    derrs, dwarns = discovery_contract_problems(sb)
    promotes = strict_dispositions(ctx)
    for p in derrs:
        (errs if promotes else warns).append(f"discovery round: {p}")
    for p in dwarns:
        warns.append(f"discovery round: {p}")
    return derrs


def review_owes_discovery(ctx, rec: dict) -> bool:
    """Does THIS review session have to leave the D0-D5 deliverables?

    A "formatting-writing" round never runs the discovery phase (its prompt
    says so). Under a phases/aspects split only session B carries it; session
    A's postcheck must not demand the other half's deliverable.
    """
    try:
        scope = round_review_scope(ctx, int(rec.get("round") or 1))
    except Exception:                                             # noqa: BLE001
        scope = "full"
    if scope != "full":
        return False
    if review_split_of(ctx) != "off":
        try:
            return str(rec.get("id") or "") == rid_guided_review_b(int(rec.get("round") or 1))
        except Exception:                                         # noqa: BLE001
            return False
    return True


def cross_namespace_duplicate_notes(sb: Path, fj) -> list:
    """X-* findings that look like re-reports of the frozen F-* list (D0's rule).

    D0 forbids re-reporting a prior finding ("same class + same location + same
    substance"), but nothing audited the rule mechanically. This reuses the
    census's own key (a `line N` both sides parse, excerpts at least
    DEDUP_MIN_WORDS long, token-set Jaccard at the census threshold) and
    reports the pair so the session and the archived record can see it; it
    never drops anything (same location with a different substance is legal).

    The CLASS is part of the key: the note's own text invokes "the same
    class+location+substance is NOT reportable", and passing a literal "X" for
    both sides made the comparison vacuous -- a discovery finding that merely
    shared a line with an unrelated frozen row was told to be dropped. When
    neither side parses a `line N`, the two findings' own `location` cells are
    the fallback key (the finding format does not mandate a line number, so the
    census key alone left the audit inert).
    """
    extra = read_json(sb / GUIDED_REVIEW_DIR / "round2" / "findings_extra.json",
                      revive=False, lenient=True)
    if not isinstance(extra, dict):
        return []
    xrows = [f for f in (extra.get("findings") or [])
             if isinstance(f, dict) and f.get("id")]
    frows = [f for f in ((fj or {}).get("findings") or [])
             if isinstance(f, dict) and f.get("id")]
    notes = []
    for x in xrows:
        x_cls = dedup_class_id(x.get("check"))
        if not x_cls:
            continue                     # no class -> no dedup key (the census rule)
        x_loc = dedup_location_of(f"{x.get('location')} {x.get('evidence')}")
        for f in frows:
            f_cls = dedup_class_id(f.get("check"))
            if not f_cls or f_cls != x_cls:
                continue
            f_loc = dedup_location_of(f"{f.get('location')} {f.get('evidence')}")
            if not (dedup_rows_match(x_cls, x_loc, f_cls, f_loc)
                    or (dedup_same_place(x.get("location"), f.get("location"))
                        and dedup_excerpts_match(x_loc, f_loc))):
                continue
            notes.append(
                f"{x.get('id')} looks like a duplicate of the frozen {f.get('id')} (same class "
                f"{x_cls}, "
                + (f"same line {x_loc[0]}"
                   if x_loc[0] is not None else
                   f"same location {str(x.get('location') or '').strip()!r}")
                + "; excerpt similarity above the census threshold): D0 says the same "
                  "class+location+substance is NOT reportable -- drop the X row, or keep it "
                  f"only if its substance really differs and say so in its explanation "
                  f"('related to {f.get('id')}')")
            break
    return notes


def parse_sweep_proposals(text: str) -> tuple:
    """(proposals, problems) for one new_sweeps.md document.

    A proposal is a `## M<NN> -- <name>` block carrying the four sweeps.md
    fields (Purpose / Enumeration / Artifact / Finding rules); `proposals` are
    `(id, name, block)` in file order, `problems` name every disqualifying
    defect (numbering below the floor, a missing field, a duplicate id). Pure,
    so the review contract and the `adopt-sweep` command share one reader.
    """
    proposals, problems = [], []
    matches = list(re.finditer(r"(?m)^#{2,3}\s*(M\d+)\s*[—–-]\s*(.+?)\s*$", text))
    if not matches:
        return [], []
    for i, m in enumerate(matches):
        sid, name = m.group(1), m.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[m.start():end].rstrip() + "\n"
        if int(sid[1:]) < DISCOVERY_PROPOSAL_MIN:
            problems.append(f"{sid}: below the numbering floor M{DISCOVERY_PROPOSAL_MIN} "
                            f"(M18-M20 are reserved and M21-M36 already adopted)")
        low = block.lower()
        for field in ("purpose", "enumeration", "artifact", "finding rule"):
            if field not in low:
                problems.append(f"{sid}: no `{field}` field")
        proposals.append((sid, name, block))
    ids = [p[0] for p in proposals]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        problems.append(f"duplicate proposal id(s): {', '.join(dups)}")
    return proposals, problems


def adopt_sweep_problems(proposals: list, sweeps_text: str) -> list:
    """Why these proposals cannot be appended to the target sweeps.md ([] = ok)."""
    problems = []
    existing = []
    for m in re.finditer(r"(?m)^#{2,3}\s*(M\d+)\b", sweeps_text):
        n = int(m.group(1)[1:])
        if n not in existing:
            existing.append(n)
    top = max(existing) if existing else 0
    for sid, _name, _block in proposals:
        n = int(sid[1:])
        if n in existing:
            problems.append(f"{sid} already exists in the target sweeps.md")
        elif n <= top:
            problems.append(
                f"{sid} does not continue the target's numbering (its highest sweep is M{top}): "
                f"proposals are appended continuing from the highest existing sweep number, so "
                f"reuse would collide with an adopted definition")
    return problems


def resync_sweeps_appendix(sweeps_path: Path, sweeps_text: str) -> str:
    """Keep the standalone review prompt's sweeps appendix byte-equal to sweeps.md.

    `validate_skill.py`'s D10 check requires the two to match, so an adoption
    that skipped this would leave the repo failing its own consistency harness.
    Returns a note for the operator.
    """
    prompt = sweeps_path.parent.parent.parent / "prompts" / "identify_issues.prompt.md"
    if not prompt.is_file():
        return f"(no {prompt.name} beside the skills; its appendix was not re-synced)"
    try:
        lines = prompt.read_text(encoding="utf-8").splitlines()
    except OSError as e:                                          # noqa: BLE001
        return f"(the prompt {prompt} could not be read: {e}; not re-synced)"
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## APPENDIX: Sweeps")), None)
    stop = next((i for i, ln in enumerate(lines) if ln.startswith("## APPENDIX: Discovery")), None)
    if start is None or stop is None or stop <= start:
        return f"(could not locate the sweeps appendix in {prompt}; not re-synced)"
    new_lines = (lines[:start + 1] + [""] + sweeps_text.strip().splitlines() + [""]
                 + lines[stop:])
    write_text_atomic(prompt, "\n".join(new_lines) + "\n")
    return f"re-synced the sweeps appendix in {prompt}"


def check_review_contract(ctx: Ctx, sb: Path, fj, errs: list, warns: list,
                          scope: str = "full", split: str = None) -> None:
    """Verify the review deliverables the prompt promises the orchestrator checks.

    `scope` is the round's review scope: a "formatting-writing" round still has
    to CARRY every check id in its coverage table, but the out-of-scope ids may
    be disposed as "out of scope -- ..." (that is the scope contract), while the
    in-scope surface checks keep the full bar.

    `split` overrides the split mode normally read from `ctx` (the sandbox
    selfcheck has no plan to read it from, so it passes the mode its own prompt
    states -- the two must agree on which half owes which artifacts).
    """
    if not isinstance(fj, dict):
        return
    # The M1b gate near the end of this function reads `seen_rows`, and it runs
    # whenever the M1 artifact carries a long-form row -- whether or not the
    # coverage table exists. The three dicts were initialised inside the
    # coverage branch, so a findings.json that parses and holds a findings list
    # but no coverage table crashed the contract check with NameError instead
    # of reporting the missing table.
    seen_ids, seen_rows, bad, bad_out_of_scope = {}, {}, [], []
    # 1. the review must be about base/, not about non_revised/ or anything else.
    raw = fj.get("submission_dir")
    if isinstance(raw, str) and raw.strip():
        try:
            resolved = (sb / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        except OSError:
            resolved = None
        base = (sb / "base").resolve()
        if resolved is not None and resolved != base:
            errs.append(f"{FINDINGS_REL} records submission_dir={raw!r}, which does not resolve "
                        f"to this sandbox's base/ ({base}); the review analysed the WRONG corpus "
                        f"-- in round 2+ non_revised/ is the pristine original, not the champion. "
                        f"Re-run the review with SUBMISSION_DIR=./base")
    else:
        # A missing/empty field used to be a warning only, so an agent could
        # drop the key and bypass the F02 rule ("the review must be about
        # base/") entirely: in round 2+ the pristine original would be reviewed
        # while the round's champion was never inspected.
        errs.append(f"{FINDINGS_REL} carries no usable 'submission_dir': the review must record "
                    f"the corpus it analysed and it must resolve to this sandbox's base/ -- "
                    f"re-run the review with SUBMISSION_DIR=./base")
    # 2. every check ID must have a real disposition.
    coverage = fj.get("coverage")
    if not isinstance(coverage, list):
        errs.append(f"{FINDINGS_REL} has no coverage table; every check ID M1-M17, M18-M36 and "
                    f"J1-J5 must carry a real disposition (the skill's acceptance gate)")
    else:
        wanted = list(REQUIRED_REVIEW_CHECKS)
        wanted.append("M19")            # always active: the length rule is not opt-in
        wanted.append("M18")            # always active: legends are always enumerated
        wanted.append("M20")            # always active: the OOXML formatting sweep
        # Adopted from the discovery rounds (sweeps.md M21-M24): the review runs
        # them, so their coverage rows are required exactly like the older ones.
        wanted += ["M21", "M22", "M23", "M24"]
        # The rewrite-parity checks (sweeps.md M25-M29) and the architecture
        # pass J5: the classes a from-scratch rewrite fixes as a side-effect.
        # The panel's frozen set is unchanged, so J5 is review-side only.
        wanted += ["M25", "M26", "M27", "M28", "M29", "J5"]
        # The source-hierarchy reconciliation (sweeps.md M30): the detection side
        # of the hierarchy the prompts already use to RESOLVE a conflict.
        wanted += ["M30"]
        # The EVIDENCE-INTEGRITY sweeps (sweeps.md M31-M35): artwork-versus-legend
        # consistency, a headline statistic against the correction the paper
        # states, availability-locator finality, figure-source-data coverage and
        # disclosure/provenance completeness, plus M36's Zotero live-field
    # refresh parity. Review-side like M25-M30.
        wanted += ["M31", "M32", "M33", "M34", "M35", "M36"]
        in_scope = set(scoped_review_checks(scope))
        out_of_scope = set(wanted) - in_scope if in_scope else set()
        for row in coverage:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("check") or "").strip()
            disp = str(row.get("disposition") or "").strip()
            if cid:
                if cid in seen_ids:
                    # One row per check id: a second, possibly contradictory,
                    # row used to silently overwrite the first (last one won),
                    # so two mutually exclusive dispositions both passed (F61).
                    errs.append(f"{FINDINGS_REL} coverage table lists check {cid!r} more than "
                                f"once: every check id must have exactly ONE disposition row")
                    continue
                seen_ids[cid] = disp
                seen_rows[cid] = row
            if cid and (not disp or disp.lower().startswith("not checked")
                        or not _coverage_disposition_ok(disp)):
                bad.append(cid)
            if (cid and cid in wanted and (not in_scope or cid in in_scope)
                    and re.sub(r"\s+", " ", disp).lower().startswith("out of scope")):
                # A FULL review's object is the whole package, and a SCOPED
                # round still owns every check it declares in scope: neither may
                # dispose one of those as out of scope. The old gate tested
                # `not in_scope`, so a formatting-writing round (non-empty
                # in_scope) silently accepted an in-scope M1 row marked out of
                # scope (the 2026-10-28 audit's F14). A genuinely out-of-scope
                # check of a scoped round is still separately checked below.
                # `cid in wanted` keeps an EXTRA coverage proposal (M37/M38)
                # that a review honestly marks "out of scope" from being
                # reported as an in-scope check.
                bad_out_of_scope.append(cid)
        if out_of_scope:
            # A scoped round must SAY that a check was left out; silence is still
            # a missing disposition.
            for cid in sorted(out_of_scope):
                disp = (seen_ids.get(cid) or "").strip().lower()
                if cid in seen_ids and not disp.replace(" ", "").startswith("outofscope"):
                    errs.append(
                        f"{FINDINGS_REL} coverage row {cid!r} = {disp!r} but this round's review "
                        f"scoped OUT that check: dispose it as 'out of scope -- this round's "
                        f"review is the formatting-and-writing-only pass' (or run the check and "
                        f"dispose it for real)")
        missing = [c for c in wanted if c not in seen_ids]
        if missing:
            errs.append(f"{FINDINGS_REL} coverage table is missing check id(s) {missing}; a "
                        f"coverage table without every required check id is not a complete review "
                        f"(use 'N findings', 'clean -- basis: <artifact>' or 'unable -- <reason>')")
        if bad:
            errs.append(f"{FINDINGS_REL} coverage rows without a real disposition: {sorted(set(bad))}"
                        f" (each row is 'N findings', 'clean -- basis: <artifact>', "
                        f"'unable -- <reason>' or 'out of scope -- <reason>'; an empty, "
                        f"'not checked' or filler cell is not a disposition)")
        if bad_out_of_scope:
            errs.append(f"{FINDINGS_REL} disposes in-scope check(s) {sorted(set(bad_out_of_scope))} "
                        f"as 'out of scope', but this round's review must apply and dispose "
                        f"every required check it holds in scope on its result")
    # 3. per-sweep artifacts must exist (the coverage evidence).
    art_dir = sb / ARTIFACTS_REL
    if not art_dir.is_dir():
        errs.append(f"{ARTIFACTS_REL}/ is missing: the skill's ENUMERATE->ARTIFACT->AUDIT->REPORT "
                    f"discipline cannot be verified without the per-sweep tables")
    elif not any(p.is_file() for p in art_dir.rglob("*")):
        errs.append(f"{ARTIFACTS_REL}/ is empty: at least one per-sweep artifact table is required")
    # 3b. the REWRITE-PARITY artifacts (M25-M29) and the architecture table
    #     (J5) are part of the contract: a sweep with no artifact proves
    #     nothing, and J5 is the only home of the scope-level (rewrite-class)
    #     issues. These are the classes a from-scratch rewrite fixes as it
    #     goes; a review that never enumerated them leaves the revision arm
    #     with nothing to fix (the documented w1/w2-vs-a2 gap).
    parity = {"M25_artwork_parity.md": ("M25", "the rewrite-parity check"),
              # M2's seed is the OTHER mechanical side of the citation sweep: the
              # entries' own DOIs, the resolver's verdict for each and the
              # code-side signals (a DOI whose own year contradicts the entry, one
              # DOI on two entries). It is seeded by the orchestrator, so a
              # zero-finding M2 is valid only with this artifact disposed.
              "M2_references.md": ("M2", "the reference-integrity seed"),
              "M26_conventions.md": ("M26", "the rewrite-parity check"),
              "M27_evidence_coverage.md": ("M27", "the rewrite-parity check"),
              "M28_symmetry.md": ("M28", "the rewrite-parity check"),
              "M29_caption_schema.md": ("M29", "the rewrite-parity check"),
              # M30 is the DETECTION side of the same hierarchy the prompts use
              # to RESOLVE a conflict; like M25-M29 it is a mechanical sweep on
              # this path (the judgment calls stay in the reviewer's rows).
              "M30_hierarchy_reconciliation.md": ("M30", "the source-hierarchy reconciliation"),
              # The EVIDENCE-INTEGRITY sweeps (M31-M35): each enumerates a class
              # the code can only SEED (what a figure prints, what a correction
              # supports, whether a locator resolves, what a source file covers,
              # what a disclosure names), so a zero-finding sweep is valid ONLY
              # with a disposed artifact.
              "M31_artwork_legend.md": ("M31", "the evidence-integrity check"),
              "M32_statistics.md": ("M32", "the evidence-integrity check"),
              "M33_availability.md": ("M33", "the evidence-integrity check"),
              "M34_source_data_coverage.md": ("M34", "the evidence-integrity check"),
              "M35_disclosures.md": ("M35", "the evidence-integrity check"),
              # M36: the live Zotero field state (stale markers, a reordered
              # bibliography, conflicting style stores) -- a document a routine
              # Word/Zotero refresh rewrites.
              "M36_zotero_parity.md": ("M36", "the Zotero live-field parity check")}
    # A SCOPED round requires only the artifacts of the checks IT runs (the
    # formatting-writing pass keeps M26's house-style table and J5's
    # architecture table; M25/M27-M36 belong to the content rounds).
    scope_in = set(scoped_review_checks(scope))
    if scope_in:
        parity = {k: v for k, v in parity.items() if v[0] in scope_in}
    # A SPLIT review divides the work: session A owns the mechanical checks
    # (M25-M29 artifacts), session B owns the J5 architecture pass and the
    # discovery round. Each session's postcheck must not demand the other's
    # artifacts -- the merge unions the coverage tables and artifacts.
    split_mode = "off"
    if split is not None:
        split_mode = split if split in REVIEW_SPLIT_MODES else "off"
    elif ctx is not None:
        try:
            split_mode = review_split_of(ctx)
        except Exception:                                        # noqa: BLE001
            split_mode = "off"
    part_b = bool(split_mode != "off" and str(sb.name).endswith("_review_b"))
    # phases: A = mechanical (M25-M29 artifacts), B = J1-J5 + discovery (J5
    # architecture table). aspects: A = content, B = packaging + M21-M30 + J5.
    want_parity_artifacts = (split_mode == "off"
                             or (split_mode == "phases" and not part_b)
                             or (split_mode == "aspects" and part_b))
    if split_mode == "aspects":
        # Aspects puts M2 (reference integrity) in session A and the packaging
        # checks in B. Demanding M2 from B made B fail on a table its prompt
        # told it not to duplicate, while nobody checked A's M2 disposal.
        parity = {k: v for k, v in parity.items()
                  if (k == "M2_references.md") != part_b}
    want_architecture = (split_mode == "off" or part_b)
    if want_parity_artifacts and art_dir.is_dir():
        for fname, (cid, kind_phrase) in parity.items():
            p = art_dir / fname
            if p.is_symlink() or not p.is_file():
                errs.append(f"{ARTIFACTS_REL}/{fname} is missing or a symlink: {kind_phrase} "
                            f"{cid} enumerates one of the classes a from-scratch rewrite fixes "
                            f"as it goes; a zero-finding sweep is valid ONLY with a disposed, "
                            f"package-local artifact")
                continue
            # Agent-written artifact: shared regular-file/no-follow/byte-budget
            # reader, never a whole-file read of an arbitrary target (F37).
            body = read_text_bounded(p)
            if body is None:
                errs.append(f"{ARTIFACTS_REL}/{fname} could not be read (it is a symlink/"
                            f"non-regular file or over the byte budget)")
                continue
            if not body.strip():
                errs.append(f"{ARTIFACTS_REL}/{fname} is EMPTY: {cid} must enumerate its rows "
                            f"and dispose every one of them")
            elif "disposition" not in body.lower():
                errs.append(f"{ARTIFACTS_REL}/{fname} carries no `disposition` column: every "
                            f"{cid} row must end in a finding id / OK - <reason> / "
                            f"unable - <reason>")
            else:
                # A header line and a separator is not a disposed artifact: the
                # old substring test accepted `| disposition |\n|---|` with no
                # data row at all. Parse the table and require a disposed row.
                for problem in _disposition_table_problems(p):
                    errs.append(f"{ARTIFACTS_REL}/{fname}: {problem}")
    arch = sb / GUIDED_REVIEW_DIR / "ARCHITECTURE.md"
    if want_architecture and not arch.is_file():
        errs.append(f"{GUIDED_REVIEW_DIR}/ARCHITECTURE.md is missing: the J5 architecture pass must "
                    f"record one row per scope (document | section | paragraphs | current "
                    f"structure | reader cost | proposed reorganization | class | severity | "
                    f"disposition -- a scope that is fine gets its own OK row), because the "
                    f"scope-level issues a rewrite fixes have no instance-level home")
    elif want_architecture:
        try:
            body = read_text_bounded(arch)
            if body is None:
                errs.append(f"{GUIDED_REVIEW_DIR}/ARCHITECTURE.md could not be read "
                            f"(unreadable, non-regular, or over the byte budget)")
            elif not body.strip():
                errs.append(f"{GUIDED_REVIEW_DIR}/ARCHITECTURE.md is EMPTY: the J5 pass must examine "
                            f"every document scope by scope")
            elif "disposition" not in body.lower():
                errs.append(f"{GUIDED_REVIEW_DIR}/ARCHITECTURE.md carries no `disposition` column: "
                            f"every scope row must be disposed against its own reading-order bar")
            else:
                # `| scope | disposition |\n|---|` used to satisfy the substring
                # test without one disposed scope row.
                for problem in _disposition_table_problems(arch):
                    errs.append(f"{GUIDED_REVIEW_DIR}/ARCHITECTURE.md: {problem}")
        except OSError as e:                                        # noqa: BLE001
            errs.append(f"{GUIDED_REVIEW_DIR}/ARCHITECTURE.md could not be read ({e})")
    # 4. finding ids must be unique and stable.
    findings = fj.get("findings")
    if isinstance(findings, list):
        ids = [str(f.get("id") or "") for f in findings if isinstance(f, dict)]
        dupes = sorted({i for i in ids if i and ids.count(i) > 1})
        empty = sum(1 for i in ids if not i)
        if dupes:
            errs.append(f"{FINDINGS_REL} reuses finding id(s) {dupes}: ids must be unique, and "
                        f"Phase 2's ledger keys on them (a duplicated id silently merges two "
                        f"findings)")
        if empty:
            errs.append(f"{FINDINGS_REL} carries {empty} finding(s) without an id")
        # The review's row shape is the SAME contract the cold-start review's findings are
        # held to: a finding needs location, check, evidence, explanation, a
        # category 0-5 and one of the four severity rungs. Without this loop a
        # malformed review row passed the review gate, was "confirmed" by the
        # audit, and then vanished from (or corrupted) the census because the
        # severity did not parse.
        malformed = []
        for f in findings:
            if not isinstance(f, dict):
                malformed.append("a non-object row")
                continue
            fid = str(f.get("id") or "").strip() or "(no id)"
            for key in ("location", "check", "evidence", "explanation"):
                if not str(f.get(key) or "").strip():
                    malformed.append(f"{fid}: no {key}")
            if not re.match(r"(?i)^(?:M\d{1,2}|J[1-5]|JF)$",
                            str(f.get("check") or "").strip()):
                malformed.append(f"{fid}: check {f.get('check')!r} is not an M/J check id")
            if str(f.get("severity") or "").strip().lower() not in DISCOVERY_SEVERITIES:
                malformed.append(f"{fid}: severity {f.get('severity')!r} is not one of "
                                 f"Fatal/Critical/Major/Minor")
            try:
                ok_cat = 0 <= int(f.get("category")) <= 5
            except (TypeError, ValueError):
                ok_cat = False
            if not ok_cat:
                malformed.append(f"{fid}: category {f.get('category')!r} is not an integer 0-5")
            # The canonical output shape (see the review prompt) requires the
            # finding's own disposition class: the reviser/auditor must be able
            # to tell a fixable defect from an unresolvable or
            # guideline-dependent one. The scoped concerns path already checks
            # this; the full review path silently accepted a missing field.
            if str(f.get("status") or "").strip().lower() not in (
                    "resolvable", "unresolvable", "guideline-dependent"):
                malformed.append(
                    f"{fid}: status {f.get('status')!r} is not one of "
                    f"resolvable|unresolvable|guideline-dependent")
        if malformed:
            errs.append(
                f"{FINDINGS_REL} carries malformed finding(s): "
                + "; ".join(malformed[:6]) + (" ..." if len(malformed) > 6 else "")
                + " (every review finding carries location, check, category 0-5, severity "
                  "Fatal/Critical/Major/Minor, evidence and explanation, exactly like a probe "
                  "finding)")
        j5_missing = [str(f.get("id") or "?") for f in findings
                      if isinstance(f, dict)
                      and str(f.get("check") or "").strip().upper() == "J5"
                      and not str(f.get("scope") or "").strip()]
        if j5_missing:
            errs.append(f"{FINDINGS_REL}: J5 architecture finding(s) {j5_missing} carry no "
                        f"`scope`; the revision stage's E11 restructuring licence is bounded by "
                        f"that scope, so it must be recorded (document/section/paragraph-range)")
    # 5. every prior-round finding must be reconciled (carried forward or recorded as gone).
    #    BOTH frozen-finding namespaces: the list the revisers and the auditor must
    #    dispose is the union of prior_round/findings.json (F-*) and
    #    prior_round/findings_extra.json (X-*, the discovery round's findings), and
    #    both files are copied into the sandbox. Reading only findings.json let an
    #    X-finding vanish between rounds without failing anything -- the exact
    #    silent-loss the F-* half of this gate exists to prevent.
    prior_ids = []
    for prior_rel in ("prior_round/findings.json", "prior_round/findings_extra.json"):
        prior = sb / prior_rel
        if not prior.is_file():
            continue
        pj = read_json(prior, revive=False, lenient=True)   # agent-written
        prior_ids += [str(f.get("id") or "") for f in ((pj or {}).get("findings") or [])
                      if isinstance(f, dict) and f.get("id")]
    if prior_ids:
        # The id must be reconciled WHERE THE CONTRACT SAYS, not merely occur
        # somewhere: a new finding's `explanation` carrying the exact marker
        # "carried over from <prior-id>", or the marker "carried over from
        # <prior-id>"/"prior <prior-id>: not reproducible in base/" in the
        # summary note of findings.md. An unrelated "see F-999" in another
        # finding's evidence used to satisfy the gate while the defect vanished.
        md_text = ""
        md = sb / FINDINGS_MD_REL
        if md.is_file():
            md_text = read_text_bounded(md) or ""
        reconciled = set()
        explanations = "\n".join(
            str(f.get("explanation") or "") for f in (fj.get("findings") or [])
            if isinstance(f, dict)) if isinstance(fj.get("findings"), list) else ""
        for pid in prior_ids:
            tok = re.escape(pid)
            if re.search(r"carried over from\s+" + tok + r"(?![A-Za-z0-9])",
                         explanations, re.I):
                reconciled.add(pid)
            elif re.search(r"carried over from\s+" + tok + r"(?![A-Za-z0-9])",
                           md_text, re.I):
                reconciled.add(pid)
            elif re.search(r"prior\s+" + tok + r"\s*:\s*not reproducible in base/",
                           md_text, re.I):
                reconciled.add(pid)
        missing = sorted(pid for pid in prior_ids if pid not in reconciled)
        if missing:
            errs.append(
                f"{len(missing)} finding(s) from the previous round's review "
                f"(findings.json + findings_extra.json) are "
                f"reconciled NOWHERE in findings.json/findings.md: {missing[:10]}"
                + ("..." if len(missing) > 10 else "")
                + ". Each prior finding must either be carried forward (a new finding whose "
                "explanation says \"carried over from <prior-id>\") or recorded as "
                "\"prior <prior-id>: not reproducible in base/\" in the summary note of "
                "findings.md -- a defect must not vanish because a later pass missed it.")
    # 5b. the discovery round's X-* findings must not re-report the frozen list.
    #     D0 states the dedup rule; the mechanical trail below (same location,
    #     comparable quote, census Jaccard) makes a violation visible instead of
    #     relying on the session's own diligence.
    for note in cross_namespace_duplicate_notes(sb, fj):
        warns.append(note)
    # 6. the M1b long-form table must be audited, not skipped. The inventory
    #    alone reads healthy for exactly this defect (an acronym defined at
    #    first use while the long form carries the prose), so residue rows may
    #    neither be absent from findings.json nor silently unaccounted for: the
    #    session either raises M1 findings, or records -- in the M1 coverage
    #    ROW (its `disposition` or its `detail` cell; the prompt names the
    #    detail cell) or in the table's own per-row `disposition` cell -- why
    #    every M1b row is disposed OK. Reading only the coverage row's
    #    `disposition` cell failed a session whose detail cell read "377 token
    #    rows + 25 M1b rows" (2026-09-22 root, second attempt), which is exactly
    #    the record the prompt asks for.
    m1_art = art_dir / "M1_acronyms.md"
    if m1_art.is_file():
        m1_md = read_text_bounded(m1_art)
        if m1_md is None:
            errs.append(f"{ARTIFACTS_REL}/M1_acronyms.md could not be read (unreadable, "
                        f"non-regular, or over the byte budget)")
            m1_md = ""
        n_m1b = m1b_row_count(m1_md)
        if n_m1b:
            m1_findings = [f for f in (findings or [])
                           if isinstance(f, dict)
                           and str(f.get("check") or "").strip().upper() == "M1"]
            m1_row_text = coverage_row_text(seen_rows.get("M1"))
            if not m1_findings and not _m1b_coverage_reason(m1_row_text) \
                    and not m1b_rows_disposed(m1_md):
                errs.append(
                    f"{ARTIFACTS_REL}/M1_acronyms.md lists {n_m1b} M1b long-form row(s) "
                    f"(un-abbreviated long forms used again after the acronym's first use), "
                    f"but {FINDINGS_REL} raises no M1 finding, the M1 coverage row (its "
                    f"disposition and its detail cell) does not give a recorded REASON for those "
                    f"rows (a bare `M1b` mention is not a disposition), and the table's own rows "
                    f"carry no recorded reason. Every M1b row is "
                    f"either an M1(k) finding (one per instance) or a row disposed OK with a "
                    f"recorded reason -- in the row's own `disposition` cell and/or in the M1 "
                    f"coverage row, which then names M1b and says why -- the defect must not "
                    f"vanish between the artifact and the findings.")
    # 3g. A CODE-PROVEN FMT-CL1 ROW CANNOT BE DELETED. The disposition gate
    #     forbids closing the cover-letter-stamp row OK without the journal's
    #     own quoted override; this re-runs the same scan that seeded it, so the
    #     row must still be in the table the reviewer disposed.
    if want_parity_artifacts:
        errs.extend(cover_letter_row_survival_problems(ctx, sb))


# The M1b table's own column names and row-number headers. A session that
# re-writes the seeded table (adding `#` and a `disposition` column) must not
# have its header counted as one more residue: the old counter read the header
# row as an instance, so a 25-row table was reported (and re-prompted) as 26.
M1B_HEADER_CELLS = {"#", "n", "no", "no.", "row", "id", "acronym", "term", "context", "file",
                    "location", "file:line", "file : line", "long form as written", "long form",
                    "variant", "excerpt", "evidence", "disposition", "resolution", "verdict",
                    "note", "notes", "why", "—", "-"}
# The script's own "nothing to report" row (`| — | — | — | — | no long-form re-use
# detected |`) is a placeholder, not an instance: counting it would demand an M1
# finding for an empty table.
M1B_EMPTY_CELLS = {"—", "-", "–", "--", "n/a", "n.a.", "none", ""}
M1B_EMPTY_ROW_MARKER = "no long-form re-use detected"
# The disposition columns of the artifact tables (`resolution` is the same
# contract under the placeholder/ledger layouts' own name).
M1B_DISPOSITION_COLUMNS = ("disposition", "resolution", "verdict")


def _m1b_table(m1_md: str):
    """(header, data rows) of the M1 artifact's M1b instance table.

    ([], []) when the section/table is absent. The table's first `|` line is its
    header and is never a data row; a repeated header (a long table split by an
    interpolated note) is recognized by its own words and dropped too; a
    non-table line AFTER the first data row ends the table, so a later section's
    rows are not counted as M1b instances.

    The cell splitter is local to this block on purpose: the gate must behave
    identically when the block is lifted into an older PINNED copy of the
    pipeline (a run root keeps the script it was set up with), and those copies
    carry the same parsing under other helper names.
    """
    lines = str(m1_md or "").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().startswith("## M1b")), None)
    if start is None:
        return [], []
    header, rows = [], []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if s.startswith("## "):                 # the next section starts here
            break
        if not s.startswith("|"):
            if rows:                            # the table is over
                break
            continue
        cells = _m1b_cells(s)
        if not cells or _m1b_separator(cells):
            continue
        if not header:
            header = cells
            continue
        if len(cells) == len(header) and all(c.lower() in M1B_HEADER_CELLS for c in cells):
            continue                            # a repeated header, not an instance
        if cells[0].lower() in M1B_EMPTY_CELLS \
                or M1B_EMPTY_ROW_MARKER in " ".join(cells).lower():
            continue                            # the script's empty-table placeholder
        rows.append(cells)
    return header, rows


def _m1b_cells(line: str) -> list:
    """The cells of one `| … |` line; a `\\|` inside a cell stays content."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, i = [], [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            cur.append(ch)
            cur.append(s[i + 1])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    cells.append("".join(cur))
    return [c.strip().replace("\\|", "|") for c in cells]


def _m1b_separator(cells: list) -> bool:
    """`|---|---|` / `|:--:|` -- the table's header/body divider."""
    return bool(cells) and all("-" in c and set(c) <= set("-: ") for c in cells)


def m1b_row_count(m1_md: str) -> int:
    """Data rows in the M1 artifact's M1b instance table (0 when absent/empty)."""
    return len(_m1b_table(m1_md)[1])


def _is_recorded_reason(cell: str) -> bool:
    """Is this disposition cell a reason rather than a bare verdict word?"""
    text = re.sub(r"\s+", " ", str(cell or "")).strip()
    return len(text) >= 12 and re.search(r"[A-Za-z]{3}", text) is not None


def m1b_rows_disposed(m1_md: str) -> bool:
    """Does the M1b table dispose every one of its own rows with a reason?

    The skill's rule (k) lets a residue row be closed in the ARTIFACT ("dispose
    a row OK ONLY with a recorded reason: a quoted title ..., a phrase that is
    genuinely a different term of art, or a generated rendering ..."), while the
    orchestrator's prompt asks for that reason in the M1 coverage row. Either
    evidence surface answers the gate; this helper is the artifact-side one.
    It cannot accept an un-disposed table: a table without a disposition column,
    or with an empty / `-` / bare-`OK` cell anywhere, returns False.
    """
    header, rows = _m1b_table(m1_md)
    if not rows:
        return False
    key = next((i for i, h in enumerate(header)
                if str(h).strip().lower() in M1B_DISPOSITION_COLUMNS), None)
    if key is None:
        return False
    for cells in rows:
        # A row too short to carry the disposition cell has no recorded reason.
        if not _is_recorded_reason(cells[key] if key < len(cells) else ""):
            return False
    return True


# A coverage-row note is a REASON, not a bare token: it must say why the M1b
# rows are not findings. "M1b long forms were reviewed" mentions the token and
# says nothing about the rows; the gate used to accept it (any `m1b` substring
# short-circuited the check), so a review with an M1b table and no disposition
# passed. The prompt names the acceptable grounds (a quoted title, a genuinely
# different term of art, a generated rendering), so those markers are what the
# coverage row has to name.
_M1B_REASON_RE = re.compile(
    r"(?i)\b(?:because|since|reason|different|distinct|quoted|title|titles|expansion|"
    r"expanded|expansion|defining|defined|acronym|abbreviation|legitimate|bibliograph|"
    r"reference|references|not\s+a\s+finding|no\s+finding|ok\b|clean|disposed|"
    r"intentional|verbatim|species|gene|proper\s+name|rendering)\b")


def _m1b_coverage_reason(text: str) -> bool:
    """Does the M1 coverage row NAME M1b and give a reason (not just the token)?"""
    text = str(text or "")
    i = text.lower().find("m1b")
    if i < 0:
        return False
    clause = text[i + 3:]
    if len(clause.strip()) < 12 or not re.search(r"[A-Za-z]{3}", clause):
        return False
    return bool(_M1B_REASON_RE.search(clause))


def coverage_row_text(row) -> str:
    """A coverage row's own words, lowercased (its `disposition` + `detail`).

    Several gates ask whether the session ACCOUNTED for something in the
    coverage table, and the master prompt sends the specifics to the row's
    `detail` cell ("a row disposed OK with a recorded reason in the M1 coverage
    detail"). Reading only the `disposition` cell re-failed a session for
    following the prompt, so the gate reads the whole row.
    """
    if not isinstance(row, dict):
        return ""
    parts = [str(v) for k, v in row.items()
             if k != "check" and isinstance(v, (str, int, float))]
    return " ".join(parts).lower()


def _finding_id_occurrences(pid: str, blob: str) -> int:
    """How many whole-token times `pid` occurs in `blob` (0 when absent)."""
    return len(re.findall(r"(?<![A-Za-z0-9])" + re.escape(pid) + r"(?![A-Za-z0-9])",
                          str(blob or "")))


def _finding_id_mentioned(pid: str, blob: str) -> bool:
    """Whole-token occurrence of a finding id inside `blob`.

    The reconciliation gate must accept a prior id only when it is genuinely
    mentioned ("carried over from F-012", "prior F-012: not reproducible"). A
    plain substring test also accepts a DIFFERENT id that merely extends it: a
    new "F-0123" contains "F-012", so a dropped prior finding passed the gate.
    Anchoring on alphanumerics keeps hyphens usable inside prose ("the F-012
    related note") while rejecting any alphanumeric continuation.
    """
    return _finding_id_occurrences(pid, blob) > 0


def archive_review_outputs(ctx: Ctx, r: int) -> Path:
    """Copy a round's review deliverables into reports/round<r>_review/.

    The next round's reviewer gets them as its carry-over reference, and the
    operator keeps the frozen finding list even after the sandbox is pruned.
    Best-effort: an archive failure must never fail the round.

    Under a `--review-split` round the MERGED finding list and the whole
    discovery round live in part B (`merge_review_parts` writes them there), so
    B is the archive source when it exists: reading only part A dropped every
    `X-*` finding and every `M37+` proposal from the next round's
    `prior_round/`, which made the convergence gate vacuous.
    """
    dst = ctx.reports_dir / f"round{int(r)}_review"
    rec = ctx.run(rid_guided_review(r)) if guided_review_enabled(ctx) else None
    sb = ctx.sandbox_of(rec) if rec is not None else None
    b_sb = None
    if rec is not None:
        try:
            if review_split_of(ctx) != "off":
                rec_b = ctx.run(rid_guided_review_b(r))
                b_sb = ctx.sandbox_of(rec_b) if rec_b is not None else None
        except Exception:                                        # noqa: BLE001
            b_sb = None

        def _src(rel: str) -> Path:
            if b_sb is not None and (b_sb / rel).is_file():
                return b_sb / rel
            return sb / rel

        mapping = ((FINDINGS_REL, "findings.json"),
                   (FINDINGS_MD_REL, "findings.md"),
                   ("guided_review/round2/findings_extra.json", "findings_extra.json"),
                   ("guided_review/round2/findings_extra.md", "findings_extra.md"),
                   ("guided_review/round2/new_sweeps.md", "new_sweeps.md"),
                   ("guided_review/round2/round2_summary.md", "round2_summary.md"))
        for rel, name in mapping:
            p = _src(rel)
            # A FILE symlink is not a review deliverable: `copy2` would archive
            # the link target's bytes (outside content) as the round's frozen
            # finding list (F50/F51).
            if not p.is_file() or p.is_symlink():
                continue
            try:
                dst.mkdir(parents=True, exist_ok=True)
                if name == "findings_extra.json":
                    # Archive the MERGED list (the review's X-* rows plus the probe
                    # session's X-9xx rows), exactly as every downstream copy holds
                    # it. The next round's prior_round/ copy and its reconciliation
                    # gate then cover probe findings with no extra machinery -- a
                    # defect the probe found cannot vanish between rounds.
                    base = read_json(p, revive=False, lenient=True)
                    merged, _rows, _remap = cold_start_merged_review_doc(
                        ctx, r, base if isinstance(base, dict) else {})
                    if merged is not None:
                        write_json_atomic(dst / name, merged)
                        continue
                shutil.copy2(p, dst / name)
            except OSError:
                continue
    # `--no-guided-review`: there is no guided-review sandbox, but the round's
    # frozen list is still the synthesized view the auditor/revisers read. Write
    # it where `review_findings_rows()` looks, or the archive (and the
    # decision report's finding list) silently loses every X-9xx row (F03).
    if frozen_review_is_synthesized(ctx):
        try:
            dst.mkdir(parents=True, exist_ok=True)
            write_json_atomic(dst / "findings.json", _frozen_review_doc(r))
            write_json_atomic(dst / "findings_extra.json",
                              {"findings": list(cold_start_findings_rows(ctx, r) or []),
                               "source": "cold_start_review", "guided_review": "off",
                               "named_gap": GUIDED_REVIEW_GAP})
        except OSError:
            pass
    # The COLD-START REVIEW session's deliverables are archived beside the review's, so a
    # pruned root can still re-seed the same frozen list (`findings_cold_start_review.json`)
    # and the operator keeps the reproduction record with the round's review.
    cold_start_rec = ctx.run(rid_cold_start_review(r))
    if cold_start_rec is not None and str(cold_start_rec.get("status") or "") == "done":
        psb = ctx.sandbox_of(cold_start_rec)
        for rel, name in ((COLD_START_FINDINGS_REL, "findings_cold_start_review.json"),
                          (COLD_START_FINDINGS_MD_REL, "findings_cold_start_review.md"),
                          (COLD_START_COVERAGE_REL, "cold_start_coverage.md"),
                          (COLD_START_REPRO_REL, "cold_start_reproduction.md")):
            p = psb / rel
            if not p.is_file() or p.is_symlink():
                continue
            try:
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst / name)
            except OSError:
                continue
    # A concern-scoped round's producer is the CONCERNS run: archive the ledger
    # and its coverage beside the review deliverables, so a pruned root keeps
    # the round's finding source (F03).
    if journal_is_scoped(ctx):
        con = ctx.run(rid_concerns(r))
        if con is not None and str(con.get("status") or "") == "done":
            csrc = ctx.sandbox_of(con) / "concerns"
            if csrc.is_dir():
                for p in sorted(csrc.iterdir()):
                    if not p.is_file() or p.is_symlink():
                        continue
                    try:
                        dst.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(p, dst / p.name)
                    except OSError:
                        continue
    # The CSV export of the same findings rides beside the archive (one row per
    # finding, with the review's own evidence/explanation as the verbal
    # description), so an operator gets the round's defect list without parsing
    # JSON. Best-effort, like the archive itself.
    try:
        if any((dst / name).is_file() for name, _src in REVIEW_FINDINGS_SOURCES):
            write_round_review_findings(ctx, r)
    except OSError:
        pass
    return dst


def prior_review_dir(ctx: Ctx, r: int):
    """Where round r-1's archived review lives (falling back to its sandbox)."""
    if r <= 1:
        return None
    arch = ctx.reports_dir / f"round{int(r) - 1}_review" / "findings.json"
    if arch.is_file():
        return arch.parent
    # Under --review-split the frozen list is session B's MERGED output; reading
    # A alone handed the next review a partial list (F38). Prefer B, then A.
    candidates = ([rid_guided_review_b(r - 1), rid_guided_review(r - 1)]
                  if review_split_of(ctx) != "off" else [rid_guided_review(r - 1)])
    for rid in candidates:
        rec = ctx.run(rid)
        if rec is None:
            continue
        sb = ctx.sandbox_of(rec) / GUIDED_REVIEW_DIR
        if (sb / "findings.json").is_file():
            return sb
    return None


PRIOR_ROUND_RULE_NONE = """PRIOR-ROUND FINDINGS: none -- this is the first round, so there is no
  earlier finding list to reconcile. Run the workflow exactly as described above."""

PRIOR_ROUND_RULE = """PRIOR-ROUND FINDINGS (read-only; round @@ROUND@@ reviews the champion of round @@PREV@@):
  * The previous round's review of the same lineage is copied next to you as prior_round/:
    prior_round/findings.json (+ findings_extra.json, new_sweeps.md, round2_summary.md). It is
    READ-ONLY and hash-verified: never modify it.
  * WHY: a single review pass has been measured to miss defects that another pass of the SAME
    corpus finds, so a prior finding must never vanish silently. BEFORE running your sweeps,
    re-check EVERY finding in prior_round/findings.json AND every discovery finding in
    prior_round/findings_extra.json against the current base/ corpus and give each one exactly one
    of two dispositions, recorded where the orchestrator can see it
    (that file carries every X-* row, INCLUDING the X-9xx rows an independent cold-start session
    filed when that round ran one):
      - STILL PRESENT -> include it in YOUR findings with a NEW id, and put the exact marker
        "carried over from <prior-id>" in the explanation field (for example
        "carried over from F-012");
      - NO LONGER PRESENT (fixed, or the quoted text/location is gone) -> write
        "prior <prior-id>: not reproducible in base/" into the summary note of findings.md.
    Do not re-file a prior finding that no longer holds, and do not drop one that does.
  * The orchestrator refuses the review if any prior finding id appears in NEITHER
    findings.json nor findings.md, so complete this reconciliation first.
  * The previous round's DISCOVERY PROPOSALS (prior_round/new_sweeps.md, when present) are the
    convergence loop: every `## M<NN>` proposal in it is a class the last round could not yet
    check mechanically, so RE-PROBE each one against the current base/ corpus too. Record every
    proposal id where the orchestrator can see it -- run it as a probe row in
    guided_review/round2/probes.md / guided_review/round2/probe_results.md, or write
    "prior proposal <id>: no instances in base/" into guided_review/round2/new_sweeps.md or
    guided_review/round2/round2_summary.md. The orchestrator refuses the review if a prior proposal id
    appears NOWHERE in the round-2 artifacts (nor in findings.json/findings.md), because a
    discovered class that vanishes between rounds never becomes a mechanical check.
  * Carrying findings forward does NOT replace the sweeps: run the complete M1-M17 + J1-J5 set
    plus the pipeline-mandated M18-M24 checks, the rewrite-parity M25-M29 checks and the
    source-hierarchy reconciliation M30 (the
    classes a from-scratch rewrite fixes as it goes) and report your own new findings as usual."""


# ---------------------------------------------------------------------
# Structured-output validation (JSON / XML). An agent's structured output is a
# CONTRACT: a truncated scores.json, an empty findings.json or a half-written
# marker is a FAILED ATTEMPT, not a result to be interpreted. Anything that does
# not parse makes the run fail so the retry policy rebuilds the sandbox and the
# agent runs again -- a judge panel must never be assembled from unparseable
# sheets, and a finding list must never be read from a broken file.
# ---------------------------------------------------------------------
STRUCTURED_OUTPUT_JSON = {
    "guided_review": ("_pipeline_done.json", "guided_review/findings.json",
               "guided_review/round2/findings_extra.json"),
    # The cold-start review's finding list (with its `checked` inventory and any
    # verifier declarations): a truncated one must fail the attempt like every
    # other stage's structured output (the postcheck cannot re-run verifiers
    # from a broken file).
    "cold_start_review": ("_pipeline_done.json", COLD_START_FINDINGS_REL),
    # The audit's sheet is validated in full by `audit_artifact_problems`, but the
    # PARSE gate belongs here too: a truncated audit.json must be caught by the
    # same structured-output scan as every other stage's (and by manual mode's
    # "the output stopped changing" detector).
    "audit": ("_pipeline_done.json", "audit/audit.json"),
    "rewrite": ("_pipeline_done.json",),
    "revise": ("_pipeline_done.json", "revised/revision_report.json"),
    "integrate": ("_pipeline_done.json", "integrated/revision_report.json"),
    "judge": ("_pipeline_done.json", "scores.json"),
    # The journal stages are part of the same safety net as every other kind:
    # their machine-readable ledgers must be parse-checked (and counted by the
    # attempt-management helpers) instead of being invisible to them.
    "feedback": ("_pipeline_done.json", JOURNAL_CONCERNS_JSON_REL),
    "concerns": ("_pipeline_done.json", JOURNAL_CONCERNS_JSON_REL),
    "response": ("_pipeline_done.json", JOURNAL_RESPONSE_MAP_REL),
}
STRUCTURED_OUTPUT_ROOTS = {
    "guided_review": (GUIDED_REVIEW_DIR,),
    "cold_start_review": (COLD_START_DIR,),
    "rewrite": ("rewritten", "code"),
    "revise": ("revised", "code"),
    "integrate": ("integrated", "code"),
    "judge": ("judge_review",),
    "feedback": ("concerns",),
    "concerns": ("concerns",),
    "response": ("response",),
}


def _input_digests(rec: dict) -> set:
    """sha256 of every read-only INPUT file of a run, whatever its path.

    Content, not path, is what identifies an inherited file: the revise stage is
    REQUIRED to copy the base's documents into revised/, so the same bytes appear
    under a different relative path, and a path-keyed index would fail to
    recognize them (a false failure of a correctly-produced package). Matching on
    the digest also covers an empty file that was inherited verbatim.
    """
    digests = set()
    for _area, man in (rec.get("inputs_manifest") or {}).items():
        for _rel, dig in ((man or {}).get("files") or {}).items():
            if dig:
                digests.add(dig)
    return digests


def _input_doc_keys(rec: dict) -> set:
    """Version-token-stripped basenames of the run's read-only input files.

    Used only for EMPTY files, whose bytes carry no information (every empty file
    has the same digest): an empty file counts as inherited only when the input
    tree already carried a file of that (version-token-insensitive) name, so an
    agent's own empty/truncated output is still reported as unfinished.
    """
    keys = set()
    for _area, man in (rec.get("inputs_manifest") or {}).items():
        for rel in ((man or {}).get("files") or {}):
            keys.add(_doc_key(Path(rel).name))
    return keys


EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def structured_output_files(sb: Path, rec: dict) -> list:
    """(rel, path) of every JSON/XML/DOCX file the run was supposed to WRITE.

    Difference-tracking auxiliaries (see TRACKING_AUX_NAME_RE) are skipped: they
    are not submission content anywhere in this pipeline (see AUX_FILES_RULE), so a
    tracked-changes writer that degrades or emits a marker file must not fail the
    run. The pipeline's own tracked-changes copies are produced independently under
    <root>/redlines/ and <root>/tracking/.
    """
    kind = rec.get("kind")
    out, seen = [], set()
    for rel in STRUCTURED_OUTPUT_JSON.get(kind, ()):
        p = sb / rel
        if p.is_file() and rel not in seen:
            seen.add(rel)
            out.append((rel, p))
    for root_rel in STRUCTURED_OUTPUT_ROOTS.get(kind, ()):
        d = sb / root_rel
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file() or _is_aux_doc(p.name) \
                    or p.suffix.lower() not in (".json", ".xml", ".docx"):
                continue
            rel = p.relative_to(sb).as_posix()
            if "work" in Path(rel).parts:
                # Scratch, never a deliverable. A judge reorganizes the blinded
                # views into `judge_review/work/` (normalized copies, renders,
                # sweeps) and one of those intermediate .docx can be truncated
                # mid-write without saying anything about the panel: the 2026-09-23
                # round-1 panel failed two sessions on
                # `judge_review/work/norm_*/f000N.docx is malformed DOCX` even
                # though their scores.json and their frozen views were intact.
                continue
            if rel not in seen:
                seen.add(rel)
                out.append((rel, p))
    return out


def _structured_problem_for(rel: str, p: Path):
    """One parse problem string for a structured-output file, or None."""
    if p.is_symlink():
        # A symlink is not agent-written structured output: name it as such
        # instead of reporting the target's size/contents (F38).
        return f"{rel} is a symlink; structured output must be a regular file"
    if json_file_too_big(p):
        return (f"{rel} is {p.stat().st_size} bytes (over the "
                f"{MAX_JSON_BYTES // (1024 * 1024)} MiB agent-output limit): refusing to parse "
                f"it -- a runaway/looping agent must be retried, never allowed to exhaust this "
                f"machine's memory")
    # Shared regular-file/no-follow/byte-budget reader: a planted symlink is a
    # named problem, not a whole-file read of its target (F38).
    text = read_text_bounded(p)
    if text is None:
        return f"{rel} could not be read (it is a symlink/non-regular file or over the byte budget)"
    if not text.strip():
        return f"{rel} is EMPTY/unfinished (structured output)"
    try:
        if p.suffix.lower() == ".json":
            # Agent-written: accept the same recoverable shapes read_json
            # accepts (UTF-8 BOM, a markdown fence or a short prose margin
            # around a COMPLETE document). A truncated payload still fails.
            if _json_from_text(text, True) is None:
                json.loads(text.lstrip("\ufeff"))       # raise, for the message below
        elif p.suffix.lower() == ".docx":
            with zipfile.ZipFile(p) as z:
                data = _docx_xml_part(z, "word/document.xml")
            if data is None:
                raise ValueError("the DOCX part is over the size/entity budget")
            ET.fromstring(data)
        else:
            ET.fromstring(text)
    except (ValueError, ET.ParseError, zipfile.BadZipFile, KeyError, RuntimeError,
            NotImplementedError) as e:
        kind = p.suffix.lstrip(".").upper()
        return f"{rel} is malformed {kind} ({str(e)[:160]})"
    return None


def _structured_output_scan(ctx: Ctx, rec: dict) -> tuple:
    """(agent problems, inherited-input notes) for a run's structured outputs.

    Read-only inputs are never blamed: a target corpus may legitimately contain
    JSON/XML the agent did not write, so a scanned file that is byte-identical to
    ANY input file is skipped -- matched by content digest, because the file is
    expected to sit at a different path in the output directory (the contract-
    named output files are always checked). Such an inherited file that is
    MALFORMED is still surfaced as a note: it is a pre-existing defect the
    author must fix, never something the arm did.
    """
    sb = ctx.sandbox_of(rec)
    kind = rec.get("kind")
    contract = set(STRUCTURED_OUTPUT_JSON.get(kind, ()))
    input_digests = _input_digests(rec)
    input_keys = None
    probs, notes = [], []
    for rel, p in structured_output_files(sb, rec):
        inherited = False
        if rel not in contract:
            try:
                dig = sha256_file(p)
                inherited = dig in input_digests
                if inherited and dig == EMPTY_SHA256:
                    # An empty file's bytes identify nothing; require the name too
                    # so a brand-new empty/truncated output is still reported.
                    if input_keys is None:
                        input_keys = _input_doc_keys(rec)
                    inherited = _doc_key(Path(rel).name) in input_keys
            except OSError:
                inherited = False
        problem = _structured_problem_for(rel, p)
        if problem is None:
            continue
        if inherited:
            notes.append(f"{problem} -- and this file was ALREADY like that in the run's "
                         f"read-only input (not the agent's fault; the author must fix it)")
        else:
            probs.append(problem)
    return probs, notes


def structured_output_problems(ctx: Ctx, rec: dict) -> list:
    """Parse errors in a run's OWN structured output (empty/truncated counts)."""
    return _structured_output_scan(ctx, rec)[0]


def inherited_structured_output_notes(ctx: Ctx, rec: dict) -> list:
    """Pre-existing malformed structured inputs carried forward by a run."""
    return _structured_output_scan(ctx, rec)[1]


# =====================================================================
# OPAQUE IDENTIFIER / EXTERNALLY-ASSIGNED FACT EVIDENCE GATE
#
# E-mail addresses are only one member of a larger class. A DOI, accession,
# ORCID, UUID/UID, git commit, funding/grant number, registry/protocol/version
# id or a reagent/cell-line/domain-specific identifier is a FACT: a name, a
# pattern, an edit-distance guess or a "standard" format is not evidence. The
# email gate (p04 `email_address_change_problems`) keeps its own contact-specific
# behaviour; this gate covers the rest and lets any INDEPENDENT record stand as
# evidence (another occurrence in the input corpus, raw_data, the base's analysis
# code, a public registry, Crossref/DataCite/ORCID, a repository page), not only
# a web search.
#
# Pure ADDITIONS for new content (a new reference's DOI) are not corrections and
# are allowed. A replacement, shortening or renumbering of an existing value needs
# evidence; without it the package stays byte-identical and the suggested
# correction belongs in the high-priority manual TODO, never in the manuscript.
# =====================================================================

FACT_VERIFICATION_JSON_REL = "work/FACT_VERIFICATION.json"
FACT_CLASSES = ("doi", "orcid", "uuid", "accession", "commit", "grant", "uid", "domain")
FACT_CLASS_LABELS = {
    "doi": "DOI", "orcid": "ORCID", "uuid": "UUID", "accession": "ACCESSION",
    "commit": "GIT COMMIT / HASH", "grant": "FUNDING/GRANT NUMBER", "uid": "UID",
    "domain": "DOMAIN-SPECIFIC ID",
}


def _fact_label(cls: str) -> str:
    return FACT_CLASS_LABELS.get(cls, str(cls).upper())


FACT_DOC_SUFFIXES = EMAIL_DOC_SUFFIXES + (".bib",)
FACT_MAX_FILE_BYTES = EMAIL_MAX_FILE_BYTES
FACT_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.I)
FACT_ORCID_RE = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dXx]\b")
FACT_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
FACT_ACCESSION_RE = re.compile(
    r"\b(?:GSE|GSM|SRP|SRR|PRJNA|PRJEB|PRJDB|SAMN|SAMD|ERP|ERS|ERR|EZID)\d{3,}\b",
    re.I)
FACT_COMMIT40_RE = re.compile(r"\b(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\b")
FACT_COMMIT_CONTEXT_RE = re.compile(
    r"(?i)\b(?:commit|sha(?:-?1)?|git|revision|hash)\b[^\n]{0,40}?"
    r"\b([0-9a-f]{7,39})\b")
FACT_COMMIT_URL_RE = re.compile(
    r"(?i)github\.com/[^/\s]+/[^/\s]+/commit/([0-9a-f]{7,40})")
FACT_GRANT_CODE_RE = re.compile(
    r"\b\d?(?:R|K|F|T|P|U|M)\d{2}\s*[-\s]?\s*[A-Z]{2}\s*[-\s]?\s*\d{5,}\b")
FACT_GRANT_CONTEXT_RE = re.compile(
    r"(?i)\b(?:grant|funding|award|contract)\b[^\n]{0,30}?"
    r"(?:no\.?|number|id|code|#)?\s*[:=]?\s*"
    r"(?=[A-Z0-9\-/.%]*\d)([A-Z0-9][A-Z0-9\-/.%]{4,})\b")
FACT_RS_RE = re.compile(r"\brs\d{3,}\b", re.I)
FACT_DOMAIN_ID_RE = re.compile(
    r"\b(?:(?:ENSG|ENST|ENSP)\d{11}|(?:NM|NP|NR|XM|XP)_\d+|"
    r"(?:CVCL|ATCC)_[A-Za-z0-9]+|(?:EMD|EMDB)-\d+)\b", re.I)
FACT_DOMAIN_RE = re.compile(
    r"(?i)\b(?:RRID|Cellosaurus|ATCC|cat(?:alog)?\.?\s*(?:no\.?|number|#)|lot|batch|"
    r"strain|plasmid|primer|antibody|reagent|protocol|registry|dbSNP|UniProt|PDB|EMDB|"
    r"GenBank|RefSeq|Ensembl|ClinVar|COSMIC|cell\s+line|clone)\b[^\n]{0,25}?"
    r"[:=#]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{2,})\b")
FACT_UID_RE = re.compile(
    r"(?i)\b(?:UID|ID|identifier|accession|protocol|registry|trial\s+registration|"
    r"IRB|ethics(?:\s+(?:approval|number|id))?)\b[^\n]{0,20}?"
    r"[:=#]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{3,})\b")
FACT_KIND_ALIASES = {
    "doi": "doi", "orcid": "orcid", "uuid": "uuid", "uid": "uid", "id": "uid",
    "identifier": "uid", "accession": "accession", "accession_id": "accession",
    "commit": "commit", "git": "commit", "sha": "commit", "grant": "grant",
    "grant_number": "grant", "funding": "grant", "award": "grant", "domain": "domain",
    "reagent": "domain", "cell_line": "domain", "registry": "uid", "protocol": "uid",
    "version": "uid", "email": "email",
}
_FACT_COMMON_WORDS = frozenset({
    "number", "identifier", "protocol", "registry", "approval", "standard", "version",
    "release", "model", "strain", "clone", "batch", "lot", "sample", "table", "figure",
    "section", "supplementary", "accession", "grant", "funding", "award", "contract",
})


def _clean_fact_token(raw: str) -> str:
    return str(raw or "").strip().strip(".,;:)]}>'\"")


def _fact_token_looks_opaque(cls: str, token: str) -> bool:
    token = str(token or "").strip()
    if cls in ("doi", "orcid", "uuid", "accession", "commit"):
        return bool(token)
    if len(token) < 4:
        return False
    if re.fullmatch(r"\d{4}(?:-\d{4})?", token):
        return False
    if cls == "grant":
        return bool(re.search(r"\d", token)) and (
            bool(re.search(r"[A-Za-z]", token)) or len(token) >= 5)
    if token.lower() in _FACT_COMMON_WORDS:
        return False
    if token.isdigit() and len(token) <= 4:
        return False
    return bool(re.search(r"\d", token) or any(c.isupper() for c in token)
                or any(c in token for c in "-_/."))


def _canonical_fact_token(cls: str, token: str) -> str:
    if cls == "doi":
        return token.lower()
    if cls in ("orcid", "accession"):
        return token.upper()
    if cls in ("uuid", "commit"):
        return token.lower()
    if cls == "grant":
        return re.sub(r"[\s\-]", "", token).upper()
    return token.casefold()


def _fact_token_kind(token: str) -> str:
    token = _clean_fact_token(token)
    if not token:
        return ""
    for cls, rx in (("doi", FACT_DOI_RE), ("orcid", FACT_ORCID_RE),
                    ("uuid", FACT_UUID_RE), ("accession", FACT_ACCESSION_RE),
                    ("commit", re.compile(r"[0-9a-fA-F]{7,64}")),
                    ("grant", FACT_GRANT_CODE_RE), ("domain", FACT_DOMAIN_ID_RE),
                    ("domain", FACT_RS_RE)):
        if rx.fullmatch(token):
            return cls
    return ""


def _fact_token_map(text: str) -> dict:
    """{class: {canonical: display}} for one text chunk, no overlapping tokens."""
    found = {cls: {} for cls in FACT_CLASSES}
    claimed = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < b and end > a for a, b in claimed)

    def add(cls: str, raw: str, start: int, end: int) -> None:
        token = _clean_fact_token(raw)
        if not token or overlaps(start, end) or not _fact_token_looks_opaque(cls, token):
            return
        key = _canonical_fact_token(cls, token)
        if key:
            found[cls].setdefault(key, token)
            claimed.append((start, end))

    for m in FACT_DOI_RE.finditer(text or ""):
        add("doi", m.group(0), m.start(), m.end())
    for m in FACT_ORCID_RE.finditer(text or ""):
        add("orcid", m.group(0), m.start(), m.end())
    for m in FACT_UUID_RE.finditer(text or ""):
        add("uuid", m.group(0), m.start(), m.end())
    for m in FACT_ACCESSION_RE.finditer(text or ""):
        add("accession", m.group(0), m.start(), m.end())
    for m in FACT_COMMIT40_RE.finditer(text or ""):
        add("commit", m.group(0), m.start(), m.end())
    for m in FACT_COMMIT_URL_RE.finditer(text or ""):
        add("commit", m.group(1), m.start(1), m.end(1))
    for m in FACT_COMMIT_CONTEXT_RE.finditer(text or ""):
        add("commit", m.group(1), m.start(1), m.end(1))
    for m in FACT_GRANT_CODE_RE.finditer(text or ""):
        add("grant", m.group(0), m.start(), m.end())
    for m in FACT_GRANT_CONTEXT_RE.finditer(text or ""):
        add("grant", m.group(1), m.start(1), m.end(1))
    for m in FACT_RS_RE.finditer(text or ""):
        add("domain", m.group(0), m.start(), m.end())
    for m in FACT_DOMAIN_ID_RE.finditer(text or ""):
        add("domain", m.group(0), m.start(), m.end())
    for m in FACT_DOMAIN_RE.finditer(text or ""):
        add("domain", m.group(1), m.start(1), m.end(1))
    for m in FACT_UID_RE.finditer(text or ""):
        add("uid", m.group(1), m.start(1), m.end(1))
    return found


def _fact_tokens_in_sources(sources, evidence: bool = False) -> tuple:
    """({class: {canonical: display}}, coverage gaps) over document sources."""
    found = {cls: {} for cls in FACT_CLASSES}
    gaps = []
    suffixes = EMAIL_EVIDENCE_SUFFIXES if evidence else FACT_DOC_SUFFIXES

    def skipped(rel: str, name: str, excluded) -> bool:
        parts = rel.split("/")
        if excluded and parts and parts[0] in excluded:
            return True
        if "work" in parts[:-1] or name.startswith("~$"):
            return True
        if (is_bookkeeping_name(name) or is_non_submitted_readme_name(name)
                or is_non_document_name(name)):
            return True
        if evidence:
            area = evidence_area_of(rel)
            if area in (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR):
                return True
            return bool(is_journal_feedback_name(name)
                        or authored_reply_name(name))
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
                if path.stat().st_size > FACT_MAX_FILE_BYTES:
                    gaps.append(f"{prefix + rel}: larger than "
                                f"{FACT_MAX_FILE_BYTES // (1024 * 1024)} MB; not scanned "
                                f"for identifiers")
                    continue
            except OSError as e:
                gaps.append(f"{prefix + rel}: stat failed ({type(e).__name__}: {e})")
                continue
            texts, gap = _email_texts_in_file(path)
            if gap:
                gaps.append(f"{prefix + rel}: {gap}; not scanned for identifiers")
                continue
            for text in texts:
                for cls, values in _fact_token_map(text).items():
                    for key, display in values.items():
                        found[cls].setdefault(key, display)
        for path in _files_under_ci(src, EMAIL_UNSCANNED_SUFFIXES):
            try:
                rel = path.relative_to(src).as_posix()
            except ValueError:                                     # pragma: no cover
                continue
            if skipped(rel, path.name, excluded):
                continue
            gaps.append(f"{prefix + rel}: unsupported editable format "
                        f"({path.suffix.lower()}); not scanned for identifiers")
    return found, gaps


def _fact_verification_rows(pkg: Path) -> tuple:
    """(valid independent-record rows, problems) from work/FACT_VERIFICATION.json."""
    path = Path(pkg) / FACT_VERIFICATION_JSON_REL
    if not path.is_file():
        return [], []
    data = read_json(path, revive=False, lenient=True)
    if data is None:
        return [], [f"{FACT_VERIFICATION_JSON_REL}: not readable as JSON"]
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
        return [], [f"{FACT_VERIFICATION_JSON_REL}: expected a list or an object"]
    records, problems = [], []

    def pick(row: dict, *keys) -> str:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    for i, row in enumerate(rows_raw):
        where = f"{FACT_VERIFICATION_JSON_REL}[{i}]"
        if not isinstance(row, dict):
            problems.append(f"{where}: not an object")
            continue
        raw_kind = pick(row, "kind", "type", "class", "identifier_kind")
        kind = FACT_KIND_ALIASES.get(raw_kind.strip().lower().replace(" ", "_")
                                     .replace("-", "_"), "")
        after = _clean_fact_token(pick(row, "after", "value", "corrected", "new"))
        if not kind and after:
            kind = _fact_token_kind(after) or "uid"
        if kind == "email":
            continue                       # the contact gate owns addresses
        if not kind:
            problems.append(f"{where}: no `kind` (doi/orcid/uuid/accession/commit/"
                            f"grant/uid/domain)")
            continue
        before = _clean_fact_token(pick(row, "before", "original", "old"))
        source_url = pick(row, "source_url", "url", "source", "lookup_url")
        query = pick(row, "query", "search", "search_query", "lookup")
        checked_at = pick(row, "checked_at", "date", "verified_at", "checked")
        evidence = pick(row, "evidence", "quote", "excerpt", "finding")
        bad = []
        if not after:
            bad.append("no `after` value")
        elif kind in ("doi", "orcid", "uuid", "accession", "commit"):
            if _fact_token_kind(after) != kind and not (
                    kind == "commit" and re.fullmatch(r"[0-9a-fA-F]{7,64}", after)):
                bad.append(f"`after` does not match the declared kind {kind!r}")
        elif not _fact_token_looks_opaque(kind, after):
            bad.append(f"`after` does not look like a {kind}")
        if before and not _fact_token_looks_opaque(kind, before):
            bad.append("`before` does not look like the declared kind")
        if not re.match(r"https?://", source_url, re.I):
            bad.append("`source_url` must be an http(s) URL")
        else:
            host = _email_url_host(source_url)
            if not host:
                bad.append("`source_url` has no host")
            elif _is_placeholder_email("x@" + host):
                bad.append("`source_url` uses a reserved/example host, not a real page")
        if len(query) < 3:
            bad.append("`query` is missing (the search/lookup string)")
        if not re.match(r"\d{4}-\d{2}-\d{2}\b", checked_at):
            bad.append("`checked_at` must be YYYY-MM-DD")
        if len(evidence) < 10 or (after and after.casefold() not in evidence.casefold()):
            bad.append("`evidence` must be a verbatim quote that contains the corrected value")
        if bad:
            problems.append(f"{where}: " + "; ".join(bad))
            continue
        records.append({
            "kind": kind, "after": after,
            "after_key": _canonical_fact_token(kind, after),
            "before": before,
            "before_key": _canonical_fact_token(kind, before) if before else "",
            "source_url": source_url, "query": query,
            "checked_at": checked_at, "evidence": evidence,
        })
    return records, problems


def _fact_similar(cls: str, a: str, b: str) -> bool:
    """A heuristic for a possible same-field correction, never a gate by itself."""
    if not a or not b or a == b:
        return False
    if cls == "doi":
        # A one/two-character DOI correction is a possible same-entry edit; a
        # new reference's DOI normally differs by more. This is a WARNING, not
        # a gate: new content is still allowed.
        return (len(a) == len(b)
                and sum(x != y for x, y in zip(a, b)) <= 2)
    if len(a) >= 7 and len(b) >= 7 and (a.startswith(b) or b.startswith(a)):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def fact_token_change_problems(before_sources, after_sources, pkg: Path,
                               label: str, evidence_sources=()) -> tuple:
    """(errors, warnings): an unverified identifier correction fails the stage.

    A replacement is caught when an old value of the class disappears and a new
    one appears (or the class count does not grow). A pure addition for new
    content is allowed; a similar added value is reported as a possible
    correction, so it can be verified or moved to the manual TODO.
    """
    before, before_gaps = _fact_tokens_in_sources(before_sources)
    after, after_gaps = _fact_tokens_in_sources(after_sources)
    evidence, evidence_gaps = _fact_tokens_in_sources(
        list(evidence_sources or ()), evidence=True)
    records, record_problems = _fact_verification_rows(Path(pkg))
    errs = list(record_problems)
    warns = [f"{label}: identifier coverage gap -- {g}"
             for g in (before_gaps + after_gaps + evidence_gaps)]
    for cls in FACT_CLASSES:
        bmap, amap = before.get(cls, {}), after.get(cls, {})
        added = set(amap) - set(bmap)
        removed = set(bmap) - set(amap)
        if not added:
            for key in sorted(removed):
                warns.append(
                    f"{label}: the delivered package no longer carries {_fact_label(cls)} "
                    f"{bmap[key]!r}. An externally-assigned identifier is not a deletion "
                    f"surface: restore it, or record the author query/evidence; do not delete "
                    f"it to resolve a finding")
            continue
        suspicious = bool(removed) or len(amap) <= len(bmap)
        if not suspicious:
            # New content is not a correction. Only flag a NEW value that is
            # close enough to an existing one to be a possible same-field edit.
            for key in sorted(added):
                for old_key in sorted(bmap):
                    if _fact_similar(cls, key, old_key):
                        warns.append(
                            f"{label}: a new {_fact_label(cls)} value {amap[key]!r} resembles the "
                            f"existing {bmap[old_key]!r}; if it is a correction, record "
                            f"independent evidence in {FACT_VERIFICATION_JSON_REL}, otherwise "
                            f"confirm it is new content")
                        break
            continue
        verified_after = {r["after_key"] for r in records if r["kind"] == cls}
        verified_before = {r["before_key"] for r in records
                           if r["kind"] == cls and r["before_key"]
                           and r["after_key"] in amap}
        allowed = set()
        old_display = bmap[sorted(removed)[0]] if removed else next(iter(bmap.values()), "?")
        for key in sorted(added):
            value = amap[key]
            if key in evidence.get(cls, {}) or key in verified_after:
                allowed.add(key)
                continue
            errs.append(
                f"{label}: the delivered package changes {_fact_label(cls)} value "
                f"{old_display!r} -> {value!r} without independent evidence. An "
                f"externally-assigned identifier is a FACT, not an inferable typo: a name, "
                f"pattern, edit-distance guess, plausible repository or 'standard' format is "
                f"not evidence. Restore the original; if a web search, a public registry, "
                f"Crossref/DataCite/ORCID or a repository page verifies {value!r}, record it in "
                f"{FACT_VERIFICATION_JSON_REL} (kind {cls!r}, before, after, query, a real "
                f"http(s) source_url, checked_at and a verbatim evidence quote containing "
                f"{value!r}); if you cannot verify it, keep the original byte-identical and put "
                f"`suggested: {value!r} (unverified)` in the high-priority manual TODO with the "
                f"location, current value and exact check")
        if removed and not (added <= allowed):
            for key in sorted(removed):
                if key in verified_before:
                    continue
                warns.append(
                    f"{label}: the delivered package no longer carries {_fact_label(cls)} "
                    f"{bmap[key]!r}; if the replacement is not independently verified, restore "
                    f"the original and put the suggested value in the manual TODO")
        for r in records:
            if (r["kind"] == cls and r["before_key"]
                    and r["before_key"] != r["after_key"]
                    and r["before_key"] in amap):
                warns.append(
                    f"{label}: the recorded correction {r['before']!r} -> {r['after']!r} left "
                    f"the superseded {_fact_label(cls)} value in the package; reconcile every "
                    f"occurrence to the SAME verified value, or record why they differ")
    return errs, warns



def structured_output_signature(ctx: Ctx, rec: dict) -> tuple:
    """(rel, size, mtime) of the run's structured outputs -- stability probe for
    manual mode, where a still-running agent may be mid-write."""
    sig = []
    for rel, p in structured_output_files(ctx.sandbox_of(rec), rec):
        try:
            st = p.stat()
            sig.append((rel, st.st_size, int(st.st_mtime)))
        except OSError:                                       # noqa: BLE001
            sig.append((rel, -1, -1))
    return tuple(sorted(sig))


def _candidate_corpus_files(sb: Path, out_dir: str = REVISED_DIR) -> list:
    """[(corpus-relative key, path)] of a candidate's output corpus.

    The candidate view mirrors corpus_sources(): everything under the run's
    output package (revised/, or rewritten/ for the rewrite arm; minus the
    stage's work/ scratch) plus everything under code/ (prefixed code/, which is
    how a corpus folds revised analysis code in). The difference-tracking
    auxiliaries (see TRACKING_AUX_NAME_RE) are skipped: they are never
    submission content and never count as "the file survived".
    """
    seen, out = set(), []
    for d, is_package in ((sb / out_dir, True), (sb / CODE_DIR, False)):
        if not d.is_dir():
            continue
        for p in _iter_tree_files(d, follow_dir_links=True):
            if not p.is_file() or _is_aux_doc(p.name) or is_word_owner_name(p.name):
                continue
            rel = p.relative_to(d).as_posix()
            if is_package and rel.split("/", 1)[0] in CORPUS_EXCLUDE_TOP:
                continue
            key = rel if is_package else ("code/" + rel)
            if key in seen:
                continue
            seen.add(key)
            out.append((key, p))
    return out


def _candidate_dest(sb: Path, rel: str, out_dir: str = REVISED_DIR):
    """Where a base file at corpus-relative path `rel` belongs in the candidate.

    A base file under code/ (round >= 2, where the base is a pinned champion
    with its code/ folded in) is restored into the sandbox's code/ directory;
    everything else goes to the run's output package (revised/, or rewritten/
    for the rewrite arm). Returns None only for a degenerate top-level entry
    literally named "code" that is a file, which cannot happen in a corpus this
    pipeline builds.
    """
    if rel == "code":
        return None
    if rel.startswith("code/"):
        return sb / CODE_DIR / rel[len("code/"):]
    return sb / out_dir / rel


# Extensions whose presence next to a PDF marks the PDF as a compiled twin of
# an editable source (see backfill_missing_files: a compiled PDF whose source
# was EDITED is deliberately left out of revised/ by the prompts, and the
# recovery layer must not undo that).
_PDF_TWIN_EXTS = (".doc", ".docx", ".tex", ".ltx", ".rtf", ".md", ".txt")


# =====================================================================
# THE READ-ONLY RAW-DATA DIRECTORY
#
# The corpus carries the author's raw data -- figure and table sources, the data
# tables, and the analysis snapshot the author's own scripts regenerate -- in
# `raw_data/`. It is an INPUT, not revision content: a package may CARRY it and
# never change it.
#
# No code path writes there: the version-token rule leaves the directory alone
# (revision_token_for_dir), and a package that edited, added, renamed or dropped
# a file inside it is put back byte-for-byte from the untouched original with a
# warning that names every file the stage touched. That is the same
# "deterministic repair, visible in the record" shape as backfill_missing_files:
# a rules-following stage is never punished for it, and a stage that rewrote a
# data table cannot ship the rewrite.
# =====================================================================

def _raw_data_key(rel: str) -> str:
    """The read-only identity of a raw-data file: its path, with any trailing
    version token stripped from the basename.

    A package carries the raw data under the file names its BASE used -- which,
    in a root set up from an earlier run's output corpus, are that run's token
    names (`dataset_summary-4f3a9c1.tsv`), and the documents in the package
    reference exactly those names. Matching by this key therefore restores the
    BYTES without ever renaming a file out from under a LaTeX \\input.
    """
    parts = norm_raw_data_name(rel).split("/")
    stem, dot, ext = parts[-1].rpartition(".")
    if dot:
        parts[-1] = DOC_TOKEN_RE.sub("", stem) + dot + ext
    return "/".join(parts)


def raw_data_entries(dirp: Path) -> dict:
    """{relative path: (relative path, sha256)} for `dirp`'s raw-data directory.

    The key is the EXACT corpus-relative path; `raw_data_pairs` applies the
    token-insensitive matching (see `_entries_in`).
    """
    area = dirp / raw_data_dirname(dirp)
    return _entries_in(area, dirp)


def _entries_in(area: Path, base: Path) -> dict:
    """{relative path: (relative path, sha256)} for ONE raw-data area directory.

    The key is the EXACT path, not `_raw_data_key`'s token-stripped form: that
    form is many-to-one (a trailing token or single letter is stripped, so
    `cohort_a.tsv` and `cohort_b.tsv` both fold to `cohort.tsv`), and folding
    two DISTINCT files into one dict key silently dropped one of them from
    every byte verification and restore -- an edited data table could ship
    (rule 2's byte-verification gap). The token-insensitive matching a package
    needs (it may carry the base's token names) is applied by
    `raw_data_pairs`, which pairs exact paths first and only then falls back to
    the stripped key, and only when that fallback is unambiguous.
    """
    out = {}
    if not area.is_dir():
        return out
    try:
        files = _iter_tree_files(area, follow_dir_links=True)
    except OSError:
        return out                      # an unreadable tree is reported by the caller
    # The walk follows DIRECTORY symlinks (a sandbox links its evidence areas),
    # but a nested link may point outside the area. Its lexical path still
    # looks local, so `copyfile`/`unlink` below would write through it. Only
    # files whose real path stays inside the area are part of the evidence.
    try:
        area_real = area.resolve()
    except OSError:
        return out
    for p in files:
        try:
            if not p.resolve().is_relative_to(area_real):
                continue
        except (OSError, RuntimeError):
            continue
        rel = p.relative_to(base).as_posix()
        try:
            out[rel] = (rel, sha256_file(p))
        except OSError:
            continue
    return out


def raw_data_pairs(want: dict, got: dict) -> tuple:
    """Pair a package's raw-data entries (`got`) with the pristine `want`.

    Both maps come from `_entries_in`. Returns `(pairs, extras)`:

      * `pairs` -- `(pristine_rel, pristine_digest, candidate_rel|None,
        candidate_digest|None)` in pristine order, so a caller can compare the
        bytes and restore the ones that differ;
      * `extras` -- the candidate's `(rel, digest)` entries the original does
        not have (the drop list).

    EXACT paths pair first (`cohort_a.tsv` with `cohort_a.tsv`), which is what
    makes every file of a token-colliding pair visible. A pristine file with no
    exact counterpart falls back to `_raw_data_key` (the token-stripped name),
    so a package carrying the base's token names
    (`dataset_summary-4f3a9c1.tsv`) is matched instead of overwritten; the
    fallback is used only when EXACTLY ONE candidate file is left for that key,
    because a wrong pairing would write one file's bytes over another's and
    restoring is the safe outcome.
    """
    used = set()
    pairs = []
    by_key = {}
    for rel in sorted(got):
        by_key.setdefault(_raw_data_key(rel), []).append(rel)
    for rel in sorted(want):
        dig = want[rel][1]
        if rel in got:
            pairs.append((rel, dig, rel, got[rel][1]))
            used.add(rel)
            continue
        # `c not in want`: a candidate file another pristine entry wants by its
        # EXACT name is never used as a token-insensitive stand-in -- pairing
        # `cohort_a.tsv` with the candidate's `cohort_b.tsv` would restore the
        # wrong bytes. Restoring is the safe outcome for the unmatched file.
        cands = [c for c in by_key.get(_raw_data_key(rel), [])
                 if c not in used and c not in want]
        if len(cands) == 1:
            pairs.append((rel, dig, cands[0], got[cands[0]][1]))
            used.add(cands[0])
        else:
            pairs.append((rel, dig, None, None))
    extras = [(rel, got[rel][1]) for rel in sorted(got) if rel not in used]
    return pairs, extras


# Text-ish files whose REFERENCES to the raw-data directory are repointed when
# the directory is materialized under its canonical name. Anything else (a
# .docx, a .pdf, an image) is left byte-identical: a compressed container cannot
# be string-substituted safely, and the prompts ask the session for the docx
# side.
def _safe_restore_copy(src: Path, dest: Path, root: Path) -> None:
    """Copy `src` to `dest` WITHOUT following a planted symlink.

    `dest` lives in the agent-controlled package (`root`). A package can make a
    file or a parent directory a symlink to any writable path outside the
    sandbox; `shutil.copyfile` would then overwrite that target while the
    restore reports the package file as repaired. Refuse a symlinked parent,
    replace a symlinked final entry, and write through a temp + os.replace so the
    final open never follows a link.
    """
    root = Path(root)
    try:
        rel = Path(dest).relative_to(root)
    except ValueError as exc:
        raise OSError(f"destination {dest} is outside {root}") from exc
    cur = root
    for part in rel.parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            raise OSError(f"refusing to write through symlinked directory {cur}")
    dest = root / rel
    if dest.is_symlink():
        dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.restore-{os.getpid()}-{time.time_ns()}")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def enforce_readonly_raw_data(ctx: Ctx, cand_dir: Path, warns: list) -> dict:
    """Put a package's raw-data directory back to the untouched original.

    Returns {'present', 'files', 'restored', 'dropped'} and appends ONE warning
    naming every deviation. A package without the directory gets the original
    one; a package whose copy differs anywhere is overwritten IN PLACE (its own
    file names are kept, so references stay valid); a file the original does not
    have is removed.
    """
    src = ctx.pristine / raw_data_dirname(ctx.pristine)
    if not src.is_dir():
        return {"present": False, "files": 0, "restored": [], "dropped": []}
    want = raw_data_entries(ctx.pristine)
    if not want:
        return {"present": False, "files": 0, "restored": [], "dropped": []}
    name = raw_data_dirname(cand_dir)
    area = cand_dir / name
    if area.is_symlink():
        # The sandbox INPUT links this area to the canonical copy; a package
        # that carries the link onward must be verified, never written through.
        try:
            same = area.resolve() == src.resolve()
        except OSError:
            same = False
        if same:
            return {"present": True, "files": len(want), "restored": [], "dropped": [],
                    "linked": True}
        with contextlib.suppress(OSError):
            area.unlink()
        warns.append(f"READ-ONLY raw data: {name}/ was a symlink to a different target and was "
                     f"replaced with the pristine copy")
    got = raw_data_entries(cand_dir)
    pairs, extras = raw_data_pairs(want, got)
    # A DIRECTORY squatting on one of the original's file paths (agent scratch at
    # the wrong path) is the recovery layer's case: it refuses to delete real work
    # and fails the attempt. This layer must not delete inside it either.
    squat = sorted({norm_raw_data_name(rel) for rel, _dig in want.values()
                    if (cand_dir / norm_raw_data_name(rel)).is_dir()})

    def inside_squat(rel: str) -> bool:
        return any(rel == s or rel.startswith(s + "/") for s in squat)

    # This is the ONE sanctioned write inside raw_data (putting a package's copy
    # back to the pristine original). The subtree is read-only by contract -- and
    # by the operator's own chmod -- so clear the write bits for the duration and
    # put every mode back exactly as it was, whether the copy ends up restored or
    # unchanged. Without this, a read-only raw_data copy would make the RESTORE
    # itself fail with EACCES (or, worse, leave half a package repaired).
    mode_plan = make_tree_writable(area) if area.is_dir() else []
    restored, dropped = [], []
    try:
        for rel, dig, crel, cdig in pairs:
            if cdig == dig:
                continue
            # The candidate's OWN spelling of the directory wins (it is what its
            # documents reference); a file the original does not have yet is written
            # under the canonical name.
            dest_rel = crel if crel is not None else norm_raw_data_name(rel)
            if (cand_dir / dest_rel).is_dir():
                continue                # squatted: reported as a warning below
            dest = cand_dir / dest_rel
            try:
                _safe_restore_copy(ctx.pristine / rel, dest, cand_dir)
                # The pristine copy's own mode is the honest one for a file the
                # package did not have (a read-only source stays read-only); the
                # finally below then restores the modes of everything that was
                # already there.
                with contextlib.suppress(OSError):
                    shutil.copymode(ctx.pristine / rel, dest)
            except OSError as e:
                warns.append(f"READ-ONLY raw data: could not restore {dest.name}: {e}")
                continue
            restored.append(dest.relative_to(cand_dir).as_posix())
        for rel, _dig in extras:
            if not inside_squat(rel):
                try:
                    (cand_dir / rel).unlink()
                except OSError as e:
                    warns.append(f"READ-ONLY raw data: could not remove added file "
                                 f"{rel}: {e}")
                    continue
                dropped.append(rel)
        # A directory the package had lost (or made writable) comes back with the
        # original's modes: the read-only contract is a property of the tree, not
        # only of its bytes. Entries that were already there keep their own modes
        # (the finally restores them).
        for src_dir in [src, *[p for p in sorted(src.rglob("*")) if p.is_dir()]]:
            rel_dir = "" if src_dir == src else src_dir.relative_to(src).as_posix()
            dst_dir = area / rel_dir if rel_dir else area
            if dst_dir.is_dir():
                with contextlib.suppress(OSError):
                    shutil.copymode(src_dir, dst_dir)
    finally:
        restore_modes(mode_plan)
    for s in squat:
        warns.append(f"READ-ONLY raw data: {s} is a directory where the pristine original has a "
                     f"file; its content was left alone (the recovery layer refuses to delete "
                     f"real work) and the attempt fails")
    for d in sorted([p for p in area.rglob("*") if p.is_dir()],
                    key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()                      # only empty directories disappear
        except OSError:
            pass
    if restored or dropped:
        changed = ", ".join(sorted(restored + dropped)[:6])
        more = f" (+{len(restored) + len(dropped) - 6} more)" \
            if len(restored) + len(dropped) > 6 else ""
        warns.append(
            f"READ-ONLY raw data: {len(restored) + len(dropped)} file(s) under {name}/ were put "
            f"back to the pristine original ({changed}{more}). The raw-data directory is an "
            f"INPUT: never edit, rename, add or drop anything inside it -- it is copied from the "
            f"original, so a document that points into it must use the name that is there")
    return {"present": True, "files": len(want), "restored": restored, "dropped": dropped}


def feedback_area_entries(dirp: Path, area_name: str) -> dict:
    """{corpus-relative path: sha256} for one review-feedback EVIDENCE area.

    No version-token normalisation here: the area is an INPUT whose file names
    never carry this package's naming evidence, so its identity is the path.
    """
    out = {}
    area = Path(dirp) / area_name
    if not area.is_dir():
        return out
    try:
        files = _iter_tree_files(area, follow_dir_links=True)
        area_real = area.resolve()
    except OSError:
        return out
    for p in files:
        try:
            if not p.resolve().is_relative_to(area_real):
                continue
        except (OSError, RuntimeError):
            continue
        rel = p.relative_to(Path(dirp)).as_posix()
        try:
            out[rel] = sha256_file(p)
        except OSError:
            continue
    return out


def human_feedback_entries(dirp: Path) -> dict:
    """{corpus-relative path: sha256} for `dirp`'s human_review_feedback area."""
    return feedback_area_entries(dirp, HUMAN_FEEDBACK_DIR)


def llm_feedback_entries(dirp: Path) -> dict:
    """{corpus-relative path: sha256} for `dirp`'s llm_review_feedback area."""
    return feedback_area_entries(dirp, LLM_FEEDBACK_DIR)


def enforce_readonly_feedback_area(ctx: Ctx, cand_dir: Path, warns: list,
                                   area_name: str = HUMAN_FEEDBACK_DIR) -> dict:
    """Put a package's review-feedback area back to the untouched original.

    Same contract as raw_data (an INPUT: never edited, renamed, added to or
    dropped), without the legacy-spelling machinery: the directory has one
    spelling. A non-empty directory squatting on a pristine file's path is
    reported and left alone, exactly like the raw-data layer. The human and LLM
    areas share the implementation; only the label and the description of what
    the area IS differ.
    """
    human = area_name == HUMAN_FEEDBACK_DIR
    label = "human" if human else "LLM"
    what = ("the real editors'/reviewers' comments" if human else
            "the LLM review findings whose false positives were filtered out")
    src = ctx.pristine / area_name
    if not src.is_dir():
        return {"present": False, "files": 0, "restored": [], "dropped": []}
    want = feedback_area_entries(ctx.pristine, area_name)
    if not want:
        return {"present": False, "files": 0, "restored": [], "dropped": []}
    area = cand_dir / area_name
    if area.is_symlink():
        try:
            same = area.resolve() == src.resolve()
        except OSError:
            same = False
        if same:
            return {"present": True, "files": len(want), "restored": [], "dropped": [],
                    "linked": True}
        with contextlib.suppress(OSError):
            area.unlink()
        warns.append(f"READ-ONLY {label} review feedback: {area_name}/ was a symlink to "
                     f"a different target and was replaced with the pristine copy")
    squat = sorted(rel for rel in want if (cand_dir / rel).is_dir())

    def inside_squat(rel: str) -> bool:
        return any(rel == s or rel.startswith(s + "/") for s in squat)

    mode_plan = make_tree_writable(area) if area.is_dir() else []
    restored, dropped = [], []
    try:
        for rel, dig in sorted(want.items()):
            dest = cand_dir / rel
            if dest.is_file():
                try:
                    if sha256_file(dest) == dig:
                        continue
                except OSError:
                    pass
            if dest.is_dir():
                continue                # squatted: reported below, never deleted
            try:
                _safe_restore_copy(ctx.pristine / rel, dest, cand_dir)
                with contextlib.suppress(OSError):
                    shutil.copymode(ctx.pristine / rel, dest)
            except OSError as e:
                warns.append(f"READ-ONLY {label} review feedback: could not restore "
                             f"{dest.name}: {e}")
                continue
            restored.append(rel)
        for rel in sorted(feedback_area_entries(cand_dir, area_name)):
            if rel in want or inside_squat(rel):
                continue
            try:
                (cand_dir / rel).unlink()
            except OSError as e:
                warns.append(f"READ-ONLY {label} review feedback: could not remove added "
                             f"file {rel}: {e}")
                continue
            dropped.append(rel)
        for src_dir in [src, *[p for p in sorted(src.rglob("*")) if p.is_dir()]]:
            rel_dir = "" if src_dir == src else src_dir.relative_to(src).as_posix()
            dst_dir = area / rel_dir if rel_dir else area
            if dst_dir.is_dir():
                with contextlib.suppress(OSError):
                    shutil.copymode(src_dir, dst_dir)
    finally:
        restore_modes(mode_plan)
    for s in squat:
        warns.append(f"READ-ONLY {label} review feedback: {s} is a directory where the pristine "
                     f"original has a file; its content was left alone (the recovery layer "
                     f"refuses to delete real work) and the attempt fails")
    for d in sorted([p for p in area.rglob("*") if p.is_dir()],
                    key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()                   # only empty directories disappear
        except OSError:
            pass
    if restored or dropped:
        changed = ", ".join(sorted(restored + dropped)[:6])
        more = (f" (+{len(restored) + len(dropped) - 6} more)"
                if len(restored) + len(dropped) > 6 else "")
        warns.append(
            f"READ-ONLY {label} review feedback: {len(restored) + len(dropped)} file(s) under "
            f"{area_name}/ were put back to the pristine original ({changed}{more}). "
            f"The area is an INPUT ({what}): never edit, rename, "
            f"add or drop anything inside it -- it is copied from the original, so a document "
            f"that points into it must use the name that is there")
    return {"present": True, "files": len(want), "restored": restored, "dropped": dropped}


def enforce_readonly_human_feedback(ctx: Ctx, cand_dir: Path, warns: list) -> dict:
    """Put a package's human_review_feedback/ back to the untouched original."""
    return enforce_readonly_feedback_area(ctx, cand_dir, warns, HUMAN_FEEDBACK_DIR)


def enforce_readonly_llm_feedback(ctx: Ctx, cand_dir: Path, warns: list) -> dict:
    """Put a package's llm_review_feedback/ back to the untouched original."""
    return enforce_readonly_feedback_area(ctx, cand_dir, warns, LLM_FEEDBACK_DIR)


def verify_readonly_raw_data(ctx: Ctx, cand_dir: Path, warns: list) -> dict:
    """The whole READ-ONLY raw-data contract for one package: the original's
    bytes. Called after the missing-file recovery, so an inherited
    deviation is healed exactly once and a stage that follows the rule is a
    no-op."""
    info = enforce_readonly_raw_data(ctx, cand_dir, warns)
    # A legacy input-area spelling is not migrated and is never ordinary
    # submission content: it would be judged/published as a new directory. Fail
    # the package so the operator renames the source corpus deliberately.
    info["legacy_input_areas"] = legacy_input_area_problems(cand_dir)
    if info["legacy_input_areas"]:
        warns.append("REMOVED input-area spelling in the package: "
                     + "; ".join(info["legacy_input_areas"]))
    # The review-feedback areas are INPUTS like raw_data: same byte-for-byte
    # contract, same restore-from-pristine repair (human editors'/reviewers'
    # comments and the pre-filtered LLM review).
    info["human_review_feedback"] = enforce_readonly_human_feedback(ctx, cand_dir, warns)
    info["llm_review_feedback"] = enforce_readonly_llm_feedback(ctx, cand_dir, warns)
    return info


def raw_data_advisories(ctx: Ctx) -> list:
    """Pins/winners whose READ-ONLY raw data differs from the pristine original.

    Reported, never repaired: a pin and its published winner are the frozen
    evidence a decided round rests on, so the pipeline does not rewrite them --
    but the operator has to know that the corpus a champion was built from
    carries raw-data edits from before the rule existed. Every stage from now on
    materializes the original's copy, so the deviation cannot reach a new
    package.
    """
    want = raw_data_entries(ctx.pristine)
    want_hf = human_feedback_entries(ctx.pristine)
    want_llm = llm_feedback_entries(ctx.pristine)
    if not want and not want_hf and not want_llm:
        return []
    out, seen = [], set()
    areas = [(f"pinned/{pin['id']}", pinned_docs_dir(ctx, pin))
             for pin in (ctx.state.get("pinned") or [])]
    for r in range(1, ctx.rounds_count() + 1):
        rrec = ctx.state.get("rounds", {}).get(str(int(r))) or {}
        if rrec.get("status") == "done" and rrec.get("winner_dir"):
            areas.append((rrec["winner_dir"], ctx.root / rrec["winner_dir"]))
    for label, d in areas:
        if label in seen or not d.is_dir():
            continue
        seen.add(label)
        if want:
            got = raw_data_entries(d)
            # Same pairing as `enforce_readonly_raw_data`: exact paths first,
            # then the token-insensitive fallback -- a package that carries the
            # base's token names (`dataset_summary-4f3a9c1.tsv`) is compliant,
            # and reading it by exact path alone reported it as a deviation.
            pairs, _extras = raw_data_pairs(want, got)
            bad = sorted(rel for rel, dig, _crel, cdig in pairs if cdig != dig)
            if bad:
                out.append(f"{label}/ carries {len(bad)} raw-data file(s) that differ from the "
                           f"pristine original ({', '.join(bad[:3])}"
                           f"{f' +{len(bad) - 3} more' if len(bad) > 3 else ''}); every stage "
                           f"materializes the original's copy, so this cannot reach a new "
                           f"package")
        if want_hf:
            got_hf = human_feedback_entries(d)
            bad_hf = sorted(rel for rel, dig in want_hf.items() if got_hf.get(rel) != dig)
            if bad_hf:
                out.append(f"{label}/ carries {len(bad_hf)} human-review-feedback file(s) that "
                           f"differ from the pristine original ({', '.join(bad_hf[:3])}"
                           f"{f' +{len(bad_hf) - 3} more' if len(bad_hf) > 3 else ''}); every "
                           f"stage materializes the original's copy, so this cannot reach a new "
                           f"package")
        if want_llm:
            got_llm = llm_feedback_entries(d)
            bad_llm = sorted(rel for rel, dig in want_llm.items() if got_llm.get(rel) != dig)
            if bad_llm:
                out.append(f"{label}/ carries {len(bad_llm)} LLM-review-feedback file(s) that "
                           f"differ from the pristine original ({', '.join(bad_llm[:3])}"
                           f"{f' +{len(bad_llm) - 3} more' if len(bad_llm) > 3 else ''}); every "
                           f"stage materializes the original's copy, so this cannot reach a new "
                           f"package")
    return out


def backfill_missing_files(ctx: Ctx, rec: dict, base_sources: list, warns: list) -> dict:
    """RECOVERY LAYER: restore base files the candidate lost, or say why it cannot.

    The document-set invariant -- "a revision must not lose a file the base
    had" -- is too important to leave to agent obedience AND too cheap to
    enforce mechanically. When the agent's package is missing a base file, the
    orchestrator copies it back from the (hash-verified, read-only) base and
    records a warning: the invariant is restored, the round proceeds, and the
    report still shows exactly what the agent dropped. This converts a
    DETERMINISTIC agent-side failure into a one-line recovery: an LLM that
    systematically classifies, say, "entire_pipeline.git-snapshot.txt" as git
    metadata rather than package content will drop it on every retry, so
    retrying (at ~1h of agent time per attempt) can never fix it.

    Coverage is wider than the document-set check on purpose: the check only
    protects EDITABLE_DOC_EXTS, which left raw-data PDFs (source-hierarchy
    tier 2: "data in raw_data/"), .tsv tables and .pptx figure sources with
    NO protection at all. The backfill restores every missing base file, so a
    dropped figure asset is repaired too -- and reported.

    Exclusions, so recovery never undoes a DELIBERATE exclusion:
      * derived build outputs (.aux/.log/.synctex.gz/... -- the prompts
        prescribe leaving them out of revised/);
      * the difference-tracking auxiliaries (see TRACKING_AUX_NAME_RE);
      * a Word OWNER (lock) file (`~$<name>`): it is not a document, and a
        candidate that drops it loses no content -- restoring one only puts a
        162-byte Word by-product back into the corpus (2026-10-15);
      * non-shippable residue (`is_non_shippable_name`: OS junk such as
        .DS_Store/:Zone.Identifier, bytecode caches, Word owners): the stage's
        strip removed it from the package identity, so recovery must not put it
        back into the pinned corpus;
      * the pipeline's own bookkeeping files (the agent regenerates them);
      * revised/work/ scratch.
    Skip-conditions, so recovery never duplicates content:
      * the destination path already exists (the file survived);
      * the file's bytes survive anywhere in the candidate (a rename);
      * an editable document's version-stripped key survives (a rename family,
        e.g. ...-b.docx -> ...-c.docx);
      * a compiled top-level PDF whose editable twin was EDITED (the prompt
        deliberately allows dropping a stale compiled PDF; re-adding it would
        ship a derived file that contradicts the revised source -- the one
        thing the derived-output rule forbids).
    A destination that exists but is EMPTY while the base file is not is
    restored (overwritten) with a warning: no sane revision empties a
    submission file, so a 0-byte candidate file is a truncation. A destination
    that is an unreadable file, a symlink or an EMPTY directory is likewise
    replaced by the base copy (an alias/scratch path is not a revision). Only a
    NON-EMPTY directory is refused -- deleting what may be real agent work is
    the one thing recovery must not do -- and the refusal is returned in
    `unresolved` so the CALLER fails the attempt (a clean retry) instead of
    reporting a package whose document was silently lost.
    """
    sb = ctx.sandbox_of(rec)
    restored, survived_other_name, stale_pdf_left, errors = [], [], [], []
    out_dir = output_dir_of(rec)
    cand_files = _candidate_corpus_files(sb, out_dir)
    cand_digests = set()
    for key, p in cand_files:
        try:
            dig = sha256_file(p)
        except OSError:
            continue
        # Every empty file shares EMPTY_SHA256; treating it as a rename match
        # let a dropped 0-byte base file "survive" because any unrelated empty
        # scratch file happened to exist.
        if dig != EMPTY_SHA256:
            cand_digests.add(dig)
    # Rename-family bookkeeping (see the family skip in the main loop). A
    # candidate document can stand in for ONE base document whose name changed,
    # but only if it is not itself the exact-name survivor of another base
    # document under the same version-stripped key: when several base documents
    # collapse to one key (Dataset-a.csv / Dataset-b.csv), the surviving sibling
    # must not absorb the slot of the one that was dropped.
    base_doc_names = set()
    for bsrc, bprefix, bexcluded in base_sources:
        if not bsrc.is_dir():
            continue
        for q in sorted(bsrc.rglob("*")):
            if not q.is_file() or _is_aux_doc(q.name) or _is_derived_name(q.name) \
                    or is_bookkeeping_name(q.name) or is_word_owner_name(q.name):
                continue
            brel = q.relative_to(bsrc).as_posix()
            if (bexcluded and brel.split("/", 1)[0] in bexcluded) \
                    or brel.split("/", 1)[0] in CORPUS_EXCLUDE_TOP \
                    or _candidate_dest(sb, bprefix + brel, out_dir) is None:
                continue
            if q.suffix.lower() in EDITABLE_DOC_EXTS:
                base_doc_names.add(bprefix + brel)
    cand_free_keys: dict = {}
    for key, p in cand_files:
        if p.suffix.lower() in EDITABLE_DOC_EXTS and not is_bookkeeping_name(p.name) \
                and key not in base_doc_names:
            fam_key = _doc_key(key)
            cand_free_keys[fam_key] = cand_free_keys.get(fam_key, 0) + 1
    # Base-side digests, for the compiled-PDF twin test.
    base_digs = {}
    for src_dir, prefix, _excluded in base_sources:
        if src_dir.is_dir():
            for p in src_dir.rglob("*"):
                if p.is_file():
                    try:
                        base_digs[(prefix + p.relative_to(src_dir).as_posix())] = sha256_file(p)
                    except OSError:
                        pass

    def _stem_key(name: str) -> str:
        return DOC_TOKEN_RE.sub("", Path(name).stem).lower()

    def _editable_twin_in_base(src_dir: Path, rel_in: str):
        """Path of an editable source with the same stem next to a base PDF."""
        d = src_dir / Path(rel_in).parent
        want = _stem_key(Path(rel_in).name)
        try:
            entries = list(d.iterdir()) if d.is_dir() else []
        except OSError:
            return None
        for q in entries:
            if q.is_file() and q.suffix.lower() in _PDF_TWIN_EXTS \
                    and _stem_key(q.name) == want:
                return q
        return None

    def _candidate_twin(stem_of_base_twin: str):
        for key, p in cand_files:
            if p.suffix.lower() in _PDF_TWIN_EXTS \
                    and _stem_key(Path(key).name) == stem_of_base_twin:
                return p
        return None

    for src_dir, prefix, excluded in base_sources:
        if not src_dir.is_dir():
            continue
        for p in sorted(src_dir.rglob("*")):
            if not p.is_file() or _is_aux_doc(p.name) or is_word_owner_name(p.name) \
                    or is_non_shippable_name(p.name):
                continue
            rel_in = p.relative_to(src_dir).as_posix()
            if excluded and rel_in.split("/", 1)[0] in excluded:
                continue
            rel = prefix + rel_in
            if rel.split("/", 1)[0] in CORPUS_EXCLUDE_TOP:
                continue
            if _is_derived_name(p.name):
                continue                      # prompts prescribe leaving these out
            if is_bookkeeping_name(p.name):
                continue                      # the agent regenerates its own reports
            dest = _candidate_dest(sb, rel, out_dir)
            if dest is None:
                continue
            # `exists()` is FALSE for a broken symlink, and TRUE for the two shapes
            # below, which are not "the file survived": a directory where the base
            # had a file, and a symlink (sound or broken). Both silently hid the
            # loss and made every downstream digest/read of the package fail later,
            # so they are treated as corruption and repaired from the base.
            if dest.is_symlink() or (dest.exists() and not dest.is_file()):
                wrong_kind = "symlink" if dest.is_symlink() else "directory"
                try:
                    if dest.is_dir() and not dest.is_symlink():
                        if any(dest.iterdir()):
                            errors.append(f"{rel}: the candidate path is a NON-EMPTY directory, "
                                          f"which cannot be repaired automatically; remove it by "
                                          f"hand and re-run")
                            continue
                        dest.rmdir()
                    else:
                        dest.unlink()
                    _safe_restore_copy(p, dest, sb)
                    restored.append(rel)
                    warns.append(f"RECOVERY: {rel} existed in the candidate as a "
                                 f"{wrong_kind} instead of "
                                 f"a regular file -- replaced with the base copy (an agent-created "
                                 f"alias/scratch path is not a revision of the document)")
                except OSError as e:                                      # noqa: BLE001
                    errors.append(f"{rel}: {e}")
                continue
            if dest.exists():
                try:
                    if dest.is_file() and dest.stat().st_size == 0 \
                            and p.stat().st_size > 0:
                        try:
                            dest.chmod(0o644)     # a read-only 0-byte file blocks copy2
                        except OSError:
                            pass
                        _safe_restore_copy(p, dest, sb)
                        restored.append(rel)
                        warns.append(f"RECOVERY: {rel} existed in the candidate as an EMPTY "
                                     f"(0-byte) file -- restored non-empty from the base "
                                     f"(a truncation is not a revision)")
                    elif dest.is_file() and p.stat().st_size > 0:
                        # Readable check: an UNREADABLE candidate file (chmod 000, a
                        # Windows lock, a broken mount) is not usable content and would
                        # otherwise crash the corpus digest with PermissionError. The
                        # base copy is hash-verified input, so restoring it is safe.
                        try:
                            with open(dest, "rb"):
                                pass
                        except OSError:
                            try:
                                dest.chmod(0o644)     # clear a mode that blocks the rewrite
                            except OSError:
                                pass
                            _safe_restore_copy(p, dest, sb)
                            restored.append(rel)
                            warns.append(f"RECOVERY: {rel} was NOT READABLE in the candidate "
                                         f"(permissions/lock) -- restored from the base copy so the "
                                         f"corpus can be hashed and judged")
                except OSError as e:                                      # noqa: BLE001
                    errors.append(f"{rel}: {e}")
                continue
            dig = base_digs.get(rel)
            if dig is None:
                try:
                    dig = sha256_file(p)
                except OSError as e:                                      # noqa: BLE001
                    errors.append(f"{rel}: {e}")
                    continue
            if dig in cand_digests:
                # Same bytes can come from a DIFFERENT base file that still has
                # its exact-name survivor (fig1.png + fig1_copy.png share bytes;
                # deleting only the copy is not a rename). Only a digest with no
                # surviving exact-name sibling can stand in for this file.
                _sibling_survives = False
                for _other, _odig in base_digs.items():
                    if _other == rel or _odig != dig:
                        continue
                    _odest = _candidate_dest(sb, _other, out_dir)
                    if _odest is not None and _odest.is_file():
                        _sibling_survives = True
                        break
                if not _sibling_survives:
                    survived_other_name.append(rel)
                    continue              # bytes survive under another name: a rename
            if p.suffix.lower() in EDITABLE_DOC_EXTS:
                fam = _doc_key(rel)
                if cand_free_keys.get(fam, 0) > 0:
                    cand_free_keys[fam] -= 1
                    survived_other_name.append(rel)
                    continue              # rename family (...-b.docx -> ...-c.docx)
            if p.suffix.lower() == ".pdf":
                twin = _editable_twin_in_base(src_dir, rel_in)
                if twin is not None:
                    cand_twin = _candidate_twin(_stem_key(twin.name))
                    if cand_twin is not None:
                        twin_dig = base_digs.get(prefix + twin.relative_to(src_dir).as_posix())
                        try:
                            if sha256_file(cand_twin) != twin_dig:
                                stale_pdf_left.append(rel)
                                continue
                        except OSError:
                            pass
            try:
                _safe_restore_copy(p, dest, sb)
                restored.append(rel)
            except OSError as e:                                          # noqa: BLE001
                errors.append(f"{rel}: {e}")

    info = {"restored": restored, "survived_under_other_name": survived_other_name,
            "stale_compiled_pdf_left_out": stale_pdf_left, "errors": errors,
            "unresolved": errors,
            "checked_at": utcnow()}
    if restored:
        warns.append(f"RECOVERY: {len(restored)} base file(s) were MISSING from the candidate "
                     f"and have been restored from the base copy: {', '.join(restored[:8])}"
                     + (" ..." if len(restored) > 8 else "")
                     + " -- the agent dropped them; the orchestrator enforces the "
                       "nothing-may-be-lost invariant mechanically, and the drop is recorded "
                       "here and in the run audit")
    if stale_pdf_left:
        warns.append("compiled PDF(s) left out of the candidate whose editable source was "
                     "EDITED (deliberate per the derived-output rule; NOT restored, so no "
                     "stale by-product is shipped): " + ", ".join(stale_pdf_left[:6])
                     + " -- recompile them manually if the package needs them")
    for e in errors:
        warns.append(f"backfill could not restore a missing base file ({e}); the document-set "
                     f"report below lists whatever is still missing")
    return info


def _caption_and_document_checks(ctx: Ctx, rec: dict, vid: str, base_sources: list,
                                 errs: list, warns: list) -> None:
    """Record a candidate's caption scan and verify its document set survived.

    `base_sources` is the [(dir, prefix, excluded)] view of what the stage
    started from (base/ for revise, self/ for integration); the candidate view is the
    version's corpus (which excludes revised/work/).
    """
    try:
        info = scan_version_captions(ctx, rec["round"], vid)
    except Exception as e:  # noqa: BLE001
        info = None
        warns.append(f"caption scan failed: {e}")
    rec["captions"] = info
    if info:
        limit = int(info.get("limit") or 0)
        n_over = len(info.get("over_limit") or [])
        if n_over:
            examples = ", ".join(f"{c['document']}:{c['caption']} ({c['words']} words)"
                                 for c in info["over_limit"][:3])
            warns.append(f"{n_over} figure caption(s) exceed the SUGGESTED {limit}-word length "
                         f"(check id M18; advisory only, never a gate): {examples}")
        if info.get("unparsed"):
            warns.append("caption text could not be parsed in: "
                         + ", ".join(info["unparsed"][:4])
                         + " (verify M18 for those files manually)")
        if info.get("suspected_count"):
            warns.append(f"{info['suspected_count']} figure-like line(s) were NOT recognised as "
                         f"captions by the code-side scan (check id M18 is advisory only): "
                         + " | ".join(info.get("suspected", [])[:3]))
    try:
        ph = scan_placeholders_in_sources(corpus_sources(ctx, rec["round"], vid))
    except Exception as e:  # noqa: BLE001
        ph = None
        warns.append(f"hand-off-placeholder scan failed: {e}")
    rec["placeholders"] = ph
    if ph and ph.get("count"):
        # Informational on purpose: the markers exist because the stage refused to
        # invent content. They are handed to the author, never charged to the run.
        warns.append(f"{ph['count']} pipeline hand-off placeholder(s) "
                     f"(\"{PLACEHOLDER_TOKEN}: ...]\") await the author in: "
                     + ", ".join(ph["files"][:4])
                     + " -- listed for manual action; never scored, never a defect")
    try:
        dset = document_set_check(base_sources, corpus_sources(ctx, rec["round"], vid))
    except Exception as e:  # noqa: BLE001
        dset = None
        warns.append(f"document-set check failed: {e}")
    rec["document_set"] = dset
    if dset:
        if dset["missing"]:
            # Names FIRST: the console truncates these lines ([:140]/[:240]), and
            # the v2.1.0 wording put a 110-character explanation in front of the
            # file list, so the only diagnostic signal was cut off mid-filename.
            # `backfill_missing_files` has already restored everything it could
            # from the base; whatever is still missing could not be recovered
            # (the base copy itself is gone), so it is a loud WARNING for the
            # author rather than another 45-minute agent retry: a retry cannot
            # conjure bytes the sandbox no longer has.
            warns.append("MISSING FROM THE CANDIDATE, not restorable from the base: "
                         + ", ".join(dset["missing"])
                         + " -- the author must repair the package by hand before submission")
        if dset["duplicates"]:
            warns.append("possible rename twin(s) / colliding document names in the candidate "
                         "(a name that was not in the base shares a version-stripped key; if "
                         "these are genuinely two different documents, ignore this -- if one is "
                         "the pre/post-rename copy of the other, drop the old copy): "
                         + "; ".join(f"{k}: {', '.join(v)}"
                                     for k, v in list(dset["duplicates"].items())[:3]))
        if dset["content_preserved_under_other_name"]:
            warns.append("document(s) preserved under a different name (content-matched): "
                         + ", ".join(dset["content_preserved_under_other_name"]))
        if dset.get("added"):
            # The mirror of "a document was lost": a submission document this
            # package carries that the base never had. Legal ONLY as declared
            # scaffolding for a mandatory item (the hand-off-placeholder rule)
            # or as the visible output of a finding; new content is invented
            # content. Reported as a warning for the author, never failed here:
            # only a human can tell a scaffold from an invention.
            warns.append("NEW document(s) not present in the base: "
                         + ", ".join(dset["added"][:6])
                         + " -- each must be declared scaffolding for a mandatory item (with its "
                           "hand-off placeholders) or the visible output of a finding; a "
                           "document that adds content silently is invented content, the same "
                           "defect class as a lost document, read in the other direction")


def postcheck_a1(ctx: Ctx, rec: dict):
    errs, warns = [], []
    src_id = rec.get("source_id")
    # The SAME resolver materialize_a1 used: the whole-tree state read here
    # compared the corpus digest of base/ against a legacy recording rule (and
    # ignored the template stage's own working original), i.e. the same mixing
    # this file's other A1 checks no longer do.
    want = (working_original_digest(ctx) if src_id == ORIGINAL_ID
            else (find_pin(ctx, src_id) or {}).get("digest"))
    got = recompute_corpus_digest(ctx, rec["round"], A1_ID)
    # The DIGEST is still recorded below; only its verification is skipped
    # (`--skip-hash`), never the recording.
    if want and got != want and not hash_checks_skipped():
        errs.append(f"base/ is not byte-identical to its source ({src_id}).")
    rec["corpus_digest"] = got
    # The round base's own hand-off markers (report-only; see the placeholder
    # rules): recorded here too so a pin of the base carries the count.
    try:
        rec["placeholders"] = scan_placeholders_in_sources(
            corpus_sources(ctx, rec["round"], A1_ID))
    except Exception as e:                                      # noqa: BLE001
        rec["placeholders"] = None
        warns.append(f"hand-off-placeholder scan failed: {e}")
    errs.extend(input_mismatches(ctx, rec))
    # The base has no agent session by construction (see materialize_a1); that is
    # not a warning about the package, so it stays out of `postcheck.warnings`.
    return (not errs), errs, warns, None


# =====================================================================
# DECISION-ARTIFACT QUALITY (the disposition layer)
#
# A seeded row is not disposed because a sentence is present in its
# disposition cell: it is disposed when the sentence is about THAT row's own
# bar. Three real failures motivate the detectors below -- 96 scan rows closed
# with one identical "no journal rule" sentence, an OUTLINE table whose
# "summaries" were the first sentences copied back, and a `searchable`
# placeholder carried into a submitted cover letter although the answer
# ("not posted") was a code-side lookup away.
# =====================================================================

DISPOSITION_BOILERPLATE_MIN_ROWS = 12
DISPOSITION_BOILERPLATE_SHARE = 0.5
# A blanket rationale shared by this many rows is conclusive on its own: the
# reviewed run closed 96 of 200 rows with one sentence (a 0.48 share, i.e. just
# under the share test), and "no journal rule" repeated 25 times is never a
# coincidence.
DISPOSITION_BOILERPLATE_HARD_ROWS = 25
# A verdict that names a whole ROW CLASS is legitimately uniform (every
# reference-list paragraph is disposed the same way, and that is the honest
# answer); what the detector hunts is a blanket EDITORIAL judgement applied to
# rows that each need their own bar.
DISPOSITION_STRUCTURAL_EXEMPT_RE = re.compile(
    r"(?:\breferences?\b|\bbibliograph\w*\b|\bfield-protected\b|\btitle page\b|"
    r"\brunning head\b|\bmetadata\b|\bnot applicable\b|\bn/a\b)", re.I)


# The columns whose cells carry a disposition. `resolution` is the same
# contract under the placeholder/ledger layouts' own name.
DISPOSITION_COLUMNS = ("disposition", "resolution")

# The cover-letter stamp row (FMT-CL1): a letter formatted in the MANUSCRIPT
# template is a defect the venue ships no cover-letter template to justify. An
# OK closure is valid ONLY with the journal's own template/guideline text
# quoted that REQUIRES this formatting -- a real run closed exactly this row
# with "the run carries the letter in the journal's own styles" (the pipeline's
# rule, not the journal's) and shipped the defect. This gate is what makes the
# reviewer (and any other disposing agent) treat it as a defect.
COVER_LETTER_STAMP_RULES = {"FMT-CL1"}
COVER_LETTER_OVERRIDE_CITE_RE = re.compile(
    r"https?://|venue_template/|\.docx\b|\.dotx\b|author guidelines|"
    r"author instructions|instructions to authors|guide[ -]?lines", re.I)
COVER_LETTER_OVERRIDE_REQUIRE_RE = re.compile(
    r"\b(?:requires?|required|mandates?|mandatory|specif(?:y|ies|ied)|instructs?|"
    r"states?|says|asks? for|calls for|directs?)\b", re.I)
COVER_LETTER_OK_CLOSE_RE = re.compile(
    r"^\s*(?:ok\b|okay\b|ok\s*[—–\-:]|acceptable\b|no change\b|pass(?:es)?\b|clean\b)",
    re.I)


def _split_table_cells(text: str) -> list:
    """Split one table line on its UNESCAPED pipes (a `\\|` is cell content).

    The seeded tables escape a literal pipe inside a cell as `\\|` (figure
    captions are full of them: "Fig. 1 \\| Strategies ..."), and splitting on
    every pipe made those rows longer than their header -- which shifted every
    later cell, so the disposition was read from the wrong column.
    """
    cells, cur, i = [], [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            cur.append(ch)
            cur.append(text[i + 1])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    cells.append("".join(cur))
    return [c.strip().replace("\\|", "|") for c in cells]


def _table_line_cells(line: str) -> list:
    """The cells of one `| ... |` line, without its two delimiter pipes."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return _split_table_cells(s)


def _is_separator_row(cells: list) -> bool:
    """`|---|---|` / `|:--:|` -- the table's header/body divider."""
    return bool(cells) and all("-" in c and set(c) <= set("-: ") for c in cells)


def _table_row(header: list, cells: list) -> tuple:
    """({column: cell}, note) for one data row; note is "", "trimmed" or "ragged".

    The tables real sessions deliver are not always exactly as wide as their
    header, and each deviation has ONE unambiguous reading:

      1. stray LEADING empty cells (a script that writes `"| " + row` for a row
         that already starts with its own pipe) are dropped;
      2. ONE more cell than the header when the last column is a disposition
         column and its own cell is EMPTY means the verdict was APPENDED after
         the seeded empty cell instead of replacing it -- rendered markdown shows
         that verdict, so it is read (the old positional zip() dropped it and
         reported every row of a fully disposed 212-row M20 sweep as EMPTY,
         failing three 30-minute attempts in a row on a real root);
      3. stray TRAILING empty cells are dropped.

    Notes: "appended" is worth warning about (the table's column count is off),
    "trimmed" is not (only empty stray cells were removed), and "ragged" means
    the row's real cells still do not match the header -- it is read
    positionally and the operator is warned, because a shifted row would put the
    verdict in the wrong column.
    """
    n = len(header)
    note = ""
    while len(cells) > n and not str(cells[0]).strip():
        cells = cells[1:]
        note = "trimmed"
    if (len(cells) == n + 1 and header and header[-1] in DISPOSITION_COLUMNS
            and not str(cells[n - 1]).strip()):
        cells = cells[:n - 1] + [cells[-1]]
        note = "appended"
    while len(cells) > n and not str(cells[-1]).strip():
        cells = cells[:-1]
        note = note or "trimmed"
    if len(cells) < n:
        cells = cells + [""] * (n - len(cells))
        note = note or "ragged"
    elif len(cells) > n:
        cells = cells[:n]
        note = "ragged"
    return {h: v for h, v in zip(header, cells)}, note


def _disposition_table_problems(path: Path) -> list:
    """A parity/architecture artifact must have a DISPOSED data row.

    The contract is a table whose rows end in a disposition; a file whose whole
    content is `| disposition |` + the separator has a header, no rows, and used
    to pass the old substring test. Every block that carries a disposition-like
    column must have at least one row and no empty disposition cell.
    """
    blocks = parse_markdown_blocks(path)
    keyed = []
    for block in blocks:
        key = next((h for h in block["header"]
                    if "disposition" in h or h in ("resolution", "verdict")), None)
        if key:
            keyed.append((block, key))
    if not keyed:
        return ["carries no table with a `disposition` column"]
    data = [(b, k) for b, k in keyed if b["rows"]]
    if not data:
        return ["carries a `disposition` header but NO data row: a header alone disposes "
                "nothing (every row must record its own verdict/reason)"]
    problems = []
    for block, key in data:
        empty = sum(1 for row in block["rows"]
                    if not str(row.get(key) or "").strip())
        if empty:
            problems.append(f"{empty} of {len(block['rows'])} row(s) have an EMPTY "
                            f"`{key}` cell")
        if key in DISPOSITION_COLUMNS:
            problems += disposition_artifact_problems(block["rows"], block.get("widths"),
                                                      len(block["header"]))
    return problems


def parse_markdown_blocks(path: Path) -> list:
    """Every markdown table block of one artifact, each against ITS OWN header.

    Returns [{"header": [...], "rows": [{column: cell}], "appended": n,
    "ragged": n}, ...] in file order. A block is a run of consecutive `|` lines:
    the first is the header, a separator row is skipped, the rest are data rows.

    Blocks must be parsed separately because the artifacts legitimately contain
    MORE THAN ONE table: the M20 sweep requires the review to add the classes the
    code-side scan cannot see ("rows added from the visual pass"), and the
    coverage/summary tables are appended the same way. Parsing the whole file
    against the FIRST header turned those rows' own cells into empty
    `disposition` cells of the seeded table.
    """
    # Agent-written table artifact: shared regular-file/no-follow/byte-budget
    # reader (the integration ledger is read here a second time, F59).
    text = read_text_bounded(path)
    if text is None:
        return []
    raw_blocks, cur = [], []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            cur.append(line.strip())
        elif cur:
            raw_blocks.append(cur)
            cur = []
    if cur:
        raw_blocks.append(cur)
    blocks = []
    for raw in raw_blocks:
        header = [c.lower() for c in _table_line_cells(raw[0])]
        rows, widths, appended, ragged = [], [], 0, 0
        for line in raw[1:]:
            cells = _table_line_cells(line)
            if _is_separator_row(cells):
                continue
            # The row's OWN cell count is kept: a row that is one cell short of
            # its header reads positionally, so its last written cell lands in
            # the column BEFORE the disposition column and the disposition cell
            # is reported EMPTY (see disposition_artifact_problems). The count
            # is what lets the message say that instead of sending the operator
            # to a cell the session never wrote.
            widths.append(len(cells))
            row, note = _table_row(header, cells)
            appended += 1 if note == "appended" else 0
            ragged += 1 if note == "ragged" else 0
            rows.append(row)
        blocks.append({"header": header, "rows": rows, "widths": widths,
                       "appended": appended, "ragged": ragged})
    return blocks


def parse_markdown_table(path: Path) -> list:
    """Rows of a seeded artifact table as {lowercased header: cell} ([] if absent).

    A file that repeats the FIRST table's header (a long ledger split by an
    interpolated paragraph) contributes every block; a table with different
    columns (the session's own added-rows/coverage table) is NOT read as more
    rows of the first table -- see parse_markdown_blocks() for why that matters.
    """
    blocks = parse_markdown_blocks(path)
    if not blocks:
        return []
    head = blocks[0]["header"]
    return [row for b in blocks if b["header"] == head for row in b["rows"]]


def _names_check_or_finding(cell: str) -> bool:
    """Does a disposition name the row's rule, a check id, or a finding id?"""
    # Case-insensitive on purpose: the callers compare LOWERCASED dispositions
    # (the boilerplate counter normalizes them), and `fmt-t9c` names the rule
    # just as well as `FMT-T9c`.
    # J5 is part of the frozen set (and of the review's coverage contract): the
    # J[1-4] range made a repeated architecture verdict that cites only J5 read
    # as unreferenced boilerplate.
    return bool(re.search(r"(FMT-[A-Z0-9]+|M\d{1,2}\b|J[1-5]\b|F-\d+|X-\d+|AU-\d+|R-\d+)",
                          str(cell or ""), re.I))


def short_row_indexes(rows: list, widths, header_width: int) -> list:
    """1-based positions of the rows that are NARROWER than their own header.

    A short row is not a cosmetic detail: the reader pads it positionally, so
    the session's verdict sits in the column before the disposition cell and
    that cell reads EMPTY. `widths` is the per-row cell count from
    `parse_markdown_blocks` (None/absent -> no row is reported as short).
    """
    if not widths or not header_width:
        return []
    return [i + 1 for i, _row in enumerate(rows)
            if i < len(widths) and widths[i] < header_width]


def disposition_artifact_problems(rows: list, widths=None, header_width: int = 0) -> list:
    """Empty disposition cells and boilerplate closures in one seeded table.

    `widths`/`header_width` are optional (the pure-fixture callers pass rows
    only); when they are given, an EMPTY disposition cell that belongs to a row
    which is NARROWER than the header is reported as exactly that -- a shifted
    row -- because the fix is different: the session must re-emit the row with
    one cell per seeded column and the verdict IN the last one, not "fill the
    cell" (it is not there). A real review attempt rewrote OUTLINE.md's 185 rows
    one cell short, which read as "185 of 185 EMPTY disposition cells".
    """
    problems = []
    # Measured against the UNFILTERED rows: `widths` is aligned with them.
    short = short_row_indexes(rows, widths, header_width)
    rows = [r for r in rows if r]
    if not rows:
        return problems
    key = next((k for k in DISPOSITION_COLUMNS if k in rows[0]), None)
    if key is None:
        return problems
    filled = [r for r in rows if str(r.get(key) or "").strip()]
    empty = len(rows) - len(filled)
    if empty:
        msg = (f"{empty} of {len(rows)} row(s) have an EMPTY {key} cell "
               f"(every seeded row must be disposed or reconciled)")
        if short:
            msg += (f"; {len(short)} of those row(s) are NARROWER than the table's "
                    f"{header_width}-column header (row {short[0]} has {widths[short[0] - 1]} "
                    f"cell(s)) -- a short row is read POSITIONALLY, so anything written after the "
                    f"seeded cells lands in the column before `{key}` and `{key}` itself reads "
                    f"empty. Re-emit every row with exactly one cell per seeded column and put "
                    f"the verdict IN the `{key}` cell (the last column)")
        problems.append(msg)
    by_text = {}
    for r in filled:
        text = re.sub(r"\s+", " ", str(r.get(key)).strip().lower())
        by_text.setdefault(text, []).append(r)
    for text, same in sorted(by_text.items(), key=lambda kv: -len(kv[1]))[:2]:
        n = len(same)
        if (n >= DISPOSITION_BOILERPLATE_HARD_ROWS
            or (n >= DISPOSITION_BOILERPLATE_MIN_ROWS
                and n / max(1, len(rows)) >= DISPOSITION_BOILERPLATE_SHARE)) \
                and not _names_check_or_finding(text) \
                and not DISPOSITION_STRUCTURAL_EXEMPT_RE.search(text):
            # The message is the operator's ONLY handle on the defect, so it names
            # the rows it is about and quotes the sentence in full: a 70-character
            # cut of a repeated rationale once hid the fact that the SAME attempt
            # had also left 101 OUTLINE summaries empty.
            where = [l for l in (row_label(r) for r in same) if l][:4]
            problems.append(f"{n} of {len(rows)} dispositions repeat the SAME sentence "
                            f"({_quote(text, 160)}) and it names neither a rule id nor a finding "
                            f"id: that is a boilerplate closure, not a disposition"
                            + (f" -- rows: {', '.join(where)}" if where else "")
                            + (f" (and {n - len(where)} more)" if where and n > len(where) else ""))
    # TEMPLATED closures: a reason that differs only by the row's quoted token
    # ("... the row is inside a bibliography abstract (<token>)") reads as
    # different text to the exact-text test, yet it is one sentence. Compare a
    # SKELETON (parentheticals/quotes/numbers removed) so a templated closure is
    # still boilerplate. A group whose every row names a check/finding id is a
    # legitimate template and is skipped.
    def _skeleton(text: str) -> str:
        s = re.sub(r"\([^)]*\)", "()", text)
        s = re.sub(r"'[^']*'|\"[^\"]*\"|\u2018[^\u2019]*\u2019|\u201c[^\u201d]*\u201d",
                   "''", s)
        s = re.sub(r"\d+", "#", s)
        return re.sub(r"\s+", " ", s).strip().lower()

    by_skel = {}
    for r in filled:
        skel = _skeleton(str(r.get(key) or ""))
        if len(skel) >= 40:
            by_skel.setdefault(skel, []).append(r)
    for skel, same in sorted(by_skel.items(), key=lambda kv: -len(kv[1]))[:2]:
        n = len(same)
        if n < DISPOSITION_BOILERPLATE_MIN_ROWS:
            continue
        if n / max(1, len(rows)) < DISPOSITION_BOILERPLATE_SHARE \
                and n < DISPOSITION_BOILERPLATE_HARD_ROWS:
            continue
        if any(_names_check_or_finding(str(r.get(key) or "")) for r in same):
            continue
        where = [l for l in (row_label(r) for r in same) if l][:4]
        problems.append(
            f"{n} of {len(rows)} dispositions repeat one TEMPLATE sentence "
            f"({_quote(skel, 160)}) with only the row's token changed: a templated "
            f"closure is boilerplate, not a per-row disposition"
            + (f" -- rows: {', '.join(where)}" if where else "")
            + (f" (and {n - len(where)} more)" if where and n > len(where) else ""))

    # A COVER-LETTER STAMP row can be closed OK only with the journal's own
    # text: FMT-CL1 says the letter was formatted in the MANUSCRIPT template,
    # which is a defect unless the journal requires that formatting -- and the
    # disposition must quote that requirement. The pipeline's own convention
    # ("the run carries the letter in the journal's styles") is not an override.
    for r in filled:
        rule = str(r.get("rule") or "").strip().upper()
        if rule not in COVER_LETTER_STAMP_RULES:
            continue
        disp = str(r.get(key) or "").strip()
        if not COVER_LETTER_OK_CLOSE_RE.match(disp):
            continue
        if COVER_LETTER_OVERRIDE_CITE_RE.search(disp) \
                and COVER_LETTER_OVERRIDE_REQUIRE_RE.search(disp):
            continue
        where = str(r.get("location") or r.get("#") or "").strip()
        problems.append(
            f"{rule} row" + (f" ({where})" if where else "")
            + " is closed with OK but quotes no journal override: a cover letter formatted "
              "in the MANUSCRIPT template may be closed OK ONLY when the journal's own "
              "template/guideline text that REQUIRES this formatting is quoted in the "
              "disposition (its source and what it requires); \"the run carries the letter "
              "in the journal's styles\" is the pipeline's rule, not the journal's -- file "
              "the M20 finding, or quote the override")
    return problems


def row_label(row: dict) -> str:
    """A short, human-usable identifier for one artifact-table row."""
    doc = str(row.get("document") or "").strip()
    head = str(row.get("heading") or "").strip()
    para = str(row.get("paragraph") or "").strip()
    if doc or head or para:
        bits = [b for b in (doc, head, (f"para {para}" if para else "")) if b]
        return " / ".join(bits)[:80]
    for k in ("acronym", "term", "figure", "caption", "item", "field", "check", "kind", "id"):
        v = str(row.get(k) or "").strip()
        if v:
            return f"{k}={v}"[:80]
    return ""


def _quote(text: str, limit: int) -> str:
    """`repr()` of a message excerpt, with an explicit marker when it is cut."""
    text = str(text or "")
    return repr(text[:limit]) + (" (truncated)" if len(text) > limit else "")


def outline_artifact_problems(rows: list) -> list:
    """An OUTLINE whose summaries are echoed first sentences / one verdict."""
    problems = []
    rows = [r for r in rows if r]
    if not rows:
        return problems
    summaries = [str(r.get("summary") or "").strip() for r in rows]
    firsts = [str(r.get("first sentence") or "").strip() for r in rows]
    empty = sum(1 for s in summaries if not s)
    echoed = 0
    for s, f in zip(summaries, firsts):
        if s and f and len(s) > 12 and (f.startswith(s) or s.startswith(f[:len(s)])):
            echoed += 1
    if empty > max(2, int(len(rows) * 0.2)):
        where = [l for l in (row_label(r) for r in rows
                             if not str(r.get("summary") or "").strip()) if l][:4]
        problems.append(f"{empty} of {len(rows)} OUTLINE rows carry no summary "
                        f"(the hierarchy pass cannot be audited)"
                        + (f" -- e.g. {', '.join(where)}" if where else ""))
    if echoed > int(len(rows) * 0.5):
        problems.append(f"{echoed} of {len(rows)} summaries are copies of the row's first "
                        f"sentence -- write what the paragraph CLAIMS")
    verdicts = [str(r.get("disposition") or "").strip().lower() for r in rows
                if str(r.get("disposition") or "").strip()]
    if verdicts:
        text, n = Counter(verdicts).most_common(1)[0]
        if n >= 10 and n / len(rows) >= 0.8 and not _names_check_or_finding(text):
            same = [r for r in rows
                    if str(r.get("disposition") or "").strip().lower() == text]
            where = [l for l in (row_label(r) for r in same) if l][:4]
            problems.append(f"{n} of {len(rows)} OUTLINE rows carry the same verdict "
                            f"({_quote(text, 120)}) -- dispose each row against its own heading"
                            + (f" -- rows: {', '.join(where)}" if where else ""))
    return problems


DECISION_ARTIFACTS = ("artifacts/M20_formatting.md", "artifacts/M18_caption_words.md",
                      "artifacts/M19_length.md", "artifacts/M8_terms.md",
                      "artifacts/M24_concepts.md", "artifacts/GLOSSARY.md",
                      "artifacts/PLACEHOLDERS.md", "artifacts/PLACEHOLDER_LOOKUP.md",
                      "artifacts/OUTLINE.md", "artifacts/CLAIM_STRENGTH.md",
                      "artifacts/M30_hierarchy_reconciliation.md",
                      # M2's reference-integrity seed: the entries' own DOIs with
                      # the resolver's verdict. Gated like every other seeded
                      # table, because "the entry's DOI resolves to another work"
                      # is exactly the class no format check and no re-reading
                      # can see (see reference_integrity_rows).
                      "artifacts/M2_references.md")


def artifact_quality_report(review_dir: Path, require_files: bool = False) -> dict:
    """{artifact: [problems]} for every decision table under guided_review/.

    EVERY table block of the artifact is checked, each against its own header:
    the seeded table and the rows the session adds itself (the M20 "classes the
    scan cannot see", a coverage table) are all rows the session had to dispose.
    """
    report = {}
    for rel in DECISION_ARTIFACTS:
        path = review_dir / rel
        if require_files and not path.is_file():
            report.setdefault(rel, []).append(
                f"{rel} is missing: the seeded decision table was deleted")
            continue
        blocks = list(parse_markdown_blocks(path))
        if require_files and not blocks:
            report.setdefault(rel, []).append(
                f"{rel} carries no decision table (the seeded table was emptied)")
            continue
        if blocks and not any(
                any(k in block["header"] for k in DISPOSITION_COLUMNS)
                for block in blocks):
            # The seeded decision table's last column is the disposition cell.
            # `disposition_artifact_problems` returned [] when the column was
            # renamed, so a session could replace every decision table with
            # arbitrary columns and the whole per-row disposition gate passed
            # clean (the 2026-10-30 F11 bypass). The stronger
            # `_disposition_table_problems` path is used for the parity and
            # architecture artifacts only; this is the decision-artifact path.
            report.setdefault(rel, []).append(
                f"{rel} carries no table with a `disposition` column: every seeded "
                f"decision row must be disposed in its own last column")
            continue
        for block in blocks:
            rows = block["rows"]
            if not rows:
                # A header-only seeded table is the documented "no rows" shape
                # (the session may leave an empty table's header); the missing
                # DISPOSITION COLUMN is the bypass this check closes.
                continue
            problems = disposition_artifact_problems(rows, block.get("widths"),
                                                      len(block["header"]))
            if rel.endswith("OUTLINE.md"):
                problems += outline_artifact_problems(rows)
            if problems:
                report.setdefault(rel, []).extend(problems)
    return report


def judge_cover_letter_artifact_problems(sb: Path, target_rows: list) -> list:
    """The judge's own M20 artifact must CATCH AND CONSIDER the target's FMT-CL1.

    A judge compares versions, but a cover letter formatted in the MANUSCRIPT
    template is a formatting defect of the version that carries it whether or
    not the opponent carries it too. When the orchestrator's scan of the blinded
    target finds FMT-CL1 (the code-side proof is in `judge_evidence`), the
    judge's M20 artifact has to record the row; an OK closure needs the journal's
    own template/guideline text quoted that REQUIRES the formatting (the same
    bar the review's disposition gate enforces).
    """
    problems = []
    rel = "judge_review/artifacts/M20_formatting.md"
    path = sb / rel
    raw = read_text_bounded(path) or ""
    if "FMT-CL1" not in raw.upper():
        problems.append(
            f"{rel} does not record the target's {len(target_rows)} FMT-CL1 row(s) "
            f"(a cover letter formatted in the MANUSCRIPT template): catch and consider "
            f"it -- state whether the compared versions carry it and how it weighs in the "
            f"formatting tier -- instead of leaving it out")
        return problems
    # Prefer the parsed table cells; a free-form note still gets the OK gate on
    # its own line. An OK closure without the journal's quoted override is the
    # disposition the pipeline exists to forbid.
    candidates = []
    for block in parse_markdown_blocks(path):
        for r in block["rows"]:
            cells = [str(v or "") for v in r.values()]
            if any("FMT-CL1" in c.upper() for c in cells):
                disp = " ".join(str(r.get(k) or "") for k in
                                ("disposition", "resolution", "verdict", "decision",
                                 "audit", "notes", "note")).strip()
                candidates.append(disp or " | ".join(cells))
    if not candidates:
        candidates = [ln.strip() for ln in raw.splitlines() if "FMT-CL1" in ln.upper()]
    for text in candidates:
        if not COVER_LETTER_OK_CLOSE_RE.match(text):
            continue
        if COVER_LETTER_OVERRIDE_CITE_RE.search(text) \
                and COVER_LETTER_OVERRIDE_REQUIRE_RE.search(text):
            continue
        problems.append(
            f"{rel}: the FMT-CL1 row is closed with OK but quotes no journal override -- "
            f"a cover letter formatted in the MANUSCRIPT template is a defect unless the "
            f"journal's own template/guideline text requires it, and that text must be "
            f"quoted in the row; otherwise consider it a formatting-tier defect of the "
            f"version that carries it")
    return problems


def artifact_quality_notes(review_dir: Path) -> dict:
    """{artifact: [notes]} for tables the parser had to read tolerantly.

    These are WARNINGS, never failures: a row with one cell more than its header
    whose verdict was appended after the seeded empty cell is read anyway (see
    _table_row), but the operator should still know the table's column count is
    off, because a row that shifted cells rather than appending one would be
    read positionally.
    """
    notes = {}
    for rel in DECISION_ARTIFACTS:
        appended = ragged = short = 0
        first_short = ""
        for block in parse_markdown_blocks(review_dir / rel):
            appended += block["appended"]
            ragged += block["ragged"]
            n_head = len(block["header"])
            for i, w in enumerate(block.get("widths") or []):
                if w < n_head:
                    short += 1
                    first_short = first_short or f"row {i + 1} has {w} cell(s), the header {n_head}"
        msgs = []
        if appended:
            msgs.append(f"{appended} row(s) carry one more cell than their header; the appended "
                        f"trailing cell was read as the "
                        f"{'/'.join(DISPOSITION_COLUMNS)} value -- write the verdict IN the "
                        f"seeded cell instead of after it")
        if short:
            msgs.append(f"{short} row(s) are NARROWER than their own header ({first_short}); a "
                        f"short row is read positionally, so a verdict written after the seeded "
                        f"cells lands one column early and the disposition cell reads EMPTY -- "
                        f"re-emit those rows with one cell per column")
        if ragged:
            msgs.append(f"{ragged} row(s) do not match their table's column count and were read "
                        f"positionally; check the table")
        if msgs:
            notes[rel] = msgs
    return notes


def check_artifact_quality(ctx: Ctx, rec: dict, sb: Path, errs: list, warns: list) -> dict:
    """Record (and optionally fail) the review's decision-artifact quality."""
    report = artifact_quality_report(sb / GUIDED_REVIEW_DIR, require_files=True)
    rec["artifact_quality"] = report
    for rel, problems in sorted(report.items()):
        for p in problems:
            msg = f"decision artifact {rel}: {p}"
            (errs if strict_dispositions(ctx) else warns).append(msg)
    for rel, notes in sorted(artifact_quality_notes(sb / GUIDED_REVIEW_DIR).items()):
        for n in notes:
            warns.append(f"decision artifact {rel}: {n}")
    return report


# =====================================================================
# SCOPED ARTIFACT REPAIR (`--strict-artifacts fix`) -- ONE PROFILE PER STAGE
#
# A mode whose contract is "make the postcheck pass" is the failure mode the
# decision-artifact layer exists for (a session once closed 96 rows with one
# sentence), so the repair session is defined by what it may NOT do. Every stage
# has a PROFILE that says (a) which postcheck problems are repairable at all,
# (b) which files it may write, and (c) which parts of those files are pinned
# evidence. The rules are the same everywhere:
#
#   * Only BOOKKEEPING is repairable: the reports, ledgers and sheets the
#     postcheck reads. A manuscript document, a code file, a corpus input, a
#     missing deliverable, a validation failure, a coverage/contract violation,
#     the M1b vanishing-residue gate or the pristine copy stay PLAIN FAILURES --
#     they encode judgement or content the session had to supply, and a repair
#     that "satisfied" them would launder a missing stage into a finished one.
#   * Inside a bookkeeping file the repair may FILL what the sandbox's own
#     evidence proves, and must write the pipeline's honest escape
#     (`unable — manual verification required: ...`) where it cannot. Rows of
#     evidence -- a decision-table row's document/counts, a judge's ledger, an
#     auditor's drop -- are IDENTITY: they may not be added, deleted, reordered
#     or re-worded.
#   * The orchestrator verifies (b) and (c) byte-for-byte / structurally on disk
#     BEFORE it re-runs the identical postcheck. A repair that went outside its
#     scope is a failed attempt, and everything it did stays in the archive.
# =====================================================================

REPAIR_PROMPT_FILE = "REPAIR_PROMPT.md"
# A repair is a few hundred lines of editing, not a review session: cap it even
# when the stage timeout is generous (an LLM that runs for an hour on this is
# not doing the bounded job the mode promises).
REPAIR_TIMEOUT_MAX = 3600
# --- CONTINUATION of a STOPPED session (`codex exec resume <id>`) -----------
# A session that ends before its deliverables exist (a stalled turn, a CLI
# timeout, a killed process) leaves a resumable transcript: `codex exec resume
# <session-id>` continues it with the whole context -- the corpus it read, the
# donors it compared, the plan it made -- instead of paying for a fresh attempt
# that reads everything again. That is a CONTINUATION of the stage's own work,
# never paperwork (the scoped artifact repair is the paperwork tool), so it is
# tried FIRST when an attempt ends unfinished, and at most
# RESUME_ATTEMPT_LIMIT times per session id.
RESUME_PROMPT_FILE = "RESUME_PROMPT.md"
RESUME_ATTEMPT_LIMIT = 2
# A provider request that already exceeded its payload/context limit keeps
# exceeding it when resumed: `codex exec resume` resends the whole session.
# Recognise that failure so the retry policy goes straight to a FRESH context
# instead of spending continuation calls that can only fail again.
AGENT_CONTEXT_OVERFLOW_RE = re.compile(
    r"(?im)(?:"
    # `unexpected status 413`, `HTTP 413: ...`, `status code 413`
    r"^\s*(?:error[:\s]+)?(?:unexpected\s+)?(?:status(?:\s+code)?|http(?:/\d(?:\.\d+)?)?)"
    r"[:\s]+413\b"
    r"|^\s*(?:error[:\s]+)?[^\n]{0,80}\brequest entity too large\b"
    r"|^\s*(?:error[:\s]+)?payload too large\b"
    # a bare status line (`413 Payload Too Large`, `Error: 413 - payload too
    # large`): the status number makes it error-shaped even without the word
    # `HTTP`/`status` in front, so the anchored patterns above miss it.
    r"|\b413\b[^\n]{0,60}\b(?:payload|request|entity)\b[^\n]{0,30}\btoo large\b"
    r"|\bcontext_length_exceeded\b"
    r"|\bmaximum context length\b"
    # both word orders: "context window ... exceeded" and "exceeds ... context window"
    r"|\bcontext (?:length|window)\b[^\n]{0,100}\b(?:exceed(?:s|ed)?|too (?:large|long))\b"
    r"|\b(?:exceed(?:s|ed)?|too (?:large|long))\b[^\n]{0,100}\bcontext (?:length|window)\b"
    r"|\b(?:prompt|input|request)\b[^\n]{0,50}\btoo (?:long|large)\b"
    r"|\btoo many tokens\b"
    r"|\blength limit exceeded\b"
    r"|\brequest body\b[^\n]{0,80}\b(?:too large|limit exceeded)\b"
    r")")


# A stdout line is evidence of a PROVIDER failure only when the line itself is
# error-shaped. The overflow regex above must stay broad enough to recognise a
# provider's own wording; applied to a session's normal output it also matched
# manuscript prose ("... the maximum context length ..." / "413 cells ... too
# large"). stderr is the provider's error channel and is scanned whole; stdout
# is filtered to these line starts first.
_ERROR_SHAPED_STDOUT_RE = re.compile(
    r"(?i)^\s*(?:\[?\d{4}-\d{2}-\d{2}[T ][0-9:.,+\-Z]+\]?\s*)?"
    r"(?:\[?(?:error|fatal|panic)\]?[:\s]+)?"
    r"(?:error\b|fatal\b|panic\b|http(?:/\d(?:\.\d+)?)?\b|status(?:\s+code)?\b"
    r"|unexpected\b"
    # A bare status is error-shaped only with a payload/limit word after it:
    # `413 cells in the request group were too large` is prose, not a status.
    r"|\d{3}\s*[-:]?\s*(?:payload|request(?:\s+entity)?|too\s+large)\b"
    r"|payload\b|request\s+entity\b|context_length\b"
    r"|maximum\s+context\b|context\s+(?:length|window)\b"
    # `prompt`/`input`/`request` alone are ordinary nouns; require the
    # error-shaped continuation the overflow wording uses.
    r"|prompt\s+(?:is|was|too|exceeds?|exceeded|length)\b"
    r"|input\s+(?:is|was|too|exceeds?|exceeded|length|tokens?)\b"
    r"|request\s+(?:body|entity|is|was|too|exceeds?|exceeded|header|size|payload)\b"
    r"|too\s+many\s+tokens\b|length\s+limit\b"
    # Structured error records and HTML error pages are error-shaped even when
    # their message does not start with a keyword.
    r"|\{\s*\"(?:error|level)\"\s*:"
    r"|\{\s*\"type\"\s*:\s*\"[^\"]*(?:error|exceeded)\""
    r"|<\s*(?:!doctype|html|head|title)\b)")


def agent_failure_kind(stdout: str = "", stderr: str = "") -> str:
    """A stable failure class read from the CLI's own transport errors.

    Only error-shaped stdout lines are considered (the process already failed,
    but its normal output can quote a manuscript); stderr is the error channel
    and is read whole.
    """
    stdout_errors = "\n".join(
        line for line in (stdout or "").splitlines()
        if _ERROR_SHAPED_STDOUT_RE.match(line))
    # A pretty-printed JSON error record is ONE document: the line filter sees
    # only `{` / `"error": ...` lines and would drop it. A dict carrying an
    # `error` key (or an error/exceeded `type`) is the provider's structured
    # error channel, so its whole text is scanned.
    _stdout_text = (stdout or "").strip()
    if _stdout_text.startswith("{"):
        try:
            _structured = json.loads(_stdout_text)
        except (TypeError, ValueError):
            _structured = None
        if isinstance(_structured, dict) and (
                "error" in _structured
                or str(_structured.get("type") or "").lower().endswith(
                    ("error", "exceeded"))):
            stdout_errors = f"{stdout_errors}\n{_stdout_text}"
    text = f"{stdout_errors}\n{stderr or ''}"
    if AGENT_CONTEXT_OVERFLOW_RE.search(text):
        return "context_overflow"
    return ""


# A continuation finishes a stage that is already 80% done: cap it well below
# the stage timeout (which defaults to 4h).
RESUME_TIMEOUT_MAX = 5400
# The CLI prints its session id in the banner (`session id: <uuid>`), or -- for a
# `claude` run configured with `--output-format json` -- in the result object
# (`"session_id": "<uuid>"`); `_execute_attempt_in` tees both into `_agent.log`,
# and that id is what `codex exec resume` / `claude --resume` consumes.
SESSION_ID_RE = re.compile(r'(?:session[_ ]id[:\s]+|"session_id"\s*:\s*")([0-9a-fA-F-]{36})')
# `dsh --json` opens its event stream with
#   {"type":"session","sessionId":"session-<uuid>","cwd":"…"}
# -- a camelCase key and a `session-` prefix, so the pattern above (codex's
# banner form, claude's snake_case result object) cannot read it. The id is what
# `dsh --profile headless --session-id <id>` adopts as a continuation.
DSH_SESSION_ID_RE = re.compile(r'"sessionId"\s*:\s*"(session-[0-9a-fA-F-]{36})"')
# Every artifact-quality message starts with this prefix (see
# `check_artifact_quality`): it is how a repairable review failure is told apart
# from every other kind without a second bookkeeping channel.
ARTIFACT_PROBLEM_PREFIX = "decision artifact "
REL_ARTIFACT_PREFIX = f"{GUIDED_REVIEW_DIR}/"
# The cells a repair may rewrite: the ones the detectors judge. Everything else
# in a seeded row -- the document, the location, the counts, the excerpt, the
# first sentence -- is the row's IDENTITY: deleting a row or re-wording its
# evidence would "fix" a table by removing what it has to dispose.
REPAIR_EDITABLE_CELLS = ("disposition", "resolution", "verdict", "summary", "decision",
                         "note", "notes", "why", "reason", "authoritative term")
# The tables a review repair may fill cell by cell. `DECISION_ARTIFACTS` is what
# the artifact-quality layer judges; `M1_acronyms.md` carries the M1b long-form
# table, whose per-row disposition is what its own gate reads. Everything else
# under guided_review/artifacts/ stays byte-identical.
REVIEW_REPAIR_TABLES = tuple(DECISION_ARTIFACTS) + ("artifacts/M1_acronyms.md",)
# The skip list of the attempt archive is the same one: re-derivable input
# corpora are verified by the postcheck's own input manifests, not here.
REPAIR_GUARD_SKIP_DIRS = ATTEMPT_ARCHIVE_SKIP_DIRS


# --- which postcheck problems each stage may repair ------------------------
# The messages are generated by the postchecks below this module section, so
# prefix/regex matching is stable and testable. Two families are shared:
REPAIR_MARKER_PATTERNS = (r"^completion marker _pipeline_done\.json missing ",
                          r"^marker stage mismatch: ", r"^marker run_id mismatch: ",
                          r"^marker round mismatch: ")
# A machine-readable deliverable the repair may rewrite from the sandbox's own
# evidence (a marker, a ledger, a sheet): "EMPTY/unfinished", "could not be
# read", over the size limit, or unparseable.
REPAIR_STRUCTURED_PATTERNS = (r" is EMPTY/unfinished \(structured output\)",
                              r" could not be read \(",
                              r" is \d+ bytes \(over the ",
                              r" does not parse as ",
                              # `_structured_problem_for` says "is malformed
                              # JSON (...)" for a truncated ledger; without this
                              # the cheap scoped repair never saw it.
                              r" is malformed [A-Za-z]+ \(")
REPAIR_VISUAL_PATTERN = r"^the visual-inspection record \S+ is missing: "
REPAIR_LANGUAGE_PATTERNS = tuple(
    rf"^{label}: no work/R6_language\.md " for label in ("rewrite", "revise", "integrate")) \
    + tuple(rf"^{label}: the language pass covers " for label in ("rewrite", "revise", "integrate"))
# The M1b long-form table (`guided_review/artifacts/M1_acronyms.md`) is a decision table
# too: its rows are residue occurrences the reviewer must dispose one by one (a
# finding, or OK with the row's own reason). The gate fires when the rows carry
# no reason AND the coverage row stays silent -- exactly the state a scoped repair
# can finish from the rows' own context/location columns.
REPAIR_M1B_PATTERNS = (r"^guided_review/artifacts/M1_acronyms\.md lists \d+ M1b long-form row\(s\)",)

REPAIR_PROFILES = {
    # The reviewer's decision tables: the only stage where the postcheck itself
    # is the artifact-quality layer.
    "guided_review": {
        "errors": (r"^decision artifact ",) + REPAIR_M1B_PATTERNS + (REPAIR_VISUAL_PATTERN,),
        "scope": "the seeded decision tables under guided_review/artifacts/ (including the M1b "
                 "long-form table; fill their judged cells), the visual record and guided_review/work/ "
                 "scratch",
        "guard": "the row identity of every decision table",
    },
    # The auditor's deliverable is a disposition sheet, not a manuscript: the
    # repair may complete it with the CONSERVATIVE verdict (confirm) only.
    "audit": {
        "errors": (REPAIR_MARKER_PATTERNS + REPAIR_STRUCTURED_PATTERNS
                   + (r"^audit/audit\.json ",
                      r"^\d+ frozen finding id\(s\) are neither confirmed nor dropped ",
                      r"^\S+ appears twice in dispositions$",
                      r"^dispositions\[\d+\] ",
                      r"^dispositions name \d+ id\(s\) that are not in the frozen review: ")),
        "scope": "audit/audit.json and audit/AUDIT.md",
        "guard": "every disposition already in the sheet, and the `adds` rows",
    },
    # The rewrite/revise/integrate arms: the PACKAGE is pinned, the pipeline's
    # bookkeeping inside it (reports, ledgers, work/ scratch) is repairable.
    "rewrite": {
        "errors": (REPAIR_MARKER_PATTERNS + REPAIR_STRUCTURED_PATTERNS
                   + (REPAIR_VISUAL_PATTERN,) + REPAIR_LANGUAGE_PATTERNS
                   + (r"^rewritten/REWRITE_REPORT\.md is missing: ",
                      r"^rewritten/REWRITE_REPORT\.md is EMPTY \(structured output\): ",
                      r"^rewrite: REWRITE_REPORT\.md declares level ")),
        "scope": "the bookkeeping files inside rewritten/ (REWRITE_REPORT.md, CHANGELOG.md, "
                 "MANUAL_STEPS.md, VISUAL_CHECK.md) plus rewritten/work/ scratch",
        "guard": "every manuscript file of the package, and the package's layout",
    },
    "revise": {
        "errors": (REPAIR_MARKER_PATTERNS + REPAIR_STRUCTURED_PATTERNS
                   + (REPAIR_VISUAL_PATTERN,) + REPAIR_LANGUAGE_PATTERNS
                   + (r"^revised/revision_report\.json is missing: ",
                      r"^revised/revision_report\.json does not carry the revision ledger ",
                      r"^revised/revision_report\.json is EMPTY/unfinished \(structured output\): ",
                      r"^revised/revision_report\.json does not name ")),
        "scope": "the bookkeeping files inside revised/ (revision_report.json, "
                 "REVISION_REPORT.md, CHANGELOG.md, MANUAL_STEPS.md, VISUAL_CHECK.md, "
                 "DIFF_LEDGER.md) plus revised/work/ scratch",
        "guard": "every manuscript file of the package, and the package's layout",
    },
    "integrate": {
        "errors": (REPAIR_MARKER_PATTERNS + REPAIR_STRUCTURED_PATTERNS
                   + (REPAIR_VISUAL_PATTERN,) + REPAIR_LANGUAGE_PATTERNS
                   + (r"^integrated/DIFF_LEDGER\.md is missing: ",
                      r"^integrated/DIFF_LEDGER\.md never names \d+ discovery finding id\(s\) ",
                      r"^integrate: \d+ ledger row\(s\) carry no `artifact` ")),
        "scope": "the bookkeeping files inside integrated/ (DIFF_LEDGER.md, "
                 "revision_report.json, REVISION_REPORT.md, CHANGELOG.md, MANUAL_STEPS.md, "
                 "VISUAL_CHECK.md) plus integrated/work/ scratch",
        "guard": "every manuscript file of the package, and the package's layout",
    },
    # The judge's sheet: the repair may make it CONSISTENT WITH ITSELF (the
    # integer is a function of the ledger) and complete its coverage record with
    # `unable` rows -- never move a judgement.
    "judge": {
        "errors": (REPAIR_MARKER_PATTERNS + REPAIR_STRUCTURED_PATTERNS
                   + (r"^run_id mismatch: ", r"^target_id mismatch: ",
                      r"^comparisons\[\d+\] is not an object$",
                      r"^comparisons\[\d+\]\.score must be an integer ",
                      r"^comparisons\[\d+\] has no `basis`",
                      r"^comparisons\[\d+\]\.basis = ",
                      r"^comparisons\[\d+\]\.basis ",
                      r"^comparisons\[\d+\] has no `checks` coverage map",
                      r"^comparisons\[\d+\]\.checks\[",
                      r"^comparisons\[\d+\]\.checks omits ",
                      r"^comparisons\[\d+\]\.checks names ",
                      r"^comparisons\[\d+\]: ",
                      r"^scores\.json is missing or unparseable although the marker claims "
                      r"completion")),
        "scope": "scores.json and judge_review/ (the frozen-sweep grounding record) plus "
                 "judge_review/artifacts/ scratch",
        "guard": "every ledger row (resolved/introduced), every comparison's identity and the "
                 "existing coverage entries",
    },
}


def repair_profile(rec: dict) -> dict:
    """The repair profile of a run's kind ({} when the stage has none)."""
    return REPAIR_PROFILES.get(str(rec.get("kind") or "")) or {}


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
    and is left alone: the retry policy then runs a fresh attempt as before.
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
    """(argv, key, reason): the continuation to run, or ([], key, "").

    A failed attempt that looks UNFINISHED but cannot be continued says so on the
    console (the same way `repairable_artifact_failure` reports a refused repair):
    the operator has to be able to tell "no resume form for this backend" and
    "the 2-continuation limit is spent" from "the attempt finished and was
    rejected on its content".
    """
    sid = str(rec.get("agent_session_id") or "")
    key = sid or "__continue__"
    reason = resume_unfinished_reason(ctx, rec)
    if not reason:
        return [], key, ""
    if rec.get("last_failure_kind") == "context_overflow":
        why = ("the provider already rejected this session's request as too large; "
               "resuming resends the same context, so a FRESH attempt follows")
        print(f"  [resume] {rec['id']}: no continuation -- {why}")
        return [], key, ""
    argv = resume_argv_for(cmd, sid)
    if not argv:
        why = ("this backend has no resume form (only the codex/claude/dsh presets do), or "
               "no session id was captured")
        print(f"  [resume] {rec['id']}: no continuation -- {why}; a fresh attempt follows")
        return [], key, ""
    used = int((rec.get("resume_attempts") or {}).get(key) or 0)
    if used >= RESUME_ATTEMPT_LIMIT:
        why = (f"{used} continuation(s) already spent on this session "
               f"(limit {RESUME_ATTEMPT_LIMIT})")
        print(f"  [resume] {rec['id']}: no continuation -- {why}; a fresh attempt follows")
        return [], key, ""
    return argv, key, reason


def resume_prompt(rec: dict, problems: list, reason: str, used: int) -> str:
    """The CONTINUATION prompt: finish the stage's own work, marker last."""
    listed = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(problems)) or "  (none recorded)"
    return with_context_budget((
        "CONTINUATION - YOUR OWN SESSION STOPPED BEFORE IT FINISHED.\n\n"
        f"Run: {rec['id']}   stage: {rec.get('kind')}   round: {rec.get('round')}\n"
        f"This is continuation {used + 1} of at most {RESUME_ATTEMPT_LIMIT} for this session.\n"
        "Your working directory is the same sandbox you were in, holding exactly the files you "
        "left; nothing was rebuilt and nothing was thrown away. Your context -- the packages you "
        "read, the differences you found, the plan you were following -- is still yours.\n\n"
        f"WHY YOU ARE BEING RESUMED: {reason}\n\n"
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
        f"  * Write the completion marker `{MARKER_FILE}` LAST, when the package and its "
        "bookkeeping are actually done. It is the only completion signal this pipeline accepts.\n"
        "  * If something cannot be finished honestly, use the pipeline's escape: write "
        "`unable — manual verification required: <what the author must check>` in the ledger / "
        "language pass / visual record, record the item in MANUAL_STEPS.md, and say so in the "
        "marker.\n"
        "  * Stay inside this sandbox; never touch sibling sandboxes or parent directories.\n"))


def repairable_artifact_failure(ctx: Ctx, rec: dict) -> list:
    """The problems ONE scoped repair session may fix for this attempt ([] if none).

    Repairable means: the policy is `fix`, the run's stage has a repair profile,
    EVERY problem in the postcheck matches that profile's bookkeeping patterns,
    the files the problems live in EXIST (variant B: a repair completes the
    bookkeeping of a stage that ran; it never authors a deliverable the stage
    never wrote), and this attempt has not already been sent to a repair session
    (one repair per failed attempt -- a repair that does not clear the problem is
    a failed attempt like any other, and the normal retry policy decides what
    happens next).
    """
    if not artifact_repair_enabled(ctx):
        return []
    profile = repair_profile(rec)
    if not profile:
        return []
    if attempt_number(rec) in (rec.get("repair_attempts") or []):
        return []
    pc = rec.get("postcheck") or {}
    errors = [str(e) for e in (pc.get("errors") or [])]
    if not errors:
        return []
    patterns = [re.compile(p) for p in profile.get("errors") or ()]
    if not all(any(p.search(e) for p in patterns) for e in errors):
        return []
    absent = repair_missing_deliverable(ctx, rec, errors)
    if absent:
        print(f"  [repair] {rec['id']}: NO repair -- the stage never wrote {absent}. A repair "
              f"completes the bookkeeping of a stage that ran; it never authors a deliverable. "
              f"This attempt FAILS: re-run the stage (a plain `run`, or `--only "
              f"{rec.get('kind')}`), or `retry --run {rec['id']}` first to reset it.")
        return []
    return errors


# --- variant B: a repair completes files, it never creates them -------------
# A problem of the "… is missing" family names a file the STAGE failed to write.
# The repair may touch it only if it actually exists (present but empty/malformed
# -- its CONTENT is then the repair's business); otherwise the stage never
# finished its work and the attempt must fail.
# The "… is missing" family, in the exact wordings the postchecks use:
# "… _pipeline_done.json missing (it is prompted as the very last step…",
# "integrated/DIFF_LEDGER.md is missing: …", "no work/R6_language.md -- …",
# "scores.json is missing or unparseable although the marker claims completion".
# A marker FIELD that "is missing/not an integer" does not match: it names no
# file, so it stays a content problem of a file that exists.
REPAIR_MISSING_RE = re.compile(r"\bis missing\b|\bmissing\b\s*[:(]|no work/r6_language\.md",
                               re.I)
REPAIR_FILE_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|json|docx|tex)")


def _resolve_in_sandbox(sb: Path, rec: dict, cand: str) -> Path:
    """Resolve a file name from a postcheck message inside this sandbox."""
    rel = str(cand).strip("`'\"(),;:")
    kind = str(rec.get("kind") or "")
    roots = [sb, sb / output_dir_for_kind(kind), sb / GUIDED_REVIEW_DIR, sb / "audit",
             sb / "judge_review", sb / output_dir_for_kind(kind) / "work"]
    for root in roots:
        p = root / rel
        if p.is_file():
            return p
    return sb / rel


def repair_missing_deliverable(ctx: Ctx, rec: dict, problems: list) -> str:
    """The file an "… is missing" problem names, when a repair may NOT supply it ("" if none).

    Variant B (operator decision, 2026-09-23): "a repair finishes the paperwork of
    work that happened; it never substitutes for the work". So a missing-family
    problem is repairable only when the file it names EXISTS -- a present but
    empty/malformed marker or ledger is content the repair may fix. Otherwise the
    stage stopped before doing (or reporting) its work and the attempt must fail.
    """
    try:
        sb = ctx.sandbox_of(rec)
    except Exception:                                            # noqa: BLE001
        sb = None
    for err in problems:
        if not REPAIR_MISSING_RE.search(str(err)):
            continue
        # The missing-marker message ends by telling the operator to write the
        # marker "next to PROMPT.md". The prompt is seeded into every sandbox,
        # so treating it as a deliverable made `any(...is_file())` true and the
        # genuinely absent marker was never reported (and the doomed scoped
        # repair was scheduled instead of the resume path).
        cands = [c for c in REPAIR_FILE_RE.findall(str(err))
                 if Path(c).name not in ("PROMPT.md", REPAIR_PROMPT_FILE)]
        if not cands:
            # a content-level "… is missing" (a marker FIELD, say): the file
            # itself exists, so its content stays the repair's business
            continue
        if sb is not None and sb.is_dir() and cands \
                and any(_resolve_in_sandbox(sb, rec, c).is_file() for c in cands):
            continue                       # present: its CONTENT is what the repair fixes
        return cands[0]
    return ""


# --- what a repair may write, per stage ------------------------------------
def _repair_path_writable(rel: Path, kind: str) -> bool:
    """May the repair overwrite this sandbox-relative FILE (or create it)?"""
    parts = tuple(p for p in rel.parts if p)
    if not parts:
        return False
    name = parts[-1].lower()
    if name in (MARKER_FILE.lower(), REPAIR_PROMPT_FILE.lower()) or name.startswith("_agent.log"):
        return True                          # the completion marker / our own transcript
    if name == "manual_steps.md" and kind in ("rewrite", "revise", "integrate"):
        return True                          # the stage's manual-item list (reported only)
    if kind == "guided_review":
        # The seeded decision tables (cell-editable; M1's long-form table included)
        # and the session's scratch. The visual record and the marker may be
        # CORRECTED when the reviewer wrote them; a review that never produced one
        # has not finished, and variant B never lets a repair author it.
        if parts[:2] == (GUIDED_REVIEW_DIR, "work"):
            return True
        if rel.as_posix() == VISUAL_ARTIFACT_REVIEW:
            return True
        return rel.as_posix() in {f"{GUIDED_REVIEW_DIR}/{r}" for r in REVIEW_REPAIR_TABLES}
    if kind == "audit":
        return parts[0] == "audit"
    if kind == "judge":
        return parts[0] == "judge_review" or rel.as_posix() == SCORES_FILE
    if kind in ("rewrite", "revise", "integrate"):
        pkg = output_dir_for_kind(kind)
        if parts[0] != pkg:
            return False
        return (len(parts) > 1 and parts[1] == "work") or is_bookkeeping_name(name)
    return False


def _repair_path_creatable(rel: Path, kind: str) -> bool:
    """May the repair CREATE this file?

    Only inside the stage's own writable DIRECTORY: a new helper file or a
    rendered page next to the tables/sheets it belongs to is harmless (nothing
    reads it), while a new file anywhere else -- beside findings.json, inside the
    package root, in the corpus -- is out of scope.
    """
    if _repair_path_writable(rel, kind):
        return True
    parts = tuple(p for p in rel.parts if p)
    if kind == "guided_review":
        return parts[:2] in ((GUIDED_REVIEW_DIR, "artifacts"), (GUIDED_REVIEW_DIR, "work"))
    if kind == "audit":
        return parts[0] == "audit"
    if kind == "judge":
        return parts[0] == "judge_review"
    if kind in ("rewrite", "revise", "integrate"):
        pkg = output_dir_for_kind(kind)
        return len(parts) > 1 and parts[0] == pkg and parts[1] == "work"
    return False


def _repair_scope_of(rel: Path, kind: str) -> str:
    """`scratch` (write freely) | `cells` (a decision table: fill cells only) |
    `protected` (byte-identical).

    The three-way split is the whole contract of the repair mode: the seated
    decision tables are cell-editable (their ROW identity is checked separately),
    every other writable file is the session's own scratch or a bookkeeping file
    it may rewrite, and everything else -- findings, the manuscript documents,
    the corpus inputs, the other stages' artifacts -- may not change at all.
    """
    if not _repair_path_writable(rel, kind):
        return "protected"
    parts = tuple(p for p in rel.parts if p)
    if parts and parts[-1].lower() == MARKER_FILE.lower():
        return "file"                        # rewritten from evidence, not cell-edited
    if kind == "guided_review" and rel.as_posix() in {f"{GUIDED_REVIEW_DIR}/{r}"
                                               for r in REVIEW_REPAIR_TABLES}:
        return "cells"
    if len(parts) > 1 and parts[1] == "work":
        return "scratch"
    if parts and parts[0] == GUIDED_REVIEW_DIR and len(parts) > 1 and parts[1] == "work":
        return "scratch"
    return "file"


def decision_artifact_rel_paths(sb: Path) -> list:
    """The decision artifacts this sandbox actually has (as guided_review/-relative paths)."""
    return [rel for rel in DECISION_ARTIFACTS if (sb / GUIDED_REVIEW_DIR / rel).is_file()]


def review_repair_table_rel_paths(sb: Path) -> list:
    """The review tables a repair may fill (decision artifacts + the M1b table)."""
    return [rel for rel in REVIEW_REPAIR_TABLES if (sb / GUIDED_REVIEW_DIR / rel).is_file()]


def _repair_table_rows(md_text: str) -> list:
    """The row IDENTITY of every table in one decision artifact, in order.

    Each row contributes its cells for the columns a repair may NOT rewrite, and
    rows/columns are compared in order -- so a repair that deletes a row,
    reorders the table, rewrites a row's evidence, or adds a row fails the guard
    even though the artifact still parses.
    """
    out, header, after_header = [], None, False
    for line in str(md_text or "").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            # A blank line or a heading ends the table block; the next `|`
            # line is a NEW table's header, not another row of the old one.
            header, after_header = None, False
            continue
        cells = _m1b_cells(s)
        if not cells:
            continue
        if header is None:
            header = [c.strip().lower() for c in cells]
            after_header = True
            continue
        # Only the row immediately below the header is the divider. A mid-table
        # dash-only row is DATA (GFM renders it as a row) and must keep its
        # identity for the repair guard.
        if after_header and _m1b_separator(cells):
            after_header = False
            continue
        if len(cells) != len(header):
            # A different column count means a new table block (the documented
            # M20 artifact carries a seeded table and the session's coverage
            # table); take this line as the new header, exactly as
            # _repair_table_skeleton already does.
            header = [c.strip().lower() for c in cells]
            after_header = True
            continue
        if all(c.strip().lower() == header[i] for i, c in enumerate(cells)):
            continue                          # a repeated header, not a row
        after_header = False
        keep = [i for i, h in enumerate(header) if h not in REPAIR_EDITABLE_CELLS]
        out.append(tuple((cells[i].strip() if i < len(cells) else "") for i in keep))
    return out


def _repair_table_skeleton(md_text: str) -> str:
    """The artifact's text with every repair-editable CELL blanked.

    The row-identity check pins the rows; this pins everything else a repair must
    not touch -- the table's header and column order, the separator, the prose
    around the table, the escape characters -- by comparing the file with the
    judged cells removed. Only cells a repair may fill can differ between two
    files with the same skeleton.
    """
    out, header, after_header = [], None, False
    for line in str(md_text or "").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            out.append(line)
            # A blank line or a heading ends the table block: the next `|` line is
            # a NEW table's header, with its own column names (the M1 artifact
            # carries an inventory table and the M1b table side by side).
            if not s or s.startswith("#"):
                header, after_header = None, False
            continue
        cells = _m1b_cells(s)
        if not cells:
            out.append(line)
            continue
        # A different column count means a new table (or a ragged row): take it as
        # the block's header rather than blanking cells against the wrong columns.
        if header is None or len(cells) != len(header):
            header = [c.strip().lower() for c in cells]
            after_header = True
            out.append(line)
            continue
        # The divider is the row immediately under the header; a mid-table
        # dash-only row is data and must be blanked like any other row, or the
        # guard's two parsers disagree about which row is which.
        if after_header and _m1b_separator(cells):
            after_header = False
            out.append(line)
            continue
        if all(c.strip().lower() == header[i] for i, c in enumerate(cells)):
            out.append(line)
            continue
        after_header = False
        blanked = [("" if header[i] in REPAIR_EDITABLE_CELLS else cells[i])
                   for i in range(min(len(cells), len(header)))]
        blanked += cells[len(header):]
        out.append("| " + " | ".join(blanked) + " |")
    return "\n".join(out)


def _repair_guard_files(sb: Path, kind: str) -> dict:
    """{rel path: sha256} for every file a repair may NOT touch.

    The input corpora (`base/`, `non_revised/`, a judge's views, the donor
    packages) are left out: the postcheck's own input manifests verify them, and
    hashing 180 MB twice per repair would cost more than the repair. Everything
    else the sandbox carries -- the manuscript files of the package, the finding
    list, the other stages' artifacts, the prompt -- is covered, except the files
    this stage's profile may rewrite.
    """
    out = {}
    for p in sorted(sb.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(sb)
        parts = tuple(x for x in rel.parts if x)
        if not parts or parts[0] in REPAIR_GUARD_SKIP_DIRS:
            continue
        if is_bytecode_cache(rel):
            continue                          # a cache of RUNNING a tool, not an edit
        if any(parts[:len(sub)] == sub for sub in ATTEMPT_ARCHIVE_SKIP_SUBTREES):
            continue
        if _repair_path_writable(rel, kind):
            continue                          # inside the repair's own scope
        if p.name.startswith("_agent.log"):
            continue                          # the session's transcript
        try:
            out[rel.as_posix()] = sha256_file(p)
        except OSError:
            continue
    return out


def _repair_read_json(path: Path):
    # Agent-written audit/repair JSON: shared regular-file/no-follow/byte-budget
    # reader (F38).
    text = read_text_bounded(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _repair_audit_rows(sb: Path) -> dict:
    """{frozen id: (verdict, reason, evidence)} of an audit sheet, plus its add ids."""
    audit = _repair_read_json(sb / "audit" / "audit.json")
    rows = {}
    if isinstance(audit, dict) and isinstance(audit.get("dispositions"), list):
        for row in audit["dispositions"]:
            if isinstance(row, dict) and str(row.get("id") or "").strip():
                rows[str(row["id"]).strip()] = (str(row.get("verdict") or "").strip().lower(),
                                                str(row.get("reason") or "").strip(),
                                                str(row.get("evidence") or "").strip())
    out = {"dispositions": rows, "adds": []}
    if isinstance(audit, dict) and isinstance(audit.get("adds"), list):
        out["adds"] = sorted({str((r or {}).get("id") or "").strip() for r in audit["adds"]
                              if isinstance(r, dict)})
    return out


def _repair_judge_rows(sb: Path) -> dict:
    """{label: {ledger, checks, score}} of a judge sheet: what may not move."""
    sj = _repair_read_json(sb / SCORES_FILE)
    out = {}
    if isinstance(sj, dict) and isinstance(sj.get("comparisons"), list):
        for c in sj["comparisons"]:
            if not isinstance(c, dict):
                continue
            label = _norm_opponent_label(c.get("opponent_label"))
            if not label:
                continue
            checks = {}
            if isinstance(c.get("checks"), dict):
                checks = {str(k): str(v or "") for k, v in c["checks"].items()}
            out[label] = {"ledger": json.dumps([c.get("resolved") or [],
                                                c.get("introduced") or []], sort_keys=True),
                          "checks": checks, "score": c.get("score"),
                          "basis": str(c.get("basis") or "").strip().lower()}
    return out


def snapshot_repair_guard(sb: Path, rec: dict) -> dict:
    """What the repair must leave alone: protected bytes + pinned structure.

    The structural half is per stage: a review's decision-table ROWS, an
    auditor's existing dispositions (and its `adds`), a judge's ledger rows and
    existing coverage entries. Those are the evidence; the cells around them are
    what the repair may fill. `editable` pins WHICH files exist: variant B lets a
    repair complete them, never create a deliverable the stage did not write.
    """
    kind = str(rec.get("kind") or "")
    tables, digests = {}, {}
    for rel in review_repair_table_rel_paths(sb):
        path = sb / GUIDED_REVIEW_DIR / rel
        text = read_text_bounded(path) or ""
        tables[rel] = {"rows": _repair_table_rows(text), "skeleton": _repair_table_skeleton(text)}
        try:
            digests[rel] = sha256_file(path)          # the repair's own diff, for the record
        except OSError:
            digests[rel] = ""
    return {"kind": kind, "files": _repair_guard_files(sb, kind), "tables": tables,
            "editable": sorted(p.relative_to(sb).as_posix()
                               for p in _repair_writable_files(sb, kind)),
            "artifacts": digests, "audit": _repair_audit_rows(sb),
            "judge": _repair_judge_rows(sb)}


def _repair_writable_files(sb: Path, kind: str) -> list:
    """Every file that exists inside the repair's own writable scope."""
    out = []
    for p in sorted(sb.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(sb)
        if _repair_path_writable(rel, kind):
            out.append(p)
    return out


def _is_repair_plumbing(rel) -> bool:
    """The orchestrator's own repair-session files (never 'the stage's writing')."""
    name = Path(str(rel)).name
    return name == REPAIR_PROMPT_FILE or name.startswith("_agent.log")


def _repair_row_identity_problems(sb: Path, guard: dict) -> list:
    """The review profile's structural guard: every table's row identity."""
    problems = []
    for rel, pinned in sorted((guard.get("tables") or {}).items()):
        pinned = pinned if isinstance(pinned, dict) else {"rows": pinned, "skeleton": None}
        rows, skeleton = pinned.get("rows") or [], pinned.get("skeleton")
        path = sb / GUIDED_REVIEW_DIR / rel
        if not path.is_file():
            problems.append(f"it DELETED the decision artifact {REL_ARTIFACT_PREFIX}{rel}")
            continue
        text = read_text_bounded(path)
        if text is None:
            problems.append(f"the decision artifact {REL_ARTIFACT_PREFIX}{rel} cannot be read "
                            f"(unreadable, non-regular, or over the byte budget)")
            continue
        now = _repair_table_rows(text)
        if now != rows:
            # Name the FIRST divergence: the operator (and the next session) can
            # see whether a row vanished or its evidence was re-worded.
            why = "a row was deleted, added or reordered"
            if len(now) == len(rows):
                for i, (a, b) in enumerate(zip(rows, now)):
                    if a != b:
                        why = (f"row {i + 1}'s identity cells changed "
                               f"({a[:3]!r} -> {b[:3]!r})")
                        break
            problems.append(f"it rewrote the seeded rows of {REL_ARTIFACT_PREFIX}{rel}: {why} "
                            f"(a repair may fill cells, never add, delete, reorder or re-word a "
                            f"row's own evidence)")
        elif skeleton is not None and _repair_table_skeleton(text) != skeleton:
            problems.append(f"it rewrote the header, the prose or a non-editable column of "
                            f"{REL_ARTIFACT_PREFIX}{rel} (only the judged cells may change: keep "
                            f"every column, the table's header and the text around it as they are)")
        if len(problems) >= 6:
            break
    return problems


def _repair_audit_problems(sb: Path, guard: dict) -> list:
    """The audit profile's guard: existing verdicts stand; only confirms may be added.

    A `drop` hides a finding from the revisers, so a repair may never create,
    widen or justify one: it may only dispose the ids the sheet left silent, and
    only as `confirm`.
    """
    problems = []
    before = guard.get("audit") or {}
    now = _repair_audit_rows(sb)
    for fid, row in sorted((before.get("dispositions") or {}).items()):
        if fid not in now["dispositions"]:
            problems.append(f"it DELETED the disposition of {fid} (an existing disposition is "
                            f"evidence and may not be removed)")
        elif tuple(now["dispositions"][fid]) != tuple(row):
            problems.append(f"it rewrote the existing disposition of {fid} "
                            f"({row[0] or 'no verdict'!r} -> "
                            f"{now['dispositions'][fid][0] or 'no verdict'!r}); a repair may only "
                            f"ADD dispositions, and only `confirm`")
    for fid, row in sorted((now.get("dispositions") or {}).items()):
        if fid not in (before.get("dispositions") or {}) and row[0] != "confirm":
            problems.append(f"it added a {row[0] or 'blank'!r} disposition for {fid}; a repair "
                            f"may only add `confirm` (dropping a finding is the auditor's own "
                            f"judgement and must keep its own reason and evidence)")
    added = set(now.get("adds") or []) - set(before.get("adds") or [])
    if added:
        problems.append(f"it invented finding(s) {', '.join(sorted(added)[:4])} in `adds`; a "
                        f"repair may complete the sheet's dispositions, never add findings")
    return problems[:6]


def _repair_judge_problems(sb: Path, guard: dict) -> list:
    """The judge profile's guard: the ledger is the judgement and stays untouched.

    The integer `score` is a FUNCTION of the ledger, derived lexicographically
    (minor 1 / major 2 / critical 3 / fatal 4 in the first non-zero tier, whose
    net is capped at +-4 and bounded by its own rows), and `basis` names that
    deciding tier, so the repair may recompute both. Everything the judge actually decided --
    resolved/introduced rows, the comparison set, existing coverage entries --
    may not move, and new coverage entries must be the honest `unable`.
    """
    problems = []
    before = guard.get("judge") or {}
    now = _repair_judge_rows(sb)
    gone = sorted(set(before) - set(now))
    if gone:
        problems.append(f"it removed the comparison(s) {', '.join(gone[:4])} (every issued label "
                        f"needs its comparison)")
    new = sorted(set(now) - set(before))
    if new:
        problems.append(f"it added comparison(s) {', '.join(new[:4])}; a repair may not judge an "
                        f"opponent the session never did")
    for label in sorted(set(before) & set(now)):
        b, n = before[label], now[label]
        if b["ledger"] != n["ledger"]:
            problems.append(f"it rewrote {label}'s resolved/introduced ledger; the ledger IS the "
                            f"judgement -- the repair may only make `score`/`basis` agree with it")
        for cid, text in sorted((b.get("checks") or {}).items()):
            if (n.get("checks") or {}).get(cid) != text:
                problems.append(f"it rewrote {label}'s existing `checks[{cid}]` coverage entry")
        for cid, text in sorted((n.get("checks") or {}).items()):
            if cid not in (b.get("checks") or {}) and not text.strip().lower().startswith("unable"):
                problems.append(f"it added {label}'s `checks[{cid}]` = {text[:40]!r}; a repair may "
                                f"only add `unable` coverage for a check it did not perform")
        if len(problems) >= 6:
            break
    return problems[:6]


def repair_guard_problems(sb: Path, guard: dict, rec: dict = None) -> list:
    """Out-of-scope changes made by a repair session ([] means in scope)."""
    kind = str((rec or {}).get("kind") or guard.get("kind") or "")
    problems = []
    before = dict(guard.get("files") or {})
    after = _repair_guard_files(sb, kind)
    for rel in sorted(set(before) | set(after)):
        if rel not in after:
            problems.append(f"it DELETED {rel}, which is outside the repair's scope")
        elif rel not in before:
            # A new file is fine only where the session may write at all; a new
            # file beside the finding list or in the corpus is not.
            if not _repair_path_creatable(Path(rel), kind):
                problems.append(f"it CREATED {rel}, which is outside the repair's scope")
        elif before[rel] != after[rel]:
            problems.append(f"it MODIFIED {rel}, which is outside the repair's scope")
        if len(problems) >= 6:
            break
    if len(problems) < 6 and "editable" in guard:
        # Variant B: within its WRITABLE scope the repair may only change files
        # that already existed (complete the stage's bookkeeping). A file it
        # brings into existence -- a ledger, a report, a marker, a visual record
        # -- is a deliverable it authored for a stage that never wrote one.
        before = set(guard.get("editable") or ())
        for p in _repair_writable_files(sb, kind):
            rel = p.relative_to(sb).as_posix()
            if rel in before or _is_repair_plumbing(rel) or is_bytecode_cache(rel):
                continue
            problems.append(f"it CREATED {rel}, which the stage never wrote (a repair completes "
                            f"the stage's own bookkeeping; it never authors a deliverable)")
            if len(problems) >= 6:
                break
    if len(problems) < 6 and kind == "guided_review":
        problems.extend(_repair_row_identity_problems(sb, guard))
    if len(problems) < 6 and kind == "audit":
        problems.extend(_repair_audit_problems(sb, guard))
    if len(problems) < 6 and kind == "judge":
        problems.extend(_repair_judge_problems(sb, guard))
    return problems[:6]
def _repair_prompt_body(ctx: Ctx, rec: dict, problems: list) -> str:
    """The scoped repair session's prompt: the problems, the rules, the limits.

    One prompt per stage, built from that stage's profile: what it may write, what
    it must not touch, and what "true" means for its bookkeeping. The review's
    variant is the long one (its tables carry the row-disposal rules); the other
    stages get the rules of their own ledger/sheet/report.
    """
    kind = str(rec.get("kind") or "")
    profile = repair_profile(rec)
    listed = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(problems))
    header = (f"ARTIFACT REPAIR — SCOPED SESSION (run {rec['id']}, stage {kind}, "
              f"round {rec['round']})")
    common_head = f"""{header}

You are NOT the {kind} session. That stage finished, and the orchestrator rejected its
BOOKKEEPING -- the report/ledger/sheet files the postcheck reads -- as unfilled, inconsistent or
unfinished. Your single job: repair exactly the problems below, from evidence that is ALREADY in
this sandbox. The manuscript/package itself is NOT yours to touch.

--- WHAT THE ORCHESTRATOR REJECTED ({len(problems)} problem(s)) ---
{listed}

--- WHERE YOU MAY WRITE (verified byte-for-byte / structurally afterwards) ---
  * {profile.get('scope')}
  * /tmp  -- scratch outside the sandbox
  * VARIANTS: you may only CHANGE files that already exist in this sandbox. You never CREATE a
    deliverable -- no ledger, no report, no language pass, no visual record, no completion
    marker. A stage that stopped before writing its files never finished its work, and the
    orchestrator re-runs it instead of fabricating its record.
Everything else must stay BYTE-IDENTICAL, above all:
  * the manuscript files/package contents (documents, code, figures) -- a repair never edits
    submission content, and never "fixes" a document, a citation or a number
  * the corpus inputs (base/, non_revised/, self/, others/, target/, field/) and the
    other stages' deliverables (guided_review/, audit/, scores.json as far as they are not yours)
  * the records this stage's own postcheck reads from the PACKAGE (a delivered document, a
    validation result) -- if one of those is broken, no repair can clear it and the attempt fails
"""
    if kind == "guided_review":
        sb = ctx.sandbox_of(rec)
        arts = decision_artifact_rel_paths(sb)
        files = "\n".join(f"  * {REL_ARTIFACT_PREFIX}{rel}" for rel in arts)
        return common_head + f"""
--- THE TABLES IN PLAY ---
{files}

--- HOW TO DISPOSE A ROW (the rule the postcheck applies) ---
  * One disposition per row and it must be about THAT row's own bar, not a blanket judgement:
    either a finding id (`F-004`), or `OK — <the bar this instance is inside, and why>`.
    "No journal rule", "editorial preference only", "not an error" are NOT dispositions for a
    row the scan put in the finding tier.
  * Never close many rows with the same sentence: the postcheck counts repeated dispositions and
    fails the table. Vary the reason with the row (its document, its heading, its rule id, the
    number the row carries).
  * An OUTLINE row's `summary` must state what the paragraph CLAIMS in your own words; copying
    the row's `first sentence` (or a prefix of it) counts as unfilled.
  * You may FILL and REPLACE the judgement cells ({', '.join(REPAIR_EDITABLE_CELLS)}), and
    nothing else: every row's own evidence (document, heading, paragraph, location, counts,
    excerpts, `first sentence`, identifiers) is IDENTITY -- no row may be added, deleted,
    reordered or re-worded. The table's HEADER, its column order and the prose around it are
    pinned as well: never add, remove or rename a column.
  * Only the files listed under THE TABLES IN PLAY may change at all; every other file under
    {ARTIFACTS_REL}/ is READ-ONLY (the later stages read them -- `M1_acronyms.md` above all).
""" + REPAIR_TAIL
    if kind in ("rewrite", "revise", "integrate"):
        pkg = output_dir_for_kind(kind)
        return common_head + f"""
--- WHAT TO FILL (from what this package actually contains) ---
  * The ledger/report rows must describe THIS package: cite its file names, sections and line
    references, and the ids the frozen review in this sandbox carries. Never invent a finding
    id, a number, a donor or a change that the package does not show.
  * {pkg}/revision_report.json (where this stage has one): one row per id the frozen review
    lists -- `fixed` / `not_applicable` / `unable` with the rationale and the evidence (the
    package location that proves it). Do not renumber or drop an id the review carries.
  * {pkg}/DIFF_LEDGER.md (integration): one row per ported or deliberately skipped difference,
    naming the donor, the size class, the finding effect and a before/after artifact reference
    (a file:line pair, or an outline diff) so the row can be re-checked.
    COMPLETE the ledger the stage wrote -- never author one it did not. Its table carries the
    ledger's own columns -- `donor` and `artifact` above all, plus `size` (small|large) and
    `finding effect` -- because the orchestrator reads THAT table: a separate orientation/summary
    table elsewhere in the file is welcome, but the ledger is the table with those columns.
    `artifact` names a REAL file that carries the row's before/after evidence -- a file the stage
    itself wrote (a before/after note under {pkg}/work/, say), or one of the package's own
    documents/sections. A row whose artifact does not exist cannot be re-checked, and a missing
    ledger is a failed attempt, not a repair job.
  * The language pass ({pkg}/work/R6_language.md): one row per change PLUS one coverage row for
    each of the steps that changed nothing -- every step needs a row. Complete the pass the stage
    wrote; a stage that never wrote one has not finished and is re-run, not repaired.
  * The visual record ({pkg}/VISUAL_CHECK.md): if the stage left one, render the package and LOOK
    at the pages (write the renders under {pkg}/work/), then record what you saw -- or write the
    honest negative ("the pages were NOT visually verified" plus the exact manual step). Never
    claim an inspection you did not perform, and never create the file yourself.
  * The completion marker can only be CORRECTED, never created: if it exists, its `run_id`,
    `stage`, `round` and summary fields must name THIS run (and clear whatever the problems
    above name). A marker the stage never wrote means the run never finished -- that attempt
    fails and the orchestrator re-runs the stage.
""" + REPAIR_TAIL
    if kind == "audit":
        return common_head + """
--- WHAT TO FILL (and the one direction you may not move) ---
  * audit/audit.json: every frozen finding id gets exactly one disposition. You may ONLY add a `confirm` row
    for an id the sheet left silent (use the finding's own evidence/location text from the frozen review
    in this sandbox, and name the finding's own check id in the reason).
  * You may NOT create, widen or "complete" a `drop`: a drop hides a finding from the revisers
    and needs the auditor's own evidence. An existing drop stays exactly as the auditor wrote it.
  * You may NOT add `AU-` findings, only complete the disposition of ids that are already there.
  * audit/AUDIT.md is the human-readable record of the same sheet; keep it consistent with it.
""" + REPAIR_TAIL
    if kind == "judge":
        return common_head + f"""
--- WHAT TO FILL (the sheet must be consistent WITH ITSELF) ---
  * The integer `score` is a FUNCTION of the sheet's own resolved/introduced ledger, derived
    LEXICOGRAPHICALLY: the FIRST tier in the priority order whose net is not zero decides the
    comparison (rows there weigh minor 1 / major 2 / critical 3 / fatal 4, resolved add and
    introduced subtract, the net is capped at +-4, and |net| is bounded by the deciding rows --
    MINOR-only reaches +-2, a MAJOR row +-3, a CRITICAL/FATAL row +-4; every lower tier is
    ignored; six zero nets = a clean 0), and `basis` names that deciding tier. If they disagree,
    recompute them from the ledger -- that is the only arithmetic you may do. Never change a
    ledger row, and never re-judge: if the ledger itself cannot support a score, that is not
    repairable and this attempt will fail.
  * `checks`: every comparison needs one disposition per frozen check id. You may add an entry
    ONLY as `unable — <why>` for a check this session did not perform, and you may not touch an
    entry that is already there. Never write `clean` or `findings` for a check you did not do.
  * `run_id`, `target_id` and `judge_index` are bookkeeping: they must name THIS run, the target
    token this sandbox was issued and this judge's index. Never invent provenance for another
    session, and never add a comparison for an opponent the sheet does not carry.
  * judge_review/ is the judge's frozen-sweep grounding record: if the problems above name it,
    write the inventory and the sweep rows the prompt requires from the blinded corpus here --
    reading and measuring, never guessing.
""" + REPAIR_TAIL
    return common_head + REPAIR_TAIL


def repair_prompt(ctx: Ctx, rec: dict, problems: list) -> str:
    """The scoped repair prompt, with the shared context-budget rule."""
    return with_context_budget(_repair_prompt_body(ctx, rec, problems))


REPAIR_TAIL = """
--- IF YOU CANNOT DO IT HONESTLY ---
Write the pipeline's escape instead of a claim: `unable — manual verification required: <what the
author must check>`. An unfilled row that says so is accepted; an invented one is a defect the
orchestrator (and the human gate) will attribute to this repair.

--- WHEN YOU ARE DONE ---
The orchestrator re-runs the SAME postcheck over this same sandbox; a repair that does not clear
every problem above is recorded as a failed attempt like any other. Keep your final message
short: which files you completed, and which rows you left `unable` (with the reason).
"""


def prepare_repair_session(ctx: Ctx, rec: dict, problems: list):
    """Write the repair prompt, pin the scope, record the attempt. None if impossible.

    The session runs in the FAILED ATTEMPT'S OWN sandbox (nothing is rebuilt, so
    it sees exactly what the postcheck judged) and counts as an attempt of the
    same run: `runs/<run>_try<N>_failed/`, and its outcome in `attempts_log`
    (source `artifact-repair`).
    """
    sb = ctx.sandbox_of(rec)
    if not sb.is_dir():
        return None
    # A fresh session may change the accepted revise package: the post-revise
    # chain's record describes the OLD bytes, so it must not suppress the chain
    # on the next acceptance.
    if rec.get("kind") == "revise":
        rec.pop("revision_audit", None)
        rec.pop("revision_repair", None)
        rec.pop("revision_chain", None)
    n = next_attempt_number(rec)
    write_text_atomic(sb / REPAIR_PROMPT_FILE, repair_prompt(ctx, rec, problems))
    guard = snapshot_repair_guard(sb, rec)
    rec["repair_attempts"] = list(rec.get("repair_attempts") or []) + [n]
    rec["artifact_repair"] = {"attempt": n, "problems": list(problems), "status": "running",
                              "started": utcnow(), "prompt": REPAIR_PROMPT_FILE}
    # The repair appends to the same transcript file as the stage session it
    # repairs (each session writes its own header naming the attempt), so the
    # archive keeps one timeline for that sandbox.
    flight = {"rid": rec["id"], "attempt": n, "problems": list(problems), "guard": guard,
              "log": str(sb.relative_to(ctx.root) / "_agent.log")}
    scope = str((repair_profile(rec) or {}).get("scope") or "").split(" plus ")[0]
    print(f"  [repair] {rec['id']}: {len(problems)} repairable bookkeeping problem(s) -> one "
          f"scoped repair session (attempt {n}; it may write {scope} and nothing else)")
    return flight


def start_repair_session(ctx: Ctx, ex, running: dict, flight: dict, rec: dict, problems: list,
                         cmd: list, timeout: int) -> bool:
    """Submit a prepared repair session to the round's executor (production stages)."""
    prepared = prepare_repair_session(ctx, rec, problems)
    if prepared is None:
        return False
    fut = ex.submit(_execute_attempt_in, ctx.sandbox_of(rec), rec, cmd,
                    min(int(timeout or REPAIR_TIMEOUT_MAX), REPAIR_TIMEOUT_MAX),
                    REPAIR_PROMPT_FILE, "_agent.log", False)
    running[fut] = rec["id"]
    flight[fut] = prepared
    ctx.save_state()
    return True


def run_repair_session_now(ctx: Ctx, rec: dict, problems: list, cmd: list, timeout: int) -> bool:
    """Run a repair session synchronously (the round-based `run_phase` driver).

    Returns True when the repair ran (whatever its outcome); the caller then looks
    at `rec["status"]` exactly as it would after any other attempt.
    """
    prepared = prepare_repair_session(ctx, rec, problems)
    if prepared is None:
        return False
    ctx.save_state()
    res = _execute_attempt_in(ctx.sandbox_of(rec), rec, cmd,
                              min(int(timeout or REPAIR_TIMEOUT_MAX), REPAIR_TIMEOUT_MAX),
                              REPAIR_PROMPT_FILE, "_agent.log", False)
    finish_repair_session(ctx, rec, prepared, res)
    return True


# --- the CONTINUATION of a stopped session ---------------------------------
def prepare_resume_session(ctx: Ctx, rec: dict, argv: list, key: str, reason: str):
    """Write the continuation prompt, charge the resume budget, record it.

    A continuation runs in the SAME sandbox as the attempt it continues (the CLI
    resumes the recorded working directory, so the sandbox must not have been
    archived yet) and is a normal attempt afterwards: the identical postcheck
    decides. Returns the flight dict, or None when it cannot run.
    """
    sb = ctx.sandbox_of(rec)
    if not sb.is_dir():
        return None
    if rec.get("kind") == "revise":
        # The continuation edits the same package: the chain record describes
        # the bytes before it, so the chain must run again after acceptance.
        rec.pop("revision_audit", None)
        rec.pop("revision_repair", None)
        rec.pop("revision_chain", None)
    used = int((rec.get("resume_attempts") or {}).get(key) or 0)
    problems = list((rec.get("postcheck") or {}).get("errors") or [])
    write_text_atomic(sb / RESUME_PROMPT_FILE, resume_prompt(rec, problems, reason, used))
    # Charge the budget NOW: a continuation that dies half-way must not be
    # restarted forever by a later invocation.
    rec["resume_attempts"] = dict(rec.get("resume_attempts") or {}, **{key: used + 1})
    rec["last_resume"] = {"session": key, "attempt": used + 1, "reason": reason,
                          "started": utcnow(), "prompt": RESUME_PROMPT_FILE,
                          # The marker belongs to the TRUNCATED case only: the
                          # old `[*argv[:3], "..."][:3]` dropped it exactly when
                          # the command was longer than three words (so the
                          # record looked complete) and added it to short ones.
                          "argv": ([*argv[:3], "..."] if len(argv) > 3 else list(argv))}
    return {"rid": rec["id"], "session": key, "reason": reason, "argv": list(argv),
            "problems": problems, "prompt": RESUME_PROMPT_FILE}


def start_resume_session(ctx: Ctx, ex, running: dict, flight_map: dict, rec: dict,
                         argv: list, key: str, reason: str, timeout: int) -> bool:
    """Submit a PREPARED continuation to the round's executor (the scheduler path)."""
    prepared = prepare_resume_session(ctx, rec, argv, key, reason)
    if prepared is None:
        return False
    print(f"  [resume] {rec['id']}: continuing session {key[:8]} — {reason} "
          f"(continuation {rec['resume_attempts'][key]}/{RESUME_ATTEMPT_LIMIT})")
    fut = ex.submit(_execute_attempt_in, ctx.sandbox_of(rec), rec, prepared["argv"],
                    min(int(timeout or RESUME_TIMEOUT_MAX), RESUME_TIMEOUT_MAX),
                    RESUME_PROMPT_FILE, "_agent.log", True)
    running[fut] = rec["id"]
    flight_map[fut] = prepared
    ctx.save_state()
    return True


def run_resume_session_now(ctx: Ctx, rec: dict, argv: list, key: str, reason: str,
                           timeout: int) -> bool:
    """Run a continuation synchronously (the `run_phase` driver)."""
    prepared = prepare_resume_session(ctx, rec, argv, key, reason)
    if prepared is None:
        return False
    print(f"  [resume] {rec['id']}: continuing session {key[:8]} — {reason} "
          f"(continuation {rec['resume_attempts'][key]}/{RESUME_ATTEMPT_LIMIT})")
    ctx.save_state()
    res = _execute_attempt_in(ctx.sandbox_of(rec), rec, prepared["argv"],
                              min(int(timeout or RESUME_TIMEOUT_MAX), RESUME_TIMEOUT_MAX),
                              RESUME_PROMPT_FILE, "_agent.log", True)
    finish_resume_session(ctx, rec, prepared, res)
    return True


def finish_resume_session(ctx: Ctx, rec: dict, flight: dict, res: dict) -> dict:
    """Judge a continuation with the SAME postcheck and record the attempt."""
    sb = ctx.sandbox_of(rec)
    bump_attempt(rec)
    rec["last_duration"] = round(res.get("dur") or 0.0, 1)
    sid = capture_agent_session_id(ctx, rec)
    if sid:
        rec["agent_session_id"] = sid
    (sb / RESUME_PROMPT_FILE).unlink(missing_ok=True)
    if res.get("error") or res.get("rc") not in (0,):
        rec["status"] = "failed"
        rec["last_error"] = (res.get("error") or f"agent exited rc={res.get('rc')}")[:600]
        rec["last_failure_kind"] = str(res.get("failure_kind") or "")
        record_attempt(ctx, rec, False, [rec["last_error"]], [],
                       source="continuation (process failed)")
        print_failure(rec["id"], [rec["last_error"]],
                      note=f"after continuation {flight['session'][:8]}")
    else:
        rec["last_failure_kind"] = ""
        postcheck(ctx, rec, source="continuation")
        if rec["status"] == "done":
            print(f"  [ok]   {rec['id']}: the CONTINUATION finished the stage "
                  f"({fmt_dur(res.get('dur'))})")
        else:
            print_failure(rec["id"], (rec.get("postcheck") or {}).get("errors", []),
                          note="after the continuation")
    rec["last_resume"].update({"finished": utcnow(), "ok": rec["status"] == "done",
                               "duration": round(res.get("dur") or 0.0, 1)})
    ctx.log("continuation", rec["id"],
            f"continuation {rec['resume_attempts'][flight['session']]}/"
            f"{RESUME_ATTEMPT_LIMIT}: {'ok' if rec['status'] == 'done' else 'failed'}")
    ctx.save_state()
    return rec


def finish_repair_session(ctx: Ctx, rec: dict, flight: dict, res: dict) -> dict:
    """Verify one repair session's scope, re-postcheck the sandbox, record it.

    A session that edited anything outside its stage's bookkeeping scope, or that
    rewrote pinned evidence (a decision-table row, an auditor's drop, a judge's
    ledger), is rejected on the spot: its postcheck is never consulted, because a
    record "fixed" by deleting the rows it had to account for is exactly the
    failure the repair mode must not launder.
    """
    sb = ctx.sandbox_of(rec)
    bump_attempt(rec)
    record = {"attempt": attempt_number(rec), "problems": list(flight["problems"]),
              "started": rec.get("last_attempt_started"), "finished": utcnow(),
              "duration": round(res.get("dur") or 0.0, 1), "prompt": REPAIR_PROMPT_FILE,
              "transcript": flight["log"]}
    problems = repair_guard_problems(sb, flight["guard"], rec)
    record["out_of_scope"] = problems
    changed = sorted(rel for rel in (guard_changed_paths(sb, flight["guard"])))
    record["changed"] = changed
    (sb / REPAIR_PROMPT_FILE).unlink(missing_ok=True)
    if res.get("error") or res.get("rc") not in (0,):
        record["ok"] = False
        record["error"] = res.get("error") or f"repair session exited rc={res.get('rc')}"
        record_attempt(ctx, rec, False, [record["error"]], [],
                       source="artifact-repair (process failed)")
    elif problems:
        record["ok"] = False
        record["error"] = ("the repair session went outside its scope: "
                           + "; ".join(problems))
        record_attempt(ctx, rec, False, [record["error"]], [],
                       source="artifact-repair (out of scope)")
    else:
        postcheck(ctx, rec, source="artifact-repair")
        record["ok"] = rec["status"] == "done"
        record["postcheck_errors"] = list((rec.get("postcheck") or {}).get("errors") or [])
    rec.setdefault("repairs", []).append(record)
    rec["artifact_repair"] = {"attempt": record["attempt"], "problems": record["problems"],
                              "status": "done" if record["ok"] else "failed",
                              "started": record["started"], "finished": record["finished"],
                              "changed": record["changed"], "transcript": record["transcript"],
                              "prompt": REPAIR_PROMPT_FILE}
    ctx.log("artifact-repair", rec["id"],
            f"attempt {record['attempt']}: {'ok' if record['ok'] else 'failed'}"
            + (f" ({len(problems)} out-of-scope change(s))" if problems else ""))
    ctx.save_state()
    if record["ok"]:
        print(f"  [repair] {rec['id']}: the scoped repair cleared every problem "
              f"({', '.join(record['changed']) or 'no artifact changed'}) -- the attempt is "
              f"recorded as repaired, not as a fresh review")
    else:
        print_failure(rec["id"], [record["error"]] if record.get("error")
                      else record["postcheck_errors"],
                      note=f"after the scoped repair (attempt {record['attempt']})")
    return record


def guard_changed_paths(sb: Path, guard: dict) -> list:
    """The artifact files the repair actually rewrote (its diff, for the record)."""
    before = dict(guard.get("files") or {})
    changed = []
    for rel, digest in sorted((guard.get("artifacts") or {}).items()):
        path = sb / GUIDED_REVIEW_DIR / rel
        if not path.is_file():
            changed.append(f"{REL_ARTIFACT_PREFIX}{rel} (deleted)")
            continue
        try:
            if sha256_file(path) != digest:
                changed.append(f"{REL_ARTIFACT_PREFIX}{rel}")
        except OSError:
            changed.append(f"{REL_ARTIFACT_PREFIX}{rel}")
    for rel, digest in sorted(before.items()):
        path = sb / rel
        try:
            if path.is_file() and sha256_file(path) != digest:
                changed.append(rel)
        except OSError:
            continue
    return changed

def _lookup_answers(sb: Path) -> dict:
    """{kind: [lookup row]} for lookups with a conclusive verdict."""
    answers = {}
    for rel in ("work/PLACEHOLDER_LOOKUP.md", f"{GUIDED_REVIEW_DIR}/work/PLACEHOLDER_LOOKUP.md"):
        for row in parse_markdown_table(sb / rel):
            verdict = str(row.get("verdict") or "").strip().lower()
            if verdict not in ("found", "absent"):
                continue
            key = str(row.get("kind") or "").strip().lower()
            answers.setdefault(key, []).append(dict(row, verdict=verdict))
    return answers


def placeholder_residual_report(ctx: Ctx, sb: Path, sources: list, label: str,
                                enforce: bool, errs: list, warns: list) -> dict:
    """Searchable hand-off markers that the orchestrator could already answer."""
    mod = _format_module()
    if mod is None:
        # The same categorical gap as a raising scanner: without the OOXML
        # engine the .docx marker state cannot be read, so the package is not
        # "clean", it is UNKNOWN. The report keeps the shape its callers update.
        msg = "the OOXML engine is unavailable, so .docx marker content cannot be read"
        (errs if enforce else warns).append(
            f"{label}: the hand-off-marker scan did not run ({msg}); the package's marker "
            f"state is UNKNOWN, not clean")
        return {"searchable_placeholders": 0, "answerable_placeholders": 0,
                "answered_kinds": [], "handoff_markers": 0,
                "handoff_marker_files": [], "handoff_marker_unparsed": [],
                "handoff_marker_scan_error": msg}
    docs = corpus_text_documents(sources)
    searchable = []
    for name, rows in docs:
        for r in mod.placeholder_ledger([x[0] for x in rows]):
            searchable.append(dict(r, document=name))
    answers = _lookup_answers(sb)
    answerable = [r for r in searchable
                  if answers.get(str(r.get("kind") or "").strip().lower())]
    # EVERY marker in the delivered package, searchable or not: the count is a
    # diagnostic under `author_to_complete: document` (the marker is the
    # author's own checklist) and the shipped-marker gate under `readme`/`off`.
    # The scan is the same
    # `scan_placeholders_in_sources` the evidence pack uses, so the two numbers
    # can never disagree.
    all_markers = {}
    scan_error = ""
    try:
        all_markers = scan_placeholders_in_sources(sources)
    except Exception as e:                                            # noqa: BLE001
        # A scanner failure is a CATEGORICAL GAP, not a clean package: the gate
        # used to turn an unreadable package / scanner bug into "0 markers" and
        # report no error, so the stage passed with its marker state unknown.
        scan_error = f"{type(e).__name__}: {e}"
        all_markers = {}
    _atc = author_to_complete_mode_of(ctx)
    unparsed_markers = list(all_markers.get("unparsed") or [])
    # A PDF/PPT is an accepted submission RENDERING the pipeline does not edit:
    # it is reported as unparsed, but it must not fail a normal package that
    # ships one (the repository accepts PDF reporting summaries/figures). An
    # editable document the scan could not read IS a gating unknown.
    _marker_doc_exts = (".doc", ".docx", ".rtf")
    unparsed_docs = [rel for rel in unparsed_markers
                     if Path(rel).suffix.lower() in _marker_doc_exts]
    if unparsed_docs and _atc != "document":
        # The scanner RETURNS the files it could not read (a malformed DOCX, an
        # unreadable file) instead of raising. Under `readme`/`off` a marker in
        # one of those files is a defect the gate cannot see, so the count is
        # UNKNOWN -- never "0 markers, clean". Under `document` the marker is
        # legitimate, so this stays a warning below.
        _gap = ("the hand-off-marker scan could not READ "
                + ", ".join(unparsed_docs[:5])
                + (f" (+{len(unparsed_docs) - 5} more)"
                   if len(unparsed_docs) > 5 else "")
                + " (no text extractor for that format, or the file is unreadable)")
        scan_error = f"{scan_error}; {_gap}" if scan_error else _gap
    report = {"searchable_placeholders": len(searchable),
              "answerable_placeholders": len(answerable),
              "answered_kinds": sorted(answers),
              "handoff_markers": int(all_markers.get("count") or 0),
              "handoff_marker_files": list(all_markers.get("files") or []),
              "handoff_marker_unparsed": unparsed_markers,
              "handoff_marker_scan_error": scan_error}
    if scan_error:
        (errs if enforce else warns).append(
            f"{label}: the hand-off-marker scan FAILED ({scan_error}); the package's marker "
            f"state is UNKNOWN, not clean. Fix the unreadable/broken file and re-run the "
            f"stage -- do not ship on the strength of a scan that never ran")
    elif unparsed_markers:
        warns.append(
            f"{label}: {len(unparsed_markers)} document(s) could not be read for hand-off "
            f"markers ({', '.join(unparsed_markers[:5])}); under "
            f"`author_to_complete: {_atc}` a marker in one would be invisible to this scan, "
            f"so the marker count is a LOWER BOUND, not a clean result")
    if report["handoff_markers"] and _atc != "document":
        # `readme` / `off`: the operator's policy is that no document carries a
        # marker, so a package that carries one is not deliverable -- the
        # residual gate blocks it instead of calling the marker a hand-off.
        (errs if enforce else warns).append(
            f"{label}: {report['handoff_markers']} hand-off marker(s) are still in the "
            f"delivered package although this root runs with `author_to_complete: {_atc}`: "
            f"{', '.join(report['handoff_marker_files'][:5])}. "
            f"Supply the missing item (or its verified negative) in the document, or leave it "
            f"out of the document and record it in the package's own "
            f"{handoff_target(_atc)}")
    for r in answerable:
        msg = (f"{label}: a `searchable` hand-off marker is still in the package although the "
               f"orchestrator answered it -- {str(r.get('payload'))[:90]!r} "
               f"(kind={r.get('kind')}; see work/PLACEHOLDER_LOOKUP.md). Write the verified "
               f"fact, or the verified NEGATIVE with its search date "
               f"(\"not posted\" / \"not yet deposited\"), instead of leaving the marker")
        (errs if enforce else warns).append(msg)
    if searchable and not answerable and not answers:
        warns.append(f"{label}: {len(searchable)} searchable hand-off marker(s) and no lookup "
                     f"evidence in the sandbox -- run with `setup --placeholder-lookup online` "
                     f"so the pipeline can answer them")
    return report


def number_provenance_report(sb: Path, sources: list) -> dict:
    """Numbers in the abstract/legends that no shipped table proves (advisory)."""
    mod = _format_module()
    if mod is None:
        return {}
    proved = {}
    for rel in ("work/NUMBERS_LEDGER.md", f"{GUIDED_REVIEW_DIR}/work/NUMBERS_LEDGER.md"):
        for row in parse_markdown_table(sb / rel):
            if str(row.get("source") or "").strip():
                proved[str(row.get("number") or "").strip()] = str(row.get("source"))
    unsourced = []
    for name, rows in corpus_text_documents(sources):
        # A COVER LETTER is not the abstract/legend surface this report is about.
        # `section_kinds` types every letter body paragraph as "front", so the
        # letter was counted here (134 "unsourced" numbers on the neohet package,
        # the first example a letter sentence). A number the letter quotes is
        # the letter's to justify, not the manuscript's ledger.
        if mod.is_cover_letter_doc(Path(name).name):
            continue
        paras = [r[0] for r in rows]
        kinds = mod.section_kinds(paras, [r[2] for r in rows])
        for i, text in enumerate(paras):
            if kinds[i] not in ("abstract", "legend", "front"):
                continue
            for m in mod.NUMBER_RE.finditer(text):
                num = m.group(0)
                if num.replace(",", "") in ("0", "1", "2", "3"):
                    continue
                if num in proved:
                    continue
                unsourced.append({"document": name, "number": num,
                                  "sentence": re.sub(r"\s+", " ", text)[:110]})
    return {"unsourced": len(unsourced), "proved": len(proved),
            "examples": unsourced[:8]}


AUDIT_ID_RE = re.compile(r"^AU-\d+$")

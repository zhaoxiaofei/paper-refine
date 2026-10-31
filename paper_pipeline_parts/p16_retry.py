# -*- coding: utf-8 -*-
# Part 16/20 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# RETRY COMMAND
# =====================================================================

def dir_size(path: Path) -> int:
    """Bytes used by a directory tree (0 when it does not exist)."""
    total = 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def cmd_prune(args) -> None:
    """Delete a completed round's SANDBOXES (pins, winners, reports and state stay).

    Every judge session copies the whole field plus the original into its sandbox;
    a three-round run is easily >10 GB. `decide` re-derives a decision from
    state.json (the judge sheets are stored there), so the sandboxes are scratch
    once their round is complete. The per-attempt archives of those rounds
    (`runs/<run>_try<N>_failed/`) go with them -- their RECORDS stay in state.json, so the
    attempt history remains readable -- and this command is dry-run unless
    `--yes` is given.
    """
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    with ctx.lock("prune"):
        _cmd_prune_locked(ctx, args)


def _cmd_prune_locked(ctx: Ctx, args) -> None:
    R = ctx.rounds_count()
    try:
        keep_latest = int(args.keep_latest)
    except (TypeError, ValueError):
        die(f"prune: --keep-latest must be an integer, got {args.keep_latest!r}")
    if keep_latest < 0:
        # A negative value used to be clamped to 0, which means "keep no
        # completed round". A typo (`-1`) therefore deleted EVERY round's
        # sandboxes and attempt archives without warning.
        die(f"prune: --keep-latest must be 0 or greater, got {keep_latest}")
    keep_from = max(1, R - keep_latest + 1)
    # The journal-facing runs (the feedback/concerns ledger, the response
    # letter, and the scoped revision whose published winner they describe) are
    # what a later `run` re-reads to rebuild `journal_submission/`; they are
    # also small. Deleting them left a completed transfer/resubmit/scoped root
    # that `run` could never finalize again. `decide` needs only state.json.
    keep_ids = set()
    for r in range(1, R + 1):
        rrec = ctx.round_get(r) or {}
        if str(rrec.get("status")) != "done":
            continue
        for rid in (rid_feedback(r), rid_concerns(r), rid_response(r)):
            if ctx.run(rid) is not None:
                keep_ids.add(rid)
        if rrec.get("scoped") and rrec.get("journal_mode"):
            keep_ids.add(rid_for_fresh(r, revise_vid(1)))
    targets, skipped_open, archives = [], [], []
    for rec in ctx.runs():
        r = int(rec.get("round") or 0)
        if r >= keep_from:
            continue
        if not round_is_done(ctx, r):
            skipped_open.append(rec["id"])
            continue
        if rec["id"] in keep_ids:
            continue
        sb = ctx.sandbox_of(rec)
        if sb.is_dir():
            targets.append((rec["id"], r, sb, dir_size(sb)))
        # The renamed failed sandboxes of the same rounds are scratch too -- the
        # attempt RECORDS stay in state.json, so `status` keeps the history.
        for arch in sorted(ctx.runs_dir.glob(f"{rec['id']}_try*_failed")):
            if arch.is_dir():
                archives.append((rec["id"], r, arch, dir_size(arch)))
    total = sum(t[3] for t in targets) + sum(t[3] for t in archives)
    print(f"[prune] root: {ctx.root}")
    print(f"[prune] keeping sandboxes of the last {args.keep_latest} round(s) "
          f"(rounds {keep_from}..{R}); pins, published winners, reports, state.json, the "
          f"redlines/ and tracking/ copies and the persistent pdfs/ tree are never touched")
    if keep_ids:
        print(f"[prune] {len(keep_ids)} journal-stage sandbox(es) are kept: a completed root "
              f"re-reads them to rebuild journal_submission/")
    if skipped_open:
        print(f"[prune] {len(skipped_open)} run(s) belong to rounds that are not complete and "
              f"are never pruned: {', '.join(skipped_open[:6])}"
              + ("..." if len(skipped_open) > 6 else ""))
    if not targets and not archives:
        print("[prune] nothing to prune.")
        return
    print(f"[prune] {len(targets)} sandbox(es) + {len(archives)} attempt archive(s), "
          f"{total / 1e9:.2f} GB:")
    for rid, r, sb, size in sorted(targets, key=lambda t: nat_key(t[0]))[:40]:
        print(f"  round {r}  {rid:<26} {size / 1e6:8.1f} MB  {sb}")
    if len(targets) > 40:
        print(f"  ... and {len(targets) - 40} more")
    for rid, r, arch, size in sorted(archives, key=lambda t: nat_key(t[0]))[:20]:
        print(f"  round {r}  {rid:<26} {size / 1e6:8.1f} MB  {arch}  (failed attempts)")
    if len(archives) > 20:
        print(f"  ... and {len(archives) - 20} more attempt archives")
    if not args.yes:
        print("[prune] DRY RUN: nothing was deleted. Re-run with --yes to reclaim the space "
              "above. (`decide` keeps working: judge sheets live in state.json; the attempt "
              "history stays readable from state.json's attempts_log.)")
        return
    freed = 0
    failed = []
    removed_sandboxes = 0
    for rid, _r, sb, size in targets:
        if rmtree_force(sb, ignore_errors=True):
            freed += size
            removed_sandboxes += 1
            print(f"[prune] removed {sb} ({rid})")
        else:
            failed.append(str(sb))
            print(f"[prune] FAILED to remove {sb} ({rid}); it still exists")
    archive_seen, archive_failed = set(), set()
    for rid, _r, arch, size in archives:
        archive_seen.add(rid)
        if rmtree_force(arch, ignore_errors=True):
            freed += size
            print(f"[prune] removed {arch} ({rid}, attempt archives)")
        else:
            archive_failed.add(rid)
            failed.append(str(arch))
            print(f"[prune] FAILED to remove {arch} ({rid}, attempt archives); it still exists")
    # Only a run whose archives are ALL gone may claim its attempts were pruned.
    pruned_runs = archive_seen - archive_failed
    for rec in ctx.runs():
        if rec.get("id") not in pruned_runs:
            continue
        for entry in rec.get("attempts_log") or []:
            if entry.get("archived"):
                entry["archive_pruned"] = True
    ctx.log("pruned", detail=f"{removed_sandboxes} sandbox(es), {freed / 1e9:.2f} GB")
    ctx.save_state()
    print(f"[prune] reclaimed ~{freed / 1e9:.2f} GB")
    if failed:
        print(f"[prune] {len(failed)} target(s) could NOT be removed; the reclaimed total "
              f"counts only successful deletions", file=sys.stderr)
        sys.exit(1)


# `retry --runs`: the SAME selection grammar as `run --only`.
#
# Targets are reset in the round plan's own dependency order within each round
# (and by ascending round): a target whose upstream is still done is
# re-materialized at reset time, and the rest are left stale for the next
# `run`'s staging loop -- so resetting a downstream BEFORE the upstream it
# consumes would rebuild it from input that is about to be replaced.
RETRY_KIND_RANK = {"a1": 0, "feedback": 1, "concerns": 1, "rewrite": 2,
                    "guided_review": 2,
                   "cold_start_review": 3, "audit": 4, "revise": 5, "response": 6, "integrate": 7,
                   "judge": 8}


def _judge_selection_for_retry(ctx: Ctx, r: int, spec: str):
    """{(version, judge index)} a judge selector names in round `r`; None = every.

    `spec` is an `--only` judge selector (`w2_j1`, `1_judge_i1_j1`, ...) as
    `OnlySpec.judge_spec_for()` renders it. Unlike the run loop's tolerant
    `judge_selection`, a selector that names NO session of this round is a hard
    error here ("" -- no selector at all -- is the only way to say "every
    session"): `retry` must never reset MORE sessions than the operator named,
    and an empty set would otherwise read as "the whole panel".
    """
    spec = str(spec or "").strip()
    if not spec:
        return None
    try:
        triples = parse_judges_enabled(spec, config_rounds(ctx),
                                       lambda rr: judgeable_ids(ctx, rr),
                                       lambda rr: round_judges(ctx, rr))
    except ValueError as e:
        die(f"--runs: {e}")
    picked = {(str(v), int(k)) for rr, v, k in triples if int(rr) == int(r)}
    if not picked:
        where = f"`agents --root {ctx.root}`" if getattr(ctx, "root", None) else "`agents`"
        die(f"--runs: the judge selection {spec!r} names no judge session of round {r} "
            f"(that round judges {', '.join(judgeable_ids(ctx, r)) or 'no version'}); run {where} "
            f"to see the judge sessions that exist")
    return picked


def retry_targets_for_selection(ctx: Ctx, only) -> tuple:
    """(run records, notes) the `--only`-grammar selection names for `retry`.

    One selection, evaluated per round with the SAME predicates the run loop
    uses (`OnlySpec.entry_selected`, `stage_selected`, `judge_spec_for`):

      * a bare round (`1`, `1-2`) or `all` selects every planned session of the
        round, its a1 base and its judge wave;
      * a stage class (`review`, `1:feedback`) selects that stage's sessions;
      * a session token (`r1_w2`, `rewriter1`) selects that one session;
      * a judge item (`1:judge`, `1:judge_w2_j1`, `judge_<token>_j<k>`) selects
        the judge records it names (`resolve_judge_run_ids` has already turned a
        judge RUN ID into its selector when this runs).

    Records that do not exist yet are reported in `notes` -- never invented:
    `retry` resets what exists, it does not start what has not run.
    """
    targets, notes, seen = [], [], set()

    def add(rec) -> None:
        if rec is None or rec.get("id") in seen:
            return
        seen.add(rec.get("id"))
        targets.append(rec)

    for r in range(1, ctx.rounds_count() + 1):
        if not only.covers_round(r):
            continue
        planned = round_run_plan(ctx, r)
        whole_round = (only.all_stages or int(r) in getattr(only, "rounds_in_full", set())
                       or (int(r) in getattr(only, "pairs", {}) and not only.pairs[int(r)]))
        if whole_round:
            # A round in full (`1`, `1-2`, `all`, `2:all`) includes its base, like
            # `run --only 1` materializes it.
            add(ctx.run(rid_a1(r)))
        planned_stages = {plan_stage_of(e) for e in planned}
        for stage in sorted(only.classes_for(r) - planned_stages - {"judge"}):
            # A stage the ROOT's plan does not have (a journal-mode stage on a
            # `continue` root, a stage the round's counts switch off): name it,
            # so an empty selection is never a silent no-op.
            notes.append(f"r{r}: this round plans no {stage!r} stage (nothing to reset for it)")
        for entry in planned:
            if not only.entry_selected(r, entry):
                continue
            rec = ctx.run(entry["id"])
            if rec is None:
                notes.append(f"r{r}: {entry['id']} is selected but has no run record yet "
                             f"(nothing to reset)")
            else:
                add(rec)
        # The judge wave is not a plan entry: it is materialized per session.
        if not only.stage_selected(r, "judge"):
            continue
        spec = only.judge_spec_for(r)
        picked = _judge_selection_for_retry(ctx, r, spec)
        found = 0
        for rec in ctx.runs(kind="judge", round_no=r):
            if picked and (str(rec.get("target_id")),
                           int(rec.get("judge_index") or 0)) not in picked:
                continue
            add(rec)
            found += 1
        if not found:
            notes.append(f"r{r}: the judge selection {spec or '(the whole configured panel)'} "
                         f"matches no judge run of this root (nothing to reset)")
    targets.sort(key=lambda rec: (int(rec.get("round") or 0),
                                  RETRY_KIND_RANK.get(str(rec.get("kind") or ""), 99),
                                  str(rec.get("id") or "")))
    return targets, notes


def cmd_retry(args) -> None:
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    with ctx.lock("retry"):
        _cmd_retry_locked(ctx, args)


def _cmd_retry_locked(ctx: Ctx, args) -> None:
    given = [name for name, on in (("--run", getattr(args, "run", None) is not None),
                                   ("--runs", getattr(args, "runs", None) is not None),
                                   ("--all-failed", bool(getattr(args, "all_failed", False))))
             if on]
    if len(given) > 1:
        die(f"specify ONE of --run <ID>, --runs <SELECTION> or --all-failed (got "
            f"{', '.join(given)})")
    if args.run:
        rec = ctx.run(args.run)
        if rec is None:
            die(f"unknown run id: {args.run}")
        targets = [rec]
    elif getattr(args, "runs", None) is not None:
        # `--runs` takes the SAME selection grammar as `run --only` (rounds,
        # stages, ROUND:STAGE, single sessions, judge selectors and judge run
        # ids), so the operator can reset exactly the part of the pipeline an
        # equivalent `run --only` invocation would have driven.
        only = parse_only_spec(args.runs, flag="--runs")
        if only is None or not only:
            die("--runs: the selection names nothing; pass rounds, stages or sessions "
                "(e.g. `--runs 1:review,1:feedback`; the grammar is the one documented for "
                "`run --only`)")
        only.validate(ctx.rounds_count(), flag="--runs")
        resolve_judge_run_ids(ctx, only, label="[retry]", flag="--runs")
        validate_only_selectors(ctx, only, flag="--runs")
        targets, notes = retry_targets_for_selection(ctx, only)
        print(f"[retry] selection: {only.label()} -- {only.describe()}")
        _ids = [str(rec["id"]) for rec in targets]
        print(f"[retry] runs ({len(_ids)}): " + ", ".join(_ids[:12])
              + (f" ... (+{len(_ids) - 12} more)" if len(_ids) > 12 else ""))
        for note in notes:
            print(f"[retry] note: {note}")
        if not targets:
            print(f"[retry] --runs {only.label()!r} selects no existing run of this root "
                  f"(nothing was reset).")
            return
    elif args.all_failed:
        targets = [r for r in ctx.runs() if r["status"] in ("failed", "stale")]
        if not targets:
            print("No failed or stale runs to reset.")
            return
    else:
        die("specify --run <ID>, --runs <SELECTION> or --all-failed")

    # 1. Invalidate first and PERSIST it, before anything can fail. Invalidating
    #    a completed round archives its published winner and drops its pins; if
    #    the process died before save_state() the on-disk filesystem and
    #    state.json would disagree, which `run` then reports as a broken chain.
    seen_rounds = set()
    for rec in targets:
        if round_is_done(ctx, rec["round"]) and rec["round"] not in seen_rounds:
            seen_rounds.add(rec["round"])
            touched = invalidate_from_round(ctx, rec["round"],
                                            f"operator reset {rec['id']}")
            print(f"[retry] round {rec['round']} and every later round were invalidated "
                  f"({len(touched)} run(s) marked stale); pinned directories stay on disk but are "
                  f"dropped from state so the chain is rebuilt.")
    ctx.save_state()

    # 2. Reset the bookkeeping of every target. A target whose sandbox needs its
    #    upstream output (revise/integrate/judge) is only REMATERIALIZED here when
    #    that upstream is still done; otherwise it stays stale and the staging
    #    loop rebuilds it, in dependency order, as soon as its upstream re-runs.
    for rec in targets:
        reset_run_record(rec)
        blocked = unmet_deps(ctx, rec)
        if blocked:
            rec["status"] = "stale"
            rec["stale_reason"] = f"operator reset {rec['id']}"
            ctx.log("retry-reset-pending", rec["id"])
            print(f"[retry] {rec['id']}: reset; sandbox left for the staging loop "
                  f"(upstream not done yet: {', '.join(blocked)})")
            continue
        try:
            rebuild_sandbox(ctx, rec)
        except DepsNotMet as e:            # defensive: same condition, race-free
            rec["status"] = "stale"
            rec["stale_reason"] = f"operator reset {rec['id']}"
            print(f"[retry] {rec['id']}: reset; sandbox left for the staging loop ({e})")
            ctx.save_state()
            continue
        if rec.get("kind") != "a1":
            rec["status"] = "pending"       # a1 is done by materialization itself
        ctx.log("retry-reset", rec["id"])
        print(f"[retry] reset {rec['id']} (sandbox rebuilt from current upstream content)")
        ctx.save_state()
    print(f"[retry] next: python {Path(sys.argv[0]).name} run --root {ctx.root}")

# -*- coding: utf-8 -*-
# Part 09/20 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# SETUP
# =====================================================================

def cmd_setup(args) -> None:
    rounds = int(args.rounds)
    # The venue is resolved BEFORE anything is created, so an unknown venue id
    # fails without leaving a half-built root behind. `--caption-limit` is
    # optional here: without it the venue profile's own default applies (0 for
    # a venue that publishes no legend number), and the resolved value is what
    # the config records.
    venue_arg = str(getattr(args, "venue", None) or "").strip()
    venue_profile_file = str(getattr(args, "venue_profile", None) or "").strip()
    journal_arg = str(getattr(args, "journal", None) or "").strip()
    article_arg = str(getattr(args, "article_type", None) or "").strip().lower()
    strict_venue = bool(getattr(args, "strict_venue", False))
    if venue_profile_file:
        # A brand-new venue on a FRESH root: setup had no way to accept a
        # profile file, while `set-venue --profile` needs an existing root --
        # the operator was told to do something impossible. Now `setup` loads
        # and installs the file into the new root itself.
        pf = Path(venue_profile_file)
        if not pf.is_file():
            die(f"--venue-profile {venue_profile_file!r} is not a readable file", code=2)
        try:
            _pdata = json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            die(f"--venue-profile {venue_profile_file!r} is not readable JSON: {e}", code=2)
        try:
            venue_profile = VenueProfile(_pdata, origin="profile file", path=pf)
        except VenueProfileError as e:
            die(f"--venue-profile {venue_profile_file!r} is not a valid venue profile: {e}",
                code=2)
        if venue_arg and venue_arg.lower() != venue_profile.id.lower():
            die(f"--venue {venue_arg!r} does not match the id {venue_profile.id!r} declared by "
                f"--venue-profile {venue_profile_file!r} (drop one of the two, or fix the id)",
                code=2)
        venue_arg = venue_profile.id
    else:
        try:
            venue_profile = load_venue_profile(venue_arg or DEFAULT_VENUE)
        except VenueProfileError as e:
            if e.unknown:
                die(unknown_venue_message(venue_arg or DEFAULT_VENUE), code=2)
            die(str(e), code=2)
    if article_arg:
        try:
            venue_profile = venue_profile.with_article_type(article_arg)
        except VenueProfileError:
            die(f"unknown article type {article_arg!r} for venue {venue_profile.id!r} "
                f"(available: {', '.join(venue_profile.article_type_ids())}). "
                f"`set-venue --list` shows the venues; `set-article-type --list` the types "
                f"of an existing root. A profile that does not carry your venue's types can "
                f"be extended with `set-venue <id> --profile FILE`.", code=2)
    article_type_source = "operator" if article_arg else "profile-default"
    journal = journal_arg or venue_profile.default_journal
    journal_source = ("operator" if journal_arg
                      else ("profile-default" if venue_profile.default_journal else "unset"))
    caption_limit_source = ("operator" if getattr(args, "caption_limit", None) is not None
                            else "profile-default")
    if not journal:
        note = ("no journal configured: the prompts will say \"the target journal\" and the "
                f"venue's rule set ({venue_profile.id}) applies. Run "
                f"`set-journal <name>` at any time before or during a run to name it.")
        if strict_venue:
            die("--strict-venue: " + note)
        print(f"[setup] venue note: {note}")
    elif not venue_profile.journal_matches(journal):
        note = (f"the journal {journal!r} is not one of the journals venue profile "
                f"{venue_profile.id!r} describes ({', '.join(venue_profile.known_journals())}); "
                f"the venue's rules still apply. Use `set-venue <id>` for another rule set or "
                f"`set-journal <name>` to change the journal.")
        if strict_venue:
            die("--strict-venue: " + note)
        print(f"[setup] venue warning: {note}")
    caption_limit = int(getattr(args, "caption_limit", None)
                        if getattr(args, "caption_limit", None) is not None
                        else venue_profile.caption_default)
    format_policy = {}
    if getattr(args, "format_policy", None):
        try:
            format_policy = json.loads(Path(args.format_policy).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            die(f"--format-policy {args.format_policy!r} is not readable JSON: {e}", code=2)
        if not isinstance(format_policy, dict):
            die("--format-policy must be a JSON object of overrides, "
                f"e.g. {{\"url_style\": \"plain\"}} (got {type(format_policy).__name__})", code=2)
    format_fix = str(getattr(args, "format_fix", DEFAULT_FORMAT_FIX) or
                     DEFAULT_FORMAT_FIX).strip().lower()
    # `--strict-artifacts [on|fix|off]` (absent = the default policy). The config
    # carries the three-valued `artifact_policy` only; the boolean compatibility
    # keys are not written or read.
    artifact_policy = str(getattr(args, "artifact_policy", None) or DEFAULT_ARTIFACT_POLICY)
    if artifact_policy not in ARTIFACT_POLICIES:
        die(f"unknown --strict-artifacts value: {artifact_policy!r} "
            f"(choose one of {', '.join(ARTIFACT_POLICIES)})", code=2)
    if format_fix not in FORMAT_FIX_MODES:
        die(f"--format-fix must be one of {', '.join(FORMAT_FIX_MODES)} (got {format_fix!r})",
            code=2)
    zotero = str(getattr(args, "zotero", DEFAULT_ZOTERO_MODE) or DEFAULT_ZOTERO_MODE).strip().lower()
    if rounds < 1:
        # A post-parse USAGE error, like the argparse errors: the README's exit
        # table says code 2 (F62).
        die("--rounds must be >= 1", code=2)
    # ---- --round-indices: run a SUBSET of the built-in round schedule -------
    # `--round-indices 2 3` runs two rounds whose per-round plan follows the
    # built-in schedule's entries 2 and 3 (no rewrites); the pipeline's own
    # round numbers stay 1..K. `--round-indices -1` / `3` runs only the final
    # schedule round (no rewrites, no integrations).
    round_indices = (normalize_round_indices(getattr(args, "round_indices", None))
                     if getattr(args, "round_indices", None) else [])
    if round_indices:
        for flag, attr in (("--rewrites", "rewrites"), ("--revises", "revises"),
                           ("--integrators", "integrators"),
                           ("--review-scope", "review_scope")):
            if getattr(args, attr.replace("-", "_"), None) is not None:
                die(f"--round-indices selects the per-round {flag[2:]} values from the built-in "
                    f"round schedule; do not pass {flag} with it (pass --judges for the panel "
                    f"size if you need to)", code=2)
        if int(args.rounds) != len(round_indices):
            print(f"[setup] note: --round-indices implies --rounds {len(round_indices)} "
                  f"(was --rounds {args.rounds}); using {len(round_indices)}")
        rounds = len(round_indices)
    judges_list = parse_round_counts(getattr(args, "judges", None) or DEFAULTS["judges"],
                                     rounds, "--judges")
    if any(j < 1 for j in judges_list):
        die(f"--judges must be >= 1 per round, got {judges_list}", code=2)
    integrators = ([ROUND_SCHEDULE[i - 1]["integrators"] for i in round_indices]
                   if round_indices else
                   parse_round_masks(getattr(args, "integrators", None) or
                                     DEFAULTS["integrators"], rounds, "--integrators"))
    if caption_limit < 0:
        die("--caption-limit must be >= 0 (0 = no caption suggestion at all, the default)",
            code=2)
    _floor_arg = getattr(args, "tiebreak_defect_floor", None)
    tiebreak_floor = int(_floor_arg if _floor_arg is not None
                         else DEFAULT_TIEBREAK_DEFECT_FLOOR)
    if tiebreak_floor < 0:
        die("--tiebreak-defect-floor must be >= 0 (it is the number of defects the cleanest "
            "ranked version must reach before the adaptive severity_tier_category prefix stops; "
            "default 10)", code=2)
    _stop_k = int(getattr(args, "stop_after_no_progress", 0) or 0)
    if _stop_k < 0:
        # `streak >= K` is true for every streak when K is negative, so a
        # negative value silently stopped the run after round 1 (F26).
        die("--stop-after-no-progress must be >= 0 (0 = off), got "
            f"{_stop_k}", code=2)
    dedup_mode = str(getattr(args, "dedup_mode", None) or "off").strip().lower()
    if dedup_mode not in DEDUP_MODES:
        die(f"--dedup-mode must be one of {', '.join(DEDUP_MODES)} (got {dedup_mode!r}); "
            f"the default 'off' performs no cross-sheet merging", code=2)
    if zotero not in ZOTERO_MODES:
        die(f"--zotero must be one of {', '.join(ZOTERO_MODES)} (got {zotero!r})", code=2)
    rewrites = ([ROUND_SCHEDULE[i - 1]["rewrites"] for i in round_indices]
                if round_indices else
                parse_round_counts(getattr(args, "rewrites", None) or DEFAULTS["rewrites"],
                                   rounds, "--rewrites"))
    revises = ([ROUND_SCHEDULE[i - 1]["revises"] for i in round_indices]
               if round_indices else
               parse_round_counts(getattr(args, "revises", None) or DEFAULTS["revises"],
                                  rounds, "--revises"))
    # ---- revision modes (init, options 1-4, continue) -----------------------
    # "continue" (the default) leaves every value below exactly as the operator
    # passed it: the historical workflow is unchanged.
    explicit_mode = str(getattr(args, "revision_mode", None) or "").strip()
    src_path = Path(args.source).resolve() if getattr(args, "source", None) else None
    if not explicit_mode and src_path and src_path.is_dir() \
            and llm_feedback_present_in(src_path):
        print(f"[setup] note: --source carries {LLM_FEEDBACK_DIR}/, but no journal mode is "
              f"selected; the historical guided-review/revise path will run. Pass "
              f"`--revision-mode {JOURNAL_MODE_LLM}` to use that feedback.")
    raw_revision_mode = (explicit_mode or JOURNAL_MODE_CONTINUE).strip().lower()
    revision_mode = normalize_revision_mode(raw_revision_mode)
    if revision_mode not in JOURNAL_MODES:
        die(f"--revision-mode must be one of {', '.join(JOURNAL_MODES)} (got {revision_mode!r}). "
            f"continue=the historical workflow (the pipeline's own guided-review/revise rounds), "
            f"init=author the submission in the venue's own "
            f"Word template first (the conform stage) then run the pipeline's own rounds with "
            f"no journal feedback, 1=transfer (new journal, no response letter), 2=resubmit "
            f"(same journal, letter), 3=major revision (scoped edits, letter), 4=minor "
            f"revision (scoped edits, letter), 5=llm (the false-positive-filtered "
            f"{LLM_FEEDBACK_DIR}/ review only; no journal letter, no response letter).", code=2)
    # A scoped (major/minor) mode overrides three operator policies. Remember
    # what the operator actually chose so `set-revision-mode` can restore it
    # when the root leaves the scoped mode instead of silently turning the
    # revision audit (and the probe) back on.
    scoped_mode_restore = None
    journal_feedback = [str(x) for x in (getattr(args, "journal_feedback", None) or [])
                        if str(x).strip()]
    journal_feedback_from = str(getattr(args, "journal_feedback_from", None) or "").strip()
    if revision_mode == JOURNAL_MODE_LLM and (journal_feedback or journal_feedback_from):
        print(f"[setup] note: revision mode {JOURNAL_MODE_LLM!r} reads ONLY "
              f"{LLM_FEEDBACK_DIR}/; --journal-feedback/--journal-feedback-from are ignored")
    if (journal_feedback or journal_feedback_from) \
            and not JOURNAL_MODES[revision_mode]["feedback"]:
        print(f"[setup] note: revision mode {revision_mode!r} reads no journal feedback; "
              f"--journal-feedback/--journal-feedback-from are ignored")
    if revision_mode != JOURNAL_MODE_CONTINUE:
        info = JOURNAL_MODES[revision_mode]
        if info["scoped"]:
            # The plan the operator passed, saved BEFORE the scoped mode
            # normalizes it: leaving the mode must restore the custom plan, not
            # the built-in defaults (F21).
            # The operator's review_scope list is saved here, BEFORE the mode
            # truncates it to its single round. Capturing it after the
            # truncation restored only ['full'] instead of the requested
            # three-round scope (F21).
            _saved_scope = getattr(args, "review_scope", None) or DEFAULTS["review_scope"]
            if not isinstance(_saved_scope, (list, tuple)):
                _saved_scope = [x.strip() for x in str(_saved_scope).split(",") if x.strip()]
            _saved_scope = [str(x).strip().lower() for x in _saved_scope if str(x).strip()]
            _saved_plan = {
                "rounds": rounds,
                "rewrites": list(rewrites),
                "revises": list(revises),
                "integrators": list(integrators),
                "round_indices": list(round_indices) if round_indices else None,
                "review_scope": _saved_scope or ["full"],
            }
            if round_indices:
                die(f"--round-indices selects the pipeline's round schedule, but revision mode "
                    f"{revision_mode!r} forces its own single concern-scoped round; drop one of "
                    f"the two", code=2)
            # Major/minor revisions are concern-scoped by definition: no
            # rewrites, ONE revision arm, no integration and ONE round. The
            # values are normalised (not refused) and the normalisation is
            # printed, so an operator who passed the defaults learns exactly
            # what the mode changed.
            forced = []
            # `rounds` first: the per-round lists must be normalised to the
            # plan's FINAL length, or the config would say `rounds: 1` while
            # `rewrites`/`revises`/`integrators` still carry the three entries
            # the default `--rounds 3` expanded to (and `set-revision-mode`
            # would write the same mode as length-1 lists).
            if rounds != 1:
                rounds = 1
                forced.append("rounds=1 (the concerns are addressed once)")
            if rewrites != [0] * rounds:
                rewrites = [0] * rounds
                forced.append("rewrites=0 (a major/minor revision may not rewrite the manuscript)")
            if revises != [1] * rounds:
                revises = [1] * rounds
                forced.append("revises=1 (concern-scoped edits are one deterministic pass)")
            if integrators != [0] * rounds:
                integrators = [0] * rounds
                forced.append("integrators=0 (nothing to integrate without rewrite arms)")
            scoped_mode_restore = {
                "audit": str(getattr(args, "audit", DEFAULT_AUDIT) or DEFAULT_AUDIT),
                "revision_audit": str(getattr(args, "revision_audit", "on") or "on").lower(),
                "cold_start_review": str(getattr(args, "cold_start_review", COLD_START_REVIEW_DEFAULT)
                                    or COLD_START_REVIEW_DEFAULT).lower(),
                **_saved_plan,
            }
            if getattr(args, "audit", DEFAULT_AUDIT) not in (None, "", "off"):
                forced.append("audit off (the guided review's audits do not run in this mode)")
            args.audit = "off"
            # The post-revise chain consumes the guided review's frozen list
            # and may change any file of the package; a concern-scoped revision
            # has neither a general review nor that freedom, so it stays off
            # (the run records the skip if an old root still carries it on).
            if str(getattr(args, "revision_audit", "on") or "on").lower() != "off":
                forced.append("revision audit off (there is no general review to audit against "
                              "and edits stay inside the admitted concerns)")
            args.revision_audit = "off"
            # The scoped review is formatting/writing only: a full discovery
            # probe would freeze X-9xx rows the reviser is asked to resolve,
            # although they are not traceable to a reviewer concern.
            if str(getattr(args, "cold_start_review", COLD_START_REVIEW_DEFAULT)).lower() != "off":
                forced.append("cold-start review off (scoped edits are driven by the concerns)")
            args.cold_start_review = "off"
            print(f"[setup] revision mode {revision_mode} (option {info['option']}): "
                  f"{info['label']}")
            for f in forced:
                print(f"[setup]   forced by the mode: {f}")
        else:
            print(f"[setup] revision mode {revision_mode} (option {info['option']}): "
                  f"{info['label']}; rewrites stay "
                  f"{'allowed' if info['rewrites'] else 'forbidden'}")
    review_scope_raw = getattr(args, "review_scope", None) or DEFAULTS["review_scope"]
    if not isinstance(review_scope_raw, (list, tuple)):
        review_scope_raw = [x.strip() for x in str(review_scope_raw).split(",") if x.strip()]
    review_scope = [str(x).strip().lower() for x in review_scope_raw if str(x).strip()]
    if not review_scope:
        review_scope = ["full"]
    while len(review_scope) < rounds:
        review_scope.append(review_scope[-1])
    review_scope = review_scope[:rounds]
    if round_indices:
        review_scope = [ROUND_SCHEDULE[i - 1]["review_scope"] for i in round_indices]
    if scoped_mode_restore is not None:
        # The plan this mode replaces: save the operator's champion-select and
        # review scope alongside the three audit policies, so leaving the mode
        # restores them instead of silently falling back to the defaults (F09).
        scoped_mode_restore["champion_select"] = str(
            getattr(args, "champion_select", None) or DEFAULT_CHAMPION_SELECT)
        scoped_mode_restore["review_scope"] = list(
            scoped_mode_restore.get("review_scope") or review_scope)
    # THE GUIDED REVIEW'S POLICY (`--no-guided-review`). The flag removes the
    # round's general checklist pass and leaves the COLD-START review alone as the finding
    # source, so the combinations that would leave the round with no source at
    # all are refused HERE, before a root is built:
    #   * a concern-scoped revision already replaces the guided review;
    #   * a split review is two guided-review sessions;
    #   * no probe means literally nothing produces findings;
    #   * a polish round reviews the surface only, and it is a guided review.
    if str(getattr(args, "guided_review", GUIDED_REVIEW_DEFAULT)).lower() == "off":
        if scoped_mode_restore is not None:
            die("--no-guided-review cannot be combined with a concern-scoped revision "
                "mode: that mode replaces the guided review with the concerns ledger, so "
                "the round would have no finding source at all", code=2)
        if str(getattr(args, "review_split", "off") or "off").lower() != "off":
            die("--no-guided-review cannot be combined with --review-split: the split runs "
                "two guided-review sessions and this round runs none", code=2)
        if str(getattr(args, "cold_start_review", COLD_START_REVIEW_DEFAULT)).lower() == "off":
            die("--no-guided-review leaves the cold-start review as the round's only finding "
                "source, but --cold-start-review off disables it too: the round would have no "
                "findings at all (keep the cold-start review on, or drop "
                "--no-guided-review)", code=2)
        if any(s in REVIEW_SCOPE_VALUES and s != "full" for s in review_scope):
            die("--no-guided-review needs a full-scope round: --review-scope selects WHICH "
                f"guided checks run, and no guided review runs here (got {review_scope})",
                code=2)
        if bool(JOURNAL_MODES.get(revision_mode, {}).get("feedback")):
            die("--no-guided-review cannot be combined with a revision mode that consumes an "
                "editors'/reviewers' decision letter: the guided review is the session that "
                "reconciles every concern, so skipping it would leave the letter unanswered",
                code=2)
        if any(int(n) == 0 for n in revises):
            # All review/cold-start entries live inside `if n:` in
            # `round_run_plan`: a round with no revision arm plans no review at
            # all, so the flag's promise ("the cold-start review runs alone")
            # would be false and the round would carry no finding source (F06).
            die("--no-guided-review needs at least one revision arm in every round: with "
                f"--revises {','.join(str(n) for n in revises)} no review session is planned, "
                "so the cold-start review would not run either. Raise --revises, or drop "
                "--no-guided-review", code=2)
    bad_scope = [x for x in review_scope if x not in REVIEW_SCOPE_VALUES]
    if bad_scope:
        die(f"--review-scope entries must be one of {'|'.join(REVIEW_SCOPE_VALUES)}, "
            f"got {bad_scope}", code=2)
    # The integrator mask addresses the pool with one bit per member; a pool that
    # outgrew the 32-bit mask cannot be expressed, and silently dropping the
    # higher members' integrations would change the field without saying so.
    for i, (m, n) in enumerate(zip(rewrites, revises), 1):
        if len(round_pool_ids(m, n)) > INTEGRATOR_BITS:
            die(f"round {i} has {len(round_pool_ids(m, n))} pool member(s) (a1 + M={m} rewrites "
                f"+ N={n} revisions), more than the {INTEGRATOR_BITS} bits of --integrators; "
                f"lower --rewrites/--revises for that round", code=2)
    for i, (m, n) in enumerate(zip(rewrites, revises), 1):
        if m + n < 1:
            die(f"round {i} would have no candidate at all: --rewrites and --revises must not "
                f"both be 0 for a round (round {i}: rewrites={m}, revises={n})", code=2)
    # The no-judge modes promote ONE named version per round; validate the whole
    # plan at setup instead of discovering an impossible round after paying for
    # the earlier sessions.
    _csel = str(getattr(args, "champion_select", None) or DEFAULT_CHAMPION_SELECT)
    if _csel in ("revise", "integrate"):
        if JOURNAL_MODES[revision_mode]["scoped"] and _csel == "integrate":
            die(f"--champion-select integrate has no meaning in revision mode "
                f"{revision_mode!r}: a concern-scoped revision already promotes its single "
                f"revised candidate and runs no integration arm", code=2)
        _explicit_masks = getattr(args, "integrators", None) is not None
        _enabled_arms = []
        for _i, (_m, _n, _mask) in enumerate(
                zip(rewrites, revises, integrators), 1):
            if _n != 1:
                die(f"--champion-select {_csel} needs exactly ONE revise arm in every round, "
                    f"but round {_i} plans N={_n}; use --revises 1", code=2)
            if _csel == "integrate":
                _arm = _m + 2
                if not ((_mask >> (_arm - 1)) & 1):
                    if _explicit_masks:
                        die(f"--champion-select integrate promotes '{integrate_vid(_arm)}' in "
                            f"round {_i} (the integration of a2), but its integrator mask "
                            f"0x{_mask:X} does not plan that arm. Set bit {_arm - 1} "
                            f"(0x{1 << (_arm - 1):X}) for round {_i}", code=2)
                    # No explicit mask: the mode's whole point is that integration
                    # arm, so enable exactly that bit (never a whole-pool
                    # rewrite of the operator's schedule) and say so.
                    _mask |= 1 << (_arm - 1)
                    integrators[_i - 1] = _mask
                    _enabled_arms.append((_i, integrate_vid(_arm), _mask))
        if _enabled_arms:
            print("[setup] champion selection: integrate enables the promoted integration "
                  "arm because --integrators was not given: "
                  + ", ".join(f"round {i} -> {vid} (mask 0x{mask:X})"
                              for i, vid, mask in _enabled_arms))
    source = Path(args.source).resolve()
    if not source.is_dir():
        die(f"--source directory not found: {source}")
    _legacy = legacy_input_area_problems(source)
    if _legacy:
        die("--source uses a removed input-area spelling:\n  - " + "\n  - ".join(_legacy)
            + "\n       Rename the directory once, then run setup again; the pipeline does not "
              "resolve legacy aliases.")
    # Count only what the copy actually carries: `_ignore_symlinks` skips every
    # symlink (except a canonical evidence link), but `p.is_file()` followed the
    # link, so a source made only of symlinked documents passed this check and
    # produced a root with an EMPTY pristine corpus.
    def _copyable(p: Path) -> bool:
        if not p.is_file():
            return False
        if not p.is_symlink():
            return True
        try:
            return is_canonical_evidence_link(p, args.root)
        except (OSError, RuntimeError):
            return False

    files = [p for p in source.rglob("*") if _copyable(p)]
    if not files:
        _links = [str(p) for p in source.rglob("*") if p.is_symlink()]
        if _links:
            die(f"--source contains only symlink(s), which setup never copies: "
                f"{', '.join(_links[:5])}{' ...' if len(_links) > 5 else ''}\n"
                f"       Point --source at the real files (or at the canonical "
                f"<root>/non_revised/<area> evidence links).")
        die(f"--source directory is empty: {source}")
    if JOURNAL_MODES[revision_mode]["feedback"]:
        # The evidence the whole mode rests on must exist BEFORE a root is
        # created: a journal mode with no feedback file would run the scoped
        # stages against nothing.
        if revision_mode != JOURNAL_MODE_LLM:
            _resolved_feedback = []
            for item in journal_feedback:
                q = Path(item)
                if not q.is_absolute():
                    root_rel = Path(args.root).resolve() / q
                    q = root_rel if root_rel.exists() else (Path.cwd() / q)
                if not q.is_file():
                    die(f"--journal-feedback {item!r} does not exist (looked for {q}).")
                _resolved_feedback.append(str(q.resolve()))
            # Store the RESOLVED paths: the later runtime lookup is root-then-cwd,
            # so a relative spelling could silently read a same-named cwd file.
            journal_feedback = _resolved_feedback
        llm_dir = source / LLM_FEEDBACK_DIR
        llm_hits = [p for p in sorted(llm_dir.rglob("*")) if p.is_file()] \
            if llm_dir.is_dir() else []
        if revision_mode == JOURNAL_MODE_LLM:
            if not llm_hits:
                die(f"revision mode {JOURNAL_MODE_LLM!r} needs a NON-EMPTY "
                    f"{LLM_FEEDBACK_DIR}/ area in --source; it is missing or empty. Add the "
                    f"false-positive-filtered LLM review, or pass an explicit "
                    f"--revision-mode continue.")
            print(f"[setup] LLM review feedback:   {len(llm_hits)} file(s) under "
                  f"{LLM_FEEDBACK_DIR}/ (false positives pre-filtered) drive the concern "
                  f"ledger; no journal decision letter is read.")
        elif not journal_feedback:
            hits = [p for p in files
                    if is_journal_feedback_name(p.name)
                    and evidence_area_of(p.relative_to(source).as_posix()) != LLM_FEEDBACK_DIR]
            if hits:
                print(f"[setup] journal feedback auto-detected in --source: "
                      + ", ".join(sorted(p.name for p in hits)[:4])
                      + (" +%d more" % (len(hits) - 4) if len(hits) > 4 else ""))
            elif llm_hits:
                print(f"[setup] journal feedback: no human decision letter was found, but "
                      f"--source carries {LLM_FEEDBACK_DIR}/ with {len(llm_hits)} file(s), "
                      f"already filtered for false positives; the journal stages will use it.")
            else:
                print(f"[setup] WARNING: revision mode {revision_mode!r} needs the editors'/"
                      f"reviewers' feedback, and no feedback-named file was found in --source "
                      f"(looked for feedback/referee/reviewer/editor/decision in the file "
                      f"names). Add it to the corpus (typically raw_data/), or name it with "
                      f"`setup --journal-feedback FILE`; the first `run` will refuse without it.")
    if any(p.is_dir() and p.name == REVISED_DIR for p in source.rglob("*")):
        print("WARNING: --source contains a 'revised' directory already; the source should be the "
              "pristine 'non_revised' corpus. Continuing anyway.")
    root = Path(args.root).resolve()
    marker = root / SETUP_MARKER
    if root.exists() and not root.is_dir():
        # `--root typo.txt` exists and is a FILE: `any(root.iterdir())` raised
        # NotADirectoryError mid-setup instead of the clean refusal every other
        # unusable root gets.
        die(f"--root exists and is a FILE, not a directory: {root} "
            f"(choose a fresh --root or delete it)")
    if root.exists() and any(root.iterdir()):
        # A root this pipeline created and never finished (the marker is written
        # before the first copy and removed only once state.json exists) is
        # disposable: a setup that hit a transient I/O error while hashing or
        # scanning the fresh copy used to leave it behind, and the operator then
        # had to delete it by hand before re-running the same command.
        if marker.is_file() and not (root / "state.json").is_file():
            print(f"[setup] {root} holds an INTERRUPTED setup (see {SETUP_MARKER}, no "
                  f"state.json yet); starting over from the source")
            rmtree_force(root)
        else:
            die(f"--root exists and is not empty: {root} (choose a fresh --root or delete it)")
    if is_within(root, source) or is_within(source, root):
        die("--root and --source must not be nested inside each other")
    # A new root must not freeze an OLD ROOT's pipeline snapshot by accident
    # (2026-10-15) -- checked BEFORE anything is created, so a refused setup
    # leaves the filesystem exactly as it found it. This is structural, not a
    # file marker: the script that is running lives directly inside another
    # pipeline root, so what would be frozen into the new root is THAT root's
    # copy, not the tree the operator maintains. The operator's own report
    # reached us through exactly this path, and the new root then ran two-day-old
    # code for every later command (see `frozen_snapshot_root`). Re-running the
    # same command from the origin tree is the fix; `--pipeline-snapshot-ok`
    # records the deliberate exception.
    _ident = pipeline_identity()
    _snap = frozen_snapshot_root(_ident.get("path"))
    if _snap and not bool(getattr(args, "pipeline_snapshot_ok", False)):
        _origin = _snap.get("origin_path") or ""
        _hint = (f"run THAT file instead:\n    python3 {_origin} setup ..."
                 if _origin and Path(_origin).is_file() else
                 "run the `paper_pipeline.py` of the tree you actually maintain")
        die("this command would freeze another root's PIPELINE SNAPSHOT into the new root:\n"
            f"    running now : {_snap['script']}\n"
            f"    snapshot of : {_snap['root']} (frozen {_snap.get('frozen_at') or 'date unknown'}"
            + (f", frozen from {_origin}" if _origin else "") + ")\n"
            f"    origin code : " + (f"differs ({str(_snap.get('origin_digest'))[:16]}... vs "
                                    f"{str(_snap.get('digest'))[:16]}...)"
                                    if _snap.get("origin_differs") else
                                    "matches the snapshot (or cannot be read)")
            + f"\nEvery later `run` in the new root executes the frozen copy, so fixes committed "
              f"since the snapshot would never run (the 2026-10-15 neohet-12to13 root was set up "
              f"this way and silently re-found defects the origin tree had already closed). "
              f"{_hint}\nPass --pipeline-snapshot-ok only when freezing this exact snapshot is "
              f"what you intend.", code=2)
    _pipeline_state = dict(_ident)
    if _snap and _snap.get("origin_path"):
        _pipeline_state.update(snapshot_of=_snap.get("root"),
                               snapshot_origin=_snap.get("origin_path"))
    try:
        root.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"setup started {utcnow()}\n", encoding="utf-8")
    except OSError as e:
        # The same unusable-root class the FILE check above refuses: a --root
        # whose PARENT is a file (`--root typo.txt/new`) reached mkdir and died
        # in a NotADirectoryError traceback instead of the clean refusal every
        # other bad root gets (and the marker write can fail on a read-only
        # mount). Nothing has been created at this point.
        die(f"cannot create the root directory {root}: {type(e).__name__}: {e}")
    ctx = Ctx(root)
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    # From here on the root exists: keep this invocation's console in it (the
    # run log the operator asked for, next to the reports it produces).
    begin_run_log("setup", root, sys.argv)
    # The pipeline frozen into the root is the one RUNNING now; when the
    # operator deliberately froze another root's snapshot, its provenance
    # travels with it (see the guard above and `root_pipeline_staleness`).
    ctx.state["pipeline"] = dict(_pipeline_state)
    if _snap:
        print(f"[setup] WARNING: freezing a PIPELINE SNAPSHOT from {_snap['root']} "
              f"({_snap.get('frozen_at') or 'date unknown'}) although the origin tree "
              f"{_snap.get('origin_path') or '(unknown)'} differs -- every later `run` in "
              f"this root executes THIS copy, and fixes committed to the origin tree are "
              f"NOT in it.")
    print(f"[setup] pipeline:                {Path(_ident['path']).name} v{_ident['version']} "
          f"sha256 {_ident['sha256'][:16]}... from {Path(_ident['path']).parent}  (THIS copy is "
          f"frozen into the root and is what every later `run` executes)")
    print(f"[setup] copying {len(files)} file(s) from {source} -> {ctx.pristine}")
    _skipped_links = []
    _source_root = Path(source).resolve()

    def _ignore_symlinks(_dir, names):
        out = []
        # A top-level evidence area may legitimately be a link to the canonical
        # `<root>/non_revised/<area>` store; setup materializes that one because
        # the pipeline's own input manifests must see the evidence. A link that
        # is merely NAMED `raw_data` is not evidence: its target may be any local
        # directory or file, so it is skipped like every other link (including
        # links nested inside an evidence area).
        at_source_root = Path(_dir).resolve() == _source_root
        for name in names:
            path = Path(_dir) / name
            if os.path.islink(path):
                canonical = (at_source_root and is_evidence_rel(name)
                             and is_canonical_evidence_link(path, root))
                if not canonical:
                    _skipped_links.append(os.path.join(_dir, name))
                    out.append(name)
        return out

    shutil.copytree(source, ctx.pristine, ignore=_ignore_symlinks)
    _mapped_feedback = []
    for _item in journal_feedback:
        _q = Path(_item)
        try:
            _rel = _q.resolve().relative_to(_source_root)
        except (OSError, ValueError):
            # The letter is outside --source: freeze it into the root instead of
            # storing an absolute path that can change/delete the input later.
            _mapped_feedback.append(_freeze_journal_feedback(root, _q))
        else:
            _mapped_feedback.append((ctx.pristine / _rel).relative_to(root).as_posix())
    journal_feedback = _mapped_feedback
    if _skipped_links:
        print(f"[setup] WARNING: skipped {len(_skipped_links)} symlink(s) in --source "
              f"(a link is not package content and its target may be outside the package): "
              + ", ".join(sorted(_skipped_links)[:5])
              + (" ..." if len(_skipped_links) > 5 else ""))
    _protected = 0
    for _name in evidence_areas_of(ctx.pristine):
        # The root's canonical evidence areas are read-only: sandboxes SYMLINK
        # them (see ensure_pristine_input), so a write through a link fails at
        # the filesystem level instead of corrupting every sandbox's evidence.
        _protected += make_tree_readonly(ctx.pristine / _name)
    if _protected:
        print(f"[setup] read-only evidence: {_protected} entr(y/ies) chmod-protected under "
              f"{ctx.pristine.name}/; stage sandboxes will symlink them instead of copying")
    # Copy the script that is RUNNING, not its basename resolved against the CWD:
    # `setup` is normally launched as `python /path/to/paper_pipeline.py setup
    # --root ...` from whatever directory the operator is in, and the basename
    # then named a file that does not exist there. That failure came AFTER the
    # root had been populated, and `setup` refuses to re-run on a non-empty root,
    # so it left a half-built root to delete by hand.
    script = Path(__file__).resolve()
    shutil.copy(script, root / script.name)
    # The loaders above are thin: their ordered implementation parts must travel
    # with them, or the frozen bundle cannot start. Refuse to create a root that
    # would freeze a loader without its implementation.
    _missing_assets = [name for name in PIPELINE_ASSET_DIRS
                       if not (script.parent / name).is_dir()]
    # The companion MODULES are just as required: the agent commands call
    # `python paper_docx_format.py scan ...`, the redline backend resolves the
    # adapter beside the driver, the `qwen` preset executes its module, and the
    # render/track shims are probed beside the driver. These used to be copied
    # only `if is_file()`, so a trimmed checkout produced a root that looked
    # healthy (exit 0) and then failed every later stage on a missing tool.
    _missing_modules = [name for name in PIPELINE_MODULE_FILES
                        if name != script.name and not (script.parent / name).is_file()]
    if _missing_assets or _missing_modules:
        _missing = [f"{n}/" for n in _missing_assets] + list(_missing_modules)
        die(f"setup: the running tree is missing {', '.join(_missing)} beside "
            f"{script.name}; refusing to freeze a bundle whose stages cannot run. Run setup "
            f"from the maintained checkout (the tree that carries the loaders, their parts "
            f"and the companion modules).")
    _asset_dirs = copy_asset_dirs(script.parent, root)
    if _asset_dirs:
        print(f"[setup] pipeline assets:         copied {', '.join(_asset_dirs)}/ "
              f"(the loaders execute the parts; the skills pack is read beside the driver)")
    # The OOXML formatting scanner is a companion module (see
    # scan_format_in_sources); copy it next to the script so the root stays
    # self-contained and `python <root>/paper_pipeline.py` keeps working.
    _fmt_mod = script.with_name(DOCX_FORMAT_MODULE)
    if _fmt_mod.is_file():
        shutil.copy(_fmt_mod, root / DOCX_FORMAT_MODULE)
    # The redline adapter travels with the root too: the tracking stage's
    # python-redlines backend resolves it NEXT TO THE RUNNING SCRIPT, and a root
    # without it silently skipped that engine (the weaker fallbacks then
    # over-marked a small edit as whole-paragraph rewrites -- exactly what
    # `redline_fidelity` now flags).
    _adapter = script.with_name(REDLINE_ADAPTER_NAME)
    if _adapter.is_file():
        shutil.copy(_adapter, root / REDLINE_ADAPTER_NAME)
    # The Qwen adapter is executed by the `qwen` agent preset, which resolves
    # its path next to the running driver. A root that lacks it cannot run that
    # preset; copy it at setup and let the module manifest gate a later drift.
    _qwen = script.with_name("paper_qwen_agent.py")
    if _qwen.is_file():
        shutil.copy(_qwen, root / "paper_qwen_agent.py")
    # The render/track shims are resolved beside the running driver
    # (`visual_renderer_choices`, the MCP probes). A root without them silently
    # loses the highest-fidelity renderer/comparer, so they travel too.
    for _shim_name in ("docx2pdf.sh", "docxcompare.sh"):
        _shim = script.with_name(_shim_name)
        if _shim.is_file():
            shutil.copy2(_shim, root / _shim_name)
    # The venue profiles travelled with `copy_asset_dirs` above: they are a
    # frozen runtime asset in the module/asset manifest (Rule 11), so setup fails
    # on a copy error instead of warning and shipping a root whose `--list` and
    # profile precedence read a missing directory.
    _venue_root = root / VENUE_PROFILES_DIRNAME
    if _venue_root.is_dir():
        print(f"[setup] venue profiles:          frozen {VENUE_PROFILES_DIRNAME}/ "
              f"({len(list(_venue_root.glob('*.json')))} profile(s)) into the root and "
              f"recorded in the module manifest")
    if venue_profile_file:
        try:
            _dest = root / VENUE_PROFILES_DIRNAME / f"{venue_profile.id}{VENUE_PROFILE_SUFFIX}"
            _dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(venue_profile_file), _dest)
            print(f"[setup] venue profile:           installed {venue_profile.id!r} from "
                  f"{venue_profile_file} into {VENUE_PROFILES_DIRNAME}/ (the new root is "
                  f"self-contained)")
        except OSError as e:
            die(f"could not install --venue-profile {venue_profile_file!r} into {root}: {e}")
    # Normalize the pristine copy BEFORE the manifests/digests are recorded, so
    # the byte-identity checks, the round-1 base (a1) and every later pin all
    # refer to the SAME repaired text. This is the formatting analogue of the
    # document-recovery repair: the operator's --source directory is never
    # touched, and `--format-fix off` keeps the copy byte-identical instead.
    _venue_snapshot = venue_profile.to_dict()
    _venue_snapshot["origin"] = venue_profile.describe_origin()
    _venue_snapshot["recorded"] = utcnow()
    ctx.cfg = {"rounds": rounds, "judges": judges_list, "source": str(source),
               # HOW the round champion is chosen: `judge` (the panel, default) or
               # the no-judge `revise`/`integrate` auto-promotion. A decided round
               # records the mode it actually used, so this key only plans future
               # rounds.
               "champion_select": str(getattr(args, "champion_select", None)
                                      or DEFAULT_CHAMPION_SELECT),
               # WHICH venue's rules this root enforces, which journal it is
               # going to, and the profile as it looked when it was selected:
               # every later stage reads these (see venue_profile_of), so a
               # root cannot silently drift to another venue's numbers.
               "venue": venue_profile.id, "journal": journal,
               "journal_source": journal_source,
               "article_type": venue_profile.article_type_id,
               "article_type_source": article_type_source,
               "caption_limit_source": caption_limit_source,
               "venue_profile": _venue_snapshot,
               "caption_limit": caption_limit, "zotero": zotero,
               "vs_original_rule": str(getattr(args, "vs_original_rule", VS_ORIGINAL_RULE)),
               # The adaptive defect-prefix tie-break's floor: keep accumulating
               # severity_tier_category cells until the cleanest ranked version
               # carries this many defects (or every cell is used).
               "tiebreak_defect_floor": tiebreak_floor,
               # The issue-census dedup mode: "off" (default) counts every
               # sheet's rows; "location" merges rows across sheets on the
               # structured key (defect class + exact line + fuzzy excerpt).
               "dedup_mode": dedup_mode,
               "stop_after_no_progress": _stop_k,
               "review_split": str(getattr(args, "review_split", "off") or "off"),
               "audit": str(getattr(args, "audit", DEFAULT_AUDIT) or DEFAULT_AUDIT),
               # The REVISION AUDIT's recorded policy: "on" (default) audits the
               # revised package and runs one bounded repair when the plan is
               # non-empty; "off" leaves the revised version final. The env
               # override PAPER_REVISION_AUDIT works on an existing root.
               "revision_audit": str(getattr(args, "revision_audit", "on") or "on").lower(),
               # The COLD-START REVIEW's recorded policy: "on" (default) plans one
               # extra independent session per full-scope round; "off" is the
               # documented off switch (`set-cold-start-review` flips it on an
               # existing root). A root with no key plans no probe run.
               "cold_start_review": str(getattr(args, "cold_start_review", COLD_START_REVIEW_DEFAULT)
                                   or COLD_START_REVIEW_DEFAULT),
               # Whether `code/` is part of the submission (default: off -- the
               # area is revision content, never submitted unless asked for).
               "submit_code": str(getattr(args, "submit_code", DEFAULT_SUBMIT_CODE)
                                  or DEFAULT_SUBMIT_CODE),
               # Where a missing mandatory item goes (default: readme -- no
               # document carries the literal "[AUTHOR TO COMPLETE: ...]" marker;
               # the item is recorded in README-AUTHOR-TO-COMPLETE.md beside the
               # cover letter and main text, and the README is never submitted).
               # `document` (`--author-to-complete document`) keeps the
               # in-document marker; `off` (`--author-to-complete off`) moves
               # the item to the package's own MANUAL_STEPS.md. Outside
               # `document`, a shipped marker is a defect.
               "author_to_complete": _atc_mode(getattr(
                   args, "author_to_complete", DEFAULT_AUTHOR_TO_COMPLETE)),
               # Files the operator declares as PLACEHOLDERS (they stand in for
               # data they do not contain). They are ignored as evidence; see
               # `declared_placeholder_paths`.
               "placeholder_files": [str(x) for x in (getattr(
                   args, "placeholder_files", None) or []) if str(x).strip()],
               "placeholder_lookup": str(getattr(args, "placeholder_lookup",
                                                 DEFAULT_PLACEHOLDER_LOOKUP)
                                         or DEFAULT_PLACEHOLDER_LOOKUP),
               # `artifact_policy` is the three-valued policy ("on" and "fix"
               # both fail an unfilled table; `fix` first offers it one repair).
               "artifact_policy": artifact_policy,
               "format_policy": format_policy, "format_fix": format_fix,
               "rewrites": rewrites, "revises": revises, "integrators": integrators,
               "review_scope": review_scope,
               "created": utcnow(), "version": VERSION}
    # THE OPT-IN POLICIES. Both defaults (`high`, `on`) are the pipeline exactly
    # as it has always been, so a default root writes NO new key and its
    # `pipeline_config.json` is byte-identical to the pre-profile pipeline's:
    # `--execution-profile high` cannot perturb a root it did not need to
    # describe. A root without either key reads as `high` / `on`, and a root
    # that opted in carries the policy that produced its artifacts (rule 10).
    _profile = str(getattr(args, "execution_profile", EXECUTION_PROFILE_DEFAULT)
                   or EXECUTION_PROFILE_DEFAULT).lower()
    if _profile != EXECUTION_PROFILE_DEFAULT:
        ctx.cfg["execution_profile"] = _profile
    _guided = str(getattr(args, "guided_review", GUIDED_REVIEW_DEFAULT)
                    or GUIDED_REVIEW_DEFAULT).lower()
    if _guided != GUIDED_REVIEW_DEFAULT:
        ctx.cfg["guided_review"] = _guided
        ctx.cfg["guided_review_gap"] = GUIDED_REVIEW_GAP
    if round_indices:
        # Traceability: pipeline round k follows built-in schedule round
        # round_indices[k-1]. The recorded per-round lists below already carry
        # the selected plan; this key names WHERE it came from.
        ctx.cfg["round_indices"] = list(round_indices)
    if revision_mode != JOURNAL_MODE_CONTINUE:
        # Journal revision modes (options 1-4) and `init`. The keys are written
        # ONLY for a non-default mode: a default root keeps the exact config it
        # always had (`journal_mode_of` reads a missing key as "continue"), so the
        # historical workflow is byte-compatible down to pipeline_config.json.
        # The feedback keys belong to the modes that actually read a letter.
        ctx.cfg["revision_mode"] = revision_mode
    if scoped_mode_restore is not None:
        # Recorded, not inferred: leaving the scoped mode must restore what the
        # operator passed here, not the built-in defaults.
        ctx.cfg["scoped_mode_restore"] = scoped_mode_restore
    if JOURNAL_MODES[revision_mode]["feedback"]:
        ctx.cfg.update({"journal_feedback": journal_feedback,
                        "journal_feedback_from": journal_feedback_from})
    # The operator's --source as it was at setup time, BEFORE the formatter
    # normalizes the working copy. `from-setup-source` compares against THIS;
    # `source_manifest` (recorded below) describes the normalized pristine copy
    # and would make every source look "changed on disk".
    source_manifest_raw = hash_manifest(ctx.pristine)
    format_fix_report = None
    if format_fix != "off":
        setup_warns = []
        format_fix_report = normalize_formatting_in_dir(
            ctx.pristine, pre_judge_format_policy(ctx), "original", warns=setup_warns,
            artifacts_dir=ctx.reports_dir, template=venue_word_templates(ctx) or None,
            containers=venue_containers(ctx))
        for w in setup_warns:
            print(f"[setup] {w}")
    # The original's VERSION digest uses the same corpus rule as every other
    # version digest (`manifest_for_sources`: the tracking auxiliaries and the
    # bookkeeping-named files are not corpus content). Recording the whole-tree
    # digest here instead made materialize_a1 die with "A1_1 base/ does not match
    # its source" for any package carrying a stage by-product -- a published
    # `REPLACEMENT_LEDGER-<token>.md` in a continue root's source, a CHANGELOG.md.
    # `source_manifest` above stays the byte-level guard of the pristine copy.
    ctx.state = {"version": STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": hash_manifest(ctx.pristine),
                 "source_manifest_raw": source_manifest_raw,
                 "original_digest":
                     manifest_digest(manifest_for_sources([(ctx.pristine, "", ())])),
                 "original_content_fingerprint":
                     corpus_content_set_fingerprint([(ctx.pristine, "", ())]),
                 "original_format_fix": format_fix_report,
                 "judge_salt": os.urandom(8).hex(),
                 # WHICH PIPELINE created this root (see pipeline_identity_note):
                 # every later invocation compares its own digest with this one.
                 # `snapshot_of`/`snapshot_origin` are set when the operator asked
                 # for another root's frozen copy to be used on purpose.
                 "pipeline": _pipeline_state,
                 "source": str(source)}
    ctx.state["original_captions"] = scan_captions_in_sources([(ctx.pristine, "", ())],
                                                              limit=caption_limit)
    ctx.state["original_lengths"] = scan_lengths_in_sources([(ctx.pristine, "", ())],
                                                            profile=venue_profile)
    ctx.state["original_placeholders"] = scan_placeholders_in_sources(
        [(ctx.pristine, "", ())])
    ctx.state["original_format"] = scan_format_in_sources(
        [(ctx.pristine, "", ())], policy=ctx.cfg.get("format_policy"))
    # The config lives in pipeline_config.json (and is mirrored into state.json so
    # the state file is self-describing, as the run-record contract requires).
    ctx.state["config"] = ctx.cfg
    write_json_atomic(ctx.cfg_path, ctx.cfg)
    ctx.log("setup", detail=f"rounds={rounds} judges={judges_list} rewrites={rewrites} "
                            f"revises={revises} integrators={[hex(x) for x in integrators]} "
                            f"venue={venue_profile.id} journal={journal or '(unset)'} "
                            f"revision_mode={revision_mode} "
                            f"round_indices={round_indices or '(all)'} "
                            f"files={len(files)} "
                            f"caption_limit={caption_limit} "
                            f"zotero={zotero} "
                            f"placeholders={ctx.state['original_placeholders']['count']}")
    ctx.save_state()
    # state.json exists: the root is a usable pipeline now, so a later `setup`
    # must refuse to touch it (the interrupted-setup branch above keys on this).
    try:
        marker.unlink()
    except OSError:
        pass
    # Round r's field is {original} + {pins from earlier rounds} + the round's
    # fresh arms (a1, M rewrites, N revisions and the integrated candidates the
    # round's integrator mask selects); a1 always deduplicates against the
    # previous pin (or the original), so an upper bound on the field size is
    # 1 + (r-1) + (1+M+N) + <selected integrations>. Judge sessions are the
    # round's own `--judges` count per member.
    #
    # `--champion-select` is part of the RUNTIME plan: `revise` runs NO
    # integration arm (round_integrators() returns 0 for an undecided round) and
    # both no-judge modes run NO judge session. This estimate/print must use the
    # same rule as drive_round, or the operator is told to budget for sessions
    # the run will never start (F20).
    _csel_plan = str(getattr(args, "champion_select", None) or DEFAULT_CHAMPION_SELECT)
    _planned_masks = [0] * rounds if _csel_plan == "revise" else list(integrators[:rounds])
    round_arms = [integrator_arms(rewrites[r - 1], revises[r - 1], _planned_masks[r - 1])
                  for r in range(1, rounds + 1)]
    field_bound = [r + len(round_pool_ids(rewrites[r - 1], revises[r - 1]))
                   + len(round_arms[r - 1]) for r in range(1, rounds + 1)]
    est_sessions = (sum(judges_list[r - 1] * field_bound[r - 1] for r in range(1, rounds + 1))
                    if _csel_plan == "judge" else 0)
    print()
    print(f"[setup] pipeline root:          {root}")
    print(f"[setup] venue:                  {venue_profile.id} (\"{venue_profile.label}\"; "
          f"{venue_profile.describe_origin()})")
    print(f"[setup] article type:           {venue_profile.article_type} "
          f"(`{venue_profile.article_type_id}`; "
          f"{len(venue_profile.article_types())} type(s) in the profile"
          + ("" if venue_profile.carries_article_numbers()
             else ", which carries no word limits for it: the stages count and name the "
                  "venue's own numbers")
          + ")")
    print(f"[setup] journal:                {journal or '(not set -- run `set-journal <name>`)'}"
          + ("" if journal else "  (the prompts say \"the target journal\")"))
    if revision_mode != JOURNAL_MODE_CONTINUE:
        print(f"[setup] revision mode:          {revision_mode} (option "
              f"{JOURNAL_MODES[revision_mode]['option']}) -- "
              f"{JOURNAL_MODES[revision_mode]['label']}"
              + (f"; feedback from {journal_feedback_from}" if journal_feedback_from else "")
              + (f"; feedback source {LLM_FEEDBACK_DIR}/ (pre-filtered)"
                 if revision_mode == JOURNAL_MODE_LLM else ""))
    _lim = venue_profile.length_limits()
    if _lim["abstract"].get("cap") is None and _lim["main text"].get("cap") is None:
        print(f"[setup] length limits (M19):     none configured by this venue profile -- the "
              f"counts are recorded and compared with the target journal's own guidelines")
    else:
        _a = "no cap" if _lim["abstract"].get("cap") is None else _lim["abstract"]["cap"]
        _m = "no cap" if _lim["main text"].get("cap") is None else _lim["main text"]["cap"]
        print(f"[setup] length limits (M19):     abstract <= {_a}, "
              f"main text <= {_m} "
              f"({venue_profile.length_limits_source})")
    print(f"[setup] rounds:                 {rounds} (FIXED length; the round-{rounds} champion "
          f"is the final answer)")
    if round_indices:
        print(f"[setup] round indices:          pipeline round(s) 1..{rounds} follow built-in "
              f"schedule round(s) {', '.join(str(i) for i in round_indices)} "
              f"({brief_list(rewrites)} rewrites; {brief_list(integrators, lambda v: hex(v))} "
              f"integrator mask(s))")
    if revision_mode in (JOURNAL_MODE_MAJOR, JOURNAL_MODE_MINOR):
        print(f"[setup] judge panel:            none -- a {revision_mode} revision is "
              f"concern-scoped, and the journal (not a quality panel) decides next")
        print(f"[setup] rewrites per round (M): {rewrites}  (forbidden in this mode)")
        print(f"[setup] revises per round (N):  {revises}  (ONE concern-scoped revision pass; "
              f"the reviewers' points are its only findings)")
        print(f"[setup] integrators per round:  {[hex(x) for x in integrators]}  "
              f"(nothing to integrate without rewrite arms)")
        print(f"[setup] pipeline:               concerns -> revision -> "
              f"{'response -> ' if revision_mode in (JOURNAL_MODE_MAJOR, JOURNAL_MODE_MINOR) else ''}"
              f"{JOURNAL_SUBMISSION_DIR}/ (raw_data/ and README*.md/.txt never submitted; "
              f"{'code/ submitted' if str(getattr(args, 'submit_code', DEFAULT_SUBMIT_CODE)) == 'on' else 'code/ never submitted'})")
        _jm_skip = True
    else:
        _jm_skip = False
    if not _jm_skip:
        if _csel_plan == "judge":
            print(f"[setup] judges per round:       {judges_list}  (independent judge sessions "
                  f"PER VERSION per round)")
        else:
            print(f"[setup] judges per round:       none -- --champion-select {_csel_plan} "
                  f"runs NO judge panel (the decision is PROVISIONAL)")
        print(f"[setup] rewrites per round (M): {rewrites}  (rewritten candidates w1..wM per "
              f"round)")
        print(f"[setup] revises per round (N):  {revises}  (reviewed-and-then-revised candidates "
              f"a2..a{{1+N}} per round; ONE $paper-review pass per round feeds all of them)")
        print(f"[setup] integrators per round:  {[hex(x) for x in _planned_masks]}  (bit k-1 selects "
              f"the k-th pool member's integration arm; 0x{INTEGRATOR_ALL:X} = every applicable "
              f"agent"
              + ("; --champion-select revise runs no integration arm"
                 if _csel_plan == "revise" else "") + ")")
        _csel = _csel_plan
        print(f"[setup] champion selection:     {_csel}  ("
              + ("the relative-judgment panel ranks the field and code selects the winner"
                 if _csel == "judge" else
                 f"NO judge panel: auto-promote "
                 f"{'the review-audit-revised a2' if _csel == 'revise' else 'the revised candidate integration arm i<M+2>'}; "
                 f"PROVISIONAL, not certified")
              + ")")
    if not _jm_skip:
        for r in range(1, rounds + 1):
            m, n_ = rewrites[r - 1], revises[r - 1]
            pool = round_pool_ids(m, n_)
            arms = set(round_arms[r - 1])
            if _csel_plan == "revise":
                # round_integrators() is 0 for an undecided round in this mode:
                # no i<k> session is planned, so do not print one.
                print(f"[setup]   round {r}: pool = {', '.join(pool)}  ->  "
                      f"NO integration arm (--champion-select revise)")
                continue
            plan = "; ".join(
                f"{integrate_vid(k + 1)} = {src} <- ({', '.join(v for v in pool if v != src)})"
                + ("" if k + 1 in arms else "  [SKIPPED: integrators bit clear]")
                for k, src in enumerate(pool))
            print(f"[setup]   round {r}: pool = {', '.join(pool)}  ->  {plan}")
        if _csel_plan == "judge":
            print(f"[setup] directed scores/version: 2*judges*(|field|-1) per round "
                  f"({2 * judges_list[0] * (field_bound[0] - 1)} in round 1 at its upper-bound "
                  f"field of {field_bound[0]}, {judges_list[0]} judges; 6*(|field|-1) when "
                  f"judges=3)")
            print(f"[setup] expected judge sessions: ~{est_sessions} over {rounds} round(s) "
                  f"(upper bounds {field_bound}; content-identical field members dedup away)")
        else:
            print(f"[setup] judge sessions:         none -- --champion-select {_csel_plan} "
                  f"promotes a named version without a panel (PROVISIONAL, not certified)")
    if caption_limit:
        _cap_origin = ("the venue's own published legend limit, carried by its profile"
                       if venue_profile.captions.get("published_limit")
                       else "proposed by the PIPELINE, not by the master prompt or the skills")
        print(f"[setup] figure captions:         <= {caption_limit} words SUGGESTED (pipeline "
              f"check id M18; reported by the rewrite, review, revise, integration and judge "
              f"prompts). "
              f"This length is {_cap_origin}, and it is ADVISORY: an over-limit caption is "
              f"reported, never enforced -- it cannot make a version ineligible or fail a "
              f"decision. Use --caption-limit 0 for no caption suggestion at all.")
    else:
        print("[setup] figure captions:         NO caption suggestion (--caption-limit 0"
              + ("" if venue_profile.captions.get("published_limit") else ", the profile default")
              + "): caption length is never flagged, scored or judged. (Caption length was never "
                "enforced in any case -- the suggestion is opt-in and advisory; "
              + (venue_profile.captions.get("source") or "no venue legend rule is carried")
              + ".)")
    cap = ctx.state["original_captions"]
    _cap_mode = (f"{len(cap['over_limit'])} over the proxy cap of {cap['limit']} words"
                 if cap["limit"] else "no proxy cap configured; counts recorded for the author "
                                      "(compare them with the venue's own per-type legend rule)")
    print(f"[setup] legend scan (source):    {cap['count']} legend(s) found, {_cap_mode}"
          + (f", {len(cap['unparsed'])} file(s) not parseable" if cap["unparsed"] else ""))
    print("[setup] abstract/main-text length: "
          + length_note(ctx.state["original_lengths"])
          + (f"; {len(ctx.state['original_lengths']['unparsed'])} file(s) not parseable"
             if ctx.state["original_lengths"]["unparsed"] else ""))
    ph = ctx.state["original_placeholders"]
    print(f"[setup] hand-off placeholders:   {ph['count']} in the pristine original "
          f"(markers the revision stages must use instead of inventing content; counted and "
          f"reported, never scored)")
    _atc = _atc_mode(getattr(args, "author_to_complete", DEFAULT_AUTHOR_TO_COMPLETE))
    _atc_note = {
        "readme": (f"(no document carries the marker: each missing item is recorded in "
                   f"{AUTHOR_TO_COMPLETE_README} beside the cover letter and main text; the "
                   f"README is never submitted, and a shipped marker is a defect)"),
        "document": ("(the stages scaffold a missing mandatory item with the literal "
                     "\"[AUTHOR TO COMPLETE: ...]\" token and list it for the author; the "
                     "marker is a legitimate hand-off)"),
        "off": ("(--author-to-complete off: no file may carry the marker -- a missing item "
                "is left out of the document and recorded in the package's MANUAL_STEPS.md, "
                "and a shipped marker is a defect rather than a hand-off)"),
    }[_atc]
    print(f"[setup] hand-off items:          {_atc} {_atc_note}")
    print("[setup] OOXML formatting scan:   " + format_note(ctx.state["original_format"])
          + "  (code-side proxy; the agents' category-4 formatting sweep is authoritative)")
    _zot_note = {
        "off": "the `zot` CLI is NEVER used; live fields stay on the skills' manual route",
        "read": "read-only reference resolution with `zot`; citation fields are not edited",
        "edit": "citation edits in the revised copy are allowed; the Zotero library stays "
                "read-only",
        "apply": "citation edits AND single-item field updates are allowed -- this WRITES TO "
                 "YOUR REMOTE ZOTERO ACCOUNT (propose-then-verify protocol)",
    }[zotero]
    print(f"[setup] zotero policy:           {zotero}: {_zot_note}"
          + (f" (`zot` {'on PATH' if zot_cli_available() else 'NOT on PATH'})"
             if zotero != "off" else ""))
    print(f"[setup] corpus rule:             the difference-tracking auxiliaries "
          f"(\"*.tracking-<token>.<ext>\" and their \"*.logging-<token>.<ext>\" fallbacks, "
          f"<token> = original / a1 / w<k> / a<k> / winner<r>) are excluded from every "
          f"judged/pinned corpus (the pipeline writes its own copies under {REDLINE_DIRNAME}/, "
          f"{TRACKING_DIRNAME}/ and {PDF_DIRNAME}/)")
    _art_note = {
        "on": "an unfilled/boilerplate decision artifact FAILS the attempt",
        "fix": "an unfilled/boilerplate decision artifact first gets ONE scoped repair session "
               "(it may only fill cells of the seeded tables, from the rows' own evidence, and "
               "it may only CHANGE files that stage wrote -- a deliverable the stage never wrote "
               "is not repairable, and the stage is re-run instead); the same postcheck then "
               "judges it, and a repair that does not clear it fails the attempt like any other",
        "off": "the detector still runs and is recorded, but never fails an attempt",
    }[artifact_policy]
    print(f"[setup] artifact policy:         {artifact_policy}: {_art_note}")
    print(f"[setup] per-round winners:       {root}/round<r>_winner/  (digest-verified against "
          f"the content-addressed pins)")
    # WHICH CODE THIS ROOT WILL RUN (2026-10-16): `setup` froze the script that
    # is running NOW, so a root created from another root's copy runs that
    # copy's code for every later command -- silently, until this note. The
    # 2026-10-15b neohet root was set up that way and its package never saw the
    # checks committed two hours earlier.
    try:
        _ctx = Ctx(root)
        _ctx.load()
        _note = pipeline_snapshot_note(_ctx)
        if _note:
            print(f"[setup] {_note}")
    except Exception as e:                                            # noqa: BLE001
        print(f"[setup] note: the pipeline-snapshot check could not run "
              f"({type(e).__name__}: {e})")
    # THE RECORDED POLICIES. Both defaults are the pipeline unchanged, so
    # printing either line only when it was actually chosen keeps a default
    # root's setup output identical to the pre-profile pipeline's.
    if str(ctx.cfg.get("execution_profile") or "high") != "high":
        print(f"[setup] execution profile: {ctx.cfg.get('execution_profile')} "
              f"(the elaborative rule sections are paged to "
              f"{PROFILE_RULES_REL} in each session sandbox; postchecks unchanged)")
    if str(ctx.cfg.get("guided_review") or "on") != "on":
        print("[setup] guided review: OFF -- the cold-start review runs alone; the guided "
              "classes (M1-M36/J1-J5, D0-D5) are recorded as a NAMED GAP in every downstream "
              "sandbox and in pipeline_config.json")
    print(f"[setup] next: python {root / script.name} run --root {root}")
    print(f"[setup] manual mode: add --agent manual (staging is respected; each round's revise "
          f"prompt appears only after its review marker)")


def _timeout_seconds(args, default: int) -> int:
    """The operator's `--timeout`, keeping an explicit 0 as "no timeout".

    The staged commands that accept `--timeout` route it through here (conform,
    add-venue, the template stage, the audits). `conflicts` validates the same
    non-negative invariant at its own entry point (`cmd_conflicts`) because it
    passes the value straight to the conflict-audit helper. Only the `run` path
    used to validate the value, so `conform --timeout -1` handed a truthy
    negative deadline to `communicate()` and every session died as an immediate
    "TIMEOUT after -1s"; a negative value must be refused before it reaches
    `communicate()`.
    """
    value = getattr(args, "timeout", None)
    seconds = int(default if value is None else value)
    if seconds < 0:
        die("--timeout must be a non-negative number of seconds", code=2)
    return seconds


def _venue_command_root(args, cmd: str) -> Path:
    """The root a `set-venue` / `set-journal` invocation may write to.

    Both commands change a root's CONFIG, so the root must already exist (its
    pipeline_config.json is the file they edit). Before `setup` there is
    nothing to configure: `setup --venue/--journal` is the way to choose the
    rule set a new root starts with.
    """
    root = Path(args.root).resolve()
    if not (root / "pipeline_config.json").is_file():
        die(f"{root} is not a pipeline root yet (no pipeline_config.json): "
            f"run `setup --source <dir> --root {root} --venue <venue>` first, or point "
            f"--root at an existing root. `{cmd}` edits an existing root's configuration.",
            code=2)
    return root


def _print_venue_list(root, as_json: bool) -> None:
    profiles = available_venue_profiles(root)
    if as_json:
        # print_raw: machine-readable output must not carry the datetime prefix.
        print_raw(json.dumps({"venues": [{"id": v["id"], "label": v.get("label"),
                                          "origin": v.get("origin"),
                                          "path": v.get("path"),
                                          "default_journal": v.get("default_journal"),
                                          "description": v.get("description"),
                                          "note": v.get("note"),
                                          "error": v.get("error")}
                                         for v in sorted(profiles.values(),
                                                         key=lambda x: x["id"])]},
                             indent=2, sort_keys=False))
        return
    print("Available venues (a venue is a requirement set, not a journal):")
    for v in sorted(profiles.values(), key=lambda x: x["id"]):
        if v.get("error"):
            print(f"  {v['id']:<24} INVALID: {v['error']}")
            continue
        default = f"; default journal {v['default_journal']!r}" if v.get("default_journal") else ""
        print(f"  {v['id']:<24} {v.get('label')} [{v.get('origin')}]{default}")
        if v.get("description"):
            print(f"  {'':<24} {v['description']}")
        if v.get("note"):
            print(f"  {'':<24} note: {v['note']}")
    print()
    print("Select one with `set-venue <id>`; add your own with")
    print(f"  set-venue <id> --profile /path/to/<id>{VENUE_PROFILE_SUFFIX} "
          f"(installed into <root>/{VENUE_PROFILES_DIRNAME}/).")
    print("See README.md -> \"Venues and journals\" for the profile schema.")


def _print_venue_show(ctx, as_json: bool, notes=()) -> None:
    prof = venue_profile_of(ctx, required=False)
    if prof is None:
        # The venue may be healthy while only the recorded ARTICLE TYPE is not:
        # show the base profile and name the type remedy instead of calling the
        # whole venue unresolved.
        base, _load_err = venue_profile_base(ctx)
        if base is not None:
            prof = base
            notes = list(notes) + [
                f"the recorded article type {str(ctx.cfg.get('article_type') or '')!r} is "
                f"invalid for venue {base.id!r}; the values below describe its default type "
                f"{base.article_type!r}. Run `set-article-type <id>`."]
    all_notes = []
    for note in [str(n) for n in notes] + list(getattr(ctx, "venue_notes", []) or []):
        if note and note not in all_notes:
            all_notes.append(note)
    data = {"root": str(ctx.root),
            "notes": all_notes,
            "venue": venue_id_of(ctx),
            "venue_label": prof.label if prof else None,
            "venue_origin": prof.describe_origin() if prof else None,
            "venue_description": prof.description if prof else None,
            "article_type": (prof.article_type if prof else None),
            "article_type_id": (prof.article_type_id if prof else None),
            "article_types": ([{"id": tid, "label": label, "limits_carried": has}
                               for tid, label, has in prof.article_types()]
                              if prof else None),
            "journal": journal_of(ctx),
            "journal_configured": str(ctx.cfg.get("journal") or ""),
            "length_limits": (prof.length_limits() if prof else None),
            "caption_limit": caption_limit_of(ctx),
            "available": sorted(available_venue_profiles(ctx.root))}
    if as_json:
        print_raw(json.dumps(data, indent=2, sort_keys=False))
        return
    for note in data["notes"]:
        # The load-time venue warnings were captured (and reached JSON) but
        # never printed in text mode.
        print(f"note:    {note}")
    print(f"root:    {ctx.root}")
    print(f"venue:   {venue_id_of(ctx)}" + (f" (\"{prof.label}\", {prof.describe_origin()})"
                                            if prof else "  -- UNRESOLVED"))
    if prof is not None:
        print(f"article: {prof.article_type} (`{prof.article_type_id}` of "
              f"{len(prof.article_types())} type(s); `set-article-type --list`)")
    unset_journal = 'not set -- the prompts say "the target journal"'
    print(f"journal: {journal_of(ctx) or '(' + unset_journal + ')'}")
    if prof is not None:
        limits = prof.length_limits()
        print("limits:  abstract "
              f"{limits['abstract'].get('cap') if limits['abstract'].get('cap') is not None else 'none'}, "
              f"main text "
              f"{limits['main text'].get('cap') if limits['main text'].get('cap') is not None else 'none'}, "
              f"caption suggestion {caption_limit_of(ctx)}")
        print(f"         provenance: {prof.length_limits_source}")
        for label, key in (("abstract", "abstract"), ("main text", "main_text")):
            note = prof.length_limit_note(key)
            if note:
                print(f"         {label} note: {note}")
    if ctx.venue_problems:
        print("problems:")
        for p in ctx.venue_problems:
            print(f"  - {p}")


def _validate_journal_name(name: str) -> str:
    """A journal name is free text, but it must be one clean line."""
    text = str(name or "").strip()
    if not text:
        die("the journal name must not be empty (`set-journal \"Journal Name\"`)", code=2)
    if any(ch in text for ch in "\r\n\t") or len(text) > 160:
        die(f"the journal name must be one line of at most 160 characters (got {text!r})", code=2)
    return text


def cmd_set_venue(args) -> None:
    """Select the venue profile a root enforces, and optionally its journal."""
    root = Path(args.root).resolve()
    if getattr(args, "list", False):
        _print_venue_list(root, bool(getattr(args, "json", False)))
        return
    venue_arg = str(getattr(args, "venue", None) or "").strip()
    profile_file = str(getattr(args, "profile", None) or "").strip()
    article_arg = str(getattr(args, "article_type", None) or "").strip().lower()
    show = bool(getattr(args, "show", False))
    if show and not venue_arg:
        ctx = Ctx(_venue_command_root(args, "set-venue"),
                  strict_venue=bool(getattr(args, "strict_venue", False)))
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            ctx.load()
        notes = [ln for ln in captured.getvalue().splitlines() if ln.strip()]
        _print_venue_show(ctx, bool(getattr(args, "json", False)), notes)
        return
    ctx = Ctx(_venue_command_root(args, "set-venue"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    if not venue_arg:
        if getattr(args, "journal", None) is not None:
            # `set-venue --journal NAME` (no venue id) is the documented
            # `set-journal NAME` one-liner. It cannot honour the venue-scoped
            # options, so refuse them rather than silently dropping them; the
            # delegated command opens its own run log (no second log here).
            if article_arg or profile_file:
                die("`set-venue --journal NAME` (without a venue id) changes only the "
                    "journal; pass the venue id to apply --article-type/--profile.",
                    code=2)
            return cmd_set_journal(args)
        die("set-venue needs a venue id, e.g. `set-venue generic` "
            "(see `set-venue --list`), or `set-venue --show` to print the current one.\n"
            "       To install a profile of your own: `set-venue <id> --profile FILE`.",
            code=2)
    begin_run_log("set-venue", ctx.root, sys.argv)
    if not VENUE_ID_RE.match(venue_arg.lower()):
        die(f"invalid venue id {venue_arg!r}: letters, digits, '.', '_', '+', '-' only", code=2)
    venue_arg = venue_arg.lower()
    old_profile = venue_profile_of(ctx, required=False)
    old_default_journal = old_profile.default_journal if old_profile is not None else ""
    old_default_article = (old_profile.data["default_article_type"]
                           if old_profile is not None else "")
    installed = None
    if profile_file:
        src = Path(profile_file).expanduser()
        if not src.is_file():
            die(f"--profile {profile_file!r} is not a readable file", code=2)
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            die(f"--profile {profile_file!r} is not readable JSON: {e}", code=2)
        declared = str((data or {}).get("id") or "").strip().lower() \
            if isinstance(data, dict) else ""
        if declared and declared != venue_arg:
            die(f"--profile {profile_file!r} declares id {declared!r} but the command selects "
                f"{venue_arg!r}; make them agree (the file name in "
                f"{VENUE_PROFILES_DIRNAME}/ is what `--venue` resolves, so the id must match).",
                code=2)
        if isinstance(data, dict) and not declared:
            data = dict(data, id=venue_arg)
        try:
            installed = VenueProfile(data, origin=f"installed from {src}")
        except VenueProfileError as e:
            die(f"--profile {profile_file!r} is not a valid venue profile: {e}", code=2)
        venue_arg = installed.id
    try:
        profile = installed or load_venue_profile(venue_arg, root=ctx.root)
    except VenueProfileError as e:
        die(unknown_venue_message(venue_arg, ctx.root) if e.unknown else str(e), code=2)
    if ctx.state.get("runs") and not getattr(args, "force", False):
        done = len([r for r in ctx.state["runs"].values()
                    if r.get("status") in ("done", "running")])
        die(f"this root already has {len(ctx.state['runs'])} run record(s) ({done} done/running): "
            f"the rounds were planned and judged under venue {venue_id_of(ctx)!r}.\n"
            f"       Re-run `set-venue {profile.id} --force` if the change is intended (the "
            f"decision report records the venue of every round, and a new venue makes the "
            f"recorded judgments a mix of two rule sets).")
    journal_arg = getattr(args, "journal", None)
    # ---- the article type ------------------------------------------------
    # An article type the operator chose is kept when the new venue has it; a
    # type that only came from the old profile's default moves with the venue,
    # and a type the new profile does not know falls back to its default with a
    # note rather than silently borrowing another type's limits.
    article_arg = str(getattr(args, "article_type", None) or "").strip().lower()
    recorded_article = str(ctx.cfg.get("article_type") or "").strip().lower()
    recorded_source = str(ctx.cfg.get("article_type_source") or "").strip().lower()
    if article_arg:
        if article_arg not in profile.article_type_ids():
            die(f"unknown article type {article_arg!r} for venue {profile.id!r} "
                f"(available: {', '.join(profile.article_type_ids())})", code=2)
        article_type_id, article_type_source = article_arg, "operator"
    else:
        kept = recorded_article and (recorded_source == "operator"
                                     or (not recorded_source
                                         and recorded_article != old_default_article))
        if kept and recorded_article in profile.article_type_ids():
            article_type_id, article_type_source = recorded_article, "operator"
        else:
            article_type_id = profile.data["default_article_type"]
            article_type_source = "profile-default"
            if kept:
                print(f"[set-venue] note: venue {profile.id!r} carries no "
                      f"{recorded_article!r} article type; falling back to its default "
                      f"{profile.article_type!r} (`{article_type_id}`). "
                      f"Pick another one with `set-article-type <id>`.")
    profile = profile.with_article_type(article_type_id)

    if journal_arg is not None:
        journal = _validate_journal_name(journal_arg)
        journal_source = "operator"
    else:
        current = str(ctx.cfg.get("journal") or "").strip()
        current_source = str(ctx.cfg.get("journal_source") or "").strip().lower()
        # A journal the OPERATOR typed is kept; a journal that only came from
        # the old profile's default moves with the venue. A root that predates
        # `journal_source` is inferred from the value itself (a journal equal to
        # the old profile's default is treated as inherited).
        kept = current and (current_source == "operator"
                            or (not current_source and current != old_default_journal))
        if kept:
            journal, journal_source = current, "operator"
        elif profile.default_journal:
            journal, journal_source = profile.default_journal, "profile-default"
        else:
            journal, journal_source = "", "unset"
    caption_source = str(ctx.cfg.get("caption_limit_source") or "").strip().lower()
    caption_limit = int(ctx.cfg.get("caption_limit")
                        if caption_source == "operator" and ctx.cfg.get("caption_limit") is not None
                        else profile.caption_default)
    with ctx.lock("set-venue"):
        if installed is not None:
            dest_dir = ctx.root / VENUE_PROFILES_DIRNAME
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{profile.id}{VENUE_PROFILE_SUFFIX}"
            write_json_atomic(dest, profile.to_dict())
            print(f"[set-venue] installed profile -> {dest}")
            profile = VenueProfile(profile.to_dict(), origin=f"root-local profile: {dest}",
                                   path=dest)
        snapshot = profile.to_dict()
        snapshot["origin"] = profile.describe_origin()
        snapshot["recorded"] = utcnow()
        ctx.cfg["venue"] = profile.id
        ctx.cfg["journal"] = journal
        ctx.cfg["journal_source"] = journal_source
        ctx.cfg["article_type"] = profile.article_type_id
        ctx.cfg["article_type_source"] = article_type_source
        ctx.cfg["caption_limit"] = caption_limit
        ctx.cfg["caption_limit_source"] = ("operator" if caption_source == "operator"
                                           else "profile-default")
        ctx.cfg["venue_profile"] = snapshot
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-venue", detail=f"venue={profile.id} journal={journal or '(unset)'}")
        ctx.save_state()
    print(f"[set-venue] venue:   {profile.id} (\"{profile.label}\", {profile.describe_origin()})")
    print(f"[set-venue] article: {profile.article_type} (`{profile.article_type_id}`, "
          f"{'operator-set' if article_type_source == 'operator' else 'the profile default'})")
    print(f"[set-venue] journal: {journal or '(not set -- run `set-journal <name>`)'}")
    print(f"[set-venue] caption suggestion: {caption_limit} "
          f"({'operator-set' if caption_source == 'operator' else 'the venue profile default'})")
    if not journal:
        print("[set-venue] note:    no journal configured; the prompts will say "
              "\"the target journal\".")
    elif not profile.journal_matches(journal):
        print(f"[set-venue] warning: the journal {journal!r} is not one of the journals venue "
              f"{profile.id!r} describes ({', '.join(profile.known_journals())}); the venue's "
              f"rules still apply. Run `set-journal <name>` to change the journal, or "
              f"`set-venue <id>` for another rule set.")
    limits = profile.length_limits()
    if limits["abstract"].get("cap") is None and limits["main text"].get("cap") is None:
        print("[set-venue] limits:  this venue profile sets no abstract/main-text cap; the "
              "stages record the counts and compare them with the target journal's guidelines.")
    else:
        _a = "no cap" if limits["abstract"].get("cap") is None else limits["abstract"]["cap"]
        _m = "no cap" if limits["main text"].get("cap") is None else limits["main text"]["cap"]
        print(f"[set-venue] limits:  abstract <= {_a}, main text <= {_m} "
              f"({profile.length_limits_source})")
    print(f"[set-venue] next:    python {Path(__file__).name} run --root {ctx.root}  "
          f"(existing roots keep their completed rounds; `retry`/`run` re-stage the rest)")


def _article_type_list_lines(profile) -> list:
    """`set-article-type --list` / the refusal message: the type table."""
    lines = [f"Article types of venue {profile.id!r} (\"{profile.label}\"):"]
    for tid, label, has_limits in profile.article_types():
        limits = profile.with_article_type(tid).length_limits()
        if has_limits:
            _a = ("no cap" if limits["abstract"].get("cap") is None
                  else limits["abstract"]["cap"])
            _m = ("no cap" if limits["main text"].get("cap") is None
                  else limits["main text"]["cap"])
            caps = f"abstract <= {_a}, main text <= {_m}"
        else:
            caps = "no numbers carried: the stages count and name the venue's own limit"
        marker = " (default)" if tid == profile.data["default_article_type"] else ""
        lines.append(f"  {tid:<24} {label}{marker}\n"
                     f"  {'':<24} {caps}")
    lines.append("")
    lines.append("Select one with `set-article-type <id>` (or `setup --article-type <id>`); "
                 "the prompts, the M19 caps and the decision report follow it.")
    return lines


def cmd_set_article_type(args) -> None:
    """Select the venue's ARTICLE TYPE (Article, Brief Communication, ...).

    A venue publishes several content types, each with its own limits; the
    profile carries the table and this command records which one the submission
    is. Selecting a type the profile has no numbers for never borrows another
    type's caps: the stages count and name the venue's own limit instead.
    """
    ctx = Ctx(_venue_command_root(args, "set-article-type"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        ctx.load()
    notes = [ln for ln in captured.getvalue().splitlines() if ln.strip()]
    # The ARTICLE TYPE may be the only broken part of the configuration: an
    # unknown recorded type made `venue_profile_of` return None, so this very
    # command died with "fix the venue first" -- the dead end F031 removed from
    # `status`. Load the venue without applying the recorded type, then apply it
    # only when it is one the profile carries.
    profile, load_err = venue_profile_base(ctx)
    if profile is None:
        for note in notes:
            print(note)
        if load_err is not None and load_err.unknown:
            die(unknown_venue_message(venue_id_of(ctx), ctx.root))
        die(f"the venue profile selected by this root cannot be used: {load_err}\n"
            f"       Fix the file (`set-venue --list` shows the profiles), then retry.")
    _recorded_type = str(ctx.cfg.get("article_type") or "").strip().lower()
    if _recorded_type and _recorded_type in profile.article_type_ids():
        profile = profile.with_article_type(_recorded_type)
    wanted = str(getattr(args, "article_type", None) or "").strip().lower()
    if getattr(args, "list", False) or (getattr(args, "show", False) and not wanted):
        if getattr(args, "json", False):
            print_raw(json.dumps({"root": str(ctx.root), "venue": profile.id,
                                  "article_type": profile.article_type,
                                  "article_type_id": profile.article_type_id,
                                  "notes": notes,
                                  "article_types": [
                                      {"id": tid, "label": label,
                                       "limits_carried": has,
                                       "caps": (lambda lim: {"abstract": lim["abstract"]["cap"],
                                                             "main_text": lim["main text"]["cap"]})(
                                           profile.with_article_type(tid).length_limits()),
                                       "default": tid == profile.data["default_article_type"]}
                                      for tid, label, has in profile.article_types()]},
                                 indent=2))
            return
        for note in notes:
            print(note)
        if getattr(args, "list", False):
            for line in _article_type_list_lines(profile):
                print(line)
        else:
            _print_venue_show(ctx, False, notes)
        return
    if not wanted:
        die("set-article-type needs an article-type id, e.g. "
            "`set-article-type brief-communication` (`set-article-type --list` shows the "
            "types this venue's profile carries), or `set-article-type --show`.", code=2)
    if wanted not in profile.article_type_ids():
        die(f"unknown article type {wanted!r} for venue {profile.id!r} "
            f"(available: {', '.join(profile.article_type_ids())}).\n"
            f"       A type the profile does not carry can be added to a copy of the profile "
            f"and installed with `set-venue {profile.id} --profile <file>`.", code=2)
    begin_run_log("set-article-type", ctx.root, sys.argv)
    if ctx.state.get("runs") and not getattr(args, "force", False):
        die(f"this root already has {len(ctx.state['runs'])} run record(s): its prompts, caps "
            f"and judgments belong to the "
            f"{profile.article_type!r} type.\n"
            f"       Re-run `set-article-type {wanted} --force` if the change is intended.")
    with ctx.lock("set-article-type"):
        ctx.cfg["article_type"] = wanted
        ctx.cfg["article_type_source"] = "operator"
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-article-type", detail=wanted)
        ctx.save_state()
    chosen = profile.with_article_type(wanted)
    limits = chosen.length_limits()
    print(f"[set-article-type] article type: {chosen.article_type} (`{wanted}`) for venue "
          f"{profile.id} (\"{profile.label}\")")
    if not chosen.carries_article_numbers():
        print("[set-article-type] note: this profile carries no word limits for that type; the "
              "stages count and name the venue's own limit (see "
              "`venue_profiles/README.md` to add the numbers to a copy of the profile).")
    else:
        _a = "no cap" if limits["abstract"].get("cap") is None else limits["abstract"]["cap"]
        _m = "no cap" if limits["main text"].get("cap") is None else limits["main text"]["cap"]
        print(f"[set-article-type] M19 caps: abstract <= {_a}, main text "
              f"<= {_m} ({chosen.length_limits_source[:120]})")
    other = [tid for tid, _label, _has in profile.article_types() if tid != wanted][:4]
    if other:
        print(f"[set-article-type] others: {', '.join(other)}  (`set-article-type --list`)")


def cmd_set_journal(args) -> None:
    """Set the target journal (free text; selects no rule set by itself)."""
    show = bool(getattr(args, "show", False))
    name = str(getattr(args, "journal", None) or "").strip()
    if show and not name:
        ctx = Ctx(_venue_command_root(args, "set-journal"),
                  strict_venue=bool(getattr(args, "strict_venue", False)))
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            ctx.load()
        notes = [ln for ln in captured.getvalue().splitlines() if ln.strip()]
        _print_venue_show(ctx, bool(getattr(args, "json", False)), notes)
        return
    if not name:
        die("set-journal needs a journal name, e.g. `set-journal \"Nature Biotechnology\"` "
            "(or `set-journal --show` to print the current one)", code=2)
    ctx = Ctx(_venue_command_root(args, "set-journal"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    begin_run_log("set-journal", ctx.root, sys.argv)
    journal = _validate_journal_name(name)
    profile = venue_profile_of(ctx, required=False)
    mismatch = None
    if profile is not None and not profile.journal_matches(journal):
        mismatch = (f"{journal!r} is not one of the journals venue profile {profile.id!r} "
                    f"describes ({', '.join(profile.known_journals())}); the venue's rules "
                    f"still apply. Use `set-venue <id>` for another rule set.")
        if getattr(args, "strict_venue", False):
            # `setup --strict-venue` refuses exactly this mismatch BEFORE it
            # writes anything. Refusing after the write left the mismatched
            # journal in the config even though the command exited non-zero.
            die("--strict-venue: " + mismatch)
    if ctx.state.get("runs") and not getattr(args, "force", False):
        die(f"this root already has {len(ctx.state['runs'])} run record(s): every prompt names "
            f"the journal it was written for.\n"
            f"       Re-run `set-journal {journal!r} --force` if the change is intended.")
    with ctx.lock("set-journal"):
        ctx.cfg["journal"] = journal
        ctx.cfg["journal_source"] = "operator"
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-journal", detail=journal)
        ctx.save_state()
    print(f"[set-journal] journal: {journal} (venue {venue_id_of(ctx)})")
    if mismatch:
        print(f"[set-journal] warning: {mismatch}")


ADD_VENUE_PROMPT = """\
=== TASK: create or update ONE venue profile, and download its recent exemplars ===

You are working inside a SANDBOX. The shared venue store `@@DEST@@` is READ-ONLY here, so
write EVERY artifact into `@@STAGE@@/` in this sandbox, using the store's own layout
(`@@STAGE@@/@@VENUE@@.json`, `@@STAGE@@/README.md`, `@@STAGE@@/@@VENUE@@.official/`,
`@@STAGE@@/@@VENUE@@.manuscripts/`). The ORCHESTRATOR validates and publishes that staging
tree into the shared store after you finish -- never try to write to `@@DEST@@` yourself,
and never treat the read-only store as a failure. Do BOTH jobs below, in order, and finish
with the completion marker.

## 1. The venue profile (JSON)

Write or UPDATE `@@STAGE@@/@@VENUE@@.json`, copying the store's current README (and, when
it exists, the current `@@VENUE@@.json`) into `@@STAGE@@/` first so your edit is an UPDATE
of the real files. It must validate against the schema in `@@DEST@@/README.md` (read it
first). Required shape:

  * `"id"`: exactly `"@@VENUE@@"` (a slug);
  * `"label"`: the venue's human name; `"short"`: a short name for prompts;
  * `"journals"`: the journals this rule set covers (free-text names), plus
    `"accepts_any_journal": true` only when it is genuinely journal-agnostic;
  * `"article_types"`: a NON-EMPTY list of the venue's content types, each with
    `"id"` (slug), `"label"`, and `"length_limits"` carrying `abstract`/`main_text`
    entries of the form `{"base": <words|null>, "relaxation": <factor >= 1.0|null>,
    "note": "<where the number comes from>"}` -- use `null` when the venue publishes no
    number for that type (never invent one; say so in `"note"`);
  * `"captions"`, `"submission"` (cover letter / format guidance), `"prompt"` (the venue
    phrases the prompts use) and `"description"` as the README documents them;
  * every number must cite the venue's own author guidelines in its `"note"` (URL + what
    the page states). If a value cannot be verified, write `null` and say so -- never
    guess a limit.

Update `@@STAGE@@/README.md`: add (or refresh) ONE row for `@@VENUE@@` in the "Shipped
profiles" table with a one-sentence description, whose FIRST COLUMN is exactly
`` `@@VENUE@@` ``. If the store already carries a profile for the same journal under ANOTHER
id, do NOT edit that venue's row -- add a row for your id. Do not restructure the file.

## 2. Official journal templates (AUTHORITATIVE, if the venue publishes them)

Most venues publish their own Word and/or LaTeX template (for example Frontiers:
`https://www.frontiersin.org/Design/zip/Frontiers_Word_Templates.zip` and
`https://www.frontiersin.org/design/zip/Frontiers_LaTeX_Templates.zip`). Find the equivalents
for THIS venue on its own author-guidelines page and:

  * download each template archive into `@@STAGE@@/@@VENUE@@.official/` (keep the `.zip` too),
    then UNZIP it in place (subdirectories are fine) so the `.docx`/`.dotx`/`.tex`/`.cls`/`.sty`
    files are readable;
  * write `@@STAGE@@/@@VENUE@@.official/manifest.json` as a list of
    `{"source_url": ..., "archive": <file>, "files": [<extracted files>], "retrieved":
      "<ISO date>", "license_note": "<what the venue says about reuse>"}` objects;
  * if the venue publishes NO template, do not invent one: say so in the transcript and skip
    this section.

## 3. Recent exemplar manuscripts (structure input ONLY, ADVISORY)

Download recently published ARTICLE-TYPE examples for this venue into
`@@STAGE@@/@@VENUE@@.manuscripts/`, preferring the venue's OWN website / official OA pages
(@@ARTICLE_TYPE@@). Rules:

  * obey robots.txt, terms of service and paywalls: open-access articles only; never
    bypass a login, a paywall or a CAPTCHA;
  * for EACH article, save the source when it is a text format (`.tex`, `.md`, `.txt`) OR
    write a STRUCTURE-ONLY transcription as `<name>.md` -- a Markdown heading line for
    every section of the published article in its published order (`# Title`,
    `## Abstract`, `## Introduction`, ...), plus one line per statement section (data
    availability, ethics, funding, author contributions, competing interests,
    acknowledgements) when the article carries it. DO NOT paste the article's prose into
    the transcription: headings and statement NAMES only;
  * keep the downloaded PDF/HTML when licensing allows it, named `<name>.pdf`/`<name>.html`;
  * write `@@STAGE@@/@@VENUE@@.manuscripts/manifest.json` as a list of
    `{"article": <file>, "transcription": <file|null>, "source_url": ..., "doi": ...,
      "license": ..., "retrieved": "<ISO date>"}` objects -- one per article;
  * aim for 8-15 articles of the target article type from the last ~3 years; if you can
    only reach fewer, save what you have and say so in the transcript.

## 4. Finish

Write `_pipeline_done.json` in this sandbox with
`{"stage": "add-venue", "status": "complete", "error": null}` (or `"failed"` with a short
error). The orchestrator then validates the JSON profile and derives the structure-only
template pack itself -- do NOT write anything under `@@STAGE@@/@@VENUE@@.templates/`.
`"complete"` means the STAGING TREE is complete; a read-only shared store is expected.
"""


def add_venue_prompt(venue_id: str, dest: Path, journal: str = "",
                     article_type: str = "", want_download: bool = True,
                     stage: str = "store") -> str:
    """The `add-venue` agent prompt (profile + README + OA exemplar downloads)."""
    text = (ADD_VENUE_PROMPT
            .replace("@@DEST@@", str(dest))
            .replace("@@STAGE@@", stage)
            .replace("@@VENUE@@", venue_id)
            .replace("@@ARTICLE_TYPE@@", article_type or "the venue's main research article"))
    if not want_download:
        head, _, _tail = text.partition("## 2. Official journal templates")
        text = (head + "## 2. Official journal templates (SKIPPED: `--no-download`)\n\n"
                "Do NOT download anything for this request: the operator will supply the "
                "official template files in `@@STAGE@@/@@VENUE@@.official/` and the exemplars in "
                "`@@STAGE@@/@@VENUE@@.manuscripts/` themselves. Your job is the profile and the "
                "README row ONLY. Keep section 4's completion contract.\n\n## 4. Finish\n\n"
                "Write `_pipeline_done.json` in this sandbox with\n"
                "`{\"stage\": \"add-venue\", \"status\": \"complete\", \"error\": null}` (or "
                "`\"failed\"` with a short error).\n"
                ).replace("@@DEST@@", str(dest)).replace("@@STAGE@@", stage).replace(
                    "@@VENUE@@", venue_id)
    if journal:
        text += f"\n\nTarget journal (for `journals` and the prompts): {journal}.\n"
    return with_context_budget(text)


def _merge_tree(src: Path, dst: Path) -> int:
    """Copy every file under `src` into `dst` (creating paths); count writes.

    Every symlink -- a source entry the staged agent planted, a symlinked source
    ROOT, or a destination already carrying one -- is refused/replaced instead
    of followed: `rglob` + `is_file()` followed a source link (copying a host
    file into the shared venue store), a symlinked `src` made `rglob` enumerate
    the link's target, and `copy2` followed a destination link (overwriting its
    external target).
    """
    src = Path(src)
    if src.is_symlink():
        # The loop below refuses links INSIDE src, but `Path.rglob` on a
        # symlinked src enumerates the TARGET's files as ordinary regular
        # files, so every one of them was published.
        raise OSError(f"refusing to publish from symlinked directory {src}")
    written = 0
    for p in sorted(src.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(src)
        target = dst / rel
        cur = dst
        for part in rel.parts[:-1]:
            cur = cur / part
            if cur.is_symlink():
                raise OSError(f"refusing to publish through symlinked directory {cur}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        elif target.is_file():
            try:
                if sha256_file(target) == sha256_file(p):
                    continue
            except OSError:
                pass
        tmp = target.with_name(f".{target.name}.merge-{os.getpid()}-{time.time_ns()}")
        try:
            shutil.copy2(p, tmp)
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        written += 1
    return written


def _merge_readme_row(staged: Path, dest: Path, vid: str,
                      profile: dict = None) -> str:
    """Publish one venue's row from the staged README into the shared one.

    Returns "created" (no README existed), "updated" (the venue's row was
    replaced), "appended"/"synthesized" (the row was added to the table) or
    "unchanged". When the agent's staged README has no row for THIS id (it may
    have refreshed another venue's row for the same journal), the row is
    SYNTHESIZED from the validated profile, so the README always names the id.
    """
    staged_lines = []
    if staged is not None:
        # The staging tree is agent-writable: read the staged README through the
        # bounded, no-follow reader so a huge or special file cannot block/OOM
        # publication (F77).
        text = read_text_bounded(staged)
        if text is not None:
            staged_lines = text.splitlines()
    rows = [ln for ln in staged_lines if ln.startswith("|") and f"`{vid}`" in ln]
    synthesized = False
    if not rows:
        label = str((profile or {}).get("label") or vid)
        desc = str((profile or {}).get("description") or "").strip() or \
            f"{label} (created by `add-venue`)"
        rows = [f"| `{vid}` | {desc} |"]
        synthesized = True
    row = rows[0]
    if not dest.is_file():
        write_text_atomic(dest, row + "\n")
        return "created"
    try:
        lines = dest.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return f"unreadable ({e}); the profile was published but its README row was not merged"
    for i, ln in enumerate(lines):
        if ln.startswith("|") and f"`{vid}`" in ln:
            if ln == row:
                return "unchanged"
            lines[i] = row
            write_text_atomic(dest, "\n".join(lines) + "\n")
            return "updated"
    # Insert at the END of the "Shipped profiles" table -- the table the README
    # documents as the venue list. The file carries several tables, and a row
    # appended to the schema table (which also has backticked first cells) is
    # worse than no row.
    anchor = None
    heading = next((i for i, ln in enumerate(lines)
                    if ln.strip().lower().startswith("## shipped profiles")), None)
    if heading is not None:
        i = heading
        while i < len(lines) and not lines[i].startswith("|"):
            i += 1
        while i < len(lines) and lines[i].startswith("|"):
            anchor = i
            i += 1
    if anchor is None:
        venue_row_re = re.compile(r"^\|\s*`[a-z0-9._+-]+`\s*\|")
        anchor = max((i for i, ln in enumerate(lines) if venue_row_re.match(ln)), default=None)
    if anchor is None:
        anchor = max((i for i, ln in enumerate(lines) if ln.startswith("|")), default=None)
    if anchor is None:
        lines.append(row)
    else:
        lines.insert(anchor + 1, row)
    write_text_atomic(dest, "\n".join(lines) + "\n")
    return "synthesized" if synthesized else "appended"


def publish_add_venue_staging(sb: Path, dest: Path, vid: str) -> dict:
    """Publish a completed `add-venue` sandbox into the shared store.

    The agent works in a sandbox that can only write inside itself, so it stages
    the store's exact layout under `<sandbox>/store/`. This copies the staged
    profile, the venue's README row, and the `.official`/`.manuscripts` corpora
    into `dest`, then the caller validates and derives the template pack.
    """
    roots = [sb / "store"]
    out = {"profile": None, "readme": "unchanged", "official_files": 0,
           "manuscript_files": 0, "sandbox": str(sb), "notes": []}
    profile = next((r / f"{vid}{VENUE_PROFILE_SUFFIX}" for r in roots
                    if (r / f"{vid}{VENUE_PROFILE_SUFFIX}").is_file()), None)
    if profile is not None and profile.is_symlink():
        # A staged link would copy its external target into the shared store.
        out["notes"].append("profile: refused a symlinked staged profile")
        profile = None
    if profile is not None:
        target = dest / f"{vid}{VENUE_PROFILE_SUFFIX}"
        if target.is_symlink():
            target.unlink()
        tmp = target.with_name(f".{target.name}.merge-{os.getpid()}-{time.time_ns()}")
        try:
            shutil.copy2(profile, tmp)
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        out["profile"] = str(target)
    staged_readme = next((r / "README.md" for r in roots if (r / "README.md").is_file()), None)
    staged_profile = None
    if profile is not None:
        # Bounded, no-follow JSON reader: `profile.read_text()` here had no size
        # cap and no symlink/FIFO guard (F77).
        staged_profile = read_json(profile, revive=False)
        if not isinstance(staged_profile, dict):
            staged_profile = None
    out["readme"] = _merge_readme_row(staged_readme, dest / "README.md", vid, staged_profile)
    official = next((r / f"{vid}{VENUE_OFFICIAL_SUFFIX}" for r in roots
                     if (r / f"{vid}{VENUE_OFFICIAL_SUFFIX}").is_dir()), None)
    if official is not None and official.is_symlink():
        # The staged agent controls `store/`; a link here would publish the
        # target's whole tree into the shared venue store (the profile branch
        # above refuses the same shape). Do not raise in the caller: the
        # operator gets a note and the rest of the staging still publishes.
        out["notes"].append(f"{official.name}: refused a symlinked staged directory")
    elif official is not None:
        out["official_files"] = _merge_tree(official, dest / f"{vid}{VENUE_OFFICIAL_SUFFIX}")
    manuscripts = next((r / f"{vid}{VENUE_EXEMPLAR_SUFFIX}" for r in roots
                        if (r / f"{vid}{VENUE_EXEMPLAR_SUFFIX}").is_dir()), None)
    if manuscripts is not None and manuscripts.is_symlink():
        out["notes"].append(f"{manuscripts.name}: refused a symlinked staged directory")
    elif manuscripts is not None:
        out["manuscript_files"] = _merge_tree(manuscripts,
                                              dest / f"{vid}{VENUE_EXEMPLAR_SUFFIX}")
    for rel, why in (("PUBLISH.md", "the agent explained a publish blocker"),
                     ("_pipeline_done.json", "the agent's completion marker")):
        if (sb / rel).is_file():
            out["notes"].append(f"{rel}: {why}")
    return out


def latest_add_venue_sandbox(dest: Path, vid: str):
    """The newest `<dest>/.add-venue/<vid>-*` sandbox, or None."""
    base = Path(dest) / ".add-venue"
    if not base.is_dir():
        return None
    # Match the EXACT `<vid>-<stamp>` segment, not a name prefix: for
    # vid="nature", `nature-biotechnology-2026...` also startswith "nature-"
    # and sorted after the operator's own `nature-...` sandbox, so
    # `--publish-only` opened another venue's staging.
    pat = re.compile(r"^" + re.escape(vid) +
                     r"-(\d{8}T\d{6})(\d{6})?Z(?:-[0-9a-f]+)?$")

    def _stamp_key(p: Path):
        # Sort by the PARSED stamp, not by the name: for the same second `...Z`
        # sorts after `...123456Z-...`, so the older whole-second sandbox won.
        m = pat.match(p.name)
        return (m.group(1), m.group(2) or "", p.name)

    cands = sorted((p for p in base.iterdir() if p.is_dir() and pat.match(p.name)),
                   key=_stamp_key)
    return cands[-1] if cands else None


def template_stage_record(ctx: Ctx) -> dict:
    """The recorded, PASSED template-first stage for this root ({} when none)."""
    st = (ctx.state or {}).get("template_stage") or {}
    if not isinstance(st, dict) or not st.get("ok") or not st.get("dir"):
        return {}
    return st if (ctx.root / str(st["dir"])).is_dir() else {}


def working_original_dir(ctx: Ctx) -> Path:
    """The corpus round 1 starts from.

    A transfer-mode root whose template-first stage passed starts from THAT
    package (the submission authored inside the journal's own templates); every
    other root keeps the pristine original. The pristine copy stays the root's
    read-only EVIDENCE and the `non_revised/` view either way.
    """
    st = template_stage_record(ctx)
    return (ctx.root / str(st["dir"])) if st else ctx.pristine


def working_original_digest(ctx: Ctx):
    """The working original's VERSION DIGEST, under the corpus rule.

    Every version digest -- and the digest `materialize_a1` re-computes for the
    round-1 base -- is defined by `manifest_for_sources`, which strips the
    tracking auxiliaries and the bookkeeping-named files (`REPLACEMENT_LEDGER-
    <token>.md`, `CHANGELOG.md`, ...). Roots set up before the rules were unified
    recorded the WHOLE-TREE digest there instead, so a continue root whose source
    carried a stage's published ledger disagreed with its own byte-identical base
    copy and died with "A1_1 base/ does not match its source 'orig'".

    A recorded value that equals the tree digest of the working original (and not
    its corpus digest) is exactly that legacy recording, and resolves to the
    corpus digest here. Any OTHER disagreement returns the recorded value, so a
    working original whose documents really changed is still caught by the A1
    comparison. A missing/pruned working original falls back to the record.
    """
    st = template_stage_record(ctx)
    recorded = st.get("digest") or (ctx.state or {}).get("original_digest")
    src = working_original_dir(ctx)
    if not recorded or not src.is_dir():
        return recorded
    man = manifest_for_sources([(src, "", ())])
    if not man.get("count"):
        return recorded
    corpus = manifest_digest(man)
    if corpus != recorded and corpus_tree_digest(src) == recorded:
        return corpus
    return recorded


def working_original_fingerprint(ctx: Ctx):
    st = template_stage_record(ctx)
    return st.get("content_fingerprint") or (ctx.state or {}).get("original_content_fingerprint")


def _stage_template_rewrite_sandbox(ctx: Ctx, src: Path, templates: dict,
                                    force: bool = False) -> Path:
    """Create/refresh the template-first session sandbox (templates + source read-only)."""
    sb = ctx.root / TEMPLATE_REWRITE_DIRNAME
    if sb.exists() and any(sb.iterdir()):
        if not force:
            return sb
        rmtree_force(sb)
    sb.mkdir(parents=True, exist_ok=True)
    stage_venue_template(ctx, sb)
    srcdir = sb / "source"
    srcdir.mkdir(exist_ok=True)
    _stage_source_package(srcdir, src)
    (sb / "out").mkdir(exist_ok=True)
    (sb / PROMPT_FILE).write_text(apply_template_prompt(ctx, sb, srcdir, templates),
                                  encoding="utf-8")
    # The venue's display rules travel with the session: the agent's own
    # `paper_docx_format.py scan --policy format_policy.json` must check the
    # same rules the pipeline's postcheck enforces.
    try:
        seed_format_policy_file(ctx, sb)
    except Exception as e:                                            # noqa: BLE001
        print(f"[template-stage] note: the venue's format policy could not be seeded "
              f"({type(e).__name__}: {e})")
    try:
        seed_template_visuals(ctx, sb)
    except Exception as e:                                            # noqa: BLE001
        print(f"[template-stage] note: the venue template render could not be seeded "
              f"({type(e).__name__}: {e}); the prompt says to compare against venue_template/")
    return sb


def _record_template_stage(ctx: Ctx, sb: Path, agent: str) -> dict:
    """Record a PASSED template-first stage and make it round 1's working original."""
    out = sb / "out"
    # The digest must use the SAME corpus rule materialize_a1 re-computes
    # (`manifest_for_sources`), not the whole-tree digest: the prompt requires
    # out/VISUAL_CHECK.md, which that rule strips as bookkeeping, so mixing the
    # two made every compliant stage fail the A1 digest comparison.
    ctx.state["template_stage"] = {
        "ok": True, "dir": out.relative_to(ctx.root).as_posix(),
        "digest": manifest_digest(manifest_for_sources([(out, "", ())])),
        "content_fingerprint": corpus_content_set_fingerprint([(out, "", ())]),
        "agent": agent, "checked": utcnow(),
    }
    ctx.save_state()
    return ctx.state["template_stage"]


def _ensure_template_stage_for_run(ctx: Ctx, args) -> None:
    """TRANSFER/INIT MODES: conform the submission to the journal's rules FIRST.

    With an official Word template the stage is the template-first session
    (`conform --agent`): copy the template, replace its placeholders. Without
    one, `init` still runs it, falling back to the journal's own author
    guidelines and then to established academic convention. Its code-side
    postcheck gates the whole run, and a passing package becomes round 1's
    working original (the a1 base, the field's `original` view and every
    `vs_original` comparison read it). `--no-template-stage` opts out. `init`
    runs this stage without any journal feedback; `transfer` also feeds the
    decision letter into the rounds afterwards -- and without a template the
    transfer stage is skipped (its job IS the target journal's template).
    """
    if template_stage_record(ctx):
        print("[run] template-first stage: already recorded (state.json)")
        # BACKFILL: a root whose stage was recorded before the stage-time hook
        # existed (or one where the process died between recording and tracking)
        # still gets the copies -- the call is idempotent and keeps a fresh
        # entry, so it costs one digest pass, never an agent or a comparison.
        maybe_track_template_stage(ctx, ctx.root / TEMPLATE_REWRITE_DIRNAME)
        return
    if bool(getattr(args, "no_template_stage", False)):
        print("[run] template-first stage: skipped by --no-template-stage")
        return
    mode = journal_mode_of(ctx)
    templates = venue_word_templates(ctx)
    if not templates and mode != JOURNAL_MODE_INIT:
        print("[run] template-first stage: the venue ships no Word template -- skipping")
        return
    if not any(p.suffix.lower() == ".docx" for p in template_package_files(ctx.pristine)):
        print("[run] template-first stage: the corpus carries no .docx -- skipping "
              "(nothing to author in Word format)")
        return
    if not templates:
        print("[run] template-first stage: the venue ships no Word template -- conforming to "
              "the journal's own author guidelines, then to academic convention")
    agent = str(getattr(args, "agent", None) or DEFAULTS.get("agent", "codex"))
    sb = ctx.root / TEMPLATE_REWRITE_DIRNAME
    if agent == "manual" and sb.is_dir() and any(sb.iterdir()) and (sb / PROMPT_FILE).is_file():
        # Re-entering the stage by hand CHECKS the session the operator filled
        # (`--agent manual` told them to do exactly that). Rebuilding it with
        # force=True deleted the hand-filled out/ and never recorded the stage,
        # so `run` looped forever and the operator's work was lost.
        report = template_rewrite_postcheck(sb, ctx.pristine, templates,
                                            policy=format_policy_of(ctx))
        report.update({"venue": venue_id_of(ctx), "source": str(ctx.pristine), "sandbox": str(sb),
                       "agent": "manual", "agent_rc": None})
        write_json_atomic(ctx.reports_dir / "template_rewrite.json", report)
        cov = report.get("coverage") or {}
        print(f"[run] template-first stage: checked the existing session {sb}: coverage "
              f"{cov.get('covered', 0)}/{cov.get('checked', 0)} "
              f"({cov.get('ratio', 0.0):.0%}), template guide sentences left "
              f"{len(report.get('template_prose_left') or [])}")
        if not report.get("ok"):
            die(f"{mode} mode conforms the submission before any other stage: fill "
                f"{sb / 'out'} using {sb / PROMPT_FILE}, then re-run `run` (or check it with "
                f"`conform --root {ctx.root} --agent manual`). Its postcheck still reports: "
                + "; ".join(report["errors"])[:400])
        rec_stage = _record_template_stage(ctx, sb, "manual")
        print(f"[run] template-first stage: PASSED -- coverage "
              f"{report['coverage']['covered']}/{report['coverage']['checked']} "
              f"({report['coverage']['ratio']:.0%}), round 1 now starts from "
              f"{rec_stage['dir']} (digest {str(rec_stage['digest'])[:12]})")
        maybe_track_template_stage(ctx, sb)
        return
    sb = _stage_template_rewrite_sandbox(ctx, ctx.pristine, templates, force=True)
    action = ("copy the journal's templates, replace their placeholders with this submission's "
              "content" if templates else
              "re-author the whole package to the journal's guidelines and academic convention")
    print(f"[run] template-first stage: {sb} ({action})")
    if agent == "manual":
        die(f"{mode} mode conforms the submission before any other stage: fill {sb / 'out'} "
            f"using {sb / PROMPT_FILE}, then re-run `run` (or check it with "
            f"`conform --root {ctx.root} --agent manual`)")
    cmd = resolve_agent_cmd(agent, getattr(args, "agent_cmd", None))
    rec = {"id": TEMPLATE_REWRITE_DIRNAME, "kind": "template-rewrite", "status": "running",
           "sandbox": str(sb), "round": 0}
    timeout = _timeout_seconds(args, DEFAULTS.get("timeout", 14400))
    res = _execute_attempt_in(sb, rec, cmd, timeout)
    print(f"[run] template-first stage: agent {agent} rc={res.get('rc')} in "
          f"{res.get('dur', 0):.0f}s (log: {res.get('log')})")
    report = template_rewrite_postcheck(sb, ctx.pristine, templates,
                                        policy=format_policy_of(ctx))
    report.update({"venue": venue_id_of(ctx), "source": str(ctx.pristine), "sandbox": str(sb),
                   "agent": agent, "agent_rc": res.get("rc")})
    write_json_atomic(ctx.reports_dir / "template_rewrite.json", report)
    if not report.get("ok"):
        die("the template-first stage did not pass its postcheck: "
            + "; ".join(report["errors"])[:400])
    rec_stage = _record_template_stage(ctx, sb, agent)
    print(f"[run] template-first stage: PASSED -- coverage "
          f"{report['coverage']['covered']}/{report['coverage']['checked']} "
          f"({report['coverage']['ratio']:.0%}), round 1 now starts from "
          f"{rec_stage['dir']} (digest {str(rec_stage['digest'])[:12]})")
    maybe_track_template_stage(ctx, sb)


def default_template_package_source(ctx: Ctx):
    """The package `conform` rebuilds when no --source is given.

    The published final package when the root has one
    (`final_clean_version_<root dir name>/`), else the most recent complete
    round's `round<r>_winner/`, else None.
    """
    fin = ctx.root / final_clean_dirname(ctx.root)
    if fin.is_dir() and any(fin.iterdir()):
        return fin
    rounds = sorted((int(k) for k in (ctx.state.get("rounds") or {})
                     if str(k).isdigit()), reverse=True)
    for r in rounds:
        w = ctx.root / f"round{r}_winner"
        if w.is_dir() and any(w.iterdir()):
            return w
    return None


def _template_rewrite_session(ctx: Ctx, args, src: Path, templates: dict) -> None:
    """`conform --agent`: one LLM session that conforms the package.

    The sandbox mirrors the pipeline's stages: the venue's templates are staged
    READ-ONLY, the source package is copied read-only beside them, and the prompt
    tells the agent to copy a template and replace its placeholders with the
    source content; a venue with no official template falls back to its author
    guidelines and academic convention. The postcheck verifies the outcome
    code-side (template guide prose gone, source content covered, template
    styles still present) and the report lands in the root's reports/.
    """
    agent = str(getattr(args, "agent", None) or "").strip()
    sb = ctx.root / TEMPLATE_REWRITE_DIRNAME
    if sb.is_dir() and any(sb.iterdir()) and not bool(getattr(args, "force", False)) \
            and agent == "manual" and (sb / PROMPT_FILE).is_file():
        # Re-running `--agent manual` on an existing session CHECKS it: the
        # operator (or an agent run by hand) has filled out/, and this invocation
        # reports the code-side verdict instead of wiping the work.
        report = template_rewrite_postcheck(sb, src, templates,
                                            policy=format_policy_of(ctx))
        report.update({"venue": venue_id_of(ctx), "source": str(src), "sandbox": str(sb),
                       "agent": "manual", "agent_rc": None})
        write_json_atomic(ctx.reports_dir / "template_rewrite.json", report)
        cov = report.get("coverage") or {}
        print(f"[conform] checked the existing session {sb}: "
              f"coverage {cov.get('covered', 0)}/{cov.get('checked', 0)} "
              f"({cov.get('ratio', 0.0):.0%}), template guide sentences left "
              f"{len(report.get('template_prose_left') or [])}, headers/footers "
              f"{'ok' if not any('headers/footers' in e for e in report['errors']) else 'MISSING'}")
        if not report["ok"]:
            die("the template-first rewrite did not pass its postcheck: "
                + "; ".join(report["errors"])[:400])
        print("[conform] the package in out/ passed the code-side postcheck")
        # The stage is finished the moment its postcheck passes: the tracked
        # copies of the conformed package are written beside out/ now, not at
        # round close (the run's round-close pass keeps this entry).
        maybe_track_template_stage(ctx, sb)
        # In transfer/init the conform stage is part of the RUN: a passing check
        # records it so the next `run` starts round 1 from out/ instead of
        # rebuilding (and losing) the session. The standalone `continue`-mode
        # session stays a staging aid: nothing is recorded there.
        if journal_mode_of(ctx) in (JOURNAL_MODE_TRANSFER, JOURNAL_MODE_INIT) \
                and not template_stage_record(ctx):
            # The check above ran against THIS session's `source/`, which a
            # `conform --source X` may have staged from ANY package. The RUN's
            # gate is defined against the root's own submission, so re-verify
            # that contract before adopting out/ as round 1's working original:
            # recording a foreign package would silently replace the original
            # the a1 base and every later vs_original comparison read.
            run_report = template_rewrite_postcheck(sb, ctx.pristine, templates,
                                                    policy=format_policy_of(ctx))
            if run_report.get("ok"):
                rec_stage = _record_template_stage(ctx, sb, "manual")
                print(f"[conform] recorded as the template-first stage: round 1 now starts from "
                      f"{rec_stage['dir']} (digest {str(rec_stage['digest'])[:12]})")
            else:
                print(f"[conform] NOT recorded as this root's template-first stage: the session "
                      f"conforms its own source/, not the root's submission ({ctx.pristine}); "
                      f"its postcheck against the root reports: "
                      + "; ".join(run_report.get("errors") or [])[:300])
        return
    if sb.exists() and any(sb.iterdir()):
        if not bool(getattr(args, "force", False)):
            die(f"{sb} exists and is not empty: pass --force to rebuild the session sandbox")
        if is_within(Path(src), sb):
            # `conform` defaults `--source` to the session's own read-only
            # `source/` copy when the root has no final_clean_version/winner
            # (that is what makes the run banner's check command work). The
            # rebuild deletes the sandbox BEFORE re-staging, so staging from a
            # path inside it would silently produce an EMPTY session (and wipe
            # the operator's filled out/ for nothing). Re-stage from the root's
            # own input instead, and say so: the operator sees which package
            # the rebuilt session carries.
            print(f"[conform] note: --force rebuilds {sb} and the source {src} lives inside it; "
                  f"re-staging from the root's input {ctx.pristine} instead")
            src = ctx.pristine
        rmtree_force(sb)
    sb.mkdir(parents=True, exist_ok=True)
    stage_venue_template(ctx, sb)
    srcdir = sb / "source"
    srcdir.mkdir(exist_ok=True)
    _stage_source_package(srcdir, src)
    (sb / "out").mkdir(exist_ok=True)
    text = apply_template_prompt(ctx, sb, srcdir, templates)
    (sb / PROMPT_FILE).write_text(text, encoding="utf-8")
    try:
        # Best-effort: the rendered template pages let the agent compare visually.
        # A renderer that is missing or slow must never block the session setup --
        # the prompt says to fall back to the venue_template/ file itself.
        seed_template_visuals(ctx, sb)
    except Exception as e:                                        # noqa: BLE001
        print(f"[conform] note: the venue template render could not be seeded "
              f"({type(e).__name__}: {e}); the prompt tells the agent to compare against "
              f"venue_template/ instead")
    print(f"[conform] template-first session sandbox: {sb}")
    print(f"[conform] prompt: {sb / PROMPT_FILE}  (copy the journal templates, then "
          f"replace every placeholder with the source content)")
    print(f"[conform] templates staged read-only: "
          + ", ".join(Path(v).name for v in sorted(templates.values())))
    print(f"[conform] source package (read-only): {src}")
    if agent == "manual":
        print(f"[conform] manual mode: run the prompt yourself and fill {sb / 'out'}, "
              f"then re-run `conform --root {ctx.root} --agent manual` to CHECK it "
              f"(the postcheck reads {sb / 'out'})")
        return
    cmd = resolve_agent_cmd(agent, getattr(args, "agent_cmd", None))
    rec = {"id": TEMPLATE_REWRITE_DIRNAME, "kind": "template-rewrite", "status": "running",
           "sandbox": str(sb), "round": 0}
    res = _execute_attempt_in(sb, rec, cmd,
                              _timeout_seconds(args, DEFAULTS.get("timeout", 14400)))
    print(f"[conform] agent: {agent} rc={res.get('rc')} in {res.get('dur', 0):.0f}s "
          f"(log: {res.get('log')})")
    if res.get("error"):
        print(f"[conform] WARNING: {res['error']}")
    report = template_rewrite_postcheck(sb, src, templates,
                                        policy=format_policy_of(ctx))
    report.update({"venue": venue_id_of(ctx), "source": str(src), "sandbox": str(sb),
                   "agent": agent, "agent_rc": res.get("rc")})
    write_json_atomic(ctx.reports_dir / "template_rewrite.json", report)
    (ctx.reports_dir / "template_rewrite.md").write_text(
        "# Template-first rewrite\n\n"
        + f"- venue: `{report['venue']}`\n- source: `{report['source']}`\n"
        + f"- sandbox: `{report['sandbox']}`\n- agent: `{report['agent']}` "
          f"(rc={report.get('agent_rc')})\n"
        + f"- documents: {', '.join(report['documents'])}\n"
        + f"- coverage: {report['coverage']['covered']}/{report['coverage']['checked']} "
          f"({report['coverage']['ratio']:.0%}) source paragraph(s) found verbatim\n"
        + f"- template guide sentences left: {len(report['template_prose_left'])}\n"
        + ("\n".join("- ERROR: " + e for e in report["errors"])
           + "\n" if report["errors"] else "- errors: none\n")
        + ("\n".join("- WARNING: " + w for w in report["warnings"])
           + "\n" if report["warnings"] else ""),
        encoding="utf-8")
    print(f"[conform] coverage: {report['coverage']['covered']}/"
          f"{report['coverage']['checked']} ({report['coverage']['ratio']:.0%}) source "
          f"paragraph(s) verbatim; template guide sentences left: "
          f"{len(report['template_prose_left'])}")
    print(f"[conform] report: {(ctx.reports_dir / 'template_rewrite.md')}")
    if not report["ok"]:
        die("the template-first rewrite did not pass its postcheck: "
            + "; ".join(report["errors"])[:400])
    print("[conform] the package in out/ passed the code-side postcheck; it is NOT yet "
          "judged: run the guided-review/revise stages (or a full `run`) when you want it in the round.")
    maybe_track_template_stage(ctx, sb)

def cmd_apply_template(args) -> None:
    """Rebuild a whole submission package inside the venue's Word templates."""
    ctx = Ctx(Path(args.root))
    ctx.load()
    with ctx.lock("conform"):
        templates = venue_word_templates(ctx)
        agent_mode = bool(str(getattr(args, "agent", None) or "").strip())
        if not templates and not agent_mode:
            die(f"the venue {venue_id_of(ctx)!r} ships no official Word template, so there is "
                f"nothing to rebuild from: put the journal's .docx (main + supplementary) under "
                f"{ctx.root}/venue_profiles/{venue_id_of(ctx)}{VENUE_OFFICIAL_SUFFIX}/ and re-run "
                f"`build-venue-templates`/`setup`")
        if not templates:
            print(f"[conform] note: the venue {venue_id_of(ctx)!r} ships no official Word template; "
                  f"the agent session follows the journal's own author guidelines, then academic "
                  f"convention")
        src = Path(args.source).expanduser() if args.source else default_template_package_source(ctx)
        if src is None:
            # A staged transfer/init session is checked against its OWN read-only
            # `source/` copy: `conform --root ... --agent manual` (the check the run
            # banner names) had no package to resolve on a root that has not
            # finished a round yet, so the advertised check could never run.
            staged = ctx.root / TEMPLATE_REWRITE_DIRNAME / "source"
            if staged.is_dir() and any(staged.iterdir()):
                src = staged
        if src is None:
            die("no package to rebuild: the root has no final_clean_version_<root name>/ and no "
                "completed round's round<r>_winner/ -- name one with --source <dir>")
        prof = venue_profile_of(ctx, required=False)
        journal = journal_of(ctx) or (prof.default_journal if prof is not None else "")
        print(f"[conform] venue: {venue_id_of(ctx)}"
              + (f" ({journal})" if journal else " (no journal configured)"))
        if str(getattr(args, "agent", None) or "").strip():
            _template_rewrite_session(ctx, args, src, templates)
            return
        dest = Path(args.dest).expanduser() if args.dest else ctx.root / TEMPLATE_PACKAGE_DIRNAME
        # `--force` recursively deletes THE DESTINATION. Protect the pipeline root:
        # the only destination inside it that may be replaced is the default
        # `<root>/template_package/`; an explicit `--dest <root>` (the confirmed
        # repro) or any other root-owned directory is refused before the deletion.
        protect = () if dest.resolve() == (ctx.root / TEMPLATE_PACKAGE_DIRNAME).resolve() \
            else (ctx.root,)
        report = rebuild_package_from_templates(templates, src, dest, force=bool(args.force),
                                                containers=venue_containers(ctx),
                                                manuscript_names=article_type_manuscript_names(ctx),
                                                protected=protect)
        if not report.get("ok"):
            if report.get("error"):
                die(report["error"])
            die("the rebuild left files un-restyled: " + ", ".join(report.get("failed") or []))
        print(f"[conform] rebuilt {report['documents_rebuilt']} document(s) and copied "
              f"{report['files_copied']} other file(s):")
        for f in report["files"]:
            if f["kind"] == "docx-rebuilt":
                print(f"  [docx] {f['file']}  (template: {Path(str(f.get('template') or '')).name}, "
                      f"text preserved={f.get('text_unchanged')}, "
                      f"headings retagged={len(f.get('headings_retagged') or [])})")
        print(f"[conform] package: {report['dest']}")
        print(f"[conform] report:  {report['dest']}.template_report.md "
              f"(+ .json; written BESIDE the package, never inside it)")
        print(f"[conform] the source package is untouched; every rebuilt document's text is "
              f"proven byte-identical to its source ({DOCX_FORMAT_MODULE} self-verification)")


def cmd_build_venue_templates(args) -> None:
    """Generate the pinned structure-only template pack from a venue's exemplars."""
    vid = str(getattr(args, "venue", None) or "").strip().lower()
    if not vid:
        die("build-venue-templates needs --venue <id>", code=2)
    report = build_venue_templates(vid, root=getattr(args, "root", None),
                                   profiles_dir=getattr(args, "profiles_dir", None),
                                   exemplar_dir=getattr(args, "exemplars", None))
    if not report.get("exemplars") and not report.get("official"):
        looked = report.get("looked") or [
            str(d) for d in venue_exemplar_dirs(vid, getattr(args, "root", None))]
        print(f"[build-venue-templates] venue {vid}: no readable official template and no "
              f"readable exemplars"
              + (f" (looked under {', '.join(looked)})" if looked else ""))
        for s in report.get("skipped") or []:
            print(f"  - skipped {s['file']}: {s['why']}")
        store = (Path(getattr(args, "profiles_dir", None)).resolve()
                 if getattr(args, "profiles_dir", None)
                 else venue_profiles_write_dir(getattr(args, "root", None)))
        print(f"  put OA article transcriptions in {store}/{vid}{VENUE_EXEMPLAR_SUFFIX}/ "
              f"and/or the journal's unzipped template files in "
              f"{store}/{vid}{VENUE_OFFICIAL_SUFFIX}/ and re-run")
        raise SystemExit(2)
    print(f"[build-venue-templates] venue {vid}: {report.get('official', 0)} official template "
          f"file(s), {report['exemplars']} exemplar(s) -> {report['pack']}")
    if report.get("official_archives") and not report.get("official"):
        print(f"[build-venue-templates] WARNING: {len(report['official_archives'])} archive(s) "
              f"are present but no extracted template file was parsed -- UNZIP the archive(s) "
              f"({', '.join(report['official_archives'])}) and re-run")
    print(f"[build-venue-templates] skeleton sections: "
          + (", ".join(report["norm_sections"]) or "(none detected)"))
    if report.get("mandatory_sections"):
        print(f"[build-venue-templates] MANDATORY (official): "
              + ", ".join(report["mandatory_sections"]))
    for s in report.get("skipped") or []:
        print(f"[build-venue-templates] skipped {s['file']}: {s['why']}")
    print(f"[build-venue-templates] files: {', '.join(report['files'])}; "
          f"every input and output is sha256-pinned in {VENUE_PACK_MANIFEST}")


def cmd_add_venue(args) -> None:
    """Create/update a venue profile and download its exemplars, with an agent."""
    vid = str(getattr(args, "venue", None) or "").strip().lower()
    if not VENUE_ID_RE.match(vid or ""):
        die(f"add-venue needs a slug venue id (letters, digits, '.', '_', '+', '-'): "
            f"got {vid!r}", code=2)
    dest = Path(getattr(args, "profiles_dir", None)
                or venue_profiles_write_dir(getattr(args, "root", None))).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[add-venue] venue: {vid}")
    print(f"[add-venue] store: {dest}")
    publish_only = bool(getattr(args, "publish_only", False)) or \
        bool(str(getattr(args, "from_sandbox", "") or "").strip())
    if publish_only:
        from_sb = str(getattr(args, "from_sandbox", "") or "").strip()
        sb = Path(from_sb).resolve() if from_sb else latest_add_venue_sandbox(dest, vid)
        if sb is None or not sb.is_dir():
            die(f"add-venue --publish-only: no staged sandbox found under "
                f"{dest / '.add-venue'} for {vid!r}; pass --from-sandbox DIR")
        print(f"[add-venue] publish-only: staging sandbox {sb}")
    else:
        # Microseconds plus a short random suffix: a second-resolution stamp let
        # two add-venue sessions for one id in the same second share (and
        # overwrite) one staging directory.
        stamp = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                 + "-" + os.urandom(3).hex())
        sb = dest / ".add-venue" / f"{vid}-{stamp}"
        sb.mkdir(parents=True, exist_ok=True)
        prompt = add_venue_prompt(vid, dest, journal=str(getattr(args, "journal", None) or ""),
                                  article_type=str(getattr(args, "article_type", None) or ""),
                                  want_download=not bool(getattr(args, "no_download", False)))
        (sb / PROMPT_FILE).write_text(prompt, encoding="utf-8")
        if bool(getattr(args, "no_download", False)):
            print("[add-venue] note: --no-download: the prompt asks for the profile + README row "
                  "ONLY; supply exemplars in "
                  f"{dest / (vid + VENUE_EXEMPLAR_SUFFIX)}/ and run "
                  f"`build-venue-templates --venue {vid}` when ready")
        print(f"[add-venue] prompt: {sb / PROMPT_FILE}")
        agent = str(getattr(args, "agent", None) or DEFAULTS.get("agent", "codex"))
        if agent == "manual":
            print(f"[add-venue] manual mode: run the prompt yourself, then re-run "
                  f"`add-venue {vid} --publish-only` (or `build-venue-templates --venue {vid}`) "
                  f"to validate and generate the template pack")
            return
        cmd = resolve_agent_cmd(agent, getattr(args, "agent_cmd", None))
        rec = {"id": f"add-venue_{vid}", "kind": "add-venue", "status": "running",
               "sandbox": str(sb), "round": 0}
        res = _execute_attempt_in(sb, rec, cmd, _timeout_seconds(args, 3600))
        print(f"[add-venue] agent rc={res.get('rc')} in {res.get('dur', 0):.0f}s "
              f"(log: {res.get('log')})")
        if res.get("error"):
            print(f"[add-venue] WARNING: {res['error']}")
    # The agent works in a sandbox that can only write inside itself; the
    # orchestrator publishes the staged store layout into the shared store.
    # VALIDATE BEFORE PUBLISH: a bad agent-written profile must never replace
    # the store's copy (the shipped default is read at import, so publishing an
    # invalid one could brick every later command, including the repair tools).
    staged_profile = next((r / f"{vid}{VENUE_PROFILE_SUFFIX}" for r in (sb / "store", sb)
                           if (r / f"{vid}{VENUE_PROFILE_SUFFIX}").is_file()), None)
    if staged_profile is not None:
        try:
            VenueProfile(json.loads(staged_profile.read_text(encoding="utf-8")),
                         origin="add-venue", path=staged_profile)
        except (OSError, ValueError, VenueProfileError) as e:
            die(f"add-venue: the staged profile {staged_profile.name} does not validate "
                f"({e}); nothing was published to {dest}", code=1)
    pub = publish_add_venue_staging(sb, dest, vid)
    print(f"[add-venue] staged artifacts published: profile={pub['profile'] or 'MISSING'}, "
          f"README={pub['readme']}, official files={pub['official_files']}, "
          f"exemplar files={pub['manuscript_files']}")
    for note in pub.get("notes") or []:
        print(f"[add-venue] staged note: {note}")
    if vid in BUILTIN_VENUE_PROFILES:
        try:
            _published = json.loads((dest / f"{vid}{VENUE_PROFILE_SUFFIX}")
                                    .read_text(encoding="utf-8"))
            _builtin = BUILTIN_VENUE_PROFILES[vid]
            if (json.dumps(_published, sort_keys=True)
                    != json.dumps(_builtin, sort_keys=True)):
                print(f"[add-venue] NOTE: {vid!r} also has a BUILT-IN fallback and the shipped "
                      f"file now differs from it. A root with NO venue_profiles/{vid}.json "
                      f"keeps the built-in rules; sync BUILTIN_VENUE_PROFILES (or delete the "
                      f"shipped file) if the update should be the default everywhere.")
        except (OSError, ValueError):
            pass
    profile_path = dest / f"{vid}{VENUE_PROFILE_SUFFIX}"
    problems = []
    if not profile_path.is_file():
        problems.append(f"{profile_path.name} was not written")
    else:
        try:
            VenueProfile(json.loads(profile_path.read_text(encoding="utf-8")),
                         origin="add-venue", path=profile_path)
        except (OSError, ValueError, VenueProfileError) as e:
            problems.append(f"{profile_path.name} does not validate: {e}")
    readme = dest / "README.md"
    if readme.is_file() and vid not in readme.read_text(encoding="utf-8", errors="replace"):
        problems.append(f"{readme.name} has no row mentioning {vid!r}")
    # The store IS the venue_profiles dir here: the exemplar corpus sits next to
    # the profile, not under another venue_profiles/ level.
    ex_dir = dest / f"{vid}{VENUE_EXEMPLAR_SUFFIX}"
    n_exemplars = len(_exemplar_files(ex_dir)) if ex_dir.is_dir() else 0
    off_dir = dest / f"{vid}{VENUE_OFFICIAL_SUFFIX}"
    n_official = len(_exemplar_files(off_dir)) if off_dir.is_dir() else 0
    if problems:
        print("[add-venue] PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
    if n_exemplars == 0 and n_official == 0:
        print(f"[add-venue] WARNING: neither official templates ({off_dir}) nor exemplars "
              f"({ex_dir}) landed; the template pack was NOT generated "
              f"(the profile part still stands)")
        raise SystemExit(1 if problems else 0)
    report = build_venue_templates(vid, profiles_dir=dest)
    print(f"[add-venue] templates: {report.get('pack')} "
          f"({report.get('official', 0)} official template file(s), "
          f"{report.get('exemplars')} exemplar(s)"
          + (f"; class: {report['documentclass']}" if report.get("documentclass") else "")
          + f"; sections: {', '.join(report.get('norm_sections') or []) or '(none detected)'})")
    if report.get("official_archives") and not report.get("official"):
        print(f"[add-venue] WARNING: {len(report['official_archives'])} official template "
              f"archive(s) landed but no extracted file was parsed -- UNZIP them "
              f"({', '.join(report['official_archives'])}) and re-run "
              f"`build-venue-templates --venue {vid}`")
    if report.get("mandatory_sections"):
        print(f"[add-venue] MANDATORY sections (official template): "
              f"{', '.join(report['mandatory_sections'])}")
    print(f"[add-venue] the official template is AUTHORITATIVE; the recent-practice norm is "
          f"ADVISORY, and the venue profile's own guidelines win over both")
    raise SystemExit(1 if problems else 0)


def cmd_set_tiebreak_defect_floor(args) -> None:
    """Set (or show) the adaptive defect-prefix floor of an existing root.

    The floor is the number of defects the CLEANEST ranked version must reach
    before the severity_tier_category walk stops; it takes effect on the next
    round decided by `run` (past decisions keep the key they were made with).
    """
    ctx = Ctx(_venue_command_root(args, "set-tiebreak-defect-floor"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    value = getattr(args, "floor", None)
    show = bool(getattr(args, "show", False)) or value is None
    if show:
        print(f"[set-tiebreak-defect-floor] floor: {tiebreak_defect_floor_of(ctx)} "
              f"(default {DEFAULT_TIEBREAK_DEFECT_FLOOR}; 0 = the EMPTY prefix (no "
              f"census cell leads), so the median/mean/IQR/digest decide; a huge value such "
              f"as 999999 uses every cell)")
        return
    try:
        floor = int(value)
    except (TypeError, ValueError):
        die(f"set-tiebreak-defect-floor needs an integer >= 0 (got {value!r})", code=2)
    if floor < 0:
        die("the tie-break defect floor must be >= 0", code=2)
    begin_run_log("set-tiebreak-defect-floor", ctx.root, sys.argv)
    if ctx.state.get("runs") and not getattr(args, "force", False):
        die(f"this root already has {len(ctx.state['runs'])} run record(s): the floor changes how "
            f"a future round is decided.\n"
            f"       Re-run `set-tiebreak-defect-floor {floor} --force` if the change is intended.")
    with ctx.lock("set-tiebreak-defect-floor"):
        ctx.cfg["tiebreak_defect_floor"] = floor
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-tiebreak-defect-floor", detail=str(floor))
        ctx.save_state()
    print(f"[set-tiebreak-defect-floor] floor: {floor} (the severity_tier_category walk stops "
          f"when the cleanest ranked version reaches {floor} defect(s), or when every cell is "
          f"used)")


def cmd_set_cold_start_review(args) -> None:
    """Set (or show) the COLD-START REVIEW policy of an existing root.

    "on" plans one extra independent session per full-scope round (see
    `--cold-start-review`); "off" is the off switch. The change takes effect for
    rounds whose review has not been materialized yet -- a round already in
    flight keeps the plan it started with, and a finished probe run keeps its
    record. Like every plan-shaping policy, it refuses to change a root that
    already has run records unless `--force` is given.
    """
    ctx = Ctx(_venue_command_root(args, "set-cold-start-review"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    mode_arg = str(getattr(args, "mode", None) or "").strip().lower()
    show = bool(getattr(args, "show", False)) or not mode_arg
    if show:
        print(f"[set-cold-start-review] cold-start review: {cold_start_review_of(ctx)} "
              f"(a root without the key plans none; `on` adds one independent discovery session "
              f"beside each full-scope round's review, with every declared verifier re-run by "
              f"the orchestrator)")
        return
    if mode_arg not in COLD_START_REVIEW_MODES:
        die(f"set-cold-start-review needs one of {', '.join(COLD_START_REVIEW_MODES)} (got {mode_arg!r})",
            code=2)
    if mode_arg == "on" and journal_is_scoped(ctx):
        # A concern-scoped revision may edit only the admitted concerns: a
        # general discovery probe would add X-9xx findings that are not
        # reviewer concerns. Setup already forces the policy off; the setter
        # must not reopen the hole.
        die("cold_start_review is fixed off in a concern-scoped revision mode "
            f"({journal_mode_of(ctx)}): the cold-start review is a general discovery pass and "
            "its findings are not reviewer concerns", code=2)
    if mode_arg == "off" and not guided_review_enabled(ctx):
        # `--no-guided-review` leaves the cold-start review as the round's ONLY
        # finding source; turning it off here would leave the plan with none
        # (setup already refuses the same combination) (F05).
        die("cold_start_review cannot be turned off on a --no-guided-review root: the "
            "cold-start review is the round's only finding source. Turn the guided review "
            "back on first, or start a fresh root with both policies as intended", code=2)
    begin_run_log("set-cold-start-review", ctx.root, sys.argv)
    if ctx.state.get("runs") and not getattr(args, "force", False):
        die(f"this root already has {len(ctx.state['runs'])} run record(s): the cold-start "
            f"review policy "
            f"changes a future round's plan.\n"
            f"       Re-run `set-cold-start-review {mode_arg} --force` if the change is intended "
            f"(rounds whose review has not been materialized yet will use it).")
    with ctx.lock("set-cold-start-review"):
        ctx.cfg["cold_start_review"] = mode_arg
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-cold-start-review", detail=mode_arg)
        ctx.save_state()
    detail = ("one cold-context independent discovery session per full-scope round, findings "
              "X-9xx, every declared verifier re-run at postcheck time" if mode_arg == "on"
              else "no cold-start session is planned")
    print(f"[set-cold-start-review] cold-start review: {mode_arg} ({detail})")


def cmd_set_submit_code(args) -> None:
    """Set (or show) whether the analysis-code area is part of the submission.

    "off" (the default, and the behaviour of every root created before this
    policy existed) strips `code/` from `journal_submission/` exactly like the
    evidence areas and rejects a response letter that cites a `code/` path;
    "on" submits the area instead (the copy carries `code/`, and citing it is
    legal). The area stays revision CONTENT either way -- a stage may revise it
    and the judges evaluate it -- and flipping the policy can never change a
    pin, a score or a champion: it only decides what the NEXT assembly of
    `journal_submission/` carries (a plain `run` re-assembles it once the
    revision is complete).
    """
    ctx = Ctx(_venue_command_root(args, "set-submit-code"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    mode_arg = str(getattr(args, "mode", None) or "").strip().lower()
    show = bool(getattr(args, "show", False)) or not mode_arg
    if show:
        print(f"[set-submit-code] code/ in the submission: "
              f"{'on' if submit_code_of(ctx) else 'off'} "
              f"(off strips the analysis-code area from journal_submission/ and refuses a "
              f"response letter that cites it; on ships it)")
        return
    if mode_arg not in SUBMIT_CODE_MODES:
        die(f"set-submit-code needs one of {', '.join(SUBMIT_CODE_MODES)} (got {mode_arg!r})",
            code=2)
    begin_run_log("set-submit-code", ctx.root, sys.argv)
    with ctx.lock("set-submit-code"):
        ctx.cfg["submit_code"] = mode_arg
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-submit-code", detail=mode_arg)
        ctx.save_state()
    detail = ("`code/` ships in the submission package and a response letter may cite it"
              if mode_arg == "on" else
              "`code/` is stripped from the submission package and a response letter may not "
              "cite it")
    print(f"[set-submit-code] code/ in the submission: {mode_arg} ({detail}; the next plain "
          f"`run` re-assembles journal_submission/ once the revision is complete)")


def cmd_set_author_to_complete(args) -> None:
    """Set (or show) where the stages put "[AUTHOR TO COMPLETE ...]" hand-off items.

    "readme" (the default) forbids the literal token in every document and records
    each missing item in ONE `README-AUTHOR-TO-COMPLETE.md` in the package root,
    beside the cover letter and main text. The README is the author's checklist
    and is never submitted (README*.md is dropped, rule 9).

    "document" (`--author-to-complete document`) keeps the
    in-document marker convention: a missing item is scaffolded with the literal
    marker and listed for the author.

    "off" (`--author-to-complete off`) forbids the token in every file the
    stages write: the item is left out of the document -- a whole missing file is
    not scaffolded as a document of instructions -- and recorded in the package's
    own MANUAL_STEPS.md / CHANGELOG.md instead. Outside "document", a marker that
    is still present in a delivered package is a DEFECT of that package.

    Flipping the policy never changes a pin, a score or a champion, and it never
    changes what is TRUE about the package: the underlying gap counts exactly as
    it did (AGENTS.md rule 5). It changes two things only -- what the stage
    prompts instruct, and whether a shipped marker is a defect.
    """
    ctx = Ctx(_venue_command_root(args, "set-author-to-complete"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    mode_arg = str(getattr(args, "mode", None) or "").strip().lower()
    show = bool(getattr(args, "show", False)) or not mode_arg
    if show:
        mode = author_to_complete_mode_of(ctx)
        how = {
            "document": ("a missing mandatory item is scaffolded with the literal "
                         f"{PLACEHOLDER_TOKEN}: ...] marker and listed for the author"),
            "readme": ("no document carries the marker: each missing item is recorded in "
                       f"{AUTHOR_TO_COMPLETE_README} in the package root (never submitted)"),
            "off": ("no file carries the marker: the item is left out of the document and "
                    "recorded in MANUAL_STEPS.md"),
        }[mode]
        print(f"[set-author-to-complete] hand-off items: {mode} ({how})")
        return
    # Reject anything outside the current mode names BEFORE normalising:
    # `_atc_mode` maps an unknown value to the default, which would silently turn
    # a typo into `readme` and report success for a policy the operator did not
    # ask for.
    if mode_arg not in AUTHOR_TO_COMPLETE_MODES:
        die(f"set-author-to-complete needs one of "
            f"{', '.join(AUTHOR_TO_COMPLETE_MODES)}; got {mode_arg!r}", code=2)
    mode_arg = _atc_mode(mode_arg)
    begin_run_log("set-author-to-complete", ctx.root, sys.argv)
    with ctx.lock("set-author-to-complete"):
        ctx.cfg["author_to_complete"] = mode_arg
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-author-to-complete", detail=mode_arg)
        ctx.save_state()
    detail = {
        "document": ("the stages mark a missing mandatory item with the literal "
                     "\"[AUTHOR TO COMPLETE: ...]\" token and list it for the author (the "
                     "marker is a hand-off, never a defect)"),
        "readme": ("no document carries the marker; each missing item goes to "
                   f"{AUTHOR_TO_COMPLETE_README} beside the cover letter and main text "
                   "(never submitted), and a marker still present in a delivered package is "
                   "a defect"),
        "off": ("no file carries the marker; the item is left out of the document and "
                "recorded in MANUAL_STEPS.md, and a marker still present in a delivered "
                "package is a defect"),
    }[mode_arg]
    print(f"[set-author-to-complete] hand-off items: {mode_arg} ({detail}; the next plain "
          f"`run` writes its prompts under the new policy)")


def cmd_set_placeholder_file(args) -> None:
    """Add, clear or show the root's PLACEHOLDER-FILE declarations.

    A placeholder is a corpus file that stands in for data it does not contain
    -- the operator's example: "the haplotypes in Chisel ACT are actually the
    HG008 haplotypes (placeholders)". Placeholder files are IGNORED as evidence:
    the evidence pack lists them, no session may cite one as a producer, and a
    claim resting only on one is reported as unverified. Nothing is deleted; the
    declaration only says how to read the file.

    `set-placeholder-file 'raw_data/**/ACT*hap*'` adds a declaration (a
    package-relative path or a glob, matched against the path and the bare file
    name); `--clear` removes them all; no operand with `--show` prints the
    current list and how many files each pattern resolves to.
    """
    ctx = Ctx(_venue_command_root(args, "set-placeholder-file"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    patterns = [str(x).strip() for x in (getattr(args, "patterns", None) or [])
                if str(x).strip()]
    current = [str(x) for x in ((ctx.cfg or {}).get("placeholder_files") or [])]
    if bool(getattr(args, "clear", False)):
        with ctx.lock("set-placeholder-file"):
            ctx.cfg["placeholder_files"] = []
            ctx.state["config"] = ctx.cfg
            write_json_atomic(ctx.cfg_path, ctx.cfg)
            ctx.log("set-placeholder-file", detail="cleared")
            ctx.save_state()
        print("[set-placeholder-file] cleared (no file is treated as a placeholder)")
        return
    # The declarations name PACKAGE-relative paths; on an existing root the
    # package that carries them is the pristine copy (non_revised/), so the
    # report resolves them there rather than against the bookkeeping root.
    pkg_root = ctx.root / PRISTINE_DIR if (ctx.root / PRISTINE_DIR).is_dir() else ctx.root
    if not patterns:
        report = placeholder_files_report(
            pkg_root, extra_globs=current,
            area_names=submission_not_carried_areas(ctx))
        print(f"[set-placeholder-file] declared pattern(s): "
              f"{', '.join(current) if current else '(none)'}")
        if report.get("declared"):
            print("[set-placeholder-file] files treated as placeholders (ignored as evidence):")
            for rel in report["declared"]:
                print(f"  - {rel}: {report['reasons'].get(rel, 'declared')}")
        if report.get("detected_copies"):
            print("[set-placeholder-file] detected placeholder copies (identical bytes under "
                  "another sample/dataset name):")
            for row in report["detected_copies"][:20]:
                print(f"  - {row['file']} duplicates {row['duplicates']}")
        return
    merged = []
    for pat in current + patterns:
        if pat not in merged:
            merged.append(pat)
    begin_run_log("set-placeholder-file", ctx.root, sys.argv)
    with ctx.lock("set-placeholder-file"):
        ctx.cfg["placeholder_files"] = merged
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-placeholder-file", detail=", ".join(merged))
        ctx.save_state()
    report = placeholder_files_report(pkg_root, extra_globs=merged,
                                      area_names=submission_not_carried_areas(ctx))
    print(f"[set-placeholder-file] declared {len(merged)} pattern(s); "
          f"{len(report.get('declared') or [])} file(s) resolve to a placeholder and are "
          f"ignored as evidence: "
          + (", ".join(report.get("declared") or []) or "(none yet -- the pattern matches no "
             "carried file; the next `run` re-checks it)"))


def cmd_set_dedup_mode(args) -> None:
    """Set (or show) the issue-census dedup mode of an existing root.

    "off" (the default) counts every judge sheet's rows as separate mentions --
    the mode every existing root was decided with. "location" additionally
    merges rows ACROSS sheets on the structured key (the NORMALIZED CHECK ID the
    sheet cites -- `M01`/`M02`/... are examples, never a closed set -- + exact
    line number + >= 7-word excerpt, token-set Jaccard >= DEDUP_FUZZY_THRESHOLD);
    the change takes effect on the next round decided by `run`, and every merge is
    recorded in reports/round<r>_dedup_audit.json.
    """
    ctx = Ctx(_venue_command_root(args, "set-dedup-mode"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    mode_arg = str(getattr(args, "mode", None) or "").strip().lower()
    show = bool(getattr(args, "show", False)) or not mode_arg
    if show:
        print(f"[set-dedup-mode] mode: {dedup_mode_of(ctx)} (default off; 'location' merges "
              f"rows across sheets on the normalized check id (any id works; M01/M02 are "
              f"examples) + exact line number + a >= "
              f"{DEDUP_MIN_WORDS}-word excerpt with token-set Jaccard >= "
              f"{DEDUP_FUZZY_THRESHOLD:g})")
        return
    if mode_arg not in DEDUP_MODES:
        die(f"set-dedup-mode needs one of {', '.join(DEDUP_MODES)} (got {mode_arg!r})", code=2)
    begin_run_log("set-dedup-mode", ctx.root, sys.argv)
    if ctx.state.get("runs") and not getattr(args, "force", False):
        die(f"this root already has {len(ctx.state['runs'])} run record(s): the dedup mode "
            f"changes how a future round's census counts issues.\n"
            f"       Re-run `set-dedup-mode {mode_arg} --force` if the change is intended.")
    with ctx.lock("set-dedup-mode"):
        ctx.cfg["dedup_mode"] = mode_arg
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-dedup-mode", detail=mode_arg)
        ctx.save_state()
    detail = ("every sheet's rows are separate mentions" if mode_arg == "off"
              else "rows across sheets merge on the structured location key")
    print(f"[set-dedup-mode] mode: {mode_arg} ({detail})")


def cmd_set_champion_select(args) -> None:
    """Set (or show) how a future round's champion is chosen.

    This is the persisted counterpart of `run/decide --champion-select`: an
    existing root can switch to the no-judge `revise`/`integrate` modes without
    re-running setup. A decided round keeps the mode it recorded; the change
    plans the rounds that have not run yet.
    """
    ctx = Ctx(_venue_command_root(args, "set-champion-select"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    mode_arg = str(getattr(args, "mode", None) or "").strip().lower()
    show = bool(getattr(args, "show", False)) or not mode_arg
    if show:
        print(f"[set-champion-select] mode: {champion_select_of(ctx)} "
              f"(judge = the relative-judgment panel; revise = promote a2; integrate = "
              f"promote i<M+2>; the no-judge modes are PROVISIONAL and need N=1)")
        return
    if mode_arg not in CHAMPION_SELECT_MODES:
        die(f"set-champion-select needs one of {', '.join(CHAMPION_SELECT_MODES)} "
            f"(got {mode_arg!r})", code=2)
    if ctx.state.get("runs") and not getattr(args, "force", False):
        die(f"this root already has {len(ctx.state['runs'])} run record(s): the champion-"
            f"selection mode changes how future rounds are decided.\n"
            f"       Re-run `set-champion-select {mode_arg} --force` if the change is intended.")
    if mode_arg in ("revise", "integrate"):
        if journal_is_scoped(ctx) and mode_arg == "integrate":
            die(f"set-champion-select integrate has no meaning in revision mode "
                f"{journal_mode_of(ctx)!r}: a concern-scoped revision already promotes its "
                f"single revised candidate and runs no integration arm", code=2)
        _rounds = ctx.rounds_count()
        _rewrites = counts_of(ctx.cfg, "rewrites", _rounds)
        _revises = counts_of(ctx.cfg, "revises", _rounds)
        _masks = masks_of(ctx.cfg, "integrators", _rounds)
        _enabled = []
        for _i, (_m, _n, _mask) in enumerate(zip(_rewrites, _revises, _masks), 1):
            if _n != 1:
                die(f"set-champion-select {mode_arg} needs exactly ONE revise arm in every "
                    f"round, but round {_i} plans N={_n}; fix `revises` first", code=2)
            if mode_arg == "integrate":
                _arm = _m + 2
                if not ((_mask >> (_arm - 1)) & 1):
                    _mask |= 1 << (_arm - 1)
                    _masks[_i - 1] = _mask
                    _enabled.append((_i, integrate_vid(_arm), _mask))
        if _enabled:
            ctx.cfg["integrators"] = _masks
            print("[set-champion-select] integrate enables the promoted integration arm: "
                  + ", ".join(f"round {i} -> {vid} (mask 0x{mask:X})"
                              for i, vid, mask in _enabled))
    begin_run_log("set-champion-select", ctx.root, sys.argv)
    with ctx.lock("set-champion-select"):
        ctx.cfg["champion_select"] = mode_arg
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-champion-select", detail=mode_arg)
        ctx.save_state()
    print(f"[set-champion-select] mode: {mode_arg}"
          + ("" if mode_arg == "judge" else " (PROVISIONAL: no judge panel)"))


def _adopt_sweep_source(arg: str) -> Path:
    """The new_sweeps.md a `--proposals` argument names (a file or a sandbox)."""
    p = Path(str(arg)).expanduser()
    if p.is_dir():
        for rel in ("guided_review/round2/new_sweeps.md", "new_sweeps.md"):
            if (p / rel).is_file():
                return p / rel
        die(f"{p} carries no guided_review/round2/new_sweeps.md (nor a bare new_sweeps.md): pass the "
            f"proposal file or a review sandbox root", code=2)
    return p


def cmd_adopt_sweep(args) -> None:
    """`adopt-sweep`: validate a discovery proposal file; with --yes, append it.

    D5's proposals used to die in guided_review/round2/new_sweeps.md ("the orchestrator
    ARCHIVES that file for you but does not apply the proposals itself"), so in
    an unattended chain of runs a discovered class could be re-discovered
    forever. This command is the adoption step: it parses the proposal blocks,
    refuses anything that is not sweeps.md-shaped or does not continue the
    numbering, checks the target for collisions, and (with --yes) appends the
    validated blocks to the skill's `references/sweeps.md` while re-syncing the
    standalone review prompt's appendix to it (validate_skill.py's D10).
    """
    src = _adopt_sweep_source(getattr(args, "proposals", ""))
    if not src.is_file():
        die(f"--proposals {src} is not a file", code=2)
    sweeps = (Path(str(args.sweeps)).expanduser() if getattr(args, "sweeps", None) else
              Path(__file__).resolve().parent / "paper-skills" / "paper-review"
              / "references" / "sweeps.md")
    if not sweeps.is_file():
        die(f"the target sweeps.md {sweeps} does not exist (pass --sweeps PATH)", code=2)
    try:
        text = src.read_text(encoding="utf-8", errors="replace")
        cur = sweeps.read_text(encoding="utf-8", errors="replace")
    except OSError as e:                                          # noqa: BLE001
        die(f"could not read {src} / {sweeps}: {e}", code=2)
    proposals, problems = parse_sweep_proposals(text)
    if not proposals:
        if DISCOVERY_NO_PROPOSAL_RE.search(text):
            print(f"[adopt-sweep] {src}: no new-sweep proposals (the file says so); nothing "
                  f"to adopt")
            return
        print(f"[adopt-sweep] {src} carries no `## M<NN> -- <name>` proposal block")
        raise SystemExit(1)
    problems += adopt_sweep_problems(proposals, cur)
    print(f"[adopt-sweep] {src}: {len(proposals)} proposal(s) -> {sweeps}")
    for sid, name, _block in proposals:
        print(f"  - {sid}: {name}")
    if problems:
        print(f"[adopt-sweep] REFUSED: {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)
    if not getattr(args, "yes", False):
        print("[adopt-sweep] dry run: nothing was written. Re-run with --yes to append the "
              "proposal(s) to sweeps.md and re-sync the standalone prompt's appendix.")
        return

    def _adopted(block: str) -> str:
        lines = block.rstrip("\n").split("\n")
        lines[0] = re.sub(r"\s*[\(\[]proposed[\)\]]\s*$", "", lines[0]).rstrip()
        return "\n".join(lines)

    new_text = (cur.rstrip("\n") + "\n\n"
                + "\n\n".join(_adopted(b) for _sid, _name, b in proposals) + "\n")
    write_text_atomic(sweeps, new_text)
    note = resync_sweeps_appendix(sweeps, new_text)
    print(f"[adopt-sweep] appended {len(proposals)} proposal(s) to {sweeps}")
    print(f"[adopt-sweep] {note}")
    print("[adopt-sweep] follow-ups: the review now runs the new sweep id(s), so their coverage "
          "rows, artifacts and finding rules must be implemented in the review skill + prompts "
          "(and a regression test added) before the next round; `selfcheck`/`validate_skill.py` "
          "will report any inconsistency.")


def _freeze_journal_feedback(root: Path, src: Path) -> str:
    """Freeze one journal-feedback file INSIDE `root`; return a root-relative path.

    AGENTS.md rule 11: a root may read only files it carries. An operator-named
    letter outside `--source` used to be stored as an absolute path in
    pipeline_config.json, so editing/moving/deleting it later silently changed
    what the root consumed. A file already under the root keeps its path; an
    external one is copied to `<root>/frozen_feedback/` under a content-stable
    name and the stored path points there.
    """
    root = root.resolve()
    src = Path(src).resolve()
    if is_within(src, root):
        return src.relative_to(root).as_posix()
    dest_dir = root / "frozen_feedback"
    dest_dir.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:8]
    dest = dest_dir / f"{src.stem}-{tag}{src.suffix}"
    # A deterministic destination name can be pre-created as a symlink; both
    # `is_file()` and `copy2` followed it, so the operator's letter was written
    # through the link and the "frozen" input stayed a live link (F35). Replace
    # the entry itself, atomically, through a reserved descriptor.
    if dest.is_symlink() or not dest.is_file() \
            or sha256_file(dest) != sha256_file(src):
        def _copy_feedback(f, _src=src):
            with open(_src, "rb") as src_file:
                shutil.copyfileobj(src_file, f)

        _atomic_write_bytes(tmp_path_for(dest), dest, _copy_feedback, binary=True)
    return dest.relative_to(root).as_posix()


def cmd_set_revision_mode(args) -> None:
    """Set (or show) the journal revision mode of an existing root.

    `continue` restores the historical pipeline. Switching to major/minor
    normalises the round plan to what that mode permits (rewrites 0, one
    revision arm, no integration, one round) and says so. Switching to
    transfer/resubmit only records the mode: the standard rounds still apply,
    with the journal feedback added as an input. `init` records the mode and
    runs the conform (template-first) stage before round 1 -- no feedback.
    `llm` records the LLM-review mode. A corpus that merely carries a non-empty
    `llm_review_feedback/` does not select it.
    """
    ctx = Ctx(_venue_command_root(args, "set-revision-mode"),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    mode_arg = str(getattr(args, "mode", None) or "").strip().lower()
    show = bool(getattr(args, "show", False)) or not mode_arg
    if show:
        mode = journal_mode_of(ctx)
        info = JOURNAL_MODES[mode]
        feedback = [str(p) for p in ((ctx.cfg or {}).get("journal_feedback") or [])]
        print(f"[set-revision-mode] mode: {mode} (option {info['option']}) -- {info['label']}")
        print(f"[set-revision-mode] response to reviewers: "
              f"{'required' if info['response'] else 'not written'}; "
              f"rewrites: {'allowed' if info['rewrites'] else 'forbidden'}; "
              f"edits: {'concern-scoped only' if info['scoped'] else 'the full review findings'}")
        if info.get("feedback"):
            if mode == JOURNAL_MODE_LLM:
                print("[set-revision-mode] feedback source: llm_review_feedback/ only "
                      "(false positives pre-filtered); no journal decision letter is read")
            else:
                print(f"[set-revision-mode] feedback from: "
                      f"{(ctx.cfg or {}).get('journal_feedback_from') or '(not set)'}; "
                      f"named feedback file(s): "
                      f"{', '.join(feedback) if feedback else '(not set)'}")
            llm_hits = [label for _p, label in journal_llm_feedback_files(ctx)]
            print(f"[set-revision-mode] LLM review file(s): "
                  f"{', '.join(llm_hits) if llm_hits else '(none found)'}")
        elif mode != JOURNAL_MODE_CONTINUE:
            print("[set-revision-mode] this mode reads no journal feedback and writes no "
                  "response letter")
        return
    mode_arg = normalize_revision_mode(mode_arg)
    if mode_arg not in JOURNAL_MODES:
        die(f"set-revision-mode needs one of {', '.join(JOURNAL_MODES)} (got {mode_arg!r}): "
            f"continue (the historical workflow, the pipeline's own guided-review/revise rounds) / "
            f"init (conform into the venue template first, "
            f"then the pipeline's own rounds) / transfer (option 1) / resubmit (option 2) / "
            f"major (option 3) / minor (option 4) / llm (option 5: the pre-filtered "
            f"{LLM_FEEDBACK_DIR}/ review only)", code=2)
    begin_run_log("set-revision-mode", ctx.root, sys.argv)
    if ctx.state.get("runs") and not getattr(args, "force", False):
        die(f"this root already has {len(ctx.state['runs'])} run record(s): the revision mode "
            f"decides which stages those runs were built for.\n"
            f"       Re-run `set-revision-mode {mode_arg} --force` if the change is intended.")
    named = [str(x) for x in (getattr(args, "journal_feedback", None) or []) if str(x).strip()]
    info = JOURNAL_MODES[mode_arg]
    _named_resolved = []
    for item in named:
        q = Path(item)
        if not q.is_absolute():
            root_rel = ctx.root / q
            q = root_rel if root_rel.exists() else (Path.cwd() / q)
        if not q.is_file():
            die(f"--journal-feedback {item!r} does not exist (looked for {q}).")
        if info["feedback"] and mode_arg != JOURNAL_MODE_LLM:
            # Freeze an external letter into the root and store it root-relative;
            # the root must not read a mutable path outside itself (rule 11).
            _named_resolved.append(_freeze_journal_feedback(ctx.root, q))
        else:
            _named_resolved.append(str(q))
    named = _named_resolved
    if named and not info["feedback"]:
        print(f"[set-revision-mode] note: mode {mode_arg!r} reads no journal feedback; "
              f"--journal-feedback/--journal-feedback-from are ignored")
    if mode_arg == JOURNAL_MODE_LLM and (named or getattr(args, "journal_feedback_from", None)):
        print(f"[set-revision-mode] note: mode {JOURNAL_MODE_LLM!r} reads ONLY "
              f"{LLM_FEEDBACK_DIR}/; --journal-feedback/--journal-feedback-from are ignored")
    with ctx.lock("set-revision-mode"):
        _prev_mode = journal_mode_of(ctx)
        ctx.cfg["revision_mode"] = mode_arg
        if named and info["feedback"] and mode_arg != JOURNAL_MODE_LLM:
            ctx.cfg["journal_feedback"] = named
        if getattr(args, "journal_feedback_from", None) and info["feedback"] \
                and mode_arg != JOURNAL_MODE_LLM:
            ctx.cfg["journal_feedback_from"] = str(args.journal_feedback_from).strip()
        forced = []
        if info["scoped"]:
            if _prev_mode not in (JOURNAL_MODE_MAJOR, JOURNAL_MODE_MINOR):
                # Remember the operator's own policies before the scoped mode
                # overrides them. A root that entered via `setup` already
                # carries this record.
                ctx.cfg.setdefault("scoped_mode_restore", {
                    "audit": str(ctx.cfg.get("audit", DEFAULT_AUDIT) or DEFAULT_AUDIT),
                    "revision_audit": str(ctx.cfg.get("revision_audit", "on") or "on").lower(),
                    # Record the RAW policy (None when the root predates the key):
                    # a legacy root must get the key back as ABSENT, not as the
                    # current default `on` (F23).
                    "cold_start_review": (str(ctx.cfg.get("cold_start_review")).lower()
                                          if "cold_start_review" in ctx.cfg else None),
                    "rounds": int(ctx.cfg.get("rounds") or DEFAULTS["rounds"]),
                    "rewrites": list(ctx.cfg.get("rewrites") or DEFAULTS["rewrites"]),
                    "revises": list(ctx.cfg.get("revises") or DEFAULTS["revises"]),
                    "integrators": list(ctx.cfg.get("integrators") or DEFAULTS["integrators"]),
                    "round_indices": (list(ctx.cfg.get("round_indices"))
                                      if ctx.cfg.get("round_indices") else None),
                    # The scoped mode also forces champion_select=revise and may
                    # run with a scoped review_scope; leaving the mode must put
                    # the operator's own values back (F09).
                    "champion_select": str(ctx.cfg.get("champion_select")
                                           or DEFAULT_CHAMPION_SELECT),
                    "review_scope": list(ctx.cfg.get("review_scope")
                                         or DEFAULTS["review_scope"]),
                })
            rounds = int(ctx.cfg.get("rounds") or 1)
            if rounds != 1:
                ctx.cfg["rounds"] = 1
                forced.append("rounds=1")
            if list(ctx.cfg.get("rewrites") or []) != [0]:
                ctx.cfg["rewrites"] = [0]
                forced.append("rewrites=0")
            if list(ctx.cfg.get("revises") or []) != [1]:
                ctx.cfg["revises"] = [1]
                forced.append("revises=1")
            if list(ctx.cfg.get("integrators") or []) != [0]:
                ctx.cfg["integrators"] = [0]
                forced.append("integrators=0")
            if ctx.cfg.pop("round_indices", None) is not None:
                forced.append("round_indices cleared (a scoped revision has one round)")
            if str(ctx.cfg.get("champion_select") or DEFAULT_CHAMPION_SELECT) == "integrate":
                ctx.cfg["champion_select"] = "revise"
                forced.append("champion_select=revise (a scoped revision has no integration arm)")
            ctx.cfg["audit"] = "off"
            forced.append("audit=off")
            ctx.cfg["revision_audit"] = "off"
            forced.append("revision_audit=off (concern-scoped edits have no general review "
                          "to audit against)")
            if str(ctx.cfg.get("cold_start_review", COLD_START_REVIEW_DEFAULT)).lower() != "off":
                ctx.cfg["cold_start_review"] = "off"
                forced.append("cold_start_review=off (scoped edits are driven by the concerns)")
        elif _prev_mode in (JOURNAL_MODE_MAJOR, JOURNAL_MODE_MINOR):
            # Leaving a scoped mode restores the historical plan the mode
            # replaced. Without this the root kept `rounds=1`, `rewrites=[0]`,
            # `integrators=[0]`, `review_scope=[formatting-writing]` and
            # `audit=off` while `journal_is_scoped` was already false -- neither
            # the documented default three-round workflow nor a scoped revision.
            saved = ctx.cfg.pop("scoped_mode_restore", None) or {}
            for _key in ("rounds", "rewrites", "revises", "review_scope", "integrators"):
                _value = saved.get(_key, DEFAULTS[_key])
                ctx.cfg[_key] = list(_value) if isinstance(_value, list) else _value
                forced.append(f"{_key}={ctx.cfg[_key]} (restored)")
            if saved.get("round_indices"):
                ctx.cfg["round_indices"] = [int(x) for x in saved["round_indices"]]
                forced.append(f"round_indices={ctx.cfg['round_indices']} (restored)")
            else:
                ctx.cfg.pop("round_indices", None)
            if saved.get("champion_select"):
                ctx.cfg["champion_select"] = str(saved["champion_select"])
                forced.append(f"champion_select={ctx.cfg['champion_select']} (restored)")
            if isinstance(saved.get("review_scope"), list) and saved["review_scope"]:
                ctx.cfg["review_scope"] = [str(x) for x in saved["review_scope"]]
                forced.append(f"review_scope={ctx.cfg['review_scope']} (restored)")
            ctx.cfg["audit"] = str(saved.get("audit") or DEFAULT_AUDIT)
            forced.append(f"audit={ctx.cfg['audit']} (restored)")
            ctx.cfg["revision_audit"] = str(saved.get("revision_audit") or "on").lower()
            forced.append(f"revision_audit={ctx.cfg['revision_audit']} (restored)")
            _saved_cold = saved.get("cold_start_review", COLD_START_REVIEW_DEFAULT)
            if _saved_cold is None:
                ctx.cfg.pop("cold_start_review", None)
                forced.append("cold_start_review unset (this root had no policy key)")
            else:
                ctx.cfg["cold_start_review"] = str(_saved_cold).lower()
                forced.append(f"cold_start_review={ctx.cfg['cold_start_review']} (restored)")
        ctx.state["config"] = ctx.cfg
        write_json_atomic(ctx.cfg_path, ctx.cfg)
        ctx.log("set-revision-mode", detail=mode_arg)
        ctx.save_state()
    print(f"[set-revision-mode] mode: {mode_arg} (option {info['option']}) -- {info['label']}")
    for f in forced:
        print(f"[set-revision-mode]   forced by the mode: {f}")
    if info.get("feedback"):
        hits = journal_feedback_files(ctx)
        llm_hits = journal_llm_feedback_files(ctx)
        print(f"[set-revision-mode] feedback file(s): "
              + (", ".join(label for _p, label in hits) if hits
                 else "(no human letter found)"))
        print(f"[set-revision-mode] LLM review file(s): "
              + (", ".join(label for _p, label in llm_hits) if llm_hits else "(none)"))
        if not hits and not llm_hits:
            print("[set-revision-mode]   `run` will refuse until the feedback is in the corpus "
                  "(human_review_feedback/ or llm_review_feedback/) or named with "
                  "--journal-feedback")


def only_is_template_stage_only(spec) -> bool:
    """`--only conform` / `--only 1:conform`: that stage alone."""
    if spec is None or getattr(spec, "all_stages", False):
        return False
    stages = set(getattr(spec, "stages", ()) or ())
    pairs = getattr(spec, "pairs", {}) or {}
    stages |= {s for v in pairs.values() for s in (v or ())}
    stages = set(stages)
    sessions = getattr(spec, "sessions", {}) or {}
    # A judge selector (`conform,w1_j1`, `conform,r1_judge_w2_j1`) is a
    # session too: the items are a UNION, so such a selection must run the
    # template stage AND the named judge session, never short-circuit to the
    # template-stage-only exit just because `sessions` is empty.
    judge_selectors = getattr(spec, "judge_selectors", {}) or {}
    judge_run_ids = getattr(spec, "judge_run_ids", None) or []
    return (stages == {"conform"} and not any(sessions.values())
            and not any(judge_selectors.values()) and not judge_run_ids)


def validate_only_selectors(ctx: Ctx, only, flag: str = "--only") -> None:
    """Refuse an `--only` SESSION item this plan cannot satisfy.

    Two namespaces, each validated against the plan before anything starts:

      * a producing session (`r1_w2`, `rewriter1`, `integrator2`) must be a
        session the round's plan runs -- the rewrites/revises the round's counts
        give, the integration arms its mask selected, and its review (with B) and
        audit sessions;
      * a judge session (`r1_judge_<version>_j<k>`, `w2_j1`, `judge1`) against the
        JUDGEABLE ids (the original, the pool and those arms) and the round's
        `--judges` count -- see parse_judges_enabled.

    A roundless item applies to every round that HAS the session, so it only dies
    when no round of the plan has it. Either way the typo dies here, with the
    values that exist, instead of quietly running a different selection later.
    """
    if only is None:
        return
    R = ctx.rounds_count()
    planned = {r: [session_id_of_entry(e) for e in round_run_plan(ctx, r)]
               for r in range(1, R + 1)}
    if only.sessions.get(None):
        missing = [tok for tok in only.sessions[None]
                   if not any(tok in planned[r] for r in planned)]
        if missing:
            die(f"{flag}: no round of this pipeline runs session(s) {', '.join(missing)}; "
                f"round 1 plans {', '.join(planned[1])} (the revise arms are numbered from a2, "
                f"so `reviser1` is a2)")
    for r in sorted(k for k in only.sessions if k is not None):
        for tok in only.sessions[r]:
            if tok not in planned[r]:
                die(f"{flag}: round {r} plans no session {tok!r}; it runs "
                    f"{', '.join(planned[r])} (the revise arms are numbered from a2, so "
                    f"`reviser1` is a2, `reviser2` a3, ...)")
    keys = {k for k in only.judge_selectors if k is not None}
    if only.judge_selectors.get(None):
        # a roundless selector applies to every round that has the version, so it
        # is validated in each of them (parse_judges_enabled skips the rest)
        keys |= set(range(1, R + 1))
    for r in sorted(k for k in keys if k <= R):
        spec = only.judge_spec_for(r)
        if not spec:
            continue
        try:
            parse_judges_enabled(spec, R, lambda rr: judgeable_ids(ctx, rr),
                                 lambda rr: round_judges(ctx, rr))
        except ValueError as e:
            die(f"{flag}: {e}")


def no_progress_measure(row: dict):
    """The ordered progress key for `--stop-after-no-progress`.

    The SAME lexicographic census `champion_sort_key()` ranks by (then
    median/mean/IQR), never the census SUM: a version that removed a fatal
    defect (census (0,5)) is progress over one that has one (1,0), although
    its total is larger. The digest tie-break is deliberately absent: an
    identity choice is not evidence of progress.
    """
    if not row:
        return None
    med, mean, iqr = row.get("median"), row.get("mean"), row.get("iqr")
    census = row.get("defect_prefix_census")
    if census is None:
        census = (int(row.get("defect_prefix_total") or 0),)
    return (
        tuple(int(x) for x in census),
        -(med if med is not None else -99.0),
        -(mean if mean is not None else -99.0),
        iqr if iqr is not None else 99.0,
    )


def cmd_run(args) -> None:
    """`run` entry point: take the root lock, then drive the rounds."""
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    refuse_foreign_pipeline(ctx, "run")
    # The stages render prompts from the venue profile: refuse to start on a
    # venue that does not resolve, whatever --strict-venue says.
    venue_profile_of(ctx)
    # WHICH CODE THIS RUN WILL EXECUTE, before it executes it: a root that froze
    # an older bundle (or one whose frozen file no longer matches its recorded
    # sha256) drives that older code for every stage below, so the note belongs
    # in the run log, not only in `status` (2026-10-15).
    _snap = pipeline_snapshot_note(ctx)
    if _snap:
        print(f"[run] {_snap}")
    with ctx.lock("run"):
        _cmd_run_locked(ctx, args)


def _cmd_run_locked(ctx: Ctx, args) -> None:
    # `--no-track` covers BOTH the per-stage hook (postcheck -> track_after_stage)
    # and the round-close pass: the choice is recorded on the context BEFORE any
    # stage starts, so every accepted version is treated the same way.
    ctx.stage_tracking = not bool(getattr(args, "no_track", False))
    # The invocation-level champion-selection override. Each round records the
    # mode it actually used (`plan.champion_select`), so a later invocation that
    # omits the flag cannot relabel an auto-promoted round as judged.
    ctx._champion_select_override = str(getattr(args, "champion_select", None) or "")
    # Input-area names are canonical and never rewritten; nothing in the
    # pipeline moves them. The pristine original is the reference every sandbox
    # and judge copy comes from; if it no longer matches the setup-time manifest,
    # refuse to proceed.
    ok, detail = pristine_integrity(ctx)
    if not ok:
        die(f"pristine integrity check failed: {detail}\n"
            f"       Restore {ctx.pristine} (e.g. from your own copy of the corpus) or start a "
            f"fresh pipeline root with `setup`.")
    print(f"[run] pristine original: {detail}")

    _only_cold_start = parse_only_spec(getattr(args, "only", None))
    if only_is_template_stage_only(_only_cold_start):
        if journal_mode_of(ctx) not in (JOURNAL_MODE_TRANSFER, JOURNAL_MODE_INIT):
            die("--only conform is the "
                f"template-first stage of the transfer and init revision modes: this root's "
                f"revision mode is {journal_mode_of(ctx)!r}")
        _ensure_template_stage_for_run(ctx, args)
        die(f"the template-first stage is {'done' if template_stage_record(ctx) else 'pending'}; "
            f"the round(s) are still pending -- run a plain `run` (or another --only selection) "
            f"to continue the chain", code=3)
    if journal_mode_of(ctx) in (JOURNAL_MODE_TRANSFER, JOURNAL_MODE_INIT):
        _ensure_template_stage_for_run(ctx, args)

    perrs = pinned_integrity(ctx)
    if perrs:
        die("pinned champion content changed after it was registered:\n  - "
            + "\n  - ".join(perrs)
            + "\n       The content-addressed chain is broken; restore the pinned/ tree (or the "
              "state.json backup) before continuing, or start a fresh --root.")
    for note in raw_data_advisories(ctx):
        print(f"[run] WARNING: {note}")

    stale, blocking = reconcile_inputs(ctx)
    if blocking:
        die("a completed round depends on content that changed after the fact:\n  - "
            + "\n  - ".join(blocking)
            + "\n       Re-run the affected stage with `retry --run <ID>` (this invalidates that "
              "round and every later round), or start a fresh --root.")
    if stale:
        print(f"[run] {len(stale)} run(s) marked stale by the content check: {', '.join(stale)}")
        ctx.save_state()
    backfill_round_raw_scores(ctx)
    manual = args.agent == "manual"
    only = parse_only_spec(getattr(args, "only", None))
    if only is not None and only.is_everything():
        only = None                     # `--only all`: exactly a plain `run`
    if only is not None:
        if journal_has_feedback(ctx):
            # The journal chain's stages are selectable exactly like the round
            # model's (feedback, concerns, review, audit, revise, integrate,
            # response). The safety rule is preserved at the SINK, not by
            # refusing the selection: the response letter and the
            # journal_submission/ package are assembled only by a plain `run`
            # once every stage of the chain is done.
            print(f"[run] --only {getattr(args, 'only', None)!r} in revision mode "
                  f"{journal_mode_of(ctx)!r}: the journal stages are selectable; the response "
                  f"letter and journal_submission/ are assembled only by a plain `run` once "
                  f"every stage of the chain is done.")
        resolve_judge_run_ids(ctx, only)    # `--only judge_t497f106d_j1`
        only.validate(ctx.rounds_count())
        validate_only_selectors(ctx, only)
        print(f"[run] --only {getattr(args, 'only', None)!r}: {only.describe()}; this invocation "
              f"drives only the selected round(s), stage type(s) and session(s); a round whose "
              f"other stages are still pending stays incomplete (resume with `run`, `--only …`, "
              f"or `retry --run <ID>`)")
    # A no-judge mode must be possible in EVERY pending round this invocation may
    # decide. Validate the target arms BEFORE the first expensive session, so an
    # existing root whose later round's mask is clear cannot fail after rounds of
    # work. An --only selection that does not ask for a round decision is exempt.
    _csel_pre = champion_select_of(ctx)
    if _csel_pre != "judge" and not journal_is_scoped(ctx):
        for _rr in range(1, ctx.rounds_count() + 1):
            if only is not None and not only.judge_step_in_full(_rr):
                continue
            if (ctx.round_get(_rr) or {}).get("status") == "done":
                continue
            auto_champion_vid(ctx, _rr, _csel_pre)
    cmd = None if manual else resolve_agent_cmd(args.agent, args.agent_cmd)
    if not manual and shutil.which(cmd[0]) is None:
        die(f"agent executable not found on PATH: {cmd[0]!r}\n"
            f"       use --agent-cmd '[\"...\"]' or PAPER_AGENT_CMD to point at your CLI"
            + agent_install_hint(cmd))
    # The judge panel is manual only when it is asked for explicitly, or when
    # NOTHING judge-specific was given and the production stages are manual: an
    # explicit --judge-agent-cmd must never be silently replaced by manual
    # waiting (it would also leave the judge wave with no timeout).
    _csel_run = champion_select_of(ctx)
    if _csel_run != "judge":
        # No judge session exists in this invocation: do not require a judge
        # backend executable, and do not pretend a manual panel is waiting.
        judge_cmd, judge_manual = None, True
        print(f"[run] judge panel: SKIPPED -- --champion-select {_csel_run} auto-promotes "
              f"the revised submission (PROVISIONAL; no panel scores are produced)")
    else:
        judge_backend = args.judge_agent or (None if args.judge_agent_cmd else args.agent)
        # An explicit --judge-agent-cmd wins over --judge-agent manual: the comment
        # below promises it is never silently replaced by manual waiting, which is
        # what happened whenever both flags were given.
        judge_manual = judge_backend == "manual" and not args.judge_agent_cmd
        if judge_manual:
            judge_cmd = None
        elif args.judge_agent_cmd:
            judge_cmd = resolve_agent_cmd(args.judge_agent or args.agent,
                                          args.judge_agent_cmd)
        elif args.judge_agent:
            # An explicit --judge-agent must win over --agent-cmd and over
            # PAPER_AGENT_CMD; otherwise the flag silently has no effect on the panel.
            judge_cmd = resolve_agent_cmd(args.judge_agent, None, use_env=False)
        else:
            judge_cmd = list(cmd)
        if not judge_manual and shutil.which(judge_cmd[0]) is None:
            die(f"judge agent executable not found on PATH: {judge_cmd[0]!r}\n"
                f"       fix --judge-agent-cmd/--judge-agent or drop the override"
                + agent_install_hint(judge_cmd))
    # The optional cross-judge conflict audit (see write_round_judge_conflicts):
    # OFF by default (the LLM defect audit below covers the same ground); an
    # explicit --conflict-agent[-cmd] or PAPER_CONFLICT_AGENT_CMD turns the LLM
    # pass on, and the mechanical pass always runs.
    _conflict_choice = getattr(args, "conflict_agent", None)
    if getattr(args, "no_conflict_agent", False):
        conflict_cmd = None
        conflict_audit_on = False
    elif getattr(args, "conflict_agent_cmd", None):
        conflict_cmd = resolve_agent_cmd(_conflict_choice or "codex-lite",
                                         args.conflict_agent_cmd)
        conflict_audit_on = True
    elif _conflict_choice == "manual":
        conflict_cmd = None
        conflict_audit_on = False
    elif _conflict_choice:
        conflict_cmd = resolve_agent_cmd(_conflict_choice, None, use_env=False)
        conflict_audit_on = True
    else:
        _env_conflict = _conflict_agent_cmd_from_env(PAPER_CONFLICT_AGENT_ENV)
        conflict_cmd = _env_conflict if (_env_conflict
                                         and _conflict_cmd_usable(_env_conflict)) else None
        conflict_audit_on = conflict_cmd is not None
    if conflict_cmd is not None and shutil.which(str(conflict_cmd[0])) is None:
        die(f"conflict-audit agent executable not found on PATH: {conflict_cmd[0]!r}\n"
            f"       fix --conflict-agent-cmd/--conflict-agent or pass --no-conflict-agent"
            + agent_install_hint(conflict_cmd))
    # The LLM defect audit (diagnostic; see write_round_defect_audit): ON by
    # default when the judge backend is a real agent, off for manual/custom
    # backends unless --defect-audit[-cmd] / PAPER_DEFECT_AUDIT_CMD asks for it.
    if champion_select_of(ctx) != "judge":
        defect_cmd, defect_src = None, "skipped (no judge panel to audit)"
    else:
        defect_cmd, defect_src = resolve_defect_audit_cmd(
            args, judge_cmd, judge_manual, ctx.state.get("defect_audit") or {})
    if defect_cmd is not None and shutil.which(str(defect_cmd[0])) is None:
        print(f"[defect-audit] WARNING: {defect_cmd[0]!r} is not on PATH; skipping the "
              f"LLM defect audit")
        defect_cmd, defect_src = None, "unavailable"
    # Record the backend the defect audit actually resolves (diagnostic only):
    # a later `decide` reuses the same one for the fingerprint-matched re-check.
    ctx.state["defect_audit"] = {
        "cmd": ([str(x) for x in defect_cmd] if defect_cmd else None),
        "source": defect_src,
        "recorded": utcnow(),
    }
    # C24 (recorded, not changed): producers and judges may be the SAME backend,
    # which makes the panel a self-consistency instrument. The operator kept one
    # Codex backend on 2026-09-21; the least the pipeline owes the reader is to
    # record it, so the decision is never mistaken for an independent measure.
    ctx.state["judge_provider"] = {
        "same_as_producer": bool(not judge_manual and cmd and judge_cmd == list(cmd)),
        "producer": (cmd[0] if cmd else None),
        "judge": (judge_cmd[0] if judge_cmd else None),
        "judge_manual": bool(judge_manual),
        "note": ("producer and judge resolve to the SAME backend: the panel measures the model "
                 "family's self-consistency as well as the packages; a different-family or human "
                 "judge (--judge-agent-cmd) is the documented way to remove that limit"),
    }
    if ctx.state["judge_provider"]["same_as_producer"]:
        print("[run] note: producers and judges use the same backend "
              f"({Path(str(cmd[0])).name}); this is recorded in decision.json "
              "(judge_provider) -- the panel is not an independent measure")
    if args.timeout is not None and args.timeout < 0:
        # A negative value is truthy, so the subprocess deadline was computed
        # in the past and every attempt died as an immediate "timeout".
        die("--timeout must be a non-negative number of seconds", code=2)
    timeout = args.timeout if args.timeout is not None else (0 if manual else DEFAULTS["timeout"])
    # ADOPTION comes after the command/timeout are known: an adopted run whose
    # postcheck fails on repairable bookkeeping gets its scoped repair session
    # (see sweep_artifacts), instead of being re-run from scratch.
    _adopted = sweep_artifacts(ctx, cmd=cmd, timeout=timeout)
    if _adopted:
        print(f"[run] adopted {len(_adopted)} run(s) whose completion signal already existed: "
              f"{', '.join(_adopted)}")
    # Automated sessions always get the default timeout, even when the
    # production stages run in manual mode (timeout=0 means "no timeout").
    judge_timeout = timeout
    if args.timeout is None and manual and not judge_manual:
        judge_timeout = DEFAULTS["timeout"]
    if not manual:
        print(f"[run] agent command: {' '.join(cmd)}")
    if judge_manual or judge_cmd != cmd:
        print("[run] judge sessions: " + ("manual" if judge_manual else " ".join(judge_cmd)))
    retries = max(0, int(args.retries))
    retry_backoff = max(0, int(getattr(args, "retry_backoff", DEFAULTS["retry_backoff"])))
    retry_backoff_max = max(0, int(getattr(args, "retry_backoff_max",
                                           DEFAULTS["retry_backoff_max"])))
    ctx.state["run_policy"] = {"agent": args.agent,
                               "judge_agent": args.judge_agent or args.agent,
                               "jobs": args.jobs, "timeout": timeout,
                               "judge_timeout": judge_timeout, "retries": retries,
                               "attempts_per_run": retries + 1,
                               "retry_backoff": retry_backoff,
                               "retry_backoff_max": retry_backoff_max,
                               "set": utcnow()}
    ctx.save_state()
    retry_note = (f"attempts/run={retries + 1} (retries={retries}, exponential backoff "
                  f"{retry_backoff}s..{retry_backoff_max}s)"
                  if retries else "no automatic retry (--retries 0)")
    print(f"[run] jobs={args.jobs} timeout={timeout or 'none'}s "
          f"judge-timeout={judge_timeout or 'none'}s {retry_note} "
          f"rounds={ctx.rounds_count()} judges/version={judges_config_note(ctx)} "
          f"integrators={integrators_config_note(ctx)} "
          f"champion-select={champion_select_of(ctx)} "
          f"agent={args.agent}")
    # The optional `docx` CLI is offered to every agent in every stage (see
    # DOCX_CLI_RULE). It is never required, but the operator should be able to
    # see from the run log whether the agents can actually reach it.
    print("[run] optional `docx` CLI for the agents: "
          + ("available on PATH (`docx read/render/diff/validate/...`; optional, never required)"
             if docx_cli_available() else
             "NOT on PATH -- the prompts tell the agents to use the other tools instead"))
    # The Zotero reference-tooling policy (setup --zotero) decides how far the
    # agent sessions may go; the operator must see the effective mode in the run
    # log, and an `apply` run -- the only mode that can write to the operator's
    # remote library -- says so loudly.
    _zot_mode = zotero_mode_of(ctx)
    if _zot_mode == "off":
        _zot_note = ("off -- the `zot` CLI is never used; live fields stay on the skills' manual "
                     "route")
    else:
        _zot_on_path = ("the `zot` CLI is on PATH" if zot_cli_available()
                        else "the `zot` CLI is NOT on PATH")
        if _zot_mode == "apply":
            _zot_note = ("apply -- citation edits AND single-field library updates are allowed "
                         "(propose-then-verify, --last-modified auto); this WRITES TO YOUR REMOTE "
                         f"ZOTERO ACCOUNT ({_zot_on_path})")
        elif _zot_mode == "edit":
            _zot_note = ("edit -- citation edits in the revised copy are allowed; the Zotero "
                         f"library stays read-only ({_zot_on_path})")
        else:
            _zot_note = f"read -- read-only reference resolution; no citation edits ({_zot_on_path})"
    print(f"[run] zotero reference tooling:  {_zot_note}")
    # The docx->pdf converter the prompts ask for FIRST (see the visual rule):
    # the docx-converter MCP tool, falling back to the other renderers.
    if mcp_server_configured(DOCX_MCP_SERVER):
        argv = [str(a) for a in (cmd or [])]
        if manual:
            note = "; manual mode: YOUR session approves the call, so no override is needed"
        elif any(o in argv for o in configured_mcp_approvals()):
            note = "; pre-approved for the agent with the -c MCP approval override"
        else:
            # Only the codex preset carries the `-c` overrides, and they are
            # codex's own mechanism: a custom command, or a preset that is not
            # codex (claude, dsh), reaches the servers through ITS OWN
            # configuration instead -- which this probe cannot see, so it says
            # what it actually knows.
            if getattr(args, "agent_cmd", None) or os.environ.get("PAPER_AGENT_CMD"):
                note = ("; NOTE: this argv carries no MCP approval override "
                        "(--agent-cmd/PAPER_AGENT_CMD was given), so the call may be denied")
            else:
                note = (f"; NOTE: the {str(getattr(args, 'agent', '') or 'selected')} preset "
                        f"carries no MCP approval override (only the codex one adds them; a CLI's "
                        f"own configuration decides which MCP servers it reaches), so the call "
                        f"may be denied")
        first_choice = (f"the {DOCX_MCP_SERVER} MCP tool (`{DOCX_MCP_TOOL}`) -- agents call it "
                        f"before any other converter{note}")
    elif shutil.which("docx2pdf.sh"):
        first_choice = ("docx2pdf.sh (the docx-converter MCP tool is not configured in "
                        f"{codex_config_path()})")
    else:
        first_choice = ("NONE of the Word-fidelity converters is available -- the prompts tell the "
                        "agents to record the limitation instead of claiming a visual check")
    print(f"[run] preferred docx->pdf converter for the agents: {first_choice}")

    R = ctx.rounds_count()
    if R < 1:
        die("pipeline_config.json records no rounds; re-run `setup` with --rounds >= 1")
    if journal_is_scoped(ctx):
        # Options 3/4: ONE concern-scoped round, no judge panel, no rewrite, then
        # the response letter (when required) and the submission package.
        print(f"[run] journal revision mode: {journal_mode_of(ctx)} "
              f"(option {JOURNAL_MODES[journal_mode_of(ctx)]['option']}) -- "
              f"{JOURNAL_MODES[journal_mode_of(ctx)]['label']}")
        if ctx.round_rec(1).get("status") == "done":
            print(f"[run] round 1 is already complete: {ctx.round_rec(1).get('champion')}")
        else:
            ok, paused = drive_round(ctx, 1, cmd=cmd, timeout=timeout, jobs=args.jobs,
                                     retries=retries, manual=manual, nowait=args.no_wait,
                                     poll=args.poll, judge_cmd=judge_cmd,
                                     judge_manual=judge_manual, judge_timeout=judge_timeout,
                                     conflict_cmd=conflict_cmd,
                                     conflict_agent=conflict_audit_on,
                                     defect_cmd=defect_cmd,
                                     retry_backoff=retry_backoff,
                                     retry_backoff_max=retry_backoff_max,
                                     redline=not getattr(args, "no_redline", False),
                                     track=not getattr(args, "no_track", False),
                                     only=only)
            ctx.save_state()
            if not ok:
                summarize(ctx)
                if paused:
                    print("[run] manual mode: prompts printed above; nothing was executed by the "
                          "orchestrator. Re-run `run --agent manual` after your agents finish.")
                    return
                ctx.round_rec(1)["status"] = "pending"
                ctx.save_state()
                keep_failed_sandboxes(ctx, manual=manual)
                print(f"[run] the {journal_mode_of(ctx)} revision is incomplete; progress is "
                      f"saved. Resume with `run --root {ctx.root}` or reset one run with "
                      f"`retry --run <ID>`.")
                sys.exit(3)
        if only is not None:
            print(f"[run] --only {getattr(args, 'only', None)!r}: the response letter and "
                  f"journal_submission/ are assembled only by a plain `run` once the "
                  f"{journal_mode_of(ctx)} revision is complete.")
            summarize(ctx)
            return
        ok, _ = drive_journal_finalize(ctx, cmd=cmd, timeout=timeout, jobs=args.jobs,
                                       retries=retries, manual=manual, nowait=args.no_wait,
                                       poll=args.poll, retry_backoff=retry_backoff,
                                       retry_backoff_max=retry_backoff_max)
        ctx.save_state()
        if not ok:
            summarize(ctx)
            print(f"[run] the {journal_mode_of(ctx)} revision itself is complete, but the "
                  f"response/submission stage did not finish; re-run `run` (or "
                  f"`retry --run {rid_response(1)}`) to finish it.")
            sys.exit(3)
        summarize(ctx)
        return
    driven = []                      # the rounds this invocation actually drove
    for r in range(1, R + 1):
        if only is not None and not only.covers_round(r):
            print(f"[run] round {r}/{R} NOT selected by --only ({getattr(args, 'only', None)!r}): "
                  f"nothing of its plan is started in this invocation")
            continue
        if only is not None and not only.selects_round(ctx, r):
            print(f"[run] round {r}/{R} has none of the selected session(s) "
                  f"({getattr(args, 'only', None)!r}): it plans "
                  f"{', '.join(session_id_of_entry(e) for e in round_run_plan(ctx, r))}; "
                  f"nothing of it is started in this invocation")
            continue
        rrec = ctx.round_rec(r)
        if rrec.get("status") == "done":
            print(f"[run] round {r}/{R} already complete: champion {rrec.get('champion')} "
                  f"pinned at {rrec.get('pin_path')}")
            continue
        ok, paused = drive_round(ctx, r, cmd=cmd, timeout=timeout, jobs=args.jobs,
                                 retries=retries, manual=manual, nowait=args.no_wait,
                                 poll=args.poll, judge_cmd=judge_cmd,
                                 judge_manual=judge_manual, judge_timeout=judge_timeout,
                                 conflict_cmd=conflict_cmd,
                                 conflict_agent=conflict_audit_on,
                                 defect_cmd=defect_cmd,
                                 retry_backoff=retry_backoff,
                                 retry_backoff_max=retry_backoff_max,
                                 redline=not getattr(args, "no_redline", False),
                                 track=not getattr(args, "no_track", False),
                                 only=only)
        driven.append(r)
        ctx.save_state()
        if not ok:
            summarize(ctx)
            if paused:
                print("[run] manual mode: prompts printed above; nothing was executed by the "
                      "orchestrator. Re-run `run --agent manual` after your agents finish.")
                return
            # Honest state: the round is waiting again, not "active".
            ctx.round_rec(r)["status"] = "pending"
            ctx.save_state()
            keep_failed_sandboxes(ctx, manual=manual)
            print(f"[run] round {r} is incomplete; progress is saved. Resume with "
                  f"`run --root {ctx.root}` (a fresh invocation grants every failed run a "
                  f"fresh retry budget) or reset a single run with `retry --run <ID>`.")
            sys.exit(3)
        # C28: the pre-registered no-progress stop. A round whose champion is its
        # own base (A1) demonstrably improved nothing, and under this measurement
        # design the next round's expected gain is ~0 while it costs a full pool
        # plus a judge wave. The streak is derived from the round records, so a
        # resumed run reaches the same conclusion.
        streak = 0
        for rr in range(int(r), 0, -1):
            rec_rr = ctx.round_rec(rr)
            if rec_rr.get("status") != "done":
                continue
            sel_rr = rec_rr.get("selection") or {}
            ranking = sel_rr.get("ranking") or []
            base_row = next((row for row in ranking if row.get("is_base")), None)
            champ_row = next(
                (row for row in ranking if row.get("id") == sel_rr.get("champion")), None)

            def measurable(row):
                return no_progress_measure(row)

            # The content digest may select a challenger when every measurable
            # term ties. That is a deterministic identity choice, not evidence
            # of progress, so it must not defeat the pre-registered stop.
            champ_key, base_key = measurable(champ_row), measurable(base_row)
            if str(sel_rr.get("champion")) == A1_ID \
                    or (champ_key is not None and base_key is not None
                        and champ_key >= base_key):
                streak += 1
            else:
                break
        stop_k = int((ctx.cfg or {}).get("stop_after_no_progress") or 0)
        more_rounds = any(rr > r and (only is None or only.covers_round(rr))
                          for rr in range(1, R + 1))
        if stop_k and streak >= stop_k and more_rounds:
            ctx.state["stopped_early"] = {
                "after_round": int(r), "planned_rounds": int(R),
                "no_progress_streak": streak,
                "rule": f"--stop-after-no-progress {stop_k}",
                "reason": ("the last round(s) pinned the incumbent base -- no demonstrable, "
                           "non-regressing progress -- or selected a challenger only on the "
                           "digest tie-break, with no measurable gain. Further rounds are "
                           "expected to cost a pool and a judge wave without improving the "
                           "panel's measurable result"),
                "at": utcnow(),
            }
            ctx.save_state()
            print(f"[run] STOPPING EARLY after round {r}/{R}: {streak} consecutive round(s) "
                  f"showed no measurable improvement over their base ({stop_k} configured). "
                  f"`decide` will treat round {r} as the final answer and record the stop in "
                  f"decision.json.")
            break

    if journal_mode_of(ctx) in (JOURNAL_MODE_TRANSFER, JOURNAL_MODE_RESUBMIT) and only is None:
        R = ctx.rounds_count()
        if all(ctx.round_rec(r).get("status") == "done" for r in range(1, R + 1)):
            ok, _ = drive_journal_finalize(ctx, cmd=cmd, timeout=timeout, jobs=args.jobs,
                                           retries=retries, manual=manual, nowait=args.no_wait,
                                           poll=args.poll, retry_backoff=retry_backoff,
                                           retry_backoff_max=retry_backoff_max)
            ctx.save_state()
            if not ok:
                summarize(ctx)
                print(f"[run] the rounds are complete, but the journal finalization did not "
                      f"finish; re-run `run` (or `retry --run {rid_response(R)}`) to finish it.")
                sys.exit(3)
        else:
            print(f"[run] journal mode {journal_mode_of(ctx)!r}: the response letter and the "
                  f"submission package are assembled once EVERY round is complete; finish the "
                  f"pending round(s) and re-run.")

    print()
    summarize(ctx)
    print("[run] per-round champions:")
    for r in range(1, R + 1):
        rrec = ctx.round_rec(r)
        print(f"  round {r}: champion={rrec.get('champion')}  "
              f"field={len(rrec.get('field') or [])}  "
              f"{rrec.get('scores_per_version')} scores/version  "
              f"winner={rrec.get('winner_dir') or rrec.get('pin_path')}")
    selected = ([r for r in range(1, R + 1) if only.covers_round(r)]
                if only is not None else list(range(1, R + 1)))
    if only is not None and not driven:
        # Nothing was driven. Two very different situations hide behind that:
        #
        #   * every round the selection COVERS is already complete -- re-running a
        #     finished `--only` selection (`--only 1:judge` after round 1 was
        #     decided) is a successful NO-OP: it reports what is complete and what
        #     is still pending, and exits 0, exactly like a plain `run` on a
        #     finished root;
        #   * the selection covers a round that still needs work but could not
        #     start anything in it (a roundless `--only w2` on a root where no
        #     pending round has w2): that is an incomplete invocation, so it says
        #     so and exits non-zero.
        covered_pending = [r for r in range(1, R + 1)
                           if only.covers_round(r) and ctx.round_rec(r).get("status") != "done"]
        if covered_pending:
            print(f"[run] --only {getattr(args, 'only', None)!r} selected no session of the "
                  f"round(s) that still need work ({', '.join(str(r) for r in covered_pending)}): "
                  f"nothing was started in this invocation.")
            sys.exit(3)
        print(f"[run] --only {getattr(args, 'only', None)!r}: round(s) "
              f"{', '.join(str(r) for r in selected) or '(none)'} of {R} are already complete -- "
              f"nothing to do in this invocation")
    if only is not None and len(selected) < R:
        print(f"[run] --only ran round(s) {', '.join(str(r) for r in selected)} of {R}; round "
              f"{R} champion is the final answer once every configured round is complete. "
              f"Next: python {Path(sys.argv[0]).name} run --root {ctx.root} "
              f"(or `decide` when all rounds are done)")
    else:
        print(f"[run] round {R} champion is the final answer. "
              f"Next: python {Path(sys.argv[0]).name} decide --root {ctx.root}")


def summarize(ctx: Ctx) -> None:
    counts = {}
    for rec in ctx.runs():
        counts[(rec["kind"], rec["status"])] = counts.get((rec["kind"], rec["status"]), 0) + 1
    if counts:
        print("[summary] " + ", ".join(f"{k}:{n} {st}" for (k, st), n in sorted(counts.items())))
    rlines = [f"round {r}: {ctx.round_get(r).get('status')} "
              f"champion={ctx.round_get(r).get('champion')}"
              for r in range(1, ctx.rounds_count() + 1)]
    if rlines:
        print("[summary] " + " | ".join(rlines))

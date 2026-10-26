# -*- coding: utf-8 -*-
# Part 08/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# AGGREGATION (Section D -- pure deterministic code, no LLM arithmetic)
# =====================================================================

def aggregate_round(ctx: Ctx, r: int, field_ids: list) -> dict:
    """Collect the round's directed scores into each version's own frame.

    D1  V's own judges contribute score(V vs W) to V["own"][W]; W's judges
        contribute score(W vs V), negated, to V["received"][W]. Opponent labels
        resolve through each judge run's stored label_map; comparisons whose
        opponent cannot be resolved are skipped and reported.
    D2  the ranking statistic is the median of the FLAT score list
        (own + received), with n, the arithmetic MEAN and the IQR reported over
        the same list. V-vs-W and W-vs-V are independent judgments from
        independent sessions, so flattening is correct; a two-level median would
        throw away that independence. The median is a coarse statistic on a
        -4..+4 integer scale and ties are common, so the arithmetic mean of the
        SAME score list is the panel-statistic fallback when a median ties
        (never a different statistic, never a re-judgement). The RANKING key
        itself puts the round's reported defect prefix above the median -- see
        `champion_sort_key`.
    D3  vs_original = median over the directed scores involving the pristine
        original (own + negated received); anti_regression_ok = vs_original
        >= VS_ORIGINAL_TOLERANCE (0 here; see the constant's comment).
    D4  vs_base = the same statistic computed against the member whose content
        IS the round's base A1_r (the base itself is content-deduplicated into
        that member, so its row is the row the judges produced for it). It is
        reported for every member, and the base's own row competes in the
        selection so a round can never crown a version the panel ranks below the
        version it started from.
    """
    field_ids = list(field_ids)
    judges = round_judges(ctx, r)
    selection = judge_selection(ctx, r)          # empty = every session runs
    # Which judges run for each version (`--only` may select only some).
    per_judges = {vid: (int(round_judges(ctx, r)) if not selection
                        else len({k for v, k in selection if v == str(vid)}))
                  for vid in field_ids}
    diags = {"sheets_used": 0, "sheets_expected": sum(per_judges.values()),
             "scores_collected": 0, "unresolved": [], "incomplete_sheets": [],
             "superseded_sheets": [], "out_of_range_sheets": []}
    # Provenance of every FLAT-LIST entry, so reports/round<r>_raw_scores.csv can
    # show the exact numbers the median and the mean were computed from (one row
    # per frame entry: the target's own score, and the SAME integer negated into
    # the opponent's received list).
    score_rows = []
    # Every resolvable comparison, kept for the issue census (which counts the
    # ledger rows per version, tier and severity -- see build_issue_census).
    census_obs = []
    if selection:
        diags["judges_enabled"] = judges_enabled_spec(ctx, r)
        diags["judges_per_version"] = dict(per_judges)
    per = {vid: {"judges": 0, "own": {}, "received": {}} for vid in field_ids}
    # ---- one sheet per (target, judge index) -------------------------------
    # A judge session is identified by its target AND its judge index, not by
    # its run id: a re-materialized judge (state repair regenerating the salt, a
    # re-registered session after a prune) can produce a SECOND done record for
    # the same (target, judge index). Counting both would push every version's
    # directed-score count ABOVE the expected panel size, which the completeness
    # test reads as "incomplete" -- a full panel would be reported as a gap and
    # the round would stay undecidable with a diagnosis pointing the operator at
    # missing judges they cannot add. Keep the newest valid sheet per slot and
    # report the superseded ones. Sheets whose judge index is outside the
    # configured 1..judges range (a stale `--judges` value) are recorded and
    # skipped for exactly the same reason.
    sheets = []
    for rec in ctx.runs(kind="judge", round_no=r):
        if rec.get("status") != "done":
            continue
        j = rec.get("judge_index")
        if selection and (str(rec.get("target_id") or ""), int(j) if is_int(j) else 0) \
                not in selection:
            # A sheet for a session this round does not run (a leftover from an
            # earlier selector, or a stale sandbox): counting it would look like an
            # over-full panel and make every version "incomplete".
            diags.setdefault("disabled_sheets", []).append(
                f"{rec.get('id')}: judge {(rec.get('target_id'), j)} is not enabled by "
                f"--only {judges_enabled_spec(ctx, r)} (the sheet is ignored)")
            continue
        if not is_int(j) or not (1 <= j <= judges):
            diags["out_of_range_sheets"].append(
                f"{rec.get('id')}: judge_index={j!r} for {rec.get('target_id')!r} is outside "
                f"the configured 1..{judges} (the sheet is ignored; a stale --judges value "
                f"cannot poison the panel)")
            continue
        sheets.append(rec)
    newest = {}
    for rec in sorted(sheets, key=lambda x: (str(x.get("finished") or x.get("created") or ""),
                                             str(x.get("id")))):
        slot = (rec.get("target_id"), rec.get("judge_index"))
        if slot in newest:
            old = newest[slot]
            diags["superseded_sheets"].append(
                f"{old.get('id')} superseded by {rec.get('id')} for {slot[0]} judge "
                f"j{slot[1]} (the newest sheet is used)")
        newest[slot] = rec
    for rec in sheets:
        if newest.get((rec.get("target_id"), rec.get("judge_index"))) is not rec:
            continue
        vid = rec.get("target_id")
        if vid not in per:
            diags["unresolved"].append(f"{rec['id']}: target {vid!r} is not a field member")
            continue
        sj = rec.get("scores")
        if not isinstance(sj, dict):
            continue
        lm = rec.get("label_map") or {}
        per[vid]["judges"] += 1
        diags["sheets_used"] += 1
        for comp in sj.get("comparisons") or []:
            if not isinstance(comp, dict):
                continue
            label, score = comp.get("opponent_label"), comp.get("score")
            # Case/whitespace-normalised: a judge typing 'V1' means the label
            # 'v1' it was issued, and the panel must not lose the comparison.
            opp = lm.get(_norm_opponent_label(label))
            if opp is None or opp not in per or opp == vid or not is_int(score):
                diags["unresolved"].append(
                    f"{rec['id']}: comparison for label {label!r} could not be resolved")
                continue
            if not (SCORE_MIN <= score <= SCORE_MAX):
                diags["unresolved"].append(
                    f"{rec['id']}: score {score!r} for label {label!r} is out of range")
                continue
            census_obs.append((rec.get("id"), vid, opp, comp))
            per[vid]["own"].setdefault(opp, []).append(int(score))
            per[opp]["received"].setdefault(vid, []).append(-int(score))
            for member, direction, credited, other in ((vid, "own", int(score), opp),
                                                       (opp, "received", -int(score), vid)):
                score_rows.append({
                    "round": int(r), "member": member, "direction": direction,
                    "credited": credited, "opponent_id": other,
                    "opponent_label": label, "sheet_target": vid,
                    "source_judge_run": rec.get("id"),
                    "source_judge_index": rec.get("judge_index"),
                    "score_as_written": int(score),
                    "basis": comp.get("basis"),
                    "resolved": _ledger_cell(comp.get("resolved")),
                    "introduced": _ledger_cell(comp.get("introduced")),
                    "reason": (str(comp.get("reason")) if comp.get("reason") else "")[:200],
                })
            diags["scores_collected"] += 1
    k = len(field_ids)
    # Directed scores per version = judges * (|field|-1) own scores plus
    # (|field|-1) * judges negated received scores = 2 * judges * (|field|-1).
    # At the default 2 judges that is the documented 4*(|field|-1) (24 at
    # |field| = 7); the formula is written generically so a setup with a
    # different --judges value is not reported as an incomplete panel.
    # A `run --only r1_judge_w2_j1` selection gives each version its own panel, so the
    # expectation is built from the ENABLED sessions: own J(V)*(k-1) plus one
    # negated received score for every other version's enabled sessions.
    enabled_total = sum(per_judges.values())
    expected_for = {vid: per_judges.get(vid, 0) * (k - 1)
                    + (enabled_total - per_judges.get(vid, 0))
                    for vid in field_ids}
    expected = 2 * judges * (k - 1)
    # The round's base A1_r is content-identical to one of the field members
    # (the pristine original in round 1, the previous round's pin later on) and is
    # therefore deduplicated out of the field. That member's row IS the base's
    # row: it is what lets the selection compare a candidate with the version the
    # round started from. Match on the DOCUMENT fingerprint, exactly like
    # build_field, so a base whose bookkeeping files were regenerated still finds
    # its representative.
    base_fp = effective_content_fingerprint(ctx, r, A1_ID)
    base_rep = None
    if base_fp:
        for vid in field_ids:
            if effective_content_fingerprint(ctx, r, vid) == base_fp:
                base_rep = vid
                break
    if base_rep is None:
        # No fingerprint available (a root created before the fingerprint existed,
        # or a pruned sandbox): fall back to the recorded integrity digest, which
        # is the pre-fingerprint behaviour.
        base_digest = recorded_version_digest(ctx, r, A1_ID)
        if base_digest:
            for vid in field_ids:
                if recorded_version_digest(ctx, r, vid) == base_digest:
                    base_rep = vid
                    break
    stats = {}
    for vid in field_ids:
        st = per[vid]
        own_flat = [s for opp in sorted(st["own"]) for s in st["own"][opp]]
        recv_flat = [s for opp in sorted(st["received"]) for s in st["received"][opp]]
        flat = own_flat + recv_flat
        vs_vals = list(st["own"].get(ORIGINAL_ID, [])) + \
            list(st["received"].get(ORIGINAL_ID, []))
        vs = float(statistics.median(vs_vals)) if vs_vals else None
        # Scores of this member against the round's base (own, plus the base
        # member's own judges negated into this member's frame).
        base_vals = ([] if base_rep in (None, vid) else
                     list(st["own"].get(base_rep, [])) +
                     list(st["received"].get(base_rep, [])))
        vs_base = float(statistics.median(base_vals)) if base_vals else None
        cap_info = caption_info_for(ctx, r, vid)
        cap_ok, cap_note = caption_gate(cap_info)
        ph_info = placeholder_info_for(ctx, r, vid) or \
            scan_placeholders_in_sources(corpus_sources(ctx, r, vid))
        stats[vid] = {
            "id": vid,
            # Content digest of the version (provenance-free identity): used as
            # the final tie-break so an exact statistical tie is never decided
            # by the arm's NAME (a2 < i1 < w1 would silently favour the revise
            # arm on every perfect tie).
            "digest": recorded_version_digest(ctx, r, vid),
            "n": len(flat),
            "expected_n": expected_for.get(vid, expected),
            "complete": len(flat) == expected_for.get(vid, expected),
            "median": float(statistics.median(flat)) if flat else None,
            "mean": float(statistics.fmean(flat)) if flat else None,
            "iqr": iqr_of(flat) if flat else None,
            "vs_original": vs,
            "vs_original_n": len(vs_vals),
            # vs_original mixes this version's own judges (V vs the pristine
            # original) with the original's own judges (negated into this frame),
            # so its expectation is J(V) + J(orig) -- 2*judges when every judge runs.
            "vs_original_expected": (per_judges.get(vid, judges)
                                     + per_judges.get(ORIGINAL_ID, judges)),
            "vs_original_complete": len(vs_vals) == (per_judges.get(vid, judges)
                                                     + per_judges.get(ORIGINAL_ID, judges)),
            # The pair's own sign evidence (wins = scores above the tolerance,
            # losses = below it) and the exact one-sided p: reported with every
            # row, and the rule that consumes them is explicit.
            "vs_original_wins": sum(1 for x in vs_vals if x > 0),
            "vs_original_losses": sum(1 for x in vs_vals if x < 0),
            "vs_original_ties": sum(1 for x in vs_vals if x == 0),
            "vs_original_sign_p": _binomial_tail_p(sum(1 for x in vs_vals if x < 0),
                                                   sum(1 for x in vs_vals if x != 0)),
            "anti_regression_rule": vs_original_rule_of(ctx),
            "anti_regression_ok": anti_regression_verdict(ctx, vid, vs, vs_vals),
            "vs_base": vs_base,
            "vs_base_n": len(base_vals),
            # The raw directed scores of the incumbent pair: REPORTED (the margin
            # a human reads, and the sign count), never a ranking input -- the
            # pair is too small for one outlier session not to flip it.
            "vs_base_vals": sorted(int(x) for x in base_vals),
            "vs_base_expected": (0 if base_rep in (None, vid) else 2 * judges),
            "is_base": vid == base_rep,
            "own_counts": {opp: len(v) for opp, v in sorted(st["own"].items())},
            "received_counts": {opp: len(v) for opp, v in sorted(st["received"].items())},
            "judges_seen": st["judges"],
            "judges_expected": judges,
            # Advisory information only (see caption_gate): the orchestrator
            # reports caption lengths and hand-off placeholders, it never gates
            # or ranks anything on them.
            "caption_gate_ok": cap_ok,
            "caption_note": cap_note,
            "captions": cap_info,
            "author_placeholders": int(ph_info.get("count") or 0),
            "placeholder_documents": list(ph_info.get("files") or []),
        }
        if not stats[vid]["complete"]:
            diags["incomplete_sheets"].append(
                f"{vid}: {len(flat)} of {expected_for.get(vid, expected)} directed "
                f"scores collected")
    # Missing-sheet diagnostics, driven by the RECORDED sessions (a recomputed
    # token would miss legacy/unsalted ids and misreport whole panels as absent).
    for vid in field_ids:
        recs = [rec for rec in ctx.runs(kind="judge", round_no=r)
                if rec.get("target_id") == vid]
        done = {rec.get("judge_index") for rec in recs if rec.get("status") == "done"}
        enabled = (sorted(k for v, k in selection if str(v) == str(vid))
                   if selection else list(range(1, judges + 1)))
        for j in enabled:
            if j not in done:
                diags["incomplete_sheets"].append(
                    f"{vid}: judge session j{j} has no completed sheet")
    # ---- panel-quality diagnostics (reported only; never used for eligibility)
    # The prompt tells judges that 0 is the expected answer for near-identical
    # packages. Nothing measured whether that held in practice, so a panel that
    # scores noise looked exactly like a panel that measured real differences.
    pq = {"scores": 0, "zero_share": None, "mean_abs": None,
          "within_direction_range_max": 0, "direction_flips": [], "judge_means": {},
          "score_histogram": {}, "max_abs_score": 0, "calibrated_sheets": 0,
          "uncalibrated_sheets": 0, "basis_counts": {}, "ledger_sign_conflicts": []}
    own_scores = [s for vid in field_ids
                  for vals in (per[vid].get("own") or {}).values() for s in vals]
    if own_scores:
        pq["scores"] = len(own_scores)
        pq["zero_share"] = round(sum(1 for s in own_scores if s == 0) / len(own_scores), 3)
        pq["mean_abs"] = round(sum(abs(s) for s in own_scores) / len(own_scores), 3)
        pq["max_abs_score"] = max(abs(s) for s in own_scores)
        hist = {}
        for s in own_scores:
            hist[str(s)] = hist.get(str(s), 0) + 1
        pq["score_histogram"] = dict(sorted(hist.items(), key=lambda kv: int(kv[0])))
    ranges = [max(vals) - min(vals) for vid in field_ids
              for vals in (per[vid].get("own") or {}).values() if len(vals) >= 2]
    pq["within_direction_range_max"] = max(ranges) if ranges else 0
    for rec in ctx.runs(kind="judge", round_no=r):
        if rec.get("status") != "done" or not isinstance(rec.get("scores"), dict):
            continue
        vals = [c.get("score") for c in (rec["scores"].get("comparisons") or [])
                if isinstance(c, dict) and is_int(c.get("score"))]
        if vals:
            pq["judge_means"][rec["id"]] = round(sum(vals) / len(vals), 3)
        # ---- graded-basis calibration (judge contract v2+) -----------------
        # How many sheets carry a checkable basis, what tiers they claim, and
        # where an integer contradicts its own ledger. Reported, never used for
        # eligibility: the score statistics above stay the ranking input.
        n_comps = 0
        n_with_basis = 0
        for c in (rec["scores"].get("comparisons") or []):
            if not isinstance(c, dict):
                continue
            n_comps += 1
            basis = str(c.get("basis") or "").strip().lower()
            if basis in BASIS_VALUES:
                n_with_basis += 1
                pq["basis_counts"][basis] = pq["basis_counts"].get(basis, 0) + 1
            if not is_int(c.get("score")):
                continue
            side_res = [i for i in (c.get("resolved") or []) if isinstance(i, dict)]
            side_int = [i for i in (c.get("introduced") or []) if isinstance(i, dict)]
            s = int(c["score"])
            if (s > 0 and not side_res) or (s < 0 and not side_int):
                pq["ledger_sign_conflicts"].append(
                    f"{rec['id']} vs {c.get('opponent_label')}: score {s:+d} with "
                    f"resolved={len(side_res)} introduced={len(side_int)}")
        if n_comps and n_with_basis == n_comps:
            pq["calibrated_sheets"] += 1
        else:
            pq["uncalibrated_sheets"] += 1
    for i, v in enumerate(field_ids):
        for w in field_ids[i + 1:]:
            own_v = per[v].get("own", {}).get(w) or []
            own_w = per[w].get("own", {}).get(v) or []
            if own_v and own_w:
                mv, mw = statistics.median(own_v), statistics.median(own_w)
                # A FLIP is the two sides claiming the SAME side is better (both own
                # medians positive, or both negative): negated into one frame they
                # would not cancel. Opposite signs are the consistent reading (V's
                # judges say V is better, W's judges say W is worse). The comparison
                # used to be inverted here, so the report listed every AGREEING pair
                # as a disagreement and hid the real ones.
                if (mv > 0 and mw > 0) or (mv < 0 and mw < 0):
                    pq["direction_flips"].append(f"{v} vs {w}: {mv:g} vs {mw:g}")
    diags["panel_quality"] = pq
    # The issue census: how many issues of each tier and severity the panel
    # attributed to each version. It is the selection's LEADING ranking input:
    # the cumulative defect count over the adaptive severity_tier_category
    # prefix, rung by rung (the four severities, tier order, peer before own).
    census = build_issue_census(census_obs, field_ids,
                                sessions_expected=sum(per_judges.values()),
                                dedup=dedup_mode_of(ctx),
                                dedup_threshold=DEDUP_FUZZY_THRESHOLD)
    # The census's LONG FORM: the very rows it counted, with their meta and the
    # sheet's own evidence sentence (reports/round<r>_defects.csv). Same
    # observations, same attribution and the same dedup rules -- the two readers
    # of one dataset.
    issue_rows = build_issue_ledger_rows(census_obs, field_ids,
                                         dedup=dedup_mode_of(ctx),
                                         dedup_threshold=DEDUP_FUZZY_THRESHOLD)
    return {"round": int(r), "field": field_ids, "field_size": k,
            "scores_per_version": expected,
            "scores_per_version_by_version": dict(expected_for),
            "stats": stats, "diagnostics": diags,
            "score_rows": score_rows, "issue_census": census,
            "issue_rows": issue_rows,
            "base_id": A1_ID, "base_rep": base_rep,
            "generated": utcnow()}


def stats_row_for(agg: dict, vid: str) -> dict:
    """The stats row that belongs to a version (the base points at its rep)."""
    stats = (agg or {}).get("stats") or {}
    if vid in stats:
        return stats[vid]
    if vid == A1_ID:
        rep = (agg or {}).get("base_rep")
        if rep:
            return stats.get(rep) or {}
    return {}


def candidate_tiebreak_inputs(ctx: Ctx, r: int, vid: str) -> tuple:
    """(critical_remaining, writing_remaining, manual_steps) for the REPORT.

    Priority: the values the round recorded when it was decided (so `decide`
    re-derives the same ranking even after old sandboxes are pruned for disk
    space), then the producing run's marker summary -- every fresh arm (rewrite,
    revise and integration) reports critical_remaining/writing_remaining/
    manual_items, so nothing here is structurally biased towards the revise arm --
    then, as a last resort, a count of the package's MANUAL_STEPS.md. A missing
    value is +inf (MISSING_TIEBREAK): absence never wins a tie, and the count is
    never taken from an inherited file when the producing run reported its own
    number.

    Neither count ranks any more (2026-10-01): the ranking's leading comparator is the
    panel-derived issue census (`champion_sort_key`), and these two remain as
    reported, cross-checked signals. `writing_remaining` is the number of the
    frozen review's CATEGORY-2 findings (writing quality, logic, repetition) still
    open in the package -- self-reported by the producing session exactly like
    `critical_remaining`, and never a score, a gate or a reason to make a version
    ineligible. The frozen-review cross-check exists only for the arms that
    consume a `review/` directory (the revise arm) and only in the reported-zero
    direction; a rewrite or integration self-report is unverified, exactly as the
    decision record's `tiebreak_notes` say. `manual_steps` is
    REPORTED, never ranked on: it measures how much work the pipeline hands to the
    author (Zotero live fields, numbers visible only inside figures, subjective
    calls), so a package must not lose a tie for reporting more of them -- that
    would reward under-reporting exactly like scoring a hand-off placeholder as a
    defect.
    """
    stored = (ctx.round_get(r).get("tiebreak_inputs") or {}).get(vid)
    if isinstance(stored, dict):
        crit = stored.get("critical_remaining", MISSING_TIEBREAK)
        writing = stored.get("writing_remaining", MISSING_TIEBREAK)
        manual = stored.get("manual_steps", MISSING_TIEBREAK)
        return (_valid_count(crit), _valid_count(writing), _valid_count(manual))
    rec = ctx.run(rid_for_fresh(r, vid)) or {}
    summ = rec.get("summary") if isinstance(rec.get("summary"), dict) else {}
    crit = _valid_count(summ.get("critical_remaining"))
    writing = _valid_count(summ.get("writing_remaining"))
    manual = MISSING_TIEBREAK
    if is_int(summ.get("manual_items")):
        manual = _valid_count(summ["manual_items"])
    elif rec and rec.get("sandbox"):
        sb = ctx.sandbox_of(rec)
        for rel in MANUAL_STEPS_RELS:
            n = count_manual_steps(sb / rel)
            if n is not None:
                manual = n
                break
    return crit, writing, manual


def _valid_count(v):
    """A reported count, or MISSING_TIEBREAK when it is absent or impossible.

    `critical_remaining`/`writing_remaining` are REPORTED (cross-checked against
    the frozen review) but never rank -- the ranking's leading comparator is the
    panel's own issue census. The guard survives from when they did rank: a
    NEGATIVE number must never be rewarded, so an agent (or a corrupted marker)
    reporting -99 sorted ahead of an honest 0. A count of findings cannot be
    negative, so a nonsensical value is treated exactly like an absent one
    (sentinel +inf, which never wins a tie).
    """
    if not is_int(v):
        return MISSING_TIEBREAK
    return int(v) if int(v) >= 0 else MISSING_TIEBREAK


# ---- the champion selection key (2026-10-01 calibrations) ------------------
# `fatal -> critical -> major -> minor -> median -> mean -> IQR -> digest`,
# where the fatal -> ... -> minor stage is the ADAPTIVE DEFECT PREFIX below:
#   * the DEFECT PREFIX LEADS (fourth calibration): the number of defects the
#     panel attributed to a version is the most direct improvement signal, and
#     the panel median is coarse on a small integer scale;
#   * the median, the mean and the IQR are the panel statistics BELOW it;
#   * the defect counts come from the round's issue census and compare the
#     TOTAL number of defects over the leading `severity_tier_category` cells
#     (a single tiny cell fluctuates too much to rank on): the walk grows the
#     prefix until the cleanest ranked version carries `tiebreak_defect_floor`
#     defects or every cell is included. The cumulative count at that prefix is
#     a TOTAL, not a rate -- every ranked version's opportunities are the same
#     in a complete panel, so the exposure normalization (own/peer) is already
#     carried by the cell ORDER (peer before own) rather than by dividing;
#   * the counts are the mentions each judge sheet filed (collapsed only per
#     session+version, never matched across sheets by default), with the opt-in
#     `dedup_mode` "location" available when the operator wants the
#     structured-key merge;
#   * the mean breaks a tie ONLY when those cumulative totals are equal
#     (a total count is more reliable than the mean of small integer scores);
#     IQR/digest stay below it as the deterministic fallbacks, and the
#     incumbent-retention rule (an exact median/mean/IQR tie keeps the base)
#     is unchanged.
# The adaptive defect-prefix tie-break (2026-10-01, fifth calibration):
#   * cells are ordered `severity_tier_category`: fatal, then critical, then
#     major, then minor, tier by tier in the scoring priority order, and within
#     a (severity, tier) cell `peer` before `own`. 48 cells -- the SAME four
#     severity rungs the census, the judge contract and the score model use, so
#     every artifact speaks one vocabulary (an earlier 36-cell variant merged
#     fatal+critical for the walk; it was reverted for consistency);
#   * walking that order, the counts are accumulated for every ranked version and
#     the walk STOPS at the first prefix where the version with the FEWEST
#     defects already carries `tiebreak_defect_floor` of them (default 10, a
#     CLI/config parameter), or when every cell is included;
#   * the version's cumulative count at that prefix is the tie-break for a
#     median tie (fewer defects is better). The arithmetic mean is consulted
#     ONLY when those cumulative counts are equal, then IQR, digest and id.
# Rationale: a per-cell count is tiny and fluctuates; accumulating cells in the
# order the scoring semantics prioritises grows the evidence until the cleanest
# candidate has enough counts (or there is nothing left to add), and the single
# accumulated number is more reliable than the mean of small integer scores.
# [(group name, the census severities it sums)], in the tie-break's rung order.
# Every rung is ONE census severity: the lattice, the long-form census, the
# judge contract and the score model all use the same four rungs.
TIEBREAK_SEVERITY_GROUPS = (("fatal", ("fatal",)),
                            ("critical", ("critical",)),
                            ("major", ("major",)),
                            ("minor", ("minor",)))
# Convenience: the flat rung order (fatal, critical, major, minor) -- the walk
# order, also used for the report table's severity columns.
SEVERITY_TIE_ORDER = tuple(name for name, _sev in TIEBREAK_SEVERITY_GROUPS)
TIEBREAK_SOURCES = ("peer", "own")
# Historical name: the defect prefix now LEADS the ranking (it is not a
# tie-break any more); this constant still governs how far the walk accumulates
# before it stops, and the `--tiebreak-defect-floor` CLI/config name is kept for
# compatibility with existing roots.
DEFAULT_TIEBREAK_DEFECT_FLOOR = 10


def tiebreak_cell_specs() -> list:
    """[(severity group, tier, source)] in the canonical `severity_tier_category` order."""
    return [(name, tier, src) for name, _sev in TIEBREAK_SEVERITY_GROUPS
            for tier in BASIS_TIERS for src in TIEBREAK_SOURCES]


def tiebreak_cell_names() -> list:
    return [f"{name}_{tier}_{src}" for name, tier, src in tiebreak_cell_specs()]


def tiebreak_group_severities(name) -> tuple:
    """The census severities one tie-break rung sums (itself for major/minor)."""
    for group_name, severities in TIEBREAK_SEVERITY_GROUPS:
        if group_name == str(name):
            return tuple(severities)
    return ()


def tiebreak_defect_floor_of(ctx) -> int:
    """The configured prefix floor (>= 0); DEFAULT_TIEBREAK_DEFECT_FLOOR when unset."""
    raw = (getattr(ctx, "cfg", None) or {}).get("tiebreak_defect_floor")
    try:
        floor = int(raw) if raw is not None else DEFAULT_TIEBREAK_DEFECT_FLOOR
    except (TypeError, ValueError):
        floor = DEFAULT_TIEBREAK_DEFECT_FLOOR
    return max(0, floor)


def _census_for(vid, agg) -> dict:
    return ((agg or {}).get("issue_census") or {}).get(str(vid)) or {}


def issue_matrix_and_cumulative(census, versions) -> tuple:
    """(cell names, per-version counts per cell, per-version prefix sums).

    The counts are the census's EFFECTIVE defect counts (per source): the raw
    mentions with dedup off (the default), the merged counts in the opt-in
    `dedup_mode` "location". The two files this feeds and the selection read the
    same numbers.
    """
    specs = tiebreak_cell_specs()
    names = tiebreak_cell_names()
    matrix = {}
    for vid in versions:
        tiers = (_census_for(vid, {"issue_census": census}).get("tiers") or {})
        row = []
        for name, tier, src in specs:
            sevs = ((tiers.get(tier) or {}).get("severities") or {})
            row.append(sum(int((sevs.get(sev) or {}).get(src) or 0)
                           for sev in tiebreak_group_severities(name)))
        matrix[str(vid)] = row
    cumulative = {vid: list(itertools.accumulate(row)) for vid, row in matrix.items()}
    return names, matrix, cumulative


def tiebreak_prefix_cells(cumulative: dict, versions, floor: int) -> int:
    """How many leading cells the tie-break uses (>= 1 unless there are no cells).

    The first prefix at which the version with the FEWEST defects reaches the
    floor wins; if no prefix reaches it, every cell is used.
    """
    if not cumulative or not versions:
        return 0
    n_cells = len(next(iter(cumulative.values())))
    for i in range(n_cells):
        if min(int(cumulative[str(v)][i]) for v in versions) >= floor:
            return i + 1
    return n_cells


def census_prefix_total(agg: dict, sel: dict, vid: str):
    """The `defects@K` number for ONE member, over the ranking's adaptive prefix.

    Every field member carries census counts -- including the members that never
    enter the ranking (the pristine original, an ineligible arm). Report the same
    cumulative statistic over the SAME prefix the ranked rows use, so the run
    table's `defects@K` column compares like with like. None when the member has
    no census row at all (the cell then stays '-', never a fabricated 0).
    None the same way when the decision carries no ranking prefix to accumulate
    over -- an absent `cells_used` cannot be read as "zero defects".
    """
    census = (agg or {}).get("issue_census") or {}
    if str(vid) not in census:
        return None
    _, _, cumulative = issue_matrix_and_cumulative(census, [str(vid)])
    row = cumulative.get(str(vid)) or []
    cells = int(((sel or {}).get("tiebreak") or {}).get("cells_used") or 0)
    if not cells or not row:
        return None
    return int(row[min(cells, len(row)) - 1])


def champion_issue_summary(vid, agg) -> dict:
    """Per severity: counts and rates (for the report/trace)."""
    tiers = (_census_for(vid, agg).get("tiers") or {})
    out = {}
    for sev in ("critical", "fatal", "major", "minor"):
        own = sum(int((((tiers.get(t) or {}).get("severities") or {})
                       .get(sev) or {}).get("own") or 0) for t in BASIS_TIERS)
        peer = sum(int((((tiers.get(t) or {}).get("severities") or {})
                        .get(sev) or {}).get("peer") or 0) for t in BASIS_TIERS)
        out[sev] = {"own": own, "peer": peer}
    return out


def champion_sort_key(row: dict) -> tuple:
    """cumulative defect count at the adaptive prefix -> median -> mean -> IQR -> digest.

    The defect prefix LEADS the key: the number of defects the panel attributed
    to a version is the most direct improvement signal, and the medians of a
    small panel are coarse. The panel's median/mean/IQR and the digest are the
    tie-breaks below it. A difference in the leading term is not a tie.
    """
    med, mean, iqr = row.get("median"), row.get("mean"), row.get("iqr")
    return ((int(row.get("defect_prefix_total") or 0),)
            + (-(med if med is not None else -99.0),)
            + (-(mean if mean is not None else -99.0),
               (iqr if iqr is not None else 99.0),
               str(row.get("digest") or "~"), str(row.get("id") or "")))


def auto_round_payload(ctx: Ctx, r: int, vid: str = None, mode: str = None) -> tuple:
    """(aggregation, selection) for a round promoted WITHOUT a judge panel.

    The shapes are the ones `pin_champion` / `publish_winner` / `finalize_round`
    and the decision report already read. Every statistical cell is None (not 0)
    -- an unjudged round has no panel score, and a fabricated zero would read as
    a perfect score. The selection is marked `auto_promoted` / `judged=False`, and
    the decision layer turns that into a PROVISIONAL (not certified) verdict.

    `vid` is normally the target `auto_champion_vid` computed from the round's
    plan; `decide` passes the STORED champion so a corrupt record is reported
    rather than silently replaced.
    """
    mode = str(mode or round_champion_select(ctx, r)).strip().lower()
    target = str(vid or auto_champion_vid(ctx, r, mode))
    digest = recorded_version_digest(ctx, r, target)
    stats_row = {
        "n": 0, "expected_n": 0, "complete": True,
        "judges_seen": 0, "judges_expected": 0,
        "median": None, "mean": None, "iqr": None,
        "vs_original": None, "vs_original_n": 0, "vs_original_expected": 0,
        "vs_original_complete": None, "anti_regression_ok": None,
        "vs_base": None, "vs_base_vals": [],
        "digest": digest,
        "caption_gate_ok": None,
        "caption_note": "not judged (auto-promoted submission)",
        "author_placeholders": 0, "placeholder_documents": [], "captions": {},
    }
    agg = {"round": int(r), "field": [target], "field_size": 1,
           "scores_per_version": 0, "stats": {target: stats_row},
           "diagnostics": {"auto_promoted": True, "champion_select": mode,
                           "judge_panel": "skipped",
                           "sheets_used": 0, "sheets_expected": 0,
                           "note": ("the round was auto-promoted without a judge panel; "
                                    "this is not a scored comparison")},
           "score_rows": [], "issue_census": {}, "issue_rows": [],
           "base_id": A1_ID, "base_rep": None, "generated": utcnow()}
    label = {"revise": f"the review-audit-revised candidate {target}",
             "integrate": f"the integrated revised candidate {target}"}.get(
                 mode, f"candidate {target}")
    trace = [f"auto-promoted by --champion-select {mode}: {label} was promoted directly; "
             f"NO judge panel scored the field, so no ranking key was consulted.",
             "the result is marked auto_promoted and the decision verdict is PROVISIONAL "
             "(not certified): an unjudged winner is an operator choice, not a panel result."]
    ranking_row = {"id": target, "rep": target, "is_base": False,
                   "n": 0, "median": None, "mean": None, "iqr": None,
                   "vs_original": None, "vs_base": None, "vs_base_vals": [],
                   "digest": digest, "defect_prefix_total": 0,
                   "tiebreak_prefix_cells": 0,
                   "critical_remaining": MISSING_TIEBREAK,
                   "writing_remaining": MISSING_TIEBREAK,
                   "manual_steps": MISSING_TIEBREAK,
                   "author_placeholders": 0, "issues": {}, "captions": None}
    sel = {"champion": target, "champion_rep": target, "base_rep": None,
           "eligible": [target], "ranking": [ranking_row], "trace": trace,
           "auto_promoted": True, "judged": False, "champion_select": mode,
           "tiebreak": {"floor": 0, "cells_used": 0, "cell_order": [], "cells_total": 0}}
    return agg, sel


def select_champion(ctx: Ctx, r: int, agg: dict) -> dict:
    """D5: rank the fresh candidates AND the round's own base.

    The fresh arms are this round's pool (M rewritten candidates w1..wM and N
    reviewed-and-revised candidates a2..a{1+N}) plus the K integrated candidates
    i1..iK. The round's base A1_r is content-identical to one field member
    (the pristine original in round 1, the previous round's pinned champion
    later on), whose judges produced a full row for it; that row enters the
    ranking as the base. Two consequences, both intended:

      * a version the panel ranks BELOW the version the round started from can
        no longer be crowned (the round would otherwise take a step backwards
        even though the field still holds the incumbent), and
      * when the base wins, the round honestly reports "no demonstrable,
        non-regressing progress" and keeps the incumbent's content, exactly as
        the no-eligible-candidate fallback always did.

    Eligibility: a complete panel is required for every row, and a FRESH arm
    must additionally clear the anti-regression gate against the pristine
    original. The base row itself is the incumbent status quo -- the gate exists
    to stop a NEW regression, and the no-progress fallback crowns the base even
    when nothing clears the gate, so the base is judged on its panel alone.

    Caption length and hand-off placeholders are ADVISORY: they are reported in
    the trace and the report and can never make a row ineligible.
    """
    stats = agg["stats"]
    trace = []
    base_rep = agg.get("base_rep")
    candidates = round_candidate_ids_run(ctx, r)
    missing = [c for c in candidates if c not in stats]
    if missing:
        trace.append(f"candidate(s) {missing} are not field members this round (their content was "
                     f"deduplicated into another member, or the arm did not run) -> not eligible "
                     f"to win")
    # (id to crown, id of the row that carries its stats, is_base)
    contenders = [(c, c, False) for c in candidates if c in stats]
    # A candidate that deduplicated away is still represented in the field by
    # the member it merged into; that member's row is already a contender of its
    # own, so nothing is silently lost from the ranking.
    if base_rep:
        contenders.append((A1_ID, base_rep, True))
        trace.append(f"the round's base A1_{r} is content-identical to field member "
                     f"{base_rep!r}; that member's row is the base's row and competes, so the "
                     f"round can never crown a version the panel ranks below the version it "
                     f"started from")
    else:
        trace.append("the round's base has no row in this field (no digest match); the selection "
                     "falls back to the fresh arms only")
    eligible = []
    for cid, row_id, is_base in contenders:
        st = stats[row_id]
        label = f"{cid} [base row {row_id}]" if is_base else cid
        if not (st.get("n") or 0):
            trace.append(f"{label}: no usable directed scores -> not eligible to win")
            continue
        if not st.get("complete"):
            trace.append(f"{label}: PANEL INCOMPLETE ({st.get('n')} of {st.get('expected_n')} "
                         f"directed scores collected) -> ineligible: a partial panel must not "
                         f"decide a round")
            continue
        if not is_base and st.get("vs_original_complete") is False:
            trace.append(f"{label}: ANTI-REGRESSION PANEL INCOMPLETE "
                         f"({st.get('vs_original_n')} of {st.get('vs_original_expected')} scores "
                         f"against the original) -> ineligible")
            continue
        if not is_base and not st.get("anti_regression_ok"):
            trace.append(f"{label}: anti-regression gate FAILED (vs_original median "
                         f"{st.get('vs_original')!r} < {VS_ORIGINAL_TOLERANCE:g}) -> ineligible")
            continue
        if st.get("caption_gate_ok") is False:
            # Advisory only: reported, never a gate. This is the master prompt's
            # treatment of its cover-letter word rule, applied to captions.
            trace.append(f"{label}: {st.get('caption_note')} -> reported only; caption length "
                         f"never affects eligibility")
        if st.get("author_placeholders"):
            trace.append(f"{label}: {st['author_placeholders']} pipeline hand-off placeholder(s) "
                         f"for the author -> reported only; a place-holder is a manual item, "
                         f"never a defect and never a score penalty")
        eligible.append(cid)
    if not eligible:
        trace.append("no eligible rows: the champion falls back to A1_r (this round made no "
                     "demonstrable, non-regressing progress). If the cause was an incomplete "
                     "panel, re-run the judge stage (`retry --run <judge id>`) before trusting "
                     "this fallback -- an incomplete panel is not evidence of no progress.")
        return {"champion": A1_ID, "champion_rep": base_rep, "eligible": [], "ranking": [],
                "trace": trace}
    rows = []
    for cid in eligible:
        row_id = base_rep if cid == A1_ID and base_rep else cid
        st = stats[row_id]
        crit, writing, manual = candidate_tiebreak_inputs(ctx, r, cid)
        rows.append({"id": cid, "rep": row_id, "is_base": bool(cid == A1_ID and base_rep),
                     "n": st["n"], "median": st["median"], "mean": st["mean"],
                     "iqr": st["iqr"], "vs_original": st["vs_original"],
                     "vs_base": st["vs_base"],
                     "digest": st.get("digest"),
                     "critical_remaining": crit, "writing_remaining": writing,
                     "manual_steps": manual,
                     "author_placeholders": st.get("author_placeholders"),
                     "issues": champion_issue_summary(row_id, agg),
                     "captions": st.get("caption_note")})
    # The adaptive defect prefix (the ranking's LEADING comparator): walk the
    # canonical severity_tier_category order, accumulate the reported counts for
    # every ranked version, and stop at the first prefix where the version with
    # the FEWEST defects reaches the configured floor (or when every cell is
    # used). The cumulative count at that prefix leads the sort key; the median
    # (then the mean, IQR, digest and id) is the tie-break below it.
    floor = tiebreak_defect_floor_of(ctx)
    rep_ids = sorted({str(t["rep"]) for t in rows})
    cell_names, _matrix, cumulative = issue_matrix_and_cumulative(
        (agg or {}).get("issue_census") or {}, rep_ids)
    prefix_cells = tiebreak_prefix_cells(cumulative, rep_ids, floor)
    for t in rows:
        t["defect_prefix_total"] = (cumulative[str(t["rep"])][prefix_cells - 1]
                                    if prefix_cells else 0)
        t["tiebreak_prefix_cells"] = prefix_cells
    # Ranking key, in order (2026-10-01, fourth calibration), with each
    # component's provenance:
    #   defect_prefix_total   the cumulative defect count (per source, collapsed
    #                         only per session+version) over the adaptive
    #                         severity_tier_category
    #                         prefix, ASCENDING: fewer defects is better. THE
    #                         PREFIX LEADS the key: it is the most direct
    #                         improvement signal, and the panel median is coarse.
    #                         The prefix stops when the cleanest ranked version
    #                         has `tiebreak_defect_floor` counts (default 10) or
    #                         every cell is included.
    #   -median               the field-wide panel statistic: the first
    #                         TIE-BREAK when two versions carry the same prefix.
    #   -mean                 consulted after the median (a total count is more
    #                         reliable than the mean of small integer scores).
    #   IQR, digest, id       deterministic fallbacks (the CONTENT DIGEST comes
    #                         before the id: a perfect tie must not be decided by
    #                         the arm's NAME, because a2 < i1 < w1 would silently
    #                         favour the revise arm on every such tie).
    # The self-reported critical_remaining/writing_remaining values are still
    # REPORTED (and cross-checked against the frozen review) but no longer rank:
    # the census is panel-derived, while those two are agent-authored.
    # vs_base (the panel's head-to-head against the incumbent) is REPORTED, and
    # the incumbent-retention rule below never lets a challenger the panel cannot
    # distinguish from the base retire it -- but it is deliberately NOT a ranking
    # key. Rationale (operator, 2026-09-21): that pair carries only 2*judges
    # directed scores, so ONE outlier session flips its sign statistic, while the
    # field-wide list carries 2*judges*(|field|-1) and is what the panel as a
    # whole measured. The margin is read by a human in the report; it does not
    # decide the round.
    # MANUAL_STEPS.md is NOT a ranking key: its size measures how much work the
    # pipeline hands to the author, so ranking on it would reward under-reporting.
    rows.sort(key=champion_sort_key)
    champ_row = rows[0]
    base_row = next((t for t in rows if t["is_base"]), None)
    if base_row is not None and champ_row is not base_row \
            and (champ_row["median"], champ_row["mean"], champ_row["iqr"]) == \
            (base_row["median"], base_row["mean"], base_row["iqr"]):
        # An exact statistical tie is not evidence of improvement: the incumbent
        # is retained rather than replaced by a version the panel cannot
        # distinguish from it (never reward a version merely for being different).
        # This is strictly a panel-statistic rule (median/mean/IQR) and it
        # OVERRIDES the leading defect prefix on purpose: a challenger with a
        # lower defect count but an identical (median, mean, IQR) does not retire
        # the incumbent -- a better defect count separates CHALLENGERS, it does
        # not retire an incumbent the panel cannot distinguish from them.
        trace.append(f"{champ_row['id']} and the base tie exactly on (median, mean, IQR) -> "
                     f"the incumbent base is retained; a challenger must be measurably better")
        champ_row = base_row
    trace.append(f"ranking key: (the cumulative defect count over the first "
                 f"{prefix_cells} cell(s) of the canonical severity_tier_category order "
                 f"(fatal->critical->major->minor, tier order, peer before own; the walk stops "
                 f"when the cleanest ranked version reaches the floor {floor} or all "
                 f"{len(cell_names)} cells are used) -- then -median, -mean, IQR, digest, id); "
                 "the cumulative counts come from the panel's own "
                 "census (the self-reported critical_remaining/writing_remaining values are "
                 "reported but no longer rank), median/mean/IQR are the field-wide panel "
                 "statistics below it, and the content digest is the provenance-free tie-break "
                 "(an arm's NAME never decides a tie). "
                 "An exact (median, mean, IQR) tie still keeps the incumbent base: that rule "
                 "overrides the prefix, so a different defect count separates challengers but "
                 "does not retire a base the panel cannot distinguish from them. "
                 "vs_base is reported but NOT a ranking key: its 2*judges directed scores are few "
                 "enough that one outlier session flips the sign statistic, so the decision stays "
                 "on the field-wide list. MANUAL_STEPS.md is reported but never ranked on; "
                 "missing counts sentinel = +inf")
    for i, t in enumerate(rows, 1):
        trace.append(f"  {i}. {t['id']}: median={t['median']:g} mean={t['mean']:.3f} "
                     f"vs_original={_g(t['vs_original'])} vs_base={_g(t['vs_base'])} "
                     f"defects@{prefix_cells}={t['defect_prefix_total']} "
                     + "(cf/maj/min peer+own="
                     + "/".join(f"{t['issues'][g]['peer']}+{t['issues'][g]['own']}"
                                for g in ("fatal", "critical", "major", "minor"))
                     + ") "
                     f"iqr={t['iqr']:g} critical_remaining={t['critical_remaining']} "
                     f"writing_remaining={t['writing_remaining']} "
                     f"manual_steps={t['manual_steps']} "
                     f"placeholders={t['author_placeholders'] or 0} "
                     f"n={t['n']} digest={str(t.get('digest') or 'n/a')[:12]} "
                     f"[{t.get('captions')}]")
    return {"champion": champ_row["id"], "champion_rep": champ_row["rep"],
            "base_rep": base_rep, "eligible": eligible, "ranking": rows, "trace": trace,
            "tiebreak": {"floor": floor, "cells_used": prefix_cells,
                         "cell_order": cell_names[:prefix_cells],
                         "cells_total": len(cell_names)}}


def _g(v) -> str:
    """Format a float-or-None stat for a trace line."""
    return f"{v:g}" if isinstance(v, (int, float)) else "n/a"


def _count_cell(v) -> str:
    """Format a tie-break count for the decision report ('-' when unknown).

    A missing count is the MISSING_TIEBREAK sentinel (+inf, "absence never wins
    a tie"), which must not be printed as a number -- in memory or in its strict-
    JSON spelling ("Infinity", which a reader that does not revive the sentinel
    hands back as a string).
    """
    if _missing_count(v) or not isinstance(v, (int, float)):
        return "-"
    return f"{v:g}"


def _missing_count(v) -> bool:
    """True when a reported count is absent (None, the +inf sentinel, or its JSON spelling)."""
    if v is None or isinstance(v, bool):
        return True
    if isinstance(v, float):
        return not math.isfinite(v)
    if isinstance(v, str):
        return v.strip().lower() in ("", "infinity", "+infinity", "-infinity", "inf", "nan")
    return False


def round_member_table_rows(ctx: Ctx, r: int, field: list, agg: dict, sel: dict,
                            champ_rep: str) -> list:
    """The run's per-member summary table (header row, then one row per member).

    Every member gets its three evidence columns filled from the round's own
    records: `defects@K` and the severity totals come from the panel's issue
    census -- the SAME numbers the ranking reads, over the SAME adaptive prefix
    -- and `writing*` falls back to the round's frozen review for the rows that
    have no producing session to self-report it (the pristine original, the
    round's base), then to the producing run's own marker for an arm the ranking
    did not admit. A '-' therefore means "this root genuinely has no record",
    not "this member was not ranked".
    """
    st = agg["stats"]
    ranking_by_id = {row["id"]: row for row in (sel.get("ranking") or [])}
    for row in (sel.get("ranking") or []):
        if row.get("rep"):
            # the base row carries the stats of the content-identical member it
            # stands for (a1 -> orig in round 1, a1 -> the previous champion later)
            ranking_by_id.setdefault(str(row["rep"]), row)
    # Column order = the champion-selection key order (`champion_sort_key`):
    # defect prefix -> median -> mean -> IQR -> digest -> id. The id is the row
    # label; every column after the digest is REPORTED only and never ranked.
    rows = [["member", "defects@K", "median", "mean", "IQR", "digest", "n/expected",
             "vs_orig", "vs_base", "severity totals f/c/maj/min", "writing*", "hand-off",
             "note"]]
    census = (agg or {}).get("issue_census") or {}
    for e in field:
        s = st[e["id"]]
        note = ""
        if e["id"] == champ_rep:
            note = "CHAMPION" if sel.get("champion") == e["id"] else \
                f"CHAMPION (=base {sel.get('champion')})"
        elif s.get("anti_regression_ok") is False:
            note = "ineligible (regressed vs original)"
        rank_row = ranking_by_id.get(e["id"]) or {}
        if rank_row.get("issues"):
            iss = rank_row["issues"]
        elif str(e["id"]) in census:
            iss = champion_issue_summary(e["id"], agg)
        else:
            iss = {}
        if iss:
            def _iss(sev):
                d = iss.get(sev) or {}
                return int(d.get("own") or 0) + int(d.get("peer") or 0)
            severity_cell = "/".join(str(_iss(sev))
                                     for sev in ("fatal", "critical", "major", "minor"))
        else:
            severity_cell = "-"
        prefix = rank_row.get("defect_prefix_total")
        if prefix is None:
            prefix = census_prefix_total(agg, sel, e["id"])
        writing = rank_row.get("writing_remaining")
        if _missing_count(writing):
            if rank_row.get("is_base") or e["id"] == A1_ID:
                # the round's review inspected exactly this package (the base)
                writing = round_writing_remaining(ctx, r)
            elif e["id"] == ORIGINAL_ID:
                writing = original_writing_remaining(ctx, r, agg)
            elif is_fresh_vid(e["id"]):
                writing = candidate_tiebreak_inputs(ctx, r, e["id"])[1]
        rows.append([e["id"],
                     f"{prefix}" if prefix is not None else "-",
                     f"{s['median']:g}" if s["median"] is not None else "-",
                     f"{s['mean']:.2f}" if s.get("mean") is not None else "-",
                     f"{s['iqr']:g}" if s["iqr"] is not None else "-",
                     (str(s.get("digest") or "")[:12] or "-"),
                     f"{s['n']}/{s['expected_n']}",
                     f"{s['vs_original']:g}" if s["vs_original"] is not None else "-",
                     f"{s['vs_base']:g}" if s.get("vs_base") is not None else "-",
                     severity_cell, _count_cell(writing),
                     f"{s.get('author_placeholders') or 0}", note])
    return rows


def pin_champion(ctx: Ctx, r: int, champ_id: str, agg: dict) -> dict:
    """Copy the round's champion into pinned/<r>_<champion_id>/ and register it.

    The pinned set grows monotonically and is deduplicated by content digest,
    so it may be smaller than the number of rounds -- that is correct.
    The documents/ directory is swapped in atomically so a retried round can
    never leave a mix of old and new pinned content on disk.
    """
    pid = pin_id_for(r, champ_id)
    dst = ctx.pins_dir / pid
    docs = dst / "documents"
    tmp = dst / "documents.tmp"
    if tmp.exists():
        rmtree_force(tmp)
    build_corpus_dir(ctx, r, champ_id, tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    manifest = corpus_dir_manifest(tmp)  # the run digest's rule
    if not manifest["count"]:
        die(f"refusing to pin '{champ_id}': its corpus is empty (no documents were found in "
            f"{', '.join(str(s) for s, _p, _e in corpus_sources(ctx, r, champ_id)) or 'no source'})")
    digest = manifest_digest(manifest)
    recorded = recorded_version_digest(ctx, r, champ_id)
    if recorded and digest != recorded:
        die(f"internal inconsistency: the pinned copy of '{champ_id}' hashes to {digest[:12]} "
            f"but its run recorded {str(recorded)[:12]}")
    if docs.is_dir() and corpus_tree_digest(docs) == digest:
        rmtree_force(tmp)          # idempotent resume: identical already
    else:
        if docs.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            superseded = unique_path(ctx.pins_dir / "_superseded" / f"{pid}.{stamp}")
            superseded.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(docs), str(superseded))
        os.replace(tmp, docs)
    st = stats_row_for(agg, champ_id)
    cap_info = caption_info_for(ctx, r, champ_id) or scan_captions_in_sources(
        [(docs, "", ())], limit=caption_limit_of(ctx))
    meta = {"id": pid, "round": int(r), "source_id": champ_id, "digest": digest,
            "content_fingerprint": effective_content_fingerprint(ctx, r, champ_id),
            "produced_by_run": rid_for_fresh(r, champ_id) if is_fresh_vid(champ_id) else None,
            "created": utcnow(),
            "champion_stats": {k: st.get(k) for k in ("n", "median", "mean", "iqr",
                                                      "vs_original", "vs_base",
                                                      "anti_regression_ok",
                                                      "author_placeholders")},
            "captions": cap_info,
            "placeholders": placeholder_info_for(ctx, r, champ_id)}
    write_json_atomic(dst / "meta.json", meta)
    cur = find_pin(ctx, pid)
    if cur is None:
        ctx.state["pinned"].append(meta)
        ctx.log("pinned", pid, digest)
    else:
        for i, p in enumerate(ctx.state["pinned"]):
            if p.get("id") == pid:
                ctx.state["pinned"][i] = meta
    return meta


def find_winner(ctx: Ctx, r: int) -> dict:
    """The published-winner record for a round (reports/round<r>_winner.json)."""
    rec = read_json(ctx.reports_dir / f"round{int(r)}_winner.json")
    return rec if isinstance(rec, dict) else {}


def publish_winner(ctx: Ctx, r: int, champ_id: str, pin: dict, agg: dict) -> dict:
    """Publish the round's winner as <root>/round<r>_winner/ (documents at its
    top level), in addition to the content-addressed pin.

    This is the copy a human opens, so it must never drift from what the judges
    scored and what the next round's base was built from: the digest is
    verified against the pin's, the swap is atomic, and a displaced copy is
    archived under <root>/_superseded/ rather than deleted.
    """
    dst = winner_dir_of(ctx, r)
    tmp = ctx.root / (WINNER_DIR_FMT.format(r=int(r)) + ".tmp")
    if tmp.exists():
        rmtree_force(tmp)
    build_corpus_dir(ctx, r, champ_id, tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    manifest = corpus_dir_manifest(tmp)  # the run digest's rule
    if not manifest["count"]:
        die(f"refusing to publish a round {r} winner: the champion '{champ_id}' has an empty "
            f"corpus")
    digest = manifest_digest(manifest)
    if pin.get("digest") and digest != pin["digest"]:
        die(f"internal inconsistency: the round {r} winner copy hashes to {digest[:12]} but its "
            f"pin recorded {str(pin.get('digest'))[:12]}")
    if dst.is_dir() and corpus_tree_digest(dst) == digest:
        rmtree_force(tmp)                      # idempotent resume: identical already
    else:
        if dst.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            aside = unique_path(superseded_dir_of(ctx) / f"{dst.name}.{stamp}")
            aside.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(aside))
        os.replace(tmp, dst)
    st = stats_row_for(agg, champ_id)
    rec = {"round": int(r), "winner_id": champ_id, "directory": dst.name, "digest": digest,
           "pin": pin.get("id"), "created": utcnow(),
           "stats": {k: st.get(k) for k in ("n", "median", "mean", "iqr", "vs_original",
                                            "vs_base", "anti_regression_ok",
                                            "author_placeholders")},
           "note": "this is the same content as the round's pin; both are verified by "
                   "`run`/`decide`, and any mismatch is refused"}
    write_json_atomic(ctx.reports_dir / f"round{int(r)}_winner.json", rec)
    ctx.log("winner-published", dst.name, f"winner={champ_id} digest={digest[:12]}")
    return rec


def finalize_round(ctx: Ctx, r: int, field: list, dropped: list, agg: dict,
                   sel: dict, pin: dict) -> dict:
    rrec = ctx.round_rec(r)
    winner = find_winner(ctx, r) or {}
    # Freeze the ranking inputs that produced this decision. `decide` re-derives
    # the ranking from them, so pruning old sandboxes cannot flip a champion.
    tiebreak_inputs = {row["id"]: {"critical_remaining": row.get("critical_remaining"),
                                   "writing_remaining": row.get("writing_remaining"),
                                   "manual_steps": row.get("manual_steps")}
                       for row in (sel.get("ranking") or [])}
    # A round that is decided now is no longer "pending because the panel was
    # short": stale panel_gaps would otherwise make `status` and the decision
    # report claim the round was never decided.
    rrec.pop("panel_gaps", None)
    m, n = round_counts(ctx, r)
    # Freeze the WHOLE plan, not only the rewrite/revise counts: the integrator
    # mask decides which integration arms exist, and the judge count decides the
    # panel every row must complete. `decide` recomputes both, so a later config
    # edit must not look like a missing arm / a stale panel.
    mask = round_integrators(ctx, r)
    integrated = round_integrated_run_ids(ctx, r, m, n)
    csel = str(sel.get("champion_select") or round_champion_select(ctx, r))
    auto_promoted = bool(sel.get("auto_promoted"))
    rrec.update({
        "status": "done", "completed": utcnow(),
        "plan": {"rewrites": m, "revises": n, "pool": round_pool_ids(m, n),
                 "integrated": integrated, "integrators": mask,
                 "review_scope": round_review_scope(ctx, r),
                 "judges": round_judges(ctx, r),
                 "champion_select": csel,
                 "judges_enabled": judges_enabled_spec(ctx, r) or JUDGES_ENABLED_ALL},
        "field": [e["id"] for e in field],
        "field_entries": field, "field_dropped": dropped,
        "field_size": agg["field_size"], "scores_per_version": agg["scores_per_version"],
        "stats": agg["stats"], "diagnostics": agg["diagnostics"], "selection": sel,
        "base_id": agg.get("base_id"), "base_rep": agg.get("base_rep"),
        "auto_promoted": auto_promoted, "judged": not auto_promoted,
        "certified": False if auto_promoted else rrec.get("certified"),
        "champion": sel["champion"],
        "champion_rep": sel.get("champion_rep") or sel["champion"],
        "champion_run": (rid_for_fresh(r, sel["champion"]) if is_fresh_vid(sel["champion"])
                         else None),
        "pin_id": pin["id"], "pin_path": f"{PIN_DIRNAME}/{pin['id']}",
        "pin_digest": pin["digest"],
        "winner_dir": winner.get("directory"),
        "winner_digest": winner.get("digest"),
        "tiebreak_inputs": tiebreak_inputs,
        "pipeline_version": VERSION,
    })
    write_json_atomic(ctx.reports_dir / f"round{r}.json",
                      {"round_record": rrec, "aggregation": agg, "selection": sel})
    # Keep this round's review deliverables (finding list, discovery output) so the
    # next round can carry them forward and the operator keeps them after a prune.
    try:
        archive_review_outputs(ctx, r)
    except Exception as e:                                      # noqa: BLE001
        print(f"[run] round {r} WARNING: could not archive the review outputs: {e}")
    ctx.log("round-done", f"round{r}", f"champion={sel['champion']} pin={pin['id']}")
    return rrec


# =====================================================================
# STALENESS / INVALIDATION
# =====================================================================

def round_is_done(ctx: Ctx, r: int) -> bool:
    return ctx.round_rec(r).get("status") == "done"


def sweep_artifacts(ctx: Ctx, cmd: list = None, timeout: int = 0) -> list:
    """Adopt runs left pending whose completion signal already exists (manual-mode
    completions, or a previous crashed orchestrator).

    The signal is the agent-written marker (rewrite/review/revise/integrate) or a parseable
    scores.json (judge) -- never a bare non-empty output directory.

    An adopted run whose postcheck fails on REPAIRABLE bookkeeping gets the same one
    scoped repair session any other attempt gets (`cmd` is the round's agent
    command): a finished 45-minute review must not be discarded because two seeded
    tables were left undisposed, which is exactly what the 2026-09-22 roots did.
    """
    adopted = []
    for rec in ctx.runs():
        if rec["status"] != "pending" or rec["kind"] == "a1":
            continue
        if not completion_signal_exists(ctx, rec):
            continue
        bump_attempt(rec)
        postcheck(ctx, rec, source="adopted (completion signal already on disk)")
        if rec["status"] != "done" and cmd:
            problems = repairable_artifact_failure(ctx, rec)
            if problems:
                run_repair_session_now(ctx, rec, problems, cmd, timeout)
        adopted.append(rec["id"])
        print(f"[sweep] {rec['id']}: {'done' if rec['status'] == 'done' else 'FAILED'} "
              f"({'; '.join((rec.get('postcheck') or {}).get('errors', []))[:160] or 'ok'})")
    if adopted:
        ctx.log("sweep-adopted", detail=", ".join(adopted))
        ctx.save_state()
    return adopted


def invalidate_from_round(ctx: Ctx, r: int, reason: str) -> list:
    """Reset round r and every later round; their pins are dropped from state.

    Pinned DIRECTORIES stay on disk as archives (nothing is deleted), but they
    no longer participate in any field: the content-addressed chain is rebuilt
    from round r onwards. Downstream runs are marked stale so the next `run`
    rebuilds their sandboxes from the new content.
    """
    R = ctx.rounds_count()
    touched = []
    for rr in range(int(r), int(R) + 1):
        rec = ctx.round_rec(rr)
        # A round that is being rebuilt must not leave a stale "winner" sitting
        # under --root: archive the published copy (and its record) instead.
        published = ctx.root / (rec.get("winner_dir") or WINNER_DIR_FMT.format(r=int(rr)))
        wjson = ctx.reports_dir / f"round{int(rr)}_winner.json"
        if published.is_dir() or wjson.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            aside = unique_path(superseded_dir_of(ctx) / f"round{int(rr)}_winner.{stamp}")
            aside.mkdir(parents=True, exist_ok=True)
            if published.is_dir():
                shutil.move(str(published), str(aside / published.name))
            if wjson.exists():
                shutil.move(str(wjson), str(aside / wjson.name))
        rec["status"] = "pending"
        for k in ("champion", "champion_rep", "champion_run", "pin_id", "pin_path", "pin_digest",
                  "field", "field_entries", "field_dropped", "stats", "selection", "diagnostics",
                  "completed", "winner_dir", "winner_digest", "tiebreak_inputs", "panel_gaps",
                  "base_id", "base_rep", "plan", "pipeline_version",
                  "judges_enabled", "auto_promoted", "judged", "certified"):
            rec.pop(k, None)
        for run_rec in ctx.runs(round_no=rr):
            touched.append(run_rec["id"])
            if run_rec["status"] == "done":
                run_rec["status"] = "stale"
                run_rec["last_error"] = f"stale: {reason}"
                run_rec["stale_reason"] = reason
                # The accepted package may be rebuilt; its post-revise chain
                # record describes the old bytes and must not suppress the
                # chain on the next acceptance.
                run_rec.pop("revision_audit", None)
                run_rec.pop("revision_repair", None)
    ctx.state["pinned"] = [p for p in (ctx.state.get("pinned") or [])
                           if int(p.get("round") or 0) < int(r)]
    ctx.log("invalidated-from-round", detail=f"round {r}: {reason}")
    return touched


def reconcile_inputs(ctx: Ctx) -> tuple:
    """Content-addressed staleness check.

    Every completed run's read-only inputs (and, for content-producing runs,
    its deliverable corpus) are re-hashed against what was recorded when the
    sandbox was built. A mismatch in an INCOMPLETE round marks the run stale so
    the next `run` rebuilds it; a mismatch inside a COMPLETED round is a
    blocking error, because that round's champion (and every pin chained onto
    it) would otherwise be silently mixed with content that changed.
    """
    stale, blocking = [], []
    for rec in ctx.runs():
        if rec["kind"] == "a1" or rec["status"] != "done":
            continue
        probs = run_input_problems(ctx, rec)
        if not probs:
            continue
        detail = "; ".join(probs)[:500]
        if round_is_done(ctx, rec["round"]):
            blocking.append(f"{rec['id']} (round {rec['round']}): {detail}")
        else:
            rec["status"] = "stale"
            rec["last_error"] = f"stale: {detail}"
            rec["stale_reason"] = detail
            rec.pop("revision_audit", None)
            rec.pop("revision_repair", None)
            stale.append(rec["id"])
    if stale:
        ctx.log("stale-marked", detail=", ".join(stale))
    return stale, blocking


def run_input_problems(ctx: Ctx, rec: dict) -> list:
    """Read-only integrity problems for one completed run's frozen inputs.

    Shared by `reconcile_inputs` (which marks incomplete rounds stale) and
    `evidence_integrity` (which lets `decide` audit the on-disk evidence
    without mutating anything).

    A sandbox that is no longer on disk (pruned with `prune`, or removed by
    hand) yields NO problem: its inputs cannot be verified any more, which is
    not the same statement as "they changed". `evidence_integrity` reports that
    situation as `missing` for the same reason, and calling it a content change
    here made `prune` permanently block every later `run` (the affected runs are
    already `done`, so there was no failing run for `retry` to reset either).
    """
    if hash_checks_skipped():
        # `--skip-hash`: neither `reconcile_inputs` nor `evidence_integrity` can
        # see drift; both report the skip through hash_skip_note().
        return []
    if not ctx.sandbox_of(rec).is_dir():
        return []
    probs = input_mismatches(ctx, rec)
    if rec["kind"] in ("rewrite", "revise", "integrate") and rec.get("corpus_digest"):
        cur = recompute_corpus_digest(ctx, rec["round"], freshness_vid(rec))
        if cur != rec["corpus_digest"]:
            probs.append(f"deliverable corpus changed after the run "
                         f"({cur[:12]} != {str(rec['corpus_digest'])[:12]})")
    if rec["kind"] == "judge":
        tid = rec.get("target_id")
        if rec.get("target_digest") and tid:
            cur = recompute_corpus_digest(ctx, rec["round"], tid)
            if cur != rec["target_digest"]:
                probs.append(f"target version '{tid}' changed after this judge ran "
                             f"({cur[:12]} != {str(rec['target_digest'])[:12]})")
        for fd in rec.get("field_digests") or []:
            if not fd.get("digest"):
                continue
            cur = recompute_corpus_digest(ctx, rec["round"], fd["id"])
            if cur != fd["digest"]:
                probs.append(f"field member '{fd['id']}' changed after this judge ran "
                             f"({cur[:12]} != {str(fd['digest'])[:12]})")
    return probs


def evidence_integrity(ctx: Ctx) -> tuple:
    """Non-mutating audit of every completed run's frozen inputs and outputs.

    Returns (changed, missing). `decide` treats `changed` as a hard problem
    (exit 5) because a sandbox edited after a round -- which `run` would already
    refuse to continue from -- must not be presented as the decision's evidence.
    A sandbox that was deleted (e.g. to reclaim disk) is reported as `missing`
    instead: the audit cannot verify it, but pruning old sandboxes is a normal
    operation, so it does not fail the decision.
    """
    changed, missing = [], []
    for rec in ctx.runs():
        if rec["kind"] == "a1" or rec["status"] != "done":
            continue
        if not ctx.sandbox_of(rec).is_dir():
            missing.append(f"{rec['id']}: sandbox is missing (evidence not verifiable)")
            continue
        for prob in run_input_problems(ctx, rec):
            changed.append(f"{rec['id']}: {prob}")
    return changed, missing


def decide_advisories(ctx: Ctx) -> dict:
    """Advisory roll-ups for the decision report (never scoring inputs).

    Two facts about a version are worth seeing next to the decision even though
    neither may change a score: files an agent DROPPED and the orchestrator
    restored (`backfill`), and runs that ended without a completed visual
    verification. Reporting them here is what keeps "the invariant was restored
    mechanically" from quietly erasing how it was broken.
    """
    recovery, visual = [], []
    for rec in ctx.runs():
        restored = ((rec.get("backfill") or {}).get("restored") or [])
        if restored:
            recovery.append({"run": rec.get("id"),
                             "version": rec.get("produces") or rec.get("id"),
                             "count": len(restored), "files": sorted(restored)[:8]})
        warns = ((rec.get("postcheck") or {}).get("warnings") or [])
        if any(("not visually verified" in str(w).lower()
                or "no pdf renderer" in str(w).lower()) for w in warns):
            visual.append(rec.get("id"))
    return {"recovery": recovery, "visual_not_verified": sorted(visual)}


# =====================================================================
# EXECUTION ENGINE
# =====================================================================

def resolve_agent_cmd(agent_name: str, agent_cmd_arg: str, use_env: bool = True):
    if agent_cmd_arg:
        try:
            cmd = json.loads(agent_cmd_arg)
            if isinstance(cmd, list) and cmd:
                return [str(x) for x in cmd]
        except ValueError:
            pass
        die("--agent-cmd must be a JSON argv list, e.g. '[\"myagent\",\"--flag\"]'")
    env = os.environ.get("PAPER_AGENT_CMD") if use_env else None
    if env:
        try:
            cmd = json.loads(env)
            if isinstance(cmd, list) and cmd:
                return [str(x) for x in cmd]
        except ValueError:
            pass
        die("PAPER_AGENT_CMD is set but is not a valid JSON argv list")
    if agent_name in AGENT_PRESETS:
        # Not AGENT_PRESETS directly: a codex session also needs the MCP
        # approval overrides, or its tools are denied before the model can use
        # them (see MCP_APPROVALS). The preset's CLI is then read for the one
        # capability a preset cannot express as a flag: the DeepSeek Harness's
        # one-shot form (see dsh_harness_problem).
        argv = agent_argv(agent_name)
        if agent_name == "qwen" and argv and not Path(argv[0]).is_file():
            # A frozen root's own driver cannot run sync-code (it refuses by
            # design), so name the maintained checkout when we can identify it.
            _snap = frozen_snapshot_root()
            _origin = str((_snap or {}).get("origin_path") or "")
            _where = (f"python3 {shlex.quote(_origin)} sync-code --root <root>"
                      if _origin and Path(_origin).is_file()
                      and not frozen_snapshot_root(_origin)
                      else "run `sync-code` from the maintained checkout -- not from this "
                           "root's frozen paper_pipeline.py")
            die(f"the qwen adapter is missing next to the driver: {argv[0]}\n"
                f"       A root created before the adapter existed must be synced first:\n"
                f"       {_where}\n"
                f"       (or recreate the root from the maintained tree).")
        harness_problem = dsh_harness_problem(argv)
        if harness_problem:
            die(harness_problem)
        return argv
    die(f"unknown agent '{agent_name}'; use {'|'.join(AGENT_CHOICES)}, PAPER_AGENT_CMD, "
        f"or --agent-cmd")


def _probe_dsh_headless(exe: str) -> str:
    """Read the installed harness's own headless help ('' = it declares the contract).

    `dsh --profile headless --help` boots the profile and prints the one-shot
    app's own flags, which is exactly the property being checked; the boot also
    initializes a fresh $DSH_HOME once, serially, before the parallel wave (the
    harness does that on its first session anyway). Every failure mode of the
    probe itself -- the binary vanished, it hangs, it prints something we cannot
    read -- reports '' (see dsh_harness_problem).
    """
    try:
        proc = subprocess.run([exe, "--profile", "headless", "--help"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace", timeout=180)
    except Exception:                                                # noqa: BLE001
        return ""
    text = proc.stdout or ""
    # The harness is a Node >= 22 application (`node:util` parseEnv): under an
    # older `node` on PATH it dies at import, and the box's own node may well be
    # the older one while the harness was installed by a newer one. That crash
    # names its own version, so it is read and reported -- otherwise every
    # session would fail with the same stack trace inside its own log.
    node = re.search(r"Node\.js v(\d+)\.", text)
    if node and int(node.group(1)) < 22:
        return ("the DeepSeek Harness cannot start under the `node` on PATH: `dsh` ran on "
                f"Node.js v{node.group(1)}, and the harness needs node >= 22 (its first "
                "import uses `node:util` parseEnv).\n"
                "       Install AND run it under the same newer node (`nvm use 22` && "
                "`npm i -g @deepseek-ai/dsh@alpha`, then run the pipeline with node 22 first "
                "on PATH), or run the stages on another backend (--agent codex|claude|manual, "
                "or --agent-cmd)")
    # The other half of the same mistake: the harness IS started by a newer node
    # than the one it was installed for, so its native binding does not match
    # (`npm i -g` under node 18, then a node-22 PATH). The package's own error
    # names it; the fix is a reinstall under the node that will run it.
    if "no usable native binding" in text.lower():
        return ("the DeepSeek Harness on PATH was installed for a different Node.js ABI than "
                "the `node` running it (`dsh: host preparation failed: No usable native "
                "binding found ...`), so it cannot boot.\n"
                "       Reinstall it under the node the pipeline will use (`nvm use 22` && "
                "`npm i -g @deepseek-ai/dsh@alpha`), or run the stages on another backend "
                "(--agent codex|claude|manual, or --agent-cmd)")
    if "headless" not in text.lower():
        return ""                        # not the app this preset speaks to: say nothing
    if "--json" in text and "stdin" in text:
        return ""
    # Name the half that is MISSING: the predicate refuses a build that lacks
    # either one, and reporting "declares neither" for a build that does carry
    # `--json` sent the operator looking for a flag it already answers.
    if "--json" not in text and "stdin" not in text:
        missing = "neither `--json` nor the stdin task form (`-`)"
    elif "--json" not in text:
        missing = "no `--json` flag (the event stream that carries the session id)"
    else:
        missing = "no stdin task form (`-`)"
    return ("the installed DeepSeek Harness cannot run this pipeline's sessions: "
            f"`dsh --profile headless` declares {missing} in its own help, so every "
            "session of this backend would fail with a usage error.\n"
            "       Upgrade it (`npm i -g @deepseek-ai/dsh@alpha`; the contract is "
            "verified against dsh 0.2.1-alpha.4 and 0.2.0-rc.2), run the stages on another "
            "backend (--agent codex|claude|manual), or point --agent-cmd at your own CLI")


_HARNESS_PROBE_CACHE = {}


def dsh_harness_problem(cmd) -> str:
    """Why the PRESET's harness argv cannot run a session ('' = no problem found).

    A preset can pin flags, not capabilities: `dsh` drives the harness's
    one-shot driver (the task on stdin, the `--json` event stream that carries
    the session id a continuation adopts), and only the BUILDS whose headless
    app declares that contract can honor it. A `dsh` that predates it would
    fail every session of a wave with the same usage error, so the argv is
    probed once per invocation and the gap is named before any session starts.
    Only a positive finding stops the run; a probe that cannot read the help
    (a custom --agent-cmd, a wrapper, a hang, a missing binary) reports '' and
    lets the sessions speak for themselves.

    The answer is cached per RESOLVED BINARY (what `dsh` resolves to on PATH,
    plus the argv), not per name: a process that changes PATH between calls gets
    the verdict for the binary it is about to run, never another one's.
    """
    argv = [str(x) for x in (cmd or [])]
    exe = argv[0] if argv else ""
    key = (shutil.which(exe) or exe, tuple(argv))
    if key not in _HARNESS_PROBE_CACHE:
        if argv and os.path.basename(argv[0]).lower() == str(AGENT_PRESETS["dsh"][0]):
            _HARNESS_PROBE_CACHE[key] = _probe_dsh_headless(argv[0])
        else:
            _HARNESS_PROBE_CACHE[key] = ""
    return _HARNESS_PROBE_CACHE[key]


def agent_install_hint(cmd) -> str:
    """The extra guidance line for a preset whose CLI is not installed ('' if none).

    The Codex/Claude CLIs an operator already runs need no explanation; the
    DeepSeek Harness is a separate install (`dsh`), and its one-shot form is a
    property of the installed build -- so the "executable not found" errors name
    both the package and the npx form that needs no global install. Only a
    preset's own binary is answered for: a custom --agent-cmd points wherever
    the operator meant it to.
    """
    name = os.path.basename(str(cmd[0])).lower() if cmd else ""
    if name == str(AGENT_PRESETS["dsh"][0]):
        return ("\n       the DeepSeek Harness CLI (`dsh`, node >= 22) is not installed: "
                "`npm i -g @deepseek-ai/dsh@alpha`. Its own home ($DSH_HOME, default ~/.dsh) "
                "holds the model, the MCP servers and the DeepSeek credential "
                "(DEEPSEEK_API_KEY)")
    return ""


def _coerce_text(s) -> str:
    if s is None:
        return ""
    if isinstance(s, bytes):
        return s.decode("utf-8", "replace")
    return str(s)


def _terminate_agent_tree(proc: subprocess.Popen) -> None:
    """Kill an agent session's WHOLE process group (see _execute_attempt_in).

    A timeout used to kill only the direct child: a codex/claude helper, a
    shell wrapping a build or a PowerShell/Word COM helper kept running, kept
    consuming CPU/quota and could keep writing into the sandbox after it had
    been renamed aside and a fresh attempt started. The session is started with
    `start_new_session=True`, so SIGTERM (then SIGKILL) to its process group
    reaches every descendant that did not deliberately leave the group.
    """
    # os.getpgid/os.killpg are POSIX-only: on native Windows the attribute is
    # MISSING (AttributeError, not OSError), so a timed-out agent raised out of
    # the timeout handler and its tree kept running. The group kill happens only
    # where both calls exist; elsewhere proc.terminate()/proc.kill() is the
    # portable fallback.
    pgid = None
    if hasattr(os, "getpgid") and hasattr(os, "killpg"):
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = None
    try:
        if pgid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if pgid:
            os.killpg(pgid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _execute_attempt_in(sb: Path, rec: dict, cmd: list, timeout: int,
                        prompt_name: str = PROMPT_FILE, log_name: str = "_agent.log",
                        archive_marker: bool = True) -> dict:
    """Run one agent session in `sb` and return {rc, dur, error, log}.

    `prompt_name`/`log_name` let the scoped ARTIFACT-REPAIR session use its own
    prompt and its own transcript, and `archive_marker=False` keeps it from
    moving the stage attempt's completion marker aside: the repair edits the
    deliverables the postcheck reads, and that marker is one of them.
    """
    prompt = (sb / prompt_name).read_text(encoding="utf-8")
    logf = sb / log_name
    if archive_marker:
        # A previous attempt's marker must never be mistaken for this attempt's result.
        archive_stale_marker(sb, rec["id"])
    t0 = time.time()
    # The header is WRITTEN after the agent returns (the log is appended once), so
    # it must carry the time the attempt actually started -- it used to print
    # `utcnow()` at the end and call it "start", which made a 20-minute attempt
    # look like it began when it finished.
    started_at = utcnow()
    rec["last_attempt_started"] = started_at
    rc, out, err, exc = None, "", "", None
    try:
        # Popen + a process GROUP, not subprocess.run: a timeout must kill the
        # agent's descendants too (see _terminate_agent_tree).
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=str(sb), text=True,
                                encoding="utf-8", errors="replace",
                                start_new_session=True)
    except FileNotFoundError as e:
        proc = None
        # The same install hint the run banner's "not on PATH" errors carry: a
        # command that stages ONE session (conform, add-venue, the template-first
        # stage, the audits) reports the gap on this attempt's record instead, and
        # a missing DeepSeek Harness is not self-explanatory the way a missing
        # `codex` is.
        rc, exc = None, f"agent executable not found: {e}" + agent_install_hint(cmd)
    except Exception as e:  # noqa: BLE001
        proc = None
        rc, exc = None, f"execution error: {e}"
    if proc is not None:
        try:
            out, err = proc.communicate(input=prompt, timeout=(timeout or None))
            rc, exc = proc.returncode, None
        except subprocess.TimeoutExpired as e:
            _terminate_agent_tree(proc)
            rc, exc = None, f"TIMEOUT after {timeout}s"
            out, err = _coerce_text(e.stdout), _coerce_text(e.stderr)
        except Exception as e:  # noqa: BLE001
            _terminate_agent_tree(proc)
            rc, exc = None, f"execution error: {e}"
        out, err = _coerce_text(out), _coerce_text(err)
    dur = time.time() - t0
    try:
        with open(logf, "a", encoding="utf-8") as f:
            f.write(f"\n===== attempt {next_attempt_number(rec)} start {started_at} =====\n")
            f.write(f"cmd: {' '.join(cmd)}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n")
            f.write(f"===== rc={rc} dur={dur:.1f}s error={exc} =====\n")
    except OSError:
        pass
    failure_kind = ""
    if rc not in (0, None):
        # BOTH streams, unconditionally: a CLI that puts the provider's 413 on
        # stdout and an unrelated warning on stderr used to be classified as ""
        # because the stdout scan ran only when stderr was empty, and the retry
        # then resumed the same oversized session. The patterns are anchored to
        # error-shaped lines, so scanning stdout does not flag a manuscript that
        # merely mentions "payload too large".
        failure_kind = agent_failure_kind(out, err)
    if failure_kind == "context_overflow":
        exc = ("the agent request exceeded the provider's payload/context limit "
               "(HTTP 413 / request too large); a continuation would resend the same "
               "oversized context, so a fresh attempt is required")
    return {"rc": rc, "dur": dur, "error": exc, "log": str(logf),
            "failure_kind": failure_kind}


def execute_wave(ctx: Ctx, ids: list, cmd: list, timeout: int, jobs: int) -> dict:
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = {}
        for rid in ids:
            rec = ctx.run(rid)
            futs[ex.submit(_execute_attempt_in, ctx.sandbox_of(rec), rec, cmd, timeout)] = rid
        for fut in as_completed(futs):
            rid = futs[fut]
            try:
                results[rid] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[rid] = {"rc": None, "dur": 0.0, "error": f"executor error: {e}",
                                "log": None}
    return results


def apply_results(ctx: Ctx, results: dict) -> None:
    for rid in sorted(results, key=nat_key):
        res = results[rid]
        rec = ctx.run(rid)
        bump_attempt(rec)
        rec["started"] = rec["started"] or utcnow()
        rec["last_duration"] = round(res.get("dur") or 0.0, 1)
        if res.get("error") or res.get("rc") not in (0,):
            rec["status"] = "failed"
            rec["last_error"] = (res.get("error") or f"agent exited rc={res.get('rc')}")[:600]
            rec["last_failure_kind"] = str(res.get("failure_kind") or "")
            # The process died mid-session: its CLI session id is still in the
            # transcript, and a continuation may finish the work it started.
            sid = capture_agent_session_id(ctx, rec)
            if sid:
                rec["agent_session_id"] = sid
            # A PROCESS-level failure never reaches a postcheck, but it is an
            # attempt exactly like a failed one: record it, so the operator can
            # still see why it ended and where its artifacts/transcript went.
            record_attempt(ctx, rec, False, [rec["last_error"]], [], source="process")
            print_failure(rid, [rec["last_error"]], note="the agent process failed")
        else:
            rec["last_failure_kind"] = ""
            postcheck(ctx, rec)
            if rec["status"] == "done":
                print(f"  [ok]   {rid} done ({fmt_dur(res.get('dur'))})"
                       + (f"  warnings: {'; '.join(rec['postcheck']['warnings'])[:120]}"
                          if rec["postcheck"]["warnings"] else ""))
            else:
                print_failure(rid, rec["postcheck"]["errors"])
        ctx.save_state()


def print_failure(rid: str, errors, note: str = "") -> None:
    """EVERY problem of one failed attempt, one per line, in full.

    The old line joined the postcheck's messages and cut the result at 140
    characters, so an attempt that failed on three artifacts reported one of them
    and half a sentence of it -- the other two were only in state.json. Nothing
    is cut now: the console (and therefore the run log under reports/) carries the
    complete list, which is also what state.json `attempts_log` and the attempt's
    archive hold.
    """
    msgs = [str(e) for e in (errors or [])]
    print(f"  [FAIL] {rid}: {len(msgs)} problem(s)" + (f" -- {note}" if note else ""))
    for m in msgs:
        print(f"        - {m}")


def manual_run_one(ctx: Ctx, rec: dict, poll: int, timeout: int) -> None:
    sb = ctx.sandbox_of(rec)
    print()
    print("=" * 72)
    print(f"MANUAL RUN: {rec['id']}   (round {rec['round']}, kind: {rec['kind']})")
    print(f"  sandbox : {sb.resolve()}")
    print(f"  prompt  : {(sb / 'PROMPT.md').resolve()}")
    print("  action  : open PROMPT.md, paste its FULL text into your agent, with the")
    print("            agent's working directory set to the sandbox above.")
    if leftovers_present(ctx, rec):
        print("  NOTE    : this sandbox already contains work. If you already started an")
        print("            agent here, do NOT start another one -- just wait for it to finish.")
        print("            If it died, Ctrl-C and reset this run with `retry --run "
              f"{rec['id']}`.")
    print("  expected: " + ("a parseable scores.json (the judge completion signal)"
                           if rec["kind"] == "judge"
                           else f"{MARKER_FILE} written LAST (a non-empty output directory is "
                                f"NOT treated as completion)"))
    print("=" * 72)
    t0 = time.time()
    last_note = 0.0
    malformed_sig = None
    try:
        while not completion_signal_exists(ctx, rec):
            if timeout and (time.time() - t0) > timeout:
                bump_attempt(rec)
                rec["status"] = "failed"
                rec["last_error"] = f"manual wait exceeded {timeout}s"
                record_attempt(ctx, rec, False, [rec["last_error"]], [], source="manual-timeout")
                ctx.save_state()
                print(f"  [FAIL] {rec['id']}: manual timeout")
                return
            if time.time() - last_note > 30:
                print(f"  ... waiting for {rec['id']} completion signal "
                      f"({fmt_dur(time.time() - t0)} elapsed)")
                last_note = time.time()
            bad = structured_output_problems(ctx, rec)
            if bad:
                # A malformed/empty structured output that stops changing means the
                # agent finished with garbage: fail this attempt so the retry loop
                # re-issues the prompt (with backoff) instead of waiting forever.
                sig = structured_output_signature(ctx, rec)
                if malformed_sig == sig:
                    rec["status"] = "failed"
                    rec["last_error"] = "malformed structured output: " + "; ".join(bad)[:400]
                    rec["postcheck"] = {"ok": False, "errors": bad, "warnings": [],
                                        "checked_at": utcnow()}
                    # Count this failure BEFORE recording it: record_attempt
                    # replaces the last entry when the attempt number is
                    # unchanged, so the old order overwrote the previous
                    # attempt's history and left the retry budget unmoved.
                    bump_attempt(rec)
                    record_attempt(ctx, rec, False, bad, [], source="malformed-output")
                    ctx.log("malformed-output", rec["id"], "; ".join(bad)[:300])
                    ctx.save_state()
                    print(f"  [FAIL] {rec['id']}: malformed structured output (unchanged for one "
                          f"poll interval): {bad[0][:120]}")
                    print("         The prompt is re-issued by the retry loop; nothing was adopted "
                          "from this attempt.")
                    return
                malformed_sig = sig
            else:
                malformed_sig = None
            time.sleep(max(2, poll))
    except KeyboardInterrupt:
        ctx.save_state()
        print("\n[manual] interrupted; state saved. Re-run `run --agent manual` to continue "
              "(staging is respected: prompts are only printed once their dependencies exist).")
        sys.exit(130)
    bump_attempt(rec)
    postcheck(ctx, rec, source="manual (operator-supplied completion signal)")
    ctx.save_state()
    print(f"  [{'ok' if rec['status'] == 'done' else 'FAIL'}] {rec['id']}: "
          f"{'; '.join((rec.get('postcheck') or {}).get('errors', []))[:160] or 'postcheck ok'}")


def run_phase(ctx: Ctx, ids: list, *, cmd, timeout: int, jobs: int, retries: int,
              manual: bool, nowait: bool, poll: int, label: str,
              retry_backoff: int = 0, retry_backoff_max: int = 0) -> tuple:
    """Drive one dependency level to completion.

    Returns (all_done, paused_for_manual). A run is only ever (re)executed when
    it has no completion signal; a sandbox that contains partial work without a
    signal is never entered by a second agent automatically.

    A failed run is retried up to `retries` times (default 2 -> three attempts)
    with exponential backoff, because a lost judge session shrinks the panel and
    an incomplete panel must never decide a round.

    The retry budget is PER INVOCATION: a fresh `run` grants every failed run
    another retries+1 attempts (the loop bound below enforces it), while the
    persistent rec["attempts"] counter keeps recording the lifetime total for
    the audit. Rationale: an operator who re-runs `run` after inspecting a
    failure is explicitly asking to try again; using the lifetime counter as the
    gate made the second `run` a no-op that exited immediately with the old
    error, which reads like a hang. `retry --run <ID>` remains the explicit
    single-run reset.
    """
    ids = [i for i in ids if ctx.run(i) is not None]
    if not ids:
        return True, False
    max_rounds = max(1, int(retries) + 1)
    # Failures observed in THIS invocation, per run. The persistent
    # rec["attempts"] counter also covers earlier invocations (and a freshly
    # rebuilt sandbox inherits it), so using it for the backoff would make a
    # rebuilt run wait before its FIRST attempt.
    failures_in_phase = {}
    for round_no in range(1, max_rounds + 1):
        eligible = []
        for rid in ids:
            rec = ctx.run(rid)
            if rec["status"] == "done":
                continue
            if rec["status"] == "stale":
                print(f"  [info] {rid}: inputs changed -> rebuilding sandbox")
                try:
                    rebuild_sandbox(ctx, rec)
                except DepsNotMet as e:
                    print(f"  [info] {rid}: {e}")
                    print(f"         It will be rebuilt by the stage that produces its "
                          f"dependency; no agent is launched into it now.")
                    continue
                except Exception as e:                      # noqa: BLE001
                    die(f"cannot rebuild the sandbox for {rid}: {e}. No agent was launched "
                        f"for it; repair the upstream output the message names and re-run.")
                # An a1 base is materialization-only: materialize_a1 marks it done
                # and no agent may ever be launched into it (there is no PROMPT.md).
                rec["status"] = "done" if rec["kind"] == "a1" else "pending"
            elif rec["status"] == "failed":
                pc_failed = bool((rec.get("postcheck") or {}).get("errors"))
                if not pc_failed and likely_complete_artifacts(ctx, rec):
                    print(f"  [info] {rid}: process-level failure but artifacts exist -> "
                          f"re-verifying")
                    bump_attempt(rec)
                    postcheck(ctx, rec, source="re-verify (process failed, artifacts complete)")
                    ctx.save_state()
                elif manual:
                    # In manual mode the operator owns the sandbox: never delete
                    # their work product automatically. The attempt stays on disk,
                    # the failure is reported, and the operator decides whether to
                    # reset it (`retry --run <ID>`), repair it, or abandon it.
                    print(f"  [manual] {rid}: attempt FAILED and is preserved (nothing was "
                          f"deleted). Inspect the sandbox, then either fix the artifacts and "
                          f"re-run `run`, or reset the attempt with `retry --run {rid}`.")
                    ctx.save_state()
                    continue
                elif failures_in_phase.get(rid, 0) > retries:
                    continue
                else:
                    try:
                        rebuild_sandbox(ctx, rec)
                    except DepsNotMet as e:
                        print(f"  [info] {rid}: {e}")
                        continue
                    except Exception as e:                  # noqa: BLE001
                        die(f"cannot rebuild the sandbox for {rid}: {e}. No agent was "
                            f"launched for it; repair the upstream output it names and re-run.")
                    rec["status"] = "pending"
            if rec["status"] == "pending":
                eligible.append(rid)
        if not eligible:
            break
        to_execute, dirty = [], []
        for rid in eligible:
            rec = ctx.run(rid)
            if leftovers_present(ctx, rec) and not completion_signal_exists(ctx, rec):
                bad = structured_output_problems(ctx, rec)
                if bad:
                    # The agent already produced structured output and it does not
                    # parse (truncated/empty JSON or XML): a failed attempt, not a
                    # live agent. Retry instead of waiting forever.
                    print(f"  [{label}] {rid}: MALFORMED structured output:")
                    for m in bad[:3]:
                        print(f"        - {m}")
                    ctx.log("malformed-output", rid, "; ".join(bad)[:300])
                    if manual:
                        # The operator's agent may still be mid-write; manual_run_one
                        # waits for the files to settle and then re-issues the prompt.
                        to_execute.append(rid)
                        continue
                    rec["last_error"] = "malformed structured output: " + "; ".join(bad)[:400]
                    rec["postcheck"] = {"ok": False, "errors": bad, "warnings": [],
                                        "checked_at": utcnow()}
                    if failures_in_phase.get(rid, 0) > retries:
                        rec["status"] = "failed"
                        print(f"        no attempts left in this invocation "
                              f"({rec.get('attempts')} lifetime); leaving it failed")
                        ctx.save_state()
                        continue
                    print("        treating it as a failed attempt: rebuilding the sandbox and "
                          "running the agent again")
                    rebuild_sandbox(ctx, rec)
                    rec["status"] = "pending"
                    to_execute.append(rid)
                    ctx.save_state()
                    continue
                if not manual:
                    dirty.append(rid)
                else:
                    to_execute.append(rid)
            else:
                to_execute.append(rid)
        if dirty:
            print(f"  [warn] {len(dirty)} pending run(s) already contain work but have no "
                  f"completion marker: {', '.join(dirty)}")
            print("         Not launching a second agent into them. If an agent is still running, "
                  "leave it and re-run later; if it died, reset with `retry --run <ID>`.")
            for rid in dirty:
                ctx.run(rid)["last_error"] = ("dirty sandbox without completion marker; waiting "
                                              "for the agent or `retry --run`")
            ctx.save_state()
        if not to_execute:
            break
        if manual:
            if nowait:
                for rid in to_execute:
                    rec = ctx.run(rid)
                    sb = ctx.sandbox_of(rec)
                    print(f"[manual] {rid}: paste {sb / 'PROMPT.md'} (cwd = {sb.resolve()}); "
                          f"then re-run `run --agent manual`")
                return False, True
            for rid in to_execute:
                manual_run_one(ctx, ctx.run(rid), poll, timeout)
                ctx.save_state()
        else:
            if round_no > 1:
                print(f"  [{label}] retry round {round_no} for: {to_execute}")
            failures = max(failures_in_phase.get(rid, 0) for rid in to_execute)
            delay = backoff_delay(retry_backoff, failures, retry_backoff_max)
            if delay:
                wait_backoff(delay, retry_backoff_max, label, to_execute, ctx)
            results = execute_wave(ctx, to_execute, cmd, timeout, jobs)
            apply_results(ctx, results)
            for rid in to_execute:
                rec = ctx.run(rid)
                if rec["status"] == "done":
                    continue
                # 1) A STOPPED session (a stalled turn, a CLI timeout) is CONTINUED
                # with its own context -- real work, not paperwork -- before
                # anything else is tried.
                argv, key, why = resume_gate(ctx, rec, cmd)
                if argv and run_resume_session_now(ctx, rec, argv, key, why, timeout):
                    if ctx.run(rid)["status"] == "done":
                        continue
                # 2) Before spending the next retry (and rebuilding the sandbox the
                # repair needs), give a repairable bookkeeping failure its ONE
                # scoped repair session -- the judge wave and the other
                # round-driven stages come through here, not through the
                # dependency scheduler.
                problems = repairable_artifact_failure(ctx, rec)
                if problems and run_repair_session_now(ctx, rec, problems, cmd, timeout):
                    if ctx.run(rid)["status"] == "done":
                        continue
                failures_in_phase[rid] = failures_in_phase.get(rid, 0) + 1
    remaining = [rid for rid in ids if ctx.run(rid)["status"] != "done"]
    if remaining:
        paused = [rid for rid in remaining if ctx.run(rid)["status"] == "pending"
                  and leftovers_present(ctx, ctx.run(rid))]
        hard = [rid for rid in remaining if rid not in paused]
        if paused:
            print(f"  [{label}] PAUSED (not failed): {paused} already contain agent output but "
                  f"no completion marker.")
        if hard:
            # Same rule as the round scheduler: name each run's OWN attempt
            # count, because a run can stop for a reason outside its budget.
            print(f"  [{label}] FAILED: " + ", ".join(
                f"{rid} ({int(ctx.run(rid).get('attempts') or 0)} attempt(s), "
                f"budget {max_rounds})" for rid in hard))
            for rid in hard[:6]:
                err = (ctx.run(rid).get("last_error") or "")[:200]
                if err:
                    print(f"        {rid}: {err}")
        ctx.save_state()
        return False, False
    return True, False


# =====================================================================
# ROUND DRIVER / RUN COMMAND
# =====================================================================

def round_run_plan(ctx: Ctx, r: int) -> list:
    """Every agent run this round needs, with its dependencies and materializer.

    The plan is a DAG, not a pipeline of barriers:

        a1 (copy, no agent)
        +-- w1..wM      rewrites        (depend on a1)          \
        +-- review      one $paper-review (depends on a1)          > wave 1
        review
        +-- a2..a{1+N}  revisions       (depend on a1 + review) -> as soon as the
                                                                  review is done
        pool = {a1, w1..wM, a2..a{1+N}}
        +-- i<k>        integrations    (depend on the WHOLE pool); only the arms
                        selected by the round's per-round `--integrators` mask run
        the judge wave is materialized separately once the field is deduplicated.
    """
    m, n = round_counts(ctx, r)
    pool = round_pool_ids(m, n)
    entries = []
    jmode = journal_mode_of(ctx)
    scoped = journal_is_scoped(ctx)
    if scoped and n != 1:
        die(f"revision mode {jmode!r} needs exactly ONE revision arm, but round {r} plans "
            f"N={n} (and M={m}). The mode is concern-scoped by definition; run "
            f"`set-revision-mode {jmode}` (it normalises rewrites/revises/integrators/rounds) "
            f"or start a fresh root.")
    feedback_rid = rid_feedback(r) if journal_has_feedback(ctx) and not scoped else None
    if feedback_rid:
        entries.append({"id": feedback_rid, "kind": "feedback", "vid": None,
                        "deps": [rid_a1(r)], "stage": "feedback",
                        "materialize": (lambda c: materialize_feedback(c, r))})
    rewrite_deps = [rid_a1(r)] + ([feedback_rid] if feedback_rid else [])
    for k in range(1, m + 1):
        vid = rewrite_vid(k)
        entries.append({"id": rid_for_fresh(r, vid), "kind": "rewrite", "vid": vid,
                        "deps": list(rewrite_deps), "stage": f"rewrite {k}/{m}",
                        "materialize": (lambda c, k=k: materialize_rewrite(c, r, k))})
    if n:
        if scoped:
            # A major/minor revision runs NO general review: the concerns run
            # produces the ledger AND the only finding list the single revise
            # session sees.
            entries.append({"id": rid_concerns(r), "kind": "concerns", "vid": None,
                            "deps": [rid_a1(r)], "stage": "concerns",
                            "materialize": (lambda c: materialize_concerns(c, r))})
            review_deps = [rid_concerns(r)]
        else:
            entries.append({"id": rid_review(r), "kind": "review", "vid": None,
                            "deps": [rid_a1(r)] + ([feedback_rid] if feedback_rid else []),
                            "stage": "review",
                            "materialize": (lambda c: materialize_review(c, r, "a"))})
            review_deps = [rid_review(r)]
        if review_split_of(ctx) != "off" and not scoped:
            entries.append({"id": rid_review_b(r), "kind": "review", "vid": None,
                            # Session B consumes session A's OUTPUT (`review_a/`,
                            # copied by materialize_review): with the same deps as
                            # A, B was materialized first and kept whatever A had
                            # written at that instant -- the seeded evidence pack
                            # at best, nothing at worst, never the findings.
                            "deps": [rid_a1(r), rid_review(r)], "stage": "review",
                            "materialize": (lambda c: materialize_review(c, r, "b"))})
            review_deps.append(rid_review_b(r))
        if probe_review_of(ctx) == "on" and round_review_scope(ctx, r) == "full":
            # The PROBE REVIEW: an independent, cold-context DISCOVERY session
            # that runs IN PARALLEL with the checklist review (same base, no
            # dependency on it). It hunts any defect class and, where a
            # computation can show one, declares a re-runnable verifier the
            # orchestrator re-runs. Its findings feed the frozen list (X-9xx),
            # so the auditor and the revisers wait for it exactly like the
            # review. Skipped in a "formatting-writing" polish round: that round
            # may not touch content, and the probe is a content-level pass.
            entries.append({"id": rid_probe(r), "kind": "probe", "vid": None,
                            "deps": [rid_a1(r)], "stage": "probe review",
                            "materialize": (lambda c: materialize_probe(c, r))})
            review_deps.append(rid_probe(r))
        if audit_enabled(ctx) and not scoped:
            # review -> AUDIT -> revise. The auditor disposes the frozen review
            # before any reviser sees it, so a boilerplate closure or a
            # mis-located finding is caught while it is still one finding, not
            # after N revisers have acted on it.
            entries.append({"id": rid_audit(r), "kind": "audit", "vid": None,
                            "deps": [rid_a1(r)] + list(review_deps), "stage": "audit",
                            "materialize": (lambda c: materialize_audit(c, r))})
            review_deps.append(rid_audit(r))
        for j in range(1, n + 1):
            vid = revise_vid(j)
            entries.append({"id": rid_for_fresh(r, vid), "kind": "revise", "vid": vid,
                            "deps": [rid_a1(r)] + review_deps,
                            "stage": f"revise {j}/{n}",
                            "materialize": (lambda c, v=vid: materialize_revise(c, r, v))})
    if scoped and journal_needs_response(ctx):
        entries.append({"id": rid_response(r), "kind": "response", "vid": None,
                        "deps": [rid_for_fresh(r, revise_vid(1))], "stage": "response",
                        "materialize": (lambda c: materialize_response(c, r))})
    mask = 0 if scoped else round_integrators(ctx, r)
    arms = integrator_arms(m, n, mask)
    for k in arms:
        vid = integrate_vid(k)
        entries.append({"id": rid_for_fresh(r, vid), "kind": "integrate", "vid": vid,
                        "deps": [rid_for_fresh(r, v) for v in pool],
                        "stage": f"integrate {k}/{len(pool)}",
                        "materialize": (lambda c, k=k: materialize_integrate(c, r, k))})
    return entries


REVISION_AUDIT_DIRNAME = "revision_audit"
REVISION_AUDIT_PROMPT_FILE = "REVISION_AUDIT_PROMPT.md"
REVISION_REPAIR_PROMPT_FILE = "REVISION_REPAIR_PROMPT.md"


def revision_audit_of(ctx) -> str:
    """`on` unless the root or the operator turned the revision audit off."""
    raw = str(os.environ.get("PAPER_REVISION_AUDIT")
              or (getattr(ctx, "cfg", None) or {}).get("revision_audit")
              or "on").strip().lower()
    return "off" if raw in {"off", "0", "no", "false", "none"} else "on"


def _revision_plan_rows(sb: Path):
    """The audit's repair rows, or None when no valid plan was written.

    Every row must be an object the repair session can locate and account for.
    A malformed row is NOT an empty plan: filtering it out would report "0
    rows" and silently drop a defect the auditor found (and make `id`/`file`
    collisions invisible to the repair ledger).
    """
    path = sb / REVISION_AUDIT_DIRNAME / "REPAIR_PLAN.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            return None
        rid = str(row.get("id") or "").strip()
        rel = str(row.get("file") or "").strip()
        if not rid or rid in seen or not rel:
            return None
        if _unsafe_package_rel(rel):
            return None
        seen.add(rid)
        out.append(dict(row, id=rid, file=rel))
    return out


def _unsafe_package_rel(rel: str) -> bool:
    """True when a plan row's `file` is not a path inside the revised package."""
    return bool(rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel)
                or ".." in Path(rel).parts)


def _revision_repair_ledger(sb: Path, rows: list):
    """(problem, counts) for the bounded repair's re-validation ledger.

    The repair session's product is the verdict it reached for EVERY planned
    row; a missing, malformed or incomplete ledger leaves the plan unaccounted
    for, so it is recorded as a failed repair (the stage postcheck still decides
    whether the final package itself is valid).
    """
    path = sb / REVISED_DIR / "REPAIR_LEDGER.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        return f"no revised/REPAIR_LEDGER.json ({e})", {}
    except ValueError as e:
        return f"revised/REPAIR_LEDGER.json is not valid JSON ({e})", {}
    ledger = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(ledger, list):
        return "revised/REPAIR_LEDGER.json carries no rows list", {}
    plan_ids = [row["id"] for row in rows]
    seen = set()
    counts = {"confirmed": 0, "rejected": 0}
    for row in ledger:
        if not isinstance(row, dict):
            return "a REPAIR_LEDGER row is not an object", {}
        rid = str(row.get("id") or "").strip()
        verdict = str(row.get("verdict") or "").strip().lower()
        if not rid or rid in seen or rid not in plan_ids:
            return (f"REPAIR_LEDGER row id {rid!r} is missing, duplicated or not in the "
                    f"audit's plan"), {}
        if verdict not in counts:
            return (f"REPAIR_LEDGER row {rid} has verdict {verdict!r} "
                    f"(expected confirmed|rejected)"), {}
        if not str(row.get("reason") or "").strip():
            return f"REPAIR_LEDGER row {rid} carries no reason", {}
        seen.add(rid)
        counts[verdict] += 1
    missing = [rid for rid in plan_ids if rid not in seen]
    if missing:
        return (f"REPAIR_LEDGER does not re-validate planned row(s) "
                f"{', '.join(missing[:6])}"), {}
    return "", counts


def record_revision_chain_skip(ctx, rec: dict, reason: str) -> None:
    """Record that the post-revise chain did not run, and why (never silent)."""
    if rec.get("kind") != "revise" or rec.get("revision_audit"):
        return
    rec["revision_audit"] = {"status": "skipped", "rows": 0, "reason": reason}
    ctx.save_state()
    print(f"  [revision-audit] {rec['id']}: skipped ({reason})")


def _run_aux_session(sb: Path, rec: dict, cmd: list, timeout: int,
                     prompt_file: str, log_name: str) -> dict:
    """Run one audit/repair session WITHOUT changing the stage attempt's clock.

    `_execute_attempt_in` records `last_attempt_started`; the auxiliary sessions
    are part of the accepted revise attempt, so the attempt's start (and the
    history row `postcheck` later writes) must keep the revise session's own
    values, and the audit/repair durations live in their own records.
    """
    started = rec.get("last_attempt_started")
    try:
        return _execute_attempt_in(sb, rec, cmd, timeout, prompt_file, log_name, False)
    finally:
        if started is not None:
            rec["last_attempt_started"] = started


def run_revision_chain(ctx, rec: dict, cmd: list, timeout: int) -> None:
    """Revision audit -> (non-empty plan) -> one bounded repair pass.

    Runs after the revise stage's own postcheck has passed, in the SAME sandbox:
    the audit reads `base/` and `revised/` and writes only
    `revision_audit/REPAIR_PLAN.json`; the repair session re-validates every row,
    edits `revised/` only, and the stage's own postcheck is re-run on the final
    package. A skipped (`--revision-audit off`), empty or inapplicable plan
    leaves `revised/` as the final revised version and says why.

    Two guards keep the chain off a judged artifact: a round that is already
    decided is never audited/repaired (its champion and pin are that digest's
    bytes, rule 5), and a concern-scoped (major/minor) revision has no general
    review/audit to consume -- its edits are limited to the admitted concerns.
    """
    if rec.get("kind") != "revise" or rec.get("revision_audit"):
        return
    r = int(rec.get("round") or 0)
    if r and round_is_done(ctx, r):
        record_revision_chain_skip(
            ctx, rec, "the round is already decided; a judged candidate is never changed")
        return
    if journal_is_scoped(ctx):
        record_revision_chain_skip(
            ctx, rec, "concern-scoped revision mode: the general revision audit is not staged")
        return
    if revision_audit_of(ctx) != "on":
        record_revision_chain_skip(ctx, rec, "revision audit off")
        return
    sb = ctx.sandbox_of(rec)
    if not sb.is_dir() or not (sb / REVISED_DIR).is_dir():
        record_revision_chain_skip(
            ctx, rec, "the revise sandbox (or revised/) is no longer on disk; nothing to audit")
        return
    (sb / REVISION_AUDIT_PROMPT_FILE).write_text(
        revision_audit_prompt(sb, rec["id"], r), encoding="utf-8")
    print(f"  [revision-audit] {rec['id']}: auditing the revised package")
    res = _run_aux_session(sb, rec, cmd, timeout, REVISION_AUDIT_PROMPT_FILE,
                           "_revision_audit.log")
    (sb / REVISION_AUDIT_PROMPT_FILE).unlink(missing_ok=True)
    rows = _revision_plan_rows(sb)
    audit_rec = {"status": "failed", "rows": 0,
                 "duration": round(res.get("dur") or 0.0, 1),
                 "error": str(res.get("error") or "")}
    if res.get("error") or res.get("rc") not in (0,):
        audit_rec["error"] = audit_rec["error"] or f"audit session exited rc={res.get('rc')}"
    elif rows is None:
        audit_rec["error"] = ("no valid revision_audit/REPAIR_PLAN.json (every row needs a "
                              "unique id and a package-relative file)")
    else:
        audit_rec["status"] = "done"
        audit_rec["rows"] = len(rows)
    rec["revision_audit"] = audit_rec
    ctx.save_state()
    if audit_rec["status"] != "done":
        print(f"  [revision-audit] {rec['id']}: FAILED — {audit_rec['error'][:240]}")
        return
    print(f"  [revision-audit] {rec['id']}: {len(rows)} confirmed repair row(s)")
    if not rows:
        return
    # Preserve the audited bytes: the repair produces the final revised version.
    pre = sb / "revised_prerepair"
    if not pre.exists():
        shutil.copytree(sb / REVISED_DIR, pre)
    (sb / REVISION_REPAIR_PROMPT_FILE).write_text(
        revision_repair_prompt(sb, rec["id"], r, len(rows)), encoding="utf-8")
    print(f"  [revision-repair] {rec['id']}: one bounded repair pass")
    res2 = _run_aux_session(sb, rec, cmd, timeout, REVISION_REPAIR_PROMPT_FILE,
                            "_revision_repair.log")
    (sb / REVISION_REPAIR_PROMPT_FILE).unlink(missing_ok=True)
    repair_rec = {"status": "failed", "rows": len(rows),
                  "duration": round(res2.get("dur") or 0.0, 1),
                  "error": str(res2.get("error") or "")}
    if res2.get("error") or res2.get("rc") not in (0,):
        repair_rec["error"] = repair_rec["error"] or f"repair session exited rc={res2.get('rc')}"
    else:
        repair_rec["status"] = "done"
        problem, counts = _revision_repair_ledger(sb, rows)
        if problem:
            repair_rec["status"] = "failed"
            repair_rec["error"] = problem
        else:
            repair_rec["ledger"] = counts
    rec["revision_repair"] = repair_rec
    ctx.save_state()
    if repair_rec["status"] != "done":
        print(f"  [revision-repair] {rec['id']}: FAILED — {str(repair_rec['error'])[:240]}")
    # The SAME postcheck decides the final revised version.
    postcheck(ctx, rec, source="revision-audit")
    ctx.save_state()


def run_round_runs(ctx: Ctx, r: int, *, cmd, timeout: int, jobs: int, retries: int,
                   manual: bool, nowait: bool, poll: int, label: str,
                   retry_backoff: int = 0, retry_backoff_max: int = 0,
                   only=None) -> tuple:
    """Drive every run of one round AS SOON AS ITS INPUTS EXIST.

    Two consequences that matter for wall-clock time:

      * the M rewrites and the round's review both depend only on the base, so
        they start TOGETHER (they used to be two sequential stages), and
      * a revise session starts the moment the review marker exists, without
        waiting for the rewrites to finish; the integrations start the moment
        the WHOLE pool is done, and the judge wave follows the field.

    A run's sandbox is materialized only when its dependencies are satisfied,
    and each run keeps the per-invocation retry budget and the exponential
    backoff of `run_phase` (so a lost session still cannot shrink the panel).
    Returns (all_done, paused_for_manual) exactly like `run_phase`.
    """
    plan = round_run_plan(ctx, r)
    # FAIL FAST on a plan this build cannot finish. A run kind with no
    # postcheck handler or no sandbox rebuilder only shows itself when a run
    # fails -- and then it blocks the round (the 2026-09-23 audit stage: no
    # rebuilder, so the first retry of a 20-minute session gave up after one of
    # three attempts and took `a2` and i1-i4 with it). Nothing is launched yet,
    # so this is the cheapest possible place to refuse.
    support = run_kind_support_problems(ctx)
    if support:
        die(f"this pipeline build cannot drive the round {r} plan: " + "; ".join(support)
            + ". Every kind the plan can produce needs a postcheck handler AND a sandbox "
              "rebuilder (POSTCHECK_HANDLERS / REBUILD_HANDLERS); nothing was launched, so no "
              "state was changed.")
    if only:
        full = list(plan)
        keep = [only.entry_selected(r, e) for e in full]
        plan = [e for e, k in zip(full, keep) if k]
        skipped = sorted({plan_stage_of(e) for e, k in zip(full, keep) if not k})
        print(f"  [{label}] --only {only.label()}: {len(plan)} run(s) selected"
              + (f"; not starting {', '.join(skipped)} run(s) in this invocation -- the round "
                 f"stays incomplete until they run" if skipped else ""))
    if not plan:
        return True, False

    def deps_ok(e) -> bool:
        return all((ctx.run(d) or {}).get("status") == "done" for d in e["deps"])

    def is_done(rid) -> bool:
        return (ctx.run(rid) or {}).get("status") == "done"

    def prepare(e) -> str:
        """Materialize one planned run if it is ready. Returns a state word.

        'done'    -> already finished
        'ready'   -> sandbox exists and no agent has touched it yet
        'dirty'   -> partial agent output without a completion marker
        'blocked' -> dependencies are not done yet
        """
        rid = e["id"]
        if is_done(rid):
            return "done"
        if not deps_ok(e):
            return "blocked"
        try:
            e["materialize"](ctx)
        except DepsNotMet as exc:
            print(f"  [info] {rid}: {exc}")
            return "blocked"
        except Exception as exc:                            # noqa: BLE001
            # A non-dependency materialization error (a missing pin, a corrupt
            # upstream tree) is a root-integrity failure. Report it as a
            # pipeline error instead of a raw traceback from inside the
            # scheduling loop.
            die(f"cannot materialize {rid}: {exc}. No agent was launched for it; repair the "
                f"upstream output the message names and re-run.")
        rec = ctx.run(rid)
        if rec is None:
            return "blocked"
        if rec.get("status") == "done":
            return "done"
        if completion_signal_exists(ctx, rec):
            return "signal"
        if leftovers_present(ctx, rec):
            return "dirty"
        return "ready"

    # ---- manual mode: dependency order, operator-paced ---------------------
    if manual:
        for e in plan:
            state = prepare(e)
            if state == "done":
                rec = ctx.run(e["id"])
                if rec and rec.get("kind") == "revise" and not rec.get("revision_audit"):
                    record_revision_chain_skip(
                        ctx, rec, "manual mode: the post-revise audit/repair sessions are "
                                  "automated; re-run that round with an agent command")
                continue
            if state == "blocked":
                continue
            if state == "signal":
                signal_rec = ctx.run(e["id"])
                bump_attempt(signal_rec)
                postcheck(ctx, signal_rec, source="recheck (marker already on disk)")
                ctx.save_state()
                if signal_rec.get("status") == "done" \
                        and signal_rec.get("kind") == "revise" \
                        and not signal_rec.get("revision_audit"):
                    record_revision_chain_skip(
                        ctx, signal_rec, "manual mode: the post-revise audit/repair sessions "
                                          "are automated; re-run that round with an agent command")
                continue
            if state == "dirty":
                print(f"  [manual] {e['id']}: this sandbox already contains work without a "
                      f"completion marker; inspect it, or reset it with `retry --run {e['id']}`")
                continue
            sb = ctx.sandbox_of(ctx.run(e["id"]))
            if nowait:
                print(f"[manual] {e['id']} (round {r}, {e['stage']}): paste "
                      f"{sb / 'PROMPT.md'} (cwd = {sb.resolve()}); then re-run "
                      f"`run --agent manual`")
                continue
            print(f"[manual] {e['id']} (round {r}, {e['stage']}): waiting for the completion "
                  f"signal; paste {sb / 'PROMPT.md'} with cwd = {sb.resolve()}")
            manual_run_one(ctx, ctx.run(e["id"]), poll, timeout)
            ctx.save_state()
            rec = ctx.run(e["id"])
            if rec and rec.get("status") == "done" and rec.get("kind") == "revise" \
                    and not rec.get("revision_audit"):
                record_revision_chain_skip(
                    ctx, rec, "manual mode: the post-revise audit/repair sessions are "
                              "automated; re-run that round with an agent command")
        if nowait and any(not is_done(e["id"]) for e in plan):
            return False, True
        remaining = [e["id"] for e in plan if not is_done(e["id"])]
        if remaining:
            print(f"  [{label}] manual round incomplete: {', '.join(remaining[:6])}")
            return False, False
        return True, False

    # ---- automated mode: rolling dependency-driven scheduler ---------------
    max_attempts = max(1, int(retries) + 1)
    attempts_left = {e["id"]: max_attempts for e in plan}
    failures = {e["id"]: 0 for e in plan}
    not_before = {e["id"]: 0.0 for e in plan}
    running = {}                      # future -> run id
    repair_flight = {}                # future -> the repair session it belongs to
    resume_flight = {}                # future -> the CONTINUATION it belongs to
    blocked_dirty, failed_hard = [], []

    def register_failure(rid: str, rec: dict) -> None:
        """Spend one attempt, then either re-queue the run or fail it for good.

        Used for BOTH failure kinds so the signal path cannot spin: a run whose
        completion marker exists but whose postcheck fails (a wrong-typed
        marker, a missing deliverable) is a failed attempt exactly like a
        non-zero exit, and it must be rebuilt and retried rather than
        re-postchecked forever in a tight loop.
        """
        failures[rid] += 1
        attempts_left[rid] -= 1
        if attempts_left[rid] <= 0:
            failed_hard.append(rid)
            return
        delay = backoff_delay(retry_backoff, failures[rid], retry_backoff_max)
        print(f"  [retry] {rid}: attempt failed; "
              + (f"waiting {delay:.0f}s before the next one" if delay else
                 "retrying immediately"))
        if delay:
            not_before[rid] = time.time() + delay
        kept = failed_sandbox_dir(ctx, rec)
        try:
            rebuild_sandbox(ctx, rec)
            rec["status"] = "pending"
            if kept.is_dir():
                print(f"  [retry] {rid}: attempt {attempt_number(rec)} kept in "
                      f"{kept.relative_to(ctx.root)} (its transcript is under "
                      f"{Path(LOGS_DIRNAME)}/)")
        except DepsNotMet as exc:
            print(f"  [info] {rid}: {exc}")
        except Exception as exc:                            # noqa: BLE001
            print(f"  [warn] {rid}: sandbox rebuild failed ({exc}); leaving it failed")
            # The reason must survive the invocation: the console line is the
            # only other place it appears, and this is an OPERATOR-level blocker
            # (nothing about the next attempt can fix it) while the run record
            # still said only what the postcheck had found.
            rec["last_error"] = (str(rec.get("last_error") or "")
                                 + f" | sandbox rebuild failed: {exc}")[:600].lstrip(" |")
            ctx.log("rebuild-failed", rid, str(exc)[:300])
            failed_hard.append(rid)

    with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as ex:
        while True:
            now = time.time()
            # 1. materialize whatever became ready, then submit up to `jobs`
            for e in plan:
                rid = e["id"]
                if rid in running.values() or rid in failed_hard:
                    continue
                if is_done(rid):
                    # A revise run accepted in an earlier invocation (or before
                    # the chain ran) still owes the post-revise chain. It is NOT
                    # launched again, so the plan's `is_done` short-circuit is
                    # the only place that can finish it.
                    if e.get("kind") == "revise":
                        rec = ctx.run(rid)
                        if rec and not rec.get("revision_audit"):
                            run_revision_chain(ctx, rec, cmd, timeout)
                            rec = ctx.run(rid)
                            if rec["status"] != "done":
                                register_failure(rid, rec)
                    continue
                if now < not_before[rid]:
                    continue
                state = prepare(e)
                if state == "done":
                    continue
                if state == "signal":
                    rec = ctx.run(rid)
                    bump_attempt(rec)
                    postcheck(ctx, rec, source="recheck (marker already on disk)")
                    ctx.save_state()
                    if rec["status"] == "done" and rec.get("kind") == "revise" \
                            and not rec.get("revision_audit"):
                        run_revision_chain(ctx, rec, cmd, timeout)
                        rec = ctx.run(rid)
                    if rec["status"] != "done":
                        problems = repairable_artifact_failure(ctx, rec)
                        if problems and len(running) < max(1, int(jobs)) \
                                and start_repair_session(ctx, ex, running, repair_flight, rec,
                                                         problems, cmd, timeout):
                            continue
                        print_failure(rid, (rec.get("postcheck") or {}).get("errors", []),
                                      note="the completion signal was already on disk")
                        register_failure(rid, rec)
                    continue
                if state == "dirty":
                    if rid not in blocked_dirty:
                        blocked_dirty.append(rid)
                        print(f"  [warn] {rid}: pending run already contains work but has no "
                              f"completion marker; not launching a second agent into it. If an "
                              f"agent is still running, leave it and re-run later; if it died, "
                              f"reset with `retry --run {rid}`.")
                        ctx.run(rid)["last_error"] = ("dirty sandbox without completion marker; "
                                                      "waiting for the agent or `retry --run`")
                        ctx.save_state()
                    continue
                if state != "ready":
                    continue
                if len(running) >= max(1, int(jobs)):
                    break
                rec = ctx.run(rid)
                print(f"  [{label}] starting {rid} ({e['stage']})"
                      + (f" [attempt {rec['attempts'] + 1}/{max_attempts}]"
                         if rec["attempts"] else ""))
                fut = ex.submit(_execute_attempt_in, ctx.sandbox_of(rec), rec, cmd, timeout)
                running[fut] = rid
            # 2. wait for a completion (or a short tick to re-check backoff timers)
            if not running:
                if any(not is_done(e["id"]) and e["id"] not in failed_hard
                       and e["id"] not in blocked_dirty for e in plan):
                    # nothing runnable and nothing running: either a run is waiting
                    # for its backoff, or its dependencies failed.
                    waits = [not_before[e["id"]] - time.time() for e in plan
                             if not is_done(e["id"]) and e["id"] not in failed_hard
                             and e["id"] not in blocked_dirty
                             and not_before[e["id"]] > time.time()]
                    if waits and max(waits) > 0:
                        time.sleep(min(2.0, max(waits)))
                        continue
                    break
                break
            done_futs, _pending = wait_futures(running, timeout=0.5)
            for fut in done_futs:
                rid = running.pop(fut)
                repair = repair_flight.pop(fut, None)
                resume = resume_flight.pop(fut, None)
                try:
                    res = fut.result()
                except Exception as exc:                        # noqa: BLE001
                    res = {"rc": None, "dur": 0.0, "error": f"executor error: {exc}",
                           "log": None}
                if repair is not None:
                    # A repair session is judged by the guard and then by the SAME
                    # postcheck; a repair that does not clear the table is a failed
                    # attempt, exactly like one the agent produced itself.
                    finish_repair_session(ctx, ctx.run(rid), repair, res)
                    rec = ctx.run(rid)
                    if rec["status"] == "done" and rec.get("kind") == "revise" \
                            and not rec.get("revision_audit"):
                        run_revision_chain(ctx, rec, cmd, timeout)
                        rec = ctx.run(rid)
                    if rec["status"] != "done":
                        register_failure(rid, rec)
                    continue
                if resume is not None:
                    # A CONTINUATION is judged by the identical postcheck: a
                    # continuation that does not finish the stage is a failed
                    # attempt like any other, and the retry policy decides next.
                    finish_resume_session(ctx, ctx.run(rid), resume, res)
                    rec = ctx.run(rid)
                    if rec["status"] == "done" and rec.get("kind") == "revise" \
                            and not rec.get("revision_audit"):
                        run_revision_chain(ctx, rec, cmd, timeout)
                        rec = ctx.run(rid)
                    if rec["status"] != "done":
                        register_failure(rid, rec)
                    continue
                apply_results(ctx, {rid: res})
                rec = ctx.run(rid)
                if rec["status"] == "done" and rec.get("kind") == "revise" \
                        and not rec.get("revision_audit"):
                    # The chain records its own skip when the audit is off (or
                    # the round is already decided), so the decision is visible
                    # in the run record.
                    run_revision_chain(ctx, rec, cmd, timeout)
                    rec = ctx.run(rid)
                if rec["status"] == "done":
                    continue
                # a process-level failure with VALID artifacts is re-verified first
                if rec["status"] == "failed" and not (rec.get("postcheck") or {}).get("errors") \
                        and likely_complete_artifacts(ctx, rec):
                    bump_attempt(rec)
                    postcheck(ctx, rec, source="re-verify (process failed, artifacts complete)")
                    ctx.save_state()
                    if rec["status"] == "done":
                        print(f"  [ok]   {rid} re-verified after a process-level failure")
                        if rec.get("kind") == "revise" and not rec.get("revision_audit"):
                            run_revision_chain(ctx, rec, cmd, timeout)
                            rec = ctx.run(rid)
                        if rec["status"] == "done":
                            continue
                # ... then a repairable artifact-quality failure before the retry
                # burns the attempt and rebuilds the sandbox it would repair.
                argv, key, why = resume_gate(ctx, rec, cmd)
                if argv and len(running) < max(1, int(jobs)) \
                        and start_resume_session(ctx, ex, running, resume_flight, rec,
                                                 argv, key, why, timeout):
                    continue
                problems = repairable_artifact_failure(ctx, rec)
                if problems and len(running) < max(1, int(jobs)) \
                        and start_repair_session(ctx, ex, running, repair_flight, rec, problems,
                                                 cmd, timeout):
                    continue
                register_failure(rid, rec)
    remaining = [e["id"] for e in plan if not is_done(e["id"])]
    if remaining:
        paused = [rid for rid in remaining if rid in blocked_dirty]
        hard = [rid for rid in remaining if rid not in paused]
        if paused:
            print(f"  [{label}] PAUSED (not failed): {paused} already contain agent output but "
                  f"no completion marker.")
        if hard:
            never_started = [rid for rid in hard if not (ctx.run(rid) or {}).get("attempts")]
            tried = [rid for rid in hard if rid not in never_started]
            if tried:
                # Each run's OWN attempt count, never the invocation's budget: a
                # run that failed for a reason OUTSIDE its retry budget (a
                # sandbox that could not be rebuilt, an internal error) never
                # spent it, and reporting "FAILED after 3 attempt(s)" for a run
                # with one attempt sends the operator hunting for two attempts
                # that never happened (2026-09-23: r1_audit).
                print(f"  [{label}] FAILED: " + ", ".join(
                    f"{rid} ({int((ctx.run(rid) or {}).get('attempts') or 0)} attempt(s), "
                    f"budget {max_attempts})" for rid in tried))
            if never_started:
                print(f"  [{label}] never started (an upstream run is not done): "
                      + ", ".join(never_started))
            for rid in hard[:6]:
                # a run whose dependencies never completed was never even
                # materialized, so it has no record to report
                err = ((ctx.run(rid) or {}).get("last_error") or "")[:200]
                if err:
                    print(f"        {rid}: {err}")
        ctx.save_state()
        return False, False
    return True, False


def wait_futures(running: dict, timeout: float = 0.5):
    """concurrent.futures.wait() wrapper (kept separate so tests can patch it)."""
    return wait(running, timeout=timeout, return_when=FIRST_COMPLETED)


def round_redlines(ctx: Ctx, r: int, enabled: bool) -> dict:
    """Tracked-changes copies for one round (an audit aid; never fails the round).

    Shared by the standard round close and by the concern-scoped (major/minor)
    close: a real journal revision needs the marked-up copy as much as the
    standard flow does.

    Returns the manifest (None when the pass is disabled or failed) so the
    difference-tracking pass that follows can REUSE the .docx redlines it
    produced instead of driving Word/COM a second time.
    """
    if not enabled:
        return None
    try:
        mf = run_redlines(ctx, rounds=[r], versions=None, tool="auto",
                          redline_cmd=None, quiet=True)
        ok_n = sum(1 for v in mf["versions"] for c in v["comparisons"] if c["ok"])
        bad_n = sum(1 for v in mf["versions"] for c in v["comparisons"] if not c["ok"])
        warn_n = sum(1 for v in mf["versions"] for c in v["comparisons"] if c.get("warning"))
        tools = sorted({c["tool"] for v in mf["versions"] for c in v["comparisons"]
                        if c["ok"] and c["tool"]})
        print(f"[run] round {r} tracked changes: {ok_n} docx pair(s) written"
              + (f" with {', '.join(tools)}" if tools else "")
              + (f", {bad_n} failed (see {REDLINE_DIRNAME}/manifest.json)" if bad_n else "")
              + (f", {warn_n} with caveats -- READ {REDLINE_DIRNAME}/README.md before "
                 f"trusting them" if warn_n else "")
              + f" -> {REDLINE_DIRNAME}/")
        return mf
    except Exception as e:                                  # noqa: BLE001
        print(f"[run] round {r} WARNING: tracked-changes generation failed: {e}")
        return None


def round_tracking(ctx: Ctx, r: int, enabled: bool,
                   redlines_manifest: dict = None) -> None:
    """Difference-tracking copies + persistent PDFs for one round.

    The stage-time hooks already wrote each version's copies: this pass FILLS IN
    what is missing (a version whose hook failed or was skipped, and the
    round's published winner directory) and leaves a fresh entry alone --
    `skip_fresh=True` -- instead of driving Word/latexdiff a second time over
    unchanged content. Both passes are audit aids: they are pure code (no agent
    session), they never enter a corpus/pin/judge view (see
    TRACKING_AUX_NAME_RE and the <root>/pdfs/ tree), and a failure here is a
    WARNING -- never a failed round.
    """
    if not enabled:
        return
    try:
        mf = run_difference_tracking(ctx, rounds=[r], versions=None, tool="auto",
                                     redline_cmd=None, quiet=True,
                                     redlines_manifest=redlines_manifest,
                                     skip_fresh=True)
        versions = [v for v in mf["versions"] if int(v.get("round") or 0) == r]
        ok_n = sum(1 for v in versions for c in v["comparisons"]
                   if c.get("ok") and c.get("tool"))
        fb_n = sum(1 for v in versions for c in v["comparisons"]
                   if c.get("ok") and not c.get("tool"))
        bad_n = sum(1 for v in versions for c in v["comparisons"]
                    if not c.get("ok"))
        tools = sorted({c["tool"] for v in versions for c in v["comparisons"]
                        if c.get("ok") and c.get("tool")})
        print(f"[run] round {r} difference tracking: {ok_n} tracked copy(ies)"
              + (f" with {', '.join(tools)}" if tools else "")
              + (f", {fb_n} logging fallback(s)" if fb_n else "")
              + (f", {bad_n} pair(s) with NO file (see {TRACKING_DIRNAME}/README.md)"
                 if bad_n else "")
              + f" -> {TRACKING_DIRNAME}/")
    except Exception as e:                                  # noqa: BLE001
        print(f"[run] round {r} WARNING: difference tracking failed: {e}")
    try:
        pm = run_pdf_conversion(ctx, rounds=[r], versions=None, quiet=True)
        docs = [d for s in pm["sets"] if int(s.get("round") or 0) == r
                for d in s["documents"]]
        ok_n = sum(1 for d in docs if d.get("ok"))
        bad_n = len(docs) - ok_n
        print(f"[run] round {r} PDF renders: {ok_n} PDF(s) written"
              + (f", {bad_n} WARNING(S) (non-fatal; see {PDF_DIRNAME}/README.md)"
                 if bad_n else "")
              + f" -> {PDF_DIRNAME}/")
    except Exception as e:                                  # noqa: BLE001
        print(f"[run] round {r} WARNING: PDF rendering failed: {e}")


def _apply_judge_selection(rrec: dict, only, judge_step: bool, r: int, ctx: Ctx) -> None:
    """Drop or record the round's remembered judge-session selection.

    Asking for the WHOLE judge step (a bare `judge`, a round in full, `all`,
    or a plain `run` -- `only is None`) must drop a selection remembered from
    an earlier invocation. The pop used to live inside `if only is not None`,
    so a plain `run` kept the stale list and decided the round on a shrunken
    (or empty) panel.
    """
    if judge_step:
        if rrec.pop("judges_enabled", None) is not None:
            print(f"[run] r{r}: this invocation asks for the WHOLE judge step; dropping the "
                  f"judge-session selection remembered from an earlier invocation (the "
                  f"round's panel is the configured {round_judges(ctx, r)} per version)")
    elif only is not None:
        _sel = only.judge_spec_for(r)
        if _sel:
            rrec["judges_enabled"] = _sel


def drive_round(ctx: Ctx, r: int, *, cmd, timeout: int, jobs: int, retries: int,
                manual: bool, nowait: bool, poll: int,
                judge_cmd=None, judge_manual: bool = None, judge_timeout=None,
                conflict_cmd=None, conflict_agent: bool = True,
                defect_cmd=None,
                retry_backoff: int = 0, retry_backoff_max: int = 0,
                redline: bool = True, track: bool = True, only=None) -> tuple:
    """Drive ONE round.

    `only` is an OnlySpec (or None): the round's stage filter is the union of
    the bare stage items and the `ROUND:STAGE` items that name this round, so
    `--only 1:review,2:judge` gives round 1 the review and round 2 the judge.
    A session item (`r1_w2`, `rewriter1`, `r1_judge_w2_j1`) narrows the round's
    run schedule to those sessions (see OnlySpec.entry_selected).
    """
    R = ctx.rounds_count()
    # The judge WAVE runs when the judge step or a judge session was selected; the
    # round DECISION (and therefore the next round) runs only when the whole judge
    # STEP was asked for (see OnlySpec.judge_step_in_full).
    judge_step = only is None or only.judge_step_in_full(r)
    judge_selected = only is None or only.stage_selected(r, "judge")
    csel = champion_select_of(ctx)
    scoped = journal_is_scoped(ctx)
    if scoped and csel == "integrate":
        die(f"--champion-select integrate has no meaning in revision mode "
            f"{journal_mode_of(ctx)!r}: a concern-scoped revision has no integration arm. "
            f"Use --champion-select revise (the scoped revision is already the answer).")
    auto_target = None
    if csel != "judge" and not scoped:
        # The advertised version is cheap to name; validate the whole plan only
        # when this invocation may actually decide the round. `--only review` on
        # an auto-mode root must still be able to run the review without being
        # blocked by a decision it did not ask for.
        _m0, _n0 = round_counts(ctx, r)
        auto_target = (integrate_vid(_m0 + 2) if csel == "integrate"
                       else revise_vid(1))
        if judge_step:
            auto_champion_vid(ctx, r, csel)
    print()
    print(f"[run] ==================== ROUND {r}/{R} ====================")
    rrec = ctx.round_rec(r)
    rrec["status"] = "active"
    rrec["started"] = rrec.get("started") or utcnow()
    # `run --only r1_judge_w2_j1` (and its roundless form `w2_j1`) selects WHICH
    # judge sessions this invocation RUNS. Asking for the whole judge step (a bare
    # `judge`, a round in full, `all`, or a plain `run`) drops any such selection
    # remembered from an earlier invocation, because then the round's panel is the
    # CONFIGURED panel -- a session list never redefines it, it only says what to
    # start now.
    _apply_judge_selection(rrec, only, judge_step, r, ctx)
    ctx.save_state()
    ph = {"cmd": cmd, "timeout": timeout, "jobs": jobs, "retries": retries,
          "manual": manual, "nowait": nowait, "poll": poll,
          "retry_backoff": retry_backoff, "retry_backoff_max": retry_backoff_max}
    # Judge sessions may run on a different backend/model than the production
    # stages (the judge panel is ~4x the session count and each session is a full
    # frozen-sweep review, so this is the main cost lever).
    ph_judge = dict(ph,
                    cmd=cmd if judge_cmd is None else judge_cmd,
                    timeout=timeout if judge_timeout is None else judge_timeout,
                    manual=manual if judge_manual is None else judge_manual)

    # (i) the round's base, then the whole dependency-driven run schedule. The
    # rewrites and the review start TOGETHER (both only need the base), each
    # revise starts as soon as the review marker exists, the integrations start
    # as soon as the WHOLE pool is done, and the judge wave follows the field --
    # no stage waits for an unrelated stage any more.
    m, n = round_counts(ctx, r)
    pool = round_pool_ids(m, n)
    mask = round_integrators(ctx, r)
    arms = integrator_arms(m, n, mask)
    try:
        materialize_a1(ctx, r)
    except DepsNotMet as exc:
        print(f"[run] round {r} base is not ready yet: {exc}")
        return False, False
    except Exception as exc:                                # noqa: BLE001
        die(f"cannot materialize the round {r} base: {exc}. The root is inconsistent; repair "
            f"the upstream output the message names and re-run (nothing was launched).")
    # Content-freshness pass: an upstream retry inside this (still incomplete)
    # round leaves downstream sandboxes holding superseded input bytes, and
    # re-materializing them would just re-hash the stale copies. Reset them
    # BEFORE anything is executed, so no agent runs on content the round no
    # longer contains (see revalidate_round_inputs).
    revalidate_round_inputs(ctx, r)
    ctx.save_state()
    _int_note = (f"{len(arms)} integration run(s) over the whole pool "
                 f"[integrators 0x{mask:X}]"
                 if arms else
                 f"NO integration run (integrators 0x{mask:X}: every applicable bit is clear)")
    if auto_target:
        _decision_note = (f"then NO judge panel: --champion-select {csel} auto-promotes "
                          f"{auto_target}"
                          + ("" if judge_step else " (decision NOT selected by --only)")
                          + " (the result is PROVISIONAL, not certified)")
    else:
        _decision_note = f"then the judge panel ({round_judges(ctx, r)} judge(s) per version)"
    print(f"[run] r{r} plan: M={m} rewrite(s) + {'1 review + ' if n else ''}"
          f"N={n} revise(s) -> pool {{{', '.join(pool)}}}; then "
          f"{_int_note}, {_decision_note}. "
          f"Sessions start as soon as their inputs exist (jobs={jobs}).")
    if n:
        for k, src in enumerate(pool, 1):
            mark = "" if k in arms else "  [SKIPPED: integrators bit clear]"
            print(f"[run] r{r}   {integrate_vid(k)} = {src} <- "
                  f"({', '.join(v for v in pool if v != src)}){mark}")
    ok, paused = run_round_runs(ctx, r, label=f"r{r}", only=only, **ph)
    if not ok:
        return False, paused

    if journal_is_scoped(ctx):
        # A major/minor revision has no judge panel and no champion choice: the
        # single concern-scoped revision IS the answer, and the response letter
        # (mode 2-4) was produced by the same plan. The round is closed here.
        a2 = revise_vid(1)
        rec2 = ctx.run(rid_for_fresh(r, a2)) or {}
        if rec2.get("status") != "done":
            print(f"[run] r{r}: the scoped revision run is not done "
                  f"({rec2.get('status', 'missing')}); the round stays incomplete")
            return False, False
        rrec = ctx.round_rec(r)
        rrec["champion"] = a2
        # Publish the winner UNDER --root like every other round (prune deletes
        # sandboxes and the contract it prints is "published winners are never
        # touched"). The old record pointed INSIDE the run's sandbox
        # (runs/r1_a2_revise/revised), so `prune --yes` destroyed it and the
        # next `run` died in pinned_integrity ("... is missing"), bricking the
        # root with no way back except restoring state.json.
        win_dst = winner_dir_of(ctx, r)
        # Atomic, like publish_winner(): a crash between `mkdir` and the copy
        # used to leave a PARTIALLY updated `round<r>_winner/` that the next run
        # copied the new corpus ON TOP OF (build_corpus_dir copies into the
        # directory, it does not clear it), and the digest then described -- and
        # publication carried -- a mixture of two revisions. The tmp build makes
        # the swap all-or-nothing; a displaced copy is archived, never deleted.
        win_tmp = ctx.root / (win_dst.name + ".tmp")
        if win_tmp.exists():
            rmtree_force(win_tmp)
        win_tmp.mkdir(parents=True, exist_ok=True)
        build_corpus_dir(ctx, r, a2, win_tmp)
        if win_dst.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            aside = unique_path(superseded_dir_of(ctx) / f"{win_dst.name}.{stamp}")
            aside.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(win_dst), str(aside))
        os.replace(win_tmp, win_dst)
        rrec["winner_dir"] = win_dst.name
        rrec["winner_digest"] = corpus_tree_digest(win_dst)
        rrec["journal_mode"] = journal_mode_of(ctx)
        rrec["scoped"] = True
        rrec["field"] = [A1_ID, a2]
        rrec["scores_per_version"] = 0
        rrec["status"] = "done"
        rrec["finished"] = utcnow()
        ctx.save_state()
        print(f"[run] r{r} {journal_mode_of(ctx)} revision complete: {a2} is the revised "
              f"manuscript (no judge panel: a concern-scoped revision is judged by the journal, "
              f"not by a quality panel)")
        round_tracking(ctx, r, track, round_redlines(ctx, r, redline))
        return True, False

    if auto_target and not judge_step:
        print(f"[run] r{r} --only {only.label()}: this selection does not ask for the "
              f"round DECISION, so nothing was pinned and round {r + 1} is not entered. "
              f"Run `--only judge` (or a plain `run`) to promote {auto_target}.")
        ctx.save_state()
        return False, False
    if auto_target:
        # NO JUDGE PANEL: the operator chose the winner up front. The round's
        # stages already ran (and, in `revise` mode, round_integrators() planned
        # no integration arm); promote the promised version, pin and publish it
        # exactly like a panel winner so the content-addressed chain and every
        # downstream consumer keep working.
        rec = ctx.run(rid_for_fresh(r, auto_target)) or {}
        if rec.get("status") != "done":
            print(f"[run] r{r} --champion-select {csel}: the promoted version "
                  f"{auto_target} is not done ({rec.get('status', 'missing')}); the round "
                  f"stays incomplete. Fix that run (`retry --run "
                  f"{rid_for_fresh(r, auto_target)}`) and re-run.")
            return False, False
        agg, sel = auto_round_payload(ctx, r, auto_target, csel)
        rrec = ctx.round_rec(r)
        rrec["auto_promoted"] = True
        rrec["judged"] = False
        rrec["certified"] = False
        pin = pin_champion(ctx, r, auto_target, agg)
        winner = publish_winner(ctx, r, auto_target, pin, agg)
        finalize_round(ctx, r, [{"id": auto_target, "kind": "auto", "vid": auto_target}],
                       [], agg, sel, pin)
        ctx.save_state()
        print()
        print(f"[run] r{r} champion: {auto_target} "
              f"(--champion-select {csel}; NO judge panel, NOT CERTIFIED -- provisional)")
        print(f"[run] round {r} champion: {auto_target} "
              f"(pinned at {PIN_DIRNAME}/{pin['id']}, digest {pin['digest'][:12]})")
        print(f"[run] round {r} winner published at {winner['directory']}/ "
              f"(same content as the pin; verified)")
        round_tracking(ctx, r, track, round_redlines(ctx, r, redline))
        return True, False

    # (viii) field + judge panel.
    field, dropped = build_field(ctx, r)
    for d in dropped:
        print(f"[run] r{r} field dedup: {d['id']} dropped — {d['reason']}")
    print(f"[run] r{r} field: {len(field)} member(s) "
          f"({', '.join(e['id'] for e in field)}) -> "
          f"{2 * round_judges(ctx, r) * (len(field) - 1)} directed scores per version")
    if only is not None and not judge_selected:
        print(f"[run] r{r} --only {only.label()}: the judge wave and the round decision are "
              f"NOT started in this invocation; run `--only judge` (or a plain `run`) to score "
              f"the field and pin the champion")
        ctx.save_state()
        return False, False
    if len(field) >= 2:
        # A selection can name a JUDGE session of a round whose own arms have not
        # run yet (`--only judge_t497f106d_j1`, or `--only r2_judge_w1_j1`): the
        # panel needs the WHOLE field, so say exactly what is missing instead of
        # raising from inside the materializer.
        missing = [rid_for_fresh(r, v) for v in round_produced_ids(ctx, r)
                   if (ctx.run(rid_for_fresh(r, v)) or {}).get("status") != "done"]
        if missing:
            print(f"[run] r{r}: the judge wave needs the WHOLE field of round {r} (the base, "
                  f"every rewrite, every revise arm and every integration run its mask "
                  f"selected); still missing: {', '.join(missing[:6])}"
                  + (" ..." if len(missing) > 6 else ""))
            print(f"[run] r{r}: nothing was judged in this invocation. Start the round's stages "
                  f"first -- a plain `run`, or `--only "
                  f"{','.join(sorted({plan_stage_of(e) for e in round_run_plan(ctx, r)}))}` -- "
                  f"then re-run this selection (`--only judge` or the same judge run id).")
            ctx.save_state()
            return False, False
        judge_ids = materialize_judges(ctx, r, field)
    else:
        # Every fresh arm produced documents content-identical to the round's
        # base, so the whole field deduplicated into a single member: there is
        # nothing to judge, and materialize_judges raises "no opponents to
        # judge", which used to kill `run` with a traceback. The rest of the
        # machinery already handles a 1-member field (expected = 0 -> panel
        # complete; the champion falls back to the base, which is the documented
        # "no demonstrable progress" outcome).
        judge_ids = []
        print(f"[run] r{r} field has a single member after content deduplication; "
              f"skipping the judge wave (no opponents to judge)")
    ctx.save_state()
    _enabled_note = judges_enabled_spec(ctx, r)
    print(f"[run] r{r} final stage: {len(judge_ids)} judge session(s) "
          + (f"[--only judge sessions: {judges_enabled_note(ctx, r)}]"
             if _enabled_note else f"({round_judges(ctx, r)} per version)")
          + ", run in parallel")
    ok, paused = run_phase(ctx, judge_ids, label=f"r{r} judge", **ph_judge)
    if not ok:
        return False, paused

    if not judge_step:
        # A judge SESSION selection ran its sessions; the round DECISION (select +
        # pin the champion) and, through the pin, the NEXT ROUND are steps the
        # operator did not ask for. `--only` never continues into them: the round
        # stays pending and the invocation exits non-zero.
        print(f"[run] r{r} --only {only.label()}: the selected judge session(s) ran, but the "
              f"ROUND DECISION is NOT started -- this selection does not ask for the judge STEP, "
              f"so no winner is selected, nothing is pinned and round {r + 1} is not entered.")
        print(f"[run] r{r}: finish the judge step when you want the round decided: "
              f"`run --only judge` runs the remaining panel (the sessions already done are kept) "
              f"and pins the champion, or use a plain `run`.")
        ctx.save_state()
        return False, False

    agg = aggregate_round(ctx, r, [e["id"] for e in field])
    # The exact numbers behind the ranking (and behind the median/mean the table
    # below prints): ONE row per directed score in the member's own frame. Written
    # BEFORE the panel-gap check, so an undecided round's scores are just as
    # inspectable -- "why do the median and the mean disagree?" is answered by the
    # `credited` column, not by re-deriving the frame by hand.
    try:
        _rs = write_round_raw_scores(ctx, r, agg)
        print(f"[run] r{r} raw scores: {_rs.relative_to(ctx.root).as_posix()} "
              f"({len(agg.get('score_rows') or [])} directed score row(s); the member's "
              f"median/mean are computed from its `credited` column)")
    except OSError as e:
        print(f"[run] r{r} WARNING: could not write the round's raw scores: {e}")
    # The reported issue census (issues per version, tier and severity) rides
    # beside the raw scores: same sheets, same aggregation, one extra file the
    # operator can concatenate across runs.
    try:
        _ic = write_round_issue_census(ctx, r, agg)
        _im = write_round_issue_matrix(ctx, r, agg)
        _icm = write_round_issue_cumulative(ctx, r, agg)
        _ida = write_round_dedup_audit(ctx, r, agg)
        _df = write_round_defects(ctx, r, agg)
        print(f"[run] r{r} issue census: {_ic.relative_to(ctx.root).as_posix()} "
              f"({sum((v.get('total') or 0) for v in (agg.get('issue_census') or {}).values())} "
              f"issue row(s) attributed across {len(agg.get('issue_census') or {})} version(s)); "
              f"severity_tier_category matrix + prefix sums -> "
              f"{_im.name}, {_icm.name}; dedup audit ({dedup_mode_of(ctx)}) -> {_ida.name}; "
              f"defect list -> {_df.relative_to(ctx.root).as_posix()} "
              f"({len(agg.get('issue_rows') or [])} defect row(s), "
              f"{sum(1 for x in (agg.get('issue_rows') or []) if x.get('counted') == 'yes')} "
              f"counted)")
    except OSError as e:
        print(f"[run] r{r} WARNING: could not write the round's issue census: {e}")
    # The LLM defect audit (diagnostic): labels every defect row TP/FP and writes
    # the audited TP-only report family.  It NEVER feeds the ranking below -- the
    # champion is selected from `agg` exactly as before, and `sel`/the pin read
    # the non-audited census only.
    defect_audit = {"used": False, "reason": "not started"}
    try:
        defect_audit = write_round_defect_audit(
            ctx, r, agg=agg, agent_cmd=defect_cmd,
            timeout=(judge_timeout or timeout))
        if defect_audit.get("used"):
            if defect_audit.get("ok"):
                _dst = " (reused)" if defect_audit.get("reused") else ""
                _extra = (f"; {defect_audit['incomplete']} unlabelled"
                          if defect_audit.get("incomplete") else "")
                print(f"[run] r{r} LLM defect audit{_dst}: "
                      f"{defect_audit.get('tp', 0)} TP / {defect_audit.get('fp', 0)} FP "
                      f"of {defect_audit.get('rows', 0)} defect row(s){_extra} -> "
                      f"reports/round{r}_auditedTP_defects.csv "
                      f"(+ audited census/matrix/cumulative/raw scores)")
            else:
                print(f"[run] r{r} WARNING: the LLM defect audit produced no verdict "
                      f"({defect_audit.get('reason')}); no audited files were written")
        else:
            print(f"[run] r{r} note: the LLM defect audit is off "
                  f"({defect_audit.get('reason')})")
    except Exception as e:                                           # noqa: BLE001
        print(f"[run] r{r} WARNING: the LLM defect audit failed: {e}")
    # Cross-judge conflicts: two independent sessions can contradict each other
    # about the same comparison or the same claim.  The aggregation keeps both
    # judgments on purpose, so the disagreements are written here as REQUIRED
    # MANUAL CHECKS (never silently averaged away).  This runs ONCE PER ROUND,
    # right after the judge wave: the deterministic pass always runs, while the
    # LLM pass is OFF by default (the LLM defect audit above covers that ground)
    # and runs only for an explicit --conflict-agent[-cmd] or
    # PAPER_CONFLICT_AGENT_CMD this invocation.
    try:
        _audit_cmd, _audit_src = resolve_round_audit_cmd(
            conflict_cmd, conflict_agent, judge_cmd, judge_manual,
            ctx.state.get("conflict_agent") or {})
        # Record the backend the audit actually uses so a later `decide` reuses
        # the SAME one by default (a real run records codex-lite, a stub run
        # records the stub) instead of resolving an unrelated default.
        ctx.state["conflict_agent"] = {
            "cmd": ([str(x) for x in _audit_cmd]
                    if (conflict_agent and _audit_cmd) else None),
            "source": _audit_src,
            "recorded": utcnow(),
        }
        ctx.save_state()
        _cf = write_round_judge_conflicts(
            ctx, r, agg=agg,
            agent_cmd=(_audit_cmd if conflict_agent else None),
            timeout=(judge_timeout or timeout))
        _cc = _cf.get("counts") or {}
        print(f"[run] r{r} judge conflicts: {_cc.get('total', 0)} flagged for manual review "
              f"({_cc.get('blocker', 0)} blocker, {_cc.get('major', 0)} major, "
              f"{_cc.get('minor', 0)} minor) -> reports/round{r}_judge_conflicts.md")
        if _cc.get("total"):
            print(f"[run] r{r} NOTE: the judge panel contradicts itself on "
                  f"{_cc.get('total')} item(s); resolve the manual checks in "
                  f"reports/round{r}_judge_conflicts.md (and the cumulative "
                  f"reports/JUDGE_CONFLICTS_TODO.md) before citing this round's numbers.")
        write_judge_conflicts_todo(ctx)
    except Exception as e:                                           # noqa: BLE001
        print(f"[run] r{r} WARNING: the judge-conflict audit failed: {e}")
    # A shrunk panel must never produce a champion: if any field member is
    # missing directed scores (a judge sheet that silently dropped a comparison,
    # a stale judge run, a whole version's sheets), stop BEFORE selecting and
    # pinning, so the retries above (or an operator `retry`) can restore it.
    gaps = [vid for vid in agg["field"]
            if not (agg["stats"].get(vid) or {}).get("complete")]
    if gaps:
        diags = agg.get("diagnostics") or {}
        print()
        print(f"[run] r{r}: JUDGE PANEL INCOMPLETE for {', '.join(gaps)} -- refusing to decide "
              f"the round on a shrunk panel.")
        for line in (diags.get("incomplete_sheets") or [])[:8]:
            print(f"       - {line}")
        for line in (diags.get("superseded_sheets") or [])[:4]:
            print(f"       - superseded sheet: {line}")
        for line in (diags.get("out_of_range_sheets") or [])[:4]:
            print(f"       - ignored sheet: {line}")
        print("       Fix the failing/partial judge session(s) with `retry --run <ID>` (or re-run "
              "`run`) and the round is re-decided with the full panel; nothing was pinned.")
        rrec = ctx.round_rec(r)
        rrec["status"] = "pending"
        rrec["panel_gaps"] = {"round": int(r), "gaps": gaps, "diagnostics": diags,
                              "checked": utcnow()}
        write_json_atomic(ctx.reports_dir / f"round{int(r)}_panel_gaps.json", rrec["panel_gaps"])
        ctx.log("panel-incomplete", detail=f"round {r}: {', '.join(gaps)}")
        ctx.save_state()
        return False, False

    sel = select_champion(ctx, r, agg)
    _tb = sel.get("tiebreak") or {}
    print(f"[run] r{r} defect-prefix tie-break: floor {_tb.get('floor', '?')}, used "
          f"{_tb.get('cells_used', '?')} of {_tb.get('cells_total', '?')} "
          f"severity_tier_category cell(s)"
          + (f" (last: {_tb.get('cell_order', [])[-1]})"
             if _tb.get("cell_order") else ""))
    pin = pin_champion(ctx, r, sel["champion"], agg)
    winner = publish_winner(ctx, r, sel["champion"], pin, agg)
    finalize_round(ctx, r, field, dropped, agg, sel, pin)
    ctx.save_state()
    champ_rep = sel.get("champion_rep") or sel["champion"]
    rows = round_member_table_rows(ctx, r, field, agg, sel, champ_rep)
    print()
    print(_tbl(rows[1:], rows[0]))
    # The audited member table is a DIAGNOSTIC view: the same score columns and
    # the same champion note, but the defect counts re-counted over the LLM
    # auditor's TP rows.  The champion selection above never reads it.
    if defect_audit.get("ok") and defect_audit.get("audited"):
        try:
            arows = round_member_table_rows(ctx, r, field, defect_audit["audited"],
                                            audited_table_sel(sel), champ_rep)
            print()
            print(f"[run] r{r} member table -- LLM-audited defects (TP-only; "
                  f"diagnostic; the champion row above is unchanged)")
            print(_tbl(arows[1:], arows[0]))
        except Exception as e:                                       # noqa: BLE001
            print(f"[run] r{r} WARNING: could not print the audited member table: {e}")
    _tb = (sel or {}).get("tiebreak") or {}
    print(f"[run] ranking key: the cumulative defect count over the "
          f"adaptive severity_tier_category prefix (fatal->critical->major->minor, tier order, "
          f"peer before own; used {_tb.get('cells_used', '?')} of {_tb.get('cells_total', '?')} "
          f"cells at floor {_tb.get('floor', '?')}) -> median -> mean -> IQR -> digest. "
          f"The table's columns follow that order (member id, the LAST key, is the row label); "
          f"every column after the digest is reported only, never ranked, and the per-severity "
          f"totals are counts, not the tie-break ordering.")
    if sel["champion"] == A1_ID and champ_rep != A1_ID:
        print(f"[run] round {r}: no fresh arm outranked the round's base -- the champion is the "
              f"incumbent base A1 (scored here as the content-identical member '{champ_rep}'), "
              f"so this round records no demonstrable progress instead of a step backwards.")
    print(f"[run] round {r} champion: {sel['champion']} "
          f"(pinned at {PIN_DIRNAME}/{pin['id']}, digest {pin['digest'][:12]})")
    print(f"[run] round {r} winner published at {winner['directory']}/ "
          f"(same content as the pin; verified)")
    # Tracked-changes copies are an audit aid: a failure here must never fail
    # the round, but it is always reported and recorded in the manifest.
    round_tracking(ctx, r, track, round_redlines(ctx, r, redline))
    return True, False

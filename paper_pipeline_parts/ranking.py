"""Pure ranking and defect-census calculations for a recorded round."""


from __future__ import annotations


import itertools


A1_ID = "a1"
BASIS_TIERS = ("correctness", "preservation", "completeness", "consistency", "writing",
               "formatting")
VS_ORIGINAL_TOLERANCE = 0.0


# ---- the champion selection key (2026-10-01 calibrations) ------------------
# `fatal -> critical -> major -> minor -> median -> mean -> IQR -> digest`,
# where the fatal -> ... -> minor stage is the ADAPTIVE DEFECT PREFIX below:
#   * the DEFECT PREFIX LEADS (fourth calibration): the number of defects the
#     panel attributed to a version is the most direct improvement signal, and
#     the panel median is coarse on a small integer scale;
#   * the median, the mean and the IQR are the panel statistics BELOW it;
#   * the defect counts come from the round's issue census and are compared
#     CELL BY CELL in canonical `severity_tier_category` order (the walk grows
#     the prefix until the cleanest ranked version carries
#     `tiebreak_defect_floor` defects or every cell is included): each cell is
#     its own lexicographic rung, so a fatal defect never ties a minor one.
#     The cells are counts, not rates -- every ranked version's opportunities
#     are the same in a complete panel, so the exposure normalization
#     (own/peer) is carried by the cell ORDER (peer before own);
#   * the counts are the mentions each judge sheet filed (collapsed only per
#     session+version, never matched across sheets by default), with the opt-in
#     `dedup_mode` "location" available when the operator wants the
#     structured-key merge;
#   * the median, then the mean, break a tie ONLY when the whole ordered census
#     is equal (the panel statistics are coarse on small integer scores);
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
#   * the version's ordered per-cell census at that prefix is the leading key
#     (fewer defects, and a worse severity earlier, is worse). The median is
#     consulted ONLY when the whole census is equal, then the mean, IQR, digest
#     and id.
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


def _census_row(vid, census) -> dict:
    """One version's census row out of a bare `{vid: row}` map."""
    return ((census or {}).get(str(vid)) or {})


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
        tiers = (_census_row(vid, census).get("tiers") or {})
        row = []
        for name, tier, src in specs:
            sevs = ((tiers.get(tier) or {}).get("severities") or {})
            row.append(sum(int((sevs.get(sev) or {}).get(src) or 0)
                           for sev in tiebreak_group_severities(name)))
        matrix[str(vid)] = row
    cumulative = {vid: list(itertools.accumulate(row)) for vid, row in matrix.items()}
    return names, matrix, cumulative


def tiebreak_prefix_cells(cumulative: dict, versions, floor: int) -> int:
    """How many leading cells the tie-break uses (0 for an empty prefix).

    The first prefix at which the version with the FEWEST defects reaches the
    floor wins; if no prefix reaches it, every cell is used. A floor <= 0 is
    reached by the EMPTY prefix, so no census cell leads (Rule 6).
    """
    if not cumulative or not versions:
        return 0
    if floor <= 0:
        return 0
    n_cells = len(next(iter(cumulative.values())))
    for i in range(n_cells):
        if min(int(cumulative[str(v)][i]) for v in versions) >= floor:
            return i + 1
    return n_cells


def _issue_summary_from_census(vid, census) -> dict:
    """`champion_issue_summary` over a bare `{vid: row}` census map (no `agg`)."""
    tiers = (_census_row(vid, census).get("tiers") or {})
    out = {}
    for sev in ("critical", "fatal", "major", "minor"):
        own = sum(int((((tiers.get(t) or {}).get("severities") or {})
                       .get(sev) or {}).get("own") or 0) for t in BASIS_TIERS)
        peer = sum(int((((tiers.get(t) or {}).get("severities") or {})
                        .get(sev) or {}).get("peer") or 0) for t in BASIS_TIERS)
        out[sev] = {"own": own, "peer": peer}
    return out


def champion_sort_key(row: dict) -> tuple:
    """defect census at the adaptive prefix -> median -> mean -> IQR -> digest.

    The adaptive-prefix census LEADS the key: the per-cell counts, ordered
    fatal, critical, major, minor, then by tier, preserve the severity and
    tier of every defect. The cumulative count alone would tie a fatal defect
    with a minor one; the census does not. The panel's median/mean/IQR and the
    digest are the tie-breaks below it. A difference in the leading term is not
    a tie.
    """
    census = row.get("defect_prefix_census")
    if census is None:
        total = row.get("defect_prefix_total")
        # A missing census/total is MISSING EVIDENCE, never zero defects: a
        # legacy/trimmed row with no recorded census must not outrank a row that
        # really carries one defect (Rule 6's "missing value is worst").
        census = (int(total),) if total is not None else (10 ** 9,)
    med, mean, iqr = row.get("median"), row.get("mean"), row.get("iqr")
    return (tuple(int(x) for x in census)
            + (-(med if med is not None else -99.0),)
            + (-(mean if mean is not None else -99.0),
               (iqr if iqr is not None else 99.0),
               str(row.get("digest") or "~")))


def derive_ranking(stats: dict, candidates: list, base_rep, census: dict,
                   floor: int, round_no: int) -> dict:
    """Rank the round's candidates from RECORDED inputs only (Rule 6's purity).

    Every input is plain data: the panel's per-version statistics (`stats`), the
    round's fresh-arm ids (`candidates`), the field member whose content IS the
    round's base (`base_rep`), the panel's issue census (`census`) and the defect
    floor the round was decided with (`floor`). This function reads no `ctx`, no
    live config and no file, so re-deriving a past round reproduces its champion
    from the recorded inputs: a later config edit cannot move a past pin (F18
    and F19 were exactly that class of bug).

    Eligibility: a complete panel is required for every row, and a FRESH arm
    must additionally clear the anti-regression gate against the pristine
    original. The base row itself is the incumbent status quo -- the gate exists
    to stop a NEW regression, and the no-progress fallback crowns the base even
    when nothing clears the gate, so the base is judged on its panel alone.

    The returned `ranking` rows carry the core columns only. `select_champion`
    adds the REPORTED-only tiebreak inputs (critical_remaining /
    writing_remaining / manual_steps), which never rank.
    """
    trace = []
    candidates = list(candidates or [])
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
    if base_rep and base_rep not in stats:
        # The round's base member has no panel row (a trimmed/legacy state): it
        # cannot compete, and subscripting it would abort the whole decision.
        trace.append(f"the round's base is content-identical to field member {base_rep!r}, "
                     f"but that member has NO stats row in this field; the base cannot compete "
                     f"and the selection falls back to the fresh arms only")
    elif base_rep:
        contenders.append((A1_ID, base_rep, True))
        trace.append(f"the round's base A1_{round_no} is content-identical to field member "
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
        if not is_base and not st.get("vs_original_complete"):
            # An ABSENT/None flag is not a complete anti-regression panel: only
            # a recorded pass (True) may clear the gate (Rule 6).
            trace.append(f"{label}: ANTI-REGRESSION PANEL INCOMPLETE "
                         f"({st.get('vs_original_n')} of {st.get('vs_original_expected')} scores "
                         f"against the original) -> ineligible")
            continue
        if not is_base and not st.get("anti_regression_ok"):
            trace.append(f"{label}: anti-regression gate FAILED (vs_original median "
                         f"{st.get('vs_original')!r} < {VS_ORIGINAL_TOLERANCE:g}) -> ineligible")
            continue
        if not str(st.get("digest") or "").strip():
            # Rule 5: a candidate's identity is its content digest. A row with
            # no recorded digest cannot be told from another except by its arm's
            # name/input order, so it is ineligible rather than silently ranked
            # by that order.
            trace.append(f"{label}: no content digest recorded -> ineligible: identity is "
                         f"the content digest (Rule 5), and an undigested row would be "
                         f"ordered by its name/position")
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
        rows.append({"id": cid, "rep": row_id, "is_base": bool(cid == A1_ID and base_rep),
                     "n": st["n"], "median": st["median"], "mean": st["mean"],
                     "iqr": st["iqr"], "vs_original": st["vs_original"],
                     "vs_base": st["vs_base"],
                     "digest": st.get("digest"),
                     "author_placeholders": st.get("author_placeholders"),
                     "issues": _issue_summary_from_census(row_id, census),
                     "captions": st.get("caption_note")})
    # The adaptive defect prefix (the ranking's LEADING comparator): walk the
    # canonical severity_tier_category order, accumulate the reported counts for
    # every ranked version, and stop at the first prefix where the version with
    # the FEWEST defects reaches the configured floor (or when every cell is
    # used). The ordered per-cell census at that prefix leads the sort key (each
    # cell a separate rung); the median (then the mean, IQR and digest) is
    # the tie-break below it.
    rep_ids = sorted({str(t["rep"]) for t in rows})
    cell_names, _matrix, cumulative = issue_matrix_and_cumulative(census, rep_ids)
    prefix_cells = tiebreak_prefix_cells(cumulative, rep_ids, floor)
    for t in rows:
        t["defect_prefix_total"] = (cumulative[str(t["rep"])][prefix_cells - 1]
                                    if prefix_cells else 0)
        # The leading key is the ordered census at the same prefix, not just
        # its length: the per-cell counts preserve the defect's tier/severity.
        t["defect_prefix_census"] = tuple(
            int(x) for x in (_matrix.get(str(t["rep"])) or [])[:prefix_cells])
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
    #   IQR, digest          deterministic fallbacks. The content digest is the
    #                         LAST rung: a perfect tie is decided by the bytes,
    #                         never by the arm's NAME (a2 < i1 < w1 would silently
    #                         favour the revise arm), and Rule 6 names no id term.
    #                         Content-identical candidates are one candidate
    #                         (Rule 5), so equal digests are the same artifact.
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
    trace.append(f"ranking key: (the ordered per-cell defect census over the first "
                 f"{prefix_cells} cell(s) of the canonical severity_tier_category order "
                 f"(fatal->critical->major->minor, tier order, peer before own; each cell is a "
                 f"separate lexicographic rung; the walk stops when the cleanest ranked version "
                 f"reaches the floor {floor} or all {len(cell_names)} cells are used) -- then "
                 "-median, -mean, IQR, digest); the per-cell counts come from the panel's own "
                 "census (the self-reported critical_remaining/writing_remaining values are "
                 "reported but no longer rank), median/mean/IQR are the field-wide panel "
                 "statistics below it, and the content digest is the provenance-free tie-break "
                 "(an arm's NAME never decides a tie). "
                 "An exact (median, mean, IQR) tie is applied as retention BEFORE the prefix "
                 "and digest, so a different defect count separates challengers but "
                 "does not retire a base the panel cannot distinguish from them. "
                 "vs_base is reported but NOT a ranking key: its 2*judges directed scores are few "
                 "enough that one outlier session flips the sign statistic, so the decision stays "
                 "on the field-wide list. MANUAL_STEPS.md is reported but never ranked on; "
                 "missing counts sentinel = +inf")
    return {"champion": champ_row["id"], "champion_rep": champ_row["rep"],
            "base_rep": base_rep, "eligible": eligible, "ranking": rows, "trace": trace,
            "tiebreak": {"floor": floor, "cells_used": prefix_cells,
                         "cell_order": cell_names[:prefix_cells],
                         "cells_total": len(cell_names)}}

# -*- coding: utf-8 -*-
# Part 10/20 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# REPORTS / STATUS
# =====================================================================

def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def do(f) -> None:
        f.write(text)

    _atomic_write_bytes(tmp_path_for(path), path, do)


def _tbl(rows: list, header: list) -> str:
    rows = [[str(c) for c in r] for r in rows]
    header = [str(h) for h in header]
    widths = [max(len(r[i]) for r in [header] + rows) for i in range(len(header))]
    sep = "-+-".join("-" * w for w in widths)
    lines = [" | ".join(h.ljust(w) for h, w in zip(header, widths)), sep]
    lines += [" | ".join(r[i].ljust(w) for i, w in enumerate(widths)) for r in rows]
    return "\n".join(lines)


def _ledger_cell(items) -> str:
    """One CSV cell for a comparison's ledger side ('tier/severity: evidence')."""
    if not isinstance(items, list):
        return ""
    parts = []
    for it in items:
        if not isinstance(it, dict):
            continue
        tier = str(it.get("tier") or "?").strip()
        sev = str(it.get("severity") or "?").strip()
        ev = " ".join(str(it.get("evidence") or "").split())
        parts.append(f"{tier}/{sev}: {ev[:120]}")
    return " | ".join(parts)


def write_raw_scores(ctx: Ctx, rounds_data: list) -> Path:
    """Every directed score, exactly as collected (audit trail)."""
    p = ctx.reports_dir / "raw_scores.csv"
    rows = []
    for rd in rounds_data:
        for rec in ctx.runs(kind="judge", round_no=rd["round"]):
            sj = rec.get("scores") or {}
            lm = rec.get("label_map") or {}
            for comp in sj.get("comparisons") or []:
                if not isinstance(comp, dict):
                    continue
                label = comp.get("opponent_label")
                rows.append({"round": rd["round"], "judge_run": rec["id"],
                             "judge_index": rec.get("judge_index"),
                             "target_id": rec.get("target_id"),
                             "opponent_label": label,
                             "opponent_id": lm.get(_norm_opponent_label(label)),
                             "score": comp.get("score"),
                             # Judge contract v2: the graded basis and the ledger
                             # behind the integer, kept in the audit trail so the
                             # calibration of every score is inspectable.
                             "basis": comp.get("basis"),
                             "resolved": _ledger_cell(comp.get("resolved")),
                             "introduced": _ledger_cell(comp.get("introduced")),
                             # str() on purpose: agent-written JSON is revived by
                             # read_json, so a literal "Infinity" note would come
                             # back as a float and break slicing.
                             "reason": (str(comp.get("reason")) if comp.get("reason")
                                        else "")[:200]})
    fields = ["round", "judge_run", "judge_index", "target_id", "opponent_label",
              "opponent_id", "score", "basis", "resolved", "introduced", "reason"]
    return write_csv_atomic(p, fields, rows)


# The columns of a round's own raw-score file. The first block is the FLAT LIST
# every statistic is computed from (`member` + `credited`), the second the sheet
# the entry came from (the same provenance the whole-pipeline raw_scores.csv
# keeps), so a reader can recompute the median/mean AND see which session moved
# them.
ROUND_RAW_SCORE_FIELDS = ("round", "member", "credited", "direction", "opponent_id",
                          "opponent_label", "source_judge_run", "source_judge_index",
                          "sheet_target", "score_as_written", "basis", "resolved",
                          "introduced", "reason", "member_n", "member_median",
                          "member_mean")


def write_round_raw_scores(ctx: Ctx, r: int, agg: dict = None, name: str = None) -> Path:
    """`reports/round<r>_raw_scores.csv`: the exact flat lists behind median/mean.

    ONE row per directed score in the member's own frame:

      * `direction = own`      the member's own judge session scored it against
                               `opponent_id`; `credited` is that integer;
      * `direction = received` another member's session scored THAT member against
                               this one; the entry in this member's list is the
                               negation, so `credited = -score_as_written`.

    `member_n` / `member_median` / `member_mean` repeat the RECORDED statistic for
    the member on every one of its rows, so the file answers "why do the median
    and the mean disagree?" without a join: the two statistics are computed from
    exactly the `credited` column of the rows below them. `run` writes this as soon
    as a round is aggregated (decided or not -- an incomplete panel's scores are
    just as inspectable) and `decide` back-fills any round that predates the file.
    """
    r = int(r)
    if agg is None:
        field = [str(v) for v in (ctx.round_rec(r).get("field") or [])]
        agg = aggregate_round(ctx, r, field) if field else {"score_rows": [], "stats": {},
                                                            "field": []}
    stats = agg.get("stats") or {}
    order = {str(v): i for i, v in enumerate(agg.get("field") or [])}
    rows = []
    for row in agg.get("score_rows") or []:
        st = stats.get(row["member"]) or {}
        out = dict(row)
        out["member_n"] = st.get("n")
        out["member_median"] = st.get("median")
        out["member_mean"] = (round(float(st["mean"]), 6)
                              if isinstance(st.get("mean"), (int, float)) else None)
        rows.append(out)
    rows.sort(key=lambda x: (order.get(str(x["member"]), 10 ** 6), str(x["member"]),
                             str(x["direction"]) != "own", str(x["source_judge_run"] or ""),
                             str(x["opponent_id"] or "")))
    # `name` lets the diagnostic LLM defect audit write its TP-only counterpart
    # (`round<r>_auditedTP_raw_scores.csv`) with the same writer; the default
    # keeps every existing caller byte-identical.
    p = ctx.reports_dir / (name or f"round{r}_raw_scores.csv")
    return write_csv_atomic(p, ROUND_RAW_SCORE_FIELDS, rows)


# The columns of a round's issue-census file: ONE row per (version, tier,
# severity), so a chain of runs concatenates into a trend table without parsing
# the report. `own`/`peer` keep the two ledger sources apart (see
# build_issue_census), `per_session` is the field-size-stable rate, and `run` is
# the pipeline root's name so rows from several runs can be told apart.
ISSUE_CENSUS_FIELDS = ("run", "round", "version", "tier", "severity", "own", "peer",
                       "total", "per_session",
                       # The counts are per-session mentions; the rates divide them
                       # by the opportunities (no cross-session matching).
                       "own_rate", "peer_rate",
                       # `own`/`peer` are the EFFECTIVE counts. With the opt-in
                       # `dedup_mode` "location" the *_raw columns are what the
                       # sheets filed and *_merged how many rows were merged
                       # away; both equal their effective counterparts when off.
                       "raw_own", "raw_peer", "merged_own", "merged_peer",
                       "dedup_mode",
                       "own_sessions", "peer_sessions", "own_opps", "peer_opps",
                       "sessions_expected")


def issue_census_rows(ctx: Ctx, r: int, agg: dict) -> list:
    """The flat (version, tier, severity) rows of one round's issue census."""
    rows = []
    run = ctx.root.name
    order = {str(v): i for i, v in enumerate(agg.get("field") or [])}
    for vid, c in (agg.get("issue_census") or {}).items():
        for tier in BASIS_TIERS:
            t = (c.get("tiers") or {}).get(tier) or {}
            for sev in SEVERITIES:
                s = (t.get("severities") or {}).get(sev) or {}
                rows.append({"run": run, "round": int(r), "version": vid, "tier": tier,
                             "severity": sev, "own": int(s.get("own") or 0),
                             "peer": int(s.get("peer") or 0),
                             "total": int(s.get("total") or 0),
                             "per_session": s.get("per_session"),
                             "own_rate": s.get("own_rate"),
                             "peer_rate": s.get("peer_rate"),
                             "raw_own": int(s.get("raw_own") or 0),
                             "raw_peer": int(s.get("raw_peer") or 0),
                             "merged_own": int(s.get("merged_own") or 0),
                             "merged_peer": int(s.get("merged_peer") or 0),
                             "dedup_mode": c.get("dedup_mode") or "off",
                             "own_sessions": c.get("own_sessions"),
                             "peer_sessions": c.get("peer_sessions"),
                             "own_opps": c.get("own_opps"),
                             "peer_opps": c.get("peer_opps"),
                             "sessions_expected": c.get("sessions_expected")})
    rows.sort(key=lambda x: (order.get(str(x["version"]), 10 ** 6), str(x["version"]),
                             BASIS_TIERS.index(x["tier"]), SEVERITIES.index(x["severity"])))
    return rows


def write_round_issue_census(ctx: Ctx, r: int, agg: dict = None,
                             name: str = None) -> Path:
    """`reports/round<r>_issue_census.csv`: issues per version, tier and severity.

    It answers "how many issues of each tier does each version carry, and who
    found them (own sweep vs peer comparison)" -- the number a chain of runs
    compares across rounds. The selection's LEADING comparator reads the reported
    per-source counts through the two sibling files this module also writes:
    `round<r>_issue_matrix.csv` (each severity_tier_category cell) and
    `round<r>_issue_cumulative.csv` (their prefix sums).
    ONE row per (version, tier, severity), zeros included, so the file's shape
    is stable across rounds and runs even when a round's sheets carry no ledger
    rows.
    """
    r, agg = _issue_file_agg(ctx, r, agg)
    p = ctx.reports_dir / (name or f"round{r}_issue_census.csv")
    return write_csv_atomic(p, ISSUE_CENSUS_FIELDS, issue_census_rows(ctx, r, agg))


def _issue_file_agg(ctx: Ctx, r: int, agg: dict = None) -> tuple:
    """(round, aggregation) for the census/matrix/cumulative writers."""
    r = int(r)
    if agg is None:
        field = [str(v) for v in (ctx.round_rec(r).get("field") or [])]
        agg = aggregate_round(ctx, r, field) if field else {"issue_census": {}, "field": []}
    return r, agg


# The columns of the round's DEFECT LIST (the census's long form): one row per
# defect mention the panel filed, carrying the meta an operator asks about
# per defect -- the version it belongs to, who found it (own sweep vs peer
# comparison), the sheet it came from and the target/opponent of that
# comparison, the frozen check id, the defect class (`tier`), the severity rung,
# and the sheet's own evidence sentence as the verbal description. `counted`
# separates the mentions the census counted (`yes`) from the ones the OPT-IN
# `dedup_mode` "location" merged into an earlier row (`no`, with `merged_into`
# naming the kept row's session), so the two files stay consistent.
DEFECT_LIST_FIELDS = ("run", "round", "defect_id", "version", "source", "side",
                      "target_version", "peer_version", "session", "judge_index",
                      "check", "tier", "severity", "evidence",
                      "dedup_mode", "counted", "merged_into",
                      "comparison_score", "comparison_basis")


def defect_list_rows(ctx: Ctx, r: int, agg: dict) -> list:
    """The flat rows of one round's defect list (see DEFECT_LIST_FIELDS)."""
    rows = agg.get("issue_rows")
    if rows is None:
        # A round aggregated by a pipeline OLDER than this report carries no
        # row list; re-deriving it from the round's judge sheets (the same
        # observations the census uses) keeps the file available for it.
        rows = _defect_rows_by_reaggregation(ctx, r)
    field_order = {str(v): i for i, v in enumerate(agg.get("field") or [])}
    session_index = {}
    for rec in ctx.runs(kind="judge", round_no=int(r)):
        session_index[str(rec.get("id"))] = rec.get("judge_index")
    out = []
    for i, row in enumerate(rows, 1):
        out.append({
            "run": ctx.root.name, "round": int(r),
            "defect_id": f"r{int(r)}-D{i:04d}",
            "version": row.get("version"), "source": row.get("source"),
            "side": row.get("side"), "target_version": row.get("target_version"),
            "peer_version": row.get("peer_version"),
            "session": row.get("session"),
            "judge_index": session_index.get(str(row.get("session"))),
            "check": row.get("check"), "tier": row.get("tier"),
            "severity": row.get("severity"), "evidence": row.get("evidence"),
            "dedup_mode": row.get("dedup_mode"),
            "counted": row.get("counted"), "merged_into": row.get("merged_into"),
            "comparison_score": row.get("comparison_score"),
            "comparison_basis": row.get("comparison_basis")})
    out.sort(key=lambda x: (field_order.get(str(x["version"]), 10 ** 6),
                            str(x["version"]),
                            -SEVERITIES.index(str(x["severity"]))
                            if str(x["severity"]) in SEVERITIES else 0,
                            BASIS_TIERS.index(str(x["tier"]))
                            if str(x["tier"]) in BASIS_TIERS else len(BASIS_TIERS),
                            str(x["target_version"]), str(x["peer_version"]),
                            str(x["session"])))
    for i, row in enumerate(out, 1):
        row["defect_id"] = f"r{int(r)}-D{i:04d}"
    return out


def _defect_rows_by_reaggregation(ctx: Ctx, r: int) -> list:
    """Re-derive one round's defect rows from its judge sheets (never invents)."""
    field = [str(v) for v in (ctx.round_rec(int(r)).get("field") or [])]
    if not field:
        return []
    return list(aggregate_round(ctx, int(r), field).get("issue_rows") or [])


def write_round_defects(ctx: Ctx, r: int, agg: dict = None, name: str = None) -> Path:
    """`reports/round<r>_defects.csv`: EVERY defect the round's panel filed.

    The issue census answers "how many issues of each class does each version
    still carry"; this file answers "WHICH ones, on which version, found against
    which comparison, and what does the sheet say about it" -- one row per
    defect mention, with the version it is attributed to, its source (own/peer),
    the comparison's target and opponent, the frozen check id, the defect class
    (`tier`), the severity rung, and the sheet's own evidence sentence as the
    verbal description. `counted`/`merged_into` keep the file consistent with
    the census under the OPT-IN `dedup_mode` "location". Rows are ordered by the
    version (field order), then severity (fatal first), then defect class in the
    scoring priority order.
    """
    r, agg = _issue_file_agg(ctx, r, agg)
    rows = defect_list_rows(ctx, r, agg)
    p = ctx.reports_dir / (name or f"round{r}_defects.csv")
    return write_csv_atomic(p, DEFECT_LIST_FIELDS, rows)

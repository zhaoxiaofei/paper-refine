# -*- coding: utf-8 -*-
# Part 11/20 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# ======================================================================================
# LLM defect audit (diagnostic): flag every round<N>_defects.csv row TP or FP and
# write the TP-only report family.  NEVER ranked: the champion selection always
# reads the NON-audited aggregation (see `select_champion`'s callers).
# ======================================================================================
# The panel's defect list is a set of CLAIMS about the packages.  Some are true
# defects (TP), some do not survive inspection (FP -- the quoted text is absent,
# the omission does not exist, the row is attributed to the wrong version, or the
# claim is otherwise unfounded).  The auditor below asks a lightweight LLM
# session to label every defect row; the labels then drive DIAGNOSTIC ONLY files:
#
#   reports/round<r>_auditedTP_defects.csv          the TP rows (+ audit columns)
#   reports/round<r>_auditedTP_issue_census.csv     census re-counted over the TP rows
#   reports/round<r>_auditedTP_issue_matrix.csv     the same matrix over those counts
#   reports/round<r>_auditedTP_issue_cumulative.csv its prefix sums
#   reports/round<r>_auditedTP_raw_scores.csv       the round's score rows (scores are
#                                                   not audited) under the audited name
#   reports/round<r>_auditedTP_dedup_audit.json     merges whose kept row is a TP
#   reports/round<r>_defect_audit.json              the audit's own record (verdicts)
#
# The audited aggregation is a COPY: `agg` itself is never mutated, `sel` never
# reads it, and the champion row/pin is selected from the non-audited agg only.
# An audit that cannot run (no backend) or returns nothing leaves the round
# exactly as it was, minus a warning.
PAPER_DEFECT_AUDIT_ENV = "PAPER_DEFECT_AUDIT_CMD"
DEFECT_AUDIT_LABELS = ("TP", "FP")
DEFECT_AUDIT_FIELDS = tuple(DEFECT_LIST_FIELDS) + ("audit_label", "audit_reason")


def _defect_audit_prompt(r: int, n_rows: int) -> str:
    return with_context_budget(F"""You are the pipeline's DEFECT AUDITOR for round {int(r)}.

The round's judge panel filed {int(n_rows)} defect rows. They are in
`defects.json` in this directory: one object per row of
`reports/round{int(r)}_defects.csv`, carrying
{{defect_id, version, check, tier, severity, side, target_version, peer_version,
session, judge_index, evidence}}.
`judge_opinions.json` carries the round's resolved directed comparisons (score,
basis, reason and the full resolved[]/introduced[] ledgers) if you need the
surrounding sheet context. `judge_runs.json` maps every judge session id to its
target and its v1..vN label map, so a `vN` in a ledger resolves to a real
version. The delivered corpora the judges saw live under `<root>/runs/<session
id>/` (target/, field/) if your environment can read them.

TASK
For EVERY defect_id in `defects.json`, decide whether the row is a TRUE POSITIVE
or a FALSE POSITIVE about the cited `version`:
  * TP -- the row's claim is supported: the quoted text/number exists where the
    row says it does, or the described difference (missing punctuation, an
    unexpanded acronym, a template-order deviation, a stale code-README
    instruction, a hyphenated page range, a missing figure-legend label, mixed
    terminology, an unqualified p-value, a missing caveat, a wrong numeric
    boundary, an understated availability statement, ...) is real.
  * FP -- the row is contradicted: the cited version contains the text the row
    says is missing, the claimed omission/defect does not exist, the row is
    attributed to the wrong version, or the claim is otherwise unfounded.
A style or architecture observation whose quoted text is really there is a TP
(the pipeline counts such rows as minor defects); it is not an FP merely because
you would not have raised it. Never invent evidence. If you cannot verify a row,
label it TP and say "unverified" in the reason -- a possibly real defect must not
be dropped silently.

Write `audit.json` in this directory with EXACTLY this schema (no extra text):
{{
  "verdicts": [
    {{"defect_id": "r{int(r)}-D0001", "label": "TP",
      "reason": "<<= 40 words: what you checked and why the label holds>"}}
  ]
}}
Every defect_id from `defects.json` must appear exactly once, with label "TP" or
"FP". Write only `audit.json`; do not modify any other file.
""")


def _normalize_defect_audit(data, valid_ids) -> dict:
    """{defect_id: (label, reason)} from the auditor's audit.json (junk dropped)."""
    out = {}
    rows = data.get("verdicts") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return out
    label_map = {
        "tp": "TP", "true_positive": "TP", "true positive": "TP", "true": "TP",
        "pass": "TP", "ok": "TP",
        "fp": "FP", "false_positive": "FP", "false positive": "FP", "false": "FP",
        "fail": "FP",
    }
    for item in rows:
        if not isinstance(item, dict):
            continue
        did = str(item.get("defect_id") or item.get("id") or "").strip()
        if did not in valid_ids or did in out:
            continue
        raw = item.get("label", item.get("verdict"))
        if isinstance(raw, bool):
            label = "TP" if raw else "FP"
        else:
            label = label_map.get(" ".join(str(raw or "").split()).lower())
        if label is None:
            continue
        reason = " ".join(str(item.get("reason") or item.get("basis") or "").split())[:400]
        out[did] = (label, reason)
    return out


def run_defect_audit_agent(ctx: Ctx, r: int, payload: dict, cmd: list,
                           timeout: int = None) -> tuple:
    """Run the LLM defect audit; returns ({defect_id: (label, reason)}, info).

    Mirrors `run_judge_conflict_agent`: the session is a small, self-contained
    sandbox next to the round's reports, its answer is schema-checked, and any
    failure is recorded in `info` (never raised into the round).
    """
    sb = ctx.reports_dir / F"defect_audit_round{int(r)}"
    sb.mkdir(parents=True, exist_ok=True)
    write_json_atomic(sb / "defects.json",
                      {k: v for k, v in payload.items() if k != "judge_runs"})
    write_json_atomic(sb / "judge_runs.json", payload.get("judge_runs") or {})
    # The sheets' own ledgers are context for the auditor; best effort only --
    # the audit's required input is defects.json.
    try:
        opinions = round_judge_opinions(ctx, int(r), field=payload.get("field"))
    except Exception:                                            # noqa: BLE001
        opinions = []
    write_json_atomic(sb / "judge_opinions.json",
                      {"run": payload.get("run"), "round": int(r),
                       "generated": utcnow(), "opinions": opinions})
    write_text_atomic(sb / "PROMPT.md",
                      _defect_audit_prompt(r, len(payload.get("defects") or [])))
    answer = sb / "audit.json"
    try:
        if answer.exists():
            answer.unlink()
    except OSError:
        pass
    rec = {"id": F"defect_audit_round{int(r)}", "kind": "defect_audit",
           "attempts_done": 0}
    seconds = max(60, min(int(timeout) if timeout else 1800, 3600))
    res = _execute_attempt_in(sb, rec, [str(x) for x in cmd], seconds,
                              prompt_name="PROMPT.md", log_name="_agent.log",
                              archive_marker=False)
    info = {"used": True, "command": [str(x) for x in cmd], "rc": res.get("rc"),
            "error": res.get("error"), "duration": round(float(res.get("dur") or 0.0), 1),
            "sandbox": str(sb)}
    data = read_json(answer, revive=False, lenient=True)
    if not isinstance(data, (dict, list)):
        info["error"] = info.get("error") or "the agent wrote no parseable audit.json"
        info["ok"] = False
        return {}, info
    valid = {str(x.get("defect_id")) for x in (payload.get("defects") or [])
             if isinstance(x, dict)}
    verdicts = _normalize_defect_audit(data, valid)
    info["verdicts"] = len(verdicts)
    info["ok"] = bool(verdicts)
    if not verdicts:
        info["error"] = info.get("error") or "the agent labelled no defect row"
    return verdicts, info


def default_defect_audit_cmd():
    """The lightweight default backend for the defect audit (None when unusable)."""
    cmd = _conflict_agent_cmd_from_env(PAPER_DEFECT_AUDIT_ENV)
    if cmd:
        return cmd if _conflict_cmd_usable(cmd) else None
    try:
        cmd = resolve_agent_cmd("codex-lite", None, use_env=False)
    except SystemExit:
        cmd = None
    if cmd and _conflict_cmd_usable(cmd):
        return cmd
    cmd = _conflict_agent_cmd_from_env("PAPER_AGENT_CMD")
    return cmd if (cmd and _conflict_cmd_usable(cmd)) else None


def resolve_defect_audit_cmd(args, judge_cmd, judge_manual: bool,
                             recorded: dict = None) -> tuple:
    """(cmd, source) for ONE round's LLM defect audit (None = skip).

    The audit is ON by default with a real agent backend, but never silently on a
    backend that cannot run it: an explicit --defect-audit[-cmd] wins, then
    PAPER_DEFECT_AUDIT_CMD, then -- when the judge backend IS an agent preset --
    the backend a previous round recorded, then the lightweight default
    (codex-lite, else PAPER_AGENT_CMD).  A manual judge wave and a custom/stub
    judge backend stay off unless the operator asks for the audit explicitly, and
    the recorded backend is DIAGNOSTIC: like the conflict audit's, it never turns
    the audit back on for a backend that must not run it.
    """
    if getattr(args, "no_defect_audit", False):
        return None, "disabled"
    explicit = getattr(args, "defect_audit_cmd", None)
    agent = getattr(args, "defect_audit", None)
    if explicit:
        try:
            return resolve_agent_cmd(agent or "codex-lite", explicit), "defect-audit-cmd"
        except SystemExit:
            print("[defect-audit] WARNING: --defect-audit-cmd could not be resolved; "
                  "skipping the LLM defect audit")
            return None, "unresolved"
    if agent == "manual":
        return None, "manual"
    if agent:
        try:
            return resolve_agent_cmd(agent, None, use_env=False), "defect-audit"
        except SystemExit:
            return None, "unresolved"
    env_cmd = _conflict_agent_cmd_from_env(PAPER_DEFECT_AUDIT_ENV)
    if env_cmd:
        if _conflict_cmd_usable(env_cmd):
            return env_cmd, "defect-audit-env"
        return None, "unusable-env"
    if judge_manual:
        return None, "manual"
    if not _looks_like_preset_cmd(judge_cmd):
        # A custom/stub judge backend is usually a test harness or a foreign CLI:
        # do not spawn a second protocol on it unless the operator opts in.
        return None, "custom-backend"
    recorded = recorded or {}
    recorded_cmd = recorded.get("cmd")
    if recorded.get("source") == "disabled":
        return None, "disabled"        # a previous --no-defect-audit stays off
    if recorded.get("source") == "manual":
        return None, "manual"
    if recorded.get("source") not in ("manual", "disabled", "unavailable") \
            and isinstance(recorded_cmd, list) and recorded_cmd:
        return [str(x) for x in recorded_cmd], "recorded"
    light = default_defect_audit_cmd()
    if light is not None:
        return light, "lightweight-default"
    return None, "unavailable"


def apply_defect_audit(rows: list, verdicts: dict) -> list:
    """The defect rows + `audit_label`/`audit_reason` (unlabelled rows stay None)."""
    out = []
    for row in rows or []:
        item = dict(row)
        label, reason = (verdicts or {}).get(str(row.get("defect_id")), (None, ""))
        item["audit_label"] = label
        item["audit_reason"] = reason
        out.append(item)
    return out


def census_from_filtered_rows(template: dict, rows: list) -> dict:
    """The census shape re-counted over a SUBSET of one round's defect rows.

    `template` is the non-audited `agg["issue_census"]`; its session and
    opportunity denominators are kept (the panel did not change), while every
    count is recomputed from `rows` with the SAME per-(session, version) key
    `build_issue_census` uses.  Rows marked `counted == "no"` (the opt-in
    location-dedup merges) stay excluded, exactly as in the original census.
    """
    counts, seen = {}, set()
    for row in rows or []:
        if str(row.get("counted") or "yes").strip().lower() == "no":
            continue
        vid = str(row.get("version"))
        tier, sev = str(row.get("tier")), str(row.get("severity"))
        if tier not in BASIS_TIERS or sev not in SEVERITIES:
            continue
        key = (str(row.get("session")), vid,
               _issue_row_key(tier, sev, row.get("evidence"), row.get("check")))
        if key in seen:
            continue
        seen.add(key)
        src = "own" if str(row.get("source")) == "own" else "peer"
        bucket = counts.setdefault((vid, tier, sev), {"own": 0, "peer": 0})
        bucket[src] += 1
    census = {}
    for vid, tpl in (template or {}).items():
        if not isinstance(tpl, dict):
            census[str(vid)] = tpl
            continue
        vid = str(vid)
        n_sessions = tpl.get("sessions_expected")
        sev_totals = {s: {"own": 0, "peer": 0, "total": 0, "raw_own": 0,
                          "raw_peer": 0, "merged_own": 0, "merged_peer": 0}
                      for s in SEVERITIES}
        tiers, own_total, peer_total = {}, 0, 0
        for tier in BASIS_TIERS:
            per_sev, t_own, t_peer = {}, 0, 0
            for sev in SEVERITIES:
                bucket = counts.get((vid, tier, sev)) or {"own": 0, "peer": 0}
                own, peer = int(bucket.get("own") or 0), int(bucket.get("peer") or 0)
                n_own_opps = int(tpl.get("own_opps") or 0)
                n_peer_opps = int(tpl.get("peer_opps") or 0)
                per_sev[sev] = {
                    "own": own, "peer": peer, "total": own + peer,
                    "raw_own": own, "raw_peer": peer,
                    "merged_own": 0, "merged_peer": 0,
                    "peer_rate": (round(peer / n_peer_opps, 6) if n_peer_opps else 0.0),
                    "own_rate": (round(own / n_own_opps, 6) if n_own_opps else 0.0),
                }
                sev_totals[sev]["own"] += own
                sev_totals[sev]["peer"] += peer
                sev_totals[sev]["raw_own"] += own
                sev_totals[sev]["raw_peer"] += peer
                sev_totals[sev]["total"] += own + peer
                t_own += own
                t_peer += peer
            for per_sev_row in per_sev.values():
                per_sev_row["per_session"] = (
                    round(per_sev_row["total"] / n_sessions, 4) if n_sessions else None)
            tier_total = t_own + t_peer
            tiers[tier] = {"own": t_own, "peer": t_peer, "total": tier_total,
                           "severities": per_sev,
                           "per_session": (round(tier_total / n_sessions, 4)
                                           if n_sessions else None)}
            own_total += t_own
            peer_total += t_peer
        total = own_total + peer_total
        rate = (round(total / n_sessions, 4) if n_sessions else None)
        census[vid] = dict(tpl, **{
            "tiers": tiers,
            "severities": {s: dict(v, per_session=(round(v["total"] / n_sessions, 4)
                                                   if n_sessions else None))
                           for s, v in sev_totals.items()},
            "own": own_total, "peer": peer_total, "total": total,
            "raw_own": own_total, "raw_peer": peer_total, "raw_total": total,
            "merged_own": 0, "merged_peer": 0, "merged": 0,
            "dedup_audit": [],
            "per_session": rate, "raw_per_session": rate})
    return census


def audited_defect_agg(ctx: Ctx, r: int, agg: dict, labelled: list) -> dict:
    """A COPY of `agg` whose defect list/census hold only the auditor's TP rows.

    The score rows, stats, field and every other key are shared with the original
    aggregation: scores are not audited, so the medians/means the table prints are
    the recorded ones.  This dict is used ONLY for the diagnostic files and the
    second member table -- never for `select_champion`/`pin_champion`.
    """
    rows = [{k: v for k, v in x.items() if k not in ("audit_label", "audit_reason")}
            for x in (labelled or []) if x.get("audit_label") == "TP"]
    out = dict(agg or {})
    out["issue_rows"] = rows
    out["issue_census"] = census_from_filtered_rows(
        (agg or {}).get("issue_census") or {}, rows)
    return out


def audited_table_sel(sel: dict) -> dict:
    """`sel` with its DEFECT-derived ranking fields stripped.

    The audited member table must show `defects@K` and the severity totals of the
    TP-only census, but `round_member_table_rows` prefers the ranking row's own
    `issues`/`defect_prefix_total` (the NON-audited numbers `select_champion`
    wrote).  This copy keeps the champion, the tie-break cell count and the
    writing/hand-off metadata while removing exactly those two defect fields, so
    the table re-reads them from the audited aggregation; the score columns and
    the champion note are untouched.
    """
    out = dict(sel or {})
    out["ranking"] = [{k: v for k, v in row.items()
                       if k not in ("issues", "defect_prefix_total")}
                      if isinstance(row, dict) else row
                      for row in (sel or {}).get("ranking") or []]
    return out


def write_round_audited_defects(ctx: Ctx, r: int, labelled: list,
                                name: str = None) -> Path:
    """`reports/round<r>_auditedTP_defects.csv`: the TP rows + audit columns."""
    rows = []
    for item in labelled or []:
        if item.get("audit_label") != "TP":
            continue
        row = {k: item.get(k) for k in DEFECT_LIST_FIELDS}
        row["defect_id"] = item.get("defect_id")
        row["audit_label"] = item.get("audit_label")
        row["audit_reason"] = item.get("audit_reason")
        rows.append(row)
    p = ctx.reports_dir / (name or f"round{r}_auditedTP_defects.csv")
    return write_csv_atomic(p, DEFECT_AUDIT_FIELDS, rows)


def _audited_dedup_payload(ctx: Ctx, r: int, agg: dict, labelled: list) -> dict:
    """The dedup merges whose KEPT row survived the audit as a TP."""
    base = dedup_audit_payload(ctx, r, agg)
    kept = {}
    for item in labelled or []:
        if item.get("audit_label") != "TP":
            continue
        if str(item.get("counted") or "yes").strip().lower() == "no":
            continue
        vid = str(item.get("version"))
        # The merge records store the KEPT excerpt through the location
        # tokenizer (`line 42: quote` -> `line 42 quote`), so this side must be
        # normalized the same way or the `line N: <quote>` form never matches.
        excerpt = " ".join(dedup_location_of(item.get("evidence"))[1])[:200]
        kept.setdefault((vid, str(item.get("session"))), []).append(excerpt)
    merges = []
    for m in base.get("merges") or []:
        key = (str(m.get("version")), str(m.get("kept_session")))
        needle = " ".join(str(m.get("kept_excerpt") or "").split())[:200].lower()
        for excerpt in kept.get(key, []):
            if excerpt[:120] and (excerpt.startswith(needle[:120])
                                  or needle[:120].startswith(excerpt[:120])):
                merges.append(m)
                break
    out = dict(base)
    out["audited"] = True
    out["merged_rows"] = len(merges)
    out["merges"] = merges
    return out


def write_defect_audit_reports(ctx: Ctx, r: int, agg: dict, labelled: list,
                               audited: dict = None) -> list:
    """Write the whole TP-only report family; returns the paths written."""
    audited = audited if audited is not None else audited_defect_agg(ctx, r, agg, labelled)
    out = [
        write_round_audited_defects(ctx, r, labelled),
        write_round_issue_census(ctx, r, audited,
                                 name=f"round{int(r)}_auditedTP_issue_census.csv"),
        write_round_issue_matrix(ctx, r, audited,
                                 name=f"round{int(r)}_auditedTP_issue_matrix.csv"),
        write_round_issue_cumulative(ctx, r, audited,
                                     name=f"round{int(r)}_auditedTP_issue_cumulative.csv"),
        write_round_raw_scores(ctx, r, audited,
                               name=f"round{int(r)}_auditedTP_raw_scores.csv"),
    ]
    p = ctx.reports_dir / f"round{int(r)}_auditedTP_dedup_audit.json"
    write_json_atomic(p, _audited_dedup_payload(ctx, r, agg, labelled))
    out.append(p)
    return out


def write_round_defect_audit(ctx: Ctx, r: int, agg: dict = None,
                             agent_cmd: list = None, timeout: int = None,
                             force: bool = False, use_agent: bool = True) -> dict:
    """Audit one round's defect list and write the TP-only diagnostic family.

    Idempotent: a stored audit with the same input fingerprint is reused (the
    `run` audit is not paid for twice by a later `decide`).  The audit is
    diagnostic -- it never changes `agg`, `sel`, a pin or a champion.
    """
    r = int(r)
    if agg is None:
        field = [str(v) for v in (ctx.round_rec(r).get("field") or [])]
        agg = aggregate_round(ctx, r, field) if field else {"issue_rows": [], "field": []}
    rows = defect_list_rows(ctx, r, agg)
    if not rows:
        return {"used": False, "reason": "no defect rows to audit", "rows": 0}
    fingerprint = hashlib.sha256(
        json.dumps(_json_safe(rows), sort_keys=True, ensure_ascii=False)
        .encode("utf-8")).hexdigest()[:16]
    # An explicit disable (--no-defect-audit / agent_cmd None) wins over a stored
    # audit: the operator asked for no audit in THIS invocation.
    if not use_agent or agent_cmd is None:
        return {"used": False, "reason": "the LLM defect audit is off", "rows": len(rows)}
    meta_path = ctx.reports_dir / f"round{int(r)}_defect_audit.json"
    existing = read_json(meta_path, revive=False, lenient=True)
    if isinstance(existing, dict) and not force \
            and existing.get("input_fingerprint") == fingerprint \
            and existing.get("ok"):
        verdicts = {}
        for v in existing.get("verdicts") or []:
            if not isinstance(v, dict) or not v.get("defect_id"):
                continue
            label = str(v.get("label") or "").strip().upper()
            if label not in DEFECT_AUDIT_LABELS:
                continue            # a label-less stored row stays UNLABELLED: it is
                # never silently promoted to TP (the writer only stores labelled
                # rows, so this is the hand-edited/stale-metadata path).
            verdicts[str(v["defect_id"])] = (label, str(v.get("reason") or ""))
        labelled = apply_defect_audit(rows, verdicts)
        audited = audited_defect_agg(ctx, r, agg, labelled)
        # Self-healing reuse: rewrite the (deterministic) TP-only family from the
        # stored verdicts, so a deleted/partial audited file is restored without
        # paying for another LLM session.
        files = write_defect_audit_reports(ctx, r, agg, labelled, audited=audited)
        return {"used": True, "reused": True, "ok": True, "rows": len(rows),
                "tp": sum(1 for x in labelled if x["audit_label"] == "TP"),
                "fp": sum(1 for x in labelled if x["audit_label"] == "FP"),
                "incomplete": sum(1 for x in labelled if not x["audit_label"]),
                "labelled": labelled, "audited": audited,
                "agent": existing.get("agent") or {},
                "files": [str(x) for x in files]}
    judge_runs = {}
    for rec in ctx.runs(kind="judge", round_no=r):
        judge_runs[str(rec.get("id"))] = {
            "judge_index": rec.get("judge_index"),
            "target": rec.get("target_id"),
            "label_map": rec.get("label_map") or {},
            "sandbox": rec.get("sandbox"),
        }
    payload = {"run": ctx.root.name, "round": r, "generated": utcnow(),
               "field": [str(v) for v in (agg.get("field") or [])],
               "defects": [_json_safe(x) for x in rows],
               "judge_runs": _json_safe(judge_runs)}
    verdicts, info = run_defect_audit_agent(ctx, r, payload, agent_cmd, timeout=timeout)
    labelled = apply_defect_audit(rows, verdicts)
    tp = [x for x in labelled if x["audit_label"] == "TP"]
    fp = [x for x in labelled if x["audit_label"] == "FP"]
    incomplete = [x for x in labelled if not x["audit_label"]]
    if not verdicts:
        return {"used": True, "ok": False, "rows": len(rows), "tp": 0, "fp": 0,
                "incomplete": len(rows), "labelled": labelled, "agent": info,
                "reason": info.get("error") or "the audit returned no verdict"}
    audited = audited_defect_agg(ctx, r, agg, labelled)
    files = write_defect_audit_reports(ctx, r, agg, labelled, audited=audited)
    meta = {"run": ctx.root.name, "round": r, "generated": utcnow(),
            "input_fingerprint": fingerprint, "ok": True,
            "rows": len(rows), "tp": len(tp), "fp": len(fp),
            "incomplete": len(incomplete),
            "agent": info, "files": [str(x) for x in files],
            "verdicts": [{"defect_id": x["defect_id"], "label": x["audit_label"],
                          "reason": x["audit_reason"]}
                         for x in labelled if x["audit_label"]]}
    write_json_atomic(meta_path, meta)
    return {"used": True, "reused": False, "ok": True, "rows": len(rows),
            "tp": len(tp), "fp": len(fp), "incomplete": len(incomplete),
            "labelled": labelled, "audited": audited, "agent": info,
            "files": [str(x) for x in files] + [str(meta_path)]}

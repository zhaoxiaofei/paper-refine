# -*- coding: utf-8 -*-
# Part 12/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# ======================================================================================
# Cross-judge conflict audit: surface contradictions between independent judges
# ======================================================================================
# The judge panel is deliberately independent: two sessions per version, and the
# same comparison is judged in BOTH directions by different sessions.  That is
# what makes the panel robust, but it also means two sessions can CONTRADICT each
# other about a hard fact: one files a claim as `resolved` while its partner files
# the same claim as `introduced`; one quotes 173-1,307 from a source table while
# the other quotes 508-1,307; or the two directions of one comparison disagree in
# sign.  The aggregation keeps both judgments on purpose (it must not invent an
# adjudication in code), so the disagreement is surfaced as a REQUIRED MANUAL
# CHECK in:
#
#   reports/round<r>_judge_conflicts.json   machine-readable conflicts
#   reports/round<r>_judge_conflicts.md     per-round manual TODO list
#   reports/JUDGE_CONFLICTS_TODO.md         cumulative TODO list over rounds
#
# The mechanical pass below is deterministic and always runs.  When an agent
# backend is available (`--conflict-agent-cmd`, `--agent-cmd`, PAPER_AGENT_CMD,
# or the run/run-decide `--agent`), an optional LLM pass reads the same opinions
# plus the mechanical candidates and can add semantic conflicts the token rules
# miss; its answer is schema-checked and merged, never trusted blindly.  The
# audit never blocks a decision by itself -- it says which items a HUMAN must
# verify before the panel's numbers are cited.
JUDGE_CONFLICT_KINDS = ("score_disagreement", "direction_conflict", "claim_inversion",
                        "numeric_contradiction", "check_disposition", "other")
JUDGE_CONFLICT_SEVERITIES = ("blocker", "major", "minor")
_JUDGE_CONFLICT_SEV_RANK = {"blocker": 0, "major": 1, "minor": 2}
_JUDGE_CONFLICT_STOPWORDS = {
    "the", "and", "that", "with", "from", "this", "than", "then", "into", "onto",
    "for", "was", "were", "are", "its", "their", "they", "them", "has", "have",
    "had", "not", "but", "one", "two", "both", "same", "also", "only", "more",
    "less", "over", "under", "about", "target", "opponent", "version", "state",
    "states", "stated", "says", "shows", "show", "which", "where", "while",
    "when", "does", "did", "per", "vs", "any", "all",
}
_JUDGE_CONFLICT_TOKEN_RE = re.compile(r"[a-z][a-z0-9_.\-/]{2,}")
_JUDGE_CONFLICT_NUMBER_RE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)")


def _conflict_numbers(text, floor: float = 10.0) -> set:
    """Quantitative numbers in a claim/message; ids and panel letters are skipped.

    The floor drops the small integers that come from check ids and figure
    letters ("M4", "Fig. 3d"), while keeping cell counts, read lengths and
    percentages (36, 50, 152, 170, 508, 1,307, ...).
    """
    out = set()
    for m in _JUDGE_CONFLICT_NUMBER_RE.finditer(str(text or "")):
        tok = m.group(1).rstrip(",").replace(",", "")
        try:
            v = float(tok)
        except ValueError:
            continue
        if v >= float(floor):
            out.add(v if v != int(v) else int(v))
    return out


def _conflict_tokens(text) -> set:
    toks = {t for t in _JUDGE_CONFLICT_TOKEN_RE.findall(str(text or "").lower())
            if t not in _JUDGE_CONFLICT_STOPWORDS}
    toks |= {F"#{v}" for v in _conflict_numbers(text)}
    return toks


def _conflict_similarity(a, b) -> float:
    ta, tb = _conflict_tokens(a), _conflict_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def _conflict_item_text(item) -> str:
    if not isinstance(item, dict):
        return ""
    return " ".join(str(item.get("evidence") or "").split())


def _conflict_item_cell(item) -> str:
    if not isinstance(item, dict):
        return "?"
    return (F"{item.get('check') or '?'} "
            F"{item.get('tier') or '?'}/{item.get('severity') or '?'}")


def _conflict_item_severity(item) -> int:
    return {"minor": 1, "major": 2, "critical": 3, "fatal": 4}.get(
        str((item or {}).get("severity") or "").lower(), 0)


def _conflict_items_similar(a, b) -> bool:
    """True when two ledger items are about the same claim (not just same words)."""
    ta, tb = _conflict_tokens(_conflict_item_text(a)), _conflict_tokens(_conflict_item_text(b))
    if not ta or not tb:
        return False
    inter = ta & tb
    sim = len(inter) / float(len(ta | tb))
    shared_numbers = _conflict_numbers(_conflict_item_text(a)) & \
        _conflict_numbers(_conflict_item_text(b))
    if sim >= 0.30:
        return True
    # A claim quoted with the same distinctive numbers and several shared terms
    # is the same claim even when the two judges phrase it differently.
    return len(inter) >= 4 and len(shared_numbers) >= 2


_JUDGE_CONFLICT_MANUAL = {
    "score_disagreement": (
        "Open each cited judge sheet (runs/<id>/scores.json) and the sources its "
        "ledger rows point at; decide which integer the evidence supports. If a "
        "sheet is wrong, fix the underlying text/data and `retry --run <ID>` so the "
        "panel is re-judged; if both readings are defensible, record the resolution "
        "in the round's manual notes before citing the panel's numbers."),
    "direction_conflict": (
        "The two directions of the same comparison disagree after negating one "
        "side. Re-read both sheets' ledgers and the pristine original; verify that "
        "the comparison was scored in the same frame (target vs opponent) and that "
        "no ledger row was filed on the wrong side. Re-judge the sheet whose frame "
        "is wrong (`retry --run <ID>`)."),
    "claim_inversion": (
        "One judge says the target FIXED this claim while another says the target "
        "INTRODUCED it. Open both packages at the cited location and the cited "
        "source artifact, decide which side the text/data support, then re-judge "
        "the losing session after correcting the claim."),
    "numeric_contradiction": (
        "The same claim is quoted with different numbers in two judge sessions. "
        "Recompute the value from the cited producer table/column (file, column, "
        "filter); treat any range that cannot be reproduced as unverified, then "
        "re-judge the sheet that cites it (`retry --run <ID>`)."),
    "check_disposition": (
        "One session marks this check clean while another reports findings (or "
        "could not judge it). Inspect the check's own artifact in both sheets, "
        "decide whether the check was actually run, and re-judge the session whose "
        "disposition is unsupported."),
    "other": ("Two judge sessions disagree; inspect the cited sheets and the source "
              "artifacts, resolve which statement the evidence supports, and re-judge "
              "the unsupported sheet (`retry --run <ID>`)."),
}


def detect_round_judge_conflicts(opinions: list) -> list:
    """Mechanical cross-judge conflicts from one round's opinions (pure).

    `opinions` is the list returned by round_judge_opinions(): one dict per
    resolved directed comparison (judge run, target, opponent, score, ledger
    items, checks).  Returns conflicts in the manual-TODO schema.
    """
    conflicts = []
    by_pair = {}
    for op in opinions or []:
        if not isinstance(op, dict):
            continue
        target, opponent = op.get("target"), op.get("opponent")
        if not target or not opponent:
            continue
        by_pair.setdefault((str(target), str(opponent)), []).append(op)

    def _subject(text) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()[:80]

    def add(kind, member, opponent, judges, severity, summary, evidence,
            manual=None, subject=""):
        conflicts.append({
            "kind": kind,
            "severity": severity if severity in JUDGE_CONFLICT_SEVERITIES else "major",
            "member": str(member),
            "opponent": str(opponent),
            "judges": sorted({str(j) for j in judges if j}),
            "subject": str(subject or ""),
            "summary": " ".join(str(summary or "").split())[:400],
            "evidence": evidence or [],
            "manual_check": " ".join(
                str(manual or _JUDGE_CONFLICT_MANUAL.get(kind, _JUDGE_CONFLICT_MANUAL["other"]))
                .split())[:800],
            "origin": "mechanical",
        })

    def score_evidence(ops):
        return [{"judge_run": str(o.get("judge_run") or ""), "side": "score",
                 "text": (F"{int(o['score']):+d} (basis {o.get('basis') or '?'}): "
                          F"{' '.join(str(o.get('reason') or '').split())[:180]}")}
                for o in ops if is_int(o.get("score"))]

    # 1. Same directed comparison, different integers from independent sessions.
    for (member, opponent), ops in sorted(by_pair.items()):
        runs = sorted({str(o.get("judge_run")) for o in ops if o.get("judge_run")})
        scores = [int(o["score"]) for o in ops if is_int(o.get("score"))]
        if len(runs) < 2 or len(scores) < 2 or len(set(scores)) < 2:
            continue
        diff = max(scores) - min(scores)
        has_neg, has_pos = any(s < 0 for s in scores), any(s > 0 for s in scores)
        severity = "blocker" if (has_neg and has_pos) else ("major" if diff >= 2 else "minor")
        add("score_disagreement", member, opponent, runs, severity,
            F"independent judges scored {member} vs {opponent} differently: "
            + ", ".join(F"{o.get('judge_run')}={int(o['score']):+d}"
                        for o in ops if is_int(o.get("score"))),
            score_evidence(ops))

    # 2. Same claim treated as resolved by one judge and introduced by another.
    for (member, opponent), ops in sorted(by_pair.items()):
        for i, a in enumerate(ops):
            for b in ops:
                if b is a or a.get("judge_run") == b.get("judge_run"):
                    continue
                for ri in a.get("resolved") or []:
                    for ij in b.get("introduced") or []:
                        if not _conflict_items_similar(ri, ij):
                            continue
                        tier = str(ri.get("tier") or ij.get("tier") or "").lower()
                        hi = max(_conflict_item_severity(ri), _conflict_item_severity(ij))
                        severity = ("blocker" if tier == "correctness" and hi >= 2
                                    else "major" if hi >= 2 else "minor")
                        add("claim_inversion", member, opponent,
                            [a.get("judge_run"), b.get("judge_run")], severity,
                            (F"{a.get('judge_run')} files the claim as RESOLVED for "
                             F"{member} while {b.get('judge_run')} files it as INTRODUCED: "
                             F"{_conflict_item_text(ri)[:140]}"),
                            [{"judge_run": str(a.get("judge_run") or ""), "side": "resolved",
                              "text": F"{_conflict_item_cell(ri)}: "
                                      F"{_conflict_item_text(ri)[:220]}"},
                             {"judge_run": str(b.get("judge_run") or ""), "side": "introduced",
                              "text": F"{_conflict_item_cell(ij)}: "
                                      F"{_conflict_item_text(ij)[:220]}"}],
                            subject="claim:" + _subject(_conflict_item_text(ri)))

    # 3. Same claim quoted with different numbers (e.g. 173-1,307 vs 508-1,307).
    for (member, opponent), ops in sorted(by_pair.items()):
        for i, a in enumerate(ops):
            for b in ops[i + 1:]:
                if a.get("judge_run") == b.get("judge_run"):
                    continue
                texts_a = [_conflict_item_text(x) for x in
                           (a.get("resolved") or []) + (a.get("introduced") or [])]
                texts_b = [_conflict_item_text(x) for x in
                           (b.get("resolved") or []) + (b.get("introduced") or [])]
                texts_a.append(str(a.get("reason") or ""))
                texts_b.append(str(b.get("reason") or ""))
                candidates = []
                for ta in texts_a:
                    for tb in texts_b:
                        sim = _conflict_similarity(ta, tb)
                        if sim >= 0.25:
                            candidates.append((sim, ta, tb))
                candidates.sort(reverse=True, key=lambda x: x[0])
                chosen = None
                for sim, ta, tb in candidates:
                    nums_a, nums_b = _conflict_numbers(ta), _conflict_numbers(tb)
                    if not (nums_a and nums_b) or nums_a == nums_b:
                        continue
                    # One side citing MORE numbers is detail, not contradiction;
                    # only an exclusive number on BOTH sides is a real conflict.
                    if nums_a <= nums_b or nums_b <= nums_a:
                        continue
                    if not (nums_a & nums_b) and len(nums_a) < 2 and len(nums_b) < 2:
                        continue
                    chosen = (sim, ta, tb, nums_a, nums_b)
                    break
                if chosen is None:
                    continue
                sim, ta, tb, nums_a, nums_b = chosen
                severity = "major" if (len(nums_a) >= 2 and len(nums_b) >= 2) else "minor"
                add("numeric_contradiction", member, opponent,
                    [a.get("judge_run"), b.get("judge_run")], severity,
                    (F"the same claim is quoted with different numbers by "
                     F"{a.get('judge_run')} and {b.get('judge_run')}: "
                     F"{sorted(nums_a)} vs {sorted(nums_b)}"),
                    [{"judge_run": str(a.get("judge_run") or ""), "side": "evidence",
                      "text": ta[:220]},
                     {"judge_run": str(b.get("judge_run") or ""), "side": "evidence",
                      "text": tb[:220]}],
                    subject="numbers:" + "+".join(str(x) for x in sorted(nums_a | nums_b)))

    # 4. The same comparison judged in both directions, with a sign/gap conflict
    #    after negating one side into the other's frame.
    pair_names = sorted({tuple(sorted((m, o))) for (m, o) in by_pair})
    for a, b in pair_names:
        ops_ab, ops_ba = by_pair.get((a, b), []), by_pair.get((b, a), [])
        scores_ab = [int(o["score"]) for o in ops_ab if is_int(o.get("score"))]
        scores_ba = [-int(o["score"]) for o in ops_ba if is_int(o.get("score"))]
        if not scores_ab or not scores_ba:
            continue
        med_ab = float(statistics.median(scores_ab))
        med_ba = float(statistics.median(scores_ba))
        sign_conflict = (med_ab > 0 > med_ba) or (med_ba > 0 > med_ab)
        if not sign_conflict and abs(med_ab - med_ba) < 2:
            continue
        if sign_conflict:
            severity = "major" if min(abs(med_ab), abs(med_ba)) >= 2 else "minor"
        else:
            severity = "major"
        add("direction_conflict", a, b,
            [o.get("judge_run") for o in ops_ab + ops_ba], severity,
            (F"the two directions of {a} vs {b} disagree: {a}-vs-{b} median "
             F"{med_ab:+.1f} vs the negated {b}-vs-{a} median {med_ba:+.1f}"),
            score_evidence(ops_ab + ops_ba))

    # 5. Same comparison, one judge marks a check clean and another files findings
    #    (or could not judge it).
    for (member, opponent), ops in sorted(by_pair.items()):
        runs = sorted({str(o.get("judge_run")) for o in ops if o.get("judge_run")})
        if len(runs) < 2:
            continue
        check_ids = set()
        for o in ops:
            check_ids.update((o.get("checks") or {}).keys())
        conflicting, evidence = [], []
        for cid in sorted(check_ids):
            disp = {}
            for o in ops:
                raw = (o.get("checks") or {}).get(cid)
                if raw is None:
                    continue
                # An agent-authored cell can be empty/whitespace ("" is a legal
                # JSON value in scores.json): splitting it would raise
                # IndexError and the callers' generic handler then skips the
                # WHOLE round's conflicts audit. Degrade per-check, not
                # per-round: the empty disposition simply disagrees with
                # nothing.
                words = str(raw).strip().split()
                disp[str(o.get("judge_run"))] = (words[0] if words else "").lower()
            vals = set(disp.values())
            if "clean" in vals and (vals & {"findings", "unable"}):
                conflicting.append((cid, vals))
                evidence.extend({"judge_run": j, "side": "checks", "text": F"{cid}: {v}"}
                                for j, v in sorted(disp.items()))
        if conflicting:
            add("check_disposition", member, opponent, runs, "minor",
                " / ".join(F"{cid} is clean in one judge's sheet but "
                           + "/".join(sorted(v for v in vals if v != "clean"))
                           + " in another's" for cid, vals in conflicting),
                evidence)
    return conflicts


def _merge_judge_conflicts(mechanical: list, llm: list) -> list:
    """Merge the LLM answer into the mechanical list, one row per real conflict."""
    def base_of(c) -> tuple:
        return (c.get("kind"), str(c.get("member")), str(c.get("opponent")),
                tuple(sorted(set(c.get("judges") or []))))

    def merge_into(old, c):
        if len(str(c.get("summary") or "")) > len(str(old.get("summary") or "")):
            old["summary"] = c["summary"]
        if len(str(c.get("manual_check") or "")) > len(str(old.get("manual_check") or "")):
            old["manual_check"] = c["manual_check"]
        if c.get("subject") and not old.get("subject"):
            old["subject"] = c["subject"]
        seen = {(e.get("judge_run"), e.get("side"), e.get("text"))
                for e in old.get("evidence") or []}
        for e in c.get("evidence") or []:
            k = (e.get("judge_run"), e.get("side"), e.get("text"))
            if k not in seen:
                old.setdefault("evidence", []).append(e)
                seen.add(k)
        if _JUDGE_CONFLICT_SEV_RANK.get(c.get("severity"), 9) < \
                _JUDGE_CONFLICT_SEV_RANK.get(old.get("severity"), 9):
            old["severity"] = c["severity"]

    merged, index = [], {}
    for c in list(mechanical or []) + list(llm or []):
        if not isinstance(c, dict):
            continue
        base = base_of(c)
        subject = str(c.get("subject") or "")
        key = base + (subject,)
        if key in index:
            merge_into(merged[index[key]], c)
            continue
        # An LLM row attaches only to the UNIQUE same-base conflict. A
        # subjectless row among two mechanical subjects used to merge into the
        # first one, overwriting its summary/severity and leaving the other
        # untouched; refusing is a visible extra row, merging is silent harm.
        candidates = [i for i, x in enumerate(merged)
                      if base_of(x) == base and (not x.get("subject") or not subject)]
        if len(candidates) == 1:
            merge_into(merged[candidates[0]], c)
            continue
        index[key] = len(merged)
        merged.append(dict(c))
    merged.sort(key=lambda c: (_JUDGE_CONFLICT_SEV_RANK.get(c.get("severity"), 9),
                               str(c.get("kind")), str(c.get("member")),
                               str(c.get("opponent"))))
    return merged


def _judge_conflict_counts(conflicts: list) -> dict:
    counts = {sev: 0 for sev in JUDGE_CONFLICT_SEVERITIES}
    for c in conflicts or []:
        sev = str(c.get("severity") or "major")
        counts[sev] = counts.get(sev, 0) + 1
    counts["total"] = sum(counts.get(s, 0) for s in JUDGE_CONFLICT_SEVERITIES)
    return counts


def round_judge_opinions(ctx: Ctx, r: int, field=None) -> list:
    """Every resolved directed comparison of one round's (newest) judge sheets.

    Mirrors aggregate_round's sheet selection: the newest valid sheet per
    (target, judge index), opponents resolved through the run's label_map.  The
    returned dicts carry the raw ledger items and `checks` dispositions, which
    the aggregated score rows drop.

    `field` is the round's field the CALLER aggregated (aggregate_round's list)
    and must be passed whenever the round record may not carry one yet: a
    `run`'s conflict audit executes BEFORE finalize_round() writes `field` into
    the round record, so reading the record alone made the audit treat every
    comparison as out-of-field and certify an empty panel as "0 conflicts"
    (2026-10-06, neohetero-04to05-1006-0354-47c5306 round 1: 16 sheets and 112
    comparisons -> 0 opinions).  `None` falls back to the record's own field.
    """
    r = int(r)
    rrec = ctx.round_rec(r)
    if field is None:
        field = rrec.get("field")
    field_ids = {str(v) for v in (field or [])}
    # Mirror aggregate_round's panel: a round with a judge-session selection
    # (--only r1_judge_w2_j1) judges only those sessions, and a judge index
    # outside the configured 1..judges range is a stale sheet, not a conflict.
    judges = int(round_judges(ctx, r))
    selection = judge_selection(ctx, r)
    sheets = []
    for rec in ctx.runs(kind="judge", round_no=r):
        if rec.get("status") != "done":
            continue
        j = rec.get("judge_index")
        if not is_int(j) or not (1 <= int(j) <= judges):
            continue
        if selection and (str(rec.get("target_id") or ""), int(j)) not in selection:
            continue
        sheets.append(rec)
    newest = {}
    for rec in sorted(sheets, key=lambda x: (str(x.get("finished") or x.get("created") or ""),
                                             str(x.get("id")))):
        newest[(rec.get("target_id"), rec.get("judge_index"))] = rec
    opinions = []
    for _slot, rec in sorted(newest.items(),
                             key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        target = str(rec.get("target_id"))
        if target not in field_ids:
            continue
        sj = rec.get("scores")
        if not isinstance(sj, dict):
            continue
        lm = rec.get("label_map") or {}
        for comp in sj.get("comparisons") or []:
            if not isinstance(comp, dict):
                continue
            label = comp.get("opponent_label")
            score = comp.get("score")
            opp = lm.get(_norm_opponent_label(label))
            if opp is None or str(opp) not in field_ids or opp == target or not is_int(score):
                continue
            if not (SCORE_MIN <= score <= SCORE_MAX):
                continue
            opinions.append({
                "judge_run": str(rec.get("id") or ""),
                "judge_index": int(rec.get("judge_index")),
                "target": target,
                "opponent": str(opp),
                "opponent_label": label,
                "score": int(score),
                "basis": comp.get("basis"),
                "reason": str(comp.get("reason") or ""),
                "resolved": [it for it in (comp.get("resolved") or [])
                             if isinstance(it, dict)],
                "introduced": [it for it in (comp.get("introduced") or [])
                               if isinstance(it, dict)],
                "checks": comp.get("checks") if isinstance(comp.get("checks"), dict) else {},
            })
    return opinions


def _normalize_llm_conflicts(data) -> list:
    """Schema-check the LLM's conflicts.json (bad rows are dropped, never trusted)."""
    out = []
    if not isinstance(data, dict):
        return out
    for c in data.get("conflicts") or []:
        if not isinstance(c, dict):
            continue
        kind = str(c.get("kind") or "other").strip().lower()
        if kind not in JUDGE_CONFLICT_KINDS:
            kind = "other"
        severity = str(c.get("severity") or "major").strip().lower()
        if severity not in JUDGE_CONFLICT_SEVERITIES:
            severity = "major"
        member = str(c.get("member") or c.get("target") or "").strip()
        opponent = str(c.get("opponent") or "").strip()
        summary = " ".join(str(c.get("summary") or "").split())[:400]
        manual = " ".join(str(c.get("manual_check") or "").split())[:800]
        evidence = []
        for q in c.get("quotes") or []:
            if isinstance(q, dict):
                evidence.append({
                    "judge_run": str(q.get("judge_run") or q.get("judge") or ""),
                    "side": str(q.get("side") or "evidence"),
                    "text": " ".join(str(q.get("text") or q.get("evidence") or "").split())[:300]})
            elif isinstance(q, str):
                evidence.append({"judge_run": "", "side": "evidence",
                                 "text": " ".join(q.split())[:300]})
        if not summary and not evidence:
            continue
        if not manual:
            manual = _JUDGE_CONFLICT_MANUAL.get(kind, _JUDGE_CONFLICT_MANUAL["other"])
        out.append({
            "kind": kind, "severity": severity, "member": member, "opponent": opponent,
            "judges": [str(j) for j in (c.get("judge_runs") or c.get("judges") or []) if j],
            "subject": str(c.get("subject") or ""),
            "summary": summary, "evidence": evidence, "manual_check": manual,
            "origin": "llm",
        })
    return out


def _judge_conflict_agent_prompt(r: int) -> str:
    return with_context_budget(F"""You are the pipeline's cross-judge CONFLICT AUDITOR for round {int(r)}.

The pipeline has just collected the round's independent judge sessions. Two judges
can legitimately differ by a point, but they can also CONTRADICT each other about a
hard fact: the same comparison scored with opposite signs; the same claim filed as
`resolved` by one session and `introduced` by another; different numbers quoted for
the same source table/sentence; or one session marking a check `clean` while another
files findings for it.

Inputs in this directory:
  * judge_opinions.json       every resolved directed comparison of the round:
                              judge_run, judge_index, target, opponent, score, basis,
                              reason, resolved[]/introduced[] ledger items and checks{{}}.
                              Ledger items carry {{check, tier, severity, evidence}}.
  * candidate_conflicts.json  the mechanical pass's candidate conflicts (same schema
                              as the output). Treat them as candidates, not truth.

TASK
1. Verify each candidate against judge_opinions.json.
2. Find any ADDITIONAL genuine conflict the mechanical rules miss (e.g. two judges
   citing different producer files for the same claim, one treating a change as an
   improvement and the other as a regression, or evidence that cannot both be true).
3. Do NOT report benign wording differences, a one-point difference with the same
   sign, or a difference that the two ledgers themselves explain. If there is no
   genuine conflict, return an empty list.
4. Never invent evidence: quote only the judge sheets' own text and name the judge
   run ids exactly as they appear in judge_opinions.json.

Write `conflicts.json` in this directory with EXACTLY this schema (no extra text):
{{
  "conflicts": [
    {{
      "kind": "score_disagreement|direction_conflict|claim_inversion|numeric_contradiction|check_disposition|other",
      "severity": "blocker|major|minor",
      "member": "<version id the conflict is about>",
      "opponent": "<other version id>",
      "judge_runs": ["<run id>", "..."],
      "summary": "<<= 40 words: what the two judges say that cannot both be true>",
      "quotes": [
        {{"judge_run": "<run id>", "side": "score|resolved|introduced|checks|evidence",
          "text": "<<= 40 words of the sheet's own text>"}}
      ],
      "manual_check": "<<= 50 words: exactly what a human must verify, and where>"
    }}
  ]
}}

`severity` is `blocker` when a correctness- or preservation-level disagreement
flips a comparison, `major` for a factual conflict that changes a reported value,
and `minor` for a same-sign or bookkeeping conflict. Write only `conflicts.json`;
do not modify any other file.
""")


def run_judge_conflict_agent(ctx: Ctx, r: int, payload: dict, cmd: list,
                             timeout: int = None) -> tuple:
    """Run the optional LLM conflict audit; returns (conflicts, info).

    The session is a small, self-contained sandbox next to the round's reports.
    Its answer is only accepted when it parses and follows the schema; any other
    outcome is recorded in `info` and the mechanical conflicts remain the answer.
    """
    # NB: NOT "judge_conflict_*" -- instrumentation/tests classify sandboxes by
    # name and a "judge_" prefix would read as a judge session.  The audit is a
    # separate, lightweight session.
    sb = ctx.reports_dir / F"conflict_check_round{int(r)}"
    sb.mkdir(parents=True, exist_ok=True)
    write_json_atomic(sb / "judge_opinions.json", payload)
    write_json_atomic(sb / "candidate_conflicts.json",
                      {"conflicts": payload.get("candidate_conflicts") or []})
    write_text_atomic(sb / "PROMPT.md", _judge_conflict_agent_prompt(r))
    answer = sb / "conflicts.json"
    try:
        if answer.exists():
            answer.unlink()
    except OSError:
        pass
    rec = {"id": F"conflict_round{int(r)}", "kind": "conflicts", "attempts_done": 0}
    seconds = max(60, min(int(timeout) if timeout else 900, 1800))
    res = _execute_attempt_in(sb, rec, [str(x) for x in cmd], seconds,
                              prompt_name="PROMPT.md", log_name="_agent.log",
                              archive_marker=False)
    info = {"used": True, "command": [str(x) for x in cmd], "rc": res.get("rc"),
            "error": res.get("error"), "duration": round(float(res.get("dur") or 0.0), 1),
            "sandbox": str(sb)}
    data = read_json(answer, revive=False, lenient=True)
    if not isinstance(data, dict):
        info["error"] = info.get("error") or "the agent wrote no parseable conflicts.json"
        info["ok"] = False
        return [], info
    conflicts = _normalize_llm_conflicts(data)
    info["conflicts"] = len(conflicts)
    info["ok"] = True
    return conflicts, info


def judge_conflicts_markdown(data: dict) -> str:
    """The per-round MANUAL TODO list (checkbox items) for the report files."""
    r = int(data.get("round") or 0)
    conflicts = data.get("conflicts") or []
    counts = data.get("counts") or _judge_conflict_counts(conflicts)
    lines = [
        F"# Judge-conflict manual checks — round {r}",
        "",
        F"Generated {data.get('generated')}; {counts.get('total', 0)} conflict(s) flagged: "
        F"{counts.get('blocker', 0)} blocker, {counts.get('major', 0)} major, "
        F"{counts.get('minor', 0)} minor.",
        "",
        "The judge panel is independent on purpose: its sessions are allowed to disagree, "
        "and the aggregation keeps both judgments. These items are therefore REQUIRED "
        "MANUAL CHECKS — the panel's numbers for the affected comparisons must not be "
        "cited until a human has resolved them. Each item names the judge runs, the "
        "conflicting statements, and what to verify.",
        "",
        F"Machine-readable form: `reports/round{r}_judge_conflicts.json`. "
        "After fixing a sheet's input, re-judge it with `retry --run <ID>` and re-decide.",
        "",
    ]
    if not conflicts:
        lines.append("No cross-judge conflicts were detected for this round.")
        return "\n".join(lines) + "\n"
    group = None
    for c in conflicts:
        g = "minor" if c.get("severity") == "minor" else "major"
        if g != group:
            group = g
            lines.append("## " + ("Blocking and major conflicts — resolve before citing "
                                  "the panel's numbers" if g == "major" else
                                  "Minor conflicts — process/bookkeeping disagreements"))
            lines.append("")
        lines.append(F"### {c.get('id')} — {c.get('kind')} ({c.get('severity')})")
        lines.append("")
        lines.append(F"- [ ] **Manual check required**: {c.get('manual_check')}")
        lines.append(F"- Comparison: `{c.get('member')}` vs `{c.get('opponent')}`")
        lines.append("- Judges: " + ", ".join(F"`{j}`" for j in (c.get("judges") or [])))
        lines.append(F"- Conflict: {c.get('summary')}")
        evidence = c.get("evidence") or []
        if evidence:
            lines.append("- Evidence:")
            for e in evidence:
                who = F"`{e.get('judge_run')}` " if e.get("judge_run") else ""
                lines.append(F"    - {who}[{e.get('side')}]: {e.get('text')}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_judge_conflicts_todo(ctx: Ctx) -> Path:
    """`reports/JUDGE_CONFLICTS_TODO.md`: every round's open manual checks."""
    lines = [
        "# Judge conflicts — manual TODO list",
        "",
        F"Root: `{ctx.root}`. Compiled from `reports/round<r>_judge_conflicts.json`.",
        "",
    ]
    total = 0
    for r in range(1, ctx.rounds_count() + 1):
        data = read_json(ctx.reports_dir / F"round{r}_judge_conflicts.json",
                         revive=False, lenient=True)
        if not isinstance(data, dict):
            continue
        conflicts = data.get("conflicts") or []
        total += len(conflicts)
        counts = data.get("counts") or _judge_conflict_counts(conflicts)
        lines.append(F"## Round {r} — {counts.get('total', len(conflicts))} conflict(s)")
        lines.append("")
        if not conflicts:
            lines.append("None detected.")
            lines.append("")
            continue
        major = [c for c in conflicts if c.get("severity") != "minor"]
        minor = [c for c in conflicts if c.get("severity") == "minor"]
        if major:
            lines.append("Blocking/major checks (resolve first):")
            lines.append("")
        for c in major:
            lines.append(F"- [ ] **{c.get('id')}** [{c.get('kind')}/{c.get('severity')}] "
                         F"`{c.get('member')}` vs `{c.get('opponent')}` — "
                         F"{c.get('summary')}")
            lines.append(F"      verify: {c.get('manual_check')}")
        if minor:
            lines.append("")
            lines.append(F"Minor process/bookkeeping checks ({len(minor)}):")
            lines.append("")
        for c in minor:
            lines.append(F"- [ ] **{c.get('id')}** [{c.get('kind')}/{c.get('severity')}] "
                         F"`{c.get('member')}` vs `{c.get('opponent')}` — "
                         F"{c.get('summary')}")
            lines.append(F"      verify: {c.get('manual_check')}")
        lines.append("")
    lines.append(F"**{total} manual check(s) across the decided round(s).**")
    p = ctx.reports_dir / "JUDGE_CONFLICTS_TODO.md"
    write_text_atomic(p, "\n".join(lines) + "\n")
    return p


def write_round_judge_conflicts(ctx: Ctx, r: int, agg: dict = None, agent_cmd: list = None,
                                timeout: int = None, use_agent: bool = True,
                                force: bool = False) -> dict:
    """Audit one round's judge sheets and write the manual-check files.

    Deterministic conflicts are always computed.  When `agent_cmd` is given (and
    `use_agent` is true), the optional LLM auditor runs in
    `reports/conflict_check_round<r>/` and its schema-checked conflicts are
    merged.  Re-running with the same judge sheets is a no-op unless `force` is
    set, so `run` and `decide` do not pay for the agent twice.
    """
    r = int(r)
    round_field = [str(v) for v in ((agg or {}).get("field")
                                    or ctx.round_rec(r).get("field") or [])]
    opinions = round_judge_opinions(ctx, r, field=round_field)
    # Never certify an empty audit as "0 conflicts": a root whose judge sheets
    # are done but whose directed comparisons cannot be extracted (missing
    # field / label_map / scores) must fail loudly instead of writing the same
    # report as a panel that genuinely agreed.  The 2026-10-06 regression in
    # `run` did exactly that: the round's `field` was not written yet, every
    # comparison was dropped, and a full 16-sheet panel was reported clean.
    if not opinions:
        done_sheets = [rec for rec in ctx.runs(kind="judge", round_no=r)
                       if rec.get("status") == "done"]
        if done_sheets:
            raise RuntimeError(
                F"round {r}: {len(done_sheets)} judge sheet(s) are done but no "
                F"directed comparison could be extracted (field carries "
                F"{len(round_field)} member(s); check the runs' scores/label_map); "
                F"refusing to write a 0-conflict report from an empty audit input")
    mechanical = detect_round_judge_conflicts(opinions)
    payload = {
        "run": ctx.root.name, "round": r, "generated": utcnow(),
        "field": round_field,
        "opinions": opinions, "candidate_conflicts": mechanical,
    }
    fingerprint = hashlib.sha256(
        json.dumps(_json_safe(opinions), sort_keys=True, ensure_ascii=False)
        .encode("utf-8")).hexdigest()[:16]
    json_path = ctx.reports_dir / F"round{r}_judge_conflicts.json"
    existing = read_json(json_path, revive=False, lenient=True)
    agent_info = {"used": False, "reason": "no agent backend"}
    if isinstance(existing, dict) and existing.get("input_fingerprint") == fingerprint \
            and not force:
        already_llm = bool((existing.get("agent") or {}).get("ok"))
        if not (agent_cmd and use_agent and not already_llm):
            return existing
    llm_conflicts = []
    if agent_cmd and use_agent:
        try:
            llm_conflicts, agent_info = run_judge_conflict_agent(
                ctx, r, payload, agent_cmd, timeout=timeout)
        except Exception as e:                                       # noqa: BLE001
            agent_info = {"used": False, "error": F"{type(e).__name__}: {e}"}
    conflicts = _merge_judge_conflicts(mechanical, llm_conflicts)
    for i, c in enumerate(conflicts, 1):
        c["id"] = F"C{r}-{i:03d}"
    counts = _judge_conflict_counts(conflicts)
    data = {
        "run": ctx.root.name, "round": r, "generated": utcnow(),
        "input_fingerprint": fingerprint,
        "judges": sorted({o.get("judge_run") for o in opinions if o.get("judge_run")}),
        "opinions": len(opinions),
        "counts": counts, "conflicts": conflicts,
        "agent": agent_info,
    }
    write_json_atomic(json_path, data)
    write_text_atomic(ctx.reports_dir / F"round{r}_judge_conflicts.md",
                      judge_conflicts_markdown(data))
    return data


PAPER_CONFLICT_AGENT_ENV = "PAPER_CONFLICT_AGENT_CMD"


def _conflict_agent_cmd_from_env(name: str):
    """Parse a JSON argv list from `name` (None when unset or invalid)."""
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        argv = json.loads(raw)
    except json.JSONDecodeError:
        print(F"[conflicts] WARNING: {name} is not a JSON argv list; ignoring it")
        return None
    if not isinstance(argv, list) or not argv:
        print(F"[conflicts] WARNING: {name} must be a non-empty JSON argv list; ignoring it")
        return None
    return [str(x) for x in argv]


def _conflict_cmd_usable(cmd) -> bool:
    if not cmd:
        return False
    if shutil.which(str(cmd[0])) is None:
        print(F"[conflicts] note: agent executable {cmd[0]!r} is not on PATH; running the "
              F"deterministic conflict check only")
        return False
    return True


def _looks_like_preset_cmd(cmd) -> bool:
    """True for a shipped preset's CLI invocation (not a stub or wrapper).

    The binaries are the preset table's own (codex/claude/dsh, see
    AGENT_PRESET_BINARIES): a test stub or a foreign tool reached through
    --agent-cmd/PAPER_AGENT_CMD must not be handed a second protocol (the defect
    audit) uninvited.
    """
    try:
        return bool(cmd) and os.path.basename(str(cmd[0])).lower() in AGENT_PRESET_BINARIES
    except Exception:                                                # noqa: BLE001
        return False


def resolve_round_audit_cmd(conflict_cmd, conflict_agent: bool, judge_cmd,
                            judge_manual: bool, recorded: dict):
    """(cmd, source) for ONE round's conflict audit (see drive_round).

    The LLM conflict pass is OFF by default (2026-10-06): it runs only when the
    operator asks for it THIS invocation -- --conflict-agent / --conflict-agent-cmd
    on run/run-decide/decide, or PAPER_CONFLICT_AGENT_CMD.  A recorded backend is
    still recorded (state.json -> conflict_agent) for diagnostics, but it no
    longer turns the auditor back on in a later command; `judge_cmd`,
    `judge_manual` and `recorded` are kept in the signature for compatibility
    with the call sites and the test suite.
    """
    if not conflict_agent:
        return None, "disabled"
    if conflict_cmd is not None:
        return conflict_cmd, "conflict-agent"
    dedicated = _conflict_agent_cmd_from_env(PAPER_CONFLICT_AGENT_ENV)
    if dedicated and _conflict_cmd_usable(dedicated):
        return dedicated, "conflict-agent-env"
    return None, "mechanical-default"


def default_conflict_agent_cmd():
    """The lightweight default backend for the conflict audit (None when unusable).

    PAPER_CONFLICT_AGENT_CMD (point it at a cheap CLI/model) wins, then the
    `codex-lite` preset (codex at low reasoning effort); PAPER_AGENT_CMD is only
    the fallback when no lightweight codex is available, so pointing the
    production agent at a heavy model does not make the audit heavy.  Never
    raises: an unusable backend returns None so the mechanical pass carries on.
    """
    cmd = _conflict_agent_cmd_from_env(PAPER_CONFLICT_AGENT_ENV)
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


def conflict_agent_cmd_from_args(args, ctx: Ctx = None) -> list:
    """The LLM backend for the conflict audit (None = mechanical check only).

    OFF by default (2026-10-06): `decide` (and the `conflicts` command, which has
    its own resolver) runs the LLM pass only when the operator asks for it this
    invocation -- --conflict-agent / --conflict-agent-cmd, or the audit-specific
    PAPER_CONFLICT_AGENT_CMD.  The backend `run` recorded is diagnostic only and
    never turns the auditor back on by itself.  --no-conflict-agent and
    --conflict-agent manual keep the deterministic pass only.
    """
    if getattr(args, "no_conflict_agent", False):
        return None
    explicit = getattr(args, "conflict_agent_cmd", None)
    agent = getattr(args, "conflict_agent", None)
    cmd = None
    if explicit:
        try:
            cmd = resolve_agent_cmd(agent or "codex-lite", explicit)
        except SystemExit:
            print("[conflicts] WARNING: --conflict-agent-cmd could not be resolved; running the "
                  "deterministic conflict check only")
            return None
    elif agent == "manual":
        return None
    elif agent:
        try:
            cmd = resolve_agent_cmd(agent, getattr(args, "agent_cmd", None))
        except SystemExit:
            cmd = None
    else:
        # Only the audit-specific environment variable can turn the pass on
        # without a flag; the recorded backend stays diagnostic.
        cmd = _conflict_agent_cmd_from_env(PAPER_CONFLICT_AGENT_ENV)
        if cmd is not None and not _conflict_cmd_usable(cmd):
            cmd = None
    if not cmd or not _conflict_cmd_usable(cmd):
        return None
    return [str(x) for x in cmd]


def conflict_cmd_for_command(args, ctx: Ctx = None) -> list:
    """The LLM backend for the standalone `conflicts` command (None = off).

    Its parser defaults `--agent` to "manual" (the LLM conflict pass is OFF by
    default), so an explicit ask is any of: --conflict-agent-cmd / --agent-cmd,
    --conflict-agent <preset>, PAPER_CONFLICT_AGENT_CMD, or a non-manual --agent.
    `--no-agent` and `--conflict-agent manual` keep the deterministic pass, and
    the backend `run` recorded is diagnostic only (never re-enables the pass).
    """
    if getattr(args, "no_agent", False):
        return None
    explicit = getattr(args, "conflict_agent_cmd", None) or getattr(args, "agent_cmd", None)
    choice = getattr(args, "conflict_agent", None)
    agent = getattr(args, "agent", None)
    cmd = None
    if explicit:
        try:
            cmd = resolve_agent_cmd(choice or agent or "codex-lite", explicit)
        except SystemExit:
            cmd = None
    elif choice == "manual":
        cmd = None
    elif choice:
        try:
            cmd = resolve_agent_cmd(choice, None, use_env=False)
        except SystemExit:
            cmd = None
    else:
        cmd = _conflict_agent_cmd_from_env(PAPER_CONFLICT_AGENT_ENV)
        if cmd is not None and not _conflict_cmd_usable(cmd):
            cmd = None
        if cmd is None and agent and agent != "manual":
            # `conflicts --agent <preset>` is itself an explicit ask.
            try:
                cmd = resolve_agent_cmd(agent, None, use_env=False)
            except SystemExit:
                cmd = None
    if not cmd or not _conflict_cmd_usable(cmd):
        return None
    return [str(x) for x in cmd]


def cmd_conflicts(args) -> None:
    """`conflicts`: audit every round's judge panels and write the manual TODO list."""
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    with ctx.lock("conflicts"):
        if getattr(args, "round", None) is not None \
                and not (1 <= int(args.round) <= ctx.rounds_count()):
            die(F"--round must be in 1..{ctx.rounds_count()} (got {args.round})")
        cmd = conflict_cmd_for_command(args, ctx)
        print("[conflicts] audit backend: "
              + (" ".join(cmd) if cmd else "none (deterministic check only)"))
        rounds = ([int(args.round)] if getattr(args, "round", None)
                  else [r for r in range(1, ctx.rounds_count() + 1)
                        # A DONE judge sheet is the entry condition, not the
                        # extraction: a round whose comparisons cannot be read
                        # must reach write_round_judge_conflicts' empty-audit
                        # guard instead of disappearing as "nothing to audit".
                        if any(rec.get("status") == "done"
                               for rec in ctx.runs(kind="judge", round_no=r))])
        if not rounds:
            print("[conflicts] no round with judge sheets; nothing to audit")
            return
        failed = []
        for r in rounds:
            try:
                data = write_round_judge_conflicts(
                    ctx, r, agent_cmd=cmd, timeout=getattr(args, "timeout", None),
                    force=bool(getattr(args, "force", False)))
            except Exception as e:                                   # noqa: BLE001
                failed.append(r)
                print(F"[conflicts] round {r}: the audit could not run: "
                      F"{type(e).__name__}: {e}")
                continue
            counts = data.get("counts") or {}
            print(F"[conflicts] round {r}: {counts.get('total', 0)} conflict(s) "
                  F"({counts.get('blocker', 0)} blocker, {counts.get('major', 0)} major, "
                  F"{counts.get('minor', 0)} minor) -> "
                  F"reports/round{r}_judge_conflicts.md")
        p = write_judge_conflicts_todo(ctx)
        print(F"[conflicts] manual TODO list -> {p.relative_to(ctx.root).as_posix()}")
        if failed:
            die(F"the conflict audit failed for round(s) "
                F"{', '.join(str(x) for x in failed)}; no fresh report was written "
                F"for them (see the message above)")


# The columns of the round's REVIEW-FINDINGS list: the review pass's own frozen
# findings (reports/round<r>_review/findings.json + findings_extra.json),
# flattened to one row per finding with the verbal description the review wrote.
# The judge-panel defect list (round<r>_defects.csv) answers "which defects does
# each VERSION carry"; this file answers "what did the ROUND's review report",
# with the finding id the revision ledger and the audit dispositions use.
REVIEW_FINDINGS_FIELDS = ("run", "round", "finding_id", "source", "category", "check",
                          "severity", "status", "location", "evidence", "explanation")
REVIEW_FINDINGS_SOURCES = (("findings.json", "review"), ("findings_extra.json", "discovery"))


def review_findings_rows(ctx: Ctx, r: int) -> list:
    """The archived review findings of one round, flattened ([] when none)."""
    arch = ctx.reports_dir / f"round{int(r)}_review"
    rows = []
    for name, source in REVIEW_FINDINGS_SOURCES:
        data = read_json(arch / name, revive=False, lenient=True)
        if not isinstance(data, dict):
            continue
        for f in data.get("findings") or []:
            if not isinstance(f, dict):
                continue
            rows.append({
                "run": ctx.root.name, "round": int(r),
                "finding_id": str(f.get("id") or ""), "source": source,
                "category": f.get("category"), "check": str(f.get("check") or ""),
                "severity": str(f.get("severity") or ""),
                "status": str(f.get("status") or ""),
                "location": str(f.get("location") or ""),
                "evidence": str(f.get("evidence") or ""),
                "explanation": str(f.get("explanation") or "")})
    return rows


def write_round_review_findings(ctx: Ctx, r: int) -> Path:
    """`reports/round<r>_review_findings.csv`: the review's findings, one row each.

    Written from the ARCHIVED review deliverables (the round's review is archived
    beside it), so it works for a round whose sandbox was already pruned; a
    round with no archived review writes a header-only file (the file's shape is
    stable, and an empty file is the honest "nothing was reviewed").
    """
    rows = review_findings_rows(ctx, r)
    p = ctx.reports_dir / f"round{int(r)}_review_findings.csv"
    return write_csv_atomic(p, REVIEW_FINDINGS_FIELDS, rows)


ISSUE_MATRIX_META_FIELDS = ("run", "round", "version")


def issue_matrix_rows(ctx: Ctx, r: int, agg: dict) -> tuple:
    """(cell names, rows) for the NON-cumulative severity_tier_category matrix."""
    field = [str(v) for v in (agg.get("field") or [])]
    names, matrix, _cum = issue_matrix_and_cumulative(agg.get("issue_census") or {}, field)
    rows = []
    for vid in field:
        row = {"run": ctx.root.name, "round": int(r), "version": vid}
        row.update({name: matrix[str(vid)][i] for i, name in enumerate(names)})
        rows.append(row)
    return names, rows


def issue_cumulative_rows(ctx: Ctx, r: int, agg: dict) -> tuple:
    """(cell names, rows) for the PREFIX-SUM severity_tier_category matrix."""
    field = [str(v) for v in (agg.get("field") or [])]
    names, _matrix, cumulative = issue_matrix_and_cumulative(
        agg.get("issue_census") or {}, field)
    rows = []
    for vid in field:
        row = {"run": ctx.root.name, "round": int(r), "version": vid}
        row.update({name: cumulative[str(vid)][i] for i, name in enumerate(names)})
        rows.append(row)
    return names, rows


def _write_issue_matrix_file(path: Path, names: list, rows: list) -> Path:
    return write_csv_atomic(path, list(ISSUE_MATRIX_META_FIELDS) + list(names), rows)


def write_round_issue_matrix(ctx: Ctx, r: int, agg: dict = None,
                             name: str = None) -> Path:
    """`reports/round<r>_issue_matrix.csv` (fileA): rows = versions, columns =
    the severity_tier_category cells in canonical order, values = the reported
    defect counts per cell (peer/own as separate cells). The lattice uses the
    SAME four severity rungs as the long-form census (fatal, critical, major,
    minor; 48 cells), so every artifact speaks one vocabulary."""
    r, agg = _issue_file_agg(ctx, r, agg)
    names, rows = issue_matrix_rows(ctx, r, agg)
    return _write_issue_matrix_file(
        ctx.reports_dir / (name or f"round{r}_issue_matrix.csv"), names, rows)


def write_round_issue_cumulative(ctx: Ctx, r: int, agg: dict = None,
                                 name: str = None) -> Path:
    """`reports/round<r>_issue_cumulative.csv`: the PREFIX SUMS of fileA, same
    rows and columns: cell k holds the cumulative defect count over the first k
    cells of the canonical order."""
    r, agg = _issue_file_agg(ctx, r, agg)
    names, rows = issue_cumulative_rows(ctx, r, agg)
    return _write_issue_matrix_file(
        ctx.reports_dir / (name or f"round{r}_issue_cumulative.csv"), names, rows)


def dedup_audit_payload(ctx: Ctx, r: int, agg: dict) -> dict:
    """The machine-readable record of one round's cross-sheet merges."""
    census = agg.get("issue_census") or {}
    merges = []
    for vid in agg.get("field") or []:
        merges.extend(list((census.get(str(vid)) or {}).get("dedup_audit") or []))
    return {"run": ctx.root.name, "round": int(r),
            "mode": dedup_mode_of(ctx),
            "min_words": DEDUP_MIN_WORDS,
            "fuzzy_threshold": DEDUP_FUZZY_THRESHOLD,
            "merged_rows": len(merges),
            "merges": merges}


def write_round_dedup_audit(ctx: Ctx, r: int, agg: dict = None,
                            name: str = None) -> Path:
    """`reports/round<r>_dedup_audit.json`: every merge the opt-in mode made.

    One record per merged row (version, source, session, defect class, line,
    excerpt, and the kept row's session/excerpt), so an operator can audit the
    fuzzy step by hand. The file is written for every mode -- an "off" round
    carries zero merges -- so the report shape does not change with the mode.
    """
    r, agg = _issue_file_agg(ctx, r, agg)
    p = ctx.reports_dir / (name or f"round{r}_dedup_audit.json")
    write_json_atomic(p, dedup_audit_payload(ctx, r, agg))
    return p


# The per-round census table's columns (DECISION_REPORT.md). The tier columns
# are totals over severities and the severity columns are totals over tiers, so
# the two blocks overlap on purpose: one answers "what is left and where", the
# other "how bad is it". The severity columns follow the RANKING's rung order
# (fatal, critical, major, minor -- the walk order), not the judge's weakest-
# first `SEVERITIES` vocabulary, so the table reads like the key it feeds.
ISSUE_CENSUS_TABLE_HEAD = (["member"] + list(BASIS_TIERS) + list(SEVERITY_TIE_ORDER)
                           + ["own/peer", "per session", "sessions o/p/expected"])


def issue_census_table(agg: dict) -> list:
    """The reported census rows (one per field member) for DECISION_REPORT.md."""
    census = agg.get("issue_census") or {}
    rows = []
    for vid in agg.get("field") or []:
        c = census.get(vid) or {}
        tiers = c.get("tiers") or {}
        sevs = c.get("severities") or {}
        rows.append([vid]
                    + [str((tiers.get(t) or {}).get("total", 0)) for t in BASIS_TIERS]
                    + [str((sevs.get(s) or {}).get("total", 0)) for s in SEVERITY_TIE_ORDER]
                    + [f"{c.get('own', 0)}/{c.get('peer', 0)}",
                       (f"{c.get('per_session'):g}" if c.get("per_session") is not None else "-"),
                       f"{c.get('own_sessions')}/{c.get('peer_sessions')}/"
                       f"{c.get('sessions_expected')}"])
    return rows


def backfill_round_raw_scores(ctx: Ctx) -> list:
    """Write the round report files (`raw_scores`, `issue_census`, `defects`, ...).

    A round decided before this report existed (or by an older copy of the
    pipeline) still has its judge sheets in state, so re-aggregating it costs one
    re-read and hands the operator the same file every later round gets
    automatically -- including `reports/round<r>_defects.csv`, the census's long
    form (every defect mention with its version, source, class, severity and the
    sheet's own evidence sentence). Only MISSING files are written -- the
    run-time writer owns the content of the rest.
    """
    out = []
    for r in range(1, ctx.rounds_count() + 1):
        rec = ctx.round_rec(r)
        if rec.get("status") != "done" or not (rec.get("field") or []):
            continue
        if rec.get("auto_promoted") or (rec.get("plan") or {}).get("champion_select") not in (
                None, "judge"):
            # An auto-promoted round has no judge sheets: aggregating it would
            # write empty score/census files that look like a scored panel.
            continue
        for name, writer in ((f"round{r}_raw_scores.csv", write_round_raw_scores),
                             (f"round{r}_issue_census.csv", write_round_issue_census),
                             (f"round{r}_issue_matrix.csv", write_round_issue_matrix),
                             (f"round{r}_issue_cumulative.csv", write_round_issue_cumulative),
                             (f"round{r}_dedup_audit.json", write_round_dedup_audit),
                             (f"round{r}_defects.csv", write_round_defects)):
            if (ctx.reports_dir / name).is_file():
                continue
            try:
                out.append(writer(ctx, r))
            except Exception as e:                               # noqa: BLE001
                print(f"[run] r{r} WARNING: could not write reports/{name}: {e}")
        # The review's own finding list (verbal descriptions included) is only
        # written when the round actually has an archived review.
        if not (ctx.reports_dir / f"round{r}_review_findings.csv").is_file() \
                and any((ctx.reports_dir / f"round{r}_review" / name).is_file()
                        for name, _src in REVIEW_FINDINGS_SOURCES):
            try:
                out.append(write_round_review_findings(ctx, r))
            except Exception as e:                               # noqa: BLE001
                print(f"[run] r{r} WARNING: could not write "
                      f"reports/round{r}_review_findings.csv: {e}")
    if out:
        print("[run] raw scores written for round(s) decided before this report existed: "
              + ", ".join(f"reports/{p.name}" for p in out))
    return out


def score_model_doc(ctx=None) -> dict:
    """The machine-readable description of how a round is scored and ranked.

    Factored out of build_decision_report so the score model is one object with
    one definition (decision.json, the report and the tests all read it) instead
    of a dict literal buried in a larger literal.
    """
    return {
        "scores_per_version": "2*judges*(|field|-1) "
                              "(= 4*(|field|-1) at the default 2 judges)",
        "scale": [SCORE_MIN, SCORE_MAX],
        "scale_note": "bounded by design: the production panel used -3..+3 and never +-4, so "
                      "widening the range would add unused rungs; the graded basis below is what "
                      "anchors the existing ones",
        "judge_contract": JUDGE_CONTRACT_VERSION,
        "graded_basis": {
            "tiers": list(BASIS_TIERS),
            "severities": list(SEVERITIES),
            "rules": ["the six tiers are compared LEXICOGRAPHICALLY in the priority order; the "
                      "FIRST tier whose net is not zero decides the comparison, and no "
                      "lower-priority tier can offset it",
                      "rows weigh minor 1 / major 2 / critical 3 / fatal 4; resolved add, "
                      "introduced subtract; the deciding tier's net is capped at +-4",
                      "the magnitude is bounded by the deciding tier's own rows: MINOR-only <= 2, "
                      "a MAJOR row reaches 3, a CRITICAL/FATAL row reaches 4",
                      "a non-zero score needs a ledger item on its own side in the deciding tier",
                      "|score| >= 3 needs a MAJOR/CRITICAL/FATAL item there, and |score| = 4 a "
                      "CRITICAL/FATAL one",
                      "a length/caption row (`M18`/`M19`) is a formatting-tier MINOR row: length "
                      "moves a comparison by at most +-1 and is never a scoring tier",
                      "every comparison carries a `checks` disposition for every frozen check id",
                      "the integer is checked against its own ledger, and a contradicting sheet "
                      "fails its run"],
            "legacy_policy": "sheets from sandboxes materialized before the contract are "
                             "accepted with a warning and counted as uncalibrated; they are "
                             "never silently mixed into a calibrated panel"},
        "ranking": "the cumulative reported defect count over the adaptive "
                   "severity_tier_category prefix LEADS (fewer defects is better; the cells are "
                   "fatal -> critical -> major -> minor, tier by tier in the scoring priority "
                   "order, peer before own -- the SAME four severity rungs the census, the "
                   "judge contract and the score model use; the walk stops when the "
                   "cleanest ranked version reaches the `tiebreak_defect_floor` or every cell "
                   "is used), then the median of the flat directed-score list, then the "
                   "arithmetic mean, the IQR and the content digest; an exact "
                   "(median, mean, IQR) tie still keeps the incumbent base",
        "cross_round_comparability": "per-round champion statistics come from different panels "
                                     "and different fields and are NOT comparable across rounds; "
                                     "the vs_base margin of the final round is the only paired "
                                     "statement the decision supports",
        "anti_regression_tolerance": VS_ORIGINAL_TOLERANCE,
        "anti_regression_rule": f"{VS_ORIGINAL_RULE} (setup --vs-original-rule median|sign); "
                                f"the sign rule fails only when the exact one-sided sign test "
                                f"over the pair's 2*judges directed scores is significant at "
                                f"{VS_ORIGINAL_ALPHA}; with so few scores NEITHER rule is "
                                f"well-powered, and every row reports its wins/losses/ties and p",
        "tiebreak_defect_floor": tiebreak_defect_floor_of(ctx),
        "dedup_mode": dedup_mode_of(ctx),
        "tiebreaks": ["cumulative defect count over the adaptive severity_tier_category prefix "
                      "(fatal->critical->major->minor, tier order, peer then own; the walk stops "
                      "when the cleanest ranked version reaches `tiebreak_defect_floor` or every "
                      "cell is used), ascending",
                      "-median", "-mean", "IQR", "digest", "id",
                      "the incumbent rule overrides on an exact (median, mean, IQR) tie"],
        "tiebreak_notes": "median/mean/IQR are PANEL statistics (verifiable); the cumulative "
                          "counts come from the panel's own ledger rows: each cell is the "
                          "count of one (severity, tier, source) combination "
                          "(reports/round<r>_issue_matrix.csv) on the same four severity rungs "
                          "the long-form census reports (fatal, critical, major, minor), the "
                          "cells are "
                          "accumulated in the "
                          "canonical severity_tier_category order (reports/round<r>_"
                          "issue_cumulative.csv), and the walk stops at the first prefix where "
                          "the version with the FEWEST defects has "
                          "`tiebreak_defect_floor` of them (default 10) -- or when every cell is "
                          "included; the cumulative count at that prefix LEADS the ranking (the "
                          "median, then the mean, the IQR and the digest are the fallbacks), "
                          "and a small per-cell count is deliberately never a rung of its own; "
                          "`dedup_mode` off (the default) performs NO cross-sheet matching (a "
                          "judge sheet that repeats a row in the same sheet counts it once, a row "
                          "two sheets both filed counts twice); the opt-in `dedup_mode` location "
                          "merges rows across sheets ONLY on the structured key (the same "
                          "defect class -- the NORMALIZED CHECK ID, whatever the sheet cites, "
                          "e.g. M01/M02/J3/FMT-*, never a closed set --, the same exact line "
                          "number, both excerpts >= DEDUP_MIN_WORDS words "
                          "with token-set Jaccard >= DEDUP_FUZZY_THRESHOLD), never merges rows "
                          "without a parseable line or a short excerpt, and records every merge "
                          "in reports/round<r>_dedup_audit.json; vs_base is reported (the incumbent margin a human reads) "
                          "but is deliberately NOT a ranking key: its 2*judges directed scores "
                          "are few enough that one outlier session flips its sign statistic; "
                          "critical_remaining and writing_remaining are SELF-REPORTED by the "
                          "producing agent, reported and cross-checked but NOT ranked; an exact "
                          "tie on median, mean and IQR keeps the incumbent base (the census "
                          "rungs and the digest never dethrone it); the content digest is the "
                          "provenance-free fallback so an arm's NAME never decides a tie; "
                          "manual_steps, caption length and hand-off placeholders are reported, "
                          "never ranked",
        "reported_but_not_ranked": ["manual_steps", "figure-caption length (M18)",
                                    "hand-off placeholders",
                                    "critical_remaining (self-reported)",
                                    "writing_remaining (self-reported)"],
        "visual_tools_detected": visual_tools_summary(),
        "review_contract": "submission_dir must resolve to base/, the coverage table must carry "
                           "every required check id, review/artifacts/ must exist, finding ids "
                           "must be unique, and prior-round findings must be reconciled",
        "base_is_winnable": True,
        "note_on_gates": "caption length and hand-off placeholders are advisory and never gate; "
                         "the only eligibility gates are a complete panel for every ranked row "
                         "plus, for a fresh arm, the vs-original anti-regression gate",
    }


def _increment_counter_name(name: str):
    """The user's generation counter: int(filename.split("-")[1]) + 1.

    "cnb-11-3-suppAll-i.tex" -> "cnb-12-3-suppAll-i.tex",
    "cnb-11-nr-reporting-summary-filled-b.pdf" -> "cnb-12-nr-...pdf".
    Returns None when the second dash-separated field of the stem is missing or
    is not an integer (index error / ValueError are both guarded), so every
    other filename is left exactly as it is.
    """
    stem = Path(name).stem
    suffix = name[len(stem):]
    parts = stem.split("-")
    try:
        field = parts[1]
    except IndexError:
        return None
    if not re.fullmatch(r"\d+", field or ""):
        return None
    try:
        number = int(field)
    except ValueError:
        return None
    parts[1] = str(number + 1)
    return "-".join(parts) + suffix


def _increment_final_clean_counters(dirp: Path) -> dict:
    """Increment the generation counter in every filename under dirp.

    Returns {"renamed": N, "file_map": {old_rel: new_rel}, "collisions": [...]}
    after applying the renames AND repointing the references inside text files
    (LaTeX
    \\input/\\include/\\includegraphics/\\addbibresource/\\bibliography,
    \\graphicspath, build scripts, derived .aux/.bcf/.bbl text), so the
    incremented package stays buildable as the next run's --source.

    Two sources that increment to the SAME name (for example "cnb-011-x" and
    "cnb-11-x", both -> "cnb-12-x") are not renamed at all: the pairs are
    returned under "collisions" and the caller aborts the publication, because
    renaming them would destroy one of them. Ordinary transient occupancy
    ("cnb-11-x" -> "cnb-12-x" while "cnb-12-x" itself is moving to "cnb-13-x")
    is handled by renaming every source to a unique temporary name first and
    then to its final name.

    `raw_data/` is EXCLUDED, in both directions: the
    author's data files keep their names (renaming one inside the read-only tree
    would both fail and silently change an input), and their text is never
    rewritten. References INTO raw_data from the manuscript's own files are
    still repointed, because the callee's file_map carries their relative paths.
    """
    raw_data_skipped = 0
    files = []
    for p in sorted(dirp.rglob("*")):
        if not p.is_file():
            continue
        if is_evidence_rel(p.relative_to(dirp).as_posix()):
            raw_data_skipped += 1
            continue
        files.append(p)
    # The counter runs on the pipeline's OWN copy of the package, so it owns the
    # write bits -- but the copy inherits the source's modes, and the source may
    # be read-only outside raw_data too. Clear them (never inside raw_data).
    make_tree_writable(dirp, skip_top=EVIDENCE_DIRNAMES)
    file_map = {}
    for p in files:
        rel = p.relative_to(dirp).as_posix()
        new_name = _increment_counter_name(p.name)
        parent = posixpath.dirname(rel)
        file_map[rel] = (f"{parent}/{new_name}" if parent else new_name) if new_name else rel
    renamed = {old: new for old, new in file_map.items() if new != old}
    targets = {}
    for old_rel, new_rel in renamed.items():
        targets.setdefault(new_rel, []).append(old_rel)
    collisions = [f"{new} <- {', '.join(sorted(srcs))}"
                  for new, srcs in sorted(targets.items()) if len(srcs) > 1]
    if collisions:
        return {"renamed": 0, "file_map": {}, "collisions": collisions}
    staged = []
    for i, (old_rel, new_rel) in enumerate(sorted(renamed.items())):
        src = dirp / old_rel
        tmp = dirp / f".paper_counter_tmp_{os.getpid()}_{i}"
        while tmp.exists():
            i += 1
            tmp = dirp / f".paper_counter_tmp_{os.getpid()}_{i}"
        src.rename(tmp)
        staged.append((tmp, new_rel))
    for tmp, new_rel in staged:
        tmp.rename(dirp / new_rel)
    if renamed:
        reverse = {new: old for old, new in file_map.items()}
        for new_rel in sorted(file_map.values()):
            if not _view_is_text(new_rel):
                continue
            p = dirp / new_rel
            raw = p.read_bytes()
            text = raw.decode("utf-8", "surrogateescape")
            text = _rewrite_view_references(text, reverse[new_rel], new_rel, file_map)
            try:
                p.write_bytes(text.encode("utf-8", "surrogateescape"))
            except OSError:
                # A file mode the writer could not clear (an ACL, a Windows lock):
                # the content pass is best-effort, the rename above already
                # happened, and the caller records the counter's own result.
                make_writable(p, directory=False)
                p.write_bytes(text.encode("utf-8", "surrogateescape"))
    return {"renamed": len(renamed), "file_map": renamed, "collisions": [],
            "raw_data_untouched": raw_data_skipped}


def decide_certification(gate_problems, rounds_data, chain_ok, panel_gaps, final_regression,
                         provisional, require_complete, final_round, rounds_total,
                         final_clean, clean_reason, auto_promoted=None) -> dict:
    """The ONE certification verdict: decision.json, the report and the exit code.

    `certified` is true only when nothing blocks AND the answer is not
    provisional; `exit_code` is 5 for a blocker, 4 for a provisional answer
    under --require-complete, and 0 otherwise. `clean_version` records whether
    THIS invocation published final_clean_version/ (and why not), so a reader
    can tell a fresh package from one left by an earlier decision.

    `auto_promoted` lists rounds whose champion was chosen without a judge panel
    (`--champion-select revise|integrate`). Such an answer can never be
    certified: it is PROVISIONAL by construction, and the reason is a note (not
    a blocker), because the operator asked for exactly this outcome.
    """
    auto_promoted = [int(r) for r in (auto_promoted or [])]
    blockers = list(gate_problems)
    if any(rd.get("mismatch") for rd in rounds_data):
        blockers.extend(str(rd["mismatch"]) for rd in rounds_data if rd.get("mismatch"))
    if not chain_ok:
        blockers.append("the pristine/pinned/evidence integrity no longer matches disk")
    if panel_gaps:
        blockers.append("one or more rounds have an incomplete judge panel")
    if final_regression:
        blockers.append(final_regression)
    notes = []
    if provisional and int(final_round) < int(rounds_total):
        notes.append(f"only round {final_round} of {rounds_total} is complete; the answer is "
                     f"provisional")
    if auto_promoted:
        notes.append(
            f"round(s) {', '.join(str(r) for r in auto_promoted)} were auto-promoted without "
            f"a judge panel (--champion-select); an unjudged winner is PROVISIONAL and is "
            f"never a certified panel result")
    status = ("certified" if (not blockers and not provisional)
              else ("provisional" if (provisional and not blockers) else "not_certified"))
    return {"certified": bool(not blockers and not provisional),
            "provisional": bool(provisional),
            "auto_promoted": auto_promoted,
            "blockers": blockers,
            "notes": notes,
            # What THIS invocation exits with: 5 = a blocker, 4 = a provisional
            # answer under --require-complete, 0 = certified (or a deliberately
            # provisional answer without the flag).
            "exit_code": (5 if blockers
                          else (4 if (provisional and require_complete) else 0)),
            "clean_version": {"published": bool((final_clean or {}).get("files")),
                              "status": status,
                              "readme": FINAL_CLEAN_README_NAME,
                              "skipped_reason": clean_reason or None}}


def certification_label(certification) -> str:
    """`CERTIFIED` / `PROVISIONAL` / `NOT CERTIFIED` for one certification dict.

    A panel-certified answer whose published package still carries readiness
    findings is NOT labelled a bare `CERTIFIED`: the round-2 readmes said
    `Certification: CERTIFIED` at the top and `Submission readiness: NOT READY`
    thirty lines later, and a reader could not tell which was the verdict.
    """
    cert = certification or {}
    if cert.get("certified"):
        if cert.get("submission_ready") is False:
            return "CERTIFIED (panel) — NOT SUBMISSION-READY"
        return "CERTIFIED"
    if cert.get("auto_promoted") and not cert.get("blockers"):
        return "AUTO-PROMOTED — PROVISIONAL (NOT JUDGED)"
    if cert.get("provisional") and not cert.get("blockers"):
        return "PROVISIONAL"
    return "NOT CERTIFIED"


def final_clean_reason(final: dict, rounds_data: list, rounds_total: int, final_regression,
                       chain_ok: bool, provisional: bool, panel_gaps: dict,
                       gate_problems: list, auto_promoted=None, skipped=None) -> str:
    """The note the final_clean_version sibling readme carries ("" = none).

    Mirrors decide_certification's blockers: ANY round whose stored champion
    failed recomputation blocks the verdict, not only the final round. The
    inlined form checked `final["mismatch"]` alone, so decision.json could carry
    `final_clean_version.certified: true` beside `certification.certified:
    false` when an earlier round mismatched.
    """
    if skipped:
        return f"the final_clean_version package was not published: {skipped}"
    if any(rd.get("mismatch") for rd in rounds_data):
        return "a stored champion failed recomputation"
    if final_regression:
        return final_regression
    if not chain_ok:
        return "the content-addressed chain is broken"
    if auto_promoted:
        return ("the champion was auto-promoted without a judge panel "
                f"(round(s) {', '.join(str(r) for r in auto_promoted)}; "
                f"--champion-select); it is PROVISIONAL, not a certified panel result")
    if provisional:
        return (f"only round {final['round']} of {rounds_total} is complete "
                f"(the champion is provisional)")
    if panel_gaps:
        return "the judge panel is incomplete"
    if gate_problems:
        return "; ".join(gate_problems)
    return ""


# ---------------------------------------------------------------------
# PACKAGE HYGIENE (rule family PKG-*).
#
# The published package is what the author hands to the journal, and it carries
# whatever the champion corpus carries. Two classes shipped in real runs:
#   * the pipeline's OWN by-products (a re-authoring ledger with the internal
#     "machine-readable exceptions" block). They are stripped by NAME now
#     (`is_bookkeeping_name`, version token included) and anything that still
#     reaches the staging tree is REPORTED here.
#   * the author's own files carrying INTERNAL review material -- a
#     `raw_data.README.md` that answers two external AI-review sessions and
#     quotes their chat URLs. Nothing in a manuscript package should hand a
#     reviewer an internal critique of that same package.
# A PDF the package ships is checked with the artifact rules (FMT-PDF1..3): an
# unfilled Adobe form is a "required document" that renders blank.
# ---------------------------------------------------------------------

INTERNAL_ARTIFACT_RES = (
    ("an internal AI-review session URL",
     re.compile(r"https?://(?:chat\.z\.ai|sorryios\.ai|chatgpt\.com/share|poe\.com|"
                r"claude\.ai/chat|gemini\.google\.com|chat\.deepseek\.com|"
                r"aistudio\.google\.com|chatglm\.[a-z]+)[^\s)\]}>\"']*", re.I)),
    ("the pipeline's re-authoring ledger",
     re.compile(r"(?i)\bREPLACEMENT\s+LEDGER\b|\bmachine[- ]readable\s+exceptions\b")),
    # The pipeline's stage artifacts are named with UNDERSCORES (the published
    # copy may carry a version token): matching the prose spellings ("revision
    # report") would flag an author's own words, so the identifiers are
    # required, while "machine-readable exceptions" above already catches the
    # ledger's own vocabulary in running text.
    ("the pipeline's own stage report",
     re.compile(r"(?i)\b(?:REWRITE_REPORT|REWRITE-REPORT|DIFF_LEDGER|DIFF-LEDGER|"
                r"REVISION_REPORT|REVISION-REPORT|VISUAL_CHECK|VISUAL-CHECK|"
                r"MANUAL_STEPS|MANUAL-STEPS)\b|\bCHANGELOG\.md\b")),
    ("an internal working note that names this pipeline's stages",
     re.compile(r"(?i)\b(?:round\s*\d+\s*winner|a1\s*/\s*base|judge (?:sheet|wave)|"
                r"stage postcheck)\b")),
    # The 2026-10-15 neohet package shipped these two shapes in `code/README.md`
    # -- the file the code stage writes beside the code -- and neither the
    # identifier list above nor the stage-name pattern caught them:
    #   * "No frozen finding asks for a code change." / "The 31 effective
    #     findings of this round (17 F-*, 13 X-*, 1 AU-*)";
    #   * "the pipeline's own ledger/report", "this run", "the decision".
    # The SPELLINGS are quoted from that run's own hand-off records, so they
    # identify the pipeline's vocabulary rather than an author's. `\bthis run\b`
    # is deliberately NOT here: "in this run we used X" is ordinary Methods
    # prose; the self-referential note always says which pass wrote it
    # ("this run's ...", "in this run,"), and the phrases below are the ones the
    # real notes use.
    # "the 31 effective findings of this round" is the pipeline's own count of a
    # review round; "the effective findings were summarized" is ordinary Methods
    # prose, so the COUNT phrase requires the round, and the bare noun phrase is
    # read as a finding id only in the pipeline's `F-012`/`X-907` shapes.
    ("the pipeline's finding ledger (a review round's own item vocabulary)",
     re.compile(r"(?i)\b\d[\d,\s]*\s+(?:effective|frozen|admitted)\s+"
                r"(?:findings?|concerns?)\b"
                r"|\b(?:the|its)\s+(?:effective|frozen|admitted)\s+"
                r"(?:findings?|concerns?)\s+of\s+(?:this|the)\s+round\b"
                r"|\bfindings? of this round\b"
                r"|\b(?:F|X|AU)-\d{2,4}\b")),
    ("a stage note that narrates HOW this package was produced",
     re.compile(r"(?i)\bthe pipeline'?s own (?:ledger|report|bookkeeping|hand-?off)\b"
                r"|\b(?:review|judge|audit|integration|revise|rewrite) session\b"
                r"|\bthis run'?s\b|\bthe decision, with its evidence\b"
                r"|\bwhat the author must do\b")),
)
PACKAGE_TEXT_EXTS = (".md", ".markdown", ".txt", ".tex", ".ltx", ".rst", ".json", ".csv",
                     ".tsv", ".bib", ".html", ".htm", ".xml", ".yml", ".yaml", ".ini",
                     ".cfg", ".log")
PACKAGE_TEXT_BYTES_LIMIT = 2_000_000


# PKG-2: a to-be-submitted file that points at what the submission does not carry
# (the analysis code, the raw data, the review feedback, the author's README
# files) leaves its reader -- the journal, a reviewer, a rebuild -- a reference
# it can never resolve. Two reference SHAPES are reported, because authors write
# both (the second one was the 2026-10-15 gap: a supplementary legend that names
# a script and an archive the submission never carries, with no `code/` path to
# match):
#   * an AREA-PREFIXED path, whose FIRST segment is one of those area names and
#     that is not the tail of a longer path or URL (`https://host/tree/main/code/a.py`
#     is not the author's own `code/`, so the "nothing word-like or `/` before
#     it" guard keeps URLs and longer paths out);
#   * a plain FILE NAME the package carries ONLY inside such an area (or as one
#     of its never-shipped by-products): the name resolves against the package
#     itself, so it is a row exactly when the shipped reader cannot open it.
# A name the package does not carry at all (an external repository's file, a
# producer only the journal has) is NOT this scan's business: only a pointer at
# something the package itself holds outside the submission is.
# The row is a REPORT, never a rewrite and never a failure: the pointer lives in
# the author's prose.


# The extensions a written reference carries. A fixed list, never "any dotted
# token": prose abbreviations ("et al."), figure call-outs ("Fig. 2"), model
# names ("DeepSeek-V4.1-Flash") and DOIs must not read as filenames.
PKG2_NAME_EXTS = (
    "py", "pyi", "ipynb", "r", "rmd", "sh", "bash", "c", "cc", "cpp", "h", "hpp",
    "java", "js", "mjs", "ts", "pl", "jl", "m", "sql",
    "zip", "tar", "tgz", "gz", "bz2", "xz", "7z",
    "csv", "tsv", "txt", "dat", "parquet", "feather",
    "xlsx", "xls", "ods", "json", "jsonl", "ndjson", "yaml", "yml", "toml",
    "ini", "cfg", "conf", "env", "xml", "html", "htm", "css",
    "md", "markdown", "rst", "tex", "ltx", "bib", "bbl", "docx", "doc",
    "pdf", "png", "jpg", "jpeg", "tif", "tiff", "eps", "svg",
    "h5", "hdf5", "npz", "npy", "pkl", "pth", "joblib", "rds",
    "fa", "fasta", "fq", "fastq", "fq.gz", "fastq.gz", "fa.gz", "fasta.gz",
    "csv.gz", "tsv.gz", "tar.gz", "tgz", "bed.gz", "vcf.gz", "bam.gz",
    "bam", "vcf", "bed", "gff", "gtf",
    "out", "log", "lst",
)


def _pkg2_name_pattern():
    """The written-filename token a shipped document may refer by name.

    Parentheses are NOT part of the name class: Word prose writes "(hpep-v07.zip)"
    and an example path's own parentheses must not travel into the reference the
    row names. The lookbehind keeps a URL tail or a longer path out (`/code/a.py`
    is the area pattern's job), the lookahead keeps a longer NAME out
    (`README.md.bak`, `data.csv.gz`), and a one-letter time of day (`9 a.m.`) is
    never a filename.
    """
    ext = "|".join(re.escape(e) for e in sorted(set(PKG2_NAME_EXTS), key=len, reverse=True))
    return re.compile(r"(?<![\w./\\+\-])(?![aApP]\.m(?![A-Za-z])|e\.g|i\.e)"
                      r"(?:[\w.\-+]+[/\\])*[\w\-+]+\.(?:"
                      + ext + r")(?!\w|\.\w)", re.I)


PKG2_NAME_RE = _pkg2_name_pattern()


# A sentence that LOCATES its material elsewhere -- a public repository, a
# deposit, a DOI link, an archive -- resolves for the reader even when this very
# package carries a same-named file outside the submission (a `code/` copy of a
# script the manuscript says is "in the hpep subdirectory of that repository").
# The 2026-10-15 discovery round: without this guard the bare-name rule could
# delete a Methods sentence whose pointer really does resolve.
PKG2_EXTERNAL_LOCATOR_RE = re.compile(
    r"(?i)https?://|www\.|\b(?:github|gitlab|bitbucket|sourceforge|zenodo|figshare|dryad|"
    r"osf\.io|protocols\.io|doi\.org|repositor(?:y|ies)|repo\b|deposit(?:ed|ory)?|"
    r"archived at|available (?:at|from|on)|publicly available|openly available)\b")


def _pkg2_external_locator(text: str, start: int, end: int) -> bool:
    """True when the reference's own SENTENCE points the reader at a locator.

    Sentence-scoped (not line/paragraph-scoped) on purpose: a paragraph may cite
    a work whose embedded `itemData` carries a DOI URL, and that must not excuse
    a pointer in a different sentence.
    """
    mod = _format_module()
    if mod is not None and hasattr(mod, "sentence_spans"):
        try:
            for a, b in mod.sentence_spans(text):
                if a <= start and end <= b:
                    return bool(PKG2_EXTERNAL_LOCATOR_RE.search(text[a:b]))
        except Exception:                                             # noqa: BLE001
            pass
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return bool(PKG2_EXTERNAL_LOCATOR_RE.search(
        text[line_start:line_end if line_end >= 0 else len(text)]))


def _pkg2_name_index(root: Path, area_set: set, is_submitted=None) -> tuple:
    """Which written file names THIS package ships, and which it does not.

    Four lookup structures over one walk (following directory links, like every
    corpus identity walk):
      * `shipped_paths` / `shipped_names` -- the files a submission carries;
      * `absent_paths` / `absent_names` -- the files the package holds but a
        submission does not: everything inside a non-carried area plus the
        never-shipped by-products (a Word owner file, a difference-tracking
        auxiliary, the pipeline's own bookkeeping).
    A name is reported only when it resolves to the second group: a shipped name
    resolves for the reader, and a name the package does not carry at all is not
    a pointer at this package's own material.
    """
    shipped_paths, shipped_names = set(), set()
    absent_paths, absent_names = {}, {}
    _decl, _own_filter = declared_submission_filter(Path(root))
    _is_submitted = is_submitted or _own_filter
    _decl_patterns = tuple(_decl.get("patterns") or ())
    for p in _iter_tree_files(root, follow_dir_links=True):
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:                                             # pragma: no cover
            continue
        top = rel.split("/", 1)[0].lower()
        absent = (top in area_set or is_word_owner_name(p.name)
                  or _is_aux_doc(p.name) or is_bookkeeping_name(p.name))
        if not absent and not _is_submitted(rel):
            # The package's OWN README declares which files are submitted; a file
            # it excludes is not carried by the submission, whatever the
            # pipeline's default area model says (2026-10-15).
            absent = True
        if absent:
            absent_names.setdefault(p.name.lower(), []).append(rel)
            absent_paths.setdefault(rel.lower(), rel)
        else:
            shipped_paths.add(rel.lower())
            shipped_names.add(p.name.lower())
    # The fifth element is the submission declaration the index was built under
    # (empty when the package declares none): the caller's row hint names it, so
    # the author reads WHY a carried file counts as not-submitted.
    return shipped_paths, shipped_names, absent_paths, absent_names, _decl_patterns


def _pkg2_name_resolution(ref: str, index: tuple):
    """(reason, where) for a written file name: "shipped", "absent" or "unknown".

    `ref` is the token as the author wrote it (`jf_supplement_analysis.py`, or a
    relative path). "absent" carries the package-relative path(s) where the file
    actually lives -- the row names them, so the author sees which area the
    reader would have to reach into.
    """
    shipped_paths, shipped_names, absent_paths, absent_names = index[:4]
    key = str(ref or "").strip().replace("\\", "/")
    while key.startswith("./"):
        key = key[2:]
    low = key.lower()
    base = low.rsplit("/", 1)[-1]
    if low in shipped_paths or base in shipped_names:
        return "shipped", []
    if low in absent_paths:
        return "absent", [absent_paths[low]]
    hits = absent_names.get(base) or []
    if hits:
        return "absent", sorted(hits)
    return "unknown", []


def _pkg2_url_query_value(line: str, start: int) -> bool:
    """Is `line[start:]` the value of a URL query/fragment key (not a pointer)?

    `Query: https://example.com/get?file=README.md` names the URL's query
    value, not the author's file; `Build with SRC=code/analysis.py` is a
    pointer the reader cannot resolve. Both are preceded by `=`, so the
    character alone cannot decide -- the token carrying the `=` does (a URL
    token carries `://` or `?` before it).
    """
    i = start - 1
    if i < 0 or line[i] != "=":
        return False
    while i > 0 and not line[i - 1].isspace():
        i -= 1
    token = line[i:start]
    return "://" in token or "?" in token


# PKG-3: a file NAME a to-be-submitted document points at, which this package
# carries NOWHERE. The pointer verb matters: "the custom generators in
# `data3from2.py` are seeded deterministically" (the 2026-10-15 CopyNumBench
# Methods) points the reader at a file; a bare inventory row or a path inside a
# code block does not. `in`/`from`/`by`/`see` are the shapes the operator's
# report used, and the multiword forms below are the explicit "where the
# material lives" spellings. Generic connectors ("with", "as", "at") are NOT
# verbs here: "invoked with a single command: \code{snake.py}" is a command
# line, not a pointer, and matching it turned a benchmark appendix into 30 rows.
PKG3_POINTER_VERB_RE = re.compile(
    r"(?i)\b(?:in|into|inside|from|by|see|produced by|generated by|written by|"
    r"created by|built by|stored in|shipped (?:in|with)|distributed with|provided in|"
    r"recorded in|listed in|contained in|called|named|supplied (?:in|by)|"
    r"available (?:in|from|as)|described in|defined in)\b")
# PKG-3's locator test is STRICTER than PKG-2's: PKG-2 may not delete a sentence
# whose pointer "resolves" in the loose sense ("the deposited code"), while
# PKG-3 only reports -- and "reproducible from the deposited code ... the custom
# generators in data3from2.py" still names a file nobody can resolve. A real
# locator (URL, repository, DOI, accession, a deposit named with its target) is
# what suppresses a PKG-3 row.
PKG3_LOCATOR_RE = re.compile(
    r"(?i)https?://|www\.|\b(?:github|gitlab|bitbucket|sourceforge|zenodo|figshare|dryad|"
    r"osf\.io|protocols\.io|doi\.org|repositor(?:y|ies)|repo\b|deposited (?:at|in|with)|"
    r"archived at|available (?:at|from|on)|accession)\b")


def _sentence_has_locator(line: str, start: int, end: int, pattern) -> bool:
    """True when the SENTENCE of `line` around [start, end) matches `pattern`.

    The same sentence-scoping `_pkg2_external_locator` uses (the formatter's own
    `sentence_spans`, with a `. ` fallback), with the CALLER's pattern: PKG-2
    asks the loose question ("does this sentence locate its material anywhere"),
    PKG-3 the strict one (a URL, a repository, a DOI, an accession).
    """
    mod = _format_module()
    if mod is not None and hasattr(mod, "sentence_spans"):
        try:
            for a, b in mod.sentence_spans(line):
                if a <= start and end <= b:
                    return bool(pattern.search(line[a:b]))
        except Exception:                                             # noqa: BLE001
            pass
    lo = line.rfind(". ", 0, start)
    lo = 0 if lo < 0 else lo + 2
    hi = line.find(". ", end)
    return bool(pattern.search(line[lo:hi if hi >= 0 else len(line)]))


# PKG-3 is scoped to the manuscript PROSE surfaces (the main text, the cover
# letter, a response letter) -- the documents a journal editor follows as prose
# pointers to the authors' own material. A supplementary METHODS appendix that
# inventories a public pipeline's own file layout ("(7) Per-cell evaluation is
# performed by \code{scripts/evaluate_caller_vs_ginkgo.py}") is a description of
# a repository the submission's availability statement names, not a promise to
# ship those files; reporting them turned one benchmark supplement into 11
# advisory rows and diluted the two real pointers the operator found. The
# evidence pack still shows reviewers every PKG-2/PKG-3 row, so the appendix
# names remain reviewable in prose.
PKG3_PROSE_NAME_RE = re.compile(
    r"(?i)(?:main[-_ ]?text|manuscript|cover[-_ ]?letter|response|reply|letter)")


# ---- WHAT THE OPERATOR DECLARES AS SUBMITTED (2026-10-15) -------------------
# A package may carry the operator's own README (`README*.md`, never submitted
# itself) stating the rule for THIS package: "Only files whose names match the
# following Bash extglob pattern will be submitted to the venue/journal:
# `cnb-*-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].@(docx|pdf)`"
# plus "Submitted files must not refer to any non-submitted files."
#
# The pipeline's own model of "the submission" is broader (the corpus minus the
# evidence areas, `code/` and the author's READMEs), so without reading that
# declaration the scans called a `.tex` source, a `.bib` or
# `supplementary_source_files/…` "carried" while the journal never receives
# them -- a dangling pointer the operator explicitly forbids would pass as
# resolvable, and the non-submitted `.tex` sources were scanned as if they were
# submission documents (their own build notes produced rows nobody needed).
#
# The declaration is honoured ONLY when it is plausible (see
# `declared_submission_set`): at least one matching file must exist and at least
# one of them must be a manuscript document. A declaration that matches nothing
# is IGNORED with a reason, never silently applied -- a mis-parsed glob must not
# turn every scan into "clean".
SUBMISSION_DECLARATION_HINT_RE = re.compile(
    r"(?i)(?:will be submitted|are submitted|is submitted|submitted to the\s+"
    r"(?:venue|journal))")


def _extglob_to_regex(pat: str):
    """A bash extglob (`*`, `?`, `[a-f]`, `@(docx|pdf)`) as a regex, or None.

    `*` never crosses a `/` (the patterns name files, and a directory-crossing
    wildcard would silently widen the submitted set).
    """
    out, i, n = [], 0, len(str(pat or ""))
    try:
        while i < n:
            c = pat[i]
            if c == "*":
                out.append("[^/]*")
            elif c == "?":
                out.append("[^/]")
            elif pat.startswith("@(", i):
                j = pat.index(")", i)
                alts = [a for a in pat[i + 2:j].split("|") if a]
                if not alts:
                    return None
                out.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
                i = j
            elif c == "[":
                j = pat.index("]", i)
                cls = pat[i:j + 1]
                if not re.fullmatch(r"\[[^\]\\]{1,40}\]", cls):
                    return None
                if cls[1] in ("!", "^"):
                    body = cls[2:-1]
                    if not body:
                        return None
                    out.append("[^" + body + "]")
                else:
                    out.append(cls)
                i = j
            else:
                out.append(re.escape(c))
            i += 1
    except (ValueError, IndexError):
        return None
    return re.compile("^" + "".join(out) + "$")


MANUSCRIPT_DOC_EXTS = (".docx", ".doc", ".pdf", ".tex", ".ltx", ".md", ".txt")


def declared_submission_set(root: Path) -> dict:
    """The submitted-file set the PACKAGE'S OWN README declares ({} when none).

    Returns {"declared": bool, "patterns": [...], "files": [rel paths],
    "carried_not_submitted": [rel paths], "ignored_reason": str|None,
    "readme": rel path|None}. `files` are package-relative paths matching the
    declared extglob patterns; everything else the package carries is NOT part
    of the submission (the operator's rule), which is what the submission-surface
    scans then use.
    """
    root = Path(root)
    out = {"declared": False, "patterns": [], "files": [], "carried_not_submitted": [],
           "ignored_reason": None, "readme": None}
    if not root.is_dir():
        return out
    # EVERY readme is a candidate, and every declaration contributes. A later
    # `README_SUBMISSION.md` must be able to add a pattern the general README
    # does not mention.
    readmes = []
    try:
        candidates = sorted(p for p in root.iterdir()
                            if p.is_file() and is_non_submitted_readme_name(p.name)
                            and not is_author_to_complete_readme_name(p.name))
    except OSError:
        return out

    def declaration_patterns(text: str) -> list:
        """Globs attached to a "will be submitted" statement.

        Earlier code took every backtick glob in the first matching README, so
        an unrelated example (`fig-*.png`, `*.log`) changed the submitted set.
        Walk the sentence that carries the declaration and the immediately
        following pattern lines; stop at the next prose line. The glob may sit
        before OR after the hint (`Only `ms-*.docx` will be submitted` and
        `The following will be submitted: `ms-*.docx`` are both declarations).
        """
        def globs_in(fragment: str) -> list:
            return [
                token.strip()
                for token_match in re.finditer(r"`([^`\n]{2,200})`", fragment)
                for token in (token_match.group(1),)
                if ("*" in token or "?" in token or "@(" in token)
                and _extglob_to_regex(token.strip()) is not None
            ]

        found = []
        for match in SUBMISSION_DECLARATION_HINT_RE.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            lines = text[line_start:].splitlines()[:24]
            if not lines:
                continue
            first = lines[0]
            local_start = match.start() - line_start
            # A pattern's own dot (`ms-*.docx`) is inside backticks and is not
            # the end of the declaration sentence.
            in_quote = [False] * len(first)
            quoted = False
            for pos, char in enumerate(first):
                in_quote[pos] = quoted
                if char == "`":
                    quoted = not quoted
            sent_start = max(
                [pos for pos in range(local_start)
                 if not in_quote[pos] and first[pos] in ".!?"] or [-1]) + 1
            sent_end_candidates = [
                pos for pos in range(local_start, len(first))
                if not in_quote[pos] and first[pos] in ".!?"
            ]
            sent_end = min(sent_end_candidates) if sent_end_candidates else len(first)
            found.extend(globs_in(first[sent_start:sent_end]))
            # The patterns may sit in a code block / next paragraph after a short
            # lead-in ("... will be submitted to the venue/journal:"). Allow a
            # bounded lead-in before the first glob, then stop at the first prose
            # line AFTER a glob (an unrelated example must not widen the set).
            seen_glob = bool(found)
            lead = 0
            for raw in lines[1:]:
                line = raw.strip()
                globs = globs_in(line)
                if globs:
                    seen_glob = True
                    found.extend(globs)
                    continue
                if not line or re.fullmatch(r"(?:or|and)[.:]?", line, re.I):
                    continue
                if not seen_glob and lead < 3 and (
                        line.endswith(":") or line.endswith(".") or line.endswith("/")):
                    lead += 1
                    continue
                if not seen_glob and lead < 3 and not ("`" in line):
                    lead += 1
                    continue
                break
        return found

    patterns = []
    hint_readmes = []
    for p in candidates:
        try:
            candidate_text = p.read_text("utf-8", "replace")
        except OSError:
            continue
        if SUBMISSION_DECLARATION_HINT_RE.search(candidate_text):
            hint_readmes.append(p)
        found = declaration_patterns(candidate_text)
        if found:
            if p not in readmes:
                readmes.append(p)
            for token in found:
                if token not in patterns:
                    patterns.append(token)
    if not readmes:
        if hint_readmes:
            out["readme"] = hint_readmes[0].relative_to(root).as_posix()
            out["readmes"] = [p.relative_to(root).as_posix() for p in hint_readmes]
            out["ignored_reason"] = (
                f"{out['readme']} names a submission rule but carries no parseable pattern")
        return out
    out["readme"] = readmes[0].relative_to(root).as_posix()
    out["readmes"] = [p.relative_to(root).as_posix() for p in readmes]
    if not patterns:
        out["ignored_reason"] = (f"{out['readme']} names a submission rule but carries no "
                                 f"parseable pattern")
        return out
    res = [_extglob_to_regex(p) for p in patterns]
    carried, declared = [], []
    for q in sorted(root.rglob("*")):
        if not q.is_file():
            continue
        rel = q.relative_to(root).as_posix()
        base = rel.rsplit("/", 1)[-1]
        if any(rx.match(rel) or rx.match(base) for rx in res):
            declared.append(rel)
        else:
            carried.append(rel)
    if not declared:
        out["ignored_reason"] = (f"the declared pattern(s) {patterns} match no file in the "
                                 f"package")
        out["patterns"] = patterns
        return out
    if not any(Path(f).suffix.lower() in MANUSCRIPT_DOC_EXTS for f in declared):
        out["ignored_reason"] = (f"the declared pattern(s) {patterns} match no manuscript "
                                 f"document ({len(declared)} file(s) matched)")
        out["patterns"] = patterns
        return out
    out.update(declared=True, patterns=patterns, files=declared,
               carried_not_submitted=carried)
    return out


def declared_submission_filter(root: Path):
    """(declared record, `is_submitted(rel) -> bool`) for the scans.

    When no declaration is honoured, every carried file counts as submitted
    (the pipeline's own model, unchanged). When one is, ONLY the declared files
    do -- and the scans skip the other carried files as documents, exactly like
    the author's READMEs and the `code/` area.
    """
    decl = declared_submission_set(Path(root))
    if not decl.get("declared"):
        return decl, (lambda rel: True)
    allowed = {str(f) for f in decl.get("files") or []}
    return decl, (lambda rel: str(rel) in allowed)


# ---- duplicate submission roles (2026-10-17) --------------------------------
# The NeoHeteroclitic `neohet-to17` package carried BOTH the revised family
# `neohetero-18-2-mainText-9915d6e.docx` / `...supplementaryMaterial-9915d6e.docx`
# and the old pre-revision family
# `neohetero-18-2-mainText-FrontiersTemplate-zotero-bbb4e84.docx` /
# `...supplementaryMaterial-FrontiersTemplate-zotero-bbb4e84.docx`. Both
# families matched the package README's submitted-set glob, so the journal would
# receive two different main texts and two different supplementary documents.
# The revision-token check catches the two-token form at stage time; this
# publication-side check also covers legacy names and names whose token alone
# does not reveal the role.
DUP_ROLE_DOC_EXTS = (".doc", ".docx", ".pdf", ".tex", ".ltx", ".md", ".txt")
DUP_ROLE_VERSION_RE = re.compile(r"(?:[-_][0-9a-f]{7}|[-_][vV]\d+)$")
DUP_ROLE_PROVENANCE_SUFFIX_RE = DOC_PROVENANCE_SUFFIX_RE


def _duplicate_role_key(name: str) -> str:
    """A document role key with only package/copy provenance removed.

    A one-letter suffix is a real document label (`panel-a`, `panel-b`), and
    words such as `revised`, `original` and `final` can name two documents a
    package must ship together. Removing them invented duplicate roles.
    """
    stem = Path(str(name)).stem.lower()
    stem = DUP_ROLE_VERSION_RE.sub("", stem)
    prev = None
    while prev != stem:
        prev = stem
        stem = DUP_ROLE_PROVENANCE_SUFFIX_RE.sub("", stem)
    return re.sub(r"[-_.]+", "-", stem).strip("-")


def duplicate_submission_role_rows(root: Path, limit: int = 20) -> list:
    """PKG-26: one submitted document role carried by more than one file.

    The check is scoped to the package's own submitted set (or the pipeline's
    standing model when no declaration is honoured), so a source PDF beside a
    DOCX, a figure asset, a non-submitted README or a bookkeeping file is not a
    row. Same-extension files whose role keys collide are a real packaging
    defect: the reader cannot tell which is the current document, and a journal
    upload carries both.
    """
    root = Path(root)
    rows = []
    if not root.is_dir():
        return rows
    _decl, is_submitted = declared_submission_filter(root)
    groups = {}
    for p in sorted(_iter_tree_files(root, follow_dir_links=True)):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if not is_submitted(rel):
            continue
        if is_evidence_rel(rel) or is_code_rel(rel):
            continue
        if p.suffix.lower() not in DUP_ROLE_DOC_EXTS:
            continue
        if is_bookkeeping_name(p.name) or _is_aux_doc(p.name) \
                or is_non_submitted_readme_name(p.name):
            continue
        key = _duplicate_role_key(p.name)
        if not key:
            continue
        groups.setdefault((Path(rel).parent.as_posix(), key, p.suffix.lower()), []).append(rel)
    for (parent, key, ext), files in sorted(groups.items()):
        if len(files) < 2:
            continue
        rows.append({
            "rule": "PKG-26", "severity": "high", "fix": "manual",
            "file": files[0], "reference": ", ".join(files[1:]),
            "detail": (f"the submitted set carries {len(files)} {ext} files for one "
                       f"document role ({key!r}) in {parent!r}: {', '.join(files)}. One is a stale "
                       f"pre-revision/source copy; the reader cannot tell which is current, "
                       f"and a journal upload carries both. Keep the current version and "
                       f"remove or rename the stale copy out of the submitted set.")})
        if len(rows) >= limit:
            break
    return rows


# ---- Placeholder FILES (2026-10-17) ----------------------------------------
# A corpus can carry a file that stands in for data it does not contain: the
# operator's 2026-10-17 note names the example, "the haplotypes in Chisel ACT are
# actually the HG008 haplotypes (placeholders)". Such a file is not evidence, and
# a role that read it as a producer would "verify" a claim against another
# sample's data. The rule is therefore: PLACEHOLDER FILES ARE IGNORED.
#
# Two independent ways to know a file is a placeholder, because neither alone
# can see every case:
#   * DECLARED -- the operator names it (`--placeholder-file GLOB` at setup /
#     `set-placeholder-file`, or a line in the package's own README:
#     "Placeholder files: `raw_data/...`"). A declaration is authoritative.
#   * DETECTED -- two files inside the evidence areas have IDENTICAL BYTES under
#     different sample/dataset names, and at least one of them is the kind of
#     input that is copied between samples (a haplotype, phasing, variant, SNP,
#     VCF or BAM file, or a name carrying placeholder/dummy/stub). One of the two
#     labels does not describe the content, so neither may be used as proof.
#
# Ignored means: the file is listed in the evidence pack under
# "Placeholder files -- ignored", it is never a producer or source for a claim,
# and a finding whose only evidence is one is not a finding. It is NOT deleted
# and NOT hidden: the row says which file it duplicates, so the author can
# rename, remove or confirm it.
PLACEHOLDER_NAME_RE = re.compile(
    r"(?i)(?:^|[^a-z])(?:placeholder|dummy|stub|fake|toy)(?:[^a-z]|$)")
PLACEHOLDER_INPUT_RE = re.compile(
    r"(?i)(?:^|[^a-z])(?:hap|haps|haplotype|phased|phasing|phase|variant|variants|"
    r"snp|snps|allele|alleles|vcf|bam|fasta|fa)(?:[^a-z]|$)")
PLACEHOLDER_DECL_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:placeholder[ \t]+files?|placeholders?)[ \t]*[:=][ \t]*(.+)$")
PLACEHOLDER_BULLET_RE = re.compile(r"(?im)^[ \t]*(?:[-*+]|\d+\.)[ \t]+(.+)$")
BACKTICK_TOKEN_RE = re.compile(r"`([^`\n]{2,300})`")
PLACEHOLDER_MAX_HASH_BYTES = 20 * 1024 * 1024


def _placeholder_globs_from_ctx(ctx=None) -> list:
    """The `placeholder_files` config key (the operator's explicit declarations)."""
    raw = ((getattr(ctx, "cfg", None) if ctx is not None else None) or {}).get(
        "placeholder_files") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x).strip() for x in raw if str(x).strip()]


def declared_placeholder_paths(root: Path, extra=()) -> dict:
    """The placeholders a package DECLARES: {patterns, files, readme, reasons}.

    Sources, in order: the `placeholder_files` config key (the
    `--placeholder-file` / `set-placeholder-file` spelling), a README line
    "Placeholder files: ...", and a README bullet that names a backticked path
    together with the word placeholder. Glob patterns (`*`, `?`, `[...]`) are
    matched against the package-relative path and the bare file name.
    """
    root = Path(root)
    out = {"patterns": [], "files": [], "readme": None, "reasons": {}}
    patterns = list(extra or ())
    if not root.is_dir():
        return out
    try:
        candidates = sorted(p for p in root.iterdir()
                            if p.is_file() and is_non_submitted_readme_name(p.name)
                            and not is_author_to_complete_readme_name(p.name))
    except OSError:
        candidates = []
    for p in candidates:
        try:
            text = p.read_text("utf-8", "replace")
        except OSError:
            continue
        found = False
        for m in PLACEHOLDER_DECL_LINE_RE.finditer(text):
            toks = BACKTICK_TOKEN_RE.findall(m.group(1)) or [
                t.strip() for t in re.split(r"[,;]", m.group(1))]
            for tok in toks:
                if tok.strip():
                    patterns.append(tok.strip())
                    found = True
        for m in PLACEHOLDER_BULLET_RE.finditer(text):
            line = m.group(1)
            if not re.search(r"(?i)\bplaceholders?\b", line):
                continue
            for tok in BACKTICK_TOKEN_RE.findall(line):
                if "/" in tok or "." in tok.rsplit("/", 1)[-1]:
                    patterns.append(tok)
                    found = True
        if found and out["readme"] is None:
            out["readme"] = p.relative_to(root).as_posix()
    seen, uniq = set(), []
    for pat in patterns:
        key = str(pat).strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(key)
    out["patterns"] = uniq
    for p in sorted(_iter_tree_files(root)):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        base = Path(rel).name
        for pat in uniq:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(base, pat):
                out["files"].append(rel)
                out["reasons"][rel] = f"declared by the operator (`{pat}`)"
                break
    return out


def _placeholder_subject_tokens(rel: str) -> set:
    """Name tokens that distinguish one sample/dataset file from another."""
    stem = str(rel).replace("\\", "/").rsplit("/", 1)[-1].lower()
    tokens = set(re.split(r"[^a-z0-9]+", stem))
    tokens.discard("")
    stop = {
        "tsv", "csv", "txt", "json", "gz", "tex", "pdf", "png", "jpg", "jpeg", "md",
        "data", "table", "tables", "source", "sources", "summary", "full", "brief",
        "all", "positions", "position", "pos", "from", "per", "and", "the", "of",
        "step", "result", "results", "stats", "out", "output", "input", "raw",
    }
    return {t for t in tokens if t not in stop and len(t) > 1}


def detect_placeholder_copies(root: Path, area_names=None,
                              max_bytes: int = PLACEHOLDER_MAX_HASH_BYTES) -> list:
    """Evidence-area files with identical bytes under different sample labels.

    See the block above: a duplicate under a DIFFERENT subject token, where at
    least one side is a haplotype/variant-style input or carries a
    placeholder/dummy name, is a placeholder copy -- one of the two labels does
    not describe the content. Only the evidence areas are walked (the submitted
    documents' own duplicate media are normal), and only files below `max_bytes`
    are hashed.
    """
    root = Path(root)
    names = {str(a).strip().lower() for a in (area_names or ()) if str(a).strip()}
    if not names or not root.is_dir():
        return []
    groups = {}
    # Size first: a byte-identical copy has the same size, so only files whose
    # size collides with another file's are worth hashing. A corpus with a few
    # hundred distinct evidence files pays almost no hashing cost.
    by_size = {}
    for p in _iter_tree_files(root):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel.split("/", 1)[0].lower() not in names:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if not st.st_size or st.st_size > max_bytes:
            continue
        by_size.setdefault(st.st_size, []).append((p, rel))
    for size, entries in by_size.items():
        if len(entries) < 2:
            continue
        for p, rel in entries:
            try:
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                continue
            groups.setdefault(digest, []).append(rel)
    rows = []
    for digest, paths in sorted(groups.items()):
        if len(paths) < 2:
            continue
        paths = sorted(paths)
        tokens = {rel: _placeholder_subject_tokens(rel) for rel in paths}
        interesting = any(PLACEHOLDER_INPUT_RE.search(rel) or PLACEHOLDER_NAME_RE.search(rel)
                          for rel in paths)
        if not interesting:
            continue
        canonical = paths[0]
        for rel in paths[1:]:
            if tokens[rel] == tokens[canonical]:
                # Same subject tokens, just another spelling of the same name
                # (`_from-table1` vs `-from-table1`): an alias, not a placeholder.
                continue
            rows.append({
                "file": rel, "duplicates": canonical, "digest": digest,
                "sample_tokens": sorted(tokens[rel]),
                "duplicate_sample_tokens": sorted(tokens[canonical]),
                "reason": ("identical bytes under a different sample/dataset name; one of "
                           "the two labels does not describe the content"),
            })
    return rows


def placeholder_files_report(root: Path, extra_globs=(), area_names=None) -> dict:
    """{declared, detected_copies, ignored, reasons} -- one report per package."""
    decl = declared_placeholder_paths(root, extra=extra_globs)
    detected = detect_placeholder_copies(
        root, area_names if area_names is not None else submission_not_carried_areas_plain())
    declared = set(decl["files"])
    ignored_for_row = {}
    for r in detected:
        pair = [r["file"], r["duplicates"]]
        # A declaration identifies the placeholder side. Without one, neither
        # label can be trusted as the real data: ignoring the alphabetically
        # later path silently kept the placeholder and discarded the original.
        if r["file"] in declared and r["duplicates"] not in declared:
            row_ignored = [r["file"]]
        elif r["duplicates"] in declared and r["file"] not in declared:
            row_ignored = [r["duplicates"]]
        else:
            marked = [rel for rel in pair if PLACEHOLDER_NAME_RE.search(rel)]
            row_ignored = marked if len(marked) == 1 else pair
        r["ignored"] = r["file"] in row_ignored
        r["ignored_files"] = sorted(set(row_ignored))
        ignored_for_row[r["file"]] = row_ignored
    ignored = sorted(declared | {
        rel for row_ignored in ignored_for_row.values() for rel in row_ignored})
    reasons = dict(decl["reasons"])
    for r in detected:
        for rel in r["ignored_files"]:
            other = r["duplicates"] if rel == r["file"] else r["file"]
            if len(r["ignored_files"]) == len(pair):
                outcome = ("both copies are unavailable as evidence until a declaration "
                           "identifies which side is real")
            elif rel in declared:
                outcome = "the operator declared this side to be the placeholder"
            else:
                outcome = "this name identifies it as the placeholder side"
            reasons.setdefault(
                rel,
                f"placeholder copy: {r['reason']} (it duplicates {other}); "
                f"{outcome}",
            )
        kept = [rel for rel in (r["file"], r["duplicates"])
                if rel not in r["ignored_files"]]
        for rel in kept:
            reasons.setdefault(
                rel, f"real-data partner of the placeholder {r['ignored_files'][0]}")
    return {"declared_patterns": decl["patterns"], "declared": decl["files"],
            "readme": decl["readme"], "detected_copies": detected,
            "ignored": ignored, "reasons": reasons}


def _pkg3_prose_document(rel: str) -> bool:
    """True when `rel` is a manuscript prose surface PKG-3 reports (see above)."""
    name = str(rel or "")
    base = name.rsplit("/", 1)[-1]
    if not name.lower().endswith((".docx", ".tex", ".ltx", ".pdf")):
        return False
    role = docx_document_role(base)
    if role in ("main", "cover"):
        return True
    return bool(PKG3_PROSE_NAME_RE.search(base))


# ---- PKG-10: what an evidence area's files may be referenced for (2026-10-17) ---
# The operator's rule for these packages, verbatim:
#
#   "All files in `raw_data` and other such directories (other than figures,
#    tables, and files that are inputted (including nested inputted or
#    recursively inputted) to .tex files in the parent directory of `raw_data`)
#    cannot be referenced by the main manuscript."
#
# and the same package's own README states the positive half: "Files that are
# inputted (recursive nested input included) to .tex files in the parent
# directory of `raw_data` are treated as if they are in the parent."
#
# So a submitted document that sends the reader to a file inside a non-carried
# area is a defect UNLESS that file is one of:
#   * a parent-directory file (the .tex sources beside the area -- what they
#     compile into IS what the reader receives, e.g. the supplementary PDF);
#   * a file a .tex file in that parent directory INPUTS, directly or through
#     nested inputs: `\input`/`\include`/`\includegraphics`/`\includepdf`/
#     `\addbibresource`/`\bibliography`/`\pgfplotstableread`/`\lstinputlisting`/
#     `\subfile`/`\import` -- the recursive "treated as in the parent" closure,
#     which is what makes a supplementary table's own source file referenceable;
#   * a FIGURE or TABLE whose content the submission itself carries: a figure
#     file whose bytes are embedded in a submitted document (the CopyNumBench
#     main text displays `raw_data/Fig3_ploidy_balloons.png` byte for byte), or
#     a display table the parent .tex typesets (the closure above).
#
# The row is a REPORT, never a mechanical edit: the reference becomes legitimate
# once the author ships the file, and deleting the sentence would destroy the
# information that the material exists. The operator's rule is categorical, so
# the row reaches the readiness list rather than the advisory tail.
TEX_INPUT_COMMANDS = (
    "input", "include", "includegraphics", "includepdf", "addbibresource",
    "bibliography", "pgfplotstableread", "pgfplotstabletypeset", "lstinputlisting",
    "subfile", "subfileinclude",
)
# `\import{dir}{file}` and `\subimport{dir}{file}` carry TWO arguments and the
# path is their JOIN. `\inputminted{lang}{file}` and `\DTLloaddb{name}{file}`
# also carry two, but only the SECOND is a path (the first is a language or a
# database name), so they are read separately.
TEX_TWO_ARG_COMMANDS = ("import", "subimport", "includefrom", "inputfrom")
TEX_SECOND_ARG_COMMANDS = ("inputminted", "DTLloaddb", "DTLloadrawdb")
TEX_INPUT_MAX_DEPTH = 6
FIGURE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".eps",
               ".svg", ".emf", ".wmf", ".ps")
TABLE_EXTS = (".tsv", ".csv", ".tab", ".xlsx", ".xls", ".ods", ".parquet")


def _tex_strip_comments(text: str) -> str:
    """LaTeX source without its comments (a commented-out \\input is not an input)."""
    out = []
    for line in str(text or "").splitlines():
        cut = None
        for i, ch in enumerate(line):
            if ch == "%" and (i == 0 or line[i - 1] != "\\"):
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def tex_input_targets(text: str) -> list:
    """Every path a LaTeX source reads, as written (see TEX_INPUT_COMMANDS)."""
    body = _tex_strip_comments(text)
    targets = []
    one = re.compile(r"\\(" + "|".join(re.escape(c) for c in TEX_INPUT_COMMANDS)
                     + r")\*?\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}", re.I)
    for m in one.finditer(body):
        raw = m.group(2).strip()
        if m.group(1).lower() == "bibliography":
            for part in raw.split(","):
                if part.strip():
                    targets.append(part.strip())
        elif raw:
            targets.append(raw)
    two = re.compile(r"\\(" + "|".join(re.escape(c) for c in TEX_TWO_ARG_COMMANDS)
                     + r")\*?\s*\{([^{}]*)\}\s*\{([^{}]*)\}", re.I)
    for m in two.finditer(body):
        joined = (m.group(2).strip().rstrip("/") + "/" + m.group(3).strip()).lstrip("/")
        if m.group(3).strip():
            targets.append(joined)
    second = re.compile(r"\\(" + "|".join(re.escape(c) for c in TEX_SECOND_ARG_COMMANDS)
                        + r")\*?\s*\{[^{}]*\}\s*\{([^{}]*)\}", re.I)
    for m in second.finditer(body):
        if m.group(2).strip():
            targets.append(m.group(2).strip())
    return targets


def _tex_target_candidates(target: str) -> list:
    """A written target's plausible file names (LaTeX omits extensions)."""
    # Escaped underscores first (`supp\_figs/x.pdf`), THEN the path separator:
    # the reverse order would turn `\_` into `/_` and lose the file.
    t = str(target or "").strip().replace("\\_", "_").replace("\\", "/")
    t = re.sub(r"\\detokenize\s*\{([^{}]*)\}", r"\1", t).strip("{} ")
    if not t or t.startswith("/") or re.match(r"^[A-Za-z]:", t):
        return []
    out = [t]
    if not Path(t).suffix:
        for ext in (".tex", ".pdf", ".png", ".jpg", ".tsv", ".csv", ".bib", ".ltx"):
            out.append(t + ext)
    if t.endswith(".tex"):
        out.append(t[:-4])
    return out


def tex_input_closure(root: Path, area_names, depths: int = TEX_INPUT_MAX_DEPTH) -> tuple:
    """(closure, sources) -- the files the parent-directory .tex files pull in.

    The closure is the operator's "treated as if they are in the parent" set: the
    files directly inside the area's parent directory (whichever directory of the
    package carries an area with that name), plus every file the .tex files THERE
    input, transitively. Paths are package-relative, `/`-separated and lowercased
    (a bare basename is added too, so a reference written as a bare name still
    matches); the second element lists the .tex sources the closure was built
    from, so a row can say WHY a file counts as carried.
    """
    root = Path(root)
    names = {str(a).strip().lower() for a in (area_names or ()) if str(a).strip()}
    closure, sources, dirs = set(), [], set()
    if not names:
        return closure, sources
    for p in root.rglob("*"):
        try:
            if p.is_dir() and p.name.lower() in names:
                dirs.add(p.parent)
        except OSError:
            continue
    for d in sorted(dirs):
        for tex in sorted(d.glob("*.tex")):
            sources.append(tex.relative_to(root).as_posix())
            # The parent directory's .tex SOURCES are the things whose inputs are
            # "treated as if they are in the parent"; an arbitrary sibling (a
            # README, a stray archive) is NOT carried just because it sits there
            # (the PKG-2 scan already treats a README as never-submitted).
            try:
                closure.add(tex.relative_to(root).as_posix().lower())
            except ValueError:
                continue
    seen_tex, pending, depth = set(), [Path(root) / s for s in sources], 0
    while pending and depth < depths:
        nxt = []
        for tex in pending:
            key = str(tex)
            if key in seen_tex:
                continue
            seen_tex.add(key)
            try:
                text = tex.read_text("utf-8", "replace")
            except OSError:
                continue
            for target in tex_input_targets(text):
                for cand in _tex_target_candidates(target):
                    cand_path = (tex.parent / cand)
                    try:
                        resolved = cand_path.resolve()
                        rel = resolved.relative_to(root.resolve()).as_posix()
                    except (OSError, ValueError):
                        continue
                    if not resolved.is_file():
                        continue
                    closure.add(rel.lower())
                    closure.add(Path(rel).name.lower())
                    if resolved.suffix.lower() == ".tex":
                        nxt.append(resolved)
        pending = nxt
        depth += 1
    return closure, sources


def embedded_media_digests(root: Path, rel_files) -> dict:
    """{sha256 hex: [<rel file>::<part>, ...]} for submitted OOXML media parts.

    A figure whose bytes appear inside a submitted document IS part of the
    submission (the reader sees it as the figure), whatever the file it came from
    is called, so a reference to that very file is not a dangling pointer. The
    CopyNumBench case: `raw_data/Fig3_ploidy_balloons.png` is byte-identical to
    `word/media/image3.png` of the submitted main text.
    """
    out = {}
    for rel in rel_files or ():
        p = Path(root) / rel
        if p.suffix.lower() not in (".docx", ".docm", ".dotx", ".pptx", ".xlsx"):
            continue
        try:
            with zipfile.ZipFile(p) as z:
                for name in z.namelist():
                    if name.endswith("/") or not name.startswith(
                            ("word/media/", "ppt/media/", "xl/media/")):
                        continue
                    out.setdefault(hashlib.sha256(z.read(name)).hexdigest(), []).append(
                        f"{rel}::{name}")
        except (OSError, zipfile.BadZipFile, RuntimeError):
            continue
    return out


def area_reference_exceptions(root: Path, areas, submitted_files) -> dict:
    """The PKG-10 exception set for one package (see the block above)."""
    closure, tex_sources = tex_input_closure(root, areas)
    media = embedded_media_digests(root, submitted_files)
    return {"closure": closure, "tex_sources": tex_sources, "media": media}


def pkg10_reference_exempt(root: Path, target: str, exc: dict) -> tuple:
    """(exempt?, reason) for a written reference that resolves inside an area."""
    cands = [k for k in _tex_target_candidates(target) if k]
    if any(k.lower() in (exc or {}).get("closure", ()) for k in cands):
        return True, "a .tex file in the area's parent directory inputs it"
    for cand in cands:
        p = Path(root) / cand.replace("\\", "/")
        try:
            if not p.is_file():
                continue
            digest = _cached_sha256(p)
        except OSError:
            continue
        where = ((exc or {}).get("media") or {}).get(digest)
        if where:
            return True, (f"its bytes are embedded in the submitted document "
                          f"{where[0].split('::')[0]} (the reader sees this display item)")
    return False, ""


_FILE_DIGEST_CACHE = {}


def _cached_sha256(p: Path) -> str:
    """sha256 of a file, cached by (path, mtime_ns, size) -- one scan reads each
    referenced figure/table once even when several sentences name it."""
    try:
        st = p.stat()
    except OSError:
        raise
    key = (str(p), st.st_mtime_ns, st.st_size)
    hit = _FILE_DIGEST_CACHE.get(key)
    if hit is not None:
        return hit
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    if len(_FILE_DIGEST_CACHE) > 512:
        _FILE_DIGEST_CACHE.clear()
    _FILE_DIGEST_CACHE[key] = digest
    return digest


# ---- Three package self-consistency scans added after the 2026-10-17 audit ----
# PKG-11: a table header that differs from its sibling tables' header only by
#   case or one character. The NeoHeteroclitic package lost a whole antigen
#   (Zhou et al., 20 peptides, 2 positives) because one file spelled
#   `MixMHCPred_aff` where the other 26 spelled `MixMHCpred_aff`, and the
#   aggregation script skipped any table lacking all twelve columns WITHOUT
#   naming it -- a one-letter header silently dropped a study and changed a
#   headline ("no PWM-derived value falls below 0.50 on any antigen").
# PKG-12: a statistics table whose own two significance columns disagree under
#   the rule its caption states. The CopyNumBench MCB table prints, for
#   AneuFinder on Hap_1 nonintCN_PCC, p = 0.115 beside a 95% interval of
#   [-0.51, -0.02]; the caption says a small p AND an interval entirely below 0
#   both mean "significantly inferior", so the row says both things at once.
# PKG-14: a cover letter that says the work is not under consideration
#   elsewhere / lists no related manuscript while the package itself carries a
#   dated editorial decision for the same title (the iScience submission of
#   2026-09-29 in the NeoHeteroclitic package).
TABLE_TEXT_EXTS = (".tsv", ".csv", ".tab")
NEAR_MISS_MIN_LEN = 6
NEAR_MISS_RATIO = 0.90
MCB_P_SMALL_RULE_RE = re.compile(
    r"(?i)(?:small\s+\$?p\$?|p\s*(?:<|≤|<=)\s*(?:0?\.05|alpha)|small(?:er)?\s+(?:p|P)\b)")
MCB_CI_RULE_RE = re.compile(
    r"(?i)(?:entirely\s+below\s+0|interval[^.]{0,60}below\s+0|CI[^.]{0,40}below\s+0|"
    r"exclu(?:de|ding|des|sion)[^.]{0,20}\b0)")
PRIOR_SUBMISSION_CLAIM_RE = re.compile(
    r"(?i)(?:related\s+manuscripts?\s*[:：]\s*none|not\s+under\s+consideration\s+elsewhere|"
    r"has\s+not\s+been\s+(?:published|submitted)\s+previously)")
PRIOR_DECISION_ID_RE = re.compile(r"\b([A-Za-z][A-Za-z ]{2,28})-([A-Z])-(\d{2})-(\d{4,8})\b")
PRIOR_TITLE_STOPWORDS = frozenset(
    "editorial decision thank you paper manuscript submission submitted journal article "
    "review reviewers reviewer editor editors comments response revision revised dear "
    "please find attached following".split())


def _title_words(text: str) -> set:
    """Comparable content words for a title-overlap guard (>= 6 letters)."""
    return {w for w in re.findall(r"[a-z]{6,}", str(text or "").lower())
            if w not in PRIOR_TITLE_STOPWORDS}


def _same_work(a: str, b: str, minimum: int = 3) -> bool:
    """True when two texts share enough of a title to be the same work.

    The guard keeps an unrelated decision letter that a co-author left in the
    feedback area from being reported as this cover letter's undisclosed prior
    submission. A short forwarded note cannot establish identity, and two
    generic domain words ("cancer patients") are not a title match.
    """
    wa, wb = _title_words(a), _title_words(b)
    if len(wa) < minimum or len(wb) < minimum:
        return False
    shared = wa & wb
    return len(shared) >= minimum and len(shared) / min(len(wa), len(wb)) >= 0.4


def _read_delimited_table(path: Path, max_bytes: int = 8 * 1024 * 1024):
    """(header, rows) of a small .tsv/.csv, or (None, []) when unreadable."""
    try:
        if path.stat().st_size > max_bytes:
            return None, []
        text = path.read_text("utf-8", "replace")
    except OSError:
        return None, []
    sample = text[:4096]
    delim = "\t" if path.suffix.lower() in (".tsv", ".tab") else \
        ("," if sample.count(",") >= sample.count("\t") else "\t")
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    except csv.Error:
        return None, []
    if not rows:
        return None, []
    return rows[0], rows[1:]


def _norm_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def scan_column_name_near_misses(root: Path, limit: int = 24) -> list:
    """PKG-11: sibling tables whose header names differ only by case/one char."""
    root = Path(root)
    headers = []
    for p in sorted(_iter_tree_files(root)):
        if not p.is_file() or p.suffix.lower() not in TABLE_TEXT_EXTS:
            continue
        header, body = _read_delimited_table(p)
        if not header or len(body) < 2:
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        headers.append((rel, [str(x).strip() for x in header]))
    # Every distinct spelling of one normalized name, with the files carrying it.
    spellings = {}
    for rel, header in headers:
        parent = Path(rel).parent.as_posix()
        for name in header:
            norm = _norm_header(name)
            if len(norm) < NEAR_MISS_MIN_LEN:
                continue
            spellings.setdefault(parent, {}).setdefault(norm, {}) \
                .setdefault(name, set()).add(rel)
    rows = []
    for _parent, by_norm in sorted(spellings.items()):
        for norm, variants in sorted(by_norm.items()):
            if len(variants) < 2:
                continue
            names = sorted(variants)
            # Pair each spelling with its nearest other spelling in the SAME
            # directory. Tables in unrelated directories are not a family, and
            # ordinary header capitalization there is not a silent join.
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    ratio = difflib.SequenceMatcher(None, a, b).ratio()
                    if a == b or (a.lower() != b.lower() and ratio < NEAR_MISS_RATIO):
                        continue
                    if variants[a] == variants[b]:
                        continue
                    fa = sorted(variants[a])[0]
                    fb = sorted(variants[b])[0]
                    rows.append({
                        "rule": "PKG-11", "severity": "medium", "fix": "manual",
                        "file": fa, "line": 1, "reference": a,
                        "detail": (f"these sibling tables spell one column differently: {a!r} in "
                                   f"{fa} but {b!r} in {fb}. A consumer that requires the exact "
                                   f"header name therefore drops one of them silently (the "
                                   f"2026-10-17 audit: a `MixMHCPred_aff`/`MixMHCpred_aff` "
                                   f"difference can silently exclude a whole antigen from the "
                                   f"aggregation and change a headline). Rename the odd header to "
                                   f"the family's own spelling, or make the consumer accept both "
                                   f"and REPORT every skipped input"),
                        "counterpart": {"file": fb, "column": b},
                    })
                    if len(rows) >= limit:
                        return rows
    return rows


def _parse_ci(cell: str):
    """(low, high) from `[-0.51, -0.02]`, or None."""
    # U+2212 (the typographic minus a PDF export emits) is a minus sign here.
    text = str(cell).replace("\u2212", "-")
    m = re.match(r"^\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]\s*$", text)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _parse_p(cell: str):
    t = re.sub(r"\\textbf\{|\\emph\{|\}", "", str(cell or "")).strip()
    t = re.sub(r"^\$?(?:p|P)?\$?\s*(?:=|<=|>=|<|>|≤|≥)?\s*", "", t)
    t = t.strip("$ ").rstrip("*")
    try:
        return float(t)
    except ValueError:
        return None


def _p_reports_significant(cell: str, parsed=None) -> bool:
    """Whether a p-value CELL states significance (star or inequality aware)."""
    text = re.sub(r"\\textbf\{|\\emph\{|\}", "", str(cell or "")).strip()
    if re.search(r"\*+\s*\$?\s*$", text):
        return True
    if re.search(r"(?:<|≤|<=)\s*\$?\s*\d", text):
        return True
    if re.search(r"(?:>|≥|>=)\s*\$?\s*\d", text):
        return False
    value = _parse_p(text) if parsed is None else parsed
    return value is not None and value <= 0.05


def _latex_command_bodies(text: str, command: str) -> list:
    """The balanced `{...}` bodies of every `\\command{...}` (nested braces kept).

    A caption is not brace-free (`\\qty{95}{\\percent}`), so the regex
    `\\caption\\{([^{}]*)\\}` stops at the first nested brace and can cut the
    sentence that states the very rule the scan is checking.
    """
    out = []
    needle = "\\" + command
    i = 0
    while True:
        j = text.find(needle, i)
        if j < 0:
            break
        k = j + len(needle)
        while k < len(text) and text[k] in " \t*":
            k += 1
        # `\captionof{table}{...}`: skip the first brace group, keep the second.
        groups, pos = [], k
        for _ in range(2):
            while pos < len(text) and text[pos] in " \t\n":
                pos += 1
            # \caption[short]{long}: the optional short title sits between the
            # command and the body; requiring `{` here read no body at all.
            if pos < len(text) and text[pos] == "[":
                close = text.find("]", pos + 1)
                if close < 0:
                    break
                pos = close + 1
                while pos < len(text) and text[pos] in " \t\n":
                    pos += 1
            if pos >= len(text) or text[pos] != "{":
                break
            depth, start = 0, pos
            while pos < len(text):
                if text[pos] == "{":
                    depth += 1
                elif text[pos] == "}":
                    depth -= 1
                    if depth == 0:
                        groups.append(text[start + 1:pos])
                        pos += 1
                        break
                pos += 1
            if command != "captionof":
                break
        if groups:
            out.append(groups[-1])
        i = max(pos, j + len(needle))
    return out


def scan_mcb_rule_conflicts(root: Path, limit: int = 24) -> list:
    """PKG-12: a table row whose p and its own interval say opposite things."""
    root = Path(root)
    rows = []
    for p in sorted(_iter_tree_files(root)):
        if not p.is_file() or p.suffix.lower() not in (".tex", ".ltx", ".txt", ".md"):
            continue
        try:
            if p.stat().st_size > 4 * 1024 * 1024:
                continue
            text = p.read_text("utf-8", "replace")
        except OSError:
            continue
        if "mcb" not in p.name.lower() and "MCB" not in text[:4000]:
            continue
        caption = " ".join(_latex_command_bodies(text, "captionof")
                           + _latex_command_bodies(text, "caption"))
        if not caption or not (MCB_P_SMALL_RULE_RE.search(caption)
                               and MCB_CI_RULE_RE.search(caption)):
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if "&" not in line or line.lstrip().startswith("%"):
                continue
            cells = [c.strip() for c in re.sub(r"\\\\.*$", "", line).split("&")]
            if len(cells) == 10:
                blocks = [(cells[2], cells[3], cells[5]), (cells[6], cells[7], cells[9])]
                label = cells[1]
                metric = cells[0]
            elif len(cells) == 5:
                blocks = [(cells[1], cells[2], cells[4])]
                label = cells[0]
                metric = ""
            else:
                continue
            for n_cell, p_cell, ci_cell in blocks:
                pval, ci = _parse_p(p_cell), _parse_ci(ci_cell)
                if pval is None or ci is None:
                    continue
                inferior_by_p = _p_reports_significant(p_cell, pval)
                inferior_by_ci = ci[0] > 0 or ci[1] < 0
                if inferior_by_p == inferior_by_ci:
                    continue
                rows.append({
                    "rule": "PKG-12", "severity": "medium", "fix": "manual",
                    "file": rel, "line": line_no,
                    "reference": (f"{metric} / {label}" if metric else label),
                    "detail": (f"this row's own two significance columns disagree under the "
                               f"rule the table's caption states (small p AND an interval "
                               f"excluding 0 both mark a significant difference): p = "
                               f"{pval:g} but the interval is [{ci[0]:g}, {ci[1]:g}]. One of "
                               f"the two columns is wrong; do not ship a table that defines "
                               f"one verdict two ways"),
                    "_strong": bool(inferior_by_ci and not inferior_by_p),
                })
    # The misleading direction first: the interval says "significantly inferior"
    # while the p does not (the row an author is most likely to read as a
    # significant result). The other direction (p significant, interval brackets
    # 0) is the same caption/table conflict but reads as conservative.
    rows.sort(key=lambda r: (not r.get("_strong"), r.get("file"), r.get("line")))
    for r in rows:
        r.pop("_strong", None)
    return rows[:limit]


# PKG-15 (2026-10-17, second pass): a DEPOSITED statistics table whose
# "pooled" section is computed on a subset of the pooled units.
#
# The CopyNumBench package carries `Fig3_ploidy_pooled_units.tsv` (one row per
# germline donor OR ACT sample: 9 + 12 = 21 units for most methods) and
# `Fig3_ploidy_mcb_pooled.tsv`, whose caption says "The first section pools
# every donor of the four panels (primary)". Its `n_units` is 9 for EVERY
# method and its `mean` is the germline-only mean: AneuFinder 69.37 (pooled:
# 80.94), FLCNA 54.45 (34.58), SCCNV 52.11 (27.76), Ginkgo-uncapped 98.88
# (87.17). The manuscript's own Supplementary Table S3 pools the same 21 units
# (n = 21 for those methods), so two deposited surfaces of the same analysis
# disagree about the sample set -- and the Hsu table's ranking follows its own
# subset (SCCNV above HMMcopy there, below it in the pooled data).
#
# The check is mechanical: for every `*mcb*.tsv` with `method`/`n_units`/`mean`
# columns, find the sibling `*units*.tsv` (same directory) and compare each
# method's unit count and mean with the table's own. A caption file with the
# same stem (`.tex`/`.md`) supplies the words the row quotes.
POOLED_UNITS_VALUE_COLUMNS = ("mean", "pct_within", "value", "score")


def _pooled_units_by_method(path: Path) -> dict:
    """{method: (n_units, mean of the value column)} for a pooled-units table."""
    header, body = _read_delimited_table(path)
    if not header or not body:
        return {}
    header = [h.strip() for h in header]
    if "method" not in header:
        return {}
    col = next((c for c in POOLED_UNITS_VALUE_COLUMNS if c in header), None)
    if col is None:
        return {}
    mi, vi = header.index("method"), header.index(col)
    groups = {}
    for r in body:
        if len(r) <= max(mi, vi):
            continue
        try:
            val = float(str(r[vi]).strip())
        except ValueError:
            continue
        groups.setdefault(str(r[mi]).strip(), []).append(val)
    return {m: (len(v), sum(v) / len(v)) for m, v in groups.items()}


# PKG-16 (2026-10-17, second pass): the REQUIRED FORM's software list vs the
# tools the manuscript says it used.
#
# The CopyNumBench Reporting Summary has a "Software and code" section that
# lists ~30 tools, but it omits four the main text names -- bedtools, Seurat,
# cellsnp-lite and UCSC liftOver -- which are exactly the four whose versions the
# main text still marks "[AUTHOR TO COMPLETE]". The form therefore contradicts
# the manuscript's own inventory: the summary reads as a complete software
# list while the paper says four tools were used. The check compares the tool
# tokens of the main text's "Software." paragraph against the form's text (whole
# text, so a form that names a tool outside its list still counts) and reports
# the tools the form never names; a form with no software inventory at all gets
# ONE row instead of one per tool.
FORM_STOP_TOKENS = {
    "the", "and", "with", "for", "from", "using", "used", "study", "were", "their",
    "its", "this", "these", "versions", "version", "additionally", "including",
    "also", "has", "have", "been", "are", "was", "is", "of", "in", "on", "at", "by",
    "as", "or", "commit", "which", "where", "publicly", "al", "all", "both",
    "extension", "benchmark", "software",
    "compute", "environment", "intel", "xeon", "gold", "cpu", "ghz",
    "recorded", "seven", "eight", "nine", "ten", "four", "five", "six",
}


def _tool_tokens(text: str) -> set:
    """Tool-like tokens of a software paragraph: the first token of each entry
    (comma-, semicolon- or sentence-delimited), connectives removed."""
    out = set()
    # A sentence boundary ends an entry list too: "STAR 2.7.5c. The extension
    # benchmark additionally used bedtools (bamtobed)" carries TWO tools, and
    # splitting on commas alone kept only STAR.
    body = re.sub(r"(?<=[.!?])\s+", ";", str(text or ""))
    for chunk in re.split(r"[,;]", body):
        c = chunk.strip()
        c = re.sub(r"^(?:and|the|with|used|using|additionally|including|also|has|have|"
                   r"were|was|of|in|on|at|by|as|or)\s+", "", c, flags=re.I)
        c = re.sub(r"^(?:[A-Za-z]+\s+){0,3}?(?:used|including|additionally)\s+", "", c,
                   flags=re.I)
        c = re.sub(r"^(?:used|using|with)\s+", "", c, flags=re.I)
        m = re.match(r"([A-Za-z][A-Za-z0-9_+.\-]{2,30})", c)
        if m and m.group(1).lower() not in FORM_STOP_TOKENS:
            out.add(m.group(1))
    return out


def _form_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _pdf_text(path)
    if path.suffix.lower() == ".docx":
        return "\n".join(_docx_paragraphs(path) or [])
    if path.suffix.lower() == ".doc":
        # A legacy binary `.doc` is not UTF-8 text. Decoding it with "replace"
        # produced non-empty garbage, so the non-empty guard passed and the
        # scan reported "no software inventory" for a form it never read. The
        # caller's own empty-text branch records "could not be read as text".
        return ""
    try:
        return path.read_text("utf-8", "replace")
    except OSError:
        return ""


def scan_form_software_coverage(root: Path, limit: int = 12) -> list:
    """PKG-16: the required form's software list omits tools the paper names."""
    root = Path(root)
    forms = []
    mains = []
    for p in sorted(_iter_tree_files(root)):
        if not p.is_file():
            continue
        low = p.name.lower()
        if ("reporting" in low and "summary" in low) and p.suffix.lower() in (
                ".pdf", ".docx", ".doc"):
            forms.append(p)
        elif p.suffix.lower() == ".docx" and docx_document_role(p.name) == "main" \
                and "supp" not in low and not ("reporting" in low and "summary" in low):
            mains.append(p)
    if not forms or not mains:
        return []
    main_paras = []
    for p in mains:
        main_paras.extend(_docx_paragraphs(p) or [])
    # A table header ("Software and algorithms") is not a software paragraph:
    # require a real sentence with a version-like token in it.
    soft_paras = []
    for index, text in enumerate(main_paras):
        stripped = text.strip()
        if re.fullmatch(r"(?i)software(?:\s+and\s+code)?\s*[:.]?", stripped):
            # A Word heading and the inventory beneath it are separate
            # paragraphs. Joining was previously limited to paragraphs that
            # themselves began "Software" and carried a digit, so the usual
            # heading + list form produced no row at all.
            following = next(
                (p.strip() for p in main_paras[index + 1:] if p.strip()), "")
            if following:
                soft_paras.append(f"Software. {following}")
            continue
        if re.match(r"(?i)^\s*(software|software and code)\b", stripped) \
                and len(stripped) >= 25 and re.search(r"\d", stripped):
            soft_paras.append(stripped)
    soft = "\n".join(soft_paras)
    soft = re.sub(r"(?i)^\s*software(?:\s+and\s+code)?\s*[.:]?\s*", "", soft)
    if not soft:
        return []
    tools = _tool_tokens(soft)
    if not tools:
        return []
    rows = []
    for form in forms:
        if form.suffix.lower() == ".pdf" and not shutil.which("pdftotext"):
            # No PDF text extractor: the class is UNEXAMINED for this form, and
            # the row says so (a hidden gap would set its probability to zero).
            rows.append({"rule": "PKG-16", "severity": "low", "fix": "manual",
                         "advisory": True,
                         "file": form.relative_to(root).as_posix(), "line": 1,
                         "reference": "software inventory",
                         "detail": ("the form is a PDF and no `pdftotext` is available in this "
                                    "environment, so its software inventory could NOT be checked "
                                    "against the manuscript's tools; install poppler-utils and "
                                    "re-run, or check the list by hand")})
            continue
        text = _form_text(form)
        if not text.strip():
            rows.append({"rule": "PKG-16", "severity": "medium", "fix": "manual",
                         "advisory": True,
                         "file": form.relative_to(root).as_posix(), "line": 1,
                         "reference": "software inventory",
                         "detail": (f"the required form could not be read as text; the "
                                    f"manuscript names {len(tools)} tool(s) and none could be "
                                    f"checked against it")})
            continue
        has_software_section = bool(re.search(r"(?i)\bsoftware\b", text))
        missing = sorted(
            tool for tool in tools
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(tool) + r"(?![A-Za-z0-9])",
                         text, re.I) is None)
        if not has_software_section:
            rows.append({"rule": "PKG-16", "severity": "medium", "fix": "manual",
                         "advisory": True,
                         "file": form.relative_to(root).as_posix(), "line": 1,
                         "reference": "software inventory",
                         "detail": (f"the required form carries no software inventory at all, "
                                    f"while the manuscript names {len(tools)} tool(s) "
                                    f"({', '.join(sorted(tools)[:8])}...): a filled form must "
                                    f"report the software the study used")})
            continue
        for name in missing[:limit]:
            rows.append({"rule": "PKG-16", "severity": "medium", "fix": "manual",
                         "advisory": True,
                         "file": form.relative_to(root).as_posix(), "line": 1,
                         "reference": name,
                         "detail": (f"the manuscript's Software paragraph names {name!r} as a "
                                    f"tool used in this study, but the required form never names "
                                    f"it: the form's software inventory is incomplete (and the "
                                    f"reader comparing the two surfaces sees a contradiction). "
                                    f"Add it to the form with its version, or say in the "
                                    f"manuscript that it was not used in the reported results")})
    return rows


# ---- Cross-surface claim checks (2026-10-17, third pass) --------------------
# The third audit round found classes that live BETWEEN two shipped surfaces
# rather than inside one table:
#   * a required form whose design claims (no selection/evaluation overlap,
#     thresholds fixed before inspection) the Methods contradict ("selected
#     empirically to match manual karyotyping on the cell-line datasets", a
#     parameter relaxed because the defaults retained no cells);
#   * a prose "X gave the highest average <metric>" the shipped per-dataset grid
#     contradicts (CopyKAT 0.751 vs Numbat 0.759 on the tumor/normal ROC-AUC
#     grid, while the claim cites a heatmap whose numbers are not shipped);
#   * a "recovered the N subpopulations" claim made with a FIXED k while the
#     same package admits no cluster-to-karyotype concordance statistic
#     (CopyNumBench HG008: Ginkgo's 7/32/81 against cytogenetics spliced from
#     two passages, 17:3 and 23:2);
#   * one symbol ("SD") used for two different estimators (population across
#     datasets in Table S1, sample across antigens in Table 4);
#   * a definition that admits one term can distort the measure and then draws a
#     comparative inference from the measure (the NeoHeteroclitic G(y) sum of
#     ratios).
#
# These rows are seeded for the review/audit/revision arms and reach readiness
# (the first two block; the judgment seeds are advisory). Each row quotes BOTH
# surfaces so a session can dispose it without re-deriving the package.
def _package_document_texts(root: Path, texts=None) -> list:
    """[(rel, [paragraph, ...], full_text)] for the package's own documents.

    Evidence areas (raw_data/, feedback, code/) and the author's READMEs are
    not manuscript surfaces; bookkeeping and scratch are skipped like every
    other corpus scan. `texts` lets a caller that runs several scans build the
    (expensive, PDF-parsing) list once and share it.
    """
    if texts is not None:
        return texts
    root = Path(root)
    out = []
    # `supplementary_source_files/` is an INPUT area for the SI build (figure
    # PDFs, table sources), not a prose surface: parsing its PDFs added seconds
    # per scan and produced no claim.
    areas = {str(a).lower() for a in EVIDENCE_DIRNAMES} | {"supplementary_source_files"}
    for p in sorted(_iter_tree_files(root)):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in (".docx", ".pdf", ".tex", ".ltx", ".md", ".txt"):
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel.split("/", 1)[0].lower() in areas:
            continue
        if is_bookkeeping_name(p.name) or is_non_submitted_readme_name(p.name):
            continue
        if ext == ".docx":
            paras = [t for t in (_docx_paragraphs(p) or []) if t.strip()]
            text = "\n".join(paras)
        elif ext == ".pdf":
            text = _pdf_text(p)
            paras = [t.strip() for t in re.split(r"\n\s*\n", text) if t.strip()]
            if len(paras) <= 1:
                # A PDF export without blank lines would otherwise read as ONE
                # paragraph, and the paragraph-level scans (a caveat followed by
                # an inference) would compare text from unrelated pages.
                paras = [t for t in text.splitlines() if t.strip()]
        else:
            try:
                text = p.read_text("utf-8", "replace")
            except OSError:
                continue
            paras = [t for t in text.splitlines() if t.strip()]
        if text.strip():
            out.append((rel, paras, text))
    return out


def _sentences(text: str) -> list:
    """Sentences of one text (whitespace-normalised)."""
    body = re.sub(r"\s+", " ", str(text or ""))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]


FORM_DESIGN_CLAIM_RE = re.compile(
    r"(?i)(?:no overlap[^.]{0,160}(?:parameter|threshold|tuning|selection|evaluation)|"
    r"(?:thresholds?|parameters?|method selection|evaluation code)[^.]{0,100}"
    r"(?:were |was )?(?:fixed|set|chosen|determined)[^.]{0,80}"
    r"(?:before)[^.]{0,100}(?:metric|performance|inspect|analysis))")
METHOD_SELECTION_RE = re.compile(
    r"(?i)(?:selected|chosen|tuned|optimized|optimised|calibrated|relaxed|lowered|"
    r"raised|adjusted|set)[^.]{0,120}"
    r"(?:empirically|to match|because the default|on the cell-line|on the [^.]{0,40}"
    r"datasets|from the [^.]{0,30}datasets)")


def scan_form_method_conflicts(root: Path, texts=None, limit: int = 8) -> list:
    """PKG-17: a required form's design claims vs the Methods' own admissions."""
    root = Path(root)
    docs = _package_document_texts(root, texts)
    if not docs:
        return []
    forms = [(rel, text) for rel, _paras, text in docs
             if "reporting" in rel.lower() and "summary" in rel.lower()]
    method_texts = [(rel, text) for rel, _paras, text in docs
                    if rel not in {f[0] for f in forms}
                    and docx_document_role(Path(rel).name) == "main"]
    if not forms or not method_texts:
        return []
    rows = []
    for frel, ftext in forms:
        fclaims = [s for s in _sentences(ftext) if FORM_DESIGN_CLAIM_RE.search(s)]
        if not fclaims:
            continue
        for mrel, mtext in method_texts:
            for s in _sentences(mtext):
                if not METHOD_SELECTION_RE.search(s):
                    continue
                if not re.search(r"(?i)\b(?:threshold|parameter|cutoff|cut-off|"
                                 r"configuration|setting)s?\b", s):
                    continue
                rows.append({
                    "rule": "PKG-17", "severity": "high", "fix": "manual",
                    "file": frel, "line": 1, "reference": "selection/evaluation overlap",
                    "detail": (f"the form states a design claim the Methods contradict. "
                               f"Form: \"{fclaims[0][:220]}\" -- Methods ({mrel}): "
                               f"\"{s[:260]}\". A parameter selected on data that are part of "
                               f"the evaluation set is not a pre-specified threshold; either "
                               f"the Methods' selection data are excluded from evaluation, or "
                               f"the form's no-overlap/fixed-before statement must be scoped to "
                               f"say what was selected and on which data"),
                })
                if len(rows) >= limit:
                    return rows
    return rows


RANK_CLAIM_RE = re.compile(
    r"(?i)\b([A-Za-z][A-Za-z0-9_.\-]{2,40}?)\s+(?:gave|had|showed|achieved)\s+the\s+"
    r"highest\s+(?:average|mean)\s+([^.;]{3,160})")


def scan_ranking_claim_conflicts(root: Path, texts=None, limit: int = 12) -> list:
    """PKG-18: a prose "X gave the highest average <metric>" vs a shipped grid.

    The grid is any `.tsv` with `method`, `metric`, `dataset` and a numeric
    `mean` (the CopyNumBench Fig. 5 grid). The metric is matched by token overlap
    with the grid's own metric names, the method by the grid's method ids, and
    the per-method mean over datasets is recomputed. A sentence that cites a
    DIFFERENT figure (whose numbers are not shipped) is advisory: the claim may
    hold there, but the gap is stated.
    """
    root = Path(root)
    docs = _package_document_texts(root, texts)
    grids = []
    for p in sorted(_iter_tree_files(root)):
        if not p.is_file() or p.suffix.lower() != ".tsv" or "grid" not in p.name.lower():
            continue
        header, body = _read_delimited_table(p)
        if not header:
            continue
        header = [h.strip() for h in header]
        if not {"method", "metric", "dataset", "mean"}.issubset(header):
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        grids.append((rel, header, body))
    if not grids or not docs:
        return []
    rows = []
    seen = set()
    for rel, _paras, text in docs:
        sentences = _sentences(text)
        for idx, s in enumerate(sentences):
            m = RANK_CLAIM_RE.search(s)
            if not m:
                continue
            claimed = m.group(1).strip().lower()
            # The metric name is usually in the sentence's own context ("For
            # tumor/normal classification based on the scRNA-seq-derived
            # aneuploidy score ... CopyKAT gave the highest average ROC-AUC"),
            # not only in the few words after "highest average": matching the
            # captured phrase alone tied every ROC-AUC metric at 2 tokens and
            # picked the wrong column.
            # The metric name can sit in the PREVIOUS sentence when a PDF line
            # break splits "(Supplementary Fig. S31), CopyKAT gave the highest
            # average ROC-AUC" into two sentences: the claim sentence then says
            # only "ROC-AUC" and every ROC metric ties.
            context = (sentences[idx - 1] if idx else "") + " " + s
            metric_words = {w for w in re.findall(r"[a-z0-9]{3,}", context.lower())}
            cites_figure = bool(re.search(
                r"(?i)\b(?:supplementary\s+)?fig(?:ure)?\.?\s*S?\d+", context))
            for grel, header, body in grids:
                mi, me_i = header.index("method"), header.index("metric")
                ds_i, mv_i = header.index("dataset"), header.index("mean")
                by_metric = {}
                for r in body:
                    if len(r) <= max(mi, me_i, ds_i, mv_i):
                        continue
                    try:
                        val = float(str(r[mv_i]).strip())
                    except ValueError:
                        continue
                    met = str(r[me_i]).strip()
                    by_metric.setdefault(met, {}).setdefault(
                        str(r[mi]).strip().lower(), {})[str(r[ds_i]).strip()] = val
                best_metric, best_score = None, 0
                for met in by_metric:
                    words = {w for w in re.findall(r"[a-z0-9]{3,}", met.lower())}
                    score = len(words & metric_words)
                    if score > best_score:
                        best_metric, best_score = met, score
                if best_metric is None or best_score < 2:
                    continue
                means = {meth: sum(vals.values()) / len(vals)
                         for meth, vals in by_metric[best_metric].items() if vals}
                if len(means) < 2:
                    continue
                claimed_key = re.sub(r"[^a-z0-9]+", "", claimed)
                claimed_ids = [
                    meth for meth in means
                    if re.sub(r"[^a-z0-9]+", "", meth.lower()) == claimed_key
                ]
                if not claimed_ids:
                    continue
                claimed_mean = max(means[meth] for meth in claimed_ids)
                top_method, top_mean = max(means.items(), key=lambda kv: kv[1])
                if claimed_mean >= top_mean - 1e-9:
                    continue
                claim_key = (claimed, re.sub(r"[^a-z0-9]+", " ", m.group(2).lower()).strip(),
                             best_metric)
                if claim_key in seen:
                    continue
                seen.add(claim_key)
                rows.append({
                    "rule": "PKG-18", "severity": "medium", "fix": "manual",
                    "advisory": bool(cites_figure),
                    "file": rel, "line": 1,
                    "reference": f"{m.group(1).strip()} / {best_metric}",
                    "detail": (f"the text says {m.group(1).strip()!r} gave the highest average "
                               f"{m.group(2).strip()[:60]!r}, but the shipped grid {grel} ranks "
                               f"{top_method!r} above it on that metric ({top_mean:.3f} vs "
                               f"{claimed_mean:.3f})."
                               + (" The sentence cites a figure whose numbers are not shipped, "
                                  "so the claim cannot be checked against the package -- name "
                                  "the surface and ship its numbers."
                                  if cites_figure else
                                  " Correct the sentence or the grid; do not leave two shipped "
                                  "surfaces disagreeing about the ranking.")),
                })
                if len(rows) >= limit:
                    return rows
    return rows


RECOVERED_CLAIM_RE = re.compile(
    r"(?i)\b(?:recover(?:ed|s)?|reproduc(?:ed|es)?)\b[^.]{0,120}"
    r"\b(?:subpopulations?|clusters?|structure)\b")
FIXED_K_RE = re.compile(
    r"(?i)\b(?:cut(?:ting)?|partition(?:ed|ing)?|split|clustered)[^.]{0,80}"
    r"\bk\s*=\s*(\d{1,2})\b|\bk\s*=\s*(\d{1,2})\b[^.]{0,80}\b(?:cut|cluster)")
NO_CONCORDANCE_RE = re.compile(
    r"(?i)\b(?:did not|do not|no)\b[^.]{0,80}\bconcordance\b")


def scan_recovered_structure_claims(root: Path, texts=None, limit: int = 8) -> list:
    """PKG-19: a "recovered the N subpopulations" claim with a fixed k and no
    concordance statistic (a qualitative claim written as a validation)."""
    root = Path(root)
    docs = _package_document_texts(root, texts)
    if not docs:
        return []
    claims, fixed_k, no_conc = [], [], []
    for rel, _paras, text in docs:
        for s in _sentences(text):
            if RECOVERED_CLAIM_RE.search(s):
                claims.append((rel, s))
            m = FIXED_K_RE.search(s)
            if m:
                fixed_k.append((rel, s, int(m.group(1) or m.group(2))))
            if NO_CONCORDANCE_RE.search(s):
                no_conc.append((rel, s))
    if not claims:
        return []
    rows = []
    for rel, s in claims[:limit]:
        k = next((k for r_, _s, k in fixed_k if r_ == rel), None)
        conc = next((cs for cr, cs in no_conc if cr == rel), "")
        sizes = ""
        for meth in re.findall(r"(?i)\b(hmmcopy|copynumber|ginkgo|aneufinder|sccnv|chisel|"
                               r"scyn|secnv|flcna|scabsolute)\b", s):
            hit = next((q for q in _iter_tree_files(root)
                        if "cluster_membership" in q.name.lower()
                        and meth.lower() in q.name.lower()), None)
            if hit is None:
                continue
            try:
                lines = [ln for ln in hit.read_text("utf-8", "replace").splitlines()
                         if ln.strip()]
            except OSError:
                continue
            counts = {}
            for line in lines[1:]:
                cells = line.split("\t")
                if cells:
                    key = cells[-1].strip()
                    counts[key] = counts.get(key, 0) + 1
            sizes = (f" {meth}: "
                     + "/".join(str(v) for v in sorted(counts.values(), reverse=True))
                     + " cells per cluster")
            break
        rows.append({
            "rule": "PKG-19", "severity": "medium", "fix": "manual", "advisory": True,
            "file": rel, "line": 1, "reference": s[:80],
            "detail": (f"the text says {s[:220]!r}"
                       + (f", while the same package fixes the cut at k = {k} "
                          f"(\"{next((fs for fr_, fs, fk in fixed_k if fr_ == rel), '')[:180]}\")"
                          if k else "")
                       + (f" and states \"{conc[:180]}\"" if conc else "")
                       + sizes
                       + ". A fixed cut imposes that many clusters, and without a concordance "
                       "statistic the claim that the karyotype-defined structure was recovered "
                       "is qualitative. State the measure (or the cluster-to-karyotype "
                       "comparison) or soften 'recovered' to what was shown."),
        })
    return rows


SD_POP_RE = re.compile(
    r"(?i)population standard deviation[^.]{0,80}denominator\s*n\b|"
    r"denominator\s*n\b[^.]{0,80}population standard deviation")
SD_SAMPLE_RE = re.compile(
    r"(?i)sample standard deviation[^.]{0,80}denominator\s*n\s*[−-]\s*1\b|"
    r"denominator\s*n\s*[−-]\s*1\b[^.]{0,80}sample standard deviation")


def scan_sd_estimator_ambiguity(root: Path, texts=None, limit: int = 6) -> list:
    """PKG-20: one symbol ("SD") defined as two different estimators."""
    root = Path(root)
    docs = _package_document_texts(root, texts)
    if not docs:
        return []
    pop = [(rel, m.group(0)) for rel, _p, t in docs for s in _sentences(t)
           for m in [SD_POP_RE.search(s)] if m]
    sample = [(rel, m.group(0)) for rel, _p, t in docs for s in _sentences(t)
              for m in [SD_SAMPLE_RE.search(s)] if m]
    if not pop or not sample:
        return []
    uses = []
    for rel, paras, _t in docs:
        if docx_document_role(Path(rel).name) != "main":
            continue
        for s in _sentences("\n".join(paras)):
            if re.search(r"(?i)\bSDs?\b", s) and not re.search(
                    r"(?i)\bpopulation\b|\bsample\b|\bdenominator\b", s):
                uses.append((rel, s))
    if not uses:
        return []
    rows = []
    for rel, s in uses[:limit]:
        rows.append({
            "rule": "PKG-20", "severity": "low", "fix": "manual", "advisory": True,
            "file": rel, "line": 1, "reference": "SD",
            "detail": (f"the package defines SD two ways -- population over datasets "
                       f"({pop[0][1][:150]!r}) and sample over antigens "
                       f"({sample[0][1][:150]!r}) -- while this sentence uses 'SD' without "
                       f"naming either: {s[:200]!r}. State the estimator (and its denominator) "
                       f"where the prose compares the two, so the two SDs are not read as one "
                       f"quantity"),
        })
    return rows


DEFINITION_DISTORTION_RE = re.compile(
    r"(?i)\b(?:can contribute disproportionately|can dominate|is dominated by|"
    r"can distort|may distort|is sensitive to (?:a )?single)\b")
DEFINITION_STRONG_RE = re.compile(
    r"(?i)\b(?:means?|therefore|demonstrates?|proves?|shows?)\b[^.]{0,120}"
    r"\b(?:more|stronger|higher|greater|larger)\b")


def scan_definition_overreach(root: Path, texts=None, limit: int = 8) -> list:
    """PKG-21: a definition that admits a distortion, then draws a strong inference."""
    root = Path(root)
    rows = []
    for rel, paras, _t in _package_document_texts(root, texts):
        for para in paras:
            if not DEFINITION_DISTORTION_RE.search(para):
                continue
            if not DEFINITION_STRONG_RE.search(para):
                continue
            sentences = _sentences(para)
            caveat = next((s for s in sentences if DEFINITION_DISTORTION_RE.search(s)), "")
            inference = next((s for s in sentences if DEFINITION_STRONG_RE.search(s)), "")
            rows.append({
                "rule": "PKG-21", "severity": "medium", "fix": "manual", "advisory": True,
                "file": rel, "line": 1, "reference": "definition vs inference",
                "detail": (f"the same paragraph states that one term can distort the measure "
                           f"(\"{caveat[:180]}\") and then draws a comparative inference "
                           f"(\"{inference[:200]}\"). One dominating term can produce the "
                           f"comparison without a repertoire-wide (or population-wide) change; "
                           f"scope the inference to what the measure actually shows, or use a "
                           f"measure that is not dominated by a single ratio"),
            })
            if len(rows) >= limit:
                return rows
    return rows


NEGATED_NOTE_RE = re.compile(
    # Only an INTERPRETATION denial counts ("should not be read as", "not
    # evidence", "does not demonstrate"). A bare limitation ("we cannot test
    # this") is not a contradiction of the citing sentence.
    r"(?i)(?:should\s+(?:therefore\s+)?not|not\s+be\s+interpreted|"
    r"cannot\s+be\s+interpreted|not\s+evidence|no\s+evidence|"
    r"does\s+not\s+demonstrat\w*|does\s+not\s+show|not\s+an?\s+intrinsic|"
    r"not\s+the\s+same\s+as)")
ASSERTIVE_MAIN_RE = re.compile(
    r"(?i)(?:\bexposed\b|\bdemonstrat\w*|\bshows? that\b|\breveals?\b|\bindicates?\b|"
    r"\bconfirms?\b|\bproves?\b|\bperformed\s+(?:near-?)?randomly\b|"
    r"\bperformed\s+(?:poorly|best|worst)\b|\boutperform\w*|\bunderperform\w*)")
METHOD_TOKENS = frozenset({
    "hmmcopy", "copynumber", "ginkgo", "aneufinder", "sccnv", "chisel", "scyn",
    "secnv", "flcna", "scabsolute", "numbat", "copykat", "casper", "infercnv",
    "infercna", "conicsmat", "scevan", "prime", "mixmhcpred", "mhcflurry",
    "netmhcpan", "caller", "callers",
})
NOTE_CITATION_RE = re.compile(r"(?i)supplementary\s+(?:note|fig(?:ure)?)\.?\s*S?\d+")


def _content_words(text: str) -> set:
    """Comparable content words (>= 4 letters, common words removed)."""
    stop = {"that", "this", "these", "those", "with", "from", "were", "have", "been",
            "which", "their", "there", "they", "than", "then", "when", "where", "also",
            "such", "more", "most", "less", "into", "over", "under", "about", "using"}
    return {w for w in re.findall(r"[a-z]{4,}", str(text or "").lower()) if w not in stop}


def scan_cited_note_negations(root: Path, texts=None, limit: int = 8) -> list:
    """PKG-22: a main-text claim whose CITED supplementary note says not to read it so."""
    root = Path(root)
    docs = _package_document_texts(root, texts)
    mains = [(rel, text) for rel, _p, text in docs
             if docx_document_role(Path(rel).name) == "main"]
    # "si" alone would match any file whose name contains it ("analysis.md"):
    # only the supplement's own documents are note surfaces.
    # `supp`/`note` as WORDS, never substrings: notebook.md, support.docx,
    # endnote_library.txt and keynote.pptx are not supplementary notes.
    _note_rel = re.compile(
        # `suppNote`/`supp_caption` are note surfaces; `support` and `notebook`
        # are not. A camel-case boundary after `supp` is a word boundary here,
        # and that lookahead must stay case-SENSITIVE even under re.I: `[A-Z]`
        # with IGNORECASE matched the `o` in `support` and the `o` in
        # `notebook`, re-admitting exactly the substrings this rule removes.
        r"(?:^|[/_.\-\s])(?:supp(?:l(?:ement(?:ary|al)?)?)?|notes?)"
        r"(?=[/_.\-\s]|(?-i:[A-Z])|$)", re.I)
    notes = [(rel, text) for rel, _p, text in docs
             if _note_rel.search(rel)]
    if not mains or not notes:
        return []
    note_rows = []
    for nrel, ntext in notes:
        sents = _sentences(ntext)
        for i, s in enumerate(sents):
            context = (sents[i - 1] + " " if i else "") + s
            note_rows.append((nrel, s, _content_words(context)))
    if not note_rows:
        return []
    rows = []
    for mrel, mtext in mains:
        sentences = _sentences(mtext)
        for idx, s in enumerate(sentences):
            if not NOTE_CITATION_RE.search(s):
                continue
            # A citation often splits from its claim: "… performed
            # near-randomly (per-dataset results in Supplementary Figs.
            # S31–S36 and Supplementary Note 1)." -- the splitter stops at
            # "Figs." Only a SHORT continuation fragment takes the previous
            # sentence; a full sentence that merely follows another one keeps
            # its own claim, or an unrelated neighbouring claim would be
            # paired with the note.
            claim_sentence = s
            if len(s.split()) <= 8 and idx:
                claim_sentence = sentences[idx - 1] + " " + s
            if not ASSERTIVE_MAIN_RE.search(claim_sentence):
                continue
            mw = _content_words(claim_sentence)
            best, best_overlap, best_words, best_shared = None, 0, set(), set()
            for nrel, ns, nw in note_rows:
                if not NEGATED_NOTE_RE.search(ns):
                    continue
                overlap = len(mw & nw)
                if overlap > best_overlap:
                    best, best_overlap, best_words = (nrel, ns), overlap, (mw & nw)
                    best_shared = mw & _content_words(ns)
            if best is None or best_overlap < 3:
                continue
            # The NEGATED sentence itself must name a shared, non-method subject
            # (row 1: "purity"): method names alone pair two different claims
            # about the same tools (the Song/CopyKAT sentence vs the note's
            # low-purity limitation).
            if not any(w not in METHOD_TOKENS for w in best_shared):
                continue
            rows.append({
                "rule": "PKG-22", "severity": "medium", "fix": "manual", "advisory": True,
                "file": mrel, "line": 1, "reference": "cited note",
                "detail": (f"the main text says \"{claim_sentence[:220]}\" and cites the "
                           f"supplementary "
                           f"note; the note's closest sentence says \"{best[1][:220]}\" "
                           f"({best[0]}, {best_overlap} shared content words). The note asks "
                           f"that the result NOT be read the way the citing sentence reads it "
                           f"-- reconcile the two (scope the main-text claim, or correct the "
                           f"note's conclusion)"),
            })
            if len(rows) >= limit:
                return rows
    return rows


REF_ENTRY_NUM_RE = re.compile(r"^\s*(\d{1,3})\.\s*$")
INLINE_CITATION_RE = re.compile(
    # The word must END in a letter: a hyphen is a word separator here, not part
    # of the citation stem, so "COVID-19" is not a citation of reference 19
    # (`[A-Za-z\-]{2,}` used to absorb the trailing hyphen and bind the 19).
    r"(?<![A-Za-z])((?!(?:grch|chm|python|hg|mm)\d)[A-Za-z][A-Za-z\-]{1,}[A-Za-z])"
    # A citation glued to the sentence period ("omics43.") is the usual form;
    # reject only a digit or a decimal continuation, not the full stop.
    r"(\d{1,4})(?!\d|\.\d)",
    re.I,
)
SINGLE_CELL_RE = re.compile(r"(?i)\bsingle[- ]cell\b")
ASSEMBLY_TITLE_RE = re.compile(
    r"(?i)\b(?:complete sequence|genome assembly|reference genome|"
    r"telomere[- ]to[- ]telomere)\b")
# A display-item label ("Figure 2") or a numbered sample is not a citation.
CITATION_LABEL_WORDS = frozenset({
    "figure", "fig", "table", "section", "note", "day", "dataset", "sample",
    "patient", "donor", "step", "round", "group", "panel", "supplementary",
})


REF_HEADING_RE = re.compile(
    r"^\s*(?:references|refs|bibliography|works\s+cited|literature\s+cited|"
    r"reference\s+list)(?:\s*\([^)]*\))?\s*[:.]?\s*$", re.I)
REF_END_RE = re.compile(
    r"^\s*(?:methods?|materials\s+and\s+methods|results?|discussion|conclusions?|"
    r"introduction|acknowledge?ments?|author\s+contributions?|funding|"
    r"figure\s+legends?|tables?|supplementary(?:\s+\w+)?|extended\s+data)\s*:?\s*$",
    re.I)
# A year alone is ordinary prose ("In 2021 we repeated ..."); a reference
# entry prints it parenthesised or as a terminal field.
_ENTRY_LIKE_RE = re.compile(
    r"(?:\bdoi\b|https?://|\bet al\b|\((?:1[5-9]|20)\d{2}[a-z]?\)"
    r"|\b(?:1[5-9]|20)\d{2}[a-z]?[;:,.])", re.I)
_NON_SURNAME = frozenset((
    "however therefore thus moreover furthermore in the this these those we our "
    "results discussion methods introduction conclusion conclusions table figure "
    "see note data").split())


def _entry_author_like(text: str) -> bool:
    """`Surname, I.` at the start, case-sensitive, and not a sentence word."""
    m = re.match(r"^\s*([A-Z][A-Za-z'’.-]+),\s+[A-Z]\.", text or "")
    return bool(m and m.group(1).lower() not in _NON_SURNAME)


def _numbered_reference_titles(paras: list) -> dict:
    """{number: entry text} from a numbered reference list (docx paragraphs)."""
    out, current = {}, None
    # A one-line "43. Nurk, S. ... Science 372, 984 (2021)." entry is the most
    # common non-Zotero layout and matched NEITHER old pattern, so the PKG-23
    # citation check silently inspected zero references. Bracket and
    # parenthesis numbering (`[1] ...`, `1) ...`) are the same entry shape.
    # The one-line form is only read INSIDE a references section: the same
    # shape is a numbered body list, and a body item could overwrite a genuine
    # entry. The Zotero two-line form is read only inside the section too.
    ref_start = None
    for i, p in enumerate(paras):
        if REF_HEADING_RE.match(p or ""):
            ref_start = i + 1
    for idx, p in enumerate(paras):
        text = p or ""
        if ref_start is not None and idx >= ref_start and REF_END_RE.match(text):
            # No end boundary made every body paragraph after the list an
            # entry (and let its number overwrite the real one).
            break
        in_refs = ref_start is not None and idx >= ref_start
        two = re.match(r"^\s*(\d{1,4})\.\s*\n\s*(\S.*)$", text, re.S)
        if two:
            num, rest = int(two.group(1)), two.group(2).strip()
            # A two-line entry OUTSIDE a section is the heading-less Zotero
            # form only; when the document HAS a references heading, a body
            # "1." + following sentence must not become entry 1.
            if in_refs or (ref_start is None and (
                    _ENTRY_LIKE_RE.search(rest) or _entry_author_like(rest))):
                out.setdefault(num, rest)
            current = None
            continue
        bare = re.match(r"^\s*(\d{1,4})\.\s*$", text)
        if bare:
            current = int(bare.group(1)) if in_refs else None
            if current is not None:
                out.setdefault(current, "")
            continue
        one = re.match(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})[.)])\s+(\S.*)$",
                       text, re.S)
        if one:
            num = int(one.group(1) or one.group(2))
            rest = one.group(3).strip()
            if in_refs and (_ENTRY_LIKE_RE.search(rest) or _entry_author_like(rest)
                            or re.match(r"^[A-Z][A-Za-z'’.-]+,?\s", rest)):
                out.setdefault(num, rest)
            current = None
            continue
        if current is not None and text.strip():
            out[current] = (out[current] + " " + text.strip()).strip()
            current = None
    return out


def scan_single_cell_citation_mismatch(root: Path, texts=None, limit: int = 8) -> list:
    """PKG-23: a single-cell claim cited to a bulk genome ASSEMBLY.

    Narrow on purpose: the sentence must say "single-cell", the citation number
    must resolve to an entry whose title is an assembly/complete-sequence paper,
    and that title must not itself be single-cell. (CopyNumBench cited Nurk et
    al., the bulk CHM13 assembly, for "single-cell telomere-to-telomere
    co-sequencing with other omics".)
    """
    root = Path(root)
    rows = []
    for rel, paras, _text in _package_document_texts(root, texts):
        if Path(rel).suffix.lower() != ".docx":
            continue
        if docx_document_role(Path(rel).name) != "main":
            continue
        refs = _numbered_reference_titles(paras)
        if not refs:
            continue
        for s in _sentences("\n".join(paras)):
            if not SINGLE_CELL_RE.search(s):
                continue
            for m in INLINE_CITATION_RE.finditer(s):
                if m.group(1).lower() in CITATION_LABEL_WORDS:
                    continue
                num = int(m.group(2))
                title = refs.get(num, "")
                if not title or SINGLE_CELL_RE.search(title):
                    continue
                if not ASSEMBLY_TITLE_RE.search(title):
                    continue
                rows.append({
                    "rule": "PKG-23", "severity": "medium", "fix": "manual",
                    "advisory": True,
                    "file": rel, "line": 1, "reference": f"ref. {num}",
                    "detail": (f"the sentence claims single-cell capability "
                               f"(\"{s[:180]}\") but its citation resolves to a bulk genome "
                               f"assembly: ref. {num} \"{title[:180]}\". That work does not "
                               f"demonstrate the single-cell (co-sequencing) claim; cite a "
                               f"single-cell method or scope the sentence"),
                })
                if len(rows) >= limit:
                    return rows
            # The inline citation can also be a bare superscript number after a
            # word ("omics43"); INLINE_CITATION_RE covers that form.
    return rows


def scan_caption_definition_gaps(root: Path, texts=None, limit: int = 8) -> list:
    """PKG-24: an information-content caption defined as a single residue's log-likelihood."""
    root = Path(root)
    rows = []
    for rel, paras, _text in _package_document_texts(root, texts):
        for para in paras:
            if not re.search(r"(?i)\b(?:fig(?:ure)?|table)\s*\.?\s*S?\d", para):
                continue
            if not re.search(r"(?i)\binformation content\b", para):
                continue
            if not re.search(r"(?i)log[- ]likelihood of the residue", para):
                continue
            if re.search(r"(?i)\bexpected\b|sum over|frequency|probability", para):
                continue
            rows.append({
                "rule": "PKG-24", "severity": "low", "fix": "manual", "advisory": True,
                "file": rel, "line": 1, "reference": "information content",
                "detail": (f"the caption defines information content as \"derived from the "
                           f"log-likelihood of the residue at that position\": {para[:220]!r}. "
                           f"Position information content is the EXPECTED log-likelihood ratio "
                           f"over residues (sum p log2(p/q), q = uniform background), and a "
                           f"logo letter's height is its frequency times that quantity; a "
                           f"single residue's log-likelihood is neither. State the standard "
                           f"definition or the exact quantity plotted"),
            })
            if len(rows) >= limit:
                return rows
    return rows


FORM_FAILURE_CLAIM_RE = re.compile(
    r"(?i)(?:failed to run|returned no calls|no output|rather than being omitted|"
    r"reported in the deposited result tables)")
FAILURE_SENTENCE_RE = re.compile(
    r"(?i)\b(?:produced no output|no output|could not be evaluated|was not evaluated|"
    r"were not evaluated|failed to run|was excluded because|were discarded|"
    r"discarded as biased)\b")
TOOL_TOKEN_RE = re.compile(
    r"(?i)\b(hmmcopy|copynumber|ginkgo|aneufinder|sccnv|chisel|scyn|secnv|flcna|"
    r"scabsolute)\b")


def scan_form_failure_claims(root: Path, texts=None, limit: int = 8) -> list:
    """PKG-25: a form's "failures are reported, not omitted" vs the deposited tables.

    CopyNumBench's Reporting Summary says "Cases in which a tool failed to run or
    returned no calls are reported in the deposited result tables rather than
    being omitted", while the ACT balloon table omits SCYN entirely (the text
    says it produced no output on ACT) and its `failed` column is False for
    every one of the 1,815 rows (CHISEL's non-evaluable ACT rows included).
    """
    root = Path(root)
    docs = _package_document_texts(root, texts)
    claim = next((s for rel, _p, text in docs if "reporting" in rel.lower()
                  and "summary" in rel.lower() for s in _sentences(text)
                  if FORM_FAILURE_CLAIM_RE.search(s)), "")
    if not claim:
        return []
    tables = []
    for p in sorted(_iter_tree_files(root)):
        if not p.is_file() or p.suffix.lower() != ".tsv":
            continue
        header, body = _read_delimited_table(p)
        if not header:
            continue
        header = [h.strip() for h in header]
        tool_col = "tool" if "tool" in header else ("method" if "method" in header else None)
        panel_col = next((c for c in ("plot", "dataset", "panel") if c in header), None)
        if not tool_col or not panel_col:
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        tables.append((rel, header, body, tool_col, panel_col))
    if not tables:
        return []
    # The cohort vocabulary comes from the tables' own panel values, so a
    # sentence that says "these samples" can be scoped by the paragraph it sits
    # in ("For real cancer data, we used the ACT breast cancer dataset …").
    cohorts = set()
    for _trel, header, body, _tc, pc in tables:
        pi = header.index(pc)
        for r in body:
            if len(r) > pi and str(r[pi]).strip():
                cohorts.add(str(r[pi]).strip())
    rows = []
    seen = set()
    for rel, paras, text in docs:
        if "reporting" in rel.lower() and "summary" in rel.lower():
            continue
        sentences = _sentences(text)
        for idx, s in enumerate(sentences):
            # Pair a tool with the failure predicate in ITS OWN clause: "Two
            # tools could not be evaluated on the ACT cohort: SCYN produced no
            # output … , and CHISEL was excluded …" must not pair Ginkgo (a
            # passing tool named elsewhere in the sentence) with a failure.
            for clause in re.split(r"(?<=[:;])\s+|,\s+and\s+|\s+whereas\s+", s):
                if not FAILURE_SENTENCE_RE.search(clause):
                    continue
                tool = TOOL_TOKEN_RE.search(clause)
                if not tool:
                    continue
                tool_id = tool.group(1).lower()
                cohort = ""
                mc = re.search(r"(?i)\bon\s+(?:the\s+|any\s+|this\s+)?"
                               r"([A-Z][A-Za-z0-9\-]{1,20})", clause)
                if mc:
                    cohort = mc.group(1)
                if not cohort:
                    back = s + " " + " ".join(sentences[max(0, idx - 2):idx])
                    for cand in cohorts:
                        if re.search(r"(?<![A-Za-z0-9])" + re.escape(cand) + r"(?![A-Za-z0-9])",
                                     back, re.I):
                            cohort = cand
                            break
                if not cohort:
                    # An unscoped failure sentence cannot be matched to a table
                    # panel; reporting it would flag every table that carries
                    # the tool for a different cohort.
                    continue
                for trel, header, body, tool_col, panel_col in tables:
                    key = (tool_id, cohort.lower(), trel)
                    if key in seen:
                        continue
                    ti, pi = header.index(tool_col), header.index(panel_col)
                    fi = header.index("failed") if "failed" in header else None
                    if fi is None:
                        # A statistics summary (MCB/pooled) has no per-row
                        # `failed` column: it is not the "result table" a form's
                        # failure-reporting claim refers to.
                        continue
                    panel_rows = [r for r in body
                                  if len(r) > max(ti, pi)
                                  and str(r[ti]).strip().lower().split("|")[0] == tool_id
                                  and (not cohort or cohort.lower() in str(r[pi]).lower())]
                    if cohort and not any(
                            cohort.lower() in str(r[pi]).lower() for r in body if len(r) > pi):
                        continue      # the table does not cover that cohort at all
                    if not panel_rows:
                        seen.add(key)
                        rows.append({
                            "rule": "PKG-25", "severity": "high", "fix": "manual",
                            "file": trel, "line": 1, "reference": f"{tool_id} / {cohort}",
                            "detail": (f"the form claims \"{claim[:200]}\" but this deposited "
                                       f"table carries no {tool_id} row for "
                                       f"{cohort or 'this panel'}, while the text says "
                                       f"\"{clause[:200]}\" -- the failure is OMITTED from the "
                                       f"table the form points at. Add the failed rows (marked "
                                       f"as failed/no-output) or scope the form's claim"),
                        })
                        if len(rows) >= limit:
                            return rows
                        continue
                    if fi is not None and len(panel_rows[0]) > fi:
                        marks = {str(r[fi]).strip().lower() for r in panel_rows if len(r) > fi}
                        if marks <= {"false", "0", ""}:
                            seen.add(key)
                            rows.append({
                                "rule": "PKG-25", "severity": "medium", "fix": "manual",
                                "file": trel, "line": 1, "reference": f"{tool_id} / {cohort}",
                                "detail": (f"the form claims failures are reported in the "
                                           f"deposited tables, but {len(panel_rows)} {tool_id} "
                                           f"row(s) in this table carry `failed = False` "
                                           f"({', '.join(sorted(marks))}), while the text says "
                                           f"\"{clause[:200]}\" -- the rows exist but are not "
                                           f"marked as not evaluable. Mark them, or scope the "
                                           f"form's claim"),
                            })
                            if len(rows) >= limit:
                                return rows
    return rows


def _pooled_table_caption(caption_file: Path) -> str:
    """The caption text of a pooled-table source, standard and float forms.

    The standard `\\caption{...}` is the common form; reading only
    `\\captionof` left the row's quote empty and skipped the caption comparison.
    """
    text = Path(caption_file).read_text("utf-8", "replace")
    return " ".join(_latex_command_bodies(text, "caption")
                    + _latex_command_bodies(text, "captionof"))


def scan_pooled_table_mismatches(root: Path, limit: int = 24) -> list:
    """PKG-15: a pooled statistics table computed on fewer units than it claims."""
    root = Path(root)
    rows = []
    for p in sorted(_iter_tree_files(root)):
        if not p.is_file() or "mcb" not in p.name.lower() or p.suffix.lower() != ".tsv":
            continue
        # Only the POOLED section is comparable with the pooled units table: a
        # per-panel table (e.g. `..._mcb_perpanel.tsv`) legitimately tests that
        # panel's own units, so comparing it with the pooled set would flag a
        # correct table.
        if "pooled" not in p.name.lower():
            continue
        header, body = _read_delimited_table(p)
        if not header:
            continue
        header = [h.strip() for h in header]
        if not {"method", "n_units", "mean"}.issubset(header):
            continue
        mi, ni, avi = header.index("method"), header.index("n_units"), header.index("mean")
        units = {}
        table_tokens = set(re.findall(
            r"[a-z0-9]+", re.sub(r"\.tsv$", "", p.name.lower())))

        def units_match(q: Path) -> tuple:
            q_tokens = set(re.findall(
                r"[a-z0-9]+", re.sub(r"\.tsv$", "", q.name.lower())))
            return (
                ("pooled" in q_tokens) == ("pooled" in table_tokens),
                len(table_tokens & q_tokens),
                -len(q.name),
            )

        candidates = sorted(p.parent.glob("*units*.tsv"), key=units_match, reverse=True)
        for q in candidates:
            units = _pooled_units_by_method(q)
            if units:
                units_file = q
                break
        if not units:
            continue
        caption = ""
        caption_files = [p.with_suffix(ext) for ext in (".tex", ".ltx", ".md")]
        # The generated .tex of a deposited table often carries a longer stem
        # (`bench-results-...ploidy-plots.pooled.stats.mcb.tex`); take the
        # directory's pooled MCB source when the same-stem file is absent.
        if not any(c.is_file() for c in caption_files):
            # The generated .tex may sit one level up (the copy that ships the
            # table) as well as beside the table.
            for d in (p.parent, p.parent.parent):
                caption_files = [q for q in sorted(d.glob("*.tex"))
                                 if "mcb" in q.name.lower() and "pooled" in q.name.lower()][:1]
                if caption_files:
                    break
        for ext in (".tex", ".ltx", ".md"):
            cq = p.with_suffix(ext)
            if not cq.is_file():
                # The fallback list only helps the .tex branch, and an entry
                # that does not exist must not shadow the .ltx/.md file that
                # DOES: selecting it made the read fail and broke the loop
                # before the real caption was reached.
                if ext != ".tex":
                    continue
                cq = next((c for c in caption_files if c.is_file()), None)
                if cq is None:
                    continue
            try:
                caption = _pooled_table_caption(cq)
            except OSError:
                continue
            break
        for r in body:
            if len(r) <= max(mi, ni, avi):
                continue
            method = str(r[mi]).strip()
            if method not in units:
                continue
            try:
                n_table = int(float(str(r[ni]).strip()))
                mean_table = float(str(r[avi]).strip())
            except ValueError:
                continue
            n_units, mean_units = units[method]
            if n_table >= n_units and abs(mean_table - mean_units) <= max(
                    0.01, 0.005 * abs(mean_units)):
                continue
            cap_quote = ""
            if caption:
                parts = [s.strip() for s in re.split(r"(?<=[.;])\s+", caption) if s.strip()]
                pool_parts = [s for s in parts if re.search(r"(?i)\bpool", s)]
                cap_quote = " ".join(pool_parts or parts[:2])[:240]
            rows.append({
                "rule": "PKG-15", "severity": "high", "fix": "manual",
                "file": p.relative_to(root).as_posix(), "line": 1, "reference": method,
                "detail": (f"this table reports n = {n_table} and mean = {mean_table:g} for "
                           f"{method!r}, while its sibling {units_file.name} carries {n_units} "
                           f"pooled units for that method (mean {mean_units:g})"
                           + (f". Its caption says: \"{cap_quote}\"" if cap_quote else "")
                           + ". A 'pooled' section that uses fewer units than the pooled set "
                           f"changes the means and the ranking. If the reduction is the intended "
                           f"complete-block restriction (a test that needs every method on every "
                           f"unit), the caption and the mean column must SAY so and name the "
                           f"units they use; otherwise the table is computed on the wrong "
                           f"sample set. Two deposited surfaces of one analysis cannot describe "
                           f"different populations under the same word"),
            })
            if len(rows) >= limit:
                return rows
    return rows


def scan_prior_submission_disclosure(root: Path, submitted_docs=None, limit: int = 8) -> list:
    """PKG-14: a cover letter that hides a prior editorial decision in the corpus."""
    root = Path(root)
    feedback = []
    for area in EVIDENCE_DIRNAMES:
        d = root / area
        if not d.is_dir():
            continue
        for p in sorted(_iter_tree_files(d)):
            if not p.is_file() or p.suffix.lower() not in (".txt", ".md", ".html", ".json"):
                continue
            try:
                text = p.read_text("utf-8", "replace")
            except OSError:
                continue
            for m in PRIOR_DECISION_ID_RE.finditer(text[:200000]):
                feedback.append({
                    "file": p.relative_to(root).as_posix(),
                    "journal": m.group(1).strip(),
                    "id": m.group(0),
                    "date": _first_date(text[m.start():m.start() + 4000]),
                    "snippet": text[max(0, m.start() - 400):m.start() + 4000],
                })
                break
    if not feedback:
        return []
    letters = []
    if submitted_docs is not None:
        letters = [rel for rel in submitted_docs
                   if docx_document_role(Path(rel).name) in ("cover", "main")]
    if not letters:
        letters = [p.relative_to(root).as_posix() for p in _iter_tree_files(root)
                   if p.is_file() and p.suffix.lower() in (".docx", ".tex", ".ltx", ".pdf")
                   and docx_document_role(p.name) in ("cover", "main")]
    rows = []
    for rel in sorted(letters):
        p = root / rel
        if p.suffix.lower() == ".docx":
            paras = _docx_paragraphs(p) or []
            text = "\n".join(paras)
        elif p.suffix.lower() == ".pdf":
            text = _pdf_text(p) or ""
        else:
            try:
                text = p.read_text("utf-8", "replace")
            except OSError:
                continue
        if not PRIOR_SUBMISSION_CLAIM_RE.search(text):
            continue
        low = text.lower()
        for f in feedback:
            journal = str(f.get("journal") or "")
            if not journal:
                continue
            # The journal NAME is not a disclosure: the letter is addressed to
            # the journal that issued the decision, so matching the addressee
            # suppressed exactly the flagship case. Only the decision id or its
            # date shows the decision itself was disclosed.
            if str(f.get("id") or "").lower() in low:
                continue
            if f.get("date") and f["date"] in text:
                continue
            if not _same_work(f.get("snippet") or "", text):
                continue
            rows.append({
                "rule": "PKG-14", "severity": "high", "fix": "manual",
                "file": rel, "line": 1,
                "reference": f"{journal} ({f.get('id')})",
                "detail": (f"this letter states that no related manuscript exists / the work "
                           f"is not under consideration elsewhere, while the package itself "
                           f"carries the {journal} editorial decision {f.get('id')}"
                           + (f" dated {f['date']}" if f.get("date") else "")
                           + f" ({f['file']}). The prior submission and its decision are "
                           f"editor-relevant facts the letter must disclose (or the letter's "
                           f"claim must be scoped so it stays true); nothing in the letter "
                           f"mentions them"),
            })
            if len(rows) >= limit:
                return rows
    return rows


def _first_date(text: str) -> str:
    """The first ISO-ish date in `text` ('' when none)."""
    m = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text or "")
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"\b(20\d{2})年(\d{1,2})月(\d{1,2})日", text or "")
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(?i)\b(january|february|march|april|may|june|july|august|september|"
                  r"october|november|december)\s+(\d{1,2}),?\s+(20\d{2})", text or "")
    if m:
        months = ("january february march april may june july august september october "
                  "november december").split()
        return f"{m.group(3)}-{months.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"
    return ""


def _pdf_text_info(path: Path) -> tuple:
    """(text, failure) of a PDF through poppler's `pdftotext`.

    `failure` is "" when the converter SUCCEEDED -- `text` may still be empty,
    which is an image-only PDF. A nonempty failure means the tool did not run,
    timed out, or exited nonzero: the PDF's reader-visible text was never
    examined, so the caller must record a coverage gap, not skip it silently.
    """
    exe = shutil.which("pdftotext")
    if not exe:
        return "", "pdftotext is not installed"
    try:
        proc = subprocess.run([exe, "-layout", str(path), "-"], capture_output=True,
                              timeout=120)
    except subprocess.TimeoutExpired:
        return "", "timed out after 120s"
    except (OSError, subprocess.SubprocessError) as e:
        return "", f"{type(e).__name__}: {e}"
    if proc.returncode == 0:
        return proc.stdout.decode("utf-8", "replace"), ""
    detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
    msg = f"exit {proc.returncode}"
    if detail:
        msg += f": {detail[-1][:200]}"
    return "", msg


def _pdf_text(path: Path) -> str:
    """Reader-visible text of a PDF through poppler's `pdftotext` ('' on failure)."""
    return _pdf_text_info(path)[0]


def non_submitted_reference_rows(root: Path, areas, limit: int = 40) -> list:
    """PKG-2: shipped text files that refer at what the submission does not carry.

    `areas` names the areas THIS package does not carry (the caller derives it
    from what the assembly stripped), so the same scan reports a `code/`
    reference only while the code is not submitted -- with `submit_code: on` a
    `code/` path resolves and is no finding at all. The author's `README*.md` /
    `README*.txt` FILES are never carried by a submission, so a bare
    `README*.md` / `.txt` token -- or one under a relative directory
    (`docs/README.md`) -- in a shipped document is a row unconditionally; a URL
    that merely ends in a README name is not.

    A reference is reported in either of two SHAPES (see the block above this
    function): an area-prefixed path, and a plain file NAME the package carries
    only outside the submission. The name shape is what a supplementary legend
    writes -- "produced by `jf_supplement_analysis.py`, which is distributed with
    the source code ... `hpep-v07.zip`" names two files the submission never
    carries, and no path prefix for a pattern to match.

    Files INSIDE a non-carried area are never scanned as submission documents:
    `code/README_RERUN.md` cites `raw_data/hpep-v07.zip` and `code/out/...` as a
    matter of course -- it is the area's own documentation, not a shipped file
    with a dangling pointer.
    """
    rows, names = [], [str(a) for a in (areas or ())]
    # `work/` is process scratch: it is never carried by the submission (see
    # CORPUS_EXCLUDE_TOP), so a written pointer at it is dangling even though the
    # file exists in the package's working tree.
    names += [n for n in CORPUS_EXCLUDE_TOP if n not in names]
    root = Path(root)
    if not root.is_dir():
        return rows
    area_set = {n.lower() for n in names}
    patterns = _pkg2_area_patterns(names)
    # ONE declaration read for the whole scan: the index and the document filter
    # must agree about the submitted set, and two calls in one walk could read two
    # different trees on a mutating package.
    _decl, is_submitted = declared_submission_filter(root)
    index = _pkg2_name_index(root, area_set, is_submitted=is_submitted)
    declared_patterns = tuple(index[4] if len(index) > 4 else ())
    # PKG-10's exception set: what inside a non-carried area still counts as
    # "treated as if it were in the parent" (a parent-directory file, a file the
    # parent's .tex files input, or a display item whose bytes the submission
    # itself carries). Built once per scan.
    try:
        submitted_now = [pp.relative_to(root).as_posix()
                         for pp in _iter_tree_files(root, follow_dir_links=True)
                         if pp.is_file() and is_submitted(pp.relative_to(root).as_posix())]
    except Exception:                                                 # noqa: BLE001
        submitted_now = []
    try:
        pkg10_exc = area_reference_exceptions(root, names, submitted_now)
    except Exception:                                                 # noqa: BLE001
        pkg10_exc = {"closure": set(), "tex_sources": [], "media": {}}

    def row(rel: str, line_no: int, ref: str, hint: str, resolves=()) -> dict:
        out = {
            "rule": "PKG-2", "file": rel, "line": line_no, "reference": ref,
            "detail": (f"this file is part of the submission but refers at {ref!r}, "
                       f"which the submission does not carry: the journal cannot "
                       f"resolve the reference. Point at shipped content, or replace "
                       f"the pointer with a locator that ships{hint}"),
            "fix": "manual"}
        if resolves:
            out["resolves_to"] = list(resolves)[:3]
        return out

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if not is_submitted(rel):
            # The package's own README declares the submitted set; a file it
            # excludes is not a submission document, so its own pointers are the
            # author's business -- exactly like a file inside `code/`. Without
            # this the non-submitted `.tex`/`.bib` sources were scanned as if the
            # journal would receive them.
            continue
        if rel.split("/", 1)[0].lower() in area_set:
            # A file inside a non-carried area is part of that area, never a
            # submission document: its own internal pointers are not findings.
            continue
        if rel.split("/", 1)[0].lower() in CORPUS_EXCLUDE_TOP:
            # The stage's process scratch is never submitted; a reference in a
            # working note is not a shipped dangling pointer.
            continue
        if is_evidence_rel(rel) or is_non_document_name(p.name) \
                or is_bookkeeping_name(p.name) or is_non_submitted_readme_name(p.name):
            # A README*.md/.txt file is the author's own documentation and never
            # a submitted file: what it points at is the author's business.
            continue
        ext = p.suffix.lower()
        if ext == ".docx":
            # The manuscript the journal actually reads is a .docx: a dangling
            # reference inside it is the defect this scan exists for, and the
            # text-file scan never opened it (a `See raw_data/tables.tsv` in
            # word/document.xml produced no row at all).
            #
            # Its PARTS carry links too: the venue's Word template attaches
            # `file:///C:\Users\<someone>\...\template.dotx`, which a restyled
            # package inherits -- a pointer at a document no reader can open,
            # naming the machine it was authored on (2026-10-15 discovery round).
            _mod = _format_module()
            if _mod is not None and hasattr(_mod, "local_path_link_rows"):
                try:
                    _links = _mod.local_path_link_rows(p)
                except Exception:                                     # noqa: BLE001
                    _links = []
                for _part, _rid, _rtype, _target in _links:
                    rows.append({
                        "rule": "PKG-2", "file": rel, "line": 1, "reference": _target,
                        "part": _part,
                        "detail": (f"the package part {_part} links to the local path "
                                   f"{_target!r}: a reader (the journal, a reviewer, a "
                                   f"rebuild) cannot open it, and it names the machine that "
                                   f"authored it. The orchestrator removes an "
                                   f"attached-template link; any other local-path link is "
                                   f"the author's to repoint"),
                        "fix": "manual"})
                    if len(rows) >= limit:
                        return rows
            lines = _docx_paragraphs(p)
            if lines is None:
                continue
        elif ext in PACKAGE_TEXT_EXTS:
            try:
                if p.stat().st_size > PACKAGE_TEXT_BYTES_LIMIT:
                    continue
                text = p.read_text("utf-8", "replace")
            except OSError:
                continue
            lines = text.splitlines()
        elif ext == ".pdf":
            # The journal reads the shipped PDF; PKG-6..9 already open it with
            # the same pdftotext reader, but PKG-2..5 never did -- a dangling
            # raw_data/ pointer in a PDF main text was invisible.
            text = _pkg_text_of_doc(p)
            if not text.strip():
                continue
            lines = text.splitlines()
        else:
            continue
        for i, line in enumerate(lines, 1):
            # EVERY reference on the line, not the first pattern's first hit:
            # the area pattern runs first, so `See README.md and also
            # raw_data/tables.tsv.` used to report only the area path, and a
            # second reference (the same class the scan exists for) was lost.
            found = [mm for pat in patterns for mm in pat.finditer(line)]
            # The area pattern's span covers a README under it
            # (`code/README.md`): that is ONE reference, named by the longer
            # match, not a second finding.
            found.sort(key=lambda mm: (mm.start(), -(mm.end() - mm.start())))
            kept = []
            for mm in found:
                if _pkg2_url_query_value(line, mm.start()):
                    continue
                if any(k.start() <= mm.start() and mm.end() <= k.end() for k in kept):
                    continue
                kept.append(mm)
            for m in kept:
                ref = m.group(0)
                # BOTH separators: the area pattern accepts a backslash
                # (`raw_data\tables.tsv`), and splitting on "/" alone read the
                # whole reference as the "head", so the row's advice named the
                # README rule for a raw_data pointer.
                # PKG-10: the operator's own rule for these packages exempts a
                # reference into the area when the target is a parent-directory
                # file, a file the parent's .tex sources input (recursively), or
                # a figure/table whose bytes the submission itself carries.
                _exempt, _why = pkg10_reference_exempt(root, ref, pkg10_exc)
                if _exempt:
                    continue
                out = row(rel, i, ref, _pkg2_hint(ref, area_set, declared_patterns))
                out["area_rule"] = "PKG-10"
                rows.append(out)
                if len(rows) >= limit:
                    return rows
            # The NAME shape: a written filename that resolves, inside this very
            # package, only to material the submission does not carry. A name
            # already covered by an area/README match (any overlap) is that one
            # reference, not a second finding.
            for m in PKG2_NAME_RE.finditer(line):
                if any(k.start() < m.end() and m.start() < k.end() for k in kept):
                    continue
                if _pkg2_url_query_value(line, m.start()):
                    continue
                reason, where = _pkg2_name_resolution(m.group(0), index)
                if reason == "unknown":
                    # PKG-3 (2026-10-15): the document names a FILE this package
                    # carries NOWHERE -- not in the submission, not in `code/`,
                    # not in `raw_data/`. That is the other half of the operator's
                    # report: the CopyNumBench Methods says the generators are "in
                    # `data3from2.py`", and no reader (the journal, a reviewer, a
                    # rebuild) can resolve that name, because the package never
                    # carries it. A name that resolves somewhere the reader cannot
                    # reach is PKG-2 (removable: the material is at hand); a name
                    # that resolves NOWHERE is REPORTED ONLY -- the pipeline cannot
                    # know whether the sentence should carry the file, a locator
                    # instead, or neither, and deleting a Methods sentence about
                    # where the analysis lives would destroy real information. The
                    # sentence therefore reaches the review/revise evidence pack
                    # (`submission_references`) for a rewriting agent to resolve,
                    # and the package readiness lists it so it cannot ship unseen.
                    # The pointer must be WRITTEN as a pointer ("in X.py",
                    # "produced by X.py"), not merely listed as an inventory row
                    # or a command line, and neither its sentence NOR the
                    # paragraph it sits in may locate the material elsewhere
                    # ("archived alongside them as hpep/aggregate.txt" resolves at
                    # the repository URL the same paragraph carries). Without both
                    # filters a benchmark appendix that documents a public
                    # pipeline's own file layout produced 30 rows for files the
                    # appendix never promises to ship.
                    if not PKG3_POINTER_VERB_RE.search(line[:m.start()].rsplit(". ", 1)[-1]):
                        continue
                    if not _pkg3_prose_document(rel):
                        continue
                    if _sentence_has_locator(line, m.start(), m.end(), PKG3_LOCATOR_RE) \
                            or PKG3_LOCATOR_RE.search(line):
                        continue
                    rows.append({
                        "rule": "PKG-3", "file": rel, "line": i, "reference": m.group(0),
                        "resolution": "unknown", "severity": "advisory",
                        "detail": (f"this file is part of the submission but names "
                                   f"{m.group(0)!r}, and the package carries no file with that "
                                   f"name anywhere (not in the submission, not in the analysis "
                                   f"code, not in the raw data): the journal, a reviewer and a "
                                   f"rebuild all get a name nobody can resolve. Ship the file, "
                                   f"replace the name with a locator, or drop the pointer"),
                        "fix": "manual"})
                    if len(rows) >= limit:
                        return rows
                    continue
                if reason != "absent":
                    continue
                if _pkg2_external_locator(line, m.start(), m.end()):
                    # The sentence sends the reader to a repository/DOI/archive:
                    # the pointer resolves there, so this is not a finding (the
                    # package merely happens to carry a same-named copy).
                    continue
                # PKG-10's exception for the name shape: when EVERY place the
                # package holds this name is "treated as in the parent" (a
                # parent-directory file, a file the parent .tex inputs, or a
                # display item the submission embeds), the written name resolves
                # for the reader and is not a dangling pointer.
                _exempts = [pkg10_reference_exempt(root, w, pkg10_exc)[0] for w in where]
                if _exempts and all(_exempts):
                    continue
                _out = row(rel, i, m.group(0),
                           _pkg2_hint(where[0], area_set, declared_patterns),
                           resolves=where)
                if any(str(w).split("/", 1)[0].lower() in area_set for w in where):
                    _out["area_rule"] = "PKG-10"
                rows.append(_out)
                if len(rows) >= limit:
                    return rows
    return rows


def _pkg2_area_patterns(names: list) -> list:
    """The area-path and README-name patterns for one set of not-carried areas."""
    patterns = []
    if names:
        patterns.append(re.compile(
            # `=` is allowed (a URL-query value is filtered by
            # `_pkg2_url_query_value`, so `SRC=code/analysis.py` IS reported);
            # `+` and a backslash separator are ordinary filename characters in
            # a path (`code/foo+bar.py`, `raw_data\tables.tsv`), and without them
            # the row named a path that does not exist ("code/foo"). ONE space is
            # allowed inside the name, and only when a dot-carrying filename
            # follows it ("raw_data/my table.tsv"): the row must name the
            # reference the author wrote, and a bare word after the space
            # ("raw_data/ and methods.md") still stops at the space.
            r"(?<![\w./\\&?#-])(?:" + "|".join(re.escape(n) for n in names)
            + r")[/\\][\w.\-+\\/]*[\w](?:\s+[\w\-+]+(?:\.[\w\-+]+)+)?", re.I))
    # A README name, bare or under a relative directory (`docs/README.md`): the
    # boundary guard keeps a URL tail (`https://host/repo/README.md`) out of the
    # report, and a path into another area (`raw_data/README.md`) is already
    # matched by that area's pattern above.
    #
    # The name class is the stripper's own (`is_non_submitted_readme_name`
    # removes every `readme*.(md|txt)` basename): a name it drops must still be
    # REPORTED, so `README+.md` / `README(notes).md` count, while a SPACE stays
    # out -- allowing whitespace here would bridge unrelated prose ("README and
    # methods.md"). The trailing guard admits a sentence-final period, the
    # normal way these names appear in running text, but not a longer filename
    # (`README.md.bak`); `=&?#` keeps a URL's query/fragment value out.
    patterns.append(re.compile(
        r"(?<![\w./\\&?#-])(?:[\w.\-+()]+/)*README[\w.\-+()]*\.(?:md|txt)"
        r"(?![\w\-/]|\.\w)", re.I))
    if names:
        # The AREA ITSELF, written with no file behind the separator: a bare
        # `code/` (nothing after the slash) and the prose spelling "the code
        # directory" / "the raw_data folder". The 2026-10-15 report was exactly
        # this -- "the supplementary material refers to the `code` directory" --
        # a pointer with no filename for the other patterns to match.
        joined = "|".join(re.escape(n) for n in names)
        patterns.append(re.compile(
            r"(?<![\w./\\&?#-])(?:" + joined
            + r")[/\\](?![^\s.,;:)\]}\u201d\u2019\"'])", re.I))
        patterns.append(re.compile(
            r"(?<![\w./\\&?#-])(?:" + joined + r")[/\\]?\s+(?:director(?:y|ies)|"
            r"folder|dir)\b", re.I))
    return patterns


def _pkg2_hint(ref: str, area_set: set, declared_patterns=()) -> str:
    """The one-fact reason a reference cannot be resolved, for the row's advice.

    `ref` is what the author wrote (`code/out/x.csv`) or where the package
    actually carries a bare name (`code/jf_supplement_analysis.py`), so one
    function covers both shapes -- and the prose spelling of an area itself
    ("code directory", "raw_data/"), where the area word is the first token.
    When the package's own README declares a submission pattern, the row says so:
    the file exists in the package but is not part of the submission.
    """
    parts = re.split(r"[/\\\s]", str(ref))
    head = (parts[0] or "").lower()
    base = parts[-1]
    if is_non_submitted_readme_name(base):
        # `set-submit-code on` does not resurrect a README, so the code switch is
        # the wrong advice in BOTH states.
        return (" (the author's README*.md/README*.txt files are never submitted)")
    if head == CODE_DIR:
        return " (the analysis code ships only when `set-submit-code on` asks for it)"
    if head in area_set:
        return " (that area is a read-only input: it never ships)"
    if is_bookkeeping_name(base) or _is_aux_doc(base) or is_word_owner_name(base):
        return (" (it is one of the pipeline's own by-product files, which never ship)")
    if declared_patterns:
        # Nothing in the standing model explains it: the package's own README
        # does. This is the 2026-10-15 gap -- a `.tex`/`.bib` source, a
        # `supplementary_source_files/…` asset or any other carried file the
        # declared submission set leaves out.
        return (f" (the package's own README declares only "
                f"{' / '.join(f'`{p}`' for p in declared_patterns[:2])} as submitted; this "
                f"file is carried by the package but is NOT part of that set)")
    return " (the author's README*.md/README*.txt files are never submitted)"


# --- PKG-2 repair: REMOVE the dangling reference ------------------------------
#
# Reporting a pointer the reader can never resolve is not enough: the submission
# must not CARRY one (AGENTS.md: "nothing that ships points at what does not
# ship", and the 2026-10-15 operator decision -- remove the pointer instead of
# shipping it dangling). The repair is mechanical, coarse and verifiable:
#   * only to-be-submitted DOCUMENTS are edited (never an evidence area, never
#     `code/`, never a by-product a submission never carries);
#   * the unit is the SENTENCE that carries the pointer, never a splice inside
#     it (a removed half-sentence reads as damage);
#   * structural files (`.csv`, `.json`, `.bib`, ...) are NOT edited -- deleting
#     a row/key can break the file -- and stay reported for the author;
#   * every removal is recorded VERBATIM and the result is re-scanned: a file
#     that does not come back clean is reported, never quietly left different.
PKG2_EDITABLE_TEXT_EXTS = (".md", ".markdown", ".txt", ".rst", ".tex", ".ltx")
# The response-to-reviewers letter is the AUTHORS' statement, and its own
# postcheck already FAILS an attempt that cites a non-submitted file (the letter
# prompt forbids it outright). Deleting a sentence from a signed point-by-point
# letter at assembly time could break the concern-by-concern mapping, so the
# letter is REPORTED (it stays in the `remaining` re-scan) and never edited here.
PKG2_NEVER_EDITED_NAMES = frozenset({
    Path(JOURNAL_RESPONSE_MD_REL).name, Path(JOURNAL_RESPONSE_MAP_REL).name,
})


def pkg2_reference_spans(text: str, patterns: list, index: tuple, exempt=None) -> list:
    """[(start, end)] of the PKG-2 references inside ONE text (paragraph or file).

    The detector's rules, expressed over a string instead of over a walk: the
    area/README patterns plus the name shape resolved against the package's own
    file names. The repair uses it to widen a reference to its sentence.

    `exempt(ref) -> bool` is PKG-10's exception test: a reference the operator's
    raw-area rule treats as carried (a parent-directory file, a file the parent's
    .tex sources input, or a display item the submission embeds) must NOT be
    stripped from the prose -- the reader can reach it.
    """
    spans = []
    for pat in patterns:
        for m in pat.finditer(text):
            if _pkg2_url_query_value(text, m.start()):
                continue
            if exempt is not None and exempt(m.group(0)):
                continue
            spans.append((m.start(), m.end()))
    for m in PKG2_NAME_RE.finditer(text):
        if any(a < m.end() and m.start() < b for a, b in spans):
            continue
        if _pkg2_url_query_value(text, m.start()):
            continue
        reason, where = _pkg2_name_resolution(m.group(0), index)
        if reason == "absent":
            if exempt is not None and where and all(exempt(w) for w in where):
                continue
            if not _pkg2_external_locator(text, m.start(), m.end()):
                spans.append((m.start(), m.end()))
    return sorted(set(spans))


def _pkg2_build_index(dirp: Path, areas) -> tuple:
    names = [str(a) for a in (areas or ())]
    # Process scratch is not shipped (CORPUS_EXCLUDE_TOP), so its files are
    # "absent" for reference resolution -- a shipped sentence pointing into
    # `work/` is dangling exactly like one pointing into `raw_data/`.
    names += [n for n in CORPUS_EXCLUDE_TOP if n not in names]
    return (_pkg2_area_patterns(names),
            _pkg2_name_index(dirp, {n.lower() for n in names}))


# A line that is a HEADING, not part of the sentence under it. Text documents
# (`.md`, `.txt`, `.tex`, `.rst`) put these on their own line, and the sentence
# splitter cannot see the boundary: without this, removing the sentence that
# carries `We ran code/analysis.py ...` also deleted the `Methods` heading line
# above it.
PKG2_HEADING_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s+\S"                       # Markdown heading
    r"|\*\*[^*]+\*\*\s*$"                        # a bold-only heading line
    r"|\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\s*(?:\{[^}]*\})?\s*$"   # \section{Methods}
    r"|[A-Z][A-Za-z0-9 ,/&()\-]{0,38}$"          # Methods / Data availability
    r"|[A-Z0-9][A-Z0-9 ,/&()\-]{0,38}$)")        # DATA AVAILABILITY


def is_heading_line(line: str) -> bool:
    """True for a short heading-like line (<= 3 words, no sentence punctuation)."""
    s = str(line or "").strip()
    if not s or len(s.split()) > 3 or s[-1] in ".!?:;,":
        return False
    return bool(PKG2_HEADING_LINE_RE.match(s))


def is_structural_reference_line(before: str) -> bool:
    """True when a reference is a document INCLUDE, not prose.

    `\\includegraphics{raw_data/Fig1.png}`, `\\input{code/x.tex}`,
    `![f](code/out/figS3.png)`, `[x](raw_data/t.csv)` and a Markdown reference
    definition (`[x]: code/y.py`) name a file the document *uses*: deleting the
    sentence that carries one would delete the include and change what the
    document renders. Those references are REPORTED (the re-scan lists them as
    remaining) and left for the author, who can repoint, ship or drop the
    include deliberately -- a prose pointer, by contrast, is removed.
    """
    before = str(before or "")
    if re.search(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])*\{[^{}]*$", before):
        return True                      # LaTeX command argument
    if re.search(r"\]\(\s*[^)]*$", before):
        return True                      # Markdown link/image target
    if re.match(r"^\s*\[[^\]]*\]:\s*\S*$", before):
        return True                      # Markdown reference definition
    return False


_FACT_LABEL_RE = re.compile(
    r"\b(?:fig(?:ure)?|table|section|eq(?:uation)?|appendix|supp(?:lementary)?)\.?\s*"
    r"[A-Za-z]?\d+[A-Za-z0-9.-]*", re.I)
# `Data S2` / `Code S1` are labels; `data 12` states a count. Requiring the
# supplementary letter keeps the count in the fact test (the old shared pattern
# stripped "data 12"/"code 45" and then saw no digit).
_FACT_DATA_LABEL_RE = re.compile(r"\b(?:data|code)\.?\s*[ST]\d+[A-Za-z0-9.-]*", re.I)
# Fallback when the formatter module is not beside the driver: a number word
# *might* be a count, so keep the sentence (never silently delete a fact)
# rather than guess it away.
_SPELLED_NUMBER_RE = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"billion|trillion)\b", re.I)


def _spelled_number_is_count(text: str) -> bool:
    """True when `text` states a spelled-out COUNT (not "one of them", "no one").

    The formatter's word-number ledger already decides this for the M30 scan;
    sharing it keeps the PKG-2 fact test from calling every "one" a numeric
    fact (which held an ordinary dangling-reference sentence for a rewrite and
    blocked readiness on a sentence that carried no number).
    """
    mod = _format_module()
    if mod is None or not hasattr(mod, "NUMBER_WORD_RE"):
        return bool(_SPELLED_NUMBER_RE.search(text))
    for m in mod.NUMBER_WORD_RE.finditer(text):
        if mod._word_number_is_count(text, m.start(), m.end(), m.group(1).strip()):
            return True
    return False


def sentence_carries_scientific_fact(text: str) -> bool:
    """True when a sentence carries a number outside a figure/table/section label.

    The PKG-2 mechanical removal is a packaging repair, not a finding
    resolution: a sentence that carries a measured value, count, p-value or
    other numeric fact must be rewritten by the revision, not silently deleted.
    A bare label (`Figure S3`, `Table 2`, `Data S1`) is not a fact.
    """
    stripped = _FACT_LABEL_RE.sub(" ", str(text or ""))
    stripped = _FACT_DATA_LABEL_RE.sub(" ", stripped)
    return bool(re.search(r"\d", stripped) or _spelled_number_is_count(stripped))


def _drop_reference_sentences_text(text: str, spans: list) -> tuple:
    """(new_text, removed, structural, held): the prose SENTENCES of a text document.

    `drop_sentences` with two text-document rules: a heading line the reference
    does not touch is never swallowed (a heading is not part of the sentence
    under it), so `Methods\\nWe ran code/analysis.py ...` loses only its second
    line; and a sentence carrying a numeric fact is KEPT (returned in `held`)
    so the caller can report it for a prose rewrite instead of deleting the
    fact. A reference that is a document INCLUDE rather than prose
    (`\\includegraphics{...}`, a Markdown link target) is left alone entirely:
    it comes back in `structural` so the caller reports it
    (`is_structural_reference_line`). Everything else is the shared sentence
    machinery.
    """
    mod = _format_module()
    text = text or ""
    prose, structural, held = [], [], []
    for s, e in sorted(tuple(x) for x in (spans or ())):
        line_start = text.rfind("\n", 0, s) + 1
        (structural if is_structural_reference_line(text[line_start:s])
         else prose).append((s, e))
    windows = []
    for a, b in (mod.sentence_windows(text, prose, eat_whitespace=False)
                 if mod is not None else ()):
        # The window may OPEN on a heading line or on a LaTeX command line the
        # reference does not sit on (`\includegraphics{...}\nWe ran code/a.py`):
        # neither is part of the sentence under them.
        while True:
            line_end = text.find("\n", a)
            if line_end < 0 or line_end >= b:
                break
            if any(a <= s and s < line_end for s, _e in prose):
                break
            if not (is_heading_line(text[a:line_end])
                    or text[a:line_end].lstrip().startswith("\\")):
                break
            a = line_end + 1
        # ... and it may CLOSE on one: `We ran code/a.py\n\includegraphics{...}`
        # has no sentence break between them, and deleting the include would
        # change what the document renders.
        while b > a:
            line_start = text.rfind("\n", 0, b) + 1
            if line_start <= a:
                break
            line = text[line_start:b]
            if any(line_start <= s < b for s, _e in prose):
                break
            if not (line.lstrip().startswith("\\")
                    or any(line_start <= s < b for s, _e in structural)):
                break
            b = line_start - 1 if text[line_start - 1:line_start] == "\n" else line_start
        # A mid-line removal must not leave the space that used to separate the
        # sentence from its neighbour ("... the benchmark. The command is in
        # code/x.py." -> "... the benchmark." and not "... the benchmark. ").
        while a > 0 and text[a - 1] in " \t":
            a -= 1
        if b > a:
            if sentence_carries_scientific_fact(text[a:b]):
                # Keep the fact and report the pointer; a mechanical deletion
                # must not turn a data statement into a clean-looking package.
                held.append((a, b))
            else:
                windows.append((a, b))
    if not windows:
        return (text, [], [text[s:e] for s, e in structural],
                [text[s:e] for s, e in held])
    out, removed, pos = [], [], 0
    for a, b in windows:
        out.append(text[pos:a])
        removed.append(text[a:b].strip())
        pos = b
    out.append(text[pos:])
    return ("".join(out), removed, [text[s:e] for s, e in structural],
            [text[s:e] for s, e in held])


def strip_dangling_references_in_dir(dirp: Path, areas, label: str,
                                     warns: list = None,
                                     artifacts_dir: Path = None,
                                     artifact_name: str = None) -> dict:
    """Remove every dangling reference the PKG-2 scan finds in `dirp`'s documents.

    Returns {"label", "areas", "files": [{"file", "removed": [sentence, ...],
    "skipped": [reason, ...]}], "removed": n, "skipped": n, "remaining": [row, ...],
    "ok": bool}. `remaining` is the re-scan of the repaired tree: a non-empty list
    means something the mechanical layer may not touch is still dangling (a
    structural file, a sentence carrying a live citation field, or a sentence
    carrying a numeric fact held for a prose rewrite), and the caller reports
    it as an author action.

    The orchestrator's own artifact (`artifacts_dir`) receives the FULL record --
    the removed sentences verbatim -- because a top-level JSON inside the package
    would become submission content. Nothing is deleted from an evidence area,
    from `code/` or from a file a submission never carries.
    """
    dirp = Path(dirp)
    report = {"label": label, "areas": [str(a) for a in (areas or ())],
              "files": [], "removed": 0, "removed_links": 0, "skipped": 0,
              "remaining": [], "ok": True}
    if dirp.is_symlink():
        # `rglob` follows the root link, so the loop below would rewrite
        # documents in the TARGET tree. The package root is a real directory;
        # a link is never the stage's own package to edit.
        report["skipped_note"] = f"{dirp} is a symlink; refusing to rewrite through it"
        report["ok"] = False
        return report
    if not dirp.is_dir():
        report["skipped_note"] = f"{dirp} is not a directory"
        return report
    patterns, index = _pkg2_build_index(dirp, areas)
    mod = _format_module()
    area_set = {str(a).lower() for a in (areas or ())}
    # PKG-10: the references the operator's raw-area rule treats as carried are
    # never stripped (the reader can reach them), so the mechanical layer and the
    # report agree on what a dangling pointer is.
    try:
        _decl, _is_sub = declared_submission_filter(dirp)
        pkg10_exc = area_reference_exceptions(
            dirp, [str(a) for a in (areas or ())],
            [q.relative_to(dirp).as_posix() for q in _iter_tree_files(dirp)
             if q.is_file() and _is_sub(q.relative_to(dirp).as_posix())])
    except Exception:                                                 # noqa: BLE001
        pkg10_exc = {"closure": set(), "tex_sources": [], "media": {}}

    def _exempt_ref(ref: str) -> bool:
        return pkg10_reference_exempt(dirp, ref, pkg10_exc)[0]

    for p in sorted(dirp.rglob("*")):
        if not p.is_file():
            continue
        if p.is_symlink():
            # A document symlink points at a file this package does not own:
            # `read_text`/`write_text` would rewrite the target. The link is
            # reported by the re-scan, never edited.
            continue
        rel = p.relative_to(dirp).as_posix()
        if rel.split("/", 1)[0].lower() in area_set or is_evidence_rel(rel):
            continue
        if rel.split("/", 1)[0].lower() in CORPUS_EXCLUDE_TOP:
            # `work/` is the stage's own process scratch (the same exclusion
            # every delivered-content scan and corpus manifest uses). Editing it
            # destroyed working notes and reported scratch references as author
            # actions; only the bytes that ship are the pointer repair's object.
            continue
        if is_word_owner_name(p.name) or _is_aux_doc(p.name) or is_bookkeeping_name(p.name) \
                or is_non_submitted_readme_name(p.name):
            # The author's own README*.md/.txt files are never submitted: editing
            # one would rewrite the author's documentation to satisfy a submission
            # rule that does not apply to it.
            continue
        if p.name in PKG2_NEVER_EDITED_NAMES:
            # Reported (the re-scan lists it), never edited -- see the constant.
            try:
                if pkg2_reference_spans(p.read_text("utf-8", "replace"), patterns, index,
                                        exempt=_exempt_ref):
                    entry = {"file": rel, "removed": [],
                             "skipped": ["the response-to-reviewers letter is the authors' "
                                         "statement: reported, never edited"]}
                    report["files"].append(entry)
                    report["skipped"] += 1
            except OSError:
                pass
            continue
        ext = p.suffix.lower()
        entry = {"file": rel, "removed": [], "skipped": []}
        try:
            if ext == ".docx":
                if mod is None or not hasattr(mod, "strip_reference_sentences"):
                    entry["skipped"].append("the OOXML engine is unavailable")
                else:
                    tmp_out = p.with_name(p.name + ".pkg2.tmp")
                    try:
                        # 1. A local-path link the package carries (the venue
                        #    template's attachedTemplate): removed together with
                        #    its own relationship.
                        if hasattr(mod, "strip_local_path_links"):
                            link_res = mod.strip_local_path_links(p, tmp_out)
                            if link_res.get("ok") and link_res.get("removed"):
                                os.replace(tmp_out, p)
                                entry.setdefault("removed_links", []).extend(
                                    f"{r.get('part')}: {r.get('target')}"
                                    for r in link_res["removed"])
                            else:
                                if link_res.get("error"):
                                    entry["skipped"].append(f"docx link: {link_res['error']}")
                        # 2. The sentence that carries a text pointer.
                        res = mod.strip_reference_sentences(
                            p, tmp_out,
                            lambda t: pkg2_reference_spans(t, patterns, index,
                                                           exempt=_exempt_ref))
                        if res.get("ok") and res.get("removed"):
                            os.replace(tmp_out, p)
                            entry["removed"] = [r.get("sentence") for r in res["removed"]]
                        else:
                            if res.get("error"):
                                entry["skipped"].append(f"docx: {res['error']}")
                            entry["skipped"].extend(res.get("skipped") or [])
                    finally:
                        # A half-written `.pkg2.tmp` must never stay inside the
                        # package (it would become corpus content).
                        if tmp_out.exists():
                            tmp_out.unlink()
            elif ext in PKG2_EDITABLE_TEXT_EXTS:
                text = None
                try:
                    if p.stat().st_size > PACKAGE_TEXT_BYTES_LIMIT:
                        entry["skipped"].append("the file is too large to repair")
                    else:
                        text = p.read_text("utf-8")
                except (OSError, UnicodeDecodeError) as e:
                    entry["skipped"].append(f"{type(e).__name__}: {e}")
                if text is not None and mod is not None and hasattr(mod, "sentence_windows"):
                    spans = pkg2_reference_spans(text, patterns, index, exempt=_exempt_ref)
                    if spans:
                        new_text, removed, structural, held = _drop_reference_sentences_text(
                            text, spans)
                        if removed:
                            after_spans = pkg2_reference_spans(new_text, patterns, index,
                                                               exempt=_exempt_ref)
                            if len(after_spans) < len(
                                    pkg2_reference_spans(text, patterns, index,
                                                         exempt=_exempt_ref)):
                                write_text_atomic(p, new_text)
                                entry["removed"] = removed
                            else:
                                entry["skipped"].append(
                                    "the edit would not reduce the reference count; left to "
                                    "the author")
                        for ref in held:
                            entry["skipped"].append(
                                f"{ref!r} carries a numeric fact and a dangling reference: "
                                f"the fact was KEPT and the pointer must be rewritten in "
                                f"prose")
                        for ref in structural:
                            entry["skipped"].append(
                                f"{ref!r} is a document INCLUDE (a command argument or a "
                                f"link target), not prose: the author repoints it at shipped "
                                f"content or drops the include deliberately")
            elif ext in PACKAGE_TEXT_EXTS:
                try:
                    text = p.read_text("utf-8", "replace")
                except OSError:
                    text = ""
                if pkg2_reference_spans(text, patterns, index, exempt=_exempt_ref):
                    entry["skipped"].append(
                        "a structural file (deleting a row/key would break it); the author "
                        "repairs it")
            else:
                continue
        except Exception as e:                                        # noqa: BLE001
            entry["skipped"].append(f"{type(e).__name__}: {e}")
        if entry["removed"] or entry["skipped"] or entry.get("removed_links"):
            report["files"].append(entry)
        report["removed"] += len(entry["removed"])
        report["removed_links"] += len(entry.get("removed_links") or [])
        report["skipped"] += len(entry["skipped"])
    # `remaining` keeps the PKG-2 meaning: a pointer at material the package
    # HOLDS but the submission does not carry, which the mechanical removal could
    # not take out (a structural file, a sentence carrying a live citation
    # field, or a numeric fact held for a prose rewrite).
    # The rows this scan also reports for a name the package carries NOWHERE
    # (`PKG-3`: a script named in Methods that no file in the package matches) are
    # NOT removals the pipeline may attempt, and they must not make this repair
    # report itself "not clean" (2026-10-15: `ok` is a stage-postcheck input, and
    # an advisory name would have failed a stage that had nothing to fix). They
    # travel in their own key, and the publish-time package scan + readiness
    # report them as advisory rows.
    _scan = non_submitted_reference_rows(dirp, report["areas"])
    report["remaining"] = [r for r in _scan if (r.get("rule") or "PKG-2") == "PKG-2"]
    report["advisory"] = [r for r in _scan if (r.get("rule") or "PKG-2") != "PKG-2"]
    report["ok"] = not report["remaining"]
    if warns is not None:
        if report["removed"]:
            warns.append(
                f"PKG-2: {report['removed']} dangling reference(s) were REMOVED from "
                f"{label}'s to-be-submitted document(s) (a to-be-submitted file may not "
                f"point at what the submission does not carry): "
                + "; ".join(f"`{f['file']}`: {len(f['removed'])} sentence(s)"
                            for f in report["files"] if f["removed"]))
        if report["removed_links"]:
            warns.append(
                f"PKG-2: {report['removed_links']} local-path link(s) (an attached Word "
                f"template pointing at somebody's own machine) were REMOVED from "
                f"{label}'s package part(s): "
                + "; ".join(f"`{f['file']}`: {len(f['removed_links'])} link(s)"
                            for f in report["files"] if f.get("removed_links")))
        if report["remaining"]:
            warns.append(
                f"PKG-2: {len(report['remaining'])} dangling reference(s) could NOT be "
                f"removed mechanically (a structural file or a sentence carrying a live "
                f"citation field): the author must repair them -- "
                + "; ".join(f"{r['file']} line {r['line']}: {r['reference']}"
                            for r in report["remaining"][:4]))
    if artifacts_dir is not None and (report["removed"] or report["removed_links"]
                                      or report["remaining"]):
        name = artifact_name or f"PKG2_{label}.json"
        try:
            write_json_atomic(Path(artifacts_dir) / name, report)
        except OSError:
            pass
    return report


def internal_artifact_rows(root: Path, limit: int = 40) -> list:
    """PKG-1: shipped files that carry the pipeline's/author's internal material.

    Evidence areas (`raw_data/`, the feedback areas) are the author's own
    provenance and are never read as prose, so they are skipped -- the rule is
    about the SUBMISSION surface (and the case that prompted it sat at the
    corpus top level as `raw_data.README.md`). Rows never delete anything: the
    author decides whether a file is removed or rewritten.

    The scan covers every text file the package calls manuscript-side content
    (`code/` included: a revision session writes `code/README.md` there, and the
    2026-10-15 neohet package shipped one naming its review round's own item
    ids). It is NOT scoped to the declared submitted set -- a file the package
    carries, that a READER can open, is part of what the package hands over,
    whichever glob its name matches.
    """
    rows, seen = [], set()
    root = Path(root)
    if not root.is_dir():
        return rows
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if is_evidence_rel(rel):
            continue
        if is_author_to_complete_readme_name(p.name):
            # The deliberate hand-off checklist of `author_to_complete: readme`.
            # It is the author's surface, not a leaked stage note: scanning it
            # for the pipeline's vocabulary would flag the very file the mode
            # exists to produce (and it never ships anyway -- README*.md).
            continue
        if p.suffix.lower() not in PACKAGE_TEXT_EXTS:
            continue
        try:
            if p.stat().st_size > PACKAGE_TEXT_BYTES_LIMIT:
                continue
            text = p.read_text("utf-8", "replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for label, pattern in INTERNAL_ARTIFACT_RES:
                m = pattern.search(line)
                if not m:
                    continue
                key = (rel, label)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "rule": "PKG-1", "severity": "high", "file": rel, "line": i,
                    "evidence": f"{line.strip()[:160]!r}: {label}",
                    "detail": "this file is part of the submission package but carries "
                              "internal working material (an internal review session, the "
                              "pipeline's own ledger/report, or a stage note); a reviewer "
                              "reading it sees how the package was produced instead of the "
                              "science -- remove the file or strip the internal text",
                    "fix": "manual"})
                if len(rows) >= limit:
                    return rows
    return rows


def package_front_matter_glue_rows(root: Path, limit: int = 20) -> list:
    """FMT-X2 rows that SURVIVED the published copy's own repair.

    The mechanical half of FMT-X2 inserts the space a fused front matter lost
    (the label's colon; an address glued to the word before it when the address's
    own local part ends that word). The other shape -- `<Name><address>` fused
    inside ONE token, as in `* Correspondence:Zhen Xiezhenxie@tsinghua.edu.cn` --
    cannot be split without knowing where the name ends, so it is REPORTED here
    for the author instead of being re-spaced by guesswork. Only the front matter
    is scanned: that is where a correspondence block lives.
    """
    rows = []
    mod = _format_module()
    root = Path(root)
    if mod is None or not hasattr(mod, "correspondence_glue_rows") or not root.is_dir():
        return rows
    _decl, _decl_is_submitted = declared_submission_filter(root)
    for p in sorted(root.rglob("*.docx")):
        if not p.is_file() or is_non_document_name(p.name) or _is_aux_doc(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        if is_evidence_rel(rel) or not _decl_is_submitted(rel):
            continue
        try:
            paras = _docx_paragraphs(p)
        except Exception:                                             # noqa: BLE001
            continue
        if not paras:
            continue
        for r in mod.correspondence_glue_rows(paras[:14], [False] * min(14, len(paras))):
            rows.append(dict(r, document=p.relative_to(root).as_posix(), stage="published"))
            if len(rows) >= limit:
                return rows
    return rows[:limit]


# PKG-6..9 (2026-10-15): the CONTRADICTION class.
#
# The operator's result-driven audit of the two delivered packages found three
# internal contradictions that no rule could see, because every existing rule
# compares one surface against ITSELF (a legend against its figure, a reference
# against its own entry) or against the raw data -- none compares two statements
# the same submission makes about its own method, disclosure or identifiers:
#
#   * PKG-6 -- a document says the manuscript was drafted "without generative
#     AI" and, in the same section, describes running a generative-AI revision
#     workflow over it. Both packages shipped that pair (the cover letter AND
#     the methods/acknowledgements), and a reviewer read it as a disclosure
#     defect. The rule is local to ONE text (the two statements must be close),
#     so it never fires from two unrelated use sites.
#   * PKG-7 -- an identifier is DEFINED and USE-d at different lengths in the
#     same package: the Reporting Summary printed the scRNA commit as
#     `c30bc1ab52f083b5761e31bec6888d7f2fd` (35 hex) while the main text carried
#     the full 40. A truncated commit is not the commit: a reader who resolves it
#     gets no object (here it also broke the URL, which the PDF wrapped).
#   * PKG-8 -- the same statistical comparison is described with two different
#     units: the supplementary figures' caption said "pairwise comparisons used
#     606-1,989 paired cells" while Table S2's own note defined n as "the number
#     of donors whose paired differences ... enter the test" (n = 9). A reader
#     cannot tell which analysis was run.
#
# All three BLOCK the submission-readiness verdict, like PKG-5: one of the two
# statements is false (or the identifier is unusable) and only the AUTHOR can
# say which, but a package that carries the pair is not one to upload. The
# pipeline never rewrites either side -- it seeds the rows into every session's
# evidence pack so the review/revise arms can repair the prose, and reports
# them in the delivered status, `readiness.findings` and the console.

# The unit names the two halves of a statistical statement can disagree about.
# Deliberately short: a unit outside this list is reported nowhere, because the
# rule has no way to know that "chips" and "libraries" are not the same thing.
STATS_UNITS = ("cells", "donors", "patients", "samples", "organoids", "mice",
               "libraries", "chips")


def _pkg_text_of_doc(p: Path) -> str:
    """The plain text of ONE deliverable document ("" when it cannot be read).

    `.docx` through the same paragraph reader every other scan uses; `.pdf`
    through `pdftotext` (the read-only external the PDF artifact scan already
    requires); a text source read as text. Anything else -- a figure, an archive,
    a data table -- has no prose to contradict, so it is skipped.

    The size caps are per FORMAT because the failure modes differ: a 4.6 MB
    manuscript `.docx` is ordinary (the CNB main text is one, and a single
    global byte cap silently skipped it -- the bug this docstring records), a
    huge PDF is where `pdftotext` gets slow, and a text source that big is not
    prose. Every cap degrades to "" -- a scan never raises out of a package.
    """
    low = p.name.lower()
    if low.endswith(".docx"):
        try:
            if p.stat().st_size > 200_000_000:
                return ""
        except OSError:
            return ""
        try:
            return "\n".join(_docx_paragraphs(p))
        except Exception:                                             # noqa: BLE001
            return ""
    if low.endswith(".pdf"):
        try:
            if p.stat().st_size > 200_000_000:
                return ""
        except OSError:
            return ""
        if not shutil.which("pdftotext"):
            return ""
        try:
            proc = subprocess.run(["pdftotext", "-layout", str(p), "-"],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=180)
        except (OSError, subprocess.SubprocessError):                  # noqa: BLE001
            return ""
        return proc.stdout or ""
    if low.endswith(PKG2_EDITABLE_TEXT_EXTS + (".bib",)):
        # `.bib` was in package_document_texts' accept-list but not in this
        # reader's dispatch, so bibliography text never reached PKG-6/7/8/9 --
        # exactly where a two-lengths identifier is most likely to hide.
        try:
            if p.stat().st_size > 8_000_000:
                return ""
            return p.read_text("utf-8", "replace")
        except OSError:
            return ""
    return ""


def package_document_texts(root: Path, limit_files: int = 25) -> list:
    """[(rel, text)] for every deliverable DOCUMENT the package carries.

    Evidence areas are skipped (the author's own provenance is never read as
    prose) and so is every non-document file -- a per-figure source-data export
    (`supplementary_source_files/*.pdf`) is a chart, not a document whose prose
    can contradict another statement, and pulling 30 of them through
    `pdftotext` bought nothing. The `limit_files` cap keeps one pathological
    package from turning `decide` into a batch job: the scanned set is sorted,
    so which documents were read is reproducible.
    """
    out = []
    root = Path(root)
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file() or is_non_document_name(p.name) or _is_aux_doc(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        if is_evidence_rel(rel) or is_bookkeeping_name(p.name):
            continue
        parts = Path(rel).parts
        if "supplementary_source_files" in parts[:-1] or "source_data" in parts[:-1]:
            continue
        if not p.name.lower().endswith((".docx", ".pdf", ".tex", ".ltx", ".md",
                                        ".markdown", ".txt", ".bib", ".rst")):
            continue
        text = _pkg_text_of_doc(p)
        if text.strip():
            out.append((rel, text))
        if len(out) >= limit_files:
            break
    return out


# The two statement shapes PKG-6 pairs. The NON-USE sentence must carry an
# explicit negation ("without generative AI", "no AI tools were used") and the
# USE evidence must name a tool/workflow ("using our AI-based revision
# workflow", "the Codex interface", "DeepSeek"). Either alone is ordinary prose.
AI_NONUSE_RE = re.compile(
    r"(?i)\b(?:without|no|never|did\s+not|not\s+(?:a|an|any))\b[^.;\n]{0,60}?"
    r"\b(?:generative\s+AI|AI\s+tools?|AI\s+assistance|large\s+language\s+models?|"
    r"LLMs?|machine[- ]generated\s+(?:text|content)|automated\s+writing)\b")
# A SCOPED denial is not the defect: "no AI tools were used for the statistical
# analysis" is a true, useful statement that can sit beside an AI WRITING
# disclosure without contradicting it. Only a denial with no scope attached is
# paired (the shipped shape: "drafted this manuscript without generative AI,
# except ..."). The scope test looks at the clause between the negation and the
# AI word, and at the 40 characters after it.
AI_NONUSE_SCOPE_RE = re.compile(
    r"(?i)\bfor\s+(?:the\s+)?(?:statistic|analys|analysis|figure|figures|table|"
    r"tables|data|image|images|code|programming|writing\s+the\s+code|"
    r"literature|language\s+edit|copy\s?edit)\w*"
    r"|\bto\s+(?:generate|analy[sz]e|process|run|compute|plot)\b"
    # `without AI assistance` directly followed by WHAT the assistance was not
    # used for ("... for the figures", ": the figures", "in the figures").
    r"|\b(?:figures?|tables?|panels?|plots?|images?|statistical\s+analysis)\b"
    r"[^.;\n]{0,24}\b(?:were|was|are|is)\b")
# An ARTIFACT-scoped denial: the AI was not used for one DRAFT/VERSION of the
# work ("the initial draft was prepared without generative AI", "an earlier
# version ... hand-written"). The naive reading took any denial as a claim
# about the whole manuscript, which would flag the very sentence the fix for the
# shipped defect produces -- this rule must stay quiet on its own advice.
AI_NONUSE_ARTIFACT_SCOPE_RE = re.compile(
    r"(?i)\b(?:initial|first|original|early|earlier|previous|prior|preliminary|"
    r"pre-?AI)\s+(?:drafts?|versions?|manuscript|text|submission)\b")
AI_USE_RE = re.compile(
    r"(?i)\b(?:generative[- ]AI|AI-based|AI-assisted|AI-driven)\b[^.;\n]{0,40}?"
    r"\b(?:workflow|pipeline|tool|model|assistant|interface|revision)\b"
    r"|\b(?:used|using|employed|applied|ran|ran\s+the)\b[^.;\n]{0,60}?"
    r"\b(?:ChatGPT|GPT-[0-9]|Claude|Gemini|Copilot|Codex|DeepSeek|GLM-|Llama|Mistral|"
    r"Qwen)\b"
    r"|\b(?:ChatGPT|GPT-[0-9]|Claude|Gemini|Copilot|Codex|DeepSeek|GLM-)\b"
    r"[^.;\n]{0,40}?\b(?:to|for)\s+(?:refine|revise|draft|edit|rewrite|polish)\b")


def ai_disclosure_contradiction_rows(texts, limit: int = 6) -> list:
    """PKG-6: one text both denies and describes generative-AI use."""
    rows = []
    for rel, text in texts:
        nonuse, use = None, None
        for m in AI_NONUSE_RE.finditer(text):
            window = text[max(0, m.start() - 60):m.end() + 60]
            if AI_NONUSE_SCOPE_RE.search(window) or AI_NONUSE_ARTIFACT_SCOPE_RE.search(window):
                continue                      # a scoped denial, not a blanket one
            nonuse = (m, " ".join(text[max(0, m.start() - 10):m.end() + 10].split()))
            break
        if nonuse is None:
            continue
        for m in AI_USE_RE.finditer(text):
            if abs(m.start() - nonuse[0].start()) < 40:
                continue                      # the denying sentence's own clause
            use = (m, " ".join(text[max(0, m.start() - 10):m.end() + 10].split()))
            break
        if use is None:
            continue
        rows.append({
            "rule": "PKG-6", "severity": "high", "file": rel, "line": 1,
            "evidence": (f"the same document both denies and describes AI use: "
                         f"{nonuse[1]!r} ... {use[1]!r}"),
            "detail": "this document says the manuscript was produced WITHOUT "
                      "generative AI and, in the same text, describes running a "
                      "generative-AI workflow (or names the tool/model) over it. A "
                      "journal that requires AI disclosure reads the denial as a "
                      "false statement -- rewrite the denial so it says what the "
                      "AI was and was not used for (the design, the analysis, or "
                      "the writing), and keep the two statements consistent.",
            "fix": "manual"})
        if len(rows) >= limit:
            break
    return rows


def truncated_identifier_rows(texts, limit: int = 8) -> list:
    """PKG-7: an identifier is written at two lengths in one package.

    Only a STRICT PREFIX relation counts (`c30bc1ab...2fd` vs the full
    `c30bc1ab...2fdc9ddb`): that is what makes one surface's value provably the
    other's truncated form rather than a different object. Short hex-like tokens
    are skipped -- a 7-hex token is a legitimate abbreviation, and the pipeline
    would drown in them.
    """
    runs = []
    # `[0-9a-fA-F]`: a PDF (or a LaTeX source) that prints the identifier in
    # CAPS is the same identifier, and the scan used to go silent on it. The
    # prefix relation is compared case-insensitively; the evidence keeps the
    # document's own spelling.
    for rel, text in texts:
        for m in re.finditer(r"[0-9a-fA-F]{20,64}", text):
            runs.append((rel, m.group(0), m.group(0).lower()))
    by_value = {}
    for rel, tok, low in runs:
        by_value.setdefault(low, {"files": set(), "spellings": set()})
        by_value[low]["files"].add(rel)
        by_value[low]["spellings"].add(tok)
    rows, seen = [], set()
    for short in sorted(by_value, key=len):
        if len(short) < 12:
            continue
        for long, long_info in by_value.items():
            long_files = long_info["files"]
            if long == short or not long.startswith(short):
                continue
            short_info = by_value[short]
            if long_files == short_info["files"]:
                continue                      # same surface, both spellings
            key = (short, long)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "rule": "PKG-7", "severity": "medium",
                "file": sorted(short_info["files"])[0], "line": 1,
                "evidence": (f"{sorted(short_info['spellings'])[0]!r} ({len(short)} hex) in "
                             f"{sorted(short_info['files'])[0]} is a prefix of the "
                             f"{len(long)}-hex value carried in "
                             f"{sorted(long_files)[0]}"),
                "detail": "one identifier is written at two lengths in this "
                          "package: a reader who resolves the short one gets no "
                          "object (a truncated commit hash, an accession, a DOI). "
                          "Print the identifier at the length the PRODUCER uses "
                          "everywhere.",
                "fix": "manual"})
            if len(rows) >= limit:
                return rows
    return rows


STATS_UNIT_DEF_RE = re.compile(
    r"(?i)\bn\s+is\s+(?:the\s+)?(?:effective\s+)?(?:sample\s+size|number|count)"
    r"[^.\n]{0,80}?\b(" + "|".join(STATS_UNITS) + r")\b")
STATS_UNIT_PAIRED_RE = re.compile(
    r"(?i)\b(?:pairwise\s+comparisons?|paired\s+tests?)\b[^.\n]{0,80}?"
    r"\b(?:paired\s+)?(" + "|".join(STATS_UNITS) + r")\b")
STATS_UNIT_N_RE = re.compile(r"(?i)\bn\s*=\s*[\d,]+")


def unit_of_analysis_rows(texts, limit: int = 6) -> list:
    """PKG-8: the same comparison is described with two different units.

    The shape is a figure caption that states the sample size and calls it one
    unit ("pairwise comparisons used 606-1,989 paired CELLS"), while the table
    the values come from declares n over another ("n is ... the number of DONORS
    whose paired differences ... enter the test"). Both halves are required, and
    the unit words must come from the short list above, so a caption that merely
    counts something the table never characterizes stays silent.
    """
    declared, claimed = [], []
    for rel, text in texts:
        for m in STATS_UNIT_DEF_RE.finditer(text):
            declared.append((rel, m.group(1).lower(),
                             " ".join(text[max(0, m.start() - 20):m.end() + 20].split())))
        for m in STATS_UNIT_PAIRED_RE.finditer(text):
            window = text[max(0, m.start() - 160):m.end() + 40]
            if not STATS_UNIT_N_RE.search(window):
                continue                      # a caption with no sample-size claim
            claimed.append((rel, m.group(1).lower(), " ".join(window.split())))
    rows = []
    seen = set()
    for crel, cunit, cwin in claimed:
        # A caption unit the package DOES define is not a contradiction: the
        # package may state two units (one per experiment, exactly as the
        # shipped methods do) and the caption's own unit is the supported one.
        # Without this test the pairing below fired on the first DIFFERENT
        # declaration it met and never looked for a matching one, so a package
        # that says "n is the number of cells" beside the caption's "paired
        # cells" (and, elsewhere, "n is the number of mice") was reported as
        # inconsistent -- a blocking row on a correct package.
        if any(dunit == cunit for _drel, dunit, _dwin in declared):
            continue
        # ONE row per (document, caption unit, declared unit): the captions of
        # S1-S22 are the SAME sentence repeated once per figure (22 occurrences
        # in the shipped supplement), and a report that lists one defect 22
        # times buries the other rows.
        if (crel, cunit) in seen:
            continue
        for drel, dunit, dwin in declared:
            if cunit == dunit:
                continue
            seen.add((crel, cunit))
            rows.append({
                "rule": "PKG-8", "severity": "medium", "file": crel, "line": 1,
                "evidence": (f"a caption states a sample size in {cunit!r} "
                             f"({cwin[-150:]!r}) while {drel} defines n in "
                             f"{dunit!r} ({dwin!r})"),
                "detail": "the same comparison is described with two different "
                          "units of analysis: the caption's sample size counts "
                          f"{cunit!r} but the table's own note says the test ran "
                          f"over {dunit!r}. A reader cannot tell which analysis "
                          "produced the values -- make the caption state the unit "
                          "the test used.",
                "fix": "manual"})
            if len(rows) >= limit:
                return rows
            break
    return rows


# PKG-9 (2026-10-15): a table names a model TOOL and an AFFINITY quantity that
# the prose never connects. The shipped case: MMH2's comparison table labelled
# `MMP_aff` "Affinity (IC50) percentile" -- "Percentile rank of the predicted
# IC50 of the pMHC pair (MixMHCpred)" -- while the Methods define the same
# column as "the percentile rank of the MixMHCpred score against a
# length- and allotype-matched background of random peptides". MixMHCpred does
# not emit an IC50, and the two descriptions cannot both be right about what
# the column is. NetMHCpan's row is the CONTROL: it carries the same claim and
# IS supported, because the prose names NetMHCpan and IC50 in the same
# sentence. The rule therefore requires BOTH halves -- a tool+metric claim in a
# table row, and NO prose sentence naming that tool within reach of that metric
# -- so it stays silent on the well-defined columns it must not touch.
AFFINITY_METRIC_RE = re.compile(
    r"(?i)\b(IC50|Kd|KD|dissociation constant|half-maximal inhibitory concentration)\b")
# The tool of an affinity claim is the word in the DETAIL's parentheses -- the
# table column that names the model the value comes from. Column ids
# (`MixMHCpred_aff`), architecture labels (`PWM-derived`) and the value's own
# row id (`MMP_aff`) are NOT tools, and pairing them produced six rows for one
# defect before this was narrowed.
AFFINITY_TOOL_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9 .+_-]{2,40})\)")

# PKG-9 must run on every installation: the pipeline is documented as
# standard-library only, and python-docx was an undeclared optional import that
# made this check silently return no rows (see README.md "Requirements"). The
# DOCX readers below use the same zip/XML path as `_docx_paragraphs`.
DOCX_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_body(path: Path):
    """The `<w:body>` element of one DOCX, or None when it cannot be parsed."""
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("word/document.xml")
        root = ET.fromstring(data)
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError, RuntimeError,
            NotImplementedError):
        return None
    return root.find(DOCX_W_NS + "body")


def _docx_paragraph_text(paragraph) -> str:
    """The text of one `<w:p>`, with a break/tab rendered as a newline."""
    parts = []
    for node in paragraph.iter():
        if node.tag in (DOCX_W_NS + "br", DOCX_W_NS + "cr", DOCX_W_NS + "tab"):
            parts.append("\n")
        elif node.tag == DOCX_W_NS + "t":
            parts.append(node.text or "")
    return "".join(parts)


def _docx_table_rows(path: Path) -> list:
    """The table rows of ONE docx as `"cell | cell"` strings ([] on any failure).

    Body-level tables only, like python-docx's `doc.tables`; a nested table is
    part of its parent cell's text and is not a second top-level table.
    """
    body = _docx_body(path)
    if body is None:
        return []
    out = []
    try:
        for table in body.findall(DOCX_W_NS + "tbl"):
            for row in table.findall(DOCX_W_NS + "tr"):
                cells = []
                for cell in row.findall(DOCX_W_NS + "tc"):
                    texts = [_docx_paragraph_text(p).strip()
                             for p in cell.findall(DOCX_W_NS + "p")]
                    cells.append("\n".join(t for t in texts if t).strip())
                if any(cells):
                    out.append(" | ".join(cells))
    except Exception:                                          # noqa: BLE001
        return out
    return out


def _docx_prose_text(path: Path) -> str:
    """The BODY paragraphs of one docx, table cells excluded ("" on failure).

    `_docx_paragraphs` returns every `<w:p>`, which is what the formatting and
    placeholder scans want (a cell's text is part of the document a reader
    sees). A rule that compares a TABLE's claim against the prose that must
    support it needs the other set: the body's OWN direct paragraphs, exactly
    the set python-docx's `doc.paragraphs` returned.
    """
    body = _docx_body(path)
    if body is None:
        return ""
    return "\n".join(_docx_paragraph_text(p)
                     for p in body.findall(DOCX_W_NS + "p"))


def affinity_definition_rows(root: Path, limit: int = 8) -> list:
    """PKG-9: a table's affinity claim for a tool the prose never says it of."""
    root = Path(root)
    if not root.is_dir():
        return []
    # The SUPPORTING prose must be prose: `_docx_paragraphs` walks EVERY
    # `<w:p>` (table cells included), and a table that says "Affinity (IC50)
    # percentile ... (MixMHCpred)" was therefore read as the sentence that
    # defines the column -- the first cut of this rule reported nothing on the
    # very package it was written for.
    prose_parts = []
    for _rel, text in package_document_texts(root):
        if _rel.lower().endswith(".docx"):
            prose_parts.append(_docx_prose_text(Path(root) / _rel))
        else:
            prose_parts.append(text)
    prose = "\n".join(p for p in prose_parts if p)
    rows = []
    for p in sorted(root.rglob("*.docx")):
        if not p.is_file() or is_non_document_name(p.name) or _is_aux_doc(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        if is_evidence_rel(rel):
            continue
        table_rows = _docx_table_rows(p)
        # (tool, the row that names it) for every row that pairs a tool with an
        # affinity quantity. ONE entry per tool, so the evidence quotes a row
        # that really carries the claim.
        claimed = {}
        for rowtext in table_rows:
            if not AFFINITY_METRIC_RE.search(rowtext):
                continue
            for cell in rowtext.split("|"):
                for tm in AFFINITY_TOOL_RE.finditer(cell):
                    cand = tm.group(1).strip()
                    if cand[:1].isupper() and re.search(re.escape(cand), prose):
                        claimed.setdefault(cand, rowtext)
        # SUPPORT means one SENTENCE that names the tool and the quantity
        # together -- the shipped control is "NetMHCpan-predicted half-maximal
        # inhibitory concentration (IC50) exceeds 10,000 nM". A character
        # window instead of a sentence boundary read the table's own cell (it
        # lands in the paragraph stream) and two unrelated paragraphs as
        # support, which is how the first cut of this rule found nothing.
        sentences = re.split(r"(?<=[.;])\s+", prose)
        for tool, claim_row in sorted(claimed.items()):
            supported = False
            for s in sentences:
                if re.search(re.escape(tool), s) and AFFINITY_METRIC_RE.search(s):
                    supported = True
                    break
            if supported:
                continue
            claim_metric = AFFINITY_METRIC_RE.search(claim_row).group(1)
            rows.append({
                "rule": "PKG-9", "severity": "medium", "file": rel, "line": 1,
                "evidence": (f"the table row {claim_row[:120]!r} states an affinity "
                             f"output ({claim_metric!r}) for {tool!r}, and no sentence "
                             f"in this package names {tool!r} near that metric"),
                "detail": "a table defines a quantity as the tool's AFFINITY output "
                          "(an IC50 or a Kd) while the prose that defines the same "
                          "column never connects that tool to that quantity. One of "
                          "the two is wrong: either the prose is missing the "
                          "definition, or the table names an output the tool does "
                          "not produce (a rank or a score is not an IC50).",
                "fix": "manual"})
            if len(rows) >= limit:
                return rows
    return rows


def package_contradiction_rows(root: Path, texts=None, limit: int = 20) -> list:
    """PKG-6..9 over one package: statements that contradict each other."""
    if texts is None:
        texts = package_document_texts(Path(root))
    rows = (ai_disclosure_contradiction_rows(texts, limit=limit)
            + truncated_identifier_rows(texts, limit=limit)
            + unit_of_analysis_rows(texts, limit=limit)
            + affinity_definition_rows(Path(root), limit=limit))
    return rows[:limit]


# PKG-4 (2026-10-15): a display item the submission CITES (and often legends)
# but carries nowhere. The operator's report was exactly this: "Figure S3 is
# cited and has a legend, but it is not in the submission -- `figS3.png` is
# under `code/out/`, which is not submitted, and the supplementary Word file
# does not embed it." A cited figure the reader cannot see is not a nuance of
# packaging: Results and the supplement both point at it. Advisory, not a
# blocker: whether the fix is to ship the figure, embed it in the supplement, or
# drop the citation is the author's call -- but the DELIVERED status must say it.
PKG4_FIGURE_CITE_RE = re.compile(
    r"(?i)\b(?P<kw>fig(?:ure)?s?\.?|supplementary\s+fig(?:ure)?s?\.?)\s*"
    # A LIST after a PLURAL keyword is still one citation group: "Figures 2, 4
    # and S2" cites three items, and the old single-label capture saw only 2.
    # A singular "Fig. 2, 3 clusters" is a fig reference followed by a count,
    # not a list, so the caller passes the keyword's plurality to the splitter.
    # The token pattern consumes a panel letter but not an ordinal suffix, and
    # refuses a digit continuation or a thousands grouping ("Figure 2 and 3,000
    # cells" must not yield labels 3 and 000).
    r"(?P<labels>(?:S?\d+(?!(?:st|nd|rd|th)\b)(?!\d)(?!,\d{3}(?!\d))[a-z]?)"
    r"(?:\s*(?:,|and|&|;|\u2013|-)\s*S?\d+(?!(?:st|nd|rd|th)\b)(?!\d)"
    r"(?!,\d{3}(?!\d))[a-z]?)*)")


def _pkg4_cited_labels(expr: str, plural: bool = True) -> list:
    """The figure labels one citation expression names, in written order.

    Comma/and lists yield each token; a same-prefix numeric range expands
    ("Figures 2-4" cites 2, 3 and 4), capped so a typo cannot enumerate a
    thousand labels. A comma-separated token is a LIST item only when the
    keyword is plural or another separator follows it: "Fig. 2, 3 clusters"
    is a citation of Figure 2 followed by the count 3, not a two-item list.
    """
    out = []
    # Keep the separators so a comma can be told apart from "and"/"&"/";".
    parts = re.split(r"\s*(,|and\b|&|;)\s*", str(expr or ""), flags=re.I)
    for i in range(0, len(parts), 2):
        token = parts[i].strip()
        if not token:
            continue
        sep = parts[i - 1].strip().lower() if i else ""
        next_sep = parts[i + 1].strip().lower() if i + 1 < len(parts) else ""
        if sep == "," and not plural and not next_sep:
            continue
        m = re.fullmatch(
            r"(?i)(S?)(\d+)[a-z]?\s*[\u2013-]\s*(S?)(\d+)[a-z]?", token)
        if m and m.group(1).lower() == m.group(3).lower():
            lo, hi = int(m.group(2)), int(m.group(4))
            if lo <= hi and hi - lo <= 50:
                out.extend(f"{(m.group(1) or '').lower()}{n}" for n in range(lo, hi + 1))
                continue
        out.extend((m.group(1) + (m.group(2) or "")).lower() for m in re.finditer(
            r"(?i)(S?\d+)(?!(?:st|nd|rd|th)\b)([a-z]?)", token))
    return list(dict.fromkeys(out))
PKG4_FIGURE_FILE_RE = re.compile(r"(?i)(?:^|[^a-z0-9])(?:supp(?:lementary)?[ _-]?)?"
                                 r"(?:fig(?:ure)?\.?[ _-]?)(S?\d+[a-z]?)(?![0-9])")
PKG4_FIGURE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".eps", ".svg", ".pdf",
                    ".ai", ".ppt", ".pptx")


def package_display_item_rows(root: Path, areas=None, limit: int = 20) -> list:
    """PKG-4: cited figures the published package does not carry.

    The inventory side is NAME-based on purpose: a submission names its figure
    files (`figures/FigureS1.png`, `figS3.png`, `Figure_S3.pdf`), and the label
    that comes out of the name is compared with the labels the documents cite.
    A label with no file is reported with what the package DOES hold (a
    same-labelled file inside a not-carried area, i.e. the exact shape the
    operator reported), so the author sees both the gap and where the figure
    actually lives.
    """
    rows = []
    root = Path(root)
    if not root.is_dir():
        return rows
    areas = [str(a).lower() for a in (areas or submission_not_carried_areas_plain())]
    _decl, is_submitted = declared_submission_filter(root)
    carried_labels, absent_labels = set(), {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or is_non_document_name(p.name):
            continue
        if p.suffix.lower() not in PKG4_FIGURE_EXTS:
            continue
        if is_evidence_rel(p.relative_to(root).as_posix()):
            continue
        m = PKG4_FIGURE_FILE_RE.search(p.name)
        if not m:
            continue
        label = m.group(1).lower()
        rel = p.relative_to(root).as_posix()
        if rel.split("/", 1)[0].lower() in areas:
            absent_labels.setdefault(label, []).append(rel)
        elif is_submitted(rel):
            carried_labels.add(label)
        else:
            # Carried by the package, but the declared submission set leaves it
            # out: for a reader of the submission it is as unreachable as an area
            # file, so the row names it too.
            absent_labels.setdefault(label, []).append(rel)
    if not carried_labels:
        # No figure FILE carries a label: this package embeds its artwork in the
        # documents themselves (the CopyNumBench main text carries five images
        # and no `Figure*.png`), so a name-based check has nothing to compare
        # against -- every citation would read as missing. Reported as a gap in
        # the decision.json `readiness` note, never as a row per citation.
        return rows
    cited = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or is_non_document_name(p.name) or _is_aux_doc(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        if rel.split("/", 1)[0].lower() in areas or is_evidence_rel(rel):
            continue
        if is_bookkeeping_name(p.name) or is_non_submitted_readme_name(p.name):
            continue
        if not is_submitted(rel):
            continue
        if p.suffix.lower() == ".docx":
            lines = _docx_paragraphs(p)
        elif p.suffix.lower() in PACKAGE_TEXT_EXTS:
            try:
                if p.stat().st_size > PACKAGE_TEXT_BYTES_LIMIT:
                    # Same cap the PKG-2 scan applies: a very large data dump is
                    # not manuscript prose, and reading it here would make the
                    # published-package scan pay for a file no citation lives in.
                    continue
                lines = p.read_text("utf-8", "replace").splitlines()
            except OSError:
                continue
        else:
            continue
        for i, line in enumerate(lines or [], 1):
            for m in PKG4_FIGURE_CITE_RE.finditer(line):
                plural = bool(re.search(r"(?i)fig(?:ure)?s\.?$", m.group("kw").strip()))
                for label in _pkg4_cited_labels(m.group("labels"), plural=plural):
                    cited.setdefault(label, (rel, i, m.group(0)))
    for label, (rel, line, text) in sorted(cited.items()):
        if label in carried_labels:
            continue
        where = absent_labels.get(label) or []
        detail = (f"this document cites {text!r}, and the submission carries no figure file for "
                  f"that item")
        if where:
            detail += (f" -- the package holds it only as "
                       + ", ".join(f"`{w}`" for w in where[:3])
                       + ", in an area the submission does not carry")
        else:
            detail += (" (no file of that name exists anywhere in the package, and the "
                       "document does not embed it)")
        detail += (". A reader following the citation finds nothing: ship the figure, embed it "
                   "in the document that legends it, or drop the citation")
        rows.append({"rule": "PKG-4", "severity": "advisory", "file": rel, "line": line,
                     "reference": text, "resolves_to": where[:3], "detail": detail,
                     "fix": "manual"})
        if len(rows) >= limit:
            break
    return rows[:limit]


# FRONT-MATTER GAPS (2026-10-15): a rule the venue profile does NOT state is not
# invented by this pipeline (AGENTS.md rule 3) -- so the two things an editor
# looks for on a title page that this rule set cannot check are COUNTED AND
# NAMED instead. The operator's audit of the CopyNumBench package reported "the
# title page still has no article type (Article, Analysis, Resource, or
# otherwise)"; the profile's `article_types` table records which type the run is
# for, and the delivered status can say that the title page does not print it,
# without claiming the venue requires it.
def front_matter_gap_rows(ctx: Ctx, root: Path, limit: int = 8) -> list:
    """Rows for title-page facts the RECORDED rule set cannot check."""
    rows = []
    root = Path(root)
    if not root.is_dir():
        return rows
    profile = venue_profile_of(ctx, required=False)
    label = ""
    try:
        label = str(getattr(profile, "article_type", "") or "")
    except Exception:                                                 # noqa: BLE001
        label = ""
    if not label:
        return rows
    _decl, _decl_is_submitted = declared_submission_filter(root)
    for p in sorted(root.rglob("*.docx")):
        if not p.is_file() or is_non_document_name(p.name) or _is_aux_doc(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        if is_evidence_rel(rel) or not _decl_is_submitted(rel) \
                or docx_document_role(p.name) != "main":
            continue
        try:
            paras = _docx_paragraphs(p) or []
        except Exception:                                             # noqa: BLE001
            continue
        head = "\n".join(paras[:12])
        if label.lower() in head.lower():
            continue
        rows.append({
            "rule": "FMT-TP1", "severity": "advisory", "file": rel, "line": 1,
            "reference": label,
            "detail": (f"the title page (the first {min(12, len(paras))} paragraph(s) of {rel}) "
                       f"does not name the content type `{label}` this run is configured for. "
                       f"The venue profile records the type's limits but states NO rule that the "
                       f"type must be printed on the title page, so this is reported as a GAP, "
                       f"not as a requirement: confirm it with the journal's own guidelines "
                       f"before submission"),
            "fix": "manual"})
        if len(rows) >= limit:
            break
    return rows[:limit]


# PKG-5 (2026-10-15): two SHIPPED surfaces attribute one display item to
# different tools. The operator's second audit found it in the delivered
# NeoHeteroclitic package: the resources table says "Matplotlib, seaborn
# (Figures 2, 4 and S2)" while Figure S2's own legend ends "Created with
# BioRender.com" (and the BioRender row claims "Figures 1 and S2"), so the
# matplotlib/seaborn row also steals the credit for the data figure that the
# code actually produced (Figure S3). Neither a per-document scan nor M31 can
# see it: the contradiction lives BETWEEN a table row and another document's
# legend, and it is mechanical once both sides are parsed.
PKG5_TOOL_ROW_RE = re.compile(r"^(?P<tools>[^()]{2,90}?)\((?P<items>[^)]{2,140})\)\s*$")
PKG5_ITEM_LIST_RE = re.compile(
    r"(?i)\b(fig(?:ure)?s?|tables?)\.?\s*"
    r"((?:S?\d+[a-z]?)(?:\s*(?:,|and|&|;|\u2013|-)\s*S?\d+[a-z]?)*)")
PKG5_LABEL_RE = re.compile(r"(?i)^\s*(fig(?:ure)?s?|tables?)\.?\s*(S?\d+)\b")
# `Created with BioRender.com`, `plotted with matplotlib`, `made in R` ... The
# captured name must START with a capital (or a digit-led product like `R 4.4`):
# otherwise an ordinary participle matches ("variants generated by substituting
# ...", "values are plotted with 10,000 bootstrap resamples") and every legend
# would attribute its figure to prose.
# The VERB half is case-insensitive, the NAME half is NOT: `[A-Z]` inside a
# `(?i)` pattern matches lowercase too, and that made every legend "attribute"
# its figure to the prose after it ("variants generated by substituting MHC-anchor
# residues", "sequence logos, plotted in bits") -- five false rows on the package
# that has exactly one real contradiction.
PKG5_PRODUCER_RE = re.compile(
    r"(?i:\b(?:created|generated|made|drawn|produced|prepared|plotted|visuali[sz]ed|"
    r"assembled|rendered|composed)\s+(?:with|using|in|by)\s+)"
    r"(?P<name>(?:[A-Z][\w.+-]{1,30}|R\s?\d[\w.]*)(?:\s?[A-Z0-9][\w.+-]{0,30}){0,3})")

# A legend that ends `... the design-space argument made in Results.` must not
# be read as a producer named "Results" (the 2026-10-15b neohet package: the
# greedy name half takes the next sentence's first word, and the contradiction
# row then sends the author hunting a defect that does not exist). The name is
# finalized in Python, where a sentence boundary is unambiguous.
PKG5_SECTION_NAMES = frozenset(
    ("results", "result", "methods", "method", "materials", "introduction",
     "discussion", "abstract", "conclusions", "conclusion", "background",
     "supplementary", "references", "acknowledgements", "acknowledgments",
     "appendix", "table", "figure", "fig", "data", "analysis", "this", "the",
     "their", "our", "text", "study", "paper", "manuscript", "main"))


def pkg5_producer_name(m: re.Match) -> str:
    """The producer named by a PKG5_PRODUCER_RE match ("" = prose, not a name).

    Three trims, each measured on a real package:
      * the name never RUNS ON into the next sentence (`Results. The method`
        matched "Results. The" before this);
      * a sentence-final period is dropped (while `BioRender.com.` keeps its
        product punctuation a dot after the domain is not a sentence end);
      * a SECTION NAME is not a producer.
    """
    name = m.group("name")
    cut = re.search(r"\.\s+[A-Z0-9]", name)
    if cut:
        name = name[:cut.start()]
    elif name.endswith("."):
        tail = (m.string[m.end():m.end() + 8] or "")
        # `Created with BioRender.com.` is fine: the legend ENDS there. The
        # shipped defect read `... made in Results. The method ...`, where the
        # period is followed by the next sentence's subject.
        if re.match(r"\s+[A-Z]", tail) or not tail:
            name = name[:-1]
    name = name.rstrip(" .;:,")
    if not name or not re.match(r"[A-Z0-9]", name):
        return ""
    if name.lower() in PKG5_SECTION_NAMES:
        return ""
    return name
PKG5_KIND = {"fig": "figure", "figs": "figure", "figure": "figure", "figures": "figure",
             "table": "table", "tables": "table"}


def display_provenance_rows(root: Path, areas=None, limit: int = 20) -> list:
    """PKG-5: a display item's declared PRODUCER disagrees between two surfaces.

    Side A is a resources/software table row: `Tool, tool (Figures 2, 4 and S2)`.
    Side B is the item's own legend, where the producer is named with a
    production verb (`Created with BioRender.com`). When the legend of item X
    names a producer and a table row claims X for a DIFFERENT tool, the two
    shipped surfaces contradict each other and the author must reconcile them
    (the pipeline cannot know which side is right).

    Silent unless both sides are present for the same item, so a legend that
    names no producer, or a table row for an item without a legend here, is not
    a row. Titles are read from the legend block of the item itself (its label
    paragraph plus the following paragraphs until the next label).
    """
    rows = []
    root = Path(root)
    if not root.is_dir():
        return rows
    areas = [str(a).lower() for a in (areas or submission_not_carried_areas_plain())]
    _decl, is_submitted = declared_submission_filter(root)
    claims, producers = {}, {}
    docs = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or is_non_document_name(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        if rel.split("/", 1)[0].lower() in areas or is_evidence_rel(rel):
            continue
        if is_bookkeeping_name(p.name) or is_non_submitted_readme_name(p.name):
            continue
        if not is_submitted(rel):
            continue
        if p.suffix.lower() == ".docx":
            lines = _docx_paragraphs(p)
        elif p.suffix.lower() in PACKAGE_TEXT_EXTS:
            try:
                if p.stat().st_size > PACKAGE_TEXT_BYTES_LIMIT:
                    continue
                lines = p.read_text("utf-8", "replace").splitlines()
            except OSError:
                continue
        else:
            continue
        if lines:
            docs.append((rel, list(lines)))
    for rel, lines in docs:
        for i, line in enumerate(lines):
            # Side A: a resources/software table row. It does NOT start with a
            # display label (`Matplotlib, seaborn (Figures 2, 4 and S2)`), so the
            # two sides are parsed INDEPENDENTLY: reading the claim only inside a
            # label's own paragraph missed every table row and reported nothing on
            # the very package that has the defect.
            tm = PKG5_TOOL_ROW_RE.match(line.strip())
            if tm:
                for im in PKG5_ITEM_LIST_RE.finditer(tm.group("items")):
                    kind = PKG5_KIND.get(im.group(1).lower(), "")
                    if not kind:
                        continue
                    tools = [t.strip(" .") for t in
                             re.split(r",|;|\band\b", tm.group("tools")) if t.strip(" .")]
                    for num in re.findall(r"(?i)S?\d+", im.group(2)):
                        for tool in tools:
                            claims.setdefault((kind, num.lower()), {}).setdefault(tool, rel)
            # Side B: the item's own legend block and the producer it names.
            m = PKG5_LABEL_RE.match(line)
            if not m:
                continue
            key = (PKG5_KIND.get(m.group(1).lower(), ""), m.group(2).lower())
            if not key[0]:
                continue
            ends = [j for j in range(i + 1, min(i + 8, len(lines)))
                    if PKG5_LABEL_RE.match(lines[j])]
            stop = ends[0] if ends else min(i + 6, len(lines))
            block = "\n".join(lines[i:stop])
            for pm in PKG5_PRODUCER_RE.finditer(block):
                name = pkg5_producer_name(pm)
                if name:
                    producers.setdefault(key, {}).setdefault(name, rel)
    # ONE row per (contradicted item, the document whose table claims it), listing
    # every contradicting tool: two rows for `Matplotlib` and `seaborn` would read
    # as two defects where the author has one correction to make.
    grouped = {}
    for key, tools in sorted(claims.items()):
        prods = producers.get(key)
        if not prods:
            continue
        blob = " | ".join(prods).lower()
        bad = sorted(t for t in tools if t.lower() not in blob)
        if not bad:
            continue
        doc = sorted(tools[t] for t in bad)[0]
        slot = grouped.setdefault((key, doc), {"tools": [], "prods": prods})
        slot["tools"].extend(bad)
    for (key, doc), slot in sorted(grouped.items()):
        prods = slot["prods"]
        rows.append({
            "rule": "PKG-5", "severity": "high", "file": doc,
            "item": f"{key[0]} {key[1]}",
            "reference": ", ".join(sorted(set(slot["tools"]))),
            "detail": (f"the resources table in `{doc}` claims "
                       f"{' / '.join(repr(t) for t in sorted(set(slot['tools'])))} for "
                       f"{key[0]} {key[1].upper()}, while that item's OWN legend attributes it "
                       f"to {', '.join(repr(p) for p in sorted(prods))} "
                       f"(in `{prods[sorted(prods)[0]]}`). Two shipped surfaces disagree about "
                       f"which tool produced this item, so one of them is wrong: correct the "
                       f"table row or the legend (and check the item the real producer belongs "
                       f"to)"),
            "fix": "manual"})
        if len(rows) >= limit:
            break
    return rows[:limit]


def submission_not_carried_areas_plain() -> list:
    """`submission_not_carried_areas` without a root: the standing areas.

    The published-package scans read the package AS a submission about to be
    assembled, so the policy keys (`submit_code`) are not available there; the
    standing answer is the one those scans always used.
    """
    return [str(n) for n in EVIDENCE_DIRNAMES] + [CODE_DIR]


def package_pdf_rows(root: Path, limit: int = 40) -> list:
    """FMT-PDF1..3 over every PDF the published package ships."""
    rows = []
    root = Path(root)
    mod = _format_module()
    if mod is None or not root.is_dir():
        return rows
    _decl, _decl_is_submitted = declared_submission_filter(root)
    for p in sorted(root.rglob("*.pdf")):
        if not p.is_file() or _is_aux_doc(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        if is_evidence_rel(rel) or not _decl_is_submitted(rel):
            continue
        try:
            # FMT-PDF3 (an empty export: no extractable text, no embedded
            # image) requires the page count, and this was the one caller that
            # never supplied one -- so the publish scan could not report the
            # blank export its own docstring promises to catch. pdftotext ends
            # every rendered page with a form feed.
            text = pages = None
            if shutil.which("pdftotext"):
                proc = subprocess.run(["pdftotext", "-layout", str(p), "-"],
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=60)
                if proc.returncode == 0:
                    text = proc.stdout or ""
                    pages = text.count("\f")
            found = mod.pdf_artifact_rows(p, text=text, pages=pages)
        except Exception as e:                                        # noqa: BLE001
            found = [{"rule": "FMT-PDF3", "severity": "medium", "document": rel,
                      "location": "-", "evidence": f"{type(e).__name__}: {e}",
                      "detail": "the PDF could not be inspected", "fix": "manual",
                      "protected": False}]
        for r in found:
            rows.append(dict(r, document=rel))
        if len(rows) >= limit:
            break
    return rows[:limit]


def write_final_clean_zip(dirp: Path, zip_path: Path) -> dict:
    """Compress the published package into `zip_path`, KEEPING `dirp` in place.

    The archive holds the directory itself (`<dir name>/...`), so unzipping it
    beside the directory restores exactly the published tree. The bytes are
    deterministic (sorted entries, fixed entry timestamps), so a repeat `decide`
    over an unchanged package keeps the existing archive instead of rewriting it
    (no churn). The directory is never removed or modified by this function.
    """
    ztmp = zip_path.with_name(zip_path.name + ".tmp")
    n_files = 0
    with zipfile.ZipFile(ztmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for q in sorted(dirp.rglob("*")):
            rel = f"{dirp.name}/{q.relative_to(dirp).as_posix()}"
            info = zipfile.ZipInfo(rel + "/" if q.is_dir() else rel,
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if q.is_dir() else 0o644) << 16
            if q.is_dir():
                zf.writestr(info, b"")
                continue
            n_files += 1
            with open(q, "rb") as fsrc, zf.open(info, "w") as fdst:
                shutil.copyfileobj(fsrc, fdst, 1 << 20)
    if zip_path.is_file() and sha256_file(zip_path) == sha256_file(ztmp):
        ztmp.unlink()
    else:
        os.replace(ztmp, zip_path)
    return {"path": str(zip_path), "files": n_files, "bytes": zip_path.stat().st_size}


def _stage_dangling_report(ctx: Ctx, final: dict):
    """The PKG-2 record the STAGE that wrote the champion left behind, or None.

    Publication preserves the judged bytes, so it never removes a dangling
    reference itself: the removal ran in the candidate stage BEFORE the pin.
    Reading that stage's own `PKG2_<run>.json` makes the readme/readiness/
    console surfaces report a repair that really happened (the old stub made
    all three blocks dead and named an artifact that is never written).
    """
    stored = (final or {}).get("stored") or {}
    rnd = stored.get("round") or (final or {}).get("round")
    champ = str(stored.get("champion") or "")
    if rnd and champ:
        try:
            rid = rid_for_fresh(int(rnd), champ)
        except (KeyError, TypeError, ValueError):
            rid = ""
        rec = ctx.run(rid) if rid else None
        if rec is not None:
            p = ctx.sandbox_of(rec) / f"PKG2_{rec.get('id') or rid}.json"
            if p.is_file():
                rep = read_json(p, revive=False, lenient=True)
                if isinstance(rep, dict):
                    try:
                        rep = dict(rep, artifact=p.relative_to(ctx.root).as_posix())
                    except ValueError:                        # pragma: no cover -- inside root
                        rep = dict(rep, artifact=str(p))
                    return rep
    # NO fallback to reports/PKG2_journal_submission.json: that record is
    # written by the POST-PIN journal-submission assembly, so it describes a
    # derived copy, not the champion's published bytes. Reporting it as the
    # champion's own repair would claim a removal the published package does
    # not carry; the publication-time scan reports those pointers instead.
    return None


def publish_final_clean(ctx: Ctx, final: dict, certified: bool, reason: str = "",
                        flatten_zotero: bool = False, residuals: dict = None) -> dict:
    """Publish <root>/final_clean_version_<root dir name>/: the champion corpus
    for a new run.

    The copy starts byte-identical to the pinned champion's corpus and remains
    byte-identical through publication. The winner
    directory is already materialized by build_corpus_dir(), which strips the
    process scratch (work/), the difference-tracking auxiliaries (see
    TRACKING_AUX_NAME_RE) and the pipeline's own bookkeeping
    (CHANGELOG.md, MANUAL_STEPS.md, REVISION_REPORT.md, revision_report.json,
    DIFF_LEDGER.md, REWRITE_REPORT.md, VISUAL_CHECK.md). Copying it therefore
    gives the champion corpus exactly what `setup --source <dir>` needs.
    Filenames and references are preserved as judged; the author checklist and
    every other status document remain siblings of the directory.

    The copy is ALWAYS attempted (2026-10-01): an uncertified champion's corpus
    is still materialized, and its certification verdict travels in the SIBLING
    `final_clean_version.readme.md` (see write_final_clean_readme), never inside
    this directory -- so `--source` never silently mixes a status file into the
    next run's manuscript. `certified`/`reason` are carried into the returned
    record for that readme (they no longer gate the copy).

    The same tree is also compressed into the SIBLING
    `<root>/final_clean_version_<root dir name>.zip` (see write_final_clean_zip)
    for handing the package over; the directory itself is KEPT in place and is
    still the next run's `--source`.

    Returns {"path", "digest", "pin_digest", "files", "renamed", "action",
    "certified", "certification_note", "zip"} or {"skipped": <reason>, ...}
    when the corpus itself cannot be built (no winner/pin on disk, empty
    corpus, or a digest mismatch). The write is idempotent: an existing copy
    that already hashes to the pinned tree is left untouched; a superseded
    copy is archived under _superseded/, never deleted.
    """
    pin = final.get("pin") or {}
    src = None
    winner = final["stored"].get("winner_dir")
    if winner and (ctx.root / winner).is_dir():
        src = ctx.root / winner
    elif pin:
        d = pinned_docs_dir(ctx, pin)
        if d.is_dir():
            src = d
    _meta = {"certified": bool(certified), "certification_note": reason or None}
    if flatten_zotero:
        return dict(_meta, skipped=(
            "post-pin Zotero-field flattening is disabled: publication must serve the "
            "judged bytes. Set format_policy.unlink_zotero_fields before `run`, or "
            "leave the live fields for the author."))
    if src is None:
        return dict(_meta, skipped="neither the published winner nor the pin is present on disk")
    fc_name = final_clean_dirname(ctx.root)
    dst = ctx.root / fc_name
    tmp = ctx.root / (fc_name + ".tmp")
    zip_path = ctx.root / (fc_name + ".zip")
    if tmp.exists():
        rmtree_force(tmp)
    copy_into(src, tmp, exclude_top=CORPUS_EXCLUDE_TOP, skip_aux=True,
              strip_bookkeeping=True, root=ctx.root)
    # The staging copy is the pipeline's own, but copy2/copytree preserved the
    # source's modes: a read-only manuscript file (or a read-only DIRECTORY the
    # counter has to rename inside) would otherwise make publication fail on
    # permissions the author set for their own protection. raw_data/ keeps its
    # modes -- and its content -- untouched; the rest of the tree is ours to write.
    chmod_plan = make_tree_writable(tmp, skip_top=EVIDENCE_DIRNAMES)
    manifest = corpus_dir_manifest(tmp)
    if not manifest["count"]:
        rmtree_force(tmp, ignore_errors=True)
        return dict(_meta, skipped="the champion corpus is empty")
    digest = manifest_digest(manifest)
    pin_digest = pin.get("digest")
    if pin_digest and digest != pin_digest:
        rmtree_force(tmp, ignore_errors=True)
        return dict(_meta, skipped=f"the clean copy hashes to {digest[:12]} but the pin "
                                   f"recorded {str(pin.get('digest'))[:12]}")
    if not pin_digest:
        # There was no pin digest to compare against; returning the COPY's own
        # digest as `pin_digest` made the report claim an unverified identity.
        pin_digest = None
    # The delivered tree is the judged tree. Everything below SCANS that tree;
    # none of the scans is allowed to rewrite it. A delivery cleanup here would
    # make final_clean_version/ (and the next round's --source) a cousin of the
    # bytes the panel scored, contradicting AGENTS.md rule 5.
    hygiene = {"removed": [], "kept_bbl": [], "raw_data_untouched": 0,
               "removed_word_owner_files": [], "removed_platform_junk": [],
               "removed_bytecode_cache": [],
               "publication_bytes": "pin-identical (no post-judgment rewrite)"}
    hygiene["held_internal_readme_notes"] = []
    counter = {"renamed": 0, "raw_data_untouched": 0, "collisions": []}
    # Build by-products are REPORTED below, never removed here. If they should
    # not ship, the stage that produced the version must remove them before the
    # pin is taken; publication cannot clean a judged corpus.
    # A non-empty .bbl and the compiled PDFs stay: the .bbl is the reference list
    # when no editable bibliography can regenerate it, and a PDF is a submission
    # deliverable when the configured venue accepts one (see the venue profile's
    # `submission` block and derived_outputs_rule()).
    # The pipeline's own by-products never reach the published package (the copy
    # strips them by name, version token included): report which ones the
    # champion carried, so the operator sees the strip instead of guessing.
    hygiene["stripped_bookkeeping"] = sorted(
        {q.name for q in src.rglob("*") if q.is_file() and is_bookkeeping_name(q.name)})
    for q in sorted(tmp.rglob("*")):
        if not q.is_file():
            continue
        rel = q.relative_to(tmp).as_posix()
        if is_evidence_rel(rel):
            hygiene["raw_data_untouched"] += 1
        if q.name.lower().endswith(".bbl") and q.stat().st_size:
            hygiene["kept_bbl"].append(rel)
    # Publication is a byte-for-byte handoff of the pin. Formatting, Zotero
    # flattening and dangling-reference removal happen in the stage that writes
    # a candidate, before it is judged; doing them here would silently replace
    # the artifact the panel selected. Report the STAGE's own repair record
    # (which described these very bytes when the candidate was pinned), not a
    # record publication can never produce.
    pub_policy, flatten_zotero = publication_format_policy(
        ctx, format_policy_of(ctx), cli_flatten=bool(flatten_zotero))
    hygiene["removed_dangling_references"] = (_stage_dangling_report(ctx, final) or {
        "skipped": "publication preserves the judged bytes; the stage that wrote the champion "
                   "reports any removal it made before the pin"
    })
    _fmt_z = _format_module()
    zot_before = {}
    if _fmt_z is not None and hasattr(_fmt_z, "zotero_report_for_docx"):
        for q in sorted(tmp.rglob("*.docx")):
            try:
                _zrep = _fmt_z.zotero_report_for_docx(q)
            except Exception:                                      # noqa: BLE001
                continue
            zot_before[q.name] = int((_zrep.get("counts") or {}).get("zotero", 0))
    format_fix = {
        "skipped": "publication preserves the judged bytes; formatting is a stage-side gate",
        "policy": pub_policy,
    }
    hygiene["zotero_unlinked"] = {"requested": bool(flatten_zotero),
                                  "documents": [],
                                  "fields_before": zot_before,
                                  "deferred": (
                                      "publication preserves the judged bytes; unlink Zotero "
                                      "fields in the stage output before it is scored"
                                      if flatten_zotero else None)}
    hygiene["zotero_live_fields"] = []
    if _fmt_z is not None and hasattr(_fmt_z, "zotero_report_for_docx"):
        for q in sorted(tmp.rglob("*.docx")):
            try:
                _zrep = _fmt_z.zotero_report_for_docx(q)
            except Exception:                                      # noqa: BLE001
                continue
            _n = (_zrep.get("counts") or {}).get("zotero", 0)
            if _n:
                hygiene["zotero_live_fields"].append({"file": q.name, "fields": int(_n)})
            elif zot_before.get(q.name):
                hygiene["zotero_unlinked"]["documents"].append(q.name)
    # Package hygiene: the by-product names are stripped above; what REMAINS is
    # scanned for internal material (PKG-1) and every shipped PDF for an
    # unfilled/blank artifact (FMT-PDF1..3). These are reported, never silently
    # deleted: the file belongs to the author, but the package must not ship it.
    hygiene["present_non_shippable"] = sorted(
        q.relative_to(tmp).as_posix()
        for q in tmp.rglob("*")
        if q.is_file() and is_non_shippable_name(q.name)
        and not is_evidence_rel(q.relative_to(tmp).as_posix())
    )
    hygiene["internal_artifacts"] = internal_artifact_rows(tmp)
    # PKG-26: two submitted files for one document role (a stale pre-revision
    # copy beside the current document). The reader cannot tell which is
    # current, and the journal receives both.
    try:
        hygiene["duplicate_roles"] = duplicate_submission_role_rows(tmp)
    except Exception as e:                                            # noqa: BLE001
        hygiene["duplicate_roles"] = []
        hygiene["duplicate_roles_error"] = f"{type(e).__name__}: {e}"
    hygiene["pdf_artifacts"] = package_pdf_rows(tmp)
    # PKG-6/7/8/9 (2026-10-15): statements the package makes about ITSELF that
    # contradict each other (an AI-use denial beside the AI workflow it denies,
    # one identifier at two lengths, one comparison described with two units).
    # Computed on the PUBLISHED copy -- these rows name the files the reader
    # actually receives -- and reported, never edited: which statement is true
    # is the author's call.
    hygiene["contradictions"] = package_contradiction_rows(tmp)
    # PKG-11/12/14/15/16 (2026-10-17): package self-consistency the audit found
    # in the delivered copies -- a sibling table whose header differs by one
    # letter (a silently dropped study), a statistics table whose p and its own
    # interval give opposite verdicts, a "pooled" table computed on a subset, a
    # form whose software list omits the paper's tools, and a cover letter that
    # denies a prior submission the package itself documents.
    try:
        _submitted_docs = [rr.relative_to(tmp).as_posix() for rr in _iter_tree_files(tmp)
                           if rr.is_file()]
        _pkg_texts = _package_document_texts(tmp)
        hygiene["package_consistency"] = {
            "column_near_misses": scan_column_name_near_misses(tmp),
            "mcb_rule_conflicts": scan_mcb_rule_conflicts(tmp),
            "pooled_table_mismatches": scan_pooled_table_mismatches(tmp),
            "form_software_coverage": scan_form_software_coverage(tmp),
            "prior_submission_disclosure": scan_prior_submission_disclosure(
                tmp, submitted_docs=_submitted_docs),
            "form_method_conflicts": scan_form_method_conflicts(tmp, texts=_pkg_texts),
            "ranking_claim_conflicts": scan_ranking_claim_conflicts(tmp, texts=_pkg_texts),
            "recovered_structure_claims": scan_recovered_structure_claims(tmp,
                                                                         texts=_pkg_texts),
            "sd_estimator_ambiguity": scan_sd_estimator_ambiguity(tmp, texts=_pkg_texts),
            "definition_overreach": scan_definition_overreach(tmp, texts=_pkg_texts),
            "cited_note_negations": scan_cited_note_negations(tmp, texts=_pkg_texts),
            "single_cell_citation_mismatch": scan_single_cell_citation_mismatch(
                tmp, texts=_pkg_texts),
            "caption_definition_gaps": scan_caption_definition_gaps(tmp, texts=_pkg_texts),
            "form_failure_claims": scan_form_failure_claims(tmp, texts=_pkg_texts),
        }
    except Exception as e:                                            # noqa: BLE001
        hygiene["package_consistency"] = {"error": f"{type(e).__name__}: {e}"}
    # Front-matter GLUE that the mechanical repair cannot resolve (the fused
    # `<name><address>` token): reported, never re-spaced by guesswork.
    hygiene["front_matter_glue"] = package_front_matter_glue_rows(tmp)
    # PKG-4: a figure the documents cite (and legend) that the package carries
    # nowhere. Computed on the PUBLISHED copy, whose names and bytes are the
    # judged ones, so the row names the file the author will actually hand over.
    hygiene["display_items"] = package_display_item_rows(
        tmp, submission_not_carried_areas(ctx))
    # PKG-5: two shipped surfaces attributing one display item to different
    # producers (a resources-table row vs the item's own legend). Reported at
    # publication because no mechanical repair may choose between them.
    hygiene["display_provenance"] = display_provenance_rows(
        tmp, submission_not_carried_areas(ctx))
    # WHAT THE SUBMISSION ACTUALLY CARRIES, per the package's own README: the
    # declaration the scoped scans above already used (or the reason it was
    # ignored). Recorded so the status document states the set the judgements were
    # made against instead of leaving the operator to infer it.
    hygiene["submission_declaration"] = declared_submission_set(tmp)
    # Title-page facts the recorded rule set cannot check (a rule the venue did
    # not state is COUNTED AND NAMED, never invented): the content type this run
    # is configured for, when the title page does not print it.
    hygiene["front_matter_gaps"] = front_matter_gap_rows(ctx, tmp)
    # PKG-2 (AGENTS.md: nothing that ships points at what does not ship). The
    # journal submission's own assembly scans the copy it just stripped; THIS
    # path published every other deliverable, and it never ran the scan at all
    # -- a supplementary legend that names the analysis script and the raw-data
    # archive reached the certified package with no row anywhere (2026-10-15).
    # The not-carried areas are the standing ones (see
    # `submission_not_carried_areas`), because this copy is the corpus the
    # author submits FROM: it still carries `code/` and the evidence, and the
    # submission does not.
    hygiene["non_submitted_references"] = non_submitted_reference_rows(
        tmp, submission_not_carried_areas(ctx))
    # REV-1/REV-2: the champion's OWN open items. Computed HERE (not in the
    # readme writer) so decision.json, the readiness block, `--require-ready`
    # and the sibling hand-off file all read one derivation. Guarded like the
    # PKG-2 repair above: reading a run's ledger is bookkeeping, and a damaged
    # or pruned sandbox must degrade to "no items recorded", never abort a
    # publication that has already verified its digests.
    try:
        open_items = collect_open_review_items(ctx, final)
        open_items["sibling"] = write_open_items_sibling(ctx, open_items)
    except Exception as e:                                            # noqa: BLE001
        open_items = {"error": f"{type(e).__name__}: {e}", "items": [], "discarded": [],
                      "statuses": {}, "sibling": None}
    # Non-shippable files were removed from the STAGE output before its corpus
    # digest. Carry that stage-side record into the delivery report without
    # touching the judged bytes again.
    _champ_rec = ctx.run(open_items.get("run")) or {}
    _strip_rec = _champ_rec.get("non_shippable_strip") or {}
    for rel in _strip_rec.get("removed") or []:
        if is_bytecode_cache_name(Path(rel).name):
            hygiene["removed_bytecode_cache"].append(rel)
        elif is_word_owner_name(Path(rel).name):
            hygiene["removed_word_owner_files"].append(rel)
        else:
            hygiene["removed_platform_junk"].append(rel)
    hygiene["held_internal_readme_notes"] = list(
        _champ_rec.get("held_internal_readme_notes") or [])
    # `author_to_complete: readme`: the published package gets ONE README
    # checklist even when the stage forgot to write it. Every row is copied from
    # the revision ledger / residual record / a literal marker already in the
    # package; no document is edited and no item is invented.
    if author_to_complete_mode_of(ctx) == "readme":
        try:
            _hreadme = write_published_handoff_readme(
                tmp, open_items, residuals,
                target_path=ctx.root / FINAL_CLEAN_AUTHOR_README_NAME)
            if _hreadme:
                hygiene["handoff_readme"] = _hreadme
        except Exception as e:                                        # noqa: BLE001
            hygiene["handoff_readme"] = {"error": f"{type(e).__name__}: {e}"}
    # A filled XFA form cannot be FLATTENED offline (that needs Acrobat), but
    # its answers can be rendered readably -- so the decision readme points at
    # a text rendering of every answer instead of leaving the reviewer with the
    # Adobe placeholder. Written to the reports directory, never into the
    # package (the package stays byte-clean manuscript content).
    hygiene["xfa_exports"] = []
    _fmt_mod = _format_module()
    if _fmt_mod is not None and hasattr(_fmt_mod, "xfa_export_text"):
        xfa_dir = Path(ctx.reports_dir) / "xfa_exports"
        for r in hygiene["pdf_artifacts"]:
            if r.get("rule") not in ("FMT-PDF1", "FMT-PDF2", "FMT-PDF4"):
                continue
            src_pdf = tmp / str(r.get("document") or "")
            if not src_pdf.is_file():
                continue
            text = _fmt_mod.xfa_export_text(src_pdf)
            if not text:
                continue
            xfa_dir.mkdir(parents=True, exist_ok=True)
            dest = xfa_dir / (src_pdf.name + ".answers.txt")
            write_text_atomic(dest, text)
            hygiene["xfa_exports"].append({"document": r.get("document"),
                                           "export": str(dest)})
    # The readiness verdict must describe the files that were ACTUALLY
    # published, not only the pre-publication winner directory: the pin fallback
    # can publish when the winner directory is absent, and the delivery hygiene
    # can change the tree. A scan failure is recorded as a coverage gap rather
    # than silently reading as "within the cap".
    try:
        published_lengths = scan_lengths_in_sources(
            [(tmp, "", ())], profile=venue_profile_of(ctx, required=False))
    except Exception as e:                                            # noqa: BLE001
        published_lengths = {"error": f"{type(e).__name__}: {e}",
                             "over_limit": [], "rows": [], "checked": False}
    hygiene["lengths"] = published_lengths
    manifest = corpus_dir_manifest(tmp)
    final_digest = manifest_digest(manifest)
    # "Unchanged" must mean the delivered tree carries the SAME FILES **and**
    # the same bytes. The file-list test alone is not enough: this function's
    # hygiene filters can change (2026-10-15: the platform-junk sweep learned to
    # see a stub that had shipped inside `figures/`), but the ordinary re-decide
    # can also change the champion's CONTENT under the same names (a formatter,
    # a PKG-2 sentence strip, a Zotero refresh) -- and reusing the old directory
    # then served stale bytes while the record reported the NEW digest.
    # One manifest function on both sides (corpus_dir_manifest: the same one the
    # pin check uses) makes the identity comparable; differing file sets and
    # differing content both republish.
    if dst.is_dir() and corpus_dir_manifest(dst) == manifest:
        rmtree_force(tmp, ignore_errors=True)
        return dict(_meta, path=str(dst), digest=final_digest, pin_digest=pin_digest,
                    files=manifest["count"], renamed=counter["renamed"],
                    raw_data_untouched=hygiene["raw_data_untouched"],
                    modes_cleared=len(chmod_plan),
                    format_fix=format_fix, hygiene=hygiene, open_items=open_items,
                    lengths=published_lengths,
                    zip=write_final_clean_zip(dst, zip_path), action="unchanged")
    if dst.is_dir():
        # The delivered copy differs from what this decision produced -- a
        # hygiene rule now holds a file back, one appeared beside the
        # manuscript, or the champion's own bytes changed under the same names:
        # the delivered copy is STALE, and a stale copy is what the author hands
        # to the journal. Republish it.
        print(f"[decide] the published copy at {dst.name}/ no longer matches the "
              f"package this decision produced; it is archived under "
              f"{superseded_dir_of(ctx).name}/ and rebuilt")
    if dst.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        aside = unique_path(superseded_dir_of(ctx) / f"{fc_name}.{stamp}")
        aside.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(aside))
    os.replace(tmp, dst)
    return dict(_meta, path=str(dst), digest=final_digest, pin_digest=pin_digest,
                files=manifest["count"], renamed=counter["renamed"],
                raw_data_untouched=hygiene["raw_data_untouched"],
                modes_cleared=len(chmod_plan),
                format_fix=format_fix, hygiene=hygiene, open_items=open_items,
                lengths=published_lengths,
                zip=write_final_clean_zip(dst, zip_path), action="created")


def final_clean_readme_text(ctx: Ctx, certification: dict, final: dict,
                            final_clean: dict) -> str:
    """The SIBLING status document that always accompanies final_clean_version/.

    The verdict, the blockers, the champion identity and the package digests --
    written next to the directory, never inside it (anything inside would become
    manuscript content in the next run).
    """
    cert = certification or {}
    fc = final_clean or {}
    verdict = certification_label(cert)
    pin = final.get("pin") or {}
    stored = final.get("stored") or {}
    L = ["# final_clean_version — status", ""]
    L.append(f"Generated: {utcnow()}  |  pipeline root: `{ctx.root}`  |  "
             f"orchestrator v{VERSION}")
    L.append("")
    L.append(f"**Certification: {verdict}.**")
    L.append("")
    L.append(f"- champion: `{stored.get('champion')}` (round {stored.get('round')}); "
             f"pin `{pin.get('id') or stored.get('pin_id')}`, digest "
             f"`{str(pin.get('digest'))[:12]}`")
    # THE LENGTH STATUS (2026-10-16). `decision.json` has carried the M19
    # `length_note` all along -- including "OVER-VENUE-LIMIT (inside the
    # pipeline's margin)" -- and the SIBLING README, the one document the author
    # actually reads beside the package, did not: the 2026-10-15b CNB package
    # went out with a 3,726-word main text against Nature Biotechnology's own
    # 3,000-word limit and a title page declaring 3,745, and no delivered line
    # said so. The margin is the pipeline's own relaxation, so a submission that
    # uses it MUST be visible where the package is handed over.
    _lens = (fc or {}).get("lengths") or final.get("lengths") or {}
    _note = (length_note(_lens) if _lens
             else str(final.get("length_note") or "").strip())
    if _note:
        L.append(f"- length status (M19): {_note}")
    if cert.get("blockers"):
        L.append("- blockers (why the decision is not certified):")
        L.extend(f"  - {b}" for b in cert["blockers"])
    if cert.get("notes"):
        L.append("- notes:")
        L.extend(f"  - {n}" for n in cert["notes"])
    L.append(f"- this decision's exit code: {cert.get('exit_code')}")
    if fc.get("skipped"):
        L.append(f"- final_clean_version/: NOT (re)built by this decision -- {fc['skipped']}")
    else:
        L.append(f"- final_clean_version/: {fc.get('action', 'published')}; "
                 f"{fc.get('files', '?')} file(s), digest `{str(fc.get('digest'))[:12]}`"
                 + f", {fc.get('raw_data_untouched', 0)} raw-data file(s) untouched")
        _zip = fc.get("zip") or {}
        if _zip.get("path"):
            L.append(f"- the same package is compressed at `{_zip['path']}` "
                     f"({_zip.get('files', '?')} file(s), {_zip.get('bytes', '?')} bytes); "
                     f"the directory is kept in place.")
    hygiene = fc.get("hygiene") or {}
    stripped = hygiene.get("stripped_bookkeeping") or []
    if stripped:
        L.append(f"- the pipeline's own by-product(s) were NOT published (stripped by name): "
                 + ", ".join(f"`{n}`" for n in stripped[:8])
                 + (" …" if len(stripped) > 8 else ""))
    word_owner = hygiene.get("removed_word_owner_files") or []
    if word_owner:
        L.append(f"- {len(word_owner)} Word owner (lock) file(s) were NOT published (a Word "
                 f"by-product -- it holds the opening user's name and is not a document): "
                 + ", ".join(f"`{n}`" for n in word_owner[:8])
                 + (" …" if len(word_owner) > 8 else ""))
    present_owner = [
        rel for rel in (hygiene.get("present_non_shippable") or [])
        if is_word_owner_name(Path(rel).name)
    ]
    if present_owner:
        L.append(f"- {len(present_owner)} Word owner (lock) file(s) remain in the judged bytes "
                 f"and cannot be removed without breaking the champion identity; the journal "
                 f"submission assembly excludes them: "
                 + ", ".join(f"`{n}`" for n in present_owner[:8]))
    junk = hygiene.get("removed_platform_junk") or []
    if junk:
        L.append(f"- {len(junk)} operating-system by-product file(s) were NOT published (a "
                 f"download/desktop stub such as `<name>:Zone.Identifier` or `.DS_Store`: no "
                 f"content, and a name that reads like a file the submission does not "
                 f"contain): " + ", ".join(f"`{n}`" for n in junk[:8])
                 + (" …" if len(junk) > 8 else ""))
    bytecode = hygiene.get("removed_bytecode_cache") or []
    if bytecode:
        L.append(f"- {len(bytecode)} Python bytecode cache file(s) (`*.pyc`) were NOT published "
                 f"(a side effect of RUNNING a helper script -- never a deliverable): "
                 + ", ".join(f"`{n}`" for n in bytecode[:8])
                 + (" …" if len(bytecode) > 8 else ""))
    dangling = hygiene.get("non_submitted_references") or []
    _pkg2 = [r for r in dangling if str(r.get("rule") or "PKG-2") != "PKG-3"]
    _pkg3 = [r for r in dangling if str(r.get("rule") or "") == "PKG-3"]
    if _pkg2:
        L.append(f"- **{len(_pkg2)} dangling reference(s) (PKG-2) remain in the judged "
                 f"bytes** -- publication preserves the scored digest, so the author must "
                 f"repair these before upload:")
        for _row in _pkg2[:12]:
            L.append(f"  - `{_row.get('file')}` line {_row.get('line')}: "
                     f"`{_row.get('reference')}` -- {_row.get('detail')}")
    if _pkg3:
        L.append(f"- {len(_pkg3)} name(s) the package carries nowhere (PKG-3, advisory): "
                 f"confirm the locator or drop the pointer -- this is not a must-repair "
                 f"PKG-2 row:")
        for _row in _pkg3[:12]:
            L.append(f"  - `{_row.get('file')}` line {_row.get('line')}: "
                     f"`{_row.get('reference')}` -- {_row.get('detail')}")
    held_readmes = hygiene.get("held_internal_readme_notes") or []
    if held_readmes:
        L.append(f"- {len(held_readmes)} `README*.md`/`README*.txt` file(s) carrying a revision "
                 f"session's own working notes were NOT published (held outside the package at "
                 f"`reports/{README_NOTE_HOLD_DIRNAME}/`; the author's documentation is carried "
                 f"by the corpus, but a note that narrates how the package was produced may "
                 f"not ship): " + ", ".join(f"`{r.get('file')}`" for r in held_readmes[:6])
                 + (" …" if len(held_readmes) > 6 else ""))
        for r in held_readmes[:3]:
            _row = (r.get("rows") or [{}])[0]
            L.append(f"  - `{r.get('file')}` line {_row.get('line')}: "
                     f"{str(_row.get('evidence'))[:160]}")
    decl = hygiene.get("submission_declaration") or {}
    if decl.get("declared"):
        L.append(f"- the SUBMITTED SET comes from the package's own `{decl.get('readme')}`: "
                 + " / ".join(f"`{p}`" for p in decl.get("patterns") or [])
                 + f" ({decl.get('submitted_count', len(decl.get('files') or []))} file(s); every "
                   f"submission-surface check above was made against that set -- the other "
                   f"{len(decl.get('carried_not_submitted') or [])} carried file(s) are not part "
                   f"of the submission)")
    elif decl.get("ignored_reason"):
        L.append(f"- the package's own README declares a submission rule that was IGNORED "
                 f"({decl['ignored_reason']}); the submission-surface checks used the pipeline's "
                 f"own model (the corpus minus the evidence areas, `code/` and the author's "
                 f"READMEs)")
    internal = hygiene.get("internal_artifacts") or []
    if internal:
        L.append("")
        L.append(f"**{len(internal)} internal-artifact finding(s) in the published package "
                 f"(PKG-1) -- the author must remove or rewrite these before submitting:**")
        for r in internal[:12]:
            L.append(f"  - `{r.get('file')}` line {r.get('line')}: {r.get('detail')}")
        if len(internal) > 12:
            L.append(f"  - … and {len(internal) - 12} more (see reports/decision.json)")
    ref_strip = hygiene.get("removed_dangling_references") or {}
    if ref_strip.get("removed"):
        L.append("")
        _strip_artifact = str(ref_strip.get("artifact") or "").strip()
        L.append(f"Dangling references: {ref_strip['removed']} sentence(s) that pointed at "
                 f"content this submission does not carry (the analysis code, the raw data, "
                 f"the review feedback, a README) were REMOVED from the to-be-submitted "
                 f"document(s) -- a submitted file may not refer to what it does not ship. "
                 f"The removal ran in the stage that wrote the champion, BEFORE it was pinned: "
                 f"the published bytes already carry the repair (publication itself preserves "
                 f"the judged bytes). The removed sentences are recorded verbatim in "
                 f"`reports/decision.json` (`final_clean.hygiene.removed_dangling_references`)"
                 + (f" and in `{_strip_artifact}`" if _strip_artifact else "") + ":")
        for f in (ref_strip.get("files") or [])[:12]:
            for s in (f.get("removed") or [])[:4]:
                L.append(f"  - `{f.get('file')}`: {str(s)[:200]}")
    if ref_strip.get("removed_links"):
        L.append("")
        L.append(f"Local-path links: {ref_strip['removed_links']} attached-template link(s) "
                 f"pointing at a path on somebody's own machine (the venue's Word template "
                 f"carries one into every restyled package) were REMOVED from the package "
                 f"part(s) that named them:")
        for f in (ref_strip.get("files") or [])[:12]:
            for s in (f.get("removed_links") or [])[:4]:
                L.append(f"  - `{f.get('file')}`: {str(s)[:200]}")
    if ref_strip.get("remaining"):
        L.append("")
        L.append(f"**{len(ref_strip['remaining'])} dangling reference(s) could NOT be removed "
                 f"mechanically (PKG-2) -- a structural file or a sentence carrying a live "
                 f"citation field; the author must repair them:**")
        for r in ref_strip["remaining"][:12]:
            L.append(f"  - `{r.get('file')}` line {r.get('line')}: `{r.get('reference')}`")
    # REV-1/REV-2: the champion's OWN open items (2026-10-15). This block is the
    # reason the readme exists: a CERTIFIED verdict answers "did the process
    # hold?", never "is anything left for the author". Without it the readme said
    # "submission-ready" while the revision had handed the author 7-9 items --
    # and the only pointer to them was a path inside the run's sandbox.
    oi = (fc.get("open_items") or {})
    oi_items = list(oi.get("items") or [])
    oi_dropped = list(oi.get("discarded") or [])
    if oi_items or oi_dropped or (oi.get("manual_steps") and oi.get("manual_steps_items")):
        L.append("")
        L.append(f"**Open item(s) the champion's own revision handed to the author "
                 f"({len(oi_items)} unresolved"
                 + (f", {len(oi_dropped)} discarded without the auditor's support"
                    if oi_dropped else "")
                 + ") -- the pipeline cannot fix these offline and they are NOT part of the "
                   "certification verdict:**")
        if oi.get("run"):
            L.append(f"  - source: the champion's producing run `{oi['run']}` "
                     f"({oi.get('kind') or 'stage'}); its hand-off list is copied beside this "
                     f"file as `{FINAL_CLEAN_STEPS_NAME}`")
        for it in oi_items[:14]:
            L.append(f"  - `{it.get('id')}` [{it.get('status')}] "
                     f"{it.get('check') or ''} {it.get('severity') or ''}".rstrip()
                     + (f" -- {str(it.get('location'))[:160]}" if it.get("location") else ""))
        if len(oi_items) > 14:
            L.append(f"  - … and {len(oi_items) - 14} more (see `readiness.open_items` in "
                     f"`reports/decision.json` and `{FINAL_CLEAN_STEPS_NAME}`)")
        for it in oi_dropped[:6]:
            L.append(f"  - `{it.get('id')}` [DISCARDED by the reviser, auditor verdict "
                     f"`{it.get('audit_verdict') or 'none'}`] "
                     + (f"-- {str(it.get('location'))[:160]}" if it.get("location") else ""))
    pdfs = hygiene.get("pdf_artifacts") or []
    prov = hygiene.get("display_provenance") or []
    if prov:
        L.append("")
        L.append(f"**{len(prov)} display-item provenance contradiction(s) (PKG-5) -- two shipped "
                 f"surfaces attribute the same item to different tools; the author must say which "
                 f"side is right:**")
        for r in prov[:12]:
            L.append(f"  - `{r.get('file')}` [{r.get('rule')}] {r.get('item')}: "
                     f"{str(r.get('detail'))[:300]}")
    contr = hygiene.get("contradictions") or []
    if contr:
        L.append("")
        L.append(f"**{len(contr)} self-contradiction(s) in the published package (PKG-6/7/8/9) "
                 f"-- the same submission makes two statements that cannot both hold; the "
                 f"author must decide which is true:**")
        for r in contr[:12]:
            L.append(f"  - `{r.get('file')}` [{r.get('rule')}]: {str(r.get('evidence'))[:220]}")
    if pdfs:
        L.append("")
        L.append(f"**{len(pdfs)} PDF artifact finding(s) in the published package "
                 f"(FMT-PDF*) -- a form that renders blank or an unreadable export:**")
        for r in pdfs[:12]:
            L.append(f"  - `{r.get('document')}` [{r.get('rule')}]: {r.get('detail')}")
        if len(pdfs) > 12:
            L.append(f"  - … and {len(pdfs) - 12} more (see reports/decision.json)")
    xfa_exports = hygiene.get("xfa_exports") or []
    if xfa_exports:
        L.append("")
        L.append("Readable rendering(s) of the form answers (generated by the pipeline, so the "
                 "answers can be reviewed even where the PDF shell shows the Adobe placeholder):")
        for r in xfa_exports[:8]:
            L.append(f"  - `{r.get('document')}` -> `{r.get('export')}`")
    zu = hygiene.get("zotero_unlinked") or {}
    live_fields = hygiene.get("zotero_live_fields") or []
    unlinked = zu.get("documents") or []
    fields_before = sum((zu.get("fields_before") or {}).values()) if isinstance(
        zu.get("fields_before"), dict) else 0
    if zu.get("requested") and not live_fields and unlinked:
        L.append("")
        L.append(f"Citation fields: refreshed and UNLINKED in the published copy "
                 f"({len(unlinked)} document(s), {fields_before} field(s) flattened to plain "
                 f"citation text carrying the verified numbering) — no Word/Zotero conversion "
                 f"can renumber it. The pinned copies in this run keep the live fields.")
    elif zu.get("requested") and live_fields:
        L.append("")
        L.append(f"**Citation fields: flattening was requested but {len(live_fields)} document(s) "
                 f"still carry live fields** (the offline refresh refused them; see "
                 f"`readiness.findings` and the formatter's `zotero_refresh.skip`): "
                 + ", ".join(f"`{r.get('file')}` ({r.get('fields')})" for r in live_fields[:6]))
    elif zu and zu.get("requested") is False and fields_before and live_fields:
        L.append("")
        L.append(f"Citation fields: refreshed and left LIVE in the published copy "
                 f"({fields_before} field(s)) — publication preserves the judged bytes, so "
                 f"unlinking them in the final submission file is the author's own step. To "
                 f"have the pipeline flatten every candidate BEFORE it is judged, set "
                 f"`format_policy.unlink_zotero_fields: true` (or the stage-side "
                 f"`unlink_zotero_fields_at_publish`) and re-run; `decide` cannot flatten a "
                 f"judged package.")
    package_findings = cert.get("package_findings") or []
    _blocking = [f for f in package_findings if not f.get("advisory")]
    _advisory = [f for f in package_findings if f.get("advisory")]
    if cert.get("certified") and _blocking:
        L.append("")
        L.append(f"**Submission readiness: NOT READY -- {len(_blocking)} package-level "
                 f"finding(s) above (including every open review item the champion's own "
                 f"revision handed to the author) must be resolved (or explicitly waived) "
                 f"before this package "
                 f"is uploaded.** The pipeline fixed everything it can fix offline (Zotero "
                 f"numbering/bibliography, reference-entry facts, formatting); the remaining "
                 f"items are listed here and in `reports/decision.json` "
                 f"(`readiness.findings`). `decide --require-ready` turns them into blockers.")
    elif cert.get("submission_ready") is False and not _blocking:
        L.append("")
        L.append("**Submission readiness: see `reports/decision.json` `readiness` block.**")
    if _advisory:
        L.append("")
        L.append(f"{len(_advisory)} ADVISORY item(s) (reported, never gated -- the pipeline "
                 f"cannot decide them):")
        for _f in _advisory[:10]:
            L.append(f"  - `{_f.get('document')}` [{_f.get('rule')}]: "
                     f"{str(_f.get('detail'))[:220]}")
        if len(_advisory) > 10:
            L.append(f"  - … and {len(_advisory) - 10} more")
    L.append("")
    if not (final_clean or {}).get("files"):
        L.append("> **final_clean_version/ was NOT published.** "
                 + (f"The reason: {final_clean.get('skipped')}. " if final_clean and
                    final_clean.get("skipped") else "")
                 + "There is no champion directory to start the next run from; the decision "
                   "and its blockers above are the record of this run.")
    elif cert.get("certified"):
        if cert.get("submission_ready") is False:
            L.append("This directory is the champion corpus. The panel completed and signed "
                     "the comparison; the readiness findings above still block upload. "
                     f"`setup --source {ctx.root / final_clean_dirname(ctx.root)}` starts the "
                     "next run from these bytes.")
        else:
            L.append(f"This directory is the certified champion corpus: "
                     f"`setup --source {ctx.root / final_clean_dirname(ctx.root)}` starts the "
                     f"next run from it.")
    else:
        L.append("> **Do not treat this directory as a certified answer.** It is the champion "
                 "corpus this decision produced; the blockers above say why the decision was "
                 "not signed. Inspect it, or start the next run from it only after resolving "
                 "them.")
    L.append("")
    L.append("(This file is a SIBLING of the directory on purpose: the directory must stay a "
             "byte-clean manuscript corpus, so anything written into it would become manuscript "
             "content in the next run.)")
    return "\n".join(L)


def write_final_clean_readme(ctx: Ctx, certification: dict, final: dict,
                             final_clean: dict) -> Path:
    """Write `<root>/final_clean_version.readme.md`; always called by `decide`."""
    p = ctx.root / FINAL_CLEAN_README_NAME
    write_text_atomic(p, final_clean_readme_text(ctx, certification, final, final_clean))
    return p


# ---- the champion's OWN open items (2026-10-15) -----------------------------
# The revision stages hand their unfinishable work to the author in
# `MANUAL_STEPS.md`, and the machine-readable ledger records one disposition per
# frozen finding (`fixed`, `fixed-with-caveat`, `manual-required`, `discarded`).
# Both live INSIDE the producing run's sandbox, which is never delivered: the
# 2026-10-15 operator report on the two clean packages was the visible half of
# this --
#   * `final_clean_version.readme.md` said CERTIFIED / submission-ready while
#     the champion's own revision had handed the author 7 (neohet) and 9 (cnb)
#     `manual-required` items, including two Major artwork defects and a
#     discarded-then-refuted data/manuscript contradiction;
#   * `DECISION_REPORT.md` told the reader to "read the champion's hand-off list
#     ... `revised/MANUAL_STEPS.md`" -- a path inside `runs/<id>/`, which the
#     package does not carry and the author never sees.
# The fix is a carrier, not a new judgement: the same rows the stage wrote are
# listed in the published status (readiness findings REV-1/REV-2), the
# MANUAL_STEPS file is copied to a SIBLING of the published directory
# (`final_clean_version.manual_steps.md` -- never inside it, which would make it
# manuscript content in the next run), and the decision report prints both.
OPEN_ITEM_STATUSES = ("manual-required", "fixed-with-caveat", "unresolved")
STAGE_REPORT_NAMES = ("revision_report.json", "integration_report.json")
FINAL_CLEAN_STEPS_NAME = "final_clean_version.manual_steps.md"
# `# MANUAL_STEPS — what the author must do (7 hand-off items, grouped ...)`
MANUAL_STEPS_COUNT_RE = re.compile(r"\((\d+)\s+hand-off items?")


def champion_producing_run(ctx: Ctx, final: dict) -> dict:
    """The run record that produced the champion (its ledger is the source).

    Resolved from the pin, which records `produced_by_run` when the champion is
    a fresh arm (a rewrites/revise/integrate run). A champion that IS the round
    base or the pristine original has no producing run: its open items are the
    ones its own frozen review filed, which `collect_residuals` already carries.
    """
    stored = (final or {}).get("stored") or {}
    pin = (final or {}).get("pin") or {}
    rec = find_pin(ctx, stored.get("pin_id")) or pin or {}
    rid = rec.get("produced_by_run") if isinstance(rec, dict) else None
    run = (ctx.state.get("runs") or {}).get(rid) if rid else None
    return run or {}


def collect_open_review_items(ctx: Ctx, final: dict) -> dict:
    """The champion's open review items + its own hand-off list.

    Returns {"run", "kind", "statuses", "items", "discarded", "manual_steps",
    "manual_steps_text", "manual_steps_items"}. `items` are the rows the
    champion's revision left open for the author (`manual-required`,
    `fixed-with-caveat`, `unresolved`); `discarded` are the rows the reviser
    closed as `discarded` where the round's auditor did NOT support the drop --
    a drop hides the finding from every later reader, so it is reported as its
    own item (REV-2) instead of vanishing with the sandbox.
    """
    info = {"run": None, "kind": None, "statuses": {}, "items": [], "discarded": [],
            "manual_steps": None, "manual_steps_text": None, "manual_steps_items": 0}
    rec = champion_producing_run(ctx, final)
    rid = rec.get("id")
    if not rid:
        return info
    info["run"] = rid
    info["kind"] = rec.get("kind")
    sb = ctx.runs_dir / str(rid)
    outdir = sb / output_dir_for_kind(rec.get("kind"))
    report = None
    for name in STAGE_REPORT_NAMES:
        cand = outdir / name
        if cand.is_file():
            report = read_json(cand)
            if report:
                break
    report = report or {}
    info["statuses"] = {str(k): int(v) for k, v in
                        (report.get("counts_by_status") or report.get("counts") or {}).items()
                        if is_int(v)}
    coverage = {str(r.get("id")): r for r in (report.get("coverage") or [])
                if isinstance(r, dict) and r.get("id")}
    findings = {str(f.get("id")): f for f in (report.get("findings") or [])
                if isinstance(f, dict) and f.get("id")}
    audit = read_json(sb / "audit" / "audit.json") or {}
    verdicts = {str(r.get("id")): str(r.get("verdict") or "").lower()
                for r in (audit.get("dispositions") or []) if isinstance(r, dict)}
    for fid, row in sorted(coverage.items()):
        status = str(row.get("final_status") or "")
        f = findings.get(fid) or {}
        item = {"id": fid, "status": status,
                "check": f.get("check") or row.get("check"),
                "severity": f.get("severity") or row.get("severity"),
                "category": f.get("category"),
                "location": f.get("location") or row.get("location"),
                "evidence": (row.get("evidence") or f.get("rationale")
                             or f.get("evidence") or f.get("explanation"))}
        if status in OPEN_ITEM_STATUSES:
            info["items"].append(item)
        elif status == "discarded":
            verdict = verdicts.get(fid, "")
            item["audit_verdict"] = verdict or None
            if verdict not in ("drop", "dropped"):
                info["discarded"].append(item)
    steps = outdir / "MANUAL_STEPS.md"
    if steps.is_file():
        try:
            text = steps.read_text("utf-8", "replace")
        except OSError:
            text = None
        if text:
            info["manual_steps"] = steps.relative_to(ctx.root).as_posix()
            info["manual_steps_text"] = text
            m = MANUAL_STEPS_COUNT_RE.search(text)
            if m:
                info["manual_steps_items"] = int(m.group(1))
            else:
                info["manual_steps_items"] = len(re.findall(r"(?m)^\*\*?[A-Z]{1,2}\d+", text))
    return info


def open_items_text(open_items: dict, limit: int = 40) -> str:
    """The hand-off list as one text block (the MANUAL_STEPS file, else the rows)."""
    oi = open_items or {}
    if oi.get("manual_steps_text"):
        return oi["manual_steps_text"].rstrip() + "\n"
    L = []
    for it in (oi.get("items") or [])[:limit]:
        L.append(f"* {it.get('id')} [{it.get('status')}] "
                 f"{it.get('check') or ''} {it.get('severity') or ''}".rstrip())
        if it.get("location"):
            L.append(f"  *Where*: {it['location']}")
        if it.get("evidence"):
            L.append(f"  *Evidence*: {it['evidence']}")
    for it in (oi.get("discarded") or [])[:limit]:
        L.append(f"* {it.get('id')} [DISCARDED, not supported by the round's auditor] "
                 f"{it.get('check') or ''} {it.get('severity') or ''}".rstrip())
        if it.get("location"):
            L.append(f"  *Where*: {it['location']}")
        if it.get("evidence"):
            L.append(f"  *Evidence*: {it['evidence']}")
    return "\n".join(L) + ("\n" if L else "")


def write_open_items_sibling(ctx: Ctx, open_items: dict) -> dict:
    """Write `<root>/final_clean_version.manual_steps.md` (a SIBLING, never inside).

    A sibling is the pipeline's own rule for status documents: anything written
    INSIDE the published directory would become manuscript content in the next
    run. When the producing stage left no `MANUAL_STEPS.md`, the ledger's own
    open rows are written instead, so the item list is never empty-by-omission.
    """
    oi = open_items or {}
    body = open_items_text(oi)
    if not body.strip():
        p = ctx.root / FINAL_CLEAN_STEPS_NAME
        if p.is_file():
            p.unlink()
        return {"path": None, "items": 0}
    head = [f"# Open items handed to the author — {ctx.root.name}",
            "",
            f"Generated: {utcnow()}  |  pipeline root: `{ctx.root}`  |  "
            f"orchestrator v{VERSION}",
            "",
            (f"Source: the champion's own revision run `{oi.get('run')}` "
             f"({oi.get('kind')}) — its `MANUAL_STEPS.md` and its finding ledger. "
             f"These items are NOT fixed by the pipeline; every one of them changes a "
             f"delivered document (or a read-only artifact the author owns), so the pipeline "
             f"reports them instead of inventing content."),
            f"Open item(s): {len(oi.get('items') or [])}"
            + (f"; unsupported discard(s): {len(oi.get('discarded') or [])}"
               if oi.get("discarded") else ""),
            "",
            "This file is a SIBLING of the published directory on purpose: the directory must "
            "stay byte-clean manuscript corpus.",
            ""]
    p = ctx.root / FINAL_CLEAN_STEPS_NAME
    write_text_atomic(p, "\n".join(head) + body)
    return {"path": str(p), "items": len(oi.get("items") or [])}


def _handoff_readme_items(final_clean: dict) -> dict:
    """{rel: item_count} for the hand-off README(s) in the published package."""
    out = {}
    base = Path(str((final_clean or {}).get("path") or ""))
    if not base.is_dir():
        return out
    # The hand-off README belongs in the package ROOT, beside the cover letter
    # and main text. A same-named file inside an evidence area is the author's
    # own data, never this mode's checklist.
    for p in sorted(base.iterdir()):
        if not p.is_file() or not is_author_to_complete_readme_name(p.name):
            continue
        n = count_manual_steps(p)
        if n is None:
            continue
        out[p.relative_to(base).as_posix()] = n
    return out


def package_readiness(final_clean: dict, residuals: dict = None,
                      author_to_complete: str = DEFAULT_AUTHOR_TO_COMPLETE,
                      lengths: dict = None) -> dict:
    """The published package's own findings, as a readiness verdict.

    Certification answers "did the pipeline's process hold?"; readiness
    answers "can THIS package be uploaded?". The two are different: a champion
    can be certified while the published copy still carries a form shell, an
    unfilled/boilerplate required document or internal working material. The
    findings are always recorded; `decide --require-ready` additionally turns
    them into blockers (exit 5), and the status readme always prints the
    verdict so "CERTIFIED" can never be read as "submission-ready" alone.

    `residuals` is the residual-gate record the same decision computed, and
    `author_to_complete` the root's hand-off policy (`readme` / `document` /
    `off`). They are read here so the two verdicts cannot contradict each other
    about the same shipped fact: the 2026-10-17 audit read
    `submission_ready: true` beside `certified: false -- hand-off markers still
    in the delivered package`, which is one package described two ways. A marker
    the residual gate already blocks on is named here too, and outside
    `document` every shipped marker is a defect of the package rather than a
    neutral hand-off.
    """
    hyg = (final_clean or {}).get("hygiene") or {}
    findings = []
    _atc = _atc_mode(author_to_complete)
    for it in ((residuals or {}).get("items") or []):
        it = str(it)
        # `collect_residuals` writes the unknown-state row as the hyphenated
        # "hand-off-marker scan FAILED"; the old space-only filter let that
        # blocker through, so readiness said submission_ready while
        # certification refused the same package.
        if "hand-off marker" not in it and "hand-off-marker" not in it:
            continue
        if _atc == "document":
            findings.append({
                "rule": "AUTH-1", "advisory": True,
                "detail": (f"the shipped package still carries the hand-off marker(s) the "
                           f"certification gate refuses on ({it}); under "
                           f"`author_to_complete: document` the marker is a legitimate hand-off, "
                           f"but this item is not submission-ready until the author "
                           f"disposes it")})
        else:
            findings.append({
                "rule": "AUTH-1",
                "detail": (f"this root runs with `author_to_complete: {_atc}`, so no document "
                           f"may carry the "
                           f"\"[AUTHOR TO COMPLETE: ...]\" marker: the item is supplied (or "
                           f"its verified negative written) in the document, or left out of "
                           f"the document and recorded in the package's "
                           f"{handoff_target(_atc)}. "
                           f"The certification gate already refuses this decision for it -- "
                           f"{it}")})
    # The hand-off README itself: never submission content, but every item in it
    # is a fact the submission still owes, so its presence makes the package NOT
    # submission-ready. One blocking row names the file and its item count (a
    # bullet/checkbox line or a Markdown table data row is one item). A README
    # with zero items is reported
    # too: it is the stale checklist the stage was told to delete.
    if _atc == "readme":
        for rel, rows in _handoff_readme_items(final_clean).items():
            findings.append({
                "rule": "AUTH-2", "document": rel,
                "detail": (f"the package carries {rows} author-to-complete item(s) in "
                           f"{rel} (a hand-off README beside the cover letter and main text; "
                           f"it is never submitted, and no submitted document may depend on "
                           f"it). Supply each item in the documents, then update or delete the "
                           f"README")})
        _handoff_rec = hyg.get("handoff_readme") or {}
        _handoff_path = Path(str(_handoff_rec.get("path") or ""))
        _published = Path(str((final_clean or {}).get("path") or ""))
        if _handoff_path.is_file() and _published.is_dir() \
                and _handoff_path.parent != _published:
            _rows = count_manual_steps(_handoff_path)
            findings.append({
                "rule": "AUTH-2", "document": _handoff_path.name,
                "detail": (f"the package's author-to-complete checklist is the SIBLING "
                           f"`{_handoff_path.name}` with {_rows if _rows is not None else '?'} "
                           f"item(s). It is outside the judged directory so publication can "
                           f"preserve the champion digest; supply each item and delete the "
                           f"checklist when it is empty")})
    handoff = hyg.get("handoff_readme") or {}
    if handoff.get("error"):
        findings.append({
            "rule": "AUTH-3", "document": AUTHOR_TO_COMPLETE_README,
            "detail": ("the publisher could not build/read the author checklist from the "
                       f"recorded open items: {handoff['error']}")})
    for problem in handoff.get("problems") or []:
        findings.append({
            "rule": "AUTH-3", "document": problem.get("file"), "advisory": True,
            "detail": ("hand-off marker coverage is UNVERIFIED in this file: "
                       f"{problem.get('problem') or problem}")})
    for r in hyg.get("internal_artifacts") or []:
        findings.append({"rule": r.get("rule") or "PKG-1",
                         "document": r.get("file"), "detail": r.get("detail")})
    for rel in hyg.get("present_non_shippable") or []:
        findings.append({
            "rule": "PKG-1", "document": rel,
            "detail": ("this non-shippable by-product is present in the judged bytes; it was "
                       "not removed after the pin because publication preserves the scored "
                       "digest. The journal submission assembly excludes it; remove it from "
                       "the source and re-run the round before treating the directory as a "
                       "clean handoff.")})
    if hyg.get("duplicate_roles_error"):
        findings.append({
            "rule": "PKG-26", "advisory": True,
            "detail": ("the duplicate-submission-role scan could not run: "
                       f"{hyg['duplicate_roles_error']}")})
    for r in hyg.get("duplicate_roles") or []:
        findings.append({
            "rule": r.get("rule") or "PKG-26",
            "document": r.get("file"),
            "detail": r.get("detail")})
    # M19 is a formatting finding, but a published package that is over a
    # configured limit is not submission-ready. The ranking never gates on a
    # word count; readiness does, because the venue cap (or the operator's cover
    # letter total) is a submission rule and the NeoHeteroclitic package reached
    # `final_clean` at 5,550 words against a 3,750-word relaxed cap.
    length_info = ((final_clean or {}).get("lengths") or lengths or {})
    if length_info.get("error"):
        findings.append({
            "rule": "FMT-M19", "advisory": True,
            "detail": (f"the published-package length scan could not run "
                       f"({length_info['error']}); the abstract/main-text/cover-letter "
                       f"caps were NOT verified")})
    length_rows = list(length_info.get("over_limit") or [])
    for r in length_rows:
        section = str(r.get("section") or "section")
        if section == "cover letter":
            cap = r.get("total_max")
            if cap is None:
                continue
            words = r.get("total_words")
            detail = (
                f"the cover letter totals {words} words against the configured "
                f"{cap}-word total-content cap (salutation, body, disclosures and "
                f"signature): trim non-persuading boilerplate or obtain an explicit "
                f"exception; never remove a claim about the work to meet the count")
        else:
            cap = r.get("cap")
            words = r.get("words")
            detail = (
                f"the {section} is {words} words against the relaxed limit of "
                f"{cap} words: trim by removing redundancy, or obtain an explicit "
                f"exception; never delete scientific content to meet the count")
        findings.append({
            "rule": "FMT-M19", "document": r.get("document"), "detail": detail})
    # PKG-2 leftovers: the pointers the mechanical removal may not touch (a
    # structural file, a sentence carrying a live citation field). The ones it
    # DID remove are recorded in the readme/decision as resolved work, not as
    # findings -- chasing an already-removed pointer would be a false positive.
    for r in ((hyg.get("removed_dangling_references") or {}).get("remaining") or []):
        detail = str(r.get("detail") or "")
        if not detail.startswith("line "):
            detail = f"line {r.get('line')}: {r.get('reference')} -- {detail}"
        findings.append({
            "rule": r.get("rule") or "PKG-2", "document": r.get("file"),
            "detail": detail})
    # The PUBLISH-TIME scan's rows: PKG-2 pointers the mechanical repair could
    # not remove, and the PKG-3 names the package carries nowhere. Until
    # 2026-10-15 this list was computed, recorded in the readme's own hygiene
    # block, and never reached `readiness.findings` -- so `--require-ready`
    # could not gate on the very rows the scan exists for.
    for r in hyg.get("non_submitted_references") or []:
        rule = r.get("rule") or "PKG-2"
        detail = (f"line {r.get('line')}: {r.get('reference')} -- {r.get('detail')}")
        row = {"rule": rule, "document": r.get("file"), "detail": detail}
        if str(r.get("severity") or "").lower() == "advisory" or rule == "PKG-3":
            # A name the package carries NOWHERE is reported for the author to
            # resolve, never gated: the pipeline cannot know whether the sentence
            # should ship the file, name a locator, or drop the pointer.
            row["advisory"] = True
        findings.append(row)
    for r in hyg.get("pdf_artifacts") or []:
        findings.append({"rule": r.get("rule"), "document": r.get("document"),
                         "detail": r.get("detail")})
    for r in hyg.get("front_matter_glue") or []:
        # The shapes the mechanical repair cannot split. Advisory: the space is
        # the author's (only they know where the name ends), but the delivered
        # file must not carry it unseen.
        findings.append({"rule": r.get("rule") or "FMT-X2",
                         "document": r.get("document"),
                         "advisory": True,
                         "detail": f"{r.get('location') or ''}: {r.get('evidence')} -- "
                                   f"{r.get('detail')}".strip(" -")})
    for r in hyg.get("display_items") or []:
        # PKG-4: a cited figure the submission carries nowhere. Advisory on
        # purpose: shipping the figure, embedding it, or dropping the citation is
        # the author's call -- but the delivered status must name it (the
        # 2026-10-15 report: "Figure S3 is cited and has a legend, but it is not
        # in the submission").
        findings.append({"rule": r.get("rule") or "PKG-4", "document": r.get("file"),
                         "advisory": True, "item": r.get("reference"),
                         "detail": f"line {r.get('line')}: {r.get('reference')} -- "
                                   f"{r.get('detail')}"})
    for r in hyg.get("display_provenance") or []:
        # PKG-5 is BLOCKING, not advisory: the two shipped surfaces contradict
        # each other about a fact, and the author is the only one who can say
        # which side is right (the pipeline must not silently pick one).
        findings.append({"rule": r.get("rule") or "PKG-5", "document": r.get("file"),
                         "item": r.get("item"),
                         "detail": r.get("detail")})
    for r in hyg.get("contradictions") or []:
        # PKG-6/7/8/9 are BLOCKING like PKG-5, and for the same reason: one of the
        # two statements is false (or the identifier is unusable), and only the
        # author knows which. The operator's audit found the AI disclosure on BOTH
        # packages, the truncated commit in the Reporting Summary and the
        # caption/table unit mismatch -- none of which any delivered line named.
        findings.append({"rule": r.get("rule") or "PKG-6", "document": r.get("file"),
                         "detail": f"{r.get('evidence')} -- {r.get('detail')}".strip(" -")})
    # PKG-11/12/14/15/16 (2026-10-17): the package's own tables and letter
    # contradict each other or the analysis they carry. BLOCKING: one of the two
    # statements is wrong (a dropped study, a verdict written two ways, a prior
    # submission the letter denies), and only the author can say which side holds.
    pc = hyg.get("package_consistency") or {}
    if pc.get("error"):
        findings.append({"rule": "PKG-11", "advisory": True,
                         "detail": (f"the package self-consistency scans could not run "
                                    f"({pc['error']}); these classes were NOT checked")})
    for key in ("column_near_misses", "mcb_rule_conflicts", "pooled_table_mismatches",
                "form_software_coverage", "prior_submission_disclosure",
                "form_method_conflicts", "ranking_claim_conflicts",
                "recovered_structure_claims", "sd_estimator_ambiguity",
                "definition_overreach", "cited_note_negations",
                "single_cell_citation_mismatch", "caption_definition_gaps",
                "form_failure_claims"):
        for r in pc.get(key) or []:
            findings.append({"rule": r.get("rule") or "PKG-11",
                             "document": r.get("file"),
                             "advisory": bool(r.get("advisory")),
                             "detail": f"line {r.get('line')}: {r.get('detail')}"})
    for r in hyg.get("front_matter_gaps") or []:
        findings.append({"rule": r.get("rule") or "FMT-TP1", "document": r.get("file"),
                         "advisory": True, "detail": r.get("detail")})
    xfa = []
    for r in hyg.get("xfa_exports") or []:
        xfa.append({"document": r.get("document"), "export": r.get("export")})
    zu = hyg.get("zotero_unlinked") or {}
    if zu.get("requested"):
        for r in hyg.get("zotero_live_fields") or []:
            findings.append({
                "rule": "FMT-Z7", "document": r.get("file"),
                "detail": (f"{r.get('fields')} live Zotero citation field(s) remain in the "
                           f"published copy although flattening was requested: the offline "
                           f"refresh/flatten pass did not remove them (a refused refresh — the "
                           f"formatter's zotero_refresh.skip names the reason — or "
                           f"format_fix=off), so they were left live rather than frozen with "
                           f"unverified numbering; refresh it in Word/Zotero and re-run, or "
                           f"flatten it manually and re-verify")})
    # REV-1/REV-2: the champion's OWN open items. A package whose revision stage
    # handed the author work is not "ready" merely because the mechanical gates
    # are clean -- the 2026-10-15 audit of the two clean packages was exactly
    # this: `submission_ready: true` beside a hand-off list naming a Major
    # artwork defect and a data/manuscript contradiction. `readiness.findings`
    # is the one list the readme, decision.json and `--require-ready` all read.
    oi = (final_clean or {}).get("open_items") or {}
    for it in (oi.get("items") or []):
        findings.append({
            "rule": "REV-1", "document": it.get("location") or it.get("id"),
            "item": it.get("id"), "status": it.get("status"),
            "check": it.get("check"), "severity": it.get("severity"),
            "detail": (f"the champion's own revision handed this item to the author "
                       f"({it.get('status')}; {it.get('check') or 'check'} "
                       f"{it.get('severity') or ''}): "
                       + str(it.get("evidence") or "see the hand-off list")).strip()})
    for it in (oi.get("discarded") or []):
        findings.append({
            "rule": "REV-2", "document": it.get("location") or it.get("id"),
            "item": it.get("id"), "status": "discarded",
            "check": it.get("check"), "severity": it.get("severity"),
            "detail": (f"the champion's revision DISCARDED this finding and the round's "
                       f"auditor did not support the drop (audit verdict: "
                       f"{it.get('audit_verdict') or 'none'}): {it.get('evidence') or ''} "
                       f"-- a drop hides the finding from every later reader, so it is "
                       f"listed here for the author to re-check").strip()})
    if oi.get("manual_steps") and not (oi.get("items") or oi.get("discarded")):
        findings.append({
            "rule": "REV-1", "document": Path(str(oi["manual_steps"])).name,
            "status": "manual-steps",
            "detail": (f"the champion's revision handed the author "
                       f"{oi.get('manual_steps_items') or 'an unstated number of'} manual "
                       f"item(s) (`{oi['manual_steps']}`); the delivered list is the sibling "
                       f"`{FINAL_CLEAN_STEPS_NAME}`")})
    blocking = [f for f in findings if not f.get("advisory")]
    return {"submission_ready": not blocking, "findings": findings,
            "blocking_findings": len(blocking),
            "advisory_findings": len(findings) - len(blocking), "xfa_exports": xfa,
            "open_items": {"run": oi.get("run"), "kind": oi.get("kind"),
                           "items": len(oi.get("items") or []),
                           "discarded": len(oi.get("discarded") or []),
                           "statuses": oi.get("statuses") or {},
                           "manual_steps": oi.get("manual_steps"),
                           "manual_steps_items": oi.get("manual_steps_items"),
                           "list": (oi.get("items") or []) + (oi.get("discarded") or [])}}


def readiness_gate_problems(readiness: dict, require_ready: bool) -> list:
    """The `--require-ready` gate: package findings as decision blockers."""
    if not require_ready or (readiness or {}).get("submission_ready"):
        return []
    findings = (readiness or {}).get("findings") or []
    # Only non-advisory findings gate; naming an advisory ("reported, never
    # gated") rule as the refusal reason, and counting it in the total, made
    # the message describe a different decision than the one computed.
    blocking = [f for f in findings if not f.get("advisory")]
    if not blocking:
        return []
    return [f"{len(blocking)} package-level finding(s) in the published package "
            f"(--require-ready): "
            + "; ".join(f"{f.get('rule')} on {f.get('document') or '(package)'}"
                        for f in blocking[:4])]


def collect_residuals(ctx: Ctx) -> dict:
    """Residual items the pipeline itself recorded on its runs.

    These are the leftovers an operator would otherwise find by reading the
    delivered documents: a `searchable` hand-off marker the lookup engine could
    already answer, a review whose decision tables were closed with one
    boilerplate sentence, or numbers in the abstract/legends that no shipped
    data table proves.

    Two lists, because they gate differently. GATING items are ones the pipeline
    KNOWS how to state and the deliverable contradicts (an answered marker, an
    unfilled/boilerplate decision table, an integration row that would undo a
    resolved finding): with `--residual-gate` (on by default) they become
    decision problems (exit 5). ADVISORY items are unresolved questions the
    operator may legitimately decide to ship (a number no shipped file proves):
    they are recorded and printed, never gated. Everything is always recorded in
    decision.json / the decision report.
    """
    items, gating, advisory = [], [], []

    def add(text: str, gate: bool) -> None:
        items.append(text)
        (gating if gate else advisory).append(text)

    for rec in sorted((ctx.state.get("runs") or {}).values(),
                      key=lambda r: str(r.get("id"))):
        if rec.get("status") != "done":
            continue
        kind, rid = rec.get("kind"), rec.get("id")
        res = rec.get("residual") or {}
        if kind in ("revise", "integrate", "rewrite"):
            _atc = author_to_complete_mode_of(ctx)
            if res.get("handoff_marker_scan_error"):
                # The marker COUNT is unknown; a gate that could not run must
                # not be reported as a clean package.
                add(f"{rid}: the hand-off-marker scan FAILED "
                    f"({res['handoff_marker_scan_error']}); the delivered package's marker "
                    f"state is UNKNOWN -- repair the unreadable/broken file and re-run the "
                    f"stage before shipping", gate=True)
            if res.get("handoff_markers") and _atc != "document":
                # `readme` / `off`: the operator's policy is that no document
                # carries the "[AUTHOR TO COMPLETE: ...]" token, so every marker
                # still in the delivered package is a defect of that package
                # (not the neutral hand-off it is under `document`).
                add(f"{rid}: {res['handoff_markers']} hand-off marker(s) are still in the "
                    f"delivered package although this root runs with "
                    f"`author_to_complete: {_atc}` "
                    f"({', '.join((res.get('handoff_marker_files') or [])[:5])}); the item "
                    f"belongs in the document or in the package's own "
                    f"{handoff_target(_atc)}, never "
                    f"as a marker inside a file that ships", gate=True)
            if res.get("answerable_placeholders"):
                add(f"{rid}: {res['answerable_placeholders']} searchable hand-off marker(s) "
                    f"that the lookup engine answered are still in the delivered package "
                    f"(see runs/{rid}/work/PLACEHOLDER_LOOKUP.md)", gate=True)
            if res.get("searchable_placeholders") and not res.get("answered_kinds"):
                add(f"{rid}: {res['searchable_placeholders']} searchable hand-off marker(s) are "
                    f"still in the delivered package and the sandbox carries no lookup verdict "
                    f"for them -- write the verified fact (or the verified negative with its "
                    f"search date) into the document, run the lookups where the network is "
                    f"reachable (`--placeholder-lookup online`), or re-run `decide "
                    f"--non-residual-gate` to record them as advisory only", gate=True)
        if kind in ("revise", "integrate") and res.get("unsourced_numbers_in_abstract_legends"):
            add(f"{rid}: {res['unsourced_numbers_in_abstract_legends']} number(s) in the "
                f"abstract/legends are not proved by any shipped data table", gate=False)
        if kind == "integrate":
            led = rec.get("diff_ledger") or {}
            for undo in (led.get("undoes") or [])[:4]:
                add(f"{rid}: an integration ledger row would UNDO a resolved finding ({undo})",
                    gate=True)
            if led.get("rows") and led.get("missing_artifact"):
                add(f"{rid}: {len(led['missing_artifact'])} integration ledger row(s) carry no "
                    f"per-difference artifact", gate=True)
        if kind == "review":
            for rel, probs in sorted((rec.get("artifact_quality") or {}).items()):
                add(f"{rid}: decision artifact {rel}: {str(probs[0])[:140]}", gate=True)
            for prob in (rec.get("discovery_contract") or []):
                add(f"{rid}: discovery round: {str(prob)[:160]}", gate=True)
        if kind == "probe":
            pr = rec.get("probe_review") or {}
            if pr.get("mismatches"):
                add(f"{rid}: {len(pr['mismatches'])} probe verifier(s) whose re-run did not "
                    f"reproduce the declared value "
                    f"({', '.join(str(x) for x in pr['mismatches'][:4])}): a computation the "
                    f"probe cannot reproduce is a correctness blocker", gate=True)
            if pr.get("findings"):
                add(f"{rid}: {len(pr['findings'])} independent probe finding(s) "
                    f"({', '.join(str(x) for x in pr['findings'][:6])}) -- filed as X-9xx rows "
                    f"for the round's revision arms", gate=False)
    return {"items": items, "gating": gating, "advisory": advisory,
            "count": len(items), "gating_count": len(gating), "advisory_count": len(advisory)}


def build_decision_report(ctx: Ctx, rounds_data: list, integrity: dict,
                          problems: list, final: dict, win_lengths=None,
                          final_clean=None, revision_token=None, win_format=None,
                          format_gate: bool = False, format_problems=None,
                          certification: dict = None) -> str:
    # Values the per-round loop below binds (`r`, `agg`, `stored`, `plan`).
    # Defaulted here so a caller with NO completed round -- an observer, a test,
    # a report rebuilt by hand -- gets a readable report instead of the
    # UnboundLocalError the 2026-10-15 hand-off work hit (2026-10-15).
    r, agg, stored, plan = 0, {}, {}, {}
    L = []
    L.append("# Round Pipeline — Decision Report")
    L.append("")
    L.append(f"Generated: {utcnow()}  |  pipeline root: `{ctx.root}`  |  orchestrator v{VERSION}")
    L.append(f"Config: rounds={ctx.rounds_count()} judges/version={judges_config_note(ctx)} "
             f"integrators/round={integrators_config_note(ctx)} "
             f"| source: `{ctx.cfg.get('source')}`")
    for line in venue_status_lines(ctx):
        L.append(f"- {line}")
    if certification:
        _cert = certification
        _verdict = certification_label(_cert)
        _why = (_cert.get("blockers") or _cert.get("notes")
                or ["every gate passed"])
        L.append("")
        L.append(f"**Certification: {_verdict}.** " + "; ".join(str(x) for x in _why))
        _cv = _cert.get("clean_version") or {}
        if _cv.get("published"):
            L.append(f"- final_clean_version/: published by this decision "
                     f"({_cv.get('status') or _verdict.lower()}); status in "
                     f"`{_cv.get('readme') or FINAL_CLEAN_README_NAME}`")
        else:
            L.append(f"- final_clean_version/: NOT (re)built by this decision"
                     + (f" -- {_cv['skipped_reason']}" if _cv.get("skipped_reason") else "")
                     + f" (status still recorded in `{FINAL_CLEAN_README_NAME}`)")
    L.append("")
    L.append("## 0. Integrity")
    L.append("")
    L.append(f"- pristine original: {'ok' if integrity['pristine_ok'] else 'CHANGED'} "
             f"({integrity['pristine_detail']})")
    L.append(f"- pinned champion chain: {'ok' if not integrity['pinned_errors'] else 'CHANGED'} "
             f"({len(ctx.state.get('pinned') or [])} pinned version(s))")
    for e in integrity["pinned_errors"]:
        L.append(f"  - {e}")
    if integrity.get("evidence_not_verifiable"):
        L.append(f"- evidence NOT verifiable for {len(integrity['evidence_not_verifiable'])} "
                 f"run(s): their sandboxes are missing (pruned or removed by hand), so the "
                 f"decision rests on the recorded manifests alone")
        for e in integrity["evidence_not_verifiable"][:8]:
            L.append(f"  - {e}")
    if integrity.get("recovery"):
        L.append(f"- orchestrator RECOVERY: {len(integrity['recovery'])} run(s) dropped base "
                 f"file(s) that were restored mechanically (advisory; the judged package is "
                 f"complete, and this never changes a score)")
        for r in integrity["recovery"][:8]:
            L.append(f"  - {r['run']} ({r['version']}): {r['count']} restored file(s)"
                     + (f", e.g. {', '.join(r['files'][:3])}" if r.get("files") else ""))
    if integrity.get("visual_not_verified"):
        L.append(f"- visual verification INCOMPLETE in {len(integrity['visual_not_verified'])} "
                 f"run(s) (a renderer was unavailable or the agent recorded 'not visually "
                 f"verified'); the author must complete those pages: "
                 + ", ".join(integrity["visual_not_verified"][:8]))
    if problems:
        L.append("")
        L.append("**Problems found while recomputing the decision (the stored chain is NOT "
                 "re-derived silently):**")
        L.append("")
        for p in problems:
            L.append(f"- {p}")
    L.append("")
    L.append("## 1. Final answer")
    L.append("")
    pin = final["pin"] or {}
    L.append(f"The round-{final['round']} champion is **{final['stored'].get('champion')}**, "
             f"pinned at `{final['stored'].get('pin_path')}` "
             f"(digest `{str(pin.get('digest'))[:16]}…`).")
    L.append("")
    L.append(f"The same content is published for review at "
             f"`{final['stored'].get('winner_dir') or '(missing)'}/` directly under the pipeline "
             f"root; every round's winner lives in its own `round<R>_winner/` directory, and each "
             f"one is digest-verified against its pin by `run`/`decide`.")
    L.append("")
    if final_clean and final_clean.get("path"):
        _pin_digest = final_clean.get("pin_digest")
        _identity = (f"the copy is byte-identical to the pin `{str(_pin_digest)[:16]}…`"
                     if _pin_digest else
                     "the pin record carries no digest, so byte-identity to a pin was NOT "
                     "verified")
        L.append(f"**Clean version for a new round:** `{final_clean['path']}` "
                 f"({final_clean['files']} file(s), digest `{str(final_clean['digest'])[:16]}…`; "
                 f"{_identity}). "
                 f"It is the champion corpus with no scratch, no auxiliaries and no self-written "
                 f"reports, so it can seed the next pipeline run directly. Its certification "
                 f"status and provenance are in the SIBLING `{FINAL_CLEAN_README_NAME}` "
                 f"(the directory itself stays byte-clean manuscript content).")
        _zip = final_clean.get("zip") or {}
        if _zip.get("path"):
            L.append(f"It is also compressed, the directory KEPT, as `{_zip['path']}` "
                     f"({_zip.get('files', '?')} file(s), {_zip.get('bytes', '?')} bytes) "
                     f"for handing the package over.")
        L.append("")
        L.append(f"```\npython paper_pipeline.py setup --source {final_clean['path']} "
                 f"--root <new-root>\n```")
    elif final_clean and final_clean.get("skipped"):
        L.append(f"**Clean version for a new round: NOT (re)built** -- "
                 f"{final_clean['skipped']}. (The directory is rebuilt on every `decide` when "
                 f"the champion corpus is available; the status file "
                 f"`{FINAL_CLEAN_README_NAME}` records the certification verdict either way.)")
    if final_clean:
        _oi = final_clean.get("open_items") or {}
        _rows = list(_oi.get("items") or [])
        _drops = list(_oi.get("discarded") or [])
        if _rows or _drops or (_oi.get("manual_steps") and _oi.get("manual_steps_items")):
            L.append("")
            L.append(f"**Open item(s) the champion's own revision handed to the author "
                     f"({len(_rows)} unresolved"
                     + (f", {len(_drops)} discarded without the auditor's support"
                        if _drops else "")
                     + ").** Certification is about the PROCESS: these items do not block it, "
                       "and the package is not submission-ready until they are resolved. They "
                       "come from the champion's producing run "
                       f"`{_oi.get('run')}` ({_oi.get('kind') or 'stage'})"
                     + (", whose ledger counts by status are "
                        + ", ".join(f"{k}={v}" for k, v in
                                    sorted((_oi.get('statuses') or {}).items()))
                        if _oi.get("statuses") else "")
                     + f"; the full list is the sibling `{FINAL_CLEAN_STEPS_NAME}` and "
                       f"`readiness.open_items` in `reports/decision.json`:")
            for it in _rows[:16]:
                L.append(f"  - `{it.get('id')}` [{it.get('status')}] "
                         f"{str(it.get('check') or '')} {str(it.get('severity') or '')}".rstrip()
                         + (f" -- {str(it.get('location'))[:150]}" if it.get("location") else ""))
            if len(_rows) > 16:
                L.append(f"  - … and {len(_rows) - 16} more")
            for it in _drops[:6]:
                L.append(f"  - `{it.get('id')}` [DISCARDED by the reviser; the auditor's "
                         f"verdict was `{it.get('audit_verdict') or 'none'}`] "
                         + (f"-- {str(it.get('location'))[:150]}" if it.get("location") else ""))
    L.append("")
    if revision_token and revision_token.get("token"):
        L.append(f"**Revision token of the final winner (content-hash version ID):** "
                 f"`{revision_token['token']}` over {revision_token['files']} payload file(s) "
                 f"(tokens seen in filenames: {', '.join(revision_token['tokens_seen']) or 'none'}"
                 f"; {'consistent' if revision_token.get('consistent') else 'legacy/not applied'})"
                 f". Applying the token never changes it: the computation normalizes existing "
                 f"version-token references before hashing.")
        L.append("")
    cap_note = (final["pin"] or {}).get("captions")
    cap_ok, cap_text = caption_gate(cap_note)
    L.append(f"Figure-caption check (M18, code-side proxy over the pinned winner): {cap_text}")
    if not cap_ok:
        L.append("")
        L.append(f"**NOTE (advisory only): the final winner still carries a caption over the "
                 f"suggested {caption_limit_of(ctx)}-word length.** The caption suggestion is a "
                 "reporting rule of this pipeline, never a gate: the winner keeps its place in "
                 "the ranking, and no version is made ineligible by caption length. Compress it "
                 "by hand (redundancy only, never by deleting content) if the author agrees, and "
                 "check the 'figure-like line(s) NOT recognised' notes above -- the code-side "
                 "scan may also have missed or mis-measured the caption the agents' M18 sweep "
                 "knows about.")
    L.append("")
    L.append("**Abstract/main-text length check (M19, code-side proxy over the pinned winner; "
             f"advisory).** {length_note(win_lengths)} "
             f"{relaxation_note(venue_profile_of(ctx, required=False))}. "
             "Words are counted as "
             "maximal runs of non-space characters with a newline treated as space, and the "
             "agents' M19 sweep (not this proxy) is authoritative. An over-cap section is a "
             "formatting-tier item: the winner keeps its place in the ranking, is never made "
             "ineligible, and compression -- when possible -- may only remove redundancy, never "
             "scientific content.")
    L.append("")
    L.append("**OOXML style/formatting check (code-side proxy over the pinned winner; "
             f"advisory unless `decide --format-gate`).** {format_note(win_format)} "
             "The scan reads the WordprocessingML the text-only corpus drops: break-only "
             "paragraphs (the blank-page cause), header-on-title-page, tracked changes and "
             "proofing marks, hand-formatted legend spacing, heading style drift, unintended "
             "italics (Zotero bibliography/citation fields are reported as field-protected: fix "
             "the CSL style or unlink the fields for the submission copy), mixed URL/email "
             "treatment, mixed quotation marks and em-dash density. Mechanical findings can be "
             "repaired with `python paper_docx_format.py fix FILE.docx --out FILE.fixed.docx` "
             "(byte-level edits, text identity verified, `docx validate` when available); the "
             "remaining rows are editorial/policy items for the author.")
    _fmt_problems = list(format_problems or [])
    if _fmt_problems:
        L.append("")
        L.append("High-severity formatting problems"
                 + (" (gate ENABLED: the decision is not certified)" if format_gate else "")
                 + ":")
        for p in _fmt_problems[:12]:
            L.append(f"- {p}")
    L.append("")
    _stop = ctx.state.get("stopped_early") or {}
    if _stop and rounds_data and (
            int(_stop.get("after_round") or -1) != int(rounds_data[-1]["round"])
            or int(_stop.get("planned_rounds") or -1) != int(ctx.rounds_count())):
        # A stop record from an earlier invocation is stale once a later round
        # was decided; it must not describe this run's round model.
        _stop = {}
    if _stop:
        L.append(f"The round model ran {_stop.get('after_round')} of "
                 f"{_stop.get('planned_rounds')} planned rounds and then STOPPED EARLY under "
                 f"`{_stop.get('rule')}`: {_stop.get('reason')} "
                 f"({_stop.get('no_progress_streak')} consecutive no-progress round(s); the "
                 f"stopping rule is pre-registered and the last completed round is the answer).")
    else:
        L.append("The round model is fixed-length: exactly "
                 f"{ctx.rounds_count()} rounds ran (or are running). There is no early stop, no "
                 "convergence test, and no skip-ahead on a non-improving round"
                 + ("; `setup --stop-after-no-progress K` turns the pre-registered adaptive stop "
                    "on." if not int((ctx.cfg or {}).get('stop_after_no_progress') or 0) else "."))
    L.append("")

    L.append("## 2. Per-round results")
    L.append("")
    for rd in rounds_data:
        r = rd["round"]
        agg, sel, stored = rd["agg"], rd["sel"], rd["stored"]
        L.append(f"### Round {r}")
        L.append("")
        L.append(f"- field: {agg['field_size']} member(s) — "
                 f"`{', '.join(agg['field'])}`")
        if (agg.get("diagnostics") or {}).get("auto_promoted"):
            L.append("- judge panel: **SKIPPED** — the round was auto-promoted by "
                     "`--champion-select`; no directed scores exist and no ranking key was "
                     "consulted. The result is PROVISIONAL, never a certified panel result.")
        else:
            L.append(f"- score set: {agg['scores_per_version']} directed scores per version "
                     f"= 2 * {round_judges(ctx, r)} * ({agg['field_size']} - 1)")
            L.append(f"- judges per version: {round_judges(ctx, r)} "
                     f"({agg['diagnostics']['sheets_used']}/{agg['diagnostics']['sheets_expected']} "
                     f"sheets usable)")
        L.append(f"- champion: **{stored.get('champion')}**"
                 + (f" (pin `{stored.get('pin_path')}`, digest "
                    f"`{str(stored.get('pin_digest'))[:16]}…`)" if stored.get("pin_digest") else ""))
        if stored.get("champion") == A1_ID and stored.get("champion_rep") \
                and stored.get("champion_rep") != A1_ID:
            L.append(f"  - the champion is the round's own base: no fresh arm measurably "
                     f"outranked it (it was scored here as the content-identical member "
                     f"`{stored.get('champion_rep')}`), so the round kept the incumbent instead "
                     f"of stepping backwards. Nothing was lost: the base is the input this round "
                     f"started from.")
        L.append(f"- winner directory: `{stored.get('winner_dir') or '(not published)'}/` "
                 f"(same content as the pin)")
        if stored.get("field_dropped"):
            L.append("- field deduplication (by content digest, first occurrence wins):")
            for d in stored["field_dropped"]:
                L.append(f"  - `{d['id']}` dropped — {d['reason']}")
        if stored.get("panel_gaps"):
            L.append("- PANEL GAPS recorded for this round (the round was decided only after the "
                     "panel was restored; if the gaps are still listed in the run audit, re-run "
                     "the failing judge session):")
            for g in stored["panel_gaps"].get("gaps") or []:
                L.append(f"  - `{g}` was short of directed scores")
        L.append("")
        rows = []
        champ_rep = stored.get("champion_rep") or stored.get("champion")
        tiebreak_inputs = stored.get("tiebreak_inputs") or {}
        base_reps = {str(t.get("rep") or t.get("id"))
                     for t in ((stored.get("selection") or {}).get("ranking") or [])
                     if t.get("is_base")}
        for vid in agg["field"]:
            s = agg["stats"][vid]
            ti = tiebreak_inputs.get(vid) or {}
            writing = ti.get("writing_remaining")
            if _missing_count(writing):
                if vid == A1_ID or vid in base_reps:
                    writing = round_writing_remaining(ctx, r)
                elif vid == ORIGINAL_ID:
                    writing = original_writing_remaining(ctx, r, agg)
                elif is_fresh_vid(vid):
                    writing = candidate_tiebreak_inputs(ctx, r, vid)[1]
            rows.append([vid, f"{s['n']}/{s['expected_n']}",
                         f"{s['median']:g}" if s["median"] is not None else "-",
                         f"{s['mean']:.2f}" if s.get("mean") is not None else "-",
                         f"{s['iqr']:g}" if s["iqr"] is not None else "-",
                         f"{s['vs_original']:g}" if s["vs_original"] is not None else "-",
                         f"{s['vs_base']:g}" if s.get("vs_base") is not None else "-",
                         _count_cell(ti.get("critical_remaining")),
                         _count_cell(writing),
                         {True: "yes", False: "NO", None: "-"}[s.get("anti_regression_ok")],
                         f"{s['judges_seen']}/{s['judges_expected']}",
                         f"{s.get('author_placeholders') or 0}",
                         "CHAMPION" if vid == champ_rep else ""])
        L.append(_tbl(rows, ["member", "scores", "median", "mean", "IQR", "vs_original",
                             "vs_base", "critical", "writing", "eligible", "judges",
                             "hand-off", "note"]))
        # The ISSUE CENSUS: how many issues of each tier and severity the
        # panel attributed to each version, counted from the judges' OWN ledger
        # rows. It is BOTH the number a chain of runs compares across rounds
        # ("fewer correctness/major issues than last round") and the selection's
        # LEADING ranking input (the adaptive severity_tier_category prefix: the walk
        # accumulates the cells until the cleanest ranked version reaches the
        # configured defect floor, or every cell is used).
        census = agg.get("issue_census") or {}
        if census:
            L.append("")
            L.append("**Issue census (also the selection's leading ranking signal, the defect "
                     "prefix):** the judges' own "
                     "ledger rows, counted per version, tier and severity. `own` = the "
                     "version's own sweep sessions (`introduced` rows), `peer` = the other "
                     "versions' comparisons against it (`resolved` rows); rows are "
                     "deduplicated per session, so one defect repeated across a session's "
                     "opponent comparisons counts once. There is NO cross-session matching "
                     "by default (`dedup_mode` off): merging rows across judge sheets by "
                     "their evidence text alone is a noise source of its own. The OPT-IN "
                     "`dedup_mode` location merges across sheets only on the structured key "
                     "(same defect class, same exact line number, both excerpts >= 7 words "
                     "with token-set Jaccard >= 0.8) and audits every merge in "
                     f"`reports/round{r}_dedup_audit.json`. `per session` divides by the sessions that COULD mention the "
                     "version (field-size-stable); `own rate`/`peer rate` divide the "
                     "counts by the OPPORTUNITIES (own judge sessions vs "
                     "opponent slots). Tier columns and severity columns overlap (a tier "
                     "total already contains its severities), and the census is not a score "
                     "by itself: it answers \"what is left and where\", and the selection "
                     "reads it through two sibling matrices: "
                     f"`reports/round{r}_issue_matrix.csv` (rows = versions, columns = the "
                     "canonical severity_tier_category cells fatal_correctness_peer, "
                     "fatal_correctness_own, ..., minor_formatting_own -- the SAME four severity "
                     "rungs the long-form census below reports; "
                     "values = the reported counts) and "
                     f"`reports/round{r}_issue_cumulative.csv` (the PREFIX SUMS of the same "
                     "rows and columns). The selection accumulates the cells in that order "
                     "and stops at the first prefix where the cleanest ranked version reaches "
                     f"the configured floor (default {DEFAULT_TIEBREAK_DEFECT_FLOOR}), or when "
                     "every cell is used; the cumulative count at that prefix breaks a median "
                     f"tie. The long-form table is `reports/round{r}_issue_census.csv` (one "
                     "row per version/tier/severity) for concatenation across runs, and "
                     f"`reports/round{r}_dedup_audit.json` records every cross-sheet merge the "
                     "opt-in `dedup_mode` location made (zero merges when it is off).")
            L.append(_tbl(issue_census_table(agg), list(ISSUE_CENSUS_TABLE_HEAD)))
        # The incumbent margin is the number a human reads before trusting a
        # "progress" claim, but it is deliberately NOT a ranking key (a 2*judges
        # pair is one outlier session away from flipping): print the pair's own
        # sign counts next to it so the margin cannot be mistaken for a decision.
        margin_lines = []
        for vid, s in agg["stats"].items():
            vals = list(s.get("vs_base_vals") or [])
            if not vals:
                continue
            wins = sum(1 for x in vals if x > 0)
            losses = sum(1 for x in vals if x < 0)
            ties = len(vals) - wins - losses
            margin_lines.append(f"`{vid}`: vs_base median {s.get('vs_base')!r} over {len(vals)} "
                                f"directed score(s) — {wins} win / {losses} loss / {ties} tie "
                                f"(REPORTED, never a ranking input)")
        if margin_lines:
            L.append("")
            L.append("**Incumbent margin (reported only — the ranking key does not use it):**")
            L.extend(f"- {ln}" for ln in margin_lines)
            L.append("")
            L.append("Per-round champion statistics come from DIFFERENT panels and different "
                     "fields: a champion's score in one round is not comparable with the same "
                     "content's score in another (the champion of round r is selected as the "
                     "argmax of that round's noisy panel, so its score is inflated by selection). "
                     "Read the vs_base margin of the FINAL round for the only paired statement "
                     "this report supports.")
        cap_lines = [f"`{vid}`: {s.get('caption_note')}"
                     for vid, s in agg["stats"].items() if s.get("caption_note")]
        if cap_lines:
            L.append("")
            L.append("Caption state (advisory only — never a gate, never a ranking input):")
            L.append("")
            for line in cap_lines:
                L.append(f"- {line}")
        ph_lines = [f"`{vid}`: {s['author_placeholders']} hand-off placeholder(s) awaiting the "
                    f"author in {', '.join(s.get('placeholder_documents') or []) or '(see corpus)'}"
                    for vid, s in agg["stats"].items() if s.get("author_placeholders")]
        if ph_lines:
            L.append("")
            L.append("Hand-off placeholders (M18's sibling; reported, never scored or ranked):")
            L.append("")
            for line in ph_lines:
                L.append(f"- {line}")
        L.append("")
        L.append("Selection trace:")
        L.append("")
        for line in sel.get("trace") or []:
            L.append(f"- {line}")
        L.append("")
        diags = agg["diagnostics"]
        pq = diags.get("panel_quality") or {}
        if pq:
            L.append("Panel quality (reported only; never used for eligibility):")
            L.append("")
            L.append(f"- {pq.get('scores')} directed scores · zero share "
                     f"{pq.get('zero_share')} · mean |score| {pq.get('mean_abs')} · largest "
                     f"within-direction judge spread {pq.get('within_direction_range_max')}")
            if pq.get("score_histogram"):
                L.append("- score histogram: "
                         + ", ".join(f"{k}: {v}" for k, v in pq["score_histogram"].items())
                         + f" (largest |score| used: {pq.get('max_abs_score')})")
            if pq.get("calibrated_sheets") or pq.get("uncalibrated_sheets"):
                L.append(f"- graded basis: {pq.get('calibrated_sheets')} calibrated sheet(s), "
                         f"{pq.get('uncalibrated_sheets')} legacy/uncalibrated sheet(s)"
                         + ("; basis tiers used: "
                            + ", ".join(f"`{k}` {v}" for k, v in
                                        sorted(pq["basis_counts"].items()))
                            if pq.get("basis_counts") else ""))
            if pq.get("ledger_sign_conflicts"):
                L.append("- LEDGER CONTRADICTIONS (an integer whose own ledger lists no item on "
                         "its side -- reported for the operator; contract v2 rejects these "
                         "outright): " + "; ".join(pq["ledger_sign_conflicts"][:8]))
            if pq.get("judge_means"):
                L.append("- per-judge mean score: "
                         + ", ".join(f"`{k}` {v}" for k, v in sorted(pq["judge_means"].items())))
            if pq.get("direction_flips"):
                L.append("- DIRECTION FLIPS (the two sides' judges disagree about who is better): "
                         + "; ".join(pq["direction_flips"]))
            L.append("- interpretation: the judge prompt expects 0 for near-identical packages. A "
                     "low zero share on a field whose members share most of their content means "
                     "the panel is scoring small differences (or artifacts) rather than "
                     "content-level advantages; read raw_scores.csv before trusting a close "
                     "ranking.")
            L.append("")
        if diags.get("incomplete_sheets"):
            L.append("Panel gaps:")
            L.append("")
            for d in diags["incomplete_sheets"][:20]:
                L.append(f"- {d}")
            L.append("")
        if diags.get("superseded_sheets"):
            L.append("Superseded judge sheets (the newest sheet for that target + judge index "
                     "was used; the panel is not double-counted):")
            L.append("")
            for d in diags["superseded_sheets"][:10]:
                L.append(f"- {d}")
            L.append("")
        if diags.get("out_of_range_sheets"):
            L.append("Ignored judge sheets (judge index outside the configured range -- a stale "
                     "`--judges` value cannot poison a panel):")
            L.append("")
            for d in diags["out_of_range_sheets"][:10]:
                L.append(f"- {d}")
            L.append("")
        if diags.get("unresolved"):
            L.append("Unresolvable comparisons (skipped, per D1):")
            L.append("")
            for d in diags["unresolved"][:20]:
                L.append(f"- {d}")
            L.append("")

    L.append("## 3. Method (deterministic; no LLM arithmetic)")
    L.append("")
    if rounds_data:
        r = rounds_data[-1].get("round", 0)
        agg = rounds_data[-1].get("agg") or {}
    L.append("**Directed scores.** Each judge session scores the target against every opponent in "
             "the target's own direction only, one integer in -4..+4. V-vs-W comes from V's "
             "judges; W-vs-V comes from W's judges and is negated into V's frame, so a version's "
             f"score list is `{round_judges(ctx, r)}*(|field|-1)` own scores plus "
             f"`(|field|-1)*{round_judges(ctx, r)}` negated received scores = "
             f"`2*judges*(|field|-1)` values (here: {agg.get('scores_per_version')} at "
             f"judges={round_judges(ctx, r)}, |field|={agg.get('field_size')}). A version is only "
             f"ELIGIBLE to win when its own panel is complete (all "
             f"{agg.get('scores_per_version')} scores collected); a FRESH arm additionally needs both "
             f"directions against the original (the anti-regression gate below), while the round's "
             f"base row needs the complete panel only. A partial panel is reported as a panel gap "
             f"and can never decide a round.")
    L.append("")
    L.append(f"**Graded basis (judge contract v{JUDGE_CONTRACT_VERSION}).** The integer is not "
             f"free-floating: every comparison carries the tier it is about "
             f"({' > '.join(BASIS_TIERS)}) plus a ledger of the concrete items on each side "
             f"(tier, severity, short evidence), and the orchestrator checks the derivation: the "
             f"tiers are compared LEXICOGRAPHICALLY and the FIRST tier whose net is not zero "
             f"decides the comparison, so no lower-priority gain can offset a higher-priority "
             f"loss. Rows weigh minor 1 / major 2 / critical 3 / fatal 4 (resolved add, introduced "
             f"subtract), the deciding tier's net is capped at +-4 and its magnitude is bounded by "
             f"its own rows (MINOR-only <= 2, a MAJOR row <= 3, a CRITICAL/FATAL row <= 4), and a "
             f"non-zero score needs an item on its own side in the deciding tier -- |score| >= 3 "
             f"needs a MAJOR/CRITICAL/FATAL row there and |score| = 4 a CRITICAL/FATAL one. A "
             f"sheet that contradicts its own ledger is a failed run, not a data point. The SCORE "
             f"range is deliberately NOT widened: the production panel used -3..+3 and never +-4, "
             f"so extra score rungs would add unused resolution instead of meaning; the ledger is "
             f"what anchors the existing rungs, and a weighted aspect average is deliberately "
             f"absent (weights are arbitrary and the tier order IS the aggregation: "
             f"correctness > preservation > completeness > consistency > writing > formatting).")
    L.append("")
    L.append("**Ranking key.** The selection key is `cumulative-defect-prefix -> median -> "
             "mean -> IQR -> digest`: the round's OWN ISSUE CENSUS leads -- how many defects "
             "the panel attributed to the version is the most direct improvement signal, while "
             "the flat median is coarse on a -4..+4 integer scale. The prefix is read from the "
             "canonical severity_tier_category order "
             f"(fatal_correctness_peer, fatal_correctness_own, ..., minor_formatting_own -- the "
             "SAME four severity rungs the census reports): the cells are accumulated for "
             "every ranked version and the walk STOPS at the first "
             f"prefix where the version with the FEWEST defects reaches the configured floor "
             f"(default {DEFAULT_TIEBREAK_DEFECT_FLOOR} defects, "
             f"`setup --tiebreak-defect-floor N` / `set-tiebreak-defect-floor N`), or when every "
             "cell is included; the cumulative count at that prefix LEADS the ranking (fewer is "
             "better), and `median(flat score list)` (with the arithmetic mean and the IQR over "
             "the same flat list) is the first tie-break below it. A per-cell count is never a "
             "rung of its own: with small counts its fluctuation is larger than the signal, "
             "which is why the prefix keeps accumulating until the cleanest candidate carries "
             "enough evidence. Counts are the mentions each judge sheet filed (collapsed only "
             "per session+version; no cross-session matching). The median and the mean are the "
             "panel statistics below the prefix; the IQR and the content digest are the "
             "deterministic fallbacks. The incumbent-retention rule still fires on an exact "
             "(median, mean, IQR) tie and KEEPS the base even when a challenger has a lower "
             "defect prefix (a better defect count separates challengers, it does not retire an "
             "incumbent the panel cannot distinguish from them). The self-reported "
             "`critical_remaining`/`writing_remaining` values are reported and cross-checked but "
             "are NOT ranking inputs.")
    L.append("")
    L.append(f"**Anti-regression gate.** `vs_original` is the median of the directed scores "
             f"involving the pinned original (own + negated received). A version is ineligible to "
             f"win when `vs_original < {VS_ORIGINAL_TOLERANCE:g}` (tolerance 0; see the code "
             f"comment for the stricter `> 0` and looser `>= -0.5` alternatives). The round's "
             f"own base A1_r is the incumbent status quo and is not subject to this gate: the "
             f"no-progress fallback crowns it when nothing else qualifies, so a gate on it would "
             f"contradict the fallback.")
    L.append("")
    plan = stored.get("plan") or {}
    pool = list(plan.get("pool") or [])
    int_recorded = plan.get("integrated") is not None
    ran_int = [v for v in (plan.get("integrated") or []) if is_integrated_vid(v)]
    _mask_note = (f" 0x{int(plan['integrators']):X}" if is_int(plan.get("integrators")) else "")
    if int_recorded and len(ran_int) < len(pool):
        _int_text = (f", plus only {len(ran_int)} of the {len(pool)} possible integration arm(s) "
                     f"(K = 1 + M + N = {len(pool)}); this round's integrator mask{_mask_note} "
                     f"left {len(pool) - len(ran_int)} arm(s) out -- they were not run, not "
                     f"judged and could not be crowned")
    else:
        _int_text = f", plus one integration run per pool member (K = 1 + M + N = {len(pool)})"
    L.append(f"**Candidate pool.** This round ran with M={plan.get('rewrites', '?')} rewritten "
             f"candidate(s) and N={plan.get('revises', '?')} reviewed-and-then-revised "
             f"candidate(s){_int_text}. Every one of them is a candidate "
             f"on the same terms: none is excluded from scoring, selection or replacement, and "
             f"each wins whenever the published ranking key puts it first.")
    if pool:
        for k, src in enumerate(pool, 1):
            donors = ", ".join(v for v in pool if v != src)
            mark = ("  (NOT RUN: the integrator mask left this arm out)"
                    if int_recorded and integrate_vid(k) not in ran_int else "")
            L.append(f"  - `{integrate_vid(k)}` = integration of `{src}` with the donors "
                     f"`({donors})`{mark}")
    L.append("")
    L.append("**Champion.** The ranked rows are the round's fresh arms (every rewrite, every "
             "reviewed-and-revised candidate and every integrated candidate) plus the round's own "
             "base A1_r (scored through the "
             "content-identical field member that the judges saw). "
             "Including the base is what keeps the rounds monotone: a version the panel "
             "ranks below the version the round started from can never be crowned, and when the "
             "base wins the round honestly reports no demonstrable, non-regressing progress "
             "(exactly as the no-eligible-candidate fallback always did). A fresh arm must also "
             "clear the anti-regression gate; the base row needs only a complete panel. The "
             "winner is the first under: the cumulative DEFECT PREFIX (the round's issue census "
             "walked over the canonical severity_tier_category cells -- fatal, critical, major, "
             "minor, tier priority order, peer before own -- until the cleanest version reaches "
             "the configured floor or every cell is used; fewer defects first), then `-median`, "
             "`-mean`, `IQR`, the CONTENT DIGEST (provenance-free: a "
             "perfect tie must never be decided by the arm's name) and only after that the id. "
             "An exact (median, mean, IQR) tie still keeps the incumbent base -- that rule "
             "overrides the prefix. `critical_remaining`/`writing_remaining` are reported and "
             "cross-checked (self-reported marker values, +inf when absent) but are NOT ranking "
             "keys. "
             "`vs_base` -- the panel's own head-to-head median against the round's incumbent -- is "
             "REPORTED (and is what the incumbent rule is about) but is deliberately not a second "
             "ranking key: it is one of the pairs already inside the flat list. An exact tie on "
             "`median`, `mean` and `IQR` keeps the incumbent base: a challenger must be "
             "measurably better, not merely different. "
             "`manual_steps` (counted from the producing run's own package: "
             "`revised/MANUAL_STEPS.md`, `rewritten/MANUAL_STEPS.md` or "
             "`integrated/MANUAL_STEPS.md`) is REPORTED but deliberately "
             "not ranked on: it counts the work the pipeline hands to the author, so ranking on "
             "it would reward under-reporting.")
    L.append("")
    L.append("**Pinning.** The champion is copied to `pinned/<r>_<champion_id>/documents/` and "
             "registered with its SHA-256 corpus digest. It joins the field of every later round, "
             "deduplicated by content digest (so a champion identical to the original, or to an "
             "existing pin, appears exactly once — the pinned set can legitimately be smaller "
             "than the number of rounds).")
    L.append("")
    L.append("**Winner publication.** Each round's champion is also published, atomically, as "
             "`round<R>_winner/` directly under the pipeline root (documents at its top level) so "
             "the operator can open the round winner without descending into `pinned/`; a "
             "displaced copy is archived under `_superseded/` rather than deleted.")
    L.append("")
    L.append(f"**Caption check (advisory, not a gate).** In addition to the agents' M18 sweep, "
             f"the orchestrator scans every candidate corpus itself (Word .docx via OOXML, LaTeX "
             f"\\caption, and Markdown/plain text) and reports any extractable caption over the "
             f"suggested {caption_limit_of(ctx)} words. It NEVER makes a version ineligible, "
             f"never reorders a ranking, and never fails a decision on caption length -- the "
             f"caption length is a pipeline suggestion, handled exactly like the master prompt's "
             f"cover-letter word rule. Files whose caption text cannot be parsed (legacy .doc, "
             f"PDF, slides) are reported as 'not verified' and rely on the agents' M18 rows; the "
             f"scan is a proxy (whitespace word counts after stripping LaTeX commands), never a "
             f"substitute for reading the caption: caption-looking lines the pattern does not "
             f"recognise are listed as 'suspected'. `setup --caption-limit 0` (the default) "
             f"switches the suggestion off entirely.")
    L.append("")
    L.append("**Interpretation caveat.** The directed scores of one version come from "
             "`judges` sessions, each of which produced one score per opponent: the values inside "
             "a session are correlated (one judge, one read), so the reported IQR is the spread "
             "across judgements, not an independent-sampling error bar. The median of the flat "
             "list remains the pre-registered ranking statistic; the arithmetic mean of the same "
             "list is used only to break a median tie.")
    L.append("")
    policy = ctx.state.get("run_policy") or {}
    if policy:
        L.append("**Retry policy (protects the panel).** A failed agent run is retried "
                 f"{policy.get('retries')} time(s) (up to {policy.get('attempts_per_run')} attempts) "
                 f"with exponential backoff starting at {policy.get('retry_backoff')}s and capped "
                 f"at {policy.get('retry_backoff_max')}s. A round whose judge panel is still "
                 f"incomplete afterwards -- any field member short of its directed scores -- is "
                 f"NEVER decided: it stays pending with `reports/round<r>_panel_gaps.json` until "
                 f"the failing judge session is repaired, so a lost session can never shrink the "
                 f"panel that ranks the versions.")
        L.append("")
    _cap = caption_limit_of(ctx)
    _cap_text = (f"is set to {_cap} words for this run (reported under check id M18)"
                 if _cap else "is switched off for this run (no caption-length suggestion; "
                              "check id M18 is not used, so the skill's discovery proposals keep "
                              "their usual M18+ numbering)")
    L.append(f"**Figure captions and hand-off placeholders.** The pipeline's caption suggestion "
             f"{_cap_text}. It is not part of the master prompt or of either skill, it is "
             f"advisory in every way (reported, never a gate, never a ranking input), and a "
             f"caption is only ever compressed by removing redundancy — never by deleting "
             f"scientific content. Agents that cannot supply missing content without inventing it "
             f"mark the gap with the pipeline's hand-off token \"{PLACEHOLDER_TOKEN}: ...]\": those "
             f"markers are manual items for the author, counted in this report and never scored, "
             f"ranked or treated as defects (a marker does not make a version worse than an "
             f"identical version without one).")
    L.append("")
    L.append("**Review provenance (carry-over).** Each round's review must satisfy the contract "
             "check (submission_dir resolves to base/, every check id M1-M17 and J1-J4 carries a "
             "real coverage disposition, review/artifacts/ exists, finding ids are unique), and "
             "its deliverables are archived under `reports/round<r>_review/`. From round 2 on, "
             "the reviewer receives the previous round's finding list as read-only `prior_round/` "
             "and must reconcile every prior id (carried forward with a new id and a "
             "\"carried over from <prior-id>\" note, or recorded as not reproducible): a finding "
             "that a later pass misses now FAILS the review instead of quietly disappearing. "
             "Residual, stated honestly: a single LLM review pass is still a sample of the defect "
             "space, so the pipeline enforces reconciliation and coverage, not completeness.")
    L.append("")
    L.append(f"**Visual verification.** The prompts require a render-then-look pass for Word "
             f"documents (convert .docx/.doc to PDF with a layout-faithful converter, render the "
             f"pages with pdftoppm/Ghostscript, inspect the images) and a record of what was "
             f"looked at: `review/artifacts/VIS_visual.md`, `judge_review/artifacts/VIS_visual.md`, "
             f"or `revised/VISUAL_CHECK.md`. The orchestrator requires that record whenever Word "
             f"documents are present and reports when the record says pages were NOT visually "
             f"verified. Renderers detected on this machine at decision time: "
             f"{visual_tools_summary()}.")
    L.append("")
    L.append("## 4. Run audit")
    L.append("")
    rows = [[r["id"], r["kind"], r["round"], r["status"], r.get("attempts", 0),
             fmt_dur(r.get("last_duration")),
             "ok" if (r.get("postcheck") or {}).get("ok") else "ERR",
             (r.get("last_error") or "; ".join((r.get("postcheck") or {}).get("warnings", [])))[:60]]
            for r in ctx.runs()]
    L.append(_tbl(rows, ["run", "kind", "round", "status", "att", "dur", "post", "note"]))
    L.append("")
    history = attempt_history_lines(ctx, indent="", limit=10)
    if history:
        L.append(f"**Failed attempts ({len(history)} recorded).** Every attempt is kept: the "
                 f"run table above shows the LAST one only, so a run that failed twice would "
                 f"otherwise report a single failure. The full history is in state.json "
                 f"(`attempts_log`, one entry per attempt: errors, warnings, the decision-artifact "
                 f"quality report, the marker's own summary, timing, and where the attempt's "
                 f"artifacts and transcript were kept), and each failed attempt's sandbox is "
                 f"preserved as `runs/<run>_try<n>_failed/` (with its own "
                 f"`record.json`) until `prune` reclaims that round.")
        L.append("")
        L.extend(history)
        L.append("")
    L.append("## 5. Human gate (nothing is auto-submitted)")
    L.append("")
    rl_dir = ctx.root / REDLINE_DIRNAME
    if (rl_dir / "manifest.json").is_file():
        L.append(f"0. Tracked changes for every candidate are under `{REDLINE_DIRNAME}/` "
                 f"(`manifest.json` names the tool that produced each file); read them before "
                 f"comparing the champion against the original by eye.")
    L.append("1. Open the final package and confirm the round champion is the version you want to "
             "submit.")
    _oi = ((final_clean or {}).get("open_items") or {})
    _oi_items = list(_oi.get("items") or [])
    _oi_dropped = list(_oi.get("discarded") or [])
    L.append("2. Read the champion's hand-off list and complete every manual item (Zotero live "
             "fields, in-figure numbers, subjective scientific judgments): the copy delivered "
             f"beside the published package, `{FINAL_CLEAN_STEPS_NAME}`"
             + (f" (it holds the hand-off list plus the {len(_oi_items) or _oi.get('manual_steps_items')} "
                f"open ledger item(s) the "
                f"champion's own revision run `{_oi.get('run')}` handed over)"
                if _oi_items or _oi.get("manual_steps") else "")
             + ". The producing run's own `MANUAL_STEPS.md` lives inside "
               "`runs/<run id>/<stage dir>/`, which the delivered package does not carry: read "
               "the sibling file, never that path.")
    L.append("3. Diff the champion against `pinned/` (and against the pristine original) with your "
             "own eyes on the FIGURES, not just the text.")
    L.append("4. Re-check the round where the champion first appeared: if its margin over the "
             "runner-up is within the panel's IQR, treat the ranking as noise-level and review "
             "both packages by hand.")
    L.append("5. Confirm the journal-facing metadata (authors, affiliations, guidelines version) "
             "before submission; the pipeline never touches it.")
    L.append("")
    return "\n".join(L)


def cmd_sync_code(args) -> None:
    """Copy the maintained module bundle into a root and record it.

    `setup` freezes the driver and its sibling modules for reproducibility. When
    the maintained tree gains a rule (the 2026-10-19 layout scans), an existing
    root keeps running the old bundle until the operator deliberately replaces
    it. This command is that deliberate replacement: it copies the maintained
    `paper_pipeline.py`, `paper_docx_format.py`, `paper_redlines_adapter.py` and
    `paper_qwen_agent.py` into the root, records their new digests (so
    `refuse_foreign_pipeline` can
    tell a synced root from a drifted one) and prints what changed. It never
    touches the package, the pinned bytes, the review or any manuscript file.
    """
    root = Path(args.root).resolve()
    if not (root / "state.json").is_file():
        die(f"sync-code: {root} is not a pipeline root (no state.json)")
    _snap = frozen_snapshot_root(Path(__file__).resolve())
    if _snap:
        origin = str(_snap.get("origin_path") or "")
        hint = (f"use `python3 {shlex.quote(origin)} sync-code --root "
                f"{shlex.quote(str(root))}`"
                if origin and Path(origin).is_file()
                and not frozen_snapshot_root(origin)
                else "run `sync-code` from the maintained checkout you mean to ship")
        die("sync-code must be run from the MAINTAINED tree, not from a root's frozen "
            f"paper_pipeline.py; {hint}.")
    src = Path(__file__).resolve().parent
    if src.resolve() == root.resolve():
        die("sync-code: the maintained tree and the root are the same directory; nothing "
            "to copy.")
    ctx = Ctx(root)
    ctx.load(need_cfg=False)
    holder = _root_lock_holder(root)
    if holder:
        die(f"sync-code: {root} is locked by pid {holder[0]} ({holder[1]}); stop the live "
            f"run before replacing the code it is executing.")
    changed, unchanged = [], []
    for name in PIPELINE_MODULE_FILES:
        s, d = src / name, root / name
        if not s.is_file():
            die(f"sync-code: the maintained tree has no {name}; refusing a partial bundle")
        try:
            same = d.is_file() and sha256_file(s) == sha256_file(d)
        except OSError:
            same = False
        if same:
            unchanged.append(name)
            continue
        # Replace atomically: a `run` that starts while the bundle is being
        # synced must read a whole module, never a half-written one.
        tmp = d.with_name(d.name + ".sync-tmp")
        shutil.copy2(s, tmp)
        os.replace(tmp, d)
        changed.append(name)
    # The loaders are thin: sync the ordered implementation parts too, again
    # atomically, and record their directory digests in the manifest.
    for name in PIPELINE_ASSET_DIRS:
        s = src / name
        if not s.is_dir():
            die(f"sync-code: the maintained tree has no {name}/; refusing a partial bundle")
        try:
            same = asset_dir_digest(src, name) == asset_dir_digest(root, name)
        except OSError:
            same = False
        if same:
            unchanged.append(name + "/")
            continue
        copy_asset_dirs(src, root, names=(name,))
        changed.append(name + "/")
    # The skills pack is frozen and manifest-recorded too (F132). A trimmed
    # checkout may legitimately omit it (module_manifest records None), so a
    # missing maintained pack is not a partial bundle; a root that lacks it
    # when the maintained tree has it is brought up to date.
    for name in PIPELINE_SKILL_ASSET_DIRS:
        s = src / name
        if not s.is_dir():
            continue
        try:
            same = asset_dir_digest(src, name) == asset_dir_digest(root, name)
        except OSError:
            same = False
        if same:
            unchanged.append(name + "/")
            continue
        copy_asset_dirs(src, root, names=(name,))
        changed.append(name + "/")
    ident = pipeline_identity()
    ident["synced_at"] = utcnow()
    ctx.state["pipeline"] = ident
    ctx.save_state()
    print(f"[sync-code] root: {root}")
    print(f"[sync-code] source tree: {src}")
    print(f"[sync-code] copied: {', '.join(changed) if changed else '(nothing changed)'}")
    if unchanged:
        print(f"[sync-code] already current: {', '.join(unchanged)}")
    print(f"[sync-code] recorded module manifest: "
          f"{', '.join(f'{k}={str(v)[:12]}' for k, v in ident['modules'].items())}")
    if (root / VENUE_PROFILES_DIRNAME).is_dir():
        print(f"[sync-code] note: {root / VENUE_PROFILES_DIRNAME} is a ROOT-LOCAL copy and "
              f"was NOT replaced. If it predates a venue rule the maintained tree now "
              f"carries (e.g. figure_text/image_dpi), refresh it with "
              f"`{Path(__file__).name} set-venue <id> --profile "
              f"{Path(__file__).resolve().parent / VENUE_PROFILES_DIRNAME}/<id>.json` "
              f"or recreate the root from the maintained tree.")
    if (root / "pipeline_config.json").is_file():
        print("[sync-code] note: pipeline_config.json's recorded `format_policy` snapshot is "
              "NOT rewritten either. A rule added to the maintained formatter that depends on "
              "a new policy key (e.g. min_figure_text_pt / min_image_dpi) stays OFF in this "
              "root until the operator refreshes the venue snapshot (`set-venue`/`setup`); "
              "the formatter treats a missing key as 'not gated', never as a clean result.")
    print("[sync-code] the next `run`/`decide` in this root executes the copied bundle; "
          "earlier verdicts remain the bytes they were.")


def cmd_status(args) -> None:
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    print(f"pipeline root: {ctx.root}")
    print(f"source:        {ctx.cfg.get('source')}")
    # WHICH code this root actually runs: the snapshot frozen at setup, and
    # whether the origin tree has moved on since (see root_pipeline_staleness).
    _snap_note = pipeline_snapshot_note(ctx)
    if _snap_note:
        print(_snap_note)
    for line in venue_status_lines(ctx):
        print(line)
    _vpack = venue_pack_dir(venue_id_of(ctx), ctx.root)
    _vpack_note = (str(_vpack) if _vpack
                   else "(none -- add exemplars under venue_profiles/<venue>.manuscripts/ "
                        "and run build-venue-templates)")
    print(f"venue norm:    {_vpack_note}")
    pok, pdetail = pristine_integrity(ctx)
    if hash_checks_skipped():
        print("pristine:      not verified (--skip-hash)")
    else:
        print(f"pristine:      {'ok' if pok else 'CHANGED'} ({pdetail})")
    perrs = pinned_integrity(ctx)
    print(f"pinned:        "
          f"{'not verified (--skip-hash)' if hash_checks_skipped() else ('ok' if not perrs else 'CHANGED')} "
          f"({len(ctx.state.get('pinned') or [])} pinned version(s))")
    for e in perrs:
        print(f"  - {e}")
    print(f"hash checks:   {'SKIPPED (--skip-hash: digests recorded, verification not run)' if hash_checks_skipped() else 'verified'}")
    print(f"config:        rounds={ctx.rounds_count()} "
          f"judges/version={judges_config_note(ctx)} "
          f"integrators/round={integrators_config_note(ctx)}")
    _round_indices = [int(x) for x in ((ctx.cfg or {}).get("round_indices") or [])]
    if _round_indices:
        print(f"round indices: pipeline rounds 1..{len(_round_indices)} follow built-in "
              f"schedule round(s) {', '.join(str(i) for i in _round_indices)}")
    _jmode = journal_mode_of(ctx)
    print(f"ranking:       adaptive severity_tier_category defect prefix LEADS; floor "
          f"{tiebreak_defect_floor_of(ctx)} "
          f"(`set-tiebreak-defect-floor N`; 0 = one cell only, 999999 = every cell)")
    print(f"dedup mode:    {dedup_mode_of(ctx)} "
          f"(`set-dedup-mode off|location`; off counts every sheet's rows)")
    print(f"champion:      {champion_select_of(ctx)} "
          f"(`set-champion-select judge|revise|integrate`; the no-judge modes are "
          f"PROVISIONAL and need N=1)")
    _dj = trend_read_decision(ctx.root)
    _cert = (_dj or {}).get("certification")
    if isinstance(_cert, dict):
        _verdict = certification_label(_cert)
        print(f"decision:      {_verdict}"
              + (f" -- {'; '.join(str(b) for b in _cert.get('blockers') or [])}"
                 if _cert.get("blockers") else ""))
    if _jmode != JOURNAL_MODE_CONTINUE:
        _jinfo = JOURNAL_MODES[_jmode]
        _jfb = [str(x) for x in ((ctx.cfg or {}).get("journal_feedback") or [])]
        print(f"revision mode: {_jmode} (option {_jinfo['option']}) -- {_jinfo['label']}")
        print(f"               response to reviewers: "
              f"{'required' if _jinfo['response'] else 'not written'}; "
              f"rewrites: {'allowed' if _jinfo['rewrites'] else 'forbidden'}; "
              f"edits: {'concern-scoped only' if _jinfo['scoped'] else 'full review findings'}")
        if _jinfo.get("feedback"):
            if _jmode == JOURNAL_MODE_LLM:
                print(f"               feedback source: {LLM_FEEDBACK_DIR}/ only "
                      f"(false positives pre-filtered); no journal decision letter")
            else:
                print(f"               feedback from: "
                      f"{(ctx.cfg or {}).get('journal_feedback_from') or '(unset)'}; files: "
                      + (", ".join(_jfb) if _jfb else "(auto-detected in the corpus)"))
        else:
            print("               no journal feedback is read in this mode")
        _jsub = (ctx.state.get("journal") or {}).get("submission_dir")
        if _jsub:
            print(f"               submission package: {_jsub}"
                  f" (raw_data/ excluded, README*.md/.txt excluded"
                  + ("" if submit_code_of(ctx) else ", code/ excluded")
                  + f"; response "
                  f"{'included' if (ctx.state.get('journal') or {}).get('response') else 'not written'})")
    # Filesystem-level numbers only: walking an 11 GB sandbox tree here would make
    # `status` take minutes. Exact per-sandbox sizes are what `prune` reports.
    try:
        free = shutil.disk_usage(ctx.root).free / 1e9
        print(f"disk:          {free:.1f} GB free on the pipeline filesystem  "
              f"(every judge session copies the field + original: `prune --root {ctx.root}` "
              f"reports and reclaims sandbox space; `decide` keeps working afterwards)")
    except OSError:
        pass
    print()
    rows = []
    for r in range(1, ctx.rounds_count() + 1):
        rr = ctx.round_get(r)
        champ = rr.get("champion") or ""
        champ_rep = rr.get("champion_rep") or champ
        champ_stat = ((rr.get("stats") or {}).get(champ_rep) or {})
        med = champ_stat.get("median")
        mean = champ_stat.get("mean")
        rows.append([r, rr.get("status"), len(rr.get("field") or []),
                     rr.get("scores_per_version") or "-",
                     (champ or "-") + ("" if champ == champ_rep else f" (=base {champ_rep})"),
                     f"{med:g}" if isinstance(med, (int, float)) else "-",
                     f"{mean:.2f}" if isinstance(mean, (int, float)) else "-",
                     rr.get("pin_path") or "-", rr.get("winner_dir") or "-",
                     f"{champ_stat.get('author_placeholders') or 0}"])
    if rows:
        print(_tbl(rows, ["ROUND", "STATUS", "FIELD", "SCORES/VER", "CHAMPION", "MEDIAN",
                          "MEAN", "PIN", "WINNER DIR", "HAND-OFF"]))
        print()
    hdr = (f"{'RUN ID':<24}{'KIND':<10}{'RND':<5}{'STATUS':<9}{'ATT':<4}{'DUR':<9}{'POST':<7}"
           f"NOTE")
    print(hdr)
    print("-" * len(hdr))
    for rec in ctx.runs():
        pc = rec.get("postcheck")
        post = "-" if pc is None else ("ok" if pc.get("ok") else "ERR")
        note = rec.get("last_error") or ""
        if not note and pc and pc.get("warnings"):
            note = pc["warnings"][0]
        if rec["kind"] == "judge" and rec.get("target_id"):
            note = f"target={rec['target_id']} " + note
        print(f"{rec['id']:<24}{rec['kind']:<10}{rec.get('round', '-'):<5}"
              f"{rec['status']:<9}{rec.get('attempts', 0):<4}"
              f"{fmt_dur(rec.get('last_duration')):<9}{post:<7}{note[:60]}")
    print()
    history = attempt_history_lines(ctx)
    if history:
        print("ATTEMPT HISTORY -- every attempt is kept (diagnostics: state.json `attempts_log`; "
              f"artifacts: runs/<run>_try<N>_failed/)")
        for line in history:
            print(line)
        print()
    summarize(ctx)
    pend = [r for r in ctx.runs() if r["status"] in ("pending", "failed", "stale")]
    gapped = []
    for r in range(1, ctx.rounds_count() + 1):
        gaps = (ctx.round_get(r).get("panel_gaps") or {}).get("gaps") or []
        if gaps:
            gapped.append(r)
            print(f"[status] round {r}: JUDGE PANEL INCOMPLETE for {', '.join(gaps)} -- the round "
                  f"was not decided; see {ctx.reports_dir / f'round{r}_panel_gaps.json'}, fix the "
                  f"judge session with `retry --run <ID>`, then `run` again")
    open_rounds = [r for r in range(1, ctx.rounds_count() + 1)
                   if ctx.round_get(r).get("status") != "done"]
    if pend or gapped or open_rounds:
        if pend:
            print(f"[status] {len(pend)} run(s) need attention: "
                  f"{', '.join(r['id'] for r in pend[:8])}"
                  + ("..." if len(pend) > 8 else ""))
        if gapped and not pend:
            print(f"[status] retry the affected judge session(s) first: "
                  f"python {Path(sys.argv[0]).name} retry --root {ctx.root} --run <judge id>")
        print(f"[status] next: python {Path(sys.argv[0]).name} run --root {ctx.root}")
    else:
        print(f"[status] next: python {Path(sys.argv[0]).name} decide --root {ctx.root}")
    print(f"[status] runnable report: {ctx.reports_dir / 'DECISION_REPORT.md'}")


# ---------------------------------------------------------------------------
# CROSS-RUN TREND (read-only): the improvement chain of several pipeline roots
# ---------------------------------------------------------------------------
# "Did iteration N+1 improve on iteration N?" cannot be read off one round's
# integer: each round scores its champion against THAT round's own input, so the
# reference moves with the chain, and the champion's score is the argmax of a
# noisy panel (selection inflation). Two things ARE comparable across a chain,
# and this command reports both:
#   * the per-round PAIRED margins the round itself recorded -- vs_input (the
#     champion against the version that run started from) and vs_incumbent (the
#     champion against the previous round's champion) -- with the winner counts;
#   * the champion's ISSUE CENSUS per tier and severity (the judges' own ledger
#     rows, counted in code): the absolute "what is left" number, which does not
#     depend on the reference at all. Rounds decided before the census existed
#     report "-" there.
# It never scores, ranks or writes into a root: it reads reports/decision.json.
TREND_ROUND_FIELDS = ("run", "round", "champion", "median", "mean", "n", "vs_input",
                      "vs_incumbent", "correctness", "consistency", "preservation",
                      "completeness", "formatting", "writing", "minor", "major",
                      "critical", "fatal")
TREND_RUN_FIELDS = ("run", "rounds", "champion", "format_rows", "format_high",
                    "format_medium", "format_low", "over_length", "placeholders",
                    "generated", "certified")


def trend_read_decision(root: Path) -> dict:
    """One root's reports/decision.json, or None when absent/unreadable."""
    p = Path(root) / "reports" / "decision.json"
    if not p.is_file():
        return None
    try:
        dj = read_json(p, revive=False, lenient=True)
    except Exception:                                            # noqa: BLE001
        return None
    return dj if isinstance(dj, dict) else None


def trend_order(roots: list) -> list:
    """Order roots into the chain each one's recorded `source` implies.

    A root whose `config.source` lies inside another root's tree consumed that
    root (usually its final_clean_version), so it comes AFTER it. Roots that
    cannot be linked keep the order they were given; a cycle is reported rather
    than guessed at.
    """
    items = [(str(Path(r).resolve()), Path(r), trend_read_decision(Path(r))) for r in roots]
    known = {rp: (r, dj) for rp, r, dj in items}
    pending = [rp for rp, _r, _dj in items]
    order, guard = [], 0
    while pending and guard <= len(pending) ** 2 + 1:
        progressed = False
        for rp in list(pending):
            _r, dj = known[rp]
            src = str(((dj or {}).get("config") or {}).get("source") or "")
            parents = [op for op in pending
                       if op != rp and src
                       and (src == op or src.startswith(op.rstrip("/") + "/"))]
            if not parents:
                order.append(rp)
                pending.remove(rp)
                progressed = True
        if not progressed:
            # A cycle (or several unlinked roots): report it, keep the given order.
            order.extend(pending)
            break
        guard += 1
    return [known[rp][0] for rp in order]


def _trend_cell(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def trend_rows(roots: list) -> tuple:
    """(per-round rows, per-run rows) for the trend tables, in chain order."""
    round_rows, run_rows = [], []
    for root in trend_order([str(r) for r in roots]):
        dj = trend_read_decision(root)
        if not dj:
            run_rows.append({"run": root.name, "rounds": 0, "champion": None,
                             "format_rows": None, "format_high": None, "format_medium": None,
                             "format_low": None, "over_length": None, "placeholders": None,
                             "generated": None,
                             # None = the decision predates the certification block.
                             "certified": None})
            continue
        src = (dj.get("config") or {}).get("source")
        rounds = dj.get("rounds") or []
        for r in rounds:
            sel = r.get("selection") or {}
            rep = sel.get("champion_rep") or sel.get("champion") or r.get("stored_champion")
            st = (r.get("stats") or {}).get(rep) or {}
            census = ((r.get("issue_census") or {}).get(rep) or {})
            tiers = census.get("tiers") or {}
            sevs = census.get("severities") or {}
            row = {"run": root.name, "round": r.get("round"),
                   "champion": sel.get("champion") or r.get("stored_champion"),
                   "median": st.get("median"), "mean": st.get("mean"), "n": st.get("n"),
                   # `vs_input` is the champion against the version THIS RUN
                   # started from: the root's pristine original (`vs_original`).
                   # `vs_incumbent` is the round's base (`vs_base`). The two are
                   # distinct from round 2 on and are deliberately NOT collapsed:
                   # the first is the run-level input margin, the second the
                   # previous champion's.
                   "vs_input": st.get("vs_original"), "vs_incumbent": st.get("vs_base")}
            for tier in BASIS_TIERS:
                row[tier] = (tiers.get(tier) or {}).get("total")
            for sev in SEVERITIES:
                row[sev] = (sevs.get(sev) or {}).get("total")
            round_rows.append(row)
        fin = dj.get("final") or {}
        fmt = fin.get("format") or {}
        lengths = fin.get("lengths") or {}
        last = rounds[-1] if rounds else {}
        last_rep = ((last.get("selection") or {}).get("champion_rep")
                    or (last.get("selection") or {}).get("champion")
                    or last.get("stored_champion"))
        last_stat = ((last.get("stats") or {}).get(last_rep) or {})
        run_rows.append({
            "run": root.name, "rounds": len(rounds),
            "champion": fin.get("champion") or last.get("stored_champion"),
            "format_rows": (len(fmt.get("rows") or []) if fmt else None),
            "format_high": fmt.get("high"), "format_medium": fmt.get("medium"),
            "format_low": fmt.get("low"),
            "over_length": (len(lengths.get("over_limit") or []) if lengths else None),
            "placeholders": last_stat.get("author_placeholders"),
            "generated": dj.get("generated"),
            # `-` for decisions written before the certification block existed:
            # the old files carry no explicit verdict, so do not imply one.
            "certified": ((dj.get("certification") or {}).get("certified")
                          if isinstance(dj.get("certification"), dict) else None)})
    return round_rows, run_rows


def format_trend(round_rows: list, run_rows: list) -> str:
    """The markdown trend report (both tables plus the reading rules)."""
    L = ["# Cross-run trend (read-only)", ""]
    L.append("One row per decided round, in the chain order the recorded `source` implies "
             "(`vs_input` = the champion against the version THAT run started from; "
             "`vs_incumbent` = the champion against the previous round's champion). The two "
             "margins come from different panels, so read them as PER-STEP statements: the run "
             "that wins each step is improving on its own input, which is exactly what the "
             "reference-moving design measures. The tier/severity columns are the champion's "
             "ISSUE CENSUS (issues the panel attributed to it, from the judges' own ledger rows) "
             "-- the absolute \"what is left\" number, comparable across runs, and `-` for rounds "
             "decided before the census existed. A shrinking census with a stable margin is "
             "progress; a stable census with a stable margin is noise-limited repetition.")
    L.append("")
    L.append(_tbl([[_trend_cell(r.get(k)) for k in TREND_ROUND_FIELDS] for r in round_rows],
                  list(TREND_ROUND_FIELDS)))
    L.append("")
    L.append("Per-run deterministic counters (code-side, no panel; `-` when the run predates "
             "them): the OOXML formatting rows, the over-cap section count and the champion's "
             "hand-off placeholder count at the end of the run. `certified` is the run's own "
             "decision.json verdict (`true`/`false`; `-` when the decision predates the "
             "certification block) -- a `false` row is a recorded, refused decision, not a "
             "certified answer.")
    L.append("")
    L.append(_tbl([[_trend_cell(r.get(k)) for k in TREND_RUN_FIELDS] for r in run_rows],
                  list(TREND_RUN_FIELDS)))
    L.append("")
    return "\n".join(L)


def cmd_trend(args) -> None:
    """`trend`: read several roots' decision.json files and print the chain."""
    roots = list(getattr(args, "roots", None) or [])
    if not roots:
        roots = [getattr(args, "root", None) or DEFAULTS["root"]]
    roots = [str(Path(r).expanduser().resolve()) for r in roots]
    missing = [r for r in roots if trend_read_decision(Path(r)) is None]
    for r in missing:
        print(f"[trend] note: {r} has no readable reports/decision.json "
              f"(undecided, pruned or not a pipeline root) -- it is reported as an empty run")
    round_rows, run_rows = trend_rows(roots)
    text = format_trend(round_rows, run_rows)
    print(text)
    out = getattr(args, "out", None)
    if out:
        write_text_atomic(Path(out), text)
        print(f"[trend] written: {Path(out)}")
    csvp = getattr(args, "csv", None)
    if csvp:
        p = write_csv_atomic(
            Path(csvp), TREND_ROUND_FIELDS,
            [{k: r.get(k) for k in TREND_ROUND_FIELDS} for r in round_rows])
        print(f"[trend] written: {p}")


def agent_session_plan(ctx: Ctx, only=None) -> list:
    """Every AGENT session each round plans, without touching the corpus.

    Producing sessions come straight from `round_run_plan()`: the rewrite
    sessions the round's `--rewrites` count gives, its review (A, and B with
    `--review-split`), its auditor and its revise arms, plus the integration arms
    the round's `--integrators` mask selected. Judge session ids are the salted
    per-version tokens of `judge_token_for()` -- a few sha256 calls over
    (round, version id), never a document hash, so the whole listing costs
    milliseconds on any root.

    The judge FIELD, though, is the one thing that cannot be known before the
    arms exist: it is deduplicated by CONTENT (a member whose documents are
    content-identical to another member's is dropped), so a pending round lists
    the candidate judge sessions and says `field_exact: false`.
    """
    rows = []
    for r in range(1, ctx.rounds_count() + 1):
        rec = ctx.round_rec(r)
        if only is not None and (not only.covers_round(r) or not only.selects_round(ctx, r)):
            continue
        producing = []
        # The round's base copy (a1) is not an agent session -- it is the
        # orchestrator's copy of the previous round's pin -- but the run table
        # carries it, so list it first and label it.
        base = {"id": rid_a1(r), "vid": A1_ID, "stage": "base", "deps": [],
                "label": "base copy (no agent session)"}
        for e in [base] + round_run_plan(ctx, r):
            if only is not None and not only.entry_selected(r, e):
                continue
            run_rec = ctx.run(e["id"]) or {}
            producing.append({
                "id": e["id"],
                "session": session_id_of_entry(e),
                "stage": plan_stage_of(e),
                "label": str(e.get("stage") or ""),
                "agent": e["id"] != rid_a1(r),     # a1 is the orchestrator's copy
                "status": run_rec.get("status") or "planned",
                "deps": [str(d) for d in (e.get("deps") or [])],
            })
        field = [str(v) for v in (rec.get("field") or [])]
        # A pending round's candidates are the judgeable ids (see judgeable_ids):
        # the original, the earlier rounds' pins and the fresh arms.
        candidates = field or judgeable_ids(ctx, r)
        judge_selected = only is None or only.stage_selected(r, "judge")
        # WHICH judge sessions of the round run: the selector the `--only` items
        # give (a preview of `run --only`), else the panel recorded by an earlier
        # invocation on the pending round (see judges_enabled_spec).
        spec = (only.judge_spec_for(r) if (only is not None and judge_selected) else "") \
            or judges_enabled_spec(ctx, r)
        enabled = set()
        if spec:
            try:
                triples = parse_judges_enabled(spec, config_rounds(ctx),
                                               lambda rr: judgeable_ids(ctx, rr),
                                               lambda rr: round_judges(ctx, rr))
                enabled = {(str(v), int(k)) for rr, v, k in triples if int(rr) == int(r)}
            except ValueError:              # a hand-edited state/config: list the full panel
                enabled = set()
        judges = []
        if judge_selected:
            for vid in candidates:
                token = judge_token_for(ctx, r, vid)
                for j in range(1, round_judges(ctx, r) + 1):
                    if enabled and (str(vid), int(j)) not in enabled:
                        continue
                    rid = rid_judge(r, token, j)
                    judges.append({
                        "id": rid,
                        "target": str(vid),
                        "judge_index": int(j),
                        "status": (ctx.run(rid) or {}).get("status") or "planned",
                    })
        rows.append({
            "round": int(r),
            "status": rec.get("status") or "pending",
            "champion": rec.get("champion"),
            "judges_per_version": int(round_judges(ctx, r)),
            "judges_enabled": spec or JUDGES_ENABLED_ALL,
            "integrators": f"0x{round_integrators(ctx, r):X}",
            "field": field,
            "field_exact": bool(field),
            "judges_selected": bool(judge_selected),
            "producing": producing,
            "judge": judges,
        })
    return rows


def cmd_agents(args) -> None:
    """`agents`: list the agent-session names every round plans.

    A DRY plan: no sandbox is materialized, no agent is launched, no document is
    hashed (see agent_session_plan). `--only` previews exactly the sessions the
    equivalent `run --only` invocation would drive.
    """
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    # `--json` must stay parseable: keep everything `load()` prints (the
    # pipeline-identity note) out of the JSON body and hand it back as a field.
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        ctx.load()
    notes = [ln for ln in captured.getvalue().splitlines() if ln.strip()]
    only = parse_only_spec(getattr(args, "only", None))
    if only is not None and only.is_everything():
        only = None
    if only is not None:
        resolve_judge_run_ids(ctx, only, label="[agents]", sink=notes)
        only.validate(ctx.rounds_count())
        validate_only_selectors(ctx, only)
    rows = agent_session_plan(ctx, only)
    if getattr(args, "pending", False):
        for row in rows:
            row["producing"] = [s for s in row["producing"] if s["status"] != "done"]
            row["judge"] = [s for s in row["judge"] if s["status"] != "done"]
    if getattr(args, "json", False):
        print_raw(json.dumps({"root": str(ctx.root),
                              "only": (only.label() if only is not None else None),
                              "notes": notes,
                              "rounds": rows}, indent=2))
        return
    for note in notes:
        print(note)
    np_ = sum(len(x["producing"]) for x in rows)
    nj = sum(len(x["judge"]) for x in rows)
    what = (f"--only {only.label()}" if only is not None else
            "every planned session")
    print(f"[agents] root: {ctx.root}")
    print(f"[agents] {what}: {np_} producing + {nj} judge session(s) over "
          f"{len(rows)} of {ctx.rounds_count()} round(s)"
          + ("  [--pending: finished sessions hidden]" if getattr(args, "pending", False) else ""))
    candidates = []
    for row in rows:
        print()
        print(f"round {row['round']}/{ctx.rounds_count()}  status={row['status']}  "
              f"champion={row['champion'] or '-'}  integrators={row['integrators']}")
        for s in row["producing"]:
            note = "" if s["agent"] else "   (no agent: the round's base copy)"
            print(f"  {s['id']:<26} {s['label'] or s['stage']:<22} {s['status']}{note}")
        if row["judge"]:
            head = (f"judge sessions ({row['judges_per_version']} per version; --only judge "
                    f"sessions: {row['judges_enabled']}):")
            print(f"  {head:<64} {len(row['judge'])}")
            for s in row["judge"]:
                label = f"-> {s['target']}  (judge {s['judge_index']}/{row['judges_per_version']})"
                print(f"  {s['id']:<26} {label:<22} {s['status']}")
            if not row["field_exact"]:
                candidates.append(row["round"])
        elif not row["judges_selected"]:
            print("  judge sessions: NOT selected by this invocation's --only")
    if candidates:
        print()
        print(f"[agents] round(s) {', '.join(str(r) for r in candidates)}: the judge ids above "
              f"are the CANDIDATES. The judge "
              f"field keeps one member per distinct document set, so a candidate whose package is "
              f"content-identical to another member's is dropped before judging and its sessions "
              f"never start (`run` prints the dropped members). Everything else is exact: no "
              f"document was hashed to produce this listing.")
    else:
        print()
        print("[agents] every id above is exact: the rounds' fields are already deduplicated, so "
              "no session here is a candidate whose membership can still change.")
    print("[agents] every id above can be fed back to `run --only` as printed: the producing ids "
          "(`--only r1_a2_revise`, `--only r1_w1`) and the judge ids (`--only "
          "judge_t497f106d_j1`, or `--only judge_1` for judge 1 of every version). The base copy's "
          "`a1` line is the only exception: it is not an agent session.")


def cmd_decide(args) -> None:
    ctx = Ctx(Path(args.root).resolve(),
              strict_venue=bool(getattr(args, "strict_venue", False)))
    ctx.load()
    refuse_foreign_pipeline(ctx, "decide")
    # Same note as `run` (see there): the decision is produced BY this code, so
    # which code it is has to be in the log of the decision too.
    _snap = pipeline_snapshot_note(ctx)
    if _snap:
        print(f"[decide] {_snap}")
    with ctx.lock("decide"):
        _cmd_decide_locked(ctx, args)


def _cmd_decide_locked(ctx: Ctx, args) -> None:
    # `decide` is NOT the read-only audit the comment in cmd_run_decide claims:
    # it writes decision.json, the round reports and final_clean_version/, so it
    # must hold the same root lock as run/retry/prune/redline.
    ctx._champion_select_override = str(getattr(args, "champion_select", None) or "")
    venue_profile_of(ctx)          # the report names the venue and quotes its limits
    if getattr(args, "unlink_zotero_fields", False):
        die("decide cannot unlink Zotero fields after the round has been judged: "
            "final_clean_version/ must be the champion pin's bytes, and a post-pin "
            "flatten would publish a different artifact. Set "
            "`format_policy.unlink_zotero_fields` (or "
            "`format_policy.unlink_zotero_fields_at_publish`) in pipeline_config.json "
            "before `run`, so every candidate is flattened before it is scored, or "
            "leave the live fields for the author to unlink manually.", code=2)
    if journal_is_scoped(ctx):
        # A major/minor revision is not decided: there is no field, no judge
        # panel and no champion choice -- the single concern-scoped revision is
        # the answer, and the journal itself decides next.
        j = (ctx.state.get("journal") or {})
        print(f"[decide] revision mode {journal_mode_of(ctx)!r} "
              f"(option {JOURNAL_MODES[journal_mode_of(ctx)]['option']}): a concern-scoped "
              f"revision has no judge panel and no champion decision.")
        if j.get("submission_dir"):
            print(f"[decide] the submission package is {j['submission_dir']}"
                  + (" (with the response to reviewers)"
                     if j.get("response") else " (no response letter in this mode)"))
        else:
            print(f"[decide] nothing is published yet: run `run` to finish the revision and "
                  f"assemble {JOURNAL_SUBMISSION_DIR}/.")
        return
    R = ctx.rounds_count()
    if R < 1:
        die("pipeline_config.json records no rounds")
    pok, pdetail = pristine_integrity(ctx)
    perrs = pinned_integrity(ctx)
    evid_changed, evid_missing = evidence_integrity(ctx)
    advisories = decide_advisories(ctx)
    rounds_data, problems = [], []
    problems.extend(f"evidence: {e}" for e in evid_changed)
    if not pok:
        problems.append(f"integrity: the pristine original CHANGED ({pdetail}); every judge's "
                        f"regression reference is no longer what is on disk")
    problems.extend(f"integrity: {e}" for e in perrs)
    for note in raw_data_advisories(ctx):
        print(f"[decide] WARNING: {note}")
    chain_ok = bool(pok and not perrs and not evid_changed)
    for e in evid_missing:
        print(f"[decide] note: {e}")
    panel_gaps = {}
    auto_rounds = []
    incomplete_rounds = []
    _panel_gaps_dirty = False
    for r in range(1, R + 1):
        rrec = ctx.round_get(r)
        if rrec.get("status") != "done":
            incomplete_rounds.append(r)
            problems.append(f"round {r}: status={rrec.get('status')!r} (not complete)")
            continue
        _plan_mode = str((rrec.get("plan") or {}).get("champion_select") or "").lower()
        if rrec.get("auto_promoted") or _plan_mode in ("revise", "integrate"):
            # NO JUDGE PANEL: this round was auto-promoted. Re-derive the target
            # from the round's OWN recorded plan (never from today's config),
            # verify the stored champion, and report the round as provisional.
            mode = _plan_mode or str(rrec.get("champion_select") or "revise")
            target = auto_champion_vid(ctx, r, mode)
            stored_champ = str(rrec.get("champion") or target)
            agg, sel = auto_round_payload(ctx, r, stored_champ, mode)
            mismatch = None
            if stored_champ != target:
                mismatch = (f"auto-promoted champion {stored_champ!r} != the version its plan "
                            f"names ({target!r})")
                problems.append(f"round {r}: {mismatch}; the round record is inconsistent")
            auto_rounds.append(r)
            print(f"[decide] round {r}: {stored_champ} was auto-promoted by "
                  f"--champion-select {mode}; no judge panel exists, so the round is "
                  f"PROVISIONAL (not a scored/certified decision)")
            rounds_data.append({"round": r, "agg": agg, "sel": sel,
                                "pin": find_pin(ctx, rrec.get("pin_id")) or {},
                                "winner": find_winner(ctx, r), "stored": rrec,
                                "mismatch": mismatch, "auto_promoted": True})
            continue
        field = rrec.get("field") or []
        agg = aggregate_round(ctx, r, field)
        # Keep every decided round's own raw-score file present and current, even
        # for roots whose round predates it (the same file `run` writes at
        # aggregation time).
        try:
            _rp = write_round_raw_scores(ctx, r, agg)
            print(f"[decide] round {r} raw scores -> {_rp.relative_to(ctx.root)}")
        except OSError as e:
            print(f"[decide] round {r} WARNING: could not write its raw scores: {e}")
        try:
            _icp = write_round_issue_census(ctx, r, agg)
            _imp = write_round_issue_matrix(ctx, r, agg)
            _icup = write_round_issue_cumulative(ctx, r, agg)
            _idap = write_round_dedup_audit(ctx, r, agg)
            _dfp = write_round_defects(ctx, r, agg)
            print(f"[decide] round {r} issue census -> {_icp.relative_to(ctx.root)}"
                  f"; severity_tier_category matrix -> {_imp.relative_to(ctx.root)}"
                  f"; prefix sums -> {_icup.relative_to(ctx.root)}"
                  f"; dedup audit -> {_idap.relative_to(ctx.root)}"
                  f"; defects -> {_dfp.relative_to(ctx.root)}")
        except OSError as e:
            print(f"[decide] round {r} WARNING: could not write its issue census: {e}")
        # The LLM defect audit (diagnostic; the same flags as `run`).  The stored
        # verdicts are reused when the defect rows are unchanged, so a
        # `run` + `decide` pair pays for the audit once.
        try:
            _prov = ctx.state.get("judge_provider") or {}
            _jcmd = [str(_prov.get("judge"))] if _prov.get("judge") else None
            _dcmd, _dsrc = resolve_defect_audit_cmd(
                args, _jcmd, bool(_prov.get("judge_manual")),
                ctx.state.get("defect_audit") or {})
            _da = write_round_defect_audit(
                ctx, r, agg=agg, agent_cmd=_dcmd,
                timeout=getattr(args, "timeout", None))
            if _da.get("used") and _da.get("ok"):
                _dst = " (reused)" if _da.get("reused") else ""
                print(f"[decide] round {r} LLM defect audit{_dst}: "
                      f"{_da.get('tp', 0)} TP / {_da.get('fp', 0)} FP of "
                      f"{_da.get('rows', 0)} defect row(s) -> "
                      f"reports/round{r}_auditedTP_defects.csv "
                      f"(+ audited census/matrix/cumulative/raw scores)")
            elif _da.get("used"):
                print(f"[decide] round {r} WARNING: the LLM defect audit produced no "
                      f"verdict ({_da.get('reason')}); no audited files were written")
            else:
                print(f"[decide] round {r} note: the LLM defect audit is off "
                      f"({_da.get('reason')})")
        except Exception as e:                                       # noqa: BLE001
            print(f"[decide] round {r} WARNING: the LLM defect audit failed: {e}")
        # Cross-judge conflicts: flag every contradiction between the round's
        # independent judge sessions as a REQUIRED MANUAL CHECK.  The mechanical
        # pass always runs; the LLM pass is OFF by default and runs only for an
        # explicit --conflict-agent[-cmd] or PAPER_CONFLICT_AGENT_CMD this
        # invocation (the backend `run` recorded stays diagnostic).
        try:
            _cfd = write_round_judge_conflicts(
                ctx, r, agg=agg,
                agent_cmd=conflict_agent_cmd_from_args(args, ctx),
                timeout=getattr(args, "timeout", None))
            _cfc = _cfd.get("counts") or {}
            print(f"[decide] round {r} judge conflicts -> "
                  f"reports/round{r}_judge_conflicts.md "
                  f"({_cfc.get('total', 0)} conflict(s): {_cfc.get('blocker', 0)} blocker, "
                  f"{_cfc.get('major', 0)} major, {_cfc.get('minor', 0)} minor)")
        except Exception as e:                                       # noqa: BLE001
            print(f"[decide] round {r} WARNING: judge-conflict audit failed: {e}")
        # The same guard `run` applies before deciding a round: a shrunk panel must
        # never be certified. `run` refuses to decide; `decide` must refuse to sign.
        gaps = [vid for vid in agg["field"]
                if not (agg["stats"].get(vid) or {}).get("complete")]
        if gaps:
            panel_gaps[r] = gaps
            _need = (agg.get("scores_per_version_by_version") or {})
            _need = ", ".join(f"{v}: {_need.get(v, agg['scores_per_version'])}"
                              for v in gaps)
            problems.append(
                f"round {r}: JUDGE PANEL INCOMPLETE for {', '.join(gaps)} "
                f"({_need} directed scores are required); "
                f"the round is NOT certified -- repair the failing judge session(s) with "
                f"`retry --run <ID>` and re-run the round")
            write_json_atomic(ctx.reports_dir / f"round{int(r)}_panel_gaps.json",
                              {"round": int(r), "gaps": gaps,
                               "diagnostics": agg.get("diagnostics") or {},
                               "checked": utcnow()})
            # `run` records the gap on the round record; `decide` used to write
            # only the report file, so `status` (which reads the record) hid
            # exactly the blocker that made the decision uncertified.
            rrec["panel_gaps"] = {"round": int(r), "gaps": gaps,
                                  "checked": utcnow()}
            _panel_gaps_dirty = True
        else:
            if rrec.pop("panel_gaps", None) is not None:
                _panel_gaps_dirty = True
            _stale_gaps = ctx.reports_dir / f"round{int(r)}_panel_gaps.json"
            if _stale_gaps.exists():
                with contextlib.suppress(OSError):
                    _stale_gaps.unlink()
        sel = select_champion(ctx, r, agg)
        mismatch = None
        if sel["champion"] != rrec.get("champion"):
            mismatch = (f"recomputed champion {sel['champion']!r} != stored champion "
                        f"{rrec.get('champion')!r}")
            decided_by = rrec.get("pipeline_version")
            if decided_by and decided_by != VERSION:
                mismatch += (f" [the round was decided by pipeline v{decided_by}; this is "
                             f"v{VERSION}, whose eligibility/ranking rules may differ -- "
                             f"re-deciding requires re-running the round, because a later "
                             f"round's inputs were produced from the stored champion]")
            problems.append(f"round {r}: {mismatch}; the pinned chain is NOT re-derived "
                            f"silently -- inspect the judge sheets or `retry` the round")
        rounds_data.append({"round": r, "agg": agg, "sel": sel,
                            "pin": find_pin(ctx, rrec.get("pin_id")) or {},
                            "winner": find_winner(ctx, r), "stored": rrec,
                            "mismatch": mismatch})
    try:
        _cfp = write_judge_conflicts_todo(ctx)
        print(f"[decide] judge-conflict manual TODO list -> "
              f"{_cfp.relative_to(ctx.root).as_posix()}")
    except OSError as e:
        print(f"[decide] WARNING: could not write the judge-conflict TODO list: {e}")
    if _panel_gaps_dirty:
        ctx.save_state()
    if not rounds_data:
        print("No completed rounds yet; nothing to decide.")
        for p in problems:
            print(f"  - {p}")
        sys.exit(2)
    final = rounds_data[-1]
    # The anti-regression gate exempts the round's own base (select_champion: the
    # base is the incumbent the no-progress fallback crowns), so the FINAL champion
    # can be a row the panel judged worse than the pristine original -- in round 2+
    # that is the inherited champion re-judged by a stricter panel. The selection
    # rule is left alone; decide simply must not sign that winner as certified,
    # exactly like an incomplete panel.
    final_champ_row = stats_row_for(final["agg"], final["stored"].get("champion"))
    final_regression = None
    if final_champ_row and final_champ_row.get("anti_regression_ok") is False:
        final_regression = (f"the final champion {final['stored'].get('champion')!r} is judged "
                            f"WORSE than the pristine original (vs_original median "
                            f"{final_champ_row.get('vs_original')!r} < "
                            f"{VS_ORIGINAL_TOLERANCE:g})")
        problems.append(f"round {final['round']}: {final_regression}; the anti-regression gate "
                        f"exempts the round's base, so the answer is NOT certified")
    # A pre-registered early stop (--stop-after-no-progress) is a deliberate end
    # of the run, not an unfinished one: the answer is final, and the stop is
    # recorded in decision.json / the report.
    _stopped_raw = ctx.state.get("stopped_early") or {}
    # A stop record only explains the run when it stopped at the FINAL decided
    # round of THIS configured run. A record from an earlier invocation that
    # later resumed and drove more rounds is stale and must not exempt the
    # still-incomplete configured rounds from certification.
    _stop_applies = bool(_stopped_raw) \
        and int(_stopped_raw.get("after_round") or -1) == int(final["round"]) \
        and int(_stopped_raw.get("planned_rounds") or -1) == int(R)
    _stopped = _stopped_raw if _stop_applies else {}
    partial_run = final["round"] < R and not _stop_applies
    provisional = partial_run or bool(auto_rounds)
    win_dir = ctx.root / (final["stored"].get("winner_dir") or "")
    win_captions = (scan_captions_in_sources([(win_dir, "", ())], limit=caption_limit_of(ctx))
                    if final["stored"].get("winner_dir") and win_dir.is_dir() else None)
    win_lengths = (scan_lengths_in_sources([(win_dir, "", ())],
                                           profile=venue_profile_of(ctx, required=False))
                   if final["stored"].get("winner_dir") and win_dir.is_dir() else None)
    win_format = (scan_format_in_sources([(win_dir, "", ())], policy=format_policy_of(ctx))
                  if final["stored"].get("winner_dir") and win_dir.is_dir() else None)
    win_token = (revision_token_for_dir(win_dir)
                 if final["stored"].get("winner_dir") and win_dir.is_dir() else None)
    cap_ok, cap_note = caption_gate(win_captions)
    caption_warnings = []
    if win_captions and win_captions.get("over_limit"):
        caption_warnings.append(
            f"{len(win_captions['over_limit'])} caption(s) in the final winner exceed the "
            f"SUGGESTED {win_captions.get('limit')}-word length (advisory; the winner keeps its "
            f"place and nothing is failed on caption length): "
            + ", ".join(f"{c['document']}:{c['caption']} ({c['words']})"
                        for c in win_captions["over_limit"][:5]))
    if win_captions and win_captions.get("unparsed"):
        caption_warnings.append("caption text could not be parsed in: "
                                + ", ".join(win_captions["unparsed"][:5])
                                + " (verify M18 manually)")
    if win_captions and win_captions.get("suspected_count"):
        caption_warnings.append(
            f"{win_captions['suspected_count']} figure-like line(s) in the final winner were NOT "
            f"recognised as captions by the code-side scan (M18 is advisory, so nothing is gated "
            f"on it): "
            + " | ".join(win_captions.get("suspected", [])[:5]) + " (verify M18 manually)")
    length_warnings = []
    if win_lengths and win_lengths.get("over_limit"):
        def _length_brief(row):
            if str(row.get("section") or "") == "cover letter":
                return (f"{row.get('document')}: cover letter TOTAL "
                        f"{row.get('total_words')} words (cap {row.get('total_max')})")
            return (f"{row.get('document')}: {row.get('section')} {row.get('words')} words "
                    f"(cap {row.get('cap')})")
        length_warnings.append(
            f"{len(win_lengths['over_limit'])} abstract/main-text/cover-letter limit(s) in "
            f"the final winner "
            f"exceed this pipeline's relaxed caps (advisory for ranking; the winner keeps its "
            f"place, but an over-cap FINAL package is not submission-ready): "
            + ", ".join(_length_brief(r) for r in win_lengths["over_limit"][:5]))
    if win_lengths and win_lengths.get("unparsed"):
        length_warnings.append("abstract/main-text text could not be parsed in: "
                               + ", ".join(win_lengths["unparsed"][:5])
                               + " (verify M19 manually)")
    # Formatting gate (opt-in): the code-side OOXML scan is advisory unless
    # `decide --format-gate` is given. High-severity findings (a break-only
    # paragraph, tracked changes, a rendered blank page) then become decision
    # problems, so the champion is not certified with a submission-ready label.
    format_problems = []
    format_unavailable = ""
    if win_format:
        format_problems = [f"formatting: {r['document']} {r['location']}: {r['evidence']}"
                           for r in (win_format.get("rows") or [])
                           if r.get("severity") == "high"]
        if win_format.get("unavailable"):
            format_unavailable = (f"the OOXML formatting scanner was UNAVAILABLE: "
                                  f"{win_format['unavailable']}")
        if getattr(args, "format_gate", False):
            problems.extend(format_problems)
            if format_unavailable:
                problems.append(f"formatting: {format_unavailable} -- the scan cannot "
                                f"certify the winner under --format-gate")
    # RESIDUAL gate (opt-in): the pipeline's own artefacts can leave a champion
    # with items it already knows how to state -- an answerable `searchable`
    # hand-off marker, a review whose decision tables were boilerplate or
    # unfilled, or unsourced numbers in the abstract/legends. Always recorded;
    # `--residual-gate` makes them decision problems.
    residuals = collect_residuals(ctx)
    # The two opt-out gates are collected here so the CERTIFICATION verdict (and
    # the status readme) carries them. They no longer gate the clean copy itself
    # (2026-10-01: the directory is always generated, operator's request); the
    # readme says NOT CERTIFIED and why.
    gate_problems = []
    if getattr(args, "format_gate", False) and format_problems:
        gate_problems.append(f"{len(format_problems)} HIGH-severity formatting finding(s) in the "
                             f"final winner (--format-gate)")
    if getattr(args, "format_gate", False) and format_unavailable:
        gate_problems.append(f"{format_unavailable} (--format-gate)")
    if residuals.get("gating") and getattr(args, "residual_gate",
                                            DEFAULT_RESIDUAL_GATE):
        gate_problems.append(f"{len(residuals['gating'])} gated residual(s) "
                             f"(--residual-gate is ON by default; --non-residual-gate records "
                             f"them as advisory only)")
    if gate_problems:
        problems.extend(f"gate: {p}" for p in gate_problems)
    if residuals.get("gating") and getattr(args, "residual_gate",
                                            DEFAULT_RESIDUAL_GATE):
        problems.extend(f"residual: {it}" for it in residuals["gating"])
    for it in residuals.get("advisory") or []:
        print(f"[decide] residual (advisory, never gated): {it}")
    # A clean, self-contained copy of the champion that can seed the NEXT
    # pipeline run (`setup --source <root>/final_clean_version`). It is ALWAYS
    # built, certified or not (2026-10-01, operator's request): the certification
    # verdict and the reasons travel in the SIBLING `final_clean_version.readme.md`
    # (never inside the directory, which must stay byte-clean manuscript
    # content). `_clean_reason` is now only the note the readme carries.
    # A final champion the panel judged WORSE than the pristine original is not
    # a package to hand to the next run; ANY round's recomputation mismatch
    # blocks, exactly as it blocks `certification` below.
    # SUBMISSION READINESS (separate from process certification): the published
    # package's own findings -- a form shell, internal working material -- are
    # recorded on every decision; `--require-ready` turns them into blockers.
    # The copy is ALWAYS built (certified or not), so these findings are known
    # BEFORE the verdict is stamped: the readiness blockers join `gate_problems`
    # first, and `final_clean_version.certified` is derived from the completed
    # reason afterwards. Stamping it first wrote `final_clean_version.certified:
    # true` beside `certification.certified: false` -- exactly the split
    # `final_clean_reason` exists to prevent.
    final_clean = publish_final_clean(ctx, final, True, "",
                                      flatten_zotero=bool(getattr(
                                          args, "unlink_zotero_fields", False)),
                                      residuals=residuals)
    published_lengths = final_clean.get("lengths") or win_lengths
    readiness = package_readiness(final_clean, residuals=residuals,
                                  author_to_complete=author_to_complete_mode_of(ctx),
                                  lengths=published_lengths)
    gate_problems.extend(readiness_gate_problems(readiness,
                                                 bool(getattr(args, "require_ready", False))))
    if incomplete_rounds and not _stop_applies:
        # `problems` carried this but `decide_certification` did not read it:
        # a later completed round could still be labelled CERTIFIED. A
        # PRE-REGISTERED stop is a deliberate end: the rounds after it are
        # supposed to be incomplete.
        gate_problems.append(
            "round(s) " + ", ".join(str(r) for r in incomplete_rounds)
            + " are not complete")
    if final_clean.get("skipped"):
        # The published package is part of the answer (AGENTS.md rule 10): a
        # decision that could not build `final_clean_version/` is not certified,
        # and its readme must say the directory does not exist.
        gate_problems.append("the final_clean_version package was not published: "
                             + str(final_clean.get("skipped")))
    _clean_reason = final_clean_reason(final, rounds_data, R, final_regression, chain_ok,
                                       provisional, panel_gaps, gate_problems,
                                       auto_promoted=auto_rounds,
                                       skipped=final_clean.get("skipped"))
    final_clean["certified"] = not _clean_reason
    final_clean["certification_note"] = _clean_reason or None
    # `action` (created/unchanged) describes THIS invocation, not the decision:
    # keeping it out of decision.json/report keeps two consecutive `decide` runs
    # byte-identical (apart from their generation timestamp).
    final_clean_json = {k: v for k, v in final_clean.items() if k != "action"}
    integrity = {"pristine_ok": pok, "pristine_detail": pdetail, "pinned_errors": perrs,
                 "evidence_not_verifiable": list(evid_missing),
                 "hash_checks": "skipped" if hash_checks_skipped() else "verified",
                 "hash_checks_note": hash_skip_note() or None,
                 "recovery": advisories["recovery"],
                 "visual_not_verified": advisories["visual_not_verified"]}
    # CERTIFICATION: ONE verdict that the process exit code, decision.json and
    # the report all read from (`decide_certification`). Before this block a
    # failed `decide` wrote a decision.json with no explicit verdict (and could
    # even publish the clean copy first); a reader could not tell a certified
    # answer from a refused one without re-deriving the exit conditions.
    certification = decide_certification(
        gate_problems, rounds_data, chain_ok, panel_gaps, final_regression, provisional,
        bool(getattr(args, "require_complete", False)), final["round"], R,
        final_clean, final_clean.get("skipped"), auto_promoted=auto_rounds)
    # `--skip-hash`: the verification passes did NOT run, so the verdict says so
    # -- a NOTE, never a blocker (skipping is the operator's explicit choice) and
    # never the word "verified". `certified` keeps its meaning: "nothing THIS
    # invocation could check blocks the answer".
    certification["hash_checks"] = "skipped" if hash_checks_skipped() else "verified"
    if hash_checks_skipped():
        certification["notes"] = list(certification.get("notes") or []) + [hash_skip_note()]
    certification["submission_ready"] = readiness["submission_ready"]
    certification["package_findings"] = readiness["findings"]
    cert_blockers = certification["blockers"]
    cert_notes = certification["notes"]
    # The status document is a SIBLING of the directory and is written on every
    # `decide` (certified, provisional or refused), so the package is never
    # mistaken for a signed answer.
    readme_path = write_final_clean_readme(ctx, certification, final, final_clean)
    decision = {
        "generated": utcnow(),
        "pipeline_root": str(ctx.root),
        "version": VERSION,
        # The rule set this decision was produced under: the venue profile (and
        # the journal the prompts named), recorded next to the numbers it
        # produced so a reader never has to guess which limits applied.
        "venue": venue_block(ctx),
        "config": ctx.cfg,
        "integrity": integrity,
        "problems": problems,
        "certification": certification,
        "judge_provider": ctx.state.get("judge_provider") or {},
        "stopped_early": _stopped or None,
        # Gates are reported at the TOP level as well as inside the final round's
        # `final` block: an operator reading decision.json should not have to
        # know where a gate put its rows.
        "residual_gate": bool(getattr(args, "residual_gate", DEFAULT_RESIDUAL_GATE)),
        "residuals": residuals,
        "readiness": readiness,
        "score_model": score_model_doc(ctx),
        "rounds": [{"round": rd["round"],
                    "field": rd["agg"]["field"],
                    "field_size": rd["agg"]["field_size"],
                    "scores_per_version": rd["agg"]["scores_per_version"],
                    "stats": rd["agg"]["stats"],
                    "diagnostics": rd["agg"]["diagnostics"],
                    # The reported issue census (issues per version/tier/severity,
                    # from the judges' own ledger rows). REPORTED ONLY -- it never
                    # feeds the ranking; it is the number a chain of runs compares
                    # across rounds. The same data is in
                    # reports/round<r>_issue_census.csv.
                    "issue_census": rd["agg"].get("issue_census") or {},
                    "selection": rd["sel"],
                    "champion_pin": rd["pin"],
                    "stored_champion": rd["stored"].get("champion"),
                    # The incumbent margin the human reads: median + sign counts of
                    # the (champion, base) directed scores. REPORTED ONLY -- the
                    # ranking key stays field-wide (a 2*judges pair is one outlier
                    # session away from flipping).
                    "champion_vs_base": {
                        "median": (stats_row_for(rd["agg"],
                                                 rd["stored"].get("champion")) or {}
                                   ).get("vs_base"),
                        "n": len(((stats_row_for(rd["agg"], rd["stored"].get("champion")) or {}
                                  ).get("vs_base_vals") or [])),
                        "wins": sum(1 for x in ((stats_row_for(
                            rd["agg"], rd["stored"].get("champion")) or {}
                        ).get("vs_base_vals") or []) if x > 0),
                        "losses": sum(1 for x in ((stats_row_for(
                            rd["agg"], rd["stored"].get("champion")) or {}
                        ).get("vs_base_vals") or []) if x < 0),
                        "reported_only": True,
                    },
                    "captions": {vid: {"gate_ok": s.get("caption_gate_ok"),
                                       "within_suggested_length": s.get("caption_gate_ok"),
                                       "note": s.get("caption_note"),
                                       "advisory": "caption length is reported only and can "
                                                   "never change eligibility or ranking",
                                       "over_limit": [c["caption"] for c in
                                                      (s.get("captions") or {}).get(
                                                          "over_limit", [])]}
                                 for vid, s in rd["agg"]["stats"].items()},
                    "recomputed_matches_stored": rd["mismatch"] is None}
                   for rd in rounds_data],
        "final": {"round": final["round"],
                  "champion": final["stored"].get("champion"),
                  "pin": final["pin"].get("id"),
                  "pin_path": final["stored"].get("pin_path"),
                  "winner_dir": final["stored"].get("winner_dir"),
                  "digest": final["pin"].get("digest"),
                  "caption_gate_ok": cap_ok,
                  "caption_note": cap_note,
                  "caption_warnings": caption_warnings,
                  "length_note": length_note(published_lengths),
                  "lengths": published_lengths,
                  "length_warnings": length_warnings,
                  "format_note": format_note(win_format),
                  "format": win_format,
                  "format_problems": format_problems,
                  "format_gate": bool(getattr(args, "format_gate", False)),
                  "residual_gate": bool(getattr(args, "residual_gate", DEFAULT_RESIDUAL_GATE)),
                  "residuals": residuals,
                  "final_clean_version": final_clean_json,
                  "revision_token": win_token,
                  "final_round_complete": final["round"] == R},
    }
    write_json_atomic(ctx.reports_dir / "decision.json", decision)
    csv_path = write_raw_scores(ctx, rounds_data)
    report = build_decision_report(ctx, rounds_data, integrity, problems, final,
                                   win_lengths=published_lengths, final_clean=final_clean_json,
                                   revision_token=win_token, win_format=win_format,
                                   format_gate=bool(getattr(args, "format_gate", False)),
                                   format_problems=format_problems,
                                   certification=certification)
    write_text_atomic(ctx.reports_dir / "DECISION_REPORT.md", report)

    # Warn about a provisional answer BEFORE anything can be packaged from it.
    if partial_run:
        print(f"[decide] WARNING: only {final['round']} of {R} rounds are complete; the answer "
              f"below is provisional (it is the last completed round's champion).")
    if auto_rounds:
        print(f"[decide] WARNING: round(s) {', '.join(str(r) for r in auto_rounds)} were "
              f"auto-promoted WITHOUT a judge panel (--champion-select); the verdict is "
              f"PROVISIONAL / NOT JUDGED, never a certified panel result.")
    if panel_gaps:
        print("[decide] WARNING: the judge panel is incomplete for "
              + ", ".join(f"round {r} ({', '.join(v)})" for r, v in sorted(panel_gaps.items()))
              + "; those rounds are not certified (reports/round<r>_panel_gaps.json).")

    if args.package_winner:
        pin = final["pin"]
        # Prefer the published winner directory (it is the copy the operator
        # reads); fall back to the pin. Both are verified to be identical.
        wsrc = ctx.root / final["stored"]["winner_dir"] \
            if final["stored"].get("winner_dir") else None
        src = wsrc if (wsrc and wsrc.is_dir()) else (pinned_docs_dir(ctx, pin) if pin else None)
        if final["mismatch"]:
            print("[decide] --package-winner skipped: the stored champion failed recomputation.")
        elif not chain_ok:
            print("[decide] --package-winner REFUSED: the content-addressed chain is broken "
                  "(see the PROBLEMS list); packaging it would hand you content that does not "
                  "match what was judged. Restore the pin/winner tree or re-run the round.")
        elif partial_run:
            print(f"[decide] --package-winner REFUSED: only round {final['round']} of {R} is "
                  f"complete, so the last completed round's champion is PROVISIONAL. Finish the "
                  f"remaining round(s) first (the answer above is not the round-{R} champion).")
        elif panel_gaps:
            print("[decide] --package-winner REFUSED: the judge panel is incomplete for "
                  + ", ".join(f"round {r} ({', '.join(v)})" for r, v in sorted(panel_gaps.items()))
                  + "; a shrunk panel must never be packaged as a decision. See "
                  + str(ctx.reports_dir / "round<r>_panel_gaps.json"))
        elif src is None or not src.is_dir():
            print("[decide] --package-winner skipped: neither the winner directory nor the pin "
                  "is present on disk.")
        else:
            if auto_rounds:
                print("[decide] --package-winner: the champion was AUTO-PROMOTED without a judge "
                      "panel; the package is a PROVISIONAL (unjudged) hand-off, not a certified "
                      "panel result.")
            tmp = ctx.root / "final.tmp"
            if tmp.exists():
                rmtree_force(tmp)
            copy_into(src, tmp, root=ctx.root)
            dst = ctx.root / "final"
            if dst.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                prev = unique_path(ctx.root / f"final.prev_{stamp}")
                shutil.move(str(dst), str(prev))
            os.replace(tmp, dst)
            print(f"[decide] final package: {dst}")

    print()
    _verdict = certification_label(certification)
    print(f"[decide] certification: {_verdict}"
          + (f" -- {'; '.join(cert_blockers)}" if cert_blockers else "")
          + (f" ({'; '.join(cert_notes)})" if cert_notes else ""))
    for rd in rounds_data:
        st = rd["agg"]["stats"]
        champ = rd["stored"].get("champion")
        crow = stats_row_for(rd["agg"], champ)
        med = crow.get("median")
        mean = crow.get("mean")
        print(f"[decide] round {rd['round']}: field={rd['agg']['field_size']} "
              f"scores/version={rd['agg']['scores_per_version']} champion={champ} "
              f"median={med if med is not None else '-'} "
              f"mean={f'{mean:.3f}' if mean is not None else '-'} "
              f"winner={rd['stored'].get('winner_dir') or rd['stored'].get('pin_path')}")
    pin = final["pin"] or {}
    print(f"[decide] FINAL (round {final['round']}/{R}): {final['stored'].get('champion')} "
          f"-> {ctx.root / (final['stored'].get('winner_dir') or final['stored'].get('pin_path'))} "
          f"(digest {str(pin.get('digest'))[:12]})")
    print(f"[decide] report:   {ctx.reports_dir / 'DECISION_REPORT.md'}")
    print(f"[decide] decision: {ctx.reports_dir / 'decision.json'}")
    print(f"[decide] raw data: {csv_path}")
    print(f"[decide] captions (final winner): {cap_note}")
    for w in caption_warnings:
        print(f"[decide] CAPTION NOTE (advisory, nothing is enforced): {w}")
    print(f"[decide] abstract/main-text length (published package): "
          f"{length_note(published_lengths)}")
    for w in length_warnings:
        print(f"[decide] LENGTH NOTE (advisory, nothing is enforced): {w}")
    if final_clean.get("path"):
        print(f"[decide] final clean version: {final_clean['path']} "
              f"({final_clean['files']} file(s), {final_clean.get('action')}, "
              f"digest {str(final_clean['digest'])[:12]}"
              + f") -- "
              + ("ready as " if certification["certified"]
                 else "NOT CERTIFIED, inspect before use; ")
              + f"`setup --source {final_clean['path']}`")
    else:
        print(f"[decide] final clean version: NOT (re)built -- {final_clean.get('skipped')}")
    _zip = final_clean.get("zip") or {}
    if _zip.get("path"):
        print(f"[decide] final clean zip: {_zip['path']} "
              f"({_zip.get('files', '?')} file(s), {_zip.get('bytes', '?')} bytes); "
              f"the directory is kept")
    _hyg = final_clean.get("hygiene") or {}
    for r in (_hyg.get("internal_artifacts") or [])[:5]:
        print(f"[decide] PACKAGE HYGIENE (PKG-1, author action required): "
              f"{r.get('file')} line {r.get('line')} -- {r.get('evidence')}")
    for r in (_hyg.get("pdf_artifacts") or [])[:5]:
        print(f"[decide] PDF ARTIFACT ({r.get('rule')}, author action required): "
              f"{r.get('document')} -- {r.get('detail')}")
    for r in (_hyg.get("contradictions") or [])[:5]:
        print(f"[decide] PACKAGE CONTRADICTION ({r.get('rule')}, author action required): "
              f"{r.get('file')} -- {str(r.get('evidence'))[:180]}")
    _stripped = _hyg.get("stripped_bookkeeping") or []
    if _stripped:
        print(f"[decide] pipeline by-product(s) stripped from the published package: "
              + ", ".join(_stripped[:6]) + (" …" if len(_stripped) > 6 else ""))
    _wo = _hyg.get("removed_word_owner_files") or []
    if _wo:
        print(f"[decide] Word owner (lock) file(s) not published (a Word by-product, not a "
              f"document): " + ", ".join(_wo[:6]) + (" …" if len(_wo) > 6 else ""))
    _junk = _hyg.get("removed_platform_junk") or []
    if _junk:
        print(f"[decide] operating-system by-product(s) not published (a download/desktop "
              f"stub such as `<name>:Zone.Identifier`): " + ", ".join(_junk[:6])
              + (" …" if len(_junk) > 6 else ""))
    _pyc = _hyg.get("removed_bytecode_cache") or []
    if _pyc:
        print(f"[decide] Python bytecode cache(s) (`*.pyc`) not published (a side effect of "
              f"running a helper script, never a deliverable): " + ", ".join(_pyc[:6])
              + (" …" if len(_pyc) > 6 else ""))
    _held = _hyg.get("held_internal_readme_notes") or []
    if _held:
        print(f"[decide] {len(_held)} README file(s) carrying a revision session's own working "
              f"notes were held out of the published package (see "
              f"`reports/{README_NOTE_HOLD_DIRNAME}/`); the sibling readme names them")
    _ref = _hyg.get("removed_dangling_references") or {}
    if _ref.get("removed"):
        print(f"[decide] PKG-2: {_ref['removed']} sentence(s) referring to content this "
              f"submission does not carry were REMOVED from the to-be-submitted "
              f"document(s); the removed text is in "
              f"`final_clean_version.readme.md` and decision.json")
    if _ref.get("removed_links"):
        print(f"[decide] PKG-2: {_ref['removed_links']} attached-template link(s) pointing at "
              f"a path on somebody's own machine were REMOVED from the published package "
              f"(the venue's Word template carries one into every restyled package)")
    for r in (_ref.get("remaining") or [])[:5]:
        print(f"[decide] PKG-2 (author action required): {r.get('file')} line "
              f"{r.get('line')} -- `{r.get('reference')}` could not be removed "
              f"mechanically: {str(r.get('detail'))[:160]}")
    print(f"[decide] certification status: {readme_path} "
          f"({certification_label(certification)})")
    if win_token and win_token.get("token"):
        print(f"[decide] revision token (final winner): {win_token['token']} over "
              f"{win_token['files']} payload file(s); filename token(s) "
              f"{win_token['tokens_seen'] or '(none)'} -- "
              f"{'consistent' if win_token.get('consistent') else 'legacy/not applied'}")
    if problems:
        print("[decide] PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
    # A gate the operator enabled is a gate: `--format-gate` (HIGH-severity
    # OOXML findings in the final winner) and `--residual-gate` (the pipeline's
    # own unanswered items) both refuse to CERTIFY the decision. Without this
    # the flag only printed "not certified" in the report while exiting 0.
    # ONE source of truth: `certification` was computed above (before the clean
    # copy was published and before decision.json was written), so the file, the
    # report and this exit code can never disagree.
    if certification["exit_code"] == 5:
        print("[decide] exit 5: NOT CERTIFIED -- " + "; ".join(cert_blockers)
              + " (decision.json's `certification` block records the same blockers; "
                "the champion is not signed).")
        sys.exit(5)
    if certification["exit_code"] == 4:
        # The record's own notes carry the true reason (auto-promotion without a
        # panel is one); the old console branch asserted an incomplete round even
        # when all R rounds were complete.
        _reason = "; ".join(certification.get("notes") or [])
        print(f"[decide] exit 4: {_reason or 'the answer is provisional'} and "
              f"--require-complete was given; the answer is PROVISIONAL.")
        sys.exit(4)
    if args.require_clean_captions and not cap_ok:
        # Kept for CLI compatibility only. Caption length is the pipeline's own
        # SUGGESTION (and 0/off by default), handled exactly like the master
        # prompt's cover-letter word rule: it is reported, never enforced, so
        # there is deliberately no non-zero exit here.
        print("[decide] --require-clean-captions: caption length is advisory in this pipeline "
              "and can no longer fail a decision (see the NOTE above for the suggested-length "
              "report).")


def cmd_run_decide(args) -> None:
    """`run`, then `decide`, in series, honouring decide's flags.

    `run` holds the root lock for its whole phase and releases it when it
    returns; `decide` then takes the lock for its own writes (reports,
    decision.json, final_clean_version/). The digest cache stays OFF for that
    phase: it rewrites files it hashed, and a same-size rewrite inside one
    timestamp tick would otherwise reuse the stale digest (main() left the cache
    off because `run-decide` is not a read-only command). A hard error inside
    `run` (a `die()`) propagates and the decide phase is skipped -- deciding a
    root that could not even be started would only repeat the same error.
    """
    cmd_run(args)
    note = configure_hash_cache_for_command("decide", getattr(args, "root", None))
    if note:
        print(f"[run-decide] note: {note}")
    cmd_decide(args)

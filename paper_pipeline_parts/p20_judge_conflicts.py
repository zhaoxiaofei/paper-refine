# -*- coding: utf-8 -*-
# Part 20/23 of the pipeline -- judge-conflict audit, split from p12 to keep every part under 10,000 lines -- executed by the
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
# The sign is part of the value: "-12" and "12" are a real contradiction.
# A leading-dot decimal (".05") has no digit before the point; accept it as a
# numeric token too, or `p = .05` vs `p = .50` stays invisible.
_JUDGE_CONFLICT_NUMBER_RE = re.compile(
    r"(?<![\w.])([-\u2212]?(?:\d[\d,]*(?:\.\d+)?|\.\d+))")
# A small integer is a COUNT when the text marks it as one: "n = 5", "5
# samples", "12 patients". The magnitude floor below still drops a BARE small
# integer (a figure/check id, a section number, "Table 2"), but no longer every
# small sample size (wave-2 F261): "n = 5 samples" vs "n = 8 samples" is exactly
# the same-claim/different-number contradiction this scanner exists to surface.
_SMALL_COUNT_BEFORE_RE = re.compile(
    r"(?:\b(?:n|N)\s*=\s*|"
    r"\b(?:sample\s+size|count|number)\s*(?:=|is|of|:)?\s*|"
    r"\b(?:n|N)\s*)$")
_SMALL_COUNT_NOUN_RE = re.compile(
    r"\s*(?:samples?|patients?|participants?|subjects?|cells?|mice|rats?|"
    r"animals?|cases?|records?|observations?|sites?|replicates?|items?|units?|"
    r"reads?|specimens?|isolates?|strains?|individuals?|volunteers?|"
    r"respondents?|households?|events?|instances?)\b", re.I)


def _small_integer_is_count(text: str, match) -> bool:
    """True when a below-floor integer is marked as a count in its context."""
    before = text[max(0, match.start() - 24):match.start()]
    after = text[match.end():match.end() + 24]
    return bool(_SMALL_COUNT_BEFORE_RE.search(before)
                or _SMALL_COUNT_NOUN_RE.match(after))


def _conflict_numbers(text, floor: float = 10.0) -> set:
    """Quantitative numbers in a claim/message; ids and panel letters are skipped.

    The floor drops the small INTEGERS that come from check ids and figure
    letters ("M4", "Fig. 3d"), while keeping cell counts, read lengths and
    percentages (36, 50, 152, 170, 508, 1,307, ...). A DECIMAL or a percent
    token is kept at any magnitude: `p = 0.021` vs `p = 0.031` and `5%` vs
    `8%` are exactly the same-claim-different-number contradiction the scanner
    exists to surface, and the magnitude floor used to hide both (they are
    below 10 but are not ids). Figure/panel ids are integers, so the floor's
    false-positive job is unchanged.
    """
    text = str(text or "")
    out = set()
    for m in _JUDGE_CONFLICT_NUMBER_RE.finditer(text):
        tok = m.group(1).replace("\u2212", "-").rstrip(",").replace(",", "")
        try:
            v = float(tok)
        except ValueError:
            continue
        # The floor is a MAGNITUDE floor: a negative disagreement of the same
        # size is as reportable as its positive twin.
        is_decimal = "." in tok
        # Allow the space some manuscripts put before the sign.
        is_percent = bool(re.match(r"\s*%", text[m.end():]))
        if abs(v) >= float(floor) or is_decimal or is_percent:
            out.add(v if v != int(v) else int(v))
        elif _small_integer_is_count(text, m):
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
                        # EITHER side's tier decides: the mechanical severity
                        # must match the audit prompt, which makes a
                        # correctness- OR preservation-level inversion a
                        # blocker. Reading only the resolved row downgraded a
                        # preservation contradiction (and a mixed pair whose
                        # introduced row was the correctness one) to major.
                        tiers = {str(ri.get("tier") or "").lower(),
                                 str(ij.get("tier") or "").lower()}
                        hi = max(_conflict_item_severity(ri), _conflict_item_severity(ij))
                        severity = ("blocker"
                                    if (tiers & {"correctness", "preservation"}) and hi >= 2
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
                    # The old extra guard then dropped the singleton-vs-singleton
                    # case -- the most direct disagreement there is ("n=173
                    # samples" vs "n=508 samples") -- because both sets had one
                    # value (the 2026-10-28 audit's F44).
                    if nums_a <= nums_b or nums_b <= nums_a:
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
    return with_context_budget(CONTRADICTION_RULE + F"""You are the pipeline's cross-judge CONFLICT AUDITOR for round {int(r)}.

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
    # The CLI documents "default: 900, capped at 1800"; the old `max(60, ...)`
    # also raised every smaller caller timeout to 60 s, so a smoke probe could
    # not bound the session it asked for. Honour the request, keep only the
    # documented upper cap, and record both values on the run.
    seconds = min(int(timeout), 1800) if timeout is not None else 900
    res = _execute_attempt_in(sb, rec, [str(x) for x in cmd], seconds,
                              prompt_name="PROMPT.md", log_name="_agent.log",
                              archive_marker=False)
    info = {"used": True, "command": [str(x) for x in cmd], "rc": res.get("rc"),
            "error": res.get("error"), "duration": round(float(res.get("dur") or 0.0), 1),
            "timeout_requested": timeout, "timeout": seconds,
            "sandbox": str(sb)}
    data = read_json(answer, revive=False, lenient=True)
    if not isinstance(data, dict):
        info["error"] = info.get("error") or "the agent wrote no parseable conflicts.json"
        info["ok"] = False
        return [], info
    conflicts = _normalize_llm_conflicts(data)
    kept, rejected = _validate_llm_conflicts(conflicts, payload.get("opinions") or [])
    info["conflicts"] = len(kept)
    info["rejected_conflicts"] = len(rejected)
    if rejected:
        info["rejected"] = rejected[:10]
    info["ok"] = True
    return kept, info


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
    # `conflicts` is the one staged-audit command that accepts `--timeout`
    # without going through `_timeout_seconds` (conform/add-venue/the template
    # stage do). F10 now honours the requested value, so a negative one reaches
    # `communicate(timeout=-1)` and every session dies instantly as a bogus
    # "TIMEOUT after -1s"; refuse it here, the same usage error the `run` path
    # and `_timeout_seconds` raise (F12's non-negative invariant).
    if getattr(args, "timeout", None) is not None and args.timeout < 0:
        die("--timeout must be a non-negative number of seconds", code=2)
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
    # The AGGREGATION's own mode, not today's config: a round decided (or
    # re-decided) under an earlier `--dedup-mode` must keep the policy that
    # produced the merges this file documents. `agg` carries it from
    # aggregate_round; fall back to the live config only for a legacy payload
    # with no recorded mode.
    mode = agg.get("dedup_mode") or dedup_mode_of(ctx)
    return {"run": ctx.root.name, "round": int(r),
            "mode": mode,
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
        "ranking": "the ORDERED per-cell reported defect census over the adaptive "
                   "severity_tier_category prefix LEADS (each cell is its own lexicographic "
                   "rung, ascending; the cells are fatal -> critical -> major -> minor, tier by "
                   "tier in the scoring priority order, peer before own -- the SAME four "
                   "severity rungs the census, the judge contract and the score model use; the "
                   "walk stops when the cleanest ranked version reaches the "
                   "`tiebreak_defect_floor` or every cell is used), then the median of the "
                   "flat directed-score list, then the "
                   "arithmetic mean, the IQR and the content digest; an exact "
                   "(median, mean, IQR) tie still keeps the incumbent base",
        "cross_round_comparability": "per-round champion statistics come from different panels "
                                     "and different fields and are NOT comparable across rounds; "
                                     "the vs_base margin of the final round is the only paired "
                                     "statement the decision supports",
        "anti_regression_tolerance": VS_ORIGINAL_TOLERANCE,
        "anti_regression_rule": f"{vs_original_rule_of(ctx)} (setup --vs-original-rule "
                                f"median|sign; the rule this root actually applies); "
                                f"the sign rule fails only when the exact one-sided sign test "
                                f"over the pair's 2*judges directed scores is significant at "
                                f"{VS_ORIGINAL_ALPHA}; with so few scores NEITHER rule is "
                                f"well-powered, and every row reports its wins/losses/ties and p",
        "tiebreak_defect_floor": tiebreak_defect_floor_of(ctx),
        "dedup_mode": dedup_mode_of(ctx),
        "tiebreaks": ["ordered per-cell defect census over the adaptive "
                      "severity_tier_category prefix at the walk's stopping point, each cell a "
                      "separate lexicographic rung (fatal->critical->major->minor, tier order, "
                      "peer then own; the walk stops when the cleanest ranked version reaches "
                      "`tiebreak_defect_floor` or every cell is used), ascending",
                      "-median", "-mean", "IQR", "digest",
                      "the incumbent rule is applied before the prefix and digest on an exact "
                      "(median, mean, IQR) tie"],
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
                          "included; the ORDERED per-cell census at that prefix LEADS the "
                          "ranking -- each cell is compared in turn (the median, then the mean, "
                          "the IQR and the digest are the fallbacks below it), so a fatal "
                          "defect never ties the same total of minor ones; "
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
                           "every required check id, guided_review/artifacts/ must exist, finding ids "
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
    # An auto-promoted champion is PROVISIONAL by construction: the machine
    # verdict must agree with `certification_label`, not merely add a note
    # (F021).
    provisional = bool(provisional or auto_promoted)
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
    # AGENTS.md rule 5: an auto-promoted winner's label is always the mandated
    # one, whether or not a blocker also makes the decision NOT CERTIFIED. The
    # old `and not blockers` guard dropped the label exactly when the readme
    # most needed to say the bytes were never judged.
    if cert.get("auto_promoted"):
        return "AUTO-PROMOTED — PROVISIONAL (NOT JUDGED)"
    if cert.get("certified"):
        label = ("CERTIFIED (panel) — NOT SUBMISSION-READY"
                 if cert.get("submission_ready") is False else "CERTIFIED")
        if cert.get("guided_review_gap"):
            label += " (guided review off — named gap)"
        return label
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




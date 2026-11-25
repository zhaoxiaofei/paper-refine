# -*- coding: utf-8 -*-
# Part 24/25 of the pipeline -- executed by the loader, in order, in the
# loader's own module globals. Imports and names defined by earlier parts are
# therefore in scope exactly as they were in the single-file source.
from __future__ import annotations

# =====================================================================
# DELIVERABLE AUDITS: the generated concern ledger and the response to
# reviewers are LLM deliverables. Each is checked by an INDEPENDENT audit
# session (read-only, one disposition per element, no new findings) and then
# repaired by ONE separate session that re-validates every row before applying
# it. This is the same producer -> audit -> repair chain the revised manuscript
# already uses (`revision_audit` -> bounded repair), applied to the two journal
# deliverables that had no independent check.
#
# The two scoped modes (`major`/`minor`) admit HUMAN feedback only, so no
# LLM-review row can become a concern or a finding. That is enforced at the
# stream level in p02 (`"streams": ("human",)`) and re-proved here.
#
# These stages are ordinary planned runs (one sandbox each), not auxiliary
# sessions: the concern chain sits between `concerns` and `revise`; the response
# chain sits between `response` and the journal-submission assembly.
# =====================================================================

CONCERN_AUDIT_DIRNAME = "concern_audit"
CONCERN_AUDIT_JSON_REL = "concern_audit/CONCERN_AUDIT.json"
CONCERN_AUDIT_MD_REL = "concern_audit/CONCERN_AUDIT.md"
CONCERN_AUDIT_UNRESOLVED_REL = "concern_audit/UNRESOLVED.md"
CONCERN_AUDIT_COVERAGE_REL = "concern_audit/coverage.md"

CONCERN_REPAIR_DIRNAME = "concern_repair"
CONCERN_REPAIR_LEDGER_REL = "concern_repair/REPAIR_LEDGER.json"
CONCERN_REPAIR_LOG_REL = "concern_repair/REPAIR_LOG.md"

RESPONSE_AUDIT_DIRNAME = "response_audit"
RESPONSE_AUDIT_JSON_REL = "response_audit/RESPONSE_AUDIT.json"
RESPONSE_AUDIT_MD_REL = "response_audit/RESPONSE_AUDIT.md"
RESPONSE_AUDIT_UNRESOLVED_REL = "response_audit/UNRESOLVED.md"
RESPONSE_AUDIT_COVERAGE_REL = "response_audit/coverage.md"

RESPONSE_REPAIR_DIRNAME = "response_repair"
RESPONSE_REPAIR_LEDGER_REL = "response_repair/REPAIR_LEDGER.json"
RESPONSE_REPAIR_LOG_REL = "response_repair/REPAIR_LOG.md"

CONCERN_AUDIT_VERDICTS = ("confirmed", "defective", "dropped")
CONCERN_DEFECT_TYPES = ("not-human", "not-a-demand", "duplicate", "wrong-source",
                        "wrong-author", "wrong-quote", "wrong-disposition",
                        "wrong-location", "wrong-action", "wrong-summary",
                        "wrong-evidence", "other")
RESPONSE_DEFECT_TYPES = ("missing-answer", "unsupported-claim", "wrong-citation",
                         "non-verbatim-quote", "wrong-status", "overclaim",
                         "underclaim", "inconsistent-map", "non-human-concern",
                         "other")
REPAIR_VERDICTS = ("confirmed", "rejected")
REPAIR_ACTIONS = ("kept", "corrected", "merged", "dropped", "no-change")


def _deliverable_audit_policy(ctx, key: str) -> str:
    """`on` unless the root, the operator or the environment turned it off."""
    raw = str(os.environ.get("PAPER_" + key.upper())
              or (getattr(ctx, "cfg", None) or {}).get(key)
              or "on").strip().lower()
    return "off" if raw in {"off", "0", "no", "false", "none"} else "on"


def concern_audit_of(ctx) -> str:
    """The concern-audit/repair chain policy (major/minor only)."""
    return _deliverable_audit_policy(ctx, "concern_audit")


def response_audit_of(ctx) -> str:
    """The response-audit/repair chain policy (every mode with a response)."""
    return _deliverable_audit_policy(ctx, "response_audit")


def _audit_reason_ok(text, min_words: int = 4) -> bool:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(re.findall(r"\S+", t)) < int(min_words):
        return False
    try:
        if _reason_is_generic_filler(t):
            return False
    except Exception:                                            # noqa: BLE001
        pass
    return True


def _concern_source_rid(ctx: Ctx, r: int) -> str:
    """The run id that carries this root's concern ledger.

    Major/minor use the CONCERN-REPAIRED ledger when that stage ran; otherwise
    the generated ledger. Every other feedback mode uses the FEEDBACK ledger.
    """
    if journal_is_scoped(ctx):
        _rep = ctx.run(rid_concern_repair(r))
        return (rid_concern_repair(r)
                if _rep is not None and _rep.get("status") == "done"
                else rid_concerns(r))
    return rid_feedback(r)


def _journal_concern_source(ctx: Ctx, r: int) -> Path:
    """The sandbox that carries the concern ledger for this round."""
    rid = _concern_source_rid(ctx, r)
    _require_done(ctx, rid, "the concern ledger is the input of this stage")
    return ctx.sandbox_of(ctx.run(rid))


def response_comment_verifies(ctx, sb: Path, row, comment: str, concern_quote: str) -> bool:
    """The letter's Comment must be the ledger quote AND verbatim human text.

    A shorter excerpt of the verified quote is allowed. A LONGER human quote is
    allowed only for a human-only concern, and only when the whole comment is
    verbatim in the human text and still contains the concern's quote: that
    cannot smuggle in invented reviewer words. For an LLM-containing row the
    strict (comment-within-quote) rule stands.
    """
    if response_comment_is_verbatim(comment, concern_quote):
        return response_comment_human_verbatim(ctx, sb, row, comment)
    if _concern_names_llm(sb, row):
        return False
    q = " ".join(str(concern_quote or "").split())
    c = " ".join(str(comment or "").split())
    return bool(q and c and _human_boundary_contains(c, q)
                and response_comment_human_verbatim(ctx, sb, row, comment))


def _human_boundary_contains(hay: str, needle: str) -> bool:
    """A case- and punctuation-sensitive span on word boundaries."""
    if not needle:
        return False
    pos = hay.find(needle)
    while pos >= 0:
        before = hay[pos - 1] if pos else ""
        end = pos + len(needle)
        after = hay[end] if end < len(hay) else ""
        if not (before.isalnum() or before == "_") \
                and not (after.isalnum() or after == "_"):
            return True
        pos = hay.find(needle, pos + 1)
    return False


def _concern_names_llm(sb: Path, row) -> bool:
    llm_dir = sb / "feedback" / "llm" / "files"
    llm_names = ([p.name for p in sorted(llm_dir.iterdir())
                  if p.is_file() and not p.is_symlink()] if llm_dir.is_dir() else [])
    srcs = [t.strip() for t in re.split(r"\s*;\s*|\s+\+\s+",
                                          str((row or {}).get("source") or ""))
            if t.strip()]
    return any(_name_matches(tok, llm_names) for tok in srcs)


def response_comment_human_verbatim(ctx, sb: Path, row, comment: str) -> bool:
    """Is the letter's Comment a verbatim span of the HUMAN feedback?

    The ledger quote is already verified, but the LETTER is the deliverable a
    reviewer reads: the quotation must preserve the reviewer's own typo, wrong
    punctuation and capitalization rather than a cleaned-up version. Only human
    feedback files are searched; an LLM-only concern (unscoped modes) has no
    human text to bind and the ledger's own quote check stands.
    """
    tdir = sb / "feedback" / "text"
    if not tdir.is_dir():
        return True
    human_names = _staged_human_names(sb)
    srcs = [t.strip() for t in re.split(r"\s*;\s*|\s+\+\s+",
                                          str((row or {}).get("source") or ""))
            if t.strip()]
    # A concern that names ANY LLM-review file is not a human-only row (the
    # ledger's own quote check governs it); do not demand its text in the human
    # stream. Otherwise the row must name a staged human file, and the comment
    # must occur verbatim in the human text.
    if _concern_names_llm(sb, row):
        return True
    if not any(_name_matches(tok, human_names) for tok in srcs):
        return True
    c_norm = " ".join(str(comment or "").split())
    if not c_norm:
        return False
    for p in sorted(tdir.glob("*.txt")):
        text = read_text_bounded(p)
        if text is None:
            continue
        if _human_boundary_contains(" ".join(text.split()), c_norm):
            return True
    return False


def _concern_ids(sb: Path) -> list:
    return [str(r.get("id") or "") for r in journal_concern_rows(sb)
            if str(r.get("id") or "")]


def _rows_by_id(rows) -> dict:
    return {str(r.get("id") or ""): r for r in (rows or []) if isinstance(r, dict)}


def _staged_human_names(sb: Path) -> list:
    """The regular human feedback files staged under feedback/files/."""
    d = sb / "feedback" / "files"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        try:
            if p.is_file() and not p.is_symlink():
                out.append(p.name)
        except OSError:
            continue
    return out


def _name_matches(cell: str, names) -> bool:
    """Does a ledger/coverage spelling name one of these staged files?

    The staged name is the corpus LABEL with `/` flattened to `__`
    (`human_review_feedback/editor.txt` -> `human_review_feedback__editor.txt`),
    while a ledger may cite the corpus label, its basename or the staged name.
    Matching the flattened tail is what makes the human/LLM stream resolution
    and the coverage gate work on real roots, not only on flat fixtures.
    """
    low = str(cell or "").strip().lower()
    if not low:
        return False
    for name in names:
        n = str(name).lower()
        variants = {n}
        if "/" in n:
            variants.add(n.rsplit("/", 1)[-1])
        if "." in n:
            variants.add(n.rsplit(".", 1)[0])
            if "/" in n:
                variants.add(n.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        if "__" in n:
            base = n.rsplit("__", 1)[-1]
            variants.add(base)
            if "." in base:
                variants.add(base.rsplit(".", 1)[0])
        if any(low == v or low.endswith("/" + v) for v in variants if v):
            return True
    return False


def _coverage_problems(rows, required_files, rel: str) -> list:
    """Every staged human feedback file needs its own examined row."""
    errs = []
    coverage = [r for r in (rows or []) if isinstance(r, dict)]
    if not coverage:
        return [f"{rel}: the audit carries no coverage rows; one row per human "
                f"feedback file is required"]
    for name in required_files:
        if not any(_name_matches(r.get("file") or r.get("area") or "", [name])
                   for r in coverage):
            errs.append(f"{rel}: no coverage row names the staged human feedback file "
                        f"{name!r}")
    for r in coverage:
        examined = r.get("examined")
        if isinstance(examined, str) and examined.strip().isdigit():
            examined = int(examined.strip())
        if not isinstance(examined, int) or examined < 0:
            errs.append(f"{rel}: a coverage row's `examined` must be a non-negative "
                        f"integer (got {r.get('examined')!r})")
        if not str(r.get("note") or "").strip():
            errs.append(f"{rel}: a coverage row carries no `note` (say what was checked)")
    return errs


def _defect_problems(defects, allowed, rel: str, cid: str,
                     correction_required: bool) -> list:
    errs = []
    rows = [d for d in (defects or []) if isinstance(d, dict)]
    if not rows:
        return [f"{rel}: concern {cid}: a defect verdict needs at least one `defects` row"]
    for i, d in enumerate(rows, 1):
        typ = str(d.get("type") or "").strip()
        if typ not in allowed:
            errs.append(f"{rel}: concern {cid} defect {i}: type {typ!r} is not one of "
                        f"{', '.join(allowed)}")
            continue
        if not str(d.get("basis") or "").strip():
            errs.append(f"{rel}: concern {cid} defect {i}: `basis` is empty (the "
                        f"file/line/quote a different session can re-run)")
        if typ in ("duplicate",):
            if not str(d.get("correct") or "").strip():
                errs.append(f"{rel}: concern {cid} defect {i}: a duplicate needs the "
                            f"surviving concern id in `correct`")
        elif typ in ("not-human", "not-a-demand"):
            # A drop has no replacement value; the evidence is the basis.
            pass
        elif correction_required:
            if not str(d.get("wrong") or "").strip():
                errs.append(f"{rel}: concern {cid} defect {i}: `wrong` is empty (quote "
                            f"the exact current value)")
            if not str(d.get("correct") or "").strip():
                errs.append(f"{rel}: concern {cid} defect {i}: `correct` is empty (the "
                            f"exact replacement the repair applies)")
    return errs


# ---------------------------------------------------------------------
# CONCERN AUDIT
# ---------------------------------------------------------------------

def concern_audit_prompt(ctx: Ctx, sb: Path, r: int) -> str:
    ids = _concern_ids(sb)
    return CONTRADICTION_RULE + f"""CONCERN AUDIT — independent check of the generated concern ledger
(round {int(r)}; read-only. You did NOT write this ledger.)

Your sandbox:
  base/                    the manuscript the feedback is about (read-only)
  non_revised/             the pristine original (read-only)
  concerns/                the generated ledger JF_concerns.json|md + SEED_COVERAGE.md
                           (READ-ONLY: this is the artifact you audit)
  guided_review/findings.json  the JF finding list derived from that ledger (READ-ONLY)
  feedback/files/          the ORIGINAL human feedback files (read-only)
  feedback/text/           the same files as plain text; quote from THIS
  feedback/original_submission/  the reviewer-visible earlier manuscript, when present
                           (EVIDENCE only)
  concern_audit/           YOUR OUTPUT DIR

A concern-scoped (major/minor) revision may answer ONLY what a HUMAN reviewer
raised. The LLM review is not a concern source in this mode and is not staged.
Every ledger row's quote was already checked mechanically for verbatim
occurrence; your job is the part a mechanical check cannot do: is the quoted
span actually a HUMAN reviewer's demand, and are the row's attribution,
disposition, location and finding mapping right?

TASK — dispose EVERY concern id, exactly once, and generate NO new concern:
{', '.join(ids) if ids else '(the ledger lists no concerns)'}

For each id choose one verdict:
  * `confirmed`  — no defect: the concern is a human reviewer's demand, the quote
    is a VERBATIM human text span (typos, wrong punctuation and capitalization
    preserved — never corrected), the author/source are supported, the
    disposition is defensible, and the JF finding (if any) is correct.
  * `defective`  — the concern IS human-raised, but one or more fields need
    correction. List one `defects` row per defect, with the exact current value
    (`wrong`), the exact replacement (`correct`) and the basis.
  * `dropped`    — the row is not a human reviewer's demand. A `dropped` row also
    carries at least one `defects` row explaining why.

Defect types:
  not-human          — the quote/source is not a human feedback file (should not
                       occur in this mode; record it if it does)
  not-a-demand       — the quote is verbatim but is background, thanks, a
                       previous-response promise, or otherwise not a reviewer demand
  duplicate          — the same demand as another row; `correct` is the surviving id
  wrong-source       — the source cell names the wrong human file
  wrong-quote        — the quote was cleaned up or altered (typo/punctuation/
                       capitalization changed); `correct` is the exact human span
  wrong-author       — the reviewer/editor attribution is not supported
  wrong-disposition  — to-fix / already-addressed / manual / not-applicable is wrong
  wrong-location     — the base/ location does not carry the concern, or is only
                       in original_submission/
  wrong-action       — text / analysis / new-experiment / clarification / formatting /
                       policy / disagree is wrong
  wrong-summary      — the summary misstates the demand
  wrong-evidence     — evidence_needed is missing or wrong
  other              — say exactly what

`already-addressed` must name a base/ location that actually answers the concern.
`not-applicable` must give a real rationale. `manual` must be a real author action.
`to-fix` must have a location in the CURRENT base/. A concern that only exists in
feedback/original_submission/ is already-addressed or not-applicable, never to-fix.

A DEFECT YOU NOTICE OUTSIDE THE LEDGER (a manuscript problem, a non-human item,
a broken quote you cannot correct, an evidence file you cannot read) goes to
`concern_audit/UNRESOLVED.md` as ONE line with its location and re-runnable
evidence. It is NOT a finding, NOT a new concern, and the repair will not act on
it. Do not add an `AU-*`/`CA-*` row.

WRITE:
  * concern_audit/CONCERN_AUDIT.json — exactly:
    {{"round": {int(r)},
      "rows": [{{"id": "R1-1",
                 "verdict": "confirmed|defective|dropped",
                 "defects": [{{"type": "<above>", "wrong": "...", "correct": "...",
                               "basis": "<file:line, verbatim quote, or re-runnable check>"}}],
                 "reason": "<<= 60 words>",
                 "evidence": "<<= 40 words: what you re-read or re-ran>"}}],
      "coverage": [{{"file": "<feedback/files/...>", "examined": 0, "defects": 0,
                     "note": "what you checked"}}],
      "notes": "..."}}
    ONE row per ledger id, no extras, no duplicates.
  * concern_audit/CONCERN_AUDIT.md — the same, human-readable.
  * concern_audit/coverage.md — one coverage row per staged human feedback file
    (use the file's staged name) plus what you could not check.
  * concern_audit/UNRESOLVED.md — observations (write "none" when there are none).

Do NOT edit base/, non_revised/, concerns/, guided_review/ or feedback/. Do NOT
write a repaired ledger, a finding list or a response letter here.

{marker_root_rule()}
Write `_pipeline_done.json` (JSON: stage "concern_audit", run_id "{sb.name}",
round {int(r)}, status "complete", confirmed N, defective N, dropped N) as the
very LAST step.
"""


def materialize_concern_audit(ctx: Ctx, r: int) -> dict:
    rid = rid_concern_audit(r)
    con_rec = _require_done(ctx, rid_concerns(r),
                            "the concern audit consumes the generated concern ledger")
    a1 = ctx.run(rid_a1(r))
    if a1 is None or a1.get("status") != "done":
        raise RuntimeError(f"cannot materialize {rid}: {rid_a1(r)} is not done")
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    ensure_copy(ctx.sandbox_of(a1) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    src = ctx.sandbox_of(con_rec)
    ensure_copy(src / "concerns", sb / "concerns")
    ensure_copy(src / GUIDED_REVIEW_DIR, sb / GUIDED_REVIEW_DIR)
    if (src / "feedback").is_dir():
        ensure_copy(src / "feedback", sb / "feedback")
    safe_mkdir(sb / CONCERN_AUDIT_DIRNAME)
    note = prior_failure_block(ctx.run(rid) or {}, sb) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt,
                          ensure_external_content_rule(
                              concern_audit_prompt(ctx, sb, r) + note + shared_blocks()))
    rec = ctx.register(rid, "concern_audit", r, f"runs/{rid}",
                       upstream_run_id=rid_concerns(r))
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR,
                                                          follow_dir_links=True),
                              "concerns": hash_manifest(sb / "concerns"),
                              "guided_review": hash_manifest(sb / GUIDED_REVIEW_DIR)}
    if (sb / "feedback").is_dir():
        rec["inputs_manifest"]["feedback"] = hash_manifest(sb / "feedback",
                                                          follow_dir_links=True)
    return rec


def _concern_location_ids(rows) -> set:
    """Ids whose to-fix/already-addressed location names the evidence copy."""
    out = set()
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        disp = str(row.get("disposition") or "")
        if disp not in ("to-fix", "already-addressed"):
            continue
        loc = str(row.get("manuscript_location") or "")
        if re.search(r"(?i)(?:^|/)original_submission/", loc):
            out.add(str(row.get("id") or ""))
    return out


def _concern_location_problems(rows) -> list:
    """A to-fix/already-addressed location must live in the CURRENT base."""
    return [f"concern {cid!r}: a to-fix/already-addressed location names "
            f"feedback/original_submission/ (evidence, not the current base/)"
            for cid in sorted(_concern_location_ids(rows))]


def concern_audit_artifact_problems(audit, concern_ids, sb: Path) -> list:
    errs = []
    if not isinstance(audit, dict):
        return [f"{CONCERN_AUDIT_JSON_REL} does not parse as a JSON object"]
    rows = [r for r in (audit.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return [f"{CONCERN_AUDIT_JSON_REL} carries no disposition rows; one row per concern "
                f"id is required (silence is not allowed)"]
    want = [str(x) for x in concern_ids]
    got = [str(r.get("id") or "") for r in rows]
    dups = sorted({x for x in got if x and got.count(x) > 1})
    if dups:
        errs.append(f"{CONCERN_AUDIT_JSON_REL}: concern id(s) appear more than once: "
                    f"{', '.join(dups[:6])}")
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    if missing:
        errs.append(f"{CONCERN_AUDIT_JSON_REL} does not dispose {len(missing)} concern(s): "
                    f"{', '.join(missing[:6])}")
    if extra:
        errs.append(f"{CONCERN_AUDIT_JSON_REL} names {len(extra)} row(s) that are not ledger "
                    f"concerns: {', '.join(extra[:6])} (the audit generates no new concern)")
    for row in rows:
        cid = str(row.get("id") or "")
        verdict = str(row.get("verdict") or "").strip()
        if verdict not in CONCERN_AUDIT_VERDICTS:
            errs.append(f"concern {cid}: verdict {verdict!r} must be one of "
                        f"{', '.join(CONCERN_AUDIT_VERDICTS)}")
            continue
        if not _audit_reason_ok(row.get("reason")):
            errs.append(f"concern {cid}: `reason` is empty/filler; name the evidence checked")
        if not str(row.get("evidence") or "").strip():
            errs.append(f"concern {cid}: `evidence` is empty (a location, verbatim quote or "
                        f"re-runnable check)")
        defects = [d for d in (row.get("defects") or []) if isinstance(d, dict)]
        _types = {str(d.get("type") or "").strip() for d in defects}
        if verdict == "dropped":
            _bad = _types - {"not-human", "not-a-demand"}
            if _bad:
                errs.append(f"concern {cid}: a dropped concern may only be dropped for "
                            f"not-human/not-a-demand, not "
                            f"{', '.join(sorted(_bad))} (a human-raised field defect is "
                            f"`defective`, not `dropped`)")
        if verdict == "defective" and (_types & {"not-human", "not-a-demand"}):
            errs.append(f"concern {cid}: a 'defective' concern must be human-raised; use "
                        f"'dropped' for not-human/not-a-demand")
        if verdict == "confirmed" and defects:
            errs.append(f"concern {cid}: verdict 'confirmed' must carry no defects")
        elif verdict in ("defective", "dropped"):
            errs.extend(_defect_problems(
                defects, CONCERN_DEFECT_TYPES, CONCERN_AUDIT_JSON_REL, cid,
                correction_required=(verdict == "defective")))
        if verdict == "dropped":
            # A dropped row must name why it is not a human demand; the defect
            # list is mandatory above, and a bare "duplicate" needs its target.
            pass
    errs.extend(_coverage_problems(audit.get("coverage"), _staged_human_names(sb),
                                   CONCERN_AUDIT_JSON_REL))
    return errs


def postcheck_concern_audit(ctx: Ctx, rec: dict):
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "concern_audit", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    errs.extend(original_submission_staging_problems(ctx, sb))
    # The frozen ledger is the object under audit: its own contract must hold
    # before a disposition can mean anything (verbatim quote, seed coverage,
    # human-only source, schema).
    data = journal_ledger_problems(ctx, sb, errs, warns, require_seed=True)
    ids = [str(x.get("id")) for x in (data.get("concerns") or [])
           if isinstance(x, dict) and str(x.get("id") or "")]
    aj = sb / CONCERN_AUDIT_JSON_REL
    if not aj.is_file():
        errs.append(f"{CONCERN_AUDIT_JSON_REL} is missing: the audit's dispositions are the "
                    f"deliverable the repair consumes")
    else:
        audit = read_json(aj, revive=False, lenient=True)
        problems = concern_audit_artifact_problems(audit, ids, sb)
        if isinstance(audit, dict):
            _by_id = _rows_by_id(data.get("concerns"))
            _unverified = set(data.get("unverified_authors") or [])
            _bad_loc = _concern_location_ids(data.get("concerns"))
            for _r in (audit.get("rows") or []):
                if not isinstance(_r, dict):
                    continue
                _cid = str(_r.get("id") or "")
                _verdict = str(_r.get("verdict"))
                if _verdict not in ("confirmed", "defective", "dropped"):
                    continue
                _row = _by_id.get(_cid) or {}
                _types = {str(d.get("type") or "").strip()
                          for d in (_r.get("defects") or []) if isinstance(d, dict)}
                _author_bad = (not str(_row.get("author") or "").strip()
                               or _cid in _unverified)
                if _verdict == "confirmed" and _author_bad:
                    problems.append(f"concern {_cid}: the audit confirmed a row whose "
                                    f"`author` is empty/unsupported; dispose the attribution")
                if _verdict == "defective" and _author_bad and "wrong-author" not in _types:
                    problems.append(f"concern {_cid}: the frozen author is empty/unsupported; "
                                    f"a defective disposition must carry a `wrong-author` "
                                    f"defect (the repair cannot fix an un-audited field)")
                if _verdict == "confirmed" and _cid in _bad_loc:
                    problems.append(f"concern {_cid}: the audit confirmed a to-fix/"
                                    f"already-addressed location that names "
                                    f"feedback/original_submission/; dispose it")
                if _verdict == "defective" and _cid in _bad_loc \
                        and "wrong-location" not in _types:
                    problems.append(f"concern {_cid}: the frozen location names "
                                    f"feedback/original_submission/; a defective disposition "
                                    f"must carry a `wrong-location` defect (the repair cannot "
                                    f"fix an un-audited field)")
        errs.extend(problems)
        if not problems and isinstance(audit, dict):
            rows = [r for r in (audit.get("rows") or []) if isinstance(r, dict)]
            rec["concern_audit"] = {
                "rows": len(rows),
                "confirmed": sum(1 for r in rows if str(r.get("verdict")) == "confirmed"),
                "defective": sum(1 for r in rows if str(r.get("verdict")) == "defective"),
                "dropped": sum(1 for r in rows if str(r.get("verdict")) == "dropped"),
            }
            if rec["concern_audit"]["dropped"]:
                warns.append(f"the concern audit dropped {rec['concern_audit']['dropped']} "
                             f"generated concern(s); the repair will remove them unless it "
                             f"independently rejects the drop")
    if not (sb / CONCERN_AUDIT_MD_REL).is_file():
        warns.append(f"{CONCERN_AUDIT_MD_REL} (the human-readable disposition record) is "
                     f"missing")
    unresolved = sb / CONCERN_AUDIT_UNRESOLVED_REL
    if unresolved.is_symlink() or (unresolved.exists() and not unresolved.is_file()):
        errs.append(f"{CONCERN_AUDIT_UNRESOLVED_REL} is a symlink or not a regular file")
    elif not unresolved.is_file():
        errs.append(f"{CONCERN_AUDIT_UNRESOLVED_REL} is missing (write 'none' when there "
                    f"are no observations)")
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


# ---------------------------------------------------------------------
# CONCERN REPAIR
# ---------------------------------------------------------------------

def concern_repair_prompt(ctx: Ctx, sb: Path, r: int) -> str:
    ids = _concern_ids(sb)
    return CONTRADICTION_RULE + f"""CONCERN REPAIR — apply the independent concern audit (one pass,
round {int(r)}; you do NOT revise the manuscript)

Your sandbox:
  base/                    the manuscript the concerns are about (read-only)
  non_revised/             the pristine original (read-only)
  concerns/                the generated ledger (EDITABLE OUTPUT)
  guided_review/           the JF finding list + artifacts (EDITABLE OUTPUT)
  feedback/                the human feedback files + text (read-only)
  concern_audit/           the audit's CONCERN_AUDIT.json + evidence (READ-ONLY)
  concern_repair/          YOUR OUTPUT DIR

You are a FINDING-CONSUMING session: the audit's rows are your inputs, never a
substitute for re-verification (rule 1B). For EVERY audit row, re-open the named
concern, the quoted location and the human feedback, decide `confirmed` or
`rejected`, and record the verdict BEFORE editing. Only confirmed defects are
applied. A rejected audit row is left as it was and recorded.

WHAT YOU MAY CHANGE:
  * Correct a confirmed `defective` concern in `concerns/JF_concerns.json|md`:
    source/author (to a staged human file), quote, disposition, location,
    action, summary, evidence_needed. The quote must stay VERBATIM in the named
    human file, preserving the reviewer's typos, wrong punctuation and
    capitalization; if the audit proposes a replacement quote, re-locate it in
    the human text before applying it. Never "fix" a reviewer's prose.
  * Drop a confirmed `dropped` concern (and its JF finding).
  * Merge a confirmed `duplicate`: keep the surviving id, add the dropped row's
    source to the survivor's `source`, remove the duplicate row.
  * Regenerate `guided_review/findings.json`, `guided_review/findings.md` and
    `guided_review/artifacts/JF_concerns.md` EXACTLY from the repaired ledger:
    ONE JF finding per `to-fix`/`manual` concern, no other finding. Keep the
    finding list's `coverage` rows (scope, and LLM-pre-filter only when that
    stream is present); they are not concern findings.
  * Update `concerns/SEED_COVERAGE.md` so every seeded block is still disposed:
    a block that only mapped to a dropped concern becomes
    `skipped — dropped by the concern audit: <reason>` (or is remapped to the
    surviving concern); never leave a seed id naming a removed concern.

WHAT YOU MAY NOT DO:
  * add a concern, a finding, a quote or a reviewer sentence that is not already
    a HUMAN reviewer's demand;
  * change `base/`, `feedback/`, `concern_audit/` or the manuscript;
  * change a concern's provenance to a non-human source;
  * apply a correction the audit did not propose, or invent a replacement value.

If there is nothing to apply, copy the ledger/finding list unchanged and write
ONE `no-change` row per audit id (an empty `rows` list is a FAILED repair: every
audit row must be accounted for).

WRITE:
  * concern_repair/REPAIR_LEDGER.json:
    {{"round": {int(r)},
      "rows": [{{"id": "R1-1",
                 "audit_verdict": "confirmed|defective|dropped",
                 "verdict": "confirmed|rejected",
                 "action": "kept|corrected|merged|dropped|no-change",
                 "reason": "...", "evidence": "..."}}],
      "counts": {{"input": N, "kept": N, "corrected": N, "merged": N, "dropped": N,
                  "rejected": N}},
      "notes": "..."}}
    ONE row per audit id, no extras.
  * concern_repair/REPAIR_LOG.md — the human-readable record, including every
    rejected audit row and what was left in place.

{marker_root_rule()}
Write `_pipeline_done.json` (JSON: stage "concerns", run_id "{sb.name}",
round {int(r)}, status "complete") as the very LAST step (stage "concerns" is the
deliverable's contract; this run is its repair).
"""


def materialize_concern_repair(ctx: Ctx, r: int) -> dict:
    rid = rid_concern_repair(r)
    con_rec = _require_done(ctx, rid_concerns(r),
                            "the concern repair edits the generated concern ledger")
    aud_rec = _require_done(ctx, rid_concern_audit(r),
                            "the concern repair consumes the independent concern audit")
    a1 = ctx.run(rid_a1(r))
    if a1 is None or a1.get("status") != "done":
        raise RuntimeError(f"cannot materialize {rid}: {rid_a1(r)} is not done")
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    ensure_copy(ctx.sandbox_of(a1) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    src = ctx.sandbox_of(con_rec)
    ensure_copy(src / "concerns", sb / "concerns")
    ensure_copy(src / GUIDED_REVIEW_DIR, sb / GUIDED_REVIEW_DIR)
    if (src / "feedback").is_dir():
        ensure_copy(src / "feedback", sb / "feedback")
    ensure_copy(ctx.sandbox_of(aud_rec) / CONCERN_AUDIT_DIRNAME,
                sb / CONCERN_AUDIT_DIRNAME)
    safe_mkdir(sb / CONCERN_REPAIR_DIRNAME)
    note = prior_failure_block(ctx.run(rid) or {}, sb) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt,
                          ensure_external_content_rule(
                              concern_repair_prompt(ctx, sb, r) + note + shared_blocks()))
    rec = ctx.register(rid, "concern_repair", r, f"runs/{rid}",
                       upstream_run_id=rid_concern_audit(r))
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR,
                                                          follow_dir_links=True),
                              "concern_audit": hash_manifest(sb / CONCERN_AUDIT_DIRNAME)}
    if (sb / "feedback").is_dir():
        rec["inputs_manifest"]["feedback"] = hash_manifest(sb / "feedback",
                                                          follow_dir_links=True)
    # The original ledger/finding list the repair starts from (these paths are
    # OUTPUTS in this sandbox, so they cannot sit in inputs_manifest).
    rec["concern_repair_source"] = {
        "concerns": hash_manifest(src / "concerns"),
        "guided_review": hash_manifest(src / GUIDED_REVIEW_DIR),
    }
    return rec


def concern_repair_ledger_problems(sb: Path, audit, original_rows, repaired_rows) -> list:
    errs = []
    path = sb / CONCERN_REPAIR_LEDGER_REL
    if not path.is_file():
        return [f"{CONCERN_REPAIR_LEDGER_REL} is missing: the repair's per-row verdicts are "
                f"the record a different session re-checks"]
    doc = read_json(path, revive=False, lenient=True)
    if not isinstance(doc, dict):
        return [f"{CONCERN_REPAIR_LEDGER_REL} does not parse as a JSON object"]
    rows = [r for r in (doc.get("rows") or []) if isinstance(r, dict)]
    audit_rows = _rows_by_id((audit or {}).get("rows") if isinstance(audit, dict) else [])
    orig = _rows_by_id(original_rows)
    new = _rows_by_id(repaired_rows)
    got = [str(r.get("id") or "") for r in rows]
    want = list(audit_rows)
    dups = sorted({x for x in got if x and got.count(x) > 1})
    if dups:
        errs.append(f"{CONCERN_REPAIR_LEDGER_REL}: id(s) appear more than once: "
                    f"{', '.join(dups[:6])}")
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    if missing:
        errs.append(f"{CONCERN_REPAIR_LEDGER_REL} does not account for {len(missing)} audit "
                    f"row(s): {', '.join(missing[:6])}")
    if extra:
        errs.append(f"{CONCERN_REPAIR_LEDGER_REL} names {len(extra)} row(s) the audit never "
                    f"disposed: {', '.join(extra[:6])}")
    for row in rows:
        cid = str(row.get("id") or "")
        verdict = str(row.get("verdict") or "").strip()
        action = str(row.get("action") or "").strip()
        if verdict not in REPAIR_VERDICTS:
            errs.append(f"repair row {cid!r}: verdict {verdict!r} must be confirmed/rejected")
            continue
        if action not in REPAIR_ACTIONS:
            errs.append(f"repair row {cid!r}: action {action!r} must be one of "
                        f"{', '.join(REPAIR_ACTIONS)}")
        if not _audit_reason_ok(row.get("reason")):
            errs.append(f"repair row {cid!r}: `reason` is empty/filler; name the evidence "
                        f"you re-checked")
        if not str(row.get("evidence") or "").strip():
            errs.append(f"repair row {cid!r}: `evidence` is empty")
        if verdict == "rejected" and new.get(cid) != orig.get(cid):
            errs.append(f"repair row {cid!r}: a rejected audit row must be left unchanged")
        if verdict == "confirmed" and action in ("kept", "no-change") \
                and new.get(cid) != orig.get(cid):
            errs.append(f"repair row {cid!r}: a no-change/kept row must be byte-identical to "
                        f"the generated concern")
        av = str((audit_rows.get(cid) or {}).get("verdict") or "")
        if av == "dropped":
            if verdict == "confirmed":
                if cid in new:
                    errs.append(f"repair row {cid!r}: the audit dropped this concern and the "
                                f"repair confirmed the drop, but the repaired ledger still "
                                f"carries it")
                if action not in ("dropped",):
                    errs.append(f"repair row {cid!r}: a confirmed drop must record action "
                                f"'dropped'")
            elif verdict == "rejected" and cid not in new:
                errs.append(f"repair row {cid!r}: the repair rejected the audit's drop, so the "
                            f"concern must remain in the repaired ledger")
        elif av in ("confirmed", "defective"):
            if cid not in new:
                errs.append(f"repair row {cid!r}: the audit did not drop this concern, but the "
                            f"repaired ledger lost it")
            if action == "dropped":
                errs.append(f"repair row {cid!r}: the audit did not drop this concern; the "
                            f"repair may not drop it on its own")
            if av == "confirmed" and verdict == "confirmed" and action in ("corrected", "merged"):
                errs.append(f"repair row {cid!r}: the audit found no defect, so the repair may "
                            f"not correct or merge the row")
            if av == "defective" and verdict == "confirmed" and action in ("no-change", "kept"):
                errs.append(f"repair row {cid!r}: the audit found a defect and the repair "
                            f"confirmed it; record `corrected` (or reject the audit row)")
            _defs = [d for d in ((audit_rows.get(cid) or {}).get("defects") or [])
                     if isinstance(d, dict)]
            _dups = [d for d in _defs if str(d.get("type")) == "duplicate"]
            if _dups and verdict == "confirmed" and action != "merged":
                errs.append(f"repair row {cid!r}: the audit found a duplicate; a confirmed "
                            f"repair must record action 'merged'")
            if action == "merged":
                if not _dups:
                    errs.append(f"repair row {cid!r}: action 'merged' needs an audited "
                                f"duplicate defect")
                for _d in _dups:
                    _keep = str(_d.get("correct") or "").strip()
                    if cid in new:
                        errs.append(f"repair row {cid!r}: the merged duplicate is still in "
                                    f"the repaired ledger")
                    if _keep and _keep not in new:
                        errs.append(f"repair row {cid!r}: the duplicate's surviving id "
                                    f"{_keep!r} is absent from the repaired ledger")
    for cid in sorted(set(new) - set(orig)):
        errs.append(f"the repaired ledger added concern {cid!r}: the repair may not invent a "
                    f"concern")
    return errs


def postcheck_concern_repair(ctx: Ctx, rec: dict):
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "concerns", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    errs.extend(original_submission_staging_problems(ctx, sb))
    # The repaired ledger and finding list must satisfy the SAME contract as the
    # generated ones; the repair cannot loosen it.
    data = journal_ledger_problems(ctx, sb, errs, warns, require_seed=True)
    errs.extend(_concern_location_problems(data.get("concerns")))
    for _row in (data.get("concerns") or []):
        if isinstance(_row, dict) and not str(_row.get("author") or "").strip():
            errs.append(f"concern {_row.get('id')!r}: the repaired ledger still has an empty "
                        f"`author`; the repair must dispose the attribution")
    if data.get("unverified_authors"):
        errs.append("the repaired ledger still has an author the cited source does not "
                    "support: " + ", ".join(str(x) for x in data["unverified_authors"][:6]))
    ferrs, fwarns, counts = concerns_finding_list_problems(sb, data)
    errs.extend(ferrs)
    warns.extend(fwarns)
    con_rec = ctx.run(rid_concerns(rec.get("round")))
    aud_rec = ctx.run(rid_concern_audit(rec.get("round")))
    if con_rec is None or aud_rec is None:
        errs.append("the concern-repair postcheck cannot find the generated ledger or the "
                    "audit it consumed")
    else:
        original = journal_concern_rows(ctx.sandbox_of(con_rec))
        audit = read_json(ctx.sandbox_of(aud_rec) / CONCERN_AUDIT_JSON_REL,
                          revive=False, lenient=True)
        errs.extend(concern_repair_ledger_problems(
            sb, audit, original, journal_concern_rows(sb)))
        # A dropped concern may not survive anywhere in the finding list.
        audit_rows = _rows_by_id((audit or {}).get("rows") if isinstance(audit, dict) else [])
        repair_doc = read_json(sb / CONCERN_REPAIR_LEDGER_REL,
                                revive=False, lenient=True) or {}
        repair_rows = _rows_by_id(repair_doc.get("rows") if isinstance(repair_doc, dict) else [])
        dropped_ids = {cid for cid, a in audit_rows.items()
                       if str(a.get("verdict")) == "dropped"
                       and str((repair_rows.get(cid) or {}).get("verdict")) == "confirmed"}
        if dropped_ids:
            for f in (read_json(sb / FINDINGS_REL, revive=False, lenient=True) or {}).get(
                    "findings") or []:
                if isinstance(f, dict) and str(f.get("concern") or "") in dropped_ids:
                    errs.append(f"finding {f.get('id')!r} still answers dropped concern "
                                f"{f.get('concern')!r}")
    if counts:
        rec["concerns"] = dict(counts, files=rec.get("feedback_files") or [])
    if not (sb / CONCERN_REPAIR_LOG_REL).is_file():
        warns.append(f"{CONCERN_REPAIR_LOG_REL} (the repair's human-readable record) is "
                     f"missing")
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


def _response_plan_note() -> str:
    return """  * response_plan/ — when present, the point-by-point response written BEFORE
    the revision (READ-ONLY): preserve its verbatim reviewer quotations and
    intended answers, reconcile them with the final package, and fill the
    actual changes/status. It is a plan, not a source of facts."""


def attach_response_plan(ctx, r: int, sb: Path, rec: dict) -> None:
    """Stage the pre-revise response plan into the final response sandbox."""
    if not (journal_has_feedback(ctx) and journal_needs_response(ctx)):
        return
    _d = ctx.run(rid_response_draft(r))
    if _d is None or _d.get("status") != "done":
        return
    ensure_copy(ctx.sandbox_of(_d) / "response", sb / "response_plan")
    rec["draft_run_id"] = rid_response_draft(r)
    if (sb / "response_plan").is_dir():
        rec["inputs_manifest"]["response_plan"] = hash_manifest(sb / "response_plan")


# ---------------------------------------------------------------------
# RESPONSE DRAFT (written BEFORE the manuscript revision)
# ---------------------------------------------------------------------

def response_draft_prompt(ctx: Ctx, sb: Path, r: int) -> str:
    ledger = journal_concern_ledger(_journal_concern_source(ctx, r))
    ids = [str(c.get("id") or "") for c in (ledger.get("concerns") or [])
           if isinstance(c, dict)]
    return CONTRADICTION_RULE + f"""POINT-BY-POINT RESPONSE — DRAFT PLAN (written BEFORE the manuscript is revised)

Your sandbox:
  base/                    the manuscript the concerns are about (read-only)
  non_revised/             the pristine original (read-only)
  concerns/                the concern ledger of record (the repaired ledger in
                           major/minor; the feedback ledger in resubmit) — read-only
  feedback/files/          the ORIGINAL human feedback files (read-only)
  feedback/text/           the same files as plain text; quote from THIS
  feedback/llm/            the admitted LLM review, when the mode stages it:
                           quote an LLM-only concern from feedback/llm/text, never
                           label it a human reviewer
  response/                YOUR OUTPUT: the response plan

This draft is written FIRST, before the revision. It fixes two things that must
not drift while the manuscript is being edited:
  1. the reviewer's own words, quoted CHARACTER-FOR-CHARACTER (typos, wrong
     punctuation and capitalization preserved — never clean them up); and
  2. the authors' intended answer to every concern.
The manuscript revision then implements this plan, and a later stage reconciles
the same letter with the final package (actual changes/statuses). This draft
must NOT claim that a change has already been made.

TASK — one block per repaired concern id, exactly once:
{', '.join(ids) if ids else '(the repaired ledger lists no concerns)'}

WRITE:
  * response/RESPONSE_TO_REVIEWERS.md — one block per concern:
      ## <id> — <short title>
      **Comment:** "<the reviewer's verbatim quotation from feedback/text/>"
      **Response:** the authors' intended answer (what will be done, or why not)
      **Planned changes:** <file:location — the planned edit>, one line per
      planned change; write "none" when no edit is planned
  * response/response_map.json — one row per concern:
      {{"id": "<concern id>",
        "status": "planned" | "already-addressed" | "not-applicable",
        "response": "<one-sentence intended answer>",
        "changes": [], "new_data": []}}
    `changes`/`new_data` stay EMPTY in the draft: they are completed-work
    claims and belong to the final letter. `already-addressed` is valid only
    when the repaired ledger marks the concern already-addressed; it names the
    base/ location in `response`. `not-applicable` gives the rationale.

RULES:
  * every `**Comment:**` is the reviewer's own text, not a paraphrase and not a
    cleaned-up version; preserve typos, wrong punctuation and capitalization.
  * one row/block per concern id, no extras, no omissions.
  * do not edit base/, non_revised/, concerns/ or feedback/; do not edit the
    manuscript; do not write a final claim ("we added ...") here.

{marker_root_rule()}
Write `_pipeline_done.json` (JSON: stage "response_draft", run_id "{sb.name}",
round {int(r)}, status "complete") as the very LAST step.
"""


def materialize_response_draft(ctx: Ctx, r: int) -> dict:
    rid = rid_response_draft(r)
    con_sb = _journal_concern_source(ctx, r)
    a1 = ctx.run(rid_a1(r))
    if a1 is None or a1.get("status") != "done":
        raise RuntimeError(f"cannot materialize {rid}: {rid_a1(r)} is not done")
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    ensure_copy(ctx.sandbox_of(a1) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)
    ensure_copy(con_sb / "concerns", sb / "concerns")
    if (con_sb / "feedback").is_dir():
        ensure_copy(con_sb / "feedback", sb / "feedback")
    safe_mkdir(sb / "response")
    note = prior_failure_block(ctx.run(rid) or {}, sb) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt,
                          ensure_external_content_rule(
                              response_draft_prompt(ctx, sb, r) + note + shared_blocks()))
    rec = ctx.register(rid, "response_draft", r, f"runs/{rid}",
                       upstream_run_id=_concern_source_rid(ctx, r))
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR,
                                                          follow_dir_links=True),
                              "concerns": hash_manifest(sb / "concerns")}
    if (sb / "feedback").is_dir():
        rec["inputs_manifest"]["feedback"] = hash_manifest(sb / "feedback",
                                                          follow_dir_links=True)
    return rec


def postcheck_response_draft(ctx: Ctx, rec: dict):
    sb = ctx.sandbox_of(rec)
    r = int(rec.get("round") or 1)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "response_draft", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    ledger = journal_concern_ledger(_journal_concern_source(ctx, r))
    rows = [c for c in (ledger.get("concerns") or []) if isinstance(c, dict)]
    by_id = _rows_by_id(rows)
    want = list(by_id)
    md = sb / JOURNAL_RESPONSE_MD_REL
    letter = read_text_bounded(md) if md.is_file() else ""
    if not letter:
        errs.append(f"{JOURNAL_RESPONSE_MD_REL} is missing/empty: the draft letter is the "
                    f"deliverable of this stage")
        letter = ""
    comments = response_comment_quotes(letter)
    answers = response_answers(letter)
    if letter and response_letter_change_paths(letter):
        errs.append("the draft letter carries a `**Changes:**` claim: this is written "
                    "BEFORE the revision; use `**Planned changes:**` and keep the map's "
                    "`changes`/`new_data` empty")
    for cid in want:
        mentions = response_heading_occurrences(cid, letter) if letter else 0
        if mentions != 1:
            errs.append(f"response draft: concern {cid!r} needs exactly one `## {cid}` block "
                        f"(found {mentions})")
            continue
        comment = comments.get(cid)
        quote = " ".join(str((by_id.get(cid) or {}).get("quote") or "").split())
        if not comment:
            errs.append(f"response draft {cid!r}: no **Comment:** line")
        elif not response_comment_verifies(ctx, sb, by_id.get(cid), comment, quote):
            errs.append(f"response draft {cid!r}: the Comment quotation is not the human "
                        f"reviewer's verbatim text (preserve typos and punctuation)")
        if not answers.get(cid):
            errs.append(f"response draft {cid!r}: no non-empty **Response:** line")
    data = read_json(sb / JOURNAL_RESPONSE_MAP_REL, revive=False, lenient=True)
    if not isinstance(data, dict):
        errs.append(f"{JOURNAL_RESPONSE_MAP_REL} is missing/unparsable")
    else:
        map_rows = [x for x in (data.get("rows") or []) if isinstance(x, dict)]
        got = [str(x.get("id") or "") for x in map_rows]
        if sorted(got) != sorted(want):
            errs.append(f"{JOURNAL_RESPONSE_MAP_REL} must carry exactly the repaired concern "
                        f"ids (got {sorted(got)}, want {sorted(want)})")
        for row in map_rows:
            cid = str(row.get("id") or "")
            status = str(row.get("status") or "").strip()
            if status not in ("planned", "already-addressed", "not-applicable"):
                errs.append(f"response draft {cid!r}: status {status!r} must be planned/"
                            f"already-addressed/not-applicable (completed-work statuses belong "
                            f"to the final letter)")
            if not str(row.get("response") or "").strip():
                errs.append(f"response draft {cid!r}: the response sentence is empty")
            if row.get("changes") or row.get("new_data"):
                errs.append(f"response draft {cid!r}: the draft must not claim completed "
                            f"changes/new data; keep `changes`/`new_data` empty")
            if status == "already-addressed"                     and str((by_id.get(cid) or {}).get("disposition")) != "already-addressed":
                errs.append(f"response draft {cid!r}: status 'already-addressed' is not the "
                            f"repaired ledger's disposition")
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


# ---------------------------------------------------------------------
# RESPONSE AUDIT
# ---------------------------------------------------------------------

def response_audit_prompt(ctx: Ctx, sb: Path, r: int, target_label: str) -> str:
    ledger = journal_concern_ledger(_journal_concern_source(ctx, r))
    ids = [str(c.get("id") or "") for c in (ledger.get("concerns") or [])
           if isinstance(c, dict)]
    return CONTRADICTION_RULE + f"""RESPONSE AUDIT — independent check of the response-to-reviewers
deliverable (round {int(r)}; read-only. You did NOT write the letter.)

Your sandbox:
  target/                 the FINAL package the letter describes (read-only)
  previous_package/       the pre-revision package, when staged (read-only)
  concerns/               the REPAIRED human concern ledger (read-only)
  feedback/               the human feedback files + text (read-only)
  response/               the deliverable under audit:
                          RESPONSE_TO_REVIEWERS.md + response_map.json (READ-ONLY)
  response_audit/         YOUR OUTPUT DIR

The letter is an LLM-written deliverable. The mechanical postcheck already
verifies block/quote/path/span conventions; your job is the semantic half: does
each block actually answer the concern truthfully, and does every claim match
what the final package and the revision ledger actually contain?

TASK — dispose EVERY concern id exactly once:
{', '.join(ids) if ids else '(the repaired ledger lists no concerns)'}

For each id choose:
  * `confirmed` — the letter's block answers the concern truthfully: the comment
    quote is the ledger's quote AND is the reviewer's own text character-for-
    character (typos, wrong punctuation and capitalization included — never
    cleaned up), the response states nothing the package does not support, the
    status is right, and every cited change/new-data file and span exists in
    target/.
  * `defective` — at least one defect. Give one `defects` row per defect with:
      - `location` (response/...:line or response_map.json row),
      - `wrong` (the exact current text/citation/status),
      - `correct` (the exact replacement, or the true supported statement),
      - `basis` (the package file:line, ledger row, revision-ledger row or
        re-runnable check that decides it).

Defect types:
  missing-answer        no real answer to the concern
  unsupported-claim     claims a change/result the package does not contain
  wrong-citation        cites the wrong file/location/span
  non-verbatim-quote    the Comment quote is not the ledger's verified quote
  wrong-status          addressed/partially-addressed/planned/... is wrong
  overclaim             claims more than the package supports
  underclaim            does less than the package supports (optional, lower priority)
  inconsistent-map      the letter and response_map.json disagree
  non-human-concern     the letter answers an item that is not a human concern
  other                 say exactly what

A `planned`/`manual` answer claims nothing done. An `addressed` answer needs a
real change or new-data file in target/. A new-experiment concern needs its new
data. The response must not invent a result, a number, a reviewer sentence, or a
file.

A MANUSCRIPT defect you notice outside the response (a wrong value, a missing
change) goes to `response_audit/UNRESOLVED.md` as an observation with location
and re-runnable evidence. It is NOT a finding and the response repair will not
edit the manuscript.

WRITE:
  * response_audit/RESPONSE_AUDIT.json — exactly:
    {{"round": {int(r)},
      "rows": [{{"id": "R1-1",
                 "verdict": "confirmed|defective",
                 "defects": [{{"type": "<above>", "location": "...",
                               "wrong": "...", "correct": "...", "basis": "..."}}],
                 "reason": "...", "evidence": "..."}}],
      "coverage": [{{"file": "<response/... or concerns/...>", "examined": 0,
                     "defects": 0, "note": "..."}}],
      "notes": "..."}}
    ONE row per ledger id, no extras.
  * response_audit/RESPONSE_AUDIT.md — the same, human-readable.
  * response_audit/coverage.md — what you checked per concern / source and what
    you could not check. The `coverage` JSON must carry one row for
    `response/RESPONSE_TO_REVIEWERS.md` and one for `response/response_map.json`
    (plus any source file you checked).
  * response_audit/UNRESOLVED.md — observations ("none" when none).

Do NOT edit target/, previous_package/, concerns/, feedback/ or response/. Do not
write a letter, a map or a manuscript change.

{marker_root_rule()}
Write `_pipeline_done.json` (JSON: stage "response_audit", run_id "{sb.name}",
round {int(r)}, status "complete", confirmed N, defective N) as the very LAST step.
"""


def materialize_response_audit(ctx: Ctx, r: int) -> dict:
    rid = rid_response_audit(r)
    resp_rec = _require_done(ctx, rid_response(r),
                             "the response audit consumes the response deliverable")
    src = ctx.sandbox_of(resp_rec)
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    for name in ("target", "previous_package", "concerns", "feedback"):
        if (src / name).is_dir():
            ensure_copy(src / name, sb / name)
    ensure_copy(src / "response", sb / "response")
    safe_mkdir(sb / RESPONSE_AUDIT_DIRNAME)
    note = prior_failure_block(ctx.run(rid) or {}, sb) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt,
                          ensure_external_content_rule(
                              response_audit_prompt(ctx, sb, r, "the final package")
                              + note + shared_blocks()))
    rec = ctx.register(rid, "response_audit", r, f"runs/{rid}",
                       upstream_run_id=rid_response(r))
    rec["inputs_manifest"] = {}
    for name in ("target", "previous_package", "feedback", "response"):
        if (sb / name).is_dir():
            rec["inputs_manifest"][name] = hash_manifest(sb / name,
                                                         follow_dir_links=True)
    # The ledger is READ-ONLY here but it is not the response's `concerns/` copy
    # in every mode; include it under its own key.
    if (sb / "concerns").is_dir():
        rec["inputs_manifest"]["concerns"] = hash_manifest(sb / "concerns")
    return rec


def response_audit_artifact_problems(audit, concern_ids, sb: Path) -> list:
    errs = []
    if not isinstance(audit, dict):
        return [f"{RESPONSE_AUDIT_JSON_REL} does not parse as a JSON object"]
    rows = [r for r in (audit.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return [f"{RESPONSE_AUDIT_JSON_REL} carries no disposition rows"]
    want = [str(x) for x in concern_ids]
    got = [str(r.get("id") or "") for r in rows]
    dups = sorted({x for x in got if x and got.count(x) > 1})
    if dups:
        errs.append(f"{RESPONSE_AUDIT_JSON_REL}: id(s) appear more than once: "
                    f"{', '.join(dups[:6])}")
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    if missing:
        errs.append(f"{RESPONSE_AUDIT_JSON_REL} does not dispose {len(missing)} concern(s): "
                    f"{', '.join(missing[:6])}")
    if extra:
        errs.append(f"{RESPONSE_AUDIT_JSON_REL} names {len(extra)} row(s) that are not "
                    f"repaired concerns: {', '.join(extra[:6])}")
    for row in rows:
        cid = str(row.get("id") or "")
        verdict = str(row.get("verdict") or "").strip()
        if verdict not in ("confirmed", "defective"):
            errs.append(f"response {cid}: verdict {verdict!r} must be confirmed/defective")
            continue
        if not _audit_reason_ok(row.get("reason")):
            errs.append(f"response {cid}: `reason` is empty/filler")
        if not str(row.get("evidence") or "").strip():
            errs.append(f"response {cid}: `evidence` is empty")
        defects = [d for d in (row.get("defects") or []) if isinstance(d, dict)]
        if verdict == "confirmed" and defects:
            errs.append(f"response {cid}: verdict 'confirmed' must carry no defects")
        elif verdict == "defective":
            if not defects:
                errs.append(f"response {cid}: a defective verdict needs at least one defect")
            for i, d in enumerate(defects, 1):
                typ = str(d.get("type") or "").strip()
                if typ not in RESPONSE_DEFECT_TYPES:
                    errs.append(f"response {cid} defect {i}: type {typ!r} is not one of "
                                f"{', '.join(RESPONSE_DEFECT_TYPES)}")
                for key in ("location", "wrong", "correct", "basis"):
                    if not str(d.get(key) or "").strip():
                        errs.append(f"response {cid} defect {i}: `{key}` is empty")
    errs.extend(_coverage_problems(audit.get("coverage"),
                                   [f for f in ("response/RESPONSE_TO_REVIEWERS.md",
                                                "response/response_map.json")
                                    if (sb / f).is_file()],
                                   RESPONSE_AUDIT_JSON_REL))
    return errs


def postcheck_response_audit(ctx: Ctx, rec: dict):
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "response_audit", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    # The deliverable under audit must still satisfy its own mechanical
    # contract; the audit cannot bless a letter the postcheck already rejects.
    resp_rec = ctx.run(rid_response(rec.get("round")))
    if resp_rec is None:
        errs.append("the response audit cannot find the response run it audits")
    else:
        ok, rerrs, rwarns, _ = postcheck_response(ctx, resp_rec)
        errs.extend(rerrs)
        warns.extend(rwarns)
    ledger = journal_concern_ledger(_journal_concern_source(ctx, rec.get("round")))
    ids = [str(c.get("id")) for c in (ledger.get("concerns") or [])
           if isinstance(c, dict) and str(c.get("id") or "")]
    aj = sb / RESPONSE_AUDIT_JSON_REL
    if not aj.is_file():
        errs.append(f"{RESPONSE_AUDIT_JSON_REL} is missing: the audit's dispositions are the "
                    f"deliverable the repair consumes")
    else:
        audit = read_json(aj, revive=False, lenient=True)
        problems = response_audit_artifact_problems(audit, ids, sb)
        errs.extend(problems)
        if not problems and isinstance(audit, dict):
            rows = [r for r in (audit.get("rows") or []) if isinstance(r, dict)]
            rec["response_audit"] = {
                "rows": len(rows),
                "confirmed": sum(1 for r in rows if str(r.get("verdict")) == "confirmed"),
                "defective": sum(1 for r in rows if str(r.get("verdict")) == "defective"),
            }
            if rec["response_audit"]["defective"]:
                warns.append(f"the response audit found {rec['response_audit']['defective']} "
                             f"defective response row(s); the repair will re-validate and "
                             f"apply only confirmed defects")
    if not (sb / RESPONSE_AUDIT_MD_REL).is_file():
        warns.append(f"{RESPONSE_AUDIT_MD_REL} is missing")
    unresolved = sb / RESPONSE_AUDIT_UNRESOLVED_REL
    if unresolved.is_symlink() or (unresolved.exists() and not unresolved.is_file()):
        errs.append(f"{RESPONSE_AUDIT_UNRESOLVED_REL} is a symlink or not a regular file")
    elif not unresolved.is_file():
        errs.append(f"{RESPONSE_AUDIT_UNRESOLVED_REL} is missing (write 'none' when there "
                    f"are no observations)")
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


# ---------------------------------------------------------------------
# RESPONSE REPAIR
# ---------------------------------------------------------------------

def response_repair_prompt(ctx: Ctx, sb: Path, r: int, target_label: str) -> str:
    ledger = journal_concern_ledger(_journal_concern_source(ctx, r))
    ids = [str(c.get("id") or "") for c in (ledger.get("concerns") or [])
           if isinstance(c, dict)]
    return CONTRADICTION_RULE + f"""RESPONSE REPAIR — apply the independent response audit (one pass,
round {int(r)}; you do NOT edit the manuscript)

Your sandbox:
  target/                 the FINAL package (read-only)
  previous_package/       the pre-revision package, when staged (read-only)
  concerns/               the repaired human concern ledger (read-only)
  feedback/               the human feedback files + text (read-only)
  response/               the deliverable you repair:
                          RESPONSE_TO_REVIEWERS.md + response_map.json (EDITABLE)
  response_audit/         the audit's RESPONSE_AUDIT.json + evidence (READ-ONLY)
  response_plan/          (when present) the point-by-point plan written before the
                           revision (READ-ONLY)
  response_prerepair/     the response/ bytes BEFORE this repair (READ-ONLY; the
                           postcheck proves a no-change run really changed nothing)
  response_repair/        YOUR OUTPUT DIR

You are a FINDING-CONSUMING session: the audit rows are inputs, never a substitute
for re-verification (rule 1B). For EVERY audit row, re-open the letter block, the
map row, the named package file/span and the repaired ledger, decide
`confirmed` or `rejected`, and record the verdict BEFORE editing. Apply only
confirmed defects.

WHAT YOU MAY CHANGE (response/ only):
  * replace a non-verbatim Comment quote with the repaired ledger's verified
    quote, copying the reviewer's text CHARACTER-FOR-CHARACTER (typos, wrong
    punctuation and capitalization included); never "fix" the reviewer's prose;
  * correct a wrong file/location/span citation to what target/ actually carries;
  * correct a wrong status to what the package supports
    (addressed / partially-addressed / already-addressed / planned / not-applicable);
  * replace an unsupported claim with the true supported statement, or downgrade
    the row to `planned`/`manual` with the exact steps when the package does not
    support it;
  * add a missing answer only when target/ supports it; otherwise mark it planned
    or manual with the exact author steps;
  * make the letter and response_map.json agree.

WHAT YOU MAY NOT DO:
  * edit target/, previous_package/, concerns/, feedback/ or response_audit/;
  * edit the manuscript or claim a manuscript change that target/ does not carry;
  * invent a result, number, reviewer sentence, new-data file, or concern;
  * add a concern id that the repaired ledger does not carry.

If the audit found nothing to correct, copy the letter/map unchanged and write
ONE `no-change` row per audit id (an empty `rows` list is a FAILED repair: every
audit row must be accounted for).

WRITE:
  * response_repair/REPAIR_LEDGER.json:
    {{"round": {int(r)},
      "rows": [{{"id": "R1-1",
                 "audit_verdict": "confirmed|defective",
                 "verdict": "confirmed|rejected",
                 "action": "kept|corrected|no-change",
                 "reason": "...", "evidence": "..."}}],
      "counts": {{"input": N, "kept": N, "corrected": N, "rejected": N}},
      "residual": "<defects you could not repair, or empty>"}}
    ONE row per audit id.
  * response_repair/REPAIR_LOG.md — the human-readable record, including every
    rejected audit row, the correction applied, and any residual defect the round
    decision must report.

{marker_root_rule()}
Write `_pipeline_done.json` (JSON: stage "response", run_id "{sb.name}",
round {int(r)}, status "complete") as the very LAST step (stage "response" is the
deliverable's contract; this run is its repair).
"""


def materialize_response_repair(ctx: Ctx, r: int) -> dict:
    rid = rid_response_repair(r)
    resp_rec = _require_done(ctx, rid_response(r),
                             "the response repair edits the response deliverable")
    aud_rec = _require_done(ctx, rid_response_audit(r),
                            "the response repair consumes the independent response audit")
    src = ctx.sandbox_of(resp_rec)
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    for name in ("target", "previous_package", "concerns", "feedback", "response_plan"):
        if (src / name).is_dir():
            ensure_copy(src / name, sb / name)
    ensure_copy(src / "response", sb / "response")
    ensure_copy(src / "response", sb / "response_prerepair")
    ensure_copy(ctx.sandbox_of(aud_rec) / RESPONSE_AUDIT_DIRNAME,
                sb / RESPONSE_AUDIT_DIRNAME)
    safe_mkdir(sb / RESPONSE_REPAIR_DIRNAME)
    note = prior_failure_block(ctx.run(rid) or {}, sb) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt,
                          ensure_external_content_rule(
                              response_repair_prompt(ctx, sb, r, "the final package")
                              + note + shared_blocks()))
    rec = ctx.register(rid, "response_repair", r, f"runs/{rid}",
                       upstream_run_id=rid_response_audit(r))
    rec["inputs_manifest"] = {}
    for name in ("target", "previous_package", "feedback", "response_plan",
                 "response_audit", "response_prerepair"):
        if (sb / name).is_dir():
            rec["inputs_manifest"][name] = hash_manifest(sb / name,
                                                         follow_dir_links=True)
    if (sb / "concerns").is_dir():
        rec["inputs_manifest"]["concerns"] = hash_manifest(sb / "concerns")
    return rec


def response_repair_ledger_problems(sb: Path, audit, ledger_ids) -> list:
    errs = []
    path = sb / RESPONSE_REPAIR_LEDGER_REL
    if not path.is_file():
        return [f"{RESPONSE_REPAIR_LEDGER_REL} is missing: the repair's per-row verdicts are "
                f"the record a different session re-checks"]
    doc = read_json(path, revive=False, lenient=True)
    if not isinstance(doc, dict):
        return [f"{RESPONSE_REPAIR_LEDGER_REL} does not parse as a JSON object"]
    rows = [r for r in (doc.get("rows") or []) if isinstance(r, dict)]
    audit_rows = _rows_by_id((audit or {}).get("rows") if isinstance(audit, dict) else [])
    got = [str(r.get("id") or "") for r in rows]
    want = list(audit_rows)
    dups = sorted({x for x in got if x and got.count(x) > 1})
    if dups:
        errs.append(f"{RESPONSE_REPAIR_LEDGER_REL}: id(s) appear more than once: "
                    f"{', '.join(dups[:6])}")
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    if missing:
        errs.append(f"{RESPONSE_REPAIR_LEDGER_REL} does not account for {len(missing)} audit "
                    f"row(s): {', '.join(missing[:6])}")
    if extra:
        errs.append(f"{RESPONSE_REPAIR_LEDGER_REL} names {len(extra)} row(s) the audit never "
                    f"disposed: {', '.join(extra[:6])}")
    for row in rows:
        cid = str(row.get("id") or "")
        verdict = str(row.get("verdict") or "").strip()
        action = str(row.get("action") or "").strip()
        if verdict not in REPAIR_VERDICTS:
            errs.append(f"response repair row {cid!r}: verdict {verdict!r} must be "
                        f"confirmed/rejected")
        if action not in ("kept", "corrected", "no-change"):
            errs.append(f"response repair row {cid!r}: action {action!r} must be "
                        f"kept/corrected/no-change")
        if not _audit_reason_ok(row.get("reason")):
            errs.append(f"response repair row {cid!r}: `reason` is empty/filler")
        if not str(row.get("evidence") or "").strip():
            errs.append(f"response repair row {cid!r}: `evidence` is empty")
        if cid not in ledger_ids:
            errs.append(f"response repair row {cid!r}: not a repaired concern id")
        av = str((audit_rows.get(cid) or {}).get("verdict") or "")
        if verdict == "rejected" and action == "corrected":
            errs.append(f"response repair row {cid!r}: a rejected audit row cannot also be "
                        f"corrected")
        if action == "corrected" and av != "defective":
            errs.append(f"response repair row {cid!r}: 'corrected' needs a DEFECTIVE audit "
                        f"row (the audit found no defect here)")
    return errs


def postcheck_response_repair(ctx: Ctx, rec: dict):
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "response", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    # Re-run the response deliverable's OWN postcheck on the repaired bytes.
    resp_rec = ctx.run(rid_response(rec.get("round")))
    if resp_rec is None:
        errs.append("the response repair cannot find the response run it repairs")
    else:
        _shadow = dict(resp_rec)
        _shadow["id"] = rec["id"]
        _shadow["kind"] = "response"
        # `sandbox_of()` reads the RECORD's path, not its id: without this the
        # shadow still points at the response sandbox and re-checks the wrong
        # marker/letter.
        _shadow["sandbox"] = rec.get("sandbox")
        _ok, rerrs, rwarns, _ = postcheck_response(ctx, _shadow)
        errs.extend(rerrs)
        warns.extend(rwarns)
    aud_rec = ctx.run(rid_response_audit(rec.get("round")))
    ledger = journal_concern_ledger(_journal_concern_source(ctx, rec.get("round")))
    ledger_ids = {str(c.get("id")) for c in (ledger.get("concerns") or [])
                  if isinstance(c, dict)}
    if aud_rec is not None:
        audit = read_json(ctx.sandbox_of(aud_rec) / RESPONSE_AUDIT_JSON_REL,
                          revive=False, lenient=True)
        errs.extend(response_repair_ledger_problems(sb, audit, ledger_ids))
        _doc = read_json(sb / RESPONSE_REPAIR_LEDGER_REL, revive=False, lenient=True) or {}
        _rows = [r for r in (_doc.get("rows") or []) if isinstance(r, dict)]
        _actions = {str(r.get("action") or "") for r in _rows}
        if _rows and not (_actions & {"corrected"}) \
                and (sb / "response_prerepair").is_dir():
            if hash_manifest(sb / "response") != hash_manifest(sb / "response_prerepair"):
                errs.append("the response repair ledger records no correction, but response/ "
                            "was changed: a no-change/rejected run must leave the deliverable "
                            "byte-identical")
    else:
        errs.append("the response repair cannot find the audit it consumed")
    if not (sb / RESPONSE_REPAIR_LOG_REL).is_file():
        warns.append(f"{RESPONSE_REPAIR_LOG_REL} is missing")
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


# ---------------------------------------------------------------------
# PROMPT BLOCK: the revision audit's scoped variant
# ---------------------------------------------------------------------

def journal_revision_audit_block(ctx: Ctx) -> str:
    """The block appended to REVISION AUDIT in a major/minor revision.

    The revision audit keeps its own object (the revision's delta); this block
    tells it that the frozen findings are the REPAIRED human concerns and that
    the scope guard, not a general review, defines the allowed edits.
    """
    return """

=== CONCERN-SCOPED REVISION AUDIT (major/minor) ===
The frozen findings in `guided_review/findings.json` are the REPAIRED HUMAN
reviewer concerns (check `JF`, with a `concern` id). This revision may change the
manuscript ONLY where one of those concerns requires it.
  * Audit the revision's own delta, not the submission: no re-review, no
    discovery hunt, no new finding.
  * Every changed file and hunk must be authorized by a surviving concern's
    finding. An edit no concern requires is a defect row (the bounded repair
    reverts or records it); the scoped scope guard is re-run after the repair.
  * A concern whose finding says `resolvable` must be genuinely fixed in
    `revised/`, not merely mentioned in the ledger or a manual item.
  * A `manual`/`unresolvable` concern must have a real manual row; inventing a
    result is a defect.
  * The response letter is a LATER stage; do not write it here.
"""


def run_response_deliverable_chain(ctx, r: int, response_dir: Path, ph: dict):
    """Run the response audit + repair as ordinary planned stages.

    Returns `(response_dir, ok, paused)`. The repair's sandbox becomes the
    response directory the journal-submission assembly reads, so the letter
    that ships is the repaired one. `ph` is the run_phase keyword payload the
    caller already built.
    """
    for _rid, _mat, _label in (
            (rid_response_audit(r),
             (lambda c: materialize_response_audit(c, r)), "journal response audit"),
            (rid_response_repair(r),
             (lambda c: materialize_response_repair(c, r)), "journal response repair")):
        _rec = ctx.run(_rid)
        if _rec is not None and _rec.get("status") == "done":
            continue
        _mat(ctx)
        ok, paused = run_phase(ctx, [_rid], label=_label, **ph)
        if not ok:
            return response_dir, False, paused
    _rep = ctx.run(rid_response_repair(r)) or {}
    if _rep.get("status") == "done":
        response_dir = ctx.sandbox_of(_rep)
    return response_dir, True, False


# ---------------------------------------------------------------------
# REGISTRATION
# ---------------------------------------------------------------------

POSTCHECK_HANDLERS.update({
    "response_draft": postcheck_response_draft,
    "concern_audit": postcheck_concern_audit,
    "concern_repair": postcheck_concern_repair,
    "response_audit": postcheck_response_audit,
    "response_repair": postcheck_response_repair,
})
REBUILD_HANDLERS.update({
    "response_draft": lambda ctx, rec: materialize_response_draft(ctx, int(rec["round"])),
    "concern_audit": lambda ctx, rec: materialize_concern_audit(ctx, int(rec["round"])),
    "concern_repair": lambda ctx, rec: materialize_concern_repair(ctx, int(rec["round"])),
    "response_audit": lambda ctx, rec: materialize_response_audit(ctx, int(rec["round"])),
    "response_repair": lambda ctx, rec: materialize_response_repair(ctx, int(rec["round"])),
})
STRUCTURED_OUTPUT_JSON.update({
    "response_draft": ("_pipeline_done.json", JOURNAL_RESPONSE_MAP_REL),
    "concern_audit": ("_pipeline_done.json", CONCERN_AUDIT_JSON_REL),
    "concern_repair": ("_pipeline_done.json", CONCERN_REPAIR_LEDGER_REL),
    "response_audit": ("_pipeline_done.json", RESPONSE_AUDIT_JSON_REL),
    "response_repair": ("_pipeline_done.json", RESPONSE_REPAIR_LEDGER_REL),
})
STRUCTURED_OUTPUT_ROOTS.update({
    "response_draft": ("response",),
    "concern_audit": (CONCERN_AUDIT_DIRNAME,),
    "concern_repair": (CONCERN_REPAIR_DIRNAME,),
    "response_audit": (RESPONSE_AUDIT_DIRNAME,),
    "response_repair": (RESPONSE_REPAIR_DIRNAME,),
})

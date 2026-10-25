# -*- coding: utf-8 -*-
# Part 07/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# STAGE-QUALITY CHECKS: the language pass, the integration ledger and the
# "did the fix introduce a NEW class of defect" comparison.
# =====================================================================

SCAN_REGRESSION_IGNORE = ("FMT-T9h",)      # a separator convention, advisory by design
# The reporter's own advice per rule: the generic prose advice ("shorten the
# sentence") is wrong for a layout rule and sent a real stage looking in the
# wrong place. The repair command is named where one exists.
RULE_REPAIR_ADVICE = {
    "FMT-TB4": "make w:tblGrid agree with the cells' w:tcW "
               "(`paper_docx_format.py repair-layout`)",
    "FMT-TB5": "widen the column or shorten the identifier "
               "(`paper_docx_format.py repair-layout`)",
    "FMT-S10": "keep exactly one PAGE field in the referenced footer part",
    "FMT-IM4": "re-export the image at the venue's effective resolution",
    "FMT-IM5": "regenerate the artwork with the manuscript's spelling",
    "FMT-AV3": "name a locator the submission carries, or say 'available from the authors'",
}

# The `writing` tier's rubric: twelve named checks so a prose judgement cites
# something a second reader can re-check, instead of taste. Kept free of any
# provenance vocabulary (see test_judge_blinding.py): it says nothing about how
# either package was produced.
WRITING_RUBRIC = """WRITING RUBRIC — use it to justify every `writing`-tier row (one named check per row):
  Q1  the sentence's claim does not match the evidence: its premise is contradicted by the data
      or by another sentence, it claims MORE than the evidence supports (an overclaim) or it
      claims LESS than the evidence supports (an underclaim -- a supported result hedged into
      "may"/"could"/"suggests"/"a trend"/"preliminary"). Both directions are Q1; a hedge the
      evidence genuinely requires is correct and is not a row. A claim whose strength is wrong
      in the UNDER direction is a `correctness`-tier defect exactly like an overclaim (see J3)
  Q2  a formal-logic slip (converse/inverse swapped; "A therefore B" where only B-with-A holds)
  Q3  a logic jump (the conclusion needs a step the text never states)
  Q4  coherence (referents, connectors, tense: between sentences and inside one sentence; and the
      LINKAGE of each unit to its parent and to its next sibling -- a unit that does not follow
      from what precedes it, or that is not connected to the next one, is a row here or at Q12).
      The first sentence of a paragraph must connect to the PREVIOUS paragraph (a pronoun,
      connector, repeated term or stated relation): a paragraph opening with a bare new-topic
      assertion -- a named tool or entity dropped in with no link -- is a row; add the link,
      never delete the content
  Q5  an unexplained prerequisite (a term a reader would have to look up; define it once, in
      place). A LaTeX command or macro argument is NOT a prerequisite -- the full paper defines
      it, so never file a row for the argument of a macro
  Q6  redundancy (the same fact stated twice in one paragraph; a sentence whose content adds
      nothing to the one before it)
  Q7  non-academic wording (metaphor, hype, promotional adjectives, or a word, verb or connector
      that is less precise, less idiomatic or less established than the alternative the register
      itself uses). Judge this GENERICALLY and directionally: compare the two versions' readings
      of the same content and name which one is worse and by what -- academic vs conversational,
      precise vs vague, the established collocation vs an ad-hoc pairing. Never work from a fixed
      word list
  Q8  non-written register (spoken, short or colloquial forms where the formal equivalent exists)
  Q9  stiff, formulaic or translated phrasing and word order, and any sentence the reader must
      RE-READ to follow (stacked clauses, a referent that resolves only later, two ideas in one
      breath): the meaning survives, the idiom and the flow do not. Includes a literal rendering
      of another language's construction; split or reorder the sentence, never change its claim
  Q10 grammar (agreement, voice, dangling modifiers, parallelism)
  Q11 typography and punctuation (typos; a comma splice; a missing or wrong mark; a spaced hyphen
      used as a dash; mixed quotation marks; hundreds separators used inconsistently; a quantity
      whose unit typography hides its value). MECHANICAL SEPARATOR CONVENTIONS ARE NOT THIS ITEM:
      character spacing, blank lines and line or paragraph breaks belong to the format checks
      (M20) and the orchestrator's normalizer -- never a row here, and never scored twice
  Q12 segmentation and structure (one sentence carrying two ideas; one paragraph carrying two
      messages; an enumeration buried inside prose; a section whose subsections do not each carry
      an independent sub-topic, or a unit whose topic does not match its parent)
  HOW TO COMPARE TWO READINGS -- this is what makes small differences scorable: a difference is a
  row when ONE side is WORSE on a named item above, never merely because the two readings differ.
  Run the items over both versions of the same content, name the item, the register the worse side
  belongs to and the intended reading. ONE worse word, verb or connector is a MINOR row exactly
  like one typo, and "it appears only once" is not an exemption; a slip that recurs through a
  paragraph, or one that leaves a whole scope's topic unclear (Q12), is MAJOR. A difference where
  BOTH readings satisfy every item is cosmetic (0) for everyone -- "different" is not "worse".
  A row names its rubric item (`Q7` -- the row's `check` cell carries the FROZEN check id this
  rubric belongs to, `J3`: the Q1-Q12 items are the twelve faces OF J3, not check ids of their
  own, and a ledger row's `check` cell is always one of M1-M24/J1-J4), quotes the offending words
  and says what the sentence should read as. The tier carries the same four severity rungs as every
  other class: one slip is a MINOR row, prose a reader must work around is MAJOR, prose nobody can
  follow is CRITICAL/FATAL -- but every row counts, and ten unfixed rows are ten rows.
  Q1-Q11 correspond one-to-one to the eleven checks of the language pass every
  package-producing session runs from the same list
  (premise, logic slip, logic jump, coherence, unexplained prerequisite, redundancy, non-academic
  wording, register, stiff phrasing, grammar, typography); Q12 is the segmentation check, and a
  difference that cannot be named in this rubric is cosmetic for you as well.
  REFILE RULE: a row whose evidence shows the MEANING changed is not a `writing` row, whichever
  item it matches -- a premise the data contradict, a logic slip that changes what the claim
  asserts, a conclusion whose missing step leaves it unsupported, or a claim stronger/weaker than
  its evidence belongs to the `correctness` tier (the class rule above), where that tier's rows
  count first; this rubric justifies only rows whose meaning survives the fix."""


def language_pass_report(pkg: Path) -> dict:
    """The L1–L11 language-pass artifact of one package: coverage per step."""
    want = [f"L{i}" for i in range(1, 12)]
    path = pkg / "work" / "R6_language.md"
    if not path.is_file():
        return {"file": str(path), "present": False, "rows": 0, "steps_seen": [],
                "missing": want}
    try:
        text = path.read_text("utf-8", "replace")
    except OSError:
        text = ""
    rows = parse_markdown_table(path)
    steps = set()
    for r in rows:
        for m in re.finditer(r"L(\d{1,2})", str(r.get("step") or "")):
            steps.add(f"L{m.group(1)}")
    for m in re.finditer(r"(?m)^\s*\|?\s*\**L(\d{1,2})\b", text):
        steps.add(f"L{m.group(1)}")
    seen = sorted(steps, key=lambda s: int(s[1:]))
    return {"file": str(path), "present": True, "rows": len(rows), "steps_seen": seen,
            "missing": [s for s in want if s not in steps]}


def check_language_pass(ctx: Ctx, rec: dict, pkg: Path, label: str,
                        errs: list, warns: list) -> dict:
    """Record (and, under --strict-artifacts, fail) the language-pass coverage."""
    rep = language_pass_report(pkg)
    rec["language_pass"] = {"present": rep["present"], "rows": rep["rows"],
                            "steps_seen": rep["steps_seen"], "missing": rep["missing"]}
    if not rep["present"]:
        msg = (f"{label}: no work/R6_language.md -- the L1-L11 language pass is a required "
               f"artifact of every package-producing stage: one row per change plus one coverage "
               f"row per step (including the steps that changed nothing)")
        (errs if strict_dispositions(ctx) else warns).append(msg)
    elif rep["missing"]:
        msg = (f"{label}: the language pass covers {11 - len(rep['missing'])}/11 steps; no "
               f"coverage row for {', '.join(rep['missing'])} (a step with no row is an "
               f"unaudited step)")
        (errs if strict_dispositions(ctx) else warns).append(msg)
    return rec["language_pass"]


def scan_regression_problems(ctx: Ctx, before_sources: list, after_sources: list,
                             label: str, fixer_reclassified=None,
                             policy: dict = None) -> tuple:
    """(errors, warnings): did the OUTPUT introduce a new finding-tier family?

    Every package-producing stage is compared with the package it started from,
    per rule, over the finding-tier families only.  A family the input did not
    have AT ALL and the output now has is a failure ("the fix introduced a new
    class of defect": a new mega-paragraph, a new nested parenthesis, a new
    value+unit outside siunitx, a new long abstract sentence).  Growth inside a
    family that was already present is reported as a warning, because a stage
    legitimately trades rows inside a family (splitting one sentence can create
    a shorter one elsewhere).

    `fixer_reclassified` names the rules the orchestrator's OWN format fixer
    gained rows for in the delivered package while merging split captions (see
    `_scan_rule_delta` + `add_stage_quality_checks`): a family that appeared
    because the caption text is now READ as a legend is a pipeline-side
    text-model artifact, reported as a warning -- the review still disposes the
    rows -- instead of failing a stage that changed no text.

    This is ALSO where the venue's own TABLE rule is enforced (rules FMT-TB1
    ..FMT-TB3): a rule the venue profile declares is not a regression question
    -- a delivered package may not carry a table whose caption or placement
    breaks the venue's own declaration, whether or not the package it started
    from did. The check is skipped (nothing is invented) when the profile
    declares no table rule.
    """
    mod = _format_module()
    if mod is None:
        # An unavailable OOXML engine is a COVERAGE GAP, not a clean comparison:
        # returning ([], []) let a stage pass with every formatting rule
        # unexamined. The manifest fence refuses a root with a missing/tampered
        # frozen module; this covers a scanner that cannot load for any other
        # reason (a syntax error, a stripped copy) and every caller -- including
        # `--format-gate`, which otherwise sees no rows and certifies.
        return ([f"{label}: the OOXML formatting scanner ({DOCX_FORMAT_MODULE}) is "
                 f"UNAVAILABLE next to the driver, so no formatting rule was examined; "
                 f"restore the module (or run from a root whose bundle is complete) "
                 f"and re-check"], [])
    # `policy` may be supplied by a caller with no Ctx (the sandbox self-check
    # reads the sandbox's own format_policy.json): the pre-flight must reach the
    # same verdict as the postcheck it previews.
    policy = policy or (format_policy_of(ctx) if ctx is not None else None)
    before_info = scan_format_in_sources(before_sources, policy=policy)
    after_info = scan_format_in_sources(after_sources, policy=policy)

    def counts(info) -> Counter:
        c = Counter()
        for r in info.get("rows") or []:
            rule = str(r.get("rule") or "")
            if rule in SCAN_REGRESSION_IGNORE:
                continue
            tier = r.get("tier") or (mod.tier_of(rule) if hasattr(mod, "tier_of") else "advisory")
            if tier == "finding":
                c[rule] += 1
        return c

    before, after = counts(before_info), counts(after_info)
    errs, warns = [], []
    fixer_reclassified = set(fixer_reclassified or ())
    for rule in sorted(set(before) | set(after)):
        if rule in DISPLAY_RULE_IDS:
            # The venue's table/figure rule is enforced by `display_rule_errors`
            # below, with the item named and the right fix; the generic "shorten
            # the sentence / use siunitx" advice would be wrong for it.
            continue
        if after[rule] <= before[rule]:
            continue
        if before[rule] == 0:
            if rule in fixer_reclassified:
                warns.append(
                    f"{label}: the new {rule} row(s) ({after[rule]}) come from the "
                    f"orchestrator's own format normalization (it merged split captions, "
                    f"which changes how the caption's text is read), not from this stage's "
                    f"edit -- recorded in the run's FORMAT_FIX artifact; the review disposes "
                    f"the row(s)")
                continue
            sample = [r for r in (after_info.get("rows") or [])
                      if str(r.get("rule") or "") == rule][:3]
            where = "; ".join(
                f"{r.get('document') or '?'}"
                + (f" / {r.get('location')}" if r.get("location") else "")
                + (f" ({str(r.get('evidence') or '')[:70]})" if r.get("evidence") else "")
                for r in sample)
            advice = RULE_REPAIR_ADVICE.get(
                rule, "shorten the sentence, split the paragraph, unwrap the parentheses, "
                      "use siunitx")
            errs.append(
                f"{label}: the delivered package introduces a NEW finding-tier defect family "
                f"{rule} ({after[rule]} row(s); the package it started from had none) -- fix it "
                f"({advice}) or record why the ruler itself is wrong"
                + (f" -- first row(s): {where}" if where else ""))
        else:
            warns.append(f"{label}: {rule} rows grew {before[rule]} -> {after[rule]} between the "
                         f"input and the delivered package")
    errs.extend(display_rule_errors(after_info, label))
    return errs, warns


# The code-side rule ids of the venue's DISPLAY rules (paper_docx_format): the
# rows a profile-declared table/figure rule produces, and the only rows the
# pipeline gates a delivered package on through this module.
DISPLAY_RULE_IDS = ("FMT-TB1", "FMT-TB2", "FMT-TB3",
                    "FMT-FG1", "FMT-FG2", "FMT-FG3")


def display_rule_errors(info: dict, label: str) -> list:
    """The venue's declared DISPLAY rules, enforced on one scan's output (pure).

    One error per FMT-TB*/FMT-FG* row the scan of the DELIVERED package found:
    the profile declared the rule, so the package may not carry it. A profile
    that declares no rule for a kind produces no rows for it, so nothing is
    invented and nothing is gated.
    """
    errs = []
    for r in info.get("rows") or []:
        rule = str(r.get("rule") or "")
        if rule not in DISPLAY_RULE_IDS:
            continue
        noun = "table" if rule.startswith("FMT-TB") else "figure"
        errs.append(
            f"{label}: the venue's own {noun} rule is not met -- {rule} "
            f"({r.get('document')}: {r.get('location')}; {r.get('evidence')}). "
            f"{str(r.get('detail') or '').strip()}")
    return errs


# The columns that MAKE a table the integration ledger (rather than the session's
# own orientation/summary table, which is welcome documentation but carries none
# of the per-difference fields the postcheck has to read).
INTEGRATION_LEDGER_COLUMNS = ("donor", "artifact", "size", "finding effect", "verdict")


def integration_ledger_rows(path: Path) -> list:
    """The LEDGER rows of DIFF_LEDGER.md, not the session's other tables.

    A ledger file legitimately carries more than one table -- an orientation or
    "state of the package" summary first, the ledger below it. parse_markdown_table()
    reads the FIRST table's header (and every block that repeats it), so a session
    that opened the file with `| version | payload files | ... |` had that four-row
    summary parsed AS the ledger and failed with "4 ledger row(s) carry no
    `artifact`" although the ledger itself was complete and correct (r1_i3,
    2026-09-22 -- that failure cost the whole repair session). Pick the table that
    carries the ledger's own columns; fall back to the first table when the file
    has no such table, so a truly column-less ledger still reports what it lacked.
    """
    blocks = parse_markdown_blocks(path)
    if not blocks:
        return []
    def score(block) -> int:
        head = [str(c).strip().lower() for c in (block.get("header") or [])]
        return sum(1 for c in INTEGRATION_LEDGER_COLUMNS if c in head)
    best = max(range(len(blocks)), key=lambda i: score(blocks[i]))
    if score(blocks[best]) >= 2:
        head = blocks[best]["header"]
        return [row for b in blocks if b["header"] == head for row in b["rows"]]
    head = blocks[0]["header"]
    return [row for b in blocks if b["header"] == head for row in b["rows"]]


def integration_ledger_report(out: Path, donors: list, expect_both_levels: bool) -> dict:
    """Parse integrated/DIFF_LEDGER.md: size classes, artifacts, finding effects."""
    rows = integration_ledger_rows(out / "DIFF_LEDGER.md")
    sizes, missing_artifact, missing_finding, undoes, seen_donors = Counter(), [], [], [], set()
    for r in rows:
        size = str(r.get("size") or "").strip().lower()
        sizes[size] += 1
        donor = str(r.get("donor") or "").strip()
        if donor:
            seen_donors.add(donor)
        if not str(r.get("artifact") or "").strip():
            missing_artifact.append(donor or "?")
        fe_raw = str(r.get("finding effect") or r.get("finding_effect") or "").strip()
        fe = fe_raw.lower()
        if not fe:
            missing_finding.append(donor or "?")
        elif fe.startswith("undo"):
            # Keep the id's own case in the message ("undoes F-002"): the
            # warning goes to a human and to the change log.
            undoes.append(f"{donor or '?'}: {fe_raw}")
    absent = [d for d in donors if d and not any(d in s for s in seen_donors)]
    return {"rows": len(rows), "sizes": dict(sizes), "missing_artifact": missing_artifact,
            "missing_finding": missing_finding, "undoes": undoes, "donors_absent": absent,
            "both_levels": bool(sizes.get("small") and sizes.get("large")),
            "expect_both_levels": bool(expect_both_levels)}


def rewrite_pool_levels(ctx: Ctx, r: int) -> dict:
    """The rewrite levels staged in this round: {level: [run ids]}."""
    out = {}
    for rec in (ctx.state.get("runs") or {}).values():
        if rec.get("kind") != "rewrite" or int(rec.get("round") or 0) != int(r):
            continue
        out.setdefault(str(rec.get("rewrite_level") or ""), []).append(rec.get("id"))
    return out


def add_stage_quality_checks(ctx: Ctx, rec: dict, before_sources: list, after_sources: list,
                             pkg: Path, label: str, errs: list, warns: list) -> None:
    """The language pass + the "no NEW finding-tier family" comparison."""
    check_language_pass(ctx, rec, pkg, label, errs, warns)
    # A caption the format fixer MERGED changes how the caption's text is read
    # (a continuation paragraph becomes part of its legend), so a rule the fixer
    # itself gained rows for is attributed to the normalizer, not to this
    # stage's edit -- reported as a warning that names the FORMAT_FIX artifact.
    merged_captions = any(
        "multi-paragraph caption" in str(change)
        for doc in ((rec.get("format_fix") or {}).get("documents") or [])
        for change in (doc.get("changes") or []))
    reclassified = set(rec.get("format_fix_rules_introduced") or ()) if merged_captions else set()
    rerrs, rwarns = scan_regression_problems(ctx, before_sources, after_sources, label,
                                             fixer_reclassified=reclassified)
    errs.extend(rerrs)
    warns.extend(rwarns)
AUDIT_VERDICTS = ("confirm", "drop")
AUDIT_SEVERITIES = ("critical", "major", "minor", "fatal")


def audit_artifact_problems(audit, frozen_ids) -> list:
    """Every problem that makes an `audit/audit.json` unusable (pure, testable).

    The contract is deliberately about DISPOSITIONS, not opinions: every frozen
    id appears exactly once as confirm/drop, a drop carries a reason AND
    evidence (so a human can re-open it), and an added finding has the same
    shape as a review finding.  A drop that says "cannot tell" is not allowed:
    an undecidable finding must be confirmed, because dropping it would hide it
    from the reviser.
    """
    problems = []
    if not isinstance(audit, dict):
        return ["audit/audit.json does not parse as a JSON object"]
    frozen = [str(i).strip() for i in (frozen_ids or []) if str(i).strip()]
    disp = audit.get("dispositions")
    if not isinstance(disp, list):
        problems.append("audit/audit.json has no 'dispositions' list "
                        "(one row per frozen finding id: confirm or drop)")
        disp = []
    seen = {}
    for i, row in enumerate(disp):
        if not isinstance(row, dict):
            problems.append(f"dispositions[{i}] is not an object")
            continue
        fid = str(row.get("id") or "").strip()
        verdict = str(row.get("verdict") or "").strip().lower()
        reason = str(row.get("reason") or "").strip()
        evid = str(row.get("evidence") or "").strip()
        if not fid:
            problems.append(f"dispositions[{i}] has no id")
            continue
        if fid in seen:
            problems.append(f"{fid} appears twice in dispositions")
        seen[fid] = verdict
        if verdict not in AUDIT_VERDICTS:
            problems.append(f"{fid}: verdict {verdict!r} is not confirm|drop")
            continue
        if verdict == "drop":
            if len(reason) < 20:
                problems.append(f"{fid}: a drop needs a reason (>=20 characters) the human "
                                f"can re-check")
            if len(evid) < 40:
                problems.append(f"{fid}: a drop needs EVIDENCE (>=40 characters: the verbatim "
                                f"text, or the file:line derivation, that refutes the finding)")
    missing = [i for i in frozen if i not in seen]
    if missing:
        problems.append(f"{len(missing)} frozen finding id(s) are neither confirmed nor dropped "
                        f"(silence is not a disposition): {', '.join(missing[:6])}"
                        + (" ..." if len(missing) > 6 else ""))
    unknown = [i for i in seen if frozen and i not in frozen]
    if unknown:
        problems.append(f"dispositions name {len(unknown)} id(s) that are not in the frozen "
                        f"review: {', '.join(unknown[:6])}")
    adds = audit.get("adds")
    if adds is None:
        adds = []
    if not isinstance(adds, list):
        problems.append("audit/audit.json 'adds' is not a list")
        adds = []
    seen_add = set()
    for i, row in enumerate(adds):
        if not isinstance(row, dict):
            # The `dispositions` loop above already reports a non-object row
            # instead of dereferencing it; this loop read `row.get(...)`
            # unconditionally and crashed cmd_selfcheck with an AttributeError.
            problems.append(f"adds[{i}] is not an object")
            continue
        aid = str(row.get("id") or "").strip()
        if not AUDIT_ID_RE.match(aid):
            problems.append(f"adds[{i}] id {aid!r} is not AU-<n>")
            aid = aid or f"adds[{i}]"
        if aid in seen_add:
            problems.append(f"added finding {aid} appears twice")
        seen_add.add(aid)
        for field, minimum in (("location", 3), ("evidence", 8), ("problem", 20)):
            if len(str(row.get(field) or "").strip()) < minimum:
                problems.append(f"{aid}: '{field}' is missing or too short")
        if str(row.get("severity") or "").strip().lower() not in AUDIT_SEVERITIES:
            problems.append(f"{aid}: severity must be Critical|Major|Minor|Fatal")
        cat = row.get("category")
        if isinstance(cat, str) and cat.strip().isdigit():
            cat = int(cat.strip())
        if not isinstance(cat, int) or not 0 <= cat <= 5:
            problems.append(f"{aid}: category must be an integer 0-5")
        if not str(row.get("check") or "").strip():
            problems.append(f"{aid}: the check id (M1-M36/J1-J5) is missing")
    return problems


def audit_effect_summary(split: dict) -> dict:
    """The audit statistics recorded on the run (pure, testable).

    `kept` is the frozen findings the auditor did NOT drop -- exactly the
    confirmed ones -- and `added` is a disjoint set of new AU-* findings. The
    record used to subtract `added` from `kept`, which made a run with one drop
    and two adds report 7 confirmed out of 10 frozen findings, and could go
    negative once the auditor added more findings than were kept.
    """
    return {"confirmed": len(split["kept"]),
            "dropped": len(split["dropped"]),
            "added": len(split["added"]),
            "effective": len(split["effective"])}


def apply_audit_to_findings(findings, audit) -> dict:
    """Split a finding list by an audit record (pure, testable)."""
    drops = {str(d.get("id") or "").strip()
             for d in ((audit or {}).get("dispositions") or []) if isinstance(d, dict)
             and str(d.get("verdict") or "").strip().lower() == "drop"}
    adds = [f for f in ((audit or {}).get("adds") or []) if isinstance(f, dict)]
    kept, dropped = [], []
    for f in (findings or []):
        if not isinstance(f, dict):
            continue
        (dropped if str(f.get("id") or "").strip() in drops else kept).append(f)
    return {"kept": kept, "dropped": dropped, "added": adds,
            "effective": kept + adds}


def _frozen_review_findings(sb: Path) -> list:
    out = []
    for rel in (FINDINGS_REL, "review/round2/findings_extra.json"):
        fj = read_json(sb / rel, revive=False, lenient=True)      # agent-written
        if isinstance(fj, dict):
            for f in fj.get("findings") or []:
                if isinstance(f, dict):
                    out.append(f)
    return out


def _probe_audit_verdict(row) -> str:
    """The verdict token of one PROBE_AUDIT row ("" when none is stated)."""
    for v in row.values():
        cell = " ".join(str(v or "").split())
        low = cell.lower()
        if low.startswith(("stands", "promoted", "needs-evidence", "needs evidence")):
            return cell
    return ""


def probe_audit_problems(sb: Path) -> list:
    """Errors for the auditor's attack on the discovery round's probe rows.

    The auditor exists to attack the reviewer's boilerplate closures, but the
    discovery round's probe dispositions were outside its surface: a probe
    closed "no anomalies -- checked: <locations>" with nothing checked, or one
    blanket sentence shared by 25 rows, was never audited. When the frozen
    review carries probe rows the auditor disposes them one row each in
    `audit/PROBE_AUDIT.md` (`stands` / `promoted to AU-xxx` / `needs-evidence`),
    and a promotion must name a real `AU-*` finding.
    """
    ids = discovery_probe_result_ids(sb)
    if not ids:
        return []
    head = ", ".join(ids[:5]) + (" ..." if len(ids) > 5 else "")
    path = sb / "audit" / "PROBE_AUDIT.md"
    if not _discovery_nonempty(path):
        return [f"review/round2/probe_results.md carries {len(ids)} probe disposition(s) "
                f"({head}) but audit/PROBE_AUDIT.md is missing or empty: the auditor must "
                f"attack the discovery round's probe closures one row each (verdict `stands` / "
                f"`promoted to AU-xxx` / `needs-evidence`), exactly like the reviewer's "
                f"finding-tier rows -- a blanket 'no anomalies' is the same boilerplate this "
                f"stage exists to promote"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    errors = []
    seen, verdictless = set(), []
    for r in _discovery_rows(path):
        m = DISCOVERY_PROBE_ID_RE.search(_row_text(r))
        if not m:
            continue
        pid = m.group(0)
        seen.add(pid)
        if not _probe_audit_verdict(r):
            verdictless.append(pid)
    missing = [p for p in ids if p not in seen]
    if missing:
        errors.append(
            f"audit/PROBE_AUDIT.md does not dispose probe(s) "
            f"{', '.join(missing[:6])}" + (" ..." if len(missing) > 6 else "")
            + ": one row per probe result, with the verdict `stands` / `promoted to AU-xxx` / "
              "`needs-evidence`")
    if verdictless:
        errors.append(
            f"audit/PROBE_AUDIT.md row(s) {', '.join(verdictless[:6])} carry no verdict: state "
            f"`stands` (the reviewer's disposition is rule-specific and stands), `promoted to "
            f"AU-xxx`, or `needs-evidence` (say what evidence the closure lacks)")
    aj = read_json(sb / "audit" / "audit.json", revive=False, lenient=True)
    adds = {}
    if isinstance(aj, dict):
        adds = {str(f.get("id") or "").strip() for f in (aj.get("adds") or [])
                if isinstance(f, dict) and str(f.get("id") or "").strip()}
    promoted = {a.upper() for a in re.findall(r"\bpromoted\s+to\s+(AU-[A-Za-z0-9-]+)", text, re.I)}
    unknown = sorted(a for a in promoted if a not in adds)
    if unknown:
        errors.append(
            f"audit/PROBE_AUDIT.md promotes probe row(s) to {', '.join(unknown)} but audit.json's "
            f"`adds` list defines no such finding: a promoted row must name the AU-* finding it "
            f"became, so the revisers resolve it")
    return errors


def postcheck_audit(ctx: Ctx, rec: dict):
    """The auditor's deliverable: a complete, evidenced disposition of the review."""
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "audit", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    frozen = _frozen_review_findings(sb)
    frozen_ids = [str(f.get("id") or "").strip() for f in frozen if str(f.get("id") or "").strip()]
    aj = sb / "audit" / "audit.json"
    if not aj.is_file():
        errs.append("audit/audit.json is missing: the auditor's dispositions are the deliverable "
                    "the revisers consume (one row per frozen finding id, plus its `AU-` adds)")
    else:
        audit = read_json(aj, revive=False, lenient=True)         # agent-written
        problems = audit_artifact_problems(audit, frozen_ids)
        errs.extend(problems)
        if not problems:
            split = apply_audit_to_findings(frozen, audit)
            rec["audit_effect"] = dict(
                audit_effect_summary(split),
                dropped_ids=[str(f.get("id")) for f in split["dropped"]],
                added_ids=[str(f.get("id")) for f in split["added"]],
            )
            if split["dropped"]:
                warns.append(
                    f"the auditor dropped {len(split['dropped'])} of the frozen review's "
                    f"findings ({', '.join(rec['audit_effect']['dropped_ids'][:5])}) -- each "
                    f"drop carries evidence in audit/audit.json; the revisers will not see them")
            if split["added"]:
                warns.append(f"the auditor added {len(split['added'])} finding(s) "
                             f"({', '.join(rec['audit_effect']['added_ids'][:5])}) that the "
                             f"revisers must resolve")
            m = marker or {}
            if is_int(m.get("findings_total")) and int(m["findings_total"]) != len(frozen_ids):
                warns.append(f"marker findings_total={m['findings_total']} but the frozen review "
                             f"lists {len(frozen_ids)} id(s)")
    if not (sb / "audit" / "AUDIT.md").is_file():
        warns.append("audit/AUDIT.md (the human-readable disposition record) was not found; a "
                     "dropped finding must stay re-checkable by a human")
    # The discovery round's probe rows are dispositions too: the auditor attacks
    # each of them (or says why it could not), one row per probe.
    errs.extend(probe_audit_problems(sb))
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


def postcheck_review(ctx: Ctx, rec: dict):
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "review", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    fp = sb / FINDINGS_REL
    if not fp.is_file():
        errs.append(f"{FINDINGS_REL} is missing (it is the deliverable Phase 2 consumes)")
    else:
        fj = read_json(fp, revive=False, lenient=True)  # agent-written
        if not isinstance(fj, dict):
            errs.append(f"{FINDINGS_REL} does not parse as a JSON object")
        else:
            if not isinstance(fj.get("findings"), list):
                errs.append(f"{FINDINGS_REL} has no 'findings' list")
            elif not fj["findings"]:
                warns.append(f"{FINDINGS_REL} lists zero findings (valid only if the corpus is "
                            f"genuinely clean; check the coverage table)")
            check_review_contract(ctx, sb, fj, errs, warns,
                                  scope=round_review_scope(ctx, int(rec.get("round") or 1)))
            if journal_has_feedback(ctx) and not journal_is_scoped(ctx):
                # `llm` mode has a feedback ledger too, and the review block
                # tells it to reconcile every concern; skipping the coverage
                # check let a session silently drop the whole ledger and pass.
                errs.extend(journal_review_coverage_problems(ctx, rec, sb, fj))
    # DISPOSITION QUALITY: the reviewer's own decision tables. Recorded always;
    # it FAILS the attempt only under `setup --strict-artifacts on`, and
    # `decide --residual-gate` refuses to certify a run that carries it.
    check_artifact_quality(ctx, rec, sb, errs, warns)
    rec["residual"] = placeholder_residual_report(ctx, sb, [(sb / "base", "", ())],
                                                  "review", enforce=False, errs=errs, warns=warns)
    if word_docs_present([sb / "base"]):
        check_visual_artifact(sb / VISUAL_ARTIFACT_REVIEW,
                              f"the visual-inspection record {VISUAL_ARTIFACT_REVIEW}",
                              errs, warns, sandbox=sb, render_roots=[sb / REVIEW_DIR])
    # THE DISCOVERY ROUND'S CONTRACT (D0-D5): the phase's deliverables are
    # quality-checked, not just existence-checked (see
    # `discovery_contract_problems`). The problems follow the review's
    # `--strict-artifacts` policy -- fail by default, warn under
    # `--strict-artifacts off` -- and the list is recorded for
    # `decide --residual-gate`. A "formatting-writing" round never runs the
    # phase, and under a phases/aspects split only session B carries it.
    if review_owes_discovery(ctx, rec):
        rec["discovery_contract"] = check_discovery_contract(ctx, sb, errs, warns)
    elif not any((sb / rel).exists() for rel in DISCOVERY_RELS):
        warns.append("no discovery-round artifact under review/round2/ -- the D0-D5 phase cannot "
                     "be verified")
    _check_pristine_copy(ctx, rec, pristine_dirname(ctx.sandbox_of(rec)), errs)
    errs.extend(input_mismatches(ctx, rec))
    # SPLIT REVIEW: this is part B, so the two sessions' findings are merged into
    # ONE frozen list here (A's ids must survive; the union must dispose every
    # check id both sessions were given). This lives in the REVIEW postcheck: the
    # dispatcher routes a revise record to postcheck_revise, so the guard can
    # never fire there and the merge would never run at all.
    if not errs and review_split_of(ctx) != "off" and rec.get("id") == rid_review_b(
            int(rec.get("round") or 1)):
        try:
            m = merge_review_parts(ctx, rec)
            rec["review_merge"] = m
            a_ids = set(frozen_finding_ids(ctx, ctx.run(rid_review(int(rec["round"]))) or {}))
            merged_ids = set(frozen_finding_ids(ctx, rec))
            missing = sorted(a_ids - merged_ids)
            if missing:
                errs.append(f"the split-review merge lost {len(missing)} finding id(s) from "
                            f"session A: {', '.join(missing[:5])}")
            print(f"[review] split merge: {m['from_a']} finding(s) from session A + "
                  f"{m['from_b']} from session B -> {len(merged_ids)} frozen id(s)"
                  + (f"; id remap {m['id_remap']}" if m["id_remap"] else ""))
        except Exception as e:                                        # noqa: BLE001
            errs.append(f"the split-review merge failed ({type(e).__name__}: {e})")
    return (not errs), errs, warns, None


def postcheck_revise(ctx: Ctx, rec: dict):
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "revise", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    rev = sb / REVISED_DIR
    _format_fix_stage_package(ctx, rec, rev, warns, errs)
    if not (rev.is_dir() and any(rev.iterdir())):
        errs.append("revised/ is missing or empty (a non-empty revised/ is required, though it is "
                    "not by itself a completion signal)")
    if count_manual_steps(rev / "MANUAL_STEPS.md") is None \
            and count_manual_steps(sb / "MANUAL_STEPS.md") is None:
        warns.append("MANUAL_STEPS.md not found under revised/ (the decision report will show the "
                     "manual-item count as unknown; the count is reported only and never ranked)")
    # The revision ledger is the deliverable that proves "no finding silently
    # dropped": require the machine-readable one, and ask for a human-readable
    # counterpart.
    lerrs, lwarns = revision_ledger_problems(rev, frozen_finding_ids(ctx, rec),
                                             frozen_findings_total(ctx, rec))
    errs.extend(lerrs)
    warns.extend(lwarns)
    # WHOLE-PARAGRAPH RE-READ (2026-10-19): a revision that edits only the
    # quoted sentence can leave the paragraph's other sentence contradicting it
    # (the round-2 "chiefly accompanied by" and "near-invariance" cases). Ask for
    # one REREAD note per fixed finding; a missing note is reported, not gated
    # (the audit may still find the residue).
    try:
        _rr = read_json(rev / "revision_report.json", revive=False, lenient=True) or {}
        _rows = _rr.get("ledger") or _rr.get("findings") or _rr.get("coverage") or []
        _fixed = [str(r.get("id")) for r in _rows if isinstance(r, dict)
                  and str(r.get("final_status") or r.get("status") or "") in
                  ("fixed", "fixed-with-caveat")]
        _notes = list((rev / "work").glob("REREAD_*.md"))
        _missing = [fid for fid in _fixed
                    if not any(_finding_id_mentioned(fid, q.name) for q in _notes)]
        if _missing:
            warns.append(
                f"{len(_missing)} fixed finding(s) have no revised/work/REREAD_<id>.md "
                f"note ({', '.join(_missing[:6])}): a sentence-local edit must re-read "
                f"the containing paragraph and its neighbour, or the next round will find "
                f"the contradiction the edit left behind")
    except Exception as e:                                            # noqa: BLE001
        warns.append(f"the REREAD-note check could not read the revision ledger "
                     f"({type(e).__name__}: {e}); the whole-paragraph re-read is not "
                     f"verified for this stage")
    # REWRITE-PARITY EVIDENCE: the frozen review may carry the classes a
    # from-scratch rewrite fixes as it goes (M25-M30) and the scope-level
    # architecture findings (J5). Their fixes have their own required
    # artifacts (E11): the convention re-run for M26, and one RESTRUCTURE note
    # per J5 scope. Absence is reported here; the ledger and the residue gate
    # carry the final judgement.
    frozen_all = _frozen_review_findings(sb)
    aud = read_json(sb / "audit" / "audit.json", revive=False, lenient=True) \
        if (sb / "audit" / "audit.json").is_file() else None
    if isinstance(aud, dict):
        frozen_all = frozen_all + [f for f in (aud.get("adds") or []) if isinstance(f, dict)]
    checks_in = {str(f.get("check") or "").strip().upper() for f in frozen_all}
    if "M26" in checks_in:
        style = rev / "work"
        if not any(style.glob("STYLE_VARIANTS.*")) and not (style / "STYLE_CONVENTIONS.md").is_file():
            warns.append("the frozen review carries M26 house-style convention findings but "
                         "revised/work/ has no STYLE_VARIANTS.* / STYLE_CONVENTIONS.md with "
                         "the M26 convention re-run (E11); the corpus-wide completion of a "
                         "convention must be provable, not asserted")
    j5_ids = [str(f.get("id") or "").strip() for f in frozen_all
              if str(f.get("check") or "").strip().upper() == "J5"]
    if j5_ids:
        notes = list((rev / "work").glob("RESTRUCTURE_*.md"))
        if not notes:
            warns.append(f"the frozen review carries {len(j5_ids)} J5 architecture finding(s) "
                         f"but revised/work/ has no RESTRUCTURE_<finding-id>.md note: E11 "
                         f"requires one per scope (BEFORE/AFTER outline, moved paragraphs, "
                         f"diff hunk ids, preservation check)")
        else:
            missing_notes = [fid for fid in j5_ids
                             if not any(fid in p.name for p in notes)]
            if missing_notes:
                warns.append(f"J5 finding(s) {missing_notes} have no RESTRUCTURE_<id>.md note "
                             f"under revised/work/: every restructuring must be re-checkable")
    # M30 (source-hierarchy reconciliation): the evidence is the stage's own
    # seeded ledger. Every row disposed means the revision looked at the written
    # value AND its producer; an empty disposition cell means the comparison the
    # finding rests on was never recorded (rule E12).
    m30_ids = [str(f.get("id") or "").strip() for f in frozen_all
               if str(f.get("check") or "").strip().upper() == "M30"]
    if m30_ids:
        ledger = sb / "work" / "M30_hierarchy_reconciliation.md"
        if not ledger.is_file():
            warns.append(f"the frozen review carries {len(m30_ids)} M30 source-hierarchy "
                         f"finding(s) but the sandbox has no work/M30_hierarchy_reconciliation.md: "
                         f"rule E12 requires the written side to be aligned with the authoritative "
                         f"producer, with the reconciling reason recorded")
        else:
            try:
                block_problems = []
                for block in parse_markdown_blocks(ledger):
                    if block["rows"]:
                        block_problems += disposition_artifact_problems(
                            block["rows"], block.get("widths"), len(block["header"]))
                if block_problems:
                    warns.append(f"work/M30_hierarchy_reconciliation.md still carries "
                                 f"{len(block_problems)} undisposed row(s) ({block_problems[0][:80]}): "
                                 f"an M30 finding's fix must record the producer it reconciled "
                                 f"against (rule E12)")
            except Exception as e:                                  # noqa: BLE001
                warns.append(f"work/M30_hierarchy_reconciliation.md could not be read ({e}); "
                             f"the M30 rows stay unverified")
    if not (rev / "CHANGELOG.md").is_file() and not (rev / "REVISION_REPORT.md").is_file():
        warns.append("neither revised/CHANGELOG.md nor revised/REVISION_REPORT.md was found "
                     "(the human-readable ledger/change log)")
    summ = rec.get("summary") or {}
    for key in ("findings_total", "fixed", "critical_remaining", "writing_remaining",
                "manual_items"):
        if not is_int(summ.get(key)):
            warns.append(f"marker summary.{key} is missing/not an integer "
                         f"(the reported quality/tie-break numbers need it)")
        elif int(summ[key]) < 0:
            warns.append(f"marker summary.{key}={summ[key]} is NEGATIVE; it is ignored for the "
                         f"tie-break and must be corrected in the final report")
    tiebreak_selfreport_warnings(ctx, rec, summ, warns)
    # Recovery BEFORE the document-set comparison: restore every base file the
    # agent dropped (any type) so the invariant holds by construction, and the
    # drop is reported instead of costing another agent session.
    rec["backfill"] = backfill_missing_files(ctx, rec, [(sb / "base", "", ())], warns)
    errs.extend(f"document recovery failed: {e}" for e in rec["backfill"]["unresolved"])
    # AFTER the recovery, so the READ-ONLY raw-data directory ends up exactly as
    # the untouched original has it -- never as the base (or a donor) left it.
    rec["raw_data"] = verify_readonly_raw_data(ctx, rev, warns)
    errs.extend(rec["raw_data"].get("legacy_input_areas") or [])
    # AFTER the read-only repair: the recorded token describes the package that
    # ships, not the one the agent left before the repair.
    _record_revision_token(rec, rev, warns, errs=errs,
                           pipeline_changed=bool((rec.get("format_fix") or {}).get("changes")))
    _caption_and_document_checks(ctx, rec, _rec_vid(rec), [(sb / "base", "", ())], errs, warns)
    if word_docs_present([rev]):
        check_visual_artifact(rev / "VISUAL_CHECK.md",
                              f"the visual-inspection record {VISUAL_ARTIFACT_REVISED}",
                              errs, warns, sandbox=sb, render_roots=[rev])
    # RESIDUALS: a `searchable` hand-off marker the pipeline could already answer
    # must not ship (the reviewer of a real run saw one carried into a submitted
    # cover letter although the answer was a recorded lookup away), and a number
    # in the abstract or a legend that no shipped table proves is reported.
    residual = placeholder_residual_report(ctx, sb, [(rev, "", CORPUS_EXCLUDE_TOP)],
                                           "revise", enforce=True, errs=errs, warns=warns)
    prov = number_provenance_report(sb, [(rev, "", CORPUS_EXCLUDE_TOP)])
    residual.update({"unsourced_numbers_in_abstract_legends": prov.get("unsourced", 0),
                     "proved_numbers": prov.get("proved", 0),
                     "unsourced_examples": prov.get("examples", [])})
    rec["residual"] = residual
    if prov.get("unsourced"):
        warns.append(f"{prov['unsourced']} number(s) in the abstract/legends are not proved by "
                     f"any shipped data table ({prov.get('proved', 0)} are) -- see "
                     f"work/NUMBERS_LEDGER.md and fill the `source` column, or record why the "
                     f"number cannot be sourced; `decide --residual-gate` lists them")
    if audit_enabled(ctx):
        effect = (ctx.run(rid_audit(int(rec["round"]))) or {}).get("audit_effect") or {}
        if effect:
            rec["audit_effect"] = effect
            if effect.get("dropped"):
                warns.append(f"this revision acted on the AUDITED list: the auditor dropped "
                             f"{effect['dropped']} frozen finding(s) "
                             f"({', '.join(effect.get('dropped_ids') or [])[:80]}) and added "
                             f"{effect.get('added', 0)}")
    # W-12: the language pass of this stage (one row per change + one coverage
    # row per step) and the "no NEW finding-tier family" comparison.
    add_stage_quality_checks(ctx, rec, [(sb / "base", "", ())],
                             [(rev, "", CORPUS_EXCLUDE_TOP)],
                             rev, "revise", errs, warns)
    # HARD check: Phase 2 must not touch the frozen review/ copy.
    _check_pristine_copy(ctx, rec, pristine_dirname(ctx.sandbox_of(rec)), errs)
    errs.extend(input_mismatches(ctx, rec))
    if journal_is_scoped(ctx):
        # A major/minor revision may change the manuscript ONLY where a reviewer
        # concern requires it: every changed file must be named in the revision
        # ledger, and no file may be added or removed. The orchestrator's own
        # PKG-2 removal (a dangling reference edited out before this check) is
        # exempt and reported: the session neither made that edit nor could name
        # it.
        _pipe_files = [f.get("file") for f in
                       ((rec.get("reference_strip") or {}).get("files") or [])
                       if f.get("removed")]
        if _pipe_files:
            warns.append("the orchestrator removed a dangling reference (PKG-2) from "
                         + ", ".join(f"`{f}`" for f in _pipe_files[:4])
                         + " -- a submission-surface repair, not a concern-driven edit; the "
                           "removed sentences are in the run record (reference_strip)")
        errs.extend(scoped_scope_problems(ctx, sb, rev, pipeline_changed=_pipe_files))
    return (not errs), errs, warns, None


SPLIT_ID_RE = re.compile(r"^(?:FA|FB)-\d+")


def merge_review_parts(ctx: Ctx, rec_b: dict) -> dict:
    """Concatenate the two split review sessions into ONE frozen finding list.

    Deterministic and code-side: A's `findings.json` rows are kept verbatim, B's
    rows follow, id collisions get a `B-` prefix (recorded in the merge block),
    coverage tables are unioned by check id (A wins on a conflict, the conflict
    is recorded) and the discovery findings are concatenated. The merged file is
    written into B's `review/`, which is the directory the revise sessions copy.
    """
    r = int(rec_b["round"])
    a_sb = ctx.sandbox_of(ctx.run(rid_review(r)) or {"sandbox": f"runs/{rid_review(r)}"})
    b_sb = ctx.sandbox_of(rec_b)
    a_json = read_json(a_sb / REVIEW_DIR / "findings.json", revive=False, lenient=True) or {}
    b_json = read_json(b_sb / REVIEW_DIR / "findings.json", revive=False, lenient=True) or {}
    a_items = [dict(f) for f in (a_json.get("findings") or []) if isinstance(f, dict)]
    b_items = [dict(f) for f in (b_json.get("findings") or []) if isinstance(f, dict)]
    seen = {str(f.get("id")) for f in a_items}

    def _dedup_key(row: dict) -> tuple:
        """(location, evidence prefix): the same defect found by both sessions."""
        loc = " ".join(str(row.get("location") or "").lower().split())
        ev = " ".join(str(row.get("evidence") or row.get("quote") or "").lower().split())
        return loc, ev[:80]

    a_keys = {_dedup_key(f) for f in a_items}
    remap = {}
    deduped = []
    b_kept = []
    for f in b_items:
        key = _dedup_key(f)
        if key != ("", "") and key in a_keys:
            # Both sessions found the same defect at the same place with the same
            # evidence: keep A's row (ids and coverage ride with it) instead of
            # handing the reviser two rows for one thing.
            deduped.append(str(f.get("id")))
            continue
        fid = str(f.get("id"))
        if fid in seen:
            new = f"B-{fid}"
            while new in seen:
                new = "B-" + new
            remap[fid] = new
            f["id"] = new
        seen.add(str(f.get("id")))
        b_kept.append(f)
    coverage, conflicts = [], []
    have = set()
    for src in (a_json.get("coverage") or [], b_json.get("coverage") or []):
        for row in src:
            if not isinstance(row, dict):
                continue
            check = str(row.get("check") or "")
            if check in have:
                conflicts.append(check)
                continue
            have.add(check)
            coverage.append(row)
    artifacts = dict(a_json.get("artifacts") or {})
    artifacts.update({k: v for k, v in (b_json.get("artifacts") or {}).items()
                      if k not in artifacts})
    merged = {"submission_dir": a_json.get("submission_dir") or b_json.get("submission_dir"),
              "guidelines_source": (a_json.get("guidelines_source")
                                    or b_json.get("guidelines_source")),
              "findings": a_items + b_kept, "artifacts": artifacts,
              "coverage": coverage,
              "split_review": {"mode": review_split_of(ctx),
                               "sessions": [rid_review(r), rid_review_b(r)],
                               "from_a": len(a_items), "from_b": len(b_kept),
                               "deduped_b": deduped,
                               "id_remap": remap, "coverage_conflicts": sorted(set(conflicts))}}
    write_json_atomic(b_sb / REVIEW_DIR / "findings.json", merged)
    # The discovery round's findings travel with the frozen list too.
    extra = []
    for sb in (a_sb, b_sb):
        doc = read_json(sb / REVIEW_DIR / "round2" / "findings_extra.json",
                        revive=False, lenient=True) or {}
        extra += [f for f in (doc.get("findings") or []) if isinstance(f, dict)]
    if extra:
        # Keep each side's D4 coverage list: rewriting the file with an EMPTY
        # coverage dropped part B's own D4 record from the merged artifact the
        # reviser and the archived ledger read.
        coverage = []
        for sb in (a_sb, b_sb):
            doc = read_json(sb / REVIEW_DIR / "round2" / "findings_extra.json",
                            revive=False, lenient=True) or {}
            for row in (doc.get("coverage") or []):
                if row not in coverage:
                    coverage.append(row)
        write_json_atomic(b_sb / REVIEW_DIR / "round2" / "findings_extra.json",
                          {"findings": extra, "coverage": coverage})
    return merged["split_review"]


def postcheck_integrate(ctx: Ctx, rec: dict):
    """The integration arm's contract: self/ reworked with the WHOLE pool.

    One run per pool member. It is checked like the other content-producing
    stages, and it additionally has to show that it looked at EVERY donor: the
    ledger must exist, and the donor directories must be exactly the pool minus
    the run's own member (checked by the input-freshness layer).
    """
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "integrate", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    out = sb / INTEGRATED_DIR
    _format_fix_stage_package(ctx, rec, out, warns, errs)
    if not (out.is_dir() and any(out.iterdir())):
        errs.append(f"{INTEGRATED_DIR}/ is missing or empty (the integrated package is this "
                    f"stage's deliverable)")
    if not (sb / INTEGRATION_LEDGER_REL).is_file():
        errs.append(f"{INTEGRATION_LEDGER_REL} is missing: it is this stage's ledger (one row per "
                    f"ported or deliberately skipped difference, with the hierarchy-based "
                    f"justification, covering EVERY donor)")
    if not (sb / "others").is_dir():
        errs.append("others/ is missing: this run consumes the WHOLE candidate pool")
    elif not any(p.is_dir() for p in (sb / "others").iterdir()):
        warns.append("others/ contains no donor directory; the integration had nothing to "
                     "incorporate from")
    if not (out / "revision_report.json").is_file():
        warns.append(f"{INTEGRATED_DIR}/revision_report.json not found (the revision skill's "
                     f"machine-readable ledger; the integration stage's own ledger is "
                     f"{INTEGRATION_LEDGER_REL})")
    # Every donor must be visible in the ledger: a donor the agent never looked
    # at is the failure mode this stage exists to prevent, and the ledger row is
    # the evidence that it was read. Reported as a warning (the ledger is prose,
    # so a donor may legitimately be named differently in it), never a hard fail.
    donors = list(rec.get("other_ids") or [])
    ledger = sb / INTEGRATION_LEDGER_REL
    if donors and ledger.is_file():
        try:
            text = ledger.read_text(encoding="utf-8", errors="replace")
        except OSError as e:                                          # noqa: BLE001
            text = ""
            warns.append(f"{INTEGRATION_LEDGER_REL} could not be read ({e})")
        missing = [d for d in donors if not _finding_id_mentioned(str(d), text)]
        if missing:
            warns.append(f"{INTEGRATION_LEDGER_REL} does not mention donor(s) {missing}; every "
                         f"donor of the pool must appear in the ledger (a donor with nothing to "
                         f"port gets an explicit no-difference row) so the whole pool is provably "
                         f"accounted for")
    # Contract: the round's frozen discovery list is reconciled BY ID in the
    # ledger -- a resolution the revise arm made must not vanish in the merge.
    # Hard under the default strict policy (the ledger is machine-parsable
    # bookkeeping and the rows are mechanical), a warning otherwise.
    if rec.get("discovery_ids"):
        msgs = discovery_ledger_reconciliation_problems(ledger, rec.get("discovery_ids"))
        (errs if strict_dispositions(ctx) else warns).extend(msgs)
    summ = rec.get("summary") or {}
    for key in ("critical_remaining", "writing_remaining", "manual_items"):
        if not is_int(summ.get(key)):
            warns.append(f"marker summary.{key} is missing/not an integer "
                         f"(the report needs it; the ranking uses statistics first)")
        elif int(summ[key]) < 0:
            warns.append(f"marker summary.{key}={summ[key]} is NEGATIVE; a count of open "
                         f"findings or manual items cannot be negative, so the value is ignored "
                         f"for the ranking (treated like a missing number) -- check the agent's "
                         f"final report")
    tiebreak_selfreport_warnings(ctx, rec, summ, warns)
    if is_int(summ.get("donors_read")) and donors and int(summ["donors_read"]) != len(donors):
        warns.append(f"marker summary.donors_read={summ['donors_read']} but this run has "
                     f"{len(donors)} donor(s); the marker's audit number does not match the pool")
    # Same recovery as the revise stage, measured against this run's SELF copy.
    rec["backfill"] = backfill_missing_files(ctx, rec, [(sb / "self", "", ())], warns)
    errs.extend(f"document recovery failed: {e}" for e in rec["backfill"]["unresolved"])
    rec["raw_data"] = verify_readonly_raw_data(ctx, out, warns)
    errs.extend(rec["raw_data"].get("legacy_input_areas") or [])
    _record_revision_token(rec, out, warns, errs=errs)
    _caption_and_document_checks(ctx, rec, freshness_vid(rec), [(sb / "self", "", ())],
                                 errs, warns)
    if word_docs_present([out]):
        check_visual_artifact(out / "VISUAL_CHECK.md",
                              f"the visual-inspection record {VISUAL_ARTIFACT_INTEGRATED}",
                              errs, warns, sandbox=sb, render_roots=[out])
    residual = placeholder_residual_report(ctx, sb, [(out, "", CORPUS_EXCLUDE_TOP)],
                                           "integrate", enforce=True, errs=errs, warns=warns)
    prov = number_provenance_report(sb, [(out, "", CORPUS_EXCLUDE_TOP)])
    residual.update({"unsourced_numbers_in_abstract_legends": prov.get("unsourced", 0),
                     "proved_numbers": prov.get("proved", 0),
                     "unsourced_examples": prov.get("examples", [])})
    rec["residual"] = residual
    if prov.get("unsourced"):
        warns.append(f"{prov['unsourced']} number(s) in the abstract/legends are not proved by "
                     f"any shipped data table -- see work/NUMBERS_LEDGER.md (the integration "
                     f"stage ports the donors' fixes; a number it changed follows the source "
                     f"hierarchy)")
    # W-11: the difference ledger's per-difference artifacts, its finding-effect
    # column, and the requirement that BOTH size classes appear when the pool
    # carries both rewrite levels. Plus W-12's language pass and the
    # "no NEW finding-tier family" comparison against this run's own base.
    levels = rewrite_pool_levels(ctx, int(rec["round"]))
    led = integration_ledger_report(out, list(rec.get("other_ids") or []),
                                    expect_both_levels=len([k for k in levels if k]) >= 2)
    rec["diff_ledger"] = led
    strict = strict_dispositions(ctx)
    if led["rows"]:
        if led["donors_absent"]:
            warns.append(f"integrate: DIFF_LEDGER.md does not name donor(s) "
                         f"{', '.join(led['donors_absent'][:4])} in its `donor` column")
        if led["expect_both_levels"] and not led["both_levels"]:
            warns.append(f"integrate: the pool contains both rewrite levels (structural and "
                         f"sentence-level) but DIFF_LEDGER.md has only the size class(es) "
                         f"{sorted(led['sizes'])} -- the ledger must weigh large and small "
                         f"differences")
        if led["missing_artifact"]:
            msg = (f"integrate: {len(led['missing_artifact'])} ledger row(s) carry no `artifact` "
                   f"(a before/after pair for a small row, an outline diff for a large row) -- "
                   f"the row cannot be re-checked")
            (errs if strict else warns).append(msg)
        if led["missing_finding"]:
            warns.append(f"integrate: {len(led['missing_finding'])} ledger row(s) do not state "
                         f"their `finding effect` (preserves/undoes <id> or none)")
        for undo in led["undoes"][:4]:
            warns.append(f"integrate: a ported difference would UNDO a resolved finding "
                         f"({undo}) -- keep the self wording unless the author decided otherwise")
    else:
        warns.append("integrate: DIFF_LEDGER.md could not be parsed as a table (the per-difference "
                     "artifacts, the size classes and the finding-effect column cannot be checked)")
    add_stage_quality_checks(ctx, rec, [(sb / "self", "", ())],
                             [(out, "", CORPUS_EXCLUDE_TOP)],
                             out, "integrate", errs, warns)
    _check_pristine_copy(ctx, rec, pristine_dirname(ctx.sandbox_of(rec)), errs)
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


def postcheck_rewrite(ctx: Ctx, rec: dict):
    """The rewrite arm's contract.

    The rewritten candidate is a FULL candidate (same documents, same content,
    alternative organization), so it is checked like the other content-producing
    stages: completion marker with stage="rewrite", a readable package in
    rewritten/, the document set preserved (with the same recovery layer), a
    recorded visual pass, and a REQUIRED rewritten/REWRITE_REPORT.md -- the
    stage's ledger, whose "PROBLEMS SURFACED" section is the feedback/reference
    deliverable later stages and the author receive. The report is prose, so it
    is required to EXIST (a missing report is a failed attempt); its content is
    never parsed for scores.
    """
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "rewrite", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    out = sb / REWRITTEN_DIR
    _format_fix_stage_package(ctx, rec, out, warns, errs)
    if not (out.is_dir() and any(out.iterdir())):
        errs.append(f"{REWRITTEN_DIR}/ is missing or empty (the full rewritten candidate is this "
                    f"stage's deliverable; a non-empty {REWRITTEN_DIR}/ is required, though it is "
                    f"not by itself a completion signal)")
    if not (sb / REWRITE_REPORT_REL).is_file():
        errs.append(f"{REWRITE_REPORT_REL} is missing: it is this stage's ledger (the organization "
                    f"map, what was deliberately left unchanged, and the problems the rewrite "
                    f"surfaced -- the feedback/reference deliverable for later stages and the "
                    f"author)")
    elif not (sb / REWRITE_REPORT_REL).stat().st_size:
        errs.append(f"{REWRITE_REPORT_REL} is EMPTY (structured output): write the organization "
                    f"map, the deliberately-unchanged list and the problems the rewrite surfaced")
    if count_manual_steps(out / "MANUAL_STEPS.md") is None \
            and count_manual_steps(sb / "MANUAL_STEPS.md") is None:
        warns.append(f"MANUAL_STEPS.md not found under {REWRITTEN_DIR}/ (the decision report will "
                     f"show the manual-item count as unknown; the count is reported only and never "
                     f"ranked)")
    summ = rec.get("summary") or {}
    for key in ("critical_remaining", "writing_remaining", "manual_items"):
        if not is_int(summ.get(key)):
            warns.append(f"marker summary.{key} is missing/not an integer "
                         f"(the report needs it; the ranking uses statistics first)")
        elif int(summ[key]) < 0:
            warns.append(f"marker summary.{key}={summ[key]} is NEGATIVE; a count of open "
                         f"findings or manual items cannot be negative, so the value is ignored "
                         f"for the ranking (treated like a missing number) -- check the agent's "
                         f"final report")
    tiebreak_selfreport_warnings(ctx, rec, summ, warns)
    for key in ("reorganized_sections", "problems_surfaced"):
        if not is_int(summ.get(key)):
            warns.append(f"marker summary.{key} is missing/not an integer (reported only; it "
                         f"documents how much the rewrite reorganized and what it surfaced)")
    # The rewrite must not lose base content: same recovery as revise/integration.
    rec["backfill"] = backfill_missing_files(ctx, rec, [(sb / "base", "", ())], warns)
    errs.extend(f"document recovery failed: {e}" for e in rec["backfill"]["unresolved"])
    rec["raw_data"] = verify_readonly_raw_data(ctx, sb / REWRITTEN_DIR, warns)
    errs.extend(rec["raw_data"].get("legacy_input_areas") or [])
    _record_revision_token(rec, sb / REWRITTEN_DIR, warns, errs=errs)
    _caption_and_document_checks(ctx, rec, freshness_vid(rec) or A1_ID,
                                 [(sb / "base", "", ())], errs, warns)
    if word_docs_present([out]):
        check_visual_artifact(out / "VISUAL_CHECK.md",
                              f"the visual-inspection record {VISUAL_ARTIFACT_REWRITTEN}",
                              errs, warns, sandbox=sb, render_roots=[out])
    rec["residual"] = placeholder_residual_report(ctx, sb, [(out, "", CORPUS_EXCLUDE_TOP)],
                                                  "rewrite", enforce=True, errs=errs, warns=warns)
    # W-11/W-12: the arm's declared LEVEL, the language pass, and the
    # "no NEW finding-tier family" comparison against the arm's own base.
    level = str(rec.get("rewrite_level") or "")
    rep = out / "REWRITE_REPORT.md"
    if level and rep.is_file():
        try:
            declared = re.search(r"(?im)^\s*(?:[-*]\s*)?LEVEL\s*[:=]\s*(structural|sentence)\b",
                                 rep.read_text("utf-8", "replace")[:4000])
        except OSError:
            declared = None
        if declared is None:
            warns.append(f"rewrite: REWRITE_REPORT.md does not state the arm's level "
                         f"({level!r}); the integration stage weighs large and small differences "
                         f"from that declaration")
        elif declared.group(1).lower() != level:
            errs.append(f"rewrite: REWRITE_REPORT.md declares level "
                        f"{declared.group(1).lower()!r} but this arm is {level!r} -- the round "
                        f"stages one structural and one sentence-level arm so the pool has both "
                        f"kinds of difference")
    add_stage_quality_checks(ctx, rec, [(sb / "base", "", ())],
                             [(out, "", CORPUS_EXCLUDE_TOP)],
                             out, "rewrite", errs, warns)
    _check_pristine_copy(ctx, rec, pristine_dirname(ctx.sandbox_of(rec)), errs)
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


def _norm_opponent_label(x) -> str:
    """Case/whitespace-insensitive opponent label ('V1 ', 'v1' -> 'v1').

    Labels are issued as v1..vK by the orchestrator, but they are typed back
    by an LLM: 'V1' or 'v1 ' is the same opponent and must not cost the panel
    a comparison (a sheet that omits an issued label FAILS the run, so a
    case slip would otherwise shrink the panel and stall the round).
    """
    return str(x or "").strip().lower()


def _norm_basis_item(item):
    """(tier, severity, evidence) of one ledger item, or None when malformed."""
    if not isinstance(item, dict):
        return None
    tier = str(item.get("tier") or "").strip().lower()
    severity = str(item.get("severity") or "").strip().lower()
    evidence = str(item.get("evidence") or "").strip()
    if tier not in BASIS_TIERS or severity not in SEVERITIES or not evidence:
        return None
    return tier, severity, evidence


def ledger_items(comp: dict):
    """[(side, tier, severity, evidence, check_id, ai_suspicion)] for a comparison.

    ONE normalizer for the derivation and the validator: `None` when the sheet
    is malformed (so the caller can report it), otherwise every row carries the
    side it was filed on, its normalized tier and severity, the evidence, the
    frozen check id it cites (FMT-*/Q1-Q12 mapped onto their owners, "" when the
    cell is absent) and whether it is a speculative-AI row (`J4` + "possible AI").
    """
    if not isinstance(comp, dict):
        return None
    out = []
    for side in ("resolved", "introduced"):
        raw = comp.get(side)
        if not isinstance(raw, list):
            return None
        for item in raw:
            norm = _norm_basis_item(item)
            if norm is None:
                return None
            cid = _norm_check_id(item.get("check")) if isinstance(item, dict) else ""
            out.append((side, norm[0], norm[1], norm[2], cid,
                        bool(cid == "J4"
                             and norm[2].strip().lower().startswith("possible ai"))))
    return out


def tier_net_scores(items) -> dict:
    """{tier: capped net} -- resolved rows add, introduced rows subtract (per tier)."""
    raw = {tier: 0 for tier in BASIS_TIERS}
    for side, tier, severity, _e, _c, _ai in items:
        weight = TIER_ROW_WEIGHTS.get(tier, {}).get(severity, 0)
        raw[tier] = raw.get(tier, 0) + (weight if side == "resolved" else -weight)
    return {tier: max(-TIER_CAPS.get(tier, 0), min(TIER_CAPS.get(tier, 0), net))
            for tier, net in raw.items()}


# --- the issue census (the selection's LEADING ranking input) ---------------
# The judge ledger is the only place in the pipeline where an issue carries a
# TIER: a comparison's `resolved` rows name the OPPONENT's defects and its
# `introduced` rows name the TARGET's. The panel therefore already measures
# "how many issues of each tier does this version carry" -- it just never
# counted them. The census counts them in CODE, from the sheets the panel
# produced:
#   * `own`  rows a version's OWN sessions attribute to it (the sessions that
#            swept it as their target: their `introduced` rows);
#   * `peer` rows the OTHER versions' sessions attribute to it (a session whose
#            target is W lists V's defects in the (W vs V) comparison's
#            `resolved` rows);
#   * rows are DEDUPLICATED per (session, version, tier, severity, check,
#     normalized evidence): the same defect a judge repeats in every opponent
#     comparison of one session is ONE issue, never |field|-1 of them. NO
#     cross-sheet matching is performed by default (`dedup_mode` "off"): a row
#     two sessions both filed counts twice. The OPT-IN "location" mode merges
#     rows across sheets only on a structured key (defect class + exact line +
#     fuzzy-matchable >= 7-word excerpt); see DEDUP_MODES below.
# The own/peer split is deliberate: the two sources have different scrutiny
# depth (own = an artifact-backed sweep of the version, peer = a read-only
# comparison against it), so a large own/peer gap is the visible symptom of a
# panel that under-reads its opponents. The count is reported per tier AND per
# severity, and normalized by the number of sessions that could have mentioned
# the version (`per_session`), which is stable as the field size changes --
# that is the number a chain of runs can compare.


def _issue_row_key(tier, severity, evidence, check) -> tuple:
    """One ledger row's identity inside a (session, version) bucket."""
    return (str(tier), str(severity), str(check or ""),
            " ".join(str(evidence or "").split()).lower())

# ---- the OPT-IN structured-location dedup (default OFF) --------------------
# Cross-sheet matching by free-text evidence was removed because it is a noise
# source. This optional mode instead matches on a STRUCTURED key the judge rows
# already carry in prose: the defect CLASS -- the NORMALIZED CHECK ID the sheet
# cites, whatever it is (the numeric `M`-ids are examples, never a closed set:
# `J1`-`J5`, `FMT-*` -> `M20`, the writing-rubric `Q` ids -> `J3`, and any other
# id is its own class) --, an exact LINE number, and the excerpt (at least
# DEDUP_MIN_WORDS words) matched
# FUZZILY (token-set Jaccard >= DEDUP_FUZZY_THRESHOLD). Rows without a parseable
# line number, or with a shorter excerpt, are NEVER merged (the conservative
# direction). It is enabled only by `setup --dedup-mode location` /
# `set-dedup-mode location`; the default `off` performs no cross-sheet merging.
DEDUP_MODES = ("off", "location")
DEDUP_MIN_WORDS = 7
DEDUP_FUZZY_THRESHOLD = 0.8
DEDUP_LINE_RE = re.compile(r"(?:\blines?\b|\bln\b|\bl\.)\s*[:#]?\s*(\d+)\b", re.I)
DEDUP_WORD_RE = re.compile(r"[0-9A-Za-z]+")
_NUMERIC_CHECK_RE = re.compile(r"^M0*(\d+)$", re.I)


def dedup_mode_of(ctx=None) -> str:
    """The configured dedup mode ('off' when unset/unknown; an operator typo dies)."""
    raw = (getattr(ctx, "cfg", None) or {}).get("dedup_mode")
    mode = str(raw or "off").strip().lower()
    if mode not in DEDUP_MODES:
        die(f"pipeline_config.json records dedup_mode {mode!r}, which is not one of "
            f"{', '.join(DEDUP_MODES)}. Fix it with `set-dedup-mode <mode>` or start a fresh "
            f"root.")
    return mode


def dedup_class_id(check) -> str:
    """The defect CLASS used by the dedup key: the NORMALIZED check id.

    `M01`, `M02`, ... are examples (zero-padded numeric check ids), never a
    closed set: `J1`-`J5` are their own classes, `FMT-*` normalizes to `M20`,
    the writing-rubric `Q` ids to `J3`, and any other id the sheet cites is its
    own class. A row with NO check id has no class and never merges.
    """
    cid = _norm_check_id(check)
    m = _NUMERIC_CHECK_RE.match(cid)
    if m:
        return f"M{int(m.group(1)):02d}"
    return cid


def dedup_location_of(evidence) -> tuple:
    """(line or None, word tuple) parsed from one ledger row's evidence text."""
    text = " ".join(str(evidence or "").split())
    m = DEDUP_LINE_RE.search(text)
    line = int(m.group(1)) if m else None
    return line, tuple(w.lower() for w in DEDUP_WORD_RE.findall(text))


def dedup_fuzzy_similarity(a_words, b_words) -> float:
    """Token-SET Jaccard similarity (0.0 when either side is empty)."""
    a, b = set(a_words or ()), set(b_words or ())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_rows_match(class_a, loc_a, class_b, loc_b, threshold: float = None) -> bool:
    """True when two rows are the SAME defect under the structured key.

    Requires: same defect class, BOTH line numbers present and EQUAL, both
    excerpts at least DEDUP_MIN_WORDS words, and token-set Jaccard >= threshold.
    A row with NO check id has no defect class, so it never merges: the key
    would be incomplete.
    """
    if not class_a or not class_b or class_a != class_b:
        return False
    line_a, words_a = loc_a
    line_b, words_b = loc_b
    if line_a is None or line_b is None or line_a != line_b:
        return False
    if len(words_a) < DEDUP_MIN_WORDS or len(words_b) < DEDUP_MIN_WORDS:
        return False
    thr = DEDUP_FUZZY_THRESHOLD if threshold is None else float(threshold)
    return dedup_fuzzy_similarity(words_a, words_b) >= thr


def dedup_same_place(loc_a, loc_b) -> bool:
    """True when two findings name the SAME location cell (lowercased, squeezed).

    The census key needs a literal `line N` on both sides; the finding format
    spells a location as a document/section/paragraph reference ("Results,
    paragraph 2") just as often. This is the fallback that keeps a same-place
    comparison possible without loosening `dedup_rows_match` itself.
    """
    a = " ".join(str(loc_a or "").lower().split())
    return bool(a) and a == " ".join(str(loc_b or "").lower().split())


def dedup_excerpts_match(loc_a: tuple, loc_b: tuple, threshold: float = None) -> bool:
    """Both excerpts carry DEDUP_MIN_WORDS and overlap at the census threshold."""
    _line_a, words_a = loc_a
    _line_b, words_b = loc_b
    if len(words_a) < DEDUP_MIN_WORDS or len(words_b) < DEDUP_MIN_WORDS:
        return False
    thr = DEDUP_FUZZY_THRESHOLD if threshold is None else float(threshold)
    return dedup_fuzzy_similarity(words_a, words_b) >= thr


# The judge-side instruction the OPT-IN `dedup_mode` "location" adds to the
# prompt (never concatenated in the default mode, so the historical prompt is
# byte-identical): the machine reader needs `line N` and a long enough quote to
# find the same defect across two sessions' sheets.
DEDUP_LOCATION_JUDGE_RULE = """
=== ISSUE-LOCATION RULE (this pipeline merges duplicate issue rows by location) ===

The issue census merges the rows TWO sessions file for the SAME defect, so every ledger row must be
machine-locatable from its `evidence` alone:

  * name the LINE NUMBER of the affected text as `line N` (e.g. `line 42 of the manuscript`), and
  * quote AT LEAST 7 words of the affected text after it (e.g. `line 42: the treated group showed
    a higher median than the control group`).

Two rows are merged only when their `check` resolves to the same defect class, their line numbers
are EQUAL, and their quoted excerpts overlap at the word-set level. Every frozen check id is its
own class (M01, M02, ... are examples of the numeric ids, not the whole set: J1-J5, FMT-* and the
writing-rubric ids all work), so cite the check you actually read. A row without a parseable
`line N` or with a shorter quote is never merged -- it is counted on its own. This rule only makes
the rows machine-locatable; it never changes what you report or how it is scored.
"""


def build_issue_census(observations, field_ids, sessions_expected=None,
                       dedup: str = "off", dedup_threshold: float = None) -> dict:
    """{vid: issue counts per tier/severity} from the round's judge sheets.

    `observations` is an iterable of `(session_id, target_vid, opponent_vid,
    comparison)` for every resolvable comparison the panel produced. A row is
    attributed to the version whose defect it names (`introduced` -> the
    target, `resolved` -> the opponent) and to the source that found it
    (`own` when that version is the session's target, else `peer`). Counts are
    the REPORTED statistic and the tie-break's input; they never change a score
    or a gate. `sessions_expected` is the number of enabled sessions that could
    have mentioned a version (the round's total); without it the rate falls back
    to the sessions that actually contributed.

    Cross-sheet dedup is OFF by default (`dedup="off"`): the counts are the
    mentions each sheet filed, collapsed only per (session, version) -- a judge
    sheet that repeats the same row for several opponent comparisons counts it
    once. The OPT-IN `dedup="location"` mode merges rows ACROSS sheets when the
    structured key matches: the same defect CLASS (the NORMALIZED CHECK ID --
    `M01`/`M02`/... are examples, never a closed set; `J1`-`J5`, `FMT-*` ->
    `M20`, the writing-rubric `Q` ids -> `J3`, and any other id is its own
    class), the SAME exact line number, and evidence excerpts of
    at least DEDUP_MIN_WORDS words whose token-set Jaccard is >=
    dedup_threshold (DEDUP_FUZZY_THRESHOLD when None). Rows without a parseable
    line number or with a shorter excerpt are never merged; every merge is
    recorded under the version's `dedup_audit` for inspection.

    Per (version, tier, severity): `own`/`peer`/`total` are the EFFECTIVE counts
    (deduplicated when the mode is on), `raw_own`/`raw_peer` the pre-dedup
    counts, and `merged_own`/`merged_peer` the number of rows merged away; the
    `peer_rate`/`own_rate` divide the effective counts by the OPPORTUNITIES.
    """
    field_ids = [str(v) for v in field_ids]
    mode = str(dedup or "off").strip().lower()
    if mode not in DEDUP_MODES:
        mode = "off"
    census = {vid: {"tiers": {t: {s: {"own": 0, "peer": 0, "raw_own": 0, "raw_peer": 0,
                                     "merged_own": 0, "merged_peer": 0}
                              for s in SEVERITIES} for t in BASIS_TIERS},
                    "own_sessions": set(), "peer_sessions": set(),
                    "own_opps": set(), "peer_opps": set(),
                    "dedup_audit": []} for vid in field_ids}
    seen = {}                       # (session, version) -> row keys already counted
    accepted = {}                   # (version, source) -> [(class, (line, words), session)]
    for sess, target, opp, comp in observations:
        if target in census:
            census[target]["own_opps"].add(sess)
        if opp in census:
            census[opp]["peer_opps"].add(sess)
        items = ledger_items(comp)
        if not items:
            continue
        target, opp = str(target), str(opp)
        for side, tier, severity, evidence, check, _ai in items:
            vid = target if side == "introduced" else opp
            c = census.get(vid)
            if c is None or tier not in c["tiers"] or severity not in SEVERITIES:
                continue
            bucket = seen.setdefault((sess, vid), set())
            key = _issue_row_key(tier, severity, evidence, check)
            if key in bucket:
                continue
            bucket.add(key)
            src = "own" if vid == target else "peer"
            c["tiers"][tier][severity]["raw_" + src] += 1
            (c["own_sessions"] if src == "own" else c["peer_sessions"]).add(sess)
            effective = True
            if mode == "location":
                class_id = dedup_class_id(check)
                loc = dedup_location_of(evidence)
                entries = accepted.setdefault((vid, src), [])
                for kept_class, kept_loc, kept_sess in entries:
                    if dedup_rows_match(class_id, loc, kept_class, kept_loc,
                                        threshold=dedup_threshold):
                        effective = False
                        c["tiers"][tier][severity]["merged_" + src] += 1
                        c["dedup_audit"].append({
                            "version": vid, "source": src, "session": str(sess),
                            "class": class_id, "line": loc[0],
                            "excerpt": " ".join(str(evidence or "").split())[:200],
                            "kept_session": str(kept_sess),
                            "kept_excerpt": " ".join(kept_loc[1])[:200]})
                        break
                else:
                    entries.append((class_id, loc, sess))
            if effective:
                c["tiers"][tier][severity][src] += 1
    n_expected = (int(sessions_expected) if is_int(sessions_expected) else None)
    out = {}
    for vid in field_ids:
        c = census[vid]
        sev_totals = {s: {"own": 0, "peer": 0, "total": 0, "raw_own": 0, "raw_peer": 0,
                          "merged_own": 0, "merged_peer": 0} for s in SEVERITIES}
        tiers, own_total, peer_total = {}, 0, 0
        raw_own_total = raw_peer_total = merged_own_total = merged_peer_total = 0
        for tier in BASIS_TIERS:
            per_sev, t_own, t_peer = {}, 0, 0
            for sev in SEVERITIES:
                d = c["tiers"][tier][sev]
                own, peer = d["own"], d["peer"]
                n_own_opps = len(c["own_opps"])
                n_peer_opps = len(c["peer_opps"])
                per_sev[sev] = {
                    "own": own, "peer": peer, "total": own + peer,
                    "raw_own": d["raw_own"], "raw_peer": d["raw_peer"],
                    "merged_own": d["merged_own"], "merged_peer": d["merged_peer"],
                    "peer_rate": (round(peer / n_peer_opps, 6) if n_peer_opps else 0.0),
                    "own_rate": (round(own / n_own_opps, 6) if n_own_opps else 0.0),
                }
                for k in ("own", "peer", "raw_own", "raw_peer", "merged_own", "merged_peer"):
                    sev_totals[sev][k] += d[k]
                sev_totals[sev]["total"] += own + peer
                t_own += own
                t_peer += peer
            total = t_own + t_peer
            tiers[tier] = {"own": t_own, "peer": t_peer, "total": total,
                           "severities": per_sev}
            own_total += t_own
            peer_total += t_peer
            raw_own_total += sum(per_sev[s]["raw_own"] for s in SEVERITIES)
            raw_peer_total += sum(per_sev[s]["raw_peer"] for s in SEVERITIES)
            merged_own_total += sum(per_sev[s]["merged_own"] for s in SEVERITIES)
            merged_peer_total += sum(per_sev[s]["merged_peer"] for s in SEVERITIES)
        total = own_total + peer_total
        raw_total = raw_own_total + raw_peer_total
        n_sessions = n_expected if n_expected is not None else (
            len(c["own_sessions"]) + len(c["peer_sessions"]))
        rate = (round(total / n_sessions, 4) if n_sessions else None)
        raw_rate = (round(raw_total / n_sessions, 4) if n_sessions else None)
        for row in tiers.values():
            row["per_session"] = (round(row["total"] / n_sessions, 4) if n_sessions else None)
            for per_sev in row["severities"].values():
                per_sev["per_session"] = (round(per_sev["total"] / n_sessions, 4)
                                          if n_sessions else None)
        merged_total = merged_own_total + merged_peer_total
        out[vid] = {"tiers": tiers,
                    "severities": {s: dict(v, per_session=(round(v["total"] / n_sessions, 4)
                                                           if n_sessions else None))
                                   for s, v in sev_totals.items()},
                    "own": own_total, "peer": peer_total, "total": total,
                    "raw_own": raw_own_total, "raw_peer": raw_peer_total,
                    "raw_total": raw_total,
                    "merged_own": merged_own_total, "merged_peer": merged_peer_total,
                    "merged": merged_total,
                    "dedup_mode": mode,
                    "dedup_audit": c["dedup_audit"],
                    "per_session": rate,
                    "raw_per_session": raw_rate,
                    "own_sessions": len(c["own_sessions"]),
                    "peer_sessions": len(c["peer_sessions"]),
                    "own_opps": len(c["own_opps"]),
                    "peer_opps": len(c["peer_opps"]),
                    "sessions_expected": n_sessions}
    return out


def build_issue_ledger_rows(observations, field_ids, dedup: str = "off",
                            dedup_threshold: float = None) -> list:
    """The LONG FORM of the issue census: one row per defect mention the panel filed.

    `observations` is the same iterable of `(session_id, target_vid, opponent_vid,
    comparison)` the census counts (`build_issue_census`); this function returns
    the rows themselves instead of the counts, with every field the census
    attributes by -- so `reports/round<r>_defects.csv` answers "WHICH defects
    does each version carry, and what does each one say" beside the census's
    "how many". Attribution follows the census EXACTLY:

      * the version a row is attributed to is the one whose defect it names --
        the TARGET for its `introduced` rows, the OPPONENT for the `resolved`
        rows of the comparison it was filed in;
      * `source` is `own` when that version was the session's sweep target and
        `peer` when it was the comparison's opponent;
      * a row repeated inside ONE session for the same version is kept ONCE (the
        per-(session, version, tier, severity, check, normalized evidence) key),
        and with the OPT-IN `dedup="location"` mode a row matching an earlier
        accepted row (same defect class, same line number, >= 7-word excerpt with
        token-set Jaccard >= threshold) is kept but marked `counted: false`, so
        the file lists every mention while the `counted` column still adds up to
        the census (`counted="yes"` rows == the census's `total`).

    The rows come out in reading order (session, then the order the sheet filed
    them) and carry the meta an operator asks about per defect: the target and
    peer version, the section of the sheet (`side`), the frozen check id, the
    defect class (`tier`), the severity rung, and the sheet's own evidence
    sentence as the verbal description.
    """
    field_ids = [str(v) for v in field_ids]
    mode = str(dedup or "off").strip().lower()
    if mode not in DEDUP_MODES:
        mode = "off"
    known = set(field_ids)
    seen, accepted = {}, {}
    rows = []
    for sess, target, opp, comp in observations:
        items = ledger_items(comp)
        if not items:
            continue
        target, opp = str(target), str(opp)
        for side, tier, severity, evidence, check, _ai in items:
            vid = target if side == "introduced" else opp
            if vid not in known or tier not in BASIS_TIERS or severity not in SEVERITIES:
                continue
            bucket = seen.setdefault((sess, vid), set())
            key = _issue_row_key(tier, severity, evidence, check)
            if key in bucket:
                continue                    # the sheet repeats it in this session
            bucket.add(key)
            src = "own" if vid == target else "peer"
            counted, merged_into = True, ""
            if mode == "location":
                class_id = dedup_class_id(check)
                loc = dedup_location_of(evidence)
                entries = accepted.setdefault((vid, src), [])
                for kept_class, kept_loc, kept_sess in entries:
                    if dedup_rows_match(class_id, loc, kept_class, kept_loc,
                                        threshold=dedup_threshold):
                        counted, merged_into = False, str(kept_sess)
                        break
                else:
                    entries.append((class_id, loc, sess))
            rows.append({
                "session": str(sess), "target_version": target, "peer_version": opp,
                "version": vid, "source": src, "side": side, "check": check,
                "tier": tier, "severity": severity,
                "evidence": " ".join(str(evidence or "").split()),
                "comparison_score": comp.get("score"),
                "comparison_basis": (str(comp.get("basis")) if comp.get("basis") else ""),
                "dedup_mode": mode,
                "counted": "yes" if counted else "no",
                "merged_into": merged_into})
    return rows


def derived_comparison_basis(comp: dict):
    """The tier the lexicographic derivation decides on ("none" for a clean 0).

    For a non-zero score this is the FIRST tier whose net is not zero -- the tier
    that decides the comparison. For a net-zero sheet with rows it is the
    highest-priority tier in which the two versions differ at all, and for an
    empty (or all-zero) sheet it is "none".
    """
    items = ledger_items(comp)
    if items is None:
        return None
    nets = tier_net_scores(items)
    for tier in BASIS_TIERS:
        if nets[tier]:
            return tier
    for tier in BASIS_TIERS:
        if any(t == tier for _s, t, _sev, _e, _c, _ai in items):
            return tier
    return "none"


def derived_comparison_score(comp: dict):
    """The integer a comparison's ledger rows imply (judge contract v4).

    LEXICOGRAPHIC: the six tiers are compared IN THE FIXED PRIORITY ORDER
    correctness > preservation > completeness > consistency > writing >
    formatting. Within one tier, resolved rows add and introduced rows subtract
    (minor 1 / major 2 / critical 3 / fatal 4) and the net is capped at +-4. The
    FIRST tier whose net is not zero DECIDES the comparison: the sign is its
    sign, and the magnitude is its |net|, bounded by the rung its own deciding
    rows can back -- a run of MINOR rows reaches +-2, a tier with a MAJOR row
    reaches +-3, a tier with a CRITICAL or FATAL row reaches +-4. Every lower
    tier is then IGNORED: a consistency improvement can never offset a
    correctness loss, and a formatting improvement can never offset a
    completeness loss. A comparison whose six nets are all zero is 0.
    """
    items = ledger_items(comp)
    if items is None:
        return None
    nets = tier_net_scores(items)
    for tier in BASIS_TIERS:
        net = nets[tier]
        if not net:
            continue
        side = "resolved" if net > 0 else "introduced"
        severities = [sev for row_side, t, sev, _e, _c, _ai in items
                      if row_side == side and t == tier]
        if any(sev in ("critical", "fatal") for sev in severities):
            rung = 4
        elif "major" in severities:
            rung = 3
        else:
            rung = 2                    # a run of MINOR rows reaches "better"
        score = (1 if net > 0 else -1) * min(abs(net), rung)
        return max(SCORE_MIN, min(SCORE_MAX, score))
    return 0


# The judge prompt's OWN sub-identifiers, mapped onto the frozen check that owns
# them. Both entries exist because the prompt names the finer-grained id and the
# panel then cites it back:
#   * `FMT-*` is a formatting-sweep RULE id (FMT-P1, FMT-S4, FMT-T9c, ...) and the
#     check that owns the sweep is M20 (2026-09-23: one session failed twice for
#     `check 'FMT-T9C'`, its sibling once for the uppercase spelling);
#   * `Q1`-`Q12` are the WRITING RUBRIC's items, and the frozen check that owns
#     that rubric is J3 ("writing quality, logic, and overclaiming (the Q1-Q12
#     rubric)" -- since 3.5.1 read as "claim calibration, overclaiming AND
#     underclaiming" (the rubric's Q1 carries both directions). The prompt says
#     "a row names its rubric item (Q7)", so the panel
#     cites Q6/Q7/Q11/Q12 -- and the 2026-09-23 round-1 panel shows what the
#     missing mapping costs: 8 of 24 sessions failed, three of them twice and one
#     (judge_t1a4cb6e6_j2) on all three attempts, on nothing but
#     `check 'Q11' is not a frozen check id`; the round burned 3h20m and still
#     finished incomplete.
WRITING_RUBRIC_CHECK = "J3"
_WRITING_RUBRIC_RE = re.compile(r"^Q(?:[1-9]|1[0-2])$")


def _norm_check_id(raw) -> str:
    """Normalize one check id, including the pipeline's OWN rule-id spellings.

    Normalizing here keeps one spelling for the coverage map AND for a ledger
    row's `check`, so a sheet is never failed for citing the finer-grained id the
    pipeline's own prompt prints (see `_WRITING_RUBRIC_RE`).
    """
    cid = str(raw or "").strip().upper().replace(" ", "")
    if cid.startswith("FMT-"):
        return "M20"
    if _WRITING_RUBRIC_RE.match(cid):
        return WRITING_RUBRIC_CHECK
    return cid


def _frozen_check_id(raw) -> str:
    """`_norm_check_id()` mapped onto the FROZEN vocabulary's spelling.

    The frozen ids are zero-pad-free (`M1`..`M24` + `J1`..`J4`; see
    JUDGE_COVERAGE_CHECKS),
    while the defect-ledger dedup CLASS ids are explicitly padded (`M01`; see
    dedup_class_id) and the CLI/prompt text cites `M01`/`M02` as "the normalized
    check id". A judge that writes the padded spelling into its coverage map
    must therefore be read as the same check -- failing a 20-40 minute session
    for a missing `M1` when `M01` is present would be an id-spelling trap of the
    same kind the FMT-*/Q1-Q12 mappings above exist to close.
    """
    cid = _norm_check_id(raw)
    m = _NUMERIC_CHECK_RE.match(cid)
    return f"M{int(m.group(1))}" if m else cid


def judge_coverage_problems(comp: dict, where: str, strict: bool) -> tuple:
    """(errors, warnings) for one comparison's per-opponent check coverage.

    Contract v2+ requires a `checks` map on EVERY comparison: one disposition
    (`clean` / `findings` / `unable`, optionally followed by a short detail) for
    every frozen check id. This is the code-side answer to "the judge sweeps
    only its target": a sheet that never looked at an opponent has to say so, and
    a missing id is a failed run, not a style slip.

    The judge's own discovery findings (contract v5) are NOT check ids: they
    live in `judge_review/discovery/` (one disposed file per side) and in the
    ledger rows that cite them, never in this map (see
    `judge_discovery_problems`).
    """
    out_e, out_w = [], []
    emit = out_e.append if strict else out_w.append
    checks = comp.get("checks")
    if not isinstance(checks, dict) or not checks:
        emit(f"{where} has no `checks` coverage map; contract v{JUDGE_CONTRACT_VERSION} "
             f"requires one disposition per frozen check id for EVERY opponent "
             f"({', '.join(JUDGE_COVERAGE_CHECKS)})")
        return out_e, out_w
    have, seen = {}, set()
    for raw_id, raw_val in checks.items():
        cid = _frozen_check_id(raw_id)
        if cid in seen:
            out_w.append(f"{where}.checks lists {cid!r} twice")
        seen.add(cid)
        text = str(raw_val or "").strip().lower()
        if not text:
            emit(f"{where}.checks[{cid!r}] is empty: state one of "
                 f"{'/'.join(JUDGE_DISPOSITIONS)} for every frozen check id")
            continue
        if not text.startswith(JUDGE_DISPOSITIONS):
            emit(f"{where}.checks[{cid!r}] = {raw_val!r} is not a disposition: it must start "
                 f"with one of {'/'.join(JUDGE_DISPOSITIONS)}")
            continue
        if cid not in JUDGE_COVERAGE_CHECKS:
            out_w.append(f"{where}.checks names {cid!r}, which is not a frozen check id of this "
                         f"round; it is ignored")
            continue
        if text.startswith("unable") and len(text.split()) < 3:
            emit(f"{where}.checks[{cid!r}] = {raw_val!r} states no reason; `unable` means "
                 f"'examined, could not be judged', so say why (the keyword plus at least two "
                 f"words, e.g. 'unable -- the figure is image-only')")
        have[cid] = text
    missing = [c for c in JUDGE_COVERAGE_CHECKS if c not in have]
    if missing:
        emit(f"{where}.checks omits {len(missing)} frozen check id(s): {', '.join(missing[:8])}"
             + (" ..." if len(missing) > 8 else ""))
    if have and not any(v.startswith(("clean", "findings")) for v in have.values()):
        out_w.append(f"{where}.checks carries no `clean` and no `findings` entry -- every frozen "
                     f"id it disposed is `unable`; the session judged nothing, so its zeros are "
                     f"non-judgments, not agreements")
    return out_e, out_w


def judge_basis_problems(comp: dict, where: str, strict: bool) -> tuple:
    """(errors, warnings) for one comparison's graded basis (judge contract v5).

    The integer score is a claim about a defect class, and the ledger is what
    makes the claim checkable. The orchestrator enforces the judge prompt's own
    anchors ARITHMETICALLY:

      * `basis` names the tier that DECIDES the comparison -- the first tier, in
        the fixed priority order, whose net is not zero (`correctness` /
        `preservation` / `completeness` / `consistency` / `writing` /
        `formatting`, the `BASIS_TIERS` order; for a net-zero comparison with rows,
        the highest-priority
        tier in which the two versions differ; `none` for a clean 0);
      * `resolved` and `introduced` list the concrete items behind a score
        (tier, severity, <=25-word evidence); an empty ledger means "no content
        difference", which is exactly a 0;
      * the score is DERIVED lexicographically: rows weigh minor 1 / major 2 /
        critical 3 / fatal 4, resolved add and introduced subtract, the first
        non-zero tier's net decides (capped at +-4) and its magnitude is bounded
        by its own rows (MINOR-only <= 2, a MAJOR row <= 3, a CRITICAL/FATAL row
        <= 4);
      * a non-zero score needs at least one item on its own side IN that deciding
        tier;
      * |score| >= 3 needs a MAJOR/CRITICAL/FATAL item there, and |score| = 4 a
        CRITICAL/FATAL one;
      * a length/caption row (M18/M19) is a formatting-tier MINOR row: length
        moves a comparison by at most +-1 and is never a scoring tier.

    `strict` is the contract gate: a sheet written under the current contract must
    satisfy all of it (errors); a legacy sheet (no contract recorded -- its
    sandbox predates the prompt that asks for a ledger) is only warned about:
    never silently mixed into a calibrated panel, and never punished for a rule
    that did not exist when its sandbox was materialized.
    """
    out_e, out_w = [], []
    emit = out_e.append if strict else out_w.append
    prefix = "" if strict else "legacy sheet (no judge-contract version recorded): "
    score = comp.get("score") if is_int(comp.get("score")) else None
    basis = str(comp.get("basis") or "").strip().lower()
    if not basis:
        if strict:
            emit(f"{prefix}{where} has no `basis`; contract v{JUDGE_CONTRACT_VERSION} requires "
                 f"the tier that decides the comparison (the first tier whose net is not zero; "
                 f"for a net-zero comparison, the highest-priority tier in which the two "
                 f"versions differ, and `none` for a clean 0) "
                 f"({'/'.join(BASIS_VALUES)})")
        else:
            out_w.append(f"{where} is UNCALIBRATED: the sheet carries no graded basis, so its "
                         f"integer cannot be checked against the defect classes it claims "
                         f"(contract v{JUDGE_CONTRACT_VERSION} asks for one; the decision record "
                         f"counts these sheets)")
    elif basis and basis not in BASIS_VALUES:
        emit(f"{prefix}{where}.basis {basis!r} is not one of {'/'.join(BASIS_VALUES)}")
    items, bad = [], []
    for side in ("resolved", "introduced"):
        raw = comp.get(side)
        if raw is None:
            if strict:
                emit(f"{prefix}{where} has no `{side}` list; contract "
                     f"v{JUDGE_CONTRACT_VERSION} requires both lists (they may be empty)")
            continue
        if not isinstance(raw, list):
            emit(f"{prefix}{where}.{side} must be a list of ledger items")
            continue
        for k, item in enumerate(raw):
            norm = _norm_basis_item(item)
            if norm is None:
                bad.append(f"{side}[{k}]")
                continue
            if len(norm[2].split()) > EVIDENCE_MAX_WORDS:
                out_w.append(f"{where}.{side}[{k}].evidence is {len(norm[2].split())} words "
                             f"(schema: <={EVIDENCE_MAX_WORDS})")
            cid = _frozen_check_id(item.get("check")) if isinstance(item, dict) else ""
            if cid in LENGTH_GUARD_CHECKS and (norm[0] != "formatting" or norm[1] != "minor"):
                emit(f"{prefix}{where}.{side}[{k}]: a length/caption row (`{cid}`) is a "
                     f"formatting-tier MINOR row -- length may enter a comparison by at most +-1 "
                     f"and is never a scoring tier of its own; got tier {norm[0]!r}, severity "
                     f"{norm[1]!r}")
            if cid and cid not in JUDGE_COVERAGE_CHECKS and not DISCOVERY_X_ID_RE.match(cid):
                # A ledger row's `check` cell is DESCRIPTIVE: nothing is looked up
                # by it (the arithmetic reads tier/severity/evidence only), and
                # the row has to be re-checkable, not perfectly labelled. So an id
                # nobody recognizes is REPORTED with what to cite and otherwise
                # ignored -- never a failed 20-40 minute session. The hard
                # contract is the coverage map above ("one disposition per frozen
                # check id"), where a missing id still fails the run, and the
                # FMT-*/Q1-Q12 spellings the prompt itself uses are normalized
                # before this point. An X-* id needs no lookup: it is the judge's
                # OWN discovery id (contract v5), defined by the file it cites in
                # `judge_review/discovery/`, and the row counts like any other.
                out_w.append(f"{prefix}{where}.{side}[{k}].check {cid!r} is not a frozen check id; "
                             f"the row still counts for the arithmetic and the id is kept as "
                             f"written -- cite M1-M24/J1-J4 (the writing rubric's Q1-Q12 items "
                             f"belong to {WRITING_RUBRIC_CHECK}, and an FMT-* sweep rule belongs "
                             f"to M20), or an X-* id from `judge_review/discovery/`")
            items.append((side, norm[0], norm[1], norm[2], cid,
                          bool(cid == "J4" and norm[2].strip().lower().startswith("possible ai"))))
    if bad:
        emit(f"{prefix}{where} has malformed ledger item(s) {bad}: each needs a valid tier "
             f"({'/'.join(BASIS_TIERS)}), a severity ({'/'.join(SEVERITIES)}) and non-empty "
             f"evidence")
    derived = derived_comparison_score(comp)
    deciding = derived_comparison_basis(comp)
    if score is not None and derived is not None and derived != score:
        emit(f"{prefix}{where}: score {score:+d} contradicts its own ledger, from which it is "
             f"DERIVED -- the rows support {derived:+d} under the lexicographic tier order: the "
             f"first tier whose net is not zero decides the comparison (minor 1 / major 2 / "
             f"critical 3 / fatal 4, net capped at +-4 per tier, and the deciding tier's rows "
             f"bound the magnitude)")
    if score is None:
        return out_e, out_w
    supporting = [(t, s, ai) for side, t, s, _e, _c, ai in items
                  if t == deciding
                  and ((side == "resolved" and score > 0) or (side == "introduced" and score < 0))]
    if score != 0 and not supporting:
        emit(f"{prefix}{where}: score {score:+d} has no ledger item on its side in the deciding "
             f"tier ({deciding!r}); a non-zero score must be backed by at least one concrete item "
             f"there, or it is 0")
    if score != 0 and supporting and all(ai for _t, _s, ai in supporting):
        emit(f"{prefix}{where}: every item on the scoring side is a speculative AI-content row "
             f"(`J4` with evidence starting 'possible AI ...'); the standing exemption says such a "
             f"row can never decide a comparison on its own -- corroborate it with a non-AI item "
             f"or score 0")
    if score != 0 and abs(score) >= 3:
        strong = [(t, s, ai) for t, s, ai in supporting
                  if s in ("major", "critical", "fatal")]
        if strong and not any(not ai for _t, _s, ai in strong):
            emit(f"{prefix}{where}: |score| = {abs(score)} rests only on speculative AI-content "
                 f"rows (`J4` with evidence starting 'possible AI ...'); the standing exemption "
                 f"forbids such a row from deciding a comparison on its own")
    if abs(score) >= 4:
        crit = [(t, s, ai) for t, s, ai in supporting
                if s in ("critical", "fatal")]
        if crit and not any(not ai for _t, _s, ai in crit):
            emit(f"{prefix}{where}: |score| = 4 leans on a critical speculative AI-content row "
                 f"alone; the decisive rung needs a CRITICAL/FATAL item that is not a "
                 f"'possible AI ...' row")
    if items and basis and deciding is not None:
        if basis == "none":
            out_w.append(f"{where}.basis is 'none' but the ledger lists {len(items)} item(s); "
                         f"'none' is for a clean 0 with no item on either side -- the deciding "
                         f"tier is {deciding!r}")
        elif basis != deciding:
            out_w.append(f"{where}.basis is {basis!r} but the tier that decides this comparison "
                         f"is {deciding!r} (the FIRST tier whose net is not zero; for a 0, the "
                         f"highest-priority tier in which the two versions differ)")
    return out_e, out_w


def validate_judge_sheet(sj: dict, rec: dict):
    """(errors, warnings) for one judge's scores.json (minimal schema, D1/D4)."""
    errs, warns = [], []
    if not isinstance(sj, dict):
        return ["scores.json is not a JSON object"], warns
    try:
        strict_basis = int(rec.get("contract") or 0) >= JUDGE_CONTRACT_VERSION
    except (TypeError, ValueError):
        strict_basis = False
    labels = rec.get("label_map") or {}
    token = rec.get("judge_target_token")
    if sj.get("run_id") != rec["id"]:
        errs.append(f"run_id mismatch: expected {rec['id']!r}, got {sj.get('run_id')!r}")
    got_tid = sj.get("target_id")
    if token:
        # The judge is issued an opaque session token (provenance-free); the
        # version id itself is deliberately absent from its sandbox.
        if got_tid != token:
            if got_tid == rec["target_id"]:
                warns.append(f"target_id is the raw version id {rec['target_id']!r} instead of "
                             f"this session's opaque token {token!r}; accepted, but the sheet "
                             f"was not written to the blind-judging contract")
            else:
                errs.append(f"target_id mismatch: expected this session's opaque token {token!r}, "
                            f"got {got_tid!r}")
    elif got_tid != rec["target_id"]:
        errs.append(f"target_id mismatch: expected {rec['target_id']!r}, got {got_tid!r}")
    # The judge is never told the round (blinding), so the sheet's "round" is
    # not a claim the session can be held to: the run record holds the real one.
    # A sheet that omits it is accepted, and a sheet that carries a DIFFERENT
    # round is a note (a judge that watched which sandbox it was staged in), not
    # a failure -- the session's provenance-free token already ties the sheet to
    # the right target, and failing a 30-minute judgement over an invented field
    # would only cost a retry.
    if sj.get("round") is not None and sj.get("round") != rec["round"]:
        warns.append(f"the sheet names round {sj.get('round')!r} but this run is round "
                     f"{rec['round']}; the round is never part of a judge prompt and is ignored")
    if sj.get("judge_index") != rec["judge_index"]:
        warns.append(f"judge_index mismatch: expected {rec['judge_index']}, "
                     f"got {sj.get('judge_index')!r}")
    comps = sj.get("comparisons")
    if not isinstance(comps, list) or not comps:
        errs.append("comparisons is missing or empty (one entry per opponent label is required)")
        comps = []
    seen = set()
    for i, c in enumerate(comps):
        if not isinstance(c, dict):
            errs.append(f"comparisons[{i}] is not an object")
            continue
        raw_label = c.get("opponent_label")
        label = _norm_opponent_label(raw_label)
        if not label or label not in labels:
            warns.append(f"comparisons[{i}] uses opponent_label {raw_label!r}, which was not issued "
                         f"to this run -- the aggregator skips it")
            continue
        if label != raw_label:
            warns.append(f"comparisons[{i}] opponent_label {raw_label!r} was normalised to "
                         f"{label!r} (case/whitespace slip; accepted)")
        if label in seen:
            errs.append(f"duplicate comparison for label {label!r}")
        seen.add(label)
        s = c.get("score")
        if not is_int(s) or not (SCORE_MIN <= s <= SCORE_MAX):
            errs.append(f"comparisons[{i}].score must be an integer in {SCORE_MIN}..{SCORE_MAX}, "
                        f"got {s!r}")
        else:
            berrs, bwarns = judge_basis_problems(c, f"comparisons[{i}]", strict=strict_basis)
            errs.extend(berrs)
            warns.extend(bwarns)
            cerrs, cwarns = judge_coverage_problems(c, f"comparisons[{i}]", strict=strict_basis)
            errs.extend(cerrs)
            warns.extend(cwarns)
        reason = c.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            warns.append(f"comparisons[{i}] has no reason text (schema: <=30 words)")
        elif len(reason.split()) > 30:
            warns.append(f"comparisons[{i}].reason is {len(reason.split())} words (schema: <=30)")
    missing = sorted(set(labels) - seen)
    if missing:
        # An incomplete sheet is not a style problem: it silently shrinks the
        # panel of every other version and can decide a round. It is a failed run.
        errs.append(f"comparisons omit {len(missing)} issued label(s): {missing} (the prompt "
                    f"requires exactly one entry per issued opponent label)")
    notes = sj.get("notes")
    if isinstance(notes, str) and len(notes.split()) > 80:
        warns.append(f"notes is {len(notes.split())} words (schema: <=80)")
    for forbidden in ("overall", "total", "weighted", "mean", "rank"):
        if forbidden in sj:
            warns.append(f"scores.json carries a {forbidden!r} aggregate field; aggregation is "
                         f"code's job and the field is ignored")
    return errs, warns


JUDGE_DISCOVERY_DIR = "judge_review/discovery"
# The spellings that DISPOSE a judge discovery row: the judge block's own
# `clean -- checked: ...` and the review skill's `no anomalies -- checked: ...`
# (the block tells the judge to read that skill, and the module's own
# `_DISCOVERY_STATUS_TOKENS` already accepts both for the review's probes).
JUDGE_DISPOSITION_RE = re.compile(
    r"\b(?:clean|finding|unable|limitation|no anomal(?:y|ies))\b", re.I)


def judge_discovery_problems(sb: Path, rec: dict) -> tuple:
    """(errors, warnings) for the judge's OWN discovery pass (judge contract v5).

    The judge is COMPLETELY blind to provenance and is handed NO discovery
    list, so the classes the frozen checklist does not own are re-derived by
    the judge itself: one bounded pass over every side -- `target.md` plus one
    `<label>.md` per opponent label under `judge_review/discovery/` -- with the
    same candidates and depth for each side, and every candidate disposed
    (`clean -- checked: <locations>`, or a finding row with a location, a
    category, a severity and a verbatim evidence quote). Those files are the
    only instrument for those classes; a pass that never ran is
    indistinguishable from one that found nothing, so a missing or empty file
    FAILS the run (structural softness is reported as a warning instead).
    """
    labels = [str(l) for l in (rec.get("label_map") or {})]
    sides = ["target"] + labels
    dd = sb / JUDGE_DISCOVERY_DIR
    out_e, out_w = [], []
    missing = [s for s in sides if not (dd / f"{s}.md").is_file()]
    if len(missing) == len(sides):
        out_e.append(
            f"{JUDGE_DISCOVERY_DIR}/ is missing: contract v{JUDGE_CONTRACT_VERSION} requires "
            f"the judge's OWN discovery pass over every side (one disposed file per side: "
            f"target.md plus one <label>.md per opponent label). No discovery list is handed to "
            f"a judge, so this pass is the only instrument for the classes the frozen sweeps do "
            f"not own, and an unrun pass is indistinguishable from one that found nothing")
        return out_e, out_w
    if missing:
        out_e.append(
            f"{JUDGE_DISCOVERY_DIR}/ has no file for {len(missing)} side(s): "
            f"{', '.join(missing[:6])}" + (" ..." if len(missing) > 6 else "")
            + " -- the SAME candidates and depth are required for the target AND every "
              "opponent, so a side without a file was not passed with equal scrutiny")
    defined = set()
    for side in sides:
        p = dd / f"{side}.md"
        if not p.is_file():
            continue
        rows = _discovery_rows(p)
        if not rows:
            out_e.append(
                f"{JUDGE_DISCOVERY_DIR}/{side}.md carries no table rows: the pass enumerates the "
                f"shared seed candidates (plus at least two of the judge's own) and disposes "
                f"every one (`clean -- checked: <locations>` or a finding row)")
            continue
        if len(rows) < 5:
            out_w.append(
                f"{JUDGE_DISCOVERY_DIR}/{side}.md carries {len(rows)} row(s): the pass's seed "
                f"list alone is larger than that -- a handful of rows looks like a placeholder")
        ids_in_file = []
        for r in rows:
            text = _row_text(r)
            if not JUDGE_DISPOSITION_RE.search(text):
                out_w.append(f"{JUDGE_DISCOVERY_DIR}/{side}.md has a row with no disposition "
                             f"cell (`clean -- checked: <locations>` or a finding row): "
                             f"{text[:90]!r}")
            elif (re.search(r"(?i)\b(?:clean|no anomal(?:y|ies))\b", text)
                  and not re.search(r"(?i)\bchecked\b", text)):
                # The block's clean closure is `clean -- checked: <locations>`,
                # and the review's own D3 check fails a probe closed "no
                # anomalies" with nothing named: a bare `clean` states no
                # coverage at all. Reported as a warning (structural softness
                # is a warning here; only a missing/empty file fails).
                out_w.append(f"{JUDGE_DISCOVERY_DIR}/{side}.md closes a row `clean` without "
                             f"naming the checked locations (the closure is `clean -- checked: "
                             f"<locations>`): {text[:90]!r}")
            for fid in re.findall(r"(?<![A-Za-z0-9])X-\d+(?![A-Za-z0-9])", text):
                if fid in ids_in_file:
                    out_w.append(f"{JUDGE_DISCOVERY_DIR}/{side}.md lists finding id {fid} more "
                                 f"than once (one row per candidate, ids unique within the file)")
                ids_in_file.append(fid)
                defined.add(fid)
    # Every X-* id a ledger row cites must be a finding the pass recorded.
    cited = set()
    sj = scores_json_of(sb, str(rec.get("kind") or "judge"))
    if isinstance(sj, dict):
        for comp in (sj.get("comparisons") or []):
            if not isinstance(comp, dict):
                continue
            for side in ("resolved", "introduced"):
                for item in (comp.get(side) or []):
                    if not isinstance(item, dict):
                        continue
                    cid = _frozen_check_id(item.get("check"))
                    if DISCOVERY_X_ID_RE.match(cid):
                        cited.add(cid)
    unknown = sorted(cited - defined)
    if unknown:
        out_w.append(
            f"{len(unknown)} ledger row(s) cite an X-* id the discovery files never define "
            f"({', '.join(unknown[:6])}): every X row must name a finding the pass recorded -- "
            f"the file gives the evidence the row cites")
    return out_e, out_w


def postcheck_judge(ctx: Ctx, rec: dict):
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    # BLIND GROUNDING, VERIFIED WITHOUT LEAKING: recompute the code-side evidence
    # of the judge's OWN blinded target (orchestrator-side only -- nothing is
    # seeded into the sandbox, so the judge cannot lean on it) and check that the
    # judge produced the M18/M19/M20 rows itself. A missing row is a warning, not
    # a failure: the panel's validity must not depend on an agent's file naming.
    try:
        ev = code_side_evidence(ctx, sb / "target", f"{rec['id']}:judge")
        rec["judge_evidence"] = ev
        write_json_atomic(ctx.reports_dir / f"judge_evidence_{rec['id']}.json", ev)
        cap_n = int((ev.get("captions") or {}).get("count") or 0)
        len_n = len(((ev.get("lengths") or {}).get("rows")) or [])
        fmt_n = len(((ev.get("format") or {}).get("rows")) or [])
        missing = [name for n, name in ((cap_n, "M18_caption_words.md"),
                                        (len_n, "M19_length.md"),
                                        (fmt_n, "M20_formatting.md"))
                   if n and not (sb / "judge_review" / "artifacts" / name).is_file()]
        if missing:
            warns.append(
                f"BLIND JUDGE GROUNDING: the blinded target carries code-side rows (M18 {cap_n}, "
                f"M19 {len_n}, M20 {fmt_n}) but the judge produced no {', '.join(missing)} "
                f"artifact under judge_review/artifacts/ -- its own numbers are therefore not "
                f"auditable; the orchestrator's scan of target/ is recorded in "
                f"reports/judge_evidence_{rec['id']}.json. Nothing was seeded into the sandbox "
                f"(the judge stays blind).")
        # A cover letter formatted in the MANUSCRIPT template (FMT-CL1) is a
        # target defect the judge must catch and consider, whatever the other
        # versions carry; an OK closure needs the journal's own quoted override.
        cl_target = [r for r in ((ev.get("format") or {}).get("rows") or [])
                     if str(r.get("rule") or "").upper() in COVER_LETTER_STAMP_RULES]
        if cl_target:
            errs.extend(judge_cover_letter_artifact_problems(sb, cl_target))
    except Exception as e:                                            # noqa: BLE001
        warns.append(f"BLIND JUDGE GROUNDING: the code-side scan of the blinded target failed "
                     f"({type(e).__name__}: {e})")
    sj = scores_json_of(sb, rec["kind"])
    marker = marker_json(sb, rec["kind"])
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    if sj is not None:
        verrs, vwarns = validate_judge_sheet(sj, rec)
        errs.extend(verrs)
        warns.extend(vwarns)
        rec["scores"] = sj if not verrs else None
    else:
        rec["scores"] = None
        if isinstance(marker, dict) and marker.get("stage") == "judge" \
                and marker.get("status") == "complete":
            errs.append("scores.json is missing or unparseable although the marker claims "
                        "completion")
        else:
            stray = (stray_signal_note(sb, rec, SCORES_FILE)
                     or stray_signal_note(sb, rec, MARKER_FILE))
            errs.append("no completion signal: scores.json is missing/unparseable and no judge "
                        "marker exists"
                        + (f" -- {stray}" if stray else
                           " -- both belong in the sandbox ROOT, next to PROMPT.md"))
    if isinstance(marker, dict):
        if marker.get("stage") not in (None, "judge"):
            errs.append(f"marker stage mismatch: expected 'judge', got {marker.get('stage')!r}")
        if marker.get("run_id") not in (None, rec["id"]):
            errs.append(f"marker run_id mismatch: expected {rec['id']!r}, "
                        f"got {marker.get('run_id')!r}")
        if marker.get("status") == "failed":
            errs.append(f"agent reported failure: {str(marker.get('error'))[:300]}")
    else:
        warns.append(f"{MARKER_FILE} missing (scores.json alone is accepted as the judge signal)")
    # The panel's premise is that every judgement is grounded in the frozen sweep
    # review. That work lives in judge_review/ -- require it, and require the
    # visual-inspection record when the field contains Word documents.
    jr = sb / "judge_review"
    if not jr.is_dir():
        errs.append("judge_review/ is missing: the judge prompt requires the frozen-sweep review "
                    "(inventory + per-sweep artifacts) to be written there, and the panel's "
                    "grounding cannot be verified without it")
    elif not any(p.is_file() for p in jr.rglob("*")):
        errs.append("judge_review/ exists but is empty: at least the corpus inventory and the "
                    "sweep artifacts are required there")
    # Contract v5: the judge's OWN discovery pass (no list is handed to a judge,
    # so the classes no frozen check owns are re-derived by every side).
    derrs, dwarns = judge_discovery_problems(sb, rec)
    errs.extend(derrs)
    warns.extend(dwarns)
    if word_docs_present([sb / "target", sb / "field"]):
        check_visual_artifact(jr / "artifacts" / "VIS_visual.md",
                              f"the visual-inspection record {VISUAL_ARTIFACT_JUDGE}",
                              errs, warns, sandbox=sb, render_roots=[jr])
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


# One handler per run kind. `check_run_kind_support`/`run_kind_support_problems`
# compare this table with REBUILD_HANDLERS and with the round's own plan, so a
# stage that is planned but cannot be judged (or cannot be rebuilt after a
# failed attempt) is reported before its agents are launched.
POSTCHECK_HANDLERS = {
    "a1": postcheck_a1,
    "rewrite": postcheck_rewrite,
    "review": postcheck_review,
    "probe": postcheck_probe,
    "audit": postcheck_audit,
    "revise": postcheck_revise,
    "integrate": postcheck_integrate,
    "judge": postcheck_judge,
}


def run_kind_support_problems(ctx: Ctx) -> list:
    """Kinds this root's plan can produce that some dispatch table cannot handle.

    Pure and cheap; returns one sentence per broken kind ([] when every planned
    kind is postcheckable AND rebuildable). Called before a round launches its
    agents: a missing REBUILDER is invisible until a run fails, and then it
    costs the whole round (see REBUILD_HANDLERS).
    """
    problems = []
    try:
        rounds = max(1, int(ctx.rounds_count()))
    except Exception:                                            # noqa: BLE001
        rounds = 1
    kinds = set()
    for r in range(1, rounds + 1):
        try:
            kinds.update(str(e.get("kind") or "") for e in round_run_plan(ctx, r))
        except Exception:                                        # noqa: BLE001
            continue                    # an unplannable round is reported elsewhere
    for kind in sorted(k for k in kinds if k):
        missing = [table for table, reg in (("postcheck", POSTCHECK_HANDLERS),
                                            ("rebuild", REBUILD_HANDLERS))
                   if kind not in reg]
        if missing:
            problems.append(f"run kind {kind!r} has no {' and no '.join(missing)} handler")
    return problems


# =====================================================================
# JOURNAL REVISION STAGES (options 1-4)
#
#   feedback   (transfer/resubmit)   enumerate the decision letter's concerns
#   concerns   (major/minor)         the same ledger + the finding list the one
#                                    scoped revision session consumes
#   response   (resubmit/major/minor) the point-by-point response letter
#
# The stages never touch the submission corpus they read: `base/` is a copy of
# the round's base, the feedback files are copied into `feedback/`, and the
# deliverables land in `concerns/` / `review/` / `response/` at the sandbox
# root -- outside every corpus directory, so no judge view or package carries
# them.
# =====================================================================

def _stage_original_submission(ctx: Ctx, sb: Path) -> dict:
    """Stage the reviewer-visible submission under `feedback/original_submission/`.

    When the corpus keeps the version the PREVIOUS journal's editors/reviewers
    saw at `human_review_feedback/original_submission/`, every journal stage
    needs it beside the letter: a reviewer quote often refers to text that the
    current `base/` has already changed, so a concern's disposition cannot be
    decided from the letter alone. The copy is byte-for-byte, READ-ONLY and
    SEPARATE from `feedback/files/` (the letter source): a manuscript inside the
    feedback area must never be enumerated as feedback text, seeded as a
    concern, or treated as the current submission.
    """
    dirs = human_original_submission_dirs(ctx.pristine)
    label = f"{HUMAN_FEEDBACK_DIR}/{ORIGINAL_SUBMISSION_DIRNAME}"
    info = {"present": False, "label": label, "files": [],
            "note": ("the manuscript version the editors/reviewers of the previous journal "
                     "actually saw -- EVIDENCE, not the current submission (base/) and not a "
                     "feedback document")}
    if not dirs:
        return info
    root = sb / "feedback" / ORIGINAL_SUBMISSION_DIRNAME
    # Re-materialization (a retry) must start from a clean tree: the previous
    # attempt's copy is READ-ONLY (files and directories), so writing over it
    # would fail on the permission bits.
    if root.exists():
        rmtree_force(root, ignore_errors=True)
        if root.exists():
            make_tree_writable(root)
    root.mkdir(parents=True, exist_ok=True)
    for path, _dir_label in dirs:
        for p in sorted(_iter_tree_files(path, follow_dir_links=True)):
            rel = p.relative_to(path).as_posix()
            dest = root / rel
            if dest.is_dir():
                rmtree_force(dest, ignore_errors=True)
            elif dest.exists():
                with contextlib.suppress(OSError):
                    dest.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            info["files"].append(f"{ORIGINAL_SUBMISSION_DIRNAME}/{rel}")
    # Harden the staged copy: the evidence contract is read-only, and a write
    # through the sandbox copy must fail exactly like a write through the
    # canonical `non_revised/human_review_feedback/` link.
    make_tree_readonly(root)
    info["present"] = True
    (sb / "feedback" / "ORIGINAL_SUBMISSION.md").write_text(
        "# original_submission/ -- the reviewer-visible manuscript (EVIDENCE)\n\n"
        "This directory is the manuscript version the editors/reviewers of the\n"
        "PREVIOUS journal actually saw. It is NOT the current submission: `base/`\n"
        "is the submission under review/revision, and this copy is supplied only\n"
        "so the raised concerns can be understood. Use it to resolve what a\n"
        "reviewer's quote refers to and to decide whether `base/` already answers\n"
        "a concern. Never edit or copy its text into a candidate package, never\n"
        "sweep, count or quote it as the authors' current prose, and never give a\n"
        "`to-fix` concern a location that exists only in `original_submission/`.\n"
        f"\nFiles ({len(info['files'])}): " + ", ".join(sorted(info["files"])) + "\n",
        encoding="utf-8")
    return info


def original_submission_staging_problems(ctx: Ctx, sb: Path) -> list:
    """Byte-for-byte verification of the staged reviewer-visible submission.

    The stage's own copy under `feedback/original_submission/` is an INPUT like
    the canonical evidence area: the session may read it, never edit, drop or
    add a file. Checked after every feedback/concerns attempt so a manuscript
    the previous journal's reviewers saw can never be silently altered on its
    way into the concern ledger or the revision sandboxes.
    """
    dirs = human_original_submission_dirs(ctx.pristine)
    root = sb / "feedback" / ORIGINAL_SUBMISSION_DIRNAME
    errs = []
    if not dirs:
        if root.exists():
            errs.append(f"feedback/{ORIGINAL_SUBMISSION_DIRNAME}/ exists although the corpus's "
                        f"{HUMAN_FEEDBACK_DIR}/ area carries no {ORIGINAL_SUBMISSION_DIRNAME}/ "
                        f"directory: remove it -- evidence is staged from the corpus, never "
                        f"invented by the session")
        return errs
    if not root.is_dir():
        return [f"feedback/{ORIGINAL_SUBMISSION_DIRNAME}/ is missing: the corpus carries the "
                f"reviewer-visible submission and every journal stage must receive it read-only"]

    def entries(base: Path) -> dict:
        out = {}
        for p in sorted(_iter_tree_files(base, follow_dir_links=True)):
            try:
                out[p.relative_to(base).as_posix()] = sha256_file(p)
            except OSError as e:
                errs.append(f"feedback/{ORIGINAL_SUBMISSION_DIRNAME}/{p.name} is unreadable: {e}")
        return out

    want = {}
    for path, _label in dirs:
        want.update(entries(path))
    have = entries(root)
    for rel in sorted(want):
        if rel not in have:
            errs.append(f"feedback/{ORIGINAL_SUBMISSION_DIRNAME}/{rel} was dropped: the "
                        f"reviewer-visible submission is READ-ONLY evidence")
        elif have[rel] != want[rel]:
            errs.append(f"feedback/{ORIGINAL_SUBMISSION_DIRNAME}/{rel} was modified: the "
                        f"reviewer-visible submission is READ-ONLY evidence")
    for rel in sorted(set(have) - set(want)):
        errs.append(f"feedback/{ORIGINAL_SUBMISSION_DIRNAME}/{rel} was added: the staged copy "
                    f"must stay byte-for-byte identical to the corpus's evidence")
    return errs


def _write_journal_feedback_inputs(ctx: Ctx, sb: Path) -> list:
    """Copy the feedback into `feedback/` and write the concern seed.

    The ORIGINAL files are copied byte-for-byte under `feedback/files/` (the
    session may need to quote them exactly) and a text rendering lands under
    `feedback/text/` (docx/pdf converted when possible). The pre-filtered LLM
    review of the corpus's `llm_review_feedback/` area is staged the same way
    under `feedback/llm/files/` + `feedback/llm/text/`, and every seed candidate
    carries its `origin` so the ledger can never blur the two voices. A file
    that cannot be rendered is recorded in `feedback/unparsed.txt` instead of
    being dropped silently. The reviewer-visible submission, when the corpus
    carries one, is staged READ-ONLY and separately under
    `feedback/original_submission/` (see _stage_original_submission) so it is
    never seeded as feedback.
    """
    files = journal_feedback_files(ctx)
    llm_files = journal_llm_feedback_files(ctx)
    if not files and not llm_files:
        die(f"no review feedback was found: put the editors'/reviewers' comments (and/or the "
            f"false-positive-filtered LLM review) in the corpus's {HUMAN_FEEDBACK_DIR}/ or "
            f"{LLM_FEEDBACK_DIR}/ area (any file name), or name the letter with "
            f"`setup --journal-feedback FILE` (or `set-revision-mode ... --journal-feedback "
            f"FILE`). The legacy shape also works: a feedback-named file anywhere in the corpus "
            f"(feedback / referee / reviewer / editor, or decision-letter/notice/email in its name), typically under "
            f"raw_data/.")
    previous = journal_previous_responses(ctx)
    (sb / "feedback" / "files").mkdir(parents=True, exist_ok=True)
    (sb / "feedback" / "text").mkdir(parents=True, exist_ok=True)
    if llm_files:
        (sb / "feedback" / "llm" / "files").mkdir(parents=True, exist_ok=True)
        (sb / "feedback" / "llm" / "text").mkdir(parents=True, exist_ok=True)
    if previous:
        (sb / "feedback" / "previous_responses" / "files").mkdir(parents=True, exist_ok=True)
        (sb / "feedback" / "previous_responses" / "text").mkdir(parents=True, exist_ok=True)
    seed, unparsed, labels, llm_labels = [], [], [], []
    streams = ([(path, label, "human", sb / "feedback") for path, label in files]
               + [(path, label, "llm", sb / "feedback" / "llm") for path, label in llm_files]
               + [(path, label, "previous", sb / "feedback" / "previous_responses")
                  for path, label in previous])
    for path, label, origin, parent in streams:
        safe = label.replace("/", "__")
        if origin == "human":
            labels.append(label)
        elif origin == "llm":
            llm_labels.append(label)
        dest = parent / "files" / safe
        if dest.exists():
            # A read-only source (a chmod a-w evidence file) was copied with its
            # mode in a previous partial materialization: replace the stale copy
            # instead of failing on the permission bits.
            with contextlib.suppress(OSError):
                make_writable(dest)
            with contextlib.suppress(OSError):
                dest.unlink()
        shutil.copy2(path, dest)
        text, note = feedback_text_of(path)
        if text.strip():
            (parent / "text" / (safe + ".txt")).write_text(text, encoding="utf-8")
            if origin != "previous":
                for row in seed_concern_candidates(text):
                    seed.append(dict(row, source=label, origin=origin))
        else:
            unparsed.append(f"{label}: {note or 'no text extracted'}")
    original_submission = _stage_original_submission(ctx, sb)
    write_json_atomic(sb / "feedback" / "CONCERN_SEED.json",
                      {"files": labels, "llm_files": llm_labels,
                       "candidates": seed, "unparsed": unparsed,
                       "previous_responses": [label for _p, label in previous],
                       "original_submission": original_submission,
                       "journal_from": str((ctx.cfg or {}).get("journal_feedback_from") or ""),
                       "target_journal": str((ctx.cfg or {}).get("journal") or "")})
    if unparsed:
        (sb / "feedback" / "unparsed.txt").write_text("\n".join(unparsed) + "\n",
                                                      encoding="utf-8")
    return seed


JOURNAL_LEDGER_SCHEMA = """{
  "journal_from": "<the journal the feedback came from>",
  "target_journal": "<the journal this revision is for>",
  "mode": "<transfer|resubmit|major|minor>",
  "source_files": ["<the feedback file names you read>"],
  "concerns": [
    {"id": "R1-1",
     "source": "<feedback file>",
     "author": "Reviewer 1",
     "quote": "<verbatim, <=300 chars; it must appear in feedback/text/>",
     "summary": "<one sentence, in your own words>",
     "action": "text|analysis|new-experiment|clarification|formatting|policy|disagree",
     "manuscript_location": "<where the concern lives in base/, or null; cite the reviewer-visible original_submission/ only as context, never as the fix target>",
     "disposition": "to-fix|already-addressed|manual|not-applicable",
     "evidence_needed": "<what evidence an answer needs; empty when the text answers it>"}
  ]
}"""


def _journal_stage_base(ctx: Ctx, sb: Path, r: int) -> None:
    """base/ + non_revised/ for one journal stage (read-only copies)."""
    _require_done(ctx, rid_a1(r), "the journal revision stages read the round's base")
    ensure_copy(ctx.sandbox_of(ctx.run(rid_a1(r))) / "base", sb / "base")
    ensure_pristine_input(ctx, sb / PRISTINE_DIR)


def materialize_feedback(ctx: Ctx, r: int) -> dict:
    """Modality 1-2: the concern-enumeration sandbox (kind "feedback")."""
    rid = rid_feedback(r)
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    _journal_stage_base(ctx, sb, r)
    (sb / "concerns").mkdir(exist_ok=True)
    seed = _write_journal_feedback_inputs(ctx, sb)
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt,
                          feedback_prompt(ctx, sb, r, seed) + note + shared_blocks())
    rec = ctx.register(rid, "feedback", r, f"runs/{rid}", produces=rid)
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR, follow_dir_links=True)}
    rec["feedback_files"] = [label for _p, label in journal_feedback_files(ctx)]
    rec["llm_feedback_files"] = [label for _p, label in journal_llm_feedback_files(ctx)]
    rec["original_submission"] = (read_json(sb / "feedback" / "CONCERN_SEED.json",
                                            revive=False, lenient=True) or {}).get(
        "original_submission") or {"present": False}
    return rec


def materialize_concerns(ctx: Ctx, r: int) -> dict:
    """Modalities 3-4: the scoped concern ledger + finding list (kind "concerns")."""
    rid = rid_concerns(r)
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    _journal_stage_base(ctx, sb, r)
    (sb / "concerns").mkdir(exist_ok=True)
    (sb / REVIEW_DIR).mkdir(exist_ok=True)
    (sb / REVIEW_DIR / "artifacts").mkdir(parents=True, exist_ok=True)
    seed = _write_journal_feedback_inputs(ctx, sb)
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt,
                          concerns_prompt(ctx, sb, r, seed) + note + shared_blocks())
    rec = ctx.register(rid, "concerns", r, f"runs/{rid}", produces=rid)
    rec["inputs_manifest"] = {"base": hash_manifest(sb / "base"),
                              PRISTINE_DIR: hash_manifest(sb / PRISTINE_DIR, follow_dir_links=True)}
    rec["feedback_files"] = [label for _p, label in journal_feedback_files(ctx)]
    rec["llm_feedback_files"] = [label for _p, label in journal_llm_feedback_files(ctx)]
    rec["original_submission"] = (read_json(sb / "feedback" / "CONCERN_SEED.json",
                                            revive=False, lenient=True) or {}).get(
        "original_submission") or {"present": False}
    return rec


def _journal_concern_source(ctx: Ctx, r: int) -> Path:
    """The sandbox that carries the concern ledger for this round."""
    rid = rid_concerns(r) if journal_is_scoped(ctx) else rid_feedback(r)
    _require_done(ctx, rid, "the concern ledger is the input of this stage")
    return ctx.sandbox_of(ctx.run(rid))


def materialize_response(ctx: Ctx, r: int, target: Path = None,
                         target_label: str = "") -> dict:
    """Modes 2-4: the response-to-reviewers sandbox (kind "response").

    `target` is the final package the letter describes: the single scoped
    revision's `revised/` for major/minor, or the pinned champion for a
    resubmit. The caller records the target in the run's provenance so `retry`
    rebuilds the same sandbox.
    """
    rid = rid_response(r)
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True, exist_ok=True)
    src_sb = _journal_concern_source(ctx, r)
    ensure_copy(src_sb / "concerns", sb / "concerns")
    if (src_sb / "feedback").is_dir():
        ensure_copy(src_sb / "feedback", sb / "feedback")
    if (src_sb / REVIEW_DIR).is_dir():
        ensure_copy(src_sb / REVIEW_DIR, sb / REVIEW_DIR)
    if target is None:
        rec0 = ctx.run(rid) or {}
        tgt_rel = str(rec0.get("target_dir") or "").strip()
        if tgt_rel:
            target = ctx.root / tgt_rel
        elif journal_is_scoped(ctx):
            rev_rec = ctx.run(rid_for_fresh(r, revise_vid(1)))
            if rev_rec is None:
                die(f"the response stage cannot be materialized: the scoped revision run "
                    f"{rid_for_fresh(r, revise_vid(1))} does not exist yet. Run the revision "
                    f"stage first (`run`).")
            target = ctx.sandbox_of(rev_rec) / REVISED_DIR
    if target is None or not target.is_dir():
        die(f"the response stage has no final package to describe (run {rid}). "
            f"This is an orchestration error -- report it with the root's state.json.")
    # ensure_copy, not "copy only when absent": a sandbox killed mid-copy left a
    # PARTIAL target/ that the old guard froze in place -- the letter was then
    # verified against a truncated package and the truncation was hashed into
    # the run's input manifest (see ensure_copy's own docstring).
    ensure_copy(target, sb / "target", exclude_top=("work",), skip_aux=True)
    (sb / "response").mkdir(exist_ok=True)
    ledger = journal_concern_ledger(src_sb)
    note = prior_failure_block(ctx.run(rid) or {}) if ctx.run(rid) else PRIOR_FAILURE_NONE
    prompt = sb / "PROMPT.md"
    if not prompt.is_file():
        _copy_session_tools(sb)
        write_text_atomic(prompt,
                          response_prompt(ctx, sb, r, target_label or target.parent.name,
                                          ledger) + note + shared_blocks())
    ledger_rid = rid_concerns(r) if journal_is_scoped(ctx) else rid_feedback(r)
    rec = ctx.register(rid, "response", r, f"runs/{rid}", upstream_run_id=ledger_rid,
                       target_dir=target.relative_to(ctx.root).as_posix()
                       if is_within(target, ctx.root) else str(target))
    rec["inputs_manifest"] = {"target": hash_manifest(sb / "target"),
                              "concerns": hash_manifest(sb / "concerns")}
    return rec


def _journal_feedback_labels(ctx: Ctx) -> list:
    return [label for _p, label in journal_feedback_files(ctx)]


def journal_feedback_origin(ctx: Ctx) -> str:
    """The human-readable source of the feedback a round answers."""
    if journal_mode_of(ctx) == JOURNAL_MODE_LLM:
        return f"the false-positive-filtered {LLM_FEEDBACK_DIR}/ review"
    return (str((ctx.cfg or {}).get("journal_feedback_from") or "").strip()
            or "the source journal")


def _journal_llm_feedback_labels(ctx: Ctx) -> list:
    return [label for _p, label in journal_llm_feedback_files(ctx)]


def _journal_seed_text(ctx: Ctx, sb: Path) -> str:
    data = read_json(sb / "feedback" / "CONCERN_SEED.json", revive=False, lenient=True) or {}
    rows = [r for r in (data.get("candidates") or []) if isinstance(r, dict)]
    if not rows:
        return "- (the mechanical split found no candidate headings; read the text yourself)"

    def _line(r: dict) -> str:
        tag = (" (LLM review, false positives pre-filtered)"
               if str(r.get("origin") or "") == "llm" else "")
        return (f"- [{str(r.get('source') or '')}]{tag} "
                f"{str(r.get('heading') or '')[:110]}: "
                f"{str(r.get('excerpt') or '')[:280]}")

    return "\n".join(_line(r) for r in rows[:80])


def feedback_prompt(ctx: Ctx, sb: Path, r: int, seed_rows: list) -> str:
    """The concern-enumeration prompt (modes 1-2)."""
    mode = journal_mode_of(ctx)
    info = JOURNAL_MODES[mode]
    labels = _journal_feedback_labels(ctx)
    llm_labels = _journal_llm_feedback_labels(ctx)
    from_j = journal_feedback_origin(ctx)
    return f"""JOURNAL FEEDBACK — CONCERN ENUMERATION (one session; you do NOT edit any manuscript)

This run is "{mode}" (option {info['option']}: {info['label']}). The review
feedback from {from_j} — the human editors'/reviewers' comments and/or the
false-positive-filtered LLM review — has to become a
complete, enumerated concern ledger before anyone touches the manuscript.

WHAT YOU READ (all of it):
  * feedback/files/  — the original human feedback file(s), byte-for-byte (from
    the corpus's `human_review_feedback/` area, or, in an older corpus, from a
    feedback-named file under `raw_data/`):
{chr(10).join('      - ' + x for x in labels) or '      - (none)'}
  * feedback/text/   — the same files as plain text (use THIS for quoting)
  * feedback/llm/files/ — the original LLM review file(s), byte-for-byte (from
    the corpus's `llm_review_feedback/` area; present only when the corpus
    carries one):
{chr(10).join('      - ' + x for x in llm_labels) or '      - (none)'}
  * feedback/llm/text/ — the same LLM files as plain text (use THIS for quoting)
  * feedback/CONCERN_SEED.json — the pipeline's mechanical candidate split; it
    is a seed, not the answer
  * base/            — the manuscript the feedback is about (read-only)
  * feedback/original_submission/ — ONLY when the seed records
    `original_submission.present`: the manuscript version the editors/reviewers
    of {from_j} actually saw (READ-ONLY evidence)

If `feedback/CONCERN_SEED.json` lists `previous_responses`, those are the
authors' OWN earlier response-to-reviewers documents (under
`feedback/previous_responses/`): they are CONTEXT (what was promised before),
never the journal's letter. Never enumerate a previous response as a concern
and never quote it as something the reviewers said.

ABOUT `feedback/original_submission/` (when present): the reviewers wrote their
concerns against THIS earlier version, while every row's `manuscript_location`
must name where the concern lives in the CURRENT `base/`. Use the reviewer-visible
copy only to resolve what a quote refers to and to decide whether `base/` already
answers a concern. It is never the submission under revision, never a source of
text to copy, and never swept or quoted as the authors' current prose. A concern
whose target no longer exists in `base/` because it was already changed is
`already-addressed` (quote the `base/` location that answers it; cite
`original_submission/` only as context) or `not-applicable` (state why). Never
mark a concern `to-fix` with a location that exists only in
`feedback/original_submission/`.

ABOUT `feedback/llm/` (when present): this is a machine-generated review whose
FALSE POSITIVES WERE ALREADY FILTERED OUT upstream. Every remaining item is a
real concern: enumerate it like a human reviewer's demand, never dismiss it
because a model wrote it, and never re-litigate it as a false positive. If after
checking `base/` and the evidence you still believe a row is wrong, it STILL
gets its own ledger row — disposition `not-applicable` (or action `disagree`)
with the concrete rationale in `evidence_needed` — never a silent omission. Name
the LLM the file itself names as the `author` (e.g. "Claude review"); when the
file names none, use "LLM review (pre-filtered)". A demand the human letter and
the LLM review both raise is still ONE row whose `source` names both.

SEED (read the real text after it):
{_journal_seed_text(ctx, sb)}

THE LEDGER IS THE DELIVERABLE (one row per distinct concern):
  * A reviewer paragraph that raises three separate demands is three rows; the
    same demand repeated by the editor, a reviewer or the LLM review is ONE row
    whose `source` names every place it was raised. Never merge two demands,
    never split one.
  * `quote` is VERBATIM from the feedback (<=300 chars, whitespace-normalised):
    it is checked mechanically against feedback/text/ and feedback/llm/text/, so
    a paraphrase fails.
  * `id` is stable and human-usable: `ED-<k>` for editor/decision points,
    `R<n>-<k>` for reviewer n (R1-3 = reviewer 1, third point).
  * `action` says what answering it demands: text | analysis | new-experiment |
    clarification | formatting | policy | disagree.
  * `disposition`: to-fix (the manuscript must change) | already-addressed
    (base/ already answers it — name and quote the BASE/ location, never
    `feedback/original_submission/`) | manual (needs the authors: a new
    experiment or a judgement call) | not-applicable (say why in
    evidence_needed).
  * Never invent a concern, never soften or sharpen one, never drop a repeat.

WRITE:
  * concerns/JF_concerns.json — the ledger:
{JOURNAL_LEDGER_SCHEMA}
  * concerns/JF_concerns.md — the same rows as a markdown table
    (id | source | author | action | disposition | quote | summary | location)
  * Do NOT write review/, do NOT edit base/, non_revised/ or feedback/, and do
    not write any other directory.

{marker_root_rule()}
Write `_pipeline_done.json` (JSON: stage "feedback", run_id "{sb.name}",
round {int(r)}, status "complete") as the very LAST step.
"""


def concerns_prompt(ctx: Ctx, sb: Path, r: int, seed_rows: list) -> str:
    """The scoped concern-enumeration + finding-list prompt (modes 3-4)."""
    mode = journal_mode_of(ctx)
    info = JOURNAL_MODES[mode]
    labels = _journal_feedback_labels(ctx)
    llm_labels = _journal_llm_feedback_labels(ctx)
    from_j = journal_feedback_origin(ctx)
    return f"""JOURNAL FEEDBACK — {mode.upper()} REVISION RECONCILIATION (one session; NO edits)

This run REPLACES the general review of a {mode} revision (option
{info['option']}: {info['label']}). The review feedback of
{from_j} — the human editors'/reviewers' comments
and/or the false-positive-filtered LLM review — requires an answer to every
point, and the manuscript may change ONLY where a concern requires it. Deliver
the concern ledger AND the finding list the single revision session follows.

WHAT YOU READ (all of it):
  * feedback/files/  — the original human feedback file(s), byte-for-byte (from
    the corpus's `human_review_feedback/` area, or, in an older corpus, from a
    feedback-named file under `raw_data/`):
{chr(10).join('      - ' + x for x in labels) or '      - (none)'}
  * feedback/text/   — the same files as plain text (use THIS for quoting)
  * feedback/llm/files/ — the original LLM review file(s), byte-for-byte (from
    the corpus's `llm_review_feedback/` area; present only when the corpus
    carries one):
{chr(10).join('      - ' + x for x in llm_labels) or '      - (none)'}
  * feedback/llm/text/ — the same LLM files as plain text (use THIS for quoting)
  * feedback/CONCERN_SEED.json — the pipeline's mechanical candidate split
  * base/            — the manuscript under revision (read-only)
  * feedback/original_submission/ — ONLY when the seed records
    `original_submission.present`: the manuscript version the editors/reviewers
    of {from_j} actually saw (READ-ONLY evidence)

If `feedback/CONCERN_SEED.json` lists `previous_responses`, those are the
authors' OWN earlier response documents (under `feedback/previous_responses/`):
context for what was promised, never a concern and never a reviewer quote.

When `feedback/original_submission/` is present, the reviewers wrote against
THAT version while every finding and every `manuscript_location` must name the
CURRENT `base/`. Use the reviewer-visible copy only to resolve a quote and to
decide whether `base/` already answers a concern; never edit it, never copy its
text, and never quote it as the authors' current prose.

When `feedback/llm/` is present, its false positives were ALREADY filtered out
upstream: every remaining item is a real concern with the same standing as a
human reviewer's point. Enumerate it, answer it, and never dismiss it as a model
false positive; a row you still believe is wrong gets `not-applicable` (or
action `disagree`) with the concrete rationale — never a silent omission. Name
the LLM the file itself names as `author`, else "LLM review (pre-filtered)"; a
demand the letter and the LLM review both raise is ONE row naming both sources.

SEED (read the real text after it):
{_journal_seed_text(ctx, sb)}

THE LEDGER (one row per distinct concern; same shape as modes 1-2):
{JOURNAL_LEDGER_SCHEMA}
`disposition` for a scoped revision:
  * to-fix             the manuscript must change; becomes ONE finding
  * already-addressed  quote the base/ location that already answers it (never
                       `feedback/original_submission/`, which is only context)
  * manual             needs the authors (new experiment / judgement call);
                       becomes ONE finding with status "unresolvable"
  * not-applicable     say why; no finding

THE FINDING LIST (the revision session consumes it):
  * review/findings.json — {{"submission_dir": "base", "findings": [ ... ],
    "coverage": [ ... ]}} with ONE finding per concern whose disposition is
    to-fix or manual, and NO other findings (a scoped revision does not fix
    what the reviewers did not raise):
      id          the concern id        location  "<file:section/line in base/>"
      category    0                     check     "JF"
      severity    "Critical"|"Major"|"Minor"
      evidence    the verbatim reviewer quote
      explanation what the revision must change (or why it is manual)
      status      "resolvable" (to-fix) | "unresolvable" (manual)
      concern     the concern id
  * review/artifacts/JF_concerns.md — the ledger as a markdown table.
  * review/findings.md — the findings in the review's markdown shape.
  * Do NOT edit base/ or the feedback; do not write revised/ here.

{marker_root_rule()}
Write `_pipeline_done.json` (JSON: stage "concerns", run_id "{sb.name}",
round {int(r)}, status "complete") as the very LAST step.
"""


def response_prompt(ctx: Ctx, sb: Path, r: int, target_label: str,
                    concern_ledger: dict) -> str:
    """The response-to-reviewers prompt (modes 2-4; option 1 writes no letter)."""
    mode = journal_mode_of(ctx)
    info = JOURNAL_MODES[mode]
    from_j = str((ctx.cfg or {}).get("journal_feedback_from") or "").strip()
    to_j = str((ctx.cfg or {}).get("journal") or "").strip()
    ids = [str(c.get("id") or "") for c in (concern_ledger.get("concerns") or [])
           if isinstance(c, dict)]
    # The analysis code is not part of the submission by default: the letter is
    # a to-be-submitted file, so it must not refer into `code/`. With
    # `submit_code: on` the area ships and a citation is legitimate.
    code_rule = ((f"  * `{CODE_DIR}/` ships with this submission (`submit_code: on`): a "
                  f"`{CODE_DIR}/` path is citeable exactly like any other package file;\n"
                  if submit_code_of(ctx) else
                  f"  * `{CODE_DIR}/` is NOT part of the submission (the analysis code is not "
                  f"submitted in this root): never cite a `{CODE_DIR}/` path in "
                  f"`changes`/`new_data` -- the letter is a to-be-submitted file and must not "
                  f"refer into the code directory. Describe a code change in the response "
                  f"sentence instead, and cite the submission document (Methods/text/legend) "
                  f"that carries it;\n")
                 + f"  * `README*.md` / `README*.txt` files are NEVER submitted (the author's "
                   f"own documentation, dropped from the package like `{CODE_DIR}/`): never "
                   f"cite one in `changes`/`new_data`;\n")
    return f"""RESPONSE TO REVIEWERS (the point-by-point letter; you do NOT edit the manuscript)

Revision mode: {mode} (option {info['option']}: {info['label']}).
Feedback from: {(from_j or '(the source journal)')}. Target journal:
{(to_j or '(the target journal)')}.

WHAT YOU READ:
  * target/   — the FINAL package ({target_label}); every change you claim must
    exist here. revision_report.json and DIFF_LEDGER.md name what changed and
    where — use them, never your memory.
  * concerns/JF_concerns.json — the concern ledger; the letter covers EVERY id
    exactly once: {', '.join(ids) if ids else '(none)'}
  * feedback/text/ — the reviewers' own wording (quote verbatim; never invent a
    reviewer or a sentence).
  * feedback/llm/text/ — the LLM review's own wording, when the corpus carries a
    pre-filtered LLM review (same rule: quote verbatim, never invent a sentence).
  * feedback/ORIGINAL_SUBMISSION.md (and feedback/original_submission/, when it
    is present) — EVIDENCE ONLY: the manuscript version the previous journal's
    editors/reviewers actually saw. It is NOT the current submission (`target/`
    is), its text is never quoted as what the authors changed, and it is never
    a `changes` target; use it only to resolve what a reviewer's quote refers to.

WRITE:
  * response/RESPONSE_TO_REVIEWERS.md — one block per concern:
      ## <id> — <short title>
      **Comment:** "<verbatim reviewer quote>"
      **Response:** what the authors did, or why they did not; state no claim
      beyond what target/ shows; a new experiment cites its actual new data/file
      or is marked "planned" with the exact steps and claims no result
      **Changes:** <file:location — before -> after>, one line per change
  * response/response_map.json — the machine-readable map:
      {{"journal_from": "...", "target_journal": "...", "mode": "{mode}",
        "rows": [{{"id": "<concern id>",
                   "status": "addressed|partially-addressed|already-addressed|planned|not-applicable",
                   "response": "<one sentence>",
                   "changes": [{{"file": "<package-relative path>",
                                 "location": "<section/line>",
                                 "before": "...", "after": "..."}}],
                   "new_data": ["<package-relative file the response cites>"]}}]}}
    ONE row per concern id, the same ids as the ledger, no extras.

ABSOLUTE RULES:
  * every changes[].file and new_data[] path must EXIST in target/ (checked
    mechanically): never cite a figure, table or file that is not in the package;
{code_rule}  * status "addressed"/"partially-addressed" needs at least one change or one
    new data file; status "already-addressed" is only for a concern the ledger
    already marks `already-addressed` (name the location in `response`, cite no
    change); status "planned" claims nothing done yet;
  * never fabricate a result, a number or a reviewer sentence;
  * the letter is a submission document but NOT manuscript text: write it here
    in response/ and never edit the package.

{marker_root_rule()}
Write `_pipeline_done.json` (JSON: stage "response", run_id "{sb.name}",
round {int(r)}, status "complete") as the very LAST step.
"""


def journal_review_block(ctx: Ctx, sb: Path) -> str:
    """The block appended to the standard review prompt (modes 1-2)."""
    mode = journal_mode_of(ctx)
    llm_only = mode == JOURNAL_MODE_LLM
    heading = ("LLM REVIEW FEEDBACK RECONCILIATION" if llm_only
               else "JOURNAL FEEDBACK RECONCILIATION")
    carried = (f"the false-positive-filtered LLM review ({LLM_FEEDBACK_DIR}/; there is no "
               f"journal decision letter in this mode)"
               if llm_only else
               "the review feedback -- the editors'/reviewers' decision letter and, when the "
               "corpus ships one, the false-positive-filtered LLM review --")
    return f"""

=== {heading} (revision mode: {mode}) ===
The round carries {carried} in `concerns/`
(`JF_concerns.json` / `JF_concerns.md`; external prose -- never
quote a reviewer or the LLM review as if the authors wrote it). Every concern
has the same standing, whatever its source. Beyond the normal sweep:
  * reconcile EVERY concern id in the ledger and write
    `review/concerns_reconciled.json` with one row per id:
    {{"id": "...", "status": "finding|already-addressed|manual|not-applicable",
      "finding": "<finding id or null>", "location": "<base/ file:where>",
      "rationale": "<one sentence>"}};
  * a concern base/ does not answer is a FINDING with `check: "JF"`,
    `concern: "<id>"`, id `JF-<n>`, category 0, and the source's verbatim quote
    as its evidence;
  * when `feedback/original_submission/` exists it is the manuscript version the
    editors/reviewers ACTUALLY SAW -- EVIDENCE, not the submission under review.
    Use it only to resolve what a quoted concern refers to and to decide whether
    `base/` already answers it; a concern that no longer exists in `base/` is
    `already-addressed` (with the `base/` location) or `not-applicable`, never a
    finding. Every finding still quotes `base/`; never sweep, count or quote the
    reviewer-visible copy as the authors' current prose, and never report a
    defect that exists only in it;
  * do not drop, merge or soften a concern. Real defects the sweeps find are
    still findings -- this is a normal round otherwise.
"""


def journal_revise_block(ctx: Ctx) -> str:
    """The block appended to the revise prompt (all four modes)."""
    mode = journal_mode_of(ctx)
    info = JOURNAL_MODES[mode]
    if not info.get("feedback"):
        # `init`/`continue` have no letter and no concern ledger: the historical
        # revise prompt must not claim a journal revision is under way.
        return ""
    if info["scoped"]:
        return f"""

=== {mode.upper()} REVISION — CONCERN-SCOPED EDITS ONLY ===
This is a real {mode} revision: the review raised the concerns now in
`review/findings.json` (every finding has `check: "JF"` and a `concern` id;
`concerns/JF_concerns.md` carries the sources' own words — human reviewers
and/or the false-positive-filtered LLM review, with the same standing).
  * Change the manuscript ONLY where a concern requires it. Every edit names the
    JF finding id / concern id that raised it.
  * NO unrelated changes: no restructuring, no style re-wording, no new findings
    from a rescan, no renames, no deletions, no added documents, no figure
    regeneration. Anything else you notice goes to MANUAL_STEPS.md as a note for
    the authors -- it is NOT edited here.
  * Findings with status "unresolvable" (a new experiment, a judgement call) are
    answered in MANUAL_STEPS.md with the exact steps; never invent the result.
  * The response letter is written in a later, separate stage from your ledger:
    record every edit (file, location, before, after).
  * The pipeline verifies the scope mechanically: a changed file the ledger does
    not name, or a file added/removed, fails the attempt.
  * When `feedback/original_submission/` exists it is the manuscript the
    previous journal's reviewers saw -- EVIDENCE, not the package you edit.
    Read it only to understand a concern; every edit and every quoted location
    must come from `base/` (never copy text out of the reviewer-visible copy).
"""
    tail = ("A response-to-reviewers letter is NOT written for this mode."
            if not info["response"] else
            "A response-to-reviewers letter is generated AFTER this stage from the "
            "revision ledger -- record every JF edit (file, location, before, after) "
            "and never claim a change that is not in the package.")
    return f"""

=== JOURNAL REVISION MODE: {mode.upper()} (option {info['option']}) ===
The round is a real revision against the review feedback in `concerns/` (the
human editors'/reviewers' points and/or the false-positive-filtered LLM review;
external prose -- never attribute it to the authors, and give the LLM review's
findings the same standing). The review's JF findings (`check: "JF"`, with a
`concern` id) are mandatory: every one is either fixed in the package or
recorded as a manual item with the exact steps.
{tail}
The manuscript must answer every concern; the normal findings still apply.
When `feedback/original_submission/` exists it is the earlier, reviewer-visible
version -- EVIDENCE, not the package you edit: read it only to understand a
concern, and make every edit, and quote every location, in the current `base/`.
"""


def journal_rewrite_block(ctx: Ctx) -> str:
    """The block appended to the standard rewrite prompt (modes 1-2)."""
    mode = journal_mode_of(ctx)
    info = JOURNAL_MODES[mode]
    llm_only = mode == JOURNAL_MODE_LLM
    tail = ("No response letter is written for a transfer; the rewrite IS the answer."
            if not info["response"] else
            "The response letter is generated later from the final package's ledger.")
    if llm_only:
        tail = ("No response letter is written in this mode; the rewrite IS the answer to the "
                "pre-filtered LLM review.")
    sources = (f"the false-positive-filtered LLM review ({LLM_FEEDBACK_DIR}/)"
               if llm_only else
               "the editors'/reviewers' points and, when the corpus ships one, the "
               "false-positive-filtered LLM review")
    heading = ("LLM REVIEW MODE" if llm_only else "JOURNAL REVISION MODE")
    return f"""

=== {heading}: {mode.upper()} — the rewrite answers the concerns ===
This from-scratch rewrite is for a real submission attempt (mode {mode}, option
{info['option']}). `concerns/JF_concerns.json|md` carries the review feedback --
{sources} -- as external prose; never copy a reviewer's or the LLM review's
sentence into the manuscript. A concern's source never changes its standing:
every `to-fix`/`manual` row must be answered.
  * The rewritten manuscript must demonstrably answer every concern whose
    `disposition` is `to-fix` or `manual`; list the per-concern handling in
    REWRITE_REPORT.md (concern id -> what the rewrite does, or why it is manual).
  * A `manual` concern (a new experiment) is never faked: state the plan in
    MANUAL_STEPS.md and keep the claim honest.
  * When `feedback/original_submission/` exists it is the version the reviewers
    saw -- EVIDENCE, not the rewrite's source. Use it only to understand a
    concern, rewrite from `base/`, and never copy text out of the
    reviewer-visible copy.
  * {tail}
"""


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def journal_ledger_problems(ctx: Ctx, sb: Path, errs: list, warns: list) -> dict:
    """Schema + quote verification of the concern ledger ({} when unusable)."""
    path = sb / JOURNAL_CONCERNS_JSON_REL
    if not path.is_file():
        errs.append(f"{JOURNAL_CONCERNS_JSON_REL} is missing: it is the concern ledger every "
                    f"later journal stage keys on")
        return {}
    data = read_json(path, revive=False, lenient=True)          # agent-written
    if not isinstance(data, dict):
        errs.append(f"{JOURNAL_CONCERNS_JSON_REL} does not parse as a JSON object")
        return {}
    rows = data.get("concerns")
    if not isinstance(rows, list) or not rows:
        errs.append(f"{JOURNAL_CONCERNS_JSON_REL} carries no 'concerns' rows: the ledger is the "
                    f"deliverable (one row per distinct concern), and an empty ledger would "
                    f"silently answer nothing")
        return data
    texts = []
    for tdir in (sb / "feedback" / "text", sb / "feedback" / "llm" / "text"):
        if tdir.is_dir():
            for p in sorted(tdir.glob("*.txt")):
                try:
                    texts.append(_norm_ws(p.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    continue
    haystack = " \n ".join(texts)
    seen = set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errs.append(f"concerns[{i}] is not an object")
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            errs.append(f"concerns[{i}] has no id")
            continue
        if cid in seen:
            errs.append(f"concern id {cid!r} appears twice: ids are the keys every later stage "
                        f"uses, so they must be unique")
        seen.add(cid)
        quote = _norm_ws(row.get("quote"))
        if len(quote) < 8:
            errs.append(f"concern {cid}: quote is missing/too short (a verbatim <=300-char "
                        f"excerpt is required)")
        elif quote not in haystack:
            errs.append(f"concern {cid}: the quote is not verbatim in any feedback/text/ or "
                        f"feedback/llm/text/ rendering (checked whitespace-normalised); a "
                        f"paraphrase fails here")
        action = str(row.get("action") or "").strip()
        if action not in JOURNAL_CONCERN_ACTIONS:
            errs.append(f"concern {cid}: action {action!r} is not one of "
                        f"{', '.join(JOURNAL_CONCERN_ACTIONS)}")
        disp = str(row.get("disposition") or "").strip()
        if disp not in JOURNAL_CONCERN_DISPOSITIONS:
            errs.append(f"concern {cid}: disposition {disp!r} is not one of "
                        f"{', '.join(JOURNAL_CONCERN_DISPOSITIONS)}")
        if disp == "already-addressed" and not str(row.get("manuscript_location") or "").strip():
            errs.append(f"concern {cid}: disposition 'already-addressed' needs the base/ "
                        f"location that answers it")
        if disp in ("manual", "not-applicable") and not str(
                row.get("evidence_needed") or "").strip():
            errs.append(f"concern {cid}: disposition {disp!r} needs evidence_needed (the exact "
                        f"steps the authors must take / why the point does not apply)")
        if not str(row.get("summary") or "").strip():
            errs.append(f"concern {cid}: summary is empty")
    if not (sb / JOURNAL_CONCERNS_MD_REL).is_file():
        warns.append(f"{JOURNAL_CONCERNS_MD_REL} is missing (the human-readable ledger table)")
    data["_to_fix"] = sum(1 for r in rows if isinstance(r, dict)
                          and str(r.get("disposition")) in ("to-fix", "manual"))
    return data


def postcheck_feedback(ctx: Ctx, rec: dict):
    """Modes 1-2: the concern ledger is complete and verbatim."""
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "feedback", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    data = journal_ledger_problems(ctx, sb, errs, warns)
    if data:
        rec["concerns"] = {"count": len(data.get("concerns") or []),
                           "to_fix": data.get("_to_fix", 0),
                           "files": rec.get("feedback_files") or []}
    fdir = sb / "feedback" / "files"
    ldir = sb / "feedback" / "llm" / "files"
    have_human = fdir.is_dir() and any(fdir.iterdir())
    have_llm = ldir.is_dir() and any(ldir.iterdir())
    if not (have_human or have_llm):
        errs.append("feedback/files/ and feedback/llm/files/ are both empty: the original "
                    "feedback files must be copied in (they are the quote source of record)")
    errs.extend(original_submission_staging_problems(ctx, sb))
    _check_pristine_copy(ctx, rec, pristine_dirname(sb), errs)
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


def journal_review_coverage_problems(ctx: Ctx, rec: dict, sb: Path, fj: dict) -> list:
    """Modes 1-2: the review reconciled EVERY concern of the decision letter.

    Reads `review/concerns_reconciled.json` (one row per concern id) against the
    feedback run's ledger and the review's own findings: a row that claims
    `finding` must name a JF finding that exists; `already-addressed` must name
    the location; `manual`/`not-applicable` must give a rationale.
    """
    errs = []
    r = int(rec.get("round") or 1)
    fb_rec = ctx.run(rid_feedback(r))
    if fb_rec is None:
        return [f"the review must reconcile the decision letter's concerns, but the feedback run "
                f"{rid_feedback(r)} does not exist"]
    rows = journal_concern_rows(ctx.sandbox_of(fb_rec))
    if not rows:
        return errs
    want = {str(x.get("id")) for x in rows}
    path = sb / REVIEW_DIR / "concerns_reconciled.json"
    if not path.is_file():
        errs.append(f"{REVIEW_DIR}/concerns_reconciled.json is missing: revision modes 1-2 must "
                    f"reconcile every concern of the decision letter (one row per id)")
        return errs
    data = read_json(path, revive=False, lenient=True)
    if not isinstance(data, dict):
        errs.append(f"{REVIEW_DIR}/concerns_reconciled.json does not parse as a JSON object")
        return errs
    got_rows = [x for x in (data.get("rows") or []) if isinstance(x, dict)]
    got = [str(x.get("id") or "") for x in got_rows]
    # "one row per concern id" is this function's own contract: two rows for the
    # same id (the classic contradictory pair) were invisible to the set
    # arithmetic below, which saw the id as present exactly once.
    dups = sorted({cid for cid in got if cid and got.count(cid) > 1})
    if dups:
        errs.append(f"the reconciliation names {len(dups)} concern(s) MORE THAN ONCE: "
                    f"{', '.join(dups[:6])} -- one row per concern id")
    missing = sorted(want - set(got))
    extra = sorted(set(got) - want)
    if missing:
        errs.append(f"the review did not reconcile {len(missing)} concern(s): "
                    f"{', '.join(missing[:6])}")
    if extra:
        errs.append(f"the reconciliation names {len(extra)} row(s) that are not concerns: "
                    f"{', '.join(extra[:6])}")
    by_id = {str(x.get("id")): x for x in (fj.get("findings") or []) if isinstance(x, dict)}
    for row in got_rows:
        cid = str(row.get("id") or "")
        status = str(row.get("status") or "").strip()
        if status not in ("finding", "already-addressed", "manual", "not-applicable"):
            errs.append(f"reconciliation row {cid!r}: status {status!r} is not one of finding/"
                        f"already-addressed/manual/not-applicable")
            continue
        fid = str(row.get("finding") or "").strip()
        if status == "finding":
            if not fid or fid not in by_id:
                errs.append(f"reconciliation row {cid!r} claims a finding but names none that "
                            f"exists in {FINDINGS_REL} ({fid or 'no id'})")
            else:
                f = by_id[fid]
                if str(f.get("check") or "").upper() != "JF" \
                        or str(f.get("concern") or "") != cid:
                    errs.append(f"reconciliation row {cid!r}: finding {fid!r} is not the JF "
                                f"finding for this concern (check/concern mismatch)")
        elif status == "already-addressed" and not str(row.get("location") or "").strip():
            errs.append(f"reconciliation row {cid!r}: 'already-addressed' needs the base/ "
                        f"location")
        elif status in ("manual", "not-applicable") and not str(row.get("rationale") or "").strip():
            errs.append(f"reconciliation row {cid!r}: {status!r} needs a rationale")
    return errs


def postcheck_concerns(ctx: Ctx, rec: dict):
    """Modes 3-4: the scoped ledger AND the finding list it produces."""
    sb = ctx.sandbox_of(rec)
    errs, warns = [], []
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "concerns", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    data = journal_ledger_problems(ctx, sb, errs, warns)
    errs.extend(original_submission_staging_problems(ctx, sb))
    rows = [r for r in (data.get("concerns") or []) if isinstance(r, dict)]
    must_fix = {str(r.get("id")) for r in rows
                if str(r.get("disposition")) in ("to-fix", "manual")}
    manual = {str(r.get("id")) for r in rows if str(r.get("disposition")) == "manual"}
    fj = read_json(sb / FINDINGS_REL, revive=False, lenient=True)
    if not isinstance(fj, dict):
        errs.append(f"{FINDINGS_REL} is missing/unparsable: the single revision session consumes "
                    f"it, and a scoped revision has no other finding source")
    else:
        findings = [f for f in (fj.get("findings") or []) if isinstance(f, dict)]
        by_concern = {}
        for f in findings:
            check = str(f.get("check") or "").strip().upper()
            concern = str(f.get("concern") or "").strip()
            if check != "JF":
                errs.append(f"finding {f.get('id')!r} has check {check!r}: a scoped revision "
                            f"carries ONLY the reviewers' concerns (check JF); an unrelated "
                            f"finding would license an unrelated edit")
            if not concern:
                errs.append(f"finding {f.get('id')!r} names no concern id")
            elif concern in by_concern:
                errs.append(f"concern {concern!r} has more than one finding")
            by_concern[concern] = f
            if not str(f.get("evidence") or "").strip():
                errs.append(f"finding {f.get('id')!r} has no evidence (quote the reviewer)")
            if not str(f.get("location") or "").strip():
                errs.append(f"finding {f.get('id')!r} has no location")
            status = str(f.get("status") or "").strip()
            want = "unresolvable" if concern in manual else "resolvable"
            if status not in ("resolvable", "unresolvable"):
                errs.append(f"finding {f.get('id')!r}: status {status!r} must be resolvable or "
                            f"unresolvable")
            elif status != want:
                errs.append(f"finding {f.get('id')!r}: status {status!r} does not match its "
                            f"ledger disposition (expected {want!r})")
        missing = sorted(must_fix - set(by_concern))
        extra = sorted(set(by_concern) - must_fix)
        if missing:
            errs.append(f"{len(missing)} concern(s) need an action but have no finding: "
                        f"{', '.join(missing[:6])}")
        if extra:
            errs.append(f"{len(extra)} finding(s) do not match a to-fix/manual concern: "
                        f"{', '.join(extra[:6])}")
        if not (sb / REVIEW_DIR / "artifacts" / "JF_concerns.md").is_file():
            errs.append(f"{ARTIFACTS_REL}/JF_concerns.md is missing")
        if not (sb / REVIEW_DIR / "findings.md").is_file():
            warns.append(f"{REVIEW_DIR}/findings.md is missing (the human-readable list)")
    if data:
        rec["concerns"] = {"count": len(rows), "to_fix": len(must_fix),
                           "manual": len(manual), "files": rec.get("feedback_files") or []}
    _check_pristine_copy(ctx, rec, pristine_dirname(sb), errs)
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


def postcheck_response(ctx: Ctx, rec: dict):
    """Modes 2-4: the letter covers every concern and cites the package truthfully."""
    sb = ctx.sandbox_of(rec)
    r = int(rec.get("round") or 1)
    errs, warns = [], []
    # The letter session receives the reviewer-visible manuscript beside the
    # letter; like every other journal stage it must not edit, drop or add it.
    errs.extend(original_submission_staging_problems(ctx, sb))
    marker = marker_json(sb, rec["kind"])
    _marker_checks(rec, marker, "response", errs, warns, sb=sb)
    errs.extend(structured_output_problems(ctx, rec))
    warns.extend(inherited_structured_output_notes(ctx, rec))
    target = sb / "target"
    src_rec = ctx.run(rid_concerns(r)) or ctx.run(rid_feedback(r))
    if src_rec is None:
        errs.append("the concern ledger's sandbox is missing (no concerns/feedback run in this "
                    "round): the letter cannot be verified against the concerns")
        src = None
    else:
        src = ctx.sandbox_of(src_rec)
    ledger_rows = {str(row.get("id")): row
                   for row in (journal_concern_rows(src) if src else [])}
    md = sb / JOURNAL_RESPONSE_MD_REL
    letter = ""
    if not md.is_file():
        errs.append(f"{JOURNAL_RESPONSE_MD_REL} is missing: the response to reviewers is the "
                    f"deliverable of this mode")
    else:
        letter = md.read_text(encoding="utf-8", errors="replace")
    data = read_json(sb / JOURNAL_RESPONSE_MAP_REL, revive=False, lenient=True)
    if not isinstance(data, dict):
        errs.append(f"{JOURNAL_RESPONSE_MAP_REL} is missing/unparsable (the letter's "
                    f"machine-readable map)")
        errs.extend(input_mismatches(ctx, rec))
        return (not errs), errs, warns, None
    rows = [x for x in (data.get("rows") or []) if isinstance(x, dict)]
    got = [str(x.get("id") or "") for x in rows]
    want = list(ledger_rows)
    if sorted(got) != sorted(want):
        missing = sorted(set(want) - set(got))
        extra = sorted(set(got) - set(want))
        errs.append(f"{JOURNAL_RESPONSE_MAP_REL} covers {len(got)} concern(s), the ledger has "
                    f"{len(want)}"
                    + (f"; missing: {', '.join(missing[:5])}" if missing else "")
                    + (f"; extra: {', '.join(extra[:5])}" if extra else ""))
    for row in rows:
        cid = str(row.get("id") or "")
        status = str(row.get("status") or "").strip()
        response = str(row.get("response") or "").strip()
        if status not in ("addressed", "partially-addressed", "already-addressed", "planned",
                          "not-applicable"):
            errs.append(f"response row {cid!r}: status {status!r} is not one of addressed/"
                        f"partially-addressed/already-addressed/planned/not-applicable")
        if not response:
            errs.append(f"response row {cid!r}: the response sentence is empty")
        changes = [c for c in (row.get("changes") or []) if isinstance(c, dict)]
        new_data = [str(x) for x in (row.get("new_data") or []) if str(x).strip()]
        for c in changes:
            f = str(c.get("file") or "").strip()
            if not f:
                errs.append(f"response row {cid!r}: a change entry names no file")
            elif not submit_code_of(ctx) and is_code_rel(f):
                errs.append(f"response row {cid!r}: change file {f!r} points into {CODE_DIR}/, "
                            f"which is never submitted (the analysis code is not part of the "
                            f"submission): cite a submission document, or describe the code "
                            f"change in the response text instead")
            elif (is_evidence_rel(f) or _is_aux_doc(Path(f).name)
                  or is_bookkeeping_name(Path(f).name)
                  or "work" in Path(f).parts[:-1]):
                errs.append(f"response row {cid!r}: change file {f!r} is not a submission "
                            f"document (bookkeeping/auxiliary/evidence files never ship)")
            elif is_non_submitted_readme_name(Path(f).name):
                errs.append(f"response row {cid!r}: change file {f!r} is a README*.md/"
                            f"README*.txt file, which is never submitted (the author's own "
                            f"documentation): cite a submission document, or describe the change "
                            f"in the response text instead")
            elif not (target / f).exists():
                errs.append(f"response row {cid!r}: change file {f!r} does not exist in the "
                            f"package -- the letter must not cite a file the revision does not "
                            f"carry")
        for f in new_data:
            if not submit_code_of(ctx) and is_code_rel(f):
                errs.append(f"response row {cid!r}: new-data file {f!r} points into {CODE_DIR}/, "
                            f"which is never submitted (the analysis code is not part of the "
                            f"submission): cite a submission document, or describe the code "
                            f"change in the response text instead")
            elif is_evidence_rel(f) or is_bookkeeping_name(Path(f).name) \
                    or "work" in Path(f).parts[:-1]:
                errs.append(f"response row {cid!r}: new-data file {f!r} is not a submission "
                            f"document (bookkeeping/evidence files never ship)")
            elif is_non_submitted_readme_name(Path(f).name):
                errs.append(f"response row {cid!r}: new-data file {f!r} is a README*.md/"
                            f"README*.txt file, which is never submitted (the author's own "
                            f"documentation): cite a submission document, or describe the change "
                            f"in the response text instead")
            elif not (target / f).exists():
                errs.append(f"response row {cid!r}: new-data file {f!r} does not exist in the "
                            f"package")
        src_row = ledger_rows.get(cid) or {}
        if status == "already-addressed" \
                and str(src_row.get("disposition") or "") != "already-addressed":
            errs.append(f"response row {cid!r}: status 'already-addressed' is only valid when the "
                        f"concern ledger marks this concern already-addressed (it says "
                        f"{str(src_row.get('disposition') or 'nothing')!r})")
        if status in ("addressed", "partially-addressed") and not changes and not new_data:
            errs.append(f"response row {cid!r}: status {status!r} claims work done but cites no "
                        f"change and no new data file")
        if status == "planned" and (changes or new_data):
            errs.append(f"response row {cid!r}: status 'planned' must not list completed "
                        f"changes/new data")
        if status in ("addressed", "partially-addressed") \
                and str(src_row.get("action") or "") == "new-experiment" and not new_data:
            errs.append(f"response row {cid!r}: the concern needs a new experiment; an "
                        f"'addressed' answer must cite the new data file(s)")
        if cid and letter and not _finding_id_mentioned(str(cid), letter):
            errs.append(f"response letter does not mention concern {cid!r}")
    # Like every sibling postcheck: the response session must not rewrite the
    # read-only package copy its letter is verified against (target/), or the
    # change citations can "exist" in a package that was never checked.
    errs.extend(input_mismatches(ctx, rec))
    return (not errs), errs, warns, None


def _scope_tree_files(root: Path) -> dict:
    """{exact relative path: (rel, sha256)} of a package's submission files.

    The key is the EXACT path, not `_doc_key`: two distinct documents that
    differ by a trailing single letter (`appendix-a.docx` / `appendix-b.docx`)
    both reduce to `appendix.docx`, and the old dict let the second overwrite
    the first in `want`/`got` -- the guard then missed a dropped sibling and
    compared one document's digest against another's. A version-token rename is
    paired later, only when the stripped key is unambiguous on both sides.
    """
    out = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("~$") or _is_aux_doc(p.name):
            continue
        rel = p.relative_to(root).as_posix()
        if is_evidence_rel(rel):
            continue
        if "work" in rel.split("/")[:-1] or is_bookkeeping_name(p.name):
            continue
        try:
            out[rel] = (rel, sha256_file(p))
        except OSError:
            continue
    return out


def scoped_scope_problems(ctx: Ctx, sb: Path, rev: Path, pipeline_changed=()) -> list:
    """The major/minor scope guard: only concern-driven edits are allowed.

    File-level and mechanical: an added or deleted file is an error; a modified
    file must be named in the package's revision ledger (which `postcheck_revise`
    requires to name every frozen finding id). The prompt asks for hunk-level
    discipline; this is the enforceable floor.

    `pipeline_changed` names the files the ORCHESTRATOR's own repairs touched
    before this check ran (the PKG-2 removal of a dangling reference, which is a
    submission-surface rule and not a concern-driven edit): those are exempt --
    the session never made them and cannot name them in its ledger -- and the
    exemption is reported by the caller.
    """
    errs = []
    pipeline_changed = {str(p) for p in (pipeline_changed or ())}
    base = sb / "base"
    if not base.is_dir() or not rev.is_dir():
        return errs
    want, got = _scope_tree_files(base), _scope_tree_files(rev)
    ledger_text = ""
    lp = rev / "revision_report.json"
    if lp.is_file():
        try:
            ledger_text = lp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ledger_text = ""
    added = sorted(set(got) - set(want))
    dropped = sorted(set(want) - set(got))
    # A version-token rename (`main-4f3a9c1.docx` -> `main-9b2c7e4.docx`) is
    # the SAME document. Pair it by the stripped key ONLY when exactly one
    # dropped and one added path share that key; a collision means two real
    # documents (or a genuine drop + add) and the exact-path verdict stands.
    by_key_want, by_key_got = {}, {}
    for rel in dropped:
        by_key_want.setdefault(_doc_key(rel), []).append(rel)
    for rel in added:
        by_key_got.setdefault(_doc_key(rel), []).append(rel)
    renamed = []
    for key, olds in by_key_want.items():
        news = by_key_got.get(key) or []
        if len(olds) == 1 and len(news) == 1:
            renamed.append((olds[0], news[0]))
            dropped.remove(olds[0])
            added.remove(news[0])
    for rel in added:
        if is_author_to_complete_readme_name(Path(rel).name):
            # The hand-off README is the mode's own surface, not a reviewer-
            # requested manuscript document: a concern-scoped revision may
            # create it (or replace a previous round's copy) without a ledger row.
            continue
        errs.append(f"scoped revision added {rel!r}: a major/minor revision may not add a "
                    f"document (the reviewers asked for no new file)")
    for rel in dropped:
        if is_author_to_complete_readme_name(Path(rel).name):
            # Items resolved: the README is deleted, and that is the goal.
            continue
        errs.append(f"scoped revision dropped {rel!r}: a major/minor revision may not remove a "
                    f"document; restore it")
    changed = [(rel, rel) for rel in sorted(set(want) & set(got))
               if want[rel][1] != got[rel][1]]
    changed += [(old, new) for old, new in renamed if want[old][1] != got[new][1]]
    for _old_rel, rel in sorted(changed, key=lambda pair: pair[1]):
        if is_author_to_complete_readme_name(Path(rel).name):
            continue
        if rel in pipeline_changed:
            continue
        if rel not in ledger_text and Path(rel).name not in ledger_text:
            errs.append(f"scoped revision changed {rel!r} but the ledger names neither the file "
                        f"nor its basename: every edit must trace to a reviewer concern")
    return errs


POSTCHECK_HANDLERS.update({
    "feedback": postcheck_feedback,
    "concerns": postcheck_concerns,
    "response": postcheck_response,
})
REBUILD_HANDLERS.update({
    "feedback": lambda ctx, rec: materialize_feedback(ctx, int(rec["round"])),
    "concerns": lambda ctx, rec: materialize_concerns(ctx, int(rec["round"])),
    "response": lambda ctx, rec: materialize_response(ctx, int(rec["round"])),
})


def journal_final_target(ctx: Ctx) -> tuple:
    """(the package the submission is built from, a label for the prompt)."""
    mode = journal_mode_of(ctx)
    if journal_is_scoped(ctx):
        rid = rid_for_fresh(1, revise_vid(1))
        rec = ctx.run(rid)
        if rec is None or rec.get("status") != "done":
            die(f"the {mode} revision has no finished revision run ({rid} is "
                f"{(rec or {}).get('status', 'missing')}): finish the round before publishing a "
                f"submission package.")
        # Prefer the published winner under --root: the run's sandbox is scratch
        # once the round is complete, and `prune --yes` deletes it, so a later
        # `run` that re-assembles the submission package must read the winner.
        rrec = ctx.round_get(1) or {}
        win_rel = str(rrec.get("winner_dir") or "")
        if win_rel and (ctx.root / win_rel).is_dir():
            return ctx.root / win_rel, f"the {mode} revision"
        sb = ctx.sandbox_of(rec)
        return sb / REVISED_DIR, f"the {mode} revision"
    pins = ctx.state.get("pinned") or []
    if pins:
        pin = pins[-1]
        return pinned_docs_dir(ctx, pin), f"the pinned champion {pin.get('id')}"
    return ctx.pristine, "the original (no round was pinned)"


def journal_final_version_id(ctx: Ctx) -> str:
    """The round-version id whose tracked changes belong to the submission.

    The scoped revision is `a2`; for modes 1-2 it is the pinned champion's own
    version (an `a1` champion has no redline -- the base did not change -- so
    nothing is copied). Empty when it cannot be resolved.
    """
    if journal_is_scoped(ctx):
        # The redline DIRECTORY is named for the round-version pair
        # (`redlines/r1_a2/...`), not for the run id (`r1_a2_revise`).
        return f"r{int(ctx.rounds_count())}_{revise_vid(1)}"
    pins = ctx.state.get("pinned") or []
    return str(pins[-1].get("id") or "") if pins else ""


def publish_journal_submission(ctx: Ctx, target: Path, label: str,
                               response_dir: Path = None) -> Path:
    """Assemble the JOURNAL SUBMISSION: the package minus the non-submitted areas.

    `raw_data/` (an INPUT: evidence) is never a submitted document, so the
    submission copy strips it (and the pipeline's own bookkeeping and revision
    auxiliaries) and includes the response-to-reviewers letter when the mode
    requires one. The analysis-code area `code/` is stripped with it -- it is
    revision content, but not part of the submission -- unless the recorded
    `submit_code` policy is `on` (see `submit_code_of`), and the author's own
    `README*.md` / `README*.txt` files are stripped unconditionally (they are
    the author's documentation, never manuscript content). The manifest records
    exactly what shipped, including what was dropped and why.
    """
    mode = journal_mode_of(ctx)
    dst = ctx.root / JOURNAL_SUBMISSION_DIR
    if dst.exists():
        rmtree_force(dst)
    dst.mkdir(parents=True, exist_ok=True)
    # WHAT THE OPERATOR DECLARES AS SUBMITTED (2026-10-15): read the package's own
    # README BEFORE the copy, because that file is itself stripped as non-submitted
    # below. It may state the submitted set as a glob ("Only files whose names match
    # `cnb-*-[0-9a-f]{7}.@(docx|pdf)` will be submitted ... Submitted files must
    # not refer to any non-submitted files"). The assembly copy is what ships, so it
    # is narrowed to that set when the declaration is plausible -- otherwise
    # `journal_submission/` would carry `.tex`/`.bib` sources and figure assets the
    # journal never receives, and the PKG-2 scan below would treat a reference into
    # them as resolvable. A declaration that matches nothing is IGNORED with a
    # recorded reason, and everything dropped is listed in the manifest. The
    # pipeline-ADDED submission documents (the response letter, the marked-up
    # copies) are placed AFTER this filter and are never dropped by it.
    decl = declared_submission_set(target)
    dropped_by_declaration = []
    copy_into(target, dst, exclude_top=("work",), skip_aux=True,
              strip_bookkeeping=True, root=ctx.root)
    include_code = submit_code_of(ctx)
    non_submitted = tuple(EVIDENCE_DIRNAMES) + (() if include_code else (CODE_DIR,))
    for name in non_submitted:
        if (dst / name).exists():
            rmtree_force(dst / name)
    if decl.get("declared"):
        keep = set(decl.get("files") or [])
        for q in sorted(dst.rglob("*")):
            if not q.is_file():
                continue
            rel = q.relative_to(dst).as_posix()
            if rel in keep:
                continue
            dropped_by_declaration.append(rel)
            q.unlink()
    response_files = []
    if response_dir is not None:
        for rel in (JOURNAL_RESPONSE_MD_REL, JOURNAL_RESPONSE_MAP_REL):
            src = response_dir / rel
            if src.is_file():
                out = dst / Path(rel).name
                shutil.copy2(src, out)
                response_files.append(out.name)
    if journal_needs_response(ctx) and not response_files:
        die(f"revision mode {mode!r} requires a response to reviewers, but the response stage "
            f"produced none: nothing was published to {dst.name}/. Run the response stage "
            f"(`run`) or retry it with `retry --run {rid_response(ctx.rounds_count())}`.")
    # Marked-up copies: a journal revision is usually submitted as the clean
    # manuscript PLUS the changes marked against what was submitted.
    # `run_redlines` writes them per version under redlines/<version>/from-original/.
    marked = []
    vid = journal_final_version_id(ctx)
    if vid:
        rd = ctx.root / REDLINE_DIRNAME / vid / "from-original"
        if rd.is_dir():
            out_dir = dst / "tracked_changes"
            for p in sorted(rd.iterdir()):
                if p.is_file():
                    # NEVER overwrite the clean document: the marked-up copies
                    # go in their own folder beside it.
                    out_dir.mkdir(exist_ok=True)
                    shutil.copy2(p, out_dir / p.name)
                    marked.append(f"tracked_changes/{p.name}")
    # The author's README files are never submitted (any depth), treated like
    # `code/` for submission purposes -- including a marked-up copy of one, so
    # this runs AFTER the tracked-change copies are placed. They stay in the
    # corpus/pin/winner; only this copy drops them, and the manifest names
    # every one.
    readme_dropped = []
    # A Word owner (lock) file is not a document and never part of a submission
    # (no submission pattern names one); the delivered folder carries only real
    # files, and the manifest names what was dropped.
    word_owner_dropped = []
    for q in sorted(dst.rglob("*")):
        if not q.is_file():
            continue
        if is_word_owner_name(q.name):
            word_owner_dropped.append(q.relative_to(dst).as_posix())
            q.unlink()
        elif is_non_submitted_readme_name(q.name):
            readme_dropped.append(q.relative_to(dst).as_posix())
            q.unlink()
    # The generic non-shippable sweep also runs on the SUBMISSION COPY: a legacy
    # or base pin that predates the stage-side sweep must not hand a `.pyc`, a
    # `.DS_Store` or a `:Zone.Identifier` stub to the journal. This is a derived
    # copy (the pin keeps its judged bytes), so the sweep is legal here.
    non_shippable_dropped = strip_non_shippable_files_in_dir(dst).get("removed") or []
    # `name`, not `p.name`: `p` is the tracked-changes copy loop's variable
    # above, so the old generator raised UnboundLocalError whenever the guard
    # fired without any redline to copy (and otherwise named the last redline
    # file instead of the leaked area).
    left = sorted(name for name in non_submitted if (dst / name).exists())
    if left:
        die(f"the submission package still carries a NON-SUBMITTED area ({', '.join(left)}); "
            f"this is a pipeline bug -- report it before submitting anything.")
    # PKG-2: nothing that ships may point at what does not ship (AGENTS.md). The
    # areas THIS package lacks are exactly the ones a shipped file must not
    # refer into. The pointers are REMOVED from the shipped documents (the
    # sentence that carries one), and whatever the mechanical layer may not
    # touch -- a structural file, a sentence carrying a live citation field --
    # is reported as an author action; the assembly never fails on it.
    missing_areas = [name for name in EVIDENCE_DIRNAMES + (CODE_DIR,)
                     if not (dst / name).exists()]
    try:
        reference_strip = strip_dangling_references_in_dir(
            dst, missing_areas, "journal submission", warns=None,
            artifacts_dir=ctx.reports_dir,
            artifact_name="PKG2_journal_submission.json")
        dangling = reference_strip.get("remaining") or []
    except Exception as e:                                            # noqa: BLE001
        reference_strip = {"error": f"{type(e).__name__}: {e}"}
        dangling = non_submitted_reference_rows(dst, missing_areas)
    manifest = hash_manifest(dst)
    write_json_atomic(ctx.root / "journal_submission.json",
                      {"mode": mode,
                       "option": JOURNAL_MODES[mode]["option"],
                       "label": JOURNAL_MODES[mode]["label"],
                       "target": label,
                       "source_package": (target.relative_to(ctx.root).as_posix()
                                          if is_within(target, ctx.root) else str(target)),
                       "response_files": response_files,
                       "marked_changes": marked,
                       "raw_data_included": False,
                       "code_included": bool(include_code),
                       "readme_files_excluded": readme_dropped,
                       "word_owner_files_excluded": word_owner_dropped,
                       "non_shippable_files_excluded": non_shippable_dropped,
                       # The operator's own declaration (its README) and what it
                       # kept out of THIS copy.
                       "declared_submission_patterns": list(decl.get("patterns") or []),
                       "declared_submission_readme": decl.get("readme"),
                       "declared_submission_ignored_reason": decl.get("ignored_reason"),
                       "not_submitted_by_declaration": dropped_by_declaration,
                       "removed_dangling_references": [
                           {"file": f["file"], "sentences": f["removed"]}
                           for f in (reference_strip.get("files") or []) if f.get("removed")],
                       "removed_local_path_links": [
                           {"file": f["file"], "links": f["removed_links"]}
                           for f in (reference_strip.get("files") or [])
                           if f.get("removed_links")],
                       "non_submitted_references": dangling,
                       # PKG-3: names the submission carries NOWHERE. Reported,
                       # never removed (`dangling` above is the removal set).
                       "unresolvable_references": list(reference_strip.get("advisory") or []),
                       "manifest": manifest,
                       "created": utcnow()})
    if readme_dropped:
        print(f"[journal] {len(readme_dropped)} README*.md/README*.txt file(s) are NOT submitted "
              f"(the author's own documentation, treated like {CODE_DIR}/): "
              + ", ".join(f"`{r}`" for r in readme_dropped[:6])
              + (" …" if len(readme_dropped) > 6 else ""))
    if word_owner_dropped:
        print(f"[journal] {len(word_owner_dropped)} Word owner (lock) file(s) are NOT "
              f"submitted (a Word by-product, not a document): "
              + ", ".join(f"`{r}`" for r in word_owner_dropped[:6])
              + (" …" if len(word_owner_dropped) > 6 else ""))
    if dropped_by_declaration:
        print(f"[journal] {len(dropped_by_declaration)} carried file(s) are NOT submitted: the "
              f"package's own `{(decl.get('readme') or 'README')}` declares only "
              + " / ".join(f"`{p}`" for p in decl.get("patterns") or [])
              + f" (every one is listed in the manifest as `not_submitted_by_declaration`); e.g. "
              + ", ".join(f"`{r}`" for r in dropped_by_declaration[:6])
              + (" …" if len(dropped_by_declaration) > 6 else ""))
    elif decl.get("ignored_reason"):
        print(f"[journal] NOTE: the package's README declares a submission rule that was IGNORED "
              f"({decl['ignored_reason']}); the copy keeps the pipeline's own submission model.")
    if dangling:
        print(f"[journal] {len(dangling)} reference(s) in the to-be-submitted files point into "
              f"an area this submission does NOT carry and could NOT be removed mechanically "
              f"(PKG-2) -- the journal cannot resolve them; the author must point at shipped "
              f"content (or submit the area, when it is one that can ship -- see "
              f"`set-submit-code`):")
        for r in dangling[:6]:
            print(f"  - {r['file']} line {r['line']}: `{r['reference']}`")
        if len(dangling) > 6:
            print(f"  - … and {len(dangling) - 6} more (see journal_submission.json)")
    _removed_refs = reference_strip.get("removed") or 0
    if _removed_refs:
        print(f"[journal] {_removed_refs} dangling reference(s) were REMOVED from the "
              f"to-be-submitted document(s) (a to-be-submitted file may not point at what the "
              f"submission does not carry); the removed sentences are recorded verbatim in "
              f"journal_submission.json:")
        for f in (reference_strip.get("files") or [])[:6]:
            if f.get("removed"):
                print(f"  - {f['file']}: {len(f['removed'])} sentence(s), e.g. "
                      f"`{str(f['removed'][0])[:120]}`")
    _removed_links = reference_strip.get("removed_links") or 0
    if _removed_links:
        print(f"[journal] {_removed_links} local-path link(s) (an attached Word template "
              f"pointing at somebody's own machine) were REMOVED from the submitted part(s); "
              f"the removed links are recorded in journal_submission.json:")
        for f in (reference_strip.get("files") or [])[:6]:
            for s in (f.get("removed_links") or [])[:2]:
                print(f"  - {f['file']}: {str(s)[:140]}")
    _advisory = reference_strip.get("advisory") or []
    if _advisory:
        print(f"[journal] {len(_advisory)} reference(s) name a file the package carries NOWHERE "
              f"(PKG-3) -- reported for the author, never removed (recorded in "
              f"journal_submission.json -> unresolvable_references):")
        for r in _advisory[:4]:
            print(f"  - {r.get('file')} line {r.get('line')}: `{r.get('reference')}`")
    return dst


def drive_journal_finalize(ctx: Ctx, *, cmd, timeout: int, jobs: int, retries: int,
                           manual: bool, nowait: bool, poll: int,
                           retry_backoff: int = 0, retry_backoff_max: int = 0) -> tuple:
    """The post-round journal step: the response letter (when required) + the
    submission package."""
    r = max(1, ctx.rounds_count())
    target, label = journal_final_target(ctx)
    if not target.is_dir():
        die(f"the journal finalization has no package to publish ({target} does not exist); "
            f"finish the round first")
    response_dir = None
    if journal_needs_response(ctx):
        rid = rid_response(r)
        rec = ctx.run(rid)
        done = bool(rec and rec.get("status") == "done"
                    and (ctx.sandbox_of(rec) / JOURNAL_RESPONSE_MD_REL).is_file())
        if not done:
            materialize_response(ctx, r, target=target, target_label=label)
            ph = {"cmd": cmd, "timeout": timeout, "jobs": jobs, "retries": retries,
                  "manual": manual, "nowait": nowait, "poll": poll,
                  "retry_backoff": retry_backoff, "retry_backoff_max": retry_backoff_max}
            ok, paused = run_phase(ctx, [rid], label="journal response", **ph)
            if not ok:
                return False, paused
        rec = ctx.run(rid) or {}
        response_dir = ctx.sandbox_of(rec)
    dst = publish_journal_submission(ctx, target, label, response_dir=response_dir)
    ctx.state.setdefault("journal", {})
    ctx.state["journal"].update({"mode": journal_mode_of(ctx),
                                 "submission_dir": dst.relative_to(ctx.root).as_posix(),
                                 "response": bool(response_dir),
                                 "published_at": utcnow()})
    ctx.save_state()
    print(f"[run] journal submission assembled: {dst} "
          f"({len((hash_manifest(dst) or {}).get('files') or {})} file(s); raw_data/ excluded"
          + ("" if submit_code_of(ctx) else "; code/ excluded")
          + (f"; response letter included ({', '.join(sorted(p.name for p in dst.iterdir() if p.name.startswith('RESPONSE') or p.name == 'response_map.json'))})" if response_dir else "; no response letter (transfer mode)")
          + ")")
    return True, False


def postcheck(ctx: Ctx, rec: dict, source: str = "postcheck") -> bool:
    """Re-verify one attempt's deliverables and record its outcome.

    `source` names HOW the attempt was evaluated (an agent session, a re-check of
    a marker that was already on disk, an adoption, a manual paste) and travels
    into the attempt history, because "attempt 2" means something different when
    no second agent ran.
    """
    kind = rec["kind"]
    # ADOPT a completion signal that names this run but was written one
    # directory down (an `audit/_pipeline_done.json`, a judge sheet inside
    # `judge_review/`), BEFORE the handler reads it: the alternative is failing
    # an attempt whose work is complete on the file's ADDRESS, and paying a
    # whole rebuilt session for it. A stray signal that names another run or
    # stage is not touched -- the handler's own error names it instead.
    #
    # The same rule covers the stage's REQUIRED bookkeeping deliverables (a
    # reviser's `revision_report.json` written into the sandbox root instead of
    # `revised/`): adopt the file the session actually wrote, never author one.
    stray_notes = rescue_misplaced_deliverable(ctx, rec) + relocate_stray_signal(ctx, rec)
    handler = POSTCHECK_HANDLERS.get(kind)
    if handler is None:
        ok, errs, warns = False, [f"unknown run kind {kind!r}"], []
    else:
        try:
            ok, errs, warns, _ = handler(ctx, rec)
        except Exception as e:                                  # noqa: BLE001
            # An unexpected error while INSPECTING a run (a transient OSError on a
            # sandbox file, a malformed structure a handler did not anticipate) must
            # fail that RUN, not crash the orchestrator mid-round: the retry policy
            # rebuilds the sandbox and the operator keeps a resumable state.
            ok, errs, warns = False, [
                f"postcheck raised {type(e).__name__}: {e} "
                f"(treated as a failed attempt; the sandbox is rebuilt on retry)"], []
    warns = list(warns) + stray_notes
    rec["postcheck"] = {"ok": ok, "errors": errs, "warnings": warns, "checked_at": utcnow()}
    rec["status"] = "done" if ok else "failed"
    # A STOPPED session is resumable if its CLI printed a session id (see
    # resume_gate): capture it here, at the single place every attempt's verdict
    # passes through. A repair session's id is deliberately NOT captured -- it is
    # the repair's session, not the stage's.
    if kind != "a1" and not str(source).startswith("artifact-repair"):
        sid = capture_agent_session_id(ctx, rec)
        if sid:
            rec["agent_session_id"] = sid
    # EVERY attempt is recorded, not only the last one: `postcheck`/`last_error`
    # are overwritten by the next attempt, so without this history a run that
    # failed twice reported one failure (see `attempt_history_lines`).
    # A version-producing stage is TRACKED the moment it is accepted: the
    # marked-up copies (`<name>.tracking-<baseline>.<ext>`, or their
    # `<name>.logging-<baseline>.<ext>` fallback when the tool failed) are
    # written BESIDE the documents the stage just produced and mirrored under
    # <root>/tracking/. The pass is code-only and never fatal -- a failure is a
    # warning on this attempt, never a failed stage (see the DIFFERENCE
    # TRACKING section).
    if ok and kind in TRACKING_STAGE_KINDS:
        note = track_after_stage(ctx, rec)
        if note:
            warns = list(warns) + [note]
            rec["postcheck"]["warnings"] = warns
    if ok:
        vid = freshness_vid(rec)
        if vid:
            try:
                rec["corpus_digest"] = recompute_corpus_digest(ctx, rec["round"], vid)
                rec["content_fingerprint"] = corpus_content_fingerprint(ctx, rec["round"], vid)
            except OSError as e:
                # An UNREADABLE candidate file (permissions, a lock, a vanished
                # path) must fail THIS attempt with an actionable message, not
                # crash the orchestrator mid-round with a traceback: the retry
                # rebuilds the sandbox and the operator keeps a resumable state.
                # The failure is named after the cause, because the console
                # truncates these lines.
                ok, rec["status"] = False, "failed"
                errs = list(errs) + [
                    f"the candidate corpus cannot be read/hashed ({type(e).__name__}: "
                    f"{e.strerror or e}) -- the run is retried, and the sandbox is rebuilt from "
                    f"the hash-verified base copy"]
        if ok:
            rec["finished"] = utcnow()
            rec["last_error"] = None
        else:
            rec["postcheck"]["ok"] = False
            rec["postcheck"]["errors"] = errs
            rec["last_error"] = "; ".join(errs)[:600]
    else:
        rec["last_error"] = "; ".join(errs)[:600]
    # Record AFTER the digest verification: this line used to run first, so the
    # attempt history stored `"ok": true` for the very attempt the digest then
    # failed.
    if kind != "a1":
        record_attempt(ctx, rec, ok, errs, warns, source=source)
    ctx.log("postcheck", rec["id"], "ok" if ok else "failed")
    return ok


# =====================================================================
# THE SANDBOX SELF-CHECK (`selfcheck --sandbox <dir> --stage <kind>`)
#
# The prompts tell every session to run this BEFORE it writes the completion
# marker (see `selfcheck_block`): it applies the postcheck's OWN detectors to
# the sandbox and prints what the postcheck would reject, while the session's
# context is still live. It exists because the two failure families below cost a
# whole rebuilt attempt each on the 2026-09-23 root -- a review that rewrote
# OUTLINE.md's 185 rows one cell short (its dispositions landed in the `summary`
# column, so every row "had an EMPTY disposition cell") and an audit that wrote
# its marker into `audit/`. Both are paperwork problems a session can fix in a
# minute and neither was visible to the session that produced it.
#
# It is a PRE-FLIGHT, deliberately not a second verdict: the checks that need
# the root's own state (the pristine-copy digests, the input manifests, the
# judge's label set, the package's corpus rules) stay in the postcheck, and the
# self-check says so. Everything it prints comes from the same function the
# postcheck calls, so the two can never disagree.
# =====================================================================

SELFCHECK_STAGES = ("rewrite", "review", "probe", "audit", "revise", "integrate", "judge")

# --- the stage's own bookkeeping deliverables --------------------------------
# `required` FAILS an attempt when it is missing (the postcheck errors on it);
# `expected` is recorded as a warning. Two layers read this table: the rescue
# below (which moves a required file the session wrote one directory up into
# place) and the pre-flight, so a session learns about a missing or mis-filed
# deliverable while its context is still live. Manuscript documents are never in
# either list -- a rescue moves BOOKKEEPING only.
STAGE_DELIVERABLES = {
    "review": {"required": (FINDINGS_REL,),
               "expected": (FINDINGS_MD_REL, "review/round2/findings_extra.json",
                            VISUAL_ARTIFACT_REVIEW)},
    "probe": {"required": (PROBE_FINDINGS_REL, PROBE_COVERAGE_REL),
              "expected": (PROBE_FINDINGS_MD_REL,)},
    "audit": {"required": ("audit/audit.json",),
              "expected": ("audit/AUDIT.md", "audit/DISPOSITION_AUDIT.md",
                           "audit/PROBE_AUDIT.md")},
    "feedback": {"required": (JOURNAL_CONCERNS_JSON_REL,),
                 "expected": (JOURNAL_CONCERNS_MD_REL,)},
    "concerns": {"required": (JOURNAL_CONCERNS_JSON_REL,),
                 "expected": (JOURNAL_CONCERNS_MD_REL,)},
    "response": {"required": (JOURNAL_RESPONSE_MAP_REL,),
                 "expected": (JOURNAL_RESPONSE_MD_REL,)},
    "rewrite": {"required": (REWRITE_REPORT_REL,),
                "expected": (f"{REWRITTEN_DIR}/VISUAL_CHECK.md",
                             f"{REWRITTEN_DIR}/MANUAL_STEPS.md")},
    "revise": {"required": ("revised/revision_report.json",),
               "expected": (f"{REVISED_DIR}/REVISION_REPORT.md", f"{REVISED_DIR}/CHANGELOG.md",
                            f"{REVISED_DIR}/DIFF_LEDGER.md", f"{REVISED_DIR}/MANUAL_STEPS.md",
                            VISUAL_ARTIFACT_REVISED)},
    "integrate": {"required": (INTEGRATION_LEDGER_REL,),
                  "expected": (f"{INTEGRATED_DIR}/revision_report.json",
                               f"{INTEGRATED_DIR}/REVISION_REPORT.md",
                               f"{INTEGRATED_DIR}/CHANGELOG.md",
                               f"{INTEGRATED_DIR}/MANUAL_STEPS.md",
                               VISUAL_ARTIFACT_INTEGRATED)},
# A judge's sheet IS its completion signal, so it belongs to
    # `signal_search_dirs` (judge_review/) rather than to this rescue.
    "judge": {"required": (), "expected": ("judge_review/artifacts/VIS_visual.md",)},
}


def _prompt_rewrite_level(sb: Path) -> str:
    """The rewrite level THIS sandbox's prompt declares ("" when unreadable).

    The arm's level lives in the run record, not in the sandbox -- but the prompt
    states it verbatim ("=== THIS ARM'S LEVEL: STRUCTURAL ... ===" and "state the
    level on its own line, literally `Level: structural`"), so the session and
    its pre-flight can read it back and check the report against it.
    """
    try:
        text = (sb / PROMPT_FILE).read_text("utf-8", "replace")[:20000]
    except OSError:
        return ""
    m = re.search(r"THIS ARM'S LEVEL:\s*(structural|sentence)", text, re.IGNORECASE)
    return m.group(1).lower() if m else ""


def _usable_deliverable(p: Path) -> bool:
    """Is this file worth ADOPTING into its canonical path?

    Non-empty, and (for JSON) parseable: a truncated file moved into place would
    only turn a "missing" failure into a "malformed" one, and the rescue exists
    to preserve work, not to shuffle garbage.
    """
    try:
        if not p.is_file() or p.stat().st_size == 0:
            return False
    except OSError:
        return False
    if p.suffix.lower() == ".json":
        return read_json(p, revive=False, lenient=True) is not None
    return True


def rescue_misplaced_deliverable(ctx: Ctx, rec: dict) -> list:
    """Move a REQUIRED bookkeeping deliverable the session wrote one level up.

    The exact analogue of `relocate_stray_signal`, for the same failure family
    that cost the 2026-09-23 root a whole session: work that happened, filed at
    the wrong address. A reviser whose `revision_report.json` sits in the sandbox
    root (or in its own `work/` scratch) instead of `revised/` used to FAIL the
    attempt -- and a rebuilt attempt re-reads the whole corpus to write the file
    again.

    Deliberately narrow: only the names in `STAGE_DELIVERABLES[...]["required"]`,
    only from the sandbox root or the session's OWN `work/` scratch (never from a
    read-only input area: `base/`, `non_revised/`, `review/` for non-review
    stages, `audit/`, `self/`, `others/`, `target/`, `field/`), and
    never for a manuscript document -- a document belongs to the package's
    document set and is handled by the recovery layer, which knows the corpus.
    """
    kind = rec.get("kind")
    table = STAGE_DELIVERABLES.get(str(kind)) or {}
    sb = ctx.sandbox_of(rec)
    if not sb.is_dir():
        return []
    notes = []
    for rel in table.get("required", ()):
        target = sb / rel
        if str(rel) == SCORES_FILE or target.is_file():
            continue
        pkg = Path(rel).parent
        name = Path(rel).name
        # Where a session plausibly writes the file: the root, its own package's
        # work/ scratch, or the sandbox-level work/ (the rewrite/revise/integrate
        # layout's evidence directory).
        cands = [sb / name]
        if pkg != Path("."):
            cands.append(sb / pkg / "work" / name)
        cands.append(sb / "work" / name)
        src = next((c for c in cands if _usable_deliverable(c)), None)
        if src is None:
            continue
        src_rel = src.relative_to(sb).as_posix()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
        except OSError as e:                                     # noqa: BLE001
            notes.append(f"the `{name}` written to `{src_rel}` could not be moved to `{rel}` "
                         f"({type(e).__name__}: {e}); it will not be read from there")
            continue
        notes.append(f"the required `{rel}` was written to `{src_rel}` instead of `{rel}`; it is "
                     f"ADOPTED (moved into place) -- the prompts pin the deliverable's path")
        print(f"  [warn] {rec.get('id')}: {notes[-1]}")
    return notes


def sandbox_selfcheck(sb: Path, kind: str, run_id: str = "", r: int = 0) -> tuple:
    """(ok, errors, warnings) for the paperwork of one sandbox (read-only).

    `kind` is the run's stage; `run_id`/`r` are only used to CHECK the marker.
    Every check below is the postcheck's OWN detector (called, not re-implemented),
    so the pre-flight can never disagree with the verdict it previews.
    """
    kind = str(kind or "")
    errs, warns = [], []
    if kind not in SELFCHECK_STAGES:
        return False, [f"unknown stage {kind!r} (known: {', '.join(SELFCHECK_STAGES)})"], []
    # `round` stays None when the caller did not supply one: the marker's own
    # round is then not checked (a wrong ROUND is a detail the operator can see
    # in the marker, and reporting a mismatch against a round nobody claimed
    # would be noise).
    rec = {"id": run_id, "kind": kind, "round": (int(r) if r else None)}
    if not sb.is_dir():
        return False, [f"the sandbox {sb} does not exist"], []
    # 1. the completion signal: it must be at the ROOT and it must name THIS run
    marker = marker_json(sb, kind)
    _marker_checks(rec, marker, kind, errs, warns, sb=sb)
    # 2. the stage's own deliverables: the REQUIRED ones fail an attempt in the
    #    postcheck, the EXPECTED ones are warnings there too.
    table = STAGE_DELIVERABLES.get(kind) or {}
    for rel in table.get("required", ()):
        if not (sb / rel).is_file():
            errs.append(f"{rel} is missing (the postcheck fails an attempt without it)")
    for rel in table.get("expected", ()):
        if not (sb / rel).is_file():
            warns.append(f"{rel} is missing (reported by the postcheck as a warning)")
    # 3. any structured output that EXISTS must parse (the postcheck's own parse
    #    gate: a truncated sheet must never be reported as complete).
    for rel, p in structured_output_files(sb, {"kind": kind}):
        problem = _structured_problem_for(rel, p)
        if problem:
            errs.append(problem)
    # 4. the stage-specific contracts, each through the postcheck's own helper
    if kind == "review":
        # The session prompt is read TWICE in this block: by the review-contract
        # branch for its scope, and by the discovery-contract check at the end,
        # which runs whether or not findings.json parsed. Initialise it here --
        # the branch that reads the file sits inside an `else`, so a missing or
        # broken findings.json (exactly the pre-flight state this selfcheck
        # exists to diagnose) raised NameError instead of reporting the missing
        # deliverable.
        _prompt = ""
        fj = read_json(sb / FINDINGS_REL, revive=False, lenient=True)
        if not isinstance(fj, dict):
            errs.append(f"{FINDINGS_REL} is missing or does not parse as a JSON object "
                        f"(it is the deliverable Phase 2 consumes)")
        elif not isinstance(fj.get("findings"), list):
            errs.append(f"{FINDINGS_REL} has no 'findings' list")
        else:
            # Read THIS session's prompt FIRST: it states the round's review scope,
            # and the pre-flight must preview the verdict the postcheck (which
            # derives the scope from the plan) will reach. With the default
            # `scope="full"` a formatting-writing session's selfcheck demanded the
            # content rounds' parity artifacts its prompt scopes out -- the
            # pre-flight disagreeing with the verdict it previews.
            try:
                _prompt = (sb / PROMPT_FILE).read_text(encoding="utf-8", errors="replace")
            except OSError:
                _prompt = ""
            _scope = ("formatting-writing"
                      if "FORMATTING AND WRITING ONLY" in _prompt else "full")
            # A SPLIT round's two halves owe different artifacts. The postcheck
            # reads the plan; the selfcheck usually runs in its own process with no
            # ctx, so it reads the split mode its own prompt states and the half its
            # own sandbox name states (`r<r>_review_b`), and the two verdicts agree.
            _split = "off"
            if "SPLIT REVIEW" in _prompt:
                _split = ("aspects"
                          if ("PACKAGING/compliance" in _prompt
                              or "CONTENT/scientific" in _prompt) else "phases")
            # `check_review_contract` needs no pipeline state (it verifies the
            # corpus pointer, the coverage table and the M1b long-form gate), so
            # the session gets the whole contract, not a summary of it.
            check_review_contract(None, sb, fj, errs, warns, scope=_scope, split=_split)
        # The discovery round's D0-D5 contract, unless THIS session's own prompt
        # says the phase is not its job (the formatting-writing scope, or the
        # mechanical half of a split review).
        _no_discovery = ("FORMATTING AND WRITING ONLY" in _prompt
                         or ("SPLIT REVIEW" in _prompt
                             and "YOUR SCOPE (B)" not in _prompt))
        if not _no_discovery:
            _derrs, _dwarns = discovery_contract_problems(sb)
            errs.extend(f"discovery round: {d}" for d in _derrs)
            warns.extend(f"discovery round: {d}" for d in _dwarns)
        report = artifact_quality_report(sb / REVIEW_DIR)
        for rel, problems in sorted(report.items()):
            for p in problems:
                errs.append(f"decision artifact {rel}: {p}")
        for rel, notes in sorted(artifact_quality_notes(sb / REVIEW_DIR).items()):
            for n in notes:
                warns.append(f"decision artifact {rel}: {n}")
        if word_docs_present([sb / "base"]):
            check_visual_artifact(sb / VISUAL_ARTIFACT_REVIEW,
                                  f"the visual-inspection record {VISUAL_ARTIFACT_REVIEW}",
                                  errs, warns, sandbox=sb, render_roots=[sb / REVIEW_DIR])
    elif kind == "probe":
        # The probe session's own detectors, verbatim: the checked inventory and
        # the finding shapes AND the reproduction pass, so a computation that
        # does not reproduce is caught while the session is still live.
        perrs, pwarns, findings = _probe_contract_problems(sb)
        errs.extend(perrs)
        warns.extend(pwarns)
        if not (sb / PROBE_COVERAGE_REL).is_file():
            errs.append(f"{PROBE_COVERAGE_REL} is missing: the areas examined, the counts and "
                        f"the round's honest limits are part of the deliverable")
        if findings:
            repro = probe_reproduction(sb, findings)
            for r in repro["results"]:
                if r["status"] == "mismatch":
                    errs.append(f"{PROBE_FINDINGS_REL} {r['row']}: the re-run of `{r['script']}` "
                                f"printed {r['produced']!r} where the finding declares "
                                f"{r['declared']!r} -- the declared computation does not "
                                f"reproduce")
                elif r["status"] in ("missing", "timeout", "failed", "empty"):
                    errs.append(f"{PROBE_FINDINGS_REL} {r['row']}: the verifier `{r['script']}` "
                                f"{'is missing' if r['status'] == 'missing' else r['status']}"
                                + (f" ({r['detail']})" if r["detail"] else ""))
    elif kind == "audit":
        aj = sb / "audit" / "audit.json"
        if not aj.is_file():
            errs.append("audit/audit.json is missing: the auditor's dispositions are the "
                        "deliverable the revisers consume")
        else:
            errs.extend(audit_artifact_problems(
                read_json(aj, revive=False, lenient=True),
                [str(f.get("id") or "").strip() for f in _frozen_review_findings(sb)
                 if str(f.get("id") or "").strip()]))
        if not (sb / "audit" / "AUDIT.md").is_file():
            warns.append("audit/AUDIT.md (the human-readable disposition record) is missing")
        errs.extend(probe_audit_problems(sb))
    elif kind in ("rewrite", "revise", "integrate"):
        pkg = output_dir_of(rec)
        d = sb / pkg
        if not (d.is_dir() and any(d.iterdir())):
            errs.append(f"{pkg}/ is empty: this stage's deliverable is the candidate package it "
                        f"writes there")
        if kind == "revise":
            # The ledger contract: one row per finding id the reviser had to
            # resolve. This is the check that failed every attempt of two real
            # revise sessions (their rows lived under a key the reader did not
            # know); it now runs BEFORE the marker too.
            frozen = findings_from_sandbox(sb, sandbox_audit_record(sb))
            ids = [str(f.get("id")).strip() for f in frozen
                   if isinstance(f.get("id"), str) and str(f.get("id")).strip()]
            total = len(ids) if (sb / FINDINGS_REL).exists() else None
            lerrs, lwarns = revision_ledger_problems(d, ids, total,
                                                     "revised/revision_report.json")
            errs.extend(lerrs)
            warns.extend(lwarns)
            # PRE-FLIGHT PARITY for the two postcheck families that failed the
            # neohet reviser: deliverable validation and the "no new finding-tier
            # family" regression. The postcheck runs both; a selfcheck that omits
            # them reported "the paperwork checks passed" on a package the
            # postcheck then rejected. The pre-flight applies the same detectors
            # to the same declared submitted set, so the two verdicts agree.
            mod = _format_module()
            if mod is not None:
                targets = _validation_targets(d)
                if targets and targets != [d]:
                    vrep = mod.validate_paths(targets, timeout=VALIDATE_TEX_TIMEOUT)
                    for row in vrep.get("results") or []:
                        if row.get("kind") == "docx" and row.get("ok") is False:
                            first = (row.get("errors") or [row.get("detail") or "invalid"])[0]
                            errs.append(f"VALIDATION: {Path(row['file']).name} is not a valid "
                                        f"DOCX: {first}")
                fpol = read_json(sb / "format_policy.json", revive=False, lenient=True)
                if (sb / "base").is_dir() and isinstance(fpol, dict):
                    rerrs, rwarns = scan_regression_problems(
                        None, [(sb / "base", "", ())], [(d, "", CORPUS_EXCLUDE_TOP)],
                        "revise", policy=fpol)
                    errs.extend(rerrs)
                    warns.extend(rwarns)
        if kind == "integrate":
            donors = [p.name for p in sorted((sb / "others").iterdir()) if p.is_dir()] \
                if (sb / "others").is_dir() else []
            led = integration_ledger_report(d, donors, expect_both_levels=False)
            if led["rows"] and led["missing_artifact"]:
                errs.append(f"integrate: {len(led['missing_artifact'])} ledger row(s) carry no "
                            f"`artifact` (a before/after pair for a small row, an outline diff "
                            f"for a large row) -- the row cannot be re-checked")
            if not led["rows"]:
                warns.append(f"{INTEGRATION_LEDGER_REL} could not be parsed as a table (the "
                             f"per-difference artifacts, the size classes and the finding-effect "
                             f"column cannot be checked)")
            # Contract: the round's frozen discovery list is reconciled by id --
            # a resolution cannot be lost between the revise arm and the
            # integrated package.
            seed_ids = ([str(f.get("id")) for f in
                         discovery_findings_of(sb / DISCOVERY_SEED_DIR)]
                        if (sb / DISCOVERY_SEED_DIR).is_dir() else [])
            errs.extend(discovery_ledger_reconciliation_problems(
                sb / INTEGRATION_LEDGER_REL, seed_ids))
        if kind == "rewrite":
            level = _prompt_rewrite_level(sb)
            if level and (sb / REWRITE_REPORT_REL).is_file():
                declared = None
                try:
                    declared = re.search(r"(?im)^\s*(?:[-*]\s*)?LEVEL\s*[:=]\s*"
                                         r"(structural|sentence)\b",
                                         (sb / REWRITE_REPORT_REL).read_text("utf-8",
                                                                              "replace")[:4000])
                except OSError:
                    declared = None
                if declared is None:
                    warns.append(f"rewrite: REWRITE_REPORT.md does not state the arm's level "
                                 f"({level!r}) on its own line (`Level: {level}`)")
                elif declared.group(1).lower() != level:
                    errs.append(f"rewrite: REWRITE_REPORT.md declares level "
                                f"{declared.group(1).lower()!r} but this arm is {level!r} -- the "
                                f"round stages one structural and one sentence-level arm so the "
                                f"pool has both kinds of difference")
        # W-12's language pass: one row per change plus one coverage row per step.
        lp = language_pass_report(d)
        if not lp["present"]:
            errs.append(f"{kind}: no work/R6_language.md -- the L1-L11 language pass is a "
                        f"required artifact of every package-producing stage: one row per change "
                        f"plus one coverage row per step (including the steps that changed "
                        f"nothing)")
        elif lp["missing"]:
            errs.append(f"{kind}: the language pass covers {11 - len(lp['missing'])}/11 steps; no "
                        f"coverage row for {', '.join(lp['missing'])} (a step with no row is an "
                        f"unaudited step)")
        visual = {REWRITTEN_DIR: VISUAL_ARTIFACT_REWRITTEN,
                  REVISED_DIR: VISUAL_ARTIFACT_REVISED,
                  INTEGRATED_DIR: VISUAL_ARTIFACT_INTEGRATED}.get(pkg)
        if visual and d.is_dir() and word_docs_present([d]):
            check_visual_artifact(sb / visual, f"the visual-inspection record {visual}",
                                  errs, warns, sandbox=sb, render_roots=[d])
    elif kind == "judge":
        sj = scores_json_of(sb, kind)
        jr = sb / "judge_review"
        if not (jr.is_dir() and any(p.is_file() for p in jr.rglob("*"))):
            errs.append("judge_review/ is missing or empty: the corpus inventory and the sweep "
                        "artifacts are required there")
        if sj is None:
            errs.append("scores.json is missing from the sandbox root or does not parse as a "
                        "JSON object")
        else:
            # The sheet's own schema, ledger arithmetic and coverage map, through
            # the postcheck's validator. The issued labels ARE the sandbox's
            # `field/` directories, and the session's opaque token is the sheet's
            # own target_id (the postcheck holds the real value); what this
            # reproduces exactly is everything the session can get wrong.
            labels = {p.name: p.name for p in sorted((sb / "field").iterdir())
                      if p.is_dir()} if (sb / "field").is_dir() else {}
            token = sj.get("target_id")
            jrec = {"id": run_id or sb.name, "kind": "judge",
                    "round": (int(r) if r else None), "label_map": labels,
                    "judge_target_token": token, "target_id": token,
                    "judge_index": sj.get("judge_index"),
                    "contract": JUDGE_CONTRACT_VERSION}
            verrs, vwarns = validate_judge_sheet(sj, jrec)
            errs.extend(verrs)
            warns.extend(vwarns)
            # Contract v5: the judge's OWN discovery pass (one disposed file per
            # side), reproduced from THIS sandbox so the session's pre-flight
            # reports exactly what the postcheck would reject.
            derrs, dwarns = judge_discovery_problems(sb, jrec)
            errs.extend(derrs)
            warns.extend(dwarns)
        if word_docs_present([sb / "target", sb / "field"]):
            check_visual_artifact(jr / "artifacts" / "VIS_visual.md",
                                  f"the visual-inspection record {VISUAL_ARTIFACT_JUDGE}",
                                  errs, warns, sandbox=sb, render_roots=[jr])
    return (not errs), errs, warns


def cmd_selfcheck(args) -> None:
    """`selfcheck`: print the postcheck's paperwork verdict for one sandbox."""
    sb = Path(args.sandbox).expanduser().resolve()
    ok, errs, warns = sandbox_selfcheck(sb, args.stage, args.run_id or sb.name,
                                        args.round or 0)
    print(f"SELF-CHECK  stage={args.stage}  sandbox={sb}")
    for w in warns:
        print(f"  [warn] {w}")
    for e in errs:
        print(f"  [FAIL] {e}")
    if ok:
        print(f"  [ok]   the paperwork checks passed: the postcheck's own detectors found "
              f"nothing to reject"
              + (" (content checks that need the pipeline root still run at postcheck time)"
                 if not warns else ""))
        raise SystemExit(0)
    print(f"  {len(errs)} problem(s): fix them, re-run this check, and write the completion "
          f"marker LAST (the postcheck reads the same files)")
    raise SystemExit(1)

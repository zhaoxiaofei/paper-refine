# This part carries NO module docstring on purpose: the loader executes every
# part in the paper_pipeline module's own globals, and a module-level string
# literal would REPLACE that module's `__doc__` with this file's text (the
# pre-existing parts made the same choice for the same reason).
#
# EXECUTION PROFILES and the TARGETED-REVIEW switch.
#
# Two operator-facing policies live here; both are recorded at `setup`, frozen
# into the root (rule 11) and never consulted from the maintained checkout.
#
# 1. `--execution-profile high|medium`
#
#    The pipeline was written for a frontier model with a very large context
#    window.  A medium model (a single-GPU 27B deployment, ~100k tokens or less)
#    does not fail on the manuscript: it fails on the INSTRUCTION PAYLOAD.  Every
#    session is handed ~115 KB of stage prompt before it reads one word of the
#    paper, and the same ~115 KB is re-sent on every step of an agent loop.  The
#    observed cost of a short manuscript was 1,589 model calls and 110.8M prompt
#    tokens (median call ~72k prompt tokens).
#
#    `high` (the default) is the pipeline exactly as it was: every rule is
#    inlined in every session, and `--execution-profile high` is byte-identical to
#    running without the flag at all.
#
#    `medium` keeps every rule but stops INLINING the elaborative ones.  Each
#    stage prompt carries the stage contract, the finding schema, the completion
#    marker and the capacity discipline, and the long rule sections it used to
#    paste are written once to `INSTRUCTIONS/PROFILE_RULES.md` in the session
#    sandbox and referenced.  The rules are not dropped, weakened or summarised:
#    the same bytes ship in the root, the prompt says they are mandatory and
#    authoritative, and a session consults a section with a bounded read when its
#    stage needs it.  The postchecks are unchanged, so coverage is unchanged --
#    the difference is where the instructions live, not what they demand.
#
# 2. `--targeted-review on|off` (and `--no-targeted-review`)
#
#    The round's TARGETED review (the M1-M36 / J1-J5 pass) and the
#    probe review (the cold, unanchored discovery pass) are independent
#    finding-generating roles.  `--no-targeted-review` runs the probe ALONE: the
#    probe's X-9xx rows become the round's frozen finding list, and the targeted
#    review's whole class is recorded as a NAMED GAP (rule 8) -- in the frozen
#    review view every downstream stage reads, in the audit and revision prompts,
#    in `state.json` and in the run's own record.  Nothing is silently zeroed: the
#    gap states which checks nobody ran.
#
# Terminology: the non-probe review is the TARGETED REVIEW.  Its on-disk names
# (`r<r>_review`, `targeted_review/`, the run kind `review`) are unchanged on purpose:
# they are part of every existing root's recorded identity and of the
# `--execution-profile high` byte-identity guarantee.

from __future__ import annotations

# ---------------------------------------------------------------------------
# Recorded policy names (see `p00_prelude.py` for the constants the CLI uses)
# ---------------------------------------------------------------------------

# The vocabulary lives in p00 (the CLI resolves its choices there); this module
# must not carry a second copy of it.
PROFILE_HIGH, PROFILE_MEDIUM = EXECUTION_PROFILES
PROFILE_INSTRUCTIONS_DIR = "INSTRUCTIONS"
PROFILE_RULES_REL = f"{PROFILE_INSTRUCTIONS_DIR}/PROFILE_RULES.md"

#: The sections `medium` pages out of a stage prompt, by the block they replace.
PROFILE_RULES_HEADER = """# PROFILE RULES — the execution profile `medium` of this pipeline run

This file is the MANDATORY, AUTHORITATIVE rule text for the session whose
prompt points at it.  The prompt carries your stage contract, your deliverable
and the completion marker; this file carries the long rule sections the prompt
used to paste inline.

READ POLICY (this is the point of the file — do not read it cover to cover):

  * Before you start, read the section your stage needs for the first item you
    work on, not all of them.
  * To find a section: `grep -n '^## ' INSTRUCTIONS/PROFILE_RULES.md`
  * To read one: `sed -n '<start>,<end>p' INSTRUCTIONS/PROFILE_RULES.md`, in
    slices of at most about 200 lines.
  * A section you never open still binds you where your stage's contract names
    it.  "I did not read that section" is not a defence for a deliverable your
    prompt requires.

Nothing here relaxes a postcheck.  Every artifact, coverage row and evidence
rule your prompt names is still required.
"""

#: The compact contract `medium` puts at the top of every stage prompt.
MEDIUM_PROFILE_CONTRACT = """=== EXECUTION PROFILE: medium — READ THIS FIRST ===

This run was set up for a model with a LIMITED context window.  The pipeline
therefore states the stage contract inline and pages the long rule sections to
`INSTRUCTIONS/PROFILE_RULES.md` (see the pointers below).  Working rules for
this profile — they are the same contract, restated for a small window:

  1. WORK IN BOUNDED STEPS. Read the passages you need, never the whole corpus
     "for context".  `grep -n` to locate, `sed -n` to read at most ~200 lines.
  2. WRITE INCREMENTALLY. Create each deliverable file as soon as you have its
     first row and append to it; do not hold the whole result until the end.
     A stage that runs out of window with nothing on disk has produced nothing.
  3. DO NOT RE-READ what you have already read or quoted: cite it from your own
     notes/artifacts.  Two identical reads are one wasted step.
  4. THE DELIVERABLES ARE THE STAGE. Your prompt names them and
     `_pipeline_done.json` in the sandbox ROOT is the last thing you write.
     A stage that does all its analysis but cannot close its deliverables has
     FAILED (this is the observed failure mode of limited-context models).
  5. THE PAGED RULES ARE BINDING. A pointer like
     `[PROFILE RULES — SECTION: see INSTRUCTIONS/PROFILE_RULES.md]` replaces
     rule text that this profile does not inline. Read the section your stage
     needs; it is authoritative and it is not optional.
  6. THE POSTCHECKS ARE UNCHANGED. Every artifact, coverage row and evidence
     rule still applies: this profile changes where the instructions live, not
     what they demand.

"""

#: One stage's prompt pointer, substituted for a paged rule section.
PROFILE_POINTER_TMPL = (
    "[PROFILE RULES — {section}: this rule section is NOT inlined by the "
    "`medium` execution profile. It is MANDATORY and it is authoritative. "
    "Read it in {rel} (section `{section}`) with `grep -n '^## '` then "
    "`sed -n`, in a slice of at most ~200 lines, before the work it governs.]")

#: The named gap a round records when `--no-targeted-review` skipped the
#: targeted review.  It is written into the frozen review view, so every
#: downstream session reads the same statement instead of an empty directory.
TARGETED_REVIEW_GAP = (
    "targeted review NOT RUN this round (`--no-targeted-review`): the round's "
    "general checklist pass (M1-M36/J1-J5 and the D0-D5 discovery round) was "
    "not performed, so every class it owns is UNREVIEWED here. The probe "
    "review's independent, generic pass is the only discovery source of this "
    "round; its coverage.md states what it actually examined.")

TARGETED_REVIEW_OFF_NOTE = """=== THIS ROUND HAS NO TARGETED REVIEW (operator policy) ===

`--no-targeted-review` was set at setup: the round's general checklist pass
(M1-M36 / J1-J5 and its D0-D5 discovery round) DID NOT RUN.  The frozen finding
list you were given is the PROBE review's independent, generic output (X-9xx
rows) and nothing else.

What that means for you:

  * The M1-M36 / J1-J5 classes are a RECORDED GAP this round, not a clean
    result. Nobody examined them. Do not treat their absence from the finding
    list as evidence that the corpus is clean, and do not report "no findings"
    for one of those classes.
  * Your mandate is unchanged in kind: dispose (audit) or resolve (revise, in
    a re-validation ledger row) every frozen X-9xx id you were given.
  * This gap is recorded in the run's state and in the frozen
    `targeted_review/findings.json` coverage table. It is not yours to close.
"""


# The run kind was renamed `review` -> `targeted_review` (2026-10). A root or a
# fixture that still records the old kind is READ under the new one, so every
# handler table, repair profile and self-check lookup keeps finding its stage;
# the recorded id and sandbox path are left alone (a legacy root keeps pointing
# at the sandboxes it already has).
LEGACY_RUN_KINDS = {"review": "targeted_review", "review_b": "targeted_review_b"}


def normalize_run_kind(kind) -> str:
    raw = str(kind or "").strip()
    return LEGACY_RUN_KINDS.get(raw, raw)


def normalize_legacy_run_kinds(runs) -> list:
    """Rewrite legacy run kinds IN MEMORY; returns the ids it touched."""
    touched = []
    if not isinstance(runs, dict):
        return touched
    for rid, rec in runs.items():
        if not isinstance(rec, dict):
            continue
        new = normalize_run_kind(rec.get("kind"))
        if new != rec.get("kind"):
            rec["kind"] = new
            touched.append(str(rid))
    return touched


def execution_profile_of(ctx) -> str:
    """The root's recorded execution profile (`high` when the key is absent).

    A root created before the feature carries no key and keeps the pipeline's
    original behaviour, which is what `high` means.
    """
    raw = str((getattr(ctx, "cfg", None) or {}).get("execution_profile") or "").strip().lower()
    return raw if raw in (PROFILE_HIGH, PROFILE_MEDIUM) else PROFILE_HIGH


def targeted_review_of(ctx) -> str:
    """Is the round's TARGETED (checklist) review stage part of the plan?

    `on` unless the operator turned it off.  A root without the key -- every
    root created before this feature -- plans the targeted review exactly as
    before.
    """
    raw = str((getattr(ctx, "cfg", None) or {}).get("targeted_review") or "").strip().lower()
    return raw if raw in ("on", "off") else "on"


def targeted_review_enabled(ctx) -> bool:
    return targeted_review_of(ctx) != "off"


def _stage_contract_header(profile: str) -> str:
    return MEDIUM_PROFILE_CONTRACT if profile == PROFILE_MEDIUM else ""


def pageable_rule_blocks(venue_profile, author_to_complete: str) -> list:
    """The role-INDEPENDENT rule blocks every stage prompt may inline.

    `page_stage_prompt` replaces only the blocks that actually OCCUR in a given
    stage's prompt, so one list serves every builder: the review uses the
    defect-class rule, the reviser uses the language-pass rule, and neither is
    handed the other's text.  A role-specific variant (a visual-inspection block
    for one artifact, a Zotero ledger for one stage) is left inline on purpose:
    it is small, and it is the rule most likely to be mis-applied out of context.
    """
    prof = venue_profile
    blocks = [
        ("DEFECT CLASS RULE", defect_class_rule(prof)),
        ("STANDING EXEMPTIONS", standing_exemptions_text(prof)),
        ("PLACEHOLDER RULE", placeholder_rule_text(author_to_complete)),
        ("AUXILIARY FILES", AUX_FILES_RULE),
        ("DERIVED OUTPUTS", derived_outputs_rule(prof)),
        ("VALIDATION", VALIDATION_RULE),
        ("SHARED DECISION RULES", shared_blocks()),
        ("ATTACHED REVIEW BRIEF", attached_head(prof) + "\n" + attached_phase1(prof)),
        ("ATTACHED REVISION BRIEF", attached_head(prof) + "\n" + ATTACHED_PHASE2),
        ("LANGUAGE PASS", LANGUAGE_PASS_RULE.replace(
            "@@R6_PATH@@", "revised/work/R6_language.md")),
        ("LANGUAGE PASS", LANGUAGE_PASS_RULE.replace(
            "@@R6_PATH@@", "integrated/work/R6_language.md")),
        ("DIFFERENCE LEDGER", DIFF_LEDGER_RULE),
        ("RE-VERIFICATION BEFORE PORTING", INTEGRATION_REVALIDATION_RULE),
        ("RE-VALIDATION BEFORE EDITING", REVALIDATION_RULE),
        ("AUDIT ADDS NO FINDINGS", AUDIT_NO_NEW_FINDINGS),
    ]
    return blocks


def page_stage_prompt(sandbox, text: str, blocks, stage: str,
                      profile: str = PROFILE_HIGH) -> str:
    """`medium` only: page the elaborative rule blocks out of an assembled prompt.

    `blocks` is an ordered list of `(section_title, block_text)` pairs -- the
    exact strings the builder just substituted (or appended).  Each one that
    occurs in `text` is replaced by a pointer to
    `INSTRUCTIONS/PROFILE_RULES.md`, and every such block is written to that
    file under its own `## <section>` heading.

    `high` returns the text UNCHANGED (a rule of this module: the profile must
    not perturb the pipeline's original prompts by a single byte).
    """
    if profile != PROFILE_MEDIUM:
        return text
    from pathlib import Path

    sb = Path(sandbox)
    # Longest first: a block that contains another must be replaced before the
    # shorter one can eat a piece of it.
    ordered = sorted(((t, b) for t, b in blocks if b and isinstance(b, str)),
                     key=lambda tb: -len(tb[1]))
    sections = []
    for title, body in ordered:
        if body not in text:
            continue
        text = text.replace(body, PROFILE_POINTER_TMPL.format(
            section=title, rel=PROFILE_RULES_REL))
        sections.append((title, body))
    if sections:
        sb.joinpath(PROFILE_INSTRUCTIONS_DIR).mkdir(parents=True, exist_ok=True)
        parts = [PROFILE_RULES_HEADER, f"_Stage: {stage}_\n"]
        for title, body in sections:
            parts.append(f"\n## {title}\n\n{body.rstrip()}\n")
        write_text_atomic(sb / PROFILE_RULES_REL, "".join(parts))
    return _stage_contract_header(profile) + text


# ---------------------------------------------------------------------------
# `--no-targeted-review`: the frozen review view a round runs on when the
# targeted review did not run.
# ---------------------------------------------------------------------------

def _frozen_review_doc(r: int) -> dict:
    """The `targeted_review/findings.json` the downstream contracts read, gap declared."""
    coverage = []
    for cid in list(REQUIRED_REVIEW_CHECKS) + ["M18", "M19", "M20",
                                               "M21", "M22", "M23", "M24",
                                               "M25", "M26", "M27", "M28", "M29", "J5"]:
        coverage.append({"check": cid,
                         "disposition": f"unable -- {TARGETED_REVIEW_GAP}",
                         "detail": "no targeted-review session ran this round"})
    return {
        "round": int(r),
        "submission_dir": "base",
        "targeted_review": "off",
        "named_gap": TARGETED_REVIEW_GAP,
        "findings": [],
        "coverage": coverage,
    }


def synthesize_frozen_review(ctx, r: int, sb) -> dict:
    """Write the round's frozen review view into `sb` from the PROBE's findings.

    `--no-targeted-review` leaves the round without a review sandbox.  Every
    consumer downstream of it (the auditor, each reviser, the integrator's
    X-* reconciliation, the reports) reads one interface: `targeted_review/findings.json`
    plus `targeted_review/round2/findings_extra.json`.  This writes that interface, with
    the probe's X-9xx rows in the discovery file exactly where the probe merge
    puts them on a normal round, and a coverage table that states the missing
    targeted review as a named gap instead of leaving an empty list that looks
    like a clean corpus.
    """
    from pathlib import Path

    sb = Path(sb)
    rows = list(probe_findings_rows(ctx, r) or [])
    if journal_is_scoped(ctx):  # defensive: a scoped round never reaches here
        rows = []
    target = sb / TARGETED_REVIEW_DIR
    target.mkdir(parents=True, exist_ok=True)
    (target / "round2").mkdir(parents=True, exist_ok=True)
    write_json_atomic(sb / FINDINGS_REL, _frozen_review_doc(r))
    write_text_atomic(sb / TARGETED_REVIEW_DIR / "findings.md",
                      "# Frozen finding list — probe review only\n\n"
                      f"{TARGETED_REVIEW_GAP}\n\n"
                      f"The {len(rows)} X-9xx row(s) below are the probe review's "
                      f"findings, in `targeted_review/round2/findings_extra.json`.\n")
    discovery_json = f"{TARGETED_REVIEW_DIR}/round2/findings_extra.json"
    write_json_atomic(sb / discovery_json,
                      {"findings": rows, "source": "probe_review",
                       "targeted_review": "off", "named_gap": TARGETED_REVIEW_GAP})
    write_text_atomic(sb / f"{TARGETED_REVIEW_DIR}/round2/findings_extra.md",
                      "# Discovery list (probe review)\n\n" + TARGETED_REVIEW_GAP + "\n")
    return {"rows": len(rows), "named_gap": TARGETED_REVIEW_GAP}


def review_producer_rid(ctx, r: int):
    """The run id whose output IS the round's frozen review, or None.

    `None` means the targeted review did not run and the frozen view is
    synthesized from the probe (`synthesize_frozen_review`).
    """
    if not targeted_review_enabled(ctx):
        return None
    return rid_targeted_review_b(r) if review_split_of(ctx) != "off" else rid_targeted_review(r)

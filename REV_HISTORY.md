# AGENT.md — working in this repository

This repository is a **venue-agnostic** round-based manuscript revision
pipeline. Read this before changing anything; it is the short version of
`README.md` for an agent (or a human) editing the code, plus the rules that keep
the pipeline from drifting back to a single journal. One revision round —
the read-only manuscript, the round base, the two arms, the integration and the
blind judge panel — is drawn in `media/paper-refine-one-revision-round.png`
(`README.md` embeds the image; the `.pdf` render and the `.pptx` source beside
it are local artefacts, not committed).

## What the pieces are

| path | what it is |
|---|---|
| `paper_pipeline.py` | the orchestrator (single file, stdlib only). CLI: `setup`, `run`, `run-decide`, `decide`, `status`, `trend`, `agents`, `conflicts`, `selfcheck`, `adopt-sweep`, `set-venue`, `set-journal`, `set-article-type`, `set-revision-mode`, `set-tiebreak-defect-floor`, `set-dedup-mode`, `set-probe-review`, `set-submit-code`, `add-venue`, `build-venue-templates`, `retry`, `prune`, `redline`, `track`, `conform`. |
| `paper_docx_format.py` | the optional companion: code-side OOXML style/formatting scan/fix (`scan`/`fix`/`check-pdf`) and the Zotero live-field parity check (`zotero-check FILE.docx`, FMT-Z1..Z5 / M36). |
| `paper_redlines_adapter.py` | optional tracked-changes `.docx` bridge. |
| `docxcompare.sh` + `mcp-docx-compare/` | Word's own comparison engine (`Word.Application.CompareDocuments` through PowerShell COM) -- the FIRST choice whenever two `.docx` files must be tracked (the `docx-compare` MCP tool wraps the script). |
| `docx2pdf.sh` + `mcp-docx-converter/` | the first-choice DOCX→PDF renderer. |
| `venue_profiles/` | the venue profiles (the submission rule sets) **and their schema documentation** — start at `venue_profiles/README.md`. |
| `paper-skills/` | the bundled `paper-review` / `paper-revise` skill packages and the two master prompts. |
| `media/` | the figures the docs embed: `paper-refine-one-revision-round.png`, one revision round. |
| `.paper_test/` | the offline regression suites (stub agents; no network). |

## Venue vs journal — the rule that matters here

* A **venue** is a *rule set*: the abstract/main-text limits and their margins,
  the figure-legend policy, the cover-letter preference, the submission-format
  note, and the phrases the prompts use. It is selected by **id**
  (`set-venue <id>`, `setup --venue <id>`) and realised by a **venue profile** —
  a JSON document in `venue_profiles/`.
* A **journal** is a *name*: the publication the manuscript is going to, free
  text (`set-journal "Cell"`). The prompts use it and the venue profile is
  checked against it. It selects no rules.
* An **article type** is *which* of the venue's content types the manuscript is
  (Article, Brief Communication, Review, Resource, Analysis, Matters Arising,
  Letter to the Editor, …). The limits belong to the type, not to the venue as a
  whole: the profile carries the table (`article_types`) and the root records
  the selection (`setup --article-type`, `set-article-type`). A type the profile
  carries no numbers for is counted and reported against the venue's own
  content-types table — never measured with another type's caps.

All three live in `<root>/pipeline_config.json` (`venue`, `journal`,
`article_type`) plus a snapshot of the resolved profile (`venue_profile`),
mirrored into `state.json`. The defaults are `nature-biotechnology` /
"Nature Biotechnology" / `article` — the pipeline's pre-venue behaviour — so
roots created before these features keep working byte-for-byte.

Resolution order: the current command's flags → `pipeline_config.json` (and its
snapshot, which wins over profile *files*) → `<root>/venue_profiles/<id>.json` →
the profiles shipped next to the script → the built-in fallback inside
`paper_pipeline.py` → the profile's `default_journal` → the default venue.

## Rules for changing the pipeline

1. **Never hard-code a journal name, a journal's numbers or a journal's
   submission requirement in the orchestration code.** Venue-specific facts go
   into a venue profile, and article types are profile data too (one entry per
   type, each with its own `length_limits`; a type with no numbers stays
   numbers-free rather than inheriting). The code reads them through `VenueProfile`
   (`venue_profile_of(ctx)`, `length_limits(profile)`,
   `standing_exemptions_text(profile)`, `caption_rule_text(limit, profile)`,
   `m19_blocks(profile)`, `derived_outputs_rule(profile)`,
   `render_venue_tokens(text, profile)`). Adding a venue must be adding a JSON
   file, never adding an `if venue == ...` branch.
2. **Every stage reads the configured values.** Prompt builders take
   `venue=<VenueProfile>`; the scans take `profile=`; setup/status/decide print
   `venue_status_lines(ctx)`. If you add a place that names the journal or a
   limit, render it from the profile.
3. **A missing or partial venue must degrade to "count and report", never to an
   invented number.** A profile with `base: null` means the stage enumerates the
   count and names the limit the target journal's own guidelines state.
4. **Do not silently change an existing root's rules.** The recorded snapshot is
   authoritative; profile files are only a lookup for roots that have no
   snapshot. `set-venue` re-records it, and refuses (without `--force`) once the
   root has run records.
   One narrow exception, for a field that did not exist when a snapshot was
   recorded: a snapshot with NO `tables`/`figures` key inherits the venue's
   shipped block of that kind (and ONLY those blocks; every other recorded rule
   still wins), so a root created before the display rules existed still gets
   its venue's rules. A snapshot that carries the key -- including an empty
   block -- is authoritative, as are operator overrides in
   `format_policy.tables` / `.figures`.
5. **Backward compatibility is a test.** `test_venue_config.py` asserts that a
   config without `venue`/`journal` behaves exactly like the old default.
6. The skill ids `$paper-review` / `$paper-revise` and the file names `paper_*.py` are
   **historical identifiers**, not venue assumptions: they are the stable names
   of the installed skill packages and of this repository's entry points. Do not
   rename them in prompt text; do keep their *prose* venue-neutral.
7. **Every two-sided check runs in BOTH directions, and one direction is not
   the check.** A claim can be too strong (overclaim) or too weak (underclaim);
   content can be lost or invented; an item can be missing or unneeded; a claim
   can carry no pointer or a printed item no description; an availability claim
   can outrun or undersell its locator; a document can be dropped or added.
   When you touch a check, its sweep entry, its prompt text or its fix rule,
   keep the pair symmetric (the shared decision block's D1 states the rule for
   every session, and `paper_docx_format.claim_strength_rows` +
   `CLAIM_STRENGTH.md` are the J3 surface; `.paper_test/test_two_sided_checks.py`
   pins it). Never add or edit only the loud direction.
8. **The source hierarchy is BOTH a resolution rule and a detection rule.**
   `SOURCE_HIERARCHY` (`paper_pipeline.py`) decides which side wins when two
   sources disagree; **M30** is the check that *finds* a written claim its own
   shipped code/raw data contradicts (`paper_docx_format.hierarchy_seed_rows` +
   `code_literal_rows` → `M30_hierarchy_reconciliation.md`; the review requires
   its coverage row and artifact, the auditor attacks the "out of scope"
   closures, and paper-revise's rule E12 aligns the WRITTEN side — rule C owns a
   code fix and `raw_data/` is read-only). M30 is review-side like M25–M29; the
   judge's frozen map stays M1–M24 + J1–J4 and its prompt scores the class under
   correctness/completeness. `.paper_test/test_hierarchy_reconciliation.py`
   pins it. Do not let a new producer-bearing artifact (a new code directory, a
   new data snapshot) enter the corpus without a way to reconcile it.
   The EVIDENCE areas are `raw_data/` (data, figure/table sources, analysis
   snapshot; legacy `raw_figs/`), `human_review_feedback/` (the REAL
   editors'/reviewers' comments, plus any previous response as context) and —
   when the operator supplies one — `llm_review_feedback/` (a machine-generated
   review whose false positives were filtered out upstream, so every remaining
   finding is a real concern with the same standing as a human point). All are
   read-only, not submission content: the converter writes their text to
   `WORK/evidence/` (never `WORK/corpus/`), the code-side scans and the skill
   scripts skip them (and a feedback/response document elsewhere in the corpus,
   by name), and no sweep counts or quotes them as the authors' prose. M30
   reads `raw_data/` as the producer side; the journal modes build the concern
   ledger and the response letter from `human_review_feedback/` and (when
   present) `llm_review_feedback/`, staging the LLM stream under `feedback/llm/`
   with its origin kept in the ledger; and a JUDGE sees every area under the
   labeled `evidence/` directory in its view (raw_data for correctness, the
   feedback areas for whether the version addresses the raised concerns, with
   the LLM findings judged like human points and never dismissed as model
   noise). `.paper_test/test_raw_data_evidence_area.py`,
   `.paper_test/test_human_review_feedback_area.py` and
   `.paper_test/test_llm_review_feedback_area.py` pin the contract. Never
   extend a scan or a packaging step without routing it through
   `is_evidence_rel` / `is_non_manuscript_rel`.
9. **A table's or a figure's caption and its place in the manuscript are VENUE FACTS too.**
   The profile carries them in its `tables` and `figures` blocks (`placement`, `caption`,
   `special`, `source`, `note`; one shared schema); `format_policy_of` injects the blocks
   into the formatter policy, the formatter's scan emits `FMT-TB1..3` / `FMT-FG1..3`
   (no caption / caption on the wrong side / item before its area) rows from exactly what
   they declare, the prompts render `display_rule_text(profile)`, and a package-producing
   stage (rewrite / revise / integrate and the template-first `conform`) FAILS while its
   delivered package still carries one of those rows (`display_rule_errors`). A profile
   with no block for a kind gets no rows and no gate for it -- never invent a rule -- and
   `special` must stay an exception list, not a blanket exemption: it names the items the
   venue itself treats differently (a key-resources table inside the methods; a graphical
   abstract that is not in the numbered figure sequence), matched on the text above the
   item, its section heading or (tables only) its first-row header, and overrides only the
   fields it states. The checks run on the MANUSCRIPT body, never on a supplementary,
   cover-letter or feedback/response document. Every session sandbox carries the blocks as
   `format_policy.json`, so the session's own `paper_docx_format.py scan <dir> --policy
   format_policy.json` checks the same rules the postcheck enforces. Pinned by
   `.paper_test/test_display_rules.py`.
10. **`run --only` and `retry --runs` are ONE selection language.** `OnlySpec`
    (`parse_only_spec`, `entry_selected`, `stage_selected`, `judge_spec_for`,
    `resolve_judge_run_ids`) is the single parser, and `retry --runs` resolves the same
    selection to RUN RECORDS with the same predicates the run loop uses
    (`retry_targets_for_selection`) -- never a second grammar, and never a reset of more
    runs than the operator named. Targets are ordered by round and by the plan's stage
    rank (a1 -> feedback/concerns -> rewrite/review -> audit -> revise -> response ->
    integrate -> judge), because `retry` re-materializes a target whose upstream is still
    done and leaves the rest stale for the next `run`. Pinned by
    `.paper_test/test_stage_subset.py`.
11. **`--skip-hash` skips VERIFICATION, never RECORDING.** The switch (`configure_hash_checks`,
    `hash_checks_skipped`) short-circuits `pristine_integrity`, `pinned_integrity`,
    `input_mismatches`, `run_input_problems`, `_check_pristine_copy`, the judge-view digest
    comparison and the a1 digest COMPARISON -- while every digest those paths record
    (state.json, pins, fingerprints, `corpus_digest`) is still computed, so the next
    invocation without the flag verifies the same chain. `status`, `decision.json`'s
    `integrity` and `certification` (`hash_checks: verified|skipped`) and the published
    `final_clean_version.readme.md` must always say which one it was: "skipped" may never
    print as "verified", and the within-invocation freshness checks that decide what an
    agent READS are never skipped. Pinned by `.paper_test/test_skip_hash.py`.
12. **Whitespace, grammar artifacts and embedded-image geometry are ONE policy-driven
    class.** `format_policy_of` injects the venue template's own blank-paragraph slots
    (`empty_paragraph_slots`, derived from the official Word template(s) by
    `paper_docx_format.empty_paragraph_slots_from_template`) and `seed_format_policy_file`
    writes them into every session's `format_policy.json`, so a session's own scan and the
    postcheck agree on what is prescribed. A blank the template carries -- the spacer above
    the title, a placeholder between two headings -- is NEVER reported or deleted; the stray
    blanks (`FMT-S8` attached to a heading, `FMT-S6` beyond `max_empty_paragraph_run`), the
    line-edge spaces (`FMT-P4`), the doubled word (`FMT-G1`) and an image drawn off its own
    pixel ratio (`FMT-IM1`) are mechanical and repaired before fingerprinting. Text-hygiene
    repairs are RECORDED text edits (like the citation/spelling edits) so the fixer's
    `text_diff_only_recorded_edits` verification still proves nothing else moved; a
    spelling-pair TIE is broken by the first occurrence, never left as an unfixable
    mechanical row (that tie used to reject every other repair of the file). Pinned by
    `.paper_test/test_format_hygiene.py`.
13. **A cover letter is a LETTER, not a manuscript document.** The journal's manuscript
    Word template is applied only to the manuscript / supplementary DOCX; a cover letter is
    restyled only into a cover-letter template the journal itself publishes (a `.docx`/
    `.dotx` in `<venue>.official/` whose name carries "cover"/"letter", resolved as the
    `word["cover"]` role). With none, `template_for_package_file` and
    `normalize_formatting_in_dir` resolve no template for it, `conform` carries it as
    authored (warning when it still uses the manuscript template's Title/Author-List
    styles), the conformance scan demands no manuscript styles/front matter from it, the
    template-first postcheck FAILS such a stamped letter, and every prompt sends it down
    the journal-guideline -> academic-convention chain. The defect is PROVEN in code:
    `format_policy_of` derives the manuscript template's front-matter style ids and its
    header/footer part hashes into the policy, and the OOXML scan reports **FMT-CL1**
    (finding tier) on every letter that carries them (the rule stands down when the
    journal ships its own cover-letter template). Every agent class must act on it: the
    review's disposition gate fails an `OK` closure without the journal's own quoted
    override and fails a table that DELETED the row; the auditor attacks such closures;
    the revise/integrate arms must restyle the letter (the rewrite arm surfaces it); and
    a judge whose blinded target carries the row must record it in its M20 artifact and
    cannot close it `OK` without that override. Pinned by
    `.paper_test/test_venue_template_conformance.py` and
    the `test_docx_format_*_*.py` parts.
14. **Difference tracking and the PDF renders are AUXILIARY, CODE-ONLY passes.**
    Tracking is written THE MOMENT A STAGE IS ACCEPTED, not at round close:
    `postcheck()` calls `track_after_stage()` for every `rewrite`/`revise`/
    `integrate` attempt that passes, and the template-first `conform` calls
    `maybe_track_template_stage()` when its own postcheck passes. Each writes
    `<name>.tracking-<baseline>.<ext>` (or the `<name>.logging-<baseline>.<ext>`
    fallback log when the tool failed) BESIDE the documents the stage produced --
    `runs/r1_w1/rewritten/`, `runs/r2_a2_revise/revised/`,
    `template_rewrite/out/` -- mirrors it under `<root>/tracking/`, and writes
    the same copies into every published `round<r>_winner/` (the round-close
    `round_tracking()`, started by `run` unless `--no-track`, keeps every fresh
    entry and fills in what a stage did not write). The baseline token NAMES
    WHAT THE COPY IS COMPARED AGAINST: `original` (the pre-conformed
    submission), `a1` (the round base), `w<k>`/`a<k>` (the version an
    integration's own `self/` member reworked) or `winner<r>` (a published round
    winner) -- there is no generic "previous" token. `.docx` pairs go through
    the `docx-compare` MCP tool (Word's own `CompareDocuments`) FIRST, then the
    redline chain; `.tex`/`.bib` pairs go through `latexdiff`, and each latexdiff
    `.tex` copy that is a LaTeX ROOT -- a byte-identical copy included, which
    yields the clean PDF -- whose `\input{}`/`\include{}`/`\addbibresource{}`/
    `\bibliography{}` targets have their own tracked copies is REWIRED to them
    and compiled into a sibling `<name>.tracking-<baseline>.pdf`
    (`compile_tracking_pdfs`; the lowercase `\dif*` aliases cover `change.case$`
    BibTeX styles; a fragment is skipped, it compiles through its master). The
    version/winner PDFs land under `<root>/pdfs/`. Three rules: (a) the names
    live in ONE place, `TRACKING_AUX_NAME_RE` / `tracking_aux_suffix()` (the
    scanner and the skill's `revision_token.py` must keep agreeing -- a test
    pins all three), so no file of the family (the compiled tracking PDF
    included) may ever be treated as submission content; (b) the pass starts NO
    agent session and must not be able to change a champion, a score, a pin or
    an input manifest -- `.paper_test/test_difference_tracking_4_e2e.py` runs a
    stub round with and without it and compares the recorded end result, and
    `.paper_test/test_difference_tracking_5_stage_hooks.py` pins the stage-time
    placement and the rewired/compiled tracking PDFs; (c) compile/convert
    failures are WARNINGS (recorded in the manifest / `<root>/pdfs/` and
    printed), never a failed stage.

15. **The published package is CHECKED as an artifact, not just as text.**
    Five classes reached a CERTIFIED package because nothing enumerated them:
    a section inside the pipeline's own relaxation but above the venue's base
    number (M19 now reports the BAND, and every mandate says the venue's own
    number is the one the submission is measured against); reference-entry
    SHAPE (`FMT-R1`–`FMT-R5`: a malformed journal/volume field, an entry with
    no venue, an unversioned repository citation, a bioRxiv-style identifier
    with a foreign DOI prefix, and the profile-gated preprint/trial-abstract
    row); display-item ORDER (`FMT-O1`, profile-gated by `numbering:
    "citation"`), glued front matter (`FMT-X2`) and another publisher's
    leftover boilerplate (`FMT-L1`, from the profile's `leftover_phrases`);
    availability finality (`FMT-AV1`: "not yet deposited", "available from the
    lead contact", "on request"; `FMT-AV2`: one repository pinned to two
    commits); and the shipped PDFs (`FMT-PDF1`–`FMT-PDF3`: an XFA/LiveCycle
    form shell that renders only Adobe's "Please wait…", an XFA dataset with no
    filled value, an export with no extractable text). Two more rules live on
    the PACKAGE level: `PKG-1` reports internal working material in the
    submission surface (an internal AI-review session URL, the pipeline's own
    re-authoring ledger or stage report, a stage note) and `is_bookkeeping_name`
    strips the pipeline's by-product family BY PATTERN, version token included
    (`REPLACEMENT_LEDGER-c27c42e.md` used to ship because the exact-name test
    missed it). `publish_final_clean` records `hygiene.internal_artifacts`,
    `hygiene.pdf_artifacts` and `hygiene.stripped_bookkeeping` in
    `decision.json`, prints them and writes them into
    `final_clean_version.readme.md` as AUTHOR ACTIONS — none of them is
    silently deleted from the author's own file. M30 grew its NON-numeric half
    (`negative_claim_rows`, seed id `M30-NC`): a written "could not be run /
    produced no output" claim while a shipped table carries that method's own
    rows. The review → audit → revise path carries the EVIDENCE-INTEGRITY
    sweeps **M31–M35** (artwork-versus-legend consistency, a headline
    statistic against the correction the paper itself states,
    availability-locator finality, figure-source-data coverage,
    disclosure/provenance completeness); the judge's frozen map is unchanged,
    discovery proposals now start at **M37**, and
    `.paper_test/test_package_integrity_2026_1009.py` pins all of it. Every new
    profile key (`numbering`, `references`, `leftover_phrases`) follows the
    "never invent a rule" contract: absent = no rows.

16. **A Word/Zotero refresh must not change the numbering, and the repo PROVES
    that before a package ships.** The manuscript's citations are live Zotero
    fields, so their rendered numbers and the bibliography are CACHED results of
    the last time the citation processor ran. Edit around them (merge two
    versions, move a paragraph) and the cache goes stale — the numbers in the
    text and the order of the reference list no longer agree with the document's
    own citation order — and the first **Zotero → Refresh** in Word renumbers the
    text, reorders the bibliography and (because the CSL style is stored in TWO
    places, `word/settings.xml` docVars and the `docProps/custom.xml` property)
    can re-render every entry in a different style. A certified package can
    therefore come back with different citation numbers, a different reference
    order and a different reference format — and individual fields can even be
    left stale by the refresh, shipping markers that point at the wrong
    reference. The repo now has **M36** and the code-side `FMT-Z1..Z5` rows
    (`zotero_citation_state`, `zotero_parity_rows` — offline: every citation
    field embeds its own `itemData`): `Z1` a marker whose number is not the cited
    item's rank, `Z2` the entry at a rank describing another work, `Z3` one item
    with two numbers / a number outside 1..N / an entry never cited, `Z4` a
    stored marker that disagrees with the visible runs, `Z5` conflicting style
    stores. `zotero_report_for_docx` carries the rows and
    `zotero_field_continuity_problems` makes a version that INTRODUCES a
    high-severity row a hard error while a refresh that clears them is a recorded
    repair. Every row is `fix=manual`, `protected=true`: the tools NEVER edit a
    field result. The author's loop is
    `python3 paper_docx_format.py zotero-check FILE.docx` → refresh in
    Word/Zotero → re-check → only then flatten (`unlink_zotero_fields`) for the
    submission copy; **never flatten a document whose markers are stale**, which
    would freeze the wrong numbering. Pinned by
    `.paper_test/test_zotero_refresh_parity.py`.

    **The offline refresh closes that loop by itself (2026-10-11).**
    `zotero_refresh_document`/`refresh_zotero_parts` re-derive every marker from
    the document's own citation order, rewrite the field's cached JSON and its
    visible result runs, rebuild a bibliography whose order or numbers disagree
    (every entry matched to its item's embedded `itemData`; a full bijection or
    nothing) and reconcile the two style stores to one CSL style — and
    `fix_package` runs it automatically at every package-producing stage and at
    publication, before `unlink_zotero_fields` (so a flattened submission copy
    carries the CORRECT numbering). **Unlinking is NEVER a default**: the
    pipeline does not unlink the fields unless asked, because the author
    normally unlinks them manually for the final submission file. When asked
    (CLI `zotero-refresh FILE.docx --unlink`, `fix ... --unlink-zotero-fields`,
    or — for the published copy — `decide --unlink-zotero-fields` /
    `format_policy.unlink_zotero_fields_at_publish: true`), the order is
    refresh → verify → unlink; the published copy is otherwise left with
    refreshed live fields and the readme says so. A refused flatten leaves the
    fields live and is recorded as readiness finding `FMT-Z7`, never as a
    silent freeze. It also repairs
    the reference-entry shapes
    `FMT-R1`/`R2`/`R3` from the facts a sibling `.bib` proves. The refresh is
    all-or-nothing and self-verified: an unresolvable item, an unrebuildable
    marker or a result that still fails its own FMT-Z checks writes NOTHING.
    Stand-alone: `python3 paper_docx_format.py zotero-refresh FILE.docx`. XFA
    forms: `FMT-PDF4` says filled-but-not-flattened (never the old false
    `FMT-PDF2`), `xfa-export` renders the answers readably, and `decide`
    records `readiness` (`submission_ready`) with `--require-ready` turning the
    package findings into blockers. Pinned by
    `.paper_test/test_zotero_auto_refresh_2026_1011.py`.

17. **The discovery round (D0–D5) is CHECKED, and its proposals CONVERGE.**
    Phase 3 of the review is the open-ended hunt for classes the frozen
    checklist does not own; a three-line `new_sweeps.md` (or no `review/round2/`
    at all) used to pass. `paper_pipeline.discovery_contract_problems` reads the
    whole deliverable set and, under the review's `--strict-artifacts` policy,
    fails a review whose discovery round is not real work: `known_index.md`
    names the class range, `gap_table.md` carries ≥25 rows each marked
    COVERED/UNCOVERED with at least one UNCOVERED, `probes.md` covers every
    uncovered row (probe or recorded limitation) with a status, `probe_results.md`
    disposes every probe (`no anomalies — checked: <locations>` / `unable —
    reason`), `findings_extra.json` carries the standard X-* finding shape,
    `new_sweeps.md` carries sweeps.md-shaped proposals from M37 (or an explicit
    no-proposal statement) and `round2_summary.md` the counts + honest limits.
    Continuity is code-enforced: every proposal id in `prior_round/new_sweeps.md`
    must be re-probed or dispositioned in the current round's round-2 artifacts.
    The auditor attacks the probe dispositions (`audit/PROBE_AUDIT.md`), F/X
    duplicates get a mechanical audit trail, and `adopt-sweep` validates a
    proposal file and (with `--yes`) appends it to `references/sweeps.md` while
    re-syncing the standalone prompt's appendix. Pinned by
    `.paper_test/test_round2_sweep_2026_1009.py`. Do not weaken any of these
    gates to make a session pass: the whole point is that an unfilled phase is
    indistinguishable from a skipped one.

18. **The discovery round's `X-*` findings reach the stages that need them
    WITHOUT breaking judge blinding: the integrator gets the frozen list, the
    judges re-derive their own.** The review's phase-3 discovery round is the
    only source of defect classes the frozen checklist does not own, and its
    `X-*` findings are what the revision arms resolve. Two consumers were
    missing, and they need DIFFERENT treatment:

    * the INTEGRATOR is not a blind stage: `round_discovery_seed()` resolves the
      round's list (the review sandbox, part B under a split review, or the
      archived `reports/round<r>_review/` copy) and `seed_discovery_findings()`
      copies `review/round2/findings_extra.{json,md}` VERBATIM into
      `frozen_discovery/` there (read-only, in `inputs_manifest`, byte-verified
      by `input_mismatches`). `integrated/DIFF_LEDGER.md` must reconcile every X
      id (ported / kept-base / an explicit no-donor-fix row), which
      `postcheck_integrate` verifies by id, or a donor's X fix can be dropped as
      an "unnamable" difference and the round's revision work vanishes. The
      AUDITOR's `drop` takes an X id out of force (`discovery_dropped_ids()`).
    * the JUDGE is COMPLETELY blind to the sources of a package -- no other
      session's findings, no round, no producing agent -- so it is **never
      seeded** with the list. Judge contract v5 instead requires the judge to
      RE-DERIVE the class itself: `judge_discovery_problems()` enforces one
      disposed file per side (`judge_review/discovery/target.md` +
      `<label>.md` for every opponent; missing or empty = failed run,
      structural softness = warning), produced by the bounded pass in
      `judge_discovery_block()` with the SAME candidates and depth for every
      side. An X-class difference the pass proves is filed as a normal
      `resolved`/`introduced` row in an EXISTING tier (the shared class rule's
      category mapping: categories 0-5 already cover
      correctness/preservation/completeness/consistency/writing/formatting;
      never invent a new class, because the census, the ranking and the score
      model all read the same six). An X id a judge cites is its OWN finding id
      -- descriptive, never a frozen check id -- and the `checks` coverage map
      stays M1-M24 + J1-J4.

    The judge prompt must stay free of provenance vocabulary (see
    `test_agent_consistency_2026_0922.py`) and must not hand over any discovery
    list; the pass is worded in content terms only. Pinned by
    `.paper_test/test_discovery_parity_2026_1010.py`.

19. **The PROBE REVIEW is a GENERIC, independent producer in the SAME frozen
    list, and every computation it declares is RE-RUN, never trusted.**
    `setup --probe-review` (default `on`; `--no-probe-review`, or
    `set-probe-review off` on an existing root, is the off switch; a root without
    the key plans none) adds `r<r>_probe` beside `r<r>_review`, depends only on
    the base, and the auditor/revision arms wait for it (`round_run_plan`). The
    probe is part of the review STEP for `--only`: selecting the review stage
    (`--only review`, `2:review`) runs the probe with it, while
    `retry --runs 1:review` stays exact (a retry resets only the runs named).
    The
    session is materialized with `base/`, `non_revised/` and two seeded
    CANDIDATE inventories (`probe_review/CLAIM_SURFACES.md`, `PRODUCERS.md`) and
    NOTHING else: no `review/`, no `prior_round/`, no finding list, no sweep
    table -- the whole point is a second, unanchored read in a context that has
    not already disposed the checklist's rows. It is GENERIC on purpose: any
    defect class may be filed (category 0-5, Fatal..Minor, any location in the
    submission documents or the evidence areas), in the same vocabulary every
    other session uses; wherever a defect can be SHOWN BY A COMPUTATION the
    finding declares a `verifier` (a relative script under
    `probe_review/scripts/` plus the exact `computed` value it prints).
    The contract is code-enforced by `postcheck_probe` +
    `_probe_contract_problems` + `probe_reproduction`:
      * the report carries a `checked` inventory (every AREA examined, with
        candidate and finding counts), so a zero-finding pass is an examined
        corpus and not an unrun one;
      * every finding has the standard shape and an `X-9xx` id (the RESERVED
        probe block; `PROBE_ID_RE`) -- a finding outside it is refused;
      * EVERY declared verifier is RE-RUN (offline, cwd = the sandbox root,
        bounded) and its last stdout line compared with `computed`
        (`probe_reproduction`): a mismatch, a missing script, a non-zero exit,
        an empty output or a timeout FAILS the attempt -- a computation the
        probe cannot reproduce is a correctness blocker, not a finding
        (`probe_review/REPRODUCTION.md` is the code-written record); findings
        WITHOUT a verifier are evidence rows and are never re-run;
      * `probe_review/coverage.md` (the areas, counts and honest limits) must
        exist and be non-empty, and `sandbox_selfcheck --stage probe` applies
        the same detectors before the marker.
    The findings ride the discovery namespace WITHOUT ever mutating the frozen
    review: `merge_probe_into_review_copy()` merges them into the review COPY of
    the audit and of every reviser (collision-safe remap, recorded),
    `round_discovery_seed()`/`seed_discovery_findings()` add them to the
    integration seed (`frozen_discovery/findings_extra.json`, merged in code),
    and `archive_review_outputs()` archives the MERGED discovery list (plus the
    probe's own `findings_probe.json`/reproduction record) so a pruned root
    re-seeds the same ids AND the next round's `prior_round/` carry-over gate
    reconciles every probe finding like any other X-* row. The auditor disposes
    them like any frozen id, the reviser's ledger must name them, and the
    integration ledger must reconcile them. The JUDGE never receives the list
    (blinding): it re-derives its OWN generic discovery pass
    (`judge_discovery_block`) and files an X-class side difference as a normal
    `resolved`/`introduced` row. Do NOT narrow either pass to a fixed class
    list. Pinned by `.paper_test/test_probe_review_2026_1012.py`.

## Commands you will use

```bash
# configure / inspect the venue and journal of an existing root
python paper_pipeline.py set-venue --list
python paper_pipeline.py set-venue example-journal --profile venue_profiles/example-journal.json
python paper_pipeline.py set-venue --journal "Example Journal"
python paper_pipeline.py set-journal "Example Journal"
python paper_pipeline.py set-venue --show [--json]
python paper_pipeline.py set-article-type --list
python paper_pipeline.py set-article-type brief-communication
python paper_pipeline.py set-article-type --show [--json]
python paper_pipeline.py status --root ./paper_rounds      # venue + journal + limits

# run/reset a subset with ONE grammar; skip the verification passes when asked
python paper_pipeline.py run   --root ./paper_rounds --only 1:review,1:feedback
python paper_pipeline.py retry --root ./paper_rounds --runs 1:judge,2:feedback,2:review
python paper_pipeline.py decide --root ./paper_rounds --skip-hash
python paper_pipeline.py track --root ./paper_rounds   # difference copies + persistent PDFs

# create a root for a specific venue in one step
python paper_pipeline.py setup --source ./non_revised --root ./paper_rounds \
    --venue generic --journal "Journal Name" --article-type article

# start at a later built-in schedule round: two rounds following the schedule's
# rounds 2 and 3 (no rewrites), or only the final round with --round-indices -1
python paper_pipeline.py setup --source ./non_revised --root ./paper_rounds \
    --round-indices 2 3

# validation (see README.md -> Tests for the full list)
python3 -m py_compile paper_pipeline.py paper_docx_format.py
python3 .paper_test/run_all.py                 # every suite, offline (24 jobs by default)
sh .paper_test/run_one.sh test_venue_config.py
```

## When a stage prompt is written

The prompt builders are the only place the venue appears to an agent. They
render, from the profile:

* the length rule (M19) and its mandates — the numbers, margins and provenance
  of the **selected article type** (a type the profile carries no numbers for
  renders the counts-only wording, never another type's caps);
* the caption rule (M18) — the venue's own legend policy;
* the derived-outputs rule — whether the venue accepts a submitted PDF;
* the master-prompt prose — subject, editor, requirements, guidelines source;
* the standing exemptions and the shared decision blocks.

If you add a rule that depends on the venue, add a field to the profile schema
(documented in `venue_profiles/README.md`), a rendering function here, and a
case in `test_venue_config.py` that asserts a non-default venue produces no
default-venue text. A field a recorded snapshot predates (`tables`, `figures`,
`references`, `numbering`, `leftover_phrases`) is inherited from the venue's own
profile file — and ONLY when the snapshot carries no key for it — by
`_inherited_display_rules`; a snapshot that carries the key, including an empty
block, stays authoritative.

## Journal revision modes — do not regress the default

`pipeline_config.json` may carry `revision_mode` (one of `continue`, `init`,
`transfer`, `resubmit`, `major`, `minor`, `llm`; default `continue`) and
`journal_feedback` (the decision-letter files; when unset they are taken from
`human_review_feedback/` first, then a legacy feedback-named file anywhere in
the corpus). A sibling `llm_review_feedback/` area is read BESIDE them: it is
staged under `feedback/llm/` and its pre-filtered findings join the concern
ledger with their origin recorded (the `feedback/concerns` stages consume both
streams; only the human/decision-letter stream uses the name heuristic).
Mode `llm` (option 5) is the one exception: it reads ONLY
`llm_review_feedback/` (no journal letter, no response letter), and it is
DIRECTORY-DRIVEN -- when no explicit `revision_mode` is recorded and the
pristine corpus carries a non-empty `llm_review_feedback/`, `journal_mode_of`
returns `llm` automatically (`setup` records it; run/status print the auto
detection). An explicit recorded mode always wins, and renaming the area to
`llm_review_feedback.disabled` (or `.off`) is the inert off-switch: the renamed
tree is never read as feedback or evidence and never becomes submission
content (`is_disabled_evidence_rel` keeps it out of scans, views and packages).
`continue` is the historical workflow; `none` is its pre-rename
spelling and is still accepted everywhere as an alias (it normalises to
`continue` and is never returned by `journal_mode_of`). `init` starts a NEW
submission: the conform stage runs before round 1 (inside the venue's own Word
template when one ships, else to the journal's own author guidelines and then
academic convention) and reads no feedback. The modes are documented in README
→ "Revision modes: `continue`, `init`, the journal modes (options 1–4), and `llm` (5)" and pinned by
the `test_journal_revision_modes_*_*.py` parts + the init section of
`.paper_test/test_venue_template_conformance.py`. Two rules matter when
touching this area:

* **The default mode is untouchable.** Every journal code path is entered only
  through the mode table (`journal_has_feedback`, `journal_is_scoped`,
  `journal_needs_response`) or `journal_mode_of(ctx) != JOURNAL_MODE_CONTINUE`:
  the round plan, prompt builders, postchecks, `decide`/`status` output and the
  submission packager must all be identical to their historical behaviour when
  the mode is absent. The J6 section of the test suite asserts the plan has no
  journal stage and the prompt carries no journal block.
* **`init` = conform first, then the default rounds.** Its plan is the default
  plan (no feedback/concerns/response stages) and the revise prompt must carry
  no journal block; only the conform stage runs first, and it must skip that
  stage only on `--no-template-stage` or a corpus with no `.docx`.
* **Careful with the scoped modes.** `major`/`minor` normalise the plan
  (rewrites 0, one revise arm, integrators 0, one round, audit off), replace the
  review with the concerns run, and enforce `scoped_scope_problems` in the
  revise postcheck: a changed file the revision ledger does not name, or any
  added/removed file, fails the attempt. The response letter is verified
  against the package (cited files must exist; `planned` rows claim nothing).
  The response letter and `journal_submission/` are submission documents, never
  manuscript text, and neither `raw_data/` nor the analysis-code area `code/`
  may be referred into by them: the submission copy strips both (`code/` is
  revision content the stages revise and the judges evaluate, but not submitted
  unless the recorded `submit_code` policy says so; the manifest records the
  actual `code_included`), and a letter whose `changes`/`new_data` cites a
  `code/` path fails `postcheck_response`. `setup --submit-code on` /
  `set-submit-code on` submits the area instead (the copy carries `code/` and
  the letter may cite it); the flag only decides what the next assembly of the
  package carries, never a pin, a score or a champion. The assembly also
  REPORTS (`PKG-2`, `journal_submission.json.non_submitted_references`) every
  other shipped text file that still points into a stripped area -- the raw
  data and the feedback areas are read-only inputs that never ship, so nothing
  that ships may refer into them either. The author's own documentation is
  never submitted either: every file whose NAME matches `README*.md` or
  `README*.txt` (any depth) is dropped from the submission copy -- no opt-in
  switch, unlike `code/` -- recorded in `readme_files_excluded`, never citable
  by the letter, and a bare or relative `README` reference in any other shipped
  file is a `PKG-2` row.
* **Retry/rebuild must know the chain.** `upstream_deps` maps
  feedback/concerns → a1, revise → a1 + the recorded review/concerns run, and
  response → its recorded ledger run: without those entries a scoped round can
  never be rebuilt after a retry (see `test_journal_revision_modes_7_scoped_prune.py`).
* **A new venue on a fresh root** goes in with
  `setup --venue-profile FILE` (the file is validated, installed into
  `<root>/venue_profiles/`, and recorded); `set-venue <id> --profile FILE`
  remains the path for an existing root.

## Scoring calibration — two rules that are easy to undo by accident

* **The six scored tiers are `correctness > preservation > completeness >
  consistency > writing > formatting`** (2026-10-01), compared
  lexicographically: the first tier whose net is not zero decides the
  comparison. The order is pinned in `BASIS_TIERS`, in the judge directives and
  in the four documents `test_grading_scheme` reads (README, sweeps.md,
  ledger.md, this file's sibling pipeline source); change all of them together
  or none. `writing` above `formatting` is deliberate: layout is pre-normalized
  before the judge sees the view.
* **The champion selection key is `cumulative defect count over the adaptive
  severity_tier_category prefix -> median -> mean -> IQR -> digest`**
  (`champion_sort_key`, `tiebreak_cell_names`, `tiebreak_prefix_cells`): the
  DEFECT PREFIX LEADS the key; the canonical cell order is fatal, critical,
  major, minor -- the SAME four severity rungs the long-form census, the judge
  contract and the score model use (48 cells) -- × the tier priority order ×
  peer/own; the walk stops at the first prefix where the cleanest ranked version
  reaches `tiebreak_defect_floor` (default 10, `setup
  --tiebreak-defect-floor N` / `set-tiebreak-defect-floor N`) or when every cell
  is used; the cumulative count at that prefix is the leading comparator, and
  the panel median (then the mean, the IQR and the digest) is the tie-break
  below it. The incumbent-retention rule OVERRIDES the prefix on an exact
  (median, mean, IQR) tie and keeps the base. NO cross-session deduplication
  is performed by default (`dedup_mode` `off`; mentions are per judge sheet,
  collapsed only per session+version). The OPT-IN `dedup_mode` `location`
  (`setup --dedup-mode location` / `set-dedup-mode location`) merges rows across
  sheets only on the structured key -- the same defect class defined as the
  NORMALIZED CHECK ID the sheet cites (M01/M02/... are examples, never a closed
  set: J1-J5, FMT-* -> M20, the writing-rubric Q ids -> J3, any other id), the
  SAME exact line number parsed from `line N`, and >= 7-word excerpts with
  token-set Jaccard >= 0.8 --
  never merges a row without a parseable line or with a short excerpt, never
  crosses the own/peer boundary, and records every merge in
  `reports/round<r>_dedup_audit.json`. The self-reported
  `critical_remaining`/`writing_remaining` counts are reported and cross-checked
  but never rank.
  `.paper_test/test_grading_scheme.py` (B2) and `test_issue_census.py` pin the
  cell order, the adaptive stop, the files and the rates.
* **Cross-judge conflicts are surfaced, not averaged away** (2026-10-05):
  independent sessions can contradict each other about the same comparison or
  claim, so `run`/`run-decide`/`decide` (and the standalone `conflicts`
  command) audit each round's sheets and write
  `reports/round<r>_judge_conflicts.{md,json}` plus the cumulative
  `reports/JUDGE_CONFLICTS_TODO.md` as REQUIRED MANUAL CHECKS: opposite scores
  for one comparison, a claim one session files as `resolved` and another as
  `introduced`, different numbers quoted for the same claim, and
  clean-vs-findings check dispositions. Every round's judge wave is followed by
  its own audit (two rounds -> two audits; `decide` only back-fills a round
  with no audit yet). The mechanical pass always runs; the LLM conflict pass is
  OFF by default (only `origin: mechanical` rows are written) and runs only for
  an explicit `--conflict-agent[-cmd]` or `PAPER_CONFLICT_AGENT_CMD`. Its answer
  is schema-checked and merged, never trusted blindly. Conflicts are advisory
  for the decision, but the affected
  comparisons' numbers must not be cited until a human has resolved the listed
  checks and re-judged the unsupported session (`retry --run <ID>`).
  `.paper_test/test_judge_conflicts.py` pins the classes.
* **The LLM defect audit is diagnostic; the champion never reads it**
  (2026-10-06): `run`/`run-decide`/`decide` can label every
  `reports/round<r>_defects.csv` row TP/FP (the auditor's schema-checked answer
  lives in `reports/defect_audit_round<r>/audit.json` and
  `round<r>_defect_audit.json`) and write the TP-only file family
  (`round<r>_auditedTP_{defects.csv,issue_census.csv,issue_matrix.csv,
  issue_cumulative.csv,raw_scores.csv,dedup_audit.json}`) plus a second member
  table. It is ON by default with a real agent backend, off for
  manual/custom backends unless `--defect-audit[-cmd]` / PAPER_DEFECT_AUDIT_CMD
  asks for it, and `--no-defect-audit` skips it. The audited aggregation is a
  COPY: `select_champion`, the pin and the winner always read the non-audited
  `agg`, and the non-audited report files are never rewritten by the audit.
  `.paper_test/test_defect_audit.py` pins the schema check, the census re-count
  and that no-mutation invariant.
* **Official templates are AUTHORITATIVE; derived structure is ADVISORY**
  (2026-10-01): `venue_profiles/<id>.official/` holds the journal's own
  Word/LaTeX template files (+ source/license/retrieval manifest) and
  optionally `requirements.json` with extra mandatory sections;
  `venue_profiles/<id>.manuscripts/` holds recent OA exemplars;
  `build-venue-templates` derives `<id>.templates/` with BOTH tiers
  (official: class, mandatory sections, declaration headings; advisory: modal
  order + presence counts), `word-template.md`, `latex-template.tex`, and
  `MANIFEST.json` pinning every input/output (deterministic, no timestamps).
  `add-venue` drives an agent to write the profile + README row + downloads,
  then the CODE derives the pack; `status` prints the pack. The review/rewrite
  prompts embed `venue_architecture.md`, and the code-side conformance rows
  (`work/OFFICIAL_TEMPLATE.md`) name a missing mandatory section, missing
  statement block or wrong class. A requirement the manuscript cannot supply is
  a MANUAL item, never invented text; no prose is copied from an exemplar or a
  template sample; neither tier gates or scores by itself. Transfer sessions
  get the extra clause that the target venue's template REPLACES the previous
  venue's (styles, section names, declarations, reference style). Pinned by
  `.paper_test/test_venue_templates.py`.
* **The read-only evidence areas are SYMLINKED into sandboxes** (2026-10-01):
  each stage sandbox's
  `non_revised/raw_data|raw_figs|human_review_feedback|llm_review_feedback`
  is a RELATIVE symlink to the root's canonical, chmod-protected pristine copy
  (`ensure_pristine_input`), so no sandbox duplicates the evidence. Every walk
  that defines identity/view/input manifests FOLLOWS directory links
  (`_iter_tree_files`, `hash_manifest(..., follow_dir_links=True)`,
  `corpus_dir_manifest`, `corpus_dir_view_files`, the run input manifests and
  `input_mismatches`), `make_tree_writable`/`rmtree_force` never chmod through
  or delete the shared target, and `enforce_readonly_*` verifies a link instead
  of writing through it. Judge views stay per-view COPIES: they anonymize and
  re-name every file, which a link cannot express. A platform without symlinks
  falls back to real copies, reported in the materialization record.
  `.paper_test/test_evidence_symlinks.py` pins all of it.

* **Live Zotero fields are a code-enforced preservation contract** (2026-10-07):
  `paper_docx_format.zotero_field_report` inventories every live field in the
  parts that can hold one (`word/document.xml`, `word/footnotes.xml`,
  `word/endnotes.xml`, headers/footers/comments), both as a complex field
  (`fldChar begin -> instrText -> separate -> result -> end`) and as the
  single-element `w:fldSimple` form, and names their structural faults (an
  unclosed begin, a missing OR duplicate `separate`, a stray field char,
  unparseable citation JSON, a missing/duplicate `citationID`).
  `zotero_field_continuity_problems` compares a stage's DOCX with its base and
  fails the attempt when a field disappears into plain text, every live field
  is removed at once, or a fault is NEW. A bibliography field whose visible
  reference list shrank, and a baseline whose own fields cannot be
  inventoried, are REPORTED with a warning instead of being compared
  empty-to-empty. Documents are paired by
  version-token-free name, and two names that strip to one key are reported
  (never silently collapsed). The formatter's LIVE-FIELD FENCE refuses a repair
  that changes the field signature, and no mechanical text edit (a hygiene
  repair, the redundant-journal-name drop) may rewrite a field RESULT -- Word
  and Zotero regenerate it -- so those rows are reported `fix=style-field` and
  never applied. `setup --zotero off|read|edit|apply`
  only widens or narrows what an AGENT may edit; it never disables the gate.
  The single opt-out is the policy key `unlink_zotero_fields` (submission
  copies). Pinned by `.paper_test/test_zotero_field_continuity.py` and
  `.paper_test/test_audit_gaps_2026_1007.py`.

* **The DELIVERED status carries the champion's own open items** (2026-10-15):
  the revision stages hand their unfinishable work to the author in
  `MANUAL_STEPS.md` and record one disposition per frozen finding
  (`fixed` / `fixed-with-caveat` / `manual-required` / `discarded`), but both
  live INSIDE the producing run's sandbox, which is never delivered. The
  operator's report on the two clean packages was the visible half: the readme
  said CERTIFIED / submission-ready while the champion's own revision had handed
  the author 7 (neohet) and 9 (cnb) `manual-required` items (two Major artwork
  defects, a data/manuscript contradiction), and `DECISION_REPORT.md` pointed at
  `revised/MANUAL_STEPS.md` -- a path inside `runs/<id>/`, which the package does
  not carry. `collect_open_review_items` reads the pin's `produced_by_run`
  ledger, `package_readiness` lists every open row as `REV-1` (an
  auditor-unsupported `discarded` row is `REV-2`), the stage's own hand-off list
  is copied to the SIBLING `final_clean_version.manual_steps.md` (never inside
  the corpus), and the readme + decision report print both. Certification still
  answers only "did the process hold"; the readiness verdict answers "can this
  be uploaded", and `--require-ready` turns these rows into blockers.
  Pinned by `.paper_test/test_review_handoff_2026_1015.py`.
* **The submission is what the package's own README DECLARES (2026-10-15).** A
  package may ship the operator's `README*.md` with the rule for that package:
  "Only files whose names match the following Bash extglob pattern will be
  submitted: `cnb-*-[0-9a-f]{7}.@(docx|pdf)`" (+ `figures/*.png` in the
  NeoHeteroclitic one) and "Submitted files must not refer to any non-submitted
  files". The pipeline's own model of "the submission" was broader (the corpus
  minus the evidence areas, `code/` and the author's READMEs), so a `.tex`/`.bib`
  source or a `supplementary_source_files/…` asset counted as carried while the
  journal never receives it (a dangling pointer PKG-2 would call resolvable), and
  the non-submitted `.tex` sources were scanned as submission documents (their
  own build notes produced rows nobody needed). `declared_submission_set` parses
  the declared extglobs (with `_extglob_to_regex`), honours them ONLY when
  plausible (>= 1 matching file, >= 1 of them a manuscript document) and
  otherwise IGNORES them with a recorded reason -- a mis-parsed glob must never
  turn every scan into "clean". The honoured set narrows the document set and the
  carried-name index of PKG-1/2/3/4/5 + FMT-PDF*/glue/TP1, narrows what
  `journal_submission/` copies, and is recorded in the status readme,
  `journal_submission.json` (`declared_submission_patterns`,
  `not_submitted_by_declaration`) and every session's evidence pack.
* **A display item's declared PRODUCER must agree across surfaces (PKG-5,
  2026-10-15).** The operator's second audit found the NeoHeteroclitic resources
  table claiming "Matplotlib, seaborn (Figures 2, 4 and S2)" while Figure S2's
  own legend ends "Created with BioRender.com" (and the BioRender row claims
  "Figures 1 and S2") -- so the table also takes the credit for the data figure
  the code produced, Figure S3. `display_provenance_rows` reads BOTH sides
  independently (a table row does not start with a display label, which is why
  reading the claim inside a label's paragraph missed every row), takes the
  legend's producer from a capitalised `verb + with/using/in/by + Name` phrase
  (the name half is deliberately case-SENSITIVE: `[A-Z]` inside `(?i)` matched
  lowercase and attributed every legend to the prose after it), and reports one
  row per contradicted (item, table document), naming both sides. It is BLOCKING
  in readiness (the author must say which surface is right) and seeded into the
  review pack + the M31/M35 sweep text; a legend naming the same tool, a legend
  with no producer, and a lowercase participle are all silent.
* **A new root never freezes another root's PIPELINE SNAPSHOT by accident**
  (2026-10-15). `setup` freezes the script that runs it into the root ("THIS copy
  is what every later `run` executes"), so driving a root with its own copy is
  the documented way to run THAT root -- but running an old root's copy to create
  a NEW root freezes two-day-old code: the neohet-12to13 root was set up as
  `python3 <neohet-10to11>/paper_pipeline.py setup --root <neohet-12to13>` and
  every later command then ran commit e15c869, which predated the PKG-2 scan, the
  README rule and the M31-M36 sweeps -- so the "new" package re-found defects the
  origin tree had already closed. `setup` refuses that shape (structural: the
  running file sits directly inside a directory holding a pipeline registry)
  unless `--pipeline-snapshot-ok` asks for it, and records `snapshot_of` /
  `snapshot_origin`; `status` prints which code the root runs and whether the
  origin tree has moved on since (`root_pipeline_staleness`).
* **A name the package carries NOWHERE is a finding too** (2026-10-15, PKG-3).
  PKG-2 covers a pointer at material the package HOLDS outside the submission
  (removable: the material is at hand). The CopyNumBench Methods named
  `data3from2.py` and the NeoHeteroclitic results named
  `neoheterocliticAggregate.py` -- files the package carries nowhere at all, so
  no reader can resolve them. PKG-3 reports them ADVISORY (never gated, never
  removed: the pipeline cannot know whether the sentence should ship the file,
  name a locator, or drop the pointer), scoped to the manuscript PROSE surfaces
  (main text/cover letter/response) and to written pointer verbs, because a
  benchmark appendix that inventories a public pipeline's own file layout
  produced 30 rows before those filters.
* **A cited figure the submission does not carry is PKG-4** (2026-10-15): the
  operator's "Figure S3 is cited and has a legend, but it is not in the
  submission -- `figS3.png` is under `code/out/`". The check compares the labels
  the documents cite with the labels the package's figure FILES carry, names
  where the package actually holds the item, and stays silent when the package
  carries no labelled figure files at all (its artwork is embedded in the
  documents, and a name-based check has nothing to compare against).
* **Hand-off markers are now an operator policy** (2026-10-17). The placeholder
  convention is right for an internal round and wrong for an upload: the
  deadline package's SUBMITTED main text still carried
  `[AUTHOR TO COMPLETE: versions of bedtools, Seurat, cellsnp-lite and UCSC
  liftOver]`, and the NeoHeteroclitic Reporting Summary was six markers and no
  filled form. `--without-author-to-complete` (`set-author-to-complete off`)
  replaces the marker rule in every prompt -- including the four master-prompt
  excerpts and the end-of-prompt reminder that restated the opposite -- with a
  no-marker rule: the missing item is left out of the document, a whole missing
  file is not scaffolded as a document of instructions, and the item is recorded
  in the package's own `MANUAL_STEPS.md`. Under `off`, a marker a stage ADDS
  fails the attempt, a marker still in a delivered package is a gating residual,
  and `package_readiness` names it as `AUTH-1` (under the default `on` it is an
  advisory hand-off and, if the residual gate refuses the decision for it, the
  readiness list now says so too -- the 2026-10-17 audit read
  `submission_ready: true` beside `certified: false -- 6 hand-off markers`).
  The probe session now receives the same rule; it never did before.
  Pinned by `.paper_test/test_manu_sub_audit_2026_1017.py`.
* **An evidence-area file may be referenced only as a display item or through
  the parent's `.tex` closure** (2026-10-17, PKG-10). The operator's rule for
  these packages: files in `raw_data/` (and its siblings) "cannot be referenced
  by the main manuscript", except figures, tables, and files inputted --
  recursively -- to `.tex` files in the area's parent directory (the same
  package's README: "treated as if they are in the parent"). `tex_input_targets`
  / `tex_input_closure` follow `\input`, `\include`, `\includegraphics`,
  `\includepdf`, `\addbibresource`, `\bibliography`, `\pgfplotstableread`,
  `\lstinputlisting`, `\subfile` and `\import` transitively; a figure whose
  BYTES are embedded in a submitted document (the CopyNumBench main text embeds
  `raw_data/Fig3_ploidy_balloons.png` as `word/media/image3.png`) is a display
  item the reader receives. The report and the mechanical strip share the
  exception, so the pipeline no longer deletes a sentence that points at a
  supplementary source the parent `.tex` really compiles.
* **Placeholder FILES are ignored** (2026-10-17). A file can stand in for data
  it does not contain: the operator's example is "the haplotypes in Chisel ACT
  are actually the HG008 haplotypes (placeholders)". Declared placeholders
  (`--placeholder-file GLOB`, `set-placeholder-file`, or a `Placeholder files:`
  line in the package README) and detected placeholder copies (identical bytes
  under two different sample/dataset names, where at least one name is a
  haplotype/variant-style input) are listed in the evidence pack under
  "Placeholder files -- ignored"; no role may use one as a producer, and a claim
  resting only on one is `unable -- placeholder input`. The real partner of a
  DECLARED placeholder stays evidence (declaring the ACT copy must not silence
  the HG008 original).
* **Three package self-consistency scans** (2026-10-17; PKG-11/12/14), each
  from a verified defect in the two packages:
  * PKG-11 -- sibling tables whose headers differ only by case/one character.
    `hpep-v07.b9.p15E…tsv` spelled `MixMHCPred_aff` where the other 26 tables
    spelled `MixMHCpred_aff`; the aggregation skipped any table lacking all
    twelve columns WITHOUT naming it. (That particular exclusion is documented
    in the manuscript and the series is not part of its curated 30 datasets ---
    see the correction bullet below --- but the hazard is real: any future study
    with a one-letter header would vanish from the aggregation silently.)
  * PKG-12 -- a statistics table row whose p-value and its own interval give
    opposite verdicts under the rule the caption states. The CopyNumBench MCB
    table prints AneuFinder/Hap_1/nonintCN_PCC with p = 0.115 beside
    [-0.51, -0.02] while the caption calls both "significantly inferior".
  * PKG-14 -- a cover letter that says the work is not under consideration
    elsewhere / lists no related manuscript while the package carries a dated
    editorial decision for the same title (the iScience decision of 2026-09-29
    in the NeoHeteroclitic package, never mentioned in the 2026-10-01 letter).
  PKG-11/12/14 reach the readiness verdict as blocking findings (one of the two
  statements is wrong and only the author can say which), and the evidence pack
  seeds them for the review/audit/revision arms.
* **M30's negative-claim seed names the RIGHT producer** (2026-10-17). The
  Methods say CHISEL "was not evaluated" on ACT while the ACT table carries its
  rows; the seed reported CHISEL against the germline MCB table (where it WAS
  evaluated) because `table_value_tokens` kept only the first table per token,
  and the session correctly disposed that pairing as a false positive. The token
  now keeps every producer (up to six) and the sentence's own context (the
  table's categorical values, e.g. `ACT`) ranks the matching one first.
* **A "pooled" statistics table must use the pooled units** (2026-10-17, second
  pass; PKG-15). CopyNumBench's `Fig3_ploidy_mcb_pooled.tsv` reports
  `n_units = 9` (the germline donors) for every method while its caption says
  "The first section pools every donor of the four panels (primary)" and the
  manuscript's Supplementary Table S3 pools 21 units (9 donors + 12 ACT
  samples); its means follow its own subset (AneuFinder 69.37 vs 80.94, FLCNA
  54.45 vs 34.58, SCCNV 52.11 vs 27.76). A complete-block restriction is a
  legitimate reason for n = 9, but then the caption and the mean column must say
  so. `scan_pooled_table_mismatches` compares every `*mcb*pooled*.tsv` with the
  sibling `*units*.tsv` (per-method count and mean), quotes the caption, and
  leaves per-panel tables alone; the rows block readiness.
* **A form's software inventory must cover the manuscript's own list**
  (2026-10-17, second pass; PKG-16, advisory). The CopyNumBench Reporting
  Summary lists ~30 tools but omits bedtools, Seurat, cellsnp-lite, Eagle and
  UCSC liftOver, all named in the main text's Software paragraph (the first four
  are exactly the ones the main text still marked as missing versions).
  `scan_form_software_coverage` compares the tool tokens of the `Software.`
  paragraph with the form's text and reports the omissions; a table header
  ("Software and algorithms") is not a software paragraph, and a manuscript with
  no Software paragraph (NeoHeteroclitic keeps its tools in Table 1) produces no
  row.
* **Spelled-out numbers are numeric artifacts** (2026-10-17). The M4 ledger and
  the M30 seed read digits only, so a count written in words escaped both:
  "three karyotype-defined subpopulations", "seven parental antigens", "four of
  the five neural-network outputs", "one row per sequencing run". Those are
  claims a shipped table can prove or contradict exactly like a digit, so
  `word_number_rows` now extracts them into the same ledger (the row keeps the
  author's `written` form and the canonical `number`, and the M30 seed pairs
  them with producer columns like any other count). The context test is
  deliberately conservative: a word is a count before a plural noun (looking
  past adjectives and hyphenated compounds such as "three karyotype-defined cell
  subpopulations"), in "N of the M", before a unit, or in "one X per Y"; pronoun
  and idiom uses ("one of them", "one another", "no one", "at once", "Run two",
  "Patient three") are dropped so the ledger stays a checklist rather than a
  noise source. Pinned by `.paper_test/test_manu_sub_audit_2026_1017.py`.
* **Cross-surface claim checks** (2026-10-17, third pass; PKG-17..24). The
  `Additional_Issues` audit found classes that live between two shipped
  surfaces, so they are now scanned and seeded for the review/audit/revise arms:
  * PKG-17 (blocking) — a required form's "no selection/evaluation overlap" or
    "thresholds fixed before inspection" beside the Methods' "selected
    empirically to match manual karyotyping on the cell-line datasets" (the
    cell lines are in the evaluated 41) or a parameter relaxed because the
    defaults retained no cells.
  * PKG-18 — a prose "X gave the highest average <metric>" recomputed from a
    shipped `method`/`metric`/`dataset`/`mean` grid; advisory when the sentence
    cites a figure whose numbers are not shipped (CopyKAT 0.751 vs Numbat
    0.759), blocking otherwise.
  * PKG-19 (advisory) — a "recovered the N subpopulations" claim with a fixed
    `k = N` and/or the package's own admission that no cluster-to-karyotype
    concordance statistic was computed; the shipped cluster sizes are quoted
    (Ginkgo 7/32/81, HMMcopy one cluster).
  * PKG-20 (advisory) — "SD" defined with two denominators (population over
    datasets in Table S1, sample over antigens in Table 4) and used unqualified
    in the prose.
  * PKG-21 (advisory) — a definition that admits a single term can dominate the
    measure, followed by a comparative inference from it (the NeoHeteroclitic
    G(y) sum of ratios).
  * PKG-22 (advisory) — a claim citing a supplementary note whose closest
    negated sentence says the result must not be read that way (the
    CopyNumBench "purity floor" beside the note's "should not be interpreted as
    demonstrating an intrinsic failure"). It requires a shared non-method
    subject, so an unrelated note limitation is not paired.
  * PKG-23 (advisory) — a "single-cell …" claim whose citation resolves to a
    bulk genome assembly (Nurk et al. cited for single-cell T2T co-sequencing).
  * PKG-24 (advisory) — a caption defining information content as a single
    residue's log-likelihood instead of the expected log-likelihood ratio.
  * PKG-25 — a form's "failures are reported in the deposited result tables
    rather than being omitted" beside a table that omits the failed tool for
    the named cohort (CopyNumBench's ACT panel has no SCYN row) or carries its
    rows with `failed = False` (the 15 CHISEL ACT rows the text says were
    discarded). The omission row is blocking, the unmarked-rows row medium.
  The two blocking classes (form-vs-methods and a bare contradicted ranking
  claim) join the readiness verdict; the rest are claim-quality seeds the
  review/audit must dispose. Pinned by the same suite.
* **The b9 antigen is a documented exclusion, not a dropped study**
  (2026-10-17, second pass; correction). The NeoHeteroclitic Methods state that
  the Zhou et al. p15E series "fails the twelve-column inclusion rule and was
  therefore not assembled into the curated benchmark"; Table 3 lists the six
  studies / 30 datasets actually used. The one-letter header (`MixMHCPred_aff`)
  remains a silent-drop HAZARD and PKG-11 reports it, but no headline rests on
  it.
* **The mandatory form's OWN dataset decides filled-vs-blank** (2026-10-15):
  `xfa_live_packets` resolves the AcroForm's `/XFA` array (objects expanded from
  their object streams, LAST definition wins) instead of guessing from packet
  order or taking the richest packet, so `xfa-export` renders the answers the
  form actually reads, FMT-PDF5 fires when that dataset is empty while an
  unreferenced copy carries answers, and FMT-PDF6 reports a file that carries two
  packet sets -- which is why the same Reporting Summary read as BLANK to the
  operator's audit and as FILLED here. Safe mechanical repairs stay conservative:
  FMT-X2 inserts the missing space after a front-matter label's colon, and the
  fused `<name><address>` token (`Correspondence:Zhen Xiezhenxie@...`) is
  REPORTED, never re-spaced by guesswork. Operating-system by-products (a
  `<name>:Zone.Identifier` download stub, `.DS_Store`, a Word owner file) are
  never documents and are stripped from the published copy with a line in the
  readme. `front_matter_gap_rows` (FMT-TP1) COUNTS AND NAMES the gap when the
  title page does not print the content type this run is configured for -- the
  profile states no such rule, so it is reported as a gap, never as a
  requirement.
* **The delivered package is made CLEAN, not just measured** (2026-10-15). The
  operator's follow-up on the same two packages found the shipped defects still
  in place, because the pipeline REPORTED them and stopped there:
  `figures/figS3.png:Zone.Identifier` (a WSL download stub) inside the neohet
  submission, a top-level `__pycache__/*.pyc` beside it, and `code/README.md`
  narrating its own review round's finding ids and `revised/MANUAL_STEPS.md`
  hand-offs -- the file the PKG-1 rule had named but nothing had removed.
  `is_non_shippable_name` (OS stub / bytecode cache / Word owner file) and
  `readme_internal_note_rows` (a README*.md whose text carries a finding id, a
  stage report name or the "this run / review session" vocabulary) are the two
  predicates; `strip_non_shippable_files_in_dir` and
  `hold_internal_readme_notes` execute them on the DELIVERED copy only, after
  the pin check -- a strip BEFORE it compared 414 files against the pin's 415
  and made `decide` refuse to publish at all (measured on the real root). The
  README that carries the package's own submitted-set declaration stays; the
  session's note is moved to `<root>/reports/readme_notes/` (idempotently, so a
  second `decide` does not accumulate `README.md-2`). The "unchanged" test in
  `publish_final_clean` now compares the two trees' file LISTS, not just their
  content digests, so a hygiene rule that learned a new class republishes the
  package instead of serving the old one. Internal-artifact scanning is no
  longer scoped to the declared submitted set: a file the package carries is
  part of what it hands over, whichever glob its name matches.
* **Two rules for the classes no rule could see** (2026-10-15). `FMT-G4`: a
  comma with no space after it inside a list. `FMT-G3` required lowercase words
  on both sides, so the CNB Reporting Summary's own version list
  (`AneuFinder 1.34.0,copynumber 1.38.0`, `FLCNA 89902690,SCYN eeef200`,
  `CaSpER 0.2.0,CONICSmat 0.0.0.1`) and the supplementary `.bib`'s keyword lists
  (`DNA aneuploidy,Molecular subtyping,Prognosis`) shipped unnoticed; `.bib` is
  now a scanned text source too. `FMT-PDF7`: a submitted PDF that OPENS by
  narrating its own production ("a static rendering of the form's own
  questions ... because the submitted PDF is an Adobe LiveCycle form whose
  static page shows only a viewer placeholder") -- the round's own judge filed
  that sentence against the champion and no delivered surface mentioned it.
  Both rules are tested against the real strings AND against the look-alikes
  that are correct (citation ranges `11,12`, digit groups `684,498`, quantities
  `1,234.5`, citation-key continuations `2020a,b`, initials `AL,Mehling`).
* **A frozen pipeline that contradicts its own record is a WARNING**
  (2026-10-15). `root_pipeline_staleness` compared only the recorded origin
  hash with the origin FILE, so a root that recorded the current
  `paper_pipeline.py` while carrying a four-commits-old copy beside its
  `state.json` read as "frozen, origin unchanged" -- and the neohet package
  shipped three defects the fixed orchestrator would have removed. The frozen
  copy is hashed now (`frozen_differs`), the note says which code the next
  command will actually execute, and `run` and `decide` print it too (it used
  to be `status`-only).
* **A package's statements about ITSELF can contradict each other** (PKG-6/7/8/9,
  2026-10-15, result-driven audit of both delivered packages). Every rule up to
  here compared a surface against itself (a legend against its own figure, a
  reference against its own entry) or against the raw data; the audit found
  three defects that needed two statements compared with each other:
  * **PKG-6** -- the same text both denies generative-AI use and describes the
    AI workflow it used. BOTH packages shipped it, in the cover letter AND the
    methods/acknowledgements ("drafted this manuscript without generative AI,
    except for using GLM-5.2 and GLM-5.3 to recommend journals. After the draft
    was complete, ... a generative AI-based revision workflow ... to refine the
    manuscript"), and a reviewer read the denial as a false disclosure. The
    rule is scoped to ONE text (a denial in the cover letter and a workflow
    description in the Methods are not a contradiction) and stays quiet on
    SCOPED denials -- "no AI tools were used for the statistical analysis", "the
    figures were generated without AI assistance", and the very wording the fix
    produces ("the initial draft was prepared without generative AI"), so the
    rule never flags its own advice.
  * **PKG-7** -- one identifier written at two lengths in the same package: the
    CNB Reporting Summary printed the scRNA commit as 35 hex
    (`c30bc1ab52f083b5761e31bec6888d7f2fd`) while the main text carried the full
    40. The gate is a strict PREFIX relation between two 20+-hex runs in
    DIFFERENT files, so a version string (`1.22.0`), a citation range (`11,12`)
    and an abbreviation (`d7c7790`) are all silent, as are two spellings inside
    one document. The same round found the source of the truncation is upstream
    of the pipeline: the XFA answer carries the full 40 hex, the run's own
    `xfa-export` renders it whole, and the truncated form is what the author's
    answer already contained.
  * **PKG-8** -- the same comparison described with two units of analysis: the
    supplementary captions said "pairwise comparisons used 606-1,989 paired
    cells" while Table S2's own note defined n as "the number of donors whose
    paired differences ... enter the test" (n = 9), so a reader cannot tell
    which analysis produced the values. Both halves are required (a caption
    that states a sample size and names a unit, plus a table note that declares
    n over another unit from a short fixed list), and repeated captions yield
    ONE row per unit pair -- the shipped supplement repeats that sentence 22
    times, and a report that lists one defect 22 times buries the rest.

  * **PKG-9** -- a table names a model TOOL and an AFFINITY quantity that the
    prose never connects: the neohet comparison table labelled `MMP_aff`
    "Affinity (IC50) percentile" -- "Percentile rank of the predicted IC50 of
    the pMHC pair (MixMHCpred)" -- while the Methods define the same column as
    "the percentile rank of the MixMHCpred score against a length- and
    allotype-matched background", and MixMHCpred emits no IC50. The table's own
    NetMHCpan row is the CONTROL (the prose names NetMHCpan and IC50 in one
    sentence), and the rule requires BOTH halves, so well-defined columns stay
    silent. The tool is read from the DETAIL cell's own parentheses -- a first
    cut that paired the row's every token produced six rows for one defect.

  All four are seeded into every session's evidence pack
  (`evidence["contradictions"]`, the "Statements that contradict each other"
  table in `EVIDENCE_PACK.md`) so the review/revise arms can repair the PROSE,
  and reported at publication in the delivered status, `readiness.findings` and
  the console. They BLOCK readiness like PKG-5: one of the two statements is
  false (or the identifier is unusable) and only the author knows which. Pinned
  by `.paper_test/test_contradictions_2026_1015b.py`, including the defect that
  the first cut of the reader carried: a single global 4 MB byte cap silently
  skipped the 4.6 MB CNB main text, so the scan saw a package without its
  manuscript.

* **The probe reads the OTHER direction, and its report must be earned**
  (2026-10-16). Two independent audits of the delivered packages found the same
  shape of defect twice: a submission that ships LESS than it promises (the CNB
  main text citing a supplementary note the declared set does not carry; the
  front-matter obligations the review itself enumerated). The probe — the
  pipeline's cold-context discovery pass — was enumerating surfaces, so it could
  not see a hole. Three changes:
  * a THIRD seeded candidate list, `probe_review/OBLIGATIONS.md`
    (`probe_obligation_rows`): the submitted set the package's own README
    declares, every carried file as submitted or NOT, every written pointer the
    submission makes and where it resolves, and every display item the documents
    cite with no matching file — the completeness direction as a disposal task;
  * the prompt's method gains "RUN THE TWO DIRECTIONS, NOT ONE": the declared
    set vs what the documents depend on, the venue's recorded structure vs the
    sections carried, and the submission's own promises (sections it announces,
    denominators its statistics name, hashes and dates its front matter pins),
    each disposed in `coverage.md` by name;
  * an acceptance floor: an empty or short report must be JUSTIFIED with
    positive evidence, area by area, and the prompt now states the stage's own
    target verbatim ("There are still remaining issues in this manuscript
    submission. Please identify these issues.") with the classes framed as ways
    to look, never as a fence on what may be filed.
* **The length status reaches the author** (2026-10-16). `decision.json` has
  carried the M19 note ("main-text 3726 words OVER-VENUE-LIMIT (inside the
  pipeline's margin)") while the SIBLING `final_clean_version.readme.md` — the
  one document beside the package — did not, so the 2026-10-15b CNB package went
  out at 3,726 words against Nature Biotechnology's own 3,000-word limit with no
  delivered line saying so. The readme now prints the note AND, per section, the
  words against the venue's OWN number with the margin's cap, because the venue's
  number is what the journal enforces.
* **Two PKG-5 / FMT-X2 false positives are closed** (2026-10-16). Both were
  found by the operator's audits and both were the pipeline reporting a defect
  the package does not have:
  * `PKG-5` read a legend ending `... the design-space argument made in
    Results.` as a producer named "Results" and contradicted the resources table
    over it. The producer name is now finalized in `pkg5_producer_name`: the
    name never runs into the next sentence, a sentence-final period is dropped
    (`BioRender.com.` keeps its product punctuation), and a SECTION name is
    refused outright;
  * `FMT-X2` read the shipped three-line correspondence block
    (`* Correspondence: / Zhen Xie / zhenxie@…`) as a glued address, because
    both readers DROPPED the `w:br` between the name and the address. Breaks are
    now a delimiter in `text_of` and `_docx_paragraphs` (one newline, counted in
    every text offset), `visual_text_lines` counts it so a trailing space cannot
    delete the break it sits beside, `rewrite_text_spans` walks both kinds of
    piece in document order and splices the cover ranges at their own offsets
    (a same-length replacement is no longer mistaken for untouched text), and
    `correspondence_glue_rows` folds the break to a space for its checks while
    remembering which spaces the breaks contributed — a real glue still reports,
    and the OLD package's truly glued line still does too.

## Known, deliberate limits

* The **skill packages** (`paper-skills/`) are standalone: their own prose still
  quotes the default profile's numbers as examples, and their
  `references/sweeps.md` M5/M13 carry the Nature Portfolio requirement list. A
  custom venue profile is authoritative when the pipeline runs them; a
  standalone run must follow the target journal's own guide. Extending those
  reference lists into per-venue data is future work, not a code path here.
* The historical **triage ledgers** (`NBT_*_LEDGER.md`) were removed from this
  repository on request; they remain in the git history if an old decision needs
  its evidence (the per-run audit reports a stage writes are unaffected).
* The **defect prefix leads the ranking**, and it is a REPORTED count: a panel
  that under-reports defects (or a version whose sheets filed few ledger rows)
  lowers its own prefix. The panel contract makes a sheet that contradicts its
  own ledger FAIL, and a complete panel is required for eligibility, but neither
  can force a judge to file a row it did not find. The median/mean/IQR below the
  prefix are the cross-check a human reads, and the incumbent rule keeps the
  base on an exact panel-statistic tie. Keep this in mind when comparing
  prefixes across ROUNDS (different panels) -- within one round every ranked
  version is read by the same-sized panel, which is what the prefix assumes.

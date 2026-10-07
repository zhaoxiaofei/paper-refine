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
| `paper_pipeline.py` | the orchestrator (single file, stdlib only). CLI: `setup`, `run`, `run-decide`, `decide`, `status`, `trend`, `agents`, `conflicts`, `selfcheck`, `set-venue`, `set-journal`, `set-article-type`, `set-revision-mode`, `set-tiebreak-defect-floor`, `set-dedup-mode`, `add-venue`, `build-venue-templates`, `retry`, `prune`, `redline`, `track`, `conform`. |
| `paper_docx_format.py` | the optional companion: code-side OOXML style/formatting scan/fix (`scan`/`fix`/`check-pdf`). |
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
python3 .paper_test/run_all.py                 # every suite, offline (20 jobs by default)
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
default-venue text.

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
→ "Revision modes: continue, init, and the journal modes" and pinned by
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
  manuscript text, and `raw_data/` must never appear in them.
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

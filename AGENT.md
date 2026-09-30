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
| `paper_pipeline.py` | the orchestrator (single file, stdlib only). CLI: `setup`, `run`, `run-decide`, `decide`, `status`, `agents`/`sessions`, `selfcheck`, `set-venue`, `set-journal`, `retry`, `prune`, `redline`. |
| `paper_docx_format.py` | the optional companion: code-side OOXML style/formatting scan/fix (`scan`/`fix`/`check-pdf`). |
| `paper_redlines_adapter.py` | optional tracked-changes `.docx` bridge. |
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
   snapshot; legacy `raw_figs/`) and `human_review_feedback/` (the REAL
   editors'/reviewers' comments, plus any previous response as context). Both
   are read-only, not submission content: the converter writes their text to
   `WORK/evidence/` (never `WORK/corpus/`), the code-side scans and the skill
   scripts skip them (and a feedback/response document elsewhere in the corpus,
   by name), and no sweep counts or quotes them as the authors' prose. M30
   reads `raw_data/` as the producer side; the journal modes build the concern
   ledger and the response letter from `human_review_feedback/`; and a JUDGE
   sees both under the labeled `evidence/` directory in its view (raw_data for
   correctness, the human feedback for whether the version addresses the
   raised concerns). `.paper_test/test_raw_data_evidence_area.py` and
   `.paper_test/test_human_review_feedback_area.py` pin the contract. Never
   extend a scan or a packaging step without routing it through
   `is_evidence_rel` / `is_non_manuscript_rel`.

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

# create a root for a specific venue in one step
python paper_pipeline.py setup --source ./non_revised --root ./paper_rounds \
    --venue generic --journal "Journal Name" --article-type article

# validation (see README.md -> Tests for the full list)
python3 -m py_compile paper_pipeline.py paper_docx_format.py
python3 .paper_test/run_all.py -j 8            # every suite, offline
python3 .paper_test/run_one.sh test_venue_config.py
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

`pipeline_config.json` may carry `revision_mode` (one of `none`, `transfer`,
`resubmit`, `major`, `minor`; default `none`) and `journal_feedback` (the
decision-letter files; when unset they are taken from `human_review_feedback/`
first, then a legacy feedback-named file anywhere in the corpus). The four non-default
modes are documented in README → "Journal revision modes (options 1–4)" and
pinned by `.paper_test/test_journal_revision_modes.py`. Two rules matter when
touching this area:

* **Mode `none` is untouchable.** Every journal code path is entered only
  through `journal_mode_of(ctx) != "none"`: the round plan, prompt builders,
  postchecks, `decide`/`status` output and the submission packager must all be
  identical to their historical behaviour when the mode is absent. The J6
  section of the test suite asserts the plan has no journal stage and the
  prompt carries no journal block.
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
  never be rebuilt after a retry (see `.paper_test/test_journal_revision_modes.py`).
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
* **The champion selection key is `median -> crit/fatal -> major -> minor ->
  mean -> IQR -> digest`** (`champion_sort_key`), where each severity rung is
  compared tier by tier in the priority order using the issue census's
  DEDUPLICATED, EXPOSURE-NORMALIZED rates -- peer rate first, own rate second
  (`champion_issue_rungs`). The self-reported `critical_remaining`/
  `writing_remaining` counts are reported and cross-checked but never rank; the
  incumbent-retention rule on an exact median/mean/IQR tie is unchanged.
  `.paper_test/test_grading_scheme.py` (B2) and `test_issue_census.py` pin the
  key, the dedup and the rates.

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

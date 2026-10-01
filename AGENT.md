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
  each stage sandbox's `non_revised/raw_data|raw_figs|human_review_feedback`
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

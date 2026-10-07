# Changelog

## 0.33 — `llm_review_feedback/`: a pre-filtered LLM review is evidence too (2026-10-07)

- **New evidence area.** A setup `--source` directory may carry an optional
  `llm_review_feedback/` sibling of `human_review_feedback/` (any file types)
  with a machine-generated review whose false-positive findings were filtered
  out upstream. The review converter marks it `area: llm_review_feedback`,
  gives it the "LLM review feedback (evidence; false positives pre-filtered)"
  role, never marks it editable, and writes its text to `WORK/evidence/` only —
  no written-surface sweep, word count or file-role row may read it as
  submission prose.
- **Concern standing.** Every remaining LLM finding is a real concern with the
  same standing as a human reviewer's point: the journal modes stage it under
  `feedback/llm/` beside the human feedback, seed it with `origin=llm`, verify
  its quotes verbatim, and answer it in the concern ledger and the response
  letter. It is never dismissed as model noise and never silently dropped; a
  row closed `not-applicable`/`disagree` needs the recorded rationale. A
  corpus whose ONLY feedback is the LLM review still runs the feedback stages.
- **Judges and reuse.** The blind judges see it under
  `evidence/llm_review_feedback/` and judge how each version ADDRESSES it like
  the human concerns. Human-reviewer findings remain filterable through the
  same recorded-rationale route (`not-applicable`/`disagree`), never silently.
- **Mode (option 5) and the off-switch.** `--revision-mode llm` consumes the
  area only (no journal letter, no response letter); when no mode is recorded
  and the area is present, the orchestrator auto-selects it and records it.
  Renaming the area to `llm_review_feedback.disabled` (or `.off`) turns the
  auto-detection off and makes the tree inert -- never read as feedback or
  evidence, never part of the submission, never shown to a judge; the review
  converter skips it entirely.

## 0.32 — live Zotero fields are carried across versions, never unlinked (2026-10-07)

- **Rule E2 continuity.** A version may ADD a field, EDIT a field and DELETE a
  field together with its visible citation text, but it may never delete every
  field at once, leave a field malformed (an unterminated begin, a missing
  separate/end, a stray `fldChar`/`instrText`, unparseable citation JSON, a
  missing or duplicate `citationID`) or replace a field by its visible text.
  A citation/bibliography position that carries plain text where a live field
  is missing is re-created from the baseline package's own
  `citationID`/`itemData`/item URIs; rebuilding a paragraph from its `w:t`
  text is named as the destructive path.
- **Review side.** An unlinked citation (visible number/author-year text with
  no live field behind it) or a malformed field is a preservation/
  field-continuity finding at its exact location, never `OK`.
- The orchestrator enforces the same rule: its format-fix keeps every field
  signature unchanged and every package-producing stage (conform, rewrite,
  revise, integrate) is audited against its base version before the attempt
  can pass.

## 0.31 — tracking copies arrive with the version, and the tracked LaTeX compiles (2026-10-07)

- **Stage-time placement.** The orchestrator now writes a version's
  `<name>.tracking-<baseline>.<ext>` copies (and their `<name>.logging-*`
  fallbacks) BESIDE the documents the moment that stage is accepted --
  rewrite/revise/integrate in `postcheck()`, the template-first stage in
  `template_rewrite/out/` -- instead of waiting for the round to close. The
  round-close pass keeps a fresh entry and only fills in what a stage did not
  write (plus each published winner).
- **The compiled PDF is part of the auxiliary family.** Every tracking `.tex`
  copy that is a LaTeX compile root is rewired to the tracked copies of the
  files it `\input`/`\include`s and `\addbibresource`/`\bibliography`s, and
  compiled into the sibling `<name>.tracking-<baseline>.pdf` (lowercase `\dif*`
  aliases cover `change.case$` BibTeX styles; a fragment compiles through its
  master). An identical pair is compiled too -- its tracking PDF is the clean
  version with its tracked includes. `revision_token.py`/`_is_aux_name` treat
  that `.pdf` exactly like the other auxiliaries, so it can never enter a
  corpus, a pin, a judge view or the version token.

## 0.30 — tracking copies are named for their baseline; no back-compat aliases (2026-10-07)

- **The file name now names WHAT the copy was compared against.**
  `<name>.tracking-<baseline>.<ext>` (fallback `<name>.logging-<baseline>.<ext>`)
  carries an informative `<baseline>` token instead of "previous": `original`
  for the pre-conformed submission, `a1` for the round base, `w<k>` / `a<k>`
  for the version an integration reworked (its own `self/` member), and
  `winner<r>` for the published winner of round r. A reader no longer has to ask
  "previous to what?".
- **No back-compat scaffolding.** The old spellings (`*.tracked.docx`,
  `*.before-after.docx`, `*.tracking-previous.*`, `*.tracking-prev-winner.*`,
  `*.logging-previous.*`, `*.logging-prev-winner.*`, `*.log-previous.*`) are no
  longer recognized as auxiliaries -- only the pattern above is -- and the
  `conform` command's `template` / `author-submission` / `apply-template` aliases
  (plus `agents`' `sessions` alias) are removed.

## 0.29 — difference-tracking auxiliaries renamed, Word-native compare first (2026-10-06)

The revision skill's tracked-changes auxiliary family is renamed to say what it
actually tracks, and the Word-native compare engine becomes the first choice
for producing it:

- The tracked-changes auxiliary is no longer `<name>.tracked.docx` (with its
  `<name>.before-after.docx` fallback): it is
  `<name>.tracking-<baseline>.<ext>` (fallback
  `<name>.logging-<baseline>.<ext>`) for `.docx` (real Word tracked changes),
  `.tex` and `.bib` (a `latexdiff` copy) alike; see 0.30 for the token.
- E5 now names the pipeline's Word-native compare engine
  (`docxcompare.sh` / the `docx-compare` MCP tool wrapping
  `Word.Application.CompareDocuments`) as the FIRST mechanism to produce the
  tracked `.docx`, before any library or raw-OOXML writer. The orchestrator
  writes the sibling `<name>.tracking-original.<ext>` copies itself (against the
  pristine submission), so an agent never has to diff an auxiliary name.

## 0.28 — whitespace/typography artifacts, template-prescribed blanks, embedded-image geometry (2026-10-05)

Two real defects shipped through the 2026-10-04 rounds: a correspondence
e-mail one space to the right of its line (a leading space after `w:br`), a
stray empty paragraph between "2 Materials and Methods" and "2.1 Study design"
-- both invisible to the text-only corpus -- and two supplementary figures
delivered 31% / 16% off their own pixel ratio after the template rewrite.
The M20 family now covers them end to end:

- `paper_docx_format.py` scans `FMT-P4` (a space rendering at the start/end of
  a visual line), `FMT-S8` (a blank line attached to a heading) and `FMT-G1`
  (a doubled article/preposition) as mechanical, and the fixer repairs them
  with recorded text edits (`text_diff_only_recorded_edits` still proves
  nothing else moved); `FMT-S6` (a run beyond `max_empty_paragraph_run`) is
  mechanical too. `FMT-IM1` compares every `wp:extent`/VML size in the
  document AND its headers/footers with the image part's own pixels
  (PNG/JPEG/GIF/BMP/TIFF, stdlib) and restores the ratio from the width.
- **Template-prescribed blanks are never touched.** The pipeline derives the
  venue Word template's own empty-paragraph slots
  (`empty_paragraph_slots`: own/previous/next style signatures) into
  `format_policy_of`, writes them into every session's `format_policy.json`,
  and the scan exempts them and anything before the first non-empty paragraph
  (the spacer the template carries above the title). Only the non-prescribed
  blanks are reported and deleted.
- The reported-but-editorial half (`FMT-P3` doubled spaces / bracket spacing /
  zero-width marks, `FMT-G2` a possible lowercase sentence start, `FMT-G3` a
  missing space after punctuation, `FMT-T10a..T10e` mixed direct fonts,
  paragraph spacing/indentation/alignment drift and a heading-level jump) is
  named in the review sweep, the auditor's new "re-derive the formatting
  state" step, the E9b fix rule, the integration/rewrite rules and the judge's
  M20 sweep; a residual mechanical row is a real defect of the version that
  carries it, and a template-prescribed blank is never a difference.
- A spelling-pair TIE now resolves by the form that occurs first
  (`modelling` x1 vs `modeling` x1), so the mechanical FMT-T8d row is
  clearable; the tie used to make the fixer's self-verification fail and
  silently discard EVERY other repair of that file.
- `ppr_of`/`rpr_of` recognise self-closing `<w:pPr/>`/`<w:rPr/>` (python-docx
  writes the former): the old lookahead treated it as "no properties element"
  and inserted a SECOND `w:pPr` -- invalid OOXML -- which made `docx validate`
  reject the repaired main text and the file keep its defects.
- The template restyle now re-runs the mechanical pass on the restyled package
  (the restyle strips direct spacing, which had silently removed the legend
  spacing the first pass applied).

## 0.27 — the built-in default profile tracks the shipped file; slow test suites split for parallel runs (2026-10-01)

- `_shipped_default_venue_profile()` loads `venue_profiles/<default>.json` at
  import time when the file is present and valid, and falls back to the
  embedded pre-venue literal only for a STRIPPED deployment (script without the
  profiles directory). `add-venue` can therefore update the default profile
  (re-verified numbers, new article types) without the built-in fallback
  drifting behind it; the embedded literal remains the last-resort copy.
- `test_only_rounds_integrators_judges.py` and
  `test_arm_levels_and_language_2026_0922.py` are split into three
  `test_*_N_*.py` parts each with a shared `*_lib.py` harness, so
  `run_all.py`/GNU parallel schedules the independent sections concurrently
  (the first suite: ~450 s serial -> ~240 s wall with the parts in parallel).
  The same pattern applies to any other single-suite bottleneck.
- `test_parallel_scheduling.py` now asserts the SCHEDULING INVARIANT
  structurally (the dependency graph has no barrier on the rewrites; the
  integrations depend on the whole pool) and keeps only generous one-sided
  wall-clock windows, so a loaded box can no longer turn a scheduling bug into
  a false alarm (the previous pairwise-overlap assertions failed under load).
- The venue/length-limit tests follow the re-verified default profile (its
  provenance now cites the journal's own content-types page).

## 0.26 — read-only evidence areas are symlinked into sandboxes, not copied (2026-10-01)

`raw_data/`, `raw_figs/` and `human_review_feedback/` are inputs; every stage
sandbox needed its own copy, and each round materializes ~10 sandboxes, so the
same evidence was duplicated gigabytes at a time. Now:

- each root keeps ONE canonical copy (`<root>/non_revised/<area>`), made
  chmod-protected read-only at `setup` (and re-asserted lazily);
- a stage sandbox's `non_revised/<area>` is a RELATIVE symlink to it
  (`ensure_pristine_input`), idempotent and self-healing like `ensure_copy`; a
  write through the link fails at the filesystem level instead of corrupting
  every sandbox's evidence;
- every identity/view/input walk FOLLOWS directory links
  (`_iter_tree_files`, `hash_manifest(..., follow_dir_links=True)`,
  `corpus_dir_manifest`, `corpus_tree_manifest`, `corpus_dir_view_files`,
  `_entries_in`/`human_feedback_entries`, the run `inputs_manifest` and
  `input_mismatches`, `dir_matches`), so pins, digests, tamper checks and judge
  views still see the evidence;
- the mode/deletion helpers are link-safe: `make_tree_writable` skips symlinks
  (chmod would follow them and strip the store's protection), `rmtree_force`
  unlinks links without descending, and `enforce_readonly_raw_data` /
  `enforce_readonly_human_feedback` VERIFY a canonical link instead of writing
  through it (a link to the wrong target is replaced);
- judge views remain per-view COPIES by design: they anonymize and re-name every
  file, which a link cannot express;
- a filesystem without symlink support (or a permission that forbids them)
  falls back to the old real copies and the materialization record says so.

Pinned by `.paper_test/test_evidence_symlinks.py` (canonical protection, relative
links, inode sharing, blocked writes, fallback, tamper detection, enforcement,
prune-safety and a real stub rewrite run).

Also fixed here while testing `add-venue`: the synthesized/merged README row now
lands at the END of the "Shipped profiles" table (it used to be appended after
whatever table came last in the file, e.g. the schema table), and `add-venue`
warns when it updates a venue that ALSO has a built-in fallback
(`nature-biotechnology`, `generic`): a root without the shipped file keeps the
built-in rules, so the built-in must be synced or the file deleted.

## 0.25 — add-venue publishes from the sandbox; template guidance sections filtered (2026-10-01)

Debug of a real `add-venue frontiers-in-immunology` run (agent rc=0, 10 min,
nothing in the store):

- **Root cause**: the agent runs inside a sandbox whose only writable paths are
  its own directory and /tmp, so the shared `venue_profiles/` store (a parent)
  is read-only to it (`EROFS`). The agent had staged the complete work --
  profile, README copy, `.official/` and `.manuscripts/` -- under
  `<sandbox>/store/` and left a `PUBLISH.md`, but nothing published it.
- **Fix**: the prompt now stages into `./store/` BY DESIGN (store layout), and
  the orchestrator publishes that tree after the session: the profile JSON is
  validated and copied, the venue's README row is merged (UPDATE if present,
  APPEND otherwise, and SYNTHESIZED from the validated profile when the staged
  README only refreshed ANOTHER venue's row for the same journal), and the
  `.official/`/`.manuscripts/` corpora are merged file-by-file. `add-venue
  --publish-only [--from-sandbox DIR]` republishes a completed sandbox without
  re-running the agent (how the recorded Frontiers run was recovered).
- **Template guidance filtered**: journal template files often embed the
  venue's own instructions as sections (Frontiers: "Article types", "Manuscript
  Formatting", "Nomenclature", "Additional Requirements", "Keywords:", "Figure
  captions"). They are no longer mistaken for manuscript sections: a guidance
  denylist plus the statement patterns filter both tiers, mandatory sections are
  computed over the samples that carry a BODY (a supplementary template cannot
  veto "Introduction"), the advisory tier now COMPLETES the official skeleton
  (Abstract inserted before Introduction; one-word variants like "Methods" fold
  into "Materials and Methods"; singular/plural headings dedupe), and
  "Supplemental Data" is recognised as a statement block.

## 0.24 — official journal templates are authoritative; the derived norm stays advisory (2026-10-01)

Many venues publish their own Word/LaTeX template (e.g. Frontiers'
`Frontiers_Word_Templates.zip` / `Frontiers_LaTeX_Templates.zip`). The venue
store now carries them explicitly, with two tiers of authority:

- **`venue_profiles/<venue-id>.official/`** — the journal's OWN template files
  (`.docx`/`.dotx`/`.tex`/`.cls`/`.sty`), unzipped, plus a `manifest.json`
  (source URL, archive, extracted files, retrieval date, license note) and an
  optional `requirements.json` (`{"mandatory_sections": [...]}`) for operator
  overrides. This tier is AUTHORITATIVE: the derived LaTeX skeleton keeps the
  journal's `\documentclass`, the Word skeleton marks the template's mandatory
  sections, and the declaration blocks use the template's own headings.
- **`venue_profiles/<venue-id>.manuscripts/`** — recent OA exemplars, unchanged
  from 0.23, and now strictly the ADVISORY tier: it fills what the official
  template leaves open and can never override it.
- `build-venue-templates` (and `add-venue`, whose prompt now asks for the
  official template archives FIRST) derives both tiers into
  `<venue-id>.templates/` deterministically; `structure.json` carries the
  `official` and `norm` blocks, `venue_architecture.md` prints them in that
  order, and `MANIFEST.json` pins every official file, every exemplar and the
  download provenance. An official-only venue (no exemplars) still gets a pack.
- The review evidence pack now contains a code-side conformance scan
  (`work/OFFICIAL_TEMPLATE.json` / `.md`): missing mandatory sections, missing
  statement blocks (matched by MEANING -- "Conflict of Interest" satisfies the
  "Competing interests" requirement) and a wrong `\documentclass`. It is
  evidence for the review's J5/M20 disposition, never a gate.
- The prompt block gains the two-tier rules and a TRANSFER clause: in
  `transfer` mode the target venue's official template REPLACES the previous
  venue's (old class/styles, section names, declarations, reference style and
  figure conventions are findings to remove), and the humans' concerns from
  `human_review_feedback/` are still answered without a response letter.

## 0.23 — pinned, structure-only venue exemplars and the `add-venue` command (2026-10-01)

A venue can now ship a shared exemplar corpus and a derived template pack:

- `venue_profiles/<venue-id>.manuscripts/` — recently published OA articles of
  the venue (or structure-only Markdown transcriptions of them), populated by
  `add-venue` (an agent downloads them from the venue's own/OA pages, obeying
  robots/ToS/paywalls) or by the operator. They are read ONLY for structure and
  are never treated as submission text.
- `venue_profiles/<venue-id>.templates/` — the DERIVED pack, generated by CODE
  (`build-venue-templates`): `structure.json`, `venue_architecture.md` (modal
  section order with presence counts and mean positions, abstract presence,
  statement placement), `word-template.md`, `latex-template.tex`, and
  `MANIFEST.json` pinning every input exemplar and every output by sha256. No
  timestamps: two builds from the same exemplars are byte-identical.
- The review and rewrite prompts embed `venue_architecture.md` as an ADVISORY
  norm (structure only): follow it where it serves the content, never copy
  prose from an exemplar, never add empty sections to match it, never treat it
  as a gate or score, and the venue's own author guidelines always win. Venues
  without a pack produce byte-identical prompts to before.
- `paper_pipeline.py add-venue <id> [--journal NAME] [--agent …] [--agent-cmd …]`
  drives one agent session that writes/updates `<id>.json` (validated against
  the schema in `venue_profiles/README.md`, every number citing the venue's
  guidelines) and adds its row to that README, downloads 8-15 recent OA
  exemplars + a source/license/retrieval manifest, and is followed by the
  code-side template derivation. `--agent manual` stages the prompt only;
  `build-venue-templates --venue <id>` re-derives the pack without an agent.

## 0.22 — `final_clean_version/` is always generated, with a sibling status readme (2026-10-01)

The 0.21 rule ("publish the clean package only for a certified champion") is
replaced at the operator's request: the champion corpus is materialized on
EVERY `decide`, certified, provisional or refused, so the workflow never loses
the package — and the certification verdict travels in a SIBLING markdown file
that can never become manuscript content:

- `<root>/final_clean_version/` is rebuilt (or left untouched when byte-identical
  to the expected tree) regardless of the exit code; the only reasons it is not
  built are missing content (no winner/pin on disk, an empty corpus, a pin
  digest mismatch, an after-increment filename collision), and those are
  recorded as `skipped_reason` in `decision.json` and in the status readme;
- `<root>/final_clean_version.readme.md` is written by every `decide`: the
  certification verdict (CERTIFIED / PROVISIONAL / NOT CERTIFIED), the blockers
  and notes, the champion and pin digests, this decision's exit code, the
  package's file/digest/renamed/raw-data counts, and the reuse hint
  (`setup --source …`) or an explicit "do not treat this as a certified answer"
  warning. It is deliberately a SIBLING: anything written inside the directory
  would become manuscript content in the next run;
- `certification.clean_version` in `decision.json` now records
  `{published, status, readme, skipped_reason}`, the DECISION_REPORT prints the
  published/skipped line with the readme name, and `decide` prints the readme
  path on every run.

## 0.21 — one certification verdict, and the clean package only for a certified champion (2026-10-01)

The "only for a certified champion" half of this entry was superseded by 0.22
the same day; the certification verdict itself stands.

Found while auditing the recorded `cnb-20to21-*` run: `decide` printed
"final clean version … ready as `setup --source …`" and THEN exited 5 with
"the champion is NOT certified" -- the residual/format gates were evaluated
after `final_clean_version/` was published, so an uncertified run could hand the
operator a package it had just refused to sign.

- `decide` now computes ONE `certification` verdict
  (`decide_certification()`): `certified` / `provisional` / `blockers` /
  `exit_code` / `clean_version`. `decision.json` carries it, `DECISION_REPORT.md`
  prints it right under the header, `status` and `trend` surface it, and the
  process exit code (5 blocker, 4 provisional under `--require-complete`, 0
  otherwise) reads from the same object — the file, the report and the exit can
  no longer disagree.
- `final_clean_version/` is published ONLY for a certified champion: the
  residual/format gates and the plain-language anti-regression failure were
  missing from the publication reason and are now included. A pre-existing
  directory from an earlier decision is never overwritten by an uncertified run
  and the run prints a NOTE saying it was not refreshed.
- `trend` gains a `certified` column on the per-run table (`-` for decisions
  written before the block existed), and `status` prints the verdict.
- The residual gate's message now says what to do when the environment is
  offline (the recorded run's lookups were all `skipped`): write the verified
  fact/negative into the document, run the lookups where the network is
  reachable, or record them as advisory with `--non-residual-gate`.
- README: the beginning is now at-a-glance (what you give it / what it produces
  / the default plan), quick start, what lands in the root, an `Everyday
  commands` table, a "Is my decision certified?" section, requirements, and the
  two read-only evidence areas.

## 0.20 — the defect prefix leads the ranking; the four severity rungs stay separate (2026-10-01)

- **The champion selection key is now
  `cumulative defect prefix -> median -> mean -> IQR -> digest`** (it was
  `median -> prefix -> mean -> IQR -> digest`): the number of defects the panel
  attributed to a version is the most direct improvement signal and the leading
  comparator; the panel median, mean and IQR are the TIE-BREAKS below it. The
  incumbent-retention rule is unchanged and OVERRIDES the prefix: an exact
  (median, mean, IQR) tie still keeps the incumbent base even when a challenger
  carries fewer defects. `score_model_doc`, the trace, the report, the CLI help
  and the tests all state the new order. A root whose rounds were DECIDED under
  the previous key re-derives a different ranking on `decide` and reports a
  recomputed-champion mismatch (exit 5) -- that is the decision-verification
  layer working as intended: re-run the affected round under the new key, or
  keep the old `decision.json` as the record of the old calibration.
- **The 0.19 top-rung merge is REVERTED for consistency**: the
  `severity_tier_category` lattice is 48 cells again --
  `fatal`, `critical`, `major`, `minor` × the tier priority order ×
  peer/own -- so the lattice, `round<r>_issue_matrix.csv`,
  `round<r>_issue_cumulative.csv`, the long-form census, the judge contract and
  the score model all speak the SAME four severity rungs, with `fatal` first
  and `critical` second. (The 0.19 rationale is kept in the history above; a
  codebase with two severities vocabularies was the heavier cost.)

## 0.19 — the top two severity rungs merged in the tie-break lattice; location dedup classes are open-ended (2026-10-01; the merge was reverted by 0.20 the same day)

- **The adaptive defect-prefix walk now merges `fatal` and `critical` into one
  `critical_or_fatal` level**, so the `severity_tier_category` lattice is 36
  cells (`critical_or_fatal` -> `major` -> `minor`, tier in the scoring priority
  order, peer before own) instead of 48. The compared number is an unweighted
  count, so fatal vs critical only moved WHERE a defect entered the walk; the
  two are the hardest pair for a judge to separate, the scoring contract
  already groups them at the `|score| = 4` rung, and no recorded real round has
  ever filed either rung (0 of 8,541 ledger rows across the ten real roots), so
  the merge changes no recorded verdict while removing a classification wobble.
  The long-form `round<r>_issue_census.csv` still reports all FOUR severities
  (audit fidelity); only the matrix/cumulative files and the prefix walk merge
  them, and the fileA/cumulative columns are now
  `critical_or_fatal_<tier>_<peer|own>`.
- **The structured-location dedup's defect class is the NORMALIZED CHECK ID,
  whatever the sheet cites**: `M01`, `M02`, ... are examples, never a closed
  set. `J1`-`J5` are their own classes, `FMT-*` normalizes to `M20`, the
  writing-rubric `Q` ids to `J3`, and any other id is its own class; a row with
  no check id still never merges. The judge-side ISSUE-LOCATION RULE says the
  same, so nobody reads it as "numeric ids only".

## 0.18 — the OPT-IN structured-location dedup (2026-10-01)

Cross-sheet deduplication stays OFF by default; the new mode is a prototype the
operator must switch on:

- `setup --dedup-mode off|location` (config key `dedup_mode`) and
  `set-dedup-mode off|location [--show] [--force]` on an existing root. `off`
  (the default) counts every judge sheet's row as a mention, exactly as 0.17
  did; `location` merges rows ACROSS sheets when BOTH rows carry the same defect
  class (the normalized check id; `M01`/`M02`/… are examples, and `FMT-*`
  normalizes to `M20`),
  the SAME exact line number parsed as `line N`, and excerpts of at least 7
  words whose token-SET Jaccard is >= 0.8 (`DEDUP_MIN_WORDS`,
  `DEDUP_FUZZY_THRESHOLD`).
- The conservative direction is structural: a row without a parseable line
  number, or with a shorter excerpt, is NEVER merged; a merge never crosses the
  `own`/`peer` boundary (each source stays normalized by its own
  opportunities), and the merge is attributed to the first-kept row's tier and
  severity.
- Every merge is audited in `reports/round<r>_dedup_audit.json` (version,
  source, session, class, line, excerpt, the kept session and its excerpt);
  the census CSV gains `raw_own`/`raw_peer` (what the sheets filed) and
  `merged_own`/`merged_peer` (what the mode merged away) beside the effective
  `own`/`peer`, plus the `dedup_mode` column. The file is written in both modes
  (an `off` round carries zero merges) so the report shape is stable.
- The judge prompt gains the ISSUE-LOCATION RULE (name the line number as
  `line N`, quote >= 7 words of the affected text) ONLY in `location` mode: the
  default prompt is byte-identical, and the rule only makes the rows
  machine-locatable. On the recorded round-1 sheets (no `line N` anywhere) the
  mode merges zero rows, i.e. it changes nothing until a run's judges are asked
  for the location.

## 0.17 — the adaptive defect-prefix tie-break, and no cross-session dedup (2026-10-01)

The selection tie-break is now an **adaptive defect prefix** instead of a
per-severity rung comparison:

- the cells are the canonical `severity_tier_category` order:
  `fatal_correctness_peer, fatal_correctness_own, fatal_preservation_peer, …,
  minor_formatting_peer, minor_formatting_own` (severity fatal→critical→major→
  minor, tier in the scoring priority order, peer before own);
- walking that order, each ranked version's reported defect counts are
  accumulated and the walk **stops at the first prefix where the version with
  the FEWEST defects reaches `tiebreak_defect_floor`** (default 10;
  `setup --tiebreak-defect-floor N` / `set-tiebreak-defect-floor N`) or when
  every cell is included;
- the **cumulative count at that prefix breaks a median tie** (fewer is
  better); the arithmetic mean is consulted only when those cumulative counts
  are equal, then IQR, digest and id. The incumbent-retention rule (an exact
  median/mean/IQR tie keeps the base) is unchanged.
- **No cross-session deduplication is performed.** Matching rows across judge
  sheets by their evidence text was a noise source of its own (reworded
  duplicates missed, boilerplate could over-merge), so the counts are the
  mentions each sheet actually filed; the ONE collapse kept is per (session,
  version) — a judge sheet that repeats the same row across its opponent
  comparisons counts it once. The `dedup_*` columns of 0.16 are removed; the
  exposure-normalized `own_rate`/`peer_rate` stay (computed from the reported
  counts).
- two files sit beside `round<r>_issue_census.csv`: `round<r>_issue_matrix.csv`
  (**fileA**: rows = versions, columns = the cells in canonical order, values =
  reported counts) and `round<r>_issue_cumulative.csv` (the prefix sums of the
  same rows and columns). `score_model_doc()`, `DECISION_REPORT.md` and the
  round table document the new key.

## 0.16 — calibration: the scoring priority order, and a panel-derived selection tie-break (2026-10-01; the tie-break and the dedup columns were superseded by 0.17 the same day)

Two calibration changes, both requested after reviewing the round-1 census of a
real run (`reports/round1_issue_census.csv`: `peer` totals are several times the
`own` totals because a version is the target in only its own judges' sessions
but an opponent in every other version's):

- **The scoring priority order is now `correctness > preservation > completeness
  > consistency > writing > formatting`.** Correctness stays first (the truth of
  what is asserted), but lost content (preservation) and missing deliverables
  (completeness) now outrank the residual `consistency` class (the same thing
  said/spelled/numbered two ways; meaning changes are refiled to correctness),
  and prose whose meaning survives (writing) outranks purely mechanical layout
  (formatting) -- the latter is pre-normalized before the judge sees the view,
  so a length row can never outweigh a prose defect.
- **The champion selection key is now `median -> crit/fatal -> major -> minor ->
  mean -> IQR -> digest`**, where each severity rung is the TOTAL defect count
  across ALL TIERS of that severity (a per-tier count is deliberately not a
  sub-rung: small counts fluctuate too much to rank on) and reads the
  EXPOSURE-NORMALIZED, DEDUPLICATED census rates: peer rate first, own rate
  second (a version is the target in only its
  own judges' sessions but an opponent in up to 7x as many), counts deduplicated
  across sessions per source by an EXACT normalized evidence key (never a fuzzy
  match, so two different defects can never be merged). The self-reported
  `critical_remaining`/`writing_remaining` counts are still recorded and
  cross-checked but no longer rank; the incumbent-retention rule (an exact
  median/mean/IQR tie keeps the base) is unchanged. The census CSV gains
  `dedup_own`/`dedup_peer`/`dedup_total`, `own_rate`/`peer_rate` and
  `own_opps`/`peer_opps` columns; `score_model_doc()`, the decision report and
  the round table document the new key.
- The judge prompt now spells out how to use the evidence areas for these
  classes: `raw_data` for value/label/cohort consistency (data-vs-written) and
  as the reference that proves a dropped claim was real (preservation), while
  the drop itself must be shown from the two packages.

## 0.15 — `human_review_feedback/` is a first-class evidence area, visible to judges (2026-10-01)

Real editors'/reviewers' comments no longer live inside `raw_data/`: the corpus
carries them in their own top-level `human_review_feedback/` directory, a
sibling of `raw_data/`. Both are EVIDENCE areas with the same byte-for-byte,
never-renamed, never-submission contract, and both are visible to a judge —
clearly labeled, so the prompt's evidence rules stay enforceable:

- the review converter marks the area `area: human_review_feedback` (role
  "human review feedback (evidence)"; a `response_to_reviewers.*` file there is
  "previous response (evidence context)"), writes its text to `WORK/evidence/`,
  and never sweeps it; the pipeline's written-surface scans skip both evidence
  areas AND any feedback/response document kept elsewhere in the corpus (by
  name), so M18/M19/M20/M4/J3 seeds no longer count a reviewer letter as a
  manuscript document; the skill scripts (`extract_numbers`,
  `extract_citations`, `extract_occurrences`, `enumerate_conventions`,
  `extract_acronyms`, `count_words`) carry the same guard;
- the four journal modes take their concerns from `human_review_feedback/`
  first — any file name, including non-English ones — with the legacy
  feedback-named file under `raw_data/` still detected; previous responses are
  CONTEXT (`feedback/previous_responses/`), never concerns and never the
  letter;
- the JUDGE view keeps both areas under stable `evidence/raw_data/` and
  `evidence/human_review_feedback/` directories (file names inside remain
  anonymized). The judge prompt now says how to use them: `raw_data/` for
  correctness/completeness, the human feedback to score how well each version
  ADDRESSES the raised concerns (a concern the target fails to answer that an
  opponent answers is a completeness difference; correctness when the text
  claims to answer it). The feedback is identical in every view, so only the
  manuscripts' handling of it can differentiate them.
- the read-only contract is enforced for the new area too
  (`READ-ONLY human review feedback:` warnings; restore/drop from the pristine
  copy, modes preserved), the submission package strips both areas, and
  `raw_data_advisories` reports deviations in either;
- audit fixes in the same pass: retry/rebuild of the journal stages now knows
  their dependency chain (`upstream_deps`), so a scoped round recovers cleanly;
  `setup --venue-profile FILE` installs a brand-new venue on a fresh root (the
  old error pointed at `set-venue`, which needs an existing root);
  `--journal-feedback` accepts CWD-relative paths; the duplicated
  `is_raw_data_rel` definition is gone; the stale "rounds (default 2)" text is
  fixed; the length/caption wording now matches the lexicographic engine (a
  length row can decide only against a WRITING-tier difference); and the
  artifact `tier` (finding/advisory) is documented as distinct from the judge's
  six scoring tiers.

## 0.14 — the four journal revision modes (2026-10-01)

A root can now be driven against a REAL decision letter instead of the
pipeline's own review rounds (`setup --revision-mode …`, `set-revision-mode …`,
`--journal-feedback`, `--journal-feedback-from`):

- **option 1 `transfer`** — revise for a NEW journal from another journal's
  feedback; NO response to reviewers; rewrites allowed;
- **option 2 `resubmit`** — new submission to the SAME journal; response to
  reviewers required; rewrites allowed;
- **option 3 `major`** and **option 4 `minor`** — complete a major/minor
  revision at the same journal; response required; rewrites forbidden; the
  manuscript is edited ONLY where a concern requires it, so the general
  review–audit–revise workflow does not run (the plan is
  `concerns → single scoped revision → response → journal_submission/`).

A new stage family does the work: the feedback stage copies the decision
letter into `feedback/` (byte-for-byte originals + text renderings) and
enumerates it into `concerns/JF_concerns.json|md` (one row per distinct
concern, verbatim quotes checked mechanically, `action` + `disposition`); the
modes 3–4 concerns stage also writes the ONLY finding list the single revision
session sees (`check: "JF"`); the response stage writes the point-by-point
letter (`RESPONSE_TO_REVIEWERS.md` + `response_map.json`, every cited change
file verified against the package, `planned` rows forbidden from claiming
results); and the finalizer assembles `<root>/journal_submission/` — the
submitted documents only, with `raw_data/` (evidence) and the pipeline's
bookkeeping excluded, plus the response letter and, when the round generated
them, the marked-up copies under `tracked_changes/` (generated against what was
submitted). The major/minor path is guarded mechanically
(`scoped_scope_problems`): a changed file the revision ledger does not name, or
any added/removed file, fails the attempt.

The default mode is `none` and the historical pipeline is unchanged there —
the journal stages never appear in the round plan, the prompts carry no journal
block, and `decide`/`status` behave exactly as before.
`.paper_test/test_journal_revision_modes.py` pins all four modes plus the
mode-`none` regression.

## 0.13 — raw_data is the EVIDENCE area, never submission content (2026-10-01)

An operator corpus carries `raw_data/` next to the submitted documents (main
text, cover letter, supplementary information), with its data tables, figure
sources, the analysis snapshot — and the editors'/reviewers' feedback the
authors received (e.g. `raw_data/iScience_feedback_from_reviewers_and_editors.txt`).
The pipeline always knew the area is byte-immutable; it did not know it is also
not a submission document, so its text could be swept as the authors' prose
(the feedback letter defaulted to the "main text" context in M1, a data table's
file name could be read as "main text"/"cover letter"/"supplementary" by the
role classifier, and the code-side M18/M19/placeholder/number/document-set
scans read its files too). That is now fixed end to end:

- `paper-review/scripts/convert_corpus.py` gives every `raw_data/` (legacy
  `raw_figs/`) file `area: raw_data`, no document role, `editable: false`, and
  writes its converted text to `WORK/evidence/` — never `WORK/corpus/` — so no
  submission sweep can read it. Feedback-named files are labelled
  "reviewer/editor feedback (raw-data evidence)".
- `extract_acronyms.py` (M1/M1b) skips evidence files explicitly and names them
  in the artifact header; `count_words.py` refuses a raw-data/feedback path
  instead of counting it as main text or a cover letter.
- `SKILL.md`, `references/sweeps.md`, the fallback prompt and `paper-revise`
  state the rule: the evidence area is never a sweep input, a word count, a
  document role or a finding quote; M30 alone reads it, as the producer side,
  and editors'/reviewers' feedback is external prose that is never attributed
  to the authors.
- `paper_pipeline.py`'s code-side scans (M18 captions, M19 lengths, OOXML
  formatting, placeholders, number provenance, document-set comparison) and
  `paper_docx_format.py`'s directory expansion skip `raw_data/`; the shared
  prompt block now says the area is not submission content.
- `.paper_test/test_raw_data_evidence_area.py` pins the whole contract.

## 0.12 — one-sided small differences are scored, and the layout budgets are measured (2026-09-30)

An operator review of a crowned winner found defects the rubric let through, so
both the *prose* floor and the *layout* budget were made explicit and, where a
file can prove it, code-checked:

- **Small differences are real differences when ONE side is worse** (Q1–Q12 of
  the shared writing rubric): a single less precise, idiomatic or academic
  word/verb/connector, a missing transition, a punctuation or grammar slip, or a
  paragraph that opens with a bare new-topic assertion is a finding; a difference
  where BOTH readings satisfy every item stays cosmetic ("different" is not
  "worse"). Character spacing, blank lines and line/paragraph breaks are M20
  formatting rows, never prose rows, and a LaTeX macro argument is not an
  unexplained prerequisite.
- **The abstract margin is +10%** (150 → 165 words) in the shipped
  nature-biotechnology profile and everywhere the limit is quoted.
- **The cover letter's TOTAL content is capped at 650 words by default**
  (`cover_letter.total_max`; salutation, body, disclosures and signature all
  count), separate from the 300-500 persuading-part preference; over the cap
  the fix trims boilerplate first, never a claim about the work.
- **Layout budgets are part of the delivered artifact**: the front page must
  hold the title, authors, affiliations, abstract AND keywords together, and the
  cover letter must render to at most two pages (both decided by a render, never
  by the cached `docProps/app.xml` count). The code-side M20 scan reports the
  front-page split from Word's own `w:lastRenderedPageBreak` record
  (`FMT-T8g`), sibling indentation drift (`FMT-T8f`) and an over-budget cover
  letter when a render or the cached count shows it (`FMT-T8h`).

## 0.11 — M30: the source hierarchy becomes a detection rule (2026-09-29)

The hierarchy (github code > data in `raw_data/` > main figures > … >
supplementary text) was stated only as a RESOLUTION rule: it decided which side
wins once two sources already disagreed. A written number, sample size,
parameter or label that the shipped code or raw data contradicted was found
only when a human happened to compare the two — even though every session's
corpus already carries its producers (the analysis code, the raw-data
snapshot, the figure/table sources). The review → audit → revise path now
carries the DETECTION side as **M30**:

- `paper-review/references/sweeps.md` gains **M30 — source-hierarchy
  reconciliation** (purpose · enumeration · artifact · finding rules):
  enumerate every operational or quantified written item, pair it with its
  producer, file one finding per incompatible instance with BOTH sides and the
  authoritative one per the hierarchy, and record
  `unable — the producer is not in the corpus` instead of a silent clean. The
  coverage table, the finding format and the discovery numbering (proposals now
  start at **M31**) move with it.
- `paper_docx_format.py` gains the seed: `table_column_stats` (each shipped
  table column's own row count and min/max/mean/sum),
  `hierarchy_seed_rows` (every written number the shipped tables do NOT prove,
  paired with its candidate producer column and the check the code can make —
  including a cohort-size sentence against the table's own row count) and
  `code_literal_rows` (module-level code/config literals such as
  `N_SAMPLES = 15`), all bounded and only on claim-bearing surfaces. The
  pipeline seeds them as `review/artifacts/M30_hierarchy_reconciliation.md`
  (a decision table) and as `work/M30_hierarchy_reconciliation.md` in the other
  layouts.
- The auditor attacks the old closures ("the code is out of scope",
  "`raw_data/` is read-only", "not in the written parts");
  `paper-revise/references/edit_rules.md` gains **E12** (align the WRITTEN side
  with the authoritative producer; rule C owns a code fix; `raw_data/` is
  read-only and stays a manual decision); the rewrite and integration prompts
  surface/resolve the conflict under the hierarchy without ever editing the
  code to make the text true.
- The judge's frozen coverage map is unchanged (M1–M24 + J1–J4); its prompt now
  states explicitly that a claim the package's own code/data refutes is
  scoreable `correctness`/`completeness`, never cosmetic.

## 0.10 — both directions of every two-sided check (2026-09-29)

The checklist was one-sided: J3 filed overclaims (unsupported first/novel
claims, causal language over a correlation, a generalization past the tested
conditions) and the same "too strong" reading ran through the other paired
classes, while the mirror direction was invisible. An UNDERCLAIM — a supported
result hedged into "may"/"could"/"suggests"/"a trend"/"preliminary", a
limitation written as a retreat, an advance left unstated — was never a
finding, and the other pairs (`M5` items present but unneeded, `M21` a letter
claim below the manuscript's evidence, `M22` an availability statement weaker
than the verified locator, `M29` a printed field the caption never describes, a
document ADDED rather than lost, length compression allowed to strip
meaning-bearing hedging) were unchecked in exactly the same way. This release
makes every pair symmetric:

- **J3 is claim calibration** (overclaiming AND underclaiming), with the fix
  allowed to run only as far as the evidence goes; the class table, J1, J2
  (precision both ways) and the `sweeps.md` preamble carry the both-directions
  rule once, and every finding must cite the evidence that fixes the
  calibration.
- A new code-side ledger `claim_strength_rows` (`paper_docx_format.py`)
  enumerates one row per claim-bearing paragraph per direction (`under` =
  hedges, `over` = maximal claims), seeded as
  `review/artifacts/CLAIM_STRENGTH.md` (a decision table under the
  strict-artifacts policy) and `work/CLAIM_STRENGTH.md` for the other layouts.
  The code cannot decide the calibration — it guarantees the quiet direction is
  enumerated too, and a hedge the evidence requires is an `OK` row.
- `paper-revise`'s E1/E3/E6/E11 and both standalone prompts state the mirror
  fixes: a calibration finding authorises the edit in the direction it names
  (never past the evidence), an availability statement is corrected toward the
  verified locator in both directions, an M29 finding is fixed by adding the
  missing description as well as by removing a false promise, and compression
  may remove only hedging that carries no meaning.
- `paper_pipeline.py` carries the rule in the shared decision block (D1), the
  defect-class vocabulary, the writing rubric (Q1) and the language pass (L1);
  the judge prompt states that a weakened supported claim is `introduced`
  correctness, never neutral caution; the M5/M21/M22/M27/M29 prompt text and
  `document_set_check` (added documents) carry their reverse directions; and
  the review's disposition mandate lists the `CLAIM_STRENGTH.md` rows.

## 0.9 — the rewrite-parity checks (2026-09-28)

The pipeline's judged rounds showed that a from-scratch rewrite (w1/w2) often
outscored the review-audit-revise arm (a2) on consistency/completeness rows the
frozen review never filed: US/UK spelling conventions, SI-legend-vs-artwork
term splits, claim→evidence pointer coverage (S12-only for a two-sample claim),
sibling definition order (`MALBAC-sequenced (multiple annealing …)`) and
scope-level organization. Those classes were visible to a rewriting session
and invisible to the instance-level review, so the revision arm had nothing to
fix. This release makes the review -> audit -> revise path do the rewrite's
enumerative work:

- `paper-review/references/sweeps.md` gains **M25–M29** (figure-artwork/text
  parity · house-style/orthographic conventions · claim→evidence coverage ·
  sibling-definition symmetry · caption-promise vs printed-schema parity) and
  **J5** (the architecture/rewrite-class pass, one row per scope in
  `review/ARCHITECTURE.md`, findings carrying a `scope` key); M1(a) now states
  that an acronym-first compound is "used before it is defined" and that "it is
  a proper name" is not a disposition when the sentence itself prints the
  expansion; J5 findings are the one deliberate exception to the
  one-verbatim-instance finding shape.
- New bundled script `paper-review/scripts/enumerate_conventions.py`: the M26
  occurrence ledger (curated US/UK spelling, hyphenation and preverb families
  plus data-driven candidate pairs) and the `STYLE_CONVENTIONS.md` decision
  table it never fills itself.
- `paper-revise/references/edit_rules.md` gains **E11**: M25–M29 are resolved by
  aligning the EDITABLE surface corpus-wide (a read-only artwork file does not
  make a term mismatch manual when the caption/text/SI legend is editable), and
  J5 licenses SCOPED restructuring (reorder/split/merge/transition edits inside
  the finding's declared scope) under a content freeze, a numbering check and
  one `WORK/RESTRUCTURE_<finding-id>.md` artifact per finding.
- `paper_pipeline.py`'s review/audit/revise prompts carry the new checks, the
  review's coverage contract requires M25–M29 + J5 with their artifacts (and a
  disposed `review/ARCHITECTURE.md`), the auditor attacks the dispositions that
  closed these classes (M1 name-bar rows, "artwork is read-only", per-document
  convention rows, unfilled architecture tables), and the revise postcheck warns
  when the convention re-run / restructuring notes are missing. The judge
  panel's frozen coverage map (M1–M24 + J1–J4) is deliberately unchanged:
  identical minimum scrutiny across versions is what keeps it calibrated, and
  the comparison already scores these differences in the
  consistency/completeness/correctness tiers.
- Discovery proposals now start at **M30**; both standalone prompts carry the
  updated check lists, the E11 rule and the resynced appendices.

## 0.8 — any venue, any journal (2026-09-25)

The skills no longer assume Nature Biotechnology. `paper_pipeline.py` gained a
configured VENUE (a rule set, selected with `set-venue <id>` / `setup --venue`)
ARTICLE TYPE (the venue's content type -- `set-article-type <id>` /
`setup --article-type`, since a venue's word limits belong to the type: Article,
Brief Communication, Review, Resource, ...) and JOURNAL (`set-journal <name>`),
all recorded in the root's `pipeline_config.json` and mirrored into
`state.json`; the venue's content types and numbers live in
`venue_profiles/<id>.json` (schema and worked examples in
`venue_profiles/README.md`), and a type the profile carries no numbers for is
counted and named from the venue's own table instead of inheriting another
type's caps. Nature Biotechnology stays the DEFAULT profile, so every number
quoted in these skills is still the default Article's.

What changed here:

- both SKILL.md files and both standalone prompts state the venue/journal rule
  up front and read their limits, provenance and guidelines source from the
  profile of the run instead of asserting Nature Biotechnology;
- `references/sweeps.md` M18/M19 now say "the target venue's" rule, with the
  Nature Biotechnology numbers marked as the default profile's, and M5/M13 stay
  the default profile's requirement list (a custom profile is authoritative
  when the pipeline runs the skill);
- `paper-review/scripts/count_words.py` gained `--venue-profile FILE`: the caps,
  the margins and the cover-letter preference come from the profile, and a
  profile that declares no limit yields counts with `cap: null` (never "over
  the cap");
- the journal hits that remain in these files are examples or the default
  profile's own provenance, and the pipeline's prompts name the configured
  journal/venue instead.

## 0.7 — content-hash version tokens (2026-09-19)

The operator replaced the letter/digit version-token increment with a
content-derived version ID. `paper-revise`'s R2 now says: give each revision
package ONE 7-character version token, printed by the new bundled tool
`scripts/revision_token.py` — the first 7 hex characters of SHA-256 over the
sorted content digests of the package's payload files (the skill's own reports,
the `.tracked.docx`/`.before-after.docx` auxiliaries and `work/` are excluded;
file NAMES do not enter the hash). Existing version-token references inside file
contents are normalized to `<VERSION>` before hashing, so applying the token
never changes it; the tool's `--verify TOKEN` proves that after the rename and
the reference repointing. Every editable document carries the token: an existing
trailing token is replaced (`-a.docx` → `-<token>.docx`, `manuscript_v2.tex` →
`manuscript_<token>.tex`) and a name without one gets it appended (`refs.bib` →
`refs-<token>.bib`). Letter/digit INCREMENTS are withdrawn; the only other
rename is the `_rev2` collision fallback.

`paper_pipeline.py`'s revision, rewrite and integration directives carry the same
rule; the pipeline recognises 7-hex tokens when matching documents (legacy
letter/digit names still work), records the package token on each producing run,
warns when a filename token contradicts the content-derived one, and reports the
final winner's token. The judging directive treats a name difference as a rename
(never as missing content) and still tolerates legacy tokens.

## 0.6 — pipeline alignment (2026-09-19)

Aligns the skills with the current `paper_pipeline.py` policy surface.

- **Length rule (M19, always on).** Replaces the blanket "abstract/main-text
  length is exempt" standing exemption in both SKILL.md files, both standalone
  prompts and the README: the journal's Article limits apply relaxed by the
  user's margins — abstract ≤ 150 words +15% (≤ 172) and main text ≤ 3,000 words
  +25% (≤ 3,750, excluding abstract, Methods, references and figure legends) —
  with words counted as maximal runs of NON-SPACE characters and a newline
  treated as space. The cover letter's persuading part is measured against the
  master prompt's own 300-500-word preference — NBT's official guidance states
  no cover-letter word limit (checked 2026-09-19) — as a Minor formatting item,
  never a journal requirement. New bundled `paper-review/scripts/count_words.py`
  produces the counts deterministically (including `--section cover-letter`).
  **M18** (figure-legend length) always enumerates every legend's word count;
  the journal requires legends to respect the article type's limit but publishes
  no number, and the optional proxy cap only changes whether an over-count
  legend is reported as an over-cap item. Discovery proposals now start at M20
  (`references/sweeps.md`, `references/discovery.md`).
- **Zotero policy (rule E2).** Replaces the absolute "never touch a citation
  field / never touch the library" with the pipeline's four modes: read-only
  reference resolution by default; citation-field edits in the REVISED copy
  under the live-field rules (parent bibliographic item keys, unique
  `citationID`s, preserved baseline, snapshot + bundled validator, no automatic
  Zotero Refresh); library writes only when the operator explicitly enabled
  them, ONE field of ONE existing item, propose-then-verify, with
  `zot items update <KEY> --field <FIELD> "<VALUE>" --last-modified auto` and no
  create/delete/bulk edits. paper-review still never writes to the library.
- **Pipeline conventions.** The `[AUTHOR TO COMPLETE: ...]` marker is disposed
  as a hand-off item, never a hygiene finding (M6); the tracked-changes
  auxiliaries stay excluded from the corpus; the word-count definition is now
  shared with the pipeline.
- `tests/validate_skill.py` gained checks for the length rule, the Zotero
  modes, the new script and the M20 proposal numbering.

## 0.5 — acronym long-form release (2026-09-18)

The reported defect: `Copy-number (CN)` introduced at its first use, yet the
manuscript main text kept spelling the term out (`copy-number`, `copy number`,
`copy numbers`) and no round ever revised it. Root cause: the M1 sweep
enumerated acronym-like TOKENS only, so the `CN` row read "defined at first
use: Y, consistent: Y" while the long form carried the prose; the finding rules
had no rule for it, the nearest one (orphan definition) pointed the wrong way,
the revise spec had no fix direction, and the judges filed wording consistency
as cosmetic. Pinned by `tests/probe_regressions.py` (R15–R20) and
`.paper_test/test_acronym_longform.py`; `tests/validate_skill.py` now has 42
checks (C25–C26 cover the artifact).

- **M1b reverse-direction audit (`extract_acronyms.py`).** For every acronym
  with a recorded definition, every occurrence of the un-abbreviated long form
  AFTER that context's first long-form occurrence is enumerated into an M1b
  instance table inside `M1_acronyms.md` (and into the JSON rows). A context is
  a section WITHIN one file; the audit is NOT licensed by a local definition,
  because the reported case is a definition in the abstract and residues in the
  main text. Matching is case/hyphen/plural-tolerant (`copy number`,
  `copy-number`, `Copy-Number`, `copy numbers`); the definition site itself
  (`copy-number (CN)`, `CN (copy-number)`, and the key form `CN, copy number;`)
  and matches inside double quotes are never rows; a line rendered once per
  page carries its repeat count so one look disposes the family. Each acronym's
  own uses are counted per context through its inflectional family (`CNs`
  counts as a use of `CN`), so rule (c) cannot mistake a definition for an
  orphan.
- **A bibliography file is a reference list.** `classify_context()` checked the
  `supp`/`fig` heuristics before the reference patterns, so a supplement's
  `.bib` was swept as supplementary text: reference titles and abstracts fed
  the M1 inventory (64 phantom tokens and the M1b rows they produced on the
  production corpus). Reference detection now runs first, including `.bib`.
- **Two matcher bugs found while testing the fix**: a hyphenated long form that
  also looked like a token (`Copy-Number` matched by the strict detector) was
  dropped as "another acronym", silently killing the whole CN audit on
  corpora with one capitalised slip; and definition spans were recorded
  lowercase while the token kept its case, so an acronym's OWN definition site
  was misread as another term's and its first-use slot was handed to a later,
  genuine residue.
- **Review spec (`paper-review/references/sweeps.md`)**: new finding rule **(k)**
  (one finding per M1b row, Minor/resolvable, substitute the acronym), rule (c)
  amended to count the inflectional family and to defer to (k), a M8 carve-out
  (long/short pairs are position-governed by M1, not "two terms for one
  entity"), and the artifact-column spec.
- **Revise spec (`paper-revise/references/edit_rules.md`)**: new rule **P1a** —
  substitute the acronym for each flagged occurrence, keep each context's first
  use, pluralise/compound correctly (`copy numbers` → `CNs`,
  `copy-number-driven` → `CN-driven`), quote or generated-rendering rows become
  manual steps, and the V3 rescan must show zero M1b rows for the edited
  contexts.
- **Both prompts** re-synced verbatim with those references (D10/D10b stay
  green) and the `extract_acronyms.py` script-table line documents the audit.
- **Orchestrator (`paper_pipeline.py`)**: `REVISE_DIRECTIVES` item 8 carries
  the rule-(k) recipe and the zero-M1b rescan gate; `JUDGE_DIRECTIVES` states
  that systematic consistency failures are NOT cosmetic, naming the M1b table
  as the evidence surface; the review postcheck now fails a review whose M1b
  table has rows while `findings.json` raises no M1 finding and the M1 coverage
  row does not account for them.

## 0.4 — audit-2 release (2026-09-14)

Findings from the second audit, each reproduced before the fix and pinned by a
regression probe in `tests/probe_regressions.py` (R1–R14) plus
`tests/probe_hardcases.py` (H1–H4). Run `python3 tests/validate_skill.py` for
the unchanged v0.3 suite (40 checks).

- **M1 dropped every all-lowercase gene/protein symbol** (`p53`, `p21`, `nf1`,
  `il6`, `stat3`, `mbd3`, `nrf2`): an uppercase-presence filter was applied to
  all detectors, and the gene pattern only covered `p/c/e` prefixes. The
  detector is now `[A-Za-z]{1,6}\d{1,4}[a-z]?` with the uppercase rule applied
  only to the strict detector, plus a stopword list so measurement nouns
  (`week12`, `day3`, `group1`) and version prefixes (`v4` from `v4.3.0`) do not
  become rows.
- **`WORK/extra_acronyms.txt` could not add lowercase terms** — the documented
  escape hatch for project-specific vocabulary now matches case-insensitively
  and bypasses the strict-detector filters, so `tnf`, `nanog` etc. can be
  declared.
- **Reference-region holes (M1/M4).** Two silent drops remained: content after
  a bibliography followed by an unrecognised heading (e.g. `## Statistical
  analysis`) was skipped because the section state stuck on `references`, and a
  trailing paragraph with no heading stayed inside the computed region. The
  region now ends at the first blank-line-separated paragraph that does not
  look like a reference entry, the section state is reset after the region, and
  the boundary (`file lines a–b, why`) is printed in the M1/M2/M4 artifacts.
- **M2 could not enumerate unnumbered reference lists** written as `Smith J.
  Title. Journal. 2019;570:1-9.` (only call-out-shaped lines were collected, so
  "listed but never cited" silently reported none). Every non-empty line inside
  the region is now an entry, with wrapped continuations merged instead of
  becoming phantom entries.
- **`Fig. 1 shows …` flipped the section context** to `figure legend` for the
  rest of the section, mislabelling M1 contexts and M4 cross-context
  comparisons. Captions now require a separator after the label
  (`Fig. 1 |`, `Fig. 1.`, `Table 2:`); prose does not qualify.
- **Sparse/merged xlsx rows lost column alignment** (a row with only `C3`
  became the single field `7`, poisoning M15 column sums). Rows are now keyed
  by cell reference and zero-padded to the widest column of the sheet.
- **Repeated `--value` (documented) was ignored** — argparse kept only the last
  value. `--term`, `--value` and `--variants-file` are now `action="append"`,
  so `--value 0.021 --value 0.031` enumerates both.
- **Measurement-interval filter widened** (`values [2, 5]`, `ages [8, 9]` were
  still counted as citations and produced phantom orphans); filtered brackets
  remain recorded in `suspect_brackets`, never silently dropped.
- **Header/footer text now carries its own context** (`header`, `footer`,
  `footnotes`, `endnotes`, ranked after body text) instead of inheriting the
  last body section; synthetic `###` corpus markers are excluded from token
  extraction, so `SHEET`/`HEADER`/`FOOTER` cannot become acronym rows.
- **Housekeeping**: removed the unused `READABLE_READONLY`/`W_NS` constants;
  shipped the three regression suites under `tests/` so the changelog claims
  are reproducible; README now names the package version (0.4) and states which
  older copies (`v01`, `v02`) should be retired.

## 0.3 — audit release (2026-09-14)

Every entry below was reproduced against the 0.2 scripts on synthetic
submissions before being fixed, and is covered by a regression check in the
audit harness (24 script checks + 16 documentation checks).

### Scripts — silent data loss and wrong artifacts

- **Reference-list truncation (all three extractors).** After a
  `References`/`Bibliography`/`Reference list` heading, everything that
  followed (figure legends, tables, Methods, appendix) was treated as
  reference text and silently dropped. `extract_numbers.py` skipped the rest
  of the file, `extract_citations.py` never re-entered body text, and
  `extract_acronyms.py` reported acronyms defined later as *never defined*.
  All three now compute an explicit `(start, end)` region that ends at the
  next section heading or display-item caption; a numbered reference entry is
  never mistaken for a heading.
- **xlsx shared strings.** Cells with `t="s"` emitted the shared-string
  *index* instead of the text, so every string label in a supplementary table
  became an integer (poisoning M15 column sums). Sheet names are now mapped
  through `xl/_rels/workbook.xml.rels` instead of by sorted file name, and
  inline strings are handled.
- **Percentages never matched.** The `%\b` pattern could not match `62%`,
  `41%.` or `62% ` — the whole percentage class was dead. AUC also missed the
  common "AUC was 0.81" phrasing, and R² only accepted `R2 =`.
- **M1 token coverage.** The acronym regex required an internal capital, so
  `Treg`, `Tregs`, `Foxp3`, `Nrf2`, `Sox2`, `Gata3`, `Stat1`, `Oct4`, `Tbx21`,
  `Tcf7`, `Il6`, `p53` … were invisible. Added gene-symbol and cell-type
  detectors, plus an optional `WORK/extra_acronyms.txt` for project terms.
  Statistical symbols are now listed as `EXEMPT (<reason>)` rows instead of
  being dropped, and `scRNA-seq/scATAC-seq` enumerates as two tokens.
- **M2 author-year matching was inverted.** `(Smith et al., 2019)` and
  `Smith et al. (2019)` were missed while prose years (`In 2020`, `Since
  2015`) were reported as call-outs. Rewritten to match the real forms and to
  require a citation shape.
- **M2 cross-document logic.** Order violations, duplicate numbers, orphans
  and uncited entries merged every document into one numbering space, so a
  cover letter citing `[5]` plus a manuscript starting at `[1]` produced
  false findings. Each list-owning file is now its own space (the artifact
  prints per-document and union views), and bracketed measurement intervals
  (`interval [2, 5]`) are recorded as `suspect_brackets`, not citations.
- **Heading variants.** `Reference list` / `Literature cited` were only
  recognised by one of the three scripts.
- **Docx coverage.** Header, footer, footnote and endnote text was never
  read (corresponding-author metadata living in a header was invisible);
  those parts are now extracted under a lowercase marker line and recorded in
  the inventory notes.
- **File handling.** `.rtf` was copied verbatim into the corpus, so triggers
  ran over RTF control words; it is now stripped to text (read-only, not for
  editing). Zero-byte files are recorded as `(empty file)` instead of
  vanishing; an unreadable/scanned PDF now carries an explanatory note
  instead of an empty one.
- **`extract_occurrences.py`.** The documented `--variants-file` dict form
  exited with "give --term, --value, or --variants-file"; dict, list-of-dicts
  and list-of-strings forms all work now, multi-target runs get a hash suffix
  so runs cannot overwrite each other, and `--out DIR` was added.
- **Reading order.** "Defined at first use" and per-context first occurrences
  were computed from sorted file names; they now use in-file section headings
  (Abstract, Results, Methods, Figure legends, …) with role-based reading
  order as the fallback, so a single-file manuscript still separates abstract
  from legends.

### Instruction files

- `paper-review/SKILL.md`: OUT/WORK may not live inside SUBMISSION_DIR; the
  occurrence-artifact location is stated; the sweep-growth loop has a
  read-only fallback.
- `references/sweeps.md`: M4's garbled purpose text replaced; M1(h) aligned
  with the "format-flexible, never a blocking requirement" rule; M1/M2/M6
  enumeration notes updated (extra-token file, per-document citation scope,
  corpus-observability limits).
- `paper-revise/SKILL.md` + `references/ledger.md`: acceptance check now says
  A1–A9; V1/V4 artifacts (`roundtrip_check.md`, `checksums_after.txt`) defined.
- `references/edit_rules.md`: E2 forbids Zotero library mutations (read-only
  verification plus explicit user confirmation instead of a hard-rule
  conflict); E5's marker fallback is renamed `<name>.before-after.docx` so a
  non-tracked file is never published under `.tracked.docx`.
- `README.md`: install/tuning paths no longer point at directories that do not
  exist, the artifact table says which tables the shipped scripts actually
  produce, the missing eval-HTML reference is marked as not bundled, and the
  package carries a version plus a duplicate-copy warning.
- `prompts/*.md`: regenerated from the updated SKILL/reference files so the
  fallbacks cannot drift.

### Not changed (needs the installer, outside this package)

- A second, byte-identical copy of this package is installed at
  `~/.codex/skills/paper-skills/`. Codex registers skills by name, so the two
  copies compete. Delete or archive the older copy after confirming it is
  unmodified.

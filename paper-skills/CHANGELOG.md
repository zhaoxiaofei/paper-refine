# Changelog

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

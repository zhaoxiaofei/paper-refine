# Edit Rules E1–E6, Propagation P1, Code C — paper-revise

Applied during Step E (one edit at a time, in A4 plan order). Each rule
exists because its violation is a documented failure mode of LLM-driven
revision — the constraint is the countermeasure, not bureaucracy.

## E1 — Precision

Edit the exact sentence/field only. No reflow, no restyle, no length-driven
cuts — EXCEPT the scoped M19 compression below. Preserve existing styles,
numbering, equations, table layouts, figure placement. Do not "improve"
untouched text. The A7 diff log must show this — unmapped hunks get reverted.

**Scoped exception — M19 length compression.** An abstract or main text over
the pipeline's relaxed caps (abstract ≤ 172 words = 150 +15%; main text ≤ 3,750
words = 3,000 +25%, excluding abstract, Methods, references and figure legends,
for the default Nature Biotechnology Article profile; another content type uses
its own base numbers with the same margins, and another venue profile carries
the numbers its own guidelines state) is brought within the cap by removing redundancy, hedging and
repeated statistics ONLY. Never delete scientific content, claims, limitations,
data, accession numbers or needed methodological detail, and never cut text
that is already within the cap for length reasons. Words are maximal runs of
non-space characters with a newline treated as space; count with
`count_words.py` (bundled with paper-review), never by eye. Record every
compression in the A7 diff log and in CHANGELOG.md under check id M19. A
section that cannot be brought within the cap without losing content is left as
it is and handed to MANUAL_STEPS.md. The cover letter's PERSUADING part follows
the user's configured 300-500-word preference (the default profile's venue
states no cover-letter word limit, checked 2026-09-19): bring it into the range by
removing redundancy only, label it as the user's preference rather than a
journal requirement, and never delete content to reach it. Figure legends
(check id M18) are always counted: with no proxy cap configured, record the
counts and never cut a legend for length; when the operator configured a cap,
the same redundancy-only compression applies.

## E2 — Zotero live fields and the Zotero library

The operator's Zotero policy (`paper_pipeline.py setup --zotero`) has four
modes; follow the mode you were given, and default to `read` when running
standalone without an explicit instruction:

- **off** — do not run the `zot` CLI. An unreadable or unverifiable field goes
  to MANUAL_STEPS.md.
- **read** — resolve and verify references read-only (`zot --local ...
  items list|get|children`, `zot items get`, `zot items citation|bib`,
  `zot fulltext get`); never edit a field; never write to the library. A
  suspected metadata error (wrong year, DOI, item, author) becomes a proposal
  in MANUAL_STEPS.md: item key, field, current value, proposed value, evidence.
- **edit** — additionally, citations may be edited in the `REVISED/` copy under
  the live-field rules below.
- **apply** — only when the operator explicitly enabled writes: additionally,
  ONE field of ONE existing library item may be corrected under the
  propose-then-verify protocol below.

**Live-field rules for any citation edit.** Read the `$zotero-use` skill's
`references/word-docx-citations.md` first — it is the authority on the OOXML
field sequence. Cite PARENT bibliographic item keys, never attachment keys;
use the URI namespace of the item's OWN library (never copy a document-wide
namespace onto a new key); give every insertion location a unique
`citationID`; put several sources cited at one location into ONE field with
several `citationItems`; never synthesize `formattedCitation`/`plainCitation`
(the visible text you insert is provisional — Zotero Refresh replaces it);
preserve every existing citation ID, item ID, URI and embedded `itemData`; add
or remove a citation by operating on the WHOLE complex field (begin →
instrText → separate → result → end) and keep the surrounding sentence
grammatical; never edit the bibliography field itself; a field you cannot fully
read or parse (foreign namespace, missing `itemData`, unreadable XML) stays
untouched and goes to MANUAL_STEPS.md; never trigger Zotero Refresh yourself —
the author refreshes in Word.

**Snapshot first, prove the edit.** Keep an untouched copy of every `.docx`
whose live fields you edit. After saving, validate the edited copy against that
snapshot with the bundled read-only validator
(`$zotero-use/scripts/validate_zotero_docx.py`, e.g. `--baseline <copy>
--preserve-baseline-citations`). If the check fails, restore the snapshot and
record a manual step instead of shipping a possibly corrupted field. Record
every citation edit in CHANGELOG.md with the item key and the validation
result.

**Library writes (mode `apply` only, on an explicit user request).** Never
create or delete library items, attachments, collections or tags; never
bulk-edit; never touch an item the manuscript does not cite; never write when
the change would alter a scientific claim. For one field of one existing item:
(P1) write the proposal row BEFORE any write — item key, version read, field,
current value, proposed value, evidence, and the manuscript location that
depends on it; (P2) re-fetch the item and confirm key, item type, title,
creators, year and DOI match what the manuscript cites, and that the change is
unambiguous and touches nothing else. Then apply exactly
`zot items update <KEY> --field <FIELD> "<VALUE>" --last-modified auto`
(the version guard turns a concurrent edit into a clean failure instead of an
overwrite), re-read the item, and append the outcome and the new version to the
ledger. Any doubt → do not write: downgrade to a proposal plus a manual step.

## E3 — Missing mandatory items

Never fabricate content. Where a skeleton can legitimately be scaffolded
(cover letter structure, data availability statement frame, author
contributions list), create the file in REVISED/ with clearly marked
`[AUTHOR TO COMPLETE: ...]` placeholders and list every placeholder in the
final report. Otherwise just report the gap. A data-availability statement
is not something to invent — it is something to scaffold.

## E4 — Plagiarism and AI-content findings

Plagiarism findings: rewrite the flagged passage with proper paraphrase and
attribution (or direct quote + citation). AI-generated-content findings:
revise flagged text for accuracy and internal consistency, but do NOT attempt
to conceal AI use — if generative AI was actually used anywhere, ensure
disclosure complies with Springer Nature policy. Ask the user to confirm
actual usage; never assume.

## E5 — Tracked-changes auxiliary files

For every edited `.docx`, ALSO emit `<name>.tracked.docx` with real Word
tracked changes (`w:ins`/`w:del` in the OOXML) covering every edit. Raw-OOXML
tracked changes are fragile to hand-write — if the available libraries cannot
produce them reliably, fall back to `<name>.before-after.docx`: a copy whose
changed paragraphs carry clearly bracketed `[BEFORE: ...]` / `[AFTER: ...]`
markers, with a first-paragraph note that it is a marker file, not a
tracked-changes document. Never publish a marker file under the `.tracked.docx`
name — the author would send a reviewer something that only looks like tracked
changes. Record the fallback in A3 and in REVISION_REPORT.md. For `.tex`: run
`latexdiff` original vs revised if available; otherwise note its absence.

## E6 — Scientific-judgement guard

Do not alter scientific claims, interpretations, or the strength of
conclusions on your own initiative. Where a fix requires such judgement
(e.g., "is this really the first demonstration?"), leave the document
unchanged, provide 2–3 alternative wordings in the final report, and set the
ledger status to `manual-required` (reason: scientific judgement). The model
chooses wordings; the author chooses claims.

**RIGOR REPAIRS ARE LEGAL (2026-09-21).** The guard above covers claims,
interpretations and conclusion strength — not the *supporting detail* behind
them. An edit that ADDS what the paper already owes its reader is allowed
without a scientific judgement call and is recorded as an improvement row
(`I-xxx`, check id, tier, severity, evidence):
  * n, error-bar definition, sample size, or which comparison a p-value refers to;
  * a missing seed / software version / accession / data-availability pointer that
    the package already implies;
  * a leakage, baseline or validation statement the Methods already support;
  * a cross-reference, number or label brought in line with the value the review's
    hierarchy names as authoritative.
If the added detail would CHANGE what the paper claims (a new comparison, a
stronger causal word, a different population), it is still a judgement call:
leave it, propose wordings, `manual-required`.

## P1 — Consistency propagation

When a mismatched number/label/term/claim is corrected, the authoritative
value follows the review's resolution priority:

**supplementary tables > supplementary figures/notes > main figures &
legends > Methods > main text (Results/Discussion) > abstract > cover letter**

For EVERY correction (not just the convenient ones):
1. script-extract all occurrences of the old value AND the new value across the whole revised corpus (`extract_occurrences.py --value ...` / `--term ...`);
2. update every occurrence (each becomes an A6 row; each verified);
3. re-scan the whole revised set for newly introduced contradictions (V3).

Propagation by attention alone is forbidden — that is the acronym problem in
reverse: an edit applied in the abstract but forgotten in Figure 3's legend.

## P1a — Acronym long-form repetition (review check M1, rule (k))

When a finding says the un-abbreviated long form was used again after the
acronym's first use (an M1b instance row), the fix is to SUBSTITUTE THE ACRONYM
for that occurrence — never the reverse:

- edit exactly the occurrences the finding lists (one A6 row each; the script's
  M1b table gives the exact file:line), never expand a short form that is
  already correct, and never delete the acronym's definition;
- match the grammar of the long form: pluralize the acronym to the long form's
  number (`copy numbers` → `CNs`; `copy-number gains` → `CN gains`), and
  substitute inside compound modifiers (`copy-number-driven` → `CN-driven`);
- keep each context's own first long-form occurrence (that is where the term is
  introduced), and leave quoted titles, proper names and genuinely different
  terms of art verbatim: mark those rows `manual-required` with that reason
  instead of editing;
- a row whose text lives in a generated rendering (figure PDF, build output) is
  fixed at its source when that source is in the corpus; otherwise record the
  manual step (which source file, which tool, the exact substitution);
- propagate per P1 across the whole revised set, then RE-RUN the sweep on the
  revised corpus: the M1b table must show ZERO rows for the contexts you
  edited, or carry a ledger reason for each residual row (V3). The re-scan is
  the proof that the convention is consistent now — a revision that leaves the
  M1b table unchanged has not fixed the finding.

## C — Code revisions (only if analysis code is part of the submission)

Locate the relevant repository (path in the submission directory, or URL
supplied by the user); copy it to `CODE/` and edit only the copy.

**Scientific integrity rule: never change analysis code merely to make
outputs match manuscript numbers.** First determine the ground-truth value
using the review's resolution priority (P1). If the CODE is wrong: fix it
minimally and flag that ALL downstream numbers/figures must be regenerated —
the dependent manuscript numbers become `manual-required` with rerun
instructions; never guess their new values. If the MANUSCRIPT is wrong: fix
the manuscript instead.

Make minimal, targeted changes; run available tests/linters if the
environment can be set up; otherwise perform a static review and say so.
Record changes in A9.

Write `CODE/README_RERUN.md`: environment setup (language, package manager,
exact dependency versions, random seeds), data locations/accessions, the
exact commands in order, expected outputs mapped to the manuscript
figure/table/number each one feeds, approximate runtime, and post-run
verification steps.

## E3a — Searchable placeholders: a VERIFIED NEGATIVE is not invention

`[AUTHOR TO COMPLETE: ...]` markers that ask for a findable fact (preprint
status/DOI, archived-copy DOI, accession, database id, repository commit,
ORCID) are classified `searchable`, and the orchestrator answers them BEFORE the
session with its own public-API lookups:

* `work/PLACEHOLDER_LOOKUP.md` — one row per lookup with its verdict
  (`found` / `absent` / `error` / `skipped`), the endpoint's own title/date and
  the query;
* `work/IDENTIFIERS.md` — every DOI/accession/repository/ORCID in the corpus with
  the same verification verdict.

Dispose every row:

* **`found`** → replace the marker with the fact and name the identifier
  (server + DOI/accession/commit).
* **`absent`** → replace the marker with the verified negative, in the author's
  voice and with the date of the search: `Preprints: not posted.`, `not yet
  deposited (checked <date>)`. This is NOT invention — a recorded, reproducible
  search that returned nothing is evidence, and it is strictly better than
  shipping the question. A marker the table answers and that still ships is a
  FAILED run (the postcheck cites the exact lookup row).
* **`error` / `skipped`** → the lookup could not run (offline). Leave the marker
  and put the failed query in `MANUAL_STEPS.md`.
* **`author-only`** (funding, consent, a decision the author owns, an identity
  you cannot confirm) → keep the marker and the manual step.

Never fill a marker from your own knowledge, and never invent an identifier:
`absent` + the search record is the answer when nothing exists.

## E7 — Acting on the auditor's dispositions (`--audit on`)

When the round ran an auditor, the reviser consumes the AUDITED list: the
auditor's `audit/audit.json` disposes every frozen finding (confirm, or drop
with evidence) and may add `AU-*` findings. Rules:

* the ledger still gets one row per **effective** finding id (frozen minus drops
  plus additions); `audit/audit.json` is the record of why an id is not yours;
* a DROPPED finding is not yours to re-litigate. If you believe the audit's
  evidence is wrong, re-open it explicitly: state the new evidence in the
  ledger row's rationale (a quote, a file:line, or a re-derivation) — never
  silently reinstate the finding;
* every `AU-*` finding is a NORMAL finding: resolve it or hand it over with a
  reason, exactly like an `F-*` row;
* the auditor never edits the package, so any edit its finding requires is
  yours, and it goes through the same E1/E5 rules (targeted, tracked auxiliary,
  ledgered).

## E9 — The L1–L11 language pass (every package-producing stage)

After the finding-led edits, run the pass sentence by sentence — including
legends, tables, footnotes and the cover letter — and write `work/R6_language.md`
in the package you produced:

* ONE row per change: `step | location | before | after | reason`;
* a COVERAGE table at the end with ONE row per step, including the steps that
  changed nothing (`L3 | 0 | no logic jumps found`). A step with no row is an
  UNAUDITED step, and the orchestrator records which steps are missing (it warns
  by default and fails the attempt under `setup --strict-artifacts`);
* after EACH step, re-run the code-side scan of the package
  (`python paper_docx_format.py scan <package dir>`): a step that introduces a
  finding-tier row (a long sentence at the section's bar, a new mega-paragraph, a
  nested parenthesis, a value+unit outside siunitx) is fixed before the next step
  runs. Each step must leave the package no worse than it found it.

The steps, in order: L1 premise/factual errors · L2 formal-logic slips ·
L3 logic jumps · L4 coherence · L5 unexplained prerequisites · L6 redundancy ·
L7 non-academic wording · L8 non-written register · L9 stiff/translated phrasing ·
L10 grammar · L11 typos/punctuation. Iterate at most twice, then stop and report.

## E10 — The integration difference ledger (one row per difference, both levels)

When merging donors into a copy, `integrated/DIFF_LEDGER.md` carries:

`file | donor | location | size (small = wording/sentence, large = section/organization) |
donor says | self says | verdict (port / keep-self / synthesize / ignore-cosmetic) | why |
effect on a claim/number/figure (or "none") | artifact (a path under integrated/work/) |
finding effect (preserves <id> / undoes <id> / none)`

* read each donor whole (no sampling); a donor with no useful difference still
  gets an explicit no-difference row;
* EVERY row carries its ARTIFACT under `integrated/work/diffs/`: a before/after
  pair for a `small` row (self sentence, donor sentence, shipped sentence) or the
  outline diff for a `large` row (self outline, donor outline, merged outline). A
  row without its artifact cannot be re-checked and is treated as unfilled;
* EVERY row states what it does to a resolved finding: `preserves F-00x`,
  `undoes F-00x` (say why in `why`, and keep the self wording unless the author
  decided otherwise), or `none`;
* the pool contains both rewrite levels (one structural arm, one sentence-level
  arm, when more than one rewrite was staged), so the ledger must contain BOTH
  `size` classes — that is what makes the integration stage a weighing of a
  reorganization against a prose improvement rather than a taste contest.

## E8 — Provenance the code already proved

`work/NUMBERS_LEDGER.md` fills the `source` column whenever a shipped data table
PROVES a value (a column sum/min/max, or a single cell — e.g. `45,365` = the sum
of `n_cells_total`). A row whose source is still empty is yours: find the
analysis output, the cited value or the Methods parameter, or record why it
cannot be sourced. A number in the abstract, a legend or the cover letter may
not stay unsourced — it is proved, cited, a declared parameter, or removed as
decoration (never silently, and never by changing a scientific claim). Removing
a number is a `preservation`-tier change: record it in CHANGELOG.md.

# adress_issues (targeted revision) — standalone prompt fallback
Paste this entire file as the prompt for a revision task when you cannot install Codex skills. It consumes review/findings.md + findings.json produced by the identify_issues prompt (or the nbt-review skill). Replace placeholder paths (FINDINGS_MD/FINDINGS_JSON, ORIGINALS, ZOTERO_SKILL) with your own. The nbt-review scripts are reused for propagation and rescans.
---
## PROMPT BODY (SKILL.md)
# NBT Targeted Revision — adress_issues

## Paths

- `FINDINGS_MD` = `./review/findings.md` — human-readable report from nbt-review
- `FINDINGS_JSON` = `./review/findings.json` — machine-readable; **CANONICAL list of finding IDs**
- `EXTRA_JSON` = `./review/round2/findings_extra.json` — discovery-round findings; merge if present
- `ORIGINALS` = the reviewed submission directory (default `./non-revised`; use the directory recorded in the findings report if present). **READ-ONLY, always.**
- `REVISED` = `./revised` · `WORK` = `./revised/work` · `CODE` = `./code`
- `ZOTERO_SKILL` = `/mnt/d/software/plugins/plugins/zotero/skills/zotero/scripts/zotero.py` (override or absent → manual instructions)
- `ZOT_CLI` = `zot` (pyzotero-cli) and the `$zotero-use` skill — reference resolution and, under the operator's Zotero policy, guarded citation-field edits (rule E2)

If both findings files are missing AND no findings are in the current conversation: **STOP and ask the user to run nbt-review (identify_issues) first.** Explicit paths the user gives override defaults. All output in English. Length rules inherited from the review (check id M19): the journal's limits apply relaxed by fixed margins — for an NBT Article, abstract ≤ 172 words (150 +15%) and main text ≤ 3,750 words (3,000 +25%, excluding abstract, Methods, references and figure legends); an over-cap section is brought within the cap by removing redundancy, hedging and repeated statistics ONLY, never by deleting scientific content, and text within the cap is never cut for length. An incompressible section goes to MANUAL_STEPS.md. The cover letter's persuading part is measured against the master prompt's own 300-500-word preference (NBT publishes no cover-letter limit) and is a Minor formatting item; figure-legend word counts (M18) are recorded but never cut when no proxy cap is configured.

## Mission

Apply every validated finding. Originals are never modified; every edit lands in `REVISED/` (documents) or `CODE/` (analysis code). Every failure mode of a revision task is enumerable too — so this skill runs on the same devices as the review: a ledger where every finding ID must get a row (no silent skip), an edit plan where every edit maps to a finding ID, a propagation map for long-range consistency, a diff log proving locality, a rescan proving no new errors, and a coverage table as the acceptance gate.

## Hard rules

1. **Originals read-only.** Record sha256 of EVERY original file BEFORE any edit (`WORK/checksums_before.txt`); never modify anything outside `REVISED/` and `CODE/`; re-verify byte-identity at the end (V4) and confirm it in the final report.
2. **Never invent.** No fabricated content, citations, data, results, or accession numbers. Missing mandatory items are scaffolded only with clearly marked `[AUTHOR TO COMPLETE: ...]` placeholders, every one listed in the final report. Scientific claims, interpretations, and the strength of conclusions are never altered on your own initiative (rule E6).
3. **No silent skip.** EVERY finding ID — `F-*` from findings.json and `X-*` from findings_extra.json (kept as separate ID namespaces) — appears exactly once in the REVISION LEDGER with a final status. "Not addressed" is not an allowed status. Every mechanical step must produce its artifact in `WORK/`; a step without its artifact is not done.
4. **One edit per finding instance.** Never aggregate edits. Every edit maps to a finding ID, or to a rescan ID `R-xxx` for issues introduced or discovered during revision.
5. **ENUMERATE → ARTIFACT → APPLY → VERIFY for every mechanical step.** Script-enumerate all affected occurrences (the review skill's `extract_occurrences.py` is bundled for this — copy it into `WORK/`), record every occurrence as a row (including rows later judged OK), act row by row, then verify row by row. Propagation by attention alone is forbidden.
6. **Zotero fields and the library (rule E2).** Reference resolution is read-only by default; a citation field may be edited ONLY in the `REVISED/` copy and only under the live-field rules (parent item keys, unique `citationID`s, preserved baseline, snapshot-then-validate with the bundled validator, no automatic Zotero Refresh). The library itself is never written unless the operator explicitly enabled writes: then ONE field of ONE existing item, after a written proposal and an independent re-fetch (`zot items update ... --last-modified auto`), never a create/delete/bulk edit. Preserve existing styles, numbering, equations, table layouts, and figure placement; no reflow, restyling, or "improving" untouched text.

## Steps (in order; each step's artifacts complete before the next)

- **R0 — Setup/safety.** Inventory + checksums; load both findings files; build the A1 ledger skeleton programmatically so no finding can be dropped; print the findings count as a checkpoint.
- **R1 — Re-verify every finding** against the sources; assign a verdict with a location-checked rationale (empty rationale = invalid). False positives → discard, but only with a recorded concrete rationale (misreading, correct cross-reference, guideline-version difference) — never silently. Ambiguous wording a reviewer could misread → verdict `clarification`. Unverifiable (unreadable Zotero field, number only inside a read-only figure) → `manual-required`. not-found-in-source → discard, unless the text lives in a read-only/unparseable file → manual-required.
- **R2 — Editable copies into `REVISED/`, ONE content-hash version token per package** (doc/docx/tex/bib/md/txt/xlsx; never pdf/png). Copy every editable document into `REVISED/` and give the whole package **one version token**: the 7-character content-hash printed by the bundled `scripts/revision_token.py REVISED/` (first 7 hex of SHA-256 over the sorted content digests of the payload files; your own reports, the `.tracked.docx` / `.before-after.docx` auxiliaries and `work/` are excluded; file names do not enter the hash, and existing version-token references inside contents are normalized, so applying the token does not change it).
  Apply the token to **every editable document**: REPLACE its trailing version token (`-a.docx` → `-<token>.docx`, `manuscript_v2.tex` → `manuscript_<token>.tex`) or APPEND it when the basename has none (`refs.bib` → `refs-<token>.bib`). The legacy letter/digit **INCREMENT rule is WITHDRAWN**: never turn `-a.docx` into `-b.docx`, and never turn `manuscript_v2.tex` into `manuscript_v3.tex`. A trailing NUMBER that is part of a document's identity (`SI-Table-1.csv`, `Figure-3.xlsx`) is not a version token and never shifts. Never mutate individual characters of a name (`manuscript.md` must not become `manuscripu.md`).
  Run the tool **before** the rename, then re-run it with `--verify <token>` after the rename/repoint pass and require the `OK` line.
  The only other rename allowed is the **collision fallback**: a same-named file already exists in `REVISED/` (re-run or two source versions) → the NEW copy gets `_rev2`, `_rev3`, … before the extension, recorded in A3 as `rename applied = yes`; leave the existing copy's name as it is.
  If (and only if) a revised path differs from the original basename (the token, the fallback, or a legacy package that already carries an incremented token), run the rename sweep: script-enumerate every reference to the **original (pre-rename) basename** (LaTeX `\input/\include/\includegraphics/\addbibresource/\bibliography`, build files, scripts) and repoint it to the new name; record each in A5. In the pure-collision case nothing needs repointing — the sweep just verifies and records zero repoints. LaTeX compile check (pdflatex + bibtex/biber or the project's Makefile) if a toolchain exists; otherwise syntax/label sanity check, stated explicitly. Legacy `.doc` → convert to `.docx` inside REVISED/ (same basename, new extension; `_rev2` on collision), note the conversion and flag it for user confirmation in the final report — do not block the run on it. Findings whose text lives in read-only files (pdf/png) cannot be edited in this workflow: mark them `manual-required` in the ledger.
- **R3 — Edit plan (A4)**, sequenced: (i) Critical factual/ethical/completeness → (ii) consistency propagation → (iii) logic/clarity/repetition → (iv) grammar/terminology → (v) formatting. If you cannot quote the before-text exactly, return to R1 — you have not located the finding.
- **E — Apply edits** one at a time in plan order, under rules E1–E6 in `references/edit_rules.md` (precision, Zotero fields, missing items, plagiarism/AI content, tracked-changes auxiliary `.tracked.docx`, scientific-judgement guard).
- **P — Propagation (A6).** Priority when a mismatched number/label/term/claim is corrected: supplementary tables > supplementary figures/notes > main figures & legends > Methods > main text > abstract > cover letter. For EVERY correction: script-extract all occurrences of the old AND new values across the whole revised corpus; update every occurrence; verify each row. Cross-check A6 against the A2 baseline — a baseline occurrence missing from A6 is a missed propagation; fix it.
- **C — Code revisions** (only if analysis code is in scope). Scientific integrity rule: never change analysis code merely to make outputs match manuscript numbers — details in `references/edit_rules.md`.
- **V — Validate.** V1 round-trip integrity (artifact `WORK/roundtrip_check.md`) · V2 locality via diff log (A7) · V3 full mechanical rescan of the revised corpus (A8: the M-sweeps from nbt-review PLUS any sweep definitions in `./review/round2/new_sweeps.md`) · V4 checksum re-verification (artifact `WORK/checksums_after.txt`) · V5 final outputs.

Artifacts A1–A9 column specifications and status vocabularies: `references/ledger.md`.

## Final outputs (write incrementally throughout)

- `REVISED/CHANGELOG.md` — for every finding ID: document, exact before → after text, status. Generated from A1 + A7.
- `REVISED/MANUAL_STEPS.md` — for every manual-required finding: which file, which section/paragraph/field, what to check, exact tool steps (e.g., verifying a citation field in Word via the Zotero plugin; applying a proposed Zotero library correction with item key, field, current value and proposed value), and follow-ups (e.g., regenerate a figure from CODE/ and update every dependent number).
- `REVISED/REVISION_REPORT.md` + `REVISED/revision_report.json` — the ledger, the coverage table (one row per finding ID — F-* and X-* — plus each R-xxx: id | final status | edit IDs | evidence of completion (diff hunk / artifact row); a finding ID without a coverage row, or a row without evidence, means the task is not finished), counts by status, the placeholder list, pending scientific-judgement decisions with proposed alternative wordings, the checksum confirmation, and guideline-version uncertainties to re-check against the current author guide.

## Execution discipline

- Prefer scripts over attention for every enumeration; keep scripts in `WORK/` (re-runnable). The nbt-review scripts (`convert_corpus.py`, `extract_occurrences.py`, `extract_acronyms.py`, `extract_citations.py`, `extract_numbers.py`) can be reused — run them against `WORK/corpus` built from `REVISED/`.
- Batch file by file to bound context, but every artifact spans the whole corpus; merge before verifying.
- Long sessions: maintain `WORK/STATE.md` (current step, pending edit IDs, open questions) so the workflow resumes without loss.

## Acceptance checks (for the human, after the run)

1. The coverage table has a row with evidence for every finding ID (F-* and X-*).
2. `revised/work/` contains the A1–A9 artifacts (A9 only when analysis code is in scope).
3. The diff log shows no unmapped hunks.
4. The checksum statement appears in REVISION_REPORT.md.
5. Every `[AUTHOR TO COMPLETE: ...]` in the revised files appears in the placeholder list.
6. Every citation-field edit is recorded in CHANGELOG.md with the item key and validated against the pre-edit snapshot (`validate_zotero_docx.py`); every over-cap abstract/main text (M19) is either within the relaxed caps or listed in MANUAL_STEPS.md with the reason, and the legend/cover-letter rows (M18/M19) are recorded (compressed only where a cap or the user's preference allows it without losing content).


## APPENDIX: Ledger A1–A9 specifications (references/ledger.md)
# Revision Ledger & Artifacts A1–A9 — nbt-revise

All artifacts live in `WORK/` (i.e. `revised/work/`) unless noted, and are
mirrored into the final report. A mechanical step without its artifact is not
done — that is the acceptance gate, not a flourish.

## A1 — REVISION LEDGER (the backbone)

One row per finding ID (BOTH namespaces: `F-*` and `X-*`). Built
programmatically in R0 so no finding can be dropped.

Columns: `id | category | severity | location | evidence | verdict | rationale | edit IDs | final status`

- `category` keeps the review's category number. The defect CLASS it maps to is the judge panel's
  vocabulary (highest priority first: `correctness > consistency > preservation > completeness >
  formatting`; the mapping table is in `nbt-review/references/sweeps.md` → CLASSIFICATION). State
  the class in the rationale whenever a row is disputed or resolved by a wording-only edit: an edit
  the panel cannot name in that vocabulary reads as cosmetic, and the reviewer's finding then never
  becomes an improvement a judge can see.
- **verdict** (from R1): `confirmed` / `false-positive` / `clarification` / `manual-required` / `not-found-in-source`
- **final status** (after edits): `fixed` / `fixed-with-caveat` / `clarification` / `placeholder-inserted` / `discarded` / `manual-required`

**Completeness check: ledger row count == total findings count across both
files.** This is what prevents the revision analogue of the original bug:
quietly handling "most" findings.

Rationale must reference the re-checked location (quote or file:line). An
empty rationale makes the row invalid.

## A2 — BASELINE ARTIFACTS

Load the artifacts stored in the findings files (M1 acronym inventory,
M2 citation inventory, M4 numbers…). If absent, extract BEFORE editing the
occurrence lists needed for propagation into `WORK/baseline/`: numbers,
labels, terms, claims (via `extract_numbers.py`, `extract_occurrences.py`,
`extract_acronyms.py`). Used by A6 and the V3 rescan comparison — every
difference between baseline and rescan must be explained by a logged edit or
flagged.

## A3 — FILE-COPY REGISTER

Columns: `original path | revised path | action | rename applied | notes`

- action: `copied-for-editing` / `new scaffold` / `not copied — read-only`
- notes: format conversions (`.doc`→`.docx`), the tracked-changes fallback
  path taken (see E5), anything unusual. The register is where conversions
  and fallbacks become visible instead of silent.

## A4 — EDIT PLAN

Columns: `edit ID (E-001…) | finding ID(s) | file | location | verbatim before text | intended after text | type (fix / clarification / scaffold) | propagation required Y/N`

Sequenced per R3: (i) Critical factual/ethical/completeness → (ii)
consistency propagation → (iii) logic/clarity/repetition → (iv)
grammar/terminology → (v) formatting. If the before-text cannot be quoted
exactly, the finding has not been located — back to R1.

## A5 — RENAME CROSS-REF MAP

Every reference to every renamed basename across the revised set:
`renamed file | referring file | line/element | updated? | verified?`
Script-enumerated (LaTeX `\input/\include/\includegraphics/\addbibresource/
\bibliography`, build files, scripts, prose mentions). Every row must end
`updated: Y, verified: Y` or carry a reason.

## A6 — PROPAGATION MAP

Per corrected value/label/term/claim: `authoritative value + basis (priority rule) | every corpus occurrence (script-extracted) | updated? | verified?`

Built with `extract_occurrences.py` (bundled in the nbt-review skill) over
the revised corpus — enumerate occurrences of BOTH the old and the new value.
A baseline occurrence (A2) missing from A6 is a missed propagation; fix it
before validation.

## A7 — DIFF LOG

Per revised file: hunks vs original (unified diff), each hunk mapped to an
edit ID. **An unmapped hunk is a violation: revert it or record an explicit
justification.** This is the locality proof — "only the intended sentences
changed".

**Improvement rows (`I-xxx`).** An edit that repairs a defect the frozen review
did NOT name is legal when it is recorded, not hidden: give it an `I-xxx` id, the
check id it belongs to (M1–M24 / J1–J4), the tier
(`correctness|consistency|preservation|completeness|formatting|writing`), a
severity (`critical|major|minor`), one line of evidence with a location, and the
diff hunk that carries it. E6 still governs *claims* (see edit_rules.md: rigor
repairs are legal; claims, interpretations and conclusion strength are not).
Record ONE row per instance: five fixed instances are five `I-` rows, never one
summary row, because the panel scores per instance. `I-` rows are not a
substitute for the frozen findings — every `F-*`/`X-*` id still needs its own
row.

## A8 — RESCAN ARTIFACTS + RESCAN FINDINGS

V3 output: the M-sweep artifacts re-run over the ENTIRE revised corpus (using
the nbt-review scripts where applicable) PLUS any sweep definitions from
`./review/round2/new_sweeps.md` (discovery classes — they apply now too).
Every rescan finding is classified:
- (a) residual manual-required item — must map to an existing ledger row;
- (b) NEW issue introduced or revealed by revision — fix immediately, assign `R-xxx`, add to the change log;
- (c) false alarm — discard with rationale.
None left undisposed.

## A9 — CODE CHANGE LOG

Only if analysis code is in scope (Step C). Columns: `file | change | finding/rescan ID | rationale | tests run | downstream numbers affected`.

## Checksum and round-trip artifacts (V1 / V4)

- `WORK/checksums_before.txt` — sha256 of every original file, written BEFORE
  any edit (hard rule 1).
- `WORK/checksums_after.txt` — the same list re-computed at the end (V4); every
  original must be byte-identical, and the comparison is quoted in
  REVISION_REPORT.md.
- `WORK/roundtrip_check.md` — V1: per revised file, that it re-opens and
  re-reads (docx/xlsx as zip + XML, `.tex` compiled or syntax-checked when a
  toolchain exists), with the method used and any file that failed.

## Coverage table (final report)

One row per finding ID (F-* and X-*) plus each R-xxx:

`id | final status | edit IDs | evidence of completion (diff hunk / artifact row)`

A finding ID without a coverage row, or a row without evidence, means the
task is not finished.

## APPENDIX: Edit rules E1–E6, P1, C (references/edit_rules.md)
# Edit Rules E1–E6, Propagation P1, Code C — nbt-revise

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
for an NBT Article; another content type uses its own base numbers with the
same margins) is brought within the cap by removing redundancy, hedging and
repeated statistics ONLY. Never delete scientific content, claims, limitations,
data, accession numbers or needed methodological detail, and never cut text
that is already within the cap for length reasons. Words are maximal runs of
non-space characters with a newline treated as space; count with
`count_words.py` (bundled with nbt-review), never by eye. Record every
compression in the A7 diff log and in CHANGELOG.md under check id M19. A
section that cannot be brought within the cap without losing content is left as
it is and handed to MANUAL_STEPS.md. The cover letter's PERSUADING part follows
the master prompt's own 300-500-word preference (NBT's official guidance states
no cover-letter word limit, checked 2026-09-19): bring it into the range by
removing redundancy only, label it as the user's preference rather than a
journal requirement, and never delete content to reach it. Figure legends
(check id M18) are always counted: with no proxy cap configured, record the
counts and never cut a legend for length; when the operator configured a cap,
the same redundancy-only compression applies.

## E2 — Zotero live fields and the Zotero library

The operator's Zotero policy (`nbt_pipeline.py setup --zotero`) has four
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
  (`python nbt_docx_format.py scan <package dir>`): a step that introduces a
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


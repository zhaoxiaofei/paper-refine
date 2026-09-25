# Revision Ledger & Artifacts A1–A9 — paper-revise

All artifacts live in `WORK/` (i.e. `revised/work/`) unless noted, and are
mirrored into the final report. A mechanical step without its artifact is not
done — that is the acceptance gate, not a flourish.

## A1 — REVISION LEDGER (the backbone)

One row per finding ID (BOTH namespaces: `F-*` and `X-*`). Built
programmatically in R0 so no finding can be dropped.

Columns: `id | category | severity | location | evidence | verdict | rationale | edit IDs | final status`

- `category` keeps the review's category number. The defect CLASS it maps to is the judge panel's
  vocabulary (highest priority first: `correctness > consistency > preservation > completeness >
  formatting`; the mapping table is in `paper-review/references/sweeps.md` → CLASSIFICATION). State
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

Built with `extract_occurrences.py` (bundled in the paper-review skill) over
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
the paper-review scripts where applicable) PLUS any sweep definitions from
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

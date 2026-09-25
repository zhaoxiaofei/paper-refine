---
name: paper-revise
description: Apply validated review findings to a manuscript package — targeted revisions in a revised/ copy while originals stay read-only. Re-verifies every finding against the source, plans and applies precise edits with cross-document consistency propagation, validates by diff and a full mechanical rescan, and reports precise manual steps for whatever cannot be safely automated. Use this skill whenever the user asks to fix, revise, address, apply, or correct the findings/issues/problems from a review — especially after the paper-review skill (identify_issues) produced findings.md / findings.json. Also trigger on "address the issues you found", "apply the findings", "make the revisions", "adress_issues".
---

# Targeted Revision — adress_issues

**Target venue and journal (configurable).** The venv-independent rule set comes from the
pipeline's venue profile (`venue_profiles/<id>.json`, selected with `set-venue`) and the journal
from `set-journal`; Nature Biotechnology is only the default profile. Numbers quoted below are
that default's -- use the profile of the run you are in.

## Paths

- `FINDINGS_MD` = `./review/findings.md` — human-readable report from paper-review
- `FINDINGS_JSON` = `./review/findings.json` — machine-readable; **CANONICAL list of finding IDs**
- `EXTRA_JSON` = `./review/round2/findings_extra.json` — discovery-round findings; merge if present
- `ORIGINALS` = the reviewed submission directory (default `./non-revised`; use the directory recorded in the findings report if present). **READ-ONLY, always.**
- `REVISED` = `./revised` · `WORK` = `./revised/work` · `CODE` = `./code`
- `ZOTERO_SKILL` = `/mnt/d/software/plugins/plugins/zotero/skills/zotero/scripts/zotero.py` (override or absent → manual instructions)
- `ZOT_CLI` = `zot` (pyzotero-cli) and the `$zotero-use` skill — reference resolution and, under the operator's Zotero policy, guarded citation-field edits (rule E2)

If both findings files are missing AND no findings are in the current conversation: **STOP and ask the user to run paper-review (identify_issues) first.** Explicit paths the user gives override defaults. All output in English. Length rules inherited from the review (check id M19): the VENUE PROFILE's limits apply relaxed by the profile's own margins — for the default nature-biotechnology Article profile, abstract ≤ 172 words (150 +15%) and main text ≤ 3,750 words (3,000 +25%, excluding abstract, Methods, references and figure legends); another profile replaces these numbers (they are stated in the prompt of the run, and in `venue_profiles/<id>.json`): an over-cap section is brought within the cap by removing redundancy, hedging and repeated statistics ONLY, never by deleting scientific content, and text within the cap is never cut for length. An incompressible section goes to MANUAL_STEPS.md. The cover letter's persuading part is measured against the user's configured 300-500-word preference (the default profile's venue publishes no cover-letter limit) and is a Minor formatting item; figure-legend word counts (M18) are recorded but never cut when no proxy cap is configured.

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
- **R2 — Editable copies into `REVISED/`, ONE content-hash version token per package** (doc/docx/tex/bib/md/txt/xlsx; never pdf/png). Copy every editable document into `REVISED/` and give the whole package **one version token**: the 7-character content-hash printed by the bundled `scripts/revision_token.py REVISED/` (the first 7 hex characters of SHA-256 over the sorted content digests of the payload files; your own reports, the `.tracked.docx` / `.before-after.docx` auxiliaries and `work/` are excluded; file NAMES do not enter the hash, and existing version-token references inside file contents are normalized to `<VERSION>` first, so applying the token does not change it).
  Apply the token to **every editable document**: REPLACE its trailing version token (`-a.docx` → `-<token>.docx`, `manuscript_v2.tex` → `manuscript_<token>.tex`, `refs02-o.bib` → `refs02-<token>.bib`) or APPEND it when the basename has none (`refs.bib` → `refs-<token>.bib`). The legacy letter/digit **INCREMENT rule is WITHDRAWN**: never turn `-a.docx` into `-b.docx`, and never turn `manuscript_v2.tex` into `manuscript_v3.tex`. A trailing NUMBER that is part of a document's identity (`SI-Table-1.csv`, `Figure-3.xlsx`) is not a version token: it stays part of the name, and you never shift a numbered family or renumber its siblings. Never mutate individual characters of a name (`manuscript.md` must not become `manuscripu.md`).
  Run the tool **before** the rename, then re-run it with `--verify <token>` after the rename/repoint pass and require the `OK` line (if it does not match, the content changed after the token was computed — recompute and re-apply).
  The only other rename allowed is the **collision fallback**: a same-named file already exists in `REVISED/` (re-run or two source versions) → the NEW copy gets `_rev2`, `_rev3`, … before the extension, recorded in A3 as `rename applied = yes`; leave the existing copy's name as it is.
  If (and only if) a revised path differs from the original basename (the token, the fallback, or a legacy package that already carries an incremented token), run the rename sweep: script-enumerate every reference to the **original (pre-rename) basename** (LaTeX `\input/\include/\includegraphics/\addbibresource/\bibliography`, build files, scripts) and repoint it to the new name; record each in A5. In the pure-collision case the original name still exists in `REVISED/` and keeps its references — nothing to repoint; the sweep then just verifies and records zero repoints. LaTeX compile check (pdflatex + bibtex/biber or the project's Makefile) if a toolchain exists; otherwise syntax/label sanity check, stated explicitly. Legacy `.doc` → convert to `.docx` inside REVISED/ (same basename, new extension; `_rev2` on collision), note the conversion and flag it for user confirmation in the final report — do not block the run on it. Findings whose text lives in read-only files (pdf/png) cannot be edited in this workflow: mark them `manual-required` in the ledger.
- **R3 — Edit plan (A4)**, sequenced: (i) Critical factual/ethical/completeness → (ii) consistency propagation → (iii) logic/clarity/repetition → (iv) grammar/terminology → (v) formatting. If you cannot quote the before-text exactly, return to R1 — you have not located the finding.
- **E — Apply edits** one at a time in plan order, under rules E1–E6 in `references/edit_rules.md` (precision, Zotero fields, missing items, plagiarism/AI content, tracked-changes auxiliary `.tracked.docx`, scientific-judgement guard).
- **P — Propagation (A6).** Priority when a mismatched number/label/term/claim is corrected: supplementary tables > supplementary figures/notes > main figures & legends > Methods > main text > abstract > cover letter. For EVERY correction: script-extract all occurrences of the old AND new values across the whole revised corpus; update every occurrence; verify each row. Cross-check A6 against the A2 baseline — a baseline occurrence missing from A6 is a missed propagation; fix it.
- **C — Code revisions** (only if analysis code is in scope). Scientific integrity rule: never change analysis code merely to make outputs match manuscript numbers — details in `references/edit_rules.md`.
- **V — Validate.** V1 round-trip integrity (artifact `WORK/roundtrip_check.md`) · V2 locality via diff log (A7) · V3 full mechanical rescan of the revised corpus (A8: the M-sweeps from paper-review PLUS any sweep definitions in `./review/round2/new_sweeps.md`) · V4 checksum re-verification (artifact `WORK/checksums_after.txt`) · V5 final outputs.

Artifacts A1–A9 column specifications and status vocabularies: `references/ledger.md`.

## Final outputs (write incrementally throughout)

- `REVISED/CHANGELOG.md` — for every finding ID: document, exact before → after text, status. Generated from A1 + A7.
- `REVISED/MANUAL_STEPS.md` — for every manual-required finding: which file, which section/paragraph/field, what to check, exact tool steps (e.g., verifying a citation field in Word via the Zotero plugin; applying a proposed Zotero library correction with item key, field, current value and proposed value), and follow-ups (e.g., regenerate a figure from CODE/ and update every dependent number).
- `REVISED/REVISION_REPORT.md` + `REVISED/revision_report.json` — the ledger, the coverage table (one row per finding ID — F-* and X-* — plus each R-xxx: id | final status | edit IDs | evidence of completion (diff hunk / artifact row); a finding ID without a coverage row, or a row without evidence, means the task is not finished), counts by status, the placeholder list, pending scientific-judgement decisions with proposed alternative wordings, the checksum confirmation, and guideline-version uncertainties to re-check against the current author guide.

## Execution discipline

- Prefer scripts over attention for every enumeration; keep scripts in `WORK/` (re-runnable). The paper-review scripts (`convert_corpus.py`, `extract_occurrences.py`, `extract_acronyms.py`, `extract_citations.py`, `extract_numbers.py`) can be reused — run them against `WORK/corpus` built from `REVISED/`.
- Batch file by file to bound context, but every artifact spans the whole corpus; merge before verifying.
- Long sessions: maintain `WORK/STATE.md` (current step, pending edit IDs, open questions) so the workflow resumes without loss.

## Acceptance checks (for the human, after the run)

1. The coverage table has a row with evidence for every finding ID (F-* and X-*).
2. `revised/work/` contains the A1–A9 artifacts (A9 only when analysis code is in scope).
3. The diff log shows no unmapped hunks.
4. The checksum statement appears in REVISION_REPORT.md.
5. Every `[AUTHOR TO COMPLETE: ...]` in the revised files appears in the placeholder list.
6. Every citation-field edit is recorded in CHANGELOG.md with the item key and validated against the pre-edit snapshot (`validate_zotero_docx.py`); every over-cap abstract/main text (M19) is either within the relaxed caps or listed in MANUAL_STEPS.md with the reason, and the legend/cover-letter rows (M18/M19) are recorded (compressed only where a cap or the user's preference allows it without losing content).

---
name: paper-review
description: Pre-submission diagnostic review of a manuscript package for ANY venue or journal. The rules come from the pipeline's VENUE PROFILE (Nature Biotechnology is the default profile); the target JOURNAL is free text. Identifies and reports problems ONLY — never fixes them. Three phases — exhaustive mechanical sweeps (M1–M17), judgment passes (J1–J4), and a discovery round that hunts issue classes the checklist itself misses. Use this skill whenever the user asks to review, audit, check, proof, pre-screen, or diagnose a manuscript/submission/paper draft, mentions identify_issues, wants "find issues before submission", or asks to hunt for issues the standard checklist missed (discover mode). Even a casual "look over my paper before I submit" should trigger this skill.
---

# Pre-Submission Review — identify_issues

**Target venue and journal (configurable).** This skill is venue-agnostic: the pipeline that runs
it selects a VENUE PROFILE (`set-venue <id>`, `setup --venue`) and a JOURNAL (`set-journal`), and
records both in `pipeline_config.json`. Wherever this file quotes a number, a name or a
submission requirement, it is the **default** profile's (Nature Biotechnology); the profile the
run was configured with is authoritative, and the prompt states it. Run standalone, use the
target journal's own author guide and say which source you used.

## Paths

- `SUBMISSION_DIR` = `./non-revised` (override: any explicit path or argument from the user)
- `OUT` = `./review` — create it; ALL outputs land here
- `WORK` = `./review/work` — corpus, scripts, state
- `ZOTERO_SKILL` = `/mnt/d/software/plugins/plugins/zotero/skills/zotero/scripts/zotero.py` (override if the user provides one; if absent → fall back to manual-verification)
- `ZOT_CLI` = `zot` (pyzotero-cli) and the `$zotero-use` skill — the reference route for resolving citations read-only (`zot --local ... items list|get|citation|bib`, `zot fulltext get`). This skill never edits a citation field and never writes to the Zotero library (see M2 and Phase 1).

If `SUBMISSION_DIR` does not exist or is empty: **STOP and ask the user.**

`OUT` and `WORK` must stay **outside SUBMISSION_DIR** — never write review
artifacts into the package being reviewed. If the user's SUBMISSION_DIR is the
working directory (or contains it), put `OUT`/`WORK` in a sibling directory and
say where they went.

## Mission

Diagnose, do not fix. Produce a findings report + artifacts that the revision skill (`paper-revise`) can consume mechanically. Length rule (replaces the former blanket exemption): **the venue profile's abstract/main-text limits apply, relaxed by the profile's own margins** — for the default Nature Biotechnology Article profile, abstract ≤ 150 words +15% (≤ 172) and main text ≤ 3,000 words +25% (≤ 3,750, excluding abstract, Methods, references and figure legends); another content type uses its own base numbers with the same margins. Words are maximal runs of non-space characters with a newline treated as space. Sweep **M19** reports over-cap sections as formatting findings; never cut content to meet a limit and never flag under-length text. Sweep **M18** always enumerates every figure legend's word count (the venue profile requires legends to respect the article type's limit but publishes no number; an optional proxy cap only changes the disposition). The cover letter's persuading part is measured against the user's **300-500-word preference** — the default profile's venue states no cover-letter word limit (checked 2026-09-19) — and is a Minor formatting item, never a journal requirement. All output in English.

Guidelines source: prefer a local copy of the author guidelines if present in the directory; otherwise the TARGET VENUE's own author guide -- the pipeline's venue profile names it
(`venue_profiles/<id>.json`; the default profile's source is Nature Biotechnology's
"Information for Authors" / Nature Portfolio author guide); **name the source/version you relied on in the summary.** Label every guideline-dependent finding `[required at initial submission]`, `[required at revised-submission stage — prepare now]`, or `[recommended]`. Never present convenience conventions as blocking requirements: when the venue's guide says
initial submissions are format-flexible (Nature Portfolio's do), say so explicitly.

## Why this skill is built this way (read once)

A plain "review my manuscript" prompt reliably misses low-salience mechanical issues (undefined acronyms, citation mismatches, inconsistent numbers), because LLM attention aggregates and skips when a single read spans thousands of tokens. The countermeasure is procedure, not intent: every mechanical check must **ENUMERATE every instance into an artifact table, then audit the table row by row**. Coverage comes from the artifact, not from attention. A sweep that reports zero findings without an artifact proves nothing — it is indistinguishable from "didn't check".

## Hard rules

1. **Identification only** — findings, never edits. Never modify any file in SUBMISSION_DIR.
2. **Never invent.** Unresolvable value → status `unresolvable — manual verification required`. Guideline rule you cannot verify → `guideline-dependent`. Missing data → note a placeholder may be needed; never fabricate.
3. **No silent skips.** Every check ID must end up in the coverage table with a real disposition (`N findings` / `clean — basis: <artifact/locations>` / `unable — <reason>`). "Not checked" is not an allowed value.
4. **Mechanical sweeps M1–M17 are EXHAUSTIVE and MANDATORY, and M18 (figure-legend lengths), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan) always run with them, together with the adopted sweeps M21–M24 (correspondence policy, data/code-availability integrity, supplementary parity, concept/term families).** M18's optional proxy cap only changes whether an over-count legend is reported as an over-cap item. Only judgment passes J1–J4 may be prioritized. The word "non-exhaustive" never applies to a mechanical sweep.
5. **One finding per instance.** "Several acronyms are undefined" is not a finding; each undefined acronym is its own finding with its own ID, quote, and location.
6. **Sweep pattern for every mechanical check:** ENUMERATE (script preferred; scripts live in `WORK/`) → ARTIFACT (`OUT/artifacts/<ID>.md` for the M1/M2/M4–M17 tables; term/value occurrence enumerations are written to `WORK/occurrences_<slug>.md`, which is M8's artifact — pass `--out OUT/artifacts` if you prefer them alongside the others; every instance gets a row, including rows later judged OK; the artifact spans the whole corpus, not one file) → AUDIT (each row gets: a finding ID, `OK`, or `unable — <reason>`) → REPORT (findings derived only from artifact rows, never from general impression).
7. **A sweep with zero findings is INVALID unless its artifact exists and every row is disposed.**

## Bundled scripts (use them — they exist so enumeration is deterministic)

All stdlib-only Python, runnable anywhere Python 3.8+ exists. Copy them into `WORK/` or invoke them in place; keep any adaptations in `WORK/` so runs are reproducible.

| script | purpose |
|---|---|
| `scripts/convert_corpus.py` | Phase 1: recursive inventory + docx/xlsx/tex/bib/md/txt → plain-text corpus in `WORK/corpus/` (+ `inventory.md`/`inventory.json`) |
| `scripts/extract_acronyms.py` | M1: full acronym inventory with expansions, first-use-per-context, consistency flags, PLUS the M1b long-form audit (every use of a defined acronym's un-abbreviated long form after its first use in a context — case/hyphen/plural-tolerant — as an instance table of finding rows; see sweeps.md rule (k)). Reads optional `WORK/extra_acronyms.txt` (one token per line, case-insensitive) for project-specific terms — the way to add digit-free lowercase symbols such as `tnf` |
| `scripts/extract_citations.py` | M2: every call-out vs every reference entry; orphans, uncited, duplicates, order |
| `scripts/extract_numbers.py` | M4: labeled metrics, accessions, versions; auto-flags same-label conflicts |
| `scripts/extract_occurrences.py` | M8 term variants; also reused by paper-revise for propagation. Writes `WORK/occurrences_<slug>.md` (multi-target runs get a hash suffix so runs cannot overwrite each other). `--term`, `--value` and `--variants-file` are repeatable, so every corrected number can be enumerated in one run: `--value 0.021 --value 0.031` |
| `scripts/count_words.py` | M18/M19: counts a document's abstract, main text and cover letter with the pipeline's word rule (maximal runs of non-space characters, newline = space); `--section cover-letter` counts the persuading part (salutation/signature/disclosures excluded) against the user's 300-500-word preference. `--json` for the artifact rows and `--base-abstract`/`--base-main-text` for another content type. Deterministic counting, never estimation |

If a script misses a case class (e.g., a citation style it can't parse), **extend it in `WORK/`** rather than falling back to eyeballing.

## Phases (in order; each completes before the next)

**Phase 1 — Setup.** Run `convert_corpus.py` on SUBMISSION_DIR. Review the inventory: role classification, editable vs read-only, conversion status. Every conversion failure is recorded, never skipped. Images are marked `visually unverifiable` unless OCR/VLM is available; when a PDF/Word renderer exists, render them and LOOK instead of marking them unverifiable. Zotero live fields: the converter marks them `[[FIELD: ...]]`; check the rendered text; an unreadable or incomplete field goes to the manual-verification list (tell the user to verify it in Word). Resolve citations READ-ONLY with `ZOT_CLI` / `$ZOTERO_SKILL` / `$zotero-use` (parent bibliographic item keys, never attachment keys; confirm title, creators, year, DOI; `zot fulltext get` for the abstract/full text). This skill never edits a field and never writes to the library: a suspected metadata error becomes a finding with the proposed correction for paper-revise or the user to apply under their Zotero policy.

**Phase 2 — Sweeps.** Mechanical sweeps M1–M17 plus M18 (legend lengths, always enumerated), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity; the pipeline seeds `review/work/FORMAT_SCAN.json` and `review/artifacts/M20_formatting.md`, and every row must be disposed), the adopted sweeps M21–M24 (see `references/sweeps.md` §M21–M24) and judgment passes J1–J4: procedures, artifact columns, finding rules, classification, and the finding format are specified in `references/sweeps.md` — follow it exactly. One sweep at a time; finish one artifact before starting the next. For long documents, sweep file by file, then merge so every artifact spans the whole corpus.

**Phase 3 — Discovery round.** D0–D5 per `references/discovery.md`: hunt issue classes OUTSIDE the checklist; outputs `OUT/round2/findings_extra.{md,json}` and `OUT/round2/new_sweeps.md`. If the user passes `discover` as the argument, run ONLY this phase against existing findings and stop.

## Output (write incrementally — never assemble only at the end)

Truncation silently drops exactly the tail-end mechanical findings, so append each artifact and finding block to the files as it is produced.

`OUT/findings.md`:
1. File inventory (from Phase 1).
2. All sweep artifacts as titled appendix tables (or pointers to `OUT/artifacts/`).
3. Findings grouped by category 0–5, each entry: ID (`F-001`…), location (document/section/paragraph/line/figure/table), category, check ID (M1–M24, J1–J4), severity, short verbatim evidence quote, concise explanation, status (`resolvable` / `unresolvable` / `guideline-dependent`).
4. Per-document index of finding IDs.
5. Coverage table: every check ID (M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths) and M20 (OOXML style/formatting rows from the pipeline's scan), plus M21–M24 (the adopted sweeps)) → `N findings` / `clean — basis` / `unable — <reason>`.
6. Summary note: counts by category/severity; unresolved gaps; missing-citation issues; ambiguous context; unresolvable contradictions; the manual-verification list (incl. Zotero fields); guidelines source/version; items to re-check against the current author guide.

`OUT/findings.json` (machine-readable, consumed by paper-revise):
```json
{"submission_dir": "<path>", "guidelines_source": "<string>",
 "findings": [{"id": "F-001", "location": "...", "category": 0, "check": "M1",
               "severity": "Major", "evidence": "...", "explanation": "...",
               "status": "resolvable"}],
 "artifacts": {"M1_acronyms": [...], "M2_citations": {...}},
 "coverage": [{"check": "M1", "disposition": "N findings", "detail": "..."}]}
```

**Verification pass before finalizing:** confirm every artifact row has a disposition; confirm every check ID is present in the coverage table; add any missed findings with new IDs; state in the summary that the pass was performed.

## Execution discipline

- One sweep at a time; artifact complete before the next begins.
- Prefer scripts over attention for all enumeration; judgment only classifies rows.
- Long sessions: maintain `WORK/STATE.md` (current sweep, pending steps, open questions) so the workflow resumes without loss.
- Grow the skill: after the discovery round, validate the proposals in `OUT/round2/new_sweeps.md` with the user and append them to `references/sweeps.md` as M25, M26… (M18–M20 are reserved by the pipeline and M21–M24 were adopted from earlier discovery rounds — see `references/sweeps.md`) — the checklist converges toward exhaustiveness over successive runs instead of pretending to be exhaustive on day one. If the skill directory is read-only (common for an installed skill), do not fight it: keep the accepted text in `OUT/round2/new_sweeps.md` and hand the user the exact block to append.

## Acceptance checks (for the human, after the run)

1. `findings.md` coverage table lists every defined check ID: M1–M17, J1–J4, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths), M20 (OOXML style/formatting rows) and M21–M24 (the adopted sweeps).
2. Every sweep with findings has a matching artifact file in `review/artifacts/` (M8's occurrence enumerations live in `review/work/occurrences_*.md`). A sweep with findings but no artifact means it worked from impression — re-run that sweep.
3. Each finding points to a specific word/number/phrase with a verbatim quote, not a whole passage.
4. `findings.json` exists and every finding has all eight fields.

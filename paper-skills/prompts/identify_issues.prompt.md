# identify_issues (pre-submission review) — standalone prompt fallback
Paste this entire file as the prompt for a manuscript review task when you cannot install Codex skills. Replace the placeholder paths (SUBMISSION_DIR, ZOTERO_SKILL) with your own at the top of the PROMPT BODY. The bundled scripts referenced in the prompt are optional but strongly recommended — copy them from paper-review/scripts/ next to your working directory.
---
## PROMPT BODY (SKILL.md)
# Pre-Submission Review — identify_issues

**Target venue, article type and journal (configurable).** This skill is venue-agnostic: the
pipeline that runs it selects a VENUE PROFILE (`set-venue <id>`, `setup --venue`), the ARTICLE
TYPE the submission is (`set-article-type`, `setup --article-type` — the profile carries the
venue's content types and each type's own limits) and a JOURNAL (`set-journal`), and records all
three in `pipeline_config.json`. Wherever this file quotes a number, a name or a
submission requirement, it is the **default** profile's (Nature Biotechnology); the profile the
run was configured with is authoritative, and the prompt states it. Run standalone, use the
target journal's own author guide and say which source you used.

## Paths

- `SUBMISSION_DIR` = `./non-revised` (override: any explicit path or argument from the user)
- `OUT` = `./review` — create it; ALL outputs land here
- `WORK` = `./review/work` — corpus, scripts, state
- `ZOTERO_SKILL` = `/mnt/d/software/plugins/plugins/zotero/skills/zotero/scripts/zotero.py` (override if the user provides one; if absent → fall back to manual-verification)
- `ZOT_CLI` = `zot` (pyzotero-cli) and the `$zotero-use` skill — the reference route for resolving citations read-only (`zot --local ... items list|get|citation|bib`, `zot fulltext get`). This review never edits a citation field and never writes to the Zotero library.

If `SUBMISSION_DIR` does not exist or is empty: **STOP and ask the user.**

`OUT` and `WORK` must stay **outside SUBMISSION_DIR** — never write review
artifacts into the package being reviewed. If the user's SUBMISSION_DIR is the
working directory (or contains it), put `OUT`/`WORK` in a sibling directory and
say where they went.

## Mission

Diagnose, do not fix. Produce a findings report + artifacts that the revision skill (`paper-revise`) can consume mechanically. Length rule (replaces the former blanket exemption): **the venue profile's abstract/main-text limits apply, relaxed by the profile's own margins** — for the default Nature Biotechnology Article profile, abstract ≤ 150 words +15% (≤ 172) and main text ≤ 3,000 words +25% (≤ 3,750, excluding abstract, Methods, references and figure legends); another content type uses its own base numbers with the same margins. Words are maximal runs of non-space characters with a newline treated as space. Sweep **M19** reports over-cap sections as formatting findings; never cut content to meet a limit, never flag under-length text, and never strengthen or weaken a claim (in either direction) to reach one — a hedge the evidence requires is content, and stripping it is an overclaim. Sweep **M18** always enumerates every figure legend's word count (the venue profile requires legends to respect the article type's limit but publishes no number; an optional proxy cap only changes the disposition). Sweep **M20** always audits the OOXML style/formatting rows the pipeline's code-side scan seeds (break-only paragraph/blank page, running head on the title page, legend spacing, heading style drift, unintended italics incl. field-protected Zotero rows, mixed URL/email treatments, mixed quotation marks, em-dash density). The cover letter's persuading part is measured against the user's **300-500-word preference** — the default profile's venue states no cover-letter word limit (checked 2026-09-19) — and is a Minor formatting item, never a journal requirement. All output in English.

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
4. **Mechanical sweeps M1–M17 are EXHAUSTIVE and MANDATORY, and M18 (figure-legend lengths), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan) always run with them, together with the adopted sweeps M21–M24 (correspondence policy, data/code-availability integrity, supplementary parity, concept/term families), the REWRITE-PARITY checks M25–M29 (figure-artwork/text parity, house-style/orthographic conventions, claim→evidence coverage, sibling-definition symmetry, caption-promise vs printed-schema parity) and the SOURCE-HIERARCHY reconciliation M30 (a written claim against the code/raw data that produced it).** M18's optional proxy cap only changes whether an over-count legend is reported as an over-cap item. Only judgment passes J1–J5 may be prioritized; J5 (architecture & rewrite-class) produces scope-level rows in `OUT/ARCHITECTURE.md`, not per-sentence findings. The word "non-exhaustive" never applies to a mechanical sweep.
5. **One finding per instance.** "Several acronyms are undefined" is not a finding; each undefined acronym is its own finding with its own ID, quote, and location.
   M1(a) "used before it is defined" includes the acronym-first compound: a sentence that prints the short form first and the expansion after it (`MALBAC-sequenced (multiple annealing …)`) has used the token before defining it. When the sentence itself prints the expansion, the token IS an abbreviation being defined, so "it is a tool/proper name" is not a disposition.
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
| `scripts/enumerate_conventions.py` | M26 house-style/orthographic convention sweep: every occurrence of a US/UK spelling, hyphenation or preverb variant, from a built-in family list plus data-driven candidate pairs, one row per occurrence. Also reused by paper-revise for the convention propagation pass. |
| `scripts/count_words.py` | M18/M19: counts a document's abstract, main text and cover letter with the pipeline's word rule (maximal runs of non-space characters, newline = space); reads `.tex`/`.ltx` sources (abstract environment, section headings, `\caption` lines) like the other formats; `--section cover-letter` counts the persuading part (salutation/signature/disclosures excluded) against the user's 300-500-word preference; `--json` for the artifact rows and `--base-abstract`/`--base-main-text` for another content type |

If a script misses a case class (e.g., a citation style it can't parse), **extend it in `WORK/`** rather than falling back to eyeballing.

## Phases (in order; each completes before the next)

**Phase 1 — Setup.** Run `convert_corpus.py` on SUBMISSION_DIR. Review the inventory: role classification, editable vs read-only, conversion status. Every conversion failure is recorded, never skipped. Images are marked `visually unverifiable` unless OCR/VLM is available; when a renderer exists, render and LOOK. Zotero live fields: the converter marks them `[[FIELD: ...]]`; check the rendered text; an unreadable or incomplete field goes to the manual-verification list (tell the user to verify it in Word). Resolve citations READ-ONLY with `ZOT_CLI` / `$ZOTERO_SKILL` (parent bibliographic item keys, never attachment keys; confirm title, creators, year, DOI) and never write to the library: a suspected metadata error becomes a finding with the proposed correction.

**Phase 2 — Sweeps.** Mechanical sweeps M1–M17 plus M18 (legend lengths, always enumerated), M19 (abstract/main-text length plus the cover-letter preference) and M20 (OOXML style/formatting uniformity; the pipeline seeds `review/work/FORMAT_SCAN.json` and `review/artifacts/M20_formatting.md`, and every row must be disposed), the adopted sweeps M21–M24 (correspondence policy, data/code-availability integrity, supplementary parity, concept/term families), the rewrite-parity checks M25–M29 (artwork/text parity, house-style conventions, claim→evidence coverage, sibling-definition symmetry, caption-promise parity), the source-hierarchy reconciliation M30 (the seeded `review/artifacts/M30_hierarchy_reconciliation.md` rows, disposed, plus the producers the code cannot see) and judgment passes J1–J5 (J5 writes `OUT/ARCHITECTURE.md`, one row per scope): procedures, artifact columns, finding rules, classification, and the finding format are specified in the appendix below — follow it exactly. One sweep at a time; finish one artifact before starting the next. For long documents, sweep file by file, then merge so every artifact spans the whole corpus.

**Phase 3 — Discovery round.** D0–D5 per `references/discovery.md`: hunt issue classes OUTSIDE the checklist; outputs `OUT/round2/findings_extra.{md,json}` and `OUT/round2/new_sweeps.md`. If the user passes `discover` as the argument, run ONLY this phase against existing findings and stop.

## Output (write incrementally — never assemble only at the end)

Truncation silently drops exactly the tail-end mechanical findings, so append each artifact and finding block to the files as it is produced.

`OUT/findings.md`:
1. File inventory (from Phase 1).
2. All sweep artifacts as titled appendix tables (or pointers to `OUT/artifacts/`).
3. Findings grouped by category 0–5, each entry: ID (`F-001`…), location (document/section/paragraph/line/figure/table; a J5 architecture finding names its paragraph-range scope instead), category, check ID (M1–M30, J1–J5), severity, short verbatim evidence quote (J5: the current → proposed outline), concise explanation, status (`resolvable` / `unresolvable` / `guideline-dependent`).
4. Per-document index of finding IDs.
5. Coverage table: every check ID (M1–M17, J1–J5, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths), M20 (OOXML style/formatting rows from the pipeline's scan), M21–M24 (the earlier adopted sweeps), M25–M29 (the rewrite-parity checks) and M30 (the source-hierarchy reconciliation)) → `N findings` / `clean — basis` / `unable — <reason>`.
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
- Grow the skill: after the discovery round, validate the proposals in `OUT/round2/new_sweeps.md` with the user and append them to `references/sweeps.md` as M31, M32… (M18–M20 are reserved by the pipeline and M21–M30 are adopted — see `references/sweeps.md`) — the checklist converges toward exhaustiveness over successive runs instead of pretending to be exhaustive on day one. If the skill directory is read-only (common for an installed skill), do not fight it: keep the accepted text in `OUT/round2/new_sweeps.md` and hand the user the exact block to append.

## Acceptance checks (for the human, after the run)

1. `findings.md` coverage table lists every defined check ID: M1–M17, J1–J5, M18 (legend counts), M19 (abstract/main-text/cover-letter lengths), M20 (OOXML style/formatting rows), M21–M24 (the earlier adopted sweeps), M25–M29 (the rewrite-parity checks) and M30 (the source-hierarchy reconciliation).
2. Every sweep with findings has a matching artifact file in `review/artifacts/` (M8's occurrence enumerations live in `review/work/occurrences_*.md`). A sweep with findings but no artifact means it worked from impression — re-run that sweep.
3. Each finding points to a specific word/number/phrase with a verbatim quote, not a whole passage.
4. `findings.json` exists and every finding has all eight fields.


## APPENDIX: Sweeps M1–M30 and judgment passes J1–J5 (references/sweeps.md)

# Sweeps M1–M30 and Judgment Passes J1–J5 — paper-review

This file is the single source of truth for Phase 2. Follow it exactly.
Every sweep entry specifies: purpose · scope · enumeration procedure (script
when applicable) · artifact table columns · finding rules (one finding per
instance). Every judgment pass specifies what to look for and how deep.

Two appendices are defined at the end of the mechanical-sweep list: **M18**
(figure-legend length; always enumerated, with an optional proxy cap) and
**M19** (abstract/main-text length plus the user's cover-letter preference;
always runs). **M20** (OOXML style/formatting uniformity; always runs, and its
enumeration is supplied by the pipeline's code-side OOXML scan) follows them.
**M21–M24** are the earlier adopted sweeps; **M25–M29** are the
REWRITE-PARITY checks (the issue classes a from-scratch rewrite fixes as part
of its ordinary work: text/artwork term parity, house-style conventions,
claim→evidence coverage, sibling-definition symmetry, caption-promise parity),
**M30** is the SOURCE-HIERARCHY reconciliation (the DETECTION side of the
hierarchy the prompts use to resolve a conflict: a written claim against the
code or raw data that produced it), and **J5** is the architecture pass that
reports the rewrite-class issues no instance-level sweep can enumerate
(organization, paragraph order, transitions, cross-section redundancy). New
sweeps validated from the discovery round are appended after the adopted block
as **M31, M32…** in the same format — do not insert into the middle (IDs are
stable).

---

## CLASSIFICATION

Categories (stable labels, used in findings):
- **0 — Editor/Reviewer Concerns**: scope fit, rigor, overclaiming, ethics, data availability, figure quality (anything an editor or reviewer at the target venue could raise).
- **1 — Completeness & Factual Integrity**: mandatory items missing; factual errors; reference integrity; cross-document inconsistencies.
- **2 — Writing Quality, Logic, and Repetition**: grammar, narrative flow, one-message-per-paragraph, redundant phrasing, terminology conventions, document hygiene.
- **3 — Plagiarism and AI-Generated Content**: uncited related work, duplication, unattributed copying, evidence-based AI-content suspicion (always "possible", never an accusation), Springer Nature genative-AI policy compliance.
- **4 — Technical Formatting**: per-format rules (LaTeX refs, docx styles), alignment, fonts, headings, numbering, caption placement, math/notation, mixed formats.
- **5 — Missing / Unneeded Information**: guideline-required info beyond §1's list; superfluous files/content (drafts, internal notes, uncited items, PII).

Severity:
- **Critical** — factual errors, ethical/completeness gaps, data-integrity items; anything that could trigger rejection or a correction later.
- **Major** — issues an editor/reviewer/copyeditor would flag; guideline violations.
- **Minor** — polish, consistency, style.

Class mapping (the pipeline's sessions share ONE defect vocabulary; the judge
panel scores by these classes, highest priority first):
**correctness > consistency > preservation > completeness > formatting**.
The category above says where the issue was found; the class says what the
DEFECT is, and where a category splits you classify by the concrete defect:

| category | class |
|---|---|
| 0 Editor/Reviewer Concerns | `correctness` (unsupported claim, overclaim, UNDERCLAIM, rigor, ethics), `completeness` (required information or data availability missing) or `preservation` (removed content or a softened limitation) |
| 1 Completeness & Factual Integrity | `correctness` (factual error, wrong number/DOI/reference key, broken cross-reference) or `completeness` (a mandatory item that is missing) |
| 2 Writing Quality, Logic and Repetition | `consistency` (the same thing said, spelled or numbered two ways; a convention applied in one place and not another), `correctness` (the wording changes the meaning) or `formatting` (a one-off wording preference with no convention behind it) |
| 3 Plagiarism / AI-generated content | `correctness` (the integrity of the content itself) |
| 4 Technical Formatting | `formatting` (M18/M19/M20 rows; at most ±1 in a comparison and never decisive alone) |
| 5 Missing / Unneeded Information | `completeness` |

Name the class in the finding's explanation whenever it is not obvious from the
category: a revision or a judge that reads the finding must classify it the same
way, and an edit that cannot be named in this vocabulary is cosmetic (score 0).

**Both directions of every two-sided check.** A directional defect is only
checked when BOTH of its directions are examined, and a run that reports one
side has not run the check: a claim can be too STRONG (an overclaim) or too WEAK
(an underclaim -- a supported result hedged into vagueness); content can be LOST
(`preservation`) or INVENTED (`correctness`); an item can be MISSING or
UNNEEDED; a claim can carry NO pointer or a printed/promised item can carry NO
description; an availability claim can be STRONGER or WEAKER than the verified
locator. The `under` direction is a real defect of the same class as the `over`
direction, never a neutral preference for caution. The review's J3 rows and the
`CLAIM_STRENGTH.md` ledger the pipeline seeds enumerate both directions of the
claim-strength pair; the other pairs are stated in their own sweep (M5, M21,
M22, M27/M29) and in the class table above.

Conflict resolution priority (which occurrence is authoritative when documents
disagree — extends the reference-chat order):
**supplementary tables > supplementary figures/notes > main figures & legends > Methods > main text (Results/Discussion) > abstract > cover letter.**
If the authoritative value cannot be determined (e.g., only visible inside a
read-only image), mark the finding `unresolvable — manual verification required`.

Statuses: `resolvable` / `unresolvable — manual verification required` / `guideline-dependent`.

## FINDING FORMAT

Every finding is ONE instance, formatted:

```
F-NNN | location: <doc>/<section>/<paragraph|line|figure|table> | category: <0–5>
check: <M1–M30|J1–J5> | severity: <Critical|Major|Minor> | status: <...>
evidence: "<short verbatim quote of the exact word/number/phrase>"
problem: <1–2 sentence explanation>
```

Point to the specific erroneous word, number, or phrase — never the whole
passage. If a Zotero live field cannot be read properly, ignore that field and
tell the user to verify it manually.

A **J5 architecture finding** is the one deliberate exception to the
one-verbatim-instance shape: its `location` is a SCOPE (document + section +
paragraph range), its `evidence` is the current vs proposed reading order (a
short before → after outline, not a quote of an erroneous word), and its
explanation names the reader cost and the class (`consistency` when a
structural convention is applied unevenly, `writing` when the cost is flow
only). Everything else — one finding per scope, a real disposition, never
invented content — still applies. The `scope` is also recorded as its own
key in `findings.json` (`"scope": "<doc>/<section>/<par-a>–<par-b>"`) so the
revision stage can check that every reordering edit stays inside it.

---

# MECHANICAL SWEEPS (EXHAUSTIVE — MANDATORY)

Mechanical = every instance is enumerable in principle. Each sweep produces its
artifact BEFORE findings are derived. Zero findings is valid ONLY with a fully
disposed artifact.

## M1 — Acronym/abbreviation sweep (scriptable: `extract_acronyms.py`)

**Purpose:** the classic missed-issue class. Every acronym-like token gets a row.

**Enumeration:** run `extract_acronyms.py --work WORK [--out OUT]` on the corpus.
It extracts every acronym-like token via four detectors: strict (all-caps ≥2
letters: PCR, CRISPR; and mixed-case tokens containing an uppercase letter:
qPCR, mRNA, scRNA-seq, sgRNA, IL-6), gene-symbol shapes (Foxp3, Nrf2, CD8,
Tbx21, p53, p21, nf1, il6, stat3, mbd3, nrf2, C1, S100 — any letter run followed
by digits, with measurement nouns like `week12`/`group1` and version prefixes
like `v4` suppressed), a curated digit-free cell-type set (Treg, Tregs, cDC, pDC, Eomes, …),
and any tokens listed in `WORK/extra_acronyms.txt` (one per line) for
project-specific vocabulary. It EXCLUDES the reference list (including a
bibliography file such as a supplement's `.bib`), DOIs, accession numbers,
URLs, file paths, and SI units; statistical symbols and generic tokens
are listed with `EXEMPT (<reason>)` rather than dropped.

The same script also runs the reverse-direction audit (**M1b**) that a token
inventory cannot see: for every acronym whose definition it recorded, it
enumerates every occurrence of the un-abbreviated long form AFTER that
context's first long-form occurrence. The matcher is variant-tolerant, so
`copy number`, `copy-number`, `Copy-Number` and `copy numbers` all match one
recorded expansion (`copy-number (CN)`). A "context" is a section (abstract /
introduction / main text / Methods / each legend / each table / body of a
supplementary document) WITHIN one file, and the audit is deliberately NOT
licensed by a local definition: the reported failure mode is exactly
`copy-number (CN)` introduced in the abstract and the long form re-used
throughout the main text -- the old token row for `CN` read "defined at first
use: Y, consistent: Y" while the prose spelled the term out 50+ times. The
first long-form occurrence of each context is legitimate (it is that context's
own first use and may carry the definition); the definition site itself and
matches inside double quotes are never rows; and a row whose identical line is
rendered once per page (a PDF running head/footer) carries its repeat count so
one look disposes the whole family. The audit also counts each acronym's own
uses per context through its inflectional family (`CNs` counts as a use of
`CN`), so a definition is never mistaken for an orphan.

Manual pass: regex still cannot catch a token with neither an internal capital
nor a digit (e.g. a lowercase `tnf`), so read each file's title, headings, and
legend lines for such tokens, or declare them in `WORK/extra_acronyms.txt`
(case-insensitive). The manual pass also covers long forms the variant matcher
cannot see: a reworded synonym of the expansion (`aberration burden` for
`copy-number (CN)`), and a definition written without parentheses
(`copy-number, hereafter CN`). The artifact header prints every reference-list
region it skipped, with the boundary reason, so an inferred cut is never
silent.

**Artifact columns** (`M1_acronyms.md`): acronym | exempt? | expansion(s) as
written | n occurrences | defined at first use? | long form after first use
(n, per context) | files | first occurrence per context (title / abstract /
main text / Methods / each figure legend / each table footnote / cover letter)
| expansion consistent everywhere? Below the token table, the **M1b instance
table** lists every long-form residue row (acronym | context | location | long
form as written | excerpt) -- audit each of those rows individually.

**Finding rules — one finding per problem instance, never aggregated:**
- (a) used before it is defined (within abstract, main text, Methods, or any single legend).
  This includes the **acronym-first compound**: a sentence that writes the short form first and
  the expansion after it (`MALBAC-sequenced (multiple annealing and looping-based amplification
  cycles)`, `META-CS-sequenced (multiplex end-tagging …)`, `ground-truth haplotypes (phased
  single-nucleotide polymorphisms, SNPs)`) has used the token before defining it, and every such
  token is a finding (Minor, resolvable: put the long form before the short form at first use).
  When the sentence itself prints the expansion, the token IS an abbreviation being defined —
  "it is a tool/proper name, not an abbreviation" is NOT a disposition for it, and "it is
  defined in the same sentence" does not cure the order. A long form that follows a short form
  already in use is also rule (a), not rule (k).
- (b) never defined anywhere in the submission
- (c) defined but never used again (orphan definition) -- count the acronym's
  inflectional family before calling a definition orphaned (`CNs` is a use of
  `CN`, `HSPs` of `HSP`), and check the M1b table first: a definition whose
  long form is still in use after it is rule (k), not (c), and the right fix is
  to USE the acronym, never to delete the definition
- (d) two or more different expansions for the same acronym
- (e) two or more different acronyms for the same entity
- (f) redefined in main text after first definition
- (g) non-standard acronym used in a figure legend or table footnote without a local definition
- (h) non-exempt acronym in the title, or in the abstract that is not defined at first use within the abstract. Label these `[recommended]` (Minor) unless the current author guide makes them mandatory; the target venue may ask titles to avoid abbreviations (Nature Biotechnology does), but never present a convenience convention as a blocking requirement, and respect the standing exemption on length-driven cuts.
- (i) inconsistent formatting (scRNAseq vs scRNA-seq; HSP vs HSPs; hyphenation; case)
- (j) acronym coined for a term used fewer than 3 times in total
- (k) the un-abbreviated long form is used again after that context's own first
  long-form occurrence (e.g. `copy number`, `copy-number`, `Copy-Number`,
  `copy numbers` used throughout the main text after `copy-number (CN)` was
  introduced in the abstract). EVERY row of the M1b instance table is ONE
  finding (Minor, resolvable): substitute the defined acronym for that
  occurrence (edit rule P1a in the revise skill) -- never expand a short form,
  never delete the abbreviation's definition.
  - the context's FIRST long-form occurrence is not a row (each context may
    introduce the term at its own first use), and the definition site itself
    and matches inside double quotes are excluded by the script, so a quoted
    title is never a finding;
  - dispose a row OK ONLY with a recorded reason: a quoted title or proper name
    that must stay verbatim, a phrase that is genuinely a different term of
    art, or a generated rendering (figure PDF, build output) whose text is
    regenerated from code or from a source that is also in the corpus -- name
    the source and route the fix there;
  - a reworded synonym of the long form (`aberration burden` for `copy-number`)
    is not matched by the script; catch it in this manual pass and record it
    with the same remedy.

**Exemption:** universal abbreviations (DNA, RNA, ATP, SDS-PAGE, PBS, SD, SEM,
ANOVA, SI units, statistical symbols) need no redefinition. If unsure whether
an abbreviation qualifies, do NOT skip it — report with status
`guideline-dependent`.

**Legend/table-footnote rule:** redefine non-standard abbreviations at first
appearance in each legend/footnote so they stand alone (readers skim figures
independently of the main text).

## M2 — Citation sweep (scriptable: `extract_citations.py`)

**Purpose:** every in-text citation vs. the reference list.

**Enumeration:** run `extract_citations.py`. Handles numeric ([1], [1,2],
[1–3]) and author-year styles, `.bib` files, numbered and unnumbered reference
lists. Extend it in WORK/ for other styles (e.g. superscript numbers) instead
of eyeballing.

**Artifact:** `M2_citations.md` — every reference-list entry (one row) and
every in-text call-out (one row) + auto-derived mismatches.

**Finding rules (one per instance):**
- cited but not in the reference list (orphan call-out)
- listed but never cited (uncited entry)
- duplicate reference entries
- misordered numeric call-outs / list numbering gaps
- wrong citation content: authors, year, journal, volume/pages, DOI (verify against internal knowledge; flag suspected hallucinated/nonexistent references — flag, never guess)
- citation-style deviations from the journal's style
- author-year ambiguity (two same-author-same-year entries without a/b disambiguation)

**Reference resolution (read-only).** When the `zot` CLI (pyzotero-cli) or the
`$zotero-use` skill is available, resolve each shortlisted item read-only
(`zot --local ... items get|citation|bib`, `zot fulltext get`) before calling a
citation wrong: cite PARENT bibliographic item keys, never attachment keys, and
confirm the parent's own metadata (title, creators, year, DOI). An item that
cannot be resolved is `unresolvable — manual verification required`. This skill
never edits a citation field and never writes to the Zotero library; a suspected
metadata error (wrong year, wrong DOI, wrong item) becomes a finding with the
proposed correction — item key, field, current value, proposed value, evidence —
for paper-revise or the user to apply under their Zotero policy.

**Scope rules for the auto-derived checks:** every file that carries its own
numbered reference list is its own numbering space — orphans, uncited entries,
duplicate numbers and order violations are computed per document (the artifact
also prints the union view). Author-year call-outs matched by the script are
`(Smith et al., 2019)`, `Smith et al. (2019)`, `Smith and Jones 2019`,
`Smith & Jones, 2019` and `(Smith, 2019)`; a bare `In 2020` is NOT a call-out.
Bracketed numbers directly after a measurement word (interval, range, threshold,
score, value, level, age, dose, time, size, …) are recorded as
`suspect_brackets` and never counted as citations. Unnumbered lists are
enumerated entry by entry (wrapped continuations are merged), so "listed but
never cited" is auditable for author-year styles too; the artifact prints the
reference-list region it read, with the boundary reason.

## M3 — Display-item sweep (script-assisted)

**Purpose:** every figure, table, panel, and supplementary item: defined ↔
called-out ↔ numbered, in both directions.

**Enumeration:** script or manual table of every display item defined in the
submission (main figures, tables, supplementary figures/tables/notes,
extended data) with its label; then every call-out in the text ("Fig. 3",
"Supplementary Table 2", "Fig. 1b", "(Supplementary Note 3)").

**Artifact:** `M3_display_items.md`: item | type | defined at (file:line) |
called out at (all occurrences) | panel sublabels | legend present? |
legend self-contained?

**Finding rules:**
- called out but never defined (e.g., "Fig. 3" with only 2 figures)
- defined but never called out in the text (uncited item)
- label mismatches (Fig. 2 vs Figure 2; Supplementary Fig. S1 vs Supplementary Fig. 1)
- panel letters missing or out of order (a, b, c…; flag missing letters only when panels exist)
- legend not self-contained: references the main text for n, error bars, or test definitions
- figure file present in the directory but not referenced by the manuscript, and vice versa

## M4 — Numbers & metrics sweep (script-assisted: `extract_numbers.py`)

**Purpose:** the long-range conflict class — the same labelled metric (p, n,
AUC, percentage, CI, R², fold-change) reported with different values in the
abstract, results, figure legend, table, Methods or supplementary text.

**Enumeration:** run `extract_numbers.py`. Enumerates labeled metrics
(p-values, n, AUC, percentages, CI, R², fold-changes), accession numbers
(GEO/SRA/ArrayExpress/Zenodo), and software versions, each with every
occurrence location. Then AUDIT the table: for each metric that appears in
more than one context (abstract vs results vs legend vs supplementary),
confirm the value agrees with the authoritative source per the conflict
priority.

**Finding rules:**
- same metric, different values across abstract/main text/legends/supplementary
- error bars / n / statistical test undefined or inconsistent in a legend (also feeds J2)
- accession number inconsistent, malformed, or missing where data availability requires it
- software version inconsistent between Methods and supplementary/code
- percentages that do not sum to ~100 where they logically must
- numbers in figures that contradict text numbers (if figure is readable; else `unresolvable`)

## M5 — Mandatory-items sweep (script-assisted: inventory + manual)

**Purpose:** every item the submission must contain, checked across the
ENTIRE directory regardless of editability.

**Enumeration — the checklist itself is the enumeration:**
cover letter (addressed to editor; significance; plain formatting) · title
page (title, authors, affiliations, corresponding author + email, ORCID) ·
abstract · main text · Methods · references · figures with legends · tables ·
combined Supplementary Information (where required) · the venue's
own reporting summary (the Nature Portfolio Reporting Summary when that is the venue) · data availability statement · code availability
statement · author contributions · competing interests declaration ·
funding/acknowledgements · ethics/consent statements (IRB/animal approval
where applicable) · permissions for reused material · accession numbers ·
(preprint disclosure; clinical-trial registration if applicable).

**Artifact:** `M5_mandatory.md`: item | present? (Y/N/partial) | file(s) |
guideline status label ([required at initial submission] / [required at
revised-submission stage — prepare now] / [recommended]).

**Finding rules:** one finding per missing or partial item. Do not invent or
fabricate missing data; note a placeholder may be needed and report every gap.
The sweep runs in BOTH directions: the enumeration above finds what the
submission must have and does not, and the same pass disposes what it HAS and
must not ship -- a draft, an internal note or meeting record, a duplicate of a
shipped item, personal or confidential material (PII), a document that
identifies the authors under a double-anonymized submission. Category 5 is
"Missing / Unneeded Information" for that reason: an unneeded item is the
mirror of a missing one and is class `completeness` too. The two halves need
different evidence, so an item may be `unable — <reason>` when the corpus
cannot show whether it is required or forbidden; it may not be silently skipped.

## M6 — Placeholder & hygiene sweep (scriptable: regex)

**Enumeration:** regex sweep over the corpus for: TODO, TBD, XXX, FIXME,
[?], [AUTHOR], {{template}}, `Lorem`, highlighted text markers, residual
tracked changes / comments (docx converter flags these in inventory notes),
stray metadata/PII (docx creator/lastModifiedBy properties — converter flags),
double spaces, "Citation" placeholders left by reference managers.

Formatting-only signals (highlighting, comment text, tracked-change rendering)
are not observable in the plain-text corpus. Dispose those rows from the
inventory notes, and for anything the corpus cannot show record
`unable — not observable in corpus`; never mark it `clean` by default.

**Artifact:** `M6_hygiene.md`: pattern | file | line | excerpt | disposition.

Pipeline convention: the literal token `[AUTHOR TO COMPLETE: ...]` is the
revision skill's hand-off marker for content it is forbidden to invent. A row
that matches it is disposed as "pipeline hand-off placeholder — manual item,
carried forward" and goes to the manual-verification list; the MARKER is never a
finding. The underlying gap still counts as a gap and is reported as such.

## M7 — Cross-reference sweep (LaTeX + Word)

**Purpose:** internal reference machinery integrity.

**Enumeration (LaTeX):** every `\label{...}` and every `\ref{...}`/`\eqref`/
`\cref`/`\Cref`/`\pageref` — pair them. Also enumerate raw
"Supplementary~Fig.~1"-style literals (should be `\cref`/`\Cref` when
feasible), `\includegraphics`/`\input`/`\include`/`\addbibresource` targets vs
files that exist, package usage, duplicate labels.

**Enumeration (Word/markdown):** "see Section X", "as shown above/below",
figure/table call-outs (overlaps M3 — dedupe at merge), cross-ref fields
flagged by the converter.

**Artifact:** `M7_crossrefs.md`: reference | target | file:line | defined?
| resolved?

## M8 — Terminology-consistency sweep (script-assisted: `extract_occurrences.py`)

**Purpose:** one consistent term per entity; style variants.

**Enumeration:** from the M1 artifact, take every non-exempt acronym and
multi-word term; run `extract_occurrences.py --term <term>` for each
high-value term (also detects hyphen/space/case/plural variants). For species
names: enumerate every occurrence of genus/species tokens. For
gene/protein symbols: enumerate each symbol's occurrences.

**Artifact:** `M8_terminology.md`: entity | variant forms found | counts |
locations | consistent?

**Finding rules:**
- same entity referred to by 2+ different terms/variants (one finding per entity, listing both variants' locations)
- species names not italicized / genus abbreviated before first full mention
- gene vs protein nomenclature convention violations ( italics, capitalization per convention)
- mixed spelling conventions (US vs UK English within the same document)
- inconsistent decimal places for the same metric type

Acronym long-form/short-form pairs are NOT M8 variants: a defined acronym
legitimately has both surface forms (long at first use, short afterwards), so
their placement is governed by M1's position-aware rules (a)/(k) and the M1b
instance table, never by this blanket variant rule. M8 still catches two
genuinely different terms for the same entity (e.g. `participant` vs `donor`
where the text never defines them as the same cohort).

## M9 — File-format & naming sweep (scriptable: inventory)

**Purpose:** the submission's file hygiene.

**Enumeration:** from `inventory.json`: every file, its role, extension,
duplicate roles (two "main text" files?), version-junk filenames (v2, FINAL,
old, backup, copy, ~), mixed formats for the same role (one figure as .tif +
.png), zero-byte or corrupted files, files that belong to a different
manuscript (name/content mismatch), stray personal/confidential files.

**Artifact:** `M9_files.md` extends the inventory with flags.

## M10 — Reference-format sweep (script-assisted)

**Purpose:** each reference entry's internal format vs journal style.

**Enumeration:** every entry from the M2 artifact is audited for: journal
style match (Nature-style abbreviations, author format), DOI presence/format
where required, required fields per entry type (year, journal, volume, pages),
italicization of journal names, en-dash ranges, "et al." usage limits.

**Artifact:** `M10_ref_format.md`: entry # | field | deviation | disposition.

## M11 — Numeric/SI formatting sweep (scriptable: regex)

**Purpose:** presentation of numbers and units.

**Enumeration:** regex sweep: SI unit usage (µL vs uL vs μl; mM vs M;
spaces between number and unit), leading zeros for p-values (0.05 not .05),
thousands separators, percent vs % consistency, degrees (°C), fold-change
format, time formats (12 h vs 12 hours), En-dash in numeric ranges.

**Artifact:** `M11_si.md`: file | line | token | issue | disposition.

## M12 — Author/affiliation sweep

**Purpose:** author metadata consistent everywhere it appears.

**Enumeration:** every author-list occurrence: title page, cover letter,
manuscript header, supplementary, Reporting Summary (if text-readable), docx
metadata. For each: names, order, initials, affiliations, corresponding
author, ORCID.

**Artifact:** `M12_authors.md`: author | occurrences | consistent?

**Finding rules:** one finding per inconsistency (name spelling/order/
initials differ; affiliation number mismatch; corresponding author email
differs; ORCID missing where required).

## M13 — Reporting-summary consistency sweep

**Purpose:** the Reporting Summary's answers vs the manuscript's claims.

**Enumeration (only if a Reporting Summary is present and text-readable):**
every question/answer pair in the summary (n, statistical tests, replication,
randomization, blinding, data availability, code availability, ethics) →
enumerated against the corresponding manuscript statement.

**Artifact:** `M13_reporting.md`: summary item | answer | manuscript statement
| file:line | agrees?

## M14 — Cross-document metadata consistency sweep (validated: iteration-1)

**Purpose:** the cover letter / title page / manuscript / SI / Reporting Summary
must agree on the submission's own metadata: title, journal name,
corresponding-author email, author block, ORCID — including
placeholder/reserved-domain detection.

**Enumeration (scriptable):** compare the exact title string, journal name,
corresponding email, author list, and ORCID across every file (title page,
cover letter, manuscript header, abstract page, supplementary, reporting
summary if present); regex flags IANA-reserved placeholder domains
(example.com/.edu/.org, .test, .invalid) and "firstname.lastname@" patterns
that differ across files.

**Artifact:** `M14_metadata.md`: field | value per file | files | consistent? |
placeholder-domain?

**Finding rules (one per instance):**
- title differs between any two documents
- corresponding email differs between any two documents, or uses a
  reserved/non-deliverable domain
- journal name differs or is missing where addressed
- author list/order differs; ORCID present in one file but absent where required

Validation: iteration-1 instances X-001 (cover-letter title mismatch — caught
only by the discovery probe) and F-035 (email mismatch + example.edu domain).

## M15 — Numeric-total reconciliation sweep (validated: iteration-1)

**Purpose:** prose totals must reconcile with table sums; cohort sizes must
reconcile with n = statements and row counts.

**Enumeration (scriptable):** parse every supplementary/main table, sum each
numeric column, and pair each sum with prose claims of that total (regex
"N cells", "N samples", "a total of N"); also enumerate every "n = N"
statement and every cohort-size statement and compare them.

Corpus format: each sheet appears as `### sheet: <name>` followed by one
pipe-separated line per row, zero-padded to the widest column of that sheet, so
column positions in the text match column positions in the table (sparse and
merged rows included). Sum by position, and state in the artifact which column
index you summed.

**Artifact:** `M15_totals.md`: claimed total | source (file:line) | computed
sum | table | agrees?

**Finding rules (one per instance):**
- prose total ≠ column sum (including when a placeholder cell makes the sum
  impossible)
- n = statement conflicts with cohort size stated elsewhere or with table row
  count
- sample/patient counts differ across abstract/results/legends/SI

Validation: iteration-1 instances F-027 (n = 15 vs 12-patient cohort),
F-028 (71,402 total vs table sum 72,982), F-034 (S11 = XXX placeholder cell) —
all caught only by manual audit before this sweep existed.

## M16 — Abstract traceability sweep (validated: iteration-1)

**Purpose:** every statistic and headline claim in the abstract must be
traceable to a main-text/Methods statement (the abstract is a review surface
of its own).

**Enumeration (scriptable):** extract every number/statistic from the abstract
(p, AUC, n, percent, fold, CI, counts) and enumerate occurrences of the same
value across the rest of the corpus (`extract_occurrences.py --value`);
each abstract value gets a row.

**Artifact:** `M16_abstract_trace.md`: abstract value | phrase | occurrences
elsewhere | traceable?

**Finding rules (one per instance):**
- abstract statistic with zero occurrences in Results/Methods/SI
- abstract statistic whose label/context differs where it recurs (e.g.,
  attached to a different test)

Validation: iteration-1 instance F-029 (p = 0.021 appearing only in the
abstract).

## M17 — Anomaly-token sweep (validated: iteration-1)

**Purpose:** present-but-unexpected tokens that no value-consistency check can
catch: species names in unexpected contexts, nonstandard control types,
"not shown" statements, internal author notes disguised as prose,
reviewer-response residue.

**Enumeration (scriptable):** (a) every species binomen outside Methods,
(b) every "not shown"/"data not shown" statement, (c) every control-type
token (ERCC, FMO, spike-in, mock, isotype) with its defining location,
(d) genre-inappropriate tokens ("we recommend", "as we told the reviewer",
"please"); model audits each row.

**Artifact:** `M17_anomalies.md`: token | file:line | context | expected? |
disposition

**Finding rules (one per instance):**
- control type never defined/justified in Methods yet referenced in a legend
- "not shown" statement without SI pointer or justification
- species name appearing where the study design does not explain it
- internal-review or workflow language left in submission prose

Validation: iteration-1 instances X-002 (E. coli spike-in sentence in the
Fig. 1 legend, study has no spike-in) and F-046 (TODO note in Methods).

## M18 — Figure-legend length (always enumerated; the cap is optional)

**Purpose:** the target venue's formatting guide requires a figure legend
not to exceed "the word limit of the article type" but publishes no number (the
default Nature Biotechnology profile: checked against its submission
guidelines, 2026-09-19). M18 therefore ALWAYS
enumerates every legend's word count; the orchestration pipeline may add a proxy
cap (`--caption-limit N`, default 0 = no cap) to turn a count into a reportable
over-cap item.

**Enumeration:** every figure caption / legend in the corpus (the leading
"Figure N |" label and title count; labels drawn inside the artwork do not)
into `M18_caption_words.md`: document | caption id | word count | disposition.

**Finding rules (one per instance):**
- a legend over the configured proxy cap → FORMATTING-tier item; it is reported
  and, only where redundancy can be removed, compressed — never by deleting
  scientific content, claims, limitations or needed methodological detail, and
  never by stripping a hedge that carries the legend's own claim strength (a
  real limitation or an uncertainty the data support): that would be a
  `correctness` overclaim, not a shorter legend. The same rule as M19's
  compression, in the legend's own words.
- no cap configured → the count is recorded with the disposition "recorded —
  the venue's per-type limit is not published; author to compare"; the word
  count alone is neither a defect nor a scoring difference
- a legend that is defective for an independent reason (method detail, unclear
  panel description, missing error-bar definition) → the normal
  clarity/formatting finding

Legend length never makes a version ineligible and never decides a comparison
on its own.

## M19 — Abstract/main-text length (always runs)

**Purpose:** the venue profile's own length limits apply, relaxed by the
profile's own margins — this replaces the former blanket "abstract/main-text
length is exempt" standing exemption. For the default Nature Biotechnology **Article** profile the base
limits are abstract ≤ 150 words and main text ≤ 3,000 words, with the main text
EXCLUDING the abstract, Methods, references and figure legends; this pipeline
allows **abstract +15% (≤ 172 words)** and **main text +25% (≤ 3,750 words)**.
Another content type takes that type's own base numbers from the journal's
content-types table with the same two margins, and the artifact must name the
base and its source. A venue profile that declares different numbers (or none)
replaces all of them: read the limits from the profile of the run you are in
(`venue_profiles/README.md` documents the schema).

**Counting rule (all word counts):** a word is a maximal run of NON-SPACE
characters, with a newline treated as space — `state-of-the-art` is ONE word and
`2026` is ONE word. `scripts/count_words.py` implements this exactly (`--json`
for machine output); use it for the counts instead of estimating.

**Cover letter (user preference, NOT a journal rule).** The default Nature
Biotechnology profile's official "Preparing your material" page states what the
cover letter must explain and disclose but states no cover-letter word limit
(checked 2026-09-19); a venue profile may configure its own range instead.
The master prompt's own preference is therefore carried as a USER
PREFERENCE: the PERSUADING part (the body explaining importance and
suitability; excluding the salutation, the signature block and required
disclosures such as related manuscripts, prior editor discussions,
double-anonymized author details and reviewer suggestions) should be
**300-500 words**; outside that range is a MINOR formatting item, never a
journal requirement and never gated. `count_words.py --cover-letter` counts it.

**Enumeration:** for every document that carries one, one row per section into
`M19_length.md`: document | section (abstract / main text / cover letter) | word
count | the base limit applied and its source | the allowed cap | disposition
(OK / over cap → finding id / over cap but not compressible without losing
content → manual verification item). Say in the artifact which text was counted
as the main text. When no editable manuscript or cover letter exists and the
text lives only in a PDF/slide rendering, the row is `unable — the only copy is
not editable; the author must convert/count it` (a manual item), never a silent
skip.

**Finding rules (one per instance):**
- abstract over the cap → CATEGORY-4 (technical formatting) finding
- main text over the cap → CATEGORY-4 (technical formatting) finding
- cover letter's persuading part outside the user's 300-500-word preference →
  MINOR formatting finding (labelled as the user's preference, not a venue rule)
- a section that cannot be brought within the cap without losing content →
  `unable — needs the author's judgement`, listed for manual action

**Never:** flag UNDER-length text (the limits are upper bounds; no minimum is
invented), cut text that is within the cap for length reasons, or delete
scientific content, claims, limitations, data or needed methodological detail to
reach a cap. Length is never a gate: it never makes a version ineligible and
only ever enters a comparison through the formatting tier.

**What compression may remove -- and what it may not.** Redundancy, repeated
statistics and hedging that carries no meaning are removable. A hedge that
carries the claim's own strength -- a limitation, an uncertainty the evidence
supports, a result reported as uncertain because it is -- is CONTENT: stripping
it turns an accurate claim into an overclaim, which is a `correctness` defect
and not a shorter version. Likewise a compression must never STRENGTHEN a claim
to save words. If the only way to reach the cap is to move a claim's strength in
either direction, the section is `unable — needs the author's judgement` and
stays as it is.

## M20 — OOXML style/formatting uniformity (always runs)

**Purpose:** the corpus converters read text only, so a candidate can pass every
other sweep while shipping a blank page, a running head on the title page,
mixed hyperlink/plain URL and email treatments, per-figure legend spacing,
heading style drift or an italic correspondence block. M20 makes the OOXML
formatting visible, enumerable and repairable. The orchestrator enumerates it
(the code-side scan of the reviewed corpus) and normalizes the mechanical
classes before a candidate is fingerprinted, pinned or judged.

**Enumeration:** `review/work/FORMAT_SCAN.json` (the code-side scan of `base/`,
repeated as rows in `review/artifacts/M20_formatting.md`): every `.docx` of the
corpus, skipping revision auxiliaries (`*.tracked.docx`, `*.before-after.docx`)
and stage scratch (`work/`). AUDIT that table row by row and ADD every
formatting defect the scan cannot see (font family/size, justification, line
spacing, legend placement, table formatting, heading numbering). Columns:
rule | severity | location | evidence | fix kind | disposition.

**Finding rules (one per instance):**
- a break-only empty paragraph, a rendered blank page, the running head on the
  title page, tracked changes or proofing markers in a final package → finding
  (a rendered blank page is the ground truth; the XML rows explain it)
- legend line spacing that is not single (`w:line=240`), or legend paragraph
  spacing that differs between figures → finding
- a heading without `keepNext`/`keepLines`, or heading runs whose direct size
  contradicts the heading style → finding
- an italic run in the title/affiliation/correspondence block, an italic
  "et al." or a journal title that is not italic in a reference, italics on a
  URL/email → finding; when the run is inside a Zotero field the row is marked
  `field-protected` and the fix is the CSL style or unlinking the fields in the
  submission copy
- mixed URL/email treatments (hyperlink + plain, differing colour/underline/
  italic) → one finding per treatment set
- mixed straight/curly quotation marks, a spaced hyphen used as a dash, or
  em-dash density above the user's cap → finding (editorial: the revision arm
  rewrites; never a mechanical replacement of meaning-bearing text)
- a layout defect the renderer shows but the XML scan cannot (overlap, clipping,
  misaligned columns) → finding from the visual pass

**Artifact:** `review/artifacts/M20_formatting.md` (the seeded table, every row
disposed) plus `review/work/FORMAT_SCAN.json`.

Formatting never makes a version ineligible and never decides a comparison on
its own; a uniform candidate may be preferred to an inconsistent one by at most
±1 in the formatting tier.

---

# JUDGMENT PASSES (deep, systematic; may be prioritized)

Judgment checks require interpretation. They still produce findings one-per-
instance with quotes, but their coverage is deep-and-prioritized rather than
exhaustive-by-enumeration.

## J1 — Scope fit & significance

Breadth of interest, novelty/technical advance, suitability for the
target journal specifically; whether the cover letter articulates the significance in plain
terms for editors; whether claims of broad interest are supported -- and, in the
same pass, whether a claim of broad interest the work DOES support is left
unstated or undersold. An unsupported claim and an undersold advance are the two
directions of one failure (the claim's strength does not match the evidence), so
a manuscript that hedges its own advance away is as reportable as one that
inflates it.

## J2 — Scientific & statistical rigor

Exact p-values (not just <0.05), error bars and n defined in every figure
legend, sample sizes per analysis, multiple-comparison correction, effect
sizes with confidence intervals, controls, power/blinding/randomization where
applicable. Computational/ML rigor where relevant: train/test contamination
(data leakage), independent external validation, baseline comparisons,
reproducible splits/seeds, calibration, uncertainty quantification, benchmark
fairness. Methods reproducibility: enough detail (parameters, software
versions, seeds, data splits, hardware, accession numbers) to reproduce the
work.

Report statistical precision in BOTH directions: an inequality where the exact
value is known ("p < 0.05" for a value the analysis printed) hides information,
and digits the design cannot support ("p = 0.0413" or a mean quoted to four
decimals from three samples) invent it -- a claim's precision is part of its
strength, so both are rigor findings.

## J3 — Writing quality, logic, and claim calibration (overclaiming and underclaiming)

Semantic/grammatical/syntactic errors (subject–verb agreement; tense and voice
consistency — past for results/methods, present for established facts;
ambiguous antecedents; dangling modifiers). Paragraphs that do not convey
exactly one key message; sections lacking cohesive narrative flow; missing
transitions; Results/Methods content mixed inappropriately. Redundant
phrasing: identical text repeated within the same paragraph/section (unless
explicitly a cross-reference); repetition across sections only when the
statement's purpose changes (Results reporting vs Discussion interpretation);
flag recurrence that adds nothing. Overclaiming: unsupported
"first/novel/state-of-the-art" claims, causal language for correlational
results, generalization beyond tested conditions, "significant" for a trend, and
an equivalence or "no effect" claim drawn from a non-significant test (absence of
evidence is not evidence of absence).

**Underclaiming -- the same defect read in the other direction.** A claim the
evidence supports, stated BELOW its supported strength: "may", "could", "it is
possible", "would seem to", "we speculate", "appears to", "suggests", "is
consistent with", or "a trend" for a significant, adequately powered result; a
conclusion the data establish left as "preliminary"/"exploratory"/"descriptive"
without a stated reason; a limitation written as a retreat that undersells what
was actually shown; the manuscript's own supported advance never stated. Both
directions are `correctness` findings -- the claim's strength does not match the
evidence -- and the fix runs only as far as the evidence goes: raise an
underclaim to exactly what the data support, lower an overclaim to exactly what
they support, never past either. A hedge the design genuinely requires (a real
limitation, uncertainty the data cannot resolve) is CORRECT and is not a
finding: the check is the CALIBRATION, not the presence of hedging, and an
underclaim finding must name the evidence that supports the stronger statement.
A session that reports only the overclaim direction has not run J3.

## J4 — Plagiarism, AI-content & policy compliance

Uncited very-related works (including preprints) to the extent detectable
from internal knowledge — state clearly when no live search is available.
Verbatim/near-verbatim duplication within the submission (across documents or
sections), overlap with published literature or the authors' own prior work
(state limits of internal-knowledge detection). Unattributed copied text
(methods, legends). Possible AI-generated content ONLY with concrete evidence
(hallucinated citations, internally inconsistent fabricated details,
characteristic stylistic patterns) and ALWAYS labeled "possible" — never a
definitive accusation. Springer Nature generative-AI policy: AI tools must
not be authors; generative-AI use (text/images) must be disclosed;
AI-generated images restricted — flag the ABSENCE of a disclosure statement as
a guideline finding, not as proof of use.

## J5 — Architecture & rewrite-class pass (scope-level, one row per scope)

The other half of what a from-scratch rewrite does: it reorganizes. Section
order, paragraph order, the order of statements inside a passage, transitions,
one-message-per-paragraph, cross-section redundancy and whether the advance
lands early are properties of a SCOPE, not instances of an erroneous word —
enumerating them one sentence at a time is what the instance-level sweeps
cannot do, and pretending otherwise hides them. This pass reports them so the
revision stage can act on them; it is not a licence to change content.

**Scope:** every document, section by section, paragraph by paragraph. Build on
`WORK/OUTLINE.md` (the seeded hierarchy scaffold) — its `summary` column is the
per-paragraph claim map this pass reads.

**What to look for (in this order, per scope):**

1. **Claim-first order.** Does the section lead with the question/advance and
   then the evidence, or does it make the reader hold unexplained setup until
   the end? Check the abstract, each Results subsection, the Discussion opening
   and the cover letter's first paragraph.
2. **Paragraph architecture (one message per paragraph).** Do sibling
   paragraphs under one heading each carry one distinct claim, or is one idea
   split across two paragraphs / two ideas packed into one? OUTLINE summaries
   that repeat, overlap or need their neighbour to make sense are the evidence.
3. **Reading order inside a passage.** Within a paragraph or a short run of
   paragraphs, are statements ordered as claim → evidence → implication, or
   does a caveat/method detail arrive before the reader knows what it qualifies?
4. **Transitions and signposting.** Does each section tell the reader why the
   next one follows (a connective sentence, a forward pointer), or does the
   manuscript jump? Absent glue is the defect; it has no quote.
5. **Cross-section redundancy.** The same fact/purpose stated in two places
   where one would do (Results vs Discussion, main text vs legend vs cover
   letter) — one row per repeated scope pair, with both locations.

**Artifact.** `review/ARCHITECTURE.md`: one row per scope —
`document | section | paragraphs | current structure | reader cost | proposed
reorganization | class | severity | disposition`.
A scope that is fine gets its own row with a row-specific
`OK — <why this order serves the reader>`; a scope needing work carries a
finding id. A document with no rows at all is an unfilled artifact.

**Finding rules (one finding per SCOPE, never per sentence).** `check: J5`,
category 2, class `consistency` when a structural convention is applied
unevenly across sibling scopes and `writing` when only flow is at stake;
severity Major when the reader cannot recover the argument without re-reading,
Minor otherwise. The explanation must state the reader cost and the proposed
order; the evidence is a short current → proposed outline. Content is never
changed: the same claims, numbers, citations, limitations and conclusions, in
a different order. A scope whose only "fix" would invent or delete content is
`unable — <reason>`, never a finding.

---

# COVERAGE TABLE (final acceptance gate)

| check | disposition | basis |
|---|---|---|
| M1 | N findings / clean / unable — reason | artifact M1_acronyms.md, N rows |
| ... | ... | ... |
| J4 | ... | locations examined |

"Not checked" is not an allowed value. "Unable — <reason>" rows repeat in the
summary note with their reasons.

The coverage table carries every check ID this skill defines: M1–M30 and
J1–J5 (M18, M19 and M20 are always active). J5's row names
`review/ARCHITECTURE.md` as its basis.

---

# THE DISPOSITION BAR (read before you fill any `disposition` cell)

A disposition is a DECISION about the row, not a sentence in its cell. Three
rules apply to every seeded table (M18, M19, M20, M4/NUMBERS_LEDGER, M8, M24,
M25–M29, GLOSSARY, IDENTIFIERS, PLACEHOLDERS, PLACEHOLDER_LOOKUP, OUTLINE,
ARCHITECTURE):

1. **Name the row's own bar.** `OK — <reason>` must be about HOW that row is
   measured: its rule id, the section it sits in, the bar it is inside, or the
   finding id it became. "No journal rule", "editorial preference only",
   "cosmetic" and "not an error" are NOT reasons: a writing-quality defect does
   not need a journal rule to exist. A row whose `tier` is `finding` is a defect
   an editor or a copyeditor would raise — either file it or say why this
   instance is inside the bar.
2. **Never close many rows with the same sentence.** The postcheck counts
   repeated dispositions; a blanket rationale shared by many finding-tier rows
   is recorded as an UNFILLED artifact, and `decide --residual-gate` refuses to
   certify the run on it (`setup --strict-artifacts on` fails the attempt). Real
   example this rule exists for: 96 rows closed with one identical "no journal
   rule" sentence, with the operator's own complaints inside that pile.
3. **OUTLINE.md is a decision table too.** A `summary` copied back from
   `first sentence`, an empty summary cell, or one verdict on every row is
   unfilled, not audited. Write what the paragraph CLAIMS.

A `searchable` hand-off marker is not a manual item when the orchestrator's
lookup answered it: `work/PLACEHOLDER_LOOKUP.md` (seeded by the pipeline) gives
`found` (the fact) or `absent` (a VERIFIED NEGATIVE, e.g. "not posted") —
either way it is a finding for the revision stage, not a carried-forward
question. Only `author-only` facts and failed lookups stay on the manual list.

---

# M21–M24 (adopted from the discovery rounds)

## M21 — Correspondence-policy sweep

**Purpose.** The cover letter is a submission document with its own policy
surface (reviewer exclusions, conflict statements, preprint disclosure,
related-manuscript disclosure, suggested reviewers' deliverability) that no
manuscript sweep covers.

**Enumeration.** For every cover-letter file: (i) every requested reviewer
exclusion with its stated reason, (ii) every suggested reviewer with name and
e-mail domain, (iii) every required disclosure line (related manuscripts, prior
discussions, preprint status, competing interests, author approval) and whether
it is present, (iv) every factual claim the letter makes about the manuscript's
own results.

**Artifact.** `M21_correspondence.md`: item | as written | policy expectation |
deliverable? | disposition.

**Finding rules (one per instance).** An exclusion request without a conflict
basis · a suggested e-mail on a retired/placeholder domain · a missing required
disclosure · a letter claim that exceeds the manuscript's own evidence (compare
against the manuscript, not against the letter) · a letter claim that falls
SHORT of it (an underclaim: a supported result or an obvious strength of the
work the letter undersells or leaves out -- the letter is read against the
manuscript's evidence in BOTH directions, and the same result may not be an
overclaim in one run and unexamined silence in the next).

## M22 — Data/code-availability integrity sweep

**Purpose.** Availability statements are checked for *presence* today (M5), not
for whether the locator form supports the claim made about it.

**Enumeration.** Every URL/accession/DOI in Data availability, Code
availability and Methods, with the claim sentence that carries it; classify each
locator (DOI / repository DOI / version-pinned repository URL / bare repository
URL / accession / placeholder) and check the claim against the class. The
orchestrator seeds `work/IDENTIFIERS.md` with its own public-API verdict
(`found` / `absent` / `error` / `skipped`): use it, re-derive it if it is
`skipped`, and never guess a DOI.

**Artifact.** `M22_availability.md`: claim | locator | locator class | supports
claim? | disposition.

**Finding rules (one per instance).** A "permanent archive" claim carried by a
bare/version-pinned repository URL · a "publicly available" claim whose locator
does not resolve · two different commit pins for the same repository where the
statement says the pin produced the published numbers · an accession without a
database name · a hand-off DOI placeholder (resolved or explicitly reported as
not yet deposited) · an availability statement WEAKER than the verified reality,
which is the same defect read in the other direction: data described as
"available upon request" (or "not yet deposited") while the corpus's accession,
repository URL or the pipeline's own `IDENTIFIERS.md` lookup shows a public,
resolving deposit; a "restricted" claim contradicted by the locator class. The
statement and the locator must agree in BOTH directions, and an
`absent`/`found` verdict from `work/IDENTIFIERS.md` is the evidence either way.

## M23 — Supplementary parity sweep

**Purpose.** The SI is a second document with its own numbers, cross-references
and availability statements.

**Enumeration.** For each SI source: every numeric claim, every
`\cref`/literal cross-reference, every availability statement, every
abbreviation definition and every term-family choice, paired with the
main-text counterpart (the pipeline's `work/NUMBERS_LEDGER.md`,
`work/M24_concepts.md` and `work/IDENTIFIERS.md` carry the code-side rows).

**Artifact.** `M23_supp_parity.md`: item | SI statement | main-text counterpart
| agrees? | disposition.

**Finding rules (one per instance).** An SI number that contradicts the main
text · a cross-reference to a table that does not contain the claimed content ·
an availability statement that differs between the two documents · an
abbreviation defined only in the SI and used undefined in the main text · a term
family chosen differently in the SI and the main text.

## M24 — Concept/term-family sweep

**Purpose.** The term ledger (M8) enumerates SURFACE FORMS; a surface form can
be individually correct while two families compete for one concept (CN vs CNV vs
CNA; emulate vs simulate; rank vs score).

**Enumeration.** The orchestrator seeds `work/M24_concepts.md` and
`work/GLOSSARY.md` from the corpus: every concept with two competing families
and the counts per surface form. Decide the authoritative term per concept in
`GLOSSARY.md` (definition · authoritative term · forbidden synonyms) and then
check EVERY occurrence against it.

**Artifact.** `M24_concepts.md` (rows, disposed) + `GLOSSARY.md` (decisions).

**Finding rules (one per instance).** Both families used for one concept with no
decided term · a hedge the manuscript introduces ("a qualitative ranking",
"descriptive rather than inferential") that is not defined at first use · a term
the manuscript itself has to gloss in place (rule `FMT-T9f`) — either use the
standard term or keep the gloss as a RECORDED decision · a family member used
with the wrong sense after the glossary was fixed (the per-occurrence audit, not
a first-use-only disambiguation).

---

# M25–M29 — the rewrite-parity checks

These five sweeps exist because a from-scratch rewrite fixes them as a
side-effect of rewriting, while an instance-level review that does not know
the class is looking for them files nothing and the targeted reviser then has
nothing to fix. They are MECHANICAL checks (enumerate → artifact → audit →
report) and their findings are normal findings; each one is Minor or Major
`consistency`/`completeness`/`correctness` evidence, and the fix is always an
edit to an editable surface of THIS corpus.

## M25 — Figure-artwork/text parity

**Purpose.** Figure artwork is generated from plotting code and silently drifts
from the manuscript's own terms, labels and publication years. No text-only
sweep reads the artwork's words, so a term split (`Average spot length` in the
artwork vs `sequencing read length` in the text and the SI legend) or a
method-year mismatch survives every other check.

**Enumeration.** Extract the text layer of every rendered figure/table artefact
in the corpus (`pdftotext` for PDFs, `pdftotext -layout` for tables, slide XML
for PPTX; OCR only when no text layer exists and an OCR tool is available) and
tokenise it. Pair every artwork token with its manuscript counterpart:
* a method/tool/protocol name → the M8 term ledger / `GLOSSARY.md` decision;
* a year printed next to a method name → the reference list's year for it;
* an axis/legend/panel/factor phrase → the figure legend, the SI legend and the
  Methods sentence that describes the same step.

**Artifact.** `M25_artwork_parity.md`: artwork token | artwork file + page |
manuscript counterpart (file + location) | agrees? | fix route (the editable
text/legend/code file) | disposition.

**Finding rules (one per instance).** An artwork token whose term/year/name
contradicts the manuscript's own authoritative ledger — `consistency` (a
`correctness` finding when the artwork attributes the work to the wrong
method/year). The artwork file itself is usually read-only in this pipeline;
that does NOT make the finding `manual-required`: when an editable surface
(main text, caption, SI legend) can be aligned with the authoritative form,
the finding is resolvable and the fix is that alignment, with the artwork
regeneration recorded as a follow-up step in MANUAL_STEPS.md. Only when no
editable surface exists does the row become `unable — <reason>`.

## M26 — House-style / orthographic convention

**Purpose.** A corpus must apply ONE convention for spelling, hyphenation and
preverb forms. A rewrite normalises the whole corpus as it goes and the judge
panel credits the completed convention as a `consistency`-tier difference
(the judge's own M20 note says so); a review that enumerates only "key terms"
never sees it (`analyzed` in the main text vs `re-analysed` twice in the cover
letter is the documented case).

**Enumeration.** Run `scripts/enumerate_conventions.py --work WORK` over the
converted corpus (or `extract_occurrences.py --variants-file` with your own
map). The script enumerates US/UK spelling pairs (`analyze/analyse`,
`analyzed/analysed`, `normalize/normalise`, `labeled/labelled`,
`color/colour`, `behavior/behaviour`, `modeling/modelling`,
`focused/focussed`, `judgment/judgement`, `artifact/artefact`,
`center/centre`, `catalog/catalogue`, …), hyphenation families
(`re-analysis/reanalysis`, `down-sample/downsample`, `multi-omics/multiomics`,
preverb forms) and — for unlisted families — data-driven candidate pairs whose
surface forms collapse to the same normalised token. Decide ONE authoritative
form per family ONCE and write it to `WORK/STYLE_CONVENTIONS.md`
(`family | authoritative form | basis (corpus majority / the manuscript's own
first use / a stated venue rule) | forbidden variants`). Every deviating
occurrence is a row, in every document including the cover letter, legends,
the SI and the references' own text that the manuscript controls.

**Artifact.** `M26_conventions.md`: family | variant | location
(document/line) | count | authoritative form (from STYLE_CONVENTIONS.md) |
excerpt | disposition.

**Finding rules (one finding per deviating occurrence, never per family).**
The variant that is not the authoritative form is the finding (`consistency`;
`correctness` when the variant is a different term of art or changes a claim's
meaning). The family's own first use and quoted titles/proper names are never
findings. A family with both variants present and no decidable authority is
`guideline-dependent` (name the venue rule if the profile states one);
never guess a spelling into a claim. The revision stage resolves the finding
by substitution (never by re-wording the sentence around it) and re-runs this
sweep: every edited occurrence must be gone, or carry a recorded reason.

## M27 — Claim→evidence coverage

**Purpose.** A resolving citation proves the pointer EXISTS, not that the
pointer set COVERS the claim. Plural/aggregate claims ("both haploid genomes",
"all three subpopulations", "the 34 datasets", "13 caller configurations")
routinely cite one of the required sources; the judge credits the completed
pointer set as `completeness` (and as `correctness` when the claim is
unsupported as written). M2/M7 only check that what IS cited resolves.

**Enumeration.** For every claim with a plural/aggregate scope — and every
number whose sentence states a universe — enumerate the evidence items the
claim requires (datasets/panels/tables/figures/Methods statements) from the
shipped data (`WORK/NUMBERS_LEDGER.md`, the dataset summary tables, the
figure/table inventory) and pair them with the pointers the sentence actually
carries (citations, figure/table call-outs, `(Methods)` pointers, SI notes).
The seeded `WORK/OUTLINE.md` and `WORK/IDENTIFIERS.md` rows are the starting
set; extend beyond them.

**Artifact.** `M27_evidence_coverage.md`: claim (with location) | required
evidence item(s) | where each item lives in the corpus | cited pointer(s) |
covered? | disposition.

**Finding rules (one per claim with at least one uncovered required item).**
`completeness` (Minor/Major); `correctness` when the missing evidence means
the sentence claims more than the cited evidence supports. State the exact
pointer to add (e.g. `Supplementary Fig. S15`, `(Methods)`); never invent a
source. A claim whose required set cannot be derived from the corpus is
`unable — <reason>`, not a finding. The pair is checked from the pointer side
only here; the claim side (a supported result the sentence never states at all)
is J3's underclaiming, filed there with its own evidence.

## M28 — Sibling-definition symmetry

**Purpose.** M1 disposes tokens ONE AT A TIME, so an asymmetry between items
listed together is invisible: three protocols in one list where one is
expanded and two are not, or two compounds whose long forms follow their short
forms while a third precedes it. A rewrite makes the list symmetric without
noticing it did.

**Enumeration.** Per sentence/legend, build each sibling set that shares a
grammatical list or a head noun (protocols, tools, callers, datasets,
cohorts). From the M1 ledger take each sibling's first-use expansion and
definition order; compare within the set. Artifact
`M28_symmetry.md`: location | siblings | expansion (each) | definition order
(each) | symmetric? | disposition.

**Finding rules (one per list).** A list in which some siblings are expanded
and others are not, or in which definition order differs across siblings, is
one finding (`consistency`, Minor) naming every sibling and the symmetric form
to apply; when a missing expansion exists nowhere in the corpus the row is
`unresolvable — manual verification required` (never invent an expansion).

## M29 — Caption-promise vs printed-schema parity

**Purpose.** Captions promise fields, panels or encodings the printed table or
artwork does not deliver ("eleven columns" for a ten-column TSV; a promised
accession column; an n/error-bar/colour-scale promise absent from the
artwork). The reader trusts the caption; no sweep compares it with the
printing.

**Enumeration.** For every table: parse the caption's promised fields and pair
each with the printed/extracted header (or the shipped table file). For every
figure: pair each promised panel/encoding (n, error bars, colour scale,
markers, axis meaning) with the artwork's own text (M25's extraction). The
seeded `WORK/NUMBERS_LEDGER.md`, the outline rows and the table headers are
the evidence.

**Artifact.** `M29_caption_schema.md`: caption promise (with location) |
printed evidence (file + header/artwork token) | satisfied? | fix route |
disposition.

**Finding rules (one per promised item with no printed counterpart).**
`completeness` normally; `correctness` when a printed count or field list
contradicts the caption's own claim. A promise satisfied inside a dataset
identifier rather than as its own column is recorded as partial satisfaction
with the fix route. Fixes align the editable side (caption or printed source
when it is in the corpus); a generated print's regeneration step goes to
MANUAL_STEPS.md. **The pairing runs in BOTH directions**: a printed
column/panel/encoding the caption never describes is the mirror finding (readers
cannot interpret an undocumented field, and the caption -- not the reader -- owns
the explanation), class `completeness`, with the same fix routes (add the
description to the editable caption, or regenerate the print). One direction
without the other is an unfilled artifact.

## M30 — Source-hierarchy reconciliation (submission ↔ code ↔ raw data)

**Purpose.** The hierarchy — **github code > data in raw_data/ (an older
corpus spells that directory raw_figs/) > main figures > supplementary figures >
main tables > supplementary tables > main text > supplementary text** — is
stated as a RESOLUTION rule: it decides which side wins once two sources
already disagree. Its DETECTION side had no enumerating check, so a written
number, sample size, parameter, protocol step or label that the shipped code or
raw data contradicts was found only if a human happened to compare them. The
reviewed corpus already carries its producers (the analysis code, the raw-data
snapshot, the figure/table sources), so M30 makes every such comparison a row.

**Enumeration.** For every operational or quantified item on a claim-bearing
surface (abstract, main text, legend, cover letter; Methods for a parameter or
step) find the artifact that PRODUCED it: a `raw_data/` file, a code/config
file's constant or the function that prints the value, the figure/table source.
The pipeline seeds `review/artifacts/M30_hierarchy_reconciliation.md` with what
the code can pair for itself — table A: every written number the shipped data
tables do not already PROVE, against its candidate producer column(s), with the
mechanical check the code can make (a cohort-size sentence against the table's
own row count; a written value against the column's values and statistics);
table B: the module-level literals the corpus's code/config files declare
(`N_SAMPLES = 15`, `"threshold": 0.05`) — the producer side of a Methods
parameter. Extend it with the rows no code can see: figure/panel ↔ the code or
data that generates it, protocol step ↔ the code that implements it,
sample/cohort set ↔ the data's rows, Methods parameter ↔ the code's constant.

**Artifact.** `review/artifacts/M30_hierarchy_reconciliation.md`:
`document | kind | number | unit | sentence | candidate producer | producer
summary | seed check | disposition` for table A and
`file | line | symbol | value | context | disposition` for table B, plus the
rows the session adds. Every seeded row and every added row is disposed.

**Finding rules (one finding per incompatible instance).**
- the producer contradicts the written value/label/sample set (or the written
  value contradicts a producer the text points at) → `correctness`, naming BOTH
  sides (`document:location` and `file:symbol/row`), and the authoritative one
  per the hierarchy;
- a written claim whose producer is MISSING from the corpus while another
  sweep's pointer promises it → `completeness`;
- a producer that is not in the corpus at all (an external GitHub repository, an
  image-only figure, a binary the text tools cannot read) → a recorded
  `unable — the producer is not in the corpus` row, never a silent clean, and
  name which artifact was searched;
- a difference that a stated unit, rounding, conversion, or a Methods-stated
  run-time override reconciles → `OK` with that reconciling reason;
- an M30 row is never fixed here: the review reports, rule C of paper-revise
  owns a code fix, and a regenerated figure/table goes to the manual list.

Validation: the class exists because the hierarchy was one-directional — a
resolution rule with no detection sweep leaves every text-vs-code and
figure-vs-raw-data conflict to luck.

## New code-side rule ids the sweeps now emit

| rule | meaning | tier |
|---|---|---|
| `FMT-T9c` | long sentence (section bar: front/abstract/legend 40, body 46, Methods 61) or a long list-paragraph (`>=3` enumerated items in `>200` words) | finding |
| `FMT-T9f` | a term the manuscript glosses in place ("X (Y, which …)") | finding |
| `FMT-T9g` | a LaTeX value+unit outside siunitx (`\qty{}{}` / `\SI{}{}` / `\num{}`); `\code{}`, verbatim, URLs, citations, math and generated tables are exempt | finding |
| `FMT-T9i` | mega-paragraph (`>250` words, non-Methods) | finding |
| `FMT-T9j` | two term families competing for one concept (CN/CNV, simulate/emulate) | finding |

Every seeded row carries its `tier` (`finding` / `advisory`); the disposition
bar above applies hardest to the `finding` tier.

## APPENDIX: Discovery round D0–D5 (references/discovery.md)

# Discovery Round D0–D5 — paper-review (Phase 3)

Purpose: the standard review runs fixed sweeps M1–M17 and judgment passes
J1–J4. Those are finite lists — the checklist itself can be incomplete. This
round hunts for issue CLASSES the checklist does not cover.

It cannot prove completeness; its deliverables are (a) executed checks for
uncovered classes, (b) new findings with IDs `X-*`, and (c) proposed new
sweeps that improve the next checklist run. Run it only AFTER the standard
Phase 2 sweeps.

**Inputs:**
- `SUBMISSION_DIR` = the reviewed directory (default `./non-revised`)
- `PRIOR` = `./review/findings.json` (canonical prior findings; also `./review/findings.md`)
- `WORK` = `./review/work` — converted corpus from the prior run; REUSE it (reconvert only missing files)
- `OUT2` = `./review/round2` (create it; ALL outputs here)

If PRIOR is missing, STOP and tell the user to run the standard review first.

**Hard rules (unchanged):** identification only — never edit submission files;
never invent; unresolvable → `unresolvable — manual verification required`;
unverifiable guideline rule → `guideline-dependent`; no silent skips — every
enumerated item gets a disposition; one finding per instance; prefer scripts
over attention.

## D0 — Dedup base

From PRIOR build two indexes (`OUT2/known_index.md`):
- **KNOWN-CLASSES**: the 36 check IDs (M1–M30, J1–J5) with one-line descriptions.
- **KNOWN-INSTANCES**: every prior finding as `id | class | location | evidence quote`.

Anything matching a KNOWN-INSTANCE (same class + same location + same
substance) is NOT reportable — it is already known. Same location, different
substance → reportable, with a "related to F-xxx" note.

## D1 — Checklist gap analysis (artifact: `OUT2/gap_table.md`)

For EACH category 0–5, enumerate issue types an editor/reviewer/copyeditor
could encounter. Mark each row COVERED (by which check ID) or UNCOVERED.

Seed the table with these, then extend well beyond them (target ≥25 rows
total; if you stall, ask "what else?" twice more before stopping):

- author lists / affiliations / ORCID consistent across title page, cover letter, manuscript?
- Reporting Summary answers consistent with the manuscript (n, tests, replication)?
- figure files actually match their legends (panel count, axis labels)?
- methods-ordering conventions; Results-statement order matches figure order?
- supplementary file naming consistent with call-outs?
- statistics reported identically in text, legends, and tables?
- cover letter addressed to the right journal? References the right manuscript title?
- manuscript title identical on title page, header, cover letter, abstract page?
- keywords/subject terms present where the journal wants them?
- blinding/ethics statements where a reviewer would demand them?
- data-availability links resolvable (format check, not fetch)?
- figure resolution/dimension signals in filenames or metadata?
- funding numbers and grant IDs consistent with acknowledgements?
- reference list cut off mid-entry? Trailing placeholder entries?
- abbreviation list present if the journal requests one?
- is a convention applied in one place and not another (spelling, hyphenation,
  preverb forms, term families) that M26's family list does not name?
- does any scope's reading order still carry a rewrite-class cost that J5's
  architecture rows do not name?
- does any KNOWN-CLASS read only ONE direction of a two-sided defect? A claim
  can be too strong or too weak (calibration), content can be lost or invented,
  an item can be missing or unneeded, a claim can carry no pointer or a printed
  item no description, an availability claim can outrun or undersell its
  locator, a document can be dropped or added. For every class whose fixed
  definition names one direction, the missing direction is a gap row (and a
  probe) until a run has reported both.

The rows are questions about issue CLASSES, not instances — instances come
from probes.

## D2 — Probe design (artifact: `OUT2/probes.md`)

Convert every UNCOVERED gap row into a concrete, executable probe: a question
that can be answered by inspecting enumerated evidence from the corpus, with
the exact files/regions to inspect and the extraction to run (script where
possible). Each probe row: probe ID (P2-001…) | gap row | question | evidence
source | status (pending/executed/unable — reason). A gap row that cannot be
converted into a probe is itself a finding class ("analysis limitation"),
recorded, not silently dropped.

## D3 — Probe execution & anomaly hunting (artifact: `OUT2/probe_results.md`)

Execute every probe. Additionally run open-ended anomaly hunts over the
corpus, because unknown unknowns resist checklisting:

- **Expected-but-absent**: values/labels the manuscript's own logic requires
  but that never appear (e.g., a two-group comparison never reporting a test;
  an n stated for one cohort but absent for the other; an error bar defined
  for some panels but not others).
- **Present-but-unexpected**: tokens appearing where they shouldn't (numbers
  inside prose that duplicate table entries inconsistently; internal review
  language; a paragraph that answers a reviewer question from an old round).
- **Boundary probes**: first/last lines of every section; every heading;
  every figure legend's first and last sentence (these carry structural
  information and are disproportionately error-prone).

Record EVERY probe result with a disposition — a probe that found nothing
records "no anomalies — checked: <locations>". Probes are judgment work, but
their coverage is still enumerated.

## D4 — New findings (outputs: `OUT2/findings_extra.md` + `findings_extra.json`)

Every new issue found gets an `X-001`… ID (separate namespace from `F-*`, so
paper-revise can merge both without collisions), formatted exactly like a
standard finding (location, category, check = the gap-row class label,
severity, evidence quote, explanation, status). Dedup per D0. Related prior
findings get the "related to F-xxx" note.

## D5 — New-sweep proposals (output: `OUT2/new_sweeps.md`)

For every issue CLASS that recurred or that a probe caught only by accident,
write a proposed sweep definition in the exact format of sweeps.md (purpose ·
enumeration procedure · artifact columns · finding rules) so the next review
run catches it mechanically:

```
## M25 — <name> (proposed)
**Purpose:** ...
**Enumeration:** <script or manual procedure — must be enumerable>
**Artifact:** M25_<slug>.md: <columns>
**Finding rules:** one per instance, listed
```

Number proposals continuing from the highest existing sweep number. M18
(figure-legend length, always enumerated with an optional proxy cap), M19
(abstract/main-text length plus the user's cover-letter preference) and M20
(OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan)
are reserved and defined in `sweeps.md`; M21–M24 were adopted from earlier
discovery rounds, M25–M29 are the rewrite-parity checks (artwork/text
parity, house-style conventions, claim→evidence coverage, sibling-definition
symmetry, caption-promise parity), and M30 is the source-hierarchy
reconciliation (a written claim against the code/raw data that produced it).
Proposals therefore start at M31.
These are PROPOSALS: the user validates them; only validated ones get
appended to `references/sweeps.md`. This is the feedback loop — no static
checklist can be complete, but each discovered miss converts into a permanent
mechanical check, so the checklist converges toward exhaustiveness across
runs instead of pretending completeness on day one.

## Round-2 output summary (`OUT2/round2_summary.md`)

Counts: gap rows (covered/uncovered), probes (executed/clean/findings/unable),
X-findings by category/severity, proposed sweeps. Manual-verification list.
Statement of what this round could NOT check (honest limits).

# Audit and code-revision plan — cnb round-1 winner + neohet revise failures
> **Validation update (2026-10-19).** Every finding below was re-checked in
> `VALIDATION_LEDGER_2026-1019.md`. Corrections: CNB F3 (reference 14) is
> **retracted** -- the paper has 12 authors, not four; the "strict dispositions
> opt-in" claim is **retracted** -- the policy is on and the detector was too
> literal; "EMF is not accepted" is **softened** to renderer-dependent font
> substitution; the spacing/line-number/widow-control/heading-style items are
> **downgraded** to editorial (Nature states no such rule for initial
> submission). The code changes in Part 3/5 have since been implemented; see
> the ledger's Part D.



Date: 2026-10-19. Workspace: `/home/zhaoxiaofei/paper-refine` (pipeline checkout at commit state of 2026-10-18 21:42).

## 0. What was examined, and how

| Object | How |
|---|---|
| `…/cnb-to34-1019-0025-a755adf/round1_winner/` | `pandoc` docx→markdown; direct OOXML inspection with `zipfile`+regex (paragraph styles, `w:sectPr`, run properties, media); LibreOffice render to PDF; `pdftoppm`/`pdftotext -layout`; per-page inspection |
| cnb round-1 artifacts | `reports/round1_review_findings.csv` (57 rows), `reports/round1_issue_matrix.csv`, `reports/FORMAT_FIX_original.json`, `runs/r1_review/review/artifacts/M20_formatting.md` (159-row disposition table), `runs/r1_a2_revise/revised/revision_report.json`, `VISUAL_CHECK.md`, `README-AUTHOR-TO-COMPLETE.md` |
| neohet revise failures | `state.json` (`attempts_log`, `postcheck`, `last_error`), `runs/r1_a2_revise_try{1,2}_failed/record.json`, `_agent.log`, `PROMPT.md`, `FORMAT_FIX_*.json`, `revised/revision_report.json`, successful `runs/r1_a2_revise` |
| Code | `paper_pipeline.py` (54,807 lines), `paper_docx_format.py` (rule registry, 87 `FMT-*` ids), `AGENTS.md` |

Claims below are marked **[verified]** when read from the artifact, **[inferred]** when derived from prompt/log behaviour.

---

# Part 1 — What is still wrong in the cnb round-1 winner

The winner is `round1_winner/cnb-33-2-mainText-9c5999e.docx` (32 A4 pages), the cover letter
`cnb-33-1-coverLetter-9c5999e.docx` (2 pages) and the supplement `cnb-33-3-suppAll-9c5999e.pdf`
(52 pages). It passed the round’s postcheck, was scored by two judges
(median 3.0, mean 3.0, n = 2) and carries 15 author hand-off items.

## 1.1 Writing: ambiguous, ungrammatical or circular sentences

These are sentences **no finding quoted** and therefore no pass ever rewrote. Paragraph numbers are
the docx `<w:p>` index (0-based) from the delivered file.

| # | Location | Quote (verbatim) | Why it is a defect |
|---|---|---|---|
| W1 | Discussion ¶1 (p51) | “Our results show that Ginkgo gives the best overall balance across metrics, **chiefly accompanied by** more accurate ploidy estimation.” | A mechanical substitution of finding F-013’s “mainly through”. The adverb has no verb to modify; the reader cannot tell what accompanies what. The ledger cites this very sentence as the *evidence that the fix is correct* (see §1.3). |
| W2 | Discussion ¶3 (p53) | “Our results also help to **explain the disagreements among** Song et al.³, Schmid et al.³⁹, and Chang et al.⁴⁰, because the ranking depends on the endpoint and on the input a caller requires” | Chang et al.’s conclusion is never stated anywhere in the paper, so there is no third position to disagree. “Explain” claims a resolution the paper does not perform. Finding F-043 asked for exactly this and is marked `fixed`. |
| W3 | Discussion ¶3 (p53) | “Numbat performed best among the callers that require BAM-format data, **which it needs** to compute B-allele frequency (BAF)” | The relative clause has no unambiguous antecedent (“which”: the data? Numbat? the requirement?). |
| W4 | Discussion ¶4 (p54) | “CHISEL’s haplotype-aware approach **therefore** has **substantial potential utility that our benchmark was not designed to evaluate**.” | “Therefore” links to nothing (the preceding sentence explains why CHISEL underperformed, which argues the opposite); “substantial potential utility” is filler. |
| W5 | Methods, Design principle ¶1 (p65) | “We can therefore downsample real sequencing data from such cells and then **invert the downsampling to obtain data with approximately any CN profile as the known ground truth**.” | “approximately any” is undefined; the operations are downsampling **and merging**, not an inverse; the final clause’s object is unclear. |
| W6 | Methods, Design principle ¶1 (p65) | “A caller that performs well on haploid input but poorly on merged input **will be flagged as inconsistent**, regardless of whether its haploid output is biologically correct.” | “Flagged” by what? The benchmark scores, it does not flag. And the clause contradicts the two-reference (Hap_0/Hap_1) design in Step 4. |
| W7 | Methods, Step 4 ¶2 (p81) | “It also **tests whether the residual aneuploidy of a haploid cell is low, because** aneuploidy is rare for germline-cell chromosomes … and CNP affects only 4.8–9.5% of the human genome.” | The “because” clause asserts the conclusion it is supposed to test. The Results (§p34) then says the data “does not establish that residual aneuploidy is negligible”, so the two sections contradict each other. |
| W8 | Methods, Step 4 ¶2 (p81) | “We **therefore expected** performance … to stay largely unchanged …, **which implies** that the consistency check approximates a comparison against the haploid ground truth.” | “Which implies” attaches to the expectation, not to a result; the logic is inverted (an expectation is not evidence). |
| W9 | Results, correction ¶ (p34) | “The correction … was metric- and caller-specific rather than uniformly slight: … **Because** the correction makes the strategy aware of CNPs and haploid aneuploidy, **we expected stability, but that variability does not establish** that residual aneuploidy is negligible.” | Three moves in one sentence (claim → expectation → caveat), and “that variability” points to the previous sentence, not to anything in its own. The paragraph order F-055 asked for is now claim-first; the sentence that carries the logic is still scrambled. |
| W10 | Results, haploidy ¶ (p35) | “… a caller’s output on the haploid input **effectively matches the CN ground truth**, and the agreement of the two references **supports this interpretation rather than replacing it**.” | Circular: the output *is* the ground truth under Hap_1. “Rather than replacing it” has no antecedent. |
| W11 | Results, SeCNV ¶ (p36) | “The notable exception **to the near-invariance described above** is SeCNV¹² …” | Nothing called “near-invariance” was described; the previous paragraph describes *metric- and caller-specific variability*. |
| W12 | Results, Ploidy ¶1 (p39) | “**We therefore examined** which metrics were associated with that balance.” | The preceding paragraph ends “Ginkgo’s lead is notable because it was published in 2015…”; “therefore” has no premise. A paragraph opening with a bare connective is a Q4 coherence defect. |
| W13 | Methods, ACT ¶ (p85) | “For real cancer data, we used the ACT breast cancer dataset²⁹: eight breast tumor samples (TN1–TN8) and four breast cancer cell-line samples (six sequencing libraries, with the three MDA-MB-231 preparations merged into one statistical sample) generated by ACT scWGS (labeled in Fig. 3d by their library identifiers MDAMB231c28, …, where the three MDA-MB-231 libraries were prepared using sample mb231 of the MDA-MB-231 cell line), with 1,024 to 2,400 evaluable cells per sample (counting each sample’s runs together).” | One 90-word sentence with four nested parentheticals. A copy-editor would return it. |
| W14 | Introduction ¶2 (p10) | “**Unlike the assay for** transposase-accessible chromatin using sequencing (ATAC-seq) **or RNA sequencing (RNA-seq)**, scWGS is free of the confounding noise …” | The comparison is between “the assay” and “RNA sequencing” — not parallel. ATAC-seq is expanded here and never used again. Finding F-040 was closed by inserting “the”, which fixes the grammar but not the sentence. |
| W15 | Methods, Workflow overview (p71) | “The procedure for benchmarking CNV calls at single-cell resolution from scWGS consists of the four steps detailed in the subsections below.” | Content-free filler; the heading already says “four steps”. |
| W16 | Results, HG008 ¶ (p46) | “Callers that performed well on our main benchmark also tended to predict HG008 subpopulations that were **more consistent** with the karyotyping results, **which supports the performance ranking descriptively**.” | “More consistent” is undefined and no statistic is given; “descriptively” is appended to disarm the claim after it is made. |
| W17 | Results, scRNA ¶ (p49) | “The same benchmark also exposed a **purity floor**” | A coined term, never defined; a “floor” is a threshold, but the text describes a trend. |
| W18 | Discussion, limitations (p58–61) | “This study has the following limitations. First, … Second, … Third, … Fourth, …” | Formulaic enumeration with wildly unequal items (First ≈ 140 words, Second = 23). |
| W19 | Data availability (p109) | 219-word paragraph mixing accessions, two repository URLs, the simulator’s reverse-smoothing caveat and COSMIC licensing | The caveat is a limitation, not an availability statement; the review said move it, the reviser cross-referenced it from the Discussion instead. |
| W20 | Fig. 5 legend | “Panels show, from top to bottom, … . **Below them, the panels show** … . **This is followed by** …” | Three different connectives for one enumeration; “Below them, the panels show” repeats “panels”. |
| W21 | Fig. 4 legend | “This pattern is consistent with Ginkgo’s leading overall balance among the … callers.” | The legend asserts the paper’s conclusion from a comparison the Methods say is a qualitative reading with no statistic. |
| W22 | Abstract | “… the ranking is qualitative and **metric-dependent**.” | “Metric-dependent” is undefined (depends on the metric chosen? on the metric set?). |
| W23 | Methods, Software (p95) | “The recorded versions are sra-tools v3.2.1, … Ginkgo commit d7c7790, … SCCNV v1.0.2, … copynumber 1.38.0, …” | One 106-word list with three incompatible version forms (commit / vX / bare), and `copynumber` lowercase here vs `Copynumber` in Step 3. |

**Cross-cutting diagnosis.** The defects cluster into four patterns:
1. **Local substitutions that were never re-read as sentences** (W1, W2, W3, W14).
2. **Paragraph-openers with a connective whose premise is absent** (W4, W12, plus W9’s “Because”).
3. **Sentences that assert their own justification** (W6, W7, W8, W10, W16).
4. **Unbounded enumerations and nested parentheses** (W13, W18, W19, W23).

## 1.2 Formatting: what a reader actually sees

The render (LibreOffice 7.3, A4, 32 pages) is *not* broken, but it is not submission-grade either.

**[verified] F1 — reference 15’s emphasis is malformed.** Every other entry bolds the volume only;
entry 15 bolds the volume, the article number and the year:

```
Front. Genet. 11, 505441 (2020).      ← “11, 505441 (2020).” is bold
Nature 472, 90–94 (2011).             ← only “472” is bold
```

The cause is inside the live Zotero field result (`<w:rPr><w:b/><w:bCs/></w:rPr>` on the run
`11, 505441 (2020).`), not a hand edit. It shipped because the pipeline treats field results as
read-only output.

**[verified] F2 — five page ranges still use a hyphen-minus** where the list otherwise uses an en
dash: refs 10 (`2239-2254.e39`), 11 (`445-452.e6`), 21 (`541-553.e5`), 23 (`6355-6369.e16`),
42 (`24-34.e10`). Findings F-024…F-028 were **confirmed** and then closed `manual-required`
because they sit in the live field.

**[verified] F3 — ref 14 truncates a four-author paper** (“Nilsen, G. *et al.*”), while the list
prints all authors for every other ≤5-author entry (X-002, still open).

**[verified] F4 — ref 34 has no journal, no volume, and a spaced hyphen used as a dash**
(“GitHub - jlaffy/infercna …”), F-023/F-029, still open.

**[verified] F5 — Fig. 1 is an 8.7 MB EMF.** A non-Word renderer substitutes the font and panel f
becomes mojibake:

> panel f of Fig. 1 rendered through LibreOffice: `ĞÝÐšŵ ÂΔǓŽĬ / E s ÐÃüēī džŵ …`

In Microsoft Word (the reviser’s renderer) it looks correct, which is why `VISUAL_CHECK.md` reports
“no overlapped text”. EMF is also not among the artwork formats Nature accepts for production.

**[verified] F6 — the figure text is 2.0–3.2 pt at the printed width.** The review measured it
(F-030…F-036, X-901…X-905); the reviser carried it to `MANUAL_STEPS.md`. It is visible at 100 %:
the Fig. 2 row labels and Fig. 3 balloon labels cannot be read.

**[verified] F7 — an orphan line in Data availability.** Lines 727–729 of the render read
“… are available”, “at”, then the long URL: the single word “at” sits alone on a line because the
following URL is one unbreakable token.

**[verified] F8 — document-wide layout defaults.** `w:widowControl w:val="0"` (widow/orphan control
off for every paragraph), `w:spacing w:line="360"` 1.5 lines (including the reference list and the
figure legends), `w:lnNumType` line numbers on, no `w:type="page"` breaks anywhere, one section for
32 pages. The figure pages only separate because each image is taller than the remaining space,
which leaves ~40 % of page 28 blank.

**[verified] F9 — alt text still differs from the legend** for Figs. 1 and 4 (F-019 was dropped by
the audit as a false positive; the mismatch is real, whatever its severity).

**[verified] F10 — the Abstract is not a heading.** `<w:p>` 6 is a plain bold paragraph; `Results`,
`Discussion`, `Methods`, … are `Heading1`. The document therefore has no semantic outline above
`Results`, no Abstract entry in Word’s navigation pane, and a journal XML conversion can lose the
section. The title, authors and affiliations are likewise direct-formatted, not `Title`/`Author`
styles.

**[verified] F11 — the supplement.** `\linenumbers` prints line numbers on the title page and the
abstract (and `\nolinenumbers` only from the figure section); S1–S22 captions are set `\small`
while S23–S36 are not (the source comment says “insufficient space left after placing huge
figures”); `\sloppy` is global; the accuracy heatmaps use a red–green scale; S23–S30 are 150-ppi
rasters (measured in the round’s X-005 probe).

**[verified] F12 — packaging bloat.** `round1_winner/` is 409 MB, of which
`cnb-33-3-suppAll-9c5999e.tracking-original.pdf` is 391 MB. The name contract excludes it from the
submission, so it is harmless to the venue, but it makes the published package unusable as a base
for the next round.

## 1.3 The pipeline knew, and its own ledger certifies the defects

Three examples from `runs/r1_a2_revise/revised/revision_report.json`:

* **F-013** (the causal “mainly through”): status `fixed`, and the ledger’s `evidence` field is the
  new sentence itself — *“chiefly accompanied by more accurate ploidy estimation”*. Nothing in the
  pipeline reads that sentence.
* **F-043** (Chang unresolved): status `fixed`, evidence = *“Discussion paragraph 3, last
  sentence”* — a **location**, not a text. The sentence it points at still does not state Chang’s
  conclusion.
* **F-024…F-028 / X-002**: `manual-required`, because “the field result is regenerated on refresh,
  so the dash convention must be fixed in the CSL style / Zotero, not by hand-editing the field
  result.” The *submitted docx* still carries the defect; the author is asked to fix it later.

Meanwhile the format scan of the delivered package reports **138 rows** — 65 long sentences, 13
mega-paragraphs, 15 confusable-term pairs, 17 repeated terms — and the reviser fixed **zero** of
them (`FORMAT_FIX_r1_a2_revise.json`: `"fixed": 0, "changes": 0`). The postcheck does not require
pre-existing rows to be fixed, only that no **new family** appears.

The judges saw almost none of this: `round1_issue_matrix.csv` records `minor_writing = 0` and
`major_writing = 0` for the a2 winner (against 1 minor correctness and 2 formatting rows).

---

# Part 2 — neohet: why the revising agent failed

## 2.1 Timeline

| Attempt | Duration | Result | Fatal error |
|---|---|---|---|
| 1 | 2082 s | failed | `VALIDATION: test_si_patched.docx is not a valid DOCX: word/document.xml: malformed XML (mismatched tag: line 2, column 30555)` |
| 2 | 1148 s | failed | `revise: the delivered package introduces a NEW finding-tier defect family FMT-T9i (1 row(s); the package it started from had none) -- fix it (…) or record why the ruler itself is wrong` |
| 3 | 1240 s | done, 5 warnings | — |

Each attempt started from `base/` again (the failed sandbox is preserved as
`runs/r1_a2_revise_try{1,2}_failed/`). Total ≈ 75 minutes for a stage that succeeds in ≈ 20.

## 2.2 Failure 1 — a scratch DOCX inside `revised/work/`

**[verified]** Attempt 1 left `revised/work/test_si_patched.docx` with a mismatched XML tag.
`_validate_stage_package()` (`paper_pipeline.py:16225`) calls
`paper_docx_format.validate_paths([pkg_dir])`, and `validate_paths()` (`paper_docx_format.py:12200`)
recurses into **every** `.docx` under the package, excluding only evidence areas and
`.tracking-*`/`.logging-*` auxiliary names. `work/` is not excluded. A scratch file therefore fails
the deliverable validation.

The agent could not see this coming: `sandbox_selfcheck()` (`paper_pipeline.py:34344`) — the command
its prompt tells it to run before writing the completion marker — never calls
`_format_fix_stage_package()` (which is where `_validate_stage_package` lives, at line 16454) nor
`validate_paths`. Its final log says *“the paperwork checks passed: the postcheck’s own detectors
found nothing to reject”*, which is false for this check. The docstring claims “every check below
is the postcheck’s OWN detector (called, not re-implemented)” — it is a **subset**, not the set.

## 2.3 Failure 2 — a format family created by a file the pipeline told the agent to write

**[verified]** `README-AUTHOR-TO-COMPLETE.md` is written into `revised/` by policy
(`author_to_complete: readme` is the default; `ensure_handoff_readme`, line 7312). In attempt 2 the
agent wrote it as a single 667-word paragraph. `scan_format_in_sources()`
(`paper_pipeline.py:14365`) scans `*.md` under the package and applies the paragraph rules
(`paper_docx_format.text_style_rows` → `long_text_rows`), so the file produced one `FMT-T9i` row
(paragraph > 250 words). `scan_regression_problems()` (line 30485) compares base vs delivered by
**rule count** and raises the fatal “NEW finding-tier defect family” error because the base had
none. The same scan also raised a `FMT-T9c` growth warning (7 → 12).

Three independent defects combine here:

1. **The scan does not know what ships.** `README-AUTHOR-TO-COMPLETE.md`, `README.md`,
   `MANUAL_STEPS.md`, `CHANGELOG.md`, `REVISION_REPORT.md` are all scanned as if they were
   manuscript prose. The file itself says *“This checklist is never submitted and no submitted
   document may depend on it.”* The cnb reviewer understood this and closed 7 such rows as
   “outside the submission surface” (`M20_formatting.md` rows 19–25) — but the **postcheck**, which
   gates the neohet reviser, does not apply that scoping.
2. **The pipeline creates the trap.** The same postcheck seeds the file (or instructs the agent to
   write it) and then fails the package for the file’s paragraph shape. `BOOKKEEPING_FILES`
   (line 4740) does not include `README-AUTHOR-TO-COMPLETE.md`, and `is_bookkeeping_name`
   (line 4788) does not match `README*.md`.
3. **The error does not name the file.** The message gives a count only; the agent had to guess
   (its log shows it guessed correctly, then spent a whole attempt rewriting a bookkeeping README).
   Attempt 3 “succeeded” by producing a 244-word paragraph — six words under the 250-word
   threshold — and the delivered scan still has 33 rows, of which 7 are `FMT-T9c`.

## 2.4 The retry prompt tells the agent to read a file it is forbidden to read

**[verified]** The prior-failure block (`prior_failure_block`, line 11214) says:

> “The failed attempt's own sandbox is preserved at runs/r1_a2_revise_try1_failed -- its
> deliverables as the postcheck judged them, its transcript and a record.json. **Read it before
> repeating an approach.**”

Two sentences later, the same prompt says:

> “Write ONLY inside this sandbox and never touch sibling sandboxes or parent directories.
> **Reading is also confined to this sandbox**, with exactly one exception: you MAY read … the skill
> documents …”

The agent cannot inspect the rejected package, so it re-derives the failure from one line of text.
`materialize_revise()` (line 23381) rebuilds the sandbox from `base/` + `review/` and carries
**nothing** from the previous attempt.

## 2.5 Warnings the pipeline caused and then blamed on the agent

The successful attempt still carries:

* *“revision token mismatch: filename token(s) ['823e0b4'] vs the content-derived token 48d78b7 --
  the package was edited after its token was applied, or a token was copied from another package.”*
  — **The pipeline restyled two documents after the agent applied its token**
  (`FORMAT_FIX_r1_a2_revise.json`: `"fixed": 2, "changes": 4`, “2 restyled into the venue's
  official Word template”). The warning’s hypothesis is wrong and its tone is accusatory.
* *“134 number(s) in the abstract/legends are not proved by any shipped data table”* — the first
  example is a **cover-letter** sentence (“From six studies we curated 30 datasets…”).
  `number_provenance_report()` (line 30334) keeps paragraphs whose `section_kinds` is
  `abstract|legend|front`; `section_kinds` classifies **every** cover-letter body paragraph as
  `front` (verified on the delivered cover letter). The count is therefore mostly the letter.
* *“marker reports writing_remaining=0 while the frozen review lists 9 category-2 finding(s)”* —
  a tie-break warning the agent cannot resolve without lying; the ledger says all 9 were fixed or
  audit-dropped, which the warning itself concedes is possible.

---

# Part 3 — Code revision plan

Each row names the file/function to change, the new behaviour, and an acceptance test. Line numbers
are from this checkout and will drift.

## 3.1 P0 — make the revise stage self-consistent (fixes both neohet failures)

### C1. One verdict function, used by both postcheck and selfcheck

**Files:** `paper_pipeline.py:30993` (`postcheck_revise`), `:34344` (`sandbox_selfcheck`),
`:16309` (`_format_fix_stage_package`), `:16225` (`_validate_stage_package`).

Extract the body of `postcheck_revise` into

```python
def revise_verdict(ctx: Ctx | None, sb: Path, rec: dict, *,
                   dry_run: bool = False) -> tuple[bool, list[str], list[str]]:
```

`postcheck_revise` becomes a thin wrapper; `sandbox_selfcheck(kind="revise")` constructs a
read-only `Ctx` from the sandbox (`pipeline_config.json` + the sandbox’s `format_policy.json`) and
calls the same function. In `dry_run` the format fixer computes the changes but writes nothing; the
verdict is identical because the write is deterministic.

**Acceptance test** (`.paper_test/test_revise_selfcheck_parity.py`): scaffold a revise sandbox whose
package contains (a) a malformed `work/x.docx`, (b) a 600-word `README-AUTHOR-TO-COMPLETE.md`;
assert `sandbox_selfcheck` returns the same fatal error count as `postcheck_revise`.

### C2. Validate only files that can ship

**File:** `paper_docx_format.py:12200` (`validate_paths`), `paper_pipeline.py:16225`.

Add `only_submission: bool = False` and `exclude_top: tuple = ()` to `validate_paths`; when set, keep
only names matching the run’s submission contract (the same predicate the corpus builder uses) and
drop `work/`. In `_validate_stage_package` call it with `only_submission=True, exclude_top=("work",)`.
A non-shipping DOCX under `work/` becomes a **warning** (`PKG-4: non-shipping scratch document …`),
not a fatal validation error — unless it is inside a directory that ships.

**Acceptance test:** the attempt-1 sandbox must now pass validation with a `PKG-4` warning naming
`work/test_si_patched.docx`.

### C3. Scope the regression scan to the submission surface, and name the row

**File:** `paper_pipeline.py:30485` (`scan_regression_problems`), `:14365`
(`scan_format_in_sources`).

1. Add a `scope="submission"` argument to `scan_format_in_sources` that skips
   `is_bookkeeping_name(name)`, `README*.md`, `README*.txt`, and the `work/` tree for **finding-tier
   gating** (they may still be scanned for a report).
2. Add `README-AUTHOR-TO-COMPLETE.md` to `BOOKKEEPING_FILES` (`:4740`) and `README(?:-|.)` to
   `BOOKKEEPING_NAME_RE` (`:4774`). This is the same scoping the reviewer already applies; the
   postcheck should agree.
3. When a new family appears, include the first three rows: `document`, `paragraph`, `evidence`
   (truncated), e.g.
   `FMT-T9i in revised/README-AUTHOR-TO-COMPLETE.md para 2 (577 words)`.

**Acceptance test:** the attempt-2 package must now **pass** (no fatal error) and report the README
row as advisory; a genuine new `FMT-T9i` in `mainText.docx` must still fail, with the document and
paragraph in the message.

### C4. Make the retry inspectable and incremental

**File:** `paper_pipeline.py:23381` (`materialize_revise`), `:11165` (`prior_failure_text`),
`:11214` (`prior_failure_block`).

1. In `materialize_revise`, when a previous attempt exists, copy its `revised/` to
   `sb/"previous_attempt"/` (read-only) and add `previous_attempt/` to the prompt’s allowed reads.
2. Change the prior-failure text from “Read it before repeating an approach” to an in-sandbox path,
   and delete the contradictory sentence from `REVISE_DIRECTIVES` (`paper_pipeline.py:9393`; the containment paragraph is at line 9403).
3. Optional but high value: seed `revised/` with the previous package and tell the agent to
   **repair** it, keeping a `REPAIR_LOG.md`. The postcheck treats a repaired package exactly like a
   fresh one because the verdict is content-based.

**Acceptance test:** a forced retry must contain `previous_attempt/revised/` and the prompt must
contain no sentence forbidding its read.

### C5. Attribute the post-restyle token mismatch to the pipeline

**File:** `paper_pipeline.py:21242` (`_record_revision_token`), `:16309`.

After `_format_fix_stage_package` has changed bytes, recompute the content token and (a) if the
package’s filenames carry the pre-fix token, rename them to the new token and update every
cross-reference (the same `revision_token.py` path the agent used), or (b) record the mismatch as
`token_basis="pre-format-fix"` and suppress the warning. Never phrase it as “edited after its token
was applied” when `rec["format_fix"]["changes"] > 0`.

**Acceptance test:** a package whose only post-token change is the venue restyle must not raise the
warning.

### C6. Fix the number-provenance scope

**File:** `paper_pipeline.py:30334` (`number_provenance_report`), `paper_docx_format.py:1870`
(`section_kinds`).

Skip cover letters (`is_cover_letter_doc`) and pass the document role into `section_kinds`, so a
letter’s body is `letter`, never `front`. Restrict the report to the abstract and figure/table
legends of the manuscript documents, as its own docstring says.

**Acceptance test:** the neohet cover letter’s 30-dataset sentence must not appear; the count must
fall to the manuscript’s own abstract/legend numbers.

## 3.2 P1 — make the revision verify the sentence, not the row

### C7. The ledger must carry before **and** after text, and the after text must be found

**File:** `paper_pipeline.py:25112` (`revision_ledger_problems`), `:30785`
(`_frozen_review_findings`), the V3 rescan text at `:9467`.

Contract change for `status in {"fixed", "fixed-with-caveat"}`:
* `before` (≥ 15 chars) and `after` (≥ 15 chars) are required;
* `after`, whitespace-normalised, must occur in the revised corpus (any shipped document);
* `evidence` may no longer be a bare location (`…/p\s*\d+$` or `Discussion paragraph \d+`) — it must
  contain a quoted span;
* for a finding whose `check` is `J3`, re-run `claim_strength_rows` on the paragraph containing
  `after` and require the flagged direction to change.

**Acceptance test:** the cnb F-013 row (`after = “chiefly accompanied by …”`) must be rejected
because `after` does not resolve the finding’s class; the F-043 row must be rejected because the
evidence is a location.

### C8. Re-read the paragraph, not the span

**File:** `paper_pipeline.py` `LANGUAGE_PASS_RULE` (`:10322`), `REVISE_DIRECTIVES`.

* The language pass’s object changes from “every edited sentence” to “**every paragraph any edit
  touches, read whole before and after**”; every ledger row’s `after` is the whole paragraph.
* Add a mandatory `PARAGRAPH_REWRITE` artifact: one entry per touched paragraph with
  `old paragraph | new paragraph | sentences changed | claim preserved?`.
* The pass runs over **every** paragraph of a section whose finding count > 0, so a section that is
  edited at all is re-read (this would have caught W9/W12 in the same pass that fixed F-055).

### C9. A sentence-quality rule family in the formatter

**File:** `paper_docx_format.py`, new `sentence_quality_rows(paras, ...)` called from
`text_style_rows` (`:4156`) and gated to `finding` tier. Concrete checks, each with a named reason:

| rule | detects | winner example |
|---|---|---|
| `FMT-G5` | a verbless fragment (no finite verb) of ≥ 8 words | W8’s “which implies” clause if split |
| `FMT-G6` | a dangling relative pronoun whose nearest noun is inanimate/incompatible | W3 (“which it”) |
| `FMT-G7` | an adverb directly modifying a past participle with no agent (`chiefly accompanied by`) | W1 |
| `FMT-G8` | a paragraph-initial connective (`Therefore`, `Thus`, `Hence`, `Because`) whose previous paragraph contains no causal premise (no `cause|because|due|result|since|therefore` and no shared content word) | W4, W12 |
| `FMT-G9` | the same content word repeated within 12 tokens | W16 |
| `FMT-G10` | a sentence with ≥ 3 parentheses or ≥ 2 nested pairs | W13 |
| `FMT-G11` | a sentence with ≥ 3 `and`/`but`/`which` clause joins | W9 |
| `FMT-G12` | a “which …” clause whose antecedent is the whole preceding clause but is placed after a noun (heuristic: `which` preceded by a noun and followed by `is/are/was/were/does`) | W10 |

These are heuristics; they must be `finding`-tier only when the pattern is unambiguous, and every
row must quote the span. The point is not to replace the language model — it is to give the
postcheck a **re-runnable** test for the exact class the judges missed.

### C10. Make the seeded-format-row disposition non-boilerplate by default

**File:** `paper_pipeline.py` `--strict-dispositions` (find `strict_dispositions`), the review prompt
`M20` block.

* Default `--strict-dispositions on` when a venue profile is present.
* Reject a disposition that is identical (after normalisation) to ≥ 3 other rows of the same rule.
* Require a finding-tier row’s disposition to quote the rule’s **own bar** (e.g. “Methods bar 61,
  sentence is 52 words” or “the two terms have separate definitions in the glossary”).
* Count `OK — none found` as an **unfilled** row, not a disposition (it appears 4 times in the cnb
  M20 table).

**Acceptance test:** re-running the cnb review must fail the disposition pass for the 58 `FMT-T9c`
rows closed with four repeated reasons, and must not accept the 44 “bibliography abstract” rows
until the `.bib` scan is fixed (C11).

### C11. Stop scanning data payloads as prose

**File:** `paper_docx_format.py` `text_source_paragraphs` / `analyse_package` (`:9732`), the `.bib`
and `.tex` branches of `scan_format_in_sources` (`:14445`).

* `.bib`: parse entries structurally; scan `title`, `journaltitle`, `booktitle`, `note` only. Skip
  `abstract`, `keywords`, `annote`, `file`, `urldate`, `doi`, `issn`.
* `.tex`: drop comment lines starting with `%`, the preamble before `\begin{document}`, and
  `\newcommand`/`\iffalse` blocks; scan only typeset text.
* `.md`: skip fenced code blocks and HTML comments (the `<!-- pipeline-managed … -->` marker is
  currently read as a 265-word sentence — M20 row 23).

**Acceptance test:** the cnb `.bib` must stop producing 44 long-sentence rows; a genuinely long
sentence in the SI prose must still be found.

### C12. Give the judge a real copy-edit discovery pass

**File:** `paper_pipeline.py` `JUDGE_DIRECTIVES` (`:8269`), `WRITING_RUBRIC` (`:30377`).

The judge already has Q1–Q12, but the cnb panel returned zero writing rows. Add to the judge’s
discovery pass:

* one mandatory pass over **every body paragraph** with a per-paragraph verdict
  (`clean | Q4 | Q9 | …`), recorded in `judge_review/writing_pass.md` — not a score, a coverage
  artifact;
* the four patterns from §1.1 as named checks (local-substitution grammar, orphan connective,
  self-justifying clause, unbounded enumeration), each mapped to Q4/Q9/Q10 so the scale does not
  grow a seventh class (rule 6);
* the postcheck requires the coverage file, exactly as it requires the L1–L11 file from the
  reviser (`language_pass_report`, `:30443`).

This is the only mechanism that can find W1–W23 *after* the revision, because the next round’s
review is not guaranteed.

## 3.3 P2 — formatting coverage the ruler is missing

### C13. `FMT-T6h` — reference run formatting

**File:** `paper_docx_format.py`, the Bibliography block of `analyse_package` (~`:9400–9495`).

For each `Bibliography` paragraph, compute the bold runs (via `run_is_italic`’s sibling,
`_effective_run_flag(…, "b")`). Expect: exactly one bold run, its text matches the volume token
(`\b\d+\b` before the comma before the page range); the page range and the `(YEAR)` are not bold.
Flag:
* a bold run containing `(` or a 4-digit year → `FMT-T6h` (ref 15);
* a bold run that also contains the page range → same;
* no bold run at all → `FMT-T6i` (journal style expects a bold volume).

Fix route: `style-field` — rewrite the field result’s run properties (the module already does this
for italics, `_rpr_set_emphasis`), or `unlink` for the submission copy.

### C14. Ship a static bibliography in the submission copy

**File:** `paper_pipeline.py` `zotero_mode_of`, `paper_docx_format.py:9943`
(“Drop fldChar/instrText runs; keep field RESULT runs (Zotero unlinking)”), `zotero-refresh`.

The pipeline already has the machinery:
`python3 paper_docx_format.py zotero-refresh FILE.docx` repairs a field result offline, and
`unlink_zotero_fields: true` in the policy produces a static bibliography. Make the **submission
copy** (the one that is pinned and shipped) always use a static bibliography that is re-rendered
from the item data + the CSL style, then re-check C13. This resolves F-024…F-028, X-002, F-029 and
F1 mechanically, instead of handing them to the author.

The live field stays in the author’s working copy; the version corpus and the pin carry the static
one. This is consistent with rule 2 (the docx is revision content) and rule 5 (the pinned bytes are
what is scored).

### C15. `FMT-IM2` — accepted artwork formats; `FMT-IM3` — effective text size

**File:** `paper_docx_format.py` `drawing_geometry_rows` (`:6905`) and the media inventory
(`media_pixel_sizes`, `:6821`).

* `FMT-IM2`: an embedded `image*.emf|wmf` in a document that ships is a finding (`formatting`,
  Major) when the venue profile lists accepted formats; the message names the format and the
  accepted set.
* `FMT-IM3`: for embedded PDF/EPS, measure the effective text size from the PDF text layer at the
  placed `wp:extent` width (the review already computed 2.0–3.2 pt by hand; the formatter can call
  `pdftotext -bbox` and scale). For rasters, compute effective DPI. Finding when below the venue’s
  floor. This turns the `M37` proposal (already written in cnb `round2/new_sweeps.md`) into an
  adopted rule.

### C16. `FMT-S9` — page furniture and display-item layout

**File:** `paper_docx_format.py` `layout_consistency_rows` (`:5796`).

* `widowControl w:val="0"` on a body style → finding (a copy-editor setting).
* a drawing paragraph whose following caption paragraph has no `keepNext` → finding.
* a display item that does not start on a fresh page when the venue profile asks for one item per
  page → finding.
* an orphan line (one word on the last line before an unbreakable token) → advisory, measured from
  `pdftotext -layout` when a render is available.

### C17. Recognise the pipeline’s own hand-off file

Covered by C3, but also: `ensure_handoff_readme` (`:7312`) should emit its header and any generated
rows as **bullets ≤ 40 words**, so even if the file is scanned it is clean. The same template should
be given to the agent in the prompt (`AUTHOR_TO_COMPLETE_README_HEADER` + a row shape).

## 3.4 P3 — calibration and certification

### C18. Do not certify a winner that still carries Major formatting items

**File:** `paper_pipeline.py:49982` (`decide` gate), `:42833` (`decide_certification`).

`--format-gate` is opt-in and only counts **HIGH-severity** scan rows. The cnb winner carries
12 Major artwork findings (F-030…F-036, X-901…X-905) that are `manual-required`. Add a default-on
`carried_major_gate`: if the winning package’s effective ledger has ≥ N `Major`/`Critical` rows with
status `manual-required` (N from the profile, default 1), the decision is `provisional` and the
status readme names them. It does not change the ranking (rule 6); it changes the label (rule 10).

### C19. Keep the pin pure

Every change above must preserve: the pin equals the judged bytes (rule 5); no role scores its own
output (rule 7); the champion remains the pure function of the sheets (rule 6); and the no-feedback
path is unchanged (rule 7). C14 changes **which bytes** are pinned (the static-bibliography variant),
so it must run **before** judging, inside the candidate production — never after `decide`.

---

# Part 4 — Rollout order

| Phase | Changes | Why first | Estimated surface |
|---|---|---|---|
| 1 | C1, C2, C3, C4, C5, C6 | Unblocks the revise stage and removes pipeline-caused retries | ~350 lines + 6 tests |
| 2 | C7, C8, C10, C11 | Makes “fixed” mean the sentence is fixed; stops boilerplate closure | ~400 lines + prompt text |
| 3 | C9, C12 | Adds a re-runnable prose gate and a blind copy-edit pass | ~500 lines + 2 prompt blocks |
| 4 | C13, C14, C15, C16, C17 | Closes the formatting classes the winner still violates | ~600 lines in the formatter |
| 5 | C18 | Labels what still ships | ~50 lines |

Verification after each phase:

```bash
python3 -m pytest .paper_test -q                     # the 152-test suite
python3 .paper_test/run_all.py                       # orchestrator-level
python3 paper_pipeline.py selfcheck --sandbox <a revise sandbox> --stage revise --round 1
python3 paper_pipeline.py run --root <a copied root> --only r1_a2_revise   # forced retry
```

Regression fixtures to keep forever (copy into `.paper_test/fixtures/`):
* `revise_scratch_docx/` — the attempt-1 shape (malformed `work/*.docx`);
* `revise_readme_paragraph/` — the attempt-2 shape (600-word hand-off README);
* `cnb_after_token/` — the post-restyle token mismatch;
* `cnb_cover_letter_numbers/` — the cover letter misclassified as `front`.

---

# Part 5 — What this does not fix

* The artwork itself (figure text below 5 pt, the Fig. 3d mark swap, the 150-ppi rasters) cannot be
  re-exported from a read-only `raw_data/`. C15 makes it **visible and unshippable-by-label**, not
  fixed. The operator must supply regenerated figures or accept a provisional decision.
* W13/W19/W23 need a human copy-editor’s judgement; C9 detects the shape, C8 forces the paragraph
  to be rewritten, C12 gives a second blind reader. That raises the probability, it does not make it
  one (rule 8).
* The live Zotero library’s own item data (ref 14’s author array, ref 34’s version) must be fixed in
  Zotero; C14 can render what the data says, not invent the missing authors.

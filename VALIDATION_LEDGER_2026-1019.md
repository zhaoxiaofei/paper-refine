# Validation ledger — every finding from the two audits, re-checked

Date: 2026-10-19. Sources audited: the CNB round-1 winner
(`…/cnb-to34-1019-0025-a755adf/round1_winner/`) and the NeoHeteroclitic revised
package (`…/neohet-to17-1029-0029-a755adf/runs/r1_a2_revise/revised/`).

## Verdicts

| verdict | meaning |
|---|---|
| **CONFIRMED** | The fact holds, the class holds, and (where a rule is claimed) a recorded venue/pipeline rule supports it. |
| **CONFIRMED (caveat)** | The fact holds, but the severity/dependence is narrower than the original wording (renderer-dependent, policy-dependent, or one reading of an ambiguous sentence). |
| **DOWNGRADED** | The fact holds but it is editorial/venue-neutral, not a defect under the recorded rule set. Kept as an observation, removed from the defect count. |
| **RETRACTED** | The claim does not hold. Withdrawn, with the correction recorded. |
| **REFINED** | The defect holds but the mechanism/fix was stated imprecisely; the corrected mechanism is recorded. |

Method: every quoted sentence was matched against the delivered text; every
count/width/page number was re-measured; the two external rules used
(Nature's figure minimum 5 pt / images ≥450 dpi / accessible palette, and the
venue profiles) were re-read from the live guide and the recorded profiles; the
reference-author premise was checked against the cited article's own author
list (Europe PMC).

---

# A. CNB round-1 winner

## A1. Writing findings (W1–W23)

All quotes were found verbatim in the delivered main text; the defect class is a
judgment applied to the quote, recorded in the original report.

| id | short claim | re-check | verdict |
|---|---|---|---|
| W1 | "chiefly accompanied by more accurate ploidy estimation" (F-013 fix) | quote + ledger row whose `evidence` is that sentence | **CONFIRMED** |
| W2 | "explain the disagreements among … Chang" — Chang's conclusion never stated | searched the corpus: "Chang" occurs only in the citation and that sentence | **CONFIRMED** |
| W3 | "which it needs to compute BAF" — dangling pronoun | quote; nearest nouns ambiguous | **CONFIRMED** |
| W4 | "CHISEL's … therefore has substantial potential utility" — non sequitur + filler | quote | **CONFIRMED** |
| W5 | "invert the downsampling … approximately any CN profile" | quote; operations are downsample+merge | **CONFIRMED** |
| W6 | "will be flagged as inconsistent" — benchmark does not flag | quote; no "flag" mechanism in Methods | **CONFIRMED** |
| W7 | "tests whether residual aneuploidy is low, because …" — asserts its own test | quote + the Results sentence denying the establishment | **CONFIRMED** |
| W8 | "which implies" attaches to an expectation | quote | **CONFIRMED** |
| W9 | 3-move sentence, "that variability" referent | quote; F-055 order now claim-first, sentence still scrambled | **CONFIRMED** |
| W10 | "effectively matches the CN ground truth" — circular | quote; Hap_1 defined from the same output | **CONFIRMED** |
| W11 | "near-invariance described above" — no such description | grep: the word occurs once | **CONFIRMED** |
| W12 | paragraph opens "We therefore…" with no premise | quote + preceding paragraph | **CONFIRMED** |
| W13 | 90-word ACT sentence with nested parentheses | word count from the docx | **CONFIRMED** |
| W14 | "Unlike the assay for … or RNA sequencing" — non-parallel | quote; F-040 fixed only the determiner | **CONFIRMED** |
| W15 | Workflow-overview filler sentence | quote | **CONFIRMED** |
| W16 | "more consistent … descriptively" — undefined, no statistic | quote | **CONFIRMED** |
| W17 | "purity floor" coined term | quote; no definition | **CONFIRMED** |
| W18 | "This study has the following limitations. First…" formulaic | quote | **CONFIRMED** |
| W19 | 219-word Data availability paragraph | word count | **CONFIRMED** |
| W20 | Fig. 5 legend: three connectives for one enumeration | quote | **CONFIRMED** |
| W21 | Fig. 4 legend asserts the paper's conclusion | quote | **CONFIRMED** |
| W22 | "metric-dependent" undefined | quote | **CONFIRMED** |
| W23 | Software version list: three version forms + `copynumber` case | quote | **CONFIRMED** |

## A2. Formatting findings (F1–F12)

| id | short claim | re-check | verdict |
|---|---|---|---|
| F1 | Reference 15 bolds `11, 505441 (2020).` | OOXML run `<w:rPr><w:b/>` on that text; new `FMT-T6h` detects it | **CONFIRMED** |
| F2 | Refs 10/11/21/23/42 use hyphen page ranges | grep of the five entries | **CONFIRMED** |
| F3 | Ref 14 truncates a four-author paper to "et al." | Europe PMC: the Copynumber paper has **12 authors**, not 4; the list's >10 truncation is consistent | **RETRACTED** |
| F4 | Ref 34 has no journal/volume and a spaced hyphen | quote | **CONFIRMED** |
| F5 | Fig. 1 is EMF; panel f renders as mojibake | OOXML media 8.7 MB EMF; LibreOffice render shows mojibake; Word renders it correctly. Nature's guide *prefers* PDF/EPS but does not ban EMF | **CONFIRMED (caveat)** — renderer-dependent font substitution, not format rejection |
| F6 | Figure text 2.0–3.2 pt at printed width | independently re-measured from the source PDFs: Fig 2 **2.78**, Fig 3 **3.20**, Fig 4 **2.03**, Fig 5 **2.84** pt; Nature guide minimum **5 pt** | **CONFIRMED** |
| F7 | "at" alone on a line before the long URL | `pdftotext` page 23 lines 727–729 | **CONFIRMED** as a typographic orphan (no venue rule) |
| F8 | `widowControl=0`, 1.5 spacing on refs/legends, line numbers on | OOXML: all true. Nature's initial submission "does not need to be specially formatted" and states no spacing/line-number rule | **DOWNGRADED** to editorial |
| F9 | Alt text differs from Fig. 1/Fig. 4 legends | `docPr descr` read; the audit dropped F-019 as not a rule violation | **DOWNGRADED** to advisory |
| F10 | Abstract is not a Heading style | OOXML `pStyle` absent; no venue rule on semantic styles | **DOWNGRADED** to editorial/accessibility |
| F11 | SI: line numbers on title/abstract; `\small` captions for S1–S22 only; red–green palette; 150-ppi rasters | `\linenumbers`, `\small` at the S1–S22 macro and Table S1, `red-to-green` sentence, `pdfimages` 1719×1728 at 150 ppi all verified | **CONFIRMED** for the caption-size inconsistency, palette and 150-ppi rasters; line numbers **DOWNGRADED** |
| F12 | The winner dir is 409 MB; one tracking PDF is 391 MB | `du`/`ls` | **CONFIRMED** as packaging hygiene (not a submission defect) |

## A3. Codebase root causes (R1–R15)

| id | claim | re-check | verdict |
|---|---|---|---|
| R1 | Revision edits are finding-scoped; no whole-paragraph re-read | `LANGUAGE_PASS_RULE` says "every edited sentence" | **CONFIRMED** |
| R2 | The ledger verifies ids only; `evidence` may be a location | `revision_ledger_problems` reads ids; F-013's evidence is the new sentence, F-043's is a location | **CONFIRMED** |
| R3 | No sentence-level quality gate | formatter rule list: no fragment/dangling/connective rules | **CONFIRMED** |
| R4 | The format sweep reads `.bib` abstracts as prose | 44 of 58 `FMT-T9c` rows were "bibliography abstract"; the `.bib` has 30 `abstract =` fields | **CONFIRMED** |
| R5 | `--strict-dispositions` is opt-in, so boilerplate closures pass | `DEFAULT_ARTIFACT_POLICY = "on"`; the cnb config is `on`. The detector compares the WHOLE disposition string, so a template with a per-row token evades it | **RETRACTED** as stated; **REFINED**: the detector is too literal, not the policy too weak |
| R6 | No rules for reference emphasis, table grid, PAGE fields, figure labels | rule registry had none | **CONFIRMED** |
| R7 | The judges found zero writing rows on the winner | `round1_issue_matrix.csv` a2: no writing fields | **CONFIRMED** |
| R8 | `sandbox_selfcheck` is a strict subset of the postcheck | no calls to the normalizer/validator/regression scan | **CONFIRMED** |
| R9 | The retry prompt points at a sibling sandbox it forbids reading; the old package is not carried | prompt text + `materialize_revise` copies nothing | **CONFIRMED** |
| R10 | The token mismatch is caused by the postcheck's own restyle | `FORMAT_FIX` changes 4 on 2 docs after the token; warning blamed the agent | **CONFIRMED** |
| R11 | Number provenance includes the cover letter as "front" | `section_kinds` on the letter: every body paragraph `front` | **CONFIRMED** |
| R12 | `validate_paths` recurses into `work/` scratch | `validate_paths([pkg_dir])` + no work exclusion | **CONFIRMED** |
| R13 | `README-AUTHOR-TO-COMPLETE.md` is scanned as manuscript prose | not in `BOOKKEEPING_FILES`; no README skip in the sweep | **CONFIRMED** |
| R14 | The new-family error carries no location | message had counts only | **CONFIRMED** |
| R15 | The declared-submission parser fails on the CNB/neohet README shape (pattern after "venue/journal:") | `declared_submission_set` returned `declared: False` on both packages; all carried files counted as submitted | **CONFIRMED (new)** — the root cause of R13's real-world effect |

---

# B. NeoHeteroclitic revised package

## B1. Major findings (M1–M7)

| id | short claim | re-check | verdict |
|---|---|---|---|
| M1 | "shipped per-candidate tables" contradicts Data Availability, and the deposit lacks the tables | two "shipped" sentences in the SI; pinned `hpep/` (GitHub API) has scripts/results/audit/FASTA only; `raw_data/hpep-v07.zip` is not submitted; Drost tables in neither | **CONFIRMED** |
| M2 | "every parental antigen is … held-out" vs "parental peptides were not screened" | both quotes in Methods | **CONFIRMED** |
| M3 | "candidate set contains every peptide with a single mismatch" vs the binding filter | both quotes in Methods | **CONFIRMED** |
| M4 | Step 4 does not state all/any/default | quote | **CONFIRMED** |
| M5 | Table 3 breaks every dataset ID | OOXML: grid `[1050,…]` vs cells `[1370,…]`; LibreOffice (grid) wraps, Word (cells) likely does not. The **grid/cell disagreement** is the defect; the wrap is one renderer's resolution | **REFINED** |
| M6 | Figure 1 prints `Hetero/clitic`, `Homo/clitic`, `FastQ` | native PNG inspected; Tesseract did not OCR the small insets and does not contain "FASTQ" in the text vocabulary | **CONFIRMED** (visual), with the OCR rule noted as low-recall on this artwork |
| M7 | Figure S1 prints `PRIME_BARank`; text is `PRIME_BArank` | native PNG + text grep | **CONFIRMED** |

## B2. Writing findings (W1–W12)

| id | short claim | re-check | verdict |
|---|---|---|---|
| W1 | "opposite conclusion" vs "does not contradict" | both quotes in the Discussion | **CONFIRMED** |
| W2 | "reported only nine analog measurements" reads as the whole study | Tangri et al. Table 1: the affinities of **nine heteroclitic analogs** were measured; the statement is true but ambiguous next to Methods' 117/116 assayed analogs | **CONFIRMED (caveat)** — ambiguity, not error |
| W3 | "clear clinical value" unsupported | Maslak et al. phase 2 met its OS endpoint but the authors say efficacy "will need to be addressed in a larger trial"; the manuscript cites testing only | **CONFIRMED** |
| W4 | "Those outcomes…" has no antecedent in the letter | quote + preceding sentence | **CONFIRMED** |
| W5 | "Per dataset … mean SCC" | Figure 3's Mean row | **CONFIRMED** |
| W6 | 240-word multi-topic paragraph; `p = 0.25` vs the deposited `0.2344` | word count 240; public `neoheterocliticAggregate_results.txt` gives 0.2344 (other paired p's match) | **CONFIRMED** (paragraph); **CONFIRMED (caveat)** (p may be a different run) |
| W7 | "five terms" but more are defined | quote + count | **CONFIRMED** |
| W8 | Abstract "was the exception" names no contrast | quote | **CONFIRMED** |
| W9 | "usable signal about how a peptide will be seen by T cells"; "unlikely ever to be seen by TCRs" | quotes; the benchmark measures heteroclitic labels, not TCR recognition | **CONFIRMED** (overclaim) |
| W10 | "dominant input … doing the work" vs "cannot separate" | both quotes | **CONFIRMED** |
| W11 | "(Zhou et al., 21)" mixes author-year and numeric | quote | **CONFIRMED** |
| W12 | "The result is not a restatement…" — no referent | quote | **CONFIRMED** |

## B3. Formatting findings (F1–F7)

| id | short claim | re-check | verdict |
|---|---|---|---|
| F1 | two page numbers on a page | `footer_venue_default.xml` has two PAGE fields, **both inside floating text boxes**; LibreOffice p. 30 prints `16` and `30`; Word prints both fields (same value) | **CONFIRMED** (fix is manual: delete one text box) |
| F2 | Table 3 continuation pages have no "(continued)" marker; Table 3 is 3 pages | render pp. 31–33 | **CONFIRMED** (marker); the multi-page rule is a typesetting-stage sentence — advisory |
| F3 | Figure 4 panels have no length labels; y labels `A0201`/`B0702` vs `HLA-A*02:01` | native PNG | **CONFIRMED** |
| F4 | Figure 1 179 dpi / Figure S2 268 dpi at 180 mm | 1269/7.0866 = 179.1; 1899/7.0866 = 268.0. The Frontiers profile records **no** dpi rule | **DOWNGRADED** to production advisory |
| F5 | Ref 23 still prints `1 -targeting` | delivered DOCX text | **CONFIRMED** |
| F6 | "Document S1" is a Cell Press label | the Frontiers profile's own vocabulary is "Supplementary Figure/Table" | **CONFIRMED** (advisory) |
| F7 | `SD` unexpanded in the abstract; BLOSUM62 expansion imprecise | quote | **CONFIRMED** (minor copyedit) |

## B4. Ledger-vs-package rows

| row | re-check | verdict |
|---|---|---|
| X-911 | ledger claims the ID column fits; grid was changed but the cells were not | **CONFIRMED (REFINED to M5)** |
| F-006 | intro and Data Availability reworded; two "shipped" sentences remain in the SI | **CONFIRMED** |
| X-910 | Figure 1 labels unchanged | **CONFIRMED** |
| X-901 | text aligned; figure axis unchanged | **CONFIRMED** |
| F-031 | library updated; DOCX field not refreshed | **CONFIRMED** |

---

# C. Corrections to the previous reports

1. **CNB ref 14 / X-002 is a false positive (retracted).** The Copynumber paper
   has 12 authors (Nilsen, Liestøl, Van Loo, Moen Vollan, Eide, Rueda, Chin,
   Russell, Baumbusch, Caldas, Børresen-Dale, Lingjaerde), not four. "Nilsen,
   G. et al." is consistent with the list's >10-author truncation. The audit
   confirmed a finding whose premise was wrong; the new pipeline should require
   a reference finding's author count to be checked against the item/DOI before
   filing.
2. **CNB "strict dispositions are opt-in" is wrong (retracted).** The default is
   `on` and the CNB root used `on`. The real defect is that
   `disposition_artifact_problems` compares the whole disposition string, so a
   template with a per-row token is not detected. Fixed with a skeleton
   comparison.
3. **CNB "EMF is not an accepted format" is too strong (retracted/softened).**
   Nature *prefers* PDF/EPS and requires editable vector text; it does not ban
   EMF. The verified defect is that the EMF's text depends on the renderer's
   fonts (panel f mojibake in LibreOffice).
4. **CNB spacing / line numbers / widow control / heading style are editorial
   (downgraded).** Nature's initial submission "does not need to be specially
   formatted"; no recorded rule makes them defects.
5. **Neohet "nine analog measurements" is not an error (caveat).** Tangri et al.
   measured the affinities of nine heteroclitic analogs; the sentence is true
   but ambiguous. The fix is "affinities for nine of the analogs", not a
   correction.
6. **Neohet Table 3 is a grid/cell disagreement (refined).** The revision changed
   `w:tblGrid` but not the cells' `w:tcW`; Word and LibreOffice resolve the
   conflict differently. The fix is to make them agree, not simply "widen".
7. **Neohet figure dpi is advisory (downgraded).** The venue profile records no
   dpi rule; the measured numbers stand as a production note.
8. **Neohet `Document S1` / SD / BLOSUM are advisory/minor (downgraded).** No
   rule is violated; a copy-editor would raise the first two, the third is a
   common shorthand.

---

# D. Code changes made (prevention + repair)

All changes are uncommitted, in `paper_docx_format.py`, `paper_pipeline.py`, and
the new test file `.paper_test/test_layout_integrity_2026_1019.py`.

## D1. New scan rules (`paper_docx_format.py`)

| rule | class | prevention |
|---|---|---|
| `FMT-TB4` | `w:tblGrid` ≠ cells' `w:tcW` | both resolutions are computed; the row names the table |
| `FMT-TB5` | an identifier cannot fit its column | token width vs usable width at the cell font size |
| `FMT-S10` | >1 PAGE field in a referenced header/footer part | only referenced parts; text-box shapes are labelled manual |
| `FMT-IM4` | raster below `min_image_dpi` at the placed width | policy-driven (0 = off); venue profiles can set the number they state |
| `FMT-IM5` | figure OCR spells a manuscript term differently | split-form and acronym-case variants; a missing tesseract is a recorded gap |
| `FMT-T6h` | bibliography bold run covers a year/page range | catches the CNB ref 15 shape |
| `FMT-AV3` | "shipped/deposited/in the repository" with no locator | catches the neohet "shipped tables" sentences |

`bib_prose_paragraphs()` now scans only title/venue/note fields (0 long-sentence
rows on the CNB `.bib`, down from 44), so the review's seeded table is signal.

## D2. Repair (`paper_docx_format.py repair-layout`)

`repair-layout FILE.docx --out FILE.docx` rewrites `w:tblGrid` from the cells
(and widens a column for `FMT-TB5`), removes duplicate plain-paragraph PAGE
fields, verifies the visible text is unchanged, writes a new package, and
re-scans. Text-box PAGE fields are left to the author with a precise message
(the neohet footer shape). Tested end-to-end on the neohet main text: the two
table grids become consistent and the re-scan is clean for TB4/TB5.

## D3. Submission surface and scope (`paper_pipeline.py`)

* `declared_submission_set` now parses a pattern that follows a short lead-in
  ("… will be submitted to the venue/journal:" then the code block) — it was
  failing on both real packages, so every carried file counted as submitted.
* `scan_format_in_sources` honours that declaration for docx, tex, md and bib
  files, skips README* and `work/`, and OCRs only declared figure files.
* `_validation_targets` validates only the declared docx/tex: a malformed scratch
  file under `work/` can no longer fail a stage (the neohet attempt-1 shape).
* `sandbox_selfcheck` for revise now runs deliverable validation and the
  new-family regression check through the same helpers the postcheck uses.
* `scan_regression_problems` accepts `policy=` with no Ctx and names the first
  rows (document/location/evidence) in the error.
* `number_provenance_report` skips cover letters.
* `disposition_artifact_problems` compares a skeleton (parentheticals/quotes/
  numbers removed) and reports templated closures.
* `materialize_revise` copies the rejected package into `previous_attempt/`; the
  revise directives allow reading it.
* `_record_revision_token` attributes a post-restyle mismatch to the pipeline's
  own FORMAT_FIX.

## D4. Verification

| command | result |
|---|---|
| `pytest .paper_test/test_layout_integrity_2026_1019.py` | 9 passed |
| `run_all.py --only` the 11 affected suites | 11 passed |
| `repair-layout` on the neohet main text | 2 table grids fixed; text byte-identical; docx validates; re-scan clean for TB4/TB5 |
| new scan on the neohet package | TB4 ×2, TB5 ×1, S10 ×1, AV3 ×2; no README/no `work/` rows |
| new scan on the CNB winner | T6h catches ref 15; no AV3 false positives |
| full suite, `run_all.py -j 24` | **135/135 passed** (with `python-docx` and `openpyxl` on `PYTHONPATH`, the two dependencies `.paper_test/README.md` names) |
| bugs found during this verification and fixed | a `NameError` in `availability_claim_rows` (caught by the new test); an uncaught `RuntimeError` in the OCR text read (an encrypted `.docx` crashed `scan_paths`; caught by the pre-existing G2 test); merged/nested tables excluded from the table repair; the repair creates its output parent |

---

# E. What is still not covered

* `FMT-IM5` OCR did not catch either known artwork defect on the neohet package
  (small inset text and the case of `PRIME_BARank` survived Tesseract). The rule
  is a sampler; the reliable prevention is the visual-check prompt item "read
  each figure's own labels and compare them with the text", which is not yet
  added to the prompt.
* A claim contradicting another section (M2, M3) is only partly mechanical; the
  new pass reports universal claims and denials side by side for the reviewer,
  but it does not decide.
* The availability rule (`FMT-AV3`) is deliberately narrow; a claim that names
  a URL which does not carry the promised file still needs the deposit-coverage
  check (M33) to be extended.
* The PNAS/Nature reference-author threshold is venue-specific; the false
  positive was caused by the reviewer not checking the author count, not by a
  missing rule. A "reference findings must record the item's author count"
  requirement is the next prompt change.

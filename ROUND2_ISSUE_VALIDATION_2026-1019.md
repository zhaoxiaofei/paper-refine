# Round-2 issue validation and code-improvement record

Date: 2026-10-19. Companion to
`ROUND2_AUDIT_AND_CODE_REVISION_PLAN_2026-1019.md`.

Purpose: re-check every issue the audit named, drop what does not survive the
check, correct what was stated imprecisely, and record what the repository now
does about each surviving class. The pipeline code was changed; the manuscript
packages were not (they are read-only delivered artifacts, and the code that
must change is the pipeline).

Verdicts:

| verdict | meaning |
|---|---|
| **CONFIRMED** | the quote/measurement holds and the class is a defect under the recorded rule set |
| **CONFIRMED (caveat)** | the fact holds but the severity/mechanism is narrower than first stated |
| **CORRECTED** | the issue holds; a number, mechanism or location in the first report was wrong |
| **FALSE POSITIVE** | the claimed defect does not hold |
| **ADVISORY** | a production observation, not a defect under a recorded rule |
| **NOT A SUBMISSION DEFECT** | true of the package, not of the submitted files |

---

## A. CNB round-2 winner

| # | issue | verdict | validated evidence |
|---|---|---|---|
| C1 | Main-text Figs. 2–5 text below the venue's 5-pt floor | **CONFIRMED** | Fig. 3 source PDF word-box geometry: native 5.09 pt × printed scale 0.63 = **3.20 pt**. The other three source PDFs are Type-3/text-path art; OCR of the delivered rasters measures 1.9, 2.2, 3.0 and 1.8 pt. Media bytes are identical to round 1. |
| C2 | Supplementary figures below 5 pt | **CONFIRMED** | Rendered p. 11 (S1) at 600 dpi: median figure-word height 18 px → **2.16 pt**. S23's row labels are not OCR-readable at print size; S31–S36 use a red–green scale. |
| C3 | Reporting Summary Randomization says "no overlap" while Methods disclose overlap | **CONFIRMED** | NR p3 quote vs Methods "the threshold was selected on data that overlap the evaluation set … no held-out rerun was performed". |
| C4 | Blinding says "no manual scoring" while the HG008 comparison is a descriptive visual reading | **CONFIRMED** | NR p3 quote vs Methods "a qualitative reading of the clusters" and Results "This comparison is descriptive". |
| C5 | Replication says failed/no-output cases are in the deposited tables, but the Fig. 3 table encodes none | **CONFIRMED** | `raw_data/source_data/Fig3_ploidy_balloons.tsv` has 1,815 rows, every row `failed=False`, and no SCYN ACT row. |
| C6 | Data availability says source data are in the repositories while the main text says the pipelines regenerate them | **CONFIRMED (caveat)** | The two sentences can coexist if the repositories carry the tables; the package does not show that they do. Kept as a lower-confidence consistency item, not one of the three hard contradictions. |
| C7 | "Eukaryotic cell lines" field is unanswered | **CONFIRMED** | NR p3: the label is followed directly by "Palaeontology and archaeology"; no Yes/No/n-a. |
| C8 | Table S3's Holm family is arithmetically inconsistent | **CONFIRMED** | 19 rows, caption "single pooled family"; n=9 min p = 2/512 = 0.003906, 19-test floor 0.0742; the table prints 0.030 (= 8 × 0.003906). The n=21 Copynumber row 1.81e-5 equals the 19-test floor. |
| C9 | "residual aneuploidy and CNP are negligible" vs the correction's large effects | **CONFIRMED (caveat)** | Not a strict contradiction: "relative to the CNVs we introduce" qualifies it. It is a claim-strength defect because the Results say the data do not establish the premise. |
| C10 | "the near-invariance described above" has no antecedent | **CONFIRMED** | `near-invariance` occurs once in the text; the preceding paragraph says "metric- and caller-specific rather than uniformly slight". |
| C11 | "invert the downsampling" misdescribes the method | **CONFIRMED** | The method downsamples and merges; no inversion step exists. |
| C12 | "tests whether the residual aneuploidy is low, because …" asserts its own premise | **CONFIRMED** | The `because` clause states the hypothesis the sentence says is under test. |
| C13 | "which implies" attaches to an expectation | **CONFIRMED** | "We therefore expected … which implies that the consistency check approximates…". |
| C14 | "will be flagged as inconsistent" has no flag mechanism | **CONFIRMED** | The benchmark scores callers; no flagging component is described. |
| C15 | Circular haploid-ground-truth sentence | **CONFIRMED** | "a caller's output on the haploid input effectively matches the CN ground truth, and the agreement of the two references supports this interpretation rather than replacing it." |
| C16 | "purity floor" coined and undefined | **CONFIRMED** | One occurrence; no definition follows. |
| C17 | three-move correction sentence | **CONFIRMED** | "Because … we expected stability, but that variability does not establish …" in one sentence; "that variability" points to the previous sentence. |
| C18 | paragraph opener "We therefore examined" with no premise | **CONFIRMED** | It opens the ploidy subsection; the preceding paragraph ends on Ginkgo's publication year. |
| C19 | ACT sentence is a 90-word monster | **CORRECTED** | The sentence is **82 words**, not 90 (counted from the DOCX). The defect (an 82-word sentence with four nested parentheticals) stands. |
| C20 | Data availability is 219 words | **CONFIRMED** | Word count 219. |
| C21 | "This study has the following limitations. First…" formulaic enumeration | **CONFIRMED** | The paragraph is 138 words; the first item runs to ~120 words, the second to 23. |
| C22 | CHISEL "therefore has substantial potential utility" non sequitur | **CONFIRMED** | The preceding sentence explains why CHISEL underperformed; "therefore" argues the opposite. |
| C23 | "which it needs" dangling relative | **CONFIRMED** | Nearest antecedents: the data / Numbat / the requirement. |
| C24 | "explain the disagreements among Song, Schmid and Chang" overstated | **CONFIRMED (caveat)** | The paragraph states Chang agrees with Song on Numbat; only Schmid differs on dataset dependence. The "three-way disagreement" framing is too strong; minor. |
| C25 | "Unlike the assay for ATAC-seq or RNA sequencing" non-parallel | **CONFIRMED** | "assay for" governs ATAC-seq but not RNA sequencing; ATAC-seq is expanded and never used again. |
| C26 | "metric-dependent" undefined in the abstract | **CONFIRMED** | No definition in the abstract or at first use. |
| C27 | Ref. 15 bolds the volume, article number and year | **CONFIRMED** | OOXML: the run `11, 505441 (2020).` carries `<w:b/><w:bCs/>`; every other entry bolds the volume only. |
| C28 | Refs. 10/11/21/23/42 use hyphen-minus page ranges | **CONFIRMED** | Dash characters are U+002D in all five; the rest of the list uses en dash. |
| C29 | Ref. 34 has no journal/volume and a spaced hyphen | **CONFIRMED** | "GitHub - jlaffy/infercna …" with no venue/volume. |
| C30 | Five titles are title case where the list is sentence case | **CONFIRMED** | Refs. 11, 21, 34, 40, 42. |
| C31 | Fig. 2 legend says "six metrics" but lists five | **CONFIRMED** | It names intCN_accuracy, intCN_PCC, nonintCN_PCC, CN_genome_cov_frac, intCN_modal_frac; breakpoint_f1score is only mentioned later as the parent of precision/recall. |
| C32 | Fig. 4 legend asserts the paper's conclusion | **CONFIRMED** | "This pattern is consistent with Ginkgo's leading overall balance…" on a descriptive heatmap. |
| C33 | Fig. 4 plots missing values at CN = 2 | **CONFIRMED** | The legend says exactly that; a reader cannot distinguish no-call from diploid. |
| C34 | Fig. 5 legend uses three connectives for one enumeration | **CONFIRMED** | "from top to bottom" + "Below them, the panels show" + "This is followed by". |
| C35 | Fig. 3 caption "Red X, no output" vs artwork key "Missing" | **CONFIRMED (minor)** | Marks match Methods (SCYN red X, CHISEL hatched); only the key word differs. |
| C36 | `CERTIFIED` beside `NOT READY` | **CONFIRMED** | `final_clean_version.readme.md` first line vs the readiness paragraph; the directory is then called "the certified champion corpus". |
| C37 | Both roots ran an old pipeline snapshot | **CONFIRMED** | Root `paper_pipeline.py` sha256 `06047562…`, formatter `48171b65…`; workspace `5ed1ec3f…` / `ee76ee34…`. `grep -c FMT-AV3/IM5/TB5/T6h` = 0 in both roots, >0 in the workspace. |
| C38 | `FMT-IM5` masked split labels when the term appeared intact | **CONFIRMED** | On the delivered Figure 1 the old loop skipped `Heteroclitic` because the top-line `Heteroclitic` was present; the inset `Hetero`/`clitic` was never checked. |
| C39 | `FMT-TB5` missed allele names | **CONFIRMED** | Old regex `^[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)*\d[A-Z0-9]*$` does not match `HLA-A*02:01` (`*`, `:`), `H2-K^b^`, `MHC-anchor`, `TCR-facing`. |
| C40 | `FMT-AV3` did not scan PDFs | **CONFIRMED** | `scan_format_in_sources` iterated DOCX/text only; the CNB supplement and Reporting Summary are PDFs. |
| C41 | `FMT-T6h` detects but cannot repair the live field | **CONFIRMED** | Rule fires as `fix=style-field, protected=True`; no submission-copy normalizer existed. |
| C42 | no statistical family-floor check | **CONFIRMED** | No function parsed n/p/caption family; Table S3 passed. |
| C43 | no cross-document claim reconciliation | **CONFIRMED** | The held-out/shipped/near-invariance pairs are in different paragraphs/documents; no pass compared them. |
| C44 | PKG-3 flags `neoheterocliticAggregate.py` although the sentence names the repository | **FALSE POSITIVE — WITHDRAWN** | Current `_sentence_has_locator` returns True on that sentence (`repository` is a locator); the advisory in the round-2 readme came from the stale snapshot. No current-code defect; a regression test is still useful. |
| C45 | The README submission rule is "ignored" | **FALSE POSITIVE — WITHDRAWN** | Current `declared_submission_set()` parses both README globs: `declared=True`, 4 files for CNB, 10 for neohet. The round-2 note came from the old snapshot. |
| C46 | Fig. S1 prints `PRIME_BARank` | **FALSE POSITIVE** | The delivered PNG says `PRIME_BArank` (cropped and upscaled axis label). The item is an OCR false positive in the review ledger. |
| C47 | The manuscript uses `FASTQ` and the figure prints `FastQ` | **FALSE POSITIVE (rationale only)** | The manuscript never writes `FASTQ` (zero hits in the DOCX XML). The figure's `FastQ` is still nonstandard and is kept as a minor spelling finding with the corrected rationale. |
| C48 | Supplementary S23–S30 are 150-ppi rasters | **CORRECTED** | Current PDF embeds them at **274 ppi**; the text is still ≈2–3 pt and below the floor. |
| C49 | Figure 1 is an 8.7 MB EMF | **NOT A DEFECT** | It is vector art; Word renders it correctly. The earlier "EMF is not accepted" claim was withdrawn by the prior audit. |

**CNB summary.** 45 of the named issues survive, 3 are false positives
(C44–C46), 1 is a false rationale with a true minor defect (C47), 2 are
corrections (C19, C48), and 1 is explicitly not a defect (C49). The major
classes are the figure legibility, the Reporting Summary contradictions and
the Table S3 family.

---

## B. NeoHeteroclitic round-2 winner

| # | issue | verdict | validated evidence |
|---|---|---|---|
| N1 | "every parental antigen is … a held-out antigen" vs "the parental peptides … were not screened" | **CONFIRMED** | Both sentences are in the same Methods; the audit paragraph explicitly says several parents are standard class-I ligands. |
| N2 | Supplement says "shipped per-candidate tables" while Data Availability says "not part of that repository" | **CONFIRMED** | Figure S3 legend and Table S2 note say "shipped"; Data Availability and the supplement introduction say "not part of the repository / available from the corresponding author". The submission carries neither `raw_data/` nor `code/`. |
| N3 | Figure 1 prints `Hetero`/`clitic` and `Homo`/`clitic` split over two lines | **CONFIRMED** | Visual crop of both insets; words are on separate lines. |
| N4 | Figure 1 prints `FastQ` not `FASTQ` | **CONFIRMED (spelling only)** | OCR reads `FastQ files`; the manuscript never uses `FASTQ`, so the "parity with the manuscript" rationale is wrong. The acronym spelling is still nonstandard. |
| N5 | Table 3 breaks `HLA-A*02:01` and `HLA-B*07:02` mid-token | **CONFIRMED** | MHC column 820 twips (0.57 in); the token needs ≈1,200–1,400 twips at 9 pt. The LibreOffice render prints `HLA-` / `A*02:01`. `MHC-anchor` / `TCR-facing` also break at the hyphen; that is a lesser typographic observation. |
| N6 | He et al. D20–D26 binary labels are not mapped to a readout | **CONFIRMED** | Table 3 header has no `Readout` column (0 occurrences in the DOCX); Methods says both tumor-growth rate and tetramer-positive fraction were thresholded. |
| N7 | CALR long-peptide register construction is not described | **CONFIRMED** | Methods only says D11/D13 were not scored through the WT1 window; Table 3 gives 6,192 and 120 candidates with no construction rule. |
| N8 | Ref. 23 prints `tumor 1 -targeting` | **CONFIRMED** | Verbatim; a visible space before the hyphen. |
| N9 | "reported only nine analog measurements" is ambiguous | **CONFIRMED (caveat)** | Tangri's benchmark sets D15/D16 carry 118/117 candidates and 117/116 assayed analogs; the sentence can be read as "only nine analogs were assayed". It is an ambiguity, not a factual error. |
| N10 | Figure S1 prints `PRIME_BARank` | **FALSE POSITIVE** | The PNG says `PRIME_BArank`; the review OCR misread it. The current `FMT-IM5` does not reproduce it. |
| N11 | Figure resolution below the venue's 300-dpi rule | **CONFIRMED** | Frontiers' author guidelines (recorded in the profile's own source tree) state 300 dpi at final size. Figure 1 = 195 dpi and Figure S2 = 292 dpi at 6.5 in. The prior audit's "no dpi rule" was too narrow: it read the profile's caption block, not the guideline source. |
| N12 | Figure text below the venue's 8-pt rule | **CONFIRMED (new)** | At 6.5 in: Figure 1 7.0–7.6, Figure 2 4.8, Figure 3 4.8–5.1, Figure 4 3.4–3.6, Figure S1 5.7–6.9, Figure S2 7.4–7.9, Figure S3 2.8–3.0 pt. Frontiers states "no less than eight points". |
| N13 | Figure 4/S1/S2 carry no DPI metadata | **ADVISORY** | Effective dpi at the placed width is the rule; metadata absence alone is not a defect. |
| N14 | `code/README_RERUN.md` says the tables are "shipped in raw_data" | **NOT A SUBMISSION DEFECT** | The README is not submitted; the submitted supplement's "shipped" is the defect (N2). The README's "package" wording should still be scoped to avoid confusing the next run. |

**Neohet summary.** 11 issues survive (N1–N9 and N11–N12; N9 is a caveat and
N11–N12 are the two figure-rule findings upgraded from advisories under the
Frontiers guideline source); 1 is a false positive (N10); 1 is not a submission
defect (N14).

---

## C. Code-level findings

| # | claim | verdict | evidence |
|---|---|---|---|
| P1 | The roots ran a frozen pipeline older than the workspace | **CONFIRMED** | Digests and missing rule ids above; the round-2 `FORMAT_SCAN_final.json` has no FMT-AV3/IM5/TB5/T6h rows. |
| P2 | `FMT-IM5` masked a split label when the term appeared intact | **CONFIRMED** | The old loop's `if term in text: continue`; Figure 1's top-line `Heteroclitic` masked the inset split. |
| P3 | `FMT-TB5` token grammar missed alleles/hyphenated labels | **CONFIRMED** | Regex test; Table 3's `HLA-B*07:02` not matched. |
| P4 | `FMT-AV3` did not scan PDFs | **CONFIRMED** | `scan_format_in_sources` no `.pdf` branch. |
| P5 | `FMT-T6h` has no repair path | **CONFIRMED** | `fix=style-field, protected=True`; no flatten/normalize behind it. |
| P6 | no Holm-family arithmetic check | **CONFIRMED** | No parser; Table S3 shipped. |
| P7 | no cross-surface claim check | **CONFIRMED** | All three contradictions in the two packages are cross-paragraph or cross-document. |
| P8 | readiness is not part of the certification label | **CONFIRMED** | `CERTIFIED` + 81/12 package findings in the same readme. |
| P9 | the PKG-3 `neoheterocliticAggregate.py` advisory is a current-code false positive | **FALSE POSITIVE** | Current `_sentence_has_locator` matches `repository`; the row came from the stale snapshot. |
| P10 | the README submission rule is not parsed | **FALSE POSITIVE** | Current `declared_submission_set` returns `declared=True` with the 4/10 files. |

---

## D. What the repository now does

### Prevention (new or repaired detectors)

1. **`paper_docx_format.py`**
   * `FMT-IM5` — split/case checks now run even when the term appears intact;
     `_ocr_text_variants()` adds an inverted/thresholded OCR pass and psm 6/11,
     which reads the neohet inset labels; canonical acronyms (`FASTQ`, `TCR`,
     `pMHC`, …) are included; short-term (`Het`+`Mut`) line-wrap artifacts are
     excluded from the split rule.
   * `FMT-TB5` — `TABLE_IDENTIFIER_RE` now covers allele names
     (`HLA-A*02:01`), H2/H-2 names and hyphenated compound labels; the width
     test still runs on every column. `repair-layout` can then widen the MHC
     column; on the neohet main text it now produces `HLA-A*02:01` on one line
     (verified in the rendered PDF).
   * `FMT-IM6` — new: measures OCR word-box height in a DOCX-placed raster
     against its `wp:extent`, reports the printed point size against the
     venue's `figure_text.min_pt`; also for standalone `figures/*.png`.
   * `FMT-IM4` — now finding-tier when the venue profile states a dpi floor;
     also measured for standalone figure files.
   * `FMT-T9L` — logic inversions (`tests whether … because`,
     `expected … which implies`, `invert the downsampling`, `flagged`,
     `which it needs`, `accompanied chiefly by`), plus the formulaic
     limitations opener and section-opening `We therefore`.
   * `FMT-T9A` — "the X described above" with no antecedent X.
   * `FMT-T9U` — undefined `approximately any`, `metric-dependent`,
     `purity floor`.
   * `FMT-CN1` — "the six metrics are …" that names fewer than six metric ids;
     ignores count sentences with no metric ids (precision fix after the first
     run produced two PDF false positives).
   * `FMT-LG1` / `FMT-LG2` — a descriptive legend that argues the paper's
     conclusion, and one enumeration with several connectives.
   * `FMT-ST1` — parses the table rows and caption's family size (PDF layout
     and LaTeX), computes the attainable Wilcoxon minimum and the Holm floor,
     and flags a p below it. A 2% rounding tolerance keeps the n=21 rounded
     floor from becoming a false positive.
   * `FMT-SR1` — Reporting Summary field labels with no Yes/No/n-a answer; the
     first run's six heading false positives were removed by restricting the
     labels to the Materials & experimental systems fields and requiring the
     label to open the line.
   * `J6-CONTRADICTION` / `FMT-AV4` — pairwise opposite claims: held-out vs
     not-screened, shipped vs not-in-repository, no-overlap vs overlap,
     no-manual-scoring vs descriptive/visual reading, negligible vs
     not-negligible, near-invariance vs variability.
   * `image_resolution_rows()` — standalone figure dpi against the venue floor.

2. **`paper_pipeline.py`**
   * `scan_format_in_sources()` now scans submitted **PDFs** (the CNB
     supplement and Reporting Summary) for text style, availability claims,
     statistics and Reporting Summary gaps.
   * The cross-surface claim check runs once after all DOCX/text/PDF
     paragraphs are collected.
   * Standalone figure files get `FMT-IM5`, `FMT-IM6` and `FMT-IM4` rows.
   * Scan rows are deduplicated by rule/document/location/evidence, so the
     DOCX path and the standalone figure path cannot double-report one defect.
   * `pipeline_identity()` records a **three-module manifest**
     (`paper_pipeline.py`, `paper_docx_format.py`,
     `paper_redlines_adapter.py`).
   * `root_pipeline_staleness()` compares the frozen modules with the
     maintained tree; `pipeline_snapshot_note()` warns; `refuse_foreign_pipeline()`
     refuses a state-changing command when a post-manifest root's modules have
     drifted.
   * `sync-code --root <root>` copies the maintained three-module bundle into
     a root, records the new digests, refuses while a root is locked, and
     refuses if run from a frozen snapshot. (Tested on a temp root.)
   * `certification_label()` returns
     `CERTIFIED (panel) — NOT SUBMISSION-READY` when the panel is certified
     but the package is not; the final readme no longer calls that directory
     "the certified champion corpus".
   * `postcheck_revise()` warns when fixed findings have no
     `work/REREAD_<id>.md` note (the whole-paragraph re-read).
   * Venue profiles: `figure_text` (Nature 5 pt, Frontiers 8 pt) and
     `image_dpi` (Nature 450, Frontiers 300) are validated, carried into
     `format_policy`, and propagated to `min_image_dpi`.

3. **Venue profiles**
   * `venue_profiles/nature-biotechnology.json`: `figure_text.min_pt = 5`,
     `image_dpi.min_dpi = 450`, both with sources.
   * `venue_profiles/frontiers-in-immunology.json`: `figure_text.min_pt = 8`,
     `image_dpi.min_dpi = 300`, both with the guideline text.

### Repair (actual fixes, not just findings)

* `repair-layout` now widens the allele/compound columns and the neohet Table 3
  renders `HLA-A*02:01` and `MHC-anchor` on single lines (verified). The same
  repair is now part of the normal `fix` path (`fix_document` step 10b), so a
  package with an over-wide identifier column no longer makes `fix` reject its
  own output. The normal fixer also applies the duplicate-PAGE-field deletion to
  referenced header/footer parts (a floating text box still stays manual).
* `FMT-AV3` was narrowed to literal `shipped`/`deposited` claims after the first
  CNB run flagged "the R evaluation scripts remain in the repository for
  backward compatibility" — a description of the repository, not a material
  claim. The neohet "shipped per-candidate tables" rows still fire.
* `FMT-CN1` ignores count sentences with no metric ids; `FMT-IM5` excludes
  short-term (`Het`+`Mut`) OCR line-wrap artifacts; `FMT-SR1` labels only the
  Materials & experimental systems fields and requires the label to open the
  line; `FMT-ST1` uses a 2% relative tolerance for a rounded floor; the
  cross-surface scan is deduplicated. These were all precision fixes made after
  running the first version on the two winners.
* `sync-code` is the deliberate repair for the stale-module root; a new root
  records the manifest automatically.
* `certification_label` / readme repair the "CERTIFIED beside NOT READY"
  presentation.
* The remaining manuscript fixes (artwork re-export, supplement wording,
  Reporting Summary answers, Table S3 family, Zotero CSL) are **reported**
  by the new rules and belong to the revision/manual stage; the pipeline does
  not fabricate them.
* `sync-code` prints a note when the root carries a root-local
  `venue_profiles/` copy: the maintained profile's new `figure_text`/`image_dpi`
  blocks do not reach that copy unless the operator runs
  `set-venue <id> --profile ...` or recreates the root.

### Tests

* New: `.paper_test/test_round2_regressions_2026_1019.py` — 22 checks covering
  the claim pairs, logic rows, count row, Holm floor (PDF and LaTeX forms),
  Reporting Summary gap, Figure 1 split, Figure S1 no-false-positive, Table 3
  allele token, CNB figure text size, and the three-module manifest.
* Existing suites re-run and passing: `test_decide_antiregression.py`,
  `test_review_handoff_2026_1015.py`, `test_venue_config.py`,
  `test_attempt_history.py`, `test_docx_format_1_scan_fix.py` …
  `test_docx_format_4_pipeline.py`.

### What is still manual

The code can detect and, for table geometry, fix; it cannot invent artwork,
reporting-summary answers, a He readout mapping, a CALR register rule, a
Zotero CSL style or a data deposit. Those remain the author/revision items
listed in the audit report.

---

## E. Corrections to the first audit report

1. The ACT sentence is **82 words**, not 90 (C19).
2. The CNB supplementary S23–S30 are **274 ppi**, not 150 (C48); the text-size
   defect stands.
3. The neohet Fig. S1 `PRIME_BARank` and the manuscript-`FASTQ` items are
   **false positives** (C46, C47); the figure's `FastQ` spelling is kept as a
   minor finding with the corrected rationale.
4. The PKG-3 `neoheterocliticAggregate.py` advisory and the "README rule was
   ignored" note are **stale-snapshot artifacts**; current code suppresses
   both (C44, C45).
5. The neohet dpi/text items are **confirmed defects under the Frontiers
   guideline source**, not production advisories (N11, N12); the report's
   section 2.9 has been corrected.
6. The CNB "data availability source data" row is a **caveat**, not a hard
   contradiction (C6).

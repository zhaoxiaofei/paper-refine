# Round-2 audit — the two winners, and the code revisions that would close them

Date: 2026-10-19. Workspace: `/home/zhaoxiaofei/paper-refine` (HEAD
`3260755`, "Add layout-integrity scans, submission-surface scoping and revise
preflight parity").

Packages audited:

* **CNB** — `/home/zhaoxiaofei/manuscript-postgrad-data/cnb-to34-1019-0025-a755adf/round2_winner/`
  (champion `a2`, token `fe8409b`; main text, cover letter, supplement PDF,
  Reporting Summary PDF);
* **NeoHeteroclitic** — `/home/zhaoxiaofei/manuscript-postgrad-data/neohet-to17-1029-0029-a755adf/round2_winner/`
  (champion `a2`, token `d70ec1b`; main text, supplement, cover letter,
  `figures/*.png`, `code/`).

Method: `pandoc` docx→markdown; direct OOXML inspection with `zipfile`/`lxml`;
LibreOffice 7.3 render to PDF and page images; `pdftotext -layout`;
`pdfimages -list`; `tesseract` on figure rasters; execution of the shipped
`code/` scripts against `raw_data/hpep-v07.zip`; the frozen finding lists,
audit dispositions and revision ledgers; and the workspace's own
`paper_docx_format.py` scanner run on both packages.

---

## Executive summary

Two facts dominate this round.

**1. Both round-2 winners were produced by a pipeline snapshot that predates the
current workspace code.** The roots were set up on 2026-10-18 at ~17:02 UTC
(the `setup` log) and froze:

| file | root copy sha256 | workspace sha256 | new rules in root? |
|---|---|---|---|
| `paper_pipeline.py` | `06047562…` | `5ed1ec3f…` | no |
| `paper_docx_format.py` | `48171b65…` | `ee76ee34…` | no |

The workspace copy contains `FMT-AV3` (availability claims), `FMT-IM5`
(figure-label OCR), `FMT-TB5` (identifier/column width) and `FMT-T6h`
(bibliography bold runs). The root copies contain **none** of those rule
identifiers (`grep -c` = 0 for all four). The round-2 reviews and revisions
therefore could not have applied them. Every run in both roots — review, probe,
audit, revise, judge, decide — executed the old snapshot. This is why the
packages "still have issues": the fixes were never in the code that produced
them.

**2. Both winners are labelled `CERTIFIED` while their own status files say
`NOT READY`.** The CNB readme lists 34 open items handed to the author and 81
package-level findings; the NeoHeteroclitic readme lists 9 open items and 12
package-level findings. The first line of each readme still says
`**Certification: CERTIFIED.**`, and the last paragraph calls the directory
"the certified champion corpus". The manuscript defects below are exactly the
open items and the reviewer-visible defects that survived.

The concrete submission defects are grouped in Parts 1 and 2; the code causes
and the revisions are in Parts 3 and 4. The single most important code change
is P0-1: make a root refuse to run (or sync) when the maintained tree's modules
differ from the frozen copies. Without that, no new rule can reach a run.

---

# Part 1 — CNB round-2 winner

Submitted set (per the package README's own glob):
`cnb-33-1-coverLetter-fe8409b.docx`,
`cnb-33-2-mainText-fe8409b.docx`,
`cnb-33-3-suppAll-fe8409b.pdf`,
`cnb-33-nr-reporting-summary-filled-fe8409b.pdf`.
The `.tex`/`.bib` sources, `raw_data/`, `supplementary_source_files/` and the
READMEs are not submitted; they are package evidence.

## 1.1 Major — the figures are below the venue's legibility floor

The main text's Figs. 2–5 are embedded rasters whose own labels are far below
the 5-pt minimum in Nature's figure guide. The prior independent measurement
was Fig. 2 ≈ 2.8 pt, Fig. 3 ≈ 3.2 pt, Fig. 4 ≈ 2.0 pt, Fig. 5 ≈ 2.8 pt at the
printed widths (5.906, 5.396, 5.370 and 5.708 in). The round-2 media are
**byte-identical** to round 1 (`sha256` of `image2.png` … `image5.png` unchanged),
so the measurement still applies. A reader sees axis labels and panel keys at
roughly one-third of body-text size.

The supplement is the same class, and visibly worse:

* Supplementary Figs. S1–S22: the 9 × 8 performance panels, printed at page
  width, have internal labels at roughly one-third the 10-pt caption height
  (prior measurement ≈ 3.0 pt);
* Supplementary Figs. S23–S30: the HG008 heatmaps are 1719 × 1728 JPEGs at
  ≈ 274 ppi, with row labels that are unreadable at print size (≈ 2–3 pt);
* Supplementary Figs. S31–S36: the 34-row × 13-column heatmaps are ≈ 4.2 pt,
  and use a red–green accuracy scale that the Nature guide names as the
  example to avoid.

Rendered page 33 (S23) and page 11 (S1) were inspected: the caption is
comfortable, the figure's own text is not. This is a Major formatting defect
under the venue's recorded figure rule, and it is the largest single reason
the package is not submission-grade.

## 1.2 Major — the Reporting Summary contradicts the manuscript

The Reporting Summary is a submitted file. It was marked "read-only" by the
revision and shipped unchanged. Four contradictions and one missing answer are
visible:

| Location | Reporting Summary says | Manuscript says |
|---|---|---|
| Randomization (p3) | "no overlap between the data used for parameter selection and the data used for evaluation" | Methods: "the 85% threshold was selected empirically to match manual karyotyping on the cell-line datasets … because those cell-line datasets are themselves among the 41 evaluated, the threshold was selected on data that overlap the evaluation set, and no held-out rerun was performed" |
| Blinding (p3) | "no manual scoring or subjective assessment of group allocation" | Methods: the HG008 comparison is "a qualitative reading of the clusters"; Results: "This comparison is descriptive: no cluster-to-karyotype concordance statistic was computed" |
| Replication (p3) | "Cases in which a tool failed to run or returned no calls are reported in the deposited result tables rather than being omitted" | Methods: "SCYN produced no output on any ACT sample, CHISEL was excluded"; in the deposited Fig. 3 balloon table (`raw_data/source_data/Fig3_ploidy_balloons.tsv`, 1,815 rows) every row carries `failed=False` and there is no SCYN ACT row, so the no-output case is not encoded in that table |
| Data availability (p2) | "Processed benchmarking results and per-figure source data are available from the repositories" | Data availability: "the deposited pipelines regenerate the processed benchmarking results and the data figures (Figs. 2–5)" (a lower-confidence mismatch: the two can coexist if the repositories carry the source tables, but the package does not show that they do) |
| Eukaryotic cell lines (p3) | heading followed by no Yes/No/n-a answer at all, although the study analyses COLO-829, HCC1395, HeLa, HG008, MDA-MB-231 and other lines | Table S1 and Methods list the lines |

The first two are direct logical contradictions, not wording differences: the
threshold was tuned on evaluated data, and the HG008 comparison is a manual
visual reading. The third is contradicted by the package's own source table.
The cell-line item is an unanswered required field.

## 1.3 Major — Table S3's Holm correction is arithmetically impossible as captioned

Supplementary Table S3's caption says the p values are
"Holm–Bonferroni-adjusted within the single pooled family". The table has 19
rows. For the n = 9 rows, the smallest attainable two-sided Wilcoxon
signed-rank p is `2 / 2^9 = 0.00390625`; the smallest Holm-adjusted value in a
19-test family is therefore `19 × 0.00390625 = 0.0742`. The table prints
`p = 0.030` for those rows.

`0.030` is `8 × 0.00390625`; it is the 8-test floor, not the 19-test floor.
The smallest n = 21 p in the table (the Copynumber rows, `1.81 × 10^-5`) **is**
the 19-test floor (`19 × 2 / 2^21 = 1.81 × 10^-5`). The table therefore mixes
an 8-test family for n = 9 with a 19-test family for n = 21 while the caption
states one 19-test family. Either the caption is wrong or the n = 9 p values
are wrong; both are visible in the submitted PDF (p. 50).

This is a correctness defect, not a formatting one: a reader who checks the
caption against the arithmetic finds an impossible number.

## 1.4 Major — internal contradictions in Results and Methods

These survive from round 1; none was addressed by the round-2 revision. They
are quoted verbatim from the delivered main text.

1. **"negligible" vs the paper's own correction result.** Design principle:
   "oocyte meiotic products and sperm are haploid, and their residual
   aneuploidy and germline copy-number polymorphism (CNP) are negligible
   relative to the CNVs we introduce." Results, two pages later: "The
   correction described in Methods was metric- and caller-specific rather than
   uniformly slight: mean FLCNA integer-CN accuracy fell from 0.454 to 0.297
   and mean SeCNV breakpoint F1-score from 0.231 to 0.102, whereas mean
   AneuFinder breakpoint F1-score rose from 0.077 to 0.371 … that variability
   does not establish that residual aneuploidy is negligible." The design
   premise and the result are in direct tension.

2. **"near-invariance described above" has no antecedent.** Results: "The
   notable exception to the near-invariance described above is SeCNV." The
   preceding paragraph describes "metric- and caller-specific" variability,
   not near-invariance. The word `near-invariance` occurs once in the whole
   text.

3. **"invert the downsampling".** Design principle: "We can therefore
   downsample real sequencing data from such cells and then invert the
   downsampling to obtain data with approximately any CN profile as the known
   ground truth." The method downsamples and merges; it never inverts a
   downsampling. "Approximately any CN profile" is also an undefined
   quantifier.

4. **a test that asserts its own premise.** Methods: "It also tests whether the
   residual aneuploidy of a haploid cell is low, because aneuploidy is rare for
   germline-cell chromosomes … and CNP affects only 4.8–9.5% of the human
   genome." The `because` clause is the hypothesis the sentence says is being
   tested.

5. **an expectation offered as evidence.** Methods: "We therefore expected
   performance … to stay largely unchanged before and after applying this
   correction, which implies that the consistency check approximates a
   comparison against the haploid ground truth." An expectation cannot imply a
   result.

6. **"flagged as inconsistent" by nothing.** Design principle: "A caller that
   performs well on haploid input but poorly on merged input will be flagged as
   inconsistent." The benchmark scores callers; no component "flags" them.

7. **circular haploid-truth sentence.** Results: "a caller's output on the
   haploid input effectively matches the CN ground truth, and the agreement of
   the two references supports this interpretation rather than replacing it."
   The output *is* the Hap_1 reference; "rather than replacing it" has no
   antecedent.

8. **"purity floor" is coined and never defined.** Results: "The same benchmark
   also exposed a purity floor." A floor is a threshold; the text describes a
   trend.

9. **the same three-move sentence remains.** Results: "Because the correction
   makes the strategy aware of CNPs and haploid aneuploidy, we expected
   stability, but that variability does not establish that residual aneuploidy
   is negligible." Claim → expectation → caveat in one sentence, and "that
   variability" points to the previous sentence.

10. **paragraph opener with no premise.** Results: "We therefore examined which
    metrics were associated with that balance." The preceding paragraph ends on
    Ginkgo's publication year; `therefore` has no premise.

## 1.5 Minor — reference list

* **Ref. 15 bolds the volume, article number and year.** Verified in OOXML:
  the run `11, 505441 (2020).` carries `<w:b/><w:bCs/>`; every other entry bolds
  the volume only. The live Zotero field produced it; it shipped.
* **Five page ranges use hyphen-minus** where the list uses en dashes:
  refs 10 (`2239-2254.e39`), 11 (`445-452.e6`), 21 (`541-553.e5`), 23
  (`6355-6369.e16`), 42 (`24-34.e10`).
* **Ref. 34 has no journal or volume** and a spaced hyphen used as a dash:
  "GitHub - jlaffy/infercna … (2019). https://github.com/jlaffy/infercna."
* **Five titles are title case** where the other entries are sentence case
  (refs 11, 21, 34, 40, 42).
* Ref. 14's "Nilsen, G. et al." is **correct** for a 12-author paper; the
  earlier "four-author" note is withdrawn.

## 1.6 Minor — figure and legend consistency

* **Fig. 2 legend counts six metrics but lists five.** "The six metrics are
  integer-CN accuracy (intCN_accuracy …), Pearson correlations of absolute
  (intCN_PCC) and relative (nonintCN_PCC) CN, the reference-genome fraction
  covered by the called profile (CN_genome_cov_frac), and the modal integer-CN
  fraction of normal cells (intCN_modal_frac)." That is five named metrics;
  `breakpoint_f1score` appears only in the next sentence as the parent of
  precision/recall.
* **Fig. 4 legend asserts the paper's conclusion.** "This pattern is consistent
  with Ginkgo's leading overall balance among the … callers." The panel is a
  heatmap; the sentence is the paper's conclusion, not a reading of the panel.
* **Fig. 4 legend admits missingness is indistinguishable from diploid.**
  "Cells with no called CN value are displayed at the color-scale center
  (CN = 2)." A reader cannot tell a missing call from a true CN = 2.
* **Fig. 5 legend uses three connectives for one enumeration.** "Panels show,
  from top to bottom, … Below them, the panels show … This is followed by …".
* **Fig. 3's status key differs from its caption.** The caption says "Red X, no
  output"; the artwork's own legend says "Missing". The marks themselves match
  the Methods (SCYN red X, CHISEL hatched), so the earlier "swapped marks" note
  is withdrawn; this is only a key-word inconsistency.

## 1.7 Minor — writing, length and section hygiene

The following survive from the round-1 audit and remain visible:

* 82-word ACT sentence with four nested parentheticals (Methods, "Ploidy
  estimation benchmark").
* 219-word Data availability paragraph mixing accessions, two repository URLs,
  the simulator's reverse-smoothing caveat and COSMIC licensing.
* "The procedure for benchmarking CNV calls … consists of the four steps
  detailed in the subsections below." (Workflow overview filler.)
* "This study has the following limitations. First, … Second, … Third, … Fourth,
  …" — the whole paragraph is 138 words; the first item runs to ~120 words,
  the second to 23.
* "CHISEL's haplotype-aware approach therefore has substantial potential
  utility that our benchmark was not designed to evaluate." (non sequitur and
  filler).
* "Numbat performed best among the callers that require BAM-format data, which
  it needs to compute B-allele frequency." (dangling `which`).
* "Our results also help to explain the disagreements among Song et al.,
  Schmid et al., and Chang et al." The paragraph now states Chang's position,
  but it states that Chang *agrees* with Song on Numbat; there is no
  three-way disagreement left to explain.
* "Unlike the assay for ATAC-seq or RNA sequencing (RNA-seq), scWGS is free of
  …" (non-parallel comparison; ATAC-seq is expanded here and never used again).
* "the ranking is qualitative and metric-dependent" (metric-dependent is
  undefined in the abstract).
* "We can therefore downsample … and then invert the downsampling …" (above).
* "A method that performs well on haploid input but poorly on merged input will
  be flagged …" (above).

Length status recorded by the pipeline: abstract 164 words against the venue's
150 (inside the pipeline's 165 cap); main text 3,740 words against 3,000
(inside the 3,750 margin); SI abstract 314 words. The pipeline reports these as
advisories, but the venue's own number is what the journal enforces. The final
readme itself says the package is "NOT submission-ready" partly because of
them.

## 1.8 The status contradiction

`final_clean_version.readme.md` says `**Certification: CERTIFIED.**` at the
top and, 30 lines later, `**Submission readiness: NOT READY -- 81 package-level
finding(s) …**`. The directory is then called "the certified champion corpus".
A reader cannot tell whether the package is signed off. This is a code
presentation defect (Part 3, P0-2), not a manuscript defect.

---

# Part 2 — NeoHeteroclitic round-2 winner

Submitted set: `neohetero-16-1-coverLetter-d70ec1b.docx`,
`neohetero-16-2-mainText-FrontiersTemplate-zotero-d70ec1b.docx`,
`neohetero-16-3-supplementaryMaterial-FrontiersTemplate-zotero-d70ec1b.docx`,
`figures/Figure1.png … FigureS3.png`. `code/`, `raw_data/`,
`human_review_feedback/` and the READMEs are package content, not submitted.

The revision is substantively much better than round 1: the AUPRC/Figure S3
work is reproducible (I ran both shipped scripts; every output, including
`figS3.png`, is byte-identical to the shipped copy), the code README is
honest about the Drost tables and the 26 binary tables, and the figure S3
y-limit is fixed. The remaining issues are concentrated and specific.

## 2.1 Major — "every parental antigen is a held-out antigen" contradicts the data-leakage audit

Methods, "Quantification and statistical analysis", last sentence:

> "No model was trained, fine-tuned, or otherwise fitted on the benchmark data,
> so all reported statistics are out-of-the-box performance and every parental
> antigen is, by construction, a held-out antigen."

Methods, "Data-leakage audit", last sentence:

> "The audit compared the variant sequences; the parental peptides themselves
> were not screened against the pooled data, and several of the parents are
> standard class-I ligands, so this argument is structural rather than a direct
> check of parent overlap."

The two sentences make opposite claims about the same object. "Held out" is a
property of the parents; the paper says the parents were not checked and
several are standard ligands likely to be in the training data. The correct
claim is the structural one (within-parent ranking shifts all variants
together), not "held-out". This is a Major correctness/consistency defect and a
reviewer will find it in one read of the two paragraphs.

## 2.2 Major — the supplement says the per-candidate tables were "shipped" while the Data Availability says they were not

Three submitted statements disagree:

* Data Availability (main text): "The curated per-candidate benchmark tables
  from which Figure 2 and Tables S1, S2 and S3 are computed are **not part of
  that repository**; they are available from the corresponding author."
* Supplement introduction: "Those tables are **not part of the resource
  repository** at the pinned commit; they can be obtained from the
  corresponding author."
* Supplement, Figure S3 legend: "Each curve is the mean … computed from the
  **shipped** per-candidate tables."
* Supplement, Table S2 note: "… computed per dataset from the **shipped**
  per-candidate tables …"

"Shipped" means the submission carries them; it does not. The submission
carries neither `raw_data/hpep-v07.zip` nor `code/`, so a reader who follows
"shipped" finds nothing. The code README's "shipped in
`raw_data/hpep-v07.zip`" is true of the package root but false of the
submission, and the supplement imported the wrong word.

## 2.3 Major — Figure 1's key terms are split across lines and one acronym is mis-set

`figures/Figure1.png` (submitted) still prints:

* `Hetero` / `clitic` on two lines in the purple inset;
* `Homo` / `clitic` on two lines in the red inset;
* `FastQ files` in the top-left workflow box.

The manuscript's own term is `heteroclitic` / `homoclitic`, and the standard
acronym is `FASTQ`. The figure is the place the paper explains these terms;
splitting them defeats the definition. The figure is 1269 × 1057 px and was
not changed in round 2 (same sha256 as round 1).

Note on the `FastQ` item: the review/audit said "main text/Table 1 use
`FASTQ`", but the delivered main text contains no `FASTQ` at all (searched the
DOCX XML; zero hits). The spelling is still nonstandard, but the parity
rationale in the ledger is false. That is a code precision issue (Part 3), not
a reason to keep the item as worded.

## 2.4 Major — Table 3's key columns break mid-token

The rendered Table 3 (pp. 32–33) prints:

```
Houghton    MHC-        TAA    HLA-    ...
et al., 2007 anchor            A*02:01
```

and the same for `TCR-/facing`. The DOCX table gives the MHC column 820 twips
(0.57 in) and the Modified-residue column 880 twips (0.61 in). `HLA-A*02:01`
at the table's 9-pt font needs ≈2,180 twips (11 characters × 9 pt × 0.55 em ×
20 twips/pt); the usable cell width after margins is ~604 twips. The column
width is intrinsic; Word will break at the hyphen just as LibreOffice does. The round-2 ledger
marked this fixed (`F-007`), but the grid/cell widths still cannot hold the
tokens. This is a Major formatting defect in a submitted table.

## 2.5 Major — the He et al. binary labels are not mapped to a readout

Results:

> "The continuous readouts of He et al. (19), tumor growth rate and
> tetramer-positive fraction, were thresholded into binary labels by that
> study, so datasets D20–D26 are scored with ROC-AUC."

Methods says He et al. measured both readouts. Neither the Results sentence,
the Methods, nor Table 3 says which readout produced `IsTrue` for each of
D20–D26. Table 3 has no `Readout` column. Two different ground truths are
therefore collapsed into one label without a mapping; a reader cannot tell
what D20–D26 measure. This is a Major completeness/correctness defect; the
revision recorded it as manual-required (N-2) and shipped it.

## 2.6 Minor — the CALR long-peptide candidate construction is not described

Methods says:

> "The CALR long-peptide datasets (D11 and D13) derive from the CALR parent
> sequence and were not scored through the WT1 window."

That rules out the WT1 window, but does not say how the 47-mer CALR parent's
registers were enumerated. Table 3 gives 6,192 candidates for D11 and 120 for
D13. A reader cannot reconstruct either count, and the source study's
construction is not cited. This is a methods completeness gap.

## 2.7 Minor — visible reference typo

Reference 23 prints:

> "Ogasawara M. Wilms' tumor 1 -targeting cancer vaccine …"

The space before the hyphen is in the live Zotero field result. It is a visible
typographical error in the submitted reference list.

## 2.8 Minor — "nine analog measurements" is ambiguous

Discussion:

> "Tangri et al. measured pMHC affinity by competitive binding assay but
> reported only nine analog measurements and did not measure binding
> stability …"

The benchmark's own Tangri datasets D15/D16 carry 118/117 candidates and
117/116 assayed analogs; a reader can read "reported only nine analog
measurements" as "Tangri assayed only nine analogs", which contradicts Table 3.
The intended meaning is presumably "reported binding affinities for nine of the
heteroclitic analogs". This is a clarity defect, not a data error.

## 2.9 Confirmed — the figures miss Frontiers' recorded resolution and 8-pt text rules

The earlier audit treated these as production advisories because the venue
profile's `figures` block carries only caption rules. That was too narrow: the
venue's own author-guideline source (recorded under the profile's `sources`)
states **"All images must have a resolution of 300 dpi at final size"** and
**"The smallest visible text should be no less than eight points in height when
viewed at actual size."** Measured at a 6.5-in print width:

* `figures/Figure1.png` is 1269 × 1057 px → **195 dpi** (below 300) and its
  own text is 7.0–7.6 pt (below 8);
* `FigureS2.png` is 1899 × 1086 → **292 dpi** (below 300) and its text is
  7.4–7.9 pt;
* `Figure2.png` 4.8 pt, `Figure3.png` 4.8–5.1 pt, `Figure4.png` 3.4–3.6 pt,
  `FigureS1.png` 5.7–6.9 pt, `FigureS3.png` 2.8–3.0 pt at 6.5 in.

These are formatting defects under the venue's stated rule, not advisories.
The submitted main text DOCX carries no embedded figures (only the legends;
figures are uploaded separately), which is consistent with the Frontiers
submission layout.

## 2.10 A false open item: Figure S1 already says `PRIME_BArank`

The revision ledger's `F-004` / manual item A-1 says `figures/FigureS1.png`
prints `PRIME_BARank`. The submitted PNG says `PRIME_BArank` — I cropped and
upscaled the axis label; it is correct. The finding is a false positive from
the review OCR, and the item still counts toward "NOT READY". This is a code
precision defect (Part 3), not a submission defect.

---

# Part 3 — Why the codebase missed these

## 3.1 The root executes a frozen snapshot, and nothing hard-stops origin drift

The roots' `state.json` records
`pipeline: {path: /home/zhaoxiaofei/paper-refine/paper_pipeline.py, sha256:
06047562…, version: 3.8.0}`. The root's `paper_pipeline.py` hashes to exactly
that value, so the root is internally consistent — but the workspace's
`paper_pipeline.py` now hashes to `5ed1ec3f…` and the workspace's
`paper_docx_format.py` to `ee76ee34…`, while the root's formatter is
`48171b65…`. The workspace HEAD commit is the one that added
`FMT-AV3/IM5/TB5/T6h`; the root copies have none of them. Both copies report
`VERSION = "3.8.0"`, so the version string cannot distinguish them; only the
digest can.

`root_pipeline_staleness()` and `pipeline_snapshot_note()` already detect
"the origin tree has changed since". They print a NOTE. `run` does not
refuse; the operator sees the note and the run proceeds on the old code. The
`refuse_foreign_pipeline()` guard compares the *running* script with the
*frozen* one, not the frozen one with the *maintained* one, so it does not
fire here. The root also records only `paper_pipeline.py`, not the formatter
or the redlines adapter, so a root can run a new driver with an old formatter
without any mismatch.

This is the primary code cause of this round: the new rules were written but
never executed in the run that produced the winners.

## 3.2 Revision is finding-scoped; nothing re-reads the paragraph or the paper

`LANGUAGE_PASS_RULE` and the revision prompt require "every edited sentence" to
be re-read, but the revision edits only the frozen findings. The W1–W23
writing defects were not frozen findings in round 2 (they came from an earlier
manual audit), so no revision session touched them. Even for edited sentences,
the check is sentence-local: "companion" fixes produced "accompanied chiefly
by" (W1) and added Chang's position without removing the "explain the
disagreements" claim (W2).

There is no pass that re-reads a whole paragraph after an edit, and no pass
that reads the paper as one argument and looks for contradictions between
paragraphs. The "negligible" vs "not negligible", "near-invariance" vs
"variability", and "held-out" vs "not screened" contradictions are all
cross-paragraph claims; no current check compares them.

## 3.3 Detection is single-surface; nothing reconciles the submitted documents

The review reads the main text and the supplement in separate sweeps. The
Reporting Summary is a separate PDF. The cover letter is a separate DOCX. The
figure rasters are separate files. The pipeline has M13 (Reporting Summary
consistency) and M29/M31 (legends/artwork), but they are review prompts, not a
deterministic reconciliation over all surfaces:

* the CNB Reporting Summary contradictions were found by the review (F-019/
  F-020/F-021) and then left manual-required; no gate stopped the package;
* the neohet supplement's "shipped" survived because `FMT-AV3` was not in the
  root's formatter and, even in the current formatter, runs on DOCX text but
  not on the CNB supplement PDF;
* the neohet `held-out` sentence survived because no pass compares the
  leakage-audit paragraph with the statistics paragraph;
* the neohet Table 3 readout gap survived because the table schema is not
  checked against the Methods' readout list.

## 3.4 The new rules are incomplete even in the workspace HEAD

Running the current workspace formatter on the two winners shows what it does
and does not catch:

| Rule | CNB winner | Neohet winner | Gap |
|---|---|---|---|
| `FMT-T6h` ref 15 bold | **fires**, but `fix: style-field, protected: True`; nothing flattens/normalizes the field result | — | no submission-copy bibliography normalizer |
| `FMT-AV3` "shipped" | not run on the supplement PDF | fires on the supplement DOCX (2 rows) | no PDF text scan; no cross-sentence resolution |
| `FMT-IM5` figure labels | — | **does not fire** on `Hetero/clitic` because `Heteroclitic` appears intact elsewhere in the same artwork | masking bug; no canonical acronym list; no legend-key check |
| `FMT-TB5` table tokens | — | **does not fire** on `HLA-A*02:01` / `MHC-anchor` (regex requires a digit) | token grammar too narrow; no render verification |
| `FMT-TB4` table grid | — | fires on Table 4; does not fire on Table 3 | width repair only moves cells that `FMT-TB5` flagged |
| Figure text size | no rule | no rule | `FMT-IM4` is dpi/aspect, not text pt; the 5-pt check is manual |
| Holm family arithmetic | no rule | no rule | M32 reviews the stats; no deterministic floor check |
| Cross-document claims | no rule | no rule | M13 is a prompt; no claim ledger |
| Whole-paragraph logic | J3 claim strength, sentence-local | J3 | no contradiction/logic rows |

Concrete code locations:

* `paper_docx_format.py:13053` `TABLE_IDENTIFIER_RE` —
  `^[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)*\d[A-Z0-9]*$`. It matches `D01M07AA0` but
  not `HLA-A*02:01`, `H2-K^b^`, `MHC-anchor` or `TCR-facing`.
* `paper_docx_format.py:13364` `figure_label_rows()` — the loop starts with
  `if term in text: continue`, so one intact occurrence of `Heteroclitic`
  suppresses the split-form check for the same term.
* `paper_docx_format.py:13429` `availability_claim_rows()` — skips a sentence
  containing "from the corresponding author"; that is right for a request
  route but it also skips a sentence that says "shipped … from the
  corresponding author", and it is only called on DOCX text.
* `paper_docx_format.py:13466` `reference_bold_rows()` — correctly flags
  ref 15, but sets `fix: style-field, protected: True`; no downstream
  `flatten/normalize` path exists in the final-publication flow.
* `paper_pipeline.py:14369` `scan_format_in_sources()` — iterates DOCX and
  text sources; no PDF path. The CNB supplement is a PDF.
* `paper_pipeline.py:43043` `decide_certification()` — `readiness` is a
  separate dict; `readiness_gate_problems()` only fires with
  `--require-ready`. The default `decide` publishes a `CERTIFIED` clean copy
  with 81/12 readiness findings.
* `paper_pipeline.py:48164` `OPEN_ITEM_STATUSES` — manual-required items are
  reported but never gate.
* `paper_pipeline.py:12229`/`12390` — `root_pipeline_staleness()` is a note;
  `refuse_foreign_pipeline()` compares running vs frozen, not frozen vs
  maintained.
* `paper_pipeline.py:43495` `declared_submission_set()` — the current parser
  **does** parse both README globs (I tested it: `declared=True`, 10 files for
  neohet, 4 for CNB). The round-2 runs used the old root copy, which did not;
  the final readme's "README rule was IGNORED" is an artifact of the stale
  snapshot.

## 3.5 OCR and finding verification are not reliable enough

Two round-2 items are false:

* `F-004` (Figure S1 `PRIME_BARank`) — the image says `PRIME_BArank`;
* `F-003`'s rationale (`FastQ` vs manuscript `FASTQ`) — the manuscript never
  uses `FASTQ`.

Both still count toward "NOT READY". At the same time, the real split labels
(`Hetero/clitic`) were found by the review, not by the formatter. The code
needs a verified-evidence step: re-OCR at high resolution, require the quoted
string to be present, and require a "manuscript term" to actually occur before
filing a parity defect.

---

# Part 4 — Code revisions

Each item names the file/function, the behavior to add, and an acceptance test
that can be run on the two round-2 winners (or on fixtures derived from them).

## P0 — make the code that runs the code the operator maintains

**P0-1. Record and enforce a three-module code manifest.**

* `paper_pipeline.py:12138` `pipeline_identity()`: add `docx_format_sha256`
  and `redlines_sha256`; write all three into `state["pipeline"]` at `setup`
  and on every `run`.
* `paper_pipeline.py:12229` `root_pipeline_staleness()`: return
  `maintained_differs` for the formatter and adapter too, not only the driver.
* `paper_pipeline.py:12390` `refuse_foreign_pipeline()`: refuse a
  state-changing command when `maintained_differs` is true and the operator
  did not pass `--accept-code-drift`; print the exact `sync-code` command.
* Add `paper_pipeline.py sync-code --root <root>`: copy the three modules from
  the maintained tree, record their sha256, write a `code_sync` record with
  the old/new digests, and refuse to copy if `state.json` says a run is in
  flight. This is the deliberate replacement the current docstring already
  describes.
* Acceptance: a root set up at 01:02 and driven after a 04:15 workspace commit
  must fail with "frozen formatter 48171… is not the maintained ee76…; run
  sync-code" instead of silently running the old rules.

**P0-2. Make readiness part of the verdict, or stop calling the package
certified.**

* `paper_pipeline.py:43043` `decide_certification()`: add `submission_ready`
  to the inputs; `certified` is true only when `submission_ready` is true.
* `paper_pipeline.py:48641` `readiness_gate_problems()`: default
  `require_ready=True` for `decide`; add `--allow-not-ready` as the explicit
  override.
* `paper_pipeline.py:48100`: change the readme line to
  `**Panel certification: CERTIFIED — submission readiness: NOT READY**`
  whenever both are true; never print `CERTIFIED` alone in that case.
* `paper_pipeline.py:47479` `publish_final_clean()`: pass `certified=False`
  when readiness is false; the copy may still be written (current design),
  but its `certified` flag and readme must say so.
* Acceptance: the current CNB package with 81 readiness findings must produce
  `certification.certified: false` and a readme that does not call it
  "the certified champion corpus".

## P1 — cross-document claim reconciliation (new check, J6/M37)

**P1-1. Build a claim ledger over every submitted document.**

New `paper_docx_format.py` function `claim_ledger_rows(paras, doc)` plus a
`paper_pipeline.py` reconciler:

* extract sentences matching a small set of claim families:
  * availability (`shipped`, `deposited`, `in the repository`, `available
    from the corresponding author`);
  * held-out/leakage (`held-out`, `not screened`, `no overlap`, `overlap`);
  * manual scoring (`no manual scoring`, `descriptive`, `visual reading`,
    `qualitative reading`);
  * thresholds (`selected on`, `tuned on`, `held fixed`, `no held-out rerun`);
  * counts and p-values (`n =`, `p =`, `family`, `Holm`);
* normalize each to `(subject, predicate, value, source_file)`; compare
  same-subject claims across documents and within a document;
* emit `J6-CONTRADICTION` rows for opposite values, with both quotes and both
  locations.

Add explicit rules for the cases in this round:

* `shipped` vs `not part of` / `not in the repository` / `from the
  corresponding author`;
* `held-out` vs `not screened` / `standard class-I ligands`;
* `no overlap` vs `overlap the evaluation set`;
* `no manual scoring` vs `descriptive visual reading` / `qualitative reading`;
* `negligible` vs `not negligible` / a large correction effect;
* `near-invariance` vs `variability` / `metric-specific`;
* `no held-out rerun` vs `no overlap`.

**P1-2. Run it over PDFs, not only DOCX.**

* `paper_pipeline.py:14369` `scan_format_in_sources()`: for every submitted
  `.pdf`, call the existing `_pdf_text()` (line 45690) and pass the paragraphs
  to `text_style_rows`, `availability_claim_rows`, `claim_strength_rows` and
  the new `claim_ledger_rows`.
* `paper_pipeline.py:45712` `non_submitted_reference_rows()`: same PDF text
  path for PKG-2.
* Acceptance: the CNB supplement's Table S3 caption and the Reporting Summary
  are in the scan; the neohet supplement's two "shipped" sentences produce
  `FMT-AV3` rows and a `J6` contradiction against Data Availability.

**P1-3. Re-scan the corpus after a claim fix.**

When a finding rewrites `shipped` → `available from the corresponding author`,
search every submitted file for the old lexeme and report leftovers. The
current revision fixed the supplement introduction but not the Fig. S3 legend
or Table S2 note; a corpus-wide re-search would have caught them.

## P1 — figure text size and artwork labels

**P1-4. Measure figure text size, not just dpi.**

Add `figure_text_size_rows(path, placed_width_in, policy)` to
`paper_docx_format.py`:

* for each submitted raster, get pixel width and the `wp:extent` width from
  the DOCX (or the figure's intended print width from the venue template);
* OCR with word boxes (`tesseract … tsv`); take the median glyph height in
  pixels; `pt = px / (px_width / placed_width_in) * 72`;
* compare with `policy["min_figure_text_pt"]` (Nature 5; Frontiers no number →
  advisory); emit a row with the measured pt, the required pt and the placed
  width;
* if tesseract is missing, emit the existing categorical-gap row (never a
  silent pass).

Acceptance: the CNB Figs. 2–5 measure 2.0–3.2 pt and produce four Major rows;
the SI pages measure ≈3–4 pt and produce rows for S1–S22 and S31–S36.

**P1-5. Auto-regenerate a figure from its vector source when one is present.**

The CNB package carries `raw_data/Fig2_scWGS_caller_grid.pdf`,
`raw_data/Fig3_ploidy_balloons.pdf`,
`raw_data/Fig4_HG008_ginkgo_heatmap.pdf`,
`raw_data/Fig5_scRNA_swarm_grid.pdf`, and the SI sources in
`supplementary_source_files/`. Add `figure_regenerate_from_source()`:

* rasterize the vector PDF at the exact printed width and 600 dpi; the text
  scales with the page, so 5 pt in the source becomes 5 pt at the printed
  width;
* replace the DOCX image part (`word/media/imageN.png`) and update
  `wp:extent`/`a:ext` only if the aspect ratio is preserved (the existing
  `FMT-IM1` check);
* re-run P1-4 and refuse the replacement if the measured text is still below
  the floor.

This is the only way to fix F-005–F-011 without asking the author to re-export
by hand; the sources are in the read-only evidence area, so the pipeline reads
them and writes only the submission image.

**P1-6. Fix `FMT-IM5`'s masking bug and add canonical terms.**

`paper_docx_format.py:13364`:

* compute `split_form(term, text)` and `case_variant(term, text)` **before**
  the `if term in text: continue`; an intact occurrence must not hide a split
  occurrence;
* for `case_variant`, do not skip when the exact term is present: a figure
  that prints both `FASTQ` and `FastQ` has a case inconsistency;
* seed a small canonical acronym list (`FASTQ`, `TCR`, `MHC`, `pMHC`, `ROC`,
  `AUPRC`, `HLA`, `H2`, `CN`, `CNV`) independent of the manuscript vocabulary;
* for each occurrence, use OCR word boxes to detect a line break between the
  two halves of a term (not just a space anywhere).

Acceptance: `figures/Figure1.png` produces a row for `Hetero/clitic`,
`Homo/clitic` and `FastQ`; `figures/FigureS1.png` produces **no** row (it says
`PRIME_BArank`).

**P1-7. Verify OCR findings before they enter the ledger.**

Add a `verify_figure_finding()` step used by the review/audit when a finding
quotes artwork text:

* re-OCR the crop at ≥300 dpi (or upscale ×3 with LANCZOS) and require the
  quoted string to appear (case-sensitive for identifiers);
* if the string is not found, the finding is `not_reproducible` and cannot be
  manual-required; it is dropped with the attempted crop recorded.

Acceptance: F-004 (`PRIME_BARank`) would be dropped; F-002 (`Hetero/clitic`)
would survive with a crop and a confidence.

**P1-8. Compare legend key words with the artwork key.**

Add `legend_key_rows(legend_text, ocr_text)`:

* extract the legend's key tokens (`Red X`, `no output`, `hatched`,
  `not applicable`, `Missing`);
* compare with the artwork's own legend OCR;
* flag a paraphrase (`no output` vs `Missing`) as a Minor consistency row.

Acceptance: CNB Fig. 3 produces the row; the marks themselves are not flagged.

## P1 — table layout for real identifiers

**P1-9. Extend the unbreakable-token grammar.**

`paper_docx_format.py:13053` `TABLE_IDENTIFIER_RE`:

* allele names: `HLA-[A-Z]\*?\d{2}:\d{2}`, `H2-[A-Za-z0-9^]+`, `H-2[A-Za-z0-9^]+`;
* accession-like tokens with `.`, `:`, `*`, `^`;
* hyphenated compound labels that should not break (`MHC-anchor`,
  `TCR-facing`, `whole-genome`, `single-cell`) — treat the hyphen as
  unbreakable for width purposes, or set `w:noBreakHyphen` in the cell;
* keep the existing dataset-ID pattern.

`table_layout_rows()`: apply the width test to the longest unbreakable token
in every column, not only tokens with a digit. `table_layout_fixes()`: after
moving width from the widest donor, verify the total table width is
unchanged and re-run; if no donor has enough slack, emit a `manual` row
suggesting landscape or a smaller font rather than a partial fix.

**P1-10. Verify the table render.**

After `repair-layout`, render the DOCX to PDF (LibreOffice, existing
`docx2pdf.sh`) and run `pdftotext -layout` over the table pages:

* flag a line ending in `-` followed by a short continuation (`HLA-` /
  `A*02:01`);
* flag a cell whose text is split across more lines than its column's width
  warrants;
* fail the repair if a previously wrapped identifier is still wrapped.

Acceptance: the neohet Table 3 MHC column widens from 820 to ≈1,500 twips and
the render prints `HLA-A*02:01` on one line; Table 4's grid mismatch is
already fixed by `FMT-TB4`.

## P1 — bibliography normalization for the submission copy

**P1-11. Add a guarded submission-copy normalizer.**

`paper_docx_format.py:13466` already detects ref 15. Add
`normalize_bibliography(xml, styles)` that runs only on the final submission
copy (after the pin, before the zip), not on the judged bytes:

* for each `Bibliography` paragraph, identify the volume token (the numeric
  run immediately before the page range) and bold only that run; strip
  `<w:b/>`/`<w:bCs/>` from every other run in the entry;
* replace hyphen-minus between digits in a page range with an en dash
  (`(\d)-(\d)` → `$1–$2`), without touching URLs, DOIs, accession IDs or
  hyphenated words;
* collapse a space before a hyphen in a title (`1 -targeting` → `1-targeting`);
* sentence-case a title only where the CSL style says so; do not change author
  names, journal names or acronyms;
* verify the visible text differs only at the intended spans; re-run
  `FMT-T6h`, `FMT-T6d`, `FMT-R1..R5`.

If fields must stay live, produce two artifacts: the pinned judged copy
(unchanged) and the submission copy (normalized, fields flattened), and say
which is which. The current `--unlink-zotero-fields` already has the split; it
needs the normalizer behind it.

Acceptance: ref 15's bold covers `11` only; refs 10/11/21/23/42 use en dashes;
ref 23 loses the space; ref 34 is flagged as an incomplete entry (manual).

## P1 — statistics arithmetic

**P1-12. Add a Holm-family floor check.**

New `paper_pipeline.py` `stats_table_rows(tex_or_docx_text)`:

* parse table rows and the caption's family statement;
* count the rows in the family (`m`);
* for each row with `n` and `p`, compute the minimum attainable two-sided
  Wilcoxon p (`2 / 2^n`, adjusted for ties if the table gives them) and the
  Holm floor `m * p_min`;
* flag `p < m * p_min - 1e-12` as "p below the stated family's floor";
* flag a caption that says "single pooled family" when the n groups use
  different floors;
* check totals: positives + negatives = total; the header counts match the
  rows.

Acceptance: CNB Table S3 produces the row
`n=9, p=0.030, m=19, floor=0.0742`; the n=21 rows pass. The fix is either an
8-test caption for the n=9 comparisons or recomputed p values.

## P2 — writing logic and undefined terms

**P2-1. Add `logic_rows()` to `paper_docx_format.py`.**

Deterministic patterns (each with the sentence and the paragraph):

* `tests? whether .* because` — a test whose `because` clause asserts the
  premise;
* `we (?:therefore )?expected? .* which implies` — an expectation used as
  evidence;
* `will be flagged` with no `flag` mechanism elsewhere in the Methods;
* `invert(?:ing|s|ed)? the downsampling` — the method's own verbs are
  downsample/merge, not invert;
* `approximately any` — undefined quantifier;
* paragraph starts with `We therefore` and the previous paragraph has no
  causal cue (`because`, `since`, `thus`, `so`, `as a result`);
* `The notable exception to the X described above` where `X` does not occur in
  the preceding N paragraphs (`near-invariance` is the case);
* `which it needs` with more than one preceding noun;
* `accompanied chiefly by` / `chiefly accompanied by` — adverb placement;
* `This study has the following limitations. First` — formulaic ordinal
  enumeration; also flag if the item lengths vary by >3×.

**P2-2. Add `undefined_term_rows()`.**

* a quoted/coined term (`purity floor`, `metric-dependent`) that is not
  defined by a following `is`/`refers to`/`we define` clause within the same
  paragraph or the glossary;
* a term in the abstract that never appears again (`metric-dependent`).

**P2-3. Add `long_sentence_rows()` / `long_paragraph_rows()`.**

* sentence > 60 words (the ACT sentence is 90);
* paragraph > 150 words outside Methods (the Data availability paragraph is
  219);
* report the section and the word count; fix = editorial.

**P2-4. Make the revision re-read the paragraph after every edit.**

In `paper_pipeline.py:31179` `postcheck_revise()`:

* require a `work/REREAD_<finding-id>.md` row for every edit, with the old and
  new paragraph, the adjacent paragraph, and a disposition of the claim
  ledger around the edit;
* run `logic_rows`, `undefined_term_rows` and `claim_ledger_rows` on the
  revised package; any new row in the edited paragraph is a stage failure.

This is the fix for the "mechanical substitution" class (W1/W2/W14) and for
the "changed one sentence, left the contradiction" class.

## P2 — legend and Reporting Summary checks

**P2-5. `legend_claim_rows()`.**

Flag evaluative/superlative language in a legend (`leading`, `best`,
`consistent with … leading`, `demonstrates`) unless the legend also names the
statistic that supports it. Flag a legend that asserts the paper's conclusion
from a descriptive panel. Acceptance: CNB Fig. 4.

**P2-6. `legend_enumeration_rows()`.**

One enumeration should use one connective. Flag a second
`Below them`/`This is followed by` after `from top to bottom`. Acceptance: CNB
Fig. 5.

**P2-7. `reporting_summary_rows()`.**

Use the existing `xfa-export`/`check-pdf` to parse the Reporting Summary's
Q/A pairs into `{question: answer}`:

* every required section has an answer (the CNB "Eukaryotic cell lines" field
  has none);
* compare answers to the manuscript's claim ledger:
  * Randomization: "no overlap" vs the Methods' overlap disclosure;
  * Blinding: "no manual scoring" vs the HG008 "descriptive visual reading";
  * Replication: "failed/no-output cases in the deposited tables" vs the
    source table's missing SCYN row;
  * Data availability: "source data in the repositories" vs "pipelines
    regenerate";
* emit `M13` rows with both quotes; make them gating.

## P2 — PKG-2 precision and scope

**P2-8. Accept a paragraph-level locator.**

`paper_pipeline.py:45712` `non_submitted_reference_rows()`:

* before flagging a bare filename, search the sentence **and the enclosing
  paragraph** for a URL, DOI, repository path, commit id or "available at";
* if one is present and the sentence does not claim the file ships, do not
  emit a PKG-2 row (it is a resolvable external reference);
* if the locator is only a commit id/repo name, emit an advisory rather than a
  finding, or require the auditor to drop with evidence.

This removes the neohet `neoheterocliticAggregate.py` false positive without
weakening the real case (a filename with no locator anywhere).

**P2-9. Scan PDFs and the supplement for PKG-2.**

Use the P1-2 PDF text path; the CNB supplement's `identify_normal_cell_subset.R`
and the neohet supplement's filenames must be checked against the submission
surface. If the repository carries them and the text gives a locator, they are
not dangling; if not, they are.

## P2 — figure/table checks in the review prompt

**P2-10. Add the missing classes to the M20/M31 checklist.**

The review prompts should name:

* figure text size in points (not just dpi);
* split labels and line-broken key terms;
* legend key words vs artwork key words;
* table cells that break an allele/identifier;
* missing-value encoding in a heatmap legend.

This is a prompt change, not just a code change: the reviewer should look for
these even when the code scan is silent.

## P3 — tests and fixtures

**P3-1. Freeze the two round-2 winners as fixtures.**

Add `tests/fixtures/round2/cnb/` and `tests/fixtures/round2/neohet/` (or
symlinks to the package paths) and tests that assert:

* `scan_format_in_sources` emits `FMT-T6h` on CNB ref 15;
* `scan_format_in_sources` emits `FMT-AV3` on the neohet supplement (2 rows);
* `figure_label_rows` emits the `Hetero/clitic` and `Homo/clitic` rows and no
  `PRIME_BARank` row;
* `table_layout_rows` emits `FMT-TB5` on `HLA-A*02:01`;
* `stats_table_rows` emits the Table S3 floor row;
* `claim_ledger_rows` emits the held-out and shipped contradictions;
* `declared_submission_set` parses both README globs (10 and 4 files);
* `root_pipeline_staleness` reports `maintained_differs` for the old roots.

**P3-2. Add a "known-good" test.**

After the fixes, the same fixtures should produce no finding-tier rows on a
re-generated package; the test asserts the number of open items is zero for a
package that was rebuilt from the current code and the manual fixes.

---

# Part 5 — What to do, in order

1. **Do not rerun `decide` on the current winners.** They were produced by the
   old code. Rebuild the roots from the current workspace HEAD (or run
   `sync-code` after P0-1), then rerun the round from the same `--source`.
   Until that happens, the new rules cannot appear in the packages.
2. **Land P0-1 and P0-2 first.** They are small, testable, and prevent a
   recurrence of "the fixes are in the workspace but not in the run".
3. **Land P1-1/P1-2 (claim ledger/PDF), P1-4/P1-6/P1-7 (figure text/labels),
   P1-9/P1-10 (table tokens/render), P1-12 (Holm floor).** These are the rules
   that map one-to-one to the Major defects in Parts 1–2.
4. **Land P1-11 (bibliography normalizer) and P2-1..P2-4 (writing logic and
   re-read).** These close the long tail that the author has been fixing by
   hand for several rounds.
5. **Apply the manual fixes that no code can supply** (the author-facing list):
   * CNB: re-export Figs. 2–5 and the SI figures at ≥5 pt (or let P1-5 do it
     from the source PDFs); fix the Reporting Summary answers; decide the
     Table S3 family; fix the Zotero CSL for refs 15 and 34; set the
     missing-value mask in Fig. 4;
   * NeoHeteroclitic: regenerate Figure 1 with `Heteroclitic`, `Homoclitic`,
     `FASTQ`; replace `shipped` with `available from the corresponding
     author` in the two supplement sentences; add the `Readout` column for
     D20–D26; add the CALR register sentence; fix ref 23's space; widen
     Table 3.
6. **Only then run `decide --require-ready`.** The current `decide` writes the
   clean copy unconditionally; P0-2 makes the verdict match the status.

---

# Appendix — evidence commands

```bash
# The two roots' frozen code vs the workspace
sha256sum /home/zhaoxiaofei/manuscript-postgrad-data/*/paper_pipeline.py \
          /home/zhaoxiaofei/paper-refine/paper_pipeline.py
sha256sum /home/zhaoxiaofei/manuscript-postgrad-data/*/paper_docx_format.py \
          /home/zhaoxiaofei/paper-refine/paper_docx_format.py
grep -c FMT-AV3 /home/zhaoxiaofei/manuscript-postgrad-data/*/paper_docx_format.py
grep -c FMT-AV3 /home/zhaoxiaofei/paper-refine/paper_docx_format.py

# Current formatter on the winners
python3 paper_docx_format.py scan <winner> --json /tmp/scan.json
python3 paper_docx_format.py repair-layout <neohet-main.docx> --out /tmp/fixed.docx

# Figure OCR / crop
tesseract <figure.png> stdout
# (the Figure S1 axis crop is in the audit transcript: it reads PRIME_BArank)

# Table 3 widths
python3 - <<'PY'
import zipfile
from lxml import etree
z=zipfile.ZipFile('<neohet-main.docx>')
root=etree.fromstring(z.read('word/document.xml'))
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
for t in root.findall('.//w:tbl',ns):
    g=t.find('w:tblGrid',ns)
    if g is not None:
        print([c.get('{%s}w'%ns['w']) for c in g.findall('w:gridCol',ns)])
PY

# Table S3 arithmetic
python3 - <<'PY'
# n=9, two-sided Wilcoxon signed-rank minimum
pmin9 = 2/2**9
print('n=9 p_min', pmin9, 'x19 =', 19*pmin9)   # 0.07421875
print('n=21 p_min x19 =', 19*2/2**21)          # 1.812e-05
PY
```

---

## Bottom line

The round-2 packages are not failing because the pipeline lacks a reviewer or a
revision pass. They are failing because the run executed a frozen 01:02
pipeline that predates the 04:15 workspace code, and because the code that did
run has three structural gaps: it does not reconcile submitted documents
against each other, it does not measure the reader-visible geometry of figures
and tables, and it does not treat its own open items as part of the verdict.
The P0 changes make the right code run and make the verdict honest; the P1
changes make the specific defect classes detectable; the P2 changes close the
long tail. The manual items in Part 5 are the residue that no code should
invent.

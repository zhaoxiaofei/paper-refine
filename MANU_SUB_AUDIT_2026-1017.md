# Manuscript-submission audit — 2026-10-17

Scope: the two delivered packages
`manuscript-postgrad-data/cnb-to34-1017-0148-47df4d7/` and
`manuscript-postgrad-data/neohet-to16-1017-0148-47df4d7/`; the Grok candidate
list in `audit_data/2026-1017-0900-manu-sub-audit/grok-build.txt`; and the
operator's three rules for this round (hand-off markers, evidence-area
references, placeholder files). Every candidate below was re-checked against
the package itself; the commands that reproduce each row are in §4.

Tiers and severities use the one ranking vocabulary (AGENTS.md rule 6):
correctness > preservation > completeness > consistency > writing > formatting,
and Fatal / Critical / Major / Minor.

## 1. CopyNumBench (`cnb-to34`, Nature Biotechnology)

| id | finding | tier / severity | status | evidence |
|---|---|---|---|---|
| C-1 | The SUBMITTED main text still carries the pipeline marker `[AUTHOR TO COMPLETE: versions of bedtools, Seurat, cellsnp-lite and UCSC liftOver]` | completeness / Major | **confirmed** | `cnb-34-2-mainText-773d9a6.docx`, Software paragraph (document.xml para 102); 1 marker in the file |
| C-2 | The deposited MCB statistics tables define one verdict two ways: 26 rows have a p-value and a 95% MCB interval that disagree under the caption's own rule (11 rows in the scWGS table, 15 in the scRNA table). Worst: AneuFinder, Hap_1, `nonintCN_PCC` — p = 0.115 with CI [−0.51, −0.02] ("entirely below 0 = significantly inferior") | consistency / Major | **confirmed** | `raw_data/bench-results-26-07-15-updated.plots.stats.mcb.tex:41`; the same class at line 55 (SCYN) and, in `raw_data/mcb.tex`, SCEVAN 2023 and inferCNA 2019 |
| C-3 | The Results paragraph calls the six listed metric IDs "the row labels of Fig. 2", but Fig. 2 draws **eight** row labels (it also draws `breakpoint_precision` and `breakpoint_recall`) and 15 scenario-by-metric blocks. The "14 of the 15 blocks" count is right; the metric list cannot produce it | consistency / Minor | **confirmed** | `raw_data/source_data/Fig2_scWGS_caller_grid.tsv`: 15 distinct (scenario, metric) pairs; `Fig2_caller_mcb.tsv`: 16 blocks (8 metrics × 2 scenarios); Fig. 2 image row labels |
| C-4 | The Discussion says CHISEL "did not perform well even when we supplied phased single-nucleotide polymorphisms (SNPs) as ground-truth haplotypes", while the Methods' Step 1 partitions germline variants **at random** into two haplotypes and true phasing is supplied only for HG008 | correctness / Major | **confirmed** | main text Discussion para 58 vs Methods Step 1 (para 80) and the HG008 Methods (para 94) |
| C-5 | Grok: "Figure 3d still plots the CHISEL runs the text says were removed" | — | **rejected as stated; corrected** | The ACT panel draws CHISEL as hatched "Not applicable" in every row (pixel-verified on `raw_data/Fig3_ploidy_balloons.pdf`; the docx embeds `raw_data/Fig3_ploidy_balloons.png` byte-identically). What IS true: the **deposited source table** keeps 15 CHISEL ACT rows with `failed = False` (BT20 92.69%, TN2 94.14%, TN4 27.85%) — a stale table that contradicts the figure, the Methods, and the MANIFEST's "the source data and the figures can never drift apart" |
| C-6 | The published copy keeps the Zotero bibliography as a live field (`ADDIN ZOTERO_BIBL … CSL_BIBLIOGRAPHY`) and 126 live citation fields | formatting / Minor | **confirmed, by design** | the pipeline's recorded policy leaves fields live and says so in `final_clean_version.readme.md`; flattening is an author step (`decide --unlink-zotero-fields`) |
| C-7 | The deposited **pooled** MCB table (Fig. 3 statistics) is computed on the 9 germline donors only, while its caption says "The first section pools every donor of the four panels (primary)" and the manuscript's own Supplementary Table S3 pools 21 units (9 donors + 12 ACT samples). Means differ materially: AneuFinder 69.37 vs 80.94, FLCNA 54.45 vs 34.58, SCCNV 52.11 vs 27.76, Ginkgo-uncapped 98.88 vs 87.17; the Hsu ranking follows its own subset | consistency / Major | **confirmed** | `raw_data/source_data/Fig3_ploidy_mcb_pooled.tsv` (`n_units = 9` on all 20 rows) vs `Fig3_ploidy_pooled_units.tsv` (21 rows for 16 method|cap groups); caption of `raw_data/bench-results-26-07-15-updated.ploidy-plots.pooled.stats.mcb.tex`; S3 in the supplementary PDF (n = 21). A complete-block restriction is a legitimate reason for n = 9, but then the caption and the mean column must say so and name the units — as deposited, two surfaces of one analysis describe different populations |
| C-8 | The required Reporting Summary's software list omits five tools the manuscript's Software paragraph names: bedtools, Seurat, cellsnp-lite, Eagle and UCSC liftOver (the four the main text still marks as missing versions, plus Eagle) | completeness / Minor | **confirmed** | summary PDF's "Software and code" section vs the main text's Software paragraph (both re-extracted; the summary names ~30 tools, none of these) |

Notes that are **not** defects: the read-length labels (TN6/TN7 at 36/152 bp),
the donor merge (9 germline donors + 12 ACT samples, n = 21), the 16% / 7% /
37% simulator wraparound numbers, and the pairwise test's n = 9 all match the
shipped tables. Supplementary Table S2 matches its deposited source table
row-for-row (64 rows, 0 value mismatches).

The delivered package was audited in both shapes that exist on disk: the
pipeline's own `final_clean_version_*.zip` (2026-10-17 03:53) and the
re-saved directory copy (08:20). Their main texts embed the **same** Figure 3
image (`word/media/image3.png` = `raw_data/Fig3_ploidy_balloons.png`,
md5 `15143a3045d2a3c1d2e2e131c3094578`), so C-5 applies to both.

Grok's "the reporting summary omits those tools as well": the Reporting
Summary PDF names none of the four tools, but its text carries no software
inventory field at all (0 hits for any of `bedtools`, `Seurat`, `cellsnp-lite`,
`liftOver`), so this is **not** counted as a separate defect — the missing
versions are the one gap already counted in C-1.

## 2. NeoHeteroclitic (`neohet-to16`, submitted to Nature Biotechnology)

| id | finding | tier / severity | status | evidence |
|---|---|---|---|---|
| N-1 | Grok: a seventh study (Zhou et al., p15E/KSPWFTTL) is dropped on a one-letter header and it "breaks the headline" | — | **rejected (corrected in this pass)** | The manuscript itself states the exclusion and its reason: "One further labeled series in the analysis archive, a single-mismatch series for the murine leukemia p15E antigen (Zhou et al., 21), is an earlier-format raw pipeline output of a seventh study. Its MixMHCpred affinity column is spelled MixMHCPred_aff, so it fails the twelve-column inclusion rule and was therefore not assembled into the curated benchmark." Table 3 lists the six studies / 30 datasets the paper uses; b9 is not one of them. The recomputation is right (three PWM outputs 0.444, the two Motif-Atlas outputs 0.694 on that antigen) but it describes a series the paper explicitly excludes, so the headline is not falsified. The *hazard* — a header near-miss silently dropping a table — remains worth a preventive scan (PKG-11) |
| N-2 | The Reporting Summary is the pipeline's scaffold — six `[AUTHOR TO COMPLETE: …]` markers, no filled Nature Portfolio form — and it matches the submission pattern, so it ships | completeness / Major | **confirmed** | `neohetero-17-4-reportingSummary-bbb4e84.docx`: 6 markers; the residual gate itself refuses the decision for them |
| N-3 | The cover letter (1 Oct 2026) says "Related manuscripts: none … not under consideration elsewhere", while the package carries the iScience decision `ISCIENCE-D-26-11070` of 29 Sep 2026 (reject/transfer with reviewer reports). The letter never mentions it | consistency / Major | **confirmed** | `neohetero-17-1-coverLetter-bbb4e84.docx:17`; `human_review_feedback/iScience_feedback_from_reviewers_and_editors.txt` |
| N-4 | The package is still a Frontiers TEMPLATE in its form (`FrontiersTemplate` in the main-text filename; Frontiers section style `Introduction` / `Materials and Methods` / `Results` / `Discussion`; Frontiers author–year reference style, e.g. "Buonaguro L, Tagliamonte M. … Frontiers in Immunology (2023) 14:1210044. doi: …") while it is addressed to Nature Biotechnology, which uses numbered references and a Methods section at the end | consistency / Major | **confirmed, with a correction** | filename + heading styles + reference style. Correction to Grok: the body carries no Frontiers conflict/editor boilerplate (0 hits for "Conflict of interest", "Edited by", "Reviewed by"); the 32 body "Frontiers" strings are all Zotero `container-title` metadata for cited papers |
| N-5 | Figure 3's legend states a −0.50 to 0.50 colour scale, but printed cells reach 0.622 and −0.603 (saturated colours) | formatting / Minor | **confirmed** | `figures/Figure3.png` (D27 `MixMHCpred_motif` 0.622***; D29 `Dist_conserv` −0.603***) |
| N-6 | Grok: "the educated-vs-naive SCC range is attributed to the wrong methods" | — | **rejected** | The Methods define the PWM family as MMP_aff, MMP_motif (MMP_loglike), MMA_motif, MMA_diff and PRIME_imm. On D27 those five cells read 0.527, 0.622, 0.527, 0.527, 0.605 → 0.527–0.622 exactly as the text says; on D28 0.208, 0.248, 0.219, 0.219, 0.168 → 0.168–0.248. `0.622` is MixMHCpred_motif (a PWM method), not MHCflurry; `0.168` is PRIME_imm, not netMHCpan_EL |
| N-7 | Grok: "the mean-row stars are the smallest p, not a test of the mean" | — | **not a defect (disclosed)** | the Figure 3 legend states exactly that ("In the bottom row the value is the mean of the column but the asterisks are the smallest p value in that column") |
| N-8 | The status layer contradicts itself: `certification.certified: false` for the six shipped markers, beside `readiness.submission_ready: true` with **zero** findings | consistency / Major | **confirmed (pipeline defect)** | `reports/decision.json` of the neohet root |
| N-9 | `code/README_RERUN.md` documents `raw_data/hpep-v07.zip` as its input | — | **rejected** | `raw_data/hpep-v07.zip` IS present (10,020,242 bytes); the unpacked `mnt/d/tmp/*.tsv` beside it are its loose copies. (Grok did not claim this; it is listed because this audit checked it.) |
| N-10 | The cover letter says "Independent T cell, immunization and tumor-control outcomes, and TCR clonotype responses, corroborate this result", while the manuscript's own D30 result is null: "no method is significantly positively correlated with heterocliticity: the five PWM metrics lie between −0.091 and 0.021, indistinguishable from chance" | consistency / Minor | **confirmed** | `neohetero-17-1-coverLetter-bbb4e84.docx` para 10 vs main text Discussion paragraph on NLVPMVATV (D30) |

## 3. What the repo now does about these classes

1. **`--with-author-to-complete` / `--without-author-to-complete`** (default
   `on`; `set-author-to-complete`, config key `author_to_complete`).
   `off` rewrites the rule in every prompt (all four master-prompt excerpts and
   the two end-of-prompt reminders that restated the opposite included), forbids
   the `[AUTHOR TO COMPLETE: …]` token in every written file, sends the missing
   item to `MANUAL_STEPS.md`, fails a stage attempt that ADDS a marker, makes a
   shipped marker a gating residual, and reports it in readiness as `AUTH-1`
   (blocking under `off`; under `on` an advisory hand-off, so readiness and
   certification can no longer contradict each other). The probe prompt now
   carries the rule too (it carried none).
2. **PKG-10: evidence-area references.** A submitted file may reference a file
   inside `raw_data/` (or a sibling area) only when it is (a) a figure/table
   whose content the submission carries — bytes embedded in a submitted document,
   or a display table the parent `.tex` typesets — or (b) a file a `.tex` file
   in the area's parent directory inputs, directly or through nested
   `\input`/`\include`/`\includegraphics`/`\includepdf`/`\addbibresource`/
   `\bibliography`/`\pgfplotstableread`/`\lstinputlisting`/`\subfile`/`\import`.
   The report (`non_submitted_reference_rows`, rows carry `area_rule: PKG-10`)
   and the mechanical sentence removal share the same exception set.
3. **Placeholder files are ignored.** `--placeholder-file` /
   `set-placeholder-file` / a `Placeholder files:` README line declare them; the
   detector also finds identical bytes under two different sample/dataset names
   (haplotype/variant-style inputs). They are listed in the evidence pack under
   "Placeholder files -- ignored", never usable as a producer; the real partner
   of a declared placeholder stays evidence. The M30 negative-claim seed now
   keeps **every** producer for a method token (up to six) and ranks them by the
   sentence's own context — the CHISEL "not evaluated on ACT" claim now points
   at `Fig3_ploidy_balloons.tsv` (whose `ACT` panel carries the rows) instead of
   only at the germline MCB table where the pairing looked like a false
   positive.
4. **PKG-11** (header near-miss), **PKG-12** (p/CI verdict conflict under the
   table caption's own rule, strong direction first) and **PKG-14** (undisclosed
   prior editorial decision) run on every produced package and published copy;
   their rows are seeded in the evidence pack and block the readiness verdict.
   M30's seed description now also tells the session how to verify an
   "N scenario-by-metric blocks" count and to check the metric IDs against the
   figure's own row labels.
5. **Second pass, same day — two more preventive scans** (from the findings
   above):
   * **PKG-15**: a `*mcb*pooled*.tsv` whose `n_units`/`mean` do not match the
     sibling `*units*.tsv` (per-method unit count and mean), with the table's own
     caption quoted in the row. It reports the 15 method|cap rows of C-7 and
     leaves per-panel tables alone (they legitimately test their own units).
     The row names the complete-block restriction as the legitimate explanation
     when that is what happened — the defect is the unstated population, not the
     test.
   * **PKG-16** (advisory): the required form's software inventory vs the tools
     the manuscript's `Software.` paragraph names. It reports the five omissions
     of C-8 and stays silent when the manuscript has no software paragraph (the
     NeoHeteroclitic main text keeps its software in Table 1, so the check does
     not fire there).
   Both are seeded in the evidence pack under the package self-consistency
   section; PKG-15 blocks readiness, PKG-16 is advisory because its tool
   extraction is a heuristic.

## 4. Reproduce

```bash
# C-2 / N-1 / N-3 / C-3 (read-only scans over the delivered packages)
python3 - <<'PY'
import paper_pipeline as P
from pathlib import Path
cnb = Path(".../cnb-to34-1017-0148-47df4d7/final_clean_version_cnb-to34-1017-0148-47df4d7")
neo = Path(".../neohet-to16-1017-0148-47df4d7/final_clean_version_neohet-to16-1017-0148-47df4d7")
print(len(P.scan_mcb_rule_conflicts(cnb)), [r["line"] for r in P.scan_mcb_rule_conflicts(cnb)])
print(P.scan_column_name_near_misses(neo))
print(P.scan_prior_submission_disclosure(neo))
print([(r["reference"], r["detail"][:80]) for r in P.scan_pooled_table_mismatches(cnb)][:3])
print([r["reference"] for r in P.scan_form_software_coverage(cnb)])
PY

# N-1: the dropped antigen, recomputed from its own table
cd .../final_clean_version_neohet-to16-1017-0148-47df4d7
python3 -c "import csv;r=list(csv.DictReader(open('raw_data/mnt/d/tmp/hpep-v07.b9.p15E.H-2-Kb.KSPWFTTL-position-3.tsv'),delimiter='\t'));print(len(r),'rows; column has MixMHCPred_aff:', 'MixMHCPred_aff' in r[0])"
grep -c KSPWFTTL code/auprc_out/auprc_per_table.csv   # 0

# C-5: the ACT panel, pixel-checked (CHISEL is hatched = not applicable)
pdftoppm -r 300 -png -f 1 -l 1 raw_data/Fig3_ploidy_balloons.pdf /tmp/fig3 && \
  convert /tmp/fig3-1.png -crop 1285x620+1285+1900 +repage /tmp/act.png
md5sum raw_data/Fig3_ploidy_balloons.png   # equals word/media/image3.png in the main text

# the new regression suite (the three rules + the three scans)
python3 .paper_test/test_manu_sub_audit_2026_1017.py
```

## 5. Left to the author (not safely automatable)

* C-2: choose which of the two significance columns decides the MCB table's
  verdict (or drop the equivalence sentence from the caption) and regenerate it.
* C-4: scope the Discussion sentence to HG008 (the only setting with phased
  variants) or say which setting supplied them.
* C-3: correct the "six metrics … row labels of Fig. 2" sentence to the eight
  labels (or to the six metrics including their two breakpoint components).
* C-5: mark the 15 CHISEL ACT rows in `Fig3_ploidy_balloons.tsv` as not
  evaluable (or remove them), so the deposited table stops contradicting the
  figure and the MANIFEST.
* N-1: rename the b9 header (or make the aggregation accept both spellings and
  report skipped inputs), then regenerate the AUPRC outputs, Table S2 and the
  headline sentence.
* N-2/N-4: fill the journal's current Reporting Summary; re-conform the
  manuscript to the Nature Biotechnology template (a `conform` run is the
  pipeline route).
* N-3: disclose the iScience decision in the cover letter (or scope the
  statement so it stays true).
* N-5: extend Figure 3's colour scale to cover the printed cells.
* C-7: state in the pooled MCB table's caption (and in a labelled mean column)
  that its primary section is the complete-block subset of 9 germline donors, or
  recompute it over the 21 pooled units; make S3 and the MCB table agree.
* C-8: add bedtools, Seurat, cellsnp-lite, Eagle and UCSC liftOver to the
  Reporting Summary's software list (with versions), or say in the manuscript
  that they did not contribute to the reported results.
* N-10: scope the cover letter's corroboration sentence so it does not claim
  the D30 (null) TCR-clonotype result as corroboration.

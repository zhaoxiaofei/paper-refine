# Audit of the revised neohet submission — remaining issues and fixes
> **Validation update (2026-10-19).** Every finding below was re-checked in
> `VALIDATION_LEDGER_2026-1019.md`. Corrections: M5 (Table 3) is **refined** --
> the defect is a `w:tblGrid`/`w:tcW` disagreement (Word uses the cells,
> LibreOffice the grid), not a plain narrowing; W2 ("nine analog measurements")
> is **confirmed as an ambiguity, not an error** -- Tangri et al. measured the
> affinities of nine heteroclitic analogs; F4 (figure dpi) is **downgraded** to a
> production advisory because the venue profile records no dpi rule. The
> pipeline changes in Part 5 have since been implemented; see the ledger's
> Part D.



Date: 2026-10-19. Package audited:
`/home/zhaoxiaofei/manuscript-postgrad-data/neohet-to17-1029-0029-a755adf/runs/r1_a2_revise/revised/`
(the round-1 revise candidate `a2`; the root has no `final_clean_version_*` yet, round 2 is pending).

## 0. What ships, and what was examined

The package README states the submission contract: **only** names matching
`neohetero-*-<7hex>.(docx|pdf)` **or** `figures/*.png` are submitted. The submitted set is therefore:

| file | pages |
|---|---|
| `neohetero-16-2-mainText-FrontiersTemplate-zotero-823e0b4.docx` | 34 (LibreOffice) / 35 (Word, per `VISUAL_CHECK.md`) |
| `neohetero-16-3-supplementaryMaterial-FrontiersTemplate-zotero-823e0b4.docx` | 5 (LibreOffice) / 4 (Word, per `VISUAL_CHECK.md`) |
| `neohetero-16-1-coverLetter-823e0b4.docx` | 2 |
| `figures/Figure1.png`, `Figure2.png`, `Figure3.png`, `Figure4.png`, `FigureS1.png`, `FigureS2.png`, `FigureS3.png` | — |

Not submitted: `raw_data/` (including `hpep-v07.zip`), `code/`, `human_review_feedback/`,
`README*.md`, `MANUAL_STEPS.md`, `CHANGELOG.md`, `revision_report.json`, tracking copies.

Examined:

* docx → markdown/plain text for all three documents;
* direct OOXML inspection (section setup, table grids, footer parts, styles);
* LibreOffice render of all three documents (PDF, page images);
* the frozen findings (`runs/r1_review/review/findings.json`, 31 rows), the audit
  (`runs/r1_audit/audit/audit.json`, 45 dispositions, 3 `AU-*` additions) and the revision ledger
  (`revision_report.json`, 48 rows);
* the pinned repository content through the GitHub API (`zhaoxiaofei/neoguider` at `7ca84f7`);
* the submitted figures at native resolution.

The revision is substantively good: 29 fixes plus 2 fixed-with-caveat, 12 audit drops, 3 clarifications and 2 manual items.
Most findings were resolved correctly and the ledger is unusually honest. The issues below are what
the next read finds.

---

# Part 1 — Major issues

## M1. The central figures/tables cannot be regenerated from the deposit, and the supplement says they were "shipped"

**Location:** Data Availability Statement; supplement, Figure S3 legend and Table S2 note.

**Evidence.**

* Data Availability: *"The curated per-candidate benchmark tables from which Figure 2 and Tables S1,
  S2 and S3 are computed are not part of that repository; they are available from the corresponding
  author."*
* Supplement intro (correctly revised): *"Those tables are not part of the resource repository at
  the pinned commit; they can be obtained from the corresponding author."*
* Supplement, Figure S3 legend: *"… the per-dataset curve computed from the **shipped**
  per-candidate tables."*
* Supplement, Table S2 note: *"… computed per dataset from the **shipped** per-candidate tables …"*

**Why it is a defect.** (i) The two "shipped" sentences contradict the two "not part of the
repository" sentences in the same document; the F-006 fix was propagated to the intro but not to
the two later occurrences. (ii) More importantly, Figure 2 — the paper's central result — and
Tables S1–S3 cannot be reproduced by a reader: the pinned `hpep/` tree contains only the scripts,
`neoheterocliticAggregate_results.txt`, the audit and a FASTA (verified through the GitHub API);
the per-candidate tables exist only in `raw_data/hpep-v07.zip`, which the submission contract
excludes. (iii) The Drost (D27–D30) per-candidate tables are in neither the repository nor the zip,
so Figure 3 is not reproducible even from the package.

**Fix (manuscript).**
1. Prefer deposit: archive the per-candidate tables (binary and Drost) under a DOI (Zenodo/figshare)
   or in the pinned repo, and give one locator in the Data Availability Statement, Table 1 and the
   cover letter.
2. If deposit is impossible before submission, make all four statements agree:
   * Figure S3 legend → "computed from the per-candidate tables, which are available from the
     corresponding author (Data Availability Statement)";
   * Table S2 note → same;
   * Data Availability → add "The Drost per-candidate tables behind Figure 3 are likewise available
     from the corresponding author";
   * cover letter → add the Drost tables to the same sentence.
3. Correct `code/README_RERUN.md` (not submitted, but part of the package): "Every number is
   computed from the per-candidate tables shipped in `raw_data/hpep-v07.zip`" is false for the four
   Drost datasets; scope it to the 26 binary datasets.

**Pipeline fix.** Extend the PKG-2 availability scan (`strip_stage_non_shippable`, and
`local_path_link_rows` in `paper_docx_format.py`) from *paths* to *availability claims*: every
sentence containing `shipped|available at|deposited|in the repository` must resolve to a file on
the submission surface or to a URL/DOI, and a claim naming a package-only area (`raw_data/`,
`code/`) is a finding. On a fix that rewrites an availability claim, re-search the whole corpus for
the old claim's lexemes (this would have caught the two "shipped" leftovers).

## M2. "Every parental antigen is, by construction, a held-out antigen" contradicts the data-leakage audit

**Location:** Methods, "Quantification and statistical analysis", last paragraph.

**Evidence.**

> "No model was trained, fine-tuned, or otherwise fitted on the benchmark data, so all reported
> statistics are out-of-the-box performance and **every parental antigen is, by construction, a
> held-out antigen**."

The same Methods section, "Data-leakage audit", says:

> "The audit compared the variant sequences; **the parental peptides themselves were not screened
> against the pooled data**, and several of the parents are standard class-I ligands, so this
> argument is structural rather than a direct check of parent overlap."

**Why it is a defect.** The two sentences make opposite claims about the same object. "Held out" is
a property of the parents here, and the paper itself says the parents were not checked; several are
standard ligands likely to be in the training data. The audit's structural argument (within-parent
ranking, so parent exposure shifts all variants together) is the correct claim; "held-out" is not.

**Fix.** Replace the clause with:

> "… so all reported statistics are out-of-the-box performance. The variant sequences are
> effectively unseen (one overlap in 684,498; Data-leakage audit); the parental peptides themselves
> were not screened, and the within-parent ranking argument is why parental exposure would not by
> itself change the ordering."

**Pipeline fix.** `claim_strength_rows` (J3) already enumerates `under`/`over` directions; add a
same-document "contradiction" pass to the reviewer's J3 requirement: every universal or
"by construction" claim must be checked against the Limitations/audit section for a denial. A J3
claim-calibration pass over the Methods should have caught it; the auditor filed no `AU-` row here.

## M3. "The candidate set contains every peptide with a single mismatch" contradicts the binding filter

**Location:** Methods, "Generation and scoring of candidate heteroclitic variants", paragraph
before the algorithm.

**Evidence.**

> "NeoHeteroclitic therefore evaluates substitutions at every position, buried and TCR-facing
> alike, so that **the candidate set contains every peptide with a single mismatch** to the
> homoclitic peptide."

Step 4 of the same algorithm:

> "Predict the pMHC binding strength of x and of y … **If the predicted binding strength of y
> exceeds that of x, add y to R** …"

and the memory filter: *"candidates whose NetMHCpan-predicted IC50 exceeds 10,000 nM are
discarded."*

**Why it is a defect.** The candidate set contains every single-mismatch peptide *that is predicted
to bind more strongly than the parent* (and passes the memory filter), not every single-mismatch
peptide. The sentence also sets up the Discussion's "variants that improve TCR contact without
improving MHC binding are excluded by the binding filter itself" — which only makes sense if the
filter is as step 4 says, not as this sentence says.

**Fix.**
> "NeoHeteroclitic therefore evaluates substitutions at every position, buried and TCR-facing alike,
> so that **every single-mismatch peptide is scored and those predicted to bind more strongly than
> the parent are retained**."

**Pipeline fix.** A methods-claim check (M6/J2) that pairs a universal quantifier ("every…") with
the algorithm's own conditional in the same section; the reviewer must dispose the pair.

## M4. Step 4 does not state whether "exceeds" means under all ten scores or under any

**Location:** Methods, "Generation and scoring", step 4.

**Evidence.**

> "Predict the pMHC binding strength of x and of y under each of the ten antigen presentation
> scores in Table 2. **If the predicted binding strength of y exceeds that of x**, add y to R …"

**Why it is a defect.** "Under each of the ten" plus a singular "the predicted binding strength"
leaves three possible rules: all ten, at least one, or the default ranking score (MMP_aff). They
produce different candidate sets, and the paper's own default ("By default NeoHeteroclitic ranks
candidates by MMP_aff") does not say which score drives the filter. A reader cannot reimplement the
tool, and the Results' candidate counts depend on the rule.

**Fix.** State the rule exactly as the code implements it, e.g.:

> "… under all ten scores in Table 2. A candidate is retained if its predicted binding strength
> exceeds the parent's under **at least one** score (the deployed pipeline ranks with MMP_aff by
> default; the filter is independent of the ranking score)."

If the code requires all ten, write "under all ten". If it uses only MMP_aff, say so and drop "each
of the ten" from the filter sentence.

**Pipeline fix.** M6 "method/algorithm reproducibility": any conditional in an algorithm block
must name its quantifier and its default. Add to the review checklist and to `M6`'s enumeration.

## M5. Table 3's Dataset ID column breaks every identifier mid-token — a regression introduced by the revision

**Location:** Table 3 (main text, pp. 31–33).

**Evidence.** Rendered table:

```
Dataset ID
D08M18DB
1
D09M18CC
9
D10M18DC
1
D11M22ED
0
```

The base table had a first column of **1370 twips** and printed `D08M18DB1` on one line. The revised
table sets it to **1050 twips** (`w:tblGrid`: 1050, 900, 960, 840, 865, 1100, 2210, 840, 595) while
the cell text is 10 pt (`TableText` style, `w:sz=20`). Usable width is 1050 − 160 (cell margins) =
890 twips = 0.62 in; a 9-character identifier at 10 pt Times is ≈ 0.69 in, so every ID wraps.

This was introduced by edit set `X-911` ("Tables 1/3 were rebalanced so the filename column … fit
without a mid-token break"), whose ledger row claims the opposite of what the render shows.

**Fix.** Restore the first column to ≥ 1300 twips, taking the width from "Candidate peptides"
(2210 → 1960) or "Total" (595 → 545). Optionally set `<w:noWrap/>` on the ID cells. Re-render and
grep the PDF for a line ending in `D\d\dM\d\d[A-Z][A-Z]` followed by a lone digit.

**Pipeline fix.** New rule `FMT-TB4` in `paper_docx_format.table_conformance_rows`: for every table
cell, compute the longest unbreakable token's width from the cell font size and compare with the
column's usable width; a token that cannot fit is a finding (formatting, Major for identifier
columns). The current X-911 check only looked at total table width and column count.

## M6. Figure 1 still carries the three artwork label defects

**Location:** `figures/Figure1.png`, right-hand insets and workflow.

**Evidence (native resolution, not a rendering artifact):**

* the two pMHC insets print `Hetero` / `clitic` and `Homo` / `clitic` on two lines each;
* the workflow box prints `FastQ files` (not `FASTQ`);
* `APC` is unexpanded in the artwork (the legend now expands it, which mitigates this one).

**Why it is a defect.** The labels are visible in the submitted figure; X-910 was
`fixed-with-caveat` on the editable side only, so the submission still shows the typo. A reader
sees "Hetero clitic" as two words.

**Fix.** Regenerate the BioRender artwork with `Heteroclitic`, `Homoclitic`, `FASTQ`; keep the
legend's `An antigen-presenting cell (APC)` sentence. Do not edit the PNG text by hand.

**Pipeline fix.** `FMT-IM5` (new): OCR every submitted figure (`tesseract` is installed) and compare
its word tokens with the manuscript's glossary/term ledger; a token that differs from the text's
spelling (`Heteroclitic`, `FASTQ`, `PRIME_BArank`) is a finding. The current M31 check compares the
legend with the text, never the artwork's own labels.

## M7. Figure S1's axis label is still `PRIME_BARank` while the text says `PRIME_BArank`

**Location:** `figures/FigureS1.png`, x-axis; main text Methods/Results/Supplement legend.

**Evidence.** The axis reads `PRIME_BARank threshold for filtering peptides`; every text occurrence
is `PRIME_BArank` (lower-case r), including the figure's own legend sentence. Manual item A-1 is
still open.

**Why it is a defect.** The figure and the text use two spellings of one identifier; a reader
searching the text for the axis quantity will not find it. The text was aligned to the producer
(`hpep/neoheterocliticRealWorldPlot.py` prints `PRIME_BArank`), so the figure is the outlier.

**Fix.** Regenerate `FigureS1.png` with `PRIME_BArank`; keep everything else.

**Pipeline fix.** Same `FMT-IM5` as M6; also a generic `M31` sub-check: an identifier that appears
in both text and artwork must match exactly (case included).

---

# Part 2 — Writing and claim-calibration issues

## W1. "Opposite conclusion" and "does not contradict" in the same section

**Location:** Discussion, "Reconciliation with the earlier negative reports", first and last
paragraphs.

> "Two influential studies concluded that pMHC binding does not predict heterocliticity (19,31).
> Our benchmark reaches **the opposite conclusion** (Figures 2 and 3)."
>
> "… Our benchmark **does not contradict** these reports; it changes the unit of analysis."

**Fix.** Keep the reconciliation, drop the contradiction:

> "Two influential studies concluded that pMHC binding does not predict heterocliticity at
> TCR-facing positions (19,31). Our benchmark finds an association where those studies reported
> none; the difference is one of scope and unit of analysis."

## W2. "Reported only nine analog measurements" reads as a contradiction with Methods

**Location:** Discussion, "Reconciliation", second paragraph.

> "Tangri et al. measured pMHC affinity by competitive binding assay but **reported only nine analog
> measurements** and did not measure binding stability …"

Methods says Tangri *"varied every non-anchor position of two epitopes … (117 and 116 assayed
analogs, respectively)"*. A reader takes "nine analog measurements" as the whole study.

**Fix.** Qualify the assay: *"reported pMHC affinities for only nine of the analogs it assayed"*.

## W3. "Some of these designs show clear clinical value" is not supported by the next sentence

**Location:** Introduction, paragraph beginning "Work to date has targeted non-personalized
antigens".

> "Some of these designs show **clear clinical value**. A heteroclitic variant of the WT1 antigen is
> a component of galinpepimut-S (23), **which has been tested** in a phase 2 trial in acute myeloid
> leukemia (24) and **is being evaluated** as maintenance therapy in the phase 3 REGAL trial (25)."

Being tested is not evidence of clinical value; the REGAL readout is not reported. This is a
Q1 overclaim.

**Fix.** *"Several of these designs have entered clinical testing."* (and, if desired, cite the
reported phase-2 result explicitly rather than the fact of testing).

## W4. The cover letter's replacement for F-001 is cryptic

**Location:** Cover letter, paragraph 4.

> "… every presentation-based method ranked TCR-facing variants above chance … **Those outcomes
> supply the benchmark's labels; the four TCR clonotype datasets, with no antigen in common,
> agree.**"

"Those outcomes" has no antecedent in the letter; "agree" has no stated object. The finding asked
for a reword that names the held-out datasets; the replacement is accurate but unreadable.

**Fix.**

> "The seven-antigen labels are themselves T-cell, immunization or tumor-control outcomes, so that
> analysis is not independent of them. The four Drost TCR-clonotype datasets share no antigen with
> those seven, and they agree."

## W5. "Per dataset, MMP_loglike reaches mean SCC 0.371" — per dataset vs mean

**Location:** Results, "Presentation-based methods also rank variants generated at TCR-facing
positions", Drost paragraph.

> "**Per dataset**, MMP_loglike reaches **mean** SCC 0.371, MMA_motif and MMA_diff 0.300, …"

It is the mean over the four datasets (Figure 3's Mean row), not a per-dataset value.

**Fix.** *"Across the four continuous datasets, MMP_loglike reaches a mean SCC of 0.371 …"*

## W6. The 240-word paragraph that carries four topics (and one stale p-value)

**Location:** Results, "Aggregation by antigen removes the mean advantage of the PWM methods, not
their consistency", first paragraph.

It covers (i) dataset-level vs antigen-level means, (ii) four paired tests, (iii) leave-one-out
resampling, (iv) allotype stratification and per-dataset variability. It also reports
`NetMHCpan affinity (p = 0.25)` where the deposited `neoheterocliticAggregate_results.txt` gives
`p 0.2344` (0.23). Every other paired value in the sentence matches the deposit (0.7656, 0.7109,
0.3766).

**Fix.** Split at the sentence boundaries into three paragraphs (paired tests; resampling;
stratification/per-dataset spread), and correct the one p-value to **0.23** (or regenerate it and
state the test).

## W7. "Five terms recur" but more than five are defined

**Location:** Introduction, paragraph beginning "That third option is the subject of this paper".

> "… and **five terms** recur throughout it."

The passage then defines residue / MHC-anchor residue / TCR-facing residue, heterocliticity, binding
motif (PWM), heteroclitic variant, enhanced mimotope, heteroclitic peptide, homoclitic, parental,
and TCR cross-reactivity. The count is not recoverable.

**Fix.** Either *"several terms recur"* or name exactly five: *"five terms recur throughout it:
residue, heterocliticity, binding motif, heteroclitic variant, and cross-reactivity."* Then do not
define the other synonyms as terms.

## W8. Abstract: "was the exception" has no stated contrast

> "Of the distance scores, the … BLOSUM62 substitution score carried no usable signal and ranked
> below chance over the 26 binary datasets. The conservation score of Tangri et al. (Dist_conserv),
> the one distance score designed around heteroclitic peptides, **was the exception**."

**Fix.** *"… was the exception: it ranked above chance over the seven TCR-facing antigens (0.716,
p = 0.008), although its advantage over the 26 binary datasets was small (0.556)."*

## W9. Two mechanistic overclaims

1. Results, "Motif signal persists…": *"The small, position-specific preferences that anchor-centric
   reasoning would dismiss as noise therefore carry **usable signal about how a peptide will be seen
   by T cells**."* The benchmark measures heteroclitic labels, not TCR recognition.
   **Fix:** *"… carry usable signal about which variants are heteroclitic."*
2. Discussion, "Translational implications": *"many neopeptides are predicted by presentation models
   to bind their MHC poorly and are therefore **unlikely ever to be seen by TCRs**."* Weak predicted
   binding does not imply never seen.
   **Fix:** *"… unlikely to be presented at levels that elicit a T-cell response."*

## W10. PRIME: "dominant input … doing the work" vs "we cannot separate"

**Location:** Discussion, "PRIME_imm bears on the choice of method".

> "PRIME takes the MixMHCpred score as its **dominant input, so its performance is consistent with
> the PWM component doing the work**." … "we **cannot separate** the contribution of PRIME's
> immunogenicity-specific features from that of its binding component."

**Fix.** *"PRIME takes the MixMHCpred score as one of its inputs, so its performance is consistent
with a PWM component; the data cannot separate that component from PRIME's immunogenicity-specific
features."*

## W11. "(Zhou et al., 21)" mixes author-year and numeric citation

**Location:** Methods, "Curation of variants generated by substituting MHC-anchor residues".

> "… a single-mismatch series for the murine leukemia p15E antigen **(Zhou et al., 21)** …"

Elsewhere the paper cites `(21)` / `(19)` numerically. "21" reads as a year.

**Fix.** `(21)`, or `Zhou et al. (21)` outside the parentheses.

## W12. "The result is not a restatement…" has no referent

**Location:** Results, "Motif signal persists where information content is lowest", first sentence.

**Fix.** *"This pattern is not a restatement of the anchor-position argument."*

---

# Part 3 — Formatting and production issues

## F1. Every even page prints two page numbers

**Location:** main text and supplement, footer.

The default footer part (`word/footer_venue_default.xml`) contains **two PAGE fields** in two
right-aligned paragraphs. The LibreOffice render shows two numbers on alternate pages — e.g. PDF
p. 30: `16` at the left and `30` at the right; p. 2: `2` and `2`; supplement p. 1: `2` and `1`. The
left value is stale on some pages (16 on page 30). Word may collapse the two fields to the same
value, but the duplicate field is still in the submitted file, and a converter that refreshes one
but not the other prints a wrong page number.

The base carries the same defect, so the revision did not introduce it — but it is in the submitted
documents and the visual check did not notice it.

**Fix.** Delete one of the two PAGE-field paragraphs from `footer_venue_default.xml` (keep the
right-aligned one) and remove the orphan `footer1/2/3.xml` parts from the package.

**Pipeline fix.** `FMT-S10` (new, `layout_consistency_rows`): count PAGE fields per referenced
footer part; >1 is a finding. Also compare the rendered footer of a sample of pages with the
expected single page number.

## F2. Table 3 continuation pages carry no "(continued)" marker

**Location:** main text pp. 31–33.

Table 3's header row repeats correctly, but the continuation pages have no `Table 3 (continued)`
line, so a reader landing on p. 32 cannot tell which table it is. Table 3 runs to three pages
(Table 1 to two, Table 2 to two), which the venue's "very large tables" sentence treats as
supplementary material; the auditor accepted the typesetting-stage reading, but the production risk
remains.

**Fix.** Add `Table 3 (continued)` to the repeated header on pp. 32–33 (and the same for Table 1).
If the editors object to the length, move Tables 1 and 3 to the supplement and update the call-outs.

## F3. Figure 4 has no panel labels for the four peptide lengths, and its y labels use a different allele spelling

**Location:** `figures/Figure4.png`.

The four panels per row are lengths 8, 9, 10 and 11, readable only from the number of x positions;
there is no `n = 8` / `n = 9` label. The y-axis labels are `A0201` and `B0702` while the row titles
are `HLA-A*02:01` and `HLA-B*07:02`. The figure is also dense: 5 rows × 4 panels at 2600 px.

**Fix.** Add `8`, `9`, `10`, `11` above the panels (or under the x axes), and either use the full
allele names on the y axis or drop the redundant y labels (the row titles already name them).
Increase the panel titles' size if the figure will be printed at column width.

## F4. Figure 1 and Figure S2 are below 300 dpi at full text width

| figure | native px | dpi at 180 mm | dpi at 85 mm |
|---|---|---|---|
| Figure 1 | 1269×1057 | **179** | 379 |
| Figure S2 | 1899×1086 | **268** | 567 |
| Figure 4 | 2600×3110 | 367 | 777 |
| Figure S1 | 2389×1497 | 337 | 714 |
| Figures 2, 3 | 6000 wide | 847 | 1794 |
| Figure S3 | 3300 wide | 466 | 986 |

The venue profile encodes no DPI rule, so the pipeline cannot gate it, but the submission delivers
two figures far below the other five. At column width they are fine; at full width Figure 1 is
visibly soft.

**Fix.** Export Figure 1 at ≥ 2600 px wide (or state that it prints at column width) and Figure S2 at
≥ 2200 px wide. Do not upsample a screenshot; re-export from BioRender.

**Pipeline fix.** `FMT-IM4` (new, `drawing_geometry_rows`): effective DPI = native pixel width /
declared print width, with the print width taken from the figure's placed extent (docx) or a
per-figure width table in the policy; report below 300 dpi.

## F5. Reference 23 still prints the stray space before the hyphen

**Location:** main text, reference 23.

> `Ogasawara M. Wilms' tumor 1 -targeting cancer vaccine …`

The Zotero library was corrected (item `8HDC3WNY`, version 5212), but the live bibliography field in
the submitted DOCX was not refreshed, so the delivered text still shows `1 -targeting`. Manual item
Z-1 is still open and the defect is visible in the submission.

**Fix.** In Word: Zotero → Refresh, then `python3 paper_docx_format.py zotero-check <main.docx>`
must print CLEAN. If a refresh cannot be done before submission, unlink the bibliography field and
edit the one run (the file is the submission, not the library).

## F6. "Document S1" is a Cell Press label in a Frontiers submission

**Location:** main text, "Supplementary Material".

> "Document S1. Figures S1, S2 and S3; Tables S1, S2 and S3."

The submitted supplement is `neohetero-16-3-supplementaryMaterial-…docx` and its own title is
`Supplementary Material`; Frontiers uses "Supplementary Figure S1"/"Supplementary Table S1", not
"Document S1". A reader/editor looking for "Document S1" will not find it.

**Fix.** *"Supplementary Material: Supplementary Figures S1–S3 and Supplementary Tables S1–S3."*

## F7. Two abbreviations in the abstract are unexpanded or imprecisely expanded

* `SD` is used in the abstract (*"across-antigen sample SD 0.077 versus 0.184"*) and expanded only
  in the Table 4 note. Add *"sample standard deviation (SD)"* at first use in the abstract, or move
  the expansion into the abstract.
* `BLOSUM62` is expanded as *"BLOcks SUbstitution Matrix 62"* in the abstract and the Abbreviations
  list. BLOSUM is the BLOcks SUbstitution Matrix; 62 is the identity threshold. Write
  *"BLOcks SUbstitution Matrix (BLOSUM) 62"* or use *"the BLOSUM62 substitution score"* without the
  pseudo-expansion.

---

# Part 4 — What the revision's own ledger says, and where it is inaccurate

These are not new findings; they are places where the ledger's claim is stronger than the delivered
package. They matter because the ledger is what the next round trusts.

| row | ledger says | delivered package |
|---|---|---|
| `X-911` | "Tables 1/3 were rebalanced so the filename column … fit without a mid-token break" | Table 3's ID column was narrowed from 1370 to 1050 twips and now breaks every ID (M5) |
| `F-006` | claim "propagated to Table 1, the SI and the cover letter" | two "shipped per-candidate tables" sentences remain in the SI (M1) |
| `X-910` | `fixed-with-caveat`, editable side aligned | Figure 1 still prints `Hetero/clitic`, `Homo/clitic`, `FastQ` (M6) |
| `X-901` | text aligned to `PRIME_BArank` | Figure S1 still prints `PRIME_BARank` (M7) |
| `F-031` | library corrected | DOCX field not refreshed; ref 23 still prints `1 -targeting` (F5) |

The pattern is consistent: **the editable side was fixed, the read-only side was recorded as a
manual item, and no check verified that the two sides agree in the delivered bytes.** The pipeline
treats "artwork regeneration" and "Zotero refresh" as legitimate `manual-required` outcomes; that is
acceptable under rule 2, but the submission then ships the inconsistency, and the ledger should say
so in the *package* row, not only in `MANUAL_STEPS.md`.

---

# Part 5 — Proposed pipeline changes (so the next round catches these)

| # | class | where | change |
|---|---|---|---|
| P1 | availability claims | `paper_pipeline.py` `strip_stage_non_shippable`, `paper_docx_format.py` `local_path_link_rows` | extract every `shipped/available at/deposited/in the repository` sentence; fail if it names a package-only area or a file outside the submission surface; after a fix, re-search the corpus for the old claim's key tokens |
| P2 | deposit coverage | `M33` availability sweep | for each Results figure/table, list the input files its caption/legend says it needs and check they are in the deposit named by the Data Availability statement; missing → finding (not a manual item unless the deposit is impossible) |
| P3 | internal contradiction | `claim_strength_rows` / J3 | a universal or "by construction" claim must be checked against the Limitations/audit section of the same document; a denial there is a finding |
| P4 | method quantifier | `M6` | an algorithm conditional must name its quantifier (all/any/default) and the default score; unstated → finding |
| P5 | table token wrap | new `FMT-TB4` in `paper_docx_format.table_conformance_rows` | longest unbreakable token width vs column usable width at the cell font size; identifier columns Major |
| P6 | duplicate page field | new `FMT-S10` in `layout_consistency_rows` | >1 PAGE field per referenced footer part → finding; compare a sample of rendered footers |
| P7 | figure label spelling | new `FMT-IM5` | OCR every submitted PNG (`tesseract`); compare word tokens with the term ledger/glossary; mismatch (`PRIME_BARank`, `FastQ`, `Hetero/clitic`) → finding |
| P8 | figure resolution | new `FMT-IM4` | effective DPI at declared print width; <300 dpi → finding |
| P9 | supplemental label convention | venue profile `supplementary_label` | a profile that uses "Supplementary Figure/Table" flags "Document S1" |
| P10 | number provenance | `number_provenance_report` | when a Data Availability statement names a public results file, allow it as a proof source; check every printed number against it (the `p = 0.25` vs `0.2344` cell would be caught) |

The changes are deliberately narrow: P1, P3–P5 are text/structure checks; P5–P8 are OOXML/render
checks; none needs a new model call.

---

# Part 6 — Suggested order

1. **Before the next round:** M5 (Table 3 width), F5 (refresh bibliography), M6/M7 (figure labels),
   F1 (footer), M1 wording (or deposit).
2. **Next revise pass:** M2, M3, M4 (the three scientific-logic fixes), then W1–W12.
3. **Production:** F2–F4, F6, F7.
4. **Pipeline:** P5–P8 first (mechanical, testable on this package), then P1–P4, P10.

Acceptance for the manuscript-level fixes:

```bash
# Table 3: no identifier split across lines (a lone digit on the line after an ID stem)
pdftotext -layout revised.pdf - | grep -B1 -E '^ *[0-9] *$' | grep -E 'D[0-9]{2}M[0-9]{2}[A-Z]{2}$'   # must print nothing

# one page number per page: count footer tokens (y > 720 pt) on every page
python3 - <<'EOF'
import re, subprocess
pdf = "revised.pdf"
n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout).group(1))
for p in range(1, n + 1):
    out = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-bbox", pdf, "-"],
                         capture_output=True, text=True).stdout
    toks = [t for y, t in re.findall(r'<word[^>]*yMin="([\d.]+)"[^>]*>([^<]*)</word>', out)
            if float(y) > 720]
    if len(toks) != 1:
        print("page", p, "footer tokens:", toks)
EOF
# figure labels
tesseract figures/Figure1.png - | grep -E 'Heteroclitic|Homoclitic|FASTQ'
tesseract figures/FigureS1.png - | grep -E 'PRIME_BArank'
# references
python3 paper_docx_format.py zotero-check mainText.docx   # CLEAN
```

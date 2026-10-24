# How to revise paper-refine so the next run identifies AND addresses the CopyNumBench issues

> **Status 2026-10-11 (this round): the Zotero/automation half is IMPLEMENTED.**
> `paper_docx_format.py` now carries the offline refresh
> (`zotero_refresh_document` / `refresh_zotero_parts` / `refresh_zotero_package`,
> CLI `zotero-refresh`), reference-entry repairs from the package's own `.bib`
> (`repair_reference_entries`), the corrected XFA reader with `FMT-PDF4` and
> `xfa-export`, and `fix_package` runs all of it automatically (policy
> `refresh_zotero_fields`, default ON) before `unlink_zotero_fields`.
> Unlinking is NEVER a default and stays an explicit opt-in: the CLI
> `zotero-refresh FILE.docx --unlink` / `fix ... --unlink-zotero-fields`, and
> for the published copy `decide --unlink-zotero-fields` (or
> `format_policy.unlink_zotero_fields_at_publish: true`). When requested, the
> order is refresh → verify → unlink; a refusal is readiness finding `FMT-Z7`
> instead of a silent freeze. By default the published copy keeps refreshed,
> live fields because the author unlinks manually for the submission file.
> `paper_pipeline.py` records a `readiness` verdict and adds
> `decide --require-ready`; the status readme prints "Submission readiness".
> Skill/prompt/README/AGENT text updated, prompts re-synced; regression suite
> `.paper_test/test_zotero_auto_refresh_2026_1011.py` pins it. The remaining
> sections below are still the plan for the detection-side sweeps (M41–M46,
> profile `structure` block, evidence-area roles, table-direction checks, etc.).

Scope: this document answers two questions about `/home/zhaoxiaofei/paper-refine`
(orchestrator v3.7.0, commit `b39f02a`):

1. **Triage** — which of the issues reported by the three external reviews of the
   `final_clean_version` package (hash `23fcb60`, run `cnb-24to25-1011-0259-b39f02a`)
   are true, and which are false positives.
2. **Revision plan** — what to change in the review sweeps, the pipeline code, the venue
   profile, the revise skill and the decision/verdict layer so that these issue classes are
   *enumerated* (not merely noticed) and, where they cannot be fixed automatically, so that
   the package can no longer be labelled CERTIFIED and shipped as submission-ready.

Evidence base (all read-only): the shipped package and the run tree under
`/home/cnb-manuscript-postgrad-data/cnb-24to25-1011-0259-b39f02a/`, the two review rounds'
findings (`reports/round1_review_findings.csv`, `reports/round2_review_findings.csv`), the
winner's `MANUAL_STEPS.md`, and the three external reviews:
`CopyNumBench_Submission_Issues_Report.docx` (I-\*), `CopyNumBench_Submission_Audit_Report.docx`
(A/B/C/D/E-\*), plus the BUILD/EXPERT issue blocks. Facts were re-verified against the package
bytes (DOCX field XML, XFA data layer, TeX/BIB, TSV, PNG metadata, rendered PDFs) and against the
live Nature Biotechnology pages.

---

## 1. Executive summary

The pipeline's **detection** is substantially better than the shipped result suggests. Of the
major problem classes raised by the three reviews, the run had already filed (often twice):

| Class | Run finding(s) |
|---|---|
| Stale citation fields (COSMIC 27/28, hg19 37/38, 39,40 vs 4,41, orphan ref. 41) | r1/r2 **F-001…F-005** (M36, Major) |
| Malformed reference entries (ref 15, 25, 34, preprint style) | r1/r2 **F-009…F-013** (M10) |
| Reporting-summary form unreadable outside Adobe | r1 **F-016** (M13), r2 **F-022** (M20) |
| Availability not archived / two commits / "not yet deposited" | r1 **F-017…F-020**, r2 **F-015/F-016** (M33) |
| CHISEL/ACT stale source rows vs "could not be run" | r1 **F-025**, r2 **F-020** (M30, Major) |
| S3 `< 0.05` bold marks mathematically unreachable | **F-027/F-021** (M32, Major) |
| raw_data.README internal working material + author-facing note | **F-022/F-017** (M35, Major) |
| Reviewer-conflict asymmetry in the cover letter | **F-024/F-019** (M21) |
| Simulator artifact magnitude unnamed (0.4% vs 16–37%) | **X-001 → F-025** (M30) |
| Fig. 5 16-of-41 selection rule | **F-026** (M34) |
| Fig. 1 EMF panel f glyphs scrambled / no Fig. 1 source | **F-026/F-027** (M31/M30) |
| Abstract 164 words, main text 3,732–3,745 words (over base caps) | **F-007/F-008** (M19) |

What failed is everything after detection:

* **Certification semantics.** `decide` printed **CERTIFIED, exit 0** while the champion's
  `MANUAL_STEPS.md` held 13 open hand-off items (Zotero refresh, reference-item repairs, archive
  deposit, form flattening, Fig. 3 regeneration, S3 re-marking, Fig. 1 re-export …). Manual steps
  are deliberately "never a score, a gate or a reason to make a version ineligible"
  (`paper_pipeline.py`, `critical_remaining`/`manual_steps` handling, ~L30555).
* **Publish-time findings never gate.** `publish_final_clean` scans the shipped package for
  internal material (`PKG-1`) and PDF artifacts (`FMT-PDF1..3`) — `internal_artifact_rows`
  (`paper_pipeline.py:37974`), `package_pdf_rows` (`:38024`) — but the rows are only rendered into
  the sibling readme (`write_final_clean_readme`, `:38291`); they never enter
  `gate_problems`/`decide_certification` (`:37853`).
* **One publish-time check is broken and produced a false blocker.** `_xfa_dataset_report`
  (`paper_docx_format.py:8835`) reports the *filled* Reporting Summary as "UNFILLED" (details in
  §5.1). The round-2 review had already verified the opposite (`F-022`: "the incremental update's
  datasets object (257) IS filled … 48 non-empty answers").
* **Several classes were never enumerated at all** (see §4.2): reference-entry style parity between
  main list and SI bibliography, reference-number spacing, document-date coherence, table-direction
  vs text claims, shipped-but-unreported analyses, reporting-summary content vs manuscript, venue
  section/heading structure, author-owned-tool disclosure.

So the revision plan is roughly 40 % new detection, 60 % decision/verdict and fix-path work.

---

## 2. Triage of the reported issues

Legend — **T** true and material; **t** true but minor/already disclosed; **P** partly true or
  mis-scoped; **F** false positive; **U** unverifiable inside the corpus (external producer).
Columns: verdict · was it in the run's findings? · note.

### 2.1 Citations and reference list

| Issue (source) | Verdict | In run? | Verified fact |
|---|---|---|---|
| COSMIC prints 27 (SafeMut) in Step 2 and Methods/Datasets; ref 28 in Code availability (BUILD, I-04/05, A1/A2) | **T** | yes (F-002/F-003, M36 Major) | Field 28 (stored Tate/COSMIC) renders `27`; field 121 renders `28`; ref 27 = SafeMut (Zhao, Guo & Wang 2023). |
| "(hg19)37" points at SCEVAN; Zarrei is 38 (BUILD, A3) | **T** | yes (F-004) | Field stores Zarrei, renders `37`; the very next clause prints `38` for the same work. |
| "…data grow39,40" stores Queitsch (ref 4) + Erickson (ref 41), renders Schmid/Chang (A4) | **T** | yes (F-001) | The field's own JSON carries Queitsch 2023 + Erickson 2022; `formattedCitation` = `\super 39,40`. |
| Ref. 41 listed but never cited (I-06, A5) | **T** | yes (F-005) | No rendered marker `41` anywhere in the 124 fields; 45 distinct markers, 41 absent. |
| Ref. 15 malformed ("Front. Genet. Volume 11-2020, (2020)") while the SI bib has `11, 505441` (BUILD, A6, E-\*) | **T** | yes (F-009) | Main ref entry vs `cnb-25-3-suppAll-*.bib` `dong2020sccnv` (volume 11, pages 505441). |
| Ref. 25 no arXiv id while the SI bib has `arXiv:1303.3997` (BUILD, A7) | **T** | yes (F-010) | `li2013aligning` carries `eprint = {1303.3997}` in the .bib only. |
| Ref. 34 pasted GitHub page title, no year/version (BUILD, A8) | **T** | yes (F-011) | Entry text = "GitHub - jlaffy/infercna: …". |
| inferCNV cited as Patel 2014 and labelled "inferCNV 2014" in Fig. 5 (BUILD, EXPERT) | **T** | partly (F-012/13 cover preprints, not this) | Ref 35 = Patel glioblastoma paper; Fig. 5 column label "inferCNV 2014" (PNG). |
| Ref. 43 (Nurk CHM13) attached to "single-cell telomere-to-telomere co-sequencing" (BUILD) | **T** | no | Field 82 stores Nurk 2022; sentence is about prospective single-cell T2T co-sequencing. |
| Every main-text reference lacks a space after the number ("1.Chen") | **T** | no | All 46 entries render `N.Author`; FMT-R rules have no such row. |
| SI source comment says webpage/preprint formatting matches main-list "entries 33 and 24"; those are now Gao (CopyKAT) and Hou; the GitHub-only item is 34 (BUILD) | **T** | no | `cnb-25-3-suppAll-*.tex` comment ~L80; main entries 33/24 are not webpage/preprint. |
| Ref. 13 flagged "Preprint at …"; ref. 40 not (EXPERT) | **T** | yes (M10 F-012/F-013, logged for proof-stage) | 13 = `Preprint at https://doi.org/…`; 40 = `bioRxiv … doi:10.64898/…`. |
| Page-range dashes mixed (A10) | **t** | no | 16 en-dash vs 6 hyphen ranges in the reference list. |
| Intro cites Song et al. 2025 (a benchmark) for the "advent of co-sequencing" (I-13, C10) | **T** | no | Sentence cites `3,4`; ref 3 is Song (benchmark), ref 4 Queitsch; the co-sequencing protocols are refs 21–23. |

### 2.2 Results, statistics and benchmark claims

| Issue | Verdict | In run? | Verified fact |
|---|---|---|---|
| Table S2 rank-biserial results contradict the text: SCYN beats Ginkgo on `intCN_accuracy` (Hap_0, r=−1.00, p=0.031) and `intCN_modal_frac` (both Haps, r=−1.00); SeCNV flips on `intCN_PCC` (Hap_0 −1.00 → Hap_1 +1.00) but SCCNV flips the same way on `nonintCN_PCC`, unnamed; HMMcopy `CN_genome_cov_frac` −1.00 both; CHISEL `nonintCN_PCC` Hap_1 −0.91; SeCNV `breakpoint_precision` −0.87/−0.96 (BUILD) | **T** | partly (M32 has the rule; no sweep enumerated S2's directions) | All quoted rows verified in `cnb-25-9-suppFigsAndTables-*.tex` (~L240–302); caption says positive r = Ginkgo ahead. Text says integer-CN metrics drove Ginkgo's best balance and calls SeCNV "the notable exception". |
| Headline ranking qualitative with no aggregate statistic (B1) | **t** | partly (M32 rule; paper is explicit and hedged) | Abstract/Results/legend all say "qualitative"; per-metric tests exist. Referees will still ask (see §4). |
| HG008 validation descriptive, no concordance statistic; every caller cut at k=3 (BUILD, B2) | **T** | no (paper discloses; no row enumerated) | Methods: "cut at k = 3 … We did not compute a cluster-to-karyotype concordance statistic". |
| Simulator off-by-one bug disclosed in "Randomization" instead of Limitations, and quantified only as 0.4 % (BUILD, B3, I-11) | **T** | yes (X-001 → F-025) | Methods/Randomization paragraph carries the bug; the README quantifies 16 % of cells and 16/7/37 % of first-segment bases; no Limitations mention. |
| Six slices = CN 6 labels one biological copy unless an unstated depth renormalization exists (BUILD) | **U/P** | no | Text: "split each haplotype BAM into six disjoint slices … retaining all six corresponds to CN = 6" while diploid ground truth uses CN 2; the renormalization lives in deposited code outside the corpus. |
| SCYN's Gini cutoff 0.12→0.21 and `mapq20_thresh` 0.1 is the patched build that beats Ginkgo on two integer metrics (BUILD, B4) | **T** | no (disclosed in Methods; no row) | Methods/Step 3 states the patch; S2 shows SCYN ahead on those two metrics. |
| scRNA ground truth generated by Ginkgo, the declared winner (B5) | **T** | no | Methods/§Extension; the circularity is disclosed but not queried. |
| HUVEC-H9 (karyotypically normal) scores 88 % "tumor purity" at the 85 % threshold, disclosed only in the STable S1 caption (I-11, B7) | **T** | no | `dataset_summary.tsv`: HUVEC-H9 = 0.8806; caption caveat only. |
| S3: scAbsolute uncapped n=9 vs n=21 elsewhere ⇒ "every tool scored capped and uncapped on ACT" is not exact (BUILD) | **T** | yes (F-027/F-021, M32 Major, other half) | S3 rows: scAbsolute `none` n=9; `10` n=21; SCYN/CHISEL n=9. |
| S1–S22 captions say "606–1,989 paired cells"; Methods say n=9 per-donor tests (EXPERT) | **T** | yes (X-001 r2) | Caption L29 vs Methods statistics paragraph. |
| `raw_data/mcb.tex`: full Hsu MCB table (n=20, p, r, CI) while Methods says "no paired test, effect size, or confidence interval … is reported" (I-10) | **T** | no | mcb.tex present and unreferenced; the Methods sentence is in `Statistics and reproducibility`. |
| "Only Ginkgo recovers all three HG008 subpopulations" overstates the analysis (BUILD) | **T** | no | Fixed k=3 everywhere; third group is a different passage (MGH p31, 2/25 spreads) than the 34–36/68–70 split (NIST p18) — the text says so, but the headline does not carry it. |

### 2.3 Reporting summary

| Issue | Verdict | In run? | Verified fact |
|---|---|---|---|
| Form opens as "Please wait…" outside Adobe; needs a flattened, readable export (BUILD, EXPERT, I-01, A-\*) | **T** | yes (F-016, F-022) | `pdftotext` = 678 chars of placeholder; `pdfinfo Form: XFA`. |
| "The XFA dataset is empty / zero filled values" (I-01 as stated; FMT-PDF2) | **F** | no (it *is* the run's own false blocker) | Live dataset packet (object 257) is filled: author "Xuegong Zhang / Zhen Xie", lastupdate `2026-10-05`, 37+ non-empty answers incl. all free text. See §5.1. |
| Recruitment answer pasted twice | **T** | no | The same paragraph occurs twice inside the recruitment field. |
| Software versions run together (`AneuFinder 1.34.0,copynumber`, `FLCNA 89902690,SCYN`, `CaSpER 0.2.0,CONICSmat`) | **T** | no | Verbatim in the form's software answer. |
| bedtools, cellsnp-lite, Eagle, Seurat, Snakemake, liftOver used (Methods) but absent from the form's software list | **T** | no | 0 occurrences each in the XFA answers. |
| "No data were excluded" and "thresholds … were fixed before the final performance metrics were inspected" conflict with the SCYN patch, CHISEL/SCYN ACT failures and the Fig. 5 exclusions | **T** | partly (SCYN/CHISEL rows exist elsewhere) | Both sentences verbatim in the form; Fig. 5 legend excludes datasets. |
| Cell-line module answers never name HeLa/COLO-829/HCC1395/MDA-MB-231; ICLAC answer defers to the source papers | **T** | no | Form text: identifiers "as given in the source publications", "refer to the source publications for … ICLAC". |
| Form "last update" 2026-10-05 predates the final text (E1, C9) | **T** | no | Field = 2026-10-05; cover letter 8 Oct; availability check 11 Oct. |

### 2.4 Journal compliance, figures, files

| Issue | Verdict | In run? | Verified fact |
|---|---|---|---|
| Main text 3,680–3,745 words vs the journal's ≤3,000; abstract 164 vs ≤150 (BUILD, EXPERT) | **T** (severity is policy) | yes, reported **Minor** (F-007/F-008) because of the pipeline's own +10 %/+25 % margins | Pipeline counted 3,732 (r1) → 3,745 (r2); the profile's own notes say the margins are "this pipeline's own … not an NBT rule" while the live page says "up to 3,000/150". |
| Discussion has 5 subheadings; heading is "Methods", not "Online Methods" (EXPERT) | **T** | no | Verified against the live NBT Content-Types page: "… Discussion Online Methods. Results and online Methods should be divided by topical subheadings; the Discussion does not contain subheadings." |
| Fig. 1 only as 8.7 MB EMF inside the DOCX (BUILD, EXPERT, C6) | **T** | yes (F-026/F-027 M31/M30) | `word/media/image1.emf` = 8,748,256 B; no Fig. 1 artwork in `raw_data/`. |
| Main text "no line numbers" (EXPERT; C1 first half) | **F** | n/a | `<w:lnNumType w:countBy="1" w:restart="continuous"/>` present; the pipeline's own PDF render shows lines 1…N. |
| Track changes still on in `settings.xml` (EXPERT) | **F** | n/a | No `trackChanges`, no `<w:ins>`/`<w:del>` in any part of the DOCX. |
| 124–125 live Zotero fields make the Word file "not flat" (EXPERT) | **T** | yes (M36 domain) | 124 `ADDIN ZOTERO_ITEM` + 1 `ZOTERO_BIBL` field. |
| Fig. 4 PNG "below the 300 DPI minimum" (I-12) | **P/F** | no | pHYs = 5906 px/m (150 dpi metadata) but the placed size is 5.37 in ⇒ ≈320 ppi effective; the Audit Report's own C7 says "content is fine". Keep as a preflight/metadata item. |
| Fig. 5 subset (16 of 41) explained in legend but not Results (I-09) | **T** | yes (F-026 M34, Minor) | Legend states the count and the exclusions; Results never does. |
| Filenames carry the build hash; zip ships a 17 MB internal plot dump (`bench-results-…-plots-all.pdf`) (EXPERT) | **T** | partly (F-026 X-002; PKG-1 skips evidence areas by design) | `raw_data/bench-results-26-07-15-updated.plots-all.pdf` = 17,805,987 B; all filenames end `-23fcb60`. |
| `raw_data.README` talks to the authors ("The manuscript should be aware…") (BUILD, EXPERT) | **T** | yes (F-022/F-017 partly fixed) | The AI-chat URLs were removed; the author-facing sentence and TN6/TN7 note remain. |
| Six `raw_data/swarmHeatmap_*.pdf` missing so the SI cannot be recompiled (I-02) | **F** | n/a | All six present in the package and in the zip; the audit's own E3 records its download truncation. |
| Seven dormant .bib entries / only 26 of 33 printed (E2) | **F** | n/a | 33 defined, 33 cited (non-comment), 33 printed in the compiled SI. |
| Repos pinned at commits with untracked paths (EXPERT) | **U** | n/a | Not checkable from the corpus; the git snapshot ships but says nothing about untracked files. |

### 2.5 Cover letter, reviewers, competing interests, dates

| Issue | Verdict | In run? | Verified fact |
|---|---|---|---|
| 4 of 5 suggested reviewers conflict (Schatz = Ginkgo, Kharchenko = Numbat, Xie/Tang = haploid datasets) and the letter excludes CHISEL/FLCNA authors (BUILD, EXPERT, D1/D2, I-03) | **T** | yes (F-024/F-019, Minor) | Supp bib confirms Schatz (Garvin 2015) and Kharchenko (Gao 2023) authorship; letter discloses all four and requests the two exclusions. |
| Cover letter dated 8 Oct vs availability "checked 2026-10-11" (BUILD, EXPERT, C9, I-07) | **T** | no | Letter `October 8, 2026`; availability "(checked 2026-10-11)". |
| Letter does not mention generative AI while the manuscript does (BUILD) | **T** | no | No AI sentence in the letter; manuscript has a Generative-AI section. |
| Letter is stronger than the paper ("underperformed or could not be evaluated", "pointed to the same leading caller") (EXPERT, D3) | **T** | partly (F-029 J3 on the paper's own hedge; no letter-vs-paper row) | Requestable under M21's two-direction rule but not filed. |
| Competing-interests says none while SafeMut (ref 27) is co-authored by the first author, ref 45 is his Genetron-affiliated work, and the tool's repo cites patent CN115458051A (BUILD) | **T** (patent detail U) | no | Crossref: ref 27 first author = Xiaofei Zhao (same as the manuscript's first author); ref 45 affiliation "Genetron Health (Beijing) Co. Ltd". Patent not fetchable here. |

### 2.6 Data/code availability

| Issue | Verdict | In run? | Verified fact |
|---|---|---|---|
| Results and code "not yet deposited in a DOI-issuing archive (checked 2026-10-11)"; GitHub alone is not the final record (BUILD, EXPERT, C2) | **T** | yes (M33 F-017…F-020 / F-015/F-016) | Verbatim in Data and Code availability; the reporting summary does not mention it. |
| The two Data/Code statements now pin the same commits (an earlier round's defect) | fixed | F-017/F-018 r1 | Both statements pin `0b10533…` and `29e8a01…` in the shipped file. |

### 2.7 Already-correct items the reviews confirm

Reporting-summary data accessions, funding numbers, tool version inventory in Methods, seeds,
figure cross-references S1–S36 / Tables S1–S3, the generative-AI disclosure's substance, and the
commit pins matching the shipped git snapshot — verified consistent in the final package.

---

## 3. Gap analysis: why each class was missed or left open

Three gap types:

* **D — detection gap**: the class had no enumerating sweep (or no row of the right shape).
* **R — resolution gap**: a sweep filed it, but the fix path is manual and the pipeline neither
  completes it nor blocks on it.
* **V — verdict gap**: the pipeline's own decision layer overrode known blockers
  (certification, publish-time hygiene not gated, wrong severity policy).

| Class | Type | Today's coverage | What went wrong |
|---|---|---|---|
| Stale citation fields / orphan entry | R | M36 + FMT-Z1..Z4 (fired, Major, ×2 rounds) | Fix requires Word+Zotero refresh; the package shipped unchanged and was certified. |
| Ref-entry shape (15, 25, 34, preprint style, spacing, main-vs-SI parity) | D (+R) | FMT-R1..R5 (R1/R5 fired) | Missing: space-after-number, main-vs-SI divergence for the same work, software citation year/version, dash normalization. |
| Table-vs-text direction (S2) | D | M32 has a direction rule but no table-row enumeration | No sweep enumerates sign/p of each table row against the named claims. |
| Withheld analysis residue (mcb.tex) | D | none | No check reads `raw_data/` analysis artifacts as "should not exist / should be referenced". |
| CN scale coherence (six slices = CN 6) | D/U | M30 seeds numbers vs shipped tables; producer is external code | Row filed as `unable` at best; the text's internal scale statement is not checked for self-consistency. |
| Simulator artifact placement/magnitude | R | X-001/F-025 (Minor, ×2) | The README's own numbers (16/7/37 %) were not propagated into the Methods paragraph or Limitations; the class was left as an advisory. |
| SCYN patch / fairness | D | none | Disclosure exists in Methods; no sweep files "non-default tool configuration" as a finding with a mitigation requirement. |
| HG008/k=3/concourse | D | none | No sweep checks a headline claim against the analysis's own declared limitation. |
| Ground-truth circularity | D | none (J2 judgment) | No probe asks "is the ground truth produced by a ranked method?" |
| Reviewer conflicts | V | M21 (Minor) | Severity policy: authored a ranked/recommended tool → should be Major + asymmetry as one finding. |
| Reporting-summary content | D (+V) | M13/M20 (fired on readability only) | No row compares the form's answers with the manuscript (software list, exclusions/thresholds, module answers, dates) — and the XFA reading itself was wrong. |
| Form shell vs filled | V+D | FMT-PDF1 correct; FMT-PDF2 wrong | Publish-time rows don't gate; the parser misreads the current dataset. |
| Length policy | V | M19 fired Minor | Operator margins (±10/25 %) silently downgrade journal-base overages. |
| Discussion subheadings / "Online Methods" | D | Profile carries the sentence only as free text | No structure rule; no profile field to check against. |
| Fig. 1 EMF / Fig. 4 dpi metadata / figure deliverables | D (+R) | M31/M30 partial | No per-display-item artwork inventory with format/effective-resolution verdicts. |
| raw_data working material (README, plot dumps, mcb.tex) | D | PKG-1 explicitly skips evidence areas | No role declaration for evidence files; no "unreferenced analysis artifact" rule. |
| Dates / version coherence | D | none | Cover letter, availability checks, form dates, compiled PDFs, filename tokens never compared. |
| Line numbers / spacing | F | M20 policy ("1.5× preference") | Reviewer claims (line numbers) false; spacing is a stage-scoped preference, not an initial-submission blocker. |
| Track changes | F | M20 rule exists | Not present in the shipped file. |

---

## 4. Revision plan

### 4.0 Adopt the run's own discovery output first

The 2026-10-11 run already produced four sweeps proposals in
`reports/round1_review/new_sweeps.md` (M37 statistical reachability, M38 form-PDF content,
M39 figure-source coverage, M40 cross-draft residue) and `adopt-sweep` exists to accept them.
Adopt M37/M39/M40 with light edits and **rewrite M38** per §4.2 before adopting (its premise —
"a filled reporting summary with an empty XFA data packet" — was itself produced by the parser
bug; the sweep is right, the trigger story must change).

### 4.1 Sweep and skill changes (`paper-skills/paper-review/references/sweeps.md`, `SKILL.md`)

**Amendments to existing sweeps**

* **M10 / FMT-R family** — add:
  * `FMT-R6`: a reference number fused to the entry text ("1.Chen"); enumerate every entry.
  * `FMT-R7`: the same work printed differently in the main list and the SI bibliography
    (volume/article-number, year, locator) — the SCCNV case; compare by DOI/title key.
  * `FMT-R8`: a software/repository citation with no year or version (inferCNA), and a
    software citation pointing at the *paper about the method* rather than the software
    (inferCNV → Patel 2014); require an explicit software/version entry.
  * `FMT-R9`: preprint-style inconsistency between two entries of the same class.
  * `FMT-R10`: page-range dash normalization (count by document, one row per deviation set).
* **M13** — extend to *content*: every free-text reporting-summary answer is compared with the
  manuscript (software inventory vs Methods, exclusions/thresholds vs actual operations,
  cell-line module vs the samples actually analyzed, recruitment/ethics text vs the manuscript's
  ethics sentence, "no data excluded" vs any documented exclusion/`failed=true` handling);
  duplicated answer text is its own row. Reading the form is a **code-artifact requirement**:
  the review must use the tolerant XFA reader (§4.2), and must record `unable` — never "empty" —
  when the dataset cannot be parsed.
* **M19** — severity policy: report the **venue base cap** overage as its own finding
  (category 4, Major when the profile says "up to N"), and the operator margin as a separate
  note. A margin may only downgrade severity when the profile's `length_limits` declares it and
  the finding text says so; the decision layer consumes the base-cap verdict. Also require the
  artifact to name the counted span ("introduction through Outlook").
* **M20** — add `FMT-S9` (reference-list spacing style) and `FMT-LN1` (line numbering present?
  spacing value; stage-scoped: `[required at revised-submission stage]` when the venue is
  format-flexible at initial submission — say so, and never call it a blocker for initial).
* **M21** — reviewer-conflict severity ladder: (a) suggested reviewer is an author of a tool the
  paper ranks (especially the top-ranked or recommended tool) → **Major**; (b) author of a
  re-analyzed dataset → Minor but must be disclosed (already is); (c) exclusion of authors of
  ranked tools must name the conflict basis and the letter must not pair an exclusion request
  with a suggestion of a competing tool's author → one finding for the asymmetry. Also add the
  two-direction letter-vs-paper check as a required row set (letter claims stronger/weaker than
  the manuscript's own hedges).
* **M22/M33** — add: availability statements that keep a dated negative while the venue's policy
  requires an archival locator → completeness (Major for the types the profile marks); the
  "checked" date must be coherent with other document dates (§M44); the reporting summary must
  repeat the archive state.
* **M30** — add two row classes: (i) **unit/scale coherence** — a stated encoding ("all six
  slices = CN 6") against the downstream metric definitions (diploid = CN 2), enumerated as a
  written-vs-written row when the producer is outside the corpus; (ii) **disclosure placement** —
  an artifact/limitation stated in a reproducibility or Methods paragraph while the manuscript's
  Limitations section omits it, and a magnitude claimed in one place ("0.4 %") that the shipped
  README quantifies differently (16 %, 16/7/37 %) → propagation finding.
* **M31** — extend to figure *deliverables*: for every display item enumerate the shipped
  artwork/source(s), their formats (EMF-only?), metadata dpi, effective ppi at the placed size,
  and whether the manuscript states a re-export/schematic plan; flag "only format is a vector
  blob inside the DOCX" and "raster metadata below the venue minimum" separately (the second is
  a preflight item, not a content defect).
* **M32** — extend the ranking rule to **table rows**: for every statistics table, enumerate
  `(metric, caller, reference, direction, p, corrected?)`; every row whose direction contradicts
  a headline claim on a claim-bearing surface (abstract, section heading, lead sentence) becomes
  a row; the claim must either name the reversal or be requalified. This closes the S2 gap.
* **M34** — add: a shipped analysis artifact (a computed statistics file, a plot dump) that no
  display item or statement references, and that contradicts a "we do not report X" sentence →
  correctness/completeness pair (mcb.tex).
* **M35** — add: a cited tool/patent whose authors include a manuscript author (or the first
  author's employer) while the competing-interests statement says none → disclosure finding with
  the item-level evidence (author list, affiliation).
* **M36** — add `FMT-Z6` (a citation marker whose superscript is fused to a digit-ending token in
  the flattened text, e.g. `HG00820`; report once per instance with the flattened rendering as
  evidence — never claim the Word rendering is wrong) and `FMT-Z7` (fields are still live in the
  submission copy; a stage-scoped recommendation whose finding text must say "flatten after a
  successful refresh, never before"). Keep M36's rule that a refresh-in-Word is the only fix.

**New sweeps** (number from the highest adopted id; M37–M40 from the run are first in the queue):

* **M41 — Table-to-text direction audit** (the S2 class, if not folded into M32 as above):
  enumeration = every statistics table row (metric, caller, reference, effect, p, correction,
  family); artifact `M41_table_directions.md`; finding rules: a row significant in the
  caller's favour while the text claims the reference's overall superiority without naming it;
  a named "exception" set that the table contradicts (SCCNV/SCYN/CHISEL flips); a caption
  definition that a printed number violates.
* **M42 — Method scale/units coherence**: enumeration = every stated encoding/conversion
  ("k slices = CN k", "downsampled to x", "expected ploidy from the profile") cross-checked
  against the metric definitions and the shipped tables; findings: contradictory scale maps,
  missing renormalization statements, sums-of-parts mismatches; producers outside the corpus →
  `unable — producer not in corpus` + an author question.
* **M43 — Unreferenced / unreported analysis residue**: enumeration = every shipped file under
  the evidence area and the package root that a reader could mistake for a result (scripts'
  stats outputs, `.tex` tables, plot dumps); verdicts: source-data-for-display-item (OK),
  working by-product (finding under PKG), or computed analysis contradicting a statement.
* **M44 — Document-set date and version coherence**: enumeration = every dated string (cover
  letter date, availability "checked" dates, form `lastupdate`, PDF creation dates, filename
  version tokens); findings: a date that postdates the package or predates the text it
  accompanies; a form older than the manuscript when the form must certify the manuscript.
* **M45 — Venue structure & format conformance (profile-driven)**: enumeration = the actual
  heading tree of the main text and the profile's `structure` block (section order, required
  heading names such as "Online Methods", banned subheadings such as Discussion subheads,
  display-item count, abstract/reference counts, title length); findings: each deviation, labelled
  `[required at initial submission]` / `[required at revised-submission stage]` per the venue's own
  guide. (This is a mechanical heading-tree walk plus a profile diff.)
* **M46 — Ground-truth provenance & fairness**: enumeration = for each benchmark route, the
  ground-truth source and whether it is itself one of the ranked tools; each tool run with
  non-default settings; each threshold applied post hoc; findings: need for a sensitivity
  analysis / a default-vs-patched comparison / a stated bias direction. (Judgment pass J2 may own
  the severity; the enumeration is mechanical.)

### 4.2 Code changes (`paper_pipeline.py`, `paper_docx_format.py`)

1. **Fix the XFA reader** — `_xfa_dataset_report` (`paper_docx_format.py:8835`):
   * tolerant tag regex (`<tag\s*>` … `</tag\s*>`) — the LiveCycle serializer writes values as
     `<author\n>…</author\n>`, which the current regex misses; that single flaw is what turned a
     filled form into FMT-PDF2 "unfilled";
   * resolve the **current** dataset through the AcroForm's `/XFA` array in the *last*
     incremental update (here: object 257, not the stale empty packet 76) instead of scanning
     every `xfa:datasets` stream;
   * outcome vocabulary: `filled` / `unfilled` / `unreadable — manual`; only the middle state may
     produce FMT-PDF2, and it must require *all* reachable dataset packets to be empty;
   * add `FMT-PDF4`: "filled XFA form delivered unflattened" → the actionable finding
     ("open in Adobe, print to PDF with forms flattened, re-check").
   Make the round-1 review probe use the same reader (the round-1 `M13` row was a false positive
   for exactly this reason, and the round-2 correction then regressed at publish time).
2. **Gate the published package** — in `publish_final_clean` (`paper_pipeline.py:38064`) the
   hygiene rows (`internal_artifacts`, `pdf_artifacts`) are computed after the certification
   inputs are assembled. Plumb them into `decide_certification` (`:37853`) as gate problems (a new
   `--package-gate`, default ON like `--residual-gate`): a HIGH-severity `FMT-PDF*`/`PKG-1` row
   must flip the verdict to NOT CERTIFIED and set the exit code, or, when the operator runs with
   `--non-package-gate`, must at least appear in `certification.blockers`/readme as
   "not submission-ready". The readme (`write_final_clean_readme`, `:38291`) must list *all*
   blocking hand-off items, not only the PDF rows.
3. **Add a submission-readiness verdict** — derive from the champion's ledger +
   `MANUAL_STEPS.md` + review findings: every item with severity ≥ Major and status
   `manual-required`/`resolved-by-hand-off` becomes a readiness blocker
   (`submission_ready: false`), with a machine-readable classifier so the operator can
   `--accept <id>` (recorded waiver, with reason) rather than the pipeline silently shipping.
   `critical_remaining`/`manual_steps` stay tiebreak-only, but readiness is a verdict.
4. **Severity policy for caps** — implement the M19 change: base-cap overage is its own finding
   (`over venue base cap`), margins are notes; the decision consumes the base-cap verdict
   according to the profile (`enforcement: report|gate`).
5. **Extend PKG rules to the evidence area by role, not by blanket skip** — `internal_artifact_rows`
   (`:37974`) currently skips `raw_data/` entirely ("the case that prompted it sat at the corpus
   top level"). Add an evidence-role declaration (`raw_data/MANIFEST` role column or
   `raw_data/ROLE.json`): rows declared `source-data` pass; undeclared or `working` artifacts
   (17 MB plot dumps, agent READMEs, unreferenced stats files) are reported as `PKG-2`.
6. **`zotero-flatten` + re-check helper** — `paper_docx_format.py` already has the flatten
   machinery for hand-offs; wire it as a first-class CLI (`zotero-flatten IN.docx OUT.docx`)
   that refuses to run while `zotero-check` reports FMT-Z1..Z4, and a `--flattened` re-check that
   verifies the flattened copy's numbers equal the refreshed fields.
7. **New code-side rule emitters** matching §4.1: `FMT-R6..R10`, `FMT-S9`, `FMT-LN1`,
   `FMT-Z6/Z7`, `FMT-D1` (date coherence), `PKG-2`, `FIG-1` (display-item artwork inventory),
   `STAT-1` (table direction rows), `RS-1..RS-5` (reporting-summary content rows).

### 4.3 Venue profile changes (`venue_profiles/nature-biotechnology.json`)

Add a structured `structure` block (today the rules exist only inside free-text `source` strings):

```json
"structure": {
  "section_order": ["Introduction", "Results", "Discussion", "Online Methods"],
  "heading_names": {"methods": "Online Methods"},
  "subheadings": {"results": "required", "methods": "required", "discussion": "forbidden"},
  "source": "https://www.nature.com/nbt/content (checked 2026-10-11)"
},
"manuscript_file": {"line_numbers": "recommended", "spacing": "double (revised-submission stage)",
                    "field_policy": "flatten only after a clean refresh"},
"reporting_summary": {"required": true, "readable_export_required": true},
"availability": {"archival_locator_required_for": ["article"],
                 "repository_urls_sufficient": false},
"figures": {"min_dpi": 300, "production_formats": ["pdf", "eps", "tif"],
            "initial_formats": ["pdf", "png", "emf"]},
"length_limits": {"article": {"base": {"abstract": 150, "main_text": 3000},
                              "margins": {"abstract": 1.1, "main_text": 1.25},
                              "margin_status": "pipeline-operator, not venue",
                              "enforcement": "report-base-cap"}}
```

(The margins stay, but the profile must state that they are the operator's and that the base cap
is the journal's; M19 and the decision read `enforcement`.)

### 4.4 Revise-skill changes (`paper-skills/paper-revise/…`)

* **Cluster closure for reference-number defects**: one cluster = all live fields + the entry in
  the main list + the SI bibliography + legends; a refresh of the main document must also
  reconcile the SI bib entry (the SCCNV divergence is a cluster that was only half-fixed). Add
  rule **E13**: after any citation edit, re-run FMT-R6..R10 and the number/entry parity check.
* **`blocked-by-refresh` status** in the ledger, distinct from `manual-required`, so the decision
  layer can count it and the acceptance gate can require the post-refresh re-scan artifact.
* **Rule E14**: a `(checked YYYY-MM-DD)` or dated negative in the manuscript must be reconciled
  with the cover letter, the reporting summary and the compiled artifacts (M44 row), and dated
  negatives must carry the venue's archival policy when the profile requires an archive.
* **Propagation for disclosure placement**: when a limitation/artifact magnitude is corrected in
  one place (README → Methods), the same text must appear in the Limitations section (M30 row).

### 4.5 Pipeline-verdict and readme semantics

* New headline states: `CERTIFIED` (nothing blocking, readiness true) /
  `CERTIFIED — NOT SUBMISSION-READY (N blockers)` / `NOT CERTIFIED` (integrity, panels,
  package gate). The readme lists every blocker with the exact instrument (Zotero refresh,
  archive deposit, form flatten, figure regeneration, S3 re-marking, reviewer list, length).
* The `decide` exit code must be non-zero when the ready verdict is false and the operator has
  not waived the item.
* Keep the package copy unconditional (per the 2026-10-01 operator request) — the verdict, not
  the copy, carries the message.

### 4.6 Tests (` .paper_test/ `)

1. XFA fixture with two dataset packets (stale empty + current filled, LiveCycle
   whitespace-serialized) → FMT-PDF1 yes, FMT-PDF2 no, FMT-PDF4 yes.
2. Same fixture with the filled packet absent → FMT-PDF2 yes.
3. Package gate: a shipped FMT-PDF1 row flips `decide` to not-certified/not-ready (and the readme
   lists it).
4. Readiness classification: a champion whose MANUAL_STEPS has a Major Zotero-refresh item is
   not submission-ready; `--accept` waives it with a recorded reason.
5. M19 severity: 3,745 words against base 3,000 / margin 3,750 → base-cap finding (Major) plus
   margin note; profile `enforcement: gate` blocks.
6. FMT-R6/R7 fixtures (space-after-number; SCCNV main-vs-SI divergence).
7. M44 fixture (cover letter date < availability check date).
8. M32/M41 fixture (S2 row direction vs a headline claim).
9. Prompt re-sync test (the existing byte-identity check) after editing `identify_issues.prompt.md`
   / `adress_issues.prompt.md`.

---

## 5. False positives and disputed items (do not fix these as reported)

1. **FMT-PDF2 "the form ships UNFILLED"** (final readme), **F-016/M13** (round 1) and **I-01**
   ("zero filled field values"): all three read the wrong XFA packet. The current dataset packet
   (object 257, referenced by the last `/XFA` array) is filled — author, `lastupdate 2026-10-05`,
   37+ non-empty leaves including all free-text answers. Two packets exist (a stale empty one and
   the current filled one), and the serialized tags carry whitespace before `>`, which the
   checker's regex rejects. The real defect is the shell (FMT-PDF1) + no flattened export.
   The Audit Report's §11.4 got this right.
2. **"settings.xml still has track changes turned on"** — false for the shipped DOCX: no
   `trackChanges`, no `w:ins`/`w:del` in any part.
3. **"The main file has no line numbers"** (EXPERT; C1's first half) — false: continuous line
   numbering is present (`w:lnNumType`) and renders (the pipeline's own PDF shows 1…N). The
   spacing half is true (1.5×), but both are stage-scoped polish at initial submission, which
   NBT declares format-flexible.
4. **I-02 "six swarmHeatmap PDFs missing, SI cannot be recompiled"** — false: all six are in the
   package and in the ZIP; the audit's own E3 attributes the miss to its truncated download.
5. **E2 "seven dormant bib entries / 26 of 33 printed"** — false: 33 defined, 33 cited,
   33 printed in the shipped compiled SI.
6. **"Fig. 4 embedded at 150 DPI (below the 300 DPI minimum)"** (I-12) — metadata-only: the PNG
   is placed at 5.37 in with 1,719 px ⇒ ≈320 ppi effective; the Audit Report's C7 says "content
   is fine". Keep as a preflight/metadata note, not a content blocker.
7. **"The citation to McDaniel was glued to the sample name" (Fig. 4 legend "120 HG00820 cells")**
   — the `20` is a superscript Zotero marker (`formattedCitation: "\super 20"`), i.e. standard
   formatting; the glue exists only when superscripts are stripped by text extraction. Keep a
   low-severity FMT-Z6 note for digit-ending tokens, but do not report the Word rendering as a
   citation error.
8. **"The Fig. 2 title says six metrics"** — the shipped artwork's title is "scWGS CNV caller
   performance across simulated cells, callers, and metrics". The real (smaller) issue is that the
   section heading/text say "six metrics" while the panel plots eight rows (the six metrics plus
   breakpoint precision and recall); report that as a row-count vs metric-count consistency item.
9. **"Six slices = CN 6 labels one biological copy"** — cannot be settled from the corpus: the
   renormalization, if any, lives in the deposited code. Record as `unable — external producer`
   plus an author question; do not assert either reading in a finding.
10. **"HeLa truth is wrong on more than a third of the autosomes"** — the underlying artifact is
    real (16 %/7 %/37 % of first-segment bases per the shipped README) and material, but the
    "wrong on >⅓" magnitude is an inference that only a regenerated ground truth can confirm;
    the finding should demand the fix/regeneration and the Limitations placement, not assert the
    magnitude.
11. **"CHISEL contradicted: text says it could not run, Discussion says it did not perform well
    even with phased SNPs"** — the Discussion sentence concerns HG008, where phased germline
    variants *were* supplied (Methods §HG008), so that particular pair is defensible; the real
    contradiction is the Results/Methods "could not be run / not evaluated" statements vs the
    stale CHISEL/ACT rows that ship in `Fig3_ploidy_balloons.tsv` (already filed as F-025/F-020).

Additionally, one of the run's *own* findings deserves re-derivation before it is trusted:
F-027/F-021 (M32) asserts the S3 bold p-values are mathematically impossible, which assumes an
exact signed-rank test; the caption does not name the variant. The sweep should require the
generator to state exact-vs-normal and re-derive, rather than asserting impossibility.

---

## 6. Suggested order of work

1. **Same day** (removes the false blocker and the "shipped blockers but certified" behaviour):
   §4.2.1 XFA fix + regression tests; §4.2.2 package gate; §4.2.3 readiness verdict; readme
   blockers list.
2. **This week** (cheap detection wins): FMT-R6..R10, FMT-Z6/Z7, M44 dates, M19 severity policy,
   adopt corrected M37–M40; M21 severity ladder.
3. **Next** (structural): M41–M46 sweeps + profile `structure` block; PKG-2 evidence roles;
   revise-skill E13/E14; prompts re-sync.
4. **Then**: feed the three external reviews (plus BUILD/EXPERT) into the next run as
   `human_review_feedback/` (or pre-filtered `llm_review_feedback/`) so every claim gets a ledger
   row with the false positives above disposed in R1 — the pipeline already supports exactly this
   mechanism, and it is the cheapest way to make the next run demonstrably close every one of
   these items or record a concrete reason.

---

## Appendix A — verified data points used above

* Live XFA dataset (filled): stream object 257 (12,269 B decompressed); `author = Xuegong
  Zhang / Zhen Xie`; `lastupdate = 2026-10-05`; software list includes "AneuFinder
  1.34.0,copynumber 1.38.0", "FLCNA 89902690,SCYN eeef200", "CaSpER 0.2.0,CONICSmat 0.0.0.1";
  `exclusions = "No data were excluded."`; `methodrandomization` contains "method selection,
  thresholds and evaluation code were fixed before the final performance metrics were
  inspected"; recruitment answer duplicated; no bedtools/cellsnp/Eagle/Seurat/Snakemake/liftOver;
  HUVEC/HeLa/COLO/HCC/MDA-MB-231 absent.
* Main DOCX: 124 `ADDIN ZOTERO_ITEM` fields + 1 bibliography field; `w:lnNumType` continuous;
  `w:line="360"` (1.5×) ×74; no track changes; `word/media/image1.emf` 8,748,256 B; images 2–5
  PNG 3510²/2569×2708/1719×1728/4830², placed 5.91/5.40/5.37/5.71 in; pHYs 11811/11811/5906/11811
  px/m ⇒ 300/300/150-metadata(~320 effective)/300 ppi.
* S2/S3 rows quoted from `cnb-25-9-suppFigsAndTables-23fcb60.tex` (~L240–302, L314–340); Fig. 5
  source rows from `raw_data/source_data/Fig5_scRNA_swarm_grid.tsv` (HUVEC-H9 `purity_bin` >80 %);
  `dataset_summary.tsv` HUVEC-H9 = 0.8806; `raw_data/mcb.tex` (Hsu MCB, n=20) unreferenced;
  `Fig3_ploidy_balloons.tsv`: 15 CHISEL/ACT rows `failed=False`, pct 27.85–94.14, Ginkgo higher on
  all 15.
* NBT live pages (checked 2026-10-11): "up to 3,000 words … Abstract – up to 150 words … Results
  and online Methods should be divided by topical subheadings; the Discussion does not contain
  subheadings"; initial submissions "do not need to be specially formatted".


# Remaining-issue triage — 2026-10-09 — two audited final packages

Repo: `/home/zhaoxiaofei/paper-refine` @ `6f541c1` (+ the repository-side fixes described
below, committed as `0bfedcc` and merged as `cab4cc3`). This report answers the three questions asked about the two
audit directories:

1. **Is each potential issue real**, checked against the result directories themselves
   (`/home/cnb-manuscript-postgrad-data/cnb-23to24-1008-0413-6f541c1/final_clean_version` and
   `/home/neohetero-manuscript-postgrad-data/neohetero-06to07-1008-0452-6f541c1/final_clean_version`)?
2. **Why could the repo not catch it** (or fail to address it)?
3. **What was changed in the repo** to identify and address the class, and **what still needs a
   human**.

Both audited directories are READ-ONLY and were not modified. Every check below was run against
them read-only; the repo-side changes are committed (`0bfedcc`, merged as `cab4cc3`).

Source audits ingested (read-only): `audit_data/2026-1009-0128-cnb-23to24-1008-0413-6f541c1-remaining-issues`
(`glm52-agent.txt`, `glm53-agent.txt`, `glm53flash-agent.txt`, `grok-build.txt`, `grok-expert.txt`) and
`audit_data/2026-1009-0140-neohetero-06to07-1008-0452-6f541c1-remaining-issues`
(`grok-build.txt`, `grok-expert.txt`).

---

## 0. Method — and one important correction to the premise

The audits were run against a **package** the operator assembled from the run
(`final_manual_clean_version_cnb-23to24-…zip`, 82 entries) and the CNB one, in part, against
`final_manual_clean_version/` — NOT against the pipeline's own `final_clean_version/`. The two
CNB directories are **different documents**: the manual copy carries 46 references with CNVeil at
13 and BWA-MEM as `Li, H. … BWA-MEM. (2013).`, while the pipeline's certified copy carries 45
references, BWA-MEM as `Preprint at arXiv:1303.3997 (2013)` and the CNP sentence already pointing
at Zarrei. Several audit items are therefore REAL in the manual package and **already absent from
`final_clean_version`**. Everything below is verified against the directory the request named
(`final_clean_version`); where a claim holds only for the manual copy, that is stated explicitly.

Evidence for the re-verification (all read-only, this box):

* paragraph-level text of both DOCX files via `paper_docx_format.paragraphs/text_of`;
* the shipped `raw_data/`, `raw_data/source_data/`, `code/`, `figures/` trees;
* `pdftotext` / `pdfinfo` on every shipped PDF, plus the XFA dataset inside the reporting summary;
* PNG `pHYs` chunks for the embedded image resolutions;
* the run's own reports (`reports/round*_defects.csv`, `decision.json`) to see what the pipeline
  itself had noticed;
* the new code-side scans (below) run against both read-only packages.

---

## 1. CNB (`copy-num-bench`, NBT Article) — verdicts

### 1.1 REAL, and shipped in `final_clean_version`

| # | Issue | Verification | Why the repo missed it |
|---|---|---|---|
| C1 | **Abstract and main text exceed the venue's own numbers** | pipeline's own counter: abstract **164** vs NBT 150 (+14), main text **3,732** vs 3,000 (+732). The scan reported both `over_limit=False` because it compared only the RELAXED caps (165 / 3,750). | M19 compared one number, the relaxed cap. The band between the venue's published number and the pipeline's margin was not a row anywhere, so a 164-word abstract was "clean" in every artifact and in `decide`. |
| C2 | **The reporting summary PDF is blank** | `cnb-24-nr-reporting-summary-filled-c27c42e.pdf`: `pdfinfo` → `Form: XFA`; `pdftotext` → only the Adobe "Please wait…" text; the XFA dataset has **no non-empty value** (all leaves self-closing or `0`). A non-Adobe reader (the journal's converter, a browser, the submission system) sees an empty page. | The PDF was copied verbatim; no check ever opened a shipped PDF except for blank-page counting (`FMT-S2`), which needs *extractable text* — an XFA shell has one non-blank page of JavaScript. |
| C3 | **Internal working material ships in the package** | `REPLACEMENT_LEDGER-c27c42e.md` is at the package root; `raw_data.README-c27c42e.md` line 23 cites `https://chat.z.ai/c/20fd2a87-…` and line 42 `https://sorryios.ai/c/31925719-…`. | The bookkeeping strip matched EXACT names (`replacement_ledger.md`), and the published name carries the version token (`-c27c42e`) so the ledger was never stripped. `raw_data.README.md` sits beside the evidence area (not inside it), so it is ordinary submission content and nothing read it for internal material. |
| C4 | **Availability statements are not final, and pin two revisions** | Data availability: "These results are **not yet deposited** in a DOI-issuing archive" (repo pinned `0b105331…`, 2026-10-05). Code availability: "The code is **not yet deposited** …" (repo pinned `cd2e3e78…`, 2026-10-01); the same two repositories appear with different commits in the two statements. | The availability contract checked that a locator EXISTS and resolves; a future/conditional locator passed, and nothing compared the pinned revisions across statements. |
| C5 | **A "not run" claim the shipped source data contradicts** | Methods: "**SCYN produced no output on any ACT sample**; CHISEL could not be run …"; `raw_data/source_data/Fig3_ploidy_balloons.tsv` carries 255 ACT rows including `tool=scyn` and `tool=chisel` with finite values (`n_cells`, `pct_within`, …). | M30 enumerated NUMBERS only (`hierarchy_seed_rows` pairs written values with table columns). A negative *statement* about a method had no detector, so the table and the sentence were never compared. |
| C6 | **Figure-5 selection rule is not in the manuscript** | The legend says "16 co-sequencing datasets plotted here out of the 41 analyzed"; the criterion (diploid-like tumors and wellDR-seq chip1-only excluded) exists only in `source_data/Fig5_scRNA_swarm_grid.meta.json` (`dataset_exclusion_rule`). | The figure/source-data pairing was never enumerated: no rule required a figure's metadata selection rule to appear in the legend/Methods. (The pipeline's own round-3 defect sheet DID note "Fig. 5 legend never says which 16 of 41 …" as an `M3` **minor** row — reported, never gated.) |
| C7 | **Undocumented TN6/TN7 second read length** | `Fig3_ploidy_balloons.tsv` carries `TN6 · 36 bp` AND `TN6 · 152 bp` (and the same for TN7); the text says "eight breast tumor samples (TN1–TN8)" and "1,024 to 2,400 evaluable cells per sample", while `TN6 · 152 bp` has **173** cells. | Same missing pairing as C6: extra dataset variants in a shipped source file are invisible unless the legend count and the file's own values are compared. |
| C8 | **Reference-entry shape** | `33. Laffy, J. infercna … https://github.com/jlaffy/infercna.` (no version/release/DOI); `41. Chang, H.-C. … bioRxiv-style identifier 2026.04.12.718050` with DOI prefix `10.64898/…` instead of the server's `10.1101/`; `12.` CNVeil and `24.` BWA-MEM and `41.` Chang are preprints. | M10 asked the reviewer to judge each entry by eye; no code rule recognised a malformed/unretrievable entry shape. |
| C9 | **Display-item order** | first mentions: Figures 1–5 in order, but supplementary items are cited out of order (S3 before S1); the supplementary TeX uses `width=1.25\textwidth` / `1.333\textwidth` inside `landscape`. | No ordering rule existed (M3 only asks whether a call-out exists); LaTeX width overflow was never checked. |
| C10 | **Figure 4 is 150 dpi; Figure 1 is EMF-only** | PNG `pHYs`: image2/3/5 = 300 dpi, **image4 (Fig. 4) = 150 dpi**; `word/media/` carries `image1.emf` (8.7 MB Windows metafile) as Fig. 1 with no raster fallback. | The formatter checks image ASPECT ratio (`FMT-IM1`), never resolution or the portability of the embedded format. |

### 1.2 REAL, but only in the manual package (already correct in `final_clean_version`)

| Issue | Status in `final_clean_version` |
|---|---|
| COSMIC cited as 27 while 27 = SafeMut (manual numbering) | **Not an issue here**: reference 27 IS the COSMIC paper, the in-text call-outs and Code availability all use 27. |
| `Front. Genet. Volume 11-2020` (SCCNV) | **Not an issue here**: that entry is reference 14 in the manual copy; in `final_clean_version` the entry reads `BMC Genomics`-style and the malformed volume string is gone. (The rule that now catches it, `FMT-R1`, fires on the manual copy.) |
| BWA-MEM "(2013)." with no venue | **Not an issue here**: `Preprint at arXiv:1303.3997 (2013)`. |
| hg19/CNP sentence cites 37 (SCEVAN) instead of 38 (Zarrei) | **Not an issue here**: ref 37 IS Zarrei and the sentence cites 37. |
| Six Discussion subheadings / no article type / no `Supplementary material` statement / missing 12 pt | **Article type and `Supplementary material` are REAL here** (see 1.3). The Discussion subheadings and the "14 pt body" claim are **not**: body text resolves to 12 pt Times New Roman from `docDefaults` (the 14 pt runs are the four title runs only). Line spacing is **1.5** (`w:line="360"` default) — not the audit's "single-spaced", but still not the double spacing a Nature Portfolio submission is usually prepared with. |

### 1.3 REAL and left to the author by the pipeline's own ledger

* **No article type on the title page** and **no `Supplementary material` statement**: the
  `REPLACEMENT_LEDGER` records both under "Manual step for the author". The repo therefore knew
  and chose to report rather than invent — correct behaviour, but the item must be actioned, and
  it was not visible enough (it lived in a file that then shipped to the journal).
* **Code/data availability not deposited with a DOI**, **commit mismatch between the two
  statements**, **generative-AI disclosure naming `GLM-5.2/GLM-5.3`, `GPT-codex`, `DeepSeek V4.1
  Flash`**, **ethics statement without IRB specifics**, **ORCID only for the two corresponding
  authors**, **cover-letter reviewer/date optics**: author decisions.

### 1.4 NOT REAL (verified and disproven)

* "Body font is 14 pt" — the body is 12 pt; only the title runs are 14 pt (audit's run inspection
  looked at the title block).
* "The supplementary LaTeX source does not reproduce the shipped PDF" (an earlier suspicion) —
  disproven by the glm53 audit itself and by the file inventory here.
* "Reference 40 has an invalid DOI because bioRxiv uses 10.1101" — the *prefix mismatch* is real
  (rule `FMT-R4` now reports it), but the claim "10.64898 is not a DOI prefix" needs the venue's
  own check: the row asks the author to confirm against the server's record rather than asserting
  invalidity. **Manual.**
* "Fig. 2 legend's `intCN_modal_frac` rendering" — not verified here (visual only); keep as a
  visual-check item.

---

## 2. neohetero (`NeoHeteroclitic`, Frontiers in Immunology Original Research) — verdicts

### 2.1 REAL, and shipped in `final_clean_version`

| # | Issue | Verification | Why the repo missed it |
|---|---|---|---|
| N1 | **The abstract reports a p-value the paper's own correction cannot reach** | Abstract line: "every presentation-derived scoring method ranked TCR-facing variants above chance … (unadjusted p < 0.025)". Results/Methods: "If the ten method-versus-chance tests are read as a single family, no test clears Holm's first threshold (0.05/10 = 0.005)" and "These ten tests are reported unadjusted; … none would survive a family-wise correction". With seven antigens the signed-rank floor is 1/128 ≈ 0.008. | M19 counts words; J2 asks the reviewer to look for statistics problems but emits no per-claim row, and no rule compares an abstract-level significance claim with the threshold the Methods state. |
| N2 | **Figure 4's source data is not in the deposit** | Data availability: "The continuous-dataset matrices underlying Figure 4 are **not yet in that repository**; they will be deposited there before publication, and they are **available from the lead contact in the meantime**." The shipped `raw_data/hpep-v07.zip` holds the 26 binary tables only. | Same gap as C4: a conditional/future locator passed the availability check. |
| N3 | **Figure/table numbering does not follow first citation** | First mentions: Figure 1 (p15), **Table 4 (p23), Table 2 (p42), Figure S2 (p53), Table 1 (p63)**, Figure 2 (p75), Figure 3/Table 3 (p78), Figure 4 (p79), Figure S1 (p80), Table S3 (p82), Figure S3/Table S1 (p88). | No ordering rule existed. |
| N4 | **Cell Press leftovers and a fused correspondence line** | p5: `* Correspondence:Zhen Xie, lead contactzhenxie@tsinghua.edu.cn`; p166/170 "**lead contact**"; p168 "This study did not generate new unique reagents."; p170 "requests for resources …". | The venue profile already declared "Lead contact" as a *foreign container heading*, but the check only looked at HEADINGS; there was no phrase-level rule and no space-glue rule. |
| N5 | **AI disclosure names a client, not a model** | p154: "… used GLM 5.2 (Zhipu AI), **GPT codex (OpenAI) codex-cli 0.160.1**, and **DeepSeek-V4.1-Flash** …", in Acknowledgments only. | No rule read the disclosure's shape or its placement. |
| N6 | **Live Zotero fields in the submission copy** | `zotero_field_report`: **137** live fields (136 citation items + 1 bibliography). | By design the pipeline PRESERVES live fields; `unlink_zotero_fields` exists as a policy but is off, and the run's config never turned it on. |
| N7 | **Table 2 defines MixMHCpred's output as an IC50 percentile** | "MMP_aff | PWM-derived | MixMHCpred_aff | **Affinity (IC50) percentile** | Percentile rank of the predicted IC50 (MixMHCpred)" while Methods says it is the percentile of the MixMHCpred score. | A table-vs-Methods definition conflict is an M23/M30-class row for an agent; nothing mechanical pairs a table cell with the Methods definition. |
| N8 | **Table 1 labels D27/D28/D30 "TCR-facing" while their candidate column says "all positions"** | Table 1 rows D27–D30 vs the Figure 4 legend and Limitations ("the published scan covers every epitope position"). | Same class as N7: an intra-document definition conflict inside a table, with no code-side pairing. |
| N9 | **Reference entries that are not published articles** | 42 BWA-MEM arXiv; 44 Mutect2 bioRxiv; 52 JCO trial-in-progress `TPS2700`. | M10 again: shape judged by eye only. |
| N10 | **A stale page field survives in the supplement** | `word/footer2.xml` carries two PAGE fields whose cached results are `3` (rendered as "33" in a text dump). | No rule inspected header/footer field RESULTS. |
| N11 | **The abstract is not in the venue's structured form; no running title** | Abstract = one unstructured paragraph, 202 words; no Background/Methods/Results/Conclusion labels; no running title anywhere. | The Frontiers profile's own note records that the abstract must be "a single structured paragraph (for example IMRAD)" but the note is never turned into a check. |

### 2.2 REAL and matters to the science, judgeable only by a reader (now swept by M31–M35)

* the figure text/legend mismatches the audits found visually (Figure 1 insets "Hetero clitic" /
  "Homo clitic", Figure S1 axis labels "Energy (instability)" / "Reaction time", Figure S2's x-axis
  printing the legacy `PRIME_BArank`, Figure 4's clamped ±0.50 color bar with printed values to
  0.622/−0.603, Figure 3's anchor shift on 10-/11-mers, Figure S3B's mean-PR curve vs Table S1);
* the AH1 nested-dataset double count and the "seven independent antigens" claim;
* Dist_bit's undocumented orientation and the `PRIME_imm` family placement;
* the parent-peptide leakage-check argument.

These need domain reading; the repo now carries **M31–M35** as required coverage rows with their own
artifacts so a review cannot silently skip them.

### 2.3 NOT REAL / already handled

* "Zotero exponents break again" — the fields are live but structurally sound (`error_codes == {}`),
  so the claim is a RISK (fix by unlinking for the submission copy), not a present defect.
* The supplement footer's stale field is real but cosmetic in a Word docx (Word recalculates);
  it matters only if the file is converted by a tool that trusts cached results. Reported as an
  artifact-integrity item, not gated.

---

## 3. Why the repo could not catch these (the gap analysis, by class)

1. **One number per limit.** M19 compared the pipeline's RELAXED cap and never reported the band
   up to it, so a section between the venue's published number and the margin was "clean"
   everywhere (C1, and the same design masks a 3,732-word main text against a 3,000-word rule).
2. **Reference entries were judged, never shaped.** M10 has no mechanical recogniser, so
   malformed volume fields, venue-less entries, unversioned repository citations and preprint
   identifiers with a foreign DOI prefix passed every code-side scan (C8, N9).
3. **Availability was checked for EXISTENCE, not finality.** "Not yet deposited", "available from
   the lead contact", "archived on acceptance" and two commits for one repository were invisible
   (C4, N2).
4. **M30 was numeric.** The source-hierarchy reconciliation paired written NUMBERS with tables;
   a written "could not be run / produced no output" claim against a table that carries the
   method's rows had no detector (C5), and neither did a figure's metadata selection rule or an
   undocumented extra dataset variant (C6, C7).
5. **The package was never inspected as an artifact.** Nothing looked at shipped PDFs for a form
   shell, nothing scanned shipped text files for internal material, and the bookkeeping strip
   was an exact-name list that a version token defeats (C2, C3; also the pipeline's own
   `REPLACEMENT_LEDGER.md` contract made the file a normal stage deliverable rather than a
   by-product name).
6. **The pipeline's own findings were comparison rows at minor severity.** The round-3 defect
   sheet already said "the blank Reporting Summary" and "Fig. 5 legend never says which 16 of 41
   datasets" — as `M5`/`M3` MINOR rows against an opponent. A version that ships them can still
   win, and `decide` certified the package; **reported ≠ required ≠ gated**.
7. **Judgment classes had no coverage row.** Statistics-vs-correction, artwork-vs-legend,
   disclosure shape and abstract structure were neither mechanical rows nor mandatory sweeps, so
   a review could close them as "clean" without an artifact (N1, N5, N11, and the 2.2 list).

---

## 4. What was changed in the repo (committed: `0bfedcc`, merged as `cab4cc3`)

`paper_pipeline.py` (VERSION → `3.7.0`):

* **M19 band**: every M19 row now carries `over_base` + `base_margin`; `scan_lengths_in_sources`
  returns `over_base`; `length_note` prints "above the venue's OWN number … (+N)"; the length rule
  and all five M19 stage mandates say the venue's published number is the one the submission is
  measured against, and a band section must be trimmed or justified.
* **`is_bookkeeping_name`** now matches the by-product FAMILY with a version token
  (`REPLACEMENT_LEDGER-c27c42e.md`, `VISUAL_CHECK-….md`, `revision_report-….json`, …); every
  strip/fingerprint/view path uses the predicate instead of the exact-name set.
* **`internal_artifact_rows` (PKG-1)** scans every shipped text file OUTSIDE the evidence areas for
  internal material (internal AI-review session URLs — `chat.z.ai`, `sorryios.ai`, chat-share
  links — the re-authoring ledger / stage reports / stage notes).
* **`package_pdf_rows`** runs the PDF artifact rules over every shipped PDF.
* **`publish_final_clean`** records `hygiene.stripped_bookkeeping`, `hygiene.internal_artifacts`
  and `hygiene.pdf_artifacts` in `decision.json`, prints them from `decide`, and writes them into
  `final_clean_version.readme.md` as AUTHOR ACTIONS (nothing is deleted from the author's file).
* **M30-NC**: `negative_claim_rows` pairs a written "not run / no output" claim with a shipped
  table's own rows; the M30 artifact grew "Table C" for it.
* **M31–M35** (EVIDENCE-INTEGRITY) blocks in the review/audit/revise/rewrite/integrate prompts; the
  review coverage contract now REQUIRES `M31…M35` rows and their five artifacts.
* **Profile plumbing**: three new optional venue keys (`numbering`, `references`,
  `leftover_phrases`) with validation, format-policy injection, session-policy seeding, and the
  same "inherit a pre-schema field, only when the snapshot has no key" exception the display
  blocks use.

`paper_docx_format.py`:

* **`reference_entry_rows`** → `FMT-R1` (malformed journal/volume, "Volume 11-2020"), `FMT-R2`
  (bare "(YEAR)." with no venue), `FMT-R3` (repository citation with no version/DOI), `FMT-R4`
  (bioRxiv-style identifier with a foreign DOI prefix), `FMT-R5` (preprint / trial-in-progress
  abstract; profile-gated by `references.flag_preprints`).
* **`display_order_rows`** → `FMT-O1` (first-mention order vs numbering; profile-gated by
  `numbering: "citation"`).
* **`correspondence_glue_rows`** → `FMT-X2` (an e-mail/label fused to its neighbour, no space
  after a furniture label's colon).
* **`leftover_phrase_rows`** → `FMT-L1` (the profile's `leftover_phrases`, e.g. "lead contact",
  "this study did not generate new unique reagents").
* **`availability_rows`** → `FMT-AV1` (future/conditional locator) and `FMT-AV2` (one repository,
  two pinned commits).
* **`pdf_artifact_rows`** → `FMT-PDF1` (the Adobe "Please wait…" shell, detected from extracted
  text OR the PDF's own compressed streams), `FMT-PDF2` (XFA/LiveCycle form with no non-empty
  dataset value), `FMT-PDF3` (no extractable text); `check_pdf` now runs them beside the
  blank-page rule.

Profiles and skill text:

* `venue_profiles/nature-biotechnology.json` and `frontiers-in-immunology.json` declare
  `numbering: "citation"`, `references.flag_preprints: true`, and their own `leftover_phrases`
  (schema documented in `venue_profiles/README.md`).
* `paper-skills/paper-review/references/sweeps.md` defines **M31–M35** and the new row ids;
  `SKILL.md`, `discovery.md` and the standalone prompts move to **M1–M35**, and discovery
  proposals now start at **M36**. The identify-issues prompt appendices were kept byte-identical
  to their sources (the skill validator's D10 invariant).

Tests: new suite `.paper_test/test_package_integrity_2026_1009.py` (M19 band, FMT-R*, FMT-O1/X2/L1,
FMT-AV*, a synthetic XFA form shell + a filled one + a plain PDF, PKG-1 + the bookkeeping
predicate, M30-NC, and the sweep/prompt/profile wiring), plus updates to the fixtures that pin the
review coverage contract and the sweep-format text.

### What the new checks now report on the two REAL packages (read-only, demonstrated)

```
CNB final_clean_version:
  FMT-R3  ref 33  (infercna: GitHub URL, no version/DOI)
  FMT-R4  ref 41  (2026.04.12.718050 with doi:10.64898/…)
  FMT-R5  refs 12, 24, 41  (preprints)
  FMT-O1  supplementary figure S1 first cited after S3
  FMT-AV1 ×2      ("not yet deposited in a DOI-issuing archive", data + code)
  FMT-AV2 ×2      (copy-num-bench-scwgs: 0b105331 vs cd2e3e78; …-to-scrna: 29e8a01e vs 98c59c68)
  PKG-1   REPLACEMENT_LEDGER-c27c42e.md ; raw_data.README-c27c42e.md (chat.z.ai URL)
  FMT-PDF1/2  cnb-24-nr-reporting-summary-filled-c27c42e.pdf (XFA shell, no filled value)
  M19 band    abstract +14 over the venue's 150 ; main text +732 over 3,000
  M30-NC      "SCYN produced no output on any ACT sample" vs tool=scyn rows in Fig3 source data

neohetero final_clean_version:
  FMT-R5  refs 42 (arXiv), 44 (bioRxiv), 52 (JCO TPS2700)
  FMT-O1  Table 4 before Tables 1–3 ; Figure S2 before S1 ; Table S3 before S1/S2
  FMT-X2  "* Correspondence:Zhen Xie, lead contactzhenxie@tsinghua.edu.cn"
  FMT-L1  "lead contact" ×2, "this study did not generate new unique reagents"
  FMT-AV1 ×2  ("will be deposited there before publication … available from the lead contact",
               "archived with a permanent DOI on acceptance")
```

---

## 5. What still needs a human (cannot be fixed by the repo)

1. **Fill the reporting summary** in Adobe Acrobat (or replace it with a flattened, filled PDF).
   No automated tool can supply the authors' answers; the repo now reports it as `FMT-PDF1/2`.
2. **Deposit the data/code** (Zenodo/Figshare/SRA/GEO) and replace "not yet deposited" /
   "available from the lead contact" with the DOI or accession — and pin ONE commit per
   repository (C4, N2).
3. **Trim the abstract/main text** to the venue's published limits (C1) or formally decide the
   margin is justified; the numbers are the venue's, not the pipeline's.
4. **Declare the article type** and add the missing `Supplementary material` statement (C3), and
   rewrite the generative-AI disclosure to name the MODEL (and its version) instead of a client
   (N5) — plus the venue-required placement.
5. **Move the science-level corrections**: the abstract's significance claim must match the
   correction the paper states (N1); the figure/source-data selection rules and the extra TN6/TN7
   rows must be stated or removed (C6, C7, N7, N8); the visual figure defects (N2.2 list) need the
   artwork regenerated.
6. **Remove the internal material from the submission package**: `REPLACEMENT_LEDGER-c27c42e.md`
   and the two internal-review URLs in `raw_data.README-c27c42e.md` (C3). The repo now strips the
   ledger family automatically and reports the README; the README's TEXT is the author's.
7. **Reference hygiene**: replace the unversioned/unpublished entries or confirm them (C8, N9),
   verify the bioRxiv DOI against the server record, and add ORCIDs/ethics specifics.

## 5b. Follow-up: the Word/Zotero refresh (the author's own note)

The Zotero refresh that produced `final_manual_clean_version` from `final_clean_version` was
diagnosed in [`ZOTERO_REFRESH_FORENSICS_2026-1009.md`](ZOTERO_REFRESH_FORENSICS_2026-1009.md):
the certified file carried 79/124 citation markers and 15 bibliography positions that disagreed
with its OWN citation order, plus two conflicting Zotero style stores (`nature` in
`word/settings.xml` docVars, `nature-biotechnology` in `docProps/custom.xml`). The refresh
re-derived the order (fixing the bibliography and 111 markers) but left 3 stale fields — exactly
the citation errors the audits found — and re-rendered the reference list in the other style.
The repo now detects all of it offline (`FMT-Z1..Z5`, `zotero-check` CLI), gates a version that
introduces a stale marker, and carries the class as the required sweep **M36**; discovery
proposals now start at **M37**.

## 6. Regression evidence (this box)

* `python3 -m py_compile paper_pipeline.py paper_docx_format.py` — clean.
* `.paper_test/test_package_integrity_2026_1009.py` — all checks pass (68 checks).
* `.paper_test/run_all.py -j 24` — **105 suites, 105 passed** (`/tmp/paper-logs6`). The first pass
  after the change exposed the expected contract-fixture updates (the review contract now
  requires the M31–M35 coverage rows and their artifacts, and the discovery-proposal numbering
  moved to M36); all of them are included above.
* The repository-side fixes are committed (`0bfedcc`, merged as `cab4cc3`), and nothing under
  `~/paper-refine/audit_data/`, `/home/cnb-manuscript-postgrad-data/` or
  `/home/neohetero-manuscript-postgrad-data/` was written to (the new scans open those trees
  read-only).

# Residual-issue ledger — audit of the shipped revision and of the pipeline that produced it

**Date.** 2026-09-21.
**Subject.** `/home/cnb-manuscript-postgrad-data/cnb-12to13-092120-2817c28` — root of the
`copy-num-bench-scwgs` NBT submission, round 1, phase 2. The artefact under audit is the
delivered revision package `runs/r1_a2_revise/revised/` and the frozen review it consumed
(`runs/r1_a2_revise/review/`).
**Question.** Which problems remain in the submission, what class does each one belong to,
why did the pipeline not catch it, and how should `nbt_pipeline.py` / `nbt_docx_format.py` /
the two skills be changed so that the whole *class* is addressed rather than the instance.
**Status.** This document is a plan. **No code and no manuscript file was modified in this
turn.** Everything below is evidence-backed by reading the shipped artefacts and by running
read-only code-side sweeps against them.

---

## 0. Verdict in one page

The pipeline's *machinery* is in good shape: the corpus is fingerprinted, the review is
frozen, the revision is ledgered finding-by-finding, the originals are hash-verified, and the
package validates. What remains is not a missing capability but a **missing decision layer**:

1. **Rows are scanned but never decided.** `nbt_docx_format.py` enumerated the very problems
   the operator is now reporting — 10 `FMT-T8c` rows ("`nature biotechnology` appears 3x in
   one paragraph", "`sequencing` appears 5x"), 96 `FMT-T9c` rows (long sentences; "paragraph
   19 carries 4 enumerated items in 234 words") — and the review disposed **all of them** with
   the single rationale *"editorial preference only, no journal rule"*. A scanner row that is
   dismissed with "no journal rule" never becomes a finding, so the revise arm never touches
   it, `writing_remaining` counts it as resolved, and the judge is never told about it.
2. **A report-only row has no owner.** `FMT-T8b/T8c/T8d/T8e/T9d` are "reported, never
   auto-edited". The review *may* promote one to a finding (it did for nested parentheses),
   but nothing forces a per-row "→ finding id, or OK with a *rule-specific* reason".
3. **The anti-invention device has no resolution path.** `[AUTHOR TO COMPLETE: …]` markers are
   the pipeline's way to avoid fabricating content, but every marker is also a *question*,
   and `placeholder_ledger()` already classifies questions into `searchable` and
   `author-only`. The `searchable` class is inert: `placeholder_lookup_rows()` is defined and
   **never called** (no CLI flag reaches it), no run ever writes `reports/PLACEHOLDER_LOOKUP.json`
   (the file the seeded artefact tells the session to consult), and the session prompt confines
   reading to the sandbox — so the session cannot search even if it wanted to.
4. **Artifacts exist without completion contracts.** `OUTLINE.md` (175 rows) was filled with
   the first sentence repeated back as the "summary" and one identical disposition;
   `CODE_SCANS.json → numbers.rows` has a `source` column that is empty in **2169/2169** rows;
   `PLACEHOLDERS.md` accepts `carried forward` as a terminal resolution. Nothing in the
   postcheck fails when an artifact is technically present but substantively empty.
5. **Whole classes have no check at all.** Paragraph/list segmentation (the operator's 2b),
   concept-level terminology (CN vs CNV vs CNA, 2c), near-synonym conflation (emulate vs
   simulate, 3c), external-identifier resolution (DOIs, SRA accessions, repositories, commits,
   preprint status, archival deposits), gene-symbol nomenclature, and SI↔main-text parity.

Nearly every remark in the operator's message maps to a row that the code **already produced**
and the decision layer **threw away**, or to a check that the discovery round **proposed and
nobody adopted** (`review/round2/new_sweeps.md` proposes exactly M21 correspondence-policy,
M22 data/code-availability integrity and M23 supplementary parity — all still "proposals for
the operator to renumber and validate").

---

## 1. Root causes

| id | root cause | where it lives | why it produces leftovers |
|---|---|---|---|
| R-01 | **Disposition without a bar.** A category-2 writing row may be closed as "no journal rule, no ambiguity". | review policy (`references/sweeps.md`, class table) + the review session's own judgement | the scanner's bar ("is there a journal rule?") is not the operator's bar ("does this read well, is it precise, is it consistent?"); *every* readability row can be dismissed this way |
| R-02 | **Report-only rows have no downstream owner.** | `nbt_docx_format.py` rule "fix": `editorial`, `report only` | the revise arm disposes such rows *in its own report*; the manuscript is not required to change; the judge never sees the report |
| R-03 | **No resolution engine for searchable placeholders**, and the session may not search. | `nbt_pipeline.py:5850` (`placeholder_lookup_rows`, dead), `:6010-6025` (seeded artefact), `:5650` (count delta = warning) | the only sanctioned network route is the orchestrator, and it is never invoked |
| R-04 | **Artifacts without completion contracts.** | `_seed_evidence_artifacts` (OUTLINE / PLACEHOLDERS / numbers / terms) | row counts are checked in places; *content quality* is not; boilerplate passes |
| R-05 | **Checklist gaps + manual adoption loop.** | `references/sweeps.md` (M1–M20), `nbt_docx_format.py` (`long_text_rows`, `CONFUSABLE_PAIRS`, `KEY_TERMS`) | no rule consumes `list_markers`; no concept layer; no identifier/gene resolution; M21–M23 never adopted |
| R-06 | **No fix-quality loop.** | stage postcheck + V3 rescan | a fix is verified only against the *mechanical* scans of the same families; a repair that re-scopes a list (SI nested parenthesis → comma list) or introduces a hedge term ("a qualitative ranking") is invisible |

---

## 2. Verified problem inventory

Each entry: **class** · evidence in the shipped artefacts · why the code missed it · fix id (§4).

### P-01 — A `searchable` placeholder was carried forward although the answer is a verified negative
*Evidence.* Cover letter p7: `Preprints: [AUTHOR TO COMPLETE: state whether this work has been
posted to a preprint server; if it has, name the server and the DOI, otherwise write "not
posted".]` · `review/artifacts/PLACEHOLDERS.md` row 1 classes it `searchable` and resolves it
as *"carried forward — the missing content was not found elsewhere in the corpus, so nothing
was filled in"* · `revised/MANUAL_STEPS.md` item 2 · `revised/REVISION_REPORT.md` F-011.
*Verified here (2026-09-21).* `CopyNumBench` returns **0** hits in Europe PMC (which indexes
bioRxiv/medRxiv/Research Square), **0** in OpenAlex, **0** in Crossref; `"commutativity-based
benchmark"` returns 0; no Zenodo deposit exists. Conclusion: **not posted** (a negative, but a
*verified* negative with a reproducible query).
*Why missed.* R-03 + R-02: the marker is never a finding for the judge, and the search route is
dead code. *Fix:* W-02.

### P-02 — A distinctive journal name repeated five times in one cover letter
*Evidence.* Revised letter contains `Nature Biotechnology` **5×** (base: 6×) in ~500 words, three
of them inside one 161-word paragraph. `work/FORMAT_SCAN.json` row 5:
`FMT-T8c | 'nature biotechnology' appears 4x in one paragraph (166 words)` → disposed
*"OK — a content word repeated inside one long paragraph; no journal rule, no ambiguity"*.
*Why missed.* R-01/R-02: the row existed; the disposition bar was "journal rule". *Fix:* W-01.

### P-03 — The abstract sentence the operator singles out is exactly 45 words, i.e. below the scanner's own bar
*Evidence.* Abstract (172/172 words) sentence 5 = **45 words**: *"Ginkgo gave the best overall
balance across the six metrics — a qualitative ranking — among the eight competing callers,
largely through more accurate ploidy estimation, corroborated by … HG008 subpopulations."*
`long_text_rows()` fires at `n > 45` (`nbt_docx_format.py:694-704`), so **no row was emitted**
for it; the abstract has no `FMT-T9c` row at all. The second half of the operator's complaint —
`a qualitative ranking` is undefined — is a *different* class with no check at all (P-07).
*Why missed.* Boundary + missing "undefined qualifier" rule. *Fix:* W-01, W-04.

### P-04 — A 269-word paragraph that embeds a four-item enumeration
*Evidence.* `work/FORMAT_SCAN.json` emits
`FMT-T9c | paragraph 19 carries 4 enumerated items in 234 words` (base) / `246 words` (revised;
the DOCX stores the same paragraph as 733 words with its embedded citation payloads),
with the rule's own advice *"either give every item its own paragraph (consistently) or break
the paragraph at a natural boundary; keep the treatment of the items identical"* — and the
review's M20 artefact disposes it inside the blanket *"OK — long sentence / long list
paragraph; editorial preference only, no journal rule (96 rows recorded)"*. The delivered
paragraph is 733 raw words (269 words of prose + citation payloads) and holds steps (1)–(4);
`CODE_SCANS.json → outline` records `lists: "1,2,3,4"` for that paragraph, and no rule anywhere
consumes that field.
*Note on the operator's exact wording.* In the shipped package (1)–(4) are **one** paragraph,
not "(1)–(3) here, (4) there". Either reading is the same defect class: an enumerated workflow
whose segmentation is inconsistent with its own enumeration. The pipeline has no rule that can
express this, and the one row that noticed was dismissed. *Fix:* W-01, W-05.

### P-05 — `CN`, `CNV`, `CNA` and "copy-number call / CNV call" are used for the same concepts
*Evidence.* Abstract: *"Copy-number (CN) callers"*; Introduction: *"the available copy-number
variation (CNV) callers"*; Results §CNV callers: *"The third step runs each CNV caller …"*;
Fig. 1 legend: *"Strategies to benchmark CN callers … CN, copy-number"*; Fig. 2 legend:
*"for calling copy-number variations (CNVs)"*; SI abstract: *"scRNA-seq-based CNV callers …
CNV information"*. `review/artifacts/M8_terms.md` has a row per surface form and disposes each
one separately — `CNV call → "OK — one precise meaning, used consistently; no competing term
found"` and `copy-number call → "OK — one precise meaning, used consistently; no competing
term found"` — so the **competition between the two families is invisible by construction**.
`F-001` renamed a single `CNA` token to `CNV` and left the family ambiguity in place.
*Why missed.* R-05: the term ledger is a *string* ledger with no concept column. *Fix:* W-04.

### P-06 — "emulate" and "simulate" are used interchangeably, sometimes in one sentence
*Evidence.* Fig. 3 legend: *"a–c, **Emulated** COLO-829 … datasets …, in which the expected
ploidy of each cell is known exactly from the **simulation**."* · Fig. 2 legend: *"n = 1,989
cells **simulated** from 9 donors …"* · Results: *"a commutativity-based benchmark on
**emulated** diploid-derived scWGS data"* · Methods: *"downsample real sequencing data and
then … approximately **simulate** any CN profile"* · `FMT-T9d` row: *"'emulate' in 7
paragraph(s) and 'simulate' in 17, together in para [38]"* → finding F-022 → resolved as
*"the two terms are distinguished at first use (p17); the FMT-T9d co-occurrence row remains
by design"*. The disposition fixed the *first use* and left every later use unchecked.
*Fix:* W-04 (glossary + per-occurrence sense audit).

### P-07 — Terms the manuscript itself has to gloss
*Evidence.* *"average **spot length** (sequencing read length, which is associated with
single-cell sequencing technology)"*. A parenthetical gloss is the text admitting a
non-standard term; the pipeline has an L5 rule ("unexplained prerequisites") in the revise
prompt but no enumeration that finds glossary-shaped constructions. *Fix:* W-01 (rule
`FMT-T9f`).

### P-08 — Numbers without a traceable source, in a ledger whose `source` column is always empty
*Evidence.* `CODE_SCANS.json → numbers` = **2169** rows, `source` filled in **0** of them.
`review/artifacts/M4_numbers.md` audits cross-document *agreement*, `M16` traces abstract
statistics to the main text, `M11` audits *style*. No sweep asks "which file proves this
number". Consequences visible in the package: `MANUAL_STEPS.md` item 14 asks the *author* to
confirm *"n = 1,989 cells simulated from 9 donors"* and *"606–1,989 paired cells"* — numbers
that exist in no shipped file.
*Verified here.* Numbers that **are** provable from shipped artefacts: 45,365 = Σ`n_cells_total`
of `raw_figs/dataset_summary-*.tsv` (41 rows) · 2,055 = max `n_cells_total` · 64 = min ·
1.77/3.82 = min/max `sample_mean_ploidy` — all four match the SI text exactly. Numbers that are
**not** provable from the package: the 1,989/606–1,989 cell counts, 120 HG008 cells, 17/20 and
2/25 metaphase spreads, 85 % diploid threshold, 0.20 purity cut, 4.8–9.5 % CNP, 28/1,496
aneuploid chromosomes, 10⁻⁶ vs 10⁻³ mutation rates, 50-fold KRAS amplification.
*Fix:* W-03.

### P-09 — No external-identifier resolution (and one real inconsistency it would have caught)
*Evidence.* The package asserts 8 SRA/BioProject accessions, 53 DOIs, 4 repository URLs and 3
commits; the review's M2/M4 sweeps check *internal* consistency only.
*Verified here (read-only, public APIs).* 53/53 DOIs resolve in Crossref with matching titles ·
8/8 accessions resolve with non-zero SRA hit counts · both GitHub repositories exist and are
public (MIT) · all three pinned commits exist.
**Found:** the Data-availability statement pins
`…/copy-num-bench-scwgs/tree/e51505a985a9b22845a7381e111a7d3ff4dc0293` (committed 2026-09-14,
*"Added cnv_heatmap_montage.py"*) while Code availability pins
`…/copy-num-bench-scwgs/tree/87728e25fdd06b99136af8002ff1c80d5ee9e4e8` (2026-09-12) for the
same repository — i.e. the "data" pin is **newer and is a code change**, so the sentence
"the commit named here is the revision that produced the published numbers" is not yet
established. This is exactly the class that manual step 14 asks the author to check by hand.
*Fix:* W-03, W-09 (adopt M22).

### P-10 — Numeric typography: the LaTeX SI uses no `\SI`/`\num`, and the style is mixed
*Evidence.* `grep -c 'SI{'` on both SI `.tex` files = **0**; the standalone wrapper
`cnb-12-3-suppAll-*.tex` does not load `siunitx`. Mixed numeral style in the main text/legends:
*"9 donors"* next to *"nine callers"*; *"n = 1,989"*. `M11_si.md` audits unit style but has no
rule for quantities outside `\SI`/`\num` (the helper `UNIT_RE`/`number_format_rows()` exists in
`nbt_docx_format.py` for exactly this, but no rule consumes it).
*Fix:* W-06.

### P-11 — No gene/symbol nomenclature check
*Evidence.* `KRAS` (main text) and six marker-gene sets (SI) appear; nothing verifies approved
symbols, aliases, or the italics convention. *Feasibility verified here:* the HGNC REST API
answers `KRAS → HGNC:6407`, `PTPRC → HGNC:9666`, `CD3D → HGNC:1673`, and a non-symbol
(`Ginkgo`) returns 0. *Fix:* W-03.

### P-12 — Availability claims vs locator class
*Evidence.* *"Processed benchmarking results … are available from the repositories listed in
Code availability at the version-pinned URLs …"* plus a hand-off DOI placeholder; *"publicly
available at https://github.com/…"*; the discovery round already proposed **M22** (availability
integrity: "a 'permanent archive' claim carried by a bare/version-pinned repository URL") and it
was never adopted into `sweeps.md`. *Fix:* W-09.

### P-13 — SI ↔ main-text parity is unchecked
*Evidence.* The SI is a second document with its own numbers, cross-references and availability
statements; M23 (parity) is a proposal only. Today the shared quantities I tested agree
(41 datasets, 45,365 cells, seven callers, six metrics, 200 kb, ±0.5), but that agreement is
unverified-by-construction, and the *lexicon* disagrees (P-05). *Fix:* W-09.

### P-14 — The same quantity is presented in three vocabularies across documents
*Evidence.* Abstract says "across the six metrics"; the cover letter says "gave the best overall
balance across metrics" (drops the count); Fig. 2's legend says "n = 1,989 cells **simulated**
from 9 donors" while Fig. 3 says "**Emulated** … known exactly from the **simulation**".
*Fix:* W-04 + W-03 (one quantity ledger; one concept glossary).

### P-15 — The completion marker's `writing_remaining` is only as good as the review
*Evidence.* `REVISION_REPORT.md`: `critical_remaining = 0`, `writing_remaining = 0` — while the
operator, reading the same package, finds category-2 problems. The marker is "cross-checked
against the frozen review", and the frozen review disposed every writing row as OK, so the
check is vacuously satisfied. *Fix:* W-01 (the cross-check must count *undisposed* code-side
rows, not only findings the review happened to write).

### P-16 — Placeholders that are *not* author-only were routed as if they were
*Evidence.* `MANUAL_STEPS.md` items 2 (preprint — verified negative, P-01), 4 (three ORCID iDs —
`ORCID: Xuegong Zhang 0000-…, Zhen Xie 0000-…` are already present, the three missing ones are
public-registry facts), 3 (funding — genuinely author-only), and the two archival DOIs
(verified here as **not yet deposited** — an author action, but one whose *absence* can be
stated instead of leaving a marker). *Fix:* W-02.

### P-17 — A fix can introduce a new class of defect, and nothing looks
*Evidence.* (i) `F-031` removed the outer parentheses of the SI protocol list; the delivered
sentence is now *"…it requires specialized library preparation protocols, namely MDA, MALBAC
(…), DLP+ (…), wellDR-seq, scONE-seq and DNTR-seq, and their derivatives, as well as deep
per-cell sequencing and dedicated bioinformatic infrastructure."* — the colon's list of three
costs has become a list whose first item now swallows the other two. (ii) `F-035`'s hedge
"a qualitative ranking, not a composite score" was inserted into the abstract, creating the
undefined modifier the operator asks about (P-03). Both are invisible to V3, which re-runs the
same mechanical families. *Fix:* W-07.

### P-18 — The abstract is pinned at the cap (172/172), so every wording fix costs content
*Evidence.* M19 row: abstract 172/172, main text 3,749/3,750, cover letter 497 (300–500).
The caps are intended as "relaxed, never a gate", but the package is now at the boundary, which
*de facto* blocks the operator's own requests (split the 45-word sentence, soften the premise
sentence) unless a compensating cut is found in the same section. *Fix:* W-08.

---

## 3. False positives and non-defects (do not act on these)

| id | claim | verdict |
|---|---|---|
| FP-01 | "Use `\SI` everywhere." | **Format-scoped.** `\SI` applies to the LaTeX SI only; the main text is DOCX (Zotero fields), where the analogous rule is typographic (value/unit spacing, `×` not `x`, en-dash ranges, thousands separators). Mandating `\SI` in DOCX would be wrong. |
| FP-02 | The Chinese prompt's step 12 ("separate word groups with spaces, end each sub-sentence with a newline") and the scoring prompt's rules b13/b14. | **Not applicable to English.** Adopting them would inject spurious spaces/newlines and fail every sentence. The English analogue is "one idea per sentence, long sentences split, one topic per paragraph". |
| FP-03 | "`FMT-T8c` is a false-positive rule." | **No.** The *rule* is right; the *dismissal* was wrong (P-02). Keep the rule, change the disposition bar. |
| FP-04 | "The unseparated 4-digit numbers in `dataset_summary-*.tsv` are a defect" (review finding F-021). | **Correctly discarded.** Machine-readable payloads must keep canonical formatting; the pipeline's exemption is right and must be preserved (the fixer/ledger must never "prettify" data files). |
| FP-05 | "Nine callers" vs "eight competing callers" is a contradiction. | **No.** Ginkgo is one of the nine; eight compete against it. A quantity ledger must encode this relation rather than flag it. |
| FP-06 | Em-dash density cap, 300–500-word cover-letter range. | **Pipeline/user preference, not journal rules — keep non-gating.** But "not a journal requirement" must never be the *only* reason to close a *writing-quality* row (that is exactly the R-01 failure). |
| FP-07 | `[AUTHOR TO COMPLETE: …]` markers as such. | **Correct: never a defect.** Only an unresolved **`searchable`** marker is (P-01); `author-only` markers must stay. |
| FP-08 | "CNV call" and "copy-number call" are the same term misspelled. | **Refine, do not blanket-rename** — see §5.2. |
| FP-09 | "Eight CN callers" (Fig. 4 legend) vs nine callers. | **No.** SCYN produced no HG008 output; the legend says "the eight CN callers that produced output". |
| FP-10 | Lower the long-sentence threshold globally to catch the abstract's 45-word sentence. | **No — tier it.** A global lower bar would emit hundreds of rows (Methods is full of long enumerations). Tier by section: abstract/legends/cover letter >40 → finding; body >45 → finding; Methods >60 → advisory. |

---

## 4. Proposed changes (workstreams)

Anchors are given as `file:line` at the current HEAD (`nbt_pipeline.py`, 15,516 lines;
`nbt_docx_format.py`, 2,315 lines). Each workstream lists: change · artefact · gate · test.

### W-01 — Give every code-side row a *decided* disposition (fixes P-02, P-03, P-04, P-07, P-15)
1. `nbt_docx_format.py`:
   * tier `long_text_rows()` (`:694`): `≥40` words → finding in abstract/legend/cover letter;
     `>45` → finding in body; `>60` → advisory in Methods;
   * promote `FMT-T8c` to a rule with an explicit editorial bar (a distinctive proper name ≥3×
     in one paragraph, or a non-technical content word ≥5×) whose finding text names the
     remedy (pronoun, ellipsis, restructure) — no longer "report only";
   * add `FMT-T9f` — a term glossed in parentheses by the manuscript itself ("X (Y, which …)")
     is a non-standard term: either use the standard term or keep the gloss and mark it;
   * add `FMT-T9g` — paragraph structure: words, enumerated-item count (`list_markers` is
     already collected in `evidence["outline"]`), and an enumeration split across a paragraph
     boundary.
2. `nbt_pipeline.py` postcheck: for every seeded row, require a disposition from
   `{finding:<id>, ok:<reason>, manual:<reason>}` where `ok:` must cite a rule-specific bar
   (a writing row may not be closed with "no journal rule"); **fail the artefact** when the
   same rationale string appears more than K times (boilerplate detector — the shipped review
   has one rationale on 96 rows and would fail, which is the point).
3. Completion marker: replace `writing_remaining` with `writing_rows_open = (seeded writing
   rows) − (rows with a finding id) − (rows with a rule-specific ok)`, so the tie-break cannot
   be satisfied by an empty review.
*Test:* `.nbt_test/test_residual_disposition_2026_0921.py` — asserts the abstract's 45-word
sentence and the 4-item paragraph produce findings, and that a 96-identical-rationale artefact
is rejected.

### W-02 — Build the resolution engine for searchable placeholders (fixes P-01, P-16, R-03)
1. Wire `placeholder_lookup_rows()` (`nbt_pipeline.py:5850`) to a real flag
   (`setup --placeholder-lookup {off,online}`, default `online` when a network probe succeeds)
   and call it in `materialize` for every stage that can receive a placeholder.
2. Extend it from "preprint" to **every searchable class**, each with its own public endpoint
   and a recorded query/observation/timestamp:
   preprint/paper → Europe PMC + OpenAlex + Crossref (title and tool name);
   DOI → Crossref (`/works/{doi}`);
   accession (SRA/BioProject/GEO) → NCBI E-utilities (`esearch`/`esummary`);
   repository/commit → GitHub API (`/repos/…`, `/commits/…`);
   archival deposit → Zenodo/Figshare/Software Heritage search;
   ORCID → the ORCID public API (name + affiliation, proposal-only when ambiguous).
   Write one artefact per stage: `work/IDENTIFIER_LOOKUP.json` + `EVIDENCE_PACK.md` rows.
3. Resolution vocabulary (three outcomes, all allowed): `found:<value>` ·
   `verified-absent (evidence: queries, endpoints, timestamps)` ·
   `author-only:<why the fact is not findable>`. A `searchable` marker that ends the run
   `author-only` must carry a recorded failed-search artefact.
4. Add the carve-out the current rules lack: writing **"not posted"** (or "not yet deposited")
   after a clean, recorded search is *not* invention — it is a verified negative and should be
   preferred over leaving a marker in a submission document.
5. Gate: a stage may not *increase* the count of unresolved `searchable` markers; `decide`
   reports `searchable_unresolved` and (with `--residual-gate`) turns a non-zero count into a
   decision problem.
*Test:* the fixture run must end with `Preprints: not posted.` and
`placeholder_searchable_unresolved: 0`, with `IDENTIFIER_LOOKUP.json` naming the queries.

### W-03 — Number, identifier and gene ledgers with code-filled sources (fixes P-08, P-09, P-11)
1. `number_ledger()` (`nbt_docx_format.py`) gains `source` + `source_kind`
   (`analysis-output | shipped-table | cited-literature | design-parameter | identifier |
   structural`) + `status`.
2. Reconciliation sub-sweep (code-side, no model): pair every derivable quantity with the
   shipped table that proves it (extend the M15 parser: sums, min/max, row counts, ratios; the
   TSV/`.tex`-table parsers already exist) and mark those rows `proved`. Target examples in this
   corpus: 45,365 · 2,055 · 64 · 1.77/3.82 · 41 · six metrics.
3. Rule: every number in the abstract, a figure legend or the cover letter must end
   `proved` (above), `cited` (with the reference and the quoted value), `parameter` (defined in
   Methods/code) or `manual:<exact check>`. Numbers elsewhere may be `unsourced` only if the
   stage records why. **Do not auto-delete unverifiable numbers**: deletion is a
   `preservation`-tier change and needs the author's decision (removal is only for
   non-essential decoration).
4. `REFERENCE_LEDGER` (every DOI in the corpus — 53 distinct here — with: resolves? title
   ratio? year match? retraction flag via
   Crossref `update-to`), `ACCESSION_LEDGER` (E-utilities), `GENE_LEDGER` (HGNC symbol/alias +
   italic convention). All are code-side and offline-degradable (SKIP, never FAIL, when the
   network is unavailable) — exactly like the existing validator's engine probe.
*Test:* the fixture proves the five derivable numbers and reports the remaining ones as
`manual/*`; the reference ledger returns 53 OK; the accession ledger returns 8 OK.

### W-04 — Concept glossary + per-occurrence sense audit (fixes P-05, P-06, P-14)
1. Seed `GLOSSARY.md` per corpus: `concept | definition | authoritative surface form |
   forbidden synonyms | first-use site`. Concepts are seeded by code from `KEY_TERMS` +
   `CONFUSABLE_PAIRS` + the manuscript's own glosses, and *decided by the review* (the author
   confirms): CN (integer/relative copy-number state) · CNV (a gain/loss event) · CNA ·
   CN calling vs CNV calling · ground truth (reference vs truth) · ploidy · emulation vs
   simulation · qualitative ranking · validation vs verification.
2. Extend `CONFUSABLE_PAIRS` (`nbt_docx_format.py:559`) with the domain pack: (CN, CNV),
   (CNV, CNA), (call, detect), (ranking, score) — present — (estimate, measure) — present —
   (emulate, simulate) — present — plus (reference, truth), (validate, benchmark),
   (sample, cell), (sensitivity, recall), (specificity, precision).
3. Replace the co-occurrence trigger with a **sense audit**: one row per occurrence family
   (`term | occurrence sites | intended concept | glossary-compliant?`), and a rule that a
   hedge/qualifier the manuscript introduces ("qualitative ranking", "descriptive rather than
   inferential") must be defined at first use or replaced by plain language.
4. The revise stage's P1 propagation must re-run the *sense* audit, not just count tokens, so
   "distinguished at first use" can never be the whole fix.
*Test:* fixture asserts `CN/CNV` and `emulate/simulate` produce concept findings with the
specific occurrences (Fig. 3 legend co-occurrence included).

### W-05 — Hierarchy pass with a completion contract (fixes P-04, R-04)
1. `OUTLINE.md` rows require a *generated* one-line summary (not the first sentence) and a
   verdict from `{coherent, incoherent:<finding>, child-mismatch:<finding>}`; the seeded
   artefact must reject a summary that is a prefix of `first sentence`.
2. Add the three coherence relations as code checks: paragraph↔heading topic match,
   sibling summaries must differ pairwise, section summary must cover its children's topics.
3. Code-side validation: ≥X % non-boilerplate verdicts, no identical disposition string more
   than K times, every row disposed.
*Test:* the shipped `OUTLINE.md` (175 rows, one verdict, summaries = first sentences) must fail
the new contract.

### W-06 — Quantity typography, format-scoped (fixes P-10)
1. Add `siunitx` to the *editable* SI preamble (`cnb-12-3-suppAll-*.tex`) and a rule: a
   value+unit in a LaTeX source outside `\SI`/`\qty`/`\num`/`\SIrange` → formatting finding.
   Accept `\qty` (siunitx v3) and `\SI` (v2 / deprecated alias) — do not force one spelling.
2. Exemption list, encoded in the rule (not left to judgement): numbers inside `\code{}`,
   metric/identifier names (`intCN_accuracy`, `hg19`, `GRCh38`, `v2.4.1`, `d7c7790`),
   gene symbols (`KRAS`), chemical names (`4′,6-diamidino-2-phenylindole`), accession strings,
   citation/reference/figure/table numbers, values inside generated table files
   (`bench-results-*.tex`, `dataset_summary-*.tsv`) — fix those at the generator, never in the
   generated file.
3. DOCX counterpart rule (no `\SI` possible): value–unit spacing, `×`, en-dash ranges,
   thousands separators, numerals-vs-words for counts ≥10, italic `n`/`k` where the journal
   style requires it — all already partially present in M11; add the numerals-vs-words and
   statistical-symbol cases.

### W-07 — Fix-quality loop (fixes P-17, R-06)
1. After every edit batch, re-run the *new* rule families (not only the ones the finding came
   from) over the edited paragraph, and require the stage to show the paragraph passes.
2. Add a "counter-change" artefact: for any structural edit (removing parentheses, splitting a
   list, inserting a hedge), record the resulting sentence and its own scan rows, so
   "the fix created a new sentence-level defect" becomes a visible row instead of a surprise.
3. Add a duplication check for hedges: the same hedge inserted in ≥2 places must be defined
   once and referenced, not repeated.

### W-08 — Cap management (fixes P-18)
1. Keep the caps non-gating. Add a *slack* read-out to the M19 row (`remaining words`) and let a
   session trade within a small band (±3 %) when a *finding*-driven edit requires it, recording
   the trade in `CHANGELOG.md` under M19.
2. Never let the abstract sit exactly on the cap: prefer ≤ cap−3 words so that the next
   finding-driven edit has room without forcing an unrelated deletion.

### W-09 — Adopt the discovery proposals as real sweeps (fixes P-09, P-12, P-13)
* Promote `review/round2/new_sweeps.md` M21 (correspondence policy), M22 (availability
  integrity), M23 (supplementary parity) into `references/sweeps.md` as first-class checks, and
  make adoption mechanical: an "adopted-sweeps registry" the pipeline reads, so a validated
  proposal reaches the next round's review prompt without a human editing the skill.
* Add to M22 the *version-pin consistency* check that found the e51505a/87728e2 mismatch.
* Add to M23 the quantity/lexicon parity table (SI ↔ main text ↔ cover letter).

### W-10 — Review architecture: split by failure mode + adversarial verification (fixes R-01, R-02, R-04)
* `--review-split` exists (`off|phases|aspects`) but was `off` in this run. Make it default-on
  above a corpus-size threshold, and add a third scope: **adversarial verification** — a session
  that receives the *artefacts and dispositions* (not the corpus) and must produce a finding for
  every disposition it can refute, citing the row. That is the cheapest defence against a
  boilerplate disposition, because it does not depend on the first session's attention.
* The merge contract already unions two parts and requires every check id to be disposed;
  extend it to three prefixes (`FA-`, `FB-`, `AV-`).
* Keep the judge blind (its rules are right); the adversarial pass is a *review* session, so it
  inherits the corpus-access rules.

### W-11 — Arm design for integration (operator suggestion 4)
* Deliberately place one **structural** rewrite arm (outline/organisation) and one
  **sentence-level** rewrite arm in each round, so the integration pool contains both levels
  and the integrator's `DIFF_LEDGER.md` (`small|large`) has both kinds of rows to weigh.
* Require a per-difference artefact (small: before/after paragraph pair; large: outline diff +
  affected summaries) and a per-finding column: "does the port preserve/undo the frozen
  finding's fix?".
* Re-scan the integrated package and compare it against the best arm's scan; a regression in
  any ruled family is a `postcheck` failure, not a warning.

### W-12 — Iterative revision pass: adopt the *transferable* half (operator suggestion 5)
* The L1–L11 language pass already in `REVISE_DIRECTIVES` is the English equivalent of the
  Chinese 12-step prompt; it is applied "at most twice" and is not verified. Change to:
  one row per step in `work/R6_language.md` with a coverage row per step, plus a mechanical
  re-scan after each step; run the pass in *every* package-producing stage (it is currently
  revise-only).
* Adopt the scoring prompt's rules b1–b12 as the **judge's writing rubric** (they map 1:1 onto
  L1–L11 plus punctuation), which makes the writing tier auditable instead of impressionistic.
* Do **not** adopt step 12 / b13 / b14 (FP-02).

---

## 5. Direct answers to the questions in the request

### 5.1 Preprint status (question 1a)
Verified negative, 2026-09-21: `CopyNumBench` → 0 hits in Europe PMC (preprint-indexing),
OpenAlex and Crossref; `"commutativity-based benchmark"` → 0; no Zenodo/Figshare deposit.
Proposed text for the cover letter: **`Preprints: not posted.`** with the search recorded in
the pipeline artefact (endpoints + date) so the statement is auditable. Do **not** leave the
literal marker: the pipeline can answer this class of question itself, and a verified negative
is not a fabrication. (The two *archived-copy DOIs* are the opposite case: the deposit does not
exist yet, so the honest statement is either the real DOI once deposited or an explicit
"not yet deposited" plus the deposit step — never a marker in the letter.)

### 5.2 CNV calls vs copy-number calls (question 2c)
Your reading is right, and the precise version is:
* **Copy number (CN)** is a *state*: the number of copies of a locus in one cell — integer
  (absolute) or non-integer/relative. A **copy-number call** / **CN call** therefore assigns a
  copy-number state (ideally an integer) to each locus: a multi-class, quantitative output.
* **Copy-number variation (CNV)** is an *alteration*: a gain/loss/structural event relative to a
  reference or between samples. A **CNV call** is the decision that such an event is present —
  a detection problem (gain/loss, ROC-AUC, breakpoints, F1).
* **CNA** ("copy-number alteration") is conventionally the *somatic* member of the CNV family;
  in an NBT manuscript, pick one of CNV/CNA and use it for the event sense everywhere.
Consequence for this manuscript: the scWGS benchmark scores *integer CN* profiles
(`intCN_accuracy`, `intCN_PCC`) → use **CN calling / CN callers** there; the scRNA-seq extension
scores *gain/loss discrimination, coverage and correlation* of continuous signals → **CNV
calling / CNV callers** is the defensible term there, and `intCN_modal_frac` is an
integer-CN state metric. Fix by glossary (W-04), not by blanket substitution: the current text
uses "CNV caller" for the scWGS tools in the Introduction/Methods and "CN caller" in the
abstract for the same tools — that is the inconsistency to remove.

### 5.3 Numbers, sources, gene names and `\SI` (question 3b)
* **Yes, generate a provenance artefact — but classify the numbers first.** Five kinds:
  (i) analysis outputs, (ii) facts shipped in the package's own tables/figures, (iii) values
  quoted from cited literature, (iv) design parameters declared in Methods/code, (v) external
  identifiers. Kinds (ii) and (v) are machine-checkable *today* (I proved 45,365 / 2,055 / 64 /
  1.77 / 3.82 from `dataset_summary-*.tsv`, 53 DOIs from Crossref, 8 accessions from
  E-utilities); kind (i) needs the analysis outputs, which is why `MANUAL_STEPS.md` item 14
  exists today; kind (iii) needs the citation plus the quoted value; kind (iv) needs the code
  line or Methods sentence.
* **Do not simply remove a number that cannot be verified.** Removal is a `preservation`-tier
  change; some of these numbers carry the claim. The rule should be: prove → else cite → else
  mark `manual` with the exact check → remove only if it is decoration, and record the removal.
* **Gene names: yes, verify with an artefact**, and make it a nomenclature check (approved
  symbol, alias, species, italic gene symbol vs roman protein). HGNC answers this
  programmatically (`KRAS → HGNC:6407`).
* **`\SI`: yes, in LaTeX, with the exemptions in W-06** — and remember two facts: the main text
  here is DOCX (a `\SI` rule cannot apply to it), and `\SI` is deprecated in siunitx v3 in favour
  of `\qty`, so the rule should accept either instead of forcing one.

### 5.4 "emulate" vs "simulate" (question 3c)
Recommended convention for this manuscript: **simulate** = produce data/values from a model
(the prior strategies: in-silico simulated reads, simulated CN profiles); **emulate** = make
*real* data behave as if they came from a different, known condition by controlled operations
while keeping real-data characteristics (your downsampling + merging of real reads). Under that
convention the Fig. 3 legend, the Fig. 2 legend ("cells simulated from 9 donors") and the
Methods sentence ("approximately simulate any CN profile") are all wrong as written, and the
fix is mechanical once the glossary is fixed.

---

## 6. Verification plan for the changes

1. **Fixture.** Freeze this run (read-only copy of `runs/r1_a2_revise/` plus
   `runs/r1_review/`) under `nbt_audit_data/2026-0921-residual-audit/` as the regression corpus.
2. **Unit/regression suite** `.nbt_test/test_residual_audit_2026_0921.py` asserting, on that
   fixture: T9c fires on the abstract's 45-word sentence and on the 4-item paragraph; the
   boilerplate-disposition detector rejects the shipped `M20_formatting.md` and `OUTLINE.md`;
   the placeholder engine writes `not posted` + `IDENTIFIER_LOOKUP.json` and ends
   `searchable_unresolved = 0`; the reconciliation proves the five derivable numbers; the
   identifier ledger returns 53/8/2/3 OK and flags the e51505a↔87728e2 pin mismatch; the
   glossary audit flags CN/CNV and emulate/simulate at named occurrences; the `\SI` rule flags
   unit-bearing SI numbers and exempts `\code{}` spans.
3. **End-to-end.** Re-run `setup → run --only review,revise` into a scratch root and require:
   zero unresolved searchable markers, zero boilerplate dispositions, no new `F*` regression in
   the rescan, and a revision report whose `writing_rows_open` is 0 *for the right reason*
   (findings resolved, not rows dismissed).
4. **Do not mutate the live root.** This root is mid-run (`r1_a1`, `r1_review`, `r1_a2_revise`
   done; rewrites/integration/judge pending). Apply pipeline changes in the workspace and run
   them in a scratch root/round, so the current comparability of the existing arms is kept.

---

## 7. What was *not* changed in this turn

No file in `/home/cnb-manuscript-postgrad-data/…` was written, and no line of
`nbt_pipeline.py`, `nbt_docx_format.py`, the skills or the manuscript was edited. The only
change in this workspace is this ledger. All network checks were read-only public-API queries
(Europe PMC, OpenAlex, Crossref, Zenodo, NCBI E-utilities, GitHub, HGNC) run from `/tmp`.

---

## 8. Implementation record (2026-09-22)

Everything in §4 was implemented, except where noted. The regression suite is
`.nbt_test/test_residual_audit_2026_0921.py` (~50 checks, including a stub round that runs the
new auditor stage end to end); the whole `.nbt_test/` suite was re-run afterwards.

| workstream | status | where it lives now |
|---|---|---|
| W-01 disposition layer | **implemented** | section-tiered `FMT-T9c` (40/46/61-word bars by section), `FMT-T8c` promoted to a finding-tier redundancy rule, new `FMT-T9f` (self-glossed term), `FMT-T9i` (mega-paragraph), `FMT-T9j` (competing term families); every row carries a `tier`; `disposition_artifact_problems()` + `outline_artifact_problems()` detect empty cells, boilerplate closures and echoed OUTLINE summaries; the review prompt carries a DECISION-ARTIFACT MANDATE; the result is recorded on the run (`artifact_quality`) and reported by the postcheck (`--strict-artifacts` makes it a hard failure) |
| W-02 placeholder/identifier resolution | **implemented** | `--placeholder-lookup {off,online}` (default online); `lookup_kind()` for preprint/DOI/accession/repository/archive/ORCID/**gene**; `placeholder_lookup_plan()`; per-root cache `reports/LOOKUP_CACHE.json` (14-day TTL) + a cached network probe; seeded `work/PLACEHOLDER_LOOKUP.md`, `work/IDENTIFIERS.md`, `work/GENE_LEDGER.md`; the placeholder rule now says a VERIFIED NEGATIVE ("not posted") is the required resolution, and a package that ships an answerable marker fails the postcheck |
| W-03 numbers/identifiers/genes | **implemented** | `reconcile_number_rows()` fills the ledger's `source` column from shipped data tables (sums/min/max/cells) — on the real corpus it proves 45,365 / 2,055 / 64 / 1.77 / 3.82; `IDENTIFIERS.md` verifies every DOI/accession/repo/commit/ORCID; `GENE_LEDGER.md` resolves symbols against HGNC (KRAS → HGNC:6407 on the real corpus); `number_provenance_report()` counts the abstract/legend numbers nothing proves |
| W-04 concept glossary | **implemented** (glossary + family rows; the per-occurrence sense audit stays with the session) | `CONCEPT_FAMILIES` + `concept_family_rows()` + `glossary_seed_rows()`; `work/M24_concepts.md` + `work/GLOSSARY.md` seeded with counts per surface form; seven CN/CNV rows on the real corpus |
| W-05 hierarchy contract | **implemented** | the OUTLINE header now demands a GENERATED summary (not the first sentence), a per-row verdict and no blanket verdict; `outline_artifact_problems()` rejects echoed summaries/one-verdict tables (it fails the shipped `OUTLINE.md`: 86 identical verdicts, 100 echoed summaries) |
| W-06 siunitx | **implemented, format-scoped** | `FMT-T9g` (accepts `\SI`/`\qty`/`\num`/`\SIrange`/`\qtyrange`) wired into every `.tex`/`.ltx` source, with the exemption list (`\code{}`, verbatim, URLs, `\cite`, cross-references, math, generated tables); the DOCX side keeps the typographic rules (M11). The SI itself still needs `\usepackage{siunitx}` — that is a manuscript edit, not a pipeline one |
| W-07 fix-quality loop | **partial** | every edited package is re-scanned by the new rules too (so a fix that re-scopes a list or introduces a hedge now produces a row), but no dedicated "counter-change artifact" is emitted |
| W-08 cap slack | **not implemented** | the caps stay exactly as configured; this one needs the operator's policy decision (the caps are the user's, not the pipeline's) |
| W-09 discovery sweeps | **implemented** | `nbt-skills/nbt-review/references/sweeps.md` now carries the disposition bar and M21 (correspondence), M22 (availability integrity incl. the version-pin check), M23 (supplementary parity) and M24 (concept/term families), plus the new rule-id table |
| W-10 auditor | **implemented as an opt-in stage** | `setup --audit on` → `r<r>_audit` between the review and the revisers: `AUDIT_DIRECTIVES`/`audit_prompt()`, `materialize_audit()`, `postcheck_audit()` (every frozen id disposed; drops need reason+evidence; `AU-` adds validated), `apply_audit_to_findings()`, and `consumed_findings()` so the revisers act on the audited list. Off by default to keep existing roots comparable |
| W-11 arm design | **implemented** | `rewrite_level_of()` stages a `structural` arm and a `sentence` arm when M ≥ 2 (declared in the prompt, recorded on the run, checked against the arm's `REWRITE_REPORT.md`); `DIFF_LEDGER_RULE` now requires a per-row `artifact` (before/after pair for a small row, outline diff for a large one) and a `finding effect` (`preserves`/`undoes`/`none`); `integration_ledger_report()` reports missing artifacts, missing size classes when the pool has both levels, absent donors and undo rows; `scan_regression_problems()` fails a stage that introduces a NEW finding-tier family relative to the package it started from |
| W-12 iterative pass | **implemented** | `LANGUAGE_PASS_RULE` now runs in rewrite/revise/integrate with its own `work/R6_language.md`, one row per change PLUS one coverage row per step, and a code-side re-scan after each step; `language_pass_report()`/`check_language_pass()` record coverage (warning by default, error under `--strict-artifacts`); the judge's `writing` tier now cites a named 12-check rubric (Q1–Q12) with a quote and the intended reading, kept free of provenance vocabulary so the blind panel stays blind |

### Answers to the two questions in the follow-up

**Is an auditor between the reviewer and the reviser a good idea?** Yes — with four conditions,
all of which the implementation enforces: (1) it must be *able to dispose*, i.e. it writes a
record the revisers consume (drops are removed from the effective list) rather than a second
opinion that merely piles up; (2) a drop needs EVIDENCE, never "I disagree" — otherwise the
auditor becomes a way to lose findings; (3) the drops stay visible and reversible for the human
(`audit/audit.json` + `AUDIT.md`), and a reviser that disagrees must re-open them WITH new
evidence; (4) it must attack *dispositions*, not only findings — that is where the pipeline's
biggest loss happened (96 rows closed with one sentence). Cost: one session per round, not per
candidate; benefit: the decision layer stops being the single point of failure. It is off by
default so the current root's arms stay comparable — turn it on with `setup --audit on`.

**Should numbers without a verifiable source be removed?** No — classify first. On the real
corpus the code now PROVES 45,365 (Σ `n_cells_total`), 2,055 (its max), 64 (its min) and
1.77/3.82 (rounded ploidy cells) from the shipped `dataset_summary-*.tsv`; the rest are either
cited-literature values, design parameters (85 %, 0.20, 200 kb, k = 3), identifiers, or genuinely
unsourced (the 1,989/606–1,989 cell counts, 120 HG008 cells, 17/20, 2/25, 28/1,496, 4.8–9.5 %,
10⁻⁶/10⁻³). Removal is a `preservation`-tier change and is the LAST resort for decoration;
the default is to source it, cite it, or hand it over with the exact check.

# Sweeps M1–M24 and Judgment Passes J1–J4 — nbt-review

This file is the single source of truth for Phase 2. Follow it exactly.
Every sweep entry specifies: purpose · scope · enumeration procedure (script
when applicable) · artifact table columns · finding rules (one finding per
instance). Every judgment pass specifies what to look for and how deep.

Two appendices are defined at the end of the mechanical-sweep list: **M18**
(figure-legend length; always enumerated, with an optional proxy cap) and
**M19** (abstract/main-text length plus the user's cover-letter preference;
always runs). **M20** (OOXML style/formatting uniformity; always runs, and its
enumeration is supplied by the pipeline's code-side OOXML scan) follows them.
New sweeps validated from the discovery round are appended after the adopted
M21–M24 as **M25, M26…** in the same format — do not insert into the middle (IDs are
stable).

---

## CLASSIFICATION

Categories (stable labels, used in findings):
- **0 — Editor/Reviewer Concerns**: scope fit, rigor, overclaiming, ethics, data availability, figure quality (anything an NBT editor/reviewer could raise).
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
| 0 Editor/Reviewer Concerns | `correctness` (unsupported claim, overclaim, rigor, ethics), `completeness` (required information or data availability missing) or `preservation` (removed content or a softened limitation) |
| 1 Completeness & Factual Integrity | `correctness` (factual error, wrong number/DOI/reference key, broken cross-reference) or `completeness` (a mandatory item that is missing) |
| 2 Writing Quality, Logic and Repetition | `consistency` (the same thing said, spelled or numbered two ways; a convention applied in one place and not another), `correctness` (the wording changes the meaning) or `formatting` (a one-off wording preference with no convention behind it) |
| 3 Plagiarism / AI-generated content | `correctness` (the integrity of the content itself) |
| 4 Technical Formatting | `formatting` (M18/M19/M20 rows; at most ±1 in a comparison and never decisive alone) |
| 5 Missing / Unneeded Information | `completeness` |

Name the class in the finding's explanation whenever it is not obvious from the
category: a revision or a judge that reads the finding must classify it the same
way, and an edit that cannot be named in this vocabulary is cosmetic (score 0).

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
check: <M1–M24|J1–J4> | severity: <Critical|Major|Minor> | status: <...>
evidence: "<short verbatim quote of the exact word/number/phrase>"
problem: <1–2 sentence explanation>
```

Point to the specific erroneous word, number, or phrase — never the whole
passage. If a Zotero live field cannot be read properly, ignore that field and
tell the user to verify it manually.

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
- (a) used before it is defined (within abstract, main text, Methods, or any single legend)
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
- (h) non-exempt acronym in the title, or in the abstract that is not defined at first use within the abstract. Label these `[recommended]` (Minor) unless the current author guide makes them mandatory; NBT asks titles to avoid abbreviations, but never present a convenience convention as a blocking requirement, and respect the standing exemption on length-driven cuts.
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
for nbt-revise or the user to apply under their Zotero policy.

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
combined Supplementary Information (where required) · Nature Portfolio
Reporting Summary · data availability statement · code availability
statement · author contributions · competing interests declaration ·
funding/acknowledgements · ethics/consent statements (IRB/animal approval
where applicable) · permissions for reused material · accession numbers ·
(preprint disclosure; clinical-trial registration if applicable).

**Artifact:** `M5_mandatory.md`: item | present? (Y/N/partial) | file(s) |
guideline status label ([required at initial submission] / [required at
revised-submission stage — prepare now] / [recommended]).

**Finding rules:** one finding per missing or partial item. Do not invent or
fabricate missing data; note a placeholder may be needed and report every gap.

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

**Purpose:** Nature Biotechnology's formatting guide requires a figure legend
not to exceed "the word limit of the article type" but publishes no number
(checked against the submission guidelines, 2026-09-19). M18 therefore ALWAYS
enumerates every legend's word count; the orchestration pipeline may add a proxy
cap (`--caption-limit N`, default 0 = no cap) to turn a count into a reportable
over-cap item.

**Enumeration:** every figure caption / legend in the corpus (the leading
"Figure N |" label and title count; labels drawn inside the artwork do not)
into `M18_caption_words.md`: document | caption id | word count | disposition.

**Finding rules (one per instance):**
- a legend over the configured proxy cap → FORMATTING-tier item; it is reported
  and, only where redundancy can be removed, compressed — never by deleting
  scientific content, claims, limitations or needed methodological detail
- no cap configured → the count is recorded with the disposition "recorded —
  the journal's per-type limit is not published; author to compare"; the word
  count alone is neither a defect nor a scoring difference
- a legend that is defective for an independent reason (method detail, unclear
  panel description, missing error-bar definition) → the normal
  clarity/formatting finding

Legend length never makes a version ineligible and never decides a comparison
on its own.

## M19 — Abstract/main-text length (always runs)

**Purpose:** the journal's own length limits apply, relaxed by the user's fixed
margins — this replaces the former blanket "abstract/main-text length is
exempt" standing exemption. For a Nature Biotechnology **Article** the base
limits are abstract ≤ 150 words and main text ≤ 3,000 words, with the main text
EXCLUDING the abstract, Methods, references and figure legends; this pipeline
allows **abstract +15% (≤ 172 words)** and **main text +25% (≤ 3,750 words)**.
Another content type takes that type's own base numbers from the journal's
content-types table with the same two margins, and the artifact must name the
base and its source.

**Counting rule (all word counts):** a word is a maximal run of NON-SPACE
characters, with a newline treated as space — `state-of-the-art` is ONE word and
`2026` is ONE word. `scripts/count_words.py` implements this exactly (`--json`
for machine output); use it for the counts instead of estimating.

**Cover letter (user preference, NOT a journal rule).** Nature Biotechnology's
official "Preparing your material" page states what the cover letter must
explain and disclose but states no cover-letter word limit (checked 2026-09-19).
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
  MINOR formatting finding (labelled as the user's preference, not an NBT rule)
- a section that cannot be brought within the cap without losing content →
  `unable — needs the author's judgement`, listed for manual action

**Never:** flag UNDER-length text (the limits are upper bounds; no minimum is
invented), cut text that is within the cap for length reasons, or delete
scientific content, claims, limitations, data or needed methodological detail to
reach a cap. Length is never a gate: it never makes a version ineligible and
only ever enters a comparison through the formatting tier.

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

Breadth of interest, novelty/technical advance, suitability for NBT
specifically; whether the cover letter articulates the significance in plain
terms for editors; whether claims of broad interest are supported.

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

## J3 — Writing quality, logic, and overclaiming

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
results, generalization beyond tested conditions.

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

---

# COVERAGE TABLE (final acceptance gate)

| check | disposition | basis |
|---|---|---|
| M1 | N findings / clean / unable — reason | artifact M1_acronyms.md, N rows |
| ... | ... | ... |
| J4 | ... | locations examined |

"Not checked" is not an allowed value. "Unable — <reason>" rows repeat in the
summary note with their reasons.

---

# THE DISPOSITION BAR (read before you fill any `disposition` cell)

A disposition is a DECISION about the row, not a sentence in its cell. Three
rules apply to every seeded table (M18, M19, M20, M4/NUMBERS_LEDGER, M8, M24,
GLOSSARY, IDENTIFIERS, PLACEHOLDERS, PLACEHOLDER_LOOKUP, OUTLINE):

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
against the manuscript, not against the letter).

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
not yet deposited).

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

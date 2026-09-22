# Discovery Round D0–D5 — nbt-review (Phase 3)

Purpose: the standard review runs fixed sweeps M1–M17 and judgment passes
J1–J4. Those are finite lists — the checklist itself can be incomplete. This
round hunts for issue CLASSES the checklist does not cover.

It cannot prove completeness; its deliverables are (a) executed checks for
uncovered classes, (b) new findings with IDs `X-*`, and (c) proposed new
sweeps that improve the next checklist run. Run it only AFTER the standard
Phase 2 sweeps.

**Inputs:**
- `SUBMISSION_DIR` = the reviewed directory (default `./non-revised`)
- `PRIOR` = `./review/findings.json` (canonical prior findings; also `./review/findings.md`)
- `WORK` = `./review/work` — converted corpus from the prior run; REUSE it (reconvert only missing files)
- `OUT2` = `./review/round2` (create it; ALL outputs here)

If PRIOR is missing, STOP and tell the user to run the standard review first.

**Hard rules (unchanged):** identification only — never edit submission files;
never invent; unresolvable → `unresolvable — manual verification required`;
unverifiable guideline rule → `guideline-dependent`; no silent skips — every
enumerated item gets a disposition; one finding per instance; prefer scripts
over attention.

## D0 — Dedup base

From PRIOR build two indexes (`OUT2/known_index.md`):
- **KNOWN-CLASSES**: the 28 check IDs (M1–M24, J1–J4) with one-line descriptions.
- **KNOWN-INSTANCES**: every prior finding as `id | class | location | evidence quote`.

Anything matching a KNOWN-INSTANCE (same class + same location + same
substance) is NOT reportable — it is already known. Same location, different
substance → reportable, with a "related to F-xxx" note.

## D1 — Checklist gap analysis (artifact: `OUT2/gap_table.md`)

For EACH category 0–5, enumerate issue types an editor/reviewer/copyeditor
could encounter. Mark each row COVERED (by which check ID) or UNCOVERED.

Seed the table with these, then extend well beyond them (target ≥25 rows
total; if you stall, ask "what else?" twice more before stopping):

- author lists / affiliations / ORCID consistent across title page, cover letter, manuscript?
- Reporting Summary answers consistent with the manuscript (n, tests, replication)?
- figure files actually match their legends (panel count, axis labels)?
- methods-ordering conventions; Results-statement order matches figure order?
- supplementary file naming consistent with call-outs?
- statistics reported identically in text, legends, and tables?
- cover letter addressed to the right journal? References the right manuscript title?
- manuscript title identical on title page, header, cover letter, abstract page?
- keywords/subject terms present where the journal wants them?
- blinding/ethics statements where a reviewer would demand them?
- data-availability links resolvable (format check, not fetch)?
- figure resolution/dimension signals in filenames or metadata?
- funding numbers and grant IDs consistent with acknowledgements?
- reference list cut off mid-entry? Trailing placeholder entries?
- abbreviation list present if the journal requests one?

The rows are questions about issue CLASSES, not instances — instances come
from probes.

## D2 — Probe design (artifact: `OUT2/probes.md`)

Convert every UNCOVERED gap row into a concrete, executable probe: a question
that can be answered by inspecting enumerated evidence from the corpus, with
the exact files/regions to inspect and the extraction to run (script where
possible). Each probe row: probe ID (P2-001…) | gap row | question | evidence
source | status (pending/executed/unable — reason). A gap row that cannot be
converted into a probe is itself a finding class ("analysis limitation"),
recorded, not silently dropped.

## D3 — Probe execution & anomaly hunting (artifact: `OUT2/probe_results.md`)

Execute every probe. Additionally run open-ended anomaly hunts over the
corpus, because unknown unknowns resist checklisting:

- **Expected-but-absent**: values/labels the manuscript's own logic requires
  but that never appear (e.g., a two-group comparison never reporting a test;
  an n stated for one cohort but absent for the other; an error bar defined
  for some panels but not others).
- **Present-but-unexpected**: tokens appearing where they shouldn't (numbers
  inside prose that duplicate table entries inconsistently; internal review
  language; a paragraph that answers a reviewer question from an old round).
- **Boundary probes**: first/last lines of every section; every heading;
  every figure legend's first and last sentence (these carry structural
  information and are disproportionately error-prone).

Record EVERY probe result with a disposition — a probe that found nothing
records "no anomalies — checked: <locations>". Probes are judgment work, but
their coverage is still enumerated.

## D4 — New findings (outputs: `OUT2/findings_extra.md` + `findings_extra.json`)

Every new issue found gets an `X-001`… ID (separate namespace from `F-*`, so
nbt-revise can merge both without collisions), formatted exactly like a
standard finding (location, category, check = the gap-row class label,
severity, evidence quote, explanation, status). Dedup per D0. Related prior
findings get the "related to F-xxx" note.

## D5 — New-sweep proposals (output: `OUT2/new_sweeps.md`)

For every issue CLASS that recurred or that a probe caught only by accident,
write a proposed sweep definition in the exact format of sweeps.md (purpose ·
enumeration procedure · artifact columns · finding rules) so the next review
run catches it mechanically:

```
## M25 — <name> (proposed)
**Purpose:** ...
**Enumeration:** <script or manual procedure — must be enumerable>
**Artifact:** M25_<slug>.md: <columns>
**Finding rules:** one per instance, listed
```

Number proposals continuing from the highest existing sweep number. M18
(figure-legend length, always enumerated with an optional proxy cap), M19
(abstract/main-text length plus the user's cover-letter preference) and M20
(OOXML style/formatting uniformity, enumerated by the pipeline's code-side scan)
are reserved and defined in `sweeps.md`, and M21–M24 were adopted from earlier
discovery rounds there, so proposals start at M25.
These are PROPOSALS: the user validates them; only validated ones get
appended to `references/sweeps.md`. This is the feedback loop — no static
checklist can be complete, but each discovered miss converts into a permanent
mechanical check, so the checklist converges toward exhaustiveness across
runs instead of pretending completeness on day one.

## Round-2 output summary (`OUT2/round2_summary.md`)

Counts: gap rows (covered/uncovered), probes (executed/clean/findings/unable),
X-findings by category/severity, proposed sweeps. Manual-verification list.
Statement of what this round could NOT check (honest limits).

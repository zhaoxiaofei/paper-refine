# NBT round-based revision pipeline

`nbt_pipeline.py` drives a **round-based, content-addressed revision loop** for a
Nature Biotechnology manuscript package. Each round produces several candidate
versions (rewrites, a reviewed-and-revised version, integrations that merge the
whole pool), judges them blindly against each other, pins the champion by
content digest, and feeds that champion into the next round. `decide` publishes
the final decision report and a clean, ready-to-use package.

The repository also carries the two companion tools the pipeline uses:

* **`nbt_docx_format.py`** — the code-side OOXML style/formatting scanner and
  normalizer (blank pages, running head on the title page, legend spacing,
  heading style drift, unintended italics, URL/email treatment, quotation
  marks, em-dash density).
* **`nbt_redlines_adapter.py`** — the tracked-changes bridge to
  `python-redlines[docxodus]` (or `docx-trackdiff`).

## Requirements

* Python 3.9+ (the pipeline and both companion tools are standard-library only).
* An agent CLI for the stage sessions: `codex` (default), `claude`, or a custom
  command via `--agent-cmd`; `--agent manual` stages prompts for a human.
* Optional, probed at runtime and never required: the `docx` CLI (read/render/
  diff/validate), a .docx→PDF converter (the `docx-converter` MCP tool,
  `docx2pdf.sh` + Word, `docx render`, LibreOffice, `pandoc`), `pdftotext`/
  `pdftoppm`, and the `zot` CLI for read-only Zotero reference resolution.

## Quick start

```bash
# 1. create a pipeline root from the pristine submission directory
python nbt_pipeline.py setup --source /path/to/non-revised --root ./nbt_rounds

# 2. run all rounds and decide (or run + decide as separate steps)
python nbt_pipeline.py run-decide --root ./nbt_rounds
#   python nbt_pipeline.py run    --root ./nbt_rounds
#   python nbt_pipeline.py decide --root ./nbt_rounds

# 3. inspect
#   ./nbt_rounds/reports/DECISION_REPORT.md
#   ./nbt_rounds/reports/decision.json
#   ./nbt_rounds/round<r>_winner/          the champion of each round
#   ./nbt_rounds/final_clean_version/      the champion, renamed for the next run
```

Useful flags: `--rounds N`, `--judges N[,N…]`, `--rewrites M[,M…]`,
`--revises N[,N…]`, `--integrators MASK[,MASK…]`,
`--jobs N`, `--agent {codex,claude,manual}`, `--agent-cmd JSON`, `--retries N`,
`--poll S` (manual mode), `--no-redline`, `run --only 1,2` (only rounds 1 and
2; see *Running only some of the steps*). Setup-time policy flags:
`--audit {off,on}` (the auditor stage), `--placeholder-lookup {off,online}`
(resolve searchable hand-off markers before the sessions run),
`--strict-artifacts [on|fix|off]` (what a boilerplate or unfilled decision table
does to an attempt: `on` fails it, `fix` first spends one scoped repair session
on it, `off` only records the report -- see *Attempt history* below);
`decide --residual-gate` refuses to certify a champion that still carries a
residual the pipeline can see.

## The auditor (`setup --audit on`): review → **audit** → revise

The review is one session that reads a whole corpus and then disposes hundreds
of code-side rows. Its two documented failure modes are (1) closing a row with a
reason that is not about that row's bar ("no journal rule", "editorial
preference only") and (2) closing MANY rows with the SAME sentence. In a real
run, 96 scan rows were closed with one identical sentence — and the sentences
the operator later flagged were inside that pile.

`--audit on` inserts one independent session between the reviewer and the
revisers. It never edits a package; its product is the decision record
(`audit/audit.json` + `audit/AUDIT.md`):

* **every frozen finding is disposed**: `confirm`, or `drop` WITH a reason and
  evidence (the verbatim text or the file:line derivation that refutes it).
  Silence about an id is a failed attempt — an undecidable finding must be
  confirmed, because dropping it would hide it from the reviser;
* it **attacks the reviewer's dispositions**: every finding-tier row the
  reviewer closed as `OK` is re-checked against its own bar, and a real defect
  becomes a new `AU-*` finding;
* the revisers consume the **audited** list (frozen − drops + `AU-*` adds) and
  the drops stay visible to the human in `audit/audit.json`, so a drop is always
  re-checkable and reversible;
* the auditor's own artifacts pass the same disposition-quality detectors as the
  reviewer's (see below).

The stage is **off by default** so that existing roots keep their plan shape and
their arms stay comparable; turn it on when you want the extra decision layer
(it costs one session per round, not per candidate).

## Arm levels, the difference ledger, and the language pass (W-11/W-12)

* **Rewrite arms carry a level.** With `--rewrites 2` the round stages one
  `structural` arm (section/paragraph order, narrative flow, headings,
  transitions — declared in `REWRITE_REPORT.md → ## ORGANIZATION MAP`) and one
  `sentence` arm (same organization, sentence-level clarity/precision/terminology
  work). The pool then holds large *and* small differences, so the integration
  stage weighs a reorganization against a prose improvement instead of a taste
  contest. `postcheck_rewrite` records the level and rejects a report that
  declares the wrong one.
* **The integration difference ledger needs an artifact per row.**
  `integrated/DIFF_LEDGER.md` rows carry `size` (small = wording, large =
  organization), `artifact` (a before/after pair under `integrated/work/diffs/`
  for a small row, the outline diff for a large row) and `finding effect`
  (`preserves F-00x` / `undoes F-00x` / `none`). The postcheck reports rows
  without an artifact, missing size classes when the pool has both levels,
  donors missing from the table, and any port that would undo a resolved
  finding.
* **No stage may introduce a NEW class of defect.** Every package-producing stage
  is re-scanned against the package it started from, per finding-tier family: a
  family the input had none of and the output now has (a new mega-paragraph, a
  new nested parenthesis, a new value+unit outside siunitx, a new abstract
  sentence past its bar) FAILS the attempt with the offending rule named; growth
  inside a family that was already present is a warning.
* **The L1–L11 language pass runs in every package-producing stage** (rewrite,
  revise, integrate), not only in the revision arm: one row per change plus one
  coverage row per step in `work/R6_language.md`, and a code-side re-scan of the
  package after each step. A missing artifact or an uncovered step is recorded
  (and fails the attempt under `--strict-artifacts`).
* **The judge scores prose against a named rubric.** The `writing` tier's rows
  cite one of twelve checks (Q1–Q12: premise, logic slip, logic jump, coherence,
  unexplained prerequisite, redundancy, non-academic wording, register, stiff
  phrasing, grammar, typography, segmentation) with a quote and the intended
  reading. The tier stays minor-only, and the rubric carries no provenance
  vocabulary, so the panel stays blind.

## Provenance, identifiers and the residual gate

Every non-judge sandbox now also receives a code-side **provenance pack**
(`work/` and, for the review, `review/artifacts/`):

| artifact | what it carries |
|---|---|
| `NUMBERS_LEDGER.md` | every numeric literal, with the `source` the CODE could PROVE from a shipped data table (a column sum/min/max or a single cell — e.g. `45,365` = the sum of `n_cells_total`). A row whose source stays empty is the session's job |
| `IDENTIFIERS.md` | every DOI / SRA-BioProject-GEO accession / repository URL+commit / ORCID, with the orchestrator's own public-API verdict (`found` / `absent` / `error` / `skipped`) |
| `PLACEHOLDER_LOOKUP.md` | the answers the pipeline already found for the `searchable` hand-off markers (`found` = the fact; `absent` = a VERIFIED NEGATIVE such as "not posted"). A marker this table answers may not ship |
| `M24_concepts.md` + `GLOSSARY.md` | two term families competing for one concept (CN vs CNV vs CNA, simulate vs emulate, rank vs score), with counts per surface form, and the term decisions to conform to |

The lookups run through a cached probe (`reports/LOOKUP_CACHE.json`, 14-day TTL):
one cheap probe per process decides whether to query at all, results are reused
across the sandboxes of a root, and `--placeholder-lookup off` records the
questions and checks nothing (useful offline).

`decide --residual-gate` turns the recorded residuals into decision problems
(exit 5): a `searchable` marker the lookup engine answered that still sits in a
delivered package, a review whose decision tables were boilerplate or unfilled,
or unsourced numbers in the abstract/legends. Without the flag the residuals are
still recorded in `decision.json` and printed — never silently dropped.

## Round model

For every round `r` the plan is `A1_r + M rewrites + 1 review + N revises +
K = 1+M+N integrations + the judge panel`:

| stage | id(s) | what it does |
|---|---|---|
| `a1` | `r<r>_a1` | the round's base: round 1 is the pristine copy, later rounds the previous champion (no agent) |
| `rewrite` | `r<r>_w1…wM` | full alternative versions with a **declared level**: odd arms are `structural` (organization-level, reported in `## ORGANIZATION MAP`), even arms are `sentence` (same organization, prose-level). With M≥2 the round therefore carries BOTH kinds of difference for the integration stage to weigh |
| `review` | `r<r>_review` | ONE frozen identification pass (`$nbt-review`) that feeds every revise session |
| `audit` | `r<r>_audit` | **optional** (`setup --audit on`): an INDEPENDENT AUDITOR between the reviewer and the revisers — it disposes every frozen finding (confirm, or drop WITH evidence), promotes the reviewer's boilerplate `OK` closures of finding-tier rows into real `AU-*` findings, and hands the AUDITED list to the revision arms |
| `revise` | `r<r>_a2…a{1+N}` | reviewed-and-revised versions that consume the frozen review (or the audited list, when the auditor ran) |
| `integrate` | `r<r>_i1…iK` | "merge from the other versions": every pool member SELECTED by the round's `--integrators` mask reworked with the WHOLE pool as donors (the default mask 0xFFFFFFFF selects all K = 1+M+N members) |
| `judge` | `judge_t…_j…` | blind pairwise panels over the round's field (the id is an opaque token: it carries no round and no arm) |

Each run keeps its sandbox under `runs/<id>/` (`base/`, `review/`, the stage's
own output directory, `PROMPT.md`, `_pipeline_done.json`). Completion is a
marker file, never "the directory is non-empty"; every published winner and pin
is verified against the digest of the corpus the judges actually scored.

## Running only some of the steps

`run --only <selection>` drives only the selected part of the pipeline in that
invocation; everything else is left pending, and a round whose other stages have
not run stays incomplete until they do. Resume at any time with a later `run`,
another `--only`, or `retry --run <ID>` (which resets one run so a COMPLETED
stage can run again).

The selection items are comma-separated and combine as a **union**:

* a **round ordinal** or range — `--only 1,2` runs only the first and second
  rounds, every stage; `--only 1-3` is the same for rounds 1..3;
* a **stage name** — the stage in every round: `rewrite`, `review`, `audit`,
  `revise`, `integrate`, `judge`, plus the aliases `w`, `a`/`a2`, `i`, `merge`,
  `j` (plurals work too);
* **`ROUND:STAGE`** — one stage of one round (`2:merge`, `3:judge`;
  `.`/`/` separate as well, and `all` stands for every stage, e.g. `2:all`);
* **one agent SESSION** — the session, not its whole stage: `rewriter2` (only
  `w2`), `integrator1` (only `i1`), `reviser1` (only `a2`, the first revise arm
  — the pipeline numbers its revise arms from `a2`, because `a1` is the round's
  base copy), `reviewer` (review session A; `review_b` is session B under
  `--review-split`) and `audit`. A round-qualified `r1_w2` / `2:w2` (also
  `2:rewriter2`) restricts it to that round; a bare `w2` applies to every round
  that has it. Only that session is materialized — no other stage, and no judge
  wave, starts in that invocation. `a1` and `orig` cannot be selected: `a1` is
  the orchestrator's copy of the previous champion, `orig` the pristine
  submission, and neither is an agent session;
* **one judge SESSION** — `r1_judge_w2_j1` (round 1, version `w2`, judge 1), also
  written `1:judge_w2_j1`; `r1_judge_w2` is every judge of that version, and a
  version without a round (`w2_j1`, `i1_j2`, `orig_j1`) applies to every round
  that has it (a bare index, `judge1`/`j1`, is judge 1 of every version). Only
  the listed sessions get a sandbox/session/sheet; each
  version's panel expectation is recomputed from the sessions that remain
  (`J(V)*(|field|-1) + Σ J(other versions)`), so a pilot panel still decides the
  round, the selector is recorded on the round's plan (so `decide` recomputes the
  panel the round was actually judged with), and a later invocation of the same
  pending round remembers it — an explicit bare `--only judge` clears it and runs
  the whole panel. An unknown round, version or judge index is refused before
  anything starts, with the values that exist.

```bash
python nbt_pipeline.py run --root ./nbt_rounds --only 1,2        # only rounds 1 and 2
python nbt_pipeline.py run --root ./nbt_rounds --only 2:review   # round 2's review only
python nbt_pipeline.py run --root ./nbt_rounds --only review
python nbt_pipeline.py run --root ./nbt_rounds --only revise
python nbt_pipeline.py run --root ./nbt_rounds --only merge      # = integrate
python nbt_pipeline.py run --root ./nbt_rounds --only judge
python nbt_pipeline.py run --root ./nbt_rounds --only review,revise
python nbt_pipeline.py run --root ./nbt_rounds --only 1,2:merge,3:judge
python nbt_pipeline.py run --root ./nbt_rounds --only rewriter2   # ONLY w2 (not w1)
python nbt_pipeline.py run --root ./nbt_rounds --only integrator1 # ONLY the i1 arm
python nbt_pipeline.py run --root ./nbt_rounds --only r1_w2       # round 1's w2 only
python nbt_pipeline.py run --root ./nbt_rounds --only w2,r2_a2    # w2 everywhere + round 2's a2
python nbt_pipeline.py run --root ./nbt_rounds --only r1_judge_w2_j1   # ONE judge session
python nbt_pipeline.py run --root ./nbt_rounds --only r1_judge_w2_j1,r2_judge_i1_j1
```

`all` (the default) means every round and every stage. An out-of-range round
(`--only 7` in a 2-round pipeline) is refused immediately. Asking for a round
whose predecessor is not finished (round 2 consumes round 1's pinned champion)
is reported as the unmet dependency it is, and nothing is started. A plain
`run` continues whatever is still pending; `run-decide` accepts the same flag
and then decides. A session item the round's plan cannot satisfy (a typo like
`integrator9`, or an arm a round's `--integrators` mask leaves out) is refused
before anything starts, naming the sessions that round does plan.

### Listing the agent sessions before a run

`agents --root <dir>` prints the session names every round will run, without
starting anything (a dry plan: no sandbox is materialized, no agent is launched,
no document is hashed — it costs a few sha256 calls over the plan, well under a
second on any root):

```bash
python nbt_pipeline.py agents --root ./nbt_rounds                 # every planned session
python nbt_pipeline.py agents --root ./nbt_rounds --pending       # only what may still run
python nbt_pipeline.py agents --root ./nbt_rounds --only rewriter2    # preview a filtered run
python nbt_pipeline.py agents --root ./nbt_rounds --json          # machine-readable
```

Per round it lists the base copy `a1` (no agent), each `w<k>`, the review
(`review`, plus `review_b` with `--review-split`), the `audit`, each revise arm
`a<k>` and each integration arm `i<k>` the round's mask selected, then every
judge session `judge_<token>_j<k>` with the version it judges. The producing
names are exact. The judge id is the **salted per-version token** (so it carries
no provenance) derived from `(round, version id)`; the judge FIELD, however, is
deduplicated by document CONTENT once every arm exists, so a pending round's
judge ids are the *candidates*: a member whose package is content-identical to
another member's is dropped before judging and its sessions never start (the
command says so). Once the round has run, the same command lists exactly the
sessions that ran — which is also how you get a judge id for `retry --run <ID>`.

### Running only some judge sessions

`--judges` says HOW MANY judges each version gets; `run --only` says WHICH of
those sessions run in that invocation (see *Running only some of the steps*) — a
cheap pilot of the panel before paying for the whole thing:

```bash
run --only r1_judge_w2_j1                    # one session: round 1, w2, judge 1
run --only r2_judge_i1_j1                    # round 2's first integration arm
run --only r1_judge_w2_j1,r1_judge_w2_j2     # two of w2's three judges
```

The selector is a **whitelist** (no selector = every session, the default):
`r<round>[_judge_<version>[_j<index>]]`, also accepted as `1:judge_w2_j1`. A
missing index means every judge of that version, a missing version every version
of that round, and a missing round every round that has the version (`w2_j2`,
`j1`). A version name is any judgeable id — `orig`, `a1`, `w1`…, `a2`…, or an
integration arm `i1`… — and an unknown round/version/index is refused before
anything starts, with the values that exist.

The same session may be spelled with the version id alone plus the judge suffix
(`r1_w2_j1`, `r2_i1_j2`, `w2_j2`) — the round-qualified form keeps its round
even when the rounds have different `--judges` counts — and the friendly
class+index spellings work here too (`r1_rewriter2_j1`, `r2_integrator1_j2`).
`agents --root <dir> --only <selector>` shows the ids before anything starts.

Only the selected sessions get a sandbox, a session and a sheet, and each
version's panel expectation is adjusted to the sessions that remain
(`expected = J(version)*(|field|-1) + Σ J(other versions)`), so the round still
decides on the smaller panel rather than reporting a gap; a sheet for a session
the selector does not enable is ignored with a diagnostic (also when the config
was edited after some sheets were written). The selector is recorded on the
round's plan, so `decide` recomputes the panel the round was actually judged
with, and `status`/`DECISION_REPORT.md` show it (`judges/version=3, enabled=…`);
a later invocation of the same pending round remembers it, while a bare
`--only judge` clears it and runs the whole panel.

## Per-round judges and integrators

Both are per-round command-line parameters with the same list rules as
`--rewrites`/`--revises` (one integer applies to every round; a shorter list is
extended by repeating its last element; a longer one is truncated):

* `setup --judges 3,1` runs **3 judge sessions per version in round 1 and 1 in
  round 2**. Each round's panel is complete only when every field member
  carries its own round's `2*judges*(|field|-1)` directed scores, and the
  decision report prints the per-round counts. Bump the final round when the
  earlier rounds are for triage, or lower it to make a long run affordable.
* `setup --integrators 0x5,0xFFFFFFFF` is a **32-bit mask per round** selecting
  which agents run an integration session. Bit `k-1` belongs to the k-th member
  of the round's pool `[a1, w1..wM, a2..a{1+N}]`, so in a round with M=2, N=1
  (`pool = a1, w1, w2, a2`): `0x5` = bits 0 and 2 = only `i1` (a1 reworked) and
  `i3` (w2 reworked) run; `0x0` runs no integration at all and the round's
  field is the pool alone; the default `0xFFFFFFFF` means **every applicable
  agent** (bits beyond the pool size are ignored, so the default keeps selecting
  the whole pool whatever M and N are). A skipped arm costs no session, is never
  judged and can never win — the round's recorded plan, the run log and
  `DECISION_REPORT.md` all name the arms the mask left out.

Masks accept decimal (`5`), hex (`0x5`, the documented default form) and the
other Python integer-literal forms. A pool wider than 32 members cannot be
addressed by the mask and is refused at setup. Like `--rewrites`/`--revises`,
all four are `setup` parameters recorded in `pipeline_config.json` (and mirrored
into `state.json`); edit the file to change a not-yet-finished round's plan, and
note that a round already decided keeps the plan it was decided with.

## Style/formatting checks and repairs

The corpus converters read DOCX **text only**, so layout and character
formatting used to be invisible to every stage. The pipeline now handles it:

* `setup` scans the source (`state.original_format`, printed as
  `[setup] OOXML formatting scan:`), copies `nbt_docx_format.py` into the root,
  and — unless `--format-fix off` is given — **normalizes the pristine copy**
  before anything is fingerprinted (text identity verified by the fixer; the
  operator's `--source` directory is never modified).
* every package-producing stage (`rewrite`/`revise`/`integrate`) normalizes its
  candidate in the postcheck, i.e. **before** the corpus digest, the pins, the
  judge views and the next round's base are built. The repair is reported as a
  `FORMAT-FIX: …` warning and recorded in
  `runs/<id>/FORMAT_FIX_<run>.json` (with before/after scans).
* the review stage receives a seeded `review/work/FORMAT_SCAN.json` plus
  `review/artifacts/M20_formatting.md` (one row per finding to dispose) and the
  review contract requires an `M20` coverage row, like M18/M19.
* `decide` re-scans the winner, reports it in `decision.json` /
  `DECISION_REPORT.md`, and `publish_final_clean` normalizes + verifies the
  published `final_clean_version/` copy.
* `decide --format-gate` promotes HIGH-severity findings (break-only
  paragraph/blank page, tracked changes, unreadable package) to decision
  problems (exit 5). The scan stays advisory without the flag.

Policy overrides (`setup --format-policy policy.json`): `journal_italics`,
`quote_style`, `caption_line`, `caption_space`, `title_page_header`,
`url_style`, `max_em_dashes_per_1000`, `unlink_zotero_fields`,
`align_heading_sizes`, `blank_page_tolerance`.

Stand-alone use (never edits in place unless you pass `--out` yourself):

```bash
python nbt_docx_format.py scan  <dir> --pdf <rendered.pdf> --json out.json
python nbt_docx_format.py fix   file.docx --out file.fixed.docx
python nbt_docx_format.py check-pdf rendered.pdf
```

Findings inside Zotero fields (the bibliography, citation fields) are reported
`field-protected`: Word cannot restyle a field result persistently. Fix the CSL
style, or set `"unlink_zotero_fields": true` in the policy for a submission copy
where the reference list becomes plain text.

### Journal / emphasis consistency (M20, rules FMT-T6c–T6g)

Character formatting that lives in a **style** used to be invisible: the scanner
read only a run's own `<w:i/>`, so a journal name italicised through Word's
`Emphasis` *character style* looked identical to roman text. On a real cover
letter that produced `Nature Biotechnology` italic in two sentences and roman in
the others, and `Nature Methods and other leading journals` emphasised as one
unit. The scanner now resolves the full precedence — direct run properties >
character style > paragraph style > document defaults (`w:i` and `w:iCs`,
including explicit `val="0"` off-switches) — and adds four rules on top of the
existing italic checks:

| rule | finding | fix (policy `journal_italics`) |
|---|---|---|
| `FMT-T6c` | a journal name is italic outside the reference list (`refs-only`/`off`) | pins the run roman with a direct `w:i val="0"` override that beats the character style |
| `FMT-T6f` | an emphasis span continues past the journal title onto ordinary lowercase prose (`… and other leading journals`) | pins the continuation runs roman |
| `FMT-T6e` | the same journal name is italic in one place and roman in another (reported per region: body text vs reference list) | the per-run rules above/below resolve it; the row itself is a report |
| `FMT-T6g` | a reference-list journal title is left roman (`refs-only`/`everywhere`; or in body text under `everywhere`) | makes the title run italic, but only when the run IS the title (a run that also carries volume/pages is reported, never re-styled) |

Guard rails: journal-like words inside ordinary prose, hyphenated compounds and
URLs (`Cell-line`, `(Single-Cell)`, `github.com/…/Single-Cell-…`) are not
journal titles; a title keeps its capitals (`Cell Syst.`, `Cell Rep. Methods`),
prose is lowercase, so the run-on rule never eats an abbreviated title; and a
legitimate italic in body text (`de novo`) is left alone. Runs inside Zotero
fields stay `field-protected` unless `unlink_zotero_fields` is set.

Every scan also carries a **font/paragraph-style inventory** (`style_survey` in
the JSON: fonts and sizes in use, paragraph styles, character styles, and how
many runs are italic via direct formatting vs a character style vs the paragraph
style). It rides along in `FORMAT_SCAN.json`, `CODE_SCANS.json` and the M20
artifact, so a visually observed font/style oddity can be traced to the OOXML
that produced it.

Verification of a repair is code-side and visual: the fixer re-scans the output
(all mechanical rules must be gone), asserts the document TEXT is unchanged and
every other package part is byte-identical, runs `docx validate` when available,
and the rendered page pass (`check-pdf`, the agents' `VIS_visual` record) covers
what OOXML inspection cannot see.

### Text-level consistency across the whole package (rules FMT-T8a–T8e and FMT-T9c/T9f/T9g/T9i/T9j)

Some consistency problems are not OOXML at all — they are in the text — and they
now run over every `.docx` AND every `.tex/.ltx/.md/.txt` source, so a problem is
found in the cover letter, the main text and the supplementary alike:

| rule | finding | action |
|---|---|---|
| `FMT-T9c` | long sentence or long list-paragraph, **section-tiered**: 40 words in a cover letter/abstract/legend, 46 in the body, 61 in Methods; `>=3` enumerated items inside a `>200`-word paragraph | finding (finding-tier); the reviewer must dispose it against that bar |
| `FMT-T9f` | a term the manuscript glosses in place ("X (Y, which …)": `average spot length (sequencing read length, …)`) | finding: use the standard term, or keep the gloss as a recorded decision |
| `FMT-T9g` | a LaTeX value+unit outside siunitx (`\qty{}{}` / `\SI{}{}`, `\num{}` for bare numbers; both spellings accepted) | finding; `\code{}`, verbatim, URLs, `\cite`, cross-references, inline math and generated tables are exempt |
| `FMT-T9i` | a mega-paragraph (`>250` words, non-Methods) | finding: split it at the natural boundary |
| `FMT-T9j` | two term families competing for one concept (CN/CNV/CNA, simulate/emulate) | finding: fix one term per concept in `GLOSSARY.md` |
| `FMT-T8a` | a document mixes citation formats (`(Author et al., 2015, Nature Methods)` vs `(Author et al., Nature Methods, 2015)` vs `(Author et al., 2015)`) | report; with `citation_journal_names="drop"` (default) the redundant journal segment is deleted, leaving one author-year format. Reported only when an odd form cannot be matched safely |
| `FMT-T8b` | nested parentheses (`(… (BAF))`) | finding-tier — moving the inner item out is a wording decision the revision stage makes; mathematical calls like `T(·,·)` are excluded |
| `FMT-T8c` | a distinctive term repeated in one short passage (`Nature Biotechnology` five times in a cover letter) | finding-tier redundancy: a proper name ≥3× in one paragraph, or a long content word ≥5×, must be varied or dropped — a writing-quality defect does not need a journal rule to exist. Deliberately narrow: proper names (2–3 capitalized words, no document-structure word) and single long content words |
| `FMT-T8d` | US/UK spelling variants in body text (`tumour` … `tumor`) | report; `term_spelling="dominant"` (default) normalizes the minority form outside the reference list |
| `FMT-T8e` | an attributive compound hyphenated in one place and not in another (`copy-number profiles` … `copy number estimate`) | report; `term_hyphenation="dominant"` (default) hyphenates the minority attributive form |

Guard rails: the reference list is never rewritten (its titles are quotations),
URLs/DOIs/e-mails are masked, `Table S1` inside `Supplementary Table S1` is not a
variant, and the citation/spelling/hyphenation fixes record every text edit —
the fixer's verification then proves that NOTHING beyond those recorded edits
changed (`verified.text_diff_only_recorded_edits`).

### Deliverable validation (DOCX XML + LaTeX), by the agents and by the pipeline

An invalid file is not a deliverable, so every EDITING session (rewrite, revise,
integrate) has to validate what it produced:

```bash
python nbt_docx_format.py validate <package dir>   # module sits next to PROMPT.md
```

It checks every `.docx` (readable zip, EVERY XML/`.rels` part parses, `docx
validate` schema check when the CLI is installed) and compiles every STANDALONE
`.tex` (`\documentclass`) in a scratch copy — `\input` fragments are validated
through the document that inputs them, and a missing TeX engine is reported as
SKIP, never as a failure. The prompt tells the agent to iterate at most three
times and, if it still fails, to leave the package as it is and record the exact
file, command and engine error in the manual-steps list.

The orchestrator does not trust that loop: the stage postchecks run the same
validator on the produced package and record the result on the run
(`rec["validation"]`). A malformed `.docx` fails the attempt, and a LaTeX
document that no longer compiles fails it too — but only when the package the
stage started from DID compile, so an author's pre-existing LaTeX breakage is
reported, never punished. A failed attempt goes through the normal retry policy
(`--retries`), which is the hard cap on the loop. The public, stateless module is
copied next to `PROMPT.md` in every session sandbox (including the judge's, whose
prompt names the same command); it carries no per-run data, and the judge's copy
is stamped with the view timestamp.

## The code-side evidence pack (identical numbers in every session)

Every session is seeded with the orchestrator's own measurements of its corpus,
so the review, the rewritten/revised/integrated packages and the judge panel
cannot disagree about a number:

| artifact | what it holds |
|---|---|
| `CODE_SCANS.json` | M18 legend counts, M19 abstract/main-text lengths, M20 OOXML formatting rows, the hand-off placeholder count and the corpus identity (digest, file list, revision token) |
| `EVIDENCE_PACK.md` | the same, human-readable, with the re-scan command |
| `M18_caption_words.md`, `M19_length.md`, `M20_formatting.md` | seeded tables (one row per code-side finding, empty disposition column) for the review and the judge |
| `CODE_SCANS_before.json` / `CODE_SCANS_after.json` | per stage: the input's and the delivered package's measurements, with an `evidence_delta` (over-cap sections, placeholders, formatting rows) recorded on the run and warned about when it regresses |

Where it lands: `review/work/` + `review/artifacts/` (review) and `work/` at the
sandbox root (rewrite/revise/integrate, scanned from the package the stage is
about to edit). An `EVIDENCE_PACK.md` also sits next to `PROMPT.md` and inside
the session's OUT directory. Those four prompts carry the same block: use these
numbers instead of re-estimating, dispose or reconcile every seeded row in your
own artifact, and state before → after numbers whenever your work changes one of
them.

**The judge gets none of it — blinding is absolute.** A judge sandbox contains
only the blinded views (`target/`, `field/<label>/`, `original/`) and the prompt;
no review findings, no change ledger, no orchestrator scan, no digest or
revision token, no pre-computed M18/M19/M20 rows. Even a scan computed from the
judge's *own* target would be a pre-digested view (and a digest it could
correlate), so the judge prompt instead carries a BLINDING RULE: derive every
measurement yourself from the packages in front of you with the same public
tool (`python nbt_docx_format.py scan target/`) and record the rows in
`judge_review/artifacts/`. Consistency is then checked from the orchestrator's
side: after a judge run, `postcheck_judge` re-scans that blinded target itself,
records it in `reports/judge_evidence_<run>.json` and the run record, and warns
(never fails) when the judge produced no corresponding artifact table. The
panel's numbers stay auditable without the judge ever being handed an answer
key.

What a judge can see is submission content only, and every other channel is
closed by construction:

| channel | what a judge view does |
|---|---|
| file names / labels | every view is a salted per-view permutation of `d01/`, `f0001<ext>` placeholders, so the same document has a different name in `target/`, in each `field/<label>/` and in `original/`; the label → version map lives only in the run record |
| run ids | `judge_<token>_j<k>` is an opaque token derived from (round, target, salt): no round prefix, no arm name, not recomputable without the root secret |
| timestamps / modes | one mtime and one mode for the whole session, identical across all its views (nothing to order the packages by) |
| auxiliary files | revision auxiliaries (`*.tracked.docx`, `*.before-after.docx`), the pipeline's bookkeeping/report files (`CHANGELOG.md`, `MANUAL_STEPS.md`, `REVISION_REPORT.md`, `revision_report.json`, `DIFF_LEDGER.md`, `VISUAL_CHECK.md`), the `work/` scratch and Word's `~$name.docx` owner file never reach a view |
| derived outputs | a judge is handed the SOURCES, never what can be compiled from them: the build by-products of an editable source (`.aux`, `.log`, `.toc`, `.synctex.gz`, …) are dropped -- a build log names the machine, its absolute paths and the exact build date, and a package an agent went over loses them while the untouched original keeps them, so their mere PRESENCE would say which package was worked on -- and so is any other derived file whose editable source ships beside it: a compiled `.bbl` next to its `.bib`, a rendered PDF next to its `.docx`/`.doc`/`.tex`/`.ltx` (same stem, version tokens ignored). The judge can compile or render the source itself. A derived file with NO source in the package stays, because it is then the only copy of the content: with no `.bib` shipped, a `.bbl` is the reference list |
| Word/PDF metadata | OOXML views are canonicalized (sorted entries, one fixed zip timestamp, core/app/custom properties blanked, `rsid`/`paraId`/`textId`/proofing/last-rendered-page markers and tracked-change author+date attributes stripped, tracked changes accepted, `docProps/thumbnail*` dropped, Word's cached Pages/Words/Characters zeroed); a PDF's `/Info`, `/ID` and uncompressed XMP identifying values are blanked in place |
| prompt / session | the judge prompt carries no round, arm, stage or provenance vocabulary (`round`, `arm`, `revise`, `integration`, `champion`, … all absent -- asserted by `test_judge_blinding.py`), no bookkeeping file name, and no hand-off marker token; the placeholder rule is stated in provenance-neutral wording |

Known limit: there is no OS-level jail, so a judge that ignores its prompt could
walk up out of its sandbox into the pipeline root. The prompt states the
restriction explicitly ("siblings and parent directories are off-limits … do
not go looking") and the orchestrator never rewards it: the panel's evidence is
re-derived from the blinded target outside the sandbox (`postcheck_judge`).

One consequence worth knowing: because a judge sees the sources, a *stale*
submitted PDF (a rendering that no longer matches the editable file beside it)
is no longer a judge finding -- the review/revise/integrate stages still see
every rendering and still flag it, and the shared derived-output rule below
still applies to them.

## One defect vocabulary, one artifact process

Every session classifies a defect the same way, so an improvement one session
sees is an improvement the panel can score. The block is generated from
`BASIS_TIERS` and inserted verbatim into all five prompts (review, rewrite,
revise, integrate, judge); the same table lives in the review skill
(`nbt-skills/nbt-review/references/sweeps.md`, mirrored in
`nbt-skills/prompts/identify_issues.prompt.md`) and in the revision ledger's
definition (`nbt-skills/nbt-revise/references/ledger.md`):

| review category | scored class (`correctness > consistency > preservation > completeness > formatting`) |
|---|---|
| 0 Editor/Reviewer concerns | `correctness` (unsupported claim, overclaim, rigor, ethics), `completeness` (required information missing) or `preservation` (removed content/limitation) |
| 1 Completeness & Factual Integrity | `correctness` (factual error, wrong number/DOI/reference key, broken cross-reference) or `completeness` (mandatory item missing) |
| 2 Writing Quality, Logic, Repetition | `consistency` (the same thing said/spelled/numbered two ways; a convention applied unevenly), `correctness` (the wording changes the meaning) or `formatting` (a one-off wording preference) |
| 3 Plagiarism / AI content | `correctness` (integrity of the content itself) |
| 4 Technical Formatting | `formatting` (M18/M19/M20; ≤ ±1 and never decisive alone) |
| 5 Missing / Unneeded Information | `completeness` |

Severity is shared too (CRITICAL / MAJOR / MINOR), and an improvement claim must
name the class and the concrete item behind it -- a difference that cannot be
named in this vocabulary is cosmetic and scores 0. What differs between sessions
is the *deliverable*, not the vocabulary: an identification session reports
findings and never scores, a comparison session scores one target against one
opponent and never ranks, and a package-producing session resolves findings in
its own copy and keeps one ledger row per finding.

The artifact *process* is shared as well; the differences are deliberate:

| artifacts | sessions | why this shape |
|---|---|---|
| `inventory.md` + `artifacts/M<id>_*.md` (ENUMERATE → ARTIFACT → AUDIT) + the M18/M19/M20 tables | review, judge | the judge runs the same frozen sweep set as the review; it must derive its own rows from the blinded packages |
| `work/CODE_SCANS.json` + `EVIDENCE_PACK.md` (the orchestrator's own M18/M19/M20/placeholder counts and corpus identity, from one set of functions) | review, rewrite, revise, integrate | one measurement of one corpus, so no session re-estimates a number; the scans use the same file-set rules as the pin and the judge view (`work/` scratch, auxiliaries, bookkeeping and derived outputs never counted) |
| nothing seeded at all; `postcheck_judge` re-scans the blinded target outside the sandbox | judge | a pre-computed row would be an answer key |
| `CHANGELOG.md` + `MANUAL_STEPS.md` inside the package | rewrite, revise, integrate | the package's own record of what changed and what the author must still do |
| `REVISION_REPORT.md` + `revision_report.json` (one row per frozen finding id) | revise, integrate | only these sessions are given findings to resolve |
| `scores.json` (signed comparison items with class + severity) | judge | only the panel scores |

**How a round is decided (one ranking key, every arm on the same terms):**
`-median`, `-mean` (breaks a median tie on the same flat directed-score list),
`IQR`, `critical_remaining`, `writing_remaining`, then the provenance-free
content digest and only after that the run id. `critical_remaining` and
`writing_remaining` are counts the *package-producing* session reports in its
completion marker -- CRITICAL-severity findings still open, and the frozen
review's category-2 (writing quality / logic / repetition) findings still open
-- so severity outranks style, and style can only separate versions the panel
statistics cannot. Both are cross-checked against the frozen review (the
revision arm is warned when it claims zero while the review lists such
findings), both are +inf when absent (absence never wins a tie), they are never
a score, a gate or a reason to make a version ineligible -- and the judge is
never asked for either number (blinding). An exact tie on `median`, `mean` and
`IQR` still keeps the incumbent base: a better writing count separates
challengers, it does not retire an incumbent the panel cannot distinguish from
them. `manual_steps`, caption lengths and hand-off placeholders are reported in
`DECISION_REPORT.md` / `decision.json` (the table has `critical` and `writing`
columns) but never ranked on.

## Attempt history: every attempt is kept, not just the last one

A run can be attempted several times (`--retries`, a fresh invocation, a
`retry`). Before this layer existed, the run record's `postcheck`/`last_error`
described only the FINAL attempt — the 2026-09-22 root showed a review failing on
the M1b gate while attempt 1's three real problems survived nowhere except the
text of attempt 2's prompt, and attempt 1's artifacts had already been destroyed
by the retry.

Now every attempt is recorded and its evidence is preserved:

| where | what it holds |
|---|---|
| `state.json` → `runs.<id>.attempts_log` | one entry per attempt: number, source (`postcheck` / `process` / `adopted` / `recheck` / `re-verify` / `manual`), timestamps, duration, status, the postcheck's errors and warnings, the decision-artifact quality report, the marker's own summary, and the paths of the attempt's archive and transcript (capped at 25 attempts per run, 60 messages each, 4 KB per message) |
| `runs/<run>_try<N>_failed/` | the FAILED TRY's whole sandbox, renamed there before the retry builds a fresh `runs/<run>/`: the deliverables exactly as the postcheck judged them, the corpus copies, the agent transcript and a self-describing `record.json` (which names the attempts whose work it holds — a stage attempt and, when the scoped repair ran in it, the repair session too). `prune` reclaims these with the round they belong to |
| `runs/_logs/<run>.<attempt…>.log` | transcripts of attempts whose sandbox was reset by a `retry` or a revalidation (a sandbox kept as `_try<N>_failed` keeps its own `_agent.log` inside) |

The console prints **all** of an attempt's problems (one per line, not a single
140-character cut) and the same complete list is handed to the NEXT attempt: the
retry prompt's `=== PREVIOUS ATTEMPT FAILED ===` block now names every error (no
four-message, 1200-character cut), the attempt's warnings, and where its kept
sandbox is — so one retry can fix all of them instead of rediscovering them one
per session. `status` and `DECISION_REPORT.md` list every failed attempt with its
first problem and the paths above, and `prune` reclaims the kept sandboxes of the
rounds it prunes — the attempt RECORDS stay in `state.json`, so the history
remains readable and says that the kept sandbox is gone.

A defect message is part of this record: a repeated disposition is now quoted in
full and names the rows it is about (`-- rows: <document> / <heading> / para n`),
so an operator (or a repair session) can act on it without opening the artifact.

**Which pipeline created the root is recorded.** `setup` prints and stores the
running script's path, version and SHA-256 (`state.json` → `pipeline`), and every
later invocation says so when the script it is executing is NOT that copy
(patched, replaced, or a different checkout). The 2026-09-22 roots needed this:
`setup` had been run from a stale checkout, so the root silently contained a
pipeline without the scoped-repair code and hours were spent asking why
`--strict-artifacts fix` never fired.

**An adopted run is repaired too.** When a resume finds a run whose sandbox
already carries its completion marker (`sweep_artifacts`), the same postcheck runs
— and if it fails on repairable bookkeeping, the scoped repair session runs right
there, so a finished 45-minute review is not thrown away for two unfilled tables.

### `--strict-artifacts fix`: one scoped repair session instead of a full re-run

Some failures are BOOKKEEPING: the stage did the work, but the report/ledger/
sheet the postcheck reads is unfilled, inconsistent or unfinished. Re-running
such a stage costs its whole session again and re-samples everything it produced
(the 2026-09-22 root got a different 102-finding review out of a retry that was
only fixing a disposition column). `--strict-artifacts fix` (alias
`--fix-artifacts`) spends ONE bounded session on the failed attempt's own sandbox
first. Every stage has a PROFILE — which problems are repairable bookkeeping,
which files may change, and which evidence is pinned:

| stage | repairable (examples) | may write | pinned evidence |
|---|---|---|---|
| `review` | the decision-artifact quality problems (empty cells, boilerplate closures, echoed OUTLINE summaries), the M1b long-form gate (undisposed residue rows — the class that failed the 2026-09-22 roots), a missing visual record | `review/artifacts/` (the seeded tables **including `M1_acronyms.md`**), `review/work/` | every table's row identity, all headers and column orders; `findings.json`/`md`, `round2/`, the other artifact files |
| `audit` | `audit.json` missing/unparseable/duplicated/missing dispositions | `audit/` | every existing disposition and every `adds` row; **new dispositions must be `confirm`** (a drop hides a finding from the revisers and needs the auditor's own evidence) |
| `rewrite` / `revise` / `integrate` | a missing/empty/thin report or ledger (`REWRITE_REPORT.md`, `revision_report.json`, `DIFF_LEDGER.md`), the language-pass coverage rows, the visual record, the marker | the package's bookkeeping files (by name) and its `work/` scratch | every manuscript file of the package; the frozen review; the corpus inputs |
| `judge` | a missing `checks` coverage map, `score`/`basis` that contradict the sheet's own ledger, bookkeeping ids, a missing grounding record | `scores.json`, `judge_review/` | `resolved`/`introduced` (the ledger IS the judgement), the comparison set, existing coverage entries; new coverage entries must be `unable` |

A repair may **fill, never re-judge**: it must write
`unable — manual verification required: <what the author must check>` where the
sandbox's own evidence is not enough, and it may never touch a submission
document, a citation, a number or another stage's deliverable. The orchestrator
verifies the scope byte-for-byte (plus the per-stage structural rules above) and
then re-runs the **identical postcheck**; anything else — a missing deliverable, a
validation failure, the M1b vanishing-residue gate, residuals, the pristine copy —
stays a plain failure. A repair that clears nothing, or that went out of scope, is
a failed attempt like any other (the normal retry policy decides next), and each
failed attempt gets at most one repair session.

The prompt is written by the pipeline (`REPAIR_PROMPT.md` in the sandbox, deleted
once the session ends), so the repair is a pipeline-defined, auditable step
rather than a second opinion: `status` and `DECISION_REPORT.md` list it under the
attempt history.

### Every attempt's errors and warnings are kept

`state.json` → `runs.<id>.attempts_log` holds one entry per attempt with its
**complete** error and warning lists (no message-count cap; only a 512 KiB total
guard, whose note says how many messages were left out), the true counts
(`n_errors`/`n_warnings`), its timing, its `source` (postcheck / process /
adopted / recheck / re-verify / manual / artifact-repair), the decision-artifact
quality report, the marker's summary and where its archive and transcript live.
The console prints every problem of a failed attempt in full, and the commands
that drive or mutate a root also keep their whole console in
`reports/<cmd>-<stamp>.log` (listed in `state.json` → `run_logs`), so the
retry/backoff decisions, the judge advisories and the `[repair] …` decisions of
an old invocation stay readable next to the reports they produced.

## Repository layout

| path | purpose |
|---|---|
| `nbt_pipeline.py` | the orchestrator (setup / run / run-decide / decide / retry / status / prune / redline) |
| `nbt_docx_format.py` | OOXML style/formatting scanner, fixer and blank-page checker |
| `nbt_redlines_adapter.py` | tracked-changes bridge (`python-redlines[docxodus]`) |
| `docx2pdf.sh` | Word→PDF conversion via PowerShell (WSL/Git Bash) |
| `mcp-docx-converter/` | the `docx-converter` MCP tool used as the first-choice renderer |
| `nbt-skills/` | the bundled review (`nbt-review`) and revision (`nbt-revise`) skills + prompts |
| `.nbt_test/` | the offline regression suites (stub agents; no network) |
| `nbt_audit_data/`, `NBT_TRIAGE_LEDGER.md`, `NBT_DESIGN_TRIAGE_LEDGER.md` | the audit inputs and the triage ledgers for the fixes they drove |

## Tests

Every suite is offline and prints one line per check; exit status is non-zero on
any failure. They are independent, so run them in parallel — 33 suites in ~110 s
on a 20-core box, against ~5.5 min sequentially:

```bash
python3 .nbt_test/run_all.py          # GNU parallel (8 jobs by default); falls back
                                      # to a thread pool when `parallel` is missing
python3 .nbt_test/run_all.py -j 16    # more sessions (measured: no faster, more load)
python3 .nbt_test/run_all.py -j 1     # the old sequential loop, for a bisect
python3 .nbt_test/run_all.py --only test_pipeline test_docx_format   # a subset
```

Each suite runs in its own `TMPDIR` and writes `<logs>/<suite>.log`; a suite that
fails is re-run alone once, so a timing-sensitive suite that merely lost a race
with seven siblings is reported as `flaky` (named, exit 0) while a real failure
keeps its `[FAIL]` lines and exit 1. The raw one-liner, if you prefer GNU parallel
directly (`mkdir -p /tmp/nbt-logs && export NBT_TEST_RUNDIR=/tmp/nbt-logs`):

```bash
ls .nbt_test/test_*.py | sed 's|.*/||' \
  | parallel -j 8 --joblog /tmp/nbt-logs/joblog '.nbt_test/run_one.sh {}'
```

Highlights: `test_pipeline.py` (prompts, gates, ranking), `test_length_limits.py`
(M18/M19 length rules), `test_docx_format.py` (OOXML formatting scan/fix, the
setup/stage normalization, the seeded M20 artifact and its contract, plus a real
LibreOffice render proving the blank page is gone), `test_stage_subset.py`
(`--only` review/revise/merge/judge end-to-end with the stub agent),
`test_only_rounds_integrators_judges.py` (`--only 1,2` / `--only 2:review` round
filtering, the per-round `--integrators` mask including 0x0 and the arms it
skips, and the per-round `--judges` panel expectation),
`test_evidence_pack.py` (the pack is written for all five session layouts, the
seeded files count as inputs not agent work, every prompt carries its block, the
judge sandbox is proved to hold NO orchestrator artifact (blinding) while the
orchestrator verifies the judge's target from its own side, and a stage records
its before/after delta),
`test_hash_cache.py`, `test_final_clean_version.py`, `test_grading_scheme.py`,
`test_anonymized_judging.py`, `test_zotero_integration.py`. See
`.nbt_test/README.md` for the full table.

## Exit codes

| code | meaning |
|---|---|
| 0 | success (`decide`: certified decision; `run`: every configured round complete) |
| 1 | a run failed / the process hit an error |
| 2 | nothing to decide yet, or a usage error |
| 3 | a round is incomplete (progress saved; resume with `run`) |
| 5 | `decide` found integrity or (with `--format-gate`) high-severity formatting problems |

## Notes

* `--root` and `--source` must not be nested; `setup` refuses a non-empty root.
* The pipeline never edits the operator's `--source`; every copy it makes
  (`non-revised/`, `base/`, pins, winners) is digest-verified.
* On WSL, `/mnt/c` occasionally returns transient `EIO` errors under a synced
  folder; re-running the affected command is safe (the pipeline is resumable).

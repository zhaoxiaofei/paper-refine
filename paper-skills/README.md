# paper-review + paper-revise — Codex Skills for Manuscript Submissions (any venue or journal)

**Package version:** 0.8 (any venue or journal, 2026-09-25; see CHANGELOG.md) — distributed as the directory
`paper-skills-v03`. The version lives here, not in the skill frontmatter. If more
than one copy of this package is installed, check this line and retire the
older copies (`paper-skills-v01/`, `paper-skills-v02/`): Codex registers skills by
name, so duplicate `paper-review/` or `paper-revise/` directories silently compete
with the one you edited.

Two complementary Codex skills that implement the **Sweep Pattern** workflow:
first *identify* every problem in a manuscript package exhaustively, then
*fix* the validated findings with surgical, verifiable edits — while the
originals stay read-only and nothing is ever fabricated.

```
paper-review  (identify_issues)          paper-revise  (adress_issues)
SUBMISSION_DIR ──► review/findings.{md,json} ──► revised/ package
            ▲                                    + CHANGELOG.md
            └── round2/new_sweeps.md ◄────────── + MANUAL_STEPS.md
                (checklist growth loop)          + REVISION_REPORT.md
```

Run inside this repository's round-based pipeline (`paper_pipeline.py`), those
two steps are arms of a larger round — the round base, M rewrites, ONE review,
N revises, K integrations and a blind judge panel that pins the champion. That
round is drawn in `media/paper-refine-one-revision-round.png`, which `README.md`
embeds.

## Installation (Codex CLI)

```bash
# 1. Copy the two skill directories into your Codex skills folder
mkdir -p ~/.codex/skills
cp -r paper-review ~/.codex/skills/
cp -r paper-revise  ~/.codex/skills/

# 2. (Optional) point paper-review / paper-revise at your Zotero skill.
#    Edit the `ZOTERO_SKILL` line in the two SKILL.md files of the copy that is
#    actually loaded (below, `<install>` is that copy — e.g. the package
#    directory itself, since Codex discovers skills recursively):
#    <install>/paper-review/SKILL.md and <install>/paper-revise/SKILL.md
#    ZOTERO_SKILL = /path/to/your/zotero/scripts/zotero.py
#    Default: /mnt/d/software/plugins/plugins/zotero/skills/zotero/scripts/zotero.py
#    If absent, both skills degrade gracefully to "manual verification required".
#    Reference resolution is read-only by default. paper-revise may edit a
#    citation field in its REVISED copy under the live-field rules
#    (snapshot + validation); writing to the Zotero library itself needs the
#    operator's explicit opt-in and follows rule E2's propose-then-verify
#    protocol (ONE field of ONE existing item, --last-modified auto, never a
#    create/delete/bulk edit).

# 3. Scripts are stdlib-only Python (3.8+) — nothing to pip-install.
python3 --version
```

After installation, Codex auto-discovers both skills by their descriptions;
no further registration is needed. If you prefer not to install skills, use
`prompts/identify_issues.prompt.md` and `prompts/adress_issues.prompt.md`
(standalone prompt fallbacks with the full sweep definitions inlined).
What changed in this audit release: `CHANGELOG.md`.

## Regression tests (shipped)

The audit findings are pinned by three runnable suites; they write only inside
`--run-dir` and exit non-zero on any failure:

```bash
python3 tests/validate_skill.py    --skill-root . --run-dir /tmp/paper_validate   # 40 checks
python3 tests/probe_regressions.py --skill-root . --run-dir /tmp/paper_probe      # 14 probes
python3 tests/probe_hardcases.py   --skill-root . --run-dir /tmp/paper_hard       # 4 hard cases
```

`validate_skill.py` covers the v0.3 audit (truncation, xlsx, numbers, acronyms,
citations, docx/rtf parsing, prompt sync); the two probe suites cover the v0.4
findings and the heuristics most likely to misfire (blank-line lists, wrapped
entries, measurement-noun noise).

Shipped scripts cover Phase-1 conversion and the M1 (acronyms), M2
(citations), M4 (numbers), M8 (term/value occurrences) and M19 (abstract /
main-text / cover-letter word counts) sweeps. M3, M5–M7 and M9–M18 are specified in
`references/sweeps.md` but are not script-backed: for those, the agent builds
the enumeration table itself and every row must still be disposed.

## Usage

### Step 1 — Review (identification only)

Say one of these to Codex in the directory that contains your submission
folder:

- "Review the manuscript package in ./submission before we submit to Nature
  Biotechnology. Do not modify anything."
- "Run the pre-submission diagnostic review on ./submission."
- "identify_issues on ./non-revised" (legacy name)
- "…discover mode" — re-runs ONLY the discovery round against existing
  findings (hunts issue classes the checklist itself misses)

Outputs land in `./review/`:

| file | content |
|---|---|
| `findings.md` | human-readable report: file inventory, sweep artifacts, findings grouped by category, per-document index, coverage table, summary |
| `findings.json` | machine-readable findings (8 fields each) + artifacts + coverage — the canonical input to paper-revise |
| `artifacts/M1_acronyms.md`, `artifacts/M2_citations.md`, `artifacts/M4_numbers.md` | enumeration tables written by the shipped scripts; the remaining M-sweeps get their tables from the agent as specified in `references/sweeps.md` (M8 occurrence tables land in `work/occurrences_*.md`) |
| `round2/` | discovery-round outputs: `findings_extra.{md,json}` (X-findings), `new_sweeps.md` (proposals), `round2_summary.md` |

### Step 2 — (optional) Validate the growth-loop proposals

`review/round2/new_sweeps.md` proposes new sweeps (M20+; M18 and M19 are
reserved by the pipeline) based on what
the discovery round caught that the checklist missed. Review them, then
append the ones you accept to `references/sweeps.md` of the installed
`paper-review` copy. If that directory is read-only (typical for an installed
skill), keep the accepted text in `review/round2/new_sweeps.md` and hand the
append to whoever owns the installation. M14–M17 shipped with this package were
validated exactly this way (see *Validation* below).

### Step 3 — Revise (targeted fixes)

- "Apply the findings in ./review to fix the submission. Never modify
  ./submission itself."
- "adress_issues" (legacy name)

Outputs land in `./revised/` (originals untouched, sha256-verified):

| file | content |
|---|---|
| revised copies of your files | same basenames as the originals (never mutated) |
| `CHANGELOG.md` | per finding ID: exact before → after text |
| `MANUAL_STEPS.md` | everything that needs the author: unverifiable refs, figures to regenerate, scientific-judgement wordings |
| `REVISION_REPORT.md` + `revision_report.json` | ledger, coverage table with evidence, placeholder list, checksum confirmation |
| `*.tracked.docx` | auxiliary tracked-changes copy for every edited .docx; when real tracked changes cannot be produced, the fallback is `<name>.before-after.docx` with bracketed `[BEFORE:]`/`[AFTER:]` markers and a first-paragraph note — never a marker file under the `.tracked.docx` name |
| `work/` | A1–A9 artifacts (ledger, edit plan, propagation map, diff log, rescan) |

What the revise skill will never do: invent values, alter scientific claims
on its own initiative, silently skip a finding, modify your originals, or write
to your Zotero library without an explicit opt-in (citation-field edits in the
REVISED copy are allowed under the live-field rules and are validated against a
pre-edit snapshot).

## How it works (the Sweep Pattern)

Both skills are built on the same countermeasure to LLM attention drift:

1. **ENUMERATE** — a script (bundled, stdlib-only) lists *every* instance of
   a checkable thing: every acronym, every citation call-out, every number,
   every table column.
2. **ARTIFACT** — the enumeration lands in a table on disk. Coverage comes
   from the artifact, not from attention: a sweep with zero findings is
   invalid unless its artifact exists with every row disposed.
3. **AUDIT** — the model classifies rows one by one (OK / finding / unable).
4. **REPORT** — findings are derived only from artifact rows. One finding
   per instance: "several acronyms are undefined" is not a finding; each
   undefined acronym is.

Mechanical sweeps M1–M17 are exhaustive and mandatory, and M18 (figure-legend
lengths; always enumerated, with an optional proxy cap) and M19
(abstract/main-text length plus the user's cover-letter preference) always run
with them. Judgment
passes J1–J4 (scope fit, statistical rigor, overclaiming, plagiarism/AI policy)
are deep and prioritized. A discovery round (D0–D5) then hunts issue
classes outside the checklist, and its validated proposals grow the
checklist (M20+) for future runs.

The revision skill mirrors the discipline: an A1 ledger where every finding
ID must get exactly one row and a status (no silent skips), an edit plan
where every edit maps to a finding, P1 consistency propagation by script
(the authoritative value flows from supplementary tables → main text →
abstract → cover letter), a diff log proving locality, and a V3 full
mechanical rescan of the revised corpus.

## Validation (iteration-1, seeded-defect benchmark)

Tested on a synthetic, Nature-Biotechnology-style submission with ~24 planted defects
(corresponding-author mismatch, orphan citation, irreconcilable cell-count
total, n = 15 vs 12-patient cohort, undefined acronyms, TODO/XXX
placeholders, duplicated sentence, cover-letter title mismatch, docx
metadata leak, E. coli spike-in anomaly, missing Reporting Summary, …),
with and without the skills, graded by scripted assertions:

| eval | with skill | baseline (no skill) |
|---|---|---|
| identify seeded defects | **12/12** | 8/12 |
| apply validated findings | **16/17** | 12/17 |

- The baseline already catches *salient* defects; the skills add the
  **coverage guarantee**: 21-check coverage table, per-sweep artifacts,
  findings.json schema for machine consumption, discovery round (it caught
  the cover-letter title mismatch that no checklist item covers),
  CHANGELOG/MANUAL_STEPS/tracked-docx outputs, explicit `[AUTHOR TO
  COMPLETE]` placeholders instead of silently-left `XXX`, and script-verified
  cross-document propagation.
- The single with-skill failure (corrupted revised filenames such as
  `manuscripu.md`) was traced to an ambiguous rename rule, fixed in this
  release, and smoke-tested: basenames now stay unchanged, collisions get
  `_rev2` suffixes, originals verified byte-identical.
- M14–M17 (metadata consistency, numeric-total reconciliation, abstract
  traceability, anomaly tokens) were appended after each was validated by
  real iteration-1 instances.
- The iteration-1 eval harness and its HTML report are **not bundled** with
  this package; the numbers above are the ones recorded when the package was
  built and are not re-verifiable from these files alone.

## Package contents

```
paper-skills/
├── paper-review/
│   ├── SKILL.md                     # phases, hard rules, output spec
│   ├── references/sweeps.md         # M1–M19 + J1–J4 (source of truth)
│   ├── references/discovery.md      # D0–D5 discovery round
│   └── scripts/                     # convert_corpus, extract_{acronyms,
│                                    #   citations,numbers,occurrences},
│                                    #   count_words
├── paper-revise/
│   ├── SKILL.md                     # R0–V pipeline, hard rules
│   ├── references/ledger.md         # A1–A9 artifact specs
│   ├── references/edit_rules.md     # E1–E6, P1, C
│   └── scripts/revision_token.py    # the 7-char content-hash version token
└── prompts/                         # standalone prompt fallbacks
    ├── identify_issues.prompt.md
    └── adress_issues.prompt.md
```

## Tuning

- **Venue, article type and journal**: selectable at run time —
  `set-venue <id>`, `set-article-type <id>` and `set-journal <name>` (or
  `setup --venue/--journal/--article-type`), with the rule set in
  `venue_profiles/<id>.json` (`venue_profiles/README.md` documents the
  schema, including the `article_types` table). The default profile is Nature Biotechnology / Nature Portfolio
  (initial submission: format-flexible, Reporting Summary required at
  acceptance stage), so the guideline-specific items in
  `references/sweeps.md` M5/M13 are that profile's; a custom profile replaces
  the numbers the pipeline enforces without editing the skill.
- **Zotero**: `ZOTERO_SKILL` / `ZOT_CLI` paths in both SKILL.md files, plus the
  operator's policy (`paper_pipeline.py setup --zotero off|read|edit|apply`).
  Both skills resolve references read-only by default. paper-revise may edit a
  citation field in its REVISED copy (live-field rules + snapshot validation);
  library writes happen only in `apply` mode, one field of one existing item,
  under rule E2's propose-then-verify protocol. No mode creates or deletes
  library items, and paper-review never writes.
- **Length rule** (M19, always on): the venue profile's limits apply relaxed
  by the profile's own margins — the default nature-biotechnology profile:
  abstract ≤ 150 words +15% (≤ 172) and main text ≤ 3,000 words +25% (≤ 3,750,
  excluding abstract, Methods, references and figure legends). Words are
  maximal runs of non-space characters with a newline treated as space
  (`scripts/count_words.py`); over-cap sections are
  reported and compressed by removing redundancy only — content is never cut,
  under-length text is never flagged, and length never gates a version.
  The cover letter's persuading part is measured against the master prompt's
  own 300-500-word preference; the default profile's venue states no
  cover-letter word limit (checked 2026-09-19), so it is a Minor formatting
  item, never a journal requirement. **M18** always enumerates figure-legend
  word counts (the venue profile requires them to respect the article type's
  limit but publishes no number); an optional `--caption-limit` proxy cap only
  changes whether an over-count legend is reported as an over-cap item.
- New sweeps you validate from `round2/new_sweeps.md` append as M20+ at the
  end of `references/sweeps.md` of the loaded copy (M18 and M19 are reserved);
  IDs are stable, never renumbered.
- **File naming**: `paper-revise` gives each revision package ONE version token:
  the 7-character content-hash printed by `paper-revise/scripts/revision_token.py`
  (first 7 hex of SHA-256 over the sorted payload content digests; reports,
  auxiliaries and `work/` excluded, names ignored, existing version-token
  references normalized before hashing so applying the token does not change
  it). Every editable document carries it, replacing a trailing `-a`/`_v2`
  token or appended when the basename has none. Letter/digit increments are
  withdrawn; the only other rename is the `_rev2` collision fallback.

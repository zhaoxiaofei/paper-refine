# AGENT.md — working in this repository

This repository is a **venue-agnostic** round-based manuscript revision
pipeline. Read this before changing anything; it is the short version of
`README.md` for an agent (or a human) editing the code, plus the rules that keep
the pipeline from drifting back to a single journal.

## What the pieces are

| path | what it is |
|---|---|
| `nbt_pipeline.py` | the orchestrator (single file, stdlib only). CLI: `setup`, `run`, `run-decide`, `decide`, `status`, `agents`/`sessions`, `selfcheck`, `set-venue`, `set-journal`, `retry`, `prune`, `redline`. |
| `nbt_docx_format.py` | the optional companion: code-side OOXML style/formatting scan/fix (`scan`/`fix`/`check-pdf`). |
| `nbt_redlines_adapter.py` | optional tracked-changes `.docx` bridge. |
| `venue_profiles/` | the venue profiles (the submission rule sets) **and their schema documentation** — start at `venue_profiles/README.md`. |
| `nbt-skills/` | the bundled `nbt-review` / `nbt-revise` skill packages and the two master prompts. |
| `.nbt_test/` | the offline regression suites (stub agents; no network). |

## Venue vs journal — the rule that matters here

* A **venue** is a *rule set*: the abstract/main-text limits and their margins,
  the figure-legend policy, the cover-letter preference, the submission-format
  note, and the phrases the prompts use. It is selected by **id**
  (`set-venue <id>`, `setup --venue <id>`) and realised by a **venue profile** —
  a JSON document in `venue_profiles/`.
* A **journal** is a *name*: the publication the manuscript is going to, free
  text (`set-journal "Cell"`). The prompts use it and the venue profile is
  checked against it. It selects no rules.

Both live in `<root>/pipeline_config.json` (`venue`, `journal`) plus a snapshot
of the resolved profile (`venue_profile`), mirrored into `state.json`. The
defaults are `nature-biotechnology` / "Nature Biotechnology" — the pipeline's
pre-venue behaviour — so roots created before this feature keep working
byte-for-byte.

Resolution order: the current command's flags → `pipeline_config.json` (and its
snapshot, which wins over profile *files*) → `<root>/venue_profiles/<id>.json` →
the profiles shipped next to the script → the built-in fallback inside
`nbt_pipeline.py` → the profile's `default_journal` → the default venue.

## Rules for changing the pipeline

1. **Never hard-code a journal name, a journal's numbers or a journal's
   submission requirement in the orchestration code.** Venue-specific facts go
   into a venue profile; the code reads them through `VenueProfile`
   (`venue_profile_of(ctx)`, `length_limits(profile)`,
   `standing_exemptions_text(profile)`, `caption_rule_text(limit, profile)`,
   `m19_blocks(profile)`, `derived_outputs_rule(profile)`,
   `render_venue_tokens(text, profile)`). Adding a venue must be adding a JSON
   file, never adding an `if venue == ...` branch.
2. **Every stage reads the configured values.** Prompt builders take
   `venue=<VenueProfile>`; the scans take `profile=`; setup/status/decide print
   `venue_status_lines(ctx)`. If you add a place that names the journal or a
   limit, render it from the profile.
3. **A missing or partial venue must degrade to "count and report", never to an
   invented number.** A profile with `base: null` means the stage enumerates the
   count and names the limit the target journal's own guidelines state.
4. **Do not silently change an existing root's rules.** The recorded snapshot is
   authoritative; profile files are only a lookup for roots that have no
   snapshot. `set-venue` re-records it, and refuses (without `--force`) once the
   root has run records.
5. **Backward compatibility is a test.** `test_venue_config.py` asserts that a
   config without `venue`/`journal` behaves exactly like the old default.
6. The skill ids `$nbt-review` / `$nbt-revise` and the file names `nbt_*.py` are
   **historical identifiers**, not venue assumptions: they are the stable names
   of the installed skill packages and of this repository's entry points. Do not
   rename them in prompt text; do keep their *prose* venue-neutral.

## Commands you will use

```bash
# configure / inspect the venue and journal of an existing root
python nbt_pipeline.py set-venue --list
python nbt_pipeline.py set-venue example-journal --profile venue_profiles/example-journal.json
python nbt_pipeline.py set-venue --journal "Example Journal"
python nbt_pipeline.py set-journal "Example Journal"
python nbt_pipeline.py set-venue --show [--json]
python nbt_pipeline.py status --root ./nbt_rounds      # venue + journal + limits

# create a root for a specific venue in one step
python nbt_pipeline.py setup --source ./non_revised --root ./nbt_rounds \
    --venue generic --journal "Journal Name"

# validation (see README.md -> Tests for the full list)
python3 -m py_compile nbt_pipeline.py nbt_docx_format.py
python3 .nbt_test/run_all.py -j 8            # every suite, offline
python3 .nbt_test/run_one.sh test_venue_config.py
```

## When a stage prompt is written

The prompt builders are the only place the venue appears to an agent. They
render, from the profile:

* the length rule (M19) and its mandates — numbers, margins, provenance;
* the caption rule (M18) — the venue's own legend policy;
* the derived-outputs rule — whether the venue accepts a submitted PDF;
* the master-prompt prose — subject, editor, requirements, guidelines source;
* the standing exemptions and the shared decision blocks.

If you add a rule that depends on the venue, add a field to the profile schema
(documented in `venue_profiles/README.md`), a rendering function here, and a
case in `test_venue_config.py` that asserts a non-default venue produces no
default-venue text.

## Known, deliberate limits

* The **skill packages** (`nbt-skills/`) are standalone: their own prose still
  quotes the default profile's numbers as examples, and their
  `references/sweeps.md` M5/M13 carry the Nature Portfolio requirement list. A
  custom venue profile is authoritative when the pipeline runs them; a
  standalone run must follow the target journal's own guide. Extending those
  reference lists into per-venue data is future work, not a code path here.
* The **triage ledgers** (`NBT_*_LEDGER.md`) are historical records of past
  runs. They are not edited to match a new venue, and their name is part of that
  record.

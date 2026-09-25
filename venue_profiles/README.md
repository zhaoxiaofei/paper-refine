# Venue profiles

A **venue** is the requirement set the pipeline enforces; a **journal** is the
publication you are submitting to; an **article type** is which of that venue's
content types the manuscript is. They are deliberately separate:

* the **venue** is selected by id (`set-venue <id>`, or `setup --venue <id>`)
  and realised by a JSON document in this directory. It carries the numbers
  the stages use: the abstract/main-text limits (and their margins), the figure
  legend policy, the cover-letter preference, the submission-format note, and
  the phrases the prompts use to name the venue.
* the **journal** is free text (`set-journal "Cell"`). It is what the prompts
  call the target journal and what the venue profile is checked against. It
  selects no rule set by itself.
* the **article type** is part of the venue's rule set: a venue publishes
  several content types (Article, Brief Communication, Review, Resource,
  Analysis, Matters Arising, Letter to the Editor, …) and the word limits belong
  to the type, not to the venue as a whole. The profile carries the table
  (`article_types`); the root records the selection
  (`setup --article-type`, `set-article-type`).

All three live in `<root>/pipeline_config.json` (`venue`, `journal`,
`article_type`) together with a **snapshot** of the resolved profile
(`venue_profile`). Every later stage reads that snapshot (`venue_profile_of`),
so a root keeps enforcing the rules it was configured with even if these files
change or disappear.

Three keys record where the journal, the article type and the caption cap came
from: `journal_source`, `article_type_source` and `caption_limit_source`. They
are `"operator"` when you set the value yourself (`setup --journal`,
`setup --article-type`, `set-journal`, `set-article-type`,
`setup --caption-limit`) and `"profile-default"`/`"unset"` when the venue
profile supplied it. A venue change therefore adopts the new profile's defaults
for the values the profile supplied, and keeps the values you chose.

## Shipped profiles

| id | what it is |
|---|---|
| `nature-biotechnology` | the pipeline's original, pre-venue rule set, with the venue's content-type table. Its **Article** type carries the numbers the pipeline started with (abstract <= 150 words, main text <= 3,000 words, relaxed by +15%/+25% to 172/3,750); the other types (Brief Communication, Review, Perspective, Analysis, Resource, Correspondence, Matters Arising) deliberately carry no numbers, so selecting them counts and reports against the venue's table instead of borrowing the Article caps. This is the **default** venue, so an existing root keeps behaving exactly as before. |
| `generic` | a venue-agnostic profile: one `Article` type that states no limits, no legend cap and no format rule of its own. Every stage still enumerates the counts and names the limit the *target journal's own* guidelines state. |
| `example-journal` | an **illustrative template** showing the fields the other two do not exercise: three article types with different caps (Research Article 275/6000, Review 220/9600, Letter to the Editor with no abstract cap and an 880-word main text), a published legend limit, no cover-letter preference and an explicit journal list. Its numbers are placeholders: copy the file, replace them with the ones your venue's guidelines state, cite them in `source`, and install it with `set-venue <id> --profile <file>`. |

`set-venue --list` prints every venue the running pipeline can see, with the
file it came from.

## Where profiles are looked up

In this order, first match wins:

1. `<root>/venue_profiles/<id>.json` — root-local (what `set-venue --profile`
   installs, and what you can edit by hand);
2. `<script dir>/venue_profiles/<id>.json` — shipped with the pipeline copy
   that is running (`setup` copies this directory into the root, so a
   self-contained root has both);
3. the built-in fallback inside `paper_pipeline.py` (`nature-biotechnology` and
   `generic`), so a single-file copy of the script still runs.

The **snapshot in `pipeline_config.json` wins over all three** for a root that
already recorded one: editing a profile file never silently changes the rules
of an existing root; re-run `set-venue <id>` to re-record it.

## Schema

Only `id` is required. Unknown keys are ignored, so a profile can carry its own
documentation.

| field | type | meaning |
|---|---|---|
| `id` | slug | the id `set-venue` resolves. Letters, digits, `.`, `_`, `+`, `-`. |
| `label` | string | human name used in the prompt prose (`"Nature Biotechnology"`). Default: the id. |
| `short` | string | short form used in phrases like "not an NBT rule". Default: the label. |
| `description` | string | what the profile is for; shown by `set-venue --list`. |
| `default_article_type` | slug | the type selected when the root records none. Default: the first entry. |
| `article_types` | list | the venue's content types (see below). A profile written in the older single-type shape (`article_type` + top-level `length_limits`/`captions`, no table) is read as a one-entry table and keeps its old behaviour. |
| `article_type` | string | the DEFAULT type's label, as resolved by the pipeline (informational; the table is authoritative). |
| `journals`, `journal_aliases` | list of strings | the journals this profile claims to describe. A journal outside the list is reported as an inconsistency (fatal under `--strict-venue`). |
| `journal_patterns` | list of regexes | extra journal names, matched case-insensitively. |
| `accepts_any_journal` | bool | `true` = never report a journal/venue mismatch (the shipped `generic` profile). |
| `default_journal` | string | used when the root records no journal; `""` = no default (the prompts then say "the target journal"). |
| `length_limits.source` | string | provenance quoted in the M19 artifacts, in `setup`/`status`, and in the decision report. |
| `length_limits.abstract` | `{base, relaxation}` | the abstract's own limit and the margin this pipeline relaxes it by (both `null` = the profile sets none). |
| `length_limits.main_text` | `{base, relaxation}` | same, for the main text. |
| `length_limits.cover_letter` | `{min, max, source}` | the *user preference* for the persuading part; `null`/`null` = no preference configured. Never a gate. |
| `captions.published_limit` | int or `null` | the venue's own published legend limit, when there is one. |
| `captions.default_cap` | int | the legend cap used when `setup` was run without `--caption-limit`; `0` = counts only. |
| `captions.source` | string | what the venue says about legend length (quoted in the M18 rule). |
| `submission.pdf_accepted` | bool or `null` | whether the venue accepts a submitted PDF. |
| `submission.formats` | list of strings | accepted formats, for the record. |
| `submission.pdf_note` | string | the sentence the derived-outputs rule uses about a submitted PDF. |
| `prompt.subject` | string | the opening phrase of the master prompt ("Review and revise **an Example Journal research-article submission**, …"). |
| `prompt.editor` | string | "anything **an Example Journal editor or reviewer** could raise". |
| `prompt.requirements` | string | "judged against **the Example Journal author guidelines and submission requirements**". |
| `prompt.requirement_authority` | string | "unless such formatting is required or recommended by **the Example Journal guidelines**". |
| `prompt.guidelines_source` | string | the guidelines source the review is told to read. |

### `article_types[]`

Each entry is one content type of the venue:

| field | type | meaning |
|---|---|---|
| `id` | slug | what `--article-type`/`set-article-type` take (`article`, `brief-communication`, …). Default: the label, slugified. |
| `label` | string | how the venue writes the type ("Brief Communication"); used in the prompts and listed by `set-article-type --list`. |
| `source` | string | where the type (and its numbers) come from — quoted when the profile carries no numbers for it. |
| `length_limits` | object or `null` | the type's own limits, exactly like the top-level block above. **`null` (or a block with `base: null` for abstract/main_text) means "this profile carries no numbers for this type"**: the stages count the section and name the limit the venue's own content-types table states — they never borrow another type's caps. |
| `captions` | object or `null` | the type's legend policy; `null`/absent inherits the default type's policy (the legend rule is venue-wide in practice). |

Abstract and main-text limits are **per type**. The cover-letter preference and
the legend policy are **per venue**: a type that does not state them inherits
the default type's, so a venue's "300–500 words in the persuading part" is not
re-declared for every type.

Validation is strict and reports **every** problem at once: an unknown id, a
non-positive `base`, a `relaxation` below 1.0, a lone `base` without its
`relaxation`, an inverted cover-letter range, an invalid regex, or a
non-boolean `pdf_accepted` all fail `set-venue <id> --profile FILE` before
anything is written.

## Two worked examples

**1. Nature Biotechnology (shipped, the default).** Its Article numbers are the
ones the pipeline originally hard-coded, and its table lists the venue's content
types; the shape is the one to copy for a real journal:

```json
{
  "id": "nature-biotechnology",
  "label": "Nature Biotechnology",
  "short": "NBT",
  "journals": ["Nature Biotechnology"],
  "journal_aliases": ["NBT", "Nat. Biotechnol."],
  "default_journal": "Nature Biotechnology",
  "default_article_type": "article",
  "article_types": [
    {
      "id": "article", "label": "Article",
      "length_limits": {
        "source": "Nature Biotechnology content-types table (Article: abstract <= 150 words; main text <= 3,000 words excluding abstract, Methods, references and figure legends)",
        "abstract": {"base": 150, "relaxation": 1.15},
        "main_text": {"base": 3000, "relaxation": 1.25},
        "cover_letter": {"min": 300, "max": 500, "source": "master-prompt preference; the journal states no limit"}
      },
      "captions": {"published_limit": null, "default_cap": 0, "source": "requires a legend no longer than the article type's word limit, but publishes no number"}
    },
    {
      "id": "brief-communication", "label": "Brief Communication",
      "length_limits": {
        "source": "Nature Biotechnology content-types table (Brief Communication: this profile carries no number for that type -- the stage names the limits the table states)"
      }
    }
  ],
  "submission": {"pdf_accepted": true, "pdf_note": "the journal accepts PDF initial submissions, and a reader or editor may open exactly that PDF"},
  "prompt": {
    "subject": "a Nature Biotechnology (NBT) manuscript submission",
    "editor": "a Nature Biotechnology editor or reviewer",
    "requirements": "the Nature Biotechnology author guidelines and submission requirements",
    "requirement_authority": "Nature Biotechnology",
    "guidelines_source": "the current Nature Biotechnology author guidelines"
  }
}
```

Selecting `brief-communication` on such a profile yields **no caps**: the
stages count the sections and hand the author the table's own number instead of
reusing the Article limits.

**2. A custom journal with its own per-type numbers.** Say the venue publishes
Research Articles (abstract <= 250 words, main text <= 4,000 words), Reviews
(abstract <= 200, main text <= 8,000), and Letters (no abstract, main text
<= 800), a 200-word legend limit and no cover-letter rule. Everything the
pipeline needs is data:

```json
{
  "id": "custom-clin-journal",
  "label": "Custom Clinical Journal",
  "short": "CCJ",
  "journals": ["Custom Clinical Journal"],
  "default_journal": "Custom Clinical Journal",
  "default_article_type": "research-article",
  "article_types": [
    {
      "id": "research-article", "label": "Research Article",
      "length_limits": {
        "source": "Custom Clinical Journal author instructions (2026): abstract <= 250 words; main text <= 4,000 words, Methods and references excluded",
        "abstract": {"base": 250, "relaxation": 1.1},
        "main_text": {"base": 4000, "relaxation": 1.1},
        "cover_letter": {"min": null, "max": null, "source": "the journal states no cover-letter word limit"}
      },
      "captions": {"published_limit": 200, "default_cap": 200, "source": "the journal limits each figure legend to 200 words"}
    },
    {
      "id": "review", "label": "Review",
      "length_limits": {
        "source": "Custom Clinical Journal author instructions (2026), Review: abstract <= 200 words; main text <= 8,000 words",
        "abstract": {"base": 200, "relaxation": 1.1},
        "main_text": {"base": 8000, "relaxation": 1.1}
      }
    },
    {
      "id": "letter-to-the-editor", "label": "Letter to the Editor",
      "length_limits": {
        "source": "Custom Clinical Journal author instructions (2026), Letter: no abstract; main text <= 800 words",
        "abstract": {"base": null, "relaxation": null},
        "main_text": {"base": 800, "relaxation": 1.1}
      }
    }
  ],
  "submission": {"pdf_accepted": true, "formats": ["PDF", "DOCX"], "pdf_note": "the journal accepts PDF submissions, and a reader or editor may open exactly that PDF"},
  "prompt": {
    "subject": "a Custom Clinical Journal submission",
    "guidelines_source": "the Custom Clinical Journal author instructions (prefer a local copy in the corpus)"
  }
}
```

Install the second one with:

```bash
python paper_pipeline.py set-venue custom-clin-journal --profile custom-clin-journal.json \
        --article-type research-article
python paper_pipeline.py set-journal "Custom Clinical Journal"
python paper_pipeline.py set-article-type --list   # research-article / review / letter-to-the-editor
python paper_pipeline.py status   # venue, article type, journal and the resolved limits
```

For the default Research Article the promoted numbers become the M19 caps
(250 * 1.1 = 275; 4000 * 1.1 = 4400), and the legend cap becomes 200 by default
because `captions.published_limit` is set. `set-article-type review` switches
those caps to 220/8800, and `set-article-type letter-to-the-editor` has no
abstract cap at all while keeping the 800-word main-text limit. The M18/M19
artifacts and the decision report quote `length_limits.source`, so a reader can
always see where a number came from — and which type it belongs to.

## Adding a venue

1. Copy `example-journal.json` (or a shipped profile) to `<your-id>.json`.
2. Set `id` to the file's base name — `set-venue <id> --profile FILE` refuses a
   mismatch, because the file name is what the id resolves to.
3. List the venue's content types under `article_types` and replace each type's
   numbers with the ones **your venue's own guidelines** state; quote them in
   `length_limits.source` / `captions.source`. Leave a number `null` (or the
   whole `length_limits` block `null`) rather than guessing: a null limit means
   "the stages count and report against the guidelines you name", never "the
   pipeline invented a number" — and never "reuse the previous type's caps".
4. Install and select it:

   ```bash
   python paper_pipeline.py set-venue <id> --profile <your-id>.json
   ```

   (This writes it into `<root>/venue_profiles/`, where it wins over the
   shipped copy and travels with the root.)
5. `python paper_pipeline.py set-venue --show` prints the resolved venue,
   journal, limits and any configuration problem.

## What the pipeline does when something is missing or inconsistent

| situation | behaviour |
|---|---|
| a root with **no `venue` key** (created before this feature) | uses the default venue `nature-biotechnology` — byte-for-byte the old behaviour — and prints a note telling you to run `set-venue` to make it explicit. |
| the **journal is missing** and the venue profile has a `default_journal` | the default is used (so the default venue yields "Nature Biotechnology"). Nothing is reported as a problem. |
| the **journal is missing** and the venue profile has no default (`generic`) | the prompts say "the target journal"; `setup`, `status` and the decision report print a note suggesting `set-journal`. Under `--strict-venue` it is an error. |
| an **unknown venue id** | `set-venue`/`setup` fail with the list of available ids. A root that already records the unknown id reports it (`status` still works, so you can see the problem) and every command that must render a prompt refuses to run. |
| the **journal does not match** the venue profile's journal list/patterns | reported as a warning by `set-journal`/`set-venue`/`setup`/`status` and under `--strict-venue` it is an error. The venue's rules still apply. |
| the **article type is missing** from the config | the venue profile's `default_article_type` is used; `setup`/`status` print a note suggesting `set-article-type <id>`. |
| an **unknown article type** | `setup --article-type`/`set-article-type`/`set-venue --article-type` fail with the ids and labels the profile carries; a root recording one reports it and every command that must render a prompt refuses to run. |
| a **type the profile carries no numbers for** (e.g. Brief Communication in the shipped Nature Biotechnology profile) | reported as a note. The stages count the abstract/main text and name the limit the venue's own content-types table states; the Article caps are never borrowed, and the M19 code-side scan reports `cap: null` rather than a violation. |
| a **type the new venue does not carry**, when the venue changes | `set-venue` falls back to that profile's default type and prints a note (an operator-chosen type is kept when the new profile has it). |
| the config's `venue` and the **recorded snapshot disagree** | the config file wins and the mismatch is reported; re-run `set-venue <id>` to re-record the snapshot. |
| `pipeline_config.json` and the mirrored `state.json.config` disagree | the config file wins and a note says so (`set-venue`/`set-journal` re-mirror it). |
| a **profile file is invalid** | `set-venue --profile` fails before writing anything, listing every schema problem; an invalid file already in `venue_profiles/` is listed as `INVALID` by `set-venue --list`. |
| a **venue change on a root that already has runs** | refused unless `--force` is given: the recorded rounds were planned, prompted and judged under the previous rule set. |
| an **article-type change on a root that already has runs** | refused unless `--force`, like a venue change: the prompts, the caps and the judgments belong to the previous type. |

## What a profile cannot express (and what therefore stays manual)

The pipeline is venue- and article-type-agnostic through configuration, but the
rule set a profile can carry is deliberately narrow: it describes what the
stages *enforce*, not everything a journal's guidelines say. These combinations
are **recorded and reported, not enforced** — the operators and the agent
sessions still see them through `length_limits.source`, `prompt.guidelines_source`
and the skills' sweeps, and they surface as manual items:

| situation | what happens today |
|---|---|
| the venue's rule is not a **word count** (page limits, character limits, reference/citation counts, display-item or supplementary limits, "total length") | not modelled: the profile has no field for it, so no code-side scan and no gate; the agents can still report it as a finding against the guidelines they read. |
| a **structured abstract** (Background/Methods/Results with separate limits) or a main text that is not one contiguous span | the abstract is counted as ONE block and the main text as the venue's single "excluding Methods/references/legends" span; per-subsection limits are not enforced. |
| limits that are **per section** ("Methods up to X") or given as ranges | not modelled; put the wording in `length_limits.source` so every stage reads it and hands the decision to the author. |
| **stage-dependent** rules (initial submission vs revision vs appeal) | one profile per root/run: use two profiles (or `set-venue`/`set-article-type` between runs) when a venue changes its limits between stages. |
| a **non-English** submission, or section headings the scan does not know | the code-side M18/M19 scans recognise the usual English headings; the agents' sweeps remain authoritative. A profile can rename the venue, not teach the scanner a language. |
| **venue-specific checklists** (Reporting Summary, significance statement, ethics/consent forms, data- and code-availability wording, ORCID rules, ...) | not data-driven: the master prompt's prose and the bundled skills carry the default profile's list. A profile names its guidelines source and its article types and numbers; adding a new mechanical sweep is a change to `paper-skills/paper-review/references/sweeps.md`. |
| a content type that is **not a research manuscript** (editorial, news, obituary, correspondence-only) | the pipeline still runs and the schema accepts the type, but the review/revision model assumes a research package; expect most checks to be reported as "not applicable" or manual. |
| **multiple venues or article types in one run** | not supported: one root = one venue + one article type (that is what makes the recorded decision reproducible). Run the pipeline once per combination. |

Everything else — any venue id, any article type label, any journal name, any
per-type numbers or none at all — is configuration, and the pipeline enforces
exactly what the profile states, never a default it invented.

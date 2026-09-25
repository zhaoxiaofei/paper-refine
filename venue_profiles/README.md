# Venue profiles

A **venue** is the requirement set the pipeline enforces; a **journal** is the
publication you are submitting to. They are deliberately separate:

* the **venue** is selected by id (`set-venue <id>`, or `setup --venue <id>`)
  and realised by a JSON document in this directory. It carries the numbers
  the stages use: the abstract/main-text limits (and their margins), the figure
  legend policy, the cover-letter preference, the submission-format note, and
  the phrases the prompts use to name the venue.
* the **journal** is free text (`set-journal "Cell"`). It is what the prompts
  call the target journal and what the venue profile is checked against. It
  selects no rule set by itself.

Both live in `<root>/pipeline_config.json` (`venue`, `journal`) together with a
**snapshot** of the resolved profile (`venue_profile`). Every later stage reads
that snapshot (`venue_profile_of`), so a root keeps enforcing the rules it was
configured with even if these files change or disappear.

Two keys record where the journal and the caption cap came from:
`journal_source` and `caption_limit_source`. They are `"operator"` when you set
the value yourself (`setup --journal`, `set-journal`, `setup --caption-limit`)
and `"profile-default"`/`"unset"` when the venue profile supplied it. A venue
change therefore adopts the new profile's defaults for the values the profile
supplied, and keeps the values you chose.

## Shipped profiles

| id | what it is |
|---|---|
| `nature-biotechnology` | the pipeline's original, pre-venue rule set (Nature Biotechnology Article: abstract <= 150 words, main text <= 3,000 words, relaxed by +15%/+25% to 172/3,750). This is the **default** venue, so an existing root keeps behaving exactly as before. |
| `generic` | a venue-agnostic profile: it states no limits, no legend cap and no format rule of its own. Every stage still enumerates the counts and names the limit the *target journal's own* guidelines state. |
| `example-journal` | an **illustrative template** showing the fields the other two do not exercise (a published legend limit, no cover-letter preference, an explicit journal list). Its numbers are placeholders: copy the file, replace the numbers with the ones your venue's guidelines state, cite them in `source`, and install it with `set-venue <id> --profile <file>`. |

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
| `article_type` | string | the content type the limits describe (`"Article"`, `"Research Article"`). |
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

Validation is strict and reports **every** problem at once: an unknown id, a
non-positive `base`, a `relaxation` below 1.0, a lone `base` without its
`relaxation`, an inverted cover-letter range, an invalid regex, or a
non-boolean `pdf_accepted` all fail `set-venue <id> --profile FILE` before
anything is written.

## Two worked examples

**1. Nature Biotechnology (shipped, the default).** Its numbers are the ones
the pipeline originally hard-coded; the shape is the one to copy for a real
journal:

```json
{
  "id": "nature-biotechnology",
  "label": "Nature Biotechnology",
  "short": "NBT",
  "article_type": "Article",
  "journals": ["Nature Biotechnology"],
  "journal_aliases": ["NBT", "Nat. Biotechnol."],
  "default_journal": "Nature Biotechnology",
  "length_limits": {
    "source": "Nature Biotechnology content-types table (Article: abstract <= 150 words; main text <= 3,000 words excluding abstract, Methods, references and figure legends)",
    "abstract": {"base": 150, "relaxation": 1.15},
    "main_text": {"base": 3000, "relaxation": 1.25},
    "cover_letter": {"min": 300, "max": 500, "source": "master-prompt preference; the journal states no limit"}
  },
  "captions": {"published_limit": null, "default_cap": 0, "source": "requires a legend no longer than the article type's word limit, but publishes no number"},
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

**2. A custom journal with its own numbers.** Say the venue publishes a
250-word abstract limit, a 4,000-word main text (excluding Methods and
references), a 200-word legend limit and no cover-letter rule. Everything the
pipeline needs is data:

```json
{
  "id": "custom-clin-journal",
  "label": "Custom Clinical Journal",
  "short": "CCJ",
  "article_type": "Original Research",
  "journals": ["Custom Clinical Journal"],
  "default_journal": "Custom Clinical Journal",
  "length_limits": {
    "source": "Custom Clinical Journal author instructions (2026): abstract <= 250 words; main text <= 4,000 words, Methods and references excluded",
    "abstract": {"base": 250, "relaxation": 1.1},
    "main_text": {"base": 4000, "relaxation": 1.1},
    "cover_letter": {"min": null, "max": null, "source": "the journal states no cover-letter word limit"}
  },
  "captions": {"published_limit": 200, "default_cap": 200, "source": "the journal limits each figure legend to 200 words"},
  "submission": {"pdf_accepted": true, "formats": ["PDF", "DOCX"], "pdf_note": "the journal accepts PDF submissions, and a reader or editor may open exactly that PDF"},
  "prompt": {
    "subject": "a Custom Clinical Journal original-research submission",
    "guidelines_source": "the Custom Clinical Journal author instructions (prefer a local copy in the corpus)"
  }
}
```

Install the second one with:

```bash
python paper_pipeline.py set-venue custom-clin-journal --profile custom-clin-journal.json
python paper_pipeline.py set-journal "Custom Clinical Journal"
python paper_pipeline.py status   # venue, journal and the resolved limits
```

The promoted numbers become the M19 caps (250 * 1.1 = 275; 4000 * 1.1 = 4400)
and the legend cap becomes 200 by default, because `captions.published_limit`
is set. The M18/M19 artifacts and the decision report quote
`length_limits.source`, so a reader can always see where a number came from.

## Adding a venue

1. Copy `example-journal.json` (or a shipped profile) to `<your-id>.json`.
2. Set `id` to the file's base name — `set-venue <id> --profile FILE` refuses a
   mismatch, because the file name is what the id resolves to.
3. Replace the numbers with the ones **your venue's own guidelines** state and
   quote them in `length_limits.source` / `captions.source`. Leave a limit
   `null` rather than guessing: a null limit means "the stages count and report
   against the guidelines you name", never "the pipeline invented a number".
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
| the config's `venue` and the **recorded snapshot disagree** | the config file wins and the mismatch is reported; re-run `set-venue <id>` to re-record the snapshot. |
| `pipeline_config.json` and the mirrored `state.json.config` disagree | the config file wins and a note says so (`set-venue`/`set-journal` re-mirror it). |
| a **profile file is invalid** | `set-venue --profile` fails before writing anything, listing every schema problem; an invalid file already in `venue_profiles/` is listed as `INVALID` by `set-venue --list`. |
| a **venue change on a root that already has runs** | refused unless `--force` is given: the recorded rounds were planned, prompted and judged under the previous rule set. |

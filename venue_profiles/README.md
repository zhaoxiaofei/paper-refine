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
| `nature-biotechnology` | **Nature Biotechnology** (Nature Portfolio / Springer Nature), the pipeline's **default** venue, whose numbers are now every one of them quoted from the journal's own pages (Content Types — https://www.nature.com/nbt/content — and the Matters Arising page, checked 2026-10-01): Article abstract <= 150 words and main text <= 3,000 words excluding abstract, Methods, references and figure legends (keeping the +10%/+25% margins the pipeline started with, so the promoted caps stay 165/3,750), Brief Communication abstract <= 70 words (3 sentences) with 1,000–1,500 words of main text including abstract/references/legends, Resource 100–150-word abstract and <= 3,000 words, Review 3,000–4,000, Perspective <= 3,000, Correspondence 300–800, Matters Arising "ideally not exceed 1,200" and Feature <= 3,000, all applied with no further margin (relaxation 1.0) — while Analysis (published on nature.com but absent from the Content Types page) and the non-primary types (Comment, News & Views, Book Review, Patent Article, Careers and Recruitment, Primer) deliberately carry no numbers, so selecting them counts and reports against the venue's own table instead of borrowing the Article caps. The profile also declares the venue's table rule (`tables`): the formatting guide's "Please include tables at the end of your text document", captioned before the table, with no special tables. It declares NO figure rule: that page says nothing about where figure legends belong, so nothing is invented for them. |
| `generic` | a venue-agnostic profile: one `Article` type that states no limits, no legend cap and no format rule of its own. Every stage still enumerates the counts and names the limit the *target journal's own* guidelines state. |
| `example-journal` | an **illustrative template** showing the fields the other shipped profiles do not exercise: three article types with different caps (Research Article 275/6000, Review 220/9600, Letter to the Editor with no abstract cap and an 880-word main text), a published legend limit, no cover-letter preference and an explicit journal list. Its numbers are placeholders: copy the file, replace them with the ones your venue's guidelines state, cite them in `source`, and install it with `set-venue <id> --profile <file>`. It also carries the two illustrative `special` entries the other shipped profiles do not exercise: a key-resources table that stays inside the methods without a "Table N." label, and a graphical abstract exempted from the numbered-figure rule. |
| `frontiers-in-immunology` | Frontiers in Immunology (Frontiers). A single-journal Frontiers profile: the Article-types page carries the per-type maximum word counts (Original Research 12,000; Review 12,000; Mini Review 3,000; Brief Research Report 4,000; Case Report 3,000; Opinion 2,000; General Commentary 1,000; Conceptual Analysis 8,000; ...), and the profile applies each type's own maximum with no margin (relaxation 1.0). Frontiers publishes no separate abstract word limit, no legend word limit and no cover-letter limit, so those are counted without a cap; the submission system's 200-word scope statement is carried as the venue-level cover-letter preference on top of the operator's 650-word TOTAL-content cap. Frontiers requires an editable Word or LaTeX manuscript, so submission.pdf_accepted is false. The profile also declares the venue's table rule (`tables`), quoted from the journal's own Word/LaTeX template ("Tables should be inserted at the end of the manuscript") and its Author guidelines ("Table captions must be placed immediately before the table"): tables at the end, caption before, and NO special table -- a table inherited from another publisher's template behaves like any other table. Its `figures` block is quoted from the same template's Figures section ("Figure legends should be placed at the end of the manuscript"; figures are submitted individually and embedded by the venue) with `caption: any`, because the manuscript carries the LABELLED LEGENDS, not captions beside images; a front-matter image another publisher's template added (a graphical abstract) is not exempt, since this venue names no special figure. |

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
| `sources` | object of URL/string | the profile's own provenance map (which guideline page each number came from). Carried through the loader unchanged so a stage that reads the profile through `VenueProfile.data` can name its source, as the skill instructs. Only its TYPE is validated (the loader reports a non-object value); the entries themselves are documentation, never checked. |
| `description` | string | what the profile is for; shown by `set-venue --list`. |
| `default_article_type` | slug | the type selected when the root records none. Default: the first entry. |
| `article_type_id` | slug | the resolved default type's ID, written back by the loader into the normalized profile (`venue_config`) so stages and snapshots name the type by id rather than by label. Informational; the table stays authoritative. |
| `article_types` | list | the venue's content types (see below). A profile written in the older single-type shape (`article_type` + top-level `length_limits`/`captions`, no table) is read as a one-entry table and keeps its old behaviour. |
| `article_type` | string | the DEFAULT type's label, as resolved by the pipeline (informational; the table is authoritative). |
| `journals`, `journal_aliases` | list of strings | the journals this profile claims to describe. A journal outside the list is reported as an inconsistency (fatal under `--strict-venue`). |
| `journal_patterns` | list of regexes | extra journal names, matched case-insensitively. |
| `accepts_any_journal` | bool | `true` = never report a journal/venue mismatch (the shipped `generic` profile). |
| `default_journal` | string | used when the root records no journal; `""` = no default (the prompts then say "the target journal"). |
| `length_limits.source` | string | provenance quoted in the M19 artifacts, in `setup`/`status`, and in the decision report. |
| `length_limits.abstract` | `{base, relaxation}` | the abstract's own limit and the margin this pipeline relaxes it by (both `null` = the profile sets none). |
| `length_limits.main_text` | `{base, relaxation}` | same, for the main text. |
| `length_limits.cover_letter` | `{min, max, total_max, source}` | the preference for the persuading part: a range (`min`+`max`), a one-sided bound (`max` alone = "at most N words", as Frontiers' 200-word scope statement; `min` alone = "at least N words"), or `null`/`null` = none. `total_max` is the operator's TOTAL-content cap (salutation, body, disclosures and signature; 650 by default) and must not sit below `max`. Never a gate. |
| `captions.published_limit` | int or `null` | the venue's own published legend limit, when there is one. |
| `captions.default_cap` | int | the legend cap used when `setup` was run without `--caption-limit`; `0` = counts only. |
| `captions.source` | string | what the venue says about legend length (quoted in the M18 rule). |
| `tables`, `figures` | object or absent | the venue's table / figure rules (see below; one shared schema). Absent = the profile declares no rule for that kind: the code-side scan emits no rows for it and no stage is gated on one. |
| `foreign_container_headings` | list of strings | headings that belong to ANOTHER publisher's template ("Lead contact", "Key resources", …) and that this venue does not use. Validated by the loader and read through `venue_containers()` by the formatter; absent = the empty list, so a profile that does not declare them flags nothing. |
| `leftover_phrases` | list of strings | the same idea at PHRASE level: another publisher's boilerplate that a transferred manuscript may still carry in running text ("lead contact", "this study did not generate new unique reagents", "requests for resources"). The code-side scan reports one `FMT-L1` row per occurrence (finding tier, author decides: remove it or replace it with the venue's own statement); absent = no rows, so the pipeline never invents a leftover rule. |
| `numbering` | `"citation"` or `"none"` | how the venue numbers its display items. `"citation"` makes the scan compare the order of first mentions with the numbers themselves and report `FMT-O1` for an item cited out of order; absent/`"none"` = the venue states no convention and no ordering row is emitted. |
| `references` | object or absent | the reference-entry policy. `{"flag_preprints": true}` makes `FMT-R5` report every preprint / trial-in-progress reference so the author confirms the venue accepts it. The shape rules `FMT-R1`–`FMT-R4` (a malformed journal/volume field, an entry with no venue, an unversioned repository citation, a bioRxiv-style identifier with a foreign DOI prefix) are objective and always run. |
| `submission.pdf_accepted` | bool or `null` | whether the venue accepts a submitted PDF. |
| `submission.formats` | list of strings | accepted formats, for the record. |
| `submission.pdf_note` | string | the sentence the derived-outputs rule uses about a submitted PDF. |
| `prompt.subject` | string | the opening phrase of the master prompt ("Review and revise **an Example Journal research-article submission**, …"). |
| `prompt.editor` | string | "anything **an Example Journal editor or reviewer** could raise". |
| `prompt.requirements` | string | "judged against **the Example Journal author guidelines and submission requirements**". |
| `prompt.requirement_authority` | string | "unless such formatting is required or recommended by **the Example Journal guidelines**". |
| `prompt.guidelines_source` | string | the guidelines source the review is told to read. |

### `tables` and `figures`

Where a table or a figure belongs and what labels it is a DECIDED venue fact, so
it is profile data (venue-level, like `captions`), never a pipeline assumption.
The two blocks share ONE schema and one validator; a profile may declare either,
both or neither:

| field | type | meaning |
|---|---|---|
| `source` | string | where the rule comes from (the venue's own template sentence and/or author guidelines, with the retrieval date). Rendered into every prompt and quoted in `status`. |
| `note` | string | free-text context, e.g. that the venue declares NO special item and what happens to a previous publisher's furniture. |
| `placement` | `"end"` \| `"inline"` \| `"any"` | `end` = the items (a table; a figure legend, or the figure itself when it is embedded) belong together in that kind's area at the end of the manuscript; `inline`/`any` = not pinned (no placement check). |
| `caption` | `"before"` \| `"after"` \| `"any"` | which side of the item carries its caption paragraph. `any` means the venue does not pin it — the right choice when the guidelines collect figure legends at the end, so an image is not expected to carry its legend next to it. |
| `special` | list | the items THIS venue genuinely treats differently. Each entry: `match` (a regular expression over the item's context — the nearest paragraph above it, its section heading or, for a table, its first-row header), and optionally `placement` (`inline` = leave it where it is), `caption` (`"none"` = this item needs no caption) plus `source`/`note`. An entry overrides only the fields it states. |

The pipeline hands the blocks to the formatter as `policy["tables"]` /
`policy["figures"]`, so `paper_docx_format.py scan` reports exactly what they
declare — `FMT-TB1`/`FMT-TB2`/`FMT-TB3` and `FMT-FG1`/`FMT-FG2`/`FMT-FG3` (no
caption / caption on the wrong side / item before its area) — in
`FORMAT_SCAN.json` and the M20 artifact, and a package-producing stage
(rewrite/revise/integrate and the template-first `conform`) FAILS while its
delivered package still carries one of those rows. The check runs on the
manuscript body only: a supplementary-material, cover-letter or
feedback/response document has its own conventions and is skipped. Every
session's sandbox also carries the blocks as `format_policy.json`, so the
session's own `python paper_docx_format.py scan <dir> --policy
format_policy.json` checks the same rules. With no block for a kind the scan
emits no rows for it and nothing is gated: a rule no level of the authority
chain states is never invented.

`figures.special` is where a front-matter item the venue numbers outside the
figure sequence belongs — a graphical abstract, a graphical table of contents —
so the numbered-figure rule neither renumbers it nor moves it; the shipped
`example-journal` profile carries that entry (and a key-resources
`tables.special` entry) as a working, explicitly illustrative example.

One compatibility note: a root recorded before these fields existed has a
profile snapshot without `tables`/`figures` keys. Such a snapshot inherits the
shipped profile file's blocks (and ONLY those; every other recorded rule still
wins), each one only when the snapshot does not carry its key at all. A
snapshot that carries its own key — including an empty block — is
authoritative, and `set-venue` re-records it as usual.

### `article_types[]`

Each entry is one content type of the venue:

| field | type | meaning |
|---|---|---|
| `id` | slug | what `--article-type`/`set-article-type` take (`article`, `brief-communication`, …). Default: the label, slugified. |
| `label` | string | how the venue writes the type ("Brief Communication"); used in the prompts and listed by `set-article-type --list`. |
| `source` | string | where the type (and its numbers) come from — quoted when the profile carries no numbers for it. |
| `length_limits` | object or `null` | the type's own limits, exactly like the top-level block above. **`null` (or a block with `base: null` for abstract/main_text) means "this profile carries no numbers for this type"**: the stages count the section and name the limit the venue's own content-types table states — they never borrow another type's caps. |
| `captions` | object or `null` | the type's legend policy; `null`/absent inherits the default type's policy (the legend rule is venue-wide in practice). |

Abstract and main-text limits are **per type**. The cover-letter preference, its
**`total_max`** (the operator's TOTAL-content cap for the letter — salutation,
body, disclosures and signature; 650 words in the shipped default) and the
legend policy are **per venue**: a type that does not state them inherits the
default type's, so a venue's "300–500 words in the persuading part" is not
re-declared for every type. `total_max` must not be below the persuading-part
`max` — a letter that cannot even hold its persuading part is a schema error.

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
        "abstract": {"base": 150, "relaxation": 1.10},
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

### Adding a venue with an agent (`add-venue`)

The manual steps above can be driven by an LLM session:

```bash
python paper_pipeline.py add-venue <venue-id> --journal "Journal Name" \
        [--agent codex|claude|manual] [--agent-cmd '<json argv>'] [--timeout S]
```

The session (a) writes/updates `<venue-id>.json` against the schema in this
file, with every number citing the venue's own guidelines, (b) adds one row to
the "Shipped profiles" table below, (c) downloads the venue's OWN official
Word/LaTeX template archives into `<venue-id>.official/` (unzipped, with a
source/license/retrieval manifest) when the venue publishes them, and
(d) downloads 8-15 recent OA articles of the requested article type into
`<venue-id>.manuscripts/`, preferring the venue's own website/OA pages, saving a
structure-only Markdown transcription (headings + statement names, never prose)
for each, plus a `manifest.json` with source URL/DOI/license/retrieval date.
`--agent manual` only stages the prompt; `--no-download` turns (c) and (d) into
an explicit skip. The orchestrator then VALIDATES the JSON and derives the
template pack itself.

The agent runs in a sandbox that can only write inside itself, so it stages the
store's own layout under `<sandbox>/store/` and the ORCHESTRATOR publishes that
tree into this directory (profile, README row, `.official/`, `.manuscripts/`).
If a session finished but its work is still only staged (an older run, a
read-only mount, an interrupted session), publish it without re-running the
agent:

```bash
python paper_pipeline.py add-venue <venue-id> --publish-only
# or from a specific sandbox:  --publish-only --from-sandbox <dir>
```

The README row is taken from the staged README when it names the id; otherwise
the orchestrator SYNTHESIZES the row from the validated profile, so the venue is
always listed (a session that refreshed another venue's row for the same
journal cannot leave the new id unlisted).

### Exemplar manuscripts and the generated template pack

A venue MAY ship THREE sibling directories of its profile:

| directory | what it holds |
|---|---|
| `<venue-id>.official/` | the journal's OWN template files (Word `.docx`/`.dotx` -- the manuscript template, an optional supplementary template, and, when the journal publishes one, a cover-letter template whose file name carries "cover"/"letter"; LaTeX `.tex`/`.cls`/`.sty`) + a `manifest.json` with source URL/license/retrieval. **AUTHORITATIVE**: its class file, mandatory sections and declaration wording win over everything the code infers. A cover letter is restyled only into a cover-letter template; with none it follows the journal's cover-letter guidance and then academic convention, never the manuscript template. |
| `<venue-id>.manuscripts/` | recently published OA articles of the venue (or their structure-only transcriptions). Read ONLY for structure; never treated as submission text and never shipped in a package. |
| `<venue-id>.templates/` | the DERIVED, pinned pack: `structure.json`, `venue_architecture.md`, `word-template.md`, `latex-template.tex` and `MANIFEST.json` (sha256 of every input exemplar and every output; no timestamps, so two builds are byte-identical). |

```bash
python paper_pipeline.py build-venue-templates --venue <id> [--profiles-dir DIR] [--root DIR]
```

derives the pack from whatever inputs are present, code-side and
deterministically. Two tiers, with different authority:

* the **OFFICIAL** tier (from `<venue-id>.official/`): the class file, the
  section skeleton with its MANDATORY sections, and the declaration blocks in
  the template's own wording. An operator may pin extra mandatory sections in
  `<venue-id>.official/requirements.json`
  (`{"mandatory_sections": ["..."]}`);
* the **recent-practice** tier (from `<venue-id>.manuscripts/`): the modal
  section order with presence counts and mean positions, abstract presence and
  statement placement. **ADVISORY**, filling what the official template leaves
  open.

The `word-template.md` and `latex-template.tex` skeletons follow the official
skeleton (and the official `\documentclass`) when one exists, otherwise the
modal order. The review and rewrite sessions receive `venue_architecture.md`
through their prompts; the code-side conformance rows
(`work/OFFICIAL_TEMPLATE.md`) name a missing mandatory section, a missing
statement block or a wrong class file. A template requirement the manuscript
cannot supply becomes a MANUAL item for the author, never invented text; no
prose from an exemplar or a template sample is ever copied; neither tier is a
gate by itself, and the venue's author guidelines still come first.

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
| a **type the profile carries no numbers for** (e.g. Analysis in the shipped Nature Biotechnology profile) | reported as a note. The stages count the abstract/main text and name the limit the venue's own content-types table states; the Article caps are never borrowed, and the M19 code-side scan reports `cap: null` rather than a violation. |
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

# -*- coding: utf-8 -*-
# Part 01/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# VENUES AND JOURNALS
# =====================================================================
# A VENUE and a JOURNAL are two different things, and the pipeline keeps them
# apart:
#
#   * the VENUE is the requirement set a stage enforces: the submission rules
#     of a publishing venue (article-type word limits, figure-legend policy,
#     accepted submission formats, and so on). It is selected by ID and
#     realised by a venue PROFILE -- a JSON document, shipped under
#     `venue_profiles/` or written into the root by the operator. One profile
#     may cover a single journal ("nature-biotechnology"), a journal family
#     ("nature-portfolio") or no journal at all ("generic").
#   * the JOURNAL is the publication the manuscript is going to: free text
#     ("Nature Biotechnology", "Cell", "eLife"), used by the prompts to say
#     what the submission is for and to check it against the venue's rules.
#     On its own it selects nothing.
#
# A venue publishes several ARTICLE TYPES (Article, Brief Communication,
# Review, Resource, Analysis, Matters Arising, Letter to the Editor, ...), and
# the limits belong to the TYPE, not to the venue as a whole. The profile
# carries the venue's table (`article_types`), the root records which type the
# submission is (`setup --article-type`, `set-article-type`), and a type whose
# numbers the profile does not carry is COUNTED and reported against the
# venue's own content-types table -- never measured against another type's caps.
#
# All three live in `<root>/pipeline_config.json` (`venue`, `journal`,
# `article_type`) with a snapshot of the resolved profile (`venue_profile`), so
# a root keeps enforcing the rules it was set up with even if the shipped
# profiles change later. The precedence, highest first, is:
#
#   1. the flags of the command being run (`setup --venue/--journal`);
#   2. the root's pipeline_config.json (written by `setup`, `set-venue`,
#      `set-journal`);
#   3. the venue profile's `default_journal` (when no journal is recorded);
#   4. the built-in defaults: venue `nature-biotechnology` (this pipeline's
#      pre-venue behaviour) with no journal beyond that profile's default.
#
# A root whose venue is missing keeps working on the default venue (backward
# compatibility); a root whose venue ID resolves to nothing is reported by
# `status` and refused by the commands that must render prompts (see
# venue_profile_of / venue_config_findings). `--strict-venue` turns the
# MISSING or INCONSISTENT cases into hard errors, for a run that must not start
# on a guess (an unresolvable venue is refused either way, by every command that
# has to render a prompt).
VENUE_PROFILES_DIRNAME = "venue_profiles"
VENUE_PROFILE_SUFFIX = ".json"
VENUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
JOURNAL_ALIAS_SPLIT_RE = re.compile(r"[^a-z0-9]+")


class VenueProfileError(ValueError):
    """A venue profile that cannot be used as written (or does not exist)."""

    def __init__(self, message: str, *, unknown: bool = False):
        super().__init__(message)
        self.unknown = unknown


def _journal_key(text) -> str:
    """A journal name reduced to letters/digits, for alias comparison."""
    return JOURNAL_ALIAS_SPLIT_RE.sub("", str(text or "").lower())


# The profiles shipped with this file, so a copy of paper_pipeline.py without the
# `venue_profiles/` directory (a stripped single-file copy, a root created
# before the profiles were copied into it) still runs with a known rule set.
# `venue_profiles/nature-biotechnology.json` and `venue_profiles/generic.json`
# carry the same data; the files are the editable copy, this is the fallback.
_DEFAULT_VENUE_PROFILE = {
    "id": "nature-biotechnology",
    "label": "Nature Biotechnology",
    "short": "NBT",
    "description": "Nature Biotechnology (Nature Portfolio): the pipeline's original, "
                   "pre-venue requirement set. It carries the venue's content types; the "
                   "Article limits are the ones this pipeline was originally written for and "
                   "are the only ones the profile states numbers for (the others are counted "
                   "and reported against the venue's own content-types table, never against "
                   "the Article caps).",
    "journals": ["Nature Biotechnology"],
    "journal_aliases": ["NBT", "Nat. Biotechnol.", "Nature Biotech",
                        "Nature Biotechnology (NBT)"],
    "default_journal": "Nature Biotechnology",
    # Another publisher's block headings are DATA this profile declares (the
    # formatter's own default is empty, so the engine carries no venue's
    # vocabulary). TOP-LEVEL: `venue_containers()` reads it here, never from an
    # article type.
    "foreign_container_headings": ["Lead contact", "Resource availability",
                                   "Materials availability", "Method details",
                                   "Key resources", "Key resources table"],
    # Another publisher's boilerplate the manuscript may still carry after a
    # transfer (FMT-L1). Nature Biotechnology uses none of it.
    "leftover_phrases": ["lead contact", "this study did not generate new unique reagents",
                         "requests for resources"],
    # Display items are numbered by first citation (FMT-O1).
    "numbering": "citation",
    # A preprint is not a published article: report one so the author decides
    # whether the venue accepts it (FMT-R5).
    "references": {"flag_preprints": True},
    # The venue's own figure-type floor (FMT-IM6). The JSON profile carries the
    # same block; this is the stripped-single-file fallback.
    "figure_text": {"min_pt": 5,
                    "source": "Nature portfolio figure guidelines: the smallest text "
                              "in a figure should be at least 5 pt at the printed size "
                              "(checked 2026-10-01)"},
    "image_dpi": {"min_dpi": 450,
                  "source": "Nature portfolio figure guidelines: images at least 450 "
                            "dpi at final size (checked 2026-10-01)"},
    # The venue's content types. Only `article` carries numbers here (the ones
    # this pipeline has always used, from the venue's content-types table); the
    # other entries exist so a submission can DECLARE its type, and a type with
    # no numbers is counted and reported instead of being measured against the
    # Article caps. Fill a type's numbers in from the venue's table (in your own
    # copy of the profile) to have the pipeline enforce them.
    "default_article_type": "article",
    "article_types": [
        {"id": "article", "label": "Article",
         "source": "Nature Biotechnology content-types table",
         "length_limits": {
             "source": "Nature Biotechnology content-types table (Article: abstract <= 150 "
                       "words; main text <= 3,000 words excluding abstract, Methods, "
                       "references and figure legends)",
             "abstract": {"base": 150, "relaxation": 1.10},
             "main_text": {"base": 3000, "relaxation": 1.25},
             "cover_letter": {
                 "min": 300, "max": 500, "total_max": None,
                 "source": "master-prompt preference (300-500 words in the persuading part); "
                           "Nature Biotechnology's official guidance states no cover-letter "
                           "word limit (checked 2026-09-19), so no total-content cap is "
                           "applied",
             },
         },
         "captions": {
             "published_limit": None,
             "default_cap": 0,
             "source": "Nature Biotechnology requires that a legend \"does not exceed the word "
                       "limit of the article type\" but does not publish that number on its "
                       "public pages (checked 2026-09-19)",
         }},
        *[{"id": tid, "label": label, "source": "Nature Biotechnology content-types table",
           "length_limits": {
               "source": f"Nature Biotechnology content-types table ({label}: this profile "
                         f"carries no number for that type -- the stage names the abstract and "
                         f"main-text limits the table states, with their source)",
               "abstract": {"base": None, "relaxation": None},
               "main_text": {"base": None, "relaxation": None},
           }}
          for tid, label in (("brief-communication", "Brief Communication"),
                             ("review", "Review"),
                             ("perspective", "Perspective"),
                             ("analysis", "Analysis"),
                             ("resource", "Resource"),
                             ("correspondence", "Correspondence"),
                             ("matters-arising", "Matters Arising"))],
    ],
    "submission": {
        "pdf_accepted": True,
        "formats": ["PDF", "Word", "TeX/LaTeX"],
        "pdf_note": "Nature Biotechnology accepts a PDF as the initial submission file "
                    "(\"We accept initial submissions in PDF, Word or TeX/LaTeX formats\" "
                    "-- submission guidelines, checked 2026-09-19), and a reader/editor "
                    "may open exactly that PDF",
    },
    "prompt": {
        "subject": "a Nature Biotechnology (NBT) manuscript submission",
        "editor": "a Nature Biotechnology editor or reviewer",
        "requirements": "the Nature Biotechnology author guidelines and submission "
                        "requirements",
        "requirement_authority": "Nature Biotechnology",
        "guidelines_source": "the current Nature Biotechnology author guidelines",
    },
}

_GENERIC_VENUE_PROFILE = {
    "id": "generic",
    "label": "generic venue (no venue-specific rules)",
    # "short" is the noun the prompts drop into phrases like "not a <short>
    # rule"; for a venue with no brand, the honest noun is the venue itself.
    "short": "VENUE",
    "description": "A venue-agnostic profile: it sets no word limits, no legend cap and no "
                   "submission-format rule of its own. Every stage still enumerates the "
                   "counts, and the artifact must name the limit the target journal's own "
                   "guidelines state, with its source. Use it when the venue publishes no "
                   "rule the pipeline can carry, or as the starting point for a custom "
                   "profile (`set-venue <id> --profile FILE`).",
    "default_article_type": "article",
    "article_types": [
        {"id": "article", "label": "Article",
         "source": "the target journal's own author guidelines",
         "length_limits": {
             "source": "the target journal's own author guidelines (this venue profile publishes "
                       "no number; the stage names the limit and its source in its artifact)",
             "abstract": {"base": None, "relaxation": None},
             "main_text": {"base": None, "relaxation": None},
             "cover_letter": {
                 "min": 300, "max": 500,
                 "source": "master-prompt preference (300-500 words in the persuading part); the "
                           "venue profile states no venue cover-letter limit",
             },
         },
         "captions": {
             "published_limit": None,
             "default_cap": 0,
             "source": "this venue profile states no figure-legend length rule; every legend's "
                       "word count is recorded and compared with the target journal's own "
                       "guidelines by the author",
         }},
    ],
    "journals": [],
    "journal_aliases": [],
    "accepts_any_journal": True,
    "default_journal": "",
    "submission": {
        "pdf_accepted": None,
        "formats": [],
        "pdf_note": "this venue profile does not state which formats the venue accepts, and a "
                    "reader or editor may still open the PDF shipped beside the editable "
                    "source",
    },
    "prompt": {
        "subject": "a manuscript submission for the target journal",
        "editor": "an editor or reviewer at the target journal",
        "requirements": "the target journal's author guidelines and submission requirements",
        "requirement_authority": "the target journal",
        "guidelines_source": "the target journal's author guidelines (prefer a local copy "
                             "in the corpus)",
    },
}

def _shipped_default_venue_profile() -> dict:
    """The default profile's SINGLE SOURCE OF TRUTH.

    `add-venue` can update the shipped `venue_profiles/<default>.json` with
    numbers verified against the journal's own pages and new article types.
    A normal checkout always reads the shipped file (the single source of
    truth); the embedded literal below is only the fallback for a STRIPPED
    deployment (script only, no venue_profiles/). That fallback is the
    pipeline's original pre-venue requirement set, so it deliberately carries
    FEWER article types (8, Article-only numbers) than the shipped profile --
    a stripped deployment runs the legacy rule set, not a mirrored copy of the
    curated one.
    """
    try:
        p = (Path(__file__).resolve().parent / VENUE_PROFILES_DIRNAME
             / f"{DEFAULT_VENUE}{VENUE_PROFILE_SUFFIX}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) \
                and str(data.get("id") or "").strip().lower() == DEFAULT_VENUE:
            return data
    except (OSError, ValueError, NameError):
        pass
    return copy.deepcopy(_DEFAULT_VENUE_PROFILE)


BUILTIN_VENUE_PROFILES = {
    DEFAULT_VENUE: _shipped_default_venue_profile(),
    _GENERIC_VENUE_PROFILE["id"]: _GENERIC_VENUE_PROFILE,
}


def _profile_int(value, field: str, problems: list, *, minimum=None, allow_none=True):
    """An optional non-negative integer profile field."""
    if value is None:
        if allow_none:
            return None
        problems.append(f"{field} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{field} must be an integer (got {value!r})")
        return None
    if minimum is not None and value < minimum:
        problems.append(f"{field} must be >= {minimum} (got {value})")
        return None
    return value


def _profile_str_list(value, field: str, problems: list) -> list:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        problems.append(f"{field} must be a list of strings")
        return []
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            problems.append(f"{field} must hold non-empty strings (got {item!r})")
            continue
        out.append(item.strip())
    return out


def _slugify_article_type(label: str) -> str:
    """`Brief Communication` -> `brief-communication` (an id from a label)."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(label or "").strip().lower()).strip("-")
    return slug or "default"


# ---- The venue's MAIN-TEXT COUNTING CONVENTION (check id M19) -------------
#
# What a venue's word limit MEANS is part of the venue's rule, not a pipeline
# assumption: Nature Biotechnology's Article counts main text with the abstract,
# Methods, references and figure legends excluded, its Brief Communication counts
# 1,000-1,500 words INCLUDING abstract, references and figure legends, and
# Frontiers counts the main body WITH Methods and in-text citations. A counter
# that always stops at Methods under-counts a Frontiers manuscript against
# Frontiers' own number. The profile therefore states, per venue (and per article
# type where the types differ), which section kinds its main-text count EXCLUDES;
# unlisted kinds are inside the count.
#
# `DEFAULT_MAIN_TEXT_EXCLUDES` is the pipeline's historical behaviour (the NBT
# Article convention), kept as the default so a profile written before this
# field, or one that states no convention, counts exactly as it always did.
MAIN_TEXT_SECTION_KINDS = ("abstract", "methods", "references", "figure-legends",
                          "acknowledgements", "author-contributions",
                          "data-availability", "competing-interests", "funding",
                          "supplementary", "table-captions")
# Table captions are a caption KIND, not a section heading: a venue states them
# only when it groups them with figure legends (Frontiers' "figure and table
# captions"). The historical default excluded figure legends only, so the new
# kind is opt-in and never changes a profile that does not name it.
DEFAULT_MAIN_TEXT_EXCLUDES = tuple(
    kind for kind in MAIN_TEXT_SECTION_KINDS if kind != "table-captions")


def _clean_counting(counting, prefix: str, problems: list):
    """Validate ONE `counting` block (the venue's or an article type's).

    `None` means "this profile states no convention": the pipeline's default
    (the NBT Article convention) applies. An explicit block MUST state
    `main_text.excludes`; an empty list is meaningful and means "nothing is
    excluded" (a venue that counts the whole document).
    """
    if counting is None:
        return None
    if not isinstance(counting, dict):
        problems.append(f"{prefix} must be an object, or null for the pipeline's default "
                        f"counting convention (got {type(counting).__name__})")
        return None
    main = counting.get("main_text")
    if not isinstance(main, dict):
        problems.append(f"{prefix}.main_text must be an object stating 'excludes' (the "
                        f"section kinds the venue leaves OUT of its main-text count)")
        return None
    raw = main.get("excludes")
    if not isinstance(raw, list):
        problems.append(f"{prefix}.main_text.excludes must be a list of section kinds "
                        f"({', '.join(MAIN_TEXT_SECTION_KINDS)}); an empty list means "
                        f"nothing is excluded")
        raw = []
    excludes: list = []
    for item in raw:
        kind = str(item or "").strip().lower().replace("_", "-")
        if kind not in MAIN_TEXT_SECTION_KINDS:
            problems.append(f"{prefix}.main_text.excludes entry {item!r} is not a section "
                            f"kind ({', '.join(MAIN_TEXT_SECTION_KINDS)})")
            continue
        if kind in excludes:
            problems.append(f"{prefix}.main_text.excludes lists {kind!r} twice")
            continue
        excludes.append(kind)
    return {"main_text": {"excludes": excludes,
                          "source": str(main.get("source") or "").strip(),
                          "note": str(main.get("note") or "").strip()}}


def _clean_length_limits(limits, prefix: str, problems: list):
    """Validate ONE `length_limits` block (the venue's or an article type's).

    `None` means "this profile carries no numbers here". That is deliberately
    NOT the same as inheriting another article type's numbers: a Brief
    Communication must never be measured against the Article caps, so a type
    without numbers is reported as counts-only and the stage names the limit
    the venue's own table states.
    """
    if limits is None:
        return None
    if not isinstance(limits, dict):
        problems.append(f"{prefix} must be an object, or null for \"no numbers carried\" "
                        f"(got {type(limits).__name__})")
        return None
    clean = {"source": str(limits.get("source") or "").strip()}
    for key in ("abstract", "main_text"):
        spec = limits.get(key)
        if spec is None:
            spec = {}
        if isinstance(spec, (int, float)) and not isinstance(spec, bool):
            # A bare number = base words, no relaxation. Leaving `relaxation`
            # unset made the pairing validator below reject every such profile
            # ("base and relaxation must be given together"), so the documented
            # shorthand could never load.
            spec = {"base": spec, "relaxation": 1.0}
        if not isinstance(spec, dict):
            problems.append(f"{prefix}.{key} must be an object with 'base' and "
                            f"'relaxation' (or null for both)")
            spec = {}
        base = spec.get("base")
        relaxation = spec.get("relaxation")
        if base is None and relaxation is None:
            clean[key] = {"base": None, "relaxation": None}
            continue
        pairing_error = (base is None) != (relaxation is None)
        base = _profile_int(base, f"{prefix}.{key}.base", problems, minimum=1)
        try:
            relaxation = float(relaxation) if relaxation is not None else None
        except (TypeError, ValueError):
            problems.append(f"{prefix}.{key}.relaxation must be a number >= 1.0 "
                            f"(got {relaxation!r})")
            relaxation = None
        if relaxation is not None and relaxation < 1.0:
            problems.append(f"{prefix}.{key}.relaxation must be >= 1.0 (got "
                            f"{relaxation:g}); the pipeline only relaxes a limit, never "
                            f"tightens it")
            relaxation = None
        if pairing_error:
            problems.append(f"{prefix}.{key}: 'base' and 'relaxation' must be given "
                            f"together (or both null)")
        clean[key] = {"base": base, "relaxation": relaxation}
    # Distinguish "this type states no cover letter at all" (inherit the
    # default type's, handled in length_limits()) from "this type explicitly
    # states no preference" (min/max null): the README documents the latter as
    # none, so the block must survive normalization with its source intact.
    cover_stated = isinstance(limits.get("cover_letter"), dict)
    cover = limits.get("cover_letter") or {}
    if not isinstance(cover, dict):
        problems.append(f"{prefix}.cover_letter must be an object with 'min' and 'max' "
                        f"(or null for both)")
        cover = {}
    cover_min = _profile_int(cover.get("min"), f"{prefix}.cover_letter.min", problems,
                             minimum=0)
    cover_max = _profile_int(cover.get("max"), f"{prefix}.cover_letter.max", problems,
                             minimum=0)
    if cover_min is not None and cover_max is not None and cover_min > cover_max:
        problems.append(f"{prefix}.cover_letter.min ({cover_min}) must not exceed "
                        f"max ({cover_max})")
    cover_total = _profile_int(cover.get("total_max"), f"{prefix}.cover_letter.total_max",
                               problems, minimum=1)
    if cover_total is not None and cover_max is not None and cover_total < cover_max:
        problems.append(f"{prefix}.cover_letter.total_max ({cover_total}) must not be below "
                        f"the persuading-part max ({cover_max})")
    if cover_stated:
        clean["cover_letter"] = {"min": cover_min, "max": cover_max,
                                 "total_max": cover_total,
                                 "source": str(cover.get("source") or "").strip()}
    return clean


_CAPTION_CAP_MISSING = object()


def _clean_captions(captions, prefix: str, problems: list):
    """Validate one legend policy block; None means "inherit the venue's"."""
    if captions is None:
        return None
    if not isinstance(captions, dict):
        problems.append(f"{prefix} must be an object, or null to inherit the venue's legend "
                        f"policy (got {type(captions).__name__})")
        return None
    raw_cap = captions.get("default_cap", _CAPTION_CAP_MISSING)
    clean = {
        "published_limit": _profile_int(captions.get("published_limit"),
                                        f"{prefix}.published_limit", problems, minimum=0),
        "default_cap": _profile_int(
            0 if raw_cap is _CAPTION_CAP_MISSING else raw_cap,
            f"{prefix}.default_cap", problems, minimum=0, allow_none=False) or 0,
        "source": str(captions.get("source") or "").strip(),
    }
    # An OMITTED key inherits the venue's published limit; an EXPLICIT 0 is
    # the documented "counts only" choice and must survive unchanged.
    if (clean["published_limit"] is not None
            and raw_cap is _CAPTION_CAP_MISSING):
        clean["default_cap"] = clean["published_limit"]
    return clean


EMPTY_LENGTH_LIMITS = {"source": "", "abstract": {"base": None, "relaxation": None},
                       "main_text": {"base": None, "relaxation": None},
                       "cover_letter": {"min": None, "max": None, "total_max": None, "source": ""}}
EMPTY_CAPTIONS = {"published_limit": None, "default_cap": 0, "source": ""}
# The venue's DISPLAY-ITEM rules (the formatter's `policy["tables"]` and
# `policy["figures"]`, rules FMT-TB1..3 / FMT-FG1..3): where a table or a figure
# belongs, which side of it carries its caption, and the items the venue itself
# treats differently. An EMPTY block means "this profile declares no rule for
# that kind" -- the scan then reports none, and no stage is gated on one (a rule
# no level of the authority chain states is never invented). The two blocks have
# the SAME schema, so they share one validator.
DISPLAY_PLACEMENTS = ("end", "inline", "any")
DISPLAY_CAPTION_SIDES = ("before", "after", "any")
EMPTY_TABLES = {"source": "", "note": "", "placement": "", "caption": "", "special": []}
EMPTY_FIGURES = {"source": "", "note": "", "placement": "", "caption": "", "special": []}


def _declares_display_rule(block: dict) -> bool:
    """Does a `tables`/`figures` block state a rule (not just a source/note)?

    A block that carries only a `source`/`note` states no rule, so nothing is
    checked or gated on it; a `placement` or a `caption` value (or a
    special-item entry) is a rule the stages enforce.
    """
    return bool((block or {}).get("placement") or (block or {}).get("caption")
                or (block or {}).get("special"))


def _clean_display_rules(raw, prefix: str, problems: list):
    """Validate one venue TABLE/FIGURE policy block; None means "declares none".

    The block is DATA, exactly like the caption policy: the pipeline renders it
    into the prompts and hands it to the formatter as `policy["tables"]` /
    `policy["figures"]`, and the formatter checks exactly what it states.
    `special` entries exist for the items a publisher genuinely treats
    differently (a Cell Press-style key-resources table that lives inside the
    methods and carries no "Table N." label; a front-matter figure such as a
    graphical abstract that is not part of the numbered figure sequence); each
    entry overrides only the fields it sets.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append(f"{prefix} must be an object, or null when the venue profile declares "
                        f"no rule for that kind (got {type(raw).__name__})")
        return None
    placement = str(raw.get("placement") or "").strip().lower()
    if placement and placement not in DISPLAY_PLACEMENTS:
        problems.append(f"{prefix}.placement {placement!r} is not one of "
                        f"{', '.join(DISPLAY_PLACEMENTS)}")
    caption = str(raw.get("caption") or "").strip().lower()
    if caption and caption not in DISPLAY_CAPTION_SIDES:
        problems.append(f"{prefix}.caption {caption!r} is not one of "
                        f"{', '.join(DISPLAY_CAPTION_SIDES)}")
    specials, seen = [], set()
    for i, entry in enumerate(raw.get("special") or []):
        if not isinstance(entry, dict):
            problems.append(f"{prefix}.special[{i}] must be an object")
            continue
        match = str(entry.get("match") or "").strip()
        if not match:
            problems.append(f"{prefix}.special[{i}].match is required (a regular expression "
                            f"over the item's context: the text above it, its section heading "
                            f"or, for a table, its first-row header)")
            continue
        try:
            re.compile(match)
        except re.error as e:
            problems.append(f"{prefix}.special[{i}].match {match!r} is not a regular "
                            f"expression: {e}")
        if match.lower() in seen:
            problems.append(f"{prefix}.special: duplicate match {match!r}")
        seen.add(match.lower())
        s_placement = str(entry.get("placement") or "").strip().lower()
        if s_placement and s_placement not in DISPLAY_PLACEMENTS:
            problems.append(f"{prefix}.special[{i}].placement {s_placement!r} is not one of "
                            f"{', '.join(DISPLAY_PLACEMENTS)}")
        s_caption = str(entry.get("caption") or "").strip().lower()
        if s_caption and s_caption not in DISPLAY_CAPTION_SIDES + ("none",):
            problems.append(f"{prefix}.special[{i}].caption {s_caption!r} is not one of "
                            f"{', '.join(DISPLAY_CAPTION_SIDES + ('none',))}")
        specials.append({"match": match, "placement": s_placement, "caption": s_caption,
                         "source": str(entry.get("source") or "").strip(),
                         "note": str(entry.get("note") or "").strip()})
    return {"source": str(raw.get("source") or "").strip(),
            "note": str(raw.get("note") or "").strip(),
            "placement": placement if placement in DISPLAY_PLACEMENTS else "",
            "caption": caption if caption in DISPLAY_CAPTION_SIDES else "",
            "special": specials}


def normalize_venue_profile(data, origin: str = "<builtin>") -> dict:
    """Validate a venue profile and fill its defaults, or raise VenueProfileError.

    The schema is documented in `venue_profiles/README.md`. Everything the
    pipeline reads is validated here, once, at the boundary: a profile that
    passes is safe for every stage to consume, and a profile that does not is
    reported with every problem it has (not just the first one).
    """
    if not isinstance(data, dict):
        raise VenueProfileError(f"{origin}: a venue profile must be a JSON object "
                                f"(got {type(data).__name__})")
    problems: list = []
    out = copy.deepcopy(data)

    venue_id = str(out.get("id") or "").strip().lower()
    if not venue_id:
        problems.append("'id' is required (a short slug, e.g. \"nature-biotechnology\")")
    elif not VENUE_ID_RE.match(venue_id):
        problems.append(f"'id' {venue_id!r} is not a slug: letters, digits, '.', '_', '+', "
                        f"'-' only")
    label = str(out.get("label") or "").strip()
    if not label:
        label = venue_id or "(unnamed venue)"
    short = str(out.get("short") or "").strip() or label
    article_type = str(out.get("article_type") or "").strip() or "Article"

    # ---- the venue's ARTICLE TYPES -------------------------------------
    # A venue publishes several content types, each with its own limits
    # (Article, Brief Communication, Review, Resource, Analysis, Matters
    # Arising, ...). The profile carries them as a table; a submission selects
    # one (`setup --article-type`, `set-article-type`), and a type whose numbers
    # the profile does not carry is reported as counts-only rather than being
    # measured against another type's caps. A profile written in the older,
    # single-type shape (top-level `article_type`/`length_limits`/`captions`)
    # is read as a one-entry table, so it keeps exactly its old behaviour.
    types_raw = out.get("article_types")
    if types_raw is None:
        types_raw = [{"id": _slugify_article_type(article_type), "label": article_type,
                      "length_limits": out.get("length_limits"),
                      "captions": out.get("captions")}]
    elif not isinstance(types_raw, list) or not types_raw:
        problems.append("'article_types' must be a non-empty list of objects "
                        "(or absent for a single-type profile)")
        types_raw = [{"id": "default", "label": article_type}]
    clean_types = []
    seen_types = set()
    for i, entry in enumerate(types_raw):
        if not isinstance(entry, dict):
            problems.append(f"article_types[{i}] must be an object")
            continue
        entry_label = str(entry.get("label") or "").strip()
        type_id = (str(entry.get("id") or "").strip().lower()
                   or _slugify_article_type(entry_label))
        if not VENUE_ID_RE.match(type_id):
            problems.append(f"article_types[{i}].id {type_id!r} is not a slug: letters, "
                            f"digits, '.', '_', '+', '-' only")
        if type_id in seen_types:
            problems.append(f"article_types: duplicate id {type_id!r}")
        seen_types.add(type_id)
        clean_types.append({
            "id": type_id,
            "label": entry_label or type_id,
            "source": str(entry.get("source") or "").strip(),
            "length_limits": _clean_length_limits(entry.get("length_limits"),
                                                  f"article_types[{type_id}].length_limits",
                                                  problems),
            "captions": _clean_captions(entry.get("captions"),
                                        f"article_types[{type_id}].captions", problems),
            "counting": _clean_counting(entry.get("counting"),
                                        f"article_types[{type_id}].counting", problems),
        })
    if not clean_types:
        clean_types = [{"id": "default", "label": article_type, "source": "",
                        "length_limits": None, "captions": None, "counting": None}]
    default_type_id = (str(out.get("default_article_type") or "").strip().lower()
                       or clean_types[0]["id"])
    type_ids = [t["id"] for t in clean_types]
    if default_type_id not in type_ids:
        problems.append(f"default_article_type {default_type_id!r} is not one of the article "
                        f"types ({', '.join(type_ids)})")
        default_type_id = clean_types[0]["id"]
    default_entry = next(t for t in clean_types if t["id"] == default_type_id)
    # The top-level fields stay the DEFAULT type's data: a reader that only knows
    # the pre-article-type shape (an older tool, a hand-written config) sees
    # exactly what it saw before, and `set-article-type` re-points the accessors.
    clean_limits = (copy.deepcopy(default_entry["length_limits"])
                    if default_entry["length_limits"] is not None
                    else copy.deepcopy(EMPTY_LENGTH_LIMITS))
    clean_captions = (copy.deepcopy(default_entry["captions"])
                      if default_entry["captions"] is not None
                      else copy.deepcopy(EMPTY_CAPTIONS))

    journals = _profile_str_list(out.get("journals"), "journals", problems)
    aliases = _profile_str_list(out.get("journal_aliases"), "journal_aliases", problems)
    patterns = _profile_str_list(out.get("journal_patterns"), "journal_patterns", problems)
    for pat in patterns:
        try:
            re.compile(pat)
        except re.error as e:
            problems.append(f"journal_patterns entry {pat!r} is not a regular expression: {e}")
    prompt = out.get("prompt") or {}
    if not isinstance(prompt, dict):
        problems.append("'prompt' must be an object")
        prompt = {}
    submission = out.get("submission") or {}
    if not isinstance(submission, dict):
        problems.append("'submission' must be an object")
        submission = {}
    pdf_accepted = submission.get("pdf_accepted")
    if pdf_accepted is not None and not isinstance(pdf_accepted, bool):
        problems.append(f"submission.pdf_accepted must be true, false or null (got "
                        f"{pdf_accepted!r})")
        pdf_accepted = None
    # Validate `formats` BEFORE the single raise below: this call appends its
    # problems, and after the raise nothing it appends would ever be seen (an
    # invalid string silently became an empty list instead of failing).
    formats = _profile_str_list(submission.get("formats"), "submission.formats",
                                problems) or []
    # Another publisher's block headings ("Lead contact", "Key resources", ...)
    # are DATA a venue declares, never pipeline knowledge: the formatter reads
    # this list through `venue_containers()` and its own default is empty.
    foreign = _profile_str_list(out.get("foreign_container_headings"),
                                "foreign_container_headings", problems) or []
    # Another publisher's boilerplate phrases (FMT-L1): same contract as the
    # foreign container headings -- profile DATA, empty by default, never a
    # phrase list the engine invents.
    leftover = _profile_str_list(out.get("leftover_phrases"),
                                 "leftover_phrases", problems) or []
    # The venue's display-item numbering convention (FMT-O1). "" = the profile
    # states none, which means the scan reports no ordering row.
    numbering = str(out.get("numbering") or "").strip().lower()
    if numbering and numbering not in ("citation", "none"):
        problems.append(f"numbering must be 'citation' or 'none' (got {numbering!r})")
        numbering = ""
    # The reference-entry policy (FMT-R5): only `flag_preprints` today, so a
    # venue that accepts preprints without comment sets it false/absent.
    references_in = out.get("references")
    clean_references = {}
    if references_in is not None and not isinstance(references_in, dict):
        problems.append("references must be an object or null")
    elif isinstance(references_in, dict):
        flag = references_in.get("flag_preprints")
        if flag is not None and not isinstance(flag, bool):
            problems.append("references.flag_preprints must be true, false or null")
        else:
            clean_references["flag_preprints"] = bool(flag)
    clean_tables = _clean_display_rules(out.get("tables"), "tables", problems)
    clean_figures = _clean_display_rules(out.get("figures"), "figures", problems)
    # The venue's M19 main-text counting convention (which section kinds its
    # word limit leaves out); a type entry may state its own, because one
    # venue's types can count differently (NBT Article vs Brief Communication).
    clean_counting = _clean_counting(out.get("counting"), "counting", problems)
    # The profile's own provenance map (C15 preserves it): a non-object value
    # is a malformed field like any other and must be reported, not dropped.
    raw_sources = out.get("sources")
    if raw_sources is not None and not isinstance(raw_sources, dict):
        problems.append("'sources' must be an object of name -> URL/string (the profile's "
                        "provenance map); got " + type(raw_sources).__name__)

    # The venue's own raster-resolution floor (FMT-IM4). Like figure_text, it is
    # a measured rule with a source, and a profile that states none gets no gate.
    image_dpi_raw = out.get("image_dpi") or {}
    clean_image_dpi = {}
    if image_dpi_raw:
        if not isinstance(image_dpi_raw, dict):
            problems.append("'image_dpi' must be an object")
        else:
            try:
                min_dpi = float(image_dpi_raw.get("min_dpi") or 0)
            except (TypeError, ValueError):
                problems.append("image_dpi.min_dpi must be a number")
                min_dpi = 0
            if min_dpi <= 0:
                problems.append("image_dpi.min_dpi must be > 0 when the block is present")
            else:
                clean_image_dpi = {"min_dpi": min_dpi,
                                   "source": str(image_dpi_raw.get("source") or "").strip()}
    # The venue's own figure-type minimum (FMT-IM6). It is a measured rule with
    # a source, not a pipeline default: a profile that does not state it gets no
    # gate. Validate it here so a typo cannot silently disable the rule.
    figure_text_raw = out.get("figure_text") or {}
    clean_figure_text = {}
    if figure_text_raw:
        if not isinstance(figure_text_raw, dict):
            problems.append("'figure_text' must be an object")
        else:
            try:
                min_pt = float(figure_text_raw.get("min_pt") or 0)
            except (TypeError, ValueError):
                problems.append("figure_text.min_pt must be a number")
                min_pt = 0
            if min_pt <= 0:
                problems.append("figure_text.min_pt must be > 0 when the block is present")
            else:
                clean_figure_text = {
                    "min_pt": min_pt,
                    "source": str(figure_text_raw.get("source") or "").strip(),
                }

    if problems:
        raise VenueProfileError(f"{origin}: " + "; ".join(problems))

    clean_prompt = {
        "subject": str(prompt.get("subject") or f"a {label} manuscript submission").strip(),
        "editor": str(prompt.get("editor") or f"a {label} editor or reviewer").strip(),
        "requirements": str(prompt.get("requirements")
                            or f"the {label} author guidelines and submission requirements").strip(),
        "requirement_authority": str(prompt.get("requirement_authority") or label).strip(),
        "guidelines_source": str(prompt.get("guidelines_source")
                                 or f"the current {label} author guidelines").strip(),
    }
    # The profile's own provenance: SKILL.md points the sessions at it ("the
    # profile's own `sources` field names where its numbers come from"), and
    # the rebuilt return value used to drop the key, so a stage reading the
    # profile through VenueProfile.data could not name the guideline it used.
    clean_sources = ({str(k): str(v) for k, v in raw_sources.items()}
                     if isinstance(raw_sources, dict) else {})
    return {
        "id": venue_id,
        "label": label,
        "short": short,
        "sources": clean_sources,
        "description": str(out.get("description") or "").strip(),
        "article_type": default_entry["label"],
        "article_type_id": default_type_id,
        "default_article_type": default_type_id,
        "article_types": clean_types,
        "journals": journals,
        "journal_aliases": aliases,
        "journal_patterns": patterns,
        "accepts_any_journal": bool(out.get("accepts_any_journal")),
        "default_journal": str(out.get("default_journal") or "").strip(),
        "length_limits": clean_limits,
        "counting": clean_counting,
        "captions": clean_captions,
        "tables": clean_tables or copy.deepcopy(EMPTY_TABLES),
        "figures": clean_figures or copy.deepcopy(EMPTY_FIGURES),
        "foreign_container_headings": foreign,
        "leftover_phrases": leftover,
        "numbering": numbering,
        "references": clean_references,
        "figure_text": clean_figure_text,
        "image_dpi": clean_image_dpi,
        "submission": {
            "pdf_accepted": pdf_accepted,
            "formats": formats,
            "pdf_note": str(submission.get("pdf_note") or "").strip(),
        },
        "prompt": clean_prompt,
    }


class VenueProfile:
    """A validated venue profile plus where it came from.

    Every stage reads the venue through this object: the prompt text, the
    length limits and the caption policy are all derived from the profile's own
    fields, so adding a venue means adding a JSON document, not a branch in the
    pipeline.
    """

    def __init__(self, data, origin: str = "<builtin>", path=None,
                 article_type_id: str = None):
        self.data = normalize_venue_profile(data, origin)
        self.origin = origin
        self.path = Path(path) if path is not None else None
        self.article_type_id = self._known_type(article_type_id) or \
            self.data["default_article_type"]

    # ---- article types ----
    def _type_entry(self, type_id: str = None) -> dict:
        wanted = str(type_id if type_id is not None else self.article_type_id).strip().lower()
        for entry in self.data["article_types"]:
            if entry["id"] == wanted:
                return entry
        return self.data["article_types"][0]

    def _default_type_entry(self) -> dict:
        return self._type_entry(self.data["default_article_type"])

    def _known_type(self, type_id) -> str:
        """The slug of `type_id` when the profile has it, else ""."""
        wanted = str(type_id or "").strip().lower()
        return wanted if any(t["id"] == wanted for t in self.data["article_types"]) else ""

    def article_type_ids(self) -> list:
        return [t["id"] for t in self.data["article_types"]]

    def article_types(self) -> list:
        """[(id, label, carries_numbers), ...] in profile order, for --list."""
        return [(entry["id"], entry["label"], self.carries_article_numbers(entry["id"]))
                for entry in self.data["article_types"]]

    def carries_article_numbers(self, type_id: str = None) -> bool:
        """Does the profile state abstract/main-text numbers for `type_id`?

        A type entry that is absent, null, or declares only null bases carries
        NO numbers: the stages then count and name the venue's own limit instead
        of being measured against another type's caps.
        """
        limits = self._type_entry(type_id).get("length_limits") or {}
        return any((limits.get(key) or {}).get("base") is not None
                   or (limits.get(key) or {}).get("relaxation") is not None
                   for key in ("abstract", "main_text"))

    def with_article_type(self, type_id) -> "VenueProfile":
        """The same venue with another article type selected.

        The type's own numbers (or its deliberate absence of numbers) drive the
        M19 caps, the caption policy and the prompt prose from here on; the
        venue-level cover-letter preference and legend policy still apply.
        """
        wanted = self._known_type(type_id) or None
        if wanted is None:
            wanted = str(type_id or "").strip().lower()
            raise VenueProfileError(
                f"unknown article type {type_id!r} for venue {self.id!r} "
                f"(available: {', '.join(self.article_type_ids())})")
        if wanted == self.article_type_id:
            return self
        clone = copy.copy(self)
        clone.article_type_id = wanted
        return clone

    # ---- identity ----
    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def label(self) -> str:
        return self.data["label"]

    @property
    def short(self) -> str:
        return self.data["short"]

    @property
    def description(self) -> str:
        return self.data["description"]

    @property
    def article_type(self) -> str:
        return self._type_entry()["label"]

    @property
    def article_type_source(self) -> str:
        return self._type_entry().get("source") or ""

    @property
    def default_journal(self) -> str:
        return self.data["default_journal"]

    @property
    def prompt(self) -> dict:
        return self.data["prompt"]

    @property
    def captions(self) -> dict:
        entry = self._type_entry()
        if entry.get("captions") is not None:
            return entry["captions"]
        default = self._default_type_entry()
        return default.get("captions") or EMPTY_CAPTIONS

    @property
    def caption_default(self) -> int:
        return int(self.captions.get("default_cap") or 0)

    @property
    def counting(self) -> dict:
        """The M19 main-text counting convention for the SELECTED article type.

        A type entry that states no convention inherits the profile-level block;
        a profile that states none gets the pipeline's default, which is the
        convention the counter always applied (the abstract, Methods, references
        and figure legends are outside the main-text count). `excludes` lists
        the section kinds left OUT of the count; every other kind is inside it.
        """
        entry = self._type_entry()
        block = entry.get("counting")
        if block is None:
            block = self.data.get("counting")
        if block is None:
            return {"main_text": {"excludes": list(DEFAULT_MAIN_TEXT_EXCLUDES),
                                  "source": "", "note": ""}}
        return copy.deepcopy(block)

    def main_text_excludes(self) -> list:
        """The section kinds this venue/article type leaves OUT of its count."""
        return list((self.counting.get("main_text") or {}).get("excludes") or [])

    @property
    def tables(self) -> dict:
        """The venue's table rule (EMPTY_TABLES when the profile declares none)."""
        return self.data.get("tables") or EMPTY_TABLES

    @property
    def figures(self) -> dict:
        """The venue's figure rule (EMPTY_FIGURES when the profile declares none)."""
        return self.data.get("figures") or EMPTY_FIGURES

    @property
    def declares_table_rule(self) -> bool:
        """Does this profile state where captioned tables belong, and how?"""
        return _declares_display_rule(self.tables)

    @property
    def declares_figure_rule(self) -> bool:
        """Does this profile state where captioned figures belong, and how?"""
        return _declares_display_rule(self.figures)

    @property
    def length_limits_source(self) -> str:
        entry = self._type_entry()
        limits = entry.get("length_limits") or {}
        source = limits.get("source") or entry.get("source")
        if source:
            return source
        if entry["length_limits"] is None:
            return (f"{self.label} submission rules ({entry['label']}: this profile carries no "
                    f"numbers for that article type -- the stage names the venue's own limit)")
        return f"{self.label} submission rules ({entry['label']})"

    def to_dict(self) -> dict:
        return copy.deepcopy(self.data)

    def length_limits(self) -> dict:
        """The M19 caps, in the shape the code-side scan and the prompts use.

        Abstract and main text come from the SELECTED article type (a type the
        profile carries no numbers for has `cap: None`, never another type's
        cap); the cover-letter preference is venue-level, so a type entry that
        does not state one inherits the default type's.
        """
        raw = self._type_entry().get("length_limits") or {}

        def spec(key: str) -> dict:
            base = (raw.get(key) or {}).get("base")
            relaxation = (raw.get(key) or {}).get("relaxation")
            cap = (lenient_word_limit(base, relaxation)
                   if base is not None and relaxation is not None else None)
            return {"base": base, "relaxation": relaxation, "cap": cap}

        # Inherit only when the type does not state a cover-letter block at
        # all; an explicit block with null min/max MEANS "none" (the README's
        # schema), so it must not be replaced by the default type's preference.
        cover = raw.get("cover_letter")
        if cover is None:
            cover = ((self._default_type_entry().get("length_limits") or {})
                     .get("cover_letter") or {})
        return {"abstract": spec("abstract"),
                "main text": spec("main_text"),
                "cover letter": {"min": cover.get("min"), "max": cover.get("max"),
                                 "total_max": cover.get("total_max"),
                                 "source": cover.get("source") or ""}}

    def known_journals(self) -> list:
        return list(self.data["journals"]) + list(self.data["journal_aliases"])

    def journal_matches(self, journal: str) -> bool:
        """Does `journal` name a journal this profile claims to describe?

        A profile that accepts any journal, or declares no journal names and no
        patterns, never fails this test (it makes no claim to check).
        """
        name = str(journal or "").strip()
        if not name or self.data["accepts_any_journal"]:
            return True
        if not self.known_journals() and not self.data["journal_patterns"]:
            return True
        key = _journal_key(name)
        if key and key in {_journal_key(j) for j in self.known_journals()}:
            return True
        for pat in self.data["journal_patterns"]:
            try:
                if re.search(pat, name, re.IGNORECASE):
                    return True
            except re.error:            # pragma: no cover -- validated on load
                continue
        return False

    def describe_origin(self) -> str:
        return f"{self.origin}" + (f" ({self.path})" if self.path is not None else "")


def venue_profile_search_dirs(root=None) -> list:
    """Where venue profiles are looked up, in precedence order.

    A root-local profile (written by `set-venue --profile`, or edited by hand)
    wins over the copy shipped with the script that is running.
    """
    dirs = []
    if root is not None:
        dirs.append(Path(root) / VENUE_PROFILES_DIRNAME)
    try:
        script_dir = Path(__file__).resolve().parent
    except (NameError, OSError):        # pragma: no cover -- __file__ always set here
        script_dir = None
    if script_dir is not None and script_dir / VENUE_PROFILES_DIRNAME not in dirs:
        dirs.append(script_dir / VENUE_PROFILES_DIRNAME)
    return dirs


def available_venue_profiles(root=None) -> dict:
    """Every venue profile this pipeline can see: FILE-NAME id -> descriptor.

    Resolution is by file name (`load_venue_profile`), so the listing is too: a
    profile is shown under the id `set-venue <id>` will actually accept. A file
    whose JSON declares a different internal id is listed under its file name
    with a `note`; the declared id is carried by `VenueProfile` only after the
    file-name override, because the README makes the file name authoritative.

    Root-local files win over shipped files of the same file name, and both win
    over the built-in copies. A file that does not parse or does not validate is
    listed with its `error` instead of being silently ignored, because
    `set-venue --list` is where the operator finds out why an id is missing.
    """
    found: dict = {}
    declared_owner: dict = {}
    seen_dirs = set()
    for d in venue_profile_search_dirs(root):
        if not d.is_dir():
            continue
        try:
            dir_key = str(Path(d).resolve())
        except OSError:                                       # pragma: no cover -- d exists
            dir_key = str(d)
        if dir_key in seen_dirs:
            continue
        seen_dirs.add(dir_key)
        for path in sorted(d.glob(f"*{VENUE_PROFILE_SUFFIX}")):
            key = path.stem.lower()
            if key in found and Path(str(found[key].get("path") or "")).parent != path.parent:
                # The same FILE NAME in a lower-precedence directory is the
                # normal post-setup state: the root carries a frozen copy and
                # the checkout carries the shipped one. The root copy wins.
                continue
            origin = f"root: {d}" if root is not None and \
                Path(d) == Path(root) / VENUE_PROFILES_DIRNAME else f"shipped: {d}"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                found.setdefault(key, {"id": key, "label": key,
                                       "error": f"{path}: not readable JSON: {e}",
                                       "origin": origin, "path": str(path)})
                continue
            declared = (str(data.get("id") or "").strip().lower()
                        if isinstance(data, dict) else "")
            # The FILE NAME is what resolves, so it is the profile's identity:
            # overriding a disagreeing internal id here keeps the listing and
            # `set-venue` on one rule (a hand-added my-venue.json declaring id
            # "other" used to be advertised as "other", which then resolved to
            # nothing). `set-venue --profile` still refuses the mismatch when a
            # file is deliberately installed.
            try:
                profile = VenueProfile(
                    dict(data, id=key) if isinstance(data, dict) else data,
                    origin=origin, path=path)
            except VenueProfileError as e:
                found.setdefault(key, {"id": key, "label": key,
                                       "error": str(e), "origin": origin,
                                       "path": str(path)})
                continue
            descriptor = {"id": key, "label": profile.label,
                          "description": profile.description,
                          "origin": origin, "path": str(path),
                          "default_journal": profile.default_journal}
            if declared and declared != key:
                descriptor["note"] = (
                    f"the file declares id {declared!r}; the file name {path.name!r} is "
                    f"the id `set-venue` resolves -- rename the file to {declared}.json "
                    f"or fix its id")
                owner = declared_owner.get(declared)
                if owner is not None and owner[1].parent == path.parent and owner[0] != key:
                    # Two files in the SAME directory declaring one id: name the
                    # duplicate instead of hiding it. The file whose NAME is the
                    # declared id is the rightful owner; the other one is the
                    # duplicate.
                    if key == declared:
                        prior = found.get(owner[0])
                        if prior is not None and not prior.get("error"):
                            prior["error"] = (
                                f"{path}: the profile id {declared!r} is also declared by "
                                f"{owner[1]}; rename one id or remove the duplicate")
                        declared_owner[declared] = (key, path)
                    else:
                        descriptor["error"] = (
                            f"{path}: the profile id {declared!r} is already provided by "
                            f"{found.get(owner[0], {}).get('path') or owner[1]}; rename one "
                            f"id or remove the duplicate")
            if declared and declared not in declared_owner:
                declared_owner[declared] = (key, path)
            found.setdefault(key, descriptor)
    for vid, data in BUILTIN_VENUE_PROFILES.items():
        # NOT setdefault(): its default argument is evaluated EAGERLY, so a
        # shipped profile whose id is already in `found` could still raise
        # KeyError from a missing display field -- on `set-venue --list`, the
        # command whose job is to show the profiles and name the one to repair.
        if vid in found:
            continue
        found[vid] = {"id": vid, "label": data.get("label") or vid,
                      "description": data.get("description") or "",
                      "origin": "built-in", "path": None,
                      "default_journal": data.get("default_journal") or ""}
    return found


def load_venue_profile(venue_id, root=None) -> VenueProfile:
    """Resolve one venue id to a profile, or raise VenueProfileError/Unknown."""
    vid = str(venue_id or "").strip().lower()
    if not vid:
        raise VenueProfileError("no venue id given", unknown=True)
    if not VENUE_ID_RE.match(vid):
        raise VenueProfileError(f"invalid venue id {venue_id!r}: letters, digits, '.', '_', "
                                f"'+', '-' only", unknown=True)
    for d in venue_profile_search_dirs(root):
        path = Path(d) / f"{vid}{VENUE_PROFILE_SUFFIX}"
        if not path.is_file():
            # The listing lowercases the stem, so a file saved as `Nature.json`
            # was listed under `nature` but could never resolve on a
            # case-sensitive filesystem. Accept the unique case-insensitive
            # spelling of the id.
            try:
                matches = [p for p in Path(d).glob(f"*{VENUE_PROFILE_SUFFIX}")
                           if p.stem.lower() == vid]
            except OSError:
                matches = []
            if len(matches) != 1:
                continue
            path = matches[0]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise VenueProfileError(f"{path}: not readable JSON: {e}")
        origin = "root-local profile" if root is not None and \
            Path(d) == Path(root) / VENUE_PROFILES_DIRNAME else "shipped profile"
        # Resolution is by FILE NAME. A hand-added file whose JSON declares a
        # different internal id must not resolve under that id (the old second
        # pass did, while `set-venue --profile` refused the same file), and the
        # id the root records must be the one later commands can resolve, so the
        # file name is the profile's identity.
        if isinstance(data, dict):
            data = dict(data, id=vid)
        return VenueProfile(data, origin=origin, path=path)
    if vid in BUILTIN_VENUE_PROFILES:
        return VenueProfile(BUILTIN_VENUE_PROFILES[vid], origin="built-in")
    raise VenueProfileError(f"unknown venue {venue_id!r}", unknown=True)


def unknown_venue_message(venue_id, root=None) -> str:
    """The one message an operator needs when a venue id resolves to nothing."""
    known = ", ".join(sorted(available_venue_profiles(root)))
    try:
        prog = Path(__file__).name
    except NameError:                   # pragma: no cover -- __file__ always set here
        prog = "paper_pipeline.py"
    return (f"unknown venue {venue_id!r}: no venue profile named "
            f"{str(venue_id or '').strip().lower()!r} was found.\n"
            f"       Available venues: {known or '(none)'}\n"
            f"       List them with `{prog} set-venue --list`. For a FRESH root, create the "
            f"profile as a JSON file and run "
            f"`{prog} setup --source <dir> --root <dir> --venue-profile <file>` (no prior root "
            f"needed); on an EXISTING root use `set-venue <id> --profile <file>`, or place the "
            f"file in {VENUE_PROFILES_DIRNAME}/<id>{VENUE_PROFILE_SUFFIX} next to the script.")


def default_venue_profile() -> VenueProfile:
    """The profile a call that has no root at hand uses (the built-in default).

    This returns the GUARDED object, not a fresh
    `VenueProfile(BUILTIN_VENUE_PROFILES[...])`: that construction re-validated
    the raw shipped data and made one bad hand edit of
    `venue_profiles/<default>.json` brick every command at import (the
    module-level LENGTH_RULE/STANDING_EXEMPTIONS constants call this function),
    including the `set-venue` path that exists to repair it. The guard falls
    back to the embedded literal and warns.
    """
    return _DEFAULT_VENUE_OBJ


# =====================================================================
# VENUE EXEMPLARS -> ADVISORY STRUCTURE NORMS (word / latex templates)
# =====================================================================
# A venue MAY ship a shared, pinned exemplar corpus:
#
#   venue_profiles/<venue-id>.manuscripts/   recently published articles
#                                            downloaded from the venue's OWN
#                                            website / OA sources
#   venue_profiles/<venue-id>.templates/     the DERIVED, structure-only pack:
#                                            structure.json, the summary, the
#                                            word/latex skeletons and MANIFEST
#
# The manuscripts are read ONLY for their STRUCTURE (section order, abstract,
# statement placement); no prose is copied, the pack is generated by CODE (so
# it is deterministic and hash-pinned), and the derived norms are ADVISORY in
# the review/rewrite prompts -- never a gate, never a substitute for the
# venue's own author guidelines (which the profile carries).
VENUE_EXEMPLAR_SUFFIX = ".manuscripts"
VENUE_TEMPLATE_SUFFIX = ".templates"
VENUE_NORM_FILE = "venue_architecture.md"
VENUE_STRUCTURE_FILE = "structure.json"
VENUE_PACK_MANIFEST = "MANIFEST.json"
VENUE_WORD_TEMPLATE = "word-template.md"
VENUE_LATEX_TEMPLATE = "latex-template.tex"
VENUE_EXEMPLAR_TEXT_SUFFIXES = (".tex", ".md", ".markdown", ".txt")
VENUE_EXEMPLAR_DOCX_SUFFIXES = (".docx",)
# The journal's OWN template files (Word .dotx/.docx, LaTeX .tex/.cls/.sty),
# unzipped into this sibling dir. They are AUTHORITATIVE: the derived skeleton,
# the mandatory sections and the class file all come from here when present.
VENUE_OFFICIAL_SUFFIX = ".official"
VENUE_OFFICIAL_REQUIREMENTS = "requirements.json"
TEX_DOCCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^{}]+)\}")

TEX_SECTION_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection)\*?\{([^{}]*)\}")
MD_HEADING_RE = re.compile(r"^(#{1,4})[ \t]+(.+?)[ \t]*$", re.M)
TEX_ABSTRACT_RE = re.compile(r"\\begin\{abstract\}", re.I)
MD_ABSTRACT_RE = re.compile(r"^#{1,3}[ \t]+abstract\b", re.I | re.M)
_TEX_LEVELS = {"part": 1, "chapter": 1, "section": 1, "subsection": 2, "subsubsection": 3}
# Statement placement is what a venue's structure prescribes beyond the body
# sections; the label is the canonical name the templates use.
VENUE_STATEMENT_PATTERNS = (
    ("Data availability", re.compile(r"data\s+availability", re.I)),
    ("Code availability", re.compile(r"code\s+availability", re.I)),
    ("Ethics", re.compile(r"\bethic", re.I)),
    ("Funding", re.compile(r"\bfunding\b", re.I)),
    ("Author contributions", re.compile(r"author\s+contributions?", re.I)),
    ("Competing interests", re.compile(r"competing\s+interests?|conflict\s+of\s+interest", re.I)),
    ("Acknowledgements", re.compile(r"acknowledg", re.I)),
    ("Supplementary material", re.compile(
        r"supplement(?:ary|al)\s+(material|information|data|tables?|figures?|methods?)", re.I)),
)
# Journal template FILES often embed the venue's own GUIDELINES as sections
# ("Article types", "Manuscript Formatting", ...) next to the sample manuscript.
# Those are not manuscript sections: they are filtered from both tiers (the
# operator can still pin extra mandatory sections in requirements.json).
VENUE_GUIDANCE_SECTIONS = {
    "article types", "manuscript formatting", "nomenclature", "additional requirements",
    "reference styles", "reference style", "figure captions", "keywords",
    "permission to reuse and copyright", "international phonetic alphabet",
    "resource identification initiative", "life science identifiers",
}


def _is_guidance_title(title) -> bool:
    """True when a heading belongs to the template's own instructions."""
    low = str(title or "").strip().strip(":").strip().lower()
    return not low or low in VENUE_GUIDANCE_SECTIONS


def venue_exemplar_dirs(venue_id, root=None) -> list:
    """Existing `<venue-id>.manuscripts/` dirs, precedence order (root first)."""
    vid = str(venue_id or "").strip().lower()
    out = []
    for d in venue_profile_search_dirs(root):
        p = Path(d) / f"{vid}{VENUE_EXEMPLAR_SUFFIX}"
        if p.is_dir():
            out.append(p)
    return out


def venue_pack_dir(venue_id, root=None):
    """The venue's generated template pack dir, or None when it does not exist."""
    vid = str(venue_id or "").strip().lower()
    for d in venue_profile_search_dirs(root):
        p = Path(d) / f"{vid}{VENUE_TEMPLATE_SUFFIX}"
        if (p / VENUE_NORM_FILE).is_file():
            return p
    return None


def venue_official_dirs(venue_id, root=None, profiles_dir=None) -> list:
    """Existing `<venue-id>.official/` dirs (explicit profiles_dir first)."""
    vid = str(venue_id or "").strip().lower()
    out = []
    if profiles_dir:
        p = Path(profiles_dir) / f"{vid}{VENUE_OFFICIAL_SUFFIX}"
        if p.is_dir():
            out.append(p)
    for d in venue_profile_search_dirs(root):
        p = Path(d) / f"{vid}{VENUE_OFFICIAL_SUFFIX}"
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def _normalized_type_spellings(texts) -> list:
    """Article-type names normalized for DOCX-name matching (deduped, ordered)."""
    out = []
    for text in texts:
        norm = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
        if norm and norm not in out:
            out.append(norm)
    return out


def _normalized_article_type_names(profile) -> list:
    """The selected article type's own name spellings (normalized), or [].

    `letter-to-the-editor` normalizes to `letter to the editor`, `editorial`
    to itself: the spellings a run's own documents may legitimately carry.
    """
    if profile is None:
        return []
    label = ""
    for tid, tlabel, _carries in profile.article_types():
        if tid == profile.article_type_id:
            label = tlabel
            break
    return _normalized_type_spellings((profile.article_type_id, label))


def article_type_manuscript_names(ctx=None) -> list:
    """The run's selected article type as DOCX-name spellings ([] when unset)."""
    prof = venue_profile_of(ctx, required=False)
    if prof is not None:
        return _normalized_article_type_names(prof)
    # A root whose venue profile is unavailable still records its article type.
    return _normalized_type_spellings((str(_ctx_cfg(ctx).get("article_type") or ""),))


def _name_is_article_type_manuscript(name, type_names=()) -> bool:
    """True when a DOCX name IS one of the selected article type's spellings.

    `letter-to-the-editor.docx` / `Letter_to_the_Editor.docx` name the
    MANUSCRIPT of a `letter-to-the-editor` run; a trailing version token
    (`-v2`, ` 2`) is ignored. Deliberately a FULL-name match: `main_letter.docx`
    or `letter_to_the_editor_comments.docx` are not the article type's name.
    """
    if not type_names:
        return False
    stem = Path(str(name or "")).stem
    norm = re.sub(r"[^a-z0-9]+", " ", stem.lower()).strip()
    if not norm:
        return False
    for t in type_names:
        t = re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip()
        if not t:
            continue
        if norm == t:
            return True
        if norm.startswith(t + " ") \
                and re.fullmatch(r"(?:v|rev|version|revision|draft)? ?\d{1,3}",
                                 norm[len(t) + 1:]):
            return True
    return False


def _document_role_tokens(name) -> set:
    """Lowercase word tokens of a filename stem, including camelCase splits."""
    stem = Path(str(name or "")).stem
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    return set(re.findall(r"[a-z0-9]+", stem.lower()))


# An authored REPLY is not a cover letter. The formatter's
# `is_cover_letter_doc` and the M19 predicate both apply this exclusion; the
# role resolver did not, so `cover-letter-response.docx` was routed to the
# cover template by one code path and rejected by the others (F09).
NON_COVER_LETTER_NAME_RE = re.compile(
    r"response|repl(?:y|ies)|rebuttal|point[\s_-]?by[\s_-]?point|"
    r"decision[\s_-]?(?:letter|notice)|referee|reviewer", re.I)


def docx_document_role(name, manuscript_names=()) -> str:
    """The submission role a package DOCX name advertises: main/supp/cover.

    ONE rule for the whole pipeline: the template resolver (which template a
    DOCX may adopt), the package verifier and the code-side normalizer all read
    the role the same way. A cover letter is a LETTER, not a manuscript: the
    manuscript template must never be applied to one (see
    `template_for_package_file`). `manuscript_names` are the run's OWN
    article-type spellings (`article_type_manuscript_names`): a document named
    for the selected type is that type's MANUSCRIPT, so a `letter-to-the-editor`
    document is a letter ONLY in a run whose article type is not
    `letter-to-the-editor` (a cover letter keeps its `cover` spelling there).
    """
    tokens = _document_role_tokens(name)
    # `supplemental` (the common US spelling) and the concatenated
    # `supplementarymaterial` were missing from the exact-token set, so
    # `Supplemental_Material.docx`/`.tex` was classified as `main` and its words
    # were charged to the article caps (or it could be chosen as the main LaTeX
    # sample). The prefix test covers every `supplement*` compound; `support`
    # does not start with `supplement` and stays `main` (see the role tests).
    if "supp" in tokens or "suppl" in tokens \
            or any(re.fullmatch(
                r"supp(?:l(?:ement(?:s|al|ary|arymaterial|almaterial)?)?)?\d*", t)
                for t in tokens):
        # The last form is the concatenated `Supp1`/`Suppl2` spelling: the
        # tokenizer keeps the digit, so the exact-token tests missed it and a
        # supplementary document was counted as the MAIN manuscript.
        return "supp"
    # `coverletter` is the conventional concatenated spelling; camel-case
    # `CoverLetter` already splits into `cover` + `letter`, but the lowercase
    # form must not fall through to `main`.
    _base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    _reply = bool(NON_COVER_LETTER_NAME_RE.search(_base))
    if not _reply and ("cover" in tokens or "coverletter" in tokens):
        return "cover"
    if _name_is_article_type_manuscript(Path(str(name)).stem, manuscript_names):
        return "main"
    if "letter" in tokens and not _reply:
        return "cover"
    return "main"


def _profile_for_template_names(venue_id, root=None, profiles_dir=None):
    """The venue profile used to derive template-role names, or None."""
    vid = str(venue_id or "").strip().lower()
    if profiles_dir:
        p = Path(profiles_dir) / f"{vid}{VENUE_PROFILE_SUFFIX}"
        if p.is_file():
            try:
                return VenueProfile(json.loads(p.read_text(encoding="utf-8")),
                                    origin=str(p), path=p)
            except (OSError, ValueError, VenueProfileError):
                return None
    try:
        return load_venue_profile(vid, root=root)
    except VenueProfileError:
        return None


def official_template_files(venue_id, root=None, profiles_dir=None,
                            manuscript_names=None) -> dict:
    """The venue's OWN deliverable templates, resolved per format.

    Returns `{"official_dir", "word": {"main", "supplementary", "cover"},
    "latex": {"sample", "cover", "cls": [...], "bst": [...]}, "sha256": {path: digest}}`;
    an empty dict when the venue ships no `.official` corpus. The ROOT's copy
    wins (setup copies the whole venue_profiles/ tree into the root), so a
    root-local update is what runs.

    Roles are resolved from the file names the journals use (a Word template
    with "template" in its name, a supplementary sibling, and -- when a journal
    publishes one -- a cover-letter template such as `Cover_Letter.docx`; a
    LaTeX sample `.tex` plus the `.cls`/`.bst` it needs). `manuscript_names` is
    the run's OWN selected article-type spellings: a template named for that
    type is a MANUSCRIPT template, not a cover letter, exactly as the package
    verifier reads it. Nothing outside `.official` is consulted, and the files
    are never modified.
    """
    vid = str(venue_id or "").strip().lower()
    if manuscript_names is None:
        _prof = _profile_for_template_names(vid, root, profiles_dir)
        manuscript_names = _normalized_article_type_names(_prof)
    dirs = venue_official_dirs(vid, root, profiles_dir)
    if not dirs:
        return {}
    d = Path(dirs[0])
    word, latex = {}, {}
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        low = p.name.lower()
        if p.suffix.lower() in (".docx", ".dotx"):
            role = docx_document_role(p.name, manuscript_names)
            if role == "cover":
                word.setdefault("cover", p)
            elif role == "supp":
                word.setdefault("supplementary", p)
            else:
                word.setdefault("main", p)
        elif p.suffix.lower() in (".tex", ".ltx"):
            # The .tex branch must read the SAME role as the .docx branch: a
            # Cover_Letter.tex used to become the manuscript's LaTeX sample
            # (sorted() put it first) and its letter boilerplate entered the
            # venue's authoritative statements table.
            role = docx_document_role(p.name, manuscript_names)
            if role == "supp":
                latex.setdefault("supplementary", p)
            elif role == "cover":
                latex.setdefault("cover", p)
            elif "sample" not in latex:
                latex["sample"] = p
        elif p.suffix.lower() == ".cls":
            latex.setdefault("cls", []).append(p)
        elif p.suffix.lower() == ".bst":
            latex.setdefault("bst", []).append(p)
    # Prefer a file that literally calls itself the template for the main role.
    if not word.get("main") or "template" not in Path(word["main"]).name.lower():
        cands = [p for p in sorted(d.rglob("*"))
                 if p.is_file() and p.suffix.lower() in (".docx", ".dotx")
                 and "template" in p.name.lower()
                 and docx_document_role(p.name, manuscript_names) == "main"]
        if cands:
            word["main"] = cands[0]
    files = {}
    for role, p in list(word.items()) + list(latex.items()):
        for q in (p if isinstance(p, list) else [p]):
            if isinstance(q, Path) and q.is_file():
                files[str(q)] = sha256_file(q)
    return {"official_dir": d, "word": word, "latex": latex, "sha256": files}


def stage_venue_template(ctx: "Ctx", sb: Path) -> dict:
    """Stage the venue's official templates into one sandbox, read-only.

    A prompt that says "use the venue's own template" is not actionable when the
    template lives outside the sandbox: agents are confined to their sandbox
    (plus the skills). Every producing/reviewing sandbox therefore gets a
    `venue_template/` copy (sha256-pinned in its own manifest) when the venue
    ships one. Returns the staged manifest (empty when there is nothing to
    stage), and is idempotent.
    """
    res = official_template_files(venue_id_of(ctx), ctx.root,
                                  manuscript_names=article_type_manuscript_names(ctx))
    if not res or not venue_templates_enabled():
        return {}
    dst = sb / "venue_template"
    staged = {}
    for role, value in (("word", res.get("word") or {}), ("latex", res.get("latex") or {})):
        for key, p in value.items():
            for q in (p if isinstance(p, list) else [p]):
                if not isinstance(q, Path) or not q.is_file():
                    continue
                target = dst / role / q.name
                if not target.is_file() or sha256_file(target) != sha256_file(q):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.is_file():
                        # the previously staged copy is 0444: an UPDATED venue
                        # template must still be re-stageable (copy2 would raise)
                        make_writable(target)
                    shutil.copy2(q, target)
                with contextlib.suppress(OSError):
                    os.chmod(target, 0o444)
                staged[f"{role}/{q.name}"] = sha256_file(target)
    if staged:
        write_json_atomic(dst / "manifest.json",
                          {"venue": venue_id_of(ctx), "files": staged})
    return staged


def venue_templates_enabled() -> bool:
    """Is the official-template pass on? Default YES; `PAPER_VENUE_TEMPLATES=0` opts out.

    The restyle is default-on because the operator asked for template
    conformance; the escape hatch exists for a venue whose template is wrong or
    for a run that must keep the author's own formatting byte-for-byte.
    """
    v = os.environ.get("PAPER_VENUE_TEMPLATES", "").strip().lower()
    return v not in ("0", "false", "no", "off")


def extract_official_template(path: Path) -> dict:
    """Structure of ONE journal-provided template file (never prose)."""
    suffix = path.suffix.lower()
    out = {"file": path.name, "format": suffix.lstrip("."), "sha256": sha256_file(path),
           "documentclass": "", "sections": [], "abstract": False, "statements": []}
    if suffix in (".cls", ".sty", ".bst"):
        # A class/style file carries no skeleton; its hash pins it and the
        # documentclass is taken from the sample .tex beside it.
        return out
    if suffix in VENUE_EXEMPLAR_TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {"skipped": "unreadable"}
        m = TEX_DOCCLASS_RE.search(text)
        out["documentclass"] = m.group(1).strip() if m else ""
        out["sections"] = [{"level": lvl, "title": title}
                           for lvl, title in _sections_from_text(text, suffix)]
        out["abstract"] = bool(TEX_ABSTRACT_RE.search(text) if suffix == ".tex"
                               else MD_ABSTRACT_RE.search(text))
        out["statements"] = [label for label, pat in VENUE_STATEMENT_PATTERNS if pat.search(text)]
        return out
    if suffix in VENUE_EXEMPLAR_DOCX_SUFFIXES:
        parsed = _docx_exemplar_text(path)
        if parsed is None:
            return {"skipped": "docx text could not be extracted (paper_docx_format.py missing "
                               "or not a readable .docx/.dotx)"}
        sections, text = parsed
        out["sections"] = [{"level": lvl, "title": title} for lvl, title in sections]
        out["abstract"] = any(lvl == 1 and t.strip().lower() == "abstract" for lvl, t in sections)
        out["statements"] = [label for label, pat in VENUE_STATEMENT_PATTERNS if pat.search(text)]
        return out
    return {"skipped": f"unsupported suffix {suffix!r}"}


def official_skeleton(records: list, explicit_requirements: dict = None) -> dict:
    """The AUTHORITATIVE skeleton: mandatory sections, class file, statements.

    `mandatory_sections` are the sections present in EVERY parsed official
    sample document, plus any the operator lists explicitly in
    `<venue-id>.official/requirements.json` (`{"mandatory_sections": [...]}`).
    """
    n = len(records)
    positions, spellings, counts = {}, {}, {}
    st_positions, st_spellings = {}, {}
    for rec in records:
        for i, sec in enumerate(rec.get("sections") or []):
            if int(sec.get("level") or 0) != 1:
                continue
            key = str(sec.get("title") or "").strip().lower()
            if not key or _is_guidance_title(sec.get("title")):
                continue
            if _section_is_statement(sec.get("title")):
                # Statement sections are carried by `statements`, not by the
                # body order / mandatory-section list; their SPELLING (the
                # template's own wording) is kept for the skeleton.
                st_positions.setdefault(key, []).append(i)
                st_spellings.setdefault(key, {})
                st_spellings[key][sec["title"].strip()] = \
                    st_spellings[key].get(sec["title"].strip(), 0) + 1
                continue
            counts[key] = counts.get(key, 0) + 1
            positions.setdefault(key, []).append(i)
            spellings.setdefault(key, {})
            spellings[key][sec["title"].strip()] = spellings[key].get(sec["title"].strip(), 0) + 1
    order = sorted(counts, key=lambda k: (sum(positions[k]) / len(positions[k]), k))
    sections = [{"title": max(spellings[k], key=spellings[k].get), "present": counts[k],
                 "n_samples": n,
                 "mean_position": round(sum(positions[k]) / len(positions[k]), 2)}
                for k in order]
    mandatory = [s["title"] for s in sections if n and s["present"] == n]
    classes = [r.get("documentclass") for r in records if r.get("documentclass")]
    statements = []
    for label, _pat in VENUE_STATEMENT_PATTERNS:
        c = sum(1 for r in records if label in (r.get("statements") or []))
        if c:
            statements.append({"label": label, "present": c, "n_samples": n})
    st_order = sorted(st_positions, key=lambda k: (sum(st_positions[k]) / len(st_positions[k]), k))
    statement_sections, seen_st = [], set()
    for k in st_order:
        title = max(st_spellings[k], key=st_spellings[k].get)
        word_key = tuple(sorted(set(re.findall(r"[a-z0-9]+", title.lower()))))
        if word_key in seen_st:
            continue
        seen_st.add(word_key)
        statement_sections.append(title)
    # Mandatory sections are computed over the samples that carry a BODY at all:
    # a supplementary-material template in the same pack must not veto a body
    # section the main samples all share.
    body_samples = 0
    for rec in records:
        if any(int(s.get("level") or 0) == 1 and not _is_guidance_title(s.get("title"))
               and not _section_is_statement(s.get("title")) for s in (rec.get("sections") or [])):
            body_samples += 1
    mandatory = [s["title"] for s in sections
                 if body_samples and s["present"] >= body_samples]
    # The operator's pinned sections must survive the body-samples recompute:
    # requirements.json is authoritative about what this venue ALWAYS requires,
    # even when the sampled official templates do not all carry the section.
    for extra in ((explicit_requirements or {}).get("mandatory_sections") or []):
        if str(extra).strip() and str(extra).strip().lower() not in \
                {m.lower() for m in mandatory}:
            mandatory.append(str(extra).strip())
    return {"n_samples": n, "documentclass": classes[0] if classes else "",
            "sections": sections, "mandatory_sections": mandatory,
            "statements": statements,
            "statement_sections": statement_sections,
            "files": [{"file": r["file"], "format": r.get("format"), "sha256": r["sha256"]}
                      for r in records]}


def official_template_requirements(venue_id, root=None) -> dict:
    """The pinned official-template requirements a session must conform to.

    `advisory_sections` carries the recent-practice order from the same pack:
    some official template packs yield only one parsible official section
    (Frontiers' does), so the architecture-order scan falls back to the
    advisory order -- always labelled as advisory in the row it emits.
    """
    pack = venue_pack_dir(venue_id, root)
    if pack is None:
        return {}
    try:
        data = json.loads((pack / VENUE_STRUCTURE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    official = (data or {}).get("official") or {}
    if not isinstance(official, dict) or not official.get("sections") \
            and not official.get("mandatory_sections"):
        return {}
    norm = (data or {}).get("norm") or {}
    advisory = [str(s.get("title") or "") for s in (norm.get("sections") or [])
                if isinstance(s, dict) and str(s.get("title") or "").strip()]
    if advisory:
        official = dict(official)
        official["advisory_sections"] = advisory
    return official


_TEMPLATE_HEADING_KEY_RE = re.compile(r"[^a-z0-9]+")
_TEMPLATE_CAPTION_RE = re.compile(r"^\s*(Figure|Fig\.?|Table)\s*(\d{1,3})[A-Za-z]?\b", re.I)


def _heading_key(text) -> str:
    return _TEMPLATE_HEADING_KEY_RE.sub("", str(text or "").lower())


def _docx_style_ids(path: Path) -> list:
    """The style ids a DOCX declares, via the formatter module ([] when absent)."""
    mod = _format_module()
    fn = getattr(mod, "docx_style_ids", None)
    return fn(path) if fn is not None else []


def _docx_front_matter_report(path: Path, template: Path = None, containers=()) -> dict:
    """Front-matter/header/footer facts for one DOCX (see the formatter module)."""
    mod = _format_module()
    fn = getattr(mod, "docx_front_matter_report", None)
    return fn(path, template, containers) if fn is not None else {}


def scan_template_conformance(sources: list, requirements: dict,
                              word_template: Path = None,
                              word_template_supplementary: Path = None,
                              word_template_cover: Path = None,
                              containers=(), manuscript_names=()) -> dict:
    """Code-side official-template conformance rows over a corpus.

    `sources` is the same [(dir, prefix, excluded_top)] shape the other scans
    take. Reports, never gates: a row names the requirement and the file that
    would satisfy it. Detects the LaTeX documentclass when one is required, each
    mandatory section (by heading/title text), the statement sections, the
    ARCHITECTURE order (section sequence and figure/table caption sequence) and,
    when a Word template is given, whether each .docx carries the template's
    style ids. A cover letter is measured against `word_template_cover` only:
    with none, it is skipped -- the manuscript template does not cover a letter.
    """
    req = requirements or {}
    mandatory = [str(s) for s in (req.get("mandatory_sections") or []) if str(s).strip()]
    statements = [str(s.get("label")) for s in (req.get("statements") or [])]
    want_class = str(req.get("documentclass") or "").strip()
    official_titles = [str(s.get("title") or "") for s in (req.get("sections") or [])
                       if isinstance(s, dict) and str(s.get("title") or "").strip()]
    advisory = [str(t) for t in (req.get("advisory_sections") or []) if str(t).strip()]
    # The official pack can yield a single parsable section (Frontiers). Then the
    # recent-practice order is the only usable architecture order; the rows say
    # which basis they used.
    order_basis = "official template"
    order_titles = official_titles
    if len(order_titles) < 2 and len(advisory) >= 2:
        order_titles, order_basis = advisory, "recent practice (advisory)"
    order_index = {}
    for i, t in enumerate(order_titles):
        order_index.setdefault(_heading_key(t), i)

    have_class, texts, docs = "", [], set()
    doc_headings = []           # (doc, title) in document order
    caption_rows = []           # (doc, is_table, number)
    docx_paths = {}             # doc -> Path
    seen_section_keys = set()   # every heading label met anywhere in the corpus

    def _section_key(value) -> str:
        """A heading label without its section number ("2.1 Results" -> results)."""
        return _heading_key(re.sub(r"^\s*\d+(?:\.\d+)*\s*[.)]?\s+", "",
                                   str(value or "")))

    for src, prefix, excluded in sources:
        if not src.is_dir():
            continue
        for p in _iter_tree_files(src, follow_dir_links=True):
            if not p.is_file() or is_non_document_name(p.name) \
                    or is_bookkeeping_name(p.name):
                continue
            rel = p.relative_to(src).as_posix()
            if excluded and rel.split("/", 1)[0] in excluded:
                continue
            if is_non_manuscript_rel(rel):
                continue
            doc = prefix + rel
            ext = p.suffix.lower()
            if ext in LENGTH_DOCX_EXTS:
                paras = _docx_paragraphs(p)
                if paras is None:
                    continue
                texts.append("\n".join(paras))
                docs.add(doc)
                docx_paths[doc] = p
                seen = set()
                for para in paras:
                    line = para.strip()
                    key = _heading_key(line)
                    if key:
                        seen_section_keys.add(_section_key(line))
                    if key in order_index and key not in seen:
                        seen.add(key)
                        doc_headings.append((doc, order_titles[order_index[key]]))
                    m = _TEMPLATE_CAPTION_RE.match(line)
                    if m:
                        caption_rows.append((doc, m.group(1).lower().startswith("tab"),
                                             int(m.group(2))))
            elif ext in LENGTH_TEX_EXTS:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                texts.append(text)
                docs.add(doc)
                for m in TEX_SECTION_RE.finditer(text):
                    key = _heading_key(m.group(2))
                    if key:
                        seen_section_keys.add(_section_key(m.group(2)))
                    if key in order_index:
                        doc_headings.append((doc, order_titles[order_index[key]]))
                for line in text.splitlines():
                    m = _TEMPLATE_CAPTION_RE.match(line)
                    if m:
                        caption_rows.append((doc, m.group(1).lower().startswith("tab"),
                                             int(m.group(2))))
                m = TEX_DOCCLASS_RE.search(text)
                if m and not have_class:
                    have_class = m.group(1).strip()
            elif ext in LENGTH_TEXT_EXTS:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                texts.append(text)
                docs.add(doc)
                for m in MD_HEADING_RE.finditer(text):
                    key = _heading_key(m.group(2))
                    if key:
                        seen_section_keys.add(_section_key(m.group(2)))
                    if key in order_index:
                        doc_headings.append((doc, order_titles[order_index[key]]))
                for line in text.splitlines():
                    m = _TEMPLATE_CAPTION_RE.match(line)
                    if m:
                        caption_rows.append((doc, m.group(1).lower().startswith("tab"),
                                             int(m.group(2))))
    blob = "\n".join(texts)
    low = blob.lower()
    # A required section must be a SECTION: its label may not be satisfied by
    # the word appearing in a Results sentence somewhere in the corpus. Section
    # numbering is dropped, so "## 2. Materials and Methods" matches the
    # requirement "Materials and Methods".
    missing_sections = [s for s in mandatory
                        if _section_key(s) not in seen_section_keys]
    # A statement requirement matches by its PATTERN, not by the canonical
    # label: a template that says "Conflict of Interest" satisfies the
    # "Competing interests" requirement, and one that says "Data Availability
    # Statement" satisfies "Data availability".
    pats = {label: pat for label, pat in VENUE_STATEMENT_PATTERNS}
    missing_statements = [
        s for s in statements
        if not ((pats[s].search(blob) if s in pats else None)
                or s.strip().lower() in low)]
    # A required class cannot be satisfied by a corpus with NO LaTeX: `have_class`
    # stays "" for a Word-only submission, and treating that as "no check needed"
    # made the requirement silently disappear from both the evidence table and
    # the row list. The requirement is absent only when the venue states none.
    class_ok = (not want_class or have_class == want_class)
    # Architecture order: the first inversion per document, against the official
    # order (or the labelled advisory order when the official pack yields none).
    order_rows = []
    by_doc = {}
    for doc, title in doc_headings:
        by_doc.setdefault(doc, []).append(title)
    for doc, seq in sorted(by_doc.items()):
        for i in range(len(seq)):
            inversion = next((j for j in range(i + 1, len(seq))
                              if order_index.get(_heading_key(seq[j]), -1)
                              < order_index.get(_heading_key(seq[i]), -1)), None)
            if inversion is not None:
                order_rows.append(
                    f"{doc}: section {seq[inversion]!r} appears after {seq[i]!r} "
                    f"(order basis: {order_basis}: {' > '.join(order_titles)})")
                break
    # Figure/table labels: first occurrences must be ascending and gap-free.
    label_rows = []
    for is_table, label in ((False, "Figure"), (True, "Table")):
        nums = [n for _doc, table, n in caption_rows if table is is_table]
        first = []
        for n in nums:
            if n not in first:
                first.append(n)
        if first and first != sorted(first):
            label_rows.append(f"{label} captions are out of order: first occurrences {first}")
        if first:
            gaps = sorted(set(range(1, max(first) + 1)) - set(first))
            if gaps:
                label_rows.append(f"{label} numbering has gaps: {gaps}")
    # Word template styles: every corpus .docx must carry the ids of the
    # template that governs ITS role (main / supplementary / cover letter).
    word_styles_missing = []
    front_rows = []
    if word_template is not None or word_template_supplementary is not None \
            or word_template_cover is not None:
        main_ids = set(_docx_style_ids(Path(word_template))) if word_template else set()
        supp_ids = (set(_docx_style_ids(Path(word_template_supplementary)))
                    if word_template_supplementary is not None else set())
        cover_ids = (set(_docx_style_ids(Path(word_template_cover)))
                     if word_template_cover is not None else set())
        if main_ids or supp_ids or cover_ids:
            for doc, path in sorted(docx_paths.items()):
                role = docx_document_role(doc, manuscript_names)
                if role == "cover":
                    if word_template_cover is None:
                        continue        # no cover-letter template: not a gap
                    want, want_tpl = cover_ids, word_template_cover
                elif role == "supp":
                    want = supp_ids or main_ids
                    want_tpl = (word_template_supplementary
                                if supp_ids else word_template)
                else:
                    want, want_tpl = main_ids, word_template
                if not want or want_tpl is None:
                    continue
                missing = sorted(want - set(_docx_style_ids(path)))
                if missing:
                    word_styles_missing.append({"document": doc, "missing": missing[:12],
                                                "missing_count": len(missing)})
                fm = _docx_front_matter_report(path, want_tpl, containers)
                for row in (fm or {}).get("rows") or []:
                    front_rows.append(f"{doc}: {row}")
    conforms = (bool(req) and not missing_sections and not missing_statements and class_ok
                and not order_rows and not label_rows and not word_styles_missing
                and not front_rows)
    return {"official": bool(req), "required": {"documentclass": want_class,
                                                "mandatory_sections": mandatory,
                                                "statements": statements},
            "found": {"documentclass": have_class, "documents": sorted(docs)},
            "missing_sections": missing_sections, "missing_statements": missing_statements,
            "class_ok": class_ok, "order_basis": order_basis,
            "order_rows": order_rows, "label_rows": label_rows,
            "word_styles_missing": word_styles_missing,
            "word_template_ok": not word_styles_missing,
            "front_matter_rows": front_rows,
            "conforms": conforms,
            "note": ("advisory, code-side: a row names a requirement the official template "
                     "demands and the corpus does not show; the review disposes it"
                     if req else "no official template pack for this venue")}


def venue_profiles_write_dir(root=None) -> Path:
    """Where `add-venue` writes: `<root>/venue_profiles/` when a root is given,
    else the venue_profiles/ directory shipped next to this script."""
    dirs = venue_profile_search_dirs(root)
    return dirs[0] if dirs else Path(VENUE_PROFILES_DIRNAME)


def _exemplar_files(dirp: Path) -> list:
    """Every supported exemplar file under one corpus dir, sorted."""
    out = []
    for p in sorted(dirp.rglob("*")):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf in VENUE_EXEMPLAR_TEXT_SUFFIXES or suf in VENUE_EXEMPLAR_DOCX_SUFFIXES:
            out.append(p)
    return out


def _sections_from_text(text: str, suffix: str) -> list:
    """[(level, title)] in reading order, from a .tex or markdown/text body."""
    if suffix == ".tex":
        return [(_TEX_LEVELS.get(kind, 1), title.strip())
                for kind, title in TEX_SECTION_RE.findall(text) if title.strip()]
    if suffix in (".md", ".markdown"):
        # Markdown levels are normalized to the LaTeX convention: the first
        # `#` heading is the TITLE (dropped below), `##` is a top-level section
        # (level 1), `###` a subsection (level 2), ...
        raw = [(len(hashes), title.strip())
               for hashes, title in MD_HEADING_RE.findall(text) if title.strip()]
        heads = [(max(1, lvl - 1), title) for lvl, title in raw]
        if raw and raw[0][0] == 1:
            heads = heads[1:]      # the leading `#` heading is the TITLE
        return heads
    return []


def _docx_exemplar_text(path: Path):
    """[(level, title)] + full text from a .docx, or None when unreadable."""
    mod = _format_module()
    if mod is None:
        return None
    try:
        with zipfile.ZipFile(path) as pkg:
            xml = pkg.read("word/document.xml").decode("utf-8", "replace")
    # RuntimeError is what `zipfile` raises for an ENCRYPTED entry and
    # NotImplementedError for an unsupported compression method: neither is an
    # OSError/BadZipFile/KeyError, so a reader that answers "unreadable" must
    # name them (see `paper_docx_format.analyse_package`).
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        return None
    sections, lines = [], []
    for _s, _e, frag in mod.paragraphs(xml):
        text = mod.text_of(frag).strip()
        if not text:
            continue
        lines.append(text)
        style = mod.elem_val(mod.ppr_of(frag), "pStyle") or ""
        m = re.match(r"(?i)^heading\s*([1-4])$", style.replace("-", "").replace(" ", ""))
        if not m:
            m = re.match(r"(?i)^heading([1-4])$", style)
        if m:
            sections.append((int(m.group(1)), text))
    return sections, "\n".join(lines)


def extract_manuscript_structure(path: Path) -> dict:
    """The structure of ONE exemplar: sections, abstract, statements, hash.

    Structure ONLY: the prose is never stored in the pack. An unsupported or
    unreadable file is reported as `skipped` by the caller.
    """
    suffix = path.suffix.lower()
    sections, text = [], ""
    if suffix in VENUE_EXEMPLAR_TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {"skipped": "unreadable"}
        sections = _sections_from_text(text, suffix)
        abstract = bool(TEX_ABSTRACT_RE.search(text) if suffix == ".tex"
                        else MD_ABSTRACT_RE.search(text))
    elif suffix in VENUE_EXEMPLAR_DOCX_SUFFIXES:
        parsed = _docx_exemplar_text(path)
        if parsed is None:
            return {"skipped": "docx text could not be extracted (paper_docx_format.py missing "
                               "or not a readable .docx)"}
        sections, text = parsed
        abstract = any(lvl == 1 and t.strip().lower() == "abstract" for lvl, t in sections)
    else:
        return {"skipped": f"unsupported suffix {suffix!r}"}
    statements = [label for label, pat in VENUE_STATEMENT_PATTERNS if pat.search(text)]
    return {"file": path.name, "format": suffix.lstrip("."), "sha256": sha256_file(path),
            "sections": [{"level": lvl, "title": title} for lvl, title in sections],
            "abstract": bool(abstract), "statements": statements}


def structure_norm(records: list) -> dict:
    """The ADVISORY norm: modal section order, presence counts, statements.

    Ordering is by MEAN POSITION (a section's average index across the
    exemplars that carry it), so a section most exemplars put first comes
    first; ties break alphabetically. Presence counts are reported next to the
    order so the reader sees how strong each part of the norm is.
    """
    n = len(records)
    positions, spellings, counts = {}, {}, {}
    for rec in records:
        for i, sec in enumerate(rec.get("sections") or []):
            if int(sec.get("level") or 0) != 1:
                # The modal order is the TOP-LEVEL order; subsections belong to
                # their parent and are reported in structure.json only.
                continue
            key = str(sec.get("title") or "").strip().lower()
            if not key or _is_guidance_title(sec.get("title")):
                continue
            if _section_is_statement(sec.get("title")):
                # Statement sections are reported under "Statement placement",
                # not in the body-section order.
                continue
            counts[key] = counts.get(key, 0) + 1
            positions.setdefault(key, []).append(i)
            spellings.setdefault(key, {})
            spellings[key][sec["title"].strip()] = spellings[key].get(sec["title"].strip(), 0) + 1
    order = sorted(counts, key=lambda k: (sum(positions[k]) / len(positions[k]), k))
    sections = [{"title": max(spellings[k], key=spellings[k].get),
                 "present": counts[k], "n_exemplars": n,
                 "mean_position": round(sum(positions[k]) / len(positions[k]), 2)}
                for k in order]
    statements = []
    for label, _pat in VENUE_STATEMENT_PATTERNS:
        c = sum(1 for r in records if label in (r.get("statements") or []))
        if c:
            statements.append({"label": label, "present": c, "n_exemplars": n})
    return {"n_exemplars": n, "sections": sections, "statements": statements,
            "abstract_present": sum(1 for r in records if r.get("abstract")),
            "formats": sorted({str(r.get("format")) for r in records if r.get("format")}),
            "exemplars": records}


def _norm_section_titles(norm: dict) -> list:
    return [s["title"] for s in (norm.get("sections") or [])]


def _section_is_statement(title) -> bool:
    """True when a section TITLE names one of the template's statement blocks."""
    low = str(title or "").strip().lower()
    return bool(low) and any(pat.search(low) for _label, pat in VENUE_STATEMENT_PATTERNS)


def render_architecture_summary(venue_id: str, norm: dict, official: dict = None) -> str:
    """The structure summary the prompts embed: OFFICIAL first, advisory norm second."""
    off = official or {}
    L = [f"# Venue structure -- {venue_id}", ""]
    if off.get("sections") or off.get("mandatory_sections"):
        L += ["## OFFICIAL journal template (AUTHORITATIVE)", "",
              f"Derived by CODE from {off.get('n_samples') or 0} file(s) of the venue's OWN "
              f"template pack"
              + (f" (class `{off['documentclass']}`)" if off.get("documentclass") else "")
              + ". STRUCTURE ONLY.", "",
              "| # | section | present | mandatory |", "|---|---|---|---|"]
        mandatory = {m.lower() for m in (off.get("mandatory_sections") or [])}
        for i, s in enumerate(off.get("sections") or [], 1):
            L.append(f"| {i} | {s['title']} | {s['present']}/{s['n_samples']} | "
                     + ("YES" if s["title"].lower() in mandatory else "") + " |")
        if off.get("mandatory_sections"):
            L += ["", "Mandatory sections (must exist): "
                  + ", ".join(off["mandatory_sections"]) + "."]
        if off.get("statements"):
            shown = {}
            for title in off.get("statement_sections") or []:
                for label, pat in VENUE_STATEMENT_PATTERNS:
                    if label not in shown and pat.search(title):
                        shown[label] = title
            L += ["", "Statement sections the template carries:", ""]
            for s in off["statements"]:
                L.append(f"- {s['label']} ({s['present']}/{s['n_samples']}"
                         + (f"; template heading: {shown[s['label']]}"
                            if s["label"] in shown else "") + ")")
        L += ["", "Rules: use the journal's template/class and its styles; the mandatory "
              "sections must be present; declaration blocks use the template's own wording; "
              "content the template requires but the manuscript cannot supply becomes a "
              "manual item for the author, never invented text.", ""]
    n = norm.get("n_exemplars") or 0
    if norm.get("sections"):
        L += [f"## Recent-practice structure (ADVISORY, {n} exemplar manuscript(s))", "",
              f"Derived by CODE from {n} exemplar manuscript(s) downloaded from the venue's own "
              f"published articles (formats: {', '.join(norm.get('formats') or []) or 'n/a'}). "
              f"STRUCTURE ONLY: no prose was copied.", "",
              "| # | section | present | mean position |", "|---|---|---|---|"]
        for i, s in enumerate(norm.get("sections") or [], 1):
            L.append(f"| {i} | {s['title']} | {s['present']}/{s['n_exemplars']} | "
                     f"{s['mean_position']:g} |")
        if norm.get("abstract_present"):
            L.append("")
            L.append(f"- Abstract: present in {norm['abstract_present']}/{n} exemplar(s).")
        if norm.get("statements"):
            L += ["", "Statement placement (recent practice):", ""]
            for s in norm["statements"]:
                L.append(f"- {s['label']}: {s['present']}/{s['n_exemplars']}")
        L += ["", "This part is ADVISORY: it fills what the official template leaves open and "
              "never overrides it; no section is added or removed merely to match it."]
    if not L[-1]:
        L.pop()
    return "\n".join(L)


def _skeleton_titles(norm: dict, official: dict = None) -> list:
    """The skeleton order: the OFFICIAL sections as the backbone, completed by
    the advisory norm's sections (inserted at their modal positions)."""
    off = list((official or {}).get("sections") or [])
    adv = list(norm.get("sections") or [])
    if not off:
        return [s["title"] for s in adv] or ["Abstract", "Introduction", "Methods", "Results",
                                             "Discussion"]

    def key(title):
        words = re.findall(r"[a-z0-9]+", str(title).lower())
        return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words)

    merged = [s["title"] for s in off]
    # The insert position must be found in the list that GROWS, never in `off`:
    # once one advisory section was inserted, index `i` of `off` no longer names
    # the same slot of `merged`, so a later advisory section landed BEFORE its
    # predecessor (Ethics 0.5, Data availability 0.6 -> the 0.6 section came
    # first). `merged_pos` carries each merged slot's mean_position in parallel.
    merged_pos = [float(o.get("mean_position", 99)) for o in off]
    seen = {key(t) for t in merged}
    word_sets = [set(key(t).split()) for t in merged]
    for a in adv:
        title = a["title"]
        k = key(title)
        if k in seen:
            continue
        if len(k.split()) == 1 and any(k in ws for ws in word_sets):
            # A one-word variant ("Methods", "Conclusion") is folded into the
            # fuller heading already present.
            continue
        idx = len(merged)
        for i, pos in enumerate(merged_pos):
            if float(a.get("mean_position", 99)) <= pos:
                idx = i
                break
        merged.insert(idx, title)
        merged_pos.insert(idx, float(a.get("mean_position", 99)))
        seen.add(k)
        word_sets.append(set(k.split()))
    return merged


def _skeleton_statements(norm: dict, official: dict = None) -> list:
    off = official or {}
    if off.get("statement_sections"):
        # The template's OWN wording for the declaration blocks wins over the
        # canonical labels.
        return list(off["statement_sections"])
    if off.get("statements"):
        return [s["label"] for s in off["statements"]]
    return [s["label"] for s in (norm.get("statements") or [])]


def render_word_template(venue_id: str, norm: dict, official: dict = None) -> str:
    """A Word-oriented skeleton: heading levels + statement placeholders."""
    off = official or {}
    titles = _skeleton_titles(norm, off)
    mandatory = {m.lower() for m in (off.get("mandatory_sections") or [])}
    L = [f"<!-- Word template skeleton for venue '{venue_id}'. Structure only; replace every "
         f"placeholder. Word styles: use Heading 1 for the title, Heading 2 for top-level "
         f"sections and Heading 3 for subsections, so the generated .docx carries a navigable "
         f"outline."
         + (" The sections marked [MANDATORY] come from the journal's OWN template: they must "
            "exist. Use the styles the journal's .dotx/.docx template provides."
            if off.get("sections") else "")
         + " -->", "",
         "# <Manuscript title>", ""]
    statement_labels = _skeleton_statements(norm, off)
    for title in titles:
        mark = " [MANDATORY]" if title.strip().lower() in mandatory else ""
        if title.strip().lower() in ("abstract",):
            L += [f"## Abstract{mark}", "", "<Abstract: one paragraph, no citations.>", ""]
            continue
        L += [f"## {title}{mark}", "", f"<{title} text.>", ""]
    for label in statement_labels:
        L += [f"## {label}", "", f"<{label} statement.>", ""]
    L += ["<!-- End of template. The section list follows the journal's OWN template when one "
          "is present (otherwise the venue's modal order); adjust only where the manuscript's "
          "content or the venue's guidelines require it. -->"]
    return "\n".join(L)


def render_latex_template(venue_id: str, norm: dict, official: dict = None) -> str:
    """A LaTeX skeleton: the journal's class/section order when one is known."""
    off = official or {}
    titles = _skeleton_titles(norm, off)
    statement_labels = _skeleton_statements(norm, off)
    docclass = str(off.get("documentclass") or "").strip()
    L = ["% LaTeX template skeleton for venue '" + venue_id + "'.",
         "% Structure only: replace the placeholders with the manuscript's own content."]
    if docclass:
        L += [f"% The journal's OWN template uses \\documentclass{{{docclass}}}; keep it (and "
              f"the class file the template ships).",
              f"\\documentclass{{{docclass}}}"]
    else:
        L += ["% No official class file was found: use the journal's template class here.",
              "\\documentclass[11pt]{article}"]
    L += ["\\usepackage[utf8]{inputenc}",
          "\\usepackage{graphicx}",
          "\\usepackage{amsmath}",
          "",
          "\\title{<Manuscript title>}",
          "\\author{<Authors>}",
          "\\date{}",
          "",
          "\\begin{document}",
          "\\maketitle",
          ""]
    for title in titles:
        low = title.strip().lower()
        if low == "abstract":
            L += ["\\begin{abstract}", "<Abstract: one paragraph, no citations.>", "\\end{abstract}",
                  ""]
            continue
        L += [f"\\section{{{title}}}", f"% <{title} text.>", ""]
    for label in statement_labels:
        L += [f"\\section*{{{label}}}", f"% <{label} statement.>", ""]
    L += ["\\end{document}"]
    return "\n".join(L)


def build_venue_templates(venue_id, root=None, profiles_dir=None, exemplar_dir=None,
                          official_dir=None) -> dict:
    """Generate the pinned structure-only pack for one venue.

    Inputs: the venue's OFFICIAL template files
    (`<venue-id>.official/`, AUTHORITATIVE) and/or the exemplar manuscripts
    (`<venue-id>.manuscripts/`, ADVISORY). Deterministic (no timestamps): the
    same inputs produce byte-identical files, and MANIFEST.json pins every input
    and output by sha256, plus the downloaders' source provenance, so a run that
    embedded the summary can be reproduced and audited.
    """
    vid = str(venue_id or "").strip().lower()
    if not vid:
        die("build-venue-templates needs a venue id")
    src_dirs = []
    if exemplar_dir:
        src_dirs = [Path(exemplar_dir)]
    else:
        if profiles_dir:
            local = Path(profiles_dir) / f"{vid}{VENUE_EXEMPLAR_SUFFIX}"
            if local.is_dir():
                src_dirs.append(local)
        src_dirs.extend(d for d in venue_exemplar_dirs(vid, root) if d not in src_dirs)
    write_dir = (Path(profiles_dir) if profiles_dir
                 else (src_dirs[0].parent if src_dirs else venue_profiles_write_dir(root)))
    off_dirs = ([Path(official_dir)] if official_dir
                else venue_official_dirs(vid, root, profiles_dir))
    files = []
    for d in src_dirs:
        files.extend(_exemplar_files(d))
    records, skipped = [], []
    for p in files:
        rec = extract_manuscript_structure(p)
        if rec.get("skipped"):
            skipped.append({"file": p.name, "why": rec["skipped"]})
        else:
            records.append(rec)
    off_files = []
    off_archives = []
    for d in off_dirs:
        off_files.extend(_exemplar_files(d))
        off_archives.extend(p for p in sorted(d.rglob("*.zip")) if p.is_file())
    off_records, off_skipped = [], []
    # The pack builder has no selected run type: use the profile's DEFAULT type
    # names. Feeding EVERY type in made a second article-type template
    # (a Letter to the Editor) a manuscript sample, which emptied the venue's
    # mandatory-section set and re-admitted its boilerplate as venue-wide
    # statements -- the very defect F067/F068 removed.
    _tmpl_names = _normalized_article_type_names(
        _profile_for_template_names(vid, root, profiles_dir))
    for p in off_files:
        # EVERY suffix, not only .docx: a Cover_Letter.tex is a deliverable too,
        # and its letter boilerplate used to enter the venue's authoritative
        # statements table as manuscript structure.
        if docx_document_role(p.name, _tmpl_names) == "cover":
            # A cover-letter template is a deliverable, not a manuscript
            # skeleton: parsing its salutation/recipient lines as "mandatory
            # sections" would corrupt the venue's requirements.
            off_skipped.append({"file": p.name,
                                "why": "cover-letter template (not a manuscript skeleton)"})
            continue
        rec = extract_official_template(p)
        if rec.get("skipped"):
            off_skipped.append({"file": p.name, "why": rec["skipped"]})
        else:
            off_records.append(rec)
    explicit = None
    for d in off_dirs:
        p = d / VENUE_OFFICIAL_REQUIREMENTS
        if p.is_file():
            try:
                explicit = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                explicit = None
            break
    if not records and not off_records:
        looked = [str(d) for d in src_dirs + off_dirs]
        return {"venue": vid, "exemplars": 0, "official": 0, "skipped": skipped + off_skipped,
                "written": [], "looked": looked,
                "note": "no readable official template and no readable exemplar manuscripts "
                        "were found"
                        + (f" under {', '.join(looked)}" if looked else "")}
    norm = structure_norm(records)
    official = official_skeleton(off_records, explicit)
    out_dir = write_dir
    pack = out_dir / f"{vid}{VENUE_TEMPLATE_SUFFIX}"
    pack.mkdir(parents=True, exist_ok=True)
    payload = {
        VENUE_STRUCTURE_FILE: json.dumps({"venue": vid, "official": official, "norm": norm},
                                         indent=2,
                                         sort_keys=True) + "\n",
        VENUE_NORM_FILE: render_architecture_summary(vid, norm, official) + "\n",
        VENUE_WORD_TEMPLATE: render_word_template(vid, norm, official) + "\n",
        VENUE_LATEX_TEMPLATE: render_latex_template(vid, norm, official) + "\n",
    }
    manifest = {"venue": vid, "pipeline_version": VERSION,
                "generated_from": [{"file": r["file"], "sha256": r["sha256"],
                                    "format": r.get("format")} for r in records],
                "official_files": [{"file": r["file"], "sha256": r["sha256"],
                                    "format": r.get("format")} for r in off_records],
                "skipped": skipped + off_skipped,
                "files": {}}
    # The downloader's own provenance (source URL/DOI/license/retrieval date per
    # article) travels into the pack's manifest, so the norm can be audited back
    # to the exact public sources it was derived from.
    prov = None
    for d in src_dirs:
        p = d / "manifest.json"
        if p.is_file():
            try:
                prov = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prov = None
            break
    if prov is not None:
        manifest["sources"] = prov
    for d in off_dirs:
        p = d / "manifest.json"
        if p.is_file():
            try:
                manifest["official_sources"] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            break
    for name, text in payload.items():
        p = pack / name
        write_text_atomic(p, text)
        manifest["files"][name] = sha256_file(p)
    write_json_atomic(pack / VENUE_PACK_MANIFEST, manifest)
    return {"venue": vid, "exemplars": len(records), "official": len(off_records),
            "official_archives": [p.name for p in off_archives],
            "skipped": skipped + off_skipped,
            "pack": str(pack), "files": sorted(payload) + [VENUE_PACK_MANIFEST],
            "norm_sections": _skeleton_titles(norm, official),
            "mandatory_sections": official.get("mandatory_sections") or [],
            "documentclass": official.get("documentclass") or "",
            "written": sorted(payload)}


VENUE_NORM_RULES = """\
=== VENUE TEMPLATE / STRUCTURE (read together with the venue profile) ===

The excerpt below was derived by CODE (structure only: section order, the class file, abstract
and statement placement; no prose was copied). Two tiers, with different authority:

  * **The OFFICIAL journal template is AUTHORITATIVE.** When the excerpt names one: use the
    journal's own template/class and its styles, keep every MANDATORY section it lists, keep the
    declaration blocks it provides (use its own wording for them), and do not invent a section
    order that contradicts it. A requirement the template demands but the manuscript cannot
    supply (e.g. an ethics statement that does not apply) becomes a precise MANUAL item for the
    author -- never invented text. The venue's author guidelines (the profile) still come first
    where they state a number or a rule the template does not.
  * **The recent-practice part is ADVISORY.** It fills what the official template leaves open
    (e.g. how the body is usually organised). Follow it only where it serves the content; never
    add empty sections to match it, and never let it override the official template.

  * NEVER copy sentences, headings' phrasing or paragraph text from any published article or
    from a template's sample manuscript: structure and boilerplate declarations only, and the
    manuscript's prose must be its authors' own.
  * Neither tier is a gate or a score by itself: the code-side conformance rows in
    `work/OFFICIAL_TEMPLATE.md` are evidence for the review's J5/M20 disposition, and no
    finding may rest on a descriptive deviation alone. A missing MANDATORY section or a wrong
    class file is a real conformance finding; a deviation from the ADVISORY part is recorded
    under J5 with one sentence and is allowed.
  * ARCHITECTURE AND FORMATTING FOLLOW THE TEMPLATE when the venue ships one: the
    section/subsection set and their ORDER, the declaration blocks, the figure/table labels and
    their order, and the fonts, paragraph spacing, indentation and heading styles all come from
    the template's own file. A read-only copy is staged in `venue_template/` and every produced
    manuscript / supplementary .docx is restyled into the template's styles by the code-side
    normalizer before the postcheck -- keep those styles and never re-copy the previous
    venue's. (The cover letter is the exception: see the next bullet.)
  * THE COVER LETTER IS NOT A MANUSCRIPT DOCUMENT: the manuscript template's front matter and
    styles cover the manuscript. When the venue ships its own cover-letter template the letter is
    built in that file; when it ships none, the letter follows the journal's own cover-letter /
    scope-statement guidance (the profile records the source) and then established academic
    convention for a submission letter (recipient block, date, salutation, body, closing and
    signature) -- the manuscript template is NEVER applied to it, and its styles are never
    demanded of it.
  * THE FIRST PAGE, THE TYPE SCALE AND THE HEADING DEPTH COME FROM THE TEMPLATE: use its title
    style (as centered as the template renders it), its author-list/front-matter style (as bold
    as the template renders it), the affiliation/correspondence block it carries, ONE
    "Keywords: ..." line and the template's UNNUMBERED abstract front matter; section numbering
    starts with the first body section. Do not create heading levels deeper than the template's
    own document uses (never a sub-sub-section such as 2.2.1 when the template stops at 2.2).
    The template's first-page header (logo) and its page-number footer are part of the
    deliverable, not decoration.
  * THE FIRST-PAGE BLOCK IS THE TEMPLATE'S OWN, IN ITS ORDER AND SPACING: one title line, ONE
    author-list line, the affiliation lines the template spaces with before=240/after=0, then ONE
    correspondence block -- the BOLD label "* Correspondence:" followed by a line break, the
    corresponding author's name (when the source marks a lead contact or a
    corresponding author), another line break and the email -- then ONE "Keywords: ..." line and
    the unnumbered "Abstract" heading with its paragraph. Fold a separate "Lead contact" /
    "Corresponding author" line into that block instead of leaving it as its own paragraph, and
    never keep the old publisher's "Highlights"/"Summary"/"Motivation" containers.
  * STYLE AND ARCHITECTURE FALL BACK IN LEVELS -- move to the NEXT level only for what the
    current level leaves UNSPECIFIED: (1) the TEMPLATE files above are the first authority;
    (2) anything they do not pin follows the journal's/venue's OFFICIAL GUIDELINES on its own
    website (the run's profile records the source it was built from -- see the pack's
    `sources`/`guidelines_source` -- and the prompt's guideline note); (3) anything still
    unstated at that level follows ESTABLISHED ACADEMIC CONVENTION -- e.g. table text one step
    smaller than the body text, single-spaced inside the table, the caption in the body font at
    body size, a table that breaks across pages repeating its header row. Record which level
    each such choice came from in the package's report. Never invent a requirement no level
    states, never let level (1) override level (2) for something the template leaves open, and
    never leave a style unset.
  * CONTAINER HEADINGS THAT BELONG TO ANOTHER PUBLISHER'S TEMPLATE (for example "Lead contact",
    "Resource availability", "Materials availability", "Method details", or a bare "Key
    resources" heading) are not part of this venue's structure: fold their content into the
    template's own sections (Methods subsections, Statements, or the tables/figures area) and
    place each table caption immediately before its table.
@@TRANSFER@@

@@NORM@@
"""

VENUE_TRANSFER_RULES = """
  * **TRANSFER MODE (new journal, no response letter):** the target venue's official template
    REPLACES the previous venue's. Treat the old class file/styles, old section names, old
    declaration wording, old reference style and old figure/supplementary conventions as
    findings to remove, and verify the new venue's mandatory sections and statements exist.
    Answer the review concerns from `human_review_feedback/` (and from
    `llm_review_feedback/` when the corpus carries the pre-filtered LLM review) where they still
    apply; never depend on a response letter. The human area's child `original_submission/`,
    when present, is the manuscript version those reviewers actually saw -- evidence for
    understanding a concern, never the current submission and never a source of text to copy.
    Every remaining LLM-review finding is a real concern (its false positives were filtered out
    upstream), never noise to dismiss."""


def venue_norm_block(venue_id, root=None, transfer: bool = False,
                     manuscript_names=None) -> str:
    """The template/norm prompt block for one venue, or "" when it has no pack."""
    pack = venue_pack_dir(venue_id, root)
    if pack is None:
        return ""
    try:
        summary = (pack / VENUE_NORM_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    digest = sha256_file(pack / VENUE_NORM_FILE)
    text = (VENUE_NORM_RULES.replace("@@NORM@@", summary)
            .replace("@@TRANSFER@@", VENUE_TRANSFER_RULES if transfer else ""))
    files = (official_template_files(venue_id, root, manuscript_names=manuscript_names)
             if venue_templates_enabled() else {})
    word = files.get("word") or {}
    latex = files.get("latex") or {}
    if word or latex:
        lines = ["", "TEMPLATE FILES FOR THIS RUN (the producing/reviewing sandboxes carry a "
                     "read-only `venue_template/` copy of the venue's own files, and their render "
                     "-- when this machine could make one -- is staged for the visual pass under "
                     "`visual_template/`):",
                     "  * READ THE TEMPLATE FILES YOURSELF -- they are this run's authority for "
                     "architecture and formatting, whatever your role: the REVIEW and the AUDIT "
                     "dispose every template-conformance row (OFFICIAL_TEMPLATE.md) against "
                     "these files and never invent a rule they do not state; the REWRITE, "
                     "REVISE and INTEGRATE agents keep the template's styles, numbering, "
                     "bullets/indentation and furniture while they edit content; the JUDGE "
                     "compares the package's own render with `visual_template/` side by side "
                     "(title page, running head/logo, footers, heading depth, caption placement) "
                     "in its visual record. Every decision must be checkable against these "
                     "files: a claim about a \"journal rule\" that neither the template nor the "
                     "venue's official guidelines states is a defect of the claim."]
        if word.get("main"):
            lines.append(f"  * Word (.docx): venue_template/word/{Path(word['main']).name}"
                         + (f"; supplementary: venue_template/word/"
                            f"{Path(word['supplementary']).name}" if word.get("supplementary")
                            else "")
                         + (f"; cover letter: venue_template/word/"
                            f"{Path(word['cover']).name}" if word.get("cover") else ""))
        lines.append(
            "  * THE MANUSCRIPT TEMPLATES DO NOT COVER THE COVER LETTER. When the "
            "venue ships a cover-letter template it is restyled into it; otherwise the "
            "letter follows the journal's own cover-letter / scope-statement guidance "
            "(the profile records it) and then established academic convention for a "
            "submission letter -- never the manuscript template's Title/Author/Abstract "
            "front matter.")
        if latex.get("sample"):
            lines.append(f"  * LaTeX: venue_template/latex/{Path(latex['sample']).name}"
                         + ("; class: " + ", ".join(Path(p).name for p in latex.get("cls") or [])
                            if latex.get("cls") else "")
                         + ("; bibliography style: "
                            + ", ".join(Path(p).name for p in latex.get("bst") or [])
                            if latex.get("bst") else ""))
        try:
            _prof = load_venue_profile(venue_id, root=root)
            _source = str((_prof.data.get("prompt") or {}).get("guidelines_source") or "").strip()
            _cguide = cover_letter_guidance_clause(cover_letter_guidance(_prof))
        except VenueProfileError:
            _source, _cguide = "", ""
        if _source:
            lines.append(f"  * The venue's official guidance this run records: {_source}")
        if _cguide:
            lines.append(f"  * The cover letter's recorded guideline basis: {_cguide}")
        lines.append("  * Every produced MANUSCRIPT / SUPPLEMENTARY .docx is restyled into its "
                     "Word template's styles and theme by the code-side normalizer before the "
                     "postcheck -- the cover letter is NOT, unless this venue ships a cover-letter "
                     "template. Keep the template's heading styles, statement names, and figure/"
                     "table label order; do not reintroduce the previous venue's styles.")
        if word.get("main"):
            lines.append("  * `visual_template/<role>/` holds the templates' own PDF and page "
                         "images (`manifest.json` names the renderer and each document's page "
                         "count): compare your render side by side with them and name each "
                         "template document and its page count in the visual-inspection record.")
        text += "\n" + "\n".join(lines)
    return text + f"\n\n(pack: {pack} -- {VENUE_NORM_FILE} sha256 {digest[:16]})"


def venue_norm_for(ctx: "Ctx") -> str:
    """The template/structure block for ONE root, with the mode's transfer rules."""
    if getattr(ctx, "root", None) is None:
        return ""                      # a stub/partial context carries no root-local profiles
    return venue_norm_block(venue_id_of(ctx), ctx.root,
                            transfer=(journal_mode_of(ctx) == JOURNAL_MODE_TRANSFER),
                            manuscript_names=article_type_manuscript_names(ctx))


def venue_word_templates(ctx: "Ctx") -> dict:
    """The venue's official Word templates: {"main", "supplementary", "cover"}.

    Empty when the venue ships no `.official` Word template; passed to the
    formatter so every produced .docx is restyled into the journal's own
    template instead of merely being described to the agents. A venue that
    ships no cover-letter template simply has no "cover" entry: the normalizer
    then leaves the letter to the guideline/academic-convention chain and never
    applies the manuscript template to it.
    """
    root = getattr(ctx, "root", None)
    if root is None:
        return {}                      # a stub/partial context carries no root-local profiles
    if not venue_templates_enabled():
        return {}                      # operator opt-out (PAPER_VENUE_TEMPLATES=0)
    res = official_template_files(venue_id_of(ctx), root,
                                  manuscript_names=article_type_manuscript_names(ctx))
    word = res.get("word") or {}
    out = {}
    for key in ("main", "supplementary", "cover"):
        if word.get(key):
            out[key] = Path(word[key])
    return out


def _ctx_cfg(ctx) -> dict:
    cfg = getattr(ctx, "cfg", None)
    return cfg if isinstance(cfg, dict) else {}


def venue_containers(ctx: "Ctx") -> tuple:
    """The foreign-publisher block headings THIS venue declares (may be empty).

    A profile lists the other publisher's blocks its own submission must not
    keep ("Lead contact", "Key resources", ...). The formatter stays agnostic:
    it only ever sees this tuple, and a venue that declares none gets no
    container rule at all.
    """
    prof = venue_profile_of(ctx, required=False)
    if prof is None:
        return ()
    return tuple(str(c) for c in (prof.data.get("foreign_container_headings") or ()) if str(c))


def venue_id_of(ctx=None) -> str:
    """The venue id a root (or a config dict) records, or the default venue."""
    cfg = _ctx_cfg(ctx)
    vid = str(cfg.get("venue") or "").strip().lower()
    return vid or DEFAULT_VENUE


# The display-rule inheritance (`_snapshot_profile`) reads the venue's profile
# file when a snapshot predates the `tables`/`figures` fields. That lookup runs
# ONCE per (root, venue, missing fields) per process: `format_policy_of` is on
# every scan and every stage postcheck, and re-reading + re-parsing the profile
# JSON on each call measurably slowed whole rounds down. A profile file edited
# in the MIDDLE of one command is therefore not picked up by an already-cached
# lookup -- re-run the command, as with every other recorded-rule change.
_DISPLAY_RULE_INHERIT_CACHE: dict = {}


def _inherited_display_rules(venue_id: str, root, missing: tuple) -> dict:
    """The shipped profile's display rules a pre-schema snapshot may inherit."""
    key = (str(root), venue_id, missing)
    if key in _DISPLAY_RULE_INHERIT_CACHE:
        return _DISPLAY_RULE_INHERIT_CACHE[key]
    inherited: dict = {}
    try:
        fresh = load_venue_profile(venue_id, root=root)
    except VenueProfileError:
        fresh = None          # no readable file: the snapshot keeps running rule-free
    if fresh is not None:
        if "tables" in missing and fresh.declares_table_rule:
            inherited["tables"] = copy.deepcopy(fresh.tables)
        if "figures" in missing and fresh.declares_figure_rule:
            inherited["figures"] = copy.deepcopy(fresh.figures)
        # The reference-entry preference, the numbering convention and the
        # leftover-phrase list are the same kind of field: they did not exist
        # when a pre-2026-10-09 snapshot was recorded, and a root that carries
        # none of them would scan with fewer rules than the postcheck does.
        # Inherit each one ONLY when the snapshot does not carry its key.
        if "references" in missing and (fresh.data.get("references") or {}):
            inherited["references"] = copy.deepcopy(fresh.data["references"])
        if "numbering" in missing and str(fresh.data.get("numbering") or ""):
            inherited["numbering"] = str(fresh.data["numbering"])
        if "leftover_phrases" in missing and (fresh.data.get("leftover_phrases") or ()):
            inherited["leftover_phrases"] = copy.deepcopy(
                list(fresh.data["leftover_phrases"]))
        # The raster-text and image-DPI floors and the foreign-heading list were
        # added after the first snapshots: a pre-schema root kept FMT-IM6 and
        # FMT-IM4 (and the foreign-heading scan) switched off forever.
        if "figure_text" in missing and (fresh.data.get("figure_text") or {}):
            inherited["figure_text"] = copy.deepcopy(fresh.data["figure_text"])
        if "image_dpi" in missing and (fresh.data.get("image_dpi") or {}):
            inherited["image_dpi"] = copy.deepcopy(fresh.data["image_dpi"])
        if "foreign_container_headings" in missing and (
                fresh.data.get("foreign_container_headings") or ()):
            inherited["foreign_container_headings"] = copy.deepcopy(
                list(fresh.data["foreign_container_headings"]))
        # The M19 counting convention is the same kind of field: a snapshot
        # recorded before it existed would count every venue with the NBT
        # Article convention, including a Frontiers root (which counts Methods).
        if "counting" in missing:
            if fresh.data.get("counting"):
                inherited["counting"] = copy.deepcopy(fresh.data["counting"])
            # A TYPE's own block (NBT's Brief Communication counts the abstract,
            # references and legends) must travel too: the venue-level block is
            # the default type's, so a Brief root that inherited only that would
            # silently count like an Article.
            type_counting = {str(t.get("id")): copy.deepcopy(t["counting"])
                             for t in (fresh.data.get("article_types") or [])
                             if isinstance(t, dict) and t.get("counting")}
            if type_counting:
                inherited["_type_counting"] = type_counting
    _DISPLAY_RULE_INHERIT_CACHE[key] = inherited
    return inherited


def _snapshot_profile(cfg: dict, venue_id: str, root=None):
    """The profile snapshot recorded in the config, when it matches the id.

    A snapshot recorded BEFORE the `tables`/`figures` schema existed carries no
    display rule at all, and the recorded snapshot normally wins over the files
    on disk. That would leave a root created earlier with no rule forever, so
    those fields -- and only those -- are inherited from the venue's own profile
    file, each one only when the snapshot does not carry its key at all (a
    snapshot that carries an explicit block, including an empty one, is
    authoritative, and re-recording with `set-venue` keeps working as before).
    The M19 counting convention inherits the same way, INCLUDING each article
    type's own block when that type counts differently from the venue default.
    """
    snapshot = cfg.get("venue_profile")
    if not isinstance(snapshot, dict):
        return None
    missing = tuple(k for k in ("tables", "figures", "references", "numbering",
                                "leftover_phrases", "counting", "figure_text",
                                "image_dpi", "foreign_container_headings")
                    if k not in snapshot)
    if missing:
        inherited = _inherited_display_rules(venue_id, root, missing)
        if inherited:
            inherited = dict(inherited)
            type_counting = inherited.pop("_type_counting", None)
            snapshot = dict(snapshot)
            snapshot.update(inherited)
            if type_counting and isinstance(snapshot.get("article_types"), list):
                snapshot["article_types"] = [
                    dict(entry,
                         counting=copy.deepcopy(type_counting[str(entry.get("id"))]))
                    if (isinstance(entry, dict) and entry.get("counting") is None
                        and str(entry.get("id")) in type_counting) else entry
                    for entry in snapshot["article_types"]]
    try:
        prof = VenueProfile(snapshot, origin="recorded snapshot")
    except VenueProfileError:
        return None
    return prof if prof.id == venue_id else None


def venue_profile_base(ctx=None):
    """(profile, load error) for the root's venue, WITHOUT the recorded type.

    The article type is applied by `venue_profile_of` on top. An UNKNOWN
    recorded type must not make the venue itself look broken: the status/
    findings surfaces need the base profile so they can print the
    `set-article-type` remedy instead of "select another venue".
    """
    cfg = _ctx_cfg(ctx)
    venue_id = venue_id_of(ctx)
    root = getattr(ctx, "root", None)
    prof = _snapshot_profile(cfg, venue_id, root=root)
    if prof is not None:
        return prof, None
    try:
        return load_venue_profile(venue_id, root=root), None
    except VenueProfileError as e:
        return None, e


def venue_profile_of(ctx=None, required: bool = True):
    """The root's venue profile.

    The snapshot recorded at setup/set-venue time WINS over the files on disk:
    a root keeps enforcing the rules it was configured with even if the shipped
    profiles are edited or the profile file is deleted later. With `required`
    false the caller gets None instead of an exception, which is what `status`
    needs to report a broken configuration.

    The ARTICLE TYPE the root records is applied on top: the same venue with
    `set-article-type brief-communication` reads the Brief Communication limits,
    not the Article ones. A root that records none keeps the profile's default
    type (the pre-article-type behaviour).
    """
    prof, load_err = venue_profile_base(ctx)
    if prof is None:
        if required:
            raise load_err
        return None
    cfg = _ctx_cfg(ctx)
    wanted = str(cfg.get("article_type") or "").strip().lower()
    if not wanted or wanted == prof.article_type_id:
        return prof
    try:
        return prof.with_article_type(wanted)
    except VenueProfileError:
        if required:
            raise
        return None


def article_type_of(ctx=None) -> str:
    """The article-type id a root selects, or the profile's default."""
    prof = venue_profile_of(ctx, required=False)
    if prof is not None:
        return prof.article_type_id
    return str(_ctx_cfg(ctx).get("article_type") or "").strip().lower()


def journal_of(ctx=None) -> str:
    """The configured journal: the config's, else the profile's default, else ""."""
    cfg = _ctx_cfg(ctx)
    name = str(cfg.get("journal") or "").strip()
    if name:
        return name
    prof = venue_profile_of(ctx, required=False)
    if prof is None:
        # The venue may be fine while only the recorded ARTICLE TYPE is bad:
        # the profile's default journal is still the configured one.
        prof, _err = venue_profile_base(ctx)
    return prof.default_journal if prof is not None else ""


def venue_summary(ctx) -> str:
    """One line naming the venue, the journal and where the profile came from."""
    prof = venue_profile_of(ctx, required=False)
    venue = venue_id_of(ctx)
    journal = journal_of(ctx) or "(not set)"
    if prof is None:
        base, _err = venue_profile_base(ctx)
        if base is not None:
            return (f"venue={base.id} (\"{base.label}\", {base.describe_origin()}) -- the "
                    f"recorded article type is INVALID (run `set-article-type <id>`), "
                    f"journal={journal}")
        return (f"venue={venue or '(missing)'} (UNRESOLVED), "
                f"journal={journal}")
    return (f"venue={prof.id} (\"{prof.label}\", {prof.describe_origin()}), "
            f"article type={prof.article_type} (`{prof.article_type_id}`), "
            f"journal={journal}")


def venue_status_lines(ctx) -> list:
    """The venue/journal lines `status`, `setup` and the decision report print."""
    prof, load_err = venue_profile_base(ctx)
    venue = venue_id_of(ctx)
    journal = journal_of(ctx)
    lines = []
    if prof is None:
        lines.append(f"venue:         {venue or '(missing)'}  -- UNRESOLVED "
                     f"(run `set-venue <id>`; `set-venue --list` shows the ids)")
    else:
        type_error = None
        wanted = str(_ctx_cfg(ctx).get("article_type") or "").strip().lower()
        if wanted and wanted != prof.article_type_id:
            try:
                prof = prof.with_article_type(wanted)
            except VenueProfileError as e:
                type_error = e
        lines.append(f"venue:         {prof.id} (\"{prof.label}\", {prof.describe_origin()})")
        if type_error is not None:
            lines.append(f"article type:  {wanted!r}  -- UNRESOLVED ({type_error}); "
                         f"run `set-article-type <id>` (`set-article-type --list` shows the "
                         f"labels). The lines below describe the profile's default type "
                         f"{prof.article_type!r} until it is repaired.")
        else:
            lines.append(f"article type:  {prof.article_type} (`{prof.article_type_id}`"
                         + ("" if prof.carries_article_numbers()
                        else "; the profile carries no word limits for it, so the stages "
                             "count and name the venue's own numbers")
                     + ")")
        limits = prof.length_limits()
        if limits["abstract"].get("cap") is None and limits["main text"].get("cap") is None:
            lines.append("limits (M19):  no abstract/main-text cap in this venue profile "
                         "(counts are recorded; the target journal's own guidelines are the bar)")
        else:
            # A venue may configure only ONE of the two caps (Frontiers does):
            # interpolating the raw None printed "abstract <= None" as if it
            # were a limit.
            _caps = {k: ("no cap" if limits[k].get("cap") is None
                         else str(limits[k].get("cap")))
                     for k in ("abstract", "main text")}
            lines.append(f"limits (M19):  abstract <= {_caps['abstract']}, "
                         f"main text <= {_caps['main text']} "
                         f"({prof.length_limits_source})")
        for key, label, rules in (("tables", "tables", "FMT-TB"), ("figures", "figures",
                                                                   "FMT-FG")):
            block = prof.data.get(key) or {}
            if not _declares_display_rule(block):
                lines.append(f"{label} ({rules}): this venue profile declares no {label} rule "
                             f"(counts are reported; no placement/caption is gated)")
                continue
            bits = []
            if block.get("placement") == "end":
                bits.append(f"{label}: together at the end of the manuscript")
            elif block.get("placement") == "inline":
                bits.append(f"{label}: in the body, where cited")
            if block.get("caption") in ("before", "after"):
                bits.append(f"caption {block['caption']} the {label[:-1]}")
            elif block.get("caption") == "any":
                bits.append(f"caption side not pinned ({label[:-1]})")
            n_special = len(block.get("special") or [])
            if n_special:
                bits.append(f"{n_special} special {label[:-1]}(s) this venue exempts")
            if not bits:
                bits.append("no placement/caption pinned")
            lines.append(f"{label} ({rules}): " + "; ".join(bits)
                         + f"  ({block.get('source') or 'venue profile'})")
    missing = 'not set -- the prompts say "the target journal"; run `set-journal <name>`'
    lines.append(f"journal:       {journal or '(' + missing + ')'}")
    return lines


def venue_block(ctx) -> dict:
    """The venue/journal block decision.json and the report carry."""
    prof = venue_profile_of(ctx, required=False)
    return {"venue": venue_id_of(ctx),
            "journal": journal_of(ctx),
            "article_type": (prof.article_type if prof is not None else None),
            "article_type_id": (prof.article_type_id if prof is not None else None),
            "article_carries_numbers": (prof.carries_article_numbers()
                                        if prof is not None else None),
            "label": prof.label if prof is not None else None,
            "origin": prof.describe_origin() if prof is not None else None,
            "length_limits": prof.length_limits() if prof is not None else None,
            "caption_limit": caption_limit_of(ctx),
            "notes": list(getattr(ctx, "venue_notes", []) or []),
            "problems": list(getattr(ctx, "venue_problems", []) or []),
            "profile": prof.to_dict() if prof is not None else None}


def venue_config_findings(ctx) -> tuple:
    """(notes, problems) for a root's venue/journal configuration.

    Notes are informational and always printed; problems are fatal only under
    `--strict-venue`, except for an unresolvable venue, which the commands that
    must render a prompt refuse outright (see venue_profile_of).
    """
    notes, problems = [], []
    cfg = _ctx_cfg(ctx)
    recorded = str(cfg.get("venue") or "").strip().lower()
    if not recorded:
        notes.append(f"no venue recorded in {Path(getattr(ctx, 'cfg_path', 'pipeline_config.json')).name}: "
                     f"using the default venue {DEFAULT_VENUE!r} (the pipeline's pre-venue "
                     f"behaviour). Run `set-venue <venue>` to make it explicit.")
    prof, load_err = venue_profile_base(ctx)
    if prof is None:
        # Distinguish "no profile by that name" from "the file is there but it
        # cannot be used": the operator's next step is different.
        if load_err is not None and load_err.unknown:
            problems.append(unknown_venue_message(recorded or DEFAULT_VENUE,
                                                  getattr(ctx, "root", None)))
        elif load_err is not None:
            problems.append(f"the venue profile selected by this root cannot be used: "
                            f"{load_err}\n"
                            f"       Fix the file, or select another venue with "
                            f"`set-venue <id>` (`set-venue --list` shows the ids).")
        else:                               # pragma: no cover -- base returned a profile
            problems.append(unknown_venue_message(recorded or DEFAULT_VENUE,
                                                  getattr(ctx, "root", None)))
        return notes, problems
    # Apply the recorded article type only when it is VALID. An unknown type is
    # not a broken venue: the article-type block below names the
    # `set-article-type` remedy, while a profile that does not need that type
    # still supplies every other rule.
    _recorded_type = str(cfg.get("article_type") or "").strip().lower()
    if _recorded_type and _recorded_type in prof.article_type_ids():
        prof = prof.with_article_type(_recorded_type)
    snapshot = cfg.get("venue_profile")
    if isinstance(snapshot, dict) and str(snapshot.get("id") or "").strip().lower() != prof.id:
        problems.append(f"the recorded profile snapshot names venue "
                        f"{str(snapshot.get('id'))!r} but the config selects {prof.id!r}; "
                        f"re-run `set-venue {prof.id}` to re-record it.")
    # ---- the article type ------------------------------------------------
    recorded_type = str(cfg.get("article_type") or "").strip().lower()
    type_ids = prof.article_type_ids()
    if not recorded_type:
        notes.append(f"no article type recorded: using the venue profile's default type "
                     f"{prof.article_type!r} (`{prof.article_type_id}`). Run "
                     f"`set-article-type <id>` to make it explicit.")
    elif recorded_type not in type_ids:
        problems.append(f"unknown article type {recorded_type!r} for venue {prof.id!r}: the "
                        f"profile carries {', '.join(type_ids)}. Run "
                        f"`set-article-type <id>` (`set-article-type --list` shows the "
                        f"labels).")
    else:
        if not prof.carries_article_numbers(recorded_type):
            notes.append(f"the venue profile carries no word limits for the "
                         f"{prof._type_entry(recorded_type)['label']!r} type: every stage "
                         f"counts and names the venue's own numbers instead of borrowing "
                         f"another type's caps.")
    journal = str(cfg.get("journal") or "").strip()
    if not journal:
        journal = prof.default_journal
    if not journal:
        problems.append("no journal configured: the prompts say \"the target journal\" and the "
                        "venue's rule set still applies. Run `set-journal <name>` to name it.")
    elif not prof.journal_matches(journal):
        known = ", ".join(prof.known_journals()) or "no names, but a pattern is declared"
        problems.append(f"the journal {journal!r} is not one of the journals venue profile "
                        f"{prof.id!r} describes ({known}). Set the venue that matches the journal "
                        f"(`set-venue <id>`) or the journal the venue describes "
                        f"(`set-journal <name>`).")
    state_cfg = ((getattr(ctx, "state", None) or {}).get("config") or {})
    mirrored = str(state_cfg.get("venue") or "").strip().lower()
    if mirrored and mirrored != recorded:
        notes.append(f"state.json records venue {mirrored!r} but pipeline_config.json selects "
                     f"{recorded!r}: the config file wins (`set-venue` re-mirrors it).")
    return notes, problems

AGENT_PRESETS = {
    "claude": ["claude", "--permission-mode", "bypassPermissions", "--print"],
    # `codex exec -` is only the BASE argv: resolve_agent_cmd() splices the MCP
    # approval overrides of codex_mcp_overrides() in after the subcommand,
    # because an MCP tool call the operator is never asked about is denied
    # outright in a non-interactive session (see MCP_APPROVALS).
    "codex": ["codex", "exec", "-"],
    # The cross-judge conflict audit is a small, bounded task: its default
    # backend is the same CLI at the cheapest reasoning effort, so the audit is
    # lightweight without needing a second model configuration.
    "codex-lite": ["codex", "exec", "-c", 'model_reasoning_effort="low"', "-"],
    # The DeepSeek Harness CLI (`dsh`): `headless` is its one-shot driver, so a
    # session is non-interactive and the stage ends with the process. The task
    # is read from stdin (`-`, the delivery codex gets; `dsh` also accepts the
    # task as a positional, but PROMPT.md is far too large for argv), and
    # `--json` replaces the printed final message with a newline-delimited
    # event stream whose opening `session` line carries the persisted session
    # id a continuation adopts (`--session-id`, see resume_argv_for). The
    # harness's own home ($DSH_HOME, default ~/.dsh) owns the model, the
    # DEEPSEEK_API_KEY credential and its MCP servers, exactly as the codex
    # profile owns the codex CLI's, so this preset carries no overrides the way
    # the codex one does.
    "dsh": ["dsh", "--profile", "headless", "--json", "-"],
    # Qwen3.8-27B through an OpenAI-compatible vLLM endpoint (the SSH-tunnel
    # route documented in `paper_qwen_agent.py`). The adapter is a thin
    # provider-config layer around the harness the operator already uses:
    # PAPER_QWEN_HARNESS=codex (default) or dsh. It starts the tunnel only when
    # the endpoint is not already reachable, and a `chat` mode is available for
    # text-only jobs. The model's provider/model/base-url are environment
    # settings (PAPER_QWEN_*; see the adapter's docstring), not pipeline
    # config: the endpoint is deployment-specific, never manuscript content.
    # The adapter is its own executable (shebang `#!/usr/bin/env python3`), not
    # `[sys.executable, path]`: `AGENT_PRESET_BINARIES` is then the adapter's
    # name, and a plain `python3 stub_agent.py` passed through --agent-cmd still
    # does not look like a shipped preset (the dsh suite checks that).
    "qwen": [str(Path(__file__).resolve().with_name("paper_qwen_agent.py"))],
}
# The backends an operator may select BY NAME (each maps to a shipped argv;
# `manual` is the no-CLI mode) -- one list, so every --agent/--judge-agent
# parser accepts the same set. A custom --agent-cmd/PAPER_AGENT_CMD stays the
# last route and is never named here.
AGENT_CHOICES = ("codex", "claude", "dsh", "qwen", "manual")
# The CLI each preset launches (`codex`, `claude`, `dsh`). Derived from the
# preset table itself, so the checks that ask "is this the operator's real
# agent CLI, or a test stub / foreign tool?" (see `_looks_like_preset_cmd`) and
# that ask "was this preset's binary not installed?" (see `agent_install_hint`)
# recognise a preset added above without a second list to keep in step.
AGENT_PRESET_BINARIES = frozenset(os.path.basename(str(argv[0])).lower()
                                  for argv in AGENT_PRESETS.values() if argv)
# Choices for --conflict-agent (the audit is lightweight by default).
CONFLICT_AGENT_CHOICES = ("codex-lite", *AGENT_CHOICES)

MARKER_FILE = "_pipeline_done.json"
SCORES_FILE = "scores.json"
PROMPT_FILE = "PROMPT.md"
PIN_DIRNAME = "pinned"
LOCK_FILE = "_pipeline.lock"
LOGS_DIRNAME = "_logs"
# EVERY attempt is kept, not just the last one. The run record's `postcheck`
# and `last_error` always describe the FINAL attempt (a retry overwrites them),
# so a run that failed twice used to leave the operator with one failure and no
# way back to the first one's diagnostics or artifacts -- the 2026-09-22 root
# showed "attempt 2" failing on the M1b gate while attempt 1's real problems
# (101 OUTLINE rows with no summary) existed only inside attempt 2's PROMPT.md.
# `attempts_log` in state.json is the machine-readable history;
# `runs/<run>_try<N>_failed/` keeps that attempt's own sandbox (renamed before the
# retry builds a fresh one -- deliverables, transcript and a record.json).
# A failed attempt's WHOLE sandbox is renamed to `runs/<run>_try<N>_failed/` before
# the retry builds a fresh one at `runs/<run>/` -- the operator asked for exactly
# that shape, and it keeps everything (deliverables as the postcheck judged them,
# the transcript, the seeded tables, the corpus copies and a record.json) without
# a second copy of the artifacts.
FAILED_SUFFIX_FMT = "_try{n}_failed"
# A pathological retry loop must not grow state.json without bound: the log keeps
# the last N attempts, each with its messages capped. The archived sandbox keeps
# the full evidence, and `prune` reclaims it with the round it belongs to.
ATTEMPTS_LOG_LIMIT = 25
ATTEMPT_MESSAGE_LIMIT = 4000
# EVERY message of an attempt is kept: the operator asked for the complete
# errors/warnings of the first attempt, the first retry, the second retry, ...
# and a capped list is exactly how attempt 1's two other problems disappeared on
# the 2026-09-22 root. The only guard left is a total BYTES cap per attempt (a
# runaway postcheck could otherwise write megabytes into state.json): when it
# triggers, the note says how many messages were left out, and the attempt's
# archived `record.json`, its transcript and the run log still carry them.
ATTEMPT_LIST_BYTES_LIMIT = 512 * 1024

# ---- the two INPUT areas, under their canonical names -----------------------
# Both were renamed to this repo's snake_case convention, for meaning as much as
# for style:
#   * `non_revised/` is the root's pristine copy of `--source` (the old spelling
#     `non-revised/` reads like a pipeline OUTPUT -- it is not, it is the
#     untouched original);
#   * `raw_data/` is the corpus's raw-data directory: figure/table sources, data
#     tables and the analysis snapshot that the author's own build scripts
#     regenerate.
# The canonical names are the ONLY names: `non-revised/` and `raw_figs/` are not
# resolved, created or accepted anywhere (no backward-compatibility aliases).
PRISTINE_DIR = "non_revised"
PRISTINE_DIRNAMES = (PRISTINE_DIR,)
RAW_DATA_DIR = "raw_data"
RAW_DATA_DIRNAMES = (RAW_DATA_DIR,)
# The human editors'/reviewers' feedback of a REAL submission lives in its own
# top-level area, a sibling of raw_data/: it is the authors' INPUT (never
# submitted, never manuscript text), it drives the concern reconciliation and
# the response letter, and a judge may read it to score how well a version
# ADDRESSES the human-raised concerns. Both areas together are the corpus's
# EVIDENCE areas (see is_evidence_rel / the judge-view layout).
HUMAN_FEEDBACK_DIR = "human_review_feedback"
# A corpus may ALSO carry a machine-generated review of the previous submission
# in its own top-level area (a sibling of human_review_feedback/). It follows
# the SAME evidence contract -- read-only, never submission text, staged into
# the journal feedback/concerns sessions and shown to judges under evidence/ --
# with one semantic difference: its false-positive findings were filtered out
# upstream, so every remaining finding is a real concern the stages must answer
# (never dismissed merely because a model wrote it, and never silently dropped).
LLM_FEEDBACK_DIR = "llm_review_feedback"
REVIEW_FEEDBACK_DIRS = (HUMAN_FEEDBACK_DIR, LLM_FEEDBACK_DIR)
# A corpus may keep the manuscript version the PREVIOUS journal's editors/
# reviewers actually saw inside the feedback area, under this fixed child name.
# It is EVIDENCE, not the current submission: it never feeds feedback discovery,
# sweeps, counts or corpus identity, and the stages may only use it to
# understand what a raised concern refers to and whether the CURRENT base
# already answers it.
ORIGINAL_SUBMISSION_DIRNAME = "original_submission"
EVIDENCE_DIRNAMES = RAW_DATA_DIRNAMES + REVIEW_FEEDBACK_DIRS
# An evidence area the operator renamed to `<area>.disabled` (or `.off`) is
# INERT: it is not read as evidence or feedback and it is not part of the
# submission either -- the rename is the documented off-switch, so its files
# must never leak into the corpus, a judge view or a published package.
DISABLED_EVIDENCE_SUFFIXES = ("disabled", "off")
# The stable root the judge view uses to expose the evidence areas (their files
# stay anonymized inside it; see _view_layout).
EVIDENCE_VIEW_ROOT = "evidence"


LEGACY_INPUT_AREA_NAMES = (("non-revised", PRISTINE_DIR), ("raw_figs", RAW_DATA_DIR))


def legacy_input_area_problems(dirp) -> list:
    """Legacy input-area spellings are a hard error, never silently resolved.

    The pipeline has ONE name per input area. A tree carrying `non-revised/` or
    `raw_figs/` is not migrated (that would be backward compatibility) and is
    not read as evidence (that could submit or overwrite the wrong directory):
    the operator renames it once, deliberately.
    """
    out = []
    for legacy, canonical in LEGACY_INPUT_AREA_NAMES:
        if (Path(dirp) / legacy).exists():
            out.append(f"{legacy}/ is the removed legacy spelling of {canonical}/; rename it "
                       f"(this pipeline no longer resolves aliases)")
    return out


def pristine_dirname(dirp: Path) -> str:
    """The name `dirp` uses for its pristine copy of the original submission."""
    return PRISTINE_DIR


def raw_data_dirname(dirp: Path) -> str:
    """The name `dirp` uses for the corpus's read-only raw-data directory."""
    return RAW_DATA_DIR


def area_dir(sb: Path, area: str) -> Path:
    """The directory a recorded input-area key names inside a sandbox."""
    return sb / area


def norm_raw_data_name(rel: str) -> str:
    """A corpus-relative path with forward slashes (no legacy-name mapping)."""
    return rel.replace("\\", "/")


def without_raw_data(m: dict) -> dict:
    """A corpus manifest with the READ-ONLY raw-data area left out.

    Used to compare a published winner with its pin: the raw-data area is an
    INPUT (byte-verified against the pristine copy), not content the stage wrote,
    so a normalised copy of it must not read as "the champion changed".
    """
    files = {k: v for k, v in (m or {}).get("files", {}).items() if not is_evidence_rel(k)}
    return {"files": files, "count": len(files)}

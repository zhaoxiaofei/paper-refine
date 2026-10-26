# -*- coding: utf-8 -*-
# Part 02/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# JOURNAL REVISION MODES (options 1-4)
#
# A root can be driven against a REAL journal decision letter instead of the
# pipeline's own from-scratch review. Four modes, one per operator workflow:
#
#   1 transfer  revise for a NEW journal (e.g. read iScience, submit to
#               Frontiers in Immunology). NO response to reviewers. Rewrites
#               allowed (a new journal is a new submission).
#   2 resubmit  revise for a NEW submission to the SAME journal. Response to
#               reviewers REQUIRED. Rewrites allowed.
#   3 major     complete a MAJOR revision at the same journal. Response to
#               reviewers REQUIRED. Rewrites NOT allowed and the manuscript is
#               revised ONLY to address the raised concerns: every change must
#               be traceable to a concern, so the general review-audit-revise
#               workflow does not run.
#   4 minor     as 3, for a MINOR revision.
#
# The default (unset) mode is "continue": the historical pipeline is entered
# exactly as before, and every journal-specific code path below runs only when
# `journal_mode_of(ctx)` is one of the explicit journal modes. `none` is not a
# mode any more and is refused rather than silently treated as `continue`.
# =====================================================================

JOURNAL_MODE_TRANSFER = "transfer"
JOURNAL_MODE_RESUBMIT = "resubmit"
JOURNAL_MODE_MAJOR = "major"
JOURNAL_MODE_MINOR = "minor"
# The LLM-review mode: the round is revised against the false-positive-filtered
# `llm_review_feedback/` area ONLY (no journal decision letter). It is selected
# explicitly; the directory's presence never changes an unconfigured root.
# Renaming it to `llm_review_feedback.disabled` keeps the tree inert.
JOURNAL_MODE_LLM = "llm"
JOURNAL_MODE_CONTINUE = "continue"
JOURNAL_MODE_INIT = "init"

JOURNAL_MODES = {
    JOURNAL_MODE_CONTINUE: {
        "option": 0,
        "label": "the pipeline's own review/revise rounds (no journal feedback)",
        "feedback": False, "response": False, "rewrites": True, "scoped": False,
        "streams": (),
    },
    JOURNAL_MODE_INIT: {
        # `init` starts a NEW submission: the conform (template-first) stage runs
        # before round 1 exactly like transfer's, but there is no decision letter
        # anywhere in the chain -- no feedback/concerns stage, no response letter,
        # no journal submission package. Everything after the conform stage is the
        # historical `continue` workflow.
        "option": 0,
        "label": "init: conform the submission first -- inside the venue's own Word template "
                 "when one ships, else to the journal's author guidelines and academic "
                 "convention -- then run the pipeline's own review/revise rounds; no journal "
                 "feedback",
        "feedback": False, "response": False, "rewrites": True, "scoped": False,
        "streams": (),
    },
    JOURNAL_MODE_TRANSFER: {
        "option": 1,
        "label": "transfer: revise for a NEW journal from another journal's feedback; "
                 "no response to reviewers",
        "feedback": True, "response": False, "rewrites": True, "scoped": False,
        "streams": ("human", "llm"),
    },
    JOURNAL_MODE_RESUBMIT: {
        "option": 2,
        "label": "resubmit: revise for a new submission to the SAME journal; "
                 "response to reviewers required",
        "feedback": True, "response": True, "rewrites": True, "scoped": False,
        "streams": ("human", "llm"),
    },
    JOURNAL_MODE_MAJOR: {
        "option": 3,
        "label": "major revision: concern-scoped edits only at the same journal; "
                 "response to reviewers required; no rewrites",
        "feedback": True, "response": True, "rewrites": False, "scoped": True,
        "streams": ("human", "llm"),
    },
    JOURNAL_MODE_MINOR: {
        "option": 4,
        "label": "minor revision: concern-scoped edits only at the same journal; "
                 "response to reviewers required; no rewrites",
        "feedback": True, "response": True, "rewrites": False, "scoped": True,
        "streams": ("human", "llm"),
    },
    JOURNAL_MODE_LLM: {
        "option": 5,
        "label": "llm: revise against the false-positive-filtered LLM review only "
                 "(llm_review_feedback/); no journal decision letter and no response letter",
        "feedback": True, "response": False, "rewrites": True, "scoped": False,
        "streams": ("llm",),
    },
}

# The boundary assertions are CASE-SENSITIVE even though the words they
# surround are matched case-insensitively: a lower->UPPER camelCase junction is
# a word boundary (`ReviewersComments.docx`), while a following lowercase
# letter is not (`biofeedback`).
_FB_WORD_START = r"(?-i:(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z])))"
_FB_WORD_END = r"(?-i:(?:(?![A-Za-z])|(?<=[a-z])(?=[A-Z])))"

JOURNAL_FEEDBACK_NAME_RE = re.compile(
    # WORD-anchored: `biofeedback`, `genome_editor` and `base_editor_results`
    # are not the journal's letter. An `editor(s)` name must carry a document
    # role (`editor_comments`, `EditorComments`, `editor_decision`, ...).
    _FB_WORD_START + r"(?:feedback|referees?|reviewers?)" + _FB_WORD_END
    + r"|" + _FB_WORD_START + r"editors?(?:[-_ ]|(?-i:(?=[A-Z])))"
    r"(?:comments?|decisions?|reports?|letters?|notices?|emails?|critiques?|forms?)"
    + _FB_WORD_END
    + r"|" + _FB_WORD_START + r"editorial" + _FB_WORD_END
    + r"|" + _FB_WORD_START + r"decision[_ \-]*(?:letter|notice|email)" + _FB_WORD_END,
    re.I)
# ... but the venue's OWN article-type vocabulary collides with those words: the
# shipped example profile's `letter-to-the-editor` and the Frontiers profile's
# `editorial` are MANUSCRIPTS the authors wrote. A name that IS such a type
# (optionally with a version token) is never the journal's feedback, wherever
# it sits -- the same reason a "cover"-spelled letter is carved out below.
ARTICLE_TYPE_MANUSCRIPT_NAME_RE = re.compile(
    r"^(?:letter[\s_-]+(?:to|for)[\s_-]+the[\s_-]+editor|editorial)"
    r"(?:[\s_-]+(?:v|rev|version|revision|draft)?[\s_-]*\d{1,3})?$", re.I)


def is_journal_feedback_name(name) -> bool:
    """Does this file NAME advertise the journal's own feedback/decision letter?

    A name that IS one of the venue article types the authors write
    (`letter-to-the-editor`, `editorial`) is their MANUSCRIPT, never the
    editors' letter, wherever it sits.
    """
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    # Strip ALL extension layers: `letter_to_the_editor.docx.txt` is the same
    # article-type manuscript as `letter_to_the_editor.docx`.
    stem = Path(base).stem
    while True:
        _stripped = re.sub(r"\.(?:txt|docx?|md|tex|pdf|rtf|csv|tsv|bak|final|tar|gz|zip)$",
                           "", stem, flags=re.I)
        if _stripped == stem:
            break
        stem = _stripped
    if ARTICLE_TYPE_MANUSCRIPT_NAME_RE.match(stem):
        return False
    return bool(JOURNAL_FEEDBACK_NAME_RE.search(base))


# A file the AUTHORS wrote ("response_to_reviewers.docx", "rebuttal.md",
# "point-by-point.docx", or a "cover_letter_to_editor.docx") is a submission
# document, not the journal's feedback: the auto-detection must never read one
# as the letter (the cover letter is the common trap -- "editor" is in its name).
JOURNAL_AUTHORED_REPLY_RE = re.compile(
    r"response|repl(?:y|ies)|rebuttal|point[-_ ]?by[-_ ]?point"
    r"|(?-i:(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))(?:[Cc]over|COVER)(?![a-z]))"
    r"|(?<![A-Za-z])coverletter", re.I)
# The WORD "cover" (or the camelCase "coverLetter"/"plainLetter", or the
# concatenated `coverletter`), never the substring: a bare `cover` also matched
# `discovery.md`, `coverage_table.txt` and `recovered_notes.tex`, which then read
# as the letter (or hid a reply whose name merely contains the substring). A
# word starts at the string's start, after a non-letter, or at a lower->UPPER
# camelCase boundary, and ends at a non-lowercase character.
_COVER_WORD_RE = re.compile(
    r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
    r"(?:[Cc]over|COVER|(?i:coverletter|plainletter))(?![a-z])")
# The reply-only spelling for the written-surface scans: a cover letter IS a
# submission document (M19 counts it as one), a response-to-reviewers is not
# manuscript prose.
AUTHORED_REPLY_NAME_RE = re.compile(
    r"response|repl(?:y|ies)|rebuttal|point[-_ ]?by[-_ ]?point", re.I)
JOURNAL_CONCERN_ACTIONS = ("text", "analysis", "new-experiment", "clarification",
                           "formatting", "policy", "disagree")
JOURNAL_CONCERN_DISPOSITIONS = ("to-fix", "already-addressed", "manual", "not-applicable")
JOURNAL_CONCERNS_MD_REL = "concerns/JF_concerns.md"
JOURNAL_CONCERNS_JSON_REL = "concerns/JF_concerns.json"
JOURNAL_RESPONSE_MD_REL = "response/RESPONSE_TO_REVIEWERS.md"
JOURNAL_RESPONSE_MAP_REL = "response/response_map.json"
JOURNAL_SUBMISSION_DIR = "journal_submission"

# The analysis-code area (`code/`) is revision CONTENT, like the documents: a
# stage may revise it (rule C), the judges evaluate it, and a corpus, a pin and
# a winner carry it. It is NOT part of the SUBMISSION by default -- the
# submission copy strips it exactly like the evidence areas, and no
# to-be-submitted file may refer into it. `setup --submit-code on` (or
# `set-submit-code on` on an existing root) submits it instead: the copy then
# carries `code/`, and a response letter may cite a code file like any other.
SUBMIT_CODE_MODES = ("on", "off")
DEFAULT_SUBMIT_CODE = "off"


def normalize_revision_mode(value=None) -> str:
    """The canonical revision-mode name for a configured/passed value.

    The default is `continue` (the pipeline's own review/revise rounds). No
    alias spellings are accepted: a mode is one of JOURNAL_MODES' keys.
    """
    return str(value or JOURNAL_MODE_CONTINUE).strip().lower()


def journal_mode_of(ctx=None) -> str:
    """The configured journal revision mode ('continue' when unset).

    Reads `revision_mode` from pipeline_config.json (mirrored into state.json
    as `config`). An unknown value is an error, not a silent 'continue': a typo
    in the mode would otherwise silently run the wrong workflow.

    When NO mode is recorded, the historical review/revise path is used. A
    directory that happens to contain `llm_review_feedback/` does not opt the
    root into a journal mode: that would make the no-journal-mode path depend
    on an input area. Select `llm` explicitly to use that area.
    """
    cfg = (getattr(ctx, "cfg", None) if ctx is not None else None) or {}
    raw = str(cfg.get("revision_mode") or "").strip()
    if not raw:
        return JOURNAL_MODE_CONTINUE
    mode = normalize_revision_mode(raw)
    if mode not in JOURNAL_MODES:
        die(f"pipeline_config.json records revision_mode {mode!r}, which is not one of "
            f"{', '.join(JOURNAL_MODES)}. Fix it with `set-revision-mode <mode>` or start a "
            f"fresh root.")
    return mode


def llm_feedback_present_in(dirp) -> bool:
    """True when `dirp` carries a NON-EMPTY llm_review_feedback/ area.

    A directory with no file anywhere inside it does not trigger the mode; a
    renamed (`llm_review_feedback.disabled`) or moved area never does either --
    only the canonical name counts.
    """
    if dirp is None:
        return False
    try:
        area = Path(dirp) / LLM_FEEDBACK_DIR
        if not area.is_dir():
            return False
        return any(p.is_file() and not is_bookkeeping_name(p.name) for p in area.rglob("*"))
    except OSError:
        return False


def journal_feedback_streams(ctx=None) -> tuple:
    """Which review-feedback streams the effective mode consumes."""
    return tuple(JOURNAL_MODES.get(journal_mode_of(ctx), {}).get("streams") or ())


def journal_mode_info(ctx=None) -> dict:
    return JOURNAL_MODES[journal_mode_of(ctx)]


def journal_is_scoped(ctx=None) -> bool:
    """True for the major/minor modes: concern-scoped edits only."""
    return bool(journal_mode_info(ctx).get("scoped"))


def journal_needs_response(ctx=None) -> bool:
    """True when a response-to-reviewers document is a required deliverable."""
    return bool(journal_mode_info(ctx).get("response"))


def submit_code_of(ctx=None) -> bool:
    """Whether the analysis-code area is part of the submission.

    `submit_code` is recorded at setup (`on`/`off`) and flipped on an existing
    root with `set-submit-code`. A root without the key -- every root created
    before this policy existed -- behaves as `off`: `code/` is revision content
    whose files a stage may revise and the judges evaluate, but the submission
    copy strips it, and a to-be-submitted file may not refer into it.
    """
    raw = ((getattr(ctx, "cfg", None) if ctx is not None else None) or {}).get("submit_code")
    if isinstance(raw, bool):
        # A hand-edited config that carries the JSON boolean, not the string.
        return raw
    return str(raw or "").strip().lower() in ("on", "true", "yes", "1")


def submission_not_carried_areas(ctx) -> list:
    """The area names a submission built from this root does NOT carry (PKG-2).

    ONE definition of "what a submission leaves out", shared by the journal
    assembly (which derives it from the copy it just stripped), the published
    package's own scan and the code-side evidence pack, so the three can never
    disagree about whether a `code/` pointer dangles: the evidence areas never
    ship, and the analysis code ships only under `submit_code: on`.
    """
    areas = [str(n) for n in EVIDENCE_DIRNAMES]
    if not submit_code_of(ctx):
        areas.append(CODE_DIR)
    return areas


def journal_has_feedback(ctx=None) -> bool:
    """True when the mode consumes an editors'/reviewers' decision letter.

    `continue` and `init` do not: no feedback/concerns
    stage, no journal block in any prompt, no response letter. The conform stage
    of `init` runs regardless -- it fills the venue's template, it does not read
    a letter.
    """
    return bool(journal_mode_info(ctx).get("feedback"))


def journal_rewrites_allowed(ctx=None) -> bool:
    """False for the major/minor modes: the manuscript may not be rewritten."""
    return bool(journal_mode_info(ctx).get("rewrites"))


def journal_feedback_paths(ctx: Ctx) -> list:
    """The operator-named feedback files, resolved (absolute paths)."""
    out = []
    raw = (ctx.cfg or {}).get("journal_feedback") or []
    if isinstance(raw, str):
        raw = [raw]
    for item in raw:
        s = str(item or "").strip()
        if not s:
            continue
        p = Path(s)
        if not p.is_absolute():
            # Root-relative first (the documented spelling), then CWD-relative:
            # an operator who typed the path from their shell should not have to
            # discover the difference.
            root_rel = ctx.root / p
            p = root_rel if root_rel.exists() else (Path.cwd() / p)
        out.append(p)
    return out


def journal_feedback_files(ctx: Ctx) -> list:
    """[(absolute path, label)] of the feedback this root revises against.

    Precedence:
      1. operator-named files (`setup --journal-feedback`), which win outright;
      2. every file in the corpus's `human_review_feedback/` area that is not an
         authored reply (the area exists for exactly this content, so it needs
         no name heuristic -- a Chinese-named or generically named report works);
      3. the legacy name heuristic over the whole corpus (`feedback`/`referee`/
         `reviewer`/`editor`, or a `decision`-letter/notice/email name), which
         keeps the earlier design working when the letter lives in `raw_data/`.
         A bare `decision.pdf` is not in this heuristic; name it
         `decision-letter.pdf` or pass it with `setup --journal-feedback`.
    A file the AUTHORS wrote (`response_to_reviewers.docx`, `cover_letter_to_
    editor.docx`, `point-by-point.md`) is never read as the journal's letter.

    This is the HUMAN/decision-letter stream only. A sibling
    `llm_review_feedback/` area (false positives pre-filtered) is resolved by
    `journal_llm_feedback_files` and merged with this one by the feedback/
    concerns sessions, which keeps each finding's provenance explicit.
    """
    streams = journal_feedback_streams(ctx)
    if streams and "human" not in streams:
        # `llm` mode reads ONLY the LLM review: a human letter in the corpus is
        # not a concern source here (it stays evidence for the judges).
        return []
    named = journal_feedback_paths(ctx)
    if named:
        out, seen = [], set()
        for p in named:
            if not p.is_file():
                die(f"--journal-feedback {p} does not exist (or is not a file). Give the "
                    f"decision letter / reviewer report(s) explicitly, or drop the flag and let "
                    f"the pipeline find them in the corpus's human_review_feedback/ area.")
            label = p.name
            if label in seen:
                # Two operator-named reports from different directories: a
                # basename-only label staged one over the other, and the ledger
                # then quoted only the survivor.
                label = (f"{p.stem}-"
                         f"{hashlib.sha1(str(p.resolve()).encode('utf-8')).hexdigest()[:8]}"
                         f"{p.suffix}")
            seen.add(label)
            out.append((p, label))
        return out
    if not ctx.pristine.is_dir():
        return []
    area = human_feedback_files_in(ctx.pristine)
    feedback = [(p, label) for p, label in area
                if not JOURNAL_AUTHORED_REPLY_RE.search(p.name)]
    if feedback:
        return feedback
    found = []
    for p in sorted(ctx.pristine.rglob("*")):
        if not p.is_file() or is_bookkeeping_name(p.name):
            continue
        rel = p.relative_to(ctx.pristine).as_posix()
        if is_original_submission_rel(rel):
            continue
        if evidence_area_of(rel) == LLM_FEEDBACK_DIR:
            # The LLM review is its own stream (`journal_llm_feedback_files`),
            # never swept up by the decision-letter name heuristic: a
            # "reviewer_report.md" inside llm_review_feedback/ must not be
            # relabelled as a human letter.
            continue
        if is_journal_feedback_name(p.name) \
                and not JOURNAL_AUTHORED_REPLY_RE.search(p.name):
            found.append((p, rel))
    return found


def is_original_submission_rel(rel: str) -> bool:
    """True for a corpus-relative path inside `human_review_feedback/original_submission/`.

    The child directory holds the manuscript version the previous journal's
    editors/reviewers saw. It is EVIDENCE: it must never be enumerated as a
    feedback document (the area's files otherwise need no name heuristic), never
    seeded as a concern and never counted as the current submission's text.
    """
    parts = str(rel or "").replace("\\", "/").lstrip("/").split("/")
    return (len(parts) >= 2 and parts[0] == HUMAN_FEEDBACK_DIR
            and parts[1] == ORIGINAL_SUBMISSION_DIRNAME)


def human_original_submission_dirs(dirp: Path) -> list:
    """[(path, label)] of the reviewer-visible submission copies in `dirp`.

    The layout is fixed: `<corpus>/human_review_feedback/original_submission/`.
    More than one corpus can contribute to one root only for named feedback
    files, so at most one entry exists in practice; returning a list keeps the
    staging code honest when a future layout nests several.
    """
    area = Path(dirp) / HUMAN_FEEDBACK_DIR
    out = []
    if not area.is_dir():
        return out
    for child in sorted(area.iterdir()):
        if child.is_dir() and child.name == ORIGINAL_SUBMISSION_DIRNAME:
            out.append((child, f"{HUMAN_FEEDBACK_DIR}/{ORIGINAL_SUBMISSION_DIRNAME}"))
    return out


def review_feedback_files_in(dirp: Path, area_name: str) -> list:
    """[(path, corpus-relative label)] of every FEEDBACK FILE in one area.

    `human_review_feedback/original_submission/` is deliberately excluded: it is
    a manuscript, not a letter or a response. Treating its files as feedback
    would seed the concern ledger from the manuscript itself. The LLM area has
    no such child.
    """
    area = Path(dirp) / area_name
    out = []
    if not area.is_dir():
        return out
    for p in sorted(area.rglob("*")):
        if not p.is_file() or is_bookkeeping_name(p.name):
            continue
        label = p.relative_to(Path(dirp)).as_posix()
        if area_name == HUMAN_FEEDBACK_DIR and is_original_submission_rel(label):
            continue
        out.append((p, label))
    return out


def human_feedback_files_in(dirp: Path) -> list:
    """[(path, label)] of the human editors'/reviewers' feedback files."""
    return review_feedback_files_in(dirp, HUMAN_FEEDBACK_DIR)


def llm_feedback_files_in(dirp: Path) -> list:
    """[(path, label)] of the (false-positive-filtered) LLM review files."""
    return review_feedback_files_in(dirp, LLM_FEEDBACK_DIR)


def journal_llm_feedback_files(ctx: Ctx) -> list:
    """[(absolute path, label)] of the LLM review feedback of this root.

    The LLM stream is kept SEPARATE from `journal_feedback_files` (the human
    decision letter / referee reports): the journal stages consume both, but the
    provenance, the prompt wording and the ledger's `author` column must never
    blur them. Unlike the human area there is no name heuristic and no
    previous-response or `original_submission/` machinery: the area IS the
    feedback.
    """
    streams = journal_feedback_streams(ctx)
    if streams and "llm" not in streams:
        return []
    if not ctx.pristine.is_dir():
        return []
    return llm_feedback_files_in(ctx.pristine)


def journal_previous_responses(ctx: Ctx) -> list:
    """[(path, label)] of authored replies found beside the human feedback.

    A previous response-to-reviewers document is CONTEXT (what was promised),
    never a concern source and never the journal's letter. It is listed to the
    session so it can keep the new response consistent with the old one.
    """
    if not ctx.pristine.is_dir():
        return []
    # `_COVER_WORD_RE` is the module's already-correct word matcher; a local
    # copy compiled with re.I made its camel-case lookarounds match ANY letter
    # pair, so `uncover_response.docx` was mistaken for a cover letter.
    return [(p, label) for p, label in human_feedback_files_in(ctx.pristine)
            if JOURNAL_AUTHORED_REPLY_RE.search(p.name)
            and not _COVER_WORD_RE.search(p.name)]


def feedback_text_of(path: Path) -> tuple:
    """(text, note) for one feedback file -- the reviewable rendering."""
    ext = path.suffix.lower()
    if ext in (".txt", ".md", ".markdown", ".rst", ".tex", ".bib", ".csv", ".tsv"):
        try:
            return path.read_text(encoding="utf-8", errors="replace"), ""
        except OSError as e:
            return "", f"unreadable: {e}"
    if ext == ".docx":
        paras = _docx_paragraphs(path)
        if paras is None:
            return "", "docx-unreadable"
        return "\n".join(paras), ""
    if ext == ".pdf":
        if shutil.which("pdftotext"):
            try:
                proc = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                                      capture_output=True, timeout=60)
                text = proc.stdout.decode("utf-8", errors="replace")
                if text.strip():
                    return text, ""
                return "", "pdftotext produced no text (scanned/image PDF?)"
            except Exception as e:                                   # noqa: BLE001
                return "", f"pdftotext failed: {e}"
        return "", "pdf-unconvertible: pdftotext not available"
    return "", f"unparseable extension {ext!r} (the original is still copied for the session)"


def seed_concern_candidates(text: str) -> list:
    """Code-side candidate split of a decision letter / reviewer report.

    Not the deliverable: a SEED the session refines. Splits at reviewer/editor
    headings and numbered-point markers; a document with none falls back to
    blank-line paragraphs. Bounded (200 rows, 400 chars each) so a runaway
    letter cannot flood the prompt.
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    starts = []
    # The word alternatives keep their trailing `\b` (so "editorial" does not
    # start a block); the marker alternatives must NOT carry it: `\b` can never
    # match after "." / ")" / "-" when a space follows, so "1. Comment" and
    # "- Item" never split (only the unusual "1.Comment" did), and the
    # docstring's "numbered-point markers" were dead.
    head_re = re.compile(
        r"^\s*(?:(?:reviewer|referee|editor|comments?|major|minor)\b|"
        r"point\b(?=\s*(?:\d|[:.]))|"
        r"\d+\s*[.)](?=\s|$)|[-*•]\s+)", re.I)
    for i, ln in enumerate(lines):
        if head_re.match(ln):
            starts.append(i)
    rows = []
    if starts:
        bounds = starts + [len(lines)]
        for a, b in zip(bounds, bounds[1:]):
            block = " ".join(x.strip() for x in lines[a:b] if x.strip())
            if block:
                rows.append({"heading": lines[a].strip()[:160], "excerpt": block[:400]})
    else:
        for para in re.split(r"\n\s*\n", "\n".join(lines)):
            block = " ".join(para.split())
            if block:
                rows.append({"heading": block[:80], "excerpt": block[:400]})
    return rows[:200]


def journal_concern_ledger(sandbox: Path) -> dict:
    """The concern ledger a feedback/concerns run wrote ({} when absent)."""
    data = read_json(sandbox / JOURNAL_CONCERNS_JSON_REL, revive=False, lenient=True)
    return data if isinstance(data, dict) else {}


def journal_concern_rows(sandbox: Path) -> list:
    rows = (journal_concern_ledger(sandbox) or {}).get("concerns")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


# The archive excludes the re-derivable INPUT corpora: every materialization
# rewrites them from hash-verified sources, and copying them would multiply a
# 180 MB sandbox by every retry. What is preserved is what the ATTEMPT produced,
# plus the prompt it answered and the bookkeeping the postcheck read.
ATTEMPT_ARCHIVE_SKIP_DIRS = ("base", "self", "others", "target", "field", "original",
                             *PRISTINE_DIRNAMES)
ATTEMPT_ARCHIVE_SKIP_SUBTREES = (("work", "corpus"),)
SUPERSEDED_DIRNAME = "_superseded"
# Python bytecode caches (`__pycache__/*.pyc`) are a side effect of RUNNING the
# helper scripts the pipeline seeds into a sandbox -- never a deliverable. The
# repair-scope guard reads them as "the session wrote outside its scope" unless
# they are filtered out (r1_i3, 2026-09-22: a repair that had cleared every
# problem it was given was failed for `__pycache__/paper_docx_format.*.pyc`).
BYTECODE_DIRNAME = "__pycache__"
BYTECODE_SUFFIXES = (".pyc", ".pyo")


def is_bytecode_cache(rel) -> bool:
    """Is this sandbox-relative path a Python bytecode cache (never a deliverable)?"""
    parts = tuple(x for x in Path(str(rel)).parts if x and x != ".")
    return BYTECODE_DIRNAME in parts or str(rel).endswith(BYTECODE_SUFFIXES)
# `setup` writes this into the root it is building and removes it once
# state.json exists, so a setup that died part-way (a transient I/O error while
# hashing or scanning the fresh copy) can be re-run on the SAME root instead of
# leaving a half-built directory the operator must delete by hand.
SETUP_MARKER = "_setup_in_progress"

# The winner of every round is published, in addition to the content-addressed
# pin, into its own directory directly under --root: <root>/round<R>_winner/.
WINNER_DIR_FMT = "round{r}_winner"
# `decide` also publishes the final champion as a clean, self-contained corpus
# that can seed a NEW pipeline run, named after the root directory that hosts
# it: <root>/final_clean_version_<root directory name>/. It is the winner
# corpus byte-for-byte (no process scratch, no auxiliaries, no self-written
# reports), so `setup --source <root>/final_clean_version_<root directory
# name>` starts from exactly the content the judges scored. It is generated on
# EVERY decide, certified or not; the verdict and the package's provenance live
# in the SIBLING <root>/final_clean_version.readme.md. Nothing is written
# INSIDE it: an added README/manifest would become manuscript content for the
# next round. The same tree is also compressed into the SIBLING
# <root>/final_clean_version_<root directory name>.zip; the directory is KEPT.
FINAL_CLEAN_DIRNAME = "final_clean_version"
# The SIBLING status file: the directory itself stays a byte-clean manuscript
# corpus (anything inside it would become manuscript content in the next run),
# so the certification verdict and the package's provenance live beside it.
FINAL_CLEAN_README_NAME = FINAL_CLEAN_DIRNAME + ".readme.md"
FINAL_CLEAN_AUTHOR_README_NAME = FINAL_CLEAN_DIRNAME + ".author_to_complete.md"


def final_clean_dirname(root: Path) -> str:
    """The published package's directory name: `final_clean_version_<root name>`."""
    return f"{FINAL_CLEAN_DIRNAME}_{Path(root).resolve().name}"


# Companion module for the code-side OOXML style/formatting scan (see
# scan_format_in_sources). `setup` copies it next to the pipeline script so the
# root stays self-contained; when it is absent the scan reports "unavailable"
# instead of failing the run.
DOCX_FORMAT_MODULE = "paper_docx_format.py"
# `setup --format-fix`: normalize the mechanical OOXML formatting defects of the
# pristine copy (and, later, of every stage package) before anything is
# fingerprinted/judged. `off` keeps the copy byte-identical to --source and the
# scan stays advisory.
FORMAT_FIX_MODES = ("auto", "off")
DEFAULT_FORMAT_FIX = "auto"
# The published copy keeps its LIVE Zotero fields by default because it must
# remain the judged bytes. Operators who want the pipeline to flatten set
# `format_policy.unlink_zotero_fields` (or the compatibility key
# `unlink_zotero_fields_at_publish`) BEFORE `run`; the stage-side formatter then
# flattens every candidate before it is pinned and scored.
DEFAULT_PUBLISH_FLATTEN_ZOTERO = False
# `run --only`: run a subset of the round's stages. `merge` is an alias for the
# integration stage (the pipeline's "merge from the other versions" step), and
# `a`/`w`/`i` are the short spellings used in the round plan.
ONLY_STAGES = ("rewrite", "review", "probe", "audit", "revise", "integrate", "judge",
               "feedback", "concerns", "response", "conform")
ONLY_ALIASES = {"w": "rewrite", "rewrites": "rewrite", "r": "review", "reviews": "review",
                "pr": "probe", "prob": "probe", "probes": "probe", "probe-review": "probe",
                "aud": "audit", "audits": "audit", "auditor": "audit", "verify": "audit",
                "a": "revise", "a2": "revise", "revises": "revise", "revision": "revise",
                "i": "integrate", "integrations": "integrate", "integration": "integrate",
                "merge": "integrate", "merges": "integrate", "j": "judge", "judges": "judge",
                "fb": "feedback", "feedbacks": "feedback",
                "concern": "concerns",
                "resp": "response", "responses": "response", "response-to-reviewers": "response"}
# The auditor sits between the reviewer and the reviser: it disposes the frozen
# review's findings (confirm / drop-with-evidence) and attacks the reviewer's
# boilerplate dispositions, and the reviser consumes the AUDITED list. `off`
# keeps the previous plan shape (review -> revise) for comparability.
# The auditor is ON by default: the review's disposition layer was the pipeline's
# single largest source of shipped leftovers, and one extra session per round is
# cheaper than a second round. `setup --audit off` (or `--no-audit`) restores the
# two-step plan; a root created before this default keeps the policy recorded in
# its own pipeline_config.json.
AUDIT_MODES = ("off", "on")
DEFAULT_AUDIT = "on"
# HOW A ROUND'S CHAMPION IS CHOSEN (`setup/run/decide --champion-select`).
#   judge     (default) the relative-judgment panel scores the field and
#             `select_champion` ranks it exactly as documented in Section D;
#   revise    NO judge panel: the round's single review-audit-revised candidate
#             (a2) is promoted directly. Integration arms are not run because
#             nothing can outrank the promoted candidate;
#   integrate NO judge panel: the integration arm of the revised candidate
#             (a_{M+2} -> i_{M+2}) is promoted directly; the round's integration
#             mask must plan that arm.
# The last two are an explicit operator override of rule 5/6's panel gate. The
# result is marked auto-promoted and the decision is PROVISIONAL: it is never
# presented as a certified panel verdict.
CHAMPION_SELECT_MODES = ("judge", "revise", "integrate")
DEFAULT_CHAMPION_SELECT = "judge"
# `setup --placeholder-lookup`: resolve a `searchable` hand-off marker
# ([AUTHOR TO COMPLETE: state whether this work has been posted to a preprint
# server ...]) with the orchestrator's own public-API lookups BEFORE the session
# starts. The sessions may not search the network (their sandbox is closed), so
# without this the pipeline can only carry the question forward -- which is how
# a question whose answer is "not posted" reached the submitted cover letter.
PLACEHOLDER_LOOKUP_MODES = ("off", "online")
DEFAULT_PLACEHOLDER_LOOKUP = "online"
# `--strict-artifacts` is ON by default and `--residual-gate` is ON by default:
# a decision artifact that is empty or boilerplate, a language pass without its
# coverage rows, and a delivered package that still carries a marker the lookup
# engine answered are all failures now, not warnings. The `--non-…` flags exist
# for operators who want the older advisory behaviour (and for the pipeline's
# own regression fixtures).
DEFAULT_STRICT_ARTIFACTS = True
# `--strict-artifacts` takes three values (bare = `on`):
#   on   an unfilled/boilerplate decision artifact FAILS the attempt (default)
#   fix  ... but first spend ONE scoped repair session on that attempt's decision
#        tables (see `artifact_policy_of`); the same postcheck judges the repair
#   off  record the detector's report as a warning, never fail on it
# VARIANT B (operator decision, 2026-09-23): a repair finishes the paperwork of
# work that HAPPENED; it never substitutes for the work. So a repair may only
# CHANGE files the stage itself wrote (fill cells, complete a ledger/report it
# left behind). A deliverable the stage never wrote -- a missing ledger, report,
# language pass, visual record or completion marker -- is NOT repairable: the
# stage stopped before finishing, the attempt fails, and the stage is re-run.
# The guard enforces it mechanically (any file created inside the writable scope
# is out of scope), so not even a well-meaning repair can author one.
# `fix` exists because the alternative -- re-running the whole review for a
# disposition column -- costs a full re-sample of the stage (the 2026-09-22 root
# paid 26 minutes and produced a different finding set to fix one column), while
# the repair is bounded: fill cells, never touch findings, never touch a row's
# identity, then pass the identical postcheck or fail like any other attempt.
ARTIFACT_POLICY_FIX = "fix"
ARTIFACT_POLICIES = ("on", ARTIFACT_POLICY_FIX, "off")
DEFAULT_ARTIFACT_POLICY = "on"
DEFAULT_RESIDUAL_GATE = True
# How many identifier lookups one stage may spend. Each lookup is one or more
# requests (a DOI asks Crossref, then DataCite, then the handle registry) with a
# 10-second timeout per request -- worst case about 30 seconds -- cached for
# LOOKUP_CACHE_TTL_DAYS across the root's sandboxes; `off`/an unreachable network
# degrades to recorded `error` rows, never to a failed stage. The cap is spent in
# the reserved order below,
# and the reference-list DOIs now sit first in that order: a manuscript's
# reference list is the largest class by far (one entry each) and the only place
# a one-character DOI corruption can be caught at all -- no format check and no
# re-reading sees it (see M2_references.md).
LOOKUP_MAX_TARGETS = 48
LOOKUP_TIMEOUT = 10
# One cheap probe per process decides whether the lookup engine runs at all;
# without it every sandbox would pay a DNS/connect timeout per query (the
# scheduling tests measure a round in seconds), and an offline operator would
# see a slow pipeline instead of `skipped` rows. The probe asks the works
# ENDPOINT (no specific record): a record is not a reachability test -- the old
# probe named a DOI that answers HTTP 404, `urlopen` raised on the 404, and the
# whole lookup engine (identifiers, availability locators, gene symbols,
# placeholders, and the reference-integrity seed) then recorded `skipped`
# everywhere while blaming the operator's network. Any HTTP ANSWER means the
# API is reachable; only a connect/DNS/TLS failure is "not available".
LOOKUP_PROBE_URL = ("https://api.crossref.org/works?rows=0"
                    "&mailto=paper-pipeline@example.org")
LOOKUP_PROBE_TIMEOUT = 2.5
LOOKUP_CACHE_REL = "reports/LOOKUP_CACHE.json"
LOOKUP_CACHE_TTL_DAYS = 14
_LOOKUP_PROBE = {}

# A candidate's corpus is its revised/ documents (plus code/), NOT the revision
# skill's WORK directory: revised/work/ holds the A1-A9 process artifacts,
# corpus conversions and scripts, which are not part of the submission. Without
# this exclusion every round's winner would carry its own scratch tree into the
# next round's base, and the frozen-sweep reviewers would inventory converted
# copies of the manuscript as if they were extra submission files.
CORPUS_EXCLUDE_TOP = ("work",)

# ---- code-side caption checking (M18) -------------------------------------
# When the operator opts into the pipeline's caption suggestion, the prompts ask
# every agent to count caption words. These lists/knobs let the orchestrator
# check the lengths mechanically where the text is extractable, and to say so
# honestly where it is not. The check is a REPORT: caption length never gates,
# ranks or fails anything (see caption_gate() and CAPTION_RULE).
# One source of truth for "which files does each code-side scan read?".
CAPTION_DOCX_EXTS = (".docx",)
CAPTION_TEX_EXTS = (".tex", ".ltx")
# The same editable text formats the length scan reads (LENGTH_TEXT_EXTS): a
# manuscript whose legends are counted as main text must also have them
# enumerated, or M18 reports nothing for a document M19 measures.
CAPTION_TEXT_EXTS = (".md", ".txt", ".markdown", ".rst")
CAPTION_SOURCE_EXTS = CAPTION_DOCX_EXTS + CAPTION_TEX_EXTS + CAPTION_TEXT_EXTS
# The placeholder diagnostic also looks at bibliography/data/prose tables.
PLACEHOLDER_SOURCE_EXTS = CAPTION_SOURCE_EXTS + (".bib", ".csv", ".rtf")
CAPTION_UNPARSED_EXTS = (".doc", ".pdf", ".ppt", ".pptx")

# Files the pipeline itself (or the revision skill it drives) mandates inside the
# submission directory. They are pipeline bookkeeping, not submission content:
# they are excluded from the caption scan and from the document-set comparison so
# that a changelog quoting a caption, or a report that is regenerated under a
# different name, is never judged as manuscript text. They are excluded from the
# corpus DIGEST (hash/pin/next-round base) -- and from the materialized pin and
# judge target -- by this same name rule, so the two sides remain byte-identical.
BOOKKEEPING_FILES = ("changelog.md", "manual_steps.md", "revision_report.md",
                     "revision_report.json", "diff_ledger.md", "rewrite_report.md",
                     "visual_check.md",
                     # The pipeline's own completion signals. They belong at the
                     # sandbox ROOT (see SIGNAL_ALT_DIRS); this list is the second
                     # fence: a signal that ends up INSIDE a package directory
                     # (a misplaced `_pipeline_done.json`, a judge sheet dropped
                     # into `revised/`) must never travel into the judged corpus,
                     # the champion pin or the content fingerprint -- a stray
                     # bookkeeping file would otherwise date a package or make
                     # two copies of the same content look different.
                     "_pipeline_done.json", "scores.json")

# Bookkeeping the pipeline (or the skills it drives) mandates inside the
# submission directory. The agent that writes a version also writes these files,
# so they must never be handed to a judge as package content: a self-written
# report is not evidence, its presence/absence between two labels is a
# provenance signal, and a polished CHANGELOG is exactly the kind of claim a
# relative judge must not read. They stay in the run's own sandbox, where the
# postchecks, the manual-item count and the decision report read them.
# (BOOKKEEPING_FILES already carries visual_check.md: the visual record is a
# stage report, so the judged/pinned corpus and the content FINGERPRINT must
# skip exactly the same names -- otherwise a champion's recorded fingerprint
# never matches the pinned copy built from it, and the next round's base stops
# deduplicating against the pin it was copied from.)
CORPORA_STRIP_BOOKKEEPING = BOOKKEEPING_FILES


# The pipeline's own by-products can carry a VERSION TOKEN between their name
# and their extension (`REPLACEMENT_LEDGER-c27c42e.md` is what the published
# package actually carries after the filename counter runs). The exact-name
# test above therefore misses them, which is how a stage's internal re-authoring
# ledger shipped to the journal. The pattern below matches the family with or
# without a token, so the strip/fingerprint/bookkeeping paths all agree.
BOOKKEEPING_NAME_RE = re.compile(
    r"^(?:replacement_ledger|diff_ledger|revision_report|rewrite_report|manual_steps|"
    r"visual_check|changelog|agent_log|worklog)"
    r"(?:[-_.][A-Za-z0-9._\-]+)?\.(?:md|txt|json)$"
    # The pipeline's own MEASUREMENT artifacts (written next to a run, never
    # into a delivered package): a scan/repair report, the code-side evidence
    # pack, the PKG-2 record. They are skipped by every corpus walk AND by the
    # PKG-2 scan itself -- an evidence JSON that names the areas ("raw_data/",
    # "code/") is not a submitted document, and reporting it as a dangling
    # reference would drown the real rows (2026-10-15).
    r"|^(?:code_scans|format_scan|format_fix|pkg2)(?:[-_.][A-Za-z0-9._\-]+)?"
    r"\.(?:md|txt|json)$", re.I)


def is_bookkeeping_name(name: str) -> bool:
    base = str(name or "").strip()
    if base.lower() in BOOKKEEPING_FILES:
        return True
    return bool(BOOKKEEPING_NAME_RE.match(base))


# Caption start patterns: "Figure 1 |", "Fig. 2.", "Supplementary Figure 3:", ...
_CAPTION_LABEL_RE = (r"^\s*(?:(?:supplementary|extended\s+data|supp\.?)\s+)?"
                     r"fig(?:ure)?s?\.?\s*\|?\s*")
_CAPTION_NUM_RE = r"(S?\d+[A-Za-z]?|(?-i:[IVXLCDM]+))"
# The panel group "(a)", "(a,b)" or "(a-b)" sits between the number and the
# separator: "Figure 2(a) |" is a caption, "Figure 2 is a schematic" is not.
_CAPTION_PANEL_RE = r"(?:\s*\([A-Za-z0-9][A-Za-z0-9,.\u2013\-]*\))?"
CAPTION_START_RE = re.compile(
    _CAPTION_LABEL_RE + _CAPTION_NUM_RE + _CAPTION_PANEL_RE +
    # A dash followed by a letter is a PANEL RANGE in running prose
    # ("Figure 2a-b shows ..."), not the caption separator.
    r"\s*(?:(?:\||:|\u2014|\u2013|-)(?![A-Za-z])|\.)\s*",
    re.IGNORECASE)
# Caption-LOOKING lines the strict pattern above does not recognise (a bare
# "Figure 3" line, a text-box label, an unusual separator). They are reported as
# suspected captions instead of being dropped silently.
CAPTION_SUSPECT_RE = re.compile(
    _CAPTION_LABEL_RE + _CAPTION_NUM_RE +
    r"\s*(?:\([^)]*\)|$|[|:\u2014\u2013\-])",
    re.IGNORECASE)
# Table captions are counted as a display-caption span only for a profile whose
# `counting.main_text.excludes` names `table-captions` (Frontiers groups "figure
# and table captions" in its main-body rule). They are not figure legends: the
# M18 legend scan keeps its figure-only patterns.
TABLE_CAPTION_START_RE = re.compile(
    r"^\s*(?:(?:supplementary|extended\s+data|supp)\s+)?tables?\.?\s*"
    r"(S?\d+[A-Za-z]?|(?-i:[IVXLCDM]+))"
    r"\s*(?:\||:|\u2014|\u2013|-|\.)\s*",
    re.IGNORECASE)

# ---- code-side document-set checking --------------------------------------
# Editable submission documents that must survive a rewrite/revision/integration
# round. Auxiliary files the revision skill emits on purpose are never required
# and never counted as duplicates. The auxiliary is a difference-tracking copy
# named for the BASELINE it was compared against (see TRACK_TOKEN_RE):
#
#   <name>.tracking-<token>.<ext>    real tracked copy (word/latexdiff)
#   <name>.tracking-<token>.pdf      compiled marked-up PDF of a latexdiff copy
#   <name>.logging-<token>.<ext>     the fallback log when the tool failed
#
# where <token> is `original` (the pre-conformed submission in non_revised/) or
# the id of the version the copy was compared against -- the round base `a1`,
# a rewrite `w<k>`, a revision `a<k>`, or `winner<r>` for the published winner
# of round r.
EDITABLE_DOC_EXTS = (".doc", ".docx", ".tex", ".ltx", ".bib", ".md", ".txt", ".xlsx",
                     ".rtf", ".csv")
# The extensions a difference-tracking copy is built for.
TRACKING_EXTS = (".docx", ".tex", ".bib")
# A latexdiff `.tex` copy is COMPILED as well, and the marked-up PDF is part of
# the same auxiliary family ("<name>.tracking-<token>.pdf"): a reader can open
# the tracked changes without a LaTeX toolchain, and the file can never leak
# into a corpus/pin/judge view (see TRACKING_AUX_NAME_RE).
TRACKING_PDF_EXT = ".pdf"
# The baseline token of a copy: the pre-conformed original, or the id of the
# version it was compared against (`a1`, `w2`, `a3`, ... -- the pipeline's own
# version vocabulary) or a published round winner (`winner1`, `winner2`, ...).
# The token is INFORMATIVE on purpose: "<name>.tracking-a1.docx" says exactly
# which version the difference was taken against.
TRACK_TOKEN_ORIGINAL = "original"
TRACK_TOKEN_RE = re.compile(r"^(?:original|winner[0-9]+|[awi][0-9]+)$", re.IGNORECASE)
# The full-file rule: `<anything>.tracking-<token>.<ext>` or
# `<anything>.logging-<token>.<ext>`. A file matching it is an auxiliary
# EVERYWHERE in the pipeline (corpus digest, pin, judge view, fingerprint,
# revision token, recovery backfill), which is what lets the pipeline write the
# copies next to a document without changing any version's identity.
TRACKING_AUX_NAME_RE = re.compile(
    r"\.(?:tracking|logging)-(?:original|winner[0-9]+|[awi][0-9]+)"
    r"\.(?:docx|tex|bib|pdf)$", re.IGNORECASE)
# Trailing version token on a basename stem: the CURRENT content-hash token
# ("-4f3a9c1"/"_4f3a9c1", 7 lowercase hex characters) or the LEGACY version
# tokens ("-b", "_v2", "-v10", case-insensitive) that older packages carry.
# A PLAIN trailing number ("-1", "-3") is NOT a version token: SI-Table-1.csv
# and Figure-3.xlsx are distinct documents and must never be merged.
DOC_TOKEN_RE = re.compile(r"(?:[-_][0-9a-f]{7}|[-_][vV]\d+|[-_][A-Za-z])$")
# Source/provenance suffixes that describe where a document came from, not a
# different submission role. A content-token rename may legitimately change
# these (`mainText-FrontiersTemplate-zotero-<old>` ->
# `mainText-<new>`); recovery must treat that as the same document renamed, not
# as a lost old document plus an invented new one.
DOC_PROVENANCE_SUFFIX_RE = re.compile(
    r"(?i)(?:[-_](?:frontiers?template|zotero))+$")

# Extensions that only ever hold a BUILD BY-PRODUCT of an editable source
# (.aux/.log/.synctex.gz/...). The prompts prescribe leaving these out of
# revised/, so the recovery backfill must never copy them back in.
DERIVED_BUILD_SUFFIXES = (".aux", ".blg", ".bcf", ".log", ".out", ".fls", ".fdb_latexmk",
                          ".synctex.gz", ".run.xml", ".toc", ".lof", ".lot", ".nav",
                          ".snm", ".vrb", ".bbl", ".idx", ".ilg", ".ind")


def _is_derived_name(name: str) -> bool:
    low = name.strip().lower()
    return any(low.endswith(s) for s in DERIVED_BUILD_SUFFIXES)


# The build by-products a JUDGE VIEW never carries: DERIVED_BUILD_SUFFIXES minus
# the one derived file the prompts let a package ship on purpose -- a compiled
# ".bbl" (with no editable ".bib" beside it, the ".bbl" is the only copy of the
# reference list, and unlike the others it carries no build date, tool path or
# machine name). Used by _is_view_excluded_file().
VIEW_STRIP_DERIVED_SUFFIXES = tuple(s for s in DERIVED_BUILD_SUFFIXES if s != ".bbl")

# Editable sources that turn a same-stem ".pdf" into a DERIVED output of the
# package: a judge is handed the source, not the rendering (see
# _is_view_excluded_file). ".txt" is deliberately absent -- a text file sitting
# beside a figure PDF is not a source/derived pair.
VIEW_DERIVED_SOURCE_EXTS = (".doc", ".docx", ".tex", ".ltx", ".rtf", ".md")

DERIVED_DOC_VERSION_RE = re.compile(r"(?:[-_][0-9a-f]{7}|[-_][vV]\d+)$")


def _doc_stem_key(name: str) -> str:
    """A basename's stem without a content/addressing version token.

    A single trailing letter is not a version token here: `figure-a.pdf` is not
    a rendering of `figure.docx`. Only the 7-hex content token and the explicit
    `-vN` spelling identify a derived output's source.
    """
    return DERIVED_DOC_VERSION_RE.sub("", Path(name).stem).lower()


def _is_view_excluded_file(name: str, siblings=()) -> bool:
    """True for a file a JUDGE VIEW never carries (submission content only).

    Beyond the revision auxiliaries `_is_aux_doc()` already drops, a view drops
    the build by-products of an editable source (".aux", ".log", ".toc", ...)
    and Word's "~$name.docx" owner/lock files. Three reasons:

      * they are not submission content -- a compile regenerates every one of
        them, and the stage prompts already order them left out of a version;
      * their CONTENT is provenance: a LaTeX ".log"/".fls"/".synctex.gz" names
        the build machine's absolute paths and the exact build date, and a
        "~$" file names its author -- the metadata pass cannot touch what is
        inside a build log;
      * their PRESENCE is provenance: a version an agent went over loses them
        (the prompts order that) while the untouched original keeps them, so
        the file SET alone would tell a judge which package was worked on.

    A view is also given the SOURCES rather than what can be compiled from them,
    so a derived output whose editable source ships in the same directory is
    dropped too: a compiled ".bbl" beside its ".bib", and a ".pdf" beside the
    ".docx"/".doc"/".tex"/".ltx"/".rtf"/".md" it was rendered from (see
    VIEW_DERIVED_SOURCE_EXTS). `siblings` is that directory's file-name list.
    A derived file with NO source in the package stays: when it is the only copy
    of the content, it IS the content -- with no ".bib" shipped, a ".bbl" is the
    only copy of the reference list.
    """
    low = name.strip().lower()
    if is_author_to_complete_readme_name(name):
        # The hand-off README is the author's checklist, never submission
        # content. Its PRESENCE differs between a candidate that still owes the
        # author an item and one that does not, so a judge must not see it: the
        # underlying gap is scored from the package itself (the judge rule says
        # so), and the checklist would otherwise be a provenance signal.
        return True
    if _is_aux_doc(name) or low.startswith("~$"):
        return True
    if low.endswith((".pdf", ".bbl")):
        sources = VIEW_DERIVED_SOURCE_EXTS if low.endswith(".pdf") else (".bib",)
        if low.endswith(".bbl"):
            # A compiled bibliography keeps the source's version token.
            stem = DOC_TOKEN_RE.sub("", Path(name).stem).lower()
            return any(
                s.strip().lower().endswith(sources)
                and DOC_TOKEN_RE.sub("", Path(s).stem).lower() == stem
                for s in siblings)
        # For a PDF, the output's own name is compared narrowly (figure-a.pdf
        # is not figure.docx), while its editable source may carry a legacy
        # one-letter token (supp-b.tex supplies supp-<hash>.pdf).
        stem = _doc_stem_key(name)
        return any(
            s.strip().lower().endswith(sources)
            and (_doc_stem_key(s) == stem
                 or DOC_TOKEN_RE.sub("", Path(s).stem).lower() == stem)
            for s in siblings)
    return low.endswith(VIEW_STRIP_DERIVED_SUFFIXES)


# ---- opaque judge session identity ----------------------------------------
# A judge must not be able to infer provenance from its own target: the sandbox
# run id and the sheet's target_id are opaque tokens derived from
# (round, version id); the version id itself lives only in the run record.
JUDGE_TOKEN_PREFIX = "t"

# Version ids. Fresh ids are local to one round; a pinned version carries its
# round prefix so ids stay unique inside a field (e.g. "r1_a2").
ORIGINAL_ID = "orig"
A1_ID = "a1"

# ---- THE ROUND'S CANDIDATE POOL (M rewrites, N revisions, then integration) --
# Every round is planned with two per-round counts (both are command-line
# parameters, see --rewrites / --revises):
#   M = the number of REWRITTEN candidates the round creates from its base
#       (independent rewrite sessions, staged BEFORE the review), and
#   N = the number of REVIEWED-AND-THEN-REVISED candidates the round creates
#       (the round's single $paper-review pass is consumed by N independent
#       $paper-revise sessions).
# The round's POOL is, in this fixed order:
#   "a1"                       the round's base A1_r        (not an agent run)
#   "w1" .. "wM"               the M rewritten candidates
#   "a2" .. "a{1+N}"           the N reviewed-and-revised candidates
# and EVERY pool member is then reworked ONCE by an INTEGRATION run that takes
# that member as its base and ALL the OTHER pool members as donors (this is the
# stage formerly mis-named "cross-pollination" -- there are no pairwise arms):
#   "i1" .. "iK"   with K = 1 + M + N, i{k} integrating the k-th pool member,
#                  so with M=2, N=1:
#                    i1 = a1 <- (w1, w2, a2)     i3 = w2 <- (a1, w1, a2)
#                    i2 = w1 <- (a1, w2, a2)     i4 = a2 <- (a1, w1, w2)
# A1_r is the round's incumbent (its row is the field member it deduplicates
# into) and is not itself a candidate to crown; everything else, the integrated
# candidates included, competes on the published ranking key.
FRESH_VID_RE = re.compile(r"^(?:w(\d+)|a(\d+)|i(\d+))$")


def rewrite_vid(k) -> str:
    """Version id of the k-th rewritten candidate of a round ("w1", "w2", ...)."""
    return f"w{int(k)}"


# The LEVEL a rewrite arm works at. The round deliberately contains BOTH levels
# when it has more than one rewrite: the pool then carries large (organization)
# and small (sentence) differences, the integration stage's DIFF_LEDGER has both
# kinds of rows to weigh, and the panel can see whether a difference is a
# reorganization or a prose improvement.
REWRITE_LEVELS = ("structural", "sentence")


def rewrite_level_of(k: int, m: int) -> str:
    """`structural` for odd arms, `sentence` for even ones (M >= 2).

    With a single rewrite arm the level is `structural`: organization is what a
    rewrite exists for, and the sentence level is covered by every revision arm
    and by the language pass.
    """
    if int(m) <= 1:
        return "structural"
    return "structural" if int(k) % 2 == 1 else "sentence"


def revise_vid(j) -> str:
    """Version id of the j-th reviewed-and-revised candidate ("a2", "a3", ...)."""
    return f"a{int(j) + 1}"


def integrate_vid(k) -> str:
    """Version id of the k-th integrated candidate ("i1", "i2", ...)."""
    return f"i{int(k)}"


def is_fresh_vid(vid) -> bool:
    """True for a round-local version id (a1/w*/a>=2/i*), False for pins/orig."""
    return bool(isinstance(vid, str) and FRESH_VID_RE.match(vid))


def is_integrated_vid(vid) -> bool:
    return bool(isinstance(vid, str) and vid.startswith("i") and
                FRESH_VID_RE.match(vid))


def arm_of_vid(vid) -> str:
    """"rewrite" | "revise" | "integrate" | "base" for a round-local version id."""
    if vid == A1_ID:
        return "base"
    m = FRESH_VID_RE.match(str(vid))
    if not m:
        return "pinned"
    if m.group(1):
        return "rewrite"
    if m.group(2):
        return "revise"
    return "integrate"


def parse_round_counts(values, rounds: int, flag: str) -> list:
    """Normalize a per-round count list to exactly `rounds` entries.

    The CLI accepts either a single integer ("--rewrites 3") or a comma/space
    separated list of length n = --rounds ("--rewrites 2,1"). A list shorter
    than n is EXTENDED BY REPEATING ITS LAST ELEMENT; a longer one is truncated
    to the first n entries (the extra entries would never be reached).
    """
    vals = []
    for v in (values if isinstance(values, (list, tuple)) else [values]):
        if v is None:
            continue
        # A command-line value arrives as ONE string ("3", "2,1", "2, 1"); a
        # config value may already be a list of ints. Both shapes are accepted.
        # `_` is a separator too: `int("1_2")` is 12, so without this a list
        # written as `1_2` silently became ONE round count of twelve.
        parts = re.split(r"[,;_\s]+", str(v).strip()) if isinstance(v, str) else [v]
        vals.extend(p for p in parts if str(p).strip() != "")
    counts = []
    for v in vals:
        try:
            counts.append(int(str(v).strip()))
        except (TypeError, ValueError):
            die(f"{flag} takes an integer or a comma-separated list of integers "
                f"(e.g. '{flag} 3' or '{flag} 2,1'), got {v!r}")
    if not counts:
        die(f"{flag} needs at least one integer")
    if any(c < 0 for c in counts):
        die(f"{flag} values must be >= 0, got {counts}")
    rounds = max(1, int(rounds))
    if len(counts) < rounds:
        counts = counts + [counts[-1]] * (rounds - len(counts))
    return counts[:rounds]


def normalize_round_indices(values, schedule_len: int = ROUND_SCHEDULE_LEN) -> list:
    """Normalize `--round-indices` to ascending 1-based schedule positions.

    Positive values count from the start of the built-in schedule (1 = the
    first round), negative values from its end (-1 = the last round). The
    ORDER is the pipeline's run order: the first index maps to pipeline
    round 1. Duplicates, an out-of-range index, a zero and a descending
    sequence are errors, because each silently changes which plan a round
    adopts.
    """
    if not values:
        die("--round-indices needs at least one round index")
    out = []
    for v in values:
        try:
            i = int(v)
        except (TypeError, ValueError):
            die(f"--round-indices takes integers (1-based, or negative from the end), got {v!r}")
        if i == 0:
            die("--round-indices is 1-based (or negative from the end); 0 is not a round")
        pos = i if i > 0 else schedule_len + 1 + i
        if pos < 1 or pos > schedule_len:
            die(f"--round-indices {i} is outside the built-in schedule 1..{schedule_len} "
                f"(negative values count from the end, -1 = {schedule_len})")
        out.append(pos)
    if len(set(out)) != len(out):
        die(f"--round-indices carries a repeated round: {out} "
            f"(one selected round runs once)")
    if out != sorted(out):
        die(f"--round-indices must be listed in ascending run order, got {values} -- "
            f"the FIRST index maps to the pipeline's round 1")
    return out


def parse_round_masks(values, rounds: int, flag: str) -> list:
    """Normalize a per-round integrator bitmask list to exactly `rounds` entries.

    Same shape rules as parse_round_counts (one value or a comma-separated list;
    a shorter list is extended by repeating its last element, a longer one is
    truncated), but each entry is an unsigned 32-bit mask written in any Python
    integer literal form: decimal ("5"), hexadecimal ("0xFFFFFFFF", the default),
    octal or binary. The mask addresses the round's pool in canonical order
    [a1, w1..wM, a2..a{1+N}]: bit (k-1) selects the integration arm i<k> of the
    k-th member (see INTEGRATOR_ALL).
    """
    vals = []
    for v in (values if isinstance(values, (list, tuple)) else [values]):
        if v is None:
            continue
        # A command-line value arrives as ONE string ("5", "0xFF,3"); a config
        # value may already be a list of ints. Both shapes are accepted.
        parts = re.split(r"[,;\s]+", str(v).strip()) if isinstance(v, str) else [v]
        vals.extend(p for p in parts if str(p).strip() != "")
    masks = []
    for v in vals:
        try:
            mask = int(str(v).strip(), 0)
        except (TypeError, ValueError):
            die(f"{flag} takes an integer bitmask or a comma-separated list of them "
                f"(e.g. '{flag} 0xFFFFFFFF' or '{flag} 0x5,3'), got {v!r}")
        if mask < 0 or mask > INTEGRATOR_ALL:
            die(f"{flag} values must be unsigned {INTEGRATOR_BITS}-bit masks in "
                f"0..0x{INTEGRATOR_ALL:X}, got {v!r}")
        masks.append(mask)
    if not masks:
        die(f"{flag} needs at least one bitmask")
    rounds = max(1, int(rounds))
    if len(masks) < rounds:
        masks = masks + [masks[-1]] * (rounds - len(masks))
    return masks[:rounds]


def counts_of(cfg, key: str, rounds: int) -> list:
    """The configured per-round counts, falling back to the documented defaults."""
    raw = (cfg or {}).get(key)
    if raw is None:
        raw = list(DEFAULTS[key])
    elif not isinstance(raw, (list, tuple)):
        raw = [raw]
    return parse_round_counts(raw, rounds, "--" + key)


def masks_of(cfg, key: str, rounds: int) -> list:
    """The configured per-round masks, falling back to the documented defaults.

    Accepts both the list written by a current `setup` and the plain integer an
    older root (or a hand-built test context) carries, so per-round integrator
    masks degrade to "the same mask every round" instead of crashing.
    """
    raw = (cfg or {}).get(key)
    if raw is None:
        raw = list(DEFAULTS[key])
    elif not isinstance(raw, (list, tuple)):
        raw = [raw]
    return parse_round_masks(raw, rounds, "--" + key)


def config_rounds(ctx=None, cfg=None) -> int:
    """The configured round count (never 0, so a hand-built test context works)."""
    cfg = (cfg if cfg is not None else getattr(ctx, "cfg", None)) or {}
    try:
        rounds = int(cfg.get("rounds") or 0)
    except (TypeError, ValueError):
        rounds = 0
    return max(1, rounds or len(DEFAULTS["rewrites"]))


def round_index(r: int, rounds: int) -> int:
    """The 0-based list index of round `r`, clamped into the configured range."""
    return max(0, min(int(r) - 1, max(1, int(rounds)) - 1))


def brief_list(values, fmt=str) -> str:
    """'3,3' / '0xffffffff,0x1' -- a one-line rendering of a per-round list."""
    return ",".join(fmt(v) for v in (values or []))


def judges_config_note(ctx) -> str:
    """The configured judges-per-round list, for config summary lines."""
    return brief_list(counts_of(getattr(ctx, "cfg", None), "judges", ctx.rounds_count()))


def integrators_config_note(ctx) -> str:
    """The configured integrators-per-round list, in hex."""
    return brief_list(masks_of(getattr(ctx, "cfg", None), "integrators", ctx.rounds_count()),
                      lambda v: f"0x{int(v):X}")


def round_counts(ctx, r: int) -> tuple:
    """(M, N) for round `r`: rewrites and reviewed-and-revised candidates.

    A round that has already been DECIDED carries its plan on the round record,
    and that recorded plan wins. Re-deriving the candidate set from the mutable
    config made `decide` non-reproducible: editing `pipeline_config.json`
    (or restoring it from a backup with different --rewrites/--revises values)
    silently changed which arms were considered, so the recomputed champion no
    longer matched the stored one and `decide` reported a bogus integrity
    problem about judge sheets that were perfectly fine.
    """
    try:
        plan = (ctx.round_get(int(r)) or {}).get("plan") or {}
    except Exception:                                        # noqa: BLE001
        plan = {}
    if is_int(plan.get("rewrites")) and is_int(plan.get("revises")):
        return max(0, int(plan["rewrites"])), max(0, int(plan["revises"]))
    rounds = config_rounds(ctx)
    idx = round_index(r, rounds)
    m = counts_of(getattr(ctx, "cfg", None), "rewrites", rounds)[idx]
    n = counts_of(getattr(ctx, "cfg", None), "revises", rounds)[idx]
    return int(m), int(n)


def champion_select_of(ctx=None) -> str:
    """The champion-selection mode (`judge` unless the operator overrode it).

    An invocation-level override (`run/decide --champion-select`) wins over the
    root's persisted `champion_select` config key. A decided round stores the
    mode it actually used in `plan.champion_select`; `decide` reads THAT (see
    `round_champion_select`) so a later config edit cannot relabel a round.
    """
    override = str(getattr(ctx, "_champion_select_override", "") or "").strip().lower()
    raw = override or str((getattr(ctx, "cfg", None) or {}).get("champion_select") or "")
    raw = raw.strip().lower()
    if not raw:
        return DEFAULT_CHAMPION_SELECT
    if raw not in CHAMPION_SELECT_MODES:
        die(f"unknown champion-selection mode {raw!r}; use "
            f"{'|'.join(CHAMPION_SELECT_MODES)} (fix `champion_select` in "
            f"pipeline_config.json, or pass --champion-select to setup/run/decide)")
    return raw


def round_champion_select(ctx, r: int) -> str:
    """The mode round `r` records (a decided round wins over the config)."""
    try:
        plan = (ctx.round_get(int(r)) or {}).get("plan") or {}
    except Exception:                                        # noqa: BLE001
        plan = {}
    raw = str(plan.get("champion_select") or "").strip().lower()
    if raw in CHAMPION_SELECT_MODES:
        return raw
    return champion_select_of(ctx)


def auto_champion_vid(ctx, r: int, mode: str = None) -> str:
    """The version auto-promoted by a no-judge mode for round `r`.

    `revise` promotes the round's single reviewed-and-revised candidate (a2).
    `integrate` promotes that candidate's integration arm: pool order is
    [a1, w1..wM, a2..a{1+N}], so a2 is pool member M+2 and its arm is i{M+2}.
    Both modes need exactly ONE revise arm; with N>1 there is no single
    "review-audit-revised submission version" to crown, and guessing would make
    the winner depend on an undocumented tie-break.
    """
    mode = str(mode or champion_select_of(ctx)).strip().lower()
    if mode not in CHAMPION_SELECT_MODES:
        die(f"unknown champion-selection mode {mode!r}; use "
            f"{'|'.join(CHAMPION_SELECT_MODES)}")
    if mode == "judge":
        die("auto_champion_vid() asked for a version in judge mode; the panel selects it")
    m, n = round_counts(ctx, r)
    if n != 1:
        die(f"--champion-select {mode} needs exactly ONE review-and-revise arm in round {r}, "
            f"but the round plans N={n}. The no-judge modes promote the single revised "
            f"submission; set --revises 1 (for every round, or for round {r}) and re-run.")
    if mode == "revise":
        return revise_vid(1)
    target = integrate_vid(m + 2)
    planned = round_integrated_run_ids(ctx, r, m, n)
    if target not in planned:
        die(f"--champion-select integrate promotes '{target}', the integration of the revised "
            f"candidate {revise_vid(1)}, but round {r}'s integrator mask "
            f"0x{round_integrators(ctx, r):X} does not plan that arm. Select pool member "
            f"{m + 2} of [{', '.join(round_pool_ids(m, n))}] (bit index {m + 1}, "
            f"mask value {1 << (m + 1)}) or use --champion-select revise.")
    return target


# --- WHICH JUDGE SESSIONS RUN (`run --only r1_judge_w2_j1`) -----------------
# `--judges` sets HOW MANY judges a version gets; `run --only` can select WHICH
# of those sessions run in that invocation (a pilot lever: one cheap judge session
# instead of a panel). No selector = every configured session (the default); the
# selector is a WHITELIST, e.g. `--only r1_judge_w2_j1,r2_judge_i1_j1`
# (`r<round>[_judge_<version>[_j<index>]]`, also `2:judge_i1_j1` or a roundless
# `w2_j1`) -- see `OnlySpec` and `validate_only_judge_selectors`, which refuse an
# unknown round, version or judge index before anything starts.
JUDGES_ENABLED_ALL = "all"


def judgeable_ids(ctx, r: int) -> list:
    """The version ids a judge session in round `r` may target, in field order.

    The judge field is the pristine original, every EARLIER ROUND's pin (its id is
    the pinned run id, e.g. `r1_w2` -- in round 2 the base member IS that pin; the
    fresh `a1` copy of it is always content-identical and dropped by the field's
    deduplication), the round's pool (a1, w1.., a2..) and the integration arms the
    round's `--integrators` mask selected -- not just the pool, which is why
    `r2_judge_i1_j1` is a valid selector.
    """
    m, n = round_counts(ctx, r)
    return [ORIGINAL_ID] + round_pin_ids(ctx, r) + list(round_pool_ids(m, n)) \
        + [integrate_vid(k) for k in integrator_arms(m, n, round_integrators(ctx, r))]


def round_pin_ids(ctx, r: int) -> list:
    """The ids of the pins earlier rounds contributed to round `r`'s field.

    A pin's id is the run id of the version that won its round (`r1_w2`), and the
    field's deduplication keeps it as the round's base member: the fresh `a1` copy
    of that same content is dropped. So `r1_w2` -- not `a1` -- is the version a
    round-2 judge session on the base actually targets.
    """
    out = []
    for pin in sorted(ctx.state.get("pinned") or [], key=lambda p: int(p.get("round") or 0)):
        if int(pin.get("round") or 0) < int(r) and pin.get("id"):
            out.append(str(pin["id"]))
    return out


def judges_enabled_spec(ctx, r: int) -> str:
    """The selector string in force for round `r` ("" when every judge runs).

    A DECIDED round's recorded plan wins, exactly like round_judges(): `decide`
    must recompute the stored panel's expectation from the plan that produced it.
    """
    try:
        plan = (ctx.round_get(int(r)) or {}).get("plan") or {}
    except Exception:                                        # noqa: BLE001
        plan = {}
    rrec = {}
    try:
        rrec = ctx.round_get(int(r)) or {}
    except Exception:                                        # noqa: BLE001
        rrec = {}
    if plan.get("judges_enabled") is not None:
        spec = str(plan["judges_enabled"])
    elif rrec.get("judges_enabled") is not None:
        # A `run --only r1_judge_w2_j1` invocation records its selection here, so
        # a LATER invocation of the same (still pending) round keeps the smaller
        # panel instead of reading a full-panel gap out of the sheets it finds.
        spec = str(rrec["judges_enabled"])
    else:
        spec = ""
    spec = spec.strip()
    return "" if spec.lower() in ("", JUDGES_ENABLED_ALL) else spec


def judge_item_parts(item: str):
    """(round|None, version|None, judge index|None) for ONE judge-selector item.

    Every spelling the operator or `agents` can produce is accepted:

        r1_judge_w2_j1 / 2:judge_i1_j1   the keyword form (and the oldest spelling)
        r1_w2_j1 / 2:i1_j1               `agents`-friendly: ROUND_version_index
        w2_j1 / orig_j2 / a2_j1          no round: every round that has the version
        w2 / r1_judge_w2                 that version's whole panel
        j1 / judge_1 / r1_j1 / r1_judge  one judge index, of every version (of a round)
        r2_r1_w2_j1                      a PIN id as the version: the base of round 2 is
                                         the pin `r1_w2` (its fresh `a1` copy is
                                         content-identical and dropped by the field)

    A version may itself start with `r<digits>_`, which is why the leading round is
    read ONCE, from the front (a last-token-wins scan would read `r2_r1_w2_j1` as
    round 1 and silently drop the selector).
    """
    tok = str(item).strip().lower().replace(" ", "")
    r = None
    m = re.fullmatch(r"r?(\d+)(?:[_:/.-](.*))?", tok)
    if m:
        r, tok = int(m.group(1)), (m.group(2) or "")
    tok = re.sub(r"^judge[_:/.-]?", "", tok)
    if not tok or tok in ("judge", "j"):
        return r, None, None
    if re.fullmatch(r"\d+", tok):            # `judge_1` -> index 1
        return r, None, int(tok)
    k = None
    m = re.fullmatch(r"(.+?)[_:/.-]j(\d+)", tok)
    if m:
        tok, k = m.group(1), int(m.group(2))
    elif re.fullmatch(r"j[_:/.-]?\d+", tok):  # a bare `j1`
        return r, None, int(re.sub(r"\D", "", tok))
    return r, (tok or None), k


def parse_judges_enabled(spec: str, rounds: int, pool_of, judges_of) -> set:
    """Expand a selector into {(round, version, judge index)}; empty set = all.

    `pool_of(r)` and `judges_of(r)` describe the plan the selector is validated
    against (see `setup`, which builds it from --rewrites/--revises/--judges).
    Raises ValueError with an actionable message on an unknown round/version/index.
    The grammar is documented on judge_item_parts().
    """
    spec = str(spec or "").strip()
    if not spec or spec.lower() == JUDGES_ENABLED_ALL:
        return set()
    out = set()
    for item in [i for i in re.split(r"[,\s]+", spec) if i]:
        r, vid, k = judge_item_parts(item)
        rs = [r] if r is not None else list(range(1, int(rounds) + 1))
        matched = False
        for rr in rs:
            if not (1 <= rr <= int(rounds)):
                raise ValueError(f"{item!r}: round {rr} is outside 1..{int(rounds)}")
            pool = list(pool_of(rr))
            js = int(judges_of(rr))
            if vid is not None and vid not in pool:
                if r:                       # an EXPLICIT round must have the version
                    raise ValueError(f"{item!r}: version {vid!r} is not in round {rr}'s judge "
                                     f"field ({', '.join(pool)})")
                continue                    # no round named: it applies where it exists
            if k is not None and not (1 <= k <= js):
                raise ValueError(f"{item!r}: judge index {k} is outside 1..{js} for round {rr} "
                                 f"(--judges)")
            matched = True
            for v in ([vid] if vid else pool):
                for j in ([k] if k else range(1, js + 1)):
                    out.add((rr, v, j))
        if not matched:
            raise ValueError(f"{item!r}: no round of this plan has version {vid!r} "
                             f"(round 1: {', '.join(pool_of(1))})")
    return out


def judge_selection(ctx, r: int) -> set:
    """{(version, judge index)} enabled in round `r`; an empty set = every session."""
    spec = judges_enabled_spec(ctx, r)
    if not spec:
        return set()
    try:
        triples = parse_judges_enabled(spec, config_rounds(ctx),
                                       lambda rr: judgeable_ids(ctx, rr),
                                       lambda rr: round_judges(ctx, rr))
    except ValueError as e:                                     # a hand-edited config
        print(f"[--only judge selection] WARNING: ignoring the selector for round {r} ({e}); every "
              f"configured judge session will run")
        return set()
    return {(str(v), int(k)) for rr, v, k in triples if int(rr) == int(r)}


def judge_enabled(ctx, r: int, vid: str, judge_index: int) -> bool:
    """Does judge session (round, version, index) run under the `--only` selector?"""
    sel = judge_selection(ctx, r)
    return not sel or (str(vid), int(judge_index)) in sel


def enabled_judges(ctx, r: int, vid: str) -> int:
    """How many judge sessions are enabled for one version (an int, never < 0)."""
    sel = judge_selection(ctx, r)
    if not sel:
        return int(round_judges(ctx, r))
    return len({k for v, k in sel if v == str(vid)})


def judges_enabled_note(ctx, r: int) -> str:
    """A short, printable description of the selector in force for round `r`."""
    spec = judges_enabled_spec(ctx, r)
    if not spec:
        return JUDGES_ENABLED_ALL
    sel = judge_selection(ctx, r)
    return f"{spec} ({len(sel)} session(s) enabled)" if sel else spec


def round_judges(ctx, r: int) -> int:
    """Judge sessions per version for round `r` (`--judges` is a per-round list).

    A decided round's RECORDED plan wins, exactly like round_counts(): `decide`
    must recompute the stored panel's expectation from the plan that produced it,
    so a later edit of the config can never turn a complete panel into a
    "stale --judges value" gap.
    """
    try:
        plan = (ctx.round_get(int(r)) or {}).get("plan") or {}
    except Exception:                                        # noqa: BLE001
        plan = {}
    if is_int(plan.get("judges")):
        return max(0, int(plan["judges"]))
    rounds = config_rounds(ctx)
    return int(counts_of(getattr(ctx, "cfg", None), "judges",
                         rounds)[round_index(r, rounds)])


def round_integrators(ctx, r: int) -> int:
    """The integrator bitmask of round `r` (the recorded plan wins; see INTEGRATOR_ALL).

    In `revise` champion-selection mode an undecided round plans NO integration
    arm: the promoted version is a2, which no merged candidate can outrank, so
    the integration sessions would be paid for and never consulted. `integrate`
    mode keeps the configured mask (the promoted arm must be part of it; see
    `auto_champion_vid`).
    """
    try:
        plan = (ctx.round_get(int(r)) or {}).get("plan") or {}
    except Exception:                                        # noqa: BLE001
        plan = {}
    if is_int(plan.get("integrators")):
        return max(0, int(plan["integrators"]))
    if champion_select_of(ctx) == "revise":
        return 0
    rounds = config_rounds(ctx)
    return int(masks_of(getattr(ctx, "cfg", None), "integrators",
                        rounds)[round_index(r, rounds)])


def round_review_scope(ctx, r: int) -> str:
    """The review's scope for round `r` (`full` or `formatting-writing`).

    The recorded plan wins (a decided round must re-derive the same review
    contract); otherwise the per-round `review_scope` list from the config,
    extended by repeating its last element exactly like `--rewrites`/`--judges`.
    """
    try:
        plan = (ctx.round_get(int(r)) or {}).get("plan") or {}
    except Exception:                                        # noqa: BLE001
        plan = {}
    scope = str(plan.get("review_scope") or "").strip().lower()
    if scope in REVIEW_SCOPE_VALUES:
        return scope
    rounds = config_rounds(ctx)
    raw = (getattr(ctx, "cfg", None) or {}).get("review_scope")
    if raw is None:
        raw = list(DEFAULTS["review_scope"])
    elif not isinstance(raw, (list, tuple)):
        raw = [raw]
    seq = [str(x).strip().lower() for x in raw if str(x).strip()]
    if not seq:
        seq = ["full"]
    while len(seq) < rounds:
        seq.append(seq[-1])
    value = seq[round_index(r, rounds)]
    if value not in REVIEW_SCOPE_VALUES:
        die(f"pipeline_config.json review_scope entry {value!r} is not one of "
            f"{'|'.join(REVIEW_SCOPE_VALUES)}")
    return value


def scoped_review_checks(scope: str) -> tuple:
    """The check ids a review of this scope must DISPOSE ITSELF (formatting pass)."""
    return FORMATTING_WRITING_CHECKS if scope == "formatting-writing" else ()


def round_pool_ids(m: int, n: int) -> list:
    """The round's pool in canonical order: [a1, w1..wM, a2..a{1+N}]."""
    return ([A1_ID] + [rewrite_vid(k) for k in range(1, int(m) + 1)]
            + [revise_vid(j) for j in range(1, int(n) + 1)])


def round_candidate_ids(m: int, n: int) -> list:
    """Every fresh arm that is eligible to win: the pool minus the base A1,
    plus the integrated candidates."""
    return round_pool_ids(m, n)[1:] + round_integrated_ids(m, n)


def round_integrated_ids(m: int, n: int) -> list:
    """EVERY integrated candidate the pool could produce: i1..iK (K = 1 + M + N).

    This is the full-arm list (used where the pool's shape alone matters, e.g.
    validating a version id). Which of those arms a round actually RUNS is
    decided by its integrator mask -- see round_integrated_run_ids().
    """
    return [integrate_vid(k) for k in range(1, len(round_pool_ids(m, n)) + 1)]


def integrator_arms(m: int, n: int, mask: int) -> list:
    """The 1-based pool positions whose integration arm the mask selects.

    Bit (k-1) of `mask` belongs to the k-th pool member; bits beyond the pool
    size are ignored (so the default 0xFFFFFFFF always means "every applicable
    agent", whatever the round's M and N are).
    """
    pool = round_pool_ids(m, n)
    return [k for k in range(1, len(pool) + 1) if (int(mask) >> (k - 1)) & 1]


def round_integrated_run_ids(ctx, r: int, m: int = None, n: int = None) -> list:
    """The integrated candidates round `r` really produces, in pool order.

    A decided round's own plan wins ("integrated" was frozen when the round was
    decided); otherwise the configured per-round integrator mask decides. An
    empty list means the round runs no integration at all (mask 0, or every
    applicable bit clear).
    """
    try:
        plan = (ctx.round_get(int(r)) or {}).get("plan") or {}
    except Exception:                                        # noqa: BLE001
        plan = {}
    recorded = plan.get("integrated")
    if isinstance(recorded, (list, tuple)):
        # An EMPTY recorded list is meaningful: the round ran no integration at
        # all (integrators 0x0), and a later config edit must not resurrect arms
        # the round never produced.
        return [str(v) for v in recorded]
    if m is None or n is None:
        m, n = round_counts(ctx, r)
    return [integrate_vid(k) for k in integrator_arms(m, n, round_integrators(ctx, r))]


def round_produced_ids(ctx, r: int) -> list:
    """Every round-local version round `r` produces: pool + selected integrations."""
    m, n = round_counts(ctx, r)
    return round_pool_ids(m, n) + round_integrated_run_ids(ctx, r, m, n)


def round_candidate_ids_run(ctx, r: int) -> list:
    """Every fresh arm of round `r` that can WIN: the pool minus the base, plus
    the integrated candidates the round actually ran."""
    m, n = round_counts(ctx, r)
    return round_pool_ids(m, n)[1:] + round_integrated_run_ids(ctx, r, m, n)


def round_fresh_ids(m: int, n: int) -> list:
    """Every round-local version the pool can produce: pool + every integration."""
    return round_pool_ids(m, n) + round_integrated_ids(m, n)

SCORE_MIN = -4
SCORE_MAX = 4

# --- judge contracts v2-v4: the GRADED BASIS of every comparison ------------
# The integer score is a claim about a DEFECT CLASS, not a mood. Judges are
# therefore asked for a small, machine-checkable ledger per comparison:
# `basis` names the tier that DECIDES the comparison (the first tier, in
# priority order, whose net is not zero; for a net-zero comparison with rows,
# the highest-priority tier in which the two versions differ), and
# `resolved`/`introduced` list the concrete items on each side (tier, severity,
# one-line evidence). Contract v2 (this constant) makes the orchestrator
# enforce the claim, so a number cannot be written without something to check
# it against. The scale itself stays -4..+4: the production panel (294 directed
# scores, 2026-09-17) used -3..3 and never once used +-4, so widening the range
# would add rungs nobody uses instead of making the existing ones mean
# something; the tier ledger is what fixes the calibration problem.
# v4 (2026-09-30): the tier ORDER is the score. Every tier carries the same FOUR
# severity rungs (minor 1 / major 2 / critical 3 / fatal 4, a distance from
# correct), the tiers are compared LEXICOGRAPHICALLY in
# correctness > preservation > completeness > consistency > writing > formatting
# order, and the first tier whose net is not zero decides the comparison -- a
# lower-priority gain can never offset a higher-priority loss. (v3 summed the
# tiers additively with differentiated caps and made formatting/writing
# MINOR-only; both are superseded.)
# v5 (2026-10-10): the judge runs its OWN DISCOVERY PASS. A judge is completely
# blind to provenance and is handed NO discovery list, so the defect classes the
# frozen checklist does not own are RE-DERIVED by the judge: one bounded pass
# over every side (target + every opponent, same candidates and depth), recorded
# as one disposed file per side under `judge_review/discovery/` and scored as
# normal ledger rows (the finding's own category decides the tier) wherever the
# sides differ. A pass that never ran is indistinguishable from one that found
# nothing, so a missing or empty pass FAILS the run -- otherwise the panel could
# silently ignore that class of findings again, and a version that resolved one
# would not be ranked ahead of the version that still carried it. (v4 and
# earlier: no discovery pass.)
JUDGE_CONTRACT_VERSION = 5
# The scoring classes, in priority order (2026-10-01 calibration):
#   correctness  -- the truth of what is asserted (wrong claim, strength mismatch)
#   preservation -- content lost or invented between the two versions
#   completeness -- an item the artifact promises / the venue requires, missing
#   consistency  -- the same thing said/spelled/numbered two ways; uneven conventions
#   writing      -- prose quality whose meaning survives (Q2-Q12 of the rubric)
#   formatting   -- purely mechanical layout; pre-normalized before the judge sees it
# Rationale: a minor convention drift must not outrank lost content or a missing
# deliverable, and a prose defect whose meaning survives must not outrank (or be
# outranked by) mechanical layout. Meaning-changing rows are refiled to
# correctness by the class rule, so `consistency` here is the residual class.
BASIS_TIERS = ("correctness", "preservation", "completeness", "consistency", "writing",
               "formatting")
BASIS_VALUES = BASIS_TIERS + ("none",)
# FOUR severity rungs, weakest first, and EVERY tier carries all four: minor 1 /
# major 2 / critical 3 / fatal 4. The rungs are a DISTANCE FROM CORRECT (a
# detail / a reported fact / a conclusion / an unusable artifact-or-claim), not
# a factual-only scale, and each tier can reach the whole -4..+4 range.
SEVERITIES = ("minor", "major", "critical", "fatal")
SEVERITY_WEIGHTS = {"minor": 1, "major": 2, "critical": 3, "fatal": 4}
TIER_ROW_WEIGHTS = {tier: dict(SEVERITY_WEIGHTS) for tier in BASIS_TIERS}
# The per-tier net is capped at +-4: the scale's own bound. What keeps
# correctness ahead of consistency is the LEXICOGRAPHIC tier order, not a
# differentiated cap (see derived_comparison_score).
TIER_CAPS = {tier: 4 for tier in BASIS_TIERS}
# The venue LENGTH checks keep their own single-rung policy: a length/caption
# row is a formatting-tier MINOR row, and length can only ever move a comparison
# by at most +-1 (the length rule is a standing exemption, not a scoring tier).
LENGTH_GUARD_CHECKS = ("M18", "M19")
EVIDENCE_MAX_WORDS = 25

# Caption cap for the pipeline's OWN extra check (id M18).
#
# Provenance, stated honestly: this cap is NOT part of the master revision
# prompt and NOT part of either skill (in the skills, M18 is the first number
# reserved for discovery proposals). It is a pipeline SUGGESTION, and it is
# exactly that -- a suggestion: an over-limit caption is REPORTED (as an M18
# formatting item) and never enforced. It can never make a version ineligible,
# can never be the reason a round falls back to its base, and never fails a
# decision. That is why the default is 0 (no caption cap at all): an operator
# who never asked for this pipeline-imposed rule gets no part of it, exactly as
# the master prompt's cover-letter 300-500 word rule is carried as a flaggable
# formatting item and never as a gate.
#
# FIGURE_CAPTION_WORD_LIMIT is the conventional suggested value an operator can
# opt into with `setup --caption-limit 300`; DEFAULT_CAPTION_LIMIT is what the
# pipeline uses when nothing was configured (no suggestion, nothing reported).
FIGURE_CAPTION_WORD_LIMIT = 300
DEFAULT_CAPTION_LIMIT = 0


# ---- The venue's own length limits, relaxed by this pipeline (check id M19)
#
# The numbers come from the configured venue profile (`length_limits` in
# venue_profiles/<id>.json), not from this file. The shipped
# `nature-biotechnology` profile carries the limits this pipeline originally
# hard-coded -- its content-types table states, for an ARTICLE:
#   * abstract  -- up to 150 words, unreferenced;
#   * main text -- up to 3,000 words, EXCLUDING abstract, Methods, references
#                  and figure legends.
# They are applied RELAXED by the operator's margins (NBT: +10% on the
# abstract, +25% on the main text). The cap is the largest INTEGER word count
# that stays inside the relaxation (floor of base*factor): 150*1.10 = 165 and
# 3000*1.25 -> exactly 3,750. A submission of another content type
# (Resource, Brief Communication, ...) takes THAT type's numbers from the same
# venue table with the same two margins; the prompts require the base and its
# source to be named in the artifact.
#
# A profile may also set NO limits (base and relaxation null, as the shipped
# `generic` profile does): the counts are still enumerated and the stage names
# the limit the target journal's own guidelines state, but this pipeline has no
# cap to compare against, so nothing can be "over the cap" here.
#
# The constants below are the shipped nature-biotechnology profile in its old
# module-level spelling, kept for tools and tests that import them; every stage
# reads `length_limits(venue_profile)` instead.


def lenient_word_limit(base: int, factor: float) -> int:
    """The largest integer word count within `base` words relaxed by `factor`."""
    # floor(base*factor), tolerant of the float representation error that made
    # "100 words +15%" 114.99999999999999 -> 114 instead of 115.
    return math.floor(float(base) * float(factor) + 1e-9)


def _builtin_default_venue_object() -> VenueProfile:
    """The module-level default profile, constructed without ever bricking the CLI.

    An invalid SHIPPED default profile -- e.g. one an `add-venue` run wrote
    before this guard existed -- must not make every command, including
    `set-venue`/`status`, die at import. Fall back to the embedded literal and
    say why so the operator can repair the file.
    """
    try:
        return VenueProfile(BUILTIN_VENUE_PROFILES[DEFAULT_VENUE], origin="built-in")
    except (VenueProfileError, ValueError, KeyError, TypeError) as e:
        print(f"[venue] WARNING: the default profile does not validate ({e}); using the "
              f"built-in fallback rules. Repair {VENUE_PROFILES_DIRNAME}/"
              f"{DEFAULT_VENUE}{VENUE_PROFILE_SUFFIX} (or the venue store copy).",
              file=sys.stderr)
        return VenueProfile(copy.deepcopy(_DEFAULT_VENUE_PROFILE), origin="built-in")


_DEFAULT_VENUE_OBJ = _builtin_default_venue_object()
_DEFAULT_LIMITS = _DEFAULT_VENUE_OBJ.length_limits()
DEFAULT_ARTICLE_ABSTRACT_WORDS = _DEFAULT_LIMITS["abstract"]["base"]
DEFAULT_ARTICLE_MAIN_TEXT_WORDS = _DEFAULT_LIMITS["main text"]["base"]
ABSTRACT_RELAXATION = _DEFAULT_LIMITS["abstract"]["relaxation"]
MAIN_TEXT_RELAXATION = _DEFAULT_LIMITS["main text"]["relaxation"]
DEFAULT_ARTICLE_ABSTRACT_CAP = _DEFAULT_LIMITS["abstract"]["cap"]
DEFAULT_ARTICLE_MAIN_TEXT_CAP = _DEFAULT_LIMITS["main text"]["cap"]
DEFAULT_LENGTH_LIMITS_SOURCE = _DEFAULT_VENUE_OBJ.length_limits_source
COVER_LETTER_MIN_WORDS = _DEFAULT_LIMITS["cover letter"]["min"]
COVER_LETTER_MAX_WORDS = _DEFAULT_LIMITS["cover letter"]["max"]
COVER_LETTER_SOURCE = _DEFAULT_LIMITS["cover letter"]["source"]
# An explicitly configured TOTAL-content budget for the letter (salutation,
# body, disclosures and signature), unlike the 300-500 persuading-part
# preference. None means the profile records no such cap.
COVER_LETTER_TOTAL_MAX_WORDS = _DEFAULT_LIMITS["cover letter"].get("total_max")


def length_limits(profile=None) -> dict:
    """The pipeline's lenient caps for the abstract and the main text.

    Without an argument this is the DEFAULT venue's rule set (the behaviour of
    every call site written before venues existed); a stage passes its root's
    `VenueProfile` instead, so a venue change moves the numbers with it.
    """
    prof = profile if isinstance(profile, VenueProfile) else default_venue_profile()
    return prof.length_limits()


def length_limits_source(profile=None) -> str:
    """The provenance string the M19 artifact and the scans carry."""
    prof = profile if isinstance(profile, VenueProfile) else default_venue_profile()
    return prof.length_limits_source


def relaxation_note(profile=None) -> str:
    """One clause describing how the venue's own limits are relaxed here."""
    limits = length_limits(profile)
    parts = []
    for key, label in (("abstract", "abstract"), ("main text", "main text")):
        spec = limits[key]
        if spec.get("base") is None:
            continue
        margin = int(round((float(spec["relaxation"]) - 1.0) * 100))
        parts.append(f"+{margin}% on the {label} (<= {spec['cap']} words)")
    if not parts:
        return ("This venue profile sets no abstract/main-text cap: the counts are recorded "
                "for the author to compare with the target journal's own guidelines")
    return "The venue's own limits are relaxed by this pipeline (" + "; ".join(parts) + ")"


def caption_limit_of(ctx) -> int:
    """The configured (suggested) caption cap; 0 = no caption rule at all.

    A cap the OPERATOR chose (`setup --caption-limit N`, recorded with
    `caption_limit_source: "operator"`) wins; otherwise the VENUE PROFILE's own
    default applies, so a venue that publishes a legend limit carries it into
    the run and a venue change moves the cap with it.
    """
    cfg = getattr(ctx, "cfg", None) or {}
    raw = cfg.get("caption_limit", None)
    source = str(cfg.get("caption_limit_source") or "operator").strip().lower()
    if raw is None or source != "operator":
        prof = venue_profile_of(ctx, required=False)
        return prof.caption_default if prof is not None else DEFAULT_CAPTION_LIMIT
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CAPTION_LIMIT
    return max(0, v)


def zotero_mode_of(ctx) -> str:
    """The configured Zotero tooling policy (off|read|edit|apply).

    An unknown value falls back to the DEFAULT mode, never to the most
    permissive one: a hand-edited pipeline_config.json must not be able to
    widen what the agent sessions may do to the operator's library.
    """
    v = str((getattr(ctx, "cfg", None) or {}).get("zotero", DEFAULT_ZOTERO_MODE)
            or "").strip().lower()
    return v if v in ZOTERO_MODES else DEFAULT_ZOTERO_MODE


def placeholder_lookup_of(ctx) -> str:
    """`off` | `online`: may the orchestrator resolve searchable markers itself?"""
    v = str((getattr(ctx, "cfg", None) or {}).get("placeholder_lookup",
                                                  DEFAULT_PLACEHOLDER_LOOKUP)
            or "").strip().lower()
    return v if v in PLACEHOLDER_LOOKUP_MODES else DEFAULT_PLACEHOLDER_LOOKUP


def audit_enabled(ctx) -> bool:
    """Is the round's auditor stage part of the plan?"""
    v = str((getattr(ctx, "cfg", None) or {}).get("audit", DEFAULT_AUDIT)
            or "").strip().lower()
    return (v if v in AUDIT_MODES else DEFAULT_AUDIT) == "on"


def artifact_policy_of(ctx) -> str:
    """`on` | `fix` | `off` -- what a decision-artifact problem does to an attempt.

      on  (default) the attempt FAILS: a decision table closed with one blanket
          sentence, or left with empty cells, is an unfilled artifact (the
          pipeline lost 96 rows to exactly that in a real run).
      fix the orchestrator spends ONE scoped repair session on the failed
          attempt's decision tables -- it may only fill cells, from evidence
          already in the rows -- and then re-runs the SAME postcheck. A repair
          that does not clear the problem is still a failed attempt and the
          normal retry policy takes over. Nothing outside `review/artifacts/`
          and `review/work/` may change, and no row may be added, removed,
          reordered or re-worded (verified byte-for-byte afterwards).
      off recorded as a warning (advisory), never a failure.

    The only accepted spellings are ARTIFACT_POLICIES; the removed boolean
    `strict_artifacts`/`strict_dispositions` keys are not read at all.
    """
    cfg = getattr(ctx, "cfg", None) or {}
    raw = str(cfg.get("artifact_policy") or "").strip().lower()
    return raw if raw in ARTIFACT_POLICIES else DEFAULT_ARTIFACT_POLICY


def strict_dispositions(ctx) -> bool:
    """Does a decision-artifact problem FAIL the attempt (unless repaired)?

    Both `on` and `fix` fail an attempt that leaves the tables unfilled -- under
    `fix` the failure first goes to one scoped repair session, whose own
    postcheck is judged by this same rule, so a repair cannot wave a table
    through. `off` records the detector's report as a warning instead (the
    report is recorded either way, and `decide --residual-gate` can still refuse
    to certify the result).
    """
    return artifact_policy_of(ctx) != "off"


def artifact_repair_enabled(ctx) -> bool:
    """May a repairable artifact-quality failure go to a scoped repair session?"""
    return artifact_policy_of(ctx) == ARTIFACT_POLICY_FIX

# The user replaced the master prompt's blanket abstract/main-text exemption
# with the journal's own limits relaxed by fixed margins (see the constants
# above). The rule travels with every prompt through STANDING_EXEMPTIONS, and
# the M19 mandates below give each stage its concrete job (sweep, compress,
# port, surface, judge). Like the caption suggestion and the cover-letter rule
# it is a flaggable FORMATTING item, never a gate.
def _as_profile(profile=None) -> VenueProfile:
    """Accept a VenueProfile, a pipeline root context, or nothing (the default)."""
    if isinstance(profile, VenueProfile):
        return profile
    if profile is not None and hasattr(profile, "cfg"):
        prof = venue_profile_of(profile, required=False)
        if prof is not None:
            return prof
    return default_venue_profile()


def _indefinite(noun: str) -> str:
    """"a X" / "an X" for the venue short names the prompts interpolate."""
    text = str(noun or "venue").strip()
    # An initialism takes the article its SPOKEN letters start with ("an NBT",
    # "an F1000", but "a GET"), a word takes the ordinary vowel test.
    # A leading capital followed by capitals OR digits is read as letters
    # ("NBT", "F1000"): "1000".isupper() is False, which made F1000 take "a".
    initialism = (len(text) > 1 and text[0].isupper()
                  and (text[1:].isupper() or text[1:2].isdigit()))
    vowel = (text[0] in "AEFHILMNORSX") if initialism else (text[:1].lower() in "aeiou")
    return ("an " if vowel else "a ") + text


def _article_phrase(profile: VenueProfile) -> str:
    """`an NBT Article`-style phrase: the profile's label + its article type."""
    prof = _as_profile(profile)
    art = str(prof.article_type or "Article").strip()
    label = prof.label
    return f"{_indefinite(label)} {art}"


def _caps_clause(profile: VenueProfile, *, article: bool = False) -> str:
    """The M19 mandate's cap clause, from the venue profile's own numbers.

    A profile without limits (the shipped `generic` one) gets a sentence that
    says so and hands the comparison to the target journal's own guidelines --
    never a number this pipeline invented.
    """
    limits = _as_profile(profile).length_limits()
    abstract, main = limits["abstract"], limits["main text"]
    if abstract["cap"] is None and main["cap"] is None:
        return ("this venue profile sets no abstract or main-text cap, so state the limit the "
                "target journal's own guidelines give and its source in the artifact")
    parts = []
    if abstract["cap"] is not None:
        parts.append(f"abstract <= {abstract['cap']} words")
    if main["cap"] is not None:
        parts.append(f"main text <= {main['cap']} words")
    clause = "; ".join(parts)
    if article:
        clause += (f" for {_article_phrase(profile)}, "
                   f"{_main_text_counting_short(profile)}")
    return clause


def _cover_bound_text(lo, hi) -> str:
    """A cover-letter preference in words, one-sided bounds included.

    `300-500 words`, `at most 200 words`, `at least 300 words`, or "" when the
    profile states neither side. The row note and the decision line both read
    this, so a one-sided profile can never render as "None-200" or as "no
    preference" while `within_preference` is false.
    """
    if lo is None and hi is None:
        return ""
    if lo is None:
        return f"at most {hi} words"
    if hi is None:
        return f"at least {lo} words"
    return f"{lo}-{hi} words"


def _cover_preference_clause(profile: VenueProfile) -> str:
    """The cover-letter preference as words (`300-500`, `at most 200`, `at least 300`).

    A venue may state only one side (Frontiers states a 200-word maximum for the
    submission system's scope statement); the clause then carries that side alone.
    """
    cover = _as_profile(profile).length_limits()["cover letter"]
    return _cover_bound_text(cover.get("min"), cover.get("max"))


def cover_letter_guidance(profile=None) -> dict:
    """The venue's RECORDED cover-letter guidance, in one shape every prompt reads.

    `preference` is the persuading-part range/one-sided bound ("" when the
    profile states none), `total_max` the operator's total-content cap (None
    when unset), and `source` the profile's own quoted basis -- the guideline
    text a cover letter falls back to when the venue ships no cover-letter
    template. Never invented: every field comes from the resolved profile.
    """
    prof = _as_profile(profile)
    try:
        lim = prof.length_limits().get("cover letter") or {}
    except Exception:                                          # noqa: BLE001 -- never gate
        lim = {}
    return {"preference": _cover_preference_clause(prof),
            "total_max": lim.get("total_max"),
            "source": str(lim.get("source") or "").strip()}


def cover_letter_guidance_clause(guide: dict) -> str:
    """One readable sentence-fragment of `cover_letter_guidance` ("" when empty)."""
    guide = guide or {}
    bits = []
    if guide.get("preference"):
        bits.append(f"the persuading part is {guide['preference']}")
    if guide.get("total_max") is not None:
        bits.append(f"its TOTAL content (salutation, body, disclosures and signature) "
                    f"must stay within {guide['total_max']} words (the operator's cap)")
    if guide.get("source"):
        bits.append(f"the recorded basis: {guide['source']}")
    return "; ".join(bits)


# The section kinds the M19 renderers NAME when they describe a counting rule:
# the four that actually change a main-text word count. Back-matter kinds
# (acknowledgements, funding, ...) end the span too, but naming all ten in every
# prompt bloats it without telling the agent anything it must decide.
_NAMED_COUNTING_KINDS = (("abstract", "the abstract"), ("methods", "Methods"),
                         ("references", "references"),
                         ("figure-legends", "figure legends"),
                         ("table-captions", "table captions"))
# Back-matter kinds are named separately: a venue whose ONLY exclusions are
# these still leaves six sections out (the NBT Brief Communication), so the
# renderer must not say "nothing EXCLUDED" for it.
_BACK_MATTER_COUNTING_KINDS = (
    ("acknowledgements", "acknowledgements"),
    ("author-contributions", "author contributions"),
    ("data-availability", "data availability"),
    ("competing-interests", "competing interests"),
    ("funding", "funding"),
    ("supplementary", "supplementary material"),
)


def _join_words(items) -> str:
    items = list(items)
    if not items:
        return "nothing"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _back_matter_counting_text(excludes) -> str:
    """`; acknowledgements ... are outside the count` ("" when none is out)."""
    out = [label for kind, label in _BACK_MATTER_COUNTING_KINDS if kind in excludes]
    if not out:
        return ""
    return ("; " + _join_words(out)
            + (" is" if len(out) == 1 else " are") + " outside the count")


def main_text_counting_text(profile=None) -> str:
    """One clause naming what the venue's main-text count leaves OUT and IN.

    The counting convention is profile data (M19): Nature Biotechnology's
    Article excludes the abstract, Methods, references and figure legends,
    Frontiers counts Methods, and NBT's Brief Communication counts the abstract,
    references and figure legends too. Every M19 renderer that describes the
    counted span reads this clause, so a prompt can never tell an agent to count
    the NBT Article way under another venue's or profile's own convention.
    """
    prof = _as_profile(profile)
    excludes = set(prof.main_text_excludes())
    left_out = [label for kind, label in _NAMED_COUNTING_KINDS if kind in excludes]
    inside = [label for kind, label in _NAMED_COUNTING_KINDS if kind not in excludes]
    back_out = _back_matter_counting_text(excludes)
    if not inside:
        return ("the main text is counted with " + _join_words(left_out)
                + " EXCLUDED" + back_out)
    left = (_join_words(left_out) if left_out
            else "no named front/mid section")
    return ("the main text is counted with " + left + " EXCLUDED, and with "
            + _join_words(inside) + " INSIDE the count" + back_out)


def _main_text_counting_short(profile=None) -> str:
    """The counting convention as a compact prepositional phrase.

    `main_text_counting_text()` is a full sentence for the length rule and the
    review mandate; this is the form the cap clause needs ("... main text
    <= 12,000 words for a Frontiers Original Research, with the abstract,
    references and figure legends excluded, and Methods counted inside").
    """
    prof = _as_profile(profile)
    excludes = set(prof.main_text_excludes())
    left_out = [label for kind, label in _NAMED_COUNTING_KINDS if kind in excludes]
    inside = [label for kind, label in _NAMED_COUNTING_KINDS if kind not in excludes]
    back_out = [label for kind, label in _BACK_MATTER_COUNTING_KINDS if kind in excludes]
    parts = []
    if left_out:
        parts.append(f"with {_join_words(left_out)} excluded")
    if inside:
        parts.append(f"with {_join_words(inside)} counted inside")
    if back_out:
        parts.append(f"with {_join_words(back_out)} outside")
    return ", and ".join(parts) if parts else "with nothing excluded"


def length_rule_text(profile=None) -> str:
    """The M19 length rule, rendered from the venue profile (see M19 below).

    The pipeline's own rule is venue-agnostic; the NUMBERS and their provenance
    come from the profile, so a venue change moves the caps with it.
    """
    prof = _as_profile(profile)
    limits = prof.length_limits()
    abstract, main = limits["abstract"], limits["main text"]
    source = prof.length_limits_source
    counting_clause = main_text_counting_text(prof)
    counting_sentence = counting_clause[:1].upper() + counting_clause[1:]
    if abstract["cap"] is None and main["cap"] is None:
        limits_para = (
            f"      carries): this venue profile publishes no abstract or main-text number for\n"
            f"      {_article_phrase(prof)}, so there is no relaxed cap to apply here. The limits "
            f"that DO\n"
            f"      apply are the target journal's own: every stage COUNTS the abstract and "
            f"the main text, and each\n"
            f"      artifact names the limit it applied and the source it came from ({source}).")
    else:
        cap_bits = []
        if abstract["cap"] is not None:
            margin = int(round((float(abstract["relaxation"]) - 1.0) * 100))
            cap_bits.append(f"the abstract <= {abstract['cap']} words"
                            + ("" if margin == 0 else
                               f" (base {abstract.get('base')} +{margin}% = {abstract['cap']})"))
        if main["cap"] is not None:
            margin = int(round((float(main["relaxation"]) - 1.0) * 100))
            cap_bits.append(f"the main text <= {main['cap']} words"
                            + ("" if margin == 0 else
                               f" (base {main.get('base')} +{margin}% = {main['cap']})"))
        limits_para = (
            f"      carries): the limits below DO apply in their RELAXED form. For "
            f"{_article_phrase(prof)} the allowed\n"
            f"      caps are {' and '.join(cap_bits)} ({source}). The relaxed cap is the ONLY\n"
            f"      limit this pipeline applies to the manuscript; it does not separately "
            f"enforce a base number.\n"
            f"      {counting_sentence}. This run is submitted as "
            f"{_article_phrase(prof)}:\n"
            f"      the venue profile's article-type table carries every type the venue "
            f"publishes, and\n"
            f"      `set-article-type` selects which one this is. A type the profile carries no "
            f"number for\n"
            f"      is COUNTED and named from the venue's own table, never measured against "
            f"these caps; a\n"
            f"      submission of another content type uses that type's own caps and "
            f"margins from\n"
            f"      the same venue table. A section within its relaxed cap is within the "
            f"limit; a section\n"
            f"      over it is reported and compressed by redundancy only, never by deleting "
            f"content.")
    cover_clause = _cover_preference_clause(prof)
    cover_source = str(limits['cover letter'].get('source') or '')
    cover_is_master = cover_source.lower().startswith("master-prompt preference")
    cover_origin = ("The master prompt's own preference is therefore applied as written: "
                    if cover_is_master else
                    "The preference recorded by the venue profile is therefore applied as written: ")
    cover_total = limits['cover letter'].get('total_max')
    cover_total_clause = (
        f"is a SEPARATE cap of {cover_total} words (the operator's default): trim the "
        f"non-persuading\n      boilerplate first, never a claim about the work."
        if cover_total is not None else
        "is counted and recorded, but this profile configures no TOTAL-content cap, so "
        "no\n      total-word limit is applied to it.")
    if cover_clause:
        cover_para = (
            f"    * THE COVER LETTER — A RECORDED PREFERENCE, NOT A COVER-LETTER WORD LIMIT. "
            f"Provenance, stated honestly:\n"
            f"      {limits['cover letter'].get('source') or 'the venue profile states no official cover-letter limit.'}\n"
            f"      {cover_origin}the "
            f"PERSUADING part (the body explaining the\n"
            f"      work's importance and its suitability for the journal -- excluding the "
            f"salutation, the\n"
            f"      signature block, and required disclosures such as related manuscripts, prior "
            f"editor\n"
            f"      discussions, double-anonymized author details and reviewer suggestions) should "
            f"be\n"
            f"      {cover_clause}. A persuading part outside that\n"
            f"      range is a MINOR formatting item (check id M19), reported and never gated; it "
            f"is never\n"
            f"      presented as a journal requirement, and it is never \"fixed\" by deleting "
            f"content. Count it\n"
            f"      with the pipeline's word rule. The letter's TOTAL content -- salutation, "
            f"body, disclosures\n"
            f"      and signature -- {cover_total_clause}")
    else:
        cover_para = (
            f"    * THE COVER LETTER — NO COVER-LETTER PREFERENCE IS CONFIGURED: this venue\n"
            f"      profile states no cover-letter word limit or preference, so the letter's length\n"
            f"      is counted and recorded but never flagged, scored or cut for length. Its TOTAL\n"
            f"      content {cover_total_clause}")
    return f"""ABSTRACT / MAIN-TEXT LENGTH — THE JOURNAL'S LIMITS, RELAXED BY THIS PIPELINE:
    * This REPLACES the blanket "abstract/main-text length is exempt" standing exemption (the same
      exemption the skills inherit, and the wording the attached master-prompt excerpt below no longer
{limits_para}
    * COUNTING RULE, for every word count in this pipeline: a word is a maximal run of NON-SPACE
      characters, with a newline treated as space. "state-of-the-art" is ONE word, "2026" is ONE
      word, and an abbreviation with an inner space ("et al.") is two. Do not split hyphenated
      compounds and do not normalise anything else away.
    * An over-limit section is a CATEGORY-4 (technical formatting) item, check id M19: it is
      compressed by removing redundancy, repeated statistics and NON-MEANING-BEARING hedging
      ONLY -- never by deleting scientific content, claims, limitations, data, accession numbers
      or needed methodological detail. A hedge that carries the claim's own strength (a
      limitation, an uncertainty the evidence supports, a result reported as uncertain because
      it is) is CONTENT: stripping it would turn an accurate claim into an overclaim, so it
      stays. Never flag UNDER-length abstract or main text (the pipeline relaxes upper limits only and
      invents no minimum; the cover-letter preference is the one configured floor), never make a length-driven cut to text that is within the cap, and never
      strengthen or weaken a claim in either direction to reach one.
{cover_para}
    * LENGTH IS NEVER A RANKING OR CANDIDATE-ELIGIBILITY GATE: no version is made ineligible,
      failed, rejected, de-ranked or re-ordered as a whole because of a word count, and length may
      only ever enter a comparison through the FORMATTING tier (a version within the cap may be
      preferred to one that is over it by at most +/-1; two versions both over, or both within,
      are indistinguishable on this check and score 0). A FINAL PUBLISHED package that is still
      over the venue's relaxed cap (or the cover-letter total cap) is NOT submission-ready: the
      readiness verdict names the section and the cap, while the highest-ranked version keeps
      its place.
    * A section that cannot be brought within the cap without losing content is left as it is and
      handed to the author as a manual item, exactly like an incompressible caption."""


def standing_exemptions_text(profile=None) -> str:
    """The standing exemptions block, with this venue's length and legend rules."""
    prof = _as_profile(profile)
    cover_clause = _cover_preference_clause(prof)
    cover_total = prof.length_limits()["cover letter"].get("total_max")
    total_pref = (
        f"must stay within {cover_total} words (the operator's default cap; a profile may\n"
        f"    override it)"
        if cover_total is not None else
        "is counted and recorded, but this profile configures no TOTAL-content cap, so no\n"
        "    total-word limit is applied")
    total_plain = (
        f"must stay within {cover_total} words (the operator's default cap)"
        if cover_total is not None else
        "is counted and recorded with no total-word cap (this profile configures none)")
    cover_bullet = (
        f"  * The master prompt's COVER-LETTER rule (the persuading part must be {cover_clause})\n"
        f"    stays a flaggable formatting item: report it, never gate on it. The LETTER ITSELF\n"
        f"    must render to at most TWO pages (a third page is a Major formatting defect) AND\n"
        f"    its TOTAL content -- salutation, body, disclosures and signature -- {total_pref}.\n"
        f"    Trim the non-persuading boilerplate first, never a claim about\n"
        f"    the work, and the page count comes from a render, never from the cached document\n"
        f"    property."
        if cover_clause else
        "  * This venue profile states no COVER-LETTER word rule: the letter's length is recorded\n"
        f"    and reported, never gated and never cut. The LETTER itself must still render to at\n"
        f"    most TWO pages (a third page is a Major formatting defect), measured from a render,\n"
        f"    and its TOTAL content {total_plain}.")
    caption_source = (prof.captions.get("source")
                      or "this venue profile states no figure-legend length rule")
    return f"""Standing exemptions and explicit limits (apply to every mode, always):
  * @@LENGTH_RULE@@
{cover_bullet}
  * FIGURE-LEGEND LENGTH (check id M18) is ALWAYS enumerated: {caption_source}.
    Every stage therefore counts every legend's words;
    when a cap IS configured -- the operator's `--caption-limit N` override, or
    the venue profile's own published default -- that cap is used as the
    pipeline's proxy for the venue's limit and an over-cap legend is a
    reportable formatting item; only when neither is present are the counts
    recorded and the comparison with the venue's limit handed to the author as
    a manual item. Nothing is ever made ineligible, ranked down, failed or rejected
    because of a legend's word count, and length is never "fixed" by deleting
    scientific content.
  * Speculative "possible AI-generated" content may be flagged ONLY with
    concrete evidence, always labeled "possible", never as a definitive
    accusation, and it can never decide a comparison on its own.""".replace(
    "@@LENGTH_RULE@@", length_rule_text(prof))


# Inserted (with the limit substituted) into every prompt that produces or
# judges content, next to the standing exemptions.
def caption_rule_template(profile=None, limit=None) -> str:
    """The M18 caption rule, with @@CAPTION_LIMIT@@ left for the caller to fill.

    `limit` is the EFFECTIVE cap the caller is about to substitute. It is what
    distinguishes the venue's own published number from an operator override:
    with `--caption-limit 300` on a venue publishing 250, the old renderer still
    called 300 "the venue's own limit" (Rule 3).
    """
    prof = _as_profile(profile)
    captions = prof.captions
    published = captions.get("published_limit")
    operator_override = bool(published is not None and limit is not None
                             and int(limit) != int(published))
    if published and not operator_override:
        origin = (f"Origin, stated honestly: {prof.label} publishes a figure-legend limit of "
                  f"{published} words ({captions.get('source') or 'venue profile'}). "
                  f"@@CAPTION_LIMIT@@ words is therefore the venue's own limit as carried by this "
                  f"pipeline's profile; the master prompt and both skills do not state a number. "
                  f"Apply it exactly as written here and never claim the venue set a number it "
                  f"did not.")
    elif published:
        origin = (f"Origin, stated honestly: {prof.label} publishes a figure-legend limit of "
                  f"{published} words ({captions.get('source') or 'venue profile'}). "
                  f"@@CAPTION_LIMIT@@ words is NOT that number: it is the OPERATOR's proxy "
                  f"(`--caption-limit N`), chosen for this run and presented as a pipeline "
                  f"suggestion only. Never call it the venue's limit; the venue states "
                  f"{published} words.")
    else:
        origin = (f"Origin, stated honestly: {captions.get('source') or 'this venue profile states no figure-legend length rule'}. "
                  f"@@CAPTION_LIMIT@@ words is therefore the ORCHESTRATION PIPELINE's proxy\n"
                  f"    for the venue's limit, chosen by the operator at setup (`--caption-limit N`); "
                  f"the master\n"
                  f"    prompt and both skills do not state a number. Apply the proxy exactly as "
                  f"written here and\n"
                  f"    never claim the venue itself set it.")
    return f"""FIGURE-LEGEND LENGTH (check id M18; applies in every mode, including judging):
  * {origin}
  * IT IS NEVER A GATE. An over-cap legend is reported (check id M18) and,
    where it can be done by removing redundancy only, compressed -- and that is all. It must
    NEVER make a version ineligible for a round, never lower a ranking, never fail a run or a
    decision, and never be presented as a requirement. Leaving a caption over the suggested
    length is an acceptable outcome; deleting content to satisfy a word count is not.
  * Where it applies: every figure caption / legend. Count the legend text as a reader sees it
    (the leading "Figure N |" label and title words count; the labels drawn inside the artwork
    do not). If a package has no figure captions, record that as a disposition rather than
    inventing one.
  * An over-limit caption is a reportable FORMATTING item, not a length-exemption case: report it
    (check id M18) and, when the redundancy can be removed without losing anything, do so --
    NEVER by deleting scientific content, claims, limitations, or necessary methodological
    detail. A cut that removes content is a preservation defect and is worse than the long
    caption. A length/caption row is a formatting-tier MINOR row -- the venue's relaxed margins
    make slight over-length intended, so it is never Major/Critical/Fatal: FORMATTING is the
    lowest scoring tier, so a length row can decide only when every other tier (including
    writing) is zero; it must never inflate a candidate's critical-finding count.
  * If a caption cannot be brought under @@CAPTION_LIMIT@@ words without losing content, do not
    guess and do not cut: leave the caption as it is and say so explicitly, listing it for manual
    action (revise: MANUAL_STEPS.md; review: the manual-verification list; judge: the comparison
    reason/notes).
  * Precedence, stated so you do not have to guess: the master prompt's blanket rule against
    length-driven cuts is narrowed by this pipeline in exactly TWO places:
    the redundancy-only compression of figure captions (this suggestion, check id M18) and the
    redundancy-only compression of an over-cap abstract or main text (the length rule, check id
    M19). The cover letter keeps that rule for its persuading part; only a profile-configured
    TOTAL-content cap may authorise trimming non-persuading boilerplate (M19).
  * When judging, caption length sits in the FORMATTING tier of the priority order
    (correctness > preservation > completeness > consistency > writing > formatting). A
    caption-length difference alone never justifies a score beyond +/-1, and two versions that are
    BOTH over the limit are indistinguishable on this check (score 0). Word-count arithmetic is never a
    substitute for judging content, and a version over the suggested length is still fully
    eligible to win the round."""

# Used instead of CAPTION_RULE when no cap is configured (`--caption-limit 0`,
# the default for a venue that publishes no number). The venue's requirement
# still holds, so the legends are STILL enumerated; only the proxy cap and any
# length-based compression/scoring are absent.
def caption_report_text(profile=None) -> str:
    """The no-cap M18 rule: enumerate every legend, compress and score none."""
    prof = _as_profile(profile)
    captions = prof.captions
    published = captions.get("published_limit")
    source = (captions.get("source")
              or "this venue profile states no figure-legend length rule")
    if published:
        # A disabled cap on a PUBLISHING venue is not "the venue publishes no
        # limit": the venue's number is known and the operator switched the
        # proxy off for this run. Say exactly that.
        origin = (f"{source}. {prof.label} publishes a figure-legend limit of {published} "
                  f"words, but the OPERATOR DISABLED the proxy cap for this run "
                  f"(`--caption-limit 0`), so the pipeline applies no number; the author "
                  f"compares each recorded legend with the venue's {published}-word limit")
        disposition = (f"recorded — the operator disabled the cap this run; {prof.label} "
                       f"publishes {published} words and the author compares it in Word")
    else:
        origin = (f"{source}, and no proxy cap is\n"
                  f"    configured (`--caption-limit 0`)")
        disposition = ("recorded — the venue's per-type limit is not published; the author "
                       "compares it in Word")
    return f"""FIGURE-LEGEND LENGTH — ENUMERATED, NO CAP CONFIGURED (check id M18):
  * {origin}. Therefore: COUNT every legend's words and
    record them in your own artifact (`judge_review/artifacts/M18_caption_words.md` for a judge
    session), with the disposition
    "{disposition}".
    A legend whose length is obviously inconsistent with its display-item budget still gets a
    normal clarity/formatting finding if it is otherwise defective, but its WORD COUNT alone is
    not a defect here.
  * Do NOT compress, reword, score or rank a legend because of its length while no cap is
    configured, and never make a length-driven cut. Two versions whose legends are
    both long (or both short) are indistinguishable on M18, and a version is never ineligible,
    de-ranked or failed because of a legend's word count."""


# Compatibility constants: the DEFAULT venue's rendering of each block, for the
# skills, tools and tests that import them by name. Every prompt is built with
# the root's own profile (see apply_m19 / apply_m18 / standing_exemptions_text).
LENGTH_RULE = length_rule_text()
STANDING_EXEMPTIONS = standing_exemptions_text()
CAPTION_RULE = caption_rule_template()
CAPTION_RULE_REPORT = caption_report_text()

# The M18 mandate sentences live in the stage directives. There are two states:
# a proxy cap configured by the operator (`--caption-limit N`) and the no-cap
# report state, which still ENUMERATES every legend's word count (the journal's
# requirement stands; only its unpublished number is missing).
M18_REVIEW_SWEEP_ON = """3. The PIPELINE-MANDATED caption sweep M18 (see the caption rule below): enumerate EVERY figure
   caption/legend in the corpus into review/artifacts/M18_caption_words.md, one row per caption
   with its document, caption id, word count, and disposition (OK / over @@CAPTION_LIMIT@@ words ->
   finding id / over the SUGGESTED length but not compressible without losing content -> manual
   verification item), then audit the table row by row. Give M18 its own coverage row, exactly
   like the skill's sweeps. This check is mandatory in every run (the skill's
   references/sweeps.md defines the same sweep). An M18 row is a formatting-tier item and never
   makes a version ineligible: the orchestrator reports caption lengths, it never gates on them.
   M18 is RESERVED by this pipeline for the caption sweep: if your discovery round proposes new
   sweeps, number them from M37 upwards in review/round2/new_sweeps.md. (This pipeline always
   reserves M18 for its caption sweep and M19 for its abstract/main-text length sweep, and M20
   for the OOXML formatting sweep, so proposals start at M37, after the adopted M21-M36. Say so
   in new_sweeps.md so the
   operator can renumber when adopting them into the skill.)"""
M18_REVIEW_SWEEP_REPORT = """3. The PIPELINE-MANDATED legend-length sweep M18 (see the legend rule below; NO cap is
   configured this run): enumerate EVERY figure legend in the corpus into
   review/artifacts/M18_caption_words.md, one row per legend with its document, legend id and
   word count, and the disposition "recorded — no proxy cap is applied this run; the author
   compares the count with the venue's per-type legend limit (the caption rule above states
   whether the venue publishes one)" (or a finding id when the legend is defective for an
   independent reason, for example it explains methods or is unclear). Give M18 its own coverage
   row, exactly like the skill's sweeps. This check is mandatory in every run (the skill's
   references/sweeps.md defines the same sweep), and it never makes a version ineligible: with no
   cap configured the word count alone is not a defect, is never scored and is never "fixed" by
   cutting text.
   M18 is RESERVED by this pipeline for the legend sweep: if your discovery round proposes new
   sweeps, number them from M37 upwards in review/round2/new_sweeps.md (M18, M19 and M20
   are reserved, and M21-M36 are adopted), and say so there so the operator can renumber when
   adopting them into the skill."""
M18_REVISE_RULE_ON = """Figure captions: bring EVERY caption over @@CAPTION_LIMIT@@ words back under the limit by
     removing redundancy, repeated statistics and non-meaning-bearing hedging -- never by deleting
     scientific content, claims, limitations or needed methodological detail, and never by
     stripping a hedge that carries the claim's own strength (that would be an overclaim, not a
     shortening). This is a SUGGESTION, not a gate: a
     caption that cannot be shortened without losing content is left as it is and handed to
     revised/MANUAL_STEPS.md instead of guessing. Record each affected caption in CHANGELOG.md
     (check id M18). M18 is the pipeline's caption sweep; the findings you inherited from Phase 1
     already carry the M18 rows."""
M18_REVISE_RULE_REPORT = """Figure legends (check id M18): no proxy cap is configured for this run, so do NOT change
     legend wording or length for length reasons and never cut a legend. Record each legend's word
     count in CHANGELOG.md and, when a legend is defective for an independent reason (method
     detail, unclear panel description, missing error-bar definition), fix that as the normal
     clarity/formatting finding it is — the word count itself stays a recorded fact for the
     author, who compares it with the venue's own per-type legend limit."""
M18_JUDGE_SWEEP_ON = """PLUS the pipeline-mandated caption sweep M18 (count every figure
   caption's words and record the rows in judge_review/artifacts/M18_caption_words.md). M18 is part
   of the frozen set for every judge session, so do not skip it and do not treat it as optional.
   Enumerate the captions YOURSELF, including unusual forms ("Figure 2(a)", a bare label on its own
   line, a legend split across paragraphs): the orchestrator's code-side scan recognises only
   common patterns and lists anything else as "suspected" -- your M18 artifact is the authoritative
   enumeration, and a caption the code-side scan did not recognise is exactly the kind of miss you
   must not repeat. M18 is a SUGGESTION: an over-limit caption is a formatting-tier MINOR item
   (<= +/-1 -- FORMATTING is the lowest tier, so a length row can decide only when every other
   tier, including writing, is zero), and it never makes a version ineligible."""
M18_JUDGE_SWEEP_REPORT = """PLUS the pipeline-mandated legend sweep M18 (count every figure
   legend's words and record the rows in judge_review/artifacts/M18_caption_words.md). M18 is part
   of the frozen set for every judge session, so do not skip it and do not treat it as optional.
   Enumerate the legends YOURSELF, including unusual forms ("Figure 2(a)", a bare label on its own
   line, a legend split across paragraphs): the orchestrator's code-side scan recognises only
   common patterns and lists anything else as "suspected" — your M18 artifact is the authoritative
   enumeration. NO cap is configured this run, so a legend's word count alone is NOT a scoring
   difference: record the counts and never score a version as better or worse because of legend
   length."""
M18_INTEGRATE_CLAUSE_ON = " plus the pipeline-mandated caption sweep M18"
M18_INTEGRATE_CLAUSE_REPORT = " plus the pipeline-mandated legend sweep M18 (counts only, no cap)"
M18_INTEGRATE_RULE_ON = """Figure captions are a difference class of their own: a caption over @@CAPTION_LIMIT@@ words is a
reportable formatting item (a SUGGESTION, never a gate), so (a)/(b) apply whenever the donor's
caption is within the suggested length and the base's is not, or when the donor compressed an
over-limit caption better without losing content. Copy the donor's wording only when you can verify
it preserves every scientific claim of the base's caption; otherwise compress the base's caption
yourself under the caption rule below, and if it cannot be compressed without losing content,
leave it and record it for manual action. Never reach the suggested length by dropping content."""
M18_INTEGRATE_RULE_REPORT = """Legend LENGTH is not a difference class in this run (no proxy cap is configured): enumerate the
legend word counts for the ledger and the report, but never port, compress, rewrite or score a
legend merely because it is longer or shorter, and never make a length-driven cut. Judge legends
on content and correctness only."""

# ---- M19: the abstract/main-text length sweep (ALWAYS active) ---------------
#
# Unlike the opt-in caption sweep (M18), M19 is always on: the user replaced
# the blanket "abstract/main-text length is exempt" standing exemption with the
# journal's own limits relaxed by +10% (abstract) and +25% (main text). Every
# stage therefore has a job -- the review enumerates and reports, the revision
# and integration stages compress by removing redundancy only, the rewrite
# surfaces without cutting, the judges treat length as formatting-tier evidence.
# Nothing here gates a VERSION's eligibility or ranking: an over-cap section is a
# CATEGORY-4 formatting item. The final PUBLISHED package is separately marked
# not submission-ready when it remains over a configured cap (see package_readiness).
def m19_blocks(profile=None) -> dict:
    """The five M19 mandate sentences, rendered from the venue profile.

    With a cap (the shipped nature-biotechnology profile) the mandates compress
    over-cap sections by redundancy only; with a profile that states no cap
    (the shipped generic one) they enumerate and report against the target
    journal's own guidelines instead, and forbid length-driven cuts entirely.
    Either way M19 is always active and never a ranking/eligibility gate; the
    final package's readiness verdict carries an unresolved over-cap breach.
    """
    prof = _as_profile(profile)
    caps = _caps_clause(prof)
    caps_article = _caps_clause(prof, article=True)
    cover_clause = _cover_preference_clause(prof)
    has_caps = not caps.startswith("this venue profile sets no")
    counting_clause = main_text_counting_text(prof)
    cover_total = prof.length_limits()["cover letter"].get("total_max")
    cover_total_note = (
        f"the cover letter's TOTAL content must stay within {cover_total} words (every line "
        f"counts: salutation, body, disclosures and signature)"
        if cover_total is not None else
        "this venue profile sets no cover-letter total-word cap")
    cover_note = (cover_total_note
                  + (f", and its persuading part is the USER PREFERENCE {cover_clause}"
                     if cover_clause else ""))
    cover_tail = (f"this is the user's preference, not {_indefinite(prof.short)} requirement, "
                  f"and the venue "
                  f"profile publishes no cover-letter limit"
                  if cover_clause else "no cover-letter preference is configured")
    if cover_total is not None:
        cover_tail += f"; the {cover_total}-word TOTAL cap is the operator's budget"
    cover_row = (
        f"only when the persuading part falls outside the user preference "
        f"({cover_clause}) -- never as a journal requirement, and never a reason to delete content."
        if cover_clause else
        "only when a cover-letter preference is configured -- never as a journal requirement, "
        "and never a reason to delete content.")
    # The cover-letter TOTAL cap is a profile value like every other M19
    # number: a profile that configures none must not be told to hit "the
    # configured cap" (or the default venue's 650) in a mandate.
    if cover_total is not None:
        revise_cover = (f"Cover letter: bring its TOTAL content within {cover_total} words -- "
                        f"trim the non-persuading boilerplate first (statement blocks, the "
                        f"reviewer list, restated affiliations), never a claim about the work")
        integrate_cover = (f"The cover letter's TOTAL content must stay within {cover_total} words "
                           f"by trimming boilerplate only (never a claim about the work).")
        rewrite_cover = (f"the cover letter's TOTAL content must stay within {cover_total} words "
                         f"(trim boilerplate only)")
    else:
        revise_cover = ("Cover letter: this profile configures no TOTAL-content cap, so count and "
                        "record its TOTAL content without cutting it for length")
        integrate_cover = ("The cover letter has no configured TOTAL-content cap: report its count "
                           "and never cut it for length.")
        rewrite_cover = ("the cover letter has no configured TOTAL-content cap: count it and never "
                         "cut it for length")
    # The persuading-part preference is separate from the TOTAL cap: say
    # nothing about "the configured preference" when the profile configures
    # none (an explicit null pair means none).
    pref_clause = (
        f" -- and when the persuading part is outside the user's {cover_clause} preference, bring "
        f"it into the range by removing redundancy only (never content); {cover_tail}"
        if cover_clause else "")
    # The venue's OWN number is the base one; the pipeline's relaxation is a
    # margin, not a second cap. A section between the two used to be reported
    # clean everywhere, which is how an abstract of 164 words passed a 150-word
    # venue: the band clause makes it a row every stage must dispose.
    band_clause = ""
    review = f"""3b. The PIPELINE-MANDATED length sweep M19 (see the length rule in the standing
   exemptions): enumerate the ABSTRACT and the MAIN TEXT of every submission document that carries
   one -- and the PERSUADING PART of the cover letter -- into review/artifacts/M19_length.md, one
   row per section: document | section
   (abstract / main text / cover letter) | word count (for the cover letter also its TOTAL word
   count) | the relaxed limit you applied and its source | the allowed
   cap ({caps_article}; {cover_note}) | disposition
   (OK / over cap -> finding id / over cap but not compressible without losing content -> manual
   verification item). Count with the pipeline's definition (maximal runs of NON-SPACE characters;
   a newline is a space) and say in the artifact which text you counted as the main text
   ({counting_clause}, exactly as the venue profile's counting rule states).
   Give M19 its own coverage row, exactly like the skill's sweeps, and report every
   over-cap section as a CATEGORY-4 (technical formatting) finding. M19 is mandatory (the skill's
   references/sweeps.md defines the same sweep as always-on) and it is NEVER a gate: an over-cap
   section never makes a version ineligible. The cover-letter row adds a MINOR formatting finding
   {cover_row} {band_clause}"""
    if has_caps:
        revise = f"""Abstract/main-text length (check id M19; see the length rule): bring EVERY over-cap abstract
     or main text within the cap ({caps_article}) by removing redundancy,
     repeated statistics and non-meaning-bearing hedging only -- NEVER by deleting scientific
     content, claims, limitations, data, accession numbers or needed methodological detail, never
     by stripping a hedge that carries the claim's own strength (a limitation, an uncertainty the
     evidence supports: removing it is an overclaim, not a shortening), and never by touching
     text that is already within the cap. Count with the pipeline's definition (maximal runs of
     NON-SPACE characters; a newline is a space) and record every compression in CHANGELOG.md
     under M19. A section that cannot be brought within the cap without losing content is left as
     it is and handed to revised/MANUAL_STEPS.md instead of guessing. {band_clause}
     {revise_cover}{pref_clause}."""
        integrate = f"""Abstract/main-text length (check id M19) is a FORMATTING-tier difference class: port a donor's
version when it is within the cap and the base's is not, or when the donor removed redundancy from
an over-cap section without losing content. Otherwise compress the base yourself under the length
rule, and if a section cannot be brought within the cap ({caps_article}) without
losing content, leave it and record it for manual action. {integrate_cover} Never reach a cap
by deleting scientific content, and never port a purely shorter version that gives up correctness,
consistency or preservation to get there. {band_clause}"""
        rewrite = f"""Abstract/main-text length (check id M19) is REPORTED here, not fixed: a rewrite must not push
an abstract or main text over the pipeline's caps ({caps_article}) and must never cut scientific
content to meet one; {rewrite_cover}.
If the base is ALREADY over a cap, surface it in rewritten/REWRITE_REPORT.md
under "PROBLEMS SURFACED" -- the revision and integration stages own the compression, and this
stage must not change content to achieve it. {band_clause}"""
    else:
        revise = f"""Abstract/main-text length (check id M19; see the length rule): this venue profile sets no
     abstract or main-text cap, so do NOT compress, reword or cut a section for length: count the
     abstract and the main text, name the limit the target journal's own guidelines give (and its
     source) in CHANGELOG.md, and change that text only for the non-length findings you were
     handed. Count with the pipeline's definition (maximal runs of NON-SPACE characters; a newline
     is a space), and hand any length question you cannot answer from the guidelines to
     revised/MANUAL_STEPS.md instead of guessing. Cover letter: {cover_note}."""
        integrate = """Abstract/main-text length (check id M19) is a REPORTED difference class, not a compression one:
this venue profile sets no cap, so enumerate and diff the counts, never port or cut text because
one version is shorter or longer, and never let a word count decide a comparison."""
        rewrite = """Abstract/main-text length (check id M19) is REPORTED here, not fixed: this venue profile sets
no cap, so count the abstract and the main text and surface the counts (with the limit the target
journal's guidelines state, and its source) in rewritten/REWRITE_REPORT.md under "PROBLEMS
SURFACED". Never change content to reach a word count."""
    judge = f"""PLUS the pipeline-mandated length sweep M19 (count the abstract and the main
   text -- and the cover letter's persuading part -- with the pipeline's word definition and record the rows in
   judge_review/artifacts/M19_length.md; {caps_article}; {cover_note}). Length is FORMATTING-tier evidence: a version within the cap may be
   preferred to one that is over it by at most +/-1, two versions that are both over (or both
   within) are indistinguishable and score 0, and a length row is a formatting-tier MINOR row
   whose +/-1 can never outweigh a difference in a higher tier.
   An over-cap section never makes a version ineligible, and the cover-letter preference is
   user-set: it is at most a +/-1 formatting-tier difference, never a journal requirement. A cover
   letter whose TOTAL content is over its cap is a formatting-tier item too: report it, never gate
   on it, and never let it outweigh a higher tier. {band_clause}"""
    return {"review": review, "revise": revise, "integrate": integrate, "rewrite": rewrite,
            "judge": judge}


M19_CAPS = length_limits()
M19_REVIEW_SWEEP = m19_blocks()["review"]
M19_REVISE_RULE = m19_blocks()["revise"]
M19_JUDGE_SWEEP = m19_blocks()["judge"]
M19_INTEGRATE_RULE = m19_blocks()["integrate"]
M19_REWRITE_RULE = m19_blocks()["rewrite"]


def apply_m19(text: str, profile=None) -> str:
    """Substitute the M19 mandate sentences (always active, unlike M18)."""
    blocks = m19_blocks(profile)
    for token, key in (("@@M19_REVIEW_SWEEP@@", "review"),
                       ("@@M19_REVISE_RULE@@", "revise"),
                       ("@@M19_JUDGE_SWEEP@@", "judge"),
                       ("@@M19_INTEGRATE_RULE@@", "integrate"),
                       ("@@M19_REWRITE_RULE@@", "rewrite")):
        text = text.replace(token, blocks[key])
    return text


# ---- M20: OOXML style/formatting uniformity (always active) ----------------
# The corpus converters read text only, so a candidate can pass every M1-M19
# check while shipping a blank page, a running head on the title page, mixed
# hyperlink/plain URL treatments, per-figure legend spacing or an italic
# correspondence block. The orchestrator normalizes the mechanical classes
# itself (FORMAT-FIX in every stage's warnings, before the corpus is pinned) and
# the scan below hands the agents the enumerated rows for the editorial ones.
M20_FORMAT_SCAN_REL = "review/work/FORMAT_SCAN.json"
M20_FORMAT_ARTIFACT_REL = "review/artifacts/M20_formatting.md"
M20_FIX_CMD = f"python {DOCX_FORMAT_MODULE} fix FILE.docx --out FILE.fixed.docx"
M20_SCAN_CMD = f"python {DOCX_FORMAT_MODULE} scan DIR"
M20_REVIEW_SWEEP = f"""3c. The PIPELINE-MANDATED OOXML formatting sweep M20 (always runs; the orchestrator
   supplies the enumeration): the code-side scan of base/ is already written to
   {M20_FORMAT_SCAN_REL} and its rows are also seeded in {M20_FORMAT_ARTIFACT_REL}.
   AUDIT THAT TABLE ROW BY ROW -- one disposition per row (OK / finding id / unable -- reason) --
   and add any formatting defect the scan cannot see (font/size/justification/spacing/legend
   placement/table formatting, caption placement, heading numbering) as new rows. Classes the
   scan covers: break-only paragraphs and blank pages, header-on-title-page, tracked changes and
   proofing markers, figure-legend spacing INCLUDING a caption split across several paragraphs
   (FMT-T2c: a caption is one paragraph) and a caption carrying a paragraph style its sibling
   captions in the same area do not (FMT-T2d), heading keepNext/style drift, unintended italics
   (Zotero bibliography/citation fields are field-protected: report them as style-level items,
   fixable through the CSL style or by unlinking the fields in the submission copy), missing or
   inconsistent journal italics, mixed hyperlink/plain URL and email treatments, mixed
   straight/curly quotation marks and em-dash density; the whitespace/grammar/skeleton families:
   a stray empty paragraph that is NOT prescribed by the venue's own template (FMT-S8 a blank
   line attached to a heading, FMT-S6 a run beyond the cap), a space that renders at the start
   or end of a visual line (FMT-P4: the correspondence e-mail one space to the right, a
   dangling trailing space), doubled spaces / bracket spacing / zero-width marks (FMT-P3), a
   doubled word (FMT-G1), a possible lowercase sentence start (FMT-G2), a missing space after
   punctuation (FMT-G3), mixed direct fonts or spacing/indentation/alignment drift inside one
   style (FMT-T10a..T10d), a heading-level jump (FMT-T10e), and an embedded image rescaled off
   its own width-to-height ratio (FMT-IM1). TEMPLATE-PRESCRIBED BLANKS ARE NOT DEFECTS: the
   policy carries the journal template's own empty-paragraph slots and anything before the
   first non-empty paragraph (the spacer the template carries above the title), so those blanks
   are never reported or deleted -- dispose such a row as `OK -- template-prescribed slot`,
   never rewrite the template's own chrome. Give M20 its own coverage row, exactly
   like the skill's sweeps. The mechanical rows are REPAIRED by the orchestrator before the
   candidate is fingerprinted ({M20_FIX_CMD}); the editorial rows (em-dash reduction, quote
   style, journal-italic policy) are findings for the revision/integration arms. M20 is
   never a gate by itself and never makes a version ineligible -- EXCEPT the venue's own TABLE
   rule (FMT-TB1..FMT-TB3, below): a package-producing stage's postcheck fails while one of its
   rows is present, because the venue profile itself declared that rule.

   FMT-CL1 -- THE COVER LETTER FORMATTED IN THE MANUSCRIPT TEMPLATE -- is not a row you may
   wave through: the scan proves it from the venue's own template (the letter uses the
   manuscript template's Title/Author-List styles, or carries its header/footer parts) and the
   venue ships no cover-letter template to justify it. Dispose it with a finding (M20), or
   close it `OK` ONLY by quoting the journal's own template/guideline text that REQUIRES the
   letter to be formatted that way (its source and what it requires). "The run carries the
   letter in the journal's styles" is the PIPELINE talking, not the journal: the postcheck
   fails that closure.

   The ZOTERO LIVE-FIELD rows (FMT-Z1..FMT-Z5, check id M36) are part of this table and are
   ALWAYS `fix=manual`, `protected=true`: a citation marker whose number is not the cited item's
   rank, a bibliography entry that describes another work, one item with two numbers, a stored
   marker that disagrees with the visible text, or two conflicting Zotero style stores in one
   document. They are never "fixed" by editing a field -- the document must be refreshed in
   Word/Zotero (or the field repaired there), the code-side check re-run
   (`python3 paper_docx_format.py zotero-check <file.docx>`), and only then may the fields be
   flattened for a submission copy. Never flatten a document whose markers are stale: that
   freezes the wrong numbering, and the next refresh of a copy that still holds live fields
   would renumber the text and the reference list again.

@@DISPLAY_RULE@@"""
M20_REVISE_RULE = f"""OOXML formatting uniformity (check id M20; see the formatting sweep): the
     mechanical defects (break-only paragraph/blank page, legend spacing, heading keepNext,
     running head on the title page, unintended italics outside Zotero fields, mixed
     hyperlink/plain URL+email treatments, proofing markers, a stray empty paragraph that is not
     template-prescribed (FMT-S6/FMT-S8), a space that renders at the start/end of a line
     (FMT-P4), a doubled word (FMT-G1), and an embedded image rescaled off its own aspect ratio
     (FMT-IM1)) are normalized automatically on the
     package you deliver -- do not fight them, and do not re-introduce them. TEMPLATE-PRESCRIBED
     BLANKS STAY: never delete an empty paragraph the venue's own template carries (the spacer
     above the title, a placeholder slot between two headings; `format_policy.json` names them).
     Fix the EDITORIAL rows yourself: rewrite parenthetical em-dashes as commas/parentheses, make
     the quotation style uniform, keep journal titles italic only in the reference list, keep
     emails/URLs in ONE treatment; clean the real doubled spaces / space-before-punctuation /
     bracket-spacing / zero-width instances the scan reports (the review's `OK` dispositions name
     the equation and notation exceptions -- leave those exactly as recorded); fix any possible
     lowercase sentence start the scan or the review flagged; align mixed direct fonts and
     spacing/indentation/alignment drift to the paragraph style, and repair heading-level jumps.
     Do not fix an image by hand: the orchestrator restores the aspect ratio from the image's own
     pixels and a hand-resized extent will be overwritten. Re-scan with `{M20_SCAN_CMD}` before
     finishing, dispose every M20 row of the review artifact, and record each formatting edit in
     CHANGELOG.md under M20. Formatting changes are allowed here without touching meaning (this
     is the formatting exception to E1); never change scientific content for a formatting row.

     FMT-CL1 (the cover letter formatted in the MANUSCRIPT template) is a defect you FIX: when
     the venue ships no cover-letter template, restyle the letter as a plain submission letter
     (recipient block, date, salutation, body, closing, signature) and drop the manuscript
     template's Title/Author-List front matter, logo header and page furniture. LEAVE it only when
     the journal's own template/guideline text REQUIRES that formatting -- and then quote that
     text in MANUAL_STEPS.md/CHANGELOG.md; otherwise fix it. The postcheck fails a delivered
     package that NEWLY introduces the row (and an OK closure without the quoted requirement).

@@DISPLAY_RULE@@"""
M20_INTEGRATE_RULE = f"""OOXML formatting (check id M20) is a difference class of its own: the
     orchestrator normalizes the mechanical rows on the integrated package, and the editorial rows
     (em-dash density, mixed quotation marks, journal-italic policy, email/URL treatment, doubled
     spaces and bracket spacing, a possible lowercase sentence start, mixed direct fonts,
     paragraph spacing/indentation/alignment drift, heading-level jumps) are ported from a donor
     when the donor is the consistent one -- never merge two documents that disagree on treatment.
     Stray empty paragraphs and spaces that render at a line edge are the normalizer's job, but
     YOU must not re-introduce them, and a template-prescribed blank (the venue template's own
     slots in `format_policy.json`) is never a difference and never gets deleted. An embedded
     image off its own width-to-height ratio (FMT-IM1) is restored by the
     orchestrator; port the image file and its extents together or not at all. Re-scan with
     `{M20_SCAN_CMD}` and record the formatting state in integrated/CHANGELOG.md under M20.

     FMT-CL1 (a cover letter formatted in the MANUSCRIPT template) is a defect of the version
     that carries it, whether or not the donors share it: when the venue ships no cover-letter
     template, PORT the plain-letter styling (no manuscript Title/Author front matter, no
     manuscript logo header/page furniture) and prove the row is gone in the re-scan. Keep the
     defect only when the journal's own template/guideline text quotes a requirement for that
     formatting, and record the quote under M20 in CHANGELOG.md.

@@DISPLAY_RULE@@"""
M20_REWRITE_RULE = f"""OOXML formatting (check id M20) is REPORTED here, not fixed: a rewrite must
     not introduce a break-only paragraph, a second URL/email treatment, a different legend
     spacing or a new quotation style, a stray empty paragraph (FMT-S6/FMT-S8), a space at a
     line edge (FMT-P4), a
     doubled word or an off-ratio image size (FMT-IM1); keep the base's formatting conventions (a
     template-prescribed blank is a convention, not a defect). Re-scan your own package with
     `{M20_SCAN_CMD}` before finishing. If the base already carries formatting defects, surface
     them in rewritten/REWRITE_REPORT.md under "PROBLEMS SURFACED" -- the revision/integration
     stages and the orchestrator's normalizer own the fix.

     FMT-CL1 (the cover letter formatted in the MANUSCRIPT template) is one of the defects to
     SURFACE in rewritten/REWRITE_REPORT.md under "PROBLEMS SURFACED" with the rule id and the
     letter's file name; do not copy the manuscript template's front matter onto the letter, and
     do not silently inherit it from the base either -- the revision/integration stages restyle
     it as a plain submission letter.

@@DISPLAY_RULE@@"""
M20_JUDGE_SWEEP = """PLUS the pipeline-mandated OOXML formatting sweep M20 (derive it yourself:
   you are handed NO orchestrator artifact -- scan your own blinded views with
   `python paper_docx_format.py scan target/` (and field/<label>/ when a comparison needs it) and
   record the rows in judge_review/artifacts/M20_formatting.md; pass --policy format_policy.json
   when it is at your sandbox root). The scan covers the classes the text-only corpus drops:
   break-only paragraphs, header-on-title-page, tracked changes/proofing marks, legend spacing,
   heading keepNext/style drift, italics and URL/email treatments, quotation marks, em-dash
   density, PLUS the whitespace/grammar/skeleton families: a stray empty paragraph that is NOT
   template-prescribed (a blank line attached to a heading, a run beyond the cap; FMT-S6/S8), a
   space rendering at the start or end of a line (FMT-P4), doubled spaces / bracket spacing /
   zero-width marks (FMT-P3), a doubled word (FMT-G1), a possible lowercase sentence start
   (FMT-G2), a missing space after punctuation (FMT-G3), mixed direct fonts and
   spacing/indentation/alignment drift inside one style (FMT-T10a..T10d), a heading-level jump
   (FMT-T10e) and an embedded image delivered off its own width-to-height ratio (FMT-IM1).
   TEMPLATE-PRESCRIBED BLANKS ARE NOT DIFFERENCES: the venue template's own empty-paragraph
   slots (and anything before the first non-empty paragraph, the spacer above the title) are
   intended; never score a version down for keeping them, and never expect a version to delete
   them. A RESIDUAL mechanical row (the orchestrator's normalizer failed or a version re-introduced
   it) is a real defect of the version that carries it, not a difference to ignore.
   FMT-CL1 (a cover letter formatted in the MANUSCRIPT template: it uses the manuscript
   template's Title/Author-List styles or carries its header/footer parts while the venue ships
   no cover-letter template) is such a defect of the version that carries it, whether or not the
   opponent carries it too: RECORD the row in judge_review/artifacts/M20_formatting.md and say
   in the comparison's M20 check whether each side carries it and how it weighs in the
   formatting tier. An `OK` closure of that row is valid ONLY with the journal's own
   template/guideline text quoted that REQUIRES this formatting; "the run carries the letter in
   the journal's styles" is not an override and the postcheck fails it.
   Formatting differences are a LOW-priority,
   formatting-tier difference class: a version whose formatting is UNIFORM (one URL/email
   treatment, consistent quotation marks, consistent legend spacing, no blank page) may be
   preferred to one that is not by at most +/-1, and formatting never decides a comparison on its
   own beyond that point: FORMATTING is the lowest tier, so a formatting-tier difference can
   decide only when every other tier (including writing) is zero; it can never outweigh a
   correctness, preservation, completeness, consistency or writing difference. Mechanical defects
   have already been normalized by the orchestrator before the view you
   read was built, so do not manufacture differences out of them (but a residual row IS such a
   difference -- report it). The TEXT-level consistency rows
   (citation dialect, US/UK spelling, attributive hyphenation) are deliberately NOT pre-normalized:
   a corpus that completed a convention where the other did not is a real CONSISTENCY-tier
   difference (second in the priority order) and is scored as one.

@@DISPLAY_RULE@@"""


def apply_m20(text: str, profile=None) -> str:
    for token, block in (("@@M20_REVIEW_SWEEP@@", M20_REVIEW_SWEEP),
                         ("@@M20_REVISE_RULE@@", M20_REVISE_RULE),
                         ("@@M20_JUDGE_SWEEP@@", M20_JUDGE_SWEEP),
                         ("@@M20_INTEGRATE_RULE@@", M20_INTEGRATE_RULE),
                         ("@@M20_REWRITE_RULE@@", M20_REWRITE_RULE)):
        text = text.replace(token, block)
    # The venue's DISPLAY rules come AFTER the blocks above (each of them carries
    # the @@DISPLAY_RULE@@ token), so one substitution fills them all.
    return text.replace("@@DISPLAY_RULE@@", display_rule_text(profile))


def display_rule_text(profile=None) -> str:
    """The venue's DISPLAY rules (tables + figures) for a prompt.

    Rendered from the profile, never invented: a kind the profile declares no
    rule for renders the report-only wording (nothing is gated for it and the
    code-side scan emits no rows for it), and a kind it does declare states
    where those items belong, which side carries the caption, and which items
    the venue itself treats differently (a key-resources table inside the
    methods, a graphical abstract that is not part of the numbered sequence).
    """
    prof = _as_profile(profile)
    blocks = [display_kind_rule_text(prof, "table", prof.data.get("tables") or {}),
              display_kind_rule_text(prof, "figure", prof.data.get("figures") or {})]
    return "\n".join(blocks)


def display_kind_rule_text(prof, kind: str, block: dict) -> str:
    """One kind's block of the display-rule prompt text (see display_rule_text)."""
    plural = kind + "s"
    rules = "FMT-TB1..FMT-TB3" if kind == "table" else "FMT-FG1..FMT-FG3"
    r1, r2, r3 = (("FMT-TB1", "FMT-TB2", "FMT-TB3") if kind == "table"
                  else ("FMT-FG1", "FMT-FG2", "FMT-FG3"))
    if not _declares_display_rule(block):
        return (f"{plural.upper()} — the venue profile declares NO {kind} rule "
                f"(check ids {rules}):\n"
                f"  * Nothing is gated on {kind} placement or captioning for this venue, and the "
                f"code-side scan emits no {rules} rows; the venue's own template and author "
                f"guidelines govern, and the review records what it finds against them. A {kind} "
                f"that carries no caption at all is still a defect an editor raises: report it "
                f"(or give the {kind} its own caption paragraph when the venue's own structure "
                f"has a slot for one) -- never invent, delete or combine {kind} content.")
    lines = [f"{plural.upper()} — THE VENUE'S OWN RULE (check ids {rules}; code-side scanned):"]
    src = f" Source: {block.get('source')}" if block.get("source") else ""
    placement = str(block.get("placement") or "")
    if placement == "end":
        area = "tables area" if kind == "table" else "figure/legend area"
        lines.append(
            f"  * WHERE {plural.upper()} BELONG: at the END of the manuscript, together in the "
            f"{area} (with the other {plural}, not scattered through the body). A {kind} "
            f"that appears before that area is the finding {r3} -- move it"
            + ("" if kind == "figure" else " (with its caption)")
            + f" into the {area} beside the other {plural}." + src)
    elif placement == "inline":
        lines.append(
            f"  * WHERE {plural.upper()} BELONG: in the body, where the text cites them; this "
            f"venue does not collect {plural} into an end-of-manuscript area, and the code checks "
            f"no placement for it." + src)
    else:
        lines.append(f"  * WHERE {plural.upper()} BELONG: the venue states no placement rule; "
                     f"the code checks none." + src)
    caption = str(block.get("caption") or "")
    label_examples = ("\"Table 1.\", \"Table S1.\", \"TABLE 2 |\"" if kind == "table"
                      else "\"Figure 2 |\", \"Fig. 2.\", \"Figure S1\", \"Extended Data "
                           "Figure 3 |\"")
    if caption == "before":
        lines.append(
            f"  * THE CAPTION: every {kind} carries its own caption paragraph IMMEDIATELY BEFORE "
            f"it (labelled as the venue labels its {plural} -- {label_examples}). A {kind} with "
            f"no caption is {r1}; a caption on the other side of the {kind} is {r2}.")
    elif caption == "after":
        lines.append(
            f"  * THE CAPTION: every {kind} carries its own caption paragraph IMMEDIATELY AFTER "
            f"it (the legend-below-the-figure layout). A {kind} with no caption is {r1}; a "
            f"caption on the other side is {r2}.")
    elif kind == "figure":
        lines.append(
            "  * THE CAPTION: the venue does not pin the caption's side -- a figure's legend may "
            "live in the legends area at the end, so no caption is required next to the image; "
            "the collect/keep-labels rule still applies (every legend carries its label).")
    else:
        lines.append(
            f"  * THE CAPTION: the venue does not pin the caption's side; a {kind} that carries "
            f"no caption at all is still {r1}.")
    specials = block.get("special") or []
    if specials:
        lines.append(
            f"  * THE VENUE'S OWN EXCEPTIONS: this venue genuinely treats SOME {plural} "
            f"differently, and the code knows them by the text above the item, the section "
            f"heading over it"
            + (" or its first-row header" if kind == "table" else "")
            + ". They are EXEMPT from the rule above exactly as stated and must not be forced "
              "into the general shape:")
        for s in specials:
            bits = []
            if s.get("placement"):
                bits.append(f"placement: {s['placement']}")
            if s.get("caption"):
                bits.append("caption: none (no caption needed)" if s["caption"] == "none"
                            else f"caption: {s['caption']}")
            lines.append(f"      - {s['match']!r}" + (f" ({'; '.join(bits)})" if bits else "")
                         + (f" -- {s.get('note')}" if s.get("note") else "")
                         + (f" [source: {s['source']}]" if s.get("source") else ""))
        if block.get("note"):
            lines.append(f"  * {block['note']}")
    elif block.get("note"):
        lines.append(f"  * NO SPECIAL {plural.upper()}: {block['note']}")
    lines.append(
        f"  * HOW THIS IS CHECKED: the pipeline's code-side scan of the manuscript reports these "
        f"as {r1}/{r2}/{r3} rows (with the item's shape and the text above it) in "
        f"`FORMAT_SCAN.json` and the M20 artifact; the review disposes every row, and a "
        f"package-producing stage must DELIVER a package with none of them -- its postcheck "
        f"fails while one is present. The same rules are written into your session as "
        f"`format_policy.json` at the sandbox root; pass it to your own scans with "
        f"`python paper_docx_format.py scan <dir> --policy format_policy.json`.")
    return "\n".join(lines)


# ---- M25-M29 + J5: THE REWRITE-PARITY CHECKS (review/audit/revise) ----------
# A from-scratch rewrite fixes these classes as a side-effect of rewriting: it
# re-aligns artwork terms with the text, completes a spelling/hyphenation
# convention across the whole corpus, completes a claim's evidence pointers,
# makes sibling definitions symmetric, aligns a caption with what is printed,
# and reorganizes at the scope level. The 2026-09-27 root measured the cost of
# the review not seeing them: the judges credited the rewrite (w1/w2) with
# consistency/completeness rows the frozen review never filed, while the a2 arm
# had "nothing to fix" and carried them into the field.
#
# The panel's frozen sweep set is NOT extended: the judges' coverage map stays
# M1-M24 + J1-J4 (identical minimum scrutiny across versions is what keeps the
# panel calibrated, and the comparison already scores these differences under
# the consistency/completeness/correctness tiers). These checks exist on the
# review -> audit -> revise path, which is the path that must stop leaving the
# points on the table.
REWRITE_PARITY_REVIEW = """3d. The REWRITE-PARITY checks M25-M29 and the ARCHITECTURE pass J5 (the jobs a
   from-scratch rewrite performs while it rewrites; definitions in the skill's
   references/sweeps.md, sections M25-M29 and J5). Each of the SIX gets its own artifact under
   review/artifacts/ AND its own coverage row, exactly like the older sweeps. One finding per
   instance for M25-M29; J5 is one finding per SCOPE:
   * M25 figure-artwork/text parity - extract the text layer of every rendered figure/table
     artefact (`pdftotext` / slide text) and pair every artwork token (method/tool name, year,
     axis/panel/factor phrase) with the manuscript's own counterpart (the M8 term ledger /
     review/work/GLOSSARY.md decision, the legend, the Methods sentence). Artifact:
     review/artifacts/M25_artwork_parity.md. An artwork file is usually read-only; that does NOT
     make its row `unable` - when the editable caption/main-text/SI-legend surface can be
     aligned, the finding is resolvable and the artwork regeneration is a manual follow-up.
   * M26 house-style / orthographic conventions - run the bundled
     `enumerate_conventions.py --work review/work` over the converted corpus (both surfaces of
     every US/UK spelling, hyphenation and preverb family, plus data-driven candidates), decide
     ONE authoritative form per family in review/work/STYLE_CONVENTIONS.md (corpus majority /
     the manuscript's own first use / a stated venue rule), and file ONE FINDING PER DEVIATING
     OCCURRENCE - never one per family. Artifact: review/artifacts/M26_conventions.md.
   * M27 claim-to-evidence coverage - for every plural/aggregate claim (and every number whose
     sentence states a universe), enumerate the evidence items the claim needs from the shipped
     data and check the pointer set actually covers them. A resolving citation is NOT coverage
     (the S12-only pointer for a claim about both haploid samples is the recorded case).
     Artifact: review/artifacts/M27_evidence_coverage.md.
   * M28 sibling-definition symmetry - per list/head-noun group, compare each sibling's
     first-use expansion and definition order (one expanded, two not; long form after short form
     for one sibling and before it for another). Artifact: review/artifacts/M28_symmetry.md.
   * M29 caption-promise vs printed-schema parity - pair every promised field/panel/encoding in
     a caption with the printed table header or the artwork's own text ("eleven columns" for a
     ten-column TSV is the recorded case) AND run the reverse pairing the same way: every printed
     column/panel/encoding the caption never describes is equally a finding (the reader cannot
     interpret an undocumented column, and the caption, not the reader, owns the explanation).
     Artifact: review/artifacts/M29_caption_schema.md.
   * J5 architecture & rewrite-class pass - one row per SCOPE in review/ARCHITECTURE.md
     (`document | section | paragraphs | current structure | reader cost | proposed
     reorganization | class | severity | disposition`): claim-first order, one message per
     paragraph, reading order inside a passage, missing transitions, cross-section redundancy.
     A row needing work becomes a finding with `check: J5` and its `scope` key set; a scope that
     is fine gets a row-specific `OK - <why this order serves the reader>`. This is the ONE
     place where a scope-level (non-instance) finding is legal, and the revision stage has a
     scoped-restructuring licence for it (E11)."""

REWRITE_PARITY_AUDIT = """4. ATTACK THE REWRITE-PARITY RECORD - the classes a rewrite fixes as it goes, and the
   dispositions that lost the last root's points. A blanket closure is not a disposition here
   either; raise every real defect as your own `AU-` finding:
     * M1 / M1b: a row closed "it is a name / proper noun, not an abbreviation" is NOT a
       disposition when the sentence itself prints the token's expansion
       (`MALBAC-sequenced (multiple annealing and looping-based amplification cycles)`,
       `ground-truth haplotypes (phased single-nucleotide polymorphisms, SNPs)`). That is M1(a)
       used-before-defined - the long form must precede the first use.
     * M25-M29: for every row the reviewer disposed, ask whether the reason is about THAT row's
       own bar (the term ledger's decision, the claim's required evidence set, the printed
       header) or a blanket sentence. A row closed "the artwork is read-only" while an editable
       caption/main-text/SI-legend surface still carries the non-authoritative form is an AU-
       finding, not a manual item. Same for a convention family closed per document while the
       convention is a corpus-level decision.
       (M25 artwork/text parity · M26 house-style conventions · M27 claim-to-evidence coverage ·
       M28 sibling-definition symmetry · M29 caption-promise parity - each artifact must carry a
       disposition on every row.)
     * the TWO-SIDED rows: a caption row disposed "the print is what it is" while a printed
       column/panel is described nowhere is an AU-finding (M29 reads in both directions), and a
       J3 row disposed as "the wording is appropriately cautious" is an AU-finding when the
       corpus's own data prove the claim the sentence hedges (an underclaim is the other half of
       the calibration check, not a virtue). Read `review/artifacts/CLAIM_STRENGTH.md` both ways.
     * J5 / review/ARCHITECTURE.md: every scope row must carry a row-specific disposition. A
       document with no rows, or one "OK - reads well" sentence repeated on every row, is an
       UNFILLED artifact - raise the scopes you can evidence yourself as `AU-` findings
       (`check: J5`, scope recorded).
   The reviewer's M25-M29/J5 FINDINGS are disposed like every other frozen id (confirm, or drop
   with evidence)."""

REWRITE_PARITY_REVISE = """13. REWRITE-PARITY findings (M25-M29) - resolve them the way a rewrite would: one
    edit per finding instance, applied to EVERY occurrence of the convention, not only the
    quoted one (rule E11 in the revision skill's edit_rules.md):
      * M25 (artwork/text parity): align the editable main text / caption / SI legend with the
        authoritative form the review recorded; the artwork regeneration (exact label + the code
        file that prints it) goes to MANUAL_STEPS.md as a follow-up. A read-only artwork file
        does NOT make this finding manual-required while an editable surface exists.
      * M26 (house-style conventions): substitute the authoritative form everywhere - main
        text, SI, legends, table notes, cover letter, and the controlled reference text - copy
        the review's STYLE_CONVENTIONS.md decisions into revised/work/STYLE_CONVENTIONS.md,
        then re-run `enumerate_conventions.py --work revised/work --corpus revised/work/corpus`
        over the revised corpus and require every edited occurrence to be gone or to carry a
        ledger reason. A fix in one document that leaves the sibling documents mixed is NOT a
        resolution.
      * M27 (claim-to-evidence coverage): add exactly the missing pointer the finding names
        (citation, figure/table call-out, `(Methods)` pointer, SI note). Never invent a source:
        a pointer set that cannot be completed without new content is manual-required with the
        exact pointer the author must add.
      * M28 (sibling symmetry): make the list symmetric exactly as the row specifies (expand the
        unexpanded siblings, or put each sibling's long form before its short form at first
        use); an expansion that exists nowhere in the corpus is manual-required, never invented.
      * M29 (caption-promise parity): align the editable side with what the print actually
        delivers - the caption wording, or the printed source when it is in the corpus and
        editable - one promised item per edit; a promise the print does not deliver and a printed
        item the caption never describes are the SAME finding class in opposite directions, so
        fix both: add the missing description for an undocumented printed field/panel, and
        remove or reword a promise the print cannot satisfy. A generated print's regeneration
        step is a manual follow-up, not a reason to carry the finding.
    These are normal E1 edits (substitutions / pointer additions inside the finding's own
    sentence); what differs from E1 is the corpus-wide completion of the convention.
13. ARCHITECTURE findings (J5) - a J5 finding names a SCOPE, and rule E11 LIFTS E1's no-reflow
    prohibition INSIDE that scope (the one restructuring exception besides M18/M19): reorder
    sentences/paragraphs, move a paragraph within its section, split or merge paragraphs, add
    or rewrite a transition sentence, rewrite a passage for cohesion. Guards, all mandatory:
    the content is frozen (same claims, numbers, citations, accessions, limitations and
    conclusions; nothing deleted except a redundancy the finding itself names; nothing
    invented), the edit stays inside the declared scope, figure/table numbering and
    cross-references stay coherent, ONE revised/work/RESTRUCTURE_<finding-id>.md artifact per
    finding (scope, BEFORE outline, AFTER outline, every moved paragraph before -> after, the
    diff hunk ids, the claim-by-claim preservation check), and the mechanical rescan (V3)
    re-runs after each scope. A J5 finding whose scope cannot be restructured without content
    loss is manual-required, with the proposed reordering written out in MANUAL_STEPS.md."""


def apply_rewrite_parity(text: str, where: str) -> str:
    """Substitute the rewrite-parity block for the stage that owns it."""
    block = {"review": REWRITE_PARITY_REVIEW,
             "audit": REWRITE_PARITY_AUDIT,
             "revise": REWRITE_PARITY_REVISE}.get(where, "")
    return text.replace("@@REWRITE_PARITY@@", block)


# ---- M30: THE SOURCE-HIERARCHY RECONCILIATION (review/audit/revise) --------
# The hierarchy (code > raw data > figures > ... > text) has always been the
# RESOLUTION rule: it decides which side wins when two sources already
# disagree. Its DETECTION side -- a written number, parameter, sample set or
# label that disagrees with the code or raw data that produced it -- had no
# enumerating check, so it was found only when a human happened to compare the
# two. M30 is that check on the review -> audit -> revise path; the code-side
# seed (paper_docx_format.hierarchy_seed_rows / code_literal_rows) pairs every
# un-proved written number with its candidate producer and lists the code's own
# literals, so the quiet half of each comparison is a row that must be disposed.
HIERARCHY_RECONCILE_REVIEW = """3e. The SOURCE-HIERARCHY reconciliation (check id M30; the definition is in the
   skill's references/sweeps.md, section M30). The source hierarchy
   (@@SOURCE_HIERARCHY@@) is the RESOLUTION rule; M30 is its DETECTION side. For every
   operational or quantified item in the written parts -- a number, n, a parameter, a
   tool/protocol step, a sample set, a panel/axis label -- find the artifact that PRODUCED it
   (a raw_data/ file, a code/config file's constant or the function that prints the value, the
   figure/table source) and reconcile the two:
   * the orchestrator seeds review/artifacts/M30_hierarchy_reconciliation.md with the rows the
     code could pair (every written number no shipped table PROVES, against its candidate
     table column(s) -- including a cohort-size sentence against the table's own row count --
     and every module-level code/config literal). Dispose EVERY seeded row, then ADD the rows
     the seed cannot see: figure/panel <-> the code or raw data that generates it, protocol
     step <-> the code that implements it, sample/cohort set <-> the data's rows, Methods
     parameter <-> the code's constant;
   * one finding per incompatible instance (`check: M30`), naming BOTH sides and the
     authoritative one per the hierarchy; class `correctness` (a factual error) or
     `completeness` (a missing producer/pointer);
   * a producer that is NOT in the corpus (an external GitHub repository, an image-only
     figure, a binary the text tools cannot read) is a recorded
     `unable - the producer is not in the corpus` row, never a silent clean; a difference a
     stated unit, rounding, conversion or Methods-stated run-time override reconciles is `OK`
     with that reason recorded;
   * NEVER "fix" the code here: the review reports. A code fix is rule C's job (paper-revise),
     and a regenerated figure/table goes to the manual list.
   Artifact: review/artifacts/M30_hierarchy_reconciliation.md, with its own coverage row."""

HIERARCHY_RECONCILE_AUDIT = """     * M30 source-hierarchy reconciliation: a row closed "the code/raw data is out of scope",
       "raw_data/ is read-only" or "not in the written parts" is NOT a disposition when the
       corpus ships the producer and the written value disagrees with it -- that is an AU-
       finding (`check: M30`, both sides cited). "No shipped table matches" is not a disposition
       either while the code declares the constant or the figure's source is in the corpus, and a
       row disposed "unable" without saying which producer was searched is unfilled. The authority
       you cite is the standing hierarchy (@@SOURCE_HIERARCHY@@), and the M30 artifact's rows are
       disposed like every other sweep's."""

HIERARCHY_RECONCILE_REVISE = """14. SOURCE-HIERARCHY findings (M30) - resolve them by rule E12: align the WRITTEN
    side with the artifact the hierarchy names as authoritative (github code > data in
    raw_data/ > main figures > supplementary figures > main tables > supplementary tables >
    main text > supplementary text). When the authoritative side is the CODE and the code is
    the wrong side, rule C owns the fix: a minimal code edit, the dependent numbers/figures
    become manual-required with rerun instructions (never guessed), and the package keeps the
    code under code/. raw_data/ is READ-ONLY: a finding whose only fix is inside it is
    manual-required with the exact file and value. Record which side was authoritative and why
    in the ledger row, and re-run the code-side scan (V3) after the edit."""

HIERARCHY_RECONCILE_REWRITE = """SOURCE-HIERARCHY (check id M30, review-side): where a written statement and its producer
   (code, raw data, figure/table source) disagree, do NOT resolve it here, even when the hierarchy
   decides unambiguously; record the conflict under PROBLEMS SURFACED with BOTH sides and the
   producer's file:line. Never rewrite a claim to match a figure, and never edit the code: a
   rewrite that silently "fixes" one side of such a conflict hides the finding the revision
   stage has to resolve under rule C/E12."""

HIERARCHY_RECONCILE_INTEGRATE = """SOURCE-HIERARCHY (check id M30): an M30 finding -- or an integration difference about a
   claim its own shipped code or raw data contradicts -- is resolved by aligning the written
   side with the authoritative artifact, exactly as P1 and rule C prescribe: a code fix travels
   under code/ with its rerun note, raw_data/ is never edited, and the DIFF_LEDGER row names
   which side was authoritative and why."""


def apply_hierarchy_reconcile(text: str, where: str) -> str:
    """Substitute the M30 block for the stage that owns it."""
    block = {"review": HIERARCHY_RECONCILE_REVIEW,
             "audit": HIERARCHY_RECONCILE_AUDIT,
             "revise": HIERARCHY_RECONCILE_REVISE,
             "rewrite": HIERARCHY_RECONCILE_REWRITE,
             "integrate": HIERARCHY_RECONCILE_INTEGRATE}.get(where, "")
    # The block spells the hierarchy itself: the review/audit/rewrite builders
    # fill @@SOURCE_HIERARCHY@@ only inside the attached master prose, so a
    # token left here would reach the session unresolved.
    return text.replace("@@HIERARCHY_RECONCILE@@",
                        block.replace("@@SOURCE_HIERARCHY@@", SOURCE_HIERARCHY))


# ---- M31-M36: THE EVIDENCE-INTEGRITY SWEEPS (review/audit/revise) ----------
# The five classes a mechanical scan can SEED but only a reader can judge: what
# a figure actually PRINTS against what its legend says (M31), whether a
# headline statistic can pass the correction the paper itself states (M32),
# whether an availability locator is final and pins ONE revision (M33), whether
# a figure's shipped source data covers exactly what the legend claims (M34),
# and whether the disclosures/provenance name the real thing -- the model, not
# the client -- with no internal working material shipped (M35). Each is
# review-side like M25-M30: the judge's frozen map is unchanged, and the code's
# own seeds are FMT-AV1/A2 (M33), the M30 source-data comparison (M34) and
# PKG-1 (M35).
EVIDENCE_INTEGRITY_REVIEW = """3f. The EVIDENCE-INTEGRITY sweeps M31-M36 (definitions in the skill's
   references/sweeps.md, sections M31-M36). Each gets its own coverage row and its own
   artifact under review/artifacts/:
   * M31 ARTWORK-VERSUS-LEGEND consistency: for every figure compare what the PRINTED
     artwork says (axis titles, inset labels, column headers, color-bar range, legend keys)
     with the legend and the manuscript's own name for that quantity. A legend sentence whose
     only job is to explain a defect the reader sees ("printed as ...", "the legacy column
     name ...", "which denotes ...", "share the extreme color") is itself the finding: the
     artwork is corrected, never the legend extended (artifact: M31_artwork_legend.md);
     the code-side PKG-4 rows in `review/work/EVIDENCE_PACK.md` ("Display items the submission
     does not carry") are this class's packaging half: a document that CITES and legends a
     figure the package carries no file for -- ship the figure, embed it, or drop the citation;
     the PKG-5 rows in the same pack ("Display-item provenance contradictions") are the
     ATTRIBUTION half: a resources/software table row claiming an item whose own legend names a
     different producer (the 2026-10-15 case: the table credited `Matplotlib, seaborn` with
     Figure S2 while S2's legend says `Created with BioRender.com`). Two shipped surfaces
     disagreeing about which tool made an item is a finding, and a legend that points at another
     surface for a value ("the fold-changes quoted in the title", "as noted in the panel title")
     while that surface does not carry it is the same class;
   * M32 HEADLINE STATISTIC vs the correction the paper states: for every numeric claim on a
     claim-bearing surface (abstract, cover letter, Results highlights, legends) check the
     test, the unit of analysis, n, the p-value and the correction the Methods/Statistics
     section itself states, then check that the corrected level is reachable (a Holm threshold
     0.05/k; a signed-rank floor of 2^-n). A claim the stated correction cannot support, or an
     "unadjusted" level reported without its correction status, is a finding (artifact:
     M32_statistics.md);
   * M33 AVAILABILITY-LOCATOR FINALITY: every Data/Code/Materials availability statement and
     resource row must point at a locator that EXISTS now (deposit, DOI, accession, repository
     + commit) and every statement about one repository must pin ONE revision. The code-side
     FMT-AV1 (future/conditional locator) and FMT-AV2 (one repository, two commits) rows seed
     it (artifact: M33_availability.md), and its other half is the code-side PKG-2 rows (the
     "Submission-surface references" table in `review/work/EVIDENCE_PACK.md`): a to-be-submitted
     DOCUMENT that names a file the submission does not carry -- a script under `code/`, the
     `raw_data/` archive, one of the author's README files -- promises the reader something
     nobody can deliver. Such a sentence is REWRITTEN (name where the material really is, or
     carry the fact itself); the orchestrator REMOVES a pointer-only sentence mechanically at
     publication when the pointer is still there, but a sentence carrying a numeric fact is held
     and reported, never deleted to make the package look clean;
     a `PKG-3` row is the same table's other shape -- a file name the package carries NOWHERE --
     which the mechanical layer never removes: rewrite the sentence to ship the file, to name a
     locator the submission carries, or to drop the pointer;
   * M34 FIGURE SOURCE DATA vs the legend's own claim: for every figure/table compare the
     shipped source data's distinct dataset/panel/method values and any selection/exclusion
     rule its metadata records with the counts and the rule the legend and manuscript state.
     Extra rows (a method the text says was not run, an undocumented second run, a second read
     length) and missing statements of an exclusion rule are findings; the M30 rows (including
     the code-side M30-NC "not run" seeds) are the numeric half (artifact:
     M34_source_data_coverage.md);
   * M35 DISCLOSURE/PROVENANCE completeness: the generative-AI disclosure names the MODEL with
     its version (a client/CLI name or a model identifier that does not exist is a finding) and
     sits where the venue's own guidelines ask for it; every named third-party tool carries its
     version/commit; and the package ships NO internal working material (the code-side PKG-1
     rows name internal review-session URLs, the pipeline's own ledgers/reports and stage
     notes) -- the file is reported for the author to remove, never silently deleted
     (artifact: M35_disclosures.md);
   * M36 ZOTERO LIVE-FIELD REFRESH PARITY: the manuscript's citations are live Zotero fields,
     and their rendered numbers plus the bibliography are CACHED results. Compare the numbering
     the document shows with the numbering its OWN citation order defines: the code-side FMT-Z1
     (a marker whose number is not the cited item's rank), FMT-Z2 (the entry at a rank describes
     another work), FMT-Z3 (one item with two numbers, a number outside 1..N, an entry never
     cited), FMT-Z4 (stored marker vs visible text) and FMT-Z5 (conflicting Zotero style stores)
     rows seed it. A Word/Zotero refresh rewrites exactly those caches -- it renumbers the text,
     reorders the bibliography and re-renders the entries in whichever style the document's
     preference stores name. The resolution is NEVER to edit a field result here: refresh in
     Word/Zotero, re-run `python3 paper_docx_format.py zotero-check <file.docx>` until it is
     clean, and only then flatten the fields (`unlink_zotero_fields`) for the submission copy;
     flattening a document whose markers are stale freezes the WRONG numbering
     (artifact: M36_zotero_parity.md).
   Report each row under its own check id (M31-M36) in the coverage table; a class with no
   finding is `clean -- basis: <the artifact and what was read>`."""

EVIDENCE_INTEGRITY_AUDIT = """     * M31-M36 evidence integrity: attack a class closed `clean` when the corpus ships what the
       class needs. An M31 `clean` while the artwork prints a label its legend renames, an M32
       `clean` while the abstract's p-value cannot pass the correction the Methods state, an M33
       `clean` while a locator is future/conditional or the same repository carries two commits,
       an M34 `clean` while a figure's source data carries more datasets/methods than the legend
       describes, an M35 `clean` while the disclosure names a client instead of a model or the
       package ships internal working material, or an M36 `clean` while a citation marker's
       number disagrees with the item's own rank in the Zotero citation order (or the
       bibliography entry at that rank describes another work) -- each is an `AU-` finding under
       that check id, with both sides quoted."""

EVIDENCE_INTEGRITY_REVISE = """15. EVIDENCE-INTEGRITY findings (M31-M36) - resolve what is editable and hand the rest to
    MANUAL_STEPS.md with the exact artifact named:
    * M31: correct the artwork, or -- when the figure is read-only -- align the editable legend
      only to what the artwork really shows and put the regeneration step in MANUAL_STEPS.md;
      never leave a legend sentence whose job is to explain a defect;
    * M32: move the caveat into the claim (or remove the claim from the abstract) so the level
      reported is the level the stated correction reaches; never adjust a number to make the stated correction pass (a source-hierarchy correction under E12 is a separate rule);
    * M33: an availability statement is aligned only by naming where the data/code ARE; a
      deposit that has not happened is MANUAL_STEPS.md, and two pins become one. A sentence of
      a to-be-submitted document that points at what the submission does not carry (the
      code-side PKG-2 seed in `work/EVIDENCE_PACK.md`) is REWRITTEN so it names shipped content
      or carries the fact itself -- never left as a promise, and never "fixed" by deleting the
      fact with the pointer (the orchestrator removes only a pointer-only sentence if the
      pointer is still there when the package is published; a numeric fact is held and
      reported);
    * M34: align the editable legend/Methods count or the stated selection rule with the source
      data; a regenerated figure/table or a stale source-data row is manual-required with the
      file named;
    * M35: rewrite a disclosure that names a client/CLI as a model+version disclosure, move it
      to the venue's required placement, and REMOVE internal working material from the package
      (report the file in MANUAL_STEPS.md when it carries author content);
    * M36: NEVER edit a Zotero field result. A stale marker is normally cleared by the postcheck's
      automatic offline `zotero-refresh`; only when that refresh refuses is it resolved by the
      AUTHOR refreshing in Word (Zotero -> Refresh), after which the code-side check is re-run.
      Record the exact file and the row the refresh must clear in MANUAL_STEPS.md, and state that
      the fields may be flattened (`unlink_zotero_fields`) ONLY after the check is clean."""

EVIDENCE_INTEGRITY_GENERIC = """EVIDENCE-INTEGRITY (check ids M31-M36, review-side): the classes above are reported,
   not silently repaired. An availability locator, an artwork label, a source-data selection
   rule and a disclosure are the AUTHOR's statements: surface them under the class's own id and
   leave the un-editable side (a read-only figure, a deposit that has not happened, an internal
   file that must be removed) to MANUAL_STEPS.md with the exact artifact named. M36 is the
   Zotero live-field refresh parity: a stale citation marker or a bibliography order that
   disagrees with the document's OWN citation order (FMT-Z1..Z5) is named for the author to
   refresh in Word/Zotero and re-check with `python3 paper_docx_format.py zotero-check` -- a
   field RESULT is never edited here, and the fields may be flattened only once the check is
   clean.

   PKG-2 is the SUBMISSION-SURFACE half of M33: a delivered document may only point at content
   the submission itself carries. A sentence naming a file the submission leaves out (a script
   under `code/`, the `raw_data/` archive, one of the author's README files) is REWRITTEN so it
   names shipped content or carries the fact itself; the orchestrator's own PKG-2 rows (the
   "Submission-surface references" table in `work/EVIDENCE_PACK.md`) list them, and the
   orchestrator REMOVES a pointer-only sentence mechanically when the pointer is still there at
   publication; a sentence carrying a numeric fact is held and reported, because a packaging
   repair must not delete the fact."""


def apply_evidence_integrity(text: str, where: str) -> str:
    """Substitute the M31-M36 block for the stage that owns it."""
    block = {"review": EVIDENCE_INTEGRITY_REVIEW,
             "audit": EVIDENCE_INTEGRITY_AUDIT,
             "revise": EVIDENCE_INTEGRITY_REVISE}.get(where, EVIDENCE_INTEGRITY_GENERIC)
    return text.replace("@@EVIDENCE_INTEGRITY@@", block)


# ---------------------------------------------------------------------
    # The other two pipeline conventions that a stage must not misread as defects
# of the package it is looking at: the hand-off placeholder the REVISION stages
# are required to write instead of inventing missing content (which the review
# skill's M5/M6 sweeps and the judge's frozen sweeps would otherwise report as a
# hygiene/completeness defect of the very version that complied), and the
# difference-tracking auxiliaries -- "*.tracking-<token>.<ext>" and their
# "*.logging-<token>.<ext>" fallbacks, see TRACKING_AUX_NAME_RE --
# (which the M6 sweep reads as "residual tracked changes" and a judge could read
# as a duplicate sibling, and which the pipeline itself writes next to every
# tracked document).
# ---------------------------------------------------------------------
PLACEHOLDER_TOKEN = "[AUTHOR TO COMPLETE"
PLACEHOLDER_RE = re.compile(r"\[\s*AUTHOR\s+TO\s+COMPLETE\b", re.IGNORECASE)

PLACEHOLDER_RULE = """PIPELINE HAND-OFF PLACEHOLDERS — the literal token "[AUTHOR TO COMPLETE: ...]":
  * The revision stages of this pipeline are forbidden to invent content, so an item that is missing
    from the submission and cannot be reconstructed (a whole mandatory file such as the cover letter
    or Reporting Summary, a statement, an accession number, an unreadable field) is scaffolded with
    the literal, clearly marked placeholder "[AUTHOR TO COMPLETE: <what is missing>]", and every one
    is listed in the package's own final report (CHANGELOG.md / MANUAL_STEPS.md / REVISION_REPORT.md).
    The token is a PIPELINE convention; it is not manuscript content and it is not a defect.
  * The MARKER ITSELF is never a defect and never a difference between versions: do not report,
    score, rank, reward or penalize its presence, absence, wording or count, and never "fix" one by
    guessing at content. Dispose a hygiene row that matches it (for example the M6 sweep's "[AUTHOR]"
    pattern) as "pipeline hand-off placeholder -- manual item, carried forward", and put it in the
    manual-verification list instead of filing a finding about the marker.
  * The UNDERLYING gap still counts as what it is -- an item missing from the version that lacks it
    -- and is scored exactly as it would be if that version had simply omitted the item with no
    marker at all. A version carrying a marker must therefore be compared like an otherwise identical
    version without one: the marker never makes a version worse, and never makes it better.
  * Never introduce a placeholder where real content exists, never delete or reword one, and never
    "complete" one out of your own knowledge; fill one in only when the missing content is verifiably
    present elsewhere in the corpus (that is a normal edit and the marker goes away).
  * SEARCHABLE MARKERS ARE THE PIPELINE'S JOB. A placeholder that asks for a findable fact -- a
    preprint/DOI/accession/database id/ORCID/repository commit -- is classified `searchable`, and the
    orchestrator answers it BEFORE your session with its own public-API lookups: read
    `work/PLACEHOLDER_LOOKUP.md` (and `work/IDENTIFIERS.md`) and dispose every row.
      - verdict `found`  -> replace the marker with the fact (naming the identifier it found);
      - verdict `absent` -> replace the marker with the VERIFIED NEGATIVE in the author's own voice,
        e.g. "Preprints: not posted." or "not yet deposited (checked <date>)". This is NOT invention:
        a recorded, dated, reproducible search that returned nothing is evidence, and a marker that
        the pipeline answered may not be shipped;
      - verdict `error`/`skipped` -> the lookup could not answer (offline / `--placeholder-lookup
        off`): leave the marker and put the failed query in MANUAL_STEPS.md;
      - `author-only` facts (funding, consent, a decision, an identity you cannot confirm) keep the
        marker and go to MANUAL_STEPS.md.
    A `searchable` marker whose lookup verdict is `found` or `absent` and is still present in a
    delivered package is a FAILED run (the postcheck points at the exact lookup row).
  * PLACEHOLDER FILES. A corpus file can stand in for data it does not contain (a haplotype,
    annotation or table copied from another sample, a dummy file). When your session receives the
    evidence pack, its "Placeholder files -- ignored" list is authoritative -- and a file that
    carries another sample's name/content is one even when no list names it. Never use one as a
    producer, a source or a contradicting fact, and never "verify" a claim against one: a claim
    that rests only on a placeholder input is `unable -- placeholder input; the real data is not
    in the corpus`, and the author must supply or remove the file."""

# ---------------------------------------------------------------------------
# `--author-to-complete off` / `--author-to-complete document` (2026-10-17).
#
# The placeholder above is a PIPELINE convention: a stage that must not invent
# content writes "[AUTHOR TO COMPLETE: ...]" into the document and lists the item
# for the author. That is the right default for an internal round -- the marker is
# the author's checklist -- but it is the WRONG behaviour for a package that is
# about to be uploaded: the 2026-10-17 audit of the two clean packages found
# `[AUTHOR TO COMPLETE: versions of bedtools, Seurat, cellsnp-lite and UCSC
# liftOver]` inside the SUBMITTED main text and a Reporting Summary that was
# nothing but a scaffold of five markers. The operator therefore chooses:
#
#   on  (default)  the marker convention, unchanged: a stage scaffolds a missing
#                  mandatory item with the token and lists it for the author.
#   off            NOTHING may carry the token. A missing item is left out of the
#                  document (or its scaffold) and written into the package's own
#                  manual-steps report instead, where a human reads it; an item
#                  the stage cannot supply is never marked inside a file that
#                  ships, and a marker that is still present is a DEFECT of that
#                  package rather than a neutral hand-off.
#
# The switch never changes what is true about the package: the underlying gap
# counts exactly as it did before (AGENTS.md rule 5: the marker never makes a
# version worse or better). What changes is only who carries the note -- the
# manuscript (document), a README in the submission directory (readme), or the
# manual-steps report (off) -- and whether a shipped marker is a defect.
#
# `readme` is the default: the hand-off items live in one README beside the
# cover letter and main text, so the author sees them with the submission while
# no submitted document carries the marker (a README*.md file is never submitted,
# rule 9). `document` keeps the old in-document marker convention; `off` moves
# the items out of the package into MANUAL_STEPS.md.
AUTHOR_TO_COMPLETE_MODES = ("readme", "document", "off")
DEFAULT_AUTHOR_TO_COMPLETE = "readme"
# The hand-off README's name: it matches `README*.md`, which the submission copy
# always drops (rule 9), so it can never ship by accident.
AUTHOR_TO_COMPLETE_README = "README-AUTHOR-TO-COMPLETE.md"
AUTHOR_TO_COMPLETE_README_HEADER = (
    "# Author to complete\n\n"
    "Items the submission still owes. Supply each item in the documents named "
    "below, then delete its row (and this file once no rows remain). This "
    "checklist is never submitted and no submitted document may depend on it.\n\n")
# The publisher owns only this block. Text and bullets outside it belong to the
# author/revision session and survive a re-publish; rows inside it are replaced
# from the CURRENT open-item ledger, so a resolved item cannot linger forever.
AUTHOR_TO_COMPLETE_MANAGED_BEGIN = (
    "<!-- pipeline-managed: author-to-complete rows; regenerated on publication -->")
AUTHOR_TO_COMPLETE_MANAGED_END = "<!-- end pipeline-managed author-to-complete rows -->"


def _atc_mode(value=None) -> str:
    """Normalise a policy value (mode string, bool or None) to a mode."""
    if isinstance(value, bool):
        return "document" if value else "off"
    s = str(value or "").strip().lower()
    if s in AUTHOR_TO_COMPLETE_MODES:
        return s
    return DEFAULT_AUTHOR_TO_COMPLETE


def handoff_target(mode=None) -> str:
    """Where a hand-off item belongs under `mode` (a file, or the manual steps)."""
    return (AUTHOR_TO_COMPLETE_README if _atc_mode(mode) == "readme"
            else "MANUAL_STEPS.md")


_HANDOFF_MARKER_RE = re.compile(
    r"\[\s*AUTHOR\s+TO\s+COMPLETE\s*:?\s*(.*?)\s*\]", re.I | re.S)


def _handoff_items_from_manual_steps(text: str) -> list:
    """The author-action lines a MANUAL_STEPS.md carries in marker form.

    The readme mode's prompt tells a stage to write the hand-off README
    directly. This extractor is the mechanical fallback for a stage that left
    the same item in its MANUAL_STEPS.md with the literal marker: the item is
    MOVED (marker removed, surrounding sentence kept), never invented, so a
    missing README cannot silently drop the author's work item.
    """
    out, seen = [], set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or not _HANDOFF_MARKER_RE.search(line):
            continue
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)
        cleaned = _HANDOFF_MARKER_RE.sub(lambda m: m.group(1).strip(), line)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .;:")
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def ensure_handoff_readme(ctx: Ctx, pkg_dir: Path, warns: list = None,
                          rec: dict = None) -> dict:
    """Materialize the author hand-off README from a stage's MANUAL_STEPS.md.

    `author_to_complete: readme` (the default) makes
    `README-AUTHOR-TO-COMPLETE.md` the one place a missing submission item is
    recorded. The stage prompt asks the session to write it; when a session
    instead left the same item in `MANUAL_STEPS.md` with the literal marker,
    this function extracts the item into the README and removes the marker
    from the text it copies. The file lands in the package root beside the
    cover letter and main text, and the submission copy drops it because it
    matches `README*.md`.

    Returns {"path", "items", "generated_from"} (empty when the mode is not
    `readme` or there is nothing to move).
    """
    mode = author_to_complete_mode_of(ctx)
    if mode != "readme":
        return {}
    pkg_dir = Path(pkg_dir)
    manual = pkg_dir / "MANUAL_STEPS.md"
    if not manual.is_file():
        return {}
    try:
        items = _handoff_items_from_manual_steps(
            manual.read_text("utf-8", "replace"))
    except OSError:
        return {}
    if not items:
        return {}
    target = pkg_dir / AUTHOR_TO_COMPLETE_README
    existing = ""
    if target.is_file():
        try:
            existing = target.read_text("utf-8", "replace")
        except OSError:
            existing = ""
    known = {re.sub(r"\s+", " ", re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", ln)).strip().lower()
             for ln in existing.splitlines()
             if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", ln)}
    new = [it for it in items if it.lower() not in known]
    if not new:
        return {}
    if not existing.strip():
        existing = AUTHOR_TO_COMPLETE_README_HEADER
    elif not existing.endswith("\n"):
        existing += "\n"
    block = "".join(f"- {it}\n" for it in new)
    write_text_atomic(target, existing + block)
    note = (f"the stage did not write {AUTHOR_TO_COMPLETE_README}; {len(new)} hand-off "
            f"item(s) were moved there from MANUAL_STEPS.md (the marker text is removed, "
            f"the surrounding instruction is kept)")
    if warns is not None:
        warns.append(note)
    if rec is not None:
        rec["handoff_readme"] = {"path": target.relative_to(pkg_dir).as_posix(),
                                 "items": len(new), "generated_from": "MANUAL_STEPS.md"}
    return {"path": str(target), "items": len(new),
            "generated_from": "MANUAL_STEPS.md"}


def _clean_handoff_row(value) -> str:
    """One checklist row with marker syntax removed and whitespace collapsed."""
    row = _HANDOFF_MARKER_RE.sub(lambda m: m.group(1).strip(), str(value or ""))
    row = re.sub(r"\[\s*AUTHOR\s+TO\s+COMPLETE", "AUTHOR TO COMPLETE", row,
                 flags=re.I)
    return re.sub(r"\s+", " ", row).strip(" .;:")


def _readme_action_rows(text: str) -> list:
    """Bullet/numbered and Markdown-table data rows from one checklist."""
    rows, seen = [], set()
    separator = re.compile(r"^\s*\|?[\s:\-|]*\-[\s:\-|]*\|?\s*$")
    table_lines = []

    def add(value) -> None:
        row = _clean_handoff_row(value)
        if row and row.lower() not in seen:
            seen.add(row.lower())
            rows.append(row)

    def flush_table() -> None:
        nonlocal table_lines
        if not table_lines:
            return
        # A normal table has a header followed by its separator. A one-line
        # table has no header: that line is the row the checklist author wrote.
        if len(table_lines) == 1 and separator.match(table_lines[0]):
            data = []
        else:
            data = (table_lines[2:]
                    if len(table_lines) > 1 and separator.match(table_lines[1])
                    else table_lines)
        for line in data:
            add(" | ".join(cell.strip()
                           for cell in line.strip().strip("|").split("|")))
        table_lines = []

    for raw in str(text or "").splitlines():
        bullet = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$", raw)
        if bullet:
            flush_table()
            add(bullet.group(1))
            continue
        if raw.count("|") >= 2:
            table_lines.append(raw)
            continue
        flush_table()
    flush_table()
    return rows


def _split_managed_handoff_readme(text: str) -> tuple:
    """(author text, managed rows, had_managed_block) for a hand-off README."""
    pattern = re.compile(
        re.escape(AUTHOR_TO_COMPLETE_MANAGED_BEGIN)
        + r"\s*(.*?)\s*" + re.escape(AUTHOR_TO_COMPLETE_MANAGED_END),
        re.S)
    managed, had = [], False
    if pattern.search(str(text or "")):
        had = True

    def take(match):
        nonlocal managed
        managed.extend(_readme_action_rows(match.group(1)))
        return "\n"

    outer = pattern.sub(take, str(text or ""))
    return outer, managed, had


def _handoff_marker_occurrences(root: Path, problems: list = None) -> list:
    """Every literal hand-off marker in the package's submission-side files.

    Returns [{"file", "marker", "quote"}]. Evidence areas, README files and
    pipeline bookkeeping are skipped: their markers are not submission text.
    When the package carries an honoured submitted-set declaration, only its
    declared files are read -- a marker in a non-submitted `.tex` source must
    not become an author-action row for the journal package.
    """
    root = Path(root)
    out, seen = [], set()
    if not root.is_dir():
        return out
    _decl, is_submitted = declared_submission_filter(root)
    for p in sorted(_iter_tree_files(root, follow_dir_links=True)):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if not is_submitted(rel):
            continue
        if is_evidence_rel(rel) or is_code_rel(rel):
            continue
        if is_bookkeeping_name(p.name) or _is_aux_doc(p.name) \
                or is_non_submitted_readme_name(p.name):
            continue
        ext = p.suffix.lower()
        blocks = []
        try:
            if ext == ".docx":
                paras = _docx_paragraphs(p)
                if paras is None and problems is not None:
                    problems.append({"file": rel, "problem": "DOCX text could not be extracted"})
                blocks = paras or []
            elif ext == ".pdf":
                _txt = _pdf_text(p)
                blocks = _txt.splitlines() if _txt else []
            elif ext in (".md", ".txt", ".tex", ".ltx", ".rtf", ".html", ".htm"):
                blocks = p.read_text("utf-8", "replace").splitlines()
            elif ext == ".doc":
                if problems is not None:
                    problems.append({
                        "file": rel,
                        "problem": "legacy DOC text could not be searched for hand-off markers"})
        except Exception as e:                                    # noqa: BLE001
            if problems is not None:
                problems.append({"file": rel,
                                 "problem": f"{type(e).__name__}: {e}"})
            continue
        for block in blocks:
            for m in _HANDOFF_MARKER_RE.finditer(str(block)):
                marker = re.sub(r"\s+", " ", m.group(0)).strip()
                key = (rel, marker.lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append({"file": rel, "marker": marker,
                            "quote": re.sub(r"\s+", " ", str(block)).strip()[:320]})
    return out


def write_published_handoff_readme(root: Path, open_items: dict = None,
                                   residuals: dict = None,
                                   target_path: Path = None) -> dict:
    """Write the author checklist for a published package.

    The stage prompts ask a revision session to write the README. A package
    generated before that rule existed (or by a stage that forgot it) still has
    the author work recorded in the revision ledger and in the residual gate.
    This publisher-side pass copies those recorded items into ONE checklist.
    Publication passes `target_path` to keep it as a SIBLING of the judged
    directory, so the delivered corpus stays byte-identical to the pin. It never
    edits a document and never invents an item: every row is derived from a
    ledger/residual/marker row in the package itself. The rows it owns sit in a
    marked block that is REPLACED on every publish, so resolved items disappear;
    author text and bullets outside that block are preserved.
    """
    root = Path(root)
    rows, problems = [], []
    oi = open_items or {}
    # "discarded" rows are findings the auditor refused, not work the author
    # owes. Re-emitting one as a checklist item would make it impossible for
    # the author to clear the checklist, and readiness already reports the
    # unsupported discard separately.
    for it in oi.get("items") or []:
        if not isinstance(it, dict):
            continue
        fid = str(it.get("id") or "").strip()
        status = str(it.get("status") or "item").strip()
        check = str(it.get("check") or "").strip()
        sev = str(it.get("severity") or "").strip()
        loc = str(it.get("location") or "").strip()
        ev = re.sub(r"\s+", " ", str(it.get("evidence") or "")).strip()
        tag = " ".join(x for x in (check, sev) if x)
        text = (f"{fid + ' ' if fid else ''}[{status}"
                f"{'; ' + tag if tag else ''}] "
                f"{loc + ': ' if loc else ''}{ev}").strip()
        if text:
            rows.append(_clean_handoff_row(text))
    markers = _handoff_marker_occurrences(root, problems=problems)
    for occ in markers:
        payload = _clean_handoff_row(occ["marker"])
        rows.append(f"{occ['file']}: missing {payload or 'the marked item'}")
    # A summary residual can say "N hand-off markers" while the marker text
    # sits in a format this package cannot parse (for example an image-only
    # PDF). It is additive: another parsed row must not hide the unparsed one.
    for it in (residuals or {}).get("items") or []:
        if "hand-off marker" in str(it):
            rows.append(_clean_handoff_row(it))
    rows = [_clean_handoff_row(r) for r in rows if str(r).strip()]
    rows = list(dict.fromkeys(r for r in rows if r))
    target = Path(target_path) if target_path is not None \
        else root / AUTHOR_TO_COMPLETE_README
    if not target.is_file() and not rows and not problems:
        return {}
    existing = ""
    if target.is_file():
        try:
            existing = target.read_text("utf-8", "replace")
        except OSError as e:
            return {"error": f"could not read the existing checklist ({type(e).__name__}: {e})",
                    "problems": problems}
    external, _managed_rows, had_block = _split_managed_handoff_readme(existing)
    header = AUTHOR_TO_COMPLETE_README_HEADER.strip()
    # A stage-authored checklist has the standard header but no managed-block
    # markers. Its bullets are author work, not a disposable generated block:
    # preserve them exactly like any other text outside the managed region.
    # Rows that duplicate a current ledger item are omitted from the generated
    # block below, so this cannot duplicate an active row.
    external_rows = _readme_action_rows(external)
    known = {row.lower() for row in external_rows}
    managed_now = []
    seen = set()
    for row in rows:
        if row.lower() in known or row.lower() in seen:
            continue
        seen.add(row.lower())
        managed_now.append(row)
    base = external.strip()
    if not base:
        base = AUTHOR_TO_COMPLETE_README_HEADER.strip()
    base = re.sub(r"\n{3,}", "\n\n", base)
    result = {"path": (target.name if target.parent == root else str(target)),
              "items": len(managed_now),
              "external_items": len(external_rows),
              "generated_from": ("revision ledger" if oi.get("items") or oi.get("discarded")
                                 else "package hand-off markers")}
    author_text = external.strip()
    if author_text == header:
        author_text = ""
    if not managed_now and not external_rows and not author_text:
        if target.is_file():
            target.unlink()
        if problems:
            result["problems"] = problems
            return result
        return {}
    pieces = [base]
    if managed_now:
        pieces.append(AUTHOR_TO_COMPLETE_MANAGED_BEGIN + "\n"
                      + "".join(f"- {row}\n" for row in managed_now)
                      + AUTHOR_TO_COMPLETE_MANAGED_END)
    text = "\n\n".join(pieces).rstrip() + "\n"
    action = "unchanged" if existing == text else ("updated" if existing else "created")
    if action != "unchanged":
        write_text_atomic(target, text)
    if problems:
        result["problems"] = problems
    return result


PLACEHOLDER_RULE_OFF = """PIPELINE HAND-OFF ITEMS — the operator turned the marker convention OFF
(`--author-to-complete off`), so the literal token "[AUTHOR TO COMPLETE..." MUST NOT APPEAR
anywhere in a file you write:
  * An item that is missing from the submission and cannot be reconstructed (a whole mandatory file
    such as the cover letter or Reporting Summary, a statement, an accession number, a version, an
    unreadable field) is NEVER marked inside a document. Leave the item out of the document -- and,
    for a whole missing file, do not create a file that carries nothing but instructions -- and
    record it in the package's own MANUAL_STEPS.md / CHANGELOG.md / REVISION_REPORT.md with the
    precise step the author must take (which file, which section or field, what to supply).
  * Existing markers are yours to clear in the same spirit: fill one ONLY when the missing content
    is verifiably present elsewhere in the corpus (that is a normal edit and the marker goes away);
    otherwise REMOVE the marker text from the document (keeping whatever surrounding content is
    real) and move the item to the manual-steps report. Never guess at the content, never write a
    bare "[TO BE COMPLETED]"-style substitute, and never leave a marker in place: with this option
    off, a shipped marker is a defect of the package, not a neutral hand-off.
  * SEARCHABLE ITEMS ARE THE PIPELINE'S JOB. A missing findable fact -- a preprint/DOI/accession/
    database id/ORCID/repository commit -- is classified `searchable`, and the orchestrator answers
    it BEFORE your session with its own public-API lookups: read `work/PLACEHOLDER_LOOKUP.md` (and
    `work/IDENTIFIERS.md`) and dispose every row.
      - verdict `found`  -> write the fact into the document (naming the identifier it found);
      - verdict `absent` -> write the VERIFIED NEGATIVE in the author's own voice, e.g. "Preprints:
        not posted." or "not yet deposited (checked <date>)". This is NOT invention: a recorded,
        dated, reproducible search that returned nothing is evidence;
      - verdict `error`/`skipped` -> the lookup could not answer (offline / `--placeholder-lookup
        off`): leave the item out of the document and put the failed query in MANUAL_STEPS.md;
      - `author-only` facts (funding, consent, a decision, an identity you cannot confirm) go to
        MANUAL_STEPS.md.
  * The rule binds every file you write, including a scaffold you create for a mandatory item and
    any report that ships beside the documents.
  * PLACEHOLDER FILES. A corpus file can stand in for data it does not contain (a haplotype,
    annotation or table copied from another sample, a dummy file). When your session receives the
    evidence pack, its "Placeholder files -- ignored" list is authoritative -- and a file that
    carries another sample's name/content is one even when no list names it. Never use one as a
    producer, a source or a contradicting fact, and never "verify" a claim against one: a claim
    that rests only on a placeholder input is `unable -- placeholder input; the real data is not
    in the corpus`, and the author must supply or remove the file."""

# `readme` (the default): the hand-off items live in ONE README in the package
# root, beside the cover letter and main text. The literal token stays forbidden
# in every file (a submitted document in particular); the README is the author's
# checklist and is never part of the submission (README*.md is dropped, rule 9).
PLACEHOLDER_RULE_README = """PIPELINE HAND-OFF ITEMS — the operator chose the README hand-off
(`--author-to-complete readme`, the default), so the literal token "[AUTHOR TO COMPLETE..."
MUST NOT APPEAR in any document or in the hand-off README:
  * An item that is missing from the submission and cannot be reconstructed (a whole mandatory file
    such as the cover letter or Reporting Summary, a statement, an accession number, a version, an
    unreadable field) is NEVER written into a document. Leave the item out of the document -- and,
    for a whole missing file, do not create a file that carries nothing but instructions -- and
    record it in ONE file in the package root, `README-AUTHOR-TO-COMPLETE.md`, beside the cover
    letter and main text. Give each item its own row: the document and section (or field), what is
    missing, and the precise step the author must take (what to supply, where). Create the README
    only when there is at least one item; update it as items are resolved and delete it when none
    remain.
  * The README is the author's checklist, never submission content: a submitted document may not
    depend on it, and the submission copy drops it (it matches README*.md). Do not put prose,
    citations or data in it.
  * EXISTING DOCUMENT MARKERS. A review, audit or probe session never edits a package: it reports
    the underlying gap as a finding and never scores the marker itself. A package-producing stage
    (revise/rewrite/integrate) fills a marker ONLY when the missing content is verifiably present
    elsewhere in the corpus (that is a normal edit and the marker goes away); otherwise REMOVE the
    marker text from the document (keeping whatever surrounding content is real) and move the item
    to the README. Never guess at the content, never write a bare "[TO BE COMPLETED]"-style
    substitute, and never leave a marker in a document: a shipped marker is a defect of the
    package, not a neutral hand-off.
  * SEARCHABLE ITEMS ARE THE PIPELINE'S JOB. A missing findable fact -- a preprint/DOI/accession/
    database id/ORCID/repository commit -- is classified `searchable`, and the orchestrator answers
    it BEFORE your session with its own public-API lookups: read `work/PLACEHOLDER_LOOKUP.md` (and
    `work/IDENTIFIERS.md`) and dispose every row.
      - verdict `found`  -> write the fact into the document (naming the identifier it found);
      - verdict `absent` -> write the VERIFIED NEGATIVE in the author's own voice, e.g. "Preprints:
        not posted." or "not yet deposited (checked <date>)". This is NOT invention: a recorded,
        dated, reproducible search that returned nothing is evidence;
      - verdict `error`/`skipped` -> the lookup could not answer (offline / `--placeholder-lookup
        off`): leave the item out of the document and put the failed query in the README;
      - `author-only` facts (funding, consent, a decision, an identity you cannot confirm) go to
        the README.
  * The rule binds every file you write, including a scaffold you create for a mandatory item and
    any report that ships beside the documents.
  * PLACEHOLDER FILES. A corpus file can stand in for data it does not contain (a haplotype,
    annotation or table copied from another sample, a dummy file). When your session receives the
    evidence pack, its "Placeholder files -- ignored" list is authoritative -- and a file that
    carries another sample's name/content is one even when no list names it. Never use one as a
    producer, a source or a contradicting fact, and never "verify" a claim against one: a claim
    that rests only on a placeholder input is `unable -- placeholder input; the real data is not
    in the corpus`, and the author must supply or remove the file."""

# The judge's half: the judge must not learn the pipeline's vocabulary, and under
# `off` the marker is no longer neutral -- a package that ships one has content the
# author still owes, and the judge scores that the same way it scores any other
# missing content (never the marker's own wording).
PLACEHOLDER_RULE_JUDGE_OFF = """PLACEHOLDER TEXT IN A PACKAGE (handle exactly this way):
  * A clearly marked placeholder (for example "[TO BE COMPLETED: ...]", a TODO note, or an
    equivalent bracket) marks content the author must still supply. Score the UNDERLYING gap
    exactly as you would score an otherwise identical package that simply omitted the item: the
    marker's own wording, count and presence are not a separate difference, and you never "fix" one
    by guessing at content.
  * The package was prepared under a no-placeholder policy, so an item left as a marker instead of
    being supplied (or instead of being moved to the package's own manual-steps list) is a
    completeness gap of that package: report it as such -- file, location, what is missing -- and
    never as a formatting nit."""

PLACEHOLDER_RULE_JUDGE_README = """PLACEHOLDER TEXT IN A PACKAGE (handle exactly this way):
  * A clearly marked placeholder (for example "[TO BE COMPLETED: ...]", a TODO note, or an
    equivalent bracket) marks content the author must still supply. Score the UNDERLYING gap
    exactly as you would score an otherwise identical package that simply omitted the item: the
    marker's own wording, count and presence are not a separate difference, and you never "fix" one
    by guessing at content.
  * The package was prepared under a no-placeholder-in-document policy, so an item left as a marker
    inside a document (instead of being supplied, or listed in the package's own hand-off README)
    is a completeness gap of that package: report it as such -- file, location, what is missing --
    and never as a formatting nit.
  * A hand-off README (a README*.md file) is the author's checklist, not submission content: its
    presence, absence or wording is never a scored difference."""


def author_to_complete_mode_of(ctx=None) -> str:
    """The root's hand-off policy: `readme` (default), `document` or `off`."""
    raw = ((getattr(ctx, "cfg", None) if ctx is not None else None) or {}).get(
        "author_to_complete")
    return _atc_mode(raw)


def author_to_complete_of(ctx=None) -> bool:
    """Whether the pipeline may write "[AUTHOR TO COMPLETE: ...]" hand-off markers.

    True only for the `document` mode (`--author-to-complete document`, or
    `set-author-to-complete document`). The default `readme` mode and `off` both
    forbid the token in a document and make a shipped marker a defect; they differ
    in where the hand-off item goes (the package's README vs MANUAL_STEPS.md).
    """
    return author_to_complete_mode_of(ctx) == "document"


def placeholder_rule_text(mode=None) -> str:
    """The hand-off rule the working sessions receive for `mode`."""
    mode = _atc_mode(mode)
    if mode == "document":
        return PLACEHOLDER_RULE
    if mode == "readme":
        return PLACEHOLDER_RULE_README
    return PLACEHOLDER_RULE_OFF


def placeholder_rule_judge_text(mode=None) -> str:
    """The same switch for the (provenance-free) comparison sessions."""
    mode = _atc_mode(mode)
    if mode == "document":
        return PLACEHOLDER_RULE_JUDGE
    if mode == "readme":
        return PLACEHOLDER_RULE_JUDGE_README
    return PLACEHOLDER_RULE_JUDGE_OFF


# The master-prompt excerpts and the end-of-prompt reminders RESTATE the
# scaffolding rule, and a restated opposite ("scaffold the missing item with the
# marker") would override the policy block above -- which is exactly how the
# contradiction would reach a session. Each row is (the text the excerpts carry,
# the same sentence under `readme`, the same sentence under `off`).
HANDOFF_PROMPT_REWRITES = (
    ('Missing mandatory items\n     are scaffolded only with clearly marked '
     '"[AUTHOR TO COMPLETE: ...]" placeholders, every one\n     listed in the final report.',
     'Missing mandatory items are NOT marked inside a document (`author_to_complete: '
     'readme`):\n     leave the item out of the document and record it in the package\'s '
     '`README-AUTHOR-TO-COMPLETE.md`\n     (beside the cover letter and main text), with the '
     'section, what is missing and the step to take.',
     'Missing mandatory items are NOT marked inside a document (`author_to_complete: off`,\n'
     '     `--author-to-complete off`): leave the item out of the document and list it in\n'
     '     the final report.'),
    ('A\nmissing mandatory item is scaffolded ONLY with the literal "[AUTHOR TO COMPLETE: ...]" '
     'marker and\nlisted for the author: that marker is a hand-off item, never content to invent '
     'and never something\nto "clean up" by guessing.',
     'A missing mandatory item is NOT marked inside the document (`author_to_complete: readme`): '
     'leave it out of the file and record it in the package\'s `README-AUTHOR-TO-COMPLETE.md` -- '
     'the item is never content to invent and never something to "clean up" by guessing.',
     'A missing mandatory item is NOT marked inside the document (`author_to_complete: off`, '
     '`--author-to-complete off`): leave it out of the file and list it in MANUAL_STEPS.md -- '
     'the item is never content to invent and never something to "clean up" by guessing.'),
    ('Hand-off markers ("[AUTHOR TO COMPLETE: ...]") are manual items for\nthe author: preserve '
     "the base's markers, never invent the missing content, and never treat a marker\nas a defect "
     'or as a difference worth scoring.',
     'Hand-off markers ("[AUTHOR TO COMPLETE: ...]") are not part of this package '
     '(`author_to_complete: readme`): if the base carries one, remove the marker text (keeping '
     'the real content around it) and record the item in `README-AUTHOR-TO-COMPLETE.md`; never '
     'invent the missing content, and never score the marker itself.',
     'Hand-off markers ("[AUTHOR TO COMPLETE: ...]") may not exist in this package '
     '(`author_to_complete: off`, `--author-to-complete off`): if the base carries one, remove '
     'the marker text (keeping the real content around it) and move the item to '
     'MANUAL_STEPS.md; never invent the missing content, and never score the marker itself.'),
    ('Anything missing from the submission (a whole mandatory\n     file, a statement, an '
     'accession number) is scaffolded ONLY with the literal\n     "[AUTHOR TO COMPLETE: ...]" '
     'marker and listed for the author.',
     'Anything missing from the submission (a whole mandatory file, a statement, an accession '
     'number) is NOT marked inside the document (`author_to_complete: readme`): leave it out and '
     'record it in `README-AUTHOR-TO-COMPLETE.md`.',
     'Anything missing from the submission (a whole mandatory file, a statement, an accession '
     'number) is NOT marked inside the document (`author_to_complete: off`, '
     '`--author-to-complete off`): leave it out and list it in MANUAL_STEPS.md.'),
    # The rewrite prompt's canonical-output block restates the marker rule in a
    # place the master-prompt excerpts above do not reach. The 2026-10-17
    # README-mode audit found it still saying "required whenever the [AUTHOR TO
    # COMPLETE ...] marker ... exists" under every mode.
    ('  rewritten/MANUAL_STEPS.md    — every hand-off item for the author (required whenever the\n'
     '        "[AUTHOR TO COMPLETE: ...]" marker, an unreadable live field, or an unfixable '
     'formatting\n        problem exists), with precise step-by-step instructions.',
     '  rewritten/MANUAL_STEPS.md    — every manual step the author must take (an unreadable\n'
     '        live field or an unfixable formatting problem), with precise step-by-step '
     'instructions.\n'
     '  rewritten/README-AUTHOR-TO-COMPLETE.md — one row per missing submission item (a\n'
     '        statement, a whole mandatory file, an accession number): the document and section,\n'
     '        what is missing, and the step the author must take. Create it only when at least\n'
     '        one item exists.',
     '  rewritten/MANUAL_STEPS.md    — every hand-off item for the author (an unreadable live\n'
     '        field or an unfixable formatting problem exists), with precise step-by-step\n'
     '        instructions; a missing submission item is listed here too, never as a marker in a\n'
     '        document.'),
)


def apply_author_to_complete_prompt(text: str, mode=None) -> str:
    """Make every restatement of the scaffolding rule agree with the policy.

    One place, applied to every prompt the pipeline writes: in `readme` and
    `off`, each excerpt that tells a session to scaffold a missing item with the
    literal marker is replaced by the same sentence under that policy. The
    replacements are exact strings on purpose -- a rewrite that silently failed to
    match would leave two contradictory instructions in one prompt, so the
    consistency suite asserts each row still matches its prompt.
    """
    mode = _atc_mode(mode)
    if mode == "document":
        return text
    idx = 1 if mode == "readme" else 2
    for row in HANDOFF_PROMPT_REWRITES:
        text = text.replace(row[0], row[idx])
    return text

# ---------------------------------------------------------------------------
# THE SHARED RULE SET — injected VERBATIM into every session prompt.
#
# The sessions drifted apart in a real run: an integration session was invited
# to IGNORE a "cosmetic-only difference" while the comparison sessions SCORED a
# formatting/writing difference as a minor row; the adopted checks M21-M24 were
# in the review's checklist and in nobody else's; the audit session had no
# disposition bar at all. The cure is mechanical: one text, one place, present
# in every prompt, plus a drift test (.paper_test/test_agent_consistency_2026_0922.py)
# that fails if any prompt loses a block or gains a private rule.
#
# It is provenance-free by construction (the comparison session must be able to
# carry it verbatim): no round/arm/order vocabulary, no bookkeeping file names.
# ---------------------------------------------------------------------------

SHARED_DECISION_BLOCK = """

=== THE SHARED DECISION RULES (identical in every session; only YOUR deliverable differs) ===
D1. ONE vocabulary. Every difference, finding and residual is named by its CLASS and SEVERITY.
    Classes, highest priority first: correctness > preservation > completeness > consistency >
    writing > formatting. Severities, a DISTANCE FROM CORRECT in every class: Fatal > Critical >
    Major > Minor. A difference that cannot be named in that vocabulary is COSMETIC and counts 0 --
    for everyone. A difference that CAN be named is never cosmetic: `formatting` and `writing` rows
    are graded on the same four rungs as every other class, and always counted by whichever session
    stands in front of the package.
    EVERY TWO-SIDED CHECK IS RUN IN BOTH DIRECTIONS, and a check reported from ONE side has not
    been run: a claim can be too strong (an overclaim) or too weak (an underclaim -- a supported
    result hedged into vagueness); content can be lost (preservation) or invented (correctness);
    an item can be missing or unneeded; a claim can carry no pointer or a printed/promised item
    can carry no description; an availability claim can be stronger or weaker than the verified
    locator. The underclaim direction is a real defect of the same class as the overclaim
    direction, never a neutral "more careful" wording: a version that weakens a supported claim
    is worse than one that states it, exactly as a version that exaggerates is.
D2. FOUR dispositions, one meaning each, for every item a session touches:
      resolved  the package now fixes it (record the before -> after text);
      carried   it cannot be fixed here: it goes to the package's single manual list (the file the
                bookkeeping convention names) with `what to check | where | why it is not
                automatic | exact tool steps`;
      dropped   it is not a defect, WITH the reason (see D3);
      added     a defect this session found that the list it received did not contain.
    Every item ends in exactly one of the four. "Not addressed" is not a disposition, and a
    problem a session surfaces but cannot fix is `carried`, never a private note.
D3. NOTHING NAMEABLE MAY BE DISCARDED. A `dropped` item needs its reason recorded: the quoted text
    does not exist where the item claims, or the item rests on a fact that is wrong, or the
    difference cannot be named in D1's vocabulary (cosmetic -- and then say so explicitly).
    "I disagree", "no journal rule", "editorial preference only" and "cosmetic-only" are NOT
    reasons for an item that names a `formatting` or `writing` defect: that is a counted row.
D4. ONE bar for a scanned row. A seeded row whose `tier` is `finding` is a defect an editor or a
    copyeditor would raise: file it (D2), or close it by naming its OWN bar and why this instance
    is inside it. The same blanket sentence across many rows is an UNFILLED artifact, and it fails
    the run in whichever session owns the table.
D5. ONE manual list per package. Every `carried` item, from any session, lands in that package's
    manual list in the D2 shape -- the author must never have to reconstruct why an item is there.
D6. ONE reading of the evidence. The orchestrator's code-side measurements (legend counts, section
    lengths, formatting rows with their `tier`, the numbers ledger with its `source`, the
    identifiers with their verification verdict, the concept families and the glossary) are the
    same numbers and the same rows in every session: use them instead of re-estimating, dispose or
    reconcile every row you are given, and state before -> after whenever your work changes one of
    them. Never contradict them silently; never edit them.
D7. ONE exception, and only one: a COMPARISON session gets the same vocabulary, the same bars and
    the same evidence definitions as every other session, but never provenance -- nothing that
    says which session produced which package, when, or in what order. Blindness to provenance is
    the only asymmetry this pipeline allows.
D8. A FACT IS NOT A REMOVAL SURFACE. Never resolve a finding by deleting the sentence, paragraph,
    table row, glossary entry, figure legend, or passage that carries a factual claim, number,
    unit, sample size, definition, method, limitation, result, or conclusion. A wrong value is
    resolved by carrying the correct value; a fact that looks misplaced, orphaned, awkwardly
    introduced, unused or redundant is resolved by relocating, merging, or connecting it. Deletion
    is allowed only for a true duplicate the finding itself names, and only when one copy of the
    same fact survives; record the survivor. When the only apparent remedy would remove a fact,
    the finding is not resolvable by deletion: dispose it as not-a-defect if it invents a rule,
    otherwise carry it to the manual list. This rule outranks a structural, packaging, length,
    style, or "unused item" finding whenever the two conflict, and it binds every role."""

ADOPTED_SWEEPS_BLOCK = """

=== THE ADOPTED CHECKS (the same checklist every session evaluates against) ===
  M1-M17  mechanical sweeps: acronyms, citations, display items, numbers/metrics, mandatory
          items, hygiene, cross-references, terminology, file hygiene, reference format, SI
          formatting, authors, reporting summary, cross-document metadata, numeric totals,
          abstract traceability, anomaly tokens. M4 includes the RANGE direction: a lower/upper
          pair printed high-to-low is a correctness candidate for any unit-bearing physical
          range, not only a CI; the M4 artifact lists every descending same-unit pair for
          disposition.
  M18     figure-legend word counts (recorded; a proxy cap is optional).
  M19     abstract/main-text length against the journal's relaxed caps, plus the cover-letter
          preference.
  M20     OOXML style/formatting rows, each carrying its `tier` (`finding` | `advisory`).
          This artifact `tier` is the ROW's priority in the review, NOT the judge's six scoring
          tiers (correctness/preservation/completeness/consistency/writing/formatting); the two
          vocabularies are independent and must never be conflated.
  M21     correspondence policy: reviewer exclusions, required disclosures, and whether a cover
          letter's claims about the work are supported by the manuscript itself -- in BOTH
          directions: a letter claim that exceeds the manuscript's evidence is an overclaim, and
          a supported result the letter leaves undersold is an underclaim.
  M22     data/code-availability integrity: the locator class (DOI / archive DOI / version-pinned
          repository URL / bare URL / accession) against the claim it carries, including whether
          two different pins of one repository are consistent with what the text asserts. Read it
          BOTH ways: a claim STRONGER than the locator supports ("permanent archive" on a
          version-pinned URL) and a claim WEAKER than the verified reality ("available on
          request" while the identifier lookup resolves a public deposit) are the same defect in
          opposite directions, never one finding and one silence.
  M23     supplementary parity: the supplement's numbers, cross-references, availability
          statements, abbreviation definitions and term choices against the main text.
  M24     concept/term families: one concept with competing surface forms, plus the glossary
          decision (definition, authoritative term, forbidden synonyms) and the per-occurrence
          sense audit that follows from it.
  J1-J4   scope fit and significance; scientific/statistical rigor; writing quality and claim
          calibration -- overclaiming AND underclaiming (the Q1-Q12 rubric); plagiarism,
          AI-content and policy compliance.
  EVERY two-sided check runs in BOTH directions, and a check reported from one side only has not
  been run: claim strength (overclaim / underclaim), content (lost / invented), items (missing /
  unneeded), pointers (claim without its evidence / printed or promised content the text never
  states), availability claims (overstated / undersold against the verified locator). The
  seeded `CLAIM_STRENGTH.md` table is the J3 surface for the claim-strength pair: dispose its
  `under` rows and its `over` rows.
  A check with no findings still gets its coverage row ("clean -- basis: <artifact/locations>");
  "not checked" is never an allowed value, and every row of every check gets a disposition (D2)."""


DISPOSITION_MANDATE = """

DECISION-ARTIFACT MANDATE — one disposition per seeded row, about THAT ROW's own bar:
  * Every seeded table under `review/artifacts/` (M18 caption words, M19 length, M20 formatting,
    M4/NUMBERS_LEDGER numbers, M8 terms, M24 concepts, GLOSSARY, IDENTIFIERS, PLACEHOLDERS,
    PLACEHOLDER_LOOKUP, OUTLINE, CLAIM_STRENGTH, M2_references, M30_hierarchy_reconciliation)
    must end with exactly one row per instance and a disposition per row: a finding id, or
    `OK — <the bar this instance is inside, and why>`.
    M2_references is the citation sweep's integrity seed: one row per reference entry that
    carries a DOI, with the orchestrator's own public-API verdict for it (`absent` = BOTH
    registries answered no -- a DOI the reader cannot resolve) and the code-side signals (a
    year token inside the DOI that contradicts the entry's own year, one DOI on two entries).
    A `found` record that names a DIFFERENT work than the entry is a finding; an
    `error`/`skipped`/`not selected` row is `unable — <why>`, never a clean.
    M30_hierarchy_reconciliation is the sweep's seed: table A pairs every written number the
    shipped data tables do NOT prove with its candidate producer column(s) and the check the code
    could make; table B lists the code/config literals (the producer side of a Methods parameter).
    Dispose both tables and ADD the producers the code cannot see (a figure's generating code, a
    protocol step's implementation, a sample set against the data's own rows); `unable — the
    producer is not in the corpus` is a RECORDED row, never a silent clean, and the authoritative
    side is always the standing source hierarchy.
    CLAIM_STRENGTH carries BOTH directions of the J3 calibration check (`under` = a hedge the
    evidence may not require, `over` = a maximal claim the evidence may not support); a session
    that disposes one direction and leaves the other undisposed has not run the check, and a
    single-direction reading of the corpus is exactly the one-sided defect this table exists to
    stop.
  * ROW SHAPE IS PART OF THAT CONTRACT: keep the seeded columns exactly as they are and write
    exactly one cell per column, in order, with your verdict IN the `disposition`/`resolution`
    cell (the LAST column of the row). A row that is one cell SHORT is read POSITIONALLY: the
    verdict lands in the column before the disposition cell and the postcheck reports the row as
    undisposed -- a real review rewrote OUTLINE.md's 185 rows that way and the whole session was
    re-run. If you rewrite a table with a script, build every row from the header's own column
    list and print the column count of the first and last row before you finish.
  * A row whose `tier` column says `finding` is a defect an editor or a copyeditor would raise.
    "No journal rule", "editorial preference only", "not an error", "cosmetic" are NOT dispositions
    for such a row: a writing-quality defect does not need a journal rule to exist. Either file the
    finding or name the row's OWN bar and why this instance is inside it ("the sentence is inside a
    Methods enumeration; the Methods bar is 61 words" is a disposition; "no journal rule" is not).
  * Never close many rows with the SAME sentence. The postcheck counts repeated dispositions: a
    blanket rationale shared by many finding-tier rows is recorded as an UNFILLED artifact, and
    `decide --residual-gate` refuses to certify the run on it. The `--strict-artifacts` policy
    decides what happens to the attempt: `on` fails it, `fix` first offers these tables ONE scoped
    repair session (which may fill cells from the rows' own evidence, and nothing else), and `off`
    only records the report. Real example this rule exists for: 96 scan rows closed with one
    identical sentence, with the operator's own complaints inside that pile.
  * The `disposition` cell is NEVER the row's own `tier` (`finding` / `report` / `advisory`), a
    bare `OK` or a bare `clean`: those are unfilled cells, and when many rows carry the same one
    the postcheck fails the attempt on the boilerplate rule. Write the rule id the row itself
    carries plus why THIS instance is inside its bar (e.g. `FMT-T9c: Methods enumeration, bar 61
    words, this row is 47`), or -- when the row IS a defect -- file the finding and put its
    `F-…` id (or a `finding id` reference) in the cell.
  * OUTLINE.md is the same kind of artifact: a `summary` copied back from `first sentence`, an empty
    summary cell, or one verdict on every row is unfilled, not audited.
  * A `searchable` hand-off placeholder (`[AUTHOR TO COMPLETE: ... ]`) that
    `review/work/PLACEHOLDER_LOOKUP.md` answers is NOT a manual item any more: its lookup verdict is
    evidence (`found` -> the fact; `absent` -> the verified negative), so it becomes a finding the
    revision stage must resolve. Only an `author-only` marker (or a lookup that could not run) stays
    on the manual list.
"""

# EVERY session classifies a defect in this one vocabulary (see
# defect_class_rule()). The review's category numbers come from the skill
# (`paper-review/references/sweeps.md` -> CLASSIFICATION); the comparison session
# scores by the same six classes, so the bridge has to be spelled out in both
# directions: without it a reviewer's "category 2" and a judge's "formatting" can
# describe the same edit, and the panel then reads a fixed defect as no change.
DEFECT_CLASS_RULE_TEMPLATE = """DEFECT CLASSES — ONE VOCABULARY FOR EVERY SESSION (every session classifies a
defect the same way; only the deliverable differs):
  * @@TIER_COUNT@@ scored classes, in this fixed priority order (highest first): @@TIER_ORDER@@.
  * Every issue, finding, edit and comparison item belongs to exactly one of them, chosen by the
    DEFECT and not by the document it was found in. The identification taxonomy's category
    numbers (0-5, see the skill's `sweeps.md`) map onto the classes; where a category splits,
    classify by the concrete defect:
      - category 1 (Completeness & Factual Integrity) -> @@T_CORRECTNESS@@ (a factual error, a
        wrong number/DOI/reference key, a broken cross-reference) or @@T_COMPLETENESS@@ (a
        mandatory item that is missing);
      - category 0 (Editor/Reviewer Concerns) -> @@T_CORRECTNESS@@ (an unsupported claim, an
        overclaim, an UNDERCLAIM -- a claim or conclusion weaker than the evidence supports, the
        same defect read in the other direction -- a rigor or ethics problem),
        @@T_COMPLETENESS@@ (required information or data availability missing) or
        @@T_PRESERVATION@@ (content or a limitation that was removed);
      - category 2 (Writing Quality, Logic and Repetition) -> @@T_CONSISTENCY@@ when the same
        thing is said, spelled or numbered two ways, or a convention is applied in one place and
        not another; @@T_CORRECTNESS@@ when the wording changes the meaning (a claim that
        becomes wrong, a number attributed to the wrong metric, a claim whose STRENGTH no longer
        matches the evidence in either direction -- an overclaim or an underclaim);
        @@T_WRITING@@ when it is a word, verb or connector that is less precise, less idiomatic
        or less academic than the alternative the register itself uses, or a grammar, spelling,
        punctuation, logic, coherence, redundancy or segmentation slip that changes no MEANING
        (graded on the same four rungs as every class: a slip that costs the reader nothing is
        Minor, one that recurs or leaves a scope's topic unclear is Major, prose nobody can follow
        is Critical/Fatal; a row whose evidence shows the meaning changed is refiled to
        @@T_CORRECTNESS@@); @@T_FORMATTING@@ only when the difference is purely mechanical
        (character spacing, line or paragraph breaks) and carries no prose quality -- those are
        the format sweep's own rows;
      - category 3 (Plagiarism / AI-generated content) -> @@T_CORRECTNESS@@ (the integrity of the
        content itself); category 4 (Technical Formatting) -> @@T_FORMATTING@@ for the M18/M19/M20
        COSMETIC rows, or @@T_COMPLETENESS@@ / @@T_CORRECTNESS@@ when the row damages the delivered
        artifact (see the artifact-damage rule above); category 5 (Missing / Unneeded
        Information) -> @@T_COMPLETENESS@@.
 * Severity has FOUR RUNGS, and it is a DISTANCE FROM CORRECT in EVERY class -- correctness,
   preservation, completeness, consistency, prose and formatting alike. FATAL = the artifact or
    the claim is unusable (a deliverable that cannot be opened or read, a rendering with no
    readable text, a fabricated result presented as established) AND no usable copy of that
    content ships elsewhere in the package (a broken render beside an intact editable source is a
    packaging/completeness item, not a fatal one); CRITICAL = the error changes a
    conclusion, contradicts the data, or is a category impossibility (a fabricated number or
    citation, a claim the data refute, a wrong species or kind); MAJOR = the error changes a
    reported fact, attribute, comparison or sample set, but not the paper's conclusion (a wrong age
    band, sex, unit or cohort label is the typical case), or a prose/formatting failure a reader
    must work around -- a slip that RECURS through a paragraph or section, or that leaves a scope's
    topic unclear, is MAJOR rather than several more MINOR rows, because the structural level a
    defect reaches is part of its distance from correct; MINOR = a detail that changes no claim,
    reported fact or downstream number (the closest miss: an adjacent value, a wording slip whose
    meaning survives). A finding's
    (category, severity) and a compared item's (class, severity) must come from the SAME defect and
    the SAME rung; "it is a factual error" alone does NOT make every rung CRITICAL, and a prose or
    formatting defect is NOT thereby barred from MAJOR, CRITICAL or FATAL.
  * A claim BOTH versions get wrong is scored by the DISTANCE between the two errors: file the
    opponent's error as a `resolved` row and the target's error, when it still has one, as an
    `introduced` row, each at its OWN rung. Two rows of the same rung cancel -- which is exactly
    "neither version is closer to the truth"; two rows of different rungs leave the difference.
  * ARTIFACT DAMAGE IS NOT COSMETIC FORMATTING: a rendered blank page, a figure or table that did
    not print, or an unreadable rendering is classified by what it DAMAGES, never filed as a
    cosmetic formatting row -- content missing from the delivered artifact is @@T_COMPLETENESS@@
    (one displaced page/figure = minor, several pages or a whole section = major, an artifact with
    no usable copy of its content = fatal), and an artifact that is corrupt or not what the authors believe they
    submitted is @@T_CORRECTNESS@@. A figure embedded at a size whose width-to-height ratio does
    not match its own image file is artifact damage too: the delivered figure no longer shows the
    geometry its source encodes (a visibly distorted figure is at least major; a distortion that
    changes the apparent data is correctness-tier). A ONE-OFF stray empty line, a spacing slip, an
    italic/quotation treatment or a mixed URL style is COSMETIC (0) -- it becomes
    @@T_CONSISTENCY@@ when the same convention is broken repeatedly instead -- and a
    @@T_FORMATTING@@ row is graded by the same four rungs (a cosmetic slip that is filed at all
    stays minor; damage a reader must work around is major). A blank line is not a blank PAGE: the
    break-only paragraph that pushes a page break is artifact damage, graded by the extent of
    what it displaces. A length/caption row (`M18`/`M19`) is always a @@T_FORMATTING@@ MINOR row:
    the venue's relaxed length margins mean slight over-length is intended, so length may move a
    comparison by at most one point and is NEVER a scoring tier of its own.
  * PAGE BUDGETS ARE PART OF THE DELIVERED ARTIFACT: the front page must hold the title, the
    authors, the affiliations, the abstract AND the keywords together, and the cover letter must
    render to at most TWO pages AND keep its TOTAL content (salutation, body, disclosures and
    signature) @@COVER_LETTER_TOTAL_CLAUSE@@. A keywords line that starts page 2, or a third cover-letter
    page, is a formatting row graded MAJOR -- the reader must work around it -- and it is decided
    by the DELIVERED layout, not by the cached page property. Never shorten a scientific claim to
    reach a budget: cut boilerplate and redundancy, or hand the compression to the author.
  * An improvement claim must name the class it improves and the concrete item behind it, with a
    location: "this edit is better" without one is not an improvement claim. A difference that
    cannot be named in this vocabulary is COSMETIC and counts 0 for every session. A difference
    that CAN be named is never cosmetic -- `formatting` and `writing` included: every row is
    counted at its own class and rung, and only the class ORDER decides which differences count
    first. Dropping a nameable difference is itself a `consistency`-tier defect.
  * What differs between sessions is the DELIVERABLE, not the vocabulary: an identification
    session reports findings and never scores; a comparison session scores one target against one
    opponent and never ranks; a package-producing session resolves findings in its own copy and
    records one ledger row per finding, never a score. The same defect must keep the same class
    from the session that finds it to the session that scores the result."""


def defect_class_rule(profile=None) -> str:
    """The shared defect-class block (filled from BASIS_TIERS, so it cannot drift).

    The cover-letter total cap comes from the selected venue profile, exactly
    like the standing exemptions: a profile that configures no total cap must
    not be given a number in this block while `length_rule_text` says no cap is
    configured.
    """
    cover_total = _as_profile(profile).length_limits()["cover letter"].get("total_max")
    cover_clause = (f"within {cover_total} words" if cover_total is not None else
                    "with no total-word cap (this profile configures none)")
    out = (DEFECT_CLASS_RULE_TEMPLATE
           .replace("@@TIER_COUNT@@", str(len(BASIS_TIERS)))
           .replace("@@TIER_ORDER@@", "  >  ".join(BASIS_TIERS))
           .replace("@@COVER_LETTER_TOTAL_CLAUSE@@", cover_clause))
    for tier in BASIS_TIERS:
        out = out.replace(f"@@T_{tier.upper()}@@", tier)
    return out


def shared_blocks() -> str:
    """The shared decision rules + the adopted checklist, verbatim for every session.

    ONE text, appended to every prompt: the sessions cannot agree on a
    vocabulary they each describe differently, and a session cannot apply a bar
    it was never told about. The comparison session receives the same two blocks
    (they carry no provenance); its extra blindness rule is added separately.
    """
    return (SHARED_DECISION_BLOCK + ADOPTED_SWEEPS_BLOCK + RAW_DATA_READONLY_RULE
            + CONTEXT_BUDGET_RULE)


CONTEXT_BUDGET_RULE = """

=== CONTEXT BUDGET — READ EVERYTHING, BUT DO NOT PASTE EVERYTHING ===
  * Read large documents and evidence files sequentially in bounded slices, taking notes in
    your work directory as you go. Never `cat` an entire large JSON/CSV/log, print thousands of
    ledger rows, or re-read from the beginning after each edit.
  * When a command can produce a large result, write it to a file and inspect the needed lines,
    counts or columns. Keep your own decisions and evidence quotes in a compact work note
    rather than carrying every source passage in the conversation.
  * For rendered documents, inspect a CONTACT SHEET covering every page first, then open
    full-resolution page images only for suspected defects and the key title/caption pages. Do
    not reopen pages already inspected.
  * This is a context-transport rule, not a coverage exemption: every file and page still has
    to be examined. A provider request that exceeds its payload/context limit cannot be resumed;
    finish the pass in one context by keeping working notes on disk.
"""


def with_context_budget(text: str) -> str:
    """Append the context-budget rule to a prompt that does not carry it.

    `shared_blocks()` covers the stages that use it, but the one-shot prompts
    (template/guideline conformation, continuation, artifact repair, add-venue)
    and the two independent audit sessions build their text directly. The README
    promises EVERY prompt carries the rule, so those builders pass through this
    one wrapper instead of repeating the block (or silently missing it).
    """
    if "=== CONTEXT BUDGET" in (text or ""):
        return text
    return (text or "").rstrip() + "\n" + CONTEXT_BUDGET_RULE


# The corpus's raw-data directory is an INPUT (see enforce_readonly_raw_data):
# this block is what makes a session leave it alone in the first place, and what
# keeps the rule from being read as a scoring criterion by the comparison
# session.
RAW_DATA_READONLY_RULE = """

=== THE EVIDENCE AREAS ARE READ-ONLY AND ARE NEVER SUBMISSION CONTENT ===
  * The corpus carries its EVIDENCE in top-level areas, beside the submission documents:
      - `raw_data/`: the data tables, figure/table sources and the analysis snapshot the
        author's own scripts regenerate -- the PRODUCER side of the written claims;
      - `human_review_feedback/`: the REAL editors'/reviewers' comments from the previous
        submission (decision letters, referee reports, editor correspondence). It may also hold
        the authors' PREVIOUS response-to-reviewers documents; those are CONTEXT for what was
        promised, never the journal's letter and never a concern source. When it carries a child
        directory `original_submission/`, that child is the manuscript version the previous
        journal's editors/reviewers ACTUALLY SAW -- the version their comments were written
        against. It is EVIDENCE (an earlier, reviewer-visible version), never the current
        submission and never a candidate.
      - `llm_review_feedback/`: a machine-generated review of the previous submission whose
        FALSE POSITIVES WERE ALREADY FILTERED OUT upstream, so every remaining item is a real,
        addressable finding with the same standing as a human reviewer's point. It is EVIDENCE
        exactly like `human_review_feedback/`: never the authors' prose, never dismissed merely
        because a model wrote it, and never silently dropped.
  * No area is part of the submission and none is submitted to the journal. Nothing in
    them is a submission document: a file there is never a main-text, cover-letter, title-page,
    supplementary or figure document, whatever its name suggests, and its text is never the
    authors' prose. Never count it against a word limit, never sweep it for acronyms, citations,
    numbers, terminology or file hygiene, and never quote it as something "the submission says".
  * Nothing in any area may be edited, regenerated, rewritten, renamed, deleted or added to.
    A package carries them BYTE-FOR-BYTE, and a document that points into them
    (`\\input{raw_data/...}`, `\\includegraphics{raw_data/...}`) names the file that is there.
  * It is CHECKED, not merely requested: the orchestrator compares every area against the
    untouched original after every package-producing session and restores the original's copy,
    file by file. A change inside them therefore never reaches the submission -- it only costs
    the work.
  * No area is ever a SCORED difference BY ITSELF: no version is rewarded for changing raw
    data or the feedback files and none is penalized for leaving them exactly as they are. A
    "fixed" data table is not a `resolved` item and a copied feedback file is not an `added` one.
  * HOW THE EVIDENCE MAY BE USED:
      - M30 reads `raw_data/` as the producer side of a written claim's comparison;
      - every stage reads `human_review_feedback/` for what the review requires (the concern
        reconciliation and the response letter are built from it);
      - every stage reads `llm_review_feedback/` the same way, when the corpus carries it: its
        remaining findings were already filtered for false positives, so treat each one as a
        real concern with the same standing (the concern ledger and the response letter answer
        it too, and its provenance is kept in the ledger's `author`/`source` columns);
      - `human_review_feedback/original_submission/` (when present) may be read ONLY to resolve
        what a raised concern refers to and to decide whether the CURRENT manuscript (`base/`)
        already answers a concern the reviewers raised against the earlier version. Never edit
        it, never copy its text into a candidate package (all edits are made in `base/`), never
        sweep, count or quote it as the authors' current prose, and never treat it as a
        competing version: a concern that no longer exists in `base/` is `already-addressed`
        (quoting the `base/` location that answers it) or `not-applicable` (with the reason) --
        never a `to-fix` row whose only location is `original_submission/`;
      - a JUDGE sees every area in its anonymized view under the labeled `evidence/` directory
        (see the judge prompt): `raw_data/` may be used to check correctness/completeness, and
        the two feedback areas may be used to check whether a version ADDRESSES the raised
        concerns (a concern the target fails to answer while an opponent answers it is a
        completeness difference; it is a correctness difference when the text claims to answer
        it and does not). The feedback is IDENTICAL in every view, so it can never by itself say
        which version is better -- only the manuscript's handling of it can. Never quote a
        reviewer's or the LLM review's words as the authors' text, and never score a version by
        the reviewers' opinion."""


def _discovery_ids_line(ids) -> str:
    return ", ".join(str(i) for i in (ids or ())) or "(none)"


def _discovery_dropped_note(dropped) -> str:
    """The auditor-drops paragraph of the INTEGRATE block ("" when there are none)."""
    if not dropped:
        return ""
    rows = "; ".join(f"{i} -- {why or 'no reason recorded'}" for i, why in dropped)
    return (f"\n  * {len(dropped)} of these id(s) were DROPPED when the list was disposed (a "
            f"dropped finding is not in force; no version was asked to fix it): {rows}. Do not "
            f"port or reconcile anything FOR a dropped id -- record it as "
            f"`dropped -- not in force` if the ledger needs a row for it.")


def judge_discovery_block() -> str:
    """The judge's OWN discovery pass (see `JUDGE_DIRECTIVES`).

    The judge never receives another session's findings (complete blinding):
    instead it RE-DERIVES a bounded discovery pass of its own over every side --
    the target and every opponent, with the same candidates and depth -- records
    one disposed file per side under `judge_review/discovery/`, and files any
    class difference as a normal scored row. The wording names no provenance:
    the pass is about the CONTENT in front of the judge.
    """
    return """
=== YOUR OWN DISCOVERY PASS (`X-*`) — EVERY SIDE, THE SAME DEPTH ===

The fixed sweeps are finite; no checklist can be complete. Before you compare, run your OWN
bounded discovery pass (the spirit of $paper-review's phase-3 discovery pass; read the skill's
references/discovery.md for its discipline -- the bounded procedure below is what this sandbox
executes) over EVERY package you can see -- `target/` AND every `field/<label>/` -- with the SAME
candidates and depth for each side. You are the only source of these findings: no discovery list is
handed to you, and nothing about where a package came from is available or needed.

For EACH side, identically:
  * ENUMERATE class candidates: start from the seed list below, then add at least two of your own
    ("what else?" twice). A candidate is a question about a CLASS of defect, never an instance.
  * PROBE each candidate against that side's corpus, naming the files/regions you checked (use a
    script where one helps).
  * DISPOSE every candidate: `clean -- checked: <locations>`, or a finding row carrying a
    location, a category (0-5), a severity, a verbatim evidence quote and a one-line explanation.
    A candidate you cannot probe is recorded as a limitation, never silently dropped.
  * WRITE one file per side: `judge_review/discovery/target.md` for the target and
    `judge_review/discovery/<label>.md` for each opponent label. One table per file, one row per
    candidate, finding ids `X-001`, `X-002`, ... unique within the file.

Seed candidates (extend them):
  * a reporting number, label or unit the package's own shipped data or code does not support;
  * a convention (spelling, hyphenation, term family, numbering style) applied in one place and
    not another and owned by no frozen check;
  * an expected-but-absent value or label the package's own logic requires (a test, an n, an
    error-bar definition, a scale);
  * a present-but-unexpected token: leftover meta-commentary, a duplicated value that disagrees,
    a placeholder where content belongs;
  * boundary defects: the first and last sentence of every section and legend, and every heading;
  * sibling asymmetry: items of one family (panels, labels, sections) defined unevenly;
  * a claim/pointer pair where one side is missing or overrun (availability, sources, disclosures).

HOW THE PASS ENTERS YOUR SHEET: compare the sides' discovery files. A class ONE side carries and
the other does not -- or two sides carrying it at DIFFERENT rungs -- is a normal scored item in the
tier the shared defect-class rule gives the finding's category (classify by the concrete defect
when the category splits), cited by its id in the row's `check` cell:
  * the target no longer carries it while the opponent does  -> `resolved`;
  * the target carries it while the opponent does not        -> `introduced`;
  * both carry it at DIFFERENT rungs                         -> two rows, each at its own rung
    (a distance, not a swap);
  * both carry it at the same rung, or neither does          -> no row for it.
The `checks` coverage map stays the frozen M/J ids: your discovery findings are YOUR OWN
instrument, recorded in the files above and in the ledger rows -- never a frozen check id. Do NOT
propose new sweeps (there is no adoption path from this sandbox)."""


def discovery_parity_integrate_block(ids, dropped=()) -> str:
    """The integrator's discovery-parity block (port the X fixes; reconcile the list)."""
    ids = [str(i) for i in (ids or ())]
    if not ids:
        return """
=== THE ROUND'S DISCOVERY FINDINGS (`X-*`) ===

The round's review carries no frozen discovery findings (no phase-3 discovery round ran, or it
found none), so there is no extra list to reconcile here: the ledger's `finding effect` cells name
only the findings your donors and self/ actually cite. This is still not a review stage -- do not
author a discovery hunt and do not propose new sweeps."""
    return f"""
=== THE ROUND'S DISCOVERY FINDINGS (`X-*`) — FROZEN, INTEGRATE THE FIXES ===

The round's review ran the $paper-review skill's discovery round (D0-D5) against this round's BASE
corpus and its findings are the X-* list in `frozen_discovery/findings_extra.json` (readable copy:
`frozen_discovery/findings_extra.md`): READ-ONLY, the SAME list the round's revision arms
resolved. This is the ONE piece of the frozen review this sandbox consumes -- there is still no
`review/` directory, no F-* finding list and no A1 ledger here.

Why it matters: the revise arm(s) in your pool acted on this list, so a donor may carry a safe,
evidenced fix for an X defect that self/ (or another donor) still carries. Without the list those
edits look like unnamed/cosmetic differences and would be dropped under (e) -- silently losing the
round's revision work in the integrated package. Treat an X fix exactly like any other finding
fix:
  * self/ still carries the defect and a donor resolves it -> PORT the donor's fix (class (a)),
    and record the id in the ledger row's `finding effect` cell (`preserves X-001`).
  * self/ and a donor fix it differently -> decide by the source hierarchy (class (b)), and
    record the rejected alternative.
  * self/ already resolves it -> KEEP AS-IS (class (c)); never port an older wording back.
  * Never port an edit that makes an X finding WORSE or re-introduces the defect. If a donor's
    "fix" contradicts the hierarchy or the rest of the package, keep the safe reading and say so.
  * `integrated/DIFF_LEDGER.md` must reconcile EVERY X id listed below ({_discovery_ids_line(ids)})
    -- a ported row, a kept-base row, or one explicit "no donor carries a fix" row per remaining
    id -- so a resolution cannot be lost between the revise arm and the integrated package. The V3
    rescan re-locates the list in `integrated/` and records each id's state.
  * Do NOT author a discovery hunt of your own and do NOT propose new sweeps.{_discovery_dropped_note(dropped)}"""


def validation_block(role: str) -> str:
    """VALIDATION_RULE with the ONE role-specific substitution.

    A comparison session gets the same validation duty as everyone else (it is
    handed sources and may compile them), but the bookkeeping file the rule names
    is a provenance signal it must not learn; the substituted words keep the rule
    identical in substance and the drift test asserts the difference is exactly
    this one token.
    """
    if role == "judge":
        return VALIDATION_RULE.replace("MANUAL_STEPS.md", "your own review note")
    return VALIDATION_RULE


# The judge never sees the pipeline's own marker syntax (the view neutralizes it)
# and must not learn a vocabulary that would let it recognise a provenance signal
# in the content: this variant keeps the scoring rule -- a clearly marked
# placeholder is never a defect -- without naming the pipeline or its token.
PLACEHOLDER_RULE_JUDGE = """PLACEHOLDER TEXT IN A PACKAGE (handle exactly this way):
  * Any clearly marked placeholder (for example "[TO BE COMPLETED: ...]", a TODO note, or an
    equivalent bracket) marks content the author must still supply. Whether such a marker is
    present, absent, worded differently or counted differently is NEVER a scoring difference
    between two packages: do not report, score, rank, reward or penalize it, and never "fix" one
    by guessing at content. Record it as a manual-verification item instead.
  * The UNDERLYING gap still counts as what it is -- an item missing from the package that lacks
    it -- and is scored exactly as it would be if the package had simply omitted the item with no
    marker at all: the marker never makes a package worse, and never makes it better."""

AUX_FILES_RULE = """PIPELINE AUXILIARY FILES — "<name>.tracking-<token>.<ext>" and its fallback
"<name>.logging-<token>.<ext>":
  * Every one of those names is an AUXILIARY difference-tracking copy of "<name>.<ext>" written by
    the document-editing tooling or by the orchestrator, not a document of its own. For .docx the
    real copy is Word tracked changes between the document and its baseline; for .tex/.bib it is a
    latexdiff copy; a latexdiff ".tex" copy's compiled marked-up PDF is the matching
    "<name>.tracking-<token>.pdf" (the same auxiliary family); the matching ".logging-*" file is
    the documented fallback log used when the real tracked copy could not be produced reliably.
  * "<token>" NAMES THE BASELINE the copy was compared against, so the file name says what the
    difference is: "original" is the pre-conformed submission, and every other token is the id of
    the version the copy was taken against (the manifest records each row's own meaning). Do not
    infer anything from a token beyond "this document was compared with that version".
  * The orchestrator EXCLUDES every file whose name matches that pattern from the judged/pinned
    submission corpus, and it writes its own copies under <pipeline root>/redlines/ and
    <pipeline root>/tracking/, so these auxiliaries are never manuscript content in this pipeline.
  * Never score, flag, enumerate or "fix" such an auxiliary -- not its presence or absence, not its
    markup, not its contents -- and never treat it as a duplicate of its parent document, as a
    hygiene defect ("residual tracked changes"), or as a difference between versions. If you find
    one inside a directory you were told to read, it is pipeline bookkeeping: skip it. Do NOT run
    latexdiff (or any other difference tool) over these copies; the orchestrator has already
    tracked every difference itself."""

def derived_outputs_rule(profile=None) -> str:
    """The derived-build-outputs rule, with the venue's own PDF stance.

    The first two bullets are venue-independent; the third states what the
    configured venue does with a submitted PDF, from the profile's
    `submission` block (a profile may say it accepts PDFs, or that it does not
    state a format -- the rule then keeps its packaging conclusion either way).
    """
    prof = _as_profile(profile)
    pdf_note = (prof.data["submission"].get("pdf_note")
                or f"{prof.label} does not state which submission formats it accepts")
    return """DERIVED BUILD OUTPUTS — never the authoritative content:
  * ".aux", ".blg", ".bcf", ".log", ".out", ".synctex.gz", ".run.xml", ".fls", ".fdb_latexmk" and a
    compiled PDF of an editable source are BY-PRODUCTS of a build, not manuscript content. Judge
    the editable SOURCES; this pipeline explicitly allows a package to leave a derived output out
    rather than ship one that contradicts the current sources (recompiling can be a manual step
    for the author, recorded in the package's manual-steps list). A JUDGE VIEW is given the
    editable SOURCES: the orchestrator strips every derived output whose source is in the package
    -- the build by-products themselves, a compiled ".bbl" beside its ".bib", and a compiled PDF
    beside the ".docx"/".doc"/".tex"/".ltx" it was rendered from -- so compile or render the
    source yourself if you want a PDF. A derived file with no source in the package is kept (with
    no ".bib" shipped, a ".bbl" is the only copy of the reference list). Their absence is never a
    defect and their content is never evidence about how or when a package was made.
  * A build by-product that no longer matches its source (a .aux/.bbl still naming the pre-rename
    file, a .log from an earlier build) is a packaging note: report it in your reason, never score
    it as a correctness/preservation/completeness/consistency defect, and never let it decide a
    comparison.
  * A STALE SUBMITTED PDF IS NOT JUST A BY-PRODUCT. @@VENUE_PDF_NOTE@@. So
    when a TOP-LEVEL manuscript, cover-letter or supplementary PDF no longer matches the editable
    source shipped beside it (older text, pre-edit numbers, a pre-rename title), record it as a
    REPORTABLE packaging/consistency item (category 4; Major only when it is the only human-
    readable copy of a document whose text is materially wrong, otherwise Minor), name the file
    pair in your reason, and require the package to either recompile it or leave it out with a
    recompile instruction in its manual-steps list. Never let it decide a comparison on its own: the
    editable sources remain the judged content, and two versions with the same stale PDF are
    indistinguishable on this point.""".replace("@@VENUE_PDF_NOTE@@", pdf_note)

# The visual-inspection rule. The master prompt demands "VISUALLY inspect the entire document
# to check for visual defects" -- but a .docx is an OOXML package: an LLM asked to look at it
# reads text and cannot see fonts, spacing, margins, overlaps, clipping or pagination. The only
# way to perform that instruction is to RENDER the document (PDF) and look at the pages as
# images. This block is substituted into every prompt that produces or judges content, with
# @@VISUAL_TOOLS@@ describing which converters this machine actually has.
VISUAL_INSPECTION_RULE = """VISUAL INSPECTION — RENDER FIRST, THEN LOOK (a DOCX is NOT a picture):
  * Reading a .docx/.doc (or its converted text) is NOT a visual inspection: text carries no
    font size, spacing, margin, alignment, pagination, overlap, clipping or colour information.
    An instruction to "visually inspect the document" therefore means: CONVERT it to PDF (trying
    the converter below, falling back to the next one only if a call fails), RENDER every page to
    an image, and LOOK at those images with your image-viewing capability.
  * Converters available on this machine right now: @@VISUAL_TOOLS@@.
  * ALWAYS TRY THE `docx-converter` MCP TOOL FIRST, BEFORE ANY OTHER CONVERTER: if your session
    has MCP tools, call `convert_docx_to_pdf` with the ABSOLUTE WSL path of the .docx (for example
    `convert_docx_to_pdf(docxPath="/path/to/package/manuscript-c.docx")`). It renders through
    Microsoft Word via WSL/PowerShell interop, i.e. the highest-fidelity renderer available, and it
    writes `<name>.pdf` NEXT TO the .docx you pass it. Only if that tool is not available in your
    session (no MCP support), or the call reports a failure, fall back -- in this order, layout
    fidelity first -- to:
      1. `docx2pdf.sh FILE` (Word COM via PowerShell; writes the PDF next to FILE), then
      2. `docx render FILE --out pages/` (page-001.png, ... -- a render, not a PDF), then
      3. LibreOffice `soffice --headless --convert-to pdf --outdir DIR FILE`, then
      4. Word via Windows PowerShell COM directly when running under WSL, then
      5. `pandoc FILE -o FILE.pdf` (a CONTENT-level render: it drops Word's direct formatting, so
         record that caveat if you must use it).
    For .tex/.ltx compile the project (e.g. `latexmk -pdf`) and use the resulting PDF. Render pages
    with `pdftoppm -r 110 -png FILE.pdf PREFIX` (or Ghostscript).
  * RENDER INTO A WRITABLE WORK DIRECTORY, NEVER INTO A READ-ONLY INPUT: every converter above
    writes its output next to (or under) the file you hand it, and every read-only input you were
    given is hash-verified. Copy the .docx you want to inspect
    into the work directory of your OWN OUT (`OUT/work/`, e.g. `judge_review/work/`) first, and
    point the converter at THAT copy, so the read-only views stay byte-identical. A PDF or
    image that appears inside a read-only view is treated as tampering and fails the run.
  * THE VENUE TEMPLATE IS ALREADY RENDERED FOR YOU: when the venue ships an official template
    and this machine could render it, `visual_template/` holds the template's own PDF, its page
    images and a `manifest.json` naming the renderer used and each template document's page
    count. LOOK at `visual_template/<role>/<name>.pdf` side by side with your own render and
    record a **Template comparison** section in @@VISUAL_ARTIFACT@@: title page (title alignment,
    author list, affiliations/correspondence), running head/logo, footers and page numbers,
    heading depth and numbering, figure/table caption placement and legibility, and the
    front-page budget. Name each template document and its page count in that section -- the
    orchestrator checks that the comparison was actually made. If `visual_template/` is absent
    or its manifest records a render error, compare against the read-only `venue_template/` file
    itself (extract its structure) and say in the artifact that the visual template render was
    unavailable.
  * PAGE COVERAGE WITHOUT CONTEXT BLOW-UP: after rendering, build contact sheets that place
    EVERY page in the document on a small number of composite images (ImageMagick `montage` or
    a short Pillow script), and inspect those first.
    Open an individual full-resolution page only when the contact sheet suggests a defect, or
    when checking a title/caption/table page that needs detail. Record which contact sheets and
    individual pages you examined; never re-open a page you already inspected.
  * What to look for, page by page: fonts too small/large for their part of the manuscript,
    justified main text (must be left-aligned), overlapping or clipped text/figures, tables that
    overflow or break badly, figures/tables split across pages, orphaned headings, uneven
    spacing, caption placement, and anything that visually contradicts the style rules.
  * THE PAGE BUDGETS ARE PART OF THE INSPECTION, and they are recorded per document:
      - the FRONT PAGE must carry the title, the authors, the affiliations, the abstract AND the
        keywords together; a keywords line that starts page 2 (or an abstract that spills) is a
        defect -- shorten the front matter, never the science;
      - the COVER LETTER must render to at most TWO pages; a third page is a defect (trim the
        non-persuading boilerplate -- statement blocks, reviewer lists, restated affiliations --
        before touching a claim about the work);
      - write the rendered page count of EVERY top-level document you converted into the visual
        artifact (`document: N page(s)`), so "it fits" is a measurement, not an impression.
        The cached `docProps/app.xml` page count is NOT evidence: it is stale in exactly the files
        that were generated programmatically, so count the pages of the render you looked at.
  * Record the pass in @@VISUAL_ARTIFACT@@: the renderer and version used, which files/pages you
    actually looked at, what you found, and what you corrected. If no renderer works, or you
    cannot view images, say so EXPLICITLY in the same artifact, list every page as "not visually
    verified", and add the rendering step to the package's manual-steps list so the
    author can complete it. Never write "visually inspected" without having seen rendered pages."""

# The `docx` CLI (bun-docx) is OPTIONAL tooling that every agent may use. The
# requirement is explicit: every agent must be ABLE to use `docx diff` and the
# other `docx` commands -- while no agent is FORCED to use any of them. The
# block travels with every prompt that produces or judges content, and the
# availability line is filled in by docx_cli_block() so a machine without the
# CLI is described honestly instead of promised.
DOCX_CLI_RULE = """OPTIONAL TOOLING — the `docx` CLI (you MAY use it, you are NEVER required to):
  * Availability on this machine right now: @@DOCX_CLI@@. Where it exists, you may call it on
    the .docx files you are allowed to read: `docx read FILE --current` (tracked changes inline,
    with pN locators), `docx outline`, `docx wc`, `docx sections`, `docx styles`, `docx find`,
    `docx validate` (ECMA-376 schema check), `docx track-changes list`, and
    `docx render FILE --out pages/` for page images.
  * CHANGE VERIFICATION: `docx diff FILE --against SNAPSHOT` is a git-style unified diff of the
    READ view between a document and another version/snapshot of it (take the snapshot BEFORE you
    edit: `cp doc.docx doc.orig.docx`). It is the right tool for proving what actually changed at
    the paragraph/run level, and for writing an honest ledger or change log. It is AVAILABLE to
    every agent, including the judges, and no stage is forbidden from using it.
  * OPTIONAL, NOT MANDATORY, AND NEVER SCORED: using it earns nothing and not using it costs
    nothing -- no finding, coverage row, score, ranking or decision may depend on whether an agent
    used the CLI. Use it when it makes your own work more reliable, and ignore it otherwise.
  * It is an AID, not a substitute for the reading a stage requires: a `docx diff` is still a
    text-level view (it cannot see figures, layout or rendered pages), so where your stage says
    "read the packages IN FULL" or "do not rely on a text diff to find differences", that
    instruction still governs; `docx render` plus your own eyes remains the only visual pass.
  * For a .docx -> .pdf conversion, the `docx-converter` MCP tool comes FIRST (see the visual
    inspection rule in this prompt): call `convert_docx_to_pdf` before `docx2pdf.sh`, before
    `docx render` and before any other converter.
  * Never point it at a path outside your sandbox, and never let it write into a READ-ONLY input
    directory (its editing subcommands write to the file you name)."""

DOCX_CLI_AVAILABLE = ("available -- the `docx` command is on PATH (bun-docx: `docx --help` lists "
                      "read/edit/render/diff/validate)")
DOCX_CLI_MISSING = ("NOT available -- the `docx` command is not on PATH on this machine; use the "
                    "other tools your stage names")

# The `zot` CLI (pyzotero-cli; the terminal route of the $zotero-use skill) is how
# the agent sessions resolve the references a manuscript cites and -- within the
# `setup --zotero` policy -- change a citation or, under `apply`, ONE field of ONE
# existing library item. Reads are ordinary reference lookups; the library is a
# remote service owned by the operator, so the write side is an explicit
# setup-time choice plus the propose-then-verify protocol below. The block
# travels with every prompt that produces or judges content, and
# zotero_cli_block() fills in the availability, ledger and stage tokens.
ZOT_CLI_AVAILABLE = ("available -- the `zot` command (pyzotero-cli) is on PATH; `zot --help` "
                     "lists the command surface")
ZOT_CLI_MISSING = ("NOT available -- the `zot` command is not on PATH on this machine; do not "
                   "invent keys or metadata, and route every Zotero item to manual verification")
ZOT_REMOTE_HINT_READY = ("a zot-cli profile or credential looks configured (~/.config/zotcli/"
                         "config.ini or ZOTERO_* environment variables); confirm it with "
                         "`zot configure list-profiles` before relying on it")
ZOT_REMOTE_HINT_UNKNOWN = ("no remote credential was detected by the orchestrator, so API-backed "
                           "commands may fail; `zot --local ...` (GET-only) needs a running Zotero "
                           "with its local API enabled")

ZOTERO_CLI_RULE = """ZOTERO REFERENCE TOOLING — the `zot` CLI (pyzotero-cli; the $zotero-use skill's terminal route):
  * Availability on this machine right now: @@ZOT_CLI@@. Remote-library access: @@ZOT_REMOTE@@.
  * If a call fails because the session itself has no network/loopback access (a ConnectError or
    permission error, as opposed to "no such item"), do not retry in a loop: record the limitation,
    say which items could not be verified, and continue on the corpus + manual-verification route.
  * WHAT IT IS FOR: resolving every reference the manuscript cites. The read routes are always
    allowed: `zot --local --library-id 0 --library-type user items list|get|children`,
    `zot items list -q WORD` / `--filter-item-type journalArticle`, `zot items get KEY`,
    `zot items citation|bib KEY`, `zot fulltext get ATTACHMENT_KEY`, `zot collections list|items`,
    `zot tags list`, `zot search`, `zot util`. Cite PARENT bibliographic item keys, never
    attachment keys, and confirm from the parent's own metadata (title, creators, year, DOI) that
    it is the work the sentence needs.
  * NEVER INVENT: no key, DOI, author, year, title or quotation that no library item or full text
    backs. A citation that cannot be resolved (missing key, no matching item, library unreachable)
    is recorded as unresolved for manual verification; when a claim depends on it, the claim's fix
    is a manual item too.
@@ZOTERO_EDIT_GUIDANCE@@
@@ZOTERO_FIELD_CONTINUITY@@
  * THE ZOTERO LIBRARY ITSELF: @@ZOTERO_LIBRARY@@
  * LEDGER: @@ZOTERO_LEDGER@@ @@ZOTERO_STAGE@@"""

# The edit-oriented half of the Zotero block. Only a stage that may change a
# citation receives it; review/judge are read-only and rewrite edits form only,
# so the producer instructions ("before touching a citation field", "PROVE THE
# EDIT") must not be pasted into their prompts.
ZOTERO_EDIT_GUIDANCE_EDIT = """  * LIVE-FIELD DOCX SEMANTICS: before touching a citation field, read the $zotero-use skill's
    `references/word-docx-citations.md`, and validate the saved result with its bundled read-only
    validator (`scripts/validate_zotero_docx.py`). Use the URI namespace of the item's OWN library
    (never copy a document-wide namespace onto a new key); give every insertion location a unique
    citationID; put several sources cited at one location into ONE field with several
    citationItems; never synthesize `formattedCitation`/`plainCitation` (the visible text you
    insert is provisional -- a later Zotero Refresh replaces it); preserve every existing citation
    ID, item ID, URI and embedded itemData; add or remove a citation by operating on the WHOLE
    complex field (begin -> instrText -> separate -> result -> end) and keep the surrounding
    sentence grammatical; a field you cannot fully read or parse (a foreign namespace, missing
    itemData, unreadable XML) stays untouched and goes to the manual-verification list -- never
    re-type what you cannot read; never edit the bibliography field itself; never trigger Zotero
    Refresh yourself -- the author refreshes in Word.
  * SNAPSHOT FIRST, PROVE THE EDIT: keep an untouched copy of every .docx whose live fields you
    edit; after saving, validate the edited copy against that snapshot so every baseline citation
    survived and the intended insertions/deletions are exactly the ones you made. When the check
    fails, restore the snapshot and write a manual step instead of shipping a possibly corrupted
    field.
  * EVIDENCE CHAIN: a citation may be edited only when the cited item's own abstract/full text
    (`zot items get`, `zot fulltext get`, or its PDF) supports the sentence it is attached to. A
    sentence that contradicts its cited work may be reworded while the manuscript's own claim,
    numbers, limitations and conclusions stay unchanged; a fix that would change any of those is a
    scientific judgement call -- record it for the author, never make it."""

ZOTERO_EDIT_GUIDANCE_REWRITE = """  * LIVE-FIELD DOCX SEMANTICS: before reading a candidate's citation field, read the
    $zotero-use skill's `references/word-docx-citations.md`; the visible citation text is
    provisional (a later Zotero Refresh replaces it), so verify a citation against the item's own
    metadata/full text, never the rendered string. A field you cannot fully read or parse (a
    foreign namespace, missing itemData, unreadable XML) stays untouched and is surfaced in
    REWRITE_REPORT.md -- never re-type what you cannot read.
  * EVIDENCE CHAIN: a citation may be judged only when the cited item's own abstract/full text
    supports the sentence it is attached to. A contradiction is surfaced in REWRITE_REPORT.md as
    a problem; the rewrite never changes a citation, a field or the library."""

ZOTERO_EDIT_GUIDANCE_READONLY = """  * READING A LIVE FIELD: the visible citation text is provisional (a later Zotero Refresh
    replaces it), so verify a citation against the item's own metadata/full text, never the
    rendered string. A field you cannot fully read or parse (a foreign namespace, missing
    itemData, unreadable XML) is UNVERIFIED evidence for your reasoning and a
    manual-verification item -- never a guess and never an automatic defect.
  * EVIDENCE CHAIN: a citation can be checked only when the cited item's own abstract/full text
    supports the sentence; a contradiction is a finding for the authors to resolve. You never
    edit the manuscript, the field or the library."""

ZOTERO_STAGE_EDIT = """CITATION EDITS IN YOUR REVISED COPY are part of this stage's job (targeted and
    ledgered like every other edit): insert a citation to a resolved library item where the revised
    text needs support; delete a citation the revised sentence no longer makes, including one the
    review flagged as wrong; relink a citation that points at the wrong item when the intended work
    is unambiguous from the sentence and the evidence; reword a sentence so it no longer
    contradicts what its own citation actually reports. A library update is not a file write and
    does not violate the sandbox rule -- it is the one action this pipeline allows outside your
    filesystem sandbox, and only under the policy above. This is the pipeline's EXPLICIT override
    of the skill's default prohibition on programmatic live-field edits: it authorizes exactly the
    citation edits above (plus the library update only when this run's policy is `apply`), and
    every other skill protection -- foreign and unreadable fields, preserved IDs/URIs, no invented
    metadata -- stays in force."""
ZOTERO_STAGE_EDIT_DISABLED = """This run's policy does NOT allow citation-field edits: use the read routes to
    check every citation the corpus makes (does the key resolve; does the cited work support the
    sentence), and route each problem into your stage's normal report and manual list instead of
    editing a field."""
ZOTERO_STAGE_REVIEW = """YOUR STAGE IDENTIFIES, IT NEVER EDITS: check every citation the corpus makes (does
    the key resolve; does the cited work support the sentence; is support missing) and report each
    problem as a finding; an unreadable or incomplete live field goes to the manual-verification
    list. A citation whose visible text has no live field behind it -- or a field left malformed
    (unterminated, a stray field char, unparseable JSON, a duplicate citationID) -- is a finding of
    its own: file it as a field-continuity/preservation defect with the exact location. Never
    modify the manuscript and never write to the library."""
ZOTERO_STAGE_REWRITE = """YOUR STAGE REWRITES FORM, NOT CONTENT: citations, keys and bibliographic entries
    survive unchanged; you may use the read routes to understand what a citation points at, and
    every citation problem you find is surfaced in REWRITE_REPORT.md ("PROBLEMS SURFACED"), never
    fixed here. Rewriting form never means unlinking: every citation stays a LIVE field in your
    rewritten document, with the same citationID and the whole begin -> instrText -> separate ->
    result -> end sequence. If a paragraph you re-render loses its field runs (a text-only
    rebuild), re-insert the complete field from the base package's own field data before saving;
    never write to the library."""
ZOTERO_STAGE_JUDGE = """JUDGE SESSIONS ARE READ-ONLY: you may resolve a citation's metadata to check
    whether a candidate's claim matches its cited work, but you never edit a file and never write to
    the library. A citation you cannot check is unverified evidence in your reasoning (say so) --
    never an automatic defect. A candidate that dropped its baseline citations, left a field
    malformed, or carries citation text without a live field IS a preservation defect: score it
    under correctness/preservation and name the field/citation it affects."""

ZOTERO_FIELD_CONTINUITY_RULE = """  * FIELD CONTINUITY (code-enforced): your version carries the base version's live fields forward.
    You may ADD a field, EDIT a field (rewriting the WHOLE complex field around the same
    citationID) and DELETE a field together with its visible citation text; you may NOT delete
    every field at once, leave a field malformed (an unterminated begin, a missing separate or
    end, a stray fldChar/instrText, unparseable citation JSON, a missing or duplicate
    citationID), or replace a field by its visible text or any other plain text. After your save
    the pipeline audits your package against the base with the same field inventory and FAILS the
    attempt on any of those.
  * If you find citation or bibliography TEXT where a live field should be (a previous stage
    unlinked it, or you rebuilt the paragraph), RE-CREATE the field from the base version's own
    field data -- its citationID, itemData and item URIs, one field per citation location, with
    the same visible text -- and never leave the plain text in place of a field. Rebuilding a
    paragraph from its `w:t` text alone (python-docx, a re-serialization, any regex that keeps
    only text runs) destroys every fldChar/instrText run inside it: use a field-preserving edit, or
    re-insert the whole field afterwards.
  * PROVE IT before you finish, against the package you started from:
      python3 <zotero-use>/scripts/validate_zotero_docx.py <your.docx> --baseline <base.docx> \\
        --preserve-baseline-citations
    A check that fails is an attempt that fails; restore the field, never ship the unlinked copy."""
# The REWRITE stage edits FORM, not content: it must preserve fields, but it may
# not add/edit/delete a citation. Passing the producer rule there authorized an
# edit the same prompt forbids elsewhere.
ZOTERO_FIELD_CONTINUITY_RULE_REWRITE = """  * FIELD CONTINUITY (code-enforced): your version carries the base version's live fields forward.
    Your stage REWRITES FORM, not content: you may NOT add, edit or delete a citation field --
    every live field survives with the same citationID, itemData and item URIs, and its whole
    begin -> instrText -> separate -> result -> end sequence. A field left malformed (an
    unterminated begin, a missing separate or end, a stray fldChar/instrText, unparseable
    citation JSON, a missing or duplicate citationID), or replaced by its visible text, FAILS the
    attempt.
  * Rebuilding a paragraph from its `w:t` text alone (python-docx, a re-serialization, any regex
    that keeps only text runs) destroys every fldChar/instrText run inside it: use a
    field-preserving edit, or RE-CREATE the field from the base package's own field data (its
    citationID, itemData and item URIs, the same visible text) and never leave the plain text in
    place of a field.
  * PROVE IT before you finish, against the package you started from:
      python3 <zotero-use>/scripts/validate_zotero_docx.py <your.docx> --baseline <base.docx> \\
        --preserve-baseline-citations
    A check that fails is an attempt that fails; restore the field, never ship the unlinked copy."""
# Review and judge sessions are READ-ONLY: the producer rule told them to add,
# edit or delete fields and to prove it against a `base.docx` their sandbox does
# not carry. A missing/malformed field is a finding there, never a repair.
ZOTERO_FIELD_CONTINUITY_RULE_READONLY = """  * FIELD CONTINUITY (code-enforced): this session is READ-ONLY. You never add, edit, delete or
    re-create a field, and you never write or save a manuscript file. A live field that is
    missing, malformed (an unterminated begin, a missing separate or end, a stray
    fldChar/instrText, unparseable citation JSON, a missing or duplicate citationID), or replaced
    by its visible text is a FINDING -- a preservation defect with its exact location -- and you
    report it; you never repair it. The producer-side validation command belongs to the stages
    that write a document and does not apply here."""

ZOTERO_LIBRARY_READ = """the library is READ-ONLY for this run. Every `zot` call must be a read; never
    run create/update/delete/add-tags/add-doi or a collection-mutating subcommand. A library record
    you believe is wrong (a field, tag, collection or duplicate) becomes a proposal row in the
    ledger -- item key, the version you read, the field, the current value, the proposed value, the
    evidence, and the manuscript location that depends on it -- plus a matching manual step: the
    author applies it in Zotero."""
ZOTERO_LIBRARY_PROPOSE = ZOTERO_LIBRARY_READ
ZOTERO_LIBRARY_APPLY = """updates are ENABLED for this run under a two-pass protocol, and NOTHING else is
    enabled. This is the pipeline's explicit override of the skill's read-only-Zotero default, and
    it covers exactly the single guarded update described here:
      P1 PROPOSE: before any write, put the proposal row in the ledger: item key, the version you
         read, the field, the current value, the proposed value, the evidence, and the manuscript
         location that depends on it.
      P2 THINK TWICE, THEN VERIFY: re-fetch the item immediately before writing and compare key,
         item type, title, creators, year and DOI against the record the manuscript cites; confirm
         the proposed value against the source text; confirm the change is ONE field on ONE item,
         that nothing else moves, and that no ambiguous or duplicate match exists. If anything is
         unclear, conflicting, or would touch a claim, DO NOT write: downgrade to a proposal row
         plus a manual step.
      APPLY exactly one guarded update:
         `zot items update <KEY> --field <FIELD> "<VALUE>" --last-modified auto`
      (the version guard turns a concurrent edit into a clean failure instead of an overwrite).
      Then RE-READ the item, confirm the new value and the untouched neighbours, and append the
      outcome and the new version to the ledger.
    HARD LIMITS even in this mode: never create or delete library items, attachments, collections
    or tags; never bulk-edit; never touch an item this manuscript does not cite; never write from
    the review, rewrite or judge stages; never write when the change would alter a scientific
    claim -- that stays a manual decision for the author."""

ZOTERO_LIBRARY_CLAUSES = {"read": ZOTERO_LIBRARY_READ,
                          "edit": ZOTERO_LIBRARY_PROPOSE,
                          "apply": ZOTERO_LIBRARY_APPLY}
ZOTERO_STAGE_CLAUSES = {"edit": ZOTERO_STAGE_EDIT,
                        "edit_disabled": ZOTERO_STAGE_EDIT_DISABLED,
                        "review": ZOTERO_STAGE_REVIEW,
                        "rewrite": ZOTERO_STAGE_REWRITE,
                        "judge": ZOTERO_STAGE_JUDGE}
ZOTERO_LEDGER_RULE_PROD = """record every Zotero action in @@ZOTERO_LEDGER_REL@@ and in the stage's own
    report: item key, command, what was read or changed, the evidence, and the outcome. Create it
    only when there is something real to record (a lookup you relied on, an edit, a proposal); a
    stage with no Zotero interaction writes no file and says so in its report."""
ZOTERO_LEDGER_RULE_REVIEW = """record what you resolved, and any proposed library correction, in the
    review's own artifacts and manual-verification list; do not create a separate Zotero ledger."""
ZOTERO_LEDGER_RULE_REWRITE = """record what you checked in rewritten/REWRITE_REPORT.md; do not create a
    separate Zotero ledger."""
ZOTERO_LEDGER_RULE_JUDGE = """name the item keys you checked, and what you concluded, in your judge
    sheet's evidence; do not create a separate Zotero ledger."""

ZOTERO_CLI_RULE_OFF = """ZOTERO TOOLING — SWITCHED OFF for this run:
  * The pipeline was configured with `--zotero off`. Do NOT run the `zot` CLI, do not attempt a
    library read or write, and follow the skills' manual route for every live field or citation you
    cannot verify from the corpus itself: an unreadable or unverifiable field goes to the
    manual-verification list / MANUAL_STEPS.md, never into a guess and never into an edit. This
    overrides any earlier sentence in this prompt that mentions the `$zotero-use` skill or the
    `zot` CLI as available tooling."""
ZOTERO_CLI_RULE_OFF_BASE = ZOTERO_CLI_RULE_OFF
ZOTERO_CLI_RULE_OFF += ("\n(The field-continuity rules below stay in force with the CLI switched "
                        "off: the bundled validate_zotero_docx.py is an offline, read-only DOCX "
                        "checker -- it does not use the `zot` CLI or the network.)\n"
                        + ZOTERO_FIELD_CONTINUITY_RULE)
ZOTERO_CLI_RULE_OFF_NOTE = ("\n(The field-continuity rules below stay in force with the CLI "
                            "switched off: the bundled validate_zotero_docx.py is an offline, "
                            "read-only DOCX checker -- it does not use the `zot` CLI or the "
                            "network.)\n")


def m18_blocks(limit: int) -> dict:
    """The M18 sentences for a prompt, switched by the caption rule's state."""
    on = int(limit) > 0
    return {
        "@@M18_REVIEW_SWEEP@@": M18_REVIEW_SWEEP_ON if on else M18_REVIEW_SWEEP_REPORT,
        "@@M18_REVISE_RULE@@": M18_REVISE_RULE_ON if on else M18_REVISE_RULE_REPORT,
        "@@M18_JUDGE_SWEEP@@": M18_JUDGE_SWEEP_ON if on else M18_JUDGE_SWEEP_REPORT,
        "@@M18_INTEGRATE_CLAUSE@@": M18_INTEGRATE_CLAUSE_ON if on else M18_INTEGRATE_CLAUSE_REPORT,
        "@@M18_INTEGRATE_RULE@@": M18_INTEGRATE_RULE_ON if on else M18_INTEGRATE_RULE_REPORT,
    }

SOURCE_HIERARCHY = ("github code > data in raw_data/ > main figures > supplementary figures "
                    "> main tables > supplementary tables > main text > supplementary text")

# Artifact locations the prompts pin down and the postchecks verify.
REVIEW_DIR = "review"
REVISED_DIR = "revised"
REWRITTEN_DIR = "rewritten"          # the rewrite stage's output package
INTEGRATED_DIR = "integrated"        # the integration stage's output package
CODE_DIR = "code"
FINDINGS_REL = "review/findings.json"
FINDINGS_MD_REL = "review/findings.md"
ARTIFACTS_REL = "review/artifacts"
# --- the discovery round's own contract (D0-D5) --------------------------
# The discovery round is the pipeline's open-ended hunt for issue CLASSES the
# frozen checklist does not own; its findings (X-*) feed the revisers and its
# proposals (M37+...) feed the next checklist run. Until this contract existed
# only the PRESENCE of one of the three legacy files was noticed (and only as a
# warning), so a three-line "# none" was indistinguishable from a thorough
# round -- the 2026-10-09 external audits' single most-reported gap. The checks
# verify STRUCTURE (the enumerations and per-row dispositions the round's own
# guide, `references/discovery.md`, requires), never that its judgement is
# correct; they run under the same `--strict-artifacts` policy as the review's
# own decision tables (fail by default, warn under `--strict-artifacts off`)
# and are never repairable bookkeeping -- the phase either ran or it did not.
DISCOVERY_ROUND_FILES = ("known_index.md", "gap_table.md", "probes.md",
                         "probe_results.md", "findings_extra.json", "findings_extra.md",
                         "new_sweeps.md", "round2_summary.md")
DISCOVERY_MIN_GAP_ROWS = 25          # D1's floor ("target >= 25 rows total")
DISCOVERY_PROPOSAL_MIN = 37          # M18-M20 reserved by the pipeline, M21-M36 adopted
DISCOVERY_PROBE_ID_RE = re.compile(r"\bP2-\d{2,}\b")
DISCOVERY_X_ID_RE = re.compile(r"^X-\d+$")
DISCOVERY_SEVERITIES = ("fatal", "critical", "major", "minor")
# D5's zero-proposal escape: the file must SAY there were no proposals (and
# why), never just be a placeholder -- the honest-limits rule of the round.
DISCOVERY_NO_PROPOSAL_RE = re.compile(
    r"\b(?:no|none|nothing)\b[^.\n]{0,60}?\b(?:new\s+)?(?:sweep|proposal)s?\b"
    r"|\bnothing\s+to\s+propose\b", re.I)
_DISCOVERY_STATUS_TOKENS = ("pending", "executed", "unable", "no anomalies", "no anomaly")
# D1's UNCOVERED spellings: the plain word, "not covered" and the hyphenated
# "not-covered"/"not-yet-covered", plus the partial/no-check phrasings that all
# mean "no frozen check owns this row" -- only the covered branch of the gap
# classifier may read a row as COVERED.
_DISCOVERY_UNCOVERED_RE = re.compile(
    r"\bun[\s-]?covered\b|\bnot[\s-]+(?:yet[\s-]+)?covered\b|\bpartially[\s-]+covered\b"
    r"|\bcovered\s+by\s+nothing\b|\bno\s+check\b", re.I)
DISCOVERY_RELS = ("review/round2/findings_extra.json", "review/round2/findings_extra.md",
                  "review/round2/new_sweeps.md")
# --- the discovery list as the INTEGRATION stage receives it ----------------
# The discovery round's X-* findings are the round's only record of defect
# classes the frozen checklist does not own. The revisers merge them into their
# ledger, but the integration stage used to be told nothing about them: an X fix
# could be dropped by an integrator as an "unnamable" difference, so the round's
# revision work could vanish from the integrated package. The integrator is NOT
# a blind stage, so it gets a SEED: the round's own frozen list is copied
# byte-for-byte (review/round2/findings_extra.{json,md}, the same list the
# revise sessions merged) into a read-only `frozen_discovery/` directory, and
# every id must be reconciled in its ledger. The JUDGE is deliberately NOT
# seeded -- a judge must be completely blind to where a package came from, so it
# RE-DERIVES its own discovery findings instead (see `judge_discovery_block`).
# The auditor's drops are honoured: an X id the round's auditor dropped is not a
# defect any version was asked to fix, so the integrator must not score it.
DISCOVERY_SEED_DIR = "frozen_discovery"
DISCOVERY_SEED_FILES = ("findings_extra.json", "findings_extra.md")
DIFF_LEDGER_REL = "revised/DIFF_LEDGER.md"
REWRITE_REPORT_REL = "rewritten/REWRITE_REPORT.md"
# The integration stage's ledger lives in its own output package.
INTEGRATION_LEDGER_REL = "integrated/DIFF_LEDGER.md"
# The skills put manual steps at revised/MANUAL_STEPS.md; each stage's own
# package path is checked first, and the bare root path is tolerated for
# packages that place it one level up.
MANUAL_STEPS_RELS = ("revised/MANUAL_STEPS.md", "rewritten/MANUAL_STEPS.md",
                     "integrated/MANUAL_STEPS.md", "MANUAL_STEPS.md")

# Judgment call: the anti-regression gate's tolerance. 0 (used here) blocks a
# version whose median vs_original is negative, i.e. "least bad" cannot win.
# Defensible alternatives that we deliberately did NOT pick: a stricter > 0
# (requires a demonstrable improvement, not merely non-regression) and a looser
# >= -0.5 (tolerates a panel that is slightly net-negative because one judge saw
# a real trade-off). Either can be switched in by editing this constant.
VS_ORIGINAL_TOLERANCE = 0.0
# C21a/C23: the gate's DECISION RULE is explicit and switchable. `median` is the
# pre-registered default (a candidate whose vs_original median is negative is
# ineligible). `sign` fails only when the exact one-sided sign test over the
# pair's directed scores is significant at VS_ORIGINAL_ALPHA -- the honest
# statement of what a 2*judges (6-score) pair can support, at the price of
# passing more real regressions. Both rules are REPORTED with their sign counts
# and p-value, so a 0.6-median pass that was a coin flip is visible.
VS_ORIGINAL_RULE = "median"
VS_ORIGINAL_ALPHA = 0.05


def _binomial_tail_p(k: int, n: int) -> float:
    """P(X >= k), X ~ Binomial(n, 1/2): the exact one-sided sign-test p-value."""
    if n <= 0:
        return 1.0
    total, c = 0, 1
    for i in range(0, n + 1):
        if i >= k:
            total += c
        c = c * (n - i) // (i + 1)
    return total / (2 ** n)


def vs_original_rule_of(ctx) -> str:
    raw = str((getattr(ctx, "cfg", None) or {}).get("vs_original_rule")
              or VS_ORIGINAL_RULE).strip().lower()
    return raw if raw in ("median", "sign") else VS_ORIGINAL_RULE


def anti_regression_verdict(ctx, vid: str, vs, vs_vals: list):
    """Eligibility against the pristine original under the configured rule.

    None for the original's own row (there is nothing to regress against); False
    for a fresh arm with no original-facing evidence; otherwise the configured
    rule -- `median` (the pre-registered default) or `sign` (fail only on a
    significant one-sided sign test over the pair's directed scores).
    """
    if vid == ORIGINAL_ID:
        return None
    if vs is None:
        return False
    if vs_original_rule_of(ctx) == "sign":
        non_tied = sum(1 for x in vs_vals if x != 0)
        losses = sum(1 for x in vs_vals if x < 0)
        return not (_binomial_tail_p(losses, non_tied) < VS_ORIGINAL_ALPHA)
    return vs >= VS_ORIGINAL_TOLERANCE

# Sentinel for a REPORTED-but-absent value (the marker summary omitted it and no
# MANUAL_STEPS.md could be counted): a missing number is +inf, so absence never
# looks better than a reported value. None of these self-reported numbers is a
# ranking key any more (the panel-derived issue census is -- see
# champion_sort_key); they are recorded and cross-checked, never ranked on --
# `manual_steps` was never ranked on at all.
MISSING_TIEBREAK = float("inf")

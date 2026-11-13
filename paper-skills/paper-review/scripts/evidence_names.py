"""Filename rules for deciding whether a converted source is manuscript prose."""


import re


EVIDENCE_DIRNAMES = ("raw_data", "human_review_feedback", "llm_review_feedback")


DISABLED_EVIDENCE_SUFFIXES = ("disabled", "off")


_ARTICLE_TYPE_MANUSCRIPT_RE = re.compile(
    r"^(?:(?:the[.\s_-]+)?editorial(?:[.\s_-]+board)?|"
    r"letters?[.\s_-]+(?:to|for)[.\s_-]+(?:the[.\s_-]+)?editor)"
    r"(?:[.\s_-]+(?:v|rev|version|revision|draft)?[.\s_-]*\d{1,3})?$", re.I)


_SEMANTIC_SUFFIX_RE = re.compile(
    r"\.(?:reply|response|rebuttal|review|notes?|comments?)(?:\.[A-Za-z0-9]+)+$", re.I)


_COVER_WORD_RE = re.compile(
    r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"
    r"(?:[Cc]over|COVER|(?i:coverletter|plainletter))(?![a-z])")


_SCIENCE_ROLE_COMPOUND_RE = re.compile(
    r"(?<![a-z])(?:dose|immune|stress|apoptotic|inflammatory|transcriptional|"
    r"pharmacodynamic)[-_ ]?response"
    r"|(?<![a-z])response[-_ ]?(?:time|rate|curve|latency|element|surface|variable)"
    r"|(?<![a-z])feedback[-_ ]?(?:loop|control|gain|signal)"
    r"|(?<![a-z])(?:bio|neuro|video|audio)[-_ ]?feedback", re.I)


def _is_evidence_part(part: str) -> bool:
    low = str(part or "").strip().lower()
    if low in EVIDENCE_DIRNAMES:
        return True
    return any(low.startswith(area + ".")
               and low[len(area) + 1:] in DISABLED_EVIDENCE_SUFFIXES
               for area in EVIDENCE_DIRNAMES)


def is_evidence(path, feedback, reply, *, science_compounds=_SCIENCE_ROLE_COMPOUND_RE):
    """Apply shared path rules, then the scanner's feedback and reply vocabulary."""
    parts = str(path).replace("\\", "/").split("/")
    if any(_is_evidence_part(part) for part in parts[:-1]):
        return True
    # The converter FLATTENS an evidence file's directory into its name
    # ("raw_data/table1.txt" -> "raw_data__table1.txt"); the two sibling
    # extractors (extract_citations.py, extract_acronyms.py) already gate on
    # that spelling, and without it raw-data text was counted against the
    # submission's abstract/main-text limits.
    if any(parts[-1].startswith(d + "__") for d in EVIDENCE_DIRNAMES):
        return True
    # A cover letter IS a submission document -- and this test must come FIRST,
    # exactly as in extract_citations.py: with the reply/feedback test below it,
    # `cover_letter_response.md` was dropped as reviewers' feedback and the
    # letter never reached the M19 length sweep.
    if _COVER_WORD_RE.search(parts[-1]):
        return False
    base = parts[-1]
    if _SEMANTIC_SUFFIX_RE.search(base):
        return True             # a reply/review/notes DOCUMENT, never author prose
    stem = base
    while True:
        _stripped = re.sub(
            r"\.(?:txt|docx?|md|tex|pdf|rtf|bib|csv|tsv|bak|final|tar|gz|zip)$",
            "", stem, flags=re.I)
        if _stripped == stem:
            break
        stem = _stripped
    if _ARTICLE_TYPE_MANUSCRIPT_RE.match(stem):
        return False            # the authors' article-type manuscript, not a letter
    cleaned = science_compounds.sub(" ", base)
    return bool(feedback.search(cleaned) or reply.search(cleaned))

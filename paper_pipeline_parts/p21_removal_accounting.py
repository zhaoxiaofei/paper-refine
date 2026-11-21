# -*- coding: utf-8 -*-
# Part 21/23 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
# Removal accounting and the soft-deletion unit filter.
#
# Split out of p06/p07 to keep every part under the 10,000-line limit. These
# helpers answer one question for a delivered package: which sentences that the
# base carried, or that a review finding quoted, are GONE? The content-edit
# policy uses that to accept the documented removable units; the revise
# postcheck uses it to refuse a ledger that reports a removed finding as
# `fixed`.
#
# No module docstring: every part is exec'd into the loader's own globals, and a
# string literal at a part's top would overwrite `paper_pipeline.__doc__` (the
# round-plan documentation) with the part's.
from __future__ import annotations


def ledger_final_status_map(ledger, wanted=()) -> dict:
    """{finding id: final edit status} for a revision ledger.

    The final outcome is a SECOND column, distinct from the re-verification
    `verdict`. The removal accounting needs the outcome (did the package claim
    a repair?) rather than the verdict (was the finding confirmed?), so it
    reads this map instead of parsing `_ledger_verdict_map`'s combined form.
    The first non-empty status wins; a genuinely contradictory ledger is
    already reported by `revision_ledger_problems`.
    """
    want = {str(w).strip() for w in (wanted or ()) if str(w).strip()}
    out = {}

    def visit(node, depth: int, keyed_id: str = ""):
        if depth > LEDGER_SCAN_DEPTH:
            return
        if isinstance(node, dict):
            rid = ledger_row_id(node) or keyed_id
            final = _ledger_final_status(node)
            if final and (not want or rid in want):
                out.setdefault(rid, final)
            for key, value in node.items():
                if isinstance(value, (dict, list, tuple)):
                    visit(value, depth + 1,
                          key.strip() if isinstance(key, str) else "")
        elif isinstance(node, (list, tuple)):
            for item in node:
                if isinstance(item, (dict, list, tuple)):
                    visit(item, depth + 1)

    visit(ledger, 0)
    return out


# Fully present means EVERY content token (F003): 0.95 let one value or
# negation token vanish from a long sentence and still count as a merge.
_CONTENT_UNIT_CONTAINED = 1.0
# Polarity is part of the statement (F002): `not`/`never` is a stopword for the
# similarity terms, so "was effective" was 100% contained by "was not
# effective". A merge must preserve the polarity of the unit it covers.
_CONTENT_NEGATION_RE = re.compile(
    r"(?i)\b(?:not|no|never|none|neither|nor|cannot|can't|won't|isn't|aren't|"
    r"wasn't|weren't|doesn't|don't|didn't|failed|fails|failing|without|unable|"
    r"lacked|lacks|lacking|refused|refuses|prevented|prevents|absent)\b")


def _content_unit_contained(unit: dict, candidates: list,
                            floor: float = _CONTENT_UNIT_CONTAINED) -> bool:
    """Is every content token of `unit` inside ONE candidate sentence?

    The one-to-one matcher consumes a candidate for a single base unit, so a
    merge of two base sentences into one delivered sentence leaves the second
    base unit unmatched even though its content is fully present. This test
    rescues exactly that case (containment, not similarity) without rescuing a
    deleted sentence: a removed claim's content tokens are not all in one
    delivered sentence.

    Containment must not rescue a REVERSED claim: the polarity of the unit and
    the candidate must match (F002), and a two-token unit is a real short claim
    ("Samples froze."), not a fragment to skip (F050). Full containment is the
    documented contract (F003).
    """
    tokens = _content_tokens(unit)
    if len(tokens) < 2:
        return False
    polarity = bool(_CONTENT_NEGATION_RE.search(str(unit.get("text") or "")))
    for cand in candidates or ():
        if len(tokens & _content_tokens(cand)) / len(tokens) < floor:
            continue
        if bool(_CONTENT_NEGATION_RE.search(str(cand.get("text") or ""))) != polarity:
            continue
        return True
    return False


def soft_deletion_missing_units(missing, cand_units, exempt_removed=(),
                                allow_marker_delete: bool = True) -> list:
    """Drop the documented removable units from a base->package `missing` list.

    The one-to-one matcher consumes a candidate for a single base unit, so a
    duplicate's second copy and a merged sentence are still listed as
    `missing`; both are accepted by the soft-deletion policy. Everything else
    in the list is a claim removal and fails the attempt.

    The pipeline-removal exemptions are consumed one-to-one and are scoped to
    the document they were recorded for (F004): the raw list used to be
    re-applied by sentence text alone, so a removal in one document whitelisted
    the same sentence deleted from another, and the second identical copy in a
    document was re-exempted after the caller had already consumed it.
    A hand-off marker is exempt only where the author-to-complete policy
    requires its removal (F070).
    """
    _cand_norms = {u["norm"] for u in cand_units}
    exempt_document, exempt_text = _removal_exemption_counters(exempt_removed)
    kept = []
    for u in missing:
        if _removal_is_artifact(u["text"],
                                allow_marker_delete=allow_marker_delete):
            continue
        if u["norm"] in _cand_norms or _content_unit_contained(u, cand_units):
            continue
        doc_key = (u.get("document"), u["norm"])
        if exempt_document.get(doc_key, 0) > 0:
            exempt_document[doc_key] -= 1
            continue
        if exempt_text.get(u["norm"], 0) > 0:
            exempt_text[u["norm"]] -= 1
            continue
        kept.append(u)
    return kept


def deletion_row_fact_loss_problems(sandbox: Path, rows, full_by_ref=None) -> list:
    """Per-row backstop: an `OK — no fact is lost` row that DID lose a value.

    The revision audit's dispositions are the pipeline's own record of what a
    deletion cost. A row disposed `OK — <why no fact is lost>` while the value
    it carried appears nowhere in `revised/`'s own prose is a false record,
    whatever the revise stage was told. The compliant dispositions already
    exist: `fact removed — RP-xxx` (with a plan row) and `manual-required`.

    `full_by_ref` maps the seeded occurrence id to the FULL paragraph text: the
    table cell is display-truncated to a fixed budget, so checking only the
    visible cell would miss a value beyond the cut (a false negative).
    """
    package = Path(sandbox) / REVISED_DIR
    if not package.is_dir():
        return []
    surviving = _fact_survival_keys(_content_unit_sentences(package))
    problems = []
    for row in rows or ():
        # The audit's disposition column is any of the accepted aliases
        # (`disposition`/`resolution`/`verdict`); reading only the literal
        # `disposition` key skipped every row of a table that used an alias
        # (F045).
        disposition = ""
        for key in DISPOSITION_COLUMNS:
            value = str(row.get(key) or "").strip()
            if value:
                disposition = value
                break
        if not re.match(r"(?i)^OK\s*[\u2014\u2013:-]", disposition):
            continue
        paragraph = str((full_by_ref or {}).get(str(row.get("#") or "").strip())
                        or row.get("paragraph") or "")
        lost = _fact_survival_lost_tokens(paragraph, surviving)
        if not lost:
            continue
        problems.append(
            f"row {str(row.get('#') or '?').strip()} is disposed "
            f"{disposition[:60]!r} but the value(s) {', '.join(sorted(set(lost)))} it carried "
            f"appear nowhere in {REVISED_DIR}/'s own prose: `OK — no fact is lost` is not "
            f"available for a deleted paragraph whose value has no surviving manuscript "
            f"carrier (a hand-off-only value is `manual-required`, not `OK`). Dispose it as "
            f"`fact removed — RP-xxx` (and add the row to REPAIR_PLAN.json), or as "
            f"`manual-required — <what the author must restore>`.")
    return problems


# A finding's evidence is a QUOTE of the base the reviewer read. The revision
# may delete that text -- insertions and deletions are the reviser's call -- but
# a deletion is a claim the package no longer carries, so it must be ACCOUNTED
# for: the finding is `manual-required`, never `fixed`, and the removed claim
# goes to the author's manual list. These patterns are the classes whose repair
# IS a removal (a workflow artifact that was never manuscript content); a
# deleted claim is not one of them.
_EVIDENCE_ARTIFACT_RE = re.compile(
    # A placeholder TOKEN is an artifact only when the unit IS a placeholder:
    # the token starts the unit (optionally bracketed/emphasised) and is
    # followed by end-of-unit or punctuation. Matching it ANYWHERE exempted a
    # real claim ("The XXX domain is required for binding.") from removal
    # accounting (F031). `[CITE]` is unambiguous and stays unanchored.
    r"(?im)^\s*(?:#{1,6}\s*)?[*_]*[\[(]?\s*"
    r"(?:TODO|TBD|FIXME|XXX|PLACEHOLDER)\s*[\])]?[*_]*\s*(?:[.:;,!?\u2014\u2013-]|$)"
    r"|\[CITE\]|\blorem\s+ipsum\b"
    r"|^\s*(?:#{1,6}\s*)?(?:instruction|prompt|system|user)\s*:"
    # The instruction patterns are ANCHORED at the sentence start: an
    # unanchored `\bimprove\s+the\s+tone\b`-style match exempted a real
    # methods sentence that happened to contain the words, hiding a removed
    # claim from the accounting gate. `INSERT` is not a documented placeholder
    # either (`insert` is an ordinary methods verb), so it is gone.
    r"|^\s*(?:output|return)\s+only\s+the\s+(?:revised|edited|rewritten)\b"
    r"|^\s*(?:please\s+)?(?:improve|revise|rewrite|expand|polish)\s+the\s+"
    r"(?:academic\s+)?(?:tone|text|paragraph)\b")

# How strongly a finding's evidence must match a BASE sentence before the gate
# treats it as a verbatim quote worth judging. The real deletions quote the base
# exactly (1.0); a partial quote, a composite "Results: ... vs 3.1: ..." row or
# a paraphrase scores far lower and is skipped, because a fuzzy base match
# cannot distinguish a corrected sentence from a deleted one.
_FINDING_QUOTE_MATCH = 0.90


def _finding_evidence_units(finding_id: str, evidence: str) -> list:
    """The evidence quote as sentence units, keyed to a pseudo-document.

    Duplicate sentences inside one quote collapse to ONE unit: a finding about a
    duplicated sentence quotes the same sentence twice, and one surviving copy
    is the correct repair. The pseudo-document is unique per finding so the
    matcher's positional pass (same file+line slot) can never pair two evidence
    sentences with each other; presence is decided by the exact/fuzzy passes.
    """
    units, seen = [], set()
    for index, sentence in enumerate(_content_sentence_parts(evidence)):
        text = _deleted_para_norm(sentence)
        if len(text) < _CONTENT_UNIT_MIN_CHARS:
            continue
        tokens = re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE)
        if len(tokens) < _CONTENT_UNIT_MIN_WORDS:
            continue
        norm = text.lower().strip()
        if norm in seen:
            continue
        seen.add(norm)
        units.append({"document": f"__finding__{finding_id}", "line": index,
                      "text": text, "norm": norm, "sentence_index": index,
                      "tokens": set(tokens)})
    return units


def _removal_is_artifact(text: str, exempt_removed=(),
                         allow_marker_delete: bool = True) -> bool:
    """Is this removed sentence one of the documented removable units?

    `allow_marker_delete` is false under `author_to_complete: document`, where a
    base hand-off marker must survive; the soft-deletion helper passes the
    stage's mode so a required marker is not exempted as an artifact (F070).
    """
    if (allow_marker_delete and _is_handoff_marker(text)) \
            or _EVIDENCE_ARTIFACT_RE.search(text):
        return True
    norm = _deleted_para_norm(text).lower()
    for item in exempt_removed or ():
        sentence = item[1] if isinstance(item, (tuple, list)) and len(item) >= 2 else item
        if norm and norm == _deleted_para_norm(sentence).lower():
            return True
    return False


def _removal_exemption_counters(exempt_removed) -> tuple:
    """(document-keyed Counter, text-only Counter) of pipeline removals.

    The document is part of the key: a removal recorded for `supplement.md`
    may not excuse the same sentence deleted from `main.md` (F004). A bare
    sentence keeps the historical text-only scope for callers that do not
    record a document. Counters make every exemption cover ONE occurrence.
    """
    by_document = Counter()
    by_text = Counter()
    for item in exempt_removed or ():
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            norm = _deleted_para_norm(item[1]).lower()
            if norm:
                by_document[(str(item[0]), norm)] += 1
        else:
            norm = _deleted_para_norm(item).lower()
            if norm:
                by_text[norm] += 1
    return by_document, by_text


def finding_removal_problems(base: Path, package: Path, findings,
                             final_status=None, exempt_removed=(),
                             skipped: list = None) -> list:
    """[{id, final, lost}] for findings whose quoted sentence is gone.

    Insertions and deletions are ON by default and are the reviser's call, so
    removing a sentence is a PERMITTED revision choice, not a defect: this
    function never asks for the sentence back and never treats the removal
    itself as a failure. What it makes visible is the ACCOUNTING. A finding
    resolved by removing its sentence is a claim the package no longer carries,
    so its ledger row may not report `fixed` (a repair the package does not
    contain) and the removed claim belongs in the author's manual list. The
    caller decides the severity: `fixed` / `fixed-with-caveat` (or no final
    status at all) over a removed sentence is a misreport; any other disposed
    row is an accepted removal.

    The deletion audit cannot catch this class on its own. Its fact gate
    (`deletion_row_fact_loss_problems`) tracks NUMBERS and IDENTIFIERS that
    survived; a sentence whose "fact" is a wrong word (a premise common
    knowledge rejects) leaves no true value in the base to lose,
    so the removal reads as `OK -- no fact is lost`. This check anchors on the
    FINDING instead: the sentence the reviewer quoted, not the value it
    happened to contain.

    Only sentences the reviewer quoted VERBATIM from the base are judged (a
    summary, a paraphrase or a composite "Results: ... vs 3.1: ..." quote is
    skipped -- a fuzzy base match cannot tell a corrected sentence from a
    deleted one). A removed sentence is excluded for the documented removable
    units (a leaked prompt/instruction, a placeholder, a duplicate whose other
    copy survives -- the matcher credits that copy -- or a sentence the
    orchestrator itself removed). `final_status` maps a finding id to the
    ledger's final status; `skipped` is forwarded to the reader.
    """
    base, package = Path(base), Path(package)
    if not findings or not package.is_dir() or not base.is_dir():
        return []
    rev_units = _content_unit_sentences(package, skipped=skipped)
    if not rev_units:
        return []
    base_units = _content_unit_sentences(base, skipped=skipped)
    if not base_units:
        return []
    statuses = {str(k).strip(): str(v or "").strip().lower()
                for k, v in (final_status or {}).items()}
    removals = []
    for finding in findings or ():
        if not isinstance(finding, dict):
            continue
        fid = str(finding.get("id") or "").strip()
        evidence = str(finding.get("evidence") or "").strip()
        # A short verbatim quote ("The sky is blue.") is a real unit: the
        # sentence builder already applies the documented 8-character /
        # 2-word floor, so the old extra 20-character gate silently exempted
        # short claims from removal accounting (F049).
        if not fid:
            continue
        units = _finding_evidence_units(fid, evidence)
        if not units:
            continue
        # Judge only sentences the reviewer quoted VERBATIM from the base: a
        # summary, a paraphrase, a composite quote of two locations or a
        # partial quote of a longer sentence is not a locatable unit, and a
        # fuzzy base match cannot tell a corrected sentence from a deleted one.
        # The high floor is what keeps this accounting from flagging a
        # legitimate in-place correction whose new wording shares few tokens
        # with the old (a corrected acronym expansion is the common case).
        quoted = []
        quoted_base = set()
        for b in units:
            for cand in base_units:
                # Every base copy of the quote is judged, not only the first
                # one the matcher happens to pair: with the sentence in both
                # main.md and supplement.md, exempting the supplement copy must
                # not hide the main.md removal (F004/R02).
                if id(cand) in quoted_base:
                    continue
                if _content_unit_similarity(b, cand) < _FINDING_QUOTE_MATCH:
                    continue
                quoted_base.add(id(cand))
                unit = dict(b)
                unit["document"] = cand.get("document")
                unit["line"] = cand.get("line")
                unit["sentence_index"] = cand.get(
                    "sentence_index", b.get("sentence_index"))
                quoted.append(unit)
        if not quoted:
            continue
        gone, _added, _pairs = _match_content_unit_pairs(quoted, rev_units)
        # The matcher consumes a candidate one-to-one, so a merge of two base
        # sentences into one delivered sentence leaves the second quoted unit
        # unmatched even though its content survives. Rescue that case here as
        # the soft-deletion gate does: an accounting error must mean the claim
        # is gone, not that its sentence was merged.
        exempt_document, exempt_text = _removal_exemption_counters(exempt_removed)
        lost = []
        for u in gone:
            if _removal_is_artifact(u["text"]):
                continue
            if _content_unit_contained(u, rev_units):
                continue
            norm = _deleted_para_norm(u["text"]).lower()
            doc_key = (str(u.get("document") or ""), norm)
            if exempt_document.get(doc_key, 0) > 0:
                exempt_document[doc_key] -= 1
                continue
            if exempt_text.get(norm, 0) > 0:
                exempt_text[norm] -= 1
                continue
            # One row per finding: two documents losing the same sentence is
            # one removed claim for the warning, not a duplicated sample.
            if u["text"] not in lost:
                lost.append(u["text"])
        if not lost:
            continue
        removals.append({"id": fid, "final": statuses.get(fid, ""),
                         "lost": lost})
    return removals


def finding_removal_messages(removals, package_rel: str = "revised/") -> tuple:
    """(errors, warnings) from `finding_removal_problems` rows.

    `fixed` (or no final status) over a removed sentence is an ERROR: the ledger
    reports a repair the package does not contain. Any other disposition is an
    accepted removal; the warning carries the removed claim to the author. The
    deletion itself is never the error -- insertions and deletions are on.
    """
    errs, warns = [], []
    for row in removals or ():
        fid = row.get("id")
        final = str(row.get("final") or "")
        lost = list(row.get("lost") or ())
        sample = "; ".join(repr(text[:120]) for text in lost[:2])
        if len(lost) > 2:
            sample += f" and {len(lost) - 2} more"
        detail = (f"finding {fid}: the sentence it quotes is absent from "
                  f"{package_rel} ({sample})")
        if final in ("", "fixed", "fixed-with-caveat"):
            errs.append(
                detail + ". Removing the sentence may be allowed by the content-edit "
                "policy, but the ledger may not record the removal as `fixed`: the package "
                "does not contain the repair. Record the finding `manual-required` with the "
                "removed claim and its location so the author decides; keep `fixed` only for "
                "a sentence that is still present (corrected in place).")
        else:
            warns.append(
                detail + f" and the ledger records it `{final}`; the removed claim is not in "
                "the package, so it must also be in the author's manual list.")
    return errs, warns


def revision_ledger_final_status(package: Path, wanted=()) -> dict:
    """{finding id: final edit status} of a package's revision ledger.

    The final outcome is a SECOND column (`final_status` / `status` /
    `disposition`), distinct from the re-verification `verdict`. The removal
    accounting needs the outcome, not the verdict.
    """
    ledger = read_json(Path(package) / "revision_report.json", revive=False, lenient=True)
    if not isinstance(ledger, (list, dict)):
        return {}
    return ledger_final_status_map(ledger, wanted)


def _reason_denies_movement(reason: str) -> bool:
    """Does a clause of `reason` deny the movement/merge it is used to claim?

    F043: `OK — not moved to Methods` / `failed to merge into Results` must be
    refused because the reason says the content did NOT survive. R03: the
    negation has to belong to the movement predicate's own clause. The old
    24-character window also refused a different negated predicate
    (`was not lost and was moved to Methods`) and the additive
    `not only moved but also merged`, both of which are real reasons.
    """
    verbs = (r"(?:moved?|moving|merged?|merging|folded?|folding|relocated?|relocating|"
             r"integrated?|integrating|reported|reporting|restated?|restating|"
             r"included?|including|placed?|placing|put|putting|found|finding|"
             r"survives?|surviving)")
    negations = (r"(?:not|never|no|failed|unable|didn't|did\s+not|could\s+not|"
                 r"cannot|can't|without)")
    # A denial can be POST-POSED after the movement word: "moving to Methods
    # was not possible" / "merging into Results could not be done". The old
    # clause test required the negation to precede the verb, so these fell
    # through to the 4-word floor and closed a deleted paragraph as OK (F016).
    postposed = re.compile(
        r"(?i)\b(?:was|were|is|are|could|can|would|will|has|have|had)\s+"
        r"(?:not|never|cannot)\b[^.;\n]{0,30}\b"
        r"(?:possible|done|performed|carried\s+out|made|allowed|feasible|successful)\b")
    for clause in re.split(
            r"(?i)\b(?:and|but|because|while|although|whereas)\b|[.;,]", reason):
        # "not only moved but also merged" is additive, not a denial.
        if re.search(r"(?i)\bnot\s+(?:only|just)\b", clause):
            continue
        if postposed.search(clause):
            return True
        neg = re.search(r"(?i)\b" + negations + r"\b", clause)
        verb = re.search(r"(?i)\b" + verbs + r"\b", clause)
        if neg and verb and neg.start() < verb.start():
            return True
    return False


def _deletion_disposition_ok(value, allow_nothing_removed: bool = True) -> bool:
    """Does a DELETED_PARAGRAPHS disposition use the seeded vocabulary?

    The seed's instructions name exactly three shapes: `OK — <why no fact is
    lost>`, `manual-required`, and `fact removed — RP-xxx`. The shared
    `disposition_artifact_problems` only rejects empty/boilerplate cells, so a
    single `x` used to pass the deletion-fact gate without disposing anything.

    `allow_nothing_removed` is true ONLY for the seed's own empty-table row
    (`expected_rows == 0`, id `-`). On a real deleted row the phrase says the
    opposite of what happened, so it is not a reason and cannot dispose it
    (F191).
    """
    text = str(value or "").strip()
    if not text:
        return False
    ok = re.match(r"(?i)^OK\s*[\u2014\u2013:-]\s*(.+)$", text)
    if ok:
        # The seeded instruction asks for `OK — <why no fact is lost>`, not
        # merely "some character after the dash": one non-space character
        # (`OK — x`) used to dispose a deleted fact-bearing paragraph. Require
        # an actual reason (>= 4 words), the smallest bar that still admits the
        # documented short closures (`OK — duplicate; no fact lost`).
        reason = ok.group(1).strip()
        # The seed's own empty-table row is `OK — nothing removed`: there is no
        # deleted paragraph to explain, so it is not the one-character closure
        # this check exists to reject -- but only THAT row may use it.
        if reason.lower() in ("nothing removed", "no rows removed"):
            return bool(allow_nothing_removed)
        # A NEGATED movement/merge is not a reason: `OK — not moved to Methods`
        # says the content did NOT survive there, and the old moved-verb branch
        # accepted it as the opposite (F043). Reject it outright instead of
        # letting it fall through to the word-count floor. Only the movement
        # predicate's own clause counts (R03), so a differently negated
        # predicate or an additive "not only moved" stays a real reason.
        if _reason_denies_movement(reason):
            return False
        # Restating the template is not a reason either (F043): it says no fact
        # is lost without naming where anything went. The same holds for
        # "nothing was checked here".
        if re.fullmatch(
                r"(?i)(?:no\s+facts?\s+(?:is|are|was|were)\s+lost|"
                r"nothing\s+(?:was\s+)?(?:lost|removed|checked)(?:\s+here)?)",
                reason):
            return False
        words = re.findall(r"[^\s]+", reason)
        # A short closure that says where the content went ("OK - moved to
        # Methods", "OK - merged into Results", "OK - now in Table 2") is a real
        # reason too. A section WORD alone is not: the old regex accepted
        # "OK - x methods" and even the negation "OK - no results" while
        # rejecting "OK - x", so two-word filler could close a deleted fact
        # (F091). The words must therefore name a section AND say the content
        # moved there.
        if len(words) >= 3 and re.search(
                r"(?i)\b(?:moved|merged|folded|relocated|integrated|reported|restated|"
                r"included|placed|put|now)\b[^.;\n]{0,30}"
                r"\b(?:methods?|results?|discussion|introduction|abstract|"
                r"table\s*\d+|figure\s*\d+|paragraph\s*\d+|supplementary)\b",
                reason):
            return True
        return len(words) >= 4
    if re.match(r"(?i)^manual-required\b", text):
        return True
    if re.match(r"(?i)^fact\s+removed\s*[\u2014\u2013:-]\s*RP-\d+\b", text):
        return True
    return False

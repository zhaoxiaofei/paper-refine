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

    def row_id(row: dict):
        for key in ("id", "finding", "finding_id", "frozen_id"):
            val = row.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    def visit(node, depth: int, keyed_id: str = ""):
        if depth > LEDGER_SCAN_DEPTH:
            return
        if isinstance(node, dict):
            rid = row_id(node) or keyed_id
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


_CONTENT_UNIT_CONTAINED = 0.95


def _content_unit_contained(unit: dict, candidates: list,
                            floor: float = _CONTENT_UNIT_CONTAINED) -> bool:
    """Is every content token of `unit` inside ONE candidate sentence?

    The one-to-one matcher consumes a candidate for a single base unit, so a
    merge of two base sentences into one delivered sentence leaves the second
    base unit unmatched even though its content is fully present. This test
    rescues exactly that case (containment, not similarity) without rescuing a
    deleted sentence: a removed claim's content tokens are not all in one
    delivered sentence.
    """
    tokens = _content_tokens(unit)
    if len(tokens) < 3:
        return False
    for cand in candidates or ():
        if len(tokens & _content_tokens(cand)) / len(tokens) >= floor:
            return True
    return False


def soft_deletion_missing_units(missing, cand_units, exempt_removed=()) -> list:
    """Drop the documented removable units from a base->package `missing` list.

    The one-to-one matcher consumes a candidate for a single base unit, so a
    duplicate's second copy and a merged sentence are still listed as
    `missing`; both are accepted by the soft-deletion policy. Everything else
    in the list is a claim removal and fails the attempt.
    """
    _cand_norms = {u["norm"] for u in cand_units}
    return [u for u in missing
            if not (_removal_is_artifact(u["text"], exempt_removed)
                    or u["norm"] in _cand_norms
                    or _content_unit_contained(u, cand_units))]


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
        disposition = str(row.get("disposition") or "").strip()
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
    r"(?is)(?<![\w.])(?:TODO|TBD|FIXME|XXX|PLACEHOLDER)(?![\w.])"
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


def _removal_is_artifact(text: str, exempt_removed=()) -> bool:
    """Is this removed sentence one of the documented removable units?"""
    if _is_handoff_marker(text) or _EVIDENCE_ARTIFACT_RE.search(text):
        return True
    norm = _deleted_para_norm(text).lower()
    for item in exempt_removed or ():
        sentence = item[1] if isinstance(item, (tuple, list)) and len(item) >= 2 else item
        if norm and norm == _deleted_para_norm(sentence).lower():
            return True
    return False


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
        if not fid or len(evidence) < 20:
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
        quoted = [b for b, cand in _match_content_unit_pairs(units, base_units)[2]
                  if _content_unit_similarity(b, cand) >= _FINDING_QUOTE_MATCH]
        if not quoted:
            continue
        gone, _added, _pairs = _match_content_unit_pairs(quoted, rev_units)
        # The matcher consumes a candidate one-to-one, so a merge of two base
        # sentences into one delivered sentence leaves the second quoted unit
        # unmatched even though its content survives. Rescue that case here as
        # the soft-deletion gate does: an accounting error must mean the claim
        # is gone, not that its sentence was merged.
        lost = [u["text"] for u in gone
                if not (_removal_is_artifact(u["text"], exempt_removed)
                        or _content_unit_contained(u, rev_units))]
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


# =====================================================================
# OUTLINE / DISPOSITION-ARTIFACT GATE
#
# Split out of p06_postchecks.py to keep every part under the documented
# 10,000-line limit (the 2026-11-22 fix-bugs wave pushed p06 over). Resolved at
# CALL time from the shared globals.
# =====================================================================

def row_label(row: dict) -> str:
    """A short, human-usable identifier for one artifact-table row."""
    doc = str(row.get("document") or "").strip()
    head = str(row.get("heading") or "").strip()
    para = str(row.get("paragraph") or "").strip()
    if doc or head or para:
        bits = [b for b in (doc, head, (f"para {para}" if para else "")) if b]
        return " / ".join(bits)[:80]
    for k in ("acronym", "term", "figure", "caption", "item", "field", "check", "kind", "id"):
        v = str(row.get(k) or "").strip()
        if v:
            return f"{k}={v}"[:80]
    return ""


def _quote(text: str, limit: int) -> str:
    """`repr()` of a message excerpt, with an explicit marker when it is cut."""
    text = str(text or "")
    return repr(text[:limit]) + (" (truncated)" if len(text) > limit else "")


def outline_artifact_problems(rows: list) -> list:
    """An OUTLINE whose summaries are echoed first sentences / one verdict."""
    problems = []
    rows = [r for r in rows if r]
    if not rows:
        return problems
    summaries = [str(r.get("summary") or "").strip() for r in rows]
    firsts = [str(r.get("first sentence") or "").strip() for r in rows]
    empty = sum(1 for s in summaries if not s)
    echoed = 0
    for s, f in zip(summaries, firsts):
        if s and f and len(s) > 12 and (f.startswith(s) or s.startswith(f[:len(s)])):
            echoed += 1
    if empty > max(2, int(len(rows) * 0.2)):
        where = [l for l in (row_label(r) for r in rows
                             if not str(r.get("summary") or "").strip()) if l][:4]
        problems.append(f"{empty} of {len(rows)} OUTLINE rows carry no summary "
                        f"(the hierarchy pass cannot be audited)"
                        + (f" -- e.g. {', '.join(where)}" if where else ""))
    if echoed > int(len(rows) * 0.5):
        problems.append(f"{echoed} of {len(rows)} summaries are copies of the row's first "
                        f"sentence -- write what the paragraph CLAIMS")
    # The OUTLINE table's disposition column may be spelled `resolution`/`verdict`
    # (DISPOSITION_COLUMNS); reading only `disposition` let a repeated boilerplate
    # verdict hide in the alias column (F159).
    _dkey = next((k for k in DISPOSITION_COLUMNS if k in rows[0]), "disposition")
    verdicts = [str(r.get(_dkey) or "").strip().lower() for r in rows
                if str(r.get(_dkey) or "").strip()]
    if verdicts:
        text, n = Counter(verdicts).most_common(1)[0]
        if n >= 10 and n / len(rows) >= 0.8 and not _names_check_or_finding(text):
            same = [r for r in rows
                    if str(r.get(_dkey) or "").strip().lower() == text]
            where = [l for l in (row_label(r) for r in same) if l][:4]
            problems.append(f"{n} of {len(rows)} OUTLINE rows carry the same verdict "
                            f"({_quote(text, 120)}) -- dispose each row against its own heading"
                            + (f" -- rows: {', '.join(where)}" if where else ""))
    return problems



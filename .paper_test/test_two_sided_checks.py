#!/usr/bin/env python3
"""Both directions of every two-sided check (the 2026-09-29 one-sidedness fix).

Run:  python3 .paper_test/test_two_sided_checks.py

The repository's checks were one-sided by construction: J3 filed overclaims
(unsupported first/novel claims, causal language over a correlation) while an
UNDERCLAIM -- a supported result hedged into "may"/"could"/"suggests"/"a
trend"/"preliminary" -- was never a finding, and the same "too strong" reading
ran through the other paired classes (M5 items present but unneeded, M21 a
letter claim below the manuscript's evidence, M22 an availability claim weaker
than the verified locator, M29 a printed field the caption never describes, a
document ADDED rather than lost, length compression allowed to strip
meaning-bearing hedging). This suite pins the fix:

  * `paper_docx_format.claim_strength_rows` enumerates BOTH directions, one row
    per claim-bearing paragraph per direction, skipping Methods and the
    reference list (and never treating a required hedge as a defect);
  * `code_side_evidence` carries the family and `seed_evidence_pack` seeds
    `CLAIM_STRENGTH.md` under `review/artifacts/` (review) and `work/` (the
    other layouts), with a disposition column;
  * the seeded review table is a DECISION table: an undisposed row is a
    problem the disposition layer reports;
  * `document_set_check` reports documents the candidate ADDED as well as
    documents it lost, and the stage postcheck warns about them;
  * all six prompts carry the both-directions rule, the judge prompt scores a
    weakened supported claim as `introduced` correctness and the mirror as
    `resolved`, the revise prompt authorises calibration edits in the direction
    the finding names, and the review prompt names the ledger;
  * the skill references and both standalone prompts carry the underclaim, the
    reverse directions (M5/M21/M22/M29) and the compression guard.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nb = _load("paper_two_sided", WS / "paper_pipeline.py")
fmt = _load("paper_two_sided_fmt", WS / "paper_docx_format.py")

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


HEDGED = ("We may have found a modest effect, and the data suggest a trend "
          "toward a higher copy number.")
MAXIMAL = ("Our method proves the first causal mechanism and dramatically "
           "improves accuracy.")


def sample_corpus(dirp: Path) -> None:
    dirp.mkdir(parents=True, exist_ok=True)
    (dirp / "manuscript.md").write_text(
        "Title\n\nAbstract\n\n" + HEDGED + "\n\nIntroduction\n\n" + MAXIMAL
        + "\n\nMethods\n\nCells were induced and may be cultured at 37 C; the "
          "protocol could be adapted.\n\nReferences\n\n1. Smith J. Nature "
          "2019;10:1-9. This method proves the first mechanism.\n",
        encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. the code-side ledger enumerates both directions
# ---------------------------------------------------------------------------


def test_claim_strength_rows():
    print()
    print("== claim_strength_rows enumerates the over AND under directions ==")
    paras = ["Title", "Abstract", HEDGED, "Results", MAXIMAL,
             "Methods", "The assay could be run at 4 C.",
             "References", "1. Smith J. Nature 2019. This proves the first claim."]
    rows = fmt.claim_strength_rows(paras)
    directions = {(r["paragraph"], r["direction"]) for r in rows}
    check("the hedge paragraph is enumerated in the UNDER direction",
          (2, "under") in directions, str(sorted(directions)))
    check("the maximal paragraph is enumerated in the OVER direction",
          (4, "over") in directions, str(sorted(directions)))
    check("Methods is not enumerated (a protocol is not a claim surface)",
          all(r["paragraph"] != 6 for r in rows), str(sorted(directions)))
    check("the reference list is not enumerated",
          all(r["paragraph"] != 8 for r in rows), str(sorted(directions)))
    under = [r for r in rows if r["paragraph"] == 2 and r["direction"] == "under"][0]
    check("an UNDER row carries its markers and the sentence",
          "may" in under["markers"] and "suggest" in under["markers"]
          and "modest" in under["markers"] and HEDGED[:20] in under["sentence"],
          str(under)[:160])
    over = [r for r in rows if r["paragraph"] == 4 and r["direction"] == "over"][0]
    check("an OVER row carries its markers and the sentence",
          "proves" in over["markers"] and "dramatically" in over["markers"]
          and MAXIMAL[:20] in over["sentence"], str(over)[:160])
    check("one row per paragraph per direction (both directions at once)",
          len([r for r in rows if r["paragraph"] == 2]) == 1
          and len([r for r in rows if r["paragraph"] == 4]) == 1)
    check("no direction is produced for a paragraph with no marker",
          all(r["paragraph"] != 0 for r in rows))


# ---------------------------------------------------------------------------
# 2. the evidence pack and the seeded decision table
# ---------------------------------------------------------------------------


def test_evidence_and_seeding():
    print()
    print("== the pack carries the family and the table is seeded with a disposition ==")
    tmp = scratch("paper_two_sided_ev_")
    corpus = tmp / "corpus"
    sample_corpus(corpus)
    ctx = type("C", (), {"cfg": {}})()
    ev = nb.code_side_evidence(ctx, corpus, "scratch:two-sided")
    rows = (ev.get("claims") or {}).get("rows") or []
    check("CODE_SCANS carries the claims family",
          isinstance(ev.get("claims"), dict) and rows,
          nb.evidence_pack_summary(ev)[-120:])
    check("the family carries BOTH directions",
          {r.get("direction") for r in rows} >= {"under", "over"},
          str(sorted({r.get("direction") for r in rows})))
    # review: review/work/ + review/artifacts/; audit/stage: work/ at the root
    for where, sub in (("review", "review"), ("audit", ""), ("stage", "")):
        sb = tmp / f"run_{where}"
        sb.mkdir()
        nb.seed_evidence_pack(ctx, sb, corpus, where)
        ledger = (sb / sub / "work" / "CLAIM_STRENGTH.md") if sub \
            else (sb / "work" / "CLAIM_STRENGTH.md")
        check(f"{where}: work/CLAIM_STRENGTH.md is seeded", ledger.is_file())
        text = ledger.read_text(encoding="utf-8") if ledger.is_file() else ""
        check(f"{where}: the ledger carries a disposition column and both rows",
              "| disposition |" in text and "| under |" in text and "| over |" in text,
              text[:120])
    review_art = tmp / "run_review" / "review" / "artifacts" / "CLAIM_STRENGTH.md"
    check("the review's artifacts/ copy is seeded too (the decision table)",
          review_art.is_file() and "| disposition |" in review_art.read_text(encoding="utf-8"))
    check("the review decision-artifact list includes the ledger",
          "artifacts/CLAIM_STRENGTH.md" in nb.DECISION_ARTIFACTS)
    check("the disposition mandate names the ledger",
          "CLAIM_STRENGTH" in nb.DISPOSITION_MANDATE)


def test_undisposed_row_is_a_problem():
    print()
    print("== an undisposed claim-strength row is a decision-artifact problem ==")
    tmp = scratch("paper_two_sided_quality_")
    art = tmp / "review" / "artifacts"
    art.mkdir(parents=True)
    (art / "CLAIM_STRENGTH.md").write_text(
        "# CLAIM_STRENGTH\n\n| # | document | paragraph | kind | direction | markers | n | "
        "sentence | disposition |\n|---|---|---|---|---|---|---|---|---|\n"
        "| 1 | ms.md | 2 | abstract | under | may | 1 | We may have found X. |  |\n",
        encoding="utf-8")
    report = nb.artifact_quality_report(tmp / "review")
    check("the undisposed ledger row is reported",
          "artifacts/CLAIM_STRENGTH.md" in report,
          str(report)[:200])


# ---------------------------------------------------------------------------
# 3. the document-set check reads both directions
# ---------------------------------------------------------------------------


def test_document_set_both_directions():
    print()
    print("== document_set_check reports ADDED documents as well as lost ones ==")
    tmp = scratch("paper_two_sided_docs_")
    base, cand = tmp / "base", tmp / "cand"
    base.mkdir(), cand.mkdir()
    (base / "manuscript.md").write_text("Abstract\n\nbody text\n", encoding="utf-8")
    (base / "supp.md").write_text("supplement\n", encoding="utf-8")
    (cand / "manuscript.md").write_text("Abstract\n\nbody text, revised\n", encoding="utf-8")
    (cand / "new_note.md").write_text("an invented document\n", encoding="utf-8")
    got = nb.document_set_check([(base, "", ())], [(cand, "", ())])
    check("the lost document is reported",
          got["missing"] == ["supp.md"], str(got))
    check("the ADDED document is reported (the other direction)",
          got.get("added") == ["new_note.md"], str(got))
    # the unchanged case: no missing, no added
    same = tmp / "same"
    shutil.copytree(base, same)
    got2 = nb.document_set_check([(base, "", ())], [(same, "", ())])
    check("an identical corpus reports neither side",
          got2["missing"] == [] and got2.get("added") == [], str(got2))
    check("the stage warning names the added document",
          "NEW document(s) not present in the base" in
          Path(WS / "paper_pipeline.py").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 4. the prompts and the skill references
# ---------------------------------------------------------------------------


def prompts() -> dict:
    P = Path("/tmp/x")
    return {
        "review": nb.review_prompt(P, "r1_review", 1),
        "audit": nb.audit_prompt(P, "r1_audit", 1),
        "rewrite": nb.rewrite_prompt(P, "r1_w1", 1, index=1, total=2),
        "revise": nb.revise_prompt(P, "r1_a2_revise", 1),
        "integrate": nb.integrate_prompt(P, "r1_i1", 1, self_id="a1", other_ids=["w1"]),
        "judge": nb.judge_prompt(P, "judge_tok_j1", 1, "tok", 1, 1, ["v1"]),
    }


def test_prompts():
    print()
    print("== every prompt carries the both-directions rule and the pair's own words ==")
    P = prompts()
    for role, text in P.items():
        check(f"{role}: D1 carries the both-directions rule",
              "EVERY TWO-SIDED CHECK IS RUN IN BOTH DIRECTIONS" in text)
        check(f"{role}: the under direction is named as a defect",
              "underclaim" in text.lower())
    check("the review prompt names the seeded ledger",
          "CLAIM_STRENGTH.md" in P["review"])
    check("the audit prompt names the ledger and its two directions",
          "work/CLAIM_STRENGTH.md" in P["audit"]
          and "BOTH directions" in P["audit"])
    check("the revise prompt names the ledger and forbids moving a claim either way",
          "work/CLAIM_STRENGTH.md" in P["revise"]
          and "EITHER direction" in P["revise"])
    check("the revise prompt authorises a calibration edit in the named direction",
          "CLAIM-CALIBRATION FINDINGS ARE THE ONE EXCEPTION" in P["revise"]
          and "authorises raising it" in P["revise"])
    check("the judge prompt scores a weakened supported claim as introduced correctness",
          "CLAIM CALIBRATION IS SCORED IN BOTH DIRECTIONS" in P["judge"]
          and "a claim the target states MORE weakly than its own evidence supports" in P["judge"]
          and "resolved" in P["judge"])
    review_flat = " ".join(P["review"].split())
    check("the review prompt carries the M29 reverse direction",
          "printed column/panel/encoding the caption never describes" in review_flat)
    check("the review prompt carries the M22 reverse direction",
          "WEAKER than the verified reality" in review_flat)
    check("the length rule forbids stripping a meaning-bearing hedge",
          "NON-MEANING-BEARING hedging" in P["review"]
          and "a hedge that carries the claim's own strength" in P["review"].lower()
          and "hedge" in P["revise"].lower() and "overclaim, not a shortening" in P["revise"])


def test_skill_docs():
    print()
    print("== the skill references carry both directions ==")
    sweeps = (WS / "paper-skills" / "paper-review" / "references" / "sweeps.md").read_text(
        encoding="utf-8")
    rules = (WS / "paper-skills" / "paper-revise" / "references" / "edit_rules.md").read_text(
        encoding="utf-8")
    check("J3 is claim calibration in both directions",
          "claim calibration (overclaiming and underclaiming)" in sweeps
          and "Underclaiming -- the same defect read in the other direction" in sweeps)
    check("the class table maps an underclaim to correctness",
          "overclaim, UNDERCLAIM" in sweeps)
    check("M5 disposes unneeded items as well as missing ones",
          "The sweep runs in BOTH directions" in sweeps)
    check("M21 reads the letter in both directions",
          "a letter claim that falls" in sweeps and "UNDERCLAIM" in sweeps.upper())
    check("M22 covers a statement WEAKER than the verified locator",
          "WEAKER than the verified reality" in sweeps)
    check("M29 pairs print→promise as well as promise→print",
          "The pairing runs in BOTH directions" in sweeps)
    check("M19/M18 compression may not strip a meaning-bearing hedge",
          "What compression may remove" in sweeps
          and "turns an accurate claim into an overclaim" in sweeps)
    check("the revision rules authorise the calibration edit in both directions",
          "CLAIM-CALIBRATION FINDINGS ARE THE EXCEPTION" in rules
          and "raise the claim to exactly the strength" in rules)
    check("the revision rules correct an availability statement in both directions",
          "corrected in BOTH directions" in rules)
    check("the revision rules fix an M29 row by adding the missing description",
          "fixed by ADDING the missing description" in rules)
    ip = (WS / "paper-skills" / "prompts" / "identify_issues.prompt.md").read_text(
        encoding="utf-8")
    ap = (WS / "paper-skills" / "prompts" / "adress_issues.prompt.md").read_text(
        encoding="utf-8")
    check("the standalone review prompt carries the same text (appendix sync)",
          "Underclaiming -- the same defect read in the other direction" in ip
          and "claim calibration (overclaiming and underclaiming)" in ip)
    ap_flat = " ".join(ap.split())
    check("the standalone revise prompt carries the same text (appendix sync)",
          "CLAIM-CALIBRATION FINDINGS ARE THE EXCEPTION" in ap_flat
          and "turns an accurate claim into an overclaim" in ap_flat
          and "corrected in BOTH directions" in ap_flat)


def main() -> int:
    sections = (("ledger", test_claim_strength_rows),
                ("evidence", test_evidence_and_seeding),
                ("quality", test_undisposed_row_is_a_problem),
                ("documents", test_document_set_both_directions),
                ("prompts", test_prompts),
                ("skills", test_skill_docs))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL TWO-SIDED-CHECK SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

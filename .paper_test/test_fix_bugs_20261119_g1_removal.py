#!/usr/bin/env python3
"""Regression checks for fix_bugs wave g1_removal (run 2026-11-19-232857).

Every check pins a defect that this group re-validated on the tree. The probe
that proved each defect before the patch is quoted in the stage result JSON;
the assertions below fail on the unpatched tree and pass after it.

Run with: python3 .paper_test/test_fix_bugs_20261119_g1_removal.py
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402

FAILS: list[str] = []


def check(label: str, cond, detail="") -> None:
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def mk(root, files: dict) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text, encoding="utf-8")
    return root


def pair(tag: str, base_files: dict, cand_files: dict):
    tmp = scratch(f"g1_{tag}_")
    return mk(tmp / "base", base_files), mk(tmp / "pkg", cand_files)


class Ctx:
    def __init__(self, **cfg):
        self.cfg = dict(cfg)
        self.root = None


def unit(text: str, doc: str = "a.md", line: int = 1, index: int = 0) -> dict:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    tokens = re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE)
    return {"document": doc, "line": line, "text": text,
            "norm": text.lower(), "sentence_index": index,
            "tokens": set(tokens)}


def _policy(base, cand, exempt=(), **cfg):
    return pp.content_edit_problems(
        Ctx(**cfg), base, cand, "revise",
        insertions_allowed=True, deletions_allowed=True,
        prefer_rewrite=False, soft_deletions=True,
        exempt_removed=list(exempt))


# ---------------------------------------------------------------- F001
def test_f001_positional_pass_needs_content() -> None:
    print("\n== F001: a same-slot swap is not hidden by a verbatim sibling ==")
    sibling = "The study enrolled 120 participants across three sites."
    base = [unit(sibling, index=0),
            unit("Treatment reduced tumour volume by 62 percent.", index=1)]
    cand = [unit(sibling, index=0),
            unit("All procedures followed institutional guidelines.", index=1)]
    missing, added = pp._match_content_units(base, cand)
    check("F001 the unrelated same-slot replacement is a deletion",
          [u["text"] for u in missing]
          == ["Treatment reduced tumour volume by 62 percent."], missing)
    check("F001 the unrelated same-slot replacement is an insertion",
          [u["text"] for u in added]
          == ["All procedures followed institutional guidelines."], added)
    # A real full rewrite at the same slot still pairs: it shares content.
    rewrite = unit("Tumour volume was reduced by 62 percent after treatment.",
                   index=1)
    missing2, added2 = pp._match_content_units(base, [cand[0], rewrite])
    check("F001 a real same-slot rewrite still pairs", not missing2 and not added2,
          (missing2, added2))


# ---------------------------------------------------------------- F002 / F003 / F050
def test_f002_containment_respects_polarity() -> None:
    print("\n== F002: an inverted claim is not a merge ==")
    base = unit("The treatment was effective in the cohort.")
    negated = unit("The treatment was not effective in the cohort at all.")
    check("F002 a negated claim is not contained",
          pp._content_unit_contained(base, [negated]) is False)
    check("F002 a polarity-preserving merge is still contained",
          pp._content_unit_contained(
              base, [unit("The treatment was effective in the cohort at all sites.")])
          is True)


def test_f003_full_containment() -> None:
    print("\n== F003: containment requires EVERY content token ==")
    words = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet "
             "kilo lima mike november oscar papa quebec romeo sierra tango").split()
    full = unit(" ".join(words))
    one_short = unit(" ".join(words[:-1]))
    check("F003 a merge that loses a token is not containment",
          pp._content_unit_contained(full, [one_short]) is False)
    check("F003 a fully present merge is containment",
          pp._content_unit_contained(full, [unit(" ".join(words))]) is True)


def test_f050_two_token_merge() -> None:
    print("\n== F050: a two-token claim can be merge-covered ==")
    check("F050 'Samples froze.' is covered by the delivered sentence",
          pp._content_unit_contained(
              unit("Samples froze."),
              [unit("All samples froze during transport at minus eighty.")])
          is True)
    check("F050 a one-token fragment is still not containment",
          pp._content_unit_contained(unit("Froze."),
                                     [unit("All samples froze during transport.")])
          is False)


# ---------------------------------------------------------------- F004
def test_f004_exemptions_are_document_scoped_and_consumed() -> None:
    print("\n== F004: pipeline removals are document-scoped and consumed once ==")
    sent = "The cohort included 42 participants."
    base, cand = pair("f004b",
                      {"a.md": "# T\n\n" + sent + " " + sent + "\n"},
                      {"a.md": "# T\n\nNothing at all was measured.\n"})
    got = _policy(base, cand, exempt=[("a.md", sent)])
    check("F004 the second identical copy is still a deletion",
          any("MISSING" in p for p in got), str(got)[:220])
    base2, cand2 = pair(
        "f004x",
        {"main.md": "# T\n\n" + sent + "\n",
         "supplement.md": "# S\n\n" + sent + "\n"},
        {"main.md": "# T\n\nNothing at all was measured.\n",
         "supplement.md": "# S\n\nNothing at all was measured.\n"})
    got2 = _policy(base2, cand2, exempt=[("supplement.md", sent)])
    check("F004 a supplement removal does not whitelist main.md",
          any("main.md" in p and "MISSING" in p for p in got2), str(got2)[:220])
    # The same exemption also feeds the finding-removal accounting (R02): the
    # pair's document must be read there too, or a supplement removal hides a
    # main.md finding removal.
    finding = [{"id": "F1", "evidence": sent, "check": "M1"}]
    lost_other_doc = pp.finding_removal_problems(
        base2, cand2, finding, exempt_removed=[("supplement.md", sent)])
    check("F004 a supplement removal does not excuse the finding's main.md copy",
          bool(lost_other_doc) and lost_other_doc[0].get("lost") == [sent],
          str(lost_other_doc)[:220])
    base3, cand3 = pair("f004finding",
                        {"main.md": "# T\n\n" + sent + "\n"},
                        {"main.md": "# T\n\nNothing at all was measured.\n"})
    lost_main = pp.finding_removal_problems(
        base3, cand3, finding, exempt_removed=[("main.md", sent)])
    check("F004 a removal in the finding's own document is exempt",
          lost_main == [], str(lost_main)[:220])
    base4, cand4 = pair(
        "f004order",
        {"aaa.md": "# A\n\n" + sent + "\n", "main.md": "# T\n\n" + sent + "\n"},
        {"aaa.md": "# A\n\nNothing at all was measured.\n",
         "main.md": "# T\n\nNothing at all was measured.\n"})
    lost_order = pp.finding_removal_problems(
        base4, cand4, finding, exempt_removed=[("aaa.md", sent)])
    check("F004 file order does not let one document's exemption hide another",
          bool(lost_order) and lost_order[0].get("lost") == [sent],
          str(lost_order)[:220])


# ---------------------------------------------------------------- F005
def test_f005_fact_exemptions_are_consumed() -> None:
    print("\n== F005: one pipeline removal exempts one fact occurrence ==")
    sent = "The dose was 62 mg in every cohort."
    base, cand = pair("f005",
                      {"a.md": "# T\n\n" + sent + " " + sent + "\n"},
                      {"a.md": "# T\n\nNothing at all was measured.\n"})
    plain = pp.fact_preservation_problems(base, cand)
    check("F005 both lost copies are reported without an exemption",
          bool(plain) and "lost 62" in plain[0], str(plain)[:160])
    exempt_one = pp.fact_preservation_problems(
        base, cand, exempt_removed=[("a.md", sent)])
    check("F005 one exemption still reports the second deleted copy",
          bool(exempt_one) and "lost 62" in exempt_one[0], str(exempt_one)[:160])
    exempt_both = pp.fact_preservation_problems(
        base, cand, exempt_removed=[("a.md", sent), ("a.md", sent)])
    check("F005 two exemptions cover both pipeline removals", exempt_both == [],
          str(exempt_both)[:160])


# ---------------------------------------------------------------- F008
def test_f008_prose_is_not_a_narrative_citation() -> None:
    print("\n== F008: ordinary capitalised prose is not an author-year citation ==")
    for prose in ("Baseline (2019) values were lower.",
                  "Wave (2020) was first.",
                  "However (2019) the trial stopped.",
                  "Lockdown (2020) changed everything."):
        check(f"F008 no key from {prose!r}", pp._prose_citation_keys(prose) == set(),
              pp._prose_citation_keys(prose))
    check("F008 'Smith et al. (2020)' is still a citation",
          pp._prose_citation_keys("Smith et al. (2020) reported the effect.")
          == {"smith2020"})
    check("F008 'Smith and Jones (2021)' is still a citation",
          pp._prose_citation_keys("Smith and Jones (2021) agreed.")
          == {"smith2021"})
    check("F008 the parenthetical form is unchanged",
          pp._prose_citation_keys("The effect is large (Smith, 2020).")
          == {"smith2020"})


# ---------------------------------------------------------------- F043
def test_f043_negated_disposition_is_not_ok() -> None:
    print("\n== F043: a negated/vacuous deletion reason is refused ==")
    for bad in ("OK — not moved to Methods",
                "OK — failed to merge into Results",
                "OK — never relocated to the supplement",
                "OK — no values were moved to Methods",
                "OK — no evidence that the value moved to Methods",
                "OK — no fact is lost",
                "OK — nothing was checked here"):
        check(f"F043 refused: {bad!r}",
              pp._deletion_disposition_ok(bad) is False, bad)
    for good in ("OK — moved to Methods",
                 "OK — merged into Results",
                 "OK — the value was not lost and was moved to Methods",
                 "OK — not only moved but also merged into Results",
                 "OK — not just moved but merged into Results",
                 "OK — duplicate; no fact lost",
                 "OK — the fact survives in Sec. 2 of main.md",
                 "manual-required",
                 "fact removed — RP-12"):
        check(f"F043 still accepted: {good!r}",
              pp._deletion_disposition_ok(good) is True, good)


# ---------------------------------------------------------------- F045
def test_f045_disposition_alias_is_read() -> None:
    print("\n== F045: the fact-loss backstop reads every disposition alias ==")
    sandbox = scratch("g1_f045_")
    (sandbox / "revised").mkdir()
    (sandbox / "revised" / "a.md").write_text(
        "# T\n\nNothing at all survives here.\n", encoding="utf-8")
    paragraph = "The cohort included 42 participants."
    for key in ("disposition", "resolution", "verdict"):
        row = {"#": "1", "document": "a.md", "line": "3",
               "paragraph": paragraph, key: "OK — no fact is lost"}
        got = pp.deletion_row_fact_loss_problems(sandbox, [row])
        check(f"F045 a row using `{key}` is checked",
              len(got) == 1 and "42" in got[0], str(got)[:160])


# ---------------------------------------------------------------- F049
def test_f049_short_evidence_is_accounted() -> None:
    print("\n== F049: a short verbatim quote is removal-accounted ==")
    base, cand = pair("f049",
                      {"a.md": "# T\n\nThe sky is blue.\n"},
                      {"a.md": "# T\n\nNothing at all survives here.\n"})
    short = pp.finding_removal_problems(
        base, cand, [{"id": "F-1", "evidence": "The sky is blue."}],
        final_status={"F-1": "fixed"})
    check("F049 a 16-character quote is reported",
          len(short) == 1 and short[0]["lost"] == ["The sky is blue."], short)
    floor = pp.finding_removal_problems(
        base, cand, [{"id": "F-2", "evidence": "Blue."}],
        final_status={"F-2": "fixed"})
    check("F049 the sentence-unit floor still drops a fragment", floor == [], floor)


# ---------------------------------------------------------------- F051
def test_f051_lowercase_micro_litre() -> None:
    print("\n== F051: lowercase µl/μl are the same unit as µL ==")
    for spelling in ("µL", "μL", "µl", "μl", "uL", "ul"):
        check(f"F051 {spelling!r} canonicalises to ul",
              pp._fact_survival_canonical_unit(spelling) == "ul",
              pp._fact_survival_canonical_unit(spelling))
    check("F051 a case-only µL -> µl edit is not a lost value",
          pp._fact_survival_lost_tokens(
              "The volume was 250 µL.",
              pp._fact_survival_keys([unit("The volume was 250 µl.")])) == [])
    check("F051 dropping the µl unit is a lost value",
          pp._fact_survival_lost_tokens(
              "The volume was 250 µl.",
              pp._fact_survival_keys([unit("The volume was 250.")]))
          == ["250 ul"])


# ---------------------------------------------------------------- F052
def test_f052_deletion_audit_consumes_one_exemption() -> None:
    print("\n== F052: each pipeline removal covers one deleted occurrence ==")
    sent = "The cohort included 42 participants."
    base, cand = pair("f052a",
                      {"a.md": "# T\n\n" + sent + " " + sent + "\n"},
                      {"a.md": "# T\n\n"})
    rows = pp.deletion_audit_rows(base, cand, exempt_removed=[("a.md", sent)])
    check("F052 the second, session-deleted copy seeds a row", len(rows) == 1, rows)
    base2, cand2 = pair("f052b",
                        {"a.md": "# T\n\n" + sent + " " + sent + "\n"},
                        {"a.md": "# T\n\n" + sent + "\n"})
    rows2 = pp.deletion_audit_rows(base2, cand2, exempt_removed=[("a.md", sent)])
    check("F052 one pipeline removal plus one surviving copy seeds no row",
          rows2 == [], rows2)


# ---------------------------------------------------------------- F055 / F056 / F187
def test_f055_f056_docx_short_units() -> None:
    print("\n== F055/F056: short DOCX paragraphs and rows stay content units ==")
    try:
        import docx
    except ImportError:                                     # pragma: no cover
        check("F055/F056 python-docx available", False, "python-docx missing")
        return

    def build(path, paragraphs, rows=()):
        d = docx.Document()
        for text in paragraphs:
            d.add_paragraph(text)
        if rows:
            table = d.add_table(rows=len(rows), cols=len(rows[0]))
            for i, row in enumerate(rows):
                for j, value in enumerate(row):
                    table.cell(i, j).text = value
        d.save(str(path))

    tmp = scratch("g1_f05x_")
    build(tmp / "base.docx", ["50 mg.", "The normal paragraph is here."],
          [["9", "9"], ["The ordinary row is here", "with text"]])
    units = pp._content_unit_sentences(tmp)
    texts = [u["text"] for u in units]
    check("F055 the short fact-bearing DOCX paragraph is a unit",
          "50 mg." in texts, texts)
    check("F056 the short DOCX table row is a row unit",
          any(u["text"] == "9 | 9" and u.get("cells") == ("9", "9") for u in units),
          [(u["text"], u.get("cells")) for u in units])


def test_f187_prose_pipe_is_not_a_row() -> None:
    print("\n== F187: a prose sentence with a vertical bar is not a table row ==")
    tmp = scratch("g1_f187_")
    mk(tmp / "base", {"m.md":
                      "# T\n\nThe mean |t| was 2.1 in the cohort.\n"})
    base_units = pp._content_unit_sentences(tmp / "base")
    check("F187 the prose pipe unit has no cells",
          base_units and "cells" not in base_units[0],
          [(u["text"], u.get("cells")) for u in base_units])
    mk(tmp / "cand", {"m.md":
                      "# T\n\nThe mean |t| was |2.1| in the cohort.\n"})
    cand_units = pp._content_unit_sentences(tmp / "cand")
    missing, added = pp._match_content_units(base_units, cand_units)
    check("F187 a pipe-count edit pairs instead of delete+insert",
          not missing and not added, (missing, added))
    # A REAL Markdown table row keeps its row shape.
    mk(tmp / "table", {"m.md":
                       "| group | n |\n|---|---|\n| A | 12 |\n"})
    rows = [u for u in pp._content_unit_sentences(tmp / "table")
            if u.get("cells")]
    check("F187 a real Markdown data row is still a row", bool(rows), rows)


# ---------------------------------------------------------------- F070
def test_f070_marker_survives_in_document_mode() -> None:
    print("\n== F070: soft deletions do not exempt a required marker ==")
    marker = "[AUTHOR TO COMPLETE: add the ethics approval number]"
    base, cand = pair("f070",
                      {"a.md": "# T\n\n" + marker + "\n"},
                      {"a.md": "# T\n\nEthics was approved.\n"})
    document = _policy(base, cand, author_to_complete="document")
    check("F070 deleting the marker under `document` is a deletion",
          any("MISSING" in p for p in document), str(document)[:220])
    readme = _policy(base, cand, author_to_complete="readme")
    check("F070 a readme-mode marker removal is required", readme == [], readme)


# ---------------------------------------------------------------- F149
def test_f149_body_prose_is_not_a_corrected_entry() -> None:
    print("\n== F149: a corrected entry does not excuse a body deletion ==")
    body = "The cohort included 42 participants."
    base, cand = pair(
        "f149",
        {"a.md": "# Paper\n\n" + body + "\n\n## References\n\n"
                  "Smith J, Jones K. The cohort included 42 participants. "
                  "Journal of Widgets. 2020;1:1-10.\n"},
        {"a.md": "# Paper\n\n## References\n\n"
                  "Smith J, Jones K, Brown L. The cohort included 42 participants. "
                  "Journal of Widgets. 2020;1:1-10.\n"})
    check("F149 the reference-entry correction is still accepted",
          bool(pp._reference_entry_corrections(base, cand)[0]),
          pp._reference_entry_corrections(base, cand)[0])
    got = pp.content_edit_problems(
        Ctx(), base, cand, "revise", insertions_allowed=False,
        deletions_allowed=False, prefer_rewrite=False, soft_deletions=False)
    missing = [p for p in got if "MISSING" in p]
    check("F149 the deleted body sentence is reported",
          bool(missing) and body in missing[0], str(got)[:260])
    check("F149 the reference-entry unit is not reported as missing",
          all("Smith J, Jones K. The cohort" not in p for p in missing),
          str(missing)[:260])


def main() -> int:
    test_f001_positional_pass_needs_content()
    test_f002_containment_respects_polarity()
    test_f003_full_containment()
    test_f050_two_token_merge()
    test_f004_exemptions_are_document_scoped_and_consumed()
    test_f005_fact_exemptions_are_consumed()
    test_f008_prose_is_not_a_narrative_citation()
    test_f043_negated_disposition_is_not_ok()
    test_f045_disposition_alias_is_read()
    test_f049_short_evidence_is_accounted()
    test_f051_lowercase_micro_litre()
    test_f052_deletion_audit_consumes_one_exemption()
    test_f055_f056_docx_short_units()
    test_f187_prose_pipe_is_not_a_row()
    test_f070_marker_survives_in_document_mode()
    test_f149_body_prose_is_not_a_corrected_entry()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("ALL g1_removal REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

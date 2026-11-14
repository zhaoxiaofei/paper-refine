#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group `journal` (run 20261115-004309).

Standalone style, like `.paper_test/test_fix_bugs_20261115_wave1.py`: every check
is one assertion, the fixtures are hermetic `tempfile.mkdtemp` trees, and a
failure exits 1. Each check pins one confirmed candidate from
`candidates_journal.json`.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paper_pipeline as pp                                                   # noqa: E402

FAILS: list[str] = []
_SCRATCH: list[Path] = []


def scratch(prefix: str = "fbw2j_") -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    _SCRATCH.append(path)
    return path


@atexit.register
def _cleanup() -> None:
    for path in _SCRATCH:
        shutil.rmtree(path, ignore_errors=True)


def check(name: str, cond, detail="") -> None:
    if cond:
        print(f"[ok ] {name}")
        return
    print(f"[FAIL] {name}  -- {detail}")
    FAILS.append(name)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pair(prefix: str, base_files: dict, cand_files: dict):
    root = scratch(prefix)
    base, cand = root / "base", root / "revised"
    base.mkdir()
    cand.mkdir()
    for name, text in base_files.items():
        write(base / name, text)
    for name, text in cand_files.items():
        write(cand / name, text)
    return base, cand


def ctx_for(root: Path):
    ctx = pp.Ctx(root)
    ctx.cfg = {"revision_mode": "transfer", "submit_code": "off", "rounds": 1}
    ctx.state = {"version": 3, "runs": {}, "rounds": {}, "pinned": [], "log": []}
    return ctx


# ---------------------------------------------------------------- F02
def test_f02_citation_correction() -> None:
    print("\n== F02: a citation-key substitution is a correction, an added key is not ==")
    base, cand = pair(
        "f02",
        {"main.md": "As shown before \\cite{smith2020}, the effect is large.\n",
         "refs.bib": "@article{smith2020, title={A}}\n"},
        {"main.md": "As shown before \\cite{smith2021}, the effect is large.\n",
         "refs.bib": "@article{smith2020, title={A}}\n"
                     "@article{smith2021, title={B}}\n"})
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   insertions_allowed=False, deletions_allowed=True)
    check("F02 a corrected citation key is not a new citation", got == [], str(got))
    # The protection the gate exists for: a key ADDED on top of the kept ones
    # is still an insertion.
    base2, cand2 = pair(
        "f02b",
        {"main.md": "The assay was done.\\cite{smith2020} We measured all samples.\n",
         "refs.bib": "@article{smith2020, title={A}}"},
        {"main.md": "The assay was done.\\cite{smith2020,jones2021} We measured all samples.\n",
         "refs.bib": "@article{smith2020, title={A}}\n@article{jones2021, title={B}}"})
    got = pp.content_edit_problems(None, base2, cand2, "revise",
                                   insertions_allowed=False, deletions_allowed=True)
    check("F02 an ADDED citation key is still an insertion",
          any("jones2021" in p and "citation" in p for p in got), str(got))


# ---------------------------------------------------------------- F03
def test_f03_author_year() -> None:
    print("\n== F03: author-year call-outs are citations too ==")
    base, cand = pair(
        "f03",
        {"main.md": "The effect is large (Smith, 2020).\n"},
        {"main.md": "The effect is large (Smith, 2020), and it replicates (Jones, 2021).\n"})
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   insertions_allowed=False, deletions_allowed=True)
    check("F03 a new author-year citation is an insertion",
          any("jones2021" in p and "citation" in p for p in got), str(got))
    check("F03 the same author-year citations are not new keys",
          pp.content_edit_problems(None, base, base, "revise",
                                   insertions_allowed=False,
                                   deletions_allowed=True) == [])


# ---------------------------------------------------------------- F04 / F203
def test_f04_f203_units() -> None:
    print("\n== F04/F203: recorded unit corrections pass; real unit changes stay reported ==")
    base, cand = pair("f04", {"m.md": "The sample was 55 mg of buffer.\n"},
                      {"m.md": "The sample was 55 ml of buffer.\n"})
    check("F04 an unrecorded unit change is still a fact change",
          bool(pp.fact_preservation_problems(base, cand, "revise")))
    write(cand / "README-AUTHOR-TO-COMPLETE.md",
          "| id | manual action |\n|---|---|\n"
          "| T-001 | corrected the measurement to 55 ml per the lab record |\n")
    got = pp.fact_preservation_problems(base, cand, "revise")
    check("F04 a RECORDED pure unit correction clears the gate", got == [], str(got))
    check("F04 the message no longer says to restore the original unit",
          "restore the original" not in pp._fact_unit_change_message(
              [( {"document": "m.md", "line": 1},
                 "55 mg", ["ml"])], "revise: "))
    # F203: equivalent spellings are the same unit; a different unit is real.
    base2, cand2 = pair("f203a", {"m.md": "The sample was 55 mm of buffer.\n"},
                        {"m.md": "The sample was 55 millimeters of buffer.\n"})
    check("F203 55 mm -> 55 millimeters is not a unit change",
          pp.fact_preservation_problems(base2, cand2, "revise") == [])
    base3, cand3 = pair("f203b", {"m.md": "The sample was 55 millimeters of buffer.\n"},
                        {"m.md": "The sample was 55 milliliters of buffer.\n"})
    got = pp.fact_preservation_problems(base3, cand3, "revise")
    check("F203 55 millimeters -> 55 milliliters IS a unit change",
          bool(got) and "UNIT" in got[0], str(got))


# ---------------------------------------------------------------- F14
def test_f14_feedback_symlink() -> None:
    print("\n== F14: feedback staging refuses a planted symlinked directory ==")
    if not hasattr(os, "symlink"):
        check("F14 symlinks unavailable (skipped)", True)
        return
    root = scratch("f14")
    sb = root / "sb"
    (sb / "feedback").mkdir(parents=True)
    outside = root / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, sb / "feedback" / "files", target_is_directory=True)
    except OSError:
        check("F14 symlinks unavailable (skipped)", True)
        return
    letter = root / "letter.txt"
    letter.write_text("Reviewer says: fix the abstract.\n", encoding="utf-8")
    real_files = pp.journal_feedback_files
    real_llm = pp.journal_llm_feedback_files
    real_prev = pp.journal_previous_responses
    pp.journal_feedback_files = lambda ctx: [(letter, "human_review_feedback/letter.txt")]
    pp.journal_llm_feedback_files = lambda ctx: []
    pp.journal_previous_responses = lambda ctx: []
    try:
        ctx = type("C", (), {"pristine": root, "cfg": {"author_to_complete": "readme"}})()
        try:
            pp._write_journal_feedback_inputs(ctx, sb)
            refused = False
        except SystemExit:
            refused = True
        check("F14 a symlinked feedback/files directory is refused", refused)
        check("F14 nothing was copied through the link",
              list(outside.iterdir()) == [], str(list(outside.iterdir())))
    finally:
        pp.journal_feedback_files = real_files
        pp.journal_llm_feedback_files = real_llm
        pp.journal_previous_responses = real_prev


# ---------------------------------------------------------------- F15 / F178
def test_f15_f178_scoped_guard() -> None:
    print("\n== F15/F178: the concern-scoped guard honours verdicts and the code area ==")
    root = scratch("f15")
    sb = root / "sb"
    base, rev = sb / "base", sb / "revised"
    base.mkdir(parents=True)
    rev.mkdir()
    write(base / "main.md", "The original claim.\n")
    write(rev / "main.md", "A completely different claim.\n")
    for verdict, expected in (("false-positive", False), ("manual-required", False),
                              ("confirmed", True)):
        write(rev / "revision_report.json", json.dumps(
            [{"id": "F-001", "verdict": verdict, "file": "main.md"}]))
        got = pp.scoped_scope_problems(None, sb, rev)
        check(f"F15 a {verdict!r} row does not authorize the edit",
              bool(got) is (not expected), str(got))
    # F178: base carries code/, revised code lives at <sandbox>/code, not revised/.
    root = scratch("f178")
    sb = root / "r1_a2_revise"
    (sb / "base" / "code").mkdir(parents=True)
    (sb / "revised" / "code").mkdir(parents=True)
    (sb / "code").mkdir()
    write(sb / "base" / "main.md", "text\n")
    write(sb / "revised" / "main.md", "text\n")
    write(sb / "base" / "code" / "analysis.py", "print(1)\n")
    write(sb / "code" / "analysis.py", "print(999)\n")
    got = pp.scoped_scope_problems(None, sb, sb / "revised")
    check("F178 base/code is not reported as a dropped document",
          not any("dropped" in e and "code/" in e for e in got), str(got))
    check("F178 an unledgered code edit IS reported",
          any("changed 'code/analysis.py'" in e for e in got), str(got))
    write(sb / "revised" / "revision_report.json", json.dumps(
        [{"id": "F-1", "verdict": "confirmed", "file": "code/analysis.py"}]))
    got = pp.scoped_scope_problems(None, sb, sb / "revised")
    check("F178 a ledgered code edit passes", got == [], str(got))


# ---------------------------------------------------------------- F180 / F181 / F182 / F188
def test_publication() -> None:
    print("\n== F180/F181/F182/F188: submission assembly ==")
    # F180 -- the declaration-excluded figure is classified 'absent' by the
    # PKG-2 scan and the pointer sentence is removed, not left dangling.
    root = scratch("f180")
    pkg = root / "pkg"
    (pkg / "figures").mkdir(parents=True)
    write(pkg / "README.md", "Only `manuscript-*.md` will be submitted.\n")
    write(pkg / "manuscript-1.md", "# Results\n\nSee figures/fig1.png for the effect.\n")
    (pkg / "figures" / "fig1.png").write_bytes(b"png")
    dst = pp.publish_journal_submission(ctx_for(root), pkg, "test")
    rec = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    check("F180 the shipped document no longer names the excluded figure",
          "fig1.png" not in (dst / "manuscript-1.md").read_text(encoding="utf-8"),
          (dst / "manuscript-1.md").read_text(encoding="utf-8"))
    check("F180 the removal is recorded as a PKG-2 removal, not PKG-3",
          rec.get("removed_dangling_references")
          and not rec.get("unresolvable_references"), str(rec.get("unresolvable_references")))
    # F181 -- a symlinked response DIRECTORY must not publish outside bytes.
    root = scratch("f181")
    outside = scratch("f181out")
    pkg = root / "pkg"
    pkg.mkdir()
    write(pkg / "main.md", "# Main\n\nText.\n")
    write(outside / "RESPONSE_TO_REVIEWERS.md", "# Response\n\nsecret\n")
    write(outside / "response_map.json", '{"rows": []}')
    sb = root / "runs" / "r1_response"
    sb.mkdir(parents=True)
    try:
        os.symlink(outside, sb / "response", target_is_directory=True)
        symlinked = True
    except OSError:
        symlinked = False
    if symlinked:
        ctx = ctx_for(root)
        ctx.cfg["revision_mode"] = "resubmit"
        try:
            pp.publish_journal_submission(ctx, pkg, "test", response_dir=sb)
            refused = False
        except SystemExit:
            refused = True
        check("F181 a symlinked response/ directory is refused", refused)
        check("F181 no outside letter was published",
              not (root / "journal_submission" / "RESPONSE_TO_REVIEWERS.md").exists())
    else:
        check("F181 symlinks unavailable (skipped)", True)
    # F182 -- a crashed PKG-2 strip is recorded in the submission record.
    root = scratch("f182")
    pkg = root / "pkg"
    pkg.mkdir()
    write(pkg / "main.tex", "The data are in raw_data/tables.tsv.\n")
    real = pp.strip_dangling_references_in_dir

    def boom(*a, **k):
        raise OSError("simulated strip failure")

    pp.strip_dangling_references_in_dir = boom
    try:
        pp.publish_journal_submission(ctx_for(root), pkg, "test")
        rec = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    finally:
        pp.strip_dangling_references_in_dir = real
    check("F182 a failed PKG-2 scan is recorded in journal_submission.json",
          "simulated strip failure" in str(rec.get("reference_strip_error")), str(rec)[:300])
    # F188 -- an empty submission is refused instead of published.
    root = scratch("f188")
    pkg = root / "pkg"
    (pkg / "raw_data").mkdir(parents=True)
    write(pkg / "raw_data" / "d.csv", "a\n")
    try:
        pp.publish_journal_submission(ctx_for(root), pkg, "test")
        refused = False
    except SystemExit:
        refused = True
    check("F188 an empty journal_submission/ is refused", refused)
    check("F188 nothing was published", not (root / "journal_submission").exists())


# ---------------------------------------------------------------- F183/F185/F186/F187/F189
def _done(sb: Path, kind: str, run_id: str, summary=None) -> None:
    payload = {"status": "complete", "stage": kind, "run_id": run_id, "round": 1}
    if summary is not None:
        payload["summary"] = summary
    write(sb / "_pipeline_done.json", json.dumps(payload))


def test_preflights() -> None:
    print("\n== F183/F185/F186/F187/F189: pre-flight parity with the postcheck ==")
    # F183 -- a deleted seeded decision table is reported by the pre-flight.
    root = scratch("f183")
    sb = root / "r1_guided_review"
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    write(sb / "guided_review" / "findings.json", '{"findings": []}')
    _done(sb, "guided_review", "r1_guided_review")
    ok, errs, _warns = pp.sandbox_selfcheck(sb, "guided_review", "r1_guided_review", 1)
    check("F183 the pre-flight reports the deleted seeded decision table",
          any("decision artifact" in e and "is missing" in e for e in errs), str(errs)[:300])
    # F185 -- header-only DIFF_LEDGER with donors is an error, not a warning.
    root = scratch("f185")
    sb = root / "runs" / "r1_i1"
    for d in (sb / "self", sb / "others" / "d1", sb / "integrated"):
        d.mkdir(parents=True)
        write(d / "main.md", "# Main\n\nSame text.\n")
    write(sb / "integrated" / "DIFF_LEDGER.md",
          "| donor | artifact | size | finding effect | verdict | revalidated |\n"
          "|---|---|---|---|---|---|\n")
    rows = "\n".join(f"| L{i} | 0 | no change |" for i in range(1, 12))
    write(sb / "integrated" / "work" / "R6_language.md",
          "| step | rows changed | note |\n|---|---|---|\n" + rows + "\n")
    _done(sb, "integrate", "r1_i1", {"manual_items": 0})
    ctx = ctx_for(root)
    rec = ctx.register("r1_i1", "integrate", 1, "runs/r1_i1")
    rec["other_ids"] = ["d1"]
    ok, errs, _warns = pp.sandbox_selfcheck(sb, "integrate", "r1_i1", 1)
    check("F185 a row-less DIFF_LEDGER with donors is a pre-flight ERROR",
          any("DIFF_LEDGER" in e and "carries no ledger row" in e for e in errs),
          str(errs)[:300])
    # F186 -- an empty REWRITE_REPORT.md is an error.
    root = scratch("f186")
    sb = root / "r1_a1_rewrite"
    write(sb / "rewritten" / "main.md", "# Main\n\nText.\n")
    write(sb / "rewritten" / "REWRITE_REPORT.md", "")
    _done(sb, "rewrite", "r1_a1_rewrite", {"manual_items": 0})
    ok, errs, _warns = pp.sandbox_selfcheck(sb, "rewrite", "r1_a1_rewrite", 1)
    check("F186 an empty REWRITE_REPORT.md is a pre-flight ERROR",
          any("REWRITE_REPORT.md is EMPTY" in e for e in errs), str(errs)[:300])
    # F187 -- a judge without a marker gets the postcheck's WARNING, not an error.
    root = scratch("f187")
    sb = root / "r1_j1"
    write(sb / "judge" / "x.md", "x")
    write(sb / "scores.json", '{"target_id": "T1", "judge_index": 0, "ledger": []}')
    ok, errs, warns = pp.sandbox_selfcheck(sb, "judge", "r1_j1", 1)
    check("F187 a missing judge marker is not a pre-flight ERROR",
          not any("completion marker" in e for e in errs), str(errs)[:300])
    check("F187 the judge marker warning mirrors the postcheck",
          any("judge signal" in w for w in warns), str(warns)[:300])
    # F189 -- a stray required report is previewed as ADOPTED, not failed.
    root = scratch("f189")
    sb = root / "r1_a1_rewrite"
    write(sb / "rewritten" / "main.md", "# Main\n\nText.\n")
    write(sb / "REWRITE_REPORT.md", "Level: structural\n\nThe report.\n")
    _done(sb, "rewrite", "r1_a1_rewrite", {"manual_items": 0})
    ok, errs, warns = pp.sandbox_selfcheck(sb, "rewrite", "r1_a1_rewrite", 1)
    check("F189 the stray report is not reported as a missing error",
          not any("REWRITE_REPORT.md is missing" in e for e in errs), str(errs)[:300])
    check("F189 the pre-flight says the postcheck ADOPTS it",
          any("ADOPTS" in w for w in warns), str(warns)[:300])


# ---------------------------------------------------------------- F190/F191/F199
def test_deletion_audit() -> None:
    print("\n== F190/F191/F199: the deletion-audit disposition contract ==")
    sb = scratch("f190")
    audit = sb / "revision_audit" / "DELETED_PARAGRAPHS.md"
    write(audit,
          "| # | document | line | paragraph | disposition notes |\n"
          "|---|---|---|---|---|\n"
          "| D1-abc | main.md | 3 | A long paragraph that was removed entirely. |  |\n")
    got = pp.deletion_audit_problems(sb, expected_rows=1)
    check("F190 a renamed `disposition notes` column is reported, not read as empty",
          any("no disposition column" in p for p in got), str(got))
    write(audit,
          "| # | document | line | paragraph | disposition |\n"
          "|---|---|---|---|---|\n"
          "| D1-abc | main.md | 3 | A long paragraph that was removed entirely. | "
          "OK — nothing removed |\n")
    got = pp.deletion_audit_problems(sb, expected_rows=1)
    check("F191 `OK — nothing removed` cannot dispose a real deleted row",
          any("outside the seeded vocabulary" in p for p in got), str(got))
    check("F191 the empty-seed phrase is still accepted by the helper",
          pp._deletion_disposition_ok("OK — nothing removed"))
    write(audit,
          "| # | document | line | paragraph | disposition |\n"
          "|---|---|---|---|---|\n"
          "| D1-abc | main.md | 3 | A long paragraph that was removed entirely. | "
          "OK — duplicate; no fact lost |\n"
          "\n| metric | value |\n|---|---|\n| rows | 1 |\n")
    got = pp.deletion_audit_problems(sb, expected_rows=1)
    check("F199 an appended summary table does not fail a disposed audit", got == [], str(got))


# ---------------------------------------------------------------- F194/F195/F196
def test_fact_gate_exemptions() -> None:
    print("\n== F194/F195/F196: fact-gate exemptions are scoped ==")
    # F194 -- a required hand-off-marker removal is not a lost fact.
    base, cand = pair(
        "f194",
        {"main.md": "# Methods\n\nWe measured the plots carefully.\n\n"
                    "[AUTHOR TO COMPLETE: state grant number 12345]\n"},
        {"main.md": "# Methods\n\nWe measured the plots carefully.\n"})
    check("F194 removing an author marker is not a lost fact",
          pp.fact_preservation_problems(base, cand, "revise") == [])
    check("F194 removing a marker seeds no deletion-audit row",
          pp.deletion_audit_rows(base, cand) == [])
    # F195 -- the pipeline's own T-001 id does not exempt the value 1.0.
    base, cand = pair(
        "f195",
        {"main.md": "# Results\n\nWe used 1.0 mg of the compound in the assay.\n\n"
                    "We measured every plot carefully in the stand.\n"},
        {"main.md": "# Results\n\nWe measured every plot carefully in the stand.\n"})
    write(cand / "README-AUTHOR-TO-COMPLETE.md",
          "| id | manual action |\n|---|---|\n"
          "| T-001 | restore the archived block count from the deposit |\n")
    got = pp.fact_preservation_problems(base, cand, "revise")
    check("F195 T-001 does not exempt the value 1.0",
          any("1.0" in p for p in got), str(got))
    # F196 -- a corrupt submitted DOCX is reported by the fact/identity gates.
    base, cand = pair("f196",
                      {"main.md": "We measured every plot carefully in the stand.\n"},
                      {"main.md": "We measured every plot carefully in the stand.\n"})
    (cand / "broken.docx").write_bytes(b"not a zip")
    got = pp.fact_preservation_problems(base, cand, "revise")
    check("F196 the fact gate reports an unreadable submitted file",
          any("could not be scanned for the fact-survival gate" in p for p in got), str(got))
    got = pp.identity_typo_problems(cand, "revise")
    check("F196 the identity gate reports an unreadable submitted file",
          any("could not be scanned for the identity-typo gate" in p for p in got), str(got))


# ---------------------------------------------------------------- F197/F198
def test_read_coverage() -> None:
    print("\n== F197/F198: unscannable submitted files are recorded ==")
    root = scratch("f197")
    base, rev = root / "base", root / "revised"
    base.mkdir()
    rev.mkdir()
    write(base / "main.md", "The original careful paragraph that is long enough.\n")
    write(rev / "main.md", "The original careful paragraph that is long enough.\n")
    outside = root / "outside.md"
    write(outside, "Some outside prose paragraph that is definitely long enough.\n")
    try:
        os.symlink(outside, base / "link.md")
        linked = True
    except OSError:
        linked = False
    skipped: list = []
    pp.deletion_audit_rows(base, rev, skipped=skipped)
    if linked:
        check("F197 a submitted file symlink is reported as unscannable",
              "link.md" in skipped, str(skipped))
    else:
        check("F197 symlinks unavailable (skipped)", True)
    base2, rev2 = pair("f198", {"paper.rtf": "{\\rtf1 long prose here and more prose.}\n"},
                       {"paper.rtf": "{\\rtf1 long prose here and more prose.}\n"})
    skipped = []
    pp.deletion_audit_rows(base2, rev2, skipped=skipped)
    check("F198 a submitted .rtf manuscript is recorded as unscannable",
          skipped.count("paper.rtf") >= 1, str(skipped))


# ---------------------------------------------------------------- F200/F201/F202
def test_unit_matching_and_markers() -> None:
    print("\n== F200/F201/F202: heading filter, marker symmetry, sentence split ==")
    # F200 -- a renamed style heading is not a deleted paragraph.
    try:
        from docx import Document
    except ImportError:
        Document = None
    if Document is not None:
        root = scratch("f200")
        base, rev = root / "base", root / "revised"
        base.mkdir()
        rev.mkdir()

        def make(p, heading):
            doc = Document()
            doc.add_heading(heading, level=1)
            doc.add_paragraph("We measured every plot carefully in the stand.")
            doc.save(p)

        make(base / "m.docx", "A very long results and discussion heading for the study")
        make(rev / "m.docx", "A different long heading for the same study section")
        check("F200 a renamed DOCX style heading seeds no deleted-paragraph row",
              pp.deletion_audit_rows(base, rev) == [])
    else:
        check("F200 python-docx unavailable (skipped)", True)
    # F201 -- document mode: a marker kept on BOTH sides is not a deletion.
    class Ctx:
        cfg = {"author_to_complete": "document"}

    text = ("We measured the plots carefully in the stand.\n\n"
            "[AUTHOR TO COMPLETE: state the grant number]\n")
    base, cand = pair("f201", {"m.md": text}, {"m.md": text})
    check("F201 a marker kept on both sides is not a deletion",
          pp.content_edit_problems(Ctx(), base, cand, "x", insertions_allowed=False,
                                   deletions_allowed=False) == [])
    write(cand / "m.md", "We measured the plots carefully in the stand.\n")
    check("F201 removing the marker is still a deletion in document mode",
          bool(pp.content_edit_problems(Ctx(), base, cand, "x", insertions_allowed=True,
                                        deletions_allowed=False)))
    # F202 -- 'vitamin D.' / 'No.' are sentence boundaries, so deleting the
    # FOLLOWING sentence is visible.
    for first in ("vitamin D.", "The answer was No."):
        base, cand = pair(
            "f202",
            {"m.md": "The patient was given " + first +
                     " The following claim is important and must survive.\n"},
            {"m.md": "The patient was given " + first + "\n"})
        got = pp.content_edit_problems(None, base, cand, "x", insertions_allowed=True,
                                       deletions_allowed=False)
        check(f"F202 a sentence after {first!r} is a separate content unit",
              bool(got), str(got))


# ---------------------------------------------------------------- F205
def test_f205_bom() -> None:
    print("\n== F205: a UTF-8 BOM is already an encoding marker, not content ==")
    root = scratch("f205")
    path = root / "m.md"
    path.write_bytes(b"\xef\xbb\xbf# Methods\n\nWe measured 55 mg today.\n")
    text = pp.read_text_bounded(path)
    check("F205 read_text_bounded strips the BOM", text and not text.startswith("\ufeff"),
          repr(text[:6]) if text else text)
    base, cand = root / "base", root / "revised"
    base.mkdir()
    cand.mkdir()
    (base / "m.md").write_bytes(b"\xef\xbb\xbf# Methods\n\nWe measured the plot carefully.\n")
    (cand / "m.md").write_bytes(b"# Methods\n\nWe measured the plot carefully.\n")
    check("F205 adding/removing a BOM seeds no deletion-audit row",
          pp.deletion_audit_rows(base, cand) == [])


def main() -> int:
    test_f02_citation_correction()
    test_f03_author_year()
    test_f04_f203_units()
    test_f14_feedback_symlink()
    test_f15_f178_scoped_guard()
    test_publication()
    test_preflights()
    test_deletion_audit()
    test_fact_gate_exemptions()
    test_read_coverage()
    test_unit_matching_and_markers()
    test_f205_bom()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL WAVE-2 JOURNAL REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

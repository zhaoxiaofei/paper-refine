#!/usr/bin/env python3
"""The deliverable audit/repair contracts (concern ledger + response letter).

These are unit-level checks of the validators the new stages use. The end-to-end
chain is exercised by the journal-revision-mode suites; here we pin the rules a
session could otherwise evade:
  * a scoped (major/minor) root admits HUMAN feedback only -- no LLM-review row;
  * every generated concern is disposed exactly once and no new concern is added;
  * a defect needs a correction (not just "I disagree");
  * the repair may remove a dropped concern only when it CONFIRMS the drop;
  * an audit that never disposed a row fails, and a repair that invents a
    concern fails;
  * the response audit/repair has the same one-row-per-concern contract.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

WS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("paper_audit", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_audit"] = nb
spec.loader.exec_module(nb)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def sandbox() -> Path:
    d = Path(tempfile.mkdtemp(prefix="paper_deliv_audit_"))
    (d / "feedback" / "files").mkdir(parents=True)
    (d / "feedback" / "files" / "editor.txt").write_text("Reviewer 1: fix the claim.\n",
                                                          encoding="utf-8")
    (d / "response").mkdir()
    (d / "response" / "RESPONSE_TO_REVIEWERS.md").write_text("# response\n", encoding="utf-8")
    (d / "response" / "response_map.json").write_text("{}", encoding="utf-8")
    return d


def concerns(ids=("R1-1", "R1-2")) -> list:
    return [{"id": i, "source": "editor.txt", "author": "Reviewer 1", "action": "text",
             "disposition": "to-fix", "quote": "fix the claim", "summary": "fix",
             "manuscript_location": "manuscript.txt:1", "evidence_needed": ""}
            for i in ids]


def audit_rows(ids=("R1-1", "R1-2"), verdict="confirmed", defects=None) -> list:
    return [{"id": i, "verdict": verdict,
             "defects": ([] if verdict == "confirmed" else (defects or [])),
             "reason": "stub reason with enough words",
             "evidence": "stub evidence"} for i in ids]


def test_human_only_scoped_streams():
    print("== scoped provenance ==")
    check("major/minor admit the human stream only",
          nb.JOURNAL_MODES["major"]["streams"] == ("human",)
          and nb.JOURNAL_MODES["minor"]["streams"] == ("human",),
          str(nb.JOURNAL_MODES["major"]["streams"]))
    root = Path(tempfile.mkdtemp(prefix="paper_prov_"))
    (root / "llm_review_feedback").mkdir(parents=True)
    (root / "llm_review_feedback" / "review.md").write_text("a model review", encoding="utf-8")
    (root / "human_review_feedback").mkdir(parents=True)
    (root / "human_review_feedback" / "letter.txt").write_text("fix it", encoding="utf-8")
    scoped = SimpleNamespace(cfg={"revision_mode": "major"}, pristine=root)
    other = SimpleNamespace(cfg={"revision_mode": "resubmit"}, pristine=root)
    check("a scoped root stages NO LLM-review feedback",
          nb.journal_llm_feedback_files(scoped) == [])
    check("an unscoped feedback mode still stages it",
          [label for _p, label in nb.journal_llm_feedback_files(other)]
          == ["llm_review_feedback/review.md"])


def test_concern_audit():
    print("== concern audit ==")
    sb = sandbox()
    ids = ["R1-1", "R1-2"]
    good = {"rows": audit_rows(ids),
            "coverage": [{"file": "editor.txt", "examined": 2, "defects": 0, "note": "read"}]}
    check("a complete confirmed audit passes",
          nb.concern_audit_artifact_problems(good, ids, sb) == [],
          str(nb.concern_audit_artifact_problems(good, ids, sb)))
    missing = dict(good, rows=audit_rows(["R1-1"]))
    check("a missing concern id fails",
          any("does not dispose" in e for e in
              nb.concern_audit_artifact_problems(missing, ids, sb)))
    extra = dict(good, rows=audit_rows(ids) + [{
        "id": "R1-9", "verdict": "confirmed", "defects": [],
        "reason": "stub reason with enough words", "evidence": "x"}])
    check("an invented concern id fails",
          any("not ledger concerns" in e for e in
              nb.concern_audit_artifact_problems(extra, ids, sb)))
    defect_missing = {"rows": audit_rows(ids, "defective", [
        {"type": "wrong-disposition", "wrong": "to-fix", "correct": "",
         "basis": "base/manuscript.txt:1 already answers it"}]),
        "coverage": good["coverage"]}
    check("a correction without a replacement fails",
          any("`correct` is empty" in e for e in
              nb.concern_audit_artifact_problems(defect_missing, ids, sb)))
    no_cov = dict(good, coverage=[])
    check("a coverage gap fails",
          any("coverage" in e for e in
              nb.concern_audit_artifact_problems(no_cov, ids, sb)))
    dropped = {"rows": audit_rows(ids, "dropped", [
        {"type": "not-a-demand", "wrong": "thanks", "correct": "",
         "basis": "editor.txt: the quoted sentence is a closing thanks"}]),
        "coverage": good["coverage"]}
    check("a dropped row with its evidence passes",
          nb.concern_audit_artifact_problems(dropped, ids, sb) == [],
          str(nb.concern_audit_artifact_problems(dropped, ids, sb)))
    wrong_drop = {"rows": audit_rows(ids, "dropped", [
        {"type": "wrong-disposition", "wrong": "to-fix", "correct": "",
         "basis": "x"}]), "coverage": good["coverage"]}
    check("a human field defect cannot be 'dropped'",
          any("dropped concern may only" in e for e in
              nb.concern_audit_artifact_problems(wrong_drop, ids, sb)))
    wrong_defect = {"rows": audit_rows(ids, "defective", [
        {"type": "not-human", "wrong": "x", "correct": "y", "basis": "z"}]),
        "coverage": good["coverage"]}
    check("a non-human row cannot be 'defective'",
          any("must be human-raised" in e for e in
              nb.concern_audit_artifact_problems(wrong_defect, ids, sb)))
    loc = [{"id": "R1-1", "disposition": "to-fix",
            "manuscript_location": "feedback/original_submission/manuscript.txt:3"}]
    check("a to-fix target in original_submission is refused",
          bool(nb._concern_location_problems(loc)))


def repair_doc(rows, audit=None):
    rows = [dict(r) for r in rows]
    if audit:
        av = {r.get("id"): str(r.get("verdict") or "")
              for r in (audit.get("rows") or []) if isinstance(r, dict)}
        for r in rows:
            r.setdefault("audit_verdict", av.get(r.get("id"), ""))
    counts = {"input": len(rows),
              "kept": sum(1 for r in rows
                          if r.get("action") not in ("corrected", "merged", "dropped")),
              "corrected": sum(1 for r in rows if r.get("action") == "corrected"),
              "merged": sum(1 for r in rows if r.get("action") == "merged"),
              "dropped": sum(1 for r in rows if r.get("action") == "dropped"),
              "rejected": sum(1 for r in rows if r.get("verdict") == "rejected")}
    return {"rows": rows, "counts": counts}


def test_concern_repair():
    print("== concern repair ==")
    sb = sandbox()
    (sb / "concern_repair").mkdir()
    orig = concerns()
    audit = {"rows": [
        {"id": "R1-1", "verdict": "dropped", "defects": [{"type": "not-a-demand"}],
         "reason": "stub reason with enough words", "evidence": "x"},
        {"id": "R1-2", "verdict": "confirmed", "defects": [],
         "reason": "stub reason with enough words", "evidence": "x"}]}

    def write(rows, audit_doc=None):
        (sb / "concern_repair" / "REPAIR_LEDGER.json").write_text(
            json.dumps(repair_doc(rows, audit_doc or audit)), encoding="utf-8")

    write([
        {"id": "R1-1", "verdict": "confirmed", "action": "dropped",
         "reason": "stub reason with enough words", "evidence": "x"},
        {"id": "R1-2", "verdict": "confirmed", "action": "no-change",
         "reason": "stub reason with enough words", "evidence": "x"}])
    check("a confirmed drop with the row removed passes",
          nb.concern_repair_ledger_problems(sb, audit, orig, concerns(["R1-2"])) == [],
          str(nb.concern_repair_ledger_problems(sb, audit, orig, concerns(["R1-2"]))))
    write([
        {"id": "R1-1", "verdict": "rejected", "action": "kept",
         "reason": "stub reason with enough words", "evidence": "x"},
        {"id": "R1-2", "verdict": "confirmed", "action": "no-change",
         "reason": "stub reason with enough words", "evidence": "x"}])
    check("a rejected drop that removed the concern fails",
          any("must remain" in e for e in
              nb.concern_repair_ledger_problems(sb, audit, orig, concerns(["R1-2"]))))
    write([
        {"id": "R1-1", "verdict": "rejected", "action": "kept",
         "reason": "stub reason with enough words", "evidence": "x"},
        {"id": "R1-2", "verdict": "confirmed", "action": "no-change",
         "reason": "stub reason with enough words", "evidence": "x"}])
    check("a rejected drop that keeps the concern passes",
          nb.concern_repair_ledger_problems(sb, audit, orig, orig) == [],
          str(nb.concern_repair_ledger_problems(sb, audit, orig, orig)))
    write([
        {"id": "R1-1", "verdict": "confirmed", "action": "kept",
         "reason": "stub reason with enough words", "evidence": "x"},
        {"id": "R1-2", "verdict": "confirmed", "action": "no-change",
         "reason": "stub reason with enough words", "evidence": "x"}])
    check("a repair may not add a concern",
          any("added concern" in e for e in
              nb.concern_repair_ledger_problems(sb, audit, orig, orig + concerns(["R1-9"]))))


def test_response_audit_repair():
    print("== response audit/repair ==")
    sb = sandbox()
    ids = ["R1-1", "R1-2"]
    good = {"rows": [{"id": i, "verdict": "confirmed", "defects": [],
                      "reason": "stub reason with enough words",
                      "evidence": "stub evidence"} for i in ids],
            "coverage": [{"file": "response/RESPONSE_TO_REVIEWERS.md", "examined": 1,
                          "defects": 0, "note": "read"},
                         {"file": "response/response_map.json", "examined": 1,
                          "defects": 0, "note": "read"}]}
    check("a complete response audit passes",
          nb.response_audit_artifact_problems(good, ids, sb) == [],
          str(nb.response_audit_artifact_problems(good, ids, sb)))
    bad = {"rows": [{"id": "R1-1", "verdict": "defective",
                     "defects": [{"type": "unsupported-claim", "location": "letter:1",
                                  "wrong": "we added a table", "correct": "",
                                  "basis": ""}],
                     "reason": "stub reason with enough words", "evidence": "x"}],
           "coverage": good["coverage"]}
    check("a response defect without a basis fails",
          any("`basis` is empty" in e for e in
              nb.response_audit_artifact_problems(bad, ids, sb)))
    good_defect = {"rows": [
        {"id": "R1-1", "verdict": "defective",
         "defects": [{"type": "missing-answer", "location": "response/letter:1",
                      "wrong": "no answer", "correct": "answer it", "basis": "target/x"}],
         "reason": "stub reason with enough words", "evidence": "stub evidence"},
        {"id": "R1-2", "verdict": "confirmed", "defects": [],
         "reason": "stub reason with enough words", "evidence": "stub evidence"}],
        "coverage": good["coverage"]}
    check("a valid response defect type is accepted",
          nb.response_audit_artifact_problems(good_defect, ids, sb) == [],
          str(nb.response_audit_artifact_problems(good_defect, ids, sb)))
    (sb / "response_repair").mkdir()
    audit = {"rows": [{"id": "R1-1", "verdict": "confirmed", "defects": [],
                       "reason": "stub reason with enough words", "evidence": "x"}]}
    (sb / "response_repair" / "REPAIR_LEDGER.json").write_text(json.dumps({
        "rows": [{"id": "R1-1", "audit_verdict": "confirmed", "verdict": "confirmed",
                  "action": "no-change",
                  "reason": "stub reason with enough words", "evidence": "x"}],
        "counts": {"input": 1, "kept": 1, "corrected": 0, "rejected": 0}}),
        encoding="utf-8")
    check("a confirmed response repair row passes",
          nb.response_repair_ledger_problems(sb, audit, {"R1-1"}) == [],
          str(nb.response_repair_ledger_problems(sb, audit, {"R1-1"})))
    (sb / "response_repair" / "REPAIR_LEDGER.json").write_text(json.dumps({
        "rows": [{"id": "R1-1", "audit_verdict": "confirmed", "verdict": "confirmed",
                  "action": "dropped",
                  "reason": "stub reason with enough words", "evidence": "x"}],
        "counts": {"input": 1, "kept": 0, "corrected": 0, "rejected": 0}}),
        encoding="utf-8")
    check("the response repair may not drop a concern",
          any("action" in e for e in
              nb.response_repair_ledger_problems(sb, audit, {"R1-1"})))


def _journal_lib():
    spec2 = importlib.util.spec_from_file_location(
        "jr_deliv", str(WS / ".paper_test" / "journal_revision_modes_lib.py"))
    jr = importlib.util.module_from_spec(spec2)
    sys.modules["jr_deliv"] = jr
    spec2.loader.exec_module(jr)
    return jr


def test_e2e_drop_and_reject():
    print("== end to end: a dropped concern leaves the repaired ledger and the letter ==")
    import os
    jr = _journal_lib()
    tmp = Path(tempfile.mkdtemp(prefix="paper_deliv_e2e_"))
    os.environ["PAPER_STUB_CONCERN_AUDIT_DROP"] = "C1"
    os.environ.pop("PAPER_STUB_CONCERN_REPAIR_REJECT", None)
    try:
        root = jr.setup_and_run(tmp, "major")
    finally:
        os.environ.pop("PAPER_STUB_CONCERN_AUDIT_DROP", None)
    rep = json.loads((root / "runs" / "r1_concern_repair" / "concerns"
                      / "JF_concerns.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in rep.get("concerns") or []]
    check("the repaired ledger removed the dropped concern", ids == ["C2"], str(ids))
    fj = json.loads((root / "runs" / "r1_concern_repair" / "guided_review"
                     / "findings.json").read_text(encoding="utf-8"))
    check("the finding list answers only the surviving concern",
          [f.get("concern") for f in fj.get("findings") or []] == ["C2"],
          str([f.get("concern") for f in fj.get("findings") or []]))
    rmap = json.loads((root / "runs" / "r1_response_repair" / "response"
                       / "response_map.json").read_text(encoding="utf-8"))
    check("the repaired response covers only the surviving concern",
          [r.get("id") for r in rmap.get("rows") or []] == ["C2"],
          str([r.get("id") for r in rmap.get("rows") or []]))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    _runs = state.get("runs") or {}
    _rev = _runs.get("r1_a2_revise") or {}
    _draft = _runs.get("r1_response_draft") or {}
    check("the scoped revised manuscript was revision-audited",
          (_rev.get("revision_audit") or {}).get("status") == "done",
          str(_rev.get("revision_audit")))
    check("the point-by-point response plan was written before the revision",
          bool(_draft.get("finished")) and bool(_rev.get("started"))
          and str(_draft["finished"]) <= str(_rev["started"]),
          f"draft={_draft.get('finished')} revise={_rev.get('started')}")
    check("the reviser received the response plan",
          "response_plan" in (_rev.get("inputs_manifest") or {}),
          str(sorted((_rev.get("inputs_manifest") or {}).keys())))
    _rprompt = (root / "runs" / "r1_a2_revise" / "PROMPT.md").read_text(encoding="utf-8")
    check("the revise prompt tells the session to implement the response plan",
          "response_plan" in _rprompt)
    letter = (root / "journal_submission" / "RESPONSE_TO_REVIEWERS.md").read_text(
        encoding="utf-8")
    check("the published letter does not answer the dropped concern",
          "## C2" in letter and "## C1" not in letter, letter[:160])
    # A repair that REJECTS the audit's drop must keep the human concern.
    tmp2 = Path(tempfile.mkdtemp(prefix="paper_deliv_e2e_reject_"))
    os.environ["PAPER_STUB_CONCERN_AUDIT_DROP"] = "C1"
    os.environ["PAPER_STUB_CONCERN_REPAIR_REJECT"] = "C1"
    try:
        root2 = jr.setup_and_run(tmp2, "major")
    finally:
        os.environ.pop("PAPER_STUB_CONCERN_AUDIT_DROP", None)
        os.environ.pop("PAPER_STUB_CONCERN_REPAIR_REJECT", None)
    rep2 = json.loads((root2 / "runs" / "r1_concern_repair" / "concerns"
                       / "JF_concerns.json").read_text(encoding="utf-8"))
    ids2 = [c["id"] for c in rep2.get("concerns") or []]
    check("a rejected drop keeps the human concern", sorted(ids2) == ["C1", "C2"],
          str(ids2))


def test_reviewer_text_is_preserved():
    print("== reviewer text is quoted character-for-character ==")
    sb = sandbox()
    (sb / "feedback" / "text").mkdir()
    (sb / "feedback" / "text" / "editor.txt.txt").write_text(
        "Reviewer 1: The datas is wrong and teh claim is 2 strong.\n", encoding="utf-8")
    row = {"source": "editor.txt"}
    check("the verbatim (typo-preserving) wording is accepted",
          nb.response_comment_human_verbatim(
              None, sb, row, "The datas is wrong and teh claim is 2 strong."))
    check("a cleaned-up spelling is rejected",
          not nb.response_comment_human_verbatim(
              None, sb, row, "The data is wrong and the claim is too strong."))
    check("a punctuation 'fix' is rejected",
          not nb.response_comment_human_verbatim(
              None, sb, row, "The datas is wrong, and teh claim is 2 strong."))
    check("a capitalization 'fix' is rejected",
          not nb.response_comment_human_verbatim(
              None, sb, row, "the datas is wrong and teh claim is 2 strong."))
    (sb / "feedback" / "llm" / "files").mkdir(parents=True)
    (sb / "feedback" / "llm" / "files" / "review.md").write_text(
        "a model review\n", encoding="utf-8")
    check("an LLM-only concern is not forced into the human stream",
          nb.response_comment_human_verbatim(
              None, sb, {"source": "llm_review.md"}, "a model review") is True)
    sb2 = sandbox()
    (sb2 / "feedback" / "text").mkdir()
    (sb2 / "feedback" / "files" / "human_review_feedback__editor.txt").write_text(
        "The datas is wrong.", encoding="utf-8")
    (sb2 / "feedback" / "text" / "human_review_feedback__editor.txt.txt").write_text(
        "The datas is wrong.", encoding="utf-8")
    check("a flattened corpus label still resolves to the human text",
          nb.response_comment_human_verbatim(
              None, sb2, {"source": "human_review_feedback/editor.txt"},
              "The datas is wrong.") is True
          and nb.response_comment_human_verbatim(
              None, sb2, {"source": "human_review_feedback/editor.txt"},
              "The data is wrong.") is False)


def test_scoped_chain_is_enabled():
    print("== scoped revision chain ==")
    p08 = (WS / "paper_pipeline_parts" / "p08_selection_driver.py").read_text("utf-8")
    p09 = (WS / "paper_pipeline_parts" / "p09_setup.py").read_text("utf-8")
    check("the scoped revision audit is no longer skipped",
          "the general revision audit is not staged" not in p08
          and "journal_revision_audit_block(ctx)" in p08)
    check("setup no longer forces revision_audit off for a scoped mode",
          'forced.append("revision_audit=off' not in p09
          and 'ctx.cfg["revision_audit"] = "off"' not in p09)
    p02 = (WS / "paper_pipeline_parts" / "p02_journal_modes.py").read_text("utf-8")
    check("the scoped concern audit/repair are planned stages",
          '"concern_audit"' in p02 and '"concern_repair"' in p02)
    check("rewrite/integration are diversity candidates, not audited deliverables",
          "rewrite_audit" not in p08 and "integrate_audit" not in p08
          and 'if rec.get("kind") != "revise"' in p08)
    check("no judge audit/repair stage exists (the panel is the check)",
          "judge_audit" not in p08 and "judge_repair" not in p08)


if __name__ == "__main__":
    test_human_only_scoped_streams()
    test_concern_audit()
    test_concern_repair()
    test_response_audit_repair()
    test_scoped_chain_is_enabled()
    test_reviewer_text_is_preserved()
    test_e2e_drop_and_reject()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL DELIVERABLE-AUDIT CHECKS PASSED")

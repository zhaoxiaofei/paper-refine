#!/usr/bin/env python3
"""Regression tests for fix-bugs wave 1, batch B_p06 (p06_postchecks.py).

One hermetic block per confirmed candidate; each check fails on the pre-patch
tree and passes here.  Run: python3 .paper_test/test_fix_wave1_B_p06.py
"""
from __future__ import annotations
import importlib.util, json, os, sys, tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
_spec = importlib.util.spec_from_file_location("pp", WS / "paper_pipeline.py")
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)
FAILS, TMPDIRS = [], []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def test_coverage():
    print("\n== F03/F143: coverage gate refuses inability/filler bases ==")
    for v in ("clean -- basis: wasn't able to check the tables",
              "clean -- basis: was unable to check the tables",
              "clean -- basis: failed to check the tables"):
        check(f"F03 {v!r} is not clean", pp._coverage_disposition_ok(v) is False)
    check("F03 a named artifact basis is still accepted",
          pp._coverage_disposition_ok("clean -- basis: artifacts/M1_acronyms.md"))
    check("F143 a missing-capability basis is refused",
          pp._coverage_disposition_ok("clean -- basis: no PDF renderer") is False)
    check("F143 the documented `unable --` form stays accepted",
          pp._coverage_disposition_ok("unable -- no PDF renderer"))
    check("F143 the bare-clean detail route refuses it too",
          pp._coverage_row_disposition_ok(
              {"disposition": "clean", "detail": "Basis: no PDF renderer"}) is False)
    # R04: "no renderer was NEEDED" says the capability was not required (a
    # clean text-only result), not that it was unavailable.
    check("R04 a not-needed capability basis is accepted",
          pp._coverage_disposition_ok(
              "clean -- basis: no PDF renderer was needed; the checks are textual"))
    check("R04 a named artifact with a not-needed capability is accepted",
          pp._coverage_disposition_ok(
              "clean -- basis: artifacts/M1_acronyms.md; no PDF renderer was needed"))
    check("R04 an unavailable capability is still refused",
          pp._coverage_disposition_ok(
              "clean -- basis: no PDF renderer was available") is False)


def test_ledgers():
    print("\n== F34: a finding-id-keyed mapping keeps its id for row lists ==")
    led = {"F-001": [{"verdict": "confirmed", "rationale": "r", "evidence": "e"}]}
    check("F34 verdict map keeps the key",
          pp._ledger_verdict_map(led) == {"F-001": {"confirmed"}},
          repr(pp._ledger_verdict_map(led)))
    check("F34 row count keeps the key", pp._ledger_row_counts(led) == {"F-001": 1})
    check("F34 missing explanation keeps the key",
          pp._ledger_rows_without_explanation({"F-001": [{"verdict": "confirmed"}]})
          == {"F-001": ["rationale", "evidence"]})
    check("F34 missing re-verification keeps the key",
          pp._ledger_rows_without_reverification({"F-001": [{"status": "fixed"}]})
          == {"F-001"})
    check("F34 a plain row list still works",
          pp._ledger_verdict_map([{"id": "F-001", "verdict": "confirmed"}])
          == {"F-001": {"confirmed"}})


def test_discovery():
    print("\n== F35: a note's negation does not discard the decision cell ==")
    check("F35 a `no row changed` note does not hide a PORTED row",
          pp.discovery_ledger_missing("| X-001 | PORTED | no row changed |",
                                      ["X-001"]) == [])
    check("F35 a negated disposition is still not a reconciliation",
          pp.discovery_ledger_missing("No disposition is recorded for X-004",
                                      ["X-004"]) == ["X-004"])
    check("F35 `NOT PORTED` is still not a reconciliation",
          pp.discovery_ledger_missing("X-004 | NOT PORTED -- left unchanged",
                                      ["X-004"]) == ["X-004"])
    check("F35 a decisionless row is still missing",
          pp.discovery_ledger_missing("| X-004 | donor | ??? | no disposition |",
                                      ["X-004"]) == ["X-004"])


def test_d5():
    print("\n== F43: D5 reads fenced illustrative headings as illustrations ==")
    sb = scratch("f43_")
    r2 = sb / "guided_review" / "round2"
    r2.mkdir(parents=True)
    (r2 / "new_sweeps.md").write_text(
        "# D5\n\nNo new sweep proposals: nothing to propose.\n\n"
        "```\n## M37 Foo\n```\n", encoding="utf-8")
    errs, _ = pp.discovery_contract_problems(sb)
    check("F43 a fenced `## M37` example fails no correct no-proposal document",
          not any("not a sweeps.md-shaped proposal block" in e for e in errs),
          str(errs)[:160])
    (r2 / "new_sweeps.md").write_text(
        "# D5\n\nNo new sweep proposals: nothing to propose.\n\n## M37 Foo\n",
        encoding="utf-8")
    errs, _ = pp.discovery_contract_problems(sb)
    check("F43 a real malformed heading is still reported",
          any("not a sweeps.md-shaped proposal block" in e for e in errs))


def test_filler():
    print("\n== F45: filler-only disposition cells are not dispositions ==")
    for cell in ("-", "\u2014", "n/a", "none", "TBD"):
        check(f"F45 {cell!r} is reported", bool(pp.disposition_artifact_problems(
            [{"rule": "R1", "disposition": cell}])))
    check("F45 a short genuine reason is still accepted",
          pp.disposition_artifact_problems(
              [{"rule": "R1", "disposition": "OK \u2014 present"}]) == [])


def test_rule_id_alias():
    print("\n== F55/F70: the `rule id` alias is read wherever `rule` is ==")
    check("F55 a `rule id` FMT-CL1 OK closure is gated",
          any("quotes no journal override" in p
              for p in pp.disposition_artifact_problems(
                  [{"rule id": "FMT-CL1", "disposition":
                    "OK \u2014 the run carries the letter in the journal's styles"}])))
    check("F55 a quoted journal override still closes OK",
          pp.disposition_artifact_problems(
              [{"rule id": "FMT-CL1", "disposition":
                "OK \u2014 the journal's author guidelines require the manuscript "
                "template: 'format the cover letter in the manuscript template'"}]) == [])
    d = scratch("f70_")
    rd = d / "review"
    (rd / "artifacts").mkdir(parents=True)
    (rd / "artifacts" / "M20_formatting.md").write_text(
        "| Rule ID | Document | Disposition |\n|---|---|---|\n"
        "| FMT-01 | main.docx | OK \u2014 journal requires 12 pt (guidelines) |\n",
        encoding="utf-8")
    rel = "artifacts/M20_formatting.md"
    rep = pp.artifact_quality_report(rd, require_files=False,
                                     m20_seed_rows=[{"rule": "FMT-01"}])
    check("F70 a Rule ID table keeps its seeded row",
          not any("no longer in the table" in p for p in rep.get(rel, [])),
          str(rep)[:160])
    rep = pp.artifact_quality_report(
        rd, require_files=False,
        m20_seed_rows=[{"rule": "FMT-01"}, {"rule": "FMT-99"}])
    check("F70 a genuinely deleted seeded row is still reported",
          any("FMT-99" in p for p in rep.get(rel, [])))


def test_outline_m1b():
    print("\n== F145/F159: degenerate M1b table; OUTLINE disposition alias ==")
    check("F145 a degenerate `| |` line is not an M1b table",
          pp.m1b_audit_section_missing(
              "## M1\n\n| ACRONYM INVENTORY | x |\n|---|---|\n\n## M1b\n| |\n") is True)
    check("F145 a real M1b table still satisfies the section",
          pp.m1b_audit_section_missing(
              "## M1\n\n| ACRONYM INVENTORY | x |\n|---|---|\n\n## M1b\n"
              "| acronym | context | disposition |\n|---|---|---|\n"
              "| A | b | OK \u2014 checked in context |\n") is False)
    rows = [{"summary": "s", "first sentence": "f",
             "verdict": "OK \u2014 reviewed the same sentence"} for _ in range(20)]
    check("F159 a repeated verdict in the `verdict` column is detected",
          any("same verdict" in p for p in pp.outline_artifact_problems(rows)))


def test_pdf_stub():
    print("\n== F31: a signature-only PDF is not a render ==")
    d = scratch("f31_")
    stub = d / "stub.pdf"
    stub.write_bytes(b"%PDF-1.4\n%%EOF\n")
    body_problem = getattr(pp, "_render_output_body_problem", lambda _p: "")
    check("F31 the 15-byte stub is not a render body", body_problem(stub) != "",
          body_problem(stub))
    docx = d / "paper.docx"
    docx.write_bytes(b"PK\x03\x04fake")
    out = d / "out"
    out.mkdir()
    stub_sh = d / "stub.sh"
    stub_sh.write_text('#!/bin/sh\nprintf \'%%PDF-1.4\\n%%%%EOF\\n\' > "${1%.docx}.pdf"\n',
                       encoding="utf-8")
    stub_sh.chmod(0o755)
    res = pp.render_docx_visual(docx, out, ("word", str(stub_sh)),
                                timeout=30, page_images=True)
    check("F31 a stub-only render is a failed render",
          res.get("ok") is False and not (out / "paper.pdf").exists(), str(res)[:160])
    body_sh = d / "body.sh"
    body_sh.write_text('#!/bin/sh\nprintf \'%%PDF-1.4\\nbody\\n%%%%EOF\\n\' > "${1%.docx}.pdf"\n',
                       encoding="utf-8")
    body_sh.chmod(0o755)
    good = pp.render_docx_visual(docx, out, ("word", str(body_sh)),
                                 timeout=30, page_images=False)
    check("F31 a render with a body still succeeds", good.get("ok") is True,
          str(good)[:160])


def test_visual_containment():
    print("\n== F18: manifest render paths must stay under visual_template ==")
    d = scratch("f18_")
    sb = d / "sandbox"
    (sb / "visual_template" / "main").mkdir(parents=True)
    (sb / "work").mkdir(parents=True)
    (sb / "work" / "page-1.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    (sb / "visual_template" / "main" / "real.pdf").write_bytes(
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    (d / "outside.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 500 + b"\n%%EOF\n")
    art = sb / "art.md"
    art.write_text("visually inspected main.docx -- 1 page; compared against the template\n",
                   encoding="utf-8")
    ok = {"role": "main", "pdf": "real.pdf", "ok": True,
          "source": "main.docx", "pages": 1}

    def errs_for(doc):
        (sb / "visual_template" / "manifest.json").write_text(
            json.dumps({"renderer": "word", "documents": [doc]}), encoding="utf-8")
        errs, warns = [], []
        pp.check_visual_artifact(art, "vis", errs, warns, render_roots=[sb], sandbox=sb)
        return errs

    check("F18 the legitimate manifest render passes", errs_for(ok) == [],
          str(errs_for(ok))[:160])
    check("F18 `..` + `../outside.pdf` cannot satisfy the gate",
          any("not a real PDF" in e for e in
              errs_for(dict(ok, role="..", pdf="../outside.pdf"))))
    check("F18 an absolute render path cannot satisfy the gate",
          any("not a real PDF" in e for e in
              errs_for(dict(ok, pdf=str(d / "outside.pdf")))))


def main():
    for fn in (test_coverage, test_ledgers, test_discovery, test_d5, test_filler,
               test_rule_id_alias, test_outline_m1b, test_pdf_stub,
               test_visual_containment):
        fn()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL B_p06 FIX-WAVE-1 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        import shutil
        for _d in TMPDIRS:
            shutil.rmtree(_d, ignore_errors=True)
    sys.exit(rc)

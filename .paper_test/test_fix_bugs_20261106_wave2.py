#!/usr/bin/env python3
"""Regression checks for the 2026-11-06 fix-bugs waves 1-2 (62 verified findings).

Every check pins a candidate that was re-confirmed on this tree and repaired in
one of the waves (wave 2 completes F-016's package-import half). Hermetic: temp
dirs only, no network, no Word.
Run: python3 .paper_test/test_fix_bugs_20261106_wave2.py
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
if str(WS) not in sys.path:
    sys.path.insert(0, str(WS))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


import paper_pipeline as pp
import paper_docx_format as FMT


def comp(**kw):
    c = {"score": 1, "basis": "correctness",
         "resolved": [{"tier": "correctness", "severity": "major", "check": "M1",
                       "evidence": "a real defect with enough words in it"}],
         "introduced": [],
         "checks": {cid: "clean -- checked it" for cid in pp.JUDGE_COVERAGE_CHECKS}}
    c.update(kw)
    return c


# ---------------------------------------------------------------------------
# p07 judge/concern validators
# ---------------------------------------------------------------------------
def test_judge_validators() -> None:
    print("\n== judge coverage / basis validators ==")
    e, _w = pp.judge_coverage_problems(comp(), "c", strict=True)
    check("F-024 a clean check cannot carry a defect row", any("marks 'M1' clean" in x for x in e), e[:1])

    c = comp()
    c["checks"] = {cid: "findings -- M1 row" for cid in pp.JUDGE_COVERAGE_CHECKS}
    e, _w = pp.judge_coverage_problems(c, "c", strict=True)
    check("F-031 a prose mention of one row cannot satisfy every check",
          any("'M2'" in x and "no `resolved`" in x for x in e), e[:1])

    c = comp()
    c["checks"] = {cid: "cleanup done" for cid in pp.JUDGE_COVERAGE_CHECKS}
    e, _w = pp.judge_coverage_problems(c, "c", strict=True)
    check("F-052 'cleanup' is not the `clean` disposition",
          any("not a disposition" in x for x in e), e[:1])

    c = comp()
    c["checks"]["M01"] = "unable -- no access"
    e, _w = pp.judge_coverage_problems(c, "c", strict=True)
    check("F-051 M1 and M01 under one normalized check are a conflict",
          any("normalized check 'M1'" in x for x in e), e[:1])

    c = comp()
    c["checks"] = {cid: "unable -- not examined" for cid in pp.JUDGE_COVERAGE_CHECKS}
    e, w = pp.judge_coverage_problems(c, "c", strict=True)
    check("F-034 an all-abstain comparison is flagged for exclusion, not counted",
          not e and any("abstention" in x for x in w)
          and pp.judge_comparison_abstained(c), (e, w))

    e, _w = pp.judge_basis_problems(comp(basis="writing"), "c", strict=True)
    check("F-058 the wrong deciding tier is an error under the strict contract",
          any("tier that decides" in x for x in e), e[:1])

    c = comp(score=4, resolved=[{"tier": "correctness", "severity": "fatal",
                                 "check": "M19x",
                                 "evidence": "a caption far longer than the venue cap"}])
    e, _w = pp.judge_basis_problems(c, "c", strict=True)
    check("F-026 a near-miss length id still gets the length guard",
          any("length/caption" in x for x in e), e[:1])

    c = comp()
    c["resolved"] = 7
    try:
        e, _w = pp.judge_coverage_problems(c, "c", strict=True)
        crashed = False
    except TypeError:
        crashed = True
    check("F-083 a scalar ledger cannot crash the coverage validator", not crashed)

    rows = [{"tier": "formatting", "severity": "minor", "check": "M019",
             "evidence": f"a distinct caption length row number {i} over the cap"}
            for i in range(3)]
    c = comp(score=1, basis="formatting", resolved=rows, introduced=[])
    e, _w = pp.judge_basis_problems(c, "c", strict=True)
    check("F-026 the padded M019 spelling is the same length-check id",
          pp._is_length_guard_check("M019")
          and pp.tier_net_scores(pp.ledger_items(c))["formatting"] == 1
          and not e, (e[:1], pp.tier_net_scores(pp.ledger_items(c))))
    c = comp(score=2, basis="formatting", resolved=rows, introduced=[])
    e, _w = pp.judge_basis_problems(c, "c", strict=True)
    check("F-026 three M019 length rows are capped at +1, so a +2 sheet is rejected",
          any("contradicts its own ledger" in x for x in e), e[:1])


def test_concern_helpers() -> None:
    print("\n== concern coverage / short quote ==")
    bad = pp.concern_coverage_problems(
        {"coverage": [{"check": "scope", "disposition": "outside is a gap"}]}, False)
    check("F-036 a bare 'gap' is not a named excluded class", bool(bad), bad)
    good = pp.concern_coverage_problems(
        {"coverage": [{"check": "scope",
                       "disposition": "gap: figure quality and house style"}]}, False)
    check("F-036 a named class list satisfies the gate", good == [], good)
    for payload in ("gap:", "gap: none", "gap: n/a", "gap: nothing", "gap: -"):
        bad = pp.concern_coverage_problems(
            {"coverage": [{"check": "scope", "disposition": payload}]}, False)
        check(f"F-036 {payload!r} is not a named excluded class", bool(bad), bad)
    good = pp.concern_coverage_problems(
        {"coverage": [{"check": "scope", "disposition": "gap: style"}]}, False)
    check("F-036 a short named class list still satisfies the gate", good == [], good)
    check("F-081 a complete short source unit is accepted",
          pp._complete_source_unit("Retain.", "Please review.\nRetain.\nThank you.")
          and not pp._complete_source_unit("Retain.", "Please retain. Thank you."))


def test_deletion_audit() -> None:
    print("\n== deletion audit ==")
    d = scratch("fb2_del_")
    base, rev = d / "b", d / "r"
    base.mkdir()
    rev.mkdir()
    para = "Treatment with the compound used a dose of 50 mM in every assay block."
    (base / "a.md").write_text("# Methods\n\n" + para + "\n")
    (rev / "a.md").write_text("# Methods\n\n" + para.replace("mM", "MM") + "\n")
    rows = pp.deletion_audit_rows(base, rev)
    check("F-059 a case-only unit change is a deletion-audit row", len(rows) == 1, rows)

    shared = "The control group received the vehicle only and was followed for twelve weeks."
    base2, rev2 = d / "b2", d / "r2"
    base2.mkdir()
    rev2.mkdir()
    (base2 / "main.md").write_text("# Results\n\n" + shared + "\n")
    (base2 / "supp.md").write_text("# Supplement\n\n" + shared + "\n")
    (rev2 / "main.md").write_text("# Results\n\n" + shared + "\n")
    (rev2 / "supp.md").write_text("# Supplement\n\nA different surviving paragraph.\n")
    rows = pp.deletion_audit_rows(base2, rev2)
    check("F-061 a copy in another document does not prove the local one survived",
          [r["document"] for r in rows] == ["supp.md"], rows)


def test_dedup_key() -> None:
    print("\n== structured-location dedup ==")
    a = pp.dedup_location_of("paper.md lines 42: the value is wrong in this cell here")
    b = pp.dedup_location_of("supp.md lines 42: the value is wrong in this cell here")
    c = pp.dedup_location_of("paper.md lines 42: the value is wrong in this cell here")
    check("F-009 the same line/excerpt in two documents does not merge",
          not pp.dedup_rows_match("M1", a, "M1", b, "major", "major"))
    check("F-009 a severity disagreement does not merge",
          not pp.dedup_rows_match("M1", a, "M1", c, "major", "minor"))
    check("F-009 the same document, line, severity and excerpt still merges",
          pp.dedup_rows_match("M1", a, "M1", c, "major", "major"))


# ---------------------------------------------------------------------------
# citation / number extractors
# ---------------------------------------------------------------------------
def _run(script, work, out):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), "--work", str(work),
                        "--out", str(out)], capture_output=True, text=True)
    return r


def test_citations() -> None:
    print("\n== M2 citation extractor ==")
    d = scratch("fb2_cite_")
    corpus = d / "work" / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "paper.tex.txt").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\nocite{*}\nSee \\cite{missing}.\n"
        "\\begin{thebibliography}{9}\n\\bibitem{known} Known.\n"
        "\\bibitem{known} Duplicate known.\n\\end{thebibliography}\n\\end{document}\n")
    (corpus / "supp.tex.txt").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{thebibliography}{9}\n\\bibitem{known} Same key, other root.\n"
        "\\end{thebibliography}\n\\end{document}\n")
    r = _run("extract_citations.py", d / "work", d / "out")
    data = json.loads((d / "out" / "artifacts" / "M2_citations.json").read_text())
    check("F-025 a nocite wildcard does not hide an explicit missing key",
          "missing" in data["tex_orphan_keys"], data["tex_orphan_keys"])
    check("F-048 an uncited key in one root is reported for that root",
          "known" in data["tex_uncited_keys"]
          and "known" in (data.get("tex_uncited_by_context") or {}).get("supp.tex.txt", []),
          data.get("tex_uncited_by_context"))
    check("F-029 a duplicate LaTeX key in one root is reported",
          data.get("duplicate_tex_keys", {}).get("paper.tex.txt", {}).get("known") == 2,
          data.get("duplicate_tex_keys"))


def test_numbers() -> None:
    print("\n== M4 number extractor ==")
    d = scratch("fb2_num_")
    corpus = d / "work" / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "paper.md.txt").write_text(
        "# Results\n"
        "p = 0.05 for the first test.\n"
        "p < 0.05 for the second test.\n"
        "The model reached AUC = 12.3 in training.\n"
        "The model reached AUC = 9% in testing.\n"
        "The model reached AUC = 0.91e0 on holdout.\n")
    _run("extract_numbers.py", d / "work", d / "out")
    data = json.loads((d / "out" / "artifacts" / "M4_numbers.json").read_text())
    vals = {(m["label"], m["value"]) for m in data["metrics"]}
    check("F-030 equality and inequality p-values keep distinct keys",
          ("p-value", "0.05") in vals and ("p-value", "<0.05") in vals, sorted(vals))
    check("F-049 explicit AUC literals are not dropped or truncated",
          ("AUC", "12.3") in vals and ("AUC", "9%") in vals and ("AUC", "0.91") in vals,
          sorted(vals))


# ---------------------------------------------------------------------------
# pairwise workbook collector
# ---------------------------------------------------------------------------
def test_pairwise() -> None:
    print("\n== pairwise score collector ==")
    import pairwise_scores as ps
    d = scratch("fb2_pair_")
    fields = ["round", "member", "credited", "direction", "opponent_id",
              "source_judge_run", "source_judge_index", "sheet_target", "reason"]

    def write(name, rows, extra_header=""):
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields + ([extra_header] if extra_header else []))
            w.writeheader()
            w.writerows(rows)
        return p

    base = {"round": 1, "member": "a", "opponent_id": "b", "source_judge_run": "j1",
            "source_judge_index": 1, "sheet_target": "a"}
    p = write("r1/s.csv", [dict(base, credited="4", direction="own"),
                           dict(base, credited="-4", direction="own")])
    cubes, notes = ps.collect([p], how="mean", pool_rounds=False, own_only=True)
    check("F-071 one judge's two contrary scores are not two votes",
          cubes["r1"]["1"][("a", "b")].values == [4.0]
          and notes["conflicting_scores"] == 1,
          (cubes["r1"]["1"][("a", "b")].values, notes["conflicting_scores"]))
    p = write("r2/s.csv", [dict(base, credited="99", direction="own")])
    cubes, notes = ps.collect([p], how="mean", pool_rounds=False, own_only=True)
    check("F-076 a score outside -4..+4 is rejected, not aggregated",
          notes["skipped_out_of_range"] == 1 and not cubes["r2"]["1"])
    p = write("r3/s.csv", [dict(base, credited="2")])
    cubes, notes = ps.collect([p], how="mean", pool_rounds=False, own_only=True)
    check("F-085 a row with no direction is not an own judgment",
          notes["skipped_direction"] == 1 and not cubes["r3"]["1"])
    p = d / "r4" / "torn.csv"
    p.parent.mkdir(parents=True)
    p.write_text(",".join(fields + ["extra"]) + "\n"
                 "1,a,2,own,b,j1,1,a,\"a complete reason\"\n"
                 "1,a,3,own,b,j1,1,a,\"unterminated")
    try:
        ps.collect([p], how="mean", pool_rounds=False, own_only=True)
        raised = False
    except SystemExit:
        raised = True
    check("F-084 an unterminated CSV record is a read error, not a score", raised)
    check("F-101 the workbook no longer equates a zero aggregate with agreement",
          "Zero is only the aggregate" in (WS / "pairwise_scores.py").read_text())


# ---------------------------------------------------------------------------
# defect audit + revision ledger
# ---------------------------------------------------------------------------
def test_defect_audit() -> None:
    print("\n== defect audit + revision ledger ==")
    valid = {"d1", "d2"}
    partial = {"verdicts": [{"defect_id": "d1", "label": "TP", "reason": "checked"}]}
    norm = pp._normalize_defect_audit(partial, valid)
    cov = pp._defect_audit_coverage(partial, valid, norm)
    check("F-028 an omitted defect id makes the audit incomplete",
          cov["missing"] == ["d2"], cov)
    dup = {"verdicts": [{"defect_id": "d1", "label": "TP", "reason": "a"},
                        {"defect_id": "d1", "label": "FP", "reason": "b"},
                        {"defect_id": "d2", "label": "TP", "reason": "c"}]}
    check("F-028 a contradictory duplicate is a conflict",
          pp._defect_audit_coverage(dup, valid,
                                    pp._normalize_defect_audit(dup, valid))["duplicate_ids"]
          == ["d1"])

    d = scratch("fb2_ledger_")
    pkg = d / "revised"
    pkg.mkdir()

    def errs(payload):
        (pkg / "revision_report.json").write_text(json.dumps(payload))
        return pp.revision_ledger_problems(pkg, ["F-001"], 1)[0]

    check("F-080 a bare final status is not a re-verification record",
          any("re-verification" in e for e in errs(
              [{"id": "F-001", "final_status": "fixed", "rationale": "done"}])))
    check("F-080 verdict + final status passes",
          errs([{"id": "F-001", "verdict": "confirmed",
                 "final_status": "fixed", "rationale": "done"}]) == [])
    check("F-093 two rows for one id are rejected",
          any("more than one authoritative row" in e for e in errs(
              [{"id": "F-001", "verdict": "confirmed", "final_status": "fixed"},
               {"id": "F-001", "verdict": "confirmed", "final_status": "fixed"}])))


# ---------------------------------------------------------------------------
# spreadsheet conversion
# ---------------------------------------------------------------------------
def _xlsx(path, sheets, rels, sheet_xml):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook><sheets>"
                   + "".join('<sheet name="%s" r:id="%s"/>' % (n, r) for n, r in sheets)
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", "<Relationships>"
                   + "".join('<Relationship Id="%s" Type="worksheet" Target="%s"/>' % (r, t)
                             for r, t in rels) + "</Relationships>")
        z.writestr("xl/sharedStrings.xml", "<sst><si><t>alpha</t></si></sst>")
        for part, text in sheet_xml.items():
            z.writestr(part, text)
    return path


def test_xlsx() -> None:
    print("\n== spreadsheet conversion ==")
    import convert_corpus as cc
    d = scratch("fb2_xlsx_")
    p = _xlsx(d / "t.xlsx", [("Ctrl", "rId1")], [("rId1", "worksheets/sheet1.xml")],
              {"xl/worksheets/sheet1.xml":
               '<worksheet><sheetData>'
               '<row r="1"><c r="A1" t="s"><v>9999</v></c><c r="B1"><v>7</v></c></row>'
               '<row r="2"><c r="A2"><f>2+3</f><v>5</v></c></row>'
               '<row r="3"><c r="A3" t="inlineStr"><is><t>x | y\nsecond</t></is></c></row>'
               '</sheetData></worksheet>'})
    text, notes = cc.xlsx_to_text(str(p))
    check("F-082 a dangling shared-string index is a visible marker",
          "[dangling shared-string index: 9999]" in text
          and any("dangling" in n or "shared-string" in n for n in notes), notes)
    check("F-086 a cached formula keeps the value and records its origin",
          "### corpus-marker: cached-formula Ctrl!A2 =2+3 -> 5" in text, text)
    check("F-075 a pipe/newline in a cell cannot fabricate columns or rows",
          "x \\| y\\nsecond" in text, text)

    p = _xlsx(d / "malformed.xlsx", [("S", "rId1")], [("rId1", "worksheets/sheet1.xml")],
              {"xl/worksheets/sheet1.xml":
               '<worksheet><sheetData><row r="1"><c r="A1"><v>1</v></c></row>'
               '<row r="2"><c r="A2"><v>2</v></c>'})
    text, notes = cc.xlsx_to_text(str(p))
    check("F-072 a malformed worksheet part is marked partial",
          any("malformed worksheet XML" in n for n in notes), notes)

    p = _xlsx(d / "missingrel.xlsx", [("Control", "rId2"), ("Treatment", "rId1")],
              [("rId1", "worksheets/sheet1.xml")],
              {"xl/worksheets/sheet1.xml":
               '<worksheet><sheetData><row r="1"><c r="A1"><v>11</v></c></row></sheetData></worksheet>',
               "xl/worksheets/sheet2.xml":
               '<worksheet><sheetData><row r="1"><c r="A1"><v>22</v></c></row></sheetData></worksheet>'})
    text, notes = cc.xlsx_to_text(str(p))
    check("F-073 a missing relationship does not borrow an unrelated sheet",
          "### corpus-marker: sheet: Control" not in text
          and any("Control" in n and "relationship" in n for n in notes), (text, notes))


def test_pdf_and_cell() -> None:
    print("\n== PDF cache + numeric cells ==")
    import paper_docx_format as fmt
    d = scratch("fb2_pdf_")
    good = d / "good.pdf"
    good.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n")
    fake = d / "fake.pdf"
    fake.write_bytes(b"not a pdf\n%PDF-1.4\n%%%%EOF\n")
    check("F-074 a header not at offset 0 is not a PDF",
          pp.pdf_signature_problem(fake) != "")
    prev = {("l", "p.docx"): {"ok": True, "sha256": "abc", "kind": "docx",
                              "out_sha256": hashlib.sha256(good.read_bytes()).hexdigest()}}
    check("F-074 a cached render is reused only with its recorded output digest",
          pp._reuse_pdf_record(prev, "l", "p.docx", "abc", good, "docx") is not None)
    prev[("l", "p.docx")]["out_sha256"] = "0" * 64
    check("F-074 changed output bytes are not reused",
          pp._reuse_pdf_record(prev, "l", "p.docx", "abc", good, "docx") is None)

    check("F-005 a locale-ambiguous comma value is not silently reinterpreted",
          fmt._cell_number("0,5") is None and fmt._cell_number("1,234") == 1234)
    check("F-005 a percent/currency cell and a non-finite value are not plain numbers",
          fmt._cell_number("5%") is None and fmt._cell_number("$50") is None
          and fmt._cell_number("inf") is None)


# ---------------------------------------------------------------------------
# pipeline internals: replay, diagnostics, repairs, view digest, coverage
# ---------------------------------------------------------------------------
def test_replay_and_repairs() -> None:
    print("\n== replay rule, panel roster, repair guards ==")
    src = (WS / "paper_pipeline_parts/p12_conflicts_decide.py").read_text()
    check("F-027 decision replay passes the recorded anti-regression rule",
          "rule=_recorded_rule" in src and "anti_regression_rule" in src)

    pre = scratch("fb2_repair_pre_")
    cur = scratch("fb2_repair_cur_")
    plan = [{"id": "RP-1", "file": "paper.md", "location": "Results",
             "wrong": "n = 10", "correct": "n = 20", "basis": "table 1",
             "edit": "replace", "evidence": "table row 1"}]
    # The repair quotes an unrelated edit in the same file and leaves the file
    # untouched: both the no-op and the plan-binding guards must fire.
    (pre / "paper.md").write_text("The endpoint was 7.\n")
    (cur / "paper.md").write_text("The endpoint was 7.\n")
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-1", "verdict": "confirmed", "reason": "ok",
         "before": "The endpoint was 7.", "after": "The endpoint was 9."}]}))
    bad = pp._revised_repair_violations(pre, cur, plan, {"RP-1"}, with_reasons=True)
    check("F-069 quotes must contain the plan's wrong/correct values",
          any("plan's `wrong`" in v for v in bad.values()), bad)
    plan2 = [{"id": "RP-1", "file": "paper.md", "location": "Results",
              "wrong": "The endpoint was 7.", "correct": "The endpoint was 9.",
              "basis": "table 1", "edit": "replace", "evidence": "row"}]
    bad = pp._revised_repair_violations(pre, cur, plan2, {"RP-1"}, with_reasons=True)
    check("F-070 an unchanged file cannot satisfy a confirmed replacement",
          any("no-op" in v for v in bad.values()), bad)

    # A pure insertion is a no-op too when its `after` is absent.
    plan3 = [{"id": "RP-1", "file": "paper.md", "location": "Results",
              "wrong": "", "correct": "A new sentence.", "basis": "b",
              "edit": "insert", "evidence": "e"}]
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-1", "verdict": "confirmed", "reason": "ok",
         "before": "", "after": "A new sentence."}]}))
    bad = pp._revised_repair_violations(pre, cur, plan3, {"RP-1"}, with_reasons=True)
    check("F-070 a confirmed insertion absent from the file is a no-op",
          any("insertion is a no-op" in v for v in bad.values()), bad)


def test_python_anonymization_offsets() -> None:
    print("\n== Python import rewrite is byte-correct ==")
    d = scratch("fb2_py_")
    (d / "m.py").write_text("label = '\u03b2'; import helper\n")
    (d / "helper.py").write_text("x = 1\n")
    fm = {"m.py": "f0001.py", "helper.py": "f0002.py"}
    data, _notes = pp._transform_view_file("m.py", d / "m.py", fm)
    text = (data or b"").decode()
    check("F-016 a non-ASCII character before an import does not shift the edit span",
          "import f0002 as helper" in text and "iimport" not in text, text)


def test_python_package_imports() -> None:
    print("\n== Python package imports survive the anonymous flattening ==")
    d = scratch("fb2_pypkg_")
    src = d / "src"
    (src / "pkg" / "nested").mkdir(parents=True)
    (src / "main.py").write_text(
        "import pkg.sub\nfrom pkg import sub as alias\n"
        "from pkg.nested.mod import answer\n"
        "print(pkg.sub.value(), alias.value(), answer, pkg.VALUE)\n"
        "from pkg import *\n"
        "print(VALUE)\n")
    (src / "pkg" / "__init__.py").write_text("from . import sub\nVALUE = 1\n")
    (src / "pkg" / "sub.py").write_text("def value():\n    return 42\n")
    (src / "pkg" / "nested" / "__init__.py").write_text(
        "from .. import VALUE\n")
    (src / "pkg" / "nested" / "mod.py").write_text(
        "from ..sub import value\nanswer = value()\n")
    fm = {"main.py": "f0001.py", "pkg/__init__.py": "d01/f0002.py",
          "pkg/sub.py": "d01/f0003.py",
          "pkg/nested/__init__.py": "d02/f0004.py",
          "pkg/nested/mod.py": "d02/f0005.py"}
    for rel, target in fm.items():
        data, _notes = pp._transform_view_file(rel, src / rel, fm)
        out = d / "view" / target
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data or b"")
    r = subprocess.run([sys.executable, "f0001.py"], cwd=d / "view",
                       capture_output=True, text=True)
    check("F-016 a renamed package graph still imports and runs",
          r.returncode == 0 and r.stdout.split() == ["42", "42", "42", "1", "1"],
          f"rc={r.returncode} out={r.stdout!r} err={r.stderr[-200:]!r}")


def test_python_sibling_imports() -> None:
    print("\n== a script's sibling module survives the anonymous layout ==")
    d = scratch("fb2_pysib_")
    src = d / "src"
    src.mkdir()
    (src / "main.py").write_text("import helper\nfrom helper import x\nprint(helper.x, x)\n")
    (src / "helper.py").write_text("x = 7\n")
    fm = {"src/main.py": "d01/f0001.py", "src/helper.py": "d01/f0002.py"}
    for rel, target in fm.items():
        data, _notes = pp._transform_view_file(rel, d / rel, fm)
        out = d / "view" / target
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data or b"")
    main_text = (d / "view" / "d01" / "f0001.py").read_text(encoding="utf-8")
    r = subprocess.run([sys.executable, "d01/f0001.py"], cwd=d / "view",
                       capture_output=True, text=True)
    check("F-016 a renamed script keeps its sibling-module imports",
          "import helper\n" not in main_text
          and r.returncode == 0 and r.stdout.split() == ["7", "7"],
          f"main={main_text!r} rc={r.returncode} out={r.stdout!r} err={r.stderr[-200:]!r}")


def test_numeric_aggregate_conflict() -> None:
    print("\n== M30 aggregate proof rejects a conflicting estimator ==")
    tables = [("t.tsv", "age,sex\n2,M\n3,M\n4,F\n")]
    hit = {"kind": "sum", "column": "age", "file": "t.tsv"}
    for sentence in ("The mean age was 9 years", "The mean total age was 9 years",
                     "The average total age was 9 years"):
        rows = [{"document": "main.txt", "number": "9", "unit": "years",
                 "sentence": sentence, "source": "", "document_paragraph": 3,
                 "kind": "abstract"}]
        filled = FMT.reconcile_number_rows(rows, tables)["filled"]
        check(f"F-003 {sentence!r} is not proved by the column sum",
              filled == 0 and not rows[0].get("source")
              and not FMT._number_proof_context_ok(rows[0], hit),
              (filled, rows[0].get("source")))
    rows = [{"document": "main.txt", "number": "9", "unit": "years",
             "sentence": "The total age was 9 years", "source": "",
             "document_paragraph": 3, "kind": "abstract"}]
    filled = FMT.reconcile_number_rows(rows, tables)["filled"]
    check("F-003 the matching aggregate still proves the sentence",
          filled == 1 and bool(rows[0].get("source")), rows[0].get("source"))


def test_ledger_dropped_by_audit() -> None:
    print("\n== a dropped finding carries its R1 verdict and final status ==")
    docs = {
        "ledger": WS / "paper-skills" / "paper-revise" / "references" / "ledger.md",
        "edit rules": WS / "paper-skills" / "paper-revise" / "references"
        / "edit_rules.md",
        "adress prompt": WS / "paper-skills" / "prompts" / "adress_issues.prompt.md",
    }
    for label, path in docs.items():
        text = " ".join(path.read_text(encoding="utf-8").split())
        check(f"F-128/F-080 the {label} documents the dropped-by-audit verdict",
              "dropped-by-audit" in text, text[:120])
    d = scratch("fb2_ledger_drop_")
    row = {"id": "F-001", "verdict": "dropped-by-audit",
           "final_status": "discarded",
           "rationale": "auditor dropped: the cited sentence is absent from base/"}
    (d / "revision_report.json").write_text(json.dumps([row]), encoding="utf-8")
    errs, _w = pp.revision_ledger_problems(d, ["F-001"], 1)
    check("F-080 a dropped row with the verdict and final status passes",
          errs == [], errs)
    (d / "revision_report.json").write_text(
        json.dumps([{k: v for k, v in row.items() if k != "verdict"}]),
        encoding="utf-8")
    errs, _w = pp.revision_ledger_problems(d, ["F-001"], 1)
    check("F-080 the same row without the R1 verdict is still rejected",
          any("re-verification" in e for e in errs), errs)


def test_view_digest() -> None:
    print("\n== judge-view digest binds paths ==")
    d = scratch("fb2_view_")
    v = d / "v"
    v.mkdir()
    (v / "a.md").write_text("AAA")
    (v / "b.md").write_text("BBB")
    dig1 = pp.judge_view_digest(v)
    (v / "a.md").write_text("BBB")
    (v / "b.md").write_text("AAA")
    dig2 = pp.judge_view_digest(v)
    check("F-015 swapping the same bytes between anonymous names changes the digest",
          dig1 != dig2, (dig1, dig2))


def test_table_coverage() -> None:
    print("\n== data-table inventory coverage ==")
    d = scratch("fb2_tables_")
    for i in range(41):
        (d / f"f{i:02d}.csv").write_text("a,b\n1,2\n")
    cov = {}
    tables = pp.data_table_texts([(d, "", ())], coverage=cov)
    check("F-006 the 40-file inventory cap reports the omitted producer path",
          len(tables) == 40 and cov.get("truncated")
          and cov.get("omitted") == ["f40.csv"], cov)


def test_lookup_budget() -> None:
    print("\n== lookup budget ==")
    targets = ([{"source": "reference", "kind": "doi", "query": "10.1/x"}] * 40
               + [{"source": "reference", "kind": "doi", "query": "10.1/y"}])
    picked = pp._select_lookup_targets(targets, 10)
    check("F-054 repeated occurrences of one DOI do not crowd out a distinct DOI",
          {t["query"] for t in picked} == {"10.1/x", "10.1/y"}, len(picked))


def test_dsh_completion() -> None:
    print("\n== dsh completion event ==")
    import paper_qwen_agent as qn
    d = scratch("fb2_dsh_")
    server = d / "silent.py"
    server.write_text("import sys\nprint('{\"type\": \"event\"}', flush=True)\n")
    rc, failed = qn.run_dsh_streaming([sys.executable, str(server)], {})
    check("F-087 exit 0 without a turn_end event is a failed turn",
          rc == 0 and failed is True, (rc, failed))


def main() -> int:
    test_judge_validators()
    test_concern_helpers()
    test_deletion_audit()
    test_dedup_key()
    test_citations()
    test_numbers()
    test_pairwise()
    test_defect_audit()
    test_xlsx()
    test_pdf_and_cell()
    test_replay_and_repairs()
    test_python_anonymization_offsets()
    test_python_package_imports()
    test_python_sibling_imports()
    test_numeric_aggregate_conflict()
    test_ledger_dropped_by_audit()
    test_view_digest()
    test_table_coverage()
    test_lookup_budget()
    test_dsh_completion()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): " + ", ".join(FAILS))
        return 1
    print("ALL 2026-11-06 WAVE-1/2 FIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

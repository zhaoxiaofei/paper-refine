#!/usr/bin/env python3
"""Regression checks for the 2026-11-05 fix-bugs wave 1 (PR151-* candidates).

Run:  python3 .paper_test/test_fix_bugs_20261105_wave1.py

Each check pins a candidate this wave re-validated on the current tree and then
repaired. The test is hermetic: every fixture lives under tempfile.mkdtemp().
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1105wave1_pp", "paper_pipeline.py")
cc = load("fb1105wave1_cc", "paper-skills/paper-review/scripts/convert_corpus.py")
pw = load("fb1105wave1_pw", "pairwise_scores.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# PR151-015 / PR151-040 / PR151-041 / PR151-043 / PR151-046 / PR151-047
# ---------------------------------------------------------------------------
def test_contract_helpers() -> None:
    print("\n== contract helpers: table cells, cold-start counts, judge coverage ==")
    check("PR151-015 md_table_cell preserves 0", pp.md_table_cell(0) == "0")
    check("PR151-015 md_table_cell preserves False", pp.md_table_cell(False) == "False")
    check("PR151-015 md_table_cell keeps None empty", pp.md_table_cell(None) == "")

    sb = scratch("wave1_cold_")
    p = sb / pp.COLD_START_FINDINGS_REL
    write(p, json.dumps({"checked": [{"area": "abstract", "examined": 0,
                                      "findings": 17}], "findings": []}))
    errs, _warns, _f = pp._cold_start_contract_problems(sb)
    check("PR151-040 a row cannot report 17 findings from 0 candidates",
          any("from 0 examined" in e for e in errs), str(errs)[:200])

    write(p, json.dumps({"checked": [{"area": "a", "examined": 1.5,
                                      "findings": True}], "findings": []}))
    errs, _warns, _f = pp._cold_start_contract_problems(sb)
    check("PR151-046 fractional/boolean counts are rejected",
          any("non-negative integer" in e for e in errs), str(errs)[:240])

    write(p, json.dumps({"checked": [{"area": "a", "examined": 1e309,
                                      "findings": 0}], "findings": []}))
    try:
        errs, _warns, _f = pp._cold_start_contract_problems(sb)
        overflow = False
    except OverflowError:
        overflow = True
        errs = []
    check("PR151-046 an infinite count does not crash the postcheck",
          not overflow and any("non-negative integer" in e for e in errs), str(errs)[:200])

    write(p, json.dumps({"checked": [{"area": "a", "examined": 2, "findings": 1}],
                         "findings": [{"id": "X-901", "location": "l", "evidence": "e",
                                       "explanation": "x", "check": "c", "status": "resolvable",
                                       "severity": "Major", "category": 2.75}]}))
    errs, _warns, _f = pp._cold_start_contract_problems(sb)
    check("PR151-046 a fractional category is rejected",
          any("integer 0-5" in e for e in errs), str(errs)[:200])

    comp = {"resolved": [], "introduced": [],
            "checks": {c: "clean" for c in pp.JUDGE_COVERAGE_CHECKS}}
    errs, _w = pp.judge_coverage_problems(comp, "sheet", True)
    check("PR151-041 a bare clean closure is rejected",
          any("states no basis" in e for e in errs), str(errs)[:200])
    comp["checks"] = {c: "clean -- examined, nothing found"
                      for c in pp.JUDGE_COVERAGE_CHECKS}
    errs, _w = pp.judge_coverage_problems(comp, "sheet", True)
    check("PR151-041 a clean closure with a basis passes", not errs, str(errs)[:200])
    comp["checks"]["M1"] = "findings -- examined"
    errs, _w = pp.judge_coverage_problems(comp, "sheet", True)
    check("PR151-043 findings needs a resolved/introduced row",
          any("both `resolved` and `introduced` are empty" in e for e in errs),
          str(errs)[:200])
    comp["resolved"] = [{"check": "M1", "tier": "consistency", "severity": "minor",
                         "evidence": "abstract: term is spelled two ways"}]
    errs, _w = pp.judge_coverage_problems(comp, "sheet", True)
    check("PR151-043 a findings row binds its own check", not errs, str(errs)[:200])
    comp["checks"]["M2"] = "findings -- examined"
    errs, _w = pp.judge_coverage_problems(comp, "sheet", True)
    check("PR151-043 another check's findings row does not bind this one",
          any("M2" in e and "no `resolved`/`introduced` row" in e for e in errs),
          str(errs)[:240])
    comp["checks"] = {c: "clean --" for c in pp.JUDGE_COVERAGE_CHECKS}
    errs, _w = pp.judge_coverage_problems(comp, "sheet", True)
    check("PR151-041 a clean closure with no basis text is rejected",
          any("states no basis" in e for e in errs), str(errs)[:200])
    comp["checks"] = {c: "clean x" for c in pp.JUDGE_COVERAGE_CHECKS}
    errs, _w = pp.judge_coverage_problems(comp, "sheet", True)
    check("PR151-041 a one-token clean closure is rejected",
          any("states no basis" in e for e in errs), str(errs)[:200])

    sentence = "No disposition is recorded for X-004\n"
    check("PR151-047 a bare 'no disposition' sentence is not reconciliation",
          pp.discovery_ledger_missing(sentence, ["X-004"]) == ["X-004"])
    decisionless = "| X-004 | donor | ??? | no disposition |\n"
    check("PR151-047 a decisionless table row is not reconciliation",
          pp.discovery_ledger_missing(decisionless, ["X-004"]) == ["X-004"],
          pp.discovery_ledger_missing(decisionless, ["X-004"]))
    table = "| X-004 | donor | KEPT-BASE | no donor fix |\n"
    check("PR151-047 an explicit ledger row reconciles the id",
          pp.discovery_ledger_missing(table, ["X-004"]) == [])


# ---------------------------------------------------------------------------
# PR151-025 -- a human label cannot bind the model stream through a weak alias
# ---------------------------------------------------------------------------
def test_feedback_binding() -> None:
    print("\n== feedback: the label's own stream binds the quote ==")
    sb = scratch("wave1_feedback_")
    for stream, flat in (("files", "human__report.txt"),
                         ("llm/files", "llm__report.txt")):
        (sb / "feedback" / stream).mkdir(parents=True)
    write(sb / "feedback/files/human__report.txt", "human bytes")
    write(sb / "feedback/text/human__report.txt.txt", "The human reviewer asks for units.")
    write(sb / "feedback/llm/files/llm__report.txt", "model bytes")
    write(sb / "feedback/llm/text/llm__report.txt.txt", "The model asks for units.")
    write(sb / "feedback/CONCERN_SEED.json", json.dumps({
        "files": ["human/report.txt"], "llm_files": ["llm/report.txt"],
        "staged": {"human/report.txt": "human__report.txt",
                   "llm/report.txt": "llm__report.txt"}}))
    write(sb / "concerns/JF_concerns.json", json.dumps({"concerns": [{
        "id": "C1", "source": "human/report.txt", "author": "Editor",
        "quote": "The model asks for units.",
        "summary": "units", "action": "text", "disposition": "to-fix"}]}))
    errs, warns = [], []
    pp.journal_ledger_problems(None, sb, errs, warns)
    check("PR151-025 a human label does not validate a model-stream quote",
          any("not verbatim" in e for e in errs), str(errs)[:240])
    # A bare basename present in BOTH streams is ambiguous, not a licence to
    # check the quote against both.
    write(sb / "concerns/JF_concerns.json", json.dumps({"concerns": [{
        "id": "C1", "source": "report.txt", "author": "Editor",
        "quote": "The human reviewer asks for units.",
        "summary": "units", "action": "text", "disposition": "to-fix"}]}))
    errs, warns = [], []
    pp.journal_ledger_problems(None, sb, errs, warns)
    check("PR151-025 a bare basename shared by both streams is ambiguous",
          any("ambiguous" in e for e in errs), str(errs)[:240])


# ---------------------------------------------------------------------------
# PR151-026 / PR151-051 / PR151-052
# ---------------------------------------------------------------------------
def test_response_parser() -> None:
    print("\n== response letter: hidden markup, duplicate quotes, short quotes ==")
    hidden = "<!--\n## C1\n**Comment:** \"a real quote\"\n-->\n"
    check("PR151-026 an all-comment letter yields no response block",
          pp.response_comment_quotes(hidden) == {}, pp.response_comment_quotes(hidden))
    fenced = "``` trailing\n## C1\n**Comment:** \"invented\"\n```\n"
    check("PR151-026 a fence with trailing text does not open a visible block",
          pp.response_comment_quotes(fenced) == {}, pp.response_comment_quotes(fenced))
    two = '## C1\n**Comment:** "first"\n**Comment:** "invented second"\n'
    check("PR151-051 two Comment lines make the block unverifiable",
          pp.response_comment_quotes(two) == {}, pp.response_comment_quotes(two))


# ---------------------------------------------------------------------------
# PR151-175 -- one literal quote must not swallow later score blocks
# ---------------------------------------------------------------------------
def test_pairwise_head_dump() -> None:
    print("\n== pairwise_scores: a literal quote inside an unquoted field ==")
    d = scratch("wave1_pair_")
    dump = d / "dump.txt"
    body = ("==> a/round1_raw_scores.csv <==\n"
            "id,side,opponent,rank,reason\n"
            'a,own,b,1,he said "hi\n'
            "\n==> b/round1_raw_scores.csv <==\n"
            "id,side,opponent,rank,reason\n"
            "b,own,a,2,clean\n")
    write(dump, body)
    blocks = list(pw.iter_head_dump(dump))
    check("PR151-175 a literal quote does not eat the next block",
          [p.as_posix() for p, _t in blocks] == ["a/round1_raw_scores.csv",
                                                  "b/round1_raw_scores.csv"],
          [p.as_posix() for p, _t in blocks])
    check("PR151-175 the quoted record stays one record",
          '"hi' in blocks[0][1] and "a,own" in blocks[0][1], blocks[0][1][:120])


# ---------------------------------------------------------------------------
# PR151-153 / PR151-156 -- AST import anonymization
# ---------------------------------------------------------------------------
def test_python_imports() -> None:
    print("\n== anonymizer: import lists, inline imports, string literals ==")
    d = scratch("wave1_imp_")
    write(d / "helper.py", "value = 1\n")
    write(d / "other.py", "value = 2\n")
    src = "import helper, other\nprint(helper.value, other.value)\n"
    write(d / "main.py", src)
    data, _ = pp._transform_view_file(
        "main.py", d / "main.py",
        {"main.py": "f1.py", "helper.py": "f2.py", "other.py": "f3.py"})
    data = data if isinstance(data, bytes) else data.encode()
    write(d / "f2.py", "value = 1\n")
    write(d / "f3.py", "value = 2\n")
    write(d / "f1.py", data.decode())
    r = subprocess.run([sys.executable, str(d / "f1.py")], capture_output=True, text=True)
    check("PR151-153 every name in `import a, b` is renamed and runs",
          r.returncode == 0 and r.stdout.strip() == "1 2",
          f"rc={r.returncode} out={r.stdout!r} src={data!r} err={r.stderr[-160:]!r}")

    inline = "if True: import helper\nprint(helper.value)\n"
    write(d / "inline.py", inline)
    data2, _ = pp._transform_view_file(
        "inline.py", d / "inline.py",
        {"inline.py": "f4.py", "helper.py": "f2.py"})
    text2 = data2.decode() if isinstance(data2, bytes) else data2
    check("PR151-153 an inline import is rewritten", "import f2" in text2, text2)

    literal = 'x = """\nimport helper\n"""\nprint(x)\n'
    write(d / "literal.py", literal)
    data3, _ = pp._transform_view_file(
        "literal.py", d / "literal.py",
        {"literal.py": "f5.py", "helper.py": "f2.py"})
    text3 = data3.decode() if isinstance(data3, bytes) else data3
    check("PR151-156 an import-looking line inside a string is untouched",
          '"""\nimport helper\n"""' in text3, text3)


# ---------------------------------------------------------------------------
# PR151-054 / PR151-057 / PR151-074 / PR151-098 -- split merge
# ---------------------------------------------------------------------------
def test_split_merge() -> None:
    print("\n== split review merge: ids, evidence, coverage, clean discovery ==")
    d = scratch("wave1_split_")
    a, b = d / "a", d / "b"
    for sb in (a, b):
        (sb / "guided_review" / "round2").mkdir(parents=True)
    write(a / "guided_review/findings.json", json.dumps({"findings": [], "coverage": [
        {"check": "J1", "disposition": "out of scope -- session B"}]}))
    write(b / "guided_review/findings.json", json.dumps({"findings": [], "coverage": [
        {"check": "J1", "disposition": "clean -- basis: sweep artifact"}]}))
    write(a / "guided_review/round2/findings_extra.json", json.dumps({
        "findings": [{"id": "X-001", "location": "a", "evidence": "A", "check": "c1"}]}))
    write(b / "guided_review/round2/findings_extra.json", json.dumps({
        "findings": [{"id": "X-001", "location": "X-001.md:17",
                      "evidence": "Sample X-001 has a missing age.", "check": "X-001"}],
        "coverage": [{"check": "X-001", "disposition": "noted"}]}))

    class Ctx:
        cfg = {"review_split": "phases"}

        def run(self, _rid):
            return {"sandbox": str(a)}

        def sandbox_of(self, rec):
            return Path(rec["sandbox"])

    merged = pp.merge_review_parts(Ctx(), {"round": 1, "sandbox": str(b)})
    extra = json.loads((b / "guided_review/round2/findings_extra.json").read_text())
    row = extra["findings"][1]
    new_id = merged["x_id_remap"]["X-001"]
    check("PR151-054 evidence and location keep their own X-001 token",
          row["evidence"] == "Sample X-001 has a missing age."
          and row["location"] == "X-001.md:17", row)
    check("PR151-054 the typed check reference follows the rename",
          row["check"] == new_id and extra["coverage"][-1]["check"] == new_id, row)
    check("PR151-098 a clean split run still merges both coverage tables",
          extra.get("findings") and len(extra["findings"]) == 2, extra)
    merged_cov = json.loads((b / "guided_review/findings.json").read_text())["coverage"]
    check("PR151-057 B's substantive coverage replaces A's out-of-scope row",
          merged_cov and merged_cov[0]["disposition"].startswith("clean"),
          merged_cov)


# ---------------------------------------------------------------------------
# PR151-003 / PR151-004 / PR151-005 / PR151-030 -- repair application scope
# ---------------------------------------------------------------------------
def test_repair_scope() -> None:
    print("\n== bounded repair scope: deletion, indentation, backslash names ==")
    check("PR151-005 a literal backslash is not a scratch separator",
          pp._repair_bookkeeping_rel("work\\paper.md") is False)

    rows = [{"id": "RP-001", "file": "paper.md", "location": "l",
             "wrong": "n = 10", "correct": "n = 20", "basis": "b", "edit": "e",
             "evidence": "x"}]
    write_ledger = {"rows": [{"id": "RP-001", "verdict": "confirmed", "reason": "r",
                              "before": "n = 10", "after": "n = 20",
                              "files": ["paper.md"]}]}
    d = scratch("wave1_repdel_")
    pre, cur = d / "pre", d / "cur"
    write(pre / "paper.md", "n = 10\n")
    (cur).mkdir()
    write(cur / "REPAIR_LEDGER.json", json.dumps(write_ledger))
    bad = pp._revised_repair_violations(pre, cur, rows, {"RP-001"}, with_reasons=True)
    check("PR151-003 a confirmed replacement row cannot delete its file",
          "paper.md" in bad and "deleted" in bad["paper.md"], bad)

    d = scratch("wave1_indent_")
    pre, cur = d / "pre", d / "cur"
    write(pre / "analysis.py", "if True:\n    n = 10\npublish()\n")
    write(cur / "analysis.py", "if True:\n    n = 20\npublish()\n")
    rows_py = [{"id": "RP-001", "file": "analysis.py", "location": "l",
                "wrong": "n = 10", "correct": "n = 20", "basis": "b", "edit": "e",
                "evidence": "x"}]
    write(cur / "REPAIR_LEDGER.json", json.dumps({"rows": [
        {"id": "RP-001", "verdict": "confirmed", "reason": "r",
         "before": "if True:\n    n = 10\npublish()",
         "after": "if True:\n    n = 20\npublish()", "files": ["analysis.py"]}]}))
    rows_py[0]["wrong"] = "n = 10"
    rows_py[0]["correct"] = "n = 20"
    bad = pp._revised_repair_violations(pre, cur, rows_py, {"RP-001"})
    check("PR151-004 indentation-only control-flow change is caught",
          "analysis.py" in bad, bad)

    # The fixture above quotes the WHOLE pre/post file, so the PR151-030
    # whole-file guard already flags it even when whitespace is collapsed: it
    # does not discriminate the line-based `.py` normalization. Quote only the
    # value and move `publish()` into the `if`; under collapsing normalization
    # the diff is inside the quote, under line-based normalization the moved
    # line is an unplanned change outside it.
    d = scratch("wave1_indent_local_")
    pre, cur = d / "pre", d / "cur"
    write(pre / "analysis.py", "if True:\n    n = 10\npublish()\n")
    write(cur / "analysis.py", "if True:\n    n = 20\n    publish()\n")
    rows_py_local = [{"id": "RP-001", "file": "analysis.py", "location": "l",
                      "wrong": "n = 10", "correct": "n = 20", "basis": "b", "edit": "e",
                      "evidence": "x"}]
    write(cur / "REPAIR_LEDGER.json", json.dumps({"rows": [
        {"id": "RP-001", "verdict": "confirmed", "reason": "r",
         "before": "n = 10", "after": "n = 20", "files": ["analysis.py"]}]}))
    bad = pp._revised_repair_violations(pre, cur, rows_py_local, {"RP-001"})
    check("PR151-004 a localized quote cannot hide an indentation-only control-flow change",
          "analysis.py" in bad, bad)

    d = scratch("wave1_whole_")
    pre, cur = d / "pre", d / "cur"
    write(pre / "paper.md", "abstract\nn = 12\nresults\n")
    write(cur / "paper.md", "abstract\nn = 13\nresults\n")
    rows_w = [{"id": "RP-001", "file": "paper.md", "location": "l",
               "wrong": "n = 12", "correct": "n = 13", "basis": "b", "edit": "e",
               "evidence": "x"}]
    write(cur / "REPAIR_LEDGER.json", json.dumps({"rows": [
        {"id": "RP-001", "verdict": "confirmed", "reason": "r",
         "before": "abstract\nn = 12\nresults", "after": "abstract\nn = 13\nresults",
         "files": ["paper.md"]}]}))
    bad = pp._revised_repair_violations(pre, cur, rows_w, {"RP-001"})
    check("PR151-030 whole-file quotes do not authorize a localized plan",
          "paper.md" in bad, bad)


# ---------------------------------------------------------------------------
# PR151-157 / PR151-165 / PR151-166 / PR151-174 -- conversion status
# ---------------------------------------------------------------------------
def test_conversion_status() -> None:
    print("\n== corpus conversion: malformed DOCX, bare XLSX, fake RTF, formula ==")
    d = scratch("wave1_conv_")
    malformed = d / "bad.docx"
    with zipfile.ZipFile(malformed, "w") as z:
        z.writestr("word/document.xml",
                   "<w:document><w:body><w:p><w:r><w:t>Visible</w:t>"
                   "<w:r><w:t>Lost</w:t></w:r></w:p></w:body>")
    text, notes = cc.docx_to_text(str(malformed))
    check("PR151-157 malformed WordprocessingML is reported, not silently converted",
          any("not well-formed" in n for n in notes), notes)
    status = cc.convert_one(str(malformed), "bad.docx")["status"]
    check("PR151-157 malformed DOCX is a failed conversion", status == "failed", status)

    bare = d / "bare.xlsx"
    with zipfile.ZipFile(bare, "w") as z:
        z.writestr("docProps/core.xml", "<core/>")
    status = cc.convert_one(str(bare), "bare.xlsx")["status"]
    check("PR151-165 an XLSX without workbook parts is unreadable, not empty",
          status == "failed", status)

    fake = d / "fake.rtf"
    write(fake, "This file is not RTF.")
    status = cc.convert_one(str(fake), "fake.rtf")["status"]
    check("PR151-166 a wrong file type named .rtf fails conversion",
          status == "failed", status)

    formula = d / "formula.xlsx"
    with zipfile.ZipFile(formula, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook><sheets><sheet name="Sheet1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships><Relationship Id="rId1" '
                   'Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet><sheetData><row r="1">'
                   '<c r="A1"><f>1+1</f><v></v></c></row></sheetData></worksheet>')
    text, notes = cc.xlsx_to_text(str(formula))
    check("PR151-174 an empty cached value on a formula is marked uncached",
          "uncached formula" in text, (text, notes))


# ---------------------------------------------------------------------------
# PR151-171 -- docx2pdf.sh refuses a non-DOCX before touching a sibling PDF
# ---------------------------------------------------------------------------
def test_docx2pdf_guard() -> None:
    print("\n== docx2pdf.sh: a non-DOCX input cannot delete a sibling PDF ==")
    d = scratch("wave1_pdf_")
    txt = d / "sample.txt"
    write(txt, "not a Word file\n")
    pdf = d / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 keep me\n")
    r = subprocess.run(["bash", str(WS / "docx2pdf.sh"), str(txt)],
                       capture_output=True, text=True)
    check("PR151-171 a non-DOCX input is refused", r.returncode == 2, r.stderr[-200:])
    check("PR151-171 the unrelated sibling PDF still exists",
          pdf.is_file() and pdf.read_bytes() == b"%PDF-1.4 keep me\n")


# ---------------------------------------------------------------------------
# PR151-013 / PR151-014 -- prompt profile and strict compilation
# ---------------------------------------------------------------------------
def test_prompt_profile() -> None:
    print("\n== prompts: no profile-only marker obligation; strict compile ==")
    sb = scratch("wave1_prompt_")
    audit_med = pp.revision_audit_prompt(sb, "r1_revision_audit", 1,
                                         execution_profile="medium")
    check("PR151-013 medium revision-audit prompt claims no root completion marker",
          "_pipeline_done.json" not in audit_med, audit_med[-400:])
    r = subprocess.run(
        [sys.executable, "-W", "error::SyntaxWarning", "-c",
         "compile(open('paper_pipeline_parts/p03_prompts.py').read(),'p','exec')"],
        cwd=WS, capture_output=True, text=True)
    check("PR151-014 prompt parts compile clean under -W error::SyntaxWarning",
          r.returncode == 0, r.stderr[-200:])


# ---------------------------------------------------------------------------
# PR151-154 / PR151-155 / PR151-173 -- citation include resolution
# ---------------------------------------------------------------------------
def test_citations() -> None:
    print("\n== citations: compile-root includes, import, nocite wildcard ==")

    def run_citations(files):
        d = scratch("wave1_cite_")
        work = d / "work"
        (work / "corpus").mkdir(parents=True)
        for name, body in files.items():
            write(work / "corpus" / name, body)
        r = subprocess.run(
            [sys.executable, str(WS / "paper-skills/paper-review/scripts/"
                                   "extract_citations.py"),
             "--work", str(work), "--out", str(d / "out")],
            capture_output=True, text=True)
        p = d / "out/artifacts/M2_citations.json"
        if not p.is_file():
            return {"error": r.stderr[-300:]}
        return json.loads(p.read_text())

    out = run_citations({
        "main.tex.txt": "\\documentclass{article}\\begin{document}\\cite{wrong}"
                        "\\end{document}",
        "left__shared.tex.txt": "\\cite{wrong}",
        "left__main.tex.txt": "\\documentclass{article}\\begin{document}"
                              "\\input{shared}\\bibitem{wrong}\\end{document}",
        "right__shared.tex.txt": "\\cite{wrong}",
        "right__main.tex.txt": "\\documentclass{article}\\begin{document}"
                               "\\input{shared}\\bibitem{wrong}\\end{document}"})
    check("PR151-154 an unrelated same-named fragment does not certify the cite",
          out.get("tex_orphan_keys") == ["wrong"], out.get("tex_orphan_keys_by_file"))

    out = run_citations({
        "main.tex.txt": "\\documentclass{article}\\begin{document}"
                        "\\import{chapters/}{shared}\\cite{impkey}\\end{document}",
        "chapters__shared.tex.txt": "\\bibitem{impkey}"})
    check("PR151-173 a file loaded with \\import enters the key space",
          out.get("tex_orphan_keys") == [], out.get("tex_orphan_keys_by_file"))

    out = run_citations({
        "main_a.tex.txt": "\\documentclass{article}\\begin{document}\\input{shared}"
                          "\\bibliography{a}\\end{document}",
        "main_b.tex.txt": "\\documentclass{article}\\begin{document}\\input{shared}"
                          "\\bibliography{b}\\end{document}",
        "shared.tex.txt": "\\nocite{*}",
        "a.bib.txt": "@article{akey, title={A}}",
        "b.bib.txt": "@article{bkey, title={B}}"})
    check("PR151-155 a shared \\nocite{*} does not orphan the other root's keys",
          out.get("tex_orphan_keys") == [], out.get("tex_orphan_keys_by_file"))


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_contract_helpers()
    test_feedback_binding()
    test_response_parser()
    test_pairwise_head_dump()
    test_python_imports()
    test_split_merge()
    test_repair_scope()
    test_conversion_status()
    test_docx2pdf_guard()
    test_prompt_profile()
    test_citations()
    cleanup()
    print()
    if FAILS:
        print(f"[tests] {len(FAILS)} FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL WAVE-1 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

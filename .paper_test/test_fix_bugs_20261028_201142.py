#!/usr/bin/env python3
"""Regression checks for the 2026-10-28 20:11 fix-bugs wave (F02..F80 ids).

Run:  python3 .paper_test/test_fix_bugs_20261028_201142.py

Each check pins one finding the verify-findings stage kept as a TRUE_POSITIVE.
It fails on the pre-fix tree and passes on the repaired one.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import types
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


pp = load("fb201142_pp", "paper_pipeline.py")
pf = load("fb201142_pf", "paper_docx_format.py")
cw = load("fb201142_cw", "paper-skills/paper-review/scripts/count_words.py")
ad = load("fb201142_ad", "paper_redlines_adapter.py")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def make_docx(path: Path, paras: list) -> None:
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        '<w:p><w:r><w:t xml:space="preserve">'
        + (p.replace("&", "&amp;").replace("<", "&lt;")) + "</w:t></w:r></w:p>"
        for p in paras)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="xml" ContentType='
                   '"application/xml"/><Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.'
                   'wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml", doc)


# ---------------------------------------------------------------------------
# M19 / counting cluster
# ---------------------------------------------------------------------------
def test_counting() -> None:
    print()
    print("== M19 counting: F02-F10, F13 ==")
    d = scratch("f02_")
    (d / "a.tex").write_text("A begins.\\input{b} A ends.", encoding="utf-8")
    (d / "b.tex").write_text("B begins.\\input{a} B ends.", encoding="utf-8")
    a_text = (d / "a.tex").read_text()
    direct = pp._tex_expand_includes(a_text, d)
    with_source = pp._tex_expand_includes(a_text, d, source=d / "a.tex")
    check("F02 an include cycle expands the root once",
          direct.count("A begins.") == 1 and with_source.count("A begins.") == 1,
          direct)

    prof = pp.load_venue_profile("nature-biotechnology")
    tex = ("\\section{Introduction}\nBody prose here.\n"
           "\\begin{table}\n\\caption{Table caption with several words}\n\\end{table}\n")
    lines, spans, _ = pp._tex_length_scan(tex)
    rows = pp._length_rows_for_lines(lines, "x.tex", caption_spans=spans,
                                     counting=prof.counting, limits=prof.length_limits())
    main = [r for r in rows if r["section"] == "main text"][0]
    check("F03 a table caption is not subtracted when the venue counts table captions",
          main["words"] == 8 and "caption word(s) subtracted" not in main["note"], main)

    d4 = scratch("f04_")
    make_docx(d4 / "paper.docx", [
        "Long paper title", "Abstract", "Abstract words here.", "Introduction",
        "Body prose one. Body prose two.", "Figure 1 | legend first part",
        "continuation of the legend here", "Results", "More body prose."])
    info4 = pp.scan_lengths_in_sources([(d4, "", ())], profile=prof)
    row4 = [r for r in info4["rows"] if r["document"] == "paper.docx"
            and r["section"] == "main text"][0]
    check("F04 a DOCX caption continuation is subtracted with its legend",
          row4["words"] == 9 and "11 caption word(s) subtracted" in row4["note"], row4)

    sec5 = cw.sections("Title\nIntroduction\nBody one.\nBody two.\nSummary\nWe conclude.")
    check("F05 a closing Summary is not the abstract", sec5[0][0] == "main text", sec5)

    d6 = scratch("f06_")
    (d6 / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\n\\section{Introduction}\nMain."
        "\\input{intro}\n\\end{document}\n", encoding="utf-8")
    (d6 / "intro.tex").write_text("Body text here and more words.\n", encoding="utf-8")
    r6 = subprocess.run([sys.executable,
                         str(WS / "paper-skills/paper-review/scripts/count_words.py"),
                         str(d6 / "main.tex")], capture_output=True, text=True)
    check("F06 count_words follows \\input", r6.returncode == 0
          and "main text: 6 words" in r6.stdout, r6.stdout[-200:])

    tex7 = ("\\section{Introduction}\nReal prose.\n\\begin{verbatim}\n"
            "code one code two code three\n\\end{verbatim}\nMore prose.\n")
    check("F07 the pipeline and skill both exclude verbatim prose",
          pp._tex_length_scan(tex7)[0] == cw.tex_lines(tex7)[0],
          (pp._tex_length_scan(tex7)[0], cw.tex_lines(tex7)[0]))

    check("F08 a response letter is not a cover letter",
          cw.is_cover_letter("Dear Editor, our response.", "response-to-reviewers.docx")
          is False)
    check("F09 a response name is not the cover role",
          pp.docx_document_role("cover-letter-response.docx") == "main"
          and pf.is_cover_letter_doc("cover-letter-response.docx") is False)

    d10 = scratch("f10_")
    p10 = d10 / "MANUAL_STEPS.md"
    p10.write_text("a | b\n--- | ---\nx | y\n", encoding="utf-8")
    check("F10 a two-column table without outer pipes is counted",
          pp.count_manual_steps(p10) == 1, pp.count_manual_steps(p10))

    check("F13 one unmatched brace in prose does not hide a complete JSON payload",
          pp._json_from_text('prose { unclosed then {"a":1}', True) == {"a": 1})


# ---------------------------------------------------------------------------
# Review / repair / ranking contracts
# ---------------------------------------------------------------------------
def _review_errors(tmp: Path, *, all_out=(), scope="full"):
    sb = tmp / "sb"
    (sb / "prior_round").mkdir(parents=True)
    (sb / "review" / "artifacts").mkdir(parents=True)
    (sb / "prior_round" / "findings.json").write_text('{"findings": []}', encoding="utf-8")
    wanted = list(pp.REQUIRED_REVIEW_CHECKS) + [
        "M19", "M18", "M20", "M21", "M22", "M23", "M24", "M25", "M26", "M27", "M28",
        "M29", "J5", "M30", "M31", "M32", "M33", "M34", "M35", "M36"]
    cov = [{"check": c,
            "disposition": ("out of scope -- pass" if c in all_out
                            else "clean -- basis: a.md")}
           for c in wanted]
    cur = {"submission_dir": "./base", "findings": [], "coverage": cov}
    (sb / "review" / "findings.json").write_text(json.dumps(cur), encoding="utf-8")
    for name in ("M1.md", "M27_evidence_coverage.md", "M34_source_data_coverage.md"):
        (sb / "review" / "artifacts" / name).write_text(
            "| check | disposition |\n|---|---|\n| x | clean |\n", encoding="utf-8")
    (sb / "review" / "findings.md").write_text("# findings\n", encoding="utf-8")
    errs = []
    pp.check_review_contract(types.SimpleNamespace(cfg={}), sb, cur, errs, [],
                             scope=scope)
    return errs


def test_contracts() -> None:
    print()
    print("== review / repair / ranking contracts: F14, F15, F17-F19 ==")
    errs = _review_errors(scratch("f14_"), all_out=("M1", "M3"), scope="formatting-writing")
    check("F14 a scoped round cannot dispose an IN-SCOPE check as out of scope",
          any("in-scope check(s)" in e for e in errs), errs[:1])
    msg = inspect.getsource(pp.postcheck_audit)
    check("F15 the missing-audit message does not ask for an AU-* adds row",
          "plus its `AU-` adds" not in msg and "audit/UNRESOLVED.md" in msg)

    pre, cur = scratch("f17_pre"), scratch("f17_cur")
    pre.mkdir(exist_ok=True); cur.mkdir(exist_ok=True)
    (pre / "main.txt").write_text("para one ALPHA\npara two BETA\n", encoding="utf-8")
    (cur / "main.txt").write_text("para one ONE\npara two TWO\n", encoding="utf-8")
    rows = [{"id": "RP-1", "file": "main.txt", "location": "para one", "wrong": "ALPHA",
             "correct": "ONE", "basis": "b", "edit": "e", "evidence": "x"},
            {"id": "RP-2", "file": "main.txt", "location": "para two", "wrong": "BETA",
             "correct": "TWO", "basis": "b", "edit": "e", "evidence": "x"}]
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-1", "before": "ALPHA", "after": "ONE"},
        {"id": "RP-2", "before": "BETA", "after": "TWO"}]}), encoding="utf-8")
    check("F17 two confirmed rows for two paragraphs of one file are accepted",
          pp._revised_repair_violations(pre, cur, rows, {"RP-1", "RP-2"}) == [],
          pp._revised_repair_violations(pre, cur, rows, {"RP-1", "RP-2"}))
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": [
        {"id": "RP-1", "before": "ALPHA", "after": "ONE"}]}), encoding="utf-8")
    check("F17 an unquoted second change is still rejected",
          pp._revised_repair_violations(pre, cur, rows, {"RP-1", "RP-2"}) == ["main.txt"])

    decide_src = (WS / "paper_pipeline_parts/p12_conflicts_decide.py").read_text()
    check("F18 the selection reads a passable/recorded defect floor",
          inspect.signature(pp.select_champion).parameters["floor"].default is None
          and '"tiebreak_defect_floor"' in inspect.getsource(pp.finalize_round)
          and 'floor=rrec.get("tiebreak_defect_floor")' in decide_src)
    check("F19 the aggregation reads a passable/recorded dedup mode",
          inspect.signature(pp.aggregate_round).parameters["dedup"].default is None
          and '"dedup_mode"' in inspect.getsource(pp.finalize_round)
          and 'dedup=rrec.get("dedup_mode")' in decide_src)
    sync_src = inspect.getsource(pp.cmd_sync_code)
    check("F25 sync-code no longer writes through a fixed .sync-tmp name",
          "_atomic_write_bytes" in sync_src
          and 'd.name + ".sync-tmp"' not in sync_src)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------
def test_paths() -> None:
    print()
    print("== path safety: F22-F35, F38, F73 ==")
    root = scratch("f22_"); (root / "pinned").mkdir()
    ctx = types.SimpleNamespace(pins_dir=root / "pinned")
    refused = 0
    for bad in ("../outside", "/tmp/outside"):
        try:
            pp.pinned_docs_dir(ctx, {"id": bad})
        except SystemExit:
            refused += 1
    check("F22 an escaping pin id is refused", refused == 2)

    root23 = scratch("f23_"); (root23 / "pinned").mkdir()
    ctx23 = types.SimpleNamespace(
        root=root23, pins_dir=root23 / "pinned",
        state={"pinned": [{"id": "p1", "digest": "x"}],
               "rounds": {"1": {"status": "done", "winner_dir": "../outside",
                                 "pin_id": "p1"}}},
        rounds_count=lambda: 1)
    errs23 = pp.pinned_integrity(ctx23)
    check("F23 an escaping winner_dir is reported, not hashed",
          any("outside --root" in e for e in errs23), errs23)

    root24 = scratch("f24_"); (root24 / "runs").mkdir()
    ctx24 = types.SimpleNamespace(root=root24, runs_dir=root24 / "runs")
    refused = 0
    for fn, args in ((pp.failed_sandbox_dir, (ctx24, {"id": "../evil"})),
                     (pp.stash_logs, (root24 / "sb", root24 / "logs", "../evil"))):
        try:
            fn(*args)
        except SystemExit:
            refused += 1
    check("F24 escaping run ids are refused by retry/prune paths", refused == 2)

    outside = scratch("f26_out_")
    (outside / "secret.tex").write_text(
        "\\documentclass{article}\\begin{document}TOPSECRET\\end{document}", encoding="utf-8")
    pkg = scratch("f26_pkg_")
    os.symlink(outside / "secret.tex", pkg / "main.tex")
    check("F26 a symlinked LaTeX root is refused",
          pp.latex_root_documents(pkg) == []
          and pp.compile_latex_pdf(pkg, "main.tex", scratch("f26_out2_") / "o.pdf")["ok"]
          is False)

    owner = scratch("f27_owner_")
    (owner / "non_revised" / "raw_data").mkdir(parents=True)
    bad_tree = scratch("f27_bad_")
    (bad_tree / "non_revised" / "raw_data").mkdir(parents=True)
    (bad_tree / "non_revised" / "raw_data" / "secret.txt").write_text("S", encoding="utf-8")
    pkg27 = scratch("f27_pkg_")
    os.symlink(bad_tree / "non_revised" / "raw_data", pkg27 / "raw_data")
    check("F27 an outside evidence-shaped tree is not followed into the judge view",
          [r for r, _p in pp.corpus_dir_view_files(pkg27, owner_root=owner)] == [])

    pkg29 = scratch("f29_"); (pkg29 / "main.tex").write_text("body", encoding="utf-8")
    (outside / "secret.docx").write_bytes(b"PK")
    os.symlink(outside / "secret.docx", pkg29 / "main.docx")
    check("F29 a symlinked document is not tracked",
          [r["rel"] for r in pp.list_track_files([(pkg29, "", ())])] == ["main.tex"])
    pkg30 = scratch("f30_")
    os.symlink(outside / "secret.txt", pkg30 / "innocent.txt")
    check("F30 a symlinked document's prose is not read", pp.package_document_texts(pkg30) == [])

    victim = outside / "victim.txt"; victim.write_bytes(b"KEEP")
    out31 = scratch("f31_") / "out.docx"
    os.symlink(victim, out31)
    ad.write_out(str(out31), b"NEW")
    check("F31 write_out replaces a planted link instead of writing through it",
          victim.read_bytes() == b"KEEP" and not out31.is_symlink()
          and out31.read_bytes() == b"NEW")
    victim32 = outside / "victim.json"; victim32.write_text("KEEP", encoding="utf-8")
    out32 = scratch("f32_") / "report.json"
    os.symlink(victim32, out32)
    pf.write_json(out32, {"a": 1})
    check("F32 write_json replaces a planted link atomically",
          victim32.read_text() == "KEEP" and not out32.is_symlink()
          and json.loads(out32.read_text()) == {"a": 1})

    root34 = scratch("f34_"); out34 = scratch("f34_out_")
    os.symlink(out34, root34 / "reports")
    check("F34 a symlinked reports/ is refused",
          pp.start_run_log("status", root34) is None and list(out34.iterdir()) == [])
    root73 = scratch("f73_"); out73 = scratch("f73_out_")
    os.symlink(out73, root73 / "redlines")
    try:
        pp.ensure_aux_output_root(root73, "redlines")
        did_refuse = False
    except SystemExit:
        did_refuse = True
    check("F73 a symlinked auxiliary output root is refused", did_refuse)

    root35 = scratch("f35_")
    src35 = scratch("f35_src_") / "letter.txt"; src35.write_text("LETTER", encoding="utf-8")
    import hashlib
    tag = hashlib.sha1(str(src35.resolve()).encode()).hexdigest()[:8]
    destdir = root35 / "frozen_feedback"; destdir.mkdir()
    dest35 = destdir / f"{src35.stem}-{tag}{src35.suffix}"
    victim35 = root35 / "victim.txt"; victim35.write_text("KEEP", encoding="utf-8")
    os.symlink(victim35, dest35)
    pp._freeze_journal_feedback(root35, src35)
    check("F35 a planted frozen-feedback link is replaced, not written through",
          victim35.read_text() == "KEEP" and not dest35.is_symlink()
          and dest35.read_text() == "LETTER")

    out38 = scratch("f38_") / "out.docx"
    victim38 = outside / "victim38.txt"; victim38.write_bytes(b"KEEP")
    os.symlink(victim38, out38)
    fake = types.ModuleType("python_redlines")
    class Engine:
        def __init__(self, *a): pass
        def run_redline(self, *a): return (b"REDLINED", "", "")
    fake.DocxodusEngine = Engine
    sys.modules["python_redlines"] = fake
    try:
        result = pp._redlines_inproc(scratch("f38b_") / "b.docx",
                                     scratch("f38b_") / "r.docx", out38)
    finally:
        sys.modules.pop("python_redlines", None)
    check("F38 the in-process redline replaces a planted OUT link",
          result["ok"] and victim38.read_bytes() == b"KEEP" and not out38.is_symlink())


# ---------------------------------------------------------------------------
# Resource bounds
# ---------------------------------------------------------------------------
def test_resources() -> None:
    print()
    print("== resource bounds: F39, F56-F60, F68, F69, F80 ==")
    big = scratch("f39_") / "big.pdf"
    with open(big, "wb") as f:
        f.truncate(pf.MAX_PDF_BYTES + 1024)
    check("F39 an over-budget PDF is refused without being read",
          pf._xfa_dataset_report(big) == (False, -1, False)
          and pf._pdf_carries_an_image(big) is False)

    sb = scratch("f56_"); (sb / "probe_review" / "scripts").mkdir(parents=True)
    (sb / "probe_review" / "scripts" / "v.py").write_text("print('1')", encoding="utf-8")
    findings = [{"id": f"X-{900 + i:03d}",
                 "verifier": {"script": "probe_review/scripts/v.py", "computed": "1"}}
                for i in range(1, 8)]
    old = pp.PROBE_REPRO_MAX_VERIFIERS
    pp.PROBE_REPRO_MAX_VERIFIERS = 3
    try:
        rep = pp.probe_reproduction(sb, findings)
    finally:
        pp.PROBE_REPRO_MAX_VERIFIERS = old
    check("F56 the verifier count is capped",
          [r["status"] for r in rep["results"]] == ["reproduced"] * 3
          + ["skipped-over-budget"] * 4, [r["status"] for r in rep["results"]])

    d = scratch("f57_")
    secret = d / "secret.md"; secret.write_text("SECRET", encoding="utf-8")
    link = d / "link.md"; os.symlink(secret, link)
    big_md = d / "big.md"
    with open(big_md, "wb") as f:
        f.truncate(pp.MAX_JSON_BYTES + 1)
    check("F57-F60 the shared text reader refuses a link and an over-budget file",
          pp.read_text_bounded(link) is None and pp.read_text_bounded(big_md) is None
          and pp.parse_markdown_blocks(link) == [])

    pkg = scratch("f68_")
    with open(pkg / "huge.tex", "wb") as f:
        f.truncate(pp.MAX_JSON_BYTES + 1)
    (pkg / "small.txt").write_text("small prose", encoding="utf-8")
    check("F68 an over-budget package document is skipped",
          [r for r, _t in pp.package_document_texts(pkg)] == ["small.txt"])

    root = scratch("f69_"); (root / "code").mkdir()
    outside = scratch("f69_out_"); (outside / "secret.tex").write_text("SECRET", encoding="utf-8")
    (root / "main.tex").write_text("\\input{sub}", encoding="utf-8")
    (root / "sub.tex").write_text("SUBPROSE", encoding="utf-8")
    os.symlink(outside / "secret.tex", root / "linked.tex")
    closure, sources = pp.tex_input_closure(root, ["code"])
    check("F69 a symlinked TeX input source is not read",
          "linked.tex" not in sources and "linked.tex" not in closure, (sources, closure))

    flood = scratch("f80_") / "server.py"
    flood.write_text("import sys, time\n"
                     "sys.stdout.write('x' * (2 * 1024 * 1024) + '\\n')\n"
                     "sys.stdout.flush()\n"
                     "time.sleep(30)\n", encoding="utf-8")
    rep80 = pp.mcp_stdio_tool_call({"command": sys.executable, "args": [str(flood)]},
                                   "tools/call", {}, timeout=2)
    check("F80 a flooding MCP server is dropped and reported",
          rep80.get("ok") is False and "flooded" in (rep80.get("error") or ""),
          rep80.get("error", "")[:120])


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def test_misc() -> None:
    print()
    print("== misc: F64, F72 ==")
    d = scratch("f64_")
    good = d / "good.pdf"
    good.write_bytes(b"%PDF-1.4\nbody\n" + b" " * 100 + b"%%EOF\n")
    bad = d / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 prose %%EOF\n" + b"x" * 3000)
    cmd = ('head -c 1024 -- "$1" | grep -aq \'%PDF-\' && '
           'tail -c 2048 -- "$1" | grep -aq \'%%EOF\' && echo PASSES || echo FAILS')
    ok = subprocess.run(["bash", "-c", cmd, "_", str(good)],
                        capture_output=True, text=True).stdout.strip()
    nok = subprocess.run(["bash", "-c", cmd, "_", str(bad)],
                         capture_output=True, text=True).stdout.strip()
    check("F64 the trailer check accepts a real PDF and rejects prose %%EOF",
          ok == "PASSES" and nok == "FAILS", (ok, nok))

    spec = importlib.util.spec_from_file_location("fb201142_qa", str(WS / "paper_qwen_agent.py"))
    qa = importlib.util.module_from_spec(spec)
    sys.modules["fb201142_qa"] = qa
    spec.loader.exec_module(qa)
    qa.probe_endpoint = lambda cfg: (True, ["m"], "")
    check("F72 --tunnel require accepts an already reachable endpoint",
          qa.ensure_tunnel({"base_url": "http://127.0.0.1:9", "tunnel": "require",
                            "local_port": 9, "ssh_port": 22, "remote": "x",
                            "ssh_host": "h"}) == "")


# ---------------------------------------------------------------------------
# Repair of the final review's confirmed issues (R01-R04)
# ---------------------------------------------------------------------------
def test_repair_r01_r04() -> None:
    print()
    print("== repair R01-R04 ==")
    # R01: a captioned TeX document named for the run's own article type must
    # not crash on the 3-tuple caption spans, and an NBT table caption must
    # stay in the count (only figure-legends are excluded).
    prof_r01 = pp.load_venue_profile("nature-biotechnology")
    prof_r01.article_type_id = "correspondence"
    d_r01 = scratch("r01_")
    (d_r01 / "Correspondence.tex").write_text(
        "Dear Editor,\n\nWe report a finding.\n"
        "\\begin{figure}\n\\caption{A figure caption with several words here}\n\\end{figure}\n"
        "\\begin{table}\n\\caption{Table caption with several words}\n\\end{table}\n"
        "Sincerely,\nA. Author\n", encoding="utf-8")
    rep_r01 = pp.scan_lengths_in_sources([(d_r01, "", ())], profile=prof_r01)
    rows_r01 = [r for r in rep_r01["rows"] if r["section"] == "main text"]
    check("R01 a captioned TeX article-type document keeps its table caption",
          len(rows_r01) == 1 and rows_r01[0]["words"] == 14, rows_r01)

    # R02: the second integration-ledger reader must refuse a symlink and an
    # over-budget file exactly like the donor-ledger reader.
    d_r02 = scratch("r02_")
    outside_r02 = d_r02 / "outside.md"
    outside_r02.write_text("X-901 ported", encoding="utf-8")
    link_r02 = d_r02 / "DIFF_LEDGER.md"
    os.symlink(outside_r02, link_r02)
    check("R02 a symlinked integration ledger is not followed",
          bool(pp.discovery_ledger_reconciliation_problems(link_r02, ["X-901"])))
    ok_r02 = d_r02 / "OK.md"
    ok_r02.write_text("X-901 ported", encoding="utf-8")
    check("R02 a regular integration ledger still reconciles",
          pp.discovery_ledger_reconciliation_problems(ok_r02, ["X-901"]) == [])
    old_json_bytes = pp.MAX_JSON_BYTES
    pp.MAX_JSON_BYTES = 64
    try:
        big_r02 = d_r02 / "BIG.md"
        big_r02.write_text("X-901 ported\n" * 20, encoding="utf-8")
        check("R02 an over-budget integration ledger is refused",
              bool(pp.discovery_ledger_reconciliation_problems(big_r02, ["X-901"])))
    finally:
        pp.MAX_JSON_BYTES = old_json_bytes

    # R03: the corpus identity must not follow an outside evidence-shaped tree
    # when the owning root is known; the canonical <root>/non_revised/<area>
    # link is still followed.
    owner_r03 = scratch("r03_owner_")
    (owner_r03 / "non_revised" / "raw_data").mkdir(parents=True)
    outside_r03 = scratch("r03_out_") / "non_revised" / "raw_data"
    outside_r03.mkdir(parents=True)
    (outside_r03 / "secret.txt").write_text("SECRET", encoding="utf-8")
    pkg_r03 = owner_r03 / "sandbox" / "revised"
    pkg_r03.mkdir(parents=True)
    (pkg_r03 / "main.tex").write_text("PROSE", encoding="utf-8")
    os.symlink(outside_r03, pkg_r03 / "raw_data")
    man_direct = pp.manifest_for_sources([(pkg_r03, "", ())], owner_root=owner_r03)
    ctx_r03 = types.SimpleNamespace(root=owner_r03)
    old_sources = pp.corpus_sources
    pp.corpus_sources = lambda ctx, r, vid: [(pkg_r03, "", ())]
    try:
        man_identity = pp.corpus_manifest(ctx_r03, 1, "v1")
    finally:
        pp.corpus_sources = old_sources
    check("R03 the corpus identity refuses an outside evidence tree",
          "raw_data/secret.txt" not in man_identity["files"]
          and "raw_data/secret.txt" not in man_direct["files"],
          {"identity": sorted(man_identity["files"]), "direct": sorted(man_direct["files"])})
    (owner_r03 / "non_revised" / "raw_data" / "real.txt").write_text("REAL", encoding="utf-8")
    pkg_r03b = owner_r03 / "sandbox" / "revised2"
    pkg_r03b.mkdir()
    os.symlink(owner_r03 / "non_revised" / "raw_data", pkg_r03b / "raw_data")
    check("R03 the owning root's canonical evidence link is still followed",
          "raw_data/real.txt" in
          pp.manifest_for_sources([(pkg_r03b, "", ())], owner_root=owner_r03)["files"])
    pp.corpus_sources = lambda ctx, r, vid: [(pkg_r03, "", ())]
    try:
        fp_with_link = pp.corpus_content_fingerprint(ctx_r03, 1, "v1")
        os.unlink(pkg_r03 / "raw_data")
        fp_without_link = pp.corpus_content_fingerprint(ctx_r03, 1, "v1")
    finally:
        pp.corpus_sources = old_sources
    check("R03 the content fingerprint ignores an outside evidence tree",
          fp_with_link == fp_without_link and bool(fp_with_link),
          (fp_with_link[:12], fp_without_link[:12]))

    # R04: a long stderr line is read with the byte cap and reported; the
    # stdout queue has a TOTAL-byte budget, not just a line count (slow
    # consumer so the queue actually accumulates).
    d_r04 = scratch("r04_")
    srv = d_r04 / "server.py"
    srv.write_text(
        "import json, sys\n"
        "mode = sys.argv[1]\n"
        "if mode == 'stderr':\n"
        "    sys.stderr.write('E' * (2 * 1024 * 1024) + '\\n')\n"
        "    sys.stderr.flush()\n"
        "elif mode == 'stdout':\n"
        "    for _ in range(12):\n"
        "        sys.stdout.write('x' * (1024 * 1024 - 1) + '\\n')\n"
        "    sys.stdout.flush()\n"
        "for line in sys.stdin:\n"
        "    try:\n"
        "        msg = json.loads(line)\n"
        "    except ValueError:\n"
        "        continue\n"
        "    if msg.get('id') == 1:\n"
        "        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {}}) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "    elif msg.get('id') == 2:\n"
        "        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': 2,\n"
        "                                      'result': {'content': []}}) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "        break\n", encoding="utf-8")
    rep_err = pp.mcp_stdio_tool_call(
        {"command": sys.executable, "args": [str(srv), "stderr"]},
        "tools/call", {}, timeout=2)
    check("R04 a long stderr line is bounded and reported",
          rep_err.get("ok") is True
          and any("stderr" in w for w in (rep_err.get("warnings") or [])), rep_err)

    class _SlowQueue(queue.Queue):
        def get(self, block=True, timeout=None):
            time.sleep(0.05)
            return super().get(block=block, timeout=timeout)

    real_queue = pp.queue.Queue
    pp.queue.Queue = _SlowQueue
    try:
        rep_queue = pp.mcp_stdio_tool_call(
            {"command": sys.executable, "args": [str(srv), "stdout"]},
            "tools/call", {}, timeout=2)
    finally:
        pp.queue.Queue = real_queue
    check("R04 the stdout queue is bounded by total bytes, not only line count",
          rep_queue.get("ok") is False
          and "flooded" in (rep_queue.get("error") or ""), rep_queue.get("error", "")[:160])


def main() -> int:
    test_counting()
    test_contracts()
    test_paths()
    test_resources()
    test_misc()
    test_repair_r01_r04()
    cleanup()
    print()
    if FAILS:
        print(f"[tests] {len(FAILS)} FAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("[tests] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

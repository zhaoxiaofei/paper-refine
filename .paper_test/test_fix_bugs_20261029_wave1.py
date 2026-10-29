#!/usr/bin/env python3
"""Regression checks for the 2026-10-29 fix-bugs wave 1.

Run:  python3 .paper_test/test_fix_bugs_20261029_wave1.py

Every finding below was verified TRUE_POSITIVE by two independent passes over
the 2026-10-29 find-bugs tree. Each check fails on the pre-fix tree and pins
the smallest observed defect (F03..F90, the ids of the verification ledger).
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import docx

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1029_pp", "paper_pipeline.py")
pf = load("fixbugs1029_pf", "paper_docx_format.py")
cw = load("fixbugs1029_cw", "paper-skills/paper-review/scripts/count_words.py")
rt = load("fixbugs1029_rt", "paper-skills/paper-revise/scripts/revision_token.py")
qn = load("fixbugs1029_qn", "paper_qwen_agent.py")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# F03 -- an include used twice expands twice; a cycle still stops
# ---------------------------------------------------------------------------
def test_f03() -> None:
    print("\n== F03: repeated TeX include counts twice ==")
    d = scratch("fixbugs1029_f03_")
    _write(d / "body.tex", "body words here now.\n")
    _write(d / "main.tex", "Main \\input{body} and \\input{body} end.\n")
    master = (d / "main.tex").read_text(encoding="utf-8")
    for label, mod in (("pipeline", pp), ("count_words", cw)):
        out = mod._tex_expand_includes(master, d, source=d / "main.tex")
        check(f"F03 {label}: both includes expand", out.count("body words here now") == 2, out)
        check(f"F03 {label}: no spurious literal left", "\\input{body}" not in out, out)
    _write(d / "a.tex", "A begins.\n\\input{b}\n")
    _write(d / "b.tex", "B body.\n\\input{a}\n")
    for label, mod in (("pipeline", pp), ("count_words", cw)):
        out = mod._tex_expand_includes((d / "a.tex").read_text(), d, source=d / "a.tex")
        check(f"F03 {label}: a two-file cycle still stops", out.count("A begins.") == 1, out)


# ---------------------------------------------------------------------------
# F04 -- subtract only the caption KINDS the venue excludes
# ---------------------------------------------------------------------------
def test_f04() -> None:
    print("\n== F04: caption kinds are honoured ==")
    tex = ("\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n"
           "Body text is here now.\n"
           "\\begin{table}\\caption{This table caption has thirteen words in it total "
           "today.}\\end{table}\n\\end{document}\n")
    lines, abstract_end, captions = cw.tex_lines(tex)
    check("F04 tex_lines tags a table caption", captions and captions[0][1] == "table",
          str(captions))
    nbt = ("abstract", "methods", "references", "figure-legends")
    rows = {s: w for s, w, _ in cw.sections("\n".join(lines), abstract_end=abstract_end,
                                            caption_lines=captions, excludes=nbt)}
    check("F04 NBT keeps the table caption in main text", rows.get("main text") == 15, str(rows))
    fron = nbt + ("table-captions", "table-contents")
    rows2 = {s: w for s, w, _ in cw.sections("\n".join(lines), abstract_end=abstract_end,
                                             caption_lines=captions, excludes=fron)}
    check("F04 Frontiers subtracts the table caption", rows2.get("main text") == 5, str(rows2))


# ---------------------------------------------------------------------------
# F05 -- a one-line abstract preceded by title text
# ---------------------------------------------------------------------------
def test_f05() -> None:
    print("\n== F05: inline abstract is recognised ==")
    one = "Title text \\begin{abstract}Inline abstract words here.\\end{abstract}\nBody here.\n"
    lines, abstract_end, _caps = cw.tex_lines(one)
    rows = {s: w for s, w, _ in cw.sections("\n".join(lines), abstract_end=abstract_end)}
    check("F05 the abstract row is emitted", rows.get("abstract") == 4, str(rows))
    check("F05 the abstract is not left in main text", rows.get("main text") == 2, str(rows))


# ---------------------------------------------------------------------------
# F06 -- DOCX is extracted, not decoded as UTF-8; other binaries are refused
# ---------------------------------------------------------------------------
def test_f06() -> None:
    print("\n== F06: count_words reads a DOCX as a document ==")
    d = scratch("fixbugs1029_f06_")
    doc = docx.Document()
    doc.add_paragraph("Introduction")
    doc.add_paragraph("This body has four words")
    doc.save(d / "main.docx")
    out = d / "rows.json"
    proc = subprocess.run([sys.executable,
                           str(WS / "paper-skills/paper-review/scripts/count_words.py"),
                           "--json", str(d / "main.docx")],
                          capture_output=True, text=True, cwd=str(WS))
    rows = {}
    with contextlib.suppress(ValueError):
        rows = {r.get("section"): r.get("words")
                for r in json.loads(proc.stdout or "{}").get("rows", [])}
    check("F06 the DOCX body is counted as its paragraph words",
          proc.returncode == 0 and rows.get("main text") == 5,
          f"rc={proc.returncode} {rows} {proc.stderr[:120]}")
    (d / "paper.pdf").write_bytes(b"%PDF-1.4 not text")
    proc2 = subprocess.run([sys.executable,
                            str(WS / "paper-skills/paper-review/scripts/count_words.py"),
                            "--json", str(d / "paper.pdf")],
                           capture_output=True, text=True, cwd=str(WS))
    check("F06 an unsupported binary is refused, not counted",
          proc2.returncode != 0 and "binary document" in (proc2.stdout + proc2.stderr),
          f"rc={proc2.returncode} {(proc2.stdout + proc2.stderr)[:200]}")
    # A text box's paragraph is nested inside its container paragraph, and an
    # mc:AlternateContent carries the same text twice. Reading every
    # descendant counted both; the visible-text walk must count each once.
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
          'xmlns:v="urn:schemas-microsoft-com:vml"')
    body = (
        "<w:document " + ns + "><w:body>"
        "<w:p><w:r><w:t>Outer</w:t></w:r><w:r><w:pict><v:shape><v:textbox>"
        "<w:txbxContent><w:p><w:r><w:t>Inner</w:t></w:r></w:p></w:txbxContent>"
        "</v:textbox></v:shape></w:pict></w:r></w:p>"
        "<w:p><w:r><mc:AlternateContent><mc:Choice Requires=\"wps\">"
        "<w:t>Choice</w:t></mc:Choice><mc:Fallback><w:t>Fallback</w:t>"
        "</mc:Fallback></mc:AlternateContent></w:r></w:p>"
        "</w:body></w:document>")
    nested = d / "nested.docx"
    with zipfile.ZipFile(nested, "w") as z:
        z.writestr("word/document.xml", body)
    text = cw.docx_paragraph_text(nested)
    check("F06 a text box is counted once", text.count("Inner") == 1, repr(text))
    check("F06 only one AlternateContent branch is counted",
          "Fallback" not in text and text.count("Choice") == 1, repr(text))
    dtd = d / "dtd.docx"
    with zipfile.ZipFile(dtd, "w") as z:
        z.writestr("word/document.xml",
                   "<!DOCTYPE x [<!ENTITY y \"z\">]><w:document " + ns +
                   "><w:body><w:p><w:r><w:t>&y;</w:t></w:r></w:p></w:body></w:document>")
    check("F06 a DOCX with a DTD is refused", cw.docx_paragraph_text(dtd) is None)


# ---------------------------------------------------------------------------
# F07 -- the corpus text scans are bounded
# ---------------------------------------------------------------------------
def test_f07() -> None:
    print("\n== F07: package text scans use read_text_bounded ==")
    d = scratch("fixbugs1029_f07_")
    _write(d / "a.md", "Figure 1. A legend that is long enough to be seen.\n")
    _write(d / "b.tex", "\\caption{A table-ish caption long enough to be seen.}\n")
    rep = pp.scan_captions_in_sources([(d, "", ())])
    check("F07 captions are found normally", rep.get("count", 0) >= 1, str(rep)[:200])
    old = pp.MAX_JSON_BYTES
    pp.MAX_JSON_BYTES = 8
    try:
        rep2 = pp.scan_captions_in_sources([(d, "", ())])
        lengths = pp.scan_lengths_in_sources(
            [(d, "", ())], profile=pp.load_venue_profile("nature-biotechnology"))
        check("F07 an over-budget caption source is a named gap",
              {"a.md", "b.tex"} <= set(rep2.get("unparsed") or []), str(rep2.get("unparsed")))
        check("F07 an over-budget manuscript source is a named gap",
              "a.md" in (lengths.get("unparsed") or []),
              str(lengths.get("unparsed")))
        check("F07 the prose helper refuses an over-budget file",
              pp.text_source_paragraphs(d / "a.md") == [])
    finally:
        pp.MAX_JSON_BYTES = old


# ---------------------------------------------------------------------------
# F08 -- Frontiers excludes table CONTENTS
# ---------------------------------------------------------------------------
def test_f08() -> None:
    print("\n== F08: Frontiers table contents are outside the count ==")
    d = scratch("fixbugs1029_f08_")
    doc = docx.Document()
    doc.add_paragraph("Introduction")
    doc.add_paragraph("One two three four five")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "six seven eight"
    table.cell(0, 1).text = "nine ten eleven"
    doc.save(d / "m.docx")
    fr = pp.scan_lengths_in_sources(
        [(d, "", ())], profile=pp.load_venue_profile("frontiers-in-immunology"))
    nb = pp.scan_lengths_in_sources(
        [(d, "", ())], profile=pp.load_venue_profile("nature-biotechnology"))
    fr_main = next((r.get("words") for r in fr.get("rows") or []
                    if r.get("section") == "main text"), None)
    nb_main = next((r.get("words") for r in nb.get("rows") or []
                    if r.get("section") == "main text"), None)
    check("F08 Frontiers counts the body but not the table cells", fr_main == 5, str(fr_main))
    check("F08 NBT (no table-contents rule) still counts them", nb_main == 11, str(nb_main))


# ---------------------------------------------------------------------------
# F09 -- a TeX table caption is not a figure legend
# ---------------------------------------------------------------------------
def test_f09() -> None:
    print("\n== F09: M18 does not file a table caption as a figure legend ==")
    d = scratch("fixbugs1029_f09_")
    _write(d / "t.tex", "\\begin{table}\\caption{Table only caption words here.}"
                        "\\end{table}\n")
    rep = pp.scan_captions_in_sources([(d, "", ())])
    check("F09 a table-only document has no figure legend", rep.get("count") == 0, str(rep)[:300])
    _write(d / "f.tex", "\\begin{figure}\\caption{Figure one caption words here.}"
                        "\\end{figure}\n")
    rep2 = pp.scan_captions_in_sources([(d, "", ())])
    check("F09 a real figure caption is still counted", rep2.get("count") == 1, str(rep2)[:300])


# ---------------------------------------------------------------------------
# F10 -- a payload file over the budget is skipped by both token readers
# ---------------------------------------------------------------------------
def test_f10() -> None:
    print("\n== F10: revision token has a payload byte budget ==")
    d = scratch("fixbugs1029_f10_")
    _write(d / "a.txt", "1234567890")
    old_pp, old_rt = pp.MAX_PAYLOAD_BYTES, rt.MAX_PAYLOAD_BYTES
    pp.MAX_PAYLOAD_BYTES = 1
    rt.MAX_PAYLOAD_BYTES = 1
    try:
        a = pp.revision_token_for_dir(d)
        b = rt.revision_token(d)
        check("F10 the pipeline token refuses an over-budget payload",
              a.get("token") == "" and a.get("files") == 0, str(a))
        check("F10 the skill token refuses it too", b.get("token") == "", str(b))
    finally:
        pp.MAX_PAYLOAD_BYTES, rt.MAX_PAYLOAD_BYTES = old_pp, old_rt


# ---------------------------------------------------------------------------
# F11 -- a symlinked package ROOT is not package content
# ---------------------------------------------------------------------------
def test_f11() -> None:
    print("\n== F11: a symlinked package root is refused ==")
    d = scratch("fixbugs1029_f11_")
    outside = d / "outside"
    outside.mkdir()
    _write(outside / "secret.txt", "outside bytes")
    pkg = d / "pkg"
    pkg.symlink_to(outside)
    check("F11 hash_manifest does not follow the root link",
          pp.hash_manifest(pkg) == {"files": {}, "count": 0}, str(pp.hash_manifest(pkg)))
    check("F11 the pipeline token does not follow it",
          pp.revision_token_for_dir(pkg).get("files") == 0)
    check("F11 the skill token does not follow it", rt.revision_token(pkg).get("files") == 0)


# ---------------------------------------------------------------------------
# F12/F13/F14/F15 -- JSON reader hardening
# ---------------------------------------------------------------------------
def test_f12_f15() -> None:
    print("\n== F12-F15: JSON reader hardening ==")
    d = scratch("fixbugs1029_json_")
    bad = d / "bad.json"
    bad.write_bytes(b'{"a": "\xff\xfe"}')
    try:
        got = pp.read_json(bad, revive=False, lenient=True)
        check("F12 invalid UTF-8 returns None", got is None, repr(got))
    except UnicodeDecodeError as exc:                                   # noqa: BLE001
        check("F12 invalid UTF-8 returns None", False, f"raised {exc}")
    deep = d / "deep.json"
    deep.write_text("[" * 1200 + "0" + "]" * 1200)
    try:
        got = pp.read_json(deep)
        check("F13 over-deep JSON returns None, never RecursionError", got is None, repr(got)[:80])
    except RecursionError as exc:                                       # noqa: BLE001
        check("F13 over-deep JSON returns None, never RecursionError", False, str(exc))
    later = pp._json_from_text('{"x": 0}\nprose { oops\n{"a": 1}\n', True)
    check("F14 a later complete document is not hidden by an earlier {}", later == {"a": 1},
          repr(later))
    target = d / "target.json"
    target.write_text('{"ok": true}')
    link = d / "link.json"
    link.symlink_to(target)
    real = pp.json_file_too_big
    pp.json_file_too_big = lambda _p: False
    try:
        check("F15 read_json refuses a symlink at the path (O_NOFOLLOW)",
              pp.read_json(link) is None)
    finally:
        pp.json_file_too_big = real


# ---------------------------------------------------------------------------
# F20 -- the previous registry survives a failed hardlink
# ---------------------------------------------------------------------------
def test_f20() -> None:
    print("\n== F20: save_state keeps a .prev even when os.link fails ==")

    class FakeCtx:
        pass

    d = scratch("fixbugs1029_f20_")
    ctx = FakeCtx()
    ctx.root = d
    ctx.state_path = d / "state.json"
    ctx.state = {"version": 1, "runs": {}}
    ctx.state_path.write_text('{"old": true}', encoding="utf-8")
    real_link = pp.os.link
    pp.os.link = lambda *_a, **_k: (_ for _ in ()).throw(OSError("no hardlinks"))
    try:
        pp.Ctx.save_state(ctx)
    finally:
        pp.os.link = real_link
    prev = pp.state_prev_path(ctx.state_path)
    check("F20 the previous registry is still there", prev.is_file()
          and prev.read_text(encoding="utf-8") == '{"old": true}', str(prev))
    check("F20 the new registry was written", "version" in ctx.state_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# F22 -- one unreadable file does not abort the corpus identity
# ---------------------------------------------------------------------------
def test_f22() -> None:
    print("\n== F22: an unreadable file is a sentinel, not a crash ==")
    d = scratch("fixbugs1029_f22_")
    _write(d / "a.txt", "x")
    os.chmod(d / "a.txt", 0)
    try:
        man = pp.manifest_for_sources([(d, "", ())])
        fp = pp.corpus_content_set_fingerprint([(d, "", ())])
        check("F22 the manifest reports the sentinel", man["files"].get("a.txt") == "<unreadable>",
              str(man))
        check("F22 the fingerprint completes", isinstance(fp, str) and len(fp) == 64, fp)
    except PermissionError as exc:                                      # noqa: BLE001
        check("F22 the manifest reports the sentinel", False, str(exc))
    finally:
        os.chmod(d / "a.txt", 0o600)


# ---------------------------------------------------------------------------
# F25 -- renderer output is bounded
# ---------------------------------------------------------------------------
def test_f25() -> None:
    print("\n== F25: renderer stdout is capped ==")
    old = pp.MAX_TOOL_OUTPUT_BYTES
    pp.MAX_TOOL_OUTPUT_BYTES = 1000
    try:
        try:
            pp._run_render_subprocess(
                [sys.executable, "-c", "print('x' * 5000)"], timeout=10)
            check("F25 an over-budget render raises ToolOutputOverBudget", False)
        except pp.ToolOutputOverBudget:
            check("F25 an over-budget render raises ToolOutputOverBudget", True)
    finally:
        pp.MAX_TOOL_OUTPUT_BYTES = old


# ---------------------------------------------------------------------------
# F26 -- pdftotext output is bounded
# ---------------------------------------------------------------------------
def test_f26() -> None:
    print("\n== F26: pdftotext goes through run_bounded ==")
    calls = []
    real_rb, real_which = pp.run_bounded, pp.shutil.which
    pp.shutil.which = lambda name: "/usr/bin/pdftotext" if name == "pdftotext" else None

    def fake_run(argv, timeout, cwd=None, env=None):
        calls.append(argv)
        return 0, b"PDF TEXT", b""

    pp.run_bounded = fake_run
    try:
        got = pp._pdf_text_info(WS / "any.pdf")
        check("F26 _pdf_text_info uses the bounded runner", got == ("PDF TEXT", "") and len(calls) == 1,
              f"{got} {calls}")
        got2 = pp.feedback_text_of(WS / "any.pdf")
        check("F26 feedback_text_of uses the bounded runner",
              got2[0] == "PDF TEXT" and len(calls) == 2, f"{got2} {calls}")
    finally:
        pp.run_bounded, pp.shutil.which = real_rb, real_which


# ---------------------------------------------------------------------------
# F27 -- the dsh event stream is echoed, not buffered
# ---------------------------------------------------------------------------
def test_f27() -> None:
    print("\n== F27: dsh stream is streamed ==")
    d = scratch("fixbugs1029_f27_")
    server = d / "dsh.py"
    _write(server, "import json,sys\n"
                   "for i in range(3):\n"
                   "    print(json.dumps({'type':'event','i':i}), flush=True)\n"
                   "print(json.dumps({'type':'turn_end','status':'error'}), flush=True)\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc, failed = qn.run_dsh_streaming([sys.executable, str(server)], {})
    check("F27 the terminal turn_end is still parsed", failed is True, str(failed))
    check("F27 every line was echoed", len(buf.getvalue().splitlines()) == 4,
          str(len(buf.getvalue().splitlines())))
    src = (WS / "paper_qwen_agent.py").read_text(encoding="utf-8")
    check("F27 the old whole-stream PIPE capture is gone",
          "subprocess.run(cmd, stdin=sys.stdin, stdout=subprocess.PIPE" not in src
          and "run_dsh_streaming(cmd, env)" in src)


# ---------------------------------------------------------------------------
# F28 -- MCP env and cwd are honoured
# ---------------------------------------------------------------------------
def test_f28() -> None:
    print("\n== F28: MCP env/cwd are parsed and launched ==")
    d = scratch("fixbugs1029_f28_")
    server = d / "srv.py"
    _write(server, "import json,sys,os\n"
                   "for line in sys.stdin:\n"
                   "    line=line.strip()\n"
                   "    if not line: continue\n"
                   "    try: msg=json.loads(line)\n"
                   "    except ValueError: continue\n"
                   "    if msg.get('method')=='initialize':\n"
                   "        print(json.dumps({'jsonrpc':'2.0','id':msg.get('id'),'result':{}}),flush=True)\n"
                   "    elif msg.get('method')=='tools/call':\n"
                   "        txt='%s|%s' % (os.environ.get('F28_TEST',''), os.getcwd())\n"
                   "        print(json.dumps({'jsonrpc':'2.0','id':msg.get('id'),'result':"
                   "{'content':[{'type':'text','text':txt}]}}),flush=True)\n")
    cfg = d / "config.toml"
    _write(cfg, '[mcp_servers.x]\ncommand = "%s"\nargs = ["%s"]\n'
                'env = { F28_TEST = "yes" }\ncwd = "%s"\n'
           % (sys.executable, server, d))
    real = pp.codex_config_path
    pp.codex_config_path = lambda: cfg
    try:
        spec = pp.mcp_server_spec("x")
        check("F28 the spec carries env and cwd",
              spec.get("env") == {"F28_TEST": "yes"} and spec.get("cwd") == str(d), str(spec))
        rep = pp.mcp_stdio_tool_call(spec, "t", {}, timeout=20)
        text = ""
        with contextlib.suppress(Exception):
            text = rep["result"]["content"][0]["text"]
        check("F28 the server actually received them", text == f"yes|{d}", f"{rep}")
    finally:
        pp.codex_config_path = real
    _write(cfg, '[mcp_servers.x]\ncommand = "node"\nenv = { FOO = }\n')
    pp.codex_config_path = lambda: cfg
    try:
        check("F28 a malformed env block is unreadable", pp.mcp_server_spec("x") == {})
    finally:
        pp.codex_config_path = real


# ---------------------------------------------------------------------------
# F29 -- a timed-out MCP server's grandchildren are killed
# ---------------------------------------------------------------------------
def test_f29() -> None:
    print("\n== F29: MCP timeout kills the whole tree ==")
    d = scratch("fixbugs1029_f29_")
    server = d / "srv.py"
    _write(server, "import subprocess,sys,time\n"
                   "marker=sys.argv[1]\n"
                   "subprocess.Popen([sys.executable,'-c',"
                   "'import time,pathlib,sys; time.sleep(2); "
                   "pathlib.Path(sys.argv[1]).write_text(\"survived\")',marker])\n"
                   "time.sleep(60)\n")
    marker = d / "marker.txt"
    start = time.monotonic()
    rep = pp.mcp_stdio_tool_call({"command": sys.executable, "args": [str(server), str(marker)]},
                                 "x", {}, timeout=1)
    elapsed = time.monotonic() - start
    time.sleep(3)
    check("F29 the call reports failure promptly", not rep.get("ok") and elapsed < 2.5,
          f"{elapsed:.2f}s")
    check("F29 the grandchild did not survive to write", not marker.exists(), str(marker))


# ---------------------------------------------------------------------------
# F31 -- decide-side scanners do not follow file symlinks
# ---------------------------------------------------------------------------
def test_f31() -> None:
    print("\n== F31: package scanners ignore file symlinks ==")
    d = scratch("fixbugs1029_f31_")
    pkg = d / "pkg"
    pkg.mkdir()
    outside = d / "outside.md"
    _write(outside, "REVISION_REPORT is an internal pipeline artifact.\n")
    (pkg / "link.md").symlink_to(outside)
    rows = pp.internal_artifact_rows(pkg)
    check("F31 a symlinked file is not read as package prose", rows == [], str(rows)[:300])
    rows2 = pp.non_submitted_reference_rows(pkg, ["code"])
    check("F31 PKG-2 does not scan a symlinked file", rows2 == [], str(rows2)[:300])


# ---------------------------------------------------------------------------
# F32 -- author READMEs are not manuscript prose
# ---------------------------------------------------------------------------
def test_f32() -> None:
    print("\n== F32: README files are not submission documents ==")
    d = scratch("fixbugs1029_f32_")
    pkg = d / "pkg"
    pkg.mkdir()
    _write(pkg / "main.md", "Intro text.\n")
    _write(pkg / "README.md", "# Methods\nFigure 1. A legend in the README.\n")
    rep = pp.scan_template_conformance([(pkg, "", ())],
                                       {"mandatory_sections": ["Methods"]})
    check("F32 the README is not a submission document",
          rep["found"]["documents"] == ["main.md"], str(rep["found"]))
    check("F32 README text cannot satisfy a section requirement",
          rep["missing_sections"] == ["Methods"], str(rep["missing_sections"]))
    caps = pp.scan_captions_in_sources([(pkg, "", ())])
    check("F32 the README contributes no caption",
          [c["document"] for c in caps["captions"]] == [], str(caps["captions"]))
    docs = [x[0] for x in pp.corpus_text_documents([(pkg, "", ())])]
    check("F32 the README is not corpus prose", docs == ["main.md"], str(docs))


# ---------------------------------------------------------------------------
# F33 -- the main manuscript's documentclass decides
# ---------------------------------------------------------------------------
def test_f33() -> None:
    print("\n== F33: the main manuscript's class decides ==")
    d = scratch("fixbugs1029_f33_")
    _write(d / "a_supp.tex", "\\documentclass{article}\n\\section{Methods}\nText.\n")
    _write(d / "main.tex", "\\documentclass{naturemag}\n\\section{Methods}\nText.\n")
    rep = pp.scan_template_conformance([(d, "", ())], {"documentclass": "naturemag"})
    check("F33 the supplement does not decide the class",
          rep["found"]["documentclass"] == "naturemag" and rep["class_ok"] is True,
          str(rep["found"]))


# ---------------------------------------------------------------------------
# F34 -- science compounds are not reply files
# ---------------------------------------------------------------------------
def test_f34() -> None:
    print("\n== F34: dose_response.txt is a manuscript ==")
    for name in ("dose_response.txt", "immune_response.md", "response_time.tex"):
        check(f"F34 {name} is manuscript prose", pp.is_non_manuscript_rel(name) is False)
    for name in ("ReviewerResponse.md", "reviewerresponse.md", "response_to_reviewers.md"):
        check(f"F34 {name} is a reply", pp.is_non_manuscript_rel(name) is True)


# ---------------------------------------------------------------------------
# F35 -- <area>.disabled is inert
# ---------------------------------------------------------------------------
def test_f35() -> None:
    print("\n== F35: a .disabled evidence area is never linked into a sandbox ==")
    d = scratch("fixbugs1029_f35_")
    root = d / "root"
    _write(root / "non_revised" / "raw_data.disabled" / "secret.txt", "SECRET")
    _write(root / "non_revised" / "main.md", "body\n")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.root = root
    ctx.pristine = root / "non_revised"
    dst = d / "sandbox"
    info = pp.ensure_pristine_input(ctx, dst)
    check("F35 the disabled area is not an evidence area",
          pp.evidence_areas_of(ctx.pristine) == [], str(pp.evidence_areas_of(ctx.pristine)))
    check("F35 no link is created", not (dst / "raw_data.disabled").exists()
          and "raw_data.disabled" not in (info.get("linked") or []), str(info))
    check("F35 it is not copied either", not (dst / "raw_data.disabled" / "secret.txt").exists())


# ---------------------------------------------------------------------------
# F36 -- orchestrator junk/README removals are not scoped-scope violations
# ---------------------------------------------------------------------------
def test_f36() -> None:
    print("\n== F36: junk/README removals are exempt from the scoped guard ==")
    d = scratch("fixbugs1029_f36_")
    sb = d / "sb"
    (sb / "base").mkdir(parents=True)
    (sb / "revised").mkdir()
    _write(sb / "base" / "main.md", "A\n")
    _write(sb / "revised" / "main.md", "A\n")
    (sb / "base" / ".DS_Store").write_bytes(b"junk")
    _write(sb / "base" / "README.md", "internal note\n")
    _write(sb / "revised" / "revision_report.json", "[]")
    errs = pp.scoped_scope_problems(None, sb, sb / "revised")
    check("F36 the orchestrator's strip/hold is not a document drop", errs == [], str(errs))


# ---------------------------------------------------------------------------
# F37/F61 -- review postcheck: symlinked artifact and duplicate coverage rows
# ---------------------------------------------------------------------------
def _review_fixture(d: Path, symlink_m25: bool = False):
    sb = d / "r1_review"
    (sb / "base").mkdir(parents=True)
    art = sb / "review" / "artifacts"
    art.mkdir(parents=True)
    table = "| item | disposition |\n|---|---|\n| x | OK - present |\n"
    parity = ["M25_artwork_parity.md", "M2_references.md", "M26_conventions.md",
              "M27_evidence_coverage.md", "M28_symmetry.md", "M29_caption_schema.md",
              "M30_hierarchy_reconciliation.md", "M31_artwork_legend.md",
              "M32_statistics.md", "M33_availability.md", "M34_source_data_coverage.md",
              "M35_disclosures.md", "M36_zotero_parity.md"]
    outside = d / "outside.md"
    outside.write_text(table, encoding="utf-8")
    for name in parity:
        p = art / name
        if symlink_m25 and name == "M25_artwork_parity.md":
            p.symlink_to(outside)
        else:
            p.write_text(table, encoding="utf-8")
    coverage = [{"check": c, "disposition": "clean -- basis: artifact"}
                for c in pp.REQUIRED_REVIEW_CHECKS]
    for c in ("M18", "M19", "M20", "M21", "M22", "M23", "M24", "M25", "M26",
              "M27", "M28", "M29", "J5", "M30", "M31", "M32", "M33", "M34",
              "M35", "M36"):
        coverage.append({"check": c, "disposition": "clean -- basis: artifact"})
    fj = {"submission_dir": "base", "findings": [], "coverage": coverage, "artifacts": {}}
    return sb, fj


def test_f37_f61() -> None:
    print("\n== F37/F61: review artifacts and coverage rows ==")
    d = scratch("fixbugs1029_f37_")
    sb, fj = _review_fixture(d, symlink_m25=True)
    errs, warns = [], []
    pp.check_review_contract(None, sb, fj, errs, warns, scope="full")
    check("F37 a symlinked parity artifact is a named error",
          any("M25_artwork_parity.md is missing or a symlink" in e for e in errs),
          str(errs)[:300])

    d2 = scratch("fixbugs1029_f61_")
    sb2, fj2 = _review_fixture(d2)
    fj2["coverage"].append({"check": "M1", "disposition": "2 findings -- see F-001"})
    errs2, warns2 = [], []
    pp.check_review_contract(None, sb2, fj2, errs2, warns2, scope="full")
    check("F61 a duplicate coverage row is rejected",
          any("more than once" in e and "'M1'" in e for e in errs2), str(errs2)[:300])


# ---------------------------------------------------------------------------
# F38 -- agent-written artifacts are read with the bounded reader
# ---------------------------------------------------------------------------
def test_f38() -> None:
    print("\n== F38: postcheck readers refuse symlinks / budget ==")
    d = scratch("fixbugs1029_f38_")
    target = d / "target.json"
    _write(target, '{"dispositions": []}')
    link = d / "audit.json"
    link.symlink_to(target)
    check("F38 repair JSON refuses a symlink", pp._repair_read_json(link) is None)
    problem = pp._structured_problem_for("audit.json", link)
    check("F38 structured output names the symlink", "symlink" in problem, str(problem))


# ---------------------------------------------------------------------------
# F39 -- bCs is read from styles and document defaults
# ---------------------------------------------------------------------------
def test_f39() -> None:
    print("\n== F39: bCs makes a run bold ==")
    check("F39 a docDefault bCs is bold",
          pf.run_is_bold({"@docDefaults": {"bCs": True}, "Normal": {"basedOn": None}},
                         "Normal", "<w:r><w:rPr></w:rPr></w:r>") is True)
    check("F39 a paragraph-style bCs is bold",
          pf.run_is_bold({"Normal": {"bCs": True, "basedOn": None}},
                         "Normal", "<w:r><w:rPr></w:rPr></w:r>") is True)
    check("F39 a character-style bCs is bold",
          pf.run_is_bold({"Normal": {"basedOn": None}, "Strong": {"bCs": True, "basedOn": None}},
                         "Normal", '<w:r><w:rPr><w:rStyle w:val="Strong"/></w:rPr></w:r>') is True)


# ---------------------------------------------------------------------------
# F40 -- a repeated heading in one sample is not two samples
# ---------------------------------------------------------------------------
def test_f40() -> None:
    print("\n== F40: official_skeleton counts samples, not headings ==")
    recs = [
        {"file": "a.tex", "format": "tex", "sha256": "a",
         "sections": [{"level": 1, "title": "Results"},
                      {"level": 1, "title": "Results"}]},
        {"file": "b.tex", "format": "tex", "sha256": "b",
         "sections": [{"level": 1, "title": "Methods"}]},
    ]
    rep = pp.official_skeleton(recs)
    check("F40 Results is present in one of two samples",
          next(s for s in rep["sections"] if s["title"] == "Results")["present"] == 1,
          str(rep["sections"]))
    check("F40 Results is therefore not mandatory", rep["mandatory_sections"] == [],
          str(rep["mandatory_sections"]))


# ---------------------------------------------------------------------------
# F44 -- page-number furniture is blank-page furniture
# ---------------------------------------------------------------------------
def test_f44() -> None:
    print("\n== F44: Page N / Page N of M is furniture ==")
    rep = pf.blank_pages_in_text("Page 1\n\nbody\fPage 2")
    check("F44 a page containing only 'Page 2' is blank", rep["blank_pages"] == [2], str(rep))
    rep2 = pf.blank_pages_in_text("Page 1 of 10\n\nbody\fPage 2 of 10")
    check("F44 'Page 2 of 10' is blank", rep2["blank_pages"] == [2], str(rep2))


# ---------------------------------------------------------------------------
# F45 -- redline_one_pair never raises when the backend's OUT vanished
# ---------------------------------------------------------------------------
def test_f45() -> None:
    print("\n== F45: redline_one_pair survives a copy failure ==")
    d = scratch("fixbugs1029_f45_")
    base, rev, out = d / "b.docx", d / "r.docx", d / "o.docx"
    base.write_bytes(b"x")
    rev.write_bytes(b"y")
    real_b, real_f = pp.builtin_tracked_changes, pp.redline_fidelity

    def fake_builtin(_b, _r, o):
        Path(o).write_bytes(b"PK")
        Path(o).unlink()                  # the backend reported success but OUT is gone
        return {"paragraphs_inserted": 1, "paragraphs_deleted": 0}

    pp.builtin_tracked_changes = fake_builtin
    pp.redline_fidelity = lambda _b, _r, _o: {
        "over_marked": True, "marked_words": 10, "minimal_words": 1}
    try:
        res = pp.redline_one_pair("auto", [], base, rev, out)
        check("F45 a failed save is an attempt, not a raise",
              res.get("ok") is False
              and any("could not be saved" in str(a.get("detail")) for a in res["attempts"]),
              str(res["attempts"][-2:]))
    finally:
        pp.builtin_tracked_changes, pp.redline_fidelity = real_b, real_f


# ---------------------------------------------------------------------------
# F46 -- repair-layout reports a write failure, never raises
# ---------------------------------------------------------------------------
def _tb4_docx(path: Path) -> None:
    tmp = path.with_suffix(".raw.docx")
    doc = docx.Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "A"
    table.cell(0, 1).text = "B"
    doc.save(tmp)
    with zipfile.ZipFile(tmp) as z:
        names = z.namelist()
        data = {n: z.read(n) for n in names}
    xml = data["word/document.xml"].decode("utf-8")
    changed = re.sub(r'<w:gridCol w:w="(\d+)"/>',
                     lambda m: '<w:gridCol w:w="%d"/>' % (int(m.group(1)) + 1000), xml)
    data["word/document.xml"] = changed.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, data[n])


def test_f46() -> None:
    print("\n== F46: repair-layout returns ok:false on a write failure ==")
    d = scratch("fixbugs1029_f46_")
    src = d / "src.docx"
    _tb4_docx(src)
    out = d / "outdir"
    out.mkdir()
    rep = pf.repair_layout_package(src, out)
    check("F46 an unwritable --out is a report, not a traceback",
          rep.get("ok") is False and "could not write/verify" in str(rep.get("error")),
          str(rep)[:300])


# ---------------------------------------------------------------------------
# F47 -- the adapter keeps a valid prior OUT when no engine can run
# ---------------------------------------------------------------------------
def test_f47() -> None:
    print("\n== F47: the redline adapter does not destroy a prior OUT ==")
    d = scratch("fixbugs1029_f47_")
    fake = d / "fakemod"
    fake.mkdir()
    _write(fake / "python_redlines.py", "x = 1\n")
    (d / "base.docx").write_bytes(b"base")
    (d / "revised.docx").write_bytes(b"rev")
    out = d / "out.docx"
    out.write_bytes(b"PRIOR")
    env = dict(os.environ, PYTHONPATH=str(fake))
    proc = subprocess.run([sys.executable, str(WS / "paper_redlines_adapter.py"),
                           str(d / "base.docx"), str(d / "revised.docx"), str(out)],
                          capture_output=True, text=True, cwd=str(d), env=env)
    check("F47 exit 5 when no interface exists", proc.returncode == 5, f"rc={proc.returncode}")
    check("F47 the previous redline is intact", out.read_bytes() == b"PRIOR", str(out))


# ---------------------------------------------------------------------------
# F49 -- scan-figures does not follow a symlinked image
# ---------------------------------------------------------------------------
def test_f49() -> None:
    print("\n== F49: scan-figures skips symlinked images ==")
    d = scratch("fixbugs1029_f49_")
    pkg = d / "pkg"
    pkg.mkdir()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AARAAI/wFgJ6kAAAAASUVORK5CYII=")
    (pkg / "Figure1.png").write_bytes(png)
    outside = d / "outside.png"
    outside.write_bytes(png)
    (pkg / "Figure2.png").symlink_to(outside)
    report = d / "r.json"
    proc = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), "scan-figures",
                           str(pkg), "--json", str(report)],
                          capture_output=True, text=True, cwd=str(WS))
    files = json.loads(report.read_text(encoding="utf-8")).get("files") if report.is_file() else []
    check("F49 the real image is scanned", any(f.endswith("Figure1.png") for f in files), str(files))
    check("F49 the symlinked image is not", not any("Figure2.png" in f for f in files), str(files))


# ---------------------------------------------------------------------------
# F58 -- accepts_any_journal must be a JSON boolean
# ---------------------------------------------------------------------------
def test_f58() -> None:
    print("\n== F58: a string 'false' does not accept any journal ==")
    prof = json.loads((WS / "venue_profiles" / "generic.json").read_text(encoding="utf-8"))
    prof["id"] = "x"
    prof["label"] = "X"
    prof["accepts_any_journal"] = "false"
    try:
        pp.normalize_venue_profile(prof)
        check("F58 a string 'false' is rejected", False)
    except pp.VenueProfileError as exc:
        check("F58 a string 'false' is rejected", "accepts_any_journal" in str(exc), str(exc))


# ---------------------------------------------------------------------------
# F60 -- the response letter must quote the reviewer verbatim
# ---------------------------------------------------------------------------
def test_f60() -> None:
    print("\n== F60: the response Comment quote is verified ==")
    d = scratch("fixbugs1029_f60_")
    sb, src = d / "r1_response", d / "r1_concerns"
    (sb / "response").mkdir(parents=True)
    (sb / "target").mkdir()
    (src / "concerns").mkdir(parents=True)
    _write(src / "concerns" / "JF_concerns.json", json.dumps({"concerns": [{
        "id": "C1", "quote": "The treated group improved markedly in this study.",
        "summary": "x"}]}))
    _write(sb / "response" / "response_map.json", json.dumps({"rows": [{
        "id": "C1", "status": "addressed", "response": "We revised it.", "changes": []}]}))
    _write(sb / "response" / "RESPONSE_TO_REVIEWERS.md",
           '## C1 - x\n**Comment:** "The treated group got much better."\n**Response:** ok\n')

    class Ctx:
        cfg = {}

        def sandbox_of(self, rec):
            return sb if rec.get("id") == "r1_response" else src

        def run(self, _rid):
            return {"id": "r1_concerns", "sandbox": str(src)}

    rec = {"id": "r1_response", "round": 1, "kind": "response"}
    saved = {}
    for name in ("original_submission_staging_problems", "structured_output_problems",
                 "inherited_structured_output_notes", "input_mismatches", "_marker_checks"):
        saved[name] = getattr(pp, name)
        setattr(pp, name, (lambda *a, **k: None) if name == "_marker_checks"
                else (lambda *a, **k: []))
    try:
        _ok, errs, _warns, _extra = pp.postcheck_response(Ctx(), rec)
        check("F60 a paraphrased quote is rejected",
              any("not verbatim" in e for e in errs), str(errs)[:300])
        _write(sb / "response" / "RESPONSE_TO_REVIEWERS.md",
               '## C1 - x\n**Comment:** "The treated group improved markedly in this study."'
               '\n**Response:** ok\n')
        _ok2, errs2, _w2, _x2 = pp.postcheck_response(Ctx(), rec)
        check("F60 the verbatim quote passes this check",
              not any("verbatim" in e or "Comment" in e for e in errs2), str(errs2)[:300])
    finally:
        for name, fn in saved.items():
            setattr(pp, name, fn)


# ---------------------------------------------------------------------------
# F62 -- a post-parse usage error exits 2
# ---------------------------------------------------------------------------
def test_f62() -> None:
    print("\n== F62: usage errors exit 2 ==")
    d = scratch("fixbugs1029_f62_")
    (d / "src").mkdir()
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                           "--source", str(d / "src"), "--root", str(d / "root"),
                           "--rounds", "0"],
                          capture_output=True, text=True, cwd=str(WS))
    check("F62 --rounds 0 is a usage error (exit 2)",
          proc.returncode == 2 and "--rounds must be >= 1" in proc.stderr,
          f"rc={proc.returncode} {proc.stderr[-160:]}")


# ---------------------------------------------------------------------------
# F65 -- an unreadable manuscript is unparsed, not a rendering
# ---------------------------------------------------------------------------
def test_f65() -> None:
    print("\n== F65: an unreadable .md is a named gap ==")
    d = scratch("fixbugs1029_f65_")
    _write(d / "a.md", "Body text\n")
    os.chmod(d / "a.md", 0)
    try:
        rep = pp.scan_lengths_in_sources(
            [(d, "", ())], profile=pp.load_venue_profile("nature-biotechnology"))
        check("F65 it is in unparsed", "a.md" in (rep.get("unparsed") or []), str(rep.get("unparsed")))
        check("F65 it is not filed as a rendering", "a.md" not in (rep.get("skipped") or []),
              str(rep.get("skipped")))
    finally:
        os.chmod(d / "a.md", 0o600)


# ---------------------------------------------------------------------------
# F68 -- the run-log trim is unconditional
# ---------------------------------------------------------------------------
def test_f68() -> None:
    print("\n== F68: run_logs are always trimmed ==")

    class FakeCtx:
        pass

    d = scratch("fixbugs1029_f68_")
    ctx = FakeCtx()
    ctx.root = d
    ctx.state_path = d / "state.json"
    ctx.state = {"run_logs": [f"log{i}" for i in range(25)]}
    ctx.state_path.write_text("{}", encoding="utf-8")
    real_log = pp.CURRENT_RUN_LOG
    pp.CURRENT_RUN_LOG = "log0"          # already recorded: the old trim never ran
    try:
        pp.Ctx.save_state(ctx)
    finally:
        pp.CURRENT_RUN_LOG = real_log
    logs = ctx.state["run_logs"]
    check("F68 the registry is trimmed to 20", len(logs) == 20, str(len(logs)))
    check("F68 the newest log is kept", logs[-1] == "log24", str(logs[-3:]))


# ---------------------------------------------------------------------------
# F75 -- template conformance reads package text with the bounded reader
# ---------------------------------------------------------------------------
def test_f75() -> None:
    print("\n== F75: scan_template_conformance is bounded ==")
    d = scratch("fixbugs1029_f75_")
    _write(d / "main.tex", "\\documentclass{naturemag}\n\\section{Methods}\nBody.\n")
    old = pp.MAX_JSON_BYTES
    pp.MAX_JSON_BYTES = 8
    try:
        rep = pp.scan_template_conformance([(d, "", ())], {"documentclass": "naturemag"})
        check("F75 an over-budget source is a named gap",
              "main.tex" in (rep.get("unparsed") or []), str(rep.get("unparsed")))
    finally:
        pp.MAX_JSON_BYTES = old


# ---------------------------------------------------------------------------
# F88 -- only a structured ledger row authorises a scoped edit
# ---------------------------------------------------------------------------
def test_f88() -> None:
    print("\n== F88: a quoted sentence does not authorise an edit ==")
    d = scratch("fixbugs1029_f88_")
    sb = d / "sb"
    (sb / "base").mkdir(parents=True)
    (sb / "revised").mkdir()
    _write(sb / "base" / "main.docx", "A")
    _write(sb / "revised" / "main.docx", "B")
    _write(sb / "revised" / "revision_report.json", json.dumps({"findings": [{
        "id": "F1", "evidence": "the reviewer said main.docx is unclear"}]}))
    errs = pp.scoped_scope_problems(None, sb, sb / "revised")
    check("F88 prose mention is not a ledger row", any("no structured row" in e for e in errs),
          str(errs))
    _write(sb / "revised" / "revision_report.json", json.dumps([{
        "id": "F1", "verdict": "fixed", "files": ["main.docx"]}]))
    check("F88 a structured files row authorises it",
          pp.scoped_scope_problems(None, sb, sb / "revised") == [])
    _write(sb / "revised" / "revision_report.json", json.dumps({
        "F1": {"verdict": "fixed", "file": "main.docx"}}))
    check("F88 a mapping keyed by finding id authorises it",
          pp.scoped_scope_problems(None, sb, sb / "revised") == [])
    _write(sb / "revised" / "revision_report.json",
           "Here is the ledger:\n```json\n" + json.dumps([{
               "id": "F1", "verdict": "fixed", "files": ["main.docx"]}]) + "\n```\n")
    check("F88 a lenient agent ledger authorises it",
          pp.scoped_scope_problems(None, sb, sb / "revised") == [])


# ---------------------------------------------------------------------------
# F89 -- every PKG class is represented before the global cap
# ---------------------------------------------------------------------------
def test_f89() -> None:
    print("\n== F89: contradiction classes share the cap ==")
    d = scratch("fixbugs1029_f89_")
    names = ("ai_disclosure_contradiction_rows", "truncated_identifier_rows",
             "unit_of_analysis_rows", "affinity_definition_rows")
    saved = {n: getattr(pp, n) for n in names}
    try:
        for n in names:
            setattr(pp, n, (lambda _texts=None, limit=20, _n=n:
                            [{"rule": _n[:3], "n": i} for i in range(10)]))
        rows = pp.package_contradiction_rows(d, texts=[], limit=4)
        rules = [r["rule"] for r in rows]
        check("F89 every detector reaches the capped list", len(set(rules)) == 4, str(rules))
    finally:
        for n, fn in saved.items():
            setattr(pp, n, fn)


# ---------------------------------------------------------------------------
# F90 -- PKG-4 with no figure files is a GAP, not a clean scan
# ---------------------------------------------------------------------------
def test_f90() -> None:
    print("\n== F90: PKG-4 reports a coverage gap ==")
    d = scratch("fixbugs1029_f90_")
    doc = docx.Document()
    doc.add_paragraph("Fig. 1 shows the design.")
    doc.save(d / "main.docx")
    rows = pp.package_display_item_rows(d, ["code"])
    check("F90 the empty result carries a gap row",
          len(rows) == 1 and rows[0].get("gap") is True
          and "NOT evaluated" in rows[0].get("detail", ""), str(rows))


# ---------------------------------------------------------------------------
# deletion audit + M30 seed: the evaluation run's two real process gaps
# ---------------------------------------------------------------------------
def test_deletion_audit_and_m30_seed() -> None:
    print("\n== deletion audit / M30 seed ==")
    d = scratch("fixbugs1029_delaudit_")
    base, revised = d / "base", d / "revised"
    base.mkdir()
    revised.mkdir()
    _write(base / "main.md",
           "# Results\n\n"
           "This base paragraph carries a fact that must survive the revision audit "
           "and cannot be silently removed.\n\n"
           "This duplicate paragraph should be reported as a removed duplicate, not "
           "as an unexplained deletion.\n")
    _write(revised / "main.md", "# Results\n\nA different paragraph survives here.\n")
    rows = pp.deletion_audit_rows(base, revised)
    check("the deletion audit finds the removed fact-bearing paragraphs",
          len(rows) == 2 and all(r.get("paragraph") for r in rows), str(rows))
    check("a section heading is not a deletion row",
          pp._deleted_para_candidate("# Results\n" + "word " * 30) == "")
    check("a deleted figure caption is auditable",
          bool(pp._deleted_para_candidate(
              "**Figure 1.** Seedling density in thinned and control plots, with the "
              "95% confidence interval shown for every block.")))
    check("a short fact sentence is auditable",
          bool(pp._deleted_para_candidate(
              "We drank the species of every seedling in the field book.")))
    (d / "sb" / "revision_audit").mkdir(parents=True)
    _write(d / "sb" / "revision_audit" / "DELETED_PARAGRAPHS.md",
           pp.deletion_audit_markdown(rows))
    check("an undisposed deletion table is a problem",
          bool(pp.deletion_audit_problems(d / "sb")),
          str(pp.deletion_audit_problems(d / "sb")))
    text = pp.deletion_audit_markdown(rows).replace(
        "|  |", "| OK — duplicate/artifact checked; no fact lost |", 1)
    text = text.replace("|  |", "| fact removed — RP-001; restore the fact |", 1)
    _write(d / "sb" / "revision_audit" / "DELETED_PARAGRAPHS.md", text)
    check("a disposed deletion table passes",
          pp.deletion_audit_problems(d / "sb") == [],
          str(pp.deletion_audit_problems(d / "sb")))
    check("a 'fact removed' disposition without a plan row is rejected",
          any("no row with that id" in p
              for p in pp.deletion_audit_problems(d / "sb", plan_ids=[])),
          str(pp.deletion_audit_problems(d / "sb", plan_ids=[])))
    check("a 'fact removed' disposition with its plan row passes",
          pp.deletion_audit_problems(d / "sb", plan_ids=["RP-001"]) == [],
          str(pp.deletion_audit_problems(d / "sb", plan_ids=["RP-001"])))
    check("a seed row removed from the audit is rejected",
          any("seed listed" in p
              for p in pp.deletion_audit_problems(d / "sb", expected_rows=3)),
          str(pp.deletion_audit_problems(d / "sb", expected_rows=3)))
    expected = [r["paragraph"] for r in rows]
    check("the seeded paragraph identities pass",
          pp.deletion_audit_problems(d / "sb", expected_paragraphs=expected) == [],
          str(pp.deletion_audit_problems(d / "sb", expected_paragraphs=expected)))
    replaced = text.replace(rows[0]["paragraph"],
                            "A replacement row that was never in the seed.", 1)
    _write(d / "sb" / "revision_audit" / "DELETED_PARAGRAPHS.md", replaced)
    check("a replaced seed row is rejected",
          any("no longer carries" in p
              for p in pp.deletion_audit_problems(d / "sb",
                                                  expected_paragraphs=expected)),
          str(pp.deletion_audit_problems(d / "sb",
                                         expected_paragraphs=expected)))
    check("the M30 seed pre-disposes a no-producer row",
          pp.m30_seed_disposition(
              {"candidate producer": "(no shipped table column matches this sentence)"}
          ).startswith("unable — no shipped producer"))
    check("the M30 seed leaves a real producer for the agent",
          pp.m30_seed_disposition({"candidate producer": "raw_data/x.csv:count"}) == "")
    table = pp._evidence_artifact_table(
        [{"a": "v", "disposition": "unable — no shipped producer in the corpus"}],
        ["a"], "none")
    check("the M30 table carries the seeded disposition",
          "unable — no shipped producer in the corpus" in table, table)
    check("the audit prompt names the deletion table",
          "DELETED_PARAGRAPHS.md" in pp.revision_audit_prompt(d / "sb", "r1", 1))


def main() -> int:
    tests = [
        test_f03, test_f04, test_f05, test_f06, test_f07, test_f08, test_f09,
        test_f10, test_f11, test_f12_f15, test_f20, test_f22, test_f25, test_f26,
        test_f27, test_f28, test_f29, test_f31, test_f32, test_f33, test_f34,
        test_f35, test_f36, test_f37_f61, test_f38, test_f39, test_f40, test_f44,
        test_f45, test_f46, test_f47, test_f49, test_f58, test_f60, test_f62,
        test_f65, test_f68, test_f75, test_f88, test_f89, test_f90,
        test_deletion_audit_and_m30_seed,
    ]
    for fn in tests:
        try:
            fn()
        except Exception as exc:                                        # noqa: BLE001
            check(f"{fn.__name__} completed", False, f"{type(exc).__name__}: {exc}")
    cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s): {FAILS}")
        return 1
    print(f"OK {len(tests)} test group(s), all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

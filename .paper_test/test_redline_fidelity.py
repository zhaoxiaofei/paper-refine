#!/usr/bin/env python3
"""The redline fidelity round (2026-10-14 reports).

Two defects the operator reported on the 2026-10-14 tracking copies, and the
grader this suite pins for each:

  * the CNB main-text redline showed far more changed words than the revision
    really made -- `docx-trackdiff` rewrites a WHOLE paragraph as delete+insert
    whenever it cannot diff the runs one segment at a time, and a Word paragraph
    carries `w:lastRenderedPageBreak` inside its single text run, so a ten-word
    edit in such a paragraph was marked as 230 words deleted + 239 inserted. The
    redline chain now MEASURES every attempt (`redline_fidelity`) against the
    least a faithful redline needs, passes an over-marking backend over for the
    next one under `--tool auto`, and keeps the least-marked result;
  * the NeoHetero main-text redline LOST the correspondence block's soft line
    breaks (SHIFT+ENTER `<w:br/>`): the built-in writer rebuilt a changed
    paragraph from plain text. It now walks the diff op by op and keeps every
    non-text inline element in place -- while ALSO guaranteeing that accepting
    all changes reproduces the revised paragraph and rejecting all changes
    reproduces the base paragraph.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_redline", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_redline"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


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


def make_docx(path: Path, paragraphs: list) -> None:
    """`paragraphs` = list of raw `<w:p>` XML strings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}><w:body>'
                   + "".join(paragraphs) + "</w:body></w:document>")


def para(text: str, brs: int = 0, page_break: bool = False) -> str:
    runs = ""
    if page_break:
        runs += "<w:r><w:lastRenderedPageBreak/><w:t xml:space=\"preserve\">" + text \
                + "</w:t></w:r>"
        return f"<w:p>{runs}</w:p>"
    for i, chunk in enumerate(text.split("|")):
        prefix = "<w:br/>" if (brs and i) else ""
        runs += f'<w:r>{prefix}<w:t xml:space="preserve">{chunk}</w:t></w:r>'
    return f"<w:p>{runs}</w:p>"


def body_views(docx: Path):
    """(base-view texts, accept-all texts, reject-all texts) of the BODY paragraphs."""
    body = ET.fromstring(zipfile.ZipFile(docx).read("word/document.xml")).find(W + "body")
    plain, accept, reject = [], [], []
    for p in body.findall(W + "p"):
        plain.append(nb._para_text(p))
        a, r = [], []
        for ch in list(p):
            if ch.tag == W + "ins":
                a.append("".join(t.text or "" for t in ch.iter(W + "t")))
            elif ch.tag == W + "del":
                r.append("".join(t.text or "" for t in ch.iter(W + "delText")))
            else:
                for t in ch.iter(W + "t"):
                    a.append(t.text or "")
                    r.append(t.text or "")
        accept.append("".join(a))
        reject.append("".join(r))
    return plain, accept, reject


def flat(texts):
    return [t for t in texts if t and t.strip()]


def para_views(p):
    """(accept, reject) of ONE paragraph, with `<br>` kept in place.

    The text-only views above cannot see WHERE a soft line break landed, and
    the op-ordered writer once emitted the breaks at the end of the piece.
    """
    acc, rej = [], []
    for ch in list(p):
        if ch.tag == W + "ins":
            for el in ch.iter():
                if el.tag == W + "t":
                    acc.append(el.text or "")
                elif el.tag == W + "br":
                    acc.append("<br>")
        elif ch.tag == W + "del":
            for el in ch.iter():
                if el.tag == W + "delText":
                    rej.append(el.text or "")
                elif el.tag == W + "br":
                    rej.append("<br>")
        else:
            for el in ch.iter():
                if el.tag == W + "t":
                    acc.append(el.text or "")
                    rej.append(el.text or "")
                elif el.tag == W + "br":
                    acc.append("<br>")
                    rej.append("<br>")
    return "".join(acc), "".join(rej)


def test_builtin_writer_keeps_soft_breaks():
    print()
    print("== the built-in writer keeps soft line breaks and both views ==")
    tmp = scratch("paper_redline_breaks_")
    base = tmp / "base.docx"
    rev = tmp / "rev.docx"
    make_docx(base, [
        para("* Correspondence:|Zhen Xie, lead contact|zhenxie@tsinghua.edu.cn", brs=1),
        para("Unchanged paragraph."),
        para("A sentence with a small edit|that continues here.", brs=1),
    ])
    make_docx(rev, [
        para("* Correspondence:|Zhen Xie|zhenxie@tsinghua.edu.cn", brs=1),
        para("Unchanged paragraph."),
        para("A sentence with a small fix|that continues here.", brs=1),
    ])
    out = tmp / "track.docx"
    nb.builtin_tracked_changes(base, rev, out)
    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    ins_br = sum(m.count("<w:br") for m in
                 __import__("re").findall(r"<w:ins(?=[\s>])[\s\S]*?</w:ins>", xml))
    del_br = sum(m.count("<w:br") for m in
                 __import__("re").findall(r"<w:del(?=[\s>])[\s\S]*?</w:del>", xml))
    check("the redline carries the soft line breaks (SHIFT+ENTER) in both streams",
          ins_br >= 2 and del_br >= 2, f"breaks total={xml.count('<w:br')} ins={ins_br} del={del_br}")
    plain, accept, reject = body_views(out)
    _, base_texts, base_reject = body_views(base)
    _, rev_texts, rev_accept = body_views(rev)
    check("accepting every change reproduces the revised document",
          flat(accept) == flat(rev_texts), str(accept)[:200])
    check("rejecting every change reproduces the base document",
          flat(reject) == flat(base_texts), str(reject)[:200])
    check("the correspondence paragraph is marked at the word level, not wholesale",
          "lead contact" not in accept[0] and "lead contact" in reject[0]
          and "Zhen Xie" in accept[0], accept[0])
    check("the unchanged paragraph is copied verbatim",
          accept[1] == reject[1] == "Unchanged paragraph.")
    p0 = ET.fromstring(zipfile.ZipFile(out).read("word/document.xml")).find(W + "body")[0]
    acc0, rej0 = para_views(p0)
    check("each soft line break keeps its own place (not moved to the piece's end)",
          acc0 == "* Correspondence:<br>Zhen Xie<br>zhenxie@tsinghua.edu.cn",
          acc0)
    check("the rejected view keeps the deleted break in its place too",
          rej0 == "* Correspondence:<br>Zhen Xie, lead contact<br>zhenxie@tsinghua.edu.cn",
          rej0)


def test_builtin_writer_handles_page_break_runs():
    print()
    print("== a paragraph with w:lastRenderedPageBreak is still diffed word by word ==")
    tmp = scratch("paper_redline_prb_")
    base = tmp / "base.docx"
    rev = tmp / "rev.docx"
    long_tail = " and the rest of the sentence stays exactly as it was in the base document."
    make_docx(base, [para("The first page paragraph ends here." + long_tail,
                          page_break=True)])
    make_docx(rev, [para("The first page paragraph closes here." + long_tail,
                         page_break=True)])
    out = tmp / "track.docx"
    nb.builtin_tracked_changes(base, rev, out)
    fidelity = nb.redline_fidelity(base, rev, out)
    check("the markup is not over-marked (marked ~ minimal)",
          not fidelity["over_marked"] and fidelity["marked_words"] <= 6,
          str(fidelity))
    plain, accept, reject = body_views(out)
    check("accept-all and reject-all both reproduce their side",
          accept[0].startswith("The first page paragraph closes here.")
          and reject[0].startswith("The first page paragraph ends here."),
          f"accept={accept[0][:60]!r} reject={reject[0][:60]!r}")


def test_fidelity_check_flags_whole_paragraph_markup():
    print()
    print("== the fidelity check flags whole-paragraph markup for a small edit ==")
    tmp = scratch("paper_redline_fid_")
    base = tmp / "base.docx"
    rev = tmp / "rev.docx"
    # The docx-trackdiff pathology: a 200-word paragraph whose only edit is one
    # word, marked as a whole deleted + whole inserted paragraph.
    body = " ".join(f"word{i}" for i in range(200))
    make_docx(base, [para(body + " end")])
    make_docx(rev, [para(body + " finish")])
    out = tmp / "track.docx"

    def whole_para_markup(b, r, o):
        payload = (
            f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}><w:body>'
            f'<w:p><w:del w:id="1" w:author="x" w:date="t">'
            f'<w:r><w:delText>{body} end</w:delText></w:r></w:del>'
            f'<w:ins w:id="2" w:author="x" w:date="t">'
            f'<w:r><w:t>{body} finish</w:t></w:r></w:ins></w:p>'
            f"</w:body></w:document>")
        with zipfile.ZipFile(o, "w") as z:
            z.writestr("word/document.xml", payload)

    whole_para_markup(base, rev, out)
    fidelity = nb.redline_fidelity(base, rev, out)
    check("a 400-word markup for a one-word change is over-marked",
          fidelity["over_marked"] and fidelity["marked_words"] > 300
          and fidelity["minimal_words"] <= 5, str(fidelity))
    nb.builtin_tracked_changes(base, rev, out)
    fidelity = nb.redline_fidelity(base, rev, out)
    check("the built-in writer stays inside the bar on the same pair",
          not fidelity["over_marked"], str(fidelity))


def test_redline_chain_reports_fidelity_and_adapter_ships():
    print()
    print("== the chain records the fidelity of the file it keeps ==")
    tmp = scratch("paper_redline_chain_")
    base = tmp / "base.docx"
    rev = tmp / "rev.docx"
    make_docx(base, [para("One paragraph, one small edit.")])
    make_docx(rev, [para("One paragraph, one small change.")])
    out = tmp / "track.docx"
    rep = nb.redline_one_pair("builtin", [], base, rev, out)
    check("the built-in backend's attempt carries the fidelity numbers",
          rep["ok"] and (rep["attempts"][-1].get("fidelity") or {}).get("minimal_words") == 2
          and (rep["attempts"][-1].get("fidelity") or {}).get("marked_words") == 2,
          str(rep)[:300])
    check("the adapter the redlines backend resolves ships next to the orchestrator",
          (WS / nb.REDLINE_ADAPTER_NAME).is_file(), nb.REDLINE_ADAPTER_NAME)
    check("the backend resolves the adapter next to the RUNNING script",
          nb.redline_adapter_path().name == nb.REDLINE_ADAPTER_NAME, str(nb.redline_adapter_path()))


def test_mcp_probe_names_why_a_server_cannot_start():
    print()
    print("== a configured-but-dead MCP server is named with the fix ==")
    tmp = scratch("paper_redline_mcp_")
    real_cfg, real_path = nb.codex_config_path, os.environ.get("PATH", "")
    try:
        # A hermetic PATH: the probe's last resort is `which <companion>`, and
        # the operator's real scripts must not decide this test.
        empty_bin = tmp / "empty-bin"
        empty_bin.mkdir()
        os.environ["PATH"] = str(empty_bin)
        server = tmp / "mcp-demo"
        server.mkdir()
        (server / "index.js").write_text("console.log('server');\n", encoding="utf-8")
        (server / "package.json").write_text(
            '{"dependencies": {"@modelcontextprotocol/server": "^2.0.0"}}',
            encoding="utf-8")
        cfg = tmp / "config.toml"
        cfg.write_text(f'[mcp_servers.{nb.DOCX_COMPARE_MCP_SERVER}]\n'
                       f'command = "{sys.executable}"\n'
                       f'args = ["{server / "index.js"}"]\n', encoding="utf-8")
        nb.codex_config_path = lambda: cfg
        reason = nb.mcp_server_unusable_reason(nb.DOCX_COMPARE_MCP_SERVER)
        check("a node server with no node_modules is not usable",
              not nb.mcp_server_configured(nb.DOCX_COMPARE_MCP_SERVER), reason)
        check("the reason names the fix (npm install in its directory)",
              "npm install" in reason and str(server) in reason, reason)
        (server / "node_modules").mkdir()
        reason = nb.mcp_server_unusable_reason(nb.DOCX_COMPARE_MCP_SERVER)
        check("a compare server without its companion script is not usable",
              "docxcompare.sh" in reason, reason)
        (server / "docxcompare.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (server / "docxcompare.sh").chmod(0o755)
        check("with node_modules and the companion beside index.js it is usable",
              nb.mcp_server_configured(nb.DOCX_COMPARE_MCP_SERVER),
              nb.mcp_server_unusable_reason(nb.DOCX_COMPARE_MCP_SERVER))
        # ...and the companion one directory above counts too (the repo layout)
        (server / "docxcompare.sh").unlink()
        (tmp / "docxcompare.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (tmp / "docxcompare.sh").chmod(0o755)
        check("a companion in the parent directory counts",
              nb.mcp_server_configured(nb.DOCX_COMPARE_MCP_SERVER))
        # the redline manifest carries the reason where the backend is skipped
        base, revised = tmp / "b.docx", tmp / "r.docx"
        make_docx(base, [para("One line.")])
        make_docx(revised, [para("One changed line.")])
        (tmp / "docxcompare.sh").unlink()
        res = nb.redline_one_pair("auto", [], base, revised, tmp / "redline.docx")
        first = (res["attempts"] or [{}])[0]
        check("the skipped compare backend's manifest row says why",
              res["ok"] and first.get("skipped")
              and "docxcompare.sh" in str(first.get("detail")), str(first)[:300])
    finally:
        nb.codex_config_path = real_cfg
        os.environ["PATH"] = real_path


def test_mcp_handshake_reports_server_stderr():
    print()
    print("== a server that dies on startup reports what it said ==")
    tmp = scratch("paper_redline_stderr_")
    noisy = tmp / "noisy_server.py"
    noisy.write_text("import sys\n"
                     "sys.stderr.write('ERR_MODULE_NOT_FOUND: Cannot find package demo\\n')\n"
                     "sys.stderr.flush()\n"
                     "sys.exit(3)\n", encoding="utf-8")
    rep = nb.mcp_stdio_tool_call({"command": sys.executable, "args": [str(noisy)]},
                                 "compare_docx", {"originalPath": "a", "revisedPath": "b"},
                                 timeout=15)
    err = str(rep.get("error") or "")
    check("the dead server is reported, not hung on", rep.get("ok") is False, str(rep)[:200])
    check("the server's own stderr travels into the message",
          "ERR_MODULE_NOT_FOUND" in err, err[:200])
    check("...and so does its exit code", "code 3" in err, err[:200])


if __name__ == "__main__":
    try:
        test_builtin_writer_keeps_soft_breaks()
        test_builtin_writer_handles_page_break_runs()
        test_fidelity_check_flags_whole_paragraph_markup()
        test_redline_chain_reports_fidelity_and_adapter_ships()
        test_mcp_probe_names_why_a_server_cannot_start()
        test_mcp_handshake_reports_server_stderr()
    except Exception as e:                                        # noqa: BLE001
        check("the suite completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("REDLINE FIDELITY PASSED")

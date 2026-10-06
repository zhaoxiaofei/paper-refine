#!/usr/bin/env python3
"""The `docx-compare` MCP tool (Word's own comparison engine) must be tried FIRST
whenever the pipeline tracks the differences between two .docx files.

Run:  python3 .paper_test/test_docx_compare.py

Asserts:
  * the Codex config probe recognises `[mcp_servers.docx-compare]` and refuses a
    section whose server script is gone;
  * `redline_one_pair(tool="auto")` drives that server BEFORE any other backend,
    writes the redline the server produced, and records the backend in the
    attempt log; a server whose call fails is recorded and the NEXT backend
    produces the file;
  * `docxcompare.sh` carries the documented contract: usage/exit codes, the
    `.docx`-only and output-must-not-be-an-input guards, the stale-output
    cleanup, and the "no output written -> failure" verification (a PowerShell
    that writes nothing can never make the script report success);
  * the approval override that makes the tool callable from a non-interactive
    `codex exec` is emitted only for a configured server;
  * the paper-revise skill names the Word compare engine FIRST for its
    difference-tracking auxiliary;
  * optionally (`PAPER_TEST_DOCX_COMPARE_MCP=1`), a real stdio handshake with
    the shipped server (tools/list).

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_docxcmp", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_docxcmp"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"[skip] {name}  -- {why}")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def make_docx(path: Path, paras: list) -> None:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
                   for p in paras)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>{body}'
                   f'</w:body></w:document>')


STUB_SERVER = r'''#!/usr/bin/env python3
"""Minimal stdio MCP server used by the tests: answers initialize/tools/call.

DOCXCMP_STUB_MODE=write (default) writes a valid .docx at outputPath;
DOCXCMP_STUB_MODE=none writes nothing but reports success (the caller must
reject it: success means "a readable OOXML file exists");
DOCXCMP_STUB_MODE=error answers the tool call with isError."""
import json
import os
import sys
import zipfile


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def write_docx(path):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    doc = ('<?xml version="1.0" encoding="UTF-8"?><w:document ' + ns + '><w:body>'
           '<w:p><w:r><w:t>stub word compare</w:t></w:r></w:p></w:body></w:document>')
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)


for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    msg = json.loads(line)
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"],
              "result": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "serverInfo": {"name": "stub-docx-compare", "version": "1"}}})
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments") or {}
        mode = os.environ.get("DOCXCMP_STUB_MODE", "write")
        if mode == "error":
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"isError": True,
                             "content": [{"type": "text", "text": "stub compare failed"}]}})
        else:
            if mode == "write":
                write_docx(args["outputPath"])
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"content": [{"type": "text", "text": "ok"}]}})
    # notifications (no id) need no answer
'''


def configured_compare(tmp: Path, mode: str = "write") -> Path:
    """A temp CODEX config + stub server; returns the config path."""
    stub = tmp / "stub_compare_server.py"
    stub.write_text(STUB_SERVER, encoding="utf-8")
    launcher = tmp / "stub_compare.sh"
    launcher.write_text(f'#!/bin/sh\nexport DOCXCMP_STUB_MODE="{mode}"\n'
                        f'exec {sys.executable} "{stub}"\n', encoding="utf-8")
    launcher.chmod(0o755)
    cfg = tmp / "config.toml"
    cfg.write_text("[mcp_servers.docx-compare]\n"
                   f'command = "{launcher}"\n'
                   'startup_timeout_sec = 20\n', encoding="utf-8")
    return cfg


# =====================================================================
# The probe: docx_compare_mcp_spec()
# =====================================================================

def test_compare_probe():
    print()
    print("== the docx-compare MCP probe ==")
    real_path = nb.codex_config_path
    tmp = scratch("paper_cmp_cfg_")
    try:
        nb.codex_config_path = lambda: tmp / "missing.toml"
        check("an unconfigured machine yields no compare spec", nb.docx_compare_mcp_spec() == {})
        cfg = configured_compare(tmp)
        nb.codex_config_path = lambda: cfg
        spec = nb.docx_compare_mcp_spec()
        check("a configured server yields its command/args",
              bool(spec.get("command")) and nb.mcp_server_configured("docx-compare"),
              str(spec))
        (tmp / "stub_compare.sh").unlink()
        check("a deleted compare server script is not usable",
              nb.docx_compare_mcp_spec() == {})
    finally:
        nb.codex_config_path = real_path


# =====================================================================
# The chain: docx-compare FIRST, then the documented fallbacks
# =====================================================================

def test_redline_chain_prefers_the_compare_mcp():
    print()
    print("== redline_one_pair(): the compare MCP is the FIRST backend ==")
    real_path = nb.codex_config_path
    tmp = scratch("paper_cmp_chain_")
    try:
        cfg = configured_compare(tmp)
        nb.codex_config_path = lambda: cfg
        base, revised = tmp / "base.docx", tmp / "revised.docx"
        make_docx(base, ["Alpha"])
        make_docx(revised, ["Alpha", "Beta"])
        out = tmp / "redline.docx"
        res = nb.redline_one_pair("auto", [], base, revised, out)
        check("the compare MCP produced the redline",
              res["ok"] and res["tool"] == nb.REDLINE_COMPARE_BACKEND,
              str(res.get("tool")) + " " + str(res.get("attempts"))[:200])
        check("the attempt log names the MCP backend FIRST",
              (res["attempts"] or [{}])[0].get("backend") == nb.REDLINE_COMPARE_BACKEND,
              str(res["attempts"])[:300])
        check("the output is a readable OOXML package",
              out.is_file() and nb.docx_is_readable(out)[0])
        # a server that answers with isError must NOT be credited; the chain
        # falls back and still produces a valid file
        nb.codex_config_path = lambda: configured_compare(tmp, mode="error")
        out2 = tmp / "redline2.docx"
        res2 = nb.redline_one_pair("auto", [], base, revised, out2)
        first = (res2["attempts"] or [{}])[0]
        check("a failing compare server is recorded and the NEXT backend wins",
              res2["ok"] and first.get("backend") == nb.REDLINE_COMPARE_BACKEND
              and not first.get("ok") and res2["tool"] != nb.REDLINE_COMPARE_BACKEND,
              f"{res2.get('tool')} / {first}")
        check("the fallback file is still a readable OOXML package",
              out2.is_file() and nb.docx_is_readable(out2)[0])
        # a server that reports success without writing anything is no success
        nb.codex_config_path = lambda: configured_compare(tmp, mode="none")
        out3 = tmp / "redline3.docx"
        res3 = nb.redline_one_pair("auto", [], base, revised, out3)
        first3 = (res3["attempts"] or [{}])[0]
        check("a no-output compare server is rejected (a readable file is required)",
              res3["ok"] and not first3.get("ok") and res3["tool"] != nb.REDLINE_COMPARE_BACKEND,
              f"{res3.get('tool')} / {first3.get('detail')}")
    finally:
        nb.codex_config_path = real_path


def test_approval_override():
    print()
    print("== the compare tool is approved for a non-interactive session ==")
    real_path = nb.codex_config_path
    tmp = scratch("paper_cmp_appr_")
    try:
        nb.codex_config_path = lambda: tmp / "missing.toml"
        check("an unconfigured compare server adds NO -c override",
              not any(nb.DOCX_COMPARE_MCP_SERVER in v for v in nb.configured_mcp_approvals()))
        nb.codex_config_path = lambda: configured_compare(tmp)
        vals = nb.configured_mcp_approvals()
        check("a configured compare server is approved with the server-level key",
              f'mcp_servers.{nb.DOCX_COMPARE_MCP_SERVER}.default_tools_approval_mode="approve"'
              in vals, str(vals))
    finally:
        nb.codex_config_path = real_path


# =====================================================================
# docxcompare.sh: the documented contract (hermetic, no Word needed)
# =====================================================================

def fake_powershell(tmp: Path, mode: str) -> Path:
    """A `powershell.exe` that decodes the -EncodedCommand and either writes the
    requested output file or writes nothing at all."""
    helper = tmp / "fake_ps.py"
    helper.write_text(
        "import base64, re, sys\n"
        "mode = sys.argv[1]\n"
        "argv = sys.argv[2:]\n"
        "enc = argv[argv.index('-EncodedCommand') + 1] if '-EncodedCommand' in argv else ''\n"
        "script = base64.b64decode(enc).decode('utf-16-le') if enc else ''\n"
        "m = re.search(r\"\\$outputPath\\s*=\\s*'(.*)'\", script)\n"
        "if not m:\n"
        "    sys.stderr.write('no outputPath in the encoded script\\n'); sys.exit(3)\n"
        "path = m.group(1).replace(\"''\", \"'\")\n"
        "# The script hands Word a Windows path; map the WSL/UNC spellings back so\n"
        "# this fake can write the file the way Word would.\n"
        "if path.startswith('\\\\\\\\wsl.localhost\\\\') or path.startswith('\\\\\\\\wsl$\\\\'):\n"
        "    parts = path.lstrip('\\\\').split('\\\\')\n"
        "    path = '/' + '/'.join(parts[2:])\n"
        "path = path.replace('\\\\', '/')\n"
        "# A path that stayed relative would be created in the CWD -- never do\n"
        "# that in a test (it used to litter the repository root).\n"
        "if not path.startswith('/'):\n"
        "    sys.stderr.write('refusing a non-absolute output path: %s\\n' % path); sys.exit(3)\n"
        "if mode == 'write':\n"
        "    with open(path, 'wb') as fh:\n"
        "        fh.write(b'PK\\x03\\x04stub')\n"
        "print(path)\n",
        encoding="utf-8")
    exe = tmp / "powershell.exe"
    exe.write_text(f'#!/bin/sh\nexec {sys.executable} "{helper}" {mode} "$@"\n',
                   encoding="utf-8")
    exe.chmod(0o755)
    return exe


def test_docxcompare_script():
    print()
    print("== docxcompare.sh: contract, guards and the no-output rule ==")
    script = WS / "docxcompare.sh"
    check("docxcompare.sh exists and is executable",
          script.is_file() and os.access(script, os.X_OK), str(script))
    text = script.read_text(encoding="utf-8")
    check("it drives Word's own CompareDocuments engine",
          "CompareDocuments" in text and "Word.Application" in text)
    check("it disables macros on the automation object",
          "AutomationSecurity = 3" in text)
    tmp = scratch("paper_docxcompare_")
    docx = tmp / "a.docx"
    docx2 = tmp / "b.docx"
    make_docx(docx, ["one"])
    make_docx(docx2, ["two"])
    p = subprocess.run([str(script)], capture_output=True, text=True)
    check("no arguments -> usage + exit 2", p.returncode == 2 and "Usage" in p.stderr,
          f"rc={p.returncode} {p.stderr[:80]}")
    p = subprocess.run([str(script), str(tmp / "nope.docx"), str(docx2)],
                       capture_output=True, text=True)
    check("a missing input -> exit 1", p.returncode == 1 and "not found" in p.stderr,
          f"rc={p.returncode} {p.stderr[:80]}")
    not_docx = tmp / "x.txt"
    not_docx.write_text("not a docx", encoding="utf-8")
    p = subprocess.run([str(script), str(not_docx), str(docx2)],
                       capture_output=True, text=True)
    check("a non-.docx input -> exit 2", p.returncode == 2 and ".docx" in p.stderr,
          f"rc={p.returncode} {p.stderr[:80]}")
    p = subprocess.run([str(script), str(docx), str(docx2), str(docx)],
                       capture_output=True, text=True)
    check("an output that IS an input is refused (the input must survive)",
          p.returncode == 2 and "refusing to overwrite an input" in p.stderr
          and docx.is_file(), f"rc={p.returncode} {p.stderr[:120]}")
    # a PowerShell that writes nothing must never look like success, and a stale
    # output must not survive it
    fake_powershell(tmp, "none")
    out = tmp / "redline.docx"
    out.write_bytes(b"PK stale")
    env = dict(os.environ, PATH=f"{tmp}:{os.environ.get('PATH', '')}")
    p = subprocess.run([str(script), str(docx), str(docx2), str(out)],
                       capture_output=True, text=True, env=env)
    check("a converter that writes nothing FAILS and leaves no stale output",
          p.returncode != 0 and not out.exists(), f"rc={p.returncode} {p.stderr[:120]}")
    # a PowerShell that writes the file makes the script succeed
    fake_powershell(tmp, "write")
    quoted = tmp / "it's quoted"
    quoted.mkdir()
    out2 = quoted / "redline.docx"
    p = subprocess.run([str(script), str(docx), str(docx2), str(out2)],
                       capture_output=True, text=True, env=env)
    check("a written comparison is reported as success (quote-safe path)",
          p.returncode == 0 and out2.is_file() and "Redline written" in p.stdout,
          f"rc={p.returncode} {p.stdout[-120:]} {p.stderr[-120:]}")


# =====================================================================
# The skill names the Word compare engine first
# =====================================================================

def test_skill_names_the_compare_engine():
    print()
    print("== the paper-revise skill names the compare engine FIRST ==")
    rules = (WS / "paper-skills/paper-revise/references/edit_rules.md").read_text(encoding="utf-8")
    skill = (WS / "paper-skills/paper-revise/SKILL.md").read_text(encoding="utf-8")
    prompt = (WS / "paper-skills/prompts/adress_issues.prompt.md").read_text(encoding="utf-8")
    flat = " ".join(rules.split())
    check("E5 names docxcompare.sh / the docx-compare MCP tool as the first choice",
          "docxcompare.sh" in flat and "docx-compare" in flat and "FIRST choice" in flat,
          flat[:200])
    check("E5 emits the renamed auxiliary family",
          ".tracking-previous.docx" in flat and ".logging-previous.docx" in flat
          and "latexdiff" in flat)
    check("SKILL.md / the prompt carry the renamed E5 rule",
          "tracking-previous" in skill and "tracking-previous" in prompt)
    aux = nb.AUX_FILES_RULE
    check("the shared auxiliary rule names the new family and the legacy spellings",
          "tracking-original" in aux and "logging-prev-winner" in aux
          and "tracked.docx" in aux)


def test_live_server_handshake():
    print()
    print("== optional: the shipped docx-compare server answers (live) ==")
    if os.environ.get("PAPER_TEST_DOCX_COMPARE_MCP") != "1":
        skip("live docx-compare MCP handshake", "set PAPER_TEST_DOCX_COMPARE_MCP=1 to run it")
        return
    server = WS / "mcp-docx-compare/index.js"
    if not (server.is_file() and shutil.which("node")):
        skip("live docx-compare MCP handshake", "node or the server script is missing")
        return
    res = nb.mcp_stdio_tool_call({"command": shutil.which("node"), "args": [str(server)]},
                                 "compare_docx", {}, timeout=60)
    check("the shipped server starts and answers (a malformed call is refused cleanly)",
          res.get("ok") or "compare_docx" in str(res.get("error")),
          str(res)[:200])


def main():
    test_compare_probe()
    test_redline_chain_prefers_the_compare_mcp()
    test_approval_override()
    test_docxcompare_script()
    test_skill_names_the_compare_engine()
    test_live_server_handshake()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("All docx-compare checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

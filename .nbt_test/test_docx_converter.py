#!/usr/bin/env python3
"""The docx-converter MCP tool must be tried FIRST for any .docx -> .pdf.

Run:  python3 .nbt_test/test_docx_converter.py

Asserts:
  * the Codex config parser recognises `[mcp_servers.docx-converter]` (plain and
    quoted section names, CODEX_HOME aware) and refuses a section whose server
    script is missing;
  * the probe list puts the MCP tool first and reports it in the
    "converters available" summary;
  * every prompt (review, rewrite, revise, integration, judge) instructs the
    agent to call `convert_docx_to_pdf` BEFORE any other converter, in the right
    order, and to render into a writable work directory instead of the
    hash-verified read-only views;
  * optionally (`NBT_TEST_DOCX_MCP=1`), a real stdio handshake with the server
    (tools/list) and a real conversion of a scratch .docx.

`NBT_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_mcp", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_mcp"] = nb
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


# =====================================================================
# The probe: is the MCP server configured (and startable)?
# =====================================================================

def test_config_probe():
    print("== the Codex config probe ==")
    tmp = scratch("nbt_mcp_cfg_")
    script = tmp / "server" / "index.js"
    script.parent.mkdir(parents=True)
    script.write_text("// fake mcp server\n", encoding="utf-8")
    node = tmp / "node"
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    cfg = tmp / "config.toml"
    cfg.write_text(
        'model = "x"\n'
        "\n"
        "[mcp_servers.deepseek-vision]\n"
        'command = "npx"\n'
        "\n"
        "[mcp_servers.docx-converter]\n"
        f'command = "{node}"\n'
        f'args = ["{script}"]\n'
        "startup_timeout_sec = 20\n",
        encoding="utf-8")
    real_path = nb.codex_config_path
    nb.codex_config_path = lambda: cfg
    try:
        check("a configured server with an existing script is detected",
              nb.mcp_server_configured("docx-converter") is True)
        check("an unrelated/absent server name is not detected",
              nb.mcp_server_configured("some-other-server") is False)
        check("probe_available() routes mcp: specs to the config probe",
              nb.probe_available("mcp:docx-converter") is True
              and nb.probe_available("mcp:missing-server") is False)
        # a deleted server script must not look configured
        script.unlink()
        check("a section whose server script was deleted is NOT usable",
              nb.mcp_server_configured("docx-converter") is False)
        script.write_text("// back\n", encoding="utf-8")
        # quoted section name (codex writes it when the name needs quoting)
        cfg.write_text('[mcp_servers."docx-converter"]\n'
                       f'command = "{node}"\nargs = ["{script}"]\n', encoding="utf-8")
        check("a quoted [mcp_servers.\"name\"] section is detected",
              nb.mcp_server_configured("docx-converter") is True)
        # no config at all
        nb.codex_config_path = lambda: tmp / "nope.toml"
        check("a missing config file yields False", nb.mcp_server_configured("docx-converter") is False)
    finally:
        nb.codex_config_path = real_path
        nb._VISUAL_TOOLS_CACHE = None
    # CODEX_HOME is honoured
    cfg_home = tmp / "codex_home"
    cfg_home.mkdir()
    (cfg_home / "config.toml").write_text('[mcp_servers.docx-converter]\n'
                                          f'command = "{node}"\nargs = ["{script}"]\n',
                                          encoding="utf-8")
    old_home = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = str(cfg_home)
    try:
        check("CODEX_HOME redirects the config path",
              nb.codex_config_path() == cfg_home / "config.toml"
              and nb.mcp_server_configured("docx-converter") is True)
    finally:
        if old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_home
        nb._VISUAL_TOOLS_CACHE = None


def test_probe_order_and_summary():
    print()
    print("== the probe list and the detected-converter summary ==")
    first_label, first_spec = nb.VISUAL_TOOL_PROBES[0]
    check("the docx-converter MCP tool is the FIRST probe",
          first_spec == "mcp:docx-converter" and "docx-converter" in first_label
          and nb.DOCX_MCP_TOOL in first_label,
          f"{first_label} / {first_spec}")
    check("docx2pdf.sh is the first FALLBACK (second probe)",
          nb.VISUAL_TOOL_PROBES[1] == ("docx2pdf.sh", "docx2pdf.sh"),
          str(nb.VISUAL_TOOL_PROBES[1]))
    order = [spec for _label, spec in nb.VISUAL_TOOL_PROBES]
    check("the remaining converters keep their layout-fidelity order",
          order.index("docx2pdf.sh") < order.index("docx") < order.index("soffice")
          < order.index("pandoc"), str(order))
    nb._VISUAL_TOOLS_CACHE = None
    summary = nb.visual_tools_summary()
    configured = nb.mcp_server_configured(nb.DOCX_MCP_SERVER)
    check("the summary lists the MCP tool iff the server is configured",
          ("docx-converter" in summary) == configured, summary)
    if configured:
        check("the MCP tool is listed FIRST in the summary", summary.startswith("docx-converter"),
              summary)
    else:
        skip("the MCP tool is listed first", "no docx-converter server on this machine")
    # a cache rebuild after a config change reflects the new state
    real_path = nb.codex_config_path
    tmp = scratch("nbt_mcp_cache_")
    nb.codex_config_path = lambda: tmp / "missing.toml"
    nb._VISUAL_TOOLS_CACHE = None
    try:
        check("an unconfigured machine omits the MCP tool from the summary",
              "docx-converter" not in nb.visual_tools_summary())
    finally:
        nb.codex_config_path = real_path
        nb._VISUAL_TOOLS_CACHE = None


# =====================================================================
# The prompts: try the MCP tool before any other converter
# =====================================================================

def test_prompts_prefer_the_mcp_tool():
    print()
    print("== every prompt tries convert_docx_to_pdf first (and renders safely) ==")
    sb = Path("/tmp/nbt_mcp_sb")
    prompts = {
        "review": nb.review_prompt(sb, "r1_review", 1),
        "rewrite": nb.rewrite_prompt(sb, "r1_w1", 1),
        "revise": nb.revise_prompt(sb, "r1_a2_revise", 1),
        "integrate": nb.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"]),
        "judge": nb.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"]),
    }
    for name, text in prompts.items():
        flat = " ".join(text.split())
        unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
        check(f"{name}: the prompt names the MCP tool and demands it FIRST",
              f"`{nb.DOCX_MCP_TOOL}`" in text and "BEFORE ANY OTHER CONVERTER" in flat,
              f"unresolved={unresolved}")
        # prompt level: the MCP call must be named before the docx2pdf fallback
        # (capability lists may mention `docx render` for other purposes, so the
        # full ordering is asserted on the visual rule itself, below)
        check(f"{name}: the MCP tool is named BEFORE the docx2pdf.sh fallback",
              flat.find(nb.DOCX_MCP_TOOL) < flat.find("docx2pdf.sh FILE")
              and flat.find(nb.DOCX_MCP_TOOL) >= 0,
              str((flat.find(nb.DOCX_MCP_TOOL), flat.find("docx2pdf.sh FILE"))))
        check(f"{name}: the prompt warns that a read-only view must stay byte-identical",
              "NEVER INTO A READ-ONLY INPUT" in flat
              and "hash-verified" in flat and "work/" in flat)
        check(f"{name}: the prompt has no unresolved tokens", not unresolved, str(unresolved))
        check(f"{name}: the optional docx CLI block repeats the MCP-first rule",
              "the `docx-converter` MCP tool comes FIRST" in flat)
        check(f"{name}: the detected-converter line names the MCP tool when configured",
              ("docx-converter MCP tool" in flat) == nb.mcp_server_configured(nb.DOCX_MCP_SERVER),
              flat[flat.find("Converters available"):][:120])
    # the authoritative converter order, taken from the visual rule itself
    visual = " ".join(nb.visual_inspection_block("X").split())
    idx = [visual.find(nb.DOCX_MCP_TOOL), visual.find("docx2pdf.sh FILE"),
           visual.find("docx render FILE --out pages/"), visual.find("soffice --headless")]
    check("the visual rule orders the converters MCP -> docx2pdf -> docx render -> LibreOffice",
          all(i >= 0 for i in idx) and idx == sorted(idx), str(idx))
    check("the visual rule tells the agent the MCP tool is the FIRST choice",
          "ALWAYS TRY THE `docx-converter` MCP TOOL FIRST" in visual)


# =====================================================================
# Optional live handshake / conversion
# =====================================================================

def mcp_server_argv(cfg: Path, name: str):
    """The argv the Codex config would use to start server `name` (or None).

    The config's `command` matters: several node versions may be on PATH, and
    only the one the operator configured is guaranteed to have the server's
    dependencies. Parsing it here keeps the test faithful to what an agent
    session actually starts.
    """
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    header = re.compile(r"^\s*\[\s*mcp_servers\s*\.\s*(?:\"" + re.escape(name) + r"\"|'" +
                        re.escape(name) + r"'|" + re.escape(name) + r")\s*\]\s*$", re.MULTILINE)
    m = header.search(text)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^\s*\[", rest, re.MULTILINE)
    body = rest[:nxt.start()] if nxt else rest
    cmd = re.search(r'^\s*command\s*=\s*"([^"]+)"', body, re.MULTILINE)
    args = re.search(r"^\s*args\s*=\s*(\[[^\]]*\])", body, re.MULTILINE)
    if not cmd:
        return None
    argv = [cmd.group(1)]
    if args:
        try:
            argv += [str(a) for a in json.loads(args.group(1))]
        except ValueError:
            return None
    return argv


def mcp_roundtrip(argv, docx: Path = None, timeout: float = 120.0):
    """Speak the MCP stdio protocol: initialize, tools/list, optionally call."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    errors = []

    def send(msg):
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            errors.append(f"{type(e).__name__}: {e}")

    def read_one(limit: float):
        box = {}

        def rd():
            box["line"] = proc.stdout.readline()
        t = threading.Thread(target=rd, daemon=True)
        t.start()
        t.join(limit)
        return box.get("line", "")

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "nbt-test", "version": "0"}}})
        init = read_one(20)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = read_one(20)
        call = ""
        if docx is not None:
            send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": nb.DOCX_MCP_TOOL, "arguments": {"docxPath": str(docx)}}})
            call = read_one(timeout)
        return init, tools, call
    except (BrokenPipeError, OSError) as e:
        return "", "", f"transport error: {e}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:                                        # noqa: BLE001
            proc.kill()


# =====================================================================
# `codex exec` cannot call an MCP tool it is not allowed to approve
# =====================================================================
# Approval policy `never` (what `codex exec` runs with) DENIES an MCP tool call
# that wants approval instead of queueing it for the operator, so the runner has
# to hand the session a per-server `-c` override or the tool is unreachable and
# every prompt falls through to docx2pdf.sh.

def test_codex_exec_mcp_approval():
    print()
    print("== codex exec: the MCP approval override ==")
    tmp = scratch("nbt_mcp_approval_")
    script = tmp / "server" / "index.js"
    script.parent.mkdir(parents=True)
    script.write_text("// fake mcp server\n", encoding="utf-8")
    cfg = tmp / "config.toml"
    cfg.write_text("[mcp_servers.docx-converter]\n"
                   f'command = "node"\nargs = ["{script}"]\n',
                   encoding="utf-8")
    real_path = nb.codex_config_path
    want = f'mcp_servers.{nb.DOCX_MCP_SERVER}.default_tools_approval_mode="approve"'
    nb.codex_config_path = lambda: cfg
    try:
        argv = nb.agent_argv("codex")
        check("the configured converter is pre-approved in the codex argv",
              argv == ["codex", "exec", "-c", want, "-"], " ".join(argv))
        check("the prompt positional `-` stays last",
              argv[-1] == "-", " ".join(argv))
        check("resolve_agent_cmd() returns the same, override included",
              want in nb.resolve_agent_cmd("codex", None, use_env=False))
        check("no approval/sandbox bypass flag is used",
              not [a for a in argv if a in ("--approve-for-me", "--full-auto", "-a",
                                            "--ask-for-approval", "-s", "--sandbox",
                                            "--dangerously-bypass-approvals-and-sandbox",
                                            "--dangerously-bypass-hook-trust")],
              " ".join(argv))
        check("only the server named in MCP_APPROVALS is approved",
              [spec[0] for spec in nb.MCP_APPROVALS] == [nb.DOCX_MCP_SERVER],
              str(nb.MCP_APPROVALS))
        # an operator-supplied argv is authoritative and must not be rewritten
        explicit = '["codex","exec","-"]'
        check("--agent-cmd is passed through untouched",
              nb.resolve_agent_cmd("codex", explicit) == ["codex", "exec", "-"],
              nb.resolve_agent_cmd("codex", explicit))
    finally:
        nb.codex_config_path = real_path
    # a machine without the server must not get a half-configured override
    nb.codex_config_path = lambda: tmp / "missing.toml"
    try:
        check("no override when the server is not configured",
              nb.agent_argv("codex") == ["codex", "exec", "-"]
              and nb.configured_mcp_approvals() == [],
              " ".join(nb.agent_argv("codex")))
    finally:
        nb.codex_config_path = real_path
    check("the claude preset is left alone",
          nb.agent_argv("claude") == nb.AGENT_PRESETS["claude"])


def test_live_server_if_available():
    print()
    print("== the live docx-converter server (handshake; conversion opt-in) ==")
    cfg = nb.codex_config_path()
    argv = mcp_server_argv(cfg, nb.DOCX_MCP_SERVER)
    if not argv:
        skip("live MCP handshake", f"no [{nb.DOCX_MCP_SERVER}] entry in {cfg}")
        return
    missing = [a for a in argv if a.startswith("/") and not Path(a).exists()]
    if missing:
        skip("live MCP handshake", f"configured path(s) missing: {missing}")
        return
    init, tools, _call = mcp_roundtrip(argv)
    if not init and not tools:
        skip("live MCP handshake", "the configured server did not answer (see stderr)")
        return
    check("the server answers initialize with its name",
          "docx-converter" in init, init[:120])
    check("tools/list offers convert_docx_to_pdf",
          nb.DOCX_MCP_TOOL in tools, tools[:200])
    if os.environ.get("NBT_TEST_DOCX_MCP") != "1":
        skip("live docx->pdf conversion",
             "set NBT_TEST_DOCX_MCP=1 to run it (needs Microsoft Word / WSL interop)")
        return
    tmp = scratch("nbt_mcp_conv_")
    docx_cli = shutil.which("docx")
    if docx_cli is None:
        skip("live docx->pdf conversion", "the `docx` CLI is not available to build a sample")
        return
    md = tmp / "sample.md"
    md.write_text("# Sample\n\nHello from the MCP test.\n", encoding="utf-8")
    sample = tmp / "sample-a.docx"
    subprocess.run([docx_cli, "create", str(sample), "--from", str(md), "--force"],
                   capture_output=True, text=True, timeout=120)
    if not sample.is_file():
        skip("live docx->pdf conversion", "could not build the sample .docx")
        return
    _init, _tools, call = mcp_roundtrip(argv, docx=sample, timeout=240)
    pdf = sample.with_suffix(".pdf")
    check("the MCP tool reports success",
          '"result"' in call and '"isError":true' not in call, call[:200])
    check("the MCP tool wrote the PDF next to the .docx",
          pdf.is_file() and pdf.stat().st_size > 1000,
          f"{pdf} {pdf.stat().st_size if pdf.is_file() else '-'} bytes")


def main() -> int:
    sections = (("probe", test_config_probe),
                ("probe", test_probe_order_and_summary),
                ("prompts", test_prompts_prefer_the_mcp_tool),
                ("codex-exec", test_codex_exec_mcp_approval),
                ("live", test_live_server_if_available))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL DOCX-CONVERTER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

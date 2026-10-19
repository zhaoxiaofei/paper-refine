#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the Qwen3.8-27B OpenAI-compatible adapter (2026-10-19).

No live model is required: a local HTTP server stands in for vLLM. Set
PAPER_QWEN_LIVE=1 to additionally probe the configured endpoint (the SSH
tunnel and vLLM server must be up).

Run: python3 .paper_test/test_qwen_provider_2026_1019.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = Path(os.environ.get("PAPER_WS") or HERE.parent)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


qwen = load("paper_qwen_agent", WS / "paper_qwen_agent.py")
pipe = load("paper_pipeline_qwen_test", WS / "paper_pipeline.py")

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class FakeVLLM(BaseHTTPRequestHandler):
    tool_ok = False
    calls = []

    def log_message(self, *args):
        pass

    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/") == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": "qwen3.8-27b",
                                                         "object": "model"}]})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        FakeVLLM.calls.append(body)
        if self.path.rstrip("/") == "/v1/chat/completions":
            if "tools" in body and not FakeVLLM.tool_ok:
                self._json(400, {"error": {"message": "\"auto\" tool choice requires "
                                                      "--enable-auto-tool-choice and "
                                                      "--tool-call-parser to be set",
                                           "type": "BadRequestError"}})
                return
            self._json(200, {"choices": [{"message": {"role": "assistant",
                                                      "content": "OK"}}]})
        else:
            self._json(404, {"error": {"message": "not found"}})


def server():
    srv = HTTPServer(("127.0.0.1", 0), FakeVLLM)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def cfg(base_url, harness="codex"):
    class A:
        pass
    a = A()
    a.base_url = base_url
    a.model = "qwen3.8-27b"
    a.api_key = "dummy"
    a.harness = harness
    a.reasoning_effort = "low"
    a.tunnel = "off"
    a.ssh_host = "zxf@101.6.31.113"
    a.ssh_port = "52080"
    a.local_port = "18000"
    a.remote = "127.0.0.1:8000"
    return qwen.config(a)


def test_argv_and_patch():
    c = cfg("http://127.0.0.1:18000/v1")
    argv = qwen.codex_argv(c, extra=["-c", 'mcp_servers.x.approval_policy="approve"'])
    text = " ".join(argv)
    check("codex argv selects the qwen provider", 'model_provider="qwen"' in text)
    check("codex argv names the model", 'model="qwen3.8-27b"' in text)
    check("codex argv uses the vLLM base URL",
          'model_providers.qwen.base_url="http://127.0.0.1:18000/v1"' in text)
    check("codex argv uses the responses wire API",
          'model_providers.qwen.wire_api="responses"' in text)
    check("codex argv sets qwen-supported effort", 'model_reasoning_effort="low"' in text)
    check("codex argv keeps the MCP overrides and the final stdin prompt",
          "mcp_servers.x.approval_policy" in text and argv[-1] == "-")
    patch = qwen.dsh_patch_text(c)
    check("dsh patch declares the llm-pi-ai route", "llm-pi-ai" in patch
          and "openai-completions" in patch)
    check("dsh patch names the endpoint and model",
          'baseURL: "http://127.0.0.1:18000/v1"' in patch
          and 'id: "qwen3.8-27b"' in patch)
    check("dsh patch declares reasoning efforts and default",
          "reasoningEfforts" in patch and 'reasoningEffort: "low"' in patch)


def test_probe_chat_and_tools():
    srv, base = server()
    try:
        c = cfg(base)
        ok, ids, err = qwen.probe_endpoint(c)
        check("probe finds the model", ok and ids == ["qwen3.8-27b"], err)
        text, err = qwen.chat_text(c, "say OK")
        check("chat returns the completion text", text == "OK" and not err, err)
        supported, detail = qwen.check_tools(c)
        check("tool check reports the server's refusal",
              not supported and "tool" in detail.lower(), detail)
        FakeVLLM.tool_ok = True
        supported, detail = qwen.check_tools(c)
        check("tool check reports acceptance when the server allows it",
              supported, detail)
    finally:
        srv.shutdown()
        srv.server_close()


def test_pipeline_integration():
    check("qwen is an offered agent backend", "qwen" in pipe.AGENT_CHOICES)
    check("qwen is offered to the conflict audit too",
          "qwen" in pipe.CONFLICT_AGENT_CHOICES)
    argv = pipe.agent_argv("qwen")
    check("agent_argv routes qwen to the adapter",
          Path(argv[0]).name == "paper_qwen_agent.py", str(argv[:3]))
    check("agent_argv names a harness", "--harness" in argv)
    os.environ["PAPER_QWEN_HARNESS"] = "dsh"
    try:
        argv = pipe.agent_argv("qwen")
        check("agent_argv honours PAPER_QWEN_HARNESS=dsh",
              "--harness" in argv and argv[argv.index("--harness") + 1] == "dsh")
    finally:
        os.environ.pop("PAPER_QWEN_HARNESS", None)
    check("the module manifest carries the adapter",
          "paper_qwen_agent.py" in pipe.PIPELINE_MODULE_FILES)


def test_tunnel_off_error():
    c = cfg("http://127.0.0.1:9/v1")
    c["tunnel"] = "off"
    err = qwen.ensure_tunnel(c, log=lambda *_: None)
    check("an unreachable endpoint with PAPER_QWEN_TUNNEL=off is a clear error",
          "not reachable" in err and "off" in err, err)
    ok, ids, perr = qwen.probe_endpoint(c, timeout=1.0)
    check("the probe reports an unreachable endpoint", not ok and bool(perr), perr)


def test_live_probe():
    if os.environ.get("PAPER_QWEN_LIVE") not in ("1", "true", "yes"):
        print("[skip] live endpoint probe  -- set PAPER_QWEN_LIVE=1 to enable")
        return
    c = qwen.config(None)
    ok, ids, err = qwen.probe_endpoint(c)
    check("live qwen endpoint answers", ok and c["model"] in ids, err or str(ids))


def main():
    for fn in (test_argv_and_patch, test_probe_chat_and_tools,
               test_tunnel_off_error, test_pipeline_integration, test_live_probe):
        try:
            fn()
        except Exception as e:                                        # noqa: BLE001
            check(f"{fn.__name__} runs", False, f"{type(e).__name__}: {e}")
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("\nPASSED: qwen adapter checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

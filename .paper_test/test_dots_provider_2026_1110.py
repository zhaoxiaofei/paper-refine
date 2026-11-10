#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the dots3-note-prev adapter (2026-11-10).

No live model is required: a local HTTP server stands in for the Dots API.
Set PAPER_DOTS_LIVE=1 to additionally probe the configured endpoint (a real
DOTS_API_KEY is required).

Run: python3 .paper_test/test_dots_provider_2026_1110.py
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


dots = load("paper_dots_agent", WS / "paper_dots_agent.py")
pipe = load("paper_pipeline_dots_test", WS / "paper_pipeline.py")

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class FakeDots(BaseHTTPRequestHandler):
    tool_ok = True
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
            self._json(200, {"object": "list",
                             "data": [{"id": "dots3-note-prev", "owned_by": "system"}]})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        FakeDots.calls.append((self.path, body, dict(self.headers)))
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
        if "tools" in body and not FakeDots.tool_ok:
            self._json(400, {"error": {"message": "tools are not supported",
                                       "type": "invalid_request_error"}})
            return
        self._json(200, {"choices": [{"finish_reason": "stop",
                                      "message": {"role": "assistant",
                                                  "content": "OK"}}]})


def server():
    srv = HTTPServer(("127.0.0.1", 0), FakeDots)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def cfg(base_url, harness="codex", api_key="test-key"):
    class A:
        pass
    a = A()
    a.base_url = base_url
    a.model = "dots3-note-prev"
    a.api_key = api_key
    a.harness = harness
    a.reasoning_effort = "medium"
    return dots.config(a)


def test_argv_and_patch():
    c = cfg("https://note3-prev-api.askdiandian.com/v1")
    argv = dots.codex_argv(c, extra=["-c", 'mcp_servers.x.approval_policy="approve"'])
    text = " ".join(argv)
    check("codex argv selects the dots provider", 'model_provider="dots"' in text)
    check("codex argv names the model", 'model="dots3-note-prev"' in text)
    check("codex argv uses the platform base URL",
          'model_providers.dots.base_url="https://note3-prev-api.askdiandian.com/v1"' in text)
    check("codex argv reads the documented DOTS_API_KEY",
          'model_providers.dots.env_key="DOTS_API_KEY"' in text)
    check("codex argv uses the documented Responses wire API",
          'model_providers.dots.wire_api="responses"' in text)
    check("codex argv disables the hosted web-search tool", 'web_search="disabled"' in text)
    check("codex argv declares the enforced context window",
          "model_context_window=393000" in text)
    check("codex argv keeps the MCP overrides and the final stdin prompt",
          "mcp_servers.x.approval_policy" in text and argv[-1] == "-")
    claude = dots.claude_env(dots.config(type("A", (), {
        "harness": "claude", "model": "dots3-note-prev",
        "base_url": dots.DEFAULT_BASE_URL, "api_key": "sk-test",
        "reasoning_effort": None})()))
    check("claude harness points at the Anthropic root",
          claude["ANTHROPIC_BASE_URL"] == "https://note3-prev-api.askdiandian.com"
          and claude["ANTHROPIC_AUTH_TOKEN"] == "sk-test"
          and claude["ANTHROPIC_MODEL"] == "dots3-note-prev")
    check("claude harness uses the documented print command",
          dots.claude_argv(dots.config(type("A", (), {
              "harness": "claude", "model": "dots3-note-prev",
              "base_url": dots.DEFAULT_BASE_URL, "api_key": "sk-test",
              "reasoning_effort": None})()))[:2]
          == ["claude", "--permission-mode"])
    check("the public harness name normalizes to the adapter spelling",
          dots.config(type("A", (), {"harness": "claude-code"})())["harness"]
          == "claude")
    patch = dots.dsh_patch_text(c)
    check("dsh patch declares the llm-pi-ai route", "llm-pi-ai" in patch
          and "openai-completions" in patch)
    check("dsh patch names the endpoint, model and key",
          'baseURL: "https://note3-prev-api.askdiandian.com/v1"' in patch
          and 'id: "dots3-note-prev"' in patch and "apiKeyEnv: DOTS_API_KEY" in patch)
    check("dsh patch declares the context/output caps",
          "contextWindow: 393000" in patch and "maxTokens: 65536" in patch)
    check("dsh patch does not invent a reasoning parameter",
          "reasoningEfforts: false" in patch)
    check("dsh patch stays on the documented token field",
          "maxTokensField: max_tokens" in patch and "supportsStore: false" in patch)
    check("dsh patch sets the default model",
          "agent-default-model" in patch and 'provider: dots' in patch
          and 'model: "dots3-note-prev"' in patch)
    check("dsh patch retries each LLM call with 10s-to-3600s backoff",
          "retryPolicy:" in patch and "initialDelayMs: 10000" in patch
          and "maxDelayMs: 3600000" in patch and "RATE_LIMIT" in patch)
    check("dsh patch routes compaction through a second Dots key",
          "dots-compaction:" in patch
          and "apiKeyEnv: DOTS_API_KEY_1474" in patch
          and "summarizationProvider: dots-compaction" in patch)


def test_probe_chat_and_tools():
    srv, base = server()
    try:
        c = cfg(base)
        ok, ids, err = dots.probe_endpoint(c)
        check("probe finds the model", ok and ids == ["dots3-note-prev"], err)
        text, err = dots.chat_text(c, "say OK")
        check("chat returns the completion text", text == "OK" and not err, err)
        supported, detail = dots.check_tools(c)
        check("tool check reports acceptance", supported, detail)
        FakeDots.tool_ok = False
        supported, detail = dots.check_tools(c)
        check("tool check reports a refusal",
              not supported and "tool" in detail.lower(), detail)
    finally:
        srv.shutdown()
        srv.server_close()


def test_key_preflight():
    missing = cfg(dots.DEFAULT_BASE_URL, api_key="")
    problem = dots._api_key_problem(missing)
    check("the hosted endpoint requires DOTS_API_KEY",
          "DOTS_API_KEY" in problem and "dots.ai/platform/docs" in problem, problem)
    local = cfg("http://127.0.0.1:9/v1", api_key="")
    check("a custom OpenAI-compatible endpoint may be keyless",
          dots._api_key_problem(local) == "", dots._api_key_problem(local))
    os.environ["PAPER_DOTS_REQUIRE_TOOLS"] = "1"
    try:
        check("PAPER_DOTS_REQUIRE_TOOLS is a hard preflight setting",
              dots.config(None)["require_tools"] is True)
    finally:
        os.environ.pop("PAPER_DOTS_REQUIRE_TOOLS", None)


def test_pipeline_integration():
    check("dots is an offered agent backend", "dots" in pipe.AGENT_CHOICES)
    check("dots is offered to the conflict audit too",
          "dots" in pipe.CONFLICT_AGENT_CHOICES)
    argv = pipe.agent_argv("dots")
    check("agent_argv routes dots to the adapter",
          Path(argv[0]).name == "paper_dots_agent.py", str(argv[:3]))
    check("agent_argv names a harness", "--harness" in argv)
    os.environ["PAPER_DOTS_HARNESS"] = "dsh"
    try:
        argv = pipe.agent_argv("dots")
        check("agent_argv honours PAPER_DOTS_HARNESS=dsh",
              "--harness" in argv and argv[argv.index("--harness") + 1] == "dsh")
    finally:
        os.environ.pop("PAPER_DOTS_HARNESS", None)
    os.environ["PAPER_DOTS_MODEL"] = "dots3-note-prev-custom"
    os.environ["PAPER_DOTS_HARNESS"] = "dsh"
    try:
        got = pipe.effective_agent_model([str(WS / "paper_dots_agent.py")])
        check("the run record names the selected model and harness",
              got["name"] == "dots3-note-prev-custom" and got["harness"] == "dsh"
              and "PAPER_DOTS" in got["source"], str(got))
    finally:
        os.environ.pop("PAPER_DOTS_MODEL", None)
        os.environ.pop("PAPER_DOTS_HARNESS", None)
    check("the module manifest carries the adapter",
          "paper_dots_agent.py" in pipe.PIPELINE_MODULE_FILES)
    check("setup copies the adapter beside the driver",
          "paper_dots_agent.py" in (WS / "paper_pipeline_parts" / "p09_setup.py").read_text())


def test_dsh_turn_events():
    print()
    print("== the dsh turn-end event shapes ==")
    check("the older /turn_end/ status=ok is a completed turn",
          dots._dsh_turn_failed(b'{"type":"turn_end","status":"ok"}') is False)
    check("the older /turn_end/ status=cancelled is a failed turn",
          dots._dsh_turn_failed(b'{"type":"turn_end","status":"cancelled"}') is True)
    check("the current /status phase=turn_end kind=completed/ is completed",
          dots._dsh_turn_failed(
              b'{"type":"status","phase":"turn_end","reason":{"kind":"completed"}}'
          ) is False)
    check("the current /reason kind=error/ is a failed turn",
          dots._dsh_turn_failed(
              b'{"type":"status","phase":"turn_end","reason":{"kind":"error"}}'
          ) is True)
    check("a status line that is not a turn end is ignored",
          dots._dsh_turn_failed(b'{"type":"status","phase":"step_start"}') is None)
    # A wrapper that exits 0 without a turn-end event is not a completed turn.
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "silent.py"
        script.write_text("print('{\"type\": \"status\", \"phase\": \"step_start\"}')\n",
                          encoding="utf-8")
        rc, failed = dots.run_dsh_streaming([sys.executable, str(script)], {})
        check("exit 0 without a turn-end event is a failed turn",
              rc == 0 and failed is True, (rc, failed))
        script.write_text(
            "import json\n"
            "print(json.dumps({'type':'status','phase':'turn_end',"
            "'reason':{'kind':'completed'}}), flush=True)\n",
            encoding="utf-8")
        rc, failed = dots.run_dsh_streaming([sys.executable, str(script)], {})
        check("the current completed event is accepted by the wrapper",
              rc == 0 and failed is False, (rc, failed))


def test_live_probe():
    if os.environ.get("PAPER_DOTS_LIVE") not in ("1", "true", "yes"):
        print("[skip] live endpoint probe  -- set PAPER_DOTS_LIVE=1 to enable")
        return
    c = dots.config(None)
    ok, ids, err = dots.probe_endpoint(c)
    check("live Dots endpoint answers", ok and c["model"] in ids, err or str(ids))


def main():
    for fn in (test_argv_and_patch, test_probe_chat_and_tools, test_key_preflight,
               test_pipeline_integration, test_dsh_turn_events, test_live_probe):
        try:
            fn()
        except Exception as e:                                        # noqa: BLE001
            check(f"{fn.__name__} runs", False, f"{type(e).__name__}: {e}")
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("\nPASSED: dots adapter checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the 3.11.0 model/harness split (2026-11-10).

`--agent-model` and `--agent-harness` choose the two axes independently; the
legacy `--agent` / `--judge-agent` names keep their old commands. No network or
real model call is used.

Run: python3 .paper_test/test_agent_model_harness_2026_1110.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
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


pipe = load("paper_model_harness_pipe", WS / "paper_pipeline.py")
router = load("paper_model_harness_router", WS / "paper_model_agent.py")
dots = load("paper_model_harness_dots", WS / "paper_dots_agent.py")
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def test_parser():
    print()
    print("== the CLI options ==")
    parser = pipe.build_parser()
    got = parser.parse_args(["run", "--root", "/tmp/x"])
    check("the old --agent is unset by default (the new pair owns the default)",
          got.agent is None and got.agent_harness is None and got.agent_model is None)
    got = parser.parse_args(["run", "--root", "/tmp/x", "--agent-harness", "dsh",
                             "--agent-model", "deepseek-flash"])
    check("the new pair parses",
          got.agent is None and got.agent_harness == "dsh"
          and got.agent_model == "deepseek-flash")
    got = parser.parse_args(["run", "--root", "/tmp/x",
                             "--judge-agent-harness", "gpt-codex",
                             "--judge-agent-model", "gpt-sol"])
    check("the judge pair parses",
          got.judge_agent is None and got.judge_agent_harness == "gpt-codex"
          and got.judge_agent_model == "gpt-sol")
    got = parser.parse_args(["run", "--root", "/tmp/x",
                             "--agent-model", "http://127.0.0.1:8000/v1/chat/completions",
                             "--agent-model-api-key", "sk-local",
                             "--agent-model-name", "qwen3.8-27b"])
    check("an arbitrary endpoint, key and model name parse",
          got.agent_model == "http://127.0.0.1:8000/v1/chat/completions"
          and got.agent_model_api_key == "sk-local"
          and got.agent_model_name == "qwen3.8-27b")
    got = parser.parse_args(["run", "--root", "/tmp/x",
                             "--agent-model", "http://127.0.0.1:8000/v1/chat/completions",
                             "--agent-model-prep-json",
                             '{"temperature":0.2,"max_tokens":4096}',
                             "--judge-agent-model-prep-json",
                             '{"reasoning_effort":"high"}'])
    check("the prep-json options parse",
          "temperature" in got.agent_model_prep_json
          and "reasoning_effort" in got.judge_agent_model_prep_json)
    got = parser.parse_args(["run", "--root", "/tmp/x",
                             "--agent", "dsh", "--judge-agent", "codex"])
    check("the legacy options still parse",
          got.agent == "dsh" and got.judge_agent == "codex")
    check("the model choices include the harness-default sentinel",
          tuple(pipe.AGENT_MODEL_CHOICES) == (
              "deepseek-flash", "gpt-sol", "gpt-terra", "claude-opus",
              "claude-sonnet", "qwen38-27b", "dots3-note-preview", "default"),
          str(pipe.AGENT_MODEL_CHOICES))
    check("the harness choices are the requested three",
          tuple(pipe.AGENT_HARNESS_CHOICES) == ("dsh", "gpt-codex", "claude-code"),
          str(pipe.AGENT_HARNESS_CHOICES))


def test_resolution():
    print()
    print("== the support matrix and command resolution ==")
    pairs = [
        ("dsh", "deepseek-flash"), ("gpt-codex", "gpt-sol"),
        ("gpt-codex", "gpt-terra"), ("claude-code", "claude-opus"),
        ("claude-code", "claude-sonnet"), ("dsh", "gpt-sol"),
        ("dsh", "claude-opus"), ("gpt-codex", "deepseek-flash"),
        ("claude-code", "deepseek-flash"), ("dsh", "qwen38-27b"),
        ("gpt-codex", "qwen38-27b"), ("claude-code", "qwen38-27b"),
        ("dsh", "dots3-note-preview"),
        ("gpt-codex", "dots3-note-preview"),
        ("claude-code", "dots3-note-preview"),
    ]
    for harness, model in pairs:
        argv = pipe.agent_argv_for(harness, model)
        check(f"{harness}/{model} resolves",
              bool(argv) and Path(argv[0]).is_file(), str(argv[:4]))
    url = "http://127.0.0.1:8000/v1/chat/completions"
    argv = pipe.agent_argv_for("dsh", url, api_key_env="PAPER_AGENT_MODEL_API_KEY",
                               model_name="local-model",
                               prep_json='{"temperature":0.2}')
    check("a custom endpoint routes through the model adapter on dsh",
          "--endpoint" in argv and url in argv and "--model-name" in argv
          and "--prep-json" in argv
          and Path(argv[0]).name == "paper_model_agent.py", str(argv))
    try:
        pipe.agent_argv_for("gpt-codex", url)
    except SystemExit as e:
        check("a custom endpoint is refused on gpt-codex", e.code != 0)
    else:
        check("a custom endpoint is refused on gpt-codex", False)
    for harness, model in (("claude-code", "gpt-sol"),
                           ("gpt-codex", "claude-opus")):
        try:
            pipe.agent_argv_for(harness, model)
        except SystemExit as e:
            check(f"{harness}/{model} is refused before a session", e.code != 0, str(e))
        else:
            check(f"{harness}/{model} is refused before a session", False)
    check("legacy --agent codex keeps its old command",
          pipe.resolve_agent_cmd("codex", None, use_env=False)[0] == "codex")
    check("the no-option default is dsh + deepseek-flash",
          pipe._agent_pair_from_options(None, None) == ("dsh", "deepseek-flash"),
          str(pipe._agent_pair_from_options(None, None)))
    check("a harness alone fills its default model",
          pipe._agent_pair_from_options("claude-code", None)
          == ("claude-code", "claude-sonnet"))
    check("a model alone fills its default harness",
          pipe._agent_pair_from_options(None, "gpt-terra")
          == ("gpt-codex", "gpt-terra"))
    check("the model router is a frozen module",
          "paper_model_agent.py" in pipe.PIPELINE_MODULE_FILES)
    env = dots.claude_env(dots.config(type("A", (), {
        "harness": "claude", "model": "dots3-note-prev",
        "base_url": dots.DEFAULT_BASE_URL, "api_key": "sk-test",
        "reasoning_effort": None})()))
    check("dots+claude uses the Anthropic root and the documented env",
          env["ANTHROPIC_BASE_URL"] == "https://note3-prev-api.askdiandian.com"
          and env["ANTHROPIC_AUTH_TOKEN"] == "sk-test"
          and env["ANTHROPIC_MODEL"] == "dots3-note-prev", str(env)[:300])


def test_registry_agreement():
    print()
    print("== the pipeline and router registries agree ==")
    for name, info in pipe.AGENT_MODELS.items():
        if info.get("family") in ("qwen", "dots"):
            continue
        check(f"{name} id agrees with paper_model_agent",
              router.MODELS.get(name, {}).get("id") == info.get("id"),
              f"{router.MODELS.get(name)} vs {info}")
        check(f"{name} harness support agrees",
              set(router._COMPATIBLE.get(name) or ()) == set(info.get("harnesses") or ()),
              f"{router._COMPATIBLE.get(name)} vs {info.get('harnesses')}")


def test_router_configs():
    print()
    print("== paper_model_agent.py's per-harness configuration ==")
    c = router.config(type("A", (), {"harness": "dsh", "model": "deepseek-flash"})())
    patch = router.dsh_patch_text(c)
    check("dsh deepseek uses the official provider",
          "provider: deepseek-official" in patch and 'model: "deepseek-flash"' in patch)
    c = router.config(type("A", (), {"harness": "dsh", "model": "gpt-sol"})())
    patch = router.dsh_patch_text(c)
    check("dsh gpt uses the openai route",
          "provider: openai" in patch and 'model: "gpt-6.1-sol"' in patch)
    c = router.config(type("A", (), {"harness": "dsh", "model": "claude-opus"})())
    patch = router.dsh_patch_text(c)
    check("dsh claude uses the anthropic route",
          "provider: anthropic" in patch and 'model: "claude-opus-5-5"' in patch)
    c = router.config(type("A", (), {"harness": "gpt-codex", "model": "gpt-sol"})())
    argv = router.codex_argv(c)
    check("codex gpt selects the model with -m",
          "-m" in argv and argv[argv.index("-m") + 1] == "gpt-6.1-sol", str(argv))
    c = router.config(type("A", (), {"harness": "gpt-codex",
                                     "model": "deepseek-flash"})())
    argv = router.codex_argv(c)
    text = " ".join(argv)
    check("codex deepseek uses the documented Responses provider",
          'model_provider="deepseek"' in text
          and 'base_url="https://api.deepseek.com"' in text
          and 'env_key="DEEPSEEK_API_KEY"' in text
          and 'wire_api="responses"' in text, text[:300])
    c = router.config(type("A", (), {"harness": "claude-code",
                                     "model": "claude-opus"})())
    argv = router.claude_argv(c)
    check("claude-code opus uses the latest alias",
          argv[argv.index("--model") + 1] == "opus", str(argv))
    c = router.config(type("A", (), {"harness": "claude-code",
                                     "model": "deepseek-flash"})())
    env = router.claude_env(c)
    check("claude-code deepseek uses its Anthropic-compatible endpoint",
          env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
          and env["ANTHROPIC_MODEL"] == "deepseek-flash[1m]")
    c = router.config(type("A", (), {"harness": "claude-code", "model": "gpt-sol"})())
    check("the router refuses an impossible pair",
          "cannot run on" in router._pair_problem(c))
    url = "http://127.0.0.1:8000/v1/chat/completions"
    c = router.config(type("A", (), {
        "harness": "dsh", "endpoint": url,
        "api_key_env": "PAPER_AGENT_MODEL_API_KEY",
        "model_name": "local-model", "model": None})())
    check("the custom endpoint base strips /chat/completions",
          c["base_url"] == "http://127.0.0.1:8000/v1", c["base_url"])
    patch = router.dsh_patch_text(c)
    check("the custom endpoint patch uses the provider and key env",
          "provider: endpoint" in patch and "apiKeyEnv: PAPER_AGENT_MODEL_API_KEY" in patch
          and 'baseURL: "http://127.0.0.1:8000/v1"' in patch
          and 'model: "local-model"' in patch, patch[:300])
    default_request = {"model": "m", "temperature": 0.7,
                       "reasoning": {"summary": "auto"}}
    merged = router.deep_merge(default_request,
                               {"temperature": 0.2,
                                "reasoning": {"effort": "high"}})
    check("prep-json deep-merges and leaves omitted defaults alone",
          merged["temperature"] == 0.2
          and merged["reasoning"] == {"summary": "auto", "effort": "high"}
          and merged["model"] == "m", str(merged))
    redacted = pipe.redact_secrets(
        "--agent-model-api-key sk-secret-123 --judge-agent-model-api-key sk-judge-456")
    check("the custom endpoint keys are redacted from a logged argv",
          "sk-secret-123" not in redacted and "sk-judge-456" not in redacted
          and redacted.count("[REDACTED]") == 2, redacted)
    c2 = router.config(type("A", (), {
        "harness": "dsh", "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "api_key_env": "PAPER_AGENT_MODEL_API_KEY",
        "model_name": None, "model": None})())
    real_catalog = router._endpoint_catalog
    router._endpoint_catalog = lambda _cfg: [{"id": "a"}, {"id": "b"}]
    try:
        _name, err = router.resolve_endpoint_model(c2)
    finally:
        router._endpoint_catalog = real_catalog
    check("a multi-model endpoint asks for --agent-model-name",
          "lists" in err and "--agent-model-name" in err, err)
    got = pipe.effective_agent_model([str(WS / "paper_model_agent.py"),
                                      "--harness", "gpt-codex",
                                      "--model", "gpt-terra"])
    check("the run record can name the router's model and harness",
          got.get("name") == "gpt-terra" and got.get("harness") == "gpt-codex"
          and got.get("id") == "gpt-6.1-terra", str(got))


def test_prep_proxy():
    print()
    print("== the prep-json proxy deep-merges every request ==")
    seen = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            seen.append(json.loads(self.rfile.read(n) or b"{}"))
            raw = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = HTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    proxy = ""
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
        proxy, err = router.start_prep_proxy(
            base, {"temperature": 0.2, "max_tokens": 321,
                   "reasoning": {"effort": "high"}})
        check("the prep proxy starts", bool(proxy) and not err, err)
        req = urllib.request.Request(
            proxy + "/chat/completions",
            data=json.dumps({"model": "m", "temperature": 0.7,
                             "reasoning": {"summary": "auto"},
                             "messages": []}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        check("the proxy forwards the merged request",
              body.get("ok") is True and bool(seen), str(body))
        got = seen[0]
        check("prep overrides the call's own values and keeps omitted defaults",
              got.get("temperature") == 0.2 and got.get("max_tokens") == 321
              and got.get("reasoning") == {"summary": "auto", "effort": "high"},
              str(got))
    finally:
        router.stop_prep_proxy()
        srv.shutdown()


def test_run_policy():
    print()
    print("== the run record names both axes ==")
    sys.path.insert(0, str(HERE))
    import only_rounds_lib as lib
    tmp = Path(tempfile.mkdtemp(prefix="model_harness_"))
    try:
        root = lib.make_root(tmp, rounds=1, rewrites="1", revises="1", judges="1")
        p = lib.cli(
            "run", "--root", str(root),
            "--agent-cmd", json.dumps([sys.executable, str(lib.STUB)]),
            "--judge-agent-cmd", json.dumps([sys.executable, str(lib.STUB_JUDGE)]),
            "--retries", "1", "--only", "1:w1",
            "--agent-harness", "dsh", "--agent-model", "deepseek-flash",
            "--judge-agent-harness", "gpt-codex", "--judge-agent-model", "gpt-sol")
        check("the selected stage ran", p.returncode == 3, (p.stdout + p.stderr)[-300:])
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        pol = state.get("run_policy") or {}
        check("the producer pair is recorded",
              pol.get("agent_harness") == "dsh"
              and pol.get("agent_model") == "deepseek-flash", str(pol)[:300])
        check("the judge pair is recorded independently",
              pol.get("judge_agent_harness") == "gpt-codex"
              and pol.get("judge_agent_model") == "gpt-sol", str(pol)[:300])
        prov = state.get("judge_provider") or {}
        check("judge_provider names both pairs",
              prov.get("producer_harness") == "dsh"
              and prov.get("producer_model") == "deepseek-flash"
              and prov.get("judge_harness") == "gpt-codex"
              and prov.get("judge_model") == "gpt-sol", str(prov)[:400])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_help():
    print()
    print("== the documented surface ==")
    import subprocess
    out = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "run", "--help"],
                         capture_output=True, text=True, timeout=120).stdout
    for flag in ("--agent-harness", "--agent-model",
                 "--agent-model-api-key", "--agent-model-name",
                 "--agent-model-prep-json",
                 "--judge-agent-harness", "--judge-agent-model",
                 "--judge-agent-model-api-key", "--judge-agent-model-name",
                 "--judge-agent-model-prep-json"):
        check(f"--help lists {flag}", flag in out)
    readme = (WS / "README.md").read_text(encoding="utf-8")
    check("README documents the model/harness pair",
          "--agent-harness" in readme and "--agent-model" in readme
          and "deepseek-flash" in readme and "gpt-6.1-sol" in readme)


def main():
    for fn in (test_parser, test_resolution, test_registry_agreement,
               test_router_configs, test_prep_proxy, test_run_policy, test_help):
        try:
            fn()
        except Exception as e:                                        # noqa: BLE001
            check(f"{fn.__name__} runs", False, f"{type(e).__name__}: {e}")
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("\nPASSED: model/harness split checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

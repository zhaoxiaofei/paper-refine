#!/usr/bin/env python3
"""Regression checks for the agent-adapter candidates of the 2026-11-22 11:28
fix-bugs wave (batch M1).

Run: python3 .paper_test/test_fix_wave1_M1_agents.py

  F15  a malformed bracketed --base-url is a clean usage error, not a traceback
  F42  signed-URL credentials are split out of the endpoint before display/argv
  F48  the Dots dsh path reports an invalid endpoint instead of a traceback
  F49  the Dots missing-key preflight survives a malformed host
  F53  an explicit --model is not overridden by an ambient endpoint variable
  F66  an invalid PAPER_AGENT_REASONING_EFFORT is a clean usage error
  F177 the tunnel URL keeps the endpoint query
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
AGENT_COMMON = WS / "agent-common"
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def run(script, *args, env_extra=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{WS}:{AGENT_COMMON}"
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(WS / script)] + list(args),
                          capture_output=True, text=True, timeout=120, env=env)


def no_traceback(p, code=2):
    out = p.stdout + p.stderr
    return p.returncode == code and "Traceback (most recent call last)" not in out


def test_cli_clean_errors():
    p = run("paper_qwen_agent.py", "--base-url", "http://[::1", "--probe")
    check("F15 qwen malformed bracketed host is a clean usage error", no_traceback(p),
          (p.stdout + p.stderr)[-300:])
    p = run("paper_dots_agent.py", "--base-url", "http://[::1", "--harness", "chat")
    check("F49 dots missing-key preflight survives the malformed host", no_traceback(p),
          (p.stdout + p.stderr)[-300:])
    p = run("paper_dots_agent.py", "--harness", "dsh", "--base-url", "not-a-url",
            "--api-key", "x", env_extra={"PAPER_DOTS_SKIP_PROBE": "1"})
    check("F48 the dots dsh path reports an invalid endpoint", no_traceback(p),
          (p.stdout + p.stderr)[-300:])
    p = run("paper_qwen_agent.py", "--probe",
            env_extra={"PAPER_AGENT_REASONING_EFFORT": "banana"})
    check("F66 an invalid reasoning effort is a clean usage error", no_traceback(p),
          (p.stdout + p.stderr)[-300:])


def _import_adapter(name):
    for entry in (str(WS), str(AGENT_COMMON)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location(name, WS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_credential_and_tunnel():
    os.environ["PYTHONPATH"] = f"{WS}:{AGENT_COMMON}"
    q = _import_adapter("paper_qwen_agent")
    cfg = q.config(argparse.Namespace(
        base_url="http://127.0.0.1:9/v1?X-Goog-Signature=SUPERSECRET"))
    check("F42 the signed-URL credential leaves the base URL",
          "SUPERSECRET" not in cfg["base_url"] and cfg["api_key"] == "SUPERSECRET",
          f"base={cfg['base_url']!r}")
    argv = q.codex_argv(cfg)
    check("F42 the credential never reaches the codex argv",
          not any("SUPERSECRET" in str(v) for v in argv))
    cfg2 = q.config(argparse.Namespace(base_url="http://example:8000/v1?model=qwen"))
    check("F177 the tunnel URL keeps the endpoint query",
          q._local_tunnel_url(cfg2) == "http://127.0.0.1:8000/v1?model=qwen",
          q._local_tunnel_url(cfg2))


def test_explicit_model_wins():
    os.environ["PYTHONPATH"] = f"{WS}:{AGENT_COMMON}"
    os.environ["PAPER_AGENT_MODEL_ENDPOINT"] = "http://127.0.0.1:9/v1"
    try:
        m = _import_adapter("paper_model_agent")
        cfg = m.config(argparse.Namespace(model="deepseek-flash"))
        check("F53 an explicit --model excludes the ambient endpoint",
              cfg["family"] != "endpoint" and cfg["model"] == "deepseek-flash",
              f"family={cfg['family']} model={cfg['model']}")
    finally:
        os.environ.pop("PAPER_AGENT_MODEL_ENDPOINT", None)


def main() -> int:
    test_cli_clean_errors()
    test_credential_and_tunnel()
    test_explicit_model_wins()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL M1 AGENT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

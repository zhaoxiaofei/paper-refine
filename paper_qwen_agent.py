#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3.8-27B agent adapter for the paper-refine pipeline.

The pipeline normally launches a coding harness (`codex exec`, `dsh
--profile headless`, ...). This adapter keeps that harness and points it at an
OpenAI-compatible vLLM server:

    ssh -p 52080 -N -L 18000:127.0.0.1:8000 zxf@101.6.31.113
    curl http://127.0.0.1:18000/v1/models
    {"data":[{"id":"qwen3.8-27b", ...}]}

It is selected with `--agent qwen` (or `"agent": "qwen"` in
pipeline_config.json). The harness is chosen with PAPER_QWEN_HARNESS:

    codex  (default)  `codex exec` with a custom `model_provider=qwen` route
    dsh               `dsh --profile headless` with a generated llm-pi-ai patch
    chat              a direct /v1/chat/completions call (text-only; no tools)

The SSH tunnel is started only when the endpoint is not already reachable. A
tunnel this process started is stopped on exit; a tunnel the operator already
had is left alone.

Environment (all optional):

    PAPER_QWEN_BASE_URL        default http://127.0.0.1:18000/v1
    PAPER_QWEN_MODEL           default qwen3.8-27b
    PAPER_QWEN_API_KEY         default `dummy` (vLLM usually needs no key)
    PAPER_QWEN_HARNESS         codex | dsh | chat (default codex)
    PAPER_QWEN_REASONING_EFFORT low | medium | xhigh (default low; qwen
                                rejects codex's `max`)
    PAPER_QWEN_TUNNEL          auto | off | require (default auto)
    PAPER_QWEN_SSH_HOST        default zxf@101.6.31.113
    PAPER_QWEN_SSH_PORT        default 52080
    PAPER_QWEN_TUNNEL_LOCAL    default 18000
    PAPER_QWEN_TUNNEL_REMOTE   default 127.0.0.1:8000
    PAPER_QWEN_CONTEXT_WINDOW  default 32768
    PAPER_QWEN_MAX_TOKENS      default 8192
    PAPER_QWEN_CHECK_TOOLS     1 = probe tool-call support before the harness

`python3 paper_qwen_agent.py --probe` reports the endpoint, model, tunnel and
tool-call support without running a session. `--chat` reads a prompt from
stdin and prints the model's text (for text-only jobs). `--check-tools` exits
0/1 on whether the server accepts `tool_choice=auto`; the live server may need
`--enable-auto-tool-choice --tool-call-parser <parser>` for agentic sessions.

Design boundary: the adapter does not reimplement the harness. It only writes
the provider configuration the harness already understands, forwards the
session's stdin/stdout, and records a capability gap (no tool calls) rather
than silently producing a text-only answer from a stage that needed tools.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:18000/v1"
DEFAULT_MODEL = "qwen3.8-27b"
DEFAULT_API_KEY = "dummy"
DEFAULT_HARNESS = "codex"
DEFAULT_EFFORT = "low"
DEFAULT_SSH_HOST = "zxf@101.6.31.113"
DEFAULT_SSH_PORT = "52080"
DEFAULT_LOCAL_PORT = "18000"
DEFAULT_REMOTE = "127.0.0.1:8000"

_TUNNEL = None          # the ssh process THIS adapter started
_TUNNEL_STDERR = None   # a temporary file holding its stderr
_DSH_HOME_TMP = None    # a temporary DSH_HOME copy for a read-only ~/.dsh
_PATCH_TMP = None       # the generated dsh patch file


def _env(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def config(args=None) -> dict:
    """Resolve the effective endpoint/harness configuration (args > env)."""
    args = args or argparse.Namespace()
    base = (getattr(args, "base_url", None) or _env("PAPER_QWEN_BASE_URL",
                                                   DEFAULT_BASE_URL)).rstrip("/")
    return {
        "base_url": base,
        "model": getattr(args, "model", None) or _env("PAPER_QWEN_MODEL", DEFAULT_MODEL),
        "api_key": getattr(args, "api_key", None) or _env("PAPER_QWEN_API_KEY",
                                                          DEFAULT_API_KEY),
        "harness": (getattr(args, "harness", None)
                    or _env("PAPER_QWEN_HARNESS", DEFAULT_HARNESS)).lower(),
        "effort": (getattr(args, "reasoning_effort", None)
                   or _env("PAPER_QWEN_REASONING_EFFORT", DEFAULT_EFFORT)).lower(),
        "tunnel": (getattr(args, "tunnel", None)
                   or _env("PAPER_QWEN_TUNNEL", "auto")).lower(),
        "ssh_host": getattr(args, "ssh_host", None) or _env("PAPER_QWEN_SSH_HOST",
                                                            DEFAULT_SSH_HOST),
        "ssh_port": str(getattr(args, "ssh_port", None) or _env("PAPER_QWEN_SSH_PORT",
                                                               DEFAULT_SSH_PORT)),
        "local_port": str(getattr(args, "local_port", None)
                          or _env("PAPER_QWEN_TUNNEL_LOCAL", DEFAULT_LOCAL_PORT)),
        "remote": getattr(args, "remote", None) or _env("PAPER_QWEN_TUNNEL_REMOTE",
                                                       DEFAULT_REMOTE),
        "context_window": _int_env("PAPER_QWEN_CONTEXT_WINDOW", 32768),
        "max_tokens": _int_env("PAPER_QWEN_MAX_TOKENS", 8192),
        "check_tools": bool(_int_env("PAPER_QWEN_CHECK_TOOLS", 0)),
    }


def _request(method: str, url: str, payload: dict = None, api_key: str = "",
             timeout: float = 10.0) -> tuple:
    """(status, parsed-body-or-text, error) for one JSON request."""
    data = None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw), ""
            except ValueError:
                return resp.status, raw, ""
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw
        return e.code, body, ""
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return 0, None, f"{type(e).__name__}: {e}"


def probe_endpoint(cfg: dict, timeout: float = 4.0) -> tuple:
    """(ok, model_ids, error) from GET {base}/models."""
    status, body, err = _request("GET", f"{cfg['base_url']}/models",
                                 api_key=cfg["api_key"], timeout=timeout)
    if err or status != 200 or not isinstance(body, dict):
        return False, [], err or f"HTTP {status}: {str(body)[:160]}"
    ids = [str(m.get("id")) for m in (body.get("data") or []) if isinstance(m, dict)]
    return True, ids, ""


def _port_open(host: str, port: str, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def _stop_tunnel() -> None:
    global _TUNNEL, _TUNNEL_STDERR
    if _TUNNEL is not None:
        try:
            _TUNNEL.terminate()
            _TUNNEL.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            try:
                _TUNNEL.kill()
            except OSError:
                pass
        _TUNNEL = None
    if _TUNNEL_STDERR is not None:
        try:
            _TUNNEL_STDERR.close()
        except OSError:
            pass
        _TUNNEL_STDERR = None


def ensure_tunnel(cfg: dict, log=None) -> str:
    """Make the endpoint reachable; return "" or an error message.

    If it is already reachable, nothing is started (the operator's tunnel is
    left alone). Otherwise an ssh local-forward is started, waited for, and
    terminated at process exit. All progress goes to stderr: the harness's
    stdout is the session transcript (and `dsh --json` is a JSON-lines stream).
    """
    if log is None:
        def log(msg):
            print(msg, file=sys.stderr)
    global _TUNNEL, _TUNNEL_STDERR
    ok, ids, err = probe_endpoint(cfg)
    mode = str(cfg.get("tunnel") or "auto").strip().lower()
    if ok and mode != "require":
        log(f"[qwen] endpoint reachable: {cfg['base_url']} (models: "
            f"{', '.join(ids) or '(none)'})")
        return ""
    if ok and mode == "require":
        log("[qwen] --tunnel require: the endpoint is directly reachable, but this "
            "mode still requires the ssh tunnel")
    if cfg["tunnel"] in ("off", "0", "false", "no"):
        return (f"qwen endpoint {cfg['base_url']} is not reachable and "
                f"PAPER_QWEN_TUNNEL=off: {err}")
    if not shutil.which("ssh"):
        return "qwen endpoint is not reachable and `ssh` is not on PATH"
    if _port_open("127.0.0.1", cfg["local_port"]):
        return (f"port {cfg['local_port']} is already listening but "
                f"{cfg['base_url']}/models did not answer ({err}); another "
                f"service may own the port -- stop it or change "
                f"PAPER_QWEN_TUNNEL_LOCAL")
    cmd = ["ssh", "-p", cfg["ssh_port"], "-N",
           "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
           "-o", "ServerAliveInterval=30",
           "-L", f"{cfg['local_port']}:{cfg['remote']}", cfg["ssh_host"]]
    _TUNNEL_STDERR = tempfile.TemporaryFile(mode="w+b")
    try:
        _TUNNEL = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                   stderr=_TUNNEL_STDERR)
    except OSError as e:
        _stop_tunnel()
        return f"could not start the qwen ssh tunnel: {type(e).__name__}: {e}"
    atexit.register(_stop_tunnel)
    deadline = time.time() + 20
    while time.time() < deadline:
        if _TUNNEL.poll() is not None:
            break
        ok, ids, err = probe_endpoint(cfg, timeout=2.0)
        if ok:
            log(f"[qwen] started ssh tunnel pid {_TUNNEL.pid}: "
                f"localhost:{cfg['local_port']} -> {cfg['ssh_host']}:"
                f"{cfg['ssh_port']} -> {cfg['remote']}; models: {', '.join(ids)}")
            _TUNNEL_STDERR.seek(0)
            return ""
        time.sleep(0.4)
    detail = ""
    if _TUNNEL_STDERR is not None:
        try:
            _TUNNEL_STDERR.seek(0)
            detail = _TUNNEL_STDERR.read().decode("utf-8", "replace").strip()
        except OSError:
            detail = ""
    _stop_tunnel()
    return (f"could not establish the qwen tunnel `{' '.join(cmd)}`"
            + (f": {detail[:400]}" if detail else f": {err}")
            + ". Run the tunnel manually and retry, or set PAPER_QWEN_TUNNEL=off "
              "once it is up.")


def check_tools(cfg: dict, timeout: float = 30.0) -> tuple:
    """(supported, detail) for tool_choice=auto on the chat endpoint."""
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 8,
        "tools": [{"type": "function", "function": {
            "name": "ping", "description": "ping",
            "parameters": {"type": "object", "properties": {}}}}],
        "tool_choice": "auto",
    }
    status, body, err = _request("POST", f"{cfg['base_url']}/chat/completions",
                                 payload=payload, api_key=cfg["api_key"],
                                 timeout=timeout)
    if err:
        return False, err
    if status == 200:
        return True, "tool_choice=auto accepted"
    return False, f"HTTP {status}: {json.dumps(body)[:300] if not isinstance(body, str) else body[:300]}"


def codex_argv(cfg: dict, extra: list = None) -> list:
    """`codex exec` with a custom qwen provider route.

    The installed codex (0.163) accepts only `wire_api = "responses"`; the vLLM
    server exposes `/v1/responses`, so the route is wired to that API. Qwen
    rejects codex's `max` reasoning effort; the adapter defaults to `low` and
    passes it explicitly.
    """
    overrides = [
        'model_provider="qwen"',
        f'model="{cfg["model"]}"',
        f'model_providers.qwen.name="Qwen vLLM ({cfg["model"]})"',
        f'model_providers.qwen.base_url="{cfg["base_url"]}"',
        'model_providers.qwen.env_key="PAPER_QWEN_API_KEY"',
        'model_providers.qwen.wire_api="responses"',
        f'model_reasoning_effort="{cfg["effort"]}"',
    ]
    argv = ["codex", "exec"]
    for value in overrides:
        argv += ["-c", value]
    # `extra` is already an argv fragment (codex_mcp_overrides returns
    # `-c VALUE` pairs); append it verbatim so the final prompt `-` stays last.
    argv += [str(v) for v in (extra or [])]
    argv += ["-"]
    return argv


def dsh_patch_text(cfg: dict) -> str:
    """The `llm-pi-ai` route + default-model patch for dsh."""
    return f"""# Generated by paper_qwen_agent.py -- do not edit in place.
- id: llm-pi-ai
  config:
    providers:
      qwen:
        displayName: "Qwen vLLM ({cfg['model']})"
        apiKeyEnv: PAPER_QWEN_API_KEY
        api: openai-completions
        baseURL: "{cfg['base_url']}"
        models:
          - id: "{cfg['model']}"
            name: "Qwen3.8-27B"
            contextWindow: {cfg['context_window']}
            maxTokens: {cfg['max_tokens']}
            reasoningEfforts:
              low: low
              medium: medium
              xhigh: xhigh
- id: agent-default-model
  config:
    provider: qwen
    model: "{cfg['model']}"
    reasoningEffort: "{cfg['effort']}"
"""


def _writable(path: Path) -> bool:
    try:
        probe = path / ".paper_qwen_write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def ensure_dsh_home() -> tuple:
    """(DSH_HOME, error). A read-only installed home gets a light temp copy."""
    global _DSH_HOME_TMP
    home = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh")).expanduser()
    if home.is_dir() and _writable(home):
        return str(home), ""
    src = home / "profiles" / "headless"
    if not src.is_dir():
        return "", (f"the dsh profile is missing: {src}; install "
                    f"@deepseek-ai/dsh and create the headless profile")
    tmp = Path(tempfile.mkdtemp(prefix="paper-qwen-dsh-"))
    _DSH_HOME_TMP = tmp
    dst = tmp / "profiles" / "headless"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "cordis.yml", "cordis.patch.yml",
                 "pnpm-workspace.yaml", "pnpm-lock.yaml"):
        s = src / name
        if s.is_file():
            shutil.copy2(s, dst / name)
    nm = src / "node_modules"
    if nm.is_dir():
        try:
            os.symlink(nm, dst / "node_modules")
        except OSError:
            shutil.copytree(nm, dst / "node_modules", symlinks=True)
    cred = home / ".credentials.yaml"
    if cred.is_file():
        shutil.copy2(cred, tmp / ".credentials.yaml")
    return str(tmp), ""


def _cleanup() -> None:
    global _DSH_HOME_TMP, _PATCH_TMP
    _stop_tunnel()
    if _DSH_HOME_TMP is not None:
        shutil.rmtree(_DSH_HOME_TMP, ignore_errors=True)
        _DSH_HOME_TMP = None
    if _PATCH_TMP is not None:
        try:
            Path(_PATCH_TMP).unlink()
        except OSError:
            pass
        _PATCH_TMP = None


def dsh_argv(cfg: dict) -> tuple:
    """(argv, env, error) for `dsh --profile headless --patch ... --json -`."""
    global _PATCH_TMP
    home, err = ensure_dsh_home()
    if err:
        return [], {}, err
    fd, patch = tempfile.mkstemp(prefix="paper-qwen-", suffix=".patch.yml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(dsh_patch_text(cfg))
    _PATCH_TMP = patch
    env = dict(os.environ, DSH_HOME=home, PAPER_QWEN_API_KEY=cfg["api_key"])
    return (["dsh", "--profile", "headless", "--patch", patch, "--json", "-"],
            env, "")


def chat_text(cfg: dict, prompt: str, system: str = "") -> tuple:
    """(text, error) from one /v1/chat/completions call."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": cfg["model"], "messages": messages,
               "temperature": 0, "max_tokens": cfg["max_tokens"]}
    status, body, err = _request("POST", f"{cfg['base_url']}/chat/completions",
                                 payload=payload, api_key=cfg["api_key"],
                                 timeout=600.0)
    if err or status != 200 or not isinstance(body, dict):
        return "", err or f"HTTP {status}: {str(body)[:400]}"
    try:
        message = body["choices"][0]["message"]
        content = message.get("content")
        if isinstance(content, list):
            # The chat API may return content parts; `str(list)` used to ship a
            # Python repr as the answer.
            content = "".join(str(part.get("text") or "")
                              for part in content
                              if isinstance(part, dict) and part.get("type") == "text")
        if not isinstance(content, str) or not content.strip():
            # Qwen3 reasoning responses can carry the text in `reasoning_content`
            # and leave `content` null. `str(None)` made the wrapper report the
            # four characters "None" and exit 0.
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return reasoning, ""
            return "", f"empty chat content: {json.dumps(body)[:400]}"
        return content, ""
    except (KeyError, IndexError, TypeError, AttributeError):
        return "", f"unexpected chat response: {json.dumps(body)[:400]}"


def _print_probe(cfg: dict) -> int:
    ok, ids, err = probe_endpoint(cfg)
    print(f"base_url: {cfg['base_url']}")
    print(f"model:    {cfg['model']}")
    print(f"harness:  {cfg['harness']}")
    print(f"tunnel:   {cfg['tunnel']}")
    if not ok:
        print(f"endpoint: UNREACHABLE ({err})")
        return 1
    print(f"endpoint: reachable; models: {', '.join(ids) or '(none)'}")
    if cfg["model"] not in ids:
        print(f"model:    NOT SERVED (available: {', '.join(ids) or '(none)'})")
        return 1
    supported, detail = check_tools(cfg)
    print(f"tools:    {'accepted' if supported else 'NOT accepted'} ({detail})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--harness", choices=("codex", "dsh", "chat"), default=None,
                   help="which harness to point at qwen (default: PAPER_QWEN_HARNESS or codex)")
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--reasoning-effort", choices=("low", "medium", "xhigh"),
                   default=None)
    p.add_argument("--tunnel", choices=("auto", "off", "require"), default=None)
    p.add_argument("--ssh-host", default=None)
    p.add_argument("--ssh-port", default=None)
    p.add_argument("--local-port", default=None)
    p.add_argument("--remote", default=None)
    p.add_argument("--codex-extra-args", default=None,
                   help="JSON list of extra `codex exec` argv values (MCP approvals)")
    p.add_argument("--system", default="", help="chat-mode system prompt")
    p.add_argument("--probe", action="store_true",
                   help="print endpoint/model/tool support and exit")
    p.add_argument("--check-tools", action="store_true",
                   help="exit 0/1 on whether tool_choice=auto is accepted")
    p.add_argument("--require-tools", action="store_true",
                   help="fail instead of warning when tool calls are unsupported")
    p.add_argument("--chat", action="store_true",
                   help="read a prompt from stdin and print one chat completion")
    args = p.parse_args(argv)
    cfg = config(args)
    atexit.register(_cleanup)
    if cfg["harness"] not in ("codex", "dsh", "chat"):
        print(f"qwen: unknown harness {cfg['harness']!r}; use codex, dsh or chat",
              file=sys.stderr)
        return 2
    if args.probe:
        # Diagnostics must run BEFORE the reachability gate: otherwise the
        # `endpoint: UNREACHABLE` / `model: NOT SERVED` report could never print.
        return _print_probe(cfg)
    err = ensure_tunnel(cfg)
    if err:
        print(f"qwen: {err}", file=sys.stderr)
        return 2
    ok, ids, perr = probe_endpoint(cfg)
    if not ok:
        print(f"qwen: endpoint {cfg['base_url']} did not answer: {perr}",
              file=sys.stderr)
        return 2
    if cfg["model"] not in ids:
        print(f"qwen: model {cfg['model']!r} is not served (available: "
              f"{', '.join(ids) or '(none)'})", file=sys.stderr)
        return 2
    if args.check_tools:
        supported, detail = check_tools(cfg)
        print(f"qwen tools: {'accepted' if supported else 'NOT accepted'} ({detail})")
        return 0 if supported else 1
    if args.chat or cfg["harness"] == "chat":
        prompt = sys.stdin.read() if not sys.stdin.isatty() else ""
        if not prompt.strip():
            print("qwen: chat mode needs a prompt on stdin", file=sys.stderr)
            return 2
        text, cerr = chat_text(cfg, prompt, system=args.system)
        if cerr:
            print(f"qwen: chat failed: {cerr}", file=sys.stderr)
            return 2
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    # dsh always sends tool definitions, so its failure is certain (and wastes a
    # full session) when the server rejects auto tool choice. Probe it once and
    # warn; a codex session is left to the harness (its Responses request may
    # not include tools until the model asks).
    need_tool_probe = (args.check_tools or args.require_tools or cfg["check_tools"]
                       or cfg["harness"] == "dsh")
    if need_tool_probe:
        supported, detail = check_tools(cfg)
        if not supported:
            msg = (f"the qwen endpoint does not accept tool_choice=auto ({detail}). "
                   f"An agentic {cfg['harness']} session will fail when it needs a "
                   f"tool. Start vLLM with `--enable-auto-tool-choice "
                   f"--tool-call-parser <parser>` (and the model's tool template), "
                   f"or use `--harness chat` for text-only calls.")
            if args.require_tools or cfg["check_tools"]:
                print(f"qwen: {msg}", file=sys.stderr)
                return 2
            print(f"[qwen] WARNING: {msg}", file=sys.stderr)
    env = dict(os.environ, PAPER_QWEN_API_KEY=cfg["api_key"],
               QWEN_API_KEY=cfg["api_key"])
    if cfg["harness"] == "codex":
        extra = []
        if args.codex_extra_args:
            try:
                extra = json.loads(args.codex_extra_args)
            except ValueError:
                print("qwen: --codex-extra-args must be a JSON list", file=sys.stderr)
                return 2
            if not isinstance(extra, list):
                print("qwen: --codex-extra-args must be a JSON list", file=sys.stderr)
                return 2
        cmd = codex_argv(cfg, extra=extra)
        print(f"[qwen] {cfg['base_url']} model={cfg['model']} harness=codex "
              f"effort={cfg['effort']}", file=sys.stderr)
    elif cfg["harness"] == "dsh":
        cmd, denv, derr = dsh_argv(cfg)
        if derr:
            print(f"qwen: {derr}", file=sys.stderr)
            return 2
        env.update(denv)
        print(f"[qwen] {cfg['base_url']} model={cfg['model']} harness=dsh "
              f"effort={cfg['effort']}", file=sys.stderr)
    else:
        print(f"qwen: unknown harness {cfg['harness']!r}", file=sys.stderr)
        return 2
    try:
        if cfg["harness"] == "dsh":
            # `dsh --json` can end a turn with a provider error and still exit
            # 0; the wrapper must surface that to the pipeline as a failure.
            proc = subprocess.run(cmd, stdin=sys.stdin, stdout=subprocess.PIPE,
                                  stderr=sys.stderr, env=env)
            out = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
            if out:
                sys.stdout.write(out)
                sys.stdout.flush()
            # Read the TERMINAL turn_end event, not two independent searches
            # over all stdout: an earlier tool error must not fail a successful
            # turn, and a failing turn_end need not carry `kind: error`.
            turn_failed = None
            for line in out.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("type") == "turn_end":
                    status = str(event.get("status") or "").lower()
                    kind = str(event.get("kind") or "").lower()
                    turn_failed = (status in ("error", "failed")
                                   or kind in ("error", "failed"))
            if turn_failed:
                print("qwen: dsh ended the turn with an error (see the JSON event "
                      "stream above)", file=sys.stderr)
                return int(proc.returncode or 0) or 2
            return int(proc.returncode or 0)
        proc = subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout,
                              stderr=sys.stderr, env=env)
    except FileNotFoundError:
        print(f"qwen: the {cfg['harness']} executable is not on PATH", file=sys.stderr)
        return 127
    return int(proc.returncode or 0)


if __name__ == "__main__":
    sys.exit(main())

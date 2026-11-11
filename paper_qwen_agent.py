#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3.8-27B agent adapter for the paper-refine pipeline.

The pipeline normally launches a coding harness (`codex exec`, `dsh
--profile headless`, ...). This adapter keeps that harness and points it at an
OpenAI-compatible vLLM server:

    ssh -p 52080 -N -L 8000:127.0.0.1:8000 zxf@101.6.31.113
    curl http://127.0.0.1:8000/v1/models
    {"data":[{"id":"qwen3.8-27b", ...}]}

It is selected with `--agent qwen` (or `"agent": "qwen"` in
pipeline_config.json). The harness is chosen with PAPER_QWEN_HARNESS:

    codex  (default)  `codex exec` with a custom `model_provider=qwen` route
    dsh               `dsh --profile headless` with a generated llm-pi-ai patch
    claude            `claude --print` against vLLM's Anthropic Messages
                      endpoint (when the server serves it)
    chat              a direct /v1/chat/completions call (text-only; no tools)

The SSH tunnel is started only when the endpoint is not already reachable. A
tunnel this process started is stopped on exit; a tunnel the operator already
had is left alone.

Environment (all optional):

    PAPER_QWEN_BASE_URL        default http://127.0.0.1:8000/v1
    PAPER_QWEN_MODEL           default qwen3.8-27b
    PAPER_QWEN_API_KEY         default `dummy` (vLLM usually needs no key)
    PAPER_QWEN_HARNESS         codex | dsh | claude | chat (default codex)
    PAPER_QWEN_REASONING_EFFORT low | medium | xhigh (default medium; qwen
                                rejects codex's `max`)
    PAPER_QWEN_TUNNEL          auto | off | require (default auto)
    PAPER_QWEN_SSH_HOST        default zxf@101.6.31.113
    PAPER_QWEN_SSH_PORT        default 52080
    PAPER_QWEN_TUNNEL_LOCAL    default 8000
    PAPER_QWEN_TUNNEL_REMOTE   default 127.0.0.1:8000
    PAPER_QWEN_CONTEXT_WINDOW  default 150000 (the deployment's window)
    PAPER_QWEN_MAX_TOKENS      default 32768 (harness replies; reasoning
                               tokens count toward it)
    PAPER_QWEN_CHAT_MAX_TOKENS  default 80000 (single-shot: reasoning + answer)
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
import contextlib
import http.client
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from agent_common import model_runtime as rt
except ImportError:  # a test loader may not put the submodule root on sys.path
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent / "agent-common"))
    from agent_common import model_runtime as rt

from agent_common.agent_cli import build_dsh_argv as _build_dsh_argv
from agent_common.chat import completion_budget, finish_reason_error, message_text
from agent_common.dsh_events import line_turn_end_failed as _line_turn_end_failed

#: The shared model catalog (canonical: ``repos/agent-common/agent_common/model_catalog.json``;
#: this checkout carries an identical copy).  The fallback keeps a checkout
#: refreshed from upstream, which may not have the copy yet, working.
_CATALOG_PATH = Path(rt.__file__).with_name("model_catalog.json")


def _catalog_capacity(model_id: str, field: str, fallback: int) -> int:
    """One capacity from the shared catalog, or ``fallback`` when absent."""
    try:
        with _CATALOG_PATH.open(encoding="utf-8") as handle:
            for entry in json.load(handle)["models"]:
                if entry["id"] == model_id:
                    return int(entry[field])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return fallback


def _catalog_text(model_id: str, field: str, fallback: str) -> str:
    """One string fact from the shared catalog, or ``fallback`` when absent."""
    try:
        with _CATALOG_PATH.open(encoding="utf-8") as handle:
            for entry in json.load(handle)["models"]:
                if entry["id"] == model_id:
                    value = entry.get(field)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return fallback


DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL = "qwen3.8-27b"
DEFAULT_API_KEY = "dummy"
DEFAULT_HARNESS = "codex"
#: qwen3.8-27b's default reasoning level is a model fact in the shared catalog
#: (``default_reasoning_level``); PAPER_QWEN_REASONING_EFFORT overrides it.
DEFAULT_EFFORT = _catalog_text("qwen3.8-27b", "default_reasoning_level", "medium")
DEFAULT_SSH_HOST = "zxf@101.6.31.113"
DEFAULT_SSH_PORT = "52080"
DEFAULT_LOCAL_PORT = "8000"
DEFAULT_REMOTE = "127.0.0.1:8000"

DEFAULT_CONTEXT_WINDOW = _catalog_capacity("qwen3.8-27b", "context_window", 150000)
DEFAULT_MAX_TOKENS = _catalog_capacity("qwen3.8-27b", "max_tokens", 32768)
DEFAULT_CHAT_MAX_TOKENS = _catalog_capacity(
    "qwen3.8-27b", "chat_max_tokens", 80000
)

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


def _normalize_harness(value: str) -> str:
    """Accept both the public harness names and the adapter spellings."""
    name = str(value).strip().lower().replace("_", "-").replace(" ", "-")
    return {"gpt-codex": "codex", "claude-code": "claude"}.get(name, name)


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
        "harness": _normalize_harness(getattr(args, "harness", None)
                                       or _env("PAPER_QWEN_HARNESS", DEFAULT_HARNESS)),
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
        "context_window": _int_env(
            "PAPER_QWEN_CONTEXT_WINDOW", DEFAULT_CONTEXT_WINDOW
        ),
        "max_tokens": _int_env("PAPER_QWEN_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        "chat_max_tokens": _int_env(
            "PAPER_QWEN_CHAT_MAX_TOKENS", DEFAULT_CHAT_MAX_TOKENS
        ),
        "check_tools": bool(_int_env("PAPER_QWEN_CHECK_TOOLS", 0)),
    }


def _selection(cfg: dict):
    """The shared selection for this adapter's model."""
    cached = cfg.get("_selection")
    if cached is not None:
        return cached
    try:
        selection = rt.resolve_agent_selection(harness="dsh", model=cfg["model"])
    except rt.ConfigError:
        # The adapter also serves a custom model id at the same endpoint; the
        # shared registry only names the stock models, so keep the provider
        # family and let ``raw_model`` carry the operator's id.
        selection = rt.resolve_agent_selection(harness="dsh", model="qwen38-27b")
    cfg["_selection"] = selection
    return selection


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
    except (urllib.error.URLError, OSError, TimeoutError,
            http.client.HTTPException) as e:
        # BadStatusLine/IncompleteRead are HTTPException, not OSError; left
        # uncaught they escaped chat/probe as a traceback instead of a retryable
        # transport error.
        return 0, None, f"{type(e).__name__}: {e}"


def _request_with_retry(
    method: str,
    url: str,
    payload: dict = None,
    api_key: str = "",
    timeout: float = 10.0,
) -> tuple:
    """(status, body, error), retrying per-LLM-call failures with backoff."""
    schedule = rt.RETRY_SCHEDULE
    attempt = 0
    while True:
        status, body, err = _request(
            method, url, payload=payload, api_key=api_key, timeout=timeout
        )
        retryable = bool(err) or status in schedule.retryable_statuses
        if not retryable or attempt >= schedule.max_retries:
            return status, body, err
        attempt += 1
        delay = schedule.delay(attempt)
        print(
            "[paper-qwen] %s %s failed (%s); retry %d/%d in %.0fs"
            % (method, url.rsplit("/", 1)[-1], err or "HTTP %s" % status,
               attempt, schedule.max_retries, delay),
            file=sys.stderr,
            flush=True,
        )
        time.sleep(delay)


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


def _local_tunnel_url(cfg: dict) -> str:
    """The URL the local end of the ssh forward actually listens on."""
    parsed = urllib.parse.urlsplit(str(cfg["base_url"]))
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit(
        (parsed.scheme or "http", "127.0.0.1:%s" % cfg["local_port"], path, "", "")
    )


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
    if mode not in ("auto", "off", "0", "false", "no", "require"):
        # The CLI restricts --tunnel, but PAPER_QWEN_TUNNEL is not validated:
        # `PAPER_QWEN_TUNNEL=banana` used to fall through and start an ssh
        # tunnel. An operator typo must fail, not silently pick a mode.
        return (f"invalid PAPER_QWEN_TUNNEL value {cfg.get('tunnel')!r}: use "
                f"auto, off or require")
    if ok:
        # "Already reachable" is success in EVERY mode: `require` means do not
        # silently fall back to a direct connection when no tunnel exists, not
        # "refuse a working endpoint". The old branch logged and continued, then
        # failed with "port already listening" -- the opposite of the documented
        # behaviour (the 2026-10-28 audit's F72).
        log(f"[qwen] endpoint reachable: {cfg['base_url']} (models: "
            f"{', '.join(ids) or '(none)'})")
        if mode == "require":
            log("[qwen] --tunnel require: the endpoint is already reachable, so no "
                "ssh tunnel is started (nothing to require)")
        return ""
    if mode in ("off", "0", "false", "no"):
        return (f"qwen endpoint {cfg['base_url']} is not reachable and "
                f"PAPER_QWEN_TUNNEL=off: {err}")
    if not shutil.which("ssh"):
        return "qwen endpoint is not reachable and `ssh` is not on PATH"
    if _port_open("127.0.0.1", cfg["local_port"]):
        return (f"port {cfg['local_port']} is already listening but "
                f"{cfg['base_url']}/models did not answer ({err}); another "
                f"service may own the port -- stop it or change "
                f"PAPER_QWEN_TUNNEL_LOCAL")
    tunnel_url = _local_tunnel_url(cfg)
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
        ok, ids, err = probe_endpoint(dict(cfg, base_url=tunnel_url), timeout=2.0)
        if ok:
            # The forward listens on local_port, which need not equal the port in
            # the configured base_url; the harness must talk to the port that is
            # actually forwarded, not the URL that was probed before the tunnel.
            cfg["base_url"] = tunnel_url
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
    rejects codex's `max` reasoning effort; the adapter defaults to the
    balanced `medium` and passes it explicitly.
    """
    overrides = [
        'model_provider="qwen"',
        f'model="{cfg["model"]}"',
        f'model_providers.qwen.name="Qwen vLLM ({cfg["model"]})"',
        f'model_providers.qwen.base_url="{cfg["base_url"]}"',
        'model_providers.qwen.env_key="PAPER_QWEN_API_KEY"',
        'model_providers.qwen.wire_api="responses"',
        # qwen3.8-27b is not in Codex's built-in catalog, so the provider must
        # declare the deployment's window explicitly or Codex applies its own
        # default (the dots adapter does the same for its model).
        f'model_context_window={int(cfg.get("context_window") or DEFAULT_CONTEXT_WINDOW)}',
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
    """The provider route, generated by the shared model runtime."""
    return rt.dsh_patch_text(
        _selection(cfg),
        raw_model=cfg["model"],
        effort_override=cfg.get("effort"),
        base_url_override=cfg["base_url"],
        context_window_override=cfg["context_window"],
        max_tokens_override=cfg["max_tokens"],
    )


def claude_argv(cfg: dict) -> list:
    """`claude --print` against vLLM's Anthropic Messages endpoint."""
    return ["claude", "--permission-mode", "bypassPermissions", "--print"]


def claude_env(cfg: dict) -> dict:
    """Point Claude Code at the same vLLM server (Anthropic Messages)."""
    root = cfg["base_url"]
    if root.endswith("/v1"):
        root = root[:-3]
    return dict(
        os.environ,
        ANTHROPIC_BASE_URL=root,
        ANTHROPIC_AUTH_TOKEN=cfg["api_key"] or "dummy",
        ANTHROPIC_API_KEY=cfg["api_key"] or "dummy",
        ANTHROPIC_MODEL=cfg["model"],
        ANTHROPIC_DEFAULT_SONNET_MODEL=cfg["model"],
        ANTHROPIC_DEFAULT_OPUS_MODEL=cfg["model"],
        ANTHROPIC_DEFAULT_HAIKU_MODEL=cfg["model"],
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
    )


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
    return (_build_dsh_argv(patch_path=patch), env, "")


def _chat_output_budget(cfg: dict, prompt: str, system: str = "") -> int:
    """The single-shot output cap, or 0 when the prompt cannot fit."""
    return completion_budget(
        int(cfg.get("context_window") or 0),
        int(cfg.get("chat_max_tokens") or cfg["max_tokens"]),
        len(prompt) + len(system),
    )
def chat_text(cfg: dict, prompt: str, system: str = "") -> tuple:
    """(text, error) from one /v1/chat/completions call."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    budget = _chat_output_budget(cfg, prompt, system)
    if budget <= 0:
        return "", ("the prompt does not fit the %s-token context window"
                    % cfg.get("context_window"))
    payload = {"model": cfg["model"], "messages": messages,
               "temperature": 0, "max_tokens": budget,
               # Reasoning is required for every completion: the chat budget
               # above covers the thinking trace plus the answer.
               "chat_template_kwargs": {"enable_thinking": True}}
    status, body, err = _request_with_retry(
        "POST", f"{cfg['base_url']}/chat/completions",
        payload=payload, api_key=cfg["api_key"], timeout=600.0)
    if err or status != 200 or not isinstance(body, dict):
        return "", err or f"HTTP {status}: {str(body)[:400]}"
    try:
        choice = body["choices"][0]
        # Only a normal terminal reason is a deliverable. `length` is a
        # max_tokens PREFIX; `content_filter` is a partial answer the provider
        # refused to finish. Both used to pass as success (F30/F68).
        finish_reason = choice.get("finish_reason")
        problem = finish_reason_error(finish_reason, budget)
        if problem:
            return "", problem
        message = choice["message"]
        content = message_text(message.get("content"))
        if not isinstance(content, str) or not content.strip():
            # Qwen3 reasoning responses can carry the text in `reasoning_content`
            # and leave `content` null. That is an INTERMEDIATE reasoning
            # channel, not the requested deliverable: returning it as the answer
            # let a stage consume the model's private scratchpad (F67).
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return "", ("empty chat content: the response carried only a "
                            "reasoning channel, with no final answer")
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


MAX_DSH_LINE_BYTES = 1 << 20      # one JSON event line larger than this is discarded


def _echo_stdout(data: bytes) -> None:
    """Forward child bytes to our stdout, text-mode or buffer."""
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        sys.stdout.write(data.decode("utf-8", "replace"))
        sys.stdout.flush()


def _dsh_turn_failed(line: bytes):
    """True/False for a turn-end event line, None for every other line."""
    return _line_turn_end_failed(line)
def run_dsh_streaming(cmd: list, env: dict) -> tuple:
    """(returncode, turn_failed) with the harness's stdout ECHOED, not buffered.

    `subprocess.run(stdout=PIPE)` accumulated the whole JSON event stream before
    parsing it: a verbose harness could exhaust memory (F27). The stream is read
    in bounded chunks, echoed immediately, and only complete lines are parsed;
    the retained diagnostic prefix is bounded too.
    """
    proc = subprocess.Popen(cmd, stdin=sys.stdin, stdout=subprocess.PIPE,
                            stderr=sys.stderr, env=env)
    turn_failed = None
    saw_turn_end = False
    carry = b""
    try:
        # `read1`, not `read`: a buffered `read(n)` waits for n bytes (or EOF),
        # so a slow harness's first event would not be echoed until the stream
        # filled or the process exited -- the opposite of streaming. `read1`
        # returns as soon as one raw chunk is available.
        read_chunk = getattr(proc.stdout, "read1", proc.stdout.read)
        while True:
            chunk = read_chunk(1 << 20)
            if not chunk:
                break
            _echo_stdout(chunk)
            carry += chunk
            *lines, carry = carry.split(b"\n")
            for line in lines:
                failed = _dsh_turn_failed(line)
                if failed is not None:
                    turn_failed = failed
                    saw_turn_end = True
            if len(carry) > MAX_DSH_LINE_BYTES:
                carry = b""           # a single event line over budget: unusable
        if carry:
            failed = _dsh_turn_failed(carry)
            if failed is not None:
                turn_failed = failed
                saw_turn_end = True
        proc.wait()
    finally:
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill()
            proc.wait()
    if not saw_turn_end:
        # Exit status 0 with no turn_end event is NOT a completed turn: the
        # harness may have died before answering. The caller checks this flag
        # by truthiness, so "no completion event" must be a failure (F-087).
        print("qwen: the harness emitted no turn_end completion event", file=sys.stderr)
        turn_failed = True
    return int(proc.returncode or 0), turn_failed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--harness",
                   choices=("codex", "gpt-codex", "dsh", "claude", "claude-code", "chat"),
                   type=_normalize_harness, default=None,
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
    if cfg["harness"] not in ("codex", "dsh", "claude", "chat"):
        print(f"qwen: unknown harness {cfg['harness']!r}; use codex, dsh, claude or chat",
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
    elif cfg["harness"] == "claude":
        cmd = claude_argv(cfg)
        env = claude_env(cfg)
        print(f"[qwen] {cfg['base_url']} model={cfg['model']} harness=claude "
              f"effort={cfg['effort']}", file=sys.stderr)
    else:
        print(f"qwen: unknown harness {cfg['harness']!r}", file=sys.stderr)
        return 2
    try:
        if cfg["harness"] == "dsh":
            # `dsh --json` can end a turn with a provider error and still exit
            # 0; the wrapper must surface that to the pipeline as a failure.
            # The stream is echoed as it arrives and never buffered whole (F27).
            rc, turn_failed = run_dsh_streaming(cmd, env)
            if turn_failed:
                print("qwen: dsh ended the turn with an error (see the JSON event "
                      "stream above)", file=sys.stderr)
                return int(rc or 0) or 2
            return int(rc or 0)
        proc = subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout,
                              stderr=sys.stderr, env=env)
    except FileNotFoundError:
        print(f"qwen: the {cfg['harness']} executable is not on PATH", file=sys.stderr)
        return 127
    return int(proc.returncode or 0)


if __name__ == "__main__":
    sys.exit(main())

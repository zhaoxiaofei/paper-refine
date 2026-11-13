#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dots3-note-prev agent adapter for the paper-refine pipeline.

The pipeline normally launches a coding harness (`codex exec`, `dsh
--profile headless`, ...). This adapter keeps that harness and points it at
the Dots API (https://dots.ai/platform/docs), whose OpenAI-compatible route
serves `dots3-note-prev`:

    base URL  https://note3-prev-api.askdiandian.com/v1
    model     dots3-note-prev
    key       DOTS_API_KEY

It is selected with `--agent dots` (or `"agent": "dots"` in
pipeline_config.json). The harness is chosen with PAPER_DOTS_HARNESS:

    codex  (default)  `codex exec` with a custom `model_provider=dots` route
                      (OpenAI Responses; the route the platform documents for
                      Codex)
    dsh               `dsh --profile headless` with a generated llm-pi-ai patch
                      (OpenAI Chat Completions; the protocol the platform
                      documents for its OpenAI-compatible endpoint)
    claude            `claude --print` against the platform's Anthropic Messages
                      endpoint (ANTHROPIC_BASE_URL/AUTH_TOKEN, as documented for
                      Claude Code)
    chat              a direct /v1/chat/completions call (text-only; no tools)

Environment (all optional except the key):

    DOTS_API_KEY               the API key created on the Dots platform
    PAPER_DOTS_API_KEY         an alias for the key (the adapter exports it as
                               DOTS_API_KEY for the harness)
    PAPER_DOTS_BASE_URL        default https://note3-prev-api.askdiandian.com/v1
    PAPER_DOTS_MODEL           default dots3-note-prev
    PAPER_DOTS_HARNESS         codex | dsh | claude | chat (default codex)
    PAPER_AGENT_REASONING_EFFORT  shared override (off | minimal | low | medium |
                               high | xhigh | max; default from the model
                               catalog, currently high)
    PAPER_DOTS_CONTEXT_WINDOW  default from the shared model catalog (the
                               window the endpoint enforces; 512K is
                               advertised, but requests above it are rejected)
    PAPER_DOTS_MAX_TOKENS      default from the shared model catalog (the
                               harness reply cap)
    PAPER_DOTS_CHAT_MAX_TOKENS  default from the shared model catalog (the
                               single-shot cap)
    PAPER_DOTS_CHECK_TOOLS     1 = probe tool_choice=auto before a session
    PAPER_DOTS_REQUIRE_TOOLS   same, but a missing tool capability fails instead
                               of warning
    PAPER_DOTS_SKIP_PROBE      1 = skip the /v1/models preflight (for a gateway
                               that does not expose that listing)

`python3 paper_dots_agent.py --probe` reports the endpoint, model and tool
support without running a session. `--chat` reads a prompt from stdin and
prints the model's text (for text-only jobs). `--check-tools` exits 0/1 on
whether the endpoint accepts `tool_choice=auto`.

Design boundary: the adapter does not reimplement the harness. It only writes
the provider configuration the harness already understands, forwards the
session's stdin/stdout, and records a capability gap (no tool calls) rather
than silently producing a text-only answer from a stage that needed tools.
The Dots platform is a remote service: no tunnel is started, and the key is
never written into a generated config file (codex and dsh read it from the
environment).
"""
from __future__ import annotations

import argparse
import atexit
import http.client
import json
import os
import shutil
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
# These scripts are also loaded by absolute filename by the test runner.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import paper_dsh_runtime
finally:
    sys.path.pop(0)

_dsh_turn_failed = paper_dsh_runtime.line_turn_end_failed

#: Every default below is a shared model setting: the catalog and the runtime
#: in ``agent-common`` own them, so a revision (reasoning level, context
#: length, caps) happens there and reaches this adapter without an edit here.
DEFAULT_BASE_URL = rt.DOTS_DEFAULT_BASE_URL
DEFAULT_MODEL = rt.DOTS_DEFAULT_MODEL
DEFAULT_HARNESS = "codex"
DEFAULT_EFFORT = rt.DOTS_DEFAULT_EFFORT
DEFAULT_CONTEXT_WINDOW = rt.DOTS_CONTEXT_WINDOW
DEFAULT_MAX_TOKENS = rt.DOTS_MAX_TOKENS
DEFAULT_CHAT_MAX_TOKENS = rt.DOTS_CHAT_MAX_TOKENS
DOCS_URL = "https://dots.ai/platform/docs"

# Cleanup targets: the temporary DSH_HOME copy and the generated patch file.
# They are module globals because the atexit cleanup runs outside the function
# that created them; an uninitialised read raised NameError on every exit.
_DSH_HOME_TMP = None
_PATCH_TMP = None
_COMPACTION_PROXY = None

#: The per-LLM-call policy is owned by the shared ``model_runtime`` module
#: (whose ``llm_retry`` copy reads ``llm_policy.json``).  Keeping one schedule
#: here means the direct-chat client and the generated DSH ``retryPolicy``
#: cannot drift.


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def _normalize_harness(value: str) -> str:
    """Accept the pipeline's harness spellings; only the three are valid."""
    text = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    return {"gpt-codex": "codex", "claude-code": "claude"}.get(text, text)


def config(args=None) -> dict:
    """Resolve the effective endpoint/harness configuration (args > env)."""
    args = args or argparse.Namespace()
    base = (getattr(args, "base_url", None)
            or _env("PAPER_DOTS_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    # ``args > env`` also for an explicitly supplied EMPTY key: a caller that
    # passes ``api_key=""`` is asking for a keyless endpoint (the local
    # OpenAI-compatible case), and the ambient DOTS_API_KEY must not silently
    # turn that into an authenticated hosted request.
    supplied_key = getattr(args, "api_key", None)
    key = (supplied_key if supplied_key is not None
           else (_env("PAPER_DOTS_API_KEY") or _env("DOTS_API_KEY")))
    compaction_key = (
        _env("DOTS_API_KEY_1474")
        or _env("DOTS_AI_API_KEY_1474")
        or _env("PAPER_DOTS_COMPACTION_API_KEY")
        or _env("DOTS_COMPACTION_API_KEY")
    )
    return {
        "base_url": base,
        "model": getattr(args, "model", None) or _env("PAPER_DOTS_MODEL",
                                                      DEFAULT_MODEL),
        "api_key": key,
        "compaction_api_key": compaction_key,
        "harness": _normalize_harness(getattr(args, "harness", None)
                                       or _env("PAPER_DOTS_HARNESS", DEFAULT_HARNESS)),
        # An explicit --reasoning-effort/flag wins, then the shared
        # PAPER_AGENT_REASONING_EFFORT override, then the adapter's family
        # variable; the shared table validates the level.
        "effort": rt.normalize_reasoning_effort(
            "dots3-note-preview",
            getattr(args, "reasoning_effort", None)
            or _env("PAPER_AGENT_REASONING_EFFORT", DEFAULT_EFFORT),
        ),
        "context_window": _int_env("PAPER_DOTS_CONTEXT_WINDOW",
                                   DEFAULT_CONTEXT_WINDOW),
        "max_tokens": _int_env("PAPER_DOTS_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        "chat_max_tokens": _int_env(
            "PAPER_DOTS_CHAT_MAX_TOKENS", DEFAULT_CHAT_MAX_TOKENS
        ),
        "check_tools": bool(_int_env("PAPER_DOTS_CHECK_TOOLS", 0)),
        "require_tools": bool(_int_env("PAPER_DOTS_REQUIRE_TOOLS", 0)),
        "skip_probe": bool(_int_env("PAPER_DOTS_SKIP_PROBE", 0)),
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
        selection = rt.resolve_agent_selection(harness="dsh", model="dots3-note-preview")
    cfg["_selection"] = selection
    return selection


def _request(method: str, url: str, payload: dict = None, api_key: str = "",
             timeout: float = 10.0) -> tuple:
    """(status, parsed-body-or-text, error) for one JSON request."""
    data = None
    headers = {"Content-Type": "application/json"}
    if api_key:
        # The platform accepts both `Authorization: Bearer ...` and its
        # documented `api-key` header; the OpenAI-compatible route is driven
        # with the bearer form, as the SDKs and both harnesses send it.
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


def _announce_retry(what: str, attempt: int, delay: float, detail: str) -> None:
    """One retry line on stderr (the shared 10s-to-3600s schedule)."""
    print(
        "[paper-dots] %s failed (%s); retry %d/%d in %.0fs"
        % (what, detail, attempt, rt.RETRY_SCHEDULE.max_retries, delay),
        file=sys.stderr,
        flush=True,
    )


def _request_with_retry(
    method: str,
    url: str,
    payload: dict = None,
    api_key: str = "",
    timeout: float = 10.0,
) -> tuple:
    """(status, body, error) with per-call exponential backoff.

    A 429 (TPM) or a 5xx is retried in this process; the prompt and the
    conversation are untouched.  4xx answers other than the retryable set are
    returned immediately: resending a malformed request only burns time.
    """
    schedule = rt.RETRY_SCHEDULE
    attempt = 0
    while True:
        status, body, err = _request(
            method, url, payload=payload, api_key=api_key, timeout=timeout
        )
        retryable = bool(err) or schedule.status_is_retryable(status)
        if not retryable or attempt >= schedule.max_retries:
            return status, body, err
        attempt += 1
        delay = schedule.delay(attempt)
        detail = err or "HTTP %s" % status
        _announce_retry("%s %s" % (method, url.rsplit("/", 1)[-1]),
                        attempt, delay, detail)
        time.sleep(delay)


def probe_endpoint(cfg: dict, timeout: float = 10.0) -> tuple:
    """(ok, model_ids, error) from GET {base}/models."""
    status, body, err = _request("GET", f"{cfg['base_url']}/models",
                                 api_key=cfg["api_key"], timeout=timeout)
    if err or status != 200 or not isinstance(body, dict):
        return False, [], err or f"HTTP {status}: {str(body)[:160]}"
    ids = [str(m.get("id")) for m in (body.get("data") or []) if isinstance(m, dict)]
    return True, ids, ""


def check_tools(cfg: dict, timeout: float = 60.0) -> tuple:
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
    detail = body if isinstance(body, str) else json.dumps(body)
    return False, f"HTTP {status}: {detail[:300]}"


def codex_argv(cfg: dict, extra: list = None) -> list:
    """`codex exec` with a custom dots provider route.

    The platform documents this route for Codex: the OpenAI Responses protocol
    at /v1, `DOTS_API_KEY` read from the environment, and web search disabled
    (the endpoint does not serve OpenAI's hosted web-search tool). The window
    the endpoint enforces (393,000 tokens) is declared explicitly:
    `dots3-note-prev` is not in Codex's built-in model catalog, so leaving it
    unset would apply Codex's default.
    """
    overrides = [
        'model_provider="dots"',
        f'model="{cfg["model"]}"',
        'model_providers.dots.name="Dots API"',
        f'model_providers.dots.base_url="{cfg["base_url"]}"',
        'model_providers.dots.env_key="DOTS_API_KEY"',
        'model_providers.dots.wire_api="responses"',
        'web_search="disabled"',
        f'model_context_window={cfg["context_window"]}',
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
        base_url_override=cfg["base_url"],
        context_window_override=cfg["context_window"],
        max_tokens_override=cfg["max_tokens"],
        effort_override=cfg.get("effort"),
        compaction_base_url=cfg.get("compaction_base_url") or None,
    )


def claude_argv(cfg: dict) -> list:
    """`claude --print` against the Dots Anthropic Messages endpoint."""
    return ["claude", "--permission-mode", "bypassPermissions", "--print"]


def claude_env(cfg: dict) -> dict:
    """The platform's documented Claude Code environment (no key in a file)."""
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


def ensure_dsh_home() -> tuple:
    global _DSH_HOME_TMP
    home, error, temporary = paper_dsh_runtime.prepare_dsh_home("dots")
    if temporary is not None:
        _DSH_HOME_TMP = temporary
    return home, error


def _cleanup() -> None:
    global _DSH_HOME_TMP, _PATCH_TMP, _COMPACTION_PROXY
    if _COMPACTION_PROXY is not None:
        rt.stop_compaction_proxy(_COMPACTION_PROXY)
        _COMPACTION_PROXY = None
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
    fd, patch = tempfile.mkstemp(prefix="paper-dots-", suffix=".patch.yml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(dsh_patch_text(cfg))
    _PATCH_TMP = patch
    key = cfg["api_key"] or "dummy"
    compaction_key = cfg.get("compaction_api_key") or key
    env = dict(os.environ, DSH_HOME=home, DOTS_API_KEY=key,
               PAPER_DOTS_API_KEY=key, DOTS_API_KEY_1474=compaction_key)
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
               "max_tokens": budget,
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
        # refused to finish.
        finish_reason = choice.get("finish_reason")
        problem = finish_reason_error(finish_reason, budget)
        if problem:
            return "", problem
        message = choice["message"]
        content = message_text(message.get("content"))
        if not isinstance(content, str) or not content.strip():
            # The platform can return the model's private reasoning channel in
            # `reasoning_content`; that is not the requested deliverable.
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
    print(f"api key:  {'set' if cfg['api_key'] else 'NOT set (DOTS_API_KEY)'}")
    if not ok:
        print(f"endpoint: UNREACHABLE ({err})")
        return 1
    print(f"endpoint: reachable; models: {', '.join(ids) or '(none)'}")
    if cfg["model"] not in ids:
        print(f"model:    NOT LISTED (available: {', '.join(ids) or '(none)'})")
        return 1
    if not cfg["api_key"]:
        print("tools:    not checked (DOTS_API_KEY is not set)")
        return 0
    supported, detail = check_tools(cfg)
    print(f"tools:    {'accepted' if supported else 'NOT accepted'} ({detail})")
    return 0


def run_dsh_streaming(cmd: list, env: dict) -> tuple:
    return paper_dsh_runtime.run_dsh_streaming(cmd, env, "dots")


def _api_key_problem(cfg: dict) -> str:
    """A missing key is fatal only where the adapter knows one is required."""
    if cfg["api_key"]:
        return ""
    # The hosted host comes from the shared runtime, so a base-URL revision in
    # agent-common moves this guard with it instead of stranding a literal.
    hosted = urllib.parse.urlsplit(rt.DOTS_DEFAULT_BASE_URL).netloc
    if urllib.parse.urlsplit(cfg["base_url"]).netloc == hosted:
        return (f"DOTS_API_KEY is not set. Create a key on the Dots platform "
                f"({DOCS_URL}) and export it: `export DOTS_API_KEY=...`")
    return ""


def _start_compaction_proxy(cfg: dict) -> None:
    """Wire the dedicated Dots compaction route to the shared retrying proxy.

    The DSH compaction summarizer calls the provider directly, outside DSH's own
    retry hook; pointing that one provider at the proxy gives the dedicated
    compaction key the same 10s-to-3600s per-call backoff.
    """
    global _COMPACTION_PROXY
    # The overlay's dots provider uses cfg["base_url"] (the --base-url override
    # when present); the compaction route must forward to that same upstream.
    target = rt.compaction_proxy_target(
        _selection(cfg), base_url_override=cfg.get("base_url")
    )
    if not target:
        return
    _COMPACTION_PROXY, proxy_base = rt.start_compaction_proxy(target)
    if _COMPACTION_PROXY is not None:
        cfg["compaction_base_url"] = proxy_base


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--harness",
                   choices=("codex", "gpt-codex", "dsh", "claude", "claude-code", "chat"),
                   type=_normalize_harness, default=None,
                   help="which harness to point at dots3-note-prev "
                        "(default: PAPER_DOTS_HARNESS or codex)")
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--reasoning-effort",
                   choices=("minimal", "low", "medium", "high", "xhigh", "max"),
                   default=None)
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
        print(f"dots: unknown harness {cfg['harness']!r}; use codex, dsh, claude or chat",
              file=sys.stderr)
        return 2
    if args.probe:
        # Diagnostics must run BEFORE the key/reachability gate: otherwise the
        # `endpoint: UNREACHABLE` / `model: NOT LISTED` report could never print.
        return _print_probe(cfg)
    err = _api_key_problem(cfg)
    if err:
        print(f"dots: {err}", file=sys.stderr)
        return 2
    if not cfg["skip_probe"]:
        ok, ids, perr = probe_endpoint(cfg)
        if not ok:
            print(f"dots: endpoint {cfg['base_url']} did not answer: {perr}",
                  file=sys.stderr)
            return 2
        if cfg["model"] not in ids:
            print(f"dots: model {cfg['model']!r} is not listed (available: "
                  f"{', '.join(ids) or '(none)'})", file=sys.stderr)
            return 2
    if args.check_tools:
        supported, detail = check_tools(cfg)
        print(f"dots tools: {'accepted' if supported else 'NOT accepted'} ({detail})")
        return 0 if supported else 1
    if args.chat or cfg["harness"] == "chat":
        prompt = sys.stdin.read() if not sys.stdin.isatty() else ""
        if not prompt.strip():
            print("dots: chat mode needs a prompt on stdin", file=sys.stderr)
            return 2
        text, cerr = chat_text(cfg, prompt, system=args.system)
        if cerr:
            print(f"dots: chat failed: {cerr}", file=sys.stderr)
            return 2
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    need_tool_probe = (args.check_tools or args.require_tools or cfg["check_tools"]
                       or cfg["require_tools"] or cfg["harness"] in ("dsh", "claude"))
    if need_tool_probe:
        supported, detail = check_tools(cfg)
        if not supported:
            msg = (f"the Dots endpoint does not accept tool_choice=auto ({detail}). "
                   f"An agentic {cfg['harness']} session will fail when it needs a "
                   f"tool. Use `--harness chat` for text-only calls, or check the "
                   f"platform status before starting a wave.")
            if args.require_tools or cfg["check_tools"] or cfg["require_tools"]:
                print(f"dots: {msg}", file=sys.stderr)
                return 2
            print(f"[dots] WARNING: {msg}", file=sys.stderr)
    key = cfg["api_key"] or "dummy"
    env = dict(os.environ, DOTS_API_KEY=key, PAPER_DOTS_API_KEY=key)
    if cfg["harness"] == "codex":
        extra = []
        if args.codex_extra_args:
            try:
                extra = json.loads(args.codex_extra_args)
            except ValueError:
                print("dots: --codex-extra-args must be a JSON list", file=sys.stderr)
                return 2
            if not isinstance(extra, list):
                print("dots: --codex-extra-args must be a JSON list", file=sys.stderr)
                return 2
        cmd = codex_argv(cfg, extra=extra)
        print(f"[dots] {cfg['base_url']} model={cfg['model']} harness=codex "
              f"effort={cfg['effort']}", file=sys.stderr)
    elif cfg["harness"] == "dsh":
        _start_compaction_proxy(cfg)
        cmd, denv, derr = dsh_argv(cfg)
        if derr:
            print(f"dots: {derr}", file=sys.stderr)
            return 2
        env.update(denv)
        print(f"[dots] {cfg['base_url']} model={cfg['model']} harness=dsh",
              file=sys.stderr)
    elif cfg["harness"] == "claude":
        cmd = claude_argv(cfg)
        env = claude_env(cfg)
        print(f"[dots] {cfg['base_url']} model={cfg['model']} harness=claude",
              file=sys.stderr)
    else:
        print(f"dots: unknown harness {cfg['harness']!r}", file=sys.stderr)
        return 2
    try:
        if cfg["harness"] == "dsh":
            # `dsh --json` can end a turn with a provider error and still exit
            # 0; the wrapper must surface that to the pipeline as a failure.
            rc, turn_failed = run_dsh_streaming(cmd, env)
            if turn_failed:
                print("dots: dsh ended the turn with an error (see the JSON event "
                      "stream above)", file=sys.stderr)
                return int(rc or 0) or 2
            return int(rc or 0)
        proc = subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout,
                              stderr=sys.stderr, env=env)
    except FileNotFoundError:
        print(f"dots: the {cfg['harness']} executable is not on PATH", file=sys.stderr)
        return 127
    return int(proc.returncode or 0)


if __name__ == "__main__":
    sys.exit(main())

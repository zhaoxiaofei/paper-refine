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
    PAPER_DOTS_REASONING_EFFORT  minimal | low | medium | high | xhigh | max
                               (default medium; sent to codex)
    PAPER_DOTS_CONTEXT_WINDOW  default 393000 (the window the endpoint
                               enforces; 512K is advertised, but requests
                               above 393000 are rejected)
    PAPER_DOTS_MAX_TOKENS      default 65536 (harness replies)
    PAPER_DOTS_CHAT_MAX_TOKENS  default 160000 (single-shot)
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
import contextlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import model_runtime as rt
except ImportError:  # a test loader may not put this file's directory on sys.path
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import model_runtime as rt

DEFAULT_BASE_URL = "https://note3-prev-api.askdiandian.com/v1"
DEFAULT_MODEL = "dots3-note-prev"
DEFAULT_HARNESS = "codex"
DEFAULT_EFFORT = "medium"

#: The shared model catalog (canonical: ``repos/common/model_catalog.json``;
#: this checkout carries an identical copy).  The fallback keeps a checkout
#: refreshed from upstream, which may not have the copy yet, working.
_CATALOG_PATH = Path(__file__).with_name("model_catalog.json")


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
DEFAULT_CONTEXT_WINDOW = _catalog_capacity(
    "dots3-note-prev", "context_window", 393000
)
DEFAULT_MAX_TOKENS = _catalog_capacity(
    "dots3-note-prev", "max_tokens", 65536
)
DEFAULT_CHAT_MAX_TOKENS = _catalog_capacity(
    "dots3-note-prev", "chat_max_tokens", 160000
)
DOCS_URL = "https://dots.ai/platform/docs"

#: Per-LLM-call retry schedule.  The canonical policy is
#: ``repos/common/llm_policy.json``; these constants are duplicated here because
#: a paper-refine root freezes each adapter as one standalone file (rule 11), so
#: the adapter cannot rely on a sibling module or JSON file existing at run time.
_RETRY_INITIAL_SECONDS = 10.0
_RETRY_MAX_SECONDS = 3600.0
_RETRY_MULTIPLIER = 2.0
_RETRY_MAX_RETRIES = 10
_RETRY_JITTER_RATIO = 0.1
_RETRY_HTTP_STATUSES = frozenset(
    {408, 409, 425, 429, 500, 502, 503, 504, 529}
)


def _retry_delay(attempt: int) -> float:
    """Seconds before retry ``attempt`` (1 = first retry), capped at one hour."""
    exponent = max(0, int(attempt) - 1)
    delay = _RETRY_INITIAL_SECONDS * (_RETRY_MULTIPLIER ** exponent)
    delay = min(delay, _RETRY_MAX_SECONDS)
    if _RETRY_JITTER_RATIO:
        factor = (
            1.0
            - _RETRY_JITTER_RATIO
            + 2.0 * _RETRY_JITTER_RATIO * random.random()
        )
        delay = min(delay * factor, _RETRY_MAX_SECONDS)
    return max(0.0, delay)


def _announce_retry(action: str, attempt: int, delay: float, detail: str) -> None:
    print(
        "[paper-dots] %s failed (%s); retry %d/%d in %.0fs"
        % (action, detail, attempt, _RETRY_MAX_RETRIES, delay),
        file=sys.stderr,
        flush=True,
    )


_DSH_HOME_TMP = None    # a temporary DSH_HOME copy for a read-only ~/.dsh
_PATCH_TMP = None       # the generated dsh patch file


def _env(name: str, default: str = "") -> str:
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
    base = (getattr(args, "base_url", None)
            or _env("PAPER_DOTS_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    key = (getattr(args, "api_key", None)
           or _env("PAPER_DOTS_API_KEY") or _env("DOTS_API_KEY"))
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
        "effort": (getattr(args, "reasoning_effort", None)
                   or _env("PAPER_DOTS_REASONING_EFFORT", DEFAULT_EFFORT)).lower(),
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
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return 0, None, f"{type(e).__name__}: {e}"


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
    attempt = 0
    while True:
        status, body, err = _request(
            method, url, payload=payload, api_key=api_key, timeout=timeout
        )
        retryable = bool(err) or status in _RETRY_HTTP_STATUSES
        if not retryable or attempt >= _RETRY_MAX_RETRIES:
            return status, body, err
        attempt += 1
        delay = _retry_delay(attempt)
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


def _writable(path: Path) -> bool:
    try:
        probe = path / ".paper_dots_write_test"
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
    tmp = Path(tempfile.mkdtemp(prefix="paper-dots-dsh-"))
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
    return (["dsh", "--profile", "headless", "--patch", patch, "--json", "-"],
            env, "")


def _chat_output_budget(cfg: dict, prompt: str, system: str = "") -> int:
    """The single-shot output cap, or 0 when the prompt cannot fit.

    A direct completion has no harness to continue a truncated reply: one
    response must hold the reasoning trace plus the answer, so it uses the
    model's ``chat_max_tokens`` instead of the smaller harness ``max_tokens``.
    Code and JSON run closer to 3.4 characters per token than to four, so this
    estimate matches paper-refine-eval's; dividing by four underestimates a
    long prompt and lets ``prompt + max_tokens`` cross the window.
    """
    cap = int(cfg.get("chat_max_tokens") or cfg["max_tokens"])
    prompt_tokens = int(math.ceil((len(prompt) + len(system)) / 3.4))
    room = int(cfg.get("context_window") or 0) - prompt_tokens - 2048
    if room <= 0:
        return 0
    return max(1, min(cap, room))


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
        if finish_reason == "length":
            return "", (f"the chat completion was truncated (finish_reason='length', "
                        f"max_tokens={budget}): the answer is incomplete")
        if finish_reason not in (None, "stop", "end_turn", "stop_sequence",
                                 "tool_calls", "function_call"):
            return "", (f"the chat completion did not finish normally "
                        f"(finish_reason={finish_reason!r}): the answer is incomplete")
        message = choice["message"]
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(str(part.get("text") or "")
                              for part in content
                              if isinstance(part, dict) and part.get("type") == "text")
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
    """True/False for a turn-end event line, None for every other line.

    Two shapes are accepted because the harness has emitted both: the older
    `{"type":"turn_end","status":...}` record and the current
    `{"type":"status","phase":"turn_end","reason":{"kind":...}}` record. A
    completion the adapter cannot parse must not turn a provider error into a
    successful stage, so the allowlist is explicit either way.
    """
    s = line.strip()
    if not s.startswith(b"{"):
        return None
    try:
        event = json.loads(s)
    except ValueError:
        return None
    if not isinstance(event, dict):
        return None
    phase = str(event.get("phase") or "").lower()
    if event.get("type") != "turn_end" and not (
            event.get("type") == "status" and phase == "turn_end"):
        return None
    status = str(event.get("status") or "").lower()
    reason = event.get("reason")
    reason_kind = ""
    if isinstance(reason, dict):
        reason_kind = str(reason.get("kind") or "").lower()
    kind = str(event.get("kind") or reason_kind).lower()
    if kind in ("error", "failed"):
        return True
    # An explicit allowlist, not a denylist: `cancelled`, `interrupted`,
    # `aborted`, `timeout` and any future non-success status are incomplete.
    ok = ("ok", "success", "succeeded", "completed", "complete", "done", "finished")
    if status:
        return status not in ok
    if kind:
        return kind not in ok
    return False


def run_dsh_streaming(cmd: list, env: dict) -> tuple:
    """(returncode, turn_failed) with the harness's stdout ECHOED, not buffered.

    `dsh --json` emits one JSON object per line; a verbose harness must not be
    accumulated whole. The stream is read in bounded chunks, echoed as it
    arrives, and only complete lines are parsed.
    """
    proc = subprocess.Popen(cmd, stdin=sys.stdin, stdout=subprocess.PIPE,
                            stderr=sys.stderr, env=env)
    turn_failed = None
    saw_turn_end = False
    carry = b""
    try:
        # `read1`, not `read`: a buffered `read(n)` waits for n bytes (or EOF),
        # so a slow harness's first event would not be echoed until the stream
        # filled or the process exited -- the opposite of streaming.
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
        # harness may have died before answering.
        print("dots: the harness emitted no turn_end completion event", file=sys.stderr)
        turn_failed = True
    return int(proc.returncode or 0), turn_failed


def _api_key_problem(cfg: dict) -> str:
    """A missing key is fatal only where the adapter knows one is required."""
    if cfg["api_key"]:
        return ""
    if cfg["base_url"].startswith("https://note3-prev-api.askdiandian.com"):
        return (f"DOTS_API_KEY is not set. Create a key on the Dots platform "
                f"({DOCS_URL}) and export it: `export DOTS_API_KEY=...`")
    return ""


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

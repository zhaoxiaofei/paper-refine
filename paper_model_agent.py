#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native model router for the paper-refine pipeline (`--agent-model`).

The pipeline normally launches a coding harness (`codex exec`, `dsh
--profile headless`, `claude --print`). This adapter keeps that harness and
selects one of the native provider models:

    deepseek-flash   DeepSeek Flash (via DeepSeek's Responses/Anthropic APIs
                     or the harness's own DeepSeek route)
    gpt-sol          GPT Sol       (latest: gpt-6.1-sol)
    gpt-terra        GPT Terra     (latest: gpt-6.1-terra)
    claude-opus      Claude Opus   (latest: the `opus` alias / claude-opus-5-5)
    claude-sonnet    Claude Sonnet (latest: the `sonnet` alias / claude-sonnet-5-5)

It is selected by the pipeline's `--agent-harness` + `--agent-model` pair; the
legacy `--agent codex|claude|dsh` shortcuts use their old commands instead.
The local/hosted provider adapters (`--agent-model qwen38-27b` and
`--agent-model dots3-note-preview`) are separate modules.

Per-harness configuration:

    dsh          a `llm-pi-ai` `agent-default-model` patch selects
                 deepseek-official/deepseek-flash, openai/<gpt id>, or
                 anthropic/<claude id>; the harness's own home and credentials
                 are used (no key is copied into the patch).
    gpt-codex    gpt models use `codex exec -m <id>`; deepseek-flash uses
                 DeepSeek's documented Responses API as a custom provider
                 (`https://api.deepseek.com`, DEEPSEEK_API_KEY).
    claude-code  claude models use `--model opus|sonnet`; deepseek-flash uses
                 DeepSeek's documented Anthropic-compatible endpoint
                 (`https://api.deepseek.com/anthropic`, DEEPSEEK_API_KEY).

The cross-provider pairs the wire protocols do not support (GPT through Claude
Code, Claude through Codex) are refused by the pipeline before a session
starts; this adapter refuses them too if invoked directly.
"""
from __future__ import annotations

import argparse
import atexit
import contextlib
import http.client
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
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

DEFAULT_HARNESS = rt.DEFAULT_AGENT_HARNESS
DEFAULT_MODEL = "deepseek-flash"

MODELS = {
    name: {
        "id": info.get("id") or name,
        "family": info.get("family") or "",
        "dsh_provider": info.get("dsh_provider"),
        "context": int(info.get("context_window") or 0),
        "max_tokens": int(info.get("max_tokens") or 0),
        "label": info.get("label") or name,
        "alias": info.get("alias"),
    }
    for name, info in rt.AGENT_MODELS.items()
}
MODELS["default"] = {
    "id": "default",
    "family": "default",
    "dsh_provider": None,
    "context": None,
    "max_tokens": None,
    "label": "Harness default",
    "alias": None,
}
HARNESSES = rt.AGENT_HARNESS_CHOICES
_COMPATIBLE = {
    name: set(info.get("harnesses") or ())
    for name, info in rt.AGENT_MODELS.items()
}
_COMPATIBLE["default"] = set(HARNESSES)
DEFAULT_MODEL = rt.DEFAULT_AGENT_MODEL
DEFAULT_ENDPOINT_CONTEXT = rt.DEFAULT_ENDPOINT_CONTEXT
DEFAULT_ENDPOINT_MAX_TOKENS = rt.DEFAULT_ENDPOINT_MAX_TOKENS

#: One JSON event line larger than this is discarded (matches the shared
#: stream readers in the qwen/dots adapters; this router lacked the constant).
MAX_DSH_LINE_BYTES = 1 << 20

_DSH_HOME_TMP = None
_PATCH_TMP = None
_PROXY_SERVER = None
_PROXY_THREAD = None


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def _choice(value) -> str:
    return str(value).strip().lower().replace("_", "-").replace(" ", "-")


def _endpoint_base(url: str) -> str:
    """The DSH provider base URL for a chat-completions endpoint.

    `https://host/v1/chat/completions` -> `https://host/v1`; DSH appends
    `/chat/completions` itself. Query/fragment are dropped, but a `model=` query
    parameter is preserved as the model name by `_endpoint_model`.
    """
    text = str(url).strip()
    try:
        parsed = urllib.parse.urlsplit(text)
        host = parsed.hostname
        parsed.port          # a non-numeric or out-of-range port is malformed too
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not host:
        return ""
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _endpoint_query_model(url: str) -> str:
    try:
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(str(url)).query)
    except ValueError:
        return ""
    return str((values.get("model") or [""])[0]).strip()


def _endpoint_catalog(cfg: dict) -> list:
    """The endpoint's /models entries ([] when it exposes no listing)."""
    base = cfg["base_url"]
    if not base:
        return []
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(f"{base}/models", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        return []
    data = body.get("data") if isinstance(body, dict) else None
    return [m for m in (data or []) if isinstance(m, dict) and m.get("id")]


def _endpoint_context(catalog: list, model: str):
    """The context window the endpoint advertises for `model`, when it does."""
    for entry in catalog:
        if str(entry.get("id")) != str(model):
            continue
        for key in ("context_length", "max_model_len", "context_window",
                    "max_context_tokens", "max_input_tokens"):
            try:
                value = int(entry.get(key))
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return None


def resolve_endpoint_model(cfg: dict) -> tuple:
    """(model_name, error) for a custom endpoint; '' on success."""
    if cfg.get("model_name"):
        catalog = _endpoint_catalog(cfg)
        context = _endpoint_context(catalog, cfg["model_name"])
        if (context and not os.environ.get("PAPER_AGENT_CONTEXT_WINDOW")
                and not cfg.get("context_explicit")):
            cfg["context"] = context
            # The discovered window is now authoritative: dsh_patch_text only
            # forwards an explicit context, so without this marker the patch
            # silently fell back to the 32768 default.
            cfg["context_explicit"] = True
        return cfg["model_name"], ""
    query_model = _endpoint_query_model(cfg.get("endpoint") or "")
    if query_model:
        return query_model, ""
    catalog = _endpoint_catalog(cfg)
    models = [str(m.get("id")) for m in catalog]
    if len(models) == 1:
        context = _endpoint_context(catalog, models[0])
        if (context and not os.environ.get("PAPER_AGENT_CONTEXT_WINDOW")
                and not cfg.get("context_explicit")):
            cfg["context"] = context
            cfg["context_explicit"] = True
        return models[0], ""
    if len(models) > 1:
        return "", (f"the endpoint lists {len(models)} models ({', '.join(models[:8])}"
                    f"{'...' if len(models) > 8 else ''}); pass --agent-model-name "
                    f"(or PAPER_AGENT_MODEL_NAME) to choose one")
    print("model: the endpoint did not list its models; sending model='default' "
          "(pass --agent-model-name if the provider requires a specific id)",
          file=sys.stderr)
    return "default", ""


def config(args=None) -> dict:
    """Resolve the effective harness/model/endpoint configuration (args > env)."""
    args = args or argparse.Namespace()
    harness = (getattr(args, "harness", None)
               or _env("PAPER_AGENT_HARNESS", DEFAULT_HARNESS))
    harness = str(harness).strip().lower().replace("_", "-").replace(" ", "-")
    endpoint = (getattr(args, "endpoint", None)
                or _env("PAPER_AGENT_MODEL_ENDPOINT", "")).strip()
    api_key_env = (getattr(args, "api_key_env", None)
                   or _env("PAPER_AGENT_MODEL_API_KEY_ENV",
                           "PAPER_AGENT_MODEL_API_KEY"))
    api_key = os.environ.get(api_key_env, "")
    if endpoint:
        return {
            "harness": harness,
            "endpoint": endpoint,
            "base_url": _endpoint_base(endpoint),
            "api_key_env": api_key_env,
            "api_key": api_key,
            "model": "custom-endpoint",
            "model_name": (getattr(args, "model_name", None)
                           or _env("PAPER_AGENT_MODEL_NAME", "")).strip(),
            "id": "custom-endpoint",
            "family": "endpoint",
            "label": "Custom API endpoint",
            "context": _int_env("PAPER_AGENT_CONTEXT_WINDOW",
                                DEFAULT_ENDPOINT_CONTEXT),
            "max_tokens": _int_env("PAPER_AGENT_MAX_TOKENS",
                                   DEFAULT_ENDPOINT_MAX_TOKENS),
            "deepseek_key": _env("DEEPSEEK_API_KEY") or _env("PAPER_DEEPSEEK_API_KEY"),
        }
    model = (getattr(args, "model", None)
             or _env("PAPER_AGENT_MODEL", DEFAULT_MODEL))
    model = str(model).strip().lower().replace("_", "-").replace(" ", "-")
    info = MODELS.get(model) or {}
    if model == "default":
        info = {"id": "default", "family": "default", "label": "Harness default"}
    return {
        "harness": harness,
        "endpoint": "",
        "base_url": "",
        "api_key_env": api_key_env,
        "api_key": api_key,
        "model": model,
        "model_name": "",
        "id": info.get("id") or model,
        "family": info.get("family") or "",
        "label": info.get("label") or model,
        "context": info.get("context"),
        "max_tokens": info.get("max_tokens"),
        "deepseek_key": _env("DEEPSEEK_API_KEY") or _env("PAPER_DEEPSEEK_API_KEY"),
    }


def _selection(cfg: dict):
    """The shared selection for this configuration (cached on the dict)."""
    cached = cfg.get("_selection")
    if cached is not None:
        return cached
    if cfg.get("family") == "endpoint":
        selection = rt.resolve_agent_selection(
            harness=cfg["harness"],
            model=cfg.get("endpoint") or "",
            api_key=cfg.get("api_key"),
            model_name=cfg.get("model_name") or "",
        )
    else:
        selection = rt.resolve_agent_selection(
            harness=cfg["harness"],
            model=cfg.get("model"),
        )
    cfg["_selection"] = selection
    return selection


def _pair_problem(cfg: dict) -> str:
    if cfg["model"] == "default":
        if cfg["harness"] not in HARNESSES:
            return f"unknown harness {cfg['harness']!r}; use {', '.join(HARNESSES)}"
        return ""
    if cfg["family"] == "endpoint":
        if cfg["harness"] != "dsh":
            return ("a custom --agent-model endpoint is an OpenAI Chat Completions "
                    "URL; only the dsh harness speaks that protocol directly. Use "
                    "--agent-harness dsh.")
        if not cfg.get("endpoint"):
            return "empty custom endpoint URL"
        if not cfg.get("base_url"):
            return (f"cannot parse endpoint URL {cfg.get('endpoint')!r}: it must be "
                    f"an http(s) URL with a host")
        credential = rt.endpoint_credentials(str(cfg.get("endpoint")))
        if credential:
            return (f"the endpoint URL carries a credential in its {credential}; "
                    f"pass the key with --api-key-env / --agent-model-api-key instead")
        return ""
    if cfg["model"] not in MODELS:
        return f"unknown native model {cfg['model']!r}; use {', '.join(MODELS)}"
    if cfg["harness"] not in HARNESSES:
        return f"unknown harness {cfg['harness']!r}; use {', '.join(HARNESSES)}"
    if cfg["harness"] not in _COMPATIBLE[cfg["model"]]:
        allowed = ", ".join(sorted(_COMPATIBLE[cfg["model"]]))
        return (f"{cfg['model']} cannot run on {cfg['harness']}: that harness does "
                f"not speak a protocol the model serves (supported: {allowed}). "
                f"Choose a supported pair.")
    return ""


def _key_problem(cfg: dict) -> str:
    if cfg["family"] == "endpoint":
        return ""                     # a local endpoint may be keyless
    if cfg["family"] == "deepseek" and cfg["harness"] in ("gpt-codex", "claude-code"):
        if not cfg["deepseek_key"]:
            return ("DEEPSEEK_API_KEY is not set; the DeepSeek Responses/Anthropic "
                    "route needs it. Create a key at "
                    "https://platform.deepseek.com/api_keys and export it.")
    return ""


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into `base` in place and return `base`.

    A missing key in `override` leaves the default untouched; a nested object is
    merged key by key; any other value (including a list or a scalar) replaces
    the default. This is the `--agent-model-prep-json` contract: an incomplete
    object is valid because it only overrides the keys it carries.
    """
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class _PrepProxyHandler(http.server.BaseHTTPRequestHandler):
    """Forward DSH's OpenAI-compatible requests, merging the prep object."""

    protocol_version = "HTTP/1.0"

    def log_message(self, *args):        # keep the adapter's stderr readable
        pass

    def _target(self) -> str:
        base = str(self.server.target_base).rstrip("/")
        path = self.path or "/"
        if path == "/v1" or path.startswith("/v1/"):
            path = path[3:]
        return base + path

    def _forward(self, method: str, body: bytes = None) -> None:
        headers = {}
        for key, value in self.headers.items():
            if key.lower() in ("host", "content-length", "connection",
                               "transfer-encoding", "accept-encoding"):
                continue
            headers[key] = value
        if body is not None:
            headers["Content-Length"] = str(len(body))
        req = urllib.request.Request(self._target(), data=body,
                                     headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=600.0)
        except urllib.error.HTTPError as e:
            raw = e.read()
            self.send_response(e.code)
            ctype = e.headers.get("Content-Type") if e.headers else None
            self.send_header("Content-Type", ctype or "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            with contextlib.suppress(OSError):
                self.wfile.write(raw)
            return
        except (urllib.error.URLError, OSError, TimeoutError,
                http.client.HTTPException) as e:
            # BadStatusLine/IncompleteRead are HTTPException, not OSError; the
            # shared model_runtime proxy already catches them, and without this
            # the client saw a closed connection instead of a structured 502.
            raw = json.dumps({"error": {"message":
                                       f"custom endpoint proxy failed: {e}"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            with contextlib.suppress(OSError):
                self.wfile.write(raw)
            return
        self.send_response(getattr(resp, "status", 200))
        for key, value in resp.headers.items():
            if key.lower() in ("transfer-encoding", "connection",
                               "content-length", "content-encoding"):
                continue
            self.send_header(key, value)
        self.end_headers()
        try:
            read_chunk = getattr(resp, "read1", resp.read)
            while True:
                chunk = read_chunk(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError):
                resp.close()

    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        body = self.rfile.read(length) if length else b""
        prep = getattr(self.server, "prep", None)
        if prep and body:
            try:
                payload = json.loads(body)
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                deep_merge(payload, prep)
                body = json.dumps(payload).encode("utf-8")
        self._forward("POST", body)


def start_prep_proxy(target_base: str, prep: dict) -> tuple:
    """(base_url, error) for a local proxy that merges `prep` into POST bodies."""
    global _PROXY_SERVER, _PROXY_THREAD
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PrepProxyHandler)
    except OSError as exc:
        return "", f"{type(exc).__name__}: {exc}"
    server.target_base = target_base
    server.prep = prep
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _PROXY_SERVER, _PROXY_THREAD = server, thread
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    return base, ""


def stop_prep_proxy() -> None:
    global _PROXY_SERVER, _PROXY_THREAD
    if _PROXY_SERVER is not None:
        with contextlib.suppress(OSError):
            _PROXY_SERVER.shutdown()
        with contextlib.suppress(OSError):
            _PROXY_SERVER.server_close()
        _PROXY_SERVER = None
    _PROXY_THREAD = None


def _writable(path: Path) -> bool:
    try:
        probe = path / ".paper_model_write_test"
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
    tmp = Path(tempfile.mkdtemp(prefix="paper-model-dsh-"))
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
    stop_prep_proxy()
    if _DSH_HOME_TMP is not None:
        shutil.rmtree(_DSH_HOME_TMP, ignore_errors=True)
        _DSH_HOME_TMP = None
    if _PATCH_TMP is not None:
        try:
            Path(_PATCH_TMP).unlink()
        except OSError:
            pass
        _PATCH_TMP = None


def dsh_patch_text(cfg: dict) -> str:
    """The DSH overlay selecting the provider/model, generated by common."""
    if cfg.get("model") == "default":
        return ""
    selection = _selection(cfg)
    context_override = cfg.get("context") if cfg.get("context_explicit") else None
    provider_override = None
    if cfg.get("family") == "deepseek":
        provider_override = _env("PAPER_DSH_DEEPSEEK_PROVIDER", "") or None
    return rt.dsh_patch_text(
        selection,
        base_url_override=cfg.get("dsh_base_url") or None,
        context_window_override=context_override,
        max_tokens_override=cfg.get("max_tokens"),
        provider_override=provider_override,
        endpoint_api_key_env=cfg.get("api_key_env"),
    )


def dsh_argv(cfg: dict) -> tuple:
    """(argv, env, error) for `dsh --profile headless --patch ... --json -`."""
    global _PATCH_TMP
    home, err = ensure_dsh_home()
    if err:
        return [], {}, err
    text = dsh_patch_text(cfg)
    patch = ""
    if text:
        fd, patch = tempfile.mkstemp(prefix="paper-model-", suffix=".patch.yml")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        _PATCH_TMP = patch
    env = dict(os.environ, DSH_HOME=home)
    if cfg["family"] == "endpoint":
        env[cfg["api_key_env"]] = cfg.get("api_key") or "dummy"
    elif cfg["deepseek_key"]:
        env.setdefault("DEEPSEEK_API_KEY", cfg["deepseek_key"])
    argv = ["dsh", "--profile", "headless"]
    if patch:
        argv += ["--patch", patch]
    argv += ["--json", "-"]
    return (argv, env, "")


def codex_argv(cfg: dict, extra: list = None) -> list:
    """`codex exec` model/provider flags, generated by common."""
    argv = ["codex", "exec"]
    if cfg.get("model") == "default":
        return argv + [str(v) for v in (extra or [])] + ["-"]
    selection = _selection(cfg)
    argv += rt.codex_provider_args(selection, raw_model=cfg.get("id"))
    if cfg.get("family") == "gpt":
        argv += ["-m", str(cfg.get("id") or cfg.get("model"))]
    argv += [str(v) for v in (extra or [])]
    argv += ["-"]
    return argv


def claude_argv(cfg: dict) -> list:
    """`claude --print` model flag, generated by common."""
    argv = ["claude", "--permission-mode", "bypassPermissions", "--print"]
    if cfg.get("model") == "default":
        return argv
    model = rt.claude_model_arg(_selection(cfg))
    if model:
        argv += ["--model", model]
    return argv


def claude_env(cfg: dict) -> dict:
    """The process environment for Claude Code, including provider routing."""
    env = dict(os.environ)
    if cfg.get("model") != "default":
        env.update(rt.claude_environment(_selection(cfg)))
    return env


def _echo_stdout(data: bytes) -> None:
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        sys.stdout.write(data.decode("utf-8", "replace"))
        sys.stdout.flush()


def _dsh_turn_failed(line: bytes):
    """True/False for a turn-end event line, None for every other line."""
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
    ok = ("ok", "success", "succeeded", "completed", "complete", "done", "finished")
    if status:
        return status not in ok
    if kind:
        return kind not in ok
    return False


def run_dsh_streaming(cmd: list, env: dict) -> tuple:
    """(returncode, turn_failed) with the harness's stdout ECHOED, not buffered."""
    proc = subprocess.Popen(cmd, stdin=sys.stdin, stdout=subprocess.PIPE,
                            stderr=sys.stderr, env=env)
    turn_failed = None
    saw_turn_end = False
    carry = b""
    try:
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
                carry = b""
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
        print("model: the harness emitted no turn_end completion event",
              file=sys.stderr)
        turn_failed = True
    return int(proc.returncode or 0), turn_failed


def _print_probe(cfg: dict) -> int:
    binary = {"dsh": "dsh", "gpt-codex": "codex",
              "claude-code": "claude"}.get(cfg["harness"], "")
    print(f"harness: {cfg['harness']}")
    if cfg["family"] == "endpoint":
        print(f"endpoint: {cfg['endpoint']}")
        print(f"base:    {cfg['base_url']}")
        print(f"model:   {cfg.get('model_name') or '(unresolved)'}")
        print(f"key:     {cfg['api_key_env']} "
              f"{'set' if cfg['api_key'] else 'NOT set (a keyless endpoint is allowed)'}")
        if cfg.get("prep"):
            print(f"prep:    {', '.join(sorted(cfg['prep'])) or '(empty)'}")
    else:
        print(f"model:   {cfg['model']} ({cfg['id']})")
    print(f"binary:  {binary}: {shutil.which(binary) or 'NOT on PATH'}")
    if cfg["family"] == "deepseek" and cfg["harness"] in ("gpt-codex", "claude-code"):
        print(f"key:     DEEPSEEK_API_KEY "
              f"{'set' if cfg['deepseek_key'] else 'NOT set'}")
    problem = _pair_problem(cfg) or _key_problem(cfg)
    if problem:
        print(f"problem: {problem}")
        return 1
    print("problem: none")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--harness", choices=HARNESSES, type=_choice, default=None,
                   help="dsh | gpt-codex | claude-code (default: PAPER_AGENT_HARNESS)")
    p.add_argument("--model", choices=tuple(MODELS), type=_choice, default=None,
                   help="deepseek-flash | gpt-sol | gpt-terra | claude-opus | claude-sonnet")
    p.add_argument("--endpoint", default=None,
                   help="an http(s) OpenAI-compatible chat-completions endpoint; runs on dsh")
    p.add_argument("--api-key-env", default=None,
                   help="env var holding the custom endpoint's key "
                        "(default: PAPER_AGENT_MODEL_API_KEY)")
    p.add_argument("--model-name", default=None,
                   help="provider model id for a custom endpoint that serves several models")
    p.add_argument("--prep-json", default=None,
                   help="JSON object merged into each request to a custom endpoint "
                        "(incomplete is valid; missing keys keep the harness defaults)")
    p.add_argument("--context-window", type=int, default=None,
                   help="custom endpoint context window (default: PAPER_AGENT_CONTEXT_WINDOW "
                        "or 32768)")
    p.add_argument("--max-tokens", type=int, default=None,
                   help="custom endpoint output cap (default: PAPER_AGENT_MAX_TOKENS or 8192)")
    p.add_argument("--codex-extra-args", default=None,
                   help="JSON list of extra `codex exec` argv values (MCP approvals)")
    p.add_argument("--probe", action="store_true",
                   help="print the resolved pair/binary/key and exit")
    args = p.parse_args(argv)
    if args.endpoint and args.model:
        print("model: use either --model (a named model) or --endpoint (a custom "
              "URL), not both", file=sys.stderr)
        return 2
    cfg = config(args)
    atexit.register(_cleanup)
    cfg["context_explicit"] = bool(args.context_window
                                   or os.environ.get("PAPER_AGENT_CONTEXT_WINDOW"))
    if args.context_window:
        cfg["context"] = int(args.context_window)
    if args.max_tokens:
        cfg["max_tokens"] = int(args.max_tokens)
    problem = _pair_problem(cfg)
    if problem:
        print(f"model: {problem}", file=sys.stderr)
        return 2
    if cfg["family"] == "endpoint":
        name, err = resolve_endpoint_model(cfg)
        if err:
            print(f"model: {err}", file=sys.stderr)
            return 2
        cfg["model_name"] = name
        cfg["id"] = name
    raw_prep = (args.prep_json
                or _env("PAPER_AGENT_MODEL_PREP_JSON", ""))
    prep = {}
    if raw_prep:
        try:
            prep = json.loads(raw_prep)
        except ValueError as exc:
            print(f"model: --prep-json is not valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(prep, dict):
            print("model: --prep-json must be a JSON object", file=sys.stderr)
            return 2
        if cfg["family"] != "endpoint":
            print("model: --prep-json applies only to a custom --endpoint URL",
                  file=sys.stderr)
            return 2
    cfg["prep"] = prep
    if args.probe:
        return _print_probe(cfg)
    problem = _key_problem(cfg)
    if problem:
        print(f"model: {problem}", file=sys.stderr)
        return 2
    env = dict(os.environ)
    if cfg["family"] == "deepseek" and cfg["deepseek_key"]:
        env.setdefault("DEEPSEEK_API_KEY", cfg["deepseek_key"])
    if cfg["harness"] == "dsh":
        if cfg["family"] == "endpoint" and prep:
            proxy_base, perr = start_prep_proxy(cfg["base_url"], prep)
            if perr:
                print(f"model: could not start the prep-json proxy: {perr}",
                      file=sys.stderr)
                return 2
            cfg["dsh_base_url"] = proxy_base
            print(f"[model] prep-json proxy for {cfg['base_url']} at {proxy_base} "
                  f"(keys: {', '.join(sorted(prep))})", file=sys.stderr)
        cmd, denv, derr = dsh_argv(cfg)
        if derr:
            print(f"model: {derr}", file=sys.stderr)
            return 2
        env.update(denv)
        label = (f"{cfg['base_url']} model={cfg.get('model_name') or cfg['id']}"
                 if cfg["family"] == "endpoint" else
                 f"{cfg['model']} ({cfg['id']})")
        print(f"[model] {cfg['harness']} {label}", file=sys.stderr)
        try:
            rc, turn_failed = run_dsh_streaming(cmd, env)
        except FileNotFoundError:
            print("model: the dsh executable is not on PATH", file=sys.stderr)
            return 127
        if turn_failed:
            print("model: dsh ended the turn with an error (see the JSON event "
                  "stream above)", file=sys.stderr)
            return int(rc or 0) or 2
        return int(rc or 0)
    if cfg["harness"] == "gpt-codex":
        extra = []
        if args.codex_extra_args:
            try:
                extra = json.loads(args.codex_extra_args)
            except ValueError:
                print("model: --codex-extra-args must be a JSON list", file=sys.stderr)
                return 2
            if not isinstance(extra, list):
                print("model: --codex-extra-args must be a JSON list", file=sys.stderr)
                return 2
        cmd = codex_argv(cfg, extra=extra)
        print(f"[model] {cfg['harness']} {cfg['model']} ({cfg['id']})",
              file=sys.stderr)
        try:
            proc = subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout,
                                  stderr=sys.stderr, env=env)
        except FileNotFoundError:
            print("model: the codex executable is not on PATH", file=sys.stderr)
            return 127
        return int(proc.returncode or 0)
    if cfg["harness"] == "claude-code":
        cmd = claude_argv(cfg)
        env = claude_env(cfg)
        print(f"[model] {cfg['harness']} {cfg['model']} ({cfg['id']})",
              file=sys.stderr)
        try:
            proc = subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout,
                                  stderr=sys.stderr, env=env)
        except FileNotFoundError:
            print("model: the claude executable is not on PATH", file=sys.stderr)
            return 127
        return int(proc.returncode or 0)
    print(f"model: unknown harness {cfg['harness']!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

# Agent harnesses and model providers

[Back to the README](../README.md)

## `--agent-harness dsh`: the DeepSeek Harness (`dsh`) as the session backend

`dsh` is a separate install (node >= 22, `npm i -g @deepseek-ai/dsh@alpha`), and
the pipeline drives it the way it drives the other two CLIs: one non-interactive
session per stage, `PROMPT.md` piped on stdin, cwd = the stage's sandbox. The
argv is `dsh --profile headless --json -`: `headless` is the harness's one-shot
driver (one fresh persisted session, print the result, exit), and `--json`
turns its stdout into a newline-delimited event stream whose opening `session`
line names the session -- which is what lets a stopped session be CONTINUED with
`--session-id <id>` exactly like a codex one (see *A STOPPED session is
continued, not restarted*). The harness's own home (`$DSH_HOME`, default
`~/.dsh`) owns the model, the MCP servers and the DeepSeek credential
(`DEEPSEEK_API_KEY`), the way `~/.codex/config.toml` owns the codex CLI's -- so
this preset carries no overrides, and a prompt that wants an MCP tool the
harness does not have falls back to the next converter in its own list. Since
that one-shot contract belongs to the installed BUILD rather than to a flag,
`--agent-harness dsh` reads the harness's own `dsh --profile headless --help` once
per invocation and names the gap (with the upgrade) up front instead of letting
every session of a wave fail one by one -- including the conditions that would
otherwise only appear as a stack trace per session: a build without the one-shot
flags, and a `node` the harness cannot run under (it needs node >= 22 AND must be
installed for the node that runs it, so putting a v22 first on PATH does not fix
a harness `npm i -g`-installed under v18 -- reinstall it under v22). A missing
`dsh` gets the install line.
Verified end to end against dsh 0.2.1-alpha.4 and 0.2.0-rc.2. Reached through a
custom `--agent-cmd` instead (e.g. the npx form, for a machine with no global
install), the sessions run exactly the same way but keep the custom-command
rule: no continuation form, so a stopped session gets a fresh attempt.

## `--agent-model qwen38-27b`: Qwen3.8-27B through an OpenAI-compatible vLLM endpoint (and Claude Code's Anthropic route)

`--agent-model qwen38-27b` points an existing harness at a vLLM server instead of
reimplementing the agent loop. The adapter, `paper_qwen_agent.py`, is copied
beside the root's driver at `setup` and travels through `sync-code`. It chooses
the harness with `PAPER_QWEN_HARNESS`:

* `codex` (default) — `codex exec` with a custom `model_provider=qwen` route.
  The installed codex accepts only `wire_api="responses"`; vLLM exposes
  `/v1/responses`, so the route uses it. Qwen rejects codex's `max` reasoning
  effort; the adapter defaults to the catalog's level (`PAPER_AGENT_REASONING_EFFORT`
  overrides it).
* `dsh` — `dsh --profile headless` plus a generated `llm-pi-ai` provider patch
  and an `agent-default-model` override for the qwen route.
* `claude` — `claude --print` against vLLM's Anthropic Messages endpoint (when
  the server serves it).
* `chat` — a direct `/v1/chat/completions` call (text-only; no tools).

The endpoint is `PAPER_QWEN_BASE_URL` (default
`http://127.0.0.1:8000/v1`), model `PAPER_QWEN_MODEL` (default
`qwen3.8-27b`), and key `PAPER_QWEN_API_KEY` (default `dummy`; vLLM usually
needs none). When the endpoint is not reachable the adapter starts the SSH
tunnel:

```
ssh -p 52080 -N -L 8000:127.0.0.1:8000 zxf@101.6.31.113
```

(`PAPER_QWEN_SSH_HOST`, `PAPER_QWEN_SSH_PORT`, `PAPER_QWEN_TUNNEL_LOCAL`,
`PAPER_QWEN_TUNNEL_REMOTE`; `PAPER_QWEN_TUNNEL=off` forbids starting it). A
tunnel the adapter started is stopped on exit; an operator's existing tunnel is
left alone. Check the route without running a session:

```
python3 paper_qwen_agent.py --probe          # endpoint, model, tool support
python3 paper_qwen_agent.py --check-tools    # exit 0/1 on tool_choice=auto
printf 'Summarize this file: ...' | python3 paper_qwen_agent.py --chat
```

**Agentic sessions need tool calls.** vLLM accepts `tool_choice=auto` only
when started with `--enable-auto-tool-choice --tool-call-parser <parser>` (and
a model tool template). Without that flag, dsh fails a tool-using turn and
codex's tools are not executed; the adapter warns on a dsh run and reports the
gap in `--probe`. `--harness chat` is a text-only route and does not complete a
pipeline stage that must write artifacts. Set `PAPER_QWEN_REQUIRE_TOOLS=1` to
make the tool probe a hard preflight for a production run (the default is
warn-and-run so the adapter can still be exercised against a text-only
endpoint).

## `--agent-model dots3-note-preview`: dots3-note-prev through the Dots API

`--agent-model dots3-note-preview` keeps the harness and points it at the Dots API instead of
reimplementing the agent loop; the platform's documentation is
<https://dots.ai/platform/docs>. The adapter, `paper_dots_agent.py`, is copied
beside the root's driver at `setup` and travels through `sync-code`. Create a
key on the platform and export it as `DOTS_API_KEY`; the default endpoint is
`https://note3-prev-api.askdiandian.com/v1` and the model is
`dots3-note-prev`. It chooses the harness with `PAPER_DOTS_HARNESS`:

* `codex` (default) — `codex exec` with a custom `model_provider=dots` route:
  the platform's documented Responses protocol (`wire_api="responses"`),
  `DOTS_API_KEY` read from the environment, web search disabled, and the
  model's enforced 393,000-token window declared explicitly (it is not in Codex's
  built-in catalog). The reasoning effort defaults to the catalog's `high`
  (`PAPER_AGENT_REASONING_EFFORT` overrides it).
* `dsh` — `dsh --profile headless` plus a generated `llm-pi-ai` route over the
  platform's OpenAI-compatible Chat Completions endpoint and an
  `agent-default-model` override. The route declares the 393,000-token window
  and the output cap, and does not invent a reasoning parameter the platform
  does not document.
* `claude` — `claude --print` against the platform's Anthropic Messages
  endpoint (its documented Claude Code route).
* `chat` — a direct `/v1/chat/completions` call (text-only; no tools).

The endpoint and model are `PAPER_DOTS_BASE_URL` and `PAPER_DOTS_MODEL`; the
capacity defaults are `PAPER_DOTS_CONTEXT_WINDOW=393000` and
`PAPER_DOTS_MAX_TOKENS=65536`. `PAPER_DOTS_SKIP_PROBE=1` skips the
`/v1/models` preflight for a gateway that does not expose that listing. Check
the route without running a session:

```
python3 paper_dots_agent.py --probe          # endpoint, model, key, tool support
python3 paper_dots_agent.py --check-tools    # exit 0/1 on tool_choice=auto
printf 'Summarize this file: ...' | python3 paper_dots_agent.py --chat
```

**Agentic sessions need tool calls.** The hosted route supports them; the
adapter checks `tool_choice=auto` before a dsh session and warns if the
endpoint refuses it. `--harness chat` is a text-only route and does not
complete a pipeline stage that must write artifacts. Set
`PAPER_DOTS_REQUIRE_TOOLS=1` (or `PAPER_DOTS_CHECK_TOOLS=1`) to make the tool
probe a hard preflight for a production run. The platform applies per-key RPM
and TPM limits; keep `--jobs` modest when the key is rate-limited (the
pipeline's normal retry/backoff policy applies to a 429). The optional LLM
audits have their own backends: the defect audit defaults to `codex-lite` and
the conflict audit is off; pass `--defect-audit dots` / `--conflict-agent dots`
to keep those passes on Dots too (the judge panel already defaults to
the producer's harness/model pair).

## Choosing the model and harness (`--agent-harness` / `--agent-model`)

`run`/`run-decide` now split the old `--agent` choice into two independent
options. The defaults are **`dsh` + `deepseek-flash`**:

| model (`--agent-model`) | latest model id | default harness | supported harnesses |
| --- | --- | --- | --- |
| `deepseek-flash` | `deepseek-flash` | `dsh` | `dsh`, `gpt-codex`, `claude-code` |
| `gpt-sol` | `gpt-6.1-sol` | `gpt-codex` | `dsh`, `gpt-codex` |
| `gpt-terra` | `gpt-6.1-terra` | `gpt-codex` | `dsh`, `gpt-codex` |
| `claude-opus` | Claude Code alias `opus` / `claude-opus-5-5` | `claude-code` | `dsh`, `claude-code` |
| `claude-sonnet` | Claude Code alias `sonnet` / `claude-sonnet-5-5` | `claude-code` | `dsh`, `claude-code` |
| `qwen38-27b` | `qwen3.8-27b` (local vLLM) | `dsh` | `dsh`, `gpt-codex`, `claude-code` |
| `dots3-note-preview` | `dots3-note-prev` (Dots API) | `dsh` | `dsh`, `gpt-codex`, `claude-code` |

| harness (`--agent-harness`) | CLI | default model |
| --- | --- | --- |
| `dsh` | DeepSeek Harness (`dsh --profile headless --json -`) | `deepseek-flash` |
| `gpt-codex` | OpenAI Codex (`codex exec`) | `gpt-sol` |
| `claude-code` | Claude Code (`claude --permission-mode bypassPermissions --print`) | `claude-sonnet` |

`qwen38-27b` through `claude-code` requires a vLLM server that serves the
Anthropic Messages API; on a server that only serves the OpenAI routes the
first request fails rather than silently switching protocols.
`qwen38-27b` through `gpt-codex` uses the qwen adapter's Codex route, which
needs a vLLM server that serves `/v1/responses`; a server with only Chat
Completions should use `dsh` for that model (or the Codex chat-completions
bridge in the reference evaluation harness).

The two axes are independent only where the wire protocol supports the pair.
If only the harness is given, its default model is used; if only the model is
given, its default harness is used. An unsupported pair (GPT through Claude
Code, Claude through Codex) is refused before any session starts, never once
per stage. `--judge-agent-harness` and
`--judge-agent-model` select the same pair for the judge panel and default to
the producer's pair; `--judge-manual` stages its prompts for a human.
`PAPER_AGENT_HARNESS` / `PAPER_AGENT_MODEL` (and the `PAPER_JUDGE_AGENT_*`
equivalents) supply defaults when the flags are absent.

## Arbitrary OpenAI-compatible endpoints

`--agent-model` also accepts an `http://` or `https://` chat-completions URL.
A custom endpoint runs on **`dsh`** (the default harness): Codex only speaks the
Responses protocol and Claude Code only Anthropic Messages, so an arbitrary
chat-completions URL is refused on those two rather than silently translated.

```bash
# a local vLLM/OpenAI-compatible server
python paper_pipeline.py run --root ./paper_rounds \
    --agent-model http://127.0.0.1:8000/v1/chat/completions \
    --agent-model-api-key "$LOCAL_KEY"

# OpenRouter (it hosts many models, so name the one to use)
python paper_pipeline.py run --root ./paper_rounds \
    --agent-model https://openrouter.ai/api/v1/chat/completions \
    --agent-model-api-key "$OPENROUTER_API_KEY" \
    --agent-model-name "anthropic/claude-sonnet-4.5"
```

The key is exported to the adapter through `PAPER_AGENT_MODEL_API_KEY` (the
judge equivalent uses `PAPER_JUDGE_AGENT_MODEL_API_KEY`); it is never written
into the generated DSH provider patch or the run record, and the option's
value is redacted from the run log. Prefer the environment variable when the
process list must not show the key. `--agent-model-name` /
`PAPER_AGENT_MODEL_NAME` is required when the endpoint's `/v1/models` listing
has more than one model; a single-model endpoint (such as a local vLLM) is
detected automatically. The adapter reuses the endpoint's advertised context
window when its catalog carries one, and otherwise uses
`PAPER_AGENT_CONTEXT_WINDOW` (default 32768) and `PAPER_AGENT_MAX_TOKENS`
(default 8192).

`--agent-model-prep-json` merges a JSON object into every request to the
custom endpoint, after the harness has built its normal payload:

```bash
python paper_pipeline.py run --root ./paper_rounds \
    --agent-model http://127.0.0.1:8000/v1/chat/completions \
    --agent-model-api-key "$LOCAL_KEY" \
    --agent-model-prep-json '{"temperature": 0.2, "max_tokens": 8192, "reasoning_effort": "high"}'
```

The merge is recursive and the object may be incomplete: keys it omits keep
the harness defaults (including nested keys such as `reasoning.summary`), and
a key it carries replaces that default; provider-specific spellings (such as
`max_token_len`) are passed through verbatim. It applies only to a custom
endpoint URL, so to use it with a model that also has a shorthand (for example
qwen38-27b) pass that model's endpoint URL and `--agent-model-name` instead of
the shorthand. `PAPER_AGENT_MODEL_PREP_JSON` supplies the same object from the
environment. Every `--agent-*` option has a `--judge-agent-*` equivalent, so
the judge side uses `--judge-agent-model`, `--judge-agent-model-api-key`,
`--judge-agent-model-name`, `--judge-agent-model-prep-json` (or
`PAPER_JUDGE_AGENT_MODEL_PREP_JSON`) and `--judge-agent-cmd` in the same way.

**Credentials.** The native harnesses use their own configuration first:
`dsh` uses its `$DSH_HOME` credentials (its GPT/Claude routes use
`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` or the stored DSH sign-in); `gpt-codex`
uses the Codex login or `OPENAI_API_KEY`; `claude-code` uses the Claude Code
login or `ANTHROPIC_API_KEY`. `gpt-codex` and `claude-code` running
`deepseek-flash` use DeepSeek's documented Responses and Anthropic-compatible
endpoints and require `DEEPSEEK_API_KEY`. `qwen38-27b` keeps the
`PAPER_QWEN_*` vLLM settings and `dots3-note-preview` keeps `DOTS_API_KEY`.
The "latest" ids above were read from Codex 0.167.0 and the DSH catalog on
2026-11-10; a newer harness release can be supported by updating the small
registry in `paper_model_agent.py` / `paper_pipeline_parts/p01_venues.py`.
The optional `--defect-audit` and `--conflict-agent` passes keep their own
legacy backend choices (`codex-lite`, `codex`, `claude`, `dsh`, `qwen`,
`dots`, `manual`); pass the family that matches the run (e.g.
`--defect-audit dsh`) when those passes should not fall back to ChatGPT.

Examples:

```bash
# the new default: DeepSeek Harness + DeepSeek Flash
python paper_pipeline.py run --root ./paper_rounds

python paper_pipeline.py run --root ./paper_rounds \
    --agent-harness gpt-codex --agent-model gpt-sol
python paper_pipeline.py run --root ./paper_rounds \
    --agent-harness claude-code --agent-model claude-opus
python paper_pipeline.py run --root ./paper_rounds \
    --agent-harness dsh --agent-model gpt-terra
python paper_pipeline.py run --root ./paper_rounds \
    --agent-harness gpt-codex --agent-model deepseek-flash
# a different, cheaper judge pair
python paper_pipeline.py run --root ./paper_rounds \
    --agent-harness claude-code --agent-model claude-sonnet \
    --judge-agent-harness gpt-codex --judge-agent-model gpt-terra
```

The legacy `--agent` / `--judge-agent` shortcuts are gone: they were replaced
by `--manual` / `--judge-manual` and the `--agent-harness`/`--agent-model`
pair. `conform` and `add-venue` still take their own `--agent` option, which is
unrelated to the run/judge pair. The Qwen and Dots adapters are selected through
`--agent-model qwen38-27b` / `--agent-model dots3-note-preview`, and their
sections above remain the detailed reference for those adapters.

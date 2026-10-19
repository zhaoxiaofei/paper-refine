# Qwen3.8-27B provider integration (2026-10-19)

## What was added

The pipeline can now run its agent sessions on **Qwen3.8-27B through an
OpenAI-compatible vLLM endpoint**, reached through the operator's SSH tunnel.
It does not reimplement the agent loop: the new adapter points the harness the
operator already uses (`codex` or `dsh`) at the endpoint, and a text-only
`chat` mode is available for jobs that need no tools.

| file | role |
|---|---|
| `paper_qwen_agent.py` (new, executable) | the adapter: endpoint/tunnel management, codex provider overrides, dsh `llm-pi-ai` patch, `chat` mode, `--probe`, `--check-tools` |
| `paper_pipeline.py` | new `qwen` entry in `AGENT_PRESETS` / `AGENT_CHOICES` (and therefore `--agent qwen`, `--judge-agent qwen`, `--conflict-agent qwen`); the adapter travels in `PIPELINE_MODULE_FILES`, is copied at `setup`, and is synced by `sync-code` |
| `README.md` | `--agent qwen` documentation and requirements |
| `.paper_test/test_qwen_provider_2026_1019.py` | 19 offline checks (fake vLLM) + an optional live probe |
| `.paper_test/test_dsh_backend.py` | the agent-choice list now includes `qwen` |

## Use

```bash
# optional: the adapter starts this itself when the endpoint is not reachable
ssh -p 52080 -N -L 18000:127.0.0.1:8000 zxf@101.6.31.113

# check the route without running a session
./paper_qwen_agent.py --probe

# a stage or the whole run: codex harness by default
python3 paper_pipeline.py run --root <root> --agent qwen

# DeepSeek Harness instead of codex
PAPER_QWEN_HARNESS=dsh python3 paper_pipeline.py run --root <root> --agent qwen

# text-only completion (no tools; does not complete a stage that writes files)
printf 'Summarize this file: ...' | ./paper_qwen_agent.py --chat
```

Environment:

| variable | default |
|---|---|
| `PAPER_QWEN_BASE_URL` | `http://127.0.0.1:18000/v1` |
| `PAPER_QWEN_MODEL` | `qwen3.8-27b` |
| `PAPER_QWEN_API_KEY` | `dummy` (vLLM usually needs none) |
| `PAPER_QWEN_HARNESS` | `codex` (`codex`/`dsh`/`chat`) |
| `PAPER_QWEN_REASONING_EFFORT` | `low` (qwen rejects codex's `max`) |
| `PAPER_QWEN_TUNNEL` | `auto` (`off`/`require`) |
| `PAPER_QWEN_SSH_HOST` | `zxf@101.6.31.113` |
| `PAPER_QWEN_SSH_PORT` | `52080` |
| `PAPER_QWEN_TUNNEL_LOCAL` | `18000` |
| `PAPER_QWEN_TUNNEL_REMOTE` | `127.0.0.1:8000` |
| `PAPER_QWEN_REQUIRE_TOOLS` | unset (`1` makes the tool probe a hard preflight) |
| `PAPER_QWEN_CHECK_TOOLS` | unset (`1` checks tool support and fails if absent) |

## How each harness is connected

### codex

`codex exec` receives one `-c` override per provider field:

```
model_provider="qwen"
model="qwen3.8-27b"
model_providers.qwen.name="Qwen vLLM (qwen3.8-27b)"
model_providers.qwen.base_url="http://127.0.0.1:18000/v1"
model_providers.qwen.env_key="PAPER_QWEN_API_KEY"
model_providers.qwen.wire_api="responses"
model_reasoning_effort="low"
```

The installed codex (0.163.0) rejects `wire_api="chat"`; vLLM exposes
`/v1/responses`, so the route uses the Responses wire API. The adapter keeps
the pipeline's `-c mcp_servers.*.default_tools_approval_mode="approve"`
overrides for the docx MCP servers.

### dsh

The adapter generates a temporary patch and runs
`dsh --profile headless --patch <patch> --json -`:

```yaml
- id: llm-pi-ai
  config:
    providers:
      qwen:
        displayName: "Qwen vLLM (qwen3.8-27b)"
        apiKeyEnv: PAPER_QWEN_API_KEY
        api: openai-completions
        baseURL: "http://127.0.0.1:18000/v1"
        models:
          - id: "qwen3.8-27b"
            name: "Qwen3.8-27B"
            contextWindow: 32768
            maxTokens: 8192
            reasoningEfforts: {low: low, medium: medium, xhigh: xhigh}
- id: agent-default-model
  config:
    provider: qwen
    model: "qwen3.8-27b"
    reasoningEffort: "low"
```

A read-only `~/.dsh` (e.g. a sandbox) gets a light temporary `DSH_HOME`:
the headless profile metadata is copied and `node_modules` is symlinked, so
the operator's installed harness is reused. A `dsh --json` turn that ends with
`reason: {kind: error}` is surfaced as a nonzero adapter exit (dsh itself can
exit 0 on that stream).

## Validation performed

Live endpoint (the task's `curl /v1/models` output): `GET /v1/models` returns
`qwen3.8-27b`; `--probe` reports the model; `--chat` returns text; the codex
route returns text.

Offline tests (fake vLLM HTTP server): provider argv, dsh patch, probe, chat,
tool refusal/acceptance, pipeline choices/resolution, module manifest.

**Known limitation (server-side, not the adapter):** the live vLLM server was
started without `--enable-auto-tool-choice --tool-call-parser`, so
`tool_choice: auto` is rejected:

```
400: "auto" tool choice requires --enable-auto-tool-choice and
     --tool-call-parser to be set
```

Consequences:

* `--harness dsh` fails a tool-using turn (the adapter warns; `--probe` reports
  `tools: NOT accepted`).
* `--harness codex` returns text, but qwen's raw tool-call markup is not
  executed by the codex tool loop; the codex session cannot edit the sandbox.
* `--harness chat` is text-only and does not satisfy a pipeline stage's
  completion contract.

A production Qwen run therefore needs the vLLM server restarted with the tool
flags (and a parser matching the model's chat template), or a tool-capable
gateway in front of it. The adapter reports this gap instead of pretending the
session succeeded. Set `PAPER_QWEN_REQUIRE_TOOLS=1` to make the preflight
refuse before a stage starts.

## Tests run

```bash
python3 .paper_test/test_qwen_provider_2026_1019.py      # PASSED
PAPER_QWEN_LIVE=1 python3 .paper_test/test_qwen_provider_2026_1019.py  # live probe PASSED
python3 .paper_test/test_dsh_backend.py                  # PASSED
python3 .paper_test/test_pipeline.py                     # PASSED
python3 .paper_test/test_round2_regressions_2026_1019.py # PASSED
./paper_qwen_agent.py --probe                            # endpoint + tools report
printf 'Reply with exactly: OK\n' | ./paper_qwen_agent.py --harness codex  # OK
```

No git commit was made.

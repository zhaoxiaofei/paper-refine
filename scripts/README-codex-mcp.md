# Import Codex MCP servers into DeepSeek Harness

`install-codex-mcp.mjs` copies the MCP servers that Codex sees into a DSH
profile. DSH does not read `~/.codex/config.toml`; it mounts one
`@deepseek-ai/dsh-mcp-client` row per server in the profile's
`cordis.patch.yml`. This script performs that translation, installs the DSH
MCP client at the exact DSH version, and validates the result.

Tested with DSH `0.2.0-rc.2` and Codex CLI `0.163.0` on Linux.

## Quick start

```bash
cd /path/to/paper-refine                      # the repository root
./scripts/install-codex-mcp.sh --dry-run      # inspect the patch first
./scripts/install-codex-mcp.sh                # write it
```

Defaults: profile `$DSH_PROFILE` or `headless`, DSH home `$DSH_HOME` or
`~/.dsh`, Codex home `$CODEX_HOME` or `~/.codex`.

Use a different profile, or import only some servers:

```bash
./scripts/install-codex-mcp.sh --profile web
./scripts/install-codex-mcp.sh --only docx-converter,docx-compare,zotero
./scripts/install-codex-mcp.sh --exclude deepseek-vision
```

## What it does

1. Runs `codex mcp list --json`, so Codex itself resolves includes, plugin
   servers, `enabled = false`, and default values.
2. Installs `@deepseek-ai/dsh-mcp-client@<dsh --version>` into the profile with
   `dsh plugin --profile <name> add ...`. If the registry install fails, it
   falls back to the copy shipped inside the DSH installation.
3. Replaces a marked block in
   `<dsh-home>/profiles/<profile>/cordis.patch.yml`. Everything outside the
   markers is preserved; re-running is idempotent.
4. Backs up the old patch as `cordis.patch.yml.bak-codex-mcp-<timestamp>` and
   runs `dsh --profile <name> --dump-config` to reject an invalid composition.
5. Sets the patch file and backups to mode `0600`, because the generated file
   may contain API keys copied from Codex.

## Mapping

| Codex (`mcp_servers.*`) | DSH (`@deepseek-ai/dsh-mcp-client`) |
|---|---|
| `command`, `args`, `env`, `cwd` | same fields |
| `env_vars = ["NAME"]` | `NAME: !!js "process.env['NAME'] ?? ''"` |
| `url` (streamable HTTP) | `transport: streamable-http`, `url` |
| `http_headers` | `headers` (literal values) |
| `env_http_headers` | `headers` with `!!js` expressions |
| `bearer_token_env_var` | `Authorization: Bearer ${process.env[...]}` |
| `tool_timeout_sec` | `toolCallTimeoutMs` (seconds × 1000) |
| `enabled = false` | skipped, or `disabled: true` with `--include-disabled` |
| server name | `serverName`, sanitized to `[A-Za-z0-9_-]{1,32}` |

DSH exposes each tool as `mcp__<serverName>__<toolName>`.

## Codex fields with no DSH equivalent

- `startup_timeout_sec` — DSH has no per-server startup timeout. A slow server
  can delay startup; connection errors are logged and the harness continues
  (`failOnStartupError` defaults to false).
- `enabled_tools` / `disabled_tools` — DSH has no per-server tool allow/deny
  list; every tool the server advertises is registered.
- `http_headers_helper` — DSH cannot run a per-request header helper.
- Codex OAuth (`auth_status = "oauth"`) — DSH supports static headers and
  bearer-token environment variables, not Codex's OAuth flow.
- `default_tools_approval_mode` — DSH approval is a session/profile policy, not
  a per-server setting.

## Verify

```bash
DSH_HOME=~/.dsh dsh --profile headless --dump-config | grep -A8 codex-mcp
```

Then start the profile and ask for a tool by name:

```bash
dsh --profile headless "Call the mcp__docx-converter__* tool and list its tools."
```

Headless has HMR off, so restart it after the install. A web profile with HMR
on reloads the patch automatically.

## Remove

```bash
./scripts/install-codex-mcp.sh --remove
```

This removes only the marked block. It leaves the
`@deepseek-ai/dsh-mcp-client` package installed; remove that with
`dsh plugin --profile headless remove @deepseek-ai/dsh-mcp-client` if desired.

## Notes

- The script reads Codex config; it never writes it.
- MCP server processes run with your user privileges, outside DSH's bash
  sandbox. Treat a server in `config.toml` like a program you chose to run.
- If `npx -y ...` fails under DSH with an npm cache permission error, install
  that package in a writable npm cache or replace `command` with an absolute
  executable path.

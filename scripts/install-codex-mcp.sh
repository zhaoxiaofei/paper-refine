#!/usr/bin/env bash
# Convenience wrapper: run the Node installer with the same arguments.
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec node "$here/install-codex-mcp.mjs" "$@"

#!/usr/bin/env bash
# Install every dependency this checkout needs, without baking a machine path
# into the repository.
#
# What it installs
#   * the reproducible conda environment described by `env/` (through
#     `scripts/create-test-env.sh`);
#   * the optional `pyzotero-cli` (`zot`) command in that environment, when pip
#     can reach it;
#   * the Node dependencies of both shipped MCP servers;
#   * the two paper skills and both shipped MCP servers in every agent harness
#     present on this machine (through `install_agent_tooling.sh`), plus the
#     Zotero MCP service when its checkout is present;
#   * the external Zotero checkouts under `external/`:
#       - `zotero-use`                 the `zot` skill / CLI source
#       - `openai-plugins`             the Zotero helper (`ZOTERO_SKILL`)
#       - `codex-zotero-bridge`        the Zotero MCP service
#   * `deps.env` and `activate-deps.sh`, both RELATIVE to this checkout.
#
# What it does not install
#   System packages (Zotero Desktop, Microsoft Word, LibreOffice, Poppler,
#   Ghostscript, ImageMagick, TeX Live, codex/dsh). It probes for them and
#   prints the exact missing command; installing an operating-system package is
#   the operator's decision.
#
# Usage
#   ./install_dependencies.sh                 # install/refresh everything it can
#   ./install_dependencies.sh --recreate      # recreate the conda env first
#   ./install_dependencies.sh --dry-run       # print the plan, change nothing
#   ./install_dependencies.sh --offline       # reuse external checkouts (conda/npm/pip still run)
#   ./install_dependencies.sh --no-conda      # skip the Python environment
#   ./install_dependencies.sh --no-node       # skip npm, skills and MCP registration
#   ./install_dependencies.sh --no-external   # skip the external git checkouts
#   ./install_dependencies.sh --no-agent-tooling  # skip skill/MCP registration
#   ./install_dependencies.sh --no-zot-cli        # skip the optional pyzotero-cli install
#   ./install_dependencies.sh --no-zotero-mcp     # do not register the Zotero MCP server
#   ./install_dependencies.sh --strict-external   # fail when an external repo fails
#
# Every path this script writes into a generated file is relative to this
# checkout; `activate-deps.sh` turns those into absolute paths for the current
# shell only. Nothing in this script names a machine's home directory.
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ENV_NAME="${PAPER_REFINE_TEST_ENV:-paper-refine-test}"
DEPS_DIR="${PAPER_REFINE_DEPS:-$REPO_ROOT/external}"
DRY_RUN=0
OFFLINE=0
RECREATE=0
DO_CONDA=1
DO_NODE=1
DO_EXTERNAL=1
DO_AGENT=1
INSTALL_ZOT_CLI=1
REGISTER_ZOTERO_MCP=1
STRICT_EXTERNAL=0
FAILED=()
MISSING_TOOLS=()
REPOS_INSTALLED=()

usage() {
    sed -n '2,41p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

note() { printf '[install] %s\n' "$*"; }
warn() { printf '[install] warning: %s\n' "$*" >&2; }
step() { printf '\n[install] == %s ==\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
fail_step() { warn "$*"; FAILED+=("$*"); }
run() {
    if [ "$DRY_RUN" = 1 ]; then
        printf '[install] would run: %s\n' "$*"
        return 0
    fi
    "$@"
}
relpath() {
    python3 -c 'import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$2"
}

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --offline) OFFLINE=1 ;;
        --recreate) RECREATE=1 ;;
        --no-conda) DO_CONDA=0 ;;
        --no-node) DO_NODE=0 ;;
        --no-external) DO_EXTERNAL=0 ;;
        --no-agent-tooling) DO_AGENT=0 ;;
        --no-zot-cli) INSTALL_ZOT_CLI=0 ;;
        --no-zotero-mcp) REGISTER_ZOTERO_MCP=0 ;;
        --strict-external) STRICT_EXTERNAL=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'error: unknown argument %s (use --help)\n' "$arg" >&2; exit 2 ;;
    esac
done

if [ "$DO_NODE" = 0 ]; then
    if [ "$DO_AGENT" = 1 ]; then
        warn "--no-node given: skipping npm, the agent skills and MCP registration"
    fi
    DO_AGENT=0
fi
if [ "$DO_AGENT" = 0 ]; then
    # "MCP registration" is part of agent-tooling setup: both --no-node and
    # --no-agent-tooling must not add the Zotero server row either.
    REGISTER_ZOTERO_MCP=0
fi

case "$DEPS_DIR" in
    "~") DEPS_DIR="$HOME" ;;
    "~/"*) DEPS_DIR="$HOME/${DEPS_DIR#\~/}" ;;
    /*) ;;
    *) DEPS_DIR="$REPO_ROOT/$DEPS_DIR" ;;
esac
DEPS_DIR=$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$DEPS_DIR")
if [ "$DRY_RUN" = 0 ] && [ "$DO_EXTERNAL" = 1 ]; then
    mkdir -p -- "$DEPS_DIR"
fi

# ---- prerequisite probes ---------------------------------------------------
step "prerequisite probes"
have bash || MISSING_TOOLS+=("bash")
have python3 || MISSING_TOOLS+=("python3")
if [ "$DO_CONDA" = 1 ] && ! have conda; then
    MISSING_TOOLS+=("conda")
fi
if [ "$DO_EXTERNAL" = 1 ] && ! have git; then
    MISSING_TOOLS+=("git")
fi
if [ "$DO_NODE" = 1 ]; then
    have node || MISSING_TOOLS+=("node")
    have npm || MISSING_TOOLS+=("npm")
fi
if [ "${#MISSING_TOOLS[@]}" -gt 0 ]; then
    for tool in "${MISSING_TOOLS[@]}"; do
        warn "required command not found: $tool"
    done
    warn "install the missing command(s), or pass the matching --no-* flag to skip that part"
    if [ "$DRY_RUN" = 0 ]; then
        exit 2
    fi
fi

# The optional tools are reported, never installed: some need administrator
# rights and all are probed at run time by the pipeline.
OPTIONAL_TOOLS=(
    codex dsh conda node npm
    soffice libreoffice pandoc pdftotext pdftoppm gs latexmk pdflatex
    powershell.exe montage magick
)
note "optional runtime tools detected:"
for tool in "${OPTIONAL_TOOLS[@]}"; do
    if have "$tool"; then
        printf '  [ok ] %s\n' "$tool"
    else
        printf '  [-- ] %s (absent; the pipeline reports the missing capability)\n' "$tool"
    fi
done

# ---- conda environment -----------------------------------------------------
if [ "$DO_CONDA" = 1 ]; then
    step "conda environment: $ENV_NAME"
    if ! have conda; then
        fail_step "conda is not on PATH; cannot create $ENV_NAME"
    else
        env_args=()
        [ "$RECREATE" = 1 ] && env_args+=(--recreate)
        if ! run env PAPER_REFINE_TEST_ENV="$ENV_NAME" \
                bash "$REPO_ROOT/scripts/create-test-env.sh" "${env_args[@]}"; then
            fail_step "scripts/create-test-env.sh failed for $ENV_NAME"
        fi
        if [ "$INSTALL_ZOT_CLI" = 1 ] && [ "$DRY_RUN" = 0 ] \
                && conda run -n "$ENV_NAME" python -c 'import sys' >/dev/null 2>&1; then
            note "installing the optional pyzotero-cli (`zot`) command"
            if ! run conda run -n "$ENV_NAME" python -m pip install \
                    --disable-pip-version-check pyzotero-cli; then
                warn "pyzotero-cli could not be installed; the Zotero MCP/skill routes still work"
            fi
        fi
    fi
else
    warn "skipped the conda environment (--no-conda)"
fi

# ---- Node dependencies of the shipped MCP servers --------------------------
if [ "$DO_NODE" = 1 ]; then
    step "Node dependencies for the shipped MCP servers"
    if ! have npm; then
        fail_step "npm is not on PATH; cannot install the MCP server dependencies"
    else
        for server in mcp-docx-compare mcp-docx-converter; do
            if [ ! -f "$REPO_ROOT/$server/package.json" ]; then
                warn "$server/package.json is missing; skipping"
                continue
            fi
            if ! ( cd -- "$REPO_ROOT/$server" && run npm ci --no-audit --no-fund ); then
                fail_step "npm ci failed in $server"
            fi
        done
    fi
fi

# ---- external git checkouts ------------------------------------------------
# These are optional for the pipeline itself: without them the Zotero MCP
# service, the Zotero skill and the `zot` CLI are simply unavailable, and every
# prompt routes Zotero work to the next available route or to manual
# verification. A checkout that cannot be reached therefore warns by default;
# `--strict-external` turns that warning into a failure for a reproducible
# machine image.
install_repo() {
    local name=$1 url=$2 dest=$3 ref=$4
    local commit=""
    if [ -d "$dest/.git" ]; then
        if [ "$OFFLINE" = 0 ] && [ -z "$(git -C "$dest" status --porcelain 2>/dev/null || true)" ]; then
            note "refreshing $name"
            if run git -C "$dest" fetch --depth 1 origin "$ref" >/dev/null 2>&1; then
                run git -C "$dest" checkout --detach FETCH_HEAD >/dev/null 2>&1 || \
                    warn "could not check out $name/$ref; keeping the existing checkout"
            else
                warn "could not fetch $name/$ref; keeping the existing checkout"
            fi
        fi
    elif [ -e "$dest" ]; then
        warn "$dest exists but is not a git checkout; leaving it untouched"
        [ "$STRICT_EXTERNAL" = 1 ] && fail_step "external path is not a git checkout: $name"
    elif [ "$OFFLINE" = 1 ]; then
        warn "offline: $name is not installed (expected at $dest)"
        [ "$STRICT_EXTERNAL" = 1 ] && fail_step "missing external checkout: $name"
        return 1
    else
        note "cloning $name -> $dest"
        if ! run git clone --depth 1 --branch "$ref" "$url" "$dest"; then
            warn "shallow clone of $name/$ref failed; retrying the default branch"
            if ! run git clone --depth 1 "$url" "$dest"; then
                warn "could not clone $name from $url"
                [ "$STRICT_EXTERNAL" = 1 ] && fail_step "could not clone external checkout: $name"
                return 1
            fi
        fi
    fi
    if [ "$DRY_RUN" = 0 ] && [ -d "$dest/.git" ]; then
        commit=$(git -C "$dest" rev-parse HEAD 2>/dev/null || true)
        REPOS_INSTALLED+=("$name=$commit")
        note "$name at ${commit:-unknown}"
    fi
    return 0
}

if [ "$DO_EXTERNAL" = 1 ]; then
    step "external Zotero checkouts under ${DEPS_DIR#"$REPO_ROOT"/}"
    if ! have git; then
        fail_step "git is not on PATH; cannot clone the external checkouts"
    else
        install_repo "zotero-use" \
            "https://github.com/drguptavivek/zotero-use.git" \
            "$DEPS_DIR/zotero-use" "${ZOTERO_USE_REF:-main}" || true
        install_repo "openai-plugins" \
            "https://github.com/openai/plugins.git" \
            "$DEPS_DIR/openai-plugins" "${OPENAI_PLUGINS_REF:-main}" || true
        install_repo "codex-zotero-bridge" \
            "https://github.com/GuoXin-Ink/codex-zotero-bridge.git" \
            "$DEPS_DIR/codex-zotero-bridge" "${ZOTERO_BRIDGE_REF:-main}" || true
    fi
else
    warn "skipped the external Zotero checkouts (--no-external)"
fi

# ---- agent harness registration -------------------------------------------
if [ "$DO_AGENT" = 1 ]; then
    step "agent skills and MCP servers"
    if ! have node; then
        fail_step "node is not on PATH; cannot register the MCP servers"
    elif ! have codex && ! have dsh && ! have dshx; then
        warn "no codex/dsh CLI detected; keeping the local skills and servers only"
    elif ! run env INSTALL_CODEX=auto INSTALL_DSH=auto \
            bash "$REPO_ROOT/install_agent_tooling.sh"; then
        fail_step "install_agent_tooling.sh failed"
    fi
else
    warn "skipped agent-tooling registration (--no-agent-tooling/--no-node)"
fi

# ---- the Zotero MCP service ------------------------------------------------
if [ "$DO_EXTERNAL" = 1 ] && [ "$REGISTER_ZOTERO_MCP" = 1 ]; then
    step "Zotero MCP service registration"
    bridge="$DEPS_DIR/codex-zotero-bridge/scripts/zotero_mcp.py"
    if [ "$DRY_RUN" = 1 ]; then
        note "would register the Zotero MCP server from $bridge when a harness is present"
    elif [ ! -f "$bridge" ]; then
        warn "the Zotero bridge is not installed at $bridge; skipping its MCP row"
    elif ! have python3; then
        warn "python3 is not on PATH; skipping the Zotero MCP row"
    else
        python_bin=$(command -v python3)
        codex_has_zotero() {
            CODEX_HOME="$1" codex mcp list --json 2>/dev/null | python3 -c 'import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
if isinstance(data, list):
    rows = data
elif isinstance(data, dict) and isinstance(data.get("servers"), list):
    rows = data["servers"]
else:
    rows = []
sys.exit(0 if any((row or {}).get("name") == "zotero" for row in rows) else 1)'
        }
        if have codex; then
            codex_home="${CODEX_HOME:-$HOME/.codex}"
            if codex_has_zotero "$codex_home"; then
                note "codex already knows a 'zotero' MCP server; leaving it untouched"
            else
                if [ -f "$codex_home/config.toml" ]; then
                    cp -p -- "$codex_home/config.toml" \
                        "$codex_home/config.toml.bak-zotero-$(date +%Y%m%d%H%M%S)"
                fi
                if run env CODEX_HOME="$codex_home" codex mcp add zotero -- \
                        "$python_bin" "$bridge" && codex_has_zotero "$codex_home"; then
                    note "registered codex MCP server: zotero"
                else
                    fail_step "could not register the Zotero MCP server with codex"
                fi
            fi
        fi
        if have dsh; then
            dsh_home="${DSH_HOME:-$HOME/.dsh}"
            if ! have node || [ ! -d "$dsh_home/profiles" ]; then
                warn "dsh is present but node or its profiles directory is missing; skipped the dsh Zotero row"
            else
                servers_json=$(mktemp)
                node -e '
                    const fs = require("fs");
                    const [out, python, script] = process.argv.slice(1);
                    const row = {
                        name: "zotero",
                        enabled: true,
                        transport: {
                            type: "stdio",
                            command: python,
                            args: [script],
                            env: null,
                            env_vars: [],
                            cwd: null,
                        },
                    };
                    fs.writeFileSync(out, `${JSON.stringify([row], null, 2)}\n`);
                ' "$servers_json" "$python_bin" "$bridge"
                profiles=0
                for profile_dir in "$dsh_home"/profiles/*/; do
                    [ -f "$profile_dir/cordis.patch.yml" ] || continue
                    profile=$(basename -- "$profile_dir")
                    if grep -Eq '^[[:space:]]*serverName:[[:space:]]*["'"'"']?zotero["'"'"']?[[:space:]]*(#.*)?$' \
                            "$profile_dir/cordis.patch.yml"; then
                        note "dsh profile $profile already carries a zotero row; leaving it untouched"
                        profiles=$((profiles + 1))
                        continue
                    fi
                    profiles=$((profiles + 1))
                    if ! run node "$REPO_ROOT/scripts/install-codex-mcp.mjs" \
                            --profile "$profile" --dsh-home "$dsh_home" \
                            --servers-json "$servers_json" --merge; then
                        fail_step "could not register the Zotero MCP server in dsh profile $profile"
                    fi
                done
                rm -f -- "$servers_json"
                [ "$profiles" -gt 0 ] || warn "no dsh profile with cordis.patch.yml found"
            fi
        fi
        note "manual pairing: in Zotero choose Tools > Codex Zotero Bridge > Pair Codex,"
        note "then call the zotero_pair tool with the one-time 8-digit code"
    fi
elif [ "$REGISTER_ZOTERO_MCP" = 0 ]; then
    warn "skipped the Zotero MCP registration (--no-zotero-mcp/--no-node/--no-agent-tooling)"
fi

# ---- generated, relative-path environment ---------------------------------
step "dependency environment"
if [ "$DRY_RUN" = 0 ]; then
    DEPS_REL=$(relpath "$DEPS_DIR" "$REPO_ROOT")
    {
        printf '# Generated by ./install_dependencies.sh -- do not edit.\n'
        printf '# Values are RELATIVE to the checkout root; source activate-deps.sh to export them.\n'
        printf 'PAPER_REFINE_DEPS=%s\n' "$DEPS_REL"
        write_optional_var() {
            local key=$1 path=$2 kind=${3:-file}
            if { [ "$kind" = dir ] && [ -d "$path" ]; } \
                    || { [ "$kind" = file ] && [ -f "$path" ]; }; then
                printf '%s=%s\n' "$key" "$(relpath "$path" "$REPO_ROOT")"
            else
                printf '# %s not installed (%s)\n' "$key" "$(relpath "$path" "$REPO_ROOT")"
            fi
        }
        if [ -d "$DEPS_DIR/openai-plugins" ]; then
            write_optional_var "ZOTERO_PLUGINS_ROOT" "$DEPS_DIR/openai-plugins" dir
            write_optional_var "ZOTERO_SKILL" \
                "$DEPS_DIR/openai-plugins/plugins/zotero/skills/zotero/scripts/zotero.py"
        else
            printf '# ZOTERO_PLUGINS_ROOT not installed (%s)\n' \
                "$(relpath "$DEPS_DIR/openai-plugins" "$REPO_ROOT")"
            printf '# ZOTERO_SKILL not installed\n'
        fi
        if [ -d "$DEPS_DIR/zotero-use" ]; then
            printf 'ZOTERO_USE_ROOT=%s\n' "$(relpath "$DEPS_DIR/zotero-use" "$REPO_ROOT")"
        else
            printf '# ZOTERO_USE_ROOT not installed (%s)\n' \
                "$(relpath "$DEPS_DIR/zotero-use" "$REPO_ROOT")"
        fi
        if [ -d "$DEPS_DIR/codex-zotero-bridge" ]; then
            printf 'ZOTERO_BRIDGE_ROOT=%s\n' \
                "$(relpath "$DEPS_DIR/codex-zotero-bridge" "$REPO_ROOT")"
            write_optional_var "ZOTERO_BRIDGE_MCP" \
                "$DEPS_DIR/codex-zotero-bridge/scripts/zotero_mcp.py"
        else
            printf '# ZOTERO_BRIDGE_ROOT not installed (%s)\n' \
                "$(relpath "$DEPS_DIR/codex-zotero-bridge" "$REPO_ROOT")"
        fi
    } > "$REPO_ROOT/deps.env"

    cat > "$REPO_ROOT/activate-deps.sh" <<'EOF'
#!/usr/bin/env bash
# Source this file to export this checkout's dependency paths for the current shell.
# The values in deps.env are relative to this directory; nothing is written
# into the checkout's source tree.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "activate-deps.sh must be sourced: source ./activate-deps.sh" >&2
    exit 2
fi
_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [ ! -f "$_repo_root/deps.env" ]; then
    echo "activate-deps.sh: $_repo_root/deps.env is missing; run ./install_dependencies.sh" >&2
    return 1
fi
export PAPER_REFINE_ROOT="$_repo_root"
while IFS='=' read -r _key _value; do
    case "$_key" in
        ''|'#'*) continue ;;
    esac
    case "$_value" in
        /*) export "$_key=$_value" ;;
        *) export "$_key=$_repo_root/$_value" ;;
    esac
done < "$_repo_root/deps.env"
unset _repo_root _key _value
EOF
    chmod +x "$REPO_ROOT/activate-deps.sh"

    if [ "${#REPOS_INSTALLED[@]}" -gt 0 ]; then
        {
            printf '{\n  "installed_at": "%s",\n  "checkout": "%s",\n  "repos": {\n' \
                "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(relpath "${BASH_SOURCE[0]}" "$REPO_ROOT")"
            first=1
            for item in "${REPOS_INSTALLED[@]}"; do
                name=${item%%=*}
                commit=${item#*=}
                [ "$first" = 1 ] || printf ',\n'
                first=0
                printf '    "%s": {"commit": "%s"}' "$name" "$commit"
            done
            printf '\n  }\n}\n'
        } > "$DEPS_DIR/INSTALLED.json"
    fi
    note "wrote deps.env and activate-deps.sh (relative paths)"

    if [ "$DO_EXTERNAL" = 1 ]; then
    cat > "$DEPS_DIR/README.md" <<'EOF'
# External dependencies

Installed by `./install_dependencies.sh` when the checkout was reachable, and
intentionally gitignored. Every path below is relative to the paper-refine
checkout; `activate-deps.sh` exports the resolved values for the current shell.
`deps.env` marks any checkout that is not installed.

| directory | what it is | exported as |
|---|---|---|
| `openai-plugins/` | the Zotero helper plugin (from https://github.com/openai/plugins.git) | `ZOTERO_SKILL` |
| `zotero-use/` | the `$zotero-use` skill and `zot` CLI source (from https://github.com/drguptavivek/zotero-use) | `ZOTERO_USE_ROOT` |
| `codex-zotero-bridge/` | the Zotero MCP service (from https://github.com/GuoXin-Ink/codex-zotero-bridge) | `ZOTERO_BRIDGE_ROOT` |

`INSTALLED.json` records the commit checked out for each repository that could be installed.

The Zotero MCP service is registered with each harness when a harness is
present. It still needs the Zotero Desktop extension: in Zotero choose
**Tools > Codex Zotero Bridge > Pair Codex**, then call the `zotero_pair` MCP
tool with the one-time 8-digit code. Until it is paired, the stage prompts fall
back to the Zotero skill and then to the `zot` CLI, exactly as they document.
EOF
    fi
fi

# ---- summary ---------------------------------------------------------------
step "summary"
note "checkout:  $REPO_ROOT"
note "deps:      ${DEPS_DIR#"$REPO_ROOT"/}"
if [ "$DO_CONDA" = 1 ]; then
    note "conda env: $ENV_NAME (activate with: conda activate $ENV_NAME)"
else
    note "conda env: skipped (--no-conda)"
fi
note "shell env: source ./activate-deps.sh"
note "data:      the shipped venue profiles are local; venue exemplars are fetched per run by"
note "           'add-venue' and are not a global dependency"
note "run:       python paper_pipeline.py setup --source <manuscript-dir> --root <run-root>"
note "Zotero:    MCP service first, Zotero skill second, \`zot\` CLI fallback;"
note "           if all three are unavailable, the stage records manual verification."
if [ "${#FAILED[@]}" -gt 0 ]; then
    printf '\n[install] incomplete:\n' >&2
    for item in "${FAILED[@]}"; do printf '  - %s\n' "$item" >&2; done
    exit 1
fi
note "install complete"

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
#     `zotero` MCP row when the Zotero bridge is installed;
#   * the external Zotero checkouts:
#       - `zotero-use`                 the `zot` skill / CLI source
#       - `openai-plugins`             the Zotero helper (`ZOTERO_SKILL`)
#     under `external/`, and the Zotero MCP service (`zotero-bridge`, upstream
#     codex-zotero-bridge) under `$MCP_TOOLS_DIR` -- default `~/mcp-servers`,
#     next to the two docx MCP servers `install_agent_tooling.sh` deploys there;
#   * `deps.env` and `activate-deps.sh` -- checkout-relative paths, or absolute
#     for a dependency installed outside the checkout (the Zotero bridge).
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
# Environment overrides
#   PAPER_REFINE_DEPS   where the external/ checkouts live (default ./external)
#   MCP_TOOLS_DIR       where the MCP server trees live (default ~/mcp-servers)
#   ZOTERO_BRIDGE_DIR   the Zotero MCP service checkout
#                       (default $MCP_TOOLS_DIR/zotero-bridge)
#
# Paths inside this checkout are written relative to it; the Zotero bridge is
# installed outside (under `$MCP_TOOLS_DIR`) and recorded by absolute path.
# `activate-deps.sh` resolves both forms for the current shell only. Nothing in
# this script names a machine's home directory: the MCP tools directory is
# `$MCP_TOOLS_DIR`, the same variable and default `install_agent_tooling.sh`
# uses, so the bridge lands next to the servers it configures.
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
    # Print the header comment block; ending at the `set` line keeps the range
    # from drifting every time the header grows.
    sed -n '2,/^set -euo pipefail$/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'
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
# Absolute, normalized path for a directory that need not exist yet: a leading
# `~` is expanded and a relative value is resolved against this checkout. The
# directory is NOT created here (`mkdir` is the caller's job, because a
# pre-created empty destination would look like a foreign install to
# install_repo and block the clone).
# `python3` is one of the prerequisites probed below; using it unconditionally
# here made a machine without it die with "python3: command not found" before
# the script could print the required-command guidance.
abspath_dir() {
    local dir=$1
    case "$dir" in
        "~") dir="$HOME" ;;
        "~/"*) dir="$HOME/${dir#\~/}" ;;
        /*) ;;
        *) dir="$REPO_ROOT/$dir" ;;
    esac
    if have python3; then
        dir=$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$dir")
    fi
    printf '%s\n' "$dir"
}

# `create-test-env.sh` may fall back to a prefix under the checkout when
# conda's envs directory is read-only; `conda run -n` would then fail silently.
# Resolve the environment the same way the create script chose it.
test_env_run() {
    if [ -n "${PAPER_REFINE_TEST_PREFIX:-}" ]; then
        conda run -p "${PAPER_REFINE_TEST_PREFIX}" "$@"
    elif conda run -n "$ENV_NAME" python -c 'import sys' >/dev/null 2>&1; then
        conda run -n "$ENV_NAME" "$@"
    elif [ -x "$REPO_ROOT/tmp/$ENV_NAME/bin/python" ]; then
        conda run -p "$REPO_ROOT/tmp/$ENV_NAME" "$@"
    else
        return 1
    fi
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

DEPS_DIR=$(abspath_dir "$DEPS_DIR")
# Where the MCP server trees live. `install_agent_tooling.sh` uses the same
# variable and the same default, and this script passes its value through, so
# the Zotero bridge and the two docx servers always sit in one directory.
MCP_TOOLS_DIR=$(abspath_dir "${MCP_TOOLS_DIR:-$HOME/mcp-servers}")
# The Zotero MCP service (upstream: codex-zotero-bridge). It is installed
# OUTSIDE this checkout, next to the docx servers, because both harnesses run
# it by absolute path -- and install_agent_tooling.sh writes the `zotero` MCP
# row that points at exactly this copy.
ZOTERO_BRIDGE_DIR=$(abspath_dir "${ZOTERO_BRIDGE_DIR:-$MCP_TOOLS_DIR/zotero-bridge}")
if [ "$DRY_RUN" = 0 ] && [ "$DO_EXTERNAL" = 1 ]; then
    mkdir -p -- "$DEPS_DIR"
    # The bridge's own directory is never pre-created: install_repo treats an
    # existing non-git directory as a foreign install and leaves it untouched.
    mkdir -p -- "$(dirname -- "$ZOTERO_BRIDGE_DIR")"
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

# ---- required agent-common submodule --------------------------------------
# `agent-common/` is a git submodule the pipeline imports before any stage can
# start, and a plain `git clone` leaves it empty. Initialize it here so the
# documented quick start works; when this checkout is not a git clone, name the
# command instead of failing later with the loader's missing-bundle diagnostic.
step "agent-common runtime submodule"
_agent_common_files=(
    agent-common/agent_common/model_runtime.py
    agent-common/agent_common/llm_retry.py
    agent-common/agent_common/llm_policy.json
    agent-common/agent_common/model_catalog.json
)
_agent_common_missing=0
for _f in "${_agent_common_files[@]}"; do
    [ -f "$REPO_ROOT/$_f" ] || _agent_common_missing=1
done
if [ "$_agent_common_missing" = 1 ]; then
    if [ -e "$REPO_ROOT/.git" ] && have git; then
        run git -C "$REPO_ROOT" submodule update --init --recursive || \
            fail_step "git submodule update --init --recursive failed; agent-common/ is required"
        if [ "$DRY_RUN" = 1 ]; then
            note "agent-common/ is empty; would be initialized by the submodule update"
        else
            for _f in "${_agent_common_files[@]}"; do
                [ -f "$REPO_ROOT/$_f" ] || _agent_common_missing=2
            done
            if [ "$_agent_common_missing" = 2 ]; then
                fail_step "agent-common/ is still empty after the submodule update"
            fi
        fi
    elif [ "$DRY_RUN" = 1 ]; then
        note "agent-common/ is empty and this checkout is not a git clone;"
        note "  would need: git submodule update --init --recursive"
    else
        fail_step "agent-common/ is missing and this checkout has no .git; run \`git submodule update --init --recursive\`"
    fi
else
    note "agent-common/ is present"
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
                && test_env_run python -c 'import sys' >/dev/null 2>&1; then
            note "installing the optional pyzotero-cli (`zot`) command"
            if ! run test_env_run python -m pip install \
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
    step "external Zotero checkouts"
    if ! have git; then
        fail_step "git is not on PATH; cannot clone the external checkouts"
    else
        install_repo "zotero-use" \
            "https://github.com/drguptavivek/zotero-use.git" \
            "$DEPS_DIR/zotero-use" "${ZOTERO_USE_REF:-main}" || true
        install_repo "openai-plugins" \
            "https://github.com/openai/plugins.git" \
            "$DEPS_DIR/openai-plugins" "${OPENAI_PLUGINS_REF:-main}" || true
        # The bridge is installed as a plain tree on machines where the Codex
        # plugin installer (or a previous manual install) put it there: that
        # copy is kept and configured, not shadowed by a clone into a path it
        # could not occupy.
        if [ -f "$ZOTERO_BRIDGE_DIR/scripts/zotero_mcp.py" ] \
                && [ ! -d "$ZOTERO_BRIDGE_DIR/.git" ]; then
            note "using the Zotero bridge already installed at $ZOTERO_BRIDGE_DIR"
            note "  (not a git checkout; it is not refreshed)"
            [ "$STRICT_EXTERNAL" = 1 ] && \
                fail_step "the Zotero bridge at $ZOTERO_BRIDGE_DIR is not a git checkout"
        else
            install_repo "zotero-bridge" \
                "https://github.com/GuoXin-Ink/codex-zotero-bridge.git" \
                "$ZOTERO_BRIDGE_DIR" "${ZOTERO_BRIDGE_REF:-main}" || true
            if [ -f "$ZOTERO_BRIDGE_DIR/scripts/zotero_mcp.py" ]; then
                note "Zotero bridge: $ZOTERO_BRIDGE_DIR"
            fi
        fi
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
    else
        # install_agent_tooling.sh owns the harness configuration, including the
        # `zotero` row: it is given the same MCP tools/bridge directories this
        # script installed into, and `--no-zotero-mcp` travels as
        # INSTALL_ZOTERO_MCP=0 (the tooling script's default is `auto`, so it
        # also leaves the rows alone when no bridge is installed).
        agent_env=(INSTALL_CODEX=auto INSTALL_DSH=auto
                   MCP_TOOLS_DIR="$MCP_TOOLS_DIR"
                   ZOTERO_BRIDGE_DIR="$ZOTERO_BRIDGE_DIR")
        if [ "$REGISTER_ZOTERO_MCP" = 0 ]; then
            agent_env+=(INSTALL_ZOTERO_MCP=0)
        fi
        if ! run env "${agent_env[@]}" bash "$REPO_ROOT/install_agent_tooling.sh"; then
            fail_step "install_agent_tooling.sh failed"
        fi
    fi
else
    warn "skipped agent-tooling registration (--no-agent-tooling/--no-node)"
fi

# ---- the Zotero MCP service ------------------------------------------------
# The `zotero` MCP row is NOT written here any more: install_agent_tooling.sh
# owns both harnesses' configuration, and it adds or repoints that row from the
# bridge directory this script installs into (an existing row that points at an
# older location -- $CODEX_HOME/mcp-tools, for example -- is repointed there).
# This step reports what the row will point at, so a skipped bridge is visible
# in the install log instead of only in the harness config.
step "Zotero MCP service"
bridge="$ZOTERO_BRIDGE_DIR/scripts/zotero_mcp.py"
if [ -f "$bridge" ]; then
    note "bridge:    $ZOTERO_BRIDGE_DIR"
elif [ "$DRY_RUN" = 1 ]; then
    note "would install the bridge at $ZOTERO_BRIDGE_DIR"
else
    warn "the Zotero bridge is not installed at $ZOTERO_BRIDGE_DIR; no MCP row will be written"
fi
if [ "$REGISTER_ZOTERO_MCP" = 1 ]; then
    if [ "$DO_AGENT" = 1 ]; then
        note "the 'zotero' MCP row is owned by install_agent_tooling.sh (added or repointed there)"
    else
        note "the 'zotero' MCP row was skipped with agent-tooling registration"
    fi
else
    warn "skipped the Zotero MCP registration (--no-zotero-mcp/--no-node/--no-agent-tooling)"
fi

# ---- generated, relative-path environment ---------------------------------
step "dependency environment"
if [ "$DRY_RUN" = 0 ]; then
    DEPS_REL=$(relpath "$DEPS_DIR" "$REPO_ROOT")
    {
        printf '# Generated by ./install_dependencies.sh -- do not edit.\n'
        printf '# Values are RELATIVE to the checkout root, or ABSOLUTE for a dependency\n'
        printf '# installed outside it (the Zotero bridge); source activate-deps.sh to export them.\n'
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
        # The bridge lives outside the checkout, so both values are absolute:
        # a `../../mcp-servers/...` relative form would only work while the
        # checkout keeps its place, and activate-deps.sh resolves both forms.
        if [ -d "$ZOTERO_BRIDGE_DIR" ]; then
            printf 'ZOTERO_BRIDGE_ROOT=%s\n' "$ZOTERO_BRIDGE_DIR"
            if [ -f "$ZOTERO_BRIDGE_DIR/scripts/zotero_mcp.py" ]; then
                printf 'ZOTERO_BRIDGE_MCP=%s\n' \
                    "$ZOTERO_BRIDGE_DIR/scripts/zotero_mcp.py"
            else
                printf '# ZOTERO_BRIDGE_MCP not installed (%s)\n' \
                    "$ZOTERO_BRIDGE_DIR/scripts/zotero_mcp.py"
            fi
        else
            printf '# ZOTERO_BRIDGE_ROOT not installed (%s)\n' "$ZOTERO_BRIDGE_DIR"
        fi
    } > "$REPO_ROOT/deps.env"

    cat > "$REPO_ROOT/activate-deps.sh" <<'EOF'
#!/usr/bin/env bash
# Source this file to export this checkout's dependency paths for the current shell.
# The values in deps.env are relative to this directory (absolute for a
# dependency installed outside the checkout); nothing is written into the
# checkout's source tree.
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
    note "wrote deps.env and activate-deps.sh (checkout-relative paths; absolute for the Zotero bridge)"

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

`INSTALLED.json` records the commit checked out for each repository that could be installed.

The Zotero MCP service (`codex-zotero-bridge`) is NOT stored here: it is
installed next to the docx MCP servers, at `$ZOTERO_BRIDGE_DIR` (default
`$MCP_TOOLS_DIR/zotero-bridge`, i.e. `~/mcp-servers/zotero-bridge`), and
`install_agent_tooling.sh` points every harness's `zotero` MCP row at that copy.
`deps.env` records its `$ZOTERO_BRIDGE_ROOT` and `$ZOTERO_BRIDGE_MCP` values as
absolute paths.

The Zotero MCP service is registered with each harness when a harness is
present. It still needs the Zotero Desktop extension: in Zotero choose
**Tools > Codex Zotero Bridge > Pair Codex**, then call the `zotero_pair` MCP
tool with the one-time 8-digit code. Until it is paired, the stage prompts use
the `zot` CLI first and fall back to the Zotero skill when the MCP service
cannot answer, exactly as they document.
EOF
    fi
fi

# ---- summary ---------------------------------------------------------------
step "summary"
note "checkout:  $REPO_ROOT"
note "deps:      ${DEPS_DIR#"$REPO_ROOT"/}"
note "mcp tools: ${MCP_TOOLS_DIR/#$HOME/\~} (docx servers and the Zotero bridge)"
if [ "$DO_CONDA" = 1 ]; then
    note "conda env: $ENV_NAME (activate with: conda activate $ENV_NAME)"
else
    note "conda env: skipped (--no-conda)"
fi
if [ "$DRY_RUN" = 1 ]; then
    note "shell env: would write ./deps.env and ./activate-deps.sh (dry run; do not source them yet)"
else
    note "shell env: source ./activate-deps.sh"
fi
note "data:      the shipped venue profiles are local; venue exemplars are fetched per run by"
note "           'add-venue' and are not a global dependency"
if [ "$DRY_RUN" = 1 ]; then
    note "run:       (after a real install) python paper_pipeline.py setup --source <manuscript-dir> --root <run-root>"
else
    note "run:       python paper_pipeline.py setup --source <manuscript-dir> --root <run-root>"
fi
note "Zotero:    \`zot\` CLI first, Zotero MCP service second, Zotero skill fallback;"
note "           if all three are unavailable, the stage records manual verification."
if [ "${#FAILED[@]}" -gt 0 ]; then
    printf '\n[install] incomplete:\n' >&2
    for item in "${FAILED[@]}"; do printf '  - %s\n' "$item" >&2; done
    exit 1
fi
note "install complete"

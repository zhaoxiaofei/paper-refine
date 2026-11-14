#!/usr/bin/env bash
# Install this checkout's two skills, its two MCP docx servers, and -- when the
# Zotero bridge is installed -- the `zotero` MCP row into every agent harness
# present on this machine:
#
#   * Codex ($CODEX_HOME, default ~/.codex): the versioned paper-skills-*
#     package and one [mcp_servers.<name>] entry per server. The entries
#     point at the server trees, which live OUTSIDE $CODEX_HOME (in
#     $MCP_TOOLS_DIR, default ~/mcp-servers): .codex is the harness's
#     configuration directory (config.toml, skill discovery), not an
#     installation root for server code.
#   * DeepSeek Harness ($DSH_HOME, default ~/.dsh): both skills in its flat
#     skills directory (one copy per frontmatter `name`), and the same two
#     servers in EVERY profile's cordis.patch.yml.
#
# The `zotero` row is conditional and is REPOINTED, not merely added:
# install_dependencies.sh installs the Zotero bridge (upstream:
# codex-zotero-bridge) at $ZOTERO_BRIDGE_DIR, default
# $MCP_TOOLS_DIR/zotero-bridge, and this script makes both harnesses run that
# copy. An entry that points at an older install location -- the legacy
# $CODEX_HOME/mcp-tools tree, for example -- is what "stale" means below, so a
# bridge that moved is picked up instead of silently left behind. When the
# bridge is absent, every existing zotero row is left exactly as it is;
# INSTALL_ZOTERO_MCP=0 skips the row, INSTALL_ZOTERO_MCP=1 forces it (and is
# an error when the bridge or python3 is missing).
#
# Each side is installed NATIVELY from this checkout. Nothing is ported from
# Codex to dsh (or back): the dsh rows name this script's own servers and
# paths and are written from this checkout's list, never from Codex's config.
# Porting -- importing one harness's configuration into the other -- is the
# fallback for an item that cannot be installed natively, and no item this
# script installs falls in that class (the repo's `scripts/install-codex-mcp.mjs`
# keeps that importer for operators who want it).
#
# A half runs only when its harness is present. The Codex half needs the
# `codex` CLI on PATH, because its registration is `codex mcp add`; the dsh half
# runs on the harness home or either CLI, and installs the MCP rows only when
# the `dsh` CLI is there (without it the skills are still installed).
# INSTALL_CODEX=1/0 and INSTALL_DSH=1/0 force or skip a half. A skipped half is
# reported, never silently dropped.
#
# Every failure is fatal (no `|| true`): a silent failure here leaves stale
# versions installed or destroys the expected backup layout without a word.
#
# The whole installation is STAGED before anything live is touched: the skills
# pack, both MCP server trees and both companion scripts are built and checked
# in temporary paths first, and only then switched in. A failed `npm ci` for the
# second server therefore leaves the previous installation intact instead of a
# mixed skills/new-converter/old-comparer tree (F-094). Harness registrations
# (Codex config, dsh profile rows) happen LAST, against the freshly switched-in
# trees, and each one is verified before it is accepted.
#
# A dsh profile's managed MCP block is reconciled before its row writer runs:
# an entry an operator pasted between the markers makes the writer refuse to
# --merge (it would silently drop that entry), which used to abort the install
# after the switch-in. The installer moves such entries back outside the
# markers, with a backup, instead of failing; see repair_dsh_managed_block.
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# Absolute, normalized path for a directory (created when absent), expanding a
# leading `~`. Every path this script writes into a CONFIG must be absolute: a
# harness spawns its MCP servers from its own cwd, so a relative
# MCP_TOOLS_DIR/CODEX_HOME would register a path that resolves only from the
# shell that ran this installer.
resolve_dir() {
    local dir=$1
    case "$dir" in
        "~") dir="$HOME" ;;
        "~/"*) dir="$HOME/${dir#\~/}" ;;
    esac
    mkdir -p -- "$dir" || {
        echo "error: could not create directory: $dir" >&2
        return 1
    }
    (cd -- "$dir" && pwd -P)
}

# Absolute, normalized path for a file (typically an executable found on PATH).
resolve_file() {
    local file=$1 dir
    case "$file" in
        */*)
            dir=$(cd -- "$(dirname -- "$file")" && pwd -P) || return 1
            printf '%s/%s\n' "$dir" "$(basename -- "$file")"
            ;;
        *)
            command -v -- "$file"
            ;;
    esac
}

codex_home="${CODEX_HOME:-$HOME/.codex}"
skills_dir="$codex_home/skills"
backup_dir="$codex_home/backup"
# Where the MCP server trees are deployed. The docx servers are private servers
# shipped by this checkout, not published packages, so the recommended shape is
# a dedicated directory OUTSIDE the harness configuration directory, referenced
# by absolute path from each config: $MCP_TOOLS_DIR, default ~/mcp-servers.
# `.codex` is a configuration hub; installing server code (and its node_modules)
# under it mixes the two concerns, clutters config backups and makes the config
# less portable. BOTH harnesses run this copy -- the dsh rows name it
# explicitly. The Zotero bridge that install_dependencies.sh installs lands in
# the same directory (see $ZOTERO_BRIDGE_DIR below). Older versions of this
# script defaulted to $CODEX_HOME/mcp-tools; a successful install moves that
# legacy tree out (see the migration at the end of this script).
tools_dir="${MCP_TOOLS_DIR:-$HOME/mcp-servers}"

# Where the DeepSeek Harness discovers skills: $DSH_HOME/skills (default
# ~/.dsh/skills), the same directory `dshx skill add` writes to. dsh ALSO reads
# <project>/.dsh/skills and ~/.agents/skills, with higher precedence; installing
# there too would leave two copies of the same frontmatter `name` competing, so
# this script owns exactly one copy per skill.
dsh_home="${DSH_HOME:-$HOME/.dsh}"
dsh_skills_dir="$dsh_home/skills"
dsh_backup_dir="$dsh_home/backup"

dsh_cli=""
if command -v dsh >/dev/null 2>&1; then dsh_cli=$(command -v dsh); fi
node_bin=""
if command -v node >/dev/null 2>&1; then node_bin=$(command -v node); fi
# Only the Zotero row needs Python. The two docx servers do not, so a machine
# without python3 still gets the whole docx installation; the zotero row is
# skipped (or is an error when INSTALL_ZOTERO_MCP=1) further down.
python_bin=""
if command -v python3 >/dev/null 2>&1; then python_bin=$(command -v python3); fi

# ---- decide which halves run ----------------------------------------------
# Codex: "available" means its CLI is on PATH, because the MCP registration
# below is done through `codex mcp add` (a directory without the CLI is not a
# usable install).
install_codex="${INSTALL_CODEX:-auto}"
codex_enabled=0
case "$install_codex" in
    auto)
        if command -v codex >/dev/null 2>&1; then codex_enabled=1; fi
        ;;
    1|yes|true|on) codex_enabled=1 ;;
    0|no|false|off) codex_enabled=0 ;;
    *)
        echo "error: INSTALL_CODEX=$install_codex is not one of auto, 1 (force), 0 (skip)" >&2
        exit 2
        ;;
esac

# dsh: the harness may be present before its CLI is, so detection accepts its
# home directory too; the MCP wiring below is skipped (with a note) if the CLI
# itself is missing. `auto` therefore needs evidence of a harness.
install_dsh="${INSTALL_DSH:-auto}"
dsh_enabled=0
case "$install_dsh" in
    auto)
        if [ -n "${DSH_HOME:-}" ] || [ -d "$dsh_home" ] \
            || command -v dsh >/dev/null 2>&1 || command -v dshx >/dev/null 2>&1; then
            dsh_enabled=1
        fi
        ;;
    1|yes|true|on) dsh_enabled=1 ;;
    0|no|false|off) dsh_enabled=0 ;;
    *)
        echo "error: INSTALL_DSH=$install_dsh is not one of auto, 1 (force), 0 (skip)" >&2
        exit 2
        ;;
esac

if [ "$codex_enabled" = 0 ] && [ "$dsh_enabled" = 0 ]; then
    echo "error: nothing to install -- neither the codex CLI nor a DeepSeek Harness was found" >&2
    echo "       (set INSTALL_CODEX=1 and/or INSTALL_DSH=1 to force a half on)" >&2
    exit 1
fi

if [ "$codex_enabled" = 1 ] && ! command -v codex >/dev/null 2>&1; then
    echo "error: INSTALL_CODEX=1 but the codex CLI is not on PATH; its MCP entries are written with codex mcp add" >&2
    exit 1
fi

if [ -z "$node_bin" ]; then
    echo "error: node was not found on PATH; the shipped MCP servers need Node >= 20" >&2
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "error: npm was not found on PATH; the shipped MCP servers install with npm ci" >&2
    exit 1
fi
# The MCP servers and the importer this script runs need Node >= 20. Checking
# only that `node` exists let an old interpreter through; the run then switched
# the live skills/servers in and died with a JavaScript SyntaxError afterwards.
node_major=$("$node_bin" -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)
case "$node_major" in
    ''|*[!0-9]*)
        echo "error: could not determine the node version from $node_bin; the shipped MCP servers need Node >= 20" >&2
        exit 1
        ;;
esac
if [ "$node_major" -lt 20 ]; then
    echo "error: node $("$node_bin" -v 2>/dev/null) is too old ($node_bin); the shipped MCP servers need Node >= 20" >&2
    exit 1
fi

# ---- normalize the paths that end up in configs ----------------------------
codex_home=$(resolve_dir "$codex_home")
skills_dir="$codex_home/skills"
backup_dir="$codex_home/backup"
tools_dir=$(resolve_dir "$tools_dir")
# Expand a leading `~` in DSH_HOME even when the dsh half is skipped: the
# legacy-install migration at the end reads the profiles to decide whether a
# registration still points at server code it must not move.
case "$dsh_home" in
    "~") dsh_home="$HOME" ;;
    "~/"*) dsh_home="$HOME/${dsh_home#\~/}" ;;
esac
# The pre-recommendation install root: server code used to be installed inside
# the Codex configuration directory. Kept so a completed install can move this
# script's own trees out of it (see the migration at the end).
legacy_tools_dir="$codex_home/mcp-tools"
case "$tools_dir/" in
    "$codex_home"/*)
        echo "warning: MCP_TOOLS_DIR ($tools_dir) is inside the Codex configuration directory" >&2
        echo "         ($codex_home); a directory of its own, outside it, is recommended" >&2
        ;;
esac
if [ "$dsh_enabled" = 1 ]; then
    dsh_home=$(resolve_dir "$dsh_home")
    dsh_skills_dir="$dsh_home/skills"
    dsh_backup_dir="$dsh_home/backup"
fi
node_bin=$(resolve_file "$node_bin")
if [ -n "$python_bin" ]; then
    python_bin=$(resolve_file "$python_bin")
fi

# ---- the Zotero MCP row (conditional) --------------------------------------
# install_dependencies.sh installs the Zotero bridge (upstream:
# codex-zotero-bridge) at $ZOTERO_BRIDGE_DIR, default
# $MCP_TOOLS_DIR/zotero-bridge, next to the docx servers, and passes its value
# through here. This directory is NEVER created by this script: an empty
# pre-created destination is a non-git directory, which install_dependencies
# reports as a foreign install and refuses to clone over -- creating it would
# break the very install it is meant to configure. The row is written only when
# the bridge's server script is already there; an INSTALL_ZOTERO_MCP=1 that
# names a missing bridge is an error instead of a silent no-op.
zotero_bridge_dir="${ZOTERO_BRIDGE_DIR:-$tools_dir/zotero-bridge}"
case "$zotero_bridge_dir" in
    "~") zotero_bridge_dir="$HOME" ;;
    "~/"*) zotero_bridge_dir="$HOME/${zotero_bridge_dir#\~/}" ;;
esac
zotero_bridge_script="$zotero_bridge_dir/scripts/zotero_mcp.py"
install_zotero="${INSTALL_ZOTERO_MCP:-auto}"
zotero_enabled=0
case "$install_zotero" in
    auto)
        if [ -f "$zotero_bridge_script" ]; then
            if [ -n "$python_bin" ]; then
                zotero_enabled=1
            else
                echo "warning: the Zotero bridge needs python3, which is not on PATH;" >&2
                echo "         leaving the zotero MCP rows unchanged" >&2
            fi
        else
            echo "no Zotero bridge at $zotero_bridge_script; leaving the zotero MCP rows unchanged"
            echo "  (install_dependencies.sh installs it; INSTALL_ZOTERO_MCP=1 forces a row)"
        fi
        ;;
    1|yes|true|on) zotero_enabled=1 ;;
    0|no|false|off) zotero_enabled=0 ;;
    *)
        echo "error: INSTALL_ZOTERO_MCP=$install_zotero is not one of auto, 1 (force), 0 (skip)" >&2
        exit 2
        ;;
esac
if [ "$zotero_enabled" = 1 ]; then
    # Forced (`INSTALL_ZOTERO_MCP=1`) or auto-detected: either way the row is
    # written only against a bridge and an interpreter that exist, so a forced
    # row cannot register a command that fails on every start.
    if [ ! -f "$zotero_bridge_script" ]; then
        echo "error: INSTALL_ZOTERO_MCP=1 but the Zotero bridge is not installed at $zotero_bridge_script" >&2
        echo "       (run ./install_dependencies.sh, or set ZOTERO_BRIDGE_DIR)" >&2
        exit 1
    fi
    if [ -z "$python_bin" ]; then
        echo "error: the Zotero bridge needs python3, and it was not found on PATH" >&2
        exit 1
    fi
    zotero_bridge_dir=$(resolve_dir "$zotero_bridge_dir")
    zotero_bridge_script="$zotero_bridge_dir/scripts/zotero_mcp.py"
elif [ "$install_zotero" != auto ]; then
    echo "skipped the Zotero MCP row: INSTALL_ZOTERO_MCP=$install_zotero"
fi

# ---- the MCP rows this installer owns --------------------------------------
# One list for both harnesses: the Codex entries and the dsh rows are written
# from the same names, commands and scripts, so a harness can never be pointed
# at a tree the other one does not use. `install_dependencies.sh` installs the
# docx servers and the Zotero bridge; this script only registers them.
mcp_row_names=(docx-compare docx-converter)
mcp_row_commands=("$node_bin" "$node_bin")
mcp_row_scripts=(
    "$tools_dir/mcp-docx-compare/index.js"
    "$tools_dir/mcp-docx-converter/index.js"
)
if [ "$zotero_enabled" = 1 ]; then
    mcp_row_names+=(zotero)
    mcp_row_commands+=("$python_bin")
    mcp_row_scripts+=("$zotero_bridge_script")
fi
# Set once a harness row for the bridge has actually been written (or confirmed
# current): the pairing note at the end is only useful when there is a row.
zotero_rows=0

if [ "$codex_enabled" = 1 ]; then
    mkdir -p -- "$skills_dir" "$backup_dir"
fi

# The commit suffix is informational: outside a git checkout (or in a shallow
# deployment) fall back to a literal so the installed name still identifies the
# install instead of ending in a bare "-".
commit=$(git -C "$repo_dir" rev-parse HEAD 2>/dev/null | head -n 1 | head -c 7) || commit=""
commit=${commit:-nogit}

new_version="$(date +'%Y-%m%d')-$commit"

# Print one top-level key of a SKILL.md's YAML frontmatter (its first --- block).
# dsh reads `name` and `description` from exactly there; a copy whose frontmatter
# is broken is installed but never loaded, which is the silent failure this
# script refuses to ship.
frontmatter_value() {
    awk -v key="$2" '
        NR == 1 && $0 == "---" { inside = 1; next }
        inside && $0 == "---" { exit }
        inside && substr($0, 1, length(key) + 1) == key ":" {
            sub("^" key ":[[:space:]]*", "")
            print
            exit
        }
    ' "$1"
}

stage_skills=""
stage_tools=()
stage_companions=()
stage_dsh=""
servers_json=""
cleanup() {
    rc=$?
    [ -n "$stage_skills" ] && rm -rf -- "$stage_skills"
    for s in "${stage_tools[@]:-}"; do
        [ -n "$s" ] && rm -rf -- "$s"
    done
    for s in "${stage_companions[@]:-}"; do
        [ -n "$s" ] && rm -f -- "$s"
    done
    [ -n "$stage_dsh" ] && rm -rf -- "$stage_dsh"
    [ -n "$servers_json" ] && rm -f -- "$servers_json"
    exit "$rc"
}
trap cleanup EXIT

# ---- stage the Codex skills pack -------------------------------------------
if [ "$codex_enabled" = 1 ]; then
    stage_skills="$skills_dir/.paper-skills-stage.$$"
    rm -rf -- "$stage_skills"
    cp -r -- "$repo_dir/paper-skills" "$stage_skills"
    [ -d "$stage_skills" ]
fi

# ---- stage the dsh skills --------------------------------------------------
# dsh registers a skill by its frontmatter `name` in a FLAT directory, so unlike
# the versioned Codex package there is no name to keep two generations apart:
# installing REPLACES $DSH_HOME/skills/<name>. Two consequences drive this
# block. (1) The previous copy is moved to $DSH_HOME/backup/ before it is
# replaced -- the copy users configure is the INSTALLED one (its ZOTERO_SKILL
# line), and overwriting it without a backup loses that edit silently. (2) The
# staged copy carries a `.dshx.json` provenance record, so `dshx skill update
# <name>` refreshes from THIS checkout instead of having nothing to re-fetch.
# Staging stays outside the skills directory: dsh hot-watches that directory,
# so a half-copied tree must never appear inside it.
if [ "$dsh_enabled" = 1 ]; then
    stage_dsh="$dsh_home/.paper-skills-stage.$$"
    rm -rf -- "$stage_dsh"
    mkdir -p -- "$stage_dsh"
    for name in paper-review paper-revise; do
        src="$repo_dir/paper-skills/$name"
        [ -f "$src/SKILL.md" ] || {
            echo "error: $src/SKILL.md is missing; refusing to install a skill dsh cannot load" >&2
            exit 1
        }
        declared=$(frontmatter_value "$src/SKILL.md" name)
        [ "$declared" = "$name" ] || {
            echo "error: $src/SKILL.md declares name '${declared}', not '$name' (dsh would expose it under the declared name)" >&2
            exit 1
        }
        [ -n "$(frontmatter_value "$src/SKILL.md" description)" ] || {
            echo "error: $src/SKILL.md has no description; dsh refuses to load such a skill" >&2
            exit 1
        }
        cp -r -- "$src" "$stage_dsh/$name"
        printf '{\n  "source": "local:%s",\n  "version": "%s",\n  "installedAt": "%s"\n}\n' \
            "$src" "$new_version" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            > "$stage_dsh/$name/.dshx.json"
    done
fi

# ---- stage both MCP servers and their companion scripts --------------------
# Deployed once and run by BOTH harnesses: the Codex entries name these paths,
# and so do the dsh rows the last section writes.
tool_names=()
tool_paths=()
companions=()
for docx_tool in converter compare; do
    tool_name="mcp-docx-${docx_tool}"
    tool_path="${tools_dir}/${tool_name}"
    case "$docx_tool" in
        compare) companion="docxcompare.sh" ;;
        converter) companion="docx2pdf.sh" ;;
    esac
    # Stage the SOURCE only and run npm ci THERE: removing a live install first
    # would break a working server when the install fails. `node_modules/` is
    # never vendored (copying it over a Windows mount is slow, and a stale copy
    # fails silently).
    staging="${tool_path}.stage.$$"
    # Register the staging tree BEFORE populating it: a failing tar/npm ci in
    # this window used to leave the half-built tree behind, because the EXIT
    # trap only removes the paths already in stage_tools.
    stage_tools+=("$staging")
    rm -rf -- "$staging"
    mkdir -p -- "$staging"
    (cd -- "$repo_dir/${tool_name}" && tar cf - --exclude=./node_modules .) | (cd -- "$staging" && tar xf -)
    npm ci --prefix "$staging" --no-audit --no-fund
    companion_stage="${tools_dir}/.${companion}.stage.$$"
    stage_companions+=("$companion_stage")
    install -m 0755 -- "$repo_dir/$companion" "$companion_stage"
    tool_names+=("$tool_name")
    tool_paths+=("$tool_path")
    companions+=("$companion")
    echo "staged mcp-tool: ${tool_path}"
done

# ---- switch the complete installation in ------------------------------------
if [ "$codex_enabled" = 1 ]; then
    shopt -s nullglob
    previous=("$skills_dir"/paper-skills-*)
    shopt -u nullglob
    for p in "${previous[@]}"; do
        case "$(basename -- "$p")" in
            .paper-skills-stage.*) continue ;;
        esac
        name=$(basename -- "$p")
        target="$backup_dir/$name"
        if [ -e "$target" ]; then
            # A same-second re-run (or a pre-existing backup) must not make `mv`
            # move the package INSIDE an existing directory: find a free name.
            stamp="$(date +%Y%m%d%H%M%S)"
            target="$backup_dir/$name.$stamp"
            suffix=0
            while [ -e "$target" ]; do
                suffix=$((suffix + 1))
                target="$backup_dir/$name.$stamp.$suffix"
            done
        fi
        mv -- "$p" "$target"
        echo "backed up: $p -> $target"
    done

    dest="$skills_dir/paper-skills-${new_version}"
    mv -- "$stage_skills" "$dest"
    stage_skills=""
    echo "installed skill: $dest"
fi

for i in "${!tool_names[@]}"; do
    tool_path="${tool_paths[$i]}"
    staging="${stage_tools[$i]}"
    companion_stage="${stage_companions[$i]}"
    companion="${companions[$i]}"
    # Keep the old tree until the staged tree is in place.
    old_path="${tool_path}.old.$$"
    if [ -e "$tool_path" ]; then
        mv -- "$tool_path" "$old_path"
    fi
    if ! mv -- "$staging" "$tool_path"; then
        # A failed switch-in must not leave the server absent: `set -e` used to
        # exit here with the live path gone, the only copy at the .old.$$ name
        # and the cleanup trap removing just the staged tree -- a broken install
        # destroying the working one it replaced.
        if [ -e "$old_path" ]; then
            if mv -- "$old_path" "$tool_path"; then
                echo "restored the previous mcp-tool after the failed switch-in: ${tool_path}" >&2
            else
                echo "error: could not restore ${tool_path}; the previous install is at ${old_path}" >&2
            fi
        fi
        exit 1
    fi
    rm -rf -- "$old_path"
    rm -rf -- "${tool_path}-${new_version}"
    cp -r -- "$tool_path" "${tool_path}-${new_version}"
    echo "installed mcp-tool: ${tool_path}"
    # Both node servers answer initialize() and then fail EVERY tool call with
    # `spawn <script> ENOENT` when the shell script they drive is not where
    # they resolve it: ../<script>, then ./<script>, then PATH.
    mv -f -- "$companion_stage" "$(dirname -- "$tool_path")/$companion"
    echo "installed companion: $(dirname -- "$tool_path")/$companion"
    stage_tools[$i]=""
    stage_companions[$i]=""
done

# ---- register the MCP rows with Codex --------------------------------------
# `codex mcp add` is the CLI's own native registration. It rewrites the whole
# [mcp_servers.<name>] table, so it is only run when the entry is missing or
# points somewhere else: a correct entry keeps whatever else the operator set
# on it (approval policy, timeouts).
codex_mcp_state() {
    CODEX_HOME="$codex_home" codex mcp list --json | "$node_bin" -e '
        let text = "";
        process.stdin.on("data", (chunk) => (text += chunk));
        process.stdin.on("end", () => {
            const [name, command, script] = process.argv.slice(1);
            let list;
            try {
                list = JSON.parse(text);
            } catch {
                console.log("unreadable");
                return;
            }
            const row = (Array.isArray(list) ? list : []).find((item) => item && item.name === name);
            if (!row) {
                console.log("missing");
                return;
            }
            const transport = row.transport || {};
            const ok = row.enabled !== false
                && transport.command === command
                && Array.isArray(transport.args)
                && transport.args.length === 1
                && transport.args[0] === script;
            console.log(ok ? "ok" : "stale");
        });
    ' "$1" "$2" "$3"
}

if [ "$codex_enabled" = 1 ]; then
    codex_config_backed_up=0
    # `codex mcp remove`/`add` rewrite ~/.codex/config.toml in place; the
    # install's staging guarantees do not cover a write the CLI makes itself, so
    # keep one copy before the first change (lazily: a run that only reports the
    # entries current touches nothing).
    backup_codex_config() {
        [ "$codex_config_backed_up" = 1 ] && return 0
        codex_config_backed_up=1
        [ -f "$codex_home/config.toml" ] || return 0
        local stamp target suffix
        stamp="$(date +%Y%m%d%H%M%S)"
        target="$backup_dir/config.toml.$stamp"
        suffix=0
        while [ -e "$target" ]; do
            suffix=$((suffix + 1))
            target="$backup_dir/config.toml.$stamp.$suffix"
        done
        cp -p -- "$codex_home/config.toml" "$target"
        echo "backed up: $codex_home/config.toml -> $target"
    }

    for i in "${!mcp_row_names[@]}"; do
        name="${mcp_row_names[$i]}"
        command="${mcp_row_commands[$i]}"
        script="${mcp_row_scripts[$i]}"
        # With `set -euo pipefail`, `codex mcp list` exiting non-zero failed
        # the assignment before the error branch ran; keep the state readable so
        # the `*` branch below can diagnose it.
        state=$(codex_mcp_state "$name" "$command" "$script" || printf 'unreadable\n')
        case "$state" in
            ok)
                echo "codex MCP server already current: $name -> $script"
                ;;
            missing)
                backup_codex_config
                CODEX_HOME="$codex_home" codex mcp add "$name" -- "$command" "$script"
                echo "registered codex MCP server: $name -> $script"
                ;;
            stale)
                # The entry runs a copy this install replaced, or an older
                # install location (the bridge that used to live under
                # $CODEX_HOME/mcp-tools): replace the entry.
                backup_codex_config
                CODEX_HOME="$codex_home" codex mcp remove "$name" >/dev/null
                CODEX_HOME="$codex_home" codex mcp add "$name" -- "$command" "$script"
                echo "repointed codex MCP server: $name -> $script"
                ;;
            *)
                echo "error: could not read the codex MCP configuration (state: $state)" >&2
                exit 1
                ;;
        esac
        state=$(codex_mcp_state "$name" "$command" "$script" || printf 'unreadable\n')
        [ "$state" = ok ] || {
            echo "error: codex still does not report $name -> $script after writing it (state: $state)" >&2
            exit 1
        }
        if [ "$name" = zotero ]; then zotero_rows=1; fi
    done
else
    if [ "$install_codex" = auto ]; then
        echo "skipped the codex half: the codex CLI is not on PATH (set INSTALL_CODEX=1 to force it)"
    else
        echo "skipped the codex half: INSTALL_CODEX=0"
    fi
fi

# ---- switch the dsh skills in ----------------------------------------------
# After every other staged tree has been built: a failure above never touches
# the harness's live skills. `dshx` reads `.dshx.json` on `list`/`update` and
# the harness hot-reloads the directory, so no restart is involved.
if [ "$dsh_enabled" = 1 ]; then
    mkdir -p -- "$dsh_skills_dir" "$dsh_backup_dir"
    for name in paper-review paper-revise; do
        staged="$stage_dsh/$name"
        dest="$dsh_skills_dir/$name"
        previous_dsh=""
        if [ -e "$dest" ] || [ -L "$dest" ]; then
            stamp="$(date +%Y%m%d%H%M%S)"
            previous_dsh="$dsh_backup_dir/$name.$stamp"
            suffix=0
            while [ -e "$previous_dsh" ]; do
                suffix=$((suffix + 1))
                previous_dsh="$dsh_backup_dir/$name.$stamp.$suffix"
            done
            mv -- "$dest" "$previous_dsh"
            echo "backed up: $dest -> $previous_dsh"
        fi
        if ! mv -- "$staged" "$dest"; then
            # Same rule as the mcp-tool switch-in: a failed switch must not
            # leave the skill absent when the previous copy is right there.
            if [ -n "$previous_dsh" ]; then
                if mv -- "$previous_dsh" "$dest"; then
                    echo "restored the previous dsh skill after the failed switch-in: ${dest}" >&2
                else
                    echo "error: could not restore ${dest}; the previous copy is at ${previous_dsh}" >&2
                fi
            fi
            exit 1
        fi
        echo "installed skill: $dest"
    done
    rm -rf -- "$stage_dsh"
    stage_dsh=""
    echo "dsh hot-reloads its skills directory; no restart needed."
fi

# ---- reconcile each dsh profile's managed block ----------------------------
# The row writer owns everything between its two markers and rewrites it on
# every run: `--merge` re-reads the block as its own rows (a 4-space `- id:`
# row carrying an 8-space `serverName:`) and REFUSES the whole merge when the
# block holds anything else, because rewriting it would silently drop that
# content. That guard is correct, but the block is a comment-delimited region
# in a file operators edit, so an entry pasted in before the closing marker
# makes the writer refuse and the install abort half-finished. The headless
# profile in debug run 261111-195659 was exactly that: a top-level
# `- id: llm-pi-ai` patch entry (and its nested model row) sat inside the
# markers, so the writer counted 5 `- id:` rows but could read only 3 rows of
# its own and exited 1 after the skills and tools had already been switched in.
#
# The installer therefore reconciles every block BEFORE the writer sees it:
# only the writer's own rows stay between the markers. Everything else the
# writer would drop is preserved byte for byte outside the markers, in place
# or as its own top-level entry: another top-level entry, an insert item with
# no serverName (kept under its own `- insert:` entry), a commented-out entry,
# or comment lines that sat before the rows. Nothing is edited, re-indented,
# renamed or deleted; the file is backed up and written atomically first. A
# block that cannot be reconciled without guessing (a serverName row at a
# drifted indentation, a duplicate serverName, an unclosed block, several
# blocks) is refused with a message and left untouched, never silently
# trimmed. A clean profile stays byte-identical, so a re-run is a no-op.
repair_dsh_managed_block() {
    local patch_file=$1
    "$node_bin" -e '
        const fs = require("fs");
        const path = require("path");
        const crypto = require("crypto");

        const BEGIN = "# >>> codex-mcp-import (managed block; regenerate with install-codex-mcp.mjs) >>>";
        const END = "# <<< codex-mcp-import <<<";
        const patchFile = process.argv[1];

        function fail(message) {
            process.stderr.write(`install_agent_tooling: ${patchFile}: ${message}\n`);
            process.exit(3);
        }

        function note(message) {
            process.stdout.write(`install_agent_tooling: ${patchFile}: ${message}\n`);
        }

        let stat;
        try {
            stat = fs.lstatSync(patchFile);
        } catch (error) {
            fail(`cannot read it (${error.code || error.message})`);
        }
        if (stat.isSymbolicLink()) fail("is a symlink; refusing to rewrite it");

        const text = fs.readFileSync(patchFile, "utf8");
        const blocks = text.split(BEGIN).length - 1;
        if (blocks === 0) {
            note("no managed block; the row writer will add one");
            process.exit(0);
        }
        if (blocks > 1) {
            fail(`carries ${blocks} managed blocks; --merge reads only the first and would drop the rest (restore it from a backup first)`);
        }
        const begin = text.indexOf(BEGIN);
        const end = text.indexOf(END);
        if (end < begin) {
            fail("the managed block opens but has no closing marker (restore it from a backup first)");
        }

        const head = text.slice(0, begin);
        const body = text.slice(begin + BEGIN.length, end);
        const tail = text.slice(end + END.length);
        if (body.trim() === "") {
            note("managed block is empty; the row writer will fill it");
            process.exit(0);
        }

        const lines = body.split("\n");
        const isTopLevel = (line) => /^-(?:[ \t]|$)/.test(line);
        const isWriterRow = (line) => /^ {4}- id: /.test(line);

        // A managed block is a sequence of TOP-LEVEL YAML entries. The writer emits
        // exactly one `- insert:` entry whose items are 4-space rows carrying an
        // 8-space serverName; anything else in the block is content the writer would
        // drop, so it is preserved outside the markers instead of being rewritten.
        const pre = [];
        const sections = [];
        let section = null;
        for (const line of lines) {
            if (isTopLevel(line)) {
                section = { lines: [line], items: [] };
                sections.push(section);
            } else if (section) {
                section.lines.push(line);
            } else {
                pre.push(line);
            }
        }

        const writerSections = [];
        for (const candidate of sections) {
            if (!/^- insert:\s*$/.test(candidate.lines[0])) continue;
            const between = [];
            let item = null;
            for (const line of candidate.lines.slice(1)) {
                if (isWriterRow(line)) {
                    item = [line];
                    candidate.items.push(item);
                } else if (item) {
                    item.push(line);
                } else {
                    between.push(line);
                }
            }
            candidate.between = between;
            if (candidate.items.length === 0) {
                if (/^\s*serverName: /m.test(candidate.lines.join("\n"))) {
                    fail("an \"- insert:\" list inside the managed block carries a serverName row that is not at the writer indentation (4 spaces before \"- id:\", 8 before \"serverName:\"); normalising it would guess the row shape, so it is left untouched (fix the indentation or move the list out of the markers and re-run)");
                }
                continue;
            }
            // The writer re-emits only 4-space "- id:" items carrying an 8-space
            // serverName. Every other item in the list is content it would drop, so
            // it is preserved verbatim as its own "- insert:" entry outside the
            // markers; an item that does carry a serverName at another indentation is
            // refused, because registering it beside the managed rows could duplicate
            // a server.
            const named = [];
            const stray = [];
            for (const linesOfItem of candidate.items) {
                if (linesOfItem.some((line) => /^ {8}serverName: /.test(line))) {
                    named.push(linesOfItem);
                } else if (linesOfItem.some((line) => /^\s*serverName:\s*/.test(line))) {
                    fail("an \"- insert:\" item inside the managed block carries a serverName at the wrong indentation; the writer would not manage it and registering it beside the managed row could duplicate a server, so it is left untouched (fix the indentation or move the item out of the markers and re-run)");
                } else {
                    stray.push(linesOfItem);
                }
            }
            if (named.length === 0) continue;   // an insert list with no MCP row is operator content: move it out verbatim
            candidate.items = named;
            candidate.strayItems = stray;
            writerSections.push(candidate);
        }
        if (writerSections.length > 1) {
            fail(`the managed block carries ${writerSections.length} "- insert:" lists of MCP rows; only one can be the writer block, and rewriting either would register the rows twice (move all but one out of the markers first)`);
        }

        const stripBlankEdges = (chunk) => {
            const out = chunk.slice();
            while (out.length > 0 && out[out.length - 1].trim() === "") out.pop();
            while (out.length > 0 && out[0].trim() === "") out.shift();
            return out;
        };

        const writeBackup = () => {
            try {
                const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").replace("Z", "");
                let target = `${patchFile}.bak-install-agent-tooling-${stamp}`;
                let suffix = 2;
                while (fs.existsSync(target)) target = `${patchFile}.bak-install-agent-tooling-${stamp}-${suffix++}`;
                fs.writeFileSync(target, text, { mode: 0o600 });
                return target;
            } catch (error) {
                fail(`could not back it up before the repair (${error.message || error.code}); the file is untouched`);
            }
        };

        const writeAtomic = (next) => {
            const dir = path.dirname(patchFile);
            const base = path.basename(patchFile);
            let tmp = null;
            try {
                for (let attempt = 0; attempt < 20; attempt += 1) {
                    tmp = path.join(dir, `.${base}.repair-${process.pid}-${crypto.randomBytes(6).toString("hex")}`);
                    try {
                        fs.writeFileSync(tmp, next, { flag: "wx", mode: 0o600 });
                        break;
                    } catch (error) {
                        tmp = null;
                        if (error.code !== "EEXIST") throw error;
                    }
                }
                if (!tmp) throw new Error("could not create a unique temporary beside the patch file");
                try { fs.chmodSync(tmp, stat.mode & 0o777); } catch { /* keep 0600 */ }
                fs.renameSync(tmp, patchFile);
                tmp = null;
            } catch (error) {
                if (tmp) {
                    try { fs.unlinkSync(tmp); } catch { /* best effort */ }
                    tmp = null;
                }
                fail(`could not rewrite it atomically (${error.message || error.code})`);
            }
        };

        const writer = writerSections[0] || null;
        if (writer === null) {
            const next = `${head}${body}${tail}`;
            if (next === text) {
                note("managed block is already mergeable");
                process.exit(0);
            }
            note("the managed block carries no MCP row; removing its empty markers and leaving the entries in place");
            const saved = writeBackup();
            writeAtomic(next);
            note(`backup: ${saved}`);
            process.exit(0);
        }

        const names = writer.items.map((linesOfItem) => {
            const found = linesOfItem.join("\n").match(/^ {8}serverName: (.*)$/m);
            return found[1].trim().replace(/^"|"$/g, "");
        });
        const duplicates = [...new Set(names.filter((name, index) => names.indexOf(name) !== index))];
        if (duplicates.length > 0) {
            fail(`the managed block carries duplicate serverName row(s) ${duplicates.map((name) => JSON.stringify(name)).join(", ")}; --merge keys the kept rows by serverName, so it would drop one (remove or rename the duplicate first)`);
        }

        const extractCommentedEntries = (chunk) => {
            const kept = [];
            const runs = [];
            for (let index = 0; index < chunk.length; index += 1) {
                if (!/^\s*#\s*-\s+id:\s*/.test(chunk[index])) {
                    kept.push(chunk[index]);
                    continue;
                }
                const run = [];
                while (index < chunk.length && /^\s*#/.test(chunk[index])) {
                    run.push(chunk[index]);
                    index += 1;
                }
                index -= 1;
                runs.push(run);
            }
            return { kept, runs };
        };

        const isCommentOnly = (chunk) => chunk.every((line) => line.trim() === "" || line.trim().startsWith("#"));
        const blockPreamble = stripBlankEdges(pre);
        const between = stripBlankEdges(writer.between || []);
        if (!isCommentOnly(blockPreamble) || !isCommentOnly(between)) {
            fail("the managed block carries content before its writer rows that the writer would drop; this script cannot move it out without guessing, so it is left untouched (move it out of the markers and re-run)");
        }
        const strayLines = [];
        if (writer.strayItems && writer.strayItems.length > 0) {
            strayLines.push("- insert:");
            for (const linesOfItem of writer.strayItems) strayLines.push(...stripBlankEdges(linesOfItem));
        }
        const blockLines = [writer.lines[0]];
        for (const linesOfItem of writer.items) blockLines.push(...stripBlankEdges(linesOfItem));
        const block = extractCommentedEntries(blockLines);
        const blockBody = block.kept.join("\n");
        const rows = (blockBody.match(/^\s*-\s+id:/gm) || []).length;
        if (rows !== writer.items.length) {
            fail(`the managed block would still carry ${rows} "- id:" row(s) for ${writer.items.length} server row(s); cannot separate them safely (move the extra row out of the markers and re-run)`);
        }

        const foreign = sections.filter((candidate) => candidate !== writer);
        const foreignBefore = foreign.filter((candidate) => sections.indexOf(candidate) < sections.indexOf(writer));
        const foreignAfter = foreign.filter((candidate) => sections.indexOf(candidate) > sections.indexOf(writer));

        const renderSections = (chunks) => chunks
            .map((chunk) => stripBlankEdges(chunk.lines).join("\n"))
            .filter((chunk) => chunk !== "")
            .join("\n\n");

        const preservedBlocks = [];
        if (blockPreamble.length > 0) preservedBlocks.push(blockPreamble.join("\n"));
        if (between.length > 0) preservedBlocks.push(between.join("\n"));
        for (const run of block.runs) preservedBlocks.push(run.join("\n"));

        const movedEntries = foreign.length + (writer.strayItems ? writer.strayItems.length : 0);
        const movedBlocks = preservedBlocks.length;
        if (movedEntries === 0 && movedBlocks === 0) {
            note("managed block is already mergeable");
            process.exit(0);
        }

        const pieces = [];
        const headText = head.replace(/\s+$/, "");
        if (headText !== "") pieces.push(headText);
        const fore = renderSections(foreignBefore);
        if (fore !== "") pieces.push(fore);
        pieces.push(`${BEGIN}\n${blockBody}\n${END}`);
        const strayText = strayLines.join("\n");
        if (strayText !== "") pieces.push(strayText);
        for (const blockText of preservedBlocks) {
            if (blockText.trim() !== "") pieces.push(blockText);
        }
        const aft = renderSections(foreignAfter);
        if (aft !== "") pieces.push(aft);
        const tailText = tail.replace(/^\s+/, "");
        if (tailText !== "") pieces.push(tailText);
        const next = `${pieces.join("\n\n")}\n`;

        if (next === text) {
            note("managed block is already mergeable");
            process.exit(0);
        }

        const saved = writeBackup();
        writeAtomic(next);
        if (movedEntries > 0) {
            note(`moved ${movedEntries} non-writer entr${movedEntries === 1 ? "y" : "ies"} out of the managed block; text preserved verbatim`);
        }
        for (const chunk of [...foreignBefore, ...foreignAfter]) {
            note(`  moved out: ${chunk.lines[0].trim()}`);
        }
        if (writer.strayItems && writer.strayItems.length > 0) {
            for (const linesOfItem of writer.strayItems) {
                note(`  moved out (kept as an "- insert:" item): ${linesOfItem[0].trim()}`);
            }
        }
        for (const run of block.runs) {
            note(`  moved out (commented-out entry): ${run[0].trim()}`);
        }
        if (blockPreamble.length > 0 || between.length > 0) {
            note("  moved out the comment lines that sat before the writer rows");
        }
        note(`backup: ${saved}`);
        note("the row writer owns the two markers; anything it would drop is preserved outside them, byte for byte");
    ' "$patch_file"
}

# Confirm a profile really carries every row this installer owns, pointing at
# the trees this run just switched in (the docx servers) or at the installed
# Zotero bridge. The row writer validates the composed profile, but it only
# reports what it wrote; this check reads the file that will be loaded next time
# a session starts.
verify_dsh_profile_rows() {
    local profile=$1 patch_file=$2
    shift 2
    "$node_bin" -e '
        const fs = require("fs");
        const argv = process.argv.slice(1);
        const file = argv.shift();
        const text = fs.readFileSync(file, "utf8");
        const missing = [];
        for (let i = 0; i < argv.length; i += 2) {
            const [name, script] = argv.slice(i, i + 2);
            if (!text.includes(`serverName: "${name}"`) || !text.includes(script)) missing.push(name);
        }
        if (missing.length > 0) {
            process.stderr.write(`missing MCP row(s): ${missing.join(", ")}\n`);
            process.exit(1);
        }
    ' "$patch_file" "$@" || {
        echo "error: dsh profile ${profile} does not carry the MCP row(s) this installer wrote after the update" >&2
        exit 1
    }
}

# ---- install the MCP rows into every dsh profile ---------------------------
# Native install: this checkout's own server list is written into the profile,
# not a copy of Codex's configuration. `--merge` keeps rows for servers this
# run does not mention, so a profile that also carries other MCP servers keeps
# them (and REPLACES the rows it does mention, keyed by serverName -- which is
# how an existing zotero row that names an older bridge location is repointed).
# The row writer installs the MCP client plugin in the profile when it is
# missing and validates the composed profile before accepting the change.
#
# Two passes: reconcile EVERY block first (so a block that cannot be
# reconciled stops the run before the row writer touches any profile), then
# invoke the writer on each. The reconciliation itself is a safe, backed-up,
# in-place edit; if a later profile cannot be reconciled, the earlier repairs
# stay in place and the rerun after fixing it is idempotent.
if [ "$dsh_enabled" = 1 ]; then
    if [ -z "$dsh_cli" ]; then
        echo "skipped the dsh MCP install: the dsh CLI is not on PATH (skills were still installed)" >&2
    elif [ ! -d "$dsh_home/profiles" ]; then
        echo "skipped the dsh MCP install: no profiles under $dsh_home/profiles" >&2
    else
        servers_json="$dsh_home/.paper-skills-servers.$$.json"
        # The rows are passed as name/command/script triples, the same arrays
        # the Codex half uses, so both harnesses are written from one list.
        row_args=()
        for i in "${!mcp_row_names[@]}"; do
            row_args+=("${mcp_row_names[$i]}" "${mcp_row_commands[$i]}" "${mcp_row_scripts[$i]}")
        done
        "$node_bin" -e '
            const fs = require("fs");
            const argv = process.argv.slice(1);
            const out = argv.shift();
            const servers = [];
            for (let i = 0; i < argv.length; i += 3) {
                const [name, command, script] = argv.slice(i, i + 3);
                servers.push({
                    name,
                    enabled: true,
                    transport: {
                        type: "stdio",
                        command,
                        args: [script],
                        env: null,
                        env_vars: [],
                        cwd: null,
                    },
                });
            }
            fs.writeFileSync(out, `${JSON.stringify(servers, null, 2)}\n`);
        ' "$servers_json" "${row_args[@]}"

        profile_dirs=()
        for profile_dir in "$dsh_home"/profiles/*/; do
            [ -f "$profile_dir/cordis.patch.yml" ] || continue
            profile_dirs+=("${profile_dir%/}")
        done
        # What the verification reads back: the same name/script pairs the
        # writer was just given.
        verify_args=()
        for i in "${!mcp_row_names[@]}"; do
            verify_args+=("${mcp_row_names[$i]}" "${mcp_row_scripts[$i]}")
        done
        if [ "${#profile_dirs[@]}" -gt 0 ]; then
            for profile_dir in "${profile_dirs[@]}"; do
                profile=$(basename -- "$profile_dir")
                echo "checking the managed MCP block in dsh profile: $profile"
                repair_dsh_managed_block "$profile_dir/cordis.patch.yml"
            done
            for profile_dir in "${profile_dirs[@]}"; do
                profile=$(basename -- "$profile_dir")
                echo "installing MCP servers into dsh profile: $profile"
                "$node_bin" "$repo_dir/scripts/install-codex-mcp.mjs" \
                    --profile "$profile" \
                    --dsh-home "$dsh_home" \
                    --servers-json "$servers_json" \
                    --merge
                verify_dsh_profile_rows "$profile" "$profile_dir/cordis.patch.yml" "${verify_args[@]}"
                if [ "$zotero_enabled" = 1 ]; then zotero_rows=1; fi
            done
        else
            echo "skipped the dsh MCP install: no profile with a cordis.patch.yml under $dsh_home/profiles" >&2
        fi
        rm -f -- "$servers_json"
        servers_json=""
    fi
else
    if [ "$install_dsh" = auto ]; then
        echo "skipped the dsh half: no DeepSeek Harness found (set INSTALL_DSH=1 to force it)"
    else
        echo "skipped the dsh half: INSTALL_DSH=0"
    fi
fi

# ---- move this script's old install out of the config directory ------------
# `$CODEX_HOME` is a configuration hub: config.toml and skill discovery belong
# there, server code does not. Older versions of this script installed the two
# trees (plus their versioned copies and companion scripts) under
# $CODEX_HOME/mcp-tools. Once this run has switched them to $MCP_TOOLS_DIR and
# repointed every registration, the old copies are dead weight in the config
# directory, so this script's own items are moved into
# $MCP_TOOLS_DIR/.legacy/ -- never deleted. Moving is refused while a
# registration this installer knows about (the user Codex config, a project
# Codex config, or a dsh profile) still names a live item: a half-skipped
# install must not break the entries it did not repoint. Items another tool
# installed under that directory (a bridge, for example) are left untouched.
legacy_tool_path_referenced() {
    local needle=$1 file
    for file in "$codex_home/config.toml" "$PWD/.codex/config.toml"; do
        if [ -f "$file" ] && grep -Fq -- "$needle" "$file" 2>/dev/null; then
            return 0
        fi
    done
    for file in "$dsh_home/cordis.patch.yml" "$dsh_home"/profiles/*/cordis.patch.yml; do
        [ -f "$file" ] || continue
        if grep -Fq -- "$needle" "$file" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

if [ -d "$legacy_tools_dir" ] && [ "$tools_dir" != "$legacy_tools_dir" ]; then
    legacy_items=()
    shopt -s nullglob
    for tool_name in mcp-docx-converter mcp-docx-compare; do
        for p in "$legacy_tools_dir/$tool_name" "$legacy_tools_dir/$tool_name"-* "$legacy_tools_dir/$tool_name".stage.*; do
            [ -e "$p" ] && legacy_items+=("$p")
        done
    done
    for companion in docx2pdf.sh docxcompare.sh; do
        for p in "$legacy_tools_dir/$companion" "$legacy_tools_dir/.$companion".stage.*; do
            [ -e "$p" ] && legacy_items+=("$p")
        done
    done
    shopt -u nullglob
    if [ "${#legacy_items[@]}" -eq 0 ]; then
        echo "nothing of this script's install remains in $legacy_tools_dir"
    else
        referenced=0
        for p in "${legacy_items[@]}"; do
            case "$(basename -- "$p")" in
                mcp-docx-converter|mcp-docx-compare|docx2pdf.sh|docxcompare.sh) ;;
                *) continue ;;
            esac
            if legacy_tool_path_referenced "$p"; then
                referenced=1
            fi
        done
        if [ "$referenced" = 1 ]; then
            echo "note: left this script's previous trees in $legacy_tools_dir; a config or dsh" >&2
            echo "      profile still names them. Server code does not belong in the config" >&2
            echo "      directory: remove them once nothing points there." >&2
        else
            legacy_backup_dir="$tools_dir/.legacy"
            stamp="$(date +%Y%m%d%H%M%S)"
            target_dir="$legacy_backup_dir/mcp-tools.$stamp"
            suffix=0
            while [ -e "$target_dir" ]; do
                suffix=$((suffix + 1))
                target_dir="$legacy_backup_dir/mcp-tools.$stamp.$suffix"
            done
            if mkdir -p -- "$target_dir"; then
                for p in "${legacy_items[@]}"; do
                    if mv -- "$p" "$target_dir/"; then
                        echo "moved out of the config directory: $p -> $target_dir/"
                    else
                        echo "warning: could not move $p out of $legacy_tools_dir" >&2
                    fi
                done
                if [ -d "$legacy_tools_dir" ]; then
                    if rmdir -- "$legacy_tools_dir" 2>/dev/null; then
                        echo "removed the now-empty $legacy_tools_dir"
                    else
                        echo "note: $legacy_tools_dir still holds files this script does not install; left in place"
                    fi
                fi
            else
                echo "warning: could not create $target_dir; the previous trees stay in $legacy_tools_dir" >&2
            fi
        fi
    fi
fi

if [ "$zotero_rows" = 1 ]; then
    # A harness row now runs the bridge, but the bridge still needs its one-time
    # pairing: say so here, where the row was written, instead of only in
    # documentation.
    echo "Zotero pairing: in Zotero choose Tools > Codex Zotero Bridge > Pair Codex,"
    echo "then call the zotero_pair tool with the one-time 8-digit code."
fi

echo "install complete: ${new_version} (MCP server code in ${tools_dir})"

#!/usr/bin/env bash
# Install this checkout's two skills AND its two MCP docx servers into every
# agent harness present on this machine:
#
#   * Codex ($CODEX_HOME, default ~/.codex): the versioned paper-skills-*
#     package, the two MCP server trees, and one [mcp_servers.<name>] entry
#     per server that points at those trees.
#   * DeepSeek Harness ($DSH_HOME, default ~/.dsh): both skills in its flat
#     skills directory (one copy per frontmatter `name`), and the same two
#     servers in EVERY profile's cordis.patch.yml.
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
# Where the two MCP servers are deployed. BOTH harnesses run this copy -- the
# dsh rows name it explicitly -- so the default keeps the historical path.
tools_dir="${MCP_TOOLS_DIR:-$codex_home/mcp-tools}"

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

# ---- normalize the paths that end up in configs ----------------------------
codex_home=$(resolve_dir "$codex_home")
skills_dir="$codex_home/skills"
backup_dir="$codex_home/backup"
tools_dir=$(resolve_dir "$tools_dir")
if [ "$dsh_enabled" = 1 ]; then
    dsh_home=$(resolve_dir "$dsh_home")
    dsh_skills_dir="$dsh_home/skills"
    dsh_backup_dir="$dsh_home/backup"
fi
node_bin=$(resolve_file "$node_bin")

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
    rm -rf -- "$staging"
    mkdir -p -- "$staging"
    (cd -- "$repo_dir/${tool_name}" && tar cf - --exclude=./node_modules .) | (cd -- "$staging" && tar xf -)
    npm ci --prefix "$staging" --no-audit --no-fund
    stage_tools+=("$staging")
    companion_stage="${tools_dir}/.${companion}.stage.$$"
    install -m 0755 -- "$repo_dir/$companion" "$companion_stage"
    stage_companions+=("$companion_stage")
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

# ---- register the two servers with Codex -----------------------------------
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

    for docx_tool in compare converter; do
        name="docx-${docx_tool}"
        script="$tools_dir/mcp-docx-${docx_tool}/index.js"
        state=$(codex_mcp_state "$name" "$node_bin" "$script")
        case "$state" in
            ok)
                echo "codex MCP server already current: $name -> $script"
                ;;
            missing)
                backup_codex_config
                CODEX_HOME="$codex_home" codex mcp add "$name" -- "$node_bin" "$script"
                echo "registered codex MCP server: $name -> $script"
                ;;
            stale)
                # The entry runs a copy this install replaced; replace the entry.
                backup_codex_config
                CODEX_HOME="$codex_home" codex mcp remove "$name" >/dev/null
                CODEX_HOME="$codex_home" codex mcp add "$name" -- "$node_bin" "$script"
                echo "repointed codex MCP server: $name -> $script"
                ;;
            *)
                echo "error: could not read the codex MCP configuration (state: $state)" >&2
                exit 1
                ;;
        esac
        state=$(codex_mcp_state "$name" "$node_bin" "$script")
        [ "$state" = ok ] || {
            echo "error: codex still does not report $name -> $script after writing it (state: $state)" >&2
            exit 1
        }
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

# ---- install the two servers into every dsh profile ------------------------
# Native install: this checkout's own server list is written into the profile,
# not a copy of Codex's configuration. `--merge` keeps rows for servers this
# run does not mention, so a profile that also carries other MCP servers keeps
# them. The row writer installs the MCP client plugin in the profile when it is
# missing and validates the composed profile before accepting the change.
if [ "$dsh_enabled" = 1 ]; then
    if [ -z "$dsh_cli" ]; then
        echo "skipped the dsh MCP install: the dsh CLI is not on PATH (skills were still installed)" >&2
    elif [ ! -d "$dsh_home/profiles" ]; then
        echo "skipped the dsh MCP install: no profiles under $dsh_home/profiles" >&2
    else
        servers_json="$dsh_home/.paper-skills-servers.$$.json"
        "$node_bin" -e '
            const fs = require("fs");
            const [out, nodeBin, toolsDir] = process.argv.slice(1);
            const servers = [
                ["docx-compare", "mcp-docx-compare"],
                ["docx-converter", "mcp-docx-converter"],
            ].map(([name, dir]) => ({
                name,
                enabled: true,
                transport: {
                    type: "stdio",
                    command: nodeBin,
                    args: [`${toolsDir}/${dir}/index.js`],
                    env: null,
                    env_vars: [],
                    cwd: null,
                },
            }));
            fs.writeFileSync(out, `${JSON.stringify(servers, null, 2)}\n`);
        ' "$servers_json" "$node_bin" "$tools_dir"

        profiles=0
        for profile_dir in "$dsh_home"/profiles/*/; do
            [ -f "$profile_dir/cordis.patch.yml" ] || continue
            profile=$(basename -- "$profile_dir")
            profiles=$((profiles + 1))
            echo "installing MCP servers into dsh profile: $profile"
            "$node_bin" "$repo_dir/scripts/install-codex-mcp.mjs" \
                --profile "$profile" \
                --dsh-home "$dsh_home" \
                --servers-json "$servers_json" \
                --merge
        done
        if [ "$profiles" = 0 ]; then
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

echo "install complete: ${new_version}"

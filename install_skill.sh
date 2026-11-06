#!/usr/bin/env bash
# Install this checkout's paper-skills/ under $HOME/.codex/skills/, moving any
# previously installed paper-skills-* package into $HOME/.codex/backup/ first.
#
# Every failure is fatal (no `|| true`): a silent failure here leaves stale
# versions installed or destroys the expected backup layout without a word.
#
# The whole installation is STAGED before anything live is touched: the skills
# pack, both MCP server trees and both companion scripts are built and checked
# in temporary paths first, and only then switched in. A failed `npm ci` for the
# second server therefore leaves the previous installation intact instead of a
# mixed skills/new-converter/old-comparer tree (F-094).
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
skills_dir="$HOME/.codex/skills"
backup_dir="$HOME/.codex/backup"
# Where the two MCP servers are deployed for the Codex config to reach.
# `$HOME/.codex/mcp-tools` is the portable default; override with MCP_TOOLS_DIR.
tools_dir="${MCP_TOOLS_DIR:-$HOME/.codex/mcp-tools}"
mkdir -p -- "$skills_dir" "$backup_dir"

# The commit suffix is informational: outside a git checkout (or in a shallow
# deployment) fall back to a literal so the installed name still identifies the
# install instead of ending in a bare "-".
commit=$(git -C "$repo_dir" rev-parse HEAD 2>/dev/null | head -n 1 | head -c 7) || commit=""
commit=${commit:-nogit}

new_version="$(date +'%Y-%m%d')-$commit"

stage_skills="$skills_dir/.paper-skills-stage.$$"
stage_tools=()
stage_companions=()
cleanup() {
    rc=$?
    rm -rf -- "$stage_skills"
    for s in "${stage_tools[@]:-}"; do
        [ -n "$s" ] && rm -rf -- "$s"
    done
    for s in "${stage_companions[@]:-}"; do
        [ -n "$s" ] && rm -f -- "$s"
    done
    exit "$rc"
}
trap cleanup EXIT

# ---- stage the skills pack -------------------------------------------------
rm -rf -- "$stage_skills"
cp -r -- "$repo_dir/paper-skills" "$stage_skills"
[ -d "$stage_skills" ]

# ---- stage both MCP servers and their companion scripts --------------------
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
echo "installed skill: $dest"

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
    mv -- "$staging" "$tool_path"
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

#!/usr/bin/env bash
# Install this checkout's paper-skills/ under $HOME/.codex/skills/, moving any
# previously installed paper-skills-* package into $HOME/.codex/backup/ first.
#
# Every failure is fatal (no `|| true`): a silent failure here leaves stale
# versions installed or destroys the expected backup layout without a word.
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

shopt -s nullglob
previous=("$skills_dir"/paper-skills-*)
shopt -u nullglob
for p in "${previous[@]}"; do
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

new_version="$(date +'%Y-%m%d')-$commit"

dest="$skills_dir/paper-skills-${new_version}"
cp -r -- "$repo_dir/paper-skills" "$dest"
echo "installed skill: $dest"

for docx_tool in converter compare; do
    tool_name="mcp-docx-${docx_tool}"
    tool_path="${tools_dir}/${tool_name}"
    case "$docx_tool" in
        compare) companion="docxcompare.sh" ;;
        converter) companion="docx2pdf.sh" ;;
    esac
    # Stage the SOURCE only and run npm ci THERE: removing the live install
    # first meant a failed/timed-out install left a working converter broken
    # and aborted before the compare server was touched. `node_modules/` is
    # never vendored (copying it over a Windows mount is slow, and a stale copy
    # fails silently).
    staging="${tool_path}.stage.$$"
    rm -rf -- "$staging"
    mkdir -p -- "$staging"
    (cd -- "$repo_dir/${tool_name}" && tar cf - --exclude=./node_modules .) | (cd -- "$staging" && tar xf -)
    npm ci --prefix "$staging" --no-audit --no-fund
    # The staging tree is complete: swap it in, keeping the old tree until the
    # move has succeeded. A same-day re-run names the SAME snapshot directory;
    # remove the stale snapshot first (the version name identifies ONE install).
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
    install -m 0755 -- "$repo_dir/$companion" "$(dirname -- "$tool_path")/$companion"
    echo "installed companion: $(dirname -- "$tool_path")/$companion"
done


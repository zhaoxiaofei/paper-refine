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
# Where the two MCP servers are deployed for the Codex config to reach (the
# operator's default; override with MCP_TOOLS_DIR on another machine).
tools_dir="${MCP_TOOLS_DIR:-/mnt/c/Users/zhaoxiaofei/Documents/my-nutstore/zxf-cnv-paper-postgrad}"
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
        target="$backup_dir/$name.$(date +%Y%m%d%H%M%S)"
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
    # Copy the SOURCE only: node_modules/ is installed at the destination below
    # (copying it over the Windows mount is slow, and a stale copy fails the
    # same silent way this script exists to prevent).
    rm -rf -- "$tool_path"
    mkdir -p -- "$tool_path"
    (cd -- "$repo_dir/${tool_name}" && tar cf - --exclude=./node_modules .) | (cd -- "$tool_path" && tar xf -)
    # A same-day re-run names the SAME snapshot directory. `cp -r SRC DST` with
    # DST already present copies SRC INTO it, so the snapshot's top level kept
    # the previous run's bytes and the fresh copy sat one level down; remove the
    # stale snapshot first (the version name identifies ONE install).
    rm -rf -- "${tool_path}-${new_version}"
    cp -r -- "$tool_path" "${tool_path}-${new_version}"
    echo "installed mcp-tool: ${tool_path}"
    # Both node servers answer initialize() and then fail EVERY tool call with
    # `spawn <script> ENOENT` when the shell script they drive is not where
    # they resolve it: ../<script>, then ./<script>, then PATH.
    install -m 0755 -- "$repo_dir/$companion" "$(dirname -- "$tool_path")/$companion"
    echo "installed companion: $(dirname -- "$tool_path")/$companion"
    # `node_modules/` is never vendored: a server started without it exits with
    # `ERR_MODULE_NOT_FOUND` before it reads stdin, which the caller sees as
    # "the MCP server did not answer initialize()".
    npm ci --prefix "$tool_path" --no-audit --no-fund
done


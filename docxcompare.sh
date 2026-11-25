#!/usr/bin/env bash
# docxcompare.sh - Compare two .docx files using Microsoft Word (via PowerShell).
# Usage: ./docxcompare.sh original.docx revised.docx [output.docx]
# If output.docx is omitted, it defaults to "original-vs-revised-redline.docx".
#
# This is the Word-native comparison engine: PowerShell drives
# `Word.Application.CompareDocuments`, Word's own redline engine (the same one
# the Review > Compare ribbon command uses), so the tracked changes a reviewer
# sees are Word's, not a re-implementation's. It is the FIRST choice of
# `paper_pipeline.redline_one_pair()` (through the `docx-compare` MCP server in
# mcp-docx-compare/) and of the paper-revise skill's E5 rule; the fallbacks
# there are python-redlines[docxodus], docx-trackdiff, a user command and the
# built-in OOXML writer.
#
# Requires WSL or Git Bash on Windows with Microsoft Word installed.

set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: $0 <original.docx> <revised.docx> [output.docx]" >&2
    exit 2
fi

ORIG="$1"
REVISED="$2"
OUTPUT="${3:-}"

for f in "$ORIG" "$REVISED"; do
    if [[ ! -f "$f" ]]; then
        echo "Error: file not found: $f" >&2
        exit 1
    fi
done

# Word's comparison engine takes WordprocessingML packages; a .doc/.rtf/.pdf
# handed in would fail deep inside COM with an opaque message, so refuse it here
# with a message that names the file.
for f in "$ORIG" "$REVISED"; do
    case "${f,,}" in
        *.docx) ;;
        *)
            echo "Error: not a .docx file: $f" >&2
            exit 2
            ;;
    esac
done

# Resolve symlinks so Word sees the real files. Checked like docx2pdf.sh does:
# an unconditional `realpath` under `set -e` died with an opaque
# "command not found" (exit 127) on a host without coreutils, before the
# `command -v realpath` guard further down could produce its own message.
if ! ORIG_REAL="$(realpath -- "$ORIG" 2>/dev/null)"; then
    echo "Error: cannot resolve the path: $ORIG" >&2
    exit 1
fi
if ! REVISED_REAL="$(realpath -- "$REVISED" 2>/dev/null)"; then
    echo "Error: cannot resolve the path: $REVISED" >&2
    exit 1
fi

# The extension check above ran on the ARGUMENT; a link named `alias.docx`
# whose target is a PDF would reach Word/COM as a PDF. Re-check the RESOLVED
# paths, like docx2pdf.sh does.
for f in "$ORIG_REAL" "$REVISED_REAL"; do
    case "${f,,}" in
        *.docx) ;;
        *)
            echo "Error: input resolves to a non-.docx file: $f" >&2
            exit 2
            ;;
    esac
done

# Derive a default output name from the resolved original path.
if [[ -z "$OUTPUT" ]]; then
    ORIG_DIR="$(dirname -- "$ORIG_REAL")"
    ORIG_BASE="$(basename -- "$ORIG_REAL")"
    REVISED_BASE="$(basename -- "$REVISED_REAL")"
    OUTPUT="$ORIG_DIR/${ORIG_BASE%.*}-vs-${REVISED_BASE%.*}-redline.docx"
fi
# SaveAs2 format 16 writes a DOCX package whatever the name says; a .pdf
# output would be reported as a redline and then fail to open as one.
case "${OUTPUT,,}" in
    *.docx) ;;
    *)
        echo "Error: output must be a .docx file: $OUTPUT" >&2
        exit 2
        ;;
esac

# Resolve a relative output against the CALLER's directory, as docx2pdf.sh
# already does: `wslpath -w` returns a relative path unchanged, so Word
# resolved the temp name against ITS OWN working directory while the
# WSL-side checks and the final `mv` looked only at the caller's cwd -- the
# comparison then failed (or wrote outside the requested destination) for
# every relative output argument.
if [[ "$OUTPUT" != /* ]]; then OUTPUT="$PWD/$OUTPUT"; fi

if ! command -v powershell.exe >/dev/null 2>&1; then
    echo "Error: powershell.exe not found. Run from WSL or Git Bash on Windows." >&2
    exit 1
fi

# Convert to absolute Windows paths.
if command -v wslpath >/dev/null 2>&1; then
    ORIG_WIN="$(wslpath -w "$ORIG_REAL")"
    REVISED_WIN="$(wslpath -w "$REVISED_REAL")"
    OUTPUT_WIN="$(wslpath -w "$OUTPUT")"
elif command -v cygpath >/dev/null 2>&1; then
    ORIG_WIN="$(cygpath -w "$ORIG_REAL")"
    REVISED_WIN="$(cygpath -w "$REVISED_REAL")"
    OUTPUT_WIN="$(cygpath -w "$OUTPUT")"
else
    echo "Error: neither wslpath nor cygpath available." >&2
    exit 1
fi

win_path() {
    if command -v wslpath >/dev/null 2>&1; then wslpath -w "$1"
    else cygpath -w "$1"; fi
}

# Never let the output BE one of the inputs: the stale-output cleanup below
# would delete the very file Word is about to read. The comparison is
# case-insensitive because the real destination is a Windows filesystem, where
# "REPORT.docx" and "report.docx" are the same file (docx2pdf.sh learned the
# same lesson for its derived PDF path).
if command -v realpath >/dev/null 2>&1; then
    OUTPUT_ABS="$(realpath -m -- "$OUTPUT" 2>/dev/null || printf '%s' "$OUTPUT")"
else
    OUTPUT_ABS="$OUTPUT"
fi
lc() { printf '%s' "${1,,}"; }
if [[ "$(lc "$OUTPUT_ABS")" == "$(lc "$ORIG_REAL")" \
   || "$(lc "$OUTPUT_ABS")" == "$(lc "$REVISED_REAL")" ]]; then
    echo "Error: refusing to overwrite an input file: $OUTPUT" >&2
    exit 2
fi

# Escape single quotes for PowerShell single-quoted strings.
ps_escape() { printf '%s' "$1" | sed "s/'/''/g"; }
ORIG_WIN_PS="$(ps_escape "$ORIG_WIN")"
REVISED_WIN_PS="$(ps_escape "$REVISED_WIN")"
OUTPUT_WIN_PS="$(ps_escape "$OUTPUT_WIN")"

# Do NOT remove an existing OUTPUT up front: the unique temp is renamed into
# place only on success, so a failed render must leave the previous file intact
# (F049).
# Write to a UNIQUE temp beside the destination, verify THAT file, then rename
# atomically into place: a shared final path let two runs delete/overwrite each
# other's in-flight output while both announced success (F02), and a PowerShell
# failure left its partial file at the requested path (F82).
OUTPUT_TMP="${OUTPUT}.tmp.$$.$RANDOM.docx"
OUTPUT_TMP_WIN="$(win_path "$OUTPUT_TMP")"
OUTPUT_TMP_WIN_PS="$(ps_escape "$OUTPUT_TMP_WIN")"
# F133: on WSL every process here is process.platform 'linux'; the Node runner
# can only SIGKILL the Unix process group, which does not reach a Windows
# powershell.exe or the Word/COM server it starts. Record their WINDOWS pids so
# the runner can taskkill.exe them on a timeout. The pid file lives beside the
# output (a path both WSL and Windows can write), so convert it here.
PIDFILE_WIN=""
if [[ -n "${DOCX_MCP_WINDOWS_PID_FILE:-}" ]]; then
    PIDFILE_WIN="$(win_path "$DOCX_MCP_WINDOWS_PID_FILE")"
fi
PIDFILE_WIN_PS="$(ps_escape "$PIDFILE_WIN")"
_cleanup_partial() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        rm -f -- "$OUTPUT_TMP"
    fi
}
trap _cleanup_partial EXIT

PS_SCRIPT=$(cat <<EOF
\$ErrorActionPreference = 'Stop'
\$originalPath = '$ORIG_WIN_PS'
\$revisedPath  = '$REVISED_WIN_PS'
\$outputPath   = '$OUTPUT_TMP_WIN_PS'
\$pidFile      = '$PIDFILE_WIN_PS'

# Record this PowerShell's Windows PID BEFORE Word starts: if COM activation
# itself hangs, the runner still has a Windows pid to kill.
if (\$pidFile) {
    try { \$PID | Set-Content -LiteralPath \$pidFile -Encoding ascii } catch { }
}

if (-not (Test-Path -LiteralPath \$originalPath)) { Write-Error "Original not found: \$originalPath"; exit 1 }
if (-not (Test-Path -LiteralPath \$revisedPath))  { Write-Error "Revised not found: \$revisedPath";  exit 1 }

\$word = \$null
\$original = \$null
\$revised = \$null
\$comparison = \$null
try {
    # Word is launched by COM, not as this process's child, so taskkill /T on
    # the PowerShell pid need not reach it. Record the WINWORD pid(s) that
    # appear while this run creates its instance.
    \$wordBefore = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue |
                    ForEach-Object { \$_.Id })
    \$word = New-Object -ComObject Word.Application
    if (\$pidFile) {
        try {
            \$wordAfter = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue |
                           ForEach-Object { \$_.Id })
            \$newWord = @(\$wordAfter | Where-Object { \$wordBefore -notcontains \$_ })
            if (\$newWord.Count -gt 0) {
                Add-Content -LiteralPath \$pidFile -Value \$newWord -Encoding ascii
            }
        } catch { }
    }
    \$word.Visible = \$false
    \$word.DisplayAlerts = 0
    # msoAutomationSecurityForceDisable = 3 -- disable macros.
    \$word.AutomationSecurity = 3

    \$original = \$word.Documents.Open(\$originalPath, \$false, \$true)  # read-only
    \$revised  = \$word.Documents.Open(\$revisedPath,  \$false, \$true)  # read-only

    # wdCompareDestinationNew = 0, wdGranularityWordLevel = 1,
    # CompareFormatting = true, CompareCaseChanges = true, etc.
    \$comparison = \$word.CompareDocuments(\$original, \$revised)
    \$comparison.SaveAs2(\$outputPath, 16)  # 16 = wdFormatDocumentDefault (.docx)
} finally {
    # Every Close is guarded: an error inside the comparison used to be masked
    # by "you cannot call a method on a null-valued expression" from here.
    if (\$comparison) { \$comparison.Close(\$false) }
    if (\$original)   { \$original.Close(\$false) }
    if (\$revised)    { \$revised.Close(\$false) }
    if (\$word) {
        \$word.Quit()
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject(\$word)
    }
}

Write-Output \$outputPath
EOF
)

ENCODED="$(printf '%s' "$PS_SCRIPT" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)"
# Word is a single-instance COM automation server, so a poisoned instance (left
# behind by a killed run) or a modal dialog can make this call block forever.
# The script therefore bounds its own call -- but it must NEVER bound it below
# the caller's budget, because the CALLER owns the kill policy: the docx-compare
# MCP server caps this same comparison at 900 s and escalates to taskkill on the
# recorded Windows pids (F133), the only kill that reaches a Windows
# powershell.exe/WINWORD from WSL, and the redline chain bounds it at 900 s as
# well (mcp_compare_docx(timeout=900)).  A 180 s cap here failed a slow-but-valid
# comparison minutes before that budget and silently downgraded the redline to a
# lower-fidelity backend -- the very defect the MCP layer already fixed once
# (C10) -- so the default is that same 900 s budget, and DOCXCOMPARE_TIMEOUT
# overrides it (0 disables the cap for a caller that carries a larger budget).
# `-k` makes the bound real: a child that ignores SIGTERM must not keep the
# wrapper waiting, so SIGKILL follows the grace period and that exit (137) also
# reads as a timeout.  `timeout` is optional (it is absent on some Git Bash
# setups); without it the behaviour is the historical unbounded call.
timeout_s="${DOCXCOMPARE_TIMEOUT:-900}"
case "$timeout_s" in
    '' | *[!0-9]*)
        echo "Error: DOCXCOMPARE_TIMEOUT must be a whole number of seconds (0 disables the cap): $timeout_s" >&2
        exit 2
        ;;
esac
# `10#` so a leading zero is read as decimal, not as octal arithmetic.
timeout_s=$((10#$timeout_s))
TIMEOUT_BIN="$(command -v timeout || true)"
if (( timeout_s > 0 )) && [[ -z "$TIMEOUT_BIN" && -n "${DOCXCOMPARE_TIMEOUT:-}" ]]; then
    echo "Warning: DOCXCOMPARE_TIMEOUT is set but 'timeout' is not installed; running unbounded" >&2
fi
rc=0
if (( timeout_s > 0 )) && [[ -n "$TIMEOUT_BIN" ]]; then
    "$TIMEOUT_BIN" -k 30 "$timeout_s" \
        powershell.exe -NoProfile -NonInteractive -EncodedCommand "$ENCODED" || rc=$?
else
    powershell.exe -NoProfile -NonInteractive -EncodedCommand "$ENCODED" || rc=$?
fi
if [[ $rc -eq 124 || $rc -eq 137 ]]; then
    echo "Error: Word comparison timed out after ${timeout_s}s: $OUTPUT" >&2
    exit 124
elif [[ $rc -ne 0 ]]; then
    exit "$rc"
fi

if [[ ! -s "$OUTPUT_TMP" ]]; then
    echo "Error: no comparison document was written: $OUTPUT" >&2
    exit 1
fi
# A non-empty file is not a Word redline: require a readable OOXML package
# carrying the main document part before reporting success. The verifier is
# Python, so a missing interpreter must be reported as a DEPENDENCY error (and
# the unverified Word output removed) instead of being misdiagnosed as a
# corrupt comparison document.
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required to verify the comparison document; install Python 3 and re-run" >&2
    rm -f -- "$OUTPUT_TMP"
    exit 1
fi
if ! python3 -c 'import sys, zipfile, xml.etree.ElementTree as ET
z = zipfile.ZipFile(sys.argv[1]); names = set(z.namelist())
for required in ("[Content_Types].xml", "word/document.xml", "word/_rels/document.xml.rels"):
    if required not in names:
        raise SystemExit(1)
ET.fromstring(z.read("[Content_Types].xml"))
doc = z.read("word/document.xml")
ET.fromstring(doc)
raise SystemExit(0 if doc.strip() else 1)'         "$OUTPUT_TMP" 2>/dev/null; then
    echo "Error: the comparison document is not a readable DOCX package: $OUTPUT" >&2
    rm -f -- "$OUTPUT_TMP"
    exit 1
fi
mv -f -- "$OUTPUT_TMP" "$OUTPUT"

echo "Redline written: $OUTPUT"

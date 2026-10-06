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

# Resolve symlinks so Word sees the real files.
ORIG_REAL="$(realpath -- "$ORIG")"
REVISED_REAL="$(realpath -- "$REVISED")"

# Derive a default output name from the resolved original path.
if [[ -z "$OUTPUT" ]]; then
    ORIG_DIR="$(dirname -- "$ORIG_REAL")"
    ORIG_BASE="$(basename -- "$ORIG_REAL")"
    REVISED_BASE="$(basename -- "$REVISED_REAL")"
    OUTPUT="$ORIG_DIR/${ORIG_BASE%.*}-vs-${REVISED_BASE%.*}-redline.docx"
fi

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

# Remove any stale output so a previous run cannot masquerade as success.
rm -f -- "$OUTPUT"

PS_SCRIPT=$(cat <<EOF
\$ErrorActionPreference = 'Stop'
\$originalPath = '$ORIG_WIN_PS'
\$revisedPath  = '$REVISED_WIN_PS'
\$outputPath   = '$OUTPUT_WIN_PS'

if (-not (Test-Path -LiteralPath \$originalPath)) { Write-Error "Original not found: \$originalPath"; exit 1 }
if (-not (Test-Path -LiteralPath \$revisedPath))  { Write-Error "Revised not found: \$revisedPath";  exit 1 }

\$word = \$null
\$original = \$null
\$revised = \$null
\$comparison = \$null
try {
    \$word = New-Object -ComObject Word.Application
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
powershell.exe -NoProfile -NonInteractive -EncodedCommand "$ENCODED"

if [[ ! -s "$OUTPUT" ]]; then
    echo "Error: no comparison document was written: $OUTPUT" >&2
    exit 1
fi

echo "Redline written: $OUTPUT"

#!/usr/bin/env bash
# docx2pdf.sh - Convert a .docx file to PDF using Microsoft Word (via PowerShell).
# Usage: ./docx2pdf.sh path/to/file.docx
# For example,
#   ./docx2pdf.sh cnb01A-1-coverLetter-b.docx # to generate cnb01A-1-coverLetter-b.pdf
#   ./docx2pdf.sh cnb01B-2-mainText-b.docx    # to generate cnb01B-2-mainText-b.pdf

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <file.docx>" >&2
    exit 2
fi

DOCX="$1"

if [[ ! -f "$DOCX" ]]; then
    echo "Error: file not found: $DOCX" >&2
    exit 1
fi

# Resolve symlinks ONCE: Word writes the PDF next to the REAL file, so the
# stale-output cleanup and the verification must use the same resolved path
# (deriving them from the link produced a guaranteed false failure, and aimed
# the rm at the wrong sibling).
if ! DOCX_REAL="$(realpath -- "$DOCX" 2>/dev/null)"; then
    echo "Error: cannot resolve the path: $DOCX" >&2
    exit 1
fi

# Check for PowerShell (works in WSL and Git Bash)
if ! command -v powershell.exe >/dev/null 2>&1; then
    echo "Error: powershell.exe not found. Run this from WSL or Git Bash on Windows." >&2
    exit 1
fi

# Convert to absolute Windows path.
# Prefer wslpath; fall back to realpath + cygpath for Git Bash.
if command -v wslpath >/dev/null 2>&1; then
    DOCX_WIN="$(wslpath -w "$DOCX_REAL")"
elif command -v cygpath >/dev/null 2>&1; then
    DOCX_WIN="$(cygpath -w "$DOCX_REAL")"
else
    echo "Error: neither wslpath nor cygpath available." >&2
    exit 1
fi

echo "Converting: $DOCX_WIN"

# ...but never delete the file we were handed. The output path is DERIVED from
# the input, so a path that already ends in .pdf is its own output: on Windows
# (case-insensitive) it is the same file, and on a case-sensitive filesystem an
# input like REPORT.PDF would delete an unrelated REPORT.pdf sibling.
case "${DOCX,,}" in
    *.pdf)
        echo "Error: input is already a PDF (nothing to convert): $DOCX" >&2
        exit 2
        ;;
esac

# The PDF this run is supposed to produce. Remove any earlier render first: the
# render-then-look rule inspects this file, and a PDF left over from a previous
# run must never pass for the output of this one.
DOCX_DIR="$(dirname -- "$DOCX_REAL")"
DOCX_BASE="$(basename -- "$DOCX_REAL")"
PDF="$DOCX_DIR/${DOCX_BASE%.*}.pdf"
rm -f -- "$PDF"

# Escape the path for a PowerShell single-quoted string: a quote inside such a
# string is written twice. (Interpolating it raw terminated the string early and
# made Word conversion fail with a syntax error for any path containing "'".)
DOCX_WIN_PS="${DOCX_WIN//\'/\'\'}"

# Build the PowerShell script. Single-quoted in bash so nothing is expanded
# here; DOCX_WIN_PS is the same path with that escaping already applied.
PS_SCRIPT=$(cat <<EOF
\$ErrorActionPreference = 'Stop'
\$docx = '$DOCX_WIN_PS'
\$pdf  = [System.IO.Path]::ChangeExtension(\$docx, '.pdf')

if (-not (Test-Path -LiteralPath \$docx)) {
    Write-Error "Input not found: \$docx"
    exit 1
}

\$word = \$null
try {
    \$word = New-Object -ComObject Word.Application
    \$word.Visible = \$false
    \$word.DisplayAlerts = 0

    \$doc = \$word.Documents.Open(\$docx, \$false, \$true)   # read-only
    try {
        \$doc.ExportAsFixedFormat(\$pdf, 17)                # 17 = wdExportFormatPDF
    }
    finally {
        \$doc.Close(\$false)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject(\$doc)
    }
}
finally {
    if (\$word) {
        \$word.Quit()
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject(\$word)
    }
}

Write-Output \$pdf
EOF
)

# Encode as UTF-16LE base64 so no shell/PowerShell quoting issues survive.
ENCODED="$(printf '%s' "$PS_SCRIPT" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)"

powershell.exe -NoProfile -NonInteractive -EncodedCommand "$ENCODED"

# Verify the output instead of assuming it: a converter that wrote no PDF (or
# nothing at all) must not be reported as a successful render.
if [[ ! -s "$PDF" ]]; then
    echo "Error: no PDF was written: $PDF" >&2
    exit 1
fi

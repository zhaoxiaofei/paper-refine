#!/usr/bin/env bash
# docx2pdf.sh - Convert a .docx file to PDF using Microsoft Word (via PowerShell).
# Usage: ./docx2pdf.sh path/to/file.docx [path/to/output.pdf]
# For example,
#   ./docx2pdf.sh cnb01A-1-coverLetter-b.docx # to generate cnb01A-1-coverLetter-b.pdf
#   ./docx2pdf.sh cnb01B-2-mainText-b.docx    # to generate cnb01B-2-mainText-b.pdf
# The optional output names the destination explicitly; the MCP server uses it
# when it hands Word a private copy of the input instead of the caller's path.

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 <file.docx> [output.pdf]" >&2
    exit 2
fi

DOCX="$1"
OUTPUT="${2:-}"

if [[ ! -f "$DOCX" ]]; then
    echo "Error: file not found: $DOCX" >&2
    exit 1
fi
# The documented input is a .docx. Without this guard a regular sample.txt is
# accepted, sample.pdf is derived and deleted as "stale output" before Word is
# even asked to open a non-Word file.
case "${DOCX,,}" in
    *.docx) ;;
    *)
        echo "Error: input is not a .docx file: $DOCX" >&2
        exit 2
        ;;
esac

# Resolve symlinks ONCE: Word writes the PDF next to the REAL file, so the
# stale-output cleanup and the verification must use the same resolved path
# (deriving them from the link produced a guaranteed false failure, and aimed
# the rm at the wrong sibling).
if ! DOCX_REAL="$(realpath -- "$DOCX" 2>/dev/null)"; then
    echo "Error: cannot resolve the path: $DOCX" >&2
    exit 1
fi
case "${DOCX_REAL,,}" in
    *.docx) ;;
    *)
        echo "Error: input resolves to a non-.docx file: $DOCX" >&2
        exit 2
        ;;
esac

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
# ...and never delete the file a symlink RESOLVES to. A link named `alias.docx`
# whose target is `realfile.pdf` slipped past the guard above, and the
# stale-output cleanup then removed the resolved PDF before failing.
case "${DOCX_REAL,,}" in
    *.pdf)
        echo "Error: input resolves to a PDF (nothing to convert): $DOCX" >&2
        exit 2
        ;;
esac

# The PDF this run is supposed to produce. Remove any earlier render first: the
# render-then-look rule inspects this file, and a PDF left over from a previous
# run must never pass for the output of this one. An explicit output is used by
# the MCP server, which hands Word a private copy of the input but must keep the
# caller-visible destination beside the real file.
if [[ -n "$OUTPUT" ]]; then
    case "${OUTPUT,,}" in
        *.pdf) ;;
        *)
            echo "Error: output must be a .pdf file: $OUTPUT" >&2
            exit 2
            ;;
    esac
    # Resolve a relative output against the caller's directory, as the derived
    # form already is absolute.
    if [[ "$OUTPUT" != /* ]]; then OUTPUT="$PWD/$OUTPUT"; fi
    if [[ -e "$OUTPUT" || -L "$OUTPUT" ]] \
       && [[ "$(realpath -m -- "$OUTPUT" 2>/dev/null || printf '%s' "$OUTPUT")" \
             == "$DOCX_REAL" ]]; then
        echo "Error: refusing to overwrite an input file: $OUTPUT" >&2
        exit 2
    fi
    PDF="$OUTPUT"
else
    DOCX_DIR="$(dirname -- "$DOCX_REAL")"
    DOCX_BASE="$(basename -- "$DOCX_REAL")"
    PDF="$DOCX_DIR/${DOCX_BASE%.*}.pdf"
fi
# Do NOT delete an existing destination up front: the render goes to a unique
# temp that is renamed into place only on success, so a failed conversion must
# leave the operator's previous PDF intact (F049).
# Render to a UNIQUE temp beside the destination, verify THAT file, then rename
# atomically into place: a PowerShell failure left its partial PDF at the
# requested path (F82), and two runs could delete each other's in-flight render
# (F02).
PDF_TMP="${PDF}.tmp.$$.$RANDOM.pdf"
if command -v wslpath >/dev/null 2>&1; then
    PDF_TMP_WIN="$(wslpath -w "$PDF_TMP")"
else
    PDF_TMP_WIN="$(cygpath -w "$PDF_TMP")"
fi
# F133: on WSL every process here is process.platform 'linux'; the Node runner
# can only SIGKILL the Unix process group, which does not reach a Windows
# powershell.exe or the Word/COM server it starts. Record their WINDOWS pids so
# the runner can taskkill.exe them on a timeout. The pid file lives beside the
# output (a path both WSL and Windows can write), so convert it here.
PIDFILE_WIN=""
if [[ -n "${DOCX_MCP_WINDOWS_PID_FILE:-}" ]]; then
    if command -v wslpath >/dev/null 2>&1; then
        PIDFILE_WIN="$(wslpath -w "$DOCX_MCP_WINDOWS_PID_FILE")"
    else
        PIDFILE_WIN="$(cygpath -w "$DOCX_MCP_WINDOWS_PID_FILE")"
    fi
fi
PIDFILE_WIN_PS="${PIDFILE_WIN//\'/\'\'}"
_cleanup_partial() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        rm -f -- "$PDF_TMP"
    fi
}
trap _cleanup_partial EXIT

# Escape the path for a PowerShell single-quoted string: a quote inside such a
# string is written twice. (Interpolating it raw terminated the string early and
# made Word conversion fail with a syntax error for any path containing "'".)
DOCX_WIN_PS="${DOCX_WIN//\'/\'\'}"

# Build the PowerShell script. Single-quoted in bash so nothing is expanded
# here; DOCX_WIN_PS is the same path with that escaping already applied.
PDF_TMP_WIN_PS="${PDF_TMP_WIN//\'/\'\'}"
PS_SCRIPT=$(cat <<EOF
\$ErrorActionPreference = 'Stop'
\$docx = '$DOCX_WIN_PS'
\$pdf  = '$PDF_TMP_WIN_PS'
\$pidFile = '$PIDFILE_WIN_PS'

# Record this PowerShell's Windows PID BEFORE Word starts: if COM activation
# itself hangs, the runner still has a Windows pid to kill.
if (\$pidFile) {
    try { \$PID | Set-Content -LiteralPath \$pidFile -Encoding ascii } catch { }
}

if (-not (Test-Path -LiteralPath \$docx)) {
    Write-Error "Input not found: \$docx"
    exit 1
}

\$word = \$null
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
    # msoAutomationSecurityForceDisable = 3. Word's automation default is
    # msoAutomationSecurityLow ("macros are enabled"), so opening an untrusted
    # submission here would run its macro payload on the operator's host.
    \$word.AutomationSecurity = 3

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
if [[ ! -s "$PDF_TMP" ]]; then
    echo "Error: no PDF was written: $PDF" >&2
    exit 1
fi
# A non-empty file is not a render: a converter that writes one garbage byte
# and exits 0 must not pass a PDF into the visual/PDF stages.
if ! head -c 1024 -- "$PDF_TMP" | grep -aq '%PDF-'; then
    echo "Error: the converter wrote no PDF header: $PDF" >&2
    exit 1
fi
# The EOF marker must be in the PDF's trailer, not merely somewhere in the
# bytes: `grep` over the whole file accepted a truncated/garbage file whose
# text stream happened to contain the marker (the 2026-10-28 audit's F64).
if ! tail -c 2048 -- "$PDF_TMP" | grep -aq '%%EOF'; then
    echo "Error: the converter wrote no PDF trailer (%%EOF): $PDF" >&2
    exit 1
fi
mv -f -- "$PDF_TMP" "$PDF"

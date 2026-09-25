#!/bin/sh
# Run ONE suite the way `run_all.py` runs it — in its own TMPDIR, with its own
# log, status and timing files. Called by the GNU-parallel engine and by the
# built-in Python engine, so both produce identical evidence.
#
#   run_one.sh <suite.py>            environment:
#     PAPER_TEST_RUNDIR   directory for <suite>.log, status/<suite>.rc,
#                       status/<suite>.time and the per-suite tmp/ sandbox
#     PAPER_TEST_WS       the tree under test (defaults to this script's parent)
#     PAPER_TEST_PYTHON   interpreter (defaults to python3)
#
# Exit status is the suite's own, so a caller that does not read the .rc file
# still gets the truth (GNU parallel's joblog, `xargs -p`, a bare `sh -c`).
set -u

suite=$1
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ws=${PAPER_TEST_WS:-$(dirname -- "$here")}
rundir=${PAPER_TEST_RUNDIR:-$(dirname -- "$here")}
python=${PAPER_TEST_PYTHON:-python3}

mkdir -p "$rundir/tmp/$suite" "$rundir/status"
start=$(date +%s)
# PYTHONDONTWRITEBYTECODE: N suites importing the pipeline concurrently all try to
# write the same __pycache__ entry; that is safe, but the tree stays clean (and the
# parallel run a little quieter) if nobody writes it.
TMPDIR="$rundir/tmp/$suite" TMP="$rundir/tmp/$suite" TEMP="$rundir/tmp/$suite" \
PYTHONDONTWRITEBYTECODE=1 \
    "$python" "$ws/.paper_test/$suite" >"$rundir/$suite.log" 2>&1
rc=$?
end=$(date +%s)
printf '%s\n' "$rc" >"$rundir/status/$suite.rc"
printf '%s %s\n' "$start" "$end" >"$rundir/status/$suite.time"
exit "$rc"

#!/usr/bin/env bash
# Export the `paper-refine-test` conda environment as DATA FILES, so it can be
# re-created later (on this machine or another one) without guessing versions.
#
# Usage:
#   bash scripts/export-test-env.sh                    # write ./env/
#   bash scripts/export-test-env.sh --out /somewhere   # write elsewhere
#   PAPER_REFINE_TEST_ENV=my-env bash scripts/export-test-env.sh
#
# What it writes into `env/` (the same shape the neoguider `env/` freeze uses):
#
#   paper-refine-test.freeze.env_export.yml              conda env export (channels + builds)
#   paper-refine-test.freeze.env_export.no_builds.yml    ... --no-builds   (portable pins)
#   paper-refine-test.freeze.env_export.no_channels.yml  ... without the channels block
#   paper-refine-test.freeze.env_export.from_history.yml ... --from-history (minimal, portable)
#   paper-refine-test.requirements.list_e.txt            pip freeze --all (every wheel)
#   paper-refine-test.requirements.list_e_no_pypi.txt    the same, conda-managed lines removed
#   paper-refine-test.requirements.test.txt              the DECLARED test deps + closure
#   README.md                                            which file to use when
#
# `scripts/create-test-env.sh` reads these files: with them present it recreates
# the environment FROM THE EXPORT (no guessing), and without them it falls back
# to `conda create python=3.12` + the two pinned dependencies.
#
# Re-run this script after you change the test dependencies, and commit the
# regenerated files together with that change.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "${HERE}/.." && pwd)"
ENV_NAME="${PAPER_REFINE_TEST_ENV:-paper-refine-test}"
OUT="${WS}/env"
CONDA="${CONDA_EXE:-$(command -v conda || true)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)
      # `set -u` turned a missing value into an unbound-variable crash instead
      # of the script's usage message (F53).
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "error: --out requires a directory argument" >&2
        exit 2
      fi
      OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "error: unknown argument $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${CONDA}" || ! -x "${CONDA}" ]]; then
  echo "error: conda was not found. Install Miniconda/Anaconda, or set CONDA_EXE." >&2
  exit 2
fi

if ! "${CONDA}" run -n "${ENV_NAME}" python -c 'import sys' >/dev/null 2>&1; then
  echo "error: conda environment ${ENV_NAME} does not exist (run scripts/create-test-env.sh)." >&2
  exit 2
fi

mkdir -p "${OUT}"
STEM="${OUT}/${ENV_NAME}"
echo "exporting ${ENV_NAME} -> ${OUT}"

# --- conda side ------------------------------------------------------------
"${CONDA}" env export -n "${ENV_NAME}" > "${STEM}.freeze.env_export.yml"
"${CONDA}" env export -n "${ENV_NAME}" --no-builds > "${STEM}.freeze.env_export.no_builds.yml"
"${CONDA}" env export -n "${ENV_NAME}" --from-history \
  > "${STEM}.freeze.env_export.from_history.yml"

# `conda env export` writes a `prefix:` line naming THIS machine; re-creating
# from a file that hard-codes someone else's home directory is a foot-gun, so
# the PORTABLE files drop it. The full export keeps it: it is the record of the
# machine the freeze was taken on (see env/README.md).
for f in "${STEM}.freeze.env_export.no_builds.yml" \
         "${STEM}.freeze.env_export.from_history.yml"; do
  grep -v '^prefix:' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done

# The no-channels variant: the full export with the whole `channels:` block
# removed, for a box whose channel configuration must not be overridden.
awk '
  /^channels:/ {skip=1; next}
  skip && /^[[:space:]]*-/ {next}
  {skip=0}
  {print}
' "${STEM}.freeze.env_export.yml" > "${STEM}.freeze.env_export.no_channels.yml"

# --- pip side --------------------------------------------------------------
# Every wheel the environment's pip knows about (the full record).
"${CONDA}" run -n "${ENV_NAME}" python -m pip freeze --all 2>/dev/null \
  > "${STEM}.requirements.list_e.txt" || true

# A conda-installed distribution is marked `pypi_0` in `conda list --export`;
# everything else came from pip, so the pip-only list keeps the `pypi_0` entries
# and drops the conda-managed lines.
"${CONDA}" list -n "${ENV_NAME}" --export 2>/dev/null \
  | awk -F= '$3 != "pypi_0" {print tolower($1)}' | tr '_' '-' | sort -u \
  > "${STEM}.conda.packages.txt"
if [[ -s "${STEM}.conda.packages.txt" ]]; then
  awk 'BEGIN{FS="=="} {n=tolower($1); gsub(/_/,"-",n); print n"\t"$0}' \
      "${STEM}.requirements.list_e.txt" \
    | grep -v -F -f <(sed 's/$/\t/' "${STEM}.conda.packages.txt") \
    | cut -f2- > "${STEM}.requirements.list_e_no_pypi.txt" || true
else
  cp "${STEM}.requirements.list_e.txt" "${STEM}.requirements.list_e_no_pypi.txt"
fi
rm -f "${STEM}.conda.packages.txt"

# Sanitise the pip records: a `pip @ file:///home/...` line is a build-machine
# artifact (the conda package's own pip build dir), not something a re-creation
# can or should install. VCS pins (`pkg @ git+https://...`) are kept.
for f in "${STEM}.requirements.list_e.txt" "${STEM}.requirements.list_e_no_pypi.txt"; do
  [[ -f "$f" ]] || continue
  grep -v -E '^pip @ file://|^[A-Za-z0-9_.\-]+ @ file:///home/' "$f" > "$f.tmp" || true
  mv "$f.tmp" "$f"
done

# The DECLARED test dependencies and their transitive closure, at the exact
# installed versions: the reproducible, portable subset that
# `create-test-env.sh` installs. The environment also carries unrelated
# base-image wheels, which the record above keeps and this file leaves out.
# (conda run does not forward its stdin, so the closure is a helper script and
# not an inline heredoc.)
"${CONDA}" run -n "${ENV_NAME}" python "${HERE}/env_test_closure.py" \
  "${STEM}.requirements.test.txt"

# --- README ----------------------------------------------------------------
cat > "${OUT}/README.md" <<EOF
# \`env/\` — the exported test environment

Generated by \`bash scripts/export-test-env.sh\` from the conda environment
\`${ENV_NAME}\`; consumed by \`bash scripts/create-test-env.sh\`, which recreates
the environment from these files instead of guessing versions.

Re-run the export (and commit the result) whenever the test dependencies change.

| file | what it is | use it when |
|---|---|---|
| \`${ENV_NAME}.freeze.env_export.from_history.yml\` | \`conda env export --from-history\`: only the packages explicitly asked for (here \`python=3.12\`) | **the portable, cross-machine choice** — \`create-test-env.sh\` pairs it with \`requirements.test.txt\` |
| \`${ENV_NAME}.requirements.test.txt\` | the DECLARED test dependencies and their full transitive closure, at the exact installed versions | **what \`create-test-env.sh\` installs** — the reproducible, portable subset |
| \`${ENV_NAME}.freeze.env_export.no_builds.yml\` | the full solve, versions pinned, build strings dropped | rebuilding on a different OS/build matrix |
| \`${ENV_NAME}.freeze.env_export.yml\` | the exact export, builds included, plus the \`prefix:\` of the machine it was taken on | reproducing THIS machine byte-for-byte; not portable (drop or rewrite the \`prefix:\` line) |
| \`${ENV_NAME}.freeze.env_export.no_channels.yml\` | the exact export with the \`channels:\` block removed | a box whose channel configuration must not be overridden |
| \`${ENV_NAME}.requirements.list_e.txt\` | \`pip freeze --all\`: every installed wheel at its exact version | the full pip record |
| \`${ENV_NAME}.requirements.list_e_no_pypi.txt\` | the same list with the conda-managed distributions removed | \`pip install\` into an environment whose non-Python packages came from conda |

The environment is small on purpose: the suites are standard-library-only
except \`python-docx\` (DOCX fixtures/scanner; it brings \`lxml\`) and \`openpyxl\`
(the pairwise workbook check).

\`\`\`bash
bash scripts/create-test-env.sh              # create/recreate from these files
bash scripts/create-test-env.sh --recreate   # delete the env first, then recreate
bash scripts/export-test-env.sh              # refresh these files
\`\`\`
EOF

echo "wrote:"
ls -1 "${OUT}" | sed 's/^/  /'

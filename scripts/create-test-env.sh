#!/usr/bin/env bash
# Create (or re-create) the reproducible offline test environment for paper-refine.
#
# Usage:
#   bash scripts/create-test-env.sh              # create it if missing; verify either way
#   bash scripts/create-test-env.sh --recreate   # DELETE it first, then create it again
#   PAPER_REFINE_TEST_ENV=my-paper-refine-test bash scripts/create-test-env.sh
#   PAPER_REFINE_TEST_PREFIX="$PWD/tmp/paper-refine-test" bash scripts/create-test-env.sh
#
# The environment is described by the EXPORTED DATA under `env/` (see
# `scripts/export-test-env.sh` and `env/README.md`):
#
#   env/<name>.freeze.env_export.from_history.yml   what conda must install (python=3.12)
#   env/<name>.requirements.test.txt                the exact pip wheels (test deps + closure)
#
# With those files present the environment is re-created FROM THE EXPORT, so it
# matches the environment the export was taken from instead of whatever the
# channels serve today. Without them the script falls back to
# `conda create python=3.12` plus the two pinned test dependencies, so a fresh
# clone without a refresh export still works.
#
# `--recreate` deletes the existing environment first, which is the supported
# repair for a broken or half-upgraded one. It refuses to delete an environment
# it cannot create again (a sandboxed or read-only conda writes an
# EnvironmentNotWritableError only AFTER the old one is gone), and it never
# targets `base`/`root`.
#
# The suite is stdlib-only except python-docx (the DOCX scanner/parity tests; it
# brings lxml) and openpyxl (the pairwise workbook test). Python 3.12 is what the
# suite is exercised with in this checkout.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "${HERE}/.." && pwd)"
ENV_NAME="${PAPER_REFINE_TEST_ENV:-paper-refine-test}"
PYTHON_VERSION="${PAPER_REFINE_TEST_PYTHON:-3.12}"
ENV_PREFIX="${PAPER_REFINE_TEST_PREFIX:-}"
CONDA="${CONDA_EXE:-$(command -v conda || true)}"
EXPORT_DIR="${PAPER_REFINE_TEST_EXPORT_DIR:-${WS}/env}"
RECREATE=0

for arg in "$@"; do
  case "${arg}" in
    --recreate) RECREATE=1 ;;
    -h|--help) sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "error: unknown argument ${arg}" >&2; exit 2 ;;
  esac
done

if [[ -z "${CONDA}" || ! -x "${CONDA}" ]]; then
  echo "error: conda was not found. Install Miniconda/Anaconda, or set CONDA_EXE." >&2
  exit 2
fi

# A prefix environment is self-contained under the checkout; keep conda's
# package cache there too, so a read-only HOME/conda cache (common in CI or a
# file sandbox) cannot block creation.
if [[ -n "${ENV_PREFIX}" ]]; then
  export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$PWD/tmp/conda-pkgs}"
  export CONDA_ENVS_PATH="${CONDA_ENVS_PATH:-$PWD/tmp/conda-envs}"
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/tmp/pip-cache}"
  mkdir -p "${CONDA_PKGS_DIRS}" "${CONDA_ENVS_PATH}" "${PIP_CACHE_DIR}"
fi

env_exists() {
  if [[ -n "${ENV_PREFIX}" ]]; then
    "${CONDA}" run -p "${ENV_PREFIX}" python -c 'import sys' >/dev/null 2>&1
  else
    "${CONDA}" run -n "${ENV_NAME}" python -c 'import sys' >/dev/null 2>&1
  fi
}

env_python() {
  if [[ -n "${ENV_PREFIX}" ]]; then
    "${CONDA}" run -p "${ENV_PREFIX}" python "$@"
  else
    "${CONDA}" run -n "${ENV_NAME}" python "$@"
  fi
}

FROM_HISTORY="${EXPORT_DIR}/${ENV_NAME}.freeze.env_export.from_history.yml"
REQUIREMENTS="${EXPORT_DIR}/${ENV_NAME}.requirements.test.txt"

# --- 0. choose a target this process can actually write --------------------
# Deleting an environment we cannot re-create is worse than not deleting it.
if [[ -z "${ENV_PREFIX}" ]] && [[ ! -w "$("${CONDA}" info --base)/envs" ]]; then
  ENV_PREFIX="${PWD}/tmp/${ENV_NAME}"
  export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$PWD/tmp/conda-pkgs}"
  export CONDA_ENVS_PATH="${CONDA_ENVS_PATH:-$PWD/tmp/conda-envs}"
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/tmp/pip-cache}"
  mkdir -p "${CONDA_PKGS_DIRS}" "${CONDA_ENVS_PATH}" "${PIP_CACHE_DIR}" \
           "$(dirname "${ENV_PREFIX}")"
  echo "note: $("${CONDA}" info --base)/envs is not writable here (sandboxed or" >&2
  echo "      read-only conda); using the self-contained prefix ${ENV_PREFIX}" >&2
  echo "      and leaving any named environment untouched." >&2
fi

if [[ -z "${ENV_PREFIX}" ]]; then
  case "${ENV_NAME}" in
    base|root)
      echo "error: refusing to manage the conda environment '${ENV_NAME}'; set" >&2
      echo "       PAPER_REFINE_TEST_ENV to a dedicated name." >&2
      exit 2 ;;
  esac
fi

# --- 1. delete the previous environment (only with --recreate) -------------
if [[ "${RECREATE}" -eq 1 ]]; then
  if env_exists; then
    if [[ -n "${ENV_PREFIX}" ]]; then
      echo "removing conda prefix environment ${ENV_PREFIX}"
      "${CONDA}" env remove -y -p "${ENV_PREFIX}"
    else
      echo "removing conda environment ${ENV_NAME}"
      "${CONDA}" env remove -y -n "${ENV_NAME}"
    fi
  else
    echo "no existing environment to remove (${ENV_PREFIX:-${ENV_NAME}})"
  fi
fi

# --- 2. create it (from the export when there is one) ---------------------
if env_exists; then
  echo "conda environment already exists: ${ENV_PREFIX:-${ENV_NAME}}"
elif [[ -f "${FROM_HISTORY}" ]]; then
  echo "creating ${ENV_PREFIX:-${ENV_NAME}} from ${FROM_HISTORY##*/}"
  if [[ -n "${ENV_PREFIX}" ]]; then
    mkdir -p "$(dirname "${ENV_PREFIX}")"
    rm -rf "${ENV_PREFIX}"
    "${CONDA}" env create -y -f "${FROM_HISTORY}" -p "${ENV_PREFIX}"
  else
    "${CONDA}" env create -y -f "${FROM_HISTORY}" -n "${ENV_NAME}"
  fi
else
  echo "creating ${ENV_PREFIX:-${ENV_NAME}} (Python ${PYTHON_VERSION}; no export in " \
       "${EXPORT_DIR}, so the version is not pinned by a freeze file)"
  if [[ -n "${ENV_PREFIX}" ]]; then
    mkdir -p "$(dirname "${ENV_PREFIX}")"
    rm -rf "${ENV_PREFIX}"
    "${CONDA}" create -y -p "${ENV_PREFIX}" "python=${PYTHON_VERSION}"
  else
    "${CONDA}" create -y -n "${ENV_NAME}" "python=${PYTHON_VERSION}"
  fi
fi

# --- 3. install the test dependencies ------------------------------------
if [[ -f "${REQUIREMENTS}" ]]; then
  echo "installing test dependencies from ${REQUIREMENTS##*/}"
  env_python -m pip install --disable-pip-version-check -r "${REQUIREMENTS}"
else
  echo "installing test dependencies (pinned; no ${REQUIREMENTS##*/} to follow)"
  env_python -m pip install --disable-pip-version-check \
    "python-docx==1.2.0" "openpyxl==3.1.5"
fi

# --- 4. prove the environment is usable ----------------------------------
# The verification runs in a fresh process: pass the workspace and the
# EXPECTED version through the environment. Running `paper_pipeline.py` by
# relative name used the caller's cwd and failed when the script was invoked by
# absolute path from elsewhere (F39); the assertion also ignored the documented
# PAPER_REFINE_TEST_PYTHON override (F40).
PAPER_REFINE_TEST_WS="${WS}" PAPER_REFINE_TEST_EXPECT_PYTHON="${PYTHON_VERSION}" \
env_python - <<'PYVERIFY'
import os
import subprocess
import sys

import docx
import lxml
import openpyxl

ws = os.environ.get("PAPER_REFINE_TEST_WS") or os.getcwd()
want = tuple(int(p) for p in
             (os.environ.get("PAPER_REFINE_TEST_EXPECT_PYTHON") or "3.12").split(".")[:2])
assert sys.version_info[:2] == want, (
    f"expected Python {'.'.join(str(p) for p in want)}, got {sys.version.split()[0]}")
print(f"python {sys.version.split()[0]}; python-docx {docx.__version__}; "
      f"openpyxl {openpyxl.__version__}; lxml {lxml.__version__}")
out = subprocess.run([sys.executable, str(os.path.join(ws, "paper_pipeline.py")), "--version"],
                     cwd=ws, capture_output=True, text=True)
assert out.returncode == 0, out.stderr
print("pipeline:", out.stdout.strip())
PYVERIFY

if [[ -n "${ENV_PREFIX}" ]]; then
  RUN=("${CONDA}" run -p "${ENV_PREFIX}")
  ACTIVATE="${CONDA} activate ${ENV_PREFIX}"
  ENV_LABEL="${ENV_PREFIX}"
else
  RUN=("${CONDA}" run -n "${ENV_NAME}")
  ACTIVATE="${CONDA} activate ${ENV_NAME}"
  ENV_LABEL="${ENV_NAME}"
fi

cat <<EOF

Environment ready: ${ENV_LABEL}

Run the full regression suite with:
  ${RUN[*]} python .paper_test/run_all.py --engine python -j 32

Or activate it first:
  ${ACTIVATE}
  python .paper_test/run_all.py --engine python -j 32

Refresh the exported freeze files after changing a test dependency:
  bash scripts/export-test-env.sh
EOF

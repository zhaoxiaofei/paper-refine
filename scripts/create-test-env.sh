#!/usr/bin/env bash
# Create the reproducible offline test environment for paper-refine.
#
# Usage:
#   bash scripts/create-test-env.sh
#   PAPER_REFINE_TEST_ENV=my-paper-refine-test bash scripts/create-test-env.sh
#   PAPER_REFINE_TEST_PREFIX="$PWD/tmp/paper-refine-test" bash scripts/create-test-env.sh
#
# The suite is stdlib-only except for python-docx (the DOCX scanner/parity
# tests) and openpyxl (the pairwise workbook test).  Python 3.12 is what the
# suite is exercised with in this checkout.
#
# A named conda environment is the default.  If conda cannot write its normal
# environment directories (for example inside a file sandbox), the script
# falls back to a local prefix environment under ./tmp/.
set -euo pipefail

ENV_NAME="${PAPER_REFINE_TEST_ENV:-paper-refine-test}"
PYTHON_VERSION="${PAPER_REFINE_TEST_PYTHON:-3.12}"
ENV_PREFIX="${PAPER_REFINE_TEST_PREFIX:-}"
CONDA="${CONDA_EXE:-$(command -v conda || true)}"

# A prefix environment is self-contained under the checkout; keep conda's
# package cache there too, so a read-only HOME/conda cache (common in CI or a
# file sandbox) cannot block creation.
if [[ -n "${ENV_PREFIX}" ]]; then
  export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$PWD/tmp/conda-pkgs}"
  export CONDA_ENVS_PATH="${CONDA_ENVS_PATH:-$PWD/tmp/conda-envs}"
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/tmp/pip-cache}"
  mkdir -p "${CONDA_PKGS_DIRS}" "${CONDA_ENVS_PATH}" "${PIP_CACHE_DIR}"
fi

if [[ -z "${CONDA}" || ! -x "${CONDA}" ]]; then
  echo "error: conda was not found. Install Miniconda/Anaconda, or set CONDA_EXE." >&2
  exit 2
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

if ! env_exists; then
  if [[ -n "${ENV_PREFIX}" ]]; then
    mkdir -p "$(dirname "${ENV_PREFIX}")"
    echo "creating conda prefix environment ${ENV_PREFIX} (Python ${PYTHON_VERSION})"
    "${CONDA}" create -y -p "${ENV_PREFIX}" "python=${PYTHON_VERSION}"
  else
    echo "creating conda environment ${ENV_NAME} (Python ${PYTHON_VERSION})"
    if ! "${CONDA}" create -y -n "${ENV_NAME}" "python=${PYTHON_VERSION}"; then
      ENV_PREFIX="$PWD/tmp/${ENV_NAME}"
      export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$PWD/tmp/conda-pkgs}"
      export CONDA_ENVS_PATH="${CONDA_ENVS_PATH:-$PWD/tmp/conda-envs}"
      export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/tmp/pip-cache}"
      mkdir -p "${CONDA_PKGS_DIRS}" "${CONDA_ENVS_PATH}" "${PIP_CACHE_DIR}"         "$(dirname "${ENV_PREFIX}")"
      echo "named environment creation failed; using local prefix ${ENV_PREFIX}" >&2
      "${CONDA}" create -y -p "${ENV_PREFIX}" "python=${PYTHON_VERSION}"
    fi
  fi
else
  echo "conda environment already exists: ${ENV_PREFIX:-${ENV_NAME}}"
fi

echo "installing test dependencies"
env_python -m pip install --disable-pip-version-check \
  "python-docx==1.2.0" "openpyxl==3.1.5"

env_python - <<'PY'
import docx, openpyxl, lxml
print(f"python-docx {docx.__version__}; openpyxl {openpyxl.__version__}; lxml {lxml.__version__}")
PY

if [[ -n "${ENV_PREFIX}" ]]; then
  RUN=(conda run -p "${ENV_PREFIX}")
  ACTIVATE="conda activate ${ENV_PREFIX}"
  ENV_LABEL="${ENV_PREFIX}"
else
  RUN=(conda run -n "${ENV_NAME}")
  ACTIVATE="conda activate ${ENV_NAME}"
  ENV_LABEL="${ENV_NAME}"
fi

cat <<EOF

Environment ready: ${ENV_LABEL}

Run the full regression suite with:
  ${RUN[*]} python .paper_test/run_all.py --engine python -j 8

Or activate it first:
  ${ACTIVATE}
  python .paper_test/run_all.py --engine python -j 8
EOF

#!/usr/bin/env bash
# Create (or re-create) the reproducible offline test environment for paper-refine.
#
# Usage:
#   bash scripts/create-test-env.sh              # create it if missing; verify either way
#   bash scripts/create-test-env.sh --recreate   # DELETE it first, then create it again
#   bash scripts/create-test-env.sh --recreate --force-delete-prefix=<path>
#        # also delete a NON-EMPTY directory that is not a conda/venv env
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
# ENV_NAME is joined into the fallback prefix and into the export filenames: a
# `../` (or an absolute value) escapes the checkout. export-test-env.sh already
# validates it; the two scripts that consume the name must too.
if [[ -z "${ENV_NAME}" || "${ENV_NAME}" == "." || "${ENV_NAME}" == ".." || "${ENV_NAME}" == */* ]]; then
  echo "error: PAPER_REFINE_TEST_ENV must be one filename component: ${ENV_NAME}" >&2
  exit 2
fi
PYTHON_VERSION="${PAPER_REFINE_TEST_PYTHON:-3.12}"
ENV_PREFIX="${PAPER_REFINE_TEST_PREFIX:-}"
CONDA="${CONDA_EXE:-$(command -v conda || true)}"
EXPORT_DIR="${PAPER_REFINE_TEST_EXPORT_DIR:-${WS}/env}"
RECREATE=0
# An explicit opt-in for deleting a non-empty directory that is not a
# conda/venv prefix. A typo in PAPER_REFINE_TEST_PREFIX must never turn
# `--recreate` into `rm -rf $HOME` (F08-20261126).
FORCE_DELETE_PREFIX=""

for arg in "$@"; do
  case "${arg}" in
    --recreate) RECREATE=1 ;;
    --force-delete-prefix=*) FORCE_DELETE_PREFIX="${arg#*=}" ;;
    -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
  export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$WS/tmp/conda-pkgs}"
  export CONDA_ENVS_PATH="${CONDA_ENVS_PATH:-$WS/tmp/conda-envs}"
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$WS/tmp/pip-cache}"
  mkdir -p "${CONDA_PKGS_DIRS}" "${CONDA_ENVS_PATH}" "${PIP_CACHE_DIR}"
fi

env_exists() {
  if [[ -n "${ENV_PREFIX}" ]]; then
    "${CONDA}" run -p "${ENV_PREFIX}" python -c 'import sys' >/dev/null 2>&1
  else
    "${CONDA}" run -n "${ENV_NAME}" python -c 'import sys' >/dev/null 2>&1
  fi
}

# EXISTENCE, not runnability: a half-created environment has no working Python,
# so `env_exists` reports it absent and `--recreate` used to skip the removal,
# leaving `conda env create` to fail on the registered prefix.
env_registered() {
  if [[ -n "${ENV_PREFIX}" ]]; then
    [[ -e "${ENV_PREFIX}" ]]
  else
    # A named environment is listed as `.../envs/<name>`, never as `/<name>`:
    # the old `grep -Fq "\"/${ENV_NAME}\""` could only match a root-level env
    # path, so a normal named environment (including a broken one) was
    # invisible and `--recreate` skipped its removal. Parse the JSON and
    # compare each listed path's LAST component -- the env's name. A namesake
    # directory elsewhere in the path (e.g. a pkgs entry) does not match.
    local listed
    listed="$("${CONDA}" env list --json 2>/dev/null || true)"
    if command -v python3 >/dev/null 2>&1; then
      printf '%s' "${listed}" | python3 -c '
import json
import re
import sys
name = sys.argv[1]
try:
    envs = json.load(sys.stdin).get("envs") or []
except Exception:
    sys.exit(1)
sys.exit(0 if any(re.split(r"[\\/]", str(p))[-1] == name for p in envs) else 1)
' "${ENV_NAME}"
    else
      # No interpreter to parse the JSON: the suffix form is still correct for
      # a path whose last component is the environment name.
      printf '%s' "${listed}" | grep -Fq "/${ENV_NAME}\""
    fi
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
  # The documented fallback is a prefix under the CHECKOUT (`../tmp/`), not the
  # caller's cwd: install_dependencies.sh invokes this script without cd, and a
  # read-only caller cwd must not break the self-contained environment.
  ENV_PREFIX="${WS}/tmp/${ENV_NAME}"
  export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$WS/tmp/conda-pkgs}"
  export CONDA_ENVS_PATH="${CONDA_ENVS_PATH:-$WS/tmp/conda-envs}"
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$WS/tmp/pip-cache}"
  mkdir -p "${CONDA_PKGS_DIRS}" "${CONDA_ENVS_PATH}" "${PIP_CACHE_DIR}" \
           "$(dirname "${ENV_PREFIX}")"
  echo "note: $("${CONDA}" info --base)/envs is not writable here (sandboxed or" >&2
  echo "      read-only conda); using the self-contained prefix ${ENV_PREFIX}" >&2
  echo "      and leaving any named environment untouched." >&2
fi

# The policy applies to the RESOLVED target, not only to the no-prefix case:
# an explicit PAPER_REFINE_TEST_PREFIX naming base/root (or a path whose last
# component is base/root) used to reach `conda env remove -y -p` unchecked.
case "$(basename -- "${ENV_PREFIX:-${ENV_NAME}}")" in
  base|root)
    echo "error: refusing to manage the conda environment '${ENV_PREFIX:-${ENV_NAME}}'; set" >&2
    echo "       PAPER_REFINE_TEST_ENV to a dedicated name." >&2
    exit 2 ;;
esac

# --- 1. delete the previous environment (only with --recreate) -------------
if [[ "${RECREATE}" -eq 1 ]]; then
  if [[ -n "${ENV_PREFIX}" && -e "${ENV_PREFIX}" \
        && ! -e "${ENV_PREFIX}/conda-meta/history" ]]; then
    # The prefix exists but is not a conda environment (an empty directory, a
    # venv, or the debris of an interrupted install). `conda env remove`
    # refuses it with EnvironmentLocationNotFound, and `set -e` used to abort
    # --recreate before the rm -rf below and before any recreation -- the
    # documented "supported repair" could never repair this state (F037).
    # conda's own environment test is conda-meta/history; with no such file
    # there is nothing conda can remove.
    #
    # But `rm -rf` on ANY non-empty directory was reachable by a typo'd or
    # reused PAPER_REFINE_TEST_PREFIX -- including $HOME. Only a directory with
    # nothing to lose (empty), a venv (pyvenv.cfg), a symlink (rm removes the
    # link, not its target), or an explicitly forced path may be deleted.
    _prefix_safe=0
    if [[ -L "${ENV_PREFIX}" ]]; then
      _prefix_safe=1
    elif [[ -d "${ENV_PREFIX}" && -f "${ENV_PREFIX}/pyvenv.cfg" ]]; then
      _prefix_safe=1
    elif [[ -d "${ENV_PREFIX}" ]]; then
      # Accept emptiness only when find itself succeeds: a missing find, a BSD
      # find without -mindepth/-maxdepth, or a permission error used to yield
      # empty output and re-enable rm -rf on a non-empty directory (F011).
      if _find_out="$(find "${ENV_PREFIX}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)"; then
        if [[ -z "${_find_out}" ]]; then
          _prefix_safe=1
        fi
      fi
    elif [[ -n "${FORCE_DELETE_PREFIX}" ]]; then
      _force="${FORCE_DELETE_PREFIX%/}"
      _target="${ENV_PREFIX%/}"
      if [[ -d "${_force}" ]]; then _force="$(cd "${_force}" && pwd -P)"; fi
      if [[ -d "${_target}" ]]; then _target="$(cd "${_target}" && pwd -P)"; fi
      if [[ "${_force}" == "${_target}" ]]; then
        _prefix_safe=1
      else
        echo "error: --force-delete-prefix names ${FORCE_DELETE_PREFIX}, not the" >&2
        echo "       resolved prefix ${ENV_PREFIX}" >&2
        exit 2
      fi
    fi
    if [[ "${_prefix_safe}" -ne 1 ]]; then
      echo "error: refusing to delete the non-empty, non-conda directory" >&2
      echo "       ${ENV_PREFIX}; set PAPER_REFINE_TEST_PREFIX to a dedicated" >&2
      echo "       environment path, or pass an explicit" >&2
      echo "       --force-delete-prefix=${ENV_PREFIX} if you are certain." >&2
      exit 2
    fi
    if [[ "$(cd "${ENV_PREFIX}" 2>/dev/null && pwd -P || printf '%s' "${ENV_PREFIX}")" == "/" ]]; then
      echo "error: refusing to delete /; set PAPER_REFINE_TEST_PREFIX to an" >&2
      echo "       environment path" >&2
      exit 2
    fi
    echo "removing non-conda directory at the prefix ${ENV_PREFIX}"
    rm -rf -- "${ENV_PREFIX}"
  elif env_exists || env_registered; then
    if ! env_exists; then
      echo "removing existing-but-broken environment (its Python does not run):" \
           "${ENV_PREFIX:-${ENV_NAME}}"
    fi
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
elif env_registered; then
  # A prefix that exists but whose Python cannot start: `conda env create`
  # would collide with the registered environment instead of repairing it.
  echo "error: ${ENV_PREFIX:-${ENV_NAME}} exists but its Python does not run;" >&2
  echo "       rerun with --recreate to remove and rebuild it." >&2
  exit 1
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

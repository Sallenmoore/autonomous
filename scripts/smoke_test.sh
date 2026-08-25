#!/usr/bin/env bash
# Post-release smoke test for autonomous-app on PyPI.
#
# Used by:
#   - .github/workflows/release-smoke.yml (CI public-audit layer)
#   - the autonomous-prod local agent (continuous post-release watcher)
#
# Usage:
#   ./scripts/smoke_test.sh             # smokes the version declared in src/autonomous/__init__.py
#   ./scripts/smoke_test.sh 0.3.128     # smokes a specific version
#
# Env:
#   SMOKE_CONTAINER  # if set (e.g. "python:3.13-slim"), runs install + import
#                    # inside `docker run --rm <image>` instead of a host venv.
#                    # Useful for hosts with a broken local Python (pyenv
#                    # missing _ctypes / libffi-dev, etc.) and for matching
#                    # the CI matrix Python version exactly.
#
# Behavior:
#   - Without SMOKE_CONTAINER: creates an isolated host venv, pip-installs
#     autonomous-app at the resolved version with retries (PyPI propagation
#     lag), and imports the public top-level symbols. The install is always
#     --no-cache-dir: see the retry loop's comment (#244).
#   - With SMOKE_CONTAINER: same flow inside an ephemeral container; bypasses
#     host Python entirely.
#
# Exit:
#   0 on success.
#   non-zero on failure, with the last line of stderr formatted as a
#   parseable signature for the prod agent's issue-fingerprinting:
#       SIGNATURE: <stage>:<error_class>:<location>

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INIT_FILE="${ROOT}/src/autonomous/__init__.py"

if [ "$#" -ge 1 ]; then
  VERSION="$1"
else
  VERSION=$(grep -E '^__version__\s*=' "${INIT_FILE}" | head -1 | sed -E "s/.*=\s*[\"'](.*)[\"'].*/\1/")
fi

if [ -z "${VERSION}" ]; then
  echo "❌ Could not resolve version from ${INIT_FILE}" >&2
  echo "SIGNATURE: setup:VersionResolveError:${INIT_FILE}" >&2
  exit 1
fi

# --- Container mode (opt-in via SMOKE_CONTAINER) -----------------------------
# Bypasses host Python entirely. The container is ephemeral (--rm); on retry
# the install is repeated inside a fresh container — acceptable cost since
# retries are rare and only fire when PyPI propagation lags.
#
# Phase marker `__INSTALL_OK__` on stderr distinguishes install failure from
# import failure for the SIGNATURE dedup (host-venv path gets this for free
# via separate bash commands; container path emits a marker between phases).
if [ -n "${SMOKE_CONTAINER:-}" ]; then
  echo "🔎 Smoke-testing autonomous-app==${VERSION} (container ${SMOKE_CONTAINER})..."

  if ! command -v docker >/dev/null 2>&1; then
    echo "❌ SMOKE_CONTAINER set but docker not on PATH" >&2
    echo "SIGNATURE: setup:DockerMissingError:" >&2
    exit 1
  fi

  TMPDIR=$(mktemp -d)
  trap 'rm -rf "${TMPDIR}"' EXIT
  SMOKE_ERR="${TMPDIR}/smoke.err"
  IMPORT_PY="${TMPDIR}/smoke_import.py"

  cat > "${IMPORT_PY}" <<'PYSCRIPT'
import os
import autonomous
import autonomous.ai
import autonomous.auth
import autonomous.db
import autonomous.logger
import autonomous.model
import autonomous.storage
import autonomous.taskrunner
from autonomous import log  # noqa: F401
expected = os.environ["EXPECTED_VERSION"]
got = getattr(autonomous, "__version__", None)
if got != expected:
    raise AssertionError(f"Version mismatch: expected {expected!r}, got {got!r}")
print(f"✅ smoke OK: autonomous-app=={got}")
PYSCRIPT

  SMOKE_OK=0
  for attempt in 1 2 3 4 5; do
    if docker run --rm -i \
         -e EXPECTED_VERSION="${VERSION}" \
         -v "${IMPORT_PY}:/tmp/smoke_import.py:ro" \
         "${SMOKE_CONTAINER}" sh -c "
           set -e
           pip install --quiet --upgrade pip
           pip install --quiet --no-cache-dir 'autonomous-app[all]==${VERSION}'
           printf '__INSTALL_OK__\n' >&2
           exec python /tmp/smoke_import.py
         " 2> "${SMOKE_ERR}"; then
      SMOKE_OK=1
      break
    fi
    # Past install but import failed — no retry, error is deterministic.
    if grep -q '__INSTALL_OK__' "${SMOKE_ERR}"; then
      break
    fi
    echo "  install attempt ${attempt}/5 failed; sleeping 30s..." >&2
    sleep 30
  done

  if [ "${SMOKE_OK}" -eq 1 ]; then
    echo "SIGNATURE: ok"
    exit 0
  fi

  if ! grep -q '__INSTALL_OK__' "${SMOKE_ERR}"; then
    echo "❌ pip install autonomous-app[all]==${VERSION} failed after 5 attempts" >&2
    cat "${SMOKE_ERR}" >&2
    echo "SIGNATURE: install:PipInstallError:autonomous-app[all]==${VERSION}" >&2
    exit 1
  fi

  echo "❌ Import smoke failed" >&2
  cat "${SMOKE_ERR}" >&2
  err_class=$(grep -E '^[A-Z][a-zA-Z]+(Error|Exception):' "${SMOKE_ERR}" | tail -1 | cut -d: -f1)
  err_class=${err_class:-ImportSmokeError}
  err_loc=$(grep -E '^\s*File "' "${SMOKE_ERR}" | tail -1 | sed -E 's/.*File "([^"]+)", line ([0-9]+).*/\1:\2/')
  err_loc=$(echo "${err_loc}" | sed -E 's|.*/site-packages/||')
  err_loc=${err_loc:-unknown}
  echo "SIGNATURE: import:${err_class}:${err_loc}" >&2
  exit 1
fi
# --- end container mode ------------------------------------------------------

# Resolve interpreter — GH Actions runners expose `python`, but bare
# hosts (Fedora/Ubuntu) typically only have `python3`. Pick whichever exists.
if command -v python >/dev/null 2>&1; then
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "❌ No python or python3 on PATH" >&2
  echo "SIGNATURE: setup:NoPythonError:" >&2
  exit 1
fi

echo "🔎 Smoke-testing autonomous-app==${VERSION} (using ${PY})..."

TMPVENV=$(mktemp -d)
trap 'rm -rf "${TMPVENV}"' EXIT
"${PY}" -m venv "${TMPVENV}"
# shellcheck disable=SC1091
source "${TMPVENV}/bin/activate"
pip install --quiet --upgrade pip

INSTALL_ERR="${TMPVENV}/install.err"
INSTALL_OK=0
# Install with [all] extras — represents how consumers actually use the
# package. A bare `pip install autonomous-app` may surface gaps in the
# core requirements.txt (e.g. transitive numpy needs), but those are
# separate library bugs to file via the normal issue flow, not smoke
# concerns.
#
# --no-cache-dir is load-bearing, not hygiene (#244). pip caches the SIMPLE
# INDEX PAGE, and smoke runs seconds after `twine upload` returns — so an
# attempt that races the index caches a listing without the new version,
# and every later attempt reads that cache and fails identically. The
# retry loop below is then structurally unable to recover: it re-asks a
# cache, not PyPI. That turned a seconds-long race into a persistent
# "released and immediately broken" false alarm (halt-trigger #5) on
# 0.3.177, where the package was live and indexed the whole time. A smoke
# test wants a cold resolve by definition; the venv is throwaway anyway.
for attempt in 1 2 3 4 5; do
  if pip install --quiet --no-cache-dir "autonomous-app[all]==${VERSION}" 2> "${INSTALL_ERR}"; then
    INSTALL_OK=1
    break
  fi
  echo "  install attempt ${attempt}/5 failed; sleeping 30s..."
  sleep 30
done

if [ "${INSTALL_OK}" -ne 1 ]; then
  echo "❌ pip install autonomous-app[all]==${VERSION} failed after 5 attempts" >&2
  cat "${INSTALL_ERR}" >&2
  echo "SIGNATURE: install:PipInstallError:autonomous-app[all]==${VERSION}" >&2
  exit 1
fi

IMPORT_ERR="${TMPVENV}/import.err"
# Use the venv's interpreter — `python` always exists inside a venv even
# when the host had only python3. Smoke imports each top-level subpackage
# to detect package-structure breakage; avoids depending on which symbols
# are re-exported (those vary by version and aren't part of the smoke
# contract — broken submodule imports usually mean missing files in the
# wheel, broken `__init__.py`, or a transitive import failure).
if ! "${TMPVENV}/bin/python" - 2> "${IMPORT_ERR}" <<PY
import autonomous
import autonomous.ai
import autonomous.auth
import autonomous.db
import autonomous.logger
import autonomous.model
import autonomous.storage
import autonomous.taskrunner
from autonomous import log
expected = "${VERSION}"
got = getattr(autonomous, "__version__", None)
if got != expected:
    raise AssertionError(f"Version mismatch: expected {expected!r}, got {got!r}")
print(f"✅ smoke OK: autonomous-app=={got}")
PY
then
  echo "❌ Import smoke failed" >&2
  cat "${IMPORT_ERR}" >&2
  err_class=$(grep -E '^[A-Z][a-zA-Z]+(Error|Exception):' "${IMPORT_ERR}" | tail -1 | cut -d: -f1)
  err_class=${err_class:-ImportSmokeError}
  # Extract last frame, strip ephemeral venv path so the signature is stable
  # across runs (dedup key for the prod agent's issue lifecycle).
  err_loc=$(grep -E '^\s*File "' "${IMPORT_ERR}" | tail -1 | sed -E 's/.*File "([^"]+)", line ([0-9]+).*/\1:\2/')
  err_loc=$(echo "${err_loc}" | sed -E 's|.*/site-packages/||')
  err_loc=${err_loc:-unknown}
  echo "SIGNATURE: import:${err_class}:${err_loc}" >&2
  exit 1
fi

echo "SIGNATURE: ok"

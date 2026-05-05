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
# Behavior:
#   - Creates an isolated venv (so the caller's env is untouched).
#   - pip-installs autonomous-app at the resolved version, with retries — PyPI
#     index propagation can lag a few minutes after a fresh upload.
#   - Imports the public top-level symbols.
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

echo "🔎 Smoke-testing autonomous-app==${VERSION}..."

TMPVENV=$(mktemp -d)
trap 'rm -rf "${TMPVENV}"' EXIT
python -m venv "${TMPVENV}"
# shellcheck disable=SC1091
source "${TMPVENV}/bin/activate"
pip install --quiet --upgrade pip

INSTALL_ERR="${TMPVENV}/install.err"
INSTALL_OK=0
for attempt in 1 2 3 4 5; do
  if pip install --quiet "autonomous-app==${VERSION}" 2> "${INSTALL_ERR}"; then
    INSTALL_OK=1
    break
  fi
  echo "  install attempt ${attempt}/5 failed; sleeping 30s..."
  sleep 30
done

if [ "${INSTALL_OK}" -ne 1 ]; then
  echo "❌ pip install autonomous-app==${VERSION} failed after 5 attempts" >&2
  cat "${INSTALL_ERR}" >&2
  echo "SIGNATURE: install:PipInstallError:autonomous-app==${VERSION}" >&2
  exit 1
fi

IMPORT_ERR="${TMPVENV}/import.err"
if ! python - 2> "${IMPORT_ERR}" <<'PY'
import autonomous
from autonomous.ai import TextAgent, JSONAgent, ImageAgent, AudioAgent
from autonomous.db import db_sync
from autonomous.auth import AutoAuth
from autonomous import log
print(f"✅ smoke OK: autonomous-app=={autonomous.__version__}")
PY
then
  echo "❌ Import smoke failed" >&2
  cat "${IMPORT_ERR}" >&2
  err_class=$(grep -E '^[A-Z][a-zA-Z]+(Error|Exception):' "${IMPORT_ERR}" | tail -1 | cut -d: -f1)
  err_class=${err_class:-ImportSmokeError}
  err_loc=$(grep -E '^\s*File "' "${IMPORT_ERR}" | tail -1 | sed -E 's/.*File "([^"]+)", line ([0-9]+).*/\1:\2/')
  err_loc=${err_loc:-unknown}
  echo "SIGNATURE: import:${err_class}:${err_loc}" >&2
  exit 1
fi

echo "SIGNATURE: ok"

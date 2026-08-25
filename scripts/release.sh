#!/usr/bin/env bash
# Release workflow for the autonomous library itself.
#
# Run from the repo root (or anywhere — the script resolves its own path):
#   ./scripts/release.sh
#
# Produces:
#   1. New patch version committed to autonomous's `main` branch.
#   2. A new wheel uploaded to PyPI via twine (delegated to `make package`).
#
# Consumers (e.g. StoryTeller) update their version pin separately — this
# script does not know or care about them. After it finishes, run the
# consumer's bump-autonomous.sh (or equivalent) with the printed version.
#
# Preconditions:
#   - On `main`, fast-forwarded to origin/main, working tree clean.
#   - `~/.pypirc` (or TWINE_USERNAME / TWINE_PASSWORD) present.
#   - SSH key loaded so `git push origin main` succeeds.
#
# History note: this script replaces phases 1–5 of the old
# `scripts/autonomous_deploy.sh` that lived in the StoryTeller tree. The
# tabs/spaces bug that script worked around in autonomous's makefile
# `package` target was fixed in PR #7, so we now delegate build + upload
# to `make package` instead of re-implementing it.

set -euo pipefail

# shellcheck source=scripts/treepaths.sh
. "$(dirname "$0")/treepaths.sh"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INIT_FILE="${ROOT}/src/autonomous/__init__.py"
# The name on PyPI, which is NOT the import name (`autonomous`).
PACKAGE_NAME="autonomous-app"

cd "$ROOT"

# --- 0. Preflight -----------------------------------------------------------

echo "🔎 Preflight..."

branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$branch" != "main" ]]; then
  echo "❌ On '$branch', expected 'main'. Aborting." >&2
  echo "    Run: git checkout main && git pull --ff-only" >&2
  exit 1
fi

# Working tree must be clean — release commits should be the only diff.
if [[ -n "$(git status --porcelain)" ]]; then
  echo "❌ Working tree has uncommitted changes. Aborting." >&2
  git status --short >&2
  exit 1
fi

# Local main must be at origin/main (fast-forwarded). Ahead-of-remote is
# also fatal — we don't want to silently rewrite remote history.
git fetch origin --quiet
local_sha=$(git rev-parse HEAD)
remote_sha=$(git rev-parse origin/main)
if [[ "$local_sha" != "$remote_sha" ]]; then
  echo "❌ Local main (${local_sha:0:7}) differs from origin/main (${remote_sha:0:7})." >&2
  echo "    Run: git pull --ff-only" >&2
  exit 1
fi

# PyPI creds (twine reads either ~/.pypirc or env vars).
if [[ ! -f "${HOME}/.pypirc" ]] && [[ -z "${TWINE_USERNAME:-}" ]]; then
  echo "❌ No ~/.pypirc and no TWINE_USERNAME set. Aborting before any state change." >&2
  exit 1
fi

# --- 1. Compute next version -----------------------------------------------

NEW_VERSION=$(python3 - <<PY
import re
with open("${INIT_FILE}") as f:
    content = f.read()
m = re.search(r'__version__\s*=\s*[\"\'](\d+\.\d+\.\d+)[\"\']', content)
if not m:
    raise SystemExit("could not find __version__ in ${INIT_FILE}")
parts = [int(x) for x in m.group(1).split('.')]
parts[2] += 1
print("{}.{}.{}".format(*parts))
PY
)

echo "📈 Bumping autonomous to ${NEW_VERSION}"

# --- 1b. Refuse a version PyPI already has ---------------------------------
# `make package` uploads with `twine upload --skip-existing`, which turns a
# collision into a SILENT no-op: twine exits 0, this script commits, pushes
# and prints ✅, and PyPI never got the artifact. Checked here, before any
# state change, per this script's abort-early design. A `2` means PyPI
# could not be read at all — warn and continue rather than block a release
# on a transient index outage; the post-upload gate is the real assertion.

PYPI_CHECK="${ROOT}/scripts/pypi_release_check.py"

echo "🔎 Checking PyPI does not already have ${NEW_VERSION}..."
set +e
python3 "${PYPI_CHECK}" "${PACKAGE_NAME}" "${NEW_VERSION}" --assert-absent
pypi_rc=$?
set -e
if [[ $pypi_rc -eq 1 ]]; then
  echo "    Nothing has changed yet. Pick an unused version and re-run." >&2
  exit 1
fi

# --- 2. Write the version bump ---------------------------------------------

python3 - <<PY
import re
path = "${INIT_FILE}"
with open(path) as f:
    content = f.read()
content = re.sub(
    r"(__version__\s*=\s*[\"'])(\d+\.\d+\.\d+)([\"'])",
    r"\g<1>${NEW_VERSION}\g<3>",
    content,
)
with open(path, "w") as f:
    f.write(content)
PY

# --- 3. Build + check + upload (delegate to make) --------------------------
# `make package` runs: clean → install build deps → build → twine check →
# twine upload. If any step fails, we abort BEFORE pushing the version
# bump anywhere — the only state change so far is the modified __init__.py
# which `git checkout` can revert.

echo "📦 Running 'make package'..."
if ! make package; then
  echo "❌ 'make package' failed. Reverting version bump and aborting." >&2
  git checkout -- "${INIT_FILE}"
  exit 1
fi

# --- 3b. Confirm the artifact landed (ADVISORY — never reverts) -------------
# The whole point of the script is that a version reached PyPI, so say so out
# loud instead of inferring it from twine's exit code.
#
# This is advisory ON PURPOSE, and the distinction is load-bearing. By this
# point `make package` has exited 0, which means twine uploaded — the bytes
# are on PyPI whether or not the JSON index has caught up yet. PyPI's index
# lags a successful upload by seconds to minutes (this repo has hit it twice:
# the release-smoke 404 flake, and 0.3.176, where the first version of THIS
# check read a stale index, declared the release failed, and reverted the
# bump — leaving PyPI holding a version the repo denied shipping. That is
# precisely the divergence the gate exists to prevent, manufactured by the
# gate). So the safe direction after a successful upload is always to RECORD
# the version, never to revert it.
#
# The real protection against a silent non-release is the `--assert-absent`
# pre-flight above, which runs before anything has changed and does abort.

echo "🔎 Confirming ${NEW_VERSION} is on PyPI..."
set +e
python3 "${PYPI_CHECK}" "${PACKAGE_NAME}" "${NEW_VERSION}" \
  --assert-present --attempts 6 --delay 10
pypi_rc=$?
set -e
if [[ $pypi_rc -ne 0 ]]; then
  echo "⚠️  Could not confirm ${NEW_VERSION} on PyPI within ~60s." >&2
  echo "    twine reported a successful upload, so the version bump is being" >&2
  echo "    committed anyway — reverting here would put the repo BEHIND what" >&2
  echo "    is published. Verify manually:" >&2
  echo "    https://pypi.org/project/${PACKAGE_NAME}/${NEW_VERSION}/" >&2
fi

# --- 4. Commit + push main -------------------------------------------------

echo "💾 Committing version bump..."
git commit -am "Bump autonomous version to ${NEW_VERSION}"

echo "⬆️  Pushing origin/main..."
git push origin main

# --- 5. Done ---------------------------------------------------------------

cat <<EOF

✅ autonomous v${NEW_VERSION} released to PyPI and origin/main.

Next: in each consumer repo, bump the autonomous-app pin to >=${NEW_VERSION}.
For StoryTeller, that means:
   cd "$(tree_path storyteller dev 2>/dev/null || echo /opt/projects/storyteller-dev)" && ./scripts/bump-autonomous.sh ${NEW_VERSION}
EOF

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

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INIT_FILE="${ROOT}/src/autonomous/__init__.py"

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
   cd /opt/projects/storyteller-dev && ./scripts/bump-autonomous.sh ${NEW_VERSION}
EOF

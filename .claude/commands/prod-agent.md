---
description: Run one iteration of the autonomous-prod release+smoke loop
---

You are the **autonomous-prod** agent. Run **exactly one iteration** of the release+smoke protocol below, then **stop** and wait for the next user command. Do NOT loop. Do NOT poll.

See `CLAUDE.md` § "Three-Agent Pipeline" for the broader doctrine (release ownership, two-layer smoke design, halt triggers). The numbered steps here are the executable protocol.

## Issue tracker = GitHub

The canonical PR target and issue tracker for `autonomous` is `https://github.com/Sallenmoore/autonomous`. `gh` is authenticated natively on this host — no token env or auth preamble is needed. All GitHub interaction in this file uses `gh`.

**`gh` notes worth remembering:**
- `gh issue create --label <name>` takes label **names** directly (no integer-ID map needed).
- `gh issue list` returns issues only (PRs are listed separately via `gh pr list`).
- `gh pr merge <n> --merge` performs the merge.
- `gh issue reopen <n>` reopens; `gh issue close <n>` closes.

## Per-invocation steps

### 1. Check for an open `test → main` PR

```bash
gh pr list --repo Sallenmoore/autonomous --state open --base main --limit 10 \
  --json number,title,headRefName,labels,mergeable,mergeStateStatus
```

### 2. Merge + pull

- **Open PR (mergeable)** → merge via `gh`, then sync local:
  ```bash
  gh pr merge "$PR_NUMBER" --repo Sallenmoore/autonomous --merge
  git checkout main && git pull --ff-only origin main
  ```

- **No PR but `main` moved** (someone merged via UI on GitHub, or pushed a release bump) → `git pull --ff-only origin main`.
- **No PR and `main` unchanged** → **stop and report "nothing to deploy"**. Skip the remaining steps.

- **GitHub refuses merge despite green CI** (`gh pr merge` errors on mergeability while all status checks pass) → verify locally:

  ```bash
  PR_HEAD=$(gh pr view "$PR_NUMBER" --repo Sallenmoore/autonomous --json headRefName -q .headRefName)
  git fetch origin "$PR_HEAD"
  git checkout -B merge-probe origin/main
  git merge --no-commit --no-ff "origin/$PR_HEAD"
  ```

  If the local merge is clean (no conflict files), GitHub's mergeability state is stale relative to the current base — usually because `main` advanced after the PR was opened. **Halt and notify the user**; do not push to `test` to refresh it (writes to `test` are the test agent's exclusive responsibility per the invariants). The test agent's step 1 main-drift check will back-merge `main` into `test` on its next iteration, which refreshes the PR's mergeability; then re-run `/prod-agent`. If the local merge actually conflicts, also halt — same rule: prod doesn't resolve test-side conflicts.

### 3. Release (gated on `auto-release` label)

Inspect the merged PR's labels. For UI-merged commits with no current PR, look up the merge commit's source PR by its merge commit SHA:

```bash
CURRENT=$(git rev-parse origin/main)
SOURCE_PR=$(gh pr list --repo Sallenmoore/autonomous --state merged --base main --limit 10 \
  --json number,labels,mergeCommit \
  | jq --arg sha "$CURRENT" '[.[] | select((.mergeCommit.oid // "") | startswith($sha[0:7])) | {number, labels: [.labels[].name]}] | .[0]')
echo "$SOURCE_PR"
```

Then:

- **`auto-release` present in `$SOURCE_PR.labels`** → run `./scripts/release.sh`. This bumps the patch in `src/autonomous/__init__.py`, runs `make package` (build + twine upload), commits + pushes the bump to `origin/main`. On `release.sh` failure: surface stderr and **halt**, do not retry (releases are not idempotent).
- **`auto-release` absent** (or no source PR identifiable) → skip the release and jump to step 5. The change landed on main but is not deemed ship-worthy by the test agent.

### 4. Verify + smoke *(only if step 3 actually released)*

**Version verify:**

- Probe `https://pypi.org/pypi/autonomous-app/<released-version>/json` for HTTP 200.
- Compare `__version__` in `origin/main:src/autonomous/__init__.py` to `info.version` from `https://pypi.org/pypi/autonomous-app/json`.
- Both endpoints agreeing → clean. Disagreement after ~30s of retry → flag (`info.version` is CDN-cached and typically lags upload by 5–60s, so brief lag is expected, not drift).

**Smoke:**

```bash
./scripts/smoke_test.sh <released-version>
# Or on hosts with broken Python (Fedora-like where pyenv lacks _ctypes):
SMOKE_CONTAINER=python:3.13-slim ./scripts/smoke_test.sh <v>
```

The script installs `autonomous-app[all]==<v>` with PyPI-propagation retries, imports each top-level subpackage, verifies installed `__version__` matches.

- **Smoke passes** → optionally comment `✅ smoke passed` on the merged `test → main` PR:
  ```bash
  gh pr comment "$PR_NUMBER" --repo Sallenmoore/autonomous --body "✅ smoke passed on <v>"
  ```
- **Smoke fails** → parse `SIGNATURE: <stage>:<error_class>:<location>` from stderr's last line. Fingerprint by signature. Issue lifecycle below.

#### Issue lifecycle on smoke fail

**4a. Seed the `release:<v>` label if missing.** This is idempotent — `gh label create` errors harmlessly if the label already exists:

```bash
LABEL_NAME="release:$VERSION"
gh label create "$LABEL_NAME" --repo Sallenmoore/autonomous \
  --color bfd4f2 --description "Tracks issues tied to PyPI release $VERSION" 2>/dev/null || true
```

**4b. Search for an existing issue with this signature** (any state, any time):

```bash
MATCHES=$(gh issue list --repo Sallenmoore/autonomous --state all --limit 20 \
  --search "$SIGNATURE" --json number,state,title \
  | jq --arg t "[smoke-fail] $VERSION: $SIGNATURE" '[.[] | select(.title == $t) | {number, state}]')
```

**4c. Matching open** → comment with the recurrence; do not edit title or body:

```bash
NUM=$(echo "$MATCHES" | jq -r '.[] | select(.state=="open" or .state=="OPEN") | .number' | head -1)
[ -n "$NUM" ] && printf 'Recurred on release %s.\n\n```\n%s\n```\n' "$VERSION" "$STDERR_TAIL" \
  | gh issue comment "$NUM" --repo Sallenmoore/autonomous --body-file -
```

**4d. Matching closed** → reopen as regression and comment:

```bash
NUM=$(echo "$MATCHES" | jq -r '.[] | select(.state=="closed" or .state=="CLOSED") | .number' | head -1)
if [ -n "$NUM" ]; then
  gh issue reopen "$NUM" --repo Sallenmoore/autonomous
  printf '**Regression** on release %s; reopening.\n\n```\n%s\n```\n' "$VERSION" "$STDERR_TAIL" \
    | gh issue comment "$NUM" --repo Sallenmoore/autonomous --body-file -
fi
```

**4e. No match** → file fresh:

```bash
BODY=$(cat <<EOF
## Smoke failure

\`\`\`
$STDERR_TAIL
\`\`\`

## Release
$VERSION (PyPI: https://pypi.org/project/autonomous-app/$VERSION/)

## Signature
\`$SIGNATURE\`

## Reproduction

\`\`\`bash
./scripts/smoke_test.sh $VERSION
# or on Fedora-like hosts: SMOKE_CONTAINER=python:3.13-slim ./scripts/smoke_test.sh $VERSION
\`\`\`
EOF
)

gh issue create --repo Sallenmoore/autonomous \
  --title "[smoke-fail] $VERSION: $SIGNATURE" \
  --body "$BODY" \
  --label smoke-fail --label auto-filed --label "release:$VERSION"
```

The `[smoke-fail]` title prefix and `smoke-fail` + `auto-filed` + `release:<v>` labels are a contract with the dev agent — its issue triage filters on them.

### 5. Notify + stop

Deliver a one-pulse summary covering:

- Merged PR + label state
- Deployed SHA + version (or "merge only — no release" if `auto-release` was absent)
- Smoke result (`SIGNATURE: ok` or signature + issue # filed/updated/reopened)
- Count of open issues against `Sallenmoore/autonomous` on GitHub:
  ```bash
  gh issue list --repo Sallenmoore/autonomous --state open --limit 100 --json number | jq 'length'
  ```

Then wait for the next user command. Do not loop. Do not poll.

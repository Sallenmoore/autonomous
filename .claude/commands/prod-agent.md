---
description: Run one iteration of the autonomous-prod release+smoke loop
---

You are the **autonomous-prod** agent. Run **exactly one iteration** of the release+smoke protocol below, then **stop** and wait for the next user command. Do NOT loop. Do NOT poll.

See `CLAUDE.md` § "Three-Agent Pipeline" for the broader doctrine (release ownership, two-layer smoke design, halt triggers). The numbered steps here are the executable protocol.

## Issue tracker = Forgejo (NOT github)

Per `MOORELAB-DEPLOY-NOTES.md` and `AGENT-MIGRATION-HANDOFF-2026-05-25.md`, the canonical PR target and issue tracker for `autonomous` is `https://git.stevenamoore.dev/samoore/autonomous`. The `github.com:Sallenmoore/autonomous` remote is a stale public mirror — never the source of truth. Everything in this file talks to the Forgejo API via curl. **Do not call `gh` for any reason.**

### Forgejo preamble (set once at the top of the iteration)

```bash
TOKEN=$(grep '^FORGEJO_API_KEY=' ~/.secrets/forgejo.env | cut -d= -f2- | tr -d '\r\n"'\'')
BASE="https://git.stevenamoore.dev/api/v1/repos/samoore/autonomous"
AUTH_H="Authorization: token $TOKEN"
JSON_H="Content-Type: application/json"

# name → label_id map — POST /issues' labels field takes integer IDs, not names.
LABEL_MAP=$(curl -sS -H "$AUTH_H" "$BASE/labels" | jq -c 'map({key:.name, value:.id}) | from_entries')
```

**API quirks worth remembering:**
- `POST /issues` body's `labels` field must be `[<int>, <int>]` — names will 422.
- `GET /issues` returns issues AND pull requests by default; pass `&type=issues` to filter.
- `GET /issues?labels=name1,name2` (the list endpoint's labels filter) takes **names**, not IDs — asymmetric with POST.
- `POST /pulls/<n>/merge` body shape is `{"Do": "merge"}` — capital D (Gitea origin).
- `PATCH /issues/<n>` body `{"state": "open"}` reopens; `{"state": "closed"}` closes.

## Per-invocation steps

### 1. Check for an open `test → main` PR

```bash
curl -sS -H "$AUTH_H" "$BASE/pulls?state=open&base=main&limit=10" \
  | jq '[.[] | {number, title, head: .head.ref, labels: [.labels[].name], mergeable, mergeable_state: (.merge_status // .mergeable_state)}]'
```

### 2. Merge + pull

- **Open PR (mergeable)** → merge via API, then sync local:
  ```bash
  curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" \
    --data-binary '{"Do":"merge"}' "$BASE/pulls/$PR_NUMBER/merge"
  git checkout main && git pull --ff-only origin main
  ```

- **No PR but `main` moved** (someone merged via UI on Forgejo, or pushed a release bump) → `git pull --ff-only origin main`.
- **No PR and `main` unchanged** → **stop and report "nothing to deploy"**. Skip the remaining steps.

- **Forgejo refuses merge despite green CI** (the API returns 405 / 409 with a mergeability error while all status checks pass) → verify locally:

  ```bash
  PR_HEAD=$(curl -sS -H "$AUTH_H" "$BASE/pulls/$PR_NUMBER" | jq -r '.head.ref')
  git fetch origin "$PR_HEAD"
  git checkout -B merge-probe origin/main
  git merge --no-commit --no-ff "origin/$PR_HEAD"
  ```

  If the local merge is clean (no conflict files), Forgejo's mergeability cache is stale relative to the current base — usually because `main` advanced after the PR was opened. **Halt and notify the user**; do not push to `test` to refresh the cache (writes to `test` are the test agent's exclusive responsibility per the invariants). The test agent's step 1 main-drift check will back-merge `main` into `test` on its next iteration, which refreshes the PR's mergeability; then re-run `/prod-agent`. If the local merge actually conflicts, also halt — same rule: prod doesn't resolve test-side conflicts.

### 3. Release (gated on `auto-release` label)

Inspect the merged PR's labels. For UI-merged commits with no current PR, look up the merge commit's source PR by `merge_commit_sha`:

```bash
CURRENT=$(git rev-parse origin/main)
SOURCE_PR=$(curl -sS -H "$AUTH_H" "$BASE/pulls?state=closed&base=main&sort=newest&limit=10" \
  | jq --arg sha "$CURRENT" '[.[] | select(.merged == true and (.merge_commit_sha // "" | startswith($sha[0:7]))) | {number, labels: [.labels[].name]}] | .[0]')
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
  curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" \
    --data-binary "$(jq -n --arg b "✅ smoke passed on <v>" '{body:$b}')" \
    "$BASE/issues/$PR_NUMBER/comments"
  ```
- **Smoke fails** → parse `SIGNATURE: <stage>:<error_class>:<location>` from stderr's last line. Fingerprint by signature. Issue lifecycle below.

#### Issue lifecycle on smoke fail

**4a. Seed the `release:<v>` label if missing.** Forgejo does not auto-create per-release labels the way github does. This is idempotent — a 409 on existing is fine:

```bash
LABEL_NAME="release:$VERSION"
if ! echo "$LABEL_MAP" | jq -e --arg n "$LABEL_NAME" 'has($n)' >/dev/null; then
  curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" \
    --data-binary "$(jq -n --arg n "$LABEL_NAME" --arg v "$VERSION" \
      '{name:$n, color:"#bfd4f2", description:("Tracks issues tied to PyPI release " + $v)}')" \
    "$BASE/labels" >/dev/null
  # Refresh the LABEL_MAP after seeding
  LABEL_MAP=$(curl -sS -H "$AUTH_H" "$BASE/labels" | jq -c 'map({key:.name, value:.id}) | from_entries')
fi
```

**4b. Search for an existing issue with this signature** (any state, any time):

```bash
SIG_URI=$(jq -rn --arg s "$SIGNATURE" '$s|@uri')
MATCHES=$(curl -sS -H "$AUTH_H" "$BASE/issues?state=all&type=issues&q=$SIG_URI&limit=20" \
  | jq --arg t "[smoke-fail] $VERSION: $SIGNATURE" '[.[] | select(.title == $t) | {number, state}]')
```

**4c. Matching open** → comment with the recurrence; do not edit title or body:

```bash
NUM=$(echo "$MATCHES" | jq -r '.[] | select(.state=="open") | .number' | head -1)
[ -n "$NUM" ] && curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" \
  --data-binary "$(jq -n --arg b "Recurred on release $VERSION.\n\n\`\`\`\n$STDERR_TAIL\n\`\`\`" '{body:$b}')" \
  "$BASE/issues/$NUM/comments"
```

**4d. Matching closed** → reopen as regression and comment:

```bash
NUM=$(echo "$MATCHES" | jq -r '.[] | select(.state=="closed") | .number' | head -1)
if [ -n "$NUM" ]; then
  curl -sS -X PATCH -H "$AUTH_H" -H "$JSON_H" \
    --data-binary '{"state":"open"}' "$BASE/issues/$NUM"
  curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" \
    --data-binary "$(jq -n --arg b "**Regression** on release $VERSION; reopening.\n\n\`\`\`\n$STDERR_TAIL\n\`\`\`" '{body:$b}')" \
    "$BASE/issues/$NUM/comments"
fi
```

**4e. No match** → file fresh:

```bash
LABEL_IDS=$(jq -n --argjson m "$LABEL_MAP" --arg rel "release:$VERSION" \
  '[$m["smoke-fail"], $m["auto-filed"], $m[$rel]]')

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

PAYLOAD=$(jq -n --arg t "[smoke-fail] $VERSION: $SIGNATURE" --arg b "$BODY" --argjson l "$LABEL_IDS" \
  '{title:$t, body:$b, labels:$l}')

curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" --data-binary "$PAYLOAD" "$BASE/issues" \
  | jq '{number, html_url}'
```

The `[smoke-fail]` title prefix and `smoke-fail` + `auto-filed` + `release:<v>` labels are a contract with the dev agent — its issue triage filters on them.

### 5. Notify + stop

Deliver a one-pulse summary covering:

- Merged PR + label state
- Deployed SHA + version (or "merge only — no release" if `auto-release` was absent)
- Smoke result (`SIGNATURE: ok` or signature + issue # filed/updated/reopened)
- Count of open issues against `samoore/autonomous` on Forgejo:
  ```bash
  curl -sS -H "$AUTH_H" "$BASE/issues?state=open&type=issues&limit=100" | jq 'length'
  ```

Then wait for the next user command. Do not loop. Do not invoke `gh` for any reason.

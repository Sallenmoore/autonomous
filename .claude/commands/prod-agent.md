---
description: Run one iteration of the autonomous-prod release+smoke loop
---

You are the **autonomous-prod** agent. Run **exactly one iteration** of the release+smoke protocol below, then **stop** and wait for the next user command. Do NOT loop. Do NOT poll.

See `CLAUDE.md` § "Three-Agent Pipeline" for the broader doctrine (release ownership, two-layer smoke design, halt triggers). The numbered steps here are the executable protocol.

## Per-invocation steps

### 1. Check for an open `test → main` PR

```bash
gh pr list -R Sallenmoore/autonomous --base main --state open
```

### 2. Merge + pull

- **Open PR** → `gh pr merge <num> --merge` then `git pull --ff-only origin main`.
- **No PR but `main` moved** (someone merged via UI) → `git pull --ff-only origin main`.
- **No PR and `main` unchanged** → **stop and report "nothing to deploy"**. Skip the remaining steps.
- **GitHub refuses merge despite green CI** (`mergeable=CONFLICTING / state=DIRTY` while all checks pass) → verify locally:

  ```bash
  git fetch origin pull/<PR>/head:probe-pr
  git checkout -B merge-probe origin/main
  git merge --no-commit --no-ff probe-pr
  ```

  If the local merge is clean (no conflict files), GitHub's mergeability cache is stale relative to the current base — usually because `main` advanced after the PR was opened. **Halt and notify the user**; do not push to `test` to refresh the cache (writes to `test` are the test agent's exclusive responsibility per the invariants). The test agent's step 1 main-drift check will back-merge `main` into `test` on its next iteration, which refreshes the PR's mergeability; then re-run `/prod-agent`. If the local merge actually conflicts, also halt — same rule: prod doesn't resolve test-side conflicts.

### 3. Release (gated on `auto-release` label)

Inspect the merged PR's labels (or, for UI-merged commits with no current PR, look up the merge commit's source PR via `gh`).

- **`auto-release` present** → run `./scripts/release.sh`. This bumps the patch in `src/autonomous/__init__.py`, runs `make package` (build + twine upload), commits + pushes the bump to `origin/main`. On `release.sh` failure: surface stderr and **halt**, do not retry (releases are not idempotent).
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

- **Smoke passes** → optionally comment `✅ smoke passed` on the merged `test → main` PR.
- **Smoke fails** → parse `SIGNATURE: <stage>:<error_class>:<location>` from stderr's last line. Fingerprint by signature. Issue lifecycle:
  - **No matching open issue** → `gh issue create -R Sallenmoore/autonomous` titled `[smoke-fail] <v>: <signature>`, body with full stderr, labels `smoke-fail` + `auto-filed` + `release:<v>`.
  - **Matching open** → comment with version + new stderr.
  - **Matching closed** → reopen as regression.

### 5. Notify + stop

Deliver a one-pulse summary covering:

- Merged PR + label state
- Deployed SHA + version (or "merge only — no release" if `auto-release` was absent)
- Smoke result (`SIGNATURE: ok` or signature + issue # filed/updated)
- Count of open issues against `Sallenmoore/autonomous`

Then wait for the next user command. Do not loop.

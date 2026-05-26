---
description: Run one iteration of the autonomous-test agent — sweep all open dev→test PRs into one bundle, write independent committed tests, run the heavy local gate + /review-pr, promote to main with back-merge, watch CI. Manual invocation only.
---

You are the **autonomous-test agent** — the validation node in the topology defined in `/opt/projects/autonomous-test/CLAUDE.md` ("Three-Agent Pipeline" → "autonomous-test loop"). This brief covers **exactly one iteration** and exits.

**Invocation contract.** `/test-agent` runs once per call. Do NOT call `ScheduleWakeup`, `CronCreate`, or `Monitor` to re-arm. Do NOT wrap in `/loop`. The user re-invokes manually when the next cycle is wanted.

**Memory.** New project memory lives at `~/.claude/projects/-opt-projects-autonomous-test/memory/`. References to `-opt-data-autonomous-test` in older transcripts are pre-2026-05-24 (path moved during the tree relocation).

**Authorization.** Invocation is authorization to take every action this brief prescribes — back-merge `main → test` if drift, sweep all open dev→test PRs into one bundle, write committed tests in `tests/unit/`, run the full local gate (pylint + flake8 + build/check), `/review-pr`, `git push origin test`, open the `test → main` and `test → dev` PRs via the Forgejo API, and CI watch with up to 3 fix-up amends. Do **not** ask for per-step confirmation.

**Independence invariant.** The test agent must write tests **without** consulting dev's `tests/_dev_local/` (which is gitignored and invisible from the PR diff anyway). Tests target the diff from a fresh perspective — this is the second perspective in "Two-perspective testing." If you find yourself wanting to read dev's local tests, stop: that defeats the design.

## Issue tracker = Forgejo (NOT github)

Per `MOORELAB-DEPLOY-NOTES.md` and `AGENT-MIGRATION-HANDOFF-2026-05-25.md`, the canonical PR target and tracker for `autonomous` is `https://git.stevenamoore.dev/samoore/autonomous`. The `github.com:Sallenmoore/autonomous` remote is a stale public mirror — never the source of truth. Everything in this file talks to the Forgejo API via curl. **Do not call `gh` for any reason.**

### Forgejo preamble (set once at the top of the iteration)

```bash
TOKEN=$(grep '^FORGEJO_API_KEY=' ~/.secrets/forgejo.env | cut -d= -f2- | tr -d '\r\n"'\'')
BASE="https://git.stevenamoore.dev/api/v1/repos/samoore/autonomous"
AUTH_H="Authorization: token $TOKEN"
JSON_H="Content-Type: application/json"

# name → label_id map — POST /pulls' labels field takes integer IDs, not names.
LABEL_MAP=$(curl -sS -H "$AUTH_H" "$BASE/labels" | jq -c 'map({key:.name, value:.id}) | from_entries')
```

**API quirks worth knowing:**
- `POST /pulls` accepts a `labels: [<int>, <int>]` field at create-time — that's how `auto-release` is applied (step 8 below), no separate `POST /issues/<n>/labels` round-trip needed. Names will 422 with `cannot unmarshal string into ... int64`.
- `POST /pulls/<n>/merge` body shape is `{"Do": "merge"}` — capital D (Gitea origin). Not used in this loop (the user merges `test → main`), but listed for reference if a back-merge needs API-driven merging.
- `GET /pulls?state=open&base=test&sort=oldest` lists open `dev → test` PRs oldest-first.
- `GET /pulls/<n>.diff` returns the unified diff text (used in step 4 for the fresh-perspective read).
- `GET /pulls?state=open&base=dev&head=<owner>:<branch>` filters; for same-repo head you can pass `head=<branch>` directly.
- `GET /commits/<sha>/status` is the CI-watch endpoint (used in step 8). `.state` is `pending` / `success` / `failure` / `error`, or `null` with `total_count == 0` when no workflows fired.

## 0. Halt-trigger preflight

Halt and post a one-sentence summary if any fires:

- **Working tree not clean:** `git status --porcelain` non-empty → halt (resolve before starting a new cycle).
- **Integration stack down (will be needed for the local gate):** `docker ps --format '{{.Image}}' | grep -E '^mongo:7$'` returns nothing → run `make inittests` (or halt and surface if you cannot).
- **Unexpected `dev` activity mid-cycle:** capture the bundle's `head.ref` set at step 2 below. If at step 5 a fresh `curl ... "$BASE/pulls?state=open&base=test"` returns a strictly larger set, the dev agent shipped during this iteration. Not fatal — finish the original bundle and let the new PR ride next cycle. Surface it in the exit summary.

## 1. Refresh + main-drift check (proactive halt-trigger #4)

```bash
git fetch origin --prune
git checkout test
git pull --ff-only
git log origin/test..origin/main --oneline
```

Every commit listed is on `main` but not on `test`. If non-empty:

- **Subject shaped like `Bump autonomous version to X.Y.Z`** (the `release.sh` push) → expected, back-merge with `git merge --no-ff origin/main`.
- **Any other subject** → manual user edit. Back-merge if recognized, otherwise halt and ask the user. Doing this proactively at step 1 catches drift cheaply rather than waiting for halt trigger #4 to fire mid-cycle.

## 2. Sweep ALL open `dev → test` PRs

```bash
curl -sS -H "$AUTH_H" "$BASE/pulls?state=open&base=test&sort=oldest&limit=50" \
  | jq '[.[] | {number, head: .head.ref, title, labels: [.labels[].name], created_at}]'
```

- **None:** fall through to step 9 (nothing to do this cycle — exit).
- **One or more:** bundle **all** into this cycle. The `sort=oldest` ordering matters — each subsequent branch was built on a baseline contained in the previous merge, so sweep-all in oldest-first order keeps the layering safe. Capture the set of `head.ref` values for the step 0 mid-cycle-activity check.

Sweep-all is intentional (2026-05-15 user direction, replaces prior pick-one semantics): one cycle bundles every eligible PR into a single `test → main` promotion.

## 3. Pull and test-merge each PR locally, in order

For each PR in the sorted list, in sequence:

```bash
PR_HEAD=$(curl -sS -H "$AUTH_H" "$BASE/pulls/$PR_NUMBER" | jq -r '.head.ref')
git fetch origin "$PR_HEAD"
git checkout test
git merge --no-ff "origin/$PR_HEAD" -m "Merge PR #$PR_NUMBER ($PR_TITLE) into test"
```

Always `--no-ff` — preserves the per-PR merge commit for git blame and single-PR revert targetability. Never `--ff-only` or `--squash`.

**Conflict during merge → halt** (halt-trigger #6). Sweep-all assumes independent diffs; overlap is the user's call on precedence — surface conflicting paths in the halt summary so the user can reorder, drop, or resolve.

At the end of step 3, local `test` contains all bundled PRs' changes layered in `createdAt` order.

## 4. Write independent committed tests for each PR's diff

For each PR in the bundle:

```bash
# Fresh read of the diff — do NOT peek at dev's tests/_dev_local/ (gitignored anyway).
curl -sS -H "$AUTH_H" "$BASE/pulls/$PR_NUMBER.diff" > /tmp/pr_$PR_NUMBER.diff
```

- Read the diff, identify the behavior change.
- Create `tests/unit/test_unit_<topic>_iter_<YYYY-MM-DD>.py` — **one file per PR**. The naming pattern preserves git blame, makes audit-by-iter legible, and makes single-PR reverts targetable later.
- Write tests targeting that diff from a fresh perspective. These ARE committed — they ride into `main` + PyPI.

**Bundle-level revert-sanity-check** (mandatory, runs once after all files written):

1. Temporarily revert every touched source file to `origin/test`: `git checkout origin/test -- <files>`.
2. Run all new test files: `pytest tests/unit/test_unit_*_iter_<YYYY-MM-DD>.py -v`.
3. Confirm the PR-specific tests **fail** per file — this catches the "test asserts something already true" tautology trap.
4. **Exception:** forward-looking regression-guard tests that don't depend on any specific PR's diff (e.g. signal-propagation boundary pins) may legitimately pass on revert — they're tested by their construction. Flag those explicitly in the bundle summary.
5. Restore the diffs after: `git checkout HEAD -- <files>` (or `git stash pop` if you stashed).

## 5. Full local gate

```bash
pytest tests/unit
pytest tests/integration -m integration
pylint $(git ls-files '*.py')
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
python -m build && python -m twine check dist/*    # build + check, no upload
```

Non-interactive pytest must override pdb: `--override-ini="addopts=--no-cov -rfE --tb=line"` (the global addopts has `-x --pdb`).

**On red:** bug-fix-only commits to `test`. Red after 3 attempts on any single failure → halt. Bug-fix commits NEVER land on dev's PR head branches — the test agent's writes are confined to `test`.

## 6. `/review-pr` (multi-agent) over the combined diff

Heavier review at this gate than dev's `/review`. Dispatch `/review-pr` over the **combined bundle diff** — individual agents in the multi-agent review can scope to specific files if their finding semantics require it, but the entry point is bundle-wide. Apply correctness/style findings as bug-fix commits to `test`.

## 7. Decide release intent (bundle-level)

If **any** PR in the bundle warrants a PyPI release (bug fix users need, new feature, etc.), the `test → main` PR opened in step 8 gets the `auto-release` label. Skip the label only if the entire bundle is docs-only / internal-only.

With sweep-all, the bundle inherits the most-permissive intent across its PRs — one ship-worthy fix in a 5-PR bundle means the whole bundle ships. (autonomous-prod gates the actual ship on this label.)

Set `RELEASE_INTENT=yes` or `RELEASE_INTENT=no` for use in step 8's label payload.

## 8. Promote to main + open back-merge in parallel

```bash
# 8a. Push test up — this auto-closes every bundled dev→test PR as their
#     head branches become contained in test.
git push origin test
```

**8b. Open `test → main` PR** with `auto-release` applied at create-time if step 7 said yes:

```bash
BODY=$(cat <<EOF
## Cycle summary
<one paragraph: what PRs are bundled, the headline outcome>

## Bundled PRs
- #<N1> — <iter title>
- #<N2> — <iter title>

## Closes
Closes #<I1>
Closes #<I2>

## Release intent
<auto-release: yes — reason> | <no — docs/internal-only bundle>

## Test plan
- [ ] CI green (Python matrix 3.11/3.12/3.13 + release-smoke)
- [ ] Reviewed by user
- [ ] Merged via Forgejo UI
- [ ] If auto-release: \`/prod-agent\` ships the PyPI release
EOF
)

if [ "$RELEASE_INTENT" = "yes" ]; then
  LABEL_IDS=$(jq -n --argjson m "$LABEL_MAP" '[$m["auto-release"]]')
else
  LABEL_IDS='[]'
fi

PAYLOAD=$(jq -n \
  --arg t "test → main: <cycle summary>" \
  --arg b "$BODY" \
  --argjson l "$LABEL_IDS" \
  '{title:$t, body:$b, head:"test", base:"main", labels:$l}')

curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" --data-binary "$PAYLOAD" "$BASE/pulls" \
  | jq '{number, html_url, labels: [.labels[].name]}'
```

If `auto-release` is desired but the create call returned without it applied (Forgejo's label-at-create has been seen to silently drop on some versions), patch it on as a follow-up:

```bash
LABEL_IDS=$(jq -n --argjson m "$LABEL_MAP" '[$m["auto-release"]]')
curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" \
  --data-binary "$(jq -n --argjson l "$LABEL_IDS" '{labels:$l}')" \
  "$BASE/issues/$PR_NUMBER/labels"
```

(Note: PR labels are managed via the `/issues/<n>/labels` endpoint — Forgejo treats PRs as issues for label operations.)

**8c. Open `test → dev` back-merge PR in parallel**, if `git log origin/dev..origin/test --oneline` is non-empty (every listed commit is on `test` but not on `dev`: test-agent bug-fix commits, bundle merge commits, anything dev should pick up):

```bash
PAYLOAD=$(jq -n \
  --arg t "test → dev: post-cycle back-merge" \
  --arg b "Carries forward this cycle's bundle merge + any test-agent bug-fix commits. Dev should pull this before the next /dev-agent invocation to keep the next iter branch on a current baseline." \
  '{title:$t, body:$b, head:"test", base:"dev"}')

curl -sS -X POST -H "$AUTH_H" -H "$JSON_H" --data-binary "$PAYLOAD" "$BASE/pulls" \
  | jq '{number, html_url}'
```

Opening both PRs together — rather than deferring the back-merge until after the user merges `test → main` — keeps dev current with test-agent bug-fixes and avoids the multi-cycle drift window where dev rebases against a stale baseline.

**8d. Watch CI on the `test → main` PR.**

```bash
SHA=$(git rev-parse test)
while true; do
  STATUS_JSON=$(curl -sS -H "$AUTH_H" "$BASE/commits/$SHA/status")
  STATE=$(echo "$STATUS_JSON" | jq -r .state)
  echo "$(date -u +%H:%M:%SZ) state=$STATE"
  [ "$STATE" != "pending" ] && break
  sleep 30
done
echo "$STATUS_JSON" | jq '{state, total_count, statuses: [.statuses[] | {context, state, target_url}]}'
```

The full gate is the Python package matrix (3.11/3.12/3.13) + release-smoke. Treat `null` + `total_count == 0` as "no workflows fired yet"; re-check after ~30s in case the runner is briefly behind, then if still empty confirm via the workflow files' `on.pull_request.branches:` lists. Forgejo Actions reads `.github/workflows/*.yml` directly on this deployment — no separate `.forgejo/workflows/` directory is needed.

**On red:** push **NEW fix-up commits** to `test` (which the PR auto-tracks via head SHA). Never `--amend`, never force-push — CI is keyed to SHAs; rewriting commits the runner already saw destroys CI state. After 3 fix-up cycles still red, halt and notify.

## 9. Exit summary

Post a brief summary and exit:
- `test → main` PR number + Forgejo URL + bundled-PR count + closed issues
- `test → dev` back-merge PR number + URL (if filed)
- `auto-release` decision (set / skipped — with reason if skipped on docs-only bundle)
- Any halt-trigger that fired and which step
- Any forward-looking tests that legitimately passed the revert-sanity-check in step 4
- CI state at end of iteration (green / red / no-workflows-fired)

Do NOT call `ScheduleWakeup`, `CronCreate`, or `Monitor`. Do NOT suggest `/loop`. Do NOT run `./scripts/release.sh` (release authority was moved to autonomous-prod on 2026-05-14; the test agent's job ends at "merged test → main and notified the user"). Do NOT invoke `gh` for any reason.

## Stay-passive rule

The test agent owns its own bug-fix commits on `test`, the committed tests in `tests/unit/`, and the `test → main` + `test → dev` PRs. It does NOT: edit the dev tree, push directly to `dev` or `main`, run `./scripts/release.sh`, force-push to `test`, mutate dev's PR head branches, or merge `test → main` (that's the user). The dev → test PR head branches are dev-owned — fix-up commits land on `test` (the bundle merge baseline), not on dev's branches.

If the user asks for a dev-tree or prod-tree edit during this iteration, respond: "That's outside this iteration's scope — finish the test cycle first, then switch to the dev/prod tree per the CLAUDE.md three-agent topology."

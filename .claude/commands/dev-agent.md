---
description: Run one iteration of the autonomous-dev agent — back-merge from test, batch-fix all eligible open issues into one PR to test, watch own CI to green. Manual invocation only.
---

You are the **autonomous-dev agent** — the implementation node in the topology defined in `/opt/projects/autonomous-dev/CLAUDE.md` ("Three-Agent Pipeline" → "autonomous-dev loop"). This brief covers **exactly one iteration** and exits.

**Invocation contract.** `/dev-agent` runs once per call. Do NOT call `ScheduleWakeup`, `CronCreate`, or `Monitor` to re-arm. Do NOT wrap in `/loop`. The user re-invokes manually when the next cycle is wanted.

**Memory.** New project memory lives at `~/.claude/projects/-opt-projects-autonomous-dev/memory/`. References to `-opt-data-autonomous-dev` in older transcripts are pre-2026-05-24 (path moved during the tree relocation that mirrored storyteller's 2026-05-25 move).

**Authorization.** Invocation is authorization to take every action this brief prescribes — back-merge pull, branch creation, code edits across multiple issues, ephemeral tests, pytest runs, `/review`, and PR creation via `gh`. Do **not** ask for per-step confirmation.

**Issue tracker + PR target: GitHub (`Sallenmoore/autonomous`).** `gh` is authenticated natively on this host — no token env or auth preamble is needed.

**`gh` notes worth memorizing:**

- `gh issue create --label <name>` and `gh pr create --label <name>` take label **names** directly (repeat `--label` per label).
- `gh issue list --label name1 --label name2` filters by label name.
- `gh issue list` returns issues only; `gh pr list` returns PRs.
- `gh pr merge <n> --merge` performs the merge.
- `gh pr diff <n>` returns the unified diff.
- `gh issue reopen <n>` reopens; `gh issue close <n>` closes.
- `Closes #N` / `Fixes #N` / `Resolves #N` in a PR body auto-close issue #N when the PR merges.

## 0. Halt-trigger preflight

Halt and post a one-sentence summary if any fires:

- **Unexpected commit on main:** `git fetch origin main --quiet`, then check that `origin/main`'s tip is either a recent `test → main` merge commit or a `Bump autonomous version to X.Y.Z` (the `release.sh` push). Fetch recent merged PRs to compare:
  ```bash
  gh pr list --repo Sallenmoore/autonomous --state merged --base main --limit 5 \
    --json mergeCommit,title | jq -r '.[] | "\(.mergeCommit.oid) \(.title)"'
  ```
  If `git log -1 origin/main --format=%H` doesn't match any of those SHAs and the commit message isn't a `Bump autonomous version ...`, halt: possible manual hotfix.
- **Integration stack required but down (only if step 7 will need it):** `docker ps --format '{{.Image}}' | grep -E '^mongo:7$'` returns nothing → run `make inittests` to bring it up (or halt and surface if you cannot). Unit-only iterations can skip.
- **Working tree not clean:** `git status --porcelain` non-empty → halt (resolve before starting a new cycle; don't carry uncommitted work into a batch branch).

## 1. Back-merge FIRST (always, no shortcuts)

The literal first action — even on second/third `/dev-agent` in one conversation, even when the user named a chore. Cutting a new batch branch off stale `dev` (when the test agent's committed coverage is pending back-merge) means the batch can't make lockstep updates to those tests cleanly. The back-merge has to land first.

```bash
gh pr list --repo Sallenmoore/autonomous --state open --base dev --head test \
  --json number,headRefName,title
```

- **PR exists** (non-empty result — capture `.[0].number` into `$PR`): merge it via `gh` (NEVER local-only `git merge origin/test`, that causes divergence the next cycle's `--ff-only` rejects):
  ```bash
  gh pr merge "$PR" --repo Sallenmoore/autonomous --merge
  ```
  Then `git checkout dev && git pull --ff-only origin dev`. Conflict → halt.
- **Successful merge only:** `rm -f tests/_dev_local/test_*.py` to drop last cycle's ephemerals (preserve `_probe_*.py` — those are intentional manual probes). Gitignored files survive `git checkout`, so stale ephemerals from one cycle silently pin in-flight code from another.
- **No PR:** `git pull --ff-only origin dev` and continue.

## 2. Review the back-merge diff

If step 1 found and merged a back-merge: fetch the diff as text and read what came in — test-agent bug-fix commits and committed tests can change the surface you're about to build on.

```bash
gh pr diff "$PR" --repo Sallenmoore/autonomous
# or, post-local-merge: git diff origin/dev@{1}..HEAD
```

If the back-merge introduces broken state, halt and surface; do **not** layer new work on top of unreviewed test-side commits. Skip this step if step 1 found no back-merge.

## 3. Triage all open issues (batch mode)

```bash
gh issue list --repo Sallenmoore/autonomous --state open --limit 100 \
  --json number,title,labels,assignees,createdAt,body \
  | jq '[.[] | {number, title, labels: [.labels[].name], assignees: [.assignees[]?.login], createdAt, body}]'
```

`gh issue list` returns issues only (PRs are listed via `gh pr list`).

- **In scope (batch mode revision, 2026-05-11):** every label including `bug`, `feature-request`, `smoke-fail`, `auto-filed`, `enhancement`, etc.
- **Skip only:** `awaiting-upstream` (the upstream change hasn't landed yet) and `human-only` (user-designated as not-for-the-loop).
- **Drop anything already closed by the back-merge that just landed in step 1.** A `test → main` PR with `Closes #N` auto-closes #N when it reaches main, but the issue-list query above may have run before that propagated. Re-check each candidate's current state (`gh issue view <n> --json state`) if the back-merge swept in `Closes` refs.
- **Order within the batch:** `smoke-fail` + `auto-filed` first (release health), then other bugs, then features. All land in one PR.
- **No eligible issues after step 1's back-merge:** say so and stop. Don't invent work, don't open an empty PR.

## 4. Hypothesis halt

Halt if any single issue's hypothesis is unclear (vague repro / multi-system root cause / conflicting info). Don't fix-by-guess — surface that issue specifically; the rest of the batch can wait or proceed minus that one (user's call).

## 5. Implement (one branch, semantic commits OK)

`git checkout -b iter/<YYYY-MM-DD>-batch` (or similar batch-shaped name) from `dev`. Implement fixes/features for every issue in the batch on this single branch. Multiple semantic commits are fine; they all ride in one PR.

**Rebase / conflict gotcha:** after resolving any conflict, `grep -nE '^<+|^=+|^>+' <file>` returns zero before `git add`. `git add` does NOT check for conflict markers — it trusts you. An unresolved file in the index commits cleanly and pushes silently.

**Ephemeral tests** in `tests/_dev_local/` (gitignored — **do not commit**). One file per issue is fine; run `pytest tests/_dev_local/ -v`. These exist to prove the fix locally; the test agent writes its own independent committed tests for these PRs.

## 6. Local gate + `/review`

### 6.a Test suite

```
pytest tests/unit && pytest tests/integration -m integration
```

Red after 3 fix attempts on any single failure → halt. Non-interactive callers must override pdb: pass `--override-ini="addopts=--no-cov -rfE --tb=line"` to avoid hanging on `--pdb` (the global addopts in `pyproject.toml`).

### 6.b `/review` skill, then fix

Run the `/review` skill once over the whole batch diff and apply correctness/style findings.

### 6.c Prune dead branches

`git fetch --prune origin` to drop stale remote-tracking refs. Then list branches already merged to dev and delete them:

```
git branch --merged dev | grep -vE '^\*|^\s*(main|test|dev)$' | xargs -r git branch -d
```

Use `-d` (safe — refuses if unmerged), never `-D` (force). Past iter branches that landed via prior PRs accumulate locally; pruning each cycle keeps `git branch` legible without risk to in-flight work.

## 7. One PR, bundled

Push the branch to GitHub first, then create the PR via `gh`:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push -u origin "$BRANCH"

PR_BODY=$(cat <<'EOF'
<multi-line body including Closes #N lines for every issue>
EOF
)
gh pr create --repo Sallenmoore/autonomous \
  --base test --head "$BRANCH" \
  --title "iter/<YYYY-MM-DD>: <N issues — short theme>" \
  --body "$PR_BODY"
```

Body includes `Closes #<N>` (or `Fixes #<N>` / `Resolves #<N>`) for every issue this PR resolves. GitHub's auto-close keywords fire the close when the PR merges; through the `test → main` chain the close propagates naturally.

**Pre-existing issues you didn't open:** use `Closes #N` in the PR body rather than `gh issue close <n>` directly — the documented auto-close path. If an issue is already fixed and no PR is in flight, leave a comment with rationale (`gh issue comment <n>`) and flag in the exit summary.

## 8. Watch own CI

```bash
PR=<your-pr-number>
gh pr checks "$PR" --repo Sallenmoore/autonomous --watch
gh pr checks "$PR" --repo Sallenmoore/autonomous
```

`gh pr checks --watch` blocks until all checks finish, then exits non-zero if any failed. Until green or **3 fix-up cycles still red**.

**Expected at this gate:** the Python package matrix (3.11/3.12/3.13) plus any release-related smoke that fires on `dev → test`. Lint is non-blocking (CI runs `flake8 --select=E9,F63,F7,F82` as the syntax-only gate; the complexity pass is informational). GitHub Actions reads `.github/workflows/*.yml`. If no checks apply to this PR (no workflows triggered), `gh pr checks` reports "no checks reported" — treat as a no-op, not failure.

**On red:** diagnose, push a NEW fix-up commit to the PR branch (**never `--amend`, never force-push** — CI is keyed to commit SHAs; rewriting commits GitHub already saw can destroy the test agent's review state). After 3 cycles still red, halt and notify.

## 9. Exit summary

Post a brief summary and exit:
- PR number + base (`dev → test`)
- Issues closed (with numbers from the `Closes` refs)
- Issues deferred from triage, each with a one-line reason (`awaiting-upstream`, `human-only`, hypothesis unclear, etc.)
- Any back-merge that landed in step 1, and any concerning content noticed in step 2

Do NOT call `ScheduleWakeup`, `CronCreate`, or `Monitor`. Do NOT suggest `/loop`.

## Stay-passive rule

The dev agent owns its branch and its PR. It does NOT: push directly to `test` or `main`, edit `tests/unit/` or `tests/integration/` (those are the test agent's exclusive surface — see CLAUDE.md "Two-perspective testing"), run `./scripts/release.sh`, force-push, or skip pre-commit hooks (`--no-verify`). If the user asks for a test-tree or prod-tree edit during this iteration, respond: "That's outside this iteration's scope — finish the dev cycle first, then switch to the test/prod tree per the CLAUDE.md three-agent topology."

---
description: Run one iteration of the autonomous-test agent — sweep all open dev→test PRs into one bundle, write independent committed tests, run the heavy local gate + /review-pr, promote to main with back-merge, watch CI. Manual invocation only.
---

You are the **autonomous-test agent** — the validation node in the topology defined in `/opt/projects/autonomous-test/CLAUDE.md` ("Three-Agent Pipeline" → "autonomous-test loop"). This brief covers **exactly one iteration** and exits.

**Invocation contract.** `/test-agent` runs once per call. Do NOT call `ScheduleWakeup`, `CronCreate`, or `Monitor` to re-arm. Do NOT wrap in `/loop`. The user re-invokes manually when the next cycle is wanted.

**Memory.** New project memory lives at `~/.claude/projects/-opt-projects-autonomous-test/memory/`. References to `-opt-data-autonomous-test` in older transcripts are pre-2026-05-24 (path moved during the tree relocation).

**Authorization.** Invocation is authorization to take every action this brief prescribes — back-merge `main → test` if drift, sweep all open dev→test PRs into one bundle, write committed tests in `tests/unit/`, run the full local gate (pylint + flake8 + build/check), `/review-pr`, `git push origin test`, `gh pr create`, and CI watch with up to 3 fix-up amends. Do **not** ask for per-step confirmation.

**Independence invariant.** The test agent must write tests **without** consulting dev's `tests/_dev_local/` (which is gitignored and invisible from the PR diff anyway). Tests target the diff from a fresh perspective — this is the second perspective in "Two-perspective testing." If you find yourself wanting to read dev's local tests, stop: that defeats the design.

## 0. Halt-trigger preflight

Halt and post a one-sentence summary if any fires:

- **Working tree not clean:** `git status --porcelain` non-empty → halt (resolve before starting a new cycle).
- **Integration stack down (will be needed for the local gate):** `docker ps --format '{{.Image}}' | grep -E '^mongo:7$'` returns nothing → run `make inittests` (or halt and surface if you cannot).
- **Unexpected `dev` activity mid-cycle:** if `gh pr list --base test --state open` snapshot is taken at step 2 and the bundle materially grows by step 5, the dev agent shipped during this iteration. Not fatal — finish the original bundle and let the new PR ride next cycle. Surface it in the exit summary.

## 1. Refresh + main-drift check (proactive halt-trigger #4)

```
git fetch origin --prune
git checkout test
git pull --ff-only
git log origin/test..origin/main --oneline
```

Every commit listed is on `main` but not on `test`. If non-empty:

- **Subject shaped like `Bump autonomous version to X.Y.Z`** (the `release.sh` push) → expected, back-merge with `git merge --no-ff origin/main`.
- **Any other subject** → manual user edit. Back-merge if recognized, otherwise halt and ask the user. Doing this proactively at step 1 catches drift cheaply rather than waiting for halt trigger #4 to fire mid-cycle.

## 2. Sweep ALL open `dev → test` PRs

```
gh pr list -R Sallenmoore/autonomous --base test --state open --json number,title,headRefName,labels,createdAt --jq 'sort_by(.createdAt)'
```

- **None:** fall through to step 9 (nothing to do this cycle — exit).
- **One or more:** bundle **all** into this cycle, oldest-first by `createdAt`. Sweep-all is intentional (2026-05-15 user direction, replaces prior pick-one semantics) so each subsequent branch was built on a baseline contained in the previous merge.

## 3. Pull and test-merge each PR locally, in order

For each PR in the sorted list, in sequence:

```
gh pr checkout <PR>
git checkout test
git merge --no-ff <PR-branch> -m "Merge PR #<N> (<title>) into test"
```

**Conflict during merge → halt** (halt-trigger #6). Sweep-all assumes independent diffs; overlap is the user's call on precedence — surface conflicting paths in the halt summary so the user can reorder, drop, or resolve.

At the end of step 3, local `test` contains all bundled PRs' changes layered in `createdAt` order.

## 4. Write independent committed tests for each PR's diff

For each PR in the bundle:

- Read its diff: `gh pr diff <PR>`.
- Create `tests/unit/test_unit_<topic>_iter_<YYYY-MM-DD>.py` — **one file per PR**. The naming pattern preserves git blame, makes audit-by-iter legible, and makes single-PR reverts targetable later.
- Write tests targeting that diff from a fresh perspective. These ARE committed — they ride into `main` + PyPI.

**Bundle-level revert-sanity-check** (mandatory, runs once after all files written):

1. Temporarily revert every touched source file to `origin/test`: `git checkout origin/test -- <files>`.
2. Run all new test files: `pytest tests/unit/test_unit_*_iter_<YYYY-MM-DD>.py -v`.
3. Confirm the PR-specific tests **fail** per file — this catches the "test asserts something already true" tautology trap.
4. **Exception:** forward-looking regression-guard tests that don't depend on any specific PR's diff (e.g. signal-propagation boundary pins) may legitimately pass on revert — they're tested by their construction. Flag those explicitly in the bundle summary.
5. Restore the diffs after: `git checkout HEAD -- <files>` (or `git stash pop` if you stashed).

## 5. Full local gate

```
pytest tests/unit
pytest tests/integration -m integration
pylint $(git ls-files '*.py')
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
python -m build && python -m twine check dist/*    # build + check, no upload
```

Non-interactive pytest must override pdb: `--override-ini="addopts=--no-cov -rfE --tb=line"` (the global addopts has `-x --pdb`).

**On red:** bug-fix-only commits to `test` (or to a PR branch if dev-owned). Red after 3 attempts on any single failure → halt.

## 6. `/review-pr` (multi-agent) over the combined diff

Heavier review at this gate than dev's `/review`. Dispatch `/review-pr` over the **combined bundle diff** — individual agents in the multi-agent review can scope to specific files if their finding semantics require it, but the entry point is bundle-wide. Apply correctness/style findings as bug-fix commits to `test`.

## 7. Decide release intent (bundle-level)

If **any** PR in the bundle warrants a PyPI release (bug fix users need, new feature, etc.), set `auto-release` on the upcoming `test → main` PR. Skip the label only if the entire bundle is docs-only / internal-only.

With sweep-all, the bundle inherits the most-permissive intent across its PRs — one ship-worthy fix in a 5-PR bundle means the whole bundle ships. (autonomous-prod gates the actual ship on this label.)

## 8. Promote to main + open back-merge in parallel

```
git push origin test
```

This auto-closes every bundled `dev → test` PR as their head branches become contained in `test`.

```
gh pr create -R Sallenmoore/autonomous --base main --title "test → main: <N bundled iters / cycle summary>" --body "..."
```

PR body should list each bundled PR's iter title and the closed issues across all PRs (use `Closes Sallenmoore/autonomous#<N>` for every underlying issue — auto-closes on `test → main` merge). Apply `auto-release` if step 7 decided yes.

**In the same step**, check `git log origin/dev..origin/test --oneline`. Every listed commit is on `test` but not on `dev` (test-agent bug-fix commits, bundle merge commits, or anything else dev should pick up). If non-empty:

```
gh pr create -R Sallenmoore/autonomous --base dev --head test --title "test → dev: post-cycle back-merge" --body "..."
```

Opening both PRs together — rather than deferring the back-merge until after the user merges `test → main` — keeps dev current with test-agent bug-fixes and avoids the multi-cycle drift window where dev rebases against a stale baseline.

**Watch CI on the `test → main` PR.** Python package matrix (3.11/3.12/3.13) + release-smoke are the gates. `gh pr checks <n>` until green or 3 fix-up amend cycles still red.

**On red:** push **NEW fix-up commits** to `test` (which the PR auto-tracks). Never `--amend`, never force-push — CI is keyed to SHAs; rewriting commits GitHub already saw destroys CI state. After 3 amend cycles still red, halt and notify.

## 9. Exit summary

Post a brief summary and exit:
- `test → main` PR number + bundled-PR count + closed issues
- `test → dev` back-merge PR number (if filed)
- `auto-release` decision (set / skipped — with reason if skipped on docs-only bundle)
- Any halt-trigger that fired and which step
- Any forward-looking tests that legitimately passed the revert-sanity-check in step 4

Do NOT call `ScheduleWakeup`, `CronCreate`, or `Monitor`. Do NOT suggest `/loop`. Do NOT run `./scripts/release.sh` (release authority was moved to autonomous-prod on 2026-05-14; the test agent's job ends at "merged test → main and notified the user").

## Stay-passive rule

The test agent owns its own bug-fix commits on `test`, the committed tests in `tests/unit/`, and the `test → main` + `test → dev` PRs. It does NOT: edit the dev tree, push directly to `dev` or `main`, run `./scripts/release.sh`, force-push to `test`, mutate dev's PR head branches, or merge `test → main` (that's the user). The dev → test PR head branches are dev-owned — fix-up commits land on `test` (the bundle merge baseline), not on dev's branches.

If the user asks for a dev-tree or prod-tree edit during this iteration, respond: "That's outside this iteration's scope — finish the test cycle first, then switch to the dev/prod tree per the CLAUDE.md three-agent topology."

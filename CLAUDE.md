# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`autonomous-app` is a routing framework agnostic containerized service framework published to PyPI. It should layer seamlessly on top of flask, fast-api, and other micro-frameworks. Library source lives under [src/autonomous/](src/autonomous/); the package version is declared in [src/autonomous/__init__.py](src/autonomous/__init__.py) and consumed dynamically by [pyproject.toml](pyproject.toml). Runtime requires Python ≥3.12 per `pyproject.toml`, though CI matrix tests 3.11/3.12/3.13 across the dev / test / main branches ([.github/workflows/python-package.yml](.github/workflows/python-package.yml)). Importing the top-level `autonomous` package calls `load_dotenv()` and exposes the global `log` singleton.

## Coordination with the storyteller agent

StoryTeller has its own dev / test agent pair operating on `/opt/data/storyteller-dev/` and `/opt/data/storyteller-test/`. Those agents do not edit this tree. The relationship is producer (this tree) ↔ consumer (storyteller's trees), mediated by:
- **GitHub issues** for change requests (storyteller → autonomous).
- **PyPI releases** for change deliveries (autonomous → storyteller).
- The `requirements.txt` pin in each storyteller tree (`autonomous-app>=X.Y.Z`) is the version contract.

Storyteller no longer vendors this repo as a submodule (decoupled 2026-05-05); it installs `autonomous-app` from PyPI exclusively. Release handoff: this repo's autonomous-test agent ships via `./scripts/release.sh`, then storyteller-dev runs `bump-autonomous.sh ${NEW_VERSION}` to update its `requirements.txt` pin.

### Issue body template

When the storyteller agent (or any other consumer) needs an autonomous library change, they file an issue against this repo using `gh issue create -R Sallenmoore/autonomous`. Issues from agents follow this body template:

```markdown
## Symptom
<one-paragraph user-visible behavior>

## Repro
<minimum-viable code or steps>

## Suspected location
<file:line in src/autonomous/...>

## Consumer-side workaround (if any)
<the temporary patch the consumer is using until library lands a fix>

## Suggested fix shape
<one-paragraph; not binding on the autonomous agent>
```

Issues feed autonomous-dev's iteration loop (see `## Three-Agent Pipeline`).

## Commands

All dev workflows go through the [makefile](makefile), which `include .env` — expect a `.env` at repo root with DB/Redis/AI credentials.

The test layout was split into hermetic unit / live-stack integration / opt-in perf tiers (MIGRATIONS.md Item 21). `pytest` invoked bare picks up `[tool.pytest.ini_options].testpaths = ["tests/unit"]`, so the default run is hermetic — no Mongo / Redis / Ollama required, safe on any laptop.

- `make test` — hermetic unit tests only: `python -m pytest tests/unit`. This is the default fast-feedback target.
- `make test-int` — integration tier: brings up the Compose stack (`inittests`) then runs `pytest tests/integration -m integration`. Requires Docker.
- `make test-perf` — opt-in `pytest-benchmark` perf suite under `tests/perf/`. Doesn't gate `test-all`; runners flake.
- `make test-all` (alias `make tests`) — `test` then `test-int` (unit-first so failures surface fast).
- `make inittests` / `make cleantests` — bring the Compose stack in [tests/docker-compose.yml](tests/docker-compose.yml) up/down without running pytest. `inittests` also `pip install -e ".[all]"` and refreshes requirements.
- `make docs` / `make cleandocs` — build/clean the Sphinx HTML reference under `docs/_build/html/` via `sphinx -W -b html docs docs/_build/html` ([docs/conf.py](docs/conf.py) drives extensions, mocks, theme; deps live in [requirements-docs.txt](requirements-docs.txt) and the `[docs]` extra). `-W` mirrors Read the Docs' `fail_on_warning`. The legacy zero-dependency Markdown generator is archived at [scripts/_archive/gen_docs.py](scripts/_archive/gen_docs.py) for reference.
- `make docs-serve` — live-reload server via `sphinx-autobuild`; iterates on the guides without manual rebuilds.
- `make package` — `python -m build` + `twine upload --skip-existing` to PyPI. Bump `__version__` in [src/autonomous/__init__.py](src/autonomous/__init__.py) first. **Side effect**: this ALWAYS attempts a PyPI upload; `--skip-existing` makes it a silent no-op when the version is already published, but a real publish for new versions. For local validation without uploading, run `python -m build && python -m twine check dist/*` directly.
- `./scripts/release.sh` — preferred release entrypoint: bumps the patch version in `src/autonomous/__init__.py`, runs `make package` (build + twine upload), then commits and pushes `origin/main`. Use this for routine patch releases. For non-patch bumps, edit `__version__` manually first, then run the script (or fall back to `make package`).
- CI lints with `flake8 . --select=E9,F63,F7,F82` (syntax-only gate) plus a non-blocking `--max-complexity=10 --max-line-length=127` pass.

Pytest config in `[tool.pytest.ini_options]`: `addopts = "--cov=autonomous -rx -l -x -s --log-level=INFO --ignore=src --no-cov-on-fail -v --pdb --cov-reset"` and loads `tests/.testenv`. Tests stop on first failure (`-x`) and drop into pdb (`--pdb`) — be aware when running non-interactively (CI passes `--pdbcls` overrides). Markers: `integration` (live services) and `perf` (benchmarks).

The package ships per-feature extras defined in [pyproject.toml](pyproject.toml) (MIGRATIONS.md Item 9): `[tasks]`, `[images]`, `[ai]`, `[github]`, `[server]`, `[dev]`, `[all]`. Install only what the consumer uses, e.g. `pip install autonomous-app[ai,tasks]`. The smoke test (`scripts/smoke_test.sh`) installs `[all]` and imports every subpackage.

Consumer-visible changes ship in [MIGRATIONS.md](MIGRATIONS.md) (most-recent-first, with replacement recipes for removed symbols). Update it for any change that breaks or alters the public API of a subpackage that downstream projects import.

## Architecture

The library is a set of loosely-coupled service wrappers glued together by the `AutoModel` ORM layer. Each subpackage assumes a companion container (MongoDB, Redis, Ollama, a media/embeddings service) reachable over the intranet.

### `autonomous.db` — vendored MongoEngine-style ORM
[src/autonomous/db/](src/autonomous/db/) is a full in-tree fork of a MongoEngine-like ODM: `Document`, `QuerySet`, `signals`, `fields`, `context_managers`, `dereference`, `db_sync`. The public surface is re-exported from [src/autonomous/db/__init__.py](src/autonomous/db/__init__.py) — import from `autonomous.db`, not the submodules. [src/autonomous/db/db_sync.py](src/autonomous/db/db_sync.py) enqueues debounced vector-embedding sync jobs via Redis/RQ and calls out to `MEDIA_API_BASE_URL` (default `http://media_ai:5005`) for embeddings.

### `autonomous.model` — AutoModel ORM surface
[src/autonomous/model/automodel.py](src/autonomous/model/automodel.py) defines `AutoModel(Document)`, the abstract base every app model should extend. **Connection is lazy.** Importing the module does NOT touch Mongo; `_ensure_connected()` runs on the first ORM operation (`save`/`get`/`all`/`where`/etc.) and calls `connect_from_env()` with `DB_HOST`/`DB_PORT`/`DB_USERNAME`/`DB_PASSWORD`/`DB_DB`. Consumers wanting explicit startup-time control call `autonomous.init(**overrides)` (re-exported from `src/autonomous/__init__.py`) or `connect_from_env` directly. This is why `pytest tests/unit/` is hermetic — unit tests that never call an ORM operation never need MongoDB. It also wires four `auto_pre/post_init/save` signal hooks that subclasses can override.

`AutoModel.load_model(name)` walks `__subclasses__()` at call time to resolve string → class, so dynamic model lookups depend on the target class having been imported already.

[src/autonomous/model/autoattr.py](src/autonomous/model/autoattr.py) wraps the db fields as `StringAttr`, `IntAttr`, `ListAttr`, `ReferenceAttr`, etc., with coercion behavior (e.g. `IntAttr` strips commas from strings, `ListAttr` splits on `;`/`,`). Prefer these over raw `db.fields` in models.

### `autonomous.ai` — pluggable AI agents
[src/autonomous/ai/baseagent.py](src/autonomous/ai/baseagent.py) defines `BaseAgent(AutoModel)` with a `MODEL_REGISTRY` mapping provider strings (`"local"`, `"gemini"`, `"openai"`, `"mock"`) to client classes in [src/autonomous/ai/models/](src/autonomous/ai/models/). The `"mock"` adapter ([src/autonomous/ai/models/mock_model.py](src/autonomous/ai/models/mock_model.py)) is what tests use to avoid Ollama/Gemini reachability. Agents (`JSONAgent`, `TextAgent`, `ImageAgent`, `AudioAgent`) lazily instantiate the right client via `get_client()` and re-instantiate if the `provider` attr changes. `LocalAIModel` talks to Ollama (`OLLAMA_API_BASE_URL`) and a media service (`MEDIA_API_BASE_URL`); `GeminiAIModel` uses `google-genai`. Individual agents can override provider via env var (e.g. `JSON_AI_AGENT`).

### `autonomous.taskrunner` — RQ-backed background jobs
[src/autonomous/taskrunner/autotasks.py](src/autonomous/taskrunner/autotasks.py) exposes `AutoTasks` with three priority queues (`high`/`default`/`low`) on a shared Redis connection configured via `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD`/`REDIS_USERNAME`/`REDIS_DB`. `AutoTask` wraps `rq.job.Job` and adds a `meta(k, v)` helper used throughout the AI agents to attach progress to the current job.

### `autonomous.web` — framework-agnostic WSGI shim
[src/autonomous/web/response.py](src/autonomous/web/response.py) defines `Response` (WSGI-callable); [src/autonomous/web/session.py](src/autonomous/web/session.py) defines a `SessionStore` protocol plus two stores: `ContextSession` (in-memory dict, per-request) and `SignedCookieSession` (stdlib HMAC, no extra deps). Host code calls `bind_session(store)` per request; the auth layer reads/writes session state through this shim, which is why the same OAuth flows run unchanged under Flask, FastAPI, Starlette, or pure WSGI.

### `autonomous.auth` — Authlib OAuth2
[src/autonomous/auth/autoauth.py](src/autonomous/auth/autoauth.py) is the base OAuth2 client; [github.py](src/autonomous/auth/github.py) and [google.py](src/autonomous/auth/google.py) are provider subclasses. `AutoAuth.auth_required(guest=, admin=)` is the framework-agnostic view decorator (gates by `is_guest` / `is_admin` predicates, not strict roles); `current_user()` reads the bound session's `"user"` key (via `autonomous.web.get_session()`) and falls back to `User.get_guest()`. [src/autonomous/auth/user.py](src/autonomous/auth/user.py) defines `AutoUser(AutoModel)` (base, with `role` field) and `User(AutoUser)` (project-extendable subclass) — note `is_guest` is true when *unauthenticated* OR `role == "guest"`, so it's a predicate, not a strict role check.

### Other subsystems
- [src/autonomous/storage/](src/autonomous/storage/) — `ImageStorage` (Pillow, writes WebP + thumbnail/small/medium/large variants under `static/images/`) and `LocalStorage`.
- [src/autonomous/apis/version_control/](src/autonomous/apis/version_control/) — PyGithub wrappers (`GHRepo`, `GHOrganization`, `GHCallbacks`).
- [src/autonomous/logger.py](src/autonomous/logger.py) — `log` is a callable singleton that writes to `logs/current_run_error_log.log` + a dated archive; pass `_print=True` to also echo to stdout. Level controlled by `LOG_LEVEL` env var.

## Three-Agent Pipeline

The autonomous library runs as a closed-loop pipeline with three agents — paired with a downstream consumer (storyteller currently) that files inbound issues. The flow is **consumer issue OR CI release-smoke fail → dev → test → main → [user: `run prod`] → PyPI release → CI release-smoke verify**, with two independent test perspectives, asymmetric review gates, and explicit halt triggers. Full design + history: `~/.claude/plans/autonomous-process-codification.md` and `~/.claude/plans/agent-topology.md`.

**Release ownership (changed 2026-05-14):** autonomous-prod runs `./scripts/release.sh` under the user's manual `run prod` trigger, but **only** when the merged `test → main` PR carries the `auto-release` label. autonomous-test sets the label as the release-intent signal; autonomous-prod gates the actual ship on it. Docs-only / internal-only PRs land on main without a corresponding PyPI bump. autonomous-prod also owns **post-release smoke verification** (`scripts/smoke_test.sh`) on the same `run prod` invocation that produced the release, and files / updates `[smoke-fail]` issues on signature mismatch. CI `release-smoke.yml` runs in parallel on the release commit as a public-audit layer in a clean GitHub Actions environment; the two layers are complementary, and disagreement between them is itself signal worth investigating. **No polling** — prod is manual-trigger only.

### Agents at a glance

| Agent | Branch | Tree | Triggered by | Writes | Review skill |
|---|---|---|---|---|---|
| **autonomous-prod** | `main` | `/opt/projects/autonomous/` | manual `run prod` from user (no polling) | `./scripts/release.sh` (version bump + PyPI upload + push) when PR has `auto-release`; `[smoke-fail] <v>: <signature>` issues against `Sallenmoore/autonomous` on smoke-test failure | n/a |
| **autonomous-dev** | `dev` | `/opt/projects/autonomous-dev/` | open `Sallenmoore/autonomous` issues | library code + ephemeral tests in `tests/_dev_local/` (gitignored) | `/review` before opening `dev → test` |
| **autonomous-test** | `test` | `/opt/projects/autonomous-test/` | open `dev → test` PRs | committed tests + bug-fix commits | `/review-pr` (multi-agent) before opening `test → main` |

dev and test run as `/loop` in dynamic / self-paced mode. **prod does NOT loop** — it runs one iteration per `run prod` user command and then stops. The dev agent does not push to `test`. The test agent does not edit the dev tree. Coordination is through PRs, issues, and labels (`smoke-fail`, `auto-filed`, `auto-release`, `awaiting-upstream`, `human-only`, `feature-request`). `auto-release` is set by the test agent and read by the prod agent as the ship-or-skip gate.

### Invariants

The procedures below describe how the contract is satisfied today. The contract itself doesn't change when CI tiers, review tooling, or release cadence evolve — re-read this table before editing the procedure to make sure the change preserves what doesn't move.

| Invariant | Source | Enforcement |
|---|---|---|
| Test agent writes tests INDEPENDENTLY of dev | Two-perspective design (`## Two-perspective testing`) | `tests/_dev_local/` is gitignored, so dev's tests are invisible in the PR diff the test agent works from |
| All bundled work goes through the full local + CI gate | No fast-paths | No docs-only skip; `/review-pr` runs at the test gate even on small bundles |
| Bug-fix commits land on `test`, never on dev's PR branch | One-way info flow (dev → test → main) | Test agent has no write capability against the dev tree or dev-owned PR head branches |
| Manual commits on `main` get reconciled before the next cycle | Halt trigger #4 + step 1 drift inspection | Pre-cycle `git log origin/test..origin/main --oneline` is part of the refresh step, not just a reactive halt |
| `test → dev` back-merge opens parallel to `test → main` | Keeps dev current with bug-fix commits the test agent landed directly on test | Both PRs are opened in step 8 — back-merge is not deferred until after main merge |

### Interactive mode

When a human invokes Claude Code interactively in any of the three trees (most often `/opt/projects/autonomous/` since that's the canonical clone), the loop discipline above is suspended in favor of explicit human direction. The agent may edit files, push branches, and open PRs from the prod tree under direct human prompts without violating the read-only constraint — that constraint applies to *autonomous* (loop-driven) operation, not human-prompted work. Project conventions (PRs target `main`, run `/review` before opening, ultrareview before merging, etc.) still apply.

In short: tree assignment dictates default loop behavior, not absolute capability. Outside an interactive session, the agent in each tree obeys its role; inside one, it follows the human.

### autonomous-prod (release + smoke operator)

Manual-triggered (no `/loop`, no polling). Owns the release step (`./scripts/release.sh`, as of 2026-05-14) and post-release smoke verification (`./scripts/smoke_test.sh`). Does not edit library source — its writes are limited to: the version-bump commit + push that `release.sh` produces, the PyPI upload, and `[smoke-fail]` issues filed/updated against `Sallenmoore/autonomous` when smoke fails. Per invocation:

1. **Check for open `test → main` PR.** `gh pr list -R Sallenmoore/autonomous --base main --state open`.
2. **Merge + pull.**
   - Open PR → `gh pr merge <num> --merge` then `git pull --ff-only origin main`.
   - No PR but `main` moved (someone merged via UI) → `git pull --ff-only origin main`.
   - No PR and `main` unchanged → **stop and report "nothing to deploy"**. Skip the remaining steps.
   - **GitHub refuses merge despite green CI** (`mergeable=CONFLICTING / state=DIRTY` while all checks pass) → verify locally: `git fetch origin pull/<PR>/head:probe-pr && git checkout -B merge-probe origin/main && git merge --no-commit --no-ff probe-pr`. If the local merge is clean (no conflict files), GitHub's mergeability cache is stale relative to the current base — usually because `main` advanced after the PR was opened. **Halt and notify the user**; do not push to `test` to refresh the cache (writes to `test` are the test agent's exclusive responsibility per the invariants). The test agent's step 1 main-drift check will back-merge `main` into `test` on its next iteration, which refreshes the PR's mergeability; then re-run `run prod`. If the local merge actually conflicts, also halt — same rule: prod doesn't resolve test-side conflicts.
3. **Release (gated on `auto-release` label).** Inspect the merged PR's labels (or, for UI-merged commits with no current PR, look up the merge commit's source PR via `gh`). If `auto-release` is present, run `./scripts/release.sh` — bumps the patch in `src/autonomous/__init__.py`, runs `make package` (build + twine upload), commits + pushes the bump to `origin/main`. On `release.sh` failure: surface stderr and **halt**, do not retry (releases are not idempotent). If `auto-release` is absent (or no source PR is identifiable), skip the release and jump to step 5 — the change landed on main but is not deemed ship-worthy by the test agent.
4. **Verify + smoke** *(only if step 3 released)*.
   - **Version verify:** probe `https://pypi.org/pypi/autonomous-app/<released-version>/json` for HTTP 200, then compare `__version__` in `origin/main:src/autonomous/__init__.py` to `info.version` from `https://pypi.org/pypi/autonomous-app/json`. Both endpoints agreeing → clean. Disagreement after ~30s of retry → flag (`info.version` is CDN-cached and typically lags upload by 5–60s, so brief lag is expected, not drift).
   - **Smoke:** run `./scripts/smoke_test.sh <released-version>` — or `SMOKE_CONTAINER=python:3.13-slim ./scripts/smoke_test.sh <v>` if the host Python is broken (Fedora-like hosts where pyenv lacks `_ctypes`). The script installs `autonomous-app[all]==<v>` with PyPI-propagation retries, imports each top-level subpackage, and verifies the installed `__version__` matches.
   - **Smoke passes** → optionally comment `✅ smoke passed` on the merged `test → main` PR.
   - **Smoke fails** → parse `SIGNATURE: <stage>:<error_class>:<location>` from stderr's last line. Fingerprint by signature. Issue lifecycle:
     - No matching open issue → `gh issue create -R Sallenmoore/autonomous` titled `[smoke-fail] <v>: <signature>`, body with full stderr, labels `smoke-fail` + `auto-filed` + `release:<v>`.
     - Matching open → comment with version + new stderr.
     - Matching closed → reopen as regression.
5. **Notify + stop.** One-pulse summary: merged PR + label state, deployed SHA + version (or "merge only — no release" if `auto-release` was absent), smoke result (`SIGNATURE: ok` or signature + issue # filed/updated), count of open issues against `Sallenmoore/autonomous`. Then wait for the next user command.

Local smoke (`scripts/smoke_test.sh`, run by prod at step 4) and CI `release-smoke.yml` (runs automatically on release commits to main) form a two-layer post-publish check: local smoke gives the operator immediate feedback under `run prod`; CI provides the public-audit layer that runs in a clean GitHub Actions environment and catches things the local environment may mask. **Only local prod files `[smoke-fail]` issues** — CI just runs `smoke_test.sh` and surfaces failure as a red check on the release commit. A red CI release-smoke after a green local smoke is the halt-trigger #5 case (human triage).

### autonomous-dev loop

Per iteration:

1. **Refresh.** `git fetch origin && git checkout dev && git pull --ff-only`. If an open `test → dev` back-merge PR exists, pull and merge it locally first. Conflict → halt.
2. **Pick an issue.** `gh issue list -R Sallenmoore/autonomous --state open --limit 50 --json number,title,labels,assignees,createdAt`. Prioritize `smoke-fail` + `auto-filed` (autonomous-prod feed). Skip `feature-request`, `awaiting-upstream`, `human-only`. Autonomous *is* the upstream — no triage-and-route step (unlike storyteller-dev which routes some issues here).
3. **Halt** if the issue's hypothesis is unclear (vague repro, conflicting info, multi-system root cause).
4. **Fix.** `git checkout -b fix/<issue>-<slug>`. Implement.
5. **Ephemeral tests.** Write tests in `tests/_dev_local/` (gitignored). Run with `pytest tests/_dev_local/ -v`. **Not committed** — the test agent will write its own independent tests.
6. **Run existing suite.** `pytest tests/unit/ && pytest tests/integration/`. Red after 3 fix attempts → halt.
7. **`/review` skill, then fix.** Apply correctness/style findings.
8. **Open PR `dev → test`.** Use `Closes Sallenmoore/autonomous#<N>` so the issue auto-closes when the change reaches main.

### autonomous-test loop

Per iteration:

1. **Refresh + main-drift check.** `git fetch origin --prune && git checkout test && git pull --ff-only`. Then inspect `git log origin/test..origin/main --oneline` — every commit listed is on `main` but not on `test`. If non-empty: any subject *not* shaped like `Bump autonomous version to X.Y.Z` (the `release.sh` push) is a manual user edit and should be back-merged into `test` (`git merge --no-ff origin/main`) before this cycle proceeds, or halt and ask the user if it's not a recognized edit. Doing this proactively at step 1 catches drift cheaply rather than waiting for halt trigger #4 to fire mid-cycle.
2. **Poll for ALL open `dev → test` PRs (sweep-all).** `gh pr list -R Sallenmoore/autonomous --base test --state open --json number,title,headRefName,labels,createdAt --jq 'sort_by(.createdAt)'`. None → fall through to step 9. One or more → bundle **all** into this cycle. Process oldest first by `createdAt` so each subsequent branch was built on a baseline contained in the previous merge. (Sweep-all changeover: 2026-05-15 user direction — replaces prior pick-one semantics.)
3. **Pull and test-merge each PR locally, in order.** For each PR in the sorted list, in sequence:
   - `gh pr checkout <PR>; git checkout test; git merge --no-ff <PR-branch> -m "Merge PR #<N> (<title>) into test"`.
   - **Conflict during merge → halt** (sweep-all assumes independent diffs; overlap is the user's call on precedence).
   At the end of step 3, `test` (local) contains all bundled PRs' changes layered in `createdAt` order.
4. **Write independent committed tests for each PR's diff.** For each PR in the bundle:
   - Read its diff (`gh pr diff <PR>`).
   - Create `tests/unit/test_unit_<topic>_iter_<date>.py` — **one file per PR**, naming pattern preserves git blame and audit-by-iter clarity (and makes single-PR reverts targetable later).
   - Write tests targeting that diff from a fresh perspective (without seeing dev's `tests/_dev_local/`, which are gitignored).
   **These ARE committed** — they ride into main + PyPI. After all PRs' test files are written: **bundle-level revert-sanity-check** — temporarily revert every touched source file to `origin/test` (`git checkout origin/test -- <files>`), run all new test files, confirm the PR-specific tests fail per file (catches the "test asserts something already true" tautology trap). Forward-looking regression-guard tests that don't depend on any specific PR's diff (e.g. signal-propagation boundary pins) may legitimately pass on revert — they're tested by their construction. Restore the diffs after.
5. **Full local gate.**
   ```bash
   pytest tests/unit/
   pytest tests/integration/
   pylint $(git ls-files '*.py')
   flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
   python -m build && python -m twine check dist/*    # build + check, no upload
   ```
   On red: bug-fix-only commits to `test` (or to PR branch if dev-owned). Red after 3 attempts → halt.
6. **`/review-pr` (multi-agent) skill, then fix.** Heavier review at this gate. Dispatched over the **combined diff** for the whole bundle — individual agents can scope to specific files if their finding semantics require it, but the entry point is bundle-wide.
7. **Decide release intent (bundle-level).** If *any* PR in the bundle warrants a PyPI release (bug fix users need, new feature, etc.), apply the `auto-release` label to the `test → main` PR. Skip the label only if the entire bundle is docs-only / internal-only. With sweep-all, the bundle inherits the most-permissive intent across its PRs.
8. **Promote to main + open back-merge in parallel.** `git push origin test` — auto-closes every bundled `dev → test` PR as their head branches become contained in `test`. Then `gh pr create --base main --title "test → main: <N bundled iters / cycle summary>"`. The PR body should list each bundled PR's iter title and the closed issues across all PRs (use `Closes Sallenmoore/autonomous#<N>` for every underlying issue so they auto-close on `test → main` merge). Then, in the same step, check `git log origin/dev..origin/test --oneline` — every listed commit is on `test` but not on `dev` (test agent bug-fix commits, the bundle's merge commits, or anything else the dev tree should pick up). If non-empty: `gh pr create --base dev --head test --title "test → dev: post-cycle back-merge"`. Opening both PRs together — rather than deferring the back-merge until after the user merges `test → main` — keeps dev current with test agent bug-fixes and avoids the multi-cycle drift window where dev rebases against a stale baseline. Watch GitHub CI on the `test → main` PR (Python package matrix + release smoke — these are the gates). Amend until green; red after 3 amends → halt. Notify user when ready to merge.
9. **After user merges `test → main`:** test agent does nothing further. If the merged PR carried `auto-release`, autonomous-prod is responsible for running `./scripts/release.sh` on its next iteration (release authority was moved from test → prod on 2026-05-14). The `test → dev` back-merge PR was already opened in step 8 — the user merges it independently of `test → main`, so no new PR is filed here.

### Halt triggers (all autonomous agents)

When any fire, the agent stops, posts a summary, and waits for user input. On resume, the agent picks up where it stopped — does not skip the failing item.

1. **Tests red after 3 fix attempts.** Local gate (test) or GitHub CI on a PR.
2. **Issue scope unclear** (dev only).
3. **Merge conflict on back-merge.** `test → dev` can't auto-resolve.
4. **Unexpected commit on main.** A commit lands on `main` that wasn't part of any `test → main` PR or a `release.sh` version-bump push. All agents pause, sync from `origin/main`, ask user.
5. **CI release-smoke fails immediately after `run prod`.** Prod published a release and the `release-smoke.yml` CI workflow reports failure against it. Stop polling on dev/test; this is "released and immediately broken" and needs human triage — autonomous-prod owns the release decision but does not auto-recover from a botched publish.
6. **Sweep-all merge conflict (test agent only).** During step 3's per-PR merge loop, two bundled PRs touch the same lines. Sweep-all assumes independent diffs; overlap is the user's call on which takes precedence. Halt with the conflicting paths in the summary so the user can (a) reorder the PRs, (b) drop one from the bundle, or (c) resolve manually. Resume by re-running `run tests` after the user's decision.

### Two-perspective testing

| Agent | Test location | Committed? | Visible to other agent? |
|---|---|---|---|
| dev | `tests/_dev_local/` | no (`.gitignore` blocks) | no — never appears in PR diff |
| test | `tests/unit/`, `tests/integration/` | yes | yes — ships to main + PyPI |

If both agents wrote tests in the same place, the test agent would just re-run dev's tests and rubber-stamp them. Gitignoring dev's tests forces the test agent to write tests independently from the PR diff alone — a genuine second perspective.

### Releasing

Use [scripts/release.sh](scripts/release.sh):
- Verifies on `main`, fast-forwarded, working tree clean, PyPI creds present
- Computes next patch version from `__version__`
- Writes the bump
- Runs `make package` (build + twine check + twine upload)
- Commits + pushes `origin/main`

After the test→main merge, the autonomous-prod agent runs `release.sh` automatically when the PR carries the `auto-release` label (release authority moved from test → prod on 2026-05-14; see `## Three-Agent Pipeline` above). Manual invocation is still supported for ad-hoc patches.

## Known broken workflows

- **`scripts/release.sh` requires an active venv with pip on PATH.** On Fedora-like hosts, system `python3` doesn't bundle pip, and `make package` calls `python3 -m pip install --upgrade build twine ...`. The script's preflight doesn't catch this — failures land mid-`make package` after the version bump is already written, and the script's revert path catches it (so no permanent damage). Run inside an activated venv with pip available, e.g. `source .venv/bin/activate && ./scripts/release.sh`.

## Conventions worth knowing

- **Never import from db submodules directly** — go through `autonomous.db`, which re-exports the intended public names.
- **MongoDB is required at import time** for anything under `autonomous.model` or `autonomous.ai`; unit tests that touch these need the Compose stack up.
- **Models must be imported before `AutoModel.load_model("Name")` will resolve them**, because resolution walks `__subclasses__()`.
- **Use [`autonomous.ai.retry.retry`](src/autonomous/ai/retry.py) for bounded HTTP retry** rather than ad-hoc `try/except` loops; backlog items in README #5, #6, #16, #21 all exist because callers bypass it.
- **Existing backlog lives in [README.md](README.md) "Task List"** — 28 items with file:line anchors and impact axes (security/stability/functionality/efficiency/usability). Before accepting a new issue, check whether it duplicates a backlog item; close as duplicate or merge scope when it does.
- **CI fires on `dev`, `test`, and `main` branches.** Feature PRs target `test` (not `dev` directly and not `main`); see "Three-Agent Pipeline" above for the dev → test → main → `run prod` flow and the `auto-release` label gate.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`autonomous-app` is a routing framework agnostic containerized service framework published to PyPI. It should layer seamlessly on top of flask, fast-api, and other micro-frameworks. Library source lives under [src/autonomous/](src/autonomous/); the package version is declared in [src/autonomous/__init__.py](src/autonomous/__init__.py) and consumed dynamically by [pyproject.toml](pyproject.toml). Runtime requires Python ≥3.12 per `pyproject.toml`, and the CI matrix tests 3.12/3.13 across the dev / test / main branches ([.github/workflows/python-package.yml](.github/workflows/python-package.yml)). Importing the top-level `autonomous` package calls `load_dotenv()` and exposes the global `log` singleton.

## Coordination with the storyteller agent

StoryTeller has its own dev / test agent pair operating on `/opt/projects/storyteller/dev/` and `/opt/projects/storyteller/test/` (moved from `/opt/data/` alongside this tree on 2026-05-25 — autonomous is a project, not a homelab service). Those agents do not edit this tree. The relationship is producer (this tree) ↔ consumer (storyteller's trees), mediated by:
- **GitHub issues** at `https://github.com/Sallenmoore/autonomous/issues` for change requests (storyteller → autonomous).
- **PyPI releases** for change deliveries (autonomous → storyteller).
- The `requirements.txt` pin in each storyteller tree (`autonomous-app>=X.Y.Z`) is the version contract.

Storyteller no longer vendors this repo as a submodule (decoupled 2026-05-05); it installs `autonomous-app` from PyPI exclusively. Release handoff: this repo's autonomous-test agent ships via `./scripts/release.sh`, then storyteller-dev runs `bump-autonomous.sh ${NEW_VERSION}` to update its `requirements.txt` pin.

### Issue body template

When the storyteller agent (or any other consumer) needs an autonomous library change, they file an issue against this repo via the GitHub API. The canonical repo is `Sallenmoore/autonomous` on `github.com`; `gh` is authenticated natively on this host — no token env or auth preamble is needed. Standard form (matches the agent slash commands at `.claude/commands/{dev,test,prod}-agent.md`):

```bash
gh issue create --repo Sallenmoore/autonomous \
  --title "<title>" \
  --body "<body>" \
  --label bug   # or feature-request, etc. — repeat --label per label
```

Issues from agents follow this body template:

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

All dev workflows go through the [makefile](makefile), which does `-include .env` (leading dash — a **missing `.env` is non-fatal**; the prod tree has none and still builds/releases). `.env` carries DB/Redis/AI credentials for the live-stack targets. **PyPI release credentials are separate**: `make package` / `release.sh` read them from `~/.pypirc` (a `[pypi]` section) or `TWINE_USERNAME`/`TWINE_PASSWORD` — never from `.env`.

The test layout was split into hermetic unit / live-stack integration / opt-in perf tiers (MIGRATIONS.md Item 21). `pytest` invoked bare picks up `[tool.pytest.ini_options].testpaths = ["tests/unit"]`, so the default run is hermetic — no Mongo / Redis / Ollama required, safe on any laptop.

- `make test` — hermetic unit tests only: `python -m pytest tests/unit`. This is the default fast-feedback target.
- `make test-int` — integration tier: brings up the Compose stack (`inittests`) then runs `pytest tests/integration -m integration`. Requires Docker.
- `make test-perf` — opt-in `pytest-benchmark` perf suite under `tests/perf/`. Doesn't gate `test-all`; runners flake.
- `make test-all` (alias `make tests`) — `test` then `test-int` (unit-first so failures surface fast).
- `make inittests` / `make cleantests` — bring the Compose stack in [tests/docker-compose.yml](tests/docker-compose.yml) up/down without running pytest. `inittests` also `pip install -e ".[all]"` and refreshes requirements.
- `make docs` / `make cleandocs` — build/clean the Sphinx HTML reference under `docs/_build/html/` via `sphinx -W -b html docs docs/_build/html` ([docs/conf.py](docs/conf.py) drives extensions, mocks, theme; deps live in [requirements-docs.txt](requirements-docs.txt) and the `[docs]` extra). `-W` mirrors Read the Docs' `fail_on_warning`. The legacy zero-dependency Markdown generator is archived at [scripts/_archive/gen_docs.py](scripts/_archive/gen_docs.py) for reference.
- `make docs-serve` — live-reload server via `sphinx-autobuild`; iterates on the guides without manual rebuilds.
- `make package` — `python -m build` + `twine upload --skip-existing` to PyPI. Bump `__version__` in [src/autonomous/__init__.py](src/autonomous/__init__.py) first. **Side effect**: this ALWAYS attempts a PyPI upload; `--skip-existing` makes it a silent no-op when the version is already published, but a real publish for new versions. For local validation without uploading, run `python -m build && python -m twine check dist/*` directly.
- `./scripts/release.sh` — preferred release entrypoint: bumps the patch version in `src/autonomous/__init__.py`, runs `make package` (build + twine upload), then commits and pushes `origin/main`. Use this for routine patch releases. For non-patch bumps, edit `__version__` manually first, then run the script (or fall back to `make package`). **It gates the upload on both sides via [scripts/pypi_release_check.py](scripts/pypi_release_check.py)** (#233): it refuses to build if the target version is *already* on PyPI — because `--skip-existing` would make that upload a silent no-op while the script still committed, pushed and reported success — and after uploading it *confirms* the version is on the index — polling ~60s, because PyPI's JSON index lags a successful upload. **That post-check is advisory and never reverts.** Once `make package` exits 0 the bytes are published whether or not the index shows them yet, so the safe direction is always to record the bump; reverting would put the repo BEHIND what is published. Learned on 0.3.176: the first version of this check read a stale index, called a landed upload a failure, and reverted — manufacturing the exact divergence it was written to prevent. The load-bearing gate is the pre-flight `--assert-absent`, which runs before anything has changed. An unreadable index exits `2`: warn, never block. This is why "the repo says it shipped" and "PyPI has it" can no longer diverge silently; if you are ever debugging that claim again, read the wheel, not the commit log.
- CI lints with `flake8 . --select=E9,F63,F7,F82` (syntax-only gate) plus a non-blocking `--max-complexity=10 --max-line-length=127` pass.

Pytest config in `[tool.pytest.ini_options]`: `addopts = "--cov=autonomous -rx -l -x -s --log-level=INFO --ignore=src --no-cov-on-fail -v --pdb --cov-reset"` and loads `tests/.testenv`. Tests stop on first failure (`-x`) and drop into pdb (`--pdb`) — be aware when running non-interactively (CI runs bare `pytest` with no override; locally pass `-o addopts=""` or `-p no:pdb`). Markers: `integration` (live services) and `perf` (benchmarks).

The package ships per-feature extras defined in [pyproject.toml](pyproject.toml) (MIGRATIONS.md Item 9): `[tasks]`, `[images]`, `[ai]`, `[server]`, `[embeddings]`, `[dev]`, `[docs]`, `[all]` (`[all]` = tasks + images + ai + server; it skips the torch-heavy `[embeddings]`). Install only what the consumer uses, e.g. `pip install autonomous-app[ai,tasks]`. The smoke test (`scripts/smoke_test.sh`) installs `[all]` and imports every subpackage.

Consumer-visible changes ship in [MIGRATIONS.md](MIGRATIONS.md) (most-recent-first, with replacement recipes for removed symbols). Update it for any change that breaks or alters the public API of a subpackage that downstream projects import.

## Architecture

The library is a set of loosely-coupled service wrappers glued together by the `AutoModel` ORM layer. Each subpackage assumes a companion container (MongoDB, Redis, Ollama, a media/embeddings service) reachable over the intranet.

### `autonomous.db` — vendored MongoEngine-style ORM
[src/autonomous/db/](src/autonomous/db/) is a full in-tree fork of a MongoEngine-like ODM: `Document`, `QuerySet`, `signals`, `fields`, `context_managers`, `dereference`, `db_sync`. The public surface is re-exported from [src/autonomous/db/__init__.py](src/autonomous/db/__init__.py) — import from `autonomous.db`, not the submodules. [src/autonomous/db/db_sync.py](src/autonomous/db/db_sync.py) enqueues debounced vector-embedding sync jobs via Redis/RQ and calls out to `MEDIA_API_BASE_URL` (default `http://media_ai:5005`) for embeddings.

### `autonomous.model` — AutoModel ORM surface
[src/autonomous/model/automodel.py](src/autonomous/model/automodel.py) defines `AutoModel(Document)`, the abstract base every app model should extend. **Connection is lazy.** Importing the module does NOT touch Mongo; `_ensure_connected()` runs on the first ORM operation (`save`/`get`/`all`/`where`/etc.) and calls `connect_from_env()` with `DB_HOST`/`DB_PORT`/`DB_USERNAME`/`DB_PASSWORD`/`DB_DB`. Consumers wanting explicit startup-time control call `autonomous.init(**overrides)` (a thin wrapper defined in `src/autonomous/__init__.py`) or `connect_from_env` directly. This is why `pytest tests/unit/` is hermetic — unit tests that never call an ORM operation never need MongoDB. It also wires four `auto_pre/post_init/save` signal hooks that subclasses can override.

`AutoModel.load_model(name)` walks `__subclasses__()` at call time to resolve string → class, so dynamic model lookups depend on the target class having been imported already.

[src/autonomous/model/autoattr.py](src/autonomous/model/autoattr.py) wraps the db fields as `StringAttr`, `IntAttr`, `ListAttr`, `ReferenceAttr`, etc., with coercion behavior (e.g. `IntAttr` strips commas from strings, `ListAttr` splits on `;`/`,`). Prefer these over raw `db.fields` in models.

### `autonomous.ai` — pluggable AI agents
[src/autonomous/ai/baseagent.py](src/autonomous/ai/baseagent.py) defines `BaseAgent(AutoModel)` with a `MODEL_REGISTRY` mapping provider strings (`"local"`, `"gemini"`, `"openai"`, `"mock"`, `"flux"`, `"litellm"`) to client classes in [src/autonomous/ai/models/](src/autonomous/ai/models/). The `"mock"` adapter ([src/autonomous/ai/models/mock_model.py](src/autonomous/ai/models/mock_model.py)) is what tests use to avoid Ollama/Gemini reachability. Agents (`JSONAgent`, `TextAgent`, `ImageAgent`, `AudioAgent`) lazily instantiate the right client via `get_client()` and re-instantiate if the `provider` attr changes. `LocalAIModel` talks to Ollama (`OLLAMA_API_BASE_URL`) and a media service (`MEDIA_API_BASE_URL`); `GeminiAIModel` uses `google-genai`. Individual agents can override provider via env var (e.g. `JSON_AI_AGENT`).

### `autonomous.taskrunner` — RQ-backed background jobs
[src/autonomous/taskrunner/autotasks.py](src/autonomous/taskrunner/autotasks.py) exposes `AutoTasks` with three priority queues (`high`/`default`/`low`) on a shared Redis connection configured via `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD`/`REDIS_USERNAME`/`REDIS_DB`. `AutoTask` wraps `rq.job.Job` and adds a `meta(k, v)` helper used throughout the AI agents to attach progress to the current job.

### `autonomous.web` — framework-agnostic WSGI shim
[src/autonomous/web/response.py](src/autonomous/web/response.py) defines `Response` (WSGI-callable); [src/autonomous/web/session.py](src/autonomous/web/session.py) defines a `SessionStore` protocol plus two stores: `ContextSession` (in-memory dict, per-request) and `SignedCookieSession` (stdlib HMAC, no extra deps). Host code calls `bind_session(store)` per request; the auth layer reads/writes session state through this shim, which is why the same OAuth flows run unchanged under Flask, FastAPI, Starlette, or pure WSGI.

### `autonomous.auth` — Authlib OAuth2
[src/autonomous/auth/autoauth.py](src/autonomous/auth/autoauth.py) is the base OAuth2 client; [github.py](src/autonomous/auth/github.py), [google.py](src/autonomous/auth/google.py), [microsoft.py](src/autonomous/auth/microsoft.py), [discord.py](src/autonomous/auth/discord.py) and [facebook.py](src/autonomous/auth/facebook.py) are provider subclasses. `AutoAuth.auth_required(guest=, admin=)` is the framework-agnostic view decorator (gates by `is_guest` / `is_admin` predicates, not strict roles); `current_user()` reads the bound session's `"user"` key (via `autonomous.web.get_session()`) and falls back to `User.get_guest()`. [src/autonomous/auth/user.py](src/autonomous/auth/user.py) defines `AutoUser(AutoModel)` (base, with `role` field) and `User(AutoUser)` (project-extendable subclass) — note `is_guest` is true when *unauthenticated* OR `role == "guest"`, so it's a predicate, not a strict role check.

### Other subsystems
- [src/autonomous/storage/](src/autonomous/storage/) — `ImageStorage` (Pillow, writes WebP + thumbnail/small/medium/large variants under `static/images/`) and `LocalStorage`.
- [src/autonomous/logger.py](src/autonomous/logger.py) — `log` is a callable singleton that writes to `logs/current_run_error_log.log` + a dated archive; pass `_print=True` to also echo to stdout. Level controlled by `LOG_LEVEL` env var.
- [src/autonomous/utils/](src/autonomous/utils/) — small shared helpers (currently just `markdown.py`); home for cross-subpackage utilities that don't belong in a specific subsystem.

## Three-Agent Pipeline

The autonomous library runs as a closed-loop pipeline with three agents — paired with a downstream consumer (storyteller currently) that files inbound issues. The flow is **consumer issue OR CI release-smoke fail → dev → test → main → [user: `/prod-agent`] → PyPI release → CI release-smoke verify**, with two independent test perspectives, asymmetric review gates, and explicit halt triggers. Full design: `/opt/projects/autonomous/agent-topology.md` (workspace root, outside this repo).

**Release ownership (changed 2026-05-14; merge ownership added 2026-06-04; back-merge ownership added 2026-06-10):** autonomous-prod runs `./scripts/release.sh` under the user's manual `/prod-agent` trigger, but **only** when the merged `test → main` PR carries the `auto-release` label. autonomous-test sets the label as the release-intent signal; autonomous-prod gates the actual ship on it. As of 2026-06-04, **autonomous-prod also owns the `test → main` merge itself** — the user no longer hand-merges; `/prod-agent` always pulls and merges any open `test → main` PR before deciding on release. Docs-only / internal-only PRs land on main without a corresponding PyPI bump. autonomous-prod also owns **post-release smoke verification** (`scripts/smoke_test.sh`) on the same `/prod-agent` invocation that produced the release, and files / updates `[smoke-fail]` issues on signature mismatch. CI `release-smoke.yml` runs in parallel on the release commit as an audit layer in a clean runner environment (GitHub Actions reads `.github/workflows/*.yml` — same workflow file, separate runner from the operator's local smoke); the two layers are complementary, and disagreement between them is itself signal worth investigating. As of 2026-06-10, CLAUDE.md formally adopts **`main → dev` as the standard back-flow** — the canonical prod-agent template has been opening these PRs in §8 all along, but CLAUDE.md previously documented the back-flow as `test → dev`. Autonomous-prod opens (or comment-updates) the `main → dev` PR at the end of every `/prod-agent` whenever `dev` is behind `main` — drift-based, not move-based, so it also catches prior-cycle back-merge debt on no-op cycles. The PR carries everything the bundled `test → main` merge brought to main plus, when `auto-release` fired, the `release.sh` version bump — one PR instead of two. This supersedes the old `test → dev` back-merge that the test agent used to open. **No polling** — prod is manual-trigger only.

### Agents at a glance

| Agent | Branch | Tree | Triggered by | Writes | Review skill |
|---|---|---|---|---|---|
| **autonomous-prod** | `main` | `/opt/projects/autonomous/prod/` | manual `/prod-agent` from user (no polling) | merges any open `test → main` PR; `./scripts/release.sh` (version bump + PyPI upload + push) when PR has `auto-release`; opens `main → dev` back-merge PR after main moves (standard back-flow as of 2026-06-10); `[smoke-fail] <v>: <signature>` issues against `Sallenmoore/autonomous` on GitHub when smoke fails | n/a |
| **autonomous-dev** | `dev` | `/opt/projects/autonomous/dev/` | open `Sallenmoore/autonomous` issues on GitHub | library code + ephemeral tests in `tests/_dev_local/` (gitignored) | `/review` before opening `dev → test` |
| **autonomous-test** | `test` | `/opt/projects/autonomous/test/` | open `dev → test` PRs | committed tests + bug-fix commits | `/review-pr` (multi-agent) before opening `test → main` |

dev and test run as `/loop` in dynamic / self-paced mode. **prod does NOT loop** — it runs one iteration per `/prod-agent` user command and then stops. The dev agent does not push to `test`. The test agent does not edit the dev tree. Coordination is through PRs, issues, and labels (`smoke-fail`, `auto-filed`, `auto-release`, `awaiting-upstream`, `human-only`, `feature-request`). `auto-release` is set by the test agent and read by the prod agent as the ship-or-skip gate.

### Invariants

The procedures below describe how the contract is satisfied today. The contract itself doesn't change when CI tiers, review tooling, or release cadence evolve — re-read this table before editing the procedure to make sure the change preserves what doesn't move.

| Invariant | Source | Enforcement |
|---|---|---|
| Test agent writes tests INDEPENDENTLY of dev | Two-perspective design (`## Two-perspective testing`) | `tests/_dev_local/` is gitignored, so dev's tests are invisible in the PR diff the test agent works from |
| All bundled work goes through the full local + CI gate | No fast-paths | No docs-only skip; `/review-pr` runs at the test gate even on small bundles |
| Bug-fix commits land on `test`, never on dev's PR branch | One-way info flow (dev → test → main) | Test agent has no write capability against the dev tree or dev-owned PR head branches |
| Manual commits on `main` get reconciled before the next cycle | Halt trigger #4 + step 1 drift inspection | Pre-cycle `git log origin/test..origin/main --oneline` is part of the refresh step, not just a reactive halt |
| `main → dev` back-merge opens whenever dev is behind main at the end of `/prod-agent` | Keeps dev current with the canonical source of truth (post-merge, post-release main) in one PR per cycle instead of two; drift-based trigger also catches prior-cycle debt | Opened by autonomous-prod in its §8 step (`gh pr list --base dev --head main` reuse-or-create); dev-agent's step 1 picks it up on the next iteration |

### Interactive mode

When a human invokes Claude Code interactively in any of the three trees (most often `/opt/projects/autonomous/prod/` since that's the canonical clone), the loop discipline above is suspended in favor of explicit human direction. The agent may edit files, push branches, and open PRs from the prod tree under direct human prompts without violating the read-only constraint — that constraint applies to *autonomous* (loop-driven) operation, not human-prompted work. Project conventions (PRs target `main`, run `/review` before opening, ultrareview before merging, etc.) still apply.

In short: tree assignment dictates default loop behavior, not absolute capability. Outside an interactive session, the agent in each tree obeys its role; inside one, it follows the human.

### autonomous-prod (release + smoke operator)

Manual-triggered (no `/loop`, no polling). Owns the `test → main` merge (as of 2026-06-04), the release step (`./scripts/release.sh`, as of 2026-05-14), and post-release smoke verification (`./scripts/smoke_test.sh`). Does not edit library source — its writes are limited to: the `test → main` merge commit, the version-bump commit + push that `release.sh` produces, the PyPI upload, and `[smoke-fail]` issues filed/updated against `Sallenmoore/autonomous` on GitHub when smoke fails.

**Per-invocation step protocol lives in [.claude/commands/prod-agent.md](.claude/commands/prod-agent.md)** — invoked as `/prod-agent`; it is a thin dispatcher that sets the project values and executes the shared template `/opt/stacks/agent-runner/templates/prod-agent.md`. This section captures the doctrine; the slash command captures the procedure.

Local smoke (`scripts/smoke_test.sh`, run by prod at step 4 of the protocol) and CI `release-smoke.yml` (runs automatically on release commits to main, via GitHub Actions reading `.github/workflows/release-smoke.yml`) form a two-layer post-publish check: local smoke gives the operator immediate feedback under `/prod-agent`; CI provides the audit layer that runs in a clean runner environment and catches things the local environment may mask. **Only local prod files `[smoke-fail]` issues** — CI just runs `smoke_test.sh` and surfaces failure as a red check on the release commit. A red CI release-smoke after a green local smoke is the halt-trigger #5 case (human triage).

### autonomous-dev loop

The operating spec is the **project-local slash command** at [.claude/commands/dev-agent.md](.claude/commands/dev-agent.md) — invoked as `/dev-agent` from the dev tree (or via the "run dev" trigger phrase). The slash command is the source of truth for the procedure; this section describes the **contract** (what the iteration does, what's in scope, what halts), not the step-by-step.

**Mode: batch.** One `/dev-agent` invocation consumes the entire eligible open-issue queue into a single `dev → test` PR. This supersedes the older one-issue-per-iteration form (revised 2026-05-11; CI-watch added 2026-05-12; back-merge-first promoted to step 1 on 2026-05-16). The user wanted fewer, larger PRs over many small ones — fewer test-agent cycles, fewer back-merges, more contiguous review surface.

Per iteration the command:

1. **Back-merges first.** Always — even on second/third invocation, even when the user named a chore. The standard back-merge source is `main` (opened by autonomous-prod after the previous cycle's `/prod-agent`, as of 2026-06-10); a `test → dev` PR may also exist as a fallback path and is merged after `main → dev` when both are open. Cutting a new batch branch off stale `dev` (when post-release main content or test-agent committed coverage is pending back-merge) prevents lockstep updates to that content. Conflict → halt.
2. **Reviews the back-merge diff(s)** if any landed. A `main → dev` diff typically carries the bundled `test → main` content plus, when applicable, a `Bump autonomous version to X.Y.Z` commit from `release.sh`; a `test → dev` diff (rarer now) carries test-agent commits made directly on `test`. Anything outside those shapes — especially in a `main → dev` PR — gets extra scrutiny before new work layers on top.
3. **Triages all open issues.** In scope: every label including `bug`, `feature-request`, `smoke-fail`, `auto-filed`, `enhancement`. Skip only `awaiting-upstream` and `human-only`. Order within the batch: release-health first (`smoke-fail` + `auto-filed`), then other bugs, then features. Drop anything already closed by the back-merge.
4. **Halts on unclear hypotheses.** Per-issue, not per-batch — the rest of the batch can wait or proceed minus the unclear one (user's call).
5. **Branches once, fixes all.** `iter/<YYYY-MM-DD>-batch`. Semantic commits OK; they all ride in one PR. Ephemeral tests in `tests/_dev_local/` (gitignored — **not committed**; the test agent will write its own independent committed tests).
6. **Runs the local gate.** `pytest tests/unit && pytest tests/integration -m integration`, then `/review` over the batch diff. Red after 3 fix attempts on any single failure → halt.
7. **Opens ONE PR `dev → test`** via `gh pr create` with `Closes #<N>` for every issue in the body — GitHub's `Closes` / `Fixes` / `Resolves` auto-close keywords fire when the PR merges, and the close propagates through the `test → main` merge.
8. **Watches own CI** until green or 3 fix-up cycles still red. Fix-ups are **new commits** — never `--amend`, never force-push (CI is keyed to SHAs; rewriting commits the runner already saw can destroy the test agent's review state).

Standing exclusions still apply: dev does not push to `test`, does not edit `tests/unit/` or `tests/integration/` (test agent's exclusive surface per "Two-perspective testing"), does not run `release.sh`, does not `--no-verify`, does not force-push.

### autonomous-test loop

The operating spec is the **project-local slash command** at `/opt/projects/autonomous/test/.claude/commands/test-agent.md` — invoked as `/test-agent` from the test tree; it is a thin dispatcher into the shared template `/opt/stacks/agent-runner/templates/test-agent.md`. The slash command is the source of truth for the procedure; this section describes the **contract** (what the iteration does, what's in scope, what halts), not the step-by-step.

**Mode: sweep-all.** One `/test-agent` invocation bundles **every** open `dev → test` PR into a single cycle (oldest-first by `createdAt`) and produces one `test → main` PR for the whole bundle. This supersedes the older pick-one-PR-per-iteration form (revised 2026-05-15 user direction). Each subsequent PR in the sort was built on a baseline contained in the previous merge, so sequential layering is safe absent diff overlap. The test agent no longer opens a `test → dev` back-merge PR (deprecated 2026-06-10); the back-flow is now `main → dev` opened by autonomous-prod after the `test → main` merge.

Per iteration the command:

1. **Refreshes with proactive main-drift check.** `git log origin/test..origin/main` — every commit listed is on `main` but not on `test`. Subjects shaped like `Bump autonomous version to X.Y.Z` (the `release.sh` push) get back-merged; anything else is a manual user edit → back-merge if recognized, halt otherwise. Catches halt-trigger #4 cheaply at step 1 rather than mid-cycle.
2. **Sweeps all open `dev → test` PRs.** Skip nothing label-based; the test agent validates whatever dev shipped. None → exit (nothing to do this cycle).
3. **Test-merges each PR locally** in `createdAt` order. Conflict during any per-PR merge → halt (sweep-all assumes independent diffs; overlap is the user's call on precedence — halt-trigger #6).
4. **Writes independent committed tests per PR.** One file per PR named `tests/unit/test_unit_<topic>_iter_<date>.py` (preserves git blame, makes single-PR reverts targetable). Tests target each diff from a **fresh perspective**, without consulting dev's `tests/_dev_local/` (which is gitignored and invisible from the PR diff anyway — the second perspective is structurally enforced). Followed by a mandatory **bundle-level revert-sanity-check**: temporarily revert every touched source file to `origin/test`, run all new test files, confirm PR-specific tests fail per file. Forward-looking regression-guard tests that legitimately pass on revert are flagged in the bundle summary.
5. **Runs the full local gate.** `pytest tests/unit && pytest tests/integration -m integration && pylint $(git ls-files '*.py') && flake8 ... && python -m build && python -m twine check dist/*` (build + check, no upload). Red after 3 fix attempts → halt. Bug-fix commits land on `test` (or on a dev-owned PR head branch if the issue is dev's).
6. **Runs `/review-pr` (multi-agent)** over the combined bundle diff — heavier than dev's `/review`. Apply correctness/style findings as additional bug-fix commits.
7. **Decides release intent at bundle level.** If any PR in the bundle warrants a PyPI release, the `test → main` PR gets the `auto-release` label. Docs-only / internal-only bundles skip the label. With sweep-all, the bundle inherits the most-permissive intent — one ship-worthy fix in a 5-PR bundle means the whole bundle ships. (autonomous-prod gates the actual ship on this label.)
8. **Promotes to main.** `git push origin test` auto-closes every bundled `dev → test` PR (their head branches become contained in `test`). Opens the `test → main` PR with `Closes` refs for every underlying issue. Watches CI on the `test → main` PR (Python matrix + release-smoke); 3 fix-up amend cycles still red → halt. Notifies user when green. (The back-merge into `dev` is no longer the test agent's responsibility — autonomous-prod opens the `main → dev` PR after merging `test → main` on the next `/prod-agent` invocation, as of 2026-06-10.)
9. **Exits after notify.** autonomous-prod merges `test → main` on the next `/prod-agent` invocation (merge authority moved from user → prod on 2026-06-04). Prod then opens the `main → dev` back-merge PR; the dev agent's step 1 picks it up on its next iteration, so the test agent does not re-poll between cycles. If the merged PR carried `auto-release`, autonomous-prod also runs `./scripts/release.sh` in the same `/prod-agent` iteration (release authority moved from test → prod on 2026-05-14) — the version-bump rides into `dev` with the same `main → dev` back-merge.

Standing exclusions still apply: test does not edit the dev tree, does not push directly to `dev` or `main`, does not run `./scripts/release.sh`, does not force-push, does not merge `test → main` (that's prod's job on `/prod-agent`). Fix-up commits land on `test` (the bundle merge baseline), not on dev's PR head branches.

### Halt triggers (all autonomous agents)

When any fire, the agent stops, posts a summary, and waits for user input. On resume, the agent picks up where it stopped — does not skip the failing item.

1. **Tests red after 3 fix attempts.** Local gate (test) or GitHub Actions CI on a PR.
2. **Issue scope unclear** (dev only).
3. **Merge conflict on back-merge.** `main → dev` (or, for the deprecated fallback path, `test → dev`) can't auto-resolve.
4. **Unexpected commit on main.** A commit lands on `main` that wasn't part of any `test → main` PR or a `release.sh` version-bump push. All agents pause, sync from `origin/main`, ask user.
5. **CI release-smoke fails immediately after `/prod-agent`.** Prod published a release and the `release-smoke.yml` CI workflow reports failure against it. Stop polling on dev/test; this is "released and immediately broken" and needs human triage — autonomous-prod owns the release decision but does not auto-recover from a botched publish.
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

- **`scripts/release.sh` requires an active venv with pip on PATH.** On Fedora-like hosts, system `python3` doesn't bundle pip, and `make package` calls `python3 -m pip install --upgrade build twine ...`. The script's preflight doesn't catch this — failures land mid-`make package` after the version bump is already written, and the script's revert path catches it (so no permanent damage). Run inside an activated venv with pip available, e.g. `source .venv/bin/activate && ./scripts/release.sh` (the in-tree `.venv` ships Python 3.13 + pip/build/twine). Credentials come from `~/.pypirc` (a `[pypi]` section), not `.env`; the preflight aborts before any state change if neither `~/.pypirc` nor `TWINE_USERNAME` is present.

## Conventions worth knowing

- **Never import from db submodules directly** — go through `autonomous.db`, which re-exports the intended public names.
- **MongoDB is required on the first ORM operation** (connection is lazy; importing `autonomous.model` or `autonomous.ai` does not connect); unit tests that save/query these need the Compose stack up.
- **Models must be imported before `AutoModel.load_model("Name")` will resolve them**, because resolution walks `__subclasses__()`.
- **Use [`autonomous.ai.retry.retry`](src/autonomous/ai/retry.py) for bounded HTTP retry** rather than ad-hoc `try/except` loops; callers that bypassed it were a recurring source of hang and retry bugs.
- **GitHub issues are the only backlog** (the README Task List was retired in #282). Before accepting a new issue, check whether it duplicates an open one; close as duplicate or merge scope when it does.
- **CI fires on `dev`, `test`, and `main` branches.** Feature PRs target `test` (not `dev` directly and not `main`); see "Three-Agent Pipeline" above for the dev → test → main → `/prod-agent` flow and the `auto-release` label gate.

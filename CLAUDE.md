# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`autonomous-app` is a routing framework agnostic containerized service framework published to PyPI. It should layer seamlessly on top of flask, fast-api, and other micro-frameworks. Library source lives under [src/autonomous/](src/autonomous/); the package version is declared in [src/autonomous/__init__.py](src/autonomous/__init__.py) and consumed dynamically by [pyproject.toml](pyproject.toml). Runtime requires Python ≥3.12 per `pyproject.toml`, though CI matrix tests 3.11/3.12/3.13 across the dev / test / main branches ([.github/workflows/python-package.yml](.github/workflows/python-package.yml)). Importing the top-level `autonomous` package calls `load_dotenv()` and exposes the global `log` singleton.

## Agent Workflow

The autonomous library runs as a closed-loop autonomous pipeline with three agents — paired with a downstream consumer (storyteller currently) that files inbound issues. The loop is **release smoke fail OR consumer issue → dev → test → main → PyPI release → smoke verify**, with two independent test perspectives, asymmetric review gates, and explicit halt triggers. Full design + history: `~/.claude/plans/autonomous-process-codification.md` and `~/.claude/plans/agent-topology.md`.

### Agents at a glance

| Agent | Branch | Tree | Polls for | Writes | Review skill |
|---|---|---|---|---|---|
| **autonomous-prod** | `main` | `/opt/data/autonomous/` (read-only) | new PyPI releases (poll PyPI for version delta) | issues against `Sallenmoore/autonomous` titled `[smoke-fail] <version>: <signature>` | n/a |
| **autonomous-dev** | `dev` | `/opt/data/autonomous-dev/` | open `Sallenmoore/autonomous` issues | library code + ephemeral tests in `tests/_dev_local/` (gitignored) | `/review` before opening `dev → test` |
| **autonomous-test** | `test` | `/opt/data/autonomous-test/` | open `dev → test` PRs | committed tests + bug-fix commits | `/review-pr` (multi-agent) before opening `test → main` |

All three run as `/loop` in dynamic / self-paced mode. The dev agent does not push to `test`. The test agent does not edit the dev tree. Coordination is through PRs, issues, and labels (`smoke-fail`, `auto-filed`, `auto-release`, `awaiting-upstream`, `human-only`, `feature-request`).

### autonomous-prod (post-release smoke watcher)

Mutates **nothing** — never edits files, never pushes, never modifies the published artifact. Per iteration:

1. **Detect new release.** Poll `https://pypi.org/pypi/autonomous-app/json` (or `git log origin/main` for `Bump autonomous version to ...` commits). Compare to `last_seen_version` in `~/.claude/projects/-opt-data-autonomous/memory/last_smoke_version.md`.
2. **No new release** → sleep self-paced (15–60 min idle, faster right after a known release).
3. **New release detected** → run `scripts/smoke_test.sh <version>`. The script creates a fresh venv, `pip install autonomous-app==<v>` with retries (PyPI propagation can lag a few minutes), then imports the public symbols (`autonomous.ai.{TextAgent, JSONAgent, ImageAgent, AudioAgent}`, `autonomous.db.db_sync`, `autonomous.auth.AutoAuth`, top-level `log`).
4. **Smoke fails** → parse `SIGNATURE: <stage>:<error_class>:<location>` from stderr's last line. Fingerprint by signature. Issue lifecycle: no matching open → `gh issue create -R Sallenmoore/autonomous` titled `[smoke-fail] <version>: <signature>`, body with full stderr, labels `smoke-fail` + `auto-filed` + `release:<v>`. Matching open → comment with version + new stderr. Matching closed → reopen as regression.
5. **Smoke passes** → update `last_seen_version`, optionally comment `✅ smoke passed` on the `test → main` PR that produced the release.

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

1. **Refresh.** `git fetch origin && git checkout test && git pull --ff-only`.
2. **Poll for open `dev → test` PRs.** None → fall through to step 9.
3. **Pull and test-merge locally.** `gh pr checkout <PR>; git checkout test; git merge --no-ff <PR-branch>`.
4. **Write independent tests for the change.** `gh pr diff <PR>` → write tests targeting the changed code from a fresh perspective (without seeing dev's `tests/_dev_local/`, which are gitignored). Place under `tests/unit/` or `tests/integration/`. **These ARE committed** — they ride into main + PyPI.
5. **Full local gate.**
   ```bash
   pytest tests/unit/
   pytest tests/integration/
   pylint $(git ls-files '*.py')
   flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
   make package    # build + twine check (no upload — release.sh handles upload)
   ```
   On red: bug-fix-only commits to `test` (or to PR branch if dev-owned). Red after 3 attempts → halt.
6. **`/review-pr` (multi-agent) skill, then fix.** Heavier review at this gate.
7. **Decide release intent.** If the change warrants a PyPI release (bug fix users need, new feature, etc.), apply the `auto-release` label to the `test → main` PR before opening. Skip the label for docs-only / internal-only changes.
8. **Promote to main.** `git push origin test; gh pr merge <PR> --merge; gh pr create --base main --title "test → main: <cycle summary>"`. Watch GitHub CI (Python package matrix + Pylint + release smoke). Amend until green; red after 3 amends → halt. Notify user when ready to merge.
9. **After user merges `test → main`:**
   - **If the merged PR carried `auto-release`** → `git checkout main && git pull --ff-only && ./scripts/release.sh`. Comment the resulting version on the merged PR. autonomous-prod picks up the new version on its next iteration.
   - **Drift check** (always) → if `git log origin/main..origin/dev` is non-empty, `gh pr create --base dev --head test --title "test → dev: post-main back-merge"`.

### Halt triggers (all autonomous agents)

When any fire, the agent stops, posts a summary, and waits for user input. On resume, the agent picks up where it stopped — does not skip the failing item.

1. **Tests red after 3 fix attempts.** Local gate (test) or GitHub CI on a PR.
2. **Issue scope unclear** (dev only).
3. **Merge conflict on back-merge.** `test → dev` can't auto-resolve.
4. **Unexpected commit on main.** A commit lands on `main` that wasn't part of any `test → main` PR or a `release.sh` version-bump push. All agents pause, sync from `origin/main`, ask user.
5. **Smoke fails immediately after auto-release.** The test agent's auto-release succeeded but autonomous-prod immediately filed a smoke-fail issue. Stop polling on dev/test; this is the equivalent of "released and immediately broken" and needs human attention.

### Two-perspective testing

| Agent | Test location | Committed? | Visible to other agent? |
|---|---|---|---|
| dev | `tests/_dev_local/` | no (`.gitignore` blocks) | no — never appears in PR diff |
| test | `tests/unit/`, `tests/integration/` | yes | yes — ships to main + PyPI |

If both agents wrote tests in the same place, the test agent would just re-run dev's tests and rubber-stamp them. Gitignoring dev's tests forces the test agent to write tests independently from the PR diff alone — a genuine second perspective.

## How this library is consumed

`autonomous-app` is published to PyPI and consumed by downstream apps (e.g. [Sallenmoore/StoryTeller](https://github.com/Sallenmoore/StoryTeller)) **purely as a PyPI dependency** — no submodule, no bind mount in any environment, since the storyteller↔autonomous decoupling on 2026-05-05. All three consumer environments (prod / consumer-test / consumer-dev) install via the `autonomous-app>=X.Y.Z` pin in their `requirements.txt`. There is no live-editing-in-the-consumer path anymore; library iteration happens in this repo and reaches consumers via a release.

Practical implication for breaking changes: ship a release via `./scripts/release.sh` (see Commands below), then the consumer's storyteller-dev agent runs `bump-autonomous.sh ${NEW_VERSION}` to update the pin. After the consumer's PR through dev → test → main lands, the prod consumer rebuild picks up the new wheel.

## Coordination with the storyteller agent

StoryTeller has its own dev / test agent pair operating on `/opt/data/storyteller-dev/` and `/opt/data/storyteller-test/`. Those agents do not edit this tree. The relationship is producer (this tree) ↔ consumer (storyteller's trees), mediated by:
- **GitHub issues** for change requests (storyteller → autonomous).
- **PyPI releases** for change deliveries (autonomous → storyteller).
- The `requirements.txt` pin in each storyteller tree (`autonomous-app>=X.Y.Z`) is the version contract.

Storyteller no longer vendors this repo as a submodule (decoupled 2026-05-05); it installs `autonomous-app` from PyPI exclusively.

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

- `make tests` — full suite: reinstalls deps, `pip install -e .`, brings up the Docker Compose stack in `tests/`, then runs `pytest`. **The test container is expected to mount the repo at `/var/app/autonomous`** (see [tests/conftest.py](tests/conftest.py)); pytest is not meant to be run directly on the host.
- `make test` — runs a single filter: `pytest -k $(TESTING)`. Override the filter inline, e.g. `make test TESTING=test_unit_automodel`. Default is `test_unit_ai`.
- `make inittests` / `make cleantests` — bring the Compose stack up/down without running pytest.
- `make package` — `python -m build` + `twine upload` to PyPI. Bump `__version__` in [src/autonomous/__init__.py](src/autonomous/__init__.py) first.
- `./scripts/release.sh` — preferred release entrypoint: bumps the patch version in `src/autonomous/__init__.py`, runs `make package` (build + twine upload), then commits and pushes `origin/main`. Use this for routine patch releases. For non-patch bumps, edit `__version__` manually first, then run the script (or fall back to `make package`).
- CI lints with `flake8 . --select=E9,F63,F7,F82` (syntax-only gate) plus a non-blocking `--max-complexity=10 --max-line-length=127` pass.

Pytest config lives in `[tool.pytest.ini_options]` in [pyproject.toml](pyproject.toml): it auto-adds `-x --pdb -s -v --cov=autonomous` and loads `tests/.testenv`. Tests stop on first failure and drop into pdb — be aware when running non-interactively.

## Architecture

The library is a set of loosely-coupled service wrappers glued together by the `AutoModel` ORM layer. Each subpackage assumes a companion container (MongoDB, Redis, Ollama, a media/embeddings service) reachable over the intranet.

### `autonomous.db` — vendored MongoEngine-style ORM
[src/autonomous/db/](src/autonomous/db/) is a full in-tree fork of a MongoEngine-like ODM: `Document`, `QuerySet`, `signals`, `fields`, `context_managers`, `dereference`, `db_sync`. The public surface is re-exported from [src/autonomous/db/__init__.py](src/autonomous/db/__init__.py) — import from `autonomous.db`, not the submodules. [src/autonomous/db/db_sync.py](src/autonomous/db/db_sync.py) enqueues debounced vector-embedding sync jobs via Redis/RQ and calls out to `MEDIA_API_BASE_URL` (default `http://media_ai:5005`) for embeddings.

### `autonomous.model` — AutoModel ORM surface
[src/autonomous/model/automodel.py](src/autonomous/model/automodel.py) defines `AutoModel(Document)`, the abstract base every app model should extend. **Importing this module calls `connect(...)` at import time** using `DB_HOST`/`DB_PORT`/`DB_USERNAME`/`DB_PASSWORD`/`DB_DB` — any code path that touches `AutoModel` (including test collection) requires a reachable MongoDB. It also wires four `auto_pre/post_init/save` signal hooks that subclasses can override.

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

The autonomous library runs as a closed-loop autonomous pipeline with three agents — paired with a downstream consumer (storyteller currently) that files inbound issues. The loop is **release smoke fail OR consumer issue → dev → test → main → PyPI release → smoke verify**, with two independent test perspectives, asymmetric review gates, and explicit halt triggers. Full design + history: `~/.claude/plans/autonomous-process-codification.md` and `~/.claude/plans/agent-topology.md`.

### Agents at a glance

| Agent | Branch | Tree | Polls for | Writes | Review skill |
|---|---|---|---|---|---|
| **autonomous-prod** | `main` | `/opt/data/autonomous/` (read-only) | new PyPI releases (poll PyPI for version delta) | issues against `Sallenmoore/autonomous` titled `[smoke-fail] <version>: <signature>` | n/a |
| **autonomous-dev** | `dev` | `/opt/data/autonomous-dev/` | open `Sallenmoore/autonomous` issues | library code + ephemeral tests in `tests/_dev_local/` (gitignored) | `/review` before opening `dev → test` |
| **autonomous-test** | `test` | `/opt/data/autonomous-test/` | open `dev → test` PRs | committed tests + bug-fix commits | `/review-pr` (multi-agent) before opening `test → main` |

All three run as `/loop` in dynamic / self-paced mode. The dev agent does not push to `test`. The test agent does not edit the dev tree. Coordination is through PRs, issues, and labels (`smoke-fail`, `auto-filed`, `auto-release`, `awaiting-upstream`, `human-only`, `feature-request`).

### Interactive mode

When a human invokes Claude Code interactively in any of the three trees (most often `/opt/data/autonomous/` since that's the canonical clone), the loop discipline above is suspended in favor of explicit human direction. The agent may edit files, push branches, and open PRs from the prod tree under direct human prompts without violating the read-only constraint — that constraint applies to *autonomous* (loop-driven) operation, not human-prompted work. Project conventions (PRs target `main`, run `/review` before opening, ultrareview before merging, etc.) still apply.

In short: tree assignment dictates default loop behavior, not absolute capability. Outside an interactive session, the agent in each tree obeys its role; inside one, it follows the human.

### autonomous-prod (post-release smoke watcher)

Mutates **nothing** — never edits files, never pushes, never modifies the published artifact. Per iteration:

1. **Detect new release.** Poll `https://pypi.org/pypi/autonomous-app/json` (or `git log origin/main` for `Bump autonomous version to ...` commits). Compare to `last_seen_version` in `~/.claude/projects/-opt-data-autonomous/memory/last_smoke_version.md`.
2. **No new release** → sleep self-paced (15–60 min idle, faster right after a known release).
3. **New release detected** → run `scripts/smoke_test.sh <version>`. The script creates a fresh venv, `pip install autonomous-app==<v>` with retries (PyPI propagation can lag a few minutes), then imports the public symbols (`autonomous.ai.{TextAgent, JSONAgent, ImageAgent, AudioAgent}`, `autonomous.db.db_sync`, `autonomous.auth.AutoAuth`, top-level `log`).
4. **Smoke fails** → parse `SIGNATURE: <stage>:<error_class>:<location>` from stderr's last line. Fingerprint by signature. Issue lifecycle: no matching open → `gh issue create -R Sallenmoore/autonomous` titled `[smoke-fail] <version>: <signature>`, body with full stderr, labels `smoke-fail` + `auto-filed` + `release:<v>`. Matching open → comment with version + new stderr. Matching closed → reopen as regression.
5. **Smoke passes** → update `last_seen_version`, optionally comment `✅ smoke passed` on the `test → main` PR that produced the release.

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

1. **Refresh.** `git fetch origin && git checkout test && git pull --ff-only`.
2. **Poll for open `dev → test` PRs.** None → fall through to step 9.
3. **Pull and test-merge locally.** `gh pr checkout <PR>; git checkout test; git merge --no-ff <PR-branch>`.
4. **Write independent tests for the change.** `gh pr diff <PR>` → write tests targeting the changed code from a fresh perspective (without seeing dev's `tests/_dev_local/`, which are gitignored). Place under `tests/unit/` or `tests/integration/`. **These ARE committed** — they ride into main + PyPI.
5. **Full local gate.**
   ```bash
   pytest tests/unit/
   pytest tests/integration/
   pylint $(git ls-files '*.py')
   flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
   make package    # build + twine check (no upload — release.sh handles upload)
   ```
   On red: bug-fix-only commits to `test` (or to PR branch if dev-owned). Red after 3 attempts → halt.
6. **`/review-pr` (multi-agent) skill, then fix.** Heavier review at this gate.
7. **Decide release intent.** If the change warrants a PyPI release (bug fix users need, new feature, etc.), apply the `auto-release` label to the `test → main` PR before opening. Skip the label for docs-only / internal-only changes.
8. **Promote to main.** `git push origin test; gh pr merge <PR> --merge; gh pr create --base main --title "test → main: <cycle summary>"`. Watch GitHub CI (Python package matrix + Pylint + release smoke). Amend until green; red after 3 amends → halt. Notify user when ready to merge.
9. **After user merges `test → main`:**
   - **If the merged PR carried `auto-release`** → `git checkout main && git pull --ff-only && ./scripts/release.sh`. Comment the resulting version on the merged PR. autonomous-prod picks up the new version on its next iteration.
   - **Drift check** (always) → if `git log origin/main..origin/dev` is non-empty, `gh pr create --base dev --head test --title "test → dev: post-main back-merge"`.

### Halt triggers (all autonomous agents)

When any fire, the agent stops, posts a summary, and waits for user input. On resume, the agent picks up where it stopped — does not skip the failing item.

1. **Tests red after 3 fix attempts.** Local gate (test) or GitHub CI on a PR.
2. **Issue scope unclear** (dev only).
3. **Merge conflict on back-merge.** `test → dev` can't auto-resolve.
4. **Unexpected commit on main.** A commit lands on `main` that wasn't part of any `test → main` PR or a `release.sh` version-bump push. All agents pause, sync from `origin/main`, ask user.
5. **Smoke fails immediately after auto-release.** The test agent's auto-release succeeded but autonomous-prod immediately filed a smoke-fail issue. Stop polling on dev/test; this is the equivalent of "released and immediately broken" and needs human attention.

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

After the test→main merge, the autonomous-test agent runs `release.sh` automatically when the PR carries the `auto-release` label (see Agent Workflow above). Manual invocation is still supported for ad-hoc patches.

## Conventions worth knowing

- **Never import from db submodules directly** — go through `autonomous.db`, which re-exports the intended public names.
- **MongoDB is required at import time** for anything under `autonomous.model` or `autonomous.ai`; unit tests that touch these need the Compose stack up.
- **Models must be imported before `AutoModel.load_model("Name")` will resolve them**, because resolution walks `__subclasses__()`.
- **Use [`autonomous.ai.retry.retry`](src/autonomous/ai/retry.py) for bounded HTTP retry** rather than ad-hoc `try/except` loops; backlog items in README #5, #6, #16, #21 all exist because callers bypass it.
- **Existing backlog lives in [README.md](README.md) "Task List"** — 28 items with file:line anchors and impact axes (security/stability/functionality/efficiency/usability). Before accepting a new issue, check whether it duplicates a backlog item; close as duplicate or merge scope when it does.
- **CI fires on `dev`, `test`, and `main` branches.** Feature PRs target `test` (not `dev` directly and not `main`); see "Agent Workflow" above for the dev → test → main flow and the `auto-release` label semantics.

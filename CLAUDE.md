# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`autonomous-app` is a routing framework agnostic containerized service framework published to PyPI. It should layer seamlessly on top of flask, fast-api, and other micro-frameworks. Library source lives under [src/autonomous/](src/autonomous/); the package version is declared in [src/autonomous/__init__.py](src/autonomous/__init__.py) and consumed dynamically by [pyproject.toml](pyproject.toml). Runtime requires Python ≥3.12 per `pyproject.toml`, though CI matrix tests 3.11/3.12/3.13 on the `dev` branch ([.github/workflows/python-package.yml](.github/workflows/python-package.yml)). Importing the top-level `autonomous` package calls `load_dotenv()` and exposes the global `log` singleton.

## Agent Workflow

This repo is owned by the **autonomous agent**, working from the canonical clone at `/opt/data/autonomous/`. The autonomous agent's responsibilities:

1. **Triage incoming issues from consumer projects.** Consumers (currently just StoryTeller; the library is framework-agnostic so others may follow) file GitHub issues against `Sallenmoore/autonomous` when they hit a library bug or want a new feature. Each issue should arrive with: a clear repro, the consumer-side workaround (if any), and a pointer to the suspected fix location. The autonomous agent reads, plans, implements, tests, and ships a release.
2. **Maintain library quality.** No consumer is editing `autonomous` source directly anymore — the agent is the sole maintainer of the library's correctness. Tests, lint, and the release pipeline all live in this tree.
3. **Coordinate releases with consumers.** After a release, notify any consumer that filed the issue (close it with a comment like "Released as v0.3.X — bump your `autonomous-app` pin"). For multi-consumer releases, post once per consumer.

### Working tree

- **Canonical clone:** `/opt/data/autonomous/` (this directory). Created 2026-05-05 as part of the storyteller decoupling.
- **Storyteller no longer vendors this repo as a submodule.** Before 2026-05-05, the dev/test trees of `Sallenmoore/StoryTeller` carried this codebase as a submodule and bind-mounted it for live editing. That coupling is gone — storyteller now installs `autonomous-app` from PyPI exclusively, like any other dependency.

### Filing issues from consumers

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

The autonomous agent should treat agent-filed issues the same as human-filed ones: read fully, decide whether to accept, plan, implement, ship.

## Coordination with the storyteller agent

StoryTeller has its own dev / test agent pair operating on `/opt/data/storyteller-dev/` and `/opt/data/storyteller-test/`. Those agents do not edit this tree. The relationship is producer (this tree) ↔ consumer (storyteller's trees), mediated by:
- **GitHub issues** for change requests (storyteller → autonomous).
- **PyPI releases** for change deliveries (autonomous → storyteller).
- The `requirements.txt` pin in each storyteller tree (`autonomous-app>=X.Y.Z`) is the version contract.

## Commands

All dev workflows go through the [makefile](makefile), which `include .env` — expect a `.env` at repo root with DB/Redis/AI credentials.

- `make tests` — full suite: reinstalls deps, `pip install -e .`, brings up the Docker Compose stack in `tests/`, then runs `pytest`. **The test container is expected to mount the repo at `/var/app/autonomous`** (see [tests/conftest.py](tests/conftest.py)); pytest is not meant to be run directly on the host.
- `make test` — runs a single filter: `pytest -k $(TESTING)`. Override the filter inline, e.g. `make test TESTING=test_unit_automodel`. Default is `test_unit_ai`.
- `make inittests` / `make cleantests` — bring the Compose stack up/down without running pytest.
- `make package` — `python -m build` + `twine upload` to PyPI. Bump `__version__` in [src/autonomous/__init__.py](src/autonomous/__init__.py) first.
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
[src/autonomous/ai/baseagent.py](src/autonomous/ai/baseagent.py) defines `BaseAgent(AutoModel)` with a `MODEL_REGISTRY` mapping provider strings (`"local"`, `"gemini"`) to client classes in [src/autonomous/ai/models/](src/autonomous/ai/models/). Agents (`JSONAgent`, `TextAgent`, `ImageAgent`, `AudioAgent`) lazily instantiate the right client via `get_client()` and re-instantiate if the `provider` attr changes. `LocalAIModel` talks to Ollama (`OLLAMA_API_BASE_URL`) and a media service (`MEDIA_API_BASE_URL`); `GeminiAIModel` uses `google-genai`. Individual agents can override provider via env var (e.g. `JSON_AI_AGENT`).

### `autonomous.taskrunner` — RQ-backed background jobs
[src/autonomous/taskrunner/autotasks.py](src/autonomous/taskrunner/autotasks.py) exposes `AutoTasks` with three priority queues (`high`/`default`/`low`) on a shared Redis connection configured via `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD`/`REDIS_USERNAME`/`REDIS_DB`. `AutoTask` wraps `rq.job.Job` and adds a `meta(k, v)` helper used throughout the AI agents to attach progress to the current job.

### `autonomous.auth` — Authlib OAuth2
[src/autonomous/auth/autoauth.py](src/autonomous/auth/autoauth.py) is the base OAuth2 client; [github.py](src/autonomous/auth/github.py) and [google.py](src/autonomous/auth/google.py) are provider subclasses. `AutoAuth.auth_required(guest=, admin=)` is the Flask view decorator; `current_user()` reads `flask.session["user"]` and falls back to `User.get_guest()`. `User` is an `AutoModel` so auth state persists to MongoDB.

### Other subsystems
- [src/autonomous/storage/](src/autonomous/storage/) — `ImageStorage` (Pillow, writes WebP + thumbnail/small/medium/large variants under `static/images/`) and `LocalStorage`.
- [src/autonomous/apis/version_control/](src/autonomous/apis/version_control/) — PyGithub wrappers (`GHRepo`, `GHOrganization`, `GHCallbacks`).
- [src/autonomous/logger.py](src/autonomous/logger.py) — `log` is a callable singleton that writes to `logs/current_run_error_log.log` + a dated archive; pass `_print=True` to also echo to stdout. Level controlled by `LOG_LEVEL` env var.

## CI/CD

### Pipeline shape (updated 2026-05-05)

```
chore/<slug> | fix/<slug> | feat/<slug>
        │
        ▼  PR (pylint on push)
      main                 (protected; default branch — release trunk)
        │
        ▼  ./scripts/release.sh
      PyPI publish + version bump commit
```

The `dev` branch in this repo is a historical integration tier from when contributions were heavier; recent practice (PR #7 makefile fix, PR #12 release.sh) targets `main` directly and `dev` has fallen behind. The autonomous agent can either revive `dev` as a CI gate or formally retire it — either is fine; just be consistent. Until that decision lands, **PR against `main`**.

**What the diagram does NOT show (because it isn't currently wired up):**
- **pytest does not gate `main` PRs.** [.github/workflows/python-package.yml](.github/workflows/python-package.yml) only triggers on push/PR to `dev`, so the only check that fires on a `main`-targeted PR is [pylint.yml](.github/workflows/pylint.yml) (which is `on: [push]`). Run `make tests` locally before opening a PR — CI will not catch test regressions.
- **`scripts/release.sh` does not create a git tag.** It bumps `__version__`, runs `make package` (which twine-uploads), commits, and pushes `origin/main`. The PyPI version is the source of truth for releases; there is no `vX.Y.Z` tag in the git history. If you need a tag (e.g. for changelog tooling), create it manually after release or extend the script.

### Releasing

Use [scripts/release.sh](scripts/release.sh):
- Verifies on `main`, fast-forwarded, working tree clean, PyPI creds present
- Computes next patch version from `__version__`
- Writes the bump
- Runs `make package` (build + twine check + twine upload)
- Commits + pushes `origin/main`

Consumer-side bump (e.g. storyteller's `autonomous-app` pin in `requirements.txt`) is the consumer's responsibility — autonomous notifies via the GitHub issue thread that produced the work.

## Conventions worth knowing

- **Never import from db submodules directly** — go through `autonomous.db`, which re-exports the intended public names.
- **MongoDB is required at import time** for anything under `autonomous.model` or `autonomous.ai`; unit tests that touch these need the Compose stack up.
- **Models must be imported before `AutoModel.load_model("Name")` will resolve them**, because resolution walks `__subclasses__()`.
- **PRs target `main`** (see Pipeline shape above for the historical context on `dev`).

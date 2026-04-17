# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`autonomous-app` is a routing framework agnotstic containerized service framework published to PyPI. It should layer seamlessly on top of flask, fast-api, and other micro-frameworks. Library source lives under [src/autonomous/](src/autonomous/); the package version is declared in [src/autonomous/__init__.py](src/autonomous/__init__.py) and consumed dynamically by [pyproject.toml](pyproject.toml). Runtime requires Python ≥3.12 per `pyproject.toml`, though CI matrix tests 3.11/3.12/3.13 on the `dev` branch ([.github/workflows/python-package.yml](.github/workflows/python-package.yml)). Importing the top-level `autonomous` package calls `load_dotenv()` and exposes the global `log` singleton.

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

### Pipeline shape

```
ai/<feature-slug>          (per-task branch, cut from ai-development)
        │
        ▼  PR (lint + unit tests required)
      dev                  (integration tier; PRs to main cut from here)
        │
        ▼  PR (lint + unit + integration tests required, 1 approval)
      main                 (protected; default branch)
        │
        ▼  git tag vX.Y.Z
```

### checklist for repo

- [ ] Create `dev` and `ai-development` branches; push
- [ ] Add `.github/pull_request_template.md` + `.github/CODEOWNERS` via PR to main
- [ ] Create rulesets for `main` (1 approval) and `dev` (0 approvals); block deletion + force-push
- [ ] Add pytest markers + lazy-connect any import-time side effects
- [ ] Commit `lint.yml`, `test-unit.yml`, `test-integration.yml` via PR
- [ ] Add required status checks to both rulesets
- [ ] Commit `release.yml` via PR
- [ ] Document AI branch convention in `CLAUDE.md`
- [ ] Smoketest PR end-to-end

## Conventions worth knowing

- **Never import from db submodules directly** — go through `autonomous.db`, which re-exports the intended public names.
- **MongoDB is required at import time** for anything under `autonomous.model` or `autonomous.ai`; unit tests that touch these need the Compose stack up.
- **Models must be imported before `AutoModel.load_model("Name")` will resolve them**, because resolution walks `__subclasses__()`.
- **CI targets the `dev` branch, not `main`** — PRs for this repo typically go to `dev`.

# Deployment Pipeline Setup

Reusable recipe for bootstrapping the `ai-development -> dev -> main` pipeline
on a new Python library repo. Run from a fresh clone of the target repo with
`gh` CLI authenticated.

## Pipeline shape

```
ai/<feature-slug>          (per-task branch, cut from ai-development)
        │
        ▼  PR (lint + unit tests required)
      dev                  (integration tier; PRs to main cut from here)
        │
        ▼  PR (lint + unit + integration tests required, 1 approval)
      main                 (protected; default branch)
        │
        ▼  git tag vX.Y.Z  -> release workflow publishes to PyPI
```

## Prerequisites

- GitHub repo with `main` as default branch
- `gh` CLI authenticated with `repo` scope (`gh auth login`, `gh auth setup-git`)
- PyPI account + project registered; API token ready for secret injection
- Repo owner / admin permission (branch rulesets require admin)

## Stage 0 — branches, templates, protection

### 1. Create branches

```sh
# dev off main (skip if it already exists)
git fetch origin
git checkout -B dev origin/main && git push -u origin dev

# ai-development off dev (the integration base for AI work)
git checkout -B ai-development origin/dev && git push -u origin ai-development
```

### 2. Commit PR template + CODEOWNERS to main

Both files must live on the **default branch** — GitHub reads them from there
regardless of PR base.

```
.github/pull_request_template.md
.github/CODEOWNERS
```

Template should include checkboxes for unit tests, integration tests, and a
version-bump reminder on release PRs. CODEOWNERS assigns at least one
default reviewer with `* @owner`.

Bootstrap commits to a protected `main` need a throwaway feature branch:

```sh
git checkout -b chore/pipeline-bootstrap main
git add .github/pull_request_template.md .github/CODEOWNERS
git commit -m "Add PR template and CODEOWNERS"
git push -u origin chore/pipeline-bootstrap
gh pr create --base main --title "..." --body "..."
# merge via gh pr merge or the UI
```

### 3. Branch rulesets (main)

`Settings -> Rules -> Rulesets -> New branch ruleset`:

- Target: `main`
- Enforcement: Active
- Rules:
  - **Restrict deletions**: on
  - **Block force pushes**: on
  - **Require a pull request before merging**: on
    - Required approvals: `1`
    - Require review from Code Owners: on (optional, uses CODEOWNERS)
  - **Require status checks to pass**: add later in Stage 2 once workflows exist
    - Checks to add: `lint`, `test-unit` (3.11/3.12/3.13 matrix), `test-integration`

### 4. Branch rulesets (dev)

Same as main but:

- Target: `dev`
- Required approvals: `0` (AI-authored PRs land after checks pass)
- Required checks: `lint`, `test-unit` (matrix)

### 5. Secrets

`Settings -> Secrets and variables -> Actions -> New repository secret`:

- `PYPI_API_TOKEN` — scoped to the target PyPI project (generate at
  https://pypi.org/manage/account/token/)

Equivalent via CLI:

```sh
gh secret set PYPI_API_TOKEN --body "pypi-AgEI..."
```

## Stage 1 — test tiers

Library must split tests into two tiers so PR feedback stays fast:

- `pytest -m unit` — no external services; mocks or pure logic only
- `pytest -m integration` — hits Mongo / Redis / AI providers (via local
  docker-compose or GitHub `services:`)

Register markers in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "unit: runs without external services",
    "integration: requires docker-compose stack",
]
```

Any module that opens a network/DB connection at import time (e.g. an ORM base
class calling `connect(...)` at top-level) must be refactored to **lazy-connect**
— otherwise unit tests can't be collected without the services running.

Makefile targets:

```make
test-unit:
	python -m pytest -m unit

test-integration:
	cd tests && docker compose up -d --build
	python -m pytest -m integration
```

## Stage 2 — CI workflows

Three workflows in `.github/workflows/`:

### `lint.yml`

```yaml
on:
  pull_request:
    branches: [dev, main]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install flake8
      - run: flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
      - run: flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
```

### `test-unit.yml`

```yaml
on:
  pull_request:
    branches: [dev, main]
jobs:
  test-unit:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ matrix.python-version }}" }
      - run: pip install -r requirements.txt -r requirements_dev.txt && pip install -e .
      - run: pytest -m unit
```

### `test-integration.yml`

```yaml
on:
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 6 * * *"   # nightly
jobs:
  test-integration:
    runs-on: ubuntu-latest
    services:
      mongo:
        image: mongo:7
        env:
          MONGO_INITDB_ROOT_USERNAME: test
          MONGO_INITDB_ROOT_PASSWORD: test
        ports: ["27017:27017"]
      redis:
        image: redis:7
        ports: ["6379:6379"]
    env:
      DB_HOST: localhost
      DB_USERNAME: test
      DB_PASSWORD: test
      DB_DB: test
      REDIS_HOST: localhost
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt -r requirements_dev.txt && pip install -e .
      - run: pytest -m integration
```

After these land, go back to the rulesets and add `lint`, `test-unit`
(one entry per matrix variant), and `test-integration` as required status
checks.

## Stage 3 — release workflow

### `release.yml`

```yaml
on:
  push:
    tags: ["v*"]
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Verify tag matches package version
        run: |
          TAG="${GITHUB_REF_NAME#v}"
          PKG=$(python -c "import <package>; print(<package>.__version__)")
          test "$TAG" = "$PKG" || { echo "Tag $TAG != package $PKG"; exit 1; }
      - run: pip install build twine
      - run: python -m build
      - run: python -m twine check dist/*
      - run: python -m twine upload dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
```

Replace `<package>` with the actual top-level package name.

### Release procedure

```sh
# on dev: bump version in <package>/__init__.py, commit, PR to main
# after main merges:
git checkout main && git pull
git tag v0.3.114
git push origin v0.3.114
# release.yml runs, publishes to PyPI
```

## Stage 4 — AI contribution conventions

Document in `CLAUDE.md` / `AGENTS.md`:

- AI branches are named `ai/<slug>` and cut from `ai-development`.
- PRs target `dev`. Squash-merge preferred to keep dev history readable.
- `ai-development` is periodically fast-forwarded to `dev` so future AI
  branches start from the latest integrated state:
  ```sh
  git checkout ai-development && git merge --ff-only origin/dev && git push
  ```

## Stage 5 — verification

- [ ] Open a throwaway PR `ai/smoketest` -> `dev`; confirm lint + test-unit run and block merge when red.
- [ ] Merge to dev; open PR `dev -> main`; confirm test-integration also runs.
- [ ] Merge to main; push tag `v0.0.1a1`; confirm release workflow publishes (or fails on version mismatch as expected).
- [ ] Delete the smoketest artifacts from TestPyPI / yank the release.

## Copy-paste checklist for a new repo

- [ ] `gh auth setup-git`
- [ ] Create `dev` and `ai-development` branches; push
- [ ] Add `.github/pull_request_template.md` + `.github/CODEOWNERS` via PR to main
- [ ] Create rulesets for `main` (1 approval) and `dev` (0 approvals); block deletion + force-push
- [ ] `gh secret set PYPI_API_TOKEN`
- [ ] Add pytest markers + lazy-connect any import-time side effects
- [ ] Commit `lint.yml`, `test-unit.yml`, `test-integration.yml` via PR
- [ ] Add required status checks to both rulesets
- [ ] Commit `release.yml` via PR
- [ ] Document AI branch convention in `CLAUDE.md`
- [ ] Smoketest PR end-to-end

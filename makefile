
.PHONY: all clean cleantests test test-int test-perf test-all tests inittests package docs cleandocs

-include .env
export

all: test clean package

# Define the interpreter (usually python3)
PYTHON = python3

package: clean
	rm -rf .pytest_cache .coverage dist build *.egg-info static
	$(PYTHON) -m pip install --upgrade build twine setuptools wheel
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*
	$(PYTHON) -m twine upload dist/* --skip-existing --verbose

###### CLEANING #######

clean:
	rm -rf .pytest_cache .coverage dist build *.egg-info static

###### TESTING #######

# Bring up the service stack for integration tests (Mongo, Redis, etc.)
inittests: cleantests
	pip install --no-cache-dir --upgrade pip wheel
	pip install --upgrade -r ./requirements.txt
	pip install --upgrade -r ./requirements_dev.txt
	pip install -e ".[all]"
	cd tests && sudo docker compose up -d --build

cleantests: clean
	- cd tests && sudo docker compose down --remove-orphans

# Hermetic unit tests only. No Mongo, Redis, or AI backends required.
# Safe to run on any laptop; what CI should gate on by default.
test:
	python -m pytest tests/unit

# Integration tests that need the full stack. `inittests` brings it up.
test-int: inittests
	python -m pytest tests/integration -m integration

# Performance benchmarks. Opt-in; doesn't gate `test-all`. Requires
# pytest-benchmark (in requirements_dev.txt). Run locally for baselines;
# CI doesn't gate on this because benchmark variance on shared runners
# would flake.
test-perf:
	python -m pytest tests/perf --benchmark-only

# Full suite — unit first (fails fast), then integration.
test-all: test test-int

# Backwards-compatible alias for the old behaviour.
tests: test-all

###### DOCS #######

# Build HTML docs into docs/_build/html via Sphinx. -W treats warnings as
# errors so broken cross-refs / stale autosummary entries fail the build.
docs:
	$(PYTHON) -m sphinx -W -b html docs docs/_build/html
	@echo "Open docs/_build/html/index.html in a browser."

# Live-reload server: rebuilds + browser-refreshes on every source edit.
# Useful when iterating on the guides; not used by CI or RTD.
docs-serve:
	$(PYTHON) -m sphinx_autobuild -b html docs docs/_build/html \
		--watch src/autonomous \
		--ignore "docs/_build/*"

cleandocs:
	rm -rf docs/_build

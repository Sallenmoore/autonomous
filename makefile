
.PHONY: all clean cleantests test test-int test-all tests inittests package docs cleandocs

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

# Full suite — unit first (fails fast), then integration.
test-all: test test-int

# Backwards-compatible alias for the old behaviour.
tests: test-all

###### DOCS #######

# Build the navigable HTML reference into docs/_build/ using the
# zero-dependency generator at scripts/gen_docs.py.
docs:
	$(PYTHON) scripts/gen_docs.py --clean
	@echo "Open docs/_build/index.html in a browser."

cleandocs:
	rm -rf docs/_build

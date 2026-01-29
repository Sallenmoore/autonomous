
.PHONY: all clean deepclean test tests testinit package

include .env
export

all: test clean package

# Define the interpreter (usually python3)
PYTHON = python3

package: clean
	$(PYTHON) -m pip install --upgrade build twine setuptools wheel
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*
	$(PYTHON) -m twine upload dist/* --skip-existing --verbose

###### CLEANING #######

clean:
	rm -rf .pytest_cache .coverage dist build *.egg-info static

###### TESTING #######

inittests: cleantests
	pip install --no-cache-dir --upgrade pip wheel
	pip install --upgrade -r ./requirements.txt
	pip install --upgrade -r ./requirements_dev.txt
	pip install -e .
	cd tests && sudo docker compose up -d --build

cleantests: clean
	cd tests && sudo docker compose down --remove-orphans

TESTING=test_unit_ai

test:
	python -m pytest -k $(TESTING)

tests:
	python -m pytest

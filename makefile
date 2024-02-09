
.PHONY: all clean deepclean test tests testinit package

include .env
export

all: test clean package

package: clean
	python -m build
	python -m pip install --upgrade twine
	twine check dist/*
	twine upload dist/* --skip-existing --verbose

###### CLEANING #######

clean:
	rm -rf .pytest_cache .coverage dist build *.egg-info static

###### TESTING #######

inittests: clean
	pip install --no-cache-dir --upgrade pip wheel
	pip install --upgrade -r ./requirements.txt
	pip install --upgrade -r ./requirements_dev.txt
	pip install -e .
	cd /root/dev/testdb && docker compose up -d

TESTING=TestAutomodel

test: inittests
	python -m pytest -k "$(TESTING)"

tests: inittests
	python -m pytest

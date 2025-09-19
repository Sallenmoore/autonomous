
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

inittests: cleantests
	pip install --no-cache-dir --upgrade pip wheel
	pip install --upgrade -r ./requirements.txt
	pip install --upgrade -r ./requirements_dev.txt
	pip install -e .
	cd tests && sudo docker compose up -d --build && sudo docker compose logs -f

cleantests: clean
	cd tests && sudo docker compose down --remove-orphans

TESTING=test_unit_ai

test:
	python -m pytest -k $(TESTING)

tests:
	python -m pytest

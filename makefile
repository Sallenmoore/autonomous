
.PHONY: all clean deepclean test tests testinit package

include .env
export

all: test clean package

CONTAINERS=$$(sudo docker ps -a -q)

package: clean
	python -m build
	python -m pip install --upgrade twine
	twine check dist/*
	twine upload dist/* --skip-existing --verbose

###### CLEANING #######

clean:
	rm -rf .pytest_cache .coverage dist
	sudo docker ps -a
	cd ../ && sudo docker compose down --remove-orphans

###### TESTING #######

inittests: clean
	pip install --no-cache-dir --upgrade pip wheel
	pip install --upgrade -r ./requirements.txt
	pip install --upgrade -r ./requirements_dev.txt
	pip install -e .
	python -m pytest

TESTING=TestImageStorage
test:
	python -m pytest -k "$(TESTING)" -s 

tests:
	python -m pytest

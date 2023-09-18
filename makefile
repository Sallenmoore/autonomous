
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
	rm -rf dist
	rm -rf .pytest_cache .coverage dist

deepclean: clean
	sudo docker ps -a
	-sudo docker kill $(CONTAINERS)
	sudo docker ps -a
	-sudo docker container prune -f
	-sudo docker image prune -f
	-sudo docker system prune -a -f --volumes

###### TESTING #######

TESTING=wikijs

testinit:
	pip install -e .
	pip install --no-cache-dir --upgrade pip wheel
	pip install -r ./requirements.txt

test: testinit
	python -m pytest -k "test_$(TESTING)" -s

testauto: testinit
	python -m pytest

testapp:
	cd src/autonomous/app_template && make test

tests: testauto testapp

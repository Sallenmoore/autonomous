
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
	-sudo docker kill $(CONTAINERS)

deepclean: clean
	-sudo docker container prune -f
	-sudo docker image prune -f
	-sudo docker system prune -a -f --volumes

###### TESTING #######

testinit: clean
	pip install --no-cache-dir --upgrade pip wheel
	pip install --upgrade -r ./requirements.txt
	pip install --upgrade -r ./requirements_dev.txt
	pip install -e .

TESTING=TestAutoTasks
test:
	python -m pytest -k "$(TESTING)" -s

testauto:
	python -m pytest

testapp:
	cd src/autonomous/app_template && make test

tests: testauto testapp
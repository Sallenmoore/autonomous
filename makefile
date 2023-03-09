
.PHONY: all build run clean deepclean debug tests test

export FIREBASE_URL := https://autonomous-ae539-default-rtdb.firebaseio.com/
export FIREBASE_KEY_FILE := app_template/vendor/firebase.json
export APP_NAME := "autonomous"
export TESTING := "True"
export LOG_LEVEL := "INFO"

all: test clean run start

APP_NAME?=auto
CONTAINERS=$(sudo docker ps -a -q)

build:
	docker-compose build --no-cache

run: 
	docker-compose up --build -d

package:
	rm -rf dist
	python setup.py bdist_wheel sdist
	twine check dist/*
	twine upload -r testpypi dist/*

###### CLEANING #######

clean:
	sudo docker ps -a
	-docker-compose down --remove-orphans
	-sudo docker kill $(CONTAINERS)

deepclean: clean
	-sudo docker container prune -f
	-sudo docker image prune -f
	-sudo docker system prune -a -f --volumes

###### TESTING #######

debug: 
	docker-compose up --build -d
	docker logs -f --since=5m -t $(APP_NAME)

# cd app_templatedocker-compose up --build -d
tests: testauto testapp

testauto: clean
	python -m pytest -v --log-level=INFO -rx -l -x --ignore=app_template/tests

# docker-compose up --build -d
testapp: clean
	cd app_template; make tests

# docker-compose up --build -d
test:
	echo "Running tests"
	python -m pytest -v --log-level=INFO -rx -l -x -k $(RUNTEST)
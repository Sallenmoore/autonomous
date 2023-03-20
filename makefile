
.PHONY: all build run clean deepclean debug tests test

# export FIREBASE_URL := https://autonomous-ae539-default-rtdb.firebaseio.com/
# export FIREBASE_KEY_FILE := app_template/vendor/firebase.json
export APP_NAME := "app"
export TESTING := "True"
export LOG_LEVEL := "INFO"
export REDIS_OM_URL := redis://localhost:10002

all: test clean run start

CONTAINERS=$$(sudo docker ps -a -q)

package:
	rm -rf dist
	python setup.py bdist_wheel sdist
	twine check dist/*
	twine upload -r testpypi dist/*

###### CLEANING #######

clean:
	sudo docker ps -a
	-sudo docker kill $(CONTAINERS)
	sudo docker ps -a

deepclean: clean
	-sudo docker container prune -f
	-sudo docker image prune -f
	-sudo docker system prune -a -f --volumes

###### TESTING #######

startdb:
	-docker network create app_net
	cd ~/projects/database; sudo docker-compose up -d
	
tests: startdb testauto testapp

# docker-compose up --build -d
RUNTEST?='test_'
test: startdb
	python -m pytest -v --log-level=INFO -rx -l -x -k $(RUNTEST)

testauto: startdb
	python -m pytest -v --log-level=INFO -rx -l -x --ignore=app_template/tests

# docker-compose up --build -d
testapp: startdb
	cd app_template; make tests


.PHONY: all package startdb create-network clean deepclean tests test testauto testapp

export APP_NAME := "app"
export TESTING := "True"
export LOG_LEVEL := "INFO"
export REDIS_URL := redis://localhost:10002
export OPENAI_KEY := ""

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
	
tests: testtox testapp

# docker-compose up --build -d
RUNTEST?='test_'
test: clean
	python -m pytest $(RUNTEST)

testauto: clean 
	python -m pytest

# docker-compose up --build -d
testapp: clean
	cd src/autonomous/app_template; make tests

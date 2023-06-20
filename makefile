
.PHONY: all package startdb create-network clean tests test testauto testapp

include .env
export

all: test clean run start

CONTAINERS=$$(sudo docker ps -a -q)

package:
	rm -rf dist
	python -m build
	python -m pip install --upgrade twine
	twine check dist/*
	twine upload dist/*


###### CLEANING #######

clean:
	sudo docker ps -a
	-sudo docker kill $(CONTAINERS)
	sudo docker ps -a
	-sudo docker container prune -f
	-sudo docker image prune -f
	-sudo docker system prune -a -f --volumes

###### TESTING #######
	
tests: testauto testapp

# docker-compose up --build -d
RUNTEST?='test_'
test:
	python -m pytest $(RUNTEST)

testauto: 
	pip install --no-cache-dir --upgrade pip wheel
	pip install -r ./requirements.txt
	python -m pytest -s -v

# docker-compose up --build -d
testapp: clean
	cd src/autonomous/app_template; make tests

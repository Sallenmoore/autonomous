
all: test clean package

package:
	pip install --upgrade pip
	rm -rf dist
	python3 -m build
	pip install -e .
	python -m twine upload --verbose --repository testpypi dist/*

###### TESTING #######

#OPTIONS
TEST_FUNC?="test_"
TB?="short"

#TEST SCRIPTS

quicktest: 
	-pytest ./tests --log-level=INFO -vv -rx -l -x --tb=$(TB) -k $(TEST_FUNC)

test_app:
	- cd tests/test_app && docker-compose up --build -d

test:clean test_app quicktest


###### CLEANING #######

CONTAINERS=$(shell docker ps -a -q)

clean:
	sudo docker ps -a
	-cd tests/test_app && docker-compose down --remove-orphans
	-sudo docker kill 

deepclean: clean
	-rm -rf tables
	-echo "$(CONTAINERS)" && sudo docker rm $(CONTAINERS)
	-sudo docker system prune -a -f --volumes
	
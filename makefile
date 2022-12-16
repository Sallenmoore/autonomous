
.PHONY: all clean deepclean test inspect trace

all: test clean package

package:
	pip install --upgrade pip
	-rm -rf dist
	python3 -m build
	-pip install -e .
	python -m twine upload --verbose --repository testpypi dist/*

###### TESTING #######

#OPTIONS
TEST_FUNC?="test_"
TB?="short"

#TEST SCRIPTS


testapp:
	-cd tests/apitester && docker-compose up --build -d
	
test: testapp
	@echo "Setting up environment variables"
	-export PYTHONDONTWRITEBYTECODE=1; export PYTHONUNBUFFERED=1; export APP_NAME="api"; \
	export AUTO_TABLE_PATH="tests"; export DEBUG=True; export PORT=7537; export HOST=0.0.0.0;\
	pytest ./tests --log-level=INFO -rx -l -x -k $(TEST_FUNC)
	cd tests/apitester && docker logs --since=5m api

trace:
	@export PYTHONDONTWRITEBYTECODE=1; export PYTHONUNBUFFERED=1; export APP_NAME="api"; \
	export AUTO_TABLE_PATH="tests"; export DEBUG=True; export PORT=7537; export HOST=0.0.0.0;\
	pytest ./tests --log-level=INFO --trace -rx -l -x --tb=$(TB) -k $(TEST_FUNC)
	

###### CLEANING #######

CONTAINERS=$(shell docker ps -a -q)

clean:
	sudo docker ps -a
	-cd tests/apitester && docker-compose down --remove-orphans
	-sudo docker kill 

deepclean: clean
	-echo "$(CONTAINERS)" && sudo docker rm $(CONTAINERS)
	-sudo docker system prune -a -f --volumes
	

.PHONY: all build run clean deepclean test tests debug

all: test clean run start

APP_NAME?=app
CONTAINERS=$(sudo docker ps -a -q)

startdb:
	docker-compose build --no-cache

build:
	docker-compose build --no-cache

run: 
	docker-compose up --build -d
	docker logs -f --since=5m -t $(APP_NAME)

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

tests: 
	docker-compose up --build -d
	docker exec -it $(APP_NAME) python -m pytest -v --log-level=INFO -rx -l -x 

RUNTEST?="test_"
test:
	docker-compose up --build -d
	docker exec -it $(APP_NAME) python -m pytest -v --log-level=INFO -rx -l -x -k $(RUNTEST)
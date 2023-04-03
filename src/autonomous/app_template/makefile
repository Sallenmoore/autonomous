
.PHONY: all build run clean deepclean test tests debug

all: test clean run start

APP_NAME?=app
CONTAINERS=$$(sudo docker ps -a -q)

###### Database #######

create-network:
	if [ -z $$(docker network ls --filter name=app_net | grep -w app_net) ]; then \
		docker network create app_net; \
	fi

###### BUILD and RUN #######
build:
	docker-compose build --no-cache

run: create-network 
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

debug: run
	docker logs -f --since=5m -t $(APP_NAME)

tests: 
	docker-compose up --build -d
	docker exec -it $(APP_NAME) python -m pytest -v --log-level=INFO -rx -l -x 

RUNTEST?="test_"
test:
	docker-compose up --build -d
	docker exec -it $(APP_NAME) python -m pytest -v --log-level=INFO -rx -l -x -k $(RUNTEST)
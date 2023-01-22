
all: test clean run

APP_NAME?="simpleapp"
CONTAINERS=$(sudo docker ps -a -q)



build: clean
	docker compose --no-cache build $(APP_NAME)

run: 
	docker-compose up --build -d
	docker logs -f --since=15m -t $(APP_NAME)

start: clean run
	xdg-open 'http://localhost'
###### CLEANING #######

clean:
	sudo docker ps -a
	-docker-compose down --remove-orphans
	-sudo docker kill $(CONTAINERS)
	-sudo docker container prune -f


deepclean: clean
	-rm -rf tables
	-echo "$(CONTAINERS)" && sudo docker rm $(CONTAINERS)
	-sudo docker image prune -f
	-sudo docker system prune -a -f --volumes

###### TESTING #######

#OPTIONS
TEST_FUNC?="test_"

test: clean run
	echo "Running tests"
	-docker exec -it $(APP_NAME) python -m pytest -v -s tests/$(TEST_FUNC)*.py
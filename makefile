
all: test clean run start

APP_NAME?=app
CONTAINERS=$(sudo docker ps -a -q)

build:
	docker-compose build --no-cache

run: 
	docker-compose up --build -d
	echo "docker logs -t $(APP_NAME) -f"

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

#OPTIONS
TEST_FUNC?="test_"

test: clean run
	echo "Running tests"
	-docker exec -it $(APP_NAME) python -m pytest -v -s tests/$(TEST_FUNC)*.py
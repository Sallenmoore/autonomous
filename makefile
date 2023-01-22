
all: test clean run start

APP_NAME?=pyramidapp
CONTAINERS=$(sudo docker ps -a -q)
PORT?=5000

build: clean
	docker-compose --no-cache build $(APP_NAME)

run: 
	docker-compose up --build -d
	docker logs -t $(APP_NAME)

start: clean run
	echo "starting app"
	xdg-open 'http://localhost'
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
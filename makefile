
all: test clean package

package:
	pip install --upgrade pip
	rm -rf dist
	python3 -m build
	pip install -e .
	python -m twine upload --verbose --repository testpypi dist/*

testapp:
	cd test_app && docker-compose up --build -d

test:
	cd tests/app_test/ && docker-compose up --build -d
	pytest ./tests --log-level=INFO -rx -l -x

clean:
	rm -rf tables; rm -rf .pytest_cache;
	sudo docker ps -a
	sudo docker rm $(sudo docker ps -a -q)
	
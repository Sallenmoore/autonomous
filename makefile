
all: test clean package

package:
	pip install --upgrade pip
	rm -rf dist
	python3 -m build
	pip install -e .
	python -m twine upload --verbose --repository testpypi dist/*

test:
	pytest ./tests --log-level=INFO -rx -l -x --tb=long

testapp:
	cd test_app && docker-compose up --build -d

clean:
	rm -rf tables
	rm -rf .pytest_cache
	sudo docker ps -a
	sudo docker kill $(sudo docker ps -q) && sudo docker rm $(sudo docker ps -a -q)
	
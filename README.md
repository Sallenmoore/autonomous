# Autonomous

***In Development - Not Suitable for Production***

# Autonomous

A framework that attempts to make it easy to create self-contained applications with minimal dependencies. Built to be as modular as possible and run entirely in containers.

## TODO

- Setup test app
- add more testing
- Improve database storage
- Improve database search
- Auto generate API documentation

## Issue Tracking

- None that I am aware of

## Basic Info

- **Latest Version**: 0.0.5
- **pypi**: https://test.pypi.org/project/autonomous/0.0.4/
- **github**: https://github.com/Sallenmoore/autonomous

### Container Apps

Autonomous has minimally 2 container components:

- **server**
  - nginx proxy server listening on port 80
  - static files and assets are served from here. This is also the main entry point for the application.
- **test**
  - access documentation on port:6000
  - Test app for the library

---

## Make PyPi Update

```
rm -rf dist && python3 -m build && pip install -e . && python3 -m twine upload --verbose --repository testpypi dist/*
```

## Run Tests

```
pytest ./tests --log-level=INFO -rx -l -x; rm -rf tables
```

## Show Logs

- `sudo docker logs -f --since=15m -t test`

## Dependencies

- **Languages**
  - [Python 3.9](/Dev/language/python)
- **Frameworks**
  - [Flask](https://flask.palletsprojects.com/en/2.1.x/)
- **Containers**
  - [Docker](https://docs.docker.com/)
  - [Docker Compose](https://github.com/compose-spec/compose-spec/blob/master/spec.md)
- **Server**
  - [nginx](https://docs.nginx.com/nginx/)
  - [gunicorn](https://docs.gunicorn.org/en/stable/configure.html)
- **Networking and Serialization**
  - [jsonpickle](https://jsonpickle.github.io/api.html#jsonpickle-high-level-api)
  - [requests](https://requests.readthedocs.io/en/latest/)
- **Database**
  - [TinyDB](https://tinydb.readthedocs.io/en/latest/usage.html)
- **Frontend Stack**
  - [Materialize](https://materializecss.com/select.html)
  - [JQuery](https://api.jquery.com/)
- **Testing**
  - [pytest](/Dev/tools/pytest)
  - [coverage](https://coverage.readthedocs.io/en/6.4.1/cmd.html)
- **Documentation**
  - [pdoc](https://pdoc.dev/docs/pdoc/doc.html)
  - [highlight.js](https://highlightjs.org/)

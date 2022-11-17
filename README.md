# Autonomous

A local, comtainerized, service based application framework that attempts to make it easy to create self-contained Python applications with minimal dependencies (coming soon!).

- **Latest Version**: 0.0.16
- **pypi**: https://test.pypi.org/project/autonomous/0.0.26/
- **github**: https://github.com/Sallenmoore/autonomous

## Features

- Fully containerized, service based archetecture
- All services are localized, interfacing walled-garden network
- Dynamic typed lists, like python.

### Container Apps

Autonomous has minimally 2 container components:

- **server**
  - nginx proxy server listening on port 80
  - static files and assets are served from here. This is also the main entry point for the application.
- **test**
  - access documentation on port:6000
  - Test app for the library

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

---

## Developer Notes

### TODO

- Setup test app
- Add more testing
- Improve database search
- Auto generate API documentation

### Issue Tracking

- None

### Make PyPi Update

1. Update version in `pyproject.toml`

2. ```sh
   rm -rf dist && python3 -m build && pip install -e . && python3 -m twine upload --verbose --repository testpypi dist/*
   ```

### Run Tests

```sh
pytest ./tests --log-level=INFO -rx -l -x; rm -rf tables
```

### Show Logs

```sh
sudo docker logs -f --since=15m -t app_name`
```
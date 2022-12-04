# Autonomous

A local, comtainerized, service based application framework that attempts to make it easy to create self-contained Python applications with minimal dependencies (coming soon!).

- **Latest Version**: 0.0.28
- **pypi**: https://test.pypi.org/project/autonomous
- **github**: https://github.com/Sallenmoore/autonomous

## Features

- Fully containerized, service based Python application framework
- All services are localized and interface using a virtual intranet
- Built-in Local NoSQL database and Model API
- Single Data-Source Models across all services
- Auto-Generated Documentation Pages (Coming Soon!!!)
- Dynamically typed database attributes
- Optional static attribute typing

### Container Apps

Autonomous has minimally 2 container components:

- **server**
  - nginx proxy server listening on port 80
  - static files and assets are served from here. This is also the main entry point for the application.
- **test**
  - access documentation on port:TBD
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

## {.tabset}

### TODO

- Get Working Again!!!
- Setup template app
- Fix app generator
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
sudo docker logs -f --since=15m -t app_name
```

### Documentation

```md

## Description

_description_of_function_

## Args

- pos_str (_type_, required): _description_
- key_str (_type_, optional): _description_

## Returns

_type_: _description_

## Exceptions

- None

## Module

- autonomous.package

```

# Autonomous

![Tests](https://github.com/Sallenmoore/autonomous/actions/workflows/tests.yml/badge.svg)

A local, containerized, service based application framework that attempts to make it easy to create self-contained Python applications with minimal dependencies (coming soon!).

- **Latest Version**: 0.0.54
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
  - [Python 3.10](/Dev/language/python)
- **Frameworks**
  - [Flask](https://flask.palletsprojects.com/en/2.1.x/)
- **Containers**
  - [Docker](https://docs.docker.com/)
  - [Docker Compose](https://github.com/compose-spec/compose-spec/blob/master/spec.md)
- **Server**
  - [nginx](https://docs.nginx.com/nginx/)
  - [gunicorn](https://docs.gunicorn.org/en/stable/configure.html)
- **Networking and Serialization**
  - [requests](https://requests.readthedocs.io/en/latest/)
- **Database**
  - [Firebase](#)
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

- Make Model and Basemodel ABC
- Use Metaclasses for auto_attributes
- Add type hints
- Setup/fix template app generator
- Auto generate API documentation
- Add more testing
- Build js Library
- Build CSS Library
- Switch to less verbose html preprocessor
- Improve database search

### Issue Tracking

- None

### Make PyPi Update

1. Update version

2. ```sh
   rm -rf dist
   python3 -m build
   pip install -e .
   python3 -m twine upload --verbose -r testpypi dist/*
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

- pos*str (\_type*, required): _description_
- key*str (\_type*, optional): _description_

## Returns

_type_: _description_

## Exceptions

- None

## Module

- autonomous.package
```

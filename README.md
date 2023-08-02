# Autonomous

:warning: :warning: :warning: WiP :warning: :warning: :warning:

![Tests](https://github.com/Sallenmoore/autonomous/actions/workflows/tests.yml/badge.svg)

A local, containerized, service based application library built on top of Flask.
The goal is to make it easy to create self-contained Python applications with minimal dependencies using built in libraries for many different kinds of tasks.

- **[pypi](https://test.pypi.org/project/autonomous)**
- **[github](https://github.com/Sallenmoore/autonomous)**

## Features

- Fully containerized, service based Python application framework
- All services are localized to a virtual intranet
- Built-in Local NoSQL database and Model API
- Cloud file storage with Cloudinary or S3
- Auto-Generated Documentation Pages (Coming Soon!!!)

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
  - [Local](https://tinydb.readthedocs.io/en/latest/)
- **Testing**
  - [pytest](/Dev/tools/pytest)
  - [coverage](https://coverage.readthedocs.io/en/6.4.1/cmd.html)
- **Documentation** - Coming Soon
  - [pdoc](https://pdoc.dev/docs/pdoc/doc.html)
  - [highlight.js](https://highlightjs.org/)

---

## Developer Notes

### TODO

- Auto generate API documentation
- Setup/fix template app generator
- Add type hints
- Switch to less verbose html preprocessor
- Add more database options
- 100% testing coverage

### Issue Tracking

- None

## Processes

### Generate app

TDB

### Tests

```sh
make tests
```

### package

1. Update version in `/src/autonomous/__init__.py`
2. `make package`

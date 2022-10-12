# Autonomous

***In Development - Not Suitable for Production***

A framework that attempts to make it easy to create self-contained applications with minimal dependencies. Built to be as modular as possible and run entirely in containers.

## Container Apps

Autonomous has minimally 2 container components:

- **server**
  - nginx proxy server listening on port 80
  - static files and assets are served from here. This is also the main entry point for the application.
- **test**
  - access documentation on port:6000
  - Test app for the library
  
---

## Stack Documentation

### Docker

- [Docker](https://docs.docker.com/)
- [Docker Compose](https://github.com/compose-spec/compose-spec/blob/master/spec.md)

### Server

- [nginx](https://docs.nginx.com/nginx/)
- [gunicorn](https://docs.gunicorn.org/en/stable/configure.html)

### Backend Stack

- [Python](https://docs.python.org/3.9/)
- [Flask](https://flask.palletsprojects.com/en/2.1.x/)

### Frontend Stack

- [Materialize](https://materializecss.com/select.html)
- [JQuery](https://api.jquery.com/)

### Database

- [TinyDB](https://tinydb.readthedocs.io/en/latest/usage.html)

### Testing

- [pytest](https://docs.pytest.org/en/7.1.x/reference/reference.html)
- [coverage](https://coverage.readthedocs.io/en/6.4.1/cmd.html)

### Documentation

- [pdoc](https://pdoc.dev/docs/pdoc/doc.html)
- [highlight.js](https://highlightjs.org/)

---

## Developer Notes

### Start/Status/Stop Commands

- build and start the container
  - `docker-compose up --build -d`
- container status
  - `docker-compose ps -a`
- run a command in the container
  - `docker-compose exec -option <service name> <command>`
- stop and remove running containers
  - `docker-compose down --remove-orphans`
- stop all running containers
  - `sudo docker kill $(sudo docker ps -q)`
- remove all stopped containers
  - `sudo docker rm $(sudo docker ps -a -q)`

### Run Tests

- To run tests:
  - `sudo docker-compose exec <service name> pytest --log-level=INFO -rx -l -x`
- To run only < name > tests on the `api` service:
  - `sudo docker-compose exec <service name>  pytest --log-level=INFO -rA -l -x -k "<test_target>"`
- To check test coverage:
  - `sudo docker-compose exec <service name>  coverage run -m pytest ...`

### Read Logs

- `sudo docker logs --since=15m -t <container>`
- `sudo docker logs -f --since=15m -t <container> &`
  - follows as a background process

### BUGS



### TODOs

1. Improve database storage
2. Improve database search
2. Auto generate API documentation

### IMPROVEMENTS

---

### Misc Notes

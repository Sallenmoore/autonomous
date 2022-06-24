# DM Buddy

DnD Helper Application



### Container Apps

Buddy has 4 inital container components:

* **server**
  * static files and assets are served from here. This is also the main entry point for the application.
* **api**
  * The backend API and database
  * currently implented with Flask and TinyDB
* **admin**
  * An admin web interface
* **view**
  * The front end interface
  
---

## Stack Documentation

### Docker

* [Docker](https://docs.docker.com/)
* [Docker Compose](https://github.com/compose-spec/compose-spec/blob/master/spec.md)

#### Quick Commands

* build and start the container
    * `docker-compose up --build -d`
* container status
    * `docker-compose ps -a`
* run a command in the container
    * `docker-compose exec -option <service name> <command>`
* stop and remove running containers
    * `docker-compose down --remove-orphans`
* stop all running containers
    * `docker kill $(docker ps -q)`
* remove all stopped containers
    * `docker rm $(docker ps -a -q)`
* read logs
    * `docker logs --since=15m -t <container>`
    * `docker logs -f --since=15m -t <container> &`
        * follows as a background process

### Server

* [nginx](https://docs.nginx.com/nginx/)
* [gunicorn](https://docs.gunicorn.org/en/stable/configure.html)

### Backend Stack

* [Python](https://docs.python.org/3.9/)
* [Flask](https://flask.palletsprojects.com/en/2.1.x/)

### Frontend Stack

* [Materialize](https://materializecss.com/select.html)
* [JQuery](https://api.jquery.com/)

### Database

* [TinyDB](https://tinydb.readthedocs.io/en/latest/usage.html)

### Testing

* [pytest](https://docs.pytest.org/en/7.1.x/reference/reference.html)
* [coverage](https://coverage.readthedocs.io/en/6.4.1/cmd.html)

---

## Developer Notes

### Run Tests

* To run tests:
    * `docker-compose exec <service name> pytest -rl -x`
* To run only Character tests on the `api` service:
    * `docker-compose exec api pytest -rl -x -k Character`
* To check test coverage:
    * `coverage run -m pytest ...`

### BUGS

* saving objects to DB
    * not saving all attributes

### TODOs

1. interfaces
    * admin
    * player
    * table

### IMPROVEMENTS

* Move DB to cloud
    * Firebase?

---

### Misc Notes
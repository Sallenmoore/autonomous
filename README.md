# DM Buddy

DnD Helper Application

## Stack Documentation

### Docker

* build and start the container
    * `docker-compose up --build -d`
* run a command in the container
    * `docker-compose exec -option <service name> <command>`
* stop and remove running containers
    * `docker-compose down --remove-orphans`

### Server

* [gunicorn](https://docs.gunicorn.org/en/stable/configure.html)

### Backend Stack

* Python
* [Flask](https://flask.palletsprojects.com/en/2.1.x/)

### Frontend Stack

* [Materialize](https://materializecss.com/select.html)
* JQuery

### Database

* [TinyDB](https://tinydb.readthedocs.io/en/latest/usage.html)

## Tests

* To run tests:
    * `docker-compose exec <service name> pytest -rl -x`
* To run only Character tests on the `api` service:
    * `docker-compose exec api pytest -rl -x -k Character`
* To check test coverage:
    * `coverage run -m pytest ...`

## Notes

---

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

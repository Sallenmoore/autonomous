# DM Buddy

DnD Helper Application

## Stack Documentation

### Docker

* build and start the container
    * docker-compose up --build -d
* run a command in the container
    * docker-compose exec -option <service name> <command>
* stop and remove running containers
    * docker-compose down --remove-orphans

### Backend Stack

* Python
* Flask

### Frontend Stack

* Materialize
* JQuery

### Database

* TinyDB

## Tests

*To run tests:
    *`docker-compose exec <service name> pytest -rl -x`
* To run only Character tests on the `api` service:
    * `docker-compose exec api pytest -rl -x -k Character`
* To check test coverage:
    * coverage run -m pytest arg1 arg2 arg3

## Notes

---

***TODO***

* Move DB to cloud: Firebase?
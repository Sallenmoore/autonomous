# Dungeon Arena

---

## Stack Documentation

### Docker

- [Docker](https://docs.docker.com/)
- [Docker Compose](https://github.com/compose-spec/compose-spec/blob/master/spec.md)

### Server

- [gunicorn](https://docs.gunicorn.org/en/stable/configure.html)

### Backend Stack

- [Python](https://docs.python.org/3.9/)
- [Flask](https://flask.palletsprojects.com/en/2.1.x/)

### Database

- [Firebase](https://firebase.google.com/docs/database/admin/save-data)
  - https://console.firebase.google.com/u/0/project/budbuddy-9c55a/database/budbuddy-9c55a-default-rtdb/data

### FrontEnd Stack

- OrbitCSS

## Developer Notes

### Start/Status/Stop Commands

- build container
  - `make build`
- build and run the container
  - `make run`
- start the container and open localhost
  - `make start`
- container status
  - `docker-compose ps -a`
- run a command in the container
  - `docker-compose exec -option auto <command>`
- stop all running containers
  - `make clean`
- remove all stopped containers
  - `make deepclean`

### Read Logs

```sh
docker logs --since=15m -t  auto
```

_follows as a background process_

```sh
docker logs -f --since=15m -t auto &`
```

### Run Tests

- `make tests`

---

### Misc Notes

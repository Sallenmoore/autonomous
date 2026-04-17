# Tasks — AutoTasks

``AutoTasks`` is a thin wrapper around [RQ](https://python-rq.org/) and
Redis that adds:

- Priority queues (``TaskPriority.HIGH`` / ``NORMAL`` / ``LOW``).
- Convenient current-job introspection.
- Timeout + result-TTL defaults that match typical web-app usage.
- Lazy connection — instantiating ``AutoTasks()`` never opens a
  socket until you actually enqueue or query something.

## Install

```bash
pip install 'autonomous-app[tasks]'
```

Extra pulls in ``redis`` and ``rq``.

## Minimal enqueue

```python
from autonomous.taskrunner.autotasks import AutoTasks, TaskPriority

def send_email(to: str, body: str) -> None:
    ...

tasks = AutoTasks()
tasks.task(send_email, "a@b.c", "hi", priority=TaskPriority.HIGH)
```

Return value is an ``rq.job.Job``. Hold on to ``job.id`` if you want
to check status later.

## Redis config

Read from the environment at construction time:

| Var | Default |
|-----|---------|
| ``REDIS_HOST`` | ``localhost`` |
| ``REDIS_PORT`` | ``6379`` |
| ``REDIS_USERNAME`` | unset |
| ``REDIS_PASSWORD`` | unset |
| ``REDIS_DB`` | ``0`` |

Override per-instance:

```python
tasks = AutoTasks(host="redis.prod", port=6380, password="...")
```

Override with a pre-built client (tests, multi-cluster apps):

```python
tasks = AutoTasks(redis_client=fake_redis)
```

Reset the process-wide singleton (mostly for tests):

```python
AutoTasks.reset_connection()
```

## Fetch / inspect / cancel

```python
tasks.get_task(job_id)           # single rq.job.Job
tasks.get_tasks(n=20)            # recent jobs across priorities
tasks.kill(job_id)               # cancel if queued, stop if running
```

## Running a worker

RQ's own CLI:

```bash
rq worker high default low --url redis://localhost:6379
```

Match the queue names to the ``TaskPriority`` enum:

| Priority | Queue name |
|----------|-----------|
| ``HIGH`` | ``high`` |
| ``NORMAL`` | ``default`` |
| ``LOW`` | ``low`` |

## Lazy connection

``AutoTasks()`` doesn't talk to Redis until the first call that needs
it (``task``, ``get_task``, ``get_tasks``, ``kill``, ``reset_connection``).
Importing the class in a process that never enqueues — a schema
migration script, a CLI tool — is free.

## Vector re-indexing

``AutoModel.save(sync=True)`` enqueues the saved document for
vector-embedding re-indexing. The handler lives in
``autonomous.db.db_sync``; wire a worker listening on the
``indexing`` queue if your app uses this.

See the [ORM guide](ormodel.md#vector-sync) for the model side.

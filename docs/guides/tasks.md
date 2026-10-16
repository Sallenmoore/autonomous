# Tasks — AutoTasks

``AutoTasks`` is a thin wrapper around [RQ](https://python-rq.org/) and
Redis that adds:

- Priority queues (``TaskPriority.HIGH`` / ``DEFAULT`` / ``LOW``).
- Convenient current-job introspection.
- A default job timeout (``TASK_JOB_TIMEOUT``, 7200 s); override per
  call with ``_task_job_timeout=<seconds>``.
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

Return value is an ``AutoTask`` wrapping the ``rq.job.Job``. Hold on to
``task.id`` if you want to check status later.

## Redis config

Read from the environment when the connection is first built:

| Var | Default |
|-----|---------|
| ``REDIS_HOST`` | ``cachedb`` |
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
tasks.get_task(job_id)           # AutoTask, or None
tasks.get_tasks()                # {"started"|"finished"|"failed"|"queued": [AutoTask, ...]}
tasks.kill(job_id)               # stop if running, then delete the job
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
| ``DEFAULT`` | ``default`` |
| ``LOW`` | ``low`` |

## Lazy connection

``AutoTasks()`` doesn't talk to Redis until the first call that needs
it (``task``, ``get_task``, ``get_tasks``, ``kill``).
Importing the class in a process that never enqueues — a schema
migration script, a CLI tool — is free.

## Vector re-indexing

``AutoModel.save(sync=True)`` enqueues the saved document for
vector-embedding re-indexing. The handler lives in
``autonomous.db.db_sync`` and is enqueued on the ``low`` priority
queue, so a worker listening on ``low`` must be running if your app
uses this.

See the [ORM guide](ormodel.md#vector-sync) for the model side.

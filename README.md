# Autonomous

:warning: :warning: :warning: WiP :warning: :warning: :warning:

![Tests](https://github.com/Sallenmoore/autonomous/actions/workflows/tests.yml/badge.svg)

**Autonomous** is an ORM + utility framework layer you lay over whatever
micro-framework you choose (Flask, FastAPI, Starlette, pure WSGI, an async
worker, a CLI) to stop rewriting the same containerized-service plumbing on
every project.

It is not a web framework. It ships a MongoDB-backed ORM, a Redis-backed task
runner, pluggable file storage, OAuth2 auth, AI-model adapters, and a tiny
WSGI-compatible response/session layer so the auth pieces drop into any host
framework without a hard dependency on it.

- **[pypi](https://test.pypi.org/project/autonomous)**
- **[github](https://github.com/Sallenmoore/autonomous)**

## What you get

| Area | Module | What it does |
|------|--------|--------------|
| ORM | `autonomous.model.automodel` | `AutoModel` — a MongoDB-backed document with typed attributes (`StringAttr`, `IntAttr`, `DateTimeAttr`, `ListAttr`, `ReferenceAttr`). Handles save/get/random/delete, inheritance, circular & dangling references. |
| Auth | `autonomous.auth` | `AutoAuth` base + `GoogleAuth` / `GithubAuth` OAuth2 flows built on Authlib; `AutoUser` model with authenticated / guest / admin roles; `@auth_required` decorator for host views. |
| Web shim | `autonomous.web` | WSGI-compatible `Response` + `redirect()`, a pluggable `SessionStore` protocol, a `ContextSession` default, and a stdlib-only `SignedCookieSession`. The auth decorator talks to these, not to any framework's globals. |
| Tasks | `autonomous.taskrunner.autotasks` | `AutoTasks` wraps RQ + Redis with priority queues, timeouts, current-job helpers. |
| Storage | `autonomous.storage` | `LocalStorage` + `ImageStorage` (thumbnails / resized variants) for filesystem-backed asset storage with URL resolution. |
| AI | `autonomous.ai.models.local_model`, `gemini` | Adapters for Ollama (local LLM), a media service for image/audio generation, and Google Gemini. All endpoints are HTTP so tests mock `requests.post`. |
| Logging | `autonomous.logger` | Leveled, toggleable logger reachable as `from autonomous import log`. |

## How it's meant to be used

Bring your own web micro-framework. Mount Autonomous components in your views,
tasks, and CLI scripts. The library stays framework-agnostic.

### Flask

```python
from flask import Flask, session as flask_session, url_for
from autonomous.auth import AutoAuth
from autonomous.auth.google import GoogleAuth
from autonomous.web import bind_session

app = Flask(__name__)
AutoAuth.login_url = "/auth/login"  # or url_for("auth.login") inside a request

@app.before_request
def _bind():
    # flask_session is already a dict-like; Autonomous will read/write it
    bind_session(flask_session)

@app.route("/me")
@AutoAuth.auth_required()
def me():
    return AutoAuth.current_user().to_json()
```

### FastAPI / Starlette / pure WSGI

```python
from autonomous.web import ContextSession, bind_session, redirect

def middleware(environ, start_response):
    bind_session(ContextSession())           # per-request dict session
    # ... dispatch to the view; if it returns a Response it's WSGI-callable:
    response = view(environ)
    return response(environ, start_response)
```

### Task runner

```python
from autonomous.taskrunner.autotasks import AutoTasks, TaskPriority

def send_email(to, body): ...

AutoTasks().task(send_email, "a@b.c", "hi", priority=TaskPriority.HIGH)
```

### ORM

```python
from autonomous.model.automodel import AutoModel
from autonomous.model.autoattr import StringAttr, IntAttr

class Post(AutoModel):
    title = StringAttr(default="")
    views = IntAttr()

p = Post(title="hello"); p.save()
Post.get(p.pk).title  # "hello"
```

## Dependencies

- **Languages**
  - [Python 3.12+](https://www.python.org/)
- **Containers**
  - [Docker](https://docs.docker.com/) + [Docker Compose](https://github.com/compose-spec/compose-spec/blob/master/spec.md)
- **Server**
  - [nginx](https://docs.nginx.com/nginx/) + [gunicorn](https://docs.gunicorn.org/en/stable/configure.html)
- **Database**
  - [pymongo](https://pymongo.readthedocs.io/en/stable/api/pymongo/index.html) (MongoDB driver)
- **Task queue**
  - [redis](https://redis.io/) + [rq](https://python-rq.org/)
- **Auth**
  - [Authlib](https://docs.authlib.org/) (OAuth2 / OIDC)
- **Networking**
  - [requests](https://requests.readthedocs.io/en/latest/)
- **AI**
  - [ollama](https://ollama.com/), [google-genai](https://pypi.org/project/google-genai/), [sentence-transformers](https://www.sbert.net/)
- **Testing**
  - [pytest](https://docs.pytest.org/) + [coverage](https://coverage.readthedocs.io/)
- **Documentation**
  - Hand-authored guides live under `docs/` (Markdown).
  - A zero-dependency generator at `scripts/gen_docs.py` introspects
    the public surface and renders a navigable HTML reference to
    `docs/_build/`.
  - Build: `make docs`. Then open `docs/_build/index.html`.

Autonomous has no framework dependency — pick your own (Flask, FastAPI, pure
WSGI, CLI) and plug Autonomous into it.

---

## Developer Notes

### TODO

- Setup/fix template app generator
- Switch to less verbose html preprocessor
- 100% testing coverage

### Issue Tracking

- None

## Processes

### Generate app

TBD

### Tests

```sh
make tests
```

### Package

1. Update version in `/src/autonomous/__init__.py`
2. `make package`

---

## Task List

Backlog of known improvements across the framework, sorted from
highest to lowest overall impact. Each item is tagged with the axis
it primarily addresses (**security** / **stability** / **functionality**
/ **efficiency** / **usability**) and a concrete file:line anchor.

1. **[security]** `apis/version_control/GHCallbacks.py:38` —
   `certificate_check` returns `True` unconditionally, disabling TLS
   verification for every git operation. Enable verification or make
   the bypass an explicit, logged opt-in.

2. **[stability]** AI backend signatures drift across
   `ai/models/local_model.py`, `ai/models/gemini.py`, and
   `ai/models/mock_model.py`. `generate_json` (`system_prompt` vs
   `function`), `upscale_image` (`image_content` vs `file`), and
   `generate_transcription` (structured dict vs raw text) disagree so
   swapping the backend raises at runtime. Pin signatures on
   `BaseAgent` and make adapters conform.

3. **[functionality]** `storage/imagestorage.py:224,239,250` —
   `remove()`, `rotate()`, and `flip()` unconditionally return
   `False` (TODO stubs). Implement the operations or remove them
   from the public surface.

4. **[stability]** `apis/version_control/GHRepo.py:97,99` — `commit()`
   hard-codes "Steven Moore" / "samoore@binghamton.edu" as the
   committer identity and uses a fixed commit message. Read from
   config or require args.

5. **[stability]** `auth/autoauth.py:129`, `auth/google.py:22` —
   userinfo is fetched with `requests.get(...).json()`: no timeout,
   no retry, no status-code check. Transient network blips propagate
   as 500s. Wrap in the existing `autonomous.ai.retry.retry` helper
   with a bounded timeout.

6. **[stability]** `ai/models/gemini.py:162-164` — unbounded `while`
   loop polling `file.state` with a 0.5s sleep and no cap. Add a
   max-attempts / wall-clock limit and raise on timeout.

7. **[functionality]** `cli.py` — `createapp()` is a single
   placeholder. Wire real commands: `autonomous init`,
   `autonomous docs build`, `autonomous tasks run-worker`.

8. **[functionality]** `model/automodel.py` — no bulk operations.
   Add `AutoModel.bulk_create(objs)` and `bulk_update(filter, **set)`
   backed by `insert_many` / `update_many`. Hot write paths currently
   loop `.save()` per object.

9. **[stability]** `apis/version_control/GHRepo.py:18,36-41` — `path`
   and `repo.name` are joined onto the on-disk target without
   traversal validation. Reuse `_sanitize_relative` / `_safe_join`
   from `storage/localstorage.py`.

10. **[stability]** GitHub APIs have no rate-limit handling. PyGithub
    raises `RateLimitExceededException` on 403; the wrappers ignore
    it. Catch, sleep until `reset_at`, retry.

11. **[functionality]** `apis/version_control/GHOrganization.py:31` —
    `get_repos()` iterates without pagination and silently truncates
    on orgs with more than 30 repos. Walk the full result set or
    accept a `page_size` kwarg.

12. **[efficiency]** `model/autoattr.py` `ListAttr.__get__` —
    reference pruning fetches each referent one at a time (N+1).
    Batch-resolve via `QuerySet.in_bulk` on the non-`None` pk set.

13. **[stability]** `db/db_sync.py:16-18` — `_redis_client`,
    `_mongo_client`, `_mongo_db` singletons are created under no
    lock. Guard with `threading.Lock` or use `functools.lru_cache`
    on the getter functions.

14. **[stability]** `logger.py:85-88` — handler opens files per call
    without locking. Concurrent `log()` calls from gunicorn workers
    interleave. Switch to `logging.handlers.RotatingFileHandler` or
    add an explicit write lock.

15. **[functionality]** `taskrunner/task_router.py` —
    `TaskRouterBase.ROUTES` is an empty list; no register decorator,
    no dispatch primitives. Flesh out as a route-name → callable
    registry or delete the module.

16. **[efficiency]** `ai/models/local_model.py:264-280` —
    `generate_text`, `generate_audio`, and `summarize_text` are
    single bare HTTP attempts. Route through the existing `retry()`
    helper.

17. **[functionality]** `db/signals.py:51-57` — pre/post init, save,
    delete only. No `pre_update` / `post_update` hook for partial
    field changes. Add signals and emit from the `.update()`
    helpers.

18. **[functionality]** No soft-delete pattern on `AutoModel`. Add
    an optional `SoftDeleteMixin` with `deleted_at` plus a queryset
    filter that hides tombstones by default.

19. **[functionality]** `storage/` — no S3 / cloud backend. Extract a
    minimal `StorageBackend` protocol; implement `S3Storage` as an
    extras-gated sibling of `LocalStorage`.

20. **[usability]** Hard-coded tuning knobs with no env-var override:
    `ai/models/local_model.py:32-36` (four timeouts),
    `storage/imagestorage.py:30` (thumbnail sizes),
    `storage/imagestorage.py:61,66` (`max_size=1024`),
    `taskrunner/autotasks.py:202` (7200s job TTL). Promote each to
    an env-driven default.

21. **[stability]** `ai/models/local_model.py:312-314` —
    `summarize_text` breaks its loop on the first exception and
    returns a partial summary silently. Count failures, raise when
    the whole batch fails, or route through `retry()`.

22. **[efficiency]** `ai/models/gemini.py:144,166` — `_add_files`
    calls `client.files.list()` once per upload batch to resolve
    filenames. Use the upload response directly.

23. **[functionality]** Test gaps — zero unit coverage for
    `apis/*`, `AutoTasks`, `ImageStorage.rotate/flip`, or the
    optional-dependency stubs in the doc generator. Add hermetic
    tests that don't require Mongo/Redis.

24. **[usability]** `autonomous/__init__.py` — only re-exports `log`
    + `init`. Add `AutoModel`, `AutoAuth`, `Response`, `AutoTasks`
    so consumers can `from autonomous import AutoModel`.

25. **[efficiency]** `db/db_sync.py:73` — hardcoded 5-second sleep in
    `process_single_object_sync`. Replace with exponential backoff
    via the `retry()` helper.

26. **[stability]** `ai/agents/imageagent.py:29` — debug
    `print("provider", self.provider)` left in the code path.
    Replace with `log(...)` or delete.

27. **[stability]** `utils/markdown.py:70-73` — recursive parser has
    no depth limit; pathological input can stack-overflow. Add an
    explicit depth cap (e.g., 128).

28. **[usability]** `apis/version_control/GHVersionControl.py:9-11`
    — `GHConfig` declares `name: float` / `email: int`; fields are
    never read anywhere. Fix the types or delete the dataclass.

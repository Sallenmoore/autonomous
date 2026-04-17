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

# Autonomous

Autonomous is an ORM + utility framework you lay over any Python
micro-framework (Flask, FastAPI, Starlette, pure WSGI, an async worker,
a CLI) to stop rewriting the same container-service plumbing on every
project.

It is **not** a web framework. It ships:

- A MongoDB-backed document ORM (``AutoModel`` + typed attributes).
- OAuth2 auth (``AutoAuth`` + Google / GitHub adapters) that plugs
  into whatever session you already have.
- Pluggable file storage — local filesystem today, swappable backends
  via the same API.
- A Redis-backed task runner (``AutoTasks``) with priority queues.
- A tiny WSGI-compatible ``Response`` + session layer so the auth
  pieces drop into any host framework without a hard dependency on it.
- AI model adapters for Ollama, Gemini, and a mock backend for tests.

## Guides

- [Quickstart](guides/quickstart.md) — install, connect, save your
  first document.
- [ORM — AutoModel and autoattr](guides/ormodel.md) — modeling,
  querying, relationships, inheritance.
- [Auth — AutoAuth and OAuth2](guides/auth.md) — wiring Google /
  GitHub auth into a Flask / WSGI app.
- [Storage — LocalStorage and ImageStorage](guides/storage.md) —
  file and image asset storage with URL resolution.
- [Tasks — AutoTasks](guides/tasks.md) — background jobs with
  priority queues.
- [Web — Response, Session, SignedCookieSession](guides/web.md) —
  the framework-agnostic HTTP primitives.
- [AI adapters](guides/ai.md) — Ollama, Gemini, Mock, and the
  retry helper.

## Reference

Auto-generated API reference for every public module and class:

- [API reference](api/index) — full tree, introspected by Sphinx
  autosummary.

## Project

- [Pipeline setup](pipeline-setup) — release flow, dev/test/main, CI.
- [README on GitHub](https://github.com/Sallenmoore/autonomous) — latest
  README + issue tracker.

```{toctree}
:hidden:
:caption: Guides
:maxdepth: 2

guides/quickstart
guides/ormodel
guides/auth
guides/ai
guides/web
guides/storage
guides/tasks
guides/configuration
```

```{toctree}
:hidden:
:caption: Reference
:maxdepth: 2

api/index
pipeline-setup
```

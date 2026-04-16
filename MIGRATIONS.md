# Migration Notes

Breaking and behavior-affecting changes for consumers of `autonomous`, most
recent first.

## Unreleased

### Flask is no longer a dependency (already landed)

- `flask` is gone from `requirements.txt`. If you relied on it being pulled in
  transitively by `autonomous`, add it to your own `requirements.txt`.
- `autonomous.auth.autoauth` no longer imports from `flask`. Consumers wire
  their session store and login URL explicitly:

  ```python
  from autonomous.auth import AutoAuth
  from autonomous.web import bind_session
  from flask import session as flask_session, url_for  # still works

  AutoAuth.login_url = "/auth/login"  # or url_for("auth.login") per-request

  @app.before_request
  def _bind():
      bind_session(flask_session)
  ```

- Decorated views (`@AutoAuth.auth_required()`) now return a WSGI-compatible
  `autonomous.web.Response` on redirect. Flask views can return it unchanged;
  other frameworks can call it as a WSGI app.

### Deferred MongoDB connection (Item 1)

**What changed.** `autonomous.model.automodel` no longer calls `connect(...)`
at import time. The connection is opened lazily on the first ORM operation
(`get`, `all`, `find`, `search`, `random`, `save`, `delete`), so importing the
ORM no longer triggers network I/O or fails when env vars are unset.

**Why.** Import-time side effects break tests, break alt-DB configs, and make
`autonomous` unusable in processes that don't need MongoDB (CLI scripts, docs
builds, linters).

**Migration.** Zero changes required if you set `DB_HOST`, `DB_PORT`,
`DB_USERNAME`, `DB_PASSWORD`, `DB_DB` before the first ORM call — the lazy
path picks them up the same way the old import-time code did.

Recommended: call `autonomous.init()` (or `autonomous.db.connect(...)`
directly) once at app startup for clearer failure modes and to override
settings programmatically:

```python
import autonomous
autonomous.init()  # uses env vars
# or
autonomous.init(host="mongo.prod", db="app", username="u", password="p")
```

`autonomous.db.db_sync` likewise replaced its module-level Redis/Mongo clients
with internal lazy getters. If you imported `from autonomous.db.db_sync import
r`, `mongo`, `db`, `MONGO_URI`, `MEDIA_URL`, `REDIS_HOST`, or `REDIS_PORT`,
those names are no longer exported — call the public functions (`get_vector`,
`request_indexing`, `process_single_object_sync`) instead.

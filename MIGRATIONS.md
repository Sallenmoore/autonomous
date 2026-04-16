# Migration Notes

Breaking and behavior-affecting changes for consumers of `autonomous`, most
recent first.

## Unreleased

### Optional dependencies moved to extras (Item 9)

**What changed.** ``requirements.txt`` shrank to just the deps that
``autonomous`` imports unconditionally (``python-dotenv``, ``pymongo``,
``blinker``, ``Authlib``, ``requests``). Everything else moved into named
extras configured under
``[tool.setuptools.dynamic.optional-dependencies]`` in ``pyproject.toml``:

| Extra | Adds | Used by |
|-------|------|---------|
| ``tasks`` | ``redis``, ``rq`` | ``autonomous.taskrunner.AutoTasks`` |
| ``images`` | ``pillow`` | ``autonomous.storage.ImageStorage`` |
| ``ai`` | ``google-genai``, ``pydub`` | ``autonomous.ai.models.gemini`` + audio |
| ``github`` | ``PyGithub``, ``pygit2`` | ``autonomous.apis.version_control.*`` |
| ``server`` | ``gunicorn`` | production WSGI server |
| ``all`` | (every other extra) | catch-all |

Each lives in its own ``requirements-<extra>.txt`` so it's still easy to
``pip install -r requirements-tasks.txt`` standalone.

Dropped from runtime entirely (no imports anywhere):
``setuptools`` (build-only), ``Flask``, ``jsmin``, ``ollama`` (the
client; the URL is hit via ``requests``), ``sentence-transformers``,
``dateparser``, ``python-slugify``.

**Why.** A 25-dep core dragged in a Postgres-sized install for users who
only wanted the ORM. Splitting into extras shrinks ``pip install
autonomous-app`` from ~1.5GB (sentence-transformers + torch + cuda
wheels) to a handful of MB; consumers opt into what they actually use.

**Migration.**

- If you used ``ImageStorage``, install ``autonomous-app[images]``.
- If you used ``AutoTasks``, install ``autonomous-app[tasks]``.
- If you used ``GeminiAIModel``, install ``autonomous-app[ai]``.
- If you used ``autonomous.apis.version_control.*``, install
  ``autonomous-app[github]``.
- Or: ``pip install autonomous-app[all]`` for the previous behaviour.
- Drop ``flask``, ``jsmin``, ``ollama``, ``sentence-transformers``,
  ``dateparser``, ``python-slugify`` from your own ``requirements.txt``
  if you don't import them yourself.

A new ``tests/unit/test_unit_packaging.py`` will fail CI if a future
change accidentally lists an unused dep in core, drops one of the extras
files, or forgets to register a new extra in ``pyproject.toml``.

### `auth_required` no longer writes on every request (Item 8)

**What changed.** The `@AutoAuth.auth_required()` decorator stopped
hammering the database and the session on every authenticated request:

- ``user.last_login`` is persisted at most once per
  ``cls.last_login_throttle_seconds`` (default ``60``). Subsequent
  requests within the window read the existing user but skip
  ``user.save()``.
- ``session["user"] = user.to_json()`` only runs if the rendered JSON
  differs from what's already in the session.
- New class attribute ``last_login_throttle_seconds`` controls the
  interval. Set it to ``0`` to restore the legacy "save on every
  request" behaviour.
- New helpers ``AutoAuth._touch_user(user)`` and
  ``AutoAuth._refresh_session_user(session, user)`` extracted for
  subclasses that need to override the policy.

**Why.** The old code did one Mongo write and one session write per
authed pageview. For a busy app that's hundreds of pointless writes per
second; in dev it floods the save signals. ``last_login`` doesn't need
second-level granularity.

**Migration.**

- If your app relies on ``last_login`` being current to the second, set
  ``AutoAuth.last_login_throttle_seconds = 0`` (or to a smaller window).
- If you observed side effects of ``user.save()`` firing on every
  request (cache invalidation, audit hooks), they now fire at most once
  per minute. Consider moving them to explicit triggers.
- If you store derived data in the session under ``"user"`` and rely on
  it being rewritten every request, push that data through a separate
  session key (or override ``_refresh_session_user``).

### Storage layers reject path traversal (Item 7)

**What changed.** ``LocalStorage`` and ``ImageStorage`` now sanitize every
user-supplied ``folder`` and ``asset_id`` before joining it under the
storage root.

- New helper ``_sanitize_relative(part)``: rejects absolute paths and any
  fragment whose normalized form contains a ``..`` segment. ``"a/../b"``
  collapses to ``"b"`` and is fine; ``"../etc"`` and ``"/etc/passwd"``
  raise ``ValueError``.
- New per-instance helper ``_safe_join(*parts)``: joins under the resolved
  ``base_path`` and asserts the resolved result is the base or a
  descendant. Anything else raises ``ValueError``.
- All public file-system entry points use ``_safe_join``:
  ``LocalStorage.save / get / get_path / search / move / remove``,
  ``ImageStorage.get_path / search``.

Read-side methods (``get``, ``remove``, ``search``) swallow the
``ValueError`` and return ``None`` / ``False`` / ``[]`` so a malformed
asset reference doesn't crash a request. Write-side methods (``save``,
``move``) raise so the caller sees the bad input.

**Why.** A user-supplied ``folder="../../etc"`` or
``asset_id="../../etc/passwd"`` previously concatenated straight onto the
storage root, letting an attacker (or a buggy upstream) read or
overwrite arbitrary files outside the storage tree.

**Migration.**

- If your app passed only safe, app-controlled folders, zero changes.
- If you ever passed user input as ``folder`` or ``asset_id``, callers
  that previously got back garbage now get ``ValueError`` (writes) or
  empty results (reads). Catch it at the boundary you accept user input.
- ``"...etc"`` and other names that merely *look* like ``..`` are still
  accepted — the check is on path *segments*, not prefix.

### OAuth state is now validated against the session (Items 6 & 19)

**What changed.** ``AutoAuth.authenticate()`` rotates ``self.state`` on
every call and stores the issued nonce in the active session under
``state_session_key`` (default ``"oauth_state"``).
``AutoAuth.handle_response()`` reads it back, refuses callbacks with no
stored state, and clears the session entry whether the exchange succeeded
or failed (so a replayed callback can't be re-validated).

If the caller passes ``state=`` explicitly, that value still wins —
backward compatible with apps that already round-tripped state through
their own session.

**Why.** Previously the issued state was generated once in ``__init__``,
overwritten on every ``authenticate()``, and never enforced on the
callback. An attacker could send a victim a crafted callback URL and the
library would happily exchange the code for a token under the victim's
session — classic OAuth login CSRF.

**Migration.**

- If you bound a session store via ``autonomous.web.bind_session(...)`` (or
  the Flask snippet in the README), zero code changes — state moves
  through that store automatically.
- If you stored the state yourself between ``authenticate()`` and
  ``handle_response()``, keep doing it; pass ``state=`` to
  ``handle_response`` and the session lookup is bypassed.
- If you do not bind a session, ``handle_response()`` raises
  ``MismatchingStateError``. Bind a session at startup, or store and pass
  the state explicitly.
- Subclasses with multiple providers in one app should override
  ``state_session_key`` to keep providers' state from colliding.

### Narrowed exception catches + bare `raise` (Items 5 & 14)

**What changed.** Broad `except Exception` blocks in first-party code were
tightened to the specific errors each site actually expects:

| File | Site | New catch |
|------|------|-----------|
| `model/automodel.py` `AutoModel.get` | DB failure | `pymongo.errors.OperationFailure`, `pymongo.errors.ConnectionFailure` (bare `raise`, no more `raise e`) |
| `db/db_sync.py` `get_vector` | embedding HTTP | `requests.RequestException`, `ValueError`, `KeyError` |
| `db/db_sync.py` oid coercion | bson parse | `bson.errors.InvalidId`, `TypeError` |
| `db/db_sync.py` `request_indexing` | enqueue | `redis.RedisError`, `ConnectionError` |
| `taskrunner/autotasks.py` `get_task` | fetch | `rq.exceptions.NoSuchJobError`, `redis.RedisError` |
| `ai/models/local_model.py` `flush_memory`, `generate_text`, `generate_json` retry, `summarize_text`, `generate_transcription`, `generate_audio`, `generate_image` | HTTP / JSON / audio | combinations of `requests.RequestException`, `json.JSONDecodeError`, `ValueError`, `OSError`, `KeyError` |
| `ai/models/gemini.py` 5 sites | Google genai | `google.genai.errors.APIError` + relevant parse errors; stopped `raise e`ing |

Rule applied: catch only expected failures; re-raise with a bare `raise`
(preserves the original traceback); let unexpected errors (`AttributeError`
from typos, `MemoryError`, `KeyboardInterrupt`) propagate.

**Why.** Broad catches hid bugs and destroyed tracebacks via `raise e`. The
retry loop in `generate_json` also slept 30 s on any error — including
transient programming errors — masking regressions during development.

**Migration.** If your code deliberately raised unusual types from callbacks
inside `AutoModel.get`, `LocalAIModel.generate_*`, or `GeminiAIModel.generate_*`
and relied on the library silently logging them, those now propagate. Catch
them at your call site instead.

### Logger is lazy + proxied; file I/O is optional (Item 4)

**What changed.**

- Importing `autonomous.logger` (or `from autonomous import log`) no longer
  creates a `logs/` directory or touches the filesystem. Path setup is
  deferred to the first actual `log(...)` call.
- Constructing a `Logger()` likewise has no side effects.
- The module-level `log` is now a proxy (`_DefaultLoggerProxy`) that lazily
  instantiates the real `Logger` on first use. All attribute access and calls
  delegate to the underlying instance, so ``from autonomous import log`` and
  ``log.enable(False)`` / ``log.set_level("DEBUG")`` continue to work.
- New factory `autonomous.get_logger(name="gunicorn.error")` returns an
  independent `Logger` for tests and subsystems that want isolation.
- New env var `LOG_TO_FILES=0` disables the archive/current-run file writes
  without having to subclass. Per-call `logger.enable_file_logging(False)`
  does the same at runtime.
- File write errors (read-only disk, permission denied) no longer crash the
  caller — the handler swallows `OSError`.

**Why.** The old code ran `os.makedirs("logs")` at import and opened two
files on every call, which broke test isolation, tripped up read-only
filesystems, and made importing the ORM / auth layers depend on CWD being
writable.

**Migration.** Zero code changes required for normal use. A few edge cases:

- If you relied on `logs/` existing simply because you imported the package,
  call `log("startup")` once or `os.makedirs("logs", exist_ok=True)`
  yourself.
- If you patched `autonomous.logger.log` in tests (replacing it with a mock),
  that still works because the proxy is at the same attribute name.
- If you want a per-test or per-subsystem logger that you can disable
  independently, use `from autonomous import get_logger` rather than sharing
  the default.

### Mutable default args replaced with None sentinel (Item 3)

**What changed.** The AI-model entry points no longer use mutable literals
(`context={}`, `filters=[]`) as default values. Defaults are now `None`, and
each function normalizes to a fresh empty container internally.

Affected signatures:

- `LocalAIModel.generate_json(..., context=None, ...)`
- `LocalAIModel.generate_text(..., context=None, ...)`
- `MockAIModel.generate_json(..., context=None)`
- `MockAIModel.generate_text(..., context=None)`
- `GeminiAIModel.generate_json(..., context=None)`
- `GeminiAIModel.generate_text(..., context=None)`
- `GeminiAIModel.list_voices(filters=None)`

**Why.** A shared mutable default dict persists across calls. If one caller
mutated `context`, every subsequent caller would observe the mutation —
intermittent, rare, hard-to-debug failures.

**Migration.** Zero code changes needed. Passing `context={}` / `filters=[]`
still works identically; only the default changed.

### Storage paths come from env vars (Item 2)

**What changed.** `LocalStorage(path=...)` and `ImageStorage(path=...)` no
longer have hardcoded string defaults in the signature. If `path` is omitted
they consult env vars:

| Class | Env var | Fallback |
|------|---------|----------|
| `LocalStorage` | `STORAGE_PATH` | `static` |
| `ImageStorage` | `STORAGE_IMAGE_PATH` | `<STORAGE_PATH>/images` |

`LocalStorage.base_url` also stopped rendering `None/...` when
`APP_BASE_URL` is unset; it now falls back to a site-relative `"/<path>"`.

**Why.** Hardcoding `"static"` tied every deployment to the same on-disk
layout. The env-var indirection lets you point at a mounted volume, a
per-environment bucket mount, or a test tmpdir without subclassing.

**Migration.** If you always passed `path=` explicitly, nothing changes. If
you relied on the string default `"static"` / `"static/images"`, nothing
changes either — that's still the fallback. If you set `APP_BASE_URL=""` and
depended on the old `"None/..."` URL shape, update your consumers to handle
`"/..."`.

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

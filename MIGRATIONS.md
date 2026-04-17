# Migration Notes

Breaking and behavior-affecting changes for consumers of `autonomous`, most
recent first.

## Unreleased

### autonomous.db fork — dead surface removal (Item 23)

**What changed.** ~1800 LOC of unreferenced mongoengine carry-over was
deleted from `src/autonomous/db/`. Nothing in `autonomous.model.*`
imports these names and no tests covered them, but a subclass reaching
directly into `autonomous.db.fields` (for example, a custom `AutoModel`
that declared `from autonomous.db import URLField`) will now fail at
import. Substitutes below.

**Removed field classes.**

| Removed | Replacement |
|---------|-------------|
| `URLField` | `StringField` + your own regex / validator |
| `LongField` | `IntField` (Python 3's `int` is already 64-bit) |
| `DecimalField`, `Decimal128Field` | `FloatField` for inexact; store as `StringField` if you need exact precision |
| `ComplexDateTimeField` | `DateTimeField` (Mongo's BSON datetime has millisecond precision; store a separate microsecond field if you need more) |
| `BinaryField` | `StringField` with your own `bytes.hex()` / `bytes.fromhex()` round-trip, or hold the bytes outside Mongo in `LocalStorage` |
| `UUIDField` | `StringField` holding `str(uuid.uuid4())` |
| `SortedListField` | `ListField` — sort in Python on access |
| `MapField` | `DictField` — it doesn't enforce a homogeneous value type, but first-party code never depended on that |
| `GenericEmbeddedDocumentField` | `EmbeddedDocumentField` pinned to the concrete class |
| `SequenceField` | `ObjectIdField` (the default primary key) |
| `CachedReferenceField` | `ReferenceField` |
| `LazyReferenceField`, `GenericLazyReferenceField` | `ReferenceField` / `GenericReferenceField` (always eagerly dereferenced via `ReferenceAttr`) |
| `GeoPointField`, `PointField`, `LineStringField`, `PolygonField`, `MultiPointField`, `MultiLineStringField`, `MultiPolygonField`, `GeoJsonBaseField` | no replacement — drop geo queries or add geo support back on the caller side |

Also removed:

- `autonomous.db.base.LazyReference` — the proxy returned by the lazy
  reference fields.
- `autonomous.db.document.MapReduceDocument` — MongoDB's mapReduce
  command is deprecated. Use `.objects.aggregate(pipeline)` instead.
- `QuerySet.map_reduce()`, `QuerySet.item_frequencies()` — both were
  server-side-JS paths (the `mapReduce` and `eval` commands). The
  `eval` command was removed in Mongo 4.2; `mapReduce` is deprecated
  in 5.0. Replace with an aggregation pipeline.
- Geo query operators: `within_*`, `near`, `near_sphere`, `geo_*`,
  `max_distance`, `min_distance`. The `_geo_index` / `_geo_indices`
  index-generation hooks are gone too; indexes now come from explicit
  `meta = {"indexes": [...]}` plus `_unique_with_indexes`.

**Deferred.** `DynamicDocument` / `DynamicEmbeddedDocument` /
`EmbeddedDocument` (+ their field descriptors and the related
datastructures) stay in the tree for now — removing them cleanly
requires a targeted pass on `base/document.py` and the metaclass. Do
not add new callers; they'll disappear in a follow-up.

**Why.** The fork was vendored from mongoengine, grew with the project,
and never had unused surface pruned. Every removed class was either
zero-consumed, shadowed by a simpler alternative, or wired to a
deprecated MongoDB command. Narrower public surface means faster
imports, fewer code paths for bugs to hide in, and a shorter mental
map for new contributors.

**Migration.**

- Grep your codebase for each name in the table. If you used one, pick
  the listed replacement (most are one-line substitutions).
- If you constructed any geo operator via `.filter(field__near=...)`
  etc., rewrite the query to use an aggregation stage — or restore
  `GeoJsonBaseField` + its fields out-of-tree if you need them.
- `QuerySet.map_reduce()` / `QuerySet.item_frequencies()` callers
  should switch to `AutoModel.objects.aggregate(...)`. See the Mongo
  aggregation docs for equivalents of the emit/reduce pattern.
- Fork-level details, including the "what's still deferred" list,
  live in `src/autonomous/db/DIVERGENCE.md`.

### `AutoModel.where()` — chainable query API (Item 20)

**What changed.** New classmethod ``AutoModel.where(**kwargs)`` returns
the underlying mongoengine ``QuerySet`` for chaining. Uses the same
``str -> __icontains`` convenience mapping as ``search`` but does not
materialize a list, so callers can keep composing:

```python
# Top-ten latest "hello"-ish posts
posts = Post.where(title="hello").order_by("-created").limit(10)

# First match of an exact lookup
author = Post.where(author_id=pk).first()

# Count without fetching rows
n = Post.where(published=True).count()

# Mix convenience and raw operators
Post.where(name="alice", views__gt=1000, tags__in=["python"])
```

Rules for kwargs:
- A ``str`` value with a plain field name (no ``__`` suffix) becomes
  ``<field>__icontains=<value>`` — case-insensitive substring match.
- Anything else (including keys that already contain ``__``) passes
  straight through to mongoengine.

**Why.** ``AutoModel.search`` returns a ``list``, which dead-ends
chaining. Consumers who discovered ``Model.objects.filter(...)`` could
chain, but that's undocumented and requires knowing mongoengine.
``.where()`` makes chaining discoverable with the same ergonomic
defaults as ``search``.

**Migration.** Additive. ``search`` still returns a list for
backward compatibility; prefer ``where`` for new code. There is no
deprecation warning — ``search`` is useful when you know you want the
list and don't care about chaining.

### autonomous.db fork cleanup (Item 22)

**What changed.** Focused pass over the vendored-then-forked
mongoengine tree at `src/autonomous/db/`. Not a re-sync with upstream;
concrete wins only.

- Narrowed every broad `except Exception` in first-party-ish code to
  the concrete errors each site actually expects (15 sites):
  - `base/fields.py` ObjectIdField to_python / to_mongo / validate,
    change-detection comparison (tz-naive vs tz-aware TypeError only).
  - `common.py` `_import_class` — catches `(ImportError, AttributeError,
    ValueError)`; re-raises as `ImportError` with `from e`.
  - `connection.py` `_create_connection` — catches
    `(pymongo.errors.PyMongoError, ValueError, TypeError)`.
  - `fields.py` BinaryField decode, ComplexDateTimeField parse, GridFS
    get/read/delete, ImageField validate — narrowed per site.
  - `document.py` DBRef key cast — catches `(TypeError, ValueError)`;
    re-raises as `TypeError`.
  - `queryset/base.py` sort translation, `queryset/transform.py` field
    lookup — catch `(LookupError, AttributeError)`.
- Removed 15 `# log(...)` debug stubs from `db/fields.py`,
  `db/base/fields.py`, `db/base/document.py`, `db/base/datastructures.py`.
- Dropped an unused `# EmbeddedDocumentList` import comment and a stale
  `# from autonomous.db.common import _import_class` comment.
- Added `src/autonomous/db/DIVERGENCE.md` documenting why the fork
  exists, every behavior delta vs upstream mongoengine that users rely
  on, and the rule for adding future divergence.

**Why.** The fork is maintained independently of upstream (per the
project owner) and had accumulated broad catches, dead comments, and no
written record of what the fork's guarantees are. Narrowing the
catches preserves tracebacks for unexpected errors. DIVERGENCE.md makes
the fork survivable across maintainers.

**Migration.**

- If you caught exotic errors (`MemoryError`, `KeyboardInterrupt`,
  `AssertionError`) leaking from within these call sites because the
  library swallowed them, those now propagate. Catch at your call site.
- Error subtypes within the expected categories still behave the same —
  an `InvalidId` still ends up as a `ValidationError` via
  `ObjectIdField.validate`, etc.

**Explicitly deferred** (audit suggested, not done here): type
annotations on the `Document` / `QuerySet` / `Field` public surface
(item #6 in the audit), `DocumentMetaclass` simplification (#11), and
GridFS handle-leak audit (#14). All three risk destabilizing
mongoengine's metaclass magic and deserve their own focused passes.

### Unit vs integration test split (Item 21)

**What changed.**

- ``pytest`` with no args now discovers only the hermetic suite under
  ``tests/unit/`` — no Mongo / Redis / AI services required.
- Previously-unit tests that actually needed the full service stack
  (``test_unit_ai.py``, ``test_unit_auth.py``, ``test_unit_automodel.py``,
  ``test_unit_storage.py``, ``test_unit_tasks.py``) moved to
  ``tests/integration/`` and were renamed to ``test_int_*.py``.
- ``tests/integration/conftest.py`` auto-applies the
  ``@pytest.mark.integration`` marker so ``pytest -m integration`` works.
- The marker is registered in ``pyproject.toml`` so pytest no longer
  warns about unknown markers.
- ``tests/docker-compose.yml`` was added with Mongo + Redis services
  matching the integration-test env vars. ``tests/.testenv`` ships the
  matching env defaults so ``pytest`` picks them up.
- ``Makefile`` targets:
  - ``make test`` — hermetic unit tests (fast, no services needed)
  - ``make test-int`` — integration tests (spins up compose stack first)
  - ``make test-all`` / ``make tests`` — both
  - ``make inittests`` — bring up the compose stack
  - ``make cleantests`` — tear it down

**Why.** The unit directory had grown to contain tests that required a
live Mongo + Redis, forcing every local ``pytest`` invocation to bring
up Docker or fail. The split makes the cheap tests run in under 3
seconds on a bare laptop and isolates the integration stack to the one
target that needs it.

**Migration.**

- If your CI invoked ``pytest`` and assumed it ran everything, switch
  to ``make test-all`` or ``pytest tests/unit tests/integration``.
- If you relied on a hand-rolled compose file at ``tests/docker-compose.yml``,
  the new version expects env vars matching ``tests/.testenv``; diff and
  merge.
- Test files moved to ``tests/integration/`` were renamed from
  ``test_unit_*.py`` to ``test_int_*.py``. Import paths are unchanged;
  CI patterns that grep for ``test_unit_`` may need updating.

### Retry helper extracted from local_model.py (Item 17)

**What changed.** New module ``autonomous.ai.retry`` exposes a
single ``retry(func, *, max_attempts, sleep_seconds, catch, on_retry,
default)`` helper that centralizes the "try-N-times-with-backoff-and-
between-attempt-side-effects" pattern previously inlined inside
``LocalAIModel.generate_json``.

The hook signature ``on_retry(attempt, exc)`` lets the caller plug in
side effects that the AI adapter needs between attempts — for example
``flush_memory`` after an empty Ollama response — without baking them
into the retry helper.

``LocalAIModel.generate_json`` is now ~30 lines shorter; the request
work and the recovery hook live in two clearly-named closures, and the
retry plumbing is one ``retry(...)`` call.

**Why.** The retry logic was tangled with payload construction and
logging. The next retry-style adapter (Gemini text, audio, image
generation) was on track to copy-paste the same loop with subtle
differences. Pulling it out keeps callers focused on what's being
retried, not how.

**Migration.** No behavioral changes for callers of ``generate_json``:

- Same number of attempts (3).
- Same sleep between attempts (``self._retry_sleep``).
- Same catch tuple (``RequestException``, ``JSONDecodeError``,
  ``ValueError``, ``KeyError``).
- Same default on total failure (``{}``).
- Same ``flush_memory`` side effect on empty-response retries.

If you want to use the helper in your own code:

```python
from autonomous.ai.retry import retry

result = retry(
    do_thing,
    max_attempts=3,
    sleep_seconds=1.0,
    catch=(MyError,),
    on_retry=lambda attempt, exc: log(f"retry {attempt}: {exc}"),
    default=None,        # omit to re-raise on exhaustion
)
```

### `Response.body` accepts iterables for streaming (Item 16)

**What changed.** ``autonomous.web.response.Response`` now accepts any
iterable of ``bytes`` / ``str`` chunks as ``body``, in addition to the
existing ``bytes`` / ``str`` whole-payload form.

- A single ``bytes`` / ``str`` body is yielded as one chunk (legacy).
- A ``list``, ``tuple``, generator, or other iterable is consumed
  chunk-by-chunk; each ``str`` chunk is utf-8-encoded.
- File streaming idiom: ``Response(body=iter(lambda: fh.read(8192), b""))``.
- Empty ``b""`` body still yields one ``b""`` chunk so WSGI servers
  see a finite iterable.
- Both ``__iter__`` and the WSGI callable ``__call__(environ,
  start_response)`` route through the new ``iter_chunks()`` method, so
  any consumer that does ``list(response)`` or ``b"".join(response)``
  continues to work.

**Why.** The previous Response materialized the whole body in memory.
Serving a multi-GB file or proxying an upstream response forced the
entire payload through the heap. Iterables let the WSGI server flush
chunks incrementally — chunked transfer encoding kicks in
automatically when ``Content-Length`` is absent and the iterable yields
more than one chunk.

**Migration.**

- If you stored the WSGI body and asserted ``body == [b"..."]`` in a
  test, switch to ``list(body) == [b"..."]`` — ``__call__`` now returns
  a generator, not a list.
- If you constructed ``Response(body=...)`` with a generator before
  (the old code only iterated the body once and lost everything past
  the first ``yield``), it now works correctly.
- Generator bodies are single-pass — calling ``list(response)`` twice
  on the same response yields ``[]`` the second time. This matches
  WSGI semantics; previously the bug was masked by the materialization.

### `SignedCookieSession` gains optional expiry + issuer binding (Item 15)

**What changed.** ``SignedCookieSession`` now accepts two optional
keyword arguments and embeds matching claims in a reserved ``__meta__``
key inside the payload:

- ``max_age`` (seconds): producer attaches ``exp = iat + max_age``;
  consumer rejects tokens past ``exp``.
- ``issuer`` (str): producer attaches ``iss``; consumer rejects tokens
  with no matching ``iss``.

Both are independently optional and asymmetric:

- A consumer with **neither** set behaves exactly as before — backward
  compatible with cookies minted by older versions (no ``__meta__`` at
  all).
- A consumer with ``max_age`` set rejects tokens with no ``exp``
  (downgrade defense — an attacker can't strip the claim by re-signing
  with a leaked key on an old cookie).
- A consumer with ``issuer`` set rejects tokens missing or mismatching
  ``iss`` (cross-app token-reuse defense).
- A consumer that doesn't set ``issuer`` ignores any ``iss`` present
  (allows third-party verifiers).

The reserved payload key ``__meta__`` is stripped on load, so a caller
who happens to store ``session["__meta__"] = ...`` cannot clobber the
envelope or leak it back into their dict.

**Why.** The previous signed cookie was infinitely valid. If the
signing key ever leaked, every historical session was usable
indefinitely. Pinning expiry and issuer narrows the blast radius — you
can rotate the key, drop the issuer, or shorten ``max_age`` and old
cookies stop verifying.

**Migration.** Zero changes for existing apps. To opt in:

```python
session = SignedCookieSession.from_cookie(
    secret, request.cookies.get("session"),
    max_age=86400,        # 24h
    issuer="my-app",
)
```

Use the same ``max_age`` / ``issuer`` on the producer side
(``SignedCookieSession(secret, initial, max_age=..., issuer=...)``).
Skew older cookies that lack the metadata are rejected, so deploy
producer-side first, wait one cookie-lifetime, then enable on the
consumer side — or just let the brief gap log out users once.

### `auto_pre_init` hardened; falsy values preserved; opt-out added (Item 13)

**What changed.** ``AutoModel.auto_pre_init`` (the pre-init signal hook
that side-loads stored fields when you write ``Model(pk=x)``) is now:

- Defensive against missing / empty ``values`` kwargs.
- Defensive against malformed primary keys (``Model(pk="not-an-oid")``
  no longer raises ``InvalidId`` from inside ``__init__``).
- Defensive against ``OperationFailure`` / ``ConnectionFailure`` from
  Mongo — the merge is skipped and instantiation continues. The error
  is logged via ``log()``.
- **Bug-fix:** the merge condition changed from ``not values.get(k)``
  (which clobbered legitimate falsy values like ``0``, ``False``, ``""``,
  ``[]``) to ``k not in values``. The caller's explicit values are
  always honored.

**New class attribute:** ``auto_load_on_init: bool = True``. Set to
``False`` on a subclass that doesn't want a Mongo round trip per
``Model(pk=x)`` construction. The default keeps the existing
"reload-on-init" pattern intact.

**Why.** The old hook had three real bugs (silent clobber of falsy
values, raise on bad pk, raise on DB outage) and no opt-out. Combined
they made ``Model(pk=x, count=0)`` silently lose the explicit ``0``
overwrite, made bad input crash the constructor, and made every read
path hit Mongo even in batch jobs that already had the data.

**Migration.**

- If your code used to write ``Model(pk=x, name="")`` expecting the
  empty string to be ignored, you now get ``""``. If you wanted the
  stored value, drop the kwarg.
- ``Model("not-a-real-oid")`` now constructs a fresh instance (no
  side-load) instead of raising. ``Model.get(...)`` is still the right
  way to look up by pk if you want None on miss.
- High-throughput read paths can disable the side-load by setting
  ``auto_load_on_init = False`` on the subclass.

### `AutoTasks` opens Redis lazily; supports injection (Item 12)

**What changed.**

- ``AutoTasks()`` no longer opens a Redis socket in ``__init__``. The
  process-wide ``AutoTasks._process_connection`` is built lazily on the
  first method that needs it (``task``, ``get_task``, ``get_tasks``,
  ``kill``, etc.).
- The ``config`` class attribute (which froze env vars at class-definition
  time) is gone. Env vars are read fresh inside ``_build_connection`` —
  so changing ``REDIS_HOST`` between import and first call works.
- New constructor kwargs: ``AutoTasks(redis_client=...)`` injects an
  arbitrary client (great for tests, multi-cluster apps).
  ``AutoTasks(host=..., port=..., password=..., username=..., db=...)``
  builds a per-instance client without affecting the singleton.
- New ``AutoTasks.reset_connection()`` classmethod drops the singleton
  so it gets rebuilt on the next call. Test helper.
- ``self._connection`` is now a property that returns whichever
  connection is appropriate (instance > singleton > lazy build).

**Why.** The class-attribute ``config = {... os.environ.get(...) ...}``
ran at import. Tests had to either spin up Redis or monkeypatch the
class. Multi-tenant deployments couldn't change config without restart.

**Migration.**

- If you imported ``AutoTasks`` in a process that doesn't have Redis
  available (e.g. a CLI tool that only uses the ORM), zero changes —
  the import is now silent.
- If you read ``AutoTasks.config`` directly, that attribute is gone;
  use the env vars or the new constructor kwargs.
- If you assigned to ``AutoTasks._connection`` to inject a fake in
  tests, switch to ``AutoTasks(redis_client=fake)`` (or set
  ``AutoTasks._process_connection = fake`` if you really need
  process-wide override).
- Direct ``tasks._connection`` reads still work — the property returns
  the right thing.

### Public surface is now type-hinted (Item 11)

**What changed.** Added type annotations and ``from __future__ import
annotations`` to the project's user-facing classes:

- ``autonomous.model.automodel.AutoModel`` — ``get / random / all / find /
  search / save / delete / model_name / get_model / load_model``, plus a
  ``PrimaryKey`` alias and ``-> Self | None`` returns where appropriate.
- ``autonomous.storage.localstorage.LocalStorage`` — every public method,
  with a new ``AssetRef`` alias for the ``{"asset_id", "url"}`` dict.
- ``autonomous.storage.imagestorage.ImageStorage`` — every public method,
  including ``Iterator[str]`` for ``scan_storage``.
- ``autonomous.auth.autoauth.AutoAuth`` — ``__init__``, ``current_user``,
  ``authenticate``, ``handle_response``, ``auth_required``, plus the
  internal ``_touch_user`` / ``_refresh_session_user`` / ``_build_session``.

The ``autonomous.web`` module was already typed in earlier items.

A guard test (``tests/unit/test_unit_type_hints.py``) inspects each
public method via ``inspect.signature`` and fails CI if a future change
silently drops a return / argument annotation.

**Why.** Hints make IDE autocomplete useful, give mypy / pyright something
to chew on, and serve as machine-checkable documentation.

**Migration.** Zero code changes. ``from __future__ import annotations``
keeps everything as strings at runtime, so even runtime ``isinstance``
checks against the annotation values are unaffected. Subclasses that
override these methods are not forced to add annotations.

### ImageStorage cache: mtime invalidation, atomic write, safe failure (Item 10)

**What changed.**

- ``ImageStorage.get_url(asset_id, size=...)`` now compares the cached
  variant's mtime against the original. If the original is newer (e.g.
  after ``rotate``/``flip``, or after a manual replacement), the variant
  is regenerated automatically.
- The variant write goes through a sibling ``.tmp`` + ``os.replace`` so
  a half-written file can't be served if two requests race.
- After regeneration the variant's mtime is pinned to the original's, so
  the freshness comparison stays stable across sub-second writes and
  clocks that don't tick.
- ``full_url=True`` now works for ``size="orig"`` and for already-cached
  variants, not just the post-resize branch.
- A failed resize logs and returns ``None``. **It no longer calls
  ``self.remove(asset_id)``**, which previously wiped the entire asset
  on a single bad call.
- ``get_url("")`` still returns ``""``; ``get_url(None)`` and
  ``get_url("../etc/passwd")`` return ``None`` (item 7's traversal
  hardening was already in place).

**Why.** The old code never invalidated, so any in-place edit of the
original left stale variants forever (or until ``clear_cached`` was
called manually). The destructive failure mode was a footgun — one
corrupted source took down the whole asset.

**Migration.**

- If you relied on ``get_url`` returning a relative URL even when
  ``APP_BASE_URL`` was set and ``full_url=True``, that was a bug; the
  full URL is now returned consistently.
- If you relied on ``get_url`` deleting the asset on resize failure (an
  odd thing to rely on), call ``storage.remove(asset_id)`` yourself.
- Manual variant clearing via ``clear_cached`` still works but is no
  longer required after ``rotate`` / ``flip`` — mtime invalidation
  handles it.

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

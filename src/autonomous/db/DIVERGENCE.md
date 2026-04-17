# autonomous.db — divergence from upstream mongoengine

This tree started as a vendored copy of [mongoengine](https://github.com/MongoEngine/mongoengine)
and has been maintained independently since. It does **not** track
upstream; bugfixes and API changes do not flow either direction
automatically.

This file is the source of truth for why the fork exists and what's
meaningfully different from stock mongoengine. Keep it up to date when
you intentionally change behavior.

## Why a fork

- Upstream mongoengine's dereferencing, signals, and change-tracking
  didn't match the usage patterns `autonomous` needs (single-instance
  auto-load via `Model(pk=x)`, lazy connect, etc.).
- We depend on concrete pymongo behaviour tighter than mongoengine
  guarantees and didn't want to track their compatibility matrix.
- The fork is small enough that a clean-room sync would cost more than
  just maintaining what's here.

## Behavioural differences from upstream mongoengine

### Lazy connection (2026 cleanup, item 1)

`autonomous.model.automodel.AutoModel` no longer calls `connect()` at
import time. The first ORM operation (`get`, `save`, etc.) triggers
`_ensure_connected`, which reads `DB_HOST` / `DB_PORT` / `DB_USERNAME` /
`DB_PASSWORD` / `DB_DB` from the environment. Consumers who want
explicit control should call `autonomous.init()` or
`autonomous.db.connect(...)` at startup.

Upstream requires `connect()` before any document operation; we allow
zero-config via env.

### `auto_pre_init` side-load (2026 cleanup, item 13)

When a caller constructs `Model(pk=x)` without other kwargs, our
pre-init hook fetches the stored document and merges the stored fields
into `values`. Caller kwargs always win. This implements the
`Model(pk=x, name="new")` → "load then mutate" pattern.

Differences from upstream:
- Opt-out via class attribute `auto_load_on_init = False`.
- Explicit falsy caller values (`0`, `False`, `""`, `[]`) are honored
  (upstream analog would have clobbered them with DB values).
- Bad primary keys don't raise from inside `__init__`; the side-load is
  just skipped.
- DB outages (`OperationFailure`, `ConnectionFailure`) are logged and
  skipped; instantiation continues with caller-supplied values only.

### Narrowed exception handling (2026 cleanup, item 22)

Several `except Exception` blocks were tightened to the specific error
types each site actually expects:

- `base/fields.py` ObjectIdField — catches `bson.errors.InvalidId`,
  `TypeError` instead of bare `Exception`.
- `base/fields.py` change-detection — catches `TypeError` (tz-naive vs
  tz-aware datetime comparisons) only.
- `common.py` `_import_class` — catches `ImportError`,
  `AttributeError`, `ValueError`. Re-raises as `ImportError` with the
  original chained via `from`.
- `connection.py` `_create_connection` — catches
  `pymongo.errors.PyMongoError`, `ValueError`, `TypeError`.
- `fields.py` BinaryField decode, ComplexDateTimeField parse, GridFS
  get/read/delete, ImageField validate — narrowed per site.
- `document.py` DBRef key cast — catches `TypeError`, `ValueError`;
  re-raises as `TypeError`.
- `queryset/base.py`, `queryset/transform.py` — narrowed to
  `LookupError`, `AttributeError`.

Unexpected errors now propagate with original tracebacks. No observable
change for well-formed inputs; malformed inputs surface clearer
exceptions.

### Custom helpers / attributes

- `autonomous.db.db_sync` — project-specific vector-indexing trigger.
  Not in upstream.
- `AutoModel.auto_pre_init` / `auto_post_init` / `auto_pre_save` /
  `auto_post_save` — subclass-overridable signal hooks. Upstream
  connects signals directly; we delegate through these so subclasses
  can specialize without touching the signal wiring.

## What we don't diverge on

- Field types and their semantics. `StringField` / `IntField` /
  `ReferenceField` / etc. behave as upstream documents.
- QuerySet semantics. `.objects.filter(...)`, `.order_by(...)`,
  `.limit(...)` behave as upstream.
- Signals. We use `blinker` the same way upstream does.
- Bson / pymongo version compatibility is tied to whatever pymongo
  version is pinned in `requirements.txt`.

## How to make a change here

1. If you're fixing a bug, add a note to this file only if the fix
   changes observable behaviour from the last release.
2. If you're adding a feature, describe it in a new subsection above.
3. Keep the "What we don't diverge on" list accurate — it's the
   shortest description of upstream compatibility we have.

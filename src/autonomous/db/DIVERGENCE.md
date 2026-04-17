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
- `fields.py` GridFS get/read/delete, ImageField validate — narrowed
  per site.
- `document.py` DBRef key cast — catches `TypeError`, `ValueError`;
  re-raises as `TypeError`.
- `queryset/base.py`, `queryset/transform.py` — narrowed to
  `LookupError`, `AttributeError`.

Unexpected errors now propagate with original tracebacks. No observable
change for well-formed inputs; malformed inputs surface clearer
exceptions.

### Removed surface area (2026 cleanup, item 23)

The fork no longer ships the following upstream classes/helpers. They
were unreferenced by `autonomous.model.*`, uncovered by tests, and
carried compatibility baggage (deprecated Mongo commands, server-side
JS, geo indexing) that the project does not need:

**Fields** — `URLField`, `LongField`, `DecimalField`,
`ComplexDateTimeField`, `BinaryField`, `UUIDField`, `Decimal128Field`,
`SortedListField`, `MapField`, `GenericEmbeddedDocumentField`,
`GeoPointField`, `PointField`, `LineStringField`, `PolygonField`,
`MultiPointField`, `MultiLineStringField`, `MultiPolygonField`,
`SequenceField`, `CachedReferenceField`, `LazyReferenceField`,
`GenericLazyReferenceField`, `GeoJsonBaseField`.

**Base datastructure** — `LazyReference` (consumer-only proxy for the
lazy reference fields).

**Documents** — `MapReduceDocument` (MongoDB's mapReduce command is
deprecated; use the aggregation pipeline via
`AutoModel.objects.aggregate(...)`).

**QuerySet methods** — `QuerySet.map_reduce()`,
`QuerySet.item_frequencies()` and their helpers. Aggregation covers
the only production use.

**Query operators** — geo operators (`within_*`, `near`, `near_sphere`,
`geo_within*`, `geo_intersects`, `max_distance`, `min_distance`) and
the `_geo_indices()` classmethod / `_geo_index` field attribute. Index
specs are now built from `_unique_with_indexes()` alone.

### Deferred removals

Still in the tree but unused by first-party code; removal requires a
more invasive pass than this cleanup made room for. Do not add new
callers.

- `DynamicDocument` / `DynamicEmbeddedDocument` and the `_dynamic*`
  machinery in `base/document.py` (52 touchpoints on
  `_dynamic` / `_dynamic_fields` / `_dynamic_lock`).
- `EmbeddedDocument`, `EmbeddedDocumentField`,
  `EmbeddedDocumentListField`, `EmbeddedDocumentList` — threaded
  through the metaclass, `dereference.py`, and `base/document.py`.
- `DynamicField` stays as long as `DynamicDocument` does (its only
  consumer is the undeclared-field path inside `BaseDocument`).

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

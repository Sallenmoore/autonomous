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
- **Layer-1 signal payload (#250):** `BaseDocument.__init__` sends
  `pre_init` with an extra `created=` kwarg (the `_created` it already
  pops from `values`). The hook returns early for `created=False` —
  documents built from a stored SON (`_from_son` on the query path,
  `reload`, dereference, unpickle) — because `values` already IS the
  stored document; refetching it was an N+1 on every materialization.

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
the only production use. `QuerySet.snapshot()` (PyMongo 3+ ignores
the option entirely — the method was already a no-op for the whole
supported pymongo range; removed in #154 along with the dead
`_snapshot` flag in `__init__`, the `clone()` copy list, and the
`_cursor_args` warning re-fire).

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

### Change-tracking perf tuning (#145)

`BaseDocument._mark_as_changed`, `._get_changed_fields`, and `._delta`
preserve upstream's string-path representation of `_changed_fields` but
shed three quadratic-or-allocating patterns the upstream form carries:

- `_mark_as_changed`: the descendant-drop loop was `O(k·n)` (one
  `list.remove()` per match × O(n) per remove). The replacement rebuilds
  `_changed_fields` in a single list comprehension — O(n). The
  ancestor-prefix scan was rewritten as an early-return loop with no
  intermediate `else`-on-while branch but produces the same
  ancestor-already-covers-this-mark outcome.
- `_get_changed_fields` (and `_nestable_types_changed_fields`): the
  `changed_fields += [list comp]` pattern materialized a throwaway list
  per nesting level. Replaced with `changed_fields.extend(generator)`,
  same observable list contents, no temporary.
- `_delta`: the per-path `new_path = []` rebuild + final
  `".".join(new_path)` was wasted work in the common case where every
  part of the path is walked. Replaced with a `used` index that re-joins
  only when a `(ObjectId, DBRef)` break actually truncates.

A fuller refactor representing paths as tuples + a parallel set-keyed
parent-prefix cache is **explicitly deferred**. That shape would force
invariant maintenance across every `_changed_fields` mutation site
(`_clear_changed_fields`, `_from_son`, `BaseList`/`BaseDict` mutation
callbacks, dynamic-field paths) — high risk for a vendored ORM. The
behavior-preserving wins above capture the worst case (the
`_mark_as_changed` quadratic) without the invariant surface area.

### `BaseQuerySet.delete()` drops vector-index entries (#207)

`queryset/base.py`'s `delete()` now collects the matched pks
(`find(self._query, {"_id": 1})`) before its `delete_many` and hands
them to `db_sync.deindex_many()` afterwards, so the Redis hashes
`lore:<pk>` go away with the documents. Upstream mongoengine has no
such concept — this is the fork knowing about a sibling subsystem,
which is the part worth flagging.

Why it lives here rather than a layer above: `delete()` is the single
funnel all three delete paths converge on. `Document.delete()` routes
through `self._qs.filter(...).delete(_from_doc_delete=True)`,
`Model.objects(...).delete()` calls it directly, and a
`reverse_delete_rule=CASCADE` parent reaches its children only through
the `refs.delete(...)` recursion inside this same method. 0.3.171
hooked `AutoModel.delete()` instead and therefore covered exactly one
of the three (#204, #205); the other two leaked every child's
embedding, with the cascade case invisible at the call site.

Constraints the implementation holds to:

- **The bulk fast path is preserved.** No degrade to a per-document
  loop — the added cost is one `find` with an `{"_id": 1}` projection,
  and `delete_many` runs exactly as before.
- **`_from_doc_delete=True` skips the pre-scan.** That flag marks a
  single `Document.delete()`, which `AutoModel.delete()` has already
  de-indexed from the pk it holds; scanning would buy nothing and put
  an extra Mongo round-trip on the most common delete in the library.
  The two hooks cover disjoint paths — neither is redundant. CASCADE
  children of such a delete are still covered, because `refs.delete()`
  does not forward the flag.
- **Guarded calls from the delete funnel only, imported
  function-locally.** The fork's whole vector vocabulary lives in this
  module's two delete regimes (the single-pass path here and
  `_delete_in_chunks`, #215) plus the `vector_index` meta key their
  shared gate reads: `from autonomous.db import db_sync` plus
  `deindex_many(pks)`, with the import kept inside the functions.
  This is a boundary choice, **not** a circular-import workaround —
  `autonomous.db.__init__` imports `db_sync` before `queryset`, so it
  is fully initialized by the time this module loads. Verified by
  hoisting the import to module level and importing `autonomous`,
  `autonomous.db`, `autonomous.db.queryset.base` and
  `autonomous.model.automodel`: all clean. Re-run that check before
  citing circularity as the reason to leave it alone.
- **Fail-soft end to end.** `deindex_many` swallows and logs every
  failure, and so do the two Mongo steps around it — the pk pre-scan
  (the only part that runs *before* the delete, and therefore the only
  part that could stop one) and the confirmation re-check. Nothing in
  this cleanup can raise out of `delete()`. Failures cost vector
  entries, never the delete the caller asked for.
- **Only confirmed-deleted pks are de-indexed.** `find` and
  `delete_many` are two operations against the same filter, so a
  document mutated out of the filter in between survives the delete
  while sitting in the de-index batch. `_confirm_deleted` catches that:
  an acknowledged `deleted_count` equal to the scan size is taken as
  clean and costs no extra query (a heuristic on this path — see #214's
  test pinning the narrow hole), and only a mismatch (or `w=0`, where
  the count means nothing) pays a chunked existence re-check. On the
  chunked path the same fast path is exact, because its deletes are
  `$in`-restricted to the scanned pks. The asymmetry is deliberate — a
  pk that starts matching *after* the scan is deleted without being
  de-indexed, which leaks a hash a sweep can recover, whereas
  de-indexing a live document cannot be recovered at all.

#215 bounded and gated the cleanup, adding the rest of the fork's
vector-index surface:

- **The pk buffer is capped** (`_BULK_DEINDEX_BUFFER`, 100k) **for
  models with no reverse-delete rules.** A scan that overflows it hands
  the teardown to `_delete_in_chunks` — scan → `$in`-restricted
  `delete_many` → confirm → de-index per batch, refilled until the
  filter matches nothing. Three early-out paths (refill cap,
  refill-scan failure, chunk-delete failure) finish the delete with one
  `delete_many` on the caller's filter and leak the remainder's hashes;
  a de-index breaker also stops calling Redis for the rest of a
  teardown after two consecutive failing calls. Ruled models keep the
  #207 single-pass shape unbounded: their rule arms run once against
  the pre-teardown match set (chunking would bypass them on
  late-matching documents), and their `__in` subqueries materialize the
  full parent pk list anyway, so the bound would be fiction there.
- **The `vector_index` meta key.** `meta = {"vector_index": False}`
  (default `True`) skips the pre-scan on bulk deletes — gated over the
  class's whole subtree via `_any_vector_indexed`, since a base-class
  delete matches subclass documents — and skips the single-pk `DEL` in
  `AutoModel.delete()`. `AutoModel.save(sync=True)` refuses to index an
  opted-out model; #220 additionally gates `db_sync.request_indexing`
  at enqueue time (the document's stored `_cls` → exact registry hit,
  via a projected point-read in the calling process) and re-checks in
  the worker via the same `_cls` where that process can resolve it — enforcement is as strong as the resolving process's
  registry, and unresolvable cases default to indexing. Upstream
  mongoengine has no such meta key; it is autonomous-specific.

Still uncovered by design: raw pymongo deletes and dropped collections
never enter this method at all. Consumers who need those cleaned keep a
periodic sweep.

## What we don't diverge on

Scope note: this section describes the vendored `autonomous.db.*`
surface only. Consumer-facing behavior is also shaped by the
**Layer-2 customizations** below — read that section before claiming
"identical to upstream" in a PR.

- Field types and their **wire-level** semantics: `to_python`,
  `to_mongo`, `prepare_query_value` for `StringField` / `IntField` /
  `ReferenceField` / etc. behave as upstream documents. (User-facing
  reference behavior is materially different because `ReferenceAttr`
  in `autonomous.model.autoattr` wraps `GenericReferenceField` with
  several overrides — see Layer-2 below.)
- QuerySet semantics. `.objects.filter(...)`, `.order_by(...)`,
  `.limit(...)` behave as upstream. (The
  `AutoModel.search()` / `.where()` helpers add a `str → __icontains`
  translation on top — see Layer-2.)
- Signals. We use `blinker` the same way upstream does.
- Bson / pymongo version compatibility is tied to whatever pymongo
  version is pinned in `requirements.txt`.

## Layer-2 customizations (`autonomous.model`)

The vendored fork above is one layer of divergence. A **second
layer** lives in `src/autonomous/model/` — specifically
`automodel.py` and `autoattr.py` — and is responsible for most of
the behavior consumers experience as "the autonomous ORM," even
though strictly speaking it sits *on top of* the fork rather than
inside it.

This section documents that layer so a future reader (or anyone
weighing item #48 in [README.md](../../../README.md) — drop the
fork, depend on stock mongoengine) can see the full divergence
surface in one place.

### `AutoModel.load_model(name)` — string → class resolution
(`automodel.py:208`)

Resolves a string name (case-insensitive) to an `AutoModel`
subclass by walking `AutoModel.__subclasses__()` recursively.
Hits are memoized in a module-level `_LOAD_MODEL_CACHE`; misses
aren't cached because a subclass may be imported later in the
process. Test teardown calls `_invalidate_load_model_cache()`.

Upstream has nothing equivalent; the closest equivalent is the
private `_class_registry` dict keyed by mongoengine's
`_class_name` discriminator. `load_model` is project-API surface;
the upstream registry is internal plumbing.

Used by `get_model`, by `ReferenceAttr` dereferencing (via the
`_cls` discriminator stored alongside the ref), and by direct
consumer code that needs polymorphic class lookup.

### `AutoModel.auto_pre_init` — side-load on `Model(pk=x)`
(`automodel.py:116`)

When a caller constructs `Model(pk=x)` with no other kwargs (or
with sparse kwargs), this hook fetches the stored document and
fills in any field the caller didn't explicitly provide. Caller
kwargs always win. Already covered in §"`auto_pre_init`
side-load" above, but bears repeating here as part of the
"model finding" surface alongside `load_model` and `get_model`.

- **`created=False` skip + `from_json` carve-out (#250).** The hook
  returns early for documents built from a stored SON (the Layer-1
  `created=` payload above). `AutoModel.from_json` is the one
  from-store path that still side-loads — a `to_json` blob omits
  None-valued fields, so it can be partial — and it opts back in
  through the module-level `_FROM_JSON_SIDELOAD` ContextVar while
  still constructing with `created=False`, because `created=True`
  would switch on `BaseDocument`'s undefined-field check that
  `strict=False` models rely on tolerating (a stale key in a session
  blob). It also delegates the decode to the base `from_json`, so an
  omitted `json_options` keeps the `LEGACY_JSON_OPTIONS` default
  `to_json` writes with.
- **Sender-unfiltered receivers are guarded.** `_auto_pre_init` /
  `_auto_post_init` / `_auto_pre_save` / `_auto_post_save` are
  connected without a `sender=`, so plain vendored `Document` /
  `EmbeddedDocument` classes fire them too; each delegator `getattr`s
  the hook and skips senders that lack one instead of raising
  `AttributeError` out of `__init__` / `save()`.

### `AutoModel.model_name()` — name discriminator override
(`automodel.py:181`)

Returns `type(self).__name__` directly rather than mongoengine's
`_class_name` discriminator (which would yield the
parent-qualified form `RealModel.ChildModel` for subclasses of
non-abstract documents). Affects `__hash__` /`__eq__` /
ordering, all keyed off `(model_name, pk)`.

### `AutoModel.search()` / `.where()` — `str → __icontains` ergonomics
(`automodel.py:294, :330`)

String values in `**kwargs` are translated to `__icontains`
queries; non-string values become exact matches. Other
mongoengine operators (`__gt`, `__in`, `__regex`...) pass through
unchanged when written explicitly. Trades exact-match-by-default
for substring-search-by-default — the common case in
application code.

`search` materializes a list; `where` returns the underlying
QuerySet for chaining (`.order_by(...).limit(...).first()`,
`len()`, etc).

### `ReferenceAttr` — polymorphic references with deletion-safety
(`autoattr.py:80`)

The single most consequential Layer-2 customization. Inherits
from upstream `GenericReferenceField`, **not** `ReferenceField`.
Net effect: every reference field in the autonomous data model is
polymorphic (target class encoded in the stored `{_cls, _ref}`
payload), so model definitions don't import each other.
Combined with `load_model`, this is what lets `ReferenceAttr` on
model A dereference to model B without A importing B.

Two overrides on top of `GenericReferenceField`:

1. **`__get__` swallows `DoesNotExist`** → returns `None` instead
   of raising when the referent has been deleted. Upstream raises.
2. **`__set__` force-marks dirty.** `GenericReferenceField`'s
   `__get__` lazily replaces the raw `{_cls, _ref}` dict in
   `instance._data` with the dereferenced `Document` object by
   writing directly to `_data`, bypassing the descriptor path.
   The base-class `BaseField.__set__` equality check then
   compares the `Document` to itself (or to a stale dict) and may
   incorrectly decide nothing changed, leaving `_changed_fields`
   empty and the next `.save()` payload missing the `$set`.
   Calling `_mark_as_changed` here unconditionally fixes that.
   **This is a genuine bug-fix relative to upstream
   `GenericReferenceField` change detection** — worth keeping if
   we ever de-fork.

### `ListAttr` — self-healing list of references
(`autoattr.py:113`)

`__get__` overrides:

- Returns `[]` (and rewrites `_data`) if the stored value is
  somehow not a list. Defensive against schema migrations or
  out-of-band writes.
- When `self.field` is a `ReferenceAttr`, walks the list and
  prunes entries that evaluate falsy (deleted referents → `None`
  via `ReferenceAttr.__get__`) or raise `DoesNotExist`. Mutates
  in place.

`__set__` overrides:

- String input becomes a list: `"a;b;c"` / `"a,b,c"` →
  `["a", "b", "c"]`; single non-empty string → `[value]`;
  empty string → `[]`. Trades stricter typing for ergonomic
  CSV-style input common in form payloads.

The self-heal trade is deliberate: deleted referents silently
disappear from the list rather than surfacing a loud error.
Upstream returns the raw list, broken DBRefs and all.

### `DictAttr` — eager reference resolution
(`autoattr.py:160`)

`__get__` walks the dict values; anything with a `.fetch()`
method (typically a `GenericReferenceField`-stored lazy proxy
with a `pk`) gets dereferenced eagerly. Missing referents are
logged and the placeholder is left in place rather than pruned
(asymmetric with `ListAttr` — a dict's keys are usually
meaningful, so we preserve the key even when the value can't be
resolved).

- Returns the declared default (copied, never the shared literal)
  and logs at `WARNING` if the stored value is not a dict —
  a field that became a `DictAttr` in a schema change leaves
  pre-change rows holding the old shape, and the `.items()` walk
  used to raise out of the getter so the *read* failed before a
  consumer could normalize (#225).
- **`_data` is deliberately left untouched** on that path —
  asymmetric with `ListAttr`, which self-heals by rewriting the
  stored value. Rewriting here would destroy the bytes a consumer
  needs for its own lazy migration, and the next `save()` would
  persist the loss. The trade is the mirror of `ListAttr`'s:
  `DictAttr` prefers a recoverable read over a healed row.
- **Empty and `None` reads stay bound (#249).** `__get__` no longer
  does `or {}` — an empty `BaseDict` is falsy and the `or` swapped it
  for a detached plain dict, so in-place writes were never tracked. A
  stored `None` (`null=True` fields) is substituted with a bound empty
  dict written straight into `_data`, *not* assigned through the
  descriptor: the read marks nothing, so an unrelated `save()` never
  persists `{}` over a stored null — the same recoverable-read rule as
  the legacy-shape path above. An in-place write on it then marks
  `foo.k`; on a row whose stored value really is null Mongo rejects
  that `$set` (`OperationError`), so reassign the whole dict there.

### `IntAttr` — string coercion
(`autoattr.py:38`)

Strips commas from numeric strings (`"1,234"` → `1234`) and
extracts the first integer substring from non-numeric input
(`"$42.50"` → `42`). Falls through to upstream `IntField`
behavior for everything else. Same form-input ergonomics motive
as `ListAttr.__set__`.

## Known limitations

### Reference dereference is N+1 by default — use `select_related()`

Accessing a reference field triggers one DB round-trip per access.
`ReferenceField.__get__` / `GenericReferenceField.__get__`
(`fields.py`) call `_lazy_load_ref` → `ref_cls._get_db().dereference(dbref)`
the first time you touch the field (the result is then cached on the
instance). Iterating a result set and reading the reference on each
element is therefore the classic N+1: the query for the set, plus one
dereference per element.

```python
# 1 query for the posts, then N more — one per .author access:
for post in Post.where(published=True):
    print(post.author.name)
```

The fix already ships — `QuerySet.select_related(max_depth=N)`
(`queryset/base.py`) pre-fetches every reference across the whole result
set in **one `$in` / `in_bulk` query per collection** (via
`DeReference._fetch_objects`, `dereference.py`) and stitches the results
into each instance, so the later `.author` access is already cached:

```python
# 1 query for the posts + one batched fetch per referenced
# collection — N+1 collapses to a small constant:
for post in Post.where(published=True).select_related():
    print(post.author.name)
```

This batches both plain `DBRef` references and the generic
`{_cls, _ref}` references that `ReferenceAttr` (the Layer-2 reference
field — see above) stores, so it covers every reference in the
autonomous data model.

Notes:

- **`max_depth` controls nested-reference depth.** `select_related(1)`
  (the default) resolves the references directly on each result;
  `select_related(2)` also batches the references *those* referents hold,
  and so on.
- **It materializes the result set.** `select_related()` walks the whole
  queryset to collect refs, so it trades memory for round-trips — reach
  for it on a bounded set you were going to iterate anyway, not as a
  blanket default on unbounded queries.
- **Chain it off `where()`, not `all()` / `search()`.** The list helpers
  `AutoModel.all()` and `AutoModel.search()` return plain `list`s
  (`automodel.py`), which have no `.select_related()`. Use
  `AutoModel.where(...)`, which returns the chainable QuerySet, when you
  want to batch the dereference:
  `Model.where(active=True).select_related()`.

## How to make a change here

1. If you're fixing a bug, add a note to this file only if the fix
   changes observable behaviour from the last release.
2. If you're adding a feature, describe it in a new subsection above.
3. Keep the "What we don't diverge on" list accurate — it's the
   shortest description of upstream compatibility we have.
4. Layer-2 changes (`autonomous.model.automodel` /
   `autonomous.model.autoattr`) get documented in the §Layer-2
   section above. The fork's behavioral surface is the *union*
   of both layers; recording divergence in only one place means a
   future reader weighing item #48 (drop the fork) will
   under-estimate the cost.

# Design: `_select_related` flag on `AutoModel.all()` / `search()`

**Issue:** [Sallenmoore/autonomous#195](https://github.com/Sallenmoore/autonomous/issues/195) — Tier 2 follow-up to #153.
**Date:** 2026-06-22
**Status:** approved (brainstorming) — pending spec review.

## Context

Reference dereference is N+1 by default: `ReferenceField.__get__` / `GenericReferenceField.__get__` (`db/fields.py`) lazily fetch one referent per access. The batch fix already ships — `QuerySet.select_related(max_depth=N)` (`db/queryset/base.py:877`) pre-fetches every reference across a result set in one `$in`/`in_bulk` query per collection (via `DeReference._fetch_objects`), documented and regression-guarded in #153 Tier 1.

But that batch path is only reachable through `AutoModel.where(...)` (`model/automodel.py:330`), which returns the chainable QuerySet. The convenient list-returning entry points — `all()` (`:288`) and `search()` (`:293`) — do `return list(...)`, so a consumer iterating their results with an N+1 reference access has to rewrite to `where(...).select_related()`.

This change adds an opt-in, default-off flag so the batch path is reachable from `all()` / `search()` without that rewrite.

**Motivation:** proactive convenience (no specific measured hot loop). Guardrail: zero behavior change for existing callers; smallest useful surface (YAGNI).

## Scope

- **In:** `AutoModel.all()` and `AutoModel.search()`.
- **Out:** `find()` / `get()` / `random()` (single-doc fetches — no N+1 across results; different fan-out pattern, deferred), and `where()` (already chains `.select_related()` directly — adding a flag there is redundant).

## API

A new optional control parameter on both methods, named with a leading underscore to match the existing `_order_by` / `_limit` convention in `search()` (separates control args from field-filter `**kwargs`, and is collision-safe):

```python
def all(cls, _select_related: bool | int = False) -> list[Self]: ...
def search(cls, _order_by=None, _limit=None, _select_related: bool | int = False, **kwargs) -> list[Self]: ...
```

**Value semantics:**

| Value | Effect |
|---|---|
| `False` / `0` / `None` (default) | Off — **byte-identical** to current behavior; `select_related` is never called. |
| `True` | Batch-dereference at `max_depth=1`. |
| `int N` (N ≥ 1) | Batch-dereference at `max_depth=N`. |
| negative int (`< 1`, truthy) | `ValueError`. |
| non-bool, non-int (str / float / list / …) | `TypeError`. |

```python
Post.all()                                # off (default)
Post.all(_select_related=True)            # batch, depth 1
Post.search(author=a, _select_related=2)  # batch, depth 2
```

## Structure

One shared private helper holds the flag→depth translation + validation, so the logic lives in one place and is tested once (vs. inlining in both methods):

```python
def _maybe_select_related(qs, flag):
    """Apply ``.select_related(max_depth=...)`` to ``qs`` per the flag, else
    return it unchanged. ``flag``: falsy = off; ``True`` = depth 1; int N = depth N."""
    if not flag:                       # False / 0 / None -> off
        return qs
    if not isinstance(flag, int):      # bool & int pass; str/float/list rejected
        raise TypeError("_select_related must be a bool or int")
    if flag < 1:                       # negative (truthy) int
        raise ValueError("_select_related must be True or a positive int")
    return qs.select_related(max_depth=int(flag))   # True -> 1, N -> N
```

(Placement: module-level private function in `model/automodel.py`, or a private static method on `AutoModel` — implementer's choice; module-level keeps it out of the public class surface.)

### `all()`

```python
@classmethod
def all(cls, _select_related: bool | int = False) -> list[Self]:
    _ensure_connected()
    return list(_maybe_select_related(cls.objects(), _select_related))
```

### `search()` — apply `select_related` **last**

`select_related` must be applied **after** `_order_by` and `_limit`, so only the rows actually returned are batch-dereferenced (not the whole pre-limit query). `select_related` materializes the queryset by iterating it, which applies the slice/limit first.

```python
@classmethod
def search(cls, _order_by=None, _limit=None, _select_related=False, **kwargs):
    _ensure_connected()
    # ... existing str->__icontains translation into new_kwargs ...
    results = cls.objects(**new_kwargs)
    if _order_by:
        results = results.order_by(*_order_by)
    if _limit:
        results = results[_limit[0]:_limit[-1]] if isinstance(_limit, list) else results[:_limit]
    results = _maybe_select_related(results, _select_related)   # after filter/order/limit
    return list(results)
```

## Edge cases

- **Empty result set** → `DeReference` is a no-op (no extra query).
- **Model with no reference fields** → `_find_references` finds none → no extra query; harmless.
- **Default-off** → `_maybe_select_related` returns the queryset unchanged; `select_related` is never invoked, so existing call sites are untouched.
- **Generic / `ReferenceAttr` references** (the `{_cls,_ref}` wire shape real models use) are batched by the same `DeReference` machinery proven in #153 Tier 1.
- **Negative int** → `ValueError`; **wrong type** (str/float/list) → `TypeError`. Fail loud, not silent.

## Testing

Query-count tests, mirroring the Tier-1 guard (`tests/unit/test_unit_select_related_iter_2026-06-21.py`):

1. **Default-off is N+1 / unchanged** — `all()` / `search()` with no flag ⇒ N per-access `dereference` calls; `select_related` not invoked.
2. **`=True` batches** — one `in_bulk` per referenced collection + **zero** per-access derefs afterward.
3. **Depth maps through** — `_select_related=2` ⇒ `select_related(max_depth=2)`.
4. **`search()` ordering** — with `_limit`, only the limited rows are batch-fetched (assert the batch fetch sees the limited id set, and `select_related` is applied after the slice).
5. **Generic / `ReferenceAttr` path** covered.
6. **Invalid input** — negative int ⇒ `ValueError`; wrong type (str/float/list) ⇒ `TypeError`.

Two-perspective split (standard): dev writes ephemeral proofs in `tests/_dev_local/`; the test agent writes the independent committed tests in `tests/unit/`.

## Docs & release

- **MIGRATIONS.md:** additive "Added" entry — new optional `_select_related` param on `all()` / `search()`, defaulting off (no migration required for existing callers), cross-referencing the `where().select_related()` note in `db/DIVERGENCE.md`.
- **Pipeline:** real `src` change (new public capability) → flows `dev → test → main` and **does warrant a PyPI release** (unlike #190 / #153-Tier1) → next patch **0.3.169**, with explicit user authorization at the release gate.

## Out of scope (explicit non-goals)

- Changing `select_related` / `DeReference` themselves (they already work).
- Touching `find()` / `get()` / `random()` / `where()`.
- Tier 2's relative — any auto/eager-by-default dereference. This stays strictly opt-in.

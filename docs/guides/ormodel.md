# ORM — AutoModel and autoattr

``AutoModel`` is a MongoDB document with typed attributes, saved and
queried through a mongoengine-derived ORM.

## Define

```python
from autonomous.model.automodel import AutoModel
from autonomous.model.autoattr import (
    StringAttr, IntAttr, DateTimeAttr, ReferenceAttr, ListAttr,
)

class Author(AutoModel):
    name = StringAttr(default="")

class Post(AutoModel):
    title = StringAttr(default="")
    body = StringAttr(default="")
    views = IntAttr(default=0)
    published_at = DateTimeAttr()
    author = ReferenceAttr()        # → Author
    tags = ListAttr(StringAttr())
```

Every subclass gets:

- A collection named after the class (lowercased).
- A ``last_updated: datetime`` field automatically touched on each
  save (from ``auto_post_init``).
- The standard ORM methods below.

## CRUD

| Call | Result |
|------|--------|
| ``Post(title="x").save()`` | inserts, returns the pk |
| ``Post.get(pk)`` | load by pk; ``None`` on miss |
| ``Post.find(title="x")`` | first match; ``None`` on miss |
| ``Post.all()`` | list of every instance |
| ``Post.random()`` | one random instance; ``None`` on empty |
| ``Post.where(**kw)`` | chainable QuerySet |
| ``Post.search(**kw, _order_by=..., _limit=N)`` | list of matches |
| ``p.delete()`` | remove from collection |

## Querying — ``where`` versus ``search``

Both translate plain ``str`` values to case-insensitive substring
matches (``__icontains``). The difference is the return shape:

```python
Post.search(title="hello")                  # list[Post]
Post.where(title="hello").order_by("-views")  # QuerySet (chainable)
```

Use ``where`` when you need to chain ``.order_by``, ``.limit``,
``.skip``, ``.first``, ``len()``, slicing, aggregation, etc.

Raw mongoengine operators pass through unchanged:

```python
Post.where(views__gt=1000, tags__in=["python", "web"])
Post.where(title__regex=r"^hello")
```

## Relationships

``ReferenceAttr`` is a generic reference — it stores the target's
collection name + pk and eagerly dereferences on read. The referent
can be any ``AutoModel`` subclass.

```python
a = Author(name="Ada").save()
p = Post(title="hello", author=Author.get(a)).save()

Post.get(p).author.name      # "Ada"
Post.get(p).author = None    # unset (stored as None)
```

Deleted referents resolve to ``None`` instead of raising
``DoesNotExist``. A ``ListAttr(ReferenceAttr())`` prunes ``None``
entries on access, so you never iterate over dangling references.

## Inheritance

``AutoModel`` sets ``allow_inheritance = True``. Subclasses share a
collection tagged with ``_cls``:

```python
class Vehicle(AutoModel): ...
class Car(Vehicle): ...

Car(...).save()            # stored in the vehicle collection
Vehicle.all()              # returns every Vehicle + Car
Car.all()                  # returns only Car instances
```

## Signals

``AutoModel`` exposes four subclass-overridable hooks:

| Hook | Fires when |
|------|-----------|
| ``auto_pre_init`` | a ``Model(pk=...)`` is about to side-load the document |
| ``auto_post_init`` | after ``__init__`` completes (touches ``last_updated``) |
| ``auto_pre_save`` | before ``save()`` writes |
| ``auto_post_save`` | after ``save()`` writes |

Override on the subclass, not the base; the framework wires them to
mongoengine's ``signals`` for you.

```python
class Post(AutoModel):
    @classmethod
    def auto_pre_save(cls, sender, document, **kwargs):
        document.title = document.title.strip()
```

## ``Model(pk=x)`` side-load

``Post(pk="abc")`` is equivalent to ``Post.get("abc")`` — the pre-init
hook fetches the document and merges any field the caller didn't
supply. Useful for ``Post(pk=x, title="new")`` which becomes "load,
override one field, ready to save".

Opt out per class:

```python
class HotPath(AutoModel):
    auto_load_on_init = False
```

Failure modes are non-fatal: bad pk, missing doc, or DB outage all
skip the merge and continue constructing a fresh instance.

## Search vs where example

```python
# search — eager list, good for "just give me the rows"
for p in Post.search(title="hello", _order_by=("-views",), _limit=10):
    render(p)

# where — lazy QuerySet, good for composition
query = Post.where(author=current_author)
if archived:
    query = query.filter(archived_at__exists=True)
for p in query.order_by("-published_at").limit(20):
    render(p)
```

## Vector sync

Passing ``sync=True`` to ``save`` enqueues the document for
vector-embedding re-indexing via ``autonomous.db.db_sync``. The hook
is fire-and-forget; it assumes Redis is configured. See the
[tasks guide](tasks.md) for the queue side of that plumbing.

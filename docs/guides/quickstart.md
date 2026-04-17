# Quickstart

Autonomous is a library, not a project template. This guide takes you
from ``pip install`` to "my first document".

## Install

Autonomous is published as ``autonomous-app``:

```bash
pip install autonomous-app              # ORM + auth core
pip install 'autonomous-app[all]'       # + tasks, images, ai, github
```

Feature extras are pay-as-you-go — see the table at the bottom of this
page.

## Configure MongoDB

Autonomous reads MongoDB settings from the environment on first use.
Set them once (``.env`` works; ``python-dotenv`` is already a
dependency):

```env
DB_HOST=localhost
DB_PORT=27017
DB_USERNAME=app
DB_PASSWORD=secret
DB_DB=myapp
```

No explicit ``connect()`` is required — the first ORM call will open
the connection. If you want earlier failure on bad credentials:

```python
import autonomous
autonomous.init()                                     # env-driven
autonomous.init(host="mongo.prod", db="app",
                username="u", password="p")          # overrides
```

## Define a model

```python
from autonomous.model.automodel import AutoModel
from autonomous.model.autoattr import StringAttr, IntAttr, DateTimeAttr

class Post(AutoModel):
    title = StringAttr(default="")
    views = IntAttr(default=0)
    published_at = DateTimeAttr()
```

Any ``AutoModel`` subclass automatically gets a MongoDB collection
named after the class.

## Save and look up

```python
p = Post(title="hello", views=12)
p.save()                 # writes; returns the new pk

Post.get(p.pk)           # fetch by primary key; returns None on miss
Post.all()               # every Post
Post.find(title="hello") # first match
Post.where(title="hello").order_by("-views")[:10]  # chainable QuerySet
```

``Post(pk=x)`` is an ergonomic shorthand for "load then mutate":

```python
p = Post(pk="abc123", title="new title")  # loads, then overrides title
p.save()
```

## Attribute types (``autoattr``)

| Attr | Stores | Notes |
|------|--------|-------|
| ``StringAttr`` | ``str`` | |
| ``IntAttr`` | ``int`` | Best-effort coerces ``"1,234"`` → ``1234``. |
| ``FloatAttr`` | ``float`` | |
| ``BoolAttr`` | ``bool`` | |
| ``DateTimeAttr`` | ``datetime`` | |
| ``EmailAttr`` | ``str`` | Validated on save. |
| ``ListAttr`` | ``list`` | Self-heals; splits on ``;``/``,`` for string input. |
| ``DictAttr`` | ``dict`` | Dereferences ``ReferenceAttr`` values eagerly. |
| ``ReferenceAttr`` | reference | Returns ``None`` on deleted referent. |
| ``FileAttr`` | GridFS file | |
| ``ImageAttr`` | GridFS image | |
| ``EnumAttr`` | ``Enum`` | |

## Feature extras

```bash
pip install 'autonomous-app[tasks]'    # + redis, rq
pip install 'autonomous-app[images]'   # + pillow
pip install 'autonomous-app[ai]'       # + google-genai, pydub
pip install 'autonomous-app[github]'   # + PyGithub, pygit2
pip install 'autonomous-app[server]'   # + gunicorn
pip install 'autonomous-app[all]'      # everything above
```

## Next

- [ORM guide](ormodel.md) — relationships, inheritance, signals.
- [Auth guide](auth.md) — wiring OAuth into Flask or FastAPI.
- [Tasks guide](tasks.md) — priority queues + background workers.

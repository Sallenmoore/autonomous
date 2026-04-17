# Storage — LocalStorage and ImageStorage

Autonomous ships two storage classes for filesystem-backed assets:

- ``LocalStorage`` — arbitrary files (documents, JSON, zips, etc.).
- ``ImageStorage`` — images with resized / cached variants served via
  URL, backed by Pillow.

Both classes:

- Read their root path from an environment variable (overridable via
  ``path=``).
- Reject path-traversal input (``..``, absolute paths) at every
  entrypoint.
- Resolve URLs against ``APP_BASE_URL`` when set; fall back to
  site-relative ``/<root>/...`` otherwise.

## LocalStorage

```python
from autonomous.storage import LocalStorage

store = LocalStorage()                        # $STORAGE_PATH or "static"
# store = LocalStorage(path="/var/data")

ref = store.save(b"hello world", folder="notes", asset_id="readme.txt")
# {"asset_id": "notes/readme.txt", "url": "/static/notes/readme.txt"}

store.get("notes/readme.txt")                # bytes
store.get_path("notes/readme.txt")           # absolute filesystem path
store.search(folder="notes")                 # ["notes/readme.txt", ...]
store.move("notes/readme.txt", "archive/readme.txt")
store.remove("archive/readme.txt")
```

``save`` returns an ``AssetRef`` (a dict of ``asset_id`` + ``url``)
you persist in your own model.

### Traversal safety

```python
store.save(b"", folder="../../etc")            # ValueError on write
store.get("../../etc/passwd")                  # None on read
store.search(folder="../somewhere")            # [] on read
```

Read-side methods swallow ``ValueError`` and return benign defaults.
Write-side methods raise so the caller sees bad input.

## ImageStorage

Built on ``LocalStorage``. Adds transparent thumbnails / resized
variants:

```python
from autonomous.storage import ImageStorage

images = ImageStorage()                        # $STORAGE_IMAGE_PATH or "images"

ref = images.save(binary, folder="avatars", asset_id="alice.png")
images.get_url(ref["asset_id"])                # original URL
images.get_url(ref["asset_id"], size=128)      # 128-px longest-side variant
images.get_url(ref["asset_id"], size="orig")   # explicit original
images.get_url(ref["asset_id"], full_url=True) # absolute URL if APP_BASE_URL set

images.rotate(ref["asset_id"], 90)
images.flip(ref["asset_id"], horizontal=True)
images.clear_cached(ref["asset_id"])           # drop variants manually
```

Variants are written to a cache folder adjacent to the original.
After ``rotate`` / ``flip``, the original's mtime is touched; the
next ``get_url(size=N)`` detects the mtime skew and regenerates the
variant automatically.

### Atomic writes + failure modes

Each variant goes through a sibling ``.tmp`` + ``os.replace``. A
half-written file can't be served if two requests race. A resize
error logs and returns ``None`` — it does **not** delete the source.

### Caching behaviour

Variants are keyed by ``(asset_id, size)``. The variant mtime is
pinned to the original's so the freshness comparison stays stable
across sub-second clock ticks. ``clear_cached`` is still available
for manual invalidation; routine edits don't need it.

## Env configuration

| Var | Class | Fallback |
|-----|-------|----------|
| ``STORAGE_PATH`` | ``LocalStorage`` | ``static`` |
| ``STORAGE_IMAGE_PATH`` | ``ImageStorage`` | ``<STORAGE_PATH>/images`` |
| ``APP_BASE_URL`` | both | site-relative ``/path`` |

## Install

``ImageStorage`` needs Pillow, which is in the ``images`` extra:

```bash
pip install 'autonomous-app[images]'
```

``LocalStorage`` has no optional deps — it's in the core install.

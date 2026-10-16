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
- Resolve URLs against ``APP_BASE_URL`` when set. When it is unset,
  ``LocalStorage`` falls back to ``http://localhost`` and
  ``ImageStorage`` to a site-relative ``/<root>/...``.

## LocalStorage

```python
from autonomous.storage.localstorage import LocalStorage

store = LocalStorage()                        # $STORAGE_PATH or "static"
# store = LocalStorage(path="/var/data")

ref = store.save(b"hello world", "txt", folder="notes")
# {"asset_id": "notes/<uuid>.txt",
#  "url": "http://localhost/static/notes/<uuid>.txt"}

store.get(ref["asset_id"])                   # AssetRef, or None if missing
store.geturl(ref["asset_id"])                # public URL
store.get_path(ref["asset_id"])              # absolute filesystem path
store.search(folder="notes")                 # [AssetRef, ...]
moved = store.move(ref["asset_id"], "archive")  # new AssetRef (new uuid), or False
store.remove(moved["asset_id"])              # True / False
```

``save`` names the file ``<uuid>.<file_type>`` and returns an
``AssetRef`` (a dict of ``asset_id`` + ``url``) you persist in your own
model.

### Traversal safety

```python
store.save(b"", "txt", folder="../../etc")     # ValueError on write
store.get("../../etc/passwd")                  # None on read
store.search(folder="../somewhere")            # [] on read
```

Read-side methods swallow ``ValueError`` and return benign defaults.
Write-side methods raise so the caller sees bad input.

## ImageStorage

A separate class (it shares ``LocalStorage``'s path sanitizer). Every
upload is converted to WebP and stored as ``<asset dir>/orig.webp``,
with resized variants cached beside it:

```python
from autonomous.storage.imagestorage import ImageStorage

images = ImageStorage()        # $STORAGE_IMAGE_PATH or "<STORAGE_PATH>/images"

asset_id = images.save(binary, folder="avatars")  # returns the asset_id (str)
images.get_url(asset_id)                   # original URL
images.get_url(asset_id, size=128)         # 128-px longest-side variant
images.get_url(asset_id, size="small")     # named size: thumbnail/small/medium/large
images.get_url(asset_id, full_url=True)    # absolute URL if APP_BASE_URL set

images.rotate(asset_id, 90)                # degrees; default -90
images.flip(asset_id, flipx=True, flipy=False)
images.clear_cached(asset_id)              # drop variants manually
```

Variants are written as ``<size>.webp`` next to ``orig.webp``.
``rotate`` / ``flip`` rewrite the original and clear the cached
variants; independently, ``get_url(size=N)`` regenerates any variant
older than the original, so a replaced original never serves stale
variants.

### Atomic writes + failure modes

Each variant goes through a sibling ``.tmp`` + ``os.replace``. A
half-written file can't be served if two requests race. A resize
error logs and ``get_url`` returns ``None`` — it does **not** delete
the source.

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
| ``APP_BASE_URL`` | both | ``LocalStorage``: ``http://localhost``; ``ImageStorage``: site-relative ``/path`` |

## Install

``ImageStorage`` needs Pillow, which is in the ``images`` extra:

```bash
pip install 'autonomous-app[images]'
```

``LocalStorage`` has no optional deps — it's in the core install.

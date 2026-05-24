"""
Content-addressed cache for image generations.

Image generations are deterministic-ish for a given (prompt, style,
aspect_ratio, files, provider) tuple — repeat requests during iteration
or A/B testing pay the same upstream bill twice. This module hashes the
canonical inputs and stores the resulting bytes on disk so subsequent
identical calls short-circuit before any API call is made.

Opt-in: the cache is disabled unless ``AUTONOMOUS_IMAGE_CACHE_DIR`` is
set to an existing writable directory. That keeps tests and one-off
runs from accumulating cache files in surprising locations, and puts
GC policy on the operator.

The cache is bytes-on-disk only — one ``<sha256>.webp`` per entry. No
DB, no manifest, no LRU eviction; if disk is finite, the operator
prunes by hand or via a cron.
"""

import hashlib
import json
import os
from pathlib import Path

from autonomous import log


def _files_digest(files) -> str:
    """Deterministically hash the ``files`` argument used by image gen.

    Accepts the same shapes ImageAgent passes through to providers:
    ``None`` (no input image), ``bytes`` (single image), or
    ``{name: bytes_or_fileobj}`` (one or more named inputs).
    """
    if not files:
        return ""
    if isinstance(files, dict):
        items = sorted(files.items(), key=lambda kv: kv[0])
    elif isinstance(files, (bytes, bytearray)):
        items = [("_bytes", files)]
    else:
        items = [("_default", files)]

    parts = []
    for name, f in items:
        if isinstance(f, (bytes, bytearray)):
            data = bytes(f)
        elif hasattr(f, "read"):
            # File-like: capture content without mutating the caller's
            # cursor permanently. seek-then-read-then-restore-via-finally
            # so a read() exception still leaves the cursor where the
            # caller had it. Non-seekable streams (no .seek) are drained
            # by f.read() — the caller has to materialize bytes itself
            # if it wants the cache to round-trip on them.
            pos = f.tell() if hasattr(f, "tell") else None
            if hasattr(f, "seek"):
                f.seek(0)
            try:
                data = f.read()
            finally:
                if pos is not None and hasattr(f, "seek"):
                    f.seek(pos)
        else:
            data = str(f).encode("utf-8")
        parts.append(f"{name}:{hashlib.sha256(data).hexdigest()}")
    return "|".join(parts)


def cache_key(
    *,
    prompt: str,
    negative_prompt: str = "",
    style=None,
    aspect_ratio: str = "",
    files=None,
    provider: str = "",
    method: str = "generate",
) -> str:
    """Compute a stable sha256 cache key from the image-gen arguments.

    Keyword-only so future fields can be added at the call site without
    silently shifting positional meaning.

    Side effect on ``files``: file-like values are read to compute the
    digest. Seekable streams have their cursor restored to its prior
    position; non-seekable streams are *drained* and the caller is
    responsible for materializing bytes if a round-trip is needed.
    """
    canonical = {
        "prompt": prompt or "",
        "negative_prompt": negative_prompt or "",
        "style": json.dumps(style, sort_keys=True, default=str) if style else "",
        "aspect_ratio": aspect_ratio or "",
        "files_digest": _files_digest(files),
        "provider": provider or "",
        "method": method or "generate",
    }
    payload = json.dumps(canonical, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cache_root() -> Path | None:
    """Resolve the cache directory, or ``None`` if caching is disabled.

    Disabled iff ``AUTONOMOUS_IMAGE_CACHE_DIR`` is unset, empty, or
    points to a non-directory. Auto-creation is deliberately not done:
    if the operator hasn't created the directory, we treat the
    misconfiguration as "no cache" rather than dumping bytes into an
    unexpected location.
    """
    root = os.environ.get("AUTONOMOUS_IMAGE_CACHE_DIR", "").strip()
    if not root:
        return None
    p = Path(root)
    if not p.is_dir():
        return None
    return p


def get(key: str) -> bytes | None:
    """Return cached bytes for ``key`` or ``None`` on miss/disabled.

    ``FileNotFoundError`` (the legitimate miss) is silent. Other
    ``OSError`` subclasses (``PermissionError``, ``IsADirectoryError``,
    disk-corruption ``EIO``) are logged loudly because they masquerade
    as cache miss and silently trigger upstream re-billing — exactly
    the failure mode the cache exists to prevent.
    """
    root = _cache_root()
    if root is None or not key:
        return None
    try:
        return (root / f"{key}.webp").read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log(
            f"Image cache read failed for {key[:12]}: {type(exc).__name__}: {exc}",
            _print=True,
        )
        return None


def put(key: str, data: bytes) -> None:
    """Persist ``data`` under ``key``. Atomic via tmp+rename. Silent on
    disabled cache or write failure — the cache is best-effort, the
    upstream call already succeeded by the time put() is called."""
    root = _cache_root()
    if root is None or not key or not data:
        return
    tmp = root / f"{key}.webp.tmp"
    final = root / f"{key}.webp"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, final)
    except OSError as exc:
        log(f"Image cache write failed for {key[:12]}: {exc}", _print=False)

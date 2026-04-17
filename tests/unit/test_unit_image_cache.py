"""Item 10: cache-correctness for ImageStorage variant generation.

The previous implementation:

- generated a variant on first request and wrote it to disk (good)
- never invalidated the cached variant when the original changed (bad)
- ``self.remove(asset_id)`` on resize failure — wiped the whole asset
  for a single bad call (bad)
- ``full_url=True`` only worked in the post-resize branch — calls that
  hit the cached path returned a relative URL even when ``APP_BASE_URL``
  was set (bad)

These tests pin the new behaviour: lazy variant generation, mtime-based
invalidation, atomic write via ``os.replace``, ``full_url`` honored
everywhere, and failure leaves the original alone.
"""

import io
import os
import time
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "store"))
    monkeypatch.delenv("STORAGE_IMAGE_PATH", raising=False)
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    return tmp_path


@pytest.fixture
def storage(storage_root):
    from autonomous.storage.imagestorage import ImageStorage

    return ImageStorage()


def _make_png(color="red", size=(40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


class TestVariantCaching:
    def test_first_request_generates_variant(self, storage):
        asset_id = storage.save(_make_png(), folder="cache-test")
        url = storage.get_url(asset_id, size="small")
        assert url
        variant_path = Path(storage.get_path(asset_id)) / "small.webp"
        assert variant_path.is_file()

    def test_second_request_does_not_regenerate(self, storage):
        asset_id = storage.save(_make_png(), folder="cache-test")
        storage.get_url(asset_id, size="small")
        variant_path = Path(storage.get_path(asset_id)) / "small.webp"
        first_mtime = variant_path.stat().st_mtime
        time.sleep(0.05)
        storage.get_url(asset_id, size="small")
        assert variant_path.stat().st_mtime == first_mtime

    def test_variant_invalidated_when_original_newer(self, storage):
        asset_id = storage.save(_make_png(), folder="cache-test")
        storage.get_url(asset_id, size="medium")
        variant_path = Path(storage.get_path(asset_id)) / "medium.webp"
        original_path = Path(storage.get_path(asset_id)) / "orig.webp"
        first_inode = variant_path.stat().st_ino

        # Make the original strictly newer than the variant.
        future = variant_path.stat().st_mtime + 5
        os.utime(original_path, (future, future))

        storage.get_url(asset_id, size="medium")
        # Inode changes via os.replace; that's how we know it was rewritten.
        assert variant_path.stat().st_ino != first_inode
        # And the regenerated variant's mtime is now pinned to the original.
        assert variant_path.stat().st_mtime == future


class TestFullUrl:
    def test_full_url_honored_for_orig(self, storage, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "https://cdn.example.com")
        asset_id = storage.save(_make_png(), folder="cdn-test")
        url = storage.get_url(asset_id, size="orig", full_url=True)
        assert url.startswith("https://cdn.example.com/")
        assert url.endswith("/orig.webp")

    def test_full_url_honored_for_cached_variant(self, storage, monkeypatch):
        asset_id = storage.save(_make_png(), folder="cdn-test")
        # Prime the cache without APP_BASE_URL.
        storage.get_url(asset_id, size="small")
        # Now flip APP_BASE_URL and ask again — should still build a full URL.
        monkeypatch.setenv("APP_BASE_URL", "https://cdn.example.com")
        url = storage.get_url(asset_id, size="small", full_url=True)
        assert url.startswith("https://cdn.example.com/")

    def test_full_url_falls_back_to_relative_when_unset(self, storage):
        asset_id = storage.save(_make_png(), folder="cdn-test")
        url = storage.get_url(asset_id, size="orig", full_url=True)
        assert url.startswith("/")


class TestFailureLeavesOriginalAlone:
    def test_resize_failure_does_not_destroy_original(self, storage, monkeypatch):
        asset_id = storage.save(_make_png(), folder="failure-test")
        original_path = Path(storage.get_path(asset_id)) / "orig.webp"
        assert original_path.is_file()

        # Force the resizer to return None (simulating a corrupted source
        # or PIL failure).
        monkeypatch.setattr(storage, "_resize_image", lambda *a, **k: None)

        result = storage.get_url(asset_id, size="small")
        assert result is None
        # Critically: the original is still there.
        assert original_path.is_file()


class TestEdgeCases:
    def test_falsy_asset_id_returns_empty(self, storage):
        assert storage.get_url("") == ""
        assert storage.get_url(None) == ""

    def test_missing_original_returns_none(self, storage):
        assert storage.get_url("does-not-exist") is None

    def test_traversal_attempt_returns_none(self, storage):
        # Item 7 makes get_path raise ValueError; get_url swallows.
        assert storage.get_url("../etc/passwd") is None

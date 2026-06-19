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


class TestRotateInteractionWithVariantCache:
    """Issue #150: pin the rotate() ↔ variant-invalidation handshake.

    rotate() clears variants then rewrites orig.webp. A subsequent
    get_url(size=...) MUST regenerate from the rotated original, not
    serve the stale pre-rotation cached variant. A refactor of either
    rotate()'s clear-then-save ordering or _regenerate_variant's
    mtime-pin could silently serve a stale variant — visually wrong,
    no exception, no signal.
    """

    def test_rotate_invalidates_cached_variant(self, storage):
        # Non-square so rotation visibly swaps aspect ratio.
        asset_id = storage.save(_make_png(size=(40, 60)), folder="rotate-test")

        # Prime the variant.
        storage.get_url(asset_id, size="thumbnail")
        variant_path = Path(storage.get_path(asset_id)) / "thumbnail.webp"
        assert variant_path.is_file()
        with Image.open(variant_path) as variant:
            pre_w, pre_h = variant.size
        assert pre_w < pre_h, "fixture sanity: pre-rotation should be portrait"

        storage.rotate(asset_id, amount=90)

        # rotate() called clear_cached() — variant file is gone.
        assert not variant_path.is_file()

        # Re-request the same variant — must regenerate from the
        # rotated original. The file-gone-then-file-back sequence
        # proves a write happened; inode comparison is unreliable
        # on tmpfs-style filesystems that reuse freed inodes.
        url = storage.get_url(asset_id, size="thumbnail")
        assert url
        assert variant_path.is_file()
        # Orientation swapped — proves the variant was rebuilt from the
        # ROTATED original, not served from a pre-rotation cache. This
        # is the load-bearing check: a regenerate-from-stale-cache bug
        # would still produce a portrait variant.
        with Image.open(variant_path) as variant:
            post_w, post_h = variant.size
        assert post_w > post_h

    def test_flip_invalidates_cached_variant(self, storage):
        """flip() takes the same clear-then-save path as rotate() — pin
        it too so a "DRY-up" of the two methods can't regress only one.

        Uses a non-symmetric image (half blue / half red) so a flipx
        produces visibly different pixels at a known coordinate; without
        this asymmetry the test could pass on a regeneration-skipped
        bug since a uniformly-colored variant looks identical pre/post
        flip."""
        # Build a 40x40 with the left half blue and the right half red,
        # so flipx swaps the visible pixel at x=5 from blue→red.
        buf = io.BytesIO()
        img = Image.new("RGB", (40, 40), color="red")
        for x in range(20):
            for y in range(40):
                img.putpixel((x, y), (0, 0, 255))  # blue left half
        img.save(buf, format="PNG")
        asset_id = storage.save(buf.getvalue(), folder="flip-test")

        storage.get_url(asset_id, size="small")
        variant_path = Path(storage.get_path(asset_id)) / "small.webp"
        assert variant_path.is_file()
        with Image.open(variant_path) as variant:
            # In the source-sized "small" variant, x=5 should still be
            # in the left (blue) half pre-flip.
            pre_pixel_left = variant.convert("RGB").getpixel((5, 20))
        # Allow some webp/Pillow color drift — just assert "more blue than red".
        assert pre_pixel_left[2] > pre_pixel_left[0], (
            f"fixture sanity: pre-flip left half should be predominantly "
            f"blue; got {pre_pixel_left!r}"
        )

        storage.flip(asset_id, flipx=True, flipy=False)

        # Cache cleared by flip().
        assert not variant_path.is_file()

        storage.get_url(asset_id, size="small")
        assert variant_path.is_file()
        with Image.open(variant_path) as variant:
            # Post-flipx: x=5 is now on the side that USED to be at
            # x=35 (the red side). Pixel should be predominantly red.
            post_pixel_left = variant.convert("RGB").getpixel((5, 20))
        assert post_pixel_left[0] > post_pixel_left[2], (
            f"post-flip left half should be predominantly red (flipped "
            f"in from the right); got {post_pixel_left!r} — likely a "
            f"stale cached variant served"
        )

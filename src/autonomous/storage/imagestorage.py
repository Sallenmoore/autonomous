import glob
import io
import os
import shutil
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from autonomous import log
from autonomous.storage.localstorage import (
    _default_storage_path,
    _sanitize_relative,
)


def _default_image_path() -> str:
    """Resolve the default image root: ``STORAGE_IMAGE_PATH`` env, else
    ``<STORAGE_PATH>/images``."""
    override = os.getenv("STORAGE_IMAGE_PATH")
    if override:
        return override
    return f"{_default_storage_path()}/images"


class ImageStorage:
    _sizes = {"thumbnail": 100, "small": 300, "medium": 600, "large": 1000}

    def __init__(self, path: str | None = None):
        self.base_path = path if path is not None else _default_image_path()
        self._base_resolved = Path(self.base_path).resolve()

    def _safe_join(self, *parts: str) -> str:
        cleaned = [_sanitize_relative(p) for p in parts if p]
        joined = Path(self.base_path, *cleaned).resolve()
        try:
            joined.relative_to(self._base_resolved)
        except ValueError as exc:
            raise ValueError(
                f"Resolved path {joined} escapes image storage root "
                f"{self._base_resolved}"
            ) from exc
        return str(joined)

    def scan_storage(self, path=None):
        for root, dirs, files in os.walk(path or self.base_path):
            for file in files:
                if file == "orig.webp":
                    yield os.path.join(root, file)

    @classmethod
    def _get_key(cls, folder="", pkey=None):
        if folder and not folder.endswith("/"):
            folder = f"{folder}/"
        folder = f"{folder.replace('/', '.')}{pkey or uuid.uuid4()}"
        return f"{folder}"

    def _resize_image(self, asset_id, max_size=1024):
        # log("Resizing image", asset_id, max_size)
        file_path = f"{self.get_path(asset_id)}/orig.webp"
        try:
            with Image.open(file_path) as img:
                resized_img = img.copy()
                max_size = self._sizes.get(max_size) or int(max_size)
                resized_img.thumbnail((max_size, max_size))
                img_byte_arr = io.BytesIO()
                resized_img.save(img_byte_arr, format="WEBP")
                return img_byte_arr.getvalue()
        except UnidentifiedImageError as e:
            log(f"Error resizing image: {e}")
            return None

    def _convert_image(self, raw, crop=False):
        with Image.open(io.BytesIO(raw)) as img:
            width, height = img.size
            if crop and width != height:
                max_size = min(width, height)
                img.crop(
                    (
                        (width - max_size) / 2,
                        (height - max_size) / 2,
                        (width + max_size) / 2,
                        (height + max_size) / 2,
                    )
                )
            img = img.copy()
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="WEBP")
            return img_byte_arr.getvalue()

    def save(self, file, folder="", crop=False):
        asset_id = self._get_key(folder)
        os.makedirs(self.get_path(asset_id), exist_ok=True)
        file_path = f"{self.get_path(asset_id)}/orig.webp"
        with open(file_path, "wb") as asset:
            file = self._convert_image(file, crop=crop)
            asset.write(file)
        return asset_id

    def get_url(self, asset_id, size="orig", full_url=False):
        """Return a URL for ``asset_id`` at the requested ``size``.

        Variants are cached on disk under the asset directory as
        ``<size>.webp``. The cache is invalidated automatically when the
        original (``orig.webp``) is newer than the cached variant — so
        callers that rotate / flip / replace the original don't have to
        manually clear stale variants.

        Returns ``""`` for a falsy ``asset_id``, ``None`` if the original
        is missing, otherwise the URL string.
        """
        if not asset_id:
            return ""
        try:
            original_dir = self.get_path(asset_id)
        except ValueError:
            return None
        original_file = os.path.join(original_dir, "orig.webp")
        if not os.path.isfile(original_file):
            log(f"Original image not found: {original_dir}")
            return None

        variant_file = os.path.join(original_dir, f"{size}.webp")
        if size != "orig":
            if not self._variant_is_fresh(variant_file, original_file):
                if not self._regenerate_variant(asset_id, size, variant_file):
                    return None
        else:
            variant_file = original_file

        return self._build_url(variant_file, full_url=full_url)

    @staticmethod
    def _variant_is_fresh(variant_file: str, original_file: str) -> bool:
        """A cached variant is fresh iff it exists and is newer than orig."""
        if not os.path.isfile(variant_file):
            return False
        try:
            return os.path.getmtime(variant_file) >= os.path.getmtime(original_file)
        except OSError:
            return False

    def _regenerate_variant(
        self, asset_id: str, size, variant_file: str
    ) -> bool:
        """Resize the original and write it to ``variant_file`` atomically.

        Returns True on success, False if the resize failed (in which case
        we leave the original alone — the previous code wiped the whole
        asset on a single resize failure).

        The new variant's mtime is set to match the original's, so the
        freshness check (``variant.mtime >= orig.mtime``) keeps passing
        across multiple regenerations within the same second and across
        clocks that don't tick during the write.
        """
        result = self._resize_image(asset_id, size)
        if not result:
            log(f"Error resizing image: asset_id={asset_id} size={size}")
            return False
        # Atomic-ish: write to a sibling, then rename. Avoids a half-written
        # file being served if two requests race.
        tmp = f"{variant_file}.tmp"
        with open(tmp, "wb") as fh:
            fh.write(result)
        os.replace(tmp, variant_file)
        # Pin the variant's mtime to the original's so the freshness
        # comparison reads as "fresh" until the original is touched again.
        original = os.path.join(os.path.dirname(variant_file), "orig.webp")
        try:
            orig_mtime = os.path.getmtime(original)
            os.utime(variant_file, (orig_mtime, orig_mtime))
        except OSError:
            pass
        return True

    def _build_url(self, file_path: str, full_url: bool = False) -> str:
        """Render a URL from a filesystem path, honoring ``APP_BASE_URL``."""
        path = f"/{file_path}"
        if not full_url:
            return path
        base = os.environ.get("APP_BASE_URL", "").rstrip("/")
        return f"{base}{path}" if base else path

    def get_path(self, asset_id):
        if not asset_id:
            return self.base_path
        return self._safe_join(asset_id)

    def search(self, folder="", **kwargs):
        imgs = []
        try:
            search_path = self._safe_join(folder) if folder else self.base_path
        except ValueError:
            return imgs
        if not os.path.isdir(search_path):
            return imgs
        for f in os.listdir(search_path):
            img_key = self._get_key(folder, pkey=f)
            imgs.append(img_key)
        return imgs

    def remove(self, asset_id):
        if not asset_id:
            return False
        file_path = self.get_path(asset_id)
        if os.path.isdir(file_path):
            print(f"Removing {file_path}")
            # return shutil.rmtree(file_path, ignore_errors=True)
        return False

    def clear_cached(self, asset_id):
        file_path = self.get_path(asset_id)
        if os.path.isdir(file_path):
            for file in glob.glob(os.path.join(file_path, "*")):
                if os.path.basename(file) != "orig.webp":
                    os.remove(file)
        return False

    def rotate(self, asset_id, amount=-90):
        file_path = self.get_path(asset_id)
        log(asset_id)
        with Image.open(f"{file_path}/orig.webp") as img:
            # Rotate the image 90 degrees
            rotated_img = img.rotate(amount, expand=True)
            # Save the rotated image
            log(img, rotated_img)
            # img = img.copy()
            # img_byte_arr = io.BytesIO()
            # img.save(img_byte_arr, )
            self.clear_cached(asset_id)
            rotated_img.save(f"{file_path}/orig.webp", format="WEBP")
        return False

    def flip(self, asset_id, flipx=True, flipy=True):
        file_path = self.get_path(asset_id)
        with Image.open(f"{file_path}/orig.webp") as img:
            if flipx:
                rotated_img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if flipy:
                rotated_img = img.transpose(Image.FLIP_TOP_BOTTOM)
            # Save the rotated image
            rotated_img.save(f"{file_path}/orig.webp", format="WEBP")
            self.clear_cached(asset_id)
        return False

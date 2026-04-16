import os
import shutil
import uuid
from pathlib import Path


def _default_storage_path() -> str:
    """Resolve the default storage root: ``STORAGE_PATH`` env, else ``static``."""
    return os.getenv("STORAGE_PATH", "static")


def _sanitize_relative(part: str) -> str:
    """Strip a user-supplied path fragment to a safe relative form.

    Rejects absolute paths and any fragment whose normalized form contains
    a ``..`` segment. ``"a/../b"`` (which normalizes to ``"b"``) is fine;
    ``"../b"`` and ``"a/../../b"`` are not. Returns an empty string for
    ``None`` / ``""`` / ``"."`` so callers can treat it as "no folder".
    """
    if part is None or part == "":
        return ""
    if os.path.isabs(part):
        raise ValueError(f"Absolute paths are not allowed: {part!r}")
    normalized = os.path.normpath(part.replace("\\", "/"))
    if normalized in (".", ""):
        return ""
    segments = normalized.split(os.sep)
    if ".." in segments:
        raise ValueError(f"Path traversal is not allowed: {part!r}")
    return normalized


class LocalStorage:
    def __init__(self, path: str | None = None):
        self.base_path = path if path is not None else _default_storage_path()
        # Resolved absolute base used to validate every derived path.
        self._base_resolved = Path(self.base_path).resolve()
        base_url = os.getenv("APP_BASE_URL", "")
        self.base_url = (
            f"{base_url.rstrip('/')}/{self.base_path}"
            if base_url
            else f"/{self.base_path}"
        )

    def _safe_join(self, *parts: str) -> str:
        """Join ``parts`` under ``base_path`` and verify the result stays in.

        Each part is sanitized; the final resolved path must be the base or
        a descendant of it. Raises :class:`ValueError` on any escape.
        """
        cleaned = [_sanitize_relative(p) for p in parts if p]
        joined = Path(self.base_path, *cleaned).resolve()
        try:
            joined.relative_to(self._base_resolved)
        except ValueError as exc:
            raise ValueError(
                f"Resolved path {joined} escapes storage root "
                f"{self._base_resolved}"
            ) from exc
        return str(joined)

    def get(self, asset_id):
        try:
            path = self._safe_join(asset_id)
        except ValueError:
            return None
        if os.path.isfile(path):
            return {"asset_id": asset_id, "url": self.geturl(asset_id)}
        return None

    def _get_key(self, folder="", ext="", filename=None):
        folder = _sanitize_relative(folder)
        if filename:
            filename = _sanitize_relative(filename)
            return f"{folder}{'/' if folder else ''}{filename}"
        return f"{folder}{'/' if folder else ''}{uuid.uuid4()}.{ext.strip('.')}"

    def geturl(self, asset_id):
        return f"{self.base_url}/{asset_id}"

    def get_path(self, asset_id):
        return self._safe_join(asset_id)

    def search(self, **kwargs):
        files = []
        if folder := kwargs.get("folder"):
            try:
                folder_path = self._safe_join(folder)
            except ValueError:
                return files
            if not os.path.isdir(folder_path):
                return files
            for f in os.listdir(folder_path):
                full = os.path.join(folder_path, f)
                if os.path.isfile(full):
                    asset_id = self._get_key(folder=folder, filename=f)
                    files.append(self.get(asset_id))
        elif asset_id := kwargs.get("asset_id"):
            try:
                path = self._safe_join(asset_id)
            except ValueError:
                return files
            if os.path.isfile(path):
                files.append(self.get(asset_id))
        return files

    def save(self, file, file_type, folder=""):
        folder = _sanitize_relative(folder)
        target_dir = self._safe_join(folder) if folder else self.base_path
        os.makedirs(target_dir, exist_ok=True)
        asset_id = self._get_key(folder, file_type)

        with open(self._safe_join(asset_id), "wb") as asset:
            asset.write(file)
        return {"asset_id": asset_id, "url": self.geturl(asset_id)}

    def move(self, asset_id, folder):
        folder = _sanitize_relative(folder)
        new_asset_id = self._get_key(folder, asset_id.split(".")[-1])
        old_path = self._safe_join(asset_id)
        new_path = self._safe_join(new_asset_id)
        if os.path.isfile(old_path):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.move(old_path, new_path)
            return self.get(new_asset_id)
        return False

    def remove(self, asset_id):
        try:
            file_path = self._safe_join(asset_id)
        except ValueError:
            return False
        if os.path.isfile(file_path):
            os.remove(file_path)
            return True
        return False

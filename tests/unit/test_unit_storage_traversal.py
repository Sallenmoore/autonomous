"""Item 7: path-traversal hardening for LocalStorage and ImageStorage.

Storage classes accept user-supplied ``folder`` and ``asset_id`` values.
Without sanitization an attacker (or a buggy upstream) can read or write
outside the configured storage root via ``..`` segments or absolute
paths. These tests pin the new behavior:

- absolute paths are rejected
- ``..`` segments that escape the root are rejected
- benign normalization (``a/../b`` -> ``b``) still works
- attempts to escape return None / [] / False rather than crashing the
  whole request
"""

import os

import pytest


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "store"))
    monkeypatch.setenv("APP_BASE_URL", "")
    monkeypatch.delenv("STORAGE_IMAGE_PATH", raising=False)
    return tmp_path


class TestSanitizeRelative:
    def test_empty_and_none_return_empty(self):
        from autonomous.storage.localstorage import _sanitize_relative

        assert _sanitize_relative("") == ""
        assert _sanitize_relative(None) == ""
        assert _sanitize_relative(".") == ""

    def test_normal_relative_path_passes(self):
        from autonomous.storage.localstorage import _sanitize_relative

        assert _sanitize_relative("foo") == "foo"
        assert _sanitize_relative("foo/bar") == "foo/bar"

    def test_double_dot_normalizes_when_safe(self):
        """``foo/../bar`` collapses to ``bar`` — that's fine."""
        from autonomous.storage.localstorage import _sanitize_relative

        assert _sanitize_relative("foo/../bar") == "bar"

    def test_leading_double_dot_rejected(self):
        from autonomous.storage.localstorage import _sanitize_relative

        with pytest.raises(ValueError):
            _sanitize_relative("../etc")
        with pytest.raises(ValueError):
            _sanitize_relative("../../etc/passwd")

    def test_absolute_paths_rejected(self):
        from autonomous.storage.localstorage import _sanitize_relative

        with pytest.raises(ValueError):
            _sanitize_relative("/etc/passwd")

    def test_three_dots_is_not_traversal(self):
        """``...etc`` is just a weird folder name, not ``..`` traversal."""
        from autonomous.storage.localstorage import _sanitize_relative

        assert _sanitize_relative("...etc") == "...etc"


class TestLocalStorageTraversal:
    def test_save_into_safe_folder(self, storage_root):
        from autonomous.storage.localstorage import LocalStorage

        s = LocalStorage()
        result = s.save(b"data", file_type="bin", folder="ok")
        assert (
            os.path.commonpath([result["url"], "/"])
            and "../" not in result["url"]
        )

    def test_save_with_traversal_folder_rejected(self, storage_root):
        from autonomous.storage.localstorage import LocalStorage

        s = LocalStorage()
        with pytest.raises(ValueError):
            s.save(b"data", file_type="bin", folder="../etc")

    def test_save_with_absolute_folder_rejected(self, storage_root):
        from autonomous.storage.localstorage import LocalStorage

        s = LocalStorage()
        with pytest.raises(ValueError):
            s.save(b"data", file_type="bin", folder="/tmp")

    def test_get_with_traversal_returns_none(self, storage_root):
        from autonomous.storage.localstorage import LocalStorage

        s = LocalStorage()
        assert s.get("../../etc/passwd") is None

    def test_remove_with_traversal_returns_false(self, storage_root, tmp_path):
        from autonomous.storage.localstorage import LocalStorage

        # Create a file outside the storage root that should NOT be
        # reachable via traversal.
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"do not delete")

        s = LocalStorage()
        assert s.remove("../outside.txt") is False
        assert outside.exists()

    def test_search_with_traversal_returns_empty(self, storage_root):
        from autonomous.storage.localstorage import LocalStorage

        s = LocalStorage()
        assert s.search(folder="../") == []

    def test_move_with_traversal_rejected(self, storage_root):
        from autonomous.storage.localstorage import LocalStorage

        s = LocalStorage()
        s.save(b"data", file_type="bin", folder="ok")
        # Find the asset_id we just saved so we can attempt to move it out.
        results = s.search(folder="ok")
        asset_id = results[0]["asset_id"]
        with pytest.raises(ValueError):
            s.move(asset_id, "../outside")


class TestImageStorageTraversal:
    def test_search_with_traversal_returns_empty(self, storage_root):
        from autonomous.storage.imagestorage import ImageStorage

        s = ImageStorage()
        assert s.search(folder="../../") == []

    def test_get_path_rejects_traversal(self, storage_root):
        from autonomous.storage.imagestorage import ImageStorage

        s = ImageStorage()
        with pytest.raises(ValueError):
            s.get_path("../../etc")

    def test_get_path_normal_asset_id(self, storage_root):
        from autonomous.storage.imagestorage import ImageStorage

        s = ImageStorage()
        # ImageStorage._get_key replaces "/" with "." so asset_ids are
        # always single-segment; the safe-join pass-through must accept
        # the dotted form unchanged.
        path = s.get_path("ok.subfolder.abc123")
        assert path.endswith("ok.subfolder.abc123")

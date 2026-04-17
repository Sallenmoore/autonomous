"""Tests for the new pluggable storage path defaults (item 2)."""

import pytest


@pytest.fixture(autouse=True)
def _clear_storage_env(monkeypatch):
    """Ensure STORAGE_* env vars don't leak between tests."""
    for key in ("STORAGE_PATH", "STORAGE_IMAGE_PATH", "APP_BASE_URL"):
        monkeypatch.delenv(key, raising=False)


class TestLocalStorageDefaults:
    def test_default_path_is_static(self):
        from autonomous.storage.localstorage import LocalStorage

        storage = LocalStorage()
        assert storage.base_path == "static"

    def test_storage_path_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("STORAGE_PATH", "/var/app/assets")
        from autonomous.storage.localstorage import LocalStorage

        storage = LocalStorage()
        assert storage.base_path == "/var/app/assets"

    def test_explicit_path_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("STORAGE_PATH", "/from-env")
        from autonomous.storage.localstorage import LocalStorage

        storage = LocalStorage(path="/explicit")
        assert storage.base_path == "/explicit"

    def test_base_url_without_app_base_url(self):
        from autonomous.storage.localstorage import LocalStorage

        storage = LocalStorage(path="uploads")
        # No APP_BASE_URL set; the old code produced "None/uploads". Now it
        # falls back to a site-relative path.
        assert storage.base_url == "/uploads"

    def test_base_url_with_app_base_url(self, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "https://cdn.example.com")
        from autonomous.storage.localstorage import LocalStorage

        storage = LocalStorage(path="uploads")
        assert storage.base_url == "https://cdn.example.com/uploads"

    def test_base_url_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "https://cdn.example.com/")
        from autonomous.storage.localstorage import LocalStorage

        storage = LocalStorage(path="uploads")
        assert storage.base_url == "https://cdn.example.com/uploads"


class TestImageStorageDefaults:
    def test_default_path_nests_under_storage_path(self):
        from autonomous.storage.imagestorage import ImageStorage

        storage = ImageStorage()
        assert storage.base_path == "static/images"

    def test_storage_image_path_env_overrides_everything(self, monkeypatch):
        monkeypatch.setenv("STORAGE_PATH", "/var/app/assets")
        monkeypatch.setenv("STORAGE_IMAGE_PATH", "/var/cdn/img")
        from autonomous.storage.imagestorage import ImageStorage

        storage = ImageStorage()
        assert storage.base_path == "/var/cdn/img"

    def test_falls_through_storage_path_for_images(self, monkeypatch):
        monkeypatch.setenv("STORAGE_PATH", "/var/app/assets")
        from autonomous.storage.imagestorage import ImageStorage

        storage = ImageStorage()
        assert storage.base_path == "/var/app/assets/images"

    def test_explicit_path_wins(self, monkeypatch):
        monkeypatch.setenv("STORAGE_IMAGE_PATH", "/from-env")
        from autonomous.storage.imagestorage import ImageStorage

        storage = ImageStorage(path="/explicit")
        assert storage.base_path == "/explicit"

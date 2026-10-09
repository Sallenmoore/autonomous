"""Independent test-agent coverage for PR #285 (batch 2), one section per
issue: #271 ImageStorage, #272 google discovery fetch, #274 logger lock,
#275/#278 local_model transient retry + summarize raising, #276 markdown
depth cap, #279 env-driven image sizes + TASK_JOB_TIMEOUT, #280 gemini
file_refs without files.list(), #282 removal regression guard.

Written from the PR diff alone.
"""

import importlib
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from PIL import Image

import autonomous
from autonomous.ai.models import local_model
from autonomous.config import Settings, settings
from autonomous.storage.imagestorage import ImageStorage
from autonomous.utils.markdown import MarkdownParser

REPO = Path(__file__).resolve().parents[2]
R, G, B, W = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


# ---------------------------------------------------------------------------
# #271 ImageStorage flip / rotate / clear_cached
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    """ImageStorage with one 40x40 asset in solid quadrants:
    TL red, TR green, BL blue, BR white. Quadrants (not single pixels)
    because the source re-saves lossy WEBP."""
    s = ImageStorage(path=str(tmp_path))
    asset = tmp_path / "a1"
    asset.mkdir()
    img = Image.new("RGB", (40, 40))
    for (x, y), colour in zip([(0, 0), (20, 0), (0, 20), (20, 20)], [R, G, B, W]):
        img.paste(colour, (x, y, x + 20, y + 20))
    img.save(asset / "orig.webp", format="WEBP", lossless=True)
    (asset / "thumbnail.webp").write_bytes(b"cached")
    return s, asset


def _pixels(asset):
    """Quadrant colours (TL, TR, BL, BR), snapped to the nearest of R/G/B/W."""
    with Image.open(asset / "orig.webp") as img:
        rgb = img.convert("RGB")
        samples = [rgb.getpixel(p) for p in [(10, 10), (30, 10), (10, 30), (30, 30)]]
    return [
        min((R, G, B, W), key=lambda c: sum((a - b) ** 2 for a, b in zip(c, px)))
        for px in samples
    ]


def test_flip_both_chains_transposes(store):
    s, asset = store
    assert s.flip("a1") is True
    # Both flips == 180 degree turn. Pre-fix only the Y flip survived.
    assert _pixels(asset) == [W, B, G, R]
    assert not (asset / "thumbnail.webp").exists()


def test_flip_x_only_and_y_only(store):
    s, asset = store
    assert s.flip("a1", flipx=True, flipy=False) is True
    assert _pixels(asset) == [G, R, W, B]
    assert s.flip("a1", flipx=False, flipy=True) is True
    assert _pixels(asset) == [W, B, G, R]


def test_flip_neither_is_noop(store):
    s, asset = store
    before = (asset / "orig.webp").read_bytes()
    assert s.flip("a1", flipx=False, flipy=False) is True
    assert (asset / "orig.webp").read_bytes() == before
    assert (asset / "thumbnail.webp").exists()


def test_rotate_returns_true(store):
    s, asset = store
    assert s.rotate("a1") is True
    assert not (asset / "thumbnail.webp").exists()


def test_clear_cached_return_value(store):
    s, asset = store
    assert s.clear_cached("a1") is True
    assert sorted(p.name for p in asset.iterdir()) == ["orig.webp"]
    assert s.clear_cached("missing") is False


# ---------------------------------------------------------------------------
# #272 google discovery fetch
# ---------------------------------------------------------------------------


def _google_with(monkeypatch, resp):
    from autonomous.auth import google

    calls = []

    def fake_get(url, **kw):
        calls.append((url, kw))
        return resp

    monkeypatch.setenv("GOOGLE_DISCOVERY_URL", "https://disc.example/cfg")
    monkeypatch.setattr(google.requests, "get", fake_get)
    return google, calls


def test_google_discovery_fetch_has_timeout(monkeypatch):
    resp = MagicMock()
    resp.json.return_value = {
        "authorization_endpoint": "https://a.example", "token_endpoint": "https://t.example",
    }
    google, calls = _google_with(monkeypatch, resp)
    google.GoogleAuth()
    assert calls == [("https://disc.example/cfg", {"timeout": 30})]
    resp.raise_for_status.assert_called_once()


def test_google_discovery_error_status_raises(monkeypatch):
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.HTTPError("503")
    google, _ = _google_with(monkeypatch, resp)
    with pytest.raises(requests.HTTPError):
        google.GoogleAuth()
    resp.json.assert_not_called()


# ---------------------------------------------------------------------------
# #274 logger lock
# ---------------------------------------------------------------------------


def test_logger_file_writes_happen_under_lock(monkeypatch, tmp_path):
    from autonomous import logger as logger_mod

    lg = logger_mod.Logger("batch2-test")
    lg.enable_file_logging(True)
    lg._log_dir = str(tmp_path)
    held = []
    real_open = open

    def spy_open(path, mode="r", *a, **kw):
        held.append(lg._file_lock.locked())
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr(logger_mod, "open", spy_open, raising=False)
    lg("hello")
    assert held == [True, True]
    assert not lg._file_lock.locked()


def test_logger_lock_released_when_disk_fails(monkeypatch, tmp_path):
    from autonomous import logger as logger_mod

    lg = logger_mod.Logger("batch2-test-fail")
    lg.enable_file_logging(True)
    lg._log_dir = str(tmp_path)

    def broken_open(*a, **kw):
        raise OSError("disk gone")

    monkeypatch.setattr(logger_mod, "open", broken_open, raising=False)
    lg("x")  # swallowed
    assert not lg._file_lock.locked()


# ---------------------------------------------------------------------------
# #278 / #275 local_model transient retry
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_model(monkeypatch):
    monkeypatch.setattr(
        local_model, "AutoTasks",
        lambda: SimpleNamespace(get_current_task=lambda: None),
    )
    return SimpleNamespace(
        _retry_sleep=0, _text_model="m", _ollama_url="http://o", _audio_url="http://a",
        _context_limit=10, _text_timeout=1, _summary_timeout=1, _media_timeout=1,
        API_KEY_ENV="ORIN_VOICE_TOKEN",
    )


def _ok(content):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"message": {"content": content}}
    return resp


def _posts(monkeypatch, *items):
    queue = list(items)
    calls = []

    def fake_post(*a, **kw):
        calls.append(a)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(local_model._HTTP, "post", fake_post)
    return calls


def test_retry_transient_retries_only_transport_errors():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise requests.Timeout("t")
        return "ok"

    assert local_model._retry_transient(SimpleNamespace(_retry_sleep=0), flaky) == "ok"
    assert len(attempts) == 3

    attempts.clear()

    def http_err():
        attempts.append(1)
        raise requests.HTTPError("500")

    with pytest.raises(requests.HTTPError):
        local_model._retry_transient(SimpleNamespace(_retry_sleep=0), http_err)
    assert len(attempts) == 1


def test_retry_transient_gives_up_after_three():
    attempts = []

    def down():
        attempts.append(1)
        raise requests.ConnectionError("down")

    with pytest.raises(requests.ConnectionError):
        local_model._retry_transient(SimpleNamespace(_retry_sleep=0), down)
    assert len(attempts) == 3


def test_generate_text_recovers_from_transient_errors(monkeypatch, stub_model):
    calls = _posts(monkeypatch, requests.ConnectionError("x"), requests.Timeout("y"), _ok("hi"))
    out = local_model.LocalAIModel.generate_text(stub_model, "msg")
    assert out == "hi"
    assert len(calls) == 3


def test_generate_audio_retries_transient(monkeypatch, stub_model):
    calls = _posts(monkeypatch, *[requests.ConnectionError("x")] * 3)
    try:
        local_model.LocalAIModel.generate_audio(stub_model, "say")
    except requests.ConnectionError:
        pass  # surfacing or swallowing the final error is the method's call
    assert len(calls) == 3


def test_summarize_text_retries_then_succeeds(monkeypatch, stub_model):
    calls = _posts(monkeypatch, requests.Timeout("t"), _ok("sum"))
    assert local_model.LocalAIModel.summarize_text(stub_model, "short") == "sum\n"
    assert len(calls) == 2


def test_summarize_text_raises_on_failed_chunk(monkeypatch, stub_model):
    # 3 chunks (40-char chunks of 100 chars); the 2nd chunk errors with a
    # 500. Pre-fix this returned the 1st chunk's summary as if complete.
    bad = MagicMock(status_code=500)
    bad.raise_for_status.side_effect = requests.HTTPError("500")
    calls = _posts(monkeypatch, _ok("one"), bad)
    with pytest.raises(requests.HTTPError):
        local_model.LocalAIModel.summarize_text(stub_model, "x" * 100)
    assert len(calls) == 2  # HTTPError not retried, no 3rd chunk


def test_summarize_text_raises_when_transient_exhausted(monkeypatch, stub_model):
    _posts(monkeypatch, _ok("one"), *[requests.ConnectionError("down")] * 3)
    with pytest.raises(requests.ConnectionError):
        local_model.LocalAIModel.summarize_text(stub_model, "x" * 100)


# ---------------------------------------------------------------------------
# #276 markdown depth cap
# ---------------------------------------------------------------------------


def _nested(depth):
    rec = {"leaf": "v"}
    for i in range(depth - 1):
        rec = {"k": rec} if i % 2 else {"k": [rec]}
    return rec


def test_markdown_max_depth_constant():
    assert MarkdownParser.MAX_DEPTH == 128


def test_markdown_within_cap_parses():
    rec = {"k": {"k": {"leaf": "v"}}}
    assert "v" in MarkdownParser(rec).parse()
    assert "v" in MarkdownParser(_nested(80)).parse()  # ~120 containers


@pytest.mark.parametrize("depth", [200, 5000])
def test_markdown_past_cap_raises_value_error(depth):
    with pytest.raises(ValueError, match="128"):
        MarkdownParser(_nested(depth)).parse()


def test_markdown_flat_siblings_do_not_accumulate_depth():
    # 500 sibling sub-dicts at one level: depth must unwind per sibling.
    rec = {f"k{i}": {"x": i} for i in range(500)}
    parser = MarkdownParser(rec)
    parser.parse()
    assert parser.depth == 0


# ---------------------------------------------------------------------------
# #279 env-driven image sizes + TASK_JOB_TIMEOUT
# ---------------------------------------------------------------------------


def test_image_and_timeout_settings_defaults(monkeypatch):
    for env in ("IMAGE_THUMBNAIL_SIZE", "IMAGE_SMALL_SIZE", "IMAGE_MEDIUM_SIZE",
                "IMAGE_LARGE_SIZE", "IMAGE_MAX_SIZE", "TASK_JOB_TIMEOUT"):
        monkeypatch.delenv(env, raising=False)
    s = Settings()
    assert (s.image_thumbnail_size, s.image_small_size, s.image_medium_size,
            s.image_large_size, s.image_max_size, s.task_job_timeout) == (
        100, 300, 600, 1000, 1024, 7200)


def test_image_and_timeout_settings_read_env(monkeypatch):
    monkeypatch.setenv("IMAGE_SMALL_SIZE", "320")
    monkeypatch.setenv("IMAGE_MAX_SIZE", "2048")
    monkeypatch.setenv("TASK_JOB_TIMEOUT", "60")
    s = Settings()
    assert (s.image_small_size, s.image_max_size, s.task_job_timeout) == (320, 2048, 60)


def test_imagestorage_sizes_come_from_settings():
    assert ImageStorage._sizes == {
        "thumbnail": settings.image_thumbnail_size,
        "small": settings.image_small_size,
        "medium": settings.image_medium_size,
        "large": settings.image_large_size,
    }


def test_autotasks_default_job_timeout_from_settings(monkeypatch):
    from autonomous.taskrunner import autotasks

    queue = MagicMock()
    tasks = autotasks.AutoTasks.__new__(autotasks.AutoTasks)
    monkeypatch.setattr(tasks, "_get_queue", lambda name: queue, raising=False)
    monkeypatch.setattr(autotasks.settings, "task_job_timeout", 42)
    tasks.task(print, "a")
    assert queue.enqueue.call_args.kwargs["job_timeout"] == 42
    tasks.task(print, "a", _task_job_timeout=5)
    assert queue.enqueue.call_args.kwargs["job_timeout"] == 5


# ---------------------------------------------------------------------------
# #280 gemini file_refs without files.list()
# ---------------------------------------------------------------------------


def test_gemini_add_files_skips_files_list():
    from autonomous.ai.models import gemini

    class _Stub:
        MAX_FILES = 10

        def save(self):
            pass

    stub = _Stub()
    stub.client = MagicMock()
    handles = []

    def upload(**kw):
        h = MagicMock()
        h.name = f"files/h{len(handles)}"
        h.state.name = "ACTIVE"
        handles.append(h)
        return h

    stub.client.files.upload.side_effect = upload
    stub.client.files.list.side_effect = AssertionError("files.list() must not be called")

    files = [{"name": "a.json", "file": b"{}"}, {"name": "b.json", "file": b"{}"}]
    gemini.GeminiAIModel._add_files(stub, files)
    stub.client.files.list.assert_not_called()
    assert stub.file_refs == ["files/h0", "files/h1"]


# ---------------------------------------------------------------------------
# #282 removal regression guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", [
    "autonomous.cli",
    "autonomous.apis.version_control.GHRepo",
    "autonomous.apis.version_control.GHOrganization",
    "autonomous.apis.version_control.GHCallbacks",
    "autonomous.apis.version_control.GHVersionControl",
])
def test_removed_modules_not_importable(module):
    with pytest.raises(ImportError):
        importlib.import_module(module)


def test_no_version_control_or_cli_sources_shipped():
    pkg = Path(autonomous.__file__).parent
    assert not (pkg / "cli.py").exists()
    # rglob on a missing dir yields nothing; stale __pycache__ is fine.
    assert list((pkg / "apis").rglob("*.py")) == []


def test_pyproject_has_no_github_extra():
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    extras = data["tool"]["setuptools"]["dynamic"]["optional-dependencies"]
    assert "github" not in extras
    assert "requirements-github.txt" not in extras["all"]["file"]
    assert not (REPO / "requirements-github.txt").exists()


def test_github_settings_fields_removed():
    for attr in ("github_pat", "github_username", "github_org"):
        assert not hasattr(settings, attr)


def test_github_oauth_still_present():
    # #282 removed the PyGithub wrappers, NOT GitHub OAuth.
    from autonomous.auth.github import GithubAuth  # noqa: F401

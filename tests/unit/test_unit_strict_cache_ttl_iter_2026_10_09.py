"""Independent test-agent coverage for PR #270 / #268 — the strict-mode
negative cache in ``openai_compat.generate_json`` is time-boxed.

Before the PR, one strict-unavailable signal (a capability 4xx or an
unparseable strict 200) pinned the ``(model, base_url)`` key into loose
mode for the whole worker lifetime. Now both paths record a deadline
``_STRICT_MODE_CACHE_TTL_SECONDS`` (15 min) out; a lookup past the
deadline drops the key and strict mode is re-probed.

The clock is ``openai_compat.time.monotonic``; tests swap the module's
``time`` for a controllable fake so no real sleeping happens.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from autonomous.ai.models import openai_compat

KEY = ("test-model", "https://test.example/v1")
STRICT_4XX_BODY = "Invalid response_format type 'json_schema'"


@pytest.fixture(autouse=True)
def _silence_autotasks():
    with patch("autonomous.ai.models.openai_compat.AutoTasks") as mock_tasks:
        mock_tasks.return_value.get_current_task.return_value = None
        yield


@pytest.fixture
def clock(monkeypatch):
    """A settable monotonic clock, seen only by openai_compat."""
    now = [1000.0]
    monkeypatch.setattr(
        openai_compat, "time", SimpleNamespace(monotonic=lambda: now[0])
    )
    openai_compat._reset_unsupported_cache()
    yield now
    openai_compat._reset_unsupported_cache()


def _client(responses):
    """OpenAIClient with ``_chat`` serving ``responses`` in order and
    recording each call's response_format type."""
    client = openai_compat.OpenAIClient.__new__(openai_compat.OpenAIClient)
    for attr, val in {
        "_data": {}, "_dynamic_fields": {}, "_changed_fields": [],
        "_initialised": False, "_created": True,
        "_json_model": KEY[0], "_base_url": KEY[1], "instructions": "x",
    }.items():
        object.__setattr__(client, attr, val)
    client.formats = []
    queue = list(responses)

    def fake_chat(model, system, user, response_format=None, **_):
        client.formats.append(response_format["type"])
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client._chat = fake_chat
    return client


def _strict_4xx():
    resp = MagicMock(status_code=400, text=STRICT_4XX_BODY)
    return requests.HTTPError(STRICT_4XX_BODY, response=resp)


def _call(client):
    return client.generate_json("p", json_schema={"type": "object"})


# Each tuple: the responses for a call that trips the negative cache.
TRIP_PATHS = {
    "4xx_first": [_strict_4xx(), '{"ok": 1}'],
    "parse_failure_200": ["not json {{", '{"ok": 1}'],
}


def test_ttl_constant_is_fifteen_minutes():
    assert openai_compat._STRICT_MODE_CACHE_TTL_SECONDS == 15 * 60


@pytest.mark.parametrize("path", TRIP_PATHS)
def test_trip_records_deadline_one_ttl_out(clock, path):
    assert _call(_client(TRIP_PATHS[path])) == {"ok": 1}
    assert KEY in openai_compat._UNSUPPORTED_STRICT_MODE
    assert openai_compat._STRICT_MODE_CACHE_EXPIRY[KEY] == (
        clock[0] + openai_compat._STRICT_MODE_CACHE_TTL_SECONDS
    )


@pytest.mark.parametrize("path", TRIP_PATHS)
def test_within_ttl_skips_strict(clock, path):
    _call(_client(TRIP_PATHS[path]))
    clock[0] += openai_compat._STRICT_MODE_CACHE_TTL_SECONDS - 1

    client = _client(['{"ok": 2}'])
    assert _call(client) == {"ok": 2}
    assert client.formats == ["json_object"]
    assert KEY in openai_compat._UNSUPPORTED_STRICT_MODE


@pytest.mark.parametrize("path", TRIP_PATHS)
def test_after_ttl_reprobes_strict_and_drops_key(clock, path):
    _call(_client(TRIP_PATHS[path]))
    # Boundary: expiry is ">= deadline", so exactly TTL later re-probes.
    clock[0] += openai_compat._STRICT_MODE_CACHE_TTL_SECONDS

    client = _client(['{"ok": 3}'])
    assert _call(client) == {"ok": 3}
    assert client.formats == ["json_schema"]
    assert KEY not in openai_compat._UNSUPPORTED_STRICT_MODE
    assert KEY not in openai_compat._STRICT_MODE_CACHE_EXPIRY


def test_reprobe_failure_recaches_with_fresh_deadline(clock):
    _call(_client(TRIP_PATHS["4xx_first"]))
    clock[0] += 10_000

    client = _client([_strict_4xx(), '{"ok": 4}'])
    assert _call(client) == {"ok": 4}
    assert client.formats == ["json_schema", "json_object"]
    assert openai_compat._STRICT_MODE_CACHE_EXPIRY[KEY] == (
        clock[0] + openai_compat._STRICT_MODE_CACHE_TTL_SECONDS
    )


def test_key_without_deadline_never_expires(clock):
    # Tests/operators seed the set directly; such keys stay put.
    openai_compat._UNSUPPORTED_STRICT_MODE.add(KEY)
    clock[0] += 10 * openai_compat._STRICT_MODE_CACHE_TTL_SECONDS

    client = _client(['{"ok": 5}'])
    _call(client)
    assert client.formats == ["json_object"]
    assert KEY in openai_compat._UNSUPPORTED_STRICT_MODE


def test_expiry_is_per_key(clock):
    other = ("other-model", KEY[1])
    _call(_client(TRIP_PATHS["4xx_first"]))
    clock[0] += 600
    openai_compat._cache_strict_unsupported(other)
    clock[0] += 300  # KEY expired, other has 600s left

    assert openai_compat._strict_unsupported(KEY) is False
    assert openai_compat._strict_unsupported(other) is True


def test_reset_clears_deadlines_too(clock):
    _call(_client(TRIP_PATHS["parse_failure_200"]))
    openai_compat._reset_unsupported_cache()
    assert openai_compat._UNSUPPORTED_STRICT_MODE == set()
    assert openai_compat._STRICT_MODE_CACHE_EXPIRY == {}


@pytest.mark.parametrize("path,detection", [
    ("4xx_first", "first"), ("parse_failure_200", "parse_failure_200"),
])
def test_event_carries_ttl_and_keeps_cached_for_process(clock, path, detection):
    with patch.object(openai_compat, "event") as mock_event:
        _call(_client(TRIP_PATHS[path]))
    calls = [
        c for c in mock_event.call_args_list
        if c.args and c.args[0] == "structured_outputs_unavailable"
    ]
    assert len(calls) == 1
    kw = calls[0].kwargs
    assert kw["detection"] == detection
    assert kw["cache_ttl_s"] == openai_compat._STRICT_MODE_CACHE_TTL_SECONDS
    assert kw["cached_for_process"] is True

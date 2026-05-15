"""Behavioral pin: retry() jitter parameter modulates the sleep correctly.

Default (jitter=0.0) preserves the legacy "exact sleep_seconds" behavior.
With jitter>0, the actual sleep is sleep_seconds * uniform(1-j, 1+j).
Invalid jitter values raise ValueError before any work happens.
"""

from unittest.mock import MagicMock, patch

import pytest

from autonomous.ai.retry import retry


def test_jitter_zero_preserves_exact_sleep(monkeypatch):
    """Default behavior: time.sleep gets exactly sleep_seconds."""
    sleep_mock = MagicMock()
    monkeypatch.setattr("autonomous.ai.retry.time.sleep", sleep_mock)

    attempts = []
    def _fail():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("nope")
        return "ok"

    result = retry(_fail, max_attempts=3, sleep_seconds=10, catch=(RuntimeError,))
    assert result == "ok"
    # Two failed attempts → two sleeps; both should be exactly 10s.
    assert sleep_mock.call_count == 2
    for call in sleep_mock.call_args_list:
        assert call.args == (10,)


def test_jitter_positive_multiplies_sleep(monkeypatch):
    """With jitter=0.5 and a deterministic uniform, sleep is scaled."""
    sleep_mock = MagicMock()
    # uniform(0.5, 1.5) — return the upper bound so we can assert the
    # exact multiplied value.
    monkeypatch.setattr("autonomous.ai.retry.time.sleep", sleep_mock)
    monkeypatch.setattr("autonomous.ai.retry.random.uniform", lambda lo, hi: hi)

    def _always_fail():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        retry(_always_fail, max_attempts=2, sleep_seconds=4, jitter=0.5, catch=(RuntimeError,))

    # One failed attempt before the last → one sleep, scaled by hi=1.5.
    assert sleep_mock.call_count == 1
    assert sleep_mock.call_args.args == (4 * 1.5,)


def test_jitter_zero_no_random_call(monkeypatch):
    """When jitter=0, random.uniform must not be invoked at all."""
    uniform_mock = MagicMock(return_value=1.0)
    monkeypatch.setattr("autonomous.ai.retry.random.uniform", uniform_mock)
    monkeypatch.setattr("autonomous.ai.retry.time.sleep", MagicMock())

    def _always_fail():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        retry(_always_fail, max_attempts=2, sleep_seconds=4, catch=(RuntimeError,))

    assert uniform_mock.call_count == 0


def test_jitter_out_of_range_raises():
    """Validation fires before any function invocation."""
    sentinel = []
    def _never_called():
        sentinel.append(1)
        return "should not see this"

    with pytest.raises(ValueError, match="jitter"):
        retry(_never_called, jitter=-0.1, sleep_seconds=1)
    with pytest.raises(ValueError, match="jitter"):
        retry(_never_called, jitter=1.0, sleep_seconds=1)
    with pytest.raises(ValueError, match="jitter"):
        retry(_never_called, jitter=2.0, sleep_seconds=1)

    assert sentinel == [], "validation must short-circuit before invoking func"


def test_jitter_with_zero_sleep_seconds_is_inert(monkeypatch):
    """jitter > 0 but sleep_seconds == 0 → still no sleep, no random call."""
    sleep_mock = MagicMock()
    uniform_mock = MagicMock(return_value=1.0)
    monkeypatch.setattr("autonomous.ai.retry.time.sleep", sleep_mock)
    monkeypatch.setattr("autonomous.ai.retry.random.uniform", uniform_mock)

    def _always_fail():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        retry(_always_fail, max_attempts=2, sleep_seconds=0, jitter=0.5, catch=(RuntimeError,))

    assert sleep_mock.call_count == 0
    assert uniform_mock.call_count == 0

"""Item 17: tests for autonomous.ai.retry.

The helper centralizes the retry / backoff / on-retry-callback pattern
used by the AI adapters. Tests pin:

- success on first attempt (no callbacks fired)
- success after a failure (callback fired once)
- exhaustion re-raises the final exception
- ``default=`` returns instead of raising
- ``default=None`` is honored (vs "default not supplied")
- catch tuple narrows what's swallowed
- on_retry is called with (1-indexed attempt, exc)
- on_retry is NOT called after the last attempt (nothing to retry)
- max_attempts < 1 raises ValueError up front
"""

from unittest.mock import MagicMock

import pytest

from autonomous.ai.retry import retry


class TestSuccessPath:
    def test_returns_first_success(self):
        calls = MagicMock(return_value="ok")
        result = retry(calls)
        assert result == "ok"
        assert calls.call_count == 1

    def test_succeeds_after_one_failure(self):
        attempts = []

        def fn():
            attempts.append(1)
            if len(attempts) < 2:
                raise RuntimeError("first attempt fails")
            return "ok-on-second"

        on_retry = MagicMock()
        result = retry(fn, max_attempts=3, on_retry=on_retry)
        assert result == "ok-on-second"
        assert len(attempts) == 2
        on_retry.assert_called_once()
        # Hook receives (attempt_number, exc).
        attempt_arg, exc_arg = on_retry.call_args.args
        assert attempt_arg == 1
        assert isinstance(exc_arg, RuntimeError)


class TestExhaustion:
    def test_reraises_final_exception_by_default(self):
        def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            retry(fn, max_attempts=3)

    def test_returns_default_when_supplied(self):
        def fn():
            raise RuntimeError("always fails")

        result = retry(fn, max_attempts=2, default={"empty": True})
        assert result == {"empty": True}

    def test_default_none_is_honored(self):
        """``default=None`` returns None — distinct from "not supplied"."""

        def fn():
            raise RuntimeError("nope")

        result = retry(fn, max_attempts=2, default=None)
        assert result is None


class TestCatchNarrowing:
    def test_unexpected_error_propagates(self):
        def fn():
            raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            retry(fn, max_attempts=3, catch=(ValueError,))

    def test_only_listed_types_are_caught(self):
        attempts = []

        def fn():
            attempts.append(1)
            if len(attempts) < 2:
                raise ValueError("transient")
            return "ok"

        result = retry(fn, max_attempts=3, catch=(ValueError,))
        assert result == "ok"
        assert len(attempts) == 2


class TestOnRetryHook:
    def test_called_per_failed_attempt_except_last(self):
        attempts = []

        def fn():
            attempts.append(1)
            raise RuntimeError("nope")

        hook = MagicMock()
        with pytest.raises(RuntimeError):
            retry(fn, max_attempts=3, on_retry=hook)
        # Three attempts, two retries -> hook called twice.
        assert hook.call_count == 2
        # First hook call is for attempt 1, second for attempt 2.
        first_attempt, _ = hook.call_args_list[0].args
        second_attempt, _ = hook.call_args_list[1].args
        assert first_attempt == 1
        assert second_attempt == 2

    def test_not_called_when_first_attempt_succeeds(self):
        hook = MagicMock()
        retry(lambda: "ok", on_retry=hook)
        hook.assert_not_called()


class TestSleep:
    def test_sleep_invoked_between_attempts(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(
            "autonomous.ai.retry.time.sleep", lambda s: sleeps.append(s)
        )
        attempts = []

        def fn():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError()
            return "ok"

        retry(fn, max_attempts=5, sleep_seconds=0.5)
        assert sleeps == [0.5, 0.5]  # two retries -> two sleeps

    def test_no_sleep_after_final_attempt(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(
            "autonomous.ai.retry.time.sleep", lambda s: sleeps.append(s)
        )

        def fn():
            raise RuntimeError()

        with pytest.raises(RuntimeError):
            retry(fn, max_attempts=2, sleep_seconds=1)
        # Two attempts -> one sleep between them, none after the last.
        assert sleeps == [1]


class TestValidation:
    def test_max_attempts_zero_raises(self):
        with pytest.raises(ValueError):
            retry(lambda: None, max_attempts=0)

    def test_negative_max_attempts_raises(self):
        with pytest.raises(ValueError):
            retry(lambda: None, max_attempts=-1)

"""Tests for the iter/2026-05-12 db_sync batch (PR #52).

Independent test-agent coverage for the five-issue batch:

- **#45** — Public ``EMBEDDING_SYNC_HEALTH_KEY_PREFIX`` constant +
  new ``bucket_key_for()`` helper that pins the wire contract in one
  place.
- **#46** — Runtime guard ``_VALID_EMBEDDING_SYNC_EVENTS`` derived
  from ``get_args(EmbeddingSyncEvent)`` so an unknown event silently
  no-ops rather than HINCRBY'ing a phantom field.
- **#47** — ``datetime.utcnow()`` → ``datetime.now(timezone.utc)``
  (deprecated in 3.12, removed in 3.15). Affects ``bucket_key_for``
  and the ``last_synced`` ISO format (now carries ``+00:00``).
- **#48** — Silent-skip threshold now operates on ``content_chars``
  (name + history + associations) rather than the template-prefixed
  ``searchable_text``. Empty docs now correctly trigger silent_skip
  (previously unreachable because the literal ``"Related: "`` made
  ``searchable_text`` always ≥ 11 chars).

The pre-existing :file:`test_unit_record_embedding_sync_event.py` was
updated in lockstep with the API renames in this batch. This file
adds the *new* coverage the batch needs from a fresh perspective:
the helper itself, the guard's single-source-of-truth construction,
the guard-precedes-Redis ordering, the tz-aware ISO suffix, and the
behavioral coverage of the content_chars threshold that the existing
file's structural pin can't reach.
"""

import inspect
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest

import autonomous.db as db_pkg
from autonomous.db import db_sync
from autonomous.db.db_sync import (
    EMBEDDING_SYNC_HEALTH_KEY_PREFIX,
    EmbeddingSyncEvent,
    bucket_key_for,
    record_embedding_sync_event,
)


# ---------------------------------------------------------------------------
# bucket_key_for() — new public helper (#45)
# ---------------------------------------------------------------------------


class TestBucketKeyFor:
    """Pin the helper that consumers (e.g. storyteller /debug/lore/health)
    use to derive the same key shape the recorder writes."""

    def test_default_dt_returns_current_utc_hour(self):
        # The helper must use UTC, not local time — otherwise a consumer
        # in a non-UTC zone would compute a different key than the
        # recorder wrote.
        before = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        key = bucket_key_for()
        after = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        prefix, _, bucket = key.partition(":")
        assert prefix == EMBEDDING_SYNC_HEALTH_KEY_PREFIX
        assert bucket in (before, after), (
            f"bucket {bucket!r} should match current UTC hour "
            f"(between {before!r} and {after!r})"
        )

    def test_explicit_dt_pins_exact_hour(self):
        # A consumer reading a historical bucket passes its own dt;
        # helper must produce the exact key the recorder would have
        # written at that moment.
        dt = datetime(2026, 5, 12, 14, 37, 0, tzinfo=timezone.utc)
        assert bucket_key_for(dt) == "embedding_sync_health:2026051214"

    def test_minute_second_precision_is_dropped(self):
        # Hour bucketing: any datetime within the same UTC hour produces
        # the same key. Otherwise the consumer's HGETALL-by-hour read
        # would scatter counts across keys that should collapse.
        early = datetime(2026, 5, 12, 14, 0, 0, tzinfo=timezone.utc)
        late = datetime(2026, 5, 12, 14, 59, 59, tzinfo=timezone.utc)
        assert bucket_key_for(early) == bucket_key_for(late)

    def test_consecutive_hours_produce_different_keys(self):
        # Boundary between hour buckets must roll forward — a write at
        # 14:59:59 and one at 15:00:00 land in different buckets.
        hour_14 = datetime(2026, 5, 12, 14, 59, 59, tzinfo=timezone.utc)
        hour_15 = datetime(2026, 5, 12, 15, 0, 0, tzinfo=timezone.utc)
        assert bucket_key_for(hour_14) != bucket_key_for(hour_15)

    def test_format_is_prefix_colon_ten_digits(self):
        # Wire shape: <prefix>:YYYYMMDDHH. Document the exact pattern so
        # consumer-side key parsers (regex extracts the bucket) catch
        # any drift here.
        key = bucket_key_for(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
        assert re.fullmatch(
            rf"{re.escape(EMBEDDING_SYNC_HEALTH_KEY_PREFIX)}:\d{{10}}",
            key,
        ), f"key {key!r} doesn't match <prefix>:YYYYMMDDHH"

    def test_far_future_date_works(self):
        # The strftime format doesn't have a year cap until 9999. Pin
        # that the helper handles plausible far-future dates without
        # special-casing.
        dt = datetime(9999, 12, 31, 23, 0, 0, tzinfo=timezone.utc)
        assert bucket_key_for(dt) == "embedding_sync_health:9999123123"

    def test_far_past_date_works(self):
        dt = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert bucket_key_for(dt) == "embedding_sync_health:1970010100"

    def test_naive_datetime_does_not_raise(self):
        # If a consumer passes a naive datetime (no tzinfo), strftime
        # still works — it just treats the wall-clock components
        # literally. Pin that the helper doesn't crash, so consumers
        # that haven't migrated to tz-aware datetimes don't break.
        dt = datetime(2026, 5, 12, 14, 0, 0)
        key = bucket_key_for(dt)
        assert key == "embedding_sync_health:2026051214"

    def test_non_utc_tz_dt_is_used_as_supplied(self):
        # strftime on a tz-aware non-UTC datetime uses the *wall-clock*
        # hour in that timezone, NOT the UTC equivalent. Pin this
        # explicitly because it's a subtle gotcha — consumers in a
        # non-UTC zone passing their local datetime would compute a
        # bucket that doesn't align with what the recorder wrote.
        # Document the contract: pass UTC datetimes, or accept that
        # the hour component is taken at face value.
        est = timezone(timedelta(hours=-5))
        dt = datetime(2026, 5, 12, 9, 0, 0, tzinfo=est)  # 09:00 EST = 14:00 UTC
        assert bucket_key_for(dt) == "embedding_sync_health:2026051209"


# ---------------------------------------------------------------------------
# Public-API exposure (#45)
# ---------------------------------------------------------------------------


class TestPublicAPIExposure:
    """The promotion from underscore-prefix to public is half the value of
    #45 — it documents that consumers may rely on these names."""

    def test_prefix_reachable_via_autonomous_db_namespace(self):
        # ``from autonomous.db.db_sync import *`` in autonomous/db/__init__.py
        # forwards public names. Pin that the rename actually flows
        # through — a residual underscore prefix would not.
        assert getattr(db_pkg, "EMBEDDING_SYNC_HEALTH_KEY_PREFIX", None) == (
            "embedding_sync_health"
        )

    def test_bucket_key_for_reachable_via_autonomous_db_namespace(self):
        # Same forwarding check for the new helper. The two together
        # constitute the wire-contract surface storyteller's consumer
        # will call against.
        assert getattr(db_pkg, "bucket_key_for", None) is bucket_key_for

    def test_module_attr_no_longer_underscored(self):
        # Hard pin: a future drive-by rename to ``_EMBEDDING_...`` would
        # silently break consumers because star-imports skip underscore
        # names. Catch that at unit-test time, not in storyteller's CI.
        assert not hasattr(db_sync, "_EMBEDDING_SYNC_HEALTH_KEY_PREFIX")
        assert hasattr(db_sync, "EMBEDDING_SYNC_HEALTH_KEY_PREFIX")


# ---------------------------------------------------------------------------
# Runtime guard against unknown event strings (#46)
# ---------------------------------------------------------------------------


class TestRuntimeGuardConstruction:
    """The frozenset is derived from ``get_args(EmbeddingSyncEvent)`` — a
    new event needs only the Literal edit, not a parallel hand-maintained
    set. Pin the single-source-of-truth construction."""

    def test_valid_events_set_matches_literal_args(self):
        # If someone adds a new event to the Literal but forgets to
        # update the runtime guard, every record_embedding_sync_event
        # call for the new event would silently no-op — exactly the
        # silent-failure mode #46 was trying to prevent. Test that the
        # set tracks the Literal automatically.
        assert db_sync._VALID_EMBEDDING_SYNC_EVENTS == frozenset(
            get_args(EmbeddingSyncEvent)
        )

    def test_valid_events_is_frozenset(self):
        # Mutability of a module-level constant is a footgun — a test
        # that .add()s to the set would silently change global state
        # for every other test in the suite. frozenset prevents this
        # by construction.
        assert isinstance(db_sync._VALID_EMBEDDING_SYNC_EVENTS, frozenset)

    def test_known_three_events_present(self):
        # If the Literal narrows in the future, the recorder's behavior
        # for currently-supported events changes silently. Pin the
        # current event set so an inadvertent removal trips a test.
        assert db_sync._VALID_EMBEDDING_SYNC_EVENTS == frozenset(
            {"success", "hpc_failure", "silent_skip"}
        )


class TestRuntimeGuardBehavior:
    """The guard's runtime behavior — separate from the lockstep-updated
    test in the existing file, which asserts hincrby/expire NOT called.
    The wedge this file adds: the guard must run BEFORE ``_get_redis()``
    so ORM-only consumers (without the [tasks] extra) don't ImportError
    on a typo'd call."""

    def test_guard_short_circuits_before_get_redis(self):
        # _get_redis() does a lazy ``import redis`` — if the [tasks]
        # extra isn't installed, that ImportError propagates. The guard
        # must run first so an unknown event never reaches that path.
        # We patch _get_redis to raise; if the guard runs first, the
        # raise never fires.
        with patch.object(db_sync, "_get_redis", side_effect=ImportError):
            # Should not raise — guard returns before _get_redis is
            # called.
            record_embedding_sync_event("not_a_real_event")  # type: ignore[arg-type]

    def test_guard_short_circuits_before_injected_client_used(self):
        # Even with an injected client, an unknown event must not
        # produce a Redis call. The lockstep-updated test in the
        # existing file pins this against the default code path; this
        # one pins it against the injected-client code path explicitly.
        client = MagicMock()
        record_embedding_sync_event("typo_event", redis_client=client)  # type: ignore[arg-type]
        assert client.method_calls == [], (
            f"unknown event should produce zero method calls; "
            f"got {client.method_calls}"
        )

    @pytest.mark.parametrize("event", ["success", "hpc_failure", "silent_skip"])
    def test_each_known_event_passes_guard(self, event):
        # Negative-space coverage: verify every event currently in the
        # Literal *does* reach Redis. A subtle bug in the guard's
        # membership check would silently demote a real event to a
        # no-op — exactly what #46 was trying to prevent.
        client = MagicMock()
        record_embedding_sync_event(event, redis_client=client)
        client.hincrby.assert_called_once()
        client.expire.assert_called_once()

    def test_empty_string_event_no_ops(self):
        # Edge case worth pinning: an empty string is a falsy value
        # that's neither in the set nor None. Guard must treat it the
        # same as any other unknown event.
        client = MagicMock()
        record_embedding_sync_event("", redis_client=client)  # type: ignore[arg-type]
        client.hincrby.assert_not_called()

    def test_none_event_no_ops(self):
        # None isn't a valid event under the Literal — guard must not
        # crash on it, must not write to Redis, must not raise.
        client = MagicMock()
        record_embedding_sync_event(None, redis_client=client)  # type: ignore[arg-type]
        client.hincrby.assert_not_called()


# ---------------------------------------------------------------------------
# UTC tz-aware migration (#47)
# ---------------------------------------------------------------------------


class TestUTCTzMigration:
    """``datetime.utcnow()`` is deprecated in 3.12 and removed in 3.15.
    Pin that the migration is complete — any remaining naive utcnow
    would re-introduce the deprecation warning on the CI matrix's
    3.13 run."""

    def test_no_utcnow_calls_remain_in_db_sync(self):
        # Hard textual pin — utcnow() should not appear anywhere in the
        # module source. Catches a future drive-by re-introduction.
        src = inspect.getsource(db_sync)
        # Strip the docstring/comment mentions which document the
        # historical context. Real call sites would have parens.
        assert "datetime.utcnow(" not in src and "utcnow()" not in src, (
            "datetime.utcnow() is deprecated; use datetime.now(timezone.utc) "
            "instead. See PR #52 / issue #47."
        )

    def test_bucket_key_uses_now_utc_under_default(self):
        # Trace test: ensure bucket_key_for()'s default branch calls
        # datetime.now(timezone.utc), not datetime.utcnow() or local
        # time. Patch datetime to assert the call signature.
        with patch("autonomous.db.db_sync.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2026, 5, 12, 14, 0, 0, tzinfo=timezone.utc
            )
            bucket_key_for()
            mock_dt.now.assert_called_once_with(timezone.utc)
            assert not mock_dt.utcnow.called, (
                "bucket_key_for must not call utcnow()"
            )

    def test_last_synced_in_process_sync_uses_now_utc(self):
        # Structural pin on the success branch: the ISO-formatted
        # timestamp written to Redis must come from datetime.now(
        # timezone.utc), not utcnow(). The full success path is too
        # heavy to mock end-to-end here, so pin at the source level.
        src = inspect.getsource(db_sync.process_single_object_sync)
        # Both pieces must coexist on the last_synced line.
        last_synced_line = next(
            (ln for ln in src.split("\n") if "last_synced" in ln), None
        )
        assert last_synced_line is not None, (
            "last_synced field not found in process_single_object_sync"
        )
        assert "datetime.now(timezone.utc)" in last_synced_line, (
            f"last_synced must use datetime.now(timezone.utc); "
            f"got: {last_synced_line.strip()!r}"
        )

    def test_last_synced_wire_format_has_utc_offset_suffix(
        self, monkeypatch
    ):
        # Behavioral pin on the wire-format change. The PR explicitly
        # promises consumers a "+00:00" suffix (was naive before #47);
        # the structural test above only checks the source line, which
        # would silently accept a future drive-by like
        # ``.replace("+00:00", "Z")`` or ``.strftime("%Y-%m-%dT%H:%M:%S")``
        # that breaks consumers parsing the historical naive form.
        # Drive through the success branch with mocked Mongo/Redis and
        # capture the value actually written.
        captured = {}

        def fake_hset(key, mapping):
            captured.setdefault("hsets", []).append((key, dict(mapping)))

        redis_client = MagicMock()
        redis_client.get.return_value = "tok"
        redis_client.hset.side_effect = fake_hset

        mongo_db = MagicMock()
        mongo_db.__getitem__.return_value.find_one.return_value = {
            "_id": "x",
            "name": "long-enough-name",
            "history": "",
            "associations": [],
        }

        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis_client)
        monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo_db)
        monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
        monkeypatch.setattr(db_sync, "get_vector", lambda _: [0.0] * 384)

        # The success branch lazy-imports numpy (intentional — kept out
        # of autonomous.db's import-time graph so ORM-only consumers
        # don't need it). Stub it so this test doesn't require the
        # dependency just to exercise the last_synced wire format.
        monkeypatch.setitem(sys.modules, "numpy", MagicMock())

        db_sync.process_single_object_sync("x", "lore", "tok")

        lore_hsets = [
            (k, m) for k, m in captured.get("hsets", []) if k.startswith("lore:")
        ]
        assert lore_hsets, (
            f"expected at least one hset on lore:* key; "
            f"got captures: {captured}"
        )
        _, mapping = lore_hsets[0]
        assert "last_synced" in mapping, (
            f"hset mapping missing last_synced: {mapping.keys()}"
        )
        last_synced = mapping["last_synced"]

        # Wire-contract guarantee #1: ends with the UTC offset suffix,
        # NOT a "Z" suffix and NOT a bare naive form.
        assert last_synced.endswith("+00:00"), (
            f"last_synced must end with '+00:00' (UTC offset); "
            f"got {last_synced!r}"
        )
        # Wire-contract guarantee #2: round-trips through fromisoformat
        # and the resulting datetime is tz-aware UTC. This catches the
        # subtle case where the suffix is right but the rest of the
        # string drifts.
        parsed = datetime.fromisoformat(last_synced)
        assert parsed.tzinfo is not None, (
            f"parsed last_synced must be tz-aware; got {parsed!r}"
        )
        assert parsed.utcoffset() == timedelta(0), (
            f"parsed last_synced offset must be UTC zero; "
            f"got {parsed.utcoffset()!r}"
        )


# ---------------------------------------------------------------------------
# content_chars threshold (#48) — behavioral coverage
# ---------------------------------------------------------------------------


class TestContentCharsThreshold:
    """Issue #48 fixed a dead branch. The existing test file pins the
    wiring structurally; this class pins the *behavior* by driving
    process_single_object_sync end-to-end with mocked Mongo/Redis."""

    @pytest.fixture
    def mocked_redis(self):
        """A Redis double whose ``get`` returns the token (so the
        debounce check passes) and tracks all writes."""
        r = MagicMock()
        # The debounce check compares token equality; matching token
        # → execute. Set after construction inside each test where
        # the token is known.
        return r

    def _setup_process_sync(self, monkeypatch, doc, redis_client, token="t"):
        """Wire up _get_redis, _get_mongo_db, time.sleep, and
        record_embedding_sync_event for one end-to-end call."""
        redis_client.get.return_value = token

        mongo_db = MagicMock()
        # db[collection].find_one(...) returns the doc
        mongo_db.__getitem__.return_value.find_one.return_value = doc

        recorder = MagicMock()

        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis_client)
        monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo_db)
        monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
        monkeypatch.setattr(
            db_sync, "record_embedding_sync_event", recorder
        )
        return recorder

    def test_empty_doc_triggers_silent_skip(self, monkeypatch, mocked_redis):
        # The whole point of #48: a doc with name/history/associations
        # all empty must produce a silent_skip metric, not a phantom
        # success. Previously the template literal "Related: " padded
        # searchable_text to 11 chars and silent_skip never fired.
        doc = {"_id": "x"}  # no name, history, or associations
        recorder = self._setup_process_sync(
            monkeypatch, doc, mocked_redis, token="t"
        )
        db_sync.process_single_object_sync("x", "lore", "t")
        recorder.assert_called_once_with("silent_skip")

    def test_none_valued_fields_trigger_silent_skip(
        self, monkeypatch, mocked_redis
    ):
        # The fix coerces ``doc.get('name') is None`` to "", not "None".
        # Pin that all-None content reaches the silent_skip branch
        # too, not the success branch.
        doc = {"_id": "x", "name": None, "history": None, "associations": None}
        recorder = self._setup_process_sync(
            monkeypatch, doc, mocked_redis, token="t"
        )
        db_sync.process_single_object_sync("x", "lore", "t")
        recorder.assert_called_once_with("silent_skip")

    def test_content_just_below_threshold_skips(
        self, monkeypatch, mocked_redis
    ):
        # 9 chars of content (below the < 10 threshold) → silent_skip.
        # Pins the exact boundary so a future off-by-one isn't silent.
        doc = {"_id": "x", "name": "123456789", "history": "", "associations": []}
        recorder = self._setup_process_sync(
            monkeypatch, doc, mocked_redis, token="t"
        )
        db_sync.process_single_object_sync("x", "lore", "t")
        recorder.assert_called_once_with("silent_skip")

    def test_content_at_threshold_passes(
        self, monkeypatch, mocked_redis
    ):
        # 10 chars of content (>= threshold) → NOT silent_skip. Pin
        # the other side of the boundary. Use get_vector returning
        # None so we don't reach the success branch either — the
        # important assertion is that silent_skip is NOT recorded.
        doc = {"_id": "x", "name": "1234567890", "history": "", "associations": []}
        recorder = self._setup_process_sync(
            monkeypatch, doc, mocked_redis, token="t"
        )
        monkeypatch.setattr(db_sync, "get_vector", lambda _: None)
        db_sync.process_single_object_sync("x", "lore", "t")
        # Recorder should not have been called for silent_skip. (It
        # may or may not be called for success depending on vector
        # being None, but the silent_skip path is what we're pinning.)
        calls = [c for c in recorder.call_args_list if c.args == ("silent_skip",)]
        assert calls == [], (
            f"content at threshold (10 chars) must not trigger "
            f"silent_skip; got calls: {recorder.call_args_list}"
        )

    def test_associations_count_toward_threshold(
        self, monkeypatch, mocked_redis
    ):
        # Empty name + empty history but a long association list:
        # should bypass silent_skip because content_chars includes the
        # association strings (joined). This prevents a regression
        # where someone "simplifies" content_chars to exclude
        # associations.
        doc = {
            "_id": "x",
            "name": "",
            "history": "",
            "associations": ["alpha_object", "beta_object", "gamma_object"],
        }
        recorder = self._setup_process_sync(
            monkeypatch, doc, mocked_redis, token="t"
        )
        monkeypatch.setattr(db_sync, "get_vector", lambda _: None)
        db_sync.process_single_object_sync("x", "lore", "t")
        skip_calls = [
            c for c in recorder.call_args_list if c.args == ("silent_skip",)
        ]
        assert skip_calls == [], (
            "associations alone should be enough content to pass "
            "threshold; got silent_skip"
        )

    def test_threshold_uses_content_not_template(
        self, monkeypatch, mocked_redis
    ):
        # Regression guard for #48 itself: the buggy old code had the
        # threshold on ``searchable_text`` which is padded by the
        # template literal "Related: ". An empty doc would have
        # searchable_text = ": Related: " (11 chars) and pass. Pin
        # that the empty-doc path correctly triggers silent_skip
        # despite the template prefix still existing in the f-string
        # below — i.e. the threshold variable is content_chars, not
        # searchable_text.
        doc = {"_id": "x", "name": "", "history": "", "associations": []}
        recorder = self._setup_process_sync(
            monkeypatch, doc, mocked_redis, token="t"
        )
        db_sync.process_single_object_sync("x", "lore", "t")
        recorder.assert_called_once_with("silent_skip")

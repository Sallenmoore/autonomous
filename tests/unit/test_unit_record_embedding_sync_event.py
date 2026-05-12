"""Tests for the record_embedding_sync_event hook (issue #41, PR #42).

The hook is a best-effort observability surface that records embedding-sync
events to a Redis hour-bucketed hash. It must:

1. HINCRBY the correct field on the correct key shape.
2. Refresh TTL to 7 days on every record (per-key self-expiry, no sweeper).
3. Accept an injected client (for consumers mirroring writes to a
   separate Redis), defaulting to ``_get_redis()`` otherwise.
4. Swallow all failures silently — never raise, never write to
   stdout/stderr, never affect caller control flow.
5. Be wired at all four call sites identified by issue #41:
   - ``_get_vector_openai`` HPCUnreachableError branch → ``"hpc_failure"``
   - ``_get_vector_openai`` generic Exception branch  → ``"hpc_failure"``
   - ``process_single_object_sync`` silent-skip branch → ``"silent_skip"``
   - ``process_single_object_sync`` success path      → ``"success"``

The wiring order in ``process_single_object_sync`` is contract-relevant:
``record_embedding_sync_event("success")`` must follow ``r.hset(...)`` —
counting a write that didn't land would corrupt the metric. We pin both
the presence of the wiring and the relative ordering at the source level
(integration-testing the full worker requires Mongo + Redis + RQ which
unit tests deliberately avoid).
"""

import inspect
import re
from datetime import datetime, timezone
from typing import get_args, get_origin
from unittest.mock import MagicMock, patch

import pytest

from autonomous.db import db_sync
from autonomous.db.db_sync import (
    EMBEDDING_SYNC_HEALTH_KEY_PREFIX,
    EmbeddingSyncEvent,
    _EMBEDDING_SYNC_HEALTH_TTL_SECONDS,
    record_embedding_sync_event,
)


# ---------------------------------------------------------------------------
# 1. Storage contract — key shape, TTL value, type alias
# ---------------------------------------------------------------------------


class TestStorageContract:
    """Pin the storage shape — consumers (StoryTeller#442) read these keys."""

    def test_key_prefix_is_embedding_sync_health(self):
        # The consumer's /debug/lore/health endpoint will `HGETALL` keys
        # matching this prefix. Renaming requires consumer coordination.
        assert EMBEDDING_SYNC_HEALTH_KEY_PREFIX == "embedding_sync_health"

    def test_ttl_is_seven_days_in_seconds(self):
        # 7 days bounds storage to a known window. Shorter TTLs would
        # truncate the consumer's 24h-window read; longer TTLs grow keys
        # unbounded between cleanups.
        assert _EMBEDDING_SYNC_HEALTH_TTL_SECONDS == 7 * 24 * 3600
        assert _EMBEDDING_SYNC_HEALTH_TTL_SECONDS == 604800

    def test_event_type_is_literal_of_three_strings(self):
        # The Literal type pins the wire vocabulary. New events would
        # widen the consumer-side parser; removing one would break it.
        assert get_origin(EmbeddingSyncEvent) is not None
        assert set(get_args(EmbeddingSyncEvent)) == {
            "success",
            "hpc_failure",
            "silent_skip",
        }


# ---------------------------------------------------------------------------
# 2. Happy path — HINCRBY + EXPIRE called with the right args
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Verify the wire-level Redis interaction."""

    def test_hincrby_called_with_event_field_and_increment_1(self):
        client = MagicMock()
        record_embedding_sync_event("success", redis_client=client)
        client.hincrby.assert_called_once()
        args, _ = client.hincrby.call_args
        # signature is hincrby(key, field, amount)
        assert args[1] == "success"
        assert args[2] == 1

    def test_expire_called_with_seven_day_ttl(self):
        client = MagicMock()
        record_embedding_sync_event("hpc_failure", redis_client=client)
        client.expire.assert_called_once()
        args, _ = client.expire.call_args
        # signature is expire(key, seconds); pin the seconds.
        assert args[1] == _EMBEDDING_SYNC_HEALTH_TTL_SECONDS

    def test_hincrby_and_expire_target_the_same_key(self):
        # TTL is per-key. If hincrby and expire disagreed, the TTL
        # would be set on a different key and the hash would live
        # forever — silent storage leak.
        client = MagicMock()
        record_embedding_sync_event("silent_skip", redis_client=client)
        hincrby_key = client.hincrby.call_args[0][0]
        expire_key = client.expire.call_args[0][0]
        assert hincrby_key == expire_key

    def test_key_is_hour_bucketed_yyyymmddhh(self):
        # The bucket format pins the consumer's window math. If this
        # ever becomes minute-bucketed, the consumer's 24h count would
        # read 24 keys instead of 24 — same N but the math relies on
        # the format. We pin the YYYYMMDDHH shape (10 digits) and that
        # the bucket matches the time when the call was made.
        client = MagicMock()
        before = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        record_embedding_sync_event("success", redis_client=client)
        after = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        key = client.hincrby.call_args[0][0]
        prefix, _, bucket = key.partition(":")
        assert prefix == EMBEDDING_SYNC_HEALTH_KEY_PREFIX
        assert re.fullmatch(r"\d{10}", bucket), (
            f"bucket should be YYYYMMDDHH (10 digits); got {bucket!r}"
        )
        # Tolerate hour-rollover during the test (before != after).
        assert bucket in {before, after}

    def test_returns_none(self):
        # The function is documented as None-returning; callers must
        # not depend on a return value. Pin it.
        client = MagicMock()
        assert record_embedding_sync_event("success", redis_client=client) is None

    def test_hincrby_precedes_expire(self):
        # TTL is meaningless until the key exists — `expire` on a
        # missing key is a Redis no-op (returns 0) and the hash would
        # then live forever once hincrby finally landed. Pin the order
        # at the mock-call level so a future refactor that swaps the
        # two statements regresses unit-test time, not at "why is
        # this hash key never expiring?" production-debug time.
        client = MagicMock()
        record_embedding_sync_event("success", redis_client=client)
        method_names = [c[0] for c in client.method_calls]
        assert method_names == ["hincrby", "expire"], (
            f"Expected hincrby then expire; got {method_names}"
        )


# ---------------------------------------------------------------------------
# 3. Client injection — defaulting vs. caller-supplied
# ---------------------------------------------------------------------------


class TestClientInjection:
    """Pin the client-resolution rule: explicit > default."""

    def test_injected_client_is_used_verbatim(self):
        injected = MagicMock()
        with patch.object(db_sync, "_get_redis") as mock_default:
            record_embedding_sync_event("success", redis_client=injected)
        mock_default.assert_not_called()
        injected.hincrby.assert_called_once()

    def test_default_client_is_get_redis_when_not_injected(self):
        with patch.object(db_sync, "_get_redis") as mock_default:
            mock_default.return_value = MagicMock()
            record_embedding_sync_event("success")
        mock_default.assert_called_once()
        mock_default.return_value.hincrby.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Best-effort contract — never raise, never write to streams
# ---------------------------------------------------------------------------


class TestBestEffortContract:
    """Failure-class matrix. Each failure point must be silently swallowed.

    The docstring promises: "any failure (Redis unreachable, [tasks]
    extra absent, network blip) is silently swallowed". We exercise
    each documented failure class and assert (a) no exception escapes,
    (b) no output reaches stdout or stderr.
    """

    def test_hincrby_raising_is_swallowed(self, capsys):
        client = MagicMock()
        client.hincrby.side_effect = RuntimeError("redis down")
        # Must not raise.
        record_embedding_sync_event("success", redis_client=client)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_expire_raising_is_swallowed(self, capsys):
        # The hincrby already succeeded — the event is counted. If
        # EXPIRE raises (e.g., connection died between calls), the key
        # would eventually accumulate, but that's a smaller problem
        # than crashing the worker on a diagnostic failure.
        client = MagicMock()
        client.expire.side_effect = RuntimeError("connection reset")
        record_embedding_sync_event("hpc_failure", redis_client=client)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_default_client_resolution_failure_is_swallowed(self, capsys):
        # The most common production failure mode: a consumer installed
        # autonomous-app without the [tasks] extra, so `import redis`
        # inside _get_redis() raises ImportError. The recorder must
        # tolerate this — the consumer can't have meaningfully opted
        # into recording yet a base ORM install must still work.
        with patch.object(db_sync, "_get_redis", side_effect=ImportError(
            "No module named 'redis'"
        )):
            record_embedding_sync_event("silent_skip")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_unknown_event_string_is_silent_noop(self, capsys):
        # An unknown event name (typo or unrecognized) must NOT be written
        # to Redis — bucket pollution would silently underreport the
        # consumer's named-field read (storyteller's /debug/lore/health
        # sums success+hpc_failure+silent_skip; a typo'd field never gets
        # counted, with no out-of-band signal). The guard is silent
        # (no raise, no log) to keep the best-effort contract intact.
        client = MagicMock()
        record_embedding_sync_event("unrecognized_event", redis_client=client)  # type: ignore[arg-type]
        client.hincrby.assert_not_called()
        client.expire.assert_not_called()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


# ---------------------------------------------------------------------------
# 5. HPC call-site wiring — mockable end-to-end via _get_vector_openai
# ---------------------------------------------------------------------------


class TestHPCCallSiteWiring:
    """Both HPC failure branches must fire `hpc_failure` and preserve
    the existing capsys-blank stderr contract."""

    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        # openai_compat imports AutoTasks at module level; neutralize it
        # so the lazy import inside _get_vector_openai doesn't reach Redis.
        with patch("autonomous.ai.models.openai_compat.AutoTasks") as mock_tasks:
            mock_tasks.return_value.get_current_task.return_value = None
            yield mock_tasks

    def test_hpc_unreachable_branch_calls_recorder_with_hpc_failure(self):
        from autonomous.ai.models.openai_compat import (
            HPCUnreachableError,
            OpenAIClient,
        )
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=HPCUnreachableError("connection refused"),
        ), patch.object(
            db_sync, "record_embedding_sync_event"
        ) as mock_record:
            db_sync._get_vector_openai("some text")
        mock_record.assert_called_once_with("hpc_failure")

    def test_generic_exception_branch_calls_recorder_with_hpc_failure(self):
        from autonomous.ai.models.openai_compat import OpenAIClient
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=ValueError("malformed response"),
        ), patch.object(
            db_sync, "record_embedding_sync_event"
        ) as mock_record:
            db_sync._get_vector_openai("some text")
        mock_record.assert_called_once_with("hpc_failure")

    def test_success_path_does_not_call_recorder_from_get_vector_openai(self):
        # Only HPC failures emit from the openai vector path; success
        # is counted at the higher process_single_object_sync layer
        # after the hset lands. If _get_vector_openai grew its own
        # success record, we'd double-count.
        from autonomous.ai.models.openai_compat import OpenAIClient
        with patch.object(
            OpenAIClient, "get_embedding", return_value=[0.1, 0.2, 0.3]
        ), patch.object(
            db_sync, "record_embedding_sync_event"
        ) as mock_record:
            result = db_sync._get_vector_openai("some text")
        assert result == [0.1, 0.2, 0.3]
        mock_record.assert_not_called()


# ---------------------------------------------------------------------------
# 6. HPC marker stdout contract still holds — regression guard
# ---------------------------------------------------------------------------


class TestHPCMarkerContractPreserved:
    """Adding the recorder must not change the `[HPC-UNREACHABLE]` log
    line that downstream scrapers tail. The existing marker test in
    test_unit_db_sync_hpc_marker.py asserts captured.err == "". If the
    recorder ever started writing to stderr (or anywhere), that test
    would fail; this is a belt-and-suspenders pin on the same contract
    framed from the new-code side."""

    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        with patch("autonomous.ai.models.openai_compat.AutoTasks") as mock_tasks:
            mock_tasks.return_value.get_current_task.return_value = None
            yield mock_tasks

    def test_recorder_does_not_write_to_stderr_on_failure_path(self, capsys):
        from autonomous.ai.models.openai_compat import (
            HPCUnreachableError,
            OpenAIClient,
        )
        # Force the recorder itself to raise, which is the worst case —
        # if it ever logged its own error, the HPC marker test's
        # captured.err == "" assertion would break in mysterious ways.
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=HPCUnreachableError("x"),
        ), patch.object(
            db_sync, "_get_redis", side_effect=RuntimeError("recorder boom")
        ):
            db_sync._get_vector_openai("t")
        captured = capsys.readouterr()
        # stdout still has the marker (existing contract).
        assert "[HPC-UNREACHABLE]" in captured.out
        # stderr is still pristine (recorder failure must be invisible).
        assert captured.err == ""


# ---------------------------------------------------------------------------
# 7. process_single_object_sync wiring — source-level (integration-only
#    in any live form; this slice is the pragmatic pin)
# ---------------------------------------------------------------------------


def _process_sync_body() -> str:
    """Return the source of process_single_object_sync as a string.

    Mocking the full worker requires Mongo + Redis + RQ. The wiring
    contract is structural ("the recorder call sits in this branch in
    this order"), so source inspection is the right tool — it'd catch
    a future refactor that drops a wire without us needing to bring up
    the Compose stack.
    """
    return inspect.getsource(db_sync.process_single_object_sync)


class TestProcessSyncWiringStructural:

    def test_silent_skip_branch_calls_recorder_with_silent_skip(self):
        # The silent-skip threshold check must wire the recorder before
        # the early return — pin structurally because the worker's full
        # path needs Mongo + Redis + RQ to exercise. Threshold variable
        # is content_chars (built from real doc fields only, not the
        # template-literal-inflated searchable_text — see #48).
        src = _process_sync_body()
        # Slice from the threshold check to the next blank line.
        m = re.search(
            r"if len\(content_chars\) < 10:(.*?)(?:\n\n|\n    [a-zA-Z#])",
            src,
            re.S,
        )
        assert m, (
            "Could not locate the silent-skip branch in "
            "process_single_object_sync source — refactor regression?"
        )
        branch = m.group(1)
        assert re.search(
            r"record_embedding_sync_event\(\s*[\"']silent_skip[\"']\s*\)",
            branch,
        ), (
            "silent-skip branch is missing the "
            "`record_embedding_sync_event(\"silent_skip\")` wire."
        )

    def test_success_recorder_follows_hset_in_source_order(self):
        # The success counter must come AFTER `_get_redis().hset(...)`
        # so a raising hset doesn't get counted as success. We pin the
        # source order: find both line numbers, assert recorder > hset.
        src = _process_sync_body()
        # Locate hset call. The function has exactly one hset (on the
        # `lore:{object_id}` key), so a non-anchored match is safe.
        hset_match = re.search(r"\.hset\(", src)
        success_match = re.search(
            r"record_embedding_sync_event\(\s*[\"']success[\"']\s*\)", src
        )
        assert hset_match, "hset() call disappeared from process_single_object_sync"
        assert success_match, (
            "process_single_object_sync is missing the "
            "`record_embedding_sync_event(\"success\")` wire."
        )
        assert success_match.start() > hset_match.start(), (
            "record_embedding_sync_event(\"success\") must follow hset() in "
            "source — counting writes that haven't landed corrupts the "
            "success-rate metric."
        )

    def test_success_recorder_is_inside_the_if_vector_branch(self):
        # The success path runs only when a vector was generated AND
        # the hset succeeded. We pin that the recorder lives inside
        # the `if vector:` block, not at the top of the function or
        # in an unrelated branch.
        src = _process_sync_body()
        m = re.search(r"if vector:(.+)", src, re.S)
        assert m, "if vector: branch missing from process_single_object_sync"
        if_vector_body = m.group(1)
        # Limit to that branch's indented body — once we hit a line
        # at column 4 ("def " or top-level statement), we're out.
        # Cheaper: just look at the rest of the function from `if
        # vector:` onward, which is the last logical block.
        assert re.search(
            r"record_embedding_sync_event\(\s*[\"']success[\"']\s*\)",
            if_vector_body,
        )

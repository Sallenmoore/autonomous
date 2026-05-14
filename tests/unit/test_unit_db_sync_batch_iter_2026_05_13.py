"""Tests for the iter/2026-05-13 db_sync observability batch (PR #63).

Independent test-agent coverage for the six-issue batch:

- **#53** — Restore forensic ``[WARNING]`` log in
  ``record_embedding_sync_event``'s unknown-event guard. The PR #46
  guard added in iter/2026-05-12 silently dropped typo'd events with
  no out-of-band signal; this pins that the no-Redis-write contract
  holds AND the WARNING log is emitted (programmer-error attribution).
- **#54** — ``bucket_key_for`` warns on naive datetime arguments
  (still returns a key, no raise) and uses ``is None`` default check
  instead of the falsy-``dt`` ``or`` idiom (which would also stomp on
  a zero-valued datetime — an edge case but a real contract bug).
- **#55** — No-op close: producer-side wire-format (``+00:00`` suffix
  on ``last_synced``) is already pinned behaviorally by
  ``test_unit_db_sync_batch.py::TestUTCTzMigration::test_last_synced_wire_format_has_utc_offset_suffix``.
- **#56** — Promote magic ``10`` to module constant ``MIN_CONTENT_CHARS``
  and add per-doc print on the ``silent_skip`` branch (parallel to the
  not-found / superseded prints that have always been loud).
- **#57** — Design pin only: caller-side ``else`` on ``if vector:``
  would double-count failures. Pinned by dev's ephemeral test +
  in-source comment; no committed test needed (would be tautological).
- **#60** — ``_get_vector_local`` failure observability is now
  symmetric with ``_get_vector_openai``: both transport-exception AND
  non-200 status paths bump ``hpc_failure`` and emit
  ``[HPC-UNREACHABLE]``. The pre-fix non-200 path was a silent
  ``return None`` with no marker and no counter.

The pre-existing :file:`test_unit_record_embedding_sync_event.py` was
updated in lockstep with #56's ``MIN_CONTENT_CHARS`` rename. The
pre-existing :file:`test_unit_db_sync_batch.py` pins the *prior*
batch's structural invariants (guard construction, UTC migration,
content_chars threshold). This file adds *new* coverage for the
behaviors introduced by PR #63 from a fresh perspective.
"""

import inspect
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from autonomous.db import db_sync
from autonomous.db.db_sync import (
    MIN_CONTENT_CHARS,
    bucket_key_for,
    record_embedding_sync_event,
)


# ---------------------------------------------------------------------------
# #53 — record_embedding_sync_event WARNING log on unknown event
# ---------------------------------------------------------------------------


class TestUnknownEventWarningLog:
    """Pin: unknown event names emit a one-line WARNING log AND skip
    the Redis write. Pre-PR-#63 the guard was silent — typo'd events
    landed in nobody's dashboard and nobody's logs. The forensic line
    is the replacement signal for the phantom HINCRBY field that #46
    removed."""

    def test_unknown_event_emits_warning_log_with_prefix(self):
        # The autonomous log singleton is imported as `from autonomous
        # import log` into db_sync — patch the module-local name, not
        # the autonomous package attr.
        client = MagicMock()
        with patch.object(db_sync, "log") as mock_log:
            record_embedding_sync_event("typo_event", redis_client=client)
        # Assert at least one WARNING call with the expected shape —
        # not exact `call_count == 1`. A future refactor that adds a
        # benign DEBUG breadcrumb (e.g. "call site located at X") next
        # to the WARNING should not break the regression pin.
        warning_calls = [
            c for c in mock_log.call_args_list
            if c.args
            and isinstance(c.args[0], str)
            and c.args[0].startswith(
                "[WARNING] record_embedding_sync_event:"
            )
        ]
        assert len(warning_calls) >= 1, (
            f"unknown event must produce at least one WARNING log; "
            f"all log calls were: {mock_log.call_args_list}"
        )
        msg = warning_calls[0].args[0]
        assert "typo_event" in msg, (
            "the offending value should appear in the log so the call "
            "site is attributable"
        )

    def test_unknown_event_does_not_write_redis(self):
        # The forensic log is additive; the no-write guard from #46
        # still holds. Phantom HINCRBY fields would let typos
        # poison the consumer's HGETALL-on-named-fields read.
        client = MagicMock()
        with patch.object(db_sync, "log"):
            record_embedding_sync_event("typo_event", redis_client=client)
        client.hincrby.assert_not_called()
        client.expire.assert_not_called()

    def test_logger_exception_does_not_propagate_from_unknown_event(self):
        # Best-effort observability invariant: the log call itself is
        # wrapped in try/except. If a future refactor drops the try
        # block, this test fails — preserving the no-raise contract
        # on the recorder surface (it must never become control flow).
        client = MagicMock()
        with patch.object(db_sync, "log", side_effect=RuntimeError("boom")):
            # Must not raise.
            record_embedding_sync_event("typo_event", redis_client=client)
        # And still no Redis write.
        client.hincrby.assert_not_called()


# ---------------------------------------------------------------------------
# #54 — bucket_key_for WARNING log on naive datetime
# ---------------------------------------------------------------------------


class TestBucketKeyForNaiveDatetimeWarning:
    """Pin: passing a naive datetime to ``bucket_key_for`` emits a
    one-line WARNING (still returns a valid key, no raise) — the
    breadcrumb that root-causes mis-aligned hourly keys when a caller
    converts a wall-clock datetime through the helper."""

    def test_naive_datetime_emits_warning_with_prefix(self):
        naive = datetime(2026, 5, 14, 12, 0, 0)  # no tzinfo
        with patch.object(db_sync, "log") as mock_log:
            key = bucket_key_for(naive)
        # At-least-one WARNING with the expected prefix; tolerate
        # future benign additions (e.g. DEBUG site-attribution).
        warning_calls = [
            c for c in mock_log.call_args_list
            if c.args
            and isinstance(c.args[0], str)
            and c.args[0].startswith("[WARNING] bucket_key_for:")
        ]
        assert len(warning_calls) >= 1, (
            f"naive datetime must produce at least one WARNING log; "
            f"all log calls were: {mock_log.call_args_list}"
        )
        msg = warning_calls[0].args[0]
        assert "naive" in msg.lower(), (
            "the diagnostic should name the contract violation"
        )
        # And the key still comes back — no raise, no None.
        assert key.startswith("embedding_sync_health:")

    def test_naive_datetime_still_returns_strftime_key(self):
        # The whole point of WARN-not-RAISE is callers keep working.
        # Pin that the returned key is the strftime of the naive
        # datetime treated as wall-clock — that's the documented
        # behavior in the docstring ("treated as wall-clock — the
        # resulting key may mis-align...").
        naive = datetime(2026, 5, 14, 12, 0, 0)
        with patch.object(db_sync, "log"):
            key = bucket_key_for(naive)
        assert key == "embedding_sync_health:2026051412"

    def test_utc_aware_datetime_does_not_log(self):
        # Negative pin: the WARNING is strictly for naive datetimes.
        # If it fires on UTC-aware too, every recorder write path
        # would log noise and the breadcrumb would lose signal.
        aware = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
        with patch.object(db_sync, "log") as mock_log:
            bucket_key_for(aware)
        mock_log.assert_not_called()

    def test_default_none_argument_does_not_log(self):
        # The most common call shape — no argument, returns the
        # current-hour bucket — must not log. ``datetime.now(timezone.utc)``
        # is aware by construction.
        with patch.object(db_sync, "log") as mock_log:
            bucket_key_for()
            bucket_key_for(None)
        mock_log.assert_not_called()

    def test_non_utc_tz_aware_does_not_log(self):
        # The source guard is `dt.tzinfo is None` — any non-None tzinfo
        # is treated as "aware enough, caller's responsibility." Pin
        # this: an EST/UTC+5/+9 datetime must NOT trip the WARNING.
        # If a future tightening narrowed the guard to "warn on
        # non-UTC tz too," every storyteller caller that passes a
        # local-zone datetime would suddenly spam logs — a real
        # regression worth catching at this perimeter.
        non_utc = timezone(timedelta(hours=-5))  # rough EST
        aware_non_utc = datetime(2026, 5, 14, 12, 0, 0, tzinfo=non_utc)
        with patch.object(db_sync, "log") as mock_log:
            bucket_key_for(aware_non_utc)
        mock_log.assert_not_called()

    def test_logger_exception_does_not_propagate_from_naive_branch(self):
        # Same best-effort invariant as the recorder: if logging fails
        # during the naive-warning path, the helper must still return
        # a key (callers depend on bucket_key_for as a non-raising
        # wire-format helper).
        naive = datetime(2026, 5, 14, 12, 0, 0)
        with patch.object(db_sync, "log", side_effect=RuntimeError("boom")):
            key = bucket_key_for(naive)
        assert key == "embedding_sync_health:2026051412"


# ---------------------------------------------------------------------------
# #56 — MIN_CONTENT_CHARS module constant + silent_skip per-doc print
# ---------------------------------------------------------------------------


class TestMinContentCharsConstantExposure:
    """Pin: ``MIN_CONTENT_CHARS`` is a module-level constant at the
    documented value. Promoting the magic 10 makes the threshold
    auditable from a single grep and tunable without diffing through
    the call site. Both invariants matter — value AND exposure."""

    def test_constant_is_module_attribute(self):
        assert hasattr(db_sync, "MIN_CONTENT_CHARS"), (
            "MIN_CONTENT_CHARS must be importable from db_sync; "
            "in-function literals are not auditable from outside"
        )

    def test_constant_value_is_ten(self):
        # The value is documented in the inline comment as "load-
        # bearing magic number after #48 made the silent_skip branch
        # reachable". Pin that the rename preserves the value — a
        # silent change to e.g. 5 would shift the silent_skip surface
        # area and could mask a regression where embeddings start
        # firing on noise-only docs.
        assert db_sync.MIN_CONTENT_CHARS == 10



class TestSilentSkipPerDocPrint:
    """Pin: the silent_skip branch in ``process_single_object_sync``
    emits a per-doc print so operators investigating
    storyteller's /debug/lore/health can attribute an increment to a
    specific document. Parallel to the not-found / superseded
    branches, which have always been loud."""

    def _setup(self, monkeypatch, doc):
        # Minimal scaffolding to drive the silent_skip branch. We
        # avoid the helper's network paths by stubbing _get_redis,
        # _get_mongo_db, and the recorder.
        redis_client = MagicMock()
        redis_client.get.return_value = "tok"
        mongo_db = MagicMock()
        mongo_db.__getitem__.return_value.find_one.return_value = doc
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis_client)
        monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo_db)
        monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
        return redis_client

    def test_silent_skip_emits_per_doc_print(self, monkeypatch, capsys):
        # Empty-content doc → content_chars is "" (len 0) < 10.
        doc = {"_id": "tiny-id", "name": "", "history": "", "associations": []}
        self._setup(monkeypatch, doc)
        # Silence the recorder so the assertion focuses on print output.
        monkeypatch.setattr(
            db_sync, "record_embedding_sync_event", lambda *a, **k: None
        )
        db_sync.process_single_object_sync("tiny-id", "lore", "tok")
        out = capsys.readouterr().out
        assert "Skipping embedding" in out, (
            "per-doc print is the operator-facing breadcrumb; without it "
            "a silent_skip increment is unattributable"
        )

    def test_silent_skip_print_includes_doc_identifier_and_threshold(
        self, monkeypatch, capsys
    ):
        # Pin the wire-format of the breadcrumb — the doc id, the
        # collection name, the actual chars, and the threshold value
        # must all appear so log-grep workflows can reconstruct
        # "what doc, why under threshold."
        doc = {"_id": "abc123", "name": "x", "history": "", "associations": []}
        self._setup(monkeypatch, doc)
        monkeypatch.setattr(
            db_sync, "record_embedding_sync_event", lambda *a, **k: None
        )
        db_sync.process_single_object_sync("abc123", "lore", "tok")
        out = capsys.readouterr().out
        assert "abc123" in out, "doc id missing from breadcrumb"
        assert "lore" in out, "collection name missing from breadcrumb"
        # The threshold value (the constant) should appear so a grep
        # finds both the call sites and the threshold simultaneously.
        assert str(db_sync.MIN_CONTENT_CHARS) in out, (
            "threshold value missing from breadcrumb"
        )

    def test_threshold_passing_does_not_emit_skipping_print(
        self, monkeypatch, capsys
    ):
        # Negative-space pin: if a future refactor accidentally moves
        # the "Skipping embedding" print OUTSIDE the `if len(...) <
        # MIN_CONTENT_CHARS:` branch, every successful indexing would
        # also log a spurious skip line. Drive the function with
        # well-above-threshold content and assert the line is absent.
        doc = {
            "_id": "abc123",
            "name": "a-name-well-above-the-ten-char-threshold",
            "history": "",
            "associations": [],
        }
        self._setup(monkeypatch, doc)
        # Stub out the recorder AND get_vector so we don't try to
        # talk to an embeddings service. get_vector returning None
        # short-circuits the Redis hset path harmlessly.
        monkeypatch.setattr(
            db_sync, "record_embedding_sync_event", lambda *a, **k: None
        )
        monkeypatch.setattr(db_sync, "get_vector", lambda _: None)
        db_sync.process_single_object_sync("abc123", "lore", "tok")
        out = capsys.readouterr().out
        assert "Skipping embedding" not in out, (
            "the Skipping-embedding breadcrumb belongs to the "
            "silent_skip branch only; firing it on threshold-passing "
            "docs would poison the operator dashboard with phantom "
            "skip attribution"
        )

    def test_threshold_loop_still_uses_constant_not_literal(self):
        # Structural pin (refactor-rot guard, not behavioral): the
        # `if len(content_chars) < ...` comparison must reference the
        # named constant MIN_CONTENT_CHARS rather than the literal 10.
        # Behavioral regression on the threshold itself is pinned by
        # `test_unit_db_sync_batch.py::TestContentCharsThreshold` (10
        # passes, 9 silent_skips). This test pins the audit-from-one-
        # grep promise that #56's rename was specifically about — if
        # someone inlines the constant back to the literal, the
        # promise breaks even though behavior is identical.
        src = inspect.getsource(db_sync.process_single_object_sync)
        assert re.search(
            r"len\(content_chars\)\s*<\s*MIN_CONTENT_CHARS", src
        ), (
            "threshold comparison must reference the constant; if the "
            "literal 10 returned, change diff-grep would lose track of "
            "all places that need to move together"
        )


# ---------------------------------------------------------------------------
# #60 — _get_vector_local failure observability symmetric with openai
# ---------------------------------------------------------------------------


class TestVectorLocalObservability:
    """Pin: both ``_get_vector_local`` failure modes (transport
    exception AND non-200 status) bump ``hpc_failure`` and emit
    ``[HPC-UNREACHABLE]``. Pre-#60, the non-200 path was a silent
    ``return None`` — the consumer dashboard underreported every
    media_ai HTTP error that wasn't a connection failure, and log
    scrapers tailing the marker family missed the same."""

    def test_transport_exception_records_hpc_failure(self, capsys):
        with patch.object(
            db_sync.requests,
            "post",
            side_effect=requests.ConnectionError("refused"),
        ), patch.object(
            db_sync, "record_embedding_sync_event"
        ) as mock_record:
            result = db_sync._get_vector_local("some text")
        assert result is None, (
            "failure path must still return None — caller contract "
            "predates the recorder addition"
        )
        mock_record.assert_called_once_with("hpc_failure")
        # The marker is the log-scraper contract.
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE]" in out, (
            "marker family is the cross-provider scraper regex; if "
            "_get_vector_local emits a different marker, the openai "
            "and local paths split and the dashboard underreports"
        )

    def test_non_200_status_records_hpc_failure(self, capsys):
        # The substance of #60: previously, a 503 from media_ai was a
        # silent None-return — no marker, no counter. Now it must
        # fire under the same family as the transport-exception case.
        fake_resp = MagicMock()
        fake_resp.status_code = 503
        with patch.object(
            db_sync.requests, "post", return_value=fake_resp
        ), patch.object(
            db_sync, "record_embedding_sync_event"
        ) as mock_record:
            result = db_sync._get_vector_local("some text")
        assert result is None
        mock_record.assert_called_once_with("hpc_failure")
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE]" in out
        # The status code should appear so a log scraper can tier
        # severity (502/503 = transient, 4xx = call-site bug).
        assert "503" in out, (
            "the HTTP status is the only on-the-wire diagnostic; "
            "without it operators can't distinguish transient from "
            "permanent failures"
        )

    def test_success_path_does_not_record_or_mark(self, capsys):
        # Regression guard symmetric with the openai-side test in
        # test_unit_record_embedding_sync_event.py — only failures
        # emit. If _get_vector_local started recording on success
        # it would double-count alongside process_single_object_sync's
        # higher-layer success counter.
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        with patch.object(
            db_sync.requests, "post", return_value=fake_resp
        ), patch.object(
            db_sync, "record_embedding_sync_event"
        ) as mock_record:
            result = db_sync._get_vector_local("some text")
        assert result == [0.1, 0.2, 0.3]
        mock_record.assert_not_called()
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE]" not in out, (
            "marker must not fire on success; would poison the "
            "log-scraper's failure regex"
        )

    def test_failure_marker_names_local_provider(self, capsys):
        # Belt-and-suspenders: the marker line should identify the
        # local provider specifically so operators can disambiguate
        # local-vs-openai HPC failures in mixed-provider deployments.
        # Pre-#60 there was nothing to disambiguate (silent return);
        # post-#60 both providers can fire and the dashboard needs
        # provider attribution.
        with patch.object(
            db_sync.requests,
            "post",
            side_effect=requests.ConnectionError("refused"),
        ), patch.object(db_sync, "record_embedding_sync_event"):
            db_sync._get_vector_local("text")
        out = capsys.readouterr().out
        assert "local" in out.lower(), (
            "marker should name the provider so the dashboard splits "
            "local vs openai failure counts"
        )

    def test_non_tuple_exception_is_caught_and_recorded(self):
        # Post-#65: `_get_vector_local` catches bare `Exception`,
        # matching `_get_vector_openai`. Previously this test pinned
        # the asymmetric narrow-tuple catch as an INTENT PIN; the
        # test agent's note authorized the flip ("If dev later
        # decides both providers should catch every Exception, flip
        # the assertion."). Both providers' exception surfaces now
        # move together — symmetric "any failure returns None and
        # bumps hpc_failure". Dashboard math (success + hpc_failure
        # + silent_skip ≈ total work) is preserved.
        with patch.object(
            db_sync.requests,
            "post",
            side_effect=RuntimeError("not a RequestException subclass"),
        ), patch.object(db_sync, "record_embedding_sync_event") as mock_record:
            result = db_sync._get_vector_local("text")
        assert result is None, (
            "bare-Exception catch must keep the documented degrade "
            "contract — return None, do not propagate"
        )
        # NOTE: `Mock.assert_called_once_with(...)` raises on mismatch,
        # so this line is the actual assertion. Don't reattach a
        # trailing tuple "message" — `(call_result, "msg")` would
        # just build and discard a 2-tuple expression and the
        # explanatory string would never reach the operator.
        mock_record.assert_called_once_with("hpc_failure")


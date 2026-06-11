"""Independent committed coverage for PR #95 / issues #84 + #85.

Both are adapter-side hardenings of pre-existing patterns:

**#84 — Gemini orphan cleanup broadening.** The outer except clause
around the poll loop widened from
``(GeminiFileUploadTimeoutError, genai.errors.APIError)`` to bare
``Exception``. Rationale: ``genai.errors.UnknownApiResponseError``
subclasses ``ValueError`` rather than ``APIError`` and would have
skipped cleanup under the narrower tuple. The per-orphan inner
delete catch also widened from ``genai.errors.APIError`` to
``Exception`` so a ``TypeError`` / ``AttributeError`` during cleanup
can't mask the original poll exception. New guard: skip orphans whose
``.name is None`` (partial-upload edge case from
``google.genai.types.File.name`` being typed ``Optional[str]``).

**#85 — flux transport_error_cls narrowed.** Flux's module-level
``_HTTP`` was constructed with
``transport_error_cls=requests.RequestException``. The
``raise_for_status``-raised ``requests.HTTPError`` was a
``RequestException`` subclass, so HttpClient's retry catch tuple
matched it — burning the retry budget on 4xx. Narrowing to
``requests.ConnectionError`` removes that overlap (HTTPError is NOT a
ConnectionError subclass) while preserving the downstream
``except (requests.RequestException, ValueError, OSError)`` catch in
``generate_image`` (ConnectionError is-a RequestException).

Independent perspective (no peek at dev's ``tests/_dev_local/``):

For #84:
- A non-APIError, non-Timeout poll exception (e.g. ``ValueError`` —
  what UnknownApiResponseError IS in the SDK) STILL triggers cleanup.
- An orphan with ``name=None`` is skipped (no TypeError raised).
- An inner delete failure of any type does NOT mask the original
  poll exception (the broadened inner except absorbs ANY exception).

For #85:
- ``_HTTP.transport_error_cls`` is exactly ``requests.ConnectionError``.
- ``ConnectionError`` is-a ``requests.RequestException`` — the
  downstream ``except`` in ``generate_image`` still catches it.
- ``HTTPError`` is NOT a ``ConnectionError`` — confirms the overlap
  is gone.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


# ===========================================================================
# #84 — Gemini orphan-cleanup broadening
# ===========================================================================


class _StubAPIError(Exception):
    """Stand-in for ``google.genai.errors.APIError``."""


def _make_stub(per_file_poll_states, *, poll_raises=None, orphan_names=None):
    """Build a Gemini stub. ``per_file_poll_states`` is list-of-lists:
    each inner list is the upload's initial state + subsequent poll
    states. ``poll_raises`` (optional): raise this exception class on
    the first poll instead of returning a state. ``orphan_names``
    (optional): override the .name attribute of each uploaded handle
    (e.g. ``[None]`` to test the None-skip guard)."""

    class _Stub:
        MAX_FILES = 10

        def save(self):
            pass

    stub = _Stub()
    stub.client = MagicMock()

    upload_handles = []
    poll_handles = []
    for file_idx, states in enumerate(per_file_poll_states):
        state_objs = []
        for s in states:
            so = MagicMock()
            so.name = s
            state_objs.append(so)
        upload_h = MagicMock()
        if orphan_names is not None and file_idx < len(orphan_names):
            upload_h.name = orphan_names[file_idx]
        else:
            upload_h.name = f"files/upload-{file_idx}"
        upload_h.state = state_objs[0]
        upload_handles.append(upload_h)
        for s in state_objs[1:]:
            h = MagicMock()
            h.name = upload_h.name
            h.state = s
            poll_handles.append(h)

    stub.client.files.upload = MagicMock(side_effect=upload_handles)
    stub.client.files.list = MagicMock(return_value=[])
    stub.client.files.delete = MagicMock()
    if poll_raises is not None:
        stub.client.files.get = MagicMock(side_effect=poll_raises)
    else:
        stub.client.files.get = MagicMock(side_effect=poll_handles or [upload_handles[0]])
    return stub


def _files(n):
    return [{"name": f"file_{i}.json", "file": b"{}"} for i in range(n)]


def _call(stub, file_list):
    from autonomous.ai.models import gemini
    return gemini.GeminiAIModel._add_files(stub, file_list)


@pytest.fixture(autouse=True)
def _patch_api_error(monkeypatch):
    from autonomous.ai.models import gemini
    monkeypatch.setattr(gemini.genai.errors, "APIError", _StubAPIError, raising=False)
    yield


def test_value_error_during_poll_still_triggers_orphan_cleanup(monkeypatch):
    """A poll failure that's NOT APIError-shaped (e.g. ValueError, which
    is what google.genai's UnknownApiResponseError actually subclasses)
    must still trigger orphan cleanup post-#84. Pre-#84 the outer
    ``except (GeminiFileUploadTimeoutError, genai.errors.APIError)``
    would NOT catch it — orphan leak re-introduced."""
    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "60")
    stub = _make_stub(
        [["PROCESSING", "PROCESSING"]],
        poll_raises=ValueError("SDK could not decode response"),
    )

    times = iter([0.0, 0.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(ValueError, match="could not decode"):
            _call(stub, _files(1))

    deletes = stub.client.files.delete.call_args_list
    orphan_calls = [c for c in deletes if c.kwargs.get("name", "").startswith("files/upload-")]
    assert len(orphan_calls) == 1, (
        f"a non-APIError poll exception (ValueError shape) must still "
        f"trigger orphan cleanup post-#84; got {len(orphan_calls)} deletes"
    )


def test_orphan_with_none_name_is_skipped_during_cleanup(monkeypatch):
    """``google.genai.types.File.name`` is typed Optional[str]. An
    orphan with ``name=None`` would cause ``files.delete(name=None)``
    to raise TypeError, which (with the broadened inner except) is
    swallowed — but the source explicitly skips the entry to avoid
    even attempting the delete. Pin the skip-guard."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "1")
    # Two orphans: file 0 has name=None (partial upload), file 1 names normally.
    stub = _make_stub(
        [["PROCESSING", "ACTIVE"], ["PROCESSING", "PROCESSING"]],
        orphan_names=[None, "files/upload-1"],
    )

    times = iter([0.0, 0.0, 1.5, 3.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError):
            _call(stub, _files(2))

    # Cleanup must have skipped the name=None orphan and delete only the named one.
    deletes = stub.client.files.delete.call_args_list
    # The pre-upload deletes use the human filename; orphan-cleanup uses
    # the handle name. Filter for handle-name deletes only.
    orphan_calls = [c for c in deletes if c.kwargs.get("name", "").startswith("files/")]
    delete_args = [c.kwargs.get("name") for c in orphan_calls]
    assert None not in delete_args, (
        f"orphan with name=None must NOT have files.delete(name=None) "
        f"attempted on it (post-#84 guard); got delete args {delete_args!r}"
    )


def test_typerror_during_orphan_delete_does_not_mask_original(monkeypatch):
    """The inner per-orphan ``except`` widened from
    ``genai.errors.APIError`` to bare ``Exception`` (#84). A TypeError
    during ``files.delete(...)`` (e.g. SDK signature changed, ``name``
    type drifted) must NOT mask the original poll exception."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "1")
    stub = _make_stub([["PROCESSING", "PROCESSING"]])

    # files.delete raises TypeError on every orphan-cleanup call.
    # The pre-upload delete (using human filename) is fine; orphan delete fails.
    def fake_delete(name=None):
        if name and name.startswith("files/upload-"):
            raise TypeError("simulated SDK signature drift on delete")
        return None
    stub.client.files.delete = MagicMock(side_effect=fake_delete)

    times = iter([0.0, 0.0, 2.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError):
            # ← Original timeout re-raises, NOT the cleanup TypeError.
            _call(stub, _files(1))


def test_value_error_subclass_during_poll_triggers_cleanup(monkeypatch):
    """Direct simulation of ``genai.errors.UnknownApiResponseError`` —
    the SDK class that motivated #84. The real class subclasses
    ``ValueError``, not ``APIError``. Pre-#84 cleanup would have been
    skipped; post-#84 broad except triggers it."""

    class _FakeUnknownResponseError(ValueError):
        """Mirrors google.genai.errors.UnknownApiResponseError's MRO."""

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "60")
    stub = _make_stub(
        [["PROCESSING", "PROCESSING"]],
        poll_raises=_FakeUnknownResponseError("SDK couldn't decode response"),
    )

    times = iter([0.0, 0.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(_FakeUnknownResponseError):
            _call(stub, _files(1))

    orphan_calls = [
        c for c in stub.client.files.delete.call_args_list
        if c.kwargs.get("name", "").startswith("files/upload-")
    ]
    assert len(orphan_calls) == 1


# ===========================================================================
# #85 — flux transport_error_cls narrowing
# ===========================================================================


def test_flux_http_transport_error_cls_is_connection_error():
    """Pin the post-#85 override: must be ``requests.ConnectionError``,
    NOT ``requests.RequestException``. The narrowing is what makes
    HttpClient's retry catch tuple stop matching the
    ``raise_for_status``-raised ``HTTPError`` (HTTPError is-a
    RequestException but NOT a ConnectionError) — fail-fast on 4xx."""
    from autonomous.ai.models.flux import _HTTP

    assert _HTTP.transport_error_cls is requests.ConnectionError, (
        f"post-#85 flux must use ConnectionError as transport_error_cls "
        f"to avoid the HTTPError-overlap retry bug; got "
        f"{_HTTP.transport_error_cls!r}"
    )


def test_flux_transport_error_cls_is_still_a_requestexception_subclass():
    """Downstream catch invariant: ``generate_image`` does
    ``except (requests.RequestException, ValueError, OSError)``. The
    narrowed override must still satisfy that catch — otherwise a
    transport-class wrap would bypass the downstream catch and crash
    the RQ task."""
    from autonomous.ai.models.flux import _HTTP

    assert issubclass(_HTTP.transport_error_cls, requests.RequestException), (
        f"transport_error_cls must remain a RequestException subclass "
        f"so generate_image's except clause continues to catch wrapped "
        f"transport failures; got {_HTTP.transport_error_cls!r}"
    )


def test_http_error_is_not_a_connection_error_subclass():
    """The whole point of #85: ``requests.HTTPError`` must NOT be a
    ``requests.ConnectionError`` subclass — that's what removes the
    retry-catch-tuple overlap that motivated the fix. Belt-and-
    suspenders against an upstream `requests` library change that
    accidentally reshuffles the exception hierarchy."""

    assert not issubclass(requests.HTTPError, requests.ConnectionError), (
        f"upstream `requests` library reshuffled its exception hierarchy "
        f"— HTTPError is now a ConnectionError subclass, which would "
        f"silently re-introduce the #85 retry bug. The flux narrowing "
        f"to ConnectionError no longer protects against the HTTPError "
        f"overlap. File an issue."
    )

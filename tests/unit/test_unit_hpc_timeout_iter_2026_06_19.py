"""PR #178 / Issue #177: bounded ``(connect, read)`` HPC timeout.

Independent second-perspective coverage. Goal of the source change is
that a stalled HPC backend (TCP connection ESTABLISHED but no bytes
returned) no longer pins an RQ worker indefinitely — it surfaces as
``HPCUnreachableError`` after the bounded read window, flows through
the existing transport-class retry budget, and gets logged.

The headline back-compat invariant pinned here is the derived-default
``hpc_read_timeout = env_int("HPC_READ_TIMEOUT", self.hpc_request_timeout)``
in ``Settings.__init__`` — three different "non-explicit-int" shapes
of HPC_READ_TIMEOUT (absent / empty string / malformed) all fall back
to whatever HPC_REQUEST_TIMEOUT produced rather than silently
downgrading to the field default. A future "tidy-up" refactor that
swaps the parser order or drops the empty-string branch of ``env_int``
would silently break legacy deployments that set HPC_REQUEST_TIMEOUT
high to absorb slow inference.

Sections:
- A — Field catalog declarations (3 entries: legacy, connect, read)
- B — Settings derived-default for ``hpc_read_timeout`` (5 cases)
- C — Settings ``hpc_connect_timeout`` (independent field)
- D — ``OpenAIClient._timeout`` is a tuple keyed on the live snapshot
- E — Tuple reaches ``_HTTP.post`` on both code paths (json + files)
- F — ``HttpClient.timeout`` accepts the tuple shape (type widening)
- G — HPCUnreachable translation wiring preserved post-#177
- H — Documentation pins (MIGRATIONS.md + configuration.md guide)
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Section A — Field catalog declarations
# ---------------------------------------------------------------------------


def _field(attr_name):
    """Look up a Field entry in the live _SPEC catalog by its ``attr`` slot."""
    from autonomous.config import _SPEC
    for f in _SPEC:
        if f.attr == attr_name:
            return f
    raise AssertionError(f"Field {attr_name!r} not in _SPEC")


class TestFieldCatalogDeclarations:
    def test_hpc_connect_timeout_field_declared(self):
        f = _field("hpc_connect_timeout")
        assert f.env == "HPC_CONNECT_TIMEOUT"
        assert f.kind == "int"
        assert f.default == 10
        assert f.group == "ai_hpc"

    def test_hpc_read_timeout_field_declared(self):
        f = _field("hpc_read_timeout")
        assert f.env == "HPC_READ_TIMEOUT"
        assert f.kind == "int"
        assert f.default == 120
        assert f.group == "ai_hpc"

    def test_legacy_hpc_request_timeout_retained_with_deprecated_marker(self):
        """Back-compat: the legacy single-knob field must remain in the
        catalog. Removing it would orphan the
        ``env_int("HPC_READ_TIMEOUT", self.hpc_request_timeout)`` fallback
        path. The DEPRECATED marker in the description signals operator-
        facing intent (also surfaces in the generated configuration guide).
        """
        f = _field("hpc_request_timeout")
        assert f.env == "HPC_REQUEST_TIMEOUT"
        assert f.default == 120
        assert "DEPRECATED" in f.description


# ---------------------------------------------------------------------------
# Section B — Settings derived-default for ``hpc_read_timeout``
# ---------------------------------------------------------------------------


class TestHpcReadTimeoutDerivedDefault:
    """The headline back-compat invariant: ``hpc_read_timeout`` inherits
    ``hpc_request_timeout`` whenever ``HPC_READ_TIMEOUT`` doesn't supply
    a parseable int. Three distinct env shapes (absent / empty / garbage)
    must all fall through to the legacy single-knob value.

    Building a fresh ``Settings()`` after ``monkeypatch.setenv`` is the
    cleanest hermetic surface — the module-level ``settings`` singleton
    is a snapshot from import time, but ``Settings()`` re-reads.
    """

    def test_absent_inherits_field_default_when_legacy_also_absent(
        self, monkeypatch
    ):
        from autonomous.config import Settings

        monkeypatch.delenv("HPC_READ_TIMEOUT", raising=False)
        monkeypatch.delenv("HPC_REQUEST_TIMEOUT", raising=False)
        s = Settings()
        # Both knobs absent: hpc_request_timeout falls to its 120 default,
        # hpc_read_timeout inherits via Settings.__init__'s derived path
        # and also lands at 120 — byte-identical pre-#177 behavior.
        assert s.hpc_request_timeout == 120
        assert s.hpc_read_timeout == 120

    def test_absent_HPC_READ_TIMEOUT_inherits_explicit_legacy_value(
        self, monkeypatch
    ):
        """The legacy deployment shape: operator set HPC_REQUEST_TIMEOUT
        to absorb slow inference. Post-#177, ``hpc_read_timeout`` must
        still pick that up — that's the back-compat promise."""
        from autonomous.config import Settings

        monkeypatch.delenv("HPC_READ_TIMEOUT", raising=False)
        monkeypatch.setenv("HPC_REQUEST_TIMEOUT", "900")
        s = Settings()
        assert s.hpc_request_timeout == 900
        assert s.hpc_read_timeout == 900

    def test_empty_HPC_READ_TIMEOUT_inherits_legacy_value(self, monkeypatch):
        """The most-likely misconfiguration shape — a templated env file
        (Docker, k8s) renders an empty string for an unset variable. The
        comment at ``Settings.__init__`` flags this case specifically as
        the reason ``env_int`` is preferred over ``env_str`` here.
        ``env_int`` returns the default on ``""`` (line 93 of config.py)."""
        from autonomous.config import Settings

        monkeypatch.setenv("HPC_READ_TIMEOUT", "")
        monkeypatch.setenv("HPC_REQUEST_TIMEOUT", "900")
        s = Settings()
        assert s.hpc_read_timeout == 900, (
            "empty-string HPC_READ_TIMEOUT must inherit HPC_REQUEST_TIMEOUT, "
            "not silently downgrade to the field default 120"
        )

    def test_explicit_HPC_READ_TIMEOUT_overrides_legacy_value(
        self, monkeypatch
    ):
        from autonomous.config import Settings

        monkeypatch.setenv("HPC_READ_TIMEOUT", "60")
        monkeypatch.setenv("HPC_REQUEST_TIMEOUT", "900")
        s = Settings()
        assert s.hpc_read_timeout == 60
        assert s.hpc_request_timeout == 900

    def test_malformed_HPC_READ_TIMEOUT_inherits_legacy_value(
        self, monkeypatch
    ):
        """``env_int`` falls back on parse failure (line 99 of config.py).
        Without this, a typo'd HPC_READ_TIMEOUT in an env file would
        silently dump to the field default 120 — masking the operator's
        intent. With this, the derived-default still flows from the
        legacy value."""
        from autonomous.config import Settings

        monkeypatch.setenv("HPC_READ_TIMEOUT", "not-an-int")
        monkeypatch.setenv("HPC_REQUEST_TIMEOUT", "900")
        s = Settings()
        assert s.hpc_read_timeout == 900


# ---------------------------------------------------------------------------
# Section C — ``hpc_connect_timeout`` (independent field, no inheritance)
# ---------------------------------------------------------------------------


class TestHpcConnectTimeout:
    def test_default_is_10(self, monkeypatch):
        from autonomous.config import Settings

        monkeypatch.delenv("HPC_CONNECT_TIMEOUT", raising=False)
        s = Settings()
        assert s.hpc_connect_timeout == 10

    def test_explicit_override(self, monkeypatch):
        from autonomous.config import Settings

        monkeypatch.setenv("HPC_CONNECT_TIMEOUT", "30")
        s = Settings()
        assert s.hpc_connect_timeout == 30

    def test_empty_string_falls_to_field_default(self, monkeypatch):
        """Connect timeout has NO derived-default — it's an independent
        field. An empty HPC_CONNECT_TIMEOUT falls back to the field
        default 10, not to ``HPC_REQUEST_TIMEOUT`` (deliberate asymmetry
        with ``hpc_read_timeout``)."""
        from autonomous.config import Settings

        monkeypatch.setenv("HPC_CONNECT_TIMEOUT", "")
        monkeypatch.setenv("HPC_REQUEST_TIMEOUT", "900")
        s = Settings()
        # Stays at 10 — not 900. This is intentional: a deployment that
        # raised HPC_REQUEST_TIMEOUT for slow inference must NOT also
        # widen the connect phase. That's the whole point of the split.
        assert s.hpc_connect_timeout == 10


# ---------------------------------------------------------------------------
# Section D — ``OpenAIClient._timeout`` shape on the live snapshot
# ---------------------------------------------------------------------------


class TestOpenAIClientTimeoutShape:
    def test_timeout_is_tuple_of_two_ints(self):
        """Pre-#177 was a single int from ``settings.hpc_request_timeout``.
        Post-#177 is a ``(connect, read)`` tuple — the ``requests``-native
        shape, fed directly through to the HTTP layer."""
        from autonomous.ai.models.openai_compat import OpenAIClient

        t = OpenAIClient._timeout
        assert isinstance(t, tuple), (
            f"OpenAIClient._timeout must be a tuple post-#177, got {type(t).__name__}"
        )
        assert len(t) == 2
        connect, read = t
        assert isinstance(connect, int)
        assert isinstance(read, int)

    def test_timeout_tracks_live_settings_snapshot(self):
        """The class attr is captured at module-load time from
        ``settings.hpc_connect_timeout`` and ``settings.hpc_read_timeout``.
        Pinning equality against the live snapshot catches a typo'd
        attribute name in the class-attr expression (e.g. accidentally
        swapping the two, or leaving one as the legacy ``hpc_request_timeout``)."""
        from autonomous.ai.models.openai_compat import OpenAIClient
        from autonomous.config import settings

        assert OpenAIClient._timeout == (
            settings.hpc_connect_timeout,
            settings.hpc_read_timeout,
        )


# ---------------------------------------------------------------------------
# Section E — Tuple actually reaches ``_HTTP.post`` on both code paths
# ---------------------------------------------------------------------------


def _make_openai_client():
    """Build an OpenAIClient instance without going through MongoEngine's
    descriptor machinery — priming ``_data`` etc. avoids the lazy DB
    connect on attribute access. Same pattern used in the per-call-model
    tests (#173)."""
    from autonomous.ai.models.openai_compat import OpenAIClient

    client = OpenAIClient.__new__(OpenAIClient)
    object.__setattr__(client, "_data", {
        "name": "test-agent",
        "instructions": "Be helpful.",
    })
    object.__setattr__(client, "_dynamic_fields", {})
    object.__setattr__(client, "_changed_fields", [])
    object.__setattr__(client, "_initialised", True)
    object.__setattr__(client, "_created", False)
    return client


class _FakeResponse:
    """Minimal stand-in for ``requests.Response``. ``_post`` returns
    whatever ``_HTTP.post`` returns; the caller (``_chat``, etc.) reads
    ``.json()`` and ``.text``. We never reach those in these tests —
    we just verify the timeout kwarg was forwarded."""
    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}
    text = "ok"


class TestTupleReachesHttpPost:
    def test_json_body_path_forwards_timeout_tuple(self, monkeypatch):
        """``_post`` json-body branch (chat, embeddings) — must forward
        the class-attr ``_timeout`` tuple to ``_HTTP.post(timeout=)``."""
        from autonomous.ai.models import openai_compat as oc

        captured = {}

        def fake_post(url, *, headers, json=None, timeout=None, **kw):
            captured["url"] = url
            captured["timeout"] = timeout
            captured["json"] = json
            return _FakeResponse()

        monkeypatch.setattr(oc._HTTP, "post", fake_post)
        # Use a sentinel tuple that can't be confused with the default.
        monkeypatch.setattr(oc.OpenAIClient, "_timeout", (3, 7))
        monkeypatch.setattr(oc.OpenAIClient, "_base_url", "http://hpc.test")

        client = _make_openai_client()
        client._post("/v1/chat/completions", json_body={"model": "x"})

        assert captured["timeout"] == (3, 7)
        assert captured["url"] == "http://hpc.test/v1/chat/completions"
        assert captured["json"] == {"model": "x"}

    def test_files_path_forwards_timeout_tuple(self, monkeypatch):
        """``_post`` multipart branch (transcriptions) — same forwarding
        contract. A refactor of the two branches that drops ``timeout=``
        on one would slip through any single-branch test."""
        from autonomous.ai.models import openai_compat as oc

        captured = {}

        def fake_post(url, *, headers, files=None, data=None, timeout=None, **kw):
            captured["url"] = url
            captured["timeout"] = timeout
            captured["files"] = files
            return _FakeResponse()

        monkeypatch.setattr(oc._HTTP, "post", fake_post)
        monkeypatch.setattr(oc.OpenAIClient, "_timeout", (3, 7))
        monkeypatch.setattr(oc.OpenAIClient, "_base_url", "http://hpc.test")

        client = _make_openai_client()
        client._post(
            "/v1/audio/transcriptions",
            files={"file": ("a.wav", b"...", "audio/wav")},
            data={"model": "whisper-1"},
        )

        assert captured["timeout"] == (3, 7)


# ---------------------------------------------------------------------------
# Section F — ``HttpClient.timeout`` type widening
# ---------------------------------------------------------------------------


class TestHttpClientTimeoutTypeWidening:
    def test_init_accepts_tuple_timeout_and_roundtrips(self):
        """A tuple-shaped ``timeout=`` must pass ``__init__`` and survive
        as ``self.timeout`` unchanged. Pre-#177 the contract was a single
        float; #177 widens it for the HPC client (and any future adapter
        that wants the split — the docstring at the shared layer makes
        that the recommended shape)."""
        from autonomous.http.client import HttpClient

        c = HttpClient(timeout=(2.5, 90.0))
        assert c.timeout == (2.5, 90.0)

    def test_init_still_accepts_legacy_scalar_timeout(self):
        """The widening is additive — float is still valid. A migration
        that forgot a legacy adapter (Gemini uses scalar) must not
        regress here."""
        from autonomous.http.client import HttpClient

        c = HttpClient(timeout=30.0)
        assert c.timeout == 30.0

    def test_request_signature_declares_tuple_in_annotation(self):
        """Type-annotation pin. The IDE / mypy contract for adapter code
        depends on ``request()`` declaring the tuple shape as legal. A
        refactor that revertis the annotation back to ``float | None``
        would re-introduce a typing-time error for the HPC client without
        any runtime signal."""
        from autonomous.http.client import HttpClient

        sig = inspect.signature(HttpClient.request)
        ann = sig.parameters["timeout"].annotation
        # Annotation is a string at runtime under `from __future__ import
        # annotations`, but we can match either string or actual type.
        text = str(ann)
        assert "tuple[float, float]" in text, (
            f"HttpClient.request timeout annotation must accept the "
            f"(connect, read) tuple shape; got: {text!r}"
        )


# ---------------------------------------------------------------------------
# Section G — HPCUnreachableError translation wiring preserved
# ---------------------------------------------------------------------------


class TestHpcUnreachableTranslationWiring:
    """The headline behavior of #177 — a stalled HPC backend surfaces as
    ``HPCUnreachableError``, not a multi-hour silent hang — depends on
    two pieces of wiring that ARE NOT what #177 introduces: the
    ``_HTTP`` instance's ``transport_error_cls`` and the requests-class
    that ``ReadTimeout`` belongs to. #177 widens the timeout shape but
    only delivers the headline behavior if these stay intact. Pin them
    explicitly — a future "tidy-up" that swaps ``transport_error_cls``
    or carves ``ReadTimeout`` into the non-transport set would silently
    re-create the silent-wedge bug."""

    def test_http_transport_error_cls_is_hpc_unreachable(self):
        """When ``_HTTP.post`` catches a transport-class exception
        (``ReadTimeout`` is a ``RequestException`` subclass), it raises
        ``transport_error_cls`` — which here must be HPCUnreachableError
        so the existing ``[HPC-UNREACHABLE]`` log + retry path fires."""
        from autonomous.ai.models.openai_compat import _HTTP, HPCUnreachableError

        assert _HTTP.transport_error_cls is HPCUnreachableError

    def test_read_timeout_is_not_carved_out_as_non_transport(self):
        """``HttpClient`` re-raises non-transport requests-exceptions raw
        (without wrapping them as ``transport_error_cls``). If
        ``ReadTimeout`` were ever added to that carve-out, the
        bounded-read wedge would surface as a bare ``ReadTimeout``
        instead of HPCUnreachableError — bypassing the [HPC-UNREACHABLE]
        log line and the retry path that was the whole point of #177."""
        import requests

        from autonomous.ai.models.openai_compat import _HTTP

        # _non_transport_exceptions is the per-instance combined tuple
        # of module-level + extra non-transport classes (see HttpClient.__init__).
        non_transport = _HTTP._non_transport_exceptions
        # ReadTimeout must NOT be in the carve-out — it's a transport-class
        # failure and should wrap into HPCUnreachableError.
        for exc_cls in non_transport:
            assert not issubclass(requests.exceptions.ReadTimeout, exc_cls), (
                f"ReadTimeout would be matched by {exc_cls.__name__} in the "
                f"non-transport carve-out — that would bypass the "
                f"HPCUnreachableError translation #177 depends on."
            )


# ---------------------------------------------------------------------------
# Section H — Documentation pins
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestMigrationsAndConfigurationDocsPin:
    def test_migrations_md_documents_177(self):
        """Operator-facing consumers grep MIGRATIONS.md for the issue
        number after seeing a behavior change. Removing the entry would
        leave a deprecation in flight (legacy HPC_REQUEST_TIMEOUT) with
        no migration recipe."""
        body = (REPO_ROOT / "MIGRATIONS.md").read_text()
        assert "(#177)" in body
        # Section heading lives at H3 in the "Unreleased" block.
        assert "Bounded `(connect, read)` timeouts on the HPC HTTP client (#177)" in body
        # The migration recipe (the explicit before/after env block) is
        # the actionable content; pin one distinctive token from it.
        assert "HPC_CONNECT_TIMEOUT=10" in body
        assert "HPC_READ_TIMEOUT=900" in body

    def test_configuration_guide_marks_legacy_deprecated(self):
        """The configuration guide is generated from ``_SPEC``'s
        ``description`` field plus a hand-edited field table. The DEPRECATED
        marker must surface here so operators reading the guide (not
        MIGRATIONS) see the split."""
        body = (REPO_ROOT / "docs" / "guides" / "configuration.md").read_text()
        # Legacy row must show DEPRECATED.
        assert "HPC_REQUEST_TIMEOUT" in body
        assert "**DEPRECATED**" in body
        # New rows must be present with #177 markers.
        assert "HPC_CONNECT_TIMEOUT" in body
        assert "HPC_READ_TIMEOUT" in body


# ---------------------------------------------------------------------------
# Section I — Version bump pin (ride-along inseparability)
# ---------------------------------------------------------------------------


class TestVersionBumpPin:
    def test_version_bumped_to_0_3_165(self):
        """PR #178 bumps the patch version. Locking the literal string
        catches an accidental revert during a back-merge resolve, which
        would silently re-publish 0.3.164 on the next ``release.sh``
        and break the storyteller-side ``requirements.txt`` pin contract."""
        import autonomous

        assert autonomous.__version__ == "0.3.165", (
            f"PR #178 bumps to 0.3.165; got {autonomous.__version__!r}"
        )

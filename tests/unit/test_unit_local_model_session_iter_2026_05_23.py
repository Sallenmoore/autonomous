"""Independent coverage for the local_model HTTP-seam contract.

History
-------
PR #117 retargeted the integration suite's monkeypatches from
``autonomous.ai.models.local_model.requests.post`` to
``autonomous.ai.models.local_model._SESSION.post`` (a ``requests.Session``).

PR #50 slice C (2026-06-10) migrated ``local_model`` to ``HttpClient``,
replacing the bare ``_SESSION`` with module-level
``_HTTP = HttpClient(timeout=None, max_attempts=1)`` and updating every
``_SESSION.post(...)`` call site to ``_HTTP.post(...)``. The ``_SESSION``
name was **dropped** rather than aliased — ``HttpClient`` routes through
``session.request("POST", ...)`` rather than ``session.post(...)``, so an
alias would have silently failed to intercept the migrated calls and a
stale ``_SESSION.post`` patch would have become a no-op.

This file pins the post-slice-C contract: ``_HTTP`` exists, is an
``HttpClient``, every production POST goes through it (no bare
``requests.post(`` regression), and the integration suite's patch target
references the new seam.

Hermetic by design: no network, no AutoModel save, no Redis.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from autonomous.ai.models import local_model
from autonomous.http import HttpClient


REPO = Path(__file__).resolve().parents[2]
LOCAL_MODEL_SRC = REPO / "src" / "autonomous" / "ai" / "models" / "local_model.py"


class TestHttpContract:
    """The patch target the integration suite and unit-test fixtures
    depend on. If a future refactor renames ``_HTTP`` or swaps the type,
    the dependent patches silently no-op — catch that here."""

    def test_http_attribute_exists(self):
        """The migrated seam must exist by name."""
        assert hasattr(local_model, "_HTTP"), (
            "post-#50-slice-C: module-level _HTTP is the patch target"
        )

    def test_http_is_httpclient_instance(self):
        """It must be ``HttpClient`` specifically — the dependent
        fixtures use ``monkeypatch.setattr(local_model._HTTP, 'post', ...)``,
        which expects an HttpClient-compatible attribute surface."""
        assert isinstance(local_model._HTTP, HttpClient), (
            f"_HTTP must be an HttpClient; got: "
            f"{type(local_model._HTTP).__name__}"
        )

    def test_http_post_is_callable(self):
        """The exact attribute the patches replace."""
        assert callable(local_model._HTTP.post)

    def test_http_get_is_callable(self):
        """Symmetric — local_model could grow GET call sites in future."""
        assert callable(local_model._HTTP.get)


class TestProductionCallSitesUseHttp:
    """Source-grep assertions: if a future PR introduces a bare
    ``requests.post(...)`` call OR reverts to a stale ``_SESSION.post(...)``
    call site in local_model.py, the patch target becomes a lie and tests
    silently bypass the production path (or worse, fail with opaque
    ``AttributeError: module has no attribute _SESSION``).
    """

    @pytest.fixture(scope="class")
    def source(self):
        return LOCAL_MODEL_SRC.read_text(encoding="utf-8")

    def test_no_bare_requests_post_calls(self, source):
        """``requests.post(...)`` must not appear as a call site — all
        outbound POSTs should go through ``_HTTP.post`` for pooling,
        timeout, and uniform patchability.

        We allow the literal string ``requests.post`` to appear in a
        comment or docstring (e.g. explaining the migration history), so
        we match only the call-form ``requests.post(``.
        """
        offenders = re.findall(r"\brequests\.post\s*\(", source)
        assert not offenders, (
            "local_model.py has bare requests.post(...) call sites — "
            "they should be _HTTP.post(...) post-#50 slice C so the "
            "integration and unit-test patches actually hit them."
        )

    def test_no_session_post_calls(self, source):
        """Symmetric guard for the pre-slice-C call form. A cherry-pick
        from a stale branch or a manual edit could re-introduce a bare
        ``_SESSION.post(`` call against a non-existent symbol."""
        offenders = re.findall(r"\b_SESSION\.post\s*\(", source)
        assert not offenders, (
            "local_model.py has stale _SESSION.post(...) call sites — "
            "_SESSION was removed in #50 slice C; migrate to _HTTP.post(...)."
        )

    def test_http_post_is_actually_called_in_source(self, source):
        """Sanity: at least one ``_HTTP.post(`` call site exists.
        Without this, our patch target is correct but unused — which
        would mean the integration tests are also not exercising the
        production path."""
        assert re.search(r"\b_HTTP\.post\s*\(", source), (
            "Expected at least one _HTTP.post(...) call in local_model.py"
        )


class TestHttpIsModuleScoped:
    """A per-call HttpClient would defeat the connection pooling rationale
    that the migration preserved from the pre-slice-C ``_SESSION``. Make
    sure ``_HTTP`` is a single module-level singleton, not a factory."""

    def test_http_is_not_a_function(self):
        assert not inspect.isfunction(local_model._HTTP)
        assert not inspect.ismethod(local_model._HTTP)

    def test_http_identity_is_stable(self):
        """Accessing _HTTP twice returns the same object — and so does
        ._HTTP.session (the requests.Session HttpClient holds internally
        for connection pooling)."""
        a = local_model._HTTP
        b = local_model._HTTP
        assert a is b
        # Pool-reuse contract is on the internal Session — ensure THAT
        # is also stable, not just _HTTP itself.
        assert a.session is b.session


class TestIntegrationTestPatchTargets:
    """The integration test file must use the new ``_HTTP.post`` patch
    target everywhere. If a future revert or a copy-paste from old
    documentation reintroduces the bare ``requests.post`` or the
    pre-slice-C ``_SESSION.post`` target, the integration tests silently
    bypass the production call site (the patch lands on an unused /
    nonexistent attribute) and either pass against a mock that production
    never hits OR fail with opaque AttributeErrors. Catching that here
    means we don't have to wait for the integration suite to surface it."""

    INT_TEST_SRC = REPO / "tests" / "integration" / "test_int_ai.py"

    @pytest.fixture(scope="class")
    def int_test_src(self):
        assert self.INT_TEST_SRC.exists(), (
            "tests/integration/test_int_ai.py missing"
        )
        return self.INT_TEST_SRC.read_text(encoding="utf-8")

    def test_no_bare_requests_post_patch_target(self, int_test_src):
        """The original patch target PR #117 retired."""
        offenders = re.findall(
            r'["\']autonomous\.ai\.models\.local_model\.requests\.post["\']',
            int_test_src,
        )
        assert not offenders, (
            "Integration tests still patch the retired "
            "'autonomous.ai.models.local_model.requests.post' target."
        )

    def test_no_stale_session_post_patch_target(self, int_test_src):
        """The pre-slice-C patch target #50 slice C migrated away from."""
        offenders = re.findall(
            r'["\']autonomous\.ai\.models\.local_model\._SESSION\.post["\']',
            int_test_src,
        )
        assert not offenders, (
            "Integration tests still patch the pre-#50-slice-C "
            "'autonomous.ai.models.local_model._SESSION.post' target — "
            "migrate to '_HTTP.post' (the HttpClient seam)."
        )

    def test_uses_http_post_patch_target(self, int_test_src):
        """Sanity: the new target appears at least once (otherwise the
        integration suite either patches something else or stopped
        patching local_model HTTP at all)."""
        hits = re.findall(
            r'["\']autonomous\.ai\.models\.local_model\._HTTP\.post["\']',
            int_test_src,
        )
        assert hits, (
            "Integration tests don't patch _HTTP.post anywhere — "
            "expected at least one usage post-#50 slice C."
        )

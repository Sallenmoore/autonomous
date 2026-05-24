"""Independent coverage for PR #117 (local_model._SESSION patch target).

PR #117 retargeted the integration suite's monkeypatches from
``autonomous.ai.models.local_model.requests.post`` to
``autonomous.ai.models.local_model._SESSION.post``.

The integration tests now depend on ``local_model._SESSION`` being a
``requests.Session`` instance whose ``.post`` is the call site that
production code uses. These hermetic unit tests pin that contract so a
silent refactor (renaming ``_SESSION``, moving back to module-level
``requests.post``, swapping in a different HTTP library) trips the unit
gate immediately instead of cascading into N integration failures with
opaque ``AttributeError: module has no attribute _SESSION`` messages.

Hermetic by design: no network, no AutoModel save, no Redis."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
import requests

from autonomous.ai.models import local_model


REPO = Path(__file__).resolve().parents[2]
LOCAL_MODEL_SRC = REPO / "src" / "autonomous" / "ai" / "models" / "local_model.py"


class TestSessionContract:
    def test_session_attribute_exists(self):
        """The patch target the integration suite depends on."""
        assert hasattr(local_model, "_SESSION")

    def test_session_is_requests_session_instance(self):
        """It must be a requests.Session (not just any object) — the
        integration tests monkeypatch it expecting Session semantics."""
        assert isinstance(local_model._SESSION, requests.Session)

    def test_session_post_is_callable(self):
        """The exact attribute the patches replace."""
        assert callable(local_model._SESSION.post)


class TestProductionCallSitesUseSession:
    """Source-grep assertions: if a future PR introduces a bare
    ``requests.post(...)`` call in local_model.py, the patch target
    becomes a lie and integration tests will pass while production
    silently bypasses any retries / pooling baked into _SESSION.
    """

    @pytest.fixture(scope="class")
    def source(self):
        return LOCAL_MODEL_SRC.read_text(encoding="utf-8")

    def test_no_bare_requests_post_calls(self, source):
        """``requests.post(...)`` must not appear as a call site — all
        outbound POSTs should go through ``_SESSION.post`` for pooling
        and uniform patchability.

        We allow the literal string ``requests.post`` to appear in a
        comment or docstring (e.g. explaining the migration), so we
        match only the call-form ``requests.post(``.
        """
        offenders = re.findall(r"\brequests\.post\s*\(", source)
        assert not offenders, (
            "local_model.py still has bare requests.post(...) call sites — "
            "they should be _SESSION.post(...) so the integration patches hit them."
        )

    def test_session_post_is_actually_called_in_source(self, source):
        """Sanity: at least one ``_SESSION.post(`` call site exists.
        Without this, our patch target is correct but unused — which
        would mean the integration tests are also not exercising the
        production path."""
        assert re.search(r"\b_SESSION\.post\s*\(", source), (
            "Expected at least one _SESSION.post(...) call in local_model.py"
        )


class TestSessionIsModuleScoped:
    """A per-call Session would defeat the connection pooling the PR
    description cites as the rationale for this migration. Make sure
    _SESSION is a single module-level singleton, not a factory."""

    def test_session_is_not_a_function(self):
        assert not inspect.isfunction(local_model._SESSION)
        assert not inspect.ismethod(local_model._SESSION)

    def test_session_identity_is_stable(self):
        """Accessing _SESSION twice returns the same object."""
        a = local_model._SESSION
        b = local_model._SESSION
        assert a is b


class TestIntegrationTestPatchTargets:
    """Ties to PR #117's actual diff: the integration test file must use
    the new ``_SESSION.post`` patch target everywhere. If a future revert
    or a copy-paste from old documentation reintroduces the bare
    ``requests.post`` target, the integration tests silently bypass the
    production call site (the patch lands on an unused attribute) and
    pass against a mock that production never hits. Catching that here
    means we don't have to wait for the integration suite to surface it
    as opaque assertion failures."""

    INT_TEST_SRC = REPO / "tests" / "integration" / "test_int_ai.py"

    @pytest.fixture(scope="class")
    def int_test_src(self):
        assert self.INT_TEST_SRC.exists(), (
            "tests/integration/test_int_ai.py missing"
        )
        return self.INT_TEST_SRC.read_text(encoding="utf-8")

    def test_no_bare_requests_post_patch_target(self, int_test_src):
        """The literal patch target string the PR retired."""
        offenders = re.findall(
            r'["\']autonomous\.ai\.models\.local_model\.requests\.post["\']',
            int_test_src,
        )
        assert not offenders, (
            "Integration tests still patch the retired "
            "'autonomous.ai.models.local_model.requests.post' target — "
            "PR #117 retargeted them to _SESSION.post."
        )

    def test_uses_session_post_patch_target(self, int_test_src):
        """Sanity: the new target appears at least once (otherwise the
        integration suite either patches something else or stopped
        patching local_model HTTP at all)."""
        hits = re.findall(
            r'["\']autonomous\.ai\.models\.local_model\._SESSION\.post["\']',
            int_test_src,
        )
        assert hits, (
            "Integration tests don't patch _SESSION.post anywhere — "
            "expected at least one usage after PR #117."
        )

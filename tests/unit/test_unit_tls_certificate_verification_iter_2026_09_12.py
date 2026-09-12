"""Independent coverage for PR #257 / issue #256 — TLS certificate
verification on git clone / fetch / push.

``GHRemoteCallbacks`` used to override ``certificate_check`` with a bare
``return True``, which tells libgit2 to accept **any** certificate from
**any** host. The same callbacks object's ``credentials()`` hands a
``GITHUB_PAT`` to that peer, so the token rode a connection whose peer was
never authenticated — on every ``GHRepo`` clone (``:20``), fetch (``:57``)
and push (``:114``), shipped as the ``autonomous-app[github]`` extra.

The fix deletes the override, so ``pygit2.RemoteCallbacks.certificate_check``
(which raises ``Passthrough``) is inherited and libgit2 does its own
validation.

The property is pinned from four independent angles, because a refactor
could reintroduce the bypass in a shape any single angle would miss:

1. **Behavioral** — the callback never *answers* "accept" for a host
   libgit2 flagged invalid. This holds no matter how the class is
   structured, so it survives a rewrite that reintroduces an override.
2. **Structural** — the subclass defines no ``certificate_check`` of its
   own and the attribute resolves to the pygit2 base implementation.
3. **Per-instance** — ``pygit2.RemoteCallbacks.__init__`` accepts a
   ``certificate_check=`` kwarg that *assigns onto the instance*, which
   would shadow the class without touching ``GHRemoteCallbacks.__dict__``.
   A constructed instance must carry no such attribute.
4. **Package-wide** — an AST guard over every shipped module, so the next
   TLS bypass (here, or in a module nobody has written yet) fails this
   suite instead of shipping. It catches the defect *class*, not just this
   instance.

Plus two controls that the fix must not have broken: ``credentials()``
still returns the expected ``UserPass``, and the class is still a usable
``pygit2.RemoteCallbacks`` subclass so ``GHRepo``'s three call sites still
accept it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pygit2
import pytest

from autonomous.apis.version_control import GHRemoteCallbacks


SRC = Path(__file__).resolve().parents[2] / "src" / "autonomous"

#: Returned by :func:`_answer` when the callback deferred to libgit2 rather
#: than answering itself. Distinct from ``None``/``False``, which are things
#: a callback could actually return.
DEFERRED = object()


def _answer(callbacks, valid: bool, host: bytes):
    """What the callback *answers* for ``(valid, host)``.

    ``DEFERRED`` if it raised ``Passthrough`` (libgit2 decides — the secure
    outcome), otherwise whatever it returned. Deliberately does not care
    *how* the answer is produced, so this stays honest across refactors.
    """
    try:
        return callbacks.certificate_check(None, valid, host)
    except pygit2.Passthrough:
        return DEFERRED


@pytest.fixture
def callbacks(monkeypatch):
    """A ``GHRemoteCallbacks`` built against known credentials.

    The constructor reads ``GITHUB_USERNAME`` / ``GITHUB_PAT`` from the
    environment, so pin them rather than inheriting the developer's real
    token into the test.
    """
    monkeypatch.setenv("GITHUB_USERNAME", "octocat")
    monkeypatch.setenv("GITHUB_PAT", "ghp_unit_test_token")
    return GHRemoteCallbacks()


# --------------------------------------------------------------------------
# 1. Behavioral: never answers "accept" for a certificate libgit2 rejected.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [b"github.com", b"evil.example.com", b"git.internal.corp", b""],
)
def test_invalid_certificate_is_never_accepted(callbacks, host):
    """``valid=False`` means libgit2 already judged the cert bad.

    Answering ``True`` there is exactly the #256 defect: it overrules
    libgit2 and hands the PAT to an unauthenticated peer. The callback must
    either defer or decline — for every host, including github.com itself.
    """
    answer = _answer(callbacks, False, host)
    assert answer is not True, (
        f"certificate_check accepted an invalid certificate for {host!r} "
        "— TLS verification is bypassed (issue #256)"
    )
    assert not answer or answer is DEFERRED, (
        f"certificate_check returned a truthy {answer!r} for an invalid "
        f"certificate from {host!r}"
    )


@pytest.mark.parametrize("valid", [True, False])
def test_certificate_decision_is_deferred_to_libgit2(callbacks, valid):
    """The decision belongs to libgit2, not to this class.

    ``Passthrough`` is pygit2's "I have no opinion, use your own
    validation" signal. Pinning it for ``valid=True`` as well as
    ``valid=False`` catches a reintroduced override that only *looks*
    conditional — the class must not be in the trust-decision business at
    all.
    """
    assert _answer(callbacks, valid, b"github.com") is DEFERRED


# --------------------------------------------------------------------------
# 2. Structural: no override on the class.
# --------------------------------------------------------------------------


def test_subclass_defines_no_certificate_check_override():
    assert "certificate_check" not in GHRemoteCallbacks.__dict__, (
        "GHRemoteCallbacks re-declared certificate_check; the #256 fix is "
        "the absence of that override"
    )


def test_certificate_check_resolves_to_the_pygit2_base_implementation():
    assert (
        GHRemoteCallbacks.certificate_check
        is pygit2.RemoteCallbacks.certificate_check
    )


# --------------------------------------------------------------------------
# 3. Per-instance: the constructor kwarg evasion.
# --------------------------------------------------------------------------


def test_instance_carries_no_certificate_check_attribute(callbacks):
    """``RemoteCallbacks(certificate_check=...)`` assigns onto the instance.

    So ``GHRemoteCallbacks.__init__`` could reintroduce the bypass by
    calling ``super().__init__(certificate_check=lambda *a: True)`` and the
    class-level assertions above would still pass. Assert on the *result*
    (nothing shadowing the inherited method) rather than on the mechanism,
    so any route to an instance attribute is covered.
    """
    assert "certificate_check" not in vars(callbacks), (
        "a certificate_check was assigned onto the instance, shadowing "
        "pygit2's validated default"
    )
    assert callbacks.certificate_check.__func__ is (
        pygit2.RemoteCallbacks.certificate_check
    )


# --------------------------------------------------------------------------
# Controls: the fix must not have broken auth or the callbacks contract.
# --------------------------------------------------------------------------


def test_credentials_still_returns_userpass_from_env(callbacks):
    """Removing the TLS bypass must not disturb authentication."""
    credential = callbacks.credentials(
        "https://github.com/Sallenmoore/autonomous.git", "octocat", 0
    )
    assert isinstance(credential, pygit2.UserPass)
    assert credential.credential_tuple == ("octocat", "ghp_unit_test_token")


def test_still_a_usable_remote_callbacks_subclass(callbacks):
    """``GHRepo`` passes this object to ``clone_repository`` / ``fetch`` /
    ``push``, all of which type-check it as a ``RemoteCallbacks``."""
    assert issubclass(GHRemoteCallbacks, pygit2.RemoteCallbacks)
    assert isinstance(callbacks, pygit2.RemoteCallbacks)


# --------------------------------------------------------------------------
# 4. Package-wide guard: no TLS bypass anywhere in the shipped package.
# --------------------------------------------------------------------------


def _shipped_modules():
    return sorted(SRC.rglob("*.py"))


def _tls_bypasses(tree: ast.AST) -> list[str]:
    """Every TLS-verification bypass in one parsed module.

    AST rather than text search on purpose: ``GHCallbacks.py`` carries a
    NOTE comment quoting the old ``certificate_check`` and its ``True``, and
    a grep-based guard would flag the very comment that documents the fix.
    """
    found = []
    for node in ast.walk(tree):
        # requests/httpx: verify=False disables certificate validation.
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "verify" and (
                    isinstance(kw.value, ast.Constant) and kw.value.value is False
                ):
                    found.append(f"line {node.lineno}: verify=False")
        # ssl._create_unverified_context() and friends.
        if isinstance(node, ast.Attribute) and node.attr.startswith(
            "_create_unverified"
        ):
            found.append(f"line {node.lineno}: ssl.{node.attr}")
        # pygit2: a certificate_check that answers truthy unconditionally.
        if isinstance(node, ast.FunctionDef) and node.name == "certificate_check":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Return)
                    and isinstance(sub.value, ast.Constant)
                    and sub.value.value
                ):
                    found.append(
                        f"line {sub.lineno}: certificate_check returns "
                        f"{sub.value.value!r}"
                    )
    return found


def test_no_tls_verification_bypass_in_the_shipped_package():
    """The defect class, not just the #256 instance.

    Everything under ``src/autonomous/`` is published to PyPI, so a bypass
    in any module is a bypass in a consumer's process. If a self-signed
    remote ever genuinely needs one, it has to be an explicit, loudly
    logged opt-in — and this test is where that decision gets made
    deliberately instead of by accident.
    """
    offenders = {}
    for module in _shipped_modules():
        bypasses = _tls_bypasses(ast.parse(module.read_text(encoding="utf-8")))
        if bypasses:
            offenders[str(module.relative_to(SRC))] = bypasses

    assert not offenders, f"TLS verification bypass in shipped package: {offenders}"


def test_tls_bypass_guard_actually_detects_a_bypass():
    """Self-check: a guard that can't fail proves nothing.

    Pins that :func:`_tls_bypasses` catches all three shapes, so a green
    :func:`test_no_tls_verification_bypass_in_the_shipped_package` means
    "no bypass" rather than "guard quietly stopped working".
    """
    sample = (
        "import ssl, requests\n"
        "class C:\n"
        "    def certificate_check(self, certificate, valid, host):\n"
        "        return True\n"
        "def f():\n"
        "    requests.get('https://x', verify=False)\n"
        "    return ssl._create_unverified_context()\n"
    )
    assert len(_tls_bypasses(ast.parse(sample))) == 3

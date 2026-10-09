"""Package-wide TLS-verification-bypass guard, carried over from the
deleted ``test_unit_tls_certificate_verification_iter_2026_09_12.py``.

PR #285 (#282) removed ``apis/version_control`` and with it that file,
whose per-class tests targeted ``GHRemoteCallbacks``. Its last two tests
were not about that class: they scan everything under ``src/autonomous/``
(all of it ships to PyPI) for TLS bypasses. They are kept here unchanged,
minus the pygit2 / GHRemoteCallbacks imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "autonomous"


def _shipped_modules():
    return sorted(SRC.rglob("*.py"))


def _tls_bypasses(tree: ast.AST) -> list[str]:
    """Every TLS-verification bypass in one parsed module.

    AST rather than text search on purpose: a module may carry a
    comment quoting an old bypass, and
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

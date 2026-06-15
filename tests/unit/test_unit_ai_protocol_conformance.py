"""Conformance test for ``AIModelProtocol`` — slice 1 of #47.

Verifies every adapter in ``BaseAgent.MODEL_REGISTRY`` declares each
canonical method (``generate_json``, ``generate_transcription``,
``generate_image``, ``upscale_image``) with the canonical kwarg names
the dispatch layer (``jsonagent.py``, ``imageagent.py``, etc.) sends.

Known drift is enumerated as ``pytest.mark.xfail(strict=True, ...)``
parametrize entries. Each xfail reason names the slice that will fix
it. ``strict=True`` means an XPASS turns into an error — so the
moment an adapter is fixed, the test FAILS, signaling "remove this
xfail." That gates progress: you can't half-migrate an adapter and
leave the conformance test silently masking the rest.

This slice does NOT change any adapter behavior. Slices 2-5 will
flip xfails to passes one at a time.
"""

from __future__ import annotations

import inspect

import pytest

from autonomous.ai.models.flux import FluxAIModel
from autonomous.ai.models.gemini import GeminiAIModel
from autonomous.ai.models.local_model import LocalAIModel
from autonomous.ai.models.mock_model import MockAIModel
from autonomous.ai.models.openai_compat import OpenAIClient
from autonomous.ai.protocol import AIModelProtocol, NotSupportedByProvider

ADAPTERS: dict[str, type] = {
    "local": LocalAIModel,
    "gemini": GeminiAIModel,
    "openai_compat": OpenAIClient,
    "flux": FluxAIModel,
    "mock": MockAIModel,
}

METHODS: tuple[str, ...] = (
    "generate_json",
    "generate_transcription",
    "generate_image",
    "upscale_image",
)


def _canonical_params(method_name: str) -> list[str]:
    """Return the canonical kwarg names from the Protocol method."""
    proto_method = getattr(AIModelProtocol, method_name)
    sig = inspect.signature(proto_method)
    return [name for name in sig.parameters if name != "self"]


def _has_param(sig: inspect.Signature, name: str) -> bool:
    """True if sig declares ``name`` explicitly OR accepts ``**kwargs``.

    ``**kwargs`` is "accepts anything keyword-named" — adapters using
    it (mock, openai_compat.generate_transcription) trivially accept
    every canonical kwarg. The trade-off is the contract isn't
    declared at the signature; that's a separate concern handled by
    the "declares no explicit params" check in
    :func:`_check_conformance`.
    """
    if name in sig.parameters:
        return True
    return any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )


def _check_conformance(
    adapter_cls: type, method_name: str
) -> tuple[bool, str | None]:
    """Return ``(conforms, reason_if_not)`` for one adapter×method pair."""
    method = getattr(adapter_cls, method_name, None)
    if method is None:
        return False, f"method missing from {adapter_cls.__name__}"

    sig = inspect.signature(method)

    # Explicit-contract check: an adapter declaring only ``*args`` and
    # ``**kwargs`` (and ``self``) technically accepts every canonical
    # kwarg, but tells the caller nothing — and routes every
    # mismatch into the body where it raises NotImplementedError.
    # Slice 2 replaces these with explicit signatures + typed
    # NotSupportedByProvider.
    declared = [
        p for p in sig.parameters.values()
        if p.name != "self"
        and p.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
    ]
    if not declared:
        return False, "declares no explicit params (*args/**kwargs only)"

    canonical = _canonical_params(method_name)
    missing = [name for name in canonical if not _has_param(sig, name)]
    if missing:
        return False, f"missing canonical kwarg(s): {missing}"

    return True, None


# Known drift — each entry MUST cite the slice that will flip it green.
# ``strict=True`` xfails turn into errors on XPASS, so the moment an
# adapter is fixed, the test fails as "stale entry, remove this line."
#
# Slice 2 landed flux's unsupported declarations and openai_compat's
# image methods → those entries removed. Slice 3 is next: gemini's
# generate_json kwarg unification.
_KNOWN_DRIFT: dict[tuple[str, str], str] = {
    ("gemini", "generate_json"): (
        "#47 slice 3 — gemini takes (message, function, "
        "additional_instructions, ...); needs to expose canonical "
        "kwargs and do function-dict translation inside the adapter"
    ),
}


def _params() -> list:
    """Build pytest.param entries with strict xfails on known-drift cases."""
    out = []
    for adapter_name in ADAPTERS:
        for method_name in METHODS:
            marks = []
            reason = _KNOWN_DRIFT.get((adapter_name, method_name))
            if reason is not None:
                marks.append(pytest.mark.xfail(strict=True, reason=reason))
            out.append(
                pytest.param(
                    adapter_name,
                    method_name,
                    id=f"{adapter_name}.{method_name}",
                    marks=marks,
                )
            )
    return out


@pytest.mark.parametrize("adapter_name, method_name", _params())
def test_adapter_conforms_to_protocol(adapter_name: str, method_name: str):
    """Each (adapter, method) pair conforms to ``AIModelProtocol``.

    Conformance = explicit signature declares (or **kwargs accepts)
    every canonical kwarg the dispatch layer sends. Return-shape
    pins are checked separately (slice 4 adds the runtime instance
    tests).
    """
    adapter_cls = ADAPTERS[adapter_name]
    conforms, why = _check_conformance(adapter_cls, method_name)
    assert conforms, (
        f"{adapter_name}.{method_name} fails protocol conformance: {why}. "
        f"Either fix the adapter or add a _KNOWN_DRIFT entry citing the slice."
    )


class TestProtocolModule:
    """Smoke tests for the Protocol module itself — exists, importable,
    and the canonical methods are declared.
    """

    def test_protocol_declares_canonical_methods(self):
        for method_name in METHODS:
            assert hasattr(AIModelProtocol, method_name), (
                f"AIModelProtocol must declare {method_name}"
            )

    def test_not_supported_subclasses_not_implemented(self):
        # Subclass relationship preserves ``except NotImplementedError``
        # catches during the multi-slice migration.
        assert issubclass(NotSupportedByProvider, NotImplementedError)

    def test_not_supported_carries_attribution(self):
        exc = NotSupportedByProvider("generate_image", "openai_compat")
        assert exc.method == "generate_image"
        assert exc.provider == "openai_compat"
        # Default message renders both.
        assert "openai_compat" in str(exc)
        assert "generate_image" in str(exc)

    def test_not_supported_custom_message(self):
        exc = NotSupportedByProvider(
            "generate_audio", "flux", message="use openai_compat for audio"
        )
        assert str(exc) == "use openai_compat for audio"
        # Attributes still populated even when custom message overrides.
        assert exc.method == "generate_audio"
        assert exc.provider == "flux"


class TestSlice2UnsupportedDeclarations:
    """Runtime confirmation that the methods slice 2 added actually
    raise ``NotSupportedByProvider`` — the conformance test above only
    checks signatures.

    Subclass relationship to ``NotImplementedError`` is verified
    indirectly: every assertion uses ``pytest.raises(NotImplementedError)``
    rather than the typed exception class, mirroring how existing
    callers catch it. If the subclass relationship breaks, these tests
    fail.
    """

    def test_flux_generate_json_raises_typed(self):
        flux = FluxAIModel.__new__(FluxAIModel)
        with pytest.raises(NotImplementedError) as exc_info:
            flux.generate_json("any prompt")
        assert isinstance(exc_info.value, NotSupportedByProvider)
        assert exc_info.value.method == "generate_json"
        assert exc_info.value.provider == "flux"

    def test_flux_generate_transcription_raises_typed(self):
        flux = FluxAIModel.__new__(FluxAIModel)
        with pytest.raises(NotImplementedError) as exc_info:
            flux.generate_transcription(b"audio-bytes")
        assert isinstance(exc_info.value, NotSupportedByProvider)
        assert exc_info.value.method == "generate_transcription"
        assert exc_info.value.provider == "flux"

    def test_openai_generate_image_raises_typed(self):
        client = OpenAIClient.__new__(OpenAIClient)
        with pytest.raises(NotImplementedError) as exc_info:
            client.generate_image("any prompt")
        assert isinstance(exc_info.value, NotSupportedByProvider)
        assert exc_info.value.method == "generate_image"
        assert exc_info.value.provider == "openai_compat"

    def test_openai_upscale_image_raises_typed(self):
        client = OpenAIClient.__new__(OpenAIClient)
        with pytest.raises(NotImplementedError) as exc_info:
            client.upscale_image("any prompt")
        assert isinstance(exc_info.value, NotSupportedByProvider)
        assert exc_info.value.method == "upscale_image"
        assert exc_info.value.provider == "openai_compat"

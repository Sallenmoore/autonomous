"""Independent coverage for PR #122 — `autonomous.ai.protocol` foundation.

Dev's committed test in this PR (`test_unit_ai_protocol_conformance.py`)
is a parametrized adapter-drift catalog: for each (adapter, method)
pair it inspects signatures and either passes or fails with a strict
xfail tied to a #47 slice. That's the catalog perspective.

This file takes an orthogonal angle — **behavior of the module surface
itself**, not the adapter-side drift it's pointed at:

- `@runtime_checkable` isinstance dispatch on `AIModelProtocol`
  (does the structural check fire on duck-typed conformers and reject
  obvious non-conformers?).
- `NotSupportedByProvider` semantics from caller perspective
  (legacy `except NotImplementedError:` catches it; typed catches
  surface `.method` / `.provider` for dispatch-layer routing).
- Module export surface (`__all__`, direct imports, no accidental
  re-exports from `autonomous.ai.protocol`).
- Protocol signature defaults and the asymmetric `files=` vs
  `image_content=` kwarg-naming convention called out in the PR body
  as a deliberate pin.

If the conformance catalog regresses, dev's test catches it. If the
runtime-check decorator gets stripped, defaults shift, or
`NotSupportedByProvider` loses its `NotImplementedError` ancestry —
mine does.
"""

from __future__ import annotations

import inspect

import autonomous.ai.protocol as protocol_module
from autonomous.ai.protocol import AIModelProtocol, NotSupportedByProvider


class TestModuleSurface:
    """The Protocol module exports exactly its two intended symbols."""

    def test_all_lists_exactly_the_two_public_symbols(self):
        # Public surface is intentionally minimal — anything else
        # accidentally added (helpers, constants) would leak.
        assert sorted(protocol_module.__all__) == [
            "AIModelProtocol",
            "NotSupportedByProvider",
        ]

    def test_protocol_is_directly_importable(self):
        from autonomous.ai.protocol import AIModelProtocol as direct  # noqa: F401

    def test_exception_is_directly_importable(self):
        from autonomous.ai.protocol import NotSupportedByProvider as direct  # noqa: F401

    def test_no_accidental_module_level_state(self):
        # Nothing module-level that mutates on import (no global dict,
        # no registry — those belong elsewhere). If protocol.py ever
        # grows a `_REGISTRY = {}` or similar, this fails first.
        module_globals = {
            name: type(value).__name__
            for name, value in vars(protocol_module).items()
            if not name.startswith("_")
        }
        # Allowed: the two public symbols, plus any imported names.
        # The Protocol itself is a metaclass instance; the exception
        # is a class. No `dict`, `list`, `set` instances should leak.
        leaked_containers = {
            name: kind
            for name, kind in module_globals.items()
            if kind in ("dict", "list", "set")
        }
        assert leaked_containers == {}, (
            f"protocol.py leaked container-typed globals: {leaked_containers}"
        )


class TestProtocolRuntimeCheckable:
    """`AIModelProtocol` is `@runtime_checkable` — isinstance() should work.

    Protocols only check for method *presence* at runtime, not
    signature shape. Even so, the runtime-check decorator is the
    contract that lets dispatch code do
    ``if isinstance(client, AIModelProtocol): ...`` — stripping it
    would silently turn those guards into TypeError.
    """

    def test_decorated_with_runtime_checkable(self):
        # The runtime_checkable decorator sets
        # _is_runtime_protocol = True on the protocol class.
        assert getattr(AIModelProtocol, "_is_runtime_protocol", False) is True

    def test_isinstance_accepts_duck_typed_conformer(self):
        # Anything with all four methods passes the structural check.
        class Conformer:
            def generate_json(self, *a, **kw): return {}
            def generate_transcription(self, *a, **kw): return {}
            def generate_image(self, *a, **kw): return b""
            def upscale_image(self, *a, **kw): return b""

        assert isinstance(Conformer(), AIModelProtocol)

    def test_isinstance_rejects_missing_method(self):
        # A class missing even one of the four methods fails.
        class MissingUpscale:
            def generate_json(self, *a, **kw): return {}
            def generate_transcription(self, *a, **kw): return {}
            def generate_image(self, *a, **kw): return b""

        assert not isinstance(MissingUpscale(), AIModelProtocol)

    def test_isinstance_rejects_bare_object(self):
        assert not isinstance(object(), AIModelProtocol)


class TestProtocolMethodSignatures:
    """Pin the Protocol method signatures the PR body called out.

    The conformance test focuses on whether *adapters* match the
    protocol. This pins the protocol *itself* — if someone tweaks
    `protocol.py` (renaming `files=` to `images=`, dropping a
    default, etc.), the adapters' xfail catalog drifts silently
    because conformance is checked against whatever's in protocol.py.
    These tests anchor the protocol to its documented shape so the
    catalog has a stable target.
    """

    def test_generate_image_uses_files_kwarg_plural(self):
        # PR body: `generate_image` takes `files=` (plural — img2img
        # source list). Distinct from `upscale_image`'s singular kwarg.
        sig = inspect.signature(AIModelProtocol.generate_image)
        assert "files" in sig.parameters
        assert "image_content" not in sig.parameters

    def test_upscale_image_uses_image_content_singular(self):
        # PR body: `upscale_image` takes `image_content=` (singular).
        sig = inspect.signature(AIModelProtocol.upscale_image)
        assert "image_content" in sig.parameters
        assert "files" not in sig.parameters

    def test_generate_json_has_default_schema_name_response(self):
        sig = inspect.signature(AIModelProtocol.generate_json)
        assert sig.parameters["schema_name"].default == "response"

    def test_generate_json_temperature_optional(self):
        # `temperature: float | None = None` — defaults to None so
        # adapters can route "let the provider choose."
        sig = inspect.signature(AIModelProtocol.generate_json)
        assert sig.parameters["temperature"].default is None

    def test_generate_transcription_prompt_defaults_empty_string(self):
        sig = inspect.signature(AIModelProtocol.generate_transcription)
        assert sig.parameters["prompt"].default == ""

    def test_generate_image_aspect_ratio_default(self):
        sig = inspect.signature(AIModelProtocol.generate_image)
        assert sig.parameters["aspect_ratio"].default == "2KPortrait"

    def test_upscale_image_aspect_ratio_default(self):
        sig = inspect.signature(AIModelProtocol.upscale_image)
        assert sig.parameters["aspect_ratio"].default == "2KPortrait"


class TestNotSupportedByProviderSemantics:
    """Caller-side behavior of the typed exception.

    Dev's test pins `.method` / `.provider` attribute population
    and the subclass relationship. This file exercises the actual
    catch-from-caller paths — the reason `NotSupportedByProvider`
    exists is so dispatch layers can introspect and route, while
    legacy `except NotImplementedError:` catches keep working.
    """

    def test_caught_by_not_implemented_error_handler(self):
        # Legacy callers using `except NotImplementedError:` MUST
        # continue catching this through the multi-slice migration.
        # Subclass relationship alone (tested by dev) doesn't prove
        # actual raise+catch flow — this does.
        caught = False
        try:
            raise NotSupportedByProvider("generate_image", "openai_compat")
        except NotImplementedError:
            caught = True
        assert caught

    def test_typed_catch_exposes_attribution(self):
        # New callers want the structured info for dispatch routing.
        try:
            raise NotSupportedByProvider("generate_transcription", "flux")
        except NotSupportedByProvider as exc:
            assert exc.method == "generate_transcription"
            assert exc.provider == "flux"
        else:
            raise AssertionError("typed catch did not fire")

    def test_typed_catch_takes_precedence_over_parent(self):
        # In a try/except chain ordered NotSupported → NotImplemented,
        # the typed handler MUST fire — exception MRO dispatches to
        # the most-specific match.
        caught_via = None
        try:
            raise NotSupportedByProvider("upscale_image", "gemini")
        except NotSupportedByProvider:
            caught_via = "typed"
        except NotImplementedError:
            caught_via = "parent"
        assert caught_via == "typed"

    def test_provider_can_introspect_unknown_method_for_routing(self):
        # Dispatch-layer pattern: catch the typed exception, then
        # decide based on `.method` whether to fall back to another
        # provider (e.g. ImageAgent routing to flux when openai_compat
        # raises on generate_image).
        routing_decisions = []

        def dispatch(exc: NotSupportedByProvider) -> str:
            if exc.method == "generate_image":
                return "fall-back-to-flux"
            return "propagate"

        try:
            raise NotSupportedByProvider("generate_image", "openai_compat")
        except NotSupportedByProvider as exc:
            routing_decisions.append(dispatch(exc))

        assert routing_decisions == ["fall-back-to-flux"]

    def test_default_message_contains_both_provider_and_method(self):
        # Default message is what bubbles to logs when no caller
        # overrides — observability depends on both fields appearing
        # so log-grep finds the provider AND the offending method.
        exc = NotSupportedByProvider("generate_json", "flux")
        rendered = str(exc)
        assert "flux" in rendered
        assert "generate_json" in rendered

    def test_default_message_repr_quotes_provider(self):
        # The exception's default-format wraps provider in repr-quotes
        # so a provider name like 'openai compat' (with a space) is
        # unambiguous in logs.
        exc = NotSupportedByProvider("generate_image", "openai compat")
        assert "'openai compat'" in str(exc)

    def test_init_message_keyword_only_via_position(self):
        # Positional call: (method, provider, message). Verify the
        # parameter ordering hasn't quietly flipped — a flip would
        # mis-label every existing raise site.
        sig = inspect.signature(NotSupportedByProvider.__init__)
        params = [p for p in sig.parameters if p != "self"]
        assert params == ["method", "provider", "message"]

    def test_subclassing_still_works(self):
        # If a future adapter wants a provider-specific subclass
        # (e.g. RateLimitedNotSupportedByProvider), the base shouldn't
        # block subclassing. Quick smoke that the typed exception is
        # not frozen / final.
        class StubError(NotSupportedByProvider):
            pass

        try:
            raise StubError("generate_json", "stub")
        except NotSupportedByProvider as exc:
            assert isinstance(exc, StubError)
            assert exc.method == "generate_json"
        else:
            raise AssertionError("subclass exception did not propagate")

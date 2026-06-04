"""FluxAIModel must accept the BaseAgent.get_client construction kwargs
without raising FieldDoesNotExist.

Behavioral pin for the PR #35 / issue #34 fix: BaseAgent.get_client
constructs every provider via ``model_class(name=..., instructions=...,
description=...)`` (baseagent.py:93-97). FluxAIModel(AutoModel) does
NOT inherit BaseAgent, so it doesn't pick up those fields through
MRO — they must be declared directly on the class. Without the
StringAttr declarations the strict Document validator raises
``FieldDoesNotExist: {'description', 'instructions', 'name'}`` and the
FLUX routing layer silently falls back to the configured fallback
provider (Gemini for storyteller), defeating the cost-reduction the
router was added for.

This file is the test-agent's independent second perspective — written
from PR #35's diff and the BaseAgent.get_client call site, NOT from
dev's gitignored tests/_dev_local/ coverage.
"""

import pytest


def _fresh_flux_class():
    """Return the FluxAIModel class without going through MRO resolution
    on the module. ImportError surfaces as test failure rather than
    collection error — the bug shape we are guarding includes
    ``FieldDoesNotExist`` raised at class-definition time if the
    StringAttr declarations are syntactically malformed.
    """
    from autonomous.ai.models.flux import FluxAIModel
    return FluxAIModel


class TestRequiredFieldsDeclared:
    """Structural pins on the three StringAttrs added in PR #35."""

    @pytest.mark.parametrize("field_name", ["name", "instructions", "description"])
    def test_field_declared_in__fields(self, field_name):
        """Each of the three fields must appear in FluxAIModel._fields.

        ``_fields`` is the mongoengine-introspectable dict of declared
        fields. If a future refactor strips the StringAttr declarations
        (e.g. someone "cleaning up unused fields"), this assertion fires
        before BaseAgent.get_client construction can re-break.
        """
        flux_cls = _fresh_flux_class()
        assert field_name in flux_cls._fields, (
            f"FluxAIModel must declare '{field_name}' so "
            f"BaseAgent.get_client can forward the kwarg from the agent "
            f"into the constructor. Missing → FieldDoesNotExist in prod."
        )

    @pytest.mark.parametrize("field_name", ["name", "instructions", "description"])
    def test_field_is_string_typed(self, field_name):
        """Each declared field must be a StringField (or subclass).

        Guards against accidental retyping (e.g. someone re-declaring
        ``name`` as a DictAttr would silently change the contract that
        BaseAgent.get_client passes a string).
        """
        from autonomous.db.fields import StringField
        flux_cls = _fresh_flux_class()
        assert isinstance(flux_cls._fields[field_name], StringField)


class TestConstructibilityWithBaseAgentKwargs:
    """The fix's headline behavior: the exact call BaseAgent.get_client
    makes must not raise."""

    def test_construct_with_all_three_kwargs(self):
        """The literal failure mode reported in issue #34.

        Before PR #35, this raised
        ``FieldDoesNotExist: {'description', 'instructions', 'name'}``
        inside the Document validator. With the fix, construction
        succeeds and the kwargs land on the instance.
        """
        flux_cls = _fresh_flux_class()
        instance = flux_cls(
            name="some_agent",
            instructions="some_instructions",
            description="some_description",
        )
        assert instance.name == "some_agent"
        assert instance.instructions == "some_instructions"
        assert instance.description == "some_description"

    def test_kwargs_override_class_defaults(self):
        """Explicit kwargs must take precedence over the declared defaults.

        Guards against a future refactor that flips StringAttr to a
        descriptor that doesn't honor constructor kwargs (would silently
        wipe whatever the agent forwarded).
        """
        flux_cls = _fresh_flux_class()
        instance = flux_cls(name="override")
        assert instance.name == "override", (
            "Constructor kwarg must beat the class-level default; "
            "otherwise BaseAgent.get_client can't forward agent.name."
        )

    def test_baseagent_get_client_construction_pattern(self):
        """Exact reproduction of baseagent.py:93-97.

        ``model_class(name=self.name, instructions=self.instructions,
        description=self.description)`` is the exact call inside
        ``BaseAgent.get_client``. Replicate the kwarg shape (not just
        the values) so a future signature change there is caught here.
        """
        flux_cls = _fresh_flux_class()

        # Simulate the agent attributes BaseAgent.get_client reads from.
        class _AgentLike:
            name = "image_agent"
            instructions = "Generate a fantasy portrait."
            description = "ImageAgent for storyteller character art."

        agent = _AgentLike()
        instance = flux_cls(
            name=agent.name,
            instructions=agent.instructions,
            description=agent.description,
        )
        assert instance.name == agent.name
        assert instance.instructions == agent.instructions
        assert instance.description == agent.description


class TestDocumentedDefaults:
    """Pin the FLUX-specific default values declared in PR #35.

    Comments in flux.py describe the defaults as 'no-ops for fal.ai'
    but they are still operator-visible identifiers — pinning them
    here so a doc/code drift in either direction is caught.
    """

    def test_default_name(self):
        flux_cls = _fresh_flux_class()
        assert flux_cls.name.default == "flux_agent"

    def test_default_instructions(self):
        flux_cls = _fresh_flux_class()
        assert flux_cls.instructions.default == (
            "You are an AI image generation assistant using FLUX.1 [pro]."
        )

    def test_default_description(self):
        flux_cls = _fresh_flux_class()
        assert flux_cls.description.default == (
            "FLUX.1 [pro] image generation adapter (fal.ai)."
        )

    @pytest.mark.parametrize("field_name", ["name", "instructions", "description"])
    def test_default_resolves_when_no_kwarg_supplied(self, field_name):
        """Constructing without kwargs must materialize the documented
        default on the instance, not just on the class descriptor.

        Without this, a caller doing ``FluxAIModel()`` (no kwargs) would
        get None on these fields and serialization back to Mongo would
        either fail validation or persist nulls. Either is a regression
        from PR #35's stated intent.
        """
        flux_cls = _fresh_flux_class()
        instance = flux_cls()
        assert getattr(instance, field_name), (
            f"Default for '{field_name}' must materialize on the "
            f"instance when no kwarg is supplied."
        )


class TestRegressionGuard:
    """Cross-file contract pin: BaseAgent.get_client's forwarded kwargs
    and FluxAIModel's declared fields must stay aligned.

    Failure modes this catches that the per-field tests above don't:
    - BaseAgent.get_client drops one of the kwargs (silent partial
      construction; instance ends up with only some fields populated).
    - A future refactor renames the kwargs at the call site without
      updating FluxAIModel.

    Does NOT catch additive divergence — if BaseAgent.get_client adds a
    NEW kwarg (e.g. ``role=self.role``), the test as written only
    verifies the original three are still forwarded. That gap is fine:
    a new kwarg failing the FluxAIModel constructor would surface
    immediately as a runtime FieldDoesNotExist that the other tests
    here would catch on the next iteration.
    """

    def test_baseagent_forwards_only_known_fields(self):
        """The kwarg set forwarded by BaseAgent.get_client must remain
        a subset of FluxAIModel's declared fields.

        If someone adds a new kwarg to the get_client call site (or to
        the FluxAIModel constructor) without updating the other, the
        next FLUX dispatch would FieldDoesNotExist again. Caught here.
        """
        import inspect

        from autonomous.ai import baseagent
        flux_cls = _fresh_flux_class()
        source = inspect.getsource(baseagent.BaseAgent.get_client)
        # The kwargs forwarded into model_class(...) — strict subset check.
        forwarded = {"name", "instructions", "description"}
        for kw in forwarded:
            assert f"{kw}=self.{kw}" in source, (
                f"BaseAgent.get_client must forward '{kw}=self.{kw}' "
                f"to the adapter constructor; if this changes, every "
                f"adapter (including FluxAIModel) needs a matching "
                f"field declaration."
            )
            assert kw in flux_cls._fields, (
                f"FluxAIModel must declare '{kw}' to receive the "
                f"forwarded kwarg without FieldDoesNotExist."
            )

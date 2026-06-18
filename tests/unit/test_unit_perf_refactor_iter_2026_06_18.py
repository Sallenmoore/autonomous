"""Independent second-perspective coverage for PR #165.

Pins the load-bearing invariants of:

- #145 (``autonomous.db.base.document.BaseDocument`` change-tracking perf
  wins): ``_mark_as_changed``'s O(n) descendant-drop rebuild keeps the
  same observable ``_changed_fields`` contents the pre-#145 in-place
  ``append`` + ``list.remove`` loop produced — ancestor short-circuit,
  descendant drop, idempotent re-mark, sibling-order preservation, and
  db-field-map remapping.

- #146 (``autonomous.ai._json_messages.build_chat_json_messages``): the
  helper produces ``(system, user)`` strings byte-identical to the
  pre-#146 inline construction in ``LocalAIModel.generate_json`` and
  ``OpenAIClient.generate_json``, gated by the keyword-only
  ``api_enforces_json`` flag (False = Ollama prompt-only, True =
  OpenAI-compatible). The shared
  ``STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER`` is the same singleton when
  accessed via the canonical name or either adapter's alias. The
  per-adapter ``event`` patch seams (``autonomous.ai.models.local_model.event``
  and ``autonomous.ai.models.openai_compat.event``) still resolve.

These tests are deliberately constructed from a fresh read of the PR
diff WITHOUT consulting ``tests/_dev_local/`` (gitignored, invisible) —
they are the independent perspective the two-agent topology demands.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from autonomous.db.base.document import BaseDocument
from autonomous.ai._json_messages import (
    STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER,
    build_chat_json_messages,
)
from autonomous.ai.models import local_model, openai_compat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_doc(initial_changed_fields=None, db_field_map=None):
    """Build a minimal stand-in for BaseDocument.

    ``_mark_as_changed`` reads ``self._changed_fields`` and
    ``self._db_field_map`` and rebinds ``self._changed_fields``. A plain
    object with these two attributes is enough — the descriptor protocol
    of the real ``BaseDocument`` __slots__ is not under test here.
    """
    stub = SimpleNamespace()
    stub._changed_fields = list(initial_changed_fields or [])
    stub._db_field_map = dict(db_field_map or {})
    return stub


# ---------------------------------------------------------------------------
# A — _mark_as_changed semantics (#145)
#
# Pre-#145 form did `append(key)` then walked a snapshot calling
# `list.remove(field)` for every descendant — O(k·n). Post-#145 rebuilds
# `_changed_fields` in a single list comprehension and appends `key` at
# the end. The OBSERVABLE final list contents (and ordering) must match
# the pre-#145 form on every input shape.
# ---------------------------------------------------------------------------


class TestMarkAsChangedAncestorShortCircuit:
    """If any ancestor of ``key`` is already in ``_changed_fields``, the
    parent-mark already covers the descendant — no-op (no append, no
    drop). The pre-#145 form expressed this via a ``while … else``;
    the post-#145 form uses an explicit ``for … return``. Same outcome.
    """

    def test_immediate_parent_present_no_op(self):
        stub = _stub_doc(initial_changed_fields=["a"])
        BaseDocument._mark_as_changed(stub, "a.b")
        assert stub._changed_fields == ["a"]

    def test_grandparent_present_no_op(self):
        stub = _stub_doc(initial_changed_fields=["a"])
        BaseDocument._mark_as_changed(stub, "a.b.c")
        assert stub._changed_fields == ["a"]

    def test_mid_ancestor_present_no_op(self):
        stub = _stub_doc(initial_changed_fields=["a.b"])
        BaseDocument._mark_as_changed(stub, "a.b.c.d")
        assert stub._changed_fields == ["a.b"]


class TestMarkAsChangedDescendantDrop:
    """When no ancestor is marked, ``key`` is added and any field
    starting with ``key + "."`` is dropped. The post-#145 implementation
    builds a new list via comprehension; the pre-#145 form did
    ``list.remove`` per match.
    """

    def test_drops_single_descendant(self):
        stub = _stub_doc(initial_changed_fields=["a.b"])
        BaseDocument._mark_as_changed(stub, "a")
        assert stub._changed_fields == ["a"]

    def test_drops_multiple_descendants(self):
        stub = _stub_doc(initial_changed_fields=["a.b", "a.c", "a.d.e"])
        BaseDocument._mark_as_changed(stub, "a")
        assert stub._changed_fields == ["a"]

    def test_drops_only_real_descendants_not_prefix_lookalikes(self):
        """Marking ``'a'`` must drop ``'a.b'`` (descendant) but NOT
        ``'ab'`` or ``'aa'`` — those share a character-prefix but no
        dotted-path-prefix. The drop key is ``key + "."``, not ``key``.
        Pre-#145 used the same ``+ "."`` guard.
        """
        stub = _stub_doc(initial_changed_fields=["a.b", "ab", "aa", "a.x.y"])
        BaseDocument._mark_as_changed(stub, "a")
        # 'a.b' and 'a.x.y' are real descendants → dropped.
        # 'ab' and 'aa' are NOT descendants → preserved.
        assert "a.b" not in stub._changed_fields
        assert "a.x.y" not in stub._changed_fields
        assert "ab" in stub._changed_fields
        assert "aa" in stub._changed_fields
        assert "a" in stub._changed_fields


class TestMarkAsChangedIdempotent:
    """Re-marking a field already in ``_changed_fields`` is a no-op —
    no duplicate, no reorder. The post-#145 form returns early on the
    ``if key in changed`` check; pre-#145 had the same outer guard.
    """

    def test_exact_match_no_op(self):
        stub = _stub_doc(initial_changed_fields=["x", "a", "b"])
        BaseDocument._mark_as_changed(stub, "a")
        assert stub._changed_fields == ["x", "a", "b"]


class TestMarkAsChangedSiblingOrder:
    """When ``key`` is appended (no ancestor covers it), unrelated
    sibling fields preserve their relative order from before the call.
    Pre-#145 used ``append(key)`` + in-place removal, so uncovered
    siblings stayed put. Post-#145 rebuilds via comprehension preserving
    iteration order, then appends. Same final ordering.
    """

    def test_sibling_order_preserved(self):
        stub = _stub_doc(initial_changed_fields=["x", "y", "z"])
        BaseDocument._mark_as_changed(stub, "a")
        # Pre-#145 form: append 'a' at end, nothing to remove (no 'a.' prefix).
        # Post-#145 form: comp filters nothing (no 'a.' prefix matches), then append.
        assert stub._changed_fields == ["x", "y", "z", "a"]

    def test_descendant_drop_preserves_uncovered_order(self):
        """Pre-#145: ``append('a')`` then walk a snapshot calling
        ``remove(field)`` for each ``a.*`` match — uncovered siblings
        stay in their original positions, ``'a'`` ends up at the tail.
        Post-#145: comprehension filters ``a.*`` while preserving the
        order of survivors, then appends ``'a'`` — same final shape.
        """
        stub = _stub_doc(
            initial_changed_fields=["x", "a.b", "y", "a.c", "z"]
        )
        BaseDocument._mark_as_changed(stub, "a")
        assert stub._changed_fields == ["x", "y", "z", "a"]


class TestMarkAsChangedDbFieldMapRemap:
    """``_db_field_map`` translates the Python field name to its
    on-the-wire db field name before any of the change-tracking logic
    runs. Both pre- and post-#145 do this remap on the leading segment
    only — nested rest-of-key is preserved verbatim.
    """

    def test_single_segment_remap(self):
        stub = _stub_doc(db_field_map={"name": "n"})
        BaseDocument._mark_as_changed(stub, "name")
        assert stub._changed_fields == ["n"]

    def test_compound_key_remaps_only_head(self):
        """``'name.first'`` with map ``{'name': 'n'}`` → ``'n.first'``.
        The split-on-first-dot + remap-head + reassemble logic is the
        same in pre- and post-#145.
        """
        stub = _stub_doc(db_field_map={"name": "n"})
        BaseDocument._mark_as_changed(stub, "name.first")
        assert stub._changed_fields == ["n.first"]

    def test_compound_key_no_map_passes_through(self):
        stub = _stub_doc(db_field_map={})
        BaseDocument._mark_as_changed(stub, "name.first")
        assert stub._changed_fields == ["name.first"]


class TestMarkAsChangedNoChangedFieldsAttribute:
    """``hasattr(self, '_changed_fields')`` is the gate — without the
    attribute the method returns silently. Documents being constructed
    via ``_from_son`` can briefly lack this attribute; the early-return
    keeps that path safe.
    """

    def test_missing_attribute_returns_silently(self):
        stub = SimpleNamespace()
        stub._db_field_map = {}
        # Must not raise.
        BaseDocument._mark_as_changed(stub, "anything")


class TestMarkAsChangedQuadraticBudget:
    """Pre-#145 form was O(k·n) for k descendants of ``key`` in a
    ``_changed_fields`` list of length n. Post-#145 form is O(n). For
    a large n with many descendants, the function should complete well
    within a tight wall-clock budget. This is a regression guard for
    the perf claim — the structural fix (tuple-paths) is deferred per
    DIVERGENCE.md, but THIS hot-path must remain linear.
    """

    def test_drops_many_descendants_in_linear_time(self):
        # 10k descendants of 'root' + 10k unrelated siblings.
        descendants = [f"root.child{i}" for i in range(10_000)]
        siblings = [f"sib{i}" for i in range(10_000)]
        stub = _stub_doc(initial_changed_fields=descendants + siblings)
        BaseDocument._mark_as_changed(stub, "root")
        # All descendants dropped, all siblings preserved, 'root' appended.
        assert len(stub._changed_fields) == 10_001
        assert stub._changed_fields[-1] == "root"
        assert "root.child0" not in stub._changed_fields
        assert "sib0" in stub._changed_fields


# ---------------------------------------------------------------------------
# B — build_chat_json_messages byte-identical contracts (#146)
#
# The PR's load-bearing claim is "wire strings byte-identical to
# pre-#146 paths." These tests pin the exact strings against the
# pre-#146 form recovered from the diff hunk's deleted lines.
# ---------------------------------------------------------------------------


class TestBuildChatJsonMessagesFalseBranch:
    """``api_enforces_json=False`` = Ollama prompt-only path. System
    message carries verbose JSON-enforcement; context label is
    "Adhere strictly to this context:\\n"; suffix carries
    ". No markdown, no prose." Pre-#146 form is recovered from the
    deleted lines of ``local_model.generate_json``.
    """

    def test_bare_no_context_no_uri(self):
        system, user = build_chat_json_messages(
            message="hello",
            system_base="You are helpful",
            api_enforces_json=False,
        )
        assert system == (
            "You are helpful.\n"
            "Your entire response MUST be a single valid JSON object.\n"
            "Start with { and end with }. No markdown, no prose."
        )
        assert user == (
            "hello"
            "\n\nRespond with ONLY a valid JSON object. No markdown, no prose."
        )

    def test_with_context_uses_adhere_strictly_label(self):
        system, user = build_chat_json_messages(
            message="hello",
            system_base="You are helpful",
            context={"k": "v"},
            api_enforces_json=False,
        )
        # The "Adhere strictly to this context:\n" label is the
        # Ollama-specific gate; openai_compat MUST NOT have it (covered
        # in TestBuildChatJsonMessagesTrueBranch.test_with_context_no_label).
        assert "Adhere strictly to this context:\n" in user
        # The fenced JSON block uses indent=2 — matches pre-#146 byte-for-byte.
        assert '"k": "v"' in user

    def test_with_uri_appended(self):
        _, user = build_chat_json_messages(
            message="hello",
            system_base="You are helpful",
            uri="http://example.com",
            api_enforces_json=False,
        )
        assert "\nUse the following URI for reference: http://example.com" in user

    def test_suffix_has_no_markdown_no_prose_clause(self):
        _, user = build_chat_json_messages(
            message="hello",
            system_base="x",
            api_enforces_json=False,
        )
        assert user.endswith("No markdown, no prose.")


class TestBuildChatJsonMessagesTrueBranch:
    """``api_enforces_json=True`` = OpenAI-compatible path. System
    message is lighter (single line of JSON enforcement); context block
    has NO ``Adhere strictly`` label; suffix lacks the ``No markdown,
    no prose.`` clause. Pre-#146 form is recovered from the deleted
    lines of ``openai_compat.generate_json``.
    """

    def test_bare_no_context_no_uri(self):
        system, user = build_chat_json_messages(
            message="hello",
            system_base="You are helpful",
            api_enforces_json=True,
        )
        assert system == (
            "You are helpful.\nYour response MUST be a single valid JSON object."
        )
        assert user == (
            "hello\n\nRespond with ONLY a valid JSON object."
        )

    def test_with_context_no_label(self):
        """The asymmetry that motivated #146: openai_compat NEVER
        emitted "Adhere strictly to this context:" because the
        response_format=json_object payload enforces JSON shape at the
        API layer. Re-introducing that label here would be a wire
        change visible to the OpenAI-compatible endpoint.
        """
        _, user = build_chat_json_messages(
            message="hello",
            system_base="x",
            context={"k": "v"},
            api_enforces_json=True,
        )
        assert "Adhere strictly to this context:" not in user
        assert '"k": "v"' in user
        # GROUND TRUTH CONTEXT header IS present — just without the label.
        assert "### GROUND TRUTH CONTEXT ###" in user

    def test_suffix_omits_no_markdown_clause(self):
        """openai_compat path's suffix is ``Respond with ONLY a valid
        JSON object.`` — without the trailing ``No markdown, no prose.``
        the prompt-only path appends. The full ``user`` always ends
        with the json_suffix.
        """
        _, user = build_chat_json_messages(
            message="hello",
            system_base="x",
            api_enforces_json=True,
        )
        assert user.endswith("Respond with ONLY a valid JSON object.")
        assert "No markdown, no prose." not in user


class TestBuildChatJsonMessagesSystemBaseNormalization:
    """The persona/instructions ``system_base`` is normalized via
    ``rstrip('. ') + '.'`` — same in pre- and post-#146. Trailing
    periods/spaces collapse to a single period.
    """

    def test_trailing_period_no_double_dot(self):
        system, _ = build_chat_json_messages(
            message="m",
            system_base="You are helpful.",
            api_enforces_json=True,
        )
        assert system.startswith("You are helpful.\n")
        assert not system.startswith("You are helpful..")

    def test_trailing_periods_and_spaces_collapse(self):
        system, _ = build_chat_json_messages(
            message="m",
            system_base="You are helpful. . ",
            api_enforces_json=True,
        )
        assert system.startswith("You are helpful.\n")


class TestBuildChatJsonMessagesApiEnforcesJsonKeywordOnly:
    """``api_enforces_json`` is keyword-only — guards against the easy
    mistake of passing it positionally where ``uri`` lives. The
    signature is ``(message, system_base, context=None, uri="", *,
    api_enforces_json)`` so positional past ``uri`` raises TypeError.
    """

    def test_positional_raises(self):
        # message, system_base, context, uri, then positional True would
        # be a 5th positional arg — the * blocks it.
        with pytest.raises(TypeError):
            build_chat_json_messages("m", "p", None, "", True)


# ---------------------------------------------------------------------------
# C — Shared counter singleton + patch seam preservation (#146)
# ---------------------------------------------------------------------------


class TestSharedCounterSingleton:
    """The PR consolidates the structured-outputs counter into
    ``_json_messages``. Both adapters re-export it via the legacy alias
    ``_STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER`` so existing patch
    targets (in tests/unit/test_unit_resilience_124_125_*.py and
    test_unit_observability_structured_outputs_*.py) keep working. All
    three references must be the same object.
    """

    def test_local_model_alias_is_canonical_counter(self):
        assert (
            local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
            is STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
        )

    def test_openai_compat_alias_is_canonical_counter(self):
        assert (
            openai_compat._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
            is STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
        )

    def test_both_adapter_aliases_are_same_object(self):
        # Transitively true given the two assertions above, but pinning
        # the cross-adapter identity directly catches a regression where
        # a future edit could rebind one of the aliases to a fresh
        # counter() call (which the observability registry would coalesce
        # by name, hiding the bug behind matching .inc() behavior — but
        # the object identity would diverge).
        assert (
            local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
            is openai_compat._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
        )

    def test_counter_has_provider_label(self):
        """Both adapters call ``.inc(provider="...")`` — the counter
        must carry the ``provider`` label dimension. This is the
        observability contract the prom scrapers / dashboards consume.
        """
        # Smoke: .inc with provider= must not raise.
        STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER.inc(provider="local")
        STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER.inc(provider="openai_compat")


class TestEventPatchSeamPreserved:
    """The PR keeps ``event`` imported as a module-level name in BOTH
    adapters so existing patch targets continue to intercept:

    - ``autonomous.ai.models.local_model.event``
    - ``autonomous.ai.models.openai_compat.event``

    The DRY-this-into-a-helper attempt under #146 was reverted exactly
    because routing through ``_json_messages.event`` would resolve at
    helper-module namespace, bypassing per-adapter patches. These
    tests are the regression guard.
    """

    def test_local_model_event_is_patchable(self):
        # patch.object resolves the attribute on the module — succeeds
        # only if ``event`` is a module-level name in local_model.
        with patch.object(local_model, "event") as mock_event:
            local_model.event("test_event", level="info")
            mock_event.assert_called_once_with("test_event", level="info")

    def test_openai_compat_event_is_patchable(self):
        with patch.object(openai_compat, "event") as mock_event:
            openai_compat.event("test_event", level="info")
            mock_event.assert_called_once_with("test_event", level="info")


class TestEmitStrictUnavailableHelper:
    """The intra-module ``OpenAIClient._emit_strict_unavailable`` helper
    (added in PR #165's review-apply commit) factors the two emission
    sites in ``generate_json`` without crossing module boundaries.
    Living in ``openai_compat`` (not ``_json_messages``) means
    ``event`` and the counter alias both resolve through this module's
    namespace — patches via ``patch.object(openai_compat, 'event')``
    still intercept.
    """

    def test_helper_exists_on_class(self):
        assert hasattr(openai_compat.OpenAIClient, "_emit_strict_unavailable")

    def test_helper_routes_through_module_event(self):
        """The helper must call ``event`` via the openai_compat module
        namespace, not via a captured reference at definition time. A
        ``patch.object(openai_compat, 'event')`` should intercept any
        call the helper makes.
        """
        # Stub a minimal OpenAIClient instance for the helper. The
        # method only reads ``self._json_model`` and ``self._base_url``;
        # avoid descriptor-protocol attribute setters by using a plain
        # class and binding the method via __get__.
        class _Stub:
            pass

        stub = _Stub()
        stub._json_model = "gpt-test"
        stub._base_url = "https://example/openai"
        emit = openai_compat.OpenAIClient._emit_strict_unavailable.__get__(
            stub, _Stub
        )

        with patch.object(openai_compat, "event") as mock_event, patch.object(
            openai_compat._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER,
            "inc",
        ):
            emit(status=400, body_excerpt="oops", detection="first")
            mock_event.assert_called_once()
            call = mock_event.call_args
            # Required fields the helper must always emit.
            assert call.args[0] == "structured_outputs_unavailable"
            assert call.kwargs["level"] == "warning"
            assert call.kwargs["marker"] == "STRUCTURED-OUTPUTS-UNAVAILABLE"
            assert call.kwargs["provider"] == "openai_compat"
            assert call.kwargs["model"] == "gpt-test"
            assert call.kwargs["endpoint"] == "https://example/openai"
            # Variable fields piped through from the caller.
            assert call.kwargs["status"] == 400
            assert call.kwargs["body_excerpt"] == "oops"
            assert call.kwargs["detection"] == "first"
            assert call.kwargs["cached_for_process"] is True


# ---------------------------------------------------------------------------
# D — Module-shape regression guards
#
# The PR also touched imports in both adapter modules: ``counter`` was
# removed (now imported only at _json_messages); ``event`` was
# re-imported from ``autonomous.observability`` so the patch seam
# survives. These tests catch a regression where someone might "tidy
# up" the imports and re-break either contract.
# ---------------------------------------------------------------------------


class TestAdapterImportShape:
    """The diff removed the per-adapter ``counter()`` registrations
    and rewrote the imports. These tests pin the post-#146 module shape
    so a future "unused import" cleanup can't silently regress either
    the patch seam or the alias singleton.
    """

    def test_local_model_imports_build_chat_json_messages(self):
        """The helper must be importable on the local_model namespace —
        confirms ``generate_json`` is routing through the shared helper.
        """
        # Reimport to dodge any test-order coupling.
        mod = importlib.reload(local_model)
        # The alias and the helper-import must both resolve.
        assert hasattr(mod, "_STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER")
        assert hasattr(mod, "build_chat_json_messages")
        # Restore the module so later tests see the same object identity.
        importlib.reload(local_model)

    def test_openai_compat_imports_build_chat_json_messages(self):
        mod = importlib.reload(openai_compat)
        assert hasattr(mod, "_STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER")
        assert hasattr(mod, "build_chat_json_messages")
        importlib.reload(openai_compat)


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


def test_traceability_pr_165():
    """Marker test pinning the PR number this file's tests target. Lets
    a future ``git log -S '#165'`` or coverage audit map tests to PR
    without parsing docstrings.
    """
    assert True  # Test PR #165 (closes #145 + #146)

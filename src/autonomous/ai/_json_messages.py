"""Shared JSON-mode chat-message construction for AI provider adapters
(issue #146).

Before #146, ``LocalAIModel.generate_json`` and
``OpenAIClient.generate_json`` each maintained a near-identical
message-build sequence. The shape was shared but the variant strings
drifted between providers — the risk of silent prompt-drift was the
primary motivation for consolidation.

``build_chat_json_messages`` returns the ``(system, user)`` tuple,
switching the JSON-instruction verbosity, context label, and trailing
suffix on a single ``api_enforces_json`` flag (True for
OpenAI-compatible endpoints that honor ``response_format=json_object``,
False for prompt-only enforcement on Ollama).

Deliberately NOT consolidated into a heavy ``JSONGenerationMixin``:

- Retry shapes are genuinely different — local_model uses an outer
  ``retry()`` wrapper because its transient surface is wide
  (``ConnectionError``, ``Timeout``, ``json.JSONDecodeError``,
  ``ValueError``, ``KeyError``); openai_compat relies on
  ``HttpClient``-internal retries plus an explicit strict→loose
  fallback that's entangled with the call sequence.
- Exception translation ladders differ — local has more typed
  translations because Ollama leaks more raw shapes; openai's
  ``HttpClient`` catches at a coarser altitude.

Forcing a single retry/translation owner would either bloat the mixin
with provider-specific branches or silently regress one side's
fail-fast / retry semantics. Helpers are the right altitude.

The shared counter (``STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER``) lives
here so the "shared resource" intent is obvious from imports.
(``observability.counter`` is idempotent on name, so a duplicated
module-level registration in each adapter would resolve to the same
singleton — but the shared intent would not be visible at import time.)

Per-call ``event()`` + counter-inc emission stays INLINE at each
adapter site. ``event`` is resolved through each adapter's module
namespace, which is the patch seam the unit tests rely on
(``patch.object(local_model, 'event')`` /
``patch.object(openai_compat, 'event')``). Routing emission through a
helper in THIS module would bypass those patches.
"""

import json

from autonomous.observability import counter


# Process-wide counter for structured-outputs-unavailable fallbacks
# (#51 step 3, consolidated under #146). Shared across providers via
# the ``provider=`` label. Bumped on first detection per
# (model, endpoint) per process, matching each adapter's log emission
# gate.
STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER = counter(
    "structured_outputs_unavailable_total",
    description=(
        "JSON adapters falling back from strict-mode schema enforcement "
        "(first detection per (model, endpoint) per process)"
    ),
    label_names=("provider",),
)


def build_chat_json_messages(
    message,
    system_base,
    context=None,
    uri="",
    *,
    api_enforces_json,
):
    """Build the ``(system, user)`` message pair for a JSON-mode chat call.

    Parameters
    ----------
    message:
        The user-side prompt (already-stringified by the caller).
    system_base:
        The resolved persona string — typically
        ``system_prompt or self.instructions`` at the caller. Resolution
        stays at the call site so an explicit ``system_prompt`` never
        triggers the ``instructions`` descriptor read.
    context:
        Optional dict of ground-truth context. Serialized into the user
        message as a fenced JSON block.
    uri:
        Optional reference URI appended to the user message.
    api_enforces_json:
        Keyword-only. ``True`` when the provider supports
        ``response_format=json_object`` (OpenAI-compatible) — uses
        lighter prompt enforcement because the API enforces shape.
        ``False`` when the provider relies on prompt-only enforcement
        (Ollama) — uses verbose prompt enforcement and a stricter
        context label.

    Returns
    -------
    tuple[str, str]
        ``(system, user)`` — pass straight to the chat-completion endpoint.
    """
    base = system_base.rstrip(". ") + "."
    if api_enforces_json:
        # OpenAI-compatible: response_format enforces, prompt can be light.
        system = f"{base}\nYour response MUST be a single valid JSON object."
        context_label = ""
        json_suffix = "\n\nRespond with ONLY a valid JSON object."
    else:
        # Prompt-only (Ollama): verbose instructions matter — the model
        # gets the entire enforcement budget from the system message.
        system = (
            f"{base}\n"
            f"Your entire response MUST be a single valid JSON object.\n"
            f"Start with {{ and end with }}. No markdown, no prose."
        )
        context_label = "Adhere strictly to this context:\n"
        json_suffix = (
            "\n\nRespond with ONLY a valid JSON object. No markdown, no prose."
        )

    user = message
    if context:
        user += (
            f"\n\n### GROUND TRUTH CONTEXT ###\n"
            f"{context_label}"
            f"{json.dumps(context, indent=2)}"
        )
    if uri:
        user += f"\nUse the following URI for reference: {uri}"
    user += json_suffix
    return system, user

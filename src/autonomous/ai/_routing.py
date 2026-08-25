"""Per-call provider resolution for agent entry points (#239).

The sibling of ``_credentials.client_key_scope``: BYOK needs *this user's
provider, billed to this user's key*, and #227 only delivered the key.
"""

import os


def resolve_client(agent, provider, env_var):
    """Return the client that should serve ONE agent call.

    ``provider=None`` — the default on every entry point — keeps the
    env-derived behavior byte-for-byte: the role's ``env_var``, falling
    back to the agent's own ``provider`` field, resolved through
    ``get_client`` and persisted on the agent exactly as before. An empty
    string is the same no-op, matching ``api_key``'s contract (#227): a
    consumer forwarding an end user's unset selector should not have to
    branch on ``"" vs None`` at every call site.

    A supplied ``provider`` returns a **transient** client and never
    touches ``agent.client``. Two reasons it cannot go through
    ``get_client``, even with ``persist=False``:

    1. ``get_client`` *assigns* ``self.client``, so a per-call override
       would leak into the agent's next call — and agent docs are shared
       by concurrent jobs in one RQ worker, which is the whole hazard
       #227 took pains to avoid for credentials.
    2. The assigned client is unsaved, so the agent's own next
       ``save()`` raises on the dangling reference (mongoengine refuses
       to reference an unsaved document).

    Raises:
        ValueError: ``provider`` is not in ``MODEL_REGISTRY``. Deliberately
            louder than ``get_client``, which falls back to ``LocalAIModel``
            for an unknown name — a consumer passing an end user's provider
            choice wants to validate it, not silently generate on the wrong
            model.
    """
    if not provider:
        return agent.get_client(os.environ.get(env_var, agent.provider))

    try:
        model_class = agent.MODEL_REGISTRY[provider]
    except KeyError:
        raise ValueError(
            f"Unknown AI provider {provider!r}. Valid providers: "
            f"{', '.join(sorted(agent.MODEL_REGISTRY))}."
        ) from None

    return model_class(
        name=agent.name,
        instructions=agent.instructions,
        description=agent.description,
    )

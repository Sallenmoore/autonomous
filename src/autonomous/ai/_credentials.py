"""Per-call provider credential overrides — the BYOK primitive (#227).

A multi-tenant consumer generating on an end user's own key cannot mutate
``os.environ`` (or an adapter class attribute) to do it: an RQ worker is a
long-lived process running jobs for many users back to back, so a global
write is a cross-user credential leak waiting for the right interleaving.

The override therefore lives in a :class:`~contextvars.ContextVar`, which
is scoped to the current thread *and* the current async task. A key bound
for one job is invisible to every other job in the same worker, and the
binding unwinds on the way out of the ``with`` block even if the call
raises. Nothing is stored on the agent, so ``BaseAgent.save()`` can never
persist a user's secret.

**Overrides are keyed by credential env-var name, never applied globally.**
``ImageAgent`` may fall back from FLUX to Gemini mid-call; binding a bare
scalar would hand the user's ``FAL_KEY`` to Google. Keying on the env var
means the fallback provider reads its *own* credential, finds no override,
and uses the deployment default — a user's key is only ever sent to the
provider it was issued for.
"""

import contextlib
import contextvars

from autonomous.config import env_str

# ``None`` rather than ``{}`` as the default: a shared mutable default on a
# ContextVar is a footgun even when the code never mutates it today.
_overrides: contextvars.ContextVar = contextvars.ContextVar(
    "autonomous_ai_api_key_overrides", default=None
)


@contextlib.contextmanager
def api_key_override(overrides):
    """Bind ``{env_var: api_key}`` for the duration of the block.

    Falsy keys and a falsy/empty mapping are no-ops, so callers can pass a
    caller-supplied ``api_key=None`` straight through without branching.
    Nested scopes merge, inner winning, so an outer per-request binding
    survives an inner per-provider one.
    """
    cleaned = {k: v for k, v in (overrides or {}).items() if k and v}
    if not cleaned:
        yield
        return
    token = _overrides.set({**(_overrides.get() or {}), **cleaned})
    try:
        yield
    finally:
        _overrides.reset(token)


def resolve_api_key(env_var, default=""):
    """The bound override for ``env_var``, else ``default``, else the env.

    ``default`` exists for adapters that snapshot their key into a class
    attribute at import (``openai_compat``, ``litellm``). Passing that
    snapshot keeps the documented "tests monkeypatch the class attrs to
    retarget" idiom working while still letting a per-call override win.
    """
    if override := (_overrides.get() or {}).get(env_var):
        return override
    return default or env_str(env_var, "")


def override_for(env_var):
    """The bound override for ``env_var``, or ``None`` — env is NOT consulted.

    For adapters that need to branch on *whether* a per-call key is in play,
    not merely resolve one: ``gemini`` memoizes its platform client on the
    instance and must build a throwaway client for an override rather than
    poisoning (or persisting) that cache.
    """
    return (_overrides.get() or {}).get(env_var) or None


def client_key_scope(client, api_key):
    """Bind ``api_key`` to ``client``'s own credential env var (#227).

    Keyed by the adapter's ``API_KEY_ENV``, never applied globally, so a
    key issued for one provider cannot travel to another on a fallback
    leg — ``ImageAgent`` may route FLUX → Gemini mid-call, and a bare
    scalar binding would hand the user's ``FAL_KEY`` to Google. An adapter
    with no ``API_KEY_ENV`` (``mock_model``, which has no credential)
    makes this a no-op.

    A module-level function rather than a ``BaseAgent`` method on purpose:
    the agent methods are routinely exercised against lightweight test
    doubles that borrow the real function, and requiring ``self`` to carry
    a new attribute would break every one of them.
    """
    return api_key_override({getattr(client, "API_KEY_ENV", None): api_key})


def current_overrides():
    """A snapshot of the bindings, for re-binding inside a worker thread.

    A ContextVar does not cross into a thread the caller did not create,
    and ``contextvars.Context.run`` cannot be entered by several threads
    at once — so a pool must re-bind explicitly from a snapshot rather
    than share one copied Context.
    """
    return dict(_overrides.get() or {})


def active_override_vars():
    """Env-var names with a binding right now — for logging/tests only.

    Deliberately returns the NAMES, never the values, so a breadcrumb can
    record that a per-call key was used without putting a secret in a log.
    """
    return sorted((_overrides.get() or {}).keys())

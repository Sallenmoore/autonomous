"""Shared response-extraction helper for AI provider adapters.

Originated as a private helper in ``openai_compat`` (issue #92) and is now
shared so ``local_model`` and ``flux`` can adopt the same typed-exception
translation (issue #142). Keeping the helper here — not in
``openai_compat`` or ``exceptions`` — avoids a cross-adapter import that
would couple ``local_model`` to ``openai_compat`` purely for a utility.

The helper takes a ``requests.Response``, an endpoint label, and an
``extractor`` callable that walks the parsed body. Any member of
``MALFORMED_2XX_EXCEPTIONS`` raised inside ``response.json()`` or the
extractor is translated to ``MalformedResponseError.from_response(...)``
with the endpoint label and a defensive body excerpt preserved.

This pattern is the consolidation gate for issue #146
(``JSONGenerationMixin`` extraction).
"""

from autonomous.ai.exceptions import (
    MALFORMED_2XX_EXCEPTIONS,
    MalformedResponseError,
)


def extract_or_malformed(response, endpoint: str, extractor):
    """Parse ``response.json()``, run ``extractor`` over it, and translate
    the malformed-2xx failure family into ``MalformedResponseError``.

    The ``extractor`` keeps the per-endpoint walk (``body["choices"][0]...``
    vs ``body.get("message", {}).get("content", "")`` vs the transcription
    shape, etc.) at the call site, but the catch tuple
    (``MALFORMED_2XX_EXCEPTIONS``), the ``MalformedResponseError``
    construction, and the defensive ``response.text`` read
    (``from_response``) live in one place — so the walk stays inside the
    protected block (an empty ``{"choices": []}`` still translates instead
    of leaking ``IndexError``) while the boilerplate is DRY.
    """
    try:
        return extractor(response.json())
    except MALFORMED_2XX_EXCEPTIONS as exc:
        raise MalformedResponseError.from_response(
            response,
            f"{endpoint} returned a malformed 2xx body: {exc}",
            endpoint=endpoint,
        ) from exc

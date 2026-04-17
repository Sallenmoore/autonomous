from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Iterable, Iterator

#: Anything the Response constructor accepts as ``body``.
BodyType = bytes | str | Iterable[bytes | str]


@dataclass
class Response:
    """Minimal WSGI-compatible response.

    ``body`` may be:

    - ``bytes`` / ``str`` — sent as a single chunk
    - any iterable of ``bytes`` / ``str`` — each item is yielded as a
      chunk, enabling streaming and chunked transfer encoding when the
      WSGI server supports it
    - a generator — same as iterable; consumed once

    A file-like object can be streamed by passing
    ``iter(lambda: fh.read(8192), b"")`` so the chunk size is explicit.
    """

    status: int = 200
    headers: dict = field(default_factory=dict)
    body: Any = b""

    def __post_init__(self) -> None:
        # Normalize a str to bytes so the simple case stays cheap. Iterables
        # are kept as-is and encoded chunk-by-chunk in ``iter_chunks``.
        if isinstance(self.body, str):
            self.body = self.body.encode("utf-8")

    @property
    def status_line(self) -> str:
        try:
            phrase = HTTPStatus(self.status).phrase
        except ValueError:
            phrase = ""
        return f"{self.status} {phrase}".strip()

    def header_list(self) -> list[tuple[str, str]]:
        return [(str(k), str(v)) for k, v in self.headers.items()]

    def iter_chunks(self) -> Iterator[bytes]:
        """Yield the response body as bytes chunks.

        Single source of truth for ``__iter__`` and ``__call__``. Bytes
        are yielded as-is; ``str`` chunks are utf-8-encoded; bytes
        bodies become a single chunk. An empty bytes body still yields
        one ``b""`` so WSGI servers see a finite iterable.
        """
        body = self.body
        if isinstance(body, (bytes, bytearray)):
            yield bytes(body)
            return
        for chunk in body:
            if isinstance(chunk, str):
                yield chunk.encode("utf-8")
            elif isinstance(chunk, (bytes, bytearray)):
                yield bytes(chunk)
            else:
                # Coerce other types via str() — last resort; explicit
                # bytes are preferred.
                yield str(chunk).encode("utf-8")

    def __iter__(self) -> Iterator[bytes]:
        return self.iter_chunks()

    def __call__(self, environ, start_response) -> Iterator[bytes]:
        start_response(self.status_line, self.header_list())
        return self.iter_chunks()


def redirect(url: str, status: int = 302) -> Response:
    return Response(status=status, headers={"Location": url})

from dataclasses import dataclass, field
from http import HTTPStatus


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self):
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

    def __iter__(self):
        yield self.body

    def __call__(self, environ, start_response):
        start_response(self.status_line, self.header_list())
        return [self.body]


def redirect(url: str, status: int = 302) -> Response:
    return Response(status=status, headers={"Location": url})

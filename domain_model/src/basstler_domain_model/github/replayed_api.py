"""
A local HTTP server standing in for GitHub's API in tests: it answers each request with
a recorded answer, and keeps what it was sent.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# %% what the server is told and sent


@dataclass(frozen=True)
class RecordedAnswer:
    """
    What one request is answered with.
    """

    status: HTTPStatus
    """
    The status to answer with.
    """

    body: str = ""
    """
    The body to answer with, empty for none.
    """

    headers: Mapping[str, str] = field(default_factory=dict)
    """
    Headers to answer with besides the body's length, such as ``Location`` or ``Link``.
    """

    @classmethod
    def from_file(cls, status: HTTPStatus, recording: Path) -> RecordedAnswer:
        """
        :param status: The status to answer with.
        :param recording: A file holding the body to answer with.
        :return: The answer.
        """
        return cls(status, recording.read_text())


@dataclass(frozen=True)
class SentRequest:
    """
    One request the server received.
    """

    method: str
    """
    Its HTTP method.
    """

    path: str
    """
    Its path, query included.
    """

    payload: Any
    """
    Its decoded JSON body, ``None`` when it had none.
    """

    authorization: str | None
    """
    Its ``Authorization`` header, ``None`` when it carried none.
    """


# %% the server


@dataclass
class ReplayedApi:
    """
    Answers each ``(method, path)`` with the answer recorded for it, and anything else
    with a 404 naming what was asked.
    """

    answers: dict[tuple[str, str], RecordedAnswer] = field(default_factory=dict)
    """
    The answer to each method and path, query included; filled before or while the
    server runs.
    """

    sent: list[SentRequest] = field(default_factory=list)
    """
    Every request received, in order.
    """

    def __enter__(self) -> ReplayedApi:
        """:return: This server, now answering."""
        replayed = self

        class Handler(BaseHTTPRequestHandler):
            """
            Hands every request to the server's recordings.
            """

            def answer(self) -> None:
                """
                Record the request and send back the recorded answer.
                """
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                replayed.sent.append(
                    SentRequest(
                        self.command,
                        self.path,
                        json.loads(raw) if raw else None,
                        self.headers.get("Authorization"),
                    )
                )
                recorded = replayed.answers.get(
                    (self.command, self.path),
                    RecordedAnswer(
                        HTTPStatus.NOT_FOUND,
                        json.dumps(
                            {
                                "message": f"no recorded answer for {self.command} {self.path}"
                            }
                        ),
                    ),
                )
                body = recorded.body.encode()
                self.send_response(recorded.status)
                for name, value in recorded.headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = answer

            def log_message(self, *arguments: Any) -> None:
                """Keep the test output free of request logs."""

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exception: Any) -> None:
        """Stop answering."""
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self) -> str:
        """:return: Where the server answers, in the form of an API root."""
        host, port = self.server.server_address
        return f"http://{host}:{port}"

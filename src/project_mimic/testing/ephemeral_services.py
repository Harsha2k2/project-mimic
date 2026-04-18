"""Ephemeral integration service harness for local tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Iterator


@dataclass(frozen=True)
class EphemeralIntegrationEnvironment:
    triton_endpoint: str


class _TritonHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
        if not self.path.endswith("/infer"):
            self.send_response(404)
            self.end_headers()
            return

        body_length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(body_length)

        payload = {
            "entities": [
                {
                    "entity_id": "e1",
                    "label": "Search",
                    "role": "button",
                    "text": "Search Flights",
                    "x": 101,
                    "y": 102,
                    "width": 120,
                    "height": 40,
                    "confidence": 0.92,
                }
            ]
        }
        encoded = json.dumps(payload).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args) -> None:  # noqa: A003
        # Keep test output clean.
        return


@contextmanager
def ephemeral_integration_environment() -> Iterator[EphemeralIntegrationEnvironment]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TritonHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address
    endpoint = f"http://{host}:{port}"

    try:
        yield EphemeralIntegrationEnvironment(triton_endpoint=endpoint)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)

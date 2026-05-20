"""Local HTTP server for the observatory dashboard.

stdlib only — no FastAPI / Flask / Starlette. Single-threaded is fine for
a localhost dashboard that polls a small JSON state. Two endpoints:

- GET /              → the HTML page (templates.INDEX_HTML)
- GET /api/state     → JSON of the current state (state.collect(...))

Run via `app ui` (see cli.py).
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from app.ui.state import collect
from app.ui.templates import INDEX_HTML


def make_handler(artifacts_root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # noqa: D401
            # Quieter logs — only print errors.
            if args and len(args) > 1 and str(args[1]).startswith(("4", "5")):
                super().log_message(fmt, *args)

        def do_GET(self) -> None:  # noqa: N802 — stdlib signature
            if self.path == "/" or self.path.startswith("/index"):
                body = INDEX_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/api/state":
                state = collect(artifacts_root)
                body = json.dumps(state, default=str).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"not found")

    return Handler


class _ReusableHTTPServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR so a recent crash doesn't block the next launch."""
    allow_reuse_address = True


def serve(artifacts_root: Path, *, host: str = "127.0.0.1", port: int = 8787, open_browser: bool = True) -> None:
    artifacts_root = artifacts_root.resolve()
    handler_cls = make_handler(artifacts_root)
    httpd = _ReusableHTTPServer((host, port), handler_cls)
    url = f"http://{host}:{port}/"
    print(f"Observatory listening at {url}")
    print(f"Artifacts root: {artifacts_root}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()

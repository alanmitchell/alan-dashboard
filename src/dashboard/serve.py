"""The long-running process: serve the page cron generates.

Cloud in a Bottle routes HTTP to the container, so the app has to answer on a
socket -- writing the file alone is not enough.  This is deliberately a plain
stdlib server: it serves exactly one document plus a health check, so there is
nothing here worth a framework or an extra 30 MB of image.

TLS, authentication and access control are the router's job, not ours; the
manifest leaves ``public_paths`` empty so every path requires the owner's login.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config, apply_process_timezone

log = logging.getLogger("dashboard.serve")

_PLACEHOLDER = """<!doctype html>
<title>Preparing dashboard</title>
<meta http-equiv="refresh" content="10">
<style>
  body { font: 16px system-ui, -apple-system, "Segoe UI", sans-serif;
         display: grid; place-items: center; min-height: 90vh; margin: 0;
         color: #52514e; background: #f9f9f7; }
  @media (prefers-color-scheme: dark) { body { color: #c3c2b7; background: #0d0d0d; } }
</style>
<p>Building the dashboard&hellip; this page refreshes itself.</p>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "alan-dashboard"
    protocol_version = "HTTP/1.1"
    config: Config

    def do_GET(self) -> None:  # noqa: N802  (stdlib naming)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"

        if path == "/healthz":
            self._respond(HTTPStatus.OK, "text/plain; charset=utf-8", b"ok")
            return
        if path != "/":
            self._respond(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found")
            return

        index = self.config.index_path
        try:
            body = index.read_bytes()
        except FileNotFoundError:
            # Cron has not produced a page yet (first boot, or a wiped temp
            # tier). Say so honestly and let the browser retry.
            self._respond(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "text/html; charset=utf-8",
                _PLACEHOLDER.encode("utf-8"),
                extra={"Retry-After": "10"},
            )
            return

        stamp = datetime.fromtimestamp(index.stat().st_mtime, tz=timezone.utc)
        self._respond(
            HTTPStatus.OK,
            "text/html; charset=utf-8",
            body,
            extra={
                # The document is rewritten every 30 minutes; never let a proxy
                # or the browser hold a stale copy.
                "Cache-Control": "no-store, must-revalidate",
                "Last-Modified": stamp.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            },
        )

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def _respond(self, status, content_type, body, extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        # Route access logs through logging so `bottle logs` sees them, and so
        # the health check does not drown out everything else.
        if "/healthz" in (args[0] if args else ""):
            return
        log.info("%s %s", self.address_string(), format % args)


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    config = Config.from_env()
    apply_process_timezone(config)
    Handler.config = config

    server = ThreadingHTTPServer((config.host, config.port), Handler)
    server.daemon_threads = True
    log.info("serving %s on http://%s:%d", config.index_path, config.host, config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

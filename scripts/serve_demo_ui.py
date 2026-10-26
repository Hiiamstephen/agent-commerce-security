"""Serve the interactive demo UI and isolated replay on loopback only."""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets

from demo_step6 import run_demo

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs" / "demo-visualizer.html"
SVG = ROOT / "docs" / "architecture.svg"


def handler_for(token: str):
    class DemoHandler(BaseHTTPRequestHandler):
        def respond(self, status: int, payload: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path in ("/", "/demo-visualizer.html"):
                page = HTML.read_text(encoding="utf-8").replace("__DEMO_SERVER_TOKEN__", token)
                self.respond(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/architecture.svg":
                self.respond(200, SVG.read_bytes(), "image/svg+xml")
            elif self.path in ("/demo-guide.md", "/step6-verification.md"):
                document = ROOT / "docs" / self.path.removeprefix("/")
                self.respond(200, document.read_bytes(), "text/markdown; charset=utf-8")
            else:
                self.respond(404, b"Not found", "text/plain; charset=utf-8")

        def do_POST(self):
            if self.path != "/api/demo":
                self.respond(404, b"Not found", "text/plain; charset=utf-8")
                return
            if self.headers.get("X-Demo-Token") != token:
                self.respond(403, b'{"error":"invalid demo token"}', "application/json")
                return
            if self.headers.get("Content-Length") not in (None, "0"):
                self.respond(400, b'{"error":"request body not accepted"}', "application/json")
                return
            try:
                result = run_demo()
            except Exception:
                self.respond(500, b'{"error":"local demo failed; see terminal"}', "application/json")
                raise
            self.respond(200, json.dumps(result).encode("utf-8"), "application/json")

    return DemoHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1–65535")
    server = HTTPServer(("127.0.0.1", args.port), handler_for(secrets.token_urlsafe(24)))
    print(f"Demo UI: http://127.0.0.1:{args.port}/", flush=True)
    print("Runs use temporary SQLite, an ephemeral token, and synthetic data. Ctrl-C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

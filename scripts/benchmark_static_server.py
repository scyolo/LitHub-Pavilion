"""Loopback-only production-asset benchmark server with a shared bandwidth cap.

Example: python scripts/benchmark_static_server.py frontend/dist --port 5182 --mbps 4 --latency-ms 80
All page and Web Worker requests share the cap; this is not a per-request delay
masquerading as aggregate bandwidth. No collector/database or external requests.
"""

import argparse
import gzip
import json
import mimetypes
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Bandwidth:
    def __init__(self, bytes_per_second):
        self.rate = bytes_per_second
        self.lock = threading.Lock()
        self.next_time = time.monotonic()

    def reserve(self, size):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_time)
            self.next_time = start + size / self.rate
            wait = self.next_time - now
        time.sleep(wait)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, root, bandwidth, latency, **kwargs):
        self.root, self.bandwidth, self.latency = root, bandwidth, latency
        super().__init__(*args, **kwargs)

    def do_GET(self):
        relative = unquote(urlsplit(self.path).path).lstrip("/") or "index.html"
        file = (self.root / relative).resolve()
        if not file.is_relative_to(self.root) or not file.is_file():
            self.send_error(404)
            return
        data = file.read_bytes()
        encoded = (
            not file.name.endswith(".gz")
            and file.suffix in {".js", ".css", ".json", ".html", ".svg"}
            and "gzip" in self.headers.get("Accept-Encoding", "")
        )
        if encoded:
            data = gzip.compress(data, mtime=0)
        time.sleep(self.latency)
        self.send_response(200)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(file.name)[0] or "application/octet-stream",
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Cache-Control",
            "no-cache"
            if file.name in {"index.html", "manifest.json"}
            else "public, max-age=31536000, immutable",
        )
        if encoded:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        try:
            for offset in range(0, len(data), 8192):
                part = data[offset : offset + 8192]
                self.bandwidth.reserve(len(part))
                self.wfile.write(part)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        print(
            json.dumps(
                {"time": time.time(), "path": relative, "body_bytes": len(data)}
            ),
            flush=True,
        )

    def log_message(self, *_args):
        pass


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--port", type=int, default=5182)
    p.add_argument("--mbps", type=float, default=4)
    p.add_argument("--latency-ms", type=float, default=80)
    args = p.parse_args()
    root = args.directory.resolve()
    if (
        not (root / "index.html").is_file()
        or not 0 < args.mbps <= 1000
        or not 0 <= args.latency_ms <= 10000
    ):
        p.error("Existing production build and valid network limits required")
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        partial(
            Handler,
            root=root,
            bandwidth=Bandwidth(args.mbps * 1_000_000 / 8),
            latency=args.latency_ms / 1000,
        ),
    )
    print(
        json.dumps(
            {
                "root": str(root),
                "port": args.port,
                "aggregate_mbps": args.mbps,
                "response_latency_ms": args.latency_ms,
            }
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

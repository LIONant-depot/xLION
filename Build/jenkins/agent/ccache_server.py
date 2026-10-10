#!/usr/bin/env python3
"""A tiny remote storage for ccache (its HTTP backend: PUT, GET, HEAD, DELETE of one entry per URL), so the CI machines share what they compile.

    python3 ccache_server.py --dir /var/lib/ccache-remote --listen 51.79.242.89 --port 8089

The machines that may use it are limited by the firewall (ufw allow from <ip> to any port 8089): there is no password here. An entry is a file; a path is mapped to a flat, safe file name
(no directory can be reached). The oldest files are removed when the folder is over --max-gb (checked after each PUT, at most every 5 minutes).
Setup and the ccache side: documentation/Linux/jenkins.md, Build/jenkins/agent/setup_ccache_remote.sh.
"""
import argparse
import hashlib
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = None
_trim_lock = threading.Lock()
_last_trim = [0.0]


def name_of(path: str) -> str:
    """/ab/cdef... -> ab_cdef...: only hex, dashes and underscores survive (a ccache key); anything else becomes a hash, so no path can leave the folder."""
    flat = path.strip("/").replace("/", "_")
    if flat and all(c in "0123456789abcdefABCDEF_-" for c in flat) and len(flat) < 200:
        return flat
    return "x_" + hashlib.sha1(path.encode()).hexdigest()


def trim() -> None:
    now = time.time()
    with _trim_lock:
        if now - _last_trim[0] < 300:
            return
        _last_trim[0] = now
        files = []
        total = 0
        for e in os.scandir(ARGS.dir):
            if e.is_file() and not e.name.endswith(".tmp"):
                st = e.stat()
                files.append((st.st_atime, st.st_size, e.path))
                total += st.st_size
        limit = ARGS.max_gb * 1024 ** 3
        files.sort()                                    # oldest use first
        for _, size, path in files:
            if total <= limit * 0.9:
                break
            try:
                os.remove(path)
                total -= size
            except OSError:
                pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):                     # quiet: ccache asks for every object
        pass

    def _file(self) -> str:
        return os.path.join(ARGS.dir, name_of(self.path.split("?")[0]))

    def _reply(self, code: int, body: bytes = b"", head: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and not head:
            self.wfile.write(body)

    def do_GET(self, head: bool = False) -> None:
        p = self._file()
        try:
            with open(p, "rb") as f:
                data = f.read()
            os.utime(p, None)                           # a hit counts as a use: what is wanted stays
        except OSError:
            return self._reply(404, head=head)
        self._reply(200, data, head)

    def do_HEAD(self) -> None:
        self.do_GET(head=True)

    def do_PUT(self) -> None:
        n = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(n)
        p = self._file()
        tmp = f"{p}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)                              # whole or not at all
        self._reply(201)
        trim()

    def do_DELETE(self) -> None:
        try:
            os.remove(self._file())
        except OSError:
            return self._reply(404)
        self._reply(204)


def main() -> None:
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--listen", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8089)
    ap.add_argument("--max-gb", type=float, default=8.0)
    ARGS = ap.parse_args()
    os.makedirs(ARGS.dir, exist_ok=True)
    ThreadingHTTPServer.request_queue_size = 128         # the default (5) is small for a build that asks for every object at once
    ThreadingHTTPServer((ARGS.listen, ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

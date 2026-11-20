"""Shared fixtures."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def http_server():
    """start(handler class) -> base URL: serves it on 127.0.0.1 in a thread until teardown.
    The mold of every http.server fixture here; each one only writes its handler."""
    started = []

    def start(handler):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        srv.daemon_threads = True
        t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        t.start()
        started.append((srv, t))
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    for srv, t in started:
        srv.shutdown()
        srv.server_close()
        t.join(5)


@pytest.fixture
def server(http_server):
    script, seen = {}, []

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.path)
            reply = script.get(self.path, (404, {}, b"nope"))
            # a callable reply answers from the request headers (conditional GETs)
            status, hdrs, body = reply(self.headers) if callable(reply) else reply
            self.send_response(status)
            for k, v in hdrs.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    yield http_server(H), script, seen


@pytest.fixture
def raw_server():
    """start(reply bytes) -> (base URL, heads): answers every connection with `reply`, then
    closes. heads gets each request's raw bytes up to the blank line, in wire order and case
    (replies http.server cannot fake, requests it would normalize); a TLS ClientHello is
    kept as its first read, and the connection closed unanswered."""
    stops, threads = [], []

    def start(reply: bytes):
        heads, stop = [], threading.Event()
        lsock = socket.create_server(("127.0.0.1", 0))
        lsock.settimeout(0.05)

        def serve():
            with lsock:
                while not stop.is_set():
                    try:
                        conn, _ = lsock.accept()
                    except socket.timeout:
                        continue
                    with conn:
                        conn.settimeout(5)
                        data = conn.recv(65536)
                        if data.startswith(b"\x16"):  # a TLS handshake record
                            heads.append(data)
                            continue
                        while b"\r\n\r\n" not in data and (got := conn.recv(65536)):
                            data += got
                        heads.append(data)
                        conn.sendall(reply)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        stops.append(stop)
        threads.append(t)
        return f"http://127.0.0.1:{lsock.getsockname()[1]}", heads

    yield start
    for stop in stops:
        stop.set()
    for t in threads:
        t.join(5)

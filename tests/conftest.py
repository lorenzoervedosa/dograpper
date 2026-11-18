"""Shared fixtures."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


# Second copy of the local-server fixture in test_httrack_fetcher.py (which keeps its own:
# queued replies, dropped connections, request headers); factor it out on the third.
@pytest.fixture
def server():
    script, seen = {}, []

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.path)
            status, hdrs, body = script.get(self.path, (404, {}, b"nope"))
            self.send_response(status)
            for k, v in hdrs.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", script, seen
    srv.shutdown()
    srv.server_close()
    t.join(5)

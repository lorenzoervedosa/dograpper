"""Log each client's raw TLS ClientHello and HTTP request header lines.

shortcut: fixture-capture tool, not product code; exercised only by the HTTrack capture run.
Usage: python3 -I capture.py PORT CERT KEY OUT_JSONL
"""
import json
import socket
import socketserver
import ssl
import struct
import sys
import threading

EXT_NAMES = {0: "server_name", 5: "status_request", 10: "supported_groups",
             11: "ec_point_formats", 13: "signature_algorithms", 16: "alpn",
             18: "sct", 21: "padding", 22: "encrypt_then_mac", 23: "extended_master_secret",
             27: "compress_certificate", 28: "record_size_limit", 35: "session_ticket",
             41: "pre_shared_key", 43: "supported_versions", 45: "psk_key_exchange_modes",
             49: "post_handshake_auth", 50: "signature_algorithms_cert", 51: "key_share",
             65281: "renegotiation_info"}

LOCK = threading.Lock()


def u16_list(b):
    return [struct.unpack(">H", b[i:i + 2])[0] for i in range(0, len(b), 2)]


def parse_client_hello(rec):
    assert rec[0] == 0x16, "not a TLS handshake record"
    body = rec[5:]
    assert body[0] == 1, "not a ClientHello"
    p = 4
    out = {"legacy_version": hex(struct.unpack(">H", body[p:p + 2])[0])}
    p += 2 + 32
    sid_len = body[p]; p += 1 + sid_len
    out["session_id_len"] = sid_len
    cs_len = struct.unpack(">H", body[p:p + 2])[0]; p += 2
    out["cipher_suites"] = [hex(c) for c in u16_list(body[p:p + cs_len])]; p += cs_len
    comp_len = body[p]; p += 1 + comp_len
    ext_total = struct.unpack(">H", body[p:p + 2])[0]; p += 2
    end = p + ext_total
    exts = []
    while p < end:
        etype, elen = struct.unpack(">HH", body[p:p + 4]); p += 4
        data = body[p:p + elen]; p += elen
        e = {"type": etype, "name": EXT_NAMES.get(etype, "?"), "len": elen}
        if etype == 10:
            e["groups"] = [hex(g) for g in u16_list(data[2:])]
        elif etype == 13:
            e["algs"] = [hex(a) for a in u16_list(data[2:])]
        elif etype == 43:
            e["versions"] = [hex(v) for v in u16_list(data[1:])]
        elif etype == 51:
            q, shares = 2, []
            while q < len(data):
                g, kl = struct.unpack(">HH", data[q:q + 4]); q += 4 + kl
                shares.append({"group": hex(g), "key_len": kl})
            e["shares"] = shares
        elif etype == 16:
            q, protos = 2, []
            while q < len(data):
                n = data[q]; protos.append(data[q + 1:q + 1 + n].decode()); q += 1 + n
            e["protocols"] = protos
        elif etype == 11:
            e["formats"] = list(data[1:])
        elif etype == 45:
            e["modes"] = list(data[1:])
        exts.append(e)
    out["extensions"] = exts
    return out


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        buf = b""
        while len(buf) < 5 or len(buf) < 5 + struct.unpack(">H", buf[3:5])[0]:
            chunk = sock.recv(65536, socket.MSG_PEEK)
            if not chunk or len(chunk) == len(buf):
                break
            buf = chunk
        record = {"peer": self.client_address[1]}
        try:
            record["client_hello"] = parse_client_hello(buf)
        except Exception as exc:  # spike: record and keep going
            record["client_hello_error"] = repr(exc)
        try:
            tls = self.server.ctx.wrap_socket(sock, server_side=True)
            record["negotiated"] = [tls.version(), tls.cipher()[0], tls.selected_alpn_protocol()]
            raw = b""
            while b"\r\n\r\n" not in raw:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                raw += chunk
            lines = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
            record["request_line"] = lines[0]
            record["headers"] = lines[1:]
            path = lines[0].split(" ")[1] if " " in lines[0] else "/"
            if path == "/robots.txt":
                resp = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            else:
                body = b'<a href="/a.html">a</a>' if path == "/" else b"plain page"
                html = b"<html><head><title>t</title></head><body>" + body + b"</body></html>"
                resp = (b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                        + str(len(html)).encode() + b"\r\nConnection: close\r\n\r\n" + html)
            tls.sendall(resp)
            tls.close()
        except Exception as exc:
            record["tls_error"] = repr(exc)
        with LOCK, open(self.server.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port, cert, key, out = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    srv = Server(("127.0.0.1", port), Handler)
    srv.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    srv.ctx.load_cert_chain(cert, key)
    srv.out = out
    srv.serve_forever()

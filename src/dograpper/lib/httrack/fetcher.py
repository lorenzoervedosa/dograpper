"""Polite HTTP fetcher: paced, retrying, redirect-blind. One instance is shared by all workers."""

import http.client
import logging
import math
import threading
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

from ...utils.redact import redact_url
from .challenge import is_challenge
from .escape import request_target
from .policy import ZSTD_MAX_WINDOW, HttrackPolicy, decoder_module, make_ssl_context, request_headers
from .robots import NO_RULES, RobotsRules, parse_robots

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024 * 1024  # raw stream and every decoded stage
MAX_ENCODINGS = 2
MAX_MEMBERS = 64  # gzip members / zstd frames per body; more is an error, never a partial body
MAX_ROBOTS_REDIRECTS = 5
RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 504})  # 503 only with Retry-After
REDIRECTS = frozenset({301, 302, 303, 307, 308})
CHUNK = 64 * 1024
_STALE = (ConnectionError, http.client.CannotSendRequest)


@dataclass
class FetchResult:
    url: str
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    location: str | None = None
    error: str | None = None
    challenged: bool = False
    attempts: int = 0


def _check(out) -> None:
    if len(out) > MAX_BODY_BYTES:
        raise ValueError("body too large")


def _members(data: bytes, new, count: int = MAX_MEMBERS, max_length: bool = True) -> bytes:
    """Every back-to-back member/frame (at most `count`), all or nothing, in time linear in
    len(data). Input goes in bounded slices: the decoders copy what they do not consume into
    unused_data, so feeding the whole remainder per member would be quadratic."""
    # a decoder without max_length gets tiny slices (a zstd block expands <= 128 KiB per few bytes)
    view, pos, out, step = memoryview(data), 0, bytearray(), CHUNK if max_length else 64
    for _ in range(count):
        d = new()
        while not d.eof:
            if pos >= len(data):
                raise ValueError("truncated compressed stream")
            piece = view[pos:pos + step]
            pos += len(piece)
            out += d.decompress(piece, MAX_BODY_BYTES - len(out) + 1) if max_length \
                else d.decompress(piece)
            _check(out)
        pos -= len(d.unused_data)
        if pos == len(data):
            return bytes(out)
    raise ValueError("trailing data after compressed stream" if count == 1
                     else "too many compressed members")


def _deflate(data: bytes) -> bytes:
    try:
        return _members(data, lambda: zlib.decompressobj(zlib.MAX_WBITS), 1)
    except zlib.error:  # raw deflate, as many servers send
        return _members(data, lambda: zlib.decompressobj(-zlib.MAX_WBITS), 1)


def _brotli(mod, data: bytes) -> bytes:
    d, out = mod.Decompressor(), bytearray()
    chunk = d.process(data, output_buffer_limit=CHUNK)
    while True:
        if len(out) + len(chunk) > MAX_BODY_BYTES:  # projected size, before appending
            raise ValueError("body too large")
        out += chunk
        if d.is_finished():
            return bytes(out)
        chunk = d.process(b"", output_buffer_limit=CHUNK)
        if not chunk and d.can_accept_more_data():  # wants input we do not have
            raise ValueError("truncated compressed stream")


def _zstd(mod, data: bytes) -> bytes:
    """All frames, bounded in total; junk, truncation or an oversized window is an error."""
    if mod.__name__ == "compression.zstd":
        opts = {mod.DecompressionParameter.window_log_max: ZSTD_MAX_WINDOW.bit_length() - 1}
        return _members(data, lambda: mod.ZstdDecompressor(options=opts))
    return _members(data, lambda: mod.ZstdDecompressor(max_window_size=ZSTD_MAX_WINDOW)
                    .decompressobj(), max_length=False)


def _decode(body: bytes, encoding: str) -> bytes:
    if not body:  # 204/3xx and HEAD-like replies carry an empty body whatever the encoding
        return body
    encs = [e.strip().lower() for e in encoding.split(",") if e.strip()]
    if len(encs) > MAX_ENCODINGS:
        raise ValueError("too many stacked content-encodings")
    for enc in reversed(encs):
        if enc in ("gzip", "x-gzip"):
            body = _members(body, lambda: zlib.decompressobj(16 + zlib.MAX_WBITS))
        elif enc == "deflate":
            body = _deflate(body)
        elif enc in ("br", "zstd") and (mod := decoder_module(enc)) is not None:
            body = (_brotli if enc == "br" else _zstd)(mod, body)
        elif enc != "identity":
            raise ValueError(f"unsupported content-encoding: {enc}")
    return body


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        secs = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        secs = (when - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, secs) if math.isfinite(secs) else None


def _origin(url: str) -> tuple[str, str]:
    """Normalised (scheme, host[:port]); ValueError for unusable URLs (bad port, no host)."""
    p = urlsplit(url)
    host, port = p.hostname, p.port
    if p.scheme not in ("http", "https") or not host:
        raise ValueError("unsupported or invalid URL")
    if ":" in host:
        host = f"[{host}]"
    return p.scheme, host + (f":{port}" if port is not None else "")


def same_host(a: str, b: str) -> bool:
    """Redirect scope: same hostname (urlsplit lowercases it); scheme and port may differ.
    False when either URL is unparseable."""
    try:
        return urlsplit(a).hostname == urlsplit(b).hostname
    except ValueError:
        return False


def _wire_host(parts) -> str:
    """Host header value: netloc without userinfo, a non-ASCII name IDNA-encoded
    (UnicodeError, a ValueError, when IDNA cannot encode it)."""
    host = parts.netloc.rpartition("@")[2]
    if host.isascii():
        return host
    name, sep, port = host.partition(":")  # a non-ASCII host is never an IPv6 literal
    return name.encode("idna").decode("ascii") + sep + port


class Fetcher:
    def __init__(self, policy: HttrackPolicy, *, clock=time.monotonic, sleep=time.sleep):
        self.policy = policy
        self._clock, self._sleep = clock, sleep
        self._ssl = make_ssl_context()
        self._local = threading.local()
        self._lock = threading.Lock()  # guards every pacing field below
        self._conn_next = 0.0
        self._bw_next = 0.0
        self._gate_until = 0.0
        self._host_next: dict[tuple[str, str], float] = {}
        self._robots: dict[str, RobotsRules] = {}
        self._delays: dict[str, float] = {}  # sanitised crawl-delay per origin
        # shortcut: one lock serialises robots fetches across hosts; fine for single-host crawls
        self._robots_lock = threading.Lock()

    # -- pacing: a slot is committed only once the Retry-After gate and every schedule allow
    # "now"; a worker that slept re-checks, so a gate set meanwhile is honoured (HTTrack
    # checks at launch time) --

    def _acquire(self, key: tuple[str, str] | None = None, conn: bool = False) -> None:
        while True:
            with self._lock:
                now = self._clock()
                start = max(now, self._gate_until)
                if key:
                    start = max(start, self._host_next.get(key, 0.0))
                if conn:
                    start = max(start, self._conn_next)
                if start <= now:
                    if key:
                        gap = max(self.policy.delay_ms / 1000,
                                  self._delays.get(f"{key[0]}://{key[1]}", 0.0))
                        self._host_next[key] = now + gap
                    if conn:
                        self._conn_next = now + 1 / self.policy.max_conn_rate
                    return
            self._sleep(start - now)

    def _charge_bandwidth(self, nbytes: int) -> None:
        with self._lock:
            now = self._clock()
            self._bw_next = max(now, self._bw_next) + nbytes / self.policy.max_bandwidth
            wait = self._bw_next - now
        if wait > 0:
            self._sleep(wait)

    def _set_gate(self, url: str, seconds: float) -> None:
        if seconds > self.policy.max_retry_after:
            logger.warning("Retry-After %ss for %s capped to %ss", seconds, redact_url(url),
                           self.policy.max_retry_after)
            seconds = self.policy.max_retry_after
        if seconds > 0:
            with self._lock:
                self._gate_until = max(self._gate_until, self._clock() + seconds)

    # -- transport --

    def _connect(self, parts) -> http.client.HTTPConnection:
        self._acquire(conn=True)
        if parts.scheme == "https":
            return http.client.HTTPSConnection(parts.hostname, parts.port,
                                               timeout=self.policy.timeout, context=self._ssl)
        return http.client.HTTPConnection(parts.hostname, parts.port, timeout=self.policy.timeout)

    def _request(self, key, parts, target, headers):
        conns = self._local.__dict__.setdefault("conns", {})
        for _ in range(2):
            conn = conns.get(key)
            fresh = conn is None
            if fresh:
                conn = conns[key] = self._connect(parts)
            try:
                conn.putrequest("GET", target, skip_host=True, skip_accept_encoding=True)
                for k, v in headers:
                    conn.putheader(k, v)
                conn.endheaders()
                resp = conn.getresponse()
                chunks, total = [], 0
                while chunk := resp.read(CHUNK):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_BODY_BYTES:
                        conn.close()
                        conns.pop(key, None)
                        raise ValueError("body too large")
                    self._charge_bandwidth(len(chunk))
                if resp.length:  # peer closed before Content-Length: HTTrack's "Incorrect length"
                    raise http.client.IncompleteRead(b"".join(chunks), resp.length)
                hdrs = {k.lower(): v for k, v in resp.getheaders()}
                if resp.will_close:
                    conn.close()
                    conns.pop(key, None)
                return resp.status, hdrs, b"".join(chunks)
            except (OSError, http.client.HTTPException) as exc:
                conn.close()
                conns.pop(key, None)
                if fresh or not isinstance(exc, _STALE):
                    raise
                # dropped keep-alive: loop once more on a fresh connection

    # -- public --

    def get(self, url: str, *, kind: str, referer: str | None = None) -> FetchResult:
        res = FetchResult(url)
        try:
            parts, key = urlsplit(url), _origin(url)
            host, target = _wire_host(parts), request_target(parts)
        except ValueError:
            res.error = "invalid URL"
            return res
        headers = request_headers(self.policy, host, kind=kind, referer=referer, scheme=key[0])
        for attempt in range(1, self.policy.retries + 2):
            res.attempts = attempt
            self._acquire(key)
            try:
                status, hdrs, raw = self._request(key, parts, target, headers)
            # timeouts, ssl.SSLError, RemoteDisconnected; short bodies (htsback.c: recatch)
            except (OSError, http.client.IncompleteRead) as exc:
                res.error = f"{type(exc).__name__}: {exc}"
                if attempt <= self.policy.retries:
                    continue
                return res
            except http.client.HTTPException as exc:
                res.error = f"{type(exc).__name__}: {exc}"
                return res
            except ValueError as exc:  # body too large, or a header value http.client refuses
                res.error = str(exc)
                return res
            res.error = None
            res.status, res.headers = status, hdrs
            ra = _parse_retry_after(hdrs.get("retry-after"))
            if status in (429, 503) and ra is not None:
                self._set_gate(url, ra)
            if (status in RETRY_STATUSES or (status == 503 and ra is not None)) \
                    and attempt <= self.policy.retries:
                continue
            res.location = hdrs.get("location")  # independent of body decoding
            try:
                res.body = _decode(raw, hdrs.get("content-encoding", ""))
            except Exception as exc:  # zlib/brotli/zstd errors differ per codec; surfaced, not hidden
                res.error = f"decode failed: {type(exc).__name__}: {exc}"
                return res
            res.challenged = is_challenge(status, hdrs, res.body)
            return res
        raise AssertionError("unreachable: the last attempt always returns")

    def _fetch_robots(self, origin: str) -> RobotsRules:
        url = origin + "/robots.txt"
        for _ in range(MAX_ROBOTS_REDIRECTS + 1):
            r = self.get(url, kind="robots")
            if r.error is not None:
                return NO_RULES
            if r.status == 200:
                return parse_robots(r.body.decode("utf-8", errors="replace"))
            if r.status not in REDIRECTS or not r.location:
                return NO_RULES
            try:  # same host only; scheme or port may change (http -> https)
                nxt = urljoin(url, r.location)  # ValueError on e.g. "http://[bad"
                _origin(nxt)
            except ValueError:
                return NO_RULES
            if not same_host(origin, nxt):
                return NO_RULES
            url = nxt
        return NO_RULES

    def robots_for(self, scheme_host: str) -> RobotsRules:
        if not self.policy.obey_robots:
            return NO_RULES
        try:
            origin = "%s://%s" % _origin(scheme_host)
        except ValueError:
            logger.warning("robots: unusable host %s", redact_url(scheme_host))
            return NO_RULES
        with self._robots_lock:
            if origin not in self._robots:
                rules = self._fetch_robots(origin)
                delay = rules.crawl_delay
                if delay is None or not math.isfinite(delay) or delay < 0:
                    delay = 0.0
                elif delay > self.policy.max_retry_after:
                    logger.warning("Crawl-delay %ss for %s capped to %ss", delay,
                                   redact_url(origin), self.policy.max_retry_after)
                    delay = float(self.policy.max_retry_after)
                with self._lock:
                    self._robots[origin], self._delays[origin] = rules, delay
            return self._robots[origin]

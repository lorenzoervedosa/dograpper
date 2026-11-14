"""Polite HTTP fetcher: paced, retrying, redirect-blind. One instance is shared by all workers."""

import http.client
import importlib
import logging
import threading
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from .challenge import is_challenge
from .policy import HttrackPolicy, make_ssl_context, request_headers
from .robots import NO_RULES, RobotsRules, parse_robots

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 504})  # 503 only with Retry-After
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


def _zstd_decompress(data: bytes) -> bytes:
    try:
        zstandard = importlib.import_module("zstandard")
        return zstandard.ZstdDecompressor().decompressobj().decompress(data)
    except ImportError:
        return importlib.import_module("compression.zstd").decompress(data)


def _inflate(data: bytes, wbits: int) -> bytes:
    return zlib.decompressobj(wbits).decompress(data)


def _deflate(data: bytes) -> bytes:
    try:
        return _inflate(data, zlib.MAX_WBITS)
    except zlib.error:
        return _inflate(data, -zlib.MAX_WBITS)  # raw deflate, as many servers send


def _decode(body: bytes, encoding: str) -> bytes:
    for enc in reversed([e.strip().lower() for e in encoding.split(",") if e.strip()]):
        if enc in ("gzip", "x-gzip"):
            body = _inflate(body, 16 + zlib.MAX_WBITS)
        elif enc == "deflate":
            body = _deflate(body)
        elif enc == "br":
            body = importlib.import_module("brotli").decompress(body)
        elif enc == "zstd":
            body = _zstd_decompress(body)
        elif enc != "identity":
            raise ValueError(f"unsupported content-encoding: {enc}")
    return body


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


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
        # shortcut: one lock serialises robots fetches across hosts; fine for single-host crawls
        self._robots_lock = threading.Lock()

    # -- pacing (all schedules are reservations: take the slot under the lock, sleep outside) --

    def _reserve(self, attr_next: float, now: float, step: float) -> tuple[float, float]:
        start = max(now, attr_next)
        return start, start + step

    def _wait_for(self, start: float, now: float) -> None:
        if start > now:
            self._sleep(start - now)

    def _pace(self, key: tuple[str, str]) -> None:
        with self._lock:
            now = self._clock()
            start = max(now, self._gate_until)  # global Retry-After gate
            rules = self._robots.get(f"{key[0]}://{key[1]}", NO_RULES)
            gap = max(self.policy.delay_ms / 1000, rules.crawl_delay or 0)
            start = max(start, self._host_next.get(key, 0.0))
            self._host_next[key] = start + gap
        self._wait_for(start, now)

    def _take_conn_token(self) -> None:
        with self._lock:
            now = self._clock()
            start, self._conn_next = self._reserve(self._conn_next, now, 1 / self.policy.max_conn_rate)
        self._wait_for(start, now)

    def _charge_bandwidth(self, nbytes: int) -> None:
        with self._lock:
            now = self._clock()
            start, self._bw_next = self._reserve(self._bw_next, now, nbytes / self.policy.max_bandwidth)
            until = self._bw_next
        self._wait_for(until, now)

    def _set_gate(self, url: str, seconds: float) -> None:
        if seconds > self.policy.max_retry_after:
            logger.warning("Retry-After %ss for %s capped to %ss", seconds, url,
                           self.policy.max_retry_after)
            seconds = self.policy.max_retry_after
        if seconds > 0:
            with self._lock:
                self._gate_until = max(self._gate_until, self._clock() + seconds)

    # -- transport --

    def _connect(self, scheme: str, parts) -> http.client.HTTPConnection:
        self._take_conn_token()
        port = parts.port
        if scheme == "https":
            return http.client.HTTPSConnection(parts.hostname, port, timeout=self.policy.timeout,
                                               context=self._ssl)
        return http.client.HTTPConnection(parts.hostname, port, timeout=self.policy.timeout)

    def _request(self, key, parts, headers):
        conns = self._local.__dict__.setdefault("conns", {})
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        for _ in range(2):
            conn = conns.get(key)
            fresh = conn is None
            if fresh:
                conn = conns[key] = self._connect(parts.scheme, parts)
            try:
                conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
                for k, v in headers:
                    conn.putheader(k, v)
                conn.endheaders()
                resp = conn.getresponse()
                chunks = []
                while chunk := resp.read(CHUNK):
                    chunks.append(chunk)
                    self._charge_bandwidth(len(chunk))
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
        parts = urlsplit(url)
        key = (parts.scheme, parts.netloc.rpartition("@")[2])
        headers = request_headers(self.policy, key[1], kind=kind, referer=referer)
        res = FetchResult(url)
        for attempt in range(1, self.policy.retries + 2):
            res.attempts = attempt
            self._pace(key)
            try:
                status, hdrs, raw = self._request(key, parts, headers)
            except http.client.HTTPException as exc:
                res.error = f"{type(exc).__name__}: {exc}"
                return res
            except OSError as exc:  # timeouts and ssl.SSLError are OSErrors
                res.error = f"{type(exc).__name__}: {exc}"
                if attempt <= self.policy.retries:
                    continue
                return res
            res.error = None
            res.status, res.headers = status, hdrs
            ra = _parse_retry_after(hdrs.get("retry-after"))
            if status in (429, 503) and ra is not None:
                self._set_gate(url, ra)
            if (status in RETRY_STATUSES or (status == 503 and ra is not None)) \
                    and attempt <= self.policy.retries:
                continue
            try:
                res.body = _decode(raw, hdrs.get("content-encoding", ""))
            except Exception as exc:  # zlib/brotli/zstd errors differ per codec; surfaced, not hidden
                res.error = f"decode failed: {type(exc).__name__}: {exc}"
                return res
            res.location = hdrs.get("location")
            res.challenged = is_challenge(status, hdrs, res.body)
            return res
        return res

    def robots_for(self, scheme_host: str) -> RobotsRules:
        if not self.policy.obey_robots:
            return NO_RULES
        with self._robots_lock:
            if scheme_host not in self._robots:
                r = self.get(scheme_host + "/robots.txt", kind="robots")
                rules = NO_RULES
                if r.error is None and r.status == 200:
                    rules = parse_robots(r.body.decode("utf-8", errors="replace"))
                with self._lock:
                    self._robots[scheme_host] = rules
            return self._robots[scheme_host]

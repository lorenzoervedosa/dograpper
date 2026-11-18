"""Browser-fingerprint transport for the fire-engine downloader (ADR-0011).

``CurlCffiFetcher`` subclasses the httrack ``Fetcher`` and swaps only the wire
call for ``curl_cffi`` with TLS/HTTP-2 impersonation. Every other behaviour --
pacing (connection rate, bandwidth, per-host gap, Retry-After gate), retry,
challenge detection and robots.txt -- is inherited unchanged.

curl hands over the body as it arrived (its decoding is off): the size cap holds in
its writer, and ``Fetcher.get`` decodes it with the bounded httrack decoder, so a
compressed body meets the same limits as on the stdlib path.

``curl_cffi`` is an optional native dependency (contract 1 / ADR-0004): it is
imported lazily, only when a session is first created.
"""
import math
from urllib.parse import unquote, urlunsplit

from ...utils.redact import redact_url
from ..httrack.fetcher import MAX_BODY_BYTES, Fetcher, wire_host

# Of the httrack request headers, only the request-specific ones go to curl; the
# impersonated browser sends its own identity (User-Agent, Accept*, Sec-Fetch-*) (ADR-0011).
_FORWARDED = frozenset({"referer", "if-none-match", "if-modified-since"})

_WRITE_ABORT = 0xFFFFFFFF  # libcurl's CURL_WRITEFUNC_ERROR: the writer stops the transfer

_MISSING = (
    "curl_cffi is required for --downloader fire-engine. "
    "Install it with: uv sync --extra fire-engine"
)


def split_proxy(proxy: str | None) -> tuple[str | None, tuple[str, str] | None]:
    """(`proxy` without user:password, (user, password) percent-decoded, or None). The
    authority is read as curl reads it: an optional scheme://, then up to the first /, ?
    or #. The credentials go to curl as options (curl_cffi proxy_auth), so they are never
    inside a URL its error messages quote."""
    if not proxy:
        return proxy, None
    head, sep, rest = proxy.partition("://")
    if not sep:  # curl takes a bare user:password@host:port as http
        head, rest = "", proxy
    end = min((i for i in map(rest.find, "/?#") if i >= 0), default=len(rest))
    userinfo, at, host = rest[:end].rpartition("@")
    if not at:
        return proxy, None
    url = head + sep + host + rest[end:]
    if not userinfo:
        return url, None
    user, _, password = userinfo.partition(":")
    return url, (unquote(user), unquote(password))


class CurlCffiMissing(RuntimeError):
    """curl_cffi is not installed: raised by the first session, wherever it opens."""


def _default_session_factory(impersonate: str, timeout: float):
    try:
        from curl_cffi import CurlOpt
        from curl_cffi import requests as cffi_requests
    except ImportError as exc:
        raise CurlCffiMissing(_MISSING) from exc
    return cffi_requests.Session(impersonate=impersonate, curl_options={
        CurlOpt.HTTP_CONTENT_DECODING: 0,  # the raw body: Fetcher.get decodes it, bounded
        # the stdlib socket timeout: to connect, then with nothing received
        CurlOpt.CONNECTTIMEOUT_MS: int(timeout * 1000),
        CurlOpt.LOW_SPEED_LIMIT: 1, CurlOpt.LOW_SPEED_TIME: math.ceil(timeout)})


class CurlCffiFetcher(Fetcher):
    """Fetcher whose wire call uses curl_cffi with a browser fingerprint.

    ``proxy`` is a single proxy URL applied to every request (no rotation in
    this slice). ``impersonate`` is a curl_cffi profile (e.g. ``"chrome124"``).
    ``session_factory`` is injectable for tests; the default imports curl_cffi.
    """

    def __init__(self, policy, *, proxy: str | None = None,
                 impersonate: str = "chrome", session_factory=None, **kw):
        super().__init__(policy, **kw)
        self._proxy, self._proxy_auth = split_proxy(proxy)
        self._impersonate = impersonate
        self._session_factory = session_factory or _default_session_factory

    def _session(self):
        session = getattr(self._local, "cffi", None)
        if session is None:
            session = self._local.cffi = self._session_factory(self._impersonate,
                                                               self.policy.timeout)
        return session

    def _request(self, key, parts, target, headers):
        self._acquire(conn=True)  # connection-rate pacing, as the stdlib path does
        # Rebuild the URL from the IDNA host (no userinfo), as the stdlib path puts on the
        # wire, so curl targets exactly what the scope/robots checks validated.
        netloc = wire_host(parts)  # the port included; ValueError on a host the checks reject
        url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
        req_headers = {k: v for k, v in headers if k.lower() in _FORWARDED}
        proxies = ({"http": self._proxy, "https": self._proxy}
                   if self._proxy else None)
        session = self._session()  # outside the try: a missing curl_cffi is no transport error
        chunks, size = [], 0

        def write(chunk):  # curl's writer, in this thread: it paces and bounds the transfer
            nonlocal size
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return _WRITE_ABORT
            chunks.append(chunk)
            self._charge_bandwidth(len(chunk))
            return len(chunk)

        try:
            # timeout=None: the session's curl_options set the stdlib-like timeouts
            resp = session.request("GET", url, headers=req_headers, proxies=proxies,
                                   proxy_auth=self._proxy_auth, timeout=None,
                                   allow_redirects=False, content_callback=write)
        except Exception as exc:  # curl transport error -> inherited retry path
            if size > MAX_BODY_BYTES:
                raise ValueError("body too large") from None
            msg = f"curl_cffi: {type(exc).__name__}: {exc}"
            if self._proxy:  # curl quotes a proxy URL it cannot use (credentials are not in it)
                msg = msg.replace(self._proxy, redact_url(self._proxy))
            raise OSError(msg) from exc
        return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, b"".join(chunks)

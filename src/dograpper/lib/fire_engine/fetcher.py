"""Browser-fingerprint transport for the fire-engine downloader (ADR-0011).

``CurlCffiFetcher`` subclasses the httrack ``Fetcher`` and swaps only the wire
call for ``curl_cffi`` with TLS/HTTP-2 impersonation. Every other behaviour --
pacing (connection rate, bandwidth, per-host gap, Retry-After gate), retry,
challenge detection and robots.txt -- is inherited unchanged.

curl hands over the body as it arrived (its decoding is off): the size cap holds in
its writer, and ``Fetcher.get`` decodes it with the bounded httrack decoder, so a
compressed body meets the same limits as on the stdlib path. The same writer asks a
``stop`` predicate (``Fetcher.get``, HTTrack ``-%s``) at the first chunk and aborts the
transfer when it says so, before any of the body is kept.

``curl_cffi`` is an optional native dependency (contract 1 / ADR-0004): it is
imported lazily, only when a session is first created.
"""
import math
from urllib.parse import unquote, urlunsplit

from ...utils.redact import redact_url
from ..httrack.fetcher import MAX_BODY_BYTES, Fetcher, wire_host

# Of the httrack request headers, only the request-specific ones go to curl; the
# impersonated browser sends its own identity (User-Agent, Accept*, Sec-Fetch-*) (ADR-0011),
# except a User-Agent the user gave, which replaces the profile's (#136 aligns it with Firecrawl).
_FORWARDED = frozenset({"referer", "if-none-match", "if-modified-since"})

# Per-target header values, set before any other header so a user's still wins (#157).
# curl_cffi 0.17's chrome131_android (the chrome_android alias) sends sec-ch-ua-mobile: ?0
# beside an Android UA; a mobile UA sends ?1 (Client Hints). A same-named header takes the
# target's slot, so the order stays the target's.
_TARGET_HEADERS = {target: {"sec-ch-ua-mobile": "?1"}
                   for target in ("chrome_android", "chrome131_android")}

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


def _head(curl) -> tuple[int, dict[str, str]]:
    """The status, Content-Type and Content-Length curl has read (CURLINFO): the headers a
    writer can see mid-transfer, which `stop` (Fetcher.get) decides on."""
    from curl_cffi import CurlInfo  # loaded: a session is running this transfer
    ctype = curl.getinfo(CurlInfo.CONTENT_TYPE)
    length = curl.getinfo(CurlInfo.CONTENT_LENGTH_DOWNLOAD_T)
    head = {}
    if ctype:
        head["content-type"] = ctype.decode("latin-1") if isinstance(ctype, bytes) else ctype
    if length >= 0:
        head["content-length"] = str(length)
    return curl.getinfo(CurlInfo.RESPONSE_CODE), head


class CurlCffiMissing(RuntimeError):
    """curl_cffi is not installed: raised by the first session, wherever it opens."""


def _default_session_factory(impersonate: str, timeout: float):
    try:
        from curl_cffi import CurlHttpVersion, CurlOpt
        from curl_cffi import requests as cffi_requests
    except ImportError as exc:
        raise CurlCffiMissing(_MISSING) from exc
    return cffi_requests.Session(impersonate=impersonate, curl_options={
        # HTTP/2 over TLS only: on http:// a browser never offers curl's h2c upgrade (#156)
        CurlOpt.HTTP_VERSION: CurlHttpVersion.V2TLS,
        CurlOpt.HTTP_CONTENT_DECODING: 0,  # the raw body: Fetcher.get decodes it, bounded
        # the stdlib socket timeout: to connect, then with nothing received. libcurl counts
        # bytes in 1 s rate records, so one reaches its check up to a second late: the
        # extra second keeps a body still arriving from aborting (#154)
        CurlOpt.CONNECTTIMEOUT_MS: int(timeout * 1000),
        CurlOpt.LOW_SPEED_LIMIT: 1, CurlOpt.LOW_SPEED_TIME: math.ceil(timeout) + 1})


class CurlCffiFetcher(Fetcher):
    """Fetcher whose wire call uses curl_cffi with a browser fingerprint.

    ``proxy`` is a single proxy URL applied to every request (no rotation in
    this slice). ``impersonate`` is a curl_cffi profile (e.g. ``"chrome124"``).
    ``session_factory`` is injectable for tests; the default imports curl_cffi.
    """

    def __init__(self, policy, *, proxy: str | None = None,
                 impersonate: str = "chrome", user_agent: str | None = None,
                 session_factory=None, **kw):
        super().__init__(policy, **kw)
        self._user_agent = user_agent
        self._proxy, self._proxy_auth = split_proxy(proxy)
        self._impersonate = impersonate
        self._session_factory = session_factory or _default_session_factory

    def _session(self):
        session = getattr(self._local, "cffi", None)
        if session is None:
            session = self._local.cffi = self._session_factory(self._impersonate,
                                                               self.policy.timeout)
        return session

    def _request(self, key, parts, target, headers, stop=None):
        self._acquire(conn=True)  # connection-rate pacing, as the stdlib path does
        # Rebuild the URL from the IDNA host (no userinfo), as the stdlib path puts on the
        # wire, so curl targets exactly what the scope/robots checks validated.
        netloc = wire_host(parts)  # the port included; ValueError on a host the checks reject
        url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
        req_headers = dict(_TARGET_HEADERS.get(self._impersonate, {}))
        req_headers.update((k, v) for k, v in headers if k.lower() in _FORWARDED)
        if self._user_agent:
            req_headers["User-Agent"] = self._user_agent
        proxies = ({"http": self._proxy, "https": self._proxy}
                   if self._proxy else None)
        session = self._session()  # outside the try: a missing curl_cffi is no transport error
        chunks, size, stopped = [], 0, None  # stopped: the (status, headers) `stop` took

        def write(chunk):  # curl's writer, in this thread: it paces and bounds the transfer
            nonlocal size, stopped
            if stop is not None and stopped is None:  # the first chunk: the headers are in
                head = _head(session.curl)
                stopped = head if stop(*head) else False
                if stopped:  # HTTrack -%s drops the connection: the body is never read
                    return _WRITE_ABORT
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
            if stopped:
                return (*stopped, None)
            if size > MAX_BODY_BYTES:
                raise ValueError("body too large") from None
            msg = f"curl_cffi: {type(exc).__name__}: {exc}"
            if self._proxy:  # curl quotes a proxy URL it cannot use (credentials are not in it)
                msg = msg.replace(self._proxy, redact_url(self._proxy))
            raise OSError(msg) from exc
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        if stop is not None and stopped is None and stop(resp.status_code, hdrs):
            return resp.status_code, hdrs, None  # no chunk came: asked once it ended
        return resp.status_code, hdrs, b"".join(chunks)

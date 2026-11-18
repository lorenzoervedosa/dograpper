"""Browser-fingerprint transport for the fire-engine downloader (ADR-0011).

``CurlCffiFetcher`` subclasses the httrack ``Fetcher`` and swaps only the wire
call for ``curl_cffi`` with TLS/HTTP-2 impersonation. Every other behaviour --
pacing (connection rate, bandwidth, per-host gap, Retry-After gate), retry,
challenge detection and robots.txt -- is inherited unchanged.

``curl_cffi`` is an optional native dependency (contract 1 / ADR-0004): it is
imported lazily, only when a session is first created.
"""
from urllib.parse import urlunsplit

from ..httrack.fetcher import MAX_BODY_BYTES, Fetcher

_MISSING = (
    "curl_cffi is required for --downloader fire-engine. "
    "Install it with: uv sync --extra fire-engine"
)


def _default_session_factory(impersonate: str):
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError as exc:
        raise RuntimeError(_MISSING) from exc
    return cffi_requests.Session(impersonate=impersonate)


class CurlCffiFetcher(Fetcher):
    """Fetcher whose wire call uses curl_cffi with a browser fingerprint.

    ``proxy`` is a single proxy URL applied to every request (no rotation in
    this slice). ``impersonate`` is a curl_cffi profile (e.g. ``"chrome124"``).
    ``session_factory`` is injectable for tests; the default imports curl_cffi.
    """

    def __init__(self, policy, *, proxy: str | None = None,
                 impersonate: str = "chrome", session_factory=None, **kw):
        super().__init__(policy, **kw)
        self._proxy = proxy
        self._impersonate = impersonate
        self._session_factory = session_factory or _default_session_factory

    def _session(self):
        session = getattr(self._local, "cffi", None)
        if session is None:
            session = self._local.cffi = self._session_factory(self._impersonate)
        return session

    def _request(self, key, parts, target, headers):
        self._acquire(conn=True)  # connection-rate pacing, as the stdlib path does
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        referer = next((v for k, v in headers if k.lower() == "referer"), None)
        req_headers = {"Referer": referer} if referer else {}
        proxies = ({"http": self._proxy, "https": self._proxy}
                   if self._proxy else None)
        try:
            resp = self._session().request(
                "GET", url, headers=req_headers, proxies=proxies,
                timeout=self.policy.timeout, allow_redirects=False,
            )
        except Exception as exc:  # curl transport error -> inherited retry path
            raise OSError(f"curl_cffi: {type(exc).__name__}: {exc}") from exc
        content = resp.content
        if len(content) > MAX_BODY_BYTES:
            raise ValueError("body too large")
        self._charge_bandwidth(len(content))
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        hdrs.pop("content-encoding", None)  # curl_cffi already decoded the body
        return resp.status_code, hdrs, content

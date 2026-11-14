"""HTTrack 3.51 request policy: clamps, wire-identical headers, TLS context."""

import importlib
import logging
import ssl
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as _pkg_version

logger = logging.getLogger(__name__)

# Deliberate second copy of cli.py's version lookup: lib must not import the CLI layer.
try:
    _VERSION = _pkg_version("dograpper")
except PackageNotFoundError:
    _VERSION = "0.0.0+unknown"

DEFAULT_USER_AGENT = f"Mozilla/5.0 (compatible; dograpper/{_VERSION})"
ACCEPT = ("text/html,image/png,image/jpeg,image/pjpeg,image/x-xbitmap,"
          "image/svg+xml,image/gif;q=0.9,*/*;q=0.1")
ACCEPT_LANGUAGE = "en, *"

MAX_CONNECTIONS = 8
MAX_CONN_RATE = 5.0
MAX_BANDWIDTH = 10_000_000
MAX_RETRY_AFTER_CAP = 3600  # never lifted, even by disable_security_limits


@dataclass(frozen=True)
class HttrackPolicy:
    user_agent: str
    connections: int
    max_conn_rate: float
    max_bandwidth: int
    timeout: float
    retries: int
    max_links: int
    max_retry_after: int
    delay_ms: int
    obey_robots: bool


def _clamp(name, value, cap, disabled):
    if not disabled and value > cap:
        logger.warning("%s=%s exceeds the safety limit; clamped to %s "
                       "(--disable-security-limits lifts it)", name, value, cap)
        return cap
    return value


def build_policy(*, user_agent: str | None = None, connections: int = 4,
                 max_conn_rate: float = 5.0, max_bandwidth: int = 100_000,
                 timeout: float = 120.0, retries: int = 2, max_links: int = 100_000,
                 max_retry_after: int = 60, delay_ms: int = 0, obey_robots: bool = True,
                 disable_security_limits: bool = False) -> HttrackPolicy:
    off = disable_security_limits
    return HttrackPolicy(
        user_agent=user_agent or DEFAULT_USER_AGENT,
        connections=_clamp("connections", connections, MAX_CONNECTIONS, off),
        max_conn_rate=_clamp("max_conn_rate", max_conn_rate, MAX_CONN_RATE, off),
        max_bandwidth=_clamp("max_bandwidth", max_bandwidth, MAX_BANDWIDTH, off),
        timeout=timeout,
        retries=retries,
        max_links=max_links,
        max_retry_after=min(max_retry_after, MAX_RETRY_AFTER_CAP),
        delay_ms=delay_ms,
        obey_robots=obey_robots,
    )


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
    except ImportError:
        return False
    return True


_DECODER_MODULES = {"br": ("brotli",), "zstd": ("zstandard", "compression.zstd")}


def _decoder_modname(encoding: str) -> str | None:
    return next((m for m in _DECODER_MODULES[encoding] if _importable(m)), None)


def decoder_module(encoding: str):
    """Module able to decode `encoding` ("br" | "zstd"), or None. Single source for
    both what we advertise and what the fetcher decodes."""
    name = _decoder_modname(encoding)
    return importlib.import_module(name) if name else None


def accept_encoding() -> str:
    parts = ["gzip", "deflate"] + [e for e in _DECODER_MODULES if _decoder_modname(e)]
    return ", ".join(parts + ["identity;q=0.9"])


def request_headers(policy: HttrackPolicy, host: str, *, kind: str,
                    referer: str | None) -> list[tuple[str, str]]:
    """Headers in HTTrack's exact order. kind: robots | navigate | linked."""
    if kind not in ("robots", "navigate", "linked"):
        raise ValueError(f"unknown request kind: {kind!r}")
    nav = kind != "robots"
    h: list[tuple[str, str]] = []
    if kind == "linked" and referer:
        h.append(("Referer", referer))
    h += [("Connection", "keep-alive"), ("Host", host)]
    if nav:
        h.append(("Upgrade-Insecure-Requests", "1"))
    h += [("User-Agent", policy.user_agent), ("Accept", ACCEPT)]
    if nav:
        h += [("Sec-Fetch-Site", "same-origin" if kind == "linked" else "none"),
              ("Sec-Fetch-Mode", "navigate"),
              ("Sec-Fetch-User", "?1"),
              ("Sec-Fetch-Dest", "document")]
    h += [("Accept-Language", ACCEPT_LANGUAGE), ("Accept-Encoding", accept_encoding())]
    return h


def make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.set_ciphers("DEFAULT")
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.options |= ssl.OP_ALL
    ctx.load_default_certs()
    return ctx


def warn_if_old_openssl() -> bool:
    if ssl.OPENSSL_VERSION_INFO >= (3, 5):
        return False
    logger.warning(
        "OpenSSL %s < 3.5: the TLS handshake will not match HTTrack's and some "
        "CDNs may reject it. See README section \"Downloader profiles\".",
        ssl.OPENSSL_VERSION)
    return True

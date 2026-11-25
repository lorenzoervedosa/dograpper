"""The browsers of --browser-headers (HTTrack -%Q, #170): which browser a User-Agent names,
and what that browser sends, ported from HTTrack's tables at the pinned commit (Chrome 155
and Firefox 158 captures). policy.request_headers() puts them on a request.
"""

from typing import NamedTuple

# the Accept values the browser tables share (htsfetch.c:549-553)
_CHROME_NAV = ("text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,"
               "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7")
_FIREFOX_NAV = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_STYLE = "text/css,*/*;q=0.1"


class Browser(NamedTuple):
    """What a browser sends: `accept` by Sec-Fetch-Dest (htsfetch.c:549-578; embed was never
    captured, so it follows object), and its header order for a navigation and for a
    subresource (htslib.c:913-946, without the headers the profile never sends:
    Content-length, From). Origin sits where those tables put it; policy.request_headers()
    sends it on a CORS-mode request only."""
    accept: dict
    navigation: tuple
    subresource: tuple


CLIENT_HINTS = ("sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform")
_FETCH = ("Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User", "Sec-Fetch-Dest")
# htslib.c:913-918: the order without a browser table, HTTrack's own
HTTRACK_ORDER = ("Referer", "Connection", "Host", *CLIENT_HINTS, "Upgrade-Insecure-Requests",
                 "User-Agent", "Accept", *_FETCH, "Accept-Language", "Accept-Encoding")
_FIREFOX_ORDER = ("Host", "User-Agent", "Accept", "Accept-Language", "Accept-Encoding",
                  "Origin", "Connection", "Referer", "Upgrade-Insecure-Requests", "Sec-Fetch-Dest",
                  "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User", *CLIENT_HINTS)
BROWSERS = {
    "chrome": Browser(
        {"document": _CHROME_NAV, "iframe": _CHROME_NAV, "frame": _CHROME_NAV,
         "image": "image/jxl,image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
         "style": _STYLE, "script": "*/*", "font": "*/*", "audio": "*/*", "video": "*/*",
         "object": _CHROME_NAV, "embed": _CHROME_NAV},
        ("Host", "Connection", "Origin", *CLIENT_HINTS, "Accept-Language",
         "Upgrade-Insecure-Requests",
         "User-Agent", "Accept", *_FETCH, "Referer", "Accept-Encoding"),
        ("Host", "Connection", "Origin", "sec-ch-ua-platform", "Accept-Language", "sec-ch-ua",
         "Upgrade-Insecure-Requests", "User-Agent", "sec-ch-ua-mobile", "Accept", *_FETCH,
         "Referer", "Accept-Encoding")),
    "firefox": Browser(
        {"document": _FIREFOX_NAV, "iframe": _FIREFOX_NAV, "frame": _FIREFOX_NAV,
         "image": "image/avif,image/jxl,image/webp,image/png,image/svg+xml,image/*;q=0.8,"
                  "*/*;q=0.5",
         "style": _STYLE, "script": "*/*",
         "font": "application/font-woff2;q=1.0,application/font-woff;q=0.9,*/*;q=0.8",
         "audio": "audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,application/ogg;q=0.7,"
                  "video/*;q=0.6,*/*;q=0.5",
         "video": "video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,"
                  "*/*;q=0.5",
         "object": "*/*", "embed": "*/*"},
        _FIREFOX_ORDER, _FIREFOX_ORDER)}
ACCEPT_LANGUAGE = "en-US,en;q=0.9"  # htsfetch.h:135, every browser table's


def _ua_parts(user_agent: str):
    """(product tokens, first comment or None) of a User-Agent, read as htslib.c reads it;
    None when a comment never closes or a token is empty (a control character)."""
    tokens, comment, i = [], None, 0
    while i < len(user_agent):
        if user_agent[i] == " ":
            i += 1
        elif user_agent[i] == "(":
            end = user_agent.find(")", i)
            if end < 0:
                return None
            if comment is None:
                comment = user_agent[i + 1:end]
            i = end + 1
        else:
            n = i
            while n < len(user_agent) and user_agent[n] > " " and user_agent[n] != "(":
                n += 1
            if n == i:  # every caller refuses an empty token (htslib.c:776-778)
                return None
            tokens.append(user_agent[i:n])
            i = n
    return tokens, comment


def _product(token: str, name: str) -> int | None:
    """htslib.c:692-714 ua_product_is: None when `token` is no `name`/version; else the
    version's first number, -1 when the version is malformed."""
    if not token.startswith(name + "/"):
        return None
    version = token[len(name) + 1:]
    digits = len(version) - len(version.lstrip("0123456789"))
    if (version[:1] == "0" or not digits or int(version[:digits]) >= 100000
            or version[digits:].strip(".0123456789")):
        return -1
    return int(version[:digits])


_GREASE_CHARS, _GREASE_VERSIONS = " (:-./);=?_", ("8", "99", "24")
_BRAND_ORDERS = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))
_PLATFORMS = (("Android", '"Android"'), ("CrOS", '"Chrome OS"'), ("Windows", '"Windows"'),
              ("Macintosh", '"macOS"'), ("Linux", '"Linux"'))  # Android before Linux


def client_hints(user_agent: str) -> tuple[str, bool, str] | None:
    """(sec-ch-ua, mobile, sec-ch-ua-platform) Chrome or Edge >= 108 sends with
    `user_agent`, with Chromium's GREASE brand seeded by the major (htslib.c:728-811
    hts_client_hints_of), or None for any other User-Agent."""
    parts = _ua_parts(user_agent)
    if parts is None:
        return None
    tokens, comment = parts
    chrome, edge, mobile, mozilla = -1, 0, False, False
    for token in tokens:  # every product must be one Chrome or Edge sends
        if (major := _product(token, "Chrome")) is not None:
            chrome = major
        elif (major := _product(token, "Edg")) is not None:
            edge = major
        elif _product(token, "Mozilla") is not None:
            mozilla = True
        elif token == "Mobile":
            mobile = True
        elif _product(token, "AppleWebKit") is None and _product(token, "Safari") is None:
            return None
    if not mozilla or chrome < 108 or (edge != 0 and edge != chrome):
        return None
    platform = next((value for word, value in _PLATFORMS if word in (comment or "")), None)
    if platform is None:
        return None
    brands = (f'"Not{_GREASE_CHARS[chrome % 11]}A{_GREASE_CHARS[(chrome + 1) % 11]}Brand";'
              f'v="{_GREASE_VERSIONS[chrome % 3]}"', f'"Chromium";v="{chrome}"',
              f'"Microsoft Edge";v="{edge}"' if edge > 0 else f'"Google Chrome";v="{chrome}"')
    shuffled = [""] * 3
    for i, at in enumerate(_BRAND_ORDERS[chrome % 6]):
        shuffled[at] = brands[i]
    return ", ".join(shuffled), mobile, platform


def _is_firefox(user_agent: str) -> bool:
    """htslib.c:820-857 ua_is_firefox: Firefox from 90 (its first Sec-Fetch-*), with only
    the products Firefox sends."""
    parts = _ua_parts(user_agent)
    if parts is None:
        return False
    firefox, gecko, mozilla = -1, False, False
    for token in parts[0]:
        if (major := _product(token, "Firefox")) is not None:
            firefox = major
        elif _product(token, "Gecko") is not None:
            gecko = True
        elif _product(token, "Mozilla") is not None:
            mozilla = True
        else:
            return False
    return mozilla and gecko and firefox >= 90


def browser_family(user_agent: str) -> str | None:
    """"chrome" (Chrome or Edge), "firefox" or None, as htslib.c:859-866 tells them."""
    if client_hints(user_agent) is not None:
        return "chrome"
    return "firefox" if _is_firefox(user_agent) else None

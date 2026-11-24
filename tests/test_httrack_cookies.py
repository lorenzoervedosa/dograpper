"""--cookies (#169, HTTrack -%K): the Netscape cookies.txt jar of the httrack profile.

The jar alone, then on the wire (the local `server` fixture's request log), then through
the CLI and the browser pass (Playwright doubles). No network, no real Chromium.
"""

import email.message
import logging
import os

import pytest
from click.testing import CliRunner

from dograpper.cli import cli

from dograpper.lib.httrack.cookies import load_jar
from dograpper.lib.httrack.fetcher import Fetcher
from dograpper.lib.httrack.policy import build_policy

JAR = ("# Netscape HTTP Cookie File\n"
       "#HttpOnly_127.0.0.1\tFALSE\t/docs\tFALSE\t0\tsid\tS3CRET\n"
       ".example.com\tTRUE\t/\tTRUE\t4102444800\tpref\tP1\n"
       "127.0.0.1\tFALSE\t/other\tFALSE\t4102444800\tx\tX9\n")


@pytest.fixture
def jar_file(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(JAR)
    return path


def test_a_loaded_jar_sends_what_matches_host_path_and_scheme(jar_file):
    """Expiry 0 is a session cookie (curl, browser exports), sent like any other; Secure
    goes over https only; a host-only cookie never reaches a subdomain."""
    jar = load_jar(str(jar_file))
    assert jar.header("http://127.0.0.1:8000/docs/a") == "sid=S3CRET"
    assert jar.header("http://127.0.0.1:8000/") is None
    assert jar.header("https://www.example.com/x") == "pref=P1"
    assert jar.header("http://www.example.com/x") is None
    assert jar.header("http://sub.127.0.0.1/docs/") is None


def _set_cookies(*lines):
    msg = email.message.Message()
    for line in lines:
        msg["Set-Cookie"] = line
    return msg


def test_the_write_back_keeps_httponly_and_session_cookies_and_takes_set_cookie(jar_file):
    """HTTrack -%K: the jar goes back to the same file. A Set-Cookie of the run is in it,
    its HttpOnly as the #HttpOnly_ prefix; a session cookie keeps expiry 0, as curl writes
    it; an expired one is gone."""
    jar = load_jar(str(jar_file))
    jar.take("http://127.0.0.1:8000/docs/a", _set_cookies(
        "got=G1; Path=/docs; HttpOnly", "gone=x; Max-Age=0", "sess2=S2"))
    jar.take("http://127.0.0.1:8000/docs/a", _set_cookies("gone=x; Path=/; Max-Age=0"))

    jar.save()

    assert jar_file.read_text() == (
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tTRUE\t4102444800\tpref\tP1\n"
        "#HttpOnly_127.0.0.1\tFALSE\t/docs\tFALSE\t0\tgot\tG1\n"
        "127.0.0.1\tFALSE\t/docs\tFALSE\t0\tsess2\tS2\n"
        "#HttpOnly_127.0.0.1\tFALSE\t/docs\tFALSE\t0\tsid\tS3CRET\n"
        "127.0.0.1\tFALSE\t/other\tFALSE\t4102444800\tx\tX9\n")
    reloaded = load_jar(str(jar_file))
    assert reloaded.header("http://127.0.0.1/docs/") == "got=G1; sess2=S2; sid=S3CRET"


@pytest.mark.parametrize("line", ["127.0.0.1\tFALSE\t/\tFALSE\t0\tsid",
                                  "127.0.0.1\tFALSE\t/\tFALSE\tsoon\tsid\tS3CRET",
                                  "127.0.0.1\tFALSE\t/\tFALSE\t0\tsid\tS3\rCRET"])
def test_a_bad_line_names_its_number_never_its_value(tmp_path, line):
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n\n" + line + "\n")
    with pytest.raises(ValueError, match="^line 3 ") as e:
        load_jar(str(path))
    assert "S3" not in str(e.value) and "sid" not in str(e.value)


def test_a_missing_jar_starts_empty_and_is_created_owner_only(tmp_path):
    path = tmp_path / "new" / "cookies.txt"
    jar = load_jar(str(path))
    assert jar.header("http://127.0.0.1/") is None
    jar.take("http://127.0.0.1/", _set_cookies("a=1"))
    jar.save()
    assert path.read_text().endswith("127.0.0.1\tFALSE\t/\tFALSE\t0\ta\t1\n")
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_a_utf8_bom_and_crlf_lines_are_read(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_bytes(b"\xef\xbb\xbf127.0.0.1\tFALSE\t/\tFALSE\t0\ta\t1\r\n")
    assert load_jar(str(path)).header("http://127.0.0.1/") == "a=1"


def recorded(log, path, reply):
    """A `server` reply for `path` that logs (path, the request headers in wire order)."""
    def answer(headers):
        log.append((path, list(headers.items())))
        return reply
    return answer


def test_the_fetcher_sends_the_matching_cookies_last_and_takes_set_cookie(server, jar_file):
    """The server's log: Cookie on the matching requests only, after every other header
    and the user's --header lines (htslib.c:1395-1412); a Set-Cookie is sent from the next
    request on."""
    base, script, _ = server
    log = []
    script["/robots.txt"] = recorded(log, "/robots.txt", (404, {}, b""))
    script["/docs/a"] = recorded(log, "/docs/a", (200, {"Set-Cookie": "got=G1; Path=/docs"}, b"a"))
    script["/docs/b"] = recorded(log, "/docs/b", (200, {}, b"b"))
    f = Fetcher(build_policy(retries=0, headers=(("X-Test", "1"),)),
                cookies=load_jar(str(jar_file)))

    f.robots_for(base)
    f.get(base + "/docs/a", kind="navigate")
    f.get(base + "/docs/b", kind="navigate")

    (_, robots), (_, a), (_, b) = log
    assert "Cookie" not in dict(robots)
    assert a[-1] == ("Cookie", "sid=S3CRET") and a[-2] == ("X-Test", "1")
    assert b[-1][0] == "Cookie" and sorted(b[-1][1].split("; ")) == ["got=G1", "sid=S3CRET"]


def test_a_cookie_header_line_replaces_the_jar_on_the_wire(server, jar_file):
    """#136 --header 'Cookie: x' wins for its request: the jar is not sent on it, as
    HTTrack sends no stored cookie beside a -%X Cookie line (htslib.c:1403)."""
    base, script, _ = server
    log = []
    script["/docs/a"] = recorded(log, "/docs/a", (200, {}, b"a"))
    f = Fetcher(build_policy(retries=0, obey_robots=False, headers=(("Cookie", "x=1"),)),
                cookies=load_jar(str(jar_file)))

    f.get(base + "/docs/a", kind="navigate")

    (_, a), = log
    assert [pair for pair in a if pair[0].lower() == "cookie"] == [("Cookie", "x=1")]


WORDS = " ".join(["documentation"] * 40)


def _page(link):
    return f'<html><body><h1>Docs</h1><p>{WORDS}</p><a href="{link}">{link}</a></body></html>'


def test_a_run_sends_the_jar_writes_it_back_and_never_shows_a_value(
        server, tmp_path, jar_file, caplog):
    """--cookies end to end: the matching requests alone carry Cookie, last; the run's
    Set-Cookie lands in the file; no cookie value reaches the logs, the report (-v) or
    the manifest."""
    base, script, _ = server
    log = []
    script["/robots.txt"] = recorded(log, "/robots.txt", (404, {}, b""))
    script["/docs/"] = recorded(log, "/docs/", (200, {"Content-Type": "text/html", "Set-Cookie":
                                            "got=G0TSECRET; Path=/docs; HttpOnly"},
                                      _page("a.html").encode()))
    script["/docs/a.html"] = recorded(log, "/docs/a.html", (200, {"Content-Type": "text/html"},
                                            _page("./").encode()))
    out = tmp_path / "m"

    with caplog.at_level(logging.DEBUG):
        res = CliRunner().invoke(cli, ["-v", "download", f"{base}/docs/", "-o", str(out),
                                       "--downloader", "httrack", "--cookies", str(jar_file),
                                       "--disable-security-limits", "--max-conn-rate", "1000"])

    assert res.exit_code == 0, res.output
    assert "Files downloaded: 2" in res.output
    assert {path: dict(headers).get("Cookie") for path, headers in log} == {
        "/robots.txt": None, "/docs/": "sid=S3CRET", "/docs/a.html": "sid=S3CRET; got=G0TSECRET"}
    assert all(headers[-1][0] == "Cookie" for path, headers in log if path != "/robots.txt")
    written = jar_file.read_text()
    assert "#HttpOnly_127.0.0.1\tFALSE\t/docs\tFALSE\t0\tgot\tG0TSECRET\n" in written
    shown = res.output + caplog.text + (out / ".dograpper-manifest.json").read_text()
    for value in ("S3CRET", "G0TSECRET", "X9", "P1"):
        assert value not in shown


def test_a_bad_jar_is_a_usage_error_before_any_request(server, tmp_path):
    base, _, seen = server
    bad = tmp_path / "cookies.txt"
    bad.write_text("127.0.0.1\tFALSE\t/\tFALSE\t0\tsid S3CRET\n")
    res = CliRunner().invoke(cli, ["download", f"{base}/docs/", "-o", str(tmp_path / "m"),
                                   "--downloader", "httrack", "--cookies", str(bad)])
    assert res.exit_code == 2
    assert "line 1 is not a cookies.txt record" in res.output and "S3CRET" not in res.output
    assert seen == []


def test_a_failed_run_still_writes_the_jar_back(server, tmp_path):
    """HTTrack -%K writes the jar on every way out: a challenge's cookie is kept too."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (403, {"cf-mitigated": "challenge", "Set-Cookie": "cf=C1"}, b"")
    jar = tmp_path / "cookies.txt"
    res = CliRunner().invoke(cli, ["download", f"{base}/docs/", "-o", str(tmp_path / "m"),
                                   "--downloader", "httrack", "--cookies", str(jar),
                                   "--retries", "0"])
    assert res.exit_code == 1, res.output
    assert jar.read_text().endswith("\tcf\tC1\n")


def test_a_refused_run_leaves_the_jar_as_it_was(tmp_path, jar_file):
    before = jar_file.read_bytes()
    res = CliRunner().invoke(cli, ["download", "http://127.0.0.1:9/docs/", "-o",
                                   str(tmp_path / "m"), "--downloader", "httrack",
                                   "--headless", "--cache", "2", "--cookies", str(jar_file)])
    assert res.exit_code == 2, res.output
    assert jar_file.read_bytes() == before


def test_a_dotless_host_keeps_its_cookies_and_its_name(tmp_path):
    """localhost, an intranet `wiki`: http.cookiejar matches them as `<host>.local`; the jar
    sends them to the host itself and writes the host's own name back (review of #169)."""
    path = tmp_path / "cookies.txt"
    path.write_text("localhost\tFALSE\t/\tFALSE\t0\ta\t1\n")
    jar = load_jar(str(path))
    jar.take("http://localhost:8080/docs/p", _set_cookies("b=2; Path=/"))
    jar.merge([{"name": "c", "value": "3", "domain": "wiki", "path": "/", "expires": -1,
                "httpOnly": False, "secure": False}])
    assert jar.header("http://localhost:8080/x") == "a=1; b=2"
    assert jar.header("http://wiki:8080/x") == "c=3"
    assert jar.header("http://sub.localhost/x") is None
    jar.save()
    assert path.read_text().splitlines()[1:] == ["localhost\tFALSE\t/\tFALSE\t0\ta\t1",
                                                 "localhost\tFALSE\t/\tFALSE\t0\tb\t2",
                                                 "wiki\tFALSE\t/\tFALSE\t0\tc\t3"]


def test_a_browser_cookie_beyond_latin1_goes_on_the_wire_and_back_as_utf8(tmp_path):
    """The jar holds wire bytes (latin-1): a browser's cookie value goes as its UTF-8 bytes,
    the bytes Chromium sends, and the file gets them unchanged; nothing turns into '?'."""
    path = tmp_path / "cookies.txt"
    jar = load_jar(str(path))
    jar.merge([{"name": "n", "value": "日本", "domain": "127.0.0.1", "path": "/",
                "expires": -1, "httpOnly": False, "secure": False}])
    assert jar.header("http://127.0.0.1/").encode("latin-1") == "n=日本".encode()
    jar.save()
    assert path.read_bytes().endswith("\tn\t日本\n".encode())
    assert load_jar(str(path)).to_browser()[0]["value"] == "日本"


# -- the security review of the slice-A–C branch (maintainer decisions on #169, 2026-11-24) --

def test_the_jar_goes_to_the_start_host_alone_even_for_a_cross_host_sub_sitemap(
        server, http_server, tmp_path):
    """Discovery may fetch a sub-sitemap on another host (sitemap_parser's path-prefix
    rule); that request, and its robots.txt, carry none of the user's cookies, not even the
    ones the jar holds for that host, and its Set-Cookie never enters the jar."""
    from http.server import BaseHTTPRequestHandler
    other = []

    class Other(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            other.append((self.path, self.headers.get("Cookie")))
            body = b"<urlset/>"
            self.send_response(200)
            self.send_header("Set-Cookie", "planted=P")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    port = http_server(Other).rsplit(":", 1)[1]
    base, script, _ = server
    index = (f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap>'
             f'<loc>http://localhost:{port}/docs/sitemap.xml</loc></sitemap></sitemapindex>')
    script["/robots.txt"] = (404, {}, b"")
    script["/sitemap.xml"] = (200, {"Content-Type": "application/xml"}, index.encode())
    script["/docs/"] = (200, {"Content-Type": "text/html"}, _page("a.html").encode())
    script["/docs/a.html"] = (200, {"Content-Type": "text/html"}, _page("./").encode())
    jar = tmp_path / "cookies.txt"
    jar.write_text("127.0.0.1\tFALSE\t/\tFALSE\t0\ta\tA0\n"
                   "localhost\tFALSE\t/\tFALSE\t0\tb\tB0\n")

    res = CliRunner().invoke(cli, ["download", f"{base}/docs/", "-o", str(tmp_path / "m"),
                                   "--downloader", "httrack", "--cookies", str(jar),
                                   "--disable-security-limits", "--max-conn-rate", "1000"])

    assert res.exit_code == 0, res.output
    assert "/docs/sitemap.xml" in [path for path, _ in other]  # the sub-sitemap was fetched
    assert [cookie for _, cookie in other] == [None] * len(other)
    assert "planted" not in jar.read_text() and "\tb\tB0" in jar.read_text()


def test_a_jar_bound_to_the_start_host_keeps_to_it():
    from dograpper.lib.httrack.cookies import Jar
    jar = Jar(None, host="docs.test")
    jar.take("http://other.test/", _set_cookies("o=1"))
    jar.take("http://docs.test/", _set_cookies("d=1"))
    jar.merge([{"name": "x", "value": "1", "domain": ".cdn.test", "path": "/",
                "expires": -1, "httpOnly": False, "secure": False},
               {"name": "p", "value": "1", "domain": ".test", "path": "/",
                "expires": -1, "httpOnly": False, "secure": False}])
    assert jar.header("http://other.test/") is None
    assert jar.header("http://docs.test/") == "d=1; p=1"
    assert sorted(c["name"] for c in jar.to_browser()) == ["d", "p"]


def test_a_set_cookie_with_a_control_character_is_refused_and_the_jar_stays_readable(
        raw_server, tmp_path):
    """NUL, HTAB and an obs-fold (CRLF + HTAB) in a value: refused at Set-Cookie, so a
    server cannot make the next run's jar unreadable (exit 2 on load)."""
    bad = (b"HTTP/1.1 200 OK\r\nSet-Cookie: s=a\x00b\r\nSet-Cookie: t=a\tb\r\n"
           b"Set-Cookie: u=a\r\n\tb\r\nSet-Cookie: ok=1\r\nContent-Length: 2\r\n"
           b"Connection: close\r\n\r\nok")
    base, _ = raw_server(bad)
    path = tmp_path / "cookies.txt"
    jar = load_jar(str(path))
    Fetcher(build_policy(retries=0, obey_robots=False), cookies=jar).get(base + "/",
                                                                         kind="navigate")
    assert jar.header(base + "/") == "ok=1"
    jar.save()
    assert load_jar(str(path)).header(base + "/") == "ok=1"


def test_every_cookie_line_passes_the_header_check_before_the_wire(server, tmp_path):
    """The same check as --header (CR, LF, NUL): a line that would end the header is an
    error of that request, never sent, and the error does not quote it."""
    from dograpper.lib.httrack.cookies import _cookie
    base, _, seen = server
    jar = load_jar(str(tmp_path / "cookies.txt"))
    jar.add(_cookie("127.0.0.1", "/", False, None, "s", "a\r\nX-Injected: 1", False))
    res = Fetcher(build_policy(retries=0, obey_robots=False), cookies=jar).get(
        base + "/p", kind="navigate")
    assert res.error == "Cookie has a CR, LF or NUL character in its value"
    assert seen == [] and "Injected" not in res.error


@pytest.mark.parametrize("field", ["a\x01b", "a\x7fb"])
def test_a_jar_line_with_a_control_character_is_a_bad_line(tmp_path, field):
    path = tmp_path / "cookies.txt"
    path.write_text(f"127.0.0.1\tFALSE\t/\tFALSE\t0\ts\t{field}\n")
    with pytest.raises(ValueError, match="^line 1 "):
        load_jar(str(path))


@pytest.mark.parametrize("url, line, other", [
    ("http://1.2.3.4/", "a=1; Domain=2.3.4", "http://5.2.3.4/"),       # from an IP host
    ("http://foo/", "a=1; Domain=local", "http://x.local/"),          # a Domain with no dot
    ("http://h.example.com/", "a=1; Domain=1.2.3.4", "http://1.2.3.4/"),  # an IP Domain
])
def test_a_domain_that_is_an_ip_or_has_no_dot_is_refused(url, line, other):
    from dograpper.lib.httrack.cookies import Jar
    jar = Jar(None)
    jar.take(url, _set_cookies(line))
    assert jar.header(url) is None and jar.header(other) is None


def test_an_ip_host_gets_no_cookie_by_domain_suffix(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(".2.3.4\tTRUE\t/\tFALSE\t0\ta\t1\n1.2.3.4\tFALSE\t/\tFALSE\t0\tb\t2\n")
    assert load_jar(str(path)).header("http://1.2.3.4/") == "b=2"


def test_a_secure_cookie_is_taken_over_https_alone_and_plain_http_cannot_touch_one():
    """RFC 6265bis 5.6 (htslib.c:1983-1987): plain http may neither set a Secure cookie
    (nor a __Secure- / __Host- one) nor shadow, replace or erase one."""
    from dograpper.lib.httrack.cookies import Jar
    jar = Jar(None)
    jar.take("http://h.test/", _set_cookies("plain=1; Secure", "__Secure-a=1",
                                            "__Host-b=1; Path=/"))
    assert jar.header("https://h.test/") is None
    jar.take("https://h.test/", _set_cookies("s=1; Secure; Path=/", "__Secure-a=1; Secure",
                                             "__Host-b=1; Secure; Path=/"))
    jar.take("http://h.test/", _set_cookies("s=2; Path=/"))  # would shadow it
    jar.take("http://h.test/", _set_cookies("s=; Path=/; Max-Age=0"))  # would erase it
    assert jar.header("https://h.test/") == "s=1; __Secure-a=1; __Host-b=1"
    assert jar.header("http://h.test/") is None


def test_max_age_0_deletes_on_a_dotless_host():
    """The stdlib deletes a host-only cookie as `<host>.local`, where a dotless host's is
    not: `s=; Max-Age=0` from http://wiki/ must still erase s=1."""
    from dograpper.lib.httrack.cookies import Jar
    jar = Jar(None)
    jar.take("http://wiki/", _set_cookies("s=1", "t=1"))
    jar.take("http://wiki/", _set_cookies("s=; Max-Age=0"))
    assert jar.header("http://wiki/") == "t=1"


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks and permission bits")
def test_a_jar_that_is_a_symlink_is_written_through_it(tmp_path):
    """As curl and HTTrack write it: the link stays a link, its target gets the jar and
    keeps its own mode."""
    target = tmp_path / "real" / "cookies.txt"
    target.parent.mkdir()
    target.write_text("127.0.0.1\tFALSE\t/\tFALSE\t0\ta\t1\n")
    os.chmod(target, 0o640)
    link = tmp_path / "cookies.txt"
    link.symlink_to(target)
    jar = load_jar(str(link))
    jar.take("http://127.0.0.1/", _set_cookies("b=2"))
    jar.save()
    assert link.is_symlink() and "\tb\t2\n" in target.read_text()
    assert target.stat().st_mode & 0o777 == 0o640

"""--browser-login (#171): a headed Chromium login before the httrack profile's run.

Playwright is a double (CI has no browser and no display); the site is the local `server`
fixture, whose request log shows what the run sent. No network.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dograpper.cli import cli

LOGIN_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Safari/537.36")
LOGIN_COOKIE = {"name": "sess", "value": "L0GIN", "domain": "127.0.0.1", "path": "/",
                "expires": -1, "httpOnly": True, "secure": False, "sameSite": "Lax"}
WORDS = " ".join(["documentation"] * 40)
FAST = ["--disable-security-limits", "--max-conn-rate", "1000"]


def _page(link):
    return (f'<html><body><h1>Docs</h1><p>{WORDS}</p><a href="{link}">{link}</a>'
            "</body></html>").encode()


@pytest.fixture
def site(server):
    """A two-page site whose every request is logged as (path, headers)."""
    base, script, _ = server
    log = []

    def logged(path, reply):
        def answer(headers):
            log.append((path, dict(headers.items())))
            return reply
        return answer

    script["/robots.txt"] = logged("/robots.txt", (404, {}, b""))
    for path, link in (("/docs/", "a.html"), ("/docs/a.html", "./")):
        script[path] = logged(path, (200, {"Content-Type": "text/html"}, _page(link)))
    return base, log


@pytest.fixture
def headed(monkeypatch, site):
    """A mocked Playwright for the login window; records how many requests the site had
    seen when the browser launched."""
    monkeypatch.setenv("DISPLAY", ":0")
    sync_api = MagicMock()
    pw = sync_api.sync_playwright.return_value.__enter__.return_value
    browser = MagicMock()
    launched = []
    pw.chromium.launch.side_effect = lambda **kw: launched.append((kw, len(site[1]))) or browser
    ctx = browser.new_context.return_value
    page = ctx.new_page.return_value
    page.evaluate.return_value = LOGIN_UA
    ctx.cookies.return_value = [LOGIN_COOKIE]
    with patch.dict(sys.modules, {"playwright": MagicMock(), "playwright.sync_api": sync_api}):
        yield launched, browser, page


def login(base, out, *args, stdin="\n"):
    return CliRunner().invoke(cli, ["download", f"{base}/docs/", "-o", str(out),
                                    "--downloader", "httrack", "--browser-login", *FAST,
                                    *args], input=stdin)


def test_the_login_runs_first_and_its_cookies_and_ua_go_on_every_request(site, headed,
                                                                         tmp_path):
    base, log = site
    launched, browser, page = headed

    res = login(base, tmp_path / "m")

    assert res.exit_code == 0, res.output
    assert launched == [({"headless": False}, 0)]  # headed, before any request of the run
    page.goto.assert_called_once()
    assert page.goto.call_args.args[0] == f"{base}/docs/"
    browser.close.assert_called_once()
    assert [path for path, _ in log] == ["/robots.txt", "/docs/", "/docs/a.html"]
    assert {h["User-Agent"] for _, h in log} == {LOGIN_UA}
    assert {h["Cookie"] for _, h in log} == {"sess=L0GIN"}
    assert "L0GIN" not in res.output


def test_with_cookies_the_login_jar_is_saved_for_reuse(site, headed, tmp_path):
    base, _ = site
    jar = tmp_path / "cookies.txt"

    res = login(base, tmp_path / "m", "--cookies", str(jar))

    assert res.exit_code == 0, res.output
    assert "#HttpOnly_127.0.0.1\tFALSE\t/\tFALSE\t0\tsess\tL0GIN\n" in jar.read_text()


def test_without_playwright_the_login_exits_1_naming_the_fix(site, tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    base, log = site
    with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
        res = login(base, tmp_path / "m")
    assert res.exit_code == 1
    assert "--browser-login needs Playwright" in res.output
    assert "uv sync --extra headless" in res.output and log == []


def test_without_a_display_the_login_exits_1_naming_the_fix(site, headed, tmp_path,
                                                             monkeypatch):
    base, log = site
    launched, _, _ = headed
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    res = login(base, tmp_path / "m")

    assert res.exit_code == 1
    assert "no display" in res.output and "--cookies" in res.output
    assert launched == [] and log == []


def test_no_enter_to_press_exits_1(site, headed, tmp_path):
    base, log = site
    res = login(base, tmp_path / "m", stdin="")
    assert res.exit_code == 1
    assert "press Enter" in res.output and log == []


@pytest.mark.parametrize("given", [["--user-agent", "X/1"], ["--user-agent", ""],
                                   ["--header", "User-Agent: X/1"]])
def test_a_user_agent_beside_the_login_is_a_usage_error(site, headed, tmp_path, given):
    """The login's cookies are tied to the browser's own User-Agent (#171 decisions)."""
    base, log = site
    launched, _, _ = headed
    res = login(base, tmp_path / "m", *given)
    assert res.exit_code == 2
    assert "--browser-login both set the User-Agent" in res.output
    assert launched == [] and log == []

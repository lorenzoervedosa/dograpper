"""`dograpper docs`: page builder (pure) and local server."""

import re
import socket
import threading
import urllib.request
from unittest.mock import patch

import click
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.commands import docs as docs_mod
from dograpper.commands.docs import build_page, make_server


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _page(group=cli):
    return build_page(group)


def test_every_command_and_option_has_an_anchor():
    page = _page()
    for name, cmd in cli.commands.items():
        assert f'id="{name}"' in page
        assert f'href="#{name}"' in page
        for p in cmd.params:
            if isinstance(p, click.Option):
                long = next(o for o in p.opts if o.startswith("--"))[2:]
                assert f'id="{name}--{long}"' in page, (name, long)
    assert 'id="docs"' in page
    for flag in ("version", "verbose", "quiet", "config"):
        assert f'id="global--{flag}"' in page


def test_option_kinds_are_rendered():
    page = _page()
    # choice: accepted values and default
    section = page.split('id="pack--strategy"')[1].split("</tr>")[0]
    assert "size" in section and "semantic" in section
    # flag pair as click prints it
    assert "--with-index / --no-index" in page
    # required option
    assert "required" in page.split('id="download--output"')[1].split("</tr>")[0]
    # repeatable option
    assert "repeatable" in page.split('id="pack--ignore"')[1].split("</tr>")[0]
    # default value
    assert "500000" in page.split('id="pack--max-words-per-chunk"')[1].split("</tr>")[0]


def _row(page, row_id):
    return page.split(f'id="{row_id}"')[1].split("</tr>")[0]


def test_option_without_default_shows_none():
    # click 8.3 reports a missing default as its UNSET sentinel, not None
    page = _page()
    assert "Sentinel" not in page
    assert "<td>none</td>" in _row(page, "download--output")


def test_page_is_self_contained():
    page = _page()
    for needle in ("<link", "<script", "<img", "@import", "url(", "src=", "<iframe"):
        assert needle not in page
    assert "<style>" in page


def test_strings_are_html_escaped():
    @click.group()
    def g():
        """Group <b>doc</b>."""

    @g.command()
    @click.option("--x", help="<script>alert(1)</script> & more")
    def evil():
        """Run <img src=x onerror=1>."""

    page = _page(g)
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in page
    assert "<img" not in page


def test_make_server_binds_loopback_and_serves_page():
    server = make_server(0, "<html>ok</html>")
    try:
        assert server.server_address[0] == "127.0.0.1"
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with urllib.request.urlopen(url) as r:
            assert r.status == 200
            assert b"ok" in r.read()
        try:
            urllib.request.urlopen(url + "nope")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        else:
            raise AssertionError("expected 404")
    finally:
        server.shutdown()
        server.server_close()


def _run(args):
    # serve_forever returns as if the user pressed Ctrl+C
    with patch.object(docs_mod.ThreadingHTTPServer, "serve_forever", side_effect=KeyboardInterrupt), \
         patch.object(docs_mod.webbrowser, "open") as wb:
        result = CliRunner().invoke(cli, ["docs", *args], prog_name="dograpper")
    return result, wb


def test_no_browser_never_calls_webbrowser_and_prints_url():
    port = _free_port()
    result, wb = _run(["--port", str(port), "--no-browser"])
    assert result.exit_code == 0, result.output
    assert f"http://127.0.0.1:{port}/" in result.output
    wb.assert_not_called()


def test_browser_opened_by_default_and_url_printed():
    port = _free_port()
    result, wb = _run(["--port", str(port)])
    assert result.exit_code == 0, result.output
    assert f"http://127.0.0.1:{port}/" in result.output
    wb.assert_called_once_with(f"http://127.0.0.1:{port}/")


def test_busy_port_exits_nonzero_naming_port_flag():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        result, wb = _run(["--port", str(port), "--no-browser"])
    assert result.exit_code != 0
    assert "--port" in result.output
    assert str(port) in result.output
    wb.assert_not_called()


def test_default_port_is_8000():
    opt = next(p for p in docs_mod.docs.params if p.name == "port")
    assert opt.default == 8000

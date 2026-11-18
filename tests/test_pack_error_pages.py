import os

from click.testing import CliRunner

from dograpper.commands.pack import pack
from dograpper.utils.error_page import find_error_page_files, is_error_page

APACHE_404 = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">
<html><head>
<title>404 Not Found</title>
</head><body>
<h1>Not Found</h1>
<p>The requested URL was not found on this server.</p>
<script>(function(){var u='/cdn-cgi/challenge-platform/scripts/jsd/main.js';})();</script></body></html>"""

REAL = ("<html><head><title>Overview</title></head><body><h1>Overview</h1>"
        "<p>%s</p></body></html>" % " ".join(["real documentation"] * 40))

# Documentation about 404s: other title, or a title of the same shape but a real body.
ABOUT_404 = ("<html><head><title>Handling 404 errors</title></head><body><h1>Handling 404 errors</h1>"
             "<p>%s</p></body></html>" % " ".join(["return a 404 Not Found page"] * 20))
PROSE = ("<html><head><title>Status codes</title></head><body><h1>Status codes</h1>"
         "<p>404 Not Found</p><p>The requested URL was not found on this server.</p></body></html>")
LONG_404 = ("<html><head><title>404 Not Found</title></head><body><h1>404 Not Found</h1>"
            "<p>%s</p></body></html>" % " ".join(["how to design a not found page"] * 30))


def test_is_error_page():
    assert is_error_page(APACHE_404.encode())
    assert is_error_page(b"<title>503 Service Unavailable</title><body>503 Service Unavailable</body>")
    assert not is_error_page(REAL.encode())
    assert not is_error_page(ABOUT_404.encode())
    assert not is_error_page(PROSE.encode())
    assert not is_error_page(LONG_404.encode())


def test_is_error_page_unclosed_script_is_not_content():
    assert is_error_page(b"<title>404 Not Found</title><p>Not Found</p><script>var a=1;")


def test_find_error_page_files_ignores_non_html(tmp_path):
    (tmp_path / "a.html").write_text(APACHE_404)
    (tmp_path / "b.md").write_text(APACHE_404)
    paths = [str(tmp_path / "a.html"), str(tmp_path / "b.md")]
    assert find_error_page_files(paths) == [str(tmp_path / "a.html")]


def _make_input(tmp_path):
    src = tmp_path / "docs"
    (src / "sub").mkdir(parents=True)
    (src / "real.html").write_text(REAL)
    (src / "about.html").write_text(ABOUT_404)
    (src / "prose.html").write_text(PROSE)
    (src / "long.html").write_text(LONG_404)
    (src / "gone.html").write_text(APACHE_404)
    (src / "sub" / "also-gone.html").write_text(APACHE_404)
    return src


def test_pack_skips_error_pages_and_reports_them(tmp_path):
    src = _make_input(tmp_path)
    out = tmp_path / "out"
    result = CliRunner().invoke(pack, [str(src), "-o", str(out), "--format", "jsonl"])
    assert result.exit_code == 0, result.output
    assert result.output.count("HTTP error page") == 1
    assert "gone.html" in result.output
    assert "sub/also-gone.html" in result.output
    assert "Error pages:     2" in result.output
    assert "Files processed: 4" in result.output
    packed = "".join(open(os.path.join(out, f)).read() for f in os.listdir(out))
    assert "real documentation" in packed
    assert "Handling 404 errors" in packed
    assert "The requested URL was not found on this server." in packed  # prose.html is kept
    assert "cdn-cgi" not in packed


def test_pack_page_layout_skips_error_pages(tmp_path):
    src = _make_input(tmp_path)
    out = tmp_path / "out"
    result = CliRunner().invoke(pack, [str(src), "-o", str(out), "--layout", "page"])
    assert result.exit_code == 0, result.output
    assert "Error pages:     2" in result.output
    assert (out / "pages" / "real.md").exists()
    assert not (out / "pages" / "gone.md").exists()
    assert not any("also-gone" in n for _, _, fs in os.walk(out) for n in fs)


def test_pack_dry_run_warns_about_error_pages(tmp_path):
    src = _make_input(tmp_path)
    result = CliRunner().invoke(pack, [str(src), "-o", str(tmp_path / "out"), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "HTTP error page" in result.output
    assert "sub/also-gone.html" in result.output


def test_pack_fails_loud_when_every_page_is_an_error_page(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "gone.html").write_text(APACHE_404)
    result = CliRunner().invoke(pack, [str(src), "-o", str(tmp_path / "out")])
    assert result.exit_code != 0
    assert "HTTP error page" in result.output

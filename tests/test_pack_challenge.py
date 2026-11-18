import os

from click.testing import CliRunner

from dograpper.commands.pack import pack
from dograpper.utils.challenge import find_challenge_files, is_challenge_page

CHALLENGE = """<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta name="robots" content="noindex,nofollow"></head>
<body><div class="main-wrapper" role="main"><noscript>
<div class="h2"><span id="challenge-error-text">Enable JavaScript and cookies to continue</span></div>
</noscript></div>
<script>window._cf_chl_opt={cvId:'3'};</script>
<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>
</body></html>"""

REAL = ("<html><head><title>Overview</title></head><body><h1>Overview</h1>"
        "<p>%s</p></body></html>" % " ".join(["real documentation"] * 40))

PROSE = ("<html><head><title>Retries</title></head><body><h1>Retries</h1>"
         "<p>If the server answers with a page titled Just a moment... "
         "wait and retry. %s</p></body></html>" % " ".join(["more text"] * 40))


def test_is_challenge_page():
    assert is_challenge_page(CHALLENGE.encode())
    assert not is_challenge_page(REAL.encode())
    assert not is_challenge_page(PROSE.encode())


def test_find_challenge_files_ignores_non_html(tmp_path):
    (tmp_path / "a.html").write_text(CHALLENGE)
    (tmp_path / "b.md").write_text(CHALLENGE)
    paths = [str(tmp_path / "a.html"), str(tmp_path / "b.md")]
    assert find_challenge_files(paths) == [str(tmp_path / "a.html")]


def _make_input(tmp_path):
    src = tmp_path / "docs"
    (src / "sub").mkdir(parents=True)
    (src / "real.html").write_text(REAL)
    (src / "prose.html").write_text(PROSE)
    (src / "blocked.html").write_text(CHALLENGE)
    (src / "sub" / "also-blocked.html").write_text(CHALLENGE)
    return src


def test_pack_skips_challenge_pages_and_reports_them(tmp_path):
    src = _make_input(tmp_path)
    out = tmp_path / "out"
    result = CliRunner().invoke(pack, [str(src), "-o", str(out), "--format", "jsonl"])
    assert result.exit_code == 0, result.output
    assert result.output.count("bot-challenge") == 1
    assert "blocked.html" in result.output
    assert "sub/also-blocked.html" in result.output
    assert "Challenge pages: 2" in result.output
    assert "Files processed: 2" in result.output
    packed = "".join(open(os.path.join(out, f)).read() for f in os.listdir(out))
    assert "real documentation" in packed
    assert "Just a moment..." in packed  # the prose page is kept
    assert "challenge-error-text" not in packed
    assert "Enable JavaScript" not in packed


def test_pack_dry_run_warns_about_challenge_pages(tmp_path):
    src = _make_input(tmp_path)
    result = CliRunner().invoke(pack, [str(src), "-o", str(tmp_path / "out"), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "bot-challenge" in result.output
    assert "sub/also-blocked.html" in result.output


def test_pack_fails_loud_when_every_page_is_a_challenge(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "blocked.html").write_text(CHALLENGE)
    result = CliRunner().invoke(pack, [str(src), "-o", str(tmp_path / "out")])
    assert result.exit_code != 0
    assert "bot-challenge" in result.output

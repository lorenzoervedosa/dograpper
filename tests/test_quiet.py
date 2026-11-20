"""`-q/--quiet` silences the success output of pack, download, sync and eval (#139)."""

import json
import logging
import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.utils.logger import setup_logger

@pytest.fixture(autouse=True)
def _restore_logger():
    """`-q` leaves the dograpper logger at ERROR with a handler; later caplog tests need it as it was."""
    log = logging.getLogger("dograpper")
    level, handlers = log.level, list(log.handlers)
    yield
    log.setLevel(level)
    log.handlers[:] = handlers


HTML = {"content-type": "text/html"}
WORDS = " ".join(["documentation"] * 40)
PAGE = f"<html><body><main><h1>Home</h1><p>{WORDS}</p></main></body></html>".encode()


def _docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.html").write_text(PAGE.decode())
    return d


def test_pack_quiet_prints_nothing(tmp_path):
    docs = _docs(tmp_path)
    loud = CliRunner().invoke(cli, ["pack", str(docs), "-o", str(tmp_path / "c1")])
    quiet = CliRunner().invoke(cli, ["-q", "pack", str(docs), "-o", str(tmp_path / "c2")])
    assert "Pack complete" in loud.output
    assert quiet.exit_code == loud.exit_code == 0
    assert quiet.stdout == "" and quiet.stderr == ""


def test_pack_quiet_dry_run_still_reports(tmp_path):
    docs = _docs(tmp_path)
    r = CliRunner().invoke(cli, ["-q", "pack", str(docs), "-o", str(tmp_path / "c"), "--dry-run"])
    assert r.exit_code == 0 and "DRY-RUN" in r.stdout.upper()


def test_quiet_keeps_errors_on_stderr(tmp_path):
    r = CliRunner().invoke(cli, ["-q", "pack", str(tmp_path / "missing"), "-o", str(tmp_path / "c")])
    assert r.exit_code != 0 and r.stderr


def test_quiet_download_and_sync_print_nothing(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/"] = (200, HTML, PAGE.replace(b"</main>", b'<a href="/b.html">b</a></main>'))
    script["/b.html"] = (200, HTML, PAGE)  # two pages: one alone triggers the Playwright layer
    url = f"{base}/"
    args = ["download", url, "-o", str(tmp_path / "d1"), "--downloader", "httrack"]
    loud = CliRunner().invoke(cli, args)
    quiet = CliRunner().invoke(cli, ["-q", "download", url, "-o", str(tmp_path / "d2"),
                                     "--downloader", "httrack"])
    assert "Download complete" in loud.output
    assert quiet.exit_code == loud.exit_code == 0
    assert quiet.stdout == ""
    sync_args = ["sync", url, "--downloader", "httrack", "-o"]
    loud_sync = CliRunner().invoke(cli, [*sync_args, str(tmp_path / "s0")])
    sync = CliRunner().invoke(cli, ["-q", *sync_args, str(tmp_path / "s")])
    assert "=== Step 1: Download ===" in loud_sync.stdout
    assert sync.exit_code == loud_sync.exit_code == 0, sync.output
    assert sync.stdout == ""


def test_eval_quiet_prints_nothing(tmp_path):
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    rec = {"id": "01_install", "source": "install.html", "words": 9,
           "content": "Installation guide run pip install to set up the package quickly",
           "breadcrumb": ["Guide", "Installation"], "readiness_grade": "A"}
    (chunks / "docs_chunk_01.jsonl").write_text(json.dumps(rec) + "\n")
    out = tmp_path / "report.json"
    loud = CliRunner().invoke(cli, ["eval", str(chunks)])
    r = CliRunner().invoke(cli, ["-q", "eval", str(chunks), "-o", str(out)])
    assert r.exit_code == loud.exit_code == 0 and r.stdout == ""
    assert out.exists()


def test_logger_writes_to_stderr(capsys):
    log = setup_logger(verbose=True)
    log.debug("probe")
    log.error("boom")
    out = capsys.readouterr()
    assert out.out == ""
    assert "DEBUG: probe" in out.err and "ERROR: boom" in out.err


def test_eval_quiet_keeps_its_error_on_stderr(tmp_path):
    (tmp_path / "empty").mkdir()
    r = CliRunner().invoke(cli, ["-q", "eval", str(tmp_path / "empty")])
    assert r.exit_code == 1 and "no JSONL chunks" in r.stderr and r.stdout == ""

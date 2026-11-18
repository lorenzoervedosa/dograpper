"""Source URLs of packed files (`pack --context-header`): manifest loading,
page markers left by HTTrack and by a browser's "Save page as"."""

import json

import pytest
from click.testing import CliRunner

from dograpper.commands.pack import pack
from dograpper.lib.source_urls import (
    CONFLICTING, INVALID, MARKER_SCAN_BYTES, MAX_URL_CHARS, marker_url,
)

PAGE = "<html><head><title>T</title></head><body><h1>Title</h1><p>Some body words here.</p></body></html>"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(path, entries):
    """Write a download manifest mapping local_path -> url."""
    files = {lp: {"url": url, "size_bytes": 1, "local_path": lp} for lp, url in entries.items()}
    _write(path, json.dumps({"base_url": "", "last_run": "", "files": files}))


def _records(out_dir):
    records = []
    for chunk in sorted(out_dir.glob("*.jsonl")):
        records.extend(json.loads(line) for line in chunk.read_text(encoding="utf-8").splitlines())
    return {r["source"]: r for r in records}


def _pack(args, verbose=False):
    return CliRunner().invoke(pack, args, obj={"VERBOSE": verbose})


def _httrack(url, version="3.x [XR&CO]"):
    """Footer comment as HTTrack writes it into the page head."""
    return (f"<!-- Mirrored from {url} by HTTrack Website Copier/{version}, "
            f"Sat, 14 Nov 2026 06:51:15 GMT -->")


def _saved_from(url, length=None):
    """Mark of the Web as a browser's "Save page as" writes it."""
    return f"<!-- saved from url=({len(url) if length is None else length:04d}){url} -->"


def _page(*markers):
    head = "\n".join(markers)
    return f"<!DOCTYPE html>\n{head}\n<html lang=\"en\">\n" + PAGE[len("<html>"):]


def test_explicit_manifest_url_reaches_record(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "a.html", PAGE)
    _manifest(tmp_path / "m.json", {"a.html": "https://example.com/a"})
    result = _pack([str(tmp_path / "docs"), "-o", str(tmp_path / "out"), "--format", "jsonl",
                    "--context-header", "--manifest", str(tmp_path / "m.json")])
    assert result.exit_code == 0, result.output
    assert _records(tmp_path / "out")["a.html"]["url"] == "https://example.com/a"


def test_explicit_manifest_missing_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "a.html", PAGE)
    missing = tmp_path / "nope.json"
    result = _pack([str(tmp_path / "docs"), "-o", str(tmp_path / "out"),
                    "--context-header", "--manifest", str(missing)])
    assert result.exit_code == 1
    assert "manifest" in result.output and str(missing) in result.output
    assert not (tmp_path / "out").exists()


def test_explicit_manifest_malformed_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "a.html", PAGE)
    _write(tmp_path / "m.json", "{not json")
    result = _pack([str(tmp_path / "docs"), "-o", str(tmp_path / "out"),
                    "--context-header", "--manifest", str(tmp_path / "m.json")])
    assert result.exit_code == 1
    assert "cannot load manifest" in result.output
    assert str(tmp_path / "m.json") in result.output


def test_explicit_manifest_with_wrong_shape_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "a.html", PAGE)
    _write(tmp_path / "m.json", json.dumps({"files": {"a.html": {"size_bytes": 1}}}))
    result = _pack([str(tmp_path / "docs"), "-o", str(tmp_path / "out"),
                    "--context-header", "--manifest", str(tmp_path / "m.json")])
    assert result.exit_code == 1
    assert "cannot load manifest" in result.output


def test_default_manifest_malformed_is_a_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "a.html", PAGE)
    _write(tmp_path / ".dograpper-manifest.json", "{not json")
    result = _pack([str(tmp_path / "docs"), "-o", str(tmp_path / "out"), "--format", "jsonl",
                    "--context-header"])
    assert result.exit_code == 0, result.output
    assert "Note: ignoring manifest .dograpper-manifest.json" in result.stderr
    assert "url" not in _records(tmp_path / "out")["a.html"]


def test_default_manifest_absent_is_silent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "a.html", PAGE)
    result = _pack([str(tmp_path / "docs"), "-o", str(tmp_path / "out"), "--context-header"])
    assert result.exit_code == 0, result.output
    assert "Note:" not in result.output


def test_manifest_ignored_without_context_header(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "docs" / "a.html", PAGE)
    result = _pack([str(tmp_path / "docs"), "-o", str(tmp_path / "out"),
                    "--manifest", str(tmp_path / "nope.json")])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# marker_url: parsing and validation of untrusted marker values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://pzwiki.net/wiki/Mod.info",
    "http://example.com/",
    "https://example.com:8443/a/b.html",
    "https://pzwiki.net/wiki/Lua_(language)?a=1&b='x';c=%20#frag",
    "https://example.com/a--%3Eb",  # HTTrack percent-encodes '<' and '>' in the footer
])
def test_httrack_marker(url):
    assert marker_url(_page(_httrack(url))) == (url, None)


def test_httrack_marker_without_scheme_is_http():
    # HTTrack <= 3.49 writes host and path without the scheme
    head = _page(_httrack("pzwiki.net/wiki/AnimNodes", "3.49-2 [XR&CO'2014]"))
    assert marker_url(head) == ("http://pzwiki.net/wiki/AnimNodes", None)


@pytest.mark.parametrize("url", [
    "https://example.com/page",
    "https://example.com/a--%3Eb?q=(1)&r='2'",
])
def test_saved_from_marker(url):
    assert marker_url(_page(_saved_from(url))) == (url, None)


def test_saved_from_value_holding_comment_end_is_rejected_whole():
    # The (NNNN) length spans the raw "-->"; the value is never cut short at it.
    assert marker_url(_page(_saved_from("https://example.com/a-->b"))) == (None, INVALID)


def test_httrack_value_holding_comment_end_is_rejected():
    head = _page("<!-- Mirrored from https://example.com/a-->b by HTTrack Website Copier/3.x -->")
    assert marker_url(head) == (None, INVALID)


@pytest.mark.parametrize("length", [10, 25])
def test_saved_from_length_mismatch_is_rejected(length):
    assert marker_url(_page(_saved_from("https://example.com/page", length))) == (None, INVALID)


@pytest.mark.parametrize("marker", [
    "<!-- saved from url=(24)https://example.com/page -->",
    "<!-- saved from url=(0024)https://example.com/page",
    "<!-- Mirrored from https://example.com/page -->",
])
def test_unrecognized_marker_is_rejected(marker):
    assert marker_url(_page(marker)) == (None, INVALID)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "javascript://example.com/%0Aalert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "about:blank",
    "ftp://example.com/file",
    "file:///etc/passwd",
    "https://example.com/a b",
    "https://example.com/\x1b[31m",
    "https://example.com/caf\u00e9",
    "https://example.com/<script>",
    'https://example.com/"q"',
    "https://user:secret@example.com/",
    "https://example.com:99999/",
    "https://example.com:port/",
    "https:///path-only",
    "https://exa_mple.com/",
    "https://example.com/" + "a" * MAX_URL_CHARS,
])
def test_invalid_url_is_rejected(url):
    assert marker_url(_page(_saved_from(url))) == (None, INVALID)
    assert marker_url(_page(_httrack(url))) == (None, INVALID)


def test_agreeing_markers_give_the_url():
    url = "https://example.com/page"
    assert marker_url(_page(_saved_from(url), _httrack(url))) == (url, None)


def test_conflicting_markers_give_no_url():
    head = _page(_saved_from("https://a.example.com/page"), _httrack("https://b.example.com/page"))
    assert marker_url(head) == (None, CONFLICTING)


def test_any_rejected_marker_gives_no_url():
    head = _page(_saved_from("about:blank"), _httrack("https://example.com/page"))
    assert marker_url(head) == (None, INVALID)


@pytest.mark.parametrize("zone", ["about:internet", "ABOUT:Internet"])
def test_mark_of_the_web_zone_marker_is_not_a_marker(zone):
    # IE/Windows "Mark of the Web" zone marker; many sites ship it in their HTML
    url = "https://example.com/page"
    assert marker_url(_page(_saved_from(zone), _httrack(url))) == (url, None)
    assert marker_url(_page(_saved_from(zone))) == (None, None)


def test_zone_marker_value_in_httrack_marker_is_rejected():
    assert marker_url(_page(_httrack("about:internet"))) == (None, INVALID)


def test_markers_after_body_open_are_ignored():
    head = PAGE.replace("<p>", _httrack("https://evil.example.com/") + "<p>")
    assert marker_url(head) == (None, None)


def test_no_marker():
    assert marker_url(PAGE) == (None, None)


# ---------------------------------------------------------------------------
# pack --context-header: URLs from markers, precedence and summary
# ---------------------------------------------------------------------------

def _mirror(root, pages):
    for name, text in pages.items():
        _write(root / name, text)
    return root


def test_marker_urls_reach_records_without_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = _mirror(tmp_path / "docs", {
        "a.html": _page(_httrack("https://pzwiki.net/wiki/A")),
        "sub/b.html": _page(_saved_from("https://example.com/b")),
    })
    result = _pack([str(docs), "-o", str(tmp_path / "out"), "--format", "jsonl", "--context-header"])
    assert result.exit_code == 0, result.output
    records = _records(tmp_path / "out")
    assert records["a.html"]["url"] == "https://pzwiki.net/wiki/A"
    assert records["sub/b.html"]["url"] == "https://example.com/b"
    assert "Source URLs:     0 from manifest, 2 from page markers, 0 without" in result.output


def test_marker_url_reaches_md_context_header(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = _mirror(tmp_path / "docs", {"a.html": _page(_httrack("https://pzwiki.net/wiki/A"))})
    result = _pack([str(docs), "-o", str(tmp_path / "out"), "--context-header"])
    assert result.exit_code == 0, result.output
    chunk = next((tmp_path / "out").glob("*.md")).read_text(encoding="utf-8")
    assert '"url": "https://pzwiki.net/wiki/A"' in chunk


def test_manifest_wins_over_marker(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = _mirror(tmp_path / "docs", {"a.html": _page(_httrack("https://marker.example.com/a"))})
    _manifest(tmp_path / ".dograpper-manifest.json", {"a.html": "https://manifest.example.com/a"})
    result = _pack([str(docs), "-o", str(tmp_path / "out"), "--format", "jsonl", "--context-header"])
    assert result.exit_code == 0, result.output
    assert _records(tmp_path / "out")["a.html"]["url"] == "https://manifest.example.com/a"
    assert "Source URLs:     1 from manifest, 0 from page markers, 0 without" in result.output


def test_marker_beyond_scan_prefix_is_ignored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    late = "<!DOCTYPE html>" + " " * MARKER_SCAN_BYTES + _httrack("https://example.com/a") + PAGE
    docs = _mirror(tmp_path / "docs", {"a.html": late})
    result = _pack([str(docs), "-o", str(tmp_path / "out"), "--format", "jsonl", "--context-header"])
    assert result.exit_code == 0, result.output
    assert "url" not in _records(tmp_path / "out")["a.html"]


def test_summary_reports_files_without_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = _mirror(tmp_path / "docs", {
        "ok.html": _page(_httrack("https://example.com/ok")),
        "bad.html": _page(_saved_from("javascript:alert(1)")),
        "both.html": _page(_saved_from("https://a.example.com/"), _httrack("https://b.example.com/")),
        "plain.html": PAGE,
        "notes.txt": "some plain text words here",
    })
    result = _pack([str(docs), "-o", str(tmp_path / "out"), "--format", "jsonl", "--context-header"])
    assert result.exit_code == 0, result.output
    assert "Source URLs:     0 from manifest, 1 from page markers, 4 without" in result.output
    assert "Rejected markers: 1 invalid, 1 conflicting" in result.output
    assert "    bad.html: invalid page marker" in result.output
    assert "    both.html: conflicting page markers" in result.output
    assert "    notes.txt: no manifest entry or page marker" in result.output
    assert "    plain.html: no manifest entry or page marker" in result.output
    records = _records(tmp_path / "out")
    assert [s for s, r in records.items() if "url" in r] == ["ok.html"]


def test_zone_marker_beside_httrack_marker_keeps_the_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = _mirror(tmp_path / "docs", {
        "a.html": _page(_saved_from("about:internet"), _httrack("https://example.com/a")),
        "b.html": _page(_saved_from("about:internet")),
    })
    result = _pack([str(docs), "-o", str(tmp_path / "out"), "--format", "jsonl", "--context-header"])
    assert result.exit_code == 0, result.output
    records = _records(tmp_path / "out")
    assert records["a.html"]["url"] == "https://example.com/a"
    assert "url" not in records["b.html"]
    assert "Source URLs:     0 from manifest, 1 from page markers, 1 without" in result.output
    assert "    b.html: no manifest entry or page marker" in result.output
    assert "Rejected markers" not in result.output


def test_summary_truncates_the_list_unless_verbose(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = _mirror(tmp_path / "docs", {f"p{i:02d}.html": PAGE for i in range(12)})
    args = [str(docs), "-o", str(tmp_path / "out"), "--context-header"]

    result = _pack(args)
    assert result.exit_code == 0, result.output
    assert "    p09.html: no manifest entry or page marker" in result.output
    assert "p10.html" not in result.output
    assert "    ... 2 more (use --verbose)" in result.output

    result = _pack(args, verbose=True)
    assert result.exit_code == 0, result.output
    assert "    p11.html: no manifest entry or page marker" in result.output
    assert "more (use --verbose)" not in result.output


def test_no_url_summary_without_context_header(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = _mirror(tmp_path / "docs", {"a.html": _page(_httrack("https://example.com/a"))})
    result = _pack([str(docs), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert "Source URLs" not in result.output

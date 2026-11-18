"""Source URLs of packed files (`pack --context-header`): manifest loading."""

import json

from click.testing import CliRunner

from dograpper.commands.pack import pack

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


def _pack(args):
    return CliRunner().invoke(pack, args)


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

"""atomic_write_bytes: a crash mid-write must never leave a truncated final file."""

import os

import pytest

from dograpper.utils.atomic_write import atomic_write_bytes


def test_atomic_write_creates_parents_and_content(tmp_path):
    target = tmp_path / "a" / "b" / "page.html"

    atomic_write_bytes(str(target), b"<html>ok</html>")

    assert target.read_bytes() == b"<html>ok</html>"
    assert list(target.parent.glob("*.tmp")) == []


def test_atomic_write_failure_leaves_no_final_file(tmp_path, monkeypatch):
    target = tmp_path / "page.html"

    def interrupted_replace(src, dst):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted_replace)

    with pytest.raises(KeyboardInterrupt):
        atomic_write_bytes(str(target), b"partial")

    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_atomic_write_uses_umask_default_mode(tmp_path):
    target, ref = tmp_path / "page.html", tmp_path / "ref.html"
    atomic_write_bytes(str(target), b"x")
    ref.write_bytes(b"x")  # what a plain open() creates under the same umask
    assert target.stat().st_mode & 0o777 == ref.stat().st_mode & 0o777

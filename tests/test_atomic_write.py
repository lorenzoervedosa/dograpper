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

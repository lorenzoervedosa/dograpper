"""Structural guard for CHANGELOG.md.

Enforces the mechanical half of the rules the file documents: the shape of its
headings, their order, and the invariant that bites hardest — the newest
released version must match ``pyproject.toml``, because ``dograpper --version``
reads the installed package metadata and a tag without the bump would ship a
binary that misreports itself.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

ALLOWED_SECTIONS = {
    "Added", "Changed", "Deprecated", "Removed", "Fixed", "Security",
}

_UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)
_RELEASE_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})\s*$",
                         re.MULTILINE)
_VERSION_HEADING_RE = re.compile(r"^## \[.*$", re.MULTILINE)
_SECTION_RE = re.compile(r"^### (.+?)\s*$", re.MULTILINE)


def _text():
    return CHANGELOG.read_text(encoding="utf-8")


def _project_version():
    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"),
                      re.MULTILINE)
    assert match, "pyproject.toml has no version"
    return match.group(1)


def test_unreleased_section_exists_and_comes_first():
    """New entries always have a home, and it is at the top."""
    text = _text()
    assert _UNRELEASED_RE.search(text), "CHANGELOG.md has no '## [Unreleased]' section"
    headings = _VERSION_HEADING_RE.findall(text)
    assert headings[0] == "## [Unreleased]", (
        f"'## [Unreleased]' must be the first version heading, found {headings[0]!r}")


def test_released_versions_are_well_formed_and_descending():
    releases = _RELEASE_RE.findall(_text())
    assert releases, "CHANGELOG.md lists no released version"

    def _key(version):
        return tuple(int(part) for part in version.split("."))

    versions = [_key(v) for v, _ in releases]
    assert versions == sorted(versions, reverse=True), (
        f"released versions are not in descending order: {[v for v, _ in releases]}")
    assert len(set(versions)) == len(versions), "a version is listed twice"


def test_newest_release_matches_the_packaged_version():
    """A tag without the pyproject bump ships a binary that misreports itself."""
    releases = _RELEASE_RE.findall(_text())
    newest = releases[0][0]
    assert newest == _project_version(), (
        f"CHANGELOG.md newest release is {newest} but pyproject.toml says "
        f"{_project_version()}")


def test_only_known_section_headings_are_used():
    unknown = sorted(set(_SECTION_RE.findall(_text())) - ALLOWED_SECTIONS)
    assert not unknown, (
        f"unknown changelog sections {unknown}; allowed: {sorted(ALLOWED_SECTIONS)}")


def test_every_released_version_has_at_least_one_section():
    """A released version with no entries means the rules were skipped."""
    text = _text()
    blocks = re.split(r"^## \[", text, flags=re.MULTILINE)[1:]
    empty = []
    for block in blocks:
        header, _, body = block.partition("\n")
        if header.startswith("Unreleased"):
            continue
        if not _SECTION_RE.search(body):
            empty.append(header.split("]")[0])
    assert not empty, f"released versions with no entries: {empty}"

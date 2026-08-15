"""Structural guard for the CLAUDE.md repository inventory.

CLAUDE.md is the context file agents read first; a stale tree or a reference
to a file that no longer exists sends them looking in the wrong place. These
tests pin both directions: every source/test module is listed, and every path
the document points at is real.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# Package plumbing carries no behaviour worth describing in the tree.
_SKIPPED_MODULES = {"__init__.py", "__main__.py"}


def _text():
    return CLAUDE_MD.read_text(encoding="utf-8")


def _source_modules():
    return sorted(
        p.name
        for p in (REPO_ROOT / "src" / "dograpper").rglob("*.py")
        if p.name not in _SKIPPED_MODULES
    )


def _test_modules():
    return sorted(p.name for p in (REPO_ROOT / "tests").glob("test_*.py"))


def test_tree_lists_every_source_module():
    text = _text()
    missing = [name for name in _source_modules() if name not in text]
    assert not missing, f"CLAUDE.md tree is missing source modules: {missing}"


def test_tree_lists_every_test_module():
    text = _text()
    missing = [name for name in _test_modules() if name not in text]
    assert not missing, f"CLAUDE.md tree is missing test modules: {missing}"


def test_referenced_paths_exist():
    """Every path spelled out in a backtick reference must exist on disk.

    Module references are written package-relative (``lib/chunker.py``), so
    each candidate is resolved against both the repo root and the package
    root before being reported as missing.
    """
    roots = (REPO_ROOT, REPO_ROOT / "src" / "dograpper")
    candidates = set(re.findall(r"`([\w./-]+\.(?:py|md|json|yml|yaml|example))`", _text()))
    # Bare filenames are ambiguous (docs prose, config keys); only verify
    # references that spell out a directory component.
    missing = sorted(
        ref
        for ref in candidates
        if "/" in ref and not any((root / ref).exists() for root in roots)
    )
    assert not missing, f"CLAUDE.md references paths that do not exist: {missing}"

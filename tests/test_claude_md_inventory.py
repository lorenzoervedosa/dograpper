"""Structural guard for the CLAUDE.md repository inventory.

The root CLAUDE.md is the context file agents read first; nested CLAUDE.md
files under src/ and tests/ hold the tree and the context-file rows of their
directory, and load when an agent reads a file there. A stale tree or a
reference to a file that no longer exists sends them looking in the wrong
place. Over the whole set, these tests pin: every source/test module is a tree
entry of exactly one file, the nearest CLAUDE.md above it; every path a file
points at is real; the root points at every nested file.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# Package plumbing carries no behaviour worth describing in the tree.
_SKIPPED_MODULES = {"__init__.py", "__main__.py"}
# A tree entry: box-drawing prefix, then the file name.
_TREE_ENTRY = re.compile(r"^[│ ]*[├└]── ([\w.-]+\.py)\b", re.M)


def _claude_mds():
    # Only src/ and tests/: other worktrees (with their own copies) live under .claude/.
    nested = sorted((REPO_ROOT / "src").rglob("CLAUDE.md")) + sorted((REPO_ROOT / "tests").rglob("CLAUDE.md"))
    return [CLAUDE_MD, *nested]


def _nearest_claude_md(path):
    for parent in path.parents:
        if (parent / "CLAUDE.md").is_file():
            return parent / "CLAUDE.md"
    raise AssertionError(f"no CLAUDE.md above {path}")


def _modules():
    source = [p for p in (REPO_ROOT / "src" / "dograpper").rglob("*.py") if p.name not in _SKIPPED_MODULES]
    tests = [p for p in (REPO_ROOT / "tests").glob("*.py") if p.name not in _SKIPPED_MODULES]
    return sorted(source + tests)


def _rel(path):
    return path.relative_to(REPO_ROOT).as_posix()


def test_every_module_is_listed_in_its_nearest_claude_md():
    missing = [
        f"{_rel(m)} (expected in {_rel(_nearest_claude_md(m))})"
        for m in _modules()
        if m.name not in _TREE_ENTRY.findall(_nearest_claude_md(m).read_text(encoding="utf-8"))
    ]
    assert not missing, f"CLAUDE.md trees are missing modules: {missing}"


def test_no_claude_md_lists_a_module_it_does_not_own():
    """A tree entry must name a module whose nearest CLAUDE.md is that file:
    an entry anywhere else is a second listing or a stale one."""
    owned = {}
    for m in _modules():
        owned.setdefault(_nearest_claude_md(m), set()).add(m.name)
    stray = [
        f"{_rel(doc)}: {name}"
        for doc in _claude_mds()
        for name in _TREE_ENTRY.findall(doc.read_text(encoding="utf-8"))
        if name not in owned.get(doc, set()) and name not in _SKIPPED_MODULES
    ]
    assert not stray, f"CLAUDE.md trees list modules they do not own: {stray}"


def test_referenced_paths_exist():
    """Every path spelled out in a backtick reference must exist on disk.

    Module references are written package-relative (``lib/chunker.py``), so
    each candidate is resolved against both the repo root and the package
    root before being reported as missing.
    """
    roots = (REPO_ROOT, REPO_ROOT / "src" / "dograpper")
    missing = []
    for doc in _claude_mds():
        candidates = set(re.findall(r"`([\w./-]+\.(?:py|md|json|yml|yaml|example))`", doc.read_text(encoding="utf-8")))
        # Bare filenames are ambiguous (docs prose, config keys); only verify
        # references that spell out a directory component.
        missing += [
            f"{_rel(doc)}: {ref}"
            for ref in sorted(candidates)
            if "/" in ref and not any((root / ref).exists() for root in roots)
        ]
    assert not missing, f"CLAUDE.md files reference paths that do not exist: {missing}"


def test_root_points_at_every_nested_claude_md():
    root = CLAUDE_MD.read_text(encoding="utf-8")
    unlisted = [_rel(doc) for doc in _claude_mds()[1:] if f"`{_rel(doc)}`" not in root]
    assert not unlisted, f"root CLAUDE.md has no pointer to: {unlisted}"

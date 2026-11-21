"""Structural guard for docs/DECISIONS.md: newest entry first, as its header says.

Parallel sessions each add an entry; an entry appended at the bottom or beside
a related one (wave 2: three of five lanes) is the mistake this catches.
"""

import re
from pathlib import Path

DECISIONS = Path(__file__).resolve().parent.parent / "docs" / "DECISIONS.md"


def test_entries_are_newest_first():
    dates = re.findall(r"^## (\d{4}-\d{2}-\d{2}) ", DECISIONS.read_text(encoding="utf-8"), re.M)
    assert dates, "no dated entry found"
    late = [f"{older} before {newer}" for older, newer in zip(dates, dates[1:]) if newer > older]
    assert not late, f"docs/DECISIONS.md is not newest first: {late}"

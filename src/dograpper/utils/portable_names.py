"""Local file-name rules shared by the httrack profile and the pack page layout (ADR-0010).

The characters HTTrack forbids become ``_``, names that differ only in case are the
same name, and a resolved path never leaves its root. Pure path computation: never
creates directories or files.
"""

import os

# htsname.c: replaced by "_" in every saved name, on every platform
FORBIDDEN = {c: "_" for c in [*range(32), 127, *map(ord, '~\\:*?"<>|')]}


def claim_unique(path: str, used: set) -> str:
    """``path``, or ``<base>-N<ext>`` with the lowest N >= 2 that is free; record it in ``used``.

    Case-insensitive, as htshash.c key_sav_equals (strcasecmp): on NTFS or APFS a
    case-only difference is the same file. casefold also folds non-ASCII (deviation).
    """
    base, ext = os.path.splitext(path)
    n, cand = 1, path
    while cand.casefold() in used:
        n += 1
        cand = f"{base}-{n}{ext}"
    used.add(cand.casefold())
    return cand


def resolve_under(root: str, *parts: str) -> str | None:
    """Real path of ``root/parts...``, or None when it leaves ``root`` (``..``, a symlink).

    ``root`` must already be a real path.
    """
    full = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath([root, full]) != root:
        return None
    return full

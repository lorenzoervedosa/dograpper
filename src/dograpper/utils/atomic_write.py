"""Atomic file writes: a final path only ever holds a complete file."""

import os
import tempfile


def atomic_write_bytes(path: str, data: bytes) -> None:
    """Write data to path via a temp file in the same dir, then os.replace.

    Same-dir temp keeps os.replace on one filesystem (atomic rename). Any
    BaseException, KeyboardInterrupt included, removes the temp file and
    re-raises; the final path is untouched.
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise

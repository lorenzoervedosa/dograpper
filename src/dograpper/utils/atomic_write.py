"""Atomic file writes: a final path only ever holds a complete file."""

import os
import tempfile

# Read once: os.umask can only be read by setting it, process-wide, so never per write/thread.
_UMASK = os.umask(0o022)
os.umask(_UMASK)


def atomic_write_bytes(path: str, data: bytes) -> None:
    """Write data to path via a temp file in the same dir, then os.replace.

    Same-dir temp keeps os.replace on one filesystem (atomic rename). The file
    gets the umask-default mode a plain open() would give, not mkstemp's 0600.
    Any BaseException, KeyboardInterrupt included, removes the temp file and
    re-raises; the final path is untouched.
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o666 & ~_UMASK)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise

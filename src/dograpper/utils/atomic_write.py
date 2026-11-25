"""Atomic file writes: a final path only ever holds a complete file."""

import os
import stat

# O_EXCL: never reuse an existing file nor follow a planted symlink (as mkstemp);
# O_BINARY: no newline translation on Windows.
_TMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)


def atomic_write_bytes(path: str, data: bytes, *, private: bool = False) -> None:
    """Write data to path via a temp file in the same dir, then os.replace.

    Same-dir temp keeps os.replace on one filesystem (atomic rename). The temp file
    is created with mode 0o666, so the kernel applies the current umask exactly as
    for a plain open(): the umask is never read, so never stale, and never set, so
    other threads never see it change.
    `private` (a file holding secrets, the --cookies jar): created 0o600 whatever the
    umask, while a file it replaces keeps its own permission bits.
    Any BaseException, KeyboardInterrupt included, removes the temp file and
    re-raises; the final path is untouched.
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, f"tmp{os.urandom(8).hex()}.tmp")
    mode = None
    if private:
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except FileNotFoundError:
            mode = 0o600
    # a private file is owner-only from its first byte; chmod then sets the exact bits
    fd = os.open(tmp, _TMP_FLAGS, 0o666 if mode is None else 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise

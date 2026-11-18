"""Throttled ``[progress]`` lines for the fetch steps of ``download`` (#98).

One reporter per fetch step, fed by every fetch path (wget output parser,
httrack crawl, Playwright). A known ``total`` gives the fixed-list shape
(``37/120 URLs (31%)``, ETA after 10 URLs); no total gives the growing shape
(``142 files``, optional ``queued`` and ``last`` URL), since a growing queue
would make a percentage go backwards.
"""

import logging
import time
from typing import Callable, Optional

from .redact import redact_url

logger = logging.getLogger(__name__)

INTERVAL_S = 5.0
ETA_AFTER = 10  # pacing and --delay make an ETA meaningless before this many URLs


def _size(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def _duration(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def _eta(seconds: float) -> str:
    return f"~{round(seconds / 60)}m" if seconds >= 60 else f"~{int(seconds)}s"


class ProgressReporter:
    """Prints at most one line per ``interval`` and only when the state changed,
    plus the final state on ``finish()``. ``--quiet`` hides it (INFO level)."""

    def __init__(self, step: str, total: Optional[int] = None, *, interval: float = INTERVAL_S,
                 clock: Callable[[], float] = time.monotonic,
                 emit: Callable[[str], None] = logger.info):
        self.step, self.total, self.interval = step, total, interval
        self._clock, self._emit = clock, emit
        self._start = self._last_emit = clock()
        self._state = None       # (done, size_bytes, queued, last_url) of the latest update
        self._printed = None     # state of the latest printed line

    def update(self, *, done: int, size_bytes: Optional[int] = None,
               queued: Optional[int] = None, last_url: Optional[str] = None) -> None:
        self._state = (done, size_bytes, queued, last_url)
        if self._clock() - self._last_emit >= self.interval:
            self._print()

    def finish(self) -> None:
        self._print()

    def _print(self) -> None:
        if self._state is None or self._state == self._printed:
            return
        now = self._clock()
        self._emit(self._line(now - self._start))
        self._printed, self._last_emit = self._state, now

    def _line(self, elapsed: float) -> str:
        done, size_bytes, queued, last_url = self._state
        if self.total is not None:
            pct = round(100 * done / self.total) if self.total else 100
            parts = [f"{done}/{self.total} URLs ({pct}%)"]
        else:
            parts = [f"{done} files"]
        if size_bytes is not None:
            parts.append(_size(size_bytes))
        parts.append(_duration(elapsed))
        if self.total is not None and ETA_AFTER <= done < self.total:
            parts.append(f"ETA {_eta(elapsed / done * (self.total - done))}")
        if queued is not None:
            parts.append(f"queued {queued}")
        if last_url:
            parts.append(f"last: {redact_url(last_url)}")
        return f"[progress] {self.step}: " + " · ".join(parts)

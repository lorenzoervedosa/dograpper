"""ProgressReporter: throttled [progress] lines for the fetch steps of download (#98)."""

from dograpper.utils.progress import ProgressReporter


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _reporter(**kw):
    clock, lines = Clock(), []
    return ProgressReporter(clock=clock, emit=lines.append, **kw), clock, lines


def test_fixed_list_shape_with_eta_only_after_ten_urls():
    rep, clock, lines = _reporter(step="wget -i", total=120)
    clock.t = 6
    rep.update(done=9, size_bytes=2_200_000)
    clock.t = 72
    rep.update(done=37, size_bytes=2_200_000)
    assert lines[0] == "[progress] wget -i: 9/120 URLs (8%) · 2.1 MB · 6s"
    assert lines[1] == "[progress] wget -i: 37/120 URLs (31%) · 2.1 MB · 1m12s · ETA ~3m"


def test_growing_total_shape_has_no_percentage_and_redacts_the_last_url():
    rep, clock, lines = _reporter(step="playwright")
    clock.t = 65
    rep.update(done=23, queued=41, last_url="https://user:pw@example.com/api/")
    assert lines == ["[progress] playwright: 23 files · 1m05s · queued 41 · last: https://example.com/api/"]


def test_at_most_one_line_per_interval_and_only_on_change():
    rep, clock, lines = _reporter(step="wget --mirror")
    clock.t = 5
    rep.update(done=1)
    clock.t = 7
    rep.update(done=2)            # inside the interval: held back
    clock.t = 10
    rep.update(done=2)            # interval passed and done changed: printed
    clock.t = 16
    rep.update(done=2)            # no change since the last line printed at t=10
    assert lines == ["[progress] wget --mirror: 1 files · 5s",
                     "[progress] wget --mirror: 2 files · 10s"]


def test_finish_prints_the_final_state_once():
    rep, clock, lines = _reporter(step="httrack", total=3)
    clock.t = 1
    rep.update(done=1)            # first update is held until the interval passes
    clock.t = 2
    rep.update(done=3)
    rep.finish()
    rep.finish()
    assert lines == ["[progress] httrack: 3/3 URLs (100%) · 2s"]


def test_finish_without_any_update_prints_nothing():
    rep, _, lines = _reporter(step="wget -i", total=0)
    rep.finish()
    assert lines == []


def test_defaults_to_the_info_logger(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="dograpper"):
        rep = ProgressReporter(step="wget -i", total=1, clock=lambda: 9.0)
        rep.update(done=1)
        rep.finish()
    assert any(r.levelno == logging.INFO and r.getMessage().startswith("[progress] wget -i: 1/1")
               for r in caplog.records)

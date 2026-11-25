"""assert_linear (tests/linearity.py): retry-on-exceed and the failure message (#192).

`cpu_time` is scripted per input size, so the cases do not depend on the machine.
"""

import pytest

from tests import linearity
from tests.linearity import assert_linear


def _script(monkeypatch, small, large):
    """cpu_time answers from the `small`/`large` lists, one entry per measurement."""
    queues = {"small": list(small), "large": list(large)}

    def fake(run, arg, repeats=3):
        return queues["small" if len(arg) == 10 else "large"].pop(0)

    monkeypatch.setattr(linearity, "cpu_time", fake)
    return queues


def _build(k):
    return "x" * k


def test_passes_without_a_retry_when_the_first_attempt_is_within_the_bound(monkeypatch):
    queues = _script(monkeypatch, [0.02], [0.08])
    assert assert_linear(_build, None, 10) == pytest.approx(4.0)
    assert queues == {"small": [], "large": []}  # no second measurement


def test_a_run_slow_only_on_its_first_measurement_passes(monkeypatch):
    queues = _script(monkeypatch, [0.02, 0.02], [0.40, 0.09])
    assert assert_linear(_build, None, 10) == pytest.approx(4.5)  # minima: 0.09 / 0.02
    assert queues == {"small": [], "large": []}


def test_a_quadratic_run_fails_every_attempt_and_the_message_says_why(monkeypatch):
    _script(monkeypatch, [0.02] * 3, [0.32] * 3)
    with pytest.raises(AssertionError) as err:
        assert_linear(_build, None, 10)
    msg = str(err.value)
    assert msg.count("16.0x") >= 3  # one ratio per attempt
    for text in ("n=10", "4n=40", "t(n)=", "t(4n)=", "bound=7.0", "floor=0.01", "load average"):
        assert text in msg


def test_a_floor_keeps_a_tiny_t_of_n_from_inflating_the_ratio(monkeypatch):
    _script(monkeypatch, [0.0001], [0.05])
    assert assert_linear(_build, None, 10, floor=0.01) == pytest.approx(5.0)


def test_real_timing_separates_linear_from_quadratic():
    def linear(s):
        return sum(1 for _ in s)

    def quadratic(s):
        return sum(1 for _ in s for _ in s)

    assert_linear(_build, linear, 3000, floor=1e-3)
    with pytest.raises(AssertionError):
        assert_linear(_build, quadratic, 300, floor=1e-4)

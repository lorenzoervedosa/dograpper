"""CPU-time linearity check shared by the hostile-input tests (#126, #131, #135)."""

import gc
import time


def cpu_time(run, arg, repeats=3):
    """Best-of-`repeats` CPU time of run(arg). The garbage collector is off during each
    run, as timeit does: a collection landing in one run skews the ratio."""
    best = float("inf")
    for _ in range(repeats):
        gc.collect()
        gc.disable()
        try:
            start = time.process_time()
            run(arg)
            best = min(best, time.process_time() - start)
        finally:
            gc.enable()
    return best


def assert_linear(build, run, n, bound=7.0, floor=0.01):
    """run(build(4n)) costs less than `bound` times run(build(n)): linear work gives a
    ratio near 4, quadratic near 16. CPU time, so other processes on the machine do not
    count. `floor` keeps a tiny t(n) from turning timer noise into a huge ratio. The
    default 7 sits above the worst clean ratio seen under load (~5.4) and below the
    weakest regression the api-reference tests catch (~7.7)."""
    small, large = cpu_time(run, build(n)), cpu_time(run, build(4 * n))
    ratio = large / max(small, floor)
    assert ratio < bound, f"4x input took {ratio:.1f}x CPU time"
    return ratio

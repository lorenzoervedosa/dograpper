"""CPU-time linearity check shared by the hostile-input tests (#126, #131, #135)."""

import gc
import os
import time

ATTEMPTS = 3


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
    count. `floor` keeps a tiny t(n) from turning timer noise into a huge ratio: the
    ratio is t(4n) / max(t(n), floor), so below the floor even a quadratic passes (a
    quadratic is caught only when t(n) is above about floor * bound / 16). Size the input
    so t(n) clears it. The default 7 sits above the worst clean ratio seen under load
    (~5.4) and below the weakest regression the api-reference tests catch (~7.7).

    Retry-on-exceed (#192): when an attempt exceeds the bound, both sizes are measured
    again, up to 3 attempts in total, keeping the minimum time per size across attempts;
    it fails only if the ratio of those minima still exceeds the bound. A first attempt
    that passes costs nothing extra. Host load only ever inflates a time, so a minimum
    can only move toward the true cost: a quadratic stays above the bound on every
    attempt. The failure message carries every attempt's ratio, the sizes, the times,
    the bound, the floor and the load average. Returns the passing ratio."""
    small_in, large_in = build(n), build(4 * n)
    best_small = best_large = float("inf")
    ratios = []
    for _ in range(ATTEMPTS):
        small, large = cpu_time(run, small_in), cpu_time(run, large_in)
        ratios.append(large / max(small, floor))
        best_small, best_large = min(best_small, small), min(best_large, large)
        ratio = best_large / max(best_small, floor)
        if ratio < bound:
            return ratio
    raise AssertionError(
        f"4x input took {ratio:.1f}x CPU time on {len(ratios)} attempts "
        f"(per attempt: {', '.join(f'{r:.1f}x' for r in ratios)}); "
        f"n={n}, 4n={4 * n}; t(n)={best_small * 1000:.2f} ms, t(4n)={best_large * 1000:.2f} ms "
        f"(minima); bound={bound}, floor={floor}; "
        f"load average {', '.join(f'{x:.1f}' for x in os.getloadavg())}"
    )

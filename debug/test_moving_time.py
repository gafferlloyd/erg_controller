"""Smoke tests for moving_time.py.

Run from project root:
  python debug/test_moving_time.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from moving_time import to_moving_time_1hz
from wbal_review import calc_wbal


def test_no_gaps_matches_plain_arrays():
    elapsed = np.arange(10, dtype=float)
    power = [100.0] * 10
    hr = [140.0] * 10
    p, h = to_moving_time_1hz(elapsed, power, hr)
    assert list(p) == power, p
    assert list(h) == hr, h
    print('  test_no_gaps_matches_plain_arrays      PASS')


def test_small_gap_still_nan_filled():
    """A 3s gap (below the 5s threshold) should still insert NaN placeholders,
    same as _to_1s_grid would -- only genuine pauses get collapsed."""
    elapsed = np.array([0.0, 1.0, 4.0])  # 3s gap between samples 1 and 2
    power = [100.0, 100.0, 100.0]
    hr = [140.0, 140.0, 140.0]
    p, h = to_moving_time_1hz(elapsed, power, hr)
    assert len(p) == 5, p  # 0,1,[nan,nan],4 -> 5 slots
    assert np.isnan(p[2]) and np.isnan(p[3]), p
    print('  test_small_gap_still_nan_filled         PASS')


def test_large_gap_is_collapsed_not_nan_filled():
    """A pause (gap > threshold) must be collapsed entirely -- no NaN seconds
    inserted for it at all, unlike a small recording blip."""
    elapsed = np.array([0.0, 1.0, 601.0])  # a 600s pause after sample 1
    power = [100.0, 100.0, 200.0]
    hr = [140.0, 140.0, 130.0]
    p, h = to_moving_time_1hz(elapsed, power, hr, gap_threshold_s=5.0)
    assert len(p) == 3, f'pause must be collapsed, got length {len(p)}'
    assert list(p) == [100.0, 100.0, 200.0], p
    print('  test_large_gap_is_collapsed_not_nan_filled  PASS')


def test_none_values_become_nan():
    elapsed = np.array([0.0, 1.0])
    p, h = to_moving_time_1hz(elapsed, [100.0, None], [140.0, None])
    assert np.isnan(p[1]) and np.isnan(h[1])
    print('  test_none_values_become_nan            PASS')


def test_pause_no_longer_grants_free_wbal_recovery():
    """The actual bug this fixes: a long pause must NOT let W'bal recover as
    if the rider coasted through it -- moving-time should show continued
    depletion picking up right where it left off pre-pause."""
    # 5 min hard (400W, way above a 250W CP) depletes W', then a long pause,
    # then more hard riding. If the pause were wall-clock-elapsed and treated
    # as 0W recovery, W'bal would refill substantially during it.
    elapsed = np.concatenate([
        np.arange(300),                    # 300s @ 400W
        [300.0 + 2400.0],                  # a 2400s (40min) pause collapsed to one step
        300.0 + 2400.0 + np.arange(1, 301),  # another 300s @ 400W after the pause
    ])
    power = [400.0] * 300 + [400.0] + [400.0] * 300
    hr = [160.0] * 601

    p_moving, _ = to_moving_time_1hz(elapsed, power, hr)
    wbal_moving = calc_wbal(p_moving, cp=250.0, wprime=21000.0)

    # Without the fix (wall-clock elapsed, pause filled with 0W), the model
    # would have ~2400s of recovery time in the middle -- refilling close to
    # full. With the fix, moving time is only ~601s of continuous 400W, so
    # W'bal should be MUCH lower at the end (still heavily depleted).
    assert wbal_moving[-1] < 5000, f'expected heavy depletion, got {wbal_moving[-1]:.0f}J'
    print('  test_pause_no_longer_grants_free_wbal_recovery  PASS')


if __name__ == '__main__':
    test_no_gaps_matches_plain_arrays()
    test_small_gap_still_nan_filled()
    test_large_gap_is_collapsed_not_nan_filled()
    test_none_values_become_nan()
    test_pause_no_longer_grants_free_wbal_recovery()
    print('\nAll tests passed.')

"""Smoke tests for best_efforts.py's rolling-window best-effort finder.

Run from project root:
  python debug/test_best_efforts.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from best_efforts import best_effort


def test_finds_known_spike():
    """A 60s spike of 400W in a sea of 100W should be found exactly."""
    power = np.full(600, 100.0)
    power[200:260] = 400.0
    avg_p, start, _hr = best_effort(power, np.full(600, np.nan), window=60)
    assert abs(avg_p - 400.0) < 0.01, avg_p
    assert start == 200, start
    print('  test_finds_known_spike        PASS')


def test_window_longer_than_data_returns_none():
    power = np.full(100, 200.0)
    result = best_effort(power, np.full(100, np.nan), window=200)
    assert result is None, result
    print('  test_window_longer_than_data_returns_none  PASS')


def test_hr_averaged_over_same_window():
    power = np.full(120, 100.0)
    power[10:20] = 500.0
    hr = np.full(120, 120.0)
    hr[10:20] = 160.0
    avg_p, start, avg_hr = best_effort(power, hr, window=10)
    assert start == 10, start
    assert abs(avg_hr - 160.0) < 0.01, avg_hr
    print('  test_hr_averaged_over_same_window  PASS')


def test_nan_power_treated_as_zero():
    """NaN gaps count as 0W, same convention as wprime_locus.py / wbal_review.py."""
    power = np.array([300.0, 300.0, np.nan, np.nan])
    avg_p, start, _hr = best_effort(power, np.full(4, np.nan), window=2)
    # Best 2s window must be the first pair (300+300)/2=300, not straddling the gap
    assert start == 0, start
    assert abs(avg_p - 300.0) < 0.01, avg_p
    print('  test_nan_power_treated_as_zero  PASS')


if __name__ == '__main__':
    test_finds_known_spike()
    test_window_longer_than_data_returns_none()
    test_hr_averaged_over_same_window()
    test_nan_power_treated_as_zero()
    print('\nAll tests passed.')

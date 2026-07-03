"""Smoke tests for wbal_review.py's calc_wbal() against js/wbal.js's calcWbal().

Run from project root:
  python debug/test_wbal_review.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from wbal_review import calc_wbal


def test_depletion_matches_linear_rule():
    """100s at 300W, CP=200: depletes 100J/s -> wbal = 21000 - 100*t."""
    power = np.array([300.0] * 100)
    wbal = calc_wbal(power, cp=200, wprime=21000)
    expected_final = 21000 - 100 * 100
    assert abs(wbal[-1] - expected_final) < 1, f'expected {expected_final}, got {wbal[-1]}'
    # Monotonically decreasing throughout
    assert np.all(np.diff(wbal) <= 0)
    print('  test_depletion_matches_linear_rule   PASS')


def test_floor_at_zero():
    """Enough above-CP time to fully deplete must floor at 0, not go negative."""
    power = np.array([500.0] * 1000)  # way more than enough to hit 0
    wbal = calc_wbal(power, cp=200, wprime=21000)
    assert wbal[-1] == 0.0, wbal[-1]
    assert wbal.min() >= 0.0
    print('  test_floor_at_zero                   PASS')


def test_recovery_approaches_wprime():
    """Long rest after depletion should recover back toward wprime (not overshoot)."""
    power = np.concatenate([np.full(200, 500.0), np.full(3600, 0.0)])
    wbal = calc_wbal(power, cp=200, wprime=21000)
    assert wbal[-1] > wbal[200], 'should have recovered from the post-depletion low'
    assert wbal[-1] <= 21000, 'must not overshoot wprime'
    assert wbal[-1] > 0.99 * 21000, f'should be nearly fully recovered, got {wbal[-1]}'
    print('  test_recovery_approaches_wprime      PASS')


def test_gaps_treated_as_zero_power():
    """NaN samples should behave like 0W (recovery), matching wprime_locus.py convention."""
    power = np.array([500.0, 500.0, np.nan, np.nan])
    wbal = calc_wbal(power, cp=200, wprime=21000)
    assert wbal[3] > wbal[1], 'NaN gap should have allowed some recovery, not stayed flat/depleted'
    print('  test_gaps_treated_as_zero_power      PASS')


if __name__ == '__main__':
    test_depletion_matches_linear_rule()
    test_floor_at_zero()
    test_recovery_approaches_wprime()
    test_gaps_treated_as_zero_power()
    print('\nAll tests passed.')

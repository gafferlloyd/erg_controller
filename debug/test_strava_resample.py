"""Smoke tests for strava_resample.py -- specifically demonstrates the forward-fill
vs. NaN-gap difference against wprime_locus._to_1s_grid on the same input, so the
intentional divergence is regression-proof.

Run from project root:
  python debug/test_strava_resample.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from strava_resample import resample_to_1hz


def test_basic_forward_fill():
    # Samples at t=0,2,4 -- gaps at t=1,3 should hold the prior value forward
    time_s = [0, 2, 4]
    values = [100, 200, 300]
    out = resample_to_1hz(values, time_s)
    assert list(out) == [100, 100, 200, 200, 300], list(out)
    print('  test_basic_forward_fill         PASS')


def test_none_treated_as_zero():
    time_s = [0, 1]
    values = [None, 50]
    out = resample_to_1hz(values, time_s)
    assert out[0] == 0.0, out
    assert out[1] == 50.0, out
    print('  test_none_treated_as_zero       PASS')


def test_diverges_from_nan_gap_convention():
    """Same sparse input: strava_resample forward-fills, wprime_locus leaves NaN gaps."""
    from wprime_locus import _to_1s_grid
    elapsed = np.array([0.0, 5.0])   # a 5s gap between samples
    raw_power = [100, 200]
    raw_hr = [None, None]

    p_nan_gap, _ = _to_1s_grid(elapsed, raw_power, raw_hr)
    p_forward_fill = resample_to_1hz(raw_power, [0, 5])

    # wprime_locus: only indices 0 and 5 are filled, the rest (1..4) are NaN
    assert np.isnan(p_nan_gap[2]), 'expected NaN gap convention in wprime_locus'
    # strava_resample: index 2 forward-fills the value from index 0 (100)
    assert p_forward_fill[2] == 100.0, p_forward_fill
    print('  test_diverges_from_nan_gap_convention  PASS')


if __name__ == '__main__':
    test_basic_forward_fill()
    test_none_treated_as_zero()
    test_diverges_from_nan_gap_convention()
    print('\nAll tests passed.')

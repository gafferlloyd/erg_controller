"""Smoke tests for hr_efficiency.py.

Run from project root:
  python debug/test_hr_efficiency.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hr_efficiency import bin_by_minute, linear_regression, linear_regression_fixed, pct_hrr


def test_bin_uses_last_sample_hr_not_average():
    """Guards the deliberate lag-reduction choice: y must be the LAST hr in
    the bin, not the mean. Bin [0,60) covers indices 0..59; index 60 (time=60)
    falls just outside it and into a (nonexistent, too-short) next bin."""
    time_s = list(range(61))
    watts = [200.0] * 61
    heartrate = [100.0] * 59 + [160.0] + [100.0]  # index 59 (last IN-bin sample) jumps up
    bins = bin_by_minute(time_s, watts, heartrate)
    assert len(bins) == 1, bins
    mean_hr = (59 * 100.0 + 160.0) / 60
    assert bins[0]['y'] == 160.0, bins       # last sample in the bin, not the mean
    assert bins[0]['y'] != round(mean_hr, 6)  # sanity: mean would clearly differ (~101)
    print('  test_bin_uses_last_sample_hr_not_average  PASS')


def test_bin_filters_out_of_range_hr():
    time_s = list(range(61))
    watts = [200.0] * 61
    heartrate = [30.0] * 61   # below the 40bpm floor -- whole bin dropped
    bins = bin_by_minute(time_s, watts, heartrate)
    assert bins == [], bins
    print('  test_bin_filters_out_of_range_hr        PASS')


def test_linear_regression_perfect_fit():
    pts = [{'x': 100, 'y': 120}, {'x': 200, 'y': 140}, {'x': 300, 'y': 160}]
    reg = linear_regression(pts)
    assert abs(reg['m'] - 0.2) < 1e-9, reg
    assert abs(reg['c'] - 100.0) < 1e-9, reg
    assert abs(reg['r2'] - 1.0) < 1e-9, reg
    print('  test_linear_regression_perfect_fit      PASS')


def test_linear_regression_needs_3_points():
    assert linear_regression([{'x': 1, 'y': 1}, {'x': 2, 'y': 2}]) is None
    print('  test_linear_regression_needs_3_points   PASS')


def test_linear_regression_fixed_uses_given_intercept():
    pts = [{'x': 100, 'y': 120}, {'x': 200, 'y': 140}, {'x': 300, 'y': 160}]
    reg = linear_regression_fixed(pts, c0=100.0)
    assert reg['c'] == 100.0, reg
    assert abs(reg['m'] - 0.2) < 1e-6, reg  # same data still recovers m=0.2 when c0 is the true intercept
    print('  test_linear_regression_fixed_uses_given_intercept  PASS')


def test_pct_hrr():
    # rest=43, max=173 -> range=130. HR=108 -> (108-43)/130*100 = 50%
    assert abs(pct_hrr(108.0, rest_hr=43, max_hr=173) - 50.0) < 1e-6
    print('  test_pct_hrr                            PASS')


if __name__ == '__main__':
    test_bin_uses_last_sample_hr_not_average()
    test_bin_filters_out_of_range_hr()
    test_linear_regression_perfect_fit()
    test_linear_regression_needs_3_points()
    test_linear_regression_fixed_uses_given_intercept()
    test_pct_hrr()
    print('\nAll tests passed.')

"""Smoke tests for strava_summary.py.

Run from project root:
  python debug/test_strava_summary.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from strava_summary import build_summary


def _make_ride(duration_s, power_fn, hr_fn):
    """Synthetic already-1Hz-uniform ride -- power_1hz/hr_1hz need no resampling here."""
    time_s = list(range(duration_s))
    watts = [power_fn(t) for t in time_s]
    heartrate = [hr_fn(t) for t in time_s]
    power_1hz = np.array(watts, dtype=float)
    hr_1hz = np.array([np.nan if h is None else h for h in heartrate], dtype=float)
    return power_1hz, hr_1hz, time_s, watts, heartrate


def test_short_ride_degrades_gracefully_no_weight():
    """25-minute ride: 60min window should say n/a; weight_kg=0 -> no W/kg clause."""
    power_1hz, hr_1hz, time_s, watts, heartrate = _make_ride(
        25 * 60, lambda t: 200.0 + 50 * (t % 10 == 0), lambda t: 130.0)
    activity = {'name': 'Test Ride', 'start_date_local': '2026-07-04T08:00:00Z'}
    summary = build_summary(activity, power_1hz, hr_1hz, time_s, watts, heartrate, weight_kg=0)
    assert 'Ride: Test Ride, 2026-07-04' in summary
    assert '60min: n/a (ride is 25min)' in summary
    assert 'W/kg' not in summary  # falsy weight -> clause omitted
    print('  test_short_ride_degrades_gracefully_no_weight  PASS')
    return summary


def test_with_weight_includes_wkg():
    power_1hz, hr_1hz, time_s, watts, heartrate = _make_ride(
        25 * 60, lambda t: 250.0, lambda t: 140.0)
    activity = {'name': 'Test Ride 2', 'start_date_local': '2026-07-04T08:00:00Z'}
    summary = build_summary(activity, power_1hz, hr_1hz, time_s, watts, heartrate, weight_kg=70.0)
    assert 'W/kg' in summary, summary
    print('  test_with_weight_includes_wkg          PASS')


def test_default_weight_used_when_none():
    """weight_kg=None (the default) should fall back to hr_efficiency.WEIGHT_KG, not omit W/kg."""
    power_1hz, hr_1hz, time_s, watts, heartrate = _make_ride(
        25 * 60, lambda t: 250.0, lambda t: 140.0)
    activity = {'name': 'Test Ride 3', 'start_date_local': '2026-07-04'}
    summary = build_summary(activity, power_1hz, hr_1hz, time_s, watts, heartrate)
    assert 'W/kg' in summary, summary
    print('  test_default_weight_used_when_none     PASS')


def test_sparse_hr_falls_back_gracefully():
    """HR present for <3 minutes worth of bins -> efficiency line degrades, doesn't crash."""
    duration = 25 * 60
    heartrate = [None] * (duration - 30) + [140.0] * 30  # only the last 30s has HR
    power_1hz, hr_1hz, time_s, watts, heartrate = _make_ride(
        duration, lambda t: 200.0, lambda t: heartrate[t])
    activity = {'name': 'Sparse HR Ride', 'start_date_local': '2026-07-04'}
    summary = build_summary(activity, power_1hz, hr_1hz, time_s, watts, heartrate, weight_kg=70.0)
    assert 'insufficient HR data' in summary, summary
    print('  test_sparse_hr_falls_back_gracefully   PASS')


def test_full_output_shape_smoke():
    summary = test_short_ride_degrades_gracefully_no_weight()
    expected_labels = ["CP/W' check", "Solved CP @ W'=15", "Solved CP @ W'=25",
                        'BE-FTP est.', 'Pinot-Grappe FTP est.', '20min:', '60min:', 'Efficiency']
    for label in expected_labels:
        assert label in summary, f'missing {label!r} in:\n{summary}'
    print('  test_full_output_shape_smoke           PASS')


if __name__ == '__main__':
    test_short_ride_degrades_gracefully_no_weight()
    test_with_weight_includes_wkg()
    test_default_weight_used_when_none()
    test_sparse_hr_falls_back_gracefully()
    test_full_output_shape_smoke()
    print('\nAll tests passed.')

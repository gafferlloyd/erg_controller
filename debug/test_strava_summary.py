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


def test_ftp_lines_include_hrr_qualifier():
    """BE-FTP/PG-FTP lines should be qualified with the %HRR of the window they came from."""
    power_1hz, hr_1hz, time_s, watts, heartrate = _make_ride(
        30 * 60, lambda t: 250.0, lambda t: 140.0)  # constant HR -> a real, computable %HRR
    activity = {'name': 'HRR Qualifier Test', 'start_date_local': '2026-07-04'}
    summary = build_summary(activity, power_1hz, hr_1hz, time_s, watts, heartrate, weight_kg=70.0)
    for line in summary.splitlines():
        if 'BE-FTP est.' in line or 'Pinot-Grappe FTP est.' in line:
            assert '% HRR' in line, f'missing HRR qualifier in: {line!r}'
    print('  test_ftp_lines_include_hrr_qualifier   PASS')


def test_efficiency_line_has_no_fit_metadata_overhead():
    """Efficiency line should be just the number now -- no R^2/n/fit-method clutter."""
    summary = test_short_ride_degrades_gracefully_no_weight()
    eff_line = next(l for l in summary.splitlines() if 'Efficiency' in l)
    assert 'R^2' not in eff_line, eff_line
    assert 'bins' not in eff_line, eff_line
    assert 'HRR-fixed fit' not in eff_line, eff_line
    print('  test_efficiency_line_has_no_fit_metadata_overhead  PASS')


def test_emojis_present():
    summary = test_short_ride_degrades_gracefully_no_weight()
    for emoji in ('\U0001F6B4', '\U0001F50B', '\U0001F3AF', '\U0001F4CA', '⏱️', '⚙️'):
        assert emoji in summary, f'missing {emoji!r}'
    print('  test_emojis_present                    PASS')


def test_ride_tag_is_last_line():
    summary = test_short_ride_degrades_gracefully_no_weight()
    lines = summary.splitlines()
    assert lines[-1].startswith('\U0001F6B4 Ride:'), lines[-1]
    assert not lines[0].startswith('\U0001F6B4'), 'ride tag should no longer be first'
    print('  test_ride_tag_is_last_line             PASS')


def test_wkg_on_cp_and_ftp_lines():
    power_1hz, hr_1hz, time_s, watts, heartrate = _make_ride(
        70 * 60, lambda t: 250.0, lambda t: 140.0)
    activity = {'name': 'Wkg Test', 'start_date_local': '2026-07-04'}
    summary = build_summary(activity, power_1hz, hr_1hz, time_s, watts, heartrate, weight_kg=70.0)
    for line in summary.splitlines():
        if any(tag in line for tag in ("CP/W' check", 'Solved CP', 'BE-FTP est.', 'Pinot-Grappe FTP est.')):
            assert 'W/kg' in line, f'missing W/kg in: {line!r}'
    print('  test_wkg_on_cp_and_ftp_lines           PASS')


def test_ftp_models_use_np_not_average_power():
    """A variable-power ride: NP should be well above the plain average, and the
    reported FTP estimate must reflect the NP-based value, not the (lower) average."""
    from strava_summary import _ftp_model_lines
    from power_curve import best_power_by_minute, power_curve_window, be_ftp_model, apply_ftp_model

    duration = 30 * 60
    # 60s at 500W, 60s at 0W, repeating -- a real average of 250W but a much higher NP.
    power_1hz = np.array([500.0 if (t // 60) % 2 == 0 else 0.0 for t in range(duration)])
    hr_1hz = np.full(duration, 140.0)

    lines = _ftp_model_lines(power_1hz, hr_1hz, weight_kg=0)
    be_ftp_line = next(l for l in lines if 'BE-FTP est.' in l)
    reported_watts = float(be_ftp_line.split(':')[1].strip().split('W')[0])

    best_powers = best_power_by_minute(power_1hz)
    longest = max(best_powers, key=lambda bp: bp['t_min'])
    window = power_curve_window(power_1hz, hr_1hz, longest['t_min'] * 60)
    avg_based = apply_ftp_model([longest], be_ftp_model())[0]['ftp_est']
    np_based = apply_ftp_model([{'t_min': longest['t_min'], 'power': window['np']}], be_ftp_model())[0]['ftp_est']

    assert np_based > avg_based + 1, 'NP-based and average-based should meaningfully differ for this trace'
    assert abs(reported_watts - np_based) < 1, f'expected NP-based {np_based:.0f}W, got {reported_watts:.0f}W'
    assert abs(reported_watts - avg_based) > 1, 'line should NOT match the average-power-based estimate'
    print('  test_ftp_models_use_np_not_average_power  PASS')


if __name__ == '__main__':
    test_short_ride_degrades_gracefully_no_weight()
    test_with_weight_includes_wkg()
    test_default_weight_used_when_none()
    test_sparse_hr_falls_back_gracefully()
    test_full_output_shape_smoke()
    test_ftp_lines_include_hrr_qualifier()
    test_efficiency_line_has_no_fit_metadata_overhead()
    test_emojis_present()
    test_ride_tag_is_last_line()
    test_wkg_on_cp_and_ftp_lines()
    test_ftp_models_use_np_not_average_power()
    print('\nAll tests passed.')

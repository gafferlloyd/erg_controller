"""Smoke tests for power_curve.py.

Run from project root:
  python debug/test_power_curve.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from power_curve import (normalized_power, power_curve_window, best_power_by_minute,
                          be_ftp_model, pinot_grappe_model, apply_ftp_model)


def test_np_constant_power_equals_power():
    power = np.full(300, 200.0)
    assert abs(normalized_power(power) - 200.0) < 0.01
    print('  test_np_constant_power_equals_power  PASS')


def test_np_short_slice_returns_none():
    assert normalized_power(np.full(29, 200.0)) is None
    print('  test_np_short_slice_returns_none      PASS')


def test_np_variable_power_exceeds_average():
    # Alternating 0/400W -- NP should be well above the plain average (100W)
    power = np.tile([0.0, 0.0, 0.0, 400.0], 100)
    avg = power.mean()
    np_val = normalized_power(power)
    assert np_val > avg, (np_val, avg)
    print('  test_np_variable_power_exceeds_average  PASS')


def test_power_curve_window_finds_spike_and_its_np():
    power = np.full(600, 100.0)
    power[200:260] = 300.0  # 60s spike
    hr = np.full(600, 140.0)
    result = power_curve_window(power, hr, window_s=60)
    assert result is not None
    assert abs(result['avg_power'] - 300.0) < 0.01, result
    assert result['start'] == 200, result
    assert abs(result['np'] - 300.0) < 0.01, result  # constant within window -> NP == avg
    print('  test_power_curve_window_finds_spike_and_its_np  PASS')


def test_power_curve_window_too_long_returns_none():
    power = np.full(100, 200.0)
    assert power_curve_window(power, np.full(100, np.nan), window_s=200) is None
    print('  test_power_curve_window_too_long_returns_none  PASS')


def test_best_power_by_minute_shape():
    power = np.full(20 * 60, 150.0)  # 20-minute ride
    results = best_power_by_minute(power)
    t_mins = [r['t_min'] for r in results]
    assert t_mins == list(range(5, 20)), t_mins  # up to 19min (20min window would equal total len)
    assert all(abs(r['power'] - 150.0) < 0.01 for r in results)
    print('  test_best_power_by_minute_shape       PASS')


def test_be_ftp_model_exact_at_anchors():
    model = be_ftp_model(t1_min=20, f1=0.95, t2_min=60, f2=1.00)
    assert abs(model['predict'](20) - 0.95) < 1e-9
    assert abs(model['predict'](60) - 1.00) < 1e-9
    print('  test_be_ftp_model_exact_at_anchors    PASS')


def test_pinot_grappe_model_bounded_and_increasing_fraction():
    # p60/P_model(t) rises toward the cap as t grows, since P_model(t) (the
    # reference power) falls with duration while p60 stays fixed.
    model = pinot_grappe_model()
    f5 = model['predict'](5)
    f60 = model['predict'](60)
    f240 = model['predict'](240)
    assert 0 < f5 <= f60 <= f240 <= 1.0, (f5, f60, f240)
    print('  test_pinot_grappe_model_bounded_and_increasing_fraction  PASS')


def test_apply_ftp_model():
    model = be_ftp_model(20, 0.95, 60, 1.00)
    best_powers = [{'t_min': 20, 'power': 300.0}, {'t_min': 60, 'power': 250.0}]
    applied = apply_ftp_model(best_powers, model)
    assert abs(applied[0]['ftp_est'] - 300.0 * 0.95) < 1e-6
    assert abs(applied[1]['ftp_est'] - 250.0 * 1.00) < 1e-6
    print('  test_apply_ftp_model                  PASS')


if __name__ == '__main__':
    test_np_constant_power_equals_power()
    test_np_short_slice_returns_none()
    test_np_variable_power_exceeds_average()
    test_power_curve_window_finds_spike_and_its_np()
    test_power_curve_window_too_long_returns_none()
    test_best_power_by_minute_shape()
    test_be_ftp_model_exact_at_anchors()
    test_pinot_grappe_model_bounded_and_increasing_fraction()
    test_apply_ftp_model()
    print('\nAll tests passed.')

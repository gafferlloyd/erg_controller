"""Smoke tests for cp_solver.py.

Run from project root:
  python debug/test_cp_solver.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from cp_solver import solve_cp_for_wprime


def test_recovers_known_breakeven_cp():
    """1000s constant 300W, W'=15000J -> breakeven CP = 300 - 15000/1000 = 285W
    (at CP=285, cumulative depletion over 1000s exactly consumes 15000J)."""
    power = np.full(1000, 300.0)
    result = solve_cp_for_wprime(power, wprime=15000.0, tol=0.2)
    assert result['status'] == 'ok', result
    assert abs(result['cp'] - 285.0) < 1.0, result
    print(f"  test_recovers_known_breakeven_cp   PASS (cp={result['cp']:.2f}, "
          f"iterations={result['iterations']})")


def test_ride_too_easy():
    """100W constant, well below even cp_lo -- never depletes at all."""
    power = np.full(60, 100.0)
    result = solve_cp_for_wprime(power, wprime=21000.0, cp_lo=150, cp_hi=400)
    assert result['status'] == 'ride_too_easy', result
    assert result['cp'] is None, result
    print('  test_ride_too_easy                 PASS')


def test_ride_too_hard():
    """1000W constant, tiny W' -- still bottoms out even at cp_hi=400."""
    power = np.full(500, 1000.0)
    result = solve_cp_for_wprime(power, wprime=5000.0, cp_lo=150, cp_hi=400)
    assert result['status'] == 'ride_too_hard', result
    assert result['cp'] is None, result
    print('  test_ride_too_hard                  PASS')


if __name__ == '__main__':
    test_recovers_known_breakeven_cp()
    test_ride_too_easy()
    test_ride_too_hard()
    print('\nAll tests passed.')

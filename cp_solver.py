"""Solve for the CP that makes a ride's W'bal model exactly breakeven at a
given assumed W' -- the same "breakeven" concept used to originally derive
the 276.7W calibration figure from a specific ride (see docs/wprime_calibration.md).

calc_wbal() clamps to [0, wprime], so "does the minimum touch zero" is true
for an entire range of too-low CPs, not just one -- not directly bisectable.
The clean monotonic signal instead is how many seconds the trace spends
PINNED at the zero floor: this shrinks monotonically as CP rises (higher CP
both reduces above-CP depletion directly, and shortens the recovery time
constant for any given below-CP power) and hits exactly zero at the true
breakeven CP.
"""
from __future__ import annotations
import numpy as np

from wbal_review import calc_wbal
from wprime_locus import CP_LO_DEFAULT, CP_HI_DEFAULT


def _floor_seconds(power: np.ndarray, cp: float, wprime: float) -> int:
    wbal = calc_wbal(power, cp, wprime)
    return int(np.sum(wbal <= 0))


def solve_cp_for_wprime(power: np.ndarray, wprime: float,
                         cp_lo: float = CP_LO_DEFAULT, cp_hi: float = CP_HI_DEFAULT,
                         tol: float = 0.5, max_iter: int = 40) -> dict:
    """Bisect for the breakeven CP at the given assumed W'.

    Returns {'wprime', 'cp': float|None, 'iterations': int, 'status': str}.
      status='ride_too_easy' : never pins the floor even at cp_lo -- ride
                                wasn't hard enough to solve; true breakeven
                                (if any) is below cp_lo.
      status='ride_too_hard' : still pins the floor even at cp_hi -- true
                                breakeven is above the search range.
      status='ok'            : bisected a crossing within [cp_lo, cp_hi].
    """
    if _floor_seconds(power, cp_lo, wprime) == 0:
        return {'wprime': wprime, 'cp': None, 'iterations': 0, 'status': 'ride_too_easy'}
    if _floor_seconds(power, cp_hi, wprime) > 0:
        return {'wprime': wprime, 'cp': None, 'iterations': 0, 'status': 'ride_too_hard'}

    lo, hi = cp_lo, cp_hi
    iterations = 0
    while hi - lo > tol and iterations < max_iter:
        mid = (lo + hi) / 2.0
        if _floor_seconds(power, mid, wprime) > 0:
            lo = mid   # still too low -- breakeven is higher
        else:
            hi = mid   # high enough -- breakeven is at or below mid
        iterations += 1

    return {'wprime': wprime, 'cp': hi, 'iterations': iterations, 'status': 'ok'}

"""Normalized Power, power-curve-at-duration, and FTP models, ported from
~/strava-efficiency/content.js (computeNP, computePowerCurve, buildBeFtpModel,
buildPinotGrappeModel, applyFtpModel -- lines ~739-826).

power_curve_window() reuses best_efforts.best_effort() for the sliding-window
search rather than reimplementing it -- same technique, just adds NP of the
found window on top.
"""
from __future__ import annotations
import math

import numpy as np

from best_efforts import best_effort


def normalized_power(power_slice: np.ndarray) -> float | None:
    """30s rolling average -> 4th-power mean -> 4th root. None if <30 samples."""
    n = len(power_slice)
    if n < 30:
        return None
    prefix = np.concatenate(([0.0], np.cumsum(power_slice)))
    rolling_avg = (prefix[30:] - prefix[:-30]) / 30.0
    return float(np.mean(rolling_avg ** 4) ** 0.25)


def power_curve_window(power_1hz: np.ndarray, hr_1hz: np.ndarray, window_s: int) -> dict | None:
    """Best-average-power window of this duration, plus NP and avg HR within it.

    "Max NP for Nmin" means: find the best AVERAGE-power window of that
    duration, then report the NP (and HR) of that specific window -- not a
    separate search for a max-NP window.
    """
    result = best_effort(power_1hz, hr_1hz, window_s)
    if result is None:
        return None
    avg_p, start, avg_hr = result
    np_val = normalized_power(power_1hz[start:start + window_s])
    return {'window_s': window_s, 'avg_power': avg_p, 'np': np_val, 'hr': avg_hr, 'start': start}


def best_power_by_minute(power_1hz: np.ndarray) -> list[dict]:
    """Best average power for each whole-minute duration from 5min up to min(60, ride_len)."""
    total = len(power_1hz)
    max_min = min(60, (total - 1) // 60)
    results = []
    for t_min in range(5, max_min + 1):
        window_s = t_min * 60
        if window_s >= total:
            break
        result = best_effort(power_1hz, np.full(total, np.nan), window_s)
        if result is None:
            continue
        avg_p, _start, _hr = result
        if avg_p >= 1:
            results.append({'t_min': t_min, 'power': avg_p})
    return results


def be_ftp_model(t1_min: float = 20.0, f1: float = 0.95,
                  t2_min: float = 60.0, f2: float = 1.00) -> dict | None:
    """Two-point power law: log10(fraction) = m*log10(t) + c. Default: Coggan convention."""
    if not (t1_min > 0 and t2_min > 0 and f1 > 0 and f2 > 0 and t1_min != t2_min):
        return None
    m = (math.log10(f2) - math.log10(f1)) / (math.log10(t2_min) - math.log10(t1_min))
    c = math.log10(f1) - m * math.log10(t1_min)

    def predict(t_min):
        return min(1.0, 10 ** (m * math.log10(t_min) + c))

    return {'m': m, 'c': c, 'predict': predict}


# Pinot & Grappe (2014) Table 1: 13 data points from professional cyclists.
_PG_DURATIONS_MIN = [5, 5.5, 6, 6.5, 7, 10, 20, 30, 45, 60, 120, 180, 240]
_PG_POWERS_W = [443, 438, 431, 427, 423, 408, 382, 360, 343, 329, 303, 288, 272]
_PG_P60 = 329


def pinot_grappe_model() -> dict:
    """FTP_ratio(t) = p60 / P_model(t), where P_model is a log-linear fit to published data."""
    xs = [math.log10(t) for t in _PG_DURATIONS_MIN]
    n = len(xs)
    xm = sum(xs) / n
    ym = sum(_PG_POWERS_W) / n
    num = sum((xs[i] - xm) * (_PG_POWERS_W[i] - ym) for i in range(n))
    den = sum((x - xm) ** 2 for x in xs)
    b = num / den
    a = ym - b * xm

    def predict(t_min):
        p_model = a + b * math.log10(t_min)
        if p_model <= 0:
            return 0.0
        return min(1.0, _PG_P60 / p_model)

    return {'A': a, 'B': b, 'p60': _PG_P60, 'predict': predict}


def apply_ftp_model(best_powers: list[dict], model: dict) -> list[dict]:
    results = []
    for bp in best_powers:
        fraction = model['predict'](bp['t_min'])
        if fraction <= 0:
            continue
        results.append({'t_min': bp['t_min'], 'power': bp['power'],
                         'fraction': fraction, 'ftp_est': bp['power'] * fraction})
    return results

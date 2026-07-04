"""HR-vs-power efficiency regression, ported from ~/strava-efficiency/content.js
(binByMinute, linearRegression, linearRegressionFixed -- lines ~583-639).

Cycling branch only (the running/GAP branch is dropped -- this automation is
cycling-only by filter). REST_HR/MAX_HR mirror the constants already used in
js/profile.js and js/fit_profile.js for this rider.
"""
from __future__ import annotations

REST_HR = 43     # mirrors js/profile.js / js/fit_profile.js
MAX_HR = 173     # mirrors js/profile.js / js/fit_profile.js
WEIGHT_KG = 66.0  # current rider weight (2026-07-04) -- js/fit_profile.js's 68 is now stale


def bin_by_minute(time_s: list, watts: list, heartrate: list) -> list[dict]:
    """Non-overlapping 60s bins: x = mean power in bin, y = HR of the LAST
    sample in the bin (not the average -- deliberate lag-reduction choice,
    since HR response lags a power change)."""
    if not time_s or not heartrate or not watts:
        return []
    bins = []
    total_time = time_s[-1]
    bin_start = 0
    while bin_start + 60 <= total_time:
        bin_end = bin_start + 60
        hr_vals, x_vals = [], []
        for i in range(len(time_s)):
            if bin_start <= time_s[i] < bin_end:
                if heartrate[i] is not None and heartrate[i] > 0:
                    hr_vals.append(heartrate[i])
                if watts[i] is not None and watts[i] > 0:
                    x_vals.append(watts[i])
        if hr_vals and x_vals:
            end_hr = hr_vals[-1]
            avg_x = sum(x_vals) / len(x_vals)
            if 40 <= end_hr <= 220 and avg_x > 0:
                bins.append({'x': avg_x, 'y': end_hr})
        bin_start += 60
    return bins


def linear_regression(pts: list[dict]) -> dict | None:
    """Free OLS fit: y = m*x + c. None if <3 points or zero x-variance."""
    n = len(pts)
    if n < 3:
        return None
    xm = sum(p['x'] for p in pts) / n
    ym = sum(p['y'] for p in pts) / n
    num = sum((p['x'] - xm) * (p['y'] - ym) for p in pts)
    den = sum((p['x'] - xm) ** 2 for p in pts)
    if den == 0:
        return None
    m = num / den
    c = ym - m * xm
    ss_tot = sum((p['y'] - ym) ** 2 for p in pts)
    ss_res = sum((p['y'] - (m * p['x'] + c)) ** 2 for p in pts)
    r2 = 0.0 if ss_tot == 0 else 1 - ss_res / ss_tot
    return {'m': m, 'c': c, 'r2': r2}


def linear_regression_fixed(pts: list[dict], c0: float) -> dict | None:
    """Constrained OLS: intercept fixed at c0, only the slope is fitted.
    m = sum(x*(y-c0)) / sum(x^2). Ref: en.wikipedia.org/wiki/Simple_linear_regression
    """
    if not pts:
        return None
    num = sum(p['x'] * (p['y'] - c0) for p in pts)
    den = sum(p['x'] ** 2 for p in pts)
    if den == 0:
        return None
    m = num / den
    n = len(pts)
    ym = sum(p['y'] for p in pts) / n
    ss_tot = sum((p['y'] - ym) ** 2 for p in pts)
    ss_res = sum((p['y'] - (m * p['x'] + c0)) ** 2 for p in pts)
    r2 = 0.0 if ss_tot == 0 else 1 - ss_res / ss_tot
    return {'m': m, 'c': c0, 'r2': r2}


def pct_hrr(avg_hr: float, rest_hr: float = REST_HR, max_hr: float = MAX_HR) -> float | None:
    """Heart rate reserve percentage: (HR - restHR) / (maxHR - restHR) * 100."""
    hrr_range = max_hr - rest_hr
    if hrr_range <= 0:
        return None
    return (avg_hr - rest_hr) / hrr_range * 100.0

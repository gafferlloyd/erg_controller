"""Build 1Hz power/HR arrays using MOVING time, not wall-clock elapsed time.

wprime_locus._to_1s_grid() indexes by elapsed-since-start, so a real device
pause (auto-pause at a stop, or manual pause) shows up as a NaN-filled gap
spanning the full paused duration -- which calc_wbal() then treats as 0W
"recovery" for that entire span. That's a DIFFERENT, deliberate convention
used elsewhere (wprime_aggregate.py's library-wide CP/W' fitting treats
"gap = coasting = recovery" as conservative for that purpose) -- but it's
wrong for reproducing what a live on-device datafield actually showed,
since a paused activity's compute() almost certainly doesn't tick during
the pause (frozen: no depletion, no recovery credited), and Garmin doesn't
even record samples during a pause in the first place.

This collapses gaps longer than gap_threshold_s entirely (as if the pause
never happened -- moving straight from the last pre-pause sample to the
first post-pause one), while still NaN-filling genuinely brief recording
blips (a dropped sample or two) the same way _to_1s_grid does.
"""
from __future__ import annotations
import numpy as np

DEFAULT_GAP_THRESHOLD_S = 5.0


def to_moving_time_1hz(elapsed: np.ndarray, raw_power: list, raw_hr: list,
                        gap_threshold_s: float = DEFAULT_GAP_THRESHOLD_S) -> tuple:
    """Returns (power_arr, hr_arr) indexed by moving seconds -- shorter than
    _to_1s_grid's output whenever the ride contains a pause longer than
    gap_threshold_s.
    """
    n = len(elapsed)
    if n == 0:
        return np.array([]), np.array([])

    power_out = [_as_float(raw_power[0])]
    hr_out = [_as_float(raw_hr[0])]

    for i in range(1, n):
        delta = elapsed[i] - elapsed[i - 1]
        if delta <= gap_threshold_s:
            for _ in range(max(0, int(round(delta)) - 1)):
                power_out.append(np.nan)
                hr_out.append(np.nan)
        # else: a real pause -- collapse it, insert nothing for the gap itself.
        power_out.append(_as_float(raw_power[i]))
        hr_out.append(_as_float(raw_hr[i]))

    return np.array(power_out), np.array(hr_out)


def _as_float(v) -> float:
    return np.nan if v is None else float(v)

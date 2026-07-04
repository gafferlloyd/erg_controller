"""Forward-fill 1Hz resampler, ported from resampleTo1Hz() in
~/strava-efficiency/content.js (line ~569).

Deliberately different from wprime_locus._to_1s_grid()'s NaN-gap convention:
this carries the last known value FORWARD into gaps (0 before the first
sample) rather than leaving gaps as NaN. Needed so the ported NP/power-curve/
efficiency functions produce the same numbers the browser extension would --
those computations were all designed against this forward-fill behaviour.
"""
from __future__ import annotations
import numpy as np


def resample_to_1hz(values: list, time_s: list) -> np.ndarray:
    """Step-function resample to 1 sample/sec, matching resampleTo1Hz() exactly.

    values may contain None (treated as 0, matching `stream[j] != null ? stream[j] : 0`).
    """
    n = len(time_s)
    if n == 0:
        return np.array([], dtype=float)
    total_secs = int(time_s[-1])
    out = np.zeros(total_secs + 1, dtype=float)
    j = 0
    for t in range(total_secs + 1):
        while j + 1 < n and time_s[j + 1] <= t:
            j += 1
        v = values[j]
        out[t] = 0.0 if v is None else float(v)
    return out

"""HR-gated interval detection.

Flags ride segments where HR stays at/above a threshold ("gate"), then
generates every contiguous combination of the resulting segments -- leaping
across whatever lies between them (slow spells, stop-start traffic, brief
recoveries) -- so back-to-back hard efforts can be evaluated either
individually or as a single combined physiological bout. For N base
segments this yields N*(N+1)/2 combined segments (N singles, N-1 pairs of
adjacent segments, ... down to 1 combination spanning all of them).

Reports Normalized Power per segment, not raw average power -- a combined
segment that leaps across a slow spell would otherwise look artificially
easy on a raw average.
"""
from __future__ import annotations
import numpy as np

from power_curve import normalized_power


def detect_gate_segments(hr_1hz: np.ndarray, hr_gate: float, min_dur_s: int = 60,
                          max_gap_s: int = 20) -> list[tuple[int, int]]:
    """Non-overlapping (start, end) index pairs (inclusive, 1Hz moving time)
    where HR stays at/above hr_gate, tolerating dips below it for up to
    max_gap_s before ending a segment, and dropping any segment shorter
    than min_dur_s once closed.
    """
    n = len(hr_1hz)
    above = np.where(np.isnan(hr_1hz), False, hr_1hz >= hr_gate)
    segments = []
    i = 0
    while i < n:
        if not above[i]:
            i += 1
            continue
        start = i
        last_above = i
        j = i
        while j < n:
            if above[j]:
                last_above = j
                j += 1
            elif j - last_above <= max_gap_s:
                j += 1
            else:
                break
        end = last_above
        if end - start + 1 >= min_dur_s:
            segments.append((start, end))
        i = j
    return segments


def combine_segments(segments: list[tuple[int, int]]) -> list[dict]:
    """Every contiguous run of 1..N base segments (in temporal order),
    spanning from the first segment's start to the last segment's end.
    """
    n = len(segments)
    combos = []
    for i in range(n):
        for j in range(i, n):
            combos.append({
                'segment_idx': (i, j),
                'n_segments': j - i + 1,
                'start': segments[i][0],
                'end': segments[j][1],
            })
    return combos


def analyze_segments(power_1hz: np.ndarray, hr_1hz: np.ndarray, combos: list[dict]) -> list[dict]:
    """Adds duration/NP/HR/power stats to each combo dict from combine_segments()."""
    results = []
    for c in combos:
        s, e = c['start'], c['end']
        p_slice = power_1hz[s:e + 1]
        h_slice = hr_1hz[s:e + 1]
        results.append({
            **c,
            'duration_s': e - s + 1,
            'avg_power': float(np.nanmean(p_slice)),
            'max_power': float(np.nanmax(p_slice)),
            'np': normalized_power(p_slice),
            'avg_hr': float(np.nanmean(h_slice)),
            'max_hr': float(np.nanmax(h_slice)),
        })
    return results


def gate_and_analyze(power_1hz: np.ndarray, hr_1hz: np.ndarray, hr_gate: float,
                      min_dur_s: int = 60, max_gap_s: int = 20) -> list[dict]:
    """Convenience wrapper: detect -> combine -> analyze in one call."""
    segments = detect_gate_segments(hr_1hz, hr_gate, min_dur_s, max_gap_s)
    combos = combine_segments(segments)
    return analyze_segments(power_1hz, hr_1hz, combos)

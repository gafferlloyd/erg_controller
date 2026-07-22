import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from hr_gate_intervals import detect_gate_segments, combine_segments, analyze_segments, gate_and_analyze


def test_detect_gate_segments_basic():
    hr = np.array([100.0] * 10 + [150.0] * 70 + [100.0] * 25 + [150.0] * 70)
    segs = detect_gate_segments(hr, hr_gate=140, min_dur_s=60, max_gap_s=20)
    assert len(segs) == 2, segs
    assert segs[0] == (10, 79), segs[0]
    assert segs[1] == (105, 174), segs[1]
    print('  test_detect_gate_segments_basic PASS')


def test_detect_gate_segments_gap_tolerance():
    # Two 70s above-gate blocks separated by a 10s dip -- within max_gap_s=20,
    # so should merge into a single segment.
    hr = np.array([150.0] * 70 + [100.0] * 10 + [150.0] * 70)
    segs = detect_gate_segments(hr, hr_gate=140, min_dur_s=60, max_gap_s=20)
    assert len(segs) == 1, segs
    assert segs[0] == (0, 149), segs[0]
    print('  test_detect_gate_segments_gap_tolerance PASS')


def test_detect_gate_segments_gap_too_long_splits():
    # Same as above but the dip is 30s -- longer than max_gap_s=20, so it
    # should split into two separate segments.
    hr = np.array([150.0] * 70 + [100.0] * 30 + [150.0] * 70)
    segs = detect_gate_segments(hr, hr_gate=140, min_dur_s=60, max_gap_s=20)
    assert len(segs) == 2, segs
    print('  test_detect_gate_segments_gap_too_long_splits PASS')


def test_detect_gate_segments_min_duration_drops_blip():
    hr = np.array([100.0] * 50 + [150.0] * 30 + [100.0] * 50)
    segs = detect_gate_segments(hr, hr_gate=140, min_dur_s=60, max_gap_s=5)
    assert segs == [], segs
    print('  test_detect_gate_segments_min_duration_drops_blip PASS')


def test_detect_gate_segments_nan_treated_as_below_gate():
    hr = np.array([150.0] * 60 + [np.nan] * 10 + [150.0] * 60)
    segs = detect_gate_segments(hr, hr_gate=140, min_dur_s=60, max_gap_s=20)
    assert len(segs) == 1, segs
    print('  test_detect_gate_segments_nan_treated_as_below_gate PASS')


def test_combine_segments_count_matches_triangular_number():
    segments = [(i * 100, i * 100 + 50) for i in range(7)]
    combos = combine_segments(segments)
    assert len(combos) == 7 * 8 // 2 == 28, len(combos)
    singles = [c for c in combos if c['n_segments'] == 1]
    assert len(singles) == 7
    full_span = [c for c in combos if c['n_segments'] == 7][0]
    assert full_span['start'] == segments[0][0]
    assert full_span['end'] == segments[-1][1]
    print('  test_combine_segments_count_matches_triangular_number PASS')


def test_combine_segments_single_segment():
    combos = combine_segments([(5, 20)])
    assert combos == [{'segment_idx': (0, 0), 'n_segments': 1, 'start': 5, 'end': 20}]
    print('  test_combine_segments_single_segment PASS')


def test_analyze_segments_reports_np_and_hr():
    n = 100
    power = np.full(n, 250.0)
    hr = np.full(n, 150.0)
    combos = combine_segments([(0, n - 1)])
    results = analyze_segments(power, hr, combos)
    assert len(results) == 1
    r = results[0]
    assert r['duration_s'] == n
    assert abs(r['avg_power'] - 250.0) < 1e-6
    assert r['np'] is not None
    assert abs(r['np'] - 250.0) < 1e-6
    assert abs(r['avg_hr'] - 150.0) < 1e-6
    print('  test_analyze_segments_reports_np_and_hr PASS')


def test_gate_and_analyze_end_to_end():
    hr = np.array([100.0] * 10 + [150.0] * 70 + [100.0] * 25 + [150.0] * 70)
    power = np.where(hr >= 140, 250.0, 150.0)
    results = gate_and_analyze(power, hr, hr_gate=140, min_dur_s=60, max_gap_s=20)
    assert len(results) == 3  # 2 singles + 1 combined (leaping the gap)
    combined = [r for r in results if r['n_segments'] == 2][0]
    assert combined['start'] == 10
    assert combined['end'] == 174
    print('  test_gate_and_analyze_end_to_end PASS')


if __name__ == '__main__':
    test_detect_gate_segments_basic()
    test_detect_gate_segments_gap_tolerance()
    test_detect_gate_segments_gap_too_long_splits()
    test_detect_gate_segments_min_duration_drops_blip()
    test_detect_gate_segments_nan_treated_as_below_gate()
    test_combine_segments_count_matches_triangular_number()
    test_combine_segments_single_segment()
    test_analyze_segments_reports_np_and_hr()
    test_gate_and_analyze_end_to_end()
    print('All tests passed.')

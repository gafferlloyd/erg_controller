"""Mean-maximal-power (best efforts) curve for a single .fit file.

For each standard duration, finds the best sustained average power anywhere
in the ride (rolling window via cumulative sum, O(n) per duration), plus
when it happened and the HR during it. Useful for characterizing exactly
how hard a specific effort was — e.g. to check a claim like "pushed harder
than recent times" against the actual numbers, or to spot a genuinely
maximal effort worth feeding into the CP/W' calibration
(see docs/wprime_calibration.md).

Usage:
    python3 best_efforts.py <fitfile>
    python3 best_efforts.py <fitfile> --around 16:23   # zoom into a window
"""
import argparse
from pathlib import Path

import numpy as np

from wprime_locus import parse_fit_records, _to_1s_grid

DURATIONS_S = [5, 15, 30, 60, 120, 180, 300, 600, 1200, 1800, 3600]


def _fmt_mmss(seconds: int) -> str:
    return f'{seconds // 60}:{seconds % 60:02d}'


def best_effort(power: np.ndarray, hr: np.ndarray, window: int):
    """Best rolling-average power for `window` seconds. Returns (avg_p, start_idx, avg_hr) or None."""
    n = len(power)
    if window > n:
        return None
    p_filled = np.where(np.isnan(power), 0.0, power)
    cum = np.concatenate(([0.0], np.cumsum(p_filled)))
    sums = cum[window:] - cum[:-window]
    start = int(np.argmax(sums))
    avg_p = sums[start] / window
    hr_win = hr[start:start + window]
    avg_hr = float(np.nanmean(hr_win)) if not np.all(np.isnan(hr_win)) else None
    return avg_p, start, avg_hr


def show_curve(path: Path):
    result = parse_fit_records(path)
    if result is None:
        print(f'No usable data in {path}')
        return None
    elapsed, raw_p, raw_h, _meta = result
    p, h = _to_1s_grid(elapsed, raw_p, raw_h)
    n = len(p)

    print(f'{path.name}  ({_fmt_mmss(n)} total)\n')
    print(f'{"Duration":>10}  {"Best avg":>9}  {"Starts at":>10}  {"Avg HR":>7}')
    for w in DURATIONS_S:
        result = best_effort(p, h, w)
        if result is None:
            continue
        avg_p, start, avg_hr = result
        hr_str = f'{avg_hr:.0f}bpm' if avg_hr is not None else '  n/a'
        label = f'{w}s' if w < 60 else f'{w // 60}min'
        print(f'{label:>10}  {avg_p:>7.0f}W  {_fmt_mmss(start):>10}  {hr_str:>7}')
    return p, h


def zoom(p: np.ndarray, h: np.ndarray, center_s: int, pad: int = 300):
    n = len(p)
    lo, hi = max(0, center_s - pad), min(n, center_s + pad)
    print(f'\nWindow {_fmt_mmss(lo)} - {_fmt_mmss(hi)} (+/-{pad}s around {_fmt_mmss(center_s)}):')
    seg_p = p[lo:hi]
    seg_h = h[lo:hi]
    valid_p = seg_p[~np.isnan(seg_p)]
    if len(valid_p):
        print(f'  avg {valid_p.mean():.0f}W  max {valid_p.max():.0f}W')
    if not np.all(np.isnan(seg_h)):
        print(f'  avg HR {np.nanmean(seg_h):.0f}bpm  max HR {np.nanmax(seg_h):.0f}bpm')
    # 30s-resolution power trace through the window
    print('  30s power trace:', ' '.join(
        f'{np.nanmean(seg_p[i:i+30]):.0f}' if not np.all(np.isnan(seg_p[i:i+30])) else '--'
        for i in range(0, len(seg_p), 30)
    ))


def _parse_mmss(s: str) -> int:
    if ':' in s:
        m, sec = s.split(':')
        return int(m) * 60 + int(sec)
    return int(s)


def _cli():
    ap = argparse.ArgumentParser(description='Mean-maximal-power curve for a .fit file')
    ap.add_argument('fit')
    ap.add_argument('--around', help='Zoom into a MM:SS (or seconds) window, +/-300s by default')
    ap.add_argument('--pad', type=int, default=300)
    args = ap.parse_args()

    p, h = show_curve(Path(args.fit))
    if args.around and p is not None:
        zoom(p, h, _parse_mmss(args.around), args.pad)


if __name__ == '__main__':
    _cli()

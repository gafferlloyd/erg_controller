"""Replay a .fit file through the exact live W'bal model (js/wbal.js) against
a candidate CP/W' pair, to check what the app would have shown in real time.

Unlike wprime_locus.py's uncapped feasibility-locus method (used for fitting
CP/W' across many rides), this runs the same CAPPED Skiba differential model
the live pacing tool uses (recovery time constant, clamped to [0, W']) — so
it reproduces exactly what a rider saw on screen during a specific ride, and
can confirm/quantify moments where the model's behaviour looks wrong (e.g.
W'bal hitting zero while power well above CP is still sustained easily,
which points at CP and/or W' being set too low).

Uses moving time (moving_time.to_moving_time_1hz), not wall-clock elapsed
time -- a real device pause must not grant free W'bal recovery the live
on-device datafield never actually credited (it doesn't tick during a pause).

Usage:
    python3 wbal_review.py <fitfile> [--cp 277] [--wprime 21000]
"""
import argparse
from pathlib import Path

import numpy as np

from wprime_locus import parse_fit_records
from moving_time import to_moving_time_1hz


def calc_wbal(power: np.ndarray, cp: float, wprime: float) -> np.ndarray:
    """Port of calcWbal() in js/wbal.js — capped Skiba differential model.

    Gaps (NaN) are treated as 0W, matching wprime_locus.py's convention.
    """
    wbal = np.empty(len(power))
    w = wprime
    for i in range(len(power)):
        p = power[i]
        p = 0.0 if np.isnan(p) else float(p)
        if p >= cp:
            w -= (p - cp)
        else:
            dcp = cp - p
            tau = 546.0 * np.exp(-0.01 * dcp) + 316.0
            w = wprime - (wprime - w) * np.exp(-1.0 / tau)
        w = max(0.0, min(wprime, w))
        wbal[i] = w
    return wbal


def _fmt_mmss(seconds: int) -> str:
    return f'{seconds // 60}:{seconds % 60:02d}'


def review(path: Path, cp: float, wprime: float) -> None:
    result = parse_fit_records(path)
    if result is None:
        print(f'No usable data in {path}')
        return
    elapsed, raw_p, raw_h, _meta = result
    # Moving time, not wall-clock elapsed -- a real pause must not grant free
    # W'bal recovery the live on-device datafield never actually credited.
    p, h = to_moving_time_1hz(elapsed, raw_p, raw_h)

    wbal = calc_wbal(p, cp, wprime)
    n = len(wbal)

    print(f'{path.name}')
    print(f"Duration: {_fmt_mmss(n)}   CP={cp:.0f}W  W'={wprime:.0f}J\n")

    tmin = int(np.argmin(wbal))
    window = slice(max(0, tmin - 60), min(n, tmin + 61))
    win_p = p[window]
    win_h = h[window]
    print(f"Lowest W'bal point: {_fmt_mmss(tmin)} moving time, {wbal[tmin]:.0f}J "
          f"({wbal[tmin]/wprime*100:.0f}% of W').")
    if not np.all(np.isnan(win_p)):
        print(f'  Power in +/-60s window around it: avg {np.nanmean(win_p):.0f}W  max {np.nanmax(win_p):.0f}W')
    if not np.all(np.isnan(win_h)):
        print(f'  HR in +/-60s window around it   : avg {np.nanmean(win_h):.0f}bpm  max {np.nanmax(win_h):.0f}bpm')

    zero_idxs = np.where(wbal <= 0)[0]
    if len(zero_idxs) == 0:
        print(f"\nW'bal never reached zero (min = {wbal.min():.0f}J = {wbal.min()/1000:.1f}kJ "
              f"= {wbal.min()/wprime*100:.0f}% floor).")
    else:
        t0 = zero_idxs[0]
        print(f"W'bal first hit zero at {_fmt_mmss(t0)} moving time.")

        after_p = p[t0:]
        after_h = h[t0:]
        valid_p = after_p[~np.isnan(after_p)]
        above_cp = valid_p[valid_p > cp]
        remaining = n - t0
        print(f'\nAfter that point ({_fmt_mmss(remaining)} remaining in the ride):')
        print(f'  Time spent >CP  : {_fmt_mmss(len(above_cp))} '
              f'({len(above_cp) / max(len(valid_p), 1) * 100:.0f}% of remaining moving time)')
        if len(above_cp):
            print(f'  Avg power >CP   : {above_cp.mean():.0f}W   Max: {above_cp.max():.0f}W')
        if not np.all(np.isnan(after_h)):
            print(f'  Avg HR          : {np.nanmean(after_h):.0f}bpm   Max: {np.nanmax(after_h):.0f}bpm')
        print(f'  Time at W\'bal=0 : {_fmt_mmss(int(np.sum(wbal[t0:] <= 0)))} '
              '(model says "no anaerobic capacity" for this long)')

    valid_all = p[~np.isnan(p)]
    print(f'\nWhole ride: avg {valid_all.mean():.0f}W  max {valid_all.max():.0f}W', end='')
    if not np.all(np.isnan(h)):
        print(f'  max HR {np.nanmax(h):.0f}bpm', end='')
    print(f'  ({n // 60}min)')


def _cli():
    ap = argparse.ArgumentParser(description="Replay a .fit file through the live W'bal model")
    ap.add_argument('fit')
    ap.add_argument('--cp', type=float, default=277)
    ap.add_argument('--wprime', type=float, default=21000)
    args = ap.parse_args()
    review(Path(args.fit), args.cp, args.wprime)


if __name__ == '__main__':
    _cli()

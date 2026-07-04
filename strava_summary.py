"""Assemble the Signal message text for one ride from its Strava streams.

Plain text, no markdown (this is a Signal message, not a Strava description --
no append/preserve-existing-text concerns either, it's a fresh message).
"""
from __future__ import annotations
import numpy as np

from wbal_review import calc_wbal
from cp_solver import solve_cp_for_wprime
from strava_resample import resample_to_1hz
from power_curve import best_power_by_minute, be_ftp_model, pinot_grappe_model, apply_ftp_model, power_curve_window
from hr_efficiency import bin_by_minute, linear_regression_fixed, pct_hrr, REST_HR, MAX_HR


def _stream_data(streams: dict, key: str) -> list:
    entry = streams.get(key)
    return entry.get('data', []) if entry else []


def _cp_check_line(power_1hz: np.ndarray, cp: float, wprime: float) -> str:
    wbal = calc_wbal(power_1hz, cp, wprime)
    floor_j = float(wbal.min())
    floor_pct = floor_j / wprime * 100
    verdict = 'cleared' if floor_j > 0 else 'HIT ZERO'
    return f"CP/W' check @ {cp:.0f}W/{wprime/1000:.1f}kJ: floor {floor_pct:.0f}% ({floor_j/1000:.1f}kJ) -- {verdict}"


def _solved_cp_line(power_1hz: np.ndarray, wprime: float) -> str:
    result = solve_cp_for_wprime(power_1hz, wprime)
    if result['status'] == 'ok':
        return f"Solved CP @ W'={wprime/1000:.0f}kJ: {result['cp']:.0f}W"
    if result['status'] == 'ride_too_easy':
        return f"Solved CP @ W'={wprime/1000:.0f}kJ: ride not hard enough to solve"
    return f"Solved CP @ W'={wprime/1000:.0f}kJ: ride harder than the search range"


def _ftp_model_lines(power_1hz: np.ndarray) -> list[str]:
    best_powers = best_power_by_minute(power_1hz)
    if not best_powers:
        return ['BE-FTP est.: n/a (ride too short)', 'Pinot-Grappe FTP est.: n/a (ride too short)']
    longest = max(best_powers, key=lambda bp: bp['t_min'])
    lines = []
    for label, model_fn in (('BE-FTP', be_ftp_model), ('Pinot-Grappe FTP', lambda: pinot_grappe_model())):
        model = model_fn()
        applied = apply_ftp_model([longest], model)
        if applied:
            lines.append(f"{label} est.: {applied[0]['ftp_est']:.0f}W (from best {longest['t_min']}min)")
        else:
            lines.append(f'{label} est.: n/a')
    return lines


def _window_line(power_1hz: np.ndarray, hr_1hz: np.ndarray, window_s: int, label: str,
                  weight_kg: float | None, ride_min: int) -> str:
    result = power_curve_window(power_1hz, hr_1hz, window_s)
    if result is None:
        return f'{label}: n/a (ride is {ride_min}min)'
    parts = [f"NP {result['np']:.0f}W" if result['np'] is not None else 'NP n/a']
    if result['hr'] is not None:
        parts.append(f"HR {result['hr']:.0f}bpm")
        hrr = pct_hrr(result['hr'])
        if hrr is not None:
            parts.append(f'{hrr:.0f}% HRR')
    if weight_kg and result['np'] is not None:
        parts.append(f"{result['np']/weight_kg:.1f} W/kg")
    return f"{label}: {', '.join(parts)}"


def _efficiency_line(time_s: list, watts: list, heartrate: list, hrr_fraction: float = 0.20) -> str:
    bins = bin_by_minute(time_s, watts, heartrate)
    if len(bins) < 3:
        return f'Efficiency: insufficient HR data (need >=3 one-minute bins, got {len(bins)})'
    c0 = REST_HR + hrr_fraction * (MAX_HR - REST_HR)
    reg = linear_regression_fixed(bins, c0)
    if reg is None or reg['m'] == 0:
        return 'Efficiency: could not fit (no power variance in the bins)'
    return (f"Efficiency ({hrr_fraction*100:.0f}%HRR-fixed fit, n={len(bins)} bins, "
            f"R^2={reg['r2']:.2f}): {1/reg['m']:.2f} W/bpm")


def build_summary(activity: dict, streams: dict, weight_kg: float | None,
                   cp: float = 277.0, wprime: float = 21000.0,
                   solve_wprimes: tuple = (15000.0, 25000.0)) -> str:
    time_s = _stream_data(streams, 'time')
    watts = _stream_data(streams, 'watts')
    heartrate = _stream_data(streams, 'heartrate')

    power_1hz = resample_to_1hz(watts, time_s)
    hr_1hz = resample_to_1hz(heartrate, time_s)
    ride_min = len(power_1hz) // 60

    name = activity.get('name', 'Ride')
    date = (activity.get('start_date_local') or '')[:10]

    lines = [f'Ride: {name}, {date}', _cp_check_line(power_1hz, cp, wprime)]
    lines += [_solved_cp_line(power_1hz, wp) for wp in solve_wprimes]
    lines += _ftp_model_lines(power_1hz)
    lines.append(_window_line(power_1hz, hr_1hz, 1200, '20min', weight_kg, ride_min))
    lines.append(_window_line(power_1hz, hr_1hz, 3600, '60min', weight_kg, ride_min))
    lines.append(_efficiency_line(time_s, watts, heartrate))

    return '\n'.join(lines)

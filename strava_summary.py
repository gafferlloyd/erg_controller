"""Assemble the Signal message text for one ride, from arrays already
extracted from its .fit file (source-agnostic -- doesn't care whether the
.fit came from intervals.icu, a local archive, or anywhere else).

Plain text, no markdown. This is meant to be copy-pasted by hand into the
ride's Strava description, not written there automatically.
"""
from __future__ import annotations
import numpy as np

from wbal_review import calc_wbal
from cp_solver import solve_cp_for_wprime
from power_curve import best_power_by_minute, be_ftp_model, pinot_grappe_model, apply_ftp_model, power_curve_window
from hr_efficiency import bin_by_minute, linear_regression_fixed, pct_hrr, REST_HR, MAX_HR, WEIGHT_KG


def _wkg_str(watts: float, weight_kg: float | None) -> str:
    return f' ({watts/weight_kg:.1f} W/kg)' if weight_kg else ''


def _cp_check_line(power_1hz: np.ndarray, cp: float, wprime: float, weight_kg: float | None) -> str:
    wbal = calc_wbal(power_1hz, cp, wprime)
    floor_j = float(wbal.min())
    floor_pct = floor_j / wprime * 100
    verdict = 'cleared' if floor_j > 0 else 'HIT ZERO'
    return (f"\U0001F50B CP/W' check @ {cp:.0f}W/{wprime/1000:.1f}kJ{_wkg_str(cp, weight_kg)}: "
            f"floor {floor_pct:.0f}% ({floor_j/1000:.1f}kJ) -- {verdict}")


def _solved_cp_line(power_1hz: np.ndarray, wprime: float, weight_kg: float | None) -> str:
    result = solve_cp_for_wprime(power_1hz, wprime)
    if result['status'] == 'ok':
        return f"\U0001F3AF Solved CP @ W'={wprime/1000:.0f}kJ: {result['cp']:.0f}W{_wkg_str(result['cp'], weight_kg)}"
    if result['status'] == 'ride_too_easy':
        return f"\U0001F3AF Solved CP @ W'={wprime/1000:.0f}kJ: ride not hard enough to solve"
    return f"\U0001F3AF Solved CP @ W'={wprime/1000:.0f}kJ: ride harder than the search range"


def _ftp_model_lines(power_1hz: np.ndarray, hr_1hz: np.ndarray, weight_kg: float | None) -> list[str]:
    best_powers = best_power_by_minute(power_1hz)
    if not best_powers:
        return ['\U0001F4CA BE-FTP est.: n/a (ride too short)',
                 '\U0001F4CA Pinot-Grappe FTP est.: n/a (ride too short)']
    longest = max(best_powers, key=lambda bp: bp['t_min'])

    # Same window as `longest`, re-run with real HR this time (best_power_by_minute
    # only tracks average power) to get its NP and HR for that specific window.
    window = power_curve_window(power_1hz, hr_1hz, longest['t_min'] * 60)
    hrr_str = ''
    if window is not None and window['hr'] is not None:
        hrr = pct_hrr(window['hr'])
        if hrr is not None:
            hrr_str = f' @ {hrr:.0f}% HRR'

    # Feed NP (not plain average power) into the FTP models -- NP better represents
    # the metabolic cost of a variable-intensity outdoor effort, which matters most
    # for longer windows (a real 60min ride segment is rarely a clean, steady effort).
    if window is not None and window['np'] is not None:
        power_for_model = {'t_min': longest['t_min'], 'power': window['np']}
    else:
        power_for_model = longest

    lines = []
    for label, model_fn in (('BE-FTP', be_ftp_model), ('Pinot-Grappe FTP', lambda: pinot_grappe_model())):
        model = model_fn()
        applied = apply_ftp_model([power_for_model], model)
        if applied:
            ftp_est = applied[0]['ftp_est']
            lines.append(f"\U0001F4CA {label} est.: {ftp_est:.0f}W{_wkg_str(ftp_est, weight_kg)} "
                          f"(from best {longest['t_min']}min{hrr_str})")
        else:
            lines.append(f'\U0001F4CA {label} est.: n/a')
    return lines


def _window_line(power_1hz: np.ndarray, hr_1hz: np.ndarray, window_s: int, label: str,
                  weight_kg: float | None, ride_min: int) -> str:
    result = power_curve_window(power_1hz, hr_1hz, window_s)
    if result is None:
        return f'⏱️ {label}: n/a (ride is {ride_min}min)'
    parts = [f"NP {result['np']:.0f}W" if result['np'] is not None else 'NP n/a']
    if result['hr'] is not None:
        parts.append(f"HR {result['hr']:.0f}bpm")
        hrr = pct_hrr(result['hr'])
        if hrr is not None:
            parts.append(f'{hrr:.0f}% HRR')
    if weight_kg and result['np'] is not None:
        parts.append(f"{result['np']/weight_kg:.1f} W/kg")
    return f"⏱️ {label}: {', '.join(parts)}"


def _efficiency_line(time_s: list, watts: list, heartrate: list, hrr_fraction: float = 0.20) -> str:
    bins = bin_by_minute(time_s, watts, heartrate)
    if len(bins) < 3:
        return f'⚙️ Efficiency: insufficient HR data (need >=3 one-minute bins, got {len(bins)})'
    c0 = REST_HR + hrr_fraction * (MAX_HR - REST_HR)
    reg = linear_regression_fixed(bins, c0)
    if reg is None or reg['m'] == 0:
        return '⚙️ Efficiency: could not fit (no power variance in the bins)'
    return f"⚙️ Efficiency: {1/reg['m']:.2f} W/bpm"


def build_summary(activity: dict, power_1hz: np.ndarray, hr_1hz: np.ndarray,
                   time_s: list, watts_raw: list, heartrate_raw: list,
                   weight_kg: float | None = None,
                   cp: float = 277.0, wprime: float = 21000.0,
                   solve_wprimes: tuple = (15000.0, 25000.0)) -> str:
    if weight_kg is None:
        weight_kg = WEIGHT_KG
    ride_min = len(power_1hz) // 60

    name = activity.get('name', 'Ride')
    date = (activity.get('start_date_local') or '')[:10]

    lines = [_cp_check_line(power_1hz, cp, wprime, weight_kg)]
    lines += [_solved_cp_line(power_1hz, wp, weight_kg) for wp in solve_wprimes]
    lines += _ftp_model_lines(power_1hz, hr_1hz, weight_kg)
    lines.append(_window_line(power_1hz, hr_1hz, 1200, '20min', weight_kg, ride_min))
    lines.append(_window_line(power_1hz, hr_1hz, 3600, '60min', weight_kg, ride_min))
    lines.append(_efficiency_line(time_s, watts_raw, heartrate_raw))
    lines.append(f'\U0001F6B4 Ride: {name}, {date}')

    return '\n'.join(lines)

"""Assemble the Signal message text for one run -- compact, emoji-led,
minimum repeated text. Redesigned 2026-07-27 from an earlier verbose,
label-per-line format at the user's explicit request.

Icon legend (kept here for reference, not repeated in the message itself):
  no icon   pace (min'sec per km, unit never repeated)
  ❤️        heart-rate reserve %, for today's own split
  🏅        age-grade %, for today's own split
  🥇🥈🥉    season rank 1st-3rd; 🏁Nth for 4th and beyond
  🌟🎂👑    season best / age-bracket PB / all-time PB (same trio reused
            for the VO2 line's SB/M55-PB/PB, one consistent meaning)
  ≤         prefix on a 🌟/🎂/👑 pace value: mathematically inferred from a
            longer distance's better-measured effort at the same source
            activity, not a direct split at this distance -- a shorter
            distance can never have a slower true best than a longer one
            contains, so an apparent violation gets corrected by borrowing
            the longer entry's value (see running_pb_query.monotonic_best_by_label)
  🫁        Garmin VO2max reported today
  🎽        half-marathon-or-longer count this calendar year
  🗓️        mileage: this month · this year -- the month figure is tagged
            with the zodiac sign occupying the majority of days in the
            current calendar month (fixed per month, not date-computed --
            e.g. August is majority-Leo, Jul23-Aug22 > Aug23-31), the year
            figure with 年 (Chinese/Japanese "year"), replacing the earlier
            "/mo"/"/yr" text suffixes
  ⏳        days-to-reach-cumulative-km-milestone (⏳...∞ = not reached yet)
  🏃        activity tag (name, date, distance) -- always last, mirrors
            cycling's trailing 🚴 tag line; also reused, prefixed by a
            keycap-digit distance, on an optional landmark line (see below)

Per-split lines are still OMITTED (not "n/a") for distances today's run
didn't reach -- unchanged from the original design.

Landmark line(s), added 2026-08-13: whenever TODAY'S OWN run tips the
month or year total over a 100km tier (e.g. 73.7km -> 100.4km), a line
like "1️⃣0️⃣0️⃣🏃km in ♌" (month, zodiac-tagged like 🗓️) or
"1️⃣'6️⃣0️⃣0️⃣🏃km in '2️⃣6️⃣" (year, keycap 2-digit year) is prepended
as the FIRST line(s) of the message -- both can fire in the same run.
Silent otherwise (no "not yet" line). See _landmark_lines().
"""
from __future__ import annotations

from age_category import age_bracket_label, exact_age
from age_grade import age_grade_pct
from hr_efficiency import pct_hrr
from running_constants import SPLIT_DISTANCES, HM_MIN_DISTANCE_M, CUMULATIVE_MILESTONES_KM
from running_pb_query import best_in_scope, rank_in_scope, monotonic_best_by_label
from running_stats import km_in_range, days_for_cumulative_km, hm_count_current_year

_SPLIT_TARGET_M = dict(SPLIT_DISTANCES)
_RANK_EMOJI = {1: '🥇', 2: '🥈', 3: '🥉'}


def _format_pace(s_per_km: float) -> str:
    """Floors rather than rounds -- a pace fractionally under a whole-second
    boundary must never display as if it reached that boundary. Found
    2026-07-27: a genuinely sub-40min 10k (239.55s/km) was rounding up to
    display as exactly "4'00", which reads as 40:00-or-slower rather than
    the sub-40 result it actually was. round() can push a value across a
    boundary the true number never crossed; floor never can."""
    total = int(s_per_km)  # truncates toward zero; s_per_km is always >= 0 here
    return f"{total // 60}'{total % 60:02d}"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


def _rank_tag(rank: int) -> str:
    return _RANK_EMOJI.get(rank, f'🏁{_ordinal(rank)}')


def _pace_with_tag(entry: dict | None) -> str:
    """A manually-entered measured-course race result (running_manual_entries.py)
    carries a short display_tag so it reads distinctly wherever it wins a
    comparison -- pace_curve's GPS-distance search could never have found it.
    A monotonic_best_by_label()-bounded entry gets a leading '≤' instead --
    it's a mathematically inferred bound, not a directly-measured split."""
    if entry is None:
        return '—'
    pace_str = _format_pace(entry['pace_s_per_km'])
    if entry.get('bound'):
        pace_str = f'≤{pace_str}'
    tag = entry.get('display_tag')
    return f'{pace_str} {tag}' if tag else pace_str


def _split_line(label: str, today_entry: dict, entries_for_d: list[dict],
                 sb: dict | None, m_pb: dict | None, pb: dict | None,
                 year: int, age: int) -> str:
    pace = today_entry['pace_s_per_km']
    rank = rank_in_scope(entries_for_d, 'pace_s_per_km', better_is_higher=False,
                          target_value=pace, year=year)

    avg_hr = today_entry.get('avg_hr')
    hrr = pct_hrr(avg_hr) if avg_hr is not None else None
    hrr_str = f'❤️{hrr:.0f}%' if hrr is not None else '❤️—'

    ag = age_grade_pct(today_entry['elapsed_s'], _SPLIT_TARGET_M[label] / 1000.0, age)
    ag_str = f'🏅{ag:.0f}%' if ag is not None else '🏅—'

    return (f"{label} {_format_pace(pace)} {hrr_str} {ag_str} {_rank_tag(rank)} "
            f"(🌟{_pace_with_tag(sb)} 🎂{_pace_with_tag(m_pb)} 👑{_pace_with_tag(pb)})")


def _vo2_line(vo2_reported: float | None, vo2_history: list[dict], year: int, age_bracket: str) -> str:
    if vo2_reported is None:
        return '🫁—'
    sb = best_in_scope(vo2_history, 'value', better_is_higher=True, year=year)
    m_pb = best_in_scope(vo2_history, 'value', better_is_higher=True, age_bracket=age_bracket)
    pb = best_in_scope(vo2_history, 'value', better_is_higher=True)
    sb_str = f"{sb['value']:.1f}" if sb else '—'
    m_pb_str = f"{m_pb['value']:.1f}" if m_pb else '—'
    pb_str = f"{pb['value']:.1f}" if pb else '—'
    return f"🫁{vo2_reported:.1f} (🌟{sb_str} 🎂{m_pb_str} 👑{pb_str})"


def _hm_count_line(count: int) -> str:
    return f'🎽{count} HMs'


# Fixed per calendar month, not date-computed -- the sign occupying the
# majority of days never changes year to year (a leap-year February still
# splits 18/10-11 in Aquarius's favor either way).
_MONTH_ZODIAC = {1: '♑', 2: '♒', 3: '♓', 4: '♈', 5: '♉', 6: '♊',
                 7: '♋', 8: '♌', 9: '♍', 10: '♎', 11: '♏', 12: '♐'}

_KEYCAP_DIGITS = {'0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣',
                  '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'}


def _keycap(text: str) -> str:
    """Digits -> keycap emoji, everything else (the ' thousands separator) passed through."""
    return ''.join(_KEYCAP_DIGITS.get(ch, ch) for ch in text)


def _keycap_number(n: int) -> str:
    return _keycap(f'{n:,}'.replace(',', "'"))


def _landmark_lines(km_month_before: float, km_month_after: float, month: int,
                     km_year_before: float, km_year_after: float, year: int) -> list[str]:
    """One line per 100km tier crossed BY today's own run -- month tier tagged
    with the zodiac sign (matches _mileage_line's convention), year tier
    tagged with the keycap 2-digit year. Only the highest tier crossed is
    reported if a single run somehow spans more than one (a real edge case
    for an ultra, never for this rider's actual mileage, but cheap to handle
    correctly rather than assume away)."""
    lines = []
    month_tier_before, month_tier_after = int(km_month_before) // 100, int(km_month_after) // 100
    if month_tier_after > month_tier_before:
        lines.append(f'{_keycap_number(month_tier_after * 100)}🏃km in {_MONTH_ZODIAC[month]}')
    year_tier_before, year_tier_after = int(km_year_before) // 100, int(km_year_after) // 100
    if year_tier_after > year_tier_before:
        lines.append(f"{_keycap_number(year_tier_after * 100)}🏃km in '{_keycap(f'{year % 100:02d}')}")
    return lines


def _mileage_line(km_month: float, km_year: float, month: int) -> str:
    return f'🗓️{km_month:.0f}km{_MONTH_ZODIAC[month]} · {km_year:.0f}km年'


def _cumulative_days_line(results: dict) -> str:
    parts = []
    for milestone_km, days in results.items():
        label = f"{int(milestone_km):,}".replace(',', "'")
        parts.append(f"{label}:{days}d" if days is not None else f"{label}:∞")
    return '⏳' + ' '.join(parts)


def _activity_tag(activity_name: str, activity_date: str, activity_distance_m: float | None) -> str:
    dist = f" · {activity_distance_m / 1000.0:.1f}km" if activity_distance_m else ''
    return f'🏃 {activity_name}, {activity_date}{dist}'


def build_summary(activity_date: str, today_splits: dict, vo2_reported: float | None,
                   activities: list[dict], splits_index: dict, vo2_history: list[dict],
                   birth_year: int, activity_name: str = 'Run',
                   activity_distance_m: float | None = None) -> str:
    year = int(activity_date[:4])
    age_bracket = age_bracket_label(year, birth_year)
    age = exact_age(year, birth_year)

    # Computed once over the FULL distance list (not just today's labels) so
    # a bound can be borrowed from a longer distance even when today's run
    # didn't itself reach that far -- see monotonic_best_by_label.
    labels_ascending = [label for label, _ in SPLIT_DISTANCES]
    sb_by_label = monotonic_best_by_label(splits_index, labels_ascending, 'pace_s_per_km', False, year=year)
    m_pb_by_label = monotonic_best_by_label(splits_index, labels_ascending, 'pace_s_per_km', False,
                                             age_bracket=age_bracket)
    pb_by_label = monotonic_best_by_label(splits_index, labels_ascending, 'pace_s_per_km', False)

    month = int(activity_date[5:7])
    month_start = activity_date[:8] + '01'
    year_start = f'{year}-01-01'
    km_month = km_in_range(activities, month_start, activity_date)
    km_year = km_in_range(activities, year_start, activity_date)
    # "Before" = after minus today's own contribution, not yesterday's total --
    # correct even on a double-run day, since it only backs out THIS run.
    today_km = (activity_distance_m or 0.0) / 1000.0

    lines = _landmark_lines(km_month - today_km, km_month, month, km_year - today_km, km_year, year)
    for label, _ in SPLIT_DISTANCES:
        if label in today_splits:
            entries_for_d = splits_index.get(label, [])
            lines.append(_split_line(label, today_splits[label], entries_for_d,
                                      sb_by_label[label], m_pb_by_label[label], pb_by_label[label],
                                      year, age))

    lines.append(_vo2_line(vo2_reported, vo2_history, year, age_bracket))
    lines.append(_hm_count_line(hm_count_current_year(activities, year, HM_MIN_DISTANCE_M)))
    lines.append(_mileage_line(km_month, km_year, month))

    cumulative = {m: days_for_cumulative_km(activities, m, activity_date) for m in CUMULATIVE_MILESTONES_KM}
    lines.append(_cumulative_days_line(cumulative))

    lines.append(_activity_tag(activity_name, activity_date, activity_distance_m))

    return '\n'.join(lines)

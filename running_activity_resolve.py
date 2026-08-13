"""Decide how to compute today's split analysis: prefer an already-indexed
local archive match (fast, and its splits already cover the whole activity
via all_splits()'s multi-extraction), falling back to downloading via
intervals.icu and computing directly when the local archive doesn't have
today's run yet -- the common case right now, since the local archive
currently lags "today" by about two months.
"""
from __future__ import annotations
import tempfile
from datetime import date
from pathlib import Path

import requests

from intervals_pull import download_fit, activity_label
from running_fit_records import parse_running_records
from running_constants import SPLIT_DISTANCES, RUNNING_HISTORY_LOOKBACK_START, EXCLUDED_INTERVALS_ACTIVITY_IDS
from age_category import age_bracket_label
from pace_curve import best_split
from running_pb_query import best_in_scope, most_recent_value_as_of


def find_archive_match(index: dict, activity_date: str, activity_distance_m: float,
                        date_tolerance_days: int = 1, distance_tolerance_m: float = 200.0) -> str | None:
    """±1 day tolerance hedges a UTC/local boundary mismatch between
    intervals.icu's start_date_local and the FIT file's own start_time."""
    target_date = date.fromisoformat(activity_date[:10])
    tolerance = max(distance_tolerance_m, 0.05 * activity_distance_m)
    best_key, best_diff = None, None
    for key, a in index['activities'].items():
        if a.get('sport') != 'running' or not a.get('date') or a.get('total_distance_m') is None:
            continue
        a_date = date.fromisoformat(a['date'])
        if abs((a_date - target_date).days) > date_tolerance_days:
            continue
        diff = abs(a['total_distance_m'] - activity_distance_m)
        if diff > tolerance:
            continue
        if best_diff is None or diff < best_diff:
            best_key, best_diff = key, diff
    return best_key


def backfill_missing_activities(index: dict, auth, athlete_id: str,
                                 since_date: str = RUNNING_HISTORY_LOOKBACK_START) -> list[dict]:
    """Every running activity intervals.icu knows about since `since_date`
    that isn't yet represented in the local archive, as ephemeral
    {'date','sport','total_distance_m'} records for the caller to merge
    into aggregate-stats input.

    Found 2026-07-31: the original fix here was a single ephemeral_activity
    record for "today's" own activity, merged only into that activity's own
    report -- fixed that day's report but not any LATER one about a
    different activity, since index['activities'] never gained the earlier
    run until the watch was next cable-synced. Widened the SAME day
    (07-31->08-01) from "this year only" to the full lookback window after
    discovering (08-01) that the local Garmin archive -- especially the
    pre-2025 Forerunner245 era -- has real, permanent multi-month gaps
    (verified directly: the Forerunner245 folder has zero files for
    2022-04..07 and 2025-04..06, and nothing at all past 2025-01-24; not an
    indexing bug, the device backup itself is incomplete), while
    intervals.icu's own history is gapless back to at least 2021 and
    reaches to 2015 -- confirmed against the user's own recollection of
    >=200km every month since 2021. Without this wider window,
    days_for_cumulative_km's multi-year walk-back would keep counting real
    Forerunner245-era gap days as 0km and overstate every milestone.
    intervals.icu is authoritative and current, so a plain activity-list
    call (no per-activity download, ~0.2s for 6 years, confirmed) is enough
    to catch anything the local archive is still missing. Degrades to
    archive-only on a network error rather than blocking the report."""
    from intervals_activity_source import fetch_activities

    today = date.today().isoformat()
    try:
        activities = fetch_activities(auth, athlete_id, since_date, today)
    except requests.RequestException:
        return []

    archive_dates = {a['date'] for a in index['activities'].values()
                      if a.get('sport') == 'running' and a.get('date')}
    backfilled = []
    for a in activities:
        if activity_label(a.get('type', '')) != 'running' or a.get('id') in EXCLUDED_INTERVALS_ACTIVITY_IDS:
            continue
        a_date = (a.get('start_date_local') or '')[:10]
        dist = a.get('distance')
        if not a_date or not dist or a_date in archive_dates:
            continue
        backfilled.append({'date': a_date, 'sport': 'running', 'total_distance_m': dist})
    return backfilled


def resolve_todays_analysis(activity: dict, auth, index: dict, birth_year: int,
                             vo2_history: list[dict]) -> dict:
    """Returns {'splits': {label: entry}, 'vo2_reported': float|None,
    'ephemeral_pool_entries': {label: [entry,...]}}.

    vo2_reported is always the most-recent-known-value carry-forward from
    vo2_history as of this activity's date. vo2_history is intervals.icu-
    sourced (see running_vo2_source.fetch_vo2max_history), fetched fresh by
    the caller -- the local device's raw 'VO2 Max' field is confirmed
    (2026-07-24) to never appear on running files in this rider's archive,
    only cycling, so it's not a usable source for this.

    ephemeral_pool_entries is empty in the archive-match case (the real
    entries are already in index['splits']); populated with one synthetic
    entry per label in the fallback case, for the caller to merge into the
    ranking pool for this report only -- nothing here gets persisted.

    Aggregate-stats completeness (km/HM-count/cumulative-days) is handled
    separately by backfill_year_activities, not here -- see its docstring
    for why a single per-activity ephemeral record wasn't enough.
    """
    activity_date = (activity.get('start_date_local') or '')[:10]
    activity_distance_m = activity.get('distance') or 0.0
    vo2_reported = most_recent_value_as_of(vo2_history, activity_date)

    matched_key = find_archive_match(index, activity_date, activity_distance_m)
    if matched_key is not None:
        splits = {}
        for label, _ in SPLIT_DISTANCES:
            entry = best_in_scope(index['splits'].get(label, []), 'pace_s_per_km',
                                   better_is_higher=False, source_key=matched_key)
            if entry is not None:
                splits[label] = entry
        return {'splits': splits, 'vo2_reported': vo2_reported, 'ephemeral_pool_entries': {}}

    # Fallback: not yet in the local archive -- download via intervals.icu
    # exactly as the cycling pipeline does, compute directly, don't persist.
    fit_bytes = download_fit(auth, activity['id'])
    if not fit_bytes:
        raise ValueError(f"could not download .fit for activity {activity['id']}")
    with tempfile.NamedTemporaryFile(suffix='.fit') as tmp:
        tmp.write(fit_bytes)
        tmp.flush()
        result = parse_running_records(Path(tmp.name))
    if result is None:
        raise ValueError('no usable records in downloaded .fit')

    elapsed_s, distance_m, heart_rate, meta = result
    year = meta['start_time'].year if meta['start_time'] else int(activity_date[:4])
    bracket = age_bracket_label(year, birth_year)
    source_tag = f"intervals:{activity['id']}"

    splits = {}
    ephemeral_pool_entries = {}
    for label, target_m in SPLIT_DISTANCES:
        found = best_split(elapsed_s, distance_m, target_m, hr=heart_rate)
        if found is None:
            continue
        entry = {'source_key': source_tag, 'date': activity_date,
                 'elapsed_s': found['elapsed_s'], 'pace_s_per_km': found['pace_s_per_km'],
                 'age_bracket': bracket, 'avg_hr': found['avg_hr']}
        splits[label] = entry
        ephemeral_pool_entries[label] = [entry]

    return {'splits': splits, 'vo2_reported': vo2_reported,
            'ephemeral_pool_entries': ephemeral_pool_entries}

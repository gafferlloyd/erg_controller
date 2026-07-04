"""Detect new qualifying rides via intervals.icu, pull their .fit file, analyze,
and send a summary via Signal -- meant to be copy-pasted by hand into the
ride's Strava description afterward (this script never touches Strava's API).

Run manually for testing, or via the strava-efficiency-post systemd timer for
the recurring/automatic case.

Usage:
    python3 strava_efficiency_post.py                       # normal run
    python3 strava_efficiency_post.py --dry-run              # compute + print, never send/save
    python3 strava_efficiency_post.py --activity-id i162397457  # one specific ride
    python3 strava_efficiency_post.py --activity-id i162397457 --force --dry-run
"""
from __future__ import annotations
import argparse
import fcntl
import logging
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import requests

import strava_state
import signal_notify
from strava_summary import build_summary
from wprime_locus import parse_fit_records, _to_1s_grid
from intervals_pull import load_env, download_fit, ENV_PATH
from intervals_activity_source import fetch_activities, qualifies, get_auth

LOCK_PATH = Path(__file__).parent / 'state' / '.strava_efficiency_post.lock'
DEFAULT_LOOKBACK_DAYS = 14

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)


def process_activity(auth, activity: dict, weight_kg: float | None,
                      cp: float, wprime: float, solve_wprimes: tuple,
                      dry_run: bool) -> str:
    fit_bytes = download_fit(auth, activity['id'])
    if not fit_bytes:
        raise ValueError(f"could not download .fit for activity {activity['id']}")

    with tempfile.NamedTemporaryFile(suffix='.fit') as tmp:
        tmp.write(fit_bytes)
        tmp.flush()
        result = parse_fit_records(Path(tmp.name))
    if result is None:
        raise ValueError('no usable records in downloaded .fit')

    elapsed, raw_p, raw_h, _meta = result
    power_1hz, hr_1hz = _to_1s_grid(elapsed, raw_p, raw_h)

    summary = build_summary(activity, power_1hz, hr_1hz, elapsed.tolist(), raw_p, raw_h,
                             weight_kg, cp, wprime, solve_wprimes)

    if dry_run:
        print(f"\n--- DRY RUN: activity {activity['id']} ---")
        print(summary)
        return summary

    signal_notify.send(summary)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--lookback-days', type=int, default=DEFAULT_LOOKBACK_DAYS)
    ap.add_argument('--dry-run', action='store_true', help='Compute + print, never send or save state')
    ap.add_argument('--activity-id', help='Process one specific intervals.icu activity id, bypassing detection')
    ap.add_argument('--force', action='store_true', help='Bypass the marker/cache check (with --activity-id)')
    ap.add_argument('--cp', type=float, default=277.0)
    ap.add_argument('--wprime', type=float, default=21000.0)
    ap.add_argument('--solve-wprimes', type=float, nargs='+', default=[15000.0, 25000.0])
    ap.add_argument('--weight-kg', type=float, help='Override rider weight (default: hr_efficiency.WEIGHT_KG)')
    args = ap.parse_args(argv)

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info('Another run is already in progress -- exiting.')
        return 0

    if not ENV_PATH.exists():
        log.error('Credentials not found at %s', ENV_PATH)
        return 1
    env = load_env(ENV_PATH)
    if not env.get('ICU_API_KEY') or not env.get('ICU_ATHLETE_ID'):
        log.error('ICU_API_KEY / ICU_ATHLETE_ID missing from %s', ENV_PATH)
        return 1
    auth = get_auth(env)
    athlete_id = env['ICU_ATHLETE_ID']

    state = {} if args.dry_run else strava_state.load_processed()

    if args.activity_id:
        candidates = [{'id': args.activity_id, 'name': f'activity {args.activity_id}',
                       'start_date_local': ''}]
        # --activity-id bypasses the qualifies() filter -- assume the caller knows what they want.
    else:
        newest = datetime.now().strftime('%Y-%m-%d')
        oldest = (datetime.now() - timedelta(days=args.lookback_days)).strftime('%Y-%m-%d')
        try:
            activities = fetch_activities(auth, athlete_id, oldest, newest)
        except requests.RequestException as e:
            log.error('Cannot list activities from intervals.icu (%s).', e)
            return 1
        candidates = sorted((a for a in activities if qualifies(a)),
                            key=lambda a: a.get('start_date_local', ''))

    processed, skipped, failed = 0, 0, 0
    for activity in candidates:
        aid = activity['id']
        if not args.force and strava_state.should_skip(aid, state):
            skipped += 1
            continue
        try:
            process_activity(auth, activity, args.weight_kg, args.cp, args.wprime,
                              tuple(args.solve_wprimes), args.dry_run)
            if not args.dry_run:
                strava_state.mark_sent(aid)
            processed += 1
        except Exception as e:
            log.error('Activity %s: %s -- skipping this one', aid, e)
            if not args.dry_run:
                strava_state.record_attempt(aid)
            failed += 1

    log.info('Done: %d processed, %d skipped (already done), %d failed', processed, skipped, failed)
    return 0


if __name__ == '__main__':
    sys.exit(main())

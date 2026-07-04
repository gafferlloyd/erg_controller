"""Detect new qualifying Strava rides, analyze them, send a summary via Signal.

Read-only against Strava (activity:read scope only -- never writes anything
back). Run manually for testing, or via the strava-efficiency-post systemd
timer for the recurring/automatic case.

Usage:
    python3 strava_efficiency_post.py                     # normal run
    python3 strava_efficiency_post.py --dry-run            # compute + print, never send/save
    python3 strava_efficiency_post.py --activity-id 12345  # one specific ride
    python3 strava_efficiency_post.py --activity-id 12345 --force --dry-run
"""
from __future__ import annotations
import argparse
import fcntl
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import strava_auth
import strava_state
import signal_notify
from strava_client import StravaClient, qualifies, AuthError, ScopeError, RateLimited
from strava_summary import build_summary

LOCK_PATH = Path(__file__).parent / 'state' / '.strava_efficiency_post.lock'
DEFAULT_LOOKBACK_DAYS = 14

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)


def process_activity(client: StravaClient, activity: dict, weight_kg: float | None,
                      cp: float, wprime: float, solve_wprimes: tuple,
                      dry_run: bool) -> str:
    streams = client.get_streams(activity['id'])
    if not streams.get('time', {}).get('data') or not streams.get('watts', {}).get('data'):
        raise ValueError('streams missing time or watts data')

    summary = build_summary(activity, streams, weight_kg, cp, wprime, solve_wprimes)

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
    ap.add_argument('--activity-id', type=int, help='Process one specific ride, bypassing detection')
    ap.add_argument('--force', action='store_true', help='Bypass the marker/cache check (with --activity-id)')
    ap.add_argument('--cp', type=float, default=277.0)
    ap.add_argument('--wprime', type=float, default=21000.0)
    ap.add_argument('--solve-wprimes', type=float, nargs='+', default=[15000.0, 25000.0])
    args = ap.parse_args(argv)

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info('Another run is already in progress -- exiting.')
        return 0

    env = strava_auth.load_env()
    client = StravaClient(env)

    weight_kg = None
    try:
        athlete = client.get_athlete()
        weight_kg = athlete.get('weight') or None
    except (ScopeError, AuthError, RateLimited) as e:
        log.warning('Could not fetch athlete weight (%s) -- omitting W/kg', e)

    state = {} if args.dry_run else strava_state.load_processed()

    if args.activity_id:
        candidates = [{'id': args.activity_id, 'name': f'activity {args.activity_id}',
                       'start_date_local': ''}]
        # --activity-id bypasses the qualifies() filter -- assume the caller knows what they want.
    else:
        after_epoch = int((datetime.now(timezone.utc) - timedelta(days=args.lookback_days)).timestamp())
        try:
            activities = client.list_activities(after_epoch)
        except ScopeError as e:
            log.error('Cannot list activities (%s). The Strava token needs re-authorization '
                       'with at least the activity:read scope -- see docs/strava_setup.md.', e)
            return 1
        except AuthError as e:
            log.error('Cannot list activities, auth is broken (%s).', e)
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
            process_activity(client, activity, weight_kg, args.cp, args.wprime,
                              tuple(args.solve_wprimes), args.dry_run)
            if not args.dry_run:
                strava_state.mark_sent(aid)
            processed += 1
        except ScopeError as e:
            log.error('Activity %s: scope error (%s) -- skipping this one', aid, e)
            if not args.dry_run:
                strava_state.record_attempt(aid)
            failed += 1
        except AuthError as e:
            log.error('Activity %s: auth error (%s) -- aborting run', aid, e)
            break
        except RateLimited as e:
            log.warning('Activity %s: rate limited (%s) -- aborting run', aid, e)
            break
        except Exception as e:
            log.error('Activity %s: %s -- skipping this one', aid, e)
            if not args.dry_run:
                strava_state.record_attempt(aid)
            failed += 1

    log.info('Done: %d processed, %d skipped (already done), %d failed', processed, skipped, failed)
    return 0


if __name__ == '__main__':
    sys.exit(main())

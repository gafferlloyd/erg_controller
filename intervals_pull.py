"""Pull recent activity .fit files from intervals.icu.

Bridges the gap between physical USB cable syncs of the Edge 530 / Fenix 7
(see garmin_sync.sh, docs/wprime_calibration.md) — intervals.icu already has
newer rides uploaded via phone/Garmin Connect before the next cable sync
happens. Kept fully independent of ~/PycharmProjects/intervals-icu-dashboard
(reuses its .env credentials read-only, writes to its own output dir, never
touches that project's files, cron, or GitHub push).

Requires ICU_API_KEY / ICU_ATHLETE_ID in the existing
~/PycharmProjects/intervals-icu-dashboard/.env (not duplicated here).

Usage:
    python3 intervals_pull.py                    # last 14 days, cycling + running
    python3 intervals_pull.py --since 2026-06-01
    python3 intervals_pull.py --cycling-only
"""
from __future__ import annotations
import argparse
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

ENV_PATH   = Path.home() / 'PycharmProjects/intervals-icu-dashboard/.env'
DEFAULT_OUT = Path('/mnt/24876752-933e-43bb-abba-2d02b23a05a3/gareth/Documents/Garmin/intervals_bridge')
BASE_URL   = 'https://intervals.icu/api/v1'
DELAY      = 0.3
DEFAULT_SINCE_DAYS = 14

CYCLING_TYPES = {'ride', 'virtualride', 'gravelride', 'mountainbikeride',
                  'ebikeride', 'emountainbikeride', 'indoorcycling'}
RUNNING_TYPES = {'run', 'trailrun', 'virtualrun', 'treadmill'}

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()
    return env


def activity_label(type_key: str) -> str | None:
    t = type_key.lower()
    if t in CYCLING_TYPES: return 'cycling'
    if t in RUNNING_TYPES: return 'running'
    return None


def fetch_activities(auth, athlete_id: str, oldest: str, newest: str) -> list[dict]:
    resp = requests.get(
        f'{BASE_URL}/athlete/{athlete_id}/activities',
        auth=auth,
        params={'oldest': oldest, 'newest': newest,
                'fields': 'id,start_date_local,type,name,trainer'},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def download_fit(auth, activity_id: str) -> bytes | None:
    resp = requests.get(f'{BASE_URL}/activity/{activity_id}/fit-file', auth=auth, timeout=30)
    if resp.status_code == 200:
        return resp.content
    log.warning('  fit-file returned %d for %s', resp.status_code, activity_id)
    return None


def main():
    ap = argparse.ArgumentParser(description='Pull recent .fit files from intervals.icu')
    ap.add_argument('--since', help='YYYY-MM-DD (default: %d days ago)' % DEFAULT_SINCE_DAYS)
    ap.add_argument('--out', default=str(DEFAULT_OUT), help='Output directory')
    ap.add_argument('--cycling-only', action='store_true')
    args = ap.parse_args()

    if not ENV_PATH.exists():
        log.error('Credentials not found at %s', ENV_PATH)
        return
    env = load_env(ENV_PATH)
    api_key, athlete_id = env.get('ICU_API_KEY'), env.get('ICU_ATHLETE_ID')
    if not api_key or not athlete_id:
        log.error('ICU_API_KEY / ICU_ATHLETE_ID missing from %s', ENV_PATH)
        return
    auth = HTTPBasicAuth('API_KEY', api_key)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    newest = datetime.now().strftime('%Y-%m-%d')
    oldest = args.since or (datetime.now() - timedelta(days=DEFAULT_SINCE_DAYS)).strftime('%Y-%m-%d')

    log.info('Fetching activity list %s -> %s for athlete %s ...', oldest, newest, athlete_id)
    activities = fetch_activities(auth, athlete_id, oldest, newest)
    log.info('Found %d activities.', len(activities))

    wanted_types = {'cycling'} if args.cycling_only else {'cycling', 'running'}
    targets = [a for a in activities if activity_label(a.get('type', '')) in wanted_types]
    log.info('%d match requested type(s).', len(targets))

    downloaded, skipped, failed = 0, 0, 0
    for i, activity in enumerate(targets, 1):
        icu_id = activity['id']
        label  = activity_label(activity.get('type', ''))
        start  = activity.get('start_date_local', '')[:19].replace('T', '_').replace(':', '-')
        fit_path = out_dir / f'{start}_{label}_{icu_id}.fit'

        if fit_path.exists():
            skipped += 1
            continue

        log.info('  [%d/%d] %s  %s  %s', i, len(targets), icu_id, label, activity.get('name', ''))
        data = download_fit(auth, icu_id)
        if not data:
            failed += 1
            continue
        fit_path.write_bytes(data)
        downloaded += 1

        if i < len(targets):
            time.sleep(DELAY)

    print(f'\n{"-"*55}')
    print(f'  Downloaded : {downloaded}  ->  {out_dir}')
    print(f'  Skipped    : {skipped}  (already present)')
    print(f'  Failed     : {failed}')
    print(f'{"-"*55}')


if __name__ == '__main__':
    main()

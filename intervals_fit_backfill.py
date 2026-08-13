"""Pull .fit files for running activities intervals.icu knows about but the
local Garmin archive doesn't -- closes the real, permanent gaps found
2026-08-01 in the pre-2025 Forerunner245 era (that device's own local backup
folder stops at 2025-01-24 and has several multi-month holes before that;
verified directly, not an indexing bug).

`running_activity_resolve.backfill_missing_activities` already fixes
aggregate stats (HM count, km/mo, cumulative-days) for these gaps at query
time, using only date/sport/distance from intervals.icu's lightweight
activity-list response. This script goes further: it downloads the actual
.fit files (same intervals_pull.download_fit() used by the single-activity
fallback path, confirmed here to also work for old/historical activity ids)
into a new local archive folder, so gap-period activities get real split/PB
history too -- something the query-time fix structurally cannot provide,
since that needs the full GPS/HR record stream a summary API response
doesn't carry.

Usage:
    python3 intervals_fit_backfill.py --dry-run           # count only, no downloads
    python3 intervals_fit_backfill.py --limit 10           # small batch, for testing
    python3 intervals_fit_backfill.py                      # full backfill
"""
from __future__ import annotations
import argparse
import logging
import sys
import time

from intervals_pull import load_env, download_fit, activity_label, ENV_PATH
from intervals_activity_source import fetch_activities, get_auth
from running_archive_index import load_index, GARMIN_ROOT
from running_constants import RUNNING_HISTORY_LOOKBACK_START, EXCLUDED_INTERVALS_ACTIVITY_IDS

DEST_DIR = GARMIN_ROOT / 'intervals_backfill'
PROGRESS_EVERY = 25

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)


def find_missing_activities(index: dict, auth, athlete_id: str,
                             since_date: str = RUNNING_HISTORY_LOOKBACK_START) -> list[dict]:
    """Full intervals.icu running-activity records (not the lightweight
    ephemeral shape backfill_missing_activities uses) for every date the
    local archive doesn't already have a running activity on."""
    today = time.strftime('%Y-%m-%d')
    activities = fetch_activities(auth, athlete_id, since_date, today)
    archive_dates = {a['date'] for a in index['activities'].values()
                      if a.get('sport') == 'running' and a.get('date')}
    missing = []
    for a in activities:
        if activity_label(a.get('type', '')) != 'running' or a.get('id') in EXCLUDED_INTERVALS_ACTIVITY_IDS:
            continue
        a_date = (a.get('start_date_local') or '')[:10]
        if not a_date or not a.get('distance') or a_date in archive_dates:
            continue
        missing.append(a)
    return missing


def _dest_filename(activity: dict) -> str:
    # "2022-05-26T08:54:33" -> "2022-05-26-08-54-33.fit", matching the
    # existing Fenix7/Forerunner245 date-named convention.
    local = activity['start_date_local'].replace('T', '-').replace(':', '-')
    return f'{local}.fit'


def download_missing(missing: list[dict], auth, dest_dir=DEST_DIR,
                      dry_run: bool = False, limit: int | None = None) -> dict:
    dest_dir.mkdir(parents=True, exist_ok=True)
    to_fetch = missing[:limit] if limit is not None else missing
    downloaded, skipped, failed = 0, 0, 0
    for i, a in enumerate(to_fetch, 1):
        path = dest_dir / _dest_filename(a)
        if path.exists():
            skipped += 1
            continue
        if dry_run:
            downloaded += 1
            continue
        try:
            fit_bytes = download_fit(auth, a['id'])
            if not fit_bytes:
                log.warning('  no .fit returned for activity %s (%s)', a['id'], a.get('start_date_local'))
                failed += 1
                continue
            path.write_bytes(fit_bytes)
            downloaded += 1
        except Exception as e:
            log.warning('  failed to download activity %s (%s): %s', a['id'], a.get('start_date_local'), e)
            failed += 1
        if i % PROGRESS_EVERY == 0:
            log.info('  ...%d/%d (downloaded=%d skipped=%d failed=%d)', i, len(to_fetch), downloaded, skipped, failed)
    return {'downloaded': downloaded, 'skipped': skipped, 'failed': failed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true', help='Count only, download nothing')
    ap.add_argument('--limit', type=int, default=None, help='Only process the first N missing activities')
    args = ap.parse_args(argv)

    if not ENV_PATH.exists():
        log.error('Credentials not found at %s', ENV_PATH)
        return 1
    env = load_env(ENV_PATH)
    if not env.get('ICU_API_KEY') or not env.get('ICU_ATHLETE_ID'):
        log.error('ICU_API_KEY / ICU_ATHLETE_ID missing from %s', ENV_PATH)
        return 1
    auth = get_auth(env)
    athlete_id = env['ICU_ATHLETE_ID']

    index = load_index()
    missing = find_missing_activities(index, auth, athlete_id)
    log.info('%d running activities on intervals.icu are missing from the local archive.', len(missing))
    if args.dry_run:
        log.info('[dry-run] would download up to %s of them into %s', args.limit or 'all', DEST_DIR)
        return 0

    result = download_missing(missing, auth, limit=args.limit)
    log.info('Done: %d downloaded, %d already present, %d failed', result['downloaded'], result['skipped'], result['failed'])
    log.info('Run `python3 running_archive_build.py` next to index the new files.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

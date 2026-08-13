"""Scan the local running archive, parse new files, and merge results into
the persisted index. The single entry point both this module's own CLI and
running_efficiency_post.py call.

NOT locked internally -- callers are responsible for holding LOCK_PATH
around build_or_update_index(), so a manual --full-rebuild invocation and
the hourly automation can't race each other. (Locking inside this function
too would self-deadlock when running_efficiency_post.py's own main() -- the
common caller -- already holds the same lock for its whole run.)

Usage:
    python3 running_archive_build.py --full-rebuild   # one-time initial build, ~13min
    python3 running_archive_build.py                  # incremental (fast once built)
    python3 running_archive_build.py --dry-run --limit 20   # quick sanity check
"""
from __future__ import annotations
import argparse
import fcntl
import logging
import sys
from datetime import datetime
from pathlib import Path

from running_archive_index import (
    load_index, save_index, empty_index, list_candidate_files, source_key, LOCK_PATH,
)
from running_fit_records import parse_running_records
from running_constants import SPLIT_DISTANCES
from age_category import load_birth_year, age_bracket_label
from pace_curve import all_splits
from running_manual_entries import build_manual_split_entries

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)

PROGRESS_EVERY = 100
STALE_WARNING_DAYS = 14

# Explicit denylist, not a heuristic -- found 2026-08-13: these intervals_backfill
# files are bike rides mistagged sport='running' at the source (18.8-30.3 km/h
# sustained for 22min-164min, two still carrying the rider's cycling FTP
# (threshold_power=399) stamped in from intervals.icu's re-export), producing
# fake sub-3'00/km 1k/3k/5k "PBs". MIN_PLAUSIBLE_PACE_S_PER_KM (150.0, see its
# own docstring) can't catch these: it's a per-window GPS-teleport check, and
# these files aren't glitchy -- they're uniformly fast for their entire
# duration, landing at 150.1-172s/km, which sits inside the same pace band as
# elite human running (that's why the floor was calibrated where it is) and
# outside what any whole-activity pace check could safely generalize from a
# couple of examples (see the threshold_power guard's own postmortem above).
# A per-file denylist is the only fix that's actually safe here: it can never
# misfire on a real run, unlike a new heuristic would.
EXCLUDED_SOURCE_KEYS = {
    'intervals_backfill/2016-09-30-15-22-51.fit',
    'intervals_backfill/2018-12-20-18-30-13.fit',
    'intervals_backfill/2020-02-13-17-47-59.fit',
    'intervals_backfill/2020-02-17-07-34-16.fit',
}


def scan_new_files(index: dict, full_rebuild: bool = False) -> list[tuple[str, Path]]:
    candidates = list_candidate_files()
    if full_rebuild:
        return candidates
    known = set(index['activities'].keys())
    return [(label, path) for label, path in candidates if source_key(label, path) not in known]


def index_one_file(source_label: str, path: Path, birth_year: int) -> dict:
    """Returns {'activity': {...}, 'splits_by_label': {label: [entry,...]}}.

    A non-running (or unparseable) file still gets a minimal 'activity'
    entry -- critical so the incremental scan's skip-check stays sport-
    agnostic and doesn't degenerate into re-parsing every cycling file
    every single run.

    activity['vo2max'] is recorded if the local device's raw 'VO2 Max'
    session field is present, but confirmed 2026-07-24 that it never is for
    running files in this archive (only cycling) -- running VO2 SB/PB is
    sourced from intervals.icu instead (see running_vo2_source.py), not
    from this per-file value or any index-level aggregate of it.
    """
    mtime = path.stat().st_mtime
    if source_key(source_label, path) in EXCLUDED_SOURCE_KEYS:
        activity = {'date': None, 'sport': None, 'total_distance_m': None,
                    'vo2max': None, 'age_bracket': None, 'indexed_mtime': mtime}
        return {'activity': activity, 'splits_by_label': {}}

    result = parse_running_records(path)
    if result is None:
        activity = {'date': None, 'sport': None, 'total_distance_m': None,
                    'vo2max': None, 'age_bracket': None, 'indexed_mtime': mtime}
        return {'activity': activity, 'splits_by_label': {}}

    elapsed_s, distance_m, heart_rate, meta = result
    date_str = meta['start_time'].date().isoformat() if meta['start_time'] else None
    sport = meta['sport']

    if sport != 'running' or date_str is None:
        activity = {'date': date_str, 'sport': sport, 'total_distance_m': None,
                    'vo2max': None, 'age_bracket': None, 'indexed_mtime': mtime}
        return {'activity': activity, 'splits_by_label': {}}

    session = meta.get('session') or {}

    # NOTE 2026-08-01: a threshold_power-based guard was tried and reverted
    # the same day. It correctly caught the two known-bad files (2016-09-30,
    # 2018-12-20, both threshold_power=399), but turned out to be
    # unreliable: threshold_power=399 also showed up on a perfectly ordinary
    # 21.5km/103min run (2025-04-02, ~12.5km/h -- an entirely normal pace).
    # It's almost certainly intervals.icu stamping the rider's PROFILE-level
    # configured cycling FTP onto every .fit file it re-exports for
    # download, regardless of the original activity's actual sport -- not a
    # per-activity signal at all. Wrongly excluded 730 of 1097 backfilled
    # activities (a huge false-positive rate) before this was caught by
    # comparing gap-month mileage before/after. Left as a cautionary note:
    # don't reintroduce a power-field check without validating across many
    # more real examples first, not just the handful that motivated it.

    total_distance_m = session.get('total_distance')
    if total_distance_m is None and len(distance_m):
        total_distance_m = float(distance_m[-1])  # defensive fallback

    vo2max = session.get('VO2 Max')
    year = meta['start_time'].year
    bracket = age_bracket_label(year, birth_year)
    key = source_key(source_label, path)

    splits_by_label = {}
    for label, target_m in SPLIT_DISTANCES:
        found = all_splits(elapsed_s, distance_m, target_m, hr=heart_rate)
        if found:
            splits_by_label[label] = [
                {'source_key': key, 'date': date_str, 'elapsed_s': f['elapsed_s'],
                 'pace_s_per_km': f['pace_s_per_km'], 'age_bracket': bracket,
                 'avg_hr': f['avg_hr']}
                for f in found
            ]

    # A file tagged 'running' that's long enough to have produced at least a
    # 1k split (pace_curve's own per-window MIN_PLAUSIBLE_PACE_S_PER_KM
    # floor already applied above) but produced NONE, at any of the 10
    # tracked distances, is almost certainly mislabeled at the source, not a
    # real run with an isolated glitch -- a genuine run with, say, a couple
    # minutes of lost GPS signal still has plenty of other genuinely-paced
    # windows throughout the rest of its duration and would still produce
    # splits normally. Found 2026-08-01: an intervals.icu-backfilled 2016
    # file (83km/2h44m, avg 31.5km/h, real cycling power/TSS fields) was
    # tagged 'running' by the device itself -- pace_curve correctly rejects
    # every window in it as implausible, at every distance, which is exactly
    # the "no evidence of real running anywhere" signal this checks for.
    # Deliberately NOT a whole-activity average-pace check (an earlier
    # version of this guard was exactly that, and the user correctly pointed
    # out it could misfire on a real run whose reported total_distance gets
    # inflated by a single bad GPS reacquisition point, even though the run
    # itself was genuine) -- this only excludes an activity when there's no
    # plausible split ANYWHERE in it, not just an unlucky overall average.
    if (total_distance_m or 0) >= 1000.0 and not splits_by_label:
        activity = {'date': date_str, 'sport': sport, 'total_distance_m': None,
                    'vo2max': None, 'age_bracket': None, 'indexed_mtime': mtime}
        return {'activity': activity, 'splits_by_label': {}}

    activity = {'date': date_str, 'sport': sport, 'total_distance_m': total_distance_m,
                'vo2max': float(vo2max) if vo2max is not None else None,
                'age_bracket': bracket, 'indexed_mtime': mtime}
    return {'activity': activity, 'splits_by_label': splits_by_label}


def merge_manual_entries(index: dict, birth_year: int) -> bool:
    """Merges running_manual_entries.py's hand-verified race results into
    index['splits'], matched by source_key. Existing entries are replaced
    in place (not just skipped) so an edit to running_manual_entries.py
    (e.g. a display_tag rename) propagates into an already-built index
    without needing a --full-rebuild. Returns True if anything was newly
    added or changed (so the caller knows whether a save is needed)."""
    changed = False
    manual_by_label = build_manual_split_entries(birth_year)
    for label, entries in manual_by_label.items():
        existing = index['splits'].get(label, [])
        by_key = {e['source_key']: i for i, e in enumerate(existing)}
        for entry in entries:
            idx = by_key.get(entry['source_key'])
            if idx is None:
                existing.append(entry)
                changed = True
            elif existing[idx] != entry:
                existing[idx] = entry
                changed = True
        index['splits'][label] = existing
    return changed


def build_or_update_index(full_rebuild: bool = False, birth_year: int | None = None,
                           quiet: bool = False, dry_run: bool = False,
                           limit: int | None = None) -> dict:
    if birth_year is None:
        birth_year = load_birth_year()

    index = empty_index() if full_rebuild else load_index()
    to_scan = scan_new_files(index, full_rebuild=full_rebuild)
    if limit is not None:
        to_scan = to_scan[:limit]

    if not quiet:
        log.info('Indexing %d file(s)%s%s...', len(to_scan),
                  ' (full rebuild)' if full_rebuild else '', ' [dry-run]' if dry_run else '')

    for i, (label, path) in enumerate(to_scan, 1):
        result = index_one_file(label, path, birth_year)
        key = source_key(label, path)
        index['activities'][key] = result['activity']
        for split_label, entries in result['splits_by_label'].items():
            index['splits'].setdefault(split_label, []).extend(entries)
        if not quiet and i % PROGRESS_EVERY == 0:
            log.info('  ...%d/%d', i, len(to_scan))

    manual_changed = merge_manual_entries(index, birth_year)

    if (to_scan or manual_changed) and not dry_run:
        index['built_at'] = datetime.now().isoformat()
        save_index(index)

    _warn_if_stale(index, quiet)
    return index


def _warn_if_stale(index: dict, quiet: bool) -> None:
    dates = [a['date'] for a in index['activities'].values()
             if a.get('sport') == 'running' and a.get('date')]
    if not dates:
        return
    newest = max(dates)
    age_days = (datetime.now() - datetime.fromisoformat(newest)).days
    if age_days > STALE_WARNING_DAYS and not quiet:
        log.warning('Newest indexed running activity is %s (%d days old) -- '
                     'local archive may need a manual cable sync.', newest, age_days)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--full-rebuild', action='store_true', help='Ignore existing index, rescan everything (~13min)')
    ap.add_argument('--dry-run', action='store_true', help='Compute but do not save -- for sanity-checking')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--limit', type=int, help='Only process this many new files (for quick manual checks)')
    args = ap.parse_args(argv)

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info('Another run (report or index build) is already in progress -- exiting.')
        return 0

    index = build_or_update_index(full_rebuild=args.full_rebuild, quiet=args.quiet,
                                    dry_run=args.dry_run, limit=args.limit)
    n_running = sum(1 for a in index['activities'].values() if a.get('sport') == 'running')
    log.info('Index has %d total activities (%d running), splits for %d distance(s).%s',
              len(index['activities']), n_running, len(index['splits']),
              ' [not saved -- dry-run]' if args.dry_run else '')
    return 0


if __name__ == '__main__':
    sys.exit(main())

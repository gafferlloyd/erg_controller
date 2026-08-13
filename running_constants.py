"""Shared constants for the running-analysis pipeline: split distances,
the HM-count threshold, cumulative-distance milestones, and the
minimum-distance qualifying filter.
"""
from __future__ import annotations

# (report/index label, target distance in meters), in report order.
SPLIT_DISTANCES = [
    ("1k", 1000.0),
    ("3k", 3000.0),
    ("5k", 5000.0),
    ("10k", 10000.0),
    ("15k", 15000.0),
    ("HM", 21097.5),
    ("25k", 25000.0),
    ("30k", 30000.0),
    ("Marathon", 42195.0),
]

# "HM Count" is an open-ended minimum-distance threshold, not a band around
# the exact half-marathon distance -- confirmed 2026-07-26 against the
# user's own intervals.icu "HM" filter ("Distance > 21km"), which counts
# every run of 21km or more, including ones stretching well past true HM
# distance (up to 30km in their real data). An earlier version of this
# constant used a tight (20500, 21800) band, which undercounted by half.
HM_MIN_DISTANCE_M = 21000.0

CUMULATIVE_MILESTONES_KM = [1000, 2000, 3000, 5000, 10000]

# Minimum total run distance to trigger a Signal report at all -- permissive
# on purpose, since even a short run can set a 1km split PB.
MIN_QUALIFYING_DISTANCE_M = 1000.0

# Faster than any split at this distance could plausibly be run by a human
# -- a hard floor, not tuned to this rider's own ability, so it only ever
# rejects genuinely impossible data, never a real personal effort. Found
# 2026-08-01: an intervals.icu-backfilled 2016 file tagged 'running' by the
# device itself was actually an 83km/2h44m bike ride (avg 31.5km/h, real
# cycling power/TSS fields) -- pace_curve happily extracted "1'27/km" splits
# from it, and it would have also polluted HM-count/mileage as an 83km
# "run". A source's own sport tag isn't trustworthy enough to skip this
# check. First value (120.0) was miscalibrated -- it's numerically FASTER
# than the human 1km world record (2:11.96 -> 131.96 s/km), so it let
# several more implausible entries (2'00-2'44/km, also intervals_backfill/
# files) through undetected. 150.0 (2'30/km) sits comfortably slower than
# every distance's world record (1km 131.96, 5k Cheptegei's WR ~151.1,
# marathon Kiptum's WR ~171.5) with real margin, while still far faster than
# this rider's own actual bests (fastest known 1k: 2'52/km) -- no real
# effort of theirs, at any distance, is at risk of a false rejection.
MIN_PLAUSIBLE_PACE_S_PER_KM = 150.0

# How far back to look on intervals.icu when backfilling aggregate-stats
# gaps in the local archive (see running_activity_resolve.backfill_missing_
# activities). Confirmed 2026-08-01: intervals.icu's own history goes back
# to 2015-03-08 for this rider -- far deeper than earlier assumed (~2025-05)
# -- and is GAPLESS for 2021-2025 where the local Garmin archive (especially
# the pre-2025 Forerunner245 era) has real multi-month holes. A fixed date
# rather than a discovered one: a query this wide is cheap (~0.2s for 6
# years, confirmed), so there's no need to find the exact earliest date.
RUNNING_HISTORY_LOOKBACK_START = '2015-01-01'

# intervals.icu activity ids known to be bike rides mistagged type='Run' at
# the source (one is literally named "Munich Cycling"; another is an exact
# duplicate of a same-timestamp "Ride" entry) -- found 2026-08-13 chasing a
# fake sub-3'00/km 1k/3k/5k PB artifact. Shared between running_archive_build
# (which denylists the corresponding local intervals_backfill/ files by
# source_key) and running_activity_resolve.backfill_missing_activities
# (which must skip the same ids at query time, or excluding the local file
# alone just lets these dates get silently re-added as ephemeral aggregate-
# stats records on the next run).
EXCLUDED_INTERVALS_ACTIVITY_IDS = {
    'i17922553',  # 2016-09-30 -- exact duplicate of Ride i17922555, same timestamp
    'i17925157',  # 2018-12-20 -- named "Munich Cycling", typed Run
    'i17929592',  # 2020-02-13 -- named "Munich cycling", typed Run
    'i17929625',  # 2020-02-17 -- 18.8km/h sustained, evening commute pattern
}

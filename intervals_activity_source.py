"""Detect qualifying rides and pull their .fit files from intervals.icu.

Reuses intervals_pull.py's auth/download (same .env, same download_fit()) --
does not duplicate that logic, only adds the broader activity-list fields
needed for qualification filtering (distance/power/HR), which
intervals_pull.py's own fetch_activities() doesn't request since it's built
for a different purpose (bridging Garmin sync gaps, not filtering).
"""
from __future__ import annotations
import requests
from requests.auth import HTTPBasicAuth

from intervals_pull import load_env, download_fit, activity_label, ENV_PATH, BASE_URL

CYCLING_TYPES = {'ride', 'virtualride', 'gravelride', 'mountainbikeride',
                  'ebikeride', 'emountainbikeride'}


def fetch_activities(auth: HTTPBasicAuth, athlete_id: str, oldest: str, newest: str) -> list[dict]:
    resp = requests.get(
        f'{BASE_URL}/athlete/{athlete_id}/activities',
        auth=auth,
        params={'oldest': oldest, 'newest': newest,
                # NB: intervals.icu's average power value needs the icu_ prefix
                # (icu_average_watts) -- device_watts/has_heartrate are plain
                # booleans though, same names Strava uses for the same thing.
                'fields': 'id,start_date_local,type,name,trainer,distance,'
                          'device_watts,has_heartrate,icu_average_watts'},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def qualifies(activity: dict) -> bool:
    label = activity_label(activity.get('type', ''))
    return (label == 'cycling'
            and (activity.get('distance') or 0) >= 20000
            and bool(activity.get('device_watts'))
            and bool(activity.get('has_heartrate')))


def get_auth(env: dict) -> HTTPBasicAuth:
    return HTTPBasicAuth('API_KEY', env['ICU_API_KEY'])

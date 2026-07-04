"""Read-only Strava API v3 client: list activities, get streams, get athlete.

No write/update calls -- this integration only ever reads from Strava. Every
request goes through _request(), which refreshes the access token once on a
401 and retries, and raises typed errors the caller can handle per-activity.
"""
from __future__ import annotations
import requests

import strava_auth

BASE_URL = 'https://www.strava.com/api/v3'
CYCLING_TYPES = {'ride', 'virtualride', 'gravelride', 'mountainbikeride',
                  'ebikeride', 'emountainbikeride'}


class AuthError(Exception):
    """401 persisted through a refresh + retry."""


class ScopeError(Exception):
    """403 -- missing activity:read_all (private activity) or profile:read_all (weight)."""


class RateLimited(Exception):
    """429 -- caller should abort the rest of this run."""


class StravaClient:
    def __init__(self, env: dict):
        self.env = env

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f'{BASE_URL}/{path}'
        headers = {'Authorization': f'Bearer {self.env["STRAVA_ACCESS_TOKEN"]}'}
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)

        if resp.status_code == 401:
            self.env = strava_auth.refresh_and_save(self.env)
            headers = {'Authorization': f'Bearer {self.env["STRAVA_ACCESS_TOKEN"]}'}
            resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
            if resp.status_code == 401:
                raise AuthError(f'{method} {path} still 401 after token refresh')

        if resp.status_code == 403:
            raise ScopeError(
                f'{method} {path} -> 403: missing activity:read_all (private activity) '
                'or profile:read_all (athlete weight)')
        if resp.status_code == 429:
            raise RateLimited(f'{method} {path} -> 429 rate limited')

        resp.raise_for_status()
        return resp

    def list_activities(self, after_epoch: int, per_page: int = 100) -> list[dict]:
        """All activities after `after_epoch`, paginated."""
        results = []
        page = 1
        while True:
            resp = self._request('GET', 'athlete/activities', params={
                'after': after_epoch, 'per_page': per_page, 'page': page})
            batch = resp.json()
            results.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return results

    def get_streams(self, activity_id: int,
                     keys=('time', 'heartrate', 'watts', 'distance')) -> dict:
        resp = self._request('GET', f'activities/{activity_id}/streams', params={
            'keys': ','.join(keys), 'key_by_type': 'true'})
        return resp.json()

    def get_athlete(self) -> dict:
        resp = self._request('GET', 'athlete')
        return resp.json()


def qualifies(activity: dict) -> bool:
    t = (activity.get('type') or activity.get('sport_type') or '').lower()
    return (t in CYCLING_TYPES
            and activity.get('distance', 0) >= 20000
            and bool(activity.get('device_watts'))
            and bool(activity.get('has_heartrate')))

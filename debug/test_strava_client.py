"""Smoke tests for strava_client.py -- monkeypatches requests, never touches the network.

Run from project root:
  python debug/test_strava_client.py
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import strava_client
from strava_client import StravaClient, AuthError, ScopeError, RateLimited, qualifies


def _resp(status, json_data=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data or {}
    if status >= 400 and status != 401 and status != 403 and status != 429:
        r.raise_for_status.side_effect = Exception(f'HTTP {status}')
    else:
        r.raise_for_status.return_value = None
    return r


def test_success_no_refresh_needed():
    client = StravaClient({'STRAVA_ACCESS_TOKEN': 'tok'})
    with patch('requests.request', return_value=_resp(200, {'ok': True})) as m:
        resp = client._request('GET', 'athlete')
        assert resp.json() == {'ok': True}
        assert m.call_count == 1
    print('  test_success_no_refresh_needed   PASS')


def test_401_then_refresh_then_retry_succeeds():
    client = StravaClient({'STRAVA_ACCESS_TOKEN': 'stale',
                            'STRAVA_CLIENT_ID': 'id', 'STRAVA_CLIENT_SECRET': 'secret',
                            'STRAVA_REFRESH_TOKEN': 'refresh'})
    responses = [_resp(401), _resp(200, {'ok': True})]
    with patch('requests.request', side_effect=responses), \
         patch('strava_auth.refresh_and_save', return_value={'STRAVA_ACCESS_TOKEN': 'fresh'}) as rf:
        resp = client._request('GET', 'athlete')
        assert resp.json() == {'ok': True}
        assert rf.call_count == 1
        assert client.env['STRAVA_ACCESS_TOKEN'] == 'fresh'
    print('  test_401_then_refresh_then_retry_succeeds  PASS')


def test_401_persists_raises_autherror():
    client = StravaClient({'STRAVA_ACCESS_TOKEN': 'stale'})
    with patch('requests.request', return_value=_resp(401)), \
         patch('strava_auth.refresh_and_save', return_value={'STRAVA_ACCESS_TOKEN': 'still_bad'}):
        try:
            client._request('GET', 'athlete')
            assert False, 'expected AuthError'
        except AuthError:
            pass
    print('  test_401_persists_raises_autherror  PASS')


def test_403_raises_scopeerror():
    client = StravaClient({'STRAVA_ACCESS_TOKEN': 'tok'})
    with patch('requests.request', return_value=_resp(403)):
        try:
            client._request('GET', 'athlete')
            assert False, 'expected ScopeError'
        except ScopeError:
            pass
    print('  test_403_raises_scopeerror       PASS')


def test_429_raises_ratelimited():
    client = StravaClient({'STRAVA_ACCESS_TOKEN': 'tok'})
    with patch('requests.request', return_value=_resp(429)):
        try:
            client._request('GET', 'athlete')
            assert False, 'expected RateLimited'
        except RateLimited:
            pass
    print('  test_429_raises_ratelimited      PASS')


def test_qualifies_filters():
    good = {'type': 'Ride', 'distance': 25000, 'device_watts': True, 'has_heartrate': True}
    assert qualifies(good)
    assert not qualifies({**good, 'distance': 5000})       # too short
    assert not qualifies({**good, 'device_watts': False})  # no power meter
    assert not qualifies({**good, 'has_heartrate': False}) # no HR
    assert not qualifies({**good, 'type': 'Run'})           # wrong sport
    print('  test_qualifies_filters           PASS')


if __name__ == '__main__':
    test_success_no_refresh_needed()
    test_401_then_refresh_then_retry_succeeds()
    test_401_persists_raises_autherror()
    test_403_raises_scopeerror()
    test_429_raises_ratelimited()
    test_qualifies_filters()
    print('\nAll tests passed.')

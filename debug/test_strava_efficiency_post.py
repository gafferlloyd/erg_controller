"""Smoke tests for strava_efficiency_post.py's process_activity() and lock
behavior. Full main() is exercised end-to-end manually via --dry-run against
a real activity id, not here (needs real network access).

Run from project root:
  python debug/test_strava_efficiency_post.py
"""
import fcntl
import struct
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import strava_efficiency_post
from strava_efficiency_post import process_activity


def _make_synthetic_fit_bytes() -> bytes:
    """Not a real .fit file -- process_activity's own parse call is mocked out
    directly in these tests, so the bytes just need to be non-empty."""
    return b'\x0efake fit bytes for testing, never actually parsed'


def _synthetic_parsed_ride(duration_s=1500):
    import numpy as np
    elapsed = np.arange(duration_s, dtype=float)
    raw_p = [220.0] * duration_s
    raw_h = [140.0] * duration_s
    return elapsed, raw_p, raw_h, {}


def test_process_activity_dry_run_does_not_send():
    activity = {'id': 'i1', 'name': 'Test', 'start_date_local': '2026-07-04'}
    with patch('strava_efficiency_post.download_fit', return_value=_make_synthetic_fit_bytes()), \
         patch('strava_efficiency_post.parse_fit_records', return_value=_synthetic_parsed_ride()), \
         patch('signal_notify.send') as mock_send:
        summary = process_activity(auth=None, activity=activity, weight_kg=70.0, cp=277.0,
                                     wprime=21000.0, solve_wprimes=(15000.0, 25000.0), dry_run=True)
        mock_send.assert_not_called()
    assert 'Ride: Test' in summary
    print('  test_process_activity_dry_run_does_not_send  PASS')


def test_process_activity_live_sends():
    activity = {'id': 'i2', 'name': 'Test2', 'start_date_local': '2026-07-04'}
    with patch('strava_efficiency_post.download_fit', return_value=_make_synthetic_fit_bytes()), \
         patch('strava_efficiency_post.parse_fit_records', return_value=_synthetic_parsed_ride()), \
         patch('signal_notify.send') as mock_send:
        process_activity(auth=None, activity=activity, weight_kg=70.0, cp=277.0, wprime=21000.0,
                          solve_wprimes=(15000.0, 25000.0), dry_run=False)
        mock_send.assert_called_once()
    print('  test_process_activity_live_sends       PASS')


def test_process_activity_rejects_missing_fit():
    activity = {'id': 'i3', 'name': 'Empty', 'start_date_local': '2026-07-04'}
    with patch('strava_efficiency_post.download_fit', return_value=None):
        try:
            process_activity(auth=None, activity=activity, weight_kg=None, cp=277.0,
                              wprime=21000.0, solve_wprimes=(15000.0,), dry_run=True)
            assert False, 'expected ValueError'
        except ValueError:
            pass
    print('  test_process_activity_rejects_missing_fit  PASS')


def test_process_activity_rejects_unparseable_fit():
    activity = {'id': 'i4', 'name': 'Bad', 'start_date_local': '2026-07-04'}
    with patch('strava_efficiency_post.download_fit', return_value=_make_synthetic_fit_bytes()), \
         patch('strava_efficiency_post.parse_fit_records', return_value=None):
        try:
            process_activity(auth=None, activity=activity, weight_kg=None, cp=277.0,
                              wprime=21000.0, solve_wprimes=(15000.0,), dry_run=True)
            assert False, 'expected ValueError'
        except ValueError:
            pass
    print('  test_process_activity_rejects_unparseable_fit  PASS')


def test_flock_prevents_concurrent_holder():
    """A second exclusive-nonblocking flock on the same file must fail while
    the first is held -- the exact mechanism main() relies on."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'test.lock'
        f1 = open(path, 'w')
        fcntl.flock(f1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f2 = open(path, 'w')
        try:
            fcntl.flock(f2, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert False, 'expected BlockingIOError'
        except BlockingIOError:
            pass
        finally:
            f1.close()
            f2.close()
    print('  test_flock_prevents_concurrent_holder  PASS')


if __name__ == '__main__':
    test_process_activity_dry_run_does_not_send()
    test_process_activity_live_sends()
    test_process_activity_rejects_missing_fit()
    test_process_activity_rejects_unparseable_fit()
    test_flock_prevents_concurrent_holder()
    print('\nAll tests passed.')

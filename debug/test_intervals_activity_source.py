"""Smoke tests for intervals_activity_source.py.

Run from project root:
  python debug/test_intervals_activity_source.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from intervals_activity_source import qualifies, ENV_PATH


def test_qualifies_filters():
    good = {'type': 'Ride', 'distance': 25000, 'device_watts': True, 'has_heartrate': True}
    assert qualifies(good)
    assert not qualifies({**good, 'distance': 5000})         # too short
    assert not qualifies({**good, 'device_watts': False})    # no power meter
    assert not qualifies({**good, 'has_heartrate': False})   # no HR
    assert not qualifies({**good, 'type': 'Run'})             # wrong sport
    print('  test_qualifies_filters              PASS')


def check_real_env():
    print(f'\nReal .env at {ENV_PATH}: ', end='')
    print('found' if ENV_PATH.exists() else 'MISSING')


if __name__ == '__main__':
    test_qualifies_filters()
    check_real_env()
    print('\nAll tests passed.')

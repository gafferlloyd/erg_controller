"""Smoke tests and diagnostics for intervals_pull.py.

Run from project root:
  python debug/test_intervals_pull.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from intervals_pull import load_env, activity_label, ENV_PATH


def test_load_env():
    content = '\n'.join([
        '# comment line, should be skipped',
        '',
        'ICU_API_KEY=abc123',
        'ICU_ATHLETE_ID=i128043',
        'GARMIN_EMAIL=someone@example.com  ',  # trailing space should be stripped
    ])
    with tempfile.NamedTemporaryFile('w', suffix='.env', delete=False) as f:
        f.write(content)
        path = Path(f.name)
    env = load_env(path)
    path.unlink()
    assert env['ICU_API_KEY'] == 'abc123', env
    assert env['ICU_ATHLETE_ID'] == 'i128043', env
    assert env['GARMIN_EMAIL'] == 'someone@example.com', env
    assert len(env) == 3, env  # comment/blank lines excluded
    print('  test_load_env                  PASS')


def test_activity_label():
    cases = [
        ('Ride', 'cycling'), ('VirtualRide', 'cycling'), ('IndoorCycling', 'cycling'),
        ('Run', 'running'), ('TrailRun', 'running'),
        ('Swim', None), ('Hike', None), ('', None),
    ]
    for type_key, expected in cases:
        got = activity_label(type_key)
        assert got == expected, f'{type_key!r}: expected {expected!r}, got {got!r}'
    print('  test_activity_label            PASS')


def check_real_env():
    """Not a unit test — reports whether the real credentials file is usable."""
    print(f'\nReal .env at {ENV_PATH}: ', end='')
    if not ENV_PATH.exists():
        print('MISSING')
        return
    env = load_env(ENV_PATH)
    have_key = bool(env.get('ICU_API_KEY'))
    have_id  = bool(env.get('ICU_ATHLETE_ID'))
    print(f'found (ICU_API_KEY {"set" if have_key else "MISSING"}, '
          f'ICU_ATHLETE_ID={env.get("ICU_ATHLETE_ID") if have_id else "MISSING"})')


if __name__ == '__main__':
    test_load_env()
    test_activity_label()
    check_real_env()
    print('\nAll tests passed.')

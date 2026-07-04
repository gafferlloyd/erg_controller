"""Smoke tests for strava_auth.py.

Run from project root:
  python debug/test_strava_auth.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strava_auth import load_env, save_env, ENV_PATH


def test_load_env_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'test.env'
        path.write_text('# comment\n\nSTRAVA_CLIENT_ID=123\nSTRAVA_ACCESS_TOKEN=abc \n')
        env = load_env(path)
        assert env == {'STRAVA_CLIENT_ID': '123', 'STRAVA_ACCESS_TOKEN': 'abc'}, env
    print('  test_load_env_roundtrip        PASS')


def test_save_env_atomic_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'test.env'
        save_env({'STRAVA_ACCESS_TOKEN': 'new_token', 'STRAVA_REFRESH_TOKEN': 'new_refresh'}, path)
        assert load_env(path) == {'STRAVA_ACCESS_TOKEN': 'new_token', 'STRAVA_REFRESH_TOKEN': 'new_refresh'}
        # No leftover temp files
        leftovers = [p for p in Path(d).iterdir() if p.name != 'test.env']
        assert not leftovers, leftovers
    print('  test_save_env_atomic_roundtrip  PASS')


def check_real_env():
    """Not a unit test -- reports which real credential keys are present, never values."""
    print(f'\nReal .env at {ENV_PATH}: ', end='')
    if not ENV_PATH.exists():
        print('MISSING')
        return
    env = load_env(ENV_PATH)
    keys = ['STRAVA_CLIENT_ID', 'STRAVA_CLIENT_SECRET', 'STRAVA_ACCESS_TOKEN', 'STRAVA_REFRESH_TOKEN']
    present = {k: (k in env and bool(env[k])) for k in keys}
    print(present)


if __name__ == '__main__':
    test_load_env_roundtrip()
    test_save_env_atomic_roundtrip()
    check_real_env()
    print('\nAll tests passed.')

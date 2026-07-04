"""Smoke tests for signal_notify.py -- mocks subprocess, never actually calls
signal-cli (which may not even be installed/linked yet).

Run from project root:
  python debug/test_signal_notify.py
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from signal_notify import send, load_phone_number, ENV_PATH


def test_load_phone_number():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'signal.env'
        path.write_text('# comment\nSIGNAL_PHONE_NUMBER=+491234567\n')
        assert load_phone_number(path) == '+491234567'
    print('  test_load_phone_number              PASS')


def test_load_phone_number_missing_raises():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'signal.env'
        path.write_text('SOMETHING_ELSE=1\n')
        try:
            load_phone_number(path)
            assert False, 'expected ValueError'
        except ValueError:
            pass
    print('  test_load_phone_number_missing_raises  PASS')


def test_send_success():
    proc = MagicMock(returncode=0, stderr='')
    with patch('subprocess.run', return_value=proc) as m:
        send('hello', phone_number='+491234567')
        args = m.call_args[0][0]
        assert args[:2] == ['signal-cli', '-a'], args
        assert '+491234567' in args
        assert 'hello' in args
    print('  test_send_success                   PASS')


def test_send_failure_raises():
    proc = MagicMock(returncode=1, stderr='some signal-cli error')
    with patch('subprocess.run', return_value=proc):
        try:
            send('hello', phone_number='+491234567')
            assert False, 'expected RuntimeError'
        except RuntimeError as e:
            assert 'some signal-cli error' in str(e)
    print('  test_send_failure_raises             PASS')


def check_real_setup():
    """Not a unit test -- reports whether the real signal.env is present."""
    print(f'\nReal config at {ENV_PATH}: ', end='')
    print('found' if ENV_PATH.exists() else 'MISSING (manual setup not done yet)')


if __name__ == '__main__':
    test_load_phone_number()
    test_load_phone_number_missing_raises()
    test_send_success()
    test_send_failure_raises()
    check_real_setup()
    print('\nAll tests passed.')

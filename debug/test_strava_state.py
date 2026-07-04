"""Smoke tests for strava_state.py.

Run from project root:
  python debug/test_strava_state.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strava_state import load_processed, mark_sent, record_attempt, should_skip, MAX_ATTEMPTS


def test_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'nested' / 'state.json'
        assert load_processed(path) == {}
    print('  test_missing_file_returns_empty     PASS')


def test_corrupt_file_returns_empty_not_fatal():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'state.json'
        path.write_text('{not valid json')
        assert load_processed(path) == {}
    print('  test_corrupt_file_returns_empty_not_fatal  PASS')


def test_mark_sent_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'state.json'
        mark_sent(12345, path)
        state = load_processed(path)
        assert state['12345']['status'] == 'sent', state
        assert should_skip(12345, state)
    print('  test_mark_sent_roundtrip            PASS')


def test_attempt_counter_caps_out():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'state.json'
        for _ in range(MAX_ATTEMPTS - 1):
            record_attempt(999, path)
            assert not should_skip(999, load_processed(path))
        record_attempt(999, path)  # reaches MAX_ATTEMPTS
        assert should_skip(999, load_processed(path))
    print('  test_attempt_counter_caps_out        PASS')


def test_unknown_activity_not_skipped():
    assert not should_skip(1, {})
    print('  test_unknown_activity_not_skipped   PASS')


if __name__ == '__main__':
    test_missing_file_returns_empty()
    test_corrupt_file_returns_empty_not_fatal()
    test_mark_sent_roundtrip()
    test_attempt_counter_caps_out()
    test_unknown_activity_not_skipped()
    print('\nAll tests passed.')

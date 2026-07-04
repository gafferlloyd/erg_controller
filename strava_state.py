"""Local processed-activity cache -- the sole idempotency mechanism (no
Strava-side marker to fall back on, since this integration never writes
back to Strava). Not a secret; gitignored only to avoid noisy machine-
specific diffs in a public repo.
"""
from __future__ import annotations
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path(__file__).parent / 'state' / 'processed_activities.json'
MAX_ATTEMPTS = 3


def load_processed(path: Path = STATE_PATH) -> dict:
    """Returns {} on missing or corrupt file -- never fatal, just re-evaluates
    every candidate activity (the designed self-healing fallback)."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix='.state_')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


def mark_sent(activity_id: int, path: Path = STATE_PATH) -> None:
    state = load_processed(path)
    state[str(activity_id)] = {
        'status': 'sent',
        'sent_at': datetime.now(timezone.utc).isoformat(),
    }
    _save(state, path)


def record_attempt(activity_id: int, path: Path = STATE_PATH) -> int:
    """Increment the failure-attempt count for an activity. Returns the new count."""
    state = load_processed(path)
    entry = state.get(str(activity_id), {'status': 'failed', 'attempts': 0})
    entry['attempts'] = entry.get('attempts', 0) + 1
    entry['status'] = 'failed'
    entry['last_attempt_at'] = datetime.now(timezone.utc).isoformat()
    state[str(activity_id)] = entry
    _save(state, path)
    return entry['attempts']


def should_skip(activity_id: int, state: dict, max_attempts: int = MAX_ATTEMPTS) -> bool:
    """True if already sent, or has exceeded the failure-attempt cap (give up)."""
    entry = state.get(str(activity_id))
    if entry is None:
        return False
    if entry.get('status') == 'sent':
        return True
    return entry.get('attempts', 0) >= max_attempts

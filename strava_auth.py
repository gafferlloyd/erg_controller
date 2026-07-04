"""Strava OAuth credential loading and refresh.

Credentials live at /home/gareth/strava.env (STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET,
STRAVA_ACCESS_TOKEN, STRAVA_REFRESH_TOKEN) -- never copied into this repo.

Strava issues a NEW refresh_token on every refresh and invalidates the old one
immediately, so the rotated pair must be persisted right after every refresh call.
"""
from __future__ import annotations
import os
import tempfile
from pathlib import Path

import requests

ENV_PATH = Path.home() / 'strava.env'
TOKEN_URL = 'https://www.strava.com/oauth/token'


def load_env(path: Path = ENV_PATH) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()
    return env


def save_env(env: dict, path: Path = ENV_PATH) -> None:
    """Atomic write: temp file in the same directory, then os.replace()."""
    lines = [f'{k}={v}' for k, v in env.items()]
    text = '\n'.join(lines) + '\n'
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix='.strava_env_')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


def refresh_access_token(env: dict) -> dict:
    """POST a refresh_token grant. Returns the new token fields (not yet persisted)."""
    resp = requests.post(TOKEN_URL, data={
        'client_id': env['STRAVA_CLIENT_ID'],
        'client_secret': env['STRAVA_CLIENT_SECRET'],
        'grant_type': 'refresh_token',
        'refresh_token': env['STRAVA_REFRESH_TOKEN'],
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()


def refresh_and_save(env: dict, path: Path = ENV_PATH) -> dict:
    """Refresh, merge the new access/refresh token into env, and persist atomically."""
    data = refresh_access_token(env)
    env = dict(env)
    env['STRAVA_ACCESS_TOKEN'] = data['access_token']
    env['STRAVA_REFRESH_TOKEN'] = data['refresh_token']
    save_env(env, path)
    return env

"""Send a message via signal-cli to your own Note-to-Self.

signal-cli must already be linked as a secondary device to your Signal
account (see the manual setup step in docs/ -- this cannot be automated,
it needs you to scan a QR code with your phone once).

Phone number lives in /home/gareth/signal.env (SIGNAL_PHONE_NUMBER=+...),
outside the repo -- same convention as strava.env / intervals.icu's .env.
"""
from __future__ import annotations
import subprocess
from pathlib import Path

ENV_PATH = Path.home() / 'signal.env'
SIGNAL_CLI = 'signal-cli'
TIMEOUT_S = 30


def load_phone_number(path: Path = ENV_PATH) -> str:
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith('SIGNAL_PHONE_NUMBER='):
            return line.split('=', 1)[1].strip()
    raise ValueError(f'SIGNAL_PHONE_NUMBER not found in {path}')


def send(message: str, phone_number: str | None = None) -> None:
    """Send `message` to your own Note-to-Self (sending to your own number)."""
    if phone_number is None:
        phone_number = load_phone_number()
    result = subprocess.run(
        [SIGNAL_CLI, '-a', phone_number, 'send', '-m', message, phone_number],
        capture_output=True, text=True, timeout=TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(f'signal-cli send failed (exit {result.returncode}): {result.stderr.strip()}')

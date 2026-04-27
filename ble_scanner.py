"""Shared BLE scan serialiser — BlueZ allows only one active scan at a time.

Import find_device() in place of BleakScanner.find_device_by_filter() so that
multiple BLE clients (KICKR, HR monitors) do not race for the radio.
"""
import asyncio
from bleak import BleakScanner

_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def find_device(filter_fn, timeout: float = 30.0):
    """Run a BLE scan exclusively — waits for any in-progress scan to finish."""
    async with _get_lock():
        return await BleakScanner.find_device_by_filter(filter_fn, timeout=timeout)

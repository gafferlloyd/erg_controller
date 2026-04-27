#!/usr/bin/env python3
"""Manual test: scan for KICKR via BLE and print notifications.

Usage:
  python debug/test_kickr_ble.py
  python debug/test_kickr_ble.py --name "KICKR BIKE SHIFT"

Press Ctrl-C to stop.
"""
import asyncio, sys, logging
sys.path.insert(0, '.')
from ble_kickr import BleKickrClient

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s  %(message)s')

async def on_notify(uuid, data):
    print(f'  NOTIFY {uuid[-8:]}  {data.hex()}')

async def on_connected(name):
    print(f'>>> KICKR connected: {name}')

async def on_disconnected():
    print('>>> KICKR disconnected')

async def main():
    hints = sys.argv[1:] or None
    client = BleKickrClient(on_notify, name_hints=hints,
                            on_connected=on_connected,
                            on_disconnected=on_disconnected)
    await client.run()

asyncio.run(main())

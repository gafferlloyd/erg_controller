#!/usr/bin/env python3
"""Standalone test for ble_hr.py — scans for HR monitors and prints raw data.

Usage:
    python debug/test_ble_hr.py                    # connect to any HR device
    python debug/test_ble_hr.py Fenix CB100        # prefer named devices
    python debug/test_ble_hr.py --scan-only        # list nearby BLE devices

Run from the erg_controller directory so ble_hr imports correctly.
"""

import asyncio, sys, logging
sys.path.insert(0, '.')
from ble_hr import BleHrClient, HR_SERVICE, HR_MEASUREMENT

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s  %(message)s')
log = logging.getLogger('test_ble_hr')


def parse_hr(data: bytes) -> dict:
    """Parse HR Measurement characteristic (0x2A37) into a dict."""
    flags = data[0]
    hr_16bit = bool(flags & 0x01)
    has_energy = bool(flags & 0x08)
    has_rr = bool(flags & 0x10)
    offset = 1
    if hr_16bit:
        bpm = int.from_bytes(data[offset:offset+2], 'little')
        offset += 2
    else:
        bpm = data[offset]
        offset += 1
    result = {'bpm': bpm, 'flags': f'0x{flags:02x}'}
    if has_energy:
        result['energy_kJ'] = int.from_bytes(data[offset:offset+2], 'little')
        offset += 2
    if has_rr:
        rr_intervals = []
        while offset + 1 < len(data):
            rr = int.from_bytes(data[offset:offset+2], 'little')
            rr_intervals.append(round(rr / 1024 * 1000, 1))  # convert to ms
            offset += 2
        result['rr_ms'] = rr_intervals
    return result


async def on_notify(uuid: str, data: bytes):
    short = uuid.replace('-', '').lower()[4:8]
    if short == '2a37':
        parsed = parse_hr(data)
        print(f'HR  raw={data.hex()}  {parsed}')
    else:
        print(f'UUID {uuid[-8:]}  raw={data.hex()}')


async def scan_only():
    """Print all BLE devices visible right now."""
    from bleak import BleakScanner
    log.info('Scanning for 10 s…')
    devices = await BleakScanner.discover(timeout=10.0)
    hr_devs = []
    for d in sorted(devices, key=lambda x: x.name or ''):
        adv = d.details.get('props', {})
        uuids = getattr(d, 'metadata', {}).get('uuids', [])
        is_hr = HR_SERVICE in uuids
        flag = ' ← HR' if is_hr else ''
        print(f'  {d.address}  RSSI={d.rssi:4d}  {d.name}{flag}')
        if is_hr:
            hr_devs.append(d)
    print(f'\nFound {len(devices)} devices, {len(hr_devs)} with HR service')


async def main():
    args = sys.argv[1:]
    if '--scan-only' in args:
        await scan_only()
        return

    hints = [a for a in args if not a.startswith('-')]
    log.info('Hints: %s  (empty = any HR device)', hints or '(none)')
    client = BleHrClient(on_notify, hints or None)

    # Run for 60 s then exit (avoids hanging in test context).
    try:
        await asyncio.wait_for(client.run(), timeout=60.0)
    except asyncio.TimeoutError:
        log.info('60 s test window complete')


if __name__ == '__main__':
    asyncio.run(main())

"""BLE HR monitor client — auto-scan, connect, reconnect.

Imported by dircon_bridge.py. Scans for any device advertising the standard
HR service (0x180D). Pass name_hints to prefer specific devices by name prefix
(e.g. ['Fenix', 'CB100']).
"""

import asyncio, logging
from bleak import BleakScanner, BleakClient

HR_SERVICE     = '0000180d-0000-1000-8000-00805f9b34fb'
HR_MEASUREMENT = '00002a37-0000-1000-8000-00805f9b34fb'

SCAN_TIMEOUT = 30.0   # seconds per scan attempt
RETRY_DELAY  = 10.0   # seconds between reconnect attempts

log = logging.getLogger('dircon.hr')


class BleHrClient:
    """Continuously scans for, connects to, and streams a BLE HR monitor.

    on_notify  : async callable(uuid: str, data: bytes)
    name_hints : list[str] — device name prefixes to prefer (case-insensitive).
                 Empty → connect to first device advertising HR service.
    """

    def __init__(self, on_notify, name_hints=None):
        self._on_notify  = on_notify
        self._hints      = [h.lower() for h in (name_hints or [])]
        self.device_name = None   # set while connected

    async def run(self):
        while True:
            try:
                await self._scan_and_run()
            except Exception as e:
                log.warning('HR: %s — retry in %.0fs', e, RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)

    async def _scan_and_run(self):
        log.info('HR: scanning (%.0fs)…', SCAN_TIMEOUT)
        device = await BleakScanner.find_device_by_filter(
            self._matches, timeout=SCAN_TIMEOUT,
        )
        if device is None:
            log.info('HR: no device found')
            return

        log.info('HR: found %s (%s)', device.name, device.address)
        disconnected = asyncio.Event()

        async with BleakClient(
            device,
            disconnected_callback=lambda _: disconnected.set(),
        ) as client:
            await client.start_notify(HR_MEASUREMENT, self._on_data)
            self.device_name = device.name
            log.info('HR: connected — %s', device.name)
            await disconnected.wait()

        log.info('HR: %s disconnected', self.device_name)
        self.device_name = None

    def _matches(self, device, adv):
        if not self._hints:
            return HR_SERVICE in (adv.service_uuids or [])
        name = (device.name or '').lower()
        return any(name.startswith(h) for h in self._hints)

    async def _on_data(self, _char, data: bytearray):
        await self._on_notify(HR_MEASUREMENT, bytes(data))

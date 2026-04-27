"""BLE KICKR client — auto-scan, connect, reconnect.

Imported by dircon_bridge.py. Scans for any device advertising FTMS (0x1826)
or CPS (0x1818), preferring names starting with 'KICKR'. Pass name_hints to
restrict to specific prefixes.
"""

import asyncio, logging
from bleak import BleakScanner, BleakClient

FTMS_SERVICE     = '00001826-0000-1000-8000-00805f9b34fb'
CPS_SERVICE      = '00001818-0000-1000-8000-00805f9b34fb'
INDOOR_BIKE_DATA = '00002ad2-0000-1000-8000-00805f9b34fb'
FTMS_CP          = '00002ad9-0000-1000-8000-00805f9b34fb'
MACHINE_STATUS   = '00002ada-0000-1000-8000-00805f9b34fb'
CPS_MEASUREMENT  = '00002a63-0000-1000-8000-00805f9b34fb'

_NOTIFY_UUIDS = [INDOOR_BIKE_DATA, MACHINE_STATUS, FTMS_CP, CPS_MEASUREMENT]
_TRAINER_SERVICES = {FTMS_SERVICE, CPS_SERVICE}

SCAN_TIMEOUT = 30.0
RETRY_DELAY  = 10.0

log = logging.getLogger('dircon.kickr')


class BleKickrClient:
    """Continuously scans for, connects to, and streams a BLE KICKR trainer.

    on_notify      : async callable(uuid: str, data: bytes)
    name_hints     : list[str] — device name prefixes to match (case-insensitive).
                     Defaults to ['kickr'].
    on_connected   : async callable(device_name: str) or None
    on_disconnected: async callable() or None
    """

    def __init__(self, on_notify, name_hints=None,
                 on_connected=None, on_disconnected=None):
        self._on_notify       = on_notify
        self._hints           = [h.lower() for h in (name_hints or ['kickr'])]
        self._on_connected    = on_connected
        self._on_disconnected = on_disconnected
        self.device_name      = None   # set while connected
        self._client          = None   # BleakClient while connected

    async def run(self):
        while True:
            try:
                await self._scan_and_run()
            except Exception as e:
                log.warning('KICKR: %s — retry in %.0fs', e, RETRY_DELAY)
            if self.device_name is not None:
                self.device_name = None
                if self._on_disconnected:
                    await self._on_disconnected()
            await asyncio.sleep(RETRY_DELAY)

    async def _scan_and_run(self):
        log.info('KICKR: scanning (%.0fs)…', SCAN_TIMEOUT)
        device = await BleakScanner.find_device_by_filter(
            self._matches, timeout=SCAN_TIMEOUT,
        )
        if device is None:
            log.info('KICKR: no device found')
            return

        log.info('KICKR: found %s (%s)', device.name, device.address)
        disconnected = asyncio.Event()

        async with BleakClient(
            device,
            disconnected_callback=lambda _: disconnected.set(),
        ) as client:
            self._client = client
            for uuid in _NOTIFY_UUIDS:
                try:
                    await client.start_notify(uuid, self._on_data)
                except Exception as e:
                    log.debug('KICKR: start_notify %s skipped: %s', uuid[-8:], e)

            self.device_name = device.name
            log.info('KICKR: connected — %s', device.name)
            if self._on_connected:
                await self._on_connected(device.name)

            await disconnected.wait()

        self._client = None
        log.info('KICKR: %s disconnected', self.device_name)
        if self.device_name is not None:
            self.device_name = None
            if self._on_disconnected:
                await self._on_disconnected()

    def _matches(self, device, adv):
        name = (device.name or '').lower()
        if any(name.startswith(h) for h in self._hints):
            return True
        return bool(_TRAINER_SERVICES & set(adv.service_uuids or []))

    async def _on_data(self, char, data: bytearray):
        await self._on_notify(str(char.uuid), bytes(data))

    async def write_cp(self, data: bytes):
        """Write to FTMS Control Point (ERG targets, handshake, etc.)."""
        if self._client is None or not self._client.is_connected:
            raise RuntimeError('KICKR not connected')
        await self._client.write_gatt_char(FTMS_CP, data, response=True)

"""DIRCON protocol client — connects to a real Wahoo KICKR trainer over TCP."""

import asyncio, struct, logging

log = logging.getLogger('dircon')

# ── Protocol constants ────────────────────────────────────────────────────────

DIRCON_PORT  = 36866
MSG_DISC_SVC = 0x01
MSG_DISC_CHR = 0x02
MSG_READ     = 0x03
MSG_WRITE    = 0x04
MSG_SUB      = 0x05
MSG_NOTIFY   = 0x06
HDR_LEN      = 6

BLE_BASE  = '0000{:04x}-0000-1000-8000-00805f9b34fb'
AUTO_SUBS = ['2ad2', '2ada']   # Indoor Bike Data, Machine Status

# ── UUID helpers ──────────────────────────────────────────────────────────────

def expand(u: str) -> str:
    """Expand a short or full UUID string to canonical 8-4-4-4-12 form."""
    u = u.lower().strip().replace('-', '')
    if len(u) <= 8:
        return BLE_BASE.format(int(u, 16))
    h = u.zfill(32)
    return f'{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}'

def u2b(u: str) -> bytes:
    return bytes.fromhex(expand(u).replace('-', ''))

def b2u(b: bytes) -> str:
    h = b.hex()
    return f'{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}'

# ── DIRCON TCP client ─────────────────────────────────────────────────────────

class DirconClient:
    """Speaks the DIRCON/WFTNP protocol over a raw TCP socket.

    All request-response operations are serialised by _lock so that
    notifications arriving mid-request go through _read_loop cleanly
    without corrupting the pending response future.
    """

    def __init__(self, host: str, port: int = DIRCON_PORT):
        self.host, self.port = host, port
        self._r = self._w = None
        self._lock    = asyncio.Lock()
        self._pending = None                # asyncio.Future | None
        self._seq     = 0
        self.on_notify = None               # async (uuid_str, bytes) → None

    async def connect(self):
        self._r, self._w = await asyncio.open_connection(self.host, self.port)
        asyncio.create_task(self._read_loop())
        log.info('TCP connected → %s:%d', self.host, self.port)

    async def _send_recv(self, mtype: int, data: bytes = b'',
                         timeout: float = 5.0) -> bytes:
        async with self._lock:
            self._seq = (self._seq + 1) & 0xFF
            self._pending = asyncio.get_running_loop().create_future()
            pkt = struct.pack('>BBBBH', 0x01, mtype, self._seq, 0, len(data)) + data
            self._w.write(pkt)
            await self._w.drain()
            try:
                return await asyncio.wait_for(self._pending, timeout)
            except asyncio.TimeoutError:
                log.warning('msg type 0x%02x timed out', mtype)
                return b''

    async def _read_loop(self):
        try:
            while True:
                hdr  = await self._r.readexactly(HDR_LEN)
                _, mt, _, resp, dlen = struct.unpack_from('>BBBBH', hdr)
                body = await self._r.readexactly(dlen) if dlen else b''
                log.debug('rx  mt=0x%02x resp=0x%02x len=%d', mt, resp, dlen)
                if mt == MSG_NOTIFY and len(body) >= 16:
                    if self.on_notify:
                        asyncio.create_task(
                            self.on_notify(b2u(body[:16]), body[16:]))
                elif self._pending and not self._pending.done():
                    if resp:
                        self._pending.set_exception(
                            RuntimeError(f'DIRCON error resp=0x{resp:02x}'))
                    else:
                        self._pending.set_result(body)
        except asyncio.IncompleteReadError:
            log.warning('DIRCON TCP connection closed')
        except Exception as e:
            log.error('read loop: %s', e)
        finally:
            if self._pending and not self._pending.done():
                self._pending.cancel()

    async def raw_request(self, mt: int, data: bytes = b'') -> bytes:
        """Forward a raw DIRCON request to the KICKR; return raw response body."""
        return await self._send_recv(mt, data)

    async def discover_services(self) -> list:
        d = await self._send_recv(MSG_DISC_SVC)
        return [b2u(d[i:i+16]) for i in range(0, len(d), 16) if i + 16 <= len(d)]

    async def subscribe(self, uuid: str, enable: bool = True):
        log.info('subscribe %s  enable=%s', uuid, enable)
        await self._send_recv(MSG_SUB,
            u2b(uuid) + bytes([0x01 if enable else 0x00]))

    async def write(self, uuid: str, value: bytes):
        log.debug('write %s = %s', uuid, value.hex())
        await self._send_recv(MSG_WRITE, u2b(uuid) + value)

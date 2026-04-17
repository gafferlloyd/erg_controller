#!/usr/bin/env python3
"""DIRCON ↔ WebSocket bridge for Wahoo KICKR trainers.

Discovers the KICKR on the local network via mDNS, connects via the
DIRCON protocol (TCP port 36866), and exposes a local WebSocket server
so a browser page can send/receive GATT characteristic traffic over
WiFi instead of Web Bluetooth.

Install:  pip install websockets zeroconf
Run:      python dircon_bridge.py [--host KICKR_IP] [--ws-port 8765] [-v]

JSON protocol — client → bridge:
  {"cmd":"subscribe", "uuid":"2ad2"}
  {"cmd":"write",     "uuid":"2ad9", "data":[0x00]}
  {"cmd":"discover"}

JSON protocol — bridge → client:
  {"type":"status",   "connected":true, "kickr":"192.168.x.x"}
  {"type":"services", "list":["00001826-..."]}
  {"type":"notify",   "uuid":"00002ad2-...", "data":[...]}
  {"type":"error",    "message":"..."}
"""

import asyncio, struct, json, logging, argparse
import websockets
from websockets.server import serve

log = logging.getLogger('dircon')

# ── Constants ─────────────────────────────────────────────────────────────────

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

    All request-response operations are serialised by _lock so that a
    notification arriving mid-request goes through _read_loop cleanly
    without interfering with the pending response future.
    """

    def __init__(self, host: str, port: int = DIRCON_PORT):
        self.host, self.port = host, port
        self._r = self._w = None
        self._lock    = asyncio.Lock()          # one request-response in flight
        self._pending = None                    # asyncio.Future | None
        self._seq     = 0
        self.on_notify = None                   # async (uuid_str, bytes) → None

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
                log.warning('msg type 0x%02x timed out — server may not ACK this op',
                            mtype)
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

# ── mDNS discovery ────────────────────────────────────────────────────────────

async def discover_kickr(timeout: float = 8.0):
    """Return the KICKR's IP address via mDNS, or None if not found."""
    try:
        from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
        import socket
        found, addr = asyncio.Event(), [None]

        class H:
            def add_service(self, zc, t, n):
                info = zc.get_service_info(t, n)
                if info and info.addresses:
                    addr[0] = socket.inet_ntoa(info.addresses[0])
                    found.set()
            def remove_service(self, *_): pass
            def update_service(self, *_): pass

        async with AsyncZeroconf() as azc:
            b = AsyncServiceBrowser(azc.zeroconf,
                '_wahoo-fitness-tnp._tcp.local.', H())
            try:
                await asyncio.wait_for(found.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            await b.async_cancel()
        return addr[0]
    except ImportError:
        log.warning('pip install zeroconf  for auto-discovery')
        return None

# ── WebSocket bridge ──────────────────────────────────────────────────────────

class Bridge:
    def __init__(self, dc: DirconClient):
        self._dc = dc
        self._clients   = set()
        self._subscribed = set()

    async def setup(self):
        try:
            svcs = await self._dc.discover_services()
            log.info('DIRCON services: %s', svcs or '(none / parse error)')
        except Exception as e:
            log.warning('discover_services: %s — continuing anyway', e)

        for uuid in AUTO_SUBS:
            try:
                await self._dc.subscribe(uuid)
                self._subscribed.add(expand(uuid))
            except Exception as e:
                log.warning('auto-subscribe %s: %s', uuid, e)

        self._dc.on_notify = self._broadcast

    async def _broadcast(self, uuid: str, data: bytes):
        if not self._clients:
            return
        msg = json.dumps({'type': 'notify', 'uuid': uuid, 'data': list(data)})
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def handle_ws(self, ws):
        self._clients.add(ws)
        await ws.send(json.dumps(
            {'type': 'status', 'connected': True, 'kickr': self._dc.host}))
        log.info('WS client connected  (total: %d)', len(self._clients))
        try:
            async for raw in ws:
                try:
                    await self._cmd(ws, json.loads(raw))
                except Exception as e:
                    await ws.send(json.dumps({'type': 'error', 'message': str(e)}))
        finally:
            self._clients.discard(ws)
            log.info('WS client disconnected (total: %d)', len(self._clients))

    async def _cmd(self, ws, msg: dict):
        cmd = msg.get('cmd')
        if cmd == 'discover':
            svcs = await self._dc.discover_services()
            await ws.send(json.dumps({'type': 'services', 'list': svcs}))
        elif cmd == 'subscribe':
            u = expand(msg['uuid'])
            if u not in self._subscribed:
                await self._dc.subscribe(u)
                self._subscribed.add(u)
        elif cmd == 'write':
            await self._dc.write(msg['uuid'], bytes(msg['data']))

# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    ap = argparse.ArgumentParser(description='DIRCON WebSocket bridge')
    ap.add_argument('--host',    default=None, help='KICKR IP (skip mDNS)')
    ap.add_argument('--ws-port', type=int, default=8765)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s  %(message)s')

    host = args.host
    if not host:
        log.info('Searching for KICKR via mDNS (up to 8 s)…')
        host = await discover_kickr()
    if not host:
        log.error('KICKR not found.  Retry with --host <IP_ADDRESS>')
        return

    log.info('Using KICKR at %s', host)
    dc = DirconClient(host)
    await dc.connect()

    bridge = Bridge(dc)
    await bridge.setup()

    log.info('WebSocket server ready  →  ws://localhost:%d', args.ws_port)
    async with serve(bridge.handle_ws, 'localhost', args.ws_port):
        await asyncio.Future()   # run until Ctrl-C

if __name__ == '__main__':
    asyncio.run(main())

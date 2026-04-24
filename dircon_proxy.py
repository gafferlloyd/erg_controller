"""DIRCON proxy server — accepts MyWhoosh connections, forwards all traffic.

Imported by dircon_bridge.py; not run directly.

What it does:
  - Listens on TCP port 36866 (the standard DIRCON port) so MyWhoosh can
    discover and connect to it instead of the real KICKR.
  - Proxies all DIRCON traffic transparently to/from the real KICKR via a
    DirconClient (MyWhoosh → KICKR: full passthrough, nothing blocked).
  - Broadcasts all KICKR notifications to every connected DIRCON client.
    The power field in 2AD2 notifications is remapped by the caller
    (Bridge._on_notify) before broadcast; all other data is unchanged.
  - Registers the proxy on the local network via mDNS so MyWhoosh can find
    it by name just like a real trainer.
"""

import asyncio, struct, logging, socket
from dataclasses import dataclass, field
from dircon_client import (
    DirconClient,
    MSG_DISC_SVC, MSG_DISC_CHR, MSG_READ, MSG_WRITE, MSG_SUB, MSG_NOTIFY,
    HDR_LEN, u2b, b2u,
)

log = logging.getLogger('dircon.proxy')

# ── Per-connection state ──────────────────────────────────────────────────────

@dataclass(eq=False)
class _Client:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    addr: tuple = field(default_factory=tuple)

# ── Proxy server ──────────────────────────────────────────────────────────────

class DirconProxyServer:

    def __init__(self, dc: DirconClient):
        self._dc = dc
        self._clients: set = set()

    async def start(self, port: int = 36866):
        srv = await asyncio.start_server(self._accept, '0.0.0.0', port)
        log.info('DIRCON proxy listening on 0.0.0.0:%d', port)
        return srv

    async def _accept(self, reader, writer):
        addr = writer.get_extra_info('peername')
        log.info('DIRCON client connected from %s', addr)
        c = _Client(reader, writer, addr)
        self._clients.add(c)
        try:
            await self._serve(c)
        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            log.error('DIRCON client %s error: %s', addr, e)
        finally:
            self._clients.discard(c)
            try:
                writer.close()
            except Exception:
                pass
            log.info('DIRCON client disconnected: %s', addr)

    async def _serve(self, c: _Client):
        while True:
            hdr  = await c.reader.readexactly(HDR_LEN)
            _, mt, seq, _, dlen = struct.unpack_from('>BBBBH', hdr)
            body = await c.reader.readexactly(dlen) if dlen else b''
            await self._handle(c, mt, seq, body)

    async def _handle(self, c: _Client, mt: int, seq: int, body: bytes):
        try:
            if mt in (MSG_DISC_SVC, MSG_DISC_CHR):
                resp = await self._dc.raw_request(mt, body)
                label = 'DISC_SVC' if mt == MSG_DISC_SVC else 'DISC_CHR'
                log.info('CAPTURE %s req  body=%s', label, body.hex() if body else '(empty)')
                log.info('CAPTURE %s resp (%d bytes): %s', label, len(resp), resp.hex())
                self._send(c.writer, mt, seq, resp)

            elif mt == MSG_READ:
                resp = await self._dc.raw_request(mt, body)
                uuid = b2u(body[:16]) if len(body) >= 16 else '?'
                log.info('CAPTURE READ  uuid=%s  resp=%s', uuid, resp.hex() if resp else '(empty)')
                self._send(c.writer, mt, seq, resp)

            elif mt == MSG_SUB:
                uuid  = b2u(body[:16]) if len(body) >= 16 else '?'
                flag  = body[16] if len(body) > 16 else 1
                log.info('CAPTURE SUB  uuid=%s  enable=%d', uuid, flag)
                self._send(c.writer, mt, seq, b'')

            elif mt == MSG_WRITE:
                uuid    = b2u(body[:16]) if len(body) >= 16 else '?'
                payload = body[16:] if len(body) > 16 else b''
                log.info('CAPTURE WRITE  uuid=%s  payload=%s', uuid, payload.hex())
                if len(body) >= 16:
                    await self._dc.write(b2u(body[:16]), payload)
                self._send(c.writer, mt, seq, b'')

            else:
                log.info('CAPTURE UNKNOWN  mt=0x%02x  body=%s', mt, body.hex() if body else '(empty)')
                self._send(c.writer, mt, seq, b'')

        except Exception as e:
            log.error('handle mt=0x%02x from %s: %s', mt, c.addr, e)

    # ── Wire helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _send(writer, mt: int, seq: int, data: bytes):
        writer.write(struct.pack('>BBBBH', 0x01, mt, seq, 0, len(data)) + data)

    @staticmethod
    def _notify(writer, uuid: str, data: bytes):
        payload = u2b(uuid) + data
        writer.write(struct.pack('>BBBBH', 0x01, MSG_NOTIFY, 0, 0, len(payload)) + payload)

    # ── Broadcast KICKR notifications to all connected DIRCON clients ─────────

    async def broadcast(self, uuid: str, data: bytes):
        if not self._clients:
            return
        log.info('CAPTURE NOTIFY uuid=%s data=%s', uuid, data.hex())
        payload = u2b(uuid) + data
        pkt = struct.pack('>BBBBH', 0x01, MSG_NOTIFY, 0, 0, len(payload)) + payload
        dead = set()
        for c in self._clients:
            try:
                c.writer.write(pkt)
                await c.writer.drain()
            except Exception:
                dead.add(c)
        self._clients -= dead

# ── mDNS advertisement ────────────────────────────────────────────────────────

def get_local_ip() -> str:
    """Return this machine's LAN IP (the address the iPad can reach)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    finally:
        s.close()

async def register_mdns(name: str, port: int, properties: dict = None, ip: str = None) -> object:
    """Advertise 'name' as a DIRCON trainer on the local network via mDNS.

    Pass the real KICKR's TXT properties so MyWhoosh recognises the proxy
    as a valid Wahoo trainer (it checks ble-service-uuids etc.).

    Returns the AsyncZeroconf instance — keep the reference alive for the
    duration of the programme; call await zc.async_close() on shutdown.

    Uses IPv4-only mode (more reliable on Windows where the IPv6 mDNS
    socket often fails to bind). Uses AsyncZeroconf to avoid EventLoopBlocked
    when called from inside an asyncio event loop (Python 3.13+).
    """
    from zeroconf import ServiceInfo
    from zeroconf.asyncio import AsyncZeroconf
    ip = ip or get_local_ip()
    info = ServiceInfo(
        '_wahoo-fitness-tnp._tcp.local.',
        f'{name}._wahoo-fitness-tnp._tcp.local.',
        addresses=[socket.inet_aton(ip)],
        port=port,
        properties=properties or {},
    )
    try:
        from zeroconf import IPVersion
        azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    except Exception:
        azc = AsyncZeroconf()
    await azc.async_register_service(info, strict=False)
    log.info('mDNS: advertising "%s" at %s:%d', name, ip, port)
    return azc

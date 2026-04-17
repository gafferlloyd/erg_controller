"""DIRCON proxy server — accepts MyWhoosh connections, filters gradient commands.

Imported by dircon_bridge.py; not run directly.

What it does:
  - Listens on TCP port 36866 (the standard DIRCON port) so MyWhoosh can
    discover and connect to it instead of the real KICKR.
  - Proxies all DIRCON traffic transparently to/from the real KICKR via a
    DirconClient — with one exception:
      FTMS op 0x11 (Set Indoor Bike Simulation / gradient + wind)
      is intercepted and a fake success response is returned to the caller.
      The command is never forwarded to the KICKR, so ERG servo control
      from index.html is not disrupted by MyWhoosh gradient changes.
  - Broadcasts all KICKR notifications (power, cadence, speed, etc.) to
    every connected DIRCON client so MyWhoosh sees live data.
  - Registers the proxy on the local network via mDNS so MyWhoosh can find
    it by name ("LloydLabs TRNR") just like a real trainer.

Windows firewall note: allow inbound TCP on port 36866 for Python.
"""

import asyncio, struct, logging, socket
from dataclasses import dataclass, field
from dircon_client import (
    DirconClient,
    MSG_DISC_SVC, MSG_DISC_CHR, MSG_WRITE, MSG_SUB, MSG_NOTIFY,
    HDR_LEN, u2b, b2u,
)

log = logging.getLogger('dircon.proxy')

FTMS_CP_BYTES  = u2b('2ad9')
OP_SIMULATION  = 0x11   # Set Indoor Bike Simulation Parameters (gradient + wind)

# ── Per-connection state ──────────────────────────────────────────────────────

@dataclass
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
                # Proxy discovery to real KICKR and relay response.
                resp = await self._dc.raw_request(mt, body)
                self._send(c.writer, mt, seq, resp)

            elif mt == MSG_SUB:
                # Subscription: real KICKR already subscribed in Bridge.setup().
                # Just acknowledge so MyWhoosh thinks it's subscribed.
                self._send(c.writer, mt, seq, b'')

            elif mt == MSG_WRITE and len(body) >= 17:
                uuid_b = body[:16]
                op     = body[16]
                if uuid_b == FTMS_CP_BYTES and op == OP_SIMULATION:
                    # Block gradient / wind simulation command.
                    log.info('FILTER: blocked op 0x11 (gradient) from %s', c.addr)
                    self._send(c.writer, mt, seq, b'')
                    # Send fake FTMS CP success indication back to caller.
                    self._notify(c.writer, '2ad9', bytes([0x80, OP_SIMULATION, 0x01]))
                else:
                    await self._dc.write(b2u(uuid_b), body[16:])
                    self._send(c.writer, mt, seq, b'')

            else:
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

def register_mdns(name: str, port: int) -> object:
    """Advertise 'name' as a DIRCON trainer on the local network via mDNS.

    Returns the Zeroconf instance — keep the reference alive for the
    duration of the programme; call .close() on shutdown.
    """
    from zeroconf import ServiceInfo, Zeroconf
    ip = get_local_ip()
    info = ServiceInfo(
        '_wahoo-fitness-tnp._tcp.local.',
        f'{name}._wahoo-fitness-tnp._tcp.local.',
        addresses=[socket.inet_aton(ip)],
        port=port,
        properties={},
    )
    zc = Zeroconf()
    zc.register_service(info)
    log.info('mDNS: advertising "%s" at %s:%d', name, ip, port)
    return zc

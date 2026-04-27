#!/usr/bin/env python3
"""DIRCON proxy bridge — main entry point.

Connects to the real KICKR via DIRCON (TCP), then:
  • Accepts MyWhoosh connections as a fake DIRCON trainer ("LloydLabs TRNR")
    and proxies all commands transparently to the KICKR.
  • Exposes a local WebSocket server (ws://localhost:8765) so index.html can
    send ERG power targets and receive live data without Web Bluetooth.
  • Advertises itself via mDNS so MyWhoosh discovers it automatically.
  • Scans for a BLE HR monitor and streams HR over the same WebSocket.

Install:  pip install websockets zeroconf bleak
Run:      python dircon_bridge.py [--host KICKR_IP] [--proxy-port 36866]
                                  [--ws-port 8765] [--name "LloydLabs TRNR"]
                                  [--hr-name Fenix] [--hr-name CB100] [-v]
"""

import asyncio, json, logging, argparse
from pathlib import Path
from websockets.asyncio.server import serve
from dircon_client import DirconClient, AUTO_SUBS, expand
from dircon_proxy  import DirconProxyServer, register_mdns
from power_map     import PowerMap
from ble_hr        import BleHrClient

log = logging.getLogger('dircon')

# HR UUID must not be forwarded to the DIRCON proxy (MyWhoosh has its own HR)
_HR_UUID_SHORT = '2a37'

# ── mDNS discovery (finds the real KICKR on the network) ─────────────────────

async def discover_kickr(timeout: float = 8.0):
    """Return (ip, instance_name, txt_properties) for the KICKR via mDNS.

    instance_name is the bare label before '._wahoo-fitness-tnp._tcp.local.'
    txt_properties is a dict of bytes→bytes TXT records from the real device.
    Returns (None, None, {}) if not found.
    """
    try:
        from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
        import socket
        found   = asyncio.Event()
        result  = [None, None, {}]   # [ip, name, props]
        loop    = asyncio.get_running_loop()

        async def _resolve_service(azc, t: str, n: str):
            if found.is_set():
                return
            try:
                info = await azc.async_get_service_info(t, n, timeout=3000)
            except Exception as e:
                log.debug('mDNS resolve %s: %s', n, e)
                return
            if not info or not info.addresses:
                return
            raw = info.addresses[0]
            try:
                if len(raw) == 4:
                    result[0] = socket.inet_ntop(socket.AF_INET, raw)
                elif len(raw) == 16:
                    result[0] = socket.inet_ntop(socket.AF_INET6, raw)
                else:
                    return
            except OSError:
                return
            # Strip the service-type suffix to get the bare instance name
            svc_suffix = '._wahoo-fitness-tnp._tcp.local.'
            result[1] = n[:-len(svc_suffix)] if n.endswith(svc_suffix) else n
            result[2] = info.properties or {}
            found.set()

        class H:
            def __init__(self, azc):
                self._azc = azc
            def add_service(self, zc, t, n):
                if not found.is_set():
                    loop.create_task(_resolve_service(self._azc, t, n))
            def remove_service(self, *_): pass
            def update_service(self, *_): pass

        async with AsyncZeroconf() as azc:
            b = AsyncServiceBrowser(azc.zeroconf,
                '_wahoo-fitness-tnp._tcp.local.', H(azc))
            try:
                await asyncio.wait_for(found.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            await b.async_cancel()
        return tuple(result)
    except ImportError:
        log.warning('pip install zeroconf  for auto-discovery')
        return None

# ── WebSocket bridge ──────────────────────────────────────────────────────────

class Bridge:
    """WebSocket server — lets index.html send/receive GATT traffic via JSON."""

    def __init__(self, dc: DirconClient, proxy: DirconProxyServer,
                 power_map: PowerMap = None, hr_name_hints: list = None):
        self._dc        = dc
        self._proxy     = proxy
        self._power_map = power_map or PowerMap.IDENTITY
        # One BleHrClient per name hint so all devices connect simultaneously.
        hints = hr_name_hints or []
        if hints:
            self._hr_clients = [BleHrClient(self._on_notify, [h]) for h in hints]
        else:
            self._hr_clients = [BleHrClient(self._on_notify, None)]
        self._clients   = set()
        self._subscribed = set()

    @property
    def _hr(self):
        """Return first connected HR client (for status message compat)."""
        for c in self._hr_clients:
            if c.device_name:
                return c
        return self._hr_clients[0]

    async def setup(self):
        try:
            svcs = await self._dc.discover_services()
            log.info('KICKR services: %s', svcs or '(none / parse error)')
        except Exception as e:
            log.warning('discover_services: %s — continuing', e)

        for uuid in AUTO_SUBS:
            try:
                await self._dc.subscribe(uuid)
                self._subscribed.add(expand(uuid))
            except Exception as e:
                log.warning('auto-subscribe %s: %s', uuid, e)

        self._dc.on_notify = self._on_notify
        for client in self._hr_clients:
            asyncio.ensure_future(client.run())
        log.info('BLE HR scanners started (%d)', len(self._hr_clients))

    async def _on_notify(self, uuid: str, data: bytes):
        log.info('NOTIFY uuid=%s data=%s', uuid[-8:], data.hex())
        await self._broadcast_ws(uuid, data)
        # HR originates from BLE, not DIRCON — don't forward to MyWhoosh proxy.
        if uuid.replace('-', '').lower()[4:8] == _HR_UUID_SHORT:
            return
        dircon_data = self._power_map.remap_ibd(data) if '2ad2' in uuid.lower() else data
        await self._proxy.broadcast(uuid, dircon_data)

    async def _broadcast_ws(self, uuid: str, data: bytes):
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
        connected_hr = [c.device_name for c in self._hr_clients if c.device_name]
        await ws.send(json.dumps({
            'type': 'status', 'connected': True,
            'kickr': self._dc.host,
            'hr': ', '.join(connected_hr) if connected_hr else None,
        }))
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
    ap = argparse.ArgumentParser(description='DIRCON proxy bridge')
    ap.add_argument('--host',       default=None,             help='KICKR IP (skip mDNS)')
    ap.add_argument('--proxy-port', type=int, default=36866,  help='DIRCON server port for MyWhoosh')
    ap.add_argument('--ws-port',    type=int, default=8765,   help='WebSocket port for index.html')
    ap.add_argument('--name',       default=None,             help='mDNS trainer name (default: copy from KICKR)')
    ap.add_argument('--ip',         default=None,             help='Override advertised mDNS IP (e.g. 192.168.0.105)')
    ap.add_argument('--lut',        default=None,             help='Power map JSON file (default: power_map.json if present)')
    ap.add_argument('--hr-name',    action='append', default=[], metavar='PREFIX',
                    help='HR device name prefix (repeatable, e.g. --hr-name Fenix --hr-name CB100)')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s  %(message)s')

    # ── Connect to real KICKR ─────────────────────────────────────────────────
    host        = args.host
    kickr_name  = None
    kickr_props = {}
    if not host:
        log.info('Searching for KICKR via mDNS (up to 8 s)…')
        host, kickr_name, kickr_props = await discover_kickr()
    if not host:
        log.error('KICKR not found.  Retry with --host <IP_ADDRESS>')
        return

    # Use the name the real KICKR advertises (so MyWhoosh recognises it)
    # unless the user explicitly overrides with --name.
    proxy_name = args.name or kickr_name or 'KICKR SHIFT'
    log.info('KICKR at %s  (mDNS name: %s)', host, kickr_name or '(unknown)')
    if kickr_props:
        log.info('KICKR TXT props: %s', kickr_props)

    # ── Load power map LUT ────────────────────────────────────────────────────
    lut_path = args.lut or 'power_map.json'
    power_map = PowerMap.IDENTITY
    if Path(lut_path).exists():
        try:
            power_map = PowerMap.load(lut_path)
        except Exception as e:
            log.warning('power_map: failed to load %s: %s — using identity', lut_path, e)
    else:
        log.info('power_map: %s not found — using identity (1:1) mapping', lut_path)

    dc = DirconClient(host)
    while True:
        try:
            await dc.connect()
            break
        except OSError as e:
            log.info('KICKR not ready (%s) — retrying in 5s…', e.strerror)
            await asyncio.sleep(5)

    # ── Subscribe to KICKR characteristics BEFORE starting any servers ────────
    proxy = DirconProxyServer(dc)
    bridge = Bridge(dc, proxy, power_map, args.hr_name or None)
    await bridge.setup()

    # ── Start proxy server (MyWhoosh connects here) ───────────────────────────
    proxy_srv = await proxy.start(port=args.proxy_port)

    # ── Advertise on mDNS so MyWhoosh finds us automatically ─────────────────
    # Pass through the real KICKR's TXT properties so MyWhoosh accepts us.
    zc = None
    try:
        zc = await register_mdns(proxy_name, args.proxy_port, kickr_props, ip=args.ip)
    except Exception as e:
        log.warning('mDNS registration failed: %r', e)
        log.warning('MyWhoosh auto-discovery unavailable — '
                    'select the trainer manually or check Windows Firewall / '
                    'Bonjour service.')

    log.info('WebSocket ready  →  ws://localhost:%d', args.ws_port)
    log.info('Proxy ready      →  "%s" on port %d',
             proxy_name, args.proxy_port)

    try:
        async with serve(bridge.handle_ws, '0.0.0.0', args.ws_port):
            await asyncio.Future()   # run until Ctrl-C
    except OSError as e:
        if e.errno in (98, 10048):   # EADDRINUSE (Linux) / WSAEADDRINUSE (Windows)
            log.error('Port %d is already in use — is another bridge window still open?',
                      args.ws_port)
        else:
            raise
    finally:
        proxy_srv.close()
        if zc:
            await zc.async_close()

if __name__ == '__main__':
    asyncio.run(main())

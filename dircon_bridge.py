#!/usr/bin/env python3
"""DIRCON proxy bridge — main entry point.

Two modes:
  BLE mode  (default, no --host): connects to the KICKR via BLE (bleak).
  DIRCON mode (--host <IP>):      connects via DIRCON TCP, runs the MyWhoosh
                                   fake-trainer proxy and mDNS advertisement.

In both modes:
  • WebSocket server (ws://…:8765) lets index.html send/receive GATT traffic.
  • BLE HR monitor is scanned and streamed over the same WebSocket.

Install:  pip install websockets zeroconf bleak
Run (BLE):      python dircon_bridge.py [--ws-port 8765] [--hr-name Fenix] [-v]
Run (DIRCON):   python dircon_bridge.py --host KICKR_IP [--proxy-port 36866] [-v]
"""

import asyncio, json, logging, argparse
from pathlib import Path
from websockets.asyncio.server import serve
from ble_hr    import BleHrClient
from ble_kickr import BleKickrClient

log = logging.getLogger('dircon')

_HR_UUID_SHORT = '2a37'

# ── mDNS discovery (DIRCON mode only) ────────────────────────────────────────

async def discover_kickr(timeout: float = 8.0):
    """Return (ip, instance_name, txt_properties) for the KICKR via mDNS."""
    try:
        from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
        import socket
        found   = asyncio.Event()
        result  = [None, None, {}]
        loop    = asyncio.get_running_loop()

        async def _resolve(azc, t, n):
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
                af = socket.AF_INET if len(raw) == 4 else socket.AF_INET6
                result[0] = socket.inet_ntop(af, raw)
            except OSError:
                return
            svc = '._wahoo-fitness-tnp._tcp.local.'
            result[1] = n[:-len(svc)] if n.endswith(svc) else n
            result[2] = info.properties or {}
            found.set()

        class H:
            def __init__(self, azc):
                self._azc = azc
            def add_service(self, zc, t, n):
                if not found.is_set():
                    loop.create_task(_resolve(self._azc, t, n))
            def remove_service(self, *_): pass
            def update_service(self, *_): pass

        async with AsyncZeroconf() as azc:
            b = AsyncServiceBrowser(azc.zeroconf, '_wahoo-fitness-tnp._tcp.local.', H(azc))
            try:
                await asyncio.wait_for(found.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            await b.async_cancel()
        return tuple(result)
    except ImportError:
        log.warning('pip install zeroconf  for auto-discovery')
        return None, None, {}

# ── WebSocket bridge ──────────────────────────────────────────────────────────

class Bridge:
    """WebSocket server — lets index.html send/receive GATT traffic via JSON.

    BLE mode:    dc=None,  proxy=None  — uses BleKickrClient internally.
    DIRCON mode: dc=<DirconClient>, proxy=<DirconProxyServer>.
    """

    def __init__(self, dc=None, proxy=None, power_map=None,
                 hr_name_hints=None, kickr_name_hints=None):
        from power_map import PowerMap
        self._dc         = dc
        self._proxy      = proxy
        self._power_map  = power_map or PowerMap.IDENTITY
        self._clients    = set()
        self._subscribed = set()

        if dc is None:
            self._kickr_ble = BleKickrClient(
                self._on_notify,
                name_hints=kickr_name_hints or ['KICKR'],
                on_connected=self._on_kickr_connected,
                on_disconnected=self._on_kickr_disconnected,
            )
        else:
            self._kickr_ble = None

        hints = hr_name_hints or []
        if hints:
            self._hr_clients = [BleHrClient(self._on_notify, [h]) for h in hints]
        else:
            self._hr_clients = [BleHrClient(self._on_notify, None)]

    # ── KICKR status helpers ──────────────────────────────────────────────────

    def _kickr_label(self):
        if self._dc:
            return self._dc.host
        return self._kickr_ble.device_name

    def _kickr_online(self):
        if self._dc:
            return True
        return self._kickr_ble.device_name is not None

    async def _on_kickr_connected(self, name):
        log.info('KICKR BLE connected: %s', name)
        await self._broadcast_status()

    async def _on_kickr_disconnected(self):
        log.info('KICKR BLE disconnected')
        await self._broadcast_status()

    async def _broadcast_status(self):
        connected_hr = [c.device_name for c in self._hr_clients if c.device_name]
        msg = json.dumps({
            'type':      'status',
            'connected': self._kickr_online(),
            'kickr':     self._kickr_label(),
            'hr':        ', '.join(connected_hr) if connected_hr else None,
        })
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def setup(self):
        if self._dc:
            from dircon_client import AUTO_SUBS, expand
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
        else:
            asyncio.ensure_future(self._kickr_ble.run())
            log.info('KICKR BLE scanner started')

        for client in self._hr_clients:
            asyncio.ensure_future(client.run())
        log.info('BLE HR scanners started (%d)', len(self._hr_clients))

    # ── Notify / WebSocket broadcast ──────────────────────────────────────────

    async def _on_notify(self, uuid: str, data: bytes):
        log.info('NOTIFY uuid=%s data=%s', uuid[-8:], data.hex())
        await self._broadcast_ws(uuid, data)
        if uuid.replace('-', '').lower()[4:8] == _HR_UUID_SHORT:
            return
        if self._proxy:
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

    # ── WebSocket handler ─────────────────────────────────────────────────────

    async def handle_ws(self, ws):
        self._clients.add(ws)
        connected_hr = [c.device_name for c in self._hr_clients if c.device_name]
        await ws.send(json.dumps({
            'type':      'status',
            'connected': self._kickr_online(),
            'kickr':     self._kickr_label(),
            'hr':        ', '.join(connected_hr) if connected_hr else None,
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
        if cmd == 'discover' and self._dc:
            from dircon_client import expand
            svcs = await self._dc.discover_services()
            await ws.send(json.dumps({'type': 'services', 'list': svcs}))
        elif cmd == 'subscribe' and self._dc:
            from dircon_client import expand
            u = expand(msg['uuid'])
            if u not in self._subscribed:
                await self._dc.subscribe(u)
                self._subscribed.add(u)
        elif cmd == 'write':
            data = bytes(msg['data'])
            if self._dc:
                await self._dc.write(msg['uuid'], data)
            elif self._kickr_ble:
                await self._kickr_ble.write_cp(data)
        elif cmd == 'connect_dircon':
            asyncio.ensure_future(self._attempt_dircon())

    async def _attempt_dircon(self):
        """Discover KICKR via mDNS and connect via DIRCON TCP."""
        from dircon_client import DirconClient, AUTO_SUBS, expand
        log.info('WiFi: searching for KICKR via mDNS…')
        await self._broadcast_status_msg(False, 'WiFi scanning…')
        host, name, _ = await discover_kickr(timeout=8.0)
        if not host:
            log.warning('WiFi: KICKR not found via mDNS')
            await self._broadcast_status_msg(False, 'KICKR not found on WiFi')
            return
        log.info('WiFi: found %s at %s — connecting…', name, host)
        try:
            dc = DirconClient(host)
            await dc.connect()
        except OSError as e:
            log.warning('WiFi: connect to %s failed: %s', host, e)
            await self._broadcast_status_msg(False, 'WiFi connect failed')
            return
        for uuid in AUTO_SUBS:
            try:
                await dc.subscribe(uuid)
            except Exception:
                pass
        dc.on_notify = self._on_notify
        self._dc = dc
        log.info('WiFi: KICKR connected at %s', host)
        await self._broadcast_status()

    async def _broadcast_status_msg(self, connected: bool, kickr_label: str):
        connected_hr = [c.device_name for c in self._hr_clients if c.device_name]
        msg = json.dumps({
            'type':      'status',
            'connected': connected,
            'kickr':     kickr_label,
            'hr':        ', '.join(connected_hr) if connected_hr else None,
        })
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    ap = argparse.ArgumentParser(description='DIRCON proxy bridge')
    ap.add_argument('--host',        default=None,            help='KICKR IP → DIRCON mode (skips BLE)')
    ap.add_argument('--proxy-port',  type=int, default=36866, help='DIRCON server port for MyWhoosh')
    ap.add_argument('--ws-port',     type=int, default=8765,  help='WebSocket port for index.html')
    ap.add_argument('--name',        default=None,            help='mDNS trainer name override')
    ap.add_argument('--ip',          default=None,            help='Override advertised mDNS IP')
    ap.add_argument('--lut',         default=None,            help='Power map JSON file')
    ap.add_argument('--kickr-name',  action='append', default=[], metavar='PREFIX',
                    help='KICKR BLE name prefix (BLE mode only, repeatable)')
    ap.add_argument('--hr-name',     action='append', default=[], metavar='PREFIX',
                    help='HR device name prefix (repeatable)')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s  %(message)s')

    lut_path  = args.lut or 'power_map.json'
    from power_map import PowerMap
    power_map = PowerMap.IDENTITY
    if Path(lut_path).exists():
        try:
            power_map = PowerMap.load(lut_path)
        except Exception as e:
            log.warning('power_map: %s — using identity', e)
    else:
        log.info('power_map: %s not found — using identity', lut_path)

    proxy_srv = None
    zc        = None

    if args.host:
        # ── DIRCON mode ───────────────────────────────────────────────────────
        from dircon_client import DirconClient
        from dircon_proxy  import DirconProxyServer, register_mdns
        host        = args.host
        kickr_name  = None
        kickr_props = {}
        log.info('DIRCON mode: connecting to %s', host)
        dc = DirconClient(host)
        while True:
            try:
                await dc.connect()
                break
            except OSError as e:
                log.info('KICKR not ready (%s) — retrying in 5s…', e.strerror)
                await asyncio.sleep(5)

        proxy      = DirconProxyServer(dc)
        proxy_name = args.name or kickr_name or 'KICKR SHIFT'
        bridge     = Bridge(dc=dc, proxy=proxy, power_map=power_map,
                            hr_name_hints=args.hr_name or None)
        await bridge.setup()

        proxy_srv = await proxy.start(port=args.proxy_port)
        try:
            zc = await register_mdns(proxy_name, args.proxy_port, kickr_props, ip=args.ip)
        except Exception as e:
            log.warning('mDNS registration failed: %r', e)
        log.info('Proxy ready  →  "%s" on port %d', proxy_name, args.proxy_port)
    else:
        # ── BLE mode ──────────────────────────────────────────────────────────
        log.info('BLE mode: scanning for KICKR via BLE')
        bridge = Bridge(dc=None, proxy=None, power_map=power_map,
                        hr_name_hints=args.hr_name or None,
                        kickr_name_hints=args.kickr_name or None)
        await bridge.setup()

    log.info('WebSocket ready  →  ws://localhost:%d', args.ws_port)
    try:
        async with serve(bridge.handle_ws, '0.0.0.0', args.ws_port):
            await asyncio.Future()
    except OSError as e:
        if e.errno in (98, 10048):
            log.error('Port %d in use — is another bridge window open?', args.ws_port)
        else:
            raise
    finally:
        if proxy_srv:
            proxy_srv.close()
        if zc:
            await zc.async_close()

if __name__ == '__main__':
    asyncio.run(main())

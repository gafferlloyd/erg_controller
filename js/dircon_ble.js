'use strict';

// ── DIRCON trainer adapter ─────────────────────────────────────────────────────
// Connects to dircon_bridge.py via WebSocket and provides the same trainer
// interface as ble.js — without using Web Bluetooth.
//
// How it works:
//   A fake ftmsCP object is injected into the ble.js globals so that all
//   existing write paths (ftmsHandshake, sendPower, writeCPBytes) route over
//   the WebSocket instead of BLE.  Incoming notifications are forwarded to the
//   existing ble.js data handlers (onFTMSIndoor, onCPResponse, onMachineStatus).
//
// Usage: call connectDircon() instead of connectTrainer().

// Use the serving host so the page works from any machine on the LAN.
// Map 'localhost' → '127.0.0.1' to avoid IPv6 (::1) on Linux.
const DIRCON_WS_DEFAULT = (() => {
  const h = window.location.hostname;
  return `ws://${h === 'localhost' ? '127.0.0.1' : h}:8765`;
})();

let _dirconWs = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

// Wrap a raw byte array in a synthetic DataView event so ble.js handlers
// can be called directly without modification.
function _synth(data) {
  return { target: { value: new DataView(new Uint8Array(data).buffer) } };
}

// Route a DIRCON notification to the matching ble.js handler by UUID suffix.
function _route(uuid, data) {
  const u = uuid.replace(/-/g, '').toLowerCase();
  const s = u.slice(4, 8);   // short UUID at chars 4-7 of the 32-char hex
  if      (s === '2ad2') onFTMSIndoor(_synth(data));    // power/cadence/speed
  else if (s === '2ad9') onCPResponse(_synth(data));    // FTMS CP indication
  else if (s === '2ada') onMachineStatus(_synth(data)); // machine status
  else if (s === '2a63') onCPS(_synth(data));           // CPS power
  else if (s === '2a37') onHRMeasurement(_synth(data)); // HR (from bridge BLE)
}

// ── Fake FTMS CP characteristic ───────────────────────────────────────────────
// Handed to ble.js's ftmsCP global; writeChar() calls writeValueWithResponse()
// transparently, routing the bytes over the WebSocket to dircon_bridge.py.

const _dirconFtmsCP = {
  writeValueWithResponse: async buf => {
    if (!_dirconWs || _dirconWs.readyState !== WebSocket.OPEN)
      throw new Error('DIRCON not connected');
    _dirconWs.send(JSON.stringify({
      cmd:  'write',
      uuid: '2ad9',
      data: Array.from(new Uint8Array(buf)),
    }));
  },
};

// ── Public connect function ───────────────────────────────────────────────────

// Auto-connect when the page loads — if the bridge isn't running the
// attempt fails silently and the user can still click the WiFi button.
document.addEventListener('DOMContentLoaded', () => {
  connectDircon().catch(() => {});
});

async function connectDircon(wsUrl = DIRCON_WS_DEFAULT) {
  if (_dirconWs) { _dirconWs.close(); _dirconWs = null; }
  setPill('trainer', false, 'WiFi…');

  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    _dirconWs = ws;

    ws.addEventListener('open', () => {
      log('DIRCON WebSocket open', 'info');
      // Bridge auto-subscribes 2AD2 + 2ADA; also request 2AD9 (CP indications).
      ws.send(JSON.stringify({ cmd: 'subscribe', uuid: '2ad9' }));
    });

    ws.addEventListener('message', e => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'status') {
        if (msg.connected) {
          ftmsCP      = _dirconFtmsCP;   // inject into ble.js scope
          trainerLive = true;
          setPill('trainer', true, msg.kickr || 'Connected');
          log(`DIRCON connected: ${msg.kickr}`, 'ok');
          ftmsHandshake();
          updateServoBtn();
          resolve();
        } else {
          setPill('trainer', false, 'BLE scanning…');
          log('Bridge live — scanning for KICKR…', 'info');
        }
        if (msg.hr) {
          hrLive = true;
          setPill('hr', true, msg.hr);
          log(`HR connected: ${msg.hr}`, 'ok');
        }
      } else if (msg.type === 'notify') {
        const s = msg.uuid.replace(/-/g, '').toLowerCase().slice(4, 8);
        if (s === '2a37' && !hrLive) {
          hrLive = true;
          setPill('hr', true, 'Bridge');
          log('HR live via bridge', 'ok');
        }
        _route(msg.uuid, msg.data);
      } else if (msg.type === 'error') {
        log(`DIRCON: ${msg.message}`, 'err');
      }
    });

    ws.addEventListener('close', () => {
      trainerLive           = false;
      ftmsCP                = null;
      ergHandshakeDone      = false;
      pendingServoPowerSend = false;
      hrLive                = false;
      _dirconWs = null;
      setPill('trainer', false, 'WiFi disconnected');
      setPill('hr', false, 'Disconnected');
      log('DIRCON disconnected', 'warn');
      updateServoBtn();
    });

    ws.addEventListener('error', () => {
      setPill('trainer', false, 'WiFi failed');
      reject(new Error(`Cannot reach DIRCON bridge at ${wsUrl}`));
    });
  });
}

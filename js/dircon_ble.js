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

const DIRCON_WS_DEFAULT = 'ws://localhost:8765';

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
      if (msg.type === 'status' && msg.connected) {
        ftmsCP      = _dirconFtmsCP;   // inject into ble.js scope
        trainerLive = true;
        setPill('trainer', true, `WiFi ${msg.kickr}`);
        log(`DIRCON connected: ${msg.kickr}`, 'ok');
        ftmsHandshake();
        updateServoBtn();
        resolve();
      } else if (msg.type === 'notify') {
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
      _dirconWs = null;
      setPill('trainer', false, 'WiFi disconnected');
      log('DIRCON disconnected', 'warn');
      updateServoBtn();
    });

    ws.addEventListener('error', () => {
      setPill('trainer', false, 'WiFi failed');
      reject(new Error(`Cannot reach DIRCON bridge at ${wsUrl}`));
    });
  });
}

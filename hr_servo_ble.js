'use strict';

// ══════════════════════════════════════════════════════
//  GATT UUIDs
// ══════════════════════════════════════════════════════
const UUID = {
  CPS_SERVICE:     0x1818,
  CPS_MEASUREMENT: 0x2A63,
  FTMS_SERVICE:    0x1826,
  FTMS_INDOOR:     0x2AD2,
  FTMS_CP:         0x2AD9,
  HR_SERVICE:      0x180D,
  HR_MEASUREMENT:  0x2A37,
};

// Wahoo proprietary ERG control characteristic (lives inside the CPS service).
// GoldenCheetah uses opcode 0x42 on this characteristic. The KICKR SHIFT exposes
// it alongside standard FTMS; prefer this path when available.
const WAHOO_CP_UUID = 'a026e005-0a7d-4ab3-97fa-f1500f9feb8b';

// ══════════════════════════════════════════════════════
//  UI helpers (used by all modules)
// ══════════════════════════════════════════════════════
const _logBuffer = [];   // full session log for download

function log(msg, cls = 'info') {
  const ts   = new Date().toTimeString().slice(0, 8);
  const line = `[${ts}] [${cls.toUpperCase().padEnd(4)}] ${msg}`;
  _logBuffer.push(line);

  const el = document.getElementById('log');
  const d  = document.createElement('div');
  d.className = cls;
  d.textContent = `[${ts}] ${msg}`;
  el.prepend(d);
}

function downloadLog() {
  const ts   = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const body = _logBuffer.join('\n');
  const blob = new Blob([body], { type: 'text/plain' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = `hrservo_${ts}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

function setPill(role, connected, name) {
  const pill = document.getElementById(`pill-${role}`);
  const dot  = document.getElementById(`pdot-${role}`);
  const lbl  = document.getElementById(`plbl-${role}`);
  pill.classList.toggle('connected', connected);
  dot.style.background = connected ? 'var(--green)' : 'var(--red)';
  lbl.textContent = name || (connected ? 'Connected' : 'Not connected');
}

// ══════════════════════════════════════════════════════
//  Device state
// ══════════════════════════════════════════════════════
let trainerDevice = null, hrDevice = null;
let trainerLive   = false, hrLive  = false;
let wahooCP       = null;   // Wahoo proprietary CP (preferred if found in CPS service)
let ftmsCP        = null;   // FTMS control point (fallback)
let ergHandshakeDone      = false;
let pendingServoPowerSend = false;  // true while waiting for FTMS 0x80 ack before first power TX

// ── GATT write serialiser ─────────────────────────────
// Chains all BLE writes onto a single promise so they execute in order and
// never overlap. Replaces the old _gattBusy flag, which caused one of every
// colliding pair (heartbeat vs tick) to be dropped silently.
let _gattChain = Promise.resolve();

// Set by heartbeat before queuing a periodic 0x07 so onCPResponse can
// swallow the routine ack without flooding the log.
let _suppressResumeLog = false;

let lastHR    = null;
let lastPower = null;

// ══════════════════════════════════════════════════════
//  BLE connect dispatcher
// ══════════════════════════════════════════════════════
async function connectDevice(role) {
  if (!navigator.bluetooth) { log('Web Bluetooth not available — use Chrome', 'err'); return; }
  if (role === 'trainer') await connectTrainer();
  else                    await connectHR();
}

async function connectTrainer() {
  setPill('trainer', false, 'Scanning…');
  let dev;
  try {
    dev = await navigator.bluetooth.requestDevice({
      filters: [
        { namePrefix: 'KICKR' }, { namePrefix: 'Wahoo' },
        { services: [UUID.CPS_SERVICE] }, { services: [UUID.FTMS_SERVICE] }
      ],
      optionalServices: [UUID.CPS_SERVICE, UUID.FTMS_SERVICE, UUID.FTMS_CP, UUID.FTMS_INDOOR],
    });
  } catch(e) { setPill('trainer', false, 'Cancelled'); return; }

  trainerDevice = dev;
  dev.addEventListener('gattserverdisconnected', () => {
    trainerLive = false; wahooCP = null; ftmsCP = null;
    ergHandshakeDone = false; pendingServoPowerSend = false;
    setPill('trainer', false, 'Disconnected');
    log('Trainer disconnected', 'warn');
    updateServoBtn();
  });

  setPill('trainer', false, 'Connecting…');
  try {
    const server = await dev.gatt.connect();
    let gotData = false;

    // ── CPS service: power readings + optional Wahoo proprietary CP ──
    try {
      const cpsSvc = await server.getPrimaryService(UUID.CPS_SERVICE);

      try {
        const chr = await cpsSvc.getCharacteristic(UUID.CPS_MEASUREMENT);
        chr.addEventListener('characteristicvaluechanged', onCPS);
        await chr.startNotifications();
        gotData = true;
        log('Subscribed: CPS power', 'ok');
      } catch(_) {}

      // Wahoo proprietary ERG control (opcode 0x42) — lives inside CPS service
      try {
        const wcp = await cpsSvc.getCharacteristic(WAHOO_CP_UUID);
        wcp.addEventListener('characteristicvaluechanged', onWahooResponse);
        await wcp.startNotifications();
        wahooCP = wcp;
        log('Wahoo proprietary CP ready (preferred over FTMS)', 'ok');
      } catch(_) {
        log('No Wahoo CP in CPS service — will try FTMS', 'info');
      }
    } catch(_) {}

    // ── FTMS service: indoor data (if CPS unavailable) + CP (if Wahoo not found) ──
    try {
      const ftmsSvc = await server.getPrimaryService(UUID.FTMS_SERVICE);

      if (!gotData) {
        try {
          const chr = await ftmsSvc.getCharacteristic(UUID.FTMS_INDOOR);
          chr.addEventListener('characteristicvaluechanged', onFTMS);
          await chr.startNotifications();
          gotData = true;
          log('Subscribed: FTMS indoor', 'ok');
        } catch(_) {}
      }

      // FTMS CP — only if Wahoo path not found.
      // Note: FTMS has no "read current ERG target" command; CP is write-only for targets.
      if (!wahooCP) {
        try {
          const cp = await ftmsSvc.getCharacteristic(UUID.FTMS_CP);
          cp.addEventListener('characteristicvaluechanged', onCPResponse);
          await cp.startNotifications();
          ftmsCP = cp;
          log('FTMS Control Point ready', 'ok');
        } catch(e) { log(`FTMS CP unavailable: ${e.message}`, 'warn'); }
      }
    } catch(_) {}

    if (gotData) {
      trainerLive = true;
      setPill('trainer', true, dev.name);
      const path = wahooCP ? 'Wahoo proprietary' : ftmsCP ? 'FTMS' : 'read-only';
      log(`Control path: ${path}`, 'info');
    } else {
      setPill('trainer', false, 'No data service');
    }
  } catch(e) {
    setPill('trainer', false, 'Failed');
    log(`Trainer connect failed: ${e.message}`, 'err');
  }
  updateServoBtn();
}

async function connectHR() {
  setPill('hr', false, 'Scanning…');
  let dev;
  try {
    dev = await navigator.bluetooth.requestDevice({
      filters: [{ services: [UUID.HR_SERVICE] }],
      optionalServices: [UUID.HR_SERVICE],
    });
  } catch(e) { setPill('hr', false, 'Cancelled'); return; }

  hrDevice = dev;
  dev.addEventListener('gattserverdisconnected', () => {
    hrLive = false;
    setPill('hr', false, 'Disconnected');
    log('HR monitor disconnected', 'warn');
    updateServoBtn();
  });

  setPill('hr', false, 'Connecting…');
  try {
    const server = await dev.gatt.connect();
    const svc    = await server.getPrimaryService(UUID.HR_SERVICE);
    const chr    = await svc.getCharacteristic(UUID.HR_MEASUREMENT);
    chr.addEventListener('characteristicvaluechanged', onHR);
    await chr.startNotifications();
    hrLive = true;
    setPill('hr', true, dev.name);
    log(`HR monitor connected: ${dev.name}`, 'ok');
  } catch(e) {
    setPill('hr', false, 'Failed');
    log(`HR connect failed: ${e.message}`, 'err');
  }
  updateServoBtn();
}

// ══════════════════════════════════════════════════════
//  GATT data handlers
// ══════════════════════════════════════════════════════
function onCPS(e) {
  const v = e.target.value;
  lastPower = v.getInt16(2, true);
  document.getElementById('m-pwr').textContent = lastPower;
  drawCharacteristic();
}

function onFTMS(e) {
  const v     = e.target.value;
  const flags = v.getUint16(0, true);
  let offset  = 2;
  offset += 2;                                              // Speed (always present)
  if (flags & 0x0002) offset += 2;                         // Average speed
  if (flags & 0x0004) offset += 2;                         // Cadence
  if (flags & 0x0008) offset += 3;                         // Total distance
  if (flags & 0x0010) offset += 2;                         // Resistance level
  if (flags & 0x0040 && offset + 1 < v.byteLength) {
    lastPower = v.getInt16(offset, true);
    document.getElementById('m-pwr').textContent = lastPower;
    drawCharacteristic();
  }
}

function onHR(e) {
  const v     = e.target.value;
  const flags = v.getUint8(0);
  lastHR = (flags & 0x01) ? v.getUint16(1, true) : v.getUint8(1);
  document.getElementById('m-hr').textContent = lastHR;
  if (servoActive) {
    const tgt = parseInt(document.getElementById('target-hr').value);
    const err = tgt - lastHR;
    const el  = document.getElementById('m-err');
    el.textContent = (err >= 0 ? '+' : '') + err;
    el.style.color = Math.abs(err) <= parseInt(document.getElementById('deadband').value)
      ? 'var(--green)' : Math.abs(err) > 10 ? 'var(--red)' : 'var(--amber)';
  }
}

function onWahooResponse(e) {
  const v  = e.target.value;
  const op = v.getUint8(0);
  log(`[RX/Wahoo] op=0x${op.toString(16).padStart(2, '0')} len=${v.byteLength}`, 'info');
}

function onCPResponse(e) {
  const v = e.target.value;
  if (v.getUint8(0) !== 0x80) return;
  const req = v.getUint8(1), res = v.getUint8(2);
  const ok  = res === 0x01;
  if (req === 0x00) {
    if (ok && !ergHandshakeDone) {
      ergHandshakeDone = true;
      log('FTMS Request Control OK', 'ok');
      // Send Start/Resume (0x07) to move trainer into Running state,
      // then fire the first power command if servo is waiting.
      writeCPBytes([0x07]).then(() => {
        log('[TX/FTMS] 07 Start/Resume', 'tx');
        if (pendingServoPowerSend && servoActive) {
          pendingServoPowerSend = false;
          sendPower(ergSetpoint);
        }
      }).catch(err => log(`Start/Resume failed: ${err.message}`, 'err'));
    } else if (!ok) {
      log(`FTMS Request Control rejected (code ${res})`, 'err');
    }
  } else if (req === 0x07) {
    if (_suppressResumeLog) { _suppressResumeLog = false; return; }  // heartbeat 0x07 — silent
    log(`FTMS Start/Resume ${ok ? 'OK' : `rejected (code ${res})`}`, ok ? 'ok' : 'err');
  } else if (req === 0x05) {
    if (!ok) log(`FTMS Set Target Power rejected (code ${res})`, 'err');
  }
}

// ══════════════════════════════════════════════════════
//  Write helpers
// ══════════════════════════════════════════════════════
async function writeChar(characteristic, bytes) {
  const p = _gattChain.then(async () => {
    const buf = new Uint8Array(bytes).buffer;
    if (characteristic.writeValueWithResponse) await characteristic.writeValueWithResponse(buf);
    else                                       await characteristic.writeValue(buf);
  });
  _gattChain = p.catch(() => {});   // keep chain alive even if this write fails
  return p;                          // caller can still await / catch
}

async function writeCPBytes(bytes) {
  if (!ftmsCP) throw new Error('No FTMS control point');
  await writeChar(ftmsCP, bytes);
}

// silent=true suppresses the log line (heartbeat uses this to avoid spam)
async function sendPower(watts, silent = false) {
  const w  = Math.round(Math.max(0, Math.min(2000, watts)));
  const lo = w & 0xFF, hi = (w >> 8) & 0xFF;
  if (wahooCP) {
    await writeChar(wahooCP, [0x42, lo, hi]);
    if (!silent) log(`[TX/Wahoo] Set power ${w}W`, 'tx');
  } else if (ftmsCP) {
    await writeCPBytes([0x05, lo, hi]);
    if (!silent) log(`[TX/FTMS] Set power ${w}W`, 'tx');
  } else {
    throw new Error('No control characteristic available');
  }
}

async function ftmsHandshake() {
  // Only needed for FTMS path — Wahoo needs no handshake.
  if (ergHandshakeDone) {
    // Already have control; re-send Start/Resume then first power.
    await writeCPBytes([0x07]);
    log('[TX/FTMS] 07 Start/Resume (re-arm)', 'tx');
    if (servoActive) sendPower(ergSetpoint);
    return;
  }
  try {
    await writeCPBytes([0x00]);
    log('[TX/FTMS] 00 Request Control', 'tx');
    pendingServoPowerSend = true;  // power sent after 0x80 ack arrives in onCPResponse
  } catch(e) { log(`FTMS handshake failed: ${e.message}`, 'err'); }
}

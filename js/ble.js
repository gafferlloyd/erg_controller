'use strict';

// ── GATT UUIDs ────────────────────────────────────────────────────────────────
const UUID = {
  CPS_SERVICE:         0x1818,
  CPS_MEASUREMENT:     0x2A63,
  FTMS_SERVICE:        0x1826,
  FTMS_INDOOR:         0x2AD2,
  FTMS_CP:             0x2AD9,
  FTMS_MACHINE_STATUS: 0x2ADA,
  HR_SERVICE:          0x180D,
  HR_MEASUREMENT:      0x2A37,
};

// Wahoo proprietary ERG CP (not present on KICKR BIKE SHIFT — FTMS is used instead)
const WAHOO_CP_UUID = 'a026e005-0a7d-4ab3-97fa-f1500f9feb8b';

// ── Device & characteristic handles ──────────────────────────────────────────
let trainerDevice = null;
let hrDevice      = null;
let wahooCP       = null;   // Wahoo proprietary CP (preferred if found)
let ftmsCP        = null;   // FTMS control point

// Public live-value globals — read by session.js, pid.js, ui.js
let trainerLive      = false;
let hrLive           = false;
let lastHR           = null;
let lastPower        = null;
let lastCadence      = null;
let lastSpeed        = null;   // km/h (from FTMS Indoor, always present)
let lastResistance   = null;   // FTMS resistance level (Machine Status 0x07)
let lastGrade        = null;   // grade % from Machine Status 0x12 (simulation params)

// ── HRV — R-R interval accumulation ──────────────────────────────────────────
// FTMS HR characteristic flag bit 4 signals RR-interval presence.
// Intervals arrive in units of 1/1024 s; we convert to ms.
const RR_WINDOW_MS  = 60000;   // keep 60 s of RR data
let   rrBuffer      = [];      // [{t: ms, rr: ms}, ...]
let   currentRMSSD  = null;    // most recent computed RMSSD (ms)

function addRRInterval(rrRaw) {
  const rrMs = Math.round(rrRaw / 1024 * 1000);
  if (rrMs < 200 || rrMs > 3000) return;  // sanity: 20–300 bpm range
  rrBuffer.push({ t: Date.now(), rr: rrMs });
  pruneRRBuffer();
  currentRMSSD = computeRMSSD(rrBuffer.map(x => x.rr));
  sessionAddRR(rrMs);   // accumulate for FIT HRV export
}

function pruneRRBuffer() {
  const cutoff = Date.now() - RR_WINDOW_MS;
  rrBuffer = rrBuffer.filter(x => x.t > cutoff);
}

function computeRMSSD(intervals) {
  if (intervals.length < 2) return null;
  let sumSq = 0;
  for (let i = 1; i < intervals.length; i++) {
    sumSq += (intervals[i] - intervals[i - 1]) ** 2;
  }
  return Math.round(Math.sqrt(sumSq / (intervals.length - 1)));
}

// ── GATT write serialiser ─────────────────────────────────────────────────────
// All BLE writes share one promise chain so they never overlap.
let _gattChain          = Promise.resolve();
let _suppressResumeLog  = false;

function writeChar(characteristic, bytes) {
  const p = _gattChain.then(async () => {
    const buf = new Uint8Array(bytes).buffer;
    if (characteristic.writeValueWithResponse) {
      await characteristic.writeValueWithResponse(buf);
    } else {
      await characteristic.writeValue(buf);
    }
  });
  _gattChain = p.catch(() => {});
  return p;
}

function writeCPBytes(bytes) {
  if (!ftmsCP) throw new Error('No FTMS control point');
  return writeChar(ftmsCP, bytes);
}

// Send a power target via Wahoo or FTMS path.
async function sendPower(watts, silent = false) {
  const w  = Math.round(Math.max(0, Math.min(2000, watts)));
  const lo = w & 0xFF;
  const hi = (w >> 8) & 0xFF;
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

// ── FTMS handshake ────────────────────────────────────────────────────────────
let ergHandshakeDone      = false;
let pendingServoPowerSend = false;

async function ftmsHandshake() {
  if (ergHandshakeDone) {
    await writeCPBytes([0x07]);
    log('[TX/FTMS] 07 Start/Resume (re-arm)', 'tx');
    if (servoActive || ergActive) sendPower(ergSetpoint);
    return;
  }
  await writeCPBytes([0x00]);
  log('[TX/FTMS] 00 Request Control', 'tx');
  pendingServoPowerSend = true;
}

// ── Data handlers ─────────────────────────────────────────────────────────────

function onCPS(e) {
  const v = e.target.value;
  lastPower = v.getInt16(2, true);
  // lastCadence and lastSpeed come from FTMS Indoor — do not overwrite here
  onNewPower(lastPower, lastCadence);
}

// Cadence lives in the CPS flags/crank revolution fields.
// Flags bit 0: wheel data present (skip 6 bytes).  Flags bit 1: crank data present.
function readCadenceFromCPS(v) {
  const flags = v.getUint16(0, true);
  let offset  = 4;   // skip flags (2) + instant power (2)
  if (flags & 0x01) offset += 6;   // wheel revolution data
  if ((flags & 0x02) && offset + 3 < v.byteLength) {
    // cumulative crank revs (uint16) + last crank event time (uint16, 1/1024 s)
    // We just return the instantaneous power; proper cadence would need deltas.
    // Cadence is separately reported by FTMS Indoor, so leave null here.
  }
  return null;
}

function onFTMSIndoor(e) {
  const v     = e.target.value;
  const flags = v.getUint16(0, true);
  let offset  = 2;
  lastSpeed = v.getUint16(offset, true) * 0.01;  // always present, units: 0.01 km/h
  offset += 2;
  if (flags & 0x0002) offset += 2;               // average speed
  if (flags & 0x0004) {                           // instantaneous cadence
    if (offset + 1 < v.byteLength) {
      lastCadence = Math.round(v.getUint16(offset, true) / 2);
    }
    offset += 2;
  }
  if (flags & 0x0008) offset += 2;               // average cadence (uint16)
  if (flags & 0x0010) offset += 3;               // total distance (uint24)
  if (flags & 0x0020) offset += 2;               // resistance level
  if (flags & 0x0040 && offset + 1 < v.byteLength) {
    lastPower = v.getInt16(offset, true);
  }
  onNewPower(lastPower, lastCadence);
}

function onHRMeasurement(e) {
  const v     = e.target.value;
  const flags = v.getUint8(0);
  const is16  = flags & 0x01;
  let offset  = 1;

  lastHR = is16 ? v.getUint16(offset, true) : v.getUint8(offset);
  offset += is16 ? 2 : 1;

  // Energy expended (bit 3) — skip
  if (flags & 0x08) offset += 2;

  // RR intervals (bit 4)
  if (flags & 0x10) {
    while (offset + 1 < v.byteLength) {
      addRRInterval(v.getUint16(offset, true));
      offset += 2;
    }
  }

  onNewHR(lastHR);
}

function onCPResponse(e) {
  const v   = e.target.value;
  if (v.getUint8(0) !== 0x80) return;
  const req = v.getUint8(1);
  const res = v.getUint8(2);
  const ok  = res === 0x01;

  if (req === 0x00) {
    if (ok && !ergHandshakeDone) {
      ergHandshakeDone = true;
      log('FTMS Request Control OK', 'ok');
      writeCPBytes([0x07]).then(() => {
        log('[TX/FTMS] 07 Start/Resume', 'tx');
        if (pendingServoPowerSend && (servoActive || ergActive)) {
          pendingServoPowerSend = false;
          sendPower(ergSetpoint);
        }
      }).catch(err => log(`Start/Resume failed: ${err.message}`, 'err'));
    } else if (!ok) {
      log(`FTMS Request Control rejected (code ${res})`, 'err');
    }
  } else if (req === 0x07) {
    if (_suppressResumeLog) { _suppressResumeLog = false; return; }
    log(`FTMS Start/Resume ${ok ? 'OK' : `rejected (${res})`}`, ok ? 'ok' : 'err');
  } else if (req === 0x05 && !ok) {
    log(`FTMS Set Target Power rejected (code ${res})`, 'err');
  }
}

function onMachineStatus(e) {
  const v  = e.target.value;
  const op = v.getUint8(0);
  if (op === 0x07 && v.byteLength >= 2) {
    // Target Resistance Level Changed — fires when user shifts gear
    lastResistance = v.getUint8(1);
    setVal('cv-gear', lastResistance);
    log(`Resistance level → ${lastResistance}`, 'info');
  } else if (op === 0x08 && v.byteLength >= 3) {
    // Target Power Changed — KICKR acknowledged our Set Target Power
    const watts = v.getUint16(1, true);
    log(`FTMS ack: Target Power → ${watts}W`, 'ok');
    onErgConfirmed(watts);
  } else if (op === 0x12 && v.byteLength >= 5) {
    // Indoor Bike Simulation Parameters Changed — parse grade from bytes 3-4
    // Format: wind(int16 LE, 0.001 m/s), grade(int16 LE, 0.01%), Crr, CwA
    lastGrade = v.getInt16(3, true) * 0.01;
    const sign = lastGrade >= 0 ? '+' : '';
    setVal('cv-grade', `${sign}${lastGrade.toFixed(1)}`);
    // Re-assert ERG if another app sent this and took us out of ERG mode.
    if (servoActive || ergActive) {
      log('MyWhoosh gradient intercepted — re-asserting ERG target', 'warn');
      sendPower(ergSetpoint).catch(e => log(`Re-assert ERG: ${e.message}`, 'warn'));
    }
  } else if (op === 0x19 || op === 0xFF) {
    log('FTMS Control Permission Lost — another device took over!', 'warn');
    onErgControlLost();
  } else if (op === 0x04) {
    log('FTMS: machine started/resumed', 'info');
  } else if (op === 0x02 || op === 0x03) {
    log(`FTMS: machine stopped (op=0x${op.toString(16)})`, 'warn');
  }
}

function onWahooResponse(e) {
  const v  = e.target.value;
  const op = v.getUint8(0);
  log(`[RX/Wahoo] op=0x${op.toString(16).padStart(2, '0')} len=${v.byteLength}`, 'info');
}

// ── Trainer connection ────────────────────────────────────────────────────────

async function connectTrainer() {
  setPill('trainer', false, 'Scanning…');
  let dev;
  try {
    dev = await navigator.bluetooth.requestDevice({
      filters: [
        { namePrefix: 'KICKR' }, { namePrefix: 'Wahoo' },
        { services: [UUID.CPS_SERVICE] }, { services: [UUID.FTMS_SERVICE] },
      ],
      optionalServices: [
        UUID.CPS_SERVICE, UUID.FTMS_SERVICE,
        UUID.FTMS_CP, UUID.FTMS_INDOOR, UUID.FTMS_MACHINE_STATUS,
      ],
    });
  } catch (_) { setPill('trainer', false, 'Cancelled'); return; }

  trainerDevice = dev;
  dev.addEventListener('gattserverdisconnected', onTrainerDisconnected);

  setPill('trainer', false, 'Connecting…');
  try {
    const server = await dev.gatt.connect();
    await subscribeTrainerServices(server);
  } catch (e) {
    setPill('trainer', false, 'Failed');
    log(`Trainer connect failed: ${e.message}`, 'err');
  }
  updateServoBtn();
}

async function subscribeTrainerServices(server) {
  let gotData = false;

  // CPS — power + optional Wahoo CP
  try {
    const cpsSvc = await server.getPrimaryService(UUID.CPS_SERVICE);
    gotData = await subscribeCPS(cpsSvc);
  } catch (_) {}

  // FTMS — indoor data (always subscribed for cadence) + control point + machine status
  try {
    const ftmsSvc = await server.getPrimaryService(UUID.FTMS_SERVICE);
    const ftmsGotData = await subscribeFTMSData(ftmsSvc);
    if (!gotData) gotData = ftmsGotData;   // CPS already provides power; keep cadence
    await subscribeFTMSControl(ftmsSvc);
    await subscribeMachineStatus(ftmsSvc);
  } catch (_) {}

  if (gotData) {
    trainerLive = true;
    setPill('trainer', true, trainerDevice.name);
    log(`Control path: ${wahooCP ? 'Wahoo' : ftmsCP ? 'FTMS' : 'read-only'}`, 'info');
  } else {
    setPill('trainer', false, 'No data service');
  }
}

async function subscribeCPS(cpsSvc) {
  let gotData = false;
  try {
    const chr = await cpsSvc.getCharacteristic(UUID.CPS_MEASUREMENT);
    chr.addEventListener('characteristicvaluechanged', onCPS);
    await chr.startNotifications();
    log('Subscribed: CPS power', 'ok');
    gotData = true;
  } catch (_) {}
  try {
    const wcp = await cpsSvc.getCharacteristic(WAHOO_CP_UUID);
    wcp.addEventListener('characteristicvaluechanged', onWahooResponse);
    await wcp.startNotifications();
    wahooCP = wcp;
    log('Wahoo proprietary CP ready', 'ok');
  } catch (_) {
    log('No Wahoo CP in CPS service — using FTMS', 'info');
  }
  return gotData;
}

async function subscribeFTMSData(ftmsSvc) {
  try {
    const chr = await ftmsSvc.getCharacteristic(UUID.FTMS_INDOOR);
    chr.addEventListener('characteristicvaluechanged', onFTMSIndoor);
    await chr.startNotifications();
    log('Subscribed: FTMS indoor', 'ok');
    return true;
  } catch (_) { return false; }
}

async function subscribeFTMSControl(ftmsSvc) {
  if (wahooCP) return;
  try {
    const cp = await ftmsSvc.getCharacteristic(UUID.FTMS_CP);
    cp.addEventListener('characteristicvaluechanged', onCPResponse);
    await cp.startNotifications();
    ftmsCP = cp;
    log('FTMS Control Point ready', 'ok');
  } catch (e) { log(`FTMS CP unavailable: ${e.message}`, 'warn'); }
}

async function subscribeMachineStatus(ftmsSvc) {
  try {
    const ms = await ftmsSvc.getCharacteristic(UUID.FTMS_MACHINE_STATUS);
    ms.addEventListener('characteristicvaluechanged', onMachineStatus);
    await ms.startNotifications();
    log('FTMS Machine Status subscribed', 'ok');
  } catch (_) {}   // not critical
}

function onTrainerDisconnected() {
  trainerLive = false;
  wahooCP = null;
  ftmsCP  = null;
  ergHandshakeDone      = false;
  pendingServoPowerSend = false;
  setPill('trainer', false, 'Disconnected');
  log('Trainer disconnected', 'warn');
  updateServoBtn();
}

// ── HR monitor connection ─────────────────────────────────────────────────────

async function connectHR() {
  setPill('hr', false, 'Scanning…');
  let dev;
  try {
    dev = await navigator.bluetooth.requestDevice({
      filters: [{ services: [UUID.HR_SERVICE] }],
      optionalServices: [UUID.HR_SERVICE],
    });
  } catch (_) { setPill('hr', false, 'Cancelled'); return; }

  hrDevice = dev;
  dev.addEventListener('gattserverdisconnected', () => {
    hrLive = false;
    setPill('hr', false, 'Disconnected');
    log('HR monitor disconnected', 'warn');
    updateServoBtn();
  });

  for (let attempt = 1; attempt <= 3; attempt++) {
    setPill('hr', false, `Connecting… (${attempt}/3)`);
    try {
      const server = await dev.gatt.connect();
      const svc    = await server.getPrimaryService(UUID.HR_SERVICE);
      const chr    = await svc.getCharacteristic(UUID.HR_MEASUREMENT);
      chr.addEventListener('characteristicvaluechanged', onHRMeasurement);
      await chr.startNotifications();
      hrLive = true;
      setPill('hr', true, dev.name);
      log(`HR monitor connected: ${dev.name}`, 'ok');
      updateServoBtn();
      return;
    } catch (e) {
      log(`HR connect attempt ${attempt}/3 failed: ${e.message}`, attempt < 3 ? 'warn' : 'err');
      if (attempt < 3) await new Promise(r => setTimeout(r, 1500));
    }
  }
  setPill('hr', false, 'Failed');
  updateServoBtn();
}

// ── Public dispatcher ─────────────────────────────────────────────────────────

function connectDevice(role) {
  if (!navigator.bluetooth) { log('Web Bluetooth not available — use Chrome', 'err'); return; }
  if (role === 'trainer') connectTrainer();
  else                    connectHR();
}

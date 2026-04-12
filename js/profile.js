'use strict';

// ── Profile object ────────────────────────────────────────────────────────────
// Persisted to localStorage between sessions.
const profile = {
  restHR:  50,
  maxHR:   180,
  ftp:     250,
  modelA:  0.35,   // HR = modelA × Power + modelB
  modelB:  60,
};

// HR-Power calibration pairs collected during servo sessions.
// Stored: [{hr, power}]  Session: same format, added this session only.
let hrCharStored  = [];
let hrCharSession = [];

// Stable-setpoint counter for characteristic collection.
let stableCount      = 0;
let prevSetpointSS   = null;

// ── Persistence ───────────────────────────────────────────────────────────────

function saveProfile() {
  readProfileFromDOM();
  localStorage.setItem('erg_profile_v2', JSON.stringify(profile));
  localStorage.setItem('erg_char_v2',    JSON.stringify(hrCharStored));
  const msg = `Profile saved — restHR ${profile.restHR}  maxHR ${profile.maxHR}  FTP ${profile.ftp}W`;
  log(msg, 'ok');
  document.getElementById('prof-status').textContent = 'Saved ✓';
  setTimeout(() => { document.getElementById('prof-status').textContent = ''; }, 2000);
}

function loadProfile() {
  try {
    const saved = localStorage.getItem('erg_profile_v2');
    if (saved) Object.assign(profile, JSON.parse(saved));
    const char = localStorage.getItem('erg_char_v2');
    if (char) hrCharStored = JSON.parse(char);
  } catch (_) {}
  writeProfileToDOM();
  log(`Profile loaded — restHR ${profile.restHR}  maxHR ${profile.maxHR}  FTP ${profile.ftp}W  char ${hrCharStored.length} pts`, 'info');
}

function readProfileFromDOM() {
  profile.restHR  = parseInt(document.getElementById('prof-rest').value)    || profile.restHR;
  profile.maxHR   = parseInt(document.getElementById('prof-max').value)      || profile.maxHR;
  profile.ftp     = parseInt(document.getElementById('prof-ftp').value)      || profile.ftp;
  profile.modelA  = parseFloat(document.getElementById('prof-model-a').value) || profile.modelA;
  profile.modelB  = parseFloat(document.getElementById('prof-model-b').value) || profile.modelB;
}

function writeProfileToDOM() {
  document.getElementById('prof-rest').value    = profile.restHR;
  document.getElementById('prof-max').value     = profile.maxHR;
  document.getElementById('prof-ftp').value     = profile.ftp;
  document.getElementById('prof-model-a').value = profile.modelA;
  document.getElementById('prof-model-b').value = profile.modelB;
}

// ── Feedforward power prediction ──────────────────────────────────────────────
// Returns the estimated watts for a given target HR, using the characteristic
// regression if enough points exist, otherwise the model prior.

function predictPower(targetHR) {
  const fit = fitCharacteristic(hrCharStored);
  if (fit) return Math.round(fit.a * targetHR + fit.b);
  // Model prior: HR = modelA × Power + modelB  →  Power = (HR - modelB) / modelA
  if (profile.modelA > 0) return Math.round((targetHR - profile.modelB) / profile.modelA);
  return null;
}

function predictPowerSource() {
  if (hrCharStored.length >= 4) return `char (${hrCharStored.length} pts)`;
  return `model (${(1 / profile.modelA).toFixed(2)} W/bpm)`;
}

// ── Linear regression ─────────────────────────────────────────────────────────
// Fits Power = a × HR + b to the characteristic points.
// Returns { a, b } or null if fewer than 4 points.

function fitCharacteristic(points) {
  if (points.length < 4) return null;
  const n    = points.length;
  const sumX = points.reduce((s, p) => s + p.hr, 0);
  const sumY = points.reduce((s, p) => s + p.power, 0);
  const sumXY = points.reduce((s, p) => s + p.hr * p.power, 0);
  const sumX2 = points.reduce((s, p) => s + p.hr * p.hr, 0);
  const denom = n * sumX2 - sumX * sumX;
  if (Math.abs(denom) < 1e-6) return null;
  const a = (n * sumXY - sumX * sumY) / denom;
  const b = (sumY - a * sumX) / n;
  return { a, b };
}

// ── Characteristic point collection ──────────────────────────────────────────
// Called each PID tick when the servo is stable.
// Only collects if the actual power is close to the setpoint.

function maybeCollectChar() {
  if (!servoActive || lastHR === null || lastPower === null) return;
  if (Math.abs(lastPower - ergSetpoint) > 15) { stableCount = 0; return; }

  if (ergSetpoint === prevSetpointSS) {
    stableCount++;
  } else {
    stableCount    = 1;
    prevSetpointSS = ergSetpoint;
  }

  if (stableCount >= 2) {
    const pt = { hr: lastHR, power: Math.round((lastPower + ergSetpoint) / 2) };
    hrCharStored.push(pt);
    hrCharSession.push(pt);
    stableCount = 0;   // avoid collecting same point repeatedly
    log(`Char point: ${pt.hr} bpm @ ${pt.power}W  (stable ${stableCount} ticks)`, 'info');
  }
}

// ── Warm-up target calculation ────────────────────────────────────────────────
// Returns the warm-up HR target as 40 %HRR.
function warmupHRTarget() {
  return Math.round(profile.restHR + 0.40 * (profile.maxHR - profile.restHR));
}

// Returns the warm-up power ceiling as 50 %FTP.
function warmupPowerCeil() {
  return Math.round(0.50 * profile.ftp);
}

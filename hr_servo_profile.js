'use strict';

// ══════════════════════════════════════════════════════
//  Athlete profile (localStorage)
// ══════════════════════════════════════════════════════
// modelA, modelB: athlete's linear HR-power relationship  HR = modelA × Power + modelB
// Inverted for feedforward: Power = (targetHR − modelB) / modelA
let profile = { restHR: 43, maxHR: 173, ftp: 290, modelA: 0.35, modelB: 60 };

function loadProfile() {
  try {
    const s = localStorage.getItem('hrservo_profile');
    if (s) {
      Object.assign(profile, JSON.parse(s));
      const savedAt = localStorage.getItem('hrservo_profile_ts');
      if (savedAt) document.getElementById('prof-saved-at').textContent = `saved ${savedAt}`;
    }
  } catch(e) {}
  document.getElementById('prof-rest').value    = profile.restHR;
  document.getElementById('prof-max').value     = profile.maxHR;
  document.getElementById('prof-ftp').value     = profile.ftp;
  document.getElementById('prof-model-a').value = profile.modelA;
  document.getElementById('prof-model-b').value = profile.modelB;
  updateProfileDerived();
  // Set initial HR target to 50% HRR from loaded profile
  const initTarget = Math.round(profile.restHR + 0.50 * (profile.maxHR - profile.restHR));
  setTarget(initTarget);
}

function saveProfile() {
  profile.restHR = parseInt(document.getElementById('prof-rest').value)     || 43;
  profile.maxHR  = parseInt(document.getElementById('prof-max').value)      || 173;
  profile.ftp    = parseInt(document.getElementById('prof-ftp').value)      || 290;
  profile.modelA = parseFloat(document.getElementById('prof-model-a').value) || 0.35;
  profile.modelB = parseFloat(document.getElementById('prof-model-b').value) || 60;
  const ts = new Date().toTimeString().slice(0, 8);
  localStorage.setItem('hrservo_profile', JSON.stringify(profile));
  localStorage.setItem('hrservo_profile_ts', ts);
  document.getElementById('prof-saved-at').textContent = `saved ${ts}`;
  updateProfileDerived();
  // Update HR target to 50% HRR from new profile values
  const newTarget = Math.round(profile.restHR + 0.50 * (profile.maxHR - profile.restHR));
  setTarget(newTarget);
  const modelWpbpm = (1 / profile.modelA).toFixed(2);
  log(`Profile saved — restHR ${profile.restHR}  maxHR ${profile.maxHR}  FTP ${profile.ftp}W  model ${modelWpbpm} W/bpm  →  50%HRR target: ${newTarget} bpm`, 'ok');
}

function hrr() { return profile.maxHR - profile.restHR; }

function updateProfileDerived() {
  // Read live from inputs so the info box updates as you type
  const rest = parseInt(document.getElementById('prof-rest').value) || profile.restHR;
  const max  = parseInt(document.getElementById('prof-max').value)  || profile.maxHR;
  const ftp  = parseInt(document.getElementById('prof-ftp').value)  || profile.ftp;
  const wuTarget = Math.round(rest + 0.40 * (max - rest));
  const wuPMax   = Math.round(0.50 * ftp);
  document.getElementById('wu-info').textContent =
    `40% HRR target: ${wuTarget} bpm  ·  Ceil: ${wuPMax} W  ·  Max 5 W/tick  ·  Floor: 50 W`;
}

// ══════════════════════════════════════════════════════
//  HR vs Power Characteristic (localStorage + session)
// ══════════════════════════════════════════════════════
let hrCharStored  = [];   // all sessions combined, persisted to localStorage
let hrCharSession = [];   // this browser session only

function loadCharacteristic() {
  try {
    const s = localStorage.getItem('hrservo_char');
    if (s) hrCharStored = JSON.parse(s);
  } catch(e) { hrCharStored = []; }
}

function saveCharacteristic() {
  try {
    localStorage.setItem('hrservo_char', JSON.stringify(hrCharStored));
    const ts = new Date().toTimeString().slice(0, 8);
    document.getElementById('char-saved-at').textContent = `auto-saved ${ts}`;
  } catch(e) {}
}

function clearCharacteristic() {
  hrCharStored = []; hrCharSession = [];
  saveCharacteristic();
  drawCharacteristic();
  log('Characteristic data cleared', 'warn');
}

// ── Steady-state collection ───────────────────────────
// Only collect when the setpoint has been stable (≤ 5 W change) for ≥ 2 consecutive
// ticks, giving HR time to settle before we record the (HR, Power) pair.
let stableCount    = 0;
let prevSetpointSS = null;

function maybeCollectChar() {
  if (warmupActive || lastHR === null || lastPower === null) return;

  // Reject if the trainer's actual power is far from the commanded setpoint —
  // the trainer hasn't settled yet (ramp-up/down lag) and the point is noise.
  if (Math.abs(lastPower - ergSetpoint) > 15) { stableCount = 0; return; }

  if (prevSetpointSS !== null && Math.abs(ergSetpoint - prevSetpointSS) <= 5) {
    stableCount++;
  } else {
    stableCount = 0;
  }
  prevSetpointSS = ergSetpoint;

  if (stableCount >= 2) {
    const pt = { hr: lastHR, power: lastPower };
    hrCharSession.push(pt);
    hrCharStored.push(pt);
    if (hrCharStored.length > 600) hrCharStored.shift();
    saveCharacteristic();
    drawCharacteristic();
    log(`Char point: ${lastHR} bpm @ ${lastPower}W  (stable ${stableCount} ticks)`, 'info');
  }
}

// ── Linear regression  Power = a·HR + b ──────────────
function fitChar(points) {
  if (points.length < 4) return null;
  let n = points.length, sx = 0, sy = 0, sxy = 0, sx2 = 0;
  for (const {hr, power} of points) {
    sx += hr; sy += power; sxy += hr * power; sx2 += hr * hr;
  }
  const d = n * sx2 - sx * sx;
  if (Math.abs(d) < 1e-9) return null;
  const a = (n * sxy - sx * sy) / d;
  const b = (sy - a * sx) / n;
  return { a, b };
}

// Feedforward: predict watts for a given target HR.
// Priority: session regression (6+ pts) → stored regression (4+ pts) → linear model prior.
function predictPower(targetHR) {
  const src = hrCharSession.length >= 6 ? hrCharSession : hrCharStored;
  const fit = fitChar(src);
  if (fit) return Math.round(fit.a * targetHR + fit.b);
  // Fall back to athlete's known linear model: HR = modelA × Power + modelB
  const { modelA, modelB } = profile;
  if (modelA > 0) return Math.round((targetHR - modelB) / modelA);
  return null;
}

// Describe the feedforward source for logging.
function predictPowerSource() {
  const src = hrCharSession.length >= 6 ? hrCharSession : hrCharStored;
  if (fitChar(src)) return `char (${src.length} pts)`;
  return `model (${(1 / profile.modelA).toFixed(2)} W/bpm)`;
}
